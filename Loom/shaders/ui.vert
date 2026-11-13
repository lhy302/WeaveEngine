#version 450
// ui.vert — T3 单源 UI 顶点（2026-11-13）：屏幕 UI 与 world Canvas **共用这一份**
//   GL：loom_shaders._HUD_VERT / _WORLD_UI_VERT 都从本文件加载（moderngl 各编一个 program）
//   VK：glslang -> ui.vert.spv，VkUIPipeline / VkWorldUIPipeline 共用同一模块
// 两条路径由 UI_IS_WORLD 区分（compat 吸收差异）：
//   · 屏幕 UI   ：像素坐标 -> NDC（GL 侧仍是 u_origin/u_size 的既有算式，逐字未改）
//   · world Canvas：世界坐标 * VP
// 顶点输入：GL 用既有的 in_pos(2f)/in_world_pos(3f)/in_uv(2f) 三个名字；
//           VK 统一成 pos3+uv2+color4 的 36B 布局（屏幕 UI 的 z 恒 0，world 的 color 恒白）。
//@@COMPAT@@

DECL_UI_VERT_UNI
DECL_UI_INPUT
DECL_UI_VARYINGS

void main() {
    gl_Position = UI_IS_WORLD ? UI_WORLD_CLIP : UI_SCREEN_CLIP;
    UI_EMIT_VARYINGS
}
