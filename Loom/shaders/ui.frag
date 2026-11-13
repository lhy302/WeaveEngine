#version 450
// ui.frag — T3 单源 UI 片段（2026-11-13）：屏幕 UI 与 world Canvas **共用这一份**
//   GL：loom_shaders._HUD_FRAG / _WORLD_UI_FRAG 都从本文件加载
//   VK：glslang -> ui.frag.spv，两条 UI 管线共用同一模块
// 语义与迁移前逐字一致：
//   · 屏幕 UI   ：texture(u_tex, v_uv) * 颜色（GL 用 uniform u_color；VK 用逐顶点色 v_color）
//   · world Canvas：texture(u_tex, v_uv)（tint 恒白，乘 1.0 不改变任何位）
//@@COMPAT@@

DECL_TEX2D(u_tex, SB_UI_TEX);
DECL_SAMPLER(s_ui, SB_UI_SAMP);
DECL_UI_FRAG_UNI
DECL_UI_FRAG_IN
LOOM_FRAG_OUT

void main() {
    frag_color = SAMPLE2D(u_tex, s_ui, v_uv) * UI_TINT;
}
