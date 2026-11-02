"""Read-only host scheduling and review advice; never dispatches or approves work.

Recorded running states/leases are supplied by the host, not remote-job discovery.
The host must separately enforce workflow approvals and provider authorization.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
from pathlib import Path

RESOURCES = ("image", "lux", "cpu", "gpu", "import")
ID = re.compile(r"[a-zA-Z0-9][a-zA-Z0-9_.-]{0,95}\Z")
HASH = re.compile(r"[0-9a-f]{64}\Z")
VISUAL_TIERS = ("blocker", "composition", "style", "polish")


class WorkgraphError(ValueError):
    pass


def _require(condition, message):
    if not condition:
        raise WorkgraphError(message)


def _number(value, positive=False):
    return (not isinstance(value, bool) and isinstance(value, (int, float))
            and math.isfinite(value) and (value > 0 if positive else value >= 0))


def _id(value):
    return isinstance(value, str) and ID.fullmatch(value) is not None


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                    allow_nan=False).encode()).hexdigest()


def _file_hash(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _path(value, project):
    _require(isinstance(value, str) and value.strip(), "File/directory path is required")
    p = Path(value)
    p = (p if p.is_absolute() else project / p).resolve()
    _require(p != project and project in p.parents, "Path escapes project or owns project root: " + value)
    return p


def _within(path, directory):
    return path == directory or directory in path.parents


def _overlap(a, b):
    return _within(a, b) or _within(b, a)


def _read(path, project):
    p = _path(str(path), project)
    _require(p.is_file(), "JSON file does not exist: " + str(path))
    return json.loads(p.read_text(encoding="utf-8"))


def _receipt(item, project):
    _require(isinstance(item, dict), "File receipt must be an object")
    path = _path(item.get("path"), project)
    _require(isinstance(item.get("sha256"), str) and HASH.fullmatch(item["sha256"]),
             "File receipt requires a lowercase SHA-256: " + str(item.get("path")))
    return path, item["sha256"]


def _check_receipt(item, project):
    p, expected = _receipt(item, project)
    return p.is_file() and _file_hash(p) == expected


def task_fingerprint(task):
    """Hash frozen task specification; execution observations do not alter it."""
    return _digest({k: v for k, v in task.items()
                    if k not in {"state", "completion", "blocker_note"}})


def inspect_workgraph(path, project):
    """Validate a DAG and recommend one resource-budgeted, nonconflicting wave.

    No files are written. A completed task must bind its frozen spec, dependency
    completion fingerprints, real output hashes and evidence of stated criteria.
    Returned fingerprints help the host record receipts; they are not approval.
    """
    project = Path(project).resolve()
    _require(project.is_dir(), "Project directory does not exist")
    data = _read(path, project)
    _require(isinstance(data, dict) and data.get("schema") == 1 and data.get("kind") == "greybox-workgraph",
             "Expected greybox-workgraph schema 1")
    _require(_id(data.get("integrator")), "A stable designated integrator ID is required")
    caps = data.get("resource_caps", {})
    _require(set(caps) == set(RESOURCES), "Set independent image/lux/cpu/gpu/import resource caps")
    _require(all(type(v) is int and v > 0 for v in caps.values()), "Resource caps must be positive integers")
    tasks = data.get("tasks")
    _require(isinstance(tasks, list) and tasks, "Workgraph must contain tasks")
    index, dirs, outputs = {}, {}, {}
    for task in tasks:
        _require(isinstance(task, dict) and _id(task.get("id")), "Every task requires a stable ID")
        tid = task["id"]
        _require(tid not in index, "Duplicate task ID: " + tid)
        index[tid] = task
        _require(all(_id(task.get(k)) for k in ("owner", "style", "assembly")),
                 tid + ": owner/style/assembly IDs are required (use shared where applicable)")
        _require(task.get("kind") in ("work", "publish"), tid + ": kind must be work or publish")
        _require(task.get("state") in ("pending", "running", "completed", "blocked"), tid + ": invalid state")
        _require(_number(task.get("estimate_minutes"), positive=True), tid + ": positive estimate_minutes required")
        priority = task.get("visual_priority")
        if priority is not None:
            _require(isinstance(priority, dict) and priority.get("tier") in VISUAL_TIERS
                     and isinstance(priority.get("rationale"), str) and priority["rationale"].strip(),
                     tid + ": visual_priority needs a tier and concrete rationale")
        unit = task.get("work_unit")
        if unit is not None:
            _require(isinstance(unit, dict) and all(isinstance(unit.get(k), str) and unit[k].strip()
                     for k in ("observable_result", "stop_condition"))
                     and _number(unit.get("active_minutes_budget"), positive=True),
                     tid + ": work_unit needs an observable result, stop condition and active-work budget")
        if data.get("scheduling_policy") == "visual-completeness-v1":
            _require(priority is not None and unit is not None,
                     tid + ": visual-completeness-v1 requires visual_priority and work_unit")
        deps = task.get("depends_on")
        _require(isinstance(deps, list) and all(_id(d) for d in deps) and len(deps) == len(set(deps)),
                 tid + ": depends_on must contain unique task IDs")
        resources = task.get("resources", {})
        _require(isinstance(resources, dict) and resources and set(resources).issubset(caps), tid + ": invalid resources")
        _require(all(type(v) is int and 0 <= v <= caps[k] for k, v in resources.items())
                 and any(resources.values()), tid + ": resource use must fit caps and reserve at least one slot")
        locks = task.get("exclusive_locks", [])
        _require(isinstance(locks, list) and all(_id(lock) for lock in locks)
                 and len(set(locks)) == len(locks), tid + ": invalid exclusive_locks")
        if task["kind"] == "publish":
            _require(task["owner"] == data["integrator"] and "publication" in locks,
                     tid + ": only the designated integrator may publish under the publication lock")
        raw_dirs = task.get("allowed_output_dirs", [])
        _require(isinstance(raw_dirs, list) and raw_dirs, tid + ": explicit allowed_output_dirs required")
        dirs[tid] = [_path(p, project) for p in raw_dirs]
        _require(len(set(dirs[tid])) == len(dirs[tid]), tid + ": duplicate output directories")
        for i, directory in enumerate(dirs[tid]):
            _require(not any(_overlap(directory, other) for other in dirs[tid][i+1:]), tid + ": redundant output scopes")
        raw_outputs = task.get("outputs", [])
        _require(isinstance(raw_outputs, list) and raw_outputs, tid + ": explicit output files required")
        outputs[tid] = [_path(p, project) for p in raw_outputs]
        _require(len(set(outputs[tid])) == len(outputs[tid]), tid + ": duplicate outputs")
        _require(not any(_overlap(a, b) for i, a in enumerate(outputs[tid]) for b in outputs[tid][i+1:]),
                 tid + ": declared file outputs cannot contain one another")
        _require(all(any(_within(p, directory) and p != directory for directory in dirs[tid])
                     for p in outputs[tid]), tid + ": output outside owned directories")
        inputs = task.get("inputs")
        _require(isinstance(inputs, list) and inputs, tid + ": frozen input file/hash receipts required")
        input_paths = [_receipt(item, project)[0] for item in inputs]
        _require(len(set(input_paths)) == len(input_paths), tid + ": duplicate input paths")
        _require(not any(_within(p, directory) for p in input_paths for directory in dirs[tid]),
                 tid + ": output scope may not contain a frozen input")
        criteria = task.get("acceptance_criteria", [])
        _require(isinstance(criteria, list) and criteria and all(isinstance(c, dict) and _id(c.get("id"))
                 and isinstance(c.get("description"), str) and c["description"].strip() for c in criteria),
                 tid + ": named acceptance criteria required")
        _require(len({c["id"] for c in criteria}) == len(criteria), tid + ": duplicate criterion IDs")
        if task["state"] == "blocked":
            _require(task.get("blocker_note"), tid + ": blocked state requires blocker_note")
    _require(data.get("scheduling_policy") in (None, "visual-completeness-v1"), "Unknown scheduling policy")
    _require(data.get("largest_visual_gap") is None or data["largest_visual_gap"] in index,
             "Largest visual gap must reference a known task")
    observations = data.get("observations", {})
    _require(isinstance(observations, dict) and set(observations).issubset(index),
             "Observations must reference known tasks")
    for tid, observation in observations.items():
        _require(isinstance(observation, dict), tid + ": observation must be an object")
        for key in ("ready_wait_rounds", "no_progress_rounds"):
            _require(type(observation.get(key, 0)) is int and observation.get(key, 0) >= 0,
                     tid + ": observation " + key + " must be a nonnegative integer")
        _require(_number(observation.get("active_minutes", 0))
                 and _number(observation.get("external_wait_minutes", 0)),
                 tid + ": active work and external wait must be nonnegative and separate")
        _require(observation.get("submission_state") in (None, "submitting", "unknown", "recovery_required", "known"),
                 tid + ": invalid submission observation")
    for tid, task in index.items():
        _require(set(task["depends_on"]).issubset(index) and tid not in task["depends_on"], tid + ": unknown/self dependency")
        for other in index:
            if tid < other:
                _require(not any(_overlap(a, b) for a in dirs[tid] for b in dirs[other]),
                         "Output ownership collision: " + tid + " / " + other)
    order, visiting, visited = [], set(), set()

    def visit(tid):
        _require(tid not in visiting, "Dependency cycle at " + tid)
        if tid in visited:
            return
        visiting.add(tid)
        for dep in index[tid]["depends_on"]:
            visit(dep)
        visiting.remove(tid)
        visited.add(tid)
        order.append(tid)

    for tid in sorted(index):
        visit(tid)
    ancestors = {}
    for tid in order:
        ancestors[tid] = set(index[tid]["depends_on"])
        for dep in index[tid]["depends_on"]:
            ancestors[tid].update(ancestors[dep])
        for item in index[tid]["inputs"]:
            input_path = _path(item["path"], project)
            producers = [other for other in index if any(_within(input_path, directory) for directory in dirs[other])]
            _require(all(input_path in outputs[other] for other in producers),
                     tid + ": another task's internal file is not a declared output interface")
            _require(all(other in ancestors[tid] for other in producers), tid + ": produced input missing dependency")
    leases = data.get("leases", [])
    _require(isinstance(leases, list), "leases must be an array")
    leased = {}
    for lease in leases:
        _require(isinstance(lease, dict) and lease.get("task_id") in index, "Lease references unknown task")
        tid = lease["task_id"]
        _require(tid not in leased and lease.get("owner") == index[tid]["owner"], "Duplicate/wrong-owner lease: " + tid)
        _require(index[tid]["state"] == "running", "Lease must describe a recorded running task: " + tid)
        leased[tid] = lease
    _require(set(leased) == {tid for tid, task in index.items() if task["state"] == "running"},
             "Every recorded running task requires exactly one owner lease")
    used = {key: 0 for key in caps}
    held_locks = set()
    for tid in leased:
        task = index[tid]
        _require(not held_locks.intersection(task.get("exclusive_locks", [])), "Recorded leases conflict on exclusive lock")
        held_locks.update(task.get("exclusive_locks", []))
        for key, value in task["resources"].items():
            used[key] += value
    _require(all(used[key] <= caps[key] for key in caps), "Recorded running work exceeds resource caps")
    states, reasons, completion_hashes, specs = {}, {}, {}, {}
    for tid in order:
        task = index[tid]
        specs[tid] = task_fingerprint(task)
        why = []
        awaiting_inputs = False
        for item in task["inputs"]:
            input_path, _ = _receipt(item, project)
            if _check_receipt(item, project):
                continue
            producer = next((other for other in ancestors[tid] if input_path in outputs[other]), None)
            if (not input_path.exists() and producer is not None and states[producer] != "completed"
                    and task["state"] != "completed"):
                awaiting_inputs = True
            else:
                why.append("frozen_input_missing_or_changed")
        deps = task["depends_on"]
        if any(states[d] == "stale" for d in deps):
            why.append("upstream_stale")
        if task["state"] == "completed":
            receipt = task.get("completion", {})
            if receipt.get("spec_sha256") != specs[tid]:
                why.append("completion_spec_missing_or_changed")
            expected_deps = {d: completion_hashes.get(d) for d in deps}
            if any(states[d] != "completed" for d in deps) or receipt.get("dependency_sha256") != expected_deps:
                why.append("completion_dependency_missing_or_changed")
            delivered = receipt.get("outputs", [])
            if (not isinstance(delivered, list) or not delivered
                    or len(delivered) != len(outputs[tid])
                    or {_receipt(item, project)[0] for item in delivered} != set(outputs[tid])
                    or any(not _check_receipt(item, project) for item in delivered)):
                why.append("completion_outputs_missing_or_changed")
            required = {c["id"] for c in task["acceptance_criteria"]}
            passed = receipt.get("criteria_passed", [])
            evidence = receipt.get("evidence", [])
            if (not isinstance(passed, list) or len(passed) != len(required) or set(passed) != required
                    or not isinstance(evidence, list) or not evidence
                    or any(not _check_receipt(item, project) for item in evidence)):
                why.append("completion_criteria_or_evidence_missing")
            if not why:
                completion_hashes[tid] = _digest({"spec_sha256": specs[tid], "receipt": receipt})
        if why:
            states[tid] = "stale"
        elif observations.get(tid, {}).get("submission_state") in ("submitting", "unknown", "recovery_required"):
            states[tid] = "reconciliation_required"
            why.append("reconcile_original_submission_before_reissue_or_vendor_change")
        elif task["state"] == "blocked":
            states[tid] = "blocked"
            why.append(task["blocker_note"])
        elif task["state"] == "completed":
            states[tid] = "completed"
        elif awaiting_inputs or any(states[d] != "completed" for d in deps):
            states[tid] = "waiting"
            why.append("awaiting_declared_upstream_output" if awaiting_inputs else "dependencies_not_completed")
        elif task["state"] == "running":
            states[tid] = "running"
        else:
            states[tid] = "ready"
        reasons[tid] = why
    control = None
    if data.get("production_control"):
        from .production_control import assess
        control = assess(project, _path(data["production_control"], project))
        for tid, task in index.items():
            if states[tid] != "ready":
                continue
            asset_ids = task.get("asset_ids", [])
            _require(isinstance(asset_ids, list) and all(_id(a) for a in asset_ids), "Task asset_ids must be stable IDs")
            blockers = []
            action = task.get("control_action", "produce")
            _require(action in {"produce", "integrate", "repair", "prepare"}, "Unknown task control_action")
            if action in {"produce", "integrate"} and task["style"] != "shared" and task["style"] not in control["active_styles"]:
                blockers.append("style_queued_until_lead_sample")
            if action == "produce":
                for aid in asset_ids:
                    blockers.extend(control["asset_blockers"].get(aid, []))
            if blockers:
                states[tid] = "blocked"
                reasons[tid].extend(sorted(set(blockers)))
    children = {tid: [] for tid in index}
    for tid, task in index.items():
        for dep in task["depends_on"]:
            children[dep].append(tid)
    critical = {}
    for tid in reversed(order):
        critical[tid] = index[tid]["estimate_minutes"] + max((critical[c] for c in children[tid]
                                                            if states[c] != "completed"), default=0)
    priorities = {tid: VISUAL_TIERS.index(task.get("visual_priority", {}).get("tier", "style"))
                  for tid, task in index.items()}
    # A declared dependency needed by the first complete sample inherits its
    # consumer's urgency. Aging never crosses a visual/necessary-work tier.
    for tid in reversed(order):
        if states[tid] != "completed":
            for dep in index[tid]["depends_on"]:
                priorities[dep] = min(priorities[dep], priorities[tid])
    reminders = {}
    for tid, observation in observations.items():
        if states[tid] == "completed":
            continue
        budget = index[tid].get("work_unit", {}).get("active_minutes_budget", 25)
        triggers = []
        if observation.get("active_minutes", 0) >= budget:
            triggers.append("active_work_budget_reached")
        if observation.get("no_progress_rounds", 0) >= 2:
            triggers.append("two_rounds_without_progress")
        if triggers:
            reminders[tid] = {"triggers": triggers, "action": "reassess_at_safe_boundary",
                "note": "Check the largest visual gap and reorder or change method. Continue a necessary blocker with demonstrated progress and a reason. Do not interrupt a tool, infer approval, pass a defect or retry an unknown submission."}
    candidates = sorted((tid for tid in index if states[tid] == "ready"), key=lambda tid: (
        priorities[tid], observations.get(tid, {}).get("no_progress_rounds", 0) >= 2,
        -observations.get(tid, {}).get("ready_wait_rounds", 0), -critical[tid], -len(children[tid]), tid))
    wave, deferred = [], {}
    for tid in candidates:
        task = index[tid]
        if held_locks.intersection(task.get("exclusive_locks", [])):
            deferred[tid] = "exclusive_lock_held"
        elif any(used[key] + value > caps[key] for key, value in task["resources"].items()):
            deferred[tid] = "resource_capacity"
        else:
            wave.append(tid)
            held_locks.update(task.get("exclusive_locks", []))
            for key, value in task["resources"].items():
                used[key] += value
    return {"ok": True, "kind": "host_scheduling_advice", "states": states, "reasons": reasons,
            "recommended_wave": wave, "deferred_ready": deferred, "resource_use_with_wave": used,
            "task_spec_sha256": specs, "completion_sha256": completion_hashes,
            "critical_path_estimate_minutes": critical, "integrator": data["integrator"],
            "effective_visual_tiers": {tid: VISUAL_TIERS[value] for tid, value in priorities.items()},
            "ready_order": candidates, "work_unit_reminders": reminders,
            "unclassified_tasks": [tid for tid, task in index.items() if "visual_priority" not in task],
            "production_control": control,
            "limits": "Read-only planning aid. Completion checks receipt integrity, not criterion truth or artistic acceptance. Leases are host records, not verified live jobs. No task is dispatched; workflow approval and paid authorization remain separate."}


def evaluate_review(data, project):
    """Recommend bounded review action without granting artistic acceptance."""
    project = Path(project).resolve()
    _require(isinstance(data, dict) and data.get("schema") == 1 and data.get("kind") == "greybox-review-budget",
             "Expected greybox-review-budget schema 1")
    budget = data.get("budget", {})
    for key in ("max_rounds", "max_minutes", "max_no_progress_rounds"):
        _require(_number(budget.get(key), positive=True), "Positive review budget required: " + key)
    _require(_number(budget.get("max_calls")), "max_calls must be nonnegative; zero permits local review without calls")
    _require(type(budget["max_rounds"]) is int and type(budget["max_calls"]) is int
             and type(budget["max_no_progress_rounds"]) is int, "Round/call limits must be integers")
    issues = data.get("issues", [])
    _require(isinstance(issues, list), "issues must be an array")
    issue_ids = set()
    for issue in issues:
        _require(isinstance(issue, dict) and _id(issue.get("id")) and issue["id"] not in issue_ids,
                 "Issues need unique stable IDs")
        issue_ids.add(issue["id"])
        _require(issue.get("severity") in ("blocking", "polish")
                 and issue.get("state") in ("open", "resolved"), "Issue needs severity and state")
        _require(isinstance(issue.get("description"), str) and issue["description"].strip(), "Issue description required")
        if issue["state"] == "resolved":
            evidence = issue.get("evidence", [])
            _require(isinstance(evidence, list) and evidence and all(_check_receipt(e, project) for e in evidence),
                     "Resolved issue requires current evidence: " + issue["id"])
    rounds = data.get("rounds", [])
    _require(isinstance(rounds, list), "rounds must be an array")
    blockers = [i["id"] for i in issues if i["severity"] == "blocking" and i["state"] == "open"]
    polish = [i["id"] for i in issues if i["severity"] == "polish" and i["state"] == "open"]
    focus = set(blockers or polish)
    elapsed, calls, stagnant = 0, 0, 0
    round_ids = set()
    hypotheses = set()
    last_progress = last_hypothesis_new = False
    for round_ in rounds:
        _require(isinstance(round_, dict) and _id(round_.get("id")) and round_["id"] not in round_ids,
                 "Review rounds need unique stable IDs")
        round_ids.add(round_["id"])
        _require(_number(round_.get("minutes")) and type(round_.get("calls")) is int and round_["calls"] >= 0,
                 "Each round must record nonnegative actual minutes and calls")
        elapsed += round_["minutes"]
        calls += round_["calls"]
        improvements = round_.get("improvements", [])
        _require(isinstance(improvements, list), "improvements must be an array")
        for improvement in improvements:
            _require(isinstance(improvement, dict) and improvement.get("issue_id") in issue_ids,
                     "Improvement must reference a tracked issue")
            before, after = improvement.get("before", {}), improvement.get("after", {})
            _require(_check_receipt(before, project) and _check_receipt(after, project), "Improvement requires real before/after evidence")
            _require(before["sha256"] != after["sha256"], "Identical evidence is not improvement")
            if improvement.get("mode", "measured") == "observed":
                _require(_id(improvement.get("reviewer")) and all(isinstance(improvement.get(k), str)
                         and improvement[k].strip() for k in ("criterion", "observation")),
                         "Observed improvement needs reviewer, criterion and a concrete before/after observation")
            else:
                _require(improvement.get("mode", "measured") == "measured", "Unknown improvement mode")
                a, b = before.get("metric"), after.get("metric")
                _require(_number(a) and _number(b), "Measured improvement needs nonnegative metrics; use observed mode for art review")
                _require((improvement.get("direction") == "increase" and b > a)
                         or (improvement.get("direction") == "decrease" and b < a), "Claimed improvement must improve the stated metric")
        last_progress = any(i["issue_id"] in focus for i in improvements)
        stagnant = 0 if last_progress else stagnant + 1
        last_hypothesis_new = False
        hypothesis = round_.get("next_hypothesis")
        if hypothesis is not None:
            _require(isinstance(hypothesis, dict) and isinstance(hypothesis.get("change"), str)
                     and hypothesis["change"].strip() and isinstance(hypothesis.get("issue_ids"), list)
                     and hypothesis["issue_ids"] and set(hypothesis["issue_ids"]).issubset(issue_ids),
                     "A new hypothesis must name a changed method and tracked issue IDs")
            key = (tuple(sorted(hypothesis["issue_ids"])), " ".join(hypothesis["change"].lower().split()))
            last_hypothesis_new = key not in hypotheses and bool(focus.intersection(hypothesis["issue_ids"]))
            hypotheses.add(key)
    exhausted = [key for key, used in (("max_rounds", len(rounds)), ("max_minutes", elapsed), ("max_calls", calls))
                 if used >= budget[key] and not (key == "max_calls" and budget[key] == 0 and used == 0)]
    no_progress = stagnant >= budget["max_no_progress_rounds"]
    if not blockers and not polish:
        action = "ready_for_user_review"
    elif exhausted or no_progress:
        action = "change_method_or_escalate_blockers" if blockers else "stop_polish_and_present"
    elif not rounds:
        action = "plan_first_bounded_iteration"
    elif not last_progress and not last_hypothesis_new:
        action = "require_new_hypothesis_before_iteration"
    else:
        action = "continue_within_existing_scope_and_budget"
    return {"ok": True, "recommendation": action, "unresolved_blockers": blockers,
            "unresolved_polish": polish, "consumed": {"rounds": len(rounds), "minutes": elapsed, "calls": calls},
            "exhausted": exhausted, "consecutive_no_progress_rounds": stagnant,
            "no_progress_focus": sorted(focus), "latest_hypothesis_is_new": last_hypothesis_new,
            "no_progress_triggered": no_progress, "remaining_calls": max(0, budget["max_calls"] - calls),
            "calls_allowed": calls < budget["max_calls"], "accepted": False, "paid_retry_authorized": False,
            "limits": "Review advice only. Metrics/observations and evidence record a host claim, not artistic proof. calls_allowed is remaining budget, not provider authorization. Unresolved blockers remain blockers; no user approval or provider retry is inferred."}


def inspect_review(path, project):
    project = Path(project).resolve()
    _require(project.is_dir(), "Project directory does not exist")
    return evaluate_review(_read(path, project), project)
