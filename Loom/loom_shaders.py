# -*- coding: utf-8 -*-
"""loom_shaders.py — 从 engine.py 抽取的全部 GLSL 着色器源码常量。

原属 engine.py 45–307 行（着色器定义段）。纯字符串常量，零运行时依赖。
engine.py 通过 `from loom_shaders import *` 重新导出这些名字，
以保持既有 `from engine import _VERT_SRC` 之类的引用完全兼容。
"""

# ================ 主渲染着色器 (顶点 + 片元) ================
# 光照模型 (M20): Blinn-Phong 漫反射+镜面高光 + 半球环境光 + 边缘光(菲涅尔) + gamma 校正.
# 之前的纯兰伯特(0.2+0.8*diff)无观察方向项, 立方体相邻面亮度可能完全相等(如 -Y/+Z 都停在环境光),
# 导致分不出边缘. 现在: 高光/边缘光看观察角度, 半球环境光按法线朝向分离相邻面.

# ================ 主渲染着色器 (顶点 + 片元) ================
# 主片段 **单一来源** = Loom/shaders/main.frag（T3a-3, 2026-11-13）：
# GL 直接用同一份 GLSL（本文件末尾 _shared_frag_src() 加载），VK 用 glslang 编译出的
# main.frag.spv。这里不再保留第二份 GLSL 文本，避免两端漂移。

# ================ HUD 正交着色器 (文字纹理 quad) ================
_HUD_VERT = """#version 330
in vec2 in_pos;
in vec2 in_uv;
out vec2 v_uv;
uniform vec2 u_origin;
uniform vec2 u_size;
void main() {
    gl_Position = vec4(in_pos * u_size + u_origin, 0.0, 1.0);
    v_uv = in_uv;
}"""

_HUD_FRAG = """#version 330
in vec2 v_uv;
uniform sampler2D u_tex;
uniform vec4 u_color;            // M33: 运行时 UI 纯色矩形用 (文字传白=不变)
out vec4 frag_color;
void main() {
    frag_color = texture(u_tex, v_uv) * u_color;
}"""

# ================ World Space UI 着色器 (2026-10-19 第1档序3阶段4) ================
# 用途：把离屏渲染的 Canvas 纹理贴到 3D 世界的一块 quad 上。
# 4 个顶点是世界坐标（CPU 侧按 billboard 或 target 旋转算好），view_proj 投影。
_WORLD_UI_VERT = """#version 330
in vec3 in_world_pos;
in vec2 in_uv;
out vec2 v_uv;
uniform mat4 u_view_proj;
void main() {
    gl_Position = u_view_proj * vec4(in_world_pos, 1.0);
    v_uv = in_uv;
}"""

_WORLD_UI_FRAG = """#version 330
in vec2 v_uv;
uniform sampler2D u_tex;
out vec4 frag_color;
void main() {
    frag_color = texture(u_tex, v_uv);
}"""

# ================ 线条着色器 (逐顶点颜色, gizmo/网格/选中框用) ================
# core profile 线宽仅保证 1px; gizmo 端点用投影小方块 (三角形) 增强可点性
_LINE_VERT = """#version 330
in vec3 in_pos;
in vec4 in_color;
uniform mat4 u_view_proj;
out vec4 v_color;
void main() {
    gl_Position = u_view_proj * vec4(in_pos, 1.0);
    v_color = in_color;
}"""

_LINE_FRAG = """#version 330
in vec4 v_color;
out vec4 frag_color;
void main() {
    frag_color = v_color;
}"""

# ================ 阴影深度 pass 着色器 (M29) ================
# 只输出深度. 顶点着色器声明与主 VAO 相同的三个输入 (交错 '3f 3f 4f'),
# 阴影 VAO 才能用与主 VAO 相同的 VBO/布局 (moderngl VAO 与创建它的程序绑定,
# 不能拿主 prog 的 VAO 去渲染阴影 prog —— 会什么都不画).
# 深度贴图存真实深度 (近=小, 默认 gl_FragCoord.z / 点光=距离/far):
# 本驱动阴影采样实测 stored>=ref 为照亮, 主 pass 传 ref = depth-bias,
# 故遮挡面(stored)在片元之后(stored>=depth-bias)=照亮. 反转深度方案已废弃.
_SHADOW_VERT = """#version 330
in vec3 in_pos;
// A2 (2026-08-29): 阴影 pass 同样走实例化 (world 矩阵 per-instance, 光 VP 仍 uniform)
in vec4 a_w0; in vec4 a_w1; in vec4 a_w2; in vec4 a_w3;
uniform mat4 u_light_vp;
out vec3 v_world_pos;
void main() {
    mat4 u_model = mat4(a_w0, a_w1, a_w2, a_w3);
    vec4 world = u_model * vec4(in_pos, 1.0);
    v_world_pos = world.xyz;
    gl_Position = u_light_vp * world;
}"""

_SHADOW_FRAG = """#version 330
uniform int u_depth_kind;      // 0= 默认深度(z), 1= 到光源距离 (点光)
uniform vec3 u_light_pos;
uniform float u_light_far;     // 点光阴影远平面（阴影 pass 独立程序，不进 Scene UBO）
in vec3 v_world_pos;
void main() {
    // 存真实深度 (近=小): 本驱动阴影采样器实测固定比较 stored >= ref (忽略 compare_func),
    // 主 pass 传 ref = depth - bias, 遮挡面在片元之后 => stored >= depth-bias => 照亮.
    // 深度测试用默认 GL_LESS (近小大远), 近的遮挡面正确覆盖远的.
    // 必须无条件写 gl_FragDepth (分支不取时值未定义, 某些驱动写 0.0).
    if (u_depth_kind > 0) {
        gl_FragDepth = clamp(length(v_world_pos - u_light_pos) / u_light_far, 0.0, 1.0);
    } else {
        gl_FragDepth = gl_FragCoord.z;
    }
}"""


# ================ 通用常量 (2026-11-09 人类裁决 Q2=A: 收敛到一处) ================
# 主 pass 清屏底色 (RGBA, alpha=1.0)。编辑器 / VK / GL 播放器必须共用这一个值 ——
# 旧实现三处字面值 (VK 与编辑器 0.10/0.12/0.16, GL 播放器 0.05/0.05/0.1), 于是同一场景
# 在没有天空盒时 GL/VK 底色不一致, 离屏 A/B 基线必然对不上。
CLEAR_COLOR_RGBA = (0.10, 0.12, 0.16, 1.0)


# ================ 2026-10-19 第1档序13 天空盒 (A1 全屏 quad + 反投影) ================
# 用户拍板 A1+B1:
#   A1: 全屏 quad + fragment 反投影（性能最好，单次全屏绘制）
#   B1: 先画几何后画天空（depth==1.0 才画，无 overdraw）
# 反投影数学（与 engine._ray_from_screen 逐位一致: 行向量约定 clip @ inv(VP) = world）:
#   frag NDC(x, y, 1.0) -> world = clip @ inv(VP) -> dir = normalize(world.xyz/w - cam_pos)
# 复用 engine._quad_vbo（2f 2f = pos + uv，其中 pos 是 0..1 归一化 quad）
_SKY_VERT = """#version 330
in vec2 in_pos;   // quad 顶点位置 (0..1 归一化)
out vec2 v_ndc;
void main() {
    // 全屏 quad: 0..1 -> NDC -1..1, z=1.0 = 远平面
    v_ndc = in_pos * 2.0 - 1.0;
    gl_Position = vec4(v_ndc, 1.0, 1.0);
}"""

_SKY_FRAG = """#version 330
in vec2 v_ndc;
uniform mat4 u_inv_view_proj;   // CPU 侧算好的 inv(VP)（行向量约定）
uniform vec3 u_camera_pos;
uniform samplerCube u_skybox;
uniform vec3 u_skybox_tint;
out vec4 frag_color;
void main() {
    // 行向量约定: clip = (ndc.x, ndc.y, 1.0, 1.0), world = clip @ inv(VP)
    // GLSL 是列主序, u_inv_view_proj * v 等价 numpy 的 v @ M（M 是行主序存储）
    vec4 clip = vec4(v_ndc.x, v_ndc.y, 1.0, 1.0);
    vec4 world = u_inv_view_proj * clip;
    vec3 dir = normalize(world.xyz / max(world.w, 1e-6) - u_camera_pos);
    vec3 col = texture(u_skybox, dir).rgb * u_skybox_tint;
    frag_color = vec4(col, 1.0);
}"""
# 2026-11-11 T3c-1: 场景 block **由字段表生成**（不许手写第二份）
from loom_scene_ubo import glsl_block as _glsl_scene_block
from loom_shader_bindings import expand as _expand_bindings
_SCENE_UBO_GLSL = _expand_bindings(_glsl_scene_block())
from loom_shader_bindings import bucket_block_glsl as _bucket_block
_BUCKET_UBO_GLSL = _expand_bindings(_bucket_block())
from loom_shader_compat_src import compat_src as _compat_src


def _shared_frag_src():
    """T3a-3: GL 主 pass 片段读**同一份** shaders/main.frag（VK 走 SPIR-V）。

    与 main.vert 同款：替换构建标记，并把 #version 450 降到 GL 4.3 的 430。
    本文件不再保存第二份 GLSL 文本（单一来源 = shaders/main.frag）。
    """
    import os
    base = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'shaders')
    with open(os.path.join(base, 'main.frag'), encoding='utf-8') as fh:
        src = fh.read()
    src = src.replace('//@@COMPAT@@', _compat_src())
    src = src.replace('//@@SCENE_UBO@@', _SCENE_UBO_GLSL)
    src = src.replace('//@@BUCKET_UBO@@', _BUCKET_UBO_GLSL)
    return src.replace('#version 450', '#version 430')


_FRAG_SRC = _shared_frag_src()
# _VERT_SRC 由 _shared_vert_src() 在文件末尾加载（单源 main.vert）


def _shared_vert_src():
    """T3a Phase-2a: GL 主 pass 顶点着色器读**同一份** shaders/main.vert（VK 走 SPIR-V）。"""
    import os
    base = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'shaders')
    with open(os.path.join(base, 'main.vert'), encoding='utf-8') as fh:
        src = fh.read()
    with open(os.path.join(base, 'loom_shader_compat.glsl'), encoding='utf-8') as fh:
        compat = fh.read()
    src = src.replace('//@@COMPAT@@', compat)
    src = src.replace('//@@SCENE_UBO@@', _SCENE_UBO_GLSL)
    return src.replace('#version 450', '#version 430')


_VERT_SRC = _shared_vert_src()

