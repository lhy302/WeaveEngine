#version 450
// shadow.vert — T3 单源阴影 pass 顶点（GL 直接用同一份，VK 走 shadow.vert.spv）
// 来源：loom_shaders._SHADOW_VERT（GL 现役）+ vk_renderer._SHADOW_VERT 的 vs 段（VK 现役）。
// 两端只有「光 VP 从哪来」不同：GL = 独立 uniform u_light_vp；VK = binding 0 的 ShadowU 块。
// 实例 world 矩阵两端口径一致：location 3..6 四个 vec4 -> mat4(a_w0..a_w3)。
//@@COMPAT@@

layout(location = 0) in vec3 in_pos;
layout(location = 3) in vec4 a_w0;
layout(location = 4) in vec4 a_w1;
layout(location = 5) in vec4 a_w2;
layout(location = 6) in vec4 a_w3;

layout(location = 0) out vec3 v_world_pos;

DECL_SHADOW_UNI

void main() {
    mat4 model = mat4(a_w0, a_w1, a_w2, a_w3);
    vec4 world = model * vec4(in_pos, 1.0);
    v_world_pos = world.xyz;
    gl_Position = SHADOW_VP * world;
}
