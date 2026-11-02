extends "res://scripts/baseline_visual_factory.gd"
const ART_SHADER = preload("res://shaders/pilot_object.gdshader")
var style_id: String = OS.get_environment("HOLE_ART_STYLE")
const Dressing = preload("res://scripts/art_dressing.gd")
const Fitter = preload("res://scripts/art_fit.gd")
var fitted_templates: Dictionary = {}
var material_converter = preload("res://scripts/material_converter.gd").new()
var skin: Dictionary = {}
var loaded: Dictionary = {}
var look_controls: Dictionary = preload("res://scripts/look_controls.gd").read_controls()

func release_templates() -> void:
	for entry in fitted_templates.values():
		if is_instance_valid(entry): entry.free()
	fitted_templates.clear()
	for entry in loaded.values():
		if is_instance_valid(entry["template"]): entry["template"].free()
	loaded.clear()

func _init() -> void:
	super._init()
	if style_id.is_empty(): style_id = "ceramic"
	var parsed = JSON.parse_string(FileAccess.get_file_as_string("res://data/pilot_skin.json"))
	if parsed is Dictionary: skin = parsed.get(style_id, {})

func bounds_of(node: Node3D, parent_transform: Transform3D = Transform3D.IDENTITY) -> AABB:
	var transform: Transform3D = parent_transform * node.transform
	var result: AABB = AABB()
	if node is MeshInstance3D and node.mesh != null: result = transform * node.get_aabb()
	for child in node.get_children():
		if child is Node3D:
			var child_bounds: AABB = bounds_of(child, transform)
			if child_bounds.size.length_squared() > 0.0:
				result = child_bounds if result.size.length_squared() == 0.0 else result.merge(child_bounds)
	return result

func convert_materials(node: Node, target: Array) -> Array:
	return material_converter.convert_materials(node,target,ART_SHADER)

func decorative_model(asset_key: String, desired: Vector3) -> Node3D:
	# Canonical generated props, attached to a parent logical object; no new simulation objects.
	for candidate in skin.values():
		if candidate.get("assetKey","")!=asset_key:continue
		var path: String=candidate["path"]
		if not loaded.has(path):
			var doc=GLTFDocument.new();var state=GLTFState.new()
			if doc.append_from_file(path,state)!=OK:return Node3D.new()
			var template: Node3D=doc.generate_scene(state)
			loaded[path]={"template":template,"bounds":bounds_of(template)}
		var model: Node3D=loaded[path]["template"].duplicate()
		if asset_key=="ceramic-parcel":plain_decorative_sugar(model)
		var bounds: AABB=loaded[path]["bounds"]
		var factor: float=minf(desired.x/bounds.size.x,minf(desired.y/bounds.size.y,desired.z/bounds.size.z))
		var wrapper=Node3D.new();wrapper.add_child(model)
		model.scale=Vector3.ONE*factor
		model.position=Vector3(-bounds.get_center().x*factor,-bounds.position.y*factor,-bounds.get_center().z*factor)
		return wrapper
	push_error("Missing canonical decorative asset: "+asset_key)
	return Node3D.new()

func plain_decorative_sugar(node: Node) -> void:
	if node is MeshInstance3D:
		for surface in node.mesh.get_surface_count():
			var material=StandardMaterial3D.new();material.albedo_color=Color("eee7d2");material.roughness=.64
			node.set_surface_override_material(surface,material)
	for child in node.get_children():plain_decorative_sugar(child)

func build(a: Dictionary, asset_id: String = "", logical_id: String = "") -> Node3D:
	if not skin.has(logical_id):
		var fallback: Node3D = super.build(a,asset_id,logical_id)
		fallback.set_meta("pilot_art",false)
		return fallback
	var spec: Dictionary = skin[logical_id]
	var adjustment: Dictionary = preload("res://scripts/look_controls.gd").asset_controls(look_controls,spec)
	var path: String = spec["path"]
	if not loaded.has(path):
		var doc: GLTFDocument = GLTFDocument.new()
		var state: GLTFState = GLTFState.new()
		var error: Error = doc.append_from_file(path,state)
		if error != OK:
			push_error("Cannot load pilot GLB: "+path)
			return super.build(a,asset_id,logical_id)
		var template: Node3D = doc.generate_scene(state)
		loaded[path] = {"template":template,"bounds":bounds_of(template)}
	var entry: Dictionary = loaded[path]
	var model: Node3D = entry["template"].duplicate()
	var bounds: AABB = entry["bounds"]
	var s: Array = a["size_xyz"]
	var target: Vector3 = Vector3(s[0],s[1],s[2])
	var factor: float = minf(target.x/bounds.size.x,minf(target.y/bounds.size.y,target.z/bounds.size.z))
	var contract_failures: Array=[]
	if spec.has("visualTargetXYZ"):
		model.free()
		var t: Array=adjustment.get("target_xyz",spec["visualTargetXYZ"])
		var visual_target=Vector3(t[0],t[1],t[2])
		var cache_key=spec["sha256"]+JSON.stringify(t)+spec["variant"]+spec["regionId"]+JSON.stringify(adjustment)
		if not fitted_templates.has(cache_key):
			var revised: Node3D=entry["template"].duplicate()
			if spec["regionId"]=="vehicle":revised.rotation.y=PI*.5
			revised.rotation.y+=deg_to_rad(float(adjustment.get("yaw_degrees",0.0)))
			var raw_bounds: AABB=bounds_of(revised)
			var fitting=Fitter.new()
			fitting.fit(revised,raw_bounds,visual_target,"sugar" if style_id=="ceramic" and spec["regionId"]=="parcel" else spec["regionId"],spec["variant"],Transform3D.IDENTITY,adjustment)
			# Explicit legacy art choice; do not hide material conversion in fitting.
			if spec["variant"]=="plain" or (style_id=="ceramic" and spec["regionId"]=="parcel"):
				plain_decorative_sugar(revised)
			fitted_templates[cache_key]=revised
		model=fitted_templates[cache_key].duplicate()
		bounds=bounds_of(model);factor=1.
		for axis in 3:
			if bounds.size[axis]<float(spec["minXYZ"][axis])-.003 or bounds.size[axis]>float(spec["maxXYZ"][axis])+.003:
				contract_failures.append("axis-"+str(axis)+": "+str(bounds.size[axis]))
		if not contract_failures.is_empty():push_error("Art fit contract failed "+logical_id+": "+str(contract_failures))
	var holder: Node3D = Node3D.new()
	holder.name = "Visual"
	var fit: Node3D = Node3D.new()
	fit.name = "Fit"
	fit.scale = Vector3.ONE * factor
	fit.position = Vector3(-(bounds.position.x+bounds.size.x*.5)*factor,-target.y*.5-bounds.position.y*factor,-(bounds.position.z+bounds.size.z*.5)*factor)
	holder.add_child(fit)
	fit.add_child(model)
	var own_materials: Array = []
	contract_failures.append_array(convert_materials(model,own_materials))
	if OS.get_environment("HOLE_ART_NO_DRESSING") != "1":
		var dressing = Dressing.new()
		dressing.build(holder, self, style_id, spec["familyId"], target, spec.get("variant","base"),adjustment)
		contract_failures.append_array(convert_materials(holder.get_node("Dressing"), own_materials))
	# Artistic overrides are separate from the faithful material conversion.
	var look: Dictionary=look_controls.get("render",{}).get("materials",{}).get(spec["regionId"],{})
	for material in own_materials:
		if look.has("roughness_multiplier"):
			material.set_shader_parameter("surface_roughness",clampf(float(material.get_shader_parameter("surface_roughness"))*float(look["roughness_multiplier"]),0.,1.))
	var aggregate: AABB = bounds_of(holder)
	holder.set_meta("cutaway_materials",own_materials)
	holder.set_meta("cutaway",0.0)
	holder.set_meta("pilot_art",true)
	holder.set_meta("family_id",spec["familyId"])
	holder.set_meta("asset_id",asset_id)
	holder.set_meta("fit_size",aggregate.size)
	holder.set_meta("fit_aabb",aggregate)
	holder.set_meta("model_size",bounds.size)
	holder.set_meta("art_contract_failures",contract_failures)
	holder.set_meta("art_region",spec.get("regionId",spec["familyId"]))
	holder.set_meta("art_variant",spec.get("variant","base"))
	holder.set_meta("art_max",spec.get("maxXYZ",s))
	holder.set_meta("status","GENERATED_PILOT_NEEDS_NATIVE_REVIEW")
	return holder
