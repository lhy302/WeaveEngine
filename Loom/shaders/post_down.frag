#version 450
// post_down.frag — T3 单源降采样（4-tap，公式逐字对齐迁移前 _DOWN / WGSL fs_down）
//@@COMPAT@@

DECL_FRAG_UV
LOOM_FRAG_OUT

DECL_TEX2D(u_tex, B_HDR);
DECL_SAMPLER(u_smp, B_SAMPLER);

layout(std140, binding = B_PARAMS) uniform Params {
    vec4 p0;   // 未用
    vec4 p1;   // (target_w, target_h, 1/src_w, 1/src_h)
} par;

void main() {
    vec2 uv = LOOM_FRAG_UV;
    vec2 o = par.p1.zw;
    vec3 c = SAMPLE2D(u_tex, u_smp, uv + vec2(-o.x, -o.y)).rgb
           + SAMPLE2D(u_tex, u_smp, uv + vec2( o.x, -o.y)).rgb
           + SAMPLE2D(u_tex, u_smp, uv + vec2(-o.x,  o.y)).rgb
           + SAMPLE2D(u_tex, u_smp, uv + vec2( o.x,  o.y)).rgb;
    frag_color = vec4(c * 0.25, 1.0);
}
