extends SceneTree
var report: Dictionary = {"checks":[],"captures":[]}
func _initialize() -> void: call_deferred("run")
func freeze_review_materials(game) -> void:
	# _restart/_build_views replace materials; freeze after each view synchronization.
	for node in game.find_children("*","MeshInstance3D",true,false):
		if node.mesh == null:continue
		for surface in node.mesh.get_surface_count():
			var material=node.get_active_material(surface)
			if material is ShaderMaterial and material.shader.code.contains("uniform float review_time"):
				material.set_shader_parameter("review_time",0.0)

func snap(game, name: String, directory: String) -> void:
	game._sync_views()
	freeze_review_materials(game)
	game.ground_labels.visible=false
	for i in range(4): await process_frame
	RenderingServer.force_draw(false)
	var path: String = directory+"/"+name+".png"
	root.get_texture().get_image().save_png(path)
	report["captures"].append(path)

func finish_report(game, directory: String, style: String, passed: bool) -> void:
	var file: FileAccess=FileAccess.open(directory+"/"+style+"-native.json",FileAccess.WRITE)
	file.store_string(JSON.stringify(report,"\t"));file.close()
	print(JSON.stringify(report))
	game.factory.release_templates()
	game.queue_free()
	for i in range(3): await process_frame
	quit(0 if passed else 1)

func run() -> void:
	if DisplayServer.get_name()=="headless": quit(2); return
	var style: String = OS.get_environment("HOLE_ART_STYLE")
	var directory: String = OS.get_environment("HOLE_ART_EVIDENCE")
	var mode: String=OS.get_environment("HOLE_CAPTURE_MODE")
	var controls_path: String=OS.get_environment("HOLE_ART_CONTROLS")
	report["captureMode"]=mode if not mode.is_empty() else "full"
	report["controlsFileSHA256"]=FileAccess.get_sha256(controls_path) if not controls_path.is_empty() else ""
	report["effectiveControls"]=preload("res://scripts/look_controls.gd").read_controls()
	report["contractFileSHA256"]=FileAccess.get_sha256("res://data/art_realization.json")
	report["skinFileSHA256"]=FileAccess.get_sha256("res://data/pilot_skin.json")
	report["runtimeFileHashes"]={}
	for path in ["project.godot","scripts/visual_factory.gd","scripts/material_converter.gd","scripts/art_fit.gd","scripts/art_dressing.gd","scripts/waterfront_stage.gd","scripts/render_profile.gd","scripts/look_controls.gd","shaders/pilot_object.gdshader","shaders/art_floor.gdshader","shaders/art_outside.gdshader","shaders/hole_interior.gdshader","shaders/water.gdshader","tests/capture_pilot.gd"]:
		report["runtimeFileHashes"][path]=FileAccess.get_sha256("res://"+path)
	DirAccess.make_dir_recursive_absolute(directory)
	var game = load("res://scenes/Main.tscn").instantiate()
	# Freeze before _ready/first physics frame so live input cannot perturb the baseline.
	game.paused=true
	game.set_process(false)
	game.set_physics_process(false)
	root.add_child(game)
	await process_frame
	if game.startup_failed: quit(1); return
	game.paused=true
	game.set_process(false)
	game.set_physics_process(false)
	report["temporalProfile"]={"gameplayPaused":true,"physicsDisabledBeforeReady":true,"proceduralShaderTimeSeconds":0.0,"scope":"All original source TIME shaders and art review_time shaders; imported animated/skinned assets remain unsupported"}
	freeze_review_materials(game)
	game.sound.configure(false,0.0)
	var sun: DirectionalLight3D=game.get_node("KeyLight")
	var environment: Environment=game.get_node("WorldEnvironment").environment
	report["effectiveRenderState"]={"sunEnergy":sun.light_energy,"sunAngularDistance":sun.light_angular_distance,"shadowBlur":sun.shadow_blur,"shadowOpacity":sun.shadow_opacity,"ambientEnergy":environment.ambient_light_energy,"exposure":environment.tonemap_exposure,"toneMapper":environment.tonemap_mode,"sunRotationDegrees":[sun.rotation_degrees.x,sun.rotation_degrees.y,sun.rotation_degrees.z]}
	report["capabilityNotes"]=["Directional PCSS is Forward+ only; Mobile uses explicit PCF filter quality and constant shadow blur."]
	game.hud.visible=false
	var loaded_count: int=0
	var bounds_checks: Array=[]
	var art_checks: Array=[]
	var realized: Array=[]
	var realized_by_id: Dictionary={}
	for index in range(game.object_views.size()):
		var view: Node3D=game.object_views[index]
		if view.get_meta("pilot_art",false):
			loaded_count+=1
			var size: Vector3=view.get_meta("fit_size")
			var allowed: Vector3=game.sim.objects[index]["size"]
			var extent: AABB=view.get_meta("fit_aabb",AABB(-size*.5,size))
			if extent.position.x < -allowed.x*.5-.001 or extent.end.x > allowed.x*.5+.001 or extent.position.z < -allowed.z*.5-.001 or extent.end.z > allowed.z*.5+.001: bounds_checks.append(view.name+"_offset")
			var art_max: Array=view.get_meta("art_max",[allowed.x,allowed.y,allowed.z])
			if size.x>art_max[0]+0.003 or size.y>art_max[1]+0.003 or size.z>art_max[2]+0.003: bounds_checks.append(view.name)
			if not view.get_meta("art_contract_failures",[]).is_empty():art_checks.append({"slot":game.sim.objects[index]["id"],"failures":view.get_meta("art_contract_failures")})
			var model_size: Vector3=view.get_meta("model_size",size)
			realized.append({"slot":game.sim.objects[index]["id"],"region":view.get_meta("art_region",""),"variant":view.get_meta("art_variant",""),"modelXYZ":[model_size.x,model_size.y,model_size.z]})
			realized_by_id[game.sim.objects[index]["id"]]=realized.back()
	report.merge({"style":style,"engine":Engine.get_version_info(),"display":DisplayServer.get_name(),"renderer":RenderingServer.get_current_rendering_method(),"renderingDriver":RenderingServer.get_current_rendering_driver_name(),"capturedAtUnix":Time.get_unix_time_from_system(),"loadedGeneratedInstances":loaded_count,"logicalObjects":game.object_views.size(),"initialLocked":game.sim.count_state(game.Simulation.LOCKED),"boundsFailures":bounds_checks,"manualPlayAcceptance":false})
	# Same reproducible concept camera, then the original runtime follow camera.
	report["artContractFailures"]=art_checks
	report["realized"]=realized
	report["artAcceptance"]="pending-visual-review"
	root.size=Vector2i(1536,1024)
	root.content_scale_size=Vector2i(1536,1024)
	root.content_scale_mode=Window.CONTENT_SCALE_MODE_VIEWPORT
	game.show_proxies=false
	game.camera.projection=Camera3D.PROJECTION_ORTHOGONAL
	game.camera.keep_aspect=Camera3D.KEEP_HEIGHT
	game.camera.size=19.0
	game.camera.position=Vector3(-12,16,6)
	game.camera.look_at(Vector3(-12,0,-8),Vector3.UP)
	await snap(game,style+"-zone-b",directory)
	report["viewport"]=[root.get_texture().get_width(),root.get_texture().get_height()]
	report["camera"]={"position":[-12,16,6],"target":[-12,0,-8],"size":19,"keepAspect":"height"}
	for index in game.object_views.size():
		var view: Node3D=game.object_views[index]
		var logical_id: String=game.sim.objects[index]["id"]
		if not realized_by_id.has(logical_id):continue
		var extent: AABB=view.get_meta("fit_aabb")
		var rect: Rect2
		for corner in 8:
			var point=game.camera.unproject_position(view.global_transform*extent.get_endpoint(corner))
			rect=Rect2(point,Vector2.ZERO) if corner==0 else rect.expand(point)
		realized_by_id[logical_id]["screenBox"]=[rect.position.x/1536.,rect.position.y/1024.,rect.size.x/1536.,rect.size.y/1024.]
	game.sim.teleport(Vector3(-12,0,-8))
	game.camera_target=Vector3(-12,0,-9.5)
	game.overview=false
	game._sync_camera(0.0,true)
	await snap(game,style+"-runtime-b",directory)
	if mode=="look":
		await finish_report(game,directory,style,game.object_views.size()==215 and loaded_count==215 and bounds_checks.is_empty() and art_checks.is_empty())
		return
	game.overview=true;game._sync_camera(0.0,true)
	await snap(game,style+"-overview",directory)
	game.overview=false
	game._enter_lab(2)
	game.show_proxies=false
	game.paused=true
	game._sync_camera(0.0,true)
	await snap(game,style+"-market-before",directory)
	# Inspect generated support contacts and the generated landmark at a readable scale.
	game.camera.projection=Camera3D.PROJECTION_ORTHOGONAL
	game.camera.size=4.8
	var first_table: Vector3
	var landmark: Vector3
	for o in game.sim.objects:
		if o["id"]=="support_table_001": first_table=o["position"]
		if o["id"]=="landmark_002": landmark=o["position"]
	game.camera.position=first_table+Vector3(3,3.5,5)
	game.camera.look_at(first_table+Vector3(0,.2,0),Vector3.UP)
	await snap(game,style+"-contact-detail",directory)
	game.camera.size=8.0
	game.camera.position=landmark+Vector3(6,6,8)
	game.camera.look_at(landmark,Vector3.UP)
	await snap(game,style+"-landmark-detail",directory)
	# Real simulation with scripted positioning. This is not a human playtest.
	var table_index: int=-1
	for i in range(game.sim.objects.size()):
		if game.sim.objects[i]["archetype"]=="support_table": table_index=i;break
	var support_id: String=game.sim.objects[table_index]["id"]
	var payloads: Array=[]
	for i in range(game.sim.objects.size()):
		if game.sim.objects[i]["support"]==support_id: payloads.append(i)
	game.sim.force_size(2)
	game.sim.teleport(game.sim.objects[table_index]["position"]*Vector3(1,0,1))
	game.sim.begin()
	var observed_release: bool=false
	var released_payloads: Dictionary={}
	for i in range(240):
		game.sim.tick(1.0/60.0,Vector2.ZERO)
		for index in payloads:
			if game.sim.objects[index]["state"]!=game.Simulation.LOCKED: released_payloads[index]=true
		if i==25:
			game._sync_camera(0.0,true)
			await snap(game,style+"-support-swallow",directory)
	game._sync_camera(0.0,true)
	await snap(game,style+"-market-after",directory)
	observed_release=not payloads.is_empty() and released_payloads.size()==payloads.size()
	report["checks"].append({"name":"scripted-support-release","support":support_id,"payloadCount":payloads.size(),"releasedCount":released_payloads.size(),"observedRelease":observed_release,"supportConsumed":game.sim.objects[table_index]["state"]==game.Simulation.CONSUMED})
	game.sim.reset(false)
	var pallet_index: int=-1
	for i in range(game.sim.objects.size()):
		if game.sim.objects[i]["archetype"]=="support_pallet":pallet_index=i;break
	var pallet_id: String=game.sim.objects[pallet_index]["id"]
	var pallet_payloads: Array=[]
	for i in game.sim.objects.size():
		if game.sim.objects[i]["support"]==pallet_id:pallet_payloads.append(i)
	var pallet_position: Vector3=game.sim.objects[pallet_index]["position"]
	game.camera.projection=Camera3D.PROJECTION_ORTHOGONAL;game.camera.size=4.0
	game.camera.position=pallet_position+Vector3(3,3,5);game.camera.look_at(pallet_position,Vector3.UP)
	await snap(game,style+"-pallet-contact",directory)
	game.sim.force_size(2);game.sim.teleport(pallet_position*Vector3(1,0,1));game.sim.begin()
	var pallet_release=false
	var released_pallet_payloads: Dictionary={}
	for i in 240:
		game.sim.tick(1./60.,Vector2.ZERO)
		for index in pallet_payloads:
			if game.sim.objects[index]["state"]!=game.Simulation.LOCKED:released_pallet_payloads[index]=true
	pallet_release=not pallet_payloads.is_empty() and released_pallet_payloads.size()==pallet_payloads.size()
	var pallet_consumed: bool=game.sim.objects[pallet_index]["state"]==game.Simulation.CONSUMED
	report["checks"].append({"name":"scripted-pallet-release","support":pallet_id,"payloadCount":pallet_payloads.size(),"releasedCount":released_pallet_payloads.size(),"observedRelease":pallet_release,"supportConsumed":pallet_consumed})
	# The taller visual-only envelope must still disappear through the original gameplay path.
	game.sim.reset(false)
	var building_index: int=-1
	for i in game.sim.objects.size():
		if game.sim.objects[i]["id"]=="wide_building_001":building_index=i;break
	var building_position: Vector3=game.sim.objects[building_index]["position"]
	game.sim.force_size(5);game.sim.teleport(building_position*Vector3(1,0,1));game.sim.begin()
	game.camera.size=5.;game.camera.position=building_position+Vector3(3,4,5);game.camera.look_at(building_position,Vector3.UP)
	for i in 240:
		game.sim.tick(1./60.,Vector2.ZERO)
		if i==28:await snap(game,style+"-building-swallow",directory)
	var building_consumed: bool=game.sim.objects[building_index]["state"]==game.Simulation.CONSUMED
	report["checks"].append({"name":"visual-envelope-building-swallow","slot":"wide_building_001","consumed":building_consumed})
	game.sim.reset(false)
	var tower_index: int=-1
	for i in game.sim.objects.size():
		if game.sim.objects[i]["id"]=="building_segment_001":tower_index=i;break
	game.sim.force_size(3);game.sim.teleport(game.sim.objects[tower_index]["position"]*Vector3(1,0,1));game.sim.begin()
	for i in 300:game.sim.tick(1./60.,Vector2.ZERO)
	var tower_consumed: bool=game.sim.objects[tower_index]["state"]==game.Simulation.CONSUMED
	report["checks"].append({"name":"visual-envelope-tower-swallow","slot":"building_segment_001","consumed":tower_consumed})
	# Normal-size keyboard input through the original input/physics path, fixed timestep.
	game.sim.reset(false)
	var reference=game.Simulation.new()
	reference.initialize(game.sim.config,game.tuning)
	var movement_start: Vector3=game.sim.holes[0]["position"]
	var route: Array=[Vector2(0,-1),Vector2(1,0),Vector2(0,1),Vector2(-1,0)]
	var route_keys: Array=[KEY_W,KEY_D,KEY_S,KEY_A]
	var camera_frames: Array=[]
	var input_path_pass: bool=true
	var input_mismatch: Dictionary={}
	game.set_physics_process(false)
	game.paused=false
	for frame in 720:
		var direction: Vector2=route[int(frame/180)]
		if frame%180==0:
			for route_key in route_keys:
				var event=InputEventKey.new()
				event.keycode=route_key
				event.physical_keycode=route_key
				event.pressed=route_key==route_keys[int(frame/180)]
				Input.parse_input_event(event)
			Input.flush_buffered_events()
		if input_mismatch.is_empty() and not game._movement_input().is_equal_approx(direction):
			input_mismatch={"frame":frame,"expected":[direction.x,direction.y],"actual":[game._movement_input().x,game._movement_input().y]}
		input_path_pass=input_path_pass and game._movement_input().is_equal_approx(direction)
		game._physics_process(1./60.);reference.tick(1./60.,direction)
		if frame%180==179:
			game._sync_camera(0.0,true)
			game._sync_views()
			game._sync_occlusion(1.0)
			var hp: Vector3=game.sim.holes[0]["position"]+Vector3(0,.06,0)
			var projected: Vector2=game.camera.unproject_position(hp)
			var inside: bool=not game.camera.is_position_behind(hp) and Rect2(Vector2.ZERO,Vector2(1536,1024)).has_point(projected)
			input_path_pass=input_path_pass and inside
			camera_frames.append({"frame":frame,"holeInViewport":inside,"holeScreenXY":[projected.x,projected.y],"occlusionPathCalled":true})
			await snap(game,style+"-normal-input-"+str(frame),directory)
	for route_key in route_keys:
		var event=InputEventKey.new();event.keycode=route_key;event.physical_keycode=route_key;event.pressed=false
		Input.parse_input_event(event)
	Input.flush_buffered_events()
	game.paused=true
	var ordinary_pass: bool=input_path_pass and game.sim.holes[0]["position"].distance_to(movement_start)>.01 and game.sim.total_reward==reference.total_reward and game.sim.consumed_count==reference.consumed_count and game.sim.holes[0]["position"].is_equal_approx(reference.holes[0]["position"]) and not game.sim.assisted_run
	for index in game.sim.objects.size():
		ordinary_pass=ordinary_pass and game.sim.objects[index]["state"]==reference.objects[index]["state"] and game.sim.objects[index]["position"].is_equal_approx(reference.objects[index]["position"])
	report["checks"].append({"name":"ordinary-input-fixed-step-replay","inputPath":"InputEventKey -> _movement_input -> _physics_process","inputMismatch":input_mismatch,"cameraFrames":camera_frames,"frames":720,"seconds":12,"passed":ordinary_pass,"score":game.sim.total_reward,"consumed":game.sim.consumed_count,"assisted":game.sim.assisted_run,"humanPlaytest":false})
	var expected: int=int(OS.get_environment("HOLE_ART_EXPECTED")) if OS.has_environment("HOLE_ART_EXPECTED") else 93
	var passed: bool = game.object_views.size()==215 and loaded_count==expected and bounds_checks.is_empty() and art_checks.is_empty() and observed_release and report["checks"][0]["supportConsumed"] and pallet_release and pallet_consumed and building_consumed and tower_consumed and ordinary_pass
	await finish_report(game,directory,style,passed)
