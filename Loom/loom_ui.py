# -*- coding: utf-8 -*-
"""loom_ui.py — Canvas/UI 系统「兼容 shim」(Q-B7-38-1 第 7 批, 2026-11-26)

原 1728 行单文件已按域拆进 ui/canvas/ 包 (一个功能一个文件):
  element / canvas / manager / widgets_basic / widgets_input / widgets_layout
  (脚本事件派发子域 _ACTIVE_ENGINE/_fire_binding 在 manager.py, 原因见该文件 docstring)。

本文件只做一件事: 把自身换成 ui.canvas 包模块对象, 让全仓既有的
`import loom_ui` / `from loom_ui import Canvas` / `loom_ui.X` 一行不改继续工作 ——
loom_ui is ui.canvas (同一个模块对象, 15 个 class 逐字一致; 模块级可变状态
(_SCRIPT_HOST_WARNED 等) 的赋值由包 __init__ 转发到真身子模块, 语义与拆分前等价)。

选「保留 shim」而不是同步改 16 处调用点: 调用点分散在 render/ scene/ script/ eai/
editor/ 与 9 个测试文件里, 全改会把「纯搬家」变成「搬家 + 大面积改调用点」
(docs/guides/开发要求_功能解耦与模块化.md §3「一次只搬一个域、行为零变化」)。

新代码请直接 `import ui.canvas`。
"""
import sys as _sys

import ui.canvas as _canvas

_sys.modules[__name__] = _canvas
