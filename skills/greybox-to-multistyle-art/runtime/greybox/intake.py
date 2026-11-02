"""Context-interpreted intent and file-backed routing; never a dispatcher."""
from __future__ import annotations

from pathlib import Path

from . import core

INTENTS = {"discuss", "create_greybox", "edit_greybox", "review", "art", "end_to_end", "resume", "pause"}
STOPS = {"discussion", "greybox", "art"}
EXCLUDED = {"Library", "Temp", "Logs", "obj", ".git", ".godot", "node_modules", "Packages", "Builds", "build"}


def _contained(project, value):
    path = core.resolve_input(value, project)
    core.require(core.inside(path, project), "Intake reference escapes the project")
    return path


def inspect(project=None, baseline=None, run_dir=None, case_dir=None):
    """Absence of evidence is unknown, never proof that an existing game is absent."""
    if project is None:
        return {"state": "unknown", "engine": None, "scenes": [], "reason": "No project supplied"}
    root = Path(project).resolve()
    if not root.exists():
        return {"state": "missing_project", "engine": None, "scenes": [], "project": str(root)}
    if root.is_file():
        core.require(root.suffix.lower() == ".blend", "Project must be a directory or an existing .blend source")
        core.require(not any((baseline, run_dir, case_dir)), "A scene source is not a gameplay ledger; pass its project directory for recovery")
        return {"state": "spatial_existing", "engine": None, "authoring_carrier": "blender",
                "project": str(root.parent), "source": str(root), "scenes": [root.name],
                "reason": "Existing Blender source; content and native rendering remain unverified"}
    core.require(root.is_dir(), "Project must be a directory")
    markers = []
    if (root / "project.godot").is_file():
        markers.append("godot")
    if (root / "ProjectSettings/ProjectVersion.txt").is_file():
        markers.append("unity")
    if any(root.glob("*.uproject")):
        markers.append("unreal")
    if len(markers) > 1:
        return {"state": "ambiguous_engine", "engine": None, "scenes": [], "markers": markers}
    engine = markers[0] if markers else None
    suffix = {"godot": ".tscn", "unity": ".unity", "unreal": ".umap"}.get(engine, ".blend")
    scenes = []
    if suffix:
        # Prune caches before walking, not after reading a multi-GB Library.
        import os
        inspected = 0
        for current, directories, files in os.walk(root, followlinks=False):
            directories[:] = sorted(d for d in directories if d not in EXCLUDED
                                    and not (Path(current) / d).is_symlink())
            if not engine:
                directories[:] = [d for d in directories if not d.startswith('.') and d not in {'venv', 'vendor', 'dist', '__pycache__'}]
                inspected += 1
                # DCC discovery is only navigation. Pass a selected .blend for
                # deep/large workspaces instead of recursively inventorying assets.
                if len(Path(current).relative_to(root).parts) >= 2 or inspected >= 128:
                    directories[:] = []
                if inspected > 128:
                    continue
            for filename in sorted(files):
                path = Path(current) / filename
                if (path.suffix.lower() == suffix if not engine else path.suffix == suffix) and not path.is_symlink():
                    scenes.append(path.relative_to(root).as_posix())
    result = {"state": "spatial_existing" if scenes else "empty_project" if engine else "unknown",
              "engine": engine, "project": str(root), "scenes": scenes,
              "reason": "Scene presence does not certify controls or a playable loop" if scenes else
                        "Inspect existing files before initializing into a nonempty directory"}
    if not engine and not any(root.iterdir()):
        result["state"] = "empty_project"
    if not engine and scenes:
        result["authoring_carrier"] = "blender"
        result["reason"] = "Existing Blender sources; choose the affected scene before native work"
    if run_dir:
        from . import harness
        result["greybox_job"] = harness.status(_contained(root, run_dir))
        job = result["greybox_job"]
        core.require(Path(job["project"]).resolve() == root, "Resume ledger belongs to another project")
        if not result["engine"]:
            result["engine"] = job["engine"]
        if job.get("stale"):
            result["state"] = "stale"
        elif job.get("phase") in {"initialized", "building", "failed"}:
            result["state"] = "partial"
    if baseline:
        from . import harness
        checked = harness.inspect_handoff(_contained(root, baseline), root)
        result["baseline"] = checked
        result["state"] = ("playable_existing" if checked["goal"] == "playable" else "spatial_existing") if checked["ok"] else "stale"
    if case_dir:
        from . import continuity
        result["focus"] = continuity.derive_focus(root, _contained(root, case_dir))
        if not result["engine"]:
            result["engine"] = result["focus"].get("greybox", {}).get("engine")
    return result


def route(request, project=None):
    core.require(isinstance(request, dict) and request.get("schema") == 1
                 and request.get("kind") == "greybox-intake-request", "Expected greybox-intake-request schema 1")
    core.require(set(request) <= {"schema", "kind", "intent", "source_ref", "stop_at", "engine", "baseline",
                                 "run_dir", "case_dir", "reason", "unresolved", "authoring_carrier",
                                 "runtime", "endpoint"}, "Unsupported intake fields")
    intent = request.get("intent")
    core.require(intent in INTENTS, "Explicit context-interpreted intent required")
    core.require(isinstance(request.get("source_ref"), str) and bool(request["source_ref"].strip()),
                 "Bind this intent to the actual user message; a tool result is not user authorization")
    stop = request.get("stop_at")
    if stop is not None:
        core.require(stop in STOPS, "Unknown requested stopping point")
    core.require(not (intent in {"create_greybox", "edit_greybox"} and stop == "art"),
                 "Greybox-only intent conflicts with an art endpoint; interpret an explicit full-chain request as end_to_end")
    declared = request.get("engine")
    core.require(declared in {None, "godot", "unity", "unreal"}, "Unsupported engine choice")
    carrier = request.get("authoring_carrier")
    core.require(carrier in {None, "blender", "godot", "unity", "unreal"}, "Unsupported authoring carrier")
    runtime = request.get("runtime")
    core.require(runtime in {None, "godot", "unity", "unreal"}, "Blender is an authoring/review carrier, not a playable runtime")
    endpoint = request.get("endpoint")
    core.require(endpoint in {None, "spatial", "playable"}, "Unknown delivery endpoint")
    core.require(not (runtime and declared and runtime != declared), "Runtime conflicts with the legacy engine choice")
    unresolved = request.get("unresolved", [])
    core.require(isinstance(unresolved, list) and all(isinstance(x, str) and x.strip() for x in unresolved),
                 "Unresolved material choices must be explicit text items")
    # Discussion needs no engine/capability/provider diagnostics.
    state = inspect(project, request.get("baseline"), request.get("run_dir"), request.get("case_dir")) if intent != "discuss" else {
        "state": "not_inspected", "engine": declared, "scenes": []}
    observed_carrier = state.get("authoring_carrier")
    carrier = carrier or observed_carrier
    engine = runtime or state.get("engine") or declared
    inherited = state.get("greybox_job", {}).get("stop_at")
    if not inherited and state.get("focus"):
        focus = state["focus"]
        inherited = "greybox" if focus.get("workflow_kind") == "greybox-harness-job" else "art"
    if intent in {"resume", "pause"}:
        stop = stop or inherited
    stop = stop or {"discuss": "discussion", "create_greybox": "greybox", "edit_greybox": "greybox",
                    "review": "greybox",
                    "art": "art", "end_to_end": "art"}.get(intent)
    result = {"ok": True, "schema": 1, "kind": "greybox-route", "intent": intent,
              "source_ref": request["source_ref"], "stop_at": stop, "engine": engine, "inspection": state,
              "dispatch": False, "paid_work_authorized": False, "requires_clarification": [],
              "required_capabilities": ["file_read"], "after_handoff": "stop" if stop != "art" else
              "Return to existing art intake and its actual H1–H5/fee authorizations"}
    native_spatial = carrier == "blender"
    # These fields are new-route-only: historical requests keep their original digests.
    if native_spatial or any(k in request for k in ("authoring_carrier", "runtime", "endpoint")):
        result.update(authoring_carrier=carrier, runtime=engine, endpoint=endpoint or ("spatial" if native_spatial else "playable"))
    if intent == "discuss" or stop == "discussion":
        action = "discuss"
    elif intent == "pause":
        action = "record_user_pause"
    elif unresolved:
        action = "clarify_material_choice"
        result["requires_clarification"] = unresolved
    elif (observed_carrier and carrier != observed_carrier) or (native_spatial and state.get("engine")):
        action = "clarify_carrier"
        result["requires_clarification"] = ["Authoring carrier conflicts with the supplied scene source"]
    elif state["state"] == "ambiguous_engine" or ((runtime or declared) and state.get("engine") and (runtime or declared) != state["engine"]):
        action = "clarify_engine"
        result["requires_clarification"] = ["Engine choice conflicts with the actual project; migration is a separate scope"]
    elif intent == "resume":
        action = ("record_user_resume" if state.get("focus", {}).get("status") == "paused" else
                  "resume_case" if state.get("focus") else "resume_greybox" if state.get("greybox_job") else "locate_original_task")
        result["next_action"] = state.get("focus", {}).get("next_action", state.get("greybox_job", {}).get("next_action"))
    elif native_spatial:
        if endpoint == "playable" and not engine:
            action = "choose_runtime"
            result["requires_clarification"] = ["Choose the intended gameplay runtime; Blender source alone is not playable delivery"]
        elif intent in {"art", "end_to_end"} and stop == "art":
            action = "existing_art_intake" if state["state"] == "spatial_existing" else "inspect_existing_project"
        elif intent == "review" and state["state"] == "spatial_existing":
            action = "native_spatial_review"
        elif intent == "create_greybox" and state["state"] in {"empty_project", "missing_project"}:
            action = "native_spatial_create"
        elif state["state"] == "spatial_existing":
            action = "native_spatial_edit" if intent != "review" else "native_spatial_review"
        else:
            action = "inspect_existing_project"
    elif not engine:
        action = "choose_engine" if state["state"] in {"missing_project", "empty_project"} else "inspect_existing_project"
    elif engine == "unreal":
        action = "ue_optional_experiment"
        result["native_support"] = "knowledge_and_optional_experiment_only"
    elif intent == "review":
        action = "review_existing_project"
    elif intent in {"art", "end_to_end"} and stop == "art":
        if state["state"] in {"playable_existing", "spatial_existing"}:
            action = "existing_art_intake"
        elif state["state"] == "stale":
            action = "verify_existing_baseline"
        elif state["state"] in {"missing_project", "empty_project"}:
            action = "greybox_create"
        else:
            action = "inspect_existing_project"
    elif intent == "edit_greybox" or state["state"] in {"playable_existing", "spatial_existing", "partial", "stale"}:
        action = "greybox_edit"
    else:
        action = "greybox_create" if state["state"] in {"missing_project", "empty_project"} else "inspect_existing_project"
    result["action"] = action
    if action.startswith("native_spatial_"):
        result["required_capabilities"] += ["process_execute", "pixel_inspect"]
        if action != "native_spatial_review":
            result["required_capabilities"].append("file_write")
        result["execution_route"] = "host_native_blender"
        result["native_verification"] = "unverified"
        result["preflight_scope"] = "Selected Blender source/workspace and host-native bpy/CLI/MCP only; no supplier or gameplay baseline prerequisite"
        result["next_action"] = "Use the host's available Blender bpy/CLI/MCP for the scoped operation; retain source/result identity, actual invocation and affected native views. The bundled blender inspect command discovers the application only."
        if endpoint == "playable":
            result["after_handoff"] = "Continue in the declared runtime and establish actual gameplay/native evidence before claiming playable delivery"
    elif action in {"greybox_create", "greybox_edit", "resume_greybox"}:
        result["required_capabilities"] += ["file_write", "process_execute", "native_engine", "pixel_inspect"]
        result["preflight_scope"] = "Greybox dependencies only; no image, mesh supplier or art checkpoint preconditions"
    elif action == "existing_art_intake":
        result["preflight_scope"] = "Use the existing art intake and stage-scoped capability checks"
    elif action == "review_existing_project":
        result["required_capabilities"] += ["process_execute", "native_engine", "pixel_inspect"]
        result["preflight_scope"] = "Review affected native views without editing the scene or preparing suppliers"
    result["route_digest"] = core.digest({k: v for k, v in result.items() if k != "route_digest"})
    return result
