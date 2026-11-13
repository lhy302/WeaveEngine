#version 450
// sky.frag — T3 单源天空盒片段（GL 直接用同一份，VK 走 sky.frag.spv）
// 来源：loom_shaders._SKY_FRAG（GL）与 vk_renderer._SKY_WGSL 的 fs（VK），两式逐字一致：
//   clip = (ndc.x, ndc.y, 1, 1) -> world = clip @ inv(VP) -> dir = normalize(world.xyz/w - cam)
// 差异只在采样器声明（GL samplerCube / VK 分离 textureCube+sampler）与天空参数来源。
//@@COMPAT@@

DECL_SKY_UNI
DECL_TEXCUBE(u_skybox, SB_SKY_CUBE);
DECL_SAMPLER(s_sky, SB_SKY_SAMP);
LOOM_FRAG_OUT

layout(location = 0) in vec2 v_ndc;

void main() {
    // 行向量约定: clip = (ndc.x, ndc.y, 1.0, 1.0), world = clip @ inv(VP)
    // GLSL 是列主序, inv_vp * clip 等价 numpy 的 clip @ inv_vp（inv_vp 按行主序上传）
    vec4 clip = vec4(v_ndc.x, v_ndc.y, 1.0, 1.0);
    vec4 world = SKY_INV_VP * clip;
    vec3 dir = normalize(world.xyz / max(world.w, 1e-6) - SKY_CAM);
    vec3 col = SAMPLECUBE(u_skybox, s_sky, dir).rgb * SKY_TINT;
    frag_color = vec4(col, 1.0);
}
