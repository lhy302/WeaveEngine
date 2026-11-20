# -*- coding: utf-8 -*-
"""loom_types.py — 引擎基础数据类型。

原属 engine.py（Point3D 定义）。零依赖模块，供 engine.py / loom_components.py
等按需引入。engine.py 通过 `from loom_types import Point3D` 重新导出，
保持既有 `from engine import Point3D` 全兼容。
"""
from collections import namedtuple

Point3D = namedtuple('Point3D', ['x', 'y', 'z'])
