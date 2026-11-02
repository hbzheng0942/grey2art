"""Small, owned native look-development recipes. No renderer is changed."""
from __future__ import annotations
import json
import math
from pathlib import Path
from . import core

FAMILIES = {"lighting", "water", "grass", "ground"}
TEXTURE_FIELDS = ("shore_mask", "normal_texture", "density_mask", "texture", "secondary_texture", "blend_mask")
FIELDS = {
    "lighting": {"sun_energy", "sun_rotation", "color", "ambient_energy", "ambient_color", "background_color", "fog_density", "exposure", "bloom", "shadows", "sky", "light_path"},
    "water": {"position", "size", "color", "deep_color", "speed", "amplitude", "shore_mask", "normal_texture", "roughness", "shore_width", "depth_distance"},
    "grass": {"bounds", "count", "seed", "exclude_rects", "height", "width", "color", "wind", "cull_distance", "y", "ground_y", "density_mask", "mask_threshold", "chunk_size"},
    "ground": {"position", "size", "color", "secondary_color", "tile_scale", "texture", "secondary_texture", "blend_mask"},
}


def validate(config):
    core.require(isinstance(config, dict), "Effects configuration must be an object")
    effects = config.get("effects", config)
    core.require(isinstance(effects, dict) and not set(effects) - FAMILIES,
                 "Effects must declare lighting, water, grass or ground")
    def finite(value):
        if isinstance(value, dict):
            return all(finite(v) for v in value.values())
        if isinstance(value, list):
            return all(finite(v) for v in value)
        return not isinstance(value, (float, int)) or isinstance(value, bool) or math.isfinite(value)
    core.require(finite(effects), "Effect parameters must be finite")
    def number(value):
        return type(value) in (int, float) and math.isfinite(value)
    def vector(value, count):
        return isinstance(value, list) and len(value) == count and all(number(v) for v in value)
    def scalar(recipe, key, minimum=0, maximum=None, strict=False):
        if key in recipe:
            value = recipe[key]
            core.require(number(value) and (value > minimum if strict else value >= minimum)
                         and (maximum is None or value <= maximum), "Invalid " + key + " range")
    for family, recipe in effects.items():
        core.require(isinstance(recipe, dict), family + " recipe must be an object")
        core.require(not set(recipe) - FIELDS[family], "Unsupported " + family + " parameter: " + ", ".join(sorted(set(recipe) - FIELDS[family])))
        for key in ("position", "sun_rotation"):
            if key in recipe:
                core.require(vector(recipe[key], 3),
                             key + " needs three coordinates")
        if "size" in recipe:
            core.require(vector(recipe["size"], 2) and all(v > 0 for v in recipe["size"]), "Surface size must be positive")
        for key in ("color", "secondary_color", "deep_color", "ambient_color", "background_color"):
            if key in recipe:
                core.require(isinstance(recipe[key], list) and len(recipe[key]) in (3, 4)
                             and all(number(v) and 0 <= v <= 1 for v in recipe[key]), "Colors must contain 0..1 RGB(A)")
        for key in ("shore_mask", "normal_texture", "density_mask", "texture", "secondary_texture", "blend_mask"):
            if key in recipe:
                core.require(isinstance(recipe[key], str) and bool(recipe[key].strip()), key + " must identify a project texture")
        if family == "lighting":
            for key in ("sun_energy", "ambient_energy"):
                scalar(recipe, key)
            scalar(recipe, "fog_density", maximum=1)
            scalar(recipe, "exposure", strict=True)
            for key in ("bloom", "shadows", "sky"):
                core.require(key not in recipe or type(recipe[key]) is bool, key + " must be boolean")
            core.require("light_path" not in recipe or isinstance(recipe["light_path"], str)
                         and bool(recipe["light_path"].strip()), "light_path must identify a scene light")
        if family == "water":
            core.require("speed" not in recipe or number(recipe["speed"]), "speed must be numeric")
            scalar(recipe, "amplitude")
            scalar(recipe, "roughness", maximum=1)
            scalar(recipe, "shore_width", strict=True)
            scalar(recipe, "depth_distance", strict=True)
        if family == "ground":
            scalar(recipe, "tile_scale", strict=True)
        if family == "grass":
            bounds = recipe.get("bounds", [-5, -5, 5, 5])
            core.require(vector(bounds, 4) and bounds[0] < bounds[2] and bounds[1] < bounds[3], "Invalid grass bounds")
            core.require(type(recipe.get("count", 400)) is int and 0 <= recipe.get("count", 400) <= 100000, "Grass count must be 0..100000")
            core.require(type(recipe.get("seed", 1)) is int, "Grass seed must be an integer")
            exclusions = recipe.get("exclude_rects", [])
            core.require(isinstance(exclusions, list), "Grass exclusions must be an array")
            for rect in exclusions:
                core.require(vector(rect, 4) and rect[0] <= rect[2] and rect[1] <= rect[3], "Invalid grass exclusion")
            for key in ("height", "width", "chunk_size"):
                scalar(recipe, key, strict=True)
            for key in ("wind", "cull_distance"):
                scalar(recipe, key)
            scalar(recipe, "mask_threshold", maximum=1)
            for key in ("y", "ground_y"):
                core.require(key not in recipe or number(recipe[key]), key + " must be numeric")
            core.require(not {"y", "ground_y"} <= recipe.keys() or recipe["y"] == recipe["ground_y"],
                         "Conflicting grass y and ground_y")
    return effects


def dependencies(effects, project):
    result = []
    for recipe in effects.values():
        for field in TEXTURE_FIELDS:
            if recipe.get(field):
                path = core.resolve_input(recipe[field], project)
                core.require(path.is_file() and core.inside(path, project), "Effect texture must be an existing project resource")
                if path.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tga"}:
                    from PIL import Image
                    try:
                        with Image.open(path) as image:
                            image.verify()
                    except (OSError, ValueError, SyntaxError) as exc:
                        raise ValueError("Effect texture cannot be decoded: " + field) from exc
                result.append({"path": str(path), "sha256": core.file_hash(path), "usage": field,
                               "color_space": "srgb" if field in ("texture", "secondary_texture") else "linear-data"})
    return result


def _godot_bindings(project, shader_root, value):
    """Explicit native resources shared by lookdev and ordinary assembly."""
    from . import godot
    root, target = Path(project).resolve(), Path(shader_root).resolve()
    # Native resources must be visible to both Godot and source-identity scanners.
    # Computed load() paths in effects.gd used to hide shaders and textures from
    # dependency snapshots, allowing changed visual inputs to retain old evidence.
    resources, properties = [], []
    for kind in ("water", "grass", "ground"):
        resources.append(f'[ext_resource type="Shader" path={json.dumps(godot.resource(root, target / (kind + ".gdshader")))} id="effect_shader_{kind}"]')
        properties.append(f'{kind}_shader = ExtResource("effect_shader_{kind}")')
    texture_ids, texture_inputs = {}, {}
    for recipe in value.values():
        for field in TEXTURE_FIELDS:
            if not recipe.get(field):
                continue
            authored_path = recipe[field]
            native_path = godot.resource(root, core.resolve_input(authored_path, root))
            if native_path not in texture_ids:
                rid = "effect_texture_" + str(len(texture_ids))
                texture_ids[native_path] = rid
                resources.append(f'[ext_resource type="Texture2D" path={json.dumps(native_path)} id="{rid}"]')
            texture_inputs[authored_path] = texture_ids[native_path]
    properties.append('texture_inputs = {\n' + ',\n'.join(
        f'{json.dumps(path)}: ExtResource("{rid}")' for path, rid in texture_inputs.items()) + '\n}')
    return resources, properties


def apply_godot(project, config, output):
    from . import godot
    root, target = Path(project).resolve(), Path(output).resolve()
    core.require(core.inside(target, root), "Native effects output must be inside its project")
    scene = config.get("scene")
    source = core.resolve_input(scene, root)
    core.require(source.is_file() and core.inside(source, root), "Effects need an existing native scene")
    value = validate(config)
    inputs = dependencies(value, root)
    owned = []
    runtime = Path(__file__).resolve().parents[1] / "godot"
    for filename in ("effects.gd", "water.gdshader", "grass.gdshader", "ground.gdshader"):
        godot._write_owned(target / filename, (runtime / filename).read_bytes(), owned)
    resources = [
        f'[ext_resource type="PackedScene" path={json.dumps(godot.resource(root, source))} id="1"]',
        f'[ext_resource type="Script" path={json.dumps(godot.resource(root, target / "effects.gd"))} id="2"]',
    ]
    effect_resources, properties = _godot_bindings(root, target, value)
    resources.extend(effect_resources)
    text = (f'[gd_scene load_steps={len(resources) + 1} format=3]\n\n'
            + '\n'.join(resources) + '\n\n'
            + f'[node name={json.dumps(godot._scene_name(source))} instance=ExtResource("1")]\n\n'
            + '[node name="GreyboxEffects" type="Node3D" parent="."]\nscript = ExtResource("2")\n'
            + f'config_json = {json.dumps(json.dumps(value))}\n'
            + '\n'.join(properties) + '\n')
    godot._write_owned(target / "lookdev.tscn", text, owned)
    result = {"ok": True, "engine": "godot", "entry_scene": godot.resource(root, target / "lookdev.tscn"),
              "effects": value, "owned_files": owned, "native_verified": False,
              "source": {"path": str(source), "sha256": core.file_hash(source)}, "dependencies": inputs}
    core.write(target / "effects-result.json", result)
    return result
