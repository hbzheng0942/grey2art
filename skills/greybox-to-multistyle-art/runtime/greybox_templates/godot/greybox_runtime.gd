extends Node3D
## Editable prototype controller. Probes use the same Input actions as human play.

var plan: Dictionary
var player: CharacterBody3D
var camera: Camera3D
var collected: Array[String] = []
var interacted: Array[String] = []
var state := "playing"
var goal_denied := 0
var restart_count := 0
var paused := false
var yaw := 0.0
var pitch := -0.12
var start_position := Vector3.ZERO
var distance_travelled := 0.0
var probe: Dictionary = {}
var probe_step := 0
var step_frame := 0
var tick := 0
var checks: Array = []
var frames: Array = []
var history: Array = []
var label: Label
var initial_entities: Dictionary = {}
var binding_errors: Array[String] = []
var entity_visuals: Dictionary = {}
var entity_triggers: Dictionary = {}
var action_names := ["move_left", "move_right", "move_forward", "move_back", "interact", "restart", "pause"]

func _ready() -> void:
	plan = JSON.parse_string(FileAccess.get_file_as_string(get_meta("plan_path")))
	player = $Player
	camera = $Player/Camera3D
	start_position = player.position
	_install_input()
	initial_entities = _read_native_entities()
	for entity in $World.get_children():
		for trigger in entity_triggers.get(entity.get_instance_id(), []):
			trigger.body_entered.connect(_entered.bind(entity))
	var canvas := CanvasLayer.new()
	add_child(canvas)
	label = Label.new()
	label.position = Vector2(18, 16)
	label.add_theme_color_override("font_color", Color.WHITE)
	canvas.add_child(label)
	for arg in OS.get_cmdline_user_args():
		if arg.begins_with("--greybox-probe="):
			probe = JSON.parse_string(FileAccess.get_file_as_string(arg.trim_prefix("--greybox-probe=")))
	if plan.player.view == "first_person" and probe.is_empty():
		Input.mouse_mode = Input.MOUSE_MODE_CAPTURED
	_update_camera()

func _binding_path(node: Node) -> String:
	return str(node.get_path()).trim_prefix("/root/")

func _xyz(vector: Vector3) -> Array:
	return [vector.x, vector.y, vector.z]

func _read_native_entities() -> Dictionary:
	var result: Dictionary = {}
	for entity in $World.get_children():
		var stable_id: String = str(entity.get_meta("stable_id", ""))
		var role: String = str(entity.get_meta("role", ""))
		if stable_id.is_empty() or role.strip_edges().is_empty() or result.has(stable_id):
			binding_errors.append("Missing/duplicate stable ID or missing role: " + _binding_path(entity))
			continue
		var visuals: Array = entity.find_children("*", "MeshInstance3D", true, false)
		if visuals.is_empty():
			binding_errors.append("No actual mesh visual for " + stable_id)
			continue
		entity_visuals[entity.get_instance_id()] = visuals
		var visual_paths: Array = []
		var bounds: AABB = visuals[0].global_transform * visuals[0].get_aabb()
		for visual in visuals:
			if visual.mesh == null:
				binding_errors.append("Visual has no actual mesh: " + _binding_path(visual))
			visual_paths.append(_binding_path(visual))
			bounds = bounds.merge(visual.global_transform * visual.get_aabb())
		var collisions: Array = []
		var collision_paths: Array = []
		for collision in entity.find_children("*", "CollisionShape3D", true, false):
			collision_paths.append(_binding_path(collision))
			collisions.append({"node_path": _binding_path(collision), "owner_path": _binding_path(collision.get_parent()), "kind": collision.get_parent().get_class(), "disabled": collision.disabled})
		entity_triggers[entity.get_instance_id()] = entity.find_children("*", "Area3D", true, false)
		var markers: Array = entity.find_children("*", "Marker3D", true, false)
		var anchors: Array = markers.filter(func(marker): return marker.get_meta("greybox_interaction_anchor", false))
		if anchors.is_empty():
			anchors = markers.filter(func(marker): return marker.name == "InteractionAnchor")
		if anchors.is_empty() and markers.size() == 1:
			anchors = markers
		if anchors.size() != 1:
			binding_errors.append("Expected one actual interaction anchor for " + stable_id)
			continue
		var anchor: Marker3D = anchors[0]
		var anchor_local: Vector3 = entity.to_local(anchor.global_position)
		result[stable_id] = {"id": stable_id, "role": role, "behavior": entity.get_meta("behavior", "none"), "node_path": _binding_path(entity), "logic_node": _binding_path(entity), "visual_path": visual_paths[0], "visual_nodes": visual_paths, "collision_nodes": collision_paths, "collisions": collisions, "interaction_anchor": {"node_path": _binding_path(anchor), "local": _xyz(anchor_local), "world": _xyz(anchor.global_position)}, "transform": {"position": _xyz(entity.global_position), "rotation_radians": _xyz(entity.global_rotation), "scale": _xyz(entity.global_transform.basis.get_scale())}, "bounds": {"center": _xyz(bounds.get_center()), "size": _xyz(bounds.size)}, "replaceable_visual": true, "binding_source": "native_scene_initial_state"}
	return result

func _install_input() -> void:
	var keys := {"move_left": [KEY_A, KEY_LEFT], "move_right": [KEY_D, KEY_RIGHT], "move_forward": [KEY_W, KEY_UP], "move_back": [KEY_S, KEY_DOWN], "interact": [KEY_E], "restart": [KEY_R], "pause": [KEY_ESCAPE]}
	for action in action_names:
		var name: String = "greybox_" + action
		if not InputMap.has_action(name):
			InputMap.add_action(name)
		for key in keys[action]:
			var event := InputEventKey.new()
			event.physical_keycode = key
			InputMap.action_add_event(name, event)

func _unhandled_input(event: InputEvent) -> void:
	if event is InputEventMouseMotion and plan.player.view == "first_person" and not paused:
		yaw -= event.relative.x * 0.003
		pitch = clampf(pitch - event.relative.y * 0.003, -1.35, 1.35)
		_update_camera()

func _physics_process(delta: float) -> void:
	if not probe.is_empty() and step_frame == 0:
		_set_probe_actions(probe.steps[probe_step].get("actions", {}))
	if Input.is_action_just_pressed("greybox_restart"):
		_restart()
	if Input.is_action_just_pressed("greybox_pause"):
		paused = not paused
		Input.mouse_mode = Input.MOUSE_MODE_VISIBLE if paused else (Input.MOUSE_MODE_CAPTURED if plan.player.view == "first_person" and probe.is_empty() else Input.MOUSE_MODE_VISIBLE)
	var previous := player.position
	if not paused and state == "playing":
		var horizontal := Input.get_action_strength("greybox_move_right") - Input.get_action_strength("greybox_move_left")
		var forward := Input.get_action_strength("greybox_move_forward") - Input.get_action_strength("greybox_move_back")
		var direction := Vector3(horizontal, 0, -forward)
		if plan.player.view == "first_person":
			direction = direction.rotated(Vector3.UP, yaw)
		else:
			var screen_right := camera.global_transform.basis.x
			screen_right.y = 0.0
			var screen_forward := -camera.global_transform.basis.z
			screen_forward.y = 0.0
			if screen_forward.length_squared() < 0.00001:
				screen_forward = camera.global_transform.basis.y
				screen_forward.y = 0.0
			direction = screen_right.normalized() * horizontal + screen_forward.normalized() * forward
		if direction.length() > 1.0:
			direction = direction.normalized()
		player.velocity.x = direction.x * float(plan.player.speed)
		player.velocity.z = direction.z * float(plan.player.speed)
		player.velocity.y -= 20.0 * delta
		player.move_and_slide()
		distance_travelled += Vector2(player.position.x - previous.x, player.position.z - previous.z).length()
		if player.position.y < -20.0:
			state = "failed"
		if Input.is_action_just_pressed("greybox_interact"):
			_interact()
	_update_camera()
	label.text = "WASD / arrows: move   E: interact   R: restart   Esc: pause\n%s | collected %d / %d" % [state, collected.size(), plan.get("objective", {}).get("required_ids", []).size()]
	if not probe.is_empty():
		tick += 1
		step_frame += 1
		for capture_frame in probe.get("capture_frames", []):
			if tick == int(capture_frame):
				_capture(tick)
		if step_frame >= int(probe.steps[probe_step].frames):
			_finish_step()

func _update_camera() -> void:
	if plan.player.view == "first_person":
		camera.position = Vector3(0, float(plan.player.height) * 0.9, 0)
		camera.rotation = Vector3(pitch, yaw, 0)
	else:
		var offset: Array = plan.camera.offset
		camera.position = Vector3(offset[0], offset[1], offset[2])
		camera.look_at(player.global_position + Vector3(0, 0.5, 0), Vector3.FORWARD if absf(float(offset[0])) + absf(float(offset[2])) < 0.001 else Vector3.UP)

func _entered(body: Node3D, entity: Node3D) -> void:
	if body != player or state != "playing" or paused:
		return
	var id: String = entity.get_meta("stable_id")
	match entity.get_meta("behavior"):
		"collectible":
			if not id in collected:
				collected.append(id)
				for visual in entity_visuals.get(entity.get_instance_id(), []):
					visual.visible = false
				for trigger in entity_triggers.get(entity.get_instance_id(), []):
					trigger.set_deferred("monitoring", false)
		"goal":
			var complete := true
			for required in plan.get("objective", {}).get("required_ids", []):
				if not required in collected:
					complete = false
			if complete:
				state = "completed"
			else:
				goal_denied += 1
		"hazard":
			state = "failed"

func _interact() -> void:
	for entity in $World.get_children():
		if entity.get_meta("behavior") != "interactable":
			continue
		var stable_id: String = entity.get_meta("stable_id", "")
		var anchor: Dictionary = initial_entities.get(stable_id, {}).get("interaction_anchor", {})
		if anchor.is_empty():
			continue
		var anchor_node: Node3D = get_node_or_null("/root/" + str(anchor.node_path))
		if anchor_node != null and anchor_node.global_position.distance_to(player.global_position + Vector3.UP) <= 2.5:
			var id: String = entity.get_meta("stable_id")
			if not id in interacted:
				interacted.append(id)
				if entity.has_method("greybox_interact"):
					entity.call("greybox_interact", player)

func _restart() -> void:
	player.position = start_position
	player.velocity = Vector3.ZERO
	collected.clear()
	interacted.clear()
	state = "playing"
	paused = false
	restart_count += 1
	for entity in $World.get_children():
		for visual in entity_visuals.get(entity.get_instance_id(), []):
			visual.visible = true
		for trigger in entity_triggers.get(entity.get_instance_id(), []):
			trigger.set_deferred("monitoring", true)
		if entity.has_method("greybox_restart"):
			entity.call("greybox_restart")

func _telemetry() -> Dictionary:
	return {"state": state, "collected_count": collected.size(), "collected_ids": collected.duplicate(), "interacted_ids": interacted.duplicate(), "objective_complete": state == "completed", "goal_reached": state == "completed", "failed": state == "failed", "goal_denied": goal_denied, "restart_count": restart_count, "restarted": restart_count > 0, "player_position": [player.position.x, player.position.y, player.position.z], "player_moved": distance_travelled > 0.1, "distance_travelled": distance_travelled, "paused": paused, "physics_frames": tick}

func _set_probe_actions(actions: Dictionary) -> void:
	for action in action_names:
		Input.action_release("greybox_" + action)
	for action in actions:
		Input.action_press("greybox_" + action, float(actions[action]))

func _capture(frame: int) -> void:
	await RenderingServer.frame_post_draw
	var path: String = probe.output_dir.path_join("frame-%05d.png" % frame)
	var error := get_viewport().get_texture().get_image().save_png(path)
	if error == OK:
		frames.append(path)

func _finish_step() -> void:
	var snapshot := _telemetry()
	var expected: Dictionary = probe.steps[probe_step].get("expect", {})
	for key in expected:
		var actual = snapshot.get(key)
		var check_name: String = str(probe.steps[probe_step].get("id", "step_%d" % probe_step)) + "." + str(key)
		checks.append({"name": check_name, "step": probe_step, "key": key, "expected": expected[key], "actual": actual, "passed": _matches(actual, expected[key])})
	history.append(snapshot)
	probe_step += 1
	step_frame = 0
	if probe_step >= probe.steps.size():
		_set_probe_actions({})
		set_physics_process(false)
		await get_tree().process_frame
		await RenderingServer.frame_post_draw
		var ok := binding_errors.is_empty()
		for check in checks:
			ok = ok and check.passed
		var report := {"ok": ok, "engine": "godot", "native": true, "checks": checks, "frames": frames, "telemetry": _telemetry(), "history": history, "entities": initial_entities, "binding_errors": binding_errors, "input_path": "action_replay uses Input.action_press -> the same human-device InputMap actions -> camera-relative shared CharacterBody3D controller -> move_and_slide / native Area3D signals"}
		var file := FileAccess.open(probe.report_path, FileAccess.WRITE)
		file.store_string(JSON.stringify(report, "\t"))
		file.close()
		get_tree().quit(0 if ok else 2)

func _matches(actual: Variant, expected: Variant) -> bool:
	if expected is Dictionary:
		if actual is Array:
			for axis in range(3):
				if expected.has("min") and actual[axis] < expected.min[axis]:
					return false
				if expected.has("max") and actual[axis] > expected.max[axis]:
					return false
		else:
			if expected.has("min") and actual < expected.min:
				return false
			if expected.has("max") and actual > expected.max:
				return false
		return true
	return actual == expected
