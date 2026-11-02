extends Node3D
## Owned effect recipes. Gameplay geometry, input and renderer stay with the host.
@export var config_json: String = "{}"
@export var water_shader: Shader
@export var grass_shader: Shader
@export var ground_shader: Shader
@export var texture_inputs: Dictionary = {}
var errors: Array = []
var grass_report: Dictionary = {}

func _v(value: Array) -> Vector3:
	return Vector3(float(value[0]), float(value[1]), float(value[2]))

func _color(value: Array) -> Color:
	return Color(float(value[0]), float(value[1]), float(value[2]), float(value[3]) if value.size() > 3 else 1.0)

func _material(kind: String) -> ShaderMaterial:
	var shader: Shader = {"water": water_shader, "grass": grass_shader, "ground": ground_shader}.get(kind)
	if not shader:
		errors.append("Effect shader binding is missing: " + kind)
		return null
	var material := ShaderMaterial.new()
	material.shader = shader
	return material

func _texture(path: String) -> Texture2D:
	var texture := texture_inputs.get(path) as Texture2D
	if not texture:
		errors.append("Effect input has no readable Texture2D binding: " + path)
	return texture

func _ready() -> void:
	var config = JSON.parse_string(config_json)
	if not config is Dictionary:
		errors.append("Invalid effect configuration")
		return
	if config.has("lighting"):
		_lighting(config.lighting)
	for kind in ["water", "ground"]:
		if config.has(kind):
			_surface(kind, config[kind])
	if config.has("grass"):
		_grass(config.grass)

func _lighting(c: Dictionary) -> void:
	var sun: DirectionalLight3D
	if c.has("light_path"):
		sun = get_tree().current_scene.get_node_or_null(NodePath(c.light_path)) as DirectionalLight3D
		if not sun:
			errors.append("lighting.light_path must identify an existing DirectionalLight3D")
			return
	else:
		sun = DirectionalLight3D.new()
		sun.name = "RecipeSun"
		add_child(sun)
	sun.rotation_degrees = _v(c.get("sun_rotation", [-45, -30, 0]))
	sun.light_energy = float(c.get("sun_energy", 1.0))
	sun.light_color = _color(c.get("color", [1.0, 0.95, 0.85]))
	sun.shadow_enabled = bool(c.get("shadows", true))
	var environment := Environment.new()
	environment.background_mode = Environment.BG_COLOR
	environment.background_color = _color(c.get("background_color", [0.25, 0.4, 0.6]))
	if bool(c.get("sky", true)):
		var sky_material := ProceduralSkyMaterial.new()
		sky_material.sky_top_color = environment.background_color
		sky_material.sky_horizon_color = _color(c.get("ambient_color", [0.65, 0.75, 0.9]))
		environment.sky = Sky.new()
		environment.sky.sky_material = sky_material
		environment.background_mode = Environment.BG_SKY
	environment.ambient_light_source = Environment.AMBIENT_SOURCE_COLOR
	environment.ambient_light_color = _color(c.get("ambient_color", [0.65, 0.75, 0.9]))
	environment.ambient_light_energy = float(c.get("ambient_energy", 0.5))
	environment.tonemap_exposure = float(c.get("exposure", 1.0))
	environment.tonemap_mode = Environment.TONE_MAPPER_FILMIC
	environment.fog_enabled = float(c.get("fog_density", 0.0)) > 0
	environment.fog_density = float(c.get("fog_density", 0.0))
	# Compatibility lacks glow. The configured request remains observable.
	var renderer: String = ProjectSettings.get_setting("rendering/renderer/rendering_method", "gl_compatibility")
	environment.glow_enabled = bool(c.get("bloom", false)) and renderer != "gl_compatibility"
	if bool(c.get("bloom", false)) and renderer == "gl_compatibility":
		errors.append("Bloom unavailable in Compatibility; renderer retained")
	var found := get_tree().current_scene.find_children("*", "WorldEnvironment", true, false)
	if not found.is_empty():
		found[0].environment = environment
	else:
		var node := WorldEnvironment.new()
		node.environment = environment
		add_child(node)

func _surface(kind: String, c: Dictionary) -> void:
	var node := MeshInstance3D.new()
	node.name = "Recipe" + kind.capitalize()
	var mesh := PlaneMesh.new()
	var size: Array = c.get("size", [10, 10])
	mesh.size = Vector2(float(size[0]), float(size[1]))
	mesh.subdivide_width = 24 if kind == "water" else 0
	mesh.subdivide_depth = 24 if kind == "water" else 0
	node.mesh = mesh
	node.position = _v(c.get("position", [0, 0, 0]))
	var material := _material(kind)
	if not material:
		node.free()
		return
	material.set_shader_parameter("base_color", _color(c.get("color", [0.08, 0.42, 0.6, 0.8] if kind == "water" else [0.3, 0.36, 0.2, 1])))
	if kind == "water":
		material.set_shader_parameter("flow_speed", float(c.get("speed", 0.4)))
		material.set_shader_parameter("amplitude", float(c.get("amplitude", 0.05)))
		material.set_shader_parameter("surface_size", mesh.size)
		material.set_shader_parameter("roughness", float(c.get("roughness", 0.18)))
		material.set_shader_parameter("shore_width", float(c.get("shore_width", 0.08 * minf(mesh.size.x, mesh.size.y))))
		material.set_shader_parameter("depth_distance", float(c.get("depth_distance", 0.08 * minf(mesh.size.x, mesh.size.y))))
		var shallow := _color(c.get("color", [0.08, 0.42, 0.6, 0.8]))
		material.set_shader_parameter("deep_color", _color(c.get("deep_color", [shallow.r, shallow.g, shallow.b, shallow.a])))
		if not c.has("deep_color"):
			# Legacy water used color inland and a 1.6x brighter edge.
			material.set_shader_parameter("base_color", Color(shallow.r * 1.6, shallow.g * 1.6, shallow.b * 1.6, shallow.a))
		if c.has("shore_mask"):
			material.set_shader_parameter("shore_mask", _texture(c.shore_mask))
			material.set_shader_parameter("use_shore_mask", true)
		if c.has("normal_texture"):
			material.set_shader_parameter("normal_texture", _texture(c.normal_texture))
			material.set_shader_parameter("use_normal_texture", true)
	else:
		material.set_shader_parameter("secondary_color", _color(c.get("secondary_color", [0.5, 0.45, 0.28, 1])))
		material.set_shader_parameter("tile_scale", float(c.get("tile_scale", 2.0)))
		for field in ["texture", "secondary_texture", "blend_mask"]:
			if c.has(field):
				material.set_shader_parameter("albedo_texture" if field == "texture" else field, _texture(c[field]))
				material.set_shader_parameter("use_" + field, true)
	node.material_override = material
	add_child(node)

func _grass(c: Dictionary) -> void:
	var rng := RandomNumberGenerator.new()
	rng.seed = int(c.get("seed", 1))
	var bounds: Array = c.get("bounds", [-5, -5, 5, 5])
	var groups: Dictionary = {}
	var count: int = int(c.get("count", 400))
	var chunk_size := float(c.get("chunk_size", 8.0))
	var ground_y := float(c.get("ground_y", c.get("y", 0.0)))
	var base_height := float(c.get("height", 0.45))
	# Existing cards were 0.35 * height wide; explicit width uses world units.
	var base_width := float(c.get("width", base_height * 0.35))
	var mask: Image
	if c.has("density_mask"):
		var texture := _texture(c.density_mask)
		if not texture:
			return
		mask = texture.get_image()
		if mask == null or mask.is_empty():
			errors.append("Grass density mask has no readable image")
			return
		if mask.is_compressed() and mask.decompress() != OK:
			errors.append("Grass density mask cannot be decompressed")
			return
	var accepted := 0
	for attempt in range(maxi(1, count * 30)):
		if accepted >= count:
			break
		var x := rng.randf_range(float(bounds[0]), float(bounds[2]))
		var z := rng.randf_range(float(bounds[1]), float(bounds[3]))
		var excluded := false
		for rect in c.get("exclude_rects", []):
			if x >= rect[0] and z >= rect[1] and x <= rect[2] and z <= rect[3]:
				excluded = true
		if excluded:
			continue
		if mask:
			var u := (x - float(bounds[0])) / (float(bounds[2]) - float(bounds[0]))
			var v := (z - float(bounds[1])) / (float(bounds[3]) - float(bounds[1]))
			var value := mask.get_pixel(clampi(int(u * mask.get_width()), 0, mask.get_width() - 1), clampi(int(v * mask.get_height()), 0, mask.get_height() - 1)).r
			if value <= float(c.get("mask_threshold", 0.0)) or rng.randf() >= value:
				continue
		var key := Vector2i(floori(x / chunk_size), floori(z / chunk_size))
		if not groups.has(key):
			groups[key] = []
		var variation := rng.randf_range(0.7, 1.3)
		var height := base_height * variation
		var center := Vector3((float(key.x) + 0.5) * chunk_size, ground_y, (float(key.y) + 0.5) * chunk_size)
		var basis := Basis(Vector3.UP, rng.randf_range(0, TAU)) * Basis.from_scale(Vector3(base_width * variation, height, 1.0))
		var transform := Transform3D(basis, Vector3(x, ground_y + height * 0.5, z) - center)
		groups[key].append(transform)
		accepted += 1
	grass_report = {"requested": count, "accepted": accepted, "seed": int(c.get("seed", 1)), "chunks": groups.size(), "chunk_size": chunk_size, "masked": mask != null}
	for key in groups:
		var multi := MultiMesh.new()
		multi.transform_format = MultiMesh.TRANSFORM_3D
		var blade := QuadMesh.new()
		blade.size = Vector2.ONE
		multi.mesh = blade
		multi.instance_count = groups[key].size()
		for index in range(groups[key].size()):
			multi.set_instance_transform(index, groups[key][index])
		var node := MultiMeshInstance3D.new()
		node.name = "GrassChunk_" + str(key.x) + "_" + str(key.y)
		node.position = Vector3((float(key.x) + 0.5) * chunk_size, ground_y, (float(key.y) + 0.5) * chunk_size)
		node.multimesh = multi
		node.visibility_range_end = float(c.get("cull_distance", 60.0))
		# Include shader wind in culling bounds without changing gameplay collision.
		node.extra_cull_margin = maxf(float(c.get("wind", 0.12)), 0.01)
		var material := _material("grass")
		if not material:
			node.free()
			return
		material.set_shader_parameter("base_color", _color(c.get("color", [0.22, 0.5, 0.13, 1])))
		material.set_shader_parameter("wind", float(c.get("wind", 0.12)))
		node.material_override = material
		add_child(node)
