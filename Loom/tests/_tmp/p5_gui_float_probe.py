# -*- coding: utf-8 -*-
"""P5-GUI 确认: 用户真实 GUI 按钮路径复现"碰撞器+重力=浮空" (真 Qt 窗口).

流程 (逐钮点击, 与用户一致):
  立方体 → ＋加刚体 (受重力) → 碰撞器按钮点 1 次 (用户以为"启用") →
  →播放 → 采样 y (若悬停 1.0 不动 = 复现; 该按钮此刻文本 = 用户看到的"启用时"证据) →
  ■停止 → 碰撞器按钮再点 1 次 (恢复启用) → →播放 → 采样 y (应下落).
用法: py -3.12 tests\\_tmp\\p5_gui_float_probe.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from PySide6.QtWidgets import QApplication, QPushButton, QToolButton
from PySide6.QtGui import QSurfaceFormat
from PySide6.QtCore import QTimer, Qt
from PySide6.QtTest import QTest

import ui.loom_gui as qv

FAILS = []


def check(name, cond, detail=""):
    print(("PASS " if cond else "FAIL ") + name + ("  " + str(detail) if detail else ""))
    if not cond:
        FAILS.append(name)


def find_btn(widget, text, parent):
    """找文本为 text 的按钮 (button text 含括号/空格差异 -> startswith 匹配)."""
    for b in parent.findChildren(QPushButton):
        if b.text().replace(' ', '') == text.replace(' ', ''):
            return b
    return None


def main():
    fmt = QSurfaceFormat()
    fmt.setVersion(3, 3)
    fmt.setProfile(QSurfaceFormat.OpenGLContextProfile.CoreProfile)
    fmt.setDepthBufferSize(24)
    fmt.setSamples(4)
    QSurfaceFormat.setDefaultFormat(fmt)
    app = QApplication(sys.argv)
    win = qv.LoomGUI(scene_path=os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                              "jt_scene.json"))
    win.show()

    def start():
        e = win.editor
        if e is None or not hasattr(e, 'models'):
            QTimer.singleShot(300, start)
            return
        e._new_scene()
        win._refresh_all()
        QTimer.singleShot(300, step_add_cube)

    def step_add_cube():
        # 工具栏"立方体"按钮
        for b in win.findChildren(QToolButton):
            if b.text() == "立方体":
                QTest.mouseClick(b, Qt.MouseButton.LeftButton)
                break
        QTimer.singleShot(300, step_add_rb)

    def step_add_rb():
        e = win.editor
        m = e._selected()
        check("物体已添加且选中", m is not None and m.primitive == 'cube',
              m.name if m else None)
        btn = find_btn(win, "＋加刚体 (受重力)", win)
        check("检查器有'＋加刚体 (受重力)'按钮", btn is not None)
        QTest.mouseClick(btn, Qt.MouseButton.LeftButton)
        QTimer.singleShot(300, step_collider)

    def step_collider():
        e = win.editor
        m = e._selected()
        btn = find_btn(win, "碰撞器: 启用中(点按禁用)", win)   # 修复后初始文本
        check("初始碰撞器按钮文本='碰撞器: 启用中(点按禁用)' (状态+动作双显)",
              btn is not None, btn.text() if btn else "无")
        QTest.mouseClick(btn, Qt.MouseButton.LeftButton)
        QTimer.singleShot(300, lambda: step_after_collider(m))

    def step_after_collider(m):
        btn = find_btn(win, "碰撞器: 已禁用(点按启用)", win)  # 修复后措辞
        check("点一次后按钮文本='碰撞器: 已禁用(点按启用)' (状态直读)",
              btn is not None, btn.text() if btn else "无")
        check("实际: collider.enabled=False (按钮点击是切换)",
              m.collider.enabled is False, "enabled=%s" % m.collider.enabled)
        QTimer.singleShot(100, lambda: step_play(m, first=True))

    def step_play(m, first=False):
        win._act_play.trigger()
        QTimer.singleShot(2200, lambda: sample(m, first))

    _seen = []

    def sample(m, first):
        e = win.editor
        y = m.position.y
        vy = m.rigidbody.velocity.y if m.rigidbody else None
        _seen.append(y)
        br = getattr(e, '_phys_bridge', None)
        nbody = br.body_count if br else -1
        act = br.active_count if br else -1
        if first:
            print("  [第1轮播放] y=%.4f vy=%s 体数=%d active=%d" % (y, vy, nbody, act))
            win._act_play.trigger()                      # ■停止
            QTimer.singleShot(400, lambda: step_enable(m))
        else:
            print("  [第2轮播放] y=%.4f vy=%s 体数=%d active=%d" % (y, vy, nbody, act))
            # 修复后: 第1轮 (碰撞器实际禁用) 走自由积分路径 -> 仍下落 (浮空已除)
            check("第1轮用户序 (点一次碰撞器+播放): 修复后下落 (不再浮空)",
                  _seen[0] < -2.0, "第1轮 y=%.4f (起始 1.0)" % _seen[0])
            check("第2轮 (碰撞器恢复启用+播放): 物体下落 (Jolt 路径)", _seen[-1] < -2.0,
                  "第2轮 y=%.4f" % _seen[-1])
            win._suppress_confirm = True
            win.close()
            QTimer.singleShot(800, app.quit)

    def step_enable(m):
        e = win.editor
        btn = find_btn(win, "碰撞器: 已禁用(点按启用)", win)  # 禁用态文本 (修复后)
        check("停止后按钮文本='碰撞器: 已禁用(点按启用)' (状态直读)",
              btn is not None, btn.text() if btn else "无")
        QTest.mouseClick(btn, Qt.MouseButton.LeftButton)  # 第二次点 = 恢复启用
        QTimer.singleShot(300, lambda: check_enabled(m))

    def check_enabled(m):
        check("第二次点击后 collider.enabled=True", m.collider.enabled is True,
              "enabled=%s" % m.collider.enabled)
        QTimer.singleShot(100, lambda: step_play(m, first=False))

    QTimer.singleShot(2500, start)
    QTimer.singleShot(90000, app.quit)
    app.exec()
    print("探针结果:", "ALL PASS" if not FAILS else ("FAIL %s" % FAILS))
    sys.exit(0 if not FAILS else 1)


if __name__ == "__main__":
    main()
