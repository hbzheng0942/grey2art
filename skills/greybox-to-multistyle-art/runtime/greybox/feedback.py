"""Evidence-bound usage observations and derived recaps; never execution authority.

PROGRESS is the index. Immutable observations are evidence, CONTROL retains asset
repair ownership, and the two current recap files are disposable derived views.
No provider, engine, model or external upload is invoked here.
"""
from __future__ import annotations

import copy
import hashlib
import json
import math
import os
from pathlib import Path
import re
import tempfile

from . import VERSION, core

KINDS = {"failure", "intervention", "attempt", "resolution", "reopen", "regression"}
PROJECT_STATES = {"open", "workaround", "fixed", "deferred"}
SKILL_STATES = {"untriaged", "candidate", "verified", "not_applicable"}
INTERVENTIONS = {"rescue", "creative_decision", "scope_change", "unclear"}
TRIAGE_CATEGORIES = {"skill_guidance", "agent_execution", "host_tool", "provider", "source_project", "unknown"}
TRIAGE_SEVERITIES = {"blocker", "major", "minor", "unknown"}
FIELDS = {"schema", "kind", "event_id", "issue_id", "type", "stage", "summary", "source_ref", "basis",
          "expected", "actual", "context", "mechanisms", "evidence", "intervention", "method", "next_test",
          "project_status", "skill_status", "regression", "costs", "triage"}
METRICS = {"active_seconds", "elapsed_seconds", "input_tokens", "cached_input_tokens", "output_tokens", "actual_cost"}
LIMITS = "Recorded observations and declared outcomes, not authenticated visual judgment, human acceptance or execution authority."
COVERAGE = "Only recorded observations and declared source records; missing data is unknown, not zero incidents or zero cost."
SUMMARY_ISSUES = 12
SUMMARY_EVENTS = 3


def _text(value, limit=4000):
    return isinstance(value, str) and bool(value.strip()) and len(value) <= limit


def _path(project, value):
    core.require(isinstance(value, (str, Path)) and str(value).strip(), "Project-contained path required")
    path = core.resolve_input(value, project)
    core.require(path != project and core.inside(path, project), "Path escapes project or owns root")
    return path


def _case(project, case_dir):
    project = Path(project).resolve()
    case = _path(project, case_dir)
    core.require((case / "PLAN.json").is_file(), "Existing case PLAN required; feedback does not create a production task")
    return project, case


def _local(case, project, suffix):
    path = _path(project, case / suffix)
    core.require(core.inside(path, case), "Feedback path escapes case")
    return path


def _receipt(project, value, verify=True, hashes=None):
    core.require(isinstance(value, dict) and set(value) == {"path", "sha256"}, "Evidence needs path/hash only")
    core.require(isinstance(value["sha256"], str) and re.fullmatch(r"[a-f0-9]{64}", value["sha256"]), "Invalid evidence hash")
    path = _path(project, value["path"])
    if verify:
        core.require(path.is_file(), "Evidence missing or stale: " + str(value["path"]))
        if hashes is None:
            actual = core.file_hash(path)
        else:
            if path not in hashes:
                hashes[path] = core.file_hash(path)
            actual = hashes[path]
        core.require(actual == value["sha256"], "Evidence missing or stale: " + str(value["path"]))
    return {"path": path.relative_to(project).as_posix(), "sha256": value["sha256"]}


def validate_observation(project, value, verify_evidence=True):
    """Normalize bounded input without inventing causes, measurements or identity."""
    project = Path(project).resolve()
    core.require(isinstance(value, dict) and set(value) <= FIELDS, "Unexpected usage observation fields")
    core.require(type(value.get("schema")) is int and value["schema"] == 1 and value.get("kind") == "greybox-usage-observation", "Expected greybox-usage-observation schema 1")
    core.require(all(core.safe_id(value.get(k)) for k in ("event_id", "issue_id")), "Stable event_id and issue_id required")
    core.require(value.get("type") in KINDS, "Invalid observation type")
    core.require(value.get("basis") in {"observed", "user_reported", "agent_inferred"}, "Declare observation basis")
    core.require(all(_text(value.get(k)) for k in ("stage", "summary", "source_ref")), "Stage, summary and actual source_ref required")
    core.require(not any(value[k].startswith("REPLACE-") for k in ("event_id", "issue_id", "stage", "source_ref")),
                 "Complete the feedback template with actual identities and source references")
    for key in ("expected", "actual", "method", "next_test"):
        core.require(value.get(key) is None or _text(value[key]), key + " must be concise text or null")
    if value["type"] == "failure":
        core.require(_text(value.get("expected")) and _text(value.get("actual")), "Failure needs expected and actual observations")
    result = copy.deepcopy(value)
    context = result.get("context", {})
    core.require(isinstance(context, dict) and set(context) <= {"host", "model", "engine", "session_ref"}, "Invalid context fields")
    core.require(all(v is None or _text(v, 500) for v in context.values()), "Context values are observed text or null")
    result["context"] = {k: context.get(k) for k in ("host", "model", "engine", "session_ref")}
    tags = result.get("mechanisms", [])
    core.require(isinstance(tags, list) and len(tags) <= 24 and all(core.safe_id(x) for x in tags)
                 and len(set(tags)) == len(tags), "Mechanisms need unique short IDs")
    result["mechanisms"] = sorted(tags)
    # Do not add a field to historical observations: their normalized bytes are
    # already hash-bound. Explicit triage is a sourced report, not a diagnosis.
    if "triage" in result:
        triage = result["triage"]
        core.require(isinstance(triage, dict) and set(triage) <= {"category", "severity", "fingerprint"},
                     "Invalid triage fields")
        core.require(isinstance(triage.get("category", "unknown"), str)
                     and triage.get("category", "unknown") in TRIAGE_CATEGORIES, "Invalid triage category")
        core.require(isinstance(triage.get("severity", "unknown"), str)
                     and triage.get("severity", "unknown") in TRIAGE_SEVERITIES, "Invalid triage severity")
        core.require(triage.get("fingerprint") is None or core.safe_id(triage["fingerprint"]), "Invalid triage fingerprint")
        result["triage"] = {"category": triage.get("category", "unknown"),
                            "severity": triage.get("severity", "unknown"), "fingerprint": triage.get("fingerprint")}
    receipts = result.get("evidence", [])
    core.require(isinstance(receipts, list) and len(receipts) <= 16, "Evidence must be a bounded receipt list")
    result["evidence"] = [_receipt(project, r, verify_evidence) for r in receipts]
    intervention = result.get("intervention")
    if intervention is not None:
        core.require(isinstance(intervention, dict) and set(intervention) == {"episode_id", "kind"}
                     and core.safe_id(intervention["episode_id"]) and intervention["kind"] in INTERVENTIONS,
                     "Intervention needs stable episode_id and kind")
    if result["type"] == "intervention":
        core.require(intervention is not None, "Intervention event needs an episode")
    if "project_status" in result:
        core.require(result["project_status"] in PROJECT_STATES, "Invalid project_status")
    if "skill_status" in result:
        core.require(result["skill_status"] in SKILL_STATES, "Invalid skill_status")
    if result.get("project_status") == "fixed":
        core.require(bool(result["evidence"]), "Fixed project outcome needs evidence")
    regression = result.get("regression")
    if regression is not None:
        core.require(isinstance(regression, dict) and set(regression) == {"before", "after", "holdout"},
                     "Regression needs before/after/holdout receipts")
        result["regression"] = {k: _receipt(project, v, verify_evidence) for k, v in regression.items()}
        core.require(len({r["path"] for r in result["regression"].values()}) == 3
                     and len({r["sha256"] for r in result["regression"].values()}) == 3,
                     "Regression receipts must have distinct paths and contents")
    if result.get("skill_status") == "verified":
        core.require(result["type"] == "regression" and regression is not None,
                     "Verified Skill outcome needs a regression event and before/after/holdout evidence")
    costs = result.get("costs")
    if costs is not None:
        core.require(isinstance(costs, dict) and set(costs) <= METRICS | {"measurement_id", "scope", "source_ref", "currency"}
                     and core.safe_id(costs.get("measurement_id")) and _text(costs.get("scope"))
                     and _text(costs.get("source_ref")), "Costs need stable measurement_id, scope and source_ref")
        for key in METRICS:
            number = costs.get(key)
            core.require(number is None or (type(number) in (int, float) and math.isfinite(number) and number >= 0
                         and ("tokens" not in key or type(number) is int)), "Invalid measured " + key)
        core.require(costs.get("currency") is None or _text(costs["currency"], 32), "Currency must be text or null")
        core.require(costs.get("actual_cost") is None or _text(costs.get("currency"), 32), "Actual cost needs currency/unit")
        result["costs"] = {**costs, **{k: costs.get(k) for k in sorted(METRICS)}, "currency": costs.get("currency")}
    core.require(len(json.dumps(result, ensure_ascii=False, allow_nan=False).encode()) <= 32768, "Observation exceeds 32 KiB")
    return result


def _progress(case):
    from . import continuity
    core.require(not (case / ".progress-transaction.json").exists(), "Interrupted progress transaction; recover before recap")
    plan = core.read(case / "PLAN.json")
    core.require(isinstance(plan, dict) and plan.get("kind") == "greybox-case-plan" and core.safe_id(plan.get("case_id")),
                 "Expected an existing case plan")
    continuity._verify_progress(case, plan)
    rows = [json.loads(line) for line in (case / "PROGRESS.jsonl").read_text(encoding="utf-8").splitlines()]
    return plan, rows


def record(project, case_dir, observation, writer, expected_revision, checkpoint_sha256):
    """Append a sourced milestone once. Orphan files are not reportable events."""
    from . import continuity
    project, case = _case(project, case_dir)
    if (case / ".progress-transaction.json").exists():
        continuity.recover(project, case, writer)
    with core.locked(case):
        plan, rows = _progress(case)
    core.require(plan["writer"] == writer, "Only the designated plan writer may record feedback")
    normalized = validate_observation(project, observation, verify_evidence=False)
    path = _local(case, project, "feedback/observations/" + normalized["event_id"] + ".json")
    relative = path.relative_to(project).as_posix()
    matches = [r for r in rows if any(e.get("path") == relative for e in r.get("evidence", []))]
    if matches:
        envelope = core.read(path)
        core.require(isinstance(envelope, dict) and envelope.get("observation_sha256") == core.digest(normalized)
                     and core.digest(envelope.get("observation")) == core.digest(normalized), "Event ID already has different observation")
        core.require(all(any(e.get("path") == relative and e.get("sha256") == core.file_hash(path)
                             for e in r.get("evidence", [])) for r in matches), "Recorded observation changed")
        return {"ok": True, "reused": True, "event_id": normalized["event_id"], "issue_id": normalized["issue_id"],
                "revision": plan["revision"], "event_seq": matches[0]["seq"], "observation_path": relative}
    normalized = validate_observation(project, observation)
    with core.locked(path.parent):
        if path.exists():
            envelope = core.read(path)
            core.require(isinstance(envelope, dict) and envelope.get("observation_sha256") == core.digest(normalized)
                         and core.digest(envelope.get("observation")) == core.digest(normalized), "Event ID already has different observation")
        else:
            manifest = Path(__file__).resolve().parents[2] / "MANIFEST.json"
            envelope = {"schema": 1, "kind": "greybox-usage-observation-record", "observation": normalized,
                        "observation_sha256": core.digest(normalized), "skill": {"version": VERSION,
                        "manifest_sha256": core.file_hash(manifest) if manifest.is_file() else None,
                        "identity_scope": "Recorder package manifest identity; not a fresh whole-package validation"}}
            core.write(path, envelope)
    event_type = "failure" if normalized["type"] in {"failure", "reopen"} else "review"
    event = {"type": event_type, "summary": normalized["summary"], "source_ref": normalized["source_ref"],
             "scope": "feedback/" + normalized["issue_id"], "evidence": [{"path": relative, "sha256": core.file_hash(path)}]}
    outcome = continuity.record_observation(project, case, writer, expected_revision, checkpoint_sha256, event)
    return {**outcome, "reused": False, "event_id": normalized["event_id"], "issue_id": normalized["issue_id"],
            "observation_path": relative}


def _empty_issue(issue_id):
    return {"issue_id": issue_id, "summary": "Observation requires inspection", "expected": None, "actual": None,
            "project_status": "open", "skill_status": "untriaged", "evidence_current": True,
            "is_defect_candidate": False, "events": [], "mechanisms": [], "context": {}, "evidence": [], "next_test": None,
            "latest_method": None, "triage": {"category": "unknown", "severity": "unknown", "fingerprint": None}}


def _unresolved(issue):
    return (issue["evidence_current"] is False or (issue["is_defect_candidate"]
            and (issue["project_status"] != "fixed" or issue["skill_status"] not in {"verified", "not_applicable"})))


def _repairs(project, plan, sources, warnings, verify_artifacts=True, hashes=None):
    ref = plan.get("references", {}).get("production_control")
    if not ref:
        conventional = "art/" + plan["case_id"] + "/shared/production/CONTROL.json"
        if _path(project, conventional).exists():
            ref = conventional
    if not ref:
        return []
    try:
        path = _path(project, ref)
        data = core.read(path)
        core.require(isinstance(data, dict) and isinstance(data.get("repairs"), dict), "CONTROL repairs must be an object")
        core.require(data.get("case_id") == plan["case_id"], "CONTROL belongs to another case")
        sources.append({"path": path.relative_to(project).as_posix(), "sha256": core.file_hash(path), "role": "production_control"})
        result = []
        for key, repair in sorted(data["repairs"].items()):
            core.require(isinstance(repair, dict), "CONTROL repair must be an object")
            attempts = repair.get("attempts", [])
            core.require(isinstance(attempts, list), "CONTROL attempts must be a list")
            evidence_current = True if verify_artifacts else None
            for attempt in attempts:
                core.require(isinstance(attempt, dict), "CONTROL attempt must be an object")
                if attempt.get("evidence"):
                    try:
                        _receipt(project, attempt["evidence"], verify_artifacts, hashes)
                    except (ValueError, OSError, TypeError, KeyError) as error:
                        warnings.append("Repair " + key + ": " + str(error))
                        evidence_current = False
            disposition = repair.get("disposition", {})
            core.require(isinstance(disposition, dict), "CONTROL disposition must be an object")
            if disposition.get("evidence"):
                try:
                    _receipt(project, disposition["evidence"], verify_artifacts, hashes)
                except (ValueError, OSError, TypeError, KeyError) as error:
                    warnings.append("Repair " + key + ": " + str(error))
                    evidence_current = False
            result.append({"issue_id": key, "defect": repair.get("defect"), "state": repair.get("state"),
                           "attempt_count": len(attempts), "inflight": bool(repair.get("inflight")),
                           "active_minutes_by_attempt": [a.get("active_minutes") for a in attempts],
                           "methods": [a.get("method") for a in attempts], "evidence_current": evidence_current,
                           "disposition": disposition.get("action"), "source": path.relative_to(project).as_posix(),
                           "scope": "Existing asset repair; does not close a Skill issue"})
        return result
    except (ValueError, OSError, TypeError, KeyError) as error:
        warnings.append("Production control unavailable: " + str(error))
        return []


def _build_recap(project, case_dir, verify_artifacts=True):
    """Read one caller-locked snapshot, including legacy failures."""
    project, case = _case(project, case_dir)
    plan, rows = _progress(case)
    issues, episodes, measurements = {}, {}, {}
    warnings, unclassified, sources = [], [], []
    obs_root = _local(case, project, "feedback/observations")
    for name in ("PLAN.json", "PROGRESS.jsonl"):
        path = case / name
        sources.append({"path": path.relative_to(project).as_posix(), "sha256": core.file_hash(path), "role": name})
    observation_count, artifact_hashes = 0, {}
    for row in rows:
        linked = False
        for receipt in row.get("evidence", []):
            try:
                path = _path(project, receipt["path"])
            except (ValueError, OSError, TypeError, KeyError):
                continue
            if not core.inside(path, obs_root):
                continue
            linked = True
            issue_id = row.get("scope", "").removeprefix("feedback/")
            if not core.safe_id(issue_id):
                issue_id = "unreadable-" + str(row["seq"])
            try:
                core.require(path.is_file() and path.stat().st_size <= 65536, "Observation record is missing or exceeds 64 KiB")
                _receipt(project, receipt)
                envelope = core.read(path)
                core.require(isinstance(envelope, dict) and envelope.get("kind") == "greybox-usage-observation-record" and envelope.get("schema") == 1,
                             "Unknown observation record")
                obs = validate_observation(project, envelope["observation"], verify_evidence=False)
                core.require(core.digest(obs) == envelope.get("observation_sha256"), "Observation payload changed")
                core.require(obs["issue_id"] == issue_id and path.name == obs["event_id"] + ".json",
                             "Observation does not match progress identity")
                current = True if verify_artifacts else None
                for item in obs["evidence"] + list(obs.get("regression", {}).values()):
                    try:
                        _receipt(project, item, verify_artifacts, artifact_hashes)
                    except (ValueError, OSError, TypeError, KeyError) as error:
                        warnings.append("Issue " + issue_id + ": " + str(error))
                        current = False
            except (ValueError, OSError, TypeError, KeyError) as error:
                warnings.append("Observation event " + str(row["seq"]) + ": " + str(error))
                issue = issues.setdefault(issue_id, _empty_issue(issue_id))
                issue["evidence_current"] = False
                issue["is_defect_candidate"] = True
                issue["events"].append({"seq": row["seq"], "type": "unreadable", "summary": "Referenced observation is missing or changed"})
                continue
            observation_count += 1
            sources.append({**receipt, "role": "observation"})
            issue = issues.setdefault(issue_id, _empty_issue(issue_id))
            decision_only = (obs["type"] == "intervention" and obs["intervention"]["kind"] in {"creative_decision", "scope_change"})
            issue["is_defect_candidate"] = issue["is_defect_candidate"] or not decision_only
            issue.update({k: obs[k] for k in ("stage", "summary", "expected", "actual", "project_status", "skill_status", "next_test")
                          if obs.get(k) is not None})
            if obs["type"] in {"failure", "reopen"}:
                issue.update(project_status="open", skill_status="untriaged")
            if current is False:
                issue["evidence_current"] = False
            elif current is None and issue["evidence_current"] is not False:
                issue["evidence_current"] = None
            issue["mechanisms"] = sorted(set(issue["mechanisms"]) | set(obs["mechanisms"]))
            # An unknown model after switching sessions must not inherit the
            # previous session's identity. Each event retains its own context.
            issue["context"] = obs["context"]
            issue["evidence"] = obs["evidence"] or issue["evidence"]
            if obs.get("method") is not None:
                issue["latest_method"] = obs["method"]
            if obs.get("triage") is not None:
                issue["triage"] = obs["triage"]
            issue["events"].append({"event_id": obs["event_id"], "seq": row["seq"], "recorded_at": row.get("recorded_at"),
                                    "type": obs["type"], "stage": obs["stage"], "summary": obs["summary"], "basis": obs["basis"],
                                    "source_ref": obs["source_ref"], "method": obs.get("method"),
                                    "context": obs["context"], "skill": envelope.get("skill"), "triage": obs.get("triage"),
                                    "evidence_current": current})
            if obs.get("intervention"):
                episode = obs["intervention"]
                episodes.setdefault(episode["episode_id"], set()).add(episode["kind"])
            if obs.get("costs"):
                measurement = obs["costs"]
                key = measurement["measurement_id"]
                if key in measurements and measurements[key] != measurement:
                    warnings.append("Conflicting measurement " + key + "; retain first observation, inspect before aggregation")
                else:
                    measurements[key] = measurement
        if row.get("type") == "failure" and not linked:
            unclassified.append({"seq": row["seq"], "summary": row.get("summary"), "scope": row.get("scope"),
                                 "source_ref": row.get("source_ref"), "classification": "unclassified"})
        if not linked and str(row.get("scope", "")).startswith("feedback/"):
            issue_id = row["scope"].removeprefix("feedback/")
            if not core.safe_id(issue_id):
                issue_id = "unreadable-" + str(row["seq"])
            issue = issues.setdefault(issue_id, _empty_issue(issue_id))
            issue.update(evidence_current=False, is_defect_candidate=True)
            warnings.append("Feedback event " + str(row["seq"]) + " has no readable in-case observation reference")
    counts = {k: 0 for k in sorted(INTERVENTIONS)}
    for episode_id, kinds in episodes.items():
        kind = next(iter(kinds)) if len(kinds) == 1 else "unclear"
        counts[kind] += 1
        if len(kinds) > 1:
            warnings.append("Intervention " + episode_id + " has conflicting classifications")
    severity_order = {"blocker": 0, "major": 1, "minor": 2, "unknown": 3}
    values = sorted(issues.values(), key=lambda i: (not _unresolved(i),
                    severity_order.get(i["triage"]["severity"], 3), i["issue_id"]))
    for issue in values:
        issue["event_count"] = len(issue["events"])
        issue["attempt_count"] = sum(event["type"] == "attempt" for event in issue["events"])
    regressions = [{"issue_id": issue["issue_id"], "stage": issue.get("stage"), "expected": issue["expected"], "actual": issue["actual"],
                    "next_test": issue["next_test"], "mechanisms": issue["mechanisms"], "evidence": issue["evidence"],
                    "status": "candidate_requires_review", "evidence_current": issue["evidence_current"]}
                   for issue in values if issue["is_defect_candidate"] and issue["expected"] and issue["actual"]
                   and issue["skill_status"] != "not_applicable"]
    repairs = _repairs(project, plan, sources, warnings, verify_artifacts, artifact_hashes)
    return {"schema": 1, "kind": "greybox-usage-recap", "case_id": plan["case_id"], "plan_revision": plan["revision"],
            "case_status": plan["status"], "current_stage": plan["current_stage"], "issues": values,
            "unclassified_failures": unclassified, "repairs": repairs,
            "interventions": {"observed_episodes": len(episodes), **counts, "coverage": "Recorded episodes only; not all chat messages or all human work"},
            "measurements": [measurements[k] for k in sorted(measurements)], "regression_candidates": regressions,
            "warnings": warnings, "coverage": {"observation_count": observation_count,
            "host_transcript": "not_collected", "token_measurements": "reported_only"
            if any(any(m.get(k) is not None for k in ("input_tokens", "cached_input_tokens", "output_tokens"))
                   for m in measurements.values()) else "unknown",
            "artifact_evidence_checked": verify_artifacts,
            "notice": COVERAGE}, "sources": sources, "limits": LIMITS,
            "cost_totals": None, "cost_note": "Measurements may overlap; no automatic total or zero-filled missing metrics"}


def build_recap(project, case_dir, verify_artifacts=True):
    """Read a consistent snapshot without changing the plan or execution state."""
    project, case = _case(project, case_dir)
    with core.locked(case):
        return _build_recap(project, case, verify_artifacts)


def _plain(value):
    text = "unknown" if value is None else str(value)
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace("\n", " ").replace("|", "\\|")


def _short(value, limit=360):
    text = "unknown" if value is None else str(value)
    return _plain(text if len(text) <= limit else text[:limit - 1] + "…")


def _identity(issue):
    """Latest event identity; never fill unknowns from a previous session."""
    events = issue.get("events", [])
    event = events[-1] if events else {}
    skill = event.get("skill") or {}
    context = event.get("context") or {}
    return ["Recorder Skill: " + _short(skill.get("version"), 80)
            + "; manifest_sha256: " + _short(skill.get("manifest_sha256"), 64),
            "Host: " + _short(context.get("host"), 160) + "; model: " + _short(context.get("model"), 160)
            + "; engine: " + _short(context.get("engine"), 160)]


def _markdown(report):
    lines = ["# Usage feedback recap", "", "Case: " + _plain(report["case_id"]),
             "Status: " + _plain(report["case_status"]) + "; stage: " + _plain(report["current_stage"]), "",
             report["coverage"]["notice"],
             "Artifact evidence checked: " + str(report["coverage"]["artifact_evidence_checked"])
             + ". Automatic refresh leaves asset freshness unknown; explicit recap/export verifies it.",
             "Recorder identities describe the package used to write each event; a historical backfill does not establish the failing package version.",
             "Full history is retained in JSON. This view shows at most " + str(SUMMARY_ISSUES)
             + " issues and the latest " + str(SUMMARY_EVENTS) + " events per issue; long fields are shortened.",
             "Recorded issues: " + str(len(report["issues"])) + "; unresolved: "
             + str(sum(_unresolved(issue) for issue in report["issues"])),
             "", "## Issues", ""]
    if not report["issues"]:
        lines.append("No structured observations recorded; this does not establish a problem-free run.")
    for issue in report["issues"][:SUMMARY_ISSUES]:
        lines += ["- **" + _plain(issue["issue_id"]) + "**: " + _short(issue["summary"]),
                  "  Stage: " + _short(issue.get("stage"), 120) + "; Project: " + _plain(issue["project_status"]) + "; Skill: " + _plain(issue["skill_status"])
                  + "; evidence current: " + str(issue["evidence_current"]),
                  "  Expected: " + _short(issue["expected"]) + "; actual: " + _short(issue["actual"])]
        lines += ["  " + line for line in _identity(issue)]
        triage = issue.get("triage", {})
        lines.append("  Reported triage: " + _plain(triage.get("category", "unknown"))
                     + "; severity: " + _plain(triage.get("severity", "unknown"))
                     + "; fingerprint: " + _plain(triage.get("fingerprint")) + ". Cause requires verification.")
        lines.append("  Recorded events: " + str(len(issue["events"])) + "; attempts: "
                     + str(issue.get("attempt_count", 0)))
        if issue.get("latest_method"):
            lines.append("  Latest reported method: " + _short(issue["latest_method"]))
        for event in issue["events"][-SUMMARY_EVENTS:]:
            lines.append("  - " + _plain(event["type"]) + " at " + _short(event.get("stage"), 120) + ": " + _short(event["summary"], 180))
        if issue.get("next_test"):
            lines.append("  Regression candidate: " + _short(issue["next_test"]))
    if len(report["issues"]) > SUMMARY_ISSUES:
        lines.append("Additional issues in JSON: " + str(len(report["issues"]) - SUMMARY_ISSUES))
    counts = report["interventions"]
    lines += ["", "## Recorded intervention episodes", "",
              ", ".join(k + ": " + str(counts[k]) for k in ("observed_episodes", "rescue", "creative_decision", "scope_change", "unclear")),
              counts["coverage"], "", "## Existing asset repairs", ""]
    for repair in report["repairs"][:SUMMARY_ISSUES]:
        lines.append("- " + _plain(repair["issue_id"]) + ": " + _short(repair["defect"]) + "; "
                     + _plain(repair["state"]) + "; attempts: " + str(repair["attempt_count"]))
    if len(report["repairs"]) > SUMMARY_ISSUES:
        lines.append("Additional repairs in JSON: " + str(len(report["repairs"]) - SUMMARY_ISSUES))
    lines += ["", "## Unclassified failures", ""]
    lines += ["- " + _short(row["summary"]) for row in report["unclassified_failures"][-SUMMARY_ISSUES:]]
    if len(report["unclassified_failures"]) > SUMMARY_ISSUES:
        lines.append("Earlier unclassified failures in JSON: " + str(len(report["unclassified_failures"]) - SUMMARY_ISSUES))
    lines += ["", "## Cost observations", "", report["cost_note"]]
    for measurement in report["measurements"][:SUMMARY_ISSUES]:
        lines.append("- " + _plain(measurement["measurement_id"]) + ": "
                     + ", ".join(k + "=" + _plain(measurement.get(k)) for k in sorted(METRICS)))
    if not report["measurements"]:
        lines.append("No cost measurements available.")
    elif len(report["measurements"]) > SUMMARY_ISSUES:
        lines.append("Additional measurements in JSON: " + str(len(report["measurements"]) - SUMMARY_ISSUES))
    lines += ["", "## Warnings and limits", ""]
    lines += ["- " + _short(warning) for warning in report["warnings"][:SUMMARY_ISSUES]]
    if len(report["warnings"]) > SUMMARY_ISSUES:
        lines.append("Additional warnings in JSON: " + str(len(report["warnings"]) - SUMMARY_ISSUES))
    lines += [report["limits"]]
    if report.get("review_required"):
        lines += ["", "Local export draft: review narrative content before sharing. No upload was performed."]
    return "\n".join(lines) + "\n"


def _issue_draft(report):
    lines = ["# Usage feedback issue draft", "",
             "Local draft; review free text and choose the relevant issue before submitting. Nothing was uploaded.",
             "Attach usage-feedback.md and usage-feedback.json after review; JSON retains full recorded history.",
             "Recorder versions identify the writing package. For a historical backfill, the package that failed remains unknown unless separately evidenced.",
             "", "Case: " + _short(report["case_id"], 80) + "; stage: " + _short(report["current_stage"], 120),
             "", report["coverage"]["notice"]]
    for issue in report["issues"][:SUMMARY_ISSUES]:
        lines += ["", "## " + _plain(issue["issue_id"]), "", _short(issue["summary"]), ""]
        lines += _identity(issue)
        lines += ["", "Expected: " + _short(issue["expected"]), "Actual: " + _short(issue["actual"]),
                  "", "Minimal reproduction: unknown. Add the smallest shareable input and exact steps that reproduce this issue; a suggested next test is not an executed reproduction.",
                  "", "Latest reported method: " + _short(issue.get("latest_method")),
                  "Recorded events: " + str(len(issue["events"])) + "; attempts: " + str(issue.get("attempt_count", 0)),
                  "Remaining state: project=" + _plain(issue["project_status"]) + "; Skill=" + _plain(issue["skill_status"]),
                  "Next test: " + _short(issue.get("next_test")),
                  "Evidence freshness: " + _plain(issue.get("evidence_current"))]
    if not report["issues"]:
        lines += ["", "No structured issues recorded. Classify an observed failure or add the missing reproduction details before submitting."]
    if len(report["issues"]) > SUMMARY_ISSUES:
        lines += ["", "Additional issues remain in the attached JSON: " + str(len(report["issues"]) - SUMMARY_ISSUES)]
    lines += ["", report["limits"]]
    return "\n".join(lines) + "\n"


def _write_text(path, text, marker):
    if path.exists():
        original = path.read_text(encoding="utf-8")
        core.require(original.startswith(marker), "Refusing to replace unrelated report file")
        if original == text:
            return False
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix="." + path.name + ".", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
    finally:
        Path(name).unlink(missing_ok=True)
    return True


def _write_report(project, directory, report, basename):
    json_path = _path(project, directory / (basename + ".json"))
    markdown_path = _path(project, directory / (basename + ".md"))
    core.require(json_path.parent == directory and markdown_path.parent == directory, "Report output resolves outside destination")
    if json_path.exists():
        existing = core.read(json_path)
        core.require(isinstance(existing, dict) and existing.get("kind") == report["kind"], "Refusing to replace unrelated report file")
    json_text = json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    changed_json = _write_text(json_path, json_text, "{")
    changed_markdown = _write_text(markdown_path, _markdown(report), "# Usage feedback recap\n")
    return json_path, markdown_path, changed_json or changed_markdown


def refresh(project, case_dir, verify_artifacts=True):
    project, case = _case(project, case_dir)
    directory = _local(case, project, "feedback")
    # Serialize with PLAN/PROGRESS updates so an old view cannot overwrite a
    # newer view. record releases the observation lock before its update hook.
    with core.locked(case):
        report = _build_recap(project, case, verify_artifacts=verify_artifacts)
        json_path, markdown_path, changed = _write_report(project, directory, report, "recap")
    return {"ok": True, "recap_json": str(json_path), "recap_markdown": str(markdown_path), "changed": changed,
            "artifact_evidence_checked": verify_artifacts}


def focus_summary(project, case_dir):
    # FOCUS is frequent navigation. Verify the small observation records, but
    # leave large artifact validation to explicit recap/export generation.
    report = build_recap(project, case_dir, verify_artifacts=False)
    unresolved = [i for i in report["issues"] if _unresolved(i)]
    return {"ok": True, "total_unresolved": len(unresolved),
            "issues": [{**{k: issue[k] for k in ("issue_id", "project_status", "skill_status", "evidence_current")},
                        "summary": issue["summary"][:240]} for issue in unresolved[:3]],
            "unclassified_failures": len(report["unclassified_failures"]),
            "warnings": [w[:240] for w in report["warnings"][:3]], "coverage": report["coverage"], "limits": LIMITS}


def _redact(value):
    if isinstance(value, dict):
        return {k: _redact(v) for k, v in value.items()
                if k not in {"source_ref", "session_ref", "source", "path", "sources", "observation_path"}}
    if isinstance(value, list):
        return [_redact(v) for v in value]
    if not isinstance(value, str):
        return value
    value = re.sub(r"https?://[^\s<>\"']+", "[URL omitted]", value, flags=re.I)
    value = re.sub(r"(?i)\b(?:Bearer\s+)[A-Za-z0-9._~+/=-]+", "[credential omitted]", value)
    value = re.sub(r"(?i)\b(?:api[_ -]?key|access[_ -]?token|refresh[_ -]?token|authorization|password|secret)\s*[:=]\s*[^\s,;]+", "[credential omitted]", value)
    value = re.sub(r"\bsk-[A-Za-z0-9_-]{8,}", "[credential omitted]", value)
    value = re.sub(r"(?<!\w)(?:[A-Za-z]:[\\/]|/)(?:[^\s<>\"'|;,]+)", "[local path omitted]", value)
    return value


def export_report(project, case_dir, output_dir):
    project, case = _case(project, case_dir)
    directory = _path(project, output_dir)
    obs_root = _local(case, project, "feedback/observations")
    skill_root = Path(__file__).resolve().parents[2]
    core.require(directory != case and not core.inside(directory, obs_root)
                 and not core.inside(directory, skill_root) and ".git" not in directory.parts,
                 "Export destination is protected")
    report = _redact(build_recap(project, case))
    report.update(kind="greybox-usage-feedback-export", review_required=True, uploaded=False,
                  redaction="Omitted source references, local paths and obvious credentials/URLs; narrative privacy still requires review")
    with core.locked(directory):
        draft_path = _path(project, directory / "issue-draft.md")
        core.require(draft_path.parent == directory, "Issue draft resolves outside destination")
        draft_text = _issue_draft(report)
        report["issue_draft_sha256"] = hashlib.sha256(draft_text.encode("utf-8")).hexdigest()
        if draft_path.exists():
            previous_text = draft_path.read_text(encoding="utf-8")
            core.require(previous_text.startswith("# Usage feedback issue draft\n"),
                         "Refusing to replace unrelated issue draft")
            if previous_text != draft_text:
                previous_report = _path(project, directory / "usage-feedback.json")
                previous = core.read(previous_report) if previous_report.is_file() else {}
                core.require(isinstance(previous, dict) and previous.get("kind") == report["kind"]
                             and previous.get("issue_draft_sha256") == core.file_hash(draft_path),
                             "Issue draft was edited; preserve it and choose another export directory")
        json_path, markdown_path, changed = _write_report(project, directory, report, "usage-feedback")
        changed_draft = _write_text(draft_path, draft_text, "# Usage feedback issue draft\n")
    return {"ok": True, "json": str(json_path), "markdown": str(markdown_path),
            "issue_draft": str(draft_path), "changed": changed or changed_draft,
            "review_required": True, "uploaded": False}
