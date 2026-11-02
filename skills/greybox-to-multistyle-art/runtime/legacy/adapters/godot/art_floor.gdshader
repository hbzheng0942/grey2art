shader_type spatial;
render_mode cull_disabled;
uniform bool orbital=false;
uniform bool real_bevel=false;
uniform float seam_strength=1.0;
uniform float grain_strength=1.0;
uniform float variation_strength=1.0;
uniform float lane_mark_strength=1.0;
uniform float roughness_multiplier=1.0;
uniform vec4 hole_a=vec4(0.0);
uniform vec4 hole_b=vec4(0.0);
uniform vec2 land_half_size=vec2(22.0,18.0);
uniform vec2 water_corner=vec2(-9.0,8.0);
uniform bool show_grid=false;
uniform float shore_margin=0.18;
varying vec3 world_position;
void vertex(){world_position=(MODEL_MATRIX*vec4(VERTEX,1.0)).xyz;}
vec3 to_linear(vec3 c){return mix(pow((c+vec3(.055))/1.055,vec3(2.4)),c/12.92,lessThan(c,vec3(.04045)));}
float road_sdf(vec2 p){float radial=length(p-vec2(0,-3));float d=abs(radial-6.3)-1.50;vec2 q=abs(p-vec2(0,4.3))-vec2(19.7,1.5);d=min(d,max(q.x,q.y));q=abs(p-vec2(-7.3,-9.8))-vec2(1.45,7.8);d=min(d,max(q.x,q.y));q=abs(p-vec2(6.5,8.9))-vec2(1.45,8.8);return min(d,max(q.x,q.y));}
float hash(vec2 p){return fract(sin(dot(p,vec2(127.1,311.7)))*43758.5453);}
float noise(vec2 p){vec2 i=floor(p),f=fract(p);f=f*f*(3.0-2.0*f);return mix(mix(hash(i),hash(i+vec2(1,0)),f.x),mix(hash(i+vec2(0,1)),hash(i+vec2(1,1)),f.x),f.y);}
float rectmask(vec2 p,vec2 c,vec2 h){vec2 q=abs(p-c)-h;return 1.0-smoothstep(0.0,0.035,max(q.x,q.y));}
void fragment(){
 vec2 p=world_position.xz;
 if(p.x<water_corner.x&&p.y>water_corner.y){discard;}
 if(hole_a.w>0.5&&distance(p,hole_a.xy)<hole_a.z){discard;}
 if(hole_b.w>0.5&&distance(p,hole_b.xy)<hole_b.z){discard;}
 float radial=length(p-vec2(0,-3));
 float plaza=1.0-smoothstep(4.55,4.65,radial);
 float ring=1.0-smoothstep(1.45,1.52,abs(radial-6.30));
 float road=max(ring,rectmask(p,vec2(0,4.30),vec2(19.7,1.50)));
 road=max(road,rectmask(p,vec2(-7.30,-9.8),vec2(1.45,7.8)));
 road=max(road,rectmask(p,vec2(6.5,8.9),vec2(1.45,8.8)));
 float tile_scale=orbital?0.50:1.35;
 vec2 grid=(p+land_half_size)*tile_scale;
 vec2 cell=floor(grid),f=fract(grid);
 float edge=min(min(f.x,1.-f.x),min(f.y,1.-f.y));
 float seam=1.0-smoothstep(.004,.015,edge);
 float bevel=1.0-smoothstep(.015,.04,edge);
 float grain=noise(p*12.)*.5+noise(p*3.)*.3+noise(p*43.)*.2;
 float variation=(hash(cell)-.5)*(orbital?.055:.08)*variation_strength;
 vec3 cream=orbital?vec3(.63,.65,.64):vec3(.77,.72,.62);
 vec3 plaza_color=orbital?vec3(.68,.68,.63):vec3(.84,.75,.59);
 vec3 lane_color=orbital?vec3(.24,.28,.32):vec3(.30,.42,.60);
 vec3 color=mix(cream,plaza_color,plaza)+variation+(grain-.5)*.055*grain_strength;
 color*=1.-seam*.29*seam_strength-bevel*.09*seam_strength;
 vec2 blue_tile=abs(fract((p+land_half_size)*1.35)-.5);
 float blue_seam=smoothstep(.474,.494,max(blue_tile.x,blue_tile.y));
 color=mix(color,lane_color*(1.-blue_seam*(orbital?.05:.22)*seam_strength)+(grain-.5)*.012*grain_strength,road);
 // Road locations match the original shader; only surfaces and edge treatment change.
 float ring_edge=(1.-smoothstep(.035,.10,abs(abs(radial-6.30)-1.50)));
 float road_edge=(1.-smoothstep(.025,.075,abs(abs(p.y-4.3)-1.50)))*rectmask(p,vec2(0,4.3),vec2(19.7,1.8));
 float spine_edge=(1.-smoothstep(.025,.075,abs(abs(p.x+7.3)-1.45)))*rectmask(p,vec2(-7.3,-9.8),vec2(1.7,7.8));
 vec3 trim=orbital?vec3(.82,.40,.055):vec3(.72,.53,.25);
 color=mix(color,trim,(1.-smoothstep(.025,.09,abs(road_sdf(p))))*.8);
 float dash=step(.45,fract(p.x*.40));
 float lane=(1.-smoothstep(.025,.050,abs(p.y-4.3)))*dash*rectmask(p,vec2(0,4.3),vec2(19,1));
 lane=max(lane,(1.-smoothstep(.025,.05,abs(p.x+7.3)))*step(.45,fract(p.y*.4))*rectmask(p,vec2(-7.3,-9.8),vec2(1,7.8)));
 float angle=atan(p.y+3.,p.x);
 lane=max(lane,(1.-smoothstep(.025,.06,abs(radial-6.3)))*step(.47,fract(angle*8.0)));
 color=mix(color,trim,lane*lane_mark_strength);
 float crossing=max(rectmask(p,vec2(-8.8,4.3),vec2(.9,1.36)),rectmask(p,vec2(8,4.3),vec2(.9,1.36)));
 crossing=max(crossing,rectmask(p,vec2(-7.3,-3.2),vec2(1.35,.85)));
 color=mix(color,orbital?vec3(.80,.54,.15):vec3(.85,.73,.49),crossing*step(.43,fract(p.y*1.5))*.95);
 if(orbital){
  // Service-panel insets, corner fasteners, subtle abrasion and hazard stencils.
  float panel=rectmask(f,vec2(.53,.52),vec2(.30,.33))*step(.55,hash(cell+11.))*(1.-road);
  float panel_edge=panel*(1.-rectmask(f,vec2(.53,.52),vec2(.285,.315)));
  color=mix(color,vec3(.35,.38,.38),panel_edge*.75);
  float scuff=smoothstep(.62,.80,noise(p*2.2+vec2(0,noise(p*.7))))*smoothstep(.60,.8,hash(cell+9.))*(1.-road);
  color=mix(color,vec3(.46,.45,.40),scuff*.25);
  float hazard=rectmask(f,vec2(.82,.16),vec2(.095,.075))*step(.80,hash(cell+2.))*(1.-road)*step(.45,fract((p.x+p.y)*3.));
  color=mix(color,vec3(.64,.49,.27),hazard*.65);
  vec2 bolt=abs(f-.075);float screw=(1.-smoothstep(.007,.014,length(bolt)))*(1.-road);
  color=mix(color,vec3(.12,.14,.16),screw);
  float inset=rectmask(f,vec2(.25,.25),vec2(.09,.045))*step(.82,hash(cell))*(1.-road);
  float grating=step(.45,fract(p.x*24.));color=mix(color,vec3(.16,.18,.19),inset*grating*.7);
 }
 if(show_grid){float g=step(.49,max(abs(fract(p)-.5).x,abs(fract(p)-.5).y));color=mix(color,vec3(.15,.75,.65),g*.35);}
 // Tile-edge slopes in world space: bevel highlights and recessed joints respond to real light.
 vec2 edge_gradient=vec2(sign(.5-f.x)*(1.-smoothstep(.008,.045,min(f.x,1.-f.x))),sign(.5-f.y)*(1.-smoothstep(.008,.045,min(f.y,1.-f.y))));
 vec3 world_n=normalize(vec3(-edge_gradient.x*(orbital?.22:.32),1.,-edge_gradient.y*(orbital?.22:.32)));
 if(!real_bevel){NORMAL=normalize((VIEW_MATRIX*vec4(world_n,0.)).xyz);}
 ALBEDO=OUTPUT_IS_SRGB?color:to_linear(color);ROUGHNESS=clamp((orbital?.64:mix(.64,.43,road))*roughness_multiplier,0.0,1.0);METALLIC=orbital?.22:0.;SPECULAR=.35;
}

