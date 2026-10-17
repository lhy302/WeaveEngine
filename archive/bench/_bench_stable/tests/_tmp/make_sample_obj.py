# -*- coding: utf-8 -*-
"""make_sample_obj.py — 生成 A03 测试用的示例 .obj (2026-08-15).

用引擎自带网格生成器导出 (绕序与引擎 front_face='cw' 一致, 保证导入后正面可见).
输出到 Loom\保存\示例obj\ : 立方体.obj / 低多边形球.obj / 金字塔.obj / 环面.obj
用法: py -3.12 tests\_tmp\make_sample_obj.py
"""
import os
import sys

BASE = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))))
sys.path.insert(0, os.path.join(BASE, 'Loom'))

from mesh import create_cube, create_sphere

OUT = os.path.join(BASE, 'Loom', '保存', '示例obj')
os.makedirs(OUT, exist_ok=True)


def write_obj(name, mesh):
    """Mesh -> .obj (v + f, 1-based; 引擎 load_obj 扇形三角化 4+ 边面)."""
    lines = ["# %s (Loom 示例, 供 A03 导入测试)" % name, "# 顶点: %d  面: %d" % (
        len(mesh.vertices), len(mesh.faces)), ""]
    for (x, y, z) in mesh.vertices:
        lines.append("v %.4f %.4f %.4f" % (x, y, z))
    lines.append("")
    for (a, b, c) in mesh.faces:
        lines.append("f %d %d %d" % (a + 1, b + 1, c + 1))
    path = os.path.join(OUT, name + ".obj")
    with open(path, 'w', encoding='utf-8') as f:
        f.write("\n".join(lines) + "\n")
    print("生成 %s  (%d 顶点 / %d 面)" % (path, len(mesh.vertices), len(mesh.faces)))


# 1) 立方体 (create_cube 绕序与引擎一致)
write_obj("立方体", create_cube(2.0))

# 2) 低多边形球 (stacks=8/slices=12: 圆润但面数少, 导入明显)
write_obj("低多边形球", create_sphere(1.0, stacks=8, slices=12))

# 3) 金字塔 (手动定义, 底面四边形 -> load_obj 自动三角化)
pyramid = type(create_cube(1))([
    (0.0, 1.0, 0.0),            # 0 尖顶
    (-1.0, 0.0, -1.0), (1.0, 0.0, -1.0),   # 1 2 底后
    (1.0, 0.0, 1.0), (-1.0, 0.0, 1.0),     # 3 4 底前
], [
    (0, 1, 2), (0, 2, 3), (0, 3, 4), (0, 4, 1),  # 四面
    (1, 2, 3), (1, 3, 4),                         # 底面 (三角化)
], ['#FF5555'] * 4 + ['#888888'] * 2)
write_obj("金字塔", pyramid)

# 4) 环面 (torus 8x12, 更有辨识度)
import math
TRI, SEG = 8, 12
R, r = 1.2, 0.45
vs, fs = [], []
for i in range(TRI):
    for j in range(SEG):
        u = 2 * math.pi * i / TRI
        v = 2 * math.pi * j / SEG
        x = (R + r * math.cos(v)) * math.cos(u)
        y = r * math.sin(v)
        z = (R + r * math.cos(v)) * math.sin(u)
        vs.append((x, y, z))
        a, b = i * SEG + j, i * SEG + (j + 1) % SEG
        c, d = ((i + 1) % TRI) * SEG + j, ((i + 1) % TRI) * SEG + (j + 1) % SEG
        fs.append((a, c, b))
        fs.append((b, c, d))
write_obj("环面", type(create_cube(1))(vs, fs, ['#55AAFF'] * len(fs)))

print("\n完成: %s" % OUT)
