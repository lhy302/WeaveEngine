# -*- coding: utf-8 -*-
"""remote_viewport.py — 远程/虚拟显示下的离屏 GL readback 视口
（原 ui/loom_gui.py RemoteViewport 段，B4 批按类拆出）。

逐行未动（只搬家 + 类头加事件桥基类）：11+1 个后端无关事件桥方法改为继承
editor.viewport.event_bridge._ViewportEventBridge（与 GLViewport / VkViewport
同一份唯一实现）；makeCurrent（离屏 GL 上下文切换）是本类特有兼容接口，保留。
"""
import os
import sys
import time

import moderngl

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QCursor, QImage, QColor, QSurfaceFormat
from PySide6.QtWidgets import QWidget

from render.gl.version import (GL_MIN_MAJOR, GL_MIN_MINOR, GLVersionError,
                             require_gl_version)

from editor.viewport.event_bridge import _ViewportEventBridge
from gui.gl_viewport import _show_gl_floor_error


# =====================================================================
# RemoteViewport — 远程/虚拟显示下的 readback fallback（2026-10-20 白屏修复）
# =====================================================================
class RemoteViewport(_ViewportEventBridge, QWidget):
    # B4 收口注：11+1 个事件桥方法继承自 _ViewportEventBridge（唯一实现）；
    # key_pressed_array/_phys/_sync_mouse/mouse×3/wheel/key×2/set_mouse_locked/
    # dragEnter/drop 的本地拷贝逐字删除＝继承；makeCurrent（离屏上下文）保留。
    """离屏 GL 渲染 + QImage 显示，绕过 QOpenGLWidget 在远程/虚拟显示下的
    native present 失败（客户区白屏，但 QWidget.grab() 正常）。

    使用 --remote-mode 或 LOOM_REMOTE_MODE=1 启用。
    接口与 GLViewport 完全兼容，可无缝替换。

    工作方式：
      1) QOpenGLContext + QOffscreenSurface 创建离屏 GL（不依赖窗口原生 surface）
      2) moderngl 复用该 context
      3) 每帧渲染到 moderngl Framebuffer，fbo.read() 读回像素
      4) 用 QImage + QPixmap 显示到 QLabel（普通 QWidget paintEvent，稳定跨平台）
      5) 事件（鼠标/键盘）转发给 editor（同 GLViewport 逻辑）

    代价：每帧 GPU readback + QImage 上传，几 ms/帧；编辑器可接受。
    运行时（--run）不要用，因为延迟会比 native present 高一些。
    """

    def __init__(self, window, scene_path=None, width=1280, height=800):
        super().__init__()
        self._window = window
        self._scene_path = scene_path
        self._init_w = max(320, int(width))
        self._init_h = max(240, int(height))
        self.editor = None
        self.ctx = None
        self.init_error = None
        self._last_move = None

        # 2026-10-20 显示层修复：不用 QLabel.setPixmap（60fps 会触发 60 次 layout
        # 导致卡顿且画面不显示）。改用 QWidget.paintEvent 直接 QPainter.drawImage。
        self._current_img = None   # 当前帧的 QImage（_tick 更新，paintEvent 消费）
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setAcceptDrops(True)

        # 离屏 GL
        try:
            self._init_offscreen_gl()
        except Exception as _e:
            import traceback
            traceback.print_exc()
            self.init_error = repr(_e)
            if isinstance(_e, GLVersionError):
                _show_gl_floor_error(self, _e)

        # 2026-10-20 修复：EditorApp 不能在 __init__ 里创建 —— 那时
        # LoomGUI.viewport 还没赋值，EditorApp._seed_scene 会触发 gl_guard()
        # 访问 self._window.viewport.makeCurrent() 崩 AttributeError。
        # 用 QTimer.singleShot 延迟到事件循环启动后（LoomGUI.__init__ 已完成）。
        QTimer.singleShot(0, self._init_editor_deferred)

        # 渲染循环（2026-10-20：60fps —— readback 实测仅 3ms/帧，30fps 是人为保守限制）
        self._last_frame = time.perf_counter()
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(16)   # ~60fps

    # ---------------- 初始化 ----------------
    def _init_offscreen_gl(self):
        from PySide6.QtGui import QOpenGLContext, QOffscreenSurface
        fmt = QSurfaceFormat()
        # 2026-11-09 A0 (D1=B): 请求 4.3 core（地板）
        fmt.setVersion(GL_MIN_MAJOR, GL_MIN_MINOR)
        fmt.setProfile(QSurfaceFormat.OpenGLContextProfile.CoreProfile)
        fmt.setDepthBufferSize(24)
        fmt.setSamples(0)       # 无 MSAA（readback 路径用不上）
        fmt.setSwapInterval(0)
        self._gl_ctx = QOpenGLContext()
        self._gl_ctx.setFormat(fmt)
        if not self._gl_ctx.create():
            raise RuntimeError('QOpenGLContext.create 失败')
        self._surface = QOffscreenSurface()
        self._surface.setFormat(fmt)
        self._surface.create()
        if not self._gl_ctx.makeCurrent(self._surface):
            raise RuntimeError('QOpenGLContext.makeCurrent 失败')
        self.ctx = moderngl.create_context()
        require_gl_version(self.ctx, '编辑器离屏回读视口')   # A0 硬门
        self.ctx.enable(moderngl.DEPTH_TEST)
        # moderngl framebuffer（color + depth）
        color_tex = self.ctx.texture((self._init_w, self._init_h), 4)
        depth_tex = self.ctx.depth_texture((self._init_w, self._init_h))
        self._fbo = self.ctx.framebuffer(
            color_attachments=[color_tex],
            depth_attachment=depth_tex)

    def _init_editor_deferred(self):
        """延迟初始化 EditorApp —— 等 LoomGUI.__init__ 完成并设置 self.viewport 后。"""
        try:
            # 重新切到离屏 GL 上下文
            self._gl_ctx.makeCurrent(self._surface)
            self._init_editor()
            print('[Remote] EditorApp 创建成功 (离屏 GL readback 模式)')
        except Exception:
            import traceback
            traceback.print_exc()
            self.init_error = repr(sys.exc_info()[1])

    def _init_editor(self):
        from editor import EditorApp
        self.editor = EditorApp(self._init_w, self._init_h,
                                scene_path=self._scene_path,
                                view=self._window, ctx=self.ctx)
        self.editor._external_fb = self._fbo
        self._window.bind_editor(self.editor)
        from core.log import verbose
        verbose('[Remote] EditorApp 创建成功 (离屏 GL readback 模式)')

    # ---------------- 渲染循环 ----------------
    def _tick(self):
        e = self.editor
        if e is None or self.ctx is None:
            return
        try:
            self._gl_ctx.makeCurrent(self._surface)
            now = time.perf_counter()
            delta = min(now - self._last_frame, 0.1)
            self._last_frame = now
            # 尺寸同步（父窗口 resize 时更新）
            dpr = self.devicePixelRatioF()
            w = max(1, int(self.width() * dpr))
            h = max(1, int(self.height() * dpr))
            if (e.width, e.height) != (w, h):
                e.width, e.height = w, h
                self.ctx.viewport = (0, 0, w, h)
                # 重建 FBO（尺寸变了）
                try:
                    self._fbo.release()
                except Exception:
                    pass
                color_tex = self.ctx.texture((w, h), 4)
                depth_tex = self.ctx.depth_texture((w, h))
                self._fbo = self.ctx.framebuffer(
                    color_attachments=[color_tex],
                    depth_attachment=depth_tex)
                e._external_fb = self._fbo
            self._fbo.use()
            # 2026-11-07 收尾 (与 GLViewport._on_tick 对齐): 远程模式原来从不调用
            # _update_camera(), 也从不清理 pressed/released ——
            #   · 相机与 UI 树收不到任何输入 (点击/HUD 按钮/WASD/滚轮全无效);
            #   · e.pressed 只增不减, 按下一次就永远处于"按下态"。
            # 顺序与 _on_tick 逐行一致: 同步鼠标 -> _update_camera (内部先
            # _dispatch_ui_mouse 分发 UI) -> 清 wheel -> 清 pressed/released。
            gpos = QCursor.pos()
            lpos = self.mapFromGlobal(gpos)
            if self.rect().contains(lpos):
                e.mouse_pos = (int(lpos.x() * dpr), int(lpos.y() * dpr))
            e._update_camera()
            e.mouse_wheel = 0   # 读取后清零 (滚轮缩放, 同 _on_tick)
            e.pressed.clear()
            e.released.clear()
            # 2026-10-20 修复：RemoteViewport 漏了 GLViewport.paintGL 的异步逻辑线程启动，
            # 导致 _logic_async=True 时 advance_logic 从不被调用、播放模式 logic_steps 恒 0。
            _t0 = time.perf_counter()
            if not getattr(e, '_logic_async', False):
                e.advance_logic(delta)
            else:
                clk = e._ensure_split()
                if clk is not None:
                    e._start_logic_thread(clk)
            _t1 = time.perf_counter()
            e.render(delta)
            _t2 = time.perf_counter()
            # 读回像素 → 存 QImage → 触发 paintEvent
            # 2026-10-20 修复 Y 翻转：OpenGL fbo.read() 返回左下原点（从下往上），
            # QImage 默认左上原点（从上往下），需垂直镜像一次。
            data = self._fbo.read(components=3, alignment=1)
            _t3 = time.perf_counter()
            img = QImage(data, e.width, e.height, e.width * 3,
                         QImage.Format.Format_RGB888)
            # mirrored(horizontal=False, vertical=True) = 上下翻转
            self._current_img = img.mirrored(False, True)
            _t4 = time.perf_counter()
            self.update()                     # 异步请求重绘（不阻塞事件循环）
            # 2026-10-20 性能诊断：LOOM_REMOTE_PROFILE=1 时打印各段耗时
            if os.environ.get('LOOM_REMOTE_PROFILE') == '1':
                self._prof_n = getattr(self, '_prof_n', 0) + 1
                if self._prof_n % 30 == 0:  # 每 30 帧打一次（每秒 1 次）
                    print('[RPROF] logic=%.1fms render=%.1fms readback=%.1fms mirror=%.1fms'
                          % ((_t1-_t0)*1000, (_t2-_t1)*1000,
                             (_t3-_t2)*1000, (_t4-_t3)*1000))
        except Exception as ex:
            # 不刷屏：每 300 帧才打印一次
            self._tick_err_n = getattr(self, '_tick_err_n', 0) + 1
            if self._tick_err_n == 1 or self._tick_err_n % 300 == 0:
                print('[Remote] tick 异常 (%d): %r' % (self._tick_err_n, ex))

    # ---------------- 显示层 ----------------
    def paintEvent(self, ev):
        """2026-10-20：直接画 _current_img 到 widget（不用 QLabel，避免 layout 风暴）。"""
        from PySide6.QtGui import QPainter
        _tp0 = time.perf_counter()
        painter = QPainter(self)
        try:
            painter.fillRect(self.rect(), QColor(0, 0, 0))
            if self._current_img is not None:
                # 保持宽高比缩放到 widget 矩形
                painter.drawImage(self.rect(), self._current_img)
        finally:
            painter.end()
        if os.environ.get('LOOM_REMOTE_PROFILE') == '1':
            _dt = (time.perf_counter() - _tp0) * 1000
            self._pprof_n = getattr(self, '_pprof_n', 0) + 1
            if self._pprof_n % 60 == 0:
                print('[PPROF] paintEvent=%.1fms' % _dt)

    # ---------------- 兼容 GLViewport 接口 ----------------
    def makeCurrent(self):
        """Qt 兼容接口：切到离屏 GL 上下文（editor 里的 bind 调用需要）。"""
        if getattr(self, '_gl_ctx', None) is not None:
            try:
                self._gl_ctx.makeCurrent(self._surface)
            except Exception:
                pass
