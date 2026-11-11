#version 450
// main.vert — T3a Phase-2a 单源主 pass 顶点着色器（GL 直接用同一份，VK 走 SPIR-V）
//@@COMPAT@@
//@@SCENE_UBO@@

layout(location = 0) in vec3 in_pos;
layout(location = 1) in vec3 in_normal;
layout(location = 2) in vec4 in_color;
layout(location = 13) in vec2 in_uv;
layout(location = 3) in vec4 a_w0;
layout(location = 4) in vec4 a_w1;
layout(location = 5) in vec4 a_w2;
layout(location = 6) in vec4 a_w3;
layout(location = 7) in vec4 a_sat;
layout(location = 8) in vec4 a_col;

layout(location = 0) out vec4 v_color;
layout(location = 1) out vec3 v_normal;
layout(location = 2) out vec3 v_world_pos;
layout(location = 3) out float v_sat;
layout(location = 4) out vec4 v_matv;
layout(location = 5) out vec2 v_uv;

void main() {
    mat4 model = mat4(a_w0, a_w1, a_w2, a_w3);   // 引擎行主序 -> mat4 列收参 = M^T（与旧实现逐位一致）
    vec4 world = model * vec4(in_pos, 1.0);
    gl_Position = u.mvp * world;
    // 法线变换: 逆转置（与旧 GL / VK 逐位一致；VK 由伴随矩阵改为 GLSL inverse）
    v_normal = transpose(inverse(mat3(model))) * in_normal;
    v_world_pos = world.xyz;
    v_color = (a_col.w > 0.5) ? vec4(a_col.rgb, 1.0) : in_color;
    v_sat = a_sat.x;
    v_matv = a_sat;
    v_uv = in_uv;
}
