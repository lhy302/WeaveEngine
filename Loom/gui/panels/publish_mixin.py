# -*- coding: utf-8 -*-
"""
gui/panels/publish_mixin.py — 发布游戏（Unity Build Settings 对齐）（Q-B7-38-1 第 8 批，自 gui/main_window.py 纯搬迁）


我负责：Build Settings 对话框、构建器启动命令、构建子进程轮询 toast。
我不负责：场景存读（actions_mixin）、状态栏（status_mixin）。

搬迁纪律（见 docs/guides/开发要求_功能解耦与模块化.md §3）：方法体逐字未动，
只改 def 归属与 import 头；LoomGUI 经 gui/main_window.py 的基类装配混入本类。
"""

import os
import subprocess
import sys

from PySide6.QtCore import QTimer

from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLineEdit,
    QPushButton,
)


class PublishMixin:
    # 混入 LoomGUI（gui/main_window.py 基类装配）；以下方法体逐字未动。

    # ---------------- 发布游戏 (Unity Build Settings 对齐, 2026-08-22) ----------------
    def _build_tool_cmd(self, extra_args):
        """构建器启动命令: 优先 <程序目录>/build_game.exe (编译版用户无 python);
        源码版用当前解释器跑 build/build_game.py. 程序目录解析同 guiloader."""
        import guiloader
        bin_dir = guiloader.program_dir()
        exe_tool = os.path.join(bin_dir, 'build_game.exe')
        if os.path.isfile(exe_tool):
            return [exe_tool] + extra_args
        py = sys.executable
        if not py or not os.path.isfile(os.path.join(bin_dir, 'build', 'build_game.py')):
            return None    # 编译版无工具/无解释器 -> 提示
        return [py, os.path.join(bin_dir, 'build', 'build_game.py')] + extra_args

    def _cmd_publish_game(self):
        """[发布游戏]: Build Settings 对话框 (游戏名/公司名/启动场景/脚本目录/
        输出目录) -> 子进程 build_game.py -> 完成 toast + 打开发布夹."""
        e = self.editor
        if e is None:
            return
        import filedialog
        dlg = QDialog(self)
        dlg.setWindowTitle("发布游戏 (Build Settings)")
        form = QFormLayout(dlg)
        edit_name = QLineEdit(e.scene_name or "我的游戏")
        edit_tb = QLineEdit(e.scene_name or "我的游戏")
        edit_co = QLineEdit("")
        edit_scene = QLineEdit(getattr(e, '_scene_path', '') or "")
        edit_scripts = QLineEdit("")
        edit_out = QLineEdit("")
        import guiloader
        import plugin.loader as plugin_loader
        def _script_dir_default():
            d = os.path.join(plugin_loader._PROGRAM_DIR, 'scripts')
            return d if os.path.isdir(d) else ""
        edit_scripts.setText(_script_dir_default())
        b_scene = QPushButton("浏览")
        b_scene.clicked.connect(lambda: edit_scene.setText(
            filedialog.open_file("选择启动场景", os.path.dirname(edit_scene.text() or ''),
                                 None, "*.json", "json") or edit_scene.text()))
        b_scripts = QPushButton("浏览")
        b_scripts.clicked.connect(lambda: edit_scripts.setText(
            filedialog.choose_directory("选择游戏脚本目录") or edit_scripts.text()))
        b_out = QPushButton("浏览")
        b_out.clicked.connect(lambda: edit_out.setText(
            filedialog.choose_directory("选择输出目录") or edit_out.text()))
        h1 = QHBoxLayout(); h1.addWidget(edit_scene, 1); h1.addWidget(b_scene)
        h2 = QHBoxLayout(); h2.addWidget(edit_scripts, 1); h2.addWidget(b_scripts)
        h3 = QHBoxLayout(); h3.addWidget(edit_out, 1); h3.addWidget(b_out)
        form.addRow("游戏名", edit_name)
        form.addRow("公司名", edit_co)
        form.addRow("窗口标题", edit_tb)
        form.addRow("启动场景", h1)
        form.addRow("游戏脚本目录\n(加密打包)", h2)
        form.addRow("输出目录", h3)
        btns = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok |
                                QDialogButtonBox.StandardButton.Cancel)
        btns.button(QDialogButtonBox.StandardButton.Ok).setText("构建")
        btns.button(QDialogButtonBox.StandardButton.Cancel).setText("取消")
        btns.accepted.connect(dlg.accept)
        btns.rejected.connect(dlg.reject)
        form.addRow(btns)
        dlg.resize(460, 300)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        scene = edit_scene.text().strip()
        if not scene or not os.path.isfile(scene):
            e._notify("启动场景不存在: %s" % scene, (220, 120, 120))
            return
        out = edit_out.text().strip() or os.path.join(
            os.path.dirname(scene), '发布_' + edit_name.text().strip())
        args = ['--name', edit_name.text().strip() or '我的游戏',
                '--company', edit_co.text().strip(),
                '--title', edit_tb.text().strip() or edit_name.text().strip(),
                '--scene', scene, '--output', out]
        if edit_scripts.text().strip():
            args += ['--game-scripts', edit_scripts.text().strip()]
        cmd = self._build_tool_cmd(args)
        if cmd is None:
            e._notify("缺少构建器: 放 build_game.py(源码版) 或 build_game.exe 到程序目录",
                      (220, 120, 120))
            return
        self._pub_proc = subprocess.Popen(cmd, cwd=os.path.dirname(scene))
        self._pub_out_path = out          # 完成后打开发布夹
        self._pub_tick = 0
        if getattr(self, '_pub_timer', None) is None:
            self._pub_timer = QTimer(self)
            self._pub_timer.setInterval(2000)
            self._pub_timer.timeout.connect(self._poll_publish)
        self._pub_timer.start()
        e._notify("正在构建游戏… (首次含打包运行时需数分钟)", (200, 200, 220))

    def _poll_publish(self):
        """构建轮询: 完成后 toast + 打开发布夹 (子进程非阻塞)."""
        e = self.editor
        proc = getattr(self, '_pub_proc', None)
        if proc is None:
            if getattr(self, '_pub_timer', None) is not None:
                self._pub_timer.stop()
            return
        self._pub_tick += 1
        rc = proc.poll()
        if rc is None and self._pub_tick % 15 == 0:   # 每 30s 报一次状态
            e._notify("正在构建游戏… (%ds)" % (self._pub_tick * 2), (180, 180, 200))
            return
        if rc is None:
            return
        out = getattr(self, '_pub_out_path', '')
        if rc == 0:
            e._notify("发布完成: %s" % out, (150, 220, 150))
        else:
            e._notify("发布失败 (退出码 %d): %s" % (rc, out), (220, 120, 120))
        try:
            if os.path.isdir(out):
                os.startfile(out)
        except Exception:
            pass
        self._pub_proc = None
