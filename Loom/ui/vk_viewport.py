# -*- coding: utf-8 -*-
"""vk_viewport.py — VK 编辑器视口（Q-B7-47-1 五阶段·阶段 4）。

基于 rendercanvas.qt.QRenderWidget（BaseRenderCanvas + QWidget，可直接放进
Qt 布局）+ get_context("wgpu")。present_method 取 **bitmap**（默认）：
  · grab() 截图可用（编辑器截图 / 远程白屏兜底是硬需求；实测中心像素=绘制内容）；
  · 帧时间实测 ~6.9ms（145fps），在 16.7ms 编辑器帧预算内；
  · screen 上屏 grab() 拿到的是纯背景（probe_dualwin 实测），故不采用。

事件桥（_ViewportEventBridge）：_phys / _sync_mouse / mouse Press/Move/Release /
wheel / key Press/Release / key_pressed_array / dragEnter / drop / set_mouse_locked
—— 这 11+1 个方法是**纯「写引擎状态字段」**（与宿主渲染后端无关）。GL 的
GLViewport 持有第一份、RemoteViewport 持有第二份（既有债；人类纪律「GL 一行不许
动」不允许本次归并）；本文件是 VK 宿主的**单一实现**（规则 5.5：VK 侧不再有第二份）。

GL/wgpu 同进程顺序约束（P6 门实测，写进 probe 证据）：
  · request_adapter_sync 会破坏已存在的 moderngl 上下文（buffer() 报
    GL_INVALID_OPERATION），但 Qt 仍误报 current；
  · 破坏是一次性的：一次 makeCurrent() 之后任意多次 wgpu submit 不再破坏；
  · 推荐顺序 = 先建 wgpu device 再建 GL 上下文。VK 编辑器（本文件）进程内
    根本不建 GL 上下文，天然不受影响；双视口并存探针（tests/_tmp/probe_s4_dualwin.py）
    按两种顺序各自取证。
"""
import json
import time

from PySide6.QtCore import QTimer, Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QWidget

import rendercanvas.qt as rq

# 复用 GL 视口的 Qt 事件翻译常量（唯一实现：ui/loom_gui.py 顶部）。
# 只 import 常量/纯函数，不触发任何 GL 上下文动作。
from ui.loom_gui import _QT_TO_PG, _qt_buttons, _qt_mods, _qt_button, _MIME_ASSET


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


class VkViewport(_ViewportEventBridge, rq.QRenderWidget):
    """VK 编辑器视口：QRenderWidget(bitmap) + VkEditorApp。

    MRO：_ViewportEventBridge 在前 —— QWidget 自带 no-op 的 mousePressEvent 等
    事件槽，桥在其后会被遮住（事件永远到不了引擎状态字段）。

    帧驱动：rendercanvas 调度器（request_draw 注册 _draw_frame）；每帧 = 
    advance_logic + editor.render（与 GLViewport.paintGL 同序，减去 GL 专有的
    widget-FBO 缓存 / FPS 预画 blit / 频闪读回诊断三段）。
    """

    def __init__(self, window, scene_path=None, width=1280, height=800):
        super().__init__(size=(max(64, int(width)), max(64, int(height))),
                         present_method='bitmap')
        self._window = window          # LoomGUI（IEditorView 宿主）
        self._scene_path = scene_path
        self._init_w, self._init_h = max(64, int(width)), max(64, int(height))
        self.editor = None             # VkEditorApp（_init_deferred 里建）
        self.ctx = None                # rendercanvas wgpu 上下文（_vk_ctx 同一对象）
        self.init_error = None
        self.configured = False
        self._last_move = None         # mouse_rel 计算用（GLViewport 同名字段）
        self.frame_errors = []         # 渲染循环内异常（冒烟门断言 0 条）
        self._last_frame_time = time.perf_counter()
        self._frames_done = 0
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setAcceptDrops(True)
        # 与 RemoteViewport 同款：EditorApp 延迟到事件循环启动后建
        # （LoomGUI.__init__ 里 viewport 赋值/工具栏构建完成后才安全）。
        QTimer.singleShot(0, self._init_deferred)

    # ---------------- 初始化（wgpu 装配） ----------------
    def _init_deferred(self):
        try:
            import wgpu
            # P6 顺序约束推荐侧：先建 wgpu device（本视口进程内随后没有任何
            # moderngl/GL 上下文创建，天然满足「先 wgpu 后 GL」）。
            adapter = wgpu.gpu.request_adapter_sync(power_preference='high-performance')
            if adapter is None:
                raise RuntimeError('无可用 Vulkan 适配器 (request_adapter_sync 返回 None)')
            from loom_backend_guard import (adapter_info_dict, adapter_backend,
                                            require_vulkan_api)
            _dev_info = adapter_info_dict(adapter)
            _be = adapter_backend(_dev_info)
            if _be and _be != 'vulkan':
                raise RuntimeError('选中了非 Vulkan 后端 (%s)' % (_be,))
            require_vulkan_api('VK 编辑器视口', adapter_info=_dev_info)
            device = adapter.request_device_sync()
            self.ctx = self.get_context("wgpu")
            fmt = self.ctx.get_preferred_format(adapter)
            # 与 vk_player 同口径：显式请求非 srgb 8bit 格式（防二次伽马，双后端一致）。
            if isinstance(fmt, str) and fmt.endswith('-srgb'):
                fmt = fmt[:-5]
            self.ctx.configure(device=device, format=fmt,
                               usage=wgpu.TextureUsage.RENDER_ATTACHMENT)
            from editor import VkEditorApp
            self.editor = VkEditorApp(self._init_w, self._init_h,
                                      scene_path=self._scene_path,
                                      view=self._window,
                                      device=device, present_format=fmt)
            self.editor._vk_ctx = self.ctx      # VkFrameExecutor 帧提交协议
            self._window.bind_editor(self.editor)
            self.configured = True
            self.request_draw(self._draw_frame)
            from loom_log import verbose
            verbose('[VkViewport] VkEditorApp 创建成功 (QRenderWidget bitmap 模式, '
                    'format=%s)' % fmt)
            print('[VkViewport] VK 编辑器就绪: device=%s | format=%s'
                  % (adapter.info.get('device', '?'), fmt))
        except Exception as _e:
            import traceback
            traceback.print_exc()
            self.init_error = repr(_e)

    # ---------------- 帧驱动 ----------------
    def _draw_frame(self, *args, **kwargs):
        """一帧 = advance_logic + editor.render（GLViewport.paintGL 的 VK 对应段）。

        rendercanvas 契约：本回调返回后框架 present（bitmap 复制上屏）。
        """
        e = self.editor
        if e is None or not self.configured:
            return
        try:
            # 尺寸同步（物理像素，与 editor.width/height、mouse 坐标同一口径）
            try:
                w, h = self.ctx.physical_size
            except Exception:
                w, h = e.width, e.height
            w, h = max(1, int(w)), max(1, int(h))
            if (e.width, e.height) != (w, h):
                e.width, e.height = w, h
                e.gui_dirty = True
            now = time.perf_counter()
            delta = min(now - self._last_frame_time, 0.1)
            self._last_frame_time = now
            # 逻辑推进（GLViewport.paintGL 同段；_logic_async 恒 False，见 VkEditorApp）
            if not getattr(e, '_logic_async', False):
                e.advance_logic(delta)
            else:
                clk = e._ensure_split()
                if clk is not None:
                    e._start_logic_thread(clk)
            e.render(delta)   # 纯渲染任务流水线（plan 执行 + 叠加层 + 交互）
            self._frames_done += 1
        except Exception as _e:
            if len(self.frame_errors) < 20:
                import traceback
                traceback.print_exc()
            self.frame_errors.append(repr(_e))

    # ---------------- GL 视口兼容面（宿主调用点不改） ----------------
    def makeCurrent(self):
        """兼容接口（GLViewport/RemoteViewport 均有）：VK 无 current 概念，no-op。

        editor 侧的 GL 守卫（如 mark_dirty 路径的 makeCurrent 钩子）在 VK 编辑器
        上走到这里时显式 no-op —— 与 GL 语义差异已留痕（VK 无 GL 状态可绑定）。
        """
        return None

    def key_pressed_array(self):
        return _ViewportEventBridge.key_pressed_array(self)


# 延迟导入说明：SimpleNamespace 供事件桥的 on_key_event 构造 KEYDOWN/KEYUP 事件
# （GLViewport 同款），放模块底部 import 保持顶部轻。
from types import SimpleNamespace  # noqa: E402
