#version 450
// post_fullscreen.vert — T3 单源全屏三角（GL: gl_VertexID / VK: gl_VertexIndex）
//@@COMPAT@@

layout(location = 0) out vec2 v_uv;

void main() {
    vec2 p = vec2((LOOM_VERTEX_ID == 1) ? 3.0 : -1.0,
                  (LOOM_VERTEX_ID == 2) ? 3.0 : -1.0);
    v_uv = p * 0.5 + 0.5;
    gl_Position = vec4(p, 0.0, 1.0);
}
