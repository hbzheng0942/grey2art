shader_type spatial;
render_mode cull_disabled;
uniform vec4 base_color : source_color = vec4(0.08,0.42,0.6,0.8);
uniform vec4 deep_color : source_color = vec4(0.044,0.273,0.48,0.8);
uniform float flow_speed = 0.4;
uniform float amplitude = 0.05;
uniform float roughness : hint_range(0.0,1.0) = 0.18;
uniform vec2 surface_size = vec2(10.0);
uniform float shore_width = 0.8;
uniform float depth_distance = 0.8;
uniform bool use_shore_mask = false;
uniform sampler2D shore_mask : filter_linear_mipmap;
uniform bool use_normal_texture = false;
uniform sampler2D normal_texture : hint_normal, repeat_enable, filter_linear_mipmap;
varying vec2 surface;
void vertex() {
    surface = VERTEX.xz;
    VERTEX.y += amplitude * (sin(VERTEX.x*1.9+TIME*flow_speed) + sin(VERTEX.z*2.7-TIME*flow_speed*0.7));
    NORMAL = normalize(vec3(-amplitude*1.9*cos(VERTEX.x*1.9+TIME*flow_speed),1.0,-amplitude*2.7*cos(VERTEX.z*2.7-TIME*flow_speed*0.7)));
}
void fragment() {
    vec2 flow = vec2(sin(surface.x*1.9+TIME*flow_speed),cos(surface.y*2.7-TIME*flow_speed*0.7));
    if (use_normal_texture) {
        vec2 first = texture(normal_texture,surface*0.5+TIME*flow_speed*vec2(0.035,0.02)).rg*2.0-1.0;
        vec2 second = texture(normal_texture,surface*0.37+TIME*flow_speed*vec2(-0.025,0.03)).rg*2.0-1.0;
        vec2 slope = clamp((first+second)*0.35,vec2(-0.95),vec2(0.95));
        NORMAL_MAP = vec3(slope*0.5+0.5,sqrt(max(0.0,1.0-dot(slope,slope)))*0.5+0.5);
    } else {
        NORMAL_MAP = vec3(0.5+flow.x*0.06,0.5+flow.y*0.06,1.0);
    }
    float edge_distance = min(min(UV.x,1.0-UV.x)*surface_size.x,min(UV.y,1.0-UV.y)*surface_size.y);
    // Compatibility has no scene-depth sampling here. An authored red mask
    // encodes inland distance / depth_distance; otherwise the bounded edge is used.
    float inland_distance = use_shore_mask ? texture(shore_mask,UV).r*depth_distance : edge_distance;
    float shore = smoothstep(0.0,max(shore_width,0.0001),inland_distance);
    float depth = smoothstep(0.0,max(depth_distance,0.0001),inland_distance);
    vec4 water_color = mix(base_color,deep_color,depth);
    ALBEDO = water_color.rgb;
    ALPHA = water_color.a * mix(0.4,1.0,shore);
    ROUGHNESS = roughness;
    METALLIC = 0.15;
}
