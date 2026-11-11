#version 450
// post_tonemap.frag — T3 单源（GLSL -> glslang -> SPIR-V；GL 直接用同一份）
//@@COMPAT@@

DECL_FRAG_UV
LOOM_FRAG_OUT

DECL_TEX2D(u_hdr, B_HDR);      // color.hdr
DECL_TEX2D(u_bloom, B_BLOOM);  // bloom.quarter（档 2 时是 bloom.half）
DECL_SAMPLER(u_smp, B_SAMPLER);

layout(std140, binding = B_PARAMS) uniform Params {
    vec4 p0;   // (0, 0, strength, exposure)
    vec4 p1;   // (target_w, target_h, 0, 0)
} par;

void main() {
    vec2 uv = LOOM_FRAG_UV;
    // 与迁移前 loom_post_gl._TONEMAP / WGSL fs_tonemap **逐公式一致**：
    //   c = pow(hdr,2.2) + bloom*strength; c *= exposure; Reinhard; encode
    // 注意 bloom 本身不做 gamma 反线性（既有实现如此，改了会偏 1LSB 以上）。
    vec3 c = pow(max(SAMPLE2D(u_hdr, u_smp, uv).rgb, vec3(0.0)), vec3(2.2));
    c += SAMPLE2D(u_bloom, u_smp, uv).rgb * par.p0.z;
    c *= par.p0.w;
    c = c / (vec3(1.0) + c);
    frag_color = vec4(pow(max(c, vec3(0.0)), vec3(1.0 / 2.2)), 1.0);
}
