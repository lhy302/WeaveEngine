# -*- coding: utf-8 -*-
"""
gui/panels/toolbar_mixin.py — 主工具栏构建 + 插件菜单注入区（Q-B7-38-1 第 8 批，自 gui/main_window.py 纯搬迁）


我负责：顶部 QToolBar（dock 开关/播放/TPS/场景名/存读新建/撤销重做/gizmo/
加物体/Prefab/发布/插件菜单按钮）与插件按钮回调。
我不负责：动作命令壳本体（actions_mixin）、状态栏（status_mixin）。

搬迁纪律（见 docs/guides/开发要求_功能解耦与模块化.md §3）：方法体逐字未动，
只改 def 归属与 import 头；LoomGUI 经 gui/main_window.py 的基类装配混入本类。
"""

from PySide6.QtGui import QAction, QActionGroup

from PySide6.QtWidgets import (
    QLabel,
    QLineEdit,
    QMenu,
    QToolBar,
    QToolButton,
)


class ToolbarMixin:
    # 混入 LoomGUI（gui/main_window.py 基类装配）；以下方法体逐字未动。

    def _build_toolbar(self):
        tb = QToolBar("工具栏")
        tb.setMovable(False)
        self.addToolBar(tb)
        e_get = lambda: self.editor

        # 2026-10-19 用户要求: dock 开关按钮放左上角（工具栏最左）
        # 之前放状态栏，窗口小时被挤掉看不见。改成工具栏按钮保证始终可见。
        # 与 F11 (UI树) / F12 (命令行) 快捷键同源，都调 _cmd_uitree/_cmd_console。
        self._btn_uitree = QToolButton()
        self._btn_uitree.setText("UI树")
        self._btn_uitree.setCheckable(True)
        self._btn_uitree.setChecked(True)   # UI 树默认显示
        self._btn_uitree.setToolTip("开关 UI 树坞 (F11)")
        self._btn_uitree.clicked.connect(self._cmd_uitree)
        tb.addWidget(self._btn_uitree)

        self._btn_console = QToolButton()
        self._btn_console.setText("命令行")
        self._btn_console.setCheckable(True)
        self._btn_console.setChecked(False)  # 命令行坞默认隐藏
        self._btn_console.setToolTip("开关命令行坞 (F12)")
        self._btn_console.clicked.connect(self._cmd_console)
        tb.addWidget(self._btn_console)
        tb.addSeparator()

        self._act_play = QAction("→播放", self)
        self._act_play.triggered.connect(lambda: self._cmd_play())
        tb.addAction(self._act_play)
        # 分离批5 (2026-09-05 用户需求): 逻辑时钟控制 — MC 同款暂停世界/步进
        self._act_tps_pause = QAction("⏸暂停TPS", self)
        self._act_tps_pause.setToolTip("暂停/恢复逻辑时钟 (F9): 渲染照跑, 世界冻结")
        self._act_tps_pause.triggered.connect(lambda: self._cmd_tps_pause())
        tb.addAction(self._act_tps_pause)
        self._act_tps_step = QAction("⏭步进1帧", self)
        self._act_tps_step.setToolTip("步进 1 逻辑帧 (F10): 仅暂停态生效")
        self._act_tps_step.triggered.connect(lambda: self._cmd_tps_step())
        tb.addAction(self._act_tps_step)
        tb.addSeparator()

        tb.addWidget(QLabel(" 场景:"))
        self._scene_edit = QLineEdit()
        self._scene_edit.setMaximumWidth(130)
        self._scene_edit.editingFinished.connect(self._cmd_scene_name)
        tb.addWidget(self._scene_edit)
        self._add_tb_btn(tb, "保存", self._cmd_save)
        self._add_tb_btn(tb, "另存为", self._cmd_save_as)
        self._add_tb_btn(tb, "加载", self._cmd_load)
        self._add_tb_btn(tb, "新建", self._cmd_new)
        self._add_tb_btn(tb, "撤销", self._cmd_undo)
        self._add_tb_btn(tb, "重做", self._cmd_redo)
        tb.addSeparator()

        g = QActionGroup(self)
        self._act_move = QAction("移动", self)
        self._act_move.setCheckable(True)
        self._act_move.setChecked(True)
        self._act_rotate = QAction("旋转", self)
        self._act_rotate.setCheckable(True)
        g.addAction(self._act_move)
        g.addAction(self._act_rotate)
        self._act_move.triggered.connect(lambda: self._cmd_gizmo('translate'))
        self._act_rotate.triggered.connect(lambda: self._cmd_gizmo('rotate'))
        tb.addActions([self._act_move, self._act_rotate])
        tb.addSeparator()

        self._add_tb_btn(tb, "立方体", lambda: self._cmd_add('cube'))
        self._add_tb_btn(tb, "球体", lambda: self._cmd_add('sphere'))
        self._add_tb_btn(tb, "平面", lambda: self._cmd_add('plane'))
        self._add_tb_btn(tb, "导入.obj", self._cmd_import_obj)
        self._add_tb_btn(tb, "复制", self._cmd_dup)
        self._add_tb_btn(tb, "删除", self._cmd_del)
        tb.addSeparator()

        tb.addWidget(QLabel(" Prefab:"))
        self._prefab_edit = QLineEdit()
        self._prefab_edit.setMaximumWidth(110)
        self._prefab_edit.editingFinished.connect(self._cmd_prefab_name)
        tb.addWidget(self._prefab_edit)
        self._add_tb_btn(tb, "存模板", self._cmd_prefab_save)
        self._add_tb_btn(tb, "放实例", self._cmd_prefab_put)
        # 2026-08-22: [发布游戏] (Unity Build Settings 按钮): 场景+脚本 -> 玩家
        # exe + 加密游戏包 (build_game.py 子进程, 完成 toast + 自动打开)
        tb.addSeparator()
        self._add_tb_btn(tb, "发布游戏", self._cmd_publish_game)
        # 2026-08-27: 插件按钮注入区 (路 A 跨层界面补充) —— 插件注册的
        # 编辑器侧操作按钮全部收进「插件」菜单, 与注入层声明无关
        tb.addSeparator()
        self._add_tb_menu(tb, "插件", self._rebuild_plugin_menu)

        # 2026-11-07 EAI 可视化 (B): AI 操作中红点, 只有 _agent_busy(True) 时可见.
        tb.addSeparator()
        self._lbl_agent_busy = QLabel("● AI 操作中")
        self._lbl_agent_busy.setStyleSheet(
            "color:#e06c75;font-weight:bold;padding:0 6px;")
        self._lbl_agent_busy.setToolTip("Agent 正在执行命令")
        # 注意: QToolBar.addWidget 返回 QWidgetAction, 显隐必须切 action
        # (直接 widget.setVisible(False) 会把控件置灰, 且 show 后又被工具栏藏回去).
        self._act_agent_busy = tb.addWidget(self._lbl_agent_busy)
        self._act_agent_busy.setVisible(False)

    def _add_tb_menu(self, tb, text, build_fn):
        """工具栏下拉菜单按钮 (插件按钮注入区): aboutToShow 时重建菜单内容."""
        tb_btn = QToolButton()
        tb_btn.setText(text)
        tb_btn.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        menu = QMenu(tb_btn)
        tb_btn.setMenu(menu)
        menu.aboutToShow.connect(lambda: build_fn(menu))
        tb.addWidget(tb_btn)
        return tb_btn

    def _rebuild_plugin_menu(self, menu):
        """重建「插件」菜单: 列出 plugin_loader.editor_buttons() 注册的按钮.
        回调与插件同环境 (普通插件=受限); 异常只提示不崩编辑器."""
        import plugin.loader as plugin_loader
        menu.clear()
        btns = plugin_loader.editor_buttons()
        if not btns:
            act = menu.addAction("(无插件按钮)")
            act.setEnabled(False)
            return
        for text, cb, pid in btns:
            act = menu.addAction(text)
            act.setToolTip(pid)
            act.triggered.connect(lambda checked=False, cb=cb: self._run_plugin_cb(cb))

    def _run_plugin_cb(self, cb):
        try:
            cb()
        except Exception as ex:
            self.editor._notify("插件按钮出错: %r" % ex, (240, 120, 120))

    def _add_tb_btn(self, tb, text, fn):
        b = QToolButton()
        b.setText(text)
        b.setAutoRaise(True)
        b.clicked.connect(lambda: fn())
        tb.addWidget(b)
        return b
