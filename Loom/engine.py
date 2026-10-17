# -*- coding: utf-8 -*-
"""
engine.py — GLEngine: moderngl (OpenGL) 真 GPU 渲染 + pygame 窗口/输入/HUD

渲染管线:
  顶点数据一次性上传为 VBO (展平: 每三角形 3 个独立顶点, 带位置/法线/颜色)
  MVP 每帧 CPU(numpy) 计算, 以 uniform 传给 GPU
  GPU 顶点着色器变换 + 光栅化 + 硬件深度测试 (Z-buffer) + 背面剔除
  pygame 管窗口/事件/字体 HUD (文字纹理 quad)

矩阵约定 (与 CPU 路径一致, 无镜像):
  - view: mat4_view_yaw_pitch (前方 z_view>0, det=+1)
  - proj: mat4_perspective (clip.w=z_view, clip.z 单调映射 [0,1], 供硬件深度测试)
  - uniform 上传: matlib 行主序 M 直接 tobytes (不转置) = GPU 的 M^T, 使 GLSL u*v 等价 numpy v@M
"""
import json
import math
import os
import threading
import time
import uuid
from collections import namedtuple

import numpy as np
import pygame
import moderngl

from matlib import (mat4_translation, mat4_rotation, mat4_scale,
                    mat4_perspective, mat4_view_yaw_pitch,
                    mat4_ortho, mat4_view_forward, decompose_euler,
                    view_basis_to_angles)   # M29: 光源正交投影/任意朝向视图; M41: set_parent 保世界旋转; 2026-08-16: 相机物体化挂父合成反解
from fastpath import depths as _fp_depths   # 组3: 深度DP Numba可选加速 (未装numba自动降级纯Python, 数值同源, 见fastpath.py)
from fastpath import ancestry_dfs as _fp_ancestry   # 组3层2: ancestry DFS Numba可选加速 (未装numba自动降级纯Python, 语义逐位同源, 见fastpath.py)
import fastpath   # 组3层3: AABB 批量归约 (aabbs_minmax 串行 njit 默认 / _par 逃生门)
from core_clock import clock_from_settings, split_enabled   # 分离批1: 逻辑帧/渲染帧分离时钟 (零依赖)
from interp_state import InterpState   # 分离批2: prev/curr 快照 + alpha 插值 (单实现双端共享)
from scheduler import (NgilPool, sched_wm_chunk,       # 调度重构期1: nogil 常驻工作池
                       split_bounds as sched_split_bounds)
import script_glue as _sg

from loom_types import Point3D   # 已抽出：原 engine.py 内联 namedtuple

# ---- 着色器源码常量（已抽出到 loom_shaders.py，原 45-307 行） ----
from loom_shaders import (  # noqa: E402
    _VERT_SRC, _FRAG_SRC, _HUD_VERT, _HUD_FRAG,
    _LINE_VERT, _LINE_FRAG,
)
from loom_shadow import ShadowMixin   # M29 阴影子系统 (已抽出)
from loom_frame_components import FrameComponentMixin   # 每帧组件推进 (音频/动画/碰撞回调)
from loom_physics import PhysicsMixin   # M28 碰撞 + M31 刚体物理 (已抽出)

# ---- 按键映射 + 输入动作层（已抽出到 loom_input.py，原 51-77 行） ----
from loom_input import _KEYMAP, DEFAULT_ACTIONS, _ACTION_FILE   # noqa: E402,F401
from loom_input import InputMixin   # 输入子系统 (按键/动作层/鼠标锁定/键位配置)
from loom_hud import HudMixin   # HUD/文字渲染子系统
from loom_camera import CameraMixin   # 相机控制子系统 (轨道相机/键控移动旋转)
from loom_render import RenderMixin   # 渲染管线子系统 (主 pass 帧准备/绘制/帧循环)
from loom_model_gpu import ModelGpuMixin   # 模型/材质 GPU 资源子系统 (几何构建/桶/场景加载)
from loom_lighting import LightingMixin   # 光源/光照上传/阴影 VP 子系统
from loom_window import WindowMixin   # 窗口/事件子系统 (尺寸/全屏/事件循环/输入钩子)
from loom_transform import TransformMixin   # 变换层次子系统 (世界矩阵/父链/包围盒)
from loom_profiler import ProfilerMixin   # 性能插桩子系统 (LOOM_PROFILE 阶段耗时)
from loom_logic_thread import LogicThreadMixin   # 逻辑帧线程子系统 (异步逻辑线程启停/主循环)

# ---- 组件化 M25（已抽出到 loom_components.py，原 79-448 行） ----
from loom_components import (  # noqa: E402,F401
    Component, TransformComponent, MeshRendererComponent, ScriptComponent,
    ColliderComponent, RigidbodyComponent, AudioSourceComponent,
    AnimationClip, AnimatorComponent, AudioSystem,
)


# ---- 材质资产（已抽出到 loom_material.py，原 451-495 行） ----
from loom_material import Material   # noqa: E402,F401


# ---- 场景物体 GameObject（已抽出到 loom_game_object.py，原 91-368 行） ----
from loom_game_object import GameObject   # noqa: E402,F401

# ---- 光源/相机/运行时 UI（已抽出到 loom_scene_entities.py，原 94-319 行） ----
from loom_scene_entities import (  # noqa: E402,F401
    wrap_deg, direction_to_angles, LightState, CameraState, RuntimeUI,
)
# ---- 按键绑定配置（已抽出到 loom_input.py，原 98-118 行） ----
from loom_input import KEY_BINDINGS   # noqa: E402,F401
# ---- hex→rgba 与缓存（已抽出到 loom_color.py，原 1027-1041 行） ----
from loom_color import _hex_rgba, _HEX_RGBA_CACHE   # noqa: E402,F401


# ================ GC 生命周期 (2026-09-01 流畅度批, 1% low 帧尖刺治理) ================
# 依据 (GC 批设计规格): 500 球场景 501 独立 Mesh 各带 vertices/faces/face_colors
# 大 list ≈ 490 万槽/次 gen2 遍历, 默认阈值下单次 gen2 停顿 20-150ms、约每 5-8 帧
# 有资格触发 —— 即用户实测"运动时掉帧卡顿感"的本体. 治理 = freeze 永久代化场景 +
# 播放态放宽阈值 (只放宽, 不 disable).
_GC_THRESH_PLAY = (50000, 50, 200)
# 依据: threshold0 700→50000 (500 球播放期 churn 12-15K tracked 对象/帧, 默认每帧
# 可触 17-21 次 gen0; 50000 → 约 1 次/3-4 帧); threshold1/2 放宽使 gen2 自动触发
# 降到数分钟级, 配合 freeze 后 gen2 单价也从 20-150ms 降到 <1ms.
# 备选档 (20000, 25, 100): 若 LOOM_GC_PROBE 实测 gen0 单次 p99 > 1ms 再降档.
_gc_thresh_prev = None      # 进入前 gc.get_threshold() 快照 (退出恢复, 非硬编码)
_gc_play_active = False     # 冻结态标志 (PlayerApp.load_scene 包裹判据/探针查询)

# ★铁律: 禁止 gc.disable ——
#   1) 脚本实例天然成环: update_scripts 绑 s.obj=m / s.engine=self; remove_model
#      (播放中) 后遗留 s.obj→m→sc→_script→s 真环, refcount 不可回收, 必须靠代际回收;
#   2) 用户脚本更易造环 (self 挂回调/缓存/监听);
#   3) 发布 exe 玩家长局无兜底重启时机, disable = 内存单调上涨;
#   4) 自定义脚本生态 (scripts.py 注册制) 是硬要求, 不能牺牲循环回收换流畅.


def _gc_enabled():
    """LOOM_GC_LEGACY=1 时全部 GC 管理变 no-op (A/B 基线 + 秒级回滚通道)."""
    return os.environ.get('LOOM_GC_LEGACY') != '1'


def engine_gc_frozen():
    """当前是否处于冻结播放态 (load_scene 包裹判据; 探针/测试用)."""
    return _gc_play_active


def gc_play_enter():
    """进入常驻播放态调用 (PlayerApp 场景加载后 / EditorApp toggle_play 进播放 /
    压测探针预热后): full collect 清进入前垃圾 → freeze 把全部 tracked 对象移入
    永久代 (490 万槽从此不进 gen2 遍历) → 放宽阈值. 冻结对象仍完全可用,
    只是 GC 不再扫/收. 一次性代价: collect 在加载尾 ~20-150ms@500球 (加载时刻)."""
    global _gc_thresh_prev, _gc_play_active
    import gc
    if not _gc_enabled():
        return
    try:
        gc.collect()                      # 只冻"活的" (冻结对象 unfreeze 前永不回收)
        gc.freeze()
        if _gc_thresh_prev is None:
            _gc_thresh_prev = gc.get_threshold()
        gc.set_threshold(*_GC_THRESH_PLAY)
        _gc_play_active = True
    except Exception as e:
        print("[gc] gc_play_enter 失败 (忽略, 回退默认 GC): %r" % (e,))


def gc_play_exit():
    """退出播放态调用 (EditorApp toggle_play 退播放 / PlayerApp.load_scene 包裹):
    unfreeze (冻结对象回普通代, 播放期垃圾/断环可回收) → full collect →
    阈值恢复进入前实测值. 幂等: 未 enter 时 unfreeze/collect 亦无害."""
    global _gc_thresh_prev, _gc_play_active
    import gc
    if not _gc_enabled():
        return
    try:
        gc.unfreeze()
        gc.collect()
        if _gc_thresh_prev is not None:
            gc.set_threshold(*_gc_thresh_prev)
            _gc_thresh_prev = None
        _gc_play_active = False
    except Exception as e:
        print("[gc] gc_play_exit 失败 (忽略): %r" % (e,))


class GLEngine(ShadowMixin, FrameComponentMixin, PhysicsMixin, InputMixin, HudMixin, CameraMixin,
               RenderMixin, ModelGpuMixin, LightingMixin, WindowMixin, TransformMixin,
               ProfilerMixin, LogicThreadMixin):
    # 组2 (2026-08-30) _ancestry_ranges 结果缓存 (tin/tout, 类级):
    # key=(id(models 列表对象), _ANCESTRY_GEN 版本号); 五个结构变更点
    # (add_model/remove_model/clear_scene/set_parent/remove_camera) 写 _ANCESTRY_GEN
    # 失效. 挂类级而非实例级: _ancestry_ranges 是 @staticmethod, 无 self 可挂;
    # 多实例共存时 id(models) 对象身份区分列表, 版本号全类共享只会"多算不会错算".
    # 组3 (2026-08-30) SoA: 类属性 _ANCESTRY_GEN 换为实例属性守卫 _bump_struct()
    # (多引擎实例互不误伤; 各失效点改调 self._bump_struct()).
    # _ANCESTRY_CACHE 已随 M28 碰撞段迁入 loom_physics.PhysicsMixin。

    def _bump_struct(self):
        """组3: 结构变更计数器 (SoA 平面快照 + ancestry 缓存共用失效源).
        实例属性守卫: 测试桩 (__new__ 不跑 __init__) 无 _struct_gen 时惰性建."""
        try:
            self._struct_gen += 1
        except AttributeError:
            self._struct_gen = 1

    # 组3: 活实例弱引用表 (GameObject.parent 旁路置脏用; __init__ 注册,
    # 弱引用自动回收死实例)
    import weakref as _weakref
    _LIVE_INSTANCES = []

    def __init__(self, width=800, height=800, fov_deg=60.0, ctx=None):
        # 组3: 活实例弱注册 (GameObject.parent 旁路失效通道; 死实例自动脱落)
        cls_live = GLEngine._LIVE_INSTANCES
        cls_live[:] = [r for r in cls_live if r() is not None]
        cls_live.append(GLEngine._weakref.ref(self))
        self._struct_gen = 0                   # 组3: 结构变更计数器 (SoA+ancestry)
        self.width = width
        self.height = height
        self.window_size = (width, height)   # 窗口模式尺寸 (F11 全屏恢复用)
        self.fullscreen = False              # 假全屏 (无边框铺满, 不切分辨率)
        self.allow_fullscreen = True         # 是否允许 F11 全屏 (编辑器 False / 封装游戏 True; 2026-08-17)
        self._window_rect = None             # 全屏前的窗口矩形 (退出还原位置用)
        self.fov_deg = fov_deg
        self._fov = math.radians(fov_deg)
        self.near = 0.1
        self.far = 100.0

        # ================ 相机/渲染参数 (可在此处修改) ================
        self.camera = Point3D(0, 0, -5)   # 初始相机位置 (2026-08-28: camera_initial 死字段已并)
        self.camera_move_speed = 3.0      # 相机移动速度 (单位/秒)
        self.camera_rotation_speed = 0.6  # 相机旋转速度 (弧度/秒)
        # 2026-08-30 用户实测: 重力加速度可调 (m/s², 负=向下; 默认 -9.8 同 _GRAVITY).
        # 场景文件 'gravity' 字段按场景覆盖; 设置面板可改全局值 (即时生效);
        # 脚本/物理全部走 self.gravity —— 感觉偏慢直接调它, 不用改代码.
        self.gravity = -9.8
        # B1 (2026-08-30): Culverin (Jolt) 物理桥 (physics_bridge.py) —— 播放期接管
        # 刚体动力学 (速度/重力/接触解算/摩擦), 引擎几何碰撞管线全部保留 (混合式).
        # _phys_bridge: 桥实例 (None=未建/不可用); _phys_bridge_auto: 完整 __init__
        # 实例才惰性建桥 —— 测试桩用 __new__ 不跑 __init__, 无此属性 ->
        # getattr 回退 False -> update_physics 永远走 legacy 契约路径
        # (现契约测试零受影响; 详见 update_physics 2674 附近分支说明).
        self._phys_bridge = None
        self._phys_bridge_auto = True

        self.camera_yaw = 0      # 水平旋转角度 (弧度)
        self.camera_pitch = 0    # 垂直旋转角度 (弧度)
        self.camera_roll = 0     # 绕视线方向倾斜 (弧度, M41; 场景摄像机 roll 经 apply_camera 换算)

        # ================ 轨道相机 (编辑器模式用) ================
        self.orbit_mode = False          # True 时 render 用 apply_orbit_camera
        self.camera_target = (0.0, 0.0, 0.0)   # 轨道目标点
        self.camera_distance = 10.0            # 相机到目标距离

        # 场景光源列表 (实体): 无默认光源, 由用户手动添加 (平行光/点光源)
        self.lights = []
        # 场景摄像机列表 (实体, Unity Camera 概念): 玩家视角 = active_camera
        self.cameras = []
        self.active_camera = None      # 当前玩家视角摄像机 guid (None = 默认轨道相机)
        # 材质库 (M23): 场景内全部 Material 资产, 物体按引用共享 (改一处全变)
        self.materials = []

        # ================ 窗口 + OpenGL 上下文 ================
        # ctx 注入 = 嵌入式模式 (2026-08-17): 宿主 (Qt QOpenGLWidget) 已建好 moderngl
        # 上下文, 引擎不再创建 pygame 窗口 —— pygame(SDL) 窗口会进程级污染中文输入法
        # (IME) 候选框 (见记忆 sdl-window-contaminates-ime), 编辑器弃用 pygame 做窗口;
        # 游戏播放器 (PlayerApp) 仍走 pygame 分支, 行为不变.
        self._external_ctx = ctx is not None
        self._desktop_override = None   # 测试钩子: 固定桌面分辨率
        if ctx is None:
            pygame.init()
            pygame.display.gl_set_attribute(pygame.GL_CONTEXT_MAJOR_VERSION, 3)
            pygame.display.gl_set_attribute(pygame.GL_CONTEXT_MINOR_VERSION, 3)
            pygame.display.gl_set_attribute(pygame.GL_CONTEXT_PROFILE_MASK,
                                            pygame.GL_CONTEXT_PROFILE_CORE)
            self.window = pygame.display.set_mode((width, height),
                                                  pygame.OPENGL | pygame.DOUBLEBUF
                                                  | pygame.RESIZABLE)
            pygame.display.set_caption("Loom - OpenGL (moderngl) GPU 渲染")
            # 窗口创建前的桌面分辨率 (Info() 在窗口存在后只返回当前窗口尺寸, 不可信;
            # F11 假全屏要铺满屏幕, 用真桌面尺寸; 运行中桌面分辨率变化极少, 此快照够用)
            _di = pygame.display.Info()
            self._desktop_size = (_di.current_w, _di.current_h)
            # 从控制台(.bat)启动时窗口可能抢不到键盘焦点 -> 强制置前
            # (Windows 限制: SetForegroundWindow 只在进程允许时生效, 创建窗口后立即调用一般可行)
            try:
                import ctypes
                hwnd = pygame.display.get_wm_info()['window']
                ctypes.windll.user32.SetForegroundWindow(hwnd)
            except Exception:
                pass
            # 关闭文本输入合成, 避免中文输入法(IME)吞掉字母/方向键的 KEYDOWN
            pygame.key.stop_text_input()
            self.ctx = moderngl.create_context()
        else:
            self.window = None                 # 外部模式: 无 pygame 窗口 (Qt 宿主管窗口)
            self._desktop_size = (width, height)
            self.ctx = ctx
        self.ctx.viewport = (0, 0, width, height)
        self.ctx.enable(moderngl.DEPTH_TEST)
        self.ctx.enable(moderngl.CULL_FACE)
        # view 前方 +z 约定 (相机在 -z 看向 +z): 法线朝外的面在屏幕空间绕序是 CW
        # (标准 OpenGL 前方 -z 才是 CCW), 所以 front_face 必须设为 cw, 否则正面被剔除
        self.ctx.front_face = 'cw'

        # 着色器程序
        self.prog = self.ctx.program(vertex_shader=_VERT_SRC, fragment_shader=_FRAG_SRC)
        self.hud_prog = self.ctx.program(vertex_shader=_HUD_VERT, fragment_shader=_HUD_FRAG)
        # M36 贴图: 1x1 白纹理 (无贴图材质的默认绑定, 采样乘白=原色不改视觉)
        self._white_tex = None
        self._build_hud_quad()
        # M29 阴影: 深度 pass 着色器 + 阴影贴图缓存 (guid -> {'type','tex','fbo'})
        # (已抽出到 loom_shadow.ShadowMixin；见 _init_shadow)
        self._init_shadow()
        # A2 (2026-08-29): GL 实例化批绘制 —— 按 mesh 桶共享几何/桶级实例缓冲:
        # 逐物体 draw 循环换成桶内一次 draw (50 球 51 draw -> ~3 draw).
        self._bucket_geo = {}     # mesh 桶 key -> {'vbo','vao','sha_vbo','sha_vao','nv'}
        self._bucket_inst = {}    # mesh 桶 key -> {'main','sha','n'} 实例缓冲 (容量生长)
        self._fw32 = None         # 当帧世界矩阵 f32 持久容量缓冲 (cap>=n 每帧原地 cast, GC 批)
        self._render_buckets = [] # 当帧 (桶 key, 模型下标列表) 列表

        # 组6可移植件3 (2026-09-02): uniform 句柄+值差分缓存 —— 热点实测
        # u_view_proj/u_view_pos 每帧字符串哈希取 uniform + 无条件上传; 灯光 8 组
        # write(tobytes) 同样每帧全量。_u 句柄缓存消字符串查找; _u_last 值差分
        # 同值跳过 (GL uniform 状态机保证语义等价)。写点已 Grep 穷尽: self.prog
        # 全部写点 = _upload_lights (L2057起) + render (L4121/4123), 单一所有者。
        # _u_last 键 = uniform 名, 值 = (kind, bytes/tuple/float) 上次已传内容;
        # program 无热重载路径 (构建一次), 无需失效钩子。
        self._u = {}              # 名 -> uniform 句柄 (惰性填充)
        self._u_last = {}         # 名 -> 上次成功上传的值 (差分跳过用)

        # 字体 (微软雅黑, 含中文; 找不到再退回默认)
        self.font = self._load_font(16)
        self._font_cache = {}                 # size -> pygame.font (GUI 用不同字号)
        # 文字纹理 LRU 缓存 (key=(text,color,size) -> (tex,w,h)), 防每帧重复建纹理
        from collections import OrderedDict
        self._text_cache = OrderedDict()
        self._text_cache_max = 400

        # ================ 模型状态初始化 ================
        from mesh import create_cube, create_sphere
        self.models = []
        self.current_model_index = 0
        # 立方体 (主) — 平直光照 (面法线); 尺寸对齐 Unity (边长 1)
        self.add_model(create_cube(1.0),
                       Point3D(0, 0, 0), Point3D(0, 0, 0),
                       normal_mode='flat')
        # 立方体 (小, 右侧) — 平直光照 (面法线)
        self.add_model(create_cube(1.0 * 0.7),
                       Point3D(3, 0, 0), Point3D(0, 0, 0),
                       normal_mode='flat')
        # 高面数球体 (体现批量渲染, 前方偏上) — 光滑光照 (顶点径向法线)
        # 半径对齐 Unity 默认 (0.5, 直径 1)
        self.add_model(create_sphere(0.5, stacks=14, slices=28),
                       Point3D(0, 0.6, -1.5), Point3D(0, 0, 0),
                       normal_mode='vertex')
        # ======================================================

        # 按键: 字符配置 -> pygame 键码
        self._key = {name: _KEYMAP[ch] for name, ch in KEY_BINDINGS.items()}
        # 存储按键状态 (按住类按键; 2026-08-28 清除玩具期 MODEL_*/ROTATE_* 键控)
        self.key_state = {}
        for name in ('CAMERA_FORWARD', 'CAMERA_BACKWARD', 'CAMERA_LEFT', 'CAMERA_RIGHT',
                     'CAMERA_UP', 'CAMERA_DOWN', 'LOOK_LEFT', 'LOOK_RIGHT',
                     'LOOK_UP', 'LOOK_DOWN'):
            self.key_state[self._key[name]] = False

        # 帧率计数
        self.last_time = time.perf_counter()   # 高精度单调钟 (与帧 dt 同源)
        self.fps = 0
        self.frame_count = 0
        # 方案一②: 帧长滑窗 (120 帧, deque maxlen 固定 — 长寿命对象不再换,
        # GC 批 freeze 兼容; _last_frame_stamp = 上一渲染帧时间戳)
        from collections import deque
        self._frame_dt = deque(maxlen=120)
        # ★2026-09-07 卡顿修复②配套: 帧时钟切 perf_counter (Qt 宿主 paintGL 与
        # editor._update_camera 同步换; time.time() 系统定时器粒度 1-15.6ms 是
        # dt 量化抖动源)。_last_frame_stamp 只被 _update_fps 用 (帧长滑窗),
        # 单调钟下语义不变。
        self._last_frame_stamp = time.perf_counter()
        self.last_frame_time = time.perf_counter()
        self._running = False
        self.ui = RuntimeUI(self)        # M33: 运行时 UI (脚本声明 HUD/按钮/进度条)
        self.audio = AudioSystem()       # M34: 音频 (pygame.mixer 封装, Sound 缓存)
        # M38: 游戏脚本目录 (exe/引擎旁的 scripts/) 启动时加载注册
        # (Unity 项目脚本机制: 游戏专属脚本放这, 检查器可挂, 打包时随游戏分发)
        try:
            from scripts import load_script_dir
            load_script_dir(os.path.join(
                os.path.dirname(os.path.abspath(__file__)), 'scripts'))
        except Exception:
            pass

        # 脚本输入状态 (M27): 每帧 _handle_events 由 pygame.key.get_pressed 刷新,
        # 键名见 _KEYMAP ('w'/'space'/'Left'...). 脚本/游戏逻辑用 engine.is_key() 查询.
        self.script_keys = {}
        # M32: 鼠标相对移动 (每帧 get_rel, 供第一/第三人称玩家控制器转向; 非播放期不消费)
        self.mouse_rel = (0, 0)
        # M39: 鼠标锁定 (FPS 标准: 隐藏+捕获居中, 视角无限转; 释放后显示+滑动不转)
        self.mouse_locked = False
        self.mouse_unlock_requested = False   # 玩家主动解锁意图 (Tab 切换)
        self._ui_capture_mouse = False        # 特殊场景(UI 菜单/暂停)强制显示鼠标标志
        # 输入动作层 (M30b, Unity 输入系统理念): 动作 -> 键名列表, 可重映射.
        # 脚本用 engine.get_action('动作') —— 改键不动脚本.
        self.actions = dict(DEFAULT_ACTIONS)
        try:
            self._load_action_bindings()
        except Exception:
            self.actions = dict(DEFAULT_ACTIONS)

        # ================ 鼠标状态 (编辑器 GUI/gizmo 用) ================
        self.mouse_pos = (0, 0)
        self.buttons = (0, 0, 0)        # 当前按住的鼠标键 (pygame.get_pressed)
        self.pressed = set()            # 本帧新按下 (键码集合)
        self.released = set()           # 本帧新松开 (键码集合)
        self.mouse_wheel = 0            # 本帧滚轮 (ev.y, 上正下负)
        self.mouse_press_pos = {}       # 键码 -> 按下时坐标 (0/1/2)
        self._mods = 0                  # 本帧键盘修饰键 (pygame.key.get_mods)
        self.gui_dirty = True           # 异步GUI: 面板 FBO 需要重绘 (初始 True 保证首帧就渲)

        # ================ 并行/CPU 亲和性 (2026-08-14 多核优化) ================
        # 设置来自 设置.json (parallel_enable/script_cores/show_grid), 见 guiloader.
        # parallel: CPU 拓扑+亲和性策略 (parallel.get_parallel 单例); _script_runner:
        # 脚本专用线程 (固定绑预留大核, 同步模型); _collision_pool: 碰撞检测线程池
        # (自适应, 场景大才启用); _frame_world: 当帧批量世界矩阵 (阴影/主 pass 共享).
        self.parallel_enable = True
        self.script_cores = 2
        self.show_grid = True
        self.parallel = None
        self._script_runner = None
        self._collision_pool = None
        self._frame_pool = None
        self._main_core_sched = None
        self._sched_pool = None            # 调度重构期1: nogil 常驻工作池
        self._sched_pool_built = False     # 建池成功标志 (LOOM_NO_SCHED/建失败=None)      # 2026-08-15: 主线程锁负载最低大核调度器
        self._frame_world = None
        self._light_vps = {}              # 每帧阴影 view-proj 缓存 (shadow pass 与 upload 复用)
        self._bb_cache = {}               # 网格齐次顶点缓存 (get_bounding_box 热路径)
        self._aabb_staging = None         # spin 治理 (2026-08-31): 堆叠缓冲 thread-local 缓存 (惰性建)
        self._stage_times = {}            # LOOM_PROFILE=1 时逐阶段耗时 (诊断用)
        # ★M3 (2026-09-09) 主线程分段归因插桩: 调用计数 + 帧计数 (per-frame 归一化).
        #   原 _stage_times 只有累计 ms 且用 time.time() (Windows 粒度 ~15.6ms),
        #   ms 级分段不可用 → M2 主线程归因只能"推断" (见 M2b主线程归因 §5).
        self._stage_calls = {}            # 阶段名 -> 调用次数
        self._stage_frames = 0            # render() 帧计数 (per-frame 分母)
        try:
            import guiloader
            _s = guiloader.load_settings('loom')
            self.parallel_enable = bool(_s.get('parallel_enable', True))
            self.script_cores = max(0, min(8, int(_s.get('script_cores', 2))))
            self.show_grid = bool(_s.get('show_grid', True))
            self.gravity = float(_s.get('gravity', self.gravity))   # 2026-08-30: 可调重力
            # 分离批1 (2026-09-05): 逻辑帧/渲染帧分离时钟.
            # logic_fps<=0 = 旧绑死模式 (用户配置; ★B7b 2026-10-16 删 LOOM_NO_SPLIT 逃生门).
            self._split_enable = split_enabled(_s)
            self._clock = (clock_from_settings(_s) if self._split_enable
                           else None)
            if self._clock is not None:
                self._clock.on_logic_step.append(self._logic_frame)
                # 批5: 物理不再挂 on_physics_step (clock 已删该回调列表);
                # 物理子步由 _logic_frame 内循环驱动 (Unity fixed_dt 语义)
            # 分离批2: 插值状态 (prev/curr 快照); models 列表对象在
            # __init__ 时已是稳定引用; interp 的 ids 每逻辑帧重抓,
            # 不依赖列表对象身份
            self._interp = (InterpState(self.models)
                            if self._split_enable else None)
            self._render_world = None
            self._logic_steps = 0
            self._logic_gen = 0              # 批5: 逻辑帧计数 (prep 缓存失效键)
            self._prep_aabbs = None          # 批5: 逻辑帧 AABB 缓存
            self._prep_light_vps = None      # 批5: 逻辑帧光源 VP 缓存
            self._prep_pairs = None          # 批5: 逻辑帧碰撞对缓存
            self._prep_sig = None            # 批5: prep 缓存签名 (gen+stamp3+fw_id)
            self._disp_gen = -1              # 批5: 事件派发节流 (每逻辑帧一次)
            self._pipe_disabled = False      # 批6: 管线永久降级标志
            self._phys_pipe_sysfail = False  # B4c: 物理线程建失败 (系统极限工况标志)
            # 方案二 (2026-09-05): 插值模式 'interpolate'(默认)/'extrapolate'
            self._interp_mode = str(_s.get('interp_mode', 'interpolate'))
            # ★B7b (2026-10-16): 排错后门设置项 (原 LOOM_NO_FRUSTUM / LOOM_NO_PBR
            #   环境逃生门退役)。UI 暂不暴露, 手动改 设置.json 切换。
            self._frustum_cull = bool(_s.get('frustum_cull', True))
            self._pbr_enabled = bool(_s.get('pbr_enabled', True))
            # TPS 缓冲实验 (2026-09-06): 逻辑帧预取记账 (闸门 logic_fps>=30;
            # 深度 2; LOOM_NO_FRAMEBUF=1 逃生门). 挂在 clock 上供 advance 消费.
            from frame_buffer import FrameBufferLedger, RenderFrameBuffer
            _lf = float(_s.get('logic_fps', 30))
            self._frame_buf = FrameBufferLedger(
                max_depth=int(_s.get('frame_buffer_depth', 2)))
            self._frame_buf.configure(_s, _lf)
            if self._clock is not None:
                self._clock.frame_buffer = self._frame_buf
            # FPS 缓冲实验 (2026-09-06): 渲染帧预画 (闸门 fps>=60 且非无上限;
            # 由 Qt 宿主 _apply_fps_limit 时 configure, 引擎只持状态+GL 资源).
            self._render_buf = RenderFrameBuffer()
        except Exception:
            pass
        # 设置读取失败的兜底 (逃生门语义: 读不到设置 = 旧绑死模式不启用分离)
        self._split_enable = getattr(self, '_split_enable', False)
        self._clock = getattr(self, '_clock', None)
        self._interp = getattr(self, '_interp', None)
        self._render_world = getattr(self, '_render_world', None)
        self._logic_steps = getattr(self, '_logic_steps', 0)
        self._logic_gen = getattr(self, '_logic_gen', 0)
        self._prep_aabbs = getattr(self, '_prep_aabbs', None)
        self._prep_light_vps = getattr(self, '_prep_light_vps', None)
        self._prep_pairs = getattr(self, '_prep_pairs', None)
        # ★M3-N3 (2026-09-09): 逻辑帧专用线程 —— **默认开启** (主线程只做
        #   render/输入; 实测 paint_total 4.95→3.47 ms/帧, FPS 134→155, 帧抖动
        #   6.50→3.15, tps 仍 20.0)。逃生门 LOOM_LOGIC_SYNC=1 回主线程串行。
        self._logic_async = os.environ.get('LOOM_LOGIC_SYNC') != '1'
        # ★M3-N4: GIL 切换间隔 —— 异步逻辑线程持 GIL 时, 渲染线程最长要等
        #   默认 5ms 才拿到 GIL (实测渲染段整体慢 2×: interp 0.53→1.09 ms/帧,
        #   连 ctypes DLL 调用 0.167→0.31)。经 LOOM_SWITCH_INTERVAL 可调 (秒)。
        _si = os.environ.get('LOOM_SWITCH_INTERVAL')
        if _si:
            try:
                sys.setswitchinterval(float(_si))
            except Exception:
                pass
        self._logic_thread = None
        self._logic_stop = None
        self._prep_pub = None
        self._prep_sig = getattr(self, '_prep_sig', None)
        self._disp_gen = getattr(self, '_disp_gen', -1)
        self._pipe_disabled = getattr(self, '_pipe_disabled', False)
        self._phys_pipe_sysfail = getattr(self, '_phys_pipe_sysfail', False)  # B4c
        self._interp_mode = getattr(self, '_interp_mode', 'interpolate')
        self._frustum_cull = getattr(self, '_frustum_cull', True)   # B7b 排错后门
        self._pbr_enabled = getattr(self, '_pbr_enabled', True)     # B7b 排错后门
        self._frame_buf = getattr(self, '_frame_buf', None)   # TPS 缓冲记账 (可 None)
        self._render_buf = getattr(self, '_render_buf', None)  # FPS 缓冲预画 (可 None)
        self._tps_events = getattr(self, '_tps_events', [])
        self._aabb_row_cache = getattr(self, '_aabb_row_cache', None)
        self._aabb_shadow_rows = getattr(self, '_aabb_shadow_rows', None)
        self._aabb_shadow_gen = getattr(self, '_aabb_shadow_gen', None)
        self._phys_pipe = None            # 分离批4: 常驻物理线程 (桥建后启动)
        self._tps_events = []             # 分离批5: TPS 实测滑动窗口 (逻辑帧时间戳)
        self._aabb_row_cache = None       # 批5: AABB 行级指纹缓存 (id(fw)+stamp 键)
        self._aabb_shadow_rows = None     # shadow_prep 直通行表 (2026-09-07, 与 out id 配对)
        self._aabb_shadow_gen = None      # 配对守卫 (id(out), n)
        # LOOM_NO_PARALLEL=1 测试守卫: 测试确定性, 不建脚本线程/不设进程亲和性
        if self.parallel_enable and os.environ.get('LOOM_NO_PARALLEL') != '1':
            try:
                from parallel import (get_parallel, ScriptRunner, FramePool,
                                      frame_workers, MainThreadCoreScheduler)
                self.parallel = get_parallel(self.script_cores)
                _m = (self.parallel.get('policy') or {}).get('script_mask')
                if _m:
                    self._script_runner = ScriptRunner(_m)
                # 每帧 CPU 预计算池 (2026-08-15 8 核均摊): 阴影 AABB/碰撞/矩阵分块丢这里,
                # numpy 释放 GIL -> 真并行; 主线程只做 GL/事件.
                _pol = self.parallel.get('policy') or {}
                _nw = frame_workers(_pol, target=8, script_cores=self.script_cores)
                _pm = _pol.get('pool_mask') or 0
                self._frame_pool = FramePool(_nw, _pm)
                # 2026-08-15 主线程核心调度: 重负载主线程锁到启动时负载最低的 P 核
                # (避开系统静态负载最高的核, 如 CPU1). 引擎本身负载高, 周期跳核会周期性
                # 卡顿 -> **只启动锁一次, 不做周期重选** (interval=0; LoomHub 才做 20s 重选).
                self._main_core_sched = None
                _topo = self.parallel.get('topology') or []
                if _topo:
                    self._main_core_sched = MainThreadCoreScheduler(
                        _topo, exclude_bits=_pol.get('script_mask') or 0,
                        interval=0.0)
                    _cb = self._main_core_sched.current_bit()
                    print("[parallel] 主线程锁定到负载最低的大核 #%s (启动锁一次, 不周期跳核)"
                          % ("?" if _cb is None else _cb))
                print("[parallel] 预计算池 %d worker (目标 8 核均摊, pool_mask=0x%X)"
                      % (_nw, _pm))
            except Exception as e:
                print("[parallel] 初始化失败, 回退单线程:", e)
                self.parallel = None
                self._script_runner = None
                self._frame_pool = None
                self._main_core_sched = None
        # ---- 调度重构期1 (2026-09-07): NgilPool nogil 常驻工作池 ----
        # 把逻辑帧 nogil 重段 (world_matrices 分块 numpy / aabbs 批) 外包出
        # 主线程, 与主线程 GL 提交真并行 (设计 §二2.2). 逃生门:
        #   LOOM_NO_SCHED=1  -> 池永不建 (逐位旧行为, A/B 基线);
        #   LOOM_SCHED_WORKERS=n -> worker 数覆盖 (默认 3).
        # 池故障 (超时/worker 异常) -> 永久降级串行 (run_batch 返回 False,
        # 调用方走旧路自愈, 不重试 — 任务书红线: 主线程 wait 恒带超时).
        self._sched_pool = None
        self._sched_pool_built = False
        if (os.environ.get('LOOM_NO_SCHED') != '1'
                and os.environ.get('LOOM_NO_PARALLEL') != '1'):
            try:
                _snw = int(os.environ.get('LOOM_SCHED_WORKERS', '3') or 3)
                _snw = max(2, min(4, _snw))
                self._sched_pool = NgilPool(n_workers=_snw, name='loom-sched')
                self._sched_pool_built = True
                print("[sched] NgilPool 就绪: %d worker (LOOM_NO_SCHED=1 旁路)"
                      % _snw)
            except Exception as e:
                self._sched_pool = None
                self._sched_pool_built = False
                print("[sched] NgilPool 建失败, 回退串行:", e)


    # ================ Layer / Tag 接口 (2026-10-18, 契约 §4) ================
    # 纯数据操作层: 校验与存储全部代理 layer_tag 模块; 撤销快照由调用方
    # (GUI commit_model / EAI _commit) 负责 —— 基座层不依赖编辑器概念.
    def tag_exists(self, tag):
        """标签是否已注册 (不区分大小写)."""
        import layer_tag
        return layer_tag.tag_exists(tag)

    def layer_name(self, layer_id):
        """层编号 -> 层名 (未命名/越界返回空串)."""
        import layer_tag
        return layer_tag.layer_name(layer_id)

    def layer_id(self, name):
        """层名 -> 层编号 (找不到返回 -1)."""
        import layer_tag
        return layer_tag.layer_id(name)

    def register_tag(self, tag):
        """注册新标签 (幂等); 已存在返回 False, 非法抛 ValueError."""
        import layer_tag
        return layer_tag.register_tag(tag)

    def find_by_tag(self, tag):
        """查找所有指定标签的物体 (不区分大小写)."""
        low = str(tag).lower()
        return [m for m in self.models
                if getattr(m, 'tag', '').lower() == low]

    def set_object_layer(self, obj, layer_id):
        """设置物体层; 越界抛 ValueError (校验在 GameObject.layer setter)."""
        obj.layer = layer_id

    def set_object_tag(self, obj, tag):
        """设置物体标签; 未注册抛 TagNotRegisteredError (校验在 GameObject.tag setter)."""
        obj.tag = tag

    def _build_hud_quad(self):
        """单位 quad (2 三角形), HUD 文字纹理 + M33 运行时 UI 纯色矩形用"""
        quad = np.array([0, 0, 0, 0,  1, 0, 1, 0,  1, 1, 1, 1,
                         0, 0, 0, 0,  1, 1, 1, 1,  0, 1, 0, 1], dtype='f4')
        self._quad_vbo = self.ctx.buffer(quad.tobytes())
        self._quad_vao = self.ctx.vertex_array(
            self.hud_prog, [(self._quad_vbo, '2f 2f', 'in_pos', 'in_uv')])
        # 1x1 白色纹理: draw_screen_rect 用它 + u_color 画纯色矩形
        import numpy as _np
        self._hud_white_tex = self.ctx.texture(
            (1, 1), 4, _np.array([255, 255, 255, 255], dtype='u1').tobytes())
        self._hud_white_tex.filter = (moderngl.NEAREST, moderngl.NEAREST)

    def draw_lines(self, verts, colors, mode=moderngl.LINES, view_proj=None):
        """
        渲染世界空间折线 (逐顶点颜色). verts: (N,3), colors: (N,3) 或 (N,4) 0..1.
        用独立 line 着色器 (不光照, 不深度).
        D10 (2026-08-30) 缓冲复用: VBO/VAO 持久缓存 (容量按需生长重建), 每帧
        6+ 次调用 (gizmo/图标/选中框) 不再逐次建+毁 GL 对象 (旧实现每次
        ctx.buffer+vertex_array+双 release 的 GL churn); 字节布局/着色器/渲染
        语义逐位不变 ('3f 4f' 交错, 同 program, 同 uniform, render vertices=N).
        """
        if mode == moderngl.LINES:
            # 2026-08-18 关键修复: Qt 外部模式下 moderngl scope 的 C 层会把
            # GL_LINE_WIDTH 破坏为 0 (pygame 模式正常) -> scope 内 LINES 线宽 0
            # 光栅化失败, 网格/选中框等一切线全部不可见 (空场景黑屏 + 网格闪烁根因).
            # 每次画线前显式重设线宽, 与 scope 内外无关; pygame 模式无副作用.
            try:
                self.ctx.line_width = 2.0
            except Exception:
                pass
        # 2026-08-18: 外部模式绘制前绑定缓存 widget FBO (scope 退出会把绑定
        # 破坏成 0, 无 scope 的调用直接画会画到 0 不可见). pygame 模式绑定
        # ctx.screen 无副作用.
        if getattr(self, '_external_ctx', False):
            self._screen_fb().use()
        if not hasattr(self, '_line_prog'):
            self._line_prog = self.ctx.program(vertex_shader=_LINE_VERT,
                                               fragment_shader=_LINE_FRAG)
        vp = view_proj if view_proj is not None else self._vp
        verts = np.asarray(verts, dtype='f4')
        colors = np.asarray(colors, dtype='f4')
        if colors.shape[1] == 3:
            colors = np.concatenate([colors, np.ones((colors.shape[0], 1), dtype='f4')],
                                    axis=1)
        packed = np.ascontiguousarray(
            np.concatenate([verts, colors], axis=1), dtype='f4')     # (N,7)
        # D10: 持久 VBO/VAO (容量生长; 换缓冲必须重建 VAO — moderngl VAO 绑定
        # 缓冲对象). 测试桩无 _line_vbo 属性时惰性建. 余量区旧字节无害:
        # render(vertices=N) 只读前 N 个顶点.
        n_bytes = packed.nbytes
        vbo = getattr(self, '_line_vbo', None)
        if vbo is None or vbo.size < n_bytes:
            if vbo is not None:
                try:
                    vbo.release()
                except Exception:
                    pass
            cap = max(4096, 2 * n_bytes)               # 初量 4KB, 生长 2x
            vbo = self.ctx.buffer(reserve=cap, dynamic=True)
            self._line_vbo = vbo
            self._line_vao = None                      # 换缓冲 -> VAO 必重建
        vbo.write(packed.tobytes())
        vao = getattr(self, '_line_vao', None)
        if vao is None:
            vao = self._line_vao = self.ctx.vertex_array(
                self._line_prog, [(vbo, '3f 4f', 'in_pos', 'in_color')])
        # 组6件3: line program uniform 句柄缓存 + write 直吃 f4 数组 (消 tobytes 拷贝)
        if not hasattr(self, '_line_u_vp'):
            self._line_u_vp = self._line_prog['u_view_proj']
        self._line_u_vp.write(np.asarray(vp, dtype='f4'))
        vao.render(mode, vertices=len(packed))





    # ================ 碰撞系统 (M28) + 刚体物理 (M31) ================
    # 已抽出到 loom_physics.PhysicsMixin (见类定义继承)

    # ============ update_audio / update_animations / _call_collision_cb ============
    # 已抽出到 loom_frame_components.FrameComponentMixin



    # ================ 输入动作层 (M30b) → loom_input.InputMixin ================
    # _key_pressed/is_key/sync_script_keys/get_action/set_mouse_locked/
    # _apply_mouse_lock/toggle_mouse_locked/set_ui_capture_mouse/
    # _action_bindings_file/_load_action_bindings/save_action_bindings/
    # rebind_action 已抽出到 loom_input.InputMixin (见类定义继承).

    # ================ 脚本系统 (M27) ================
    def update_scripts(self, delta_time):
        """播放期每帧调用: 遍历物体上所有脚本组件 (M25: 可多个), 惰性实例化并 update.
        优化 (2026-10-01): 快速早退与活跃脚本过滤 —— 场景无脚本时 0 迭代直接退出，
        消灭 500+ 物体每帧在解释器内的 O(N) 线性盲目轮询与属性查找。
        ★M4 DLL 并网: 集成 script.dll 原生批处理 (batch_rotate),
        将纯几何自转脚本通过单次 C 原生调用完成 SIMD 批量计算,
        消除 100+ 旋转脚本逐物体进入 Python 反射与 Point3D 实例化开销。
        ★B3 退役 (2026-10-16): 删 use_c 逃生门 + batch_move 死代码 (无对应脚本);
        script.dll 官方件缺失硬 raise。"""
        models = self.models
        if not models:
            return
        has_scripts = getattr(self, '_has_scripts_cached', None)
        struct_gen = getattr(self, '_struct_gen', 0)
        cache_gen = getattr(self, '_has_scripts_gen', -1)
        if cache_gen != struct_gen:
            has_scripts = any(bool(m.scripts) for m in models)
            self._has_scripts_cached = has_scripts
            self._has_scripts_gen = struct_gen
        if not has_scripts:
            return

        from scripts import get_script
        import script_glue as _sg
        _sg.handle()   # ★B3: 官方件缺失硬 raise (不再有 use_c 逃生门)

        rot_items = []
        generic_items = []

        for m in models:
            if not m.scripts:
                continue
            for sc in m.scripts:              # 组2: 引用迭代 (旧 list() 每物体每帧复制;
                                              # 契约: update 不增删本物体脚本组件)
                if not sc.script_id:
                    sc._script = None
                    sc._script_broken = False
                    continue
                if sc._script_broken:
                    continue
                s = sc._script
                if s is None:
                    cls = get_script(sc.script_id)
                    if cls is None:
                        continue
                    s = cls()
                    s.obj = m
                    s.engine = self
                    for key, _label, default, *_ in cls.params:
                        if key in sc.script_vars:
                            s.vals[key] = sc.script_vars[key]
                    sc._script = s
                    try:
                        s.on_enable()   # C1: Unity 语义, on_enable 早于 on_start
                        s.on_start()
                    except Exception as e:
                        print("[脚本] %s.on_enable/on_start 出错: %r" % (m.name, e))
                        sc._script = None
                        sc._script_broken = True
                        continue

                # M4 C 批处理分流: rotate 走 C 原生批处理, 其余走通用 update
                # ★B3 退役: 删 use_c 判断 + move/linear_move 分流 (死代码)
                if sc.script_id == 'rotate':
                    rot_items.append((m, sc, s))
                else:
                    generic_items.append((m, sc, s))

        # ① 纯 C 原生批量自转 (SIMD 加速, 消除 Python 反射与方法调用)
        if rot_items:
            valid_rot = []
            for m, sc, s in rot_items:
                try:
                    v = s.vals
                    sx = float(v.get('sx', 0.0))
                    sy = float(v.get('sy', 90.0))
                    sz = float(v.get('sz', 0.0))
                    r = m.rotation
                    valid_rot.append((m, sc, s, float(r.x), float(r.y), float(r.z), sx, sy, sz))
                except Exception as e:
                    print("[脚本] %s(rotate) 参数异常: %r" % (m.name, e))
                    sc._script = None
                    sc._script_broken = True

            n_rot = len(valid_rot)
            if n_rot > 0:
                rot_buf = getattr(self, '_script_rot_buf', None)
                if rot_buf is None or rot_buf.shape[0] < n_rot:
                    cap = max(64, n_rot, (rot_buf.shape[0] * 2) if rot_buf is not None else 0)
                    rot_buf = self._script_rot_buf = np.empty((cap, 3), dtype=np.float64)
                    self._script_speeds_buf = np.empty((cap, 3), dtype=np.float64)
                    self._script_out_rot_buf = np.empty((cap, 3), dtype=np.float64)
                speeds_buf = self._script_speeds_buf
                out_rot_buf = self._script_out_rot_buf

                for i, (m, sc, s, rx, ry, rz, sx, sy, sz) in enumerate(valid_rot):
                    rot_buf[i, 0] = rx
                    rot_buf[i, 1] = ry
                    rot_buf[i, 2] = rz
                    speeds_buf[i, 0] = sx
                    speeds_buf[i, 1] = sy
                    speeds_buf[i, 2] = sz

                # ★B3: batch_rotate 失败已由 glue 硬 raise (无回退分支)
                c_out = _sg.batch_rotate(rot_buf[:n_rot], speeds_buf[:n_rot], delta_time, out_rot=out_rot_buf[:n_rot])
                for i, (m, sc, s, *_) in enumerate(valid_rot):
                    m.rotation = Point3D(float(c_out[i, 0]), float(c_out[i, 1]), float(c_out[i, 2]))

        # ② 通用 Python 脚本逐个调度
        # ★B3 退役: 删 batch_move 死代码段 (engine 的 move/linear_move 分流从未被触发)
        for m, sc, s in generic_items:
            try:
                s.update(delta_time)
            except Exception as e:
                print("[脚本] %s(%s) 出错: %r" % (m.name, sc.script_id, e))
                sc._script = None
                sc._script_broken = True

    # ================ 分离批1: 逻辑帧/渲染帧分离 (批5 重对齐) ================
    def _logic_frame(self, fixed_dt):
        """一个逻辑步 = 整个场景的最高同步点 (批5 架构裁决). 帧内段次序
        (与旧绑死模式 render() 四段同序, R3 数值路径零改动):
          [脚本] → [物理子步 ×N (N=clock.sub_steps, dt 恒 sub_dt)] →
          [音频] → [动画] → [逻辑帧 prep: AABB/光源VP/碰撞对] →
          [事件派发] → [插值翻页].
        物理**不再是**独立 accumulator 回调 — Unity 模型: 物理在逻辑帧内
        自动子步, fixed_dt 一个时钟 (批5 删除双 accumulator)."""
        _t = self._prof_t0()
        self._run_scripts(fixed_dt)
        self._prof_add('mt_scripts', _t)
        clk = getattr(self, '_clock', None)
        sdt = clk.sub_dt if clk is not None else fixed_dt
        nsub = clk.sub_steps if clk is not None else 1
        pipe = getattr(self, '_phys_pipe', None)
        # ★B4c 退役 (2026-10-16): 删 LOOM_NO_PIPE 逃生门 (pipe is not None 已涵盖
        # "线程未建" 情况; 删 env 判断不动降级语义)。
        pipe_ok = (pipe is not None and not pipe._degraded
                   and not getattr(self, '_pipe_disabled', False)
                   and getattr(self, '_phys_bridge', None) is not None)
        if pipe_ok:
            # 批6 流水线: 连发 N 子步指令 (不等待) → 音频/动画与物理并行
            # → S1 同步点等物理 → prep (物理回读后位形)
            g = getattr(self, 'gravity', self._GRAVITY)
            _t = self._prof_t0()
            for _ in range(nsub):
                self._pipe_post(pipe, sdt, g)
            self._prof_add('mt_pipe_post', _t)
            _t = self._prof_t0()
            self.update_audio(fixed_dt)
            self.update_animations(fixed_dt)
            self._prof_add('mt_audio_anim', _t)
            try:
                self._profile('pipe_wait', lambda: pipe.wait_pending())
            except Exception as e:
                print("[物理] 管线异常 (%r) -> 降级主线程直跑" % (e,))
                self._stop_phys_pipe()
                self._pipe_disabled = True
            _t = self._prof_t0()
            self._logic_prep(fixed_dt)
            self._prof_add('mt_logic_prep', _t)
        else:
            # 无管线: 串行子步 (legacy/降级/NO_PIPE 路径)
            _t = self._prof_t0()
            for _ in range(nsub):
                self._physics_frame(sdt)
            self._prof_add('mt_physics_serial', _t)
            _t = self._prof_t0()
            self.update_audio(fixed_dt)
            self.update_animations(fixed_dt)
            self._prof_add('mt_audio_anim', _t)
            _t = self._prof_t0()
            self._logic_prep(fixed_dt)
            self._prof_add('mt_logic_prep', _t)
        # 碰撞事件派发 (消费 _prep_pairs; 每逻辑帧一次)
        if getattr(self, 'is_playing', False) and self._prep_pairs is not None:
            _t = self._prof_t0()
            self._dispatch_collision_events(self._prep_pairs)
            self._prof_add('mt_dispatch', _t)
        # 插值层翻页: prev=curr, curr=新快照 (分离批2; 逻辑帧收口同步点)
        it = getattr(self, '_interp', None)
        if it is not None:
            _t = self._prof_t0()
            snap = getattr(self, '_soa_snap', None)
            planes = (snap[2], snap[3], snap[4]) if (snap is not None and len(snap) >= 5) else None
            it.advance(planes)
            self._prof_add('mt_interp_advance', _t)
        self._logic_gen += 1             # 批5: prep 缓存失效键 bump

    def _pipe_post(self, pipe, sdt, g):
        """批6: 段B 指令投递 (异常降级: 本帧起主线程直跑, 游戏不崩)."""
        try:
            pipe.post(self.models, sdt, g, False)
        except Exception as e:
            print("[物理] 管线提交异常 (%r) -> 降级主线程直跑" % (e,))
            self._stop_phys_pipe()
            self._pipe_disabled = True

    def _physics_frame(self, phys_dt):
        """一个物理子步: update_physics 原样 (桥三段 pre→step→post 或
        legacy, R1 红线: 本方法只改"调用时机与 dt", 桥内一行不动).
        批5 起由 _logic_frame 子步循环调用 (不再挂 clock.on_physics_step)."""
        self.update_physics(phys_dt, events=False)

    def _logic_prep(self, fixed_dt):
        """批5: 逻辑帧尾 prep — AABB / 光源 VP / 碰撞对 一次算好缓存
        (Panda3D 段C: 物理后依赖段; 批6 起与物理子步流水线重叠).
        结构/外观 stamp 不变且逻辑帧没跑过 → 直接复用 (静止零开销)."""
        models = self.models
        n = len(models)
        stamp3 = (getattr(self, '_struct_gen', 0), GameObject._appearance_gen)
        sig = (self._logic_gen, stamp3,
               id(getattr(self, '_frame_world', None)))
        # 逻辑帧跑了 (gen 变) 或结构/外观变 → 重算; 否则跳过
        if self._prep_sig == sig and self._prep_aabbs is not None:
            return
        # 逻辑矩阵: 用/建 _frame_world (静止帧 _fw_cache 命中 ~0ms)
        fw = getattr(self, '_frame_world', None)
        if fw is None or fw.shape[0] != n:
            fw = self._profile(
                'world_matrices', lambda: self.compute_world_matrices(models))
            self._frame_world = fw
        # ① 全量 AABB (visible_only=False 阴影碰撞共享)
        self._prep_aabbs = self._profile(
            'aabbs', lambda: self._model_aabbs_par(models, fw,
                                                   visible_only=False))
        # ② 光源 VP
        self._prep_light_vps = self._profile(
            'shadow_bounds', lambda: self._compute_light_vps(self._prep_aabbs))
        # ③ 碰撞对 (只读检测; 派发在 _logic_frame 尾部主线程)
        pool = getattr(self, '_frame_pool', None)
        if (pool is not None and n >= self._COLLISION_PAR_THRESHOLD
                and getattr(self, 'is_playing', False)):
            self._prep_pairs = self._profile(
                'collide_pairs',
                lambda: self._collision_pairs_parallel(aabbs=self._prep_aabbs))
        else:
            self._prep_pairs = []
        self._prep_sig = sig
        self._light_vps = self._prep_light_vps   # 渲染帧消费面不变

    def _ensure_split(self):
        """惰性初始化分离态 (测试桩 __new__ 路径兜底: __init__ 未跑时
        按默认 30/60 建时钟; 返回 None = 分离未启用)."""
        enable = getattr(self, '_split_enable', False)
        clock = getattr(self, '_clock', None)
        if clock is None and enable:
            clock = self._clock = clock_from_settings(
                {'logic_fps': 30, 'physics_fps': 60})
            clock.on_logic_step.append(self._logic_frame)
        return clock

    def _framebuf_prefetch(self, frame_start):
        """TPS 缓冲 (2026-09-06): 渲染帧尾预取决策+执行. frame_start=本渲染帧
        开始墙钟 (预算计算). 富余且 accumulator 有到期未来帧 → 提前跑一个
        逻辑帧 (产物落引擎既有 _prep_*/interp 缓存), 记账待 advance 消费.
        预取帧不派发碰撞事件 (派发在 _parallel_shadow_and_collision 按
        _disp_gen 节流, 预取帧的 pairs 留到所属渲染帧 — 与旧序一致)."""
        led = getattr(self, '_frame_buf', None)
        clk = getattr(self, '_clock', None)
        if led is None or clk is None or not led.enabled:
            return
        if not self.is_playing or getattr(self, '_logic_paused', False):
            return
        if led.should_prefetch(time.perf_counter() - frame_start):
            # 预取一个逻辑帧: 复用 _logic_frame (脚本/物理/prep 全套),
            # 但事件派发与插值翻页在其内部照常执行 — 与正常帧唯一差异是
            # "提前了" (时间轴语义不变: advance 时该帧不再重跑).
            self._logic_frame(clk.fixed_dt)
            led.record_prefetch()

    def advance_logic(self, render_dt):
        """分离批3 兼容入口: 宿主 (编辑器 paintGL) 渲染帧先调本方法推进时钟,
        再调 render() 只画不推进 (render 内检测 _advanced_this_frame 跳过).
        ★is_playing=False (编辑态/暂停): 零逻辑 — 渲染帧照跑, alpha=0 (守旧).
        ★_logic_paused (F9, MC 同款暂停世界): 渲染帧照跑但时钟冻结 (alpha=0);
          F10 步进在暂停态下强制走 1 个逻辑帧 (step_logic_once).
        分离未开 = 零操作 (render 内走旧绑死分支)."""
        if not getattr(self, 'is_playing', True):
            self._advanced_this_frame = True   # 编辑态: render 不再推进
            it = getattr(self, '_interp', None)
            if it is not None:
                it.alpha = 0.0
            return
        clk = self._ensure_split()
        if clk is not None:
            # ★M3-N3 修正 (2026-09-09 晚): 异步逻辑线程**仅限 Qt 宿主编辑器**
            #   (_external_ctx=True)。无头探针/测试直驱 advance_logic 时若也起
            #   线程, 会与调用方双驱逻辑帧 + 物理管线 → 同步超时 + IndexError
            #   (collide_val_check 回归抓到)。探针/测试一律走同步旧路径。
            if self._logic_async and getattr(self, '_external_ctx', False):
                # ★M3-N3: 逻辑工作 (脚本/等物理/prep/翻页) 由 _logic_loop 承担;
                # 主线程只同步插值相位并标记"本帧已推进" (防 render 重复推进)。
                self._start_logic_thread(clk)
                it = getattr(self, '_interp', None)
                if it is not None and not getattr(self, '_logic_paused', False):
                    it.alpha = clk.alpha
                self._advanced_this_frame = True
                return
            if getattr(self, '_logic_paused', False):
                if not getattr(self, '_step_requested', False):
                    # 暂停且无步进请求: 本渲染帧零逻辑 (世界冻结), 渲染照跑
                    self._advanced_this_frame = True
                    it = getattr(self, '_interp', None)
                    if it is not None:
                        it.alpha = 0.0
                    return
                # F10 步进: 强制恰好 1 逻辑帧 (不管 accumulator — 直注 fixed_dt
                # 后排干; MC "播放一帧 TPS" 同款)
                self._step_requested = False
                self._profile('logic_step', lambda: clk.step_once())
                self._logic_steps = clk.steps
                self._advanced_this_frame = True
                it = getattr(self, '_interp', None)
                if it is not None:
                    it.alpha = clk.alpha
                return
            self._profile('logic_step',
                          lambda: clk.advance(render_dt))
            self._logic_steps = clk.steps            # HUD/对拍用
            self._advanced_this_frame = True
            it = getattr(self, '_interp', None)
            if it is not None:
                it.alpha = clk.alpha                 # 时钟 -> 插值层
        else:
            # 逃生门 (NO_SPLIT/logic_fps<=0): 旧绑死四行 (诊断报告 §四 必修 —
            # 缺此分支 = NO_SPLIT 编辑器播放态逻辑全丢, 场景静止+假高帧率).
            # 与 engine.render 逃生门分支逐字一致 (A/B 基线逐位).
            self._run_scripts(render_dt)
            self._profile('physics',
                          lambda: self.update_physics(render_dt, events=False))
            self.update_audio(render_dt)
            self.update_animations(render_dt)
            self._advanced_this_frame = True

    def toggle_logic_paused(self):
        """暂停/恢复逻辑时钟 (F9, MC 同款暂停世界 TPS): 渲染帧照跑
        (开发者相机/交互不受影响 — 批5 独立性), 逻辑帧冻结; F10 步进生效.
        分离未开 (旧绑死模式) = 无暂停语义 (返回 False 不生效)."""
        if not getattr(self, 'is_playing', False):
            return False
        if self._ensure_split() is None:
            return False
        self._logic_paused = not getattr(self, '_logic_paused', False)
        if self._logic_paused:
            # 暂停边界: 清 accumulator 余量 (恢复时从整拍开始, 不补暂停期欠账)
            self._clock.reset()
            it = getattr(self, '_interp', None)
            if it is not None:
                it.align()
            self._render_world = None
        return self._logic_paused

    def step_logic_once(self):
        """步进 1 逻辑帧 (F10, MC 同款): 仅暂停态生效 — 置请求标志,
        下一渲染帧 advance_logic 消费 (恰好 1 逻辑帧后继续冻结)."""
        if not getattr(self, '_logic_paused', False):
            return False
        self._step_requested = True
        return True

    def get_tps(self):
        """实测 TPS (逻辑帧/秒, 2 秒滑动窗口; 状态栏直读). 暂停时 → 0."""
        if not self._tps_events:
            return 0.0
        now = time.time()
        n = len(self._tps_events)
        span = now - self._tps_events[0]
        if span <= 0.01:
            return 0.0
        return n / span

    def _run_scripts(self, dt):
        """脚本更新分发 (2026-08-14 多核优化): 有专用脚本线程则交给它 (同步等待),
        否则内联 (测试直调 update_scripts / 未启用并行 时行为零变化)."""
        # 批5: TPS 实测 (逻辑帧/秒滑动窗口, 状态栏显示 — 用户直读"逻辑时钟
        # 到底在不在走/能不能停下")
        now = time.time()
        self._tps_events.append(now)
        cutoff = now - 2.0
        while self._tps_events and self._tps_events[0] < cutoff:
            self._tps_events.pop(0)
        runner = getattr(self, '_script_runner', None)
        if runner is None:
            self.update_scripts(dt)
            return
        try:
            runner.run_frame(self.update_scripts, dt)
        except BaseException:
            # 脚本线程异常/死亡: 回退内联, 游戏不崩 (本帧脚本照跑)
            self.update_scripts(dt)


    def _stop_parallel(self):
        """退出清理 (run 循环结束调): 停脚本线程 + 关闭碰撞/预计算线程池. 幂等.
        B1: 物理桥销毁 (Jolt 世界只存活播放/运行期; 幂等, 未建桥时 no-op).
        期1 (2026-09-07): NgilPool 一并停 (shutdown 幂等, 降级态 no-op 安全).
        ★M3-N3: 逻辑线程一并停 (LOOM_LOGIC_ASYNC=1 时才存在)。"""
        self._stop_logic_thread()
        self._destroy_phys_bridge()
        sp = getattr(self, '_sched_pool', None)
        if sp is not None:
            try:
                sp.shutdown()
            except Exception:
                pass
            self._sched_pool = None
        try:
            sr = getattr(self, '_script_runner', None)
            if sr is not None:
                sr.stop()
                self._script_runner = None
        except Exception:
            pass
        for name in ('_collision_pool', '_frame_pool'):
            pool = getattr(self, name, None)
            if pool is not None:
                try:
                    pool.shutdown(wait=False)
                except Exception:
                    pass
                setattr(self, name, None)
        sched = getattr(self, '_main_core_sched', None)
        if sched is not None:
            try:
                sched.stop()
            except Exception:
                pass
            self._main_core_sched = None







