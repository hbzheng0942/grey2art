extends SceneTree
const ENTRY="res://art/museum-dog/styles/A01/runtime/revisions/7016ffcf59c4e2f2/play.tscn"
const ACTIONS=["dog_forward","dog_back","dog_left","dog_right","dog_bark"]
var stage
var game
var output:String=""
var tick:int=0
var samples:Array=[]
var initial:Vector3
func _initialize()->void:
	output=OS.get_cmdline_user_args()[0]
	call_deferred("run")
func run()->void:
	root.size=Vector2i(960,540)
	DisplayServer.window_set_size(Vector2i(960,540))
	stage=load(ENTRY).instantiate()
	root.add_child(stage)
	current_scene=stage
	await stage.assembled
	game=stage.game
	if not stage.report.failed.is_empty() or not stage.report.missing_generated_models.is_empty():
		push_error("Incomplete canonical art scene");quit(2);return
	game.dog.global_position=Vector3(0,.15,2.6)
	game.dog.rotation.y=0
	game.yaw=0
	game.cam_follow=false
	game.shot="homepage_hall"
	game.shot_pos=Vector3(6.2,3.6,6.9)
	game.shot_look=Vector3(-.4,1.6,-2.2)
	game.shot_fov=70
	game._update_camera(1.0,true)
	for layer in game.find_children("*","CanvasLayer",true,false):layer.hide()
	if stage.status_label!=null:stage.status_label.hide()
	initial=game.dog.global_position
	for i in range(24):await process_frame
	for frame in range(192):
		var t:float=float(frame)/24.0
		for action in ACTIONS:Input.action_release(action)
		if t>=.5 and t<2.05:Input.action_press("dog_left")
		elif t>=2.05 and t<4.65:Input.action_press("dog_right")
		elif t>=4.65 and t<6.2:Input.action_press("dog_left")
		elif t>=6.2 and t<7.4:Input.action_press("dog_forward")
		if frame==150:Input.action_press("dog_bark")
		await process_frame
		if frame%3==0:
			await RenderingServer.frame_post_draw
			var image:Image=root.get_texture().get_image()
			var path:String=output+"/frames/%03d.jpg"%(frame/3)
			if image.save_jpg(path,.94)!=OK:push_error("Frame save failed");quit(2);return
			samples.append({"frame":frame/3,"simulation_seconds":t,"dog_position":[game.dog.global_position.x,game.dog.global_position.y,game.dog.global_position.z],"sha256":FileAccess.get_sha256(path)})
	for action in ACTIONS:Input.action_release(action)
	var record={"kind":"native_gameplay_with_fixed_overview_camera","entry":ENTRY,"engine":Engine.get_version_info().string,"renderer":RenderingServer.get_current_rendering_method(),"frames":samples,"simulation_fps":24,"capture_fps":8,"duration_seconds":8,"capture_resolution":[960,540],"hud_hidden":true,"camera_override":"fixed hall overview; no camera animation","input_method":"original dog_* Input actions; no teleport after initial spawn","initial_position":[initial.x,initial.y,initial.z],"final_position":[game.dog.global_position.x,game.dog.global_position.y,game.dog.global_position.z],"scene_assembly_failures":stage.report.failed,"missing_sources":stage.report.missing_generated_models,"publication_sha256":FileAccess.get_sha256(ENTRY.get_base_dir()+"/publication.json"),"registry_sha256":FileAccess.get_sha256(stage.registry_path),"not_real_time_fps_measurement":true}
	FileAccess.open(output+"/native-capture.json",FileAccess.WRITE).store_string(JSON.stringify(record,"  ")+"\n")
	print("MUSEUM_HALL_CAPTURE "+str(samples.size()))
	quit()
