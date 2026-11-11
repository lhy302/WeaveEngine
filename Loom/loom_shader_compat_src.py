# -*- coding: utf-8 -*-
"""loom_shader_compat_src.py — 读取 shaders/loom_shader_compat.glsl（GL 侧宏层）。"""
import os


def compat_src():
    p = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                     "shaders", "loom_shader_compat.glsl")
    with open(p, encoding="utf-8") as f:
        return f.read()
