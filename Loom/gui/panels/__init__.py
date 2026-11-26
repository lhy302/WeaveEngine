# -*- coding: utf-8 -*-
"""
gui/panels/ — LoomGUI 按面板域拆分的 mixin 包（Q-B7-38-1 第 8 批）。

按人类裁定「按域拆到底 + 一个功能一个文件」（docs/guides/开发要求_功能解耦与模块化.md）：
每个文件承载一个面板域；方法体逐字自 gui/main_window.py 搬迁（纯搬家，行为零变化）。
LoomGUI 在 gui/main_window.py 以 (…Mixin, QMainWindow) 装配混入；mixin 之间通过 self
互调（拼装后是同一个实例），彼此不 import（§1 规则 2：模块间只通过标准方式互调）。
"""

__all__ = [
    'CmdBridgeMixin',
    'ActionsMixin',
    'ToolbarMixin',
    'HierarchyMixin',
    'GizmoMixin',
    'AssetMixin',
]
