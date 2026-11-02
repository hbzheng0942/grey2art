shader_type spatial;
uniform vec4 base_color : source_color = vec4(0.3,0.36,0.2,1.0);
uniform vec4 secondary_color : source_color = vec4(0.5,0.45,0.28,1.0);
uniform float tile_scale = 2.0;
uniform bool use_texture = false;
uniform bool use_secondary_texture = false;
uniform bool use_blend_mask = false;
uniform sampler2D albedo_texture : source_color, repeat_enable;
uniform sampler2D secondary_texture : source_color, repeat_enable;
uniform sampler2D blend_mask : filter_linear_mipmap;
varying vec2 surface;
void vertex() { surface = (MODEL_MATRIX*vec4(VERTEX,1.0)).xz; }
void fragment() {
    float blend = 0.5+0.25*sin(surface.x*tile_scale)+0.25*sin(surface.y*tile_scale*0.73);
    if (use_blend_mask) { blend = texture(blend_mask,UV).r; }
    vec3 first = use_texture ? texture(albedo_texture,surface*tile_scale).rgb*base_color.rgb : base_color.rgb;
    vec3 second = use_secondary_texture ? texture(secondary_texture,surface*tile_scale).rgb*secondary_color.rgb : secondary_color.rgb;
    ALBEDO = mix(first,second,blend);
    ROUGHNESS = 0.9;
}
