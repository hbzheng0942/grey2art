extends SceneTree
const ACTIONS=["forward","back","left","right","run"]
var game
var output:String
var samples:Array=[]
func _initialize()->void:
	output=OS.get_cmdline_user_args()[0]
	call_deferred("run")
func run()->void:
	root.content_scale_mode=Window.CONTENT_SCALE_MODE_DISABLED
	root.content_scale_size=Vector2i(960,540)
	root.size=Vector2i(960,540)
	DisplayServer.window_set_size(Vector2i(960,540))
	game=load("res://play_meadow.tscn").instantiate()
	root.add_child(game)
	current_scene=game
	for frame in range(600):
		await process_frame
		if game.art_initialized:break
	if not game.art_initialized:push_error("Garden did not initialize");quit(2);return
	game.begin()
	game.hud.hide()
	game.player.position=Vector3(-3,.1,15)
	game.player.velocity=Vector3.ZERO
	game.player.pivot.rotation.y=0
	game.player.arm.spring_length=8
	game.player.orbit_pitch=-.28
	game.player.arm.rotation.x=-.28
	game.player.camera.fov=52
	for frame in range(24):await process_frame
	for frame in range(192):
		for action in ACTIONS:Input.action_release(action)
		var t:float=float(frame)/24.0
		if t>=.25 and t<5.0:Input.action_press("forward")
		elif t>=5.0 and t<7.4:Input.action_press("right")
		await process_frame
		if frame%3==0:
			await RenderingServer.frame_post_draw
			var path:String=output+"/frames/%03d.jpg"%(frame/3)
			if root.get_texture().get_image().save_jpg(path,.94)!=OK:push_error("Frame save failed");quit(2);return
			samples.append({"frame":frame/3,"simulation_seconds":t,"player_position":[game.player.global_position.x,game.player.global_position.y,game.player.global_position.z],"sha256":FileAccess.get_sha256(path)})
	for action in ACTIONS:Input.action_release(action)
	var record={"kind":"native_garden_ink_gameplay","source_entry":"res://play_meadow.tscn","engine":Engine.get_version_info().string,"renderer":RenderingServer.get_current_rendering_method(),"capture_fps":8,"simulation_fps":24,"duration_seconds":8,"capture_resolution":[960,540],"hud_hidden":true,"camera":"native follow orbit; yaw0 pitch-.28 spring8 fov52","input_method":"original forward/right actions; only initial spawn staged","frames":samples,"not_real_time_fps_measurement":true}
	FileAccess.open(output+"/native-capture.json",FileAccess.WRITE).store_string(JSON.stringify(record,"  ")+"\n")
	print("GARDEN_INK_CAPTURE "+str(samples.size()))
	game.queue_free()
	for frame in range(3):await process_frame
	load("res://art/runtime/model_visuals.gd").cache.clear()
	load("res://art/runtime/ink_style.gd").materials.clear()
	load("res://art/runtime/ink_style.gd").meshes.clear()
	quit()
