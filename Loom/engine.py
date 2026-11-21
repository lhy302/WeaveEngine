# -*- coding: utf-8 -*-
"""engine.py — 薄门面（目录重构 B3 批，2026-11-21）。

GLEngine 本体（1695 行，原 Loom/engine.py）已整体搬到 render/gl/engine.py；
本文件把旧导入名 'engine' **别名**到新模块（sys.modules 换身），旧调用面一行不改:
  - 全仓 ~90 个文件的 from-engine-import / import-engine（测试、编辑器、运行时、工具链）
  - 用户游戏脚本（Loom/scripts/*.py、Projects、examples/ 的 from engine import Point3D）
  - 打包/发布链 tools/（build_entry 等）

为什么用 sys.modules 别名而不是逐名 re-export: engine 模块携带模块级可变状态
（_gc_thresh_prev / _gc_play_active / _UI_LINE_ERR_REPORTED / _UI_POLY_ERR_REPORTED，
由函数内 global 语句写入）—— 别名保证读/写/monkeypatch 全部落在**同一个模块对象**上，
语义逐位不变（薄门面先例 = B2 批的 sceneio.py；sceneio 是纯函数面用逐名 re-export，
engine 有可变模块状态，必须换身）。
"""
import sys as _sys

from render.gl import engine as _engine

_sys.modules[__name__] = _engine
