extends Node
## Additive art is attached to its gameplay owner; raw source transforms stay intact.
@export var manifest_path: String
@export var effect_script: Script
@export var water_shader: Shader
@export var grass_shader: Shader
@export var ground_shader: Shader
@export var texture_inputs: Dictionary = {}
var manifest: Dictionary = {}
var assembly_receipts: Array = []
var assembly_errors: Array = []
var assembled := false

func _ready() -> void:
	await get_tree().process_frame
	var parsed = JSON.parse_string(FileAccess.get_file_as_string(manifest_path))
	if not parsed is Dictionary:
		assembly_errors.append("Invalid assembly manifest")
		assembled = true
		return
	manifest = parsed
	for binding in manifest.get("bindings", []):
		_attach(binding)
	if not manifest.get("effects", {}).is_empty():
		if not effect_script:
			assembly_errors.append("Effect script binding is missing")
		else:
			var effects := Node3D.new()
			effects.name = "GreyboxEffects"
			effects.set_script(effect_script)
			effects.set("config_json", JSON.stringify(manifest.effects))
			effects.set("water_shader", water_shader)
			effects.set("grass_shader", grass_shader)
			effects.set("ground_shader", ground_shader)
			effects.set("texture_inputs", texture_inputs)
			get_parent().add_child(effects)
			for error in effects.get("errors"):
				assembly_errors.append(error)
	assembled = true

func _vector(value: Array) -> Vector3:
	return Vector3(float(value[0]), float(value[1]), float(value[2]))

func _attach(binding: Dictionary) -> void:
	var logical_owner := get_parent().get_node_or_null(NodePath(binding.owner))
	if not logical_owner is Node3D:
		assembly_errors.append("Missing Node3D owner: " + str(binding.owner))
		return
	var art := Node3D.new()
	art.name = "Art_" + str(binding.id).validate_node_name()
	art.set_meta("greybox_binding", binding.id)
	logical_owner.add_child(art)
	var source: Dictionary = binding.get("source", {})
	var visual: Node3D
	if source.has("path"):
		var packed = load(source.path)
		if not packed is PackedScene:
			assembly_errors.append("Source is not a PackedScene: " + str(source.path))
			art.queue_free()
			return
		visual = packed.instantiate() as Node3D
		if not visual:
			assembly_errors.append("Source root must be Node3D: " + str(source.path))
			art.queue_free()
			return
	else:
		visual = _primitive(source, binding)
	var raw_visual := visual
	if source.get("basis", "godot") == "z_up":
		var source_frame := Node3D.new()
		source_frame.name = "SourceFrame"
		source_frame.rotation.x = -PI * 0.5
		source_frame.add_child(visual)
		raw_visual = source_frame
	art.add_child(raw_visual)
	# Every instance starts from the immutable imported resource. Never bake/flatten.
	var bounds := _bounds(raw_visual, Transform3D.IDENTITY)
	var unit_scale := float({"m": 1.0, "cm": 0.01, "mm": 0.001}.get(source.get("units", "m"), 1.0))
	var factor := float(binding.get("uniform_scale", 1.0)) * unit_scale
	var normalize: Dictionary = binding.get("normalize", {})
	var rotation_basis := Basis.from_euler(_vector(binding.get("rotation_degrees", [0, 0, 0])) * PI / 180.0)
	var normalization_space: String = normalize.get("space", "world")
	var owner_bounds: AABB = _bounds(raw_visual, Transform3D(rotation_basis, Vector3.ZERO))
	var world_bounds: AABB = _bounds(raw_visual, Transform3D(logical_owner.global_basis * rotation_basis, Vector3.ZERO))
	var measured_bounds: AABB = world_bounds if normalization_space == "world" else owner_bounds
	if normalize.get("mode", "none") == "uniform_bounds":
		var longest := maxf(measured_bounds.size.x, maxf(measured_bounds.size.y, measured_bounds.size.z))
		if longest <= 0.000001:
			assembly_errors.append("Cannot normalize empty mesh bounds: " + str(binding.id))
		else:
			factor *= float(normalize.get("max_extent", 1.0)) / (longest * unit_scale)
	art.scale = Vector3.ONE * factor
	var source_anchor := Vector3.ZERO
	if binding.get("anchor_mode", "origin") == "bottom_center":
		source_anchor = Vector3(bounds.get_center().x, bounds.position.y, bounds.get_center().z)
	elif binding.has("source_anchor"):
		source_anchor = _vector(binding.source_anchor)
	art.rotation_degrees = _vector(binding.get("rotation_degrees", [0, 0, 0]))
	art.position = _vector(binding.get("anchor", [0, 0, 0])) - art.basis * source_anchor
	# Imported materials are preserved unless an explicit art treatment is declared.
	if binding.has("material_override"):
		_override_material(visual, binding.material_override)
	for path in binding.get("hide", []):
		var old = get_parent().get_node_or_null(NodePath(path))
		if old is VisualInstance3D:
			old.visible = false
		else:
			assembly_errors.append("hide target must be VisualInstance3D, never gameplay/collision: " + str(path))
	assembly_receipts.append({"id": binding.id, "owner": str(logical_owner.get_path()),
		"art": str(art.get_path()), "uniform_scale": factor,
		"raw_bounds": [bounds.position.x, bounds.position.y, bounds.position.z, bounds.size.x, bounds.size.y, bounds.size.z],
		"normalization_space": normalization_space,
		"normalized_extent": maxf(measured_bounds.size.x, maxf(measured_bounds.size.y, measured_bounds.size.z)) * factor,
		"local_extent": maxf(owner_bounds.size.x, maxf(owner_bounds.size.y, owner_bounds.size.z)) * factor,
		"world_extent": maxf(world_bounds.size.x, maxf(world_bounds.size.y, world_bounds.size.z)) * factor,
		"source_units": source.get("units", "m"), "source_basis": source.get("basis", "godot"),
		"source_materials_preserved": not binding.has("material_override")})

func _primitive(source: Dictionary, binding: Dictionary) -> MeshInstance3D:
	var mesh := MeshInstance3D.new()
	var size := _vector(source.get("size", [1, 1, 1]))
	match source.get("primitive", "box"):
		"sphere":
			var shape := SphereMesh.new()
			shape.radius = size.x * 0.5
			shape.height = size.y
			shape.radial_segments = 16
			shape.rings = 8
			mesh.mesh = shape
		"cylinder":
			var shape := CylinderMesh.new()
			shape.top_radius = size.x * 0.5
			shape.bottom_radius = size.z * 0.5
			shape.height = size.y
			shape.radial_segments = 8
			mesh.mesh = shape
		_:
			var shape := BoxMesh.new()
			shape.size = size
			mesh.mesh = shape
	mesh.material_override = _material(binding.get("material", {"color": "#cccccc"}))
	return mesh

func _material(spec: Dictionary) -> StandardMaterial3D:
	var material := StandardMaterial3D.new()
	material.albedo_color = Color(str(spec.get("color", "#cccccc")))
	material.roughness = float(spec.get("roughness", 0.8))
	material.metallic = float(spec.get("metallic", 0.0))
	return material

func _override_material(node: Node, spec: Dictionary) -> void:
	if node is MeshInstance3D:
		node.material_override = _material(spec)
	for child in node.get_children():
		_override_material(child, spec)

func _bounds(node: Node, parent_transform: Transform3D) -> AABB:
	var transform := parent_transform
	if node is Node3D:
		transform = parent_transform * node.transform
	var result := AABB()
	var found := false
	if node is MeshInstance3D and node.mesh:
		result = transform * node.mesh.get_aabb()
		found = true
	for child in node.get_children():
		var child_bounds := _bounds(child, transform)
		if child_bounds.size.length_squared() > 0:
			result = result.merge(child_bounds) if found else child_bounds
			found = true
	return result
