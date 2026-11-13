#version 450
// shadow.frag — T3 单源阴影 pass 片段（GL 直接用同一份，VK 走 shadow.frag.spv）
// 来源：loom_shaders._SHADOW_FRAG（GL）+ vk_renderer._SHADOW_VERT 的 fs 段（VK）。
// 语义：深度 pass 只输出一个深度值（近=小）。
//   · 模式 0（平行光 / 点光的面）：窗口深度（gl_FragCoord.z）
//   · 模式 1（点光）：到光源距离 / far
// 产物落点不同：GL 有深度附件 -> gl_FragDepth；VK 是 r32float 颜色附件 -> frag_color.r。
//@@COMPAT@@

layout(location = 0) in vec3 v_world_pos;

DECL_SHADOW_UNI
DECL_SHADOW_PARAMS
DECL_SHADOW_OUT

void main() {
    // 必须无条件产出一个值（旧 GL 注释：分支不取时 gl_FragDepth 未定义，某些驱动写 0）。
    float d;
    if (SHADOW_IS_DISTANCE) {
        d = clamp(length(v_world_pos - SHADOW_LIGHT_POS) / SHADOW_FAR, 0.0, 1.0);
    } else {
        d = SHADOW_STAGE_DEPTH;
    }
    SHADOW_STORE_DEPTH(d);
}
