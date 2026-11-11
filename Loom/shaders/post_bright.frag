#version 450
// post_bright.frag — T3 单源亮部提取（公式逐字对齐迁移前 _BRIGHT / WGSL fs_bright）
//@@COMPAT@@

DECL_FRAG_UV
LOOM_FRAG_OUT

DECL_TEX2D(u_hdr, B_HDR);
DECL_SAMPLER(u_smp, B_SAMPLER);

layout(std140, binding = B_PARAMS) uniform Params {
    vec4 p0;   // (threshold, knee, exposure, 0)
    vec4 p1;   // (target_w, target_h, 0, 0)
} par;

void main() {
    vec2 uv = LOOM_FRAG_UV;
    // HDR 存 gamma 编码值 -> 反线性；再乘曝光（与 tonemap 同一曝光），阈值按曝光后线性亮度
    vec3 c = pow(max(SAMPLE2D(u_hdr, u_smp, uv).rgb, vec3(0.0)), vec3(2.2)) * par.p0.z;
    float l = dot(c, vec3(0.2126, 0.7152, 0.0722));
    float w = smoothstep(par.p0.x, par.p0.x + max(par.p0.y, 1e-4), l);
    frag_color = vec4(c * w, 1.0);
}
