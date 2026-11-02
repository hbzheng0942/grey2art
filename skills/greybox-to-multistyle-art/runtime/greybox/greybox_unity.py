"""Native Unity greybox authoring, separate from the art-only assembly adapter.

All generated scene resources belong to the caller's immutable revision. The
small versioned harness runtime has one stable location to avoid duplicate C#
types across revisions. Replay drives the same action method as keyboard input;
its receipts explicitly identify action replay rather than device input.
"""
from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
import re
import subprocess
import time
import uuid

from . import unity

TEMPLATES = Path(__file__).resolve().parents[1] / "greybox_templates/unity"
TOOL_ROOT = "Assets/GreyboxHarness"
OWNER = "greybox-authoring-v05"
ACTIONS = {"move_right", "move_left", "move_forward", "move_backward", "turn_right", "turn_left", "look_up", "look_down", "jump", "interact", "restart", "pause"}
ENTITY_FIELDS = {"id", "role", "shape", "position", "size", "color", "collider", "behavior", "component_type", "properties", "interaction_anchor", "label", "tags", "relations", "constraints"}
PLAN_FIELDS = {"schema", "kind", "id", "engine", "goal", "player", "camera", "entities", "objective", "title", "description", "_resource_root", "brief", "seed", "validation", "spatial_constraints", "notes", "relations", "engine_version"}


def _json(path, value=None):
    path = Path(path)
    if value is None:
        return json.loads(path.read_text(encoding="utf-8"))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")
    return value


def _vec(value, count, label, *, positive=False):
    if not isinstance(value, list) or len(value) != count or any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) or positive and v <= 0 for v in value):
        raise ValueError(label + " needs " + str(count) + " finite" + (" positive" if positive else "") + " numbers")
    return value


def _properties(value):
    if not isinstance(value, dict):
        raise ValueError("Unity component properties must be an object")
    result = []
    for name, item in value.items():
        if not isinstance(name, str) or not name or name.startswith("m_"):
            raise ValueError("Use explicitly named public serialized component properties")
        row = {"name": name}
        if isinstance(item, bool):
            row.update(kind="bool", boolean=item)
        elif isinstance(item, (int, float)) and math.isfinite(item):
            row.update(kind="number", number=item)
        elif isinstance(item, str):
            row.update(kind="string", text=item)
        elif isinstance(item, list) and len(item) in (2, 3, 4):
            row.update(kind="vector", values=_vec(item, len(item), "component vector"))
        else:
            raise ValueError("Unsupported Unity serialized property value: " + name)
        result.append(row)
    return result


def _plan(plan):
    if not isinstance(plan, dict) or set(plan) - PLAN_FIELDS:
        raise ValueError("Unsupported Unity greybox plan fields: " + str(sorted(set(plan) - PLAN_FIELDS) if isinstance(plan, dict) else plan))
    if plan.get("engine") != "unity" or plan.get("schema") != 1 or plan.get("kind") != "greybox-build-plan":
        raise ValueError("Expected schema 1 Unity greybox-build-plan")
    if plan.get("goal") not in ("playable", "spatial"):
        raise ValueError("Greybox goal must be playable or spatial")
    player = dict(plan.get("player", {}))
    if set(player) - {"position", "speed", "height", "radius", "view"}:
        raise ValueError("Unsupported Unity player fields")
    _vec(player.get("position", [0, 0, 0]), 3, "player.position")
    for key, default in (("speed", 5), ("height", 1.8), ("radius", .35)):
        player.setdefault(key, default)
        if isinstance(player[key], bool) or not isinstance(player[key], (int, float)) or not math.isfinite(player[key]) or player[key] <= 0:
            raise ValueError("player." + key + " must be positive")
    player.setdefault("position", [0, 0, 0])
    player.setdefault("view", "top_down")
    if player["view"] not in {"top_down", "first_person"} or player["height"] < player["radius"] * 2:
        raise ValueError("Unsupported camera view or capsule dimensions")
    camera = dict(plan.get("camera", {}))
    if set(camera) - {"offset"}:
        raise ValueError("Unsupported Unity camera fields")
    camera.setdefault("offset", [0, 12, 8])
    _vec(camera["offset"], 3, "camera.offset")
    entities, ids = [], set()
    for source in plan.get("entities", []):
        if not isinstance(source, dict) or set(source) - ENTITY_FIELDS:
            raise ValueError("Unsupported Unity entity fields")
        item = dict(source)
        if not isinstance(item.get("id"), str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,95}", item["id"]) or item["id"] in ids:
            raise ValueError("Unity entity IDs must be unique safe stable identifiers")
        if not isinstance(item.get("role"), str) or not item["role"].strip():
            raise ValueError("Entity needs a semantic role")
        ids.add(item["id"])
        item.setdefault("behavior", "none")
        item.setdefault("shape", "box")
        if item["behavior"] not in {"none", "collectible", "goal", "hazard", "interactable"} or item["shape"] not in {"box", "sphere", "cylinder"}:
            raise ValueError("Unsupported Unity entity behavior or primitive shape")
        _vec(item.get("position"), 3, "entity.position")
        _vec(item.get("size"), 3, "entity.size", positive=True)
        _vec(item.setdefault("color", [.5, .6, .7, 1]), 4, "entity.color")
        if any(v < 0 or v > 1 for v in item["color"]):
            raise ValueError("Entity color channels must be within 0–1")
        if not isinstance(item.setdefault("collider", True), bool):
            raise ValueError("Entity collider must be boolean")
        _vec(item.setdefault("interaction_anchor", [0, 0, 0]), 3, "interaction_anchor")
        if item.get("component_type") is not None and (not isinstance(item["component_type"], str) or not item["component_type"].strip()):
            raise ValueError("component_type must name a project MonoBehaviour")
        if item.get("properties") and not item.get("component_type"):
            raise ValueError("Unity entity properties require component_type")
        item["properties"] = _properties(item.get("properties", {}))
        entities.append(item)
    if not entities:
        raise ValueError("A greybox needs at least one entity")
    objective = dict(plan.get("objective", {}))
    if set(objective) - {"required_ids", "goal_id"}:
        raise ValueError("Unsupported Unity objective fields")
    objective.setdefault("required_ids", [])
    if plan["goal"] == "playable":
        if not isinstance(objective.get("required_ids"), list) or not objective.get("goal_id"):
            raise ValueError("Playable greybox needs required_ids and a goal_id")
        by_id = {item["id"]: item for item in entities}
        if any(key not in by_id or by_id[key]["behavior"] != "collectible" for key in objective["required_ids"]) or len(set(objective["required_ids"])) != len(objective["required_ids"]):
            raise ValueError("required_ids must name distinct collectibles")
        if objective["goal_id"] not in by_id or by_id[objective["goal_id"]]["behavior"] != "goal":
            raise ValueError("goal_id must name a goal entity")
    objective.setdefault("goal_id", "")
    return {"id": plan["id"], "goal": plan["goal"], "player": player, "camera": camera, "entities": entities, "objective": objective, "title": plan.get("title", plan["id"])}


def _project(project, executable, output):
    root = Path(project).resolve()
    version = root / "ProjectSettings/ProjectVersion.txt"
    binary = unity.engine(executable, root)
    created = not version.is_file()
    if created:
        if root.exists() and any(root.iterdir()):
            # Harness state may be established before project creation, but no
            # unrelated partial project is silently replaced.
            if any(p.name not in {"art", ".greybox", ".greybox-work"} for p in root.iterdir()):
                raise ValueError("Unity project is partial or nonempty; preserve it and choose an empty project directory")
        root.mkdir(parents=True, exist_ok=True)
        proc = subprocess.run([binary, "-batchmode", "-nographics", "-quit", "-createProject", str(root), "-logFile", str(output / "create-project.log")], capture_output=True, text=True, timeout=300)
        if proc.returncode != 0 or not version.is_file():
            raise RuntimeError("Unity project creation failed; inspect create-project.log")
        unity.configure_packages(root, gltfast=False, urp=True)
    else:
        manifest = root / "Packages/manifest.json"
        if not manifest.is_file() or "com.unity.render-pipelines.universal" not in _json(manifest).get("dependencies", {}):
            raise ValueError("Existing project must declare URP; Built-in/HDRP is unsupported and is not converted")
    return root, binary, created


def _install(root):
    target = root / TOOL_ROOT
    marker = target / "owner.json"
    if target.exists() and (not marker.is_file() or _json(marker).get("owner") != OWNER):
        raise ValueError("Harness tool root belongs to another owner: " + str(target))
    target.mkdir(parents=True, exist_ok=True)
    _json(marker, {"schema": 1, "owner": OWNER})
    files = [marker]
    for source in sorted(TEMPLATES.rglob("*.cs")):
        dest = target / source.relative_to(TEMPLATES)
        dest.parent.mkdir(parents=True, exist_ok=True)
        content = source.read_bytes()
        if not dest.is_file() or dest.read_bytes() != content:
            dest.write_bytes(content)
        files.append(dest)
    return files


def _invoke(root, binary, request, output, timeout=300):
    request = dict(request, request_id=uuid.uuid4().hex, report=str(output / "native-report.json"), evidence_root=str(output))
    request_path = output / "native-request.json"
    if request_path.exists() or Path(request["report"]).exists():
        raise ValueError("Use a fresh output directory for each native invocation")
    _json(request_path, request)
    started = time.monotonic()
    try:
        proc = subprocess.run([binary, "-batchmode", "-projectPath", str(root), "-executeMethod", "GreyboxHarnessV05.Editor.AuthoringBridge.Execute", "-greyboxAuthoringRequest", str(request_path), "-logFile", str(output / "unity.log")], capture_output=True, text=True, timeout=timeout)
        (output / "process.log").write_text((proc.stdout or "") + (proc.stderr or ""), encoding="utf-8")
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError("Unity authoring timed out; existing evidence does not certify completion") from exc
    report = _json(request["report"]) if Path(request["report"]).is_file() else {"ok": False, "errors": ["Unity did not write a native report; inspect unity.log"]}
    errors = list(report.get("errors", []))
    if report.get("request_id") != request["request_id"] or report.get("operation") != request["operation"] or report.get("scene") != request["scene"]:
        errors.append("Native receipt identity mismatch")
    if proc.returncode != 0:
        errors.append("Unity exit code: " + str(proc.returncode))
    report.update(ok=bool(report.get("ok")) and not errors, errors=errors, elapsed_seconds=time.monotonic() - started, native=True, engine="unity")
    _json(output / "result.json", report)
    return report


def build(project, plan, output, executable=None):
    spec = _plan(plan)
    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=True)
    root, binary, created = _project(project, executable, output)
    resource = Path(plan.get("_resource_root", "")).resolve()
    assets = (root / "Assets").resolve()
    if not resource.is_relative_to(assets / "Greybox") or resource == assets / "Greybox":
        raise ValueError("_resource_root must be a fresh revision below Assets/Greybox")
    if resource.exists() and any(resource.iterdir()):
        raise ValueError("Greybox revision resources are immutable; use a fresh revision")
    _install(root)
    resource.mkdir(parents=True, exist_ok=True)
    spec_path = resource / "build-spec.json"
    _json(spec_path, spec)
    scene = (resource / "Greybox.unity").relative_to(root).as_posix()
    report = _invoke(root, binary, {"operation": "build", "scene": scene, "spec_path": str(spec_path), "configure_pipeline": created}, output)
    # Evidence is not a runtime asset. Writing this after Editor exit under
    # Assets would defer .meta creation until the next run and change the
    # supposedly frozen source closure during its first validation.
    _json(output / "semantics.json", {"schema": 1, "kind": "greybox-semantic-index", "engine": "unity", "scene": scene, "entities": {row["id"]: row for row in report.get("entities", [])}})
    source_files = {p for p in (root / TOOL_ROOT).rglob("*") if p.is_file()} | {p for p in resource.rglob("*") if p.is_file()}
    report.update(source_files=[str(p) for p in sorted(source_files)], entities={row["id"]: row for row in report.pop("entities", [])}, project_created=created, pipeline="urp")
    _json(output / "result.json", report)
    return report


def _run_config(config):
    if not isinstance(config, dict) or set(config) - {"steps", "capture_frames", "warmup_frames", "width", "height", "frame_stride", "timeout"}:
        raise ValueError("Unsupported Unity greybox run configuration")
    result = {"steps": [], "capture_frames": config.get("capture_frames", 3), "warmup_frames": config.get("warmup_frames", 8), "frame_stride": config.get("frame_stride", 4), "width": config.get("width", 960), "height": config.get("height", 540)}
    for name, low, high in (("capture_frames", 1, 120), ("warmup_frames", 1, 300), ("frame_stride", 1, 120), ("width", 64, 4096), ("height", 64, 4096)):
        if not isinstance(result[name], int) or isinstance(result[name], bool) or not low <= result[name] <= high:
            raise ValueError("Unity run " + name + " outside supported range")
    for index, source in enumerate(config.get("steps", [])):
        if not isinstance(source, dict) or set(source) - {"id", "actions", "frames", "expect"}:
            raise ValueError("Unsupported Unity replay step fields")
        actions = source.get("actions", {})
        if not isinstance(actions, dict) or set(actions) - ACTIONS or any(not isinstance(v, (bool, int, float)) or not math.isfinite(v) or abs(v) > 1 for v in actions.values()):
            raise ValueError("Unsupported action or value in Unity action replay")
        frames = source.get("frames", 1)
        if not isinstance(frames, int) or isinstance(frames, bool) or not 1 <= frames <= 1800:
            raise ValueError("Replay step frames must be within 1–1800")
        expected = source.get("expect", {})
        if not isinstance(expected, dict):
            raise ValueError("Replay expect must be an object")
        result["steps"].append({"id": str(source.get("id", index)), "actions": actions, "frames": frames})
    return result


def _scene(root, scene):
    path = (root / scene).resolve() if not Path(scene).is_absolute() else Path(scene).resolve()
    if not path.is_relative_to(root / "Assets") or path.suffix != ".unity" or not path.is_file():
        raise ValueError("Unity greybox scene must be an existing project Assets scene")
    return path.relative_to(root).as_posix()


def _matches(observed, expected):
    if isinstance(expected, dict):
        if not expected or set(expected) - {"min", "max"}:
            raise ValueError("Unity range expectations accept only min/max")
        if isinstance(observed, list):
            for bound in expected.values():
                _vec(bound, len(observed), "range bound")
            return all(_matches(value, {key: bound[index] for key, bound in expected.items()}) for index, value in enumerate(observed))
        if not isinstance(observed, (int, float)) or isinstance(observed, bool):
            return False
        for bound in expected.values():
            if not isinstance(bound, (int, float)) or isinstance(bound, bool) or not math.isfinite(bound):
                raise ValueError("Range bounds must be finite numbers")
        return ("min" not in expected or observed >= expected["min"]) and ("max" not in expected or observed <= expected["max"])
    if isinstance(expected, list) and isinstance(observed, list):
        return len(expected) == len(observed) and all(_matches(a, b) for a, b in zip(observed, expected))
    if isinstance(expected, (float, int)) and not isinstance(expected, bool) and isinstance(observed, (float, int)):
        return math.isclose(observed, expected, abs_tol=1e-4)
    return observed == expected


def run(project, scene, config, output, executable=None):
    root = Path(project).resolve()
    scene = _scene(root, scene)
    settings = _run_config(config or {})
    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=True)
    report = _invoke(root, unity.engine(executable, root), dict(settings, operation="run", scene=scene), output, timeout=(config or {}).get("timeout", 300))
    checks = [{"name": "native-playmode", "passed": bool(report.get("play_mode")), "expected": True, "actual": report.get("play_mode")}, {"name": "graphics-device", "passed": report.get("graphics_device", "Null") != "Null", "expected": "real graphics device", "actual": report.get("graphics_device")}]
    snapshots = report.get("snapshots", [])
    for index, step in enumerate((config or {}).get("steps", [])):
        actual = snapshots[index] if index < len(snapshots) else {}
        for key, expected in step.get("expect", {}).items():
            observed = actual.get(key)
            passed = key in actual and _matches(observed, expected)
            checks.append({"name": "step-" + str(step.get("id", index)) + ":" + key, "key": key, "step": index, "passed": passed, "expected": expected, "actual": observed})
    frames = []
    for item in report.get("captures", []):
        path = Path(item["path"]).resolve()
        valid = path.is_relative_to(output) and path.is_file() and path.read_bytes().startswith(b"\x89PNG\r\n\x1a\n") and hashlib.sha256(path.read_bytes()).hexdigest() == item.get("sha256")
        checks.append({"name": "capture-" + str(len(frames)), "passed": valid, "expected": "bound native PNG", "actual": str(path)})
        if valid:
            frames.append(str(path))
    checks.append({"name": "capture-count", "passed": len(frames) >= settings["capture_frames"], "expected": settings["capture_frames"], "actual": len(frames)})
    source_files = {p for p in (root / TOOL_ROOT).rglob("*") if p.is_file()} | {p for p in (root / scene).parent.rglob("*") if p.is_file()}
    mode = "action_replay" if settings["steps"] else "idle_observation"
    native_entities = report.get("entities", [])
    entities = {row["id"]: row for row in native_entities}
    checks.append({"name": "actual-semantic-bindings", "passed": bool(entities) and len(entities) == len(native_entities), "expected": "unique actual scene entity bindings", "actual": len(entities)})
    report.update(ok=report["ok"] and all(row["passed"] for row in checks), checks=checks, entities=entities, frames=frames, telemetry=report.get("telemetry", {}), input_mode=mode, input_provenance={"kind": mode, "entrypoint": "GreyboxController.ApplyActions", "real_device_input_verified": False}, source_files=[str(p) for p in sorted(source_files)])
    _json(output / "result.json", report)
    return report


def launch(project, scene, executable=None):
    root = Path(project).resolve()
    scene = _scene(root, scene)
    # Editor UI and Play button remain user controlled. No unattended instance is
    # silently left in the background and no replay is called device input.
    command = [unity.engine(executable, root), "-projectPath", str(root), "-openfile", str(root / scene)]
    process = subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return {"ok": True, "engine": "unity", "scene": scene, "pid": process.pid, "input_mode": "keyboard_mouse", "action": "editor-open-scene", "play_required": True, "controls": "WASD/arrows move; right mouse look in first person; E interact; R restart; Escape/Space pause; Play in Editor to start"}
