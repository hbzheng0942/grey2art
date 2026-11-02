extends RefCounted
# Narrow opaque PBR adapter; preserve originals and reject unsupported runtime features.
var shader_variants: Dictionary = {}

func channel_mask(channel: int) -> Vector4:
	match channel:
		0: return Vector4(1,0,0,0)
		1: return Vector4(0,1,0,0)
		2: return Vector4(0,0,1,0)
		3: return Vector4(0,0,0,1)
	return Vector4(0.3333,0.3333,0.3333,0)

func convert_materials(node: Node, target: Array, base_shader: Shader) -> Array:
	var failures: Array = []
	if node is MeshInstance3D and node.mesh != null:
		for i in range(node.mesh.get_surface_count()):
			var source_mat = node.get_active_material(i)
			if not source_mat is StandardMaterial3D:
				failures.append(str(node.name)+": unsupported material class")
				continue
			if source_mat.transparency != BaseMaterial3D.TRANSPARENCY_DISABLED or source_mat.shading_mode != BaseMaterial3D.SHADING_MODE_PER_PIXEL or (source_mat.vertex_color_use_as_albedo and (node.mesh.surface_get_format(i) & Mesh.ARRAY_FORMAT_COLOR) != 0) or (source_mat.emission_enabled and (source_mat.emission_texture != null or source_mat.emission.r > 0.0 or source_mat.emission.g > 0.0 or source_mat.emission.b > 0.0)) or source_mat.ao_enabled or source_mat.clearcoat_enabled or source_mat.rim_enabled or source_mat.subsurf_scatter_enabled or source_mat.anisotropy_enabled or source_mat.heightmap_enabled or source_mat.refraction_enabled or source_mat.uv1_triplanar:
				var active: Array=[]
				for key in ["transparency","shading_mode","vertex_color_use_as_albedo","emission_enabled","ao_enabled","clearcoat_enabled","rim_enabled","subsurf_scatter_enabled","anisotropy_enabled","heightmap_enabled","refraction_enabled","uv1_triplanar"]:active.append(key+"="+str(source_mat.get(key)))
				failures.append(str(node.name)+": unsupported runtime material feature "+str(active))
				continue
			var mat: ShaderMaterial = ShaderMaterial.new()
			mat.shader = base_shader
			if source_mat is StandardMaterial3D:
				var cull: int = source_mat.cull_mode
				var shader_key=str(base_shader.get_instance_id())+":"+str(cull)
				if not shader_variants.has(shader_key):
					var shader = Shader.new()
					shader.code = base_shader.code.replace("cull_disabled", "cull_back" if cull == 0 else ("cull_front" if cull == 1 else "cull_disabled"))
					shader_variants[shader_key] = shader
				mat.shader = shader_variants[shader_key]
				mat.set_shader_parameter("surface_specular", source_mat.metallic_specular)
				mat.set_shader_parameter("uv_scale", source_mat.uv1_scale)
				mat.set_shader_parameter("uv_offset", source_mat.uv1_offset)
			if source_mat is StandardMaterial3D:
				mat.set_shader_parameter("base_color", source_mat.albedo_color)
				mat.set_shader_parameter("surface_roughness", source_mat.roughness)
				mat.set_shader_parameter("surface_metallic", source_mat.metallic)
				mat.set_shader_parameter("roughness_channel", channel_mask(source_mat.roughness_texture_channel))
				mat.set_shader_parameter("metallic_channel", channel_mask(source_mat.metallic_texture_channel))
				for pair in [["albedo", source_mat.albedo_texture],["roughness",source_mat.roughness_texture],["metallic",source_mat.metallic_texture]]:
					if pair[1] != null:
						mat.set_shader_parameter("has_"+pair[0], true)
						mat.set_shader_parameter(pair[0]+"_map",pair[1])
				if source_mat.normal_enabled and source_mat.normal_texture != null:
					mat.set_shader_parameter("has_normal",true)
					mat.set_shader_parameter("normal_map",source_mat.normal_texture)
					mat.set_shader_parameter("normal_strength",source_mat.normal_scale)
			node.set_surface_override_material(i,mat)
			target.append(mat)
	for child in node.get_children(): failures.append_array(convert_materials(child,target,base_shader))
	return failures

