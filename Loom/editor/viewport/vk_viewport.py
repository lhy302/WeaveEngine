"""vk_viewport.py — VK 编辑器视口（Q-B7-47-1 五阶段·阶段 4）。

基于 rendercanvas.qt.QRenderWidget（BaseRenderCanvas + QWidget，可直接放进
Qt 布局）+ get_context("wgpu")。present_method 取 **bitmap**（默认）：
  · grab() 截图可用（编辑器截图 / 远程白屏兜底是硬需求；实测中心像素=绘制内容）；
  · 帧时间实测 ~6.9ms（145fps），在 16.7ms 编辑器帧预算内；
  · screen 上屏 grab() 拿到的是纯背景（probe_dualwin 实测），故不采用。

事件桥（_ViewportEventBridge）：_phys / _sync_mouse / mouse Press/Move/Release /
wheel / key Press/Release / key_pressed_array / dragEnter / drop / set_mouse_locked
—— 这 11+1 个方法是**纯「写引擎状态字段」**（与宿主渲染后端无关）。B4 批（2026-11-21）S5 留痕收口：GL/Remote/VK 三份逐字段拷贝已收敛为
editor/viewport/event_bridge.py 的同一份基类，本类改为继承（事件桥方法体
逐字未动，MRO 约定照旧）。

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

# 事件桥与 Qt 事件翻译常量的唯一实现：editor/viewport/event_bridge.py（B4 收口）。
# 只 import 常量/纯函数，不触发任何 GL 上下文动作。
# 事件桥与 Qt 事件翻译常量 = editor/viewport/event_bridge.py（B4 收口的唯一实现；
# 原 ui/loom_gui.py 顶部拷贝，GL/Remote/VK 三端共用同一份 _ViewportEventBridge）。
from editor.viewport.event_bridge import (
    _ViewportEventBridge, _QT_TO_PG, _qt_buttons, _qt_mods, _qt_button, _MIME_ASSET,
)


def _acquire_vk_device():
    """请求 Vulkan 适配器 + 过 Vulkan 地板闸 + 建 device —— **唯一探测实现**。

    2026-11-25 终审 P0-1（人类 2026-11-24 指令「编辑器启动时 VK 失败 → 自动改写配置为
    opengl + 提示」）: 启动期探测与真正装配必须共用**同一份判据**（规则 5.5）——否则
    探测说能装、装配又按另一套判据失败（或反之），用户看到的提示与实际行为对不上。

    返回 (adapter, device, adapter_info)；失败原样抛出（VkBackendInitError / RuntimeError）。
    """
    import wgpu
    adapter = wgpu.gpu.request_adapter_sync(power_preference='high-performance')
    if adapter is None:
        raise RuntimeError('无可用 Vulkan 适配器 (request_adapter_sync 返回 None)')
    from hostenv.backend_guard import (adapter_info_dict, adapter_backend,
                                       require_vulkan_api)
    info = adapter_info_dict(adapter)
    be = adapter_backend(info)
    if be and be != 'vulkan':
        raise RuntimeError('选中了非 Vulkan 后端 (%s)' % (be,))
    require_vulkan_api('VK 编辑器视口', adapter_info=info)
    device = adapter.request_device_sync()
    return adapter, device, info


def probe_vk_ready():
    """启动期探测 VK 可装配性（**不建视口**，宿主据此决定走 VK 还是直接 GL）。

    为什么用「先探测再建视口」而不是「建了 VkViewport 再销毁重建」（P0-1 修法选择）:
      · VkViewport 的 wgpu 装配本来就是**延迟**的（QTimer.singleShot(0, _init_deferred)，
        因为 VkEditorApp 需要 LoomGUI 构建完成后才安全）—— 构造之后立刻读 init_error
        恒为 None，拿不到失败；
      · 等延迟 init 失败再销毁/重建，_build_central 早已把死视口装进布局，替换要动布局、
        已启动的渲染/刷新定时器与 rendercanvas 上下文，Qt 侧风险高且不可测。
    所以采用「探测失败就不建 VkViewport」: 启动期一次性选择（**不是**热切换，与裁决①
    「重启编辑器生效」不冲突），GL 视口在 _build_central 之前就位，本次启动编辑器可用。

    返回 (ok, reason, ready):
      ok=True  -> ready = (adapter, device, info)，交给 VkViewport(vk_ready=...) 复用；
      ok=False -> reason = 失败原因文本（给可见提示用），ready=None。
    """
    try:
        return True, None, _acquire_vk_device()
    except Exception as e:
        return False, (str(e) or repr(e)), None


class VkViewport(_ViewportEventBridge, rq.QRenderWidget):
    """VK 编辑器视口：QRenderWidget(bitmap) + VkEditorApp。

    MRO：_ViewportEventBridge 在前 —— QWidget 自带 no-op 的 mousePressEvent 等
    事件槽，桥在其后会被遮住（事件永远到不了引擎状态字段）。

    帧驱动：rendercanvas 调度器（request_draw 注册 _draw_frame）；每帧 = 
    advance_logic + editor.render（与 GLViewport.paintGL 同序，减去 GL 专有的
    widget-FBO 缓存 / FPS 预画 blit / 频闪读回诊断三段）。
    """

    def __init__(self, window, scene_path=None, width=1280, height=800,
                 vk_ready=None, on_init_error=None):
        super().__init__(size=(max(64, int(width)), max(64, int(height))),
                         present_method='bitmap')
        self._window = window          # LoomGUI（IEditorView 宿主）
        self._scene_path = scene_path
        self._init_w, self._init_h = max(64, int(width)), max(64, int(height))
        # 2026-11-25 终审 P0-1: 宿主可在启动期先 probe_vk_ready() 探测，把已就绪的
        # (adapter, device, info) 传进来复用 —— 探测与装配共用 _acquire_vk_device 唯一实现，
        # 不重复请求适配器/设备。None = 自己探测（旧调用面一字不变）。
        self._vk_ready = vk_ready
        # 延迟 init 失败时的宿主回调（可选）: 宿主据此给可见提示 + 改写配置。
        # 启动期探测已覆盖绝大多数「VK 不可用」；本钩子兜住 device/上下文/EditorApp
        # 装配期的残余失败，避免「失败无声」（Loom.exe 无控制台）。
        self._on_init_error = on_init_error
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
            # P6 顺序约束推荐侧：先建 wgpu device（本视口进程内随后没有任何
            # moderngl/GL 上下文创建，天然满足「先 wgpu 后 GL」）。
            # 唯一探测实现在模块级 _acquire_vk_device（启动期 probe_vk_ready 同一份）；
            # 宿主已探测过就把就绪三元组传进来复用，不再二次请求适配器/设备。
            import wgpu                     # TextureUsage（下面 configure 用）
            adapter, device, _dev_info = (self._vk_ready or (None, None, None))
            if device is None:
                adapter, device, _dev_info = _acquire_vk_device()
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
            from core.log import verbose
            verbose('[VkViewport] VkEditorApp 创建成功 (QRenderWidget bitmap 模式, '
                    'format=%s)' % fmt)
            print('[VkViewport] VK 编辑器就绪: device=%s | format=%s'
                  % (adapter.info.get('device', '?'), fmt))
        except Exception as _e:
            import traceback
            traceback.print_exc()
            self.init_error = repr(_e)
            # 2026-11-25 终审 P0-1: 装配失败必须**可见**（Loom.exe 无控制台时 traceback
            # 没人看得见）。宿主装了回调就交回宿主统一处理（弹窗 + 按裁决改写配置）。
            cb = self._on_init_error
            if callable(cb):
                try:
                    cb(self.init_error)
                except Exception as _cb_e:
                    print('[VkViewport] 宿主失败回调异常 (忽略): %r' % (_cb_e,))

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

    # key_pressed_array 由 _ViewportEventBridge 基类提供（B4 收口：本地再绑定拷贝删除）。


# 延迟导入说明：SimpleNamespace 供事件桥的 on_key_event 构造 KEYDOWN/KEYUP 事件
# （GLViewport 同款），放模块底部 import 保持顶部轻。
from types import SimpleNamespace  # noqa: E402
