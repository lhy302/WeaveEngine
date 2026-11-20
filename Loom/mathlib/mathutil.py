# -*- coding: utf-8 -*-
"""mathlib/mathutil.py — 纯数学小工具（零引擎依赖）。

2026-11-21 目录重构 B1 批：wrap_deg 自 loom_scene_entities **前置**到此处
（Q-B7-38-1 裁决 20 顶层包 / mathlib P1 前置项）。
loom_scene_entities 继续 re-export，旧引用面（from loom_scene_entities
import wrap_deg）保持有效；实现从此只有这一份。
"""


def wrap_deg(v, lo=0.0, hi=360.0):
    """角度环绕: 把 v 环绕进 [lo, hi). 用于 朝向/俯仰/倾斜 拖拽越过边界后继续转.
    已在范围内则原样返回 (避免取模引入 ~1e-13 浮点噪声)."""
    if lo <= v < hi:
        return v
    span = hi - lo
    return lo + ((v - lo) % span)
