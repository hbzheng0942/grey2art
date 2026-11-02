extends RefCounted
# Attached visual detail stays inside the original logical footprint and follows swallowing.
var groups: Dictionary={}
func add(mesh: Mesh, xform: Transform3D, color: String) -> void:
	if not groups.has(color):
		var st=SurfaceTool.new();st.begin(Mesh.PRIMITIVE_TRIANGLES);groups[color]=st
	groups[color].append_from(mesh,0,xform)
func box(size: Vector3, p: Vector3, color: String) -> void:
	var m=BoxMesh.new();m.size=size;add(m,Transform3D(Basis.IDENTITY,p),color)
func cylinder(radius: float, height: float, p: Vector3, color: String, top: float=-1.) -> void:
	var m=CylinderMesh.new();m.bottom_radius=radius;m.top_radius=radius if top<0. else top;m.height=height;m.radial_segments=20
	add(m,Transform3D(Basis.IDENTITY,p),color)
func oval(size: Vector3, p: Vector3, rotation: Vector3, color: String) -> void:
	var m=SphereMesh.new();m.radius=.5;m.height=1.;m.radial_segments=8;m.rings=4
	add(m,Transform3D(Basis.from_euler(rotation).scaled(size),p),color)
func plant(p: Vector3, r: float, seed_: int) -> void:
	var rng=RandomNumberGenerator.new();rng.seed=seed_
	cylinder(r*.78,r*1.4,p+Vector3(0,r*.7,0),"b99560",r)
	cylinder(r*1.05,r*.18,p+Vector3(0,r*1.38,0),"e4d7b6")
	cylinder(r*.91,r*.04,p+Vector3(0,r*1.49,0),"514730")
	for i in 30:
		var a=rng.randf()*TAU;var d=sqrt(rng.randf())*r*.9
		var q=p+Vector3(cos(a)*d,r*(1.65+rng.randf()*2.1),sin(a)*d)
		oval(Vector3(r*.54,r*.33,r*.75),q,Vector3(rng.randf(),a,rng.randf()),"62734a" if i%2==0 else "87964d")
		if i%4==0:
			for j in 5:
				var theta=j*TAU/5.;var petal=q+Vector3(cos(theta)*r*.12,r*.12,sin(theta)*r*.12)
				oval(Vector3(r*.19,r*.08,r*.19),petal,Vector3.ZERO,"e8dfba")
			oval(Vector3(r*.12,r*.09,r*.12),q+Vector3(0,r*.16,0),Vector3.ZERO,"c5943a")
func build(holder: Node3D, _factory, style: String, family: String, size: Vector3, variant: String="base", controls: Dictionary={}) -> void:
	var root=Node3D.new();root.name="Dressing";holder.add_child(root)
	if family not in ["tower","kiosk","egg","croissant","cake","gyro","dome","pitcher","jug","drum"]:return
	var base=-size.y*.5
	if variant in ["cap-a","cap-b"]:
		# Distinct implemented detail, keyed by the plan's variant rather than implicit reuse.
		var badge=Vector3(0,base+size.y*.28,size.z*.475)
		if variant=="cap-a":
			box(Vector3(size.x*.16,.12,.018),badge,"b58c43" if style=="ceramic" else "d68b40")
		else:
			for side in [-1.,1.]:
				box(Vector3(size.x*.045,.19,.018),badge+Vector3(side*size.x*.055,.035,0),"294d7c" if style=="ceramic" else "4da5a8")
	if style=="ceramic":
		# Greenery, ceramic pots and threshold stones are part of each building, not new blockers.
		var r=minf(.19,minf(size.x,size.z)*.10)
		for side in [-1.,1.]:
			plant(Vector3(side*(size.x*.5-r*1.15),base+.015,size.z*.5-r*1.15),r,int(size.y*91.+side*23.))
		if family in ["egg","cake","croissant"]:
			for side in [-1.,1.]:
				plant(Vector3(side*(size.x*.5-r*1.15),base+.015,-size.z*.25),r,int(size.y*73.+side*17.))
		# Slim inset foundation courses remain within the original envelope.
		var count=maxi(3,int(size.x/.4))
		for i in count:
			var x=-size.x*.40+(i+.5)*size.x*.8/count
			box(Vector3(size.x*.8/count-.018,.065,.14),Vector3(x,base+.033,size.z*.43),"c6b18a")
	else:
		# Dock brackets, raised service sockets and inset teal strips give pods a grounded base.
		for side in [-1.,1.]:
			var x=side*size.x*.43;var z=size.z*.36
			box(Vector3(size.x*.12,.12,size.z*.20),Vector3(x,base+.06,z),"535e67")
			box(Vector3(size.x*.08,.15,size.z*.055),Vector3(x,base+.12,z),"b57d3f")
			box(Vector3(size.x*.07,.025,size.z*.10),Vector3(x,base+.147,z-size.z*.065),"589b9b")
			cylinder(.045,.025,Vector3(x,base+.13,z+size.z*.08),"a6adb0")
		box(Vector3(size.x*.56,.04,.16),Vector3(0,base+.025,size.z*.43),"747d80")
	# Reuse verified generated props for concept-like frontage clusters, entirely within the parent footprint.
	var cluster_count: int=int(controls.get("cluster_count",0))
	var cluster_positions: Array=[Vector2(0,0),Vector2(1,0),Vector2(2,0),Vector2(.3,1),Vector2(1.3,1),Vector2(.65,2)]
	for index in cluster_count:
		var cube: Node3D=_factory.decorative_model(style+"-parcel",Vector3(.28,.28,.28))
		var p: Vector2=cluster_positions[index]
		cube.rotation.y=deg_to_rad(-4.+float(index)*2.)
		cube.position=Vector3(-size.x*.5+.24+p.x*.27,base+.012+p.y*.28,size.z*.5-.22-p.y*.025)
		root.add_child(cube)
	if cluster_count>0:
		var vessel: Node3D=_factory.decorative_model(style+"-bin",Vector3(.28,.5,.28))
		vessel.position=Vector3(size.x*.5-.24,base+.012,-size.z*.5+.24)
		root.add_child(vessel)
	for color in groups:
		var node=MeshInstance3D.new();node.name="Detail_"+color;node.mesh=groups[color].commit()
		var mat=StandardMaterial3D.new();mat.albedo_color=Color(color);mat.roughness=.70;mat.metallic=.22 if style=="orbital" else 0.
		node.material_override=mat;root.add_child(node)

	var b: AABB = _factory.bounds_of(root)
	var half_x=maxf(absf(b.position.x),absf(b.end.x))
	var half_z=maxf(absf(b.position.z),absf(b.end.z))
	var factor=minf(1.,minf(size.x*.495/maxf(half_x,.001),size.z*.495/maxf(half_z,.001)))
	root.scale=Vector3(factor,1.,factor)
