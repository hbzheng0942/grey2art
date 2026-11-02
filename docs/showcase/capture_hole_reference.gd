extends SceneTree
## Replays the recorded ceramic/orbital zone-b reference camera in a disposable overlay.

func _initialize() -> void:
	call_deferred("_capture")

func _capture() -> void:
	var args := OS.get_cmdline_user_args()
	if args.is_empty():
		push_error("Expected output PNG path")
		quit(2)
		return
	get_root().size = Vector2i(1536, 1024)
	get_root().content_scale_size = Vector2i(1536, 1024)
	var result := change_scene_to_file(str(ProjectSettings.get_setting("application/run/main_scene")))
	if result != OK:
		push_error("Main scene load failed")
		quit(3)
		return
	for i in range(12):
		await process_frame
	var game := current_scene
	if game.get("startup_failed") == true or game.get("camera") == null:
		push_error("Game failed to initialize")
		quit(4)
		return
	game.set("paused", true)
	game.set("overview", false)
	game.set_process(false)
	game.set_physics_process(false)
	for key in ["hud", "ground_labels", "proxy_root"]:
		var node = game.get(key)
		if node != null:
			node.hide()
	if game.get("sound") != null:
		game.get("sound").configure(false, 0.0)
	var camera: Camera3D = game.get("camera")
	camera.projection = Camera3D.PROJECTION_ORTHOGONAL
	camera.keep_aspect = Camera3D.KEEP_HEIGHT
	camera.size = 19.0
	camera.position = Vector3(-12, 16, 6)
	camera.look_at(Vector3(-12, 0, -8), Vector3.UP)
	camera.current = true
	for i in range(4):
		await process_frame
		await RenderingServer.frame_post_draw
	var image := get_root().get_texture().get_image()
	var saved := image.save_png(args[0])
	print("GREY2ART_REFERENCE_CAMERA " + JSON.stringify({
		"projection": "orthographic", "keep_aspect": "keep_height",
		"target": [-12, 0, -8], "position": [camera.position.x, camera.position.y, camera.position.z],
		"rotation_radians": [camera.rotation.x, camera.rotation.y, camera.rotation.z],
		"size": camera.size, "resolution": [image.get_width(), image.get_height()],
		"renderer": RenderingServer.get_current_rendering_method(),
		"engine": Engine.get_version_info().string,
		"capture_kind": "native still; paused simulation; only debug/UI hidden",
		"save_error": saved, "user_data_dir": OS.get_user_data_dir()
	}))
	quit(0 if saved == OK else 5)
