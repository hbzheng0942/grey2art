extends SceneTree
var factory=preload("res://scripts/visual_factory.gd").new()
var output: String
var records: Array=[]
var rejection_checks: Array=[]
func _initialize(): call_deferred("run")
func capture(name: String) -> String:
 for i in range(5):await process_frame
 RenderingServer.force_draw(false)
 var path=output+"/"+name+".png"
 root.get_texture().get_image().save_png(path)
 return path
func pair(world: Node3D,model: Node3D,id: String):
 var bg=await capture(id+"-background")
 world.add_child(model)
 var imported=await capture(id+"-imported")
 var errors=factory.convert_materials(model,[])
 if not errors.is_empty():push_error(str(errors));quit(2);return
 var converted=await capture(id+"-converted")
 records.append({"id":id,"imported":imported,"converted":converted,"background":bg})
 model.queue_free();await process_frame
func run():
 if DisplayServer.get_name()=="headless":quit(2);return
 output=OS.get_environment("HOLE_RENDER_EVIDENCE")
 if output.is_empty():quit(2);return
 DirAccess.make_dir_recursive_absolute(output)
 root.content_scale_size=Vector2i(768,512)
 root.content_scale_mode=Window.CONTENT_SCALE_MODE_VIEWPORT
 root.size=Vector2i(768,512)
 var world=Node3D.new();root.add_child(world)
 var env=WorldEnvironment.new();env.environment=Environment.new()
 env.environment.background_mode=Environment.BG_COLOR;env.environment.background_color=Color("303844")
 world.add_child(env)
 var light=DirectionalLight3D.new();light.rotation=Vector3(-1.03,-.55,0);light.shadow_enabled=true;world.add_child(light)
 var camera=Camera3D.new();camera.projection=Camera3D.PROJECTION_ORTHOGONAL;camera.size=3.4;camera.current=true
 world.add_child(camera);camera.position=Vector3(2.6,2.2,4.8);camera.look_at(Vector3(0,1,0))
 var skin=JSON.parse_string(FileAccess.get_file_as_string("res://data/pilot_skin.json"))
 var assets=[]
 for style in ["ceramic","orbital"]:
  preload("res://scripts/render_profile.gd").apply(env.environment,light,style=="orbital")
  var path: String=""
  for spec in skin[style].values():
   if spec.familyId=="tower":path=spec.path;break
  var doc=GLTFDocument.new();var state=GLTFState.new()
  if doc.append_from_file(path,state)!=OK:quit(2);return
  var model=doc.generate_scene(state)
  var bounds=factory.bounds_of(model);var factor=2.3/bounds.size.y
  model.scale=Vector3.ONE*factor;model.position=Vector3(-(bounds.position.x+bounds.size.x*.5)*factor,-bounds.position.y*factor,-(bounds.position.z+bounds.size.z*.5)*factor)
  assets.append({"path":path,"sha256":FileAccess.get_sha256(path)})
  await pair(world,model,style)
 # Analytic sentinels test factors/color independently of generated textures.
 preload("res://scripts/render_profile.gd").apply(env.environment,light,false)
 for i in range(6):
  var model=MeshInstance3D.new();var sphere=SphereMesh.new();sphere.radius=.65;sphere.height=1.3;model.mesh=sphere;model.position.y=.8
  var mat=StandardMaterial3D.new()
  mat.albedo_color=[Color(.18,.18,.18),Color(.9,.9,.9),Color(.2,.45,.8),Color(.65,.5,.15),Color(.5,.5,.5),Color(.5,.5,.5)][i]
  mat.roughness=[.8,.8,.2,.3,.8,.6][i];mat.metallic=1. if i in [3,4] else 0.
  if i==4:
   var packed=Image.create(2,2,false,Image.FORMAT_RGBA8);packed.fill(Color(.9,.3,.6,1))
   var texture=ImageTexture.create_from_image(packed)
   mat.roughness_texture=texture;mat.metallic_texture=texture
   mat.roughness_texture_channel=BaseMaterial3D.TEXTURE_CHANNEL_GREEN;mat.metallic_texture_channel=BaseMaterial3D.TEXTURE_CHANNEL_BLUE
  if i==5:
   var normal=Image.create(2,2,false,Image.FORMAT_RGBA8);normal.fill(Color(.65,.55,1,1))
   mat.normal_enabled=true;mat.normal_scale=.6;mat.normal_texture=ImageTexture.create_from_image(normal)
  model.material_override=mat
  # Overrides supersede surface overrides; assign to the mesh so converter sees the actual test material.
  model.material_override=null;sphere.material=mat
  await pair(world,model,"sentinel-"+str(i))
 for feature in ["emission","alpha"]:
  var node=MeshInstance3D.new();var mesh=BoxMesh.new();var mat=StandardMaterial3D.new();mesh.material=mat;node.mesh=mesh
  if feature=="emission":mat.emission_enabled=true;mat.emission=Color(1,.2,0)
  else:mat.transparency=BaseMaterial3D.TRANSPARENCY_ALPHA
  var errors=factory.convert_materials(node,[])
  var rejected=not errors.is_empty() and node.get_surface_override_material(0)==null
  rejection_checks.append({"feature":feature,"rejectedWithoutMutation":rejected})
  node.free()
  if not rejected:push_error("Unsupported feature escaped guard");quit(2);return
 var hashes={}
 for path in ["project.godot","scripts/material_converter.gd","scripts/visual_factory.gd","scripts/render_profile.gd","shaders/pilot_object.gdshader","tests/material_probe.gd","data/pilot_skin.json"]:hashes[path]=FileAccess.get_sha256("res://"+path)
 var report={"runtimeRejectionChecks":rejection_checks,"pairs":records,"assets":assets,"runtimeHashes":hashes,"engineVersion":Engine.get_version_info().string,"renderer":RenderingServer.get_current_rendering_method(),"device":RenderingServer.get_video_adapter_name(),"viewport":[root.get_texture().get_width(),root.get_texture().get_height()],"native":true}
 FileAccess.open(output+"/probe.json",FileAccess.WRITE).store_string(JSON.stringify(report,"  "))
 factory.release_templates();world.queue_free();await process_frame
 print("MATERIAL_PROBE_DONE "+output);quit()
