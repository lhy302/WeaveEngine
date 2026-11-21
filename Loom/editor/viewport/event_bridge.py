# -*- coding: utf-8 -*-
"""event_bridge.py — 视口事件桥唯一实现（目录重构 B4 批，S5 留痕收口）。

_ViewportEventBridge 的 11+1 个方法（_phys / _sync_mouse / mouse Press/Move/
Release / wheel / key Press/Release / key_pressed_array / dragEnter / drop /
set_mouse_locked）是**纯「写引擎状态字段」**的 Qt 事件翻译层，与宿主渲染后端
无关。历史上有三份逐字段相同的拷贝：
  · GLViewport（原 ui/loom_gui.py，2026-08-17 Qt 重写时第一份）
  · RemoteViewport（同文件，2026-10-20 白屏修复时第二份）
  · VkViewport（B6 批 ui/vk_viewport.py，建包时第三份 + 本基类）
本批把三份收敛为**这一份基类**（规则 5.5：同源唯一实现），三端改继承：
  GLViewport(_ViewportEventBridge, QOpenGLWidget)     gui/gl_viewport.py
  RemoteViewport(_ViewportEventBridge, QWidget)       gui/remote_viewport.py
  VkViewport(_ViewportEventBridge, QRenderWidget)     editor/viewport/vk_viewport.py
MRO 约定（B6 已锁，写进 probe 证据）：事件桥在前，QWidget 自带的 no-op 事件槽
在后 —— super().mouseXxx(ev) 语义与拆分前逐位一致。

同文件还承载 Qt 事件翻译常量（_QT_TO_PG / _qt_mods / _qt_button / _qt_buttons /
_MIME_ASSET，原 ui/loom_gui.py 顶部唯一实现，事件桥的词汇表）—— 放这里是
为了依赖方向单一（gui -> editor.viewport，editor.viewport 不回头 import gui）。
"""
import json

import pygame   # 仅取 K_* / KMOD_* 常量 (import 不初始化 SDL, 无 IME 污染)

from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication

from types import SimpleNamespace   # noqa: F401  事件桥 on_key_event 构造 KEYDOWN/KEYUP 用


# pygame 键值 (Qt.Key -> pygame 常量)
_QT_TO_PG = {
    Qt.Key.Key_W: pygame.K_w, Qt.Key.Key_S: pygame.K_s,
    Qt.Key.Key_A: pygame.K_a, Qt.Key.Key_D: pygame.K_d,
    Qt.Key.Key_Q: pygame.K_q, Qt.Key.Key_E: pygame.K_e,
    Qt.Key.Key_Left: pygame.K_LEFT, Qt.Key.Key_Right: pygame.K_RIGHT,
    Qt.Key.Key_Up: pygame.K_UP, Qt.Key.Key_Down: pygame.K_DOWN,
    Qt.Key.Key_Tab: pygame.K_TAB,
    Qt.Key.Key_0: pygame.K_0,          # 2026-08-28: 编辑器"重置相机姿态"键迁移自空格
    Qt.Key.Key_Escape: pygame.K_ESCAPE,
    Qt.Key.Key_Z: pygame.K_z, Qt.Key.Key_Y: pygame.K_y,
    Qt.Key.Key_F9: pygame.K_F9,        # 分离批5: 暂停逻辑时钟 (2026-09-05)
    Qt.Key.Key_F10: pygame.K_F10,      # 分离批5: 步进 1 逻辑帧
    Qt.Key.Key_F11: pygame.K_F11,      # 全屏 (播放器路径判 K_F11)
}

_MIME_ASSET = 'application/x-loom-asset'   # 资源拖入视口的 mime 格式





def _qt_mods(mods):
    """Qt 修饰键 -> pygame 修饰位 (on_key_event 判 Ctrl 用)."""
    v = 0
    if mods & Qt.KeyboardModifier.ControlModifier:
        v |= pygame.KMOD_CTRL
    if mods & Qt.KeyboardModifier.ShiftModifier:
        v |= pygame.KMOD_SHIFT
    if mods & Qt.KeyboardModifier.AltModifier:
        v |= pygame.KMOD_ALT
    return v


def _qt_button(btn):
    """Qt 鼠标键 -> pygame 按钮号 (1=左 2=中 3=右)."""
    if btn == Qt.MouseButton.LeftButton:
        return 1
    if btn == Qt.MouseButton.MiddleButton:
        return 2
    if btn == Qt.MouseButton.RightButton:
        return 3
    return 0


def _qt_buttons(btns):
    """Qt 按钮组合 -> pygame get_pressed 三元组 (左, 中, 右)."""
    return (bool(btns & Qt.MouseButton.LeftButton),
            bool(btns & Qt.MouseButton.MiddleButton),
            bool(btns & Qt.MouseButton.RightButton))


class _ViewportEventBridge:
    """Qt 输入事件 -> 引擎状态字段（后端无关；与 GLViewport 逐字段同语义）。"""

    # ---------------- 鼠标事件 -> 引擎状态 ----------------
    def _phys(self, pos):
        """Qt 逻辑坐标 -> 物理像素 (引擎/GL 用物理像素, 与 pygame 时代一致)."""
        dpr = self.devicePixelRatioF()
        return (int(pos.x() * dpr), int(pos.y() * dpr))

    def _sync_mouse(self, pos):
        e = self.editor
        if e is None:
            return
        e.mouse_pos = self._phys(pos)
        e._mods = _qt_mods(QGuiApplication.keyboardModifiers())
        e.buttons = _qt_buttons(QGuiApplication.mouseButtons())

    def mousePressEvent(self, ev):
        e = self.editor
        if e is None:
            return
        self.setFocus()   # 点击视口即获键盘焦点 (WASD 相机移动)
        self._sync_mouse(ev.position())
        btn = _qt_button(ev.button())
        if btn:
            e.pressed.add(btn)
            e.mouse_press_pos[btn] = e.mouse_pos
            # 按下瞬间重置相机拖拽基线: mouseTracking 关时鼠标无 move 事件,
            # _cam_prev_mouse 可能过期, 不重置 dx 巨大 -> 右键跳视角 (2026-08-18)
            e._cam_prev_mouse = e.mouse_pos
        self._last_move = None
        super().mousePressEvent(ev)

    def mouseMoveEvent(self, ev):
        e = self.editor
        if e is None:
            return
        self._sync_mouse(ev.position())
        e.buttons = _qt_buttons(ev.buttons())
        # M32 玩家控制器转向: 相对上次 move 的位移 (播放模式用)
        if self._last_move is not None:
            d = ev.position() - self._last_move
            e.mouse_rel = (int(d.x()), int(d.y()))
        self._last_move = ev.position()
        super().mouseMoveEvent(ev)

    def mouseReleaseEvent(self, ev):
        e = self.editor
        if e is None:
            return
        self._sync_mouse(ev.position())
        btn = _qt_button(ev.button())
        if btn:
            e.released.add(btn)
            e.mouse_press_pos.pop(btn, None)
        self._last_move = None
        super().mouseReleaseEvent(ev)

    def wheelEvent(self, ev):
        e = self.editor
        if e is None:
            return
        e.mouse_pos = self._phys(ev.position())
        e.mouse_wheel = ev.angleDelta().y() / 120.0   # 向上 = +1 (与 pygame MOUSEWHEEL 同向)
        super().wheelEvent(ev)

    # ---------------- 键盘事件 (焦点在视口时) ----------------
    def keyPressEvent(self, ev):
        e = self.editor
        if e is None:
            return
        e._mods = _qt_mods(ev.modifiers())
        k = _QT_TO_PG.get(ev.key())
        if k is not None:
            e.key_state[k] = True
        e.on_key_event(SimpleNamespace(type='KEYDOWN', key=k or 0, mod=e._mods))
        super().keyPressEvent(ev)

    def keyReleaseEvent(self, ev):
        e = self.editor
        if e is None:
            return
        e._mods = _qt_mods(ev.modifiers())
        k = _QT_TO_PG.get(ev.key())
        if k is not None:
            e.key_state[k] = False
        e.on_key_event(SimpleNamespace(type='KEYUP', key=k or 0, mod=e._mods))
        super().keyReleaseEvent(ev)

    def key_pressed_array(self):
        """引擎 _key_pressed(): 按键快照 (dict/defaultdict; pygame 特殊键码
        超出 512 数组, 语义与 GLViewport.key_pressed_array 逐字段一致)."""
        from collections import defaultdict
        e = self.editor
        if e is None:
            return defaultdict(int)
        return defaultdict(int, {k: 1 for k, v in e.key_state.items() if v})

    # ---------------- 资源拖入视口 ----------------
    def dragEnterEvent(self, ev):
        if ev.mimeData().hasFormat(_MIME_ASSET):
            ev.acceptProposedAction()

    def dropEvent(self, ev):
        e = self.editor
        if e is None:
            return
        raw = bytes(ev.mimeData().data(_MIME_ASSET)).decode('utf-8', 'replace')
        try:
            key = json.loads(raw)
        except Exception:
            return
        it = e._find_asset((key.get('type'), key.get('key')))
        if it is not None:
            e._asset_drop_to_scene(it, self._phys(ev.position()))
        ev.acceptProposedAction()

    # ---------------- 播放模式鼠标锁定 ----------------
    def set_mouse_locked(self, locked):
        """引擎 set_mouse_locked 外部模式转发点: 播放期隐藏光标并捕获."""
        if locked:
            self.setCursor(Qt.CursorShape.BlankCursor)
            self.grabMouse()
        else:
            self.unsetCursor()
            self.releaseMouse()
