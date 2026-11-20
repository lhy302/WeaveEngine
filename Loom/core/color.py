# -*- coding: utf-8 -*-
"""loom_color.py — hex 颜色到 rgba 的转换 + 缓存。

原属 engine.py（"hex 颜色 -> rgba (A2 实例颜色/共享几何用, 缓存)" 段）。
零依赖模块，供 engine.py / loom_material.py 使用。
engine.py 通过 `from loom_color import _hex_rgba` 重新导出。
"""

# ================ hex 颜色 -> rgba (A2 实例颜色/共享几何用, 缓存) ================
_HEX_RGBA_CACHE = {}


def _hex_rgba(c):
    """'#RRGGBB' -> (r,g,b,alpha=1.0) float 元组 (失败回退灰色 .5)."""
    t = _HEX_RGBA_CACHE.get(c)
    if t is None:
        try:
            t = (int(c[1:3], 16) / 255.0, int(c[3:5], 16) / 255.0,
                 int(c[5:7], 16) / 255.0, 1.0)
        except Exception:
            t = (0.5, 0.5, 0.5, 1.0)
        _HEX_RGBA_CACHE[c] = t
    return t
