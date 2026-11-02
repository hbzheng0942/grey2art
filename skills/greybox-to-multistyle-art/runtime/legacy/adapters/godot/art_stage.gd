extends "res://scripts/baseline_waterfront_stage.gd"
const ART_FLOOR=preload("res://shaders/art_floor.gdshader")
const OUTSIDE=preload("res://shaders/art_outside.gdshader")

func surface(color: Color, metallic: float=0.0, roughness: float=.55) -> StandardMaterial3D:
	var mat=StandardMaterial3D.new()
	mat.albedo_color=color;mat.metallic=metallic;mat.roughness=roughness
	return mat

func boxes(parent: Node3D, name_: String, size: Vector3, transforms: Array, mat: Material) -> void:
	if transforms.is_empty():return
	var mesh=BoxMesh.new();mesh.size=size
	var multi=MultiMesh.new();multi.transform_format=MultiMesh.TRANSFORM_3D;multi.mesh=mesh;multi.instance_count=transforms.size()
	for i in transforms.size():multi.set_instance_transform(i,transforms[i])
	var view=MultiMeshInstance3D.new();view.name=name_;view.multimesh=multi;view.material_override=mat;parent.add_child(view)

func paving_mesh(width: float, depth: float, pitch: float, orbital: bool, gap_multiplier: float=1.0) -> ArrayMesh:
	# One merged mesh, recessed seams and chamfered slab edges; no extra colliders.
	var st=SurfaceTool.new();st.begin(Mesh.PRIMITIVE_TRIANGLES)
	var nx=int(ceil(width/pitch));var nz=int(ceil(depth/pitch))
	for iz in nz:
		for ix in nx:
			var x0=-width*.5+ix*pitch;var x1=minf(x0+pitch,width*.5)
			var z0=-depth*.5+iz*pitch;var z1=minf(z0+pitch,depth*.5)
			var gap=(.008 if not orbital else .012)*gap_multiplier
			var bevel=.025 if not orbital else .035
			var outer=[Vector3(x0+gap,-.022,z0+gap),Vector3(x1-gap,-.022,z0+gap),Vector3(x1-gap,-.022,z1-gap),Vector3(x0+gap,-.022,z1-gap)]
			var inner=[Vector3(x0+bevel,0,z0+bevel),Vector3(x1-bevel,0,z0+bevel),Vector3(x1-bevel,0,z1-bevel),Vector3(x0+bevel,0,z1-bevel)]
			for tri in [[inner[0],inner[1],inner[2]],[inner[0],inner[2],inner[3]]]:
				for v in tri:st.set_normal(Vector3.UP);st.set_uv(Vector2(v.x,v.z));st.add_vertex(v)
			for j in 4:
				var k=(j+1)%4
				for tri in [[outer[j],inner[j],inner[k]],[outer[j],inner[k],outer[k]]]:
					var n=(tri[2]-tri[0]).cross(tri[1]-tri[0]).normalized()
					for v in tri:st.set_normal(n);st.set_uv(Vector2(v.x,v.z));st.add_vertex(v)
	st.index()
	return st.commit()

func build(parent: Node3D, factory, map: Dictionary) -> Dictionary:
	var result: Dictionary=super.build(parent,factory,map)
	var root: Node3D=result["root"]
	root.name="ConceptEnvironment"
	var orbital: bool=factory.style_id=="orbital"
	var controls: Dictionary=factory.look_controls
	var render_controls: Dictionary=controls.get("render",{})
	for child in root.get_children():
		if child.has_meta("role") and child.get_meta("role")=="SCENERY_ONLY":child.free()
	var floor_mat: ShaderMaterial=result["floor_material"]
	floor_mat.shader=ART_FLOOR;floor_mat.set_shader_parameter("orbital",orbital)
	floor_mat.set_shader_parameter("real_bevel",true)
	for parameter in render_controls.get("floor",{}):floor_mat.set_shader_parameter(parameter,render_controls["floor"][parameter])
	root.get_node("DryLand_HoleAware").mesh=paving_mesh(map["floor_size_xz"][0],map["floor_size_xz"][1],2. if orbital else 1./1.35,orbital,float(controls.get("assembly",{}).get("paving_gap_multiplier",1.0)))
	var grout=MeshInstance3D.new();grout.name="RecessedGrout_HoleAware"
	var grout_mesh=PlaneMesh.new();grout_mesh.size=Vector2(map["floor_size_xz"][0],map["floor_size_xz"][1]);grout.mesh=grout_mesh
	grout.position.y=-.025;grout.material_override=floor_mat;root.add_child(grout)
	var outside=root.get_node("Water_NOT_PLAYABLE")
	outside.name="Space_NOT_PLAYABLE" if orbital else "Coffee_NOT_PLAYABLE"
	if orbital:outside.position.y=-7.
	outside.material_override.shader=OUTSIDE;outside.material_override.set_shader_parameter("orbital",orbital)
	outside.material_override.set_shader_parameter("background_detail",float(render_controls.get("background_detail",1.0)))
	if not orbital:
		var meta=JSON.parse_string(FileAccess.get_file_as_string("res://data/coffee-texture.json"))
		var image=Image.load_from_file(meta.path);image.generate_mipmaps()
		outside.material_override.set_shader_parameter("coffee_map",ImageTexture.create_from_image(image))
	var points: Array=map["land_polygon_xz"]
	var curb: Array=[];var band: Array=[];var fixtures: Array=[];var lights: Array=[];var clamp_bases: Array=[];var clamp_caps: Array=[]
	for i in points.size():
		var a=Vector2(points[i][0],points[i][1]);var b=Vector2(points[(i+1)%points.size()][0],points[(i+1)%points.size()][1])
		var d: Vector2=(b-a).normalized();var n=Vector2(-d.y,d.x)
		var count: int=int(ceil(a.distance_to(b)/.5))
		for j in count:
			var p: Vector2=a.lerp(b,(float(j)+.5)/count)
			var basis=Basis(Vector3.UP,-atan2(d.y,d.x))
			curb.append(Transform3D(basis,Vector3(p.x,-.025,p.y)))
			band.append(Transform3D(basis,Vector3(p.x,-.22,p.y)))
			if orbital and j%9==3:
				fixtures.append(Transform3D(basis,Vector3(p.x,.035,p.y)))
				clamp_bases.append(Transform3D(basis,Vector3(p.x,-.04,p.y)))
				for side in [-1.,1.]:
					clamp_caps.append(Transform3D(basis,Vector3(p.x+d.x*.20*side,.145,p.y+d.y*.20*side)))
				lights.append(Transform3D(basis,Vector3(p.x+n.x*.16,.10,p.y+n.y*.16)))
	boxes(root,"RimTiles",Vector3(.484,.12,.23),curb,surface(Color("c9b281") if not orbital else Color("626975"),.12,.45))
	boxes(root,"RimUnderband",Vector3(.50,.32,.16),band,surface(Color("775b3d") if not orbital else Color("252d38"),.2,.6))
	boxes(root,"OrangeEdgeClamps",Vector3(.58,.20,.42),fixtures,surface(Color("e28a28"),.25,.45))
	boxes(root,"ClampBacking",Vector3(.70,.13,.50),clamp_bases,surface(Color("35414b"),.5,.65))
	boxes(root,"ClampFasteners",Vector3(.055,.025,.10),clamp_caps,surface(Color("bbc2bf"),.65,.45))
	var glow=surface(Color("78c7ca"));glow.emission_enabled=true;glow.emission=Color("397f8b");glow.emission_energy_multiplier=.6
	boxes(root,"EdgeNavigationLights",Vector3(.30,.025,.035),lights,glow)
	if orbital:
		var rng=RandomNumberGenerator.new();rng.seed=4481
		var asteroids: Array=[]
		for i in 70:
			var p=Vector3(rng.randf_range(-45,45),rng.randf_range(-4,-1.8),rng.randf_range(-36,36))
			if absf(p.x)<24. and absf(p.z)<20.:continue
			var s=rng.randf_range(.15,.65)
			asteroids.append(Transform3D(Basis.from_euler(Vector3(rng.randf()*3.,rng.randf()*3.,rng.randf()*3.)).scaled(Vector3(s,s*.7,s*.83)),p))
		var rock=SphereMesh.new();rock.radius=1.;rock.height=2.;rock.radial_segments=7;rock.rings=4
		var mm=MultiMesh.new();mm.transform_format=MultiMesh.TRANSFORM_3D;mm.mesh=rock;mm.instance_count=asteroids.size()
		for i in asteroids.size():mm.set_instance_transform(i,asteroids[i])
		var view=MultiMeshInstance3D.new();view.name="DistantAsteroids";view.multimesh=mm;view.material_override=surface(Color("595451"),.05,.95);root.add_child(view)
	var environment: Environment=parent.get_node("WorldEnvironment").environment
	var sun: DirectionalLight3D=parent.get_node("KeyLight")
	preload("res://scripts/render_profile.gd").apply(environment,sun,orbital,controls)
	root.set_meta("effective_look_controls",controls)
	root.set_meta("art_environment",factory.style_id)
	return result
