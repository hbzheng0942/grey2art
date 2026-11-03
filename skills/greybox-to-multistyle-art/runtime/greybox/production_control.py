"""Case-local operational control, separate from creative approvals and charges.

This is a small host-managed record, not an autonomous scheduler or art judge.
New submissions and native assembly consult it; existing remote work can always
be queried/downloaded. Stable asset identities survive scripts, agents and runs.
"""
from __future__ import annotations

from pathlib import Path
import copy
import math
import contextlib
import time

from . import core, layout

KIND = "greybox-production-control"
PROFILE_FIELDS = {"structure", "method", "skeleton", "engine"}
NATIVE_CHECKS = {"imports", "materials", "scale", "visibility"}


def control_path(project, plan):
    return layout.case_root(Path(project).resolve(), plan) / "shared/production/CONTROL.json"


def _path(project, value):
    p = core.resolve_input(value, Path(project).resolve())
    core.require(core.inside(p, Path(project).resolve()) and p != Path(project).resolve(),
                 "Production-control reference must remain inside its project")
    return p


def _receipt(project, value):
    core.require(isinstance(value, dict) and set(value) == {"path", "sha256"}, "Evidence needs path and sha256")
    p = _path(project, value["path"])
    core.require(p.is_file() and core.file_hash(p) == value["sha256"], "Operational evidence missing or changed: " + str(p))
    return p


def _ids(values, label, empty=False):
    core.require(isinstance(values, list) and (empty or values) and all(core.safe_id(v) for v in values)
                 and len(values) == len(set(values)), label + " needs unique stable IDs")
    return set(values)


def _profile(family):
    return core.digest({"profile": family["profile"], "runtime_profile": family.get("runtime_profile")})


def _validate(data, project):
    core.require(data.get("schema") == 1 and data.get("kind") == KIND, "Expected production-control schema 1")
    core.require(core.safe_id(data.get("case_id")) and core.safe_id(data.get("writer")), "Control needs case_id and designated writer")
    core.require(type(data.get("revision")) is int and data["revision"] > 0, "Control revision must be positive")
    selected = _ids(data.get("selected_styles"), "Selected styles")
    core.require(data.get("lead_style") in selected, "Lead style must be selected")
    active = _ids(data.get("active_styles"), "Active styles")
    core.require(active <= selected, "Active styles must stay inside the approved selection")
    core.require(set(data.get("style_phases", {})) == selected and all(v in {"representative", "expansion"}
                 for v in data["style_phases"].values()), "Declare each selected style's representative/expansion phase")
    core.require(type(data.get("max_open_combinations")) is int and data["max_open_combinations"] > 0,
                 "max_open_combinations must be a positive integer")
    core.require(isinstance(data.get("families"), dict) and isinstance(data.get("combinations"), dict),
                 "Configure families and combinations before production")
    for fid, family in data["families"].items():
        core.require(core.safe_id(fid) and isinstance(family, dict), "Invalid processing family")
        profile = family.get("profile", {})
        core.require(set(profile) == PROFILE_FIELDS and all(isinstance(v, str) and v.strip() for v in profile.values()),
                     "Family profile needs structure, method, skeleton and engine; use 'none' where appropriate")
        _ids(family.get("asset_ids"), "Family assets")
        core.require(_ids(family.get("pilot_asset_ids"), "Family pilot assets") <= set(family["asset_ids"]),
                     "Pilot assets must belong to their family")
        _ids(family.get("required_interactions", []), "Family interactions", True)
        if family.get("runtime_profile") is not None:
            from .runtime_profile import validate_profile
            runtime = validate_profile(family["runtime_profile"], project)
            core.require(runtime["engine"] == profile["engine"], "Runtime profile and family engines differ")
    covered = []
    for family in data["families"].values():
        covered.extend(family["asset_ids"])
    core.require(len(covered) == len(set(covered)), "An asset has exactly one processing family")
    for cid, combo in data["combinations"].items():
        core.require(core.safe_id(cid) and isinstance(combo, dict) and combo.get("style_id") in selected,
                     "Combination must name one selected style")
        core.require(_ids(combo.get("asset_ids", []), "Combination necessary assets", True) <= set(covered),
                     "Every combination asset needs a configured family")
        _ids(combo.get("required_interactions", []), "Combination interactions", True)
        core.require(combo.get("state") in {"queued", "active", "integrated"}, "Invalid combination state")
    core.require(isinstance(data.get("claims"), dict) and isinstance(data.get("repairs"), dict)
                 and isinstance(data.get("events"), list), "Control must preserve claims, repairs and events")
    if active != {data["lead_style"]}:
        _lead_completion(data, project)
    return data


def _read(project, path):
    path = _path(project, path)
    core.require(path.is_file(), "Production control is required before new production. Run scripts/production_control.py init "
                 "--project PROJECT --plan PLAN.json --workflow WORKFLOW.json, then configure families and combinations.")
    return _validate(core.read(path), project)


def initialize(project, plan, workflow_path, lead_style=None, writer="integrator", families=None, combinations=None):
    """Create an explicitly unfinished control; no inferred qualification/approval."""
    project = Path(project).resolve()
    path = control_path(project, plan)
    workflow_path = _path(project, workflow_path)
    workflow = core.read(workflow_path)
    styles = workflow.get("selected_styles", [])
    _ids(styles, "Workflow selected styles")
    core.require(set(layout.style_ids(plan)) <= set(styles), "Plan styles exceed the workflow selection")
    data = {"schema": 1, "kind": KIND, "case_id": layout.workspace(plan)["case_id"], "writer": writer,
            "revision": 1, "workflow_path": str(workflow_path), "selected_styles": styles,
            "lead_style": lead_style or styles[0], "active_styles": [lead_style or styles[0]],
            "style_phases": {s: "representative" for s in styles}, "max_open_combinations": 1,
            "families": families or {}, "combinations": combinations or {}, "claims": {}, "repairs": {},
            "events": [{"type": "initialized", "at": core.now(), "note": "Unfinished until configured; no qualification inferred"}]}
    _validate(data, project)
    with core.locked(path.parent):
        core.require(not path.exists(), "Control already exists; inspect/configure it without resetting history")
        core.write(path, data)
    return assess(project, path)


@contextlib.contextmanager
def _locked(directory):
    """Serialize short case writes across independent run locks, never steal one."""
    deadline = time.monotonic() + 5
    while True:
        lock = core.locked(directory)
        try:
            lock.__enter__()
            break
        except core.WorkflowLockBusy:
            if time.monotonic() >= deadline:
                raise
            time.sleep(.02)
    try:
        yield
    finally:
        lock.__exit__(None, None, None)


def _update(project, path, mutation, expected_revision=None):
    path = _path(project, path)
    with _locked(path.parent):
        data = _read(project, path)
        if expected_revision is not None:
            core.require(data["revision"] == expected_revision, "Control changed; inspect and rebase the operational edit")
        result = mutation(data)
        data["revision"] += 1
        _validate(data, project)
        core.write(path, data)
    return result


def configure(project, path, settings, expected_revision):
    """Set scheduling definitions without replacing claims/repairs or approvals."""
    allowed = {"families", "combinations", "max_open_combinations", "style_phases"}
    core.require(isinstance(settings, dict) and settings and set(settings) <= allowed, "Configure operational definitions only")
    def change(data):
        for fid, old in data["families"].items():
            new = settings.get("families", data["families"]).get(fid)
            if new is not None and _profile(new) != _profile(old):
                core.require(not new.get("qualification"), "Changed processing profile needs fresh qualification; do not copy the old pass")
        data.update(copy.deepcopy(settings))
        data["events"].append({"type": "configured", "at": core.now()})
    _update(project, path, change, expected_revision)
    return assess(project, path)


def _native(project, receipt, engine, assets, interactions, family=None, expect_pass=True):
    """Validate evidence coverage, not the truth of the host's visual judgment."""
    report = core.read(_receipt(project, receipt))
    core.require(report.get("schema") == 1 and report.get("kind") == "native-composition-check"
                 and report.get("engine") == engine and report.get("passed") is expect_pass,
                 "Need an actual successful native composition report for this engine")
    core.require(isinstance(report.get("reviewer"), str) and report["reviewer"].strip()
                 and isinstance(report.get("source_ref"), str) and report["source_ref"].strip()
                 and isinstance(report.get("camera_id"), str) and report["camera_id"].strip(),
                 "Native check needs reviewer, source and actual main camera")
    required = NATIVE_CHECKS | ({"interaction_continuity"} if interactions else set())
    if expect_pass:
        core.require(all(report.get("checks", {}).get(k) is True for k in required),
                     "Native visibility/continuity checks are required; numerical contact alone is insufficient")
    else:
        core.require(all(type(report.get("checks", {}).get(k)) is bool for k in required)
                     and any(report["checks"][k] is False for k in required), "Quality rejection must name an actual failed native criterion")
    source_assets = report.get("assets", {})
    core.require(isinstance(source_assets, dict) and set(assets) <= set(source_assets), "Native check omits required assets")
    for aid in assets:
        _receipt(project, source_assets[aid])
    core.require(set(interactions) <= _ids(report.get("covered_interactions", []), "Covered interactions", True),
                 "Native report omits required interactions")
    media = report.get("media", [])
    core.require(isinstance(media, list) and media, "Native report needs actual main-camera images/continuous captures")
    continuous = False
    frame_sequences = {}
    for item in media:
        core.require(isinstance(item, dict), "Invalid native media")
        p = _receipt(project, {k: item[k] for k in ("path", "sha256") if k in item})
        core.require(p.stat().st_size > 0 and item.get("camera_id") == report["camera_id"], "Media must bind the main camera")
        if p.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp"}:
            from .modeling_refs import _decode
            _decode(p.read_bytes())
            if item.get("sequence_id"):
                stamp = item.get("time_seconds")
                core.require(isinstance(stamp, (int, float)) and not isinstance(stamp, bool) and math.isfinite(stamp) and stamp >= 0,
                             "Continuous frames need actual finite capture times")
                frame_sequences.setdefault(item["sequence_id"], []).append((stamp, item["sha256"]))
        else:
            core.require(p.suffix.lower() in {".mp4", ".webm", ".mov", ".gif"}, "Native media must be an image or continuous capture")
        continuous |= item.get("continuous") is True and p.suffix.lower() in {".mp4", ".webm", ".mov", ".gif"}
    sequence = report.get("continuous_sequence")
    if sequence:
        frames = frame_sequences.get(sequence.get("id"), [])
        times = [t for t, _ in frames]
        gap = sequence.get("max_gap_seconds")
        core.require(len(frames) >= 3 and len({h for _, h in frames}) >= 2 and times == sorted(set(times))
                     and isinstance(gap, (int, float)) and not isinstance(gap, bool) and math.isfinite(gap) and gap > 0
                     and max(b - a for a, b in zip(times, times[1:])) <= gap
                     and times[0] == sequence.get("from_seconds") and times[-1] == sequence.get("to_seconds"),
                     "Continuous frame evidence must cover its declared interval without omitted gaps")
        continuous = True
    core.require(not expect_pass or not interactions or continuous, "Key interactions need a reviewed continuous main-camera capture or timed frame sequence")
    if expect_pass and family and family.get("runtime_profile") is not None:
        from .runtime_profile import validate_profile, validate_targets
        runtime = validate_profile(family["runtime_profile"], project)
        core.require(runtime["engine"] == engine and report.get("runtime_target") == runtime["target"],
                     "Native report must use the runtime profile's engine and target environment")
        by_asset = report.get("targets_by_asset", {})
        core.require(isinstance(by_asset, dict), "targets_by_asset must map asset IDs to budget targets")
        for aid in assets:
            targets = by_asset.get(aid, report.get("targets") if len(source_assets) == 1 else None)
            core.require(isinstance(targets, list), "Multi-asset native reports need targets_by_asset for every runtime-profile asset")
            validate_targets(family["runtime_profile"], targets, project, asset_id=aid)
    elif family:
        core.require(report.get("budget_passed") is not True, "No runtime profile is not evidence of performance/budget acceptance")
    return report


def qualify(project, path, family_id, receipt):
    def change(data):
        family = data["families"].get(family_id)
        core.require(family is not None, "Unknown family")
        _native(project, receipt, family["profile"]["engine"], family["pilot_asset_ids"],
                family.get("required_interactions", []), family)
        family["qualification"] = {"profile_digest": _profile(family), "evidence": receipt}
        data["events"].append({"type": "qualified", "family_id": family_id, "at": core.now()})
    _update(project, path, change)
    return assess(project, path)


def _qualified(project, family):
    q = family.get("qualification")
    if not q:
        return False
    core.require(q.get("profile_digest") == _profile(family), "Family qualification uses a different processing/runtime profile")
    _native(project, q.get("evidence"), family["profile"]["engine"], family["pilot_asset_ids"],
            family.get("required_interactions", []), family)
    return True


def integrate(project, path, combination_id, receipt):
    def change(data):
        combo = data["combinations"].get(combination_id)
        core.require(combo and combo["state"] == "active", "Integrate the current active combination")
        families = [f for f in data["families"].values() if set(f["asset_ids"]) & set(combo["asset_ids"])]
        engine = families[0]["profile"]["engine"] if families else core.read(_receipt(project, receipt)).get("engine")
        core.require(all(f["profile"]["engine"] == engine for f in families), "Combination engine mismatch")
        _native(project, receipt, engine, combo["asset_ids"], combo.get("required_interactions", []))
        for family in families:
            if family.get("runtime_profile") is not None:
                _native(project, receipt, engine, set(family["asset_ids"]) & set(combo["asset_ids"]), [], family)
        combo.update(state="integrated", native_evidence=receipt)
        data["events"].append({"type": "integrated", "combination_id": combination_id, "at": core.now()})
    _update(project, path, change)
    return assess(project, path)


def start_combination(project, path, combination_id):
    """Start local/reuse integration without requiring an otherwise needless POST."""
    def change(data):
        combo = data["combinations"].get(combination_id)
        core.require(combo and combo["style_id"] in data["active_styles"], "Combination is outside the active style")
        core.require(combo["state"] != "integrated", "Keep accepted integration evidence; configure a new combination for changed work")
        if combo["state"] == "queued":
            core.require(sum(c["state"] == "active" for c in data["combinations"].values()) < data["max_open_combinations"],
                         "Integration backlog is full")
            combo["state"] = "active"
        data["events"].append({"type": "start_combination", "id": combination_id, "at": core.now()})
    _update(project, path, change)
    return assess(project, path)


def _lead_completion(data, project, workflow_path=None):
    from . import workflow
    reference = data.get("lead_completion")
    core.require(reference, "Complete and accept the lead style's H4 before releasing other styles; polish does not postpone an accepted H4")
    source = _path(project, reference.get("workflow_path", workflow_path or data["workflow_path"]))
    document = core.read(source)
    _same_creative_context(project, document, core.read(_path(project, workflow_path or data["workflow_path"])))
    stage = next((s for s in document.get("stages", []) if s.get("scope") == data["lead_style"]
                  and s.get("id") == "representative_sample"), None)
    core.require(stage and workflow.stage_digest(stage) == reference.get("stage_digest"), "Lead H4 proof changed")
    workflow.inspect_workflow(source, project, selected_styles=[data["lead_style"]], expansion=True, require_current_capabilities=False)
    return True


def _same_creative_context(project, first, second):
    from . import workflow
    for sid in ("baseline", "directions", "selection"):
        a = next((s for s in first.get("stages", []) if s.get("scope") == "shared" and s.get("id") == sid), None)
        b = next((s for s in second.get("stages", []) if s.get("scope") == "shared" and s.get("id") == sid), None)
        core.require(a and b and workflow.stage_digest(a) == workflow.stage_digest(b),
                     "Lead H4 belongs to a different baseline or selected concept context: " + sid)


def activate_styles(project, path, styles, workflow_path=None):
    def change(data):
        core.require(_ids(styles, "Requested active styles") <= set(data["selected_styles"]), "Cannot add unselected styles")
        if set(styles) != {data["lead_style"]}:
            from . import workflow
            source = _path(project, workflow_path or data["workflow_path"])
            _same_creative_context(project, core.read(source), core.read(_path(project, data["workflow_path"])))
            workflow.inspect_workflow(source, project, selected_styles=[data["lead_style"]], expansion=True, require_current_capabilities=False)
            stage = next(s for s in core.read(source)["stages"] if s["scope"] == data["lead_style"] and s["id"] == "representative_sample")
            data["lead_completion"] = {"workflow_path": str(source), "stage_digest": workflow.stage_digest(stage)}
        data["active_styles"] = styles
        data["events"].append({"type": "active_styles", "styles": styles, "at": core.now()})
    _update(project, path, change)
    return assess(project, path)


def _repair_blockers(data, asset_id, submission=None):
    return [key for key, value in data["repairs"].items() if asset_id in value["asset_ids"] and value["state"] != "resolved"
            and (value["state"] == "deferred" or (value.get("inflight") and (submission is None or value["inflight"].get("submission") != submission))
                 or len(value["attempts"]) >= value["max_attempts"]
                 or sum(a["active_minutes"] for a in value["attempts"]) >= value["max_active_minutes"])]


def _asset_combination(data, asset_id):
    matches = [(cid, c) for cid, c in data["combinations"].items()
               if asset_id in c["asset_ids"] and c["style_id"] in data["active_styles"] and c["state"] != "integrated"]
    core.require(matches, "Asset is not necessary for an unfinished combination in the active style: " + asset_id)
    return sorted(matches, key=lambda item: (item[1]["state"] != "active", item[0]))[0]


def ensure_prepared(project, plan, workflow_path=None):
    data = _read(project, control_path(project, plan))
    core.require(data["case_id"] == layout.workspace(plan)["case_id"], "Wrong production-control case")
    core.require(set(layout.style_ids(plan)) <= set(data["selected_styles"]), "Production styles exceed control selection")
    actual_workflow = workflow_path or plan.get("workflow", {}).get("path")
    if actual_workflow:
        _same_creative_context(project, core.read(_path(project, actual_workflow)), core.read(_path(project, data["workflow_path"])))
    core.require(data["combinations"], "Control is unfinished: configure combinations (style_id, necessary asset_ids, required_interactions) "
                 "and families (profile, asset_ids, pilot_asset_ids) using scripts/production_control.py configure")
    for asset in plan.get("assets", []):
        aid = asset.get("id", asset.get("asset_id"))
        core.require(any(aid in c["asset_ids"] for c in data["combinations"].values()), "Control omits planned asset: " + aid)
    return data


def guard_style(project, plan, style_id):
    data = ensure_prepared(project, plan)
    core.require(style_id in data["active_styles"], "Style is queued until the lead H4 is accepted: " + style_id)
    consumed = set()
    for original in plan.get("bindings", []):
        binding = copy.deepcopy(original)
        binding.update(binding.pop("styles", {}).get(style_id, {}))
        if binding.get("source", {}).get("asset_id"):
            consumed.add(binding["source"]["asset_id"])
    for aid in consumed:
        for issue in _repair_blockers(data, aid):
            repair = data["repairs"][issue]
            # Native inspection of an already bounded repair is necessary to
            # finish that attempt; exhausted/deferred production cannot bypass
            # the same issue by switching generation to a reuse plan.
            core.require(repair.get("inflight") and repair["state"] == "open",
                         "Native production consumes an exhausted/deferred repair asset: " + aid)
    return True


def guard_submission(project, plan, asset_id, operation, run_dir, request_digest, dry_run=False):
    """Validate or claim new work. A dry run never reserves control state."""
    path = control_path(project, plan)
    ensure_prepared(project, plan)
    def change(data):
        identity = {"asset_id": asset_id, "operation": operation, "run_dir": str(Path(run_dir).resolve()), "request_digest": request_digest}
        family = next((f for f in data["families"].values() if asset_id in f["asset_ids"]), None)
        core.require(family is not None, "Configure a processing family for asset: " + asset_id)
        core.require(not _repair_blockers(data, asset_id, identity), "Cumulative repair limit reached or attempt unresolved; resolve/defer the defect before repeating")
        core.require(asset_id in family["pilot_asset_ids"] or _qualified(project, family), "Processing family needs its native pilot before expanding: " + asset_id)
        cid, combo = _asset_combination(data, asset_id)
        if combo["state"] == "queued":
            open_count = sum(c["state"] == "active" for c in data["combinations"].values())
            core.require(open_count < data["max_open_combinations"], "Integration backlog is full; complete an active combination before opening another")
            combo["state"] = "active"
        key = core.digest([data["case_id"], asset_id, operation])
        previous = data["claims"].get(key)
        replace = previous and previous.get("terminal_state") in {"failed", "cancelled", "rejected", "native_failed", "not_submitted"}
        if replace and previous["terminal_state"] == "native_failed":
            repair = data["repairs"].get(previous.get("repair_issue"), {})
            core.require(repair.get("inflight", {}).get("submission") == identity,
                         "Rejected ready output needs a bounded repair attempt bound to this exact next submission")
        core.require(previous is None or replace or all(previous.get(k) == v for k, v in identity.items()),
                     "This case asset/operation already belongs to another attempt; recover/reuse its original output, never reset by changing run")
        if previous is None or replace:
            history = ([{k: v for k, v in previous.items() if k != "history"}] + previous.get("history", [])) if previous else []
            data["claims"][key] = {**identity, "combination_id": cid, "claimed_at": core.now(), "history": history}
        return {"ok": True, "claim_id": key, "combination_id": cid}
    if dry_run:
        # Same locked read, checks and candidate validation as _update; discard
        # the candidate without incrementing revision or persisting a claim.
        with _locked(_path(project, path).parent):
            data = _read(project, path)
            result = change(data)
            _validate(data, project)
            return {**result, "dry_run": True}
    return _update(project, path, change)


def release_unsubmitted(project, plan, asset_id, operation, run_dir, request_digest):
    """Runner-only cleanup after its existing claim guard rejects, before POST.

    The persisted original supplier row must prove no task or cost reservation
    was made. This never releases the legacy/H3 unknown-task guard itself.
    """
    run = _path(project, run_dir)
    state = core.read(run / "supplier-run.json")
    portfolio = core.read(run / "supplier-portfolio.json")
    selected = next(o for o in portfolio["options"] if o["id"] == state["selected_option"])
    ops = [o for o in selected["operations"] if o["asset_id"] == asset_id and o["operation"] == operation and core.digest(o) == request_digest]
    core.require(len(ops) == 1, "Unsubmitted release must name the original operation")
    oid = ops[0]["id"]; row = state["operations"][oid]
    core.require(row.get("state") == "blocked_duplicate" and not row.get("task_id") and oid not in state["reservations"],
                 "Only a persisted pre-POST claim rejection may release an unsubmitted operational claim")
    def change(data):
        key = core.digest([data["case_id"], asset_id, operation])
        claim = data["claims"].get(key)
        core.require(claim and claim["run_dir"] == str(run) and claim["request_digest"] == request_digest,
                     "Unsubmitted release cannot affect another run's claim")
        claim.update(terminal_state="not_submitted", terminal_note="Existing H3/unresolved guard rejected before reservation or POST",
                     reconciled_at=core.now())
    _update(project, control_path(project, plan), change)


def reconcile_claim(project, path, claim_id, evidence, note, repair_issue=None, quality_evidence=None):
    """Release only a confirmed terminal original run, retaining all attempt history."""
    core.require(isinstance(note, str) and note.strip(), "Terminal claim reconciliation needs a reason")
    ledger_path = _receipt(project, evidence)
    def change(data):
        claim = data["claims"].get(claim_id)
        core.require(claim is not None, "Unknown case operation claim")
        run = _path(project, claim["run_dir"])
        ledger = core.read(ledger_path)
        if ledger.get("kind") == "supplier-job-run":
            core.require(ledger_path == run / "supplier-run.json", "Claim reconciliation must read the original supplier run")
            portfolio = core.read(run / "supplier-portfolio.json")
            option = next(o for o in portfolio["options"] if o["id"] == ledger["selected_option"])
            ops = [o for o in option["operations"] if o["asset_id"] == claim["asset_id"] and o["operation"] == claim["operation"]
                   and core.digest(o) == claim["request_digest"]]
            core.require(len(ops) == 1, "Original operation identity is missing or ambiguous")
            row = ledger["operations"][ops[0]["id"]]
        else:
            core.require(ledger.get("kind") == "greybox-art-run" and ledger_path == run / "run.json", "Claim reconciliation must read the original art run")
            row = ledger.get("assets", {}).get(claim["asset_id"], {})
            core.require(row.get("operation") == claim["operation"] and core.digest({"operation": row.get("operation"),
                         "parameters": row.get("parameters")}) == claim["request_digest"], "Original asset request changed")
        terminal = row.get("state")
        if terminal == "ready":
            repair = data["repairs"].get(repair_issue)
            core.require(repair and repair["state"] == "open" and claim["asset_id"] in repair["asset_ids"],
                         "Ready-output replacement requires a tracked native defect and cumulative repair allowance")
            family = next(f for f in data["families"].values() if claim["asset_id"] in f["asset_ids"])
            report = _native(project, quality_evidence, family["profile"]["engine"], [claim["asset_id"]],
                             family.get("required_interactions", []), expect_pass=False)
            actual = report["assets"][claim["asset_id"]]
            outputs = row.get("artifacts", []) if ledger.get("kind") == "supplier-job-run" else [row.get("artifact", {})]
            core.require(any(a.get("sha256") == actual["sha256"] and _path(project, a.get("path", "")) == _path(project, actual["path"])
                             for a in outputs), "Quality rejection does not inspect the original ready output")
            terminal = "native_failed"
            claim.update(repair_issue=repair_issue, quality_evidence=quality_evidence)
        core.require(terminal in {"failed", "cancelled", "rejected", "native_failed"},
                     "Unknown/inflight work cannot release its claim; ready output should be reused")
        claim.update(terminal_state=terminal, terminal_evidence=evidence, terminal_note=note,
                     reconciled_at=core.now())
        data["events"].append({"type": "terminal_claim", "claim_id": claim_id, "state": row["state"], "at": core.now()})
    _update(project, path, change)
    return assess(project, path)


def open_repair(project, path, issue_id, asset_ids, defect, max_attempts=3, max_active_minutes=30):
    core.require(core.safe_id(issue_id) and isinstance(defect, str) and defect.strip(), "Repair needs stable issue ID and defect")
    core.require(type(max_attempts) is int and max_attempts > 0 and isinstance(max_active_minutes, (int, float))
                 and not isinstance(max_active_minutes, bool) and math.isfinite(max_active_minutes)
                 and max_active_minutes > 0, "Repair needs bounded attempts/time")
    def change(data):
        core.require(issue_id not in data["repairs"], "Repair already exists; preserve its cumulative history")
        known = {a for f in data["families"].values() for a in f["asset_ids"]}
        core.require(_ids(asset_ids, "Repair assets") <= known, "Repair contains unknown assets")
        signature = core.digest([sorted(asset_ids), " ".join(defect.lower().split())])
        core.require(not any(r["signature"] == signature for r in data["repairs"].values()), "Same defect already has a repair record; changing issue ID cannot reset it")
        data["repairs"][issue_id] = {"asset_ids": asset_ids, "defect": defect, "signature": signature,
            "max_attempts": max_attempts, "max_active_minutes": max_active_minutes, "attempts": [], "state": "open"}
    _update(project, path, change)
    return assess(project, path)


def begin_repair(project, path, issue_id, method, owner, submission=None):
    core.require(all(isinstance(v, str) and v.strip() for v in (method, owner)), "Repair attempt needs method and owner")
    def change(data):
        r = data["repairs"].get(issue_id)
        core.require(r and r["state"] == "open" and not r.get("inflight"), "Repair is not open or already has an unfinished attempt")
        core.require(len(r["attempts"]) < r["max_attempts"] and sum(a["active_minutes"] for a in r["attempts"]) < r["max_active_minutes"],
                     "Cumulative repair allowance exhausted; apply a verified fallback or defer, do not restart under another script/agent")
        r["inflight"] = {"method": method, "owner": owner, "started_at": core.now(), "attempt": len(r["attempts"]) + 1}
        if submission is not None:
            core.require(isinstance(submission, dict) and set(submission) == {"asset_id", "operation", "run_dir", "request_digest"}
                         and submission["asset_id"] in r["asset_ids"] and core.safe_id(submission["operation"])
                         and isinstance(submission["request_digest"], str) and len(submission["request_digest"]) == 64,
                         "Repair submission permit needs exact asset/operation/run/request identity")
            r["inflight"]["submission"] = {**submission, "run_dir": str(_path(project, submission["run_dir"]))}
        return copy.deepcopy(r["inflight"])
    return _update(project, path, change)


def finish_repair(project, path, issue_id, active_minutes, evidence, observation):
    core.require(isinstance(active_minutes, (int, float)) and not isinstance(active_minutes, bool)
                 and math.isfinite(active_minutes) and active_minutes >= 0
                 and isinstance(observation, str) and observation.strip(), "Record actual active minutes and observed result")
    _receipt(project, evidence)
    def change(data):
        r = data["repairs"].get(issue_id)
        core.require(r and r.get("inflight"), "No started repair attempt")
        r["attempts"].append({**r.pop("inflight"), "active_minutes": active_minutes, "evidence": evidence,
                              "observation": observation, "finished_at": core.now()})
    _update(project, path, change)
    return assess(project, path)


def resolve_repair(project, path, issue_id, action, note, evidence=None):
    core.require(action in {"verified_fix", "verified_fallback", "defer"} and isinstance(note, str) and note.strip(), "Choose a concrete repair disposition")
    def change(data):
        r = data["repairs"].get(issue_id)
        core.require(r and not r.get("inflight"), "Finish/reconcile the current attempt before resolving")
        if action != "defer":
            families = [f for f in data["families"].values() if set(f["asset_ids"]) & set(r["asset_ids"])]
            for f in families:
                _native(project, evidence, f["profile"]["engine"], set(f["asset_ids"]) & set(r["asset_ids"]),
                        f.get("required_interactions", []), f)
        r.update(state="deferred" if action == "defer" else "resolved", disposition={"action": action, "note": note, "evidence": evidence})
    _update(project, path, change)
    return assess(project, path)


def assess(project, path, workflow_path=None):
    data = _read(project, path)
    qualified, errors = [], {}
    for fid, family in data["families"].items():
        try:
            if _qualified(project, family):
                qualified.append(fid)
        except (ValueError, OSError, KeyError, TypeError) as error:
            errors[fid] = str(error)
    lead_ready = False
    try:
        if data.get("lead_completion"):
            lead_ready = _lead_completion(data, project, workflow_path)
        else:
            from . import workflow
            source = _path(project, workflow_path or data["workflow_path"])
            workflow.inspect_workflow(source, project, selected_styles=[data["lead_style"]], expansion=True, require_current_capabilities=False)
            lead_ready = True
    except (ValueError, OSError, KeyError, TypeError):
        pass
    repair_blockers = {aid: _repair_blockers(data, aid) for f in data["families"].values() for aid in f["asset_ids"] if _repair_blockers(data, aid)}
    asset_blockers = {}
    open_count = sum(c["state"] == "active" for c in data["combinations"].values())
    for fid, family in data["families"].items():
        for aid in family["asset_ids"]:
            reasons = []
            if aid in repair_blockers:
                reasons.append("cumulative_repair_limit_or_unfinished_attempt")
            if aid not in family["pilot_asset_ids"] and fid not in qualified:
                reasons.append("processing_family_pilot_required")
            try:
                _, combo = _asset_combination(data, aid)
                if combo["state"] == "queued" and open_count >= data["max_open_combinations"]:
                    reasons.append("integration_backlog_full")
            except ValueError:
                reasons.append("not_in_current_style_unfinished_combination")
            if reasons:
                asset_blockers[aid] = reasons
    return {"ok": not errors, "path": str(_path(project, path)), "revision": data["revision"],
        "case_id": data["case_id"], "active_styles": data["active_styles"],
        "queued_styles": [s for s in data["selected_styles"] if s not in data["active_styles"]],
        "style_phases": data["style_phases"], "ready_for_style_transition": lead_ready,
        "configured": bool(data["combinations"]), "qualified_families": qualified, "qualification_errors": errors,
        "open_combinations": [k for k, v in data["combinations"].items() if v["state"] == "active"],
        "integration_backlog": sum(v["state"] == "active" for v in data["combinations"].values()),
        "repair_blockers": repair_blockers, "asset_blockers": asset_blockers, "claims": len(data["claims"]),
        "limits": "Operational host records only. Evidence integrity is checked; visual truth, human approval and charges remain in their original records."}
