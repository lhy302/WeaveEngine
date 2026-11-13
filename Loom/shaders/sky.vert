#version 450
// sky.vert — T3 单源天空盒顶点（GL 直接用同一份，VK 走 sky.vert.spv）
// 两端覆盖同一块全屏区域，差异只在顶点从哪来：
//   GL：loom_render 的 quad VBO（in_pos 0..1，画 6 顶点）
//   VK：无顶点缓冲，gl_VertexIndex 直接出全屏三角（画 3 顶点）
// 顶点输出 v_ndc = 该顶点的 NDC 位置（z=1 = 远平面），片段据此反投影。
//@@COMPAT@@

DECL_SKY_INPUT
layout(location = 0) out vec2 v_ndc;

void main() {
    vec2 p = SKY_VERT_NDC;
    v_ndc = p;
    gl_Position = vec4(p, 1.0, 1.0);
}
