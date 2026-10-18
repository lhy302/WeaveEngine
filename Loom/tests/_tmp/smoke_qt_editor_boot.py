# -*- coding: utf-8 -*-
"""smoke_qt_editor_boot.py — Qt 编辑器开窗冒烟 (2026-10-18)

验证 GLFW 窗口层剥离后 Qt 编辑器路径仍能启动。
用 run_loom_gui 的 --auto-close 3 自动关窗，跑 3 秒后进程应正常退出。
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..'))

# 用 subprocess 方式拉起 run_loom_gui 更接近真实启动，但会污染父进程，改为直接调用
# 注意：需要 QApplication 存在才能起 Qt
from PySide6.QtWidgets import QApplication
from ui.loom_gui import LoomGUI

# 已有 QApplication 吗？（前置脚本可能建过）
app = QApplication.instance()
if app is None:
    app = QApplication(sys.argv)

win = LoomGUI(scene_path=None, width=800, height=600)
win.show()

# 用 QTimer 3 秒后关闭（避免手弹窗）
from PySide6.QtCore import QTimer
QTimer.singleShot(3000, win.close)

print('[smoke] LoomGUI 已创建并 show，3 秒后自动关闭')
app.exec()
print('[smoke] QApplication 已退出')
print('[smoke] SMOKE_PASS')
