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
# T3b (2026-11-13): 阴影 pass 顶点+片段已单源化 —— GL 与 VK 读同一份
# Loom/shaders/shadow.vert / shadow.frag（VK 走 glslang 出来的 .spv）。
# 由本文件末尾的 _shared_shader_src() 加载，这里不再保留第二份 GLSL 文本。


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
# T3b (2026-11-13): 天空盒顶点+片段已单源化 —— GL 与 VK 读同一份
# Loom/shaders/sky.vert / sky.frag（VK 走 glslang 出来的 .spv）。
# 由本文件末尾的 _shared_shader_src() 加载，这里不再保留第二份 GLSL 文本。
# 2026-11-11 T3c-1: 场景 block **由字段表生成**（不许手写第二份）
from loom_scene_ubo import glsl_block as _glsl_scene_block
from loom_shader_bindings import expand as _expand_bindings
_SCENE_UBO_GLSL = _expand_bindings(_glsl_scene_block())
from loom_shader_bindings import bucket_block_glsl as _bucket_block
_BUCKET_UBO_GLSL = _expand_bindings(_bucket_block())
from loom_shader_compat_src import compat_src as _compat_src


def _shared_shader_src(name):
    """T3b: 读 Loom/shaders/<name> 单源（GL 侧用；VK 侧走同一份源编译出的 .spv）。

    与 main.frag/main.vert 同款：展开 COMPAT，并把 #version 450 降到 GL 4.3 的 430。
    天空/阴影源里没有 SCENE/BUCKET 标记，故不替换那两个块。
    """
    import os
    base = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'shaders')
    with open(os.path.join(base, name), encoding='utf-8') as fh:
        src = fh.read()
    src = src.replace('//@@COMPAT@@', _compat_src())
    return src.replace('#version 450', '#version 430')


# T3b: 阴影 pass / 天空盒 = 单一来源（GL 与 VK 同一份 GLSL）
_SHADOW_VERT = _shared_shader_src('shadow.vert')
_SHADOW_FRAG = _shared_shader_src('shadow.frag')
_SKY_VERT = _shared_shader_src('sky.vert')
_SKY_FRAG = _shared_shader_src('sky.frag')


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

