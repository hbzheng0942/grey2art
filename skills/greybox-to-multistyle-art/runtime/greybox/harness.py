"""Local, bounded greybox authoring jobs and semantic baseline handoff.

No art checkpoint, image provider or paid service is invoked here. Native
adapters author editable project resources; this module owns their revisions.
"""
from __future__ import annotations

import copy
import math
from pathlib import Path
import uuid

from . import VERSION, core, engines

SKILL = Path(__file__).resolve().parents[2]
BEHAVIORS = {"none", "collectible", "goal", "hazard", "interactable"}


def _external(path):
    result = Path(path).resolve()
    core.require(not core.inside(result, SKILL), "Installed skill is read-only; use an external project/job")
    return result


def _vector(value, size, name, positive=False):
    core.require(isinstance(value, list) and len(value) == size and all(
        type(x) in (int, float) and math.isfinite(x) and (not positive or x > 0) for x in value),
        name + " must contain finite" + (" positive" if positive else "") + " numbers")


def validate_plan(plan, project=None):
    core.require(isinstance(plan, dict) and plan.get("schema") == 1 and
                 plan.get("kind") == "greybox-build-plan", "Expected greybox-build-plan schema 1")
    allowed = {"schema", "kind", "id", "engine", "goal", "player", "camera", "entities", "objective",
               "brief", "seed", "validation", "spatial_constraints", "notes", "relations", "engine_version", "title", "description"}
    core.require(set(plan) <= allowed, "Unsupported build-plan field; define a native extension explicitly")
    core.require(core.safe_id(plan.get("id")), "Stable build-plan id required")
    core.require(plan.get("engine") in {"godot", "unity"}, "UE is knowledge/optional experiment only; no native authoring adapter")
    core.require(plan.get("goal") in {"playable", "spatial"}, "Declare playable or spatial greybox goal")
    player = plan.get("player", {})
    core.require(isinstance(player, dict), "Player configuration required")
    core.require(set(player) <= {"position", "speed", "height", "radius", "view"}, "Unsupported player control")
    _vector(player.get("position", [0, 0, 0]), 3, "player.position")
    for key, default in (("speed", 5), ("height", 1.8), ("radius", .35)):
        value = player.get(key, default)
        core.require(type(value) in (int, float) and math.isfinite(value) and value > 0, key + " must be positive")
    core.require(player.get("height", 1.8) >= 2 * player.get("radius", .35), "Capsule height is smaller than its diameter")
    core.require(player.get("view", "top_down") in {"top_down", "first_person"}, "Unknown camera view")
    camera = plan.get("camera", {})
    core.require(isinstance(camera, dict) and set(camera) <= {"offset"}, "Unsupported camera control")
    _vector(camera.get("offset", [0, 12, 8]), 3, "camera.offset")
    core.require(any(camera.get("offset", [0, 12, 8])), "Camera offset must not be zero")
    entities = plan.get("entities")
    core.require(isinstance(entities, list) and entities, "Author at least one explicit scene entity")
    ids = [e.get("id") for e in entities if isinstance(e, dict)]
    core.require(len(ids) == len(entities) and all(core.safe_id(i) for i in ids) and len(set(ids)) == len(ids),
                 "Entities need unique stable IDs")
    allowed_entity = {"id", "role", "shape", "position", "size", "color", "collider", "behavior", "script",
                      "component_type", "properties", "interaction_anchor", "label", "tags", "relations", "constraints"}
    for entity in entities:
        core.require(set(entity) <= allowed_entity, "Unsupported entity field")
        core.require(isinstance(entity.get("role"), str) and entity["role"].strip(), "Each entity needs its semantic role")
        core.require(entity.get("shape") in {"box", "sphere", "cylinder"}, "Unsupported primitive shape")
        _vector(entity.get("position"), 3, "entity.position")
        _vector(entity.get("size"), 3, "entity.size", positive=True)
        _vector(entity.get("color", [.6, .6, .6, 1]), 4, "entity.color")
        core.require(all(0 <= x <= 1 for x in entity.get("color", [.6, .6, .6, 1])), "Color channels must be in 0..1")
        core.require(type(entity.get("collider", True)) is bool, "collider must be boolean")
        core.require(entity.get("behavior", "none") in BEHAVIORS, "Unsupported behavior; attach an explicit project script/component")
        _vector(entity.get("interaction_anchor", [0, 0, 0]), 3, "interaction_anchor")
        core.require(isinstance(entity.get("properties", {}), dict), "Component properties must be an object")
        core.require(not (entity.get("script") and entity.get("component_type")), "Select the engine's native extension form")
        core.require(not entity.get("script") or plan["engine"] == "godot", "GDScript extensions require Godot")
        core.require(not entity.get("component_type") or plan["engine"] == "unity", "C# component extensions require Unity")
        if entity.get("script") and project:
            p = core.resolve_input(entity["script"], project)
            core.require(core.inside(p, project) and p.is_file() and p.suffix == ".gd", "Custom script must be an existing project GDScript")
    objective = plan.get("objective", {})
    core.require(isinstance(objective, dict) and set(objective) <= {"required_ids", "goal_id"}, "Unsupported objective field")
    required = objective.get("required_ids", [])
    core.require(isinstance(required, list) and all(i in ids for i in required) and len(set(required)) == len(required),
                 "Objective references missing/duplicate entity IDs")
    if plan["goal"] == "playable":
        core.require(objective.get("goal_id") in ids, "Playable starter needs an actual goal entity")
        behaviors = {e["id"]: e.get("behavior", "none") for e in entities}
        core.require(behaviors[objective["goal_id"]] == "goal" and all(behaviors[i] == "collectible" for i in required),
                     "Objective IDs must bind actual goal/collectible behaviors")
    validation = plan.get("validation", {})
    core.require(isinstance(validation, dict) and set(validation) <= {"required_checks", "coverage"}, "Unsupported validation declaration")
    checks = validation.get("required_checks", [])
    core.require(isinstance(checks, list) and all(isinstance(x, str) and x.strip() for x in checks) and
                 len(set(checks)) == len(checks), "required_checks need unique names")
    coverage = validation.get("coverage", {})
    core.require(isinstance(coverage, dict) and set(coverage) <= {"input", "loop", "reset"}, "Unknown native coverage area")
    core.require(all(isinstance(names, list) and names and all(n in checks for n in names) for names in coverage.values()),
                 "Coverage must refer to declared required checks")
    return {"ok": True, "engine": plan["engine"], "goal": plan["goal"], "entities": len(entities)}


def starter(engine="godot", goal="playable", plan_id="prototype"):
    """Editable composition example, not a universal game design or full loop proof."""
    result = {"schema": 1, "kind": "greybox-build-plan", "id": plan_id, "engine": engine, "goal": goal,
              "brief": {"question": "Can the player move, read the space and complete the intended interaction?"},
              "player": {"position": [0, 0, 0], "speed": 5, "height": 1.8, "radius": .35, "view": "top_down"},
              "camera": {"offset": [0, 12, 8]}, "entities": [
                  {"id": "floor", "role": "walkable_surface", "shape": "box", "position": [0, -.5, 0],
                   "size": [16, 1, 12], "color": [.45, .48, .52, 1], "collider": True, "behavior": "none"}],
              "validation": {"required_checks": [], "coverage": {}}}
    if goal == "playable":
        result["entities"] += [
            {"id": "token", "role": "objective_item", "shape": "sphere", "position": [2, .5, 0],
             "size": [1, 1, 1], "color": [.9, .7, .2, 1], "collider": False, "behavior": "collectible"},
            {"id": "exit", "role": "completion_zone", "shape": "box", "position": [4, .5, 0],
             "size": [1, 1, 2], "color": [.2, .7, .4, 1], "collider": False, "behavior": "goal"}]
        result["objective"] = {"required_ids": ["token"], "goal_id": "exit"}
    return result


def _load(run_dir):
    root = _external(run_dir)
    state = core.read(root / "job.json")
    core.require(state.get("kind") == "greybox-harness-job" and state.get("schema") == 1,
                 "Expected greybox harness job")
    core.require(Path(state["run_dir"]).resolve() == root, "Job directory changed; preserve original identity")
    return root, state


def initialize(project, run_dir, plan, stop_at="greybox", source_ref=None):
    project, root = _external(project), _external(run_dir)
    core.require(root != project and core.inside(root, project), "Job ledger must be inside its project and must not own the project root")
    validate_plan(plan, project)
    core.require(stop_at in {"greybox", "art"}, "Greybox job requires an explicit stopping point")
    core.require(isinstance(source_ref, str) and source_ref.strip(), "Actual user task source required")
    with core.locked(root):
        core.require(not (root / "job.json").exists() and not (root / "build-plan.json").exists(), "Job exists; inspect/resume it")
        core.write(root / "build-plan.json", plan)
        state = {"schema": 1, "kind": "greybox-harness-job", "version": VERSION, "id": plan["id"],
                 "project": str(project), "run_dir": str(root), "engine": plan["engine"], "goal": plan["goal"],
                 "source_ref": source_ref, "stop_at": stop_at, "phase": "initialized", "attempts": [],
                 "created_at": core.now(), "last_verified": None, "artifact": None, "handoff": None}
        core.write(root / "job.json", state)
    return {"ok": True, "job": str(root / "job.json"), "plan": str(root / "build-plan.json"),
            "next_action": "Edit the plan for the user's intended experience, then build",
            "continuity": {"workflow": str(root / "job.json"), "ledger": str(root / "job.json"),
                           "stage": "greybox/build", "note": "Reference this ledger from the current case; preserve existing PLAN/PROGRESS"},
            "paid_work_authorized": False}


def _adapter(engine):
    if engine == "godot":
        from . import greybox_godot
        return greybox_godot
    from . import greybox_unity
    return greybox_unity


def _files(paths, project):
    found = {}
    for value in paths:
        p = core.resolve_input(value, project)
        core.require(core.inside(p, project) and p.is_file(), "Native source missing/outside its project: " + str(p))
        found[p.relative_to(project).as_posix()] = core.file_hash(p)
    return found


def _snapshot(project, artifact):
    paths = list(artifact.get("source_files", []))
    engine = artifact["engine"]
    paths += [str(p) for p in engines.configuration_files(project, {"engine": engine})]
    if engine == "unity":
        # C# compilation is global even if a script is not referenced by this scene.
        paths += [str(p) for p in (project / "Assets").rglob("*.cs")]
    # Resolve native resource references as well as authoring-owned files.
    # Scene edits can add a script/material outside the generated directory.
    deps = engines.dependency_snapshot(project, {"engine": engine,
        "workspace": {"engine": engine}, "contract": {"scene": artifact["scene"], "source_paths": paths}})
    paths += [item["path"] for item in deps]
    files = _files(paths, project)
    runtime = core.runtime_snapshot()
    return {"files": files, "runtime": runtime, "sha256": core.digest({"files": files, "runtime": runtime["sha256"]})}


def _semantic_map(plan, artifact):
    entities = artifact.get("entities")
    core.require(isinstance(entities, dict), "Native authoring must return the actual entity map")
    for item in plan["entities"]:
        binding = entities.get(item["id"])
        core.require(isinstance(binding, dict) and binding.get("node_path") and binding.get("visual_path"),
                     "Missing actual logical/visual node mapping for " + item["id"])
        core.require(binding.get("role") == item["role"], "Native semantic role changed")
        binding["declared_constraints"] = copy.deepcopy(item.get("constraints", []))
        binding["relations"] = copy.deepcopy(item.get("relations", []))
        binding["tags"] = copy.deepcopy(item.get("tags", []))
    return entities


def build(run_dir, plan=None, executable=None):
    root, _ = _load(run_dir)
    with core.locked(root):
        _, state = _load(root)
        project = Path(state["project"])
        source = plan if plan is not None else core.read(root / "build-plan.json")
        validate_plan(source, project)
        core.require(source["id"] == state["id"] and source["engine"] == state["engine"],
                     "Changing job/engine identity requires a separate explicit job")
        revision = core.digest({"plan": source, "runtime": core.runtime_snapshot()["sha256"]})[:16]
        parent = project / ("Assets/Greybox" if state["engine"] == "unity" else "Greybox") / state["id"]
        resource_root = parent / revision
        core.require(not resource_root.exists(), "Resource revision exists; inspect/resume or edit explicitly, do not overwrite it")
        output = root / "builds" / (revision + "-" + uuid.uuid4().hex[:8])
        state.update(phase="building", error=None, pending_attempt={"operation": "build", "revision": revision,
                     "resource_root": str(resource_root), "output": str(output), "started_at": core.now()})
        core.write(root / "build-plan.json", source)
        core.write(root / "job.json", state)
        try:
            native = _adapter(state["engine"]).build(project, {**source, "_resource_root": str(resource_root)}, output, executable)
            core.require(native.get("ok"), "Native authoring did not finish; inspect the preserved build output")
            artifact = {**native, "engine": state["engine"], "goal": source["goal"], "revision": revision}
            _semantic_map(source, artifact)
            scene = core.resolve_input(artifact["scene"], project)
            core.require(core.inside(scene, resource_root) and scene.is_file(), "Authoring scene escaped its owned revision")
            artifact["source_snapshot"] = _snapshot(project, artifact)
            state.update(phase="built", artifact=artifact, plan_digest=core.digest(source), goal=source["goal"], validation=None, handoff=None, pending_attempt=None)
            state["attempts"].append({"operation": "build", "revision": revision, "ok": True, "output": str(output), "at": core.now()})
        except Exception as error:
            state.update(phase="failed", error=str(error))
            state["attempts"].append({"operation": "build", "revision": revision, "ok": False, "output": str(output), "at": core.now()})
            core.write(root / "job.json", state)
            raise
        core.write(root / "job.json", state)
        return {"ok": True, "scene": artifact["scene"], "revision": revision,
                "job": str(root / "job.json"), "next_action": "Run the actual scene and iterate on the intended experience"}


def _fresh(root, state):
    core.require(state.get("artifact"), "Build an actual native greybox before running it")
    core.require(core.digest(core.read(root / "build-plan.json")) == state.get("plan_digest"), "Plan changed; build its new revision")
    actual = _snapshot(Path(state["project"]), state["artifact"])
    core.require(actual["sha256"] == state["artifact"]["source_snapshot"]["sha256"],
                 "Greybox source/config/runtime changed; inspect and validate the edited native scene")
    return actual


def _coverage(plan, checks):
    names = [item.get("name", item.get("id")) for item in checks]
    core.require(all(isinstance(n, str) and n for n in names) and len(set(names)) == len(names), "Native checks need distinct names")
    actual = {name: item.get("passed") is True for name, item in zip(names, checks)}
    required = plan.get("validation", {}).get("required_checks", [])
    coverage = plan.get("validation", {}).get("coverage", {})
    areas = {"input", "loop", "reset"} if plan["goal"] == "playable" else {"input"}
    missing = sorted(set(required) - set(actual))
    failures = sorted(n for n in required if not actual.get(n, False))
    by_name = dict(zip(names, checks))
    def observed(area, item):
        key, value = item.get("key"), item.get("actual")
        if area == "loop":
            return key == "objective_complete" and value is True
        if area == "reset":
            return key == "restarted" and value is True or key == "restart_count" and type(value) in (int, float) and value > 0
        if key == "player_moved" and value is True:
            return True
        if key in {"interacted_ids", "collected_ids"} and isinstance(value, list) and value:
            return True
        if key == "distance_travelled" and type(value) in (int, float) and value > .01:
            return True
        if key == "player_position" and isinstance(value, list) and len(value) == 3:
            initial = plan.get("player", {}).get("position", [0, 0, 0])
            return sum((float(value[i]) - initial[i]) ** 2 for i in (0, 2)) > .0001
        return False
    invalid = sorted(area for area in areas if not any(
        name in by_name and actual[name] and observed(area, by_name[name]) for name in coverage.get(area, [])))
    assigned = [n for area in areas for n in coverage.get(area, [])]
    overlap = len(assigned) != len(set(assigned))
    ready = bool(required) and not missing and not failures and not invalid and not overlap and areas <= set(coverage) and all(actual.get(n) for v in coverage.values() for n in v)
    return {"ready": ready, "required_checks": required, "missing_checks": missing,
            "failed_checks": failures, "coverage": coverage, "missing_areas": sorted(areas - set(coverage)),
            "unproven_areas": invalid, "overlapping_area_checks": overlap}


def validate(run_dir, config=None, executable=None):
    root, _ = _load(run_dir)
    with core.locked(root):
        _, state = _load(root)
        project, artifact = Path(state["project"]), state.get("artifact")
        # Native source edits are an intended iteration route; bind the exact
        # edited sources before this invocation, then reject changes during it.
        core.require(artifact, "Build the greybox before native validation")
        core.require(core.digest(core.read(root / "build-plan.json")) == state.get("plan_digest"), "Plan changed; build a revision instead")
        before = _snapshot(project, artifact)
        output = root / "evidence" / ("native-" + uuid.uuid4().hex[:12])
        state.update(phase="validating", validation=None, handoff=None,
                     pending_attempt={"operation": "validate", "output": str(output), "started_at": core.now()})
        core.write(root / "job.json", state)
        try:
            result = _adapter(state["engine"]).run(project, artifact["scene"], config or {}, output, executable)
            core.require(result.get("native") is True and result.get("engine") == state["engine"], "Native invocation identity required")
            # Refresh semantics from the actual native scene, including manual
            # renames and transform/collision edits; never rebind an old map to
            # a new source hash merely because gameplay still passes.
            _semantic_map(core.read(root / "build-plan.json"), result)
            artifact["entities"] = result["entities"]
            after = _snapshot(project, artifact)
            core.require(before["sha256"] == after["sha256"], "Source/config changed during native validation; rerun exact current sources")
            checks = result.get("checks", [])
            core.require(isinstance(checks, list) and checks, "Actual native checks required")
            frames = []
            for frame in result.get("frames", []):
                p = Path(frame.get("path") if isinstance(frame, dict) else frame).resolve()
                core.require(core.inside(p, output) and p.is_file(), "Native frame must be an actual owned output")
                from PIL import Image
                with Image.open(p) as decoded:
                    decoded.load()
                    metadata = {"width": decoded.width, "height": decoded.height, "format": decoded.format}
                core.require(metadata["width"] > 0 and metadata["height"] > 0, "Empty native image")
                frames.append({"path": str(p), "sha256": core.file_hash(p), "image": metadata})
            core.require(frames, "Native greybox evidence needs actual captured pixels")
            coverage = _coverage(core.read(root / "build-plan.json"), checks)
            passed = result.get("ok") is True and all(c.get("passed") is True for c in checks)
            report = {"schema": 1, "kind": "greybox-native-evidence", "engine": state["engine"],
                      "scene": artifact["scene"], "goal": state["goal"], "native": True, "passed": passed,
                      "checks": checks, "coverage": coverage, "frames": frames, "source_snapshot": after,
                      "entities": result["entities"],
                      "invocation": result, "input_provenance": result.get("input_provenance", "adapter_action_replay"),
                      "human_playtest": "pending", "spatial_experience": "agent must inspect the actual frames and play route",
                      "at": core.now()}
            report_path = output / "evidence.json"
            core.write(report_path, report)
            artifact["source_snapshot"] = after
            state.update(phase="validated" if passed else "failed", artifact=artifact,
                         validation={"path": str(report_path), "sha256": core.file_hash(report_path), "passed": passed,
                                     "handoff_ready": passed and coverage["ready"]}, error=None if passed else "Native check failed", pending_attempt=None)
            if passed:
                state["last_verified"] = {"revision": artifact["revision"], **state["validation"]}
            state["attempts"].append({"operation": "validate", "ok": passed, "output": str(output), "at": core.now()})
        except Exception as error:
            state.update(phase="failed", error=str(error))
            state["attempts"].append({"operation": "validate", "ok": False, "output": str(output), "at": core.now()})
            core.write(root / "job.json", state)
            raise
        core.write(root / "job.json", state)
        return {"ok": passed, "report": str(report_path), "coverage": coverage,
                "handoff_ready": passed and coverage["ready"], "human_playtest": "pending"}


def play(run_dir, executable=None):
    root, state = _load(run_dir)
    _fresh(root, state)
    return _adapter(state["engine"]).launch(Path(state["project"]), state["artifact"]["scene"], executable)


def handoff(run_dir, output, spatial_review=None):
    root, _ = _load(run_dir)
    target = _external(output)
    with core.locked(root):
        _, state = _load(root)
        core.require(core.inside(target, state["project"]), "Handoff must be inside its project so intake can resume the same baseline")
        _fresh(root, state)
        validation = state.get("validation") or {}
        core.require(validation.get("passed") and validation.get("handoff_ready"), "Native coverage is incomplete; smoke checks alone do not establish a usable baseline")
        report_path = Path(validation["path"])
        core.require(report_path.is_file() and core.file_hash(report_path) == validation["sha256"], "Native evidence changed")
        report = core.read(report_path)
        for frame in report["frames"]:
            core.require(Path(frame["path"]).is_file() and core.file_hash(frame["path"]) == frame["sha256"], "Captured pixels changed")
        plan, artifact = core.read(root / "build-plan.json"), state["artifact"]
        manifest = {"schema": 1, "kind": "greybox-baseline-manifest", "id": state["id"], "origin": "harness",
                    "engine": state["engine"], "goal": state["goal"], "scene": artifact["scene"],
                    "revision": artifact["revision"], "source_snapshot": artifact["source_snapshot"],
                    "brief": plan.get("brief", {}), "player": plan.get("player", {}), "camera": plan.get("camera", {}),
                    "entities": artifact["entities"], "objective": plan.get("objective", {}),
                    "relations": plan.get("relations", []), "spatial_constraints": plan.get("spatial_constraints", {}),
                    "native_evidence": {"path": str(report_path), "sha256": validation["sha256"]},
                    "spatial_review": spatial_review or {"state": "pending"}, "human_acceptance": "pending",
                    "stop_at": state["stop_at"], "next_workflow": "Existing baseline intake only when requested",
                    "art_authorized": False, "paid_work_authorized": False, "at": core.now()}
        manifest["binding_digest"] = core.digest(manifest)
        core.require(not target.exists(), "Preserve the prior handoff; choose a new output")
        core.write(target, manifest)
        checked = inspect_handoff(target, Path(state["project"]))
        core.require(checked["ok"], "Handoff compatibility check failed")
        state.update(phase="handoff", handoff={"path": str(target), "sha256": core.file_hash(target)})
        core.write(root / "job.json", state)
        return {"ok": True, "manifest": str(target), "compatibility": checked, "stop_at": state["stop_at"],
                "art_authorized": False, "paid_work_authorized": False}


def inspect_handoff(path, project):
    value = core.read(path)
    core.require(value.get("kind") == "greybox-baseline-manifest" and value.get("schema") == 1, "Expected greybox-baseline-manifest schema 1")
    core.require(value.get("binding_digest") == core.digest({k: v for k, v in value.items() if k != "binding_digest"}), "Handoff identity changed")
    project = Path(project).resolve()
    engines.validate_scene({"engine": value["engine"], "contract": {"scene": value["scene"]}})
    changed = []
    for rel, expected in value["source_snapshot"]["files"].items():
        p = core.resolve_input(rel, project)
        if not core.inside(p, project) or not p.is_file() or core.file_hash(p) != expected:
            changed.append(rel)
    if core.runtime_snapshot()["sha256"] != value["source_snapshot"]["runtime"]["sha256"]:
        changed.append("runtime")
    evidence = value["native_evidence"]
    p = Path(evidence["path"])
    if not p.is_file() or core.file_hash(p) != evidence["sha256"]:
        changed.append("native_evidence")
    else:
        report = core.read(p)
        if report.get("source_snapshot", {}).get("sha256") != value["source_snapshot"]["sha256"] or report.get("scene") != value["scene"] or report.get("engine") != value["engine"]:
            changed.append("native_source_identity")
        if report.get("native") is not True or not report.get("passed") or not report.get("coverage", {}).get("ready"):
            changed.append("native_coverage")
        if core.digest(report.get("entities")) != core.digest(value.get("entities")):
            changed.append("native_semantics")
        for frame in report.get("frames", []):
            f = Path(frame["path"])
            if not f.is_file() or core.file_hash(f) != frame["sha256"]:
                changed.append("frame:" + f.name)
    scene = core.resolve_input(value["scene"], project)
    if not core.inside(scene, project) or not scene.is_file():
        changed.append("scene")
    core.require(value.get("entities") and all(e.get("node_path") and e.get("visual_path") for e in value["entities"].values()),
                 "Baseline needs actual logical/visual semantic bindings")
    return {"ok": not changed, "goal": value["goal"], "engine": value["engine"], "scene": value["scene"],
            "changed": changed, "semantic_entities": len(value["entities"]), "art_authorized": False,
            "native_only": True, "human_acceptance": value.get("human_acceptance", "pending")}


def status(run_dir):
    root, state = _load(run_dir)
    stale, problem = False, None
    if state.get("artifact"):
        try:
            _fresh(root, state)
            if state.get("validation"):
                r = state["validation"]
                core.require(Path(r["path"]).is_file() and core.file_hash(r["path"]) == r["sha256"], "Native receipt changed")
                for frame in core.read(r["path"]).get("frames", []):
                    core.require(Path(frame["path"]).is_file() and core.file_hash(frame["path"]) == frame["sha256"], "Captured native pixels changed")
        except (ValueError, OSError, KeyError, TypeError) as error:
            stale, problem = True, str(error)
    next_action = "Inspect the changed sources and rerun affected native checks" if stale else {
        "initialized": "Edit the brief/build plan, then build", "building": "Inspect the original build outputs before recovery",
        "built": "Play the actual scene, adjust it, and validate", "validating": "Inspect the original native process/output before recovery",
        "validated": "Inspect actual pixels and coverage, then hand off the greybox", "handoff": "Deliver the greybox; continue art only if requested",
        "failed": "Inspect the preserved failure and last verified revision; repair only the affected work"}.get(state["phase"], "Inspect job")
    return {"ok": True, "kind": state["kind"], "project": state["project"], "id": state["id"],
            "phase": state["phase"], "stale": stale, "error": problem or state.get("error"),
            "engine": state["engine"], "goal": state["goal"], "stop_at": state["stop_at"], "next_action": next_action,
            "scene": (state.get("artifact") or {}).get("scene"), "last_verified": state.get("last_verified"),
            "validation": state.get("validation"), "handoff": state.get("handoff"),
            "pending_attempt": state.get("pending_attempt"), "paid_work_authorized": False}


def focus(state, plan, checkpoint, case):
    """Derived continuity view over the same job, not a parallel mutable plan."""
    current = status(checkpoint.parent)
    next_action = current["next_action"] if plan["status"] == "active" else "Case is " + plan["status"] + "; follow the current user instruction"
    from . import continuity
    unknown, errors = [], []
    for reference in plan.get("references", {}).get("ledgers", []):
        try:
            path = core.resolve_input(reference, state["project"])
            core.require(core.inside(path, state["project"]), "Ledger escapes project")
            unknown.extend(continuity._unknowns(core.read(path), reference))
        except (ValueError, OSError, KeyError, TypeError) as error:
            errors.append({"ledger": reference, "error": str(error)})
    if unknown or errors:
        next_action += "; preserve and reconcile original unknown service tasks, while independent local greybox work may continue"
    return {"ok": True, "workflow_kind": "greybox-harness-job", "case_id": plan["case_id"], "objective": plan["objective"],
            "status": plan["status"], "current_stage": plan["current_stage"], "constraints": plan["constraints"],
            "quality_floor": plan["quality_floor"], "remaining": plan["remaining"], "pending_proposals": plan["proposals"],
            "next_action": next_action, "required_roles": [], "missing_roles": [], "greybox": current,
            "stop_at": current["stop_at"], "authorization_refs": [], "unknown_submissions": unknown, "ledger_errors": errors,
            "original_ledger_refs": plan.get("references", {}).get("ledgers", []), "ledger_coverage": "declared_paths_only",
            "progress_path": str(case / "PROGRESS.jsonl"), "latest_event_seq": plan["progress_seq"],
            "resume_token": {"plan_revision": plan["revision"], "plan_sha256": core.file_hash(case / "PLAN.json"),
                             "checkpoint_sha256": core.file_hash(checkpoint)}, "paid_work_authorized": False,
            "limits": "Derived greybox navigation; existing art/provider authorizations stay in their original ledgers"}
