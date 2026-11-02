extends SceneTree

var plan: Dictionary
var frame := 0
var captured := 0
var output := ""
var source_scene := ""

func _initialize() -> void:
	var plan_path := ""
	for arg in OS.get_cmdline_user_args():
		if arg.begins_with("--plan="): plan_path = arg.trim_prefix("--plan=")
	plan = JSON.parse_string(FileAccess.get_file_as_string(plan_path))
	output = str(plan.output)
	DirAccess.make_dir_recursive_absolute(output)
	ProjectSettings.set_setting("application/config/use_custom_user_dir", true)
	ProjectSettings.set_setting("application/config/custom_user_dir_name", "Grey2Art-Gallery-Capture-20261030")
	call_deferred("boot")

func boot() -> void:
	root.mode = Window.MODE_WINDOWED
	root.unresizable = true
	root.size = Vector2i(960, 540)
	root.content_scale_size = Vector2i(1280, 720)
	root.content_scale_mode = Window.CONTENT_SCALE_MODE_CANVAS_ITEMS
	root.content_scale_aspect = Window.CONTENT_SCALE_ASPECT_IGNORE
	source_scene = str(ProjectSettings.get_setting("application/run/main_scene"))
	var packed := load(source_scene) as PackedScene
	var scene := packed.instantiate()
	root.add_child(scene)
	current_scene = scene

func _process(_delta: float) -> bool:
	frame += 1
	if root.mode != Window.MODE_WINDOWED: root.mode = Window.MODE_WINDOWED
	if root.size != Vector2i(960, 540): root.size = Vector2i(960, 540)
	for action in plan.events:
		if int(action.frame) != frame: continue
		if action.type == "key":
			var event := InputEventKey.new()
			event.keycode = OS.find_keycode_from_string(str(action.key))
			event.physical_keycode = event.keycode
			event.pressed = bool(action.pressed)
			Input.parse_input_event(event)
		elif action.type == "look":
			var motion := InputEventMouseMotion.new()
			motion.relative = Vector2(float(action.x), float(action.y))
			motion.screen_relative = motion.relative
			Input.parse_input_event(motion)
	var start := int(plan.capture_start)
	if frame >= start and frame < start + int(plan.capture_frames):
		capture(frame - start)
	if frame >= start + int(plan.capture_frames) + 2:
		var receipt := FileAccess.open(output.path_join("native.json"), FileAccess.WRITE)
		receipt.store_string(JSON.stringify({"captured_frames": captured, "main_scene": source_scene,
			"engine": Engine.get_version_info(), "rendering_method": RenderingServer.get_current_rendering_method(),
			"viewport_size": [root.size.x, root.size.y], "user_data_dir": OS.get_user_data_dir()}, "\t"))
		quit()
	return false

func capture(index: int) -> void:
	RenderingServer.force_draw(false)
	var picture := root.get_texture().get_image()
	var result := picture.save_png(output.path_join("%04d.png" % index))
	if result != OK:
		push_error("Cannot write native frame")
		quit(1)
	captured += 1
