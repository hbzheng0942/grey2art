"""Portable early scope brief and conditional character work, with no execution.

Profiles describe discovery, never host readiness. Report evidence is supplied by
an actual host; this module validates bindings, not the authenticity of a human.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from urllib.parse import urlsplit

from .core import digest, require, safe_id

HOST_FEATURES = {
    "file_read": {"read"}, "file_write": {"write"},
    "process_execute": {"execute"}, "image_inspect": {"pixel_read"},
    "image_present": {"display"}, "human_input": {"source_reference"},
    "image_generate": {"text_to_image", "reference_image"},
    "image_generate_text": {"text_to_image"},
    "image_generate_reference": {"reference_image"},
    "image_edit": {"reference_image"}, "delegate": {"subagents"},
}
BASE_HOST_OPERATIONS = ("file_read", "file_write", "process_execute", "image_inspect",
                        "image_present", "human_input")
SCENE_FORMATS = {"blend", "glb", "gltf", "fbx", "obj", "usd", "usda", "usdc"}
ENGINE_STATUS = {"godot": "implemented_native_adapter",
                 "unity": "implemented_native_adapter", "threejs": "planned_unverified"}
CHARACTER_POLICY = "needs-driven-v2"
GATES = [
    {"id": "H1", "decision": "Select actual concept directions"},
    {"id": "H2", "decision": "Confirm coherent concept atlas and spatial design"},
    {"id": "H3", "decision": "Confirm asset routes, supplier combination and spending scope"},
    {"id": "H4", "decision": "Accept the complete native representative sample"},
    {"id": "H5", "decision": "Accept all promised styles and playable evidence"},
]


def _text(value):
    return isinstance(value, str) and bool(value.strip())


def _no_secrets(value):
    if isinstance(value, dict):
        for key, child in value.items():
            require(key.lower().replace("_", "").replace("-", "") not in
                    {"apikey", "authorization", "accesstoken", "secret", "password"},
                    "Keep credentials outside portable briefs and host reports")
            _no_secrets(child)
    elif isinstance(value, list):
        for child in value:
            _no_secrets(child)


def check_host_capabilities(report, required_operations=None, expected_host=None,
                            expected_session=None):
    """Check actual current session bindings, without probing or invoking tools.

    Optional delegation has an explicit sequential fallback. Missing required
    visual/reference operations have no silent fallback to text-only work.
    """
    require(isinstance(report, dict) and report.get("schema") == 1
            and report.get("kind") == "host-capability-report",
            "Expected host-capability-report schema 1, not a static host profile")
    _no_secrets(report)
    require(safe_id(report.get("host_id")) and _text(report.get("session_id")),
            "Host discovery needs actual host and session identity")
    if expected_host:
        require(report["host_id"] == expected_host, "Host report belongs to another host")
    if expected_session:
        require(report["session_id"] == expected_session,
                "Host report belongs to another session; rediscover its tools")
    try:
        checked = datetime.fromisoformat(str(report["checked_at"]).replace("Z", "+00:00"))
        require(checked.utcoffset() is not None, "Host checked_at needs a timezone")
        age = (datetime.now(timezone.utc) - checked).total_seconds()
    except (KeyError, ValueError, TypeError):
        raise ValueError("Host checked_at needs a timezone-aware ISO8601 timestamp") from None
    require(-300 <= age <= 86400, "Host discovery expired; refresh operational readiness")
    required = list(BASE_HOST_OPERATIONS if required_operations is None else required_operations)
    require(all(safe_id(x) for x in required) and len(required) == len(set(required)),
            "Required host operations need unique stable IDs")
    operations = report.get("operations")
    require(isinstance(operations, dict), "Host operations must be a mapping")
    bindings, blockers = {}, []

    def inspect(operation):
        cap = operations.get(operation, {})
        if not isinstance(cap, dict):
            return None, "operation-unavailable"
        channel, verification = cap.get("channel", {}), cap.get("verification", {})
        if not isinstance(channel, dict) or not isinstance(verification, dict):
            return None, "channel-unbound-or-unverified"
        kind, target, supports = channel.get("kind"), channel.get("target"), channel.get("supports", [])
        if cap.get("status") != "available":
            return None, "operation-unavailable"
        if kind not in {"host_tool", "mcp", "api", "cli", "manual"} or not _text(target):
            return None, "channel-unbound-or-unverified"
        if kind == "manual" and operation not in {"human_input", "image_present"}:
            return None, "manual-channel-does-not-provide-operation"
        if kind == "api":
            url = urlsplit(target)
            if url.scheme != "https" or not url.hostname or url.username or url.query or url.fragment:
                return None, "api-channel-needs-public-https-endpoint-without-credentials"
        if (verification.get("level") not in {"discovered", "connection_verified", "invocation_verified"}
                or not _text(verification.get("evidence")) or not _text(cap.get("evidence"))):
            return None, "channel-unbound-or-unverified"
        if not isinstance(supports, list) or not all(_text(x) for x in supports):
            return None, "required-feature-missing"
        if not HOST_FEATURES.get(operation, set()) <= set(supports):
            return None, "required-feature-missing"
        return {"kind": kind, "target": target, "verification": verification["level"],
                "supports": sorted(set(supports))}, None

    for operation in required:
        binding, error = inspect(operation)
        if error:
            blockers.append({"operation": operation, "reason": error})
        else:
            bindings[operation] = binding
    delegate, _ = inspect("delegate")
    return {"ok": not blockers, "host_id": report["host_id"], "session_id": report["session_id"],
            "checked_at": report["checked_at"], "report_digest": digest(report),
            "bindings": bindings, "blockers": blockers,
            "collaboration": "parallel_available" if delegate else "sequential_fallback",
            "note": "Host-reported discovery is not an invocation test, human authentication, or engine integration proof"}


def _character_needs(needs):
    require(isinstance(needs, dict), "Character needs must be a mapping")
    presence = needs.get("presence", "uncertain")
    require(presence in {"required", "none", "uncertain"}, "Unknown character presence")
    value = {
        "presence": presence,
        "source": needs.get("source", "none" if presence == "none" else "uncertain"),
        "deformation": needs.get("deformation", "none" if presence == "none" else "uncertain"),
        "rig": needs.get("rig", "none" if presence == "none" else "uncertain"),
        "animation": needs.get("animation", "none" if presence == "none" else "uncertain"),
        "retarget": needs.get("retarget", "none" if presence == "none" else "uncertain"),
    }
    require(value["source"] in {"new", "reuse", "none", "uncertain"}, "Unknown character source")
    require(value["deformation"] in {"required", "none", "uncertain"}, "Unknown deformation need")
    require(value["rig"] in {"new", "existing", "none", "uncertain"}, "Unknown rig need")
    require(value["animation"] in {"new", "reuse", "none", "uncertain"}, "Unknown animation need")
    require(value["retarget"] in {"required", "none", "uncertain"}, "Unknown retarget need")
    if presence == "none":
        require(all(value[k] == "none" for k in value if k != "presence"),
                "No-character scope cannot hide character production requests")
    if presence == "required":
        require(value["source"] != "none", "Required character needs a source")
    if value["deformation"] == "none":
        require(value["rig"] == "none" and value["retarget"] == "none",
                "Rigid/static characters do not need skeletal rigging or retargeting")
    if value["deformation"] == "required":
        require(value["rig"] != "none", "Deforming characters require an existing, new or unresolved rig")
    if value["rig"] in {"existing", "new"}:
        require(value["deformation"] != "none", "Rig requires a deformation need")
    if value["rig"] == "existing":
        require(value["source"] == "reuse", "Existing rigs must identify the reused character asset")
    if value["retarget"] == "required":
        require(value["animation"] != "none" and value["deformation"] != "none",
                "Retargeting requires skeletal animation and deformation")
    for key, field in (("source", "asset_ref"), ("animation", "motion_ref")):
        if value[key] == "reuse":
            require(_text(needs.get(field)), "Reused character/motion needs " + field)
            value[field] = needs[field]
    if value["animation"] == "reuse" and value["rig"] in {"new", "existing"} and value["retarget"] == "none":
        require(needs.get("skeleton_compatible_verified") is True and _text(needs.get("compatibility_evidence")),
                "Reused motion needs retargeting or verified skeleton compatibility with its target rig")
        value["skeleton_compatible_verified"] = True
        value["compatibility_evidence"] = needs["compatibility_evidence"]
    if "mesh_processing" in needs:
        processing = needs["mesh_processing"]
        require(processing in {"none", "repair", "remesh", "uncertain"}, "Unknown character mesh processing need")
        require(presence != "none" or processing == "none", "No-character scope cannot request mesh processing")
        value["mesh_processing"] = processing
        if processing in {"repair", "remesh"}:
            require(_text(needs.get("mesh_processing_reason")), "Character mesh processing needs a concrete defect or measured budget reason")
            value["mesh_processing_reason"] = needs["mesh_processing_reason"]
        require(processing != "remesh" or value["rig"] != "existing",
                "Remeshing changes topology; plan new rigging or a qualified weight-transfer route instead of preserving an existing-rig claim")
    return value


def character_graph(needs, native_engine="godot", *, policy=CHARACTER_POLICY):
    """Derive all necessary nodes; unsure branches block dependent production."""
    value = _character_needs(needs)
    require(policy in {"legacy-v1", CHARACTER_POLICY}, "Unknown character processing policy")
    if value["presence"] == "none":
        return {"needs": value, "state": "skipped", "nodes": [], "required_tools": [], "unresolved": []}
    unresolved = [k for k, v in value.items() if v == "uncertain"]
    nodes = []

    def add(name, depends, tools, status="required"):
        nodes.append({"id": name, "depends_on": depends, "required_tools": tools, "status": status})

    if value["presence"] == "uncertain":
        add("character_scope", [], ["human_input"], "uncertain")
        return {"needs": value, "state": "needs_scope", "nodes": nodes,
                "required_tools": ["human_input"], "unresolved": unresolved}
    if unresolved:
        add("character_scope", [], ["human_input"], "uncertain")
    predecessor = ["character_scope"] if unresolved else []
    if value["source"] == "new":
        add("character_model", predecessor, ["model_generation"])
        if policy == "legacy-v1":
            add("character_cleanup", ["character_model"], ["mesh_inspect", "mesh_edit"])
            last = "character_cleanup"
        else:
            add("character_inspect", ["character_model"], ["mesh_inspect"])
            last = "character_inspect"
    elif value["source"] == "reuse":
        add("character_reuse_check", predecessor, ["mesh_inspect"])
        last = "character_reuse_check"
    else:
        last = "character_scope"
    if policy == CHARACTER_POLICY and value.get("mesh_processing") in {"repair", "remesh"}:
        add("character_cleanup" if value["mesh_processing"] == "repair" else "character_remesh", [last], ["mesh_edit"])
        last = nodes[-1]["id"]
    add("character_scale_fit", [last], ["mesh_inspect", "mesh_transform"])
    last = "character_scale_fit"
    if value["rig"] == "new":
        add("character_rig", [last], ["rig"])
        last = "character_rig"
    if value["rig"] in {"new", "existing"}:
        add("character_deformation_check", [last], ["rig_inspect"])
        last = "character_deformation_check"
    if value["animation"] in {"new", "reuse"}:
        if value["deformation"] == "none":
            add("character_rigid_animation", [last], ["rigid_animation"])
        else:
            add("character_motion", [last], ["motion_generate" if value["animation"] == "new" else "motion_import"])
        last = nodes[-1]["id"]
        if value["retarget"] == "required":
            add("character_retarget", [last], ["retarget"])
            last = "character_retarget"
        add("character_contact_check", [last], ["contact_review", "animation_edit"])
        last = "character_contact_check"
    add("character_export", [last], ["asset_export"])
    add("character_native_check", ["character_export"], ["native_import", "native_character_validation"])
    return {"needs": value, "state": "needs_scope" if unresolved else "planned",
            "target_engine": native_engine, "nodes": nodes,
            "required_tools": sorted({tool for node in nodes for tool in node["required_tools"]}),
            "unresolved": unresolved}


def _normalize_intake(intake):
    require(isinstance(intake, dict) and intake.get("schema") == 1
            and intake.get("kind") == "workflow-overview-intake", "Expected workflow-overview-intake schema 1")
    _no_secrets(intake)
    require(safe_id(intake.get("id")), "Overview intake needs a stable ID")
    value = deepcopy(intake)
    goals = value.get("goals")
    require(isinstance(goals, list) and goals and all(_text(x) for x in goals), "Overview needs concrete delivery goals")
    source = value.get("input", {})
    require(isinstance(source, dict) and source.get("mode") in {"playable", "spatial_only"},
            "Declare playable or spatial_only input mode")
    require(_text(source.get("format")), "Input needs its actual format")
    raw_format = source["format"].lower().lstrip(".")
    if raw_format in SCENE_FORMATS:
        require(source["mode"] == "spatial_only" and source.get("baseline_verified", False) is False,
                "A scene-only file is spatial_only; a playable claim needs a native game host and baseline")
    if source.get("baseline_verified") is True:
        require(source["mode"] == "playable" and _text(source.get("baseline_evidence")),
                "A verified playable baseline needs its actual native evidence reference")
    else:
        require(source.get("baseline_verified", False) is False, "baseline_verified must be a boolean")
    spatial_endpoint = value.get("endpoint") == "spatial"
    if "endpoint" in value:
        require(value["endpoint"] in {"spatial", "playable"}, "Unknown delivery endpoint")
    if "authoring_carrier" in value:
        require(value["authoring_carrier"] in {"blender", "godot", "unity", "unreal"}, "Unknown authoring carrier")
    if spatial_endpoint:
        require(_text(value.get("authoring_carrier")), "Spatial endpoint needs its authoring carrier")
        require(source["mode"] == "spatial_only", "Spatial delivery uses spatial_only input")
        require(value.get("target_engine") is None or _text(value.get("target_engine")), "Runtime must be absent or a named target")
    else:
        require(_text(value.get("target_engine")), "Overview needs a target runtime engine")
    if value.get("target_engine"):
        require(value["target_engine"].lower() != "blender", "Blender is an authoring/geometry backend; declare a gameplay runtime separately")
        value["target_engine"] = value["target_engine"].lower()
    mode = value.get("delivery_mode", "spatial_design" if spatial_endpoint else "multistyle")
    require(mode in {"single_style", "multistyle", "spatial_design"}, "Unknown overview delivery mode")
    count = value.get("style_count", 2 if mode == "multistyle" else 1)
    require(type(count) is int and count >= (2 if mode == "multistyle" else 1), "Style count must match the promised delivery mode")
    value["delivery_mode"], value["style_count"] = mode, count
    value["concept_source"] = value.get("concept_source", "generate")
    require(value["concept_source"] in {"generate", "approved_import"}, "Unknown concept source")
    providers = value.get("providers", [])
    require(isinstance(providers, list), "Provider readiness must be a list")
    ids = []
    for provider in providers:
        require(isinstance(provider, dict) and safe_id(provider.get("id"))
                and provider.get("status") in {"unconfigured", "configured", "discovered", "connection_verified", "operation_verified", "native_verified", "unverified"},
                "Provider entry needs an ID and explicit declared readiness")
        ids.append(provider["id"])
    require(len(ids) == len(set(ids)), "Duplicate overview supplier")
    value["providers"] = providers
    value["character"] = _character_needs(value.get("character", {"presence": "none" if spatial_endpoint else "uncertain"}))
    if spatial_endpoint:
        require(value.get("operation", "create") in {"create", "edit", "review"}, "Unknown native spatial operation")
    branches = value.get("branches", [])
    require(isinstance(branches, list), "Overview branches must be a list")
    for branch in branches:
        require(isinstance(branch, dict) and safe_id(branch.get("id"))
                and branch.get("status") in {"required", "optional", "uncertain", "not_needed"}
                and _text(branch.get("note")), "Branches need ID, status and scope note")
    require(len({b["id"] for b in branches}) == len(branches), "Duplicate overview branch")
    value["branches"] = branches
    return value


def generate_overview(intake, host_report=None, *, character_policy=CHARACTER_POLICY):
    """Create a simple early brief; never approve scope or execute production."""
    value = _normalize_intake(intake)
    engine = value.get("target_engine")
    spatial_endpoint = value.get("endpoint") == "spatial"
    native_spatial = spatial_endpoint and value["delivery_mode"] == "spatial_design"
    graph = character_graph(value["character"], engine, policy=character_policy)
    verified = value["input"].get("baseline_verified", False)
    required_operations = list(BASE_HOST_OPERATIONS)
    if not native_spatial and value["concept_source"] == "generate":
        required_operations.append("image_generate")
    readiness = (check_host_capabilities(host_report, required_operations) if host_report is not None else
                 {"ok": False, "status": "not_supplied", "collaboration": "sequential_fallback",
                  "note": "Discover actual host bindings; loading this skill does not verify capabilities"})
    blockers = []
    if not spatial_endpoint and (value.get("endpoint") == "playable" or value["delivery_mode"] != "spatial_design") and not verified:
        blockers.append("Establish and verify a native gameplay host/baseline before claiming playable delivery")
    if not spatial_endpoint and engine and ENGINE_STATUS.get(engine) != "implemented_native_adapter":
        blockers.append("Target runtime adapter is planned/unverified; budget a separate integration and native validation step")
    if graph["unresolved"]:
        blockers.append("Resolve character scope before its dependent asset production")
    steps = [
        {"id": "intake", "work": "Inspect greybox, preserve gameplay/spatial contract and discover tools", "human_gate": None},
        {"id": "directions", "work": "Propose 8–10 differentiated actual concept images", "human_gate": "H1"},
        {"id": "spatial_design", "work": "Develop coherent multi-scene concept atlas and spatial design", "human_gate": "H2"},
        {"id": "asset_plan", "work": "Compare supplier combinations, full asset routes and budget", "human_gate": "H3"},
        {"id": "sample", "work": "Produce and assemble a complete native representative sample", "human_gate": "H4"},
        {"id": "delivery", "work": "Expand accepted recipes and validate every promised style", "human_gate": "H5"},
    ]
    gates = deepcopy(GATES)
    if native_spatial:
        operation = value.get("operation", "create")
        if operation == "review":
            # Reviewing an existing source is not an authoring or supplier request.
            required_operations = [name for name in BASE_HOST_OPERATIONS if name != "file_write"]
            readiness = (check_host_capabilities(host_report, required_operations) if host_report is not None else readiness)
        steps = [
            {"id": "intake", "work": "Inspect the selected source or new workspace and discover the declared authoring carrier", "human_gate": None},
            {"id": "native_spatial", "work": "Review existing source without modifying it" if operation == "review" else "Create or revise the scoped editable spatial source using available host-native tools", "human_gate": None},
            {"id": "spatial_evidence", "work": "Inspect actual affected native views and retain source/result identity plus invocation evidence; do not claim gameplay", "human_gate": None},
        ]
        gates = []
    result = {"schema": 1, "kind": "workflow-overview", "id": value["id"],
            "intake": value, "intake_digest": digest(value),
            "target": {"engine": engine, "adapter_status": "host_native_route" if spatial_endpoint and not engine else ENGINE_STATUS.get(engine, "unimplemented"),
                       "delivery_mode": value["delivery_mode"], "style_count": value["style_count"],
                       "baseline_status": "verified_evidence_declared" if verified else "unverified"},
            "steps": steps, "human_gates": gates, "character_graph": graph,
            "host_readiness": readiness, "blockers": blockers,
            "budget": {"status": "preliminary_only", "note": "Do not invent a fixed cost or schedule; H3 binds the actual supplier options and spending scope"},
            "grants_authorization": False, "note": "Early scope overview, not a new approval gate. Update changed scope; preserve H1–H5 decisions and their exact dependencies"}
    if spatial_endpoint:
        result["target"].update(authoring_carrier=value["authoring_carrier"], endpoint="spatial",
                                native_verification="unverified")
        if not native_spatial:
            result["human_gates"][-1]["decision"] = "Accept all promised styles and native spatial evidence"
    if character_policy != "legacy-v1":
        result["character_policy"] = character_policy
    return result


def validate_overview(brief):
    require(isinstance(brief, dict) and brief.get("schema") == 1
            and brief.get("kind") == "workflow-overview", "Expected workflow-overview schema 1")
    _no_secrets(brief)
    intake = _normalize_intake(brief.get("intake"))
    require(brief.get("intake_digest") == digest(intake), "Overview intake changed; regenerate its derived scope")
    expected = generate_overview(intake, character_policy=brief.get("character_policy", "legacy-v1"))
    for key in ("id", "target", "steps", "human_gates", "character_graph", "blockers", "budget", "grants_authorization"):
        require(brief.get(key) == expected[key], "Overview derived field changed or required work omitted: " + key)
    readiness = brief.get("host_readiness")
    require(isinstance(readiness, dict) and isinstance(readiness.get("ok"), bool), "Overview needs explicit host discovery status")
    if readiness.get("ok"):
        require(_text(readiness.get("host_id")) and _text(readiness.get("session_id"))
                and _text(readiness.get("report_digest")) and _text(readiness.get("checked_at")),
                "A ready overview must reference its actual host report; recheck it before execution")
    return {"ok": True, "id": brief["id"], "style_count": intake["style_count"],
            "character_state": brief["character_graph"]["state"], "blockers": brief["blockers"],
            "grants_authorization": False, "host_readiness_is_historical_snapshot": True}


def render_overview(brief):
    validate_overview(brief)
    value, target = brief["intake"], brief["target"]
    lines = ["Workflow overview — " + brief["id"], "", "Goal: " + "; ".join(value["goals"]),
             f"Output: {target.get('authoring_carrier', target['engine'])} · {target['style_count']} style(s) · {target['delivery_mode']}",
             f"Input: {value['input']['mode']} · baseline {target['baseline_status']} · adapter {target['adapter_status']}", ""]
    lines.extend(f"{i}. {step['work']}" + (" → " + step["human_gate"] if step["human_gate"] else "")
                 for i, step in enumerate(brief["steps"], 1))
    character = brief["character_graph"]
    lines.extend(["", "Character: " + character["state"] + " · " +
                  ", ".join(f"{key}={value['character'][key]}" for key in
                            ("presence", "deformation", "rig", "animation", "retarget"))])
    for branch in value["branches"]:
        lines.append(f"Branch {branch['id']}: {branch['status']} · {branch['note']}")
    providers = ", ".join(p["id"] + "=" + p["status"] for p in value["providers"]) or "not inventoried"
    lines.extend(["Suppliers (declared): " + providers,
                  "Host: " + brief["host_readiness"].get("collaboration", "sequential_fallback"),
                  "Investment: preliminary; exact options and spending are confirmed at H3."])
    if brief["host_readiness"].get("status") == "not_supplied":
        lines.append("Open: host tools have not been inventoried for this session")
    for missing in brief["host_readiness"].get("blockers", []):
        lines.append("Missing tool: " + missing["operation"] + " · " + missing["reason"])
    lines.extend("Open: " + item for item in brief["blockers"])
    lines.append("This overview grants no production or spending authorization.")
    return "\n".join(lines) + "\n"


# Functional meanings of supplier operations, not a closed supplier/model list.
_SUPPLIER_FUNCTIONS = {
    "image_to_3d": {"model_generation"}, "text_to_3d": {"model_generation"},
    "character_generate": {"model_generation"}, "rig": {"rig"},
    "auto_rig": {"rig"}, "animation": {"motion_generate"},
    "motion_generate": {"motion_generate"}, "retarget": {"retarget"},
    "remesh": {"mesh_edit"}, "retopology": {"mesh_edit"},
    "cleanup": {"mesh_edit"}, "export": {"asset_export"},
}


def validate_production_scope(brief, portfolio, base=None):
    """Link R3 supplier scope to the overview's necessary character functions.

    This is a plan-completeness check, not tool execution or acceptance. A caller
    checks current capability/operation readiness separately. Legacy R2 callers
    need not call it. H3 binds this portfolio and its exact overview reference.
    Local/manual/reuse routes are valid; required work is never made paid merely
    to satisfy this contract. An explicit partial-batch deferral is retained as
    outstanding work rather than pretending characters are finished.
    """
    from .core import file_hash, read, resolve_input
    from pathlib import Path
    import re

    validate_overview(brief)
    require(isinstance(portfolio, dict), "Production portfolio must be an object")
    _no_secrets(portfolio)

    def evidence(record):
        require(isinstance(record, dict) and _text(record.get("path"))
                and re.fullmatch(r"[a-f0-9]{64}", str(record.get("sha256", ""))) is not None,
                "Functional evidence needs path and SHA-256")
        path = Path(record["path"])
        require(path.is_absolute() or base is not None, "Relative functional evidence needs its project base")
        path = resolve_input(record["path"], base) if base is not None else path.resolve()
        require(path.is_file() and file_hash(path) == record["sha256"],
                "Functional evidence is missing or changed")
        return path

    overview_path = evidence(portfolio.get("overview"))
    require(digest(read(overview_path)) == digest(brief), "Portfolio references a different workflow overview")
    graph = brief["character_graph"]
    assets = portfolio.get("character_assets", [])
    require(isinstance(assets, list) and all(safe_id(a) for a in assets)
            and len(assets) == len(set(assets)), "Character assets need unique stable IDs")
    required_assets = portfolio.get("required_assets", [])
    require(isinstance(required_assets, list) and set(assets) <= set(required_assets),
            "Character assets must belong to this portfolio's actual asset scope")
    options = portfolio.get("options", [])
    require(isinstance(options, list) and options, "Production scope needs portfolio options")
    if graph["state"] == "skipped":
        require(not assets and not portfolio.get("character_deferral"),
                "No-character overview cannot hide a character asset scope")
        require(all(not option.get("character_work") for option in options),
                "No-character scope cannot contain character work")
        return {"ok": True, "character_state": "skipped", "character_assets": [],
                "deferred": False, "grants_authorization": False}
    deferral = portfolio.get("character_deferral")
    if deferral is not None:
        require(not assets and isinstance(deferral, dict)
                and deferral.get("scope") == "excluded_from_this_batch" and _text(deferral.get("reason")),
                "Character deferral must explicitly exclude this batch, with a reason and no character assets")
        require(all(not option.get("character_work") for option in options),
                "Deferred character work cannot be partly hidden in this batch")
        return {"ok": True, "character_state": graph["state"], "character_assets": [],
                "deferred": True, "remaining_nodes": [node["id"] for node in graph["nodes"]],
                "note": "Partial batch only; required character work remains outstanding for final delivery",
                "grants_authorization": False}
    require(graph["state"] == "planned", "Resolve character needs before its dependent production scope")
    require(assets, "Required character work must name scoped character_assets or an explicit partial-batch deferral")
    nodes = {node["id"]: node for node in graph["nodes"]}
    summaries = []
    for option in options:
        operations = {operation["id"]: operation for operation in option.get("operations", [])}
        entries = {entry["asset_id"]: entry for entry in option.get("assets", [])}
        require(set(assets) <= set(entries), "Every option must include each scoped character asset")
        work = option.get("character_work")
        require(isinstance(work, list), "Every option needs complete character_work coverage")
        covered = {asset: {node_id: set() for node_id in nodes} for asset in assets}
        for record in work:
            require(isinstance(record, dict) and record.get("asset_id") in covered
                    and record.get("node_id") in nodes, "Character work refers to another asset or an undeclared node")
            asset, node_id = record["asset_id"], record["node_id"]
            capabilities = record.get("capabilities")
            require(isinstance(capabilities, list) and capabilities and all(safe_id(c) for c in capabilities)
                    and len(capabilities) == len(set(capabilities)), "Character work needs explicit unique functional capabilities")
            needed = set(nodes[node_id]["required_tools"])
            declared = set(capabilities)
            require(declared <= needed and not (declared & covered[asset][node_id]),
                    "Character work has extra or duplicate functional coverage")
            route = record.get("route")
            require(route in {"supplier", "local", "manual", "reuse"}, "Unknown character work route")
            if (brief.get("character_policy") == CHARACTER_POLICY
                    and declared & {"mesh_edit", "rig", "motion_generate", "retarget"} and route != "reuse"):
                require(_text(record.get("route_reason")), "Necessary character processing needs a route_reason covering suitability and effort")
                if route in {"local", "manual"}:
                    require(_text(record.get("supplier_evaluation")),
                            "Local/manual processing needs supplier_evaluation: assess suitable installed supplier operations before custom work")
            if route == "supplier":
                operation = operations.get(record.get("operation_id"))
                require(operation is not None and operation.get("asset_id") == asset
                        and operation["id"] in entries[asset].get("operation_ids", []),
                        "Character supplier work must bind the same asset's costed operation")
                # Exact semantic names permit new suppliers without a core enum.
                supported = _SUPPLIER_FUNCTIONS.get(operation.get("operation"), {operation.get("operation")})
                require(declared <= supported,
                        "Supplier operation does not implement the declared character function")
            elif route == "local":
                channel = record.get("channel", {})
                require(isinstance(channel, dict) and channel.get("kind") in {"cli", "mcp", "host_tool", "api"}
                        and _text(channel.get("target")) and isinstance(channel.get("supports"), list)
                        and declared <= set(channel["supports"]),
                        "Local character work needs an exact channel supporting its functions")
                records = record.get("evidence")
                require(isinstance(records, list) and records, "Local character work needs hash-bound channel evidence")
                for item in records:
                    evidence(item)
            elif route == "manual":
                handoff = record.get("handoff", {})
                require(isinstance(handoff, dict) and _text(handoff.get("owner"))
                        and _text(handoff.get("action")) and _text(handoff.get("resume_requirement")),
                        "Manual character work needs an owner, action and resumable evidence requirement")
            else:
                require(node_id != "character_model", "New character model production cannot be silently replaced by reuse")
                records = record.get("evidence")
                require(isinstance(records, list) and records, "Reused character work needs hash-bound existing evidence")
                for item in records:
                    evidence(item)
            covered[asset][node_id].update(declared)
        for asset in assets:
            for node_id, node in nodes.items():
                require(covered[asset][node_id] == set(node["required_tools"]),
                        "Portfolio omits required character function: " + asset + "/" + node_id)
        summaries.append({"option_id": option.get("id"), "character_assets": list(assets),
                          "required_nodes": list(nodes)})
    return {"ok": True, "character_state": graph["state"], "character_assets": list(assets),
            "deferred": False, "options": summaries, "grants_authorization": False,
            "note": "Functional plan coverage only; current tools, actual outputs and native H4/H5 acceptance remain separate"}
