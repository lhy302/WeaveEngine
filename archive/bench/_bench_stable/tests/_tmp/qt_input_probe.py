# -*- coding: utf-8 -*-
"""
qt_input_probe.py — GUI 老链路合成事件探针 (2026-08-27)
复现用户疑点: 右键滑动视角 / 中键平移 (连贯操作, 老链路事件处理) 是否正常。
合成 QMouseEvent 直接 sendEvent 到视口 (不经命令层/不经 EAI), 验证:
  ①右键拖动 -> camera_yaw/pitch 变化 (GUI 老链路)
  ②中键拖动 -> camera_target 变化 (GUI 老链路)
一切与"命令"无关, 只测 GUI 原生输入链路.
"""
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from PySide6.QtCore import QEvent, QPointF, QTimer, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QApplication

import ui.loom_gui as qv

FAILS = []


def check(name, cond, a, b):
    print(("PASS " if cond else "FAIL ") + name +
          ("   yaw=%.2f pitch=%.2f target=%s" % (a['yaw'], a['pitch'], a['target'])
           if isinstance(a, dict) else ""))
    if not cond and len(FAILS) < 10:
        FAILS.append(name)


def send_mouse(win, typ, pos, btn, buttons):
    ev = QMouseEvent(typ, QPointF(pos[0], pos[1]),
                     btn, buttons, Qt.KeyboardModifier.NoModifier)
    QApplication.sendEvent(win.viewport, ev)


def snap(ed):
    return {'yaw': math.degrees(ed.camera_yaw),
            'pitch': math.degrees(ed.camera_pitch),
            'target': tuple(ed.camera_target)}


def main():
    app = QApplication(sys.argv)
    win = qv.LoomGUI(scene_path=None, width=1280, height=800)
    ed = win.editor
    win.show()
    seq = []

    def step1():
        # 右键拖动 (按住往右移): 老链路 = 视口事件 -> editor.buttons/mouse_rel
        send_mouse(win, QEvent.Type.MouseButtonPress, (600, 400),
                   Qt.MouseButton.RightButton, Qt.MouseButton.RightButton)
        for i in range(1, 9):
            send_mouse(win, QEvent.Type.MouseMove, (600 + i * 20, 400 + i * 3),
                       Qt.MouseButton.NoButton, Qt.MouseButton.RightButton)
        send_mouse(win, QEvent.Type.MouseButtonRelease, (760, 424),
                   Qt.MouseButton.RightButton, Qt.MouseButton.NoButton)
        seq.append(('c0', snap(ed)))

    def step2():
        seq.append(('c1', snap(ed)))
        send_mouse(win, QEvent.Type.MouseButtonPress, (600, 400),
                   Qt.MouseButton.MiddleButton, Qt.MouseButton.MiddleButton)
        for i in range(1, 9):
            send_mouse(win, QEvent.Type.MouseMove, (600 + i * 15, 400 - i * 10),
                       Qt.MouseButton.NoButton, Qt.MouseButton.MiddleButton)
        send_mouse(win, QEvent.Type.MouseButtonRelease, (720, 320),
                   Qt.MouseButton.MiddleButton, Qt.MouseButton.NoButton)

    def step3():
        seq.append(('c2', snap(ed)))
        dyaw = abs(seq[1][1]['yaw'] - seq[0][1]['yaw'])
        dpitch = abs(seq[1][1]['pitch'] - seq[0][1]['pitch'])
        check("右键拖动 -> yaw 变化 (老链路正常)", dyaw > 1.0, seq[0][1], seq[1][1])
        check("右键拖动 -> pitch 变化", dpitch > 0.5, seq[0][1], seq[1][1])
        dt = math.dist(seq[2][1]['target'], seq[1][1]['target'])
        check("中键平移 -> target 变化 (老链路正常)", dt > 0.5,
              seq[1][1], seq[2][1])
        win.close()

    QTimer.singleShot(800, step1)
    QTimer.singleShot(1600, step2)
    QTimer.singleShot(2400, step3)
    QTimer.singleShot(6000, win.close)
    app.exec()
    if FAILS:
        print("探针结果: FAIL", FAILS)
        sys.exit(1)
    print("探针结果: ALL PASS")


if __name__ == "__main__":
    main()
