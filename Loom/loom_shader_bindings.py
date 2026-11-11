# -*- coding: utf-8 -*-
"""loom_shader_bindings.py — T3c 最小落地：post 链绑定号**单点表**（2026-11-11）。

GL 与 VK 共用这一张表：着色器里只写 `layout(binding = B_HDR)`，构建期/GL 加载期展开成数字；
两端不允许各写一套数字。VK 侧 bind group layout 也引用本模块常量。
"""
import re

B_SCENE = 0      # 主 pass 场景 UBO（VK SceneC 就在 binding 0；GL 用 bind_to_uniform_block(0)）
B_HDR = 0        # 主输入纹理（tonemap: color.hdr；bright: color.hdr；down: bloom.half）
B_BLOOM = 1      # 第二输入纹理（tonemap: bloom 目标；其余 pass 复用同槽位）
B_SAMPLER = 2    # 采样器
B_PARAMS = 3     # std140 参数块（p0/p1）

_TABLE = {
    'B_SCENE': B_SCENE,
    'B_HDR': B_HDR,
    'B_BLOOM': B_BLOOM,
    'B_SAMPLER': B_SAMPLER,
    'B_PARAMS': B_PARAMS,
}


def expand(src):
    """把 B_xxx 展开成数字（按标识符边界，避免误伤其它名字）。"""
    def _sub(m):
        return str(_TABLE[m.group(0)])
    return re.sub(r"\bB_(SCENE|HDR|BLOOM|SAMPLER|PARAMS)\b", _sub, src)

# ---------------- T3c-3: 实例属性布局（GL/VK 共用同一张表）----------------
INSTANCE_STRIDE = 96           # T3c-3: 24 f32 / 实例（法线矩阵移到 GPU）
INSTANCE_LAYOUT = (
    (3, 'a_w0', 0),  (4, 'a_w1', 16), (5, 'a_w2', 32), (6, 'a_w3', 48),
    (7, 'a_sat', 64),
    (8, 'a_col', 80),
)

# 顶点属性（非实例）：pos/normal/color/uv —— VK 与 GL 用同一 location 表
VERTEX_LAYOUT = (
    (0, 'in_pos', 0, 12), (1, 'in_normal', 12, 12),
    (2, 'in_color', 24, 16), (13, 'in_uv', 40, 8),
)
VERTEX_STRIDE = 48

