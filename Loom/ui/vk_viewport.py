# -*- coding: utf-8 -*-
"""ui/vk_viewport.py — 薄门面（目录重构 B4 批，2026-11-21）。

VkViewport 本体（原 ui/vk_viewport.py，B6 批所建）已归位到
editor/viewport/vk_viewport.py（与 editor/ 包同域：编辑器 VK 视口 + VkEditorApp
装配）；本文件把旧导入名 'ui.vk_viewport' **别名**到新模块（sys.modules 换身），
仓外旧调用面一行不改。

仓内全部调用面已改指 editor.viewport.vk_viewport（见 B4 提交说明）。
sys.modules 别名先例 = B3 engine / B6 scripts 薄门面。
"""
import sys as _sys

from editor.viewport import vk_viewport as _vk_viewport

_sys.modules[__name__] = _vk_viewport
