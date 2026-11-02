extends SceneTree
## Runs the declared gameplay hooks, records state, and captures actual native pixels.
var output: String
var errors: Array = []
var captures: Array = []
var states: Array = []
var passed_check_ids: Array = []

func _initialize() -> void:
	call_deferred("_run")

func _arg(key: String) -> String:
	var args := OS.get_cmdline_user_args()
	var index := args.find(key)
	return args[index + 1] if index >= 0 and index + 1 < args.size() else ""

func _run() -> void:
	output = _arg("--output")
	var packed = load(_arg("--scene"))
	if not packed is PackedScene:
		push_error("Cannot load declared playable scene")
		quit(2)
		return
	var game: Node = packed.instantiate()
	root.add_child(game)
	current_scene = game
	root.size = Vector2i(960, 540)
	var layer = game.get_node_or_null("_GreyboxArtLayer")
	for frame in range(240):
		await process_frame
		if layer and layer.assembled:
			break
	if not layer or not layer.assembled:
		errors.append("Art layer did not finish assembly")
		_finish({}, 0)
		return
	errors.append_array(layer.assembly_errors)
	var contract: Dictionary = layer.manifest.get("contract", {})
	var declared_camera = game.get_node_or_null(NodePath(contract.get("camera", "")))
	if not declared_camera is Camera3D:
		errors.append("Declare a valid Camera3D node path in contract.camera")
	elif not declared_camera.is_current():
		errors.append("Declared gameplay camera is not current; validation does not replace it")
	await _capture("00_initial")
	var assertions := 0
	var steps: Array = contract.get("validation", {}).get("steps", [])
	for index in range(steps.size()):
		var step: Dictionary = steps[index]
		var actual: Dictionary = {}
		var errors_before := errors.size()
		if step.has("input_action"):
			var action := str(step.input_action)
			if not InputMap.has_action(action):
				errors.append("Missing declared input action: " + action)
			else:
				if step.get("input_mode", "action_state") == "input_event":
					var press := InputEventAction.new()
					press.action = action
					press.pressed = true
					Input.parse_input_event(press)
				else:
					Input.action_press(action)
				for frame in range(int(step.get("frames", 2))):
					await physics_frame
				if step.get("input_mode", "action_state") == "input_event":
					var release := InputEventAction.new()
					release.action = action
					release.pressed = false
					Input.parse_input_event(release)
				else:
					Input.action_release(action)
		if step.has("hook"):
			var hook: Dictionary = step.hook
			var owner = game.get_node_or_null(NodePath(hook.get("node", ".")))
			if owner and owner.has_method(hook.get("method", "")):
				var result = owner.callv(hook.method, hook.get("args", []))
				if result is Dictionary:
					actual = result
				else:
					errors.append("Validation hook must return state Dictionary")
			else:
				errors.append("Missing declared validation hook: " + str(hook))
		for key in step.get("expect", {}):
			assertions += 1
			if actual.get(key) != step.expect[key]:
				errors.append("State mismatch " + str(step.get("name", index)) + "." + str(key) + ": " + str(actual.get(key)))
		if errors.size() == errors_before and not step.get("expect", {}).is_empty():
			passed_check_ids.append(str(step.get("id", step.get("name", index))))
		states.append({"step": step, "actual": actual, "physics_frame": Engine.get_physics_frames()})
		await _capture("%02d_%s" % [index + 1, str(step.get("name", "step")).validate_filename()])
	_finish({"root_name": game.name, "root_path": str(game.get_path()),
		"current_scene_is_gameplay_root": current_scene == game,
		"bindings": layer.assembly_receipts, "renderer": RenderingServer.get_current_rendering_method()}, assertions)

func _capture(label: String) -> void:
	for frame in range(8):
		await process_frame
	await RenderingServer.frame_post_draw
	var pixels := root.get_texture().get_image()
	var filename := output.path_join(label + ".png")
	var error := pixels.save_png(filename)
	if error != OK:
		errors.append("Native screenshot failed: " + filename)
	else:
		captures.append(filename)

func _finish(native: Dictionary, assertions: int) -> void:
	var report := {"passed": errors.is_empty(), "errors": errors, "native": native,
		"attempt_id": _arg("--attempt-id"), "binding_digest": _arg("--binding-digest"), "scene": _arg("--scene"),
		"passed_check_ids": passed_check_ids,
		"states": states, "captures": captures, "assertions": assertions,
		"gameplay_verified": assertions > 0 and errors.is_empty(),
		"art_acceptance": "human-review-pending", "engine": Engine.get_version_info()}
	var file := FileAccess.open(output.path_join("native-report.json"), FileAccess.WRITE)
	file.store_string(JSON.stringify(report, "\t"))
	file.close()
	quit(0 if errors.is_empty() else 1)
