shader_type spatial;
uniform float review_time = -1.0;
uniform float background_detail = 1.0;
render_mode unshaded,cull_disabled;
uniform bool orbital=false;
uniform sampler2D coffee_map : source_color, filter_linear_mipmap, repeat_enable;
uniform vec2 land_half_size=vec2(22.,18.);
uniform vec2 water_corner=vec2(-9.,8.);
varying vec3 world_position;
void vertex(){world_position=(MODEL_MATRIX*vec4(VERTEX,1.)).xyz;}
float hash(vec2 p){return fract(sin(dot(p,vec2(127.1,311.7)))*43758.5453);}
float noise(vec2 p){vec2 i=floor(p),f=fract(p);f=f*f*(3.-2.*f);return mix(mix(hash(i),hash(i+vec2(1,0)),f.x),mix(hash(i+vec2(0,1)),hash(i+vec2(1,1)),f.x),f.y);}
void fragment(){
 vec2 p=world_position.xz;
 bool in_rectangle=abs(p.x)<=land_half_size.x&&abs(p.y)<=land_half_size.y;
 bool in_inlet=p.x<water_corner.x&&p.y>water_corner.y;
 if(in_rectangle&&!in_inlet){discard;}
 if(orbital){
  vec3 color=mix(vec3(.005,.009,.018),vec3(.022,.035,.058),noise(p*.12));
  vec2 grid=p*3.2,i=floor(grid),f=fract(grid);
  vec2 offset=vec2(hash(i),hash(i+17.));
  float star=(1.-smoothstep(.013,.052,distance(f,offset)))*step(.91,hash(i+42.));
  color+=star*mix(vec3(.42,.65,.85),vec3(.93,.71,.48),hash(i+8.));ALBEDO=color;
 }else{
  vec2 uv=p/18.+vec2((review_time >= 0.0 ? review_time : TIME)*.0006,0.);
  vec2 warp=vec2(noise(p*.19),noise(p*.19+13.))*.014;
  ALBEDO=mix(vec3(.065,.028,.013),texture(coffee_map,uv+warp).rgb*.48,.55*background_detail);

 }
}
