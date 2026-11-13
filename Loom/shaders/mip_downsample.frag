#version 450
// mip_downsample.frag — T3 单源登记：VK mip 逐级降采样（VK 走 mip_downsample.frag.spv）
// 来源：vk_renderer._MIP_WGSL（14 行手写 WGSL）。
// ★ GL 侧**没有对应实现**：GL 的 mip 由驱动 glGenerateMipmap（moderngl texture.build_mipmaps）
//   在 GPU 内部完成，没有可单源化的 shader 阶段。此文件只服务 VK，计入 T2 差异清单。
// 顶点阶段复用 post_fullscreen.vert（全屏三角 + v_uv，本片段用 gl_FragCoord 不读 v_uv）。
//@@COMPAT@@

DECL_TEX2D(t_src, 0);
DECL_SAMPLER(s_src, 1);
LOOM_FRAG_OUT

void main() {
    // 目标 mip 尺寸 = 源的一半；uv 必须按**目标**像素归一（按源归一只能采到 1/4 区域）
    vec2 dst = max(vec2(textureSize(t_src, 0)) * 0.5, vec2(1.0));
    frag_color = SAMPLE2D_LOD(t_src, s_src, gl_FragCoord.xy / dst, 0.0);
}
