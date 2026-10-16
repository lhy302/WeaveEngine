# -*- coding: utf-8 -*-
"""P3 检查器单组显示探针: 有刚体 -> 只显示刚体组; 无 -> 只显示碰撞组 (2026-08-30)"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QSurfaceFormat
from PySide6.QtCore import QTimer, QPoint, Qt
from PySide6.QtTest import QTest

import ui.loom_gui as qv

FAILS = []


def check(name, cond, detail=""):
    print(("PASS " if cond else "FAIL ") + name + ("  " + str(detail) if detail else ""))
    if not cond:
        FAILS.append(name)


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

    def step():
        e = win.editor
        if e is None or not hasattr(e, 'models') or not e.models:
            QTimer.singleShot(300, step)
            return
        players = [i for i, m in enumerate(e.models) if m.rigidbody is not None]
        grounds = [i for i, m in enumerate(e.models) if m.rigidbody is None]
        assert players and grounds, "场景应有刚体/非刚体对象"

        # --- 刚体对象: 只显示刚体组 (rb.fric/rb.rest/rb.roll), 无 col.* ---
        e.selected_index = players[0]
        win._refresh_all()
        QTimer.singleShot(200, lambda: check_rb(e, players[0], grounds[0]))

    def check_rb(e, pi, gi):
        ks = set(win._spins.keys())
        check("刚体对象: 显示 rb 组三键 (fric/rest/roll)",
              {'rb.fric', 'rb.rest', 'rb.roll'} <= ks, sorted(ks))
        check("刚体对象: 不显示 col 组键",
              not ({'col.fric', 'col.rest', 'col.roll'} & ks), sorted(ks))
        # 滚动摩擦: 真实用户路径 = 聚焦数值行 -> 底部拖拽块 按住拖动 (撤销协议:
        # mousePress 拍起点快照 -> move apply -> release 压栈)
        win._spin_focused('rb.roll')
        QTimer.singleShot(200, lambda: drag_test(e, pi, gi))

    def drag_test(e, pi, gi):
        m = e.models[pi]
        # 真实路径 = 聚焦数值行 -> 拖拽块 set_target; 300ms 刷新轮询可能在检查器
        # 重建时收起拖拽块, 这里重新聚焦 (等价于用户再次点击数值行).
        win._spin_focused('rb.roll')
        db = win._dragblock
        check("拖拽块已弹出且指向滚动摩擦行", db.isVisible()
              and db._target is not None and db._target['label'] == '滚动摩擦',
              db._target['label'] if db._target else None)
        QTest.mousePress(db, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier,
                         QPoint(5, 18))
        QTest.mouseMove(db, QPoint(50, 18), 10)
        QTest.mouseRelease(db, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier,
                           QPoint(50, 18))
        v_now = m.rigidbody.rolling_friction
        check("拖动写回滚动摩擦 (0.1 + 45px*0.05)", abs(v_now - (0.1 + 45 * 0.05)) < 1e-3,
              "v=%.3f" % v_now)
        e._undo_action()
        check("撤销回 0.1", abs(m.rigidbody.rolling_friction - 0.1) < 1e-6,
              m.rigidbody.rolling_friction)
        e._redo_action()
        check("重做回拖动值", abs(m.rigidbody.rolling_friction - v_now) < 1e-6,
              m.rigidbody.rolling_friction)
        # --- 非刚体对象: 只显示碰撞组 ---
        e.selected_index = gi
        win._refresh_all()
        QTimer.singleShot(200, lambda: check_col(e, gi))

    def check_col(e, gi):
        ks = set(win._spins.keys())
        check("非刚体对象: 显示 col 组三键",
              {'col.fric', 'col.rest', 'col.roll'} <= ks, sorted(ks))
        check("非刚体对象: 不显示 rb 组键",
              not {'rb.fric', 'rb.rest', 'rb.roll'} & ks, sorted(ks))
        m = e.models[gi]
        check("col.roll 存在且同步检查器", 'col.roll' in ks and abs(win._spins['col.roll'].value() - 0.1) < 1e-6,
              win._spins['col.roll'].value() if 'col.roll' in ks else None)
        win._suppress_confirm = True
        win.close()
        QTimer.singleShot(800, app.quit)

    QTimer.singleShot(2500, step)
    QTimer.singleShot(60000, app.quit)
    app.exec()
    print("探针结果:", "ALL PASS" if not FAILS else ("FAIL %s" % FAILS))
    sys.exit(0 if not FAILS else 1)


if __name__ == "__main__":
    main()
