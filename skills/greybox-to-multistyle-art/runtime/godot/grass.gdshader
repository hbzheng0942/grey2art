shader_type spatial;
render_mode cull_disabled;
uniform vec4 base_color : source_color = vec4(0.22,0.5,0.13,1.0);
uniform float wind = 0.12;
void vertex() {
    float tip = 1.0-UV.y;
    VERTEX.x += sin(TIME*1.8+MODEL_MATRIX[3].x*0.8+MODEL_MATRIX[3].z)*wind*tip*tip;
}
void fragment() {
    float width = mix(0.04,0.5,UV.y);
    ALPHA = 1.0-step(width,abs(UV.x-0.5));
    ALPHA_SCISSOR_THRESHOLD = 0.5;
    ALBEDO = base_color.rgb*mix(1.25,0.7,UV.y);
    ROUGHNESS = 0.9;
}
