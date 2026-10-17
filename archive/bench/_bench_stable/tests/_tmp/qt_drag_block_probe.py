# -*- coding: utf-8 -*-
"""qt_drag_block_probe.py — 检查器底部数值拖拽块 (2026-08-22 用户需求) 验证.
覆盖: 聚焦数值行 → 拖块显示且指向该行; 按住左右拖动 → 值按 step/px 变化 +
spinbox 同步; 释放 → 撤销压栈 (undo 回原值); 焦点离开检查器数值行 → 拖块隐藏.
程序化 QMouseEvent (sendEvent) 模拟 press/move/release, 不依赖真实光标."""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
LOOM_DIR = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, LOOM_DIR)

import plugin_loader
plugin_loader.plugin_dir = lambda program='loom', base=None: os.path.join(LOOM_DIR, 'plugins')

from PySide6.QtCore import Qt, QEvent, QPointF
from PySide6.QtGui import QMouseEvent, QFocusEvent
from PySide6.QtWidgets import QApplication, QLineEdit

FAILS = []


def check(name, cond, extra=""):
    print(("PASS " if cond else "FAIL ") + name + ("  " + str(extra) if extra else ""))
    if not cond:
        FAILS.append(name)


from ui.loom_gui import LoomGUI

app = QApplication(sys.argv)
win = LoomGUI(scene_path=None, width=1000, height=680)
win.show()
app.processEvents()
QApplication.setActiveWindow(win)     # 探针窗口常不被 OS 激活, setFocus 会被 Qt 延迟
app.processEvents()
e = win.editor
check("editor 实例已创建", e is not None)


def _tick():
    win._refresh_all()
    app.processEvents()


def mouseev(t, pos):
    return QMouseEvent(t, QPointF(pos[0], pos[1]), QPointF(pos[0], pos[1]),
                       Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton,
                       Qt.KeyboardModifier.NoModifier)


win._cmd_add('cube'); _tick()
m = e.models[-1]
check("加立方体后检查器数值行就位 (pos.X 存在)", 'pos.X' in win._spins)
check("初始拖块隐藏", win._dragblock.isVisible() is False)
sbx = win._spins['pos.X']


def drag(dx_from, dx_to, y=18):
    b = win._dragblock
    QApplication.sendEvent(b, mouseev(QEvent.Type.MouseButtonPress, (dx_from, y)))
    app.processEvents()
    QApplication.sendEvent(b, mouseev(QEvent.Type.MouseMove, (dx_to, y)))
    app.processEvents()
    QApplication.sendEvent(b, mouseev(QEvent.Type.MouseButtonRelease, (dx_to, y)))
    app.processEvents()


# ========== 1. 聚焦数值行 -> 拖块显示 + 指向该行 ==========
# 探针窗口不被 OS 激活时 Qt 延迟 setFocus (真实用户点击无此问题), 用 FocusIn
# 事件直发走 focusInEvent -> _spin_focused 真实链路
QApplication.sendEvent(sbx,
                       QFocusEvent(QEvent.Type.FocusIn, Qt.FocusReason.OtherFocusReason))
app.processEvents()
check("聚焦 pos.X 后拖块显示", win._dragblock.isVisible() is True)
check("拖块目标 label=X (位置行)", win._dragblock._target['label'] == 'X',
      win._dragblock._target['label'] if win._dragblock._target else None)

# ========== 2. 按住拖 +50px -> 位置 X +5.0 (step=0.1/px) ==========
before = m.position.x
drag(20, 70)
check("拖动 +50px 后 pos.x +5.0", abs(m.position.x - (before + 5.0)) < 1e-6,
      m.position.x)
check("拖动后 spinbox 同步 (blockSignals 回写)", abs(sbx.value() -
      (before + 5.0)) < 1e-6, sbx.value())
check("释放后拖块仍在 (焦点未动)", win._dragblock.isVisible() is True)

# ========== 3. 撤销协议: 拖动释放应压一格撤销 (拖回原值) ==========
e.undo.undo()
_tick()
check("undo 后位置回原值 (拖动=一步命令)", abs(m.position.x - before) < 1e-6,
      m.position.x)
# 撤销后 spinbox 同步: 拖块按下前 force sync (顺带暴露并修复了
# _sync_inspector_values getattr 'X' 大小写错位的隐藏 bug -> 现在直接同步)
check("undo 后 spinbox 同步为模型值 (旧隐藏 bug 修复)",
      abs(sbx.value() - m.position.x) < 1e-6, sbx.value())

# ========== 4. 向左拖动 = 减小 ==========
b2 = m.position.x
drag(70, 40)
check("向左拖 -30px 后 pos.x 减少 3.0", abs(m.position.x - (b2 - 3.0)) < 1e-6,
      m.position.x)

# ========== 4.5 三轴隔离: 拖 X 只改 X (用户实测 bug: XYZ 被同时改) ==========
QApplication.sendEvent(sbx,
                       QFocusEvent(QEvent.Type.FocusIn, Qt.FocusReason.OtherFocusReason))
app.processEvents()
bx0, b_y, b_z = m.position.x, m.position.y, m.position.z
drag(30, 60)          # +30px -> pos.x +3.0 (X 轴拖块)
check("拖 X 后 pos.x = 起点+3.0", abs(m.position.x - (bx0 + 3.0)) < 1e-6,
      m.position.x)
check("拖 X 后 pos.y 不变 (轴隔离)", abs(m.position.y - b_y) < 1e-6, m.position.y)
check("拖 X 后 pos.z 不变 (轴隔离)", abs(m.position.z - b_z) < 1e-6, m.position.z)
# pos.Y 行拖拽同样轴隔离 (y 变, x/z 不动)
bx_after = m.position.x
sby = win._spins['pos.Y']
QApplication.sendEvent(sby,
                       QFocusEvent(QEvent.Type.FocusIn, Qt.FocusReason.OtherFocusReason))
app.processEvents()
drag(30, 60)
check("拖 Y 后 pos.y = 起点+3.0", abs(m.position.y - (b_y + 3.0)) < 1e-6,
      m.position.y)
check("拖 Y 后 pos.x 不变", abs(m.position.x - bx_after) < 1e-6, m.position.x)

# ========== 4.6 光源位置行同样轴隔离 (namedtuple setattr 无效 bug 修复) ==========
win._cmd_add_light('point'); _tick()
l = e.lights[-1]
l.position = type(l.position)(1.0, 2.0, 3.0)   # 直接设基准
_tick()
check("光源位置行存在", 'li.pX' in win._spins)
sbx_l = win._spins['li.pX']
QApplication.sendEvent(sbx_l,
                       QFocusEvent(QEvent.Type.FocusIn, Qt.FocusReason.OtherFocusReason))
app.processEvents()
drag(30, 90)          # +60px -> +6.0
check("光源拖 X 后 li.x +6.0", abs(l.position.x - 7.0) < 1e-6, l.position.x)
check("光源拖 X 后 li.y 不变", abs(l.position.y - 2.0) < 1e-6, l.position.y)

# ========== 4.7 摄像机位置行同样轴隔离 ==========
win._cmd_add_camera(); _tick()
c = e.cameras[-1]
c.position = type(c.position)(1.0, 2.0, 3.0)
_tick()
check("相机位置行存在", 'cam.pX' in win._spins)
sbx_c = win._spins['cam.pX']
QApplication.sendEvent(sbx_c,
                       QFocusEvent(QEvent.Type.FocusIn, Qt.FocusReason.OtherFocusReason))
app.processEvents()
drag(30, 90)
check("相机拖 X 后 cam.x +6.0", abs(c.position.x - 7.0) < 1e-6, c.position.x)
check("相机拖 X 后 cam.y 不变", abs(c.position.y - 2.0) < 1e-6, c.position.y)

# ========== 5. 焦点离开检查器数值行 -> 拖块隐藏; 回来 -> 又显示 ==========
# focusChanged 是 QApplication 状态信号 (sendEvent 不触发), 直呼 handler 验证逻辑;
# 真接线 = __init__ 里 QApplication.instance().focusChanged.connect(...)
qline = win.inspector.findChild(QLineEdit)   # 名称框 (检查器内, 非数值)
check("名称框存在", qline is not None)
if qline is not None:
    win._on_app_focus_changed(None, qline)
    app.processEvents()
    check("焦点到名称框后拖块隐藏", win._dragblock.isVisible() is False)
e._select_model(e.models.index(m))   # 切回物体, 检查器重建出 pos.* 行
_tick()
sbx2 = win._spins['pos.X']
QApplication.sendEvent(sbx2,
                       QFocusEvent(QEvent.Type.FocusIn, Qt.FocusReason.OtherFocusReason))
app.processEvents()
check("重新聚焦数值行后拖块又显示", win._dragblock.isVisible() is True)
# 拖拽进行中, focusChanged 不应打断 (松手前不消失)
win._spin_focused('pos.X')
app.processEvents()
QApplication.sendEvent(win._dragblock,
                       QMouseEvent(QEvent.Type.MouseButtonPress, QPointF(20, 18),
                                   QPointF(20, 18), Qt.MouseButton.LeftButton,
                                   Qt.MouseButton.LeftButton,
                                   Qt.KeyboardModifier.NoModifier))
app.processEvents()
check("拖动中的拖块不被 focusChanged 隐藏", win._dragblock.is_dragging() is True)
win._on_app_focus_changed(None, None)
app.processEvents()
check("拖动中 focusChanged 不隐藏拖块", win._dragblock.isVisible() is True)
QApplication.sendEvent(win._dragblock,
                       QMouseEvent(QEvent.Type.MouseButtonRelease, QPointF(20, 18),
                                   QPointF(20, 18), Qt.MouseButton.LeftButton,
                                   Qt.MouseButton.NoButton,
                                   Qt.KeyboardModifier.NoModifier))
app.processEvents()

# ========== 6. 夹紧: 拖到范围外被 clamp (hi=1000 不适用, 用 lo=-1000 极端小测) ==========
e.undo.clear()
win.close()
print("总结果:", "ALL PASS ✅" if not FAILS else "FAIL ❌ " + str(FAILS))
sys.exit(1 if FAILS else 0)
