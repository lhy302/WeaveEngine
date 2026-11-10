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
import os

import numpy as np

from loom_types import Point3D
from loom_material import Material


def _normalize_scale(v):
    """缩放归一化: 1~3 个数值 -> 3 元组, 缺省分量补 1.0 (None -> (1,1,1)).

    P-05 (2026-11-07): mat4_scale / SoA 快照按 s[0]/s[1]/s[2] 取分量, 长度
    小于 3 的序列 (如 (1, 2)) 会在渲染/物理帧内抛 IndexError. TransformComponent
    的构造器与 setter 都过这里, 保证矩阵路径永远拿到 3 分量; 长度 0 或 >3 /
    非数值序列显式 ValueError (与 loom_game_object._normalize_scale 同语义).
    """
    if v is None:
        return (1.0, 1.0, 1.0)
    try:
        vals = tuple(float(x) for x in v)
    except (TypeError, ValueError):
        raise ValueError('scale 必须是 1~3 个数值的序列, 收到 %r' % (v,))
    if not 1 <= len(vals) <= 3:
        raise ValueError('scale 必须是 1~3 个数值的序列, 收到 %r' % (v,))
    if len(vals) < 3:
        vals = vals + (1.0,) * (3 - len(vals))
    return vals


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
        self._scale = _normalize_scale(scale)
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
        # P-05: 统一归一化 (短序列补 1.0 / 非法长度拒绝), 矩阵与 SoA 路径
        # 恒拿到 3 分量; 旧实现 tuple(v) 接受 (1,2) 后在热路径 IndexError.
        self._scale = _normalize_scale(v)
        TransformComponent._xform_gen += 1


class MeshRendererComponent(Component):
    """网格渲染组件: 网格 + 材质引用 + 法线模式 + 可见性 (M23 材质资产化).
    颜色/饱和度移到共享 Material 上 —— 多个物体引用同一材质, 改一处全变."""
    ctype = 'mesh_renderer'

    # 2026-11-07 (_fix_summary §5 遗留: _update_lod 无 LOD 仍每帧全量扫描):
    # LOD 配置代 —— lod_levels / lod_screen_levels 每次写入都 bump.
    # SceneDriver 只比较本代, 变了才重建"配了 LOD 的模型"集合 (O(N) 一次);
    # 集合为空时每帧 O(1) 早退. 运行期脚本/撤销/EAI 直接写 renderer.lod_*
    # 也能被感知 (不需要调用方显式登记), 无 LOD 的默认路径零扫描.
    _lod_gen = 0

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
        # 存 _lod_levels / _lod_screen_levels, 由 property 写入并 bump _lod_gen.
        self._lod_levels = None
        # M36 LOD 屏幕占比模式 (对标 Unity LODGroup.screenRelativeTransitionHeight):
        # [(屏幕占比阈值, mesh), ...] 降序 (高精度阈值大); 更准确 (大物体远处仍高精度)。
        self._lod_screen_levels = None
        self.lod_bias = 1.0                      # LOD 偏移 (对标 Unity lodBias; >1 更早降级)
        self._lod_cur = None                     # 上次 LOD 选中的 mesh (防每帧重复切换)
        self._lod_radius = None                  # 缓存包围球半径 (屏幕占比用)

    # ---- LOD 配置 property (写入 bump _lod_gen, 供 SceneDriver 增量登记) ----
    @property
    def lod_levels(self):
        return self._lod_levels

    @lod_levels.setter
    def lod_levels(self, v):
        self._lod_levels = v
        MeshRendererComponent._lod_gen += 1

    @property
    def lod_screen_levels(self):
        return self._lod_screen_levels

    @lod_screen_levels.setter
    def lod_screen_levels(self, v):
        self._lod_screen_levels = v
        MeshRendererComponent._lod_gen += 1


class ScriptComponent(Component):
    """脚本组件 (M27 -> M25): 一个脚本挂载, 物体可有多个.
    script_id = scripts.SCRIPTS 的键; script_vars = 参数覆盖;
    _script/_script_broken 是播放期运行态 (编辑/非播放期不实例化)."""
    ctype = 'script'

    # P-03 (2026-11-07): 脚本组件创建代。GameObject.add_script 只 append 组件,
    # 不 bump 引擎结构代 —— engine.update_scripts 的 has_scripts 缓存若只看
    # 结构代, 无脚本场景运行期挂脚本后会永久早退。构造函数是全库唯一构造点,
    # 在这里 bump; engine 缓存键 = (结构代, 本代), remove/clear 不 bump 只会
    # 多扫一帧 (多算不错算)。
    _script_gen = 0

    def __init__(self, script_id=None, script_vars=None):
        super().__init__()
        ScriptComponent._script_gen += 1
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

    def __init__(self, frames=None, loop_mode=None):
        self.frames = frames or []
        # beta6 C1: 每片段循环模式 ('once'/'loop'/'pingpong'); None = 继承
        # AnimatorComponent.loop (旧文件/旧构造点行为逐位不变).
        self.loop_mode = loop_mode
        self._np_key = None      # (id(frames), len(frames)) 缓存失效校验
        self._np_fast = False    # True = sample 可走 numpy 快路径
        self._np_times = None    # (F,) f64 关键帧时间 (frames 列表序, 不重排)
        self._np_vals = None     # {'position'/'rotation'/'scale': (F,3) f64}
        self._np_batch = None    # beta6 C1: 批量求值用 (times, vals) / None
        self._np_varies = None   # beta6 C1: {通道: 是否逐帧变化}
        self._np_rebuild()

    @property
    def duration(self):
        return self.frames[-1]['time'] if self.frames else 0.0

    # ---- beta6 C1: 内容相等 / 身份哈希 ----
    # 为什么需要 __eq__: undo.snapshot() 现在按值拷贝 clips (隔离), commit_model
    # 用 before/after 快照比较判定"是否真的改了"; 若按对象身份比较, 任何一次
    # commit 都会因拷贝产生新对象而误判为"改了" -> 撤销栈塞满空操作。
    # 为什么 hash 保持身份: 求值器按"片段实例"分组 (同内容不同实例各自成组),
    # 身份哈希即可; 内容相等只用于快照比较 (两者不冲突: 不同 hash 的相等对象
    # 不会被 dict 合并)。**已知不对称**: `b in [a]` 可为 True 而 `{a:1}.get(b)`
    # 为 None —— 本仓只有"列表/== 比较"与"按实例分组"两种用法, 不走混合读者。
    #
    # R5-02 P-07: 比较走**规范键**而不是裸 frames —— 帧值可能是 numpy 数组
    # (脚本/插件塞进来的非规范数据), 直接 `array == array` 会抛
    # ValueError("truth value ... ambiguous")。规范键把 ndarray 折成
    # (形状/类型/字节) 三元组, list 与 tuple 归一成 tuple。
    @staticmethod
    def _canon_value(v, depth=0):
        """值 -> 可比较规范形 (R6 V-12: 容器**递归**, 内嵌 ndarray 一并折字节).

        顶层 ndarray 早在 R5 P-07 就折成 (shape/dtype/bytes); 但 list/tuple
        里再套 ndarray 时, `tuple(v)` 内仍是数组 -> `==` 歧义 -> __eq__ 落到
        `self is other` -> 同内容判不等。这里逐层递归; 深度上限 8 防环。
        """
        if depth > 8:
            return v
        if isinstance(v, np.ndarray):
            return ('__ndarray__', v.shape, v.dtype.str, v.tobytes())
        if isinstance(v, (list, tuple)):
            return tuple(AnimationClip._canon_value(x, depth + 1) for x in v)
        return v

    def _content_key(self):
        return (self.loop_mode,
                tuple(tuple((k, self._canon_value(v))
                            for k, v in sorted(fr.items()))
                      for fr in self.frames))

    def __eq__(self, other):
        if not isinstance(other, AnimationClip):
            return NotImplemented
        try:
            return self._content_key() == other._content_key()
        except Exception:                # 畸形帧 (不可排序/不可哈希的值)
            return self is other

    def __ne__(self, other):
        r = self.__eq__(other)
        return NotImplemented if r is NotImplemented else not r

    __hash__ = object.__hash__

    def copy(self):
        """深拷贝 (帧字典 + 值序列都复制) —— undo 快照值隔离 / 场景重建用.

        beta6 C1: 旧 undo 快照按引用存 clips 字典, 改快照会污染模型
        (docs/design/research_beta6_03_animation.md §1.5 实测 D1/D2).
        值序列保持原类型 (list/tuple/ndarray), 不改变序列化形态;
        R5-02 P-07: list 拷一份、ndarray `.copy()` —— 否则模型与快照共享
        同一个可变数组, 改一侧会串到另一侧 (值隔离被打破)。
        """
        def _cv(v, depth=0):
            """值 -> 深拷贝 (R6 V-12: 容器递归; list/tuple/ndarray 都隔离)."""
            if depth > 8:                # 环状容器: 放弃深拷 (极边界, 不炸)
                return v
            if isinstance(v, np.ndarray):
                return v.copy()
            if isinstance(v, list):
                return [_cv(x, depth + 1) for x in v]
            if isinstance(v, tuple):
                return tuple(_cv(x, depth + 1) for x in v)
            return v
        return AnimationClip(
            [{k: _cv(v) for k, v in fr.items()} for fr in self.frames],
            loop_mode=self.loop_mode)

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
        self._np_batch = None
        self._np_varies = None
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
        self._np_batch = (times, vals)     # beta6 C1: 批量求值直接读这一对
        # beta6 C1: 通道是否逐帧变化 —— 恒定通道不必采样/不必 tolist,
        # 直接写该常量 (值取 clip.sample(0) 的结果, 与插值公式逐位一致)。
        varies = {}
        for k in self._CHANNELS:
            arr = vals[k]
            const_k = not bool((arr != arr[0]).any())
            if const_k and bool((arr[0] == 0.0).any()):
                # 常量通道但值为 ±0: 0.0/-0.0 的符号位会随插值因子 f 变化,
                # 保守起见仍按"会变"处理 (走采样), 保证与逐物体结果逐位一致。
                const_k = False
            varies[k] = not const_k
        self._np_varies = varies
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
        # beta6 C1: 播放速率 (1.0=原速; 旧构造点缺省 -> 行为与旧实现逐位一致).
        self.speed = 1.0

    def play(self, name, restart=False):
        """播放/切换到动画 (restart=True 从头播)."""
        if restart or self.current != name:
            self.time = 0.0
        self.current = name
        self.playing = True

    def stop(self):
        self.playing = False

    # ---- beta6 C1: 播放控制 (变速 / scrub / 有效循环模式) ----
    def set_speed(self, speed):
        """设置播放速率 (>0 加速, <0 倒放; 0=冻结). 非数值 -> ValueError."""
        try:
            speed = float(speed)
        except (TypeError, ValueError):
            raise ValueError('speed 必须是数值, 收到 %r' % (speed,))
        if speed != speed or speed in (float('inf'), float('-inf')):
            raise ValueError('speed 必须是有限数值, 收到 %r' % (speed,))
        self.speed = speed
        return speed

    def effective_loop_mode(self, clip=None):
        """该片段生效的循环模式: clip.loop_mode 优先, 否则由组件 loop 推导."""
        if clip is None:
            clip = self.clips.get(self.current) if self.current else None
        mode = getattr(clip, 'loop_mode', None) if clip is not None else None
        return mode or ('loop' if self.loop else 'once')

    def seek(self, t):
        """把播放头移到 t 秒 (按循环模式归一到合法区间; 编辑器 scrub 用).

        once: [0, duration] 夹取; loop: t % duration; pingpong: 折返.
        不改变 playing (scrub 预览不应偷偷开播).
        """
        try:
            t = float(t)
        except (TypeError, ValueError):
            raise ValueError('seek 需要数值秒, 收到 %r' % (t,))
        clip = self.clips.get(self.current) if self.current else None
        if clip is None:
            self.time = t
            return t
        mode = self.effective_loop_mode(clip)
        dur = clip.duration
        if mode == 'once':
            if t < 0.0:
                t = 0.0
            elif dur > 0.0 and t > dur:
                t = dur
        elif mode == 'pingpong' and dur > 0.0:
            period = dur + dur
            t = t % period
            if t > dur:
                t = period - t
        elif dur > 0.0:
            t = t % dur
        self.time = t
        return t


# ============================================================================
# beta6 C1: 动画求值内核 —— GL 引擎与 SceneDriver 的**唯一**实现
# ----------------------------------------------------------------------------
# 设计依据 docs/design/research_beta6_03_animation.md（批次1）:
#   ① 去复刻: loom_frame_components.update_animations 与 scene_driver
#      ._update_animations 都只调 evaluate_animations()（旧实现逐行相同, 改一处
#      忘一处 = 双后端行为分叉）。
#   ② 批量: 快路径片段按 clip 分组走一次 numpy 分段线性求值, 与
#      AnimationClip.sample() 快路径**同公式同操作顺序**(searchsorted side=left /
#      i 夹到 >=1 / span<=0 -> f=0 / a+(b-a)*f), 因此数值逐位一致
#      (tests/test_animation_base.py 有对拍断言)。
#   ③ 时间语义: once 到点 = **末帧**(旧实现被 sample() 无条件取模倒回第 0 帧);
#      loop/pingpong 相位每帧规范化(旧实现一帧只减一次 duration, 跨周期越界)。
#   ④ 写者优先级 D6「动画只驱动 kinematic」: 动态刚体(rigidbody 且非 kinematic)
#      的变换归物理所有, 动画跳过并只告警一次 —— 这样物理管线开/关两种配置
#      不再改变结果(旧实现两条路径胜负相反)。
def physics_disabled_by_env():
    """LOOM_NO_PHYSICS=1 -> 强制"物理不可用" (R6 V-10 兑现: 之前只写在注释里).

    与旧 LOOM_NO_PHYSICS_DLL (DLL 层整体禁门, 已在 B3 删除) 不是一回事:
    这里只影响**本进程的物理解算**, 让动画回退驱动动态刚体, 用于诊断/回归
    (无 culverin 的机器行为等价)。接受 1/true/yes/on; 0/false/no/off/空 -> 关。
    """
    v = os.environ.get('LOOM_NO_PHYSICS')
    if not v:
        return False
    return v.strip().lower() not in ('0', 'false', 'no', 'off')


_ANIM_CHANNELS = ('position', 'rotation', 'scale')
_ANIM_WARNED_DYNAMIC = False
_ANIM_WARNED_NO_PHYSICS = False   # R5-02 P-06: 物理不可用 -> 回退动画驱动 (一次性提示)
_ANIM_WARNED_BAD_SPEED = False    # R5-02 P-07: speed 非数值 -> 单物体降级 (一次性提示)
_ANIM_INF = float('inf')
# Point3D 是 namedtuple; 其 __new__ 是 Python 层函数 (~0.4us/次). 批量写回每帧
# 要造 N 个点, 故走 tuple.__new__(Point3D, 序列) 的 C 路径 (~0.12us) ——
# 产物仍是 Point3D (同名/同值/同相等语义), 只是跳过 namedtuple 的包装层。
_P3_NEW = tuple.__new__


def reset_anim_warn():
    """测试用: 清掉全部一次性告警标记 (动态刚体/无物理/speed 非法)."""
    global _ANIM_WARNED_DYNAMIC, _ANIM_WARNED_NO_PHYSICS, _ANIM_WARNED_BAD_SPEED
    _ANIM_WARNED_DYNAMIC = False
    _ANIM_WARNED_NO_PHYSICS = False
    _ANIM_WARNED_BAD_SPEED = False


def animator_to_dict(an):
    """AnimatorComponent -> 场景字典 (beta6 C1: v11 增量 speed / clip_meta).

    运行时态 time/playing **不落盘**(D6: 只作预览态) —— 存盘=回到起点,
    与旧行为一致; 这里显式写入注释与测试断言, 防止有人"顺手"加进去。
    """
    if an is None:
        return None
    d = {
        "current": an.current,
        "loop": an.loop,
        "clips": {name: [dict(f) for f in clip.frames]
                  for name, clip in an.clips.items()},
    }
    speed = float(getattr(an, 'speed', 1.0))
    if speed != 1.0:
        d["speed"] = speed          # 缺省不写, 旧文件/旧阅读器语义不变
    meta = {}
    for name, clip in an.clips.items():
        lm = getattr(clip, 'loop_mode', None)
        if lm in ('once', 'loop', 'pingpong'):
            meta[name] = {"loop_mode": lm}
    if meta:
        d["clip_meta"] = meta
    return d


def animator_from_dict(an):
    """场景字典 -> (clips, current, loop, speed). 旧文件(无 speed/clip_meta)兼容."""
    clips = {}
    for name, frames in (an.get('clips') or {}).items():
        clips[name] = AnimationClip([dict(f) for f in frames])
    meta = an.get('clip_meta')
    if isinstance(meta, dict):
        for name, m in meta.items():
            clip = clips.get(name)
            if clip is None or not isinstance(m, dict):
                continue
            lm = m.get('loop_mode')
            if lm in ('once', 'loop', 'pingpong'):
                clip.loop_mode = lm
    speed = 1.0
    raw_speed = an.get('speed', 1.0)
    try:
        speed = float(raw_speed)
    except (TypeError, ValueError):
        speed = 1.0
    if not math.isfinite(speed):
        speed = 1.0
    return clips, an.get('current'), an.get('loop', True), speed


def _sample_batch(times, vals, phases, channels=_ANIM_CHANNELS):
    """批量分段线性采样: 与 AnimationClip.sample 快路径逐位一致.

    返回 ({通道: (k,3) float64}, ok: bool[k])；ok=False 的行(NaN / 越过末帧)
    必须回落到逐物体 sample()，语义与旧实现相同。
    channels 只影响"算什么" (调用方跳过恒定通道), 不改变任一通道的公式。
    """
    idx = np.searchsorted(times, phases, side='left')   # 首个 times[i] >= t
    ok = (idx < times.shape[0]) & (phases == phases)
    idx = np.minimum(np.maximum(idx, 1), times.shape[0] - 1)
    prev_t = times[idx - 1]
    span = times[idx] - prev_t
    f = np.where(span <= 0.0, 0.0,
                 (phases - prev_t) / np.where(span <= 0.0, 1.0, span))
    out = {}
    for k in channels:
        v = vals[k]
        a = v[idx - 1]
        b = v[idx]
        out[k] = a + (b - a) * f[:, None]
    return out, ok


def _write_pose(m, s):
    """把 sample() 的通道子集写回物体 (慢路径 / 末帧; 与旧实现同语义).

    旧实现走 m.position / m.rotation 的 property setter (每次 bump gen);
    这里对"标准 3 分量"直写 transform 内部字段 (gen 由调用方每帧统一 bump),
    其余形态仍走公开 setter —— 短序列补 1.0 / 长度错抛 TypeError 等旧语义
    因此保持不变。
    """
    tr = m.transform
    if 'position' in s:
        p = s['position']
        if (type(p) is tuple or type(p) is list) and len(p) == 3:
            tr._position = Point3D(float(p[0]), float(p[1]), float(p[2]))
        else:
            m.position = Point3D(*p)
    if 'rotation' in s:
        r = s['rotation']
        if (type(r) is tuple or type(r) is list) and len(r) == 3:
            tr._rotation = Point3D(float(r[0]), float(r[1]), float(r[2]))
        else:
            m.rotation = Point3D(*r)
    if 'scale' in s:
        sc = s['scale']
        if (type(sc) is tuple or type(sc) is list) and len(sc) == 3:
            tr._scale = (float(sc[0]), float(sc[1]), float(sc[2]))
        else:
            m.set_scale(sc)


def evaluate_animations(models, dt, physics_available=True):
    """推进全部 Animator 组件并写回变换 (batch / 双后端唯一实现).

    返回 {'advanced': 推进的实例数, 'blocked_dynamic': 因动态刚体被跳过的实例数,
          'fallback_dynamic': 因物理不可用而改由动画驱动的动态刚体数}.

    physics_available: 调用方告知"物理后端是否真的在驱动刚体"。
      · True  = D6: 动态刚体位姿归物理, 动画整条跳过;
      · False = 物理后端缺失/被禁 (culverin 缺失、桥僵死): **回退动画驱动**,
                否则这些物体会永久冻结 (审计 R5-02 P-06 / Q-C1-3=A)。
    单遍扫描 + 同片段分组批量求值; 慢路径与旧实现逐位一致 (对拍见
    tests/test_animation_base.py)。

    性能 (R6 F-02 诚实口径, 不再写"≤1ms"): 500 动画物体实测 **1.42-1.69ms/
    逻辑帧** (旧逐物体实现 12.7-13.1ms, 约 8-9x)。剩余成本是**两个无法向量化
    的 Python 逐物体循环** (扫描推进 ~0.35ms + 写回 Point3D ~0.45ms) + GC
    ~0.24ms; 想真到 ≤1ms 需要 animator 状态也 SoA + 活跃集缓存 (批次2 重构,
    会动 play/stop 与 undo 链路), 不在本批风险面内。原始目标见
    docs/design/research_beta6_03_animation.md §③ S2 (已标注未达成)。
    """
    global _ANIM_WARNED_DYNAMIC, _ANIM_WARNED_NO_PHYSICS, _ANIM_WARNED_BAD_SPEED
    stats = {'advanced': 0, 'blocked_dynamic': 0, 'fallback_dynamic': 0}
    if not models:
        return stats
    groups = {}          # clip -> (times, vals, models, phases)
    synced = set()       # R5-02 P-05: 本帧已 _np_sync 的片段 (帧列表可能被脚本换掉)
    blocked = 0
    fallback = 0
    fallback_ms = []     # R6 V-08: 本帧回退动画驱动的物体 (物理侧据此避让)
    advanced = 0
    wrote = False
    P3NEW = _P3_NEW
    # ---- ① 单遍扫描: 推进播放头 + 分组 (只碰状态, 不碰变换) ----
    for m in models:
        an = m.animator
        if an is None or not an.playing:
            continue
        name = an.current
        if not name:
            continue
        clip = an.clips.get(name)
        if clip is None:
            continue
        frame_list = clip.frames
        if not frame_list:
            continue
        rb = m.rigidbody
        if rb is not None and not rb.is_kinematic:
            if physics_available:
                blocked += 1                 # D6: 动态刚体归物理
                continue
            fallback += 1                    # Q-C1-3=A: 无物理时回退动画驱动
            fallback_ms.append(m)            # R6 V-08: 物理侧要避让这批
        advanced += 1
        mode = clip.loop_mode
        if mode is None:
            mode = 'loop' if an.loop else 'once'
        dur = frame_list[-1]['time']
        # R5-02 P-07 + R6 V-05: an.speed 是公开属性 —— 非数值(list/None) 会抛
        # TypeError, 非有限(nan/inf) 会让 t/phase 变 nan 后**静默冻结**(nan 传播,
        # 永不恢复)。两者都按单物体降级 1.0 + 一次性提示, 不放大成整帧失败。
        try:
            t = an.time + dt * an.speed
        except TypeError:
            t = None
        if t is None or t != t or t == _ANIM_INF or t == -_ANIM_INF:
            an.speed = 1.0
            at = an.time
            if type(at) is not float and type(at) is not int:
                an.time = 0.0
            elif at != at or at == _ANIM_INF or at == -_ANIM_INF:
                an.time = 0.0                    # 污染的时间一并复位 (否则 nan 不愈)
            t = an.time + dt
            if not _ANIM_WARNED_BAD_SPEED:
                _ANIM_WARNED_BAD_SPEED = True
                print('[动画] 物体 %r 的 animator.speed/时间非法, 已重置 (speed=1.0)'
                      % (getattr(m, 'name', m),))
        if mode == 'loop':
            if dur > 0.0:
                phase = t % dur              # 循环: 每帧规范化 (旧实现只减一次)
                an.time = phase
            else:
                an.time = t
                phase = t
        elif mode == 'once':
            if dur > 0.0 and t >= dur:
                an.time = dur                # 到点: 停在末帧 (不再取模回第 0 帧)
                an.playing = False
                last = frame_list[-1]
                _write_pose(m, {k: last[k] for k in _ANIM_CHANNELS if k in last})
                wrote = True
                continue
            if t < 0.0 or dur <= 0.0:
                # R5-02 P-02 / R6 V-04 (U-03=A): 与 seek 一致 —— once 夹到 [0, dur]。
                # 旧实现把负相位直接交给批量 -> 外推 (物体飞走), 而慢路径
                # sample() 取模回绕 -> 同一函数两条路径语义分叉; 这里统一到 0
                # 并停播。dur<=0 (单帧/所有关键帧同 time) 同样夹 0 停播 ——
                # 旧实现此时 an.time 无界负增长且 playing 永真。
                an.time = 0.0
                an.playing = False
                phase = 0.0
            else:
                an.time = t
                phase = t
        elif mode == 'pingpong' and dur > 0.0:
            period = dur + dur
            ph = t % period                  # 跨多周期也规范化
            if ph > dur:
                ph = period - ph
            if ph >= dur:                    # 折返端点 = 末帧
                an.time = ph
                last = frame_list[-1]
                _write_pose(m, {k: last[k] for k in _ANIM_CHANNELS if k in last})
                wrote = True
                continue
            an.time = ph
            phase = ph
        else:
            an.time = t
            phase = t
        cid = id(clip)                       # R5-02 P-05: 与 sample() 同点失效
        if cid not in synced:                # (脚本可能整体替换 clip.frames)
            synced.add(cid)
            clip._np_sync()
        arr = clip._np_batch
        if arr is None or phase != phase:    # 非快路径 / NaN: 逐物体 sample()
            _write_pose(m, clip.sample(phase))
            wrote = True
            continue
        ent = groups.get(clip)
        if ent is None:
            ent = groups[clip] = (arr[0], arr[1], [], [])
        ent[2].append(m)
        ent[3].append(phase)
    if blocked and not _ANIM_WARNED_DYNAMIC:
        _ANIM_WARNED_DYNAMIC = True
        print('[动画] %d 个物体同时有动态刚体与 Animator: 动画不驱动动态刚体'
              '(D6: 只驱动 kinematic/静态体), 已跳过; 要让动画驱动请把刚体设为 '
              'kinematic' % blocked)
    if fallback and not _ANIM_WARNED_NO_PHYSICS:
        # R5-02 P-06 / Q-C1-3=A: 物理不可用时回退动画驱动 (否则位姿永久冻结,
        # 与"动画坏了"不可区分)。物理恢复后自动改回 D6 (物理拥有位姿)。
        _ANIM_WARNED_NO_PHYSICS = True
        print('[动画] 物理后端不可用: %d 个动态刚体上的动画改由动画驱动; '
              '物理恢复后自动改回物理驱动' % fallback)
    # ---- ② 批量求值 + 写回 (同片段一次向量化; 恒定通道不采样/不 tolist) ----
    for clip, (times, vals, ms, phases) in groups.items():
        varies = clip._np_varies or {'position': True, 'rotation': True,
                                     'scale': True}
        want = [k for k in _ANIM_CHANNELS if varies[k]]
        const = clip.sample(0.0) if len(want) != 3 else None
        if want:
            with np.errstate(divide='ignore', invalid='ignore'):
                sampled, ok = _sample_batch(
                    times, vals, np.asarray(phases, dtype=np.float64), want)
        else:
            sampled, ok = {}, np.ones(len(ms), dtype=bool)
        if not ok.all():
            # NaN / 越过末帧等极端行: 整组回落逐物体 sample() (与旧实现同语义;
            # 常规行与批量结果逐位一致, 见 tests/test_animation_base.py)。
            for j, mm in enumerate(ms):
                _write_pose(mm, clip.sample(phases[j]))
            wrote = True
            continue
        pw = 'position' in sampled
        rw = 'rotation' in sampled
        sw = 'scale' in sampled
        pos = sampled['position'].tolist() if pw else None
        rot = sampled['rotation'].tolist() if rw else None
        scl = sampled['scale'].tolist() if sw else None
        # R5-02 P-01 (P0): 常量通道也必须写 Point3D —— _position/_rotation 的
        # 契约是 Point3D, 下游 undo.snapshot / sceneio._emit_object /
        # instantiate_prefab / 脚本 obj.position.x 全按 .x/.y/.z 读; 写 plain
        # tuple 会让"轮子/风扇/平移平台"这类正常片段在保存或撤销时 AttributeError。
        # scale 的契约本来就是 tuple, 但统一 float 化。
        cpos = crot = cscl = None
        if const is not None:
            if not pw:
                v = const.get('position')
                if v is not None and len(v) == 3:
                    cpos = P3NEW(Point3D, v)
            if not rw:
                v = const.get('rotation')
                if v is not None and len(v) == 3:
                    crot = P3NEW(Point3D, v)
            if not sw:
                v = const.get('scale')
                if v is not None and len(v) == 3:
                    cscl = (float(v[0]), float(v[1]), float(v[2]))
        trs = [mm.transform for mm in ms]
        changed = False
        for j, tr in enumerate(trs):
            if pw:
                tr._position = P3NEW(Point3D, pos[j])
                changed = True
            elif cpos is not None and tr._position != cpos:
                tr._position = cpos
                changed = True
            if rw:
                r = rot[j]
                cr = tr._rotation
                if r[0] != cr[0] or r[1] != cr[1] or r[2] != cr[2]:
                    tr._rotation = P3NEW(Point3D, r)
                    changed = True
            elif crot is not None and tr._rotation != crot:
                tr._rotation = crot
                changed = True
            if sw:
                s = scl[j]
                cs = tr._scale
                if s[0] != cs[0] or s[1] != cs[1] or s[2] != cs[2]:
                    tr._scale = (s[0], s[1], s[2])
                    changed = True
            elif cscl is not None and tr._scale != cscl:
                tr._scale = cscl
                changed = True
        if changed:
            wrote = True
    if wrote:
        TransformComponent._xform_gen += 1
    stats['advanced'] = advanced
    stats['blocked_dynamic'] = blocked
    stats['fallback_dynamic'] = fallback
    stats['fallback_models'] = fallback_ms      # R6 V-08: 空列表=无回退
    return stats

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
