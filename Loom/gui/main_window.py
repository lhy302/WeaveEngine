# -*- coding: utf-8 -*-
"""
ui/loom_gui.py — Loom 编辑器 PySide6 原生 Qt 视图 (IEditorView 实现)
================================================================================
2026-08-17: pygame(SDL) 窗口会进程级污染中文输入法(IME)候选框 —— tkinter 子窗口、
系统文件对话框全中招, 补丁无解 (见记忆 sdl-window-contaminates-ime). 编辑器定案 =
PySide6 原生 Qt 控件全重写: QOpenGLWidget 承载 moderngl 视口 + QTreeWidget /
QLineEdit / QDoubleSpinBox 等原生面板. QLineEdit 中文输入法原生可用, 修复核心.

架构 (控制器命令层/GL 渲染管线复用, 只换窗口+事件+面板):
  GLEngine (engine.py, 嵌入式 ctx 模式)  <- 渲染/场景/物理/脚本 零改动
  EditorApp (editor.py)                  <- 命令/撤销/选择/gizmo 零改动
  LoomGUI (本文件)                <- 原生面板 + 事件映射 + 渲染驱动
  GLViewport (本文件)                    <- QOpenGLWidget 承载 moderngl

启动: py -3.13 Loom.py --ui qt [--open 场景.json]
2026-08-28: 更名回 LoomGUI —— 本文件即 Loom 编辑器核心 GUI (旧 pygame 即时
模式视图 ui/LoomGUI.py 已删除, 功能 1:1 对照历史)。

实现约定:
  - 全部写操作走 EditorApp 命令 (B7-56/B7-56-2 后面板写操作再经 _invoke_cmd
    翻译成 EAI 命令, 视图不直接改模型状态、不自己压撤销栈).
  - 检查器数值行: valueChanged 实时应用 (EAI 命令, 会话批合一步撤销),
    editingFinished 收口会话批 (对齐 pygame drag_float 的
    右键键入-Enter提交-压栈 语义).
  - 鼠标/键盘事件 -> 引擎状态字段 (mouse_pos/buttons/pressed/released/
    mouse_wheel/_mods/key_state/mouse_rel), _update_camera/render 逻辑复用.
  - 视口叠加 (网格/选中框/gizmo/光源相机图标/播放期游戏 HUD) 在 draw() 里用
    engine 的 draw_lines/draw_screen_rect 绘制 (与旧版GUI 相同的绘制路径).
"""

import os
import sys
import time
import json
import math
import subprocess
from types import SimpleNamespace

import numpy as np
import moderngl

import pygame   # 仅取 K_* / KMOD_* 常量 (import 不初始化 SDL, 无 IME 污染)

import agent_commands   # EAI 命令层 (纯标准库, 无 Qt 依赖): 命令表 + 共用写入helper

_WINMM_PERIOD_SET = False
def _init_winmm_timer():
    global _WINMM_PERIOD_SET
    if not _WINMM_PERIOD_SET and sys.platform == 'win32':
        try:
            import ctypes
            ctypes.windll.winmm.timeBeginPeriod(1)
            _WINMM_PERIOD_SET = True
        except Exception:
            pass
_init_winmm_timer()

from PySide6.QtCore import Qt, QTimer, QByteArray, QMimeData, QEvent
from PySide6.QtGui import (
    QAction, QActionGroup, QColor, QBrush, QPainter, QCursor, QGuiApplication,
    QSurfaceFormat, QImage, QPixmap,
    QOpenGLContext, QOffscreenSurface,
)
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QFormLayout,
    QSplitter, QLabel, QLineEdit, QDoubleSpinBox, QSpinBox, QComboBox, QCheckBox,
    QPushButton, QToolBar, QScrollArea, QTreeWidget, QTreeWidgetItem,
    QListWidget, QListWidgetItem, QMenu, QDialog, QDialogButtonBox,
    QInputDialog, QMessageBox, QAbstractItemView, QToolButton, QFrame,
    QSizePolicy, QSlider, QDockWidget, QPlainTextEdit,
)
from PySide6.QtOpenGLWidgets import QOpenGLWidget

# 2026-11-09 批次 A0（人类裁决 D1=B）：GL 地板 3.3 -> 4.3 core。
# 版本门与报错文案的唯一实现在 loom_gl_version（GLFW/Qt 两条路径共用）。
from render.gl.version import (GL_MIN_MAJOR, GL_MIN_MINOR, GLVersionError,
                             require_gl_version)

# B4 收口（2026-11-21）：Qt 事件翻译常量（_QT_TO_PG/_qt_mods/_qt_button/
# _qt_buttons/_MIME_ASSET）随事件桥收敛到 editor/viewport/event_bridge.py
# （GL/Remote/VK 三端共用唯一实现）；本模块 re-import 保留旧命名空间
# （ui/loom_gui 门面经 sys.modules 别名指向本模块，lg._QT_TO_PG 等旧读法不变）。
from editor.viewport.event_bridge import (  # noqa: F401
    _QT_TO_PG, _qt_mods, _qt_button, _qt_buttons, _MIME_ASSET,
)

# B4 按类拆出（逐行未动，只搬家）：GLViewport -> gui/gl_viewport.py、
# RemoteViewport -> gui/remote_viewport.py、AssetListWidget/DraggableSpin/
# DragBlock -> gui/widgets/。
from gui.gl_viewport import GLViewport, _show_gl_floor_error        # noqa: F401
from gui.remote_viewport import RemoteViewport                      # noqa: F401
from gui.widgets import AssetListWidget, DraggableSpin, DragBlock   # noqa: F401
from gui.panels.toolbar_mixin import ToolbarMixin   # Q-B7-38-1 第 8 批（纯搬迁，按面板域拆 mixin）
from gui.panels.actions_mixin import ActionsMixin   # Q-B7-38-1 第 8 批（纯搬迁，按面板域拆 mixin）
from gui.panels.cmd_bridge_mixin import CmdBridgeMixin   # Q-B7-38-1 第 8 批（纯搬迁，按面板域拆 mixin）

_MSG_COLORS = {'ok': '#222222', 'err': '#c00000', 'dim': '#666666'}


# namedtuple 向量单轴写入: 实现在 agent_commands.vec_set (命令层专用 helper;
# 2026-08-22 的坑记录在那里: Point3D 是 namedtuple, setattr 无效 / 整体重建
# 会三轴同改). Q-B7-56-1 裁定① (2026-11-22): GUI 检查器数值行不再直调本函数,
# 统一翻译成 set_transform/light_set/camera_set 命令 (见 _cmd_vec_set).


# =====================================================================
# LoomGUI — 主窗口 + 全部原生面板 (IEditorView 实现)
# =====================================================================
class LoomGUI(CmdBridgeMixin,
              ActionsMixin,
              ToolbarMixin,
              QMainWindow):
    # S4（Q-B7-47-1 阶段 4）: backend='vulkan' 时视口用 VkViewport（backend 为 vulkan
    # 即走 —— 来源可为配置文件 render_api，也可为显式 --backend；Q-B7-60-1 后配置同样
    # 驱动，且缺省配置就是 vulkan。缺省 'gl' = 原路径一行不差）。
    def __init__(self, scene_path=None, width=1280, height=800, backend='gl',
                 explicit=False):
        super().__init__()
        self.editor = None
        # 2026-11-25 终审 P0-1（人类 2026-11-24 指令）: 本次 backend 是否来自**显式**
        # --backend（argv 里给了值）。显式失败不改写用户配置（Q6 先例），但仍回退 GL +
        # 可见提示；配置/默认来的 vulkan 失败则自动把配置改写成 opengl。
        self._backend_explicit = bool(explicit)
        # 本次启动 VK 装配失败的回退记录（dict | None）—— 可见提示与门都读它
        self._vk_fallback = None
        self._scene_path = scene_path
        self._init_w, self._init_h = width, height
        self.setWindowTitle("Loom — 编辑器 (Qt)")
        # 2026-10-20 白屏修复 P0-1：窗口尺寸钳制到屏幕可用区域。
        # 之前固定 resize(width+500, height+60) = 1780×860，在 1536×864 屏上超宽；
        # 加 DPI 缩放后原生 surface 与 FBO 尺寸脱节，导致整个客户区白屏
        # （win.grab() 正常但屏幕白 —— Qt native present 失败）。
        # 修复：取屏幕 availableGeometry，宽高取 min(请求值, available-80)，
        # 位置居中，避免超屏。
        try:
            screen = QGuiApplication.primaryScreen()
            if screen is not None:
                avail = screen.availableGeometry()
                req_w = width + 500
                req_h = height + 60
                clamp_w = min(req_w, max(800, avail.width() - 80))
                clamp_h = min(req_h, max(600, avail.height() - 80))
                self.resize(clamp_w, clamp_h)
                cx = avail.x() + (avail.width() - clamp_w) // 2
                cy = avail.y() + (avail.height() - clamp_h) // 2
                self.move(cx, cy)
            else:
                self.resize(width + 500, height + 60)
        except Exception:
            self.resize(width + 500, height + 60)

        # 2026-10-20 白屏修复 P1：远程/虚拟显示下 QOpenGLWidget native present
        # 可能失败（客户区白屏但 win.grab() 正常）。--remote-mode 或
        # LOOM_REMOTE_MODE=1 时改用离屏 GL + QImage readback，绕过 native present。
        _remote = ('--remote-mode' in sys.argv
                   or os.environ.get('LOOM_REMOTE_MODE') == '1')
        if _remote:
            print('[Qt] 远程/虚拟显示模式启用（离屏 GL readback）')
            self.viewport = RemoteViewport(self, scene_path, width, height)
        elif backend == 'vulkan':
            # S4（Q-B7-47-1 阶段 4）: backend 为 vulkan（来源可为配置 render_api 或显式
            # --backend）的编辑器走 VK 视口（QRenderWidget bitmap present；GL 路径分支
            # 原样保留，缺省零变化）。
            #
            # 2026-11-25 终审 P0-1（人类 2026-11-24 指令「加编辑器启动时 VK 失败 → 自动
            # 改写配置为 opengl + 提示」）: 先**探测** VK 可装配性，探测失败就不建
            # VkViewport，直接建 GLViewport 并在 _build_central 之前完成（本次启动编辑器
            # 可用）。为什么不是「建了 VkViewport 再销毁重建」见 vk_viewport.probe_vk_ready
            # 的 docstring（VkViewport 的 wgpu 装配是延迟的，构造后 init_error 恒为 None）。
            from editor.viewport import vk_viewport as _vk_vp
            _vk_ok, _vk_reason, _vk_ready = _vk_vp.probe_vk_ready()
            if _vk_ok:
                self.viewport = _vk_vp.VkViewport(
                    self, scene_path, width, height, vk_ready=_vk_ready,
                    on_init_error=self._on_vk_late_init_error)
            else:
                # 本次回退 GL（启动期一次性选择，不是运行期热切换 —— 与裁决①不冲突）
                self.viewport = GLViewport(self, scene_path, width, height)
                self._vk_fallback = self._handle_vk_init_failure(
                    _vk_reason, adapter_info=(_vk_ready or (None, None, {}))[2],
                    can_swap=True)
        else:
            self.viewport = GLViewport(self, scene_path, width, height)

        # 2026-11-07 EAI 可视化 (B/E): Agent 逐条执行 -> 状态栏进度/红点/步进.
        # 这些属性必须在 _build_toolbar/_build_statusbar 之前就位: 构建期若
        # 有钩子被提前调用也能安全读到默认值.
        self._agent_service = None
        self._agent_status_active = False   # 状态栏当前被 AI 进度占用
        self._agent_busy_active = False     # Agent 正在执行 (红点)
        self._agent_idle_token = 0          # 1.5s 空闲恢复的重入令牌
        # 2026-11-08 批4 (裁决 D10): Agent 批次租约可视化
        self._agent_batch_active = False    # 批次进行中 (状态栏已被占用)
        self._agent_batch_remaining = None  # 剩余秒数 (None = 无批次)
        # 2026-11-08 批4 (U-02): 窗口销毁后的静默/单次告警状态
        self._agent_gui_dead = False        # True = 底层 QWidget 已失效
        self._agent_gui_warned = False      # 已告警一次 (之后静默)

        self._build_toolbar()
        self._build_central()          # 层级/资源 | 视口 | 检查器
        self._build_statusbar()
        self._build_console()          # 底部命令行坞 (EAI 命令表, 默认隐藏)
        # 2026-10-18 阶段5: 底部 UI 树 dock（CanvasUI 可视化编辑器）
        self._ui_selected_name = None      # 当前选中的 UI 元素名
        self._ui_selected_canvas = None    # 所在 Canvas 序号
        self._build_ui_tree_dock()

        # 渲染驱动 (帧率档位由 设置.json 的 fps_limit 决定, 见 _apply_fps_limit)
        # + 面板轮询刷新 (300ms).
        # 2026-08-19 帧率修复背景: ①16ms 定时器锁死 ~62FPS -> 按档位 + PreciseTimer;
        # ②Qt 默认 vsync (swapInterval=1) 锁显示器刷新率 -> run_loom_gui 里
        # fmt.setSwapInterval(0) 关闭 (对齐 pygame 无 vsync).
        self._render_timer = QTimer(self)
        self._render_timer.timeout.connect(self._on_tick)
        self._render_timer.setTimerType(Qt.TimerType.PreciseTimer)
        self._apply_fps_limit()
        self._refresh_timer = QTimer(self)
        self._refresh_timer.timeout.connect(self._refresh_all)
        self._refresh_timer.start(300)

        # 检查器重建缓存: 选中目标变化才重建; _building 防信号回环
        self._insp_key = None
        self._building = False
        self._spins = {}               # key -> QDoubleSpinBox (值同步用)
        self._spin_meta = {}           # key -> (apply,label,lo,hi,step,sb,edit) 拖拽块元数据
        self._res_selected = None      # (type, key) 当前选中资产
        self._hier_down = None         # 层级拖拽解析: (按下pos, item数据)
        self._hier_pressed = False
        self._hier_last_digest = None  # 层级树内容摘要缓存
        self._res_last_digest = None   # 资源列表内容摘要缓存
        self._insp_last_digest = None  # 检查器组件状态摘要缓存
        # 窗口级键盘 (对齐 pygame): 焦点不在文本/列表控件时, 按键转发给视口
        # (否则焦点在工具栏/空白处时 WASD 相机移动无反应)
        QApplication.instance().installEventFilter(self)
        # 焦点变化 -> 底部数值拖拽块显隐 (2026-08-22): 聚焦数值行显示,
        # 焦点离开检查器数值控件隐藏 (拖拽进行中不隐藏)
        QApplication.instance().focusChanged.connect(self._on_app_focus_changed)

    # ---------------- 渲染后端装配失败（P0-1，人类 2026-11-24 指令） ----------------
    def _on_vk_late_init_error(self, reason):
        """VkViewport **延迟**装配失败的回调（启动期探测过了，真正装配仍失败）。

        装配失败发生在事件循环启动后（QTimer.singleShot(0, _init_deferred)），此时
        _build_central 已把视口装进布局 —— 不在这里销毁重建（Qt 风险高，见
        editor/viewport/vk_viewport.probe_vk_ready 的 docstring），只做可见失败 +
        按裁决改写配置；设置面板已无条件可达（P0-1 另一半），用户可据此改后端并重启。
        """
        if self._vk_fallback is None:
            self._vk_fallback = self._handle_vk_init_failure(reason, can_swap=False)

    def _handle_vk_init_failure(self, reason, adapter_info=None, can_swap=False):
        """VK 装配失败的**唯一出口**（人类 2026-11-24 指令 + Q1/Q6/Q7 裁决）。

        三件事，顺序固定:
          ① 按**唯一判据**（hostenv.editor_launch.should_rewrite_config_on_vk_failure）
             决定要不要把配置改写成 opengl；改写走**唯一写盘路径**
             （hostenv.editor_launch.write_render_api_choice —— 与设置面板同一条，
             不另起第三处写盘）；
          ② 发**可见提示**（hostenv.backend_guard.show_blocking_dialog —— 播放器 VK 失败
             用的同一份可见失败组件，规则 5.5；LOOM_NO_DIALOG=1 时只打印，与既有语义一致）；
          ③ 记录本次回退（can_swap=True: 视口已在调用点换成 GLViewport，本次可用；
             False: 视口装配失败，提示要求重启）。

        返回 dict（reason / rewritten / effective / explicit / requested_api / shown /
        can_swap / message / write_error），self._vk_fallback 与门都读它。
        """
        from hostenv.editor_launch import (should_rewrite_config_on_vk_failure,
                                           write_render_api_choice)
        explicit = bool(getattr(self, '_backend_explicit', False))
        api_req = None
        try:
            import run_player
            api_req = run_player.resolve_backend(None)
        except Exception as e:
            print('[VK] 读配置失败 (%r) —— 按「默认 vulkan」判断是否改写' % (e,))
        rewrite = should_rewrite_config_on_vk_failure(explicit, api_req)
        rewritten = False
        eff, werr = None, None
        if rewrite:
            try:
                res = write_render_api_choice('opengl')
                rewritten = bool(res.get('ok'))
                eff = res.get('effective')
                werr = res.get('error')
            except Exception as e:
                werr = repr(e)
        msg = self._vk_failure_message(reason, api_req, explicit, rewritten, werr,
                                       can_swap)
        print(msg)
        shown = False
        try:
            from hostenv.backend_guard import show_blocking_dialog
            shown = show_blocking_dialog('Vulkan 初始化失败', msg)
        except Exception as e:
            print('[VK] 弹窗失败 (%r) —— 仅打印原因' % (e,))
        if not shown:
            print('[VK] (未弹窗: 无 GUI 或 LOOM_NO_DIALOG=1 —— 原因见上面的 [VK] 行)')
        return {'reason': reason, 'rewritten': rewritten, 'effective': eff,
                'explicit': explicit, 'requested_api': api_req, 'shown': shown,
                'can_swap': can_swap, 'message': msg, 'write_error': werr}

    @staticmethod
    def _vk_failure_message(reason, api_req, explicit, rewritten, werr, can_swap):
        """VK 装配失败的可见提示文案 —— 必须同时说清三件事:
        ① VK 初始化失败原因摘要；② 配置有没有被改成 opengl；③ 本次怎么办。"""
        if can_swap:
            lines = ['[VK] Vulkan 初始化失败，本次启动已回退到 OpenGL（需要 4.3 core）视口，'
                     '编辑器可继续使用。']
        else:
            lines = ['[VK] Vulkan 初始化失败，视口装配未完成 —— 请按下面的提示处理后重启编辑器。']
        lines.append('[VK] 失败原因: %s' % (reason,))
        _req = str(api_req or '').strip().lower()
        if explicit:
            lines.append('[VK] 本次是显式 --backend vulkan：**未改写配置文件**（尊重显式选择）。'
                         '如需永久改用 OpenGL，请在设置面板把渲染后端改为 OpenGL。')
        elif _req == 'auto':
            lines.append('[VK] 本次配置是 auto（先试 Vulkan、失败回退 OpenGL）：'
                         '**未改写配置文件**（auto 本身没有偏好可持久化）。')
        elif rewritten:
            lines.append('[VK] 已把配置里的渲染后端改写为 opengl —— 下次启动直接走 OpenGL。')
        else:
            lines.append('[VK] 改写配置为 opengl **失败**%s —— 下次启动仍会先试 Vulkan，'
                         '可在设置面板里手动改成 OpenGL。'
                         % (('(%s)' % (werr,)) if werr else '',))
        if not can_swap:
            lines.append('[VK] 本次视口未能装配：请重启编辑器（或加 --backend opengl 启动）后继续。')
        lines.append('[VK] 提示: 升级显卡驱动（需要 Vulkan 1.1+）可恢复 Vulkan 后端。')
        return '\n'.join(lines)

    # ---------------- IEditorView 契约 ----------------
    def attach(self, controller):
        """EditorApp 构造时调用 (editor.py __init__ 里 view.attach(self))."""
        self.editor = controller
        if controller is not None:
            # 未保存询问框用 Qt 原生 (无 pygame 时 tkinter 风格不符)
            controller._confirm_callback = self._ask_save_dirty
            # Q3=A (2026-11-07, F8 配套): 删除"仍有子物体的父物体"前弹确认框,
            # 文案显示子物体数量 N —— 删父 = 连整棵子树删, 不可撤销前必须让人看到 N。
            # 原来 Qt 编辑器没注入这个钩子, editor.delete_object 里 getattr 拿到 None,
            # 于是 Qt 里删父物体静默连子树删 (无任何提示)。
            controller._confirm_delete_callback = self._ask_delete_confirm
            # Qt 模式下视口 = 整个 GLViewport, 相机交互天然在视口内
            controller._in_viewport = lambda pos: True

    def _inject_delete_confirm(self, editor):
        """把 Q3 删除确认钩子挂到 editor 上 (幂等)。

        注意顺序陷阱: editor.py __init__ 里 `view.attach(self)` 在第 140 行,
        而 `self._confirm_delete_callback = None` 在第 158 行 —— attach 期注入的
        钩子会被 __init__ 后面的 None 覆盖。所以真正生效的注入点在
        bind_editor() (__init__ 返回后宿主调用) 与删除入口 _cmd_del() 里。"""
        if editor is not None:
            editor._confirm_delete_callback = self._ask_delete_confirm

    def bind_editor(self, editor):
        """initializeGL 建好 EditorApp 后调用 (attach 已由 EditorApp 内部完成)."""
        self.attach(editor)
        # Q3=A (2026-11-07): __init__ 已把 attach 期注入的钩子清成 None,
        # 这里 (__init__ 返回后) 重新注入才真正生效。
        self._inject_delete_confirm(editor)
        self._refresh_all()

    def input_state(self):
        e = self.editor
        if e is None:
            return {'mouse_pos': (0, 0), 'buttons': (0, 0, 0), 'pressed': set(),
                    'released': set(), 'wheel': 0, 'click_captured': False,
                    'focus_id': None}
        return {'mouse_pos': e.mouse_pos, 'buttons': e.buttons,
                'pressed': e.pressed, 'released': e.released,
                'wheel': e.mouse_wheel, 'click_captured': False, 'focus_id': None}

    def handle_key_event(self, ev):
        """原生控件自己消费键盘 (QLineEdit 等), 视口键已由 GLViewport 直通 editor."""
        return False

    def key_pressed_array(self):
        """引擎 _key_pressed() 的宿主入口 (self.view 是 LoomGUI):
        转发到视口的按键快照 (WASD/方向键相机移动)."""
        return self.viewport.key_pressed_array()

    def reset_interaction(self):
        """播放切换/对话框返回: 清视口拖拽状态 + 强制刷新."""
        self._hier_down = None
        self._hier_pressed = False
        self.viewport._last_move = None
        self._refresh_all()

    def draw(self, ctl, delta_time):
        """每帧 GL 视口叠加: 网格/选中框/gizmo/光源相机图标/播放期游戏 HUD.
        (原生面板由 Qt 自己画, 不进这里.)"""
        if ctl.is_playing:
            # 播放期: 光源/相机图标仍画 (对齐旧版GUI). Canvas 游戏 UI **不在这里画** ——
            # S1 (Q-B7-48-1, 2026-11-19 同源裁决): 它由 FramePlan 的 screen_ui pass
            # (include_ui) 绘制, 与播放器同一条路径; 本方法只画编辑器叠加层,
            # 且在 plan 之后 (叠加层在最上)。旧自画 (2026-10-18 注) 已删。
            self._draw_light_icons(ctl)
            self._draw_camera_icons(ctl)
            return
        # Q-B7-53-1（2026-11-22 真窗口取证）：网格由谁画由**后端能力**决定 ——
        # EngineCore.grid_in_scene_pass（公共语义，默认 False）由各后端显式覆写：
        #   GL = True  -> 帧执行器在最后一个 3D pass 之后画进当前场景目标
        #                 （深度附件 = 刚写完的场景深度，见 render/gl/render.py::
        #                 _draw_grid_in_scene）-> 这里不再重复画；
        #   VK = False -> 仍走下面的叠加层调用点（其深度视图 = 主 pass 深度视图）。
        # 两端都显式有值，不是「属性不存在 = False」的隐式分支；getattr 仅用于
        # 无头桩/测试替身（它们不必声明该属性）。
        if (getattr(ctl, 'show_grid', True)
                and not getattr(ctl, 'grid_in_scene_pass', False)):
            out = ctl.grid_geometry()
            if out is not None:
                verts, cols = out
                # 叠加层状态走 overlay_scope 钩子（与 gizmo/选中框同一条同源路径）。
                # Q-B7-53-1（2026-11-22 真窗口取证，更正 2026-08-18 的旧说法）：
                # 「依赖 _clear_main_fbo 每帧清深度到 far、物体深度更近时遮挡网格」
                # 只在不走后处理链时才成立 —— 后处理开启（默认）时主 pass 的深度写在
                # color.hdr 上，屏幕 FBO 的深度从没被写过，GL 网格深度测试恒失败（0 像素，
                # 见 render/gl/render.py::_draw_grid_in_scene 的真因说明）。所以 GL 侧网格
                # 已改到场景 pass 内绘制（grid_in_scene_pass=True -> 本分支只在 VK 生效）；
                # VK 的深度附件 = 主 pass 深度视图，本调用点的 depth_test/blend 语义正确。
                with ctl.overlay_scope(framebuffer=ctl._screen_fb(),
                                       enable=('depth_test', 'blend')):
                    ctl.draw_lines(verts, cols)
        ctl._draw_selection_box()
        self._draw_gizmo(ctl)
        self._draw_light_icons(ctl)
        self._draw_camera_icons(ctl)

    # ---------------- 视口叠加 (与旧版GUI 同路径: draw_lines/draw_screen_rect) ----------------
    def _draw_gizmo(self, ctl):
        from engine import LightState, CameraState   # 仅判类型用 (函数内 import 防环)
        t = ctl._gizmo_target()
        if t is None or (not isinstance(t, (LightState, CameraState))
                         and not t.visible):
            return
        o = ctl._target_world_pos(ctl, t)
        lines, cols = [], []
        if ctl.gizmo_mode == 'translate':
            L = ctl._GIZMO_LEN
            for axis in ('X', 'Y', 'Z'):
                ax = ctl._GIZMO_AXES[axis]
                col = (1.0, 1.0, 1.0) if axis == ctl.gizmo_axis else ctl._GIZMO_COLORS[axis]
                lines += [(o[0], o[1], o[2]),
                          (o[0] + L * ax[0], o[1] + L * ax[1], o[2] + L * ax[2])]
                cols += [col, col]
                # 轴端小方块帽 (屏幕投影)
                cap = ctl.project_world((o[0] + L * ax[0], o[1] + L * ax[1],
                                         o[2] + L * ax[2]))
                if cap is None:
                    continue              # 轴端在相机背后: 不画帽 (背面镜像, 2026-08-21)
                ex, ey = cap
                s = 8
                ctl.draw_screen_rect((ex - s / 2, ey - s / 2, s, s),
                                     tuple(int(c * 255) for c in ctl._GIZMO_COLORS[axis]))
        else:
            R = ctl._GIZMO_RAD
            for axis in ('X', 'Y', 'Z'):
                u, v = ctl._gizmo_basis(axis)
                pts = ctl._gizmo_circle_points(o, R, u, v)
                col = (1.0, 1.0, 1.0) if axis == ctl.gizmo_axis else ctl._GIZMO_COLORS[axis]
                for i in range(ctl._GIZMO_SEGS):
                    lines.append(pts[i])
                    lines.append(pts[(i + 1) % ctl._GIZMO_SEGS])
                    cols += [col, col]
            rot_center = ctl.project_world(o)
            if rot_center is not None:
                cx, cy = rot_center
                ctl.draw_screen_rect((cx - 3, cy - 3, 6, 6), (255, 255, 255))
        if lines:
            # 2026-08-22 A11 修复: gizmo 必须恒可见 (选中框同款逻辑) —— 主 pass
            # 渲染后 GL 残留 DEPTH_TEST=on, 裸调 draw_lines 的棒/圆环线会被身前
            # 物体遮挡 (用户实测"拉条被物体挡住无法拖动"); scope enable_only=0
            # 关全部深度测试. enable_only 破坏 GL_LINE_WIDTH 由 draw_lines 内部
            # 每帧重设 2.0 抵消 (2026-08-18 修复), 选中框已同款实践证明有效.
            with ctl.overlay_scope(framebuffer=ctl._screen_fb(), enable_only=0):
                ctl.draw_lines(lines, cols)

    def _icon_size(self, ctl, p):
        return max(6.0, min(14.0, ctl.camera_distance * 0.35))

    def _direction_cone(self, ax, ay, az, dx, dy, dz, L, col):
        """顶端指向圆锥 (线框): 尖端 (ax,ay,az) 朝向 (dx,dy,dz), 基圆在线后端.
        2026-08-22 从旧版GUI移植 (Qt 版此前为"简化直线", 用户报缺失)."""
        cone_len, cone_r = 0.25 * L, 0.18 * L
        ref = (0, 1, 0) if abs(dy) < 0.9 else (1, 0, 0)
        ux, uy, uz = (dy * ref[2] - dz * ref[1],
                      dz * ref[0] - dx * ref[2],
                      dx * ref[1] - dy * ref[0])
        nl = math.sqrt(ux * ux + uy * uy + uz * uz) or 1.0
        ux, uy, uz = ux / nl, uy / nl, uz / nl
        vx, vy, vz = (uy * dz - uz * dy, uz * dx - ux * dz, ux * dy - uy * dx)
        bx, by, bz = ax - dx * cone_len, ay - dy * cone_len, az - dz * cone_len
        verts, cols2 = [], []
        nseg = 12
        for i in range(nseg):
            t0 = 2 * math.pi * i / nseg
            t1 = 2 * math.pi * (i + 1) / nseg
            c0, s0, c1, s1 = math.cos(t0), math.sin(t0), math.cos(t1), math.sin(t1)
            p0 = (bx + (ux * c0 + vx * s0) * cone_r,
                  by + (uy * c0 + vy * s0) * cone_r,
                  bz + (uz * c0 + vz * s0) * cone_r)
            p1 = (bx + (ux * c1 + vx * s1) * cone_r,
                  by + (uy * c1 + vy * s1) * cone_r,
                  bz + (uz * c1 + vz * s1) * cone_r)
            verts.append((ax, ay, az)); verts.append(p0)
            verts.append(p0); verts.append(p1)
            cols2.extend([col, col, col, col])
        return verts, cols2

    def _draw_light_icons(self, ctl):
        sel = ctl._selected_light()
        for light in ctl.lights:
            p = (light.position.x, light.position.y, light.position.z)
            scr = ctl.project_world(p)
            if scr is None:
                continue                  # 光源在相机背后: 图标/朝向线不画 (2026-08-21)
            sx, sy = scr
            s = self._icon_size(ctl, p)
            col = (230, 200, 90) if light.kind == 'directional' else (240, 150, 70)
            if light is sel:
                ctl.draw_screen_rect((sx - s / 2 - 2, sy - s / 2 - 2, s + 4, s + 4),
                                     (255, 255, 255))
            ctl.draw_screen_rect((sx - s / 2, sy - s / 2, s, s), col)
            if light is sel and light.kind == 'directional':
                self._draw_directional_dir(ctl, light, p)

    def _draw_directional_dir(self, ctl, light, p):
        """选中方向光: 朝向线 + 指向圆锥 + roll 倾斜箭头 + 光束截面 (mode=beam).
        2026-08-22 对齐旧版GUI (原"简化版"缺锥体/roll 箭头/矩形截面, 用户报缺失)."""
        D = (light.direction.x, light.direction.y, light.direction.z)
        ln = math.sqrt(D[0] * D[0] + D[1] * D[1] + D[2] * D[2])
        if ln < 1e-6:
            return
        u = (D[0] / ln, D[1] / ln, D[2] / ln)
        L = 2.2
        col = (0.9, 0.78, 0.35)
        lines = [(p[0], p[1], p[2]),
                 (p[0] + u[0] * L, p[1] + u[1] * L, p[2] + u[2] * L)]
        cols = [col, col]
        # 指向圆锥 (线框, 尖端在光束末端)
        ex, ey, ez = p[0] + u[0] * L, p[1] + u[1] * L, p[2] + u[2] * L
        cone_v, cone_c = self._direction_cone(ex, ey, ez, u[0], u[1], u[2], L, col)
        lines += cone_v
        cols += cone_c
        # roll 倾斜方向箭头 (M30/M41 同款): 朝向线中点 1/4 大小黄色箭头 -> up_vector
        try:
            up = light.up_vector()
            mL = L * 0.25
            mx, my, mz = (p[0] + u[0] * (L / 2),
                          p[1] + u[1] * (L / 2), p[2] + u[2] * (L / 2))
            tx, ty, tz = mx + up.x * mL, my + up.y * mL, mz + up.z * mL
            lines.append((mx, my, mz)); lines.append((tx, ty, tz))
            cols.append((0.95, 0.75, 0.25)); cols.append((0.95, 0.75, 0.25))
            cone2_v, cone2_c = self._direction_cone(tx, ty, tz, up.x, up.y, up.z,
                                                    mL, (0.95, 0.75, 0.25))
            lines += cone2_v
            cols += cone2_c
        except Exception:
            pass
        if getattr(light, 'mode', 'full') == 'beam':
            # 光束截面: 垂直于方向的圆环 (shape=circle) 或矩形 (shape=rect)
            R = getattr(light, 'size', 5.0)
            o = (p[0] + u[0] * L, p[1] + u[1] * L, p[2] + u[2] * L)
            # 截面基 = 光源 up_vector (含方位/俯仰/roll 全部倾斜, 引擎保证恒
            # ⊥ 方向线) + cross(up, direction): 法线严格=光方向, 倾斜随 roll
            # —— 2026-08-22 用户实测原"世界轴参考"只在一个轴面上近似同步且
            # 未应用倾斜, 对齐旧版GUI._draw_beam_cross_section 正确算法
            up = light.up_vector()
            vx = (up.x, up.y, up.z)
            vy = (up.y * u[2] - up.z * u[1], up.z * u[0] - up.x * u[2],
                  up.x * u[1] - up.y * u[0])
            if getattr(light, 'shape', 'circle') == 'circle':
                for i in range(36):
                    a = i / 36 * math.tau
                    b = (i + 1) / 36 * math.tau
                    lines.append((o[0] + R * (math.cos(a) * vx[0] + math.sin(a) * vy[0]),
                                  o[1] + R * (math.cos(a) * vx[1] + math.sin(a) * vy[1]),
                                  o[2] + R * (math.cos(a) * vx[2] + math.sin(a) * vy[2])))
                    lines.append((o[0] + R * (math.cos(b) * vx[0] + math.sin(b) * vy[0]),
                                  o[1] + R * (math.cos(b) * vx[1] + math.sin(b) * vy[1]),
                                  o[2] + R * (math.cos(b) * vx[2] + math.sin(b) * vy[2])))
                    cols += [col, col]
            else:
                corners = [(o[0] + (vx[0] * a + vy[0] * b) * R,
                            o[1] + (vx[1] * a + vy[1] * b) * R,
                            o[2] + (vx[2] * a + vy[2] * b) * R)
                           for a in (-1, 1) for b in (-1, 1)]
                for a, b in ((0, 1), (1, 3), (3, 2), (2, 0)):
                    lines.append(corners[a]); lines.append(corners[b])
                    cols += [col, col]
        # 2026-08-22: 光源指示线/锥/截面恒可见 (同 gizmo A11 修复)
        with ctl.overlay_scope(framebuffer=ctl._screen_fb(), enable_only=0):
            ctl.draw_lines(lines, cols)

    def _draw_camera_icons(self, ctl):
        sel = ctl._selected_camera()
        for cam in ctl.cameras:
            p = (cam.position.x, cam.position.y, cam.position.z)
            scr = ctl.project_world(p)
            if scr is None:
                continue                  # 摄像机在相机背后: 图标不画 (2026-08-21)
            sx, sy = scr
            s = self._icon_size(ctl, p)
            if cam is sel:
                ctl.draw_screen_rect((sx - s / 2 - 2, sy - s / 2 - 2, s + 4, s + 4),
                                     (255, 255, 255))
            ctl.draw_screen_rect((sx - s / 2, sy - s / 2, s, s), (140, 191, 242))
            if cam is sel:
                # 朝向线 + 指向圆锥 + roll 倾斜箭头 (M41, 2026-08-22 对齐旧版GUI)
                yaw, pitch = cam.yaw, cam.pitch
                dx = math.sin(yaw) * math.cos(pitch)
                dy = math.sin(pitch)
                dz = math.cos(yaw) * math.cos(pitch)
                L = 1.2
                lines = [p, (p[0] + dx * L, p[1] + dy * L, p[2] + dz * L)]
                cols = [(0.55, 0.75, 0.95), (0.55, 0.75, 0.95)]
                ex, ey, ez = p[0] + dx * L, p[1] + dy * L, p[2] + dz * L
                cone_v, cone_c = self._direction_cone(ex, ey, ez, dx, dy, dz, L,
                                                      (0.55, 0.75, 0.95))
                lines += cone_v
                cols += cone_c
                # roll 方向标识 (世界基 ey = roll 上): 中线 1/4 黄色箭头 -> up
                try:
                    _exw, _eyw, _ezw = ctl.camera_world_basis(cam)
                    up = (_eyw[0], _eyw[1], _eyw[2])
                    mL = L * 0.25
                    mx, my, mz = p[0] + dx * (L / 2), p[1] + dy * (L / 2), p[2] + dz * (L / 2)
                    tx, ty, tz = mx + up[0] * mL, my + up[1] * mL, mz + up[2] * mL
                    lines.append((mx, my, mz)); lines.append((tx, ty, tz))
                    cols.append((0.95, 0.75, 0.25)); cols.append((0.95, 0.75, 0.25))
                    cone2_v, cone2_c = self._direction_cone(tx, ty, tz, up[0], up[1],
                                                            up[2], mL, (0.95, 0.75, 0.25))
                    lines += cone2_v
                    cols += cone2_c
                except Exception:
                    pass
                # 2026-08-22: 相机朝向线/锥/roll 箭头恒可见 (同 gizmo A11 修复)
                with ctl.overlay_scope(framebuffer=ctl._screen_fb(), enable_only=0):
                    ctl.draw_lines(lines, cols)

    # ---------------- FPS 缓冲: 空窗预画 ----------------
    def _preframe_in_gap(self, now, tgt):
        """FPS 缓冲实验 (2026-09-06): _on_tick 等待空窗内预画下一渲染帧.
        预画 = 离屏 FBO 上完整走 e.render (逻辑推进跳过 — advance 已在上帧
        消费/标记, _advanced_this_frame 语义保证本画不推进时钟).
        ★预画用的输入 = 当前相机/场景态 (与节拍点画的一致 — 相机输入在
        _on_tick 后段才采集, 本空窗还没动). 预画失败 = 作废, 节拍点正常画."""
        e = self.editor
        rb = getattr(e, '_render_buf', None) if e is not None else None
        if rb is None or not rb.enabled:
            return
        # 仅播放态预画 (编辑态相机/物体每帧可能变, 预画一帧延迟显眼且无收益)
        if not getattr(e, 'is_playing', False) or \
                getattr(e, '_logic_paused', False):
            return
        # 2026-09-06 用户实测: 关 FPS 缓冲仍频闪 → 预画路径非频闪根源
        # (本路径保留; widget FBO 稳定缓存 _widget_fb + 预画后显式绑回
        # 已消除其 FBO 绑定残留风险)。
        if not rb.should_preframe(now, tgt):
            return
        gap = tgt - time.perf_counter()
        # 预画预算: 空窗的 70% (留 30% 给 GL 提交/swap/系统余量), 再留 1ms 底线
        if gap < 0.004:
            rb.rejected += 1
            return
        try:
            if rb.begin(e.ctx, e.width, e.height):
                e._preframing = True    # 预画帧: 内部跳过 TPS 预取/FPS 计数
                try:
                    e.render(0.0)       # 离屏画 (render 内部不改 _tick 状态)
                finally:
                    e._preframing = False
                rb.commit()
                # 恢复 widget FBO 绑定 (防御: 预画把 GL 绑定留在离屏 FBO,
                # 下一拍 paintGL 的 clear/detect 若在残留绑定下执行 = 黑屏一拍)
                wf = getattr(self, '_widget_fb', None)
                if wf is not None:
                    wf.use()
        except Exception:
            rb.abort()
            wf = getattr(self, '_widget_fb', None)
            if wf is not None:
                wf.use()

    # ---------------- 主渲染循环 ----------------
    def _on_tick(self):
        e = self.editor
        if e is None:
            return
        # ★M3: 主线程非 paintGL 段归因 (mt_qt_tick) —— 量化 tick 处理开销
        _t_tick = e._prof_t0() if hasattr(e, '_prof_t0') else 0.0
        # 限帧器校准 (方案一 2026-09-05): 档位模式帧首对齐固定节拍网格
        # (wait_until 混合等待: sleep 大段+忙等收尾, 消 QTimer 到达抖动);
        # 无上限档不做 pacing (kivy maxfps=0 同款: 无目标周期, 忙等纯烧 CPU
        # — 无上限的抖动源=逻辑帧落点双峰, 由帧长观测量化+外推缓解).
        tp = getattr(self, '_tick_period', None)
        if tp is not None:
            now = time.perf_counter()
            tgt = getattr(self, '_tick_target', None)
            if tgt is None:
                self._tick_target = now + tp     # 首帧: 建网格锚点
            else:
                if now < tgt - 0.002:            # 提前 >2ms → 混合等待
                    # FPS 缓冲 (2026-09-06 实验): 等待空窗内预画下一渲染帧
                    # (离屏 FBO 完整走 render 管线, 逻辑推进跳过). 成功 commit
                    # 后剩余等待照常; 失败/放弃 → 正常等待, 节拍点正常画.
                    self._preframe_in_gap(now, tgt)
                    self._wait_until(tgt)
                now2 = time.perf_counter()
                self._tick_target = tgt + tp     # 固定网格推进
                if self._tick_target < now2:     # 落后 (帧超预算) → 重锚不追
                    self._tick_target = now2 + tp
        # 2026-11-07 P1-5: pressed/released 绝不能在这里清 —— 它们是 Qt 事件
        # 回调 (mousePressEvent/mouseReleaseEvent) 攒下的"本帧新按下/松开",
        # 真正的消费者是 _update_camera() 开头的 editor._dispatch_ui_mouse()
        # (UI 树分发) 与相机输入。原来在 _update_camera 之前清空, UI 树每帧
        # 收到空的 pressed/released -> Qt 编辑器里 HUD 按钮/滑条/输入框全部
        # 点不动 (pygame 主线自己轮询鼠标, 不受影响, 所以只有 Qt 版本坏)。
        # 清空动作移到 _update_camera() 之后 (UI + 相机都消费完)。
        # 注意: mouse_wheel 不能在开头清零 —— wheelEvent (事件驱动) 设置的值
        # 会被 _update_camera 读取做相机缩放, 先清零会让滚轮永远失效
        # (2026-08-19 修复). 清零移到 _update_camera 之后 (读取后清零).
        # 每帧同步真实鼠标位置 (对齐 pygame 版每帧轮询 get_pos): 鼠标无 move 事件时
        # mouse_pos 停留旧值, 右键按下瞬间 dx 巨大 -> 视角跳变 (2026-08-18 修复).
        # 只在鼠标位于视口内时更新 (事件只在窗口内的约定不变).
        gpos = QCursor.pos()   # 全局鼠标位置 (静态方法, 无窗口句柄依赖)
        lpos = self.viewport.mapFromGlobal(gpos)
        if self.viewport.rect().contains(lpos):
            dpr = self.viewport.devicePixelRatioF()
            e.mouse_pos = (int(lpos.x() * dpr), int(lpos.y() * dpr))
        e._update_camera()
        e.mouse_wheel = 0   # 读取后清零 (滚轮缩放 2026-08-19)
        # 2026-11-07 P1-5: UI 分发与相机都已消费本帧输入, 现在才清 pressed/
        # released (原位置在 _update_camera 之前, 见上方注释)。
        e.pressed.clear()
        e.released.clear()
        self.viewport.update()
        if _t_tick:
            e._prof_add('mt_qt_tick', _t_tick)

    # ---------------- 构建: 工具栏 ----------------

    # ---------------- UI 树 dock (2026-10-18 阶段5) ----------------
    def _build_ui_tree_dock(self):
        """底部 UI 树 dock（与命令行坞并列，默认显示）.
        2026-10-19 修复: 坞被用户点 X 关闭时同步状态栏按钮态,
        避免按钮"显示已打开"但坞已关。"""
        from ui import qt_uitree
        self.uitree = qt_uitree.UITreeDock(self)
        self.addDockWidget(Qt.DockWidgetArea.BottomDockWidgetArea, self.uitree)
        # 与 console 并排（tabify 或 split），保持两个都在底部
        try:
            self.tabifyDockWidget(self.console, self.uitree)
        except Exception:
            pass
        self.uitree.show()
        # 2026-10-19: 坞可见性 -> 按钮状态同步（对齐 console 同款）
        self.uitree.visibilityChanged.connect(
            lambda vis: self._btn_uitree.setChecked(bool(vis)))

    def _cmd_uitree(self, checked=None):
        """2026-10-19: [UI树] 按钮 / F11: 开关 UI 树坞."""
        show = not self.uitree.isVisible() if checked is None else bool(checked)
        self.uitree.setVisible(show)
        self._btn_uitree.setChecked(show)
        if show:
            self.uitree.raise_()   # 从 tab 切到前台（与 console 同款行为）
        return show

    def _ui_tree_set_selection(self, elem_name, canvas_idx):
        """UI 树选中变化 -> 检查器切到该元素属性（C3）."""
        if elem_name == self._ui_selected_name and canvas_idx == self._ui_selected_canvas:
            return
        self._ui_selected_name = elem_name
        self._ui_selected_canvas = canvas_idx
        self._insp_last_digest = None
        self._rebuild_inspector()

    def _ui_tree_add_dialog(self, canvas=0, parent=None):
        """UI 树「+ 元素」对话框."""
        import agent_commands as ac
        dlg = QDialog(self)
        dlg.setWindowTitle("添加 UI 元素")
        form = QFormLayout(dlg)
        type_combo = QComboBox()
        type_combo.addItems(list(ac._UI_TYPE_NAMES))
        form.addRow("类型:", type_combo)
        name_edit = QLineEdit('')
        name_edit.setPlaceholderText("(自动生成)")
        form.addRow("名字:", name_edit)
        x_spin = QSpinBox(); x_spin.setRange(-10000, 10000); x_spin.setValue(0)
        y_spin = QSpinBox(); y_spin.setRange(-10000, 10000); y_spin.setValue(0)
        w_spin = QSpinBox(); w_spin.setRange(1, 10000); w_spin.setValue(120)
        h_spin = QSpinBox(); h_spin.setRange(1, 10000); h_spin.setValue(32)
        row_rect = QWidget()
        hr = QHBoxLayout(row_rect); hr.setContentsMargins(0,0,0,0)
        for lab, sp in (('x', x_spin), ('y', y_spin), ('w', w_spin), ('h', h_spin)):
            hr.addWidget(QLabel(lab)); hr.addWidget(sp)
        form.addRow("位置/尺寸:", row_rect)
        parent_label = QLabel(parent or "(Canvas root)")
        form.addRow("父元素:", parent_label)
        canvas_label = QLabel(str(canvas))
        form.addRow("Canvas:", canvas_label)
        btns = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok
                                | QDialogButtonBox.StandardButton.Cancel)
        btns.accepted.connect(dlg.accept)
        btns.rejected.connect(dlg.reject)
        form.addRow(btns)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        args = {
            'type': type_combo.currentText(),
            'canvas': canvas,
            'rect': (x_spin.value(), y_spin.value(),
                     w_spin.value(), h_spin.value()),
        }
        if name_edit.text().strip():
            args['name'] = name_edit.text().strip()
        if parent:
            args['parent'] = parent
        self._invoke_ui_cmd('ui_add', **args)

    def _ui_tree_add_canvas_dialog(self):
        """UI 树「+ Canvas」对话框."""
        dlg = QDialog(self)
        dlg.setWindowTitle("添加 Canvas")
        form = QFormLayout(dlg)
        type_combo = QComboBox()
        type_combo.addItems(['screen', 'world'])
        form.addRow("类型:", type_combo)
        w_spin = QSpinBox(); w_spin.setRange(1, 10000); w_spin.setValue(1280)
        h_spin = QSpinBox(); h_spin.setRange(1, 10000); h_spin.setValue(720)
        form.addRow("宽度:", w_spin)
        form.addRow("高度:", h_spin)
        z_spin = QSpinBox(); z_spin.setRange(-1000, 1000); z_spin.setValue(0)
        form.addRow("z_order:", z_spin)
        btns = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok
                                | QDialogButtonBox.StandardButton.Cancel)
        btns.accepted.connect(dlg.accept)
        btns.rejected.connect(dlg.reject)
        form.addRow(btns)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        self._invoke_ui_cmd('ui_canvas_add',
                            type=type_combo.currentText(),
                            width=w_spin.value(),
                            height=h_spin.value(),
                            z_order=z_spin.value())

    def _build_central(self):
        left = QWidget()
        lv = QVBoxLayout(left)
        lv.setContentsMargins(0, 0, 0, 0)
        lv.setSpacing(0)
        self.hierarchy = QTreeWidget()
        self.hierarchy.setHeaderHidden(True)
        self.hierarchy.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.hierarchy.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.hierarchy.customContextMenuRequested.connect(self._hier_menu)
        self.hierarchy.viewport().installEventFilter(self)
        self._build_hier_tools()          # 层级树区顶部操作按钮行 (+光源/摄像机/显隐)
        self.resources = AssetListWidget()
        self.resources.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.resources.setDragEnabled(True)
        self.resources.itemDoubleClicked.connect(self._res_double)
        self._preview = QFrame()
        self._preview.setFrameShape(QFrame.Shape.StyledPanel)
        pv = QHBoxLayout(self._preview)
        pv.setContentsMargins(6, 4, 6, 4)
        self._preview_label = QLabel("(未选中资产)")
        pv.addWidget(self._preview_label, 1)
        self._btn_apply = QPushButton("应用到选中")
        self._btn_apply.clicked.connect(self._cmd_apply_asset)
        pv.addWidget(self._btn_apply)
        self._btn_place = QPushButton("放入场景")
        self._btn_place.clicked.connect(self._cmd_place_asset)
        pv.addWidget(self._btn_place)
        lv.addWidget(self._hier_tools)
        lv.addWidget(self.hierarchy, 3)
        lv.addWidget(self.resources, 2)
        lv.addWidget(self._preview)
        self._preview.setVisible(False)

        self.inspector_scroll = QScrollArea()
        self.inspector_scroll.setWidgetResizable(True)
        self.inspector = QWidget()
        self.inspector_layout = QFormLayout(self.inspector)
        self.inspector_layout.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        self.inspector_scroll.setWidget(self.inspector)
        self.inspector_scroll.setMinimumWidth(280)
        self.inspector_scroll.setMaximumWidth(400)

        split = QSplitter(Qt.Orientation.Horizontal)
        split.addWidget(left)
        split.addWidget(self.viewport)
        # 右侧 = 检查器(scroll, 可滚动) + 底部数值拖拽块 (2026-08-22,
        # 拖块固定不随滚动, 选中数值行后弹出可拖区)
        side = QWidget()
        sidev = QVBoxLayout(side)
        sidev.setContentsMargins(0, 0, 0, 0)
        sidev.setSpacing(0)
        sidev.addWidget(self.inspector_scroll, 1)
        self._dragblock = DragBlock(side)
        sidev.addWidget(self._dragblock)
        split.addWidget(side)
        split.setStretchFactor(0, 0)
        split.setStretchFactor(1, 1)
        split.setStretchFactor(2, 0)
        split.setSizes([260, 900, 320])
        self.setCentralWidget(split)

    def _build_hier_tools(self):
        """层级树区顶部操作按钮行 (对齐旧版GUI 层级面板 "-- 操作 --" 按钮区):
        + 平行光 / + 点光源 / + 摄像机 / 显隐. 写操作全走 EditorApp 命令,
        视图不直接改模型状态、不自己压撤销栈 (与旧版GUI 相同)."""
        self._hier_tools = QWidget()
        h = QHBoxLayout(self._hier_tools)
        h.setContentsMargins(4, 4, 4, 4)
        h.setSpacing(4)
        pairs = (
            ("+ 平行光", lambda: self._cmd_add_light('directional')),
            ("+ 点光源", lambda: self._cmd_add_light('point')),
            # 2026-10-19 第1档序9 聚光灯
            ("+ 聚光灯", lambda: self._cmd_add_light('spot')),
            ("+ 摄像机", self._cmd_add_camera),
            ("显隐", self._cmd_toggle_visible),
        )
        for text, fn in pairs:
            b = QPushButton(text)
            b.clicked.connect(lambda _=False, f=fn: f())
            h.addWidget(b)

    def _build_statusbar(self):
        self._msg_label = QLabel("")
        self._msg_label.setStyleSheet("color:#666;")
        self.statusBar().addPermanentWidget(self._msg_label)
        # 2026-10-19 移动: UI树/命令行开关按钮移到主工具栏左上角（用户要求）
        # 原因: 状态栏在窗口较小时可能被挤掉看不见，工具栏始终可见。
        sb = QToolButton()
        sb.setText("设置")
        sb.setAutoRaise(True)
        sb.clicked.connect(self._cmd_settings)
        self.statusBar().addPermanentWidget(sb)
    # ---------------- EAI 可视化 (B, 2026-11-07) ----------------
    # AgentService 每执行一条命令回调下列钩子 (getattr 存在才调用, 本类全实现):
    #   _agent_progress(cmd, args, done, total) -> 状态栏进度
    #   _agent_busy(active)                     -> 工具栏红点 + 状态栏变色
    #   _agent_after_command()                  -> 视口立即重绘
    @staticmethod
    def _agent_args_summary(args, limit=40):
        """命令参数 -> 'k=v k=v' 摘要, 超过 limit 字符截断 (末尾省略号)."""
        if not args:
            return ''
        if not isinstance(args, dict):
            txt = str(args)
        else:
            parts = []
            for k, v in args.items():
                if isinstance(v, (dict, list, tuple)):
                    try:
                        v = json.dumps(v, ensure_ascii=False,
                                       separators=(',', ':'))
                    except Exception:
                        v = str(v)
                else:
                    v = str(v)
                parts.append('%s=%s' % (k, v))
            txt = ' '.join(parts)
        txt = txt.replace('\n', ' ').replace('\r', ' ')
        if limit and len(txt) > limit:
            txt = txt[:max(0, limit - 1)] + '…'
        return txt

    def _agent_progress(self, cmd, args, done, total):
        """状态栏: 'AI: <cmd> <参数摘要≤40> (done/total)'.

        窗口已销毁时直接返回 —— 既不碰 QWidget, 也不再排新的空闲定时器
        (U-02: 保证"销毁后静默停表", 而不是每来一条命令再抛一次)。
        """
        if getattr(self, '_agent_gui_dead', False):
            return
        try:
            done_i, total_i = int(done), int(total)
        except Exception:
            done_i, total_i = 0, 0
        summ = self._agent_args_summary(args)
        txt = "AI: %s%s (%d/%d)" % (
            cmd, (" " + summ) if summ else "", done_i, total_i)
        rem = getattr(self, '_agent_batch_remaining', None)
        if rem is not None:
            txt += " · 批次剩余 %ds" % int(rem)
        self._agent_status_active = True
        self.statusBar().showMessage(txt)
        if self._agent_busy_active:
            self.statusBar().setStyleSheet("color:#e06c75;")
        # 空闲 1.5s 恢复默认文本; token 防重入: 新命令让旧定时器自动作废.
        self._agent_idle_token += 1
        tok = self._agent_idle_token
        QTimer.singleShot(1500, lambda: self._agent_idle(tok))

    def _agent_gui_alive(self):
        """窗口底层 C++ 对象是否还活着 (2026-11-08 批4 · 审计 U-02).

        Qt 里窗口 close/deleteLater 之后, 再调它任何方法都会抛
        RuntimeError("Internal C++ object already deleted")。定时器是
        QTimer.singleShot 排的一次性回调, 排完就没了 —— 真正要防的是
        "_refresh_status 抛出来后每来一条命令又排一个新定时器、每次再抛一遍"。
        """
        if getattr(self, '_agent_gui_dead', False):
            return False
        try:
            self.statusBar()
            return True
        except RuntimeError as e:            # 只认"对象已销毁"这一类
            self._agent_gui_dead = True
            self._agent_gui_warn_once('statusBar 已失效 (%s): %s'
                                      % (type(e).__name__, e))
            return False
        except Exception as e:               # 其它异常: 记一次原因, 复现照旧
            self._agent_gui_warn_once('statusBar 访问异常: %r' % (e,))
            return False

    def _agent_gui_warn_once(self, reason):
        """GUI 已销毁/异常时只告警一次 (之后静默, 避免每帧刷屏)."""
        if getattr(self, '_agent_gui_warned', False):
            return
        self._agent_gui_warned = True
        try:
            import sys as _sys
            print('[agent] GUI 状态栏不可用, 之后静默: %s' % reason,
                  file=_sys.stderr)
        except Exception as e:
            self._agent_gui_warned = False
            print('[agent] 告警输出失败: %r (原因: %s)' % (e, reason))

    def _agent_idle(self, token):
        """1.5s 无新命令: 释放状态栏, 回落 _refresh_status 的默认文本.

        2026-11-08 批4 (审计 U-02): 旧实现把 `_refresh_status()` 放在所有 try 之外,
        窗口销毁后定时器一触发就抛 RuntimeError; 现在:
          · 先判窗口是否还活着 (_agent_gui_alive, 销毁即静默停表);
          · _refresh_status 包 try, 失败**只告警一次并带原因** (不无差别吞).
        """
        if token != getattr(self, '_agent_idle_token', -1):
            return                      # 期间又来了新命令, 旧定时器作废
        if getattr(self, '_agent_batch_active', False):
            return                      # 批次提示占用状态栏 (D10 可视化), 不清
        if not self._agent_gui_alive():
            return                      # 窗口已销毁: 静默停止, 不再碰任何 QWidget
        self._agent_status_active = False
        if not self._agent_busy_active:
            try:
                self.statusBar().setStyleSheet("")
            except RuntimeError as e:
                self._agent_gui_warn_once('setStyleSheet 失败 (%s): %s'
                                          % (type(e).__name__, e))
                return
        try:
            self.statusBar().clearMessage()
        except RuntimeError as e:
            self._agent_gui_warn_once('clearMessage 失败 (%s): %s'
                                      % (type(e).__name__, e))
            return
        try:
            self._refresh_status()
        except RuntimeError as e:
            self._agent_gui_warn_once('_refresh_status 失败 (%s): %s'
                                      % (type(e).__name__, e))
        except Exception as e:
            # 非"对象已销毁"类异常: 只告警一次, 带上类型与原因, 不静默
            self._agent_gui_warn_once('_refresh_status 异常: %r' % (e,))

    @staticmethod
    def _agent_tb_visible(act, widget, visible):
        """QToolBar 内控件的可靠显隐: 先切 QWidgetAction, 再切控件本身.

        只切 action 时, 若窗口 show 时 action 恰好不可见, 工具栏会给控件打上
        显式 hide 标记, 之后再 action.setVisible(True) 控件仍不出现 (实测)."""
        visible = bool(visible)
        if act is not None:
            act.setVisible(visible)
        if widget is not None:
            widget.setVisible(visible)

    def _agent_busy(self, active):
        """工具栏红点显隐 + 状态栏文字颜色 (#e06c75 表示 Agent 执行中)."""
        self._agent_busy_active = bool(active)
        self._agent_tb_visible(getattr(self, '_act_agent_busy', None),
                               getattr(self, '_lbl_agent_busy', None),
                               self._agent_busy_active)
        try:
            if self._agent_busy_active:
                self.statusBar().setStyleSheet("color:#e06c75;")
                if not self._agent_status_active:
                    self.statusBar().showMessage("AI: 操作中…")
            else:
                self.statusBar().setStyleSheet("")
                if not self._agent_status_active:
                    self.statusBar().clearMessage()
        except Exception:
            pass

    def _agent_batch_status(self, remaining):
        """Agent 批次租约状态 (2026-11-08 批4 / 裁决 D10).

        remaining=None -> 批次结束/没有批次: 清提示并回落默认文本;
        remaining=数字  -> 状态栏 'Agent 批次进行中（剩余 Xs）'.

        AgentService 每拍调 (只在"剩余秒数变化"时), 所以这里不做节流。
        """
        self._agent_batch_remaining = None if remaining is None else int(remaining)
        self._agent_batch_active = remaining is not None
        try:
            if remaining is None:
                self._agent_status_active = False
                self.statusBar().setStyleSheet("")
                self.statusBar().clearMessage()
                self._refresh_status()
            else:
                self._agent_status_active = True
                self.statusBar().showMessage(
                    "Agent 批次进行中（剩余 %ds）" % int(remaining))
        except Exception as e:
            print("[agent] 批次状态栏更新失败: %r" % (e,))

    def _agent_after_command(self):
        """每条命令执行完强制重绘视口, 保证人眼立刻看到结果."""
        vp = getattr(self, 'viewport', None)
        if vp is not None:
            try:
                vp.update()
            finally:
                vp.repaint()

    def _bind_agent_service(self, agent):
        """--agent 分支 / 测试: 绑定 AgentService (可视化钩子由服务侧 getattr 调用)."""
        self._agent_service = agent
        return agent

    # ---------------- 命令行坞 (EAI P2①, 2026-08-27) ----------------
    def _build_console(self):
        """底部命令行坞: 输入 -> agent_commands.dispatch (与远程 EAI 同一张
        命令表), 输出 = 命令结果 + 引擎日志环增量. 默认隐藏, 状态栏
        [命令行] 按钮 / F12 开关 (视口面积不被默认占用)."""
        from ui import qt_console
        self.console = qt_console.ConsoleDock(self)
        self.addDockWidget(Qt.DockWidgetArea.BottomDockWidgetArea, self.console)
        self.console.resize(self.console.width(), 200)
        self.console.hide()
        # 坞被用户点 X 关闭时同步按钮态 (否则按钮显示"按下"但坞已关)
        self.console.visibilityChanged.connect(
            lambda vis: self._btn_console.setChecked(bool(vis)))

    def _cmd_console(self, checked=None):
        """[命令行] 按钮 / F12: 开关命令行坞 (打开时输入框自动获得焦点)."""
        show = not self.console.isVisible() if checked is None else bool(checked)
        self.console.setVisible(show)
        self._btn_console.setChecked(show)
        if show:
            self.console.entry.setFocus()
        return show

    # ---------------- 发布游戏 (Unity Build Settings 对齐, 2026-08-22) ----------------
    def _build_tool_cmd(self, extra_args):
        """构建器启动命令: 优先 <程序目录>/build_game.exe (编译版用户无 python);
        源码版用当前解释器跑 build/build_game.py. 程序目录解析同 guiloader."""
        import guiloader
        bin_dir = guiloader.program_dir()
        exe_tool = os.path.join(bin_dir, 'build_game.exe')
        if os.path.isfile(exe_tool):
            return [exe_tool] + extra_args
        py = sys.executable
        if not py or not os.path.isfile(os.path.join(bin_dir, 'build', 'build_game.py')):
            return None    # 编译版无工具/无解释器 -> 提示
        return [py, os.path.join(bin_dir, 'build', 'build_game.py')] + extra_args

    def _cmd_publish_game(self):
        """[发布游戏]: Build Settings 对话框 (游戏名/公司名/启动场景/脚本目录/
        输出目录) -> 子进程 build_game.py -> 完成 toast + 打开发布夹."""
        e = self.editor
        if e is None:
            return
        import filedialog
        dlg = QDialog(self)
        dlg.setWindowTitle("发布游戏 (Build Settings)")
        form = QFormLayout(dlg)
        edit_name = QLineEdit(e.scene_name or "我的游戏")
        edit_tb = QLineEdit(e.scene_name or "我的游戏")
        edit_co = QLineEdit("")
        edit_scene = QLineEdit(getattr(e, '_scene_path', '') or "")
        edit_scripts = QLineEdit("")
        edit_out = QLineEdit("")
        import guiloader
        import plugin.loader as plugin_loader
        def _script_dir_default():
            d = os.path.join(plugin_loader._PROGRAM_DIR, 'scripts')
            return d if os.path.isdir(d) else ""
        edit_scripts.setText(_script_dir_default())
        b_scene = QPushButton("浏览")
        b_scene.clicked.connect(lambda: edit_scene.setText(
            filedialog.open_file("选择启动场景", os.path.dirname(edit_scene.text() or ''),
                                 None, "*.json", "json") or edit_scene.text()))
        b_scripts = QPushButton("浏览")
        b_scripts.clicked.connect(lambda: edit_scripts.setText(
            filedialog.choose_directory("选择游戏脚本目录") or edit_scripts.text()))
        b_out = QPushButton("浏览")
        b_out.clicked.connect(lambda: edit_out.setText(
            filedialog.choose_directory("选择输出目录") or edit_out.text()))
        h1 = QHBoxLayout(); h1.addWidget(edit_scene, 1); h1.addWidget(b_scene)
        h2 = QHBoxLayout(); h2.addWidget(edit_scripts, 1); h2.addWidget(b_scripts)
        h3 = QHBoxLayout(); h3.addWidget(edit_out, 1); h3.addWidget(b_out)
        form.addRow("游戏名", edit_name)
        form.addRow("公司名", edit_co)
        form.addRow("窗口标题", edit_tb)
        form.addRow("启动场景", h1)
        form.addRow("游戏脚本目录\n(加密打包)", h2)
        form.addRow("输出目录", h3)
        btns = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok |
                                QDialogButtonBox.StandardButton.Cancel)
        btns.button(QDialogButtonBox.StandardButton.Ok).setText("构建")
        btns.button(QDialogButtonBox.StandardButton.Cancel).setText("取消")
        btns.accepted.connect(dlg.accept)
        btns.rejected.connect(dlg.reject)
        form.addRow(btns)
        dlg.resize(460, 300)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        scene = edit_scene.text().strip()
        if not scene or not os.path.isfile(scene):
            e._notify("启动场景不存在: %s" % scene, (220, 120, 120))
            return
        out = edit_out.text().strip() or os.path.join(
            os.path.dirname(scene), '发布_' + edit_name.text().strip())
        args = ['--name', edit_name.text().strip() or '我的游戏',
                '--company', edit_co.text().strip(),
                '--title', edit_tb.text().strip() or edit_name.text().strip(),
                '--scene', scene, '--output', out]
        if edit_scripts.text().strip():
            args += ['--game-scripts', edit_scripts.text().strip()]
        cmd = self._build_tool_cmd(args)
        if cmd is None:
            e._notify("缺少构建器: 放 build_game.py(源码版) 或 build_game.exe 到程序目录",
                      (220, 120, 120))
            return
        self._pub_proc = subprocess.Popen(cmd, cwd=os.path.dirname(scene))
        self._pub_out_path = out          # 完成后打开发布夹
        self._pub_tick = 0
        if getattr(self, '_pub_timer', None) is None:
            self._pub_timer = QTimer(self)
            self._pub_timer.setInterval(2000)
            self._pub_timer.timeout.connect(self._poll_publish)
        self._pub_timer.start()
        e._notify("正在构建游戏… (首次含打包运行时需数分钟)", (200, 200, 220))

    def _poll_publish(self):
        """构建轮询: 完成后 toast + 打开发布夹 (子进程非阻塞)."""
        e = self.editor
        proc = getattr(self, '_pub_proc', None)
        if proc is None:
            if getattr(self, '_pub_timer', None) is not None:
                self._pub_timer.stop()
            return
        self._pub_tick += 1
        rc = proc.poll()
        if rc is None and self._pub_tick % 15 == 0:   # 每 30s 报一次状态
            e._notify("正在构建游戏… (%ds)" % (self._pub_tick * 2), (180, 180, 200))
            return
        if rc is None:
            return
        out = getattr(self, '_pub_out_path', '')
        if rc == 0:
            e._notify("发布完成: %s" % out, (150, 220, 150))
        else:
            e._notify("发布失败 (退出码 %d): %s" % (rc, out), (220, 120, 120))
        try:
            if os.path.isdir(out):
                os.startfile(out)
        except Exception:
            pass
        self._pub_proc = None

    def _apply_fps_limit(self, fps_limit=None):
        """按 设置.json 的 fps_limit 档位设置渲染定时器周期 (即时生效).
        档位: 30/60/90/120/240/unlimited/auto(按设备检测, 见 guiloader.device_fps_limit).
        限帧器校准 (2026-09-05 调研方案一): QTimer 1ms 在 Windows 实际抖动大
        (系统定时器粒度+事件循环阻塞, 实测 10-150FPS 飘) — unlimited 档改
        自校准混合等待 (QTimer 仅作 1ms 唤醒源, 帧尾在 _on_tick 里睡到
        目标节律: sleep 大段 + 忙等 4ms 收尾, Panda3D wait_until 语义 /
        kivy MIN_SLEEP=5ms·UNDERSHOOT=4ms 参数样本).
        逃生门: 设置键 'precise_limit': False → 回退旧 QTimer 纯驱动."""
        import guiloader
        if fps_limit is None:
            fps_limit = guiloader.load_settings('loom').get('fps_limit', '120')
        if fps_limit == 'auto':
            fps_limit = guiloader.device_fps_limit()
        interval = guiloader.FPS_LIMITS.get(fps_limit, 8)
        s = guiloader.load_settings('loom')
        self._calibrated = bool(s.get('precise_limit', True))
        # 方案一: 档位模式 (30-240) 校准开 → _tick_period=目标周期, 帧首
        # wait_until 对齐固定节拍网格 (消 QTimer 到达抖动); unlimited/逃生门
        # → None = 纯 QTimer 驱动行为同旧 (无上限不做 pacing, kivy maxfps=0)
        self._tick_period = (interval / 1000.0
                             if (self._calibrated and fps_limit != 'unlimited')
                             else None)
        self._tick_target = None
        self._render_timer.start(interval)
        label = {'30': '30fps', '60': '60fps', '90': '90fps', '120': '120fps',
                 '240': '240fps', 'unlimited': '无上限'}.get(fps_limit, fps_limit)
        self._fps_limit_mode = fps_limit
        # FPS 缓冲 (2026-09-06 实验): 档位变化即重判闸门 (>=60 且非无上限)
        e = self.editor
        rb = getattr(e, '_render_buf', None) if e is not None else None
        if rb is not None:
            rb.configure(guiloader.load_settings('loom'), fps_limit)
        print("[Qt] 帧率上限:", label, "(周期 %dms%s)" % (
            interval, ", 混合等待校准" if self._tick_period is not None else ""))

    @staticmethod
    def _wait_until(target, min_sleep=0.0015, undershoot=0.001):
        """优化混合等待到 target (perf_counter 秒, 1ms 多媒体时钟纳管):
        通过 timeBeginPeriod(1) 将 Windows 系统调度粒度定在 1ms;
        大段与中间段均通过释放 GIL 的 time.sleep 睡掉，仅在最后 <0.4ms 进行微自旋收尾，
        彻底消灭原 4ms 霸占 GIL 的死循环，彻底释放后台异步逻辑线程与调度器。"""
        _init_winmm_timer()
        while True:
            remain = target - time.perf_counter()
            if remain <= 0.0:
                return
            if remain > min_sleep:
                time.sleep(remain - undershoot)
            else:
                if remain > 0.0004:
                    time.sleep(0)  # 让渡时间片并释放 GIL
                end = target
                while time.perf_counter() < end:
                    pass
                return

    def _cmd_set_parallel(self, on):
        """多核并行复选框 (Q-B7-56-2 裁定①): 设置写盘翻译成 settings_set 命令
        (命令体 = guiloader load/save 同一入口); 重启生效提示保留。
        网格显隐复选框不在此列 —— 编辑器视图状态, 终审判定豁免。"""
        self._invoke_cmd('settings_set', {'key': 'parallel_enable',
                                          'value': bool(on)})
        e = self.editor
        if e is not None:
            e._notify("并行开关重启后生效", (240, 200, 90))

    def _cmd_set_render_api(self, index):
        """渲染后端下拉框（Q-B7-60-1 裁定①② + 2026-11-25 终审 P1-1 单层化）。

        人类 2026-11-23 裁决「一个键全局消费」: 这里写的 render_api 既是播放/打包
        游戏的后端，也是**编辑器视口**的后端（编辑器侧读它走
        hostenv.editor_launch.editor_backend_choice -> run_player.resolve_backend）。
        裁决①「重启编辑器生效」: 不做视口热切换，故只落盘 + 提示重启，不重建视口。

        P1-1（修前缺陷）: 面板原来只写**引擎层**，而解析链优先级是 游戏层 > 引擎层 ——
        播放器 VK 失败回退把游戏层写成 opengl 后，面板显示 vulkan、生效却是 opengl，
        且「改回」无效。现在写盘走**唯一写盘路径** write_render_api_choice（同一份函数
        也被 VK 装配失败自动回退使用）: 引擎层写入 + 清游戏层覆盖键 + 复核生效值。
        """
        combo = getattr(self, '_render_api_combo', None)
        api = combo.itemData(index) if combo is not None else None
        if not api:
            return
        from hostenv.editor_launch import write_render_api_choice
        # invoke=self._invoke_cmd = 与设置面板同一条命令壳入口（settings_set）
        res = write_render_api_choice(api, invoke=self._invoke_cmd)
        if not res.get('ok'):
            self._notify_or_print("渲染后端保存失败：%s" % (res.get('error'),),
                                  (235, 90, 90))
            return
        self._notify_or_print(
            "渲染后端已保存（生效值 %s）：编辑器视口与播放/打包游戏共用此键，"
            "重启编辑器/播放器后生效" % (res.get('effective'),), (240, 200, 90))

    # ---------------- 层级树 ----------------
    def _hier_data(self, item):
        """item -> ('model'|'light'|'camera', index) 或 None."""
        if item is None:
            return None
        return item.data(0, Qt.ItemDataRole.UserRole)

    def _rebuild_hierarchy(self):
        e = self.editor
        tree = self.hierarchy
        tree.blockSignals(True)
        tree.clear()
        try:
            # 对象 (DFS 前序, 子级挂父 item)
            head = QTreeWidgetItem(["对象 (%d)" % len(e.models)])
            head.setFlags(head.flags() & ~Qt.ItemFlag.ItemIsEnabled)
            head.setForeground(0, QBrush(QColor('#888888')))
            tree.addTopLevelItem(head)
            head.setExpanded(True)   # 分组头默认折叠 -> 对象行不可见 (2026-08-18 bug)
            self._hier_obj_item = {}
            rows = e._hierarchy_rows()
            for i, (depth, m) in enumerate(rows):
                item = QTreeWidgetItem(["%s %s" % ('√' if m.visible else '×', m.name)])
                item.setData(0, Qt.ItemDataRole.UserRole, ('model', i))
                item.setExpanded(True)
                if m.parent is not None:
                    pitem = self._hier_obj_item.get(id(m.parent))
                    if pitem is not None:
                        pitem.addChild(item)
                    else:
                        head.addChild(item)
                else:
                    head.addChild(item)
                self._hier_obj_item[id(m)] = item
                if i == e.selected_index and e.selected_light_index < 0 \
                        and e.selected_camera_index < 0:
                    item.setBackground(0, QBrush(QColor('#2d5a88')))
            # 光源
            head = QTreeWidgetItem(["— 光源 (%d) —" % len(e.lights)])
            head.setFlags(head.flags() & ~Qt.ItemFlag.ItemIsEnabled)
            head.setForeground(0, QBrush(QColor('#888888')))
            tree.addTopLevelItem(head)
            head.setExpanded(True)
            for i, l in enumerate(e.lights):
                mark = '◎' if l.kind == 'directional' else '●'
                item = QTreeWidgetItem(["%s %s" % (mark, l.name)])
                item.setData(0, Qt.ItemDataRole.UserRole, ('light', i))
                head.addChild(item)
                if i == e.selected_light_index:
                    item.setBackground(0, QBrush(QColor('#2d5a88')))
            # 摄像机
            head = QTreeWidgetItem(["— 摄像机 (%d) —" % len(e.cameras)])
            head.setFlags(head.flags() & ~Qt.ItemFlag.ItemIsEnabled)
            head.setForeground(0, QBrush(QColor('#888888')))
            tree.addTopLevelItem(head)
            head.setExpanded(True)
            for i, c in enumerate(e.cameras):
                lock = '锁' if c.fov_locked else '开'
                item = QTreeWidgetItem(["◇ %s [%s]" % (c.name, lock)])
                item.setData(0, Qt.ItemDataRole.UserRole, ('camera', i))
                head.addChild(item)
                if i == e.selected_camera_index:
                    item.setBackground(0, QBrush(QColor('#2d5a88')))
        finally:
            tree.blockSignals(False)
        # 2026-08-22: setExpanded(True) 必须在 item 已入树 (已 addChild/addTopLevelItem)
        # 之后调用才生效 —— Qt 对"未入树"的 item 设置 expanded 会被忽略 (探针实测:
        # 入树前 False / 入树后 True). 上面循环里 946 行 setExpanded 发生在 addChild
        # 之前 → 每次 rebuild 后所有带子行全折叠, 用户实测: 挂父后点箭头"闪一下
        # 收回 / 二级挂父列表打不开". 重建完成后统一全展开 (head 行一直这么做, OK).
        def _expand_all(it):
            it.setExpanded(True)
            for i in range(it.childCount()):
                _expand_all(it.child(i))
        for i in range(tree.topLevelItemCount()):
            _expand_all(tree.topLevelItem(i))

    def _hier_arrow_zone(self, item, pos):
        """点击位置是否命中该行的展开/折叠箭头 (item 视觉矩形左侧的分支指示器区).
        2026-08-22: 箭头区点击必须走 Qt 原生 toggle, 不能劫持成"选中+刷新" ——
        _hier_digest 含 selected_index, 点击箭头落入 release 单击分支会选中该行 →
        digest 变化 → _refresh_all → 整树 rebuild → 用户刚点击的展开/折叠被整体
        抹掉 (旧 item 引用也被删), 现象=用户实测"闪一下收回/二级挂父打不开"."""
        if item.childCount() <= 0:
            return False   # 无子项的行没有箭头, 不拦截
        rect = self.hierarchy.visualItemRect(item)
        return rect.left() - self.hierarchy.indentation() <= pos.x() < rect.left()

    def _hier_item_at(self, pos):
        return self.hierarchy.itemAt(pos.toPoint())

    def eventFilter(self, obj, ev):
        """两级过滤:
        1) 应用级键盘 (installEventFilter(QApplication)): 焦点不在文本/列表/按钮
           控件时, 按键转发给视口 —— 窗口级键盘, 对齐 pygame 版体验 (2026-08-18).
        2) 层级树鼠标: 左键按下记录起点, 松开解析 (单击=选中 / 拖行=挂父 / 拖空白=脱父).
        """
        if obj is not self.hierarchy.viewport():
            t = ev.type()
            # F12 = 命令行坞开关 (2026-08-27). 必须在这里判: 应用级事件过滤器
            # 先于 QShortcutMap 拿到按键并 return True, QShortcut 永远不会触发.
            if t == QEvent.Type.KeyPress and ev.key() == Qt.Key.Key_F12:
                self._cmd_console()
                return True
            # 2026-10-19: F11 = UI 树坞开关（与 F12 同款机制）
            if t == QEvent.Type.KeyPress and ev.key() == Qt.Key.Key_F11:
                self._cmd_uitree()
                return True
            if t in (QEvent.Type.KeyPress, QEvent.Type.KeyRelease):
                fw = QApplication.focusWidget()
                if not isinstance(fw, (QLineEdit, QComboBox, QDoubleSpinBox,
                                       QAbstractItemView, QPushButton,
                                       QPlainTextEdit)):   # 命令行输出区可选中复制
                    if t == QEvent.Type.KeyPress:
                        self.viewport.keyPressEvent(ev)
                    else:
                        self.viewport.keyReleaseEvent(ev)
                    return True   # 已消费, 不再分发
        elif obj is self.hierarchy.viewport():
            t = ev.type()
            if t == QEvent.Type.MouseButtonPress and ev.button() == Qt.MouseButton.LeftButton:
                item = self._hier_item_at(ev.position())
                if item is not None and self._hier_arrow_zone(item, ev.position()):
                    # 展开/折叠箭头: 不记录拖拽起点, 不拦截 —— 事件继续传给
                    # QTreeView 原生 toggle (否则 release 选中+刷新会 rebuild 抹掉
                    # 用户刚点的展开/折叠, 见 _hier_arrow_zone 注释)
                    return False
                d = self._hier_data(item)
                if d is not None and d[0] == 'light':
                    # 光源行: 按下即选中 (不参与拖拽, 与旧版GUI 一致)
                    self._select_by_kind(*d)
                self._hier_down = (ev.position(), d)
                self._hier_pressed = True
            elif t == QEvent.Type.MouseButtonRelease and ev.button() == Qt.MouseButton.LeftButton:
                self._hier_pressed = False
                if self._hier_down is not None:
                    start, d0 = self._hier_down
                    item1 = self._hier_item_at(ev.position())
                    d1 = self._hier_data(item1)
                    if (ev.position() - start).manhattanLength() < 5:
                        if d0 is not None and d0[0] != 'light':
                            self._select_by_kind(*d0)
                    else:
                        self._hier_drop(d0, d1)
                    self._hier_down = None
                    self._refresh_all()
        return super().eventFilter(obj, ev)

    def _select_by_kind(self, kind, idx):
        e = self.editor
        if e is None:
            return
        if kind == 'model':
            e._select_model(idx)
        elif kind == 'light':
            e.selected_light_index = idx
            e.selected_index = -1
            e.selected_camera_index = -1
        elif kind == 'camera':
            if 0 <= idx < len(e.cameras):
                e._select_camera(e.cameras[idx])

    def _hier_drop(self, d0, d1):
        """拖拽落点解析: 拖到行=挂父, 拖空白=脱父 (仅对象/相机参与).

        Q-B7-56-1 裁定① (2026-11-22): 挂父/脱父本体翻译成 reparent 命令 (物体与
        相机共用同一条命令, 命令层内含脱父/自挂/成环判据, 与本函数的拖拽预判
        一致; 无效拖拽只选中不翻译, 保持旧 UX)。拖拽手势本身属鼠标豁免面,
        命令化的只是落点解析后的那次写操作。
        """
        e = self.editor
        if e is None or d0 is None:
            return
        kind0, idx0 = d0
        src = None
        if kind0 == 'model' and 0 <= idx0 < len(e.models):
            src = e.models[idx0]
        elif kind0 == 'camera' and 0 <= idx0 < len(e.cameras):
            src = e.cameras[idx0]
        if src is None:
            return
        if d1 is None:
            # 拖空白: 有父则脱父 (reparent 命令缺 parent = 脱父)
            if getattr(src, 'parent', None) is not None:
                self._invoke_cmd('reparent', {'child': src.name})
            return
        kind1, idx1 = d1
        dst = None
        if kind1 == 'model' and 0 <= idx1 < len(e.models):
            dst = e.models[idx1]
        elif kind1 == 'camera' and 0 <= idx1 < len(e.cameras):
            dst = e.cameras[idx1]
        if dst is None or dst is src:
            return
        if kind0 == kind1 == 'model':
            # 不拖到自身/父/后代 (命令层同判据)
            if not self._is_ancestor(dst, src) and src.parent is not dst:
                self._invoke_cmd('reparent', {'child': src.name,
                                              'parent': dst.name})
            else:
                e._select_model(idx0)
        elif kind0 == kind1 == 'camera':
            if src.parent is not dst:
                self._invoke_cmd('reparent', {'child': src.name,
                                              'parent': dst.name})

    @staticmethod
    def _is_ancestor(anc, m):
        p = m.parent
        while p is not None:
            if p is anc:
                return True
            p = p.parent
        return False

    # ---------------- 层级右键菜单 ----------------
    def _hier_menu(self, pos):
        e = self.editor
        if e is None:
            return
        item = self.hierarchy.itemAt(pos)
        d = self._hier_data(item)
        if d is None:
            return
        kind, idx = d
        self._select_by_kind(kind, idx)
        menu = QMenu(self)
        if kind == 'model' and 0 <= idx < len(e.models):
            m = e.models[idx]
            menu.addAction("重命名", lambda: self._rename_obj(m))
            menu.addAction("复制", self._cmd_dup)
            menu.addAction("删除", self._cmd_del)
            if m.parent is not None:
                # Q-B7-56-1 裁定①: 脱父翻译成 reparent 命令 (缺 parent = 脱父)
                menu.addAction("脱父", lambda: self._invoke_cmd(
                    'reparent', {'child': m.name}))
        elif kind == 'light' and 0 <= idx < len(e.lights):
            l = e.lights[idx]
            menu.addAction("重命名", lambda: self._rename_light(l))
            menu.addAction("删除", self._cmd_del)
        elif kind == 'camera' and 0 <= idx < len(e.cameras):
            c = e.cameras[idx]
            menu.addAction("重命名", lambda: self._rename_camera(c))
            # Q-B7-56-2 裁定①: 预览/激活翻译成 camera_preview / camera_active 命令
            menu.addAction("用此相机预览", lambda: self._invoke_cmd(
                'camera_preview', {'name': c.name}))
            menu.addAction("取消激活" if e.active_camera == c.guid else "设为激活相机",
                           lambda: self._invoke_cmd(
                               'camera_active', {}
                               if e.active_camera == c.guid else {'name': c.name}))
            if c.parent is not None:
                # Q-B7-56-1 裁定①: 相机脱父同样走 reparent 命令
                menu.addAction("脱父", lambda: self._invoke_cmd(
                    'reparent', {'child': c.name}))
            menu.addAction("删除", self._cmd_del)
        menu.exec(self.hierarchy.viewport().mapToGlobal(pos))
        self._refresh_all()

    def _ask_text(self, title, prompt, initial):
        text, ok = QInputDialog.getText(self, title, prompt, text=initial)
        return text if ok else None

    def _rename_obj(self, m):
        v = self._ask_text("重命名", "新名称:", m.name)
        if v is not None and self.editor is not None:
            # Q-B7-56-1 裁定①: 改名翻译成 object_rename 命令 (命令层按名字解析
            # 三类目标, 命令体 = ed.rename/rename_light/rename_camera 同一入口;
            # 重名/非法名由命令层查实际结果报 error -> _notify, 与旧 toast 等价)
            self._invoke_cmd('object_rename', {'name': m.name, 'new': v})
            self._refresh_all()

    def _rename_light(self, l):
        v = self._ask_text("重命名", "新名称:", l.name)
        if v is not None and self.editor is not None:
            self._invoke_cmd('object_rename', {'name': l.name, 'new': v})
            self._refresh_all()

    def _rename_camera(self, c):
        v = self._ask_text("重命名", "新名称:", c.name)
        if v is not None and self.editor is not None:
            self._invoke_cmd('object_rename', {'name': c.name, 'new': v})
            self._refresh_all()

    # ---------------- 资源面板 ----------------
    def _rebuild_resources(self):
        e = self.editor
        rl = self.resources
        rl.blockSignals(True)
        rl.clear()
        self._assets = []       # [(type, key), ...] 与行顺序对应
        groups = {'mesh': ('网格', '□'), 'material': ('材质', '■'), 'prefab': ('Prefab', '◆')}
        by = {'mesh': [], 'material': [], 'prefab': []}
        for it in e._scan_assets():
            by.setdefault(it.get('type'), []).append(it)
        for gtype in ('mesh', 'material', 'prefab'):
            name, mark = groups[gtype]
            items = by[gtype]
            head = QListWidgetItem("— %s (%d) —" % (name, len(items)))
            head.setFlags(head.flags() & ~Qt.ItemFlag.ItemIsEnabled)
            head.setForeground(QColor('#888888'))
            rl.addItem(head)
            for it in items:
                disp = it.get('name') or os.path.basename(it.get('key', '?'))
                row = QListWidgetItem("%s %s" % (mark, disp))
                row.setData(Qt.ItemDataRole.UserRole, (it.get('type'), it.get('key')))
                rl.addItem(row)
                self._assets.append((it.get('type'), it.get('key')))
        rl.blockSignals(False)

    def _res_item_data(self, item):
        if item is None:
            return None
        return item.data(Qt.ItemDataRole.UserRole)

    def _res_double(self, item):
        """双击: 放入场景 (视口中心)."""
        e = self.editor
        d = self._res_item_data(item)
        if e is None or d is None:
            return
        # Q-B7-56-2 裁定①: 双击翻译成 asset_place 命令 (命令体 =
        # e._asset_drop_to_scene(it, 视口中心), 同一入口; 拖拽落场景仍走鼠标豁免面)
        self._invoke_cmd('asset_place', {'type': d[0], 'key': d[1]})
        self._refresh_all()

    def _cmd_apply_asset(self):
        e = self.editor
        if e is None or self._res_selected is None:
            return
        # Q-B7-56-2 裁定①: 应用材质资产翻译成 asset_apply 命令 (命令体 =
        # e._apply_material_asset(it, m), 同一入口)
        self._invoke_cmd('asset_apply', {'type': self._res_selected[0],
                                         'key': self._res_selected[1]})
        self._refresh_all()

    def _cmd_place_asset(self):
        e = self.editor
        if e is None or self._res_selected is None:
            return
        # Q-B7-56-2 裁定①: 放入场景按钮翻译成 asset_place 命令 (同双击)
        self._invoke_cmd('asset_place', {'type': self._res_selected[0],
                                         'key': self._res_selected[1]})
        self._refresh_all()

    # ---------------- 检查器 ----------------
    def _insp_target(self):
        """当前检查器目标 (含类型). ('obj'|'light'|'camera'|'ui', 对象)."""
        e = self.editor
        if e is None or e.is_playing:
            return None
        # 2026-10-18 阶段5: UI 树选中的元素优先（C3 联动）
        if self._ui_selected_name is not None and self._ui_selected_canvas is not None:
            ui = getattr(e, 'ui', None)
            if ui is not None and self._ui_selected_canvas < len(ui.canvases):
                c = ui.canvases[self._ui_selected_canvas]
                elem = c.root.find(self._ui_selected_name)
                if elem is not None:
                    return ('ui', elem)
        # 2026-10-19 第1档序3阶段4: 选中 Canvas 节点本身 -> Canvas 属性面板
        if self._ui_selected_name is None and self._ui_selected_canvas is not None:
            ui = getattr(e, 'ui', None)
            if ui is not None and self._ui_selected_canvas < len(ui.canvases):
                return ('canvas', ui.canvases[self._ui_selected_canvas])
        m = e._selected()
        if m is not None:
            return ('obj', m)
        l = e._selected_light()
        if l is not None:
            return ('light', l)
        c = e._selected_camera()
        if c is not None:
            return ('camera', c)
        return None

    def _insp_key_of(self):
        e = self.editor
        if e is None:
            return None
        if e.is_playing:
            return ('play',)
        t = self._insp_target()
        if t is None:
            return None
        kind, obj = t
        # 2026-10-18 阶段5: UI 元素用 (canvas_idx, name) 标识（元素会重建, id 不稳）
        if kind == 'ui':
            return ('ui', self._ui_selected_canvas, self._ui_selected_name)
        if kind == 'canvas':
            return ('canvas', self._ui_selected_canvas)
        return (kind, id(obj))

    def _rebuild_inspector(self):
        """清空并重建检查器表单 (选中目标变化时).
        2026-08-22 修复: 清空必须先 setParent(None) 立即脱离 —— 原 deleteLater
        是异步延迟删除, 旧按钮仍占据面板, 重建后新旧按钮重叠错位 (用户实测
        "截面按钮绑定到阴影/光柱未切换"根因: 点到的其实是旧面板残留按钮)."""
        e = self.editor
        lay = self.inspector_layout
        while lay.count():
            item = lay.takeAt(0)
            w = item.widget()
            if w is not None:
                w.setParent(None)   # 立即从父容器/布局移除 (视觉即刻消失)
                w.deleteLater()     # 事件循环空闲时回收 C++ 对象
        self._spins = {}
        self._spin_meta = {}
        self._dragblock.hide_target()       # 旧行全部失效, 拖拽块收起
        self._INSP_LE_CACHE = None          # 表单重建, QLineEdit 集合缓存失效
        self._building = True
        try:
            t = self._insp_target()
            if t is None:
                if e.is_playing:
                    lay.addRow(QLabel("→ 播放中 —— 停止后回到编辑"))
                else:
                    lay.addRow(QLabel("(未选中对象)"))
                return
            kind, obj = t
            if kind == 'obj':
                self._build_obj_inspector(lay, obj)
            elif kind == 'light':
                self._build_light_inspector(lay, obj)
            elif kind == 'ui':
                # 2026-10-18 阶段5: UI 元素检查器
                self._build_ui_inspector(lay, obj)
            elif kind == 'canvas':
                # 2026-10-19 第1档序3阶段4: Canvas 属性面板
                self._build_canvas_inspector(lay, obj)
            else:
                self._build_camera_inspector(lay, obj)
        finally:
            self._building = False

    # ---- 数值行通用 (撤销接线: 命令化数值行编辑会话批, 合一步撤销) ----
    def _spin(self, lay, label, value, lo, hi, key, apply, step=0.1, dec=3):
        """数值行通用入口 (2026-08-22 加拖拽调节): QDoubleSpinBox + 聚焦后检查器
        底部弹出 DragBlock 拖区 (按住左右拖动调值, 每像素=step). 后续新增可拖条
        数值行只需继续调用本函数, 自动获得拖拽调节 + 撤销. apply(v) 已翻译成
        EAI 命令 (每条自带一步撤销; Q-B7-56-1 裁定① + Q-B7-56-2 扫尾后全部
        数值行命令化): 撤销/教学日志/刷新由**数值行编辑会话批**协议接管
        (_spin_session_begin/end —— 会话内连续命令合成一步撤销, 对齐旧快照协议
        "一次编辑=一步撤销"的用户可见语义). 终审 F-69 (agent-68): 旧
        via_cmd=False 分支 (edit_model/edit_light/edit_camera 快照直调) 已删
        —— 本批后所有调用点均走命令会话批, 死分支无引用."""
        sb = DraggableSpin(key, self._spin_focused)
        sb.setRange(lo, hi)
        sb.setDecimals(dec)
        sb.setSingleStep(step)
        sb.setValue(float(value))
        self._spins[key] = sb
        e = self.editor

        def edit(active):
            if self._building or e is None:
                return
            # Q-B7-56-1 裁定① + Q-B7-56-2 扫尾: 全部数值行走命令化会话批协议
            # (begin/end 合一步撤销); 旧 edit_model/edit_light/edit_camera
            # 快照直调死分支已删 (终审 F-69, agent-68: 本批后无 via_cmd=False
            # 调用点, 无引用).
            if active:
                self._spin_session_begin(label)
            else:
                self._spin_session_end(label)

        def on_drag(v):
            if self._building or e is None:
                return
            edit(True)          # 先开会话批: 首条命令也进批 (合一步撤销)
            apply(v)

        def on_finish():
            if self._building or e is None:
                return
            edit(False)         # 收口会话批 + _spin_session_end 统一补日志/刷新

        sb.valueChanged.connect(on_drag)
        sb.editingFinished.connect(on_finish)
        self._spin_meta[key] = (apply, label, lo, hi, step, sb, edit)
        lay.addRow(label, sb)
        return sb

    # ---- 底部数值拖拽块 (2026-08-22 用户需求, 通用) ----
    def _spin_focused(self, key):
        """数值行聚焦 -> 底部拖拽块切换到该行 (显示后左键按住左右拖动调值)."""
        meta = self._spin_meta.get(key)
        if meta is None:
            return
        apply_, label, lo, hi, step, sb, edit = meta
        self._dragblock.set_target(label, apply_, lo, hi, step, sb, edit, self)

    def _on_app_focus_changed(self, old, new):
        """焦点离开检查器数值行 -> 隐藏拖拽块 (拖拽进行中不隐藏, 防松手前消失)."""
        if self._dragblock.is_dragging():
            return
        if new is None or not new in self._spins.values():
            self._dragblock.hide_target()

    def _btn_row(self, lay, pairs):
        row = QWidget()
        h = QHBoxLayout(row)
        h.setContentsMargins(0, 0, 0, 0)
        for text, fn in pairs:
            b = QPushButton(text)
            b.clicked.connect(lambda _=False, f=fn: f())
            h.addWidget(b)
        lay.addRow(row)


    def _build_ui_inspector(self, lay, elem):
        """UI 元素检查器 (C3). 每次编辑 = 一个 ui_set 命令 = 一个撤销步骤."""
        typ = elem.ctype
        lay.addRow(QLabel("<b>%s</b>  [%s]" % (elem.name, typ)))

        # 通用字段
        lay.addRow(QLabel("位置/尺寸 (rect)"))
        for i, axis in enumerate(('X', 'Y', 'W', 'H')):
            self._ui_attr_spin(lay, axis, elem.rect[i], -10000, 10000,
                               ('rect', i), step=1, dec=0)
        lay.addRow(QLabel("锚点 (anchor)"))
        for i, axis in enumerate(('AX', 'AY')):
            self._ui_attr_spin(lay, axis, elem.anchor[i], 0, 1,
                               ('anchor', i), step=0.05, dec=2)
        lay.addRow(QLabel("轴心 (pivot)"))
        for i, axis in enumerate(('PX', 'PY')):
            self._ui_attr_spin(lay, axis, elem.pivot[i], 0, 1,
                               ('pivot', i), step=0.05, dec=2)
        self._ui_attr_check(lay, "可见", elem.visible, 'visible')
        self._ui_attr_check(lay, "启用", elem.enabled, 'enabled')
        self._ui_attr_spin(lay, "z_order", elem.z_order, -1000, 1000,
                           ('z_order',), step=1, dec=0)

        # type-specific（常用字段）
        if typ == 'button':
            self._ui_attr_line(lay, "文字", elem.text, 'text')
        elif typ == 'text':
            self._ui_attr_line(lay, "内容", elem.text, 'text')
        elif typ == 'input_field':
            self._ui_attr_line(lay, "文字", elem.text, 'text')
            self._ui_attr_line(lay, "占位", elem.placeholder, 'placeholder')
        elif typ == 'toggle':
            self._ui_attr_check(lay, "勾选", elem.is_on, 'is_on')
            self._ui_attr_line(lay, "标签", elem.label, 'label')
        elif typ == 'slider':
            self._ui_attr_spin(lay, "值", elem.value,
                               elem.min_value, elem.max_value,
                               ('value',), step=0.01, dec=3)
        elif typ == 'progress_bar':
            self._ui_attr_spin(lay, "进度", elem.value, 0, 1,
                               ('value',), step=0.01, dec=3)

        lay.addRow(QLabel(
            "(更多字段请用控制台命令: ui_set name=%s ...)" % elem.name))

    def _ui_attr_spin(self, lay, label, value, lo, hi, path,
                      step=1.0, dec=3):
        sb = QDoubleSpinBox()
        sb.setRange(lo, hi)
        sb.setDecimals(dec)
        sb.setSingleStep(step)
        sb.setValue(float(value))
        sb.editingFinished.connect(
            lambda: self._ui_apply_attr(path, sb.value()))
        lay.addRow(label, sb)

    def _ui_attr_check(self, lay, label, value, attr):
        cb = QCheckBox()
        cb.setChecked(bool(value))
        cb.stateChanged.connect(
            lambda _s: self._ui_apply_attr((attr,), bool(cb.isChecked())))
        lay.addRow(label, cb)

    def _ui_attr_line(self, lay, label, value, attr):
        le = QLineEdit(str(value))
        le.editingFinished.connect(
            lambda: self._ui_apply_attr((attr,), le.text()))
        lay.addRow(label, le)

    def _ui_apply_attr(self, path, value):
        """path 元组：('attr',) 或 ('rect', 0)。构造 ui_set payload。"""
        if self._building:
            return
        name = self._ui_selected_name
        canvas = self._ui_selected_canvas
        if name is None or canvas is None:
            return
        e = self.editor
        if not e.ui.canvases or canvas >= len(e.ui.canvases):
            return
        elem = e.ui.canvases[canvas].root.find(name)
        if elem is None:
            return
        payload = {'name': name, 'canvas': canvas}
        if len(path) == 1:
            payload[path[0]] = value
        else:
            cur = list(getattr(elem, path[0]))
            cur[path[1]] = value
            payload[path[0]] = tuple(cur)
        self._invoke_ui_cmd('ui_set', **payload)

    # ---- 2026-10-19 第1档序3阶段4: Canvas 属性面板 ----
    def _build_canvas_inspector(self, lay, canvas):
        """Canvas 属性：宽高/z_order/类型；world 模式 + world_scale/billboard/target."""
        ci = self._ui_selected_canvas
        lay.addRow(QLabel("<b>Canvas %d</b>  [%s]" % (ci, canvas.canvas_type)))
        self._canvas_spin(lay, "宽度", canvas.width, 1, 10000, 'width',
                          step=1, dec=0)
        self._canvas_spin(lay, "高度", canvas.height, 1, 10000, 'height',
                          step=1, dec=0)
        self._canvas_spin(lay, "z_order", canvas.z_order, -1000, 1000,
                          'z_order', step=1, dec=0)
        type_cb = QComboBox()
        type_cb.addItems(['screen', 'world'])
        type_cb.setCurrentText(canvas.canvas_type)
        type_cb.currentTextChanged.connect(
            lambda v: self._canvas_apply_attr('type', v))
        lay.addRow("类型", type_cb)
        if canvas.canvas_type == 'world':
            self._canvas_spin(lay, "world_scale",
                              getattr(canvas, 'world_scale', 0.01),
                              0.0001, 10.0, 'world_scale',
                              step=0.01, dec=4)
            bb = QCheckBox()
            bb.setChecked(bool(getattr(canvas, 'billboard', True)))
            bb.stateChanged.connect(
                lambda _s: self._canvas_apply_attr(
                    'billboard', bool(bb.isChecked())))
            lay.addRow("面向相机", bb)
            tgt = getattr(canvas, 'target', None)
            tgt_edit = QLineEdit(tgt.name if tgt is not None else '')
            tgt_edit.setPlaceholderText("(空=不绑定物体)")
            tgt_edit.editingFinished.connect(
                lambda: self._canvas_apply_attr('target', tgt_edit.text()))
            lay.addRow("宿主物体", tgt_edit)
        lay.addRow(QLabel(
            "(等价命令: ui_canvas_set canvas=%d ...)" % ci))

    def _canvas_spin(self, lay, label, value, lo, hi, field,
                     step=1.0, dec=3):
        sb = QDoubleSpinBox()
        sb.setRange(lo, hi)
        sb.setDecimals(dec)
        sb.setSingleStep(step)
        sb.setValue(float(value))
        sb.editingFinished.connect(
            lambda: self._canvas_apply_attr(field, sb.value()))
        lay.addRow(label, sb)

    def _canvas_apply_attr(self, field, value):
        if self._building:
            return
        ci = self._ui_selected_canvas
        if ci is None:
            return
        payload = {'canvas': ci, field: value}
        self._invoke_ui_cmd('ui_canvas_set', **payload)

    def _build_obj_inspector(self, lay, m):
        e = self.editor
        name_edit = QLineEdit(m.name)
        name_edit.editingFinished.connect(
            lambda: self._invoke_cmd('object_rename', {'name': m.name, 'new': name_edit.text()})
            if name_edit.text() != m.name else None)   # Q-B7-56-1 裁定①
        lay.addRow("名称", name_edit)
        # ---- Layer / Tag (2026-10-18, 契约 §7) ----
        import kernels.layer_tag as layer_tag
        lay_combo = QComboBox()
        for i in range(32):
            nm = e.layer_name(i)
            lay_combo.addItem("%d: %s" % (i, nm if nm else "(未命名)"), i)
        lay_combo.setCurrentIndex(m.layer)
        # Q-B7-56-2 裁定①: Layer 翻译成 set_layer 命令 (命令体 = commit_model+
        # set_object_layer 同一撤销路径)
        lay_combo.currentIndexChanged.connect(
            lambda i: self._invoke_cmd('set_layer', {'name': m.name, 'layer': i})
            if i != m.layer else None)
        lay.addRow("Layer", lay_combo)

        tag_combo = QComboBox()
        tag_combo.setEditable(True)
        for t in layer_tag.get_tags():
            tag_combo.addItem(t)
        cur_tag = m.tag
        idx = tag_combo.findText(cur_tag)
        if idx >= 0:
            tag_combo.setCurrentIndex(idx)
        else:
            tag_combo.setEditText(cur_tag)

        def _apply_tag():
            val = tag_combo.currentText().strip()
            if val == m.tag:
                return
            ok, reason = layer_tag.validate_tag(val)
            if not ok:
                e._notify("Tag 非法: %s" % reason, (220, 80, 80))
                tag_combo.setEditText(m.tag)
                return
            # Q-B7-56-2 裁定① (P2-2): 注册与设置都翻译成命令 —— register_tag
            # (幂等注册) + set_tag (含同款校验/自动注册); GUI 预校验只保留
            # toast/回退 UX。tag_exists 是读侧, 豁免。
            if not e.tag_exists(val):
                r = self._invoke_cmd('register_tag', {'tag': val},
                                     notify_error=False)
                if isinstance(r, dict) and r.get('error'):
                    e._notify("Tag 注册失败: %s" % r['error'], (220, 80, 80))
                    tag_combo.setEditText(m.tag)
                    return
                # 注册成功后刷新下拉项 (新 tag 出现在列表里)
                if tag_combo.findText(val) < 0:
                    tag_combo.addItem(val)
                    tag_combo.setCurrentIndex(tag_combo.count() - 1)
            self._invoke_cmd('set_tag', {'name': m.name, 'tag': val})

        tag_combo.activated.connect(lambda _i: _apply_tag())
        if tag_combo.lineEdit() is not None:
            tag_combo.lineEdit().editingFinished.connect(_apply_tag)
        lay.addRow("Tag", tag_combo)
        parent_name = m.parent.name if m.parent is not None else "(根)"
        info = "父级: %s" % parent_name
        if m.prefab_ref:
            info += "  [Prefab %s]" % m.prefab_ref[:8]
        lay.addRow(QLabel(info))
        if m.prefab_ref:
            lay.addRow(QLabel("类型: %s" % (m.primitive or '导入网格')))
        # Q-B7-56-2 裁定①: 存网格为资产翻译成 asset_save 命令
        self._btn_row(lay, [("存网格为资产",
                             lambda: self._invoke_cmd('asset_save',
                                                      {'what': 'mesh'}))])

        p = m.position
        lay.addRow(QLabel("位置"))
        for axis, cur in (('X', p.x), ('Y', p.y), ('Z', p.z)):
            # Q-B7-56-1 裁定①: 数值行写位置翻译成 set_transform 命令 (单轴语义
            # 与旧 vec_set 直写逐字一致 —— 命令体就是 vec_set; 数值行会话批把
            # 拖拽/连输合一步撤销)
            self._spin(lay, axis, cur, -1000, 1000, 'pos.' + axis,
                       lambda v, a=axis: self._cmd_vec_set(m, 'model',
                                                           'position', a, v))
        r = m.rotation
        lay.addRow(QLabel("旋转 (°)"))
        for axis, cur in (('X', r.x), ('Y', r.y), ('Z', r.z)):
            # 2026-08-27 修复: 原写 setattr(m.rotation, 'X', ...) —— rotation 是
            # Point3D **namedtuple**, setattr 直接抛 AttributeError (且键名大小写
            # 也不对), 异常在 Qt 信号回调里被吞 -> 旋转三行从来改不动值.
            # Q-B7-56-1 裁定①: 旋转行翻译成 set_transform 命令 (rx/ry/rz **度制**,
            # 命令层内部转弧度 + vec_set 整体重建, 与命令行输 set_transform 同义;
            # 这里不再预转 radians —— 命令层换算)
            self._spin(lay, axis, math.degrees(cur), -360, 360, 'rot.' + axis,
                       lambda v, a=axis: self._cmd_vec_set(m, 'model',
                                                           'rotation', a, v),
                       step=1.0)
        s = m.scale
        lay.addRow(QLabel("缩放"))
        for i, axis in enumerate(('X', 'Y', 'Z')):
            # Q-B7-56-2 裁定①: 缩放行翻译成 set_transform sx/sy/sz 命令
            self._spin(lay, axis, s[i], 0.01, 100, 'scale.' + axis,
                       lambda v, a=axis: self._invoke_cmd(
                           'set_transform', {'name': m.name,
                                             's' + a.lower(): v},
                           quiet=True),
                       step=0.1)
        # 材质 (M23: 材质在 renderer.material, 共享引用语义)
        if e.materials:
            combo = QComboBox()
            cur_mat = m.renderer.material
            for i, mat in enumerate(e.materials):
                combo.addItem("%s%s" % (mat.name, '  √' if mat is cur_mat else ''), i)
            combo.setCurrentIndex(max(0, next((i for i, x in enumerate(e.materials)
                                              if x is cur_mat), 0)))
            # Q-B7-56-2 裁定①: 换材质翻译成 set_material 命令 (共享引用语义)
            combo.currentIndexChanged.connect(
                lambda i: self._invoke_cmd('set_material',
                                           {'name': m.name, 'index': i})
                if i >= 0 else None)
            lay.addRow("材质", combo)
        self._btn_row(lay, [
            ("＋新建材质", lambda: self._invoke_cmd('material_new',
                                               {'name': m.name})),
            ("存材质为资产", lambda: self._invoke_cmd('asset_save',
                                                  {'what': 'material'}))])
        # Q-B7-56-2 裁定①: 饱和度行翻译成 set_saturation 命令 (会话批协议)
        self._spin(lay, "饱和度", m.saturation, 0, 2, 'sat',
                   lambda v: self._invoke_cmd('set_saturation',
                                              {'name': m.name, 'value': v},
                                              quiet=True),
                   step=0.05)
        # 碰撞 (B1-修复_b 2026-08-30 用户二轮: 按钮措辞陷阱 —— 旧文"碰撞器: 禁用"
        # 出现在**已启用**状态, 状态式误读会把"点此禁用"读成"当前禁用" -> 用户点
        # 一次以为启用, 实际关掉碰撞器; 桥路径下不建体=>浮空 (配合自由积分修复).
        # 改为 状态+动作显式: "启用中(点按禁用)" / "已禁用(点按启用)"。
        if m.collider is not None:
            # Q-B7-56-2 裁定①: 碰撞器开关翻译成 collider 命令 (缺 on = 切换)
            self._btn_row(lay, [("碰撞器: 启用中(点按禁用)" if m.collider.enabled
                                 else "碰撞器: 已禁用(点按启用)",
                                 lambda: self._invoke_cmd('collider',
                                                          {'name': m.name}))])
            # B1 (2026-08-30) 用户新需求: 接触材质 —— 阿蒙东-库仑摩擦 f=μN,
            # 弹性=回弹系数, 滚动摩擦=滚动阻力. B1-P1(2026-08-30) 用户实测
            # "摩擦选项有两个" -> 单组显示: 有刚体只显示刚体组 (动态体用 rb 值),
            # 无刚体只显示碰撞组 (静态/运动学用 col 值) —— 数据仍双通道.
            if m.rigidbody is None:
                # Q-B7-56-2 裁定①: 接触材质行翻译成 collider 命令 (会话批协议)
                self._spin(lay, "摩擦系数", m.collider.friction, 0, 3, 'col.fric',
                           lambda v: self._invoke_cmd(
                               'collider', {'name': m.name, 'friction': v},
                               quiet=True), step=0.05)
                self._spin(lay, "弹性", m.collider.restitution, 0, 1, 'col.rest',
                           lambda v: self._invoke_cmd(
                               'collider', {'name': m.name, 'restitution': v},
                               quiet=True), step=0.05)
                self._spin(lay, "滚动摩擦", m.collider.rolling_friction, 0, 3, 'col.roll',
                           lambda v: self._invoke_cmd(
                               'collider', {'name': m.name, 'rolling_friction': v},
                               quiet=True), step=0.05)
            # 2026-10-18 阶段1档序17 Trigger: is_trigger 开关（路线见路线图 §2.7）
            # 语义: is_trigger=True 时物理层建 sensor 体（可重叠穿过, 不产生接触力）,
            # 事件走 on_trigger_enter/exit/stay（双方任一方 trigger 即走 trigger 路径）.
            # 按钮措辞: 状态+动作显式（"触发器: 开/关"），避免同 toggle_collider 旧措辞陷阱.
            # Q-B7-56-2 裁定①: 触发器翻译成 collider is_trigger 命令
            self._btn_row(lay, [
                ("触发器: 开 (点按关闭)" if getattr(m.collider, 'is_trigger', False)
                 else "触发器: 关 (点按开启)",
                 lambda: self._invoke_cmd(
                     'collider', {'name': m.name,
                                  'is_trigger': not getattr(m.collider,
                                                            'is_trigger',
                                                            False)}))])
        # 刚体
        if m.rigidbody is not None:
            # Q-B7-56-2 裁定①: 刚体重力/移除翻译成 rigidbody 命令
            txt = "刚体: 受重力" if m.rigidbody.use_gravity else "刚体: 不受重力"
            self._btn_row(lay, [
                (txt, lambda: self._invoke_cmd('rigidbody',
                                               {'name': m.name,
                                                'action': 'gravity'})),
                ("移除刚体", lambda: self._invoke_cmd('rigidbody',
                                                  {'name': m.name,
                                                   'action': 'remove'}))])
            # B1: 动态体接触材质 (桥透传; pair 值 = 两体几何平均); 滚动摩擦
            # 0=关闭; 桥内衰减系数 f = max(0, 1-μ·rolling·K·dt)
            # Q-B7-56-2 裁定①: 刚体接触材质行翻译成 rigidbody action=set 命令
            self._spin(lay, "摩擦系数", m.rigidbody.friction, 0, 3, 'rb.fric',
                       lambda v: self._invoke_cmd(
                           'rigidbody', {'name': m.name, 'action': 'set',
                                         'friction': v}, quiet=True),
                       step=0.05)
            self._spin(lay, "弹性", m.rigidbody.restitution, 0, 1, 'rb.rest',
                       lambda v: self._invoke_cmd(
                           'rigidbody', {'name': m.name, 'action': 'set',
                                         'restitution': v}, quiet=True),
                       step=0.05)
            self._spin(lay, "滚动摩擦", m.rigidbody.rolling_friction, 0, 3, 'rb.roll',
                       lambda v: self._invoke_cmd(
                           'rigidbody', {'name': m.name, 'action': 'set',
                                         'rolling_friction': v}, quiet=True),
                       step=0.05)
        else:
            self._btn_row(lay, [("＋加刚体 (受重力)",
                                 lambda: self._invoke_cmd(
                                     'rigidbody', {'name': m.name,
                                                   'action': 'add'}))])
        # 音频 (组件属性名 = audio_source, 与旧版GUI 一致)
        if m.audio_source is not None:
            au = m.audio_source
            clip_edit = QLineEdit(au.clip or "")
            clip_edit.setPlaceholderText("音频文件路径 (wav/ogg)")
            # Q-B7-56-2 裁定①: 音频组件操作翻译成 audio / set_audio_3d 命令
            clip_edit.editingFinished.connect(
                lambda: self._invoke_cmd('audio', {'name': m.name,
                                                   'action': 'clip',
                                                   'clip': clip_edit.text()}))
            lay.addRow("音频", clip_edit)
            self._btn_row(lay, [("循环: 开" if au.loop else "循环: 关",
                                 lambda: self._invoke_cmd('audio',
                                                          {'name': m.name,
                                                           'action': 'loop'})),
                                ("→播放" if not au.playing else "■停止",
                                 lambda: self._invoke_cmd('audio',
                                                          {'name': m.name,
                                                           'action': 'play'})),
                                ("移除", lambda: self._invoke_cmd(
                                    'audio', {'name': m.name,
                                              'action': 'remove'}))])
            self._spin(lay, "音量", au.volume, 0, 1, 'au.vol',
                       lambda v: self._invoke_cmd('audio', {'name': m.name,
                                                            'action': 'volume',
                                                            'value': v},
                                                  quiet=True),
                       step=0.05)
            # 2026-10-18 3D 音频 (契约 §9): 类别决定空间化, music 强制 2D
            cat_combo = QComboBox()
            for _label, _val in (("音效", "sfx"), ("背景音乐", "music"), ("人声", "voice")):
                cat_combo.addItem(_label, _val)
            _ci = cat_combo.findData(au.category)
            cat_combo.setCurrentIndex(max(0, _ci))

            def _on_cat(_i, _c=cat_combo, _a=au, _m=m):
                _v = _c.itemData(_i)
                if not _v or _v == _a.category:
                    return
                # Q-B7-56-2 裁定①: 类别翻译成 set_audio_3d 命令 (同款校验+
                # 一步撤销; 撤销标签为命令层 "设置音频 3D")
                self._invoke_cmd('set_audio_3d', {'name': _m.name,
                                                  'category': _v})
                self._refresh_all()

            cat_combo.currentIndexChanged.connect(_on_cat)
            lay.addRow("类别", cat_combo)
            if au.is_spatial():
                # Q-B7-56-2 裁定①: 3D 距离行翻译成 set_audio_3d 命令。
                # GUI 预判 min<max 保留旧 toast UX (不合法不发命令); 合法值由
                # 命令层再校验一次 (组件 setter 静默回退 → 命令层显式报错)。
                def _min_set(v):
                    if v >= au.max_distance:
                        e._notify("最小距离必须小于最大距离", (220, 80, 80))
                        self._refresh_all()
                        return
                    self._invoke_cmd('set_audio_3d',
                                     {'name': m.name, 'min_distance': v},
                                     quiet=True)

                def _max_set(v):
                    if v <= au.min_distance:
                        e._notify("最大距离必须大于最小距离", (220, 80, 80))
                        self._refresh_all()
                        return
                    self._invoke_cmd('set_audio_3d',
                                     {'name': m.name, 'max_distance': v},
                                     quiet=True)

                self._spin(lay, "最小距离", au.min_distance, 0.01, 10000, 'au.min',
                           _min_set, step=0.1)
                self._spin(lay, "最大距离", au.max_distance, 0.01, 10000, 'au.max',
                           _max_set, step=1.0)
                self._spin(lay, "衰减强度", au.rolloff, 0.01, 10, 'au.roll',
                           lambda v: self._invoke_cmd(
                               'set_audio_3d', {'name': m.name, 'rolloff': v},
                               quiet=True),
                           step=0.1)
        else:
            self._btn_row(lay, [("＋加音频源",
                                 lambda: self._invoke_cmd(
                                     'audio', {'name': m.name,
                                               'action': 'add'}))])
        # 动画
        if m.animator is not None:
            # Q-B7-56-2 裁定①: 动画组件操作翻译成 animator 命令
            an = m.animator
            self._btn_row(lay, [("循环: 开" if an.loop else "循环: 关",
                                 lambda: self._invoke_cmd('animator',
                                                          {'name': m.name,
                                                           'action': 'loop'})),
                                ("→播放" if not an.playing else "■停止",
                                 lambda: self._invoke_cmd('animator',
                                                          {'name': m.name,
                                                           'action': 'play'})),
                                ("移除", lambda: self._invoke_cmd(
                                    'animator', {'name': m.name,
                                                 'action': 'remove'}))])
            for clip in (an.clips or []):
                self._btn_row(lay, [("→ " + clip if an.current == clip else clip,
                                     lambda c=clip: self._invoke_cmd(
                                         'animator', {'name': m.name,
                                                      'action': 'clip',
                                                      'clip': c}))])
        else:
            self._btn_row(lay, [("＋加动画组件",
                                 lambda: self._invoke_cmd(
                                     'animator', {'name': m.name,
                                                  'action': 'add'}))])
        # 脚本
        if m.scripts:
            for i, sc in enumerate(m.scripts):
                row = QWidget()
                h = QHBoxLayout(row)
                h.setContentsMargins(0, 0, 0, 0)
                h.addWidget(QLabel(sc.script_id))
                b = QPushButton("×")
                b.setFixedWidth(28)
                # Q-B7-56-2 裁定①: 移除脚本翻译成 script_remove 命令
                b.clicked.connect(lambda _=False, i=i: self._invoke_cmd(
                    'script_remove', {'name': m.name, 'index': i}))
                h.addWidget(b)
                lay.addRow("脚本", row)
                try:
                    from script.scripts import get_script
                    params = get_script(sc.script_id).params
                    # Q-B7-56-2 附带修正: params 既可能是 dict {key: 默认值规格}
                    # (旧约定) 也可能是 ((key,label,default,...),...) 元组表
                    # (scripts.py 现行约定) —— 旧代码一律 .items() 对元组表抛
                    # AttributeError 被 except 吞掉, 脚本参数行从未渲染过。
                    if isinstance(params, dict):
                        pitems = [(k, d.get('default', 0.0))
                                  for k, d in params.items()]
                    else:
                        pitems = [(p[0], p[2] if len(p) > 2 else 0.0)
                                  for p in params]
                    for pname, dflt in pitems:
                        val = sc.script_vars.get(pname, dflt)
                        # Q-B7-56-2 裁定①: 脚本参数行翻译成 script_var 命令
                        self._spin(lay, pname, val, -1e6, 1e6,
                                   'svar.%d.%s' % (i, pname),
                                   lambda v, i=i, p=pname: self._invoke_cmd(
                                       'script_var', {'name': m.name,
                                                      'index': i, 'key': p,
                                                      'value': v},
                                       quiet=True),
                                   step=0.1)
                except Exception:
                    pass
        # 可挂脚本下拉 (2026-08-22 修复: script_options() 返回 (id,name) 元组,
        # 旧代码当字符串 addItem 会 TypeError 被吞 -> 下拉从未显示; 已挂脚本
        # 也未过滤, 一并修: 过滤+addItem(name, id))
        try:
            from script.scripts import script_options
            have = {sc.script_id for sc in m.scripts}
            opts = [(sid, nm) for sid, nm in script_options()
                    if sid is not None and sid not in have]
            if opts:
                combo = QComboBox()
                combo.addItem("＋ 添加脚本…", None)
                for sid, nm in opts:
                    combo.addItem(nm, sid)
                # Q-B7-56-2 裁定①: 添加脚本翻译成 script_add 命令
                combo.currentIndexChanged.connect(
                    lambda i: self._invoke_cmd('script_add',
                                               {'sid': combo.itemData(i),
                                                'target': m.name})
                    if combo.itemData(i) else None)
                lay.addRow(QLabel("脚本"), combo)
        except Exception:
            pass
        if m.prefab_ref:
            # 2026-08-27 修复: _btn_row 的回调是无参调用 f(), 直接挂
            # e.unlink_prefab (签名 unlink_prefab(self, m)) 点一下就 TypeError
            # 被 Qt 吞掉 —— 按钮从来没断开过 Prefab 连接.
            # Q-B7-56-2 裁定①: 断开 Prefab 翻译成 prefab_unlink 命令
            self._btn_row(lay, [("与 Prefab 断开连接",
                                 lambda: self._invoke_cmd('prefab_unlink',
                                                          {'name': m.name}))])

    def _build_light_inspector(self, lay, l):
        e = self.editor
        name_edit = QLineEdit(l.name)
        name_edit.editingFinished.connect(
            lambda: self._invoke_cmd('object_rename', {'name': l.name, 'new': name_edit.text()})
            if name_edit.text() != l.name else None)   # Q-B7-56-1 裁定①
        lay.addRow("名称", name_edit)
        # Q-B7-56-2 裁定①: 光源按钮翻译成 light_set 命令 (同款一步撤销)
        self._btn_row(lay, [("阴影: 开" if l.shadow else "阴影: 关",
                             lambda: self._invoke_cmd('light_set',
                                                      {'name': l.name,
                                                       'shadow': not l.shadow}))])
        if l.kind == 'directional':
            # 模式: M29 全场景平行光 'full' | 光束 'beam' (截面平行光)
            self._btn_row(lay, [("模式: 全场景" if l.mode != 'beam' else "模式: 光束",
                                 lambda: self._invoke_cmd(
                                     'light_set', {'name': l.name,
                                                   'mode': 'beam' if l.mode != 'beam'
                                                   else 'full'}))])
            if l.mode == 'beam':
                self._btn_row(lay, [("截面: 圆" if l.shape == 'circle' else "截面: 矩形",
                                     lambda: self._invoke_cmd(
                                         'light_set', {'name': l.name,
                                                       'shape': 'circle' if l.shape != 'circle'
                                                       else 'rect'}))])
                # Q-B7-56-2 裁定①: 光源数值行翻译成 light_set 命令 (会话批协议)
                self._spin(lay, "尺寸", l.size, 0.05, 50, 'li.size',
                           lambda v: self._invoke_cmd('light_set',
                                                      {'name': l.name,
                                                       'size': v},
                                                      quiet=True),
                           step=0.05)
        self._spin(lay, "强度", l.intensity, 0, 10, 'li.intensity',
                   lambda v: self._invoke_cmd('light_set', {'name': l.name,
                                                            'intensity': v},
                                              quiet=True),
                   step=0.05)
        self._spin(lay, "颜色 R", l.color[0], 0, 1, 'li.cR',
                   lambda v: self._invoke_cmd('light_set', {'name': l.name,
                                                            'r': v},
                                              quiet=True),
                   step=0.01)
        self._spin(lay, "颜色 G", l.color[1], 0, 1, 'li.cG',
                   lambda v: self._invoke_cmd('light_set', {'name': l.name,
                                                            'g': v},
                                              quiet=True),
                   step=0.01)
        self._spin(lay, "颜色 B", l.color[2], 0, 1, 'li.cB',
                   lambda v: self._invoke_cmd('light_set', {'name': l.name,
                                                            'b': v},
                                              quiet=True),
                   step=0.01)
        if l.kind == 'directional':
            # M30: 平行光三角度存度制 (azimuth/elevation/roll), 直接读写不转换
            # Q-B7-56-2 裁定①: 三角度行度制直传 (命令层 light_set 同为度制直写)
            self._spin(lay, "朝向", l.azimuth, -360, 360, 'li.az',
                       lambda v: self._invoke_cmd('light_set',
                                                  {'name': l.name,
                                                   'azimuth': v},
                                                  quiet=True),
                       step=1.0)
            self._spin(lay, "俯仰", l.elevation, -360, 360, 'li.el',
                       lambda v: self._invoke_cmd('light_set',
                                                  {'name': l.name,
                                                   'elevation': v},
                                                  quiet=True),
                       step=1.0)
            self._spin(lay, "倾斜", l.roll, -180, 180, 'li.roll',
                       lambda v: self._invoke_cmd('light_set',
                                                  {'name': l.name, 'roll': v},
                                                  quiet=True),
                       step=1.0)
        p = l.position
        for axis, cur in (('X', p.x), ('Y', p.y), ('Z', p.z)):
            # Q-B7-56-1 裁定①: 光源位置行翻译成 light_set 命令
            self._spin(lay, "位置 " + axis, cur, -1000, 1000, 'li.p' + axis,
                       lambda v, a=axis: self._cmd_vec_set(l, 'light',
                                                           'position', a, v))

    def _build_camera_inspector(self, lay, c):
        e = self.editor
        name_edit = QLineEdit(c.name)
        name_edit.editingFinished.connect(
            lambda: self._invoke_cmd('object_rename', {'name': c.name, 'new': name_edit.text()})
            if name_edit.text() != c.name else None)   # Q-B7-56-1 裁定①
        lay.addRow("名称", name_edit)
        p = c.position
        for axis, cur in (('X', p.x), ('Y', p.y), ('Z', p.z)):
            # Q-B7-56-1 裁定①: 摄像机位置行翻译成 camera_set 命令
            self._spin(lay, "位置 " + axis, cur, -1000, 1000, 'cam.p' + axis,
                       lambda v, a=axis: self._cmd_vec_set(c, 'camera',
                                                           'position', a, v))
        # M41: 摄像机朝向存度制 (yaw/pitch/roll 环绕), 直接读写不转换
        # Q-B7-56-2 裁定①: 相机角度/FOV 行翻译成 camera_set 命令 (度制直传)
        self._spin(lay, "朝向", c.yaw, -360, 360, 'cam.yaw',
                   lambda v: self._invoke_cmd('camera_set', {'name': c.name,
                                                             'yaw': v},
                                              quiet=True),
                   step=1.0)
        self._spin(lay, "俯仰", c.pitch, -360, 360, 'cam.pitch',
                   lambda v: self._invoke_cmd('camera_set', {'name': c.name,
                                                             'pitch': v},
                                              quiet=True),
                   step=1.0)
        self._spin(lay, "倾斜", c.roll, -180, 180, 'cam.roll',
                   lambda v: self._invoke_cmd('camera_set', {'name': c.name,
                                                             'roll': v},
                                              quiet=True),
                   step=1.0)
        self._spin(lay, "FOV", c.fov, 20, 120, 'cam.fov',
                   lambda v: self._invoke_cmd('camera_set', {'name': c.name,
                                                             'fov': v},
                                              quiet=True),
                   step=1.0)
        # fov_locked 语义 (engine.py): True=锁定玩家调整. 旧代码 "玩家可调" if
        # c.fov_locked 布尔颠倒 (默认 True 却显示"玩家可调"); LoomGUI 是 not
        # Q-B7-56-2 裁定①: fov 锁定/俯仰限制按钮翻译成 camera_set 命令
        self._btn_row(lay, [("玩家可调" if not c.fov_locked else "玩家锁定",
                             lambda: self._invoke_cmd('camera_set',
                                                      {'name': c.name,
                                                       'fov_lock': not c.fov_locked}))])
        self._btn_row(lay, [("俯仰限制: 已启用" if c.pitch_lock else "俯仰限制: 未启用",
                             lambda: self._invoke_cmd('camera_set',
                                                      {'name': c.name,
                                                       'pitch_lock': not c.pitch_lock}))])
        if c.pitch_lock:
            self._spin(lay, "最低俯角", c.pitch_min, -180, 180, 'cam.pmin',
                       lambda v: self._invoke_cmd('camera_set',
                                                  {'name': c.name,
                                                   'pitch_min': v},
                                                  quiet=True),
                       step=1.0)
            self._spin(lay, "最高仰角", c.pitch_max, -180, 180, 'cam.pmax',
                       lambda v: self._invoke_cmd('camera_set',
                                                  {'name': c.name,
                                                   'pitch_max': v},
                                                  quiet=True),
                       step=1.0)
        # Q-B7-56-2 裁定①: 预览/激活翻译成 camera_preview / camera_active 命令
        # (exit_preview 走 camera_preview off=true, 不新增命令)
        if e.preview_camera is c:
            self._btn_row(lay, [("退出预览",
                                 lambda: self._invoke_cmd('camera_preview',
                                                          {'off': True}))])
        else:
            self._btn_row(lay, [("用此相机预览",
                                 lambda: self._invoke_cmd('camera_preview',
                                                          {'name': c.name}))])
        # active_camera 在 editor 里存 guid (set_active_camera 写 cam.guid) 非相机
        # 对象 —— 旧代码 e.active_camera is c 永远 False, 点击后按钮文字永不刷新
        # (用户实测 2026-08-22). 与旧版GUI 同款 guid 比较.
        is_active = (e.active_camera == c.guid)
        self._btn_row(lay, [("取消激活" if is_active else "设为激活相机",
                             lambda: self._invoke_cmd(
                                 'camera_active', {} if is_active
                                 else {'name': c.name}))])

    # ---------------- 300ms 轮询刷新 ----------------
    def _refresh_all(self):
        e = self.editor
        if e is None:
            return
        self._scene_edit.blockSignals(True)
        self._scene_edit.setText(e.scene_name)
        self._scene_edit.blockSignals(False)
        self._prefab_edit.blockSignals(True)
        self._prefab_edit.setText(e.prefab_name)
        self._prefab_edit.blockSignals(False)
        self._act_play.setText("■停止" if e.is_playing else "→播放")
        self._act_move.setChecked(e.gizmo_mode == 'translate')
        self._act_rotate.setChecked(e.gizmo_mode == 'rotate')
        dig = self._res_digest(e)
        if dig != self._res_last_digest:
            self._res_last_digest = dig
            self._rebuild_resources()
        # 资源选中同步 -> 预览条
        cur_item = self.resources.currentItem()
        cur = self._res_item_data(cur_item)
        if cur != self._res_selected:
            self._res_selected = cur
            if cur is not None:
                it = e._find_asset(tuple(cur))
                if it is not None:
                    data = e._asset_data(it)
                    nm = data.get('name', '') if isinstance(data, dict) else ''
                    self._preview_label.setText("%s  %s" % (cur[1], nm))
                    self._preview.setVisible(True)
            else:
                self._preview.setVisible(False)
        # 检查器: 目标变化才重建; 同目标只同步 spinbox 值
        key = self._insp_key_of()
        if key != self._insp_key:
            self._insp_key = key
            self._insp_last_digest = None
            self._rebuild_inspector()
        else:
            # 组件状态变化 (音频/动画播放中/循环) 且焦点不在检查器输入控件时重建,
            # 按钮文本才能实时反映 (播放中/循环: 开)
            dig = self._insp_component_digest(key)
            if dig is not None and dig != self._insp_last_digest:
                # 2026-08-22 修复: last 更新与 rebuild 必须同进退 —— 原顺序先更新
                # last 再检 focus, 焦点在输入控件时 rebuild 被挡但 last 已变,
                # 之后所有 tick 都视为"无变化" → 面板永久卡旧状态 (用户实测
                # 按钮文字/截面行不刷新、旧按钮残留)
                if not self._insp_input_focused():
                    self._insp_last_digest = dig
                    self._rebuild_inspector()
            else:
                self._sync_inspector_values()
        # 层级树: 内容摘要变化才重建 (避免 300ms 轮询反复重建丢展开状态)
        dig = self._hier_digest(e)
        if dig != self._hier_last_digest:
            self._hier_last_digest = dig
            if not (QGuiApplication.mouseButtons() & Qt.MouseButton.LeftButton) \
                    and not self._hier_pressed:
                self._rebuild_hierarchy()
        # 状态栏
        self._refresh_status()
        # toast 消息 (editor.msg_color 是 RGB 元组, 转 #rrggbb)
        self._msg_label.setText(e.msg or "")
        try:
            c = e.msg_color
            self._msg_label.setStyleSheet("color:#%02x%02x%02x;" % c)
        except Exception:
            self._msg_label.setStyleSheet("color:#666;")

    def _insp_input_focused(self):
        """焦点是否在检查器表单输入控件 (正在输入值, rebuild 应打断避免丢输入).
        2026-08-22 修: 原实现任何 QLineEdit 都挡 —— 场景名/预制名框(工具栏)
        是窗口默认驻扎焦点, 用户从没碰过输入框就点检查器按钮时, 焦点恒在场景名
        框 → 点击后 rebuild 永远被挡 → 按钮文字/状态永不刷新 (用户实测
        "设为激活相机"按钮不变的真凶之一; 程序化 click 也不抢焦点同路径).
        现在只挡检查器表单内的 QLineEdit (名称/音频路径框) + spinbox + combo."""
        fw = QApplication.focusWidget()
        if isinstance(fw, (QDoubleSpinBox, QComboBox)):
            return True
        if isinstance(fw, QLineEdit):
            return self.inspector is not None and fw in self._insp_line_edits()
        return False

    _INSP_LE_CACHE = None

    def _insp_line_edits(self):
        if self._INSP_LE_CACHE is None:
            self._INSP_LE_CACHE = set(self.inspector.findChildren(QLineEdit))
        return self._INSP_LE_CACHE

    def _insp_component_digest(self, key):
        """检查器组件状态摘要, 变化时重建检查器.
        2026-08-22 修复: 原实现光源/相机一律返回 None → 检查器永不重建,
        阴影/模式/截面按钮点击后文字不刷新 (用户实测); 现按目标类型分派.
        obj: 音频/动画播放中/循环/当前剪辑; light: 阴影/模式/截面/尺寸;
        camera: FOV/预览/激活 状态."""
        if key != self._insp_key:
            return None
        e = self.editor
        if e is None:
            return None
        t = self._insp_target()
        if t is None:
            return None
        kind, obj = t
        parts = []
        if kind == 'light':
            parts.append(('shadow', getattr(obj, 'shadow', False)))
            parts.append(('mode', getattr(obj, 'mode', 'full')))
            parts.append(('shape', getattr(obj, 'shape', 'circle')))
            parts.append(('size', round(float(getattr(obj, 'size', 0.0)), 4)))
            return repr(parts)
        if kind == 'camera':
            parts.append(('fov', round(float(getattr(obj, 'fov', 0.0)), 4)))
            parts.append(('preview', getattr(e, 'preview_camera', None) is obj))
            # active: editor 存 guid 非对象 (is obj 永远 False, 同按钮文字 bug);
            # fov_lock/pitch_lock: "玩家可调""俯仰限制"按钮文字 + min/max 行显隐
            parts.append(('active', getattr(e, 'active_camera', None)
                          == getattr(obj, 'guid', None)))
            parts.append(('fov_lock', bool(getattr(obj, 'fov_locked', False))))
            parts.append(('pitch_lock', bool(getattr(obj, 'pitch_lock', False))))
            return repr(parts)
        # obj 类型: 音频/动画动态状态
        au = getattr(obj, 'audio_source', None)
        if au is not None:
            parts.append(('au', getattr(au, 'playing', False),
                          getattr(au, 'loop', False), getattr(au, 'volume', 0)))
        an = getattr(obj, 'animator', None)
        if an is not None:
            parts.append(('an', getattr(an, 'playing', False),
                          getattr(an, 'loop', False), getattr(an, 'current', None)))
        # 2026-08-22 系统性排查: 补点击后状态变化的字段 —— 碰撞器启用/刚体
        # (＋加刚体后应自动换成"移除刚体"行)/脚本行/×/Prefab 断开按钮消失/
        # 材质库 (＋新建材质后下拉刷新), 否则这些控件点击后检查器永不重建
        col = getattr(obj, 'collider', None)
        if col is not None:
            parts.append(('col', bool(getattr(col, 'enabled', False))))
        rb = getattr(obj, 'rigidbody', None)
        if rb is not None:
            parts.append(('rb', bool(getattr(rb, 'use_gravity', False))))
        if getattr(obj, 'scripts', None):
            parts.append(('scr', [sc.script_id for sc in obj.scripts]))
        if getattr(obj, 'prefab_ref', None):
            parts.append(('pref', getattr(obj, 'prefab_ref', None)))
        mats = getattr(e, 'materials', None)
        if mats is not None:
            parts.append(('mats', [getattr(m, 'name', '') for m in mats]))
        return repr(parts)

    def _res_digest(self, e):
        """资源列表内容摘要 (资产 (type,key) 序列), 变化才重建列表."""
        try:
            return [(it.get('type'), it.get('key')) for it in e._scan_assets()]
        except Exception:
            return []

    def _hier_digest(self, e):
        """层级树内容摘要 (模型/光源/摄像机 + 选中态), 变化才重建树."""
        return ([(id(m), m.name, m.visible, id(m.parent) if m.parent else None)
                 for m in e.models]
                + [(id(l), l.name) for l in e.lights]
                # 2026-08-22: 补 fov_locked —— 层级相机行 [锁/开] 标识, 检查器
                # "玩家可调"点击后层级树也要刷新 (旧 digest 只有 (id,name) 永不重建)
                + [(id(c), c.name, c.fov_locked) for c in e.cameras]
                + [e.selected_index, e.selected_light_index, e.selected_camera_index])

    def _sync_inspector_values(self, force=False):
        """同目标时同步 spinbox 当前值 (gizmo 拖拽等外部改动).
        spinbox 正在输入 (有焦点) 时跳过, 防值被写回干扰输入;
        force=True 时忽略焦点 (拖拽块按下前同步, 保证拖动基准 = 模型值)."""
        e = self.editor
        if e is None:
            return
        if not force and isinstance(QApplication.focusWidget(), QDoubleSpinBox):
            return
        t = self._insp_target()
        if t is None:
            return
        kind, obj = t
        for key, sb in self._spins.items():
            try:
                if kind == 'obj':
                    if key.startswith('pos.'):
                        v = getattr(obj.position, key[4].lower())
                    elif key.startswith('rot.'):
                        v = math.degrees(getattr(obj.rotation, key[4].lower()))
                    elif key.startswith('scale.'):
                        v = obj.scale[{'X': 0, 'Y': 1, 'Z': 2}[key[4]]]
                    elif key == 'sat':
                        v = obj.saturation
                    elif key.startswith('au.vol') and obj.audio_source is not None:
                        v = obj.audio_source.volume
                    elif key.startswith('svar.'):
                        _, i, pname = key.split('.', 2)
                        sc = obj.scripts[int(i)]
                        v = sc.script_vars.get(pname, 0.0)
                    elif key == 'col.fric':
                        v = obj.collider.friction
                    elif key == 'col.rest':
                        v = obj.collider.restitution
                    elif key == 'col.roll':
                        v = obj.collider.rolling_friction
                    elif key == 'rb.fric' and obj.rigidbody is not None:
                        v = obj.rigidbody.friction
                    elif key == 'rb.rest' and obj.rigidbody is not None:
                        v = obj.rigidbody.restitution
                    elif key == 'rb.roll' and obj.rigidbody is not None:
                        v = obj.rigidbody.rolling_friction
                    else:
                        continue
                elif kind == 'light':
                    if key.startswith('li.c'):
                        v = {'R': 0, 'G': 1, 'B': 2}[key[3]]
                        v = obj.color[v]
                    elif key == 'li.intensity':
                        v = obj.intensity
                    elif key == 'li.size':
                        v = obj.size
                    elif key == 'li.az':
                        v = obj.azimuth
                    elif key == 'li.el':
                        v = obj.elevation
                    elif key == 'li.roll':
                        v = obj.roll
                    elif key.startswith('li.p'):
                        v = getattr(obj.position, key[4].lower())
                    else:
                        continue
                else:
                    if key.startswith('cam.p'):
                        v = getattr(obj.position, key[5].lower())
                    elif key == 'cam.yaw':
                        v = obj.yaw
                    elif key == 'cam.pitch':
                        v = obj.pitch
                    elif key == 'cam.roll':
                        v = obj.roll
                    elif key == 'cam.fov':
                        v = obj.fov
                    elif key == 'cam.pmin':
                        v = obj.pitch_min
                    elif key == 'cam.pmax':
                        v = obj.pitch_max
                    else:
                        continue
                if abs(sb.value() - float(v)) > 1e-4:
                    sb.blockSignals(True)
                    sb.setValue(float(v))
                    sb.blockSignals(False)
            except Exception:
                pass

    def _refresh_status(self):
        e = self.editor
        if e is None:
            return
        m = e._selected()
        if m is not None:
            sel = m.name
        elif e._selected_light() is not None:
            sel = "光源: " + e._selected_light().name
        elif e._selected_camera() is not None:
            sel = "相机: " + e._selected_camera().name
        else:
            sel = "无"
        # TPS 实测 (分离批5, 用户需求: FPS 旁直读逻辑时钟走没走/停没停)
        tps = e.get_tps() if e.is_playing else 0.0
        tps_txt = ("TPS: %.1f" % tps) if e.is_playing else "TPS: —"
        if e.is_playing and getattr(e, '_logic_paused', False):
            tps_txt = "TPS: 已暂停 (F10 步进)"
        txt = ("FPS: %d | %s | 对象: %d | 光源: %d | 摄像机: %d | 选中: %s | "
               "相机距离: %.1f%s" % (e.fps, tps_txt, len(e.models), len(e.lights),
                                   len(e.cameras), sel, e.camera_distance,
                                   " | → 播放中" if e.is_playing else ""))
        # ★B4c (2026-10-16): 物理线程建失败 (系统极限工况) 醒目提示
        if getattr(e, '_phys_pipe_sysfail', False):
            txt = ("!!! 物理线程创建失败 (系统资源耗尽?) — 立即保存并关闭软件 !!! "
                   "| " + txt)
            self._msg_label.setText("⚠️ 物理线程创建失败，请立即保存并关闭软件")
            self._msg_label.setStyleSheet("color:#d33;font-weight:bold;")
            self.statusBar().showMessage(txt)
            # 一次性弹窗 (避免轮询反复弹)
            if not getattr(self, '_phys_sysfail_notified', False):
                self._phys_sysfail_notified = True
                from PySide6.QtWidgets import QMessageBox
                QMessageBox.critical(
                    self, "系统资源告警",
                    "物理线程创建失败，可能原因：系统线程数或内存耗尽。\n\n"
                    "引擎已降级为主线程串行跑物理（功能可用但性能下降）。\n\n"
                    "★ 请立即保存场景并关闭软件，排查系统资源占用。\n"
                    "★ 继续运行可能进一步耗尽资源，下次崩溃可能是整个系统。\n\n"
                    "Physics thread failed (OS thread/memory exhausted?).\n"
                    "Degraded to main-thread physics. SAVE & CLOSE NOW.")
            return
        # 2026-11-07 EAI 可视化 (B): Agent 进度正占用状态栏时, 300ms 轮询
        # 不得覆盖; 空闲 1.5s 后 _agent_idle 会主动回调本函数恢复默认文本.
        if getattr(self, '_agent_status_active', False):
            return
        self.statusBar().showMessage(txt)

    # ---------------- 设置对话框 ----------------
    def _cmd_settings(self):
        """设置对话框。

        2026-11-25 终审 P0-1（另一半）: **面板必须始终可达**。修前首行是
        `e = self.editor; if e is None: return` —— 视口装配失败（VK 不可用机器）
        时 self.editor 恒 None，对话框创建 0 次，用户连「把后端改成 OpenGL」这条
        唯一逃生门都没有（只能 --backend opengl 或手改 json）。
        现在按依赖切两段:
          · 不依赖 editor 的段落（GUI 界面 / 保存目录 / 渲染后端下拉 —— 只用
            guiloader + settings_set 命令壳）**无条件渲染**；
          · 依赖 editor 的段落（网格/并行/帧率/移速/重力/逻辑帧/插值/帧缓冲/核心数/
            插件）在 editor 为 None 时整段跳过，并显示一行「编辑器未就绪」说明。
        """
        e = self.editor          # 可能为 None（视口装配失败）—— 下面按依赖分段
        import guiloader
        s = guiloader.load_settings('loom')
        dlg = QDialog(self)
        dlg.setWindowTitle("设置")
        lay = QVBoxLayout(dlg)
        # GUI 界面
        lay.addWidget(QLabel("GUI 界面（重启后生效）"))
        gui_list = QListWidget()
        cur_gui = s.get('gui', 'LoomGUI')
        for g in guiloader.scan_guis('loom'):
            row = QListWidgetItem(("● " if g['id'] == cur_gui else "○ ") + g['name'])
            row.setData(Qt.ItemDataRole.UserRole, g['id'])
            gui_list.addItem(row)
        lay.addWidget(gui_list)

        def _on_gui(row):
            """切 GUI（不依赖 editor: 只写设置.json）。P0-1: editor 为 None 也可用。"""
            gid = row.data(Qt.ItemDataRole.UserRole)
            if gid:
                s['gui'] = gid
                guiloader.save_settings('loom', s)
                self._notify_or_print("已切换到「%s」，重启后生效" % gid, (240, 200, 90))
        gui_list.itemClicked.connect(_on_gui)
        # 保存目录
        lay.addWidget(QLabel("保存目录"))
        dir_row = QWidget()
        h = QHBoxLayout(dir_row)
        h.setContentsMargins(0, 0, 0, 0)
        dir_label = QLabel(s.get('save_dir') or '(默认)')
        h.addWidget(dir_label, 1)

        def _choose_dir():
            import filedialog
            d = filedialog.choose_directory("选择保存目录")
            if d:
                s['save_dir'] = d
                guiloader.save_settings('loom', s)
                dir_label.setText(d)
                self._notify_or_print("保存目录已更改，重启后生效", (240, 200, 90))
        b = QPushButton("更改…")
        b.clicked.connect(_choose_dir)
        h.addWidget(b)
        lay.addWidget(dir_row)
        # ---- 渲染后端（不依赖 editor: 只用 guiloader + settings_set 命令壳）----
        # Q-B7-60-1（人类 2026-11-23 裁决「一个键全局消费」）: 同一个 render_api 键既
        # 决定**编辑器视口**后端，也决定播放/打包游戏的后端（编辑器读它走
        # run_player.resolve_backend 同一条解析链）；玩家侧仍可 --backend /
        # 游戏设置.json 自行覆盖，底层设置 API 留给开发者 UI。
        # 裁决①: 重启编辑器生效，**不做视口热切换**。
        # 2026-11-25 终审 P1-1（写盘单层化）: 选中项 = **生效值**
        # （effective_render_api = 解析链最终结果），不再是引擎层单层值 —— 否则就是
        # 「面板显示 X、生效 Y」（游戏层覆盖键压过引擎层）。生效值来自游戏层时在右侧
        # 标注来源层，用户能看出「这个值是谁写的」。
        api_row = QWidget()
        ha = QHBoxLayout(api_row)
        ha.setContentsMargins(0, 0, 0, 0)
        ha.addWidget(QLabel("渲染后端（编辑器与播放共用，重启生效）"))
        api_combo = QComboBox()
        # 2026-11-06 R-05 (复核 B 指出): 下拉此前只有 vulkan/opengl, 设计文档 P5
        # 明写的 auto(vk 失败自动回退 gl) 因此无法从 UI 选到; 设置里存成 auto 时
        # 下拉还会错误地显示成 Vulkan。三项与 run_player.resolve_backend 的合法值
        # 集合严格一致。
        # P1-2（2026-11-25）: auto 两端同义 —— 先试 VK、失败回退 GL（编辑器侧由启动期
        # 探测 + 回退实现），故「自动（Vulkan 失败回退 OpenGL）」这个文案对两端都成立。
        try:
            from hostenv.editor_launch import effective_render_api
            _eff_api, _eff_src = effective_render_api()
        except Exception as _ee:
            print('[设置] 读生效渲染后端失败 (%r) -> 退回引擎层配置值' % (_ee,))
            _eff_api, _eff_src = s.get('render_api', 'vulkan'), 'engine'
        for i, (txt, aid) in enumerate((
                ("自动（Vulkan 失败回退 OpenGL）", "auto"),
                ("Vulkan（新，推荐）", "vulkan"),
                ("OpenGL（保底）", "opengl"))):
            api_combo.addItem(txt, aid)
            if aid == _eff_api:
                api_combo.setCurrentIndex(i)
        api_combo.setToolTip(
            "设置当前项目的渲染后端（以配置文件为准）。编辑器视口与播放/打包游戏共用此键；"
            "修改后重启编辑器/播放器生效。--backend 命令行参数可临时覆盖本次启动。")
        self._render_api_combo = api_combo
        # Q-B7-56-2 裁定①: 面板写盘翻译成命令（唯一写盘路径内部走 settings_set 命令壳），
        # 不再直写 guiloader。重启生效提示保留。
        api_combo.currentIndexChanged.connect(self._cmd_set_render_api)
        ha.addWidget(api_combo)
        if _eff_src == 'game':
            ha.addWidget(QLabel("（生效值来自 游戏设置.json 覆盖层）"))
        lay.addWidget(api_row)
        # ---- editor 为 None（视口装配失败）时: 以上三段照常可用，以下整段跳过 ----
        if e is None:
            lay.addWidget(QLabel(
                "编辑器未就绪（视口装配失败）：以上 GUI 界面 / 保存目录 / 渲染后端"
                "仍可修改；改成 OpenGL 后重启编辑器即可继续使用。"))
            _btns0 = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
            _btns0.rejected.connect(dlg.reject)
            _btns0.accepted.connect(dlg.accept)
            lay.addWidget(_btns0)
            dlg.exec()
            return
        # ---- 以下依赖 editor（网格/并行/帧率/移速/重力/逻辑帧/插值/帧缓冲/核心数/插件）----
        # 网格 / 并行 / 脚本核心数
        grid_chk = QCheckBox("无限网格（即时生效）")
        grid_chk.setChecked(bool(getattr(e, 'show_grid', True)))
        grid_chk.toggled.connect(lambda v: (setattr(e, 'show_grid', bool(v)),
                                            s.__setitem__('show_grid', bool(v)),
                                            guiloader.save_settings('loom', s)))
        lay.addWidget(grid_chk)
        par_chk = QCheckBox("多核并行（重启生效）")
        par_chk.setChecked(bool(getattr(e, 'parallel_enable', True)))
        # Q-B7-56-2 裁定①: 设置写盘翻译成 settings_set 命令 (提示保留)
        par_chk.toggled.connect(self._cmd_set_parallel)
        lay.addWidget(par_chk)
        # 帧率上限 (2026-08-19): 档位即时生效 (渲染定时器周期直接改)
        fps_row = QWidget()
        hf = QHBoxLayout(fps_row)
        hf.setContentsMargins(0, 0, 0, 0)
        hf.addWidget(QLabel("帧率上限（即时生效）"))
        fps_combo = QComboBox()
        cur_fps = s.get('fps_limit', '120')
        for i, (txt, fid) in enumerate(guiloader.FPS_OPTIONS):
            fps_combo.addItem(txt, fid)
            if fid == cur_fps:
                fps_combo.setCurrentIndex(i)
        fps_combo.currentIndexChanged.connect(
            lambda i: (s.__setitem__('fps_limit', fps_combo.itemData(i)),
                       guiloader.save_settings('loom', s),
                       self._apply_fps_limit(fps_combo.itemData(i)),
                       getattr(self, '_fb_lazy_refresh', lambda: None)(),
                       e._notify("帧率上限已生效", (240, 200, 90))))
        hf.addWidget(fps_combo)
        lay.addWidget(fps_row)
        # 摄像机移速倍率 (2026-08-19): 对数坐标拖条 —— 倍率 2^(p/100),
        # p∈[-100,100] 对应 0.5x~2x; 0.5→1 与 1→2 距离相等 (对数等距).
        speed_row = QWidget()
        hs = QHBoxLayout(speed_row)
        hs.setContentsMargins(0, 0, 0, 0)
        cur_sp = float(s.get('cam_speed', 1.0))
        speed_slider = QSlider(Qt.Orientation.Horizontal)
        speed_slider.setRange(-100, 100)
        speed_slider.setValue(int(round(100.0 * math.log2(cur_sp))))
        speed_label = QLabel("摄像机移速 %.2fx" % cur_sp)

        def _apply_speed(v):
            m = 2.0 ** (v / 100.0)
            s['cam_speed'] = round(m, 3)
            guiloader.save_settings('loom', s)
            speed_label.setText("摄像机移速 %.2fx" % m)
            if e is not None:
                e._cam_speed = s['cam_speed']   # 缓存同步 (editor._update_camera)
            e._notify("摄像机移速 %.2fx 已生效" % m, (240, 200, 90))
        speed_slider.valueChanged.connect(_apply_speed)
        hs.addWidget(QLabel("0.5x"))
        hs.addWidget(speed_slider, 1)
        hs.addWidget(QLabel("2x"))
        hs.addWidget(speed_label)
        lay.addWidget(speed_row)
        # 重力加速度 (2026-08-30 用户实测): 场景内整体重力可调 (m/s², 负=向下),
        # 即时生效 (engine.gravity; 场景文件可覆盖, 面板值=全局默认)
        grav_row = QWidget()
        hg = QHBoxLayout(grav_row)
        hg.setContentsMargins(0, 0, 0, 0)
        hg.addWidget(QLabel("重力加速度"))
        grav_spin = QDoubleSpinBox()
        grav_spin.setRange(-100.0, 100.0)
        grav_spin.setDecimals(2)
        grav_spin.setSingleStep(1.0)
        grav_spin.setValue(float(s.get('gravity', -9.8)))
        grav_spin.valueChanged.connect(
            lambda v: (s.__setitem__('gravity', round(float(v), 2)),
                       guiloader.save_settings('loom', s),
                       setattr(e, 'gravity', float(v)),
                       e._notify("重力加速度 %.2f m/s² 已生效 (播放器/场景)" % v,
                                 (240, 200, 90))))
        hg.addWidget(grav_spin)
        hg.addWidget(QLabel("m/s²（负=向下，即时生效）"))
        lay.addWidget(grav_row)
        # 逻辑帧频率 (2026-09-05 分离批3): 20/30/45/60/120/跟随渲染帧(=旧绑死)
        lf_row = QWidget()
        hl = QHBoxLayout(lf_row)
        hl.setContentsMargins(0, 0, 0, 0)
        hl.addWidget(QLabel("逻辑帧率（播放态）"))
        lf_combo = QComboBox()
        for txt, fid in (("1 Hz（步进播放）", 1), ("20 Hz", 20), ("30 Hz（默认）", 30),
                         ("45 Hz", 45), ("60 Hz", 60), ("120 Hz", 120),
                         ("跟随渲染帧（旧模式）", 0)):
            lf_combo.addItem(txt, fid)
            if int(fid) == int(s.get('logic_fps', 30)):
                lf_combo.setCurrentIndex(lf_combo.count() - 1)

        def _apply_lf(i):
            v = int(lf_combo.itemData(i))
            s['logic_fps'] = v
            guiloader.save_settings('loom', s)
            # 批5: 即时生效 — 播放态直接改运行中时钟 (accumulator 按新步长
            # 继续; <=0 时即时停步进=跟随渲染, >0 恢复分离)
            clk = getattr(e, '_clock', None)
            if clk is not None:
                if v > 0:
                    clk.set_fps(logic_fps=v)   # 即时改频 (accumulator 连续)
                # v<=0: 保持时钟但 preview 提示走重启 (绑死模式仅在启动时由
                # logic_fps<=0 判定, 不热切; ★B7b 2026-10-16 删 LOOM_NO_SPLIT env)
            e._notify("逻辑帧率 %s %s" % (
                "跟随渲染帧" if v <= 0 else ("%dHz%s" % (v, "（步进播放）" if v == 1 else "")),
                "已即时生效" if (v > 0 and clk is not None) else "（重启播放生效）"),
                (240, 200, 90))
        lf_combo.currentIndexChanged.connect(
            lambda i: (_apply_lf(i),
                       getattr(self, '_fb_lazy_refresh', lambda: None)()))
        hl.addWidget(lf_combo)
        lay.addWidget(lf_row)
        # 方案二 (2026-09-05): 插值模式 — 插值(默认, 落后半帧)/外推(领先半帧,
        # 急变速物体可能过冲; Unity Rigidbody.interpolation 枚举同款 trade-off)
        im_row = QWidget()
        hi = QHBoxLayout(im_row)
        hi.setContentsMargins(0, 0, 0, 0)
        hi.addWidget(QLabel("渲染位姿模式"))
        im_combo = QComboBox()
        for txt, mid in (("插值（默认，画面落后半帧内）", 'interpolate'),
                         ("外推（画面领先半帧内，可回退）", 'extrapolate')):
            im_combo.addItem(txt, mid)
            if mid == s.get('interp_mode', 'interpolate'):
                im_combo.setCurrentIndex(im_combo.count() - 1)
        im_combo.currentIndexChanged.connect(
            lambda i: (s.__setitem__('interp_mode', im_combo.itemData(i)),
                       guiloader.save_settings('loom', s),
                       setattr(e, '_interp_mode', im_combo.itemData(i)),
                       e._notify("渲染位姿模式: %s 已生效" % im_combo.itemData(i),
                                 (240, 200, 90))))
        hi.addWidget(im_combo)
        lay.addWidget(im_row)
        # 实验开关 (2026-09-06): TPS/FPS 帧缓冲 — 两道独立闸门灰置:
        #   TPS 缓冲: 逻辑帧率 >= 30 (低 TPS 单帧时间长, 缓冲引入延迟得不偿失)
        #   FPS 缓冲: 帧率档位 >= 60 且非无上限/auto (无上限=画一帧显一帧无节拍)
        # 两个开关互不牵连 (射击类=低TPS高FPS 只开 FPS 侧; 3A=高TPS低FPS 只开 TPS 侧)
        def _fb_gates():
            lf = int(s.get('logic_fps', 30))
            fl = s.get('fps_limit', '120')
            if fl == 'auto':
                fl = guiloader.device_fps_limit()
            try:
                fln = int(fl)
            except (TypeError, ValueError):
                fln = 0
            return lf, fln
        fb_row = QWidget()
        hfb = QHBoxLayout(fb_row)
        hfb.setContentsMargins(0, 0, 0, 0)
        tps_chk = QCheckBox("TPS缓冲（实验）")
        fps_chk = QCheckBox("FPS缓冲（实验）")
        tps_chk.setToolTip("空闲时提前算好下一逻辑帧 (最多2帧), 尖峰帧到点取成品保 TPS 节律。\n"
                           "要求: 逻辑帧率 ≥ 30 (低帧率缓冲延迟过大, 得不偿失)")
        fps_chk.setToolTip("空闲时把下一渲染帧预画进离屏缓冲, 到点直接上屏。\n"
                           "要求: 帧率上限 ≥ 60 且非无上限/自动 (无上限画一帧显一帧, 无节拍可缓冲)")
        hfb.addWidget(tps_chk)
        hfb.addWidget(fps_chk)
        hfb.addStretch(1)
        lay.addWidget(fb_row)

        def _fb_refresh():
            lf, fln = _fb_gates()
            tps_ok = lf >= 30
            fps_ok = fln >= 60
            tps_chk.setEnabled(tps_ok)
            fps_chk.setEnabled(fps_ok)
            if not tps_ok and tps_chk.isChecked():
                tps_chk.setChecked(False)
            if not fps_ok and fps_chk.isChecked():
                fps_chk.setChecked(False)
            tps_chk.setText("TPS缓冲（实验）" if tps_ok
                            else "TPS缓冲（需逻辑帧率≥30）")
            fps_chk.setText("FPS缓冲（实验）" if fps_ok
                            else "FPS缓冲（需帧率≥60且非无上限）")
        _fb_refresh()
        # 逻辑帧率/帧率档位变化时刷新灰置 (下拉回调里已存 s, 这里轮询即可 —
        # 两个 combo 的 currentIndexChanged 无法在此处直接拿到, 用懒刷新:
        # 面板每次打开重建, 运行中改档位后重开设置即刷新)
        tps_chk.setChecked(bool(s.get('frame_buffer_tps', False)))
        fps_chk.setChecked(bool(s.get('frame_buffer_fps', False)))
        _fb_refresh()   # setChecked 后再校一次闸门 (越界存档值自动弹回)

        def _apply_fb():
            s['frame_buffer_tps'] = bool(tps_chk.isChecked())
            s['frame_buffer_fps'] = bool(fps_chk.isChecked())
            guiloader.save_settings('loom', s)
            fb = getattr(e, '_frame_buf', None)
            if fb is not None:
                lf, _fln = _fb_gates()
                fb.enabled = bool(s['frame_buffer_tps'] and lf >= 30)
            e._notify("帧缓冲开关: TPS=%s FPS=%s %s" % (
                "开" if s['frame_buffer_tps'] else "关",
                "开" if s['frame_buffer_fps'] else "关",
                "(TPS 侧即时生效; FPS 侧重启播放生效)"),
                (240, 200, 90))
        tps_chk.toggled.connect(_apply_fb)
        fps_chk.toggled.connect(_apply_fb)
        self._fb_lazy_refresh = _fb_refresh   # 两个下拉回调联动刷新灰置
        # 批5: "物理步频"下拉已撤 — 物理在逻辑帧内自动子步 (Unity fixed_dt 语义),
        # 步长=内部参数 (设置.json "phys_substep_dt" 键, 高级开发者可调)
        cores_row = QWidget()
        hc = QHBoxLayout(cores_row)
        hc.setContentsMargins(0, 0, 0, 0)
        hc.addWidget(QLabel("脚本预留核心数"))
        cores = QComboBox()
        for n in (1, 2, 4):
            cores.addItem(str(n), n)
        cores.setCurrentIndex(max(0, cores.findData(int(s.get('script_cores', 2)))))
        cores.currentIndexChanged.connect(
            lambda i: (s.__setitem__('script_cores', cores.itemData(i)),
                       guiloader.save_settings('loom', s),
                       e._notify("预留核数重启后生效", (240, 200, 90))))
        hc.addWidget(cores)
        lay.addWidget(cores_row)
        # 插件挂载区 (2026-08-27 L1 分级): 三类三态展示 + 单独 加载/卸载/确认信任.
        #  plugins/editor|player = 普通插件 (受限环境, 目录即声明注入层);
        #  core_plugins/<类别>   = 核心插件 (全权, 信任闸: 未信任/被改 -> 确认后重启生效)
        lay.addWidget(QLabel(
            "插件（plugins/editor|player 普通插件·受限；core_plugins 核心插件·信任闸+重启生效）"))
        import plugin.loader as plugin_loader
        plug_list = QListWidget()
        plug_summary = QLabel("")

        def _add_head(text):
            item = QListWidgetItem(text)
            item.setFlags(Qt.ItemFlag.NoItemFlags)
            plug_list.addItem(item)

        def _add_plug_row(text, pid, state, path=None):
            """state: loaded|unloaded|broken|untrusted|modified"""
            row = QWidget()
            h = QHBoxLayout(row)
            h.setContentsMargins(6, 2, 6, 2)
            h.addWidget(QLabel(text), 1)
            b_load = QPushButton("加载")
            b_unload = QPushButton("卸载")
            b_load.setEnabled(state == 'unloaded')
            b_unload.setEnabled(state == 'loaded')
            b_load.clicked.connect(lambda: (_do_load(pid), _refresh_plugins()))
            b_unload.clicked.connect(lambda: (_do_unload(pid), _refresh_plugins()))
            h.addWidget(b_load)
            h.addWidget(b_unload)
            if state in ('untrusted', 'modified'):
                b_trust = QPushButton("确认信任")
                b_trust.clicked.connect(
                    lambda: (_do_trust(pid, path), _refresh_plugins()))
                h.addWidget(b_trust)
            item = QListWidgetItem()
            plug_list.addItem(item)
            item.setSizeHint(row.sizeHint())
            plug_list.setItemWidget(item, row)

        def _do_load(pid):
            plugin_loader.load_plugin(pid)   # 取消会话禁用 + 重新加载
            e._notify("已加载「%s」" % pid, (240, 200, 90))

        def _do_unload(pid):
            ok, err = plugin_loader.unload_plugin(pid)   # 会话禁用 (重启恢复)
            e._notify("已卸载「%s」%s" % (
                pid, err if not ok else "（重启前保持卸载，删目录可永久移除）"),
                (240, 200, 90))

        def _do_trust(pid, path):
            ok = plugin_loader.confirm_core_trust(pid, path)
            e._notify("「%s」已写入信任记录，重启后生效" % pid if ok
                      else "「%s」信任记录写入失败" % pid, (240, 200, 90) if ok
                      else (240, 120, 120))

        def _scan_unloaded(skip_ids=frozenset()):
            """未加载目录行: ['standard'|'core', pid|fname, info, path, err].
            skip_ids: 已单列 (待信任/已加载) 的插件 id, 不再重复列出."""
            out = []
            for layer in ('editor', 'player'):
                d = plugin_loader.plugin_dir(layer)
                if not os.path.isdir(d):
                    continue
                for fname in sorted(os.listdir(d)):
                    p = os.path.join(d, fname)
                    if not os.path.isdir(p):
                        continue
                    if any(plugin_loader.get_plugin(i)['path'] == p
                           for i in plugin_loader.get_loaded()):
                        continue
                    info, err = plugin_loader._parse_manifest(p)
                    if info is not None and info['id'] in skip_ids:
                        continue
                    out.append(('standard', fname, info, p, err))
            core = plugin_loader.core_plugin_root()
            if os.path.isdir(core):
                for cat in sorted(os.listdir(core)):
                    cd = os.path.join(core, cat)
                    if not os.path.isdir(cd):
                        continue
                    for fname in sorted(os.listdir(cd)):
                        p = os.path.join(cd, fname)
                        if not os.path.isdir(p):
                            continue
                        if any(plugin_loader.get_plugin(i)['path'] == p
                               for i in plugin_loader.get_loaded()):
                            continue
                        info, err = plugin_loader._parse_manifest(p, core=True)
                        if info is not None and info['id'] in skip_ids:
                            continue
                        out.append(('core', fname, info, p, err))
            return out

        def _refresh_plugins():
            plugin_loader.rescan_plugins()
            plug_list.clear()
            trust_items = plugin_loader.list_untrusted()
            trust_by_id = {t['id']: t for t in trust_items}
            core_rows, std_rows = [], []
            for pid, ent in plugin_loader.get_loaded().items():
                kind = ent['kind']
                txt = "● 已加载  %s  %s v%s" % (
                    "核心" if kind == 'core' else "标准", pid,
                    ent['info'].get('name', ''), ent['info']['version'])
                (core_rows if kind == 'core' else std_rows).append(
                    ('loaded', txt, pid, ent['path']))
            for tid, t in trust_by_id.items():
                prefix = "⚠ 被修改" if t['state'] == 'modified' else "⚠ 待信任"
                (core_rows if t.get('kind') == 'core' else std_rows).append(
                    (t['state'], "%s  %s（确认后重启生效）" % (prefix, tid),
                     tid, t['path']))
            for kind, fname, info, p, err in _scan_unloaded(set(trust_by_id)):
                if info is None:
                    txt = "× 有问题  %s  (%s)" % (fname, err)
                    (core_rows if kind == 'core' else std_rows).append(
                        ('broken', txt, fname, p))
                else:
                    txt = "○ 未加载  %s  %s v%s" % (
                        info['id'], info.get('name', ''), info['version'])
                    (core_rows if kind == 'core' else std_rows).append(
                        ('unloaded', txt, info['id'], p))
            if core_rows:
                _add_head("── 核心插件（全权 · 信任闸） ──")
                for state, txt, pid, path in core_rows:
                    _add_plug_row(txt, pid, state, path)
            if std_rows:
                _add_head("── 普通插件（受限环境） ──")
                for state, txt, pid, path in std_rows:
                    _add_plug_row(txt, pid, state, path)
            if plug_list.count() == 0:
                plug_list.addItem("(插件目录为空或不存在)")
            plug_summary.setText(
                "plugins: %s   |  核心: %s   |  已加载 %d 个" % (
                    plugin_loader.plugin_dir('loom'),
                    plugin_loader.core_plugin_root(), len(plugin_loader.get_loaded())))
        _refresh_plugins()
        lay.addWidget(plug_list)
        plug_row = QWidget()
        hp = QHBoxLayout(plug_row)
        hp.setContentsMargins(0, 0, 0, 0)
        hp.addWidget(plug_summary, 1)
        pb = QPushButton("重新扫描")
        pb.clicked.connect(lambda: (_refresh_plugins(),
                                    e._notify("插件已重新扫描", (240, 200, 90))))
        hp.addWidget(pb)
        lay.addWidget(plug_row)
        lay.addWidget(QLabel("更改 GUI / 保存目录 / 并行需重启 Loom 生效"))
        btns = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        btns.rejected.connect(dlg.reject)
        btns.accepted.connect(dlg.accept)
        lay.addWidget(btns)

        dlg.exec()

    # ---------------- 未保存询问 / 关闭 ----------------
    def _ask_save_dirty(self):
        """防丢询问框: 返回 'save' | 'discard' | 'cancel' (controller 三态).
        2026-08-22 A01 修复: 旧静态 question 只有 保存/不保存 两钮 —— 弹框
        右上角 X 被 Qt 归为 No -> 不保存直接退出 (用户实测); 现改三按钮 +
        escapeButton=取消 (X/Esc = 取消 = 返回编辑器继续编辑)."""
        box = QMessageBox(self)
        box.setWindowTitle("Loom")
        box.setText("当前场景有未保存的修改，是否保存？")
        b_save = box.addButton("保存", QMessageBox.ButtonRole.AcceptRole)
        b_discard = box.addButton("不保存", QMessageBox.ButtonRole.DestructiveRole)
        b_cancel = box.addButton("取消", QMessageBox.ButtonRole.RejectRole)
        box.setDefaultButton(b_save)
        box.setEscapeButton(b_cancel)
        box.exec()
        clicked = box.clickedButton()
        if clicked is b_save:
            return 'save'
        if clicked is b_discard:
            return 'discard'
        return 'cancel'

    def _ask_delete_confirm(self, model, n_children):
        """Q3=A 删除确认框 (2026-11-07, editor._confirm_delete_callback 的 Qt 实现)。

        editor.delete_object() 在"要连子树一起删"时回调本方法, 返回 False = 取消删除。
        文案按 F8 裁决: N>0 明说会一并删除 N 个子物体; N=0 是普通删除确认。
        默认按钮 = 否 (误按 Enter 不会删掉整棵子树), 关窗/取消都按"否"处理。
        """
        try:
            n = int(n_children)
        except (TypeError, ValueError):
            n = 0
        if n > 0:
            text = '该物体有 %d 个子物体，删除将一并删除，是否继续？' % n
        else:
            text = '确定删除该物体？'
        name = getattr(model, 'name', None)
        title = ('删除 %s' % name) if name else '删除确认'
        try:
            ans = QMessageBox.question(
                self, title, text,
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No)
        except Exception:
            # 弹框本身失败 (无 GUI 的异常环境): 保持旧行为 = 直接删, 不阻断操作
            return True
        return ans == QMessageBox.StandardButton.Yes

    def closeEvent(self, ev):
        e = self.editor
        # 2026-08-28: 命令行/Agent 经 quit 命令关窗时, dirty 决断 (存/丢) 已在
        # 命令层做完 —— 挂 _suppress_confirm 标记直接关, 不会再弹模态框
        # (用户实测: 命令行退出弹"是否保存"框, 命令链卡死没人真正关掉).
        # 人点窗口 X 不挂这个标记, 该弹的防丢框照弹 (A01 三态).
        if getattr(self, '_suppress_confirm', False):
            self._suppress_confirm = False
        elif e is not None and e.scene_is_dirty() and not e._confirm_unsaved():
            ev.ignore()
            return
        # 2026-10-19 第1档序7 应用级钩子：退出前派发 on_application_quit
        # （脚本存档/清理）。必须在 stop timer 前 —— 有些脚本需要引擎状态仍可读。
        if e is not None:
            try:
                e._dispatch_application_quit()
            except Exception as ex:
                print("[Qt] on_application_quit 派发异常 (忽略): %r" % (ex,))
        self._render_timer.stop()
        self._refresh_timer.stop()
        ev.accept()

    def changeEvent(self, ev):
        """2026-10-19 第1档序7 应用级钩子：窗口最小化/恢复时派发
        on_became_invisible / on_became_visible（脚本暂停音频/降帧率用）。
        只在状态真正变化时派发一次（Qt 会重复触发 WindowStateChange）。"""
        if ev.type() == QEvent.Type.WindowStateChange:
            e = self.editor
            if e is not None:
                was_min = bool(ev.oldState() & Qt.WindowState.WindowMinimized)
                is_min = bool(self.windowState() & Qt.WindowState.WindowMinimized)
                if not was_min and is_min:
                    try:
                        e._dispatch_visibility_changed(False)
                    except Exception as ex:
                        print("[Qt] on_became_invisible 派发异常 (忽略): %r" % (ex,))
                elif was_min and not is_min:
                    try:
                        e._dispatch_visibility_changed(True)
                    except Exception as ex:
                        print("[Qt] on_became_visible 派发异常 (忽略): %r" % (ex,))
        super().changeEvent(ev)


# =====================================================================
# 入口
# =====================================================================
def _confirm_core_plugins(win):
    """核心插件信任闸 (2026-08-27): 启动时对未信任/被修改的核心插件弹确认框.
    警告信息明示全权风险与来源可信要求; [确认信任] -> 写信任记录 + 提示重启
    (本次不加载, 重启后生效); [本会话不加载] -> 跳过. 无头/自动关闭模式跳过."""
    import plugin.loader as plugin_loader
    unfound = plugin_loader.list_untrusted()
    if not unfound:
        return
    for u in unfound:
        info = u['info']
        msg = QMessageBox(win)
        msg.setIcon(QMessageBox.Icon.Warning)
        msg.setWindowTitle("核心插件 · 信任确认")
        msg.setText("发现%s核心插件「%s」(v%s)" % (
            "被修改的" if u['state'] == 'modified' else "未信任的",
            info.get('name', info['id']), info['version']))
        msg.setInformativeText(
            "插件 id: %s\n注入层: %s   替换功能: %s\n来源目录: %s\n用途: %s\n\n"
            "⚠ 核心插件拥有引擎全部权限（等同引擎本体）：可读写任意文件、联网、"
            "启动进程。\n请确认插件来源可信（建议安装前阅读插件源码）。\n"
            "确认信任后将写入信任记录，重启 Loom 后生效。" % (
                info['id'], info.get('layer', ''), info.get('capability', ''),
                u['path'], info.get('desc', '')))
        ok_btn = msg.addButton("确认信任（重启后生效）",
                               QMessageBox.ButtonRole.AcceptRole)
        msg.addButton("本会话不加载", QMessageBox.ButtonRole.RejectRole)
        msg.exec()
        if msg.clickedButton() is ok_btn:
            if plugin_loader.confirm_core_trust(info['id'], u['path']):
                print("[插件] 已信任「%s」, 重启后生效" % info['id'])
            else:
                print("[插件] 「%s」信任记录写入失败" % info['id'])


def run_loom_gui(scene_path=None, width=1280, height=800, backend='gl',
                 explicit=False):
    """PySide6 编辑器入口 (Loom.py --ui qt 调用). QApplication + 主窗口 + 事件循环.
    支持 --auto-close N: N 秒后自动关闭 (冒烟测试用, 交互使用不要带).
    S4: backend='vulkan' -> 编辑器视口走 VK。backend 为 vulkan 的来源**两种**:
    配置文件 render_api（Q-B7-60-1 后配置同样驱动，且缺省配置就是 vulkan）或
    显式 --backend（Q-B7-60-1：显式仍是最高优先级）；缺省 'gl' 与修前逐位一致。

    2026-11-25 终审 P0-1（人类 2026-11-24 指令「编辑器启动时 VK 失败 → 自动改写配置为
    opengl + 提示」）: explicit=True 表示本次 backend 来自**显式** --backend —— 装配失败
    时**不改写用户配置**（Q6 先例：显式选择不动配置），但仍给可见提示 + 本次回退 GL。
    两个入口都传（run_player.parse_backend_arg(argv) is not None）。"""
    fmt = QSurfaceFormat()
    # 2026-11-09 A0 (D1=B): GL 地板 4.3 core（Qt 里请求不到时由各视口的版本门明确报错）
    fmt.setVersion(GL_MIN_MAJOR, GL_MIN_MINOR)
    fmt.setProfile(QSurfaceFormat.OpenGLContextProfile.CoreProfile)
    fmt.setDepthBufferSize(24)
    fmt.setSamples(4)   # TEMP-回退: 恢复用户测试时的多采样状态
    # 2026-08-19: 关垂直同步 (swapInterval=0) —— Qt 默认 vsync 会把帧率锁在
    # 显示器刷新率 (60Hz 屏=60FPS, 重写后 120→60 的根因之一). pygame 模式
    # 本来就是无 vsync 自由渲染 (120FPS), Qt 模式对齐. 高帧率换潜在撕裂,
    # 与 pygame 模式行为一致 (用户接受).
    fmt.setSwapInterval(0)
    QSurfaceFormat.setDefaultFormat(fmt)

    auto_close = 0
    if '--auto-close' in sys.argv:
        i = sys.argv.index('--auto-close')
        if i + 1 < len(sys.argv):
            try:
                auto_close = float(sys.argv[i + 1])
            except ValueError:
                auto_close = 3

    # 无 --open: 自动恢复上次保存/打开的场景 (editor_state 的 last_scene).
    # 否则每次启动都是种子场景, 保存永远弹另存为 (旧文件被避让成 场景1.json).
    if scene_path is None:
        try:
            from editor.core import STATE_FILE, load_last_scene  # B4: 常量真源在 editor.core（monkeypatch 目标 = editor.core.STATE_FILE）
            scene_path = load_last_scene(STATE_FILE)
        except Exception:
            pass

    app = QApplication(sys.argv)
    win = LoomGUI(scene_path=scene_path, width=width, height=height, backend=backend,
                  explicit=explicit)
    # 2026-08-27 EAI: --agent 启动命令桥 (Http 127.0.0.1 + 端口文件) +
    # 主线程 QTimer 轮询命令队列 (与 UI 一致执行); Agent 经 /cmd /logs 驱动
    agent = None
    if '--agent' in sys.argv:
        import agent_commands
        agent = agent_commands.AgentService(win)
        # 2026-11-07 EAI 可视化: 先绑定服务, 再启动 HTTP; 钩子由 AgentService 侧 getattr 调用.
        win._bind_agent_service(agent)
        try:
            agent.start()
            _t = QTimer(win)
            _t.setInterval(4)
            _t.timeout.connect(agent.drain)
            _t.start()
        except Exception as e:
            print("[agent] EAI 启动失败: %r" % e)
    if auto_close > 0:
        QTimer.singleShot(int(auto_close * 1000), win.close)
    win.show()
    # 2026-10-20 白屏修复 P0-2：show 后确保窗口在屏幕内并激活。
    # 报告发现第二次启动 Qt 主窗口出现在 -25600,-25600 / 159×27（WM 记住了上次最小化状态），
    # 同时可见窗口是 ConsoleWindowClass —— 用户看到的是 console/白底而不是编辑器。
    # 修复：showNormal + 屏幕外强制移回 + raise/activate + 触发 surface 重建。
    #
    # 2026-10-20 二次强化：根因是 LoomHub 用 CREATE_NO_WINDOW 启动时 Windows 给
    # 子进程传 STARTUPINFO.wShowWindow=SW_HIDE，Qt 遵循把窗口藏到 (-25600,-25600)，
    # 用户看到"白屏"（其实是窗口隐藏）。修复：Qt 侧 + Win32 侧双保险强制可见。
    try:
        # 1) 强制清除隐藏/最小化状态
        win.setWindowState(Qt.WindowState.WindowNoState)
        win.showNormal()
        # 2) 检查几何位置
        g = win.geometry()
        moved = False
        if g.x() < -1000 or g.y() < -1000 or g.width() < 400 or g.height() < 300:
            screen = QGuiApplication.primaryScreen()
            if screen is not None:
                avail = screen.availableGeometry()
                w = min(1280, avail.width() - 80)
                h = min(720, avail.height() - 80)
                win.resize(max(800, w), max(600, h))
                win.move(avail.x() + 40, avail.y() + 40)
                moved = True
                print('[Qt] 窗口从异常位置 (%d,%d %dx%d) 移回屏幕'
                      % (g.x(), g.y(), g.width(), g.height()))
        # 3) Win32 兜底：强制 ShowWindow(SW_SHOWNORMAL) + SetForegroundWindow
        # 对付 STARTUPINFO.wShowWindow=SW_HIDE 的 Qt 底层表现
        try:
            import ctypes
            hwnd = int(win.winId())
            SW_SHOWNORMAL = 1
            ctypes.windll.user32.ShowWindow(hwnd, SW_SHOWNORMAL)
            ctypes.windll.user32.SetForegroundWindow(hwnd)
            ctypes.windll.user32.BringWindowToTop(hwnd)
        except Exception as _we:
            print('[Qt] Win32 兜底异常: %r' % _we)
        # 4) Qt 高层激活
        win.raise_()
        win.activateWindow()
        # 5) 触发 QOpenGLWidget surface 重建
        try:
            win.viewport.update()
            win.viewport.repaint()
        except Exception:
            pass
        # 6) 最终几何兜底（Win32 调用后 Qt geometry 可能不同步）
        if moved:
            win.move(win.x(), win.y())
    except Exception as e:
        print('[Qt] 窗口激活异常: %r' % e)
    if not auto_close:
        # 核心插件信任闸: 待确认弹窗 (自动关闭冒烟模式跳过)
        try:
            _confirm_core_plugins(win)
        except Exception as e:
            print("[插件] 信任确认流程异常: %r" % e)
    app.exec()
    if agent:
        try:
            agent.stop()
        except Exception:
            pass
    sys.exit(0)


if __name__ == "__main__":
    run_loom_gui()






