shader_type spatial;
render_mode cull_disabled;
uniform sampler2D albedo_map : source_color, filter_linear_mipmap;
uniform sampler2D roughness_map : filter_linear_mipmap;
uniform sampler2D metallic_map : filter_linear_mipmap;
uniform sampler2D normal_map : hint_normal, filter_linear_mipmap;
uniform vec4 base_color : source_color = vec4(1.0);
uniform bool has_albedo = false;
uniform bool has_roughness = false;
uniform bool has_metallic = false;
uniform bool has_normal = false;
uniform vec4 roughness_channel = vec4(0.0,1.0,0.0,0.0);
uniform vec4 metallic_channel = vec4(0.0,0.0,1.0,0.0);
uniform float surface_specular = 0.5;
uniform vec3 uv_scale = vec3(1.0);
uniform vec3 uv_offset = vec3(0.0);
uniform float surface_roughness = 0.65;
uniform float surface_metallic = 0.0;
uniform float normal_strength = 1.0;
uniform vec4 hole_a = vec4(0.0);
uniform vec4 hole_b = vec4(0.0);
uniform float occlusion_fade = 0.0;
varying vec3 world_position;
void vertex(){world_position=(MODEL_MATRIX*vec4(VERTEX,1.0)).xyz;UV=UV*uv_scale.xy+uv_offset.xy;}
void fragment(){
 if(world_position.y < -0.025){
  bool inside_a=hole_a.w>0.5 && distance(world_position.xz,hole_a.xy)<hole_a.z;
  bool inside_b=hole_b.w>0.5 && distance(world_position.xz,hole_b.xy)<hole_b.z;
  if((!inside_a && !inside_b) || world_position.y < -2.60){discard;}
 }
 if(occlusion_fade>0.001){
  vec2 pixel=floor(FRAGCOORD.xy);
  float dither=fract(52.9829189*fract(dot(pixel,vec2(0.06711056,0.00583715))));
  if(dither<occlusion_fade){discard;}
 }
 vec3 color=base_color.rgb;
 if(has_albedo){color*=texture(albedo_map,UV).rgb;}
 ALBEDO=color*mix(1.0,0.38,clamp(-world_position.y/2.6,0.0,1.0));
 ROUGHNESS=has_roughness ? dot(texture(roughness_map,UV),roughness_channel)*surface_roughness : surface_roughness;
 SPECULAR=surface_specular;
 METALLIC=has_metallic ? dot(texture(metallic_map,UV),metallic_channel)*surface_metallic : surface_metallic;
 if(has_normal){NORMAL_MAP=texture(normal_map,UV).rgb;NORMAL_MAP_DEPTH=normal_strength;}
}
