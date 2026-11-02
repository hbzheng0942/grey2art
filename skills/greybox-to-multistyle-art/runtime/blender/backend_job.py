"""Executed inside Blender after the validated JOB literal is prepended.

Never opens/saves a .blend or uses undo as rollback. All created data is removed.
This intentionally rejects rigs, shape keys, and non-object live edit modes.
"""
import bpy
from mathutils import Vector
import hashlib
import json
from pathlib import Path
import traceback


def _hash(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _ids():
    return {item for prop in bpy.data.bl_rna.properties
            if prop.type == "COLLECTION" and prop.identifier != "rna_type"
            for item in getattr(bpy.data, prop.identifier) if isinstance(item, bpy.types.ID)}


def _bounds(objects):
    vertices = [obj.matrix_world @ Vector(corner) for obj in objects for corner in obj.bound_box]
    return (Vector(tuple(min(v[i] for v in vertices) for i in range(3))),
            Vector(tuple(max(v[i] for v in vertices) for i in range(3))))


def _materials(objects):
    result = []
    for mat in sorted({m for ob in objects for m in ob.data.materials if m}, key=lambda m: m.name):
        row = {"name": mat.name, "use_nodes": mat.use_nodes, "textures": [], "warnings": []}
        if mat.use_nodes:
            for node in mat.node_tree.nodes:
                if node.type != "TEX_IMAGE" or not node.image:
                    continue
                pending = [link for socket in node.outputs for link in socket.links]
                visited = set()
                channels = set()
                while pending:
                    link = pending.pop()
                    target = link.to_node
                    if target.type == "BSDF_PRINCIPLED":
                        channels.add(link.to_socket.name)
                    elif target not in visited:
                        visited.add(target)
                        pending.extend(edge for socket in target.outputs for edge in socket.links)
                channels = sorted(channels)
                data_channels = bool(set(channels) & {"Roughness", "Metallic", "Normal", "Height"})
                color_channels = bool(set(channels) & {"Base Color", "Emission Color", "Emission"})
                expected = "Non-Color" if data_channels and not color_channels else "sRGB" if color_channels and not data_channels else None
                before = node.image.colorspace_settings.name
                if data_channels and color_channels:
                    row["warnings"].append("Shared color/data image requires deliberate channel separation")
                if expected and before != expected:
                    if JOB.get("material_policy") == "normalize_pbr":
                        # Images can be reused by the importer or by color/data slots.
                        # Copy only the image whose interpretation changes.
                        node.image = node.image.copy()
                        node.image.colorspace_settings.name = expected
                    else:
                        row["warnings"].append("Review texture colorspace: " + node.image.name)
                row["textures"].append({"image": node.image.name, "channels": channels,
                                        "colorspace_before": before,
                                        "colorspace_after": node.image.colorspace_settings.name})
            for node in mat.node_tree.nodes:
                if node.type == "BSDF_PRINCIPLED":
                    row["principled"] = {key: ("linked" if node.inputs[key].is_linked else
                        list(node.inputs[key].default_value) if hasattr(node.inputs[key].default_value, "__len__")
                        else node.inputs[key].default_value)
                        for key in ("Base Color", "Metallic", "Roughness", "Emission Strength") if key in node.inputs}
        result.append(row)
    return result


def _run():
    if bpy.context.mode != "OBJECT":
        raise RuntimeError("Live Blender is in edit/pose/sculpt mode; finish that operation or use background CLI")
    output = Path(JOB["output_dir"])
    output.mkdir(parents=True, exist_ok=True)
    for name in ("asset.glb", "report.json", "preview.png"):
        if (output / name).exists():
            raise RuntimeError("Existing output refused: " + str(output / name))
    if JOB.get("input") and _hash(JOB["input"]["path"]) != JOB["input"]["sha256"]:
        raise RuntimeError("Immutable source hash changed")
    original_ids = _ids()
    original_scene = bpy.context.scene
    window = bpy.context.window
    original_layer = window.view_layer if window else bpy.context.view_layer
    original_selected = tuple(bpy.context.selected_objects)
    original_active = original_layer.objects.active
    original_filepath = bpy.data.filepath
    def original_settings():
        return {"camera": original_scene.camera.name if original_scene.camera else None,
                "world": original_scene.world.name if original_scene.world else None,
                "render_engine": original_scene.render.engine,
                "resolution": [original_scene.render.resolution_x, original_scene.render.resolution_y,
                               original_scene.render.resolution_percentage],
                "render_filepath": original_scene.render.filepath,
                "frame": original_scene.frame_current,
                "units": [original_scene.unit_settings.system, original_scene.unit_settings.scale_length]}
    before_settings = original_settings()
    scene = None
    report = {"schema": 1, "job_id": JOB["job_id"], "asset_id": JOB["asset_id"],
              "job_sha256": hashlib.sha256(json.dumps(JOB, sort_keys=True).encode()).hexdigest(),
              "input": JOB.get("input"), "blender_version": bpy.app.version_string,
              "kind": JOB["kind"], "operations": JOB.get("operations", []),
              "scope": "static_geometry_only", "user_state_restored": False}
    failure = None
    try:
        scene = bpy.data.scenes.new("GreyboxJob_" + JOB["job_id"])
        scene.unit_settings.system = "METRIC"
        scene.unit_settings.scale_length = 1.0
        if window:
            window.scene = scene
        with bpy.context.temp_override(scene=scene, view_layer=scene.view_layers[0], collection=scene.collection):
            if JOB["kind"] == "diagnostic_cube":
                bpy.ops.mesh.primitive_cube_add(size=1)
                obj = bpy.context.object
                obj.name = JOB["asset_id"]
                material = bpy.data.materials.new("Diagnostic_PBR")
                material.use_nodes = True
                principled = next(n for n in material.node_tree.nodes if n.type == "BSDF_PRINCIPLED")
                principled.inputs["Base Color"].default_value = (0.12, 0.32, 0.7, 1)
                principled.inputs["Roughness"].default_value = 0.65
                obj.data.materials.append(material)
            else:
                bpy.ops.import_scene.gltf(filepath=JOB["input"]["path"])
            meshes = sorted((o for o in scene.objects if o.type == "MESH"), key=lambda o: o.name)
            if not meshes:
                raise RuntimeError("Import contains no mesh")
            if any(o.type == "ARMATURE" for o in scene.objects) or any(o.data.shape_keys for o in meshes):
                raise RuntimeError("Static geometry backend refuses rigs or shape keys; use the character path")
            # Bake each complete world matrix before detaching parents, preserving geometry.
            matrices = {o: o.matrix_world.copy() for o in meshes}
            for index, obj in enumerate(meshes):
                obj.data = obj.data.copy()
                obj.data.transform(matrices[obj])
                obj.parent = None
                obj.matrix_world.identity()
                obj["stable_id"] = obj.get("stable_id") or JOB["asset_id"] + ":mesh:" + str(index).zfill(3)
                obj["greybox_asset_id"] = JOB["asset_id"]
                if JOB.get("material_policy") == "normalize_pbr":
                    for slot in obj.material_slots:
                        if slot.material in original_ids:
                            slot.material = slot.material.copy()
            bpy.context.view_layer.update()
            low, high = _bounds(meshes)
            normalize = JOB.get("normalize", {})
            factor = normalize.get("unit_scale", 1.0)
            if normalize.get("target_height_m"):
                if high.z - low.z <= 0:
                    raise RuntimeError("Cannot normalize a zero-height mesh")
                factor = normalize["target_height_m"] / (high.z - low.z)
            anchor = normalize.get("anchor", "base_center")
            origin = Vector((0, 0, 0)) if anchor == "origin" else (low + high) / 2
            if anchor == "base_center":
                origin.z = low.z
            for obj in meshes:
                for vertex in obj.data.vertices:
                    vertex.co = (vertex.co - origin) * factor
                for operation in JOB.get("operations", []):
                    modifier = obj.modifiers.new("Declared_Bevel", "BEVEL")
                    modifier.width = operation["width_m"]
                    modifier.segments = operation.get("segments", 2)
            bpy.context.view_layer.update()
            low, high = _bounds(meshes)
            dimensions = list(high - low)
            if JOB.get("max_dimensions_m") and any(a > b + 1e-5 for a, b in zip(dimensions, JOB["max_dimensions_m"])):
                raise RuntimeError("Geometry exceeds approved visual envelope")
            for obj in scene.objects:
                obj.select_set(False)
            for obj in meshes:
                obj.select_set(True)
            for anchor_spec in JOB.get("semantic_anchors", []):
                obj = bpy.data.objects.new(anchor_spec["id"], None)
                scene.collection.objects.link(obj)
                obj.location = anchor_spec["position_m"]
                obj["stable_id"] = JOB["asset_id"] + ":anchor:" + anchor_spec["id"]
                obj["semantic_anchor"] = anchor_spec["id"]
                obj.select_set(True)
            report.update(dimensions_m=dimensions, normalization={"uniform_scale": factor,
                          "origin_before_m": list(origin), "anchor": anchor},
                          materials=_materials(meshes), mesh_count=len(meshes),
                          source_mesh_stable_ids=[o["stable_id"] for o in meshes])
            bpy.context.view_layer.objects.active = meshes[0]
            bpy.ops.export_scene.gltf(filepath=str(output / "asset.glb"), export_format="GLB",
                use_selection=True, use_active_scene=True, export_extras=True, export_apply=True, export_animations=False,
                export_cameras=False, export_lights=False, export_yup=True)
            report["output"] = {"path": str(output / "asset.glb"), "sha256": _hash(output / "asset.glb"),
                                "format": "glTF2-GLB", "units": "metres", "up_axis": "+Y"}
            if JOB.get("render"):
                engines = {item.identifier for item in scene.render.bl_rna.properties["engine"].enum_items}
                scene.render.engine = "BLENDER_EEVEE_NEXT" if "BLENDER_EEVEE_NEXT" in engines else "BLENDER_EEVEE"
                scene.render.resolution_x = 384
                scene.render.resolution_y = 384
                scene.render.resolution_percentage = 100
                scene.render.image_settings.file_format = "PNG"
                scene.render.filepath = str(output / "preview.png")
                world = bpy.data.worlds.new("Diagnostic_World")
                world.use_nodes = True
                background = next(n for n in world.node_tree.nodes if n.type == "BACKGROUND")
                background.inputs["Color"].default_value = (0.12, 0.12, 0.12, 1)
                scene.world = world
                size = max(dimensions)
                center = (low + high) / 2
                camera_data = bpy.data.cameras.new("Diagnostic_Camera")
                camera = bpy.data.objects.new("Diagnostic_Camera", camera_data)
                scene.collection.objects.link(camera)
                camera.location = center + Vector((2.5, -3.2, 2.0)) * size
                camera.rotation_euler = (center - camera.location).to_track_quat("-Z", "Y").to_euler()
                camera_data.type = "ORTHO"
                camera_data.ortho_scale = 2.0 * size
                scene.camera = camera
                light_data = bpy.data.lights.new("Diagnostic_Key", "AREA")
                light_data.energy = 600
                light_data.shape = "DISK"
                light_data.size = 3 * size
                light = bpy.data.objects.new("Diagnostic_Key", light_data)
                scene.collection.objects.link(light)
                light.location = center + Vector((2, -3, 4)) * size
                light.rotation_euler = (center - light.location).to_track_quat("-Z", "Y").to_euler()
                bpy.ops.render.render(write_still=True, scene=scene.name)
                report["preview_sha256"] = _hash(output / "preview.png")
            report["status"] = "complete"
    except Exception:
        report["status"] = "failed"
        failure = traceback.format_exc()
        report["error"] = failure
    finally:
        if window:
            window.scene = original_scene
            window.view_layer = original_layer
        bpy.data.batch_remove(ids=tuple(_ids() - original_ids))
        # Existing data, selection and camera/render values were never modified.
        remaining_selected = tuple(bpy.context.selected_objects)
        report["user_state_restored"] = (bpy.data.filepath == original_filepath and
            bpy.context.scene == original_scene and set(remaining_selected) == set(original_selected) and
            original_layer.objects.active == original_active and _ids() == original_ids and
            original_settings() == before_settings)
        report["original_scene_settings_before"] = before_settings
        report["original_scene_settings_after"] = original_settings()
        with (output / "report.json").open("x", encoding="utf-8") as handle:
            json.dump(report, handle, indent=2)
            handle.write("\n")
    if failure:
        raise RuntimeError(failure)
    if not report["user_state_restored"]:
        raise RuntimeError("User state preservation check failed; inspect report")
    print("GREYBOX_BLENDER_JOB " + json.dumps({"job_id": JOB["job_id"], "status": report["status"],
          "output": str(output / "asset.glb"), "user_state_restored": report["user_state_restored"]}))


_run()
