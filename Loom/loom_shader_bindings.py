# -*- coding: utf-8 -*-
"""loom_shader_bindings.py — T3c 最小落地：post 链绑定号**单点表**（2026-11-11）。

GL 与 VK 共用这一张表：着色器里只写 `layout(binding = B_HDR)`，构建期/GL 加载期展开成数字；
两端不允许各写一套数字。VK 侧 bind group layout 也引用本模块常量。
"""
import re

B_BUCKET = 1     # 桶级 UBO（GL 绑定点；VK 在 binding 8，字段布局一致）
B_SCENE = 0      # 主 pass 场景 UBO（VK SceneC 就在 binding 0；GL 用 bind_to_uniform_block(0)）
B_HDR = 0        # 主输入纹理（tonemap: color.hdr；bright: color.hdr；down: bloom.half）
B_BLOOM = 1      # 第二输入纹理（tonemap: bloom 目标；其余 pass 复用同槽位）
B_SAMPLER = 2    # 采样器
B_PARAMS = 3     # std140 参数块（p0/p1）

_TABLE = {
    'B_SCENE': B_SCENE,
    'B_BUCKET': B_BUCKET,
    'B_HDR': B_HDR,
    'B_BLOOM': B_BLOOM,
    'B_SAMPLER': B_SAMPLER,
    'B_PARAMS': B_PARAMS,
}


def expand(src):
    """把 B_xxx 展开成数字（按标识符边界，避免误伤其它名字）。"""
    def _sub(m):
        return str(_TABLE[m.group(0)])
    return re.sub(r"\bB_(SCENE|BUCKET|HDR|BLOOM|SAMPLER|PARAMS)\b", _sub, src)

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


# ---------------- T3c-2a: 桶级参数（GL/VK 同一张表）----------------
BUCKET_FIELDS = (
    ('metallic', 0), ('roughness', 4), ('pbr', 8),
    ('has_normal_map', 12), ('has_env', 16), ('env_max_lod', 20),
    ('pad0', 24), ('pad1', 28),
)
BUCKET_FLOATS = 8
BUCKET_BYTES = 32


def bucket_block_glsl():
    """由表生成 GL 的桶级 UBO 声明（字段名/顺序与 VK Bucket 一致）。"""
    return (
        # 绑定号走 compat 的 SB_BUCKET（GL=1 绑定点 / VK=8 descriptor）；
        # 不能写死 B_BUCKET —— 它只是 GL 侧的绑定点号，VK 的 SPIR-V 会落到 1 号与 t_shadow 冲突。
        "layout(std140, binding = SB_BUCKET) uniform Bucket {\n"
        "    float metallic;\n"
        "    float roughness;\n"
        "    float pbr;\n"
        "    float has_normal_map;\n"
        "    float has_env;\n"
        "    float env_max_lod;\n"
        "    float pad0;\n"
        "    float pad1;\n"
        "} bkt;\n")


def assert_bucket_layout():
    assert len(BUCKET_FIELDS) * 4 == BUCKET_BYTES
    assert [off for _n, off in BUCKET_FIELDS] == [i * 4 for i in range(BUCKET_FLOATS)]
    return BUCKET_BYTES

