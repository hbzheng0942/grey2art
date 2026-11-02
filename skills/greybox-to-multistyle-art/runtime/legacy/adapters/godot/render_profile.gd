extends RefCounted
# Renderer + display transform + illumination form one calibrated profile.
# Albedo is source_color; metallic/roughness and normal maps are linear data.
static func apply(environment: Environment, sun: DirectionalLight3D, orbital: bool, controls: Dictionary={}) -> void:
	environment.ambient_light_source=Environment.AMBIENT_SOURCE_COLOR
	environment.ambient_light_color=Color("b8c5dc") if orbital else Color("e4e0d5")
	environment.ambient_light_energy=.22
	environment.tonemap_mode=Environment.TONE_MAPPER_ACES
	environment.tonemap_exposure=1.0
	sun.light_color=Color("edf3ff") if orbital else Color("fff1d9")
	sun.light_energy=.72
	sun.light_angular_distance=.8
	sun.directional_shadow_max_distance=65.0
	var render: Dictionary=controls.get("render",{})
	environment.ambient_light_energy=float(render.get("ambient_energy",environment.ambient_light_energy))
	environment.tonemap_exposure=float(render.get("exposure",environment.tonemap_exposure))
	sun.light_energy=float(render.get("sun_energy",sun.light_energy))
	sun.light_angular_distance=float(render.get("sun_angular_distance",sun.light_angular_distance))
	if render.has("shadow_filter_quality"):RenderingServer.directional_soft_shadow_filter_set_quality(int(render["shadow_filter_quality"]))
	sun.shadow_blur=float(render.get("shadow_blur",sun.shadow_blur))
	sun.shadow_opacity=float(render.get("shadow_opacity",sun.shadow_opacity))
	if render.has("ambient_color"):environment.ambient_light_color=Color(render["ambient_color"])
	if render.has("sun_color"):sun.light_color=Color(render["sun_color"])
	if render.has("sun_rotation_degrees"):
		var a: Array=render["sun_rotation_degrees"]
		sun.rotation_degrees=Vector3(a[0],a[1],a[2])

