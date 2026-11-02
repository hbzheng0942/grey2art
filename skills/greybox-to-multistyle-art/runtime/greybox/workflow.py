"""Fail-closed revisioned creative checkpoints, not an approval authority.

The host must record actual user messages and native evidence. Hash binding detects
stale/cross-scope receipts; editable local JSON cannot authenticate a human or prove
artistic quality. Operational capability refreshes never rewrite creative decisions.
"""
from __future__ import annotations

from pathlib import Path
from datetime import datetime, timezone
import re
from .core import require, read, file_hash, resolve_input, inside, safe_id, digest

SHARED = ("preflight", "baseline", "directions", "selection")
STYLED = ("atlas", "spatial_design", "art_proxy", "production_plan")
HUMAN_STAGES = {"selection", "atlas", "spatial_design", "production_plan", "representative_sample"}
TECHNICAL_CHECKS = {"material_calibration", "scale_fit", "assembly_seams"}
LEGACY_PRODUCTION_POLICY = "image-conditioned-v1"
PREVIOUS_PRODUCTION_POLICY = "complete-visual-sample-v2"
PRODUCTION_POLICY = "asset-routed-visual-sample-v3"
HISTORICAL_PRODUCTION_POLICIES = {LEGACY_PRODUCTION_POLICY, PREVIOUS_PRODUCTION_POLICY}
ROLES = {
    "preflight": {"capability_report"},
    "baseline": {"spatial_contract", "native_baseline"},
    "directions": {"concept_image", "directions_manifest"},
    "selection": {"selection_decision"},
    "atlas": {"concept_image", "atlas_manifest"},
    "spatial_design": {"plan_view", "spatial_graph", "section_or_volume"},
    "art_proxy": {"native_proxy", "risk_review"},
    "production_plan": {"production_table", "assembly_recipe", "scope_decision"},
    "representative_sample": {"sample_source_production", "sample_inputs", "native_sample", "native_capture", "visual_review", "technical_report", "gameplay_report"},
}


def _hash(value):
    return isinstance(value, str) and re.fullmatch(r"[a-f0-9]{64}", value) is not None


def _text(value):
    return isinstance(value, str) and bool(value.strip())


def _ids(value, label, nonempty=True):
    require(isinstance(value, list) and (bool(value) or not nonempty)
            and all(safe_id(x) for x in value) and len(value) == len(set(value)),
            label + " needs unique stable IDs" + (" (nonempty)" if nonempty else ""))
    return set(value)


def execution_plan_digest(plan):
    """Bind all executable/creative fields, excluding only receipt recursion.

    No generic metadata exemption: changes to assets, bindings, policy, budgets,
    contracts, work units or style content all invalidate production authorization.
    Operational receipts are not executable plan fields and are checked separately.
    """
    return digest({k: v for k, v in plan.items() if k not in {"workflow", "operational_receipts"}})


def stage_digest(stage):
    """The exact revision/artifacts/dependencies approved; no circular approval."""
    return digest({k: v for k, v in stage.items() if k not in {
        "status", "actor", "recorded_by", "decision_note", "approval", "authorization"}})


def dependencies(sid, scope):
    """Creative DAG. Capability refresh deliberately has no creative descendants."""
    shared = {"preflight": [], "baseline": [], "directions": ["shared/baseline"],
              "selection": ["shared/directions"]}
    if sid in shared:
        require(scope == "shared", "Shared stages must have shared scope")
        return shared[sid]
    require(scope != "shared", "Style stages need a selected style scope")
    by_stage = {
        "atlas": ["shared/baseline", "shared/selection"],
        "spatial_design": ["shared/baseline", "shared/selection", scope + "/atlas"],
        "art_proxy": [scope + "/spatial_design"],
        "production_plan": [scope + "/atlas", scope + "/spatial_design", scope + "/art_proxy"],
        "representative_sample": [scope + "/production_plan"],
    }
    require(sid in by_stage, "Unknown workflow stage")
    return by_stage[sid]


def check_capabilities(report, require_lux=False, concept_source="generate", expected_session=None,
                       required_capabilities=None, image_features=None):
    require(isinstance(report, dict) and report.get("schema") == 2,
            "Capability report needs schema 2 channel bindings; refresh-readiness without rewriting creative approvals")
    require(_text(report.get("session_id")), "Capability discovery must identify its actual host session")
    if expected_session:
        require(report["session_id"] == expected_session, "Capability report belongs to another host session; rediscover tools")
    try:
        checked = datetime.fromisoformat(str(report["checked_at"]).replace("Z", "+00:00"))
        age = (datetime.now(timezone.utc) - checked).total_seconds()
    except (ValueError, KeyError, TypeError):
        raise ValueError("Capability report needs a timezone-aware checked_at") from None
    require(-300 <= age <= 86400, "Capability receipt expired; rediscover the current tools without submitting paid work")
    require(concept_source in ("generate", "approved_import"), "Unknown concept source; no implicit fallback")
    declared = required_capabilities or []
    _ids(declared, "Required capabilities", False)
    required = set(declared) | {"engine", "native_capture"}
    if concept_source == "generate":
        required.add("image_generate")
    if require_lux:
        required.add("lux")
    blockers, bindings = [], {}
    for key in sorted(required):
        cap = report.get("capabilities", {}).get(key, {})
        channel = cap.get("channel", {})
        verification = cap.get("verification", {})
        kind, target = channel.get("kind"), channel.get("target")
        supported = channel.get("supports", [])
        valid_channel = (kind in {"host_tool", "mcp", "api", "cli", "bundled_openapi"}
                         and _text(target) and isinstance(supported, list)
                         and all(_text(feature) for feature in supported))
        if valid_channel and kind == "api":
            from urllib.parse import urlsplit
            url = urlsplit(target)
            valid_channel = url.scheme == "https" and bool(url.hostname) and not url.username and not url.query
        level = verification.get("level")
        verified = level in {"discovered", "connection_verified", "invocation_verified"} and _text(verification.get("evidence"))
        needed_features = (set(image_features if image_features is not None else {"text_to_image", "reference_image"}) if key == "image_generate" else
                           {"reference_image"} if key == "image_edit" else
                           {"screenshot"} if key == "native_capture" else set())
        if cap.get("status") != "available" or not _text(cap.get("interface")) or not _text(cap.get("evidence")):
            reason = "capability-unavailable"
        elif not valid_channel or not verified:
            reason = "channel-unbound-or-unverified"
        elif key in {"image_generate", "image_edit"} and kind not in {"host_tool", "mcp", "api", "cli"}:
            reason = "image-channel-must-be-discovered-on-host"
        elif not needed_features <= set(supported):
            reason = "required-feature-missing"
        elif key == "lux" and (kind != "bundled_openapi" or target != "greybox.lux"
                               or channel.get("region") not in {"cn", "international"}
                               or level not in {"connection_verified", "invocation_verified"}):
            reason = "bundled-lux-account-connection-required"
        else:
            bindings[key] = {"kind": kind, "target": target, "verification": level}
            continue
        blockers.append({"capability": key, "state": cap.get("status", "unverified"), "reason": reason,
                         "next": "Discover/configure the exact callable channel and required reference/capture features; verify Lux account without generation when used. No silent provider substitution."})
    return {"ok": not blockers, "blockers": blockers, "bindings": bindings,
            "note": "Channel/interface evidence is host-reported, not authentication. Discovered image tools are not a paid invocation test; first authorized output proves invocation."}


def plan_capability_requirements(plan, project):
    declared = list(plan.get("required_capabilities", []))
    reference = plan.get("workflow", {}).get("path")
    if reference:
        declared.extend(read(resolve_input(reference, project)).get("required_capabilities", []))
    result = sorted(set(declared))
    _ids(result, "Required capabilities", False)
    return result


def check_plan_capabilities(plan, project, report, expected_session=None):
    reference = plan.get("workflow", {}).get("path")
    data = read(resolve_input(reference, project)) if reference else {}
    generated = [a["generation"] for a in plan.get("assets", []) if a.get("generation")]
    result = check_capabilities(report, bool(generated) or data.get("requires_lux", False),
                                data.get("concept_source", "generate"), expected_session,
                                plan_capability_requirements(plan, project),
                                plan.get("required_image_features", data.get("required_image_features")))
    if result["ok"] and generated:
        bound_region = report["capabilities"]["lux"]["channel"]["region"]
        if any(g["region"] != bound_region for g in generated):
            result["ok"] = False
            result["blockers"].append({"capability": "lux", "state": "region-mismatch",
                "reason": "Every task region must match this run's verified Lux account region",
                "next": "Verify the intended account region or separate regional production runs"})
    return result


def _image(path):
    with path.open("rb") as f:
        raw = f.read(12)
    return raw.startswith(b"\x89PNG\r\n\x1a\n") or raw.startswith(b"\xff\xd8\xff") or (raw[:4] == b"RIFF" and raw[8:12] == b"WEBP")


def _evidence(stage, project, decode_images=False):
    result, ids = {}, set()
    require(isinstance(stage.get("evidence"), list), "Stage evidence must be a list")
    for item in stage["evidence"]:
        require(isinstance(item, dict) and _text(item.get("role")) and _text(item.get("path")) and _hash(item.get("sha256")), "Evidence needs role/path/sha256")
        p = resolve_input(item["path"], project)
        require(inside(p, project) and p.is_file(), "Stage evidence missing or outside project")
        require(file_hash(p) == item["sha256"], "Stage evidence changed; dependent approval is stale")
        if item["role"] in {"concept_image", "native_capture", "bom_board", "assembly_map", "proxy_capture"}:
            require(_image(p), "Concept/native image must contain native image bytes, not a prompt/path placeholder")
            require(safe_id(item.get("id")) and item["id"] not in ids, "Image evidence needs unique stable IDs")
            ids.add(item["id"])
            if decode_images:
                from .modeling_refs import _decode
                _decode(p.read_bytes())
        if item["role"] == "concept_image":
            require(item.get("origin") in ("host_generated", "user_provided"), "Record actual concept provenance")
            require(_text(item.get("provenance_note")), "Concept image needs its real generation receipt/reference or user provenance")
        result.setdefault(item["role"], []).append(p)
    return result


def _one(evidence, role):
    require(len(evidence.get(role, [])) == 1, "Stage requires exactly one " + role)
    value = read(evidence[role][0])
    require(isinstance(value, dict), role + " must be a JSON object")
    return value


def _sample_input_dependencies(manifest, project):
    """Verify H4's actual inputs, including discoverable native dependencies.

    This iteration supports project-contained resources only. No external path or
    symlink escape is authorized by a manifest. Computed/dynamic resource paths
    must be declared in files; a folder scan would invalidate unrelated expansion.
    """
    require(isinstance(manifest, dict) and manifest.get("schema") == 2
            and manifest.get("kind") == "sample-inputs", "Expected sample-inputs schema 2")
    from .core import runtime_snapshot
    require(_hash(manifest.get("producer_runtime_digest"))
            and manifest["producer_runtime_digest"] == runtime_snapshot()["sha256"],
            "Sample producer runtime changed; previous H4 does not validate current assembly rules")
    require(safe_id(manifest.get("style_id")) and _text(manifest.get("scene"))
            and _text(manifest.get("baseline_scene")), "Sample inputs need style/native scene/baseline identity")
    items = manifest.get("files")
    require(isinstance(items, list) and items, "Sample inputs must record actual source/assets/render configuration files")
    _ids([item.get("id") for item in items if isinstance(item, dict)], "Sample input files")
    records = {}
    for item in items:
        require(isinstance(item, dict) and safe_id(item.get("id")) and _text(item.get("path"))
                and _hash(item.get("sha256")) and item.get("category") in {"source", "asset", "render_config"},
                "Sample input entries need id/path/sha256 and source/asset/render_config category")
        path = resolve_input(item["path"], project)
        require(inside(path, project), "Sample inputs must remain inside project; external dependency roots are not supported here")
        require(path.is_file(), "Sample input file is missing")
        require(str(path) not in records, "Sample inputs contain duplicate canonical file paths")
        actual = file_hash(path)
        require(actual == item["sha256"], "Sample input file changed; previous H4 no longer covers current source/asset/render configuration")
        records[str(path)] = {"path": str(path), "sha256": actual, "category": item["category"]}
    from . import engines
    native_plan = {"engine": manifest.get("engine") or engines.name(project=project), "contract": {
        "scene": manifest["scene"], "source_paths": list(records)}}
    for config in engines.configuration_files(project, native_plan):
        project_config = str(config.resolve())
        require(project_config in records and records[project_config]["category"] == "render_config",
                "Sample inputs must include " + config.name + " render configuration")
    for field in ("scene", "baseline_scene"):
        path = resolve_input(manifest[field], project)
        require(inside(path, project) and str(path) in records and records[str(path)]["category"] == "source",
                "Sample inputs must include actual native and baseline scene source files")
    # Native scene/text references, including assembly JSON and shader/material
    # references, are traversed by the existing read-only engine adapter. An added
    # independent file is ignored; a newly referenced dependency cannot be omitted.
    discovered = engines.dependency_snapshot(project, native_plan)
    require({item["path"] for item in discovered} <= set(records),
            "Sample inputs omit a discoverable native source/asset/render dependency")
    importable = {".glb", ".gltf", ".fbx", ".obj", ".blend", ".png", ".jpg", ".jpeg", ".webp", ".exr"}
    for item in discovered:
        path = Path(item["path"])
        sidecar = engines.import_sidecar(path, engines.name(native_plan, project))
        if path.suffix.lower() in importable and sidecar.is_file():
            require(str(sidecar.resolve()) in records, "Sample inputs omit current asset import/render settings")
    return [{"path": p, "sha256": records[p]["sha256"]} for p in sorted(records)]


def evidence_dependencies(workflow_path, project):
    """Read-only dependency walker for core snapshots/status/validation.

    Returns sorted unique {path:absolute, sha256:current} file records, excluding
    the workflow file itself. Direct evidence and recursively archived production
    evidence are verified. Schema2 sample-inputs manifests contribute their actual
    resource dependencies. Schema1 frozen records do not acquire new requirements.
    This verifies evidence integrity only, never approval or creative readiness.
    """
    path = resolve_input(workflow_path, project)
    require(inside(path, project) and path.is_file(), "Workflow receipt missing or outside project")
    data = read(path)
    schema2 = data.get("schema") == 2
    found, active, traversed = {}, set(), set()

    def add_file(path, expected):
        require(inside(path, project) and path.is_file(), "Workflow evidence dependency missing or outside project")
        actual = file_hash(path)
        require(_hash(expected) and actual == expected, "Workflow evidence dependency changed")
        require(str(path) not in found or found[str(path)] == actual, "Conflicting workflow dependency hashes")
        found[str(path)] = actual

    def visit(stage, depth=0):
        require(isinstance(stage, dict) and isinstance(stage.get("evidence", []), list) and depth <= 32,
                "Invalid or excessively nested archived workflow evidence")
        for item in stage.get("evidence", []):
            require(isinstance(item, dict) and _text(item.get("path")), "Workflow evidence needs a path")
            dep = resolve_input(item["path"], project)
            add_file(dep, item.get("sha256"))
            role = item.get("role")
            if role == "sample_source_production":
                require(str(dep) not in active, "Cyclic archived production evidence")
                if str(dep) not in traversed:
                    active.add(str(dep))
                    visit(read(dep), depth + 1)
                    active.remove(str(dep))
                    traversed.add(str(dep))
            elif schema2 and role == "sample_inputs":
                for dependency in _sample_input_dependencies(read(dep), project):
                    add_file(Path(dependency["path"]), dependency["sha256"])
            elif schema2 and role == "production_table":
                table = read(dep)
                archived = table.get("sample_source_workflow")
                if archived is not None:
                    require(isinstance(archived, dict) and _text(archived.get("path")), "Frozen sample workflow needs a path")
                    archived_path = resolve_input(archived["path"], project)
                    add_file(archived_path, archived.get("sha256"))
                    require(str(archived_path) not in active, "Cyclic archived workflow context")
                    if str(archived_path) not in traversed:
                        active.add(str(archived_path))
                        for archived_stage in read(archived_path).get("stages", []):
                            visit(archived_stage, depth + 1)
                        active.remove(str(archived_path))
                        traversed.add(str(archived_path))
                reference = table.get("modeling_references")
                if reference is not None:
                    require(isinstance(reference, dict) and _text(reference.get("path")), "Modeling-reference package needs a path")
                    package_path = resolve_input(reference["path"], project)
                    add_file(package_path, reference.get("sha256"))
                    from . import modeling_refs
                    validated = modeling_refs.validate_package(read(package_path), project)
                    for dependency in validated["dependencies"]:
                        add_file(Path(dependency["path"]), dependency["sha256"])

    for stage in data.get("stages", []):
        visit(stage)
    return [{"path": p, "sha256": found[p]} for p in sorted(found)]


def _approval(stage):
    approval = stage.get("approval", {})
    require(stage.get("actor") == "user" and approval.get("actor") == "user",
            "Only record actual user approval; production scope authority cannot be self-authorized")
    require(approval.get("decision") == "accepted" and _text(approval.get("source_ref")),
            "User approval needs an actual decision source_ref; silence/agent inference is not approval")
    require(approval.get("scope") == stage["scope"] + "/" + stage["id"], "User approval belongs to another scope")
    require(approval.get("stage_digest") == stage_digest(stage), "User approval is stale for these stage artifacts/revision/inputs")
    return approval


def _directions(stage, evidence, concept_source):
    manifest = _one(evidence, "directions_manifest")
    require(manifest.get("schema") == 2 and manifest.get("kind") == "direction-manifest", "Expected direction-manifest schema 2")
    candidates = manifest.get("candidates", [])
    require(isinstance(candidates, list) and candidates, "Directions need actual candidate concepts")
    ids = [c.get("id") for c in candidates]
    _ids(ids, "Direction candidates")
    images = {e["id"]: e for e in stage["evidence"] if e["role"] == "concept_image"}
    used, hashes, signatures = set(), set(), []
    axes = ("theme", "shape_language", "material_language", "spatial_composition", "functional_identity")
    for candidate in candidates:
        image = images.get(candidate.get("concept_image_id"), {})
        require(image and image["sha256"] == candidate.get("concept_sha256"), "Direction must bind its actual concept image ID and hash")
        require(image["id"] not in used and image["sha256"] not in hashes, "Directions cannot reuse the same image as different candidates")
        used.add(image["id"]); hashes.add(image["sha256"])
        brief = candidate.get("brief", {})
        require(isinstance(brief, dict) and all(_text(brief.get(k)) for k in axes + ("light_palette",)), "Direction needs theme, shape, material, spatial, functional and lighting design briefs")
        signature = tuple(brief[k].strip().casefold() for k in axes)
        require(all(sum(a != b for a, b in zip(signature, other)) >= 2 for other in signatures),
                "Directions need at least two substantive declared design differences; palette changes alone do not count")
        signatures.append(signature)
    require(used == set(images), "Directions manifest must account for every candidate image")
    if not 8 <= len(candidates) <= 10:
        override = manifest.get("count_override", {})
        require(override.get("actor") == "user" and override.get("decision") == "accepted"
                and _text(override.get("source_ref")) and _text(override.get("reason"))
                and override.get("scope") == "shared/directions"
                and override.get("candidate_set_digest") == digest(candidates),
                "Directions default to 8–10; a different count needs explicit user scope bound to this candidate set")
    if concept_source == "approved_import":
        imported = manifest.get("import_approval", {})
        require(imported.get("actor") == "user" and imported.get("decision") == "accepted"
                and _text(imported.get("source_ref")) and imported.get("scope") == "shared/directions"
                and imported.get("candidate_set_digest") == digest(candidates),
                "approved_import requires actual user approval bound to the imported candidate set")
    return {c["id"]: c for c in candidates}


def _selection(evidence, styles, directions, directions_digest):
    decision = _one(evidence, "selection_decision")
    require(decision.get("schema") == 2 and decision.get("kind") == "style-selection", "Expected style-selection schema 2")
    require(decision.get("directions_digest") == directions_digest, "Selection is stale for the current directions revision")
    selected = decision.get("selected", [])
    require(isinstance(selected, list), "Selection needs selected image records")
    _ids([s.get("style_id") for s in selected], "Selected styles")
    require(set(styles) == {s["style_id"] for s in selected}, "Selection receipt must exactly match workflow selected styles")
    for item in selected:
        candidate = directions.get(item["style_id"])
        require(candidate and all(item.get(k) == candidate[k] for k in ("concept_image_id", "concept_sha256")),
                "Selection receipt does not bind the selected actual concept image")


def _spatial_scope(baseline):
    scope = baseline.get("spatial_scope")
    require(isinstance(scope, dict) and scope.get("mode") in {"finite", "large", "continuous"},
            "Current production needs baseline spatial_scope mode finite/large/continuous; do not infer route coverage from the atlas")
    spaces = _ids(scope.get("space_ids"), "Baseline spatial scope spaces")
    transitions = _ids(scope.get("transition_ids", []), "Baseline spatial scope transitions", False)
    segments = scope.get("segments", [])
    require(isinstance(segments, list) and all(isinstance(s, dict) for s in segments), "Baseline spatial scope segments must be objects")
    _ids([s.get("id") for s in segments], "Baseline spatial scope segments", scope["mode"] != "finite")
    covered = set()
    for segment in segments:
        member = _ids(segment.get("space_ids"), "Segment spaces")
        require(member <= spaces, "Baseline segment references unknown spaces")
        covered |= member
    if scope["mode"] in {"large", "continuous"}:
        require(len(segments) >= 2 and covered == spaces,
                "Large/continuous space needs at least two explicit regions/segments covering the whole baseline")
        if scope["mode"] == "continuous":
            require(transitions, "Continuous space needs declared shared transitions")
    return scope


def _spatial_design(graph, atlas, scope):
    focused = atlas.get("scope_mode") == "focused"
    spaces = set(atlas["required_space_ids"] if focused else scope["space_ids"])
    require(set(graph.get("space_ids", [])) == spaces, "Spatial graph must equal its approved detailed space scope")
    designs = graph.get("space_designs")
    require(isinstance(designs, list) and all(isinstance(d, dict) for d in designs),
            "Spatial design needs per-space art intent, invariants, freedom and near/mid/far composition")
    _ids([d.get("space_id") for d in designs], "Spatial design entries")
    require({d["space_id"] for d in designs} == spaces, "Spatial design must cover every approved detailed space")
    for design in designs:
        for field in ("art_intent", "gameplay_invariants", "visual_freedom", "foreground", "midground", "background"):
            require(_text(design.get(field)), "Spatial design entry needs " + field)
    boundaries = graph.get("boundaries", [])
    require(isinstance(boundaries, list) and all(isinstance(b, dict) for b in boundaries), "Spatial boundaries must be objects")
    _ids([b.get("id") for b in boundaries], "Spatial boundary IDs", False)
    require({b["id"] for b in boundaries} == set(atlas["required_transition_ids"] if focused else scope.get("transition_ids", [])),
            "Spatial design must bind every required shared transition")
    boundary_spaces = set(scope["space_ids"]) if focused else spaces
    global_boundaries = {b["id"]: b for b in atlas.get("global_layout", {}).get("boundaries", [])}
    for boundary in boundaries:
        require(boundary.get("from_space_id") in boundary_spaces and boundary.get("to_space_id") in boundary_spaces
                and boundary["from_space_id"] != boundary["to_space_id"]
                and _text(boundary.get("continuity_rule")),
                "Spatial boundary needs distinct known spaces and an explicit continuity/assembly rule")
        if focused:
            require(all(boundary.get(k) == global_boundaries[boundary["id"]][k]
                        for k in ("from_space_id", "to_space_id", "continuity_rule")),
                    "Focused boundary must preserve its approved global interface")


def _focused_scope(atlas, scope):
    """Keep global gameplay coverage while deepening only the current slice."""
    require(scope["mode"] in {"large", "continuous"}, "Focused atlas is for large/continuous spaces; finite scenes retain their complete scope")
    spaces = _ids(atlas["required_space_ids"], "Focused spaces")
    require(spaces <= set(scope["space_ids"]), "Focused spaces are outside the approved baseline")
    layout = atlas.get("global_layout", {})
    intents = layout.get("spaces", [])
    require(isinstance(intents, list) and all(isinstance(s, dict) and _text(s.get("intent")) for s in intents)
            and _ids([s.get("space_id") for s in intents], "Global coarse spaces") == set(scope["space_ids"]),
            "Focused atlas needs coarse intent for every baseline space; later regions remain in scope")
    boundaries = layout.get("boundaries", [])
    require(isinstance(boundaries, list) and all(isinstance(b, dict) for b in boundaries)
            and _ids([b.get("id") for b in boundaries], "Global coarse boundaries", False) == set(scope["transition_ids"]),
            "Focused atlas needs every baseline transition in the global coarse layout")
    touched = set()
    adjacent = {s: set() for s in spaces}
    for b in boundaries:
        endpoints = {b.get("from_space_id"), b.get("to_space_id")}
        require(len(endpoints) == 2 and endpoints <= set(scope["space_ids"]) and _text(b.get("continuity_rule")),
                "Global interface needs known distinct endpoints and a continuity rule")
        if endpoints & spaces:
            touched.add(b["id"])
        if endpoints <= spaces:
            a, z = tuple(endpoints); adjacent[a].add(z); adjacent[z].add(a)
    require(set(atlas["required_transition_ids"]) == touched,
            "Focused atlas must deepen all internal and entry/exit transitions touching its spaces")
    if scope["mode"] == "continuous":
        seen, todo = set(), [next(iter(spaces))]
        while todo:
            current = todo.pop()
            if current not in seen:
                seen.add(current); todo.extend(adjacent[current] - seen)
        require(seen == spaces, "Continuous first sample must be connected, not scattered attractive views")
    views = {v["id"]: v for v in atlas["views"]}
    require(all(set(v["space_ids"]) <= set(scope["space_ids"]) and set(v["space_ids"]) & spaces for v in views.values()),
            "Focused views must show approved baseline space and relate to the active slice")
    contract = atlas.get("focus_contract", {})
    require(_text(contract.get("playable_loop")), "Focused sample needs its concrete playable loop")
    for edge in ("entry", "exit"):
        record = contract.get(edge, {})
        view = views.get(record.get("view_id"))
        require(record.get("space_id") in spaces and view and record["space_id"] in view["space_ids"]
                and _text(record.get("interface")), "Focused sample needs an actual entry and exit view with interface constraints")
    require(contract["entry"]["view_id"] != contract["exit"]["view_id"],
            "Focused sample entry and exit must have distinct actual observations")


def _atlas(stage, evidence, direction, spatial_scope=None):
    atlas = _one(evidence, "atlas_manifest")
    require(atlas.get("schema") == 2 and atlas.get("kind") == "concept-atlas" and atlas.get("style_id") == stage["scope"], "Expected concept-atlas schema 2 for this style")
    require(atlas.get("direction_concept_sha256") == direction["concept_sha256"], "Atlas uses a stale selected concept")
    images = {e["id"]: e["sha256"] for e in stage["evidence"] if e["role"] == "concept_image"}
    views = atlas.get("views", [])
    require(isinstance(views, list) and views, "Atlas needs actual key-scene/transition views")
    _ids([v.get("id") for v in views], "Atlas views")
    for view in views:
        require(view.get("concept_image_id") in images and images[view["concept_image_id"]] == view.get("concept_sha256"), "Atlas view must bind actual concept image bytes")
        require(_text(view.get("camera_id")) and view.get("role") in ("key_scene", "transition"), "Atlas views need camera identity and scene/transition role")
        _ids(view.get("space_ids"), "Atlas view spaces")
    required_spaces = _ids(atlas.get("required_space_ids"), "Atlas required spaces")
    required_transitions = _ids(atlas.get("required_transition_ids", []), "Atlas required transitions", False)
    require(required_spaces <= {s for v in views for s in v["space_ids"]}, "Atlas is missing required spatial coverage")
    require(required_transitions <= {v.get("transition_id") for v in views if v["role"] == "transition"}, "Atlas is missing required transition coverage")
    require(set(images) == {v["concept_image_id"] for v in views}, "Atlas manifest must account for every concept image")
    if spatial_scope is not None:
        require(atlas.get("scope_mode", "full") in {"full", "focused"}, "Unknown atlas coverage mode")
        focused = atlas.get("scope_mode") == "focused"
        if focused:
            _focused_scope(atlas, spatial_scope)
        else:
            require(required_spaces == set(spatial_scope["space_ids"]), "Atlas coverage must match the approved baseline spaces; cannot shrink its own required_space_ids")
            require(required_transitions == set(spatial_scope.get("transition_ids", [])), "Atlas transitions must match the approved baseline transitions")
        if spatial_scope["mode"] in {"large", "continuous"}:
            key_views = [v for v in views if v["role"] == "key_scene"]
            segment_ids = {s["id"] for s in spatial_scope["segments"] if not focused or set(s["space_ids"]) & required_spaces}
            require({v.get("segment_id") for v in key_views} == segment_ids,
                    "Large/continuous atlas needs a distinct key-scene expansion for every baseline region/segment")
            require(len({v["concept_image_id"] for v in key_views}) >= len(segment_ids)
                    and len({v["concept_sha256"] for v in key_views}) >= len(segment_ids)
                    and len({v["camera_id"] for v in key_views}) >= len(segment_ids),
                    "Regional/segment expansions need distinct actual images and cameras; a single overview cannot substitute")
            for segment in spatial_scope["segments"]:
                required = set(segment["space_ids"]) & required_spaces if focused else set(segment["space_ids"])
                require(required <= {s for v in key_views if v.get("segment_id") == segment["id"] for s in v["space_ids"]},
                        "Atlas regional key scenes omit spaces in their baseline segment")
    return atlas


def _native_realization(assembly, image_ids=None):
    """Validate declared native work ownership, never certify its execution."""
    realization = assembly.get("native_realization")
    if realization is None:
        return False
    require(isinstance(realization, dict)
            and set(realization) == {"kind", "target", "method", "evidence_image_id"}
            and realization.get("kind") in {"material", "lighting", "shader", "vfx", "environment"}
            and _text(realization.get("target")) and _text(realization.get("method"))
            and safe_id(realization.get("evidence_image_id")),
            "Native realization needs kind, actual scene/node/material target, method and evidence image; mesh production stays in asset proposals")
    if image_ids is not None:
        require(realization["evidence_image_id"] in image_ids,
                "Native realization must bind actual H3 BOM or assembly image evidence")
    return True


def _assembly(recipe, table, spatial_scope, spatial_design_digest):
    require(recipe.get("spatial_design_digest") == spatial_design_digest,
            "Assembly recipe must bind this style's approved spatial design")
    proposals = table.get("asset_proposals")
    require(isinstance(proposals, list) and all(isinstance(p, dict) for p in proposals),
            "Production table needs an actual per-asset/source proposal list")
    asset_ids = _ids([p.get("asset_id") for p in proposals], "Production asset proposals", False)
    for proposal in proposals:
        require(proposal.get("route") in {"reuse", "procedural", "generated", "hybrid"} and _text(proposal.get("reason")),
                "Production asset proposal needs route and task-specific rationale")
        generation = proposal.get("generation")
        if generation is not None:
            require(isinstance(generation, dict) and generation.get("operation") in {
                "image_to_3d", "multiview_to_3d", "remesh", "articulate", "rig", "retarget", "material_transfer", "export"},
                    "New mesh production must use image_to_3d or multiview_to_3d; text_to_3d cannot preserve approved style")
            require(proposal["route"] in {"generated", "hybrid"}, "Reuse/procedural proposal cannot conceal a generation task")
    assemblies = recipe.get("assemblies")
    require(isinstance(assemblies, list) and assemblies and all(isinstance(a, dict) for a in assemblies),
            "Assembly recipe needs actual placement/fitting/material/seam work units")
    assembly_ids = _ids([a.get("id") for a in assemblies], "Assembly units")
    covered_assets, graph = set(), {}
    for assembly in assemblies:
        require(_ids(assembly.get("space_ids"), "Assembly spaces") <= set(spatial_scope["space_ids"]), "Assembly references unknown baseline spaces")
        native = _native_realization(assembly)
        sources = _ids(assembly.get("asset_ids"), "Assembly asset IDs", not native)
        require(sources <= asset_ids, "Assembly references assets missing from the production table")
        covered_assets |= sources
        for field in ("anchor_and_support", "scale_and_fit", "material_and_lighting", "seam_integration"):
            require(_text(assembly.get(field)), "Assembly unit needs " + field)
        deps = _ids(assembly.get("depends_on", []), "Assembly dependencies", False)
        require(deps <= assembly_ids and assembly["id"] not in deps, "Assembly dependency is unknown or self-referential")
        graph[assembly["id"]] = deps
    require(covered_assets == asset_ids, "Assembly recipe omits proposed assets")
    remaining = dict(graph)
    while remaining:
        ready = {key for key, deps in remaining.items() if not deps & set(remaining)}
        require(ready, "Assembly recipe dependencies contain a cycle")
        remaining = {key: deps for key, deps in remaining.items() if key not in ready}
    return proposals


COMPOSITION_LAYERS = {"major_forms", "environment", "functional_objects", "contact", "lighting_materials"}


def _observations(baseline):
    contract = baseline.get("observations", {})
    views = contract.get("views")
    require(isinstance(views, list) and views and all(isinstance(v, dict) for v in views),
            "Baseline needs observation views/states for whole composition and gameplay")
    _ids([v.get("id") for v in views], "Observation view IDs")
    for view in views:
        require(safe_id(view.get("camera_id")) and safe_id(view.get("state_id"))
                and view.get("framing") in {"whole_composition", "interaction"}, "Observation needs camera/state/framing")
        require(_ids(view.get("space_ids"), "Observation spaces") <= set(baseline["spatial_scope"]["space_ids"]),
                "Observation references unknown spaces")
        require(_ids(view.get("required_layers"), "Observation required layers") <= COMPOSITION_LAYERS,
                "Unknown observation composition layer")
    require(any(v["framing"] == "whole_composition" and COMPOSITION_LAYERS <= set(v["required_layers"]) for v in views),
            "Observations need a whole-composition view covering environment, major forms, functional objects, contact and lighting")
    _ids(contract.get("risk_ids", []), "Observation risk IDs", False)
    return contract


def _capture_coverage(manifest, stage, views, role, project, *, proxy=False):
    captures = manifest.get("captures")
    require(isinstance(captures, list) and captures and all(isinstance(c, dict) for c in captures),
            "Native composition evidence needs captures")
    images = {e["id"]: e for e in stage["evidence"] if e["role"] == role}
    expected = {v["id"]: v for v in views}
    covered = set()
    for capture in captures:
        view = expected.get(capture.get("view_id"))
        item = images.get(capture.get("image_id"))
        require(view and item and capture.get("sha256") == item["sha256"]
                and str(resolve_input(capture.get("path", ""), project)) == str(resolve_input(item["path"], project)),
                "Composition capture must bind an actual view and image")
        require(all(capture.get(k) == view[k] for k in ("camera_id", "state_id", "framing")),
                "Composition capture has wrong camera/state/framing")
        layers = _ids(capture.get("visible_layers"), "Capture visible layers", proxy is False)
        missing = _ids(capture.get("missing_layers", []), "Capture missing layers", False)
        require(not layers & missing and layers | missing == set(view["required_layers"]),
                "Capture must account for every required composition layer")
        require(proxy or not missing, "H4 complete sample cannot have missing composition layers")
        covered.add(view["id"])
    require(covered == set(expected) and {c["image_id"] for c in captures} == set(images),
            "Native captures omit required view/state coverage or contain unaccounted images")


def _proxy(stage, evidence, observation_contract, project):
    manifest = _one(evidence, "native_proxy")
    require(manifest.get("schema") == 1 and manifest.get("kind") == "composition-probe"
            and manifest.get("scope") == stage["scope"] and manifest.get("purpose") == "risk_and_composition_only",
            "S6 needs a composition probe; it is not a finished playable art sample")
    _capture_coverage(manifest, stage, observation_contract["views"], "proxy_capture", project, proxy=True)
    risks = _one(evidence, "risk_review")
    records = risks.get("risks")
    require(isinstance(records, list) and all(isinstance(r, dict) for r in records), "S6 needs explicit risk observations")
    require(_ids([r.get("id") for r in records], "S6 observed risks", False) == set(observation_contract["risk_ids"]),
            "S6 omits required spatial/composition risk coverage")
    for record in records:
        require(record.get("status") in {"resolved", "unresolved"} and _text(record.get("observation"))
                and (record["status"] == "resolved" or _text(record.get("next_action"))),
                "S6 unresolved risk needs an observation and next action")
    require(not any(r["status"] == "unresolved" for r in records), "S6 unresolved production risk blocks H3")


def _visual_package(table, recipe, stage, evidence, atlas, observations, *, routed=False):
    contract = table["sample_contract"]
    require(table.get("scope_mode") in {"complete_sample", "expansion"},
            "H3 must name complete_sample or expansion scope; the original H4 sample contract stays frozen")
    views = _ids(contract.get("required_view_ids"), "Sample required views")
    all_views = {v["id"]: v for v in observations["views"]}
    sample_spaces = _ids(contract.get("sample_space_ids"), "Complete sample spaces")
    require(sample_spaces <= set(atlas["required_space_ids"]),
            "Sample spaces need their approved detailed H2 atlas; global coarse intent does not authorize production")
    require(sample_spaces <= {space for view in all_views.values() for space in view["space_ids"]},
            "Complete sample references unknown observation spaces")
    expected_views = {v["id"] for v in all_views.values() if sample_spaces & set(v["space_ids"])}
    require(views == expected_views and any(all_views[v]["framing"] == "whole_composition" for v in views),
            "Sample needs every approved view/state for its spaces, including whole-composition observation coverage")
    assembly_spaces = {space for unit in recipe["assemblies"] for space in unit["space_ids"]}
    if table["scope_mode"] == "complete_sample":
        require(sample_spaces == assembly_spaces, "Complete-sample assembly spaces differ from its approved scope")
    else:
        require(_hash(contract.get("source_production_digest")), "Expansion needs its original accepted sample production identity")
        production_spaces = _ids(table.get("production_space_ids"), "Expansion production spaces")
        require(production_spaces <= set(atlas["required_space_ids"]) and production_spaces == assembly_spaces,
                "Expansion assembly spaces must equal its current approved production scope")
        views = _ids(table.get("production_view_ids"), "Expansion production views")
        require(views == {v["id"] for v in all_views.values() if production_spaces & set(v["space_ids"])},
                "Expansion must cover every approved observation for its current production spaces")
    require(COMPOSITION_LAYERS <= _ids(contract.get("required_composition_layers"), "Sample composition layers"),
            "Complete sample must include environment, major forms, functional objects, contact and lighting")
    owners = table.get("composition_owners", {})
    require(isinstance(owners, dict) and set(owners) == COMPOSITION_LAYERS,
            "Every complete-sample visual layer needs an assembly owner; environment is formal work")
    for layer, unit_ids in owners.items():
        require(_ids(unit_ids, "Composition layer owners") <= {a["id"] for a in recipe["assemblies"]},
                "Composition layer references unknown assembly owners")
    proposals = {a["asset_id"]: a for a in table["asset_proposals"]}
    features = table.get("visual_features")
    require(isinstance(features, list) and features and all(isinstance(f, dict) for f in features),
            "H3 needs concept visual features mapped to responsible asset families or native assembly owners")
    feature_ids = _ids([f.get("id") for f in features], "Visual feature IDs")
    require(set(contract["required_critical_features"]) <= feature_ids, "Visual responsibility omits critical concept features")
    require(any(f.get("importance") == "dominant" for f in features), "H3 must identify dominant visual responsibility")
    image_ids = {e["id"]: e for e in stage["evidence"] if e["role"] in {"bom_board", "assembly_map"}}
    native_owners = {a["id"]: a for a in recipe["assemblies"] if _native_realization(a, image_ids)}
    if routed:
        from .asset_routes import validate_routes
        validate_routes(table, image_ids)
    package = _one(evidence, "visual_package")
    require(package.get("schema") == 1 and package.get("kind") == "production-visual-package"
            and package.get("style_id") == stage["scope"], "H3 needs a style-bound visual package")

    def region(record, role):
        item = image_ids.get(record.get("image_id"))
        require(item and item["role"] == role, "Visual package must bind actual BOM/assembly image IDs")
        box = record.get("region")
        require(isinstance(box, list) and len(box) == 4 and all(type(n) in {int, float} for n in box)
                and 0 <= box[0] < 1 and 0 <= box[1] < 1 and box[2] > 0 and box[3] > 0
                and box[0] + box[2] <= 1 and box[1] + box[3] <= 1, "BOM/assembly annotation needs a bounded normalized image region")

    bom = package.get("bom")
    require(isinstance(bom, list) and all(isinstance(b, dict) for b in bom), "H3 BOM must list its actual source families")
    require(_ids([b.get("asset_id") for b in bom], "BOM asset IDs", False) == set(proposals), "H3 BOM omits promised asset families")
    for entry in bom:
        region(entry, "bom_board")
        route = proposals[entry["asset_id"]]["route"]
        if route in {"generated", "hybrid"}:
            require(entry.get("reference_status") == "production_ready", "Generated source needs a production-ready BOM reference")
        elif route == "reuse":
            require(entry.get("reference_status") == "approved_reuse", "Reused source needs an approved reuse BOM reference")
        require(entry.get("reference_status") in {"production_ready", "approved_reuse", "procedural_design"},
                "H3 complete-sample BOM cannot label missing/reference-only design as production ready")
    annotations = package.get("assembly_annotations")
    require(isinstance(annotations, list) and all(isinstance(a, dict) for a in annotations), "H3 needs actual assembly annotations")
    expected_assemblies = {a["id"]: set(a["asset_ids"]) for a in recipe["assemblies"]}
    require(_ids([a.get("assembly_id") for a in annotations], "Assembly annotation IDs") == set(expected_assemblies),
            "Assembly map omits planned assemblies")
    for annotation in annotations:
        region(annotation, "assembly_map")
        require(_ids(annotation.get("asset_ids"), "Annotated asset IDs", False) == expected_assemblies[annotation["assembly_id"]],
                "Assembly annotation assets differ from the recipe")
    used, used_native = set(), set()
    for proposal in proposals.values():
        if proposal["route"] == "generated" or (routed and proposal["route"] == "hybrid"):
            require(proposal.get("generation", {}).get("operation") in {"image_to_3d", "multiview_to_3d"},
                    "Generated visual route must name its actual image-conditioned generation operation")
    for feature in features:
        require(feature.get("concept_view_id") in {v["id"] for v in atlas["views"]}
                and feature.get("importance") in {"dominant", "supporting"}
                and feature.get("responsibility") in {"appearance", "precise_geometry", "environment"}
                and _text(feature.get("target")), "Visual feature needs actual concept view, importance, responsibility and target")
        assets = _ids(feature.get("asset_ids"), "Visual feature asset families", False)
        native_ids = _ids(feature.get("assembly_ids", []), "Visual feature native assembly owners", False)
        require(native_ids <= set(native_owners), "Visual feature references unknown or non-native assembly owners")
        require(assets or native_ids, "Visual feature needs asset families or a declared native assembly owner")
        require(feature["responsibility"] != "precise_geometry" or assets,
                "Precise geometry responsibility still requires actual asset families")
        require(all(set(native_owners[owner]["asset_ids"]) <= assets for owner in native_ids),
                "Visual feature omits its native assembly's asset families")
        require(assets <= set(proposals) and _ids(feature.get("native_view_ids"), "Feature native views") <= views,
                "Visual feature references unknown asset or observation")
        used |= assets
        used_native |= native_ids
        for asset_id in assets:
            proposal = proposals[asset_id]
            if feature["importance"] == "dominant" and feature["responsibility"] == "appearance":
                if proposal["route"] == "procedural":
                    match = proposal.get("procedural_visual_match", {})
                    require(_text(match.get("reason")) and match.get("evidence_image_id") in image_ids
                            and _text(match.get("observed_match")),
                            "Dominant procedural appearance needs target-match rationale and actual visual evidence; AI cannot be reserved for decorations")
                if proposal["route"] == "hybrid":
                    require(_text(proposal.get("generated_visual_role")) and _text(proposal.get("controlled_structure_role")),
                            "Hybrid needs explicit generated appearance and controlled structure responsibilities")
    require(used == set(proposals), "Visual responsibility omits production asset families")
    require(used_native == set(native_owners), "Visual responsibility omits native assembly owners")


def _production(scope, evidence, baseline_checks, baseline_scene, *, strict=False, spatial_scope=None,
                spatial_design_digest=None, project=None, selected_concept_sha256=None,
                current=False, stage=None, atlas=None, observations=None, routed=False):
    table, recipe = _one(evidence, "production_table"), _one(evidence, "assembly_recipe")
    for value, kind in ((table, "production-table"), (recipe, "assembly-recipe")):
        require(value.get("schema") == 2 and value.get("kind") == kind and value.get("style_id") == scope, "Expected " + kind + " schema 2 for this style")
        require(_hash(value.get("execution_plan_digest")), kind + " needs execution_plan_digest")
    require(table["execution_plan_digest"] == recipe["execution_plan_digest"], "Production table and assembly recipe refer to different executable plans")
    contract = table.get("sample_contract", {})
    if contract.get("scene_comparison") is not None:
        from .scene_review import CONTRACT
        require(contract["scene_comparison"] == CONTRACT, "Unknown scene comparison contract")
    require(contract.get("style_id") == scope and _text(contract.get("scene")) and _hash(contract.get("input_digest")), "Production sample contract needs style/scene/input identity")
    require(contract.get("baseline_scene") == baseline_scene, "Sample contract baseline_scene differs from approved gameplay scene")
    require(_hash(contract.get("execution_plan_digest")), "Sample contract needs its source execution_plan_digest")
    technical = _ids(contract.get("required_technical_checks"), "Required technical checks")
    require(TECHNICAL_CHECKS <= technical, "Sample requires material_calibration, scale_fit and assembly_seams checks")
    gameplay = _ids(contract.get("required_gameplay_checks"), "Required gameplay checks")
    require(baseline_checks <= gameplay, "Sample gameplay coverage omits required baseline checks")
    _ids(contract.get("required_critical_features"), "Required critical concept features")
    scope_decision = _one(evidence, "scope_decision")
    require(scope_decision.get("execution_plan_digest") == table["execution_plan_digest"]
            and scope_decision.get("style_id") == scope, "Production scope decision must bind the exact executable plan and style")
    if strict:
        proposals = _assembly(recipe, table, spatial_scope, spatial_design_digest)
        expected = [p["asset_id"] for p in proposals if p.get("generation", {}).get("operation") in {"image_to_3d", "multiview_to_3d"}]
        if expected:
            package = table.get("modeling_references", {})
            require(isinstance(package, dict) and _text(package.get("path")) and _hash(package.get("sha256")),
                    "Generated production needs a hashed modeling-reference package with actual image bytes")
            path = resolve_input(package["path"], project)
            require(inside(path, project) and path.is_file() and file_hash(path) == package["sha256"],
                    "Production modeling-reference package missing, changed or outside project")
            from . import modeling_refs
            modeling_refs.validate_package(read(path), project, style_id=scope, expected_asset_ids=expected,
                                           selected_concept_sha256=selected_concept_sha256)
    if current:
        _visual_package(table, recipe, stage, evidence, atlas, observations, routed=routed)
    return table


def _identity_equal(report, identity, label):
    require(report.get("schema") == 2 and report.get("identity") == identity, label + " belongs to another style/scene/attempt/input/plan")


def sample_context(data, project, scope):
    """Read the optional small frozen H2/H3 source; never substitute current H3."""
    stages = [s for s in data.get("stages", []) if s.get("scope") == scope and s.get("id") == "production_plan"]
    if not stages:
        return data
    table = _one(_evidence(stages[0], project), "production_table")
    reference = table.get("sample_source_workflow")
    if reference is None:
        return data
    require(isinstance(reference, dict) and _text(reference.get("path")) and _hash(reference.get("sha256")),
            "Sample source workflow needs path and hash")
    path = resolve_input(reference["path"], project)
    require(inside(path, project) and path.is_file() and file_hash(path) == reference["sha256"],
            "Frozen sample source workflow missing or changed")
    context = read(path)
    require(isinstance(context, dict) and context.get("production_policy") in {PRODUCTION_POLICY, PREVIOUS_PRODUCTION_POLICY},
            "Frozen sample source workflow must retain its current-policy evidence")
    return context


def _preserved_detail(source_atlas, atlas, source_graph, graph, source_stage, stage):
    require(set(source_atlas["required_space_ids"]) <= set(atlas["required_space_ids"])
            and set(source_atlas["required_transition_ids"]) <= set(atlas["required_transition_ids"]),
            "Expanded H2 must retain the original sample's detailed spaces and interfaces")
    require(atlas.get("sample_focus_contract", atlas.get("focus_contract")) == source_atlas.get("focus_contract"),
            "Expanded H2 changed original sample playable loop or entry/exit contract; preserve sample_focus_contract or supply new H4")
    roles = {"plan_view", "section_or_volume"}
    old_drawings = {(e["role"], e["path"], e["sha256"]) for e in source_stage["evidence"] if e["role"] in roles}
    drawings = {(e["role"], e["path"], e["sha256"]) for e in stage["evidence"] if e["role"] in roles}
    require(old_drawings <= drawings,
            "Expanded H2 must retain original sample plan/section evidence; add new region drawings without replacing the old layout")
    for old, new, key, label in ((source_atlas["views"], atlas["views"], "id", "concept views"),
            (source_graph["space_designs"], graph["space_designs"], "space_id", "space designs"),
            (source_graph["boundaries"], graph["boundaries"], "id", "interfaces")):
        current = {entry[key]: entry for entry in new}
        require(all(current.get(entry[key]) == entry for entry in old),
                "Expanded H2 changed original sample " + label + "; new sample evidence is required")


def _sample_source(stage, evidence, table, project, current_digests, baseline_checks, baseline_scene, *, strict=False,
                   spatial_scope=None, selected_concept_sha256=None, current=False, atlas=None, observations=None,
                   current_data=None, routed=False):
    source = _one(evidence, "sample_source_production")
    require(source.get("id") == "production_plan" and source.get("scope") == stage["scope"]
            and source.get("status") == "accepted" and type(source.get("revision")) is int
            and source["revision"] > 0, "Sample source must be an archived accepted production stage for this style")
    _approval(source)
    required = dependencies("production_plan", stage["scope"])
    require(isinstance(source.get("consumes"), dict) and set(source["consumes"]) == set(required), "Sample source production has missing creative dependencies")
    source_digests, source_atlas = current_digests, atlas
    source_policy = current_data.get("production_policy") if current_data else PRODUCTION_POLICY
    archived_context = current_data is not None and table.get("sample_source_workflow")
    changed_design = any(source["consumes"][k] != current_digests.get(k) for k in required)
    if archived_context or changed_design:
        require(current_data is not None and table.get("sample_source_workflow"),
                "Sample source was made for stale creative design inputs; focused H2 expansion needs its frozen source workflow")
        context = sample_context(current_data, project, stage["scope"])
        source_policy = context["production_policy"]
        path = resolve_input(table["sample_source_workflow"]["path"], project)
        checked = inspect_workflow(path, project, [stage["scope"]], require_current_capabilities=False)
        source_digests = checked["stage_digests"]
        require(all(source_digests.get(k) == current_digests.get(k) for k in
                    ("shared/baseline", "shared/directions", "shared/selection")),
                "Frozen sample workflow uses different gameplay or selected concepts")
        require(source_digests[stage["scope"] + "/production_plan"] == stage_digest(source),
                "Frozen workflow does not contain the original approved sample production")
        old_index = {(s["scope"], s["id"]): s for s in context["stages"]}
        new_index = {(s["scope"], s["id"]): s for s in current_data["stages"]}
        source_atlas = _one(_evidence(old_index[(stage["scope"], "atlas")], project), "atlas_manifest")
        old_graph = _one(_evidence(old_index[(stage["scope"], "spatial_design")], project), "spatial_graph")
        graph = _one(_evidence(new_index[(stage["scope"], "spatial_design")], project), "spatial_graph")
        if changed_design:
            require(source_atlas.get("scope_mode") == "focused", "Only a preserved focused H2 slice can extend through an archived source workflow")
            _preserved_detail(source_atlas, atlas, old_graph, graph,
                              old_index[(stage["scope"], "spatial_design")], new_index[(stage["scope"], "spatial_design")])
    require(all(source["consumes"][k] == source_digests.get(k) for k in required), "Sample source was made for stale creative design inputs")
    nested = _evidence(source, project)
    require(ROLES["production_plan"] <= set(nested), "Sample source production evidence is incomplete")
    from .asset_routes import ROUTE_CONTRACT
    if _one(nested, "production_table").get("asset_route_contract") == ROUTE_CONTRACT:
        # The H3 digest binds this marker. A copied v3 source cannot be downgraded
        # merely by changing its workflow's unbound top-level policy string.
        source_policy = PRODUCTION_POLICY
    original = _production(stage["scope"], nested, baseline_checks, baseline_scene, strict=strict,
        spatial_scope=spatial_scope, spatial_design_digest=source_digests[stage["scope"] + "/spatial_design"],
        project=project, selected_concept_sha256=selected_concept_sha256, current=current, stage=source, atlas=source_atlas,
        observations=observations, routed=routed and source_policy == PRODUCTION_POLICY)
    if current:
        require({"bom_board", "assembly_map", "visual_package"} <= set(nested), "Archived H3 visual package is incomplete")
        _evidence(source, project, decode_images=True)
    source_digest = stage_digest(source)
    current_contract = table["sample_contract"]
    require(current_contract.get("source_production_digest") == source_digest, "Expansion must explicitly bind the original sample production receipt")
    require(current_contract["execution_plan_digest"] == original["execution_plan_digest"], "Sample source plan differs from approved expansion sample contract")
    require({k: v for k, v in current_contract.items() if k != "source_production_digest"}
            == {k: v for k, v in original["sample_contract"].items() if k != "source_production_digest"},
            "Expansion changed the accepted sample contract; supply appropriate new sample evidence")
    require(stage["consumes"].get(stage["scope"] + "/production_plan") == source_digest,
            "Sample consumed another production revision")
    return source_digest, source_policy


def _sample(stage, evidence, table, project, observations=None, *, routed=False):
    contract = table["sample_contract"]
    identity = stage.get("identity", {})
    require(isinstance(identity, dict) and safe_id(identity.get("attempt_id")), "Sample needs a current native attempt ID")
    inputs = _one(evidence, "sample_inputs")
    require(all(inputs.get(k) == contract[k] for k in ("style_id", "scene", "baseline_scene")),
            "Sample inputs belong to another style/native scene/baseline")
    _sample_input_dependencies(inputs, project)
    if routed:
        from .asset_routes import validate_model_tasks
        source = _one(evidence, "sample_source_production")
        original = _one(_evidence(source, project), "production_table")
        validate_model_tasks(inputs, original, project)
    expected = {k: contract[k] for k in ("style_id", "scene", "input_digest")}
    expected.update(execution_plan_digest=contract["execution_plan_digest"], attempt_id=identity["attempt_id"],
                    sample_inputs_digest=digest(inputs))
    require(identity == expected, "Sample identity differs from approved production contract")
    manifest = _one(evidence, "native_sample")
    _identity_equal(manifest, identity, "Native sample")
    require(manifest.get("kind") == "native-sample", "Native sample needs a native-sample manifest")
    captures = manifest.get("captures", [])
    require(isinstance(captures, list) and captures, "Native sample needs captures from this attempt")
    recorded = {(str(resolve_input(e["path"], project)), e["sha256"]) for e in stage["evidence"] if e["role"] == "native_capture"}
    require(recorded == {(str(resolve_input(c.get("path", ""), project)), c.get("sha256")) for c in captures}, "Native captures must match the hashed sample manifest")
    if observations is not None:
        _capture_coverage(manifest, stage, [v for v in observations["views"] if v["id"] in contract["required_view_ids"]],
                          "native_capture", project)
    for role, required in (("technical_report", "required_technical_checks"), ("gameplay_report", "required_gameplay_checks")):
        report = _one(evidence, role)
        _identity_equal(report, identity, role)
        require(report.get("passed") is True and not report.get("errors") and not report.get("failed_check_ids"), "Sample " + role + " reports failure; outer acceptance cannot override it")
        checks = _ids(report.get("passed_check_ids"), role + " passed checks")
        require(set(contract[required]) <= checks, "Sample " + role + " has incomplete required check coverage")
        if role == "gameplay_report":
            require(report.get("gameplay_verified") is True, "Sample gameplay is not verified")
    visual = _one(evidence, "visual_review")
    _identity_equal(visual, identity, "Visual review")
    require(visual.get("visual_accepted") is True and visual.get("actor") == "user"
            and visual.get("source_ref") == stage["approval"]["source_ref"], "Sample needs actual human visual acceptance bound to this attempt")
    features = _ids(visual.get("passed_feature_ids"), "Accepted critical concept features")
    require(set(contract["required_critical_features"]) <= features, "Sample has unmet critical concept commitments")


def inspect_workflow(path, project, selected_styles=None, expansion=False, expected_session=None,
                     proxy_only=False, capability_report=None, require_current_capabilities=True, required_capabilities=None,
                     style_phases=None):
    path = Path(path).resolve()
    require(inside(path, project) and path.is_file(), "Workflow receipt missing or outside project")
    data = read(path)
    require(data.get("schema") == 2 and data.get("kind") == "greybox-art-workflow",
            "Expected greybox-art-workflow schema 2. Schema 1 is historical: preserve frozen runs for status/recovery; author revisioned stages and record actual user decisions to migrate. Never infer approvals.")
    all_styles = data.get("selected_styles", [])
    _ids(all_styles, "Workflow selected styles")
    styles = all_styles if selected_styles is None else selected_styles
    _ids(styles, "Production styles")
    require(set(styles) <= set(all_styles), "Production styles differ from user-selected styles")
    require(style_phases is None or (isinstance(style_phases, dict) and set(style_phases) <= set(styles)
            and all(v in {"representative", "expansion"} for v in style_phases.values())),
            "Per-style phases must name selected inspection styles and representative/expansion")
    phases = {s: (style_phases or {}).get(s, "expansion" if expansion else "representative") for s in styles}
    require(data.get("concept_source", "generate") in ("generate", "approved_import"), "Unknown concept source; no implicit fallback")
    index = {}
    for stage in data.get("stages", []):
        require(isinstance(stage, dict), "Workflow stages must be objects")
        key = (stage.get("id"), stage.get("scope"))
        require(key[0] in ROLES and (key[1] == "shared" or key[1] in all_styles), "Unknown stage/scope")
        require(key not in index, "Duplicate workflow stage/scope")
        index[key] = stage
    require(not (proxy_only and any(p == "expansion" for p in phases.values())), "Proxy preview is not an expansion delivery")
    sequence = [(s, "shared") for s in SHARED]
    for style in styles:
        per_style = ("atlas", "spatial_design") if proxy_only else STYLED + (("representative_sample",) if phases[style] == "expansion" else ())
        sequence.extend((s, style) for s in per_style)
    checked, digests, tables, atlases, scene_comparisons, historical_samples = [], {}, {}, {}, {}, {}
    directions, baseline_checks, baseline = {}, set(), {}
    current = data.get("production_policy") == PRODUCTION_POLICY
    visual_current = current or data.get("production_policy") == PREVIOUS_PRODUCTION_POLICY
    strict = current or data.get("production_policy") in HISTORICAL_PRODUCTION_POLICIES
    spatial_scope, observations = None, None
    for sid, scope in sequence:
        stage = index.get((sid, scope))
        key = scope + "/" + sid
        require(stage is not None, "BLOCKED_STAGE_MISSING: " + key)
        require(stage.get("status") == "accepted", "BLOCKED_STAGE_NOT_ACCEPTED: " + key)
        require(type(stage.get("revision")) is int and stage["revision"] > 0, "Stage needs a positive revision")
        require(_text(stage.get("decision_note")) and stage.get("actor") in ("agent", "user", "host"), "Stage needs a real scoped decision")
        wanted = dependencies(sid, scope)
        require(isinstance(stage.get("consumes"), dict) and set(stage["consumes"]) == set(wanted), "Stage must consume exact upstream dependencies: " + key)
        if sid != "representative_sample":
            for dependency in wanted:
                require(stage["consumes"][dependency] == digests.get(dependency), "Stale upstream dependency: " + key + " consumed " + dependency)
        evidence = _evidence(stage, project, decode_images=visual_current)
        require(ROLES[sid] <= set(evidence), "Missing stage evidence roles: " + sid + ": " + ",".join(sorted(ROLES[sid] - set(evidence))))
        if sid in HUMAN_STAGES:
            _approval(stage)
        if sid == "preflight":
            archived = _one(evidence, "capability_report")
            require(archived.get("schema") in (1, 2) and _text(archived.get("session_id")), "Preflight requires its original capability receipt")
            if require_current_capabilities:
                cap = capability_report if capability_report is not None else archived
                assessment = check_capabilities(cap, data.get("requires_lux", False), data.get("concept_source", "generate"), expected_session,
                                                sorted(set(data.get("required_capabilities", [])) | set(required_capabilities or [])))
                require(assessment["ok"], "BLOCKED_CAPABILITY: " + ",".join(b["capability"] for b in assessment["blockers"]))
        elif sid == "baseline":
            baseline = _one(evidence, "spatial_contract")
            require(_text(baseline.get("scene")), "Baseline spatial contract needs actual scene identity")
            if strict:
                spatial_scope = _spatial_scope(baseline)
            if visual_current:
                observations = _observations(baseline)
            validation = baseline.get("validation", {})
            declared = [s.get("id", s.get("name")) for s in validation.get("steps", []) if s.get("expect")]
            baseline_checks = _ids(validation.get("required_checks", declared), "Baseline required gameplay checks")
            require(baseline_checks <= set(declared), "Baseline required checks must be executable declared checks")
        elif sid == "directions":
            directions = _directions(stage, evidence, data.get("concept_source", "generate"))
        elif sid == "selection":
            _selection(evidence, all_styles, directions, digests["shared/directions"])
        elif sid == "atlas":
            atlases[scope] = _atlas(stage, evidence, directions[scope], spatial_scope if strict else None)
        elif sid == "spatial_design":
            graph = _one(evidence, "spatial_graph")
            require(graph.get("schema") == 2 and graph.get("style_id") == scope and graph.get("atlas_digest") == digests[scope + "/atlas"], "Spatial graph must bind this style and approved atlas revision")
            require(set(atlases[scope]["required_space_ids"]) <= _ids(graph.get("space_ids"), "Spatial graph spaces"), "Spatial graph omits atlas spaces")
            require(set(atlases[scope].get("required_transition_ids", [])) <= _ids(graph.get("transition_ids", []), "Spatial graph transitions", False), "Spatial graph omits atlas transitions")
            if strict:
                _spatial_design(graph, atlases[scope], spatial_scope)
        elif sid == "art_proxy" and visual_current:
            require("proxy_capture" in evidence, "S6 needs actual native composition captures")
            scoped_observations = observations
            if atlases[scope].get("scope_mode") == "focused":
                scoped_observations = {**observations, "views": [v for v in observations["views"]
                    if set(v["space_ids"]) & set(atlases[scope]["required_space_ids"])]}
            _proxy(stage, evidence, scoped_observations, project)
        elif sid == "production_plan":
            if visual_current:
                require({"bom_board", "assembly_map", "visual_package"} <= set(evidence), "H3 needs actual BOM board, assembly map and visual package")
            tables[scope] = _production(scope, evidence, baseline_checks, baseline["scene"], strict=strict,
                spatial_scope=spatial_scope, spatial_design_digest=digests[scope + "/spatial_design"],
                project=project, selected_concept_sha256=directions[scope]["concept_sha256"],
                current=visual_current, stage=stage, atlas=atlases[scope], observations=observations, routed=current)
            if visual_current and tables[scope].get("scope_mode") == "expansion":
                require(phases[scope] == "expansion", "Expansion scope requires the H4 expansion gate; representative production cannot bypass the original sample")
        elif sid == "representative_sample":
            _, source_policy = _sample_source(stage, evidence, tables[scope], project, digests, baseline_checks, baseline["scene"], strict=strict,
                           spatial_scope=spatial_scope, selected_concept_sha256=directions[scope]["concept_sha256"],
                           current=visual_current, atlas=atlases[scope], observations=observations, current_data=data, routed=current)
            source_routed = current and source_policy == PRODUCTION_POLICY
            if current and not source_routed:
                historical_samples[scope] = {"production_policy": source_policy, "model_task_evidence": "historical_not_v3_checked"}
            _sample(stage, evidence, tables[scope], project, observations if visual_current else None, routed=source_routed)
            if visual_current:
                from .scene_review import validate_stage
                scene_comparisons[scope] = validate_stage(data, project, stage)
        digests[key] = stage_digest(stage)
        checked.append(key)
    reviews = {}
    if visual_current:
        from .pre_handoff import CRITERIA, review_inputs, validate_review_receipt
        for sid, scope in sequence:
            if sid in CRITERIA:
                stage = index[(sid, scope)]
                reviews[scope + "/" + sid] = validate_review_receipt(stage.get("review"), review_inputs(data, project, stage), stage.get("producer"))
                if sid == "representative_sample":
                    source = _one(_evidence(stage, project), "sample_source_production")
                    validate_review_receipt(source.get("review"), review_inputs(sample_context(data, project, scope), project, source), source.get("producer"))
    return {"ok": True, "schema": 2, "checked_stages": checked, "stage_digests": digests,
            "selected_styles": styles, "style_phases": phases, "execution_plan_digests": {s: t["execution_plan_digest"] for s, t in tables.items()},
            "production_asset_proposals": {s: t.get("asset_proposals", []) for s, t in tables.items()},
            "production_modeling_references": {s: t.get("modeling_references") for s, t in tables.items()},
            "baseline_scene": baseline["scene"],
            "baseline_validation_mode": baseline["validation"].get("mode", "playable"),
            "baseline_required_steps": {s.get("id", s.get("name")): s for s in baseline["validation"]["steps"]
                                        if s.get("id", s.get("name")) in baseline_checks},
            "capabilities_current": require_current_capabilities, "production_policy_current": current, "pre_handoff_reviews": reviews,
            "scene_comparisons": scene_comparisons,
            "historical_sample_sources": historical_samples,
            "ready_for": ("art_proxy" if proxy_only else ("mixed_scoped_production" if len(set(phases.values())) > 1 else
                "expansion_production" if next(iter(phases.values())) == "expansion" else "representative_production")) if current else "historical_integrity",
            "limitations": "Checks declared provenance, revision integrity and report coverage. Cannot authenticate user messages or independently judge artwork/native gameplay."}


def check_plan_gate(plan, project, capability_report=None, require_current_capabilities=True, expected_session=None,
                    allow_legacy_policy=False):
    gate = plan.get("workflow", {})
    require(gate.get("path") and gate.get("sha256"),
            "BLOCKED_WORKFLOW: production requires schema2 concepts/selection/atlas/spatial design/proxy/production approval. See references/workflow-vnext.md. Technical fixture is a separate explicit mode, not a fallback.")
    p = resolve_input(gate["path"], project)
    require(inside(p, project) and p.is_file() and file_hash(p) == gate["sha256"], "Workflow receipt missing/changed")
    data = read(p)
    require(data.get("production_policy") == PRODUCTION_POLICY or
            (allow_legacy_policy and data.get("production_policy") in HISTORICAL_PRODUCTION_POLICIES),
            "BLOCKED_WORKFLOW_POLICY: frozen legacy workflows remain inspectable/recoverable; new production requires asset-routed-visual-sample-v3 and actual scoped decisions, never silent approval migration")
    is_proxy = plan.get("purpose") == "art_proxy"
    has_generation = any(a.get("generation") for a in plan.get("assets", []))
    require(not (is_proxy and has_generation), "Art proxy is a no-paid-generation preview; approve a separate production plan for detailed assets")
    if has_generation:
        require(data.get("requires_lux") is True, "This plan uses Lux; preflight must require Lux")
    phase = gate.get("production_scope", "representative")
    require(phase in ("representative", "expansion"), "Unknown production_scope")
    # A new supplied operational report may belong to a new session. The caller
    # binds it to its actual host session; the old creative checkpoint stays fixed.
    session = expected_session if expected_session is not None else (gate.get("session_id") if capability_report is None else None)
    # Operational blockers are cheap and may change independently of creative
    # approvals. Reject them before decoding/validating the visual evidence DAG.
    if require_current_capabilities:
        cap = capability_report
        if cap is None:
            preflight = next((s for s in data.get("stages", []) if s.get("id") == "preflight" and s.get("scope") == "shared"), None)
            require(preflight is not None, "BLOCKED_STAGE_MISSING: shared/preflight")
            cap = _one(_evidence(preflight, project), "capability_report")
        assessment = check_plan_capabilities(plan, project, cap, session)
        require(assessment["ok"], "BLOCKED_CAPABILITY: " + ",".join(b["capability"] + ":" + b["reason"] for b in assessment["blockers"]))
    result = inspect_workflow(p, project, [s["id"] for s in plan["styles"]], phase == "expansion", session,
                              proxy_only=is_proxy, capability_report=capability_report,
                              require_current_capabilities=require_current_capabilities,
                              required_capabilities=plan_capability_requirements(plan, project))
    require(plan.get("contract", {}).get("scene") == result["baseline_scene"], "Executable scene differs from approved gameplay baseline")
    validation = plan.get("contract", {}).get("validation", {})
    current_steps = {s.get("id", s.get("name")): s for s in validation.get("steps", []) if s.get("expect")}
    required_ids = set(validation.get("required_checks", current_steps))
    require(validation.get("mode", "playable") == result["baseline_validation_mode"]
            and set(result["baseline_required_steps"]) <= required_ids
            and all(current_steps.get(k) == v for k, v in result["baseline_required_steps"].items()),
            "Executable gameplay validation differs from approved baseline required checks")
    if not is_proxy:
        actual = execution_plan_digest(plan)
        require(all(h == actual for h in result["execution_plan_digests"].values()), "Executable plan differs from approved production table/assembly recipe; revise scope before production")
        result["execution_plan_digest"] = actual
        assets = {a["id"]: a for a in plan.get("assets", [])}
        for style in [s["id"] for s in plan["styles"]]:
            proposed = {a["asset_id"]: a for a in result["production_asset_proposals"][style]}
            if data.get("production_policy") == PRODUCTION_POLICY:
                if not plan.get("bindings"):
                    stage = next(s for s in data["stages"] if s["id"] == "production_plan" and s["scope"] == style)
                    recipe = _one(_evidence(stage, project), "assembly_recipe")
                    require(any(_native_realization(a) for a in recipe["assemblies"]),
                            "Native-only executable plan needs approved native assembly owners")
                for binding in plan.get("bindings", []):
                    source = binding.get("styles", {}).get(style, {}).get("source", binding.get("source", {}))
                    source_id = source.get("asset_id") or binding.get("id")
                    require(source_id in proposed, "Production table omits an executable asset source: " + str(source_id))
            used = {b.get("styles", {}).get(style, {}).get("source", b.get("source", {})).get("asset_id")
                    for b in plan.get("bindings", [])} - {None}
            for asset_id in used:
                require(asset_id in proposed, "Production table omits an executable asset: " + asset_id)
                asset = assets[asset_id]
                require(proposed[asset_id].get("generation") == asset.get("generation"),
                        "Production table generation differs from the executable asset; cannot omit image-based requirements")
                if asset.get("generation", {}).get("operation") in {"image_to_3d", "multiview_to_3d"}:
                    from . import core, modeling_refs
                    actual_images = core._check_generation_reference(asset, project)
                    reference = result["production_modeling_references"][style]
                    reviewed = modeling_refs.validate_operation_reference({"asset_id": asset_id, "modeling_references": reference}, project)
                    require(actual_images["mode"] == reviewed["mode"] and
                            [i["sha256"] for i in actual_images["images"]] == [i["sha256"] for i in reviewed["images"]],
                            "Executable asset's submitted image bytes/order differ from this style's H3 modeling references")
    return result


def build_review_inputs(path, project, stage_key):
    """Read-only handoff package. The caller must actually review it separately."""
    from .pre_handoff import review_inputs
    path = resolve_input(path, project)
    require(inside(path, project) and path.is_file(), "Workflow review inputs missing or outside project")
    data = read(path)
    require(data.get("production_policy") == PRODUCTION_POLICY, "Review input builder requires current production policy")
    matches = [s for s in data.get("stages", []) if s.get("scope", "") + "/" + s.get("id", "") == stage_key]
    require(len(matches) == 1, "Review target must identify exactly one stage")
    return review_inputs(data, project, matches[0])
