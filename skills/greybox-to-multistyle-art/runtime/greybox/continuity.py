"""Small case plan and append-only progress journal; never an approval authority.

The designated integrator writes a case under a process lock and revision CAS.
FOCUS is derived from current references and existing workflow/run ledgers. It
does not cache approval, budget, provider state or a third hand-maintained plan.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path

from . import core, workflow, knowledge
from .workgraph import inspect_workgraph, VISUAL_TIERS

EVENT_TYPES = {"requirement", "proposal", "change", "decision_reference", "completed", "failure",
               "review", "handoff", "pause", "resume"}
PLAN_FIELDS = {"objective", "constraints", "quality_floor", "current_stage", "remaining", "proposals",
               "references", "status", "execution_context"}


def _text(value):
    return isinstance(value, str) and bool(value.strip())


def _path(path, project):
    core.require(_text(str(path)), "Project-contained path required")
    result = core.resolve_input(path, project)
    core.require(result != project and core.inside(result, project), "Path escapes project or owns root")
    return result


def _checkpoint(plan, project):
    path = _path(plan["references"]["workflow"], project)
    core.require(path.is_file(), "Referenced workflow is missing")
    return path, core.file_hash(path)


def _validate(plan, project, check_sources=True):
    core.require(isinstance(plan, dict) and plan.get("schema") == 1
                 and plan.get("kind") == "greybox-case-plan", "Expected greybox-case-plan schema 1")
    core.require(set(plan) <= PLAN_FIELDS | {"schema", "kind", "case_id", "writer", "revision", "progress_seq"},
                 "PLAN may not duplicate approval, budget or execution ledgers")
    core.require(core.safe_id(plan.get("case_id")) and core.safe_id(plan.get("writer")), "Case ID and writer required")
    core.require(type(plan.get("revision")) is int and plan["revision"] > 0, "Positive plan revision required")
    core.require(type(plan.get("progress_seq")) is int and plan["progress_seq"] > 0, "Progress sequence required")
    core.require(plan.get("status") in {"active", "paused", "complete"}, "Invalid case status")
    core.require(_text(plan.get("objective")) and _text(plan.get("current_stage")), "Objective and stage required")
    if "execution_context" in plan:
        from . import task_context
        task_context.validate_context(plan["execution_context"])
        core.require(Path(plan["execution_context"]["project"]["root"]).resolve() == project,
                     "Pinned execution context belongs to another project")
    for key in ("constraints", "quality_floor", "remaining", "proposals"):
        core.require(isinstance(plan.get(key), list) and all(_text(x) for x in plan[key]), key + " must be text items")
    refs = plan.get("references", {})
    core.require(isinstance(refs, dict) and set(refs) <= {"workflow", "workgraph", "approved_inputs", "ledgers", "production_control"},
                 "Use workflow/workgraph/approved_inputs/ledgers/production_control references only")
    if check_sources:
        _checkpoint(plan, project)
    else:
        _path(refs["workflow"], project)
    if refs.get("workgraph"):
        p = _path(refs["workgraph"], project)
        core.require(not check_sources or p.is_file(), "Referenced workgraph is missing")
    if refs.get("production_control"):
        p = _path(refs["production_control"], project)
        core.require(not check_sources or p.is_file(), "Referenced production control is missing")
    core.require(isinstance(refs.get("approved_inputs", []), list), "Approved input references must be a list")
    for receipt in refs.get("approved_inputs", []):
        core.require(isinstance(receipt, dict) and set(receipt) == {"path", "sha256"}, "Input needs path/hash only")
        p = _path(receipt["path"], project)
        core.require(not check_sources or (p.is_file() and core.file_hash(p) == receipt["sha256"]),
                     "Approved input changed or missing")
    ledgers = refs.get("ledgers", [])
    core.require(isinstance(ledgers, list), "Ledger references must be a list")
    for ledger in ledgers:
        core.require(isinstance(ledger, str), "Ledger reference must be a path")
        p = _path(ledger, project)
        core.require(not check_sources or p.is_file(), "Referenced execution ledger is missing")


def _event(value, writer, revision, sequence):
    core.require(isinstance(value, dict) and set(value) <= {"type", "summary", "source_ref", "scope", "evidence"},
                 "Progress stores key events, not approval/budget/execution objects")
    core.require(value.get("type") in EVENT_TYPES and all(_text(value.get(k)) for k in ("summary", "source_ref", "scope")),
                 "Event needs type, summary, actual source reference and affected scope")
    core.require(isinstance(value.get("evidence", []), list), "Event evidence must be receipt list")
    return {**value, "writer": writer, "plan_revision": revision, "seq": sequence, "recorded_at": core.now()}


def _event_evidence(event, project):
    for receipt in event.get("evidence", []):
        core.require(isinstance(receipt, dict) and set(receipt) == {"path", "sha256"}, "Evidence needs path/hash")
        p = _path(receipt["path"], project)
        core.require(p.is_file() and core.file_hash(p) == receipt["sha256"], "Event evidence missing or stale")


def _recover(case):
    """Complete our own interrupted two-file commit; never erase unknown bytes."""
    journal = case / ".progress-transaction.json"
    if not journal.exists():
        return
    tx = core.read(journal)
    current = case / "PLAN.json"
    current_hash = core.file_hash(current) if current.exists() else None
    core.require(current_hash == tx["previous_plan_sha256"] or
                 (current.exists() and core.digest(core.read(current)) == core.digest(tx["plan"])),
                 "Plan changed during interrupted transaction; do not overwrite another revision")
    progress = case / "PROGRESS.jsonl"
    existing = progress.read_bytes() if progress.exists() else b""
    offset = tx["offset"]
    core.require(len(existing) >= offset and hashlib.sha256(existing[:offset]).hexdigest() == tx["prefix_sha256"],
                 "Progress changed during interrupted transaction; inspect before recovery")
    line = (json.dumps(tx["event"], ensure_ascii=False, sort_keys=True, allow_nan=False) + "\n").encode()
    tail = existing[offset:]
    core.require(line.startswith(tail), "Unexpected progress tail; do not overwrite another writer")
    if tail != line:
        with progress.open("ab") as stream:
            stream.write(line[len(tail):])
            stream.flush()
            os.fsync(stream.fileno())
    core.write(case / "PLAN.json", tx["plan"])
    journal.unlink()


def _commit(case, plan, event):
    progress = case / "PROGRESS.jsonl"
    existing = progress.read_bytes() if progress.exists() else b""
    previous = case / "PLAN.json"
    core.write(case / ".progress-transaction.json", {"plan": plan, "event": event, "offset": len(existing),
               "previous_plan_sha256": core.file_hash(previous) if previous.exists() else None,
               "prefix_sha256": hashlib.sha256(existing).hexdigest()})
    _recover(case)


def _verify_progress(case, plan):
    raw = (case / "PROGRESS.jsonl").read_bytes()
    core.require(raw.endswith(b"\n"), "Progress has an incomplete append; inspect the journal before continuing")
    rows = [json.loads(line) for line in raw.splitlines()]
    core.require(rows and all(row.get("seq") == i + 1 and row.get("writer") == plan["writer"]
                             for i, row in enumerate(rows)), "Progress sequence/writer changed; inspect before continuing")
    core.require(rows[-1]["seq"] == plan["progress_seq"] and rows[-1]["plan_revision"] == plan["revision"],
                 "Plan and progress revisions disagree; inspect the journal")


def initialize(project, case_dir, plan, event):
    project = Path(project).resolve()
    case = _path(case_dir, project)
    plan = {**plan, "schema": 1, "kind": "greybox-case-plan", "revision": 1, "progress_seq": 1}
    _validate(plan, project)
    event = _event(event, plan["writer"], 1, 1)
    _event_evidence(event, project)
    with core.locked(case):
        core.require(not (case / "PLAN.json").exists() and not (case / "PROGRESS.jsonl").exists()
                     and not (case / ".progress-transaction.json").exists(), "Case already exists; resume, do not recreate")
        _commit(case, plan, event)
    return {"ok": True, "revision": 1, "plan": str(case / "PLAN.json"),
            "usage_feedback": _refresh_feedback(project, case)}


def recover(project, case_dir, writer):
    """Finish an existing transaction only; no semantic new event or approval."""
    project = Path(project).resolve()
    case = _path(case_dir, project)
    with core.locked(case):
        pending = case / ".progress-transaction.json"
        current = case / "PLAN.json"
        core.require(current.exists() or pending.exists(), "No case or interrupted transaction to recover")
        plan = core.read(current) if current.exists() else core.read(pending)["plan"]
        core.require(plan["writer"] == writer, "Only the designated plan writer may recover")
        _recover(case)
        plan = core.read(current)
        _verify_progress(case, plan)
    return {"ok": True, "revision": plan["revision"], "paid_work_authorized": False,
            "usage_feedback": _refresh_feedback(project, case)}


def _refresh_feedback(project, case):
    try:
        from . import feedback
        return feedback.refresh(project, case, verify_artifacts=False)
    except Exception as error:
        return {"ok": False, "error": str(error),
                "next_action": "Progress was saved; inspect feedback sources and rerun feedback recap"}


def _feedback_after_event(project, case, event, changes):
    """Derive a cheap local recap after commit; reporting cannot undo progress."""
    if (event["type"] not in {"failure", "review", "handoff", "pause", "completed"}
            and "current_stage" not in (changes or {})
            and not (case / "feedback" / "observations").exists()):
        return None
    return _refresh_feedback(project, case)


def _feedback_focus(project, case):
    paths = {"recap_markdown": str(case / "feedback" / "recap.md"),
             "recap_json": str(case / "feedback" / "recap.json"),
             "report_available": (case / "feedback" / "recap.md").is_file()
                                 and (case / "feedback" / "recap.json").is_file()}
    try:
        from . import feedback
        return {**feedback.focus_summary(project, case), **paths,
                "capture": "Agent-recorded observations; capture completeness is unknown",
                "sharing": "Ask to export usage feedback; feedback export creates local Markdown, JSON and an issue draft"}
    except Exception as error:
        return {"ok": False, "error": str(error), **paths,
                "next_action": "Feedback coverage is unknown; inspect sources without resetting the task"}


def record_observation(project, case_dir, writer, expected_revision, expected_checkpoint_sha256, event):
    """Append feedback even about a broken source binding; never edit task state.

    Production update/FOCUS/dispatch retain their full source checks. This
    observation-only path can change revision/sequence and nothing else.
    """
    project = Path(project).resolve()
    case = _path(case_dir, project)
    core.require(event.get("type") in {"failure", "review"}
                 and str(event.get("scope", "")).startswith("feedback/")
                 and len(event.get("evidence", [])) == 1, "Expected a single feedback observation event")
    receipt_path = _path(event["evidence"][0]["path"], project)
    core.require(core.inside(receipt_path, case / "feedback" / "observations"),
                 "Observation must belong to this case")
    core.require(isinstance(expected_checkpoint_sha256, str)
                 and re.fullmatch(r"[a-f0-9]{64}", expected_checkpoint_sha256), "Checkpoint hash required")
    with core.locked(case):
        original = core.read(case / "PLAN.json")
        core.require(original["writer"] == writer, "Only the designated plan writer may record feedback")
        _recover(case)
        original = core.read(case / "PLAN.json")
        _verify_progress(case, original)
        _validate(original, project, check_sources=False)
        core.require(original["revision"] == expected_revision, "Stale plan revision; derive current feedback context")
        checkpoint = _path(original["references"]["workflow"], project)
        checkpoint_available = checkpoint.is_file()
        if checkpoint_available:
            core.require(core.file_hash(checkpoint) == expected_checkpoint_sha256, "Workflow checkpoint changed")
        plan = {**original, "revision": original["revision"] + 1, "progress_seq": original["progress_seq"] + 1}
        value = _event(event, writer, plan["revision"], plan["progress_seq"])
        _event_evidence(value, project)
        _commit(case, plan, value)
    return {"ok": True, "revision": plan["revision"], "event_seq": plan["progress_seq"],
            "checkpoint_available": checkpoint_available, "production_context_validated": False,
            "usage_feedback": _refresh_feedback(project, case)}


def update(project, case_dir, writer, expected_revision, expected_checkpoint_sha256, event, changes=None):
    """Record one key event, optionally revise plan. An event never approves work."""
    project = Path(project).resolve()
    case = _path(case_dir, project)
    core.require(isinstance(changes or {}, dict) and set(changes or {}) <= PLAN_FIELDS, "Unsupported plan changes")
    with core.locked(case):
        # Verify designated writer before resuming their interrupted commit.
        pending = case / ".progress-transaction.json"
        original = core.read(case / "PLAN.json") if (case / "PLAN.json").exists() else core.read(pending)["plan"]
        core.require(original["writer"] == writer, "Only the designated plan writer may update; send a handoff instead")
        _recover(case)
        original = core.read(case / "PLAN.json")
        _verify_progress(case, original)
        core.require(original["revision"] == expected_revision, "Stale plan revision; derive focus and rebase the change")
        core.require(_checkpoint(original, project)[1] == expected_checkpoint_sha256,
                     "Workflow checkpoint changed; derive focus before acting")
        plan = {**original, **(changes or {}), "revision": expected_revision + 1,
                "progress_seq": original["progress_seq"] + 1}
        _validate(plan, project)
        value = _event(event, writer, plan["revision"], plan["progress_seq"])
        _event_evidence(value, project)
        if plan["status"] != original["status"]:
            wanted = {"paused": "pause", "active": "resume", "complete": "completed"}[plan["status"]]
            core.require(value["type"] == wanted, "Case status change needs corresponding sourced event")
        _commit(case, plan, value)
    result = {"ok": True, "revision": plan["revision"], "event_seq": plan["progress_seq"]}
    recap = _feedback_after_event(project, case, value, changes)
    if recap is not None:
        result["usage_feedback"] = recap
    return result


def classify_message(message):
    """Conservative triage hint, never authentication or an automatic plan edit."""
    core.require(_text(message), "Message text required")
    text = message.strip().lower()
    if re.search(r"(?:暂停|先停|停止当前|\bpause\b|\bstop this\b)", text):
        category = "pause"
    elif re.search(r"(?:取消当前|换个目标|替换目标|\breplace (?:this|the) (?:task|goal)\b)", text):
        category = "replace"
    elif re.search(r"(?:[?？]|会不会|是否|怎么样|如何|\b(?:could|would|should|what|how)\b)", text):
        category = "inquiry"
    elif re.search(r"(?:建议|考虑|不如|可以试|也许|\b(?:suggest|maybe|consider|propose)\b)", text):
        category = "proposal"
    elif re.search(r"(?:不要批准|不批准|未批准|do not approve|don't approve)", text):
        category = "clarify"
    elif re.search(r"(?:批准|确认(?:这个|这批|该|h[1-5])|同意(?:这个|该|方案)|\bapprove\b)", text):
        category = "approval_candidate"
    elif re.search(r"(?:这批改|改成|调整为|补(?:上)?\s*bom|切换到|\b(?:change|switch|add|update)\b)", text):
        category = "change"
    elif re.search(r"(?:继续|恢复|\b(?:continue|resume|proceed)\b)", text):
        category = "continue"
    else:
        category = "clarify"
    return {"category": category, "approval_granted": False, "changes_plan": False,
            "next": "Record actual scoped approval through the existing workflow gate" if category == "approval_candidate"
            else "Interpret the message in context; preserve the current objective unless explicitly changed"}


def _unknowns(value, source, pointer=""):
    found = []
    if isinstance(value, dict):
        state = value.get("state", value.get("phase"))
        if state in {"unknown", "submitting", "reserved", "attempted", "recovery_required"}:
            found.append({"ledger": source, "pointer": pointer or "/", "state": state})
        for key, child in value.items():
            found.extend(_unknowns(child, source, pointer + "/" + str(key)))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            found.extend(_unknowns(child, source, pointer + "/" + str(index)))
    return found


def derive_focus(project, case_dir):
    """Read current references without rewriting case, approvals or job state."""
    project = Path(project).resolve()
    case = _path(case_dir, project)
    core.require(not (case / ".progress-transaction.json").exists(),
                 "Interrupted case update; designated writer must resume the journal before deriving focus")
    plan_path = case / "PLAN.json"
    plan = core.read(plan_path)
    _validate(plan, project)
    _verify_progress(case, plan)
    checkpoint, checkpoint_hash = _checkpoint(plan, project)
    state = core.read(checkpoint)
    execution_context = {"pinned": plan.get("execution_context"), "current_session_checked": False,
                         "next_action": "Run task-context check with the actual current session report before guarded dispatch"
                         if plan.get("execution_context") else "Legacy case is unpinned; inspect actual entry before pinning via PLAN CAS"}
    if state.get("kind") == "greybox-harness-job":
        from . import harness
        return {**harness.focus(state, plan, checkpoint, case),
                "learning": knowledge.for_focus(plan["current_stage"], state.get("engine")),
                "execution_context": execution_context,
                "usage_feedback": _feedback_focus(project, case)}
    stages = state.get("stages", [])
    stage_id = plan["current_stage"].rsplit("/", 1)[-1]
    current = next((s for s in stages if s.get("scope", "") + "/" + s.get("id", "") == plan["current_stage"]), None)
    required_roles = set(workflow.ROLES.get(stage_id, set()))
    if state.get("production_policy") == workflow.PRODUCTION_POLICY:
        required_roles.update({"production_plan": {"bom_board", "assembly_map", "visual_package"},
                               "art_proxy": {"proxy_capture"}}.get(stage_id, set()))
    required_roles = sorted(required_roles)
    present_roles = {e.get("role") for e in current.get("evidence", [])} if current else set()
    refs = plan["references"]
    style = plan["current_stage"].rsplit("/", 1)[0]
    active_styles = [style] if style in state.get("selected_styles", []) else state.get("selected_styles", [])
    phases = {sid: "expansion" if sid == style and stage_id == "representative_sample" else "representative"
              for sid in active_styles}
    for sid in active_styles:
        production = next((s for s in stages if s.get("scope") == sid and s.get("id") == "production_plan"), None)
        table = next((e for e in production.get("evidence", []) if e.get("role") == "production_table"), None) if production else None
        if table:
            try:
                if core.read(_path(table["path"], project)).get("scope_mode") == "expansion":
                    phases[sid] = "expansion"
            except (ValueError, OSError, KeyError, TypeError):
                pass  # The authoritative workflow inspection reports this error.
    control_path = _path(refs.get("production_control", "art/" + plan["case_id"] + "/shared/production/CONTROL.json"), project)
    control, control_hash, control_error = None, None, None
    if control_path.is_file():
        try:
            from . import production_control
            control = production_control.assess(project, control_path, workflow_path=checkpoint)
            current_phases = phases
            active_styles = control["active_styles"]
            phases = {sid: control["style_phases"].get(sid, "representative") for sid in active_styles}
            # Navigation cannot call H4 complete by looking only at H3, even
            # when the operational phase has not yet been advanced.
            for sid in active_styles:
                if current_phases.get(sid) == "expansion":
                    phases[sid] = "expansion"
            control_hash = core.file_hash(control_path)
        except (ValueError, OSError, KeyError, TypeError) as error:
            control_error = str(error)
    expansion = bool(phases) and all(v == "expansion" for v in phases.values())
    stage_scope_matches_active = style == "shared" or style in active_styles
    inspection_scope = "mixed_scoped_production" if len(set(phases.values())) > 1 else "expansion" if expansion else "representative_production"
    try:
        core.require(not control_error, "Production control is invalid: " + str(control_error))
        checked = workflow.inspect_workflow(checkpoint, project, selected_styles=active_styles,
            require_current_capabilities=False, style_phases=phases)
        workflow_check = {"ok": checked["ok"], "ready_for": checked["ready_for"], "capabilities_current": False,
                          "inspection_scope": inspection_scope, "active_styles": active_styles, "style_phases": phases}
    except (ValueError, OSError, KeyError, TypeError) as error:
        workflow_check = {"ok": False, "error": str(error), "capabilities_current": False,
                          "inspection_scope": inspection_scope, "active_styles": active_styles, "style_phases": phases}
    authorization_refs = [{"stage": s.get("scope", "") + "/" + s.get("id", ""),
                           "source_ref": s["approval"].get("source_ref"), "recorded_decision": s["approval"].get("decision"),
                           "check": "source_reference_only_use_workflow_gate"}
                          for s in stages if isinstance(s.get("approval"), dict) and s["approval"].get("source_ref")]
    unknown, ledger_errors = [], []
    for ref in refs.get("ledgers", []):
        try:
            unknown.extend(_unknowns(core.read(_path(ref, project)), ref))
        except (OSError, ValueError, TypeError) as error:
            ledger_errors.append({"ledger": ref, "error": str(error)})
    graph = inspect_workgraph(refs["workgraph"], project) if refs.get("workgraph") else None
    graph_unknown = [tid for tid, state in graph["states"].items() if state == "reconciliation_required"] if graph else []
    largest_gap, next_action = None, "Complete the current stage's missing evidence and workflow requirements"
    if graph:
        raw = core.read(_path(refs["workgraph"], project))
        pending = [t for t in raw["tasks"] if graph["states"][t["id"]] != "completed"
                   and t.get("style") in set(active_styles) | {"shared"}
                   and graph["effective_visual_tiers"][t["id"]] in {"blocker", "composition"}]
        pending.sort(key=lambda t: (VISUAL_TIERS.index(graph["effective_visual_tiers"][t["id"]]),
                     t["id"] != raw.get("largest_visual_gap"), t["id"]))
        if pending:
            task = pending[0]
            largest_gap = {"task": task["id"], "state": graph["states"][task["id"]],
                           "rationale": task.get("visual_priority", {}).get("rationale", "Required dependency")}
        if graph["recommended_wave"]:
            next_action = "Check existing authorization, then dispatch ready work: " + ", ".join(graph["recommended_wave"])
    if plan["status"] != "active":
        next_action = "Case is " + plan["status"] + "; follow the recorded user decision before resuming"
    elif unknown or ledger_errors or graph_unknown:
        next_action = "Reconcile original unknown submissions; independent local ready work may continue. Do not reissue or switch provider for affected work."
    elif not workflow_check["ok"]:
        next_action += ". Production remains gated: " + workflow_check["error"]
    if not stage_scope_matches_active:
        next_action = ("Designated writer must update PLAN.current_stage to the active style; preserve CONTROL and existing authorized work. "
                       + next_action)
    return {"ok": True, "case_id": plan["case_id"], "objective": plan["objective"],
            "status": plan["status"], "current_stage": plan["current_stage"], "constraints": plan["constraints"],
            "learning": knowledge.for_focus(plan["current_stage"]),
            "quality_floor": plan["quality_floor"], "remaining": plan["remaining"], "pending_proposals": plan["proposals"],
            "required_roles": required_roles, "missing_roles": sorted(set(required_roles) - present_roles),
            "largest_visual_gap": largest_gap, "next_action": next_action, "workflow_check": workflow_check,
            "production_control": control, "queued_styles": [sid for sid in state.get("selected_styles", []) if sid not in active_styles],
            "stage_scope_matches_active": stage_scope_matches_active,
            "execution_context": execution_context,
            "usage_feedback": _feedback_focus(project, case),
            "authorization_refs": authorization_refs, "unknown_submissions": unknown, "ledger_errors": ledger_errors,
            "reconciliation_required_tasks": graph_unknown, "progress_path": str(case / "PROGRESS.jsonl"),
            "latest_event_seq": plan["progress_seq"],
            "ledger_coverage": "declared_paths_only" if refs.get("ledgers") else "no_ledgers_declared_not_proof_of_no_submissions",
            "workgraph": {k: graph[k] for k in ("recommended_wave", "work_unit_reminders", "unclassified_tasks")} if graph else None,
            "resume_token": {"plan_revision": plan["revision"], "plan_sha256": core.file_hash(plan_path),
                             "checkpoint_sha256": checkpoint_hash,
                             **({"production_control_sha256": control_hash} if control_hash else {})},
            "limits": "Derived navigation, not approval or a dispatcher. Check actual workflow/quote/ledger gates before action; refresh host capabilities. Historical events are not execution authority."}


def check_resume_token(project, case_dir, token):
    current = derive_focus(project, case_dir)["resume_token"]
    core.require(current == token, "Plan or workflow changed; derive focus and rebase before publishing or dispatching")
    return {"ok": True, "resume_token": current, "paid_work_authorized": False}
