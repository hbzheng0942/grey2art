"""Background-only Blender worker. Invoked with --factory-startup and one job path."""
import bpy
from mathutils import Vector
import hashlib
import json
import math
from pathlib import Path
import random
import sys
import traceback


def file_hash(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def job_hash(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def select_only(obj):
    bpy.ops.object.select_all(action="DESELECT")
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj


def import_meshes(job):
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete(use_global=False)
    if job.get("input"):
        if file_hash(job["input"]["path"]) != job["input"]["sha256"]:
            raise RuntimeError("Immutable source changed before import")
        bpy.ops.import_scene.gltf(filepath=job["input"]["path"])
    else:
        bpy.ops.mesh.primitive_cube_add(size=1, location=(0, 0, .5))
        material = bpy.data.materials.new("Fixture_PBR")
        material.use_nodes = True
        bsdf = material.node_tree.nodes.get("Principled BSDF")
        bsdf.inputs["Base Color"].default_value = (.1, .4, .17, 1)
        bsdf.inputs["Roughness"].default_value = .65
        bpy.context.object.data.materials.append(material)
    meshes = sorted((obj for obj in bpy.context.scene.objects if obj.type == "MESH"), key=lambda obj: obj.name)
    if not meshes or any(obj.type == "ARMATURE" for obj in bpy.context.scene.objects) or any(obj.data.shape_keys for obj in meshes):
        raise RuntimeError("Production jobs require static meshes; rigs/shape keys use the character workflow")
    used = set()
    for index, obj in enumerate(meshes):
        stable_id = str(obj.get("stable_id", "mesh-" + str(index).zfill(3)))
        if stable_id in used:
            raise RuntimeError("Source contains duplicate stable mesh IDs")
        used.add(stable_id)
        obj["stable_id"] = stable_id
    return meshes


def configure_cycles(scene, samples):
    scene.render.engine = "CYCLES"
    scene.cycles.device = "CPU"
    scene.cycles.samples = samples
    scene.render.image_settings.file_format = "PNG"
    scene.render.image_settings.color_mode = "RGBA"
    scene.render.image_settings.color_depth = "8"
    scene.render.resolution_percentage = 100
    scene.unit_settings.system = "METRIC"
    scene.unit_settings.scale_length = 1.0


def save_recipe(output):
    bpy.context.preferences.filepaths.save_version = 0
    # Paths refer to the one exported texture set; do not pack another copy.
    for image in bpy.data.images:
        if image.filepath and not image.packed_file:
            try:
                image.filepath = bpy.path.relpath(image.filepath, start=str(output))
            except (ValueError, OSError):
                pass
    bpy.ops.wm.save_as_mainfile(filepath=str(output / "recipe.blend"), compress=True)


def export_meshes(meshes, path):
    bpy.ops.object.select_all(action="DESELECT")
    for obj in meshes:
        obj.select_set(True)
    bpy.context.view_layer.objects.active = meshes[0]
    bpy.ops.export_scene.gltf(filepath=str(path), export_format="GLB", use_selection=True,
                              export_extras=True, export_animations=False, export_cameras=False,
                              export_lights=False, export_yup=True)


def bake(job, meshes, output):
    settings = job["bake"]
    scene = bpy.context.scene
    configure_cycles(scene, settings.get("samples", 16))
    scene.render.bake.margin = settings.get("margin_px", 4)
    scene.render.bake.use_selected_to_active = False
    scene.render.bake.use_pass_direct = False
    scene.render.bake.use_pass_indirect = False
    scene.render.bake.use_pass_color = True
    scene.render.bake.normal_space = "TANGENT"
    scene.render.bake.normal_r = "POS_X"
    scene.render.bake.normal_g = "NEG_Y" if settings["normal_convention"] == "directx" else "POS_Y"
    scene.render.bake.normal_b = "POS_Z"
    (output / "textures").mkdir()
    texture_info = []
    for index, obj in enumerate(meshes):
        select_only(obj)
        uv = settings["uv"]
        layer = obj.data.uv_layers.get(uv["name"])
        if layer is None:
            if uv["mode"] == "preserve":
                raise RuntimeError("Requested preserved UV layer is missing on " + obj.name)
            layer = obj.data.uv_layers.new(name=uv["name"])
        obj.data.uv_layers.active = layer
        layer.active_render = True
        if uv["mode"] == "smart_project":
            bpy.ops.object.mode_set(mode="EDIT")
            bpy.ops.mesh.select_all(action="SELECT")
            bpy.ops.uv.smart_project(angle_limit=1.1519173, island_margin=.03)
            bpy.ops.object.mode_set(mode="OBJECT")
        # Own material copies; never alter an importer-shared material in another mesh.
        if not obj.data.materials:
            material = bpy.data.materials.new("BakeSource_" + str(index))
            material.use_nodes = True
            obj.data.materials.append(material)
        for slot in obj.material_slots:
            if slot.material is None:
                slot.material = bpy.data.materials.new("BakeSource_" + str(index))
            slot.material = slot.material.copy()
            slot.material.use_nodes = True
        images = {}
        for channel in settings["channels"]:
            name = "mesh-" + str(index).zfill(3) + "_" + channel
            image = bpy.data.images.new(name, width=settings["resolution"], height=settings["resolution"], alpha=True)
            image.colorspace_settings.name = "sRGB" if channel == "base_color" else "Non-Color"
            targets = []
            for slot in obj.material_slots:
                node = slot.material.node_tree.nodes.new("ShaderNodeTexImage")
                node.image = image
                slot.material.node_tree.nodes.active = node
                node.select = True
                targets.append((slot.material.node_tree, node))
            bpy.ops.object.bake(type={"base_color": "DIFFUSE", "normal": "NORMAL", "ao": "AO"}[channel])
            path = output / "textures" / (name + ".png")
            image.filepath_raw = str(path)
            image.file_format = "PNG"
            image.save()
            for tree, node in targets:
                tree.nodes.remove(node)
            images[channel] = image
            texture_info.append({"mesh_id": obj["stable_id"], "channel": channel,
                                 "path": str(path.relative_to(output)), "colorspace": image.colorspace_settings.name,
                                 "normal_convention": settings["normal_convention"] if channel == "normal" else None})
        # glTF tangent normals are +Y even when a separate DirectX texture is requested.
        if "normal" in images and settings["normal_convention"] == "directx":
            source = images["normal"]
            normal = source.copy()
            normal.name = source.name + "_gltf"
            pixels = list(source.pixels[:])
            for offset in range(1, len(pixels), 4):
                pixels[offset] = 1.0 - pixels[offset]
            normal.pixels[:] = pixels
            normal.filepath_raw = str(output / "textures" / ("mesh-" + str(index).zfill(3) + "_normal_gltf.png"))
            normal.file_format = "PNG"
            normal.save()
            images["normal"] = normal
        for slot in obj.material_slots:
            tree = slot.material.node_tree
            shader = next((node for node in tree.nodes if node.type == "BSDF_PRINCIPLED"), None)
            if shader is None:
                raise RuntimeError("Bake output expects a Principled material")
            if "base_color" in images:
                node = tree.nodes.new("ShaderNodeTexImage"); node.image = images["base_color"]
                tree.links.new(node.outputs["Color"], shader.inputs["Base Color"])
            if "normal" in images:
                node = tree.nodes.new("ShaderNodeTexImage"); node.image = images["normal"]
                normal = tree.nodes.new("ShaderNodeNormalMap"); normal.uv_map = uv["name"]
                tree.links.new(node.outputs["Color"], normal.inputs["Color"])
                tree.links.new(normal.outputs["Normal"], shader.inputs["Normal"])
            if "ao" in images:
                group = bpy.data.node_groups.get("glTF Material Output")
                if group is None:
                    group = bpy.data.node_groups.new("glTF Material Output", "ShaderNodeTree")
                    group.interface.new_socket(name="Occlusion", in_out="INPUT", socket_type="NodeSocketFloat")
                gltf = tree.nodes.new("ShaderNodeGroup"); gltf.node_tree = group
                node = tree.nodes.new("ShaderNodeTexImage"); node.image = images["ao"]
                tree.links.new(node.outputs["Color"], gltf.inputs["Occlusion"])
    export_meshes(meshes, output / "asset.glb")
    save_recipe(output)
    return {"textures": texture_info, "uv": settings["uv"], "material_export_normal_convention": "opengl",
            "storage_reason": "External texture channels and one editable recipe are production outputs; GLB embeds maps for self-contained engine import"}


def scatter(job, meshes, output):
    settings = job["scatter"]
    rng = random.Random(settings["seed"])
    xmin, ymin, xmax, ymax = settings["bounds_xy"]
    mask = None
    if settings.get("density_mask"):
        reference = settings["density_mask"]
        if file_hash(reference["path"]) != reference["sha256"]:
            raise RuntimeError("Density mask changed before use")
        mask = bpy.data.images.load(reference["path"], check_existing=False)
        mask.colorspace_settings.name = "Non-Color"
        pixels = list(mask.pixels[:])
        width, height = mask.size[:]
    rows = []
    attempts = 0
    limit = max(1000, settings["count"] * 100)
    while len(rows) < settings["count"] and attempts < limit:
        attempts += 1
        x, y = rng.uniform(xmin, xmax), rng.uniform(ymin, ymax)
        if any(a <= x <= c and b <= y <= d for a, b, c, d in settings.get("exclude_rects", [])):
            continue
        if mask:
            px = min(width-1, int((x-xmin)/(xmax-xmin)*width))
            py = min(height-1, int((y-ymin)/(ymax-ymin)*height))
            offset = (py * width + px) * 4
            density = sum(pixels[offset:offset+3])/3 * pixels[offset+3]
            if rng.random() > density:
                continue
        yaw = rng.uniform(-math.pi, math.pi)
        scale = rng.uniform(*settings.get("scale", [1, 1]))
        rows.append({"id": job["job_id"] + ":instance:" + str(len(rows)).zfill(6),
                     "translation_m": [x, settings.get("height_m", 0), -y],
                     "rotation_quaternion_xyzw": [0, math.sin(yaw/2), 0, math.cos(yaw/2)],
                     "scale": [scale, scale, scale]})
    if len(rows) != settings["count"]:
        raise RuntimeError("Mask/exclusions could not admit the requested count within the bounded sampling budget")
    source = job.get("input")
    if source is None:
        export_meshes(meshes, output / "prototype.glb")
        source = {"path": str(output / "prototype.glb"), "sha256": file_hash(output / "prototype.glb")}
    result = {"schema": 1, "kind": "instance-transforms", "coordinate_system": "glTF-Y-up-right-handed",
              "source": source, "seed": settings["seed"], "count": len(rows), "instances": rows,
              "density_mask": settings.get("density_mask"), "sampling_attempts": attempts}
    (output / "instances.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    return {"count": len(rows), "source": source, "coordinate_system": result["coordinate_system"],
            "geometry_duplicated": False, "mask_used": bool(mask)}


def render(job, meshes, output):
    settings = job["render"]
    scene = bpy.context.scene
    configure_cycles(scene, settings.get("samples", 16))
    scene.render.resolution_x, scene.render.resolution_y = settings["resolution"]
    scene.render.film_transparent = settings.get("transparent_background", False)
    scene.view_settings.view_transform = settings["view_transform"]
    scene.view_settings.look = "None"
    scene.view_settings.exposure = 0
    scene.view_settings.gamma = 1
    world = bpy.data.worlds.new("DeclaredWorld"); world.use_nodes = True
    background = world.node_tree.nodes.get("Background")
    background.inputs["Color"].default_value = (*settings["environment"]["color"], 1)
    background.inputs["Strength"].default_value = settings["environment"]["strength"]
    scene.world = world
    camera_data = bpy.data.cameras.new("DeclaredCamera")
    camera = bpy.data.objects.new("DeclaredCamera", camera_data)
    scene.collection.objects.link(camera)
    spec = settings["camera"]
    camera.location = spec["position"]
    camera.rotation_euler = (Vector(spec["target"])-camera.location).to_track_quat("-Z", "Y").to_euler()
    camera_data.type = "ORTHO" if spec["projection"] == "orthographic" else "PERSP"
    camera_data.ortho_scale, camera_data.lens = spec.get("ortho_scale", 3), spec.get("lens_mm", 50)
    scene.camera = camera
    for index, spec in enumerate(settings["lights"]):
        light_data = bpy.data.lights.new("DeclaredLight" + str(index), spec["type"])
        light_data.energy = spec["energy"]
        if spec["type"] == "AREA":
            light_data.size = spec.get("size", 3)
        obj = bpy.data.objects.new(light_data.name, light_data); scene.collection.objects.link(obj)
        obj.location = spec["position"]
        obj.rotation_euler = (Vector(spec.get("target", [0, 0, 0]))-obj.location).to_track_quat("-Z", "Y").to_euler()
    initial = {obj: obj.rotation_euler.copy() for obj in meshes}
    (output / "frames").mkdir()
    for frame in settings["frames"]:
        scene.frame_set(frame)
        for obj in meshes:
            obj.rotation_euler = initial[obj]
            obj.rotation_euler.z += math.radians(settings.get("turntable_degrees_per_frame", 0) * frame)
        scene.render.filepath = str(output / "frames" / ("frame-" + str(frame).zfill(6) + ".png"))
        bpy.ops.render.render(write_still=True)
    return {"frames": settings["frames"], "resolution": settings["resolution"],
            "color_management": {"view_transform": settings["view_transform"], "look": "None", "exposure": 0, "gamma": 1},
            "render_engine": "CYCLES", "device": "CPU", "recipe": "job.json references immutable input; no duplicate scene snapshot"}


def main():
    args = sys.argv[sys.argv.index("--")+1:]
    job = json.loads(Path(args[0]).read_text(encoding="utf-8"))
    output = Path(job["output_dir"])
    report = {"schema": 1, "kind": "blender-production-report", "job_sha256": job_hash(job),
              "worker_sha256": file_hash(__file__),
              "input": job.get("input"), "operation": job["operation"], "blender_version": bpy.app.version_string,
              "execution": "factory-startup-background", "native_admission": "pending"}
    try:
        meshes = import_meshes(job)
        details = {"bake": bake, "scatter": scatter, "render": render}[job["operation"]](job, meshes, output)
        report.update(status="complete", details=details,
                      outputs=[{"path": str(path.relative_to(output)), "bytes": path.stat().st_size, "sha256": file_hash(path)}
                               for path in sorted(output.rglob("*")) if path.is_file() and path.name not in {"job.json", ".production.lock", "invocation.log", "report.json"}])
    except Exception:
        report.update(status="failed", error=traceback.format_exc(), outputs=[])
        (output / "report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        raise
    (output / "report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")


main()
