"""Godot 4 native greybox authoring, human play and actual-input probes.

This deliberately has no art-production dependency. The caller validates the
shared plan and owns project locking; generated resources remain immutable.
"""
from __future__ import annotations

import hashlib
import copy
import json
import math
import os
from pathlib import Path
import re
import subprocess

from .godot import engine, project_path, resource

TEMPLATE = Path(__file__).resolve().parents[1] / "greybox_templates" / "godot" / "greybox_runtime.gd"
ENTITY_KEYS = {"id", "role", "shape", "position", "size", "color", "collider", "behavior", "script", "properties", "interaction_anchor", "label", "relations", "constraints", "tags"}
ACTIONS = {"move_left", "move_right", "move_forward", "move_back", "interact", "restart", "pause"}
STATES = {"state", "collected_count", "collected_ids", "interacted_ids", "objective_complete", "goal_reached", "failed", "goal_denied", "restart_count", "restarted", "player_position", "player_moved", "distance_travelled", "paused", "physics_frames"}


def _json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n"


def _immutable(path, data):
    path = Path(path)
    if path.is_symlink() or path.resolve() != Path(os.path.abspath(path)):
        raise ValueError("Greybox resources cannot use symlink redirection: " + str(path))
    raw = data.encode("utf-8")
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if not path.is_file() or path.read_bytes() != raw:
            raise ValueError("Immutable greybox resource already exists: " + str(path))
    else:
        with path.open("xb") as stream:
            stream.write(raw)


def _vector(values):
    return "Vector3(%s)" % ", ".join(str(float(value)) for value in values)


def _variant(value):
    if isinstance(value, bool):
        return "true" if value else "false"
    if value is None:
        return "null"
    if isinstance(value, (str, int, float)):
        if isinstance(value, float) and not math.isfinite(value):
            raise ValueError("Godot property must be finite")
        return json.dumps(value, ensure_ascii=False)
    if isinstance(value, list):
        return "[" + ", ".join(_variant(item) for item in value) + "]"
    if isinstance(value, dict):
        return "{" + ", ".join(_variant(str(key)) + ": " + _variant(item) for key, item in value.items()) + "}"
    raise ValueError("Unsupported Godot exported property type")


def _node_name(identity):
    return "Entity_" + re.sub(r"[^a-zA-Z0-9_]", "_", identity)[:48] + "_" + hashlib.sha256(identity.encode()).hexdigest()[:8]


def _engine(executable):
    if executable is not None and not Path(executable).is_file():
        raise ValueError("Explicit Godot executable does not exist; no fallback: " + str(executable))
    binary = engine(executable)
    version = subprocess.run([binary, "--version"], capture_output=True, text=True, timeout=15)
    if version.returncode or not version.stdout.strip().startswith("4."):
        raise ValueError("Native greybox authoring requires the selected Godot 4 executable")
    return binary


def _source_files(project, scene):
    path = project_path(project, scene)
    files = [path, path.parent / "plan.json", path.parent / "greybox_runtime.gd", Path(project).resolve() / "project.godot"]
    plan = json.loads((path.parent / "plan.json").read_text(encoding="utf-8"))
    for entity in plan["entities"]:
        if entity.get("script"):
            files.append(project_path(project, entity["script"]))
    return sorted({str(item.resolve()) for item in files})


def build(project, plan, output, executable=None):
    """Create an editable .tscn under the caller's fresh resource root only."""
    plan = copy.deepcopy(plan)
    plan.setdefault("player", {})
    for key, value in {"position": [0, 0, 0], "speed": 5, "height": 1.8, "radius": .35, "view": "top_down"}.items():
        plan["player"].setdefault(key, value)
    plan.setdefault("camera", {}).setdefault("offset", [0, 12, 8])
    for entity in plan["entities"]:
        entity.setdefault("color", [.6, .6, .6, 1])
        entity.setdefault("collider", True)
        entity.setdefault("behavior", "none")
    project = Path(project).resolve()
    root = project_path(project, plan["_resource_root"])
    if root == project:
        raise ValueError("A dedicated immutable resource root is required")
    if root.exists() and any(root.iterdir()):
        raise ValueError("Greybox resource root must be fresh and empty")
    if plan.get("engine") != "godot":
        raise ValueError("Godot adapter requires engine=godot")
    scene = root / "greybox.tscn"
    plan_path = root / "plan.json"
    script = root / "greybox_runtime.gd"
    for entity in plan["entities"]:
        unsupported = set(entity) - ENTITY_KEYS
        if unsupported:
            raise ValueError("Unsupported Godot entity fields: " + ", ".join(sorted(unsupported)))
        if entity.get("script"):
            source = project_path(project, entity["script"])
            if source.suffix != ".gd" or not source.is_file():
                raise ValueError("entity.script must name an existing project-contained .gd file")
        elif entity.get("properties"):
            raise ValueError("Godot exported properties require entity.script")
    ext = ['[ext_resource type="Script" path=%s id="1_runtime"]' % _variant(resource(project, script))]
    subs = []
    nodes = ['[node name="Greybox" type="Node3D"]', 'script = ExtResource("1_runtime")', 'metadata/plan_path = ' + _variant(resource(project, plan_path)), '', '[node name="World" type="Node3D" parent="."]', '']
    entities = {}
    for index, entity in enumerate(plan["entities"]):
        name = _node_name(entity["id"])
        size = entity["size"]
        shape = entity["shape"]
        meshid, shapeid, materialid = "Mesh_%d" % index, "Shape_%d" % index, "Material_%d" % index
        if shape == "box":
            subs.extend(['[sub_resource type="BoxMesh" id="%s"]' % meshid, 'size = ' + _vector(size), '', '[sub_resource type="BoxShape3D" id="%s"]' % shapeid, 'size = ' + _vector(size), ''])
        elif shape in {"sphere", "cylinder"}:
            radius = float(size[0]) / 2.0
            if abs(float(size[0]) - float(size[2])) > 1e-6:
                raise ValueError("Godot sphere/cylinder require equal x/z size; use box or a custom script")
            if shape == "sphere":
                subs.extend(['[sub_resource type="SphereMesh" id="%s"]' % meshid, 'radius = %s' % radius, 'height = %s' % float(size[1]), '', '[sub_resource type="SphereShape3D" id="%s"]' % shapeid, 'radius = %s' % radius, ''])
                if abs(float(size[0]) - float(size[1])) > 1e-6:
                    raise ValueError("Godot sphere requires equal x/y/z size for matching physical bounds")
            else:
                subs.extend(['[sub_resource type="CylinderMesh" id="%s"]' % meshid, 'top_radius = %s' % radius, 'bottom_radius = %s' % radius, 'height = %s' % float(size[1]), '', '[sub_resource type="CylinderShape3D" id="%s"]' % shapeid, 'radius = %s' % radius, 'height = %s' % float(size[1]), ''])
        else:
            raise ValueError("Unsupported Godot shape: " + str(shape))
        subs.extend(['[sub_resource type="StandardMaterial3D" id="%s"]' % materialid, 'albedo_color = Color(%s)' % ', '.join(str(float(c)) for c in entity["color"]), 'roughness = 0.85', ''])
        path = "World/" + name
        nodes.extend(['[node name=%s type="Node3D" parent="World"]' % _variant(name), 'position = ' + _vector(entity["position"]), 'metadata/stable_id = ' + _variant(entity["id"]), 'metadata/role = ' + _variant(entity["role"]), 'metadata/behavior = ' + _variant(entity["behavior"])])
        if entity.get("script"):
            sid = "custom_%d" % index
            ext.append('[ext_resource type="Script" path=%s id=%s]' % (_variant(resource(project, entity["script"])), _variant(sid)))
            nodes.append('script = ExtResource(%s)' % _variant(sid))
        for key, value in entity.get("properties", {}).items():
            if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key) or key in {"script", "position", "transform", "rotation", "scale", "name", "owner"}:
                raise ValueError("Unsupported or protected exported property: " + str(key))
            nodes.append(key + " = " + _variant(value))
        nodes.extend(['', '[node name="Visual" type="MeshInstance3D" parent=%s]' % _variant(path), 'mesh = SubResource(%s)' % _variant(meshid), 'material_override = SubResource(%s)' % _variant(materialid), '', '[node name="InteractionAnchor" type="Marker3D" parent=%s]' % _variant(path), 'position = ' + _vector(entity.get("interaction_anchor", [0, 0, 0])), 'metadata/greybox_interaction_anchor = true', ''])
        collision_paths = []
        if entity["collider"]:
            nodes.extend(['[node name="Body" type="StaticBody3D" parent=%s]' % _variant(path), '', '[node name="CollisionShape3D" type="CollisionShape3D" parent=%s]' % _variant(path + "/Body"), 'shape = SubResource(%s)' % _variant(shapeid), ''])
            collision_paths.append("Greybox/" + path + "/Body/CollisionShape3D")
        if entity["behavior"] in {"collectible", "goal", "hazard"}:
            nodes.extend(['[node name="Trigger" type="Area3D" parent=%s]' % _variant(path), 'collision_layer = 0', 'collision_mask = 1', '', '[node name="CollisionShape3D" type="CollisionShape3D" parent=%s]' % _variant(path + "/Trigger"), 'shape = SubResource(%s)' % _variant(shapeid), ''])
            collision_paths.append("Greybox/" + path + "/Trigger/CollisionShape3D")
        anchor = entity.get("interaction_anchor", [0, 0, 0])
        entities[entity["id"]] = {"id": entity["id"], "role": entity["role"], "behavior": entity["behavior"], "node_path": "Greybox/" + path, "logic_node": "Greybox/" + path, "visual_path": "Greybox/" + path + "/Visual", "visual_nodes": ["Greybox/" + path + "/Visual"], "collision_nodes": collision_paths, "interaction_anchor": {"node_path": "Greybox/" + path + "/InteractionAnchor", "local": anchor, "world": [float(a) + float(b) for a, b in zip(entity["position"], anchor)]}, "bounds": {"center": entity["position"], "size": size}, "relations": entity.get("relations", []), "constraints": entity.get("constraints", []), "tags": entity.get("tags", []), "label": entity.get("label", entity["id"]), "script": entity.get("script"), "replaceable_visual": True}
    height = float(plan["player"]["height"])
    radius = float(plan["player"]["radius"])
    subs.extend(['[sub_resource type="CapsuleShape3D" id="PlayerShape"]', 'radius = %s' % radius, 'height = %s' % height, '', '[sub_resource type="CapsuleMesh" id="PlayerMesh"]', 'radius = %s' % radius, 'height = %s' % height, '', '[sub_resource type="StandardMaterial3D" id="PlayerMaterial"]', 'albedo_color = Color(0.95, 0.65, 0.13, 1)', ''])
    nodes.extend(['[node name="Player" type="CharacterBody3D" parent="."]', 'position = ' + _vector(plan["player"]["position"]), 'floor_snap_length = 0.2', '', '[node name="CollisionShape3D" type="CollisionShape3D" parent="Player"]', 'position = Vector3(0, %s, 0)' % (height / 2), 'shape = SubResource("PlayerShape")', '', '[node name="Visual" type="MeshInstance3D" parent="Player"]', 'position = Vector3(0, %s, 0)' % (height / 2), 'mesh = SubResource("PlayerMesh")', 'material_override = SubResource("PlayerMaterial")', 'visible = ' + ('false' if plan["player"]["view"] == "first_person" else 'true'), '', '[node name="Camera3D" type="Camera3D" parent="Player"]', 'current = true', 'near = 0.05', '', '[node name="DirectionalLight3D" type="DirectionalLight3D" parent="."]', 'rotation_degrees = Vector3(-55, -25, 0)', 'light_energy = 1.2', 'shadow_enabled = true', '', '[node name="WorldEnvironment" type="WorldEnvironment" parent="."]', 'environment = SubResource("Environment")', ''])
    subs.extend(['[sub_resource type="Environment" id="Environment"]', 'background_mode = 1', 'background_color = Color(0.12, 0.17, 0.23, 1)', 'ambient_light_source = 3', 'ambient_light_color = Color(0.8, 0.85, 1, 1)', 'ambient_light_energy = 0.7', ''])
    body = '[gd_scene load_steps=%d format=3]\n\n' % (len(ext) + len([line for line in subs if line.startswith('[sub_resource')]) + 1) + '\n\n'.join(ext) + '\n\n' + '\n'.join(subs + nodes)
    public_plan = {key: value for key, value in plan.items() if not key.startswith("_")}
    _immutable(plan_path, _json(public_plan))
    _immutable(script, TEMPLATE.read_text(encoding="utf-8"))
    _immutable(scene, body)
    config = project / "project.godot"
    created_project = not config.exists()
    if created_project:
        _immutable(config, 'config_version=5\n\n[application]\nconfig/name=' + _variant(plan.get("id", "Greybox")) + '\nrun/main_scene=' + _variant(resource(project, scene)) + '\n\n[display]\nwindow/size/viewport_width=960\nwindow/size/viewport_height=640\n\n[rendering]\nrenderer/rendering_method="gl_compatibility"\nrenderer/rendering_method.mobile="gl_compatibility"\n')
    result = {"ok": True, "engine": "godot", "scene": resource(project, scene), "source_files": _source_files(project, scene), "entities": entities, "created_project": created_project, "renderer_policy": "new projects use gl_compatibility; existing project settings retained", "input_actions": sorted(ACTIONS), "limitations": ["default controller supports walking without jump; custom entity scripts provide project-specific interactions", "space quality requires authored scenarios and native observation; success is not human acceptance"]}
    if output:
        out = Path(output).resolve()
        out.mkdir(parents=True, exist_ok=True)
        _immutable(out / "godot-build.json", _json(result))
    return result


def _probe(config, output, goal):
    unknown = set(config) - {"steps", "capture_frames", "timeout", "resolution", "headless"}
    if unknown:
        raise ValueError("Unsupported Godot probe fields: " + ", ".join(sorted(unknown)))
    if config.get("headless"):
        raise ValueError("Native greybox capture requires a rendered viewport; headless cannot prove pixels")
    steps = config.get("steps") or [{"id": "smoke_move", "actions": {"move_right": 1}, "frames": 20, "expect": {"player_moved": True}}, {"id": "smoke_reset", "actions": {"restart": 1}, "frames": 2, "expect": {"restarted": True}}]
    if not isinstance(steps, list) or not steps or len(steps) > 1000:
        raise ValueError("Probe needs 1..1000 input steps")
    step_ids = []
    for index, step in enumerate(steps):
        if set(step) - {"id", "actions", "frames", "expect"}:
            raise ValueError("Unsupported Godot step fields")
        if "id" in step and (not isinstance(step["id"], str) or not re.fullmatch(r"[A-Za-z0-9_-]+", step["id"])):
            raise ValueError("Step id must use letters, numbers, underscore or hyphen")
        step_ids.append(step.get("id", "step_%d" % index))
        if not isinstance(step.get("frames"), int) or isinstance(step.get("frames"), bool) or not 1 <= step["frames"] <= 36000:
            raise ValueError("Each input step needs frames in 1..36000")
        if set(step.get("actions", {})) - ACTIONS:
            raise ValueError("Unsupported Godot input action")
        if any(not isinstance(value, (int, float)) or not math.isfinite(value) or not 0 <= value <= 1 for value in step.get("actions", {}).values()):
            raise ValueError("Input strength must be finite in 0..1")
        if set(step.get("expect", {})) - STATES:
            raise ValueError("Unknown Godot telemetry expectation")
        for key, expectation in step.get("expect", {}).items():
            if isinstance(expectation, dict):
                if not expectation or set(expectation) - {"min", "max"}:
                    raise ValueError("Numeric expectations support only min/max bounds")
                vector = key == "player_position"
                numeric_keys = {"collected_count", "goal_denied", "restart_count", "distance_travelled", "physics_frames"}
                if not vector and key not in numeric_keys:
                    raise ValueError("Range expectation requires numeric telemetry")
                for bound in expectation.values():
                    values = bound if vector else [bound]
                    if not isinstance(values, list) or (vector and len(values) != 3) or any(type(v) not in (int, float) or not math.isfinite(v) for v in values):
                        raise ValueError("Range bounds require finite numbers; player_position needs xyz bounds")
                if "min" in expectation and "max" in expectation:
                    lower, upper = expectation["min"], expectation["max"]
                    invalid = any(lo > hi for lo, hi in zip(lower, upper)) if vector else lower > upper
                    if invalid:
                        raise ValueError("Range min must not exceed max")
    if len(set(step_ids)) != len(step_ids):
        raise ValueError("Probe step IDs must be unique")
    total = sum(step["frames"] for step in steps)
    captures = config.get("capture_frames", [min(8, total), total])
    if not isinstance(captures, list) or any(not isinstance(frame, int) or isinstance(frame, bool) or not 1 <= frame <= total for frame in captures):
        raise ValueError("capture_frames must lie inside the actual input run")
    return {"steps": steps, "capture_frames": sorted(set(captures)), "output_dir": str(output), "report_path": str(output / "native-report.json")}


def run(project, scene, config, output, executable=None):
    project = Path(project).resolve()
    scene_path = project_path(project, scene)
    if not scene_path.is_file() or scene_path.name != "greybox.tscn":
        raise ValueError("Expected a generated native greybox.tscn")
    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=True)
    if (output / "native-report.json").exists():
        raise ValueError("Native output already exists; select a new evidence directory")
    plan = json.loads((scene_path.parent / "plan.json").read_text(encoding="utf-8"))
    probe = _probe(config or {}, output, plan["goal"])
    _immutable(output / "probe.json", _json(probe))
    binary = _engine(executable)
    resolution = (config or {}).get("resolution", "960x640")
    if not isinstance(resolution, str) or not re.fullmatch(r"[1-9][0-9]{2,3}x[1-9][0-9]{2,3}", resolution):
        raise ValueError("resolution must be WIDTHxHEIGHT, 100..9999")
    timeout = float((config or {}).get("timeout", 120))
    if not math.isfinite(timeout) or not 1 <= timeout <= 3600:
        raise ValueError("Native timeout must be 1..3600 seconds")
    command = [binary, "--path", str(project), "--resolution", resolution, resource(project, scene_path), "--", "--greybox-probe=" + str(output / "probe.json")]
    try:
        process = subprocess.run(command, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        _immutable(output / "native.log", str(exc.stdout or "") + "\n" + str(exc.stderr or ""))
        return {"ok": False, "native": True, "engine": "godot", "scene": resource(project, scene_path), "checks": [], "frames": [], "telemetry": {}, "source_files": _source_files(project, scene_path), "error": "Godot native input probe timed out", "log": str(output / "native.log")}
    _immutable(output / "native.log", process.stdout + "\n" + process.stderr)
    report = output / "native-report.json"
    result = json.loads(report.read_text(encoding="utf-8")) if report.is_file() else {"ok": False, "checks": [], "frames": [], "telemetry": {}, "error": "Native runtime did not write its report"}
    result.update(native=True, engine="godot", scene=resource(project, scene_path), source_files=_source_files(project, scene_path), exit_code=process.returncode, command=command, log=str(output / "native.log"))
    result["ok"] = bool(result["ok"] and process.returncode == 0)
    if any(not Path(frame).is_file() for frame in result["frames"]):
        result["ok"] = False
        result["error"] = "Native report named a missing frame"
    if probe["capture_frames"] and len(result["frames"]) != len(probe["capture_frames"]):
        result["ok"] = False
        result.setdefault("error", "Native renderer did not capture all requested frames")
    if "SCRIPT ERROR:" in process.stderr or re.search(r"^ERROR:", process.stderr, re.M):
        result["ok"] = False
        result.setdefault("error", "Godot reported native resource or script errors; inspect native.log")
    _immutable(output / "godot-run.json", _json(result))
    return result


def launch(project, scene, executable=None):
    project = Path(project).resolve()
    path = project_path(project, scene)
    if not path.is_file():
        raise ValueError("Native greybox scene does not exist")
    binary = _engine(executable)
    process = subprocess.Popen([binary, "--path", str(project), resource(project, path)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return {"ok": True, "native": True, "engine": "godot", "scene": resource(project, path), "pid": process.pid, "controls": "WASD/arrows move; mouse first-person view; E interact; R restart; Escape pause"}
