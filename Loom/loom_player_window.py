# -*- coding: utf-8 -*-
"""loom_player_window.py — 玩家模式远程兼容窗口（Qt 离屏 GL + QImage 显示）。

2026-10-20 P0-1 白屏修复：
  - GLFW native present 在远程/虚拟显示环境下失败（客户区白屏，但渲染内容正常）
  - 本模块用离屏 GL 渲染 + QWidget.paintEvent 直接画 QImage，绕过 native present
  - 与编辑器 RemoteViewport 同一套已验证方案（编辑器白屏就是这么修的）

用法：
    from loom_player_window import run_player_window
    run_player_window('scene.json', width=1280, height=800)
"""
import os as _os
import sys as _sys
import time as _time


# tkinter keysym / Qt key -> pygame 常量映射（最小化，只覆盖游戏常用键）
_QT_TO_PG_MAP = None


def _build_qt_to_pg():
    """构造 Qt.Key -> pygame 常量映射（与编辑器 ui/loom_gui._QT_TO_PG 一致）。"""
    global _QT_TO_PG_MAP
    if _QT_TO_PG_MAP is not None:
        return _QT_TO_PG_MAP
    import pygame
    from PySide6.QtCore import Qt
    _QT_TO_PG_MAP = {
        Qt.Key.Key_W: pygame.K_w, Qt.Key.Key_S: pygame.K_s,
        Qt.Key.Key_A: pygame.K_a, Qt.Key.Key_D: pygame.K_d,
        Qt.Key.Key_Q: pygame.K_q, Qt.Key.Key_E: pygame.K_e,
        Qt.Key.Key_R: pygame.K_r, Qt.Key.Key_F: pygame.K_f,
        Qt.Key.Key_Z: pygame.K_z, Qt.Key.Key_X: pygame.K_x,
        Qt.Key.Key_C: pygame.K_c, Qt.Key.Key_V: pygame.K_v,
        Qt.Key.Key_Left: pygame.K_LEFT, Qt.Key.Key_Right: pygame.K_RIGHT,
        Qt.Key.Key_Up: pygame.K_UP, Qt.Key.Key_Down: pygame.K_DOWN,
        Qt.Key.Key_Space: pygame.K_SPACE,
        Qt.Key.Key_Shift: pygame.K_LSHIFT,
        Qt.Key.Key_Control: pygame.K_LCTRL,
        Qt.Key.Key_Escape: pygame.K_ESCAPE,
        Qt.Key.Key_Tab: pygame.K_TAB,
        Qt.Key.Key_Return: pygame.K_RETURN,
        Qt.Key.Key_F9: pygame.K_F9,
        Qt.Key.Key_F10: pygame.K_F10,
        Qt.Key.Key_F11: pygame.K_F11,
        Qt.Key.Key_0: pygame.K_0,
    }
    return _QT_TO_PG_MAP


class _PlayerWidget:
    """延迟构造（先建 QApplication，再建 widget）。"""

    @staticmethod
    def create(scene_path, width, height, title):
        from PySide6.QtCore import Qt, QTimer
        from PySide6.QtGui import (QImage, QPainter, QColor, QSurfaceFormat,
                                   QOpenGLContext, QOffscreenSurface)
        from PySide6.QtWidgets import QWidget
        import moderngl

        class PlayerWidget(QWidget):
            def __init__(self):
                super().__init__()
                self.setWindowTitle(title or 'Loom Player')
                self.resize(width, height)
                self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
                self.setStyleSheet('background: black;')
                self._current_img = None
                self._engine = None
                self._last_frame = _time.perf_counter()
                # 离屏 GL
                self._gl_ctx = QOpenGLContext()
                fmt = QSurfaceFormat()
                fmt.setVersion(3, 3)
                fmt.setProfile(QSurfaceFormat.OpenGLContextProfile.CoreProfile)
                fmt.setDepthBufferSize(24)
                fmt.setSamples(0)
                fmt.setSwapInterval(0)
                self._gl_ctx.setFormat(fmt)
                if not self._gl_ctx.create():
                    raise RuntimeError('QOpenGLContext.create 失败')
                self._surface = QOffscreenSurface()
                self._surface.setFormat(fmt)
                self._surface.create()
                if not self._gl_ctx.makeCurrent(self._surface):
                    raise RuntimeError('makeCurrent 失败')
                self.ctx = moderngl.create_context()
                self.ctx.enable(moderngl.DEPTH_TEST)
                self.ctx.enable(moderngl.CULL_FACE)
                self.ctx.front_face = 'cw'
                # FBO
                self._fbo = self.ctx.framebuffer(
                    color_attachments=[self.ctx.texture((width, height), 4)],
                    depth_attachment=self.ctx.depth_texture((width, height)))
                # 延迟建引擎（等 widget 就绪）
                QTimer.singleShot(0, self._init_engine)
                # 渲染循环
                self._timer = QTimer(self)
                self._timer.timeout.connect(self._tick)
                self._timer.start(16)   # 60fps

            def _init_engine(self):
                try:
                    self._gl_ctx.makeCurrent(self._surface)
                    from runtime import PlayerApp
                    self._engine = PlayerApp(scene_path, width, height,
                                              title=title, ctx=self.ctx)
                    self._engine._external_fb = self._fbo
                    print('[PlayerWindow] EditorApp 创建成功（离屏 GL readback 模式）')
                except Exception:
                    import traceback
                    traceback.print_exc()

            def _tick(self):
                e = self._engine
                if e is None:
                    return
                try:
                    self._gl_ctx.makeCurrent(self._surface)
                    now = _time.perf_counter()
                    dt = min(now - self._last_frame, 0.1)
                    self._last_frame = now
                    dpr = self.devicePixelRatioF()
                    w = max(1, int(self.width() * dpr))
                    h = max(1, int(self.height() * dpr))
                    if (e.width, e.height) != (w, h):
                        e.width, e.height = w, h
                        self.ctx.viewport = (0, 0, w, h)
                        try:
                            self._fbo.release()
                        except Exception:
                            pass
                        self._fbo = self.ctx.framebuffer(
                            color_attachments=[self.ctx.texture((w, h), 4)],
                            depth_attachment=self.ctx.depth_texture((w, h)))
                        e._external_fb = self._fbo
                    self._fbo.use()
                    if not getattr(e, '_logic_async', False):
                        e.advance_logic(dt)
                    else:
                        clk = e._ensure_split()
                        if clk is not None:
                            e._start_logic_thread(clk)
                    e.render(dt)
                    data = self._fbo.read(components=3, alignment=1)
                    img = QImage(data, e.width, e.height, e.width * 3,
                                 QImage.Format.Format_RGB888)
                    self._current_img = img.mirrored(False, True)
                    self.update()
                except Exception as ex:
                    n = getattr(self, '_tick_err_n', 0) + 1
                    self._tick_err_n = n
                    if n <= 3 or n % 100 == 0:
                        print('[PlayerWindow] tick 异常 (%d): %r' % (n, ex))

            def paintEvent(self, ev):
                painter = QPainter(self)
                try:
                    painter.fillRect(self.rect(), QColor(0, 0, 0))
                    if self._current_img is not None:
                        painter.drawImage(self.rect(), self._current_img)
                finally:
                    painter.end()

            def keyPressEvent(self, ev):
                km = _build_qt_to_pg()
                k = km.get(ev.key())
                if k is not None and self._engine is not None:
                    self._engine.key_state[k] = True
                    try:
                        from types import SimpleNamespace
                        self._engine.on_key_event(SimpleNamespace(
                            type='KEYDOWN', key=k, mod=0))
                    except Exception:
                        pass
                super().keyPressEvent(ev)

            def keyReleaseEvent(self, ev):
                km = _build_qt_to_pg()
                k = km.get(ev.key())
                if k is not None and self._engine is not None:
                    self._engine.key_state[k] = False
                    try:
                        from types import SimpleNamespace
                        self._engine.on_key_event(SimpleNamespace(
                            type='KEYUP', key=k, mod=0))
                    except Exception:
                        pass
                super().keyReleaseEvent(ev)

            def mousePressEvent(self, ev):
                if self._engine is None:
                    return
                self.setFocus()
                p = self._phys(ev.position())
                self._engine.mouse_pos = p
                btn = self._qt_button(ev.button())
                if btn:
                    self._engine.pressed.add(btn)
                    self._engine.mouse_press_pos[btn] = p
                    try:
                        self._engine._cam_prev_mouse = p
                    except Exception:
                        pass
                super().mousePressEvent(ev)

            def mouseMoveEvent(self, ev):
                if self._engine is None:
                    return
                self._engine.mouse_pos = self._phys(ev.position())
                super().mouseMoveEvent(ev)

            def mouseReleaseEvent(self, ev):
                if self._engine is None:
                    return
                self._engine.mouse_pos = self._phys(ev.position())
                btn = self._qt_button(ev.button())
                if btn:
                    self._engine.released.add(btn)
                    self._engine.mouse_press_pos.pop(btn, None)
                super().mouseReleaseEvent(ev)

            def wheelEvent(self, ev):
                if self._engine is not None:
                    self._engine.mouse_wheel = ev.angleDelta().y() / 120.0
                super().wheelEvent(ev)

            def _phys(self, pos):
                dpr = self.devicePixelRatioF()
                return (int(pos.x() * dpr), int(pos.y() * dpr))

            @staticmethod
            def _qt_button(qt_btn):
                from PySide6.QtCore import Qt
                if qt_btn == Qt.MouseButton.LeftButton:
                    return 1
                if qt_btn == Qt.MouseButton.MiddleButton:
                    return 2
                if qt_btn == Qt.MouseButton.RightButton:
                    return 3
                return None

            def closeEvent(self, ev):
                self._timer.stop()
                try:
                    if self._engine is not None:
                        self._engine._dispatch_application_quit()
                except Exception:
                    pass
                super().closeEvent(ev)

        return PlayerWidget()


def run_player_window(scene_path, width=1280, height=800, title=None):
    """玩家模式入口：Qt 离屏 GL 渲染 + QImage 显示。"""
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication(_sys.argv)
    w = _PlayerWidget.create(scene_path, width, height, title)
    w.show()
    _sys.exit(app.exec())
