# -*- coding: utf-8 -*-
"""gl_viewport.py — GL 编辑器视口（原 ui/loom_gui.py GLViewport 段，B4 批按类拆出）。

QOpenGLWidget 承载 moderngl 上下文 (initializeGL 建), 每帧 paintGL 调
editor.render。逐行未动（只搬家 + 类头加事件桥基类）：
  B4 批（2026-11-21）S5 留痕收口 —— 鼠标/键盘/滚轮/拖拽/锁标 11+1 个后端无关
  事件桥方法改为继承 editor.viewport.event_bridge._ViewportEventBridge
  （与 RemoteViewport / VkViewport 同一份唯一实现，方法体逐字删除＝继承）。
"""
import os
import time

import numpy as np
import moderngl

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QMessageBox
from PySide6.QtOpenGLWidgets import QOpenGLWidget

from render.gl.version import (GL_MIN_MAJOR, GL_MIN_MINOR, GLVersionError,
                             require_gl_version)

from editor.viewport.event_bridge import _ViewportEventBridge


# =====================================================================
# GLViewport — moderngl 视口 + 事件 -> 引擎状态
# =====================================================================
def _show_gl_floor_error(widget, err):
    """GL 地板不满足：把原因弹到用户面前（2026-11-09 A0 硬要求：不得静默黑屏）。

    只负责「可见」：详细诊断已由 loom_gl_version.require_gl_version 打印到控制台，
    这里补一个模态框，避免用户只看到黑视口却以为「引擎在跑、只是场景空」。
    """
    def _pop():
        try:
            QMessageBox.critical(
                widget, '无法启动渲染',
                '当前显卡/驱动不满足 OpenGL %d.%d core 要求，渲染已停止。\n\n'
                '详见控制台 [GL] 开头的诊断（含显卡/驱动版本）；'
                '先更新显卡驱动，或改用 Vulkan 后端：--backend vulkan'
                % (GL_MIN_MAJOR, GL_MIN_MINOR))
        except Exception:
            pass
    try:
        QTimer.singleShot(0, _pop)
    except Exception:
        pass


class GLViewport(_ViewportEventBridge, QOpenGLWidget):
    # B4 收口注：11+1 个事件桥方法（_phys/_sync_mouse/mouse×3/wheel/key×2/
    # key_pressed_array/dragEnter/drop/set_mouse_locked）继承自
    # _ViewportEventBridge（唯一实现），本类只保留 GL 生命周期四方法。
    """QOpenGLWidget 承载 moderngl 上下文 (initializeGL 建), 每帧 paintGL 调
    editor.render; 鼠标/键盘/滚轮事件写入引擎状态字段并调 on_key_event 钩子."""

    def __init__(self, window, scene_path=None, width=1280, height=800):
        super().__init__()
        self._window = window
        self._scene_path = scene_path
        self._init_w, self._init_h = width, height
        self.editor = None          # EditorApp (initializeGL 里建, 需要 GL 上下文)
        self.ctx = None             # moderngl 上下文
        self._glf = None            # QOpenGLFunctions (clear 用, initializeGL 里建)
        self.init_error = None
        self._last_move = None      # mouse_rel 计算用
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setAcceptDrops(True)

    # ---------------- GL 生命周期 ----------------
    def initializeGL(self):
        """Qt 已 current 上下文 -> moderngl 复用 (spike test_qt_gl.py 已验证).
        然后创建 EditorApp (嵌入式 ctx 模式, 不建 pygame 窗口)."""
        try:
            self.ctx = moderngl.create_context()
            # 2026-11-09 A0 (D1=B): 4.3 core 地板硬门。Qt 可能静默给更低版本 -> 明确报错。
            require_gl_version(self.ctx, '编辑器 GL 视口')
            self.ctx.enable(moderngl.DEPTH_TEST)
            from editor import EditorApp
            self.editor = EditorApp(self._init_w, self._init_h,
                                    scene_path=self._scene_path,
                                    view=self._window, ctx=self.ctx)
            self._window.bind_editor(self.editor)
            from core.log import verbose
            verbose("[Qt] EditorApp 创建成功 (嵌入式 ctx 模式)")
        except Exception as _e:
            import traceback
            traceback.print_exc()
            self.init_error = repr(_e)
            if isinstance(_e, GLVersionError):
                _show_gl_floor_error(self, _e)

    def paintGL(self):
        e = self.editor
        if e is None or self.ctx is None:
            return
        # ★M3 (2026-09-09) 主线程分段归因: paintGL 总耗时 = 宿主 Qt/GL 胶水 + 引擎段.
        #   qt_glue = mt_paint_total − mt_paint_advance − mt_paint_render (探针侧算).
        _t_paint = e._prof_t0() if hasattr(e, '_prof_t0') else 0.0
        # 2026-08-18 关键: 缓存 Qt 刚绑定的 widget FBO. moderngl 的 scope 退出
        # 会把 GL framebuffer 绑定恢复成 0 (窗口默认), detect_framebuffer() 只能
        # 拿到"当前绑定"—— 若当前已是 0 就画到 0 (看不见). 引擎外部模式所有
        # 绘制统一走缓存的 _external_fb (engine._screen_fb()).
        # ★2026-09-06 编译版低TPS偶发闪黑修复: widget FBO **缓存一次稳定复用**,
        # 不再每帧 detect —— 帧首 _on_tick 空窗预画 (FPS 缓冲) 会在 paintGL
        # 之前做 GL 操作, 离屏 FBO 绑定残留导致 detect 拿错 → 整帧画到看不见
        # 的 FBO = 黑屏一拍 (与逻辑帧节拍耦合交替, 编译版帧时序不同更易踩)。
        # widget FBO 本身生命周期 = widget (resize 不换 FBO 对象, 只换尺寸),
        # 首帧 detect 后缓存; 视口尺寸走 viewport 状态独立同步。
        if getattr(self, '_widget_fb', None) is None:
            self._widget_fb = self.ctx.detect_framebuffer()
        e._external_fb = self._widget_fb
        dpr = self.devicePixelRatioF()
        w, h = max(1, int(self.width() * dpr)), max(1, int(self.height() * dpr))
        if (e.width, e.height) != (w, h):
            e.width, e.height = w, h
            self.ctx.viewport = (0, 0, w, h)
        # 2026-10-20 白屏修复 P1：GL 诊断日志（LOOM_GL_DEBUG=1 时输出）。
        # 报告要求：size/DPR/FBO/paintGL 计数，用于定位 native present 失败。
        if os.environ.get('LOOM_GL_DEBUG') == '1':
            self._dbg_paint_n = getattr(self, '_dbg_paint_n', 0) + 1
            first = self._dbg_paint_n == 1
            every300 = self._dbg_paint_n % 300 == 0
            if first or every300:
                try:
                    scr = self.window().windowHandle().screen() if self.window().windowHandle() else None
                    scr_name = scr.name() if scr else '?'
                    scr_geom = scr.geometry() if scr else None
                    scr_dpr = scr.devicePixelRatio() if scr else '?'
                    print('[GLDBG] paint=%d widget=%dx%d dpr=%.2f fbo=%dx%d '
                          'screen=%s geom=%s dpr=%s fmt=%s'
                          % (self._dbg_paint_n, self.width(), self.height(),
                             dpr, w, h, scr_name, scr_geom, scr_dpr,
                             self.format().version()))
                    err = self.ctx.error
                    if err != 'GL_NO_ERROR':
                        print('[GLDBG] glGetError: %s' % err)
                except Exception as _e:
                    print('[GLDBG] 诊断异常: %r' % (_e,))
        # ★2026-09-07 相机卡顿修复②: 渲染帧 dt 时钟 time.time()->perf_counter
        # (引擎 _last_frame_time 同步切)。time.time() 走系统定时器 (1-15.6ms 粒度),
        # 轻帧 (6ms) 下 delta 量化 = 逻辑时钟/相机速率逐帧抖动源之一;
        # perf_counter 100ns 单调, advance_logic 与 _update_camera 输入一致。
        # 时间轴/alpha 语义零变化 (同为墙钟间隔, 只换高精度单调钟)。
        now = time.perf_counter()
        delta = min(now - e.last_frame_time, 0.1)
        e.last_frame_time = now
        # FPS 缓冲 (2026-09-06 实验): 有预画成品 → 整块 blit 上屏, 跳过重画.
        # 消费后仍走 advance_logic (逻辑时间轴照常推进; 渲染输出=预画帧).
        rb = getattr(e, '_render_buf', None)
        if rb is not None and rb.has_ready():
            e._external_fb = e._external_fb or self.ctx.detect_framebuffer()
            if rb.blit(self.ctx, e._screen_fb()):
                _t = e._prof_t0() if hasattr(e, '_prof_t0') else 0.0
                e.advance_logic(delta)
                if _t:
                    e._prof_add('mt_paint_advance', _t)
                e._update_fps()
                if _t_paint:
                    e._prof_add('mt_paint_total', _t_paint)
                return
            rb.reset()
        # 核心任务流水线彻底解耦 (2026-10-01):
        # 逻辑任务流水线 (Logic Pipeline) 由专用线程独立以固定 TPS 推进;
        # 渲染任务流水线 (Render Pipeline) 纯粹消费快照, 在核心调用上彻底解耦!
        if not getattr(e, '_logic_async', False):
            _t = e._prof_t0() if hasattr(e, '_prof_t0') else 0.0
            e.advance_logic(delta)
            if _t:
                e._prof_add('mt_paint_advance', _t)
        else:
            clk = e._ensure_split()
            if clk is not None:
                e._start_logic_thread(clk)
        _t = e._prof_t0() if hasattr(e, '_prof_t0') else 0.0
        e.render(delta)   # 纯粹的渲染任务流水线
        if _t:
            e._prof_add('mt_paint_render', _t)
        # ★频闪诊断 (2026-09-06, LOOM_FLICKER_DEBUG=1): 每帧读回中心 1px,
        # 连续暗帧 (清屏色级) 打印渲染状态快照 — 用户复现频闪时抓真凶。
        if os.environ.get('LOOM_FLICKER_DEBUG') == '1':
            try:
                data = self.ctx.detect_framebuffer().read(
                    viewport=(e.width // 2, e.height // 2, 1, 1), components=3)
                r, g, b = data[0], data[1], data[2]
                dark = (r < 40 and g < 40 and b < 60)
                self._flick_n = getattr(self, '_flick_n', 0) + 1
                if dark:
                    self._flick_dark = getattr(self, '_flick_dark', 0) + 1
                    if self._flick_dark <= 5 or self._flick_dark % 30 == 0:
                        it = getattr(e, '_interp', None)
                        print('[flick] frame=%d rgb=(%d,%d,%d) playing=%s '
                              'steps=%s alpha=%.3f buckets=%d gen=%s '
                              'render_world=%s vp_nan=%s'
                              % (self._flick_n, r, g, b, e.is_playing,
                                 getattr(getattr(e, '_clock', None), 'steps', '?'),
                                 getattr(getattr(e, '_clock', None), 'alpha', -1),
                                 len(getattr(e, '_render_buckets', []) or []),
                                 getattr(e, '_logic_gen', '?'),
                                 'None' if getattr(e, '_render_world', None) is None else 'ok',
                                 bool(np.isnan(e._vp).any())))
            except Exception:
                pass
        if _t_paint:
            e._prof_add('mt_paint_total', _t_paint)

    def paintEvent(self, ev):
        """★M3-N6: 包住 Qt 的 paintEvent (内含 paintGL + 缓冲交换) ——
        mt_paint_event − mt_paint_total = 交换/驱动阻塞 + Qt 开销, 用于判断
        主线程非 paintGL 时间是否真的是"等 GPU"。"""
        e = self.editor
        _t = e._prof_t0() if (e is not None and hasattr(e, '_prof_t0')) else 0.0
        super().paintEvent(ev)
        if _t:
            e._prof_add('mt_paint_event', _t)

    def resizeEvent(self, ev):
        super().resizeEvent(ev)
        e = self.editor
        if e is not None and self.ctx is not None:
            dpr = self.devicePixelRatioF()
            e.width, e.height = max(1, int(self.width() * dpr)), max(1, int(self.height() * dpr))
            self.ctx.viewport = (0, 0, e.width, e.height)
            e.gui_dirty = True

