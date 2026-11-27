# -*- coding: utf-8 -*-
"""
gui/panels/console_mixin.py — 底部命令行坞（EAI 命令行输入/输出）（Q-B7-38-1 第 8 批，自 gui/main_window.py 纯搬迁）


我负责：控制台坞构建与 [命令行] 按钮 / F12 开关。
我不负责：UI 树坞（uitree_mixin）、设置对话框（settings_mixin）。

搬迁纪律（见 docs/guides/开发要求_功能解耦与模块化.md §3）：方法体逐字未动，
只改 def 归属与 import 头；LoomGUI 经 gui/main_window.py 的基类装配混入本类。
"""

from PySide6.QtCore import Qt


class ConsoleMixin:
    # 混入 LoomGUI（gui/main_window.py 基类装配）；以下方法体逐字未动。

    # ---------------- 命令行坞 (EAI P2①, 2026-08-27) ----------------
    def _build_console(self):
        """底部命令行坞: 输入 -> agent_commands.dispatch (与远程 EAI 同一张
        命令表), 输出 = 命令结果 + 引擎日志环增量. 默认隐藏, 状态栏
        [命令行] 按钮 / F12 开关 (视口面积不被默认占用)."""
        from ui import qt_console
        self.console = qt_console.ConsoleDock(self)
        self.addDockWidget(Qt.DockWidgetArea.BottomDockWidgetArea, self.console)
        self.console.resize(self.console.width(), 200)
        self.console.hide()
        # 坞被用户点 X 关闭时同步按钮态 (否则按钮显示"按下"但坞已关)
        self.console.visibilityChanged.connect(
            lambda vis: self._btn_console.setChecked(bool(vis)))

    def _cmd_console(self, checked=None):
        """[命令行] 按钮 / F12: 开关命令行坞 (打开时输入框自动获得焦点)."""
        show = not self.console.isVisible() if checked is None else bool(checked)
        self.console.setVisible(show)
        self._btn_console.setChecked(show)
        if show:
            self.console.entry.setFocus()
        return show
