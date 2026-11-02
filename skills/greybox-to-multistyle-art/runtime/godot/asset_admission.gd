extends SceneTree
## Import a canonical GLB directly. Never invoke editor import or copy assets.
var config: Dictionary
var report := {"schema": 1, "engine": "godot", "status": "failed", "checks": {}, "scope": "static_geometry_import_only"}
var lows := Vector3(INF, INF, INF)
var highs := Vector3(-INF, -INF, -INF)
var mesh_ids: Array = []
var all_ids: Array = []
var materials: Array = []
var mesh_count := 0
var missing_material := false

func _initialize():
    # SceneTree initialization is not an in-tree ready callback.
    call_deferred("_probe")

func _stable_id(node: Node) -> String:
    for key in node.get_meta_list():
        var value = node.get_meta(key)
        if str(key) == "stable_id":
            return str(value)
        if value is Dictionary and value.has("stable_id"):
            return str(value["stable_id"])
    return ""

func _walk(node: Node, parent_transform: Transform3D):
    var transform := parent_transform
    if node is Node3D:
        transform = parent_transform * node.transform
    var identity := _stable_id(node)
    if identity != "":
        all_ids.append(identity)
    if node is MeshInstance3D and node.mesh:
        mesh_count += 1
        mesh_ids.append(identity)
        var box: AABB = node.mesh.get_aabb()
        for i in range(8):
            # Explicit local matrix accumulation also works outside the tree.
            var point: Vector3 = transform * box.get_endpoint(i)
            lows = lows.min(point)
            highs = highs.max(point)
        for i in range(node.mesh.get_surface_count()):
            var material = node.get_active_material(i)
            if not material is BaseMaterial3D:
                missing_material = true
                continue
            var linear: Color = material.albedo_color.srgb_to_linear()
            materials.append({"name": material.resource_name, "roughness": material.roughness,
                "metallic": material.metallic, "albedo_srgb": [material.albedo_color.r, material.albedo_color.g, material.albedo_color.b],
                "albedo_linear": [linear.r, linear.g, linear.b], "emission_enabled": material.emission_enabled,
                "normal_enabled": material.normal_enabled, "normal_texture": material.normal_texture != null,
                "albedo_texture": material.albedo_texture != null,
                "roughness_texture": material.roughness_texture != null,
                "metallic_texture": material.metallic_texture != null})
    for child in node.get_children():
        _walk(child, transform)

func _material_checks() -> bool:
    if missing_material:
        return false
    var expected: Array = config.get("source_materials", [])
    if expected.is_empty():
        # No PBR requirement was asserted by the source; retain observations.
        return true
    if materials.is_empty():
        return false
    for actual in materials:
        var source: Dictionary = {}
        for candidate in expected:
            if candidate.get("name") == actual["name"]:
                source = candidate
                break
        if source.is_empty() and expected.size() == 1:
            source = expected[0]
        if source.is_empty():
            return false
        var pbr: Dictionary = source.get("principled", {})
        for item in [["Roughness", "roughness"], ["Metallic", "metallic"]]:
            var value = pbr.get(item[0])
            if value is float or value is int:
                if abs(float(value) - float(actual[item[1]])) > 0.03:
                    return false
        var base = pbr.get("Base Color")
        if base is Array and base.size() >= 3 and not actual["albedo_texture"]:
            for i in range(3):
                if abs(float(base[i]) - float(actual["albedo_linear"][i])) > 0.03:
                    return false
        var emission = pbr.get("Emission Strength")
        if (emission is float or emission is int) and emission <= 0.00001 and actual["emission_enabled"]:
            return false
        for texture in source.get("textures", []):
            var channels: Array = texture.get("channels", [])
            if channels.has("Base Color") and not actual["albedo_texture"]:
                return false
            if channels.has("Normal") and (not actual["normal_enabled"] or not actual["normal_texture"]):
                return false
    return true

func _probe():
    var args := OS.get_cmdline_user_args()
    if args.size() != 1:
        push_error("Expected one native probe config argument")
        quit(2)
        return
    var parsed = JSON.parse_string(FileAccess.get_file_as_string(args[0]))
    if not parsed is Dictionary:
        push_error("Native probe config is not a JSON object")
        quit(2)
        return
    config = parsed
    report["attempt"] = config["attempt"]
    report["engine_version"] = Engine.get_version_info().get("string")
    report["asset_sha256"] = FileAccess.get_sha256(config["asset_path"])
    var state := GLTFState.new()
    var document := GLTFDocument.new()
    var error := document.append_from_file(config["asset_path"], state)
    report["import_error"] = error
    if error == OK and report["asset_sha256"] == config["asset_sha256"]:
        var scene := document.generate_scene(state)
        if scene:
            _walk(scene, Transform3D.IDENTITY)
            var dimensions := highs - lows
            var expected: Array = config["expected_dimensions_m"]
            var bounds_ok := mesh_count > 0
            var measured := [dimensions.x, dimensions.y, dimensions.z]
            for i in range(3):
                bounds_ok = bounds_ok and is_finite(measured[i]) and measured[i] > 0.0 and abs(measured[i] - float(expected[i])) < max(0.001, float(expected[i]) * 0.0001)
            if config.get("require_base_contact", false):
                bounds_ok = bounds_ok and abs(lows.y) < 0.001
            var identities_ok: bool = mesh_ids.size() == config["expected_mesh_ids"].size()
            var unique := {}
            for identity in mesh_ids:
                identities_ok = identities_ok and identity != "" and not unique.has(identity) and config["expected_mesh_ids"].has(identity)
                unique[identity] = true
            report["mesh_count"] = mesh_count
            report["dimensions_m"] = measured
            report["bounds_min_m"] = [lows.x, lows.y, lows.z]
            report["bounds_max_m"] = [highs.x, highs.y, highs.z]
            report["native_mesh_stable_ids"] = mesh_ids
            report["native_stable_ids"] = all_ids
            report["materials"] = materials
            report["checks"] = {"mesh_bounds": bounds_ok, "stable_ids": identities_ok, "materials": _material_checks()}
            report["status"] = "passed" if report["checks"].values().all(func(value): return value) else "failed"
            scene.free()
    var file := FileAccess.open(config["output_path"], FileAccess.WRITE)
    if not file:
        push_error("Cannot write new native probe report")
        quit(2)
        return
    file.store_string(JSON.stringify(report, "  "))
    file.close()
    print("GREYBOX_NATIVE_ADMISSION " + JSON.stringify(report))
    quit(0 if report["status"] == "passed" else 2)
