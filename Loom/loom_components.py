# -*- coding: utf-8 -*-
"""loom_components.py — 组件化 (M25) 与资产类。

原属 engine.py（"组件化 (M25): 组合优于继承" 段，含 Component 家族 +
AnimationClip / AnimatorComponent / AudioSystem）。依赖：
  - loom_types.Point3D
  - loom_material.Material
  - numpy（AnimationClip 快路径）
  - audio_backend（AudioSystem 惰性 import）
engine.py 通过 `from loom_components import *` 重导出所有组件类。
"""

import math

import numpy as np

from loom_types import Point3D
from loom_material import Material


# ================ 组件化 (M25): 组合优于继承 ================
# Unity 哲学: GameObject 是最空的容器, 行为全来自挂上去的组件.
# 这里 GameObject = 容器, 组件列表决定它"能干嘛". 一个物体可挂多个脚本.
class Component:
    """组件基类: 挂在 GameObject 上的数据/行为块 (M25).
    owner 反查宿主物体. 子类各自持有自己的数据, 互不干扰."""

    ctype = 'component'

    def __init__(self):
        self.owner = None      # 宿主 GameObject


class TransformComponent(Component):
    """变换组件: 位置/旋转/缩放 + 父子层次 (对应 Unity 的 Transform 组件).
    ctype = 'transform'."""
    ctype = 'transform'

    # 变换代数 (类级, 2026-09-06 编辑态插值失同步修复): 任何 position/rotation/
    # scale 写入都 bump。渲染循环 (编辑态) 检测代数变化 -> 插值快照对齐
    # (_interp.align) + 渲染矩阵失效 —— 修"拖动物体黄框走了画面物体不动"
    # (插值快照 prev==curr 恒成立, 不知道物体本体在快照外被改)。
    _xform_gen = 0

    def __init__(self, position, rotation, scale=(1.0, 1.0, 1.0)):
        super().__init__()
        self._position = Point3D(*position)
        self._rotation = Point3D(*rotation)
        self._scale = tuple(scale if scale is not None else (1.0, 1.0, 1.0))
        self.parent = None
        self.children = []

    # ---- position/rotation/scale property (写入 bump _xform_gen) ----
    @property
    def position(self):
        return self._position
    @position.setter
    def position(self, v):
        self._position = v if isinstance(v, Point3D) else Point3D(*v)
        TransformComponent._xform_gen += 1
    @property
    def rotation(self):
        return self._rotation
    @rotation.setter
    def rotation(self, v):
        self._rotation = v if isinstance(v, Point3D) else Point3D(*v)
        TransformComponent._xform_gen += 1
    @property
    def scale(self):
        return self._scale
    @scale.setter
    def scale(self, v):
        self._scale = tuple(v)
        TransformComponent._xform_gen += 1


class MeshRendererComponent(Component):
    """网格渲染组件: 网格 + 材质引用 + 法线模式 + 可见性 (M23 材质资产化).
    颜色/饱和度移到共享 Material 上 —— 多个物体引用同一材质, 改一处全变."""
    ctype = 'mesh_renderer'

    def __init__(self, mesh, color=None, normal_mode='flat', primitive=None,
                 params=None, saturation=1.0, visible=True, material=None):
        super().__init__()
        self.mesh = mesh
        # 材质 (M23): 默认自建一个 (color/saturation 为该材质初值);
        # 传入 material 则共享引用 (多个物体指向同一材质).
        self.material = material if material is not None else Material(color=color,
                                                                      saturation=saturation)
        self.normal_mode = normal_mode           # 'flat' 面法线 | 'vertex' 顶点径向
        self.primitive = primitive               # 基元类型 'cube'/'sphere'/'plane'/None
        self.params = params                     # 基元参数 (尺寸等, 序列化用)
        self.visible = visible
        # M36 LOD (2026-10-14): 距离分级网格 [(max_dist, mesh), ...] 升序;
        # None=无 LOD (零开销). 引擎 _update_lod 按相机距离切换 renderer.mesh。
        self.lod_levels = None
        # M36 LOD 屏幕占比模式 (对标 Unity LODGroup.screenRelativeTransitionHeight):
        # [(屏幕占比阈值, mesh), ...] 降序 (高精度阈值大); 更准确 (大物体远处仍高精度)。
        self.lod_screen_levels = None
        self.lod_bias = 1.0                      # LOD 偏移 (对标 Unity lodBias; >1 更早降级)
        self._lod_cur = None                     # 上次 LOD 选中的 mesh (防每帧重复切换)
        self._lod_radius = None                  # 缓存包围球半径 (屏幕占比用)


class ScriptComponent(Component):
    """脚本组件 (M27 -> M25): 一个脚本挂载, 物体可有多个.
    script_id = scripts.SCRIPTS 的键; script_vars = 参数覆盖;
    _script/_script_broken 是播放期运行态 (编辑/非播放期不实例化)."""
    ctype = 'script'

    def __init__(self, script_id=None, script_vars=None):
        super().__init__()
        self.script_id = script_id
        self.script_vars = dict(script_vars or {})
        self._script = None
        self._script_broken = False


class ColliderComponent(Component):
    """碰撞体组件 (M28): 给物体一个"物理碰撞体积", 决定它挡不挡别人/被不被挡.
    shape: 'box'   AABB 盒 (立方体/平面等, 取世界包围盒)
           'sphere' 球体 (球体网格自动用这个, 比 AABB 更贴合)
           'none'   无碰撞 (纯装饰, 谁都不挡)
    enabled: False = 暂时关闭 (不参与碰撞检测).
    碰撞是"世界空间"概念: 组件只存形状开关, 每帧按当前变换实时算世界体积,
    父链移动子物体也会正确挡住别人 (get_bounding_box 已沿父链合成)."""
    ctype = 'collider'

    def __init__(self, shape='box', enabled=True, friction=0.5, restitution=0.0,
                 rolling_friction=0.1, is_trigger=False):
        super().__init__()
        self.shape = shape
        self.enabled = bool(enabled)
        # B1 (2026-08-30): 接触材质参数 (阿蒙东-库仑 f=μN, 接触面积无关):
        # 摩擦系数 friction (0=冰面, 越大越涩) / 弹性 restitution (0=不回弹)。
        # 静态/运动学体 (无刚体) 的碰撞面材质走这里; 动态体走 RigidbodyComponent.
        # pair 有效值 = Jolt 几何平均 sqrt(μ1*μ2) (默认组合模式).
        self.friction = float(friction)
        self.restitution = float(restitution)
        # B1-P1 (2026-08-30): 滚动摩擦系数 (0=关闭, 默认 0.1, 范围 0-3);
        # culverin 0.14.0 无原生滚动阻尼 -> 桥内按 f = max(0, 1 - μ·rolling·K·dt)
        # 指数衰减 ω/水平线速度 (仅动态体清醒时)。与摩擦/弹性同控制组。
        self.rolling_friction = float(rolling_friction)
        # 2026-10-18 阶段1档序17 Trigger (路线见 docs/design/功能补全5档施工路线图 §2.7):
        # is_trigger=True 时: 物理层传 is_sensor (Culverin 不产生接触力, 可重叠穿过);
        # 事件层派发 on_trigger_* 而非 on_collision_*（详见 loom_physics 事件分流）.
        # 语义对齐 Unity Collider.isTrigger: 任一方为 trigger 即走触发事件路径.
        self.is_trigger = bool(is_trigger)


class RigidbodyComponent(Component):
    """刚体组件 (M31, Unity Rigidbody 理念): 给物体速度/重力, 引擎每帧按速度带碰撞移动.
    mass          质量 (暂用于未来冲量, 目前不参与响应)
    use_gravity   是否受重力 (默认 true, 沿 -Y)
    is_kinematic  运动学: true = 由脚本/动画控制 (不被重力/碰撞响应推), false = 动态
    velocity      世界速度 (m/s), 每帧 position += velocity*dt (带碰撞, 被挡停)
    注意: 刚体需配合 ColliderComponent 才有碰撞体积; 同树物体仍不互撞.
    运行时状态 (velocity/_colliding) 不序列化, 播放快照自动覆盖."""
    ctype = 'rigidbody'

    def __init__(self, mass=1.0, use_gravity=True, is_kinematic=False,
                 friction=0.5, restitution=0.0, rolling_friction=0.1):
        super().__init__()
        self.mass = float(mass)
        self.use_gravity = bool(use_gravity)
        self.is_kinematic = bool(is_kinematic)
        # B1 (2026-08-30): 动态体接触材质 (阿蒙东-库仑): 摩擦系数/弹性
        # (桥 create_body 透传; pair 有效值 = Jolt 几何平均)。序列化/快照/检查器跟随.
        self.friction = float(friction)
        self.restitution = float(restitution)
        # B1-P1 (2026-08-30): 滚动摩擦系数 (0=关闭, 默认 0.1, 范围 0-3);
        # 桥内衰减 (见 ColliderComponent.rolling_friction 注释)。动态体用本值。
        self.rolling_friction = float(rolling_friction)
        self.velocity = Point3D(0.0, 0.0, 0.0)   # 世界速度 (m/s)
        self._colliding = set()                  # 当前碰撞对 (物体 id), 事件检测用


class AudioSourceComponent(Component):
    """音频源组件 (M34, Unity AudioSource 理念): 挂物体上播放音频文件.
    clip     音频文件路径 (wav/ogg 等 pygame.mixer 支持的格式)
    loop     是否循环播放 (音乐用 true, 音效用 false)
    volume   音量 0..1
    playing  是否播放 (脚本/检查器设, 引擎每帧按状态 play/stop)
    _key     运行时: 已播放的 (clip, playing) 标志 (不序列化, 播放状态变化才重播)"""
    ctype = 'audio'

    # 2026-10-18 3D 音频 (契约 3D音频系统契约_20261018.md):
    #   category 决定空间化行为 —— music 强制 2D (背景音乐不该有距离感),
    #   sfx/voice 走 3D (音源位置 + 距离衰减). 不存在独立 spatial 开关.
    _CATEGORIES = ('music', 'sfx', 'voice')

    def __init__(self, clip=None, loop=False, volume=1.0,
                 category='sfx', min_distance=1.0, max_distance=500.0,
                 rolloff=1.0):
        super().__init__()
        self.clip = clip
        self.loop = bool(loop)
        self.volume = float(volume)
        # 3D 字段 (setter 做静默回退; EAI 层单独校验并返回 error)
        self.category = category
        self.min_distance = min_distance
        self.max_distance = max_distance
        self.rolloff = rolloff
        self.playing = False
        self._key = None

    # ---- 3D 音频字段 (2026-10-18) ----
    @property
    def category(self):
        return self._category

    @category.setter
    def category(self, v):
        """非法值静默回退 'sfx' (契约 §10: 组件层回退, 场景加载/EAI 层另行警告/报错)."""
        s = str(v).strip().lower() if v is not None else 'sfx'
        self._category = s if s in self._CATEGORIES else 'sfx'

    @property
    def min_distance(self):
        return self._min_distance

    @min_distance.setter
    def min_distance(self, v):
        try:
            f = float(v)
        except (TypeError, ValueError):
            f = 1.0
        self._min_distance = f if f > 0 else 1.0

    @property
    def max_distance(self):
        return self._max_distance

    @max_distance.setter
    def max_distance(self, v):
        try:
            f = float(v)
        except (TypeError, ValueError):
            f = 500.0
        if f <= 0:
            f = 500.0
        lo = getattr(self, '_min_distance', 1.0)
        if f <= lo:                       # 必须严格大于 min_distance
            f = lo * 2.0
        self._max_distance = f

    @property
    def rolloff(self):
        return self._rolloff

    @rolloff.setter
    def rolloff(self, v):
        try:
            f = float(v)
        except (TypeError, ValueError):
            f = 1.0
        self._rolloff = f if f > 0 else 1.0

    def is_spatial(self):
        """是否走 3D 空间化 (契约 §2.2 唯一判定入口)."""
        return self._category in ('sfx', 'voice')


class AnimationClip:
    """动画剪辑 (M35, Unity AnimationClip 简化): 关键帧序列, 随时间插值变换.
    frames: [{ 'time': 秒, 'position': (x,y,z)|None, 'rotation': (rx,ry,rz)|None,
               'scale': (sx,sy,sz)|None }]  —— 缺省字段保持上一帧值.
    旋转为欧拉角弧度 (与 transform 一致). duration = 末帧 time.

    A6 numpy 化: frames 仍是原 dict 列表 (外部可读/可改/可序列化); 内部另建
    numpy 缓存 (_np_times (F,) f64 + 三通道 (F,3) f64), sample() 两条路径并存:
    快路径 = searchsorted 定段 + 向量化插值 + 转 Python float tuple, 仅当
    "F>=2 且时间非降序且 position/rotation/scale 全帧齐备且值可转 (F,3)" 才启用
    (缺任一前提整体走旧循环慢路径, 语义以旧实现为准, 逐位一致——含首段 t 早于
    首帧时间的负 f 外推、span<=0 时 f=0.0、末帧保持原对象). 缓存失效 (红线3):
    sample 入口 id(frames)+len 校验, 列表对象身份或长度变化即重建; 同长度原地
    改帧不在校验范围, 需调 _np_rebuild() 显式重建 (全工程现状无此用法)."""

    _CHANNELS = ('position', 'rotation', 'scale')

    def __init__(self, frames=None):
        self.frames = frames or []
        self._np_key = None      # (id(frames), len(frames)) 缓存失效校验
        self._np_fast = False    # True = sample 可走 numpy 快路径
        self._np_times = None    # (F,) f64 关键帧时间 (frames 列表序, 不重排)
        self._np_vals = None     # {'position'/'rotation'/'scale': (F,3) f64}
        self._np_rebuild()

    @property
    def duration(self):
        return self.frames[-1]['time'] if self.frames else 0.0

    def _np_rebuild(self):
        """A6: 重建 numpy 缓存 (创建时/frames 换列表后调). 任一快路径前提
        不满足 → _np_fast=False 整体留慢路径, 采样语义与旧实现逐位一致.
        (D2 收紧) time/分量只认纯 Python int/float: np.array 会把 None 静默
        转 nan、数字字符串静默转数值, 而旧实现对它们是报错/原样语义, 故
        None/bool/np 数/str 等一律慢路径, 杜绝 nan 静默扩散."""
        frames = self.frames
        self._np_key = (id(frames), len(frames))
        self._np_fast = False
        self._np_times = None
        self._np_vals = None
        if len(frames) < 2:
            return
        try:
            for fr in frames:
                tv = fr['time']
                if type(tv) is not float and type(tv) is not int:
                    return      # None/bool/np 数/str: 旧实现比较/报错语义特殊 → 慢路径
                if type(tv) is int and float(tv) != tv:
                    return      # int 超 f64 精度: 定段可能偏移 → 慢路径
                for k in self._CHANNELS:
                    v = fr[k]   # 缺 k → KeyError → 慢路径 (采样时同旧代码报错)
                    if type(v) is not list and type(v) is not tuple:
                        return  # None/np 数组等: np.array 会静默转 nan/数值 → 慢路径
                    if len(v) < 3:
                        return  # 旧代码 a[j] 会 IndexError → 慢路径保持该语义
                    for j in range(3):
                        x = v[j]
                        if x != x:          # nan 分量 → 慢路径 (旧实现原样算出 nan)
                            return
                        if type(x) is not int and type(x) is not float:
                            return  # 分量含 None/bool/np 数/str → 慢路径
            times = np.array([fr['time'] for fr in frames], dtype=np.float64)
            if times.shape != (len(frames),) or not np.all(times[1:] >= times[:-1]):
                return          # 时间乱序: searchsorted 定段与旧线性扫不等价 → 慢路径
            vals = {}
            for k in self._CHANNELS:
                arr = np.array([fr[k] for fr in frames], dtype=np.float64)  # 缺 k→KeyError
                if arr.shape != (len(frames), 3):
                    return      # 非 3 分量值: 向量化插值语义不可保证 → 慢路径
                vals[k] = arr
        except (TypeError, ValueError, KeyError, IndexError, OverflowError):
            return              # 坏帧数据 → 永久慢路径 (采样时同旧代码报错)
        self._np_times = times
        self._np_vals = vals
        self._np_fast = True

    def _np_sync(self):
        """A6 (红线3): 缓存失效校验——frames 列表对象身份或长度变化即重建."""
        if self._np_key != (id(self.frames), len(self.frames)):
            self._np_rebuild()

    def sample(self, t):
        """时间 t 采样插值变换. 返回 { 'position':(x,y,z) | 'rotation':.. | 'scale':.. } 子集."""
        if not self.frames:
            return {}
        self._np_sync()
        if not self._np_fast or (type(t) is not float and type(t) is not int):
            return self._sample_slow(t)     # 特殊 t 类型 (bool/np 数/Decimal 等) → 旧循环语义
        dur = self.duration
        if dur > 0:
            t = t % dur
        if t != t:
            # NaN t (含 ±inf 取模结果): 旧循环 t<=x 全不命中 → 与旧实现一致保持末帧原值
            last = self.frames[-1]
            return {k: last[k] for k in self._CHANNELS if k in last}
        times = self._np_times
        i = int(np.searchsorted(times, t, side='left'))   # 首个 times[i] >= t
        if i >= len(times):
            # t 越过末帧 (仅 dur<=0 时可达): 与旧循环扫完一致, 保持末帧原值原对象
            last = self.frames[-1]
            return {k: last[k] for k in self._CHANNELS if k in last}
        if i == 0:
            i = 1   # t<=首帧时间: 旧循环首查 i=1 → 段 (0,1) (t 早于首帧时 f<0 外推, 同旧)
        prev_t = float(times[i - 1])
        span = float(times[i]) - prev_t
        f = 0.0 if span <= 0 else (t - prev_t) / span   # 与旧实现同一公式同一顺序
        out = {}
        for k in self._CHANNELS:
            a = self._np_vals[k][i - 1]
            b = self._np_vals[k][i]
            # 行向量化插值: 与旧公式 a[j]+(b[j]-a[j])*f 同序 (减→乘→加), IEEE754
            # 逐位同源; tolist() 转回 Python float 再组 tuple (输出类型与旧一致)
            out[k] = tuple((a + (b - a) * f).tolist())
        return out

    def _sample_slow(self, t):
        """A6 慢路径: 旧逐帧线性扫原样保留 (语义基准)."""
        dur = self.duration
        if dur > 0:
            t = t % dur
        prev = self.frames[0]
        for i in range(1, len(self.frames)):
            nxt = self.frames[i]
            if t <= nxt['time']:
                span = nxt['time'] - prev['time']
                f = 0.0 if span <= 0 else (t - prev['time']) / span
                out = {}
                for k in ('position', 'rotation', 'scale'):
                    if k in prev and k in nxt:
                        a, b = prev[k], nxt[k]
                        out[k] = tuple(a[j] + (b[j] - a[j]) * f for j in range(3))
                    elif k in prev:
                        out[k] = prev[k]
                return out
            prev = nxt
        return {k: prev[k] for k in ('position', 'rotation', 'scale') if k in prev}


class AnimatorComponent(Component):
    """动画组件 (M35, Unity Animator 简化): 挂物体播放关键帧变换动画.
    clips     {'动画名': AnimationClip}
    current   当前动画名 (None=不播)
    time      当前播放时间 (秒)
    playing   是否播放 (脚本 play/stop)
    loop      是否循环 (播到末帧停)"""
    ctype = 'animator'

    def __init__(self, clips=None, current=None, loop=True):
        super().__init__()
        self.clips = clips or {}
        self.current = current
        self.time = 0.0
        self.playing = False
        self.loop = bool(loop)

    def play(self, name, restart=False):
        """播放/切换到动画 (restart=True 从头播)."""
        if restart or self.current != name:
            self.time = 0.0
        self.current = name
        self.playing = True

    def stop(self):
        self.playing = False


class AudioSystem:
    """M34: 音频后端封装 (B2 2026-08-30 换库: 委托 audio_backend.AudioBackend).

    主后端 = game-audio (miniaudio); 兜底 = pygame.mixer (现状语义); 两者皆失败
    → 全静默 no-op (与现状无设备同语义). 公开 API 语义不变: 文件缺失不崩,
    播放失败静默; owner=组件身份 (id 组件) 供同 clip 多组件独立音量.
    ★退出必须 shutdown() (miniaudio 设备线程; 引擎退出链 + atexit 三重兜底)."""
    def __init__(self):
        self._backend = None   # 惰性 (audio_backend.AudioBackend)
        self._init_done = False

    def _ensure(self):
        if not self._init_done:
            from audio_backend import AudioBackend
            self._backend = AudioBackend()
            self._init_done = True
        return self._backend

    def load(self, path):
        """加载/缓存句柄 (失败 None 缓存, 不崩). 无 owner = 共享句柄 (一次性音效)."""
        b = self._ensure()
        return b.load(path, owner=None)

    def play(self, path, loop=False, volume=1.0, owner=None):
        """播放音效 (loop=True 循环). 文件缺失/后端失败静默跳过."""
        self._ensure().play(path, loop=loop, volume=volume, owner=owner)

    def stop(self, path, owner=None):
        """停止 (幂等; 未播放/未加载静默)."""
        b = self._ensure()
        b.stop(path, owner=owner)

    def play_sound(self, path, volume=1.0):
        """脚本用: 一次性音效 (如跳跃/碰撞)."""
        self.play(path, loop=False, volume=volume)

    def shutdown(self):
        """关闭音频设备后端 (幂等; 进程退出链 + atexit 兜底)."""
        if self._backend is not None:
            try:
                self._backend.shutdown()
            except Exception:
                pass
