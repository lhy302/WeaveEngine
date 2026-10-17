# -*- coding: utf-8 -*-
"""
ui/ — Loom 编辑器 UI 层 (UI 模块化 2026-08-13)

本包承载编辑器全部"显示层"代码 (面板绘制 + 视口叠加绘制), 与逻辑层
(editor.py 的 EditorController 命令层) 通过 IEditorView 契约解耦:
    ui/editor_ui.py         IEditorView 接口契约 (换 UI 只实现它)
    ui/loom_gui.py          LoomGUI 默认实现 (PySide6 Qt 原生控件, 全功能)
    ui/minimal_editor_view.py  MinimalEditorView 第二实现 (极简只读, 证明可换)
"""
