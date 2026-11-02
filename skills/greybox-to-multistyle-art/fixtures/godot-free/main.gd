extends Node3D
## Public-domain tiny playable case: two connected spaces, owned decor and one shared landmark.
var interactions := 0
var zone := 0
var camera: Camera3D
var target: StaticBody3D
var player: Node3D

func _ready() -> void:
	_register_action("interact", KEY_SPACE)
	_register_action("transition", KEY_T)
	_register_action("move_left", KEY_A)
	_register_action("move_right", KEY_D)
	var light := DirectionalLight3D.new()
	light.name = "Sun"
	light.rotation_degrees = Vector3(-55, -30, 0)
	light.light_energy = 1.0
	light.shadow_enabled = true
	add_child(light)
	var world := WorldEnvironment.new()
	world.environment = Environment.new()
	world.environment.background_mode = Environment.BG_COLOR
	world.environment.background_color = Color("#18253b")
	world.environment.ambient_light_source = Environment.AMBIENT_SOURCE_COLOR
	world.environment.ambient_light_color = Color.WHITE
	world.environment.ambient_light_energy = 0.45
	add_child(world)
	for position_x in [0, 8]:
		var floor := _solid("Floor" + str(position_x), Vector3(7, 0.35, 7), Vector3(position_x, -0.2, 0), Color("#78818b"))
		add_child(floor)
	add_child(_solid("Bridge", Vector3(2, 0.35, 2), Vector3(4, -0.2, 0), Color("#68717b")))
	target = _solid("Target", Vector3(1.5, 1.5, 1.5), Vector3(-1.5, 0.75, 0), Color("#b2b2b2"))
	add_child(target)
	var anchor := Node3D.new()
	anchor.name = "DecorAnchor"
	anchor.position = Vector3(0, 1.0, 0)
	target.add_child(anchor)
	var landmark := Node3D.new()
	landmark.name = "SharedLandmark"
	landmark.position = Vector3(4, 0, -2.2)
	add_child(landmark)
	landmark.add_child(_mesh("Grey", Vector3(0.8, 4, 0.8), Vector3(0, 2, 0), Color("#aaaaaa")))
	# Off-centre pivot and nested nonuniform parent transform are intentional calibration inputs.
	var probe := Node3D.new()
	probe.name = "PivotProbe"
	probe.position = Vector3(1.5, 0.05, 2.0)
	add_child(probe)
	player = _mesh("Player", Vector3(0.6, 0.9, 0.6), Vector3(0, 0.5, 1.5), Color("#ffffff"))
	add_child(player)
	for index in range(3):
		add_child(_mesh("Color" + str(index), Vector3(0.5, 0.5, 0.5), Vector3(-2.3 + index * 0.65, 0.25, 2.5), [Color.RED, Color.GREEN, Color.BLUE][index]))
	add_child(_mesh("OneMetre", Vector3(1, 0.08, 0.08), Vector3(0.5, 0.08, 3), Color.WHITE))
	camera = Camera3D.new()
	camera.name = "Camera3D"
	camera.position = Vector3(10, 11, 15)
	add_child(camera)
	camera.look_at(Vector3(2, 0, 0))
	camera.current = true
	var canvas := CanvasLayer.new()
	var label := Label.new()
	label.text = "FREE GREYBOX FIXTURE  |  A / D move    SPACE collect    T next space\nSame collision / interaction / camera; two art styles, one shared landmark"
	label.position = Vector2(18, 14)
	label.add_theme_font_size_override("font_size", 17)
	canvas.add_child(label)
	add_child(canvas)

func _register_action(action: String, key: Key) -> void:
	if not InputMap.has_action(action):
		InputMap.add_action(action)
	var event := InputEventKey.new()
	event.physical_keycode = key
	InputMap.action_add_event(action, event)

func _physics_process(delta: float) -> void:
	if Input.is_action_just_pressed("interact"):
		collect()
	if Input.is_action_just_pressed("transition"):
		transition()
	player.position.x += (Input.get_action_strength("move_right") - Input.get_action_strength("move_left")) * delta * 3.0

func collect() -> void:
	if target.visible:
		interactions += 1
		target.visible = false
		target.get_node("Collision").set_deferred("disabled", true)

func transition() -> void:
	zone = 1 - zone
	player.position.x = float(zone) * 8.0
	camera.position.x = 10.0 + zone * 5.0
	camera.look_at(Vector3(2 + zone * 5, 0, 0))

func greybox_validation(action: String = "state") -> Dictionary:
	if action == "collect":
		collect()
	elif action == "transition":
		transition()
	var decor := target.get_node_or_null("DecorAnchor/Art_target_cap")
	var pivot := get_node_or_null("PivotProbe/Art_pivot_probe")
	var landmark := get_node("SharedLandmark") as Node3D
	var pivot_ground := false
	var source_material := false
	if pivot:
		var layer := get_node_or_null("_GreyboxArtLayer")
		var bounds: AABB = layer._bounds(pivot, Transform3D.IDENTITY)
		pivot_ground = absf(bounds.position.y) < 0.001
		var mesh := pivot.find_child("OffsetMesh", true, false) as MeshInstance3D
		source_material = mesh.material_override == null and mesh.mesh.surface_get_material(0).albedo_color.is_equal_approx(Color(0.7, 0.35, 0.2, 1))
	return {"interactions": interactions, "zone": zone, "target_visible": target.is_visible_in_tree(),
		"decor_visible": decor.is_visible_in_tree() if decor else null,
		"decor_owned_by_target": decor != null and target.is_ancestor_of(decor),
		"collision_count": find_children("*", "CollisionShape3D", true, false).size(),
		"target_collision_disabled": target.get_node("Collision").disabled,
		"root_identity_preserved": get_tree().current_scene == self and get_path() == NodePath("/root/Fixture"),
		"landmark_in_front": not camera.is_position_behind(landmark.global_position + Vector3.UP * 2),
		"pivot_at_ground": pivot_ground, "source_material_preserved": source_material}

func _mesh(node_name: String, dimensions: Vector3, at: Vector3, color: Color) -> MeshInstance3D:
	var result := MeshInstance3D.new()
	result.name = node_name
	var shape := BoxMesh.new()
	shape.size = dimensions
	result.mesh = shape
	result.position = at
	var material := StandardMaterial3D.new()
	material.albedo_color = color
	material.roughness = 0.85
	result.material_override = material
	return result

func _solid(node_name: String, dimensions: Vector3, at: Vector3, color: Color) -> StaticBody3D:
	var body := StaticBody3D.new()
	body.name = node_name
	body.position = at
	body.add_child(_mesh("Grey", dimensions, Vector3.ZERO, color))
	var collision := CollisionShape3D.new()
	collision.name = "Collision"
	var shape := BoxShape3D.new()
	shape.size = dimensions
	collision.shape = shape
	body.add_child(collision)
	return body
