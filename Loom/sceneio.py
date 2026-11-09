# -*- coding: utf-8 -*-
"""
sceneio.py — 场景/Prefab 序列化 (M18 + M16 + M21)

格式 (v7):
  {
    "version": 7,
    "camera": {"target":[...], "distance":.., "yaw":.., "pitch":..},   # 可空
    "materials": [                # 材质资产库 (M23, 可空数组)
      {"id": "<guid>", "name": .., "color": "#RRGGBB|null", "saturation": ..}
    ],
    "lights": [                    # 场景光源实体 (M21, 可空数组)
      {"id": .., "name": .., "kind": "directional|point",
       "position": [x,y,z], "direction": [x,y,z],
       "color": [r,g,b], "intensity": 1.0}
    ],
    "cameras": [                   # 场景摄像机实体 (Unity Camera, 可空数组)
      {"id": .., "name": .., "position": [x,y,z], "yaw": .., "pitch": ..,
       "fov": 45.0, "fov_locked": true}     # fov_locked: 视角广度玩家是否可调
    ],
    "active_camera": "<玩家视角摄像机 id | null>",  # 运行时/Player 用该摄像机作玩家视角
    "objects": [                     # DFS 前序: 父一定在子之前
      {
        "id": "<stable-guid>",       # 稳定身份 (场景内对象引用 key)
        "parent_id": "<父的 id | null>",
        "prefab_ref": "<prefab guid | null>",   # 该对象来自哪个 Prefab 实例
        "name": .., "type": .., "params": ..,
        "position": [x,y,z], "rotation": [x,y,z], "scale": [sx,sy,sz],
        "color": "#RRGGBB|null", "normal_mode": "flat|vertex",
        "saturation": 0.0..2.0, "visible": bool,
        "scripts": [                   # M25: 物体可挂多个脚本组件 (可空数组)
          {"id": "rotate", "vars": {参数覆盖}}
        ]
      }
    ]
  }

健壮性 (M18):
  - migrate(data): v1 -> v2 (补 parent_id/prefab_ref); 未知版本降级不抛.
  - 加载容错: 未知基元类型 -> 立方体兜底; 缺字段 -> 默认值.
  - 保存原子化: 写 <path>.tmp 再 os.replace, 崩溃不损坏旧存档.
  - 对象 GUID: 每次 add_model 自动生成; 加载时用文件里的 id 覆盖.

Prefab (M16): 资产文件只存一棵子树 (局部引用), 实例化时整体重生成 GUID,
  每个实例对象挂 prefab_ref, 根对象整体平移 offset.
"""
import json
import os
import uuid
import zlib
import base64
import math

from engine import Point3D, wrap_deg
from mesh import create_cube, spec_to_mesh

SCENE_VERSION = 10  # v10 (2026-08-16 相机物体化): 摄像机可挂父 (parent_id)
PREFAB_VERSION = 1


def generate_guid():
    return uuid.uuid4().hex


class SceneCycleError(ValueError):
    """场景/Prefab 父链成环或对象图不可达.

    加载/保存遇到时直接拒绝 (不静默丢对象). 继承 ValueError, 调用方可按
    普通数据错误处理.
    """


def _validate_object_graph(objects):
    """检测场景/Prefab dict 列表的 parent_id 成环 (不修改数据).

    返回 {对象 id: dict}. 成环抛 SceneCycleError. 非 dict/缺 id 的条目跳过
    (由后续加载容错路径处理), 避免坏文件在检测阶段崩溃.
    """
    id_map = {}
    for obj in objects:
        if not isinstance(obj, dict):
            continue
        oid = obj.get('id') or obj.get('guid')
        if isinstance(oid, str) and oid:
            id_map[oid] = obj
    state = {}          # 1=当前路径, 2=已完成
    for start in id_map:
        if state.get(start) == 2:
            continue
        chain = []
        cur = start
        while cur is not None and cur in id_map:
            st = state.get(cur)
            if st == 1:
                try:
                    i = chain.index(cur)
                except ValueError:
                    i = 0
                cyc = chain[i:] + [cur]
                raise SceneCycleError(
                    "场景父链成环 (parent_id): %s" % " -> ".join(cyc))
            if st == 2:
                break
            state[cur] = 1
            chain.append(cur)
            pid = id_map[cur].get('parent_id')
            cur = pid if isinstance(pid, str) and pid in id_map else None
        for oid in chain:
            state[oid] = 2
    return id_map


def _validate_model_graph(models):
    """检测运行时模型父链成环/不可达 (保存前防御).

    场景保存只从根 DFS; 若父链成环或父指针悬空, 部分对象会被静默丢弃.
    本函数在序列化前显式拒绝, 抛 SceneCycleError.
    """
    model_ids = {id(m) for m in models}
    for m in models:
        path = set()
        cur = m
        while cur is not None:
            k = id(cur)
            if k in path:
                raise SceneCycleError(
                    "场景父链成环 (模型): %r" % (getattr(cur, 'name', cur),))
            path.add(k)
            cur = getattr(cur, 'parent', None)
    reachable = set()
    stack = [m for m in models if getattr(m, 'parent', None) is None]
    while stack:
        m = stack.pop()
        k = id(m)
        if k in reachable or k not in model_ids:
            continue
        reachable.add(k)
        stack.extend(getattr(m, 'children', ()) or ())
    if len(reachable) != len(model_ids):
        raise SceneCycleError(
            "场景对象图存在不可达对象 (%d 个): 父链可能成环"
            % (len(model_ids) - len(reachable)))


# ---------------- 对象 <-> dict ----------------

def _f3(v, default):
    """容错 3 分量取值 (安全扫描 2026-08-20 加固): 接受 [x,y,z]/tuple 且每分量
    可转 float; 其他 (None/字符串/长度不符/坏数) -> 返回 default. 坏场景文件不崩."""
    if isinstance(v, (list, tuple)) and len(v) == 3:
        try:
            return tuple(float(x) for x in v)
        except (TypeError, ValueError):
            pass
    return default


def _f1(v, default):
    """容错单数值: 可转 float 才用, 否则 default (坏场景文件不崩)."""
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


# ---------------- 相机投影字段的归一/校验 (2026-11-08 批2) ----------------
# 人类裁决 D7=A: ortho / ortho_size / fov 是**场景相机属性**
#   （进脏判定、进撤销、播放前后恒等）——所以读侧/写侧必须用同一套归一规则，
#   否则"保存的值"和"加载回来的值"不是同一个东西。
# 人类裁决 Q4=B: 场景是不可信输入时"报错即可"，但**不得静默错值**、不得崩、不得死循环。
# 归一规则（_b_strict / norm_ortho_size / norm_fov_deg 三条是唯一实现，editor/scene_driver 都复用它）：
#   · 缺键/None          -> 默认（旧场景兼容，不打印）
#   · 类型非法/NaN/inf   -> 默认 + 打印警告（出声，不静默）
#   · 数值越界（ortho_size<=0 / fov 越界）-> 钳制 + 打印警告
ORTHO_SIZE_DEFAULT = 12.0     # 正交可见高度 (世界单位)，与 EAI camera_proj 默认一致
ORTHO_SIZE_MIN = 1.0          # 与 agent_commands.camera_proj 的 max(1.0, ...) 下界一致
FOV_DEFAULT_DEG = 60.0        # 与 engine._fov 初值 (radians(60)) 一致
FOV_MIN_DEG, FOV_MAX_DEG = 1.0, 179.0

_TRUE_WORDS = ('1', 'true', 'yes', 'on', 'y')
_FALSE_WORDS = ('0', 'false', 'no', 'off', 'n')


def _b_strict(v, default=False, where='?'):
    """严格布尔解析: bool / 0|1 / 文本 true|false|1|0|yes|no|on|off (忽略大小写与空白).

    为什么不用 bool(v): bool('false') is True —— 字符串 "false" 会被当成"开",
    把透视场景静默变成正交 (审计 P-03-04)。非法类型 -> default + 警告，不静默。
    """
    if v is None:
        return bool(default)
    if isinstance(v, bool):
        return v
    if isinstance(v, (int, float)):
        return bool(v)
    if isinstance(v, str):
        s = v.strip().lower()
        if s in _TRUE_WORDS:
            return True
        if s in _FALSE_WORDS:
            return False
        print("[场景] %s 布尔值无法识别 (%r) -> 用默认 %r" % (where, v, default))
        return bool(default)
    print("[场景] %s 布尔值类型非法 (%s) -> 用默认 %r"
          % (where, type(v).__name__, default))
    return bool(default)


def norm_ortho_size(v, where='camera.ortho_size'):
    """正交可见高度归一: 非法类型/NaN/inf -> 默认; <=0 -> 钳到 ORTHO_SIZE_MIN.

    为什么必须做: mat4_ortho 的内部是 2/(right-left)，ortho_size=0 时
    right-left==0.0 -> ZeroDivisionError，整帧渲染抛异常 (审计 P-03-06)；
    负数会让 left>right（水平镜像），NaN 会让整个 VP 变 NaN（整屏不可见）——
    两者都是静默错值。
    """
    f = _f1(v, None) if v is not None else None
    if f is None:
        if v is not None:
            print("[场景] %s 非数值 (%r) -> 用默认 %.3g" % (where, v, ORTHO_SIZE_DEFAULT))
        return ORTHO_SIZE_DEFAULT
    if not math.isfinite(f):
        print("[场景] %s 非有限数 (%r) -> 用默认 %.3g" % (where, v, ORTHO_SIZE_DEFAULT))
        return ORTHO_SIZE_DEFAULT
    if f < ORTHO_SIZE_MIN:
        print("[场景] %s=%.6g 过小 -> 钳到 %.3g" % (where, f, ORTHO_SIZE_MIN))
        return ORTHO_SIZE_MIN
    return f


def norm_fov_deg(v, where='camera.fov'):
    """透视视场角(度)归一: 非数值/NaN -> 默认; 越界 -> 钳到 [1, 179] 并警告."""
    f = _f1(v, None) if v is not None else None
    if f is None:
        if v is not None:
            print("[场景] %s 非数值 (%r) -> 用默认 %.3g°" % (where, v, FOV_DEFAULT_DEG))
        return FOV_DEFAULT_DEG
    if not math.isfinite(f):
        print("[场景] %s 非有限数 (%r) -> 用默认 %.3g°" % (where, v, FOV_DEFAULT_DEG))
        return FOV_DEFAULT_DEG
    if f < FOV_MIN_DEG or f > FOV_MAX_DEG:
        c = max(FOV_MIN_DEG, min(FOV_MAX_DEG, f))
        print("[场景] %s=%.6g° 越界 -> 钳到 %.3g°" % (where, f, c))
        return c
    return f


def _emit_object(m):
    """GameObject -> dict (单对象). M25: 脚本组件数组 (可多个). M23: 材质引用."""
    mat = m.renderer.material
    return {
        "id": m.guid,
        "parent_id": m.parent.guid if m.parent is not None else None,
        "prefab_ref": m.prefab_ref,
        "name": m.name,
        # Layer/Tag (2026-10-18): 项目级身份元信息; 旧文件无此二键 -> 加载取默认
        "layer": m.layer,
        "tag": m.tag,
        "type": m.primitive or 'cube',
        "params": dict(m.params) if m.params else {'size': 1.0},
        "position": [m.position.x, m.position.y, m.position.z],
        "rotation": [m.rotation.x, m.rotation.y, m.rotation.z],
        "scale": list(m.scale),
        "color": m.color,
        "material_id": mat.guid if mat is not None else None,   # M23: 引用材质库
        "normal_mode": m.normal_mode,
        "saturation": m.saturation,
        "visible": m.visible,
        "scripts": [{"id": sc.script_id, "vars": dict(sc.script_vars)}
                    for sc in m.scripts if sc.script_id],
        # M28 + B1 (2026-08-30): 碰撞体 (含接触材质: 摩擦系数/弹性, 静态体用);
        # B1-P1 加 rolling_friction (旧文件无此键 -> 缺省=默认 0.1, 兼容不变)
        "collider": {"shape": m.collider.shape, "enabled": m.collider.enabled,
                     "friction": m.collider.friction,
                     "restitution": m.collider.restitution,
                     "rolling_friction": m.collider.rolling_friction,
                     # 2026-10-18 Trigger: is_trigger (旧文件无此键 -> 缺省 False)
                     "is_trigger": bool(getattr(m.collider, 'is_trigger', False))},
        # M31 + B1: 刚体 (包含接触材质: 动态体用; 缺省=默认, 兼容旧文件)
        "rigidbody": None if m.rigidbody is None else {
            "mass": m.rigidbody.mass,
            "use_gravity": m.rigidbody.use_gravity,
            "is_kinematic": m.rigidbody.is_kinematic,
            "friction": m.rigidbody.friction,
            "restitution": m.rigidbody.restitution,
            "rolling_friction": m.rigidbody.rolling_friction,
        },
        "audio_source": None if m.audio_source is None else {  # M34: 音频源
            "clip": m.audio_source.clip,
            "loop": m.audio_source.loop,
            "volume": m.audio_source.volume,
            # 2026-10-18 3D 音频 (契约 §6.1)
            "category": m.audio_source.category,
            "min_distance": m.audio_source.min_distance,
            "max_distance": m.audio_source.max_distance,
            "rolloff": m.audio_source.rolloff,
        },
        "animator": None if m.animator is None else {          # M35: 动画
            "current": m.animator.current,
            "loop": m.animator.loop,
            "clips": {name: [dict(f) for f in clip.frames]
                      for name, clip in m.animator.clips.items()},
        },
    }


def _emit_subtree(m, out, seen=None):
    """DFS 前序输出子树. seen 共享集合用于检测重复/成环 (防无限递归)."""
    if seen is None:
        seen = set()
    key = id(m)
    if key in seen:
        raise SceneCycleError(
            "序列化父链成环/对象重复: %r" % (getattr(m, 'name', m),))
    seen.add(key)
    out.append(_emit_object(m))
    for c in m.children:
        _emit_subtree(c, out, seen)


def _make_mesh(obj):
    """容错建网格: obj 类型重读外部文件; 未知/坏参数/文件失效 -> 立方体兜底"""
    t = obj.get('type', 'cube')
    params = obj.get('params', {})
    if t == 'obj' and isinstance(params.get('obj'), str) and params['obj']:
        try:
            from mesh import load_obj
            return load_obj(params['obj'])     # M36: 重读 .obj 文件
        except (ValueError, OSError):
            return create_cube(1.0)            # 文件失效 -> 立方体兜底
    try:
        return spec_to_mesh(t, params)
    except (ValueError, TypeError):
        return create_cube(1.0)


def _apply_object(engine, obj):
    """按 dict 创建物体 (不做父链). 返回 (model, oid).
    M23: 有 material_id 则引用材质库中的共享材质 (找不到则按颜色/饱和度自建),
    无 material_id (v4 旧文件) 保持 add_model 自建的默认材质."""
    mesh = _make_mesh(obj)
    m = engine.add_model(mesh,
                         Point3D(*_f3(obj.get('position'), (0, 0, 0))),
                         Point3D(*_f3(obj.get('rotation'), (0, 0, 0))),
                         normal_mode=obj.get('normal_mode', 'flat'),
                         name=obj.get('name', '物体'),
                         scale=_f3(obj.get('scale'), (1, 1, 1)),
                         visible=obj.get('visible', True),
                         color=obj.get('color'),
                         saturation=obj.get('saturation', 1.0))
    mat_id = obj.get('material_id')
    if mat_id:
        mat = engine._find_material(mat_id)
        if mat is None:                    # 材质不在库 (旧文件/手工编辑) -> 自建并登记
            mat = engine.add_material(color=obj.get('color'),
                                      saturation=obj.get('saturation', 1.0),
                                      guid=mat_id)
        m.renderer.material = mat          # 引用共享材质 (资产语义)
    oid = obj.get('id') or obj.get('guid') or m.guid
    if oid:
        m.guid = oid
    m.prefab_ref = obj.get('prefab_ref')
    # Layer/Tag (2026-10-18, 契约 §3.3 容错):
    #   layer 越界 -> 钳制 0 + 警告;  tag 未注册 -> 自动注册 + 警告;
    #   tag 非法字符 -> 回退 'Untagged' + 警告. 任何情况都不阻断场景加载.
    try:
        lv = int(obj.get('layer', 0))
    except (TypeError, ValueError):
        lv = 0
    if lv < 0 or lv > 31:
        print("[sceneio] 警告: 物体 %r 的 layer=%r 越界, 已钳制为 0"
              % (m.name, obj.get('layer')))
        lv = 0
    m.layer = lv
    tg = obj.get('tag', 'Untagged')
    if not isinstance(tg, str) or not tg.strip():
        tg = 'Untagged'
    tg = tg.strip()
    import layer_tag
    if not layer_tag.tag_exists(tg):
        try:
            layer_tag.register_tag(tg)
            print("[sceneio] 警告: 标签 %r 未注册, 已自动注册" % tg)
        except ValueError as e:
            print("[sceneio] 警告: 标签 %r 非法 (%s), 回退 'Untagged'"
                  % (tg, e))
            tg = 'Untagged'
    m.tag = tg
    # 脚本 (M25): 恢复全部脚本组件 (可多个). 兼容 v3 的单 "script" 字段.
    scs = obj.get('scripts')
    if scs is None:
        sc = obj.get('script')
        scs = [sc] if isinstance(sc, dict) and sc.get('id') else []
    for s in scs:
        if isinstance(s, dict) and s.get('id'):
            m.add_script(s['id'], s.get('vars') if isinstance(s.get('vars'), dict) else {})
    # 刚体 (M31): 文件有 rigidbody 字段则加刚体 (旧文件无字段=无刚体, 保持原行为)
    # B1: friction/restitution/rolling_friction 缺省=默认 (0.5/0.0/0.1), 兼容旧文件
    rb = obj.get('rigidbody')
    if isinstance(rb, dict):
        m.add_rigidbody(mass=rb.get('mass', 1.0),
                        use_gravity=rb.get('use_gravity', True),
                        is_kinematic=rb.get('is_kinematic', False),
                        friction=rb.get('friction', 0.5),
                        restitution=rb.get('restitution', 0.0),
                        rolling_friction=rb.get('rolling_friction', 0.1))
    # 音频源 (M34): 文件有 audio_source 字段则加 (旧文件无=无音频)
    au = obj.get('audio_source')
    if isinstance(au, dict):
        # 2026-10-18 3D 音频 (契约 §6.2): 逐项校验 + 显式警告 (组件 setter 是静默回退,
        # 场景加载需要让用户知道文件里写坏了什么).
        cat = au.get('category', 'sfx')
        if not isinstance(cat, str) or cat.strip().lower() not in ('music', 'sfx', 'voice'):
            print("[sceneio] 警告: 物体 %r 的音频 category=%r 非法, 回退 'sfx'"
                  % (m.name, cat))
            cat = 'sfx'
        else:
            cat = cat.strip().lower()
        try:
            mn = float(au.get('min_distance', 1.0))
        except (TypeError, ValueError):
            mn = 1.0
        if mn <= 0:
            print("[sceneio] 警告: 物体 %r 的音频 min_distance=%r 非法, 回退 1.0"
                  % (m.name, au.get('min_distance')))
            mn = 1.0
        try:
            mx = float(au.get('max_distance', 500.0))
        except (TypeError, ValueError):
            mx = 500.0
        if mx <= mn:
            print("[sceneio] 警告: 物体 %r 的音频 max_distance=%r 不大于 min_distance=%r, "
                  "回退默认 (1.0/500.0)" % (m.name, au.get('max_distance'), mn))
            mn, mx = 1.0, 500.0
        try:
            ro = float(au.get('rolloff', 1.0))
        except (TypeError, ValueError):
            ro = 1.0
        if ro <= 0:
            print("[sceneio] 警告: 物体 %r 的音频 rolloff=%r 非法, 回退 1.0"
                  % (m.name, au.get('rolloff')))
            ro = 1.0
        m.add_audio_source(clip=au.get('clip'),
                           loop=au.get('loop', False),
                           volume=au.get('volume', 1.0),
                           category=cat, min_distance=mn,
                           max_distance=mx, rolloff=ro)
    # 动画 (M35): 文件有 animator 字段则加 (重建 AnimationClip)
    an = obj.get('animator')
    if isinstance(an, dict) and isinstance(an.get('clips'), dict):
        from engine import AnimationClip
        clips = {name: AnimationClip([dict(f) for f in frames])
                 for name, frames in an['clips'].items()}
        m.add_animator(clips=clips, current=an.get('current'),
                       loop=an.get('loop', True))
    # 碰撞体 (M28): 文件有 collider 字段则覆盖默认 (旧文件无字段保持自动派生)
    # B1: friction/restitution/rolling_friction 缺省=默认 (0.5/0.0/0.1), 兼容旧文件
    col = obj.get('collider')
    if isinstance(col, dict):
        if col.get('shape') in ('box', 'sphere', 'none'):
            m.collider.shape = col['shape']
        m.collider.enabled = bool(col.get('enabled', True))
        m.collider.friction = float(col.get('friction', 0.5))
        m.collider.restitution = float(col.get('restitution', 0.0))
        m.collider.rolling_friction = float(col.get('rolling_friction', 0.1))
        # 2026-10-18 Trigger: 旧文件无此键 -> 缺省 False（兼容不变）
        m.collider.is_trigger = bool(col.get('is_trigger', False))
    return m, oid


def _link_by_map(objects, models, id_map):
    """按 id_map (对象 id -> model) 建父链. objects/models 等长 DFS 前序."""
    for obj, m in zip(objects, models):
        pid = obj.get('parent_id')
        if pid and pid in id_map and id_map[pid] is not m:
            par = id_map[pid]
            m.parent = par
            par.children.append(m)


def _link_parents(objects, models):
    """默认: 以 model.guid 为 id_map (加载场景时 guid == 对象 id)"""
    _link_by_map(objects, models, {m.guid: m for m in models})


# ---------------- 光源 (M21) ----------------

def _emit_light(l):
    """LightState -> dict (M30: 平行光加 3 角度字段; direction 保留为派生兼容旧读者)"""
    return {
        "id": l.guid,
        "name": l.name,
        "kind": l.kind,
        "position": [l.position.x, l.position.y, l.position.z],
        "direction": [l.direction.x, l.direction.y, l.direction.z],
        "azimuth": l.azimuth,      # M30: 平行光 朝向 (度, 0..360)
        "elevation": l.elevation,  # M30: 平行光 俯仰 (度)
        "roll": l.roll,            # M30: 平行光 倾斜 (度, 绕方向线自旋)
        "color": [l.color[0], l.color[1], l.color[2]],
        "intensity": l.intensity,
        "mode": l.mode,          # M29: 'full' 全场景 | 'beam' 光束
        "shape": l.shape,        # M29: 'circle' | 'rect' (beam 截面)
        "size": l.size,          # M29: 光束截面尺寸 (圆=半径/矩形=半边长)
        "shadow": l.shadow,      # M29: 是否投射阴影 (物理遮挡)
        "range": l.range,        # 点光范围 (对齐 Unity Light.range)
        # 2026-10-19 第1档序9 聚光灯: 内外锥角（旧文件无此键 -> 缺省 30/60）
        "spot_inner_angle": getattr(l, 'spot_inner_angle', 30.0),
        "spot_outer_angle": getattr(l, 'spot_outer_angle', 60.0),
    }


def _apply_lights(engine, light_dicts):
    """光源 dict 列表 -> engine.lights (清空重建; 文件 id 覆盖 guid)"""
    engine.lights.clear()
    for d in light_dicts:
        kind = d.get('kind', 'directional')
        # 2026-10-19 第1档序9: 允许 'spot'（旧文件仅 dir/point，非法值降级为 dir）
        if kind not in ('directional', 'point', 'spot'):
            kind = 'directional'
        kwargs = dict(position=_f3(d.get('position'), (0, 5, 0)),
                      direction=_f3(d.get('direction'), (0, -1, 0)),
                      color=_f3(d.get('color'), (1.0, 1.0, 1.0)),
                      intensity=_f1(d.get('intensity'), 1.0),
                      name=d.get('name'),
                      mode=d.get('mode', 'full'),
                      shape=d.get('shape', 'circle'),
                      size=_f1(d.get('size'), 5.0),
                      shadow=d.get('shadow', True),
                      range=_f1(d.get('range'), 10.0),
                      spot_inner_angle=_f1(d.get('spot_inner_angle'), 30.0),
                      spot_outer_angle=_f1(d.get('spot_outer_angle'), 60.0))
        if d.get('azimuth') is not None:   # M30: 优先用 3 角度; 旧文件只有 direction 走反算
            kwargs['azimuth'] = d['azimuth']
            kwargs['elevation'] = d.get('elevation', 0.0)
            kwargs['roll'] = d.get('roll', 0.0)
        l = engine.add_light(kind, **kwargs)
        if d.get('id'):
            l.guid = d['id']


# ---------------- 摄像机 (Unity Camera 概念) ----------------

# ---------------- 天空盒 (beta5 Q1/Q4/Q5/Q6, 人类裁决 2026-11-09) ----------------
# 白盒契约:
#   · Q1=A 新建场景、以及"没有 skybox 键 / 值为 null"的场景 -> **默认纯色蓝天**;
#     默认值只在本文件定义一次 (DEFAULT_SKYBOX_COLOR), 其它模块不得再写字面量。
#   · Q3=A 相机级 skybox 非 None 时优先（"生效的那一个"由 editor 算好交给 engine._skybox）。
#   · Q4=A 颜色只认 0..255 的整数（或整值浮点）; 0-1 浮点 / 越界 / 长度错 -> 明确报错，
#     不得用 int() 静默截断（历史病灶: [0.2,0.4,0.8] -> int -> (0,0,0) 全黑）。
#   · Q5=A 解析失败必须可见: 打印原因, 并让调用方拿到 (valid, reason)。
#   · Q6=A 六面图 paths 以**相对场景目录**的形式序列化, 加载时按 base_dir 解析; 缺文件报错。
DEFAULT_SKYBOX_COLOR = (58, 155, 213, 255)      # #3A9BD5 —— 默认蓝天（白盒契约）
DEFAULT_SKYBOX_NAME = '默认蓝天'


def default_skybox():
    """Q1=A: 默认纯色天空盒（新建场景 / 场景无 skybox 键 / 值解析失败时使用）。"""
    from loom_cubemap import Cubemap
    return Cubemap.from_solid(DEFAULT_SKYBOX_COLOR, name=DEFAULT_SKYBOX_NAME)


def parse_color(v):
    """Q4=A 颜色白盒契约 -> ((r,g,b,a) | None, reason | None).

    接受: '#RRGGBB' / '#RRGGBBAA' / [r,g,b] / [r,g,b,a]，通道必须是 0..255 的 int
    （bool 不算）或**整值浮点**（58.0 可以, 0.2 不行）。拒绝: 0-1 浮点、越界、
    长度不是 3/4、非数值。
    """
    import re as _re
    if isinstance(v, str):
        s = v.strip()
        m = _re.match(r'^#?([0-9a-fA-F]{6})([0-9a-fA-F]{2})?$', s)
        if not m:
            return None, '颜色字符串必须形如 #RRGGBB 或 #RRGGBBAA: %r' % (v,)
        h, a = m.group(1), (m.group(2) or 'FF')
        return ((int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16),
                 int(a, 16)), None)
    if not isinstance(v, (list, tuple)):
        return None, '颜色必须是 #RRGGBB 字符串或 [r,g,b(,a)] 数组: %r' % (v,)
    if len(v) not in (3, 4):
        return None, '颜色数组必须是 3 或 4 个通道: 收到 %d 个 %r' % (len(v), v)
    out = []
    for i, x in enumerate(v):
        if isinstance(x, bool) or not isinstance(x, (int, float)):
            return None, '颜色通道 #%d 必须是数值: %r' % (i, x)
        if isinstance(x, float):
            if not float(x).is_integer():
                return None, ('颜色通道 #%d=%r 不是 0..255 的整数（看起来是 0-1 浮点）; '
                              '请乘 255, 或用 #RRGGBB' % (i, x))
            x = int(x)
        if not (0 <= int(x) <= 255):
            return None, '颜色通道 #%d=%r 超出 0..255' % (i, x)
        out.append(int(x))
    if len(out) == 3:
        out.append(255)
    return tuple(out), None


def skybox_from_dict(d, base_dir=None):
    """Q5=A/Q6=A: dict -> (cube | None, valid: bool, reason | None).

    失败一律给 reason（不抛、不静默）；paths 的相对项按 base_dir（场景目录）解析；
    成功时把**原始（可能相对的）paths** 记到 cube._source_paths，供 _emit_skybox 原样回写。
    """
    if not d:
        return None, False, '缺少 paths/solid_color'
    try:
        from loom_cubemap import Cubemap
    except Exception as e:
        return None, False, 'Cubemap 模块不可用: %r' % (e,)
    paths = d.get('paths')
    if paths:
        if not isinstance(paths, (list, tuple)) or len(paths) != 6:
            return None, False, ('paths 必须是 6 个路径 (px,nx,py,ny,pz,nz): 收到 %r'
                                 % (paths,))
        abs_paths = []
        for i, p in enumerate(paths):
            q = str(p)
            if not os.path.isabs(q):
                q = os.path.join(base_dir or '', q)
            if not os.path.isfile(q):
                return None, False, '第 %d 面图片不存在: %s' % (i, os.path.abspath(q))
            abs_paths.append(os.path.abspath(q))
        try:
            cube = Cubemap.from_files(abs_paths, name=d.get('name'),
                                      guid=d.get('guid'))
        except Exception as e:
            return None, False, '六面图加载失败: %r' % (e,)
        cube._source_paths = [str(p) for p in paths]        # Q6: 保留相对形式
        return cube, True, None
    solid = d.get('solid_color')
    if solid is not None:
        rgba, reason = parse_color(solid)
        if rgba is None:
            return None, False, reason
        try:
            cube = Cubemap.from_solid(rgba, name=d.get('name'), guid=d.get('guid'))
        except Exception as e:
            return None, False, '纯色天空盒创建失败: %r' % (e,)
        return cube, True, None
    return None, False, '缺少 paths/solid_color'


def _apply_skybox(d, base_dir=None):
    """dict -> Cubemap 实例（兼容旧签名）。失败: **出声** + 返回 None（Q5=A）。"""
    cube, valid, reason = skybox_from_dict(d, base_dir)
    if not valid and d:
        print('[场景] 天空盒解析失败: %s' % (reason,))
    return cube


def _scene_skybox_from_data(data, base_dir=None):
    """场景级天空盒 -> (cube, valid, reason)；Q1=A: 缺键/null -> 默认蓝。

    有值但解析失败: 出声 + 回退默认蓝（保证"打开场景一定有天空盒"），valid=False
    由调用方转成可查询的 _skybox_valid/_skybox_error（skybox_get 用）。
    """
    d = data.get('skybox')
    if not d:
        return default_skybox(), True, None
    cube, valid, reason = skybox_from_dict(d, base_dir)
    if valid:
        return cube, True, None
    print('[场景] 天空盒解析失败 (%s) -> 回退默认蓝天盒' % (reason,))
    return default_skybox(), False, reason


def _apply_skybox_or_default(d, base_dir=None):
    """只要 cube 的便捷口（场景级）；缺键/null/解析失败都回落默认蓝。"""
    cube, _valid, _reason = _scene_skybox_from_data({'skybox': d}, base_dir)
    return cube


def _emit_skybox(cube, base_dir=None):
    """Cubemap -> dict（None 时返回 None）.

    Q6=A: paths 优先写**相对场景目录**的形式（_source_paths 原样回写；否则按
    base_dir 做 relpath）。无可用来源（内存态 cubemap）返回 None。
    """
    if cube is None:
        return None
    out = {"name": getattr(cube, 'name', None),
           "guid": getattr(cube, 'guid', None)}
    paths = getattr(cube, 'paths', None)
    if paths:
        src = getattr(cube, '_source_paths', None)
        if src and len(src) == len(paths):
            out["paths"] = [str(p) for p in src]
        elif base_dir:
            rel = []
            for p in paths:
                try:
                    rel.append(os.path.relpath(p, base_dir))
                except Exception:
                    rel.append(p)
            out["paths"] = rel
        else:
            out["paths"] = list(paths)
        return out
    solid = getattr(cube, '_solid_color', None)
    if solid:
        out["solid_color"] = [int(c) for c in solid]
        return out
    return None   # 无可用来源（内存态 cubemap 无法序列化）


def _emit_camera(cam, base_dir=None):
    """CameraState -> dict (M41: 朝向度制 + roll + 俯仰角限制; 2026-08-16 相机物体化 parent_id)

    base_dir: 场景目录（Q6=A: 相机级 skybox 的六面图路径写成相对该目录的形式）。
    """
    return {
        "id": cam.guid,
        "name": cam.name,
        "position": [cam.position.x, cam.position.y, cam.position.z],
        "yaw": cam.yaw,          # 度 [0,360)
        "pitch": cam.pitch,      # 度
        "roll": cam.roll,        # 度 (M41 倾斜)
        "fov": cam.fov,
        "fov_locked": cam.fov_locked,
        "pitch_lock": cam.pitch_lock,     # M41 俯仰角限制: 启用?
        "pitch_min": cam.pitch_min,       # 度 最低俯角 (含)
        "pitch_max": cam.pitch_max,       # 度 最高仰角 (含)
        "parent_id": cam.parent.guid if cam.parent is not None else None,
        # 2026-10-19 第1档序13 天空盒 (C3): 相机级 skybox 覆盖（None=用场景默认）
        "skybox": _emit_skybox(getattr(cam, 'skybox', None), base_dir),
    }


def _apply_cameras(engine, cam_dicts, base_dir=None):
    """摄像机 dict 列表 -> engine.cameras (清空重建; 文件 id 覆盖 guid).
    返回 [(cam, parent_id)] 供 _link_camera_parents 在物体建链后连父 (相机引用物体)."""
    engine.cameras.clear()
    links = []
    for d in cam_dicts:
        cam = engine.add_camera(
            position=_f3(d.get('position'), (0, 0, -5)),
            yaw=_f1(d.get('yaw'), 0.0),
            pitch=_f1(d.get('pitch'), 0.0),
            roll=_f1(d.get('roll'), 0.0),
            fov=_f1(d.get('fov'), 60.0),
            fov_locked=d.get('fov_locked', True),
            name=d.get('name'),
            pitch_lock=d.get('pitch_lock', False),
            pitch_min=d.get('pitch_min', -85.0),
            pitch_max=d.get('pitch_max', 85.0))
        if d.get('id'):
            cam.guid = d['id']
        # 2026-10-19 天空盒: 相机级覆盖（旧文件无此键 -> None=用场景默认）
        # Q5=A: 解析失败出声并记下原因（skybox_get 可查询），不让它静默变"无天空盒"
        _cube, _valid, _reason = skybox_from_dict(d.get('skybox'), base_dir)
        cam.skybox = _cube
        cam._skybox_valid = bool(_valid)
        cam._skybox_error = _reason
        if not _valid and d.get('skybox'):
            print('[场景] 相机 %r 的天空盒解析失败: %s'
                  % (getattr(cam, 'name', '?'), _reason))
        links.append((cam, d.get('parent_id')))
    return links


def _link_camera_parents(engine, links, id_map=None):
    """摄像机父链 (在物体创建并建链后调用): parent_id -> GameObject.guid.
    找不到的 parent_id 忽略 (相机保持根, 防御孤儿引用). 相机物体化 2026-08-16."""
    id_map = id_map or {m.guid: m for m in engine.models}
    for cam, pid in links:
        if pid and pid in id_map:
            cam.parent = id_map[pid]
            id_map[pid].camera_children.append(cam)


# ---------------- 材质资产 (M23) ----------------

def _emit_material(mat):
    """Material -> dict (M36: 含 albedo 贴图引用 path+guid)"""
    d = {"id": mat.guid, "name": mat.name,
         "color": mat.color, "saturation": mat.saturation,
         "metallic": getattr(mat, 'metallic', 0.0),
         "roughness": getattr(mat, 'roughness', 0.5),
         "pbr": getattr(mat, 'pbr', False)}
    alb = getattr(mat, 'albedo', None)
    if alb is not None:
        d["albedo"] = {"guid": alb.guid, "path": alb.path, "name": alb.name,
                       "wrap": alb.wrap, "filter_mode": alb.filter_mode,
                       "aniso": alb.aniso, "max_size": alb.max_size,
                       "mipmaps": alb.mipmaps, "compression": alb.compression}
    nrm = getattr(mat, 'normal_map', None)
    if nrm is not None:
        d["normal_map"] = {"guid": nrm.guid, "path": nrm.path, "name": nrm.name,
                           "wrap": nrm.wrap, "filter_mode": nrm.filter_mode,
                           "aniso": nrm.aniso, "max_size": nrm.max_size,
                           "mipmaps": nrm.mipmaps, "compression": nrm.compression}
    env = getattr(mat, 'env_map', None)
    if env is not None:
        d["env_map"] = {"guid": env.guid, "name": env.name}
        paths = getattr(env, 'paths', None)
        if paths:
            d["env_map"]["paths"] = list(paths)
        else:
            # 2026-11-07: 纯色 Cubemap (from_solid) 无 paths, 旧实现保存即丢.
            solid = getattr(env, '_solid_color', None)
            if solid:
                d["env_map"]["solid_color"] = list(solid)
    return d


def _apply_materials(engine, mat_dicts):
    """材质 dict 列表 -> engine.materials (清空重建; 文件 id 覆盖 guid).
    必须在创建物体之前调用, 这样物体才能通过 material_id 引用库中材质.
    M36: 有 albedo 引用则从文件重建 Texture (文件缺失/解码失败 -> 跳过贴图, 容错)."""
    engine.materials.clear()
    for d in mat_dicts:
        mat = engine.add_material(color=d.get('color'),
                                  saturation=d.get('saturation', 1.0),
                                  name=d.get('name'),
                                  guid=d.get('id'))
        if d.get('id'):
            mat.guid = d['id']
        # M36 PBR: 恢复金属度/粗糙度/PBR 开关
        try:
            mat.metallic = d.get('metallic', 0.0)
            mat.roughness = d.get('roughness', 0.5)
            mat.pbr = d.get('pbr', False)
        except Exception:
            pass
        from loom_texture import Texture
        for slot, key in (('albedo', 'albedo'), ('normal_map', 'normal_map')):
            ref = d.get(key)
            if ref and ref.get('path'):
                try:
                    tex = Texture.from_file(
                        ref['path'], name=ref.get('name'), guid=ref.get('guid'),
                        mipmaps=ref.get('mipmaps', True),
                        wrap=ref.get('wrap', 'repeat'),
                        filter_mode=ref.get('filter_mode', 'trilinear'),
                        aniso=ref.get('aniso', 1.0),
                        max_size=ref.get('max_size', 0),
                        compression=ref.get('compression', 'none'))
                    setattr(mat, slot, tex)
                except Exception:
                    pass                # 贴图文件缺失 -> 保持无贴图 (容错)
        # M36 环境反射: 6 面路径或纯色重建 cubemap
        eref = d.get('env_map')
        if eref:
            try:
                from loom_cubemap import Cubemap
                if eref.get('paths'):
                    mat.env_map = Cubemap.from_files(eref['paths'],
                                                     name=eref.get('name'),
                                                     guid=eref.get('guid'))
                elif eref.get('solid_color'):
                    # 2026-11-07: 纯色 env (from_solid) 往返还原
                    mat.env_map = Cubemap.from_solid(
                        tuple(eref['solid_color']), name=eref.get('name'),
                        guid=eref.get('guid'))
            except Exception:
                pass                    # 文件缺失 -> 保持无 env (容错)


def _is_default_material(mat):
    """材质是否是 add_model 自建的默认材质 (无颜色/贴图/PBR 参数, 名字=材质).

    用于加载期孤儿判定: 只有"默认材质"可以安全丢弃; 用户显式创建的彩色/贴图
    材质即使暂未引用也保留 (资产库语义).
    """
    if mat is None:
        return False
    if getattr(mat, 'color', None) is not None:
        return False
    if getattr(mat, 'pbr', False):
        return False
    if (getattr(mat, 'albedo', None) is not None
            or getattr(mat, 'normal_map', None) is not None
            or getattr(mat, 'env_map', None) is not None):
        return False
    if getattr(mat, 'name', None) not in (None, '材质'):
        return False
    try:
        if abs(float(getattr(mat, 'saturation', 1.0)) - 1.0) > 1e-9:
            return False
        if abs(float(getattr(mat, 'metallic', 0.0))) > 1e-9:
            return False
        if abs(float(getattr(mat, 'roughness', 0.5)) - 0.5) > 1e-9:
            return False
    except (TypeError, ValueError):
        return False
    return True


def _drop_orphan_default_materials(engine, keep_ids, models):
    """D2=A (2026-11-07): 加载时丢弃无物体引用的默认材质.

    每次 load 时每个物体都会先建默认材质再换成文件引用材质, 旧实现把这些
    默认材质留在 engine.materials 并随下次 save 落盘 -> 每次 load->save 材质
    数线性膨胀. 规则:
      - 本次加载新建且无引用 (不在文件材质库 keep_ids 里) -> 丢弃;
      - 文件里显式登记但无引用的"默认形态"材质 -> 丢弃并告警;
      - 文件里显式登记且非默认形态 (有颜色/贴图/PBR/自定义名) -> 保留,
        即使暂未引用 (资产库语义; 保存端不动).
    """
    refs = set()
    for m in models:
        mat = getattr(getattr(m, 'renderer', None), 'material', None)
        if mat is not None:
            refs.add(id(mat))
    dropped = 0
    for mat in list(engine.materials):
        if id(mat) in refs:
            continue
        if id(mat) not in keep_ids or _is_default_material(mat):
            engine.materials.remove(mat)
            dropped += 1
    if dropped:
        print("[sceneio] 警告: 丢弃 %d 个无引用的加载默认材质 (防孤儿膨胀)"
              % dropped)


# ---------------- 场景 ----------------

def _emit_ui_element(elem):
    """UIElement -> dict (递归). 阶段1 支持 panel/text/image."""
    base = {
        'type': elem.ctype,
        'name': elem.name,
        'rect': list(elem.rect),
        'anchor': list(elem.anchor),
        'pivot': list(elem.pivot),
        'visible': bool(elem.visible),
        'enabled': bool(elem.enabled),
        'z_order': int(elem.z_order),
    }
    if elem.ctype == 'panel':
        base['bg_color'] = list(elem.bg_color)
    elif elem.ctype == 'text':
        base['text'] = elem.text
        base['font_size'] = int(elem.font_size)
        base['color'] = list(elem.color)
        base['align'] = elem.align
        base['wrap_width'] = int(elem.wrap_width)
    elif elem.ctype == 'image':
        base['texture_path'] = elem.texture_path
        base['tint'] = list(elem.tint)
        base['fit'] = elem.fit
    elif elem.ctype == 'button':
        base['text'] = elem.text
        base['font_size'] = int(elem.font_size)
        base['text_color'] = list(elem.text_color)
        base['normal_color'] = list(elem.normal_color)
        base['hover_color'] = list(elem.hover_color)
        base['pressed_color'] = list(elem.pressed_color)
        # on_click 不序列化 (运行时由脚本挂载, 契约 §8)
    elif elem.ctype == 'slider':
        base['min_value'] = float(elem.min_value)
        base['max_value'] = float(elem.max_value)
        base['value'] = float(elem.value)
        base['direction'] = elem.direction
        base['track_color'] = list(elem.track_color)
        base['fill_color'] = list(elem.fill_color)
        base['handle_color'] = list(elem.handle_color)
        # on_change 不序列化
    elif elem.ctype == 'toggle':
        base['is_on'] = bool(elem.is_on)
        base['label'] = elem.label
        base['label_size'] = int(elem.label_size)
        base['box_color'] = list(elem.box_color)
        base['check_color'] = list(elem.check_color)
        base['label_color'] = list(elem.label_color)
        # on_change 不序列化
    elif elem.ctype == 'progress_bar':
        base['value'] = float(elem.value)
        base['bg_color'] = list(elem.bg_color)
        base['fill_color'] = list(elem.fill_color)
    elif elem.ctype == 'scroll_view':
        base['content_size'] = list(elem.content_size)
        base['scroll_pos'] = list(elem.scroll_pos)
        base['bg_color'] = list(elem.bg_color)
        base['bar_color'] = list(elem.bar_color)
        base['bar_width'] = int(elem.bar_width)
        base['show_bar'] = bool(elem.show_bar)
        base['scroll_step'] = int(elem.scroll_step)
    elif elem.ctype == 'dropdown':
        base['options'] = list(elem.options)
        base['selected_index'] = int(elem.selected_index)
        base['bg_color'] = list(elem.bg_color)
        base['hover_color'] = list(elem.hover_color)
        base['list_bg'] = list(elem.list_bg)
        base['list_hover'] = list(elem.list_hover)
        base['text_color'] = list(elem.text_color)
        base['font_size'] = int(elem.font_size)
        base['item_height'] = int(elem.item_height)
        # on_change 不序列化
    elif elem.ctype == 'grid_layout':
        base['cell_size'] = [elem.cell_w, elem.cell_h]
        base['spacing'] = [elem.spacing_x, elem.spacing_y]
        base['columns'] = int(elem.columns)
        base['bg_color'] = list(elem.bg_color)
    elif elem.ctype == 'input_field':
        base['text'] = elem.text
        base['placeholder'] = elem.placeholder
        base['max_length'] = int(elem.max_length)
        base['bg_color'] = list(elem.bg_color)
        base['focus_bg_color'] = list(elem.focus_bg_color)
        base['text_color'] = list(elem.text_color)
        base['placeholder_color'] = list(elem.placeholder_color)
        base['cursor_color'] = list(elem.cursor_color)
        base['font_size'] = int(elem.font_size)
        # on_submit / on_change 不序列化 (运行时由脚本挂载, 契约 §8)
    elif elem.ctype == 'shape':
        # 2026-10-20 沙盘 2D 绘制（line/polyline/polygon/circle）
        base['shape_type'] = getattr(elem, 'shape_type', 'line')
        base['points'] = [list(p) for p in (getattr(elem, 'points', []) or [])]
        base['radius'] = float(getattr(elem, 'radius', 0.0))
        sc = getattr(elem, 'stroke_color', None)
        base['stroke_color'] = list(sc) if sc else None
        base['stroke_width'] = int(getattr(elem, 'stroke_width', 2))
        fc = getattr(elem, 'fill_color', None)
        base['fill_color'] = list(fc) if fc else None
        base['segments'] = int(getattr(elem, 'segments', 32))
        base['close'] = bool(getattr(elem, 'close', False))
    # 2026-10-19 P0-5: 声明式事件绑定可序列化（{event: {script, method, owner_guid}}）
    eb = getattr(elem, 'event_bindings', None)
    if eb:
        base['event_bindings'] = dict(eb)
    base['children'] = [_emit_ui_element(c) for c in elem.children]
    return base


def _emit_ui(ui_manager):
    """UIManager -> dict (契约 §8). 空/None -> 空 canvases."""
    if ui_manager is None:
        return {'canvases': []}
    canvases = []
    for c in ui_manager.canvases:
        d = {
            'canvas_type': c.canvas_type,
            'z_order': int(c.z_order),
            'width': int(c.width),
            'height': int(c.height),
            'elements': [_emit_ui_element(c.root)],
        }
        # 2026-10-19 第1档序3阶段4 World Space UI: world 模式三字段
        if c.canvas_type == 'world':
            tgt = getattr(c, 'target', None)
            d['target_id'] = getattr(tgt, 'guid', None) if tgt is not None else None
            d['world_scale'] = float(getattr(c, 'world_scale', 0.01))
            d['billboard'] = bool(getattr(c, 'billboard', True))
        canvases.append(d)
    return {'canvases': canvases}


def _apply_ui_element(d):
    """dict -> UIElement (按 type 分发). 未知类型返回 None + 警告."""
    if not isinstance(d, dict):
        return None
    import loom_ui
    typ = d.get('type', '')
    kw = {
        'name': d.get('name', 'element'),
        'rect': tuple(d.get('rect') or (0, 0, 100, 30)),
        'anchor': tuple(d.get('anchor') or (0, 0)),
        'pivot': tuple(d.get('pivot') or (0, 0)),
        'visible': bool(d.get('visible', True)),
        'enabled': bool(d.get('enabled', True)),
        'z_order': int(d.get('z_order', 0)),
    }
    if typ == 'element':
        # Canvas.root 等纯容器 (无专属字段)
        elem = loom_ui.UIElement(**kw)
    elif typ == 'panel':
        elem = loom_ui.Panel(bg_color=tuple(d.get('bg_color') or (0, 0, 0, 128)), **kw)
    elif typ == 'text':
        elem = loom_ui.Text(text=str(d.get('text', '')),
                            font_size=int(d.get('font_size', 16)),
                            color=tuple(d.get('color') or (255, 255, 255)),
                            align=d.get('align', 'left'),
                            wrap_width=int(d.get('wrap_width', 0)), **kw)
    elif typ == 'image':
        elem = loom_ui.Image(texture_path=str(d.get('texture_path', '')),
                             tint=tuple(d.get('tint') or (255, 255, 255, 255)),
                             fit=d.get('fit', 'stretch'), **kw)
    elif typ == 'button':
        elem = loom_ui.Button(text=str(d.get('text', '')),
                              font_size=int(d.get('font_size', 16)),
                              text_color=tuple(d.get('text_color') or (255, 255, 255)),
                              normal_color=tuple(d.get('normal_color') or (70, 80, 100, 255)),
                              hover_color=tuple(d.get('hover_color') or (90, 100, 125, 255)),
                              pressed_color=tuple(d.get('pressed_color') or (50, 60, 80, 255)),
                              **kw)
    elif typ == 'slider':
        elem = loom_ui.Slider(min_value=float(d.get('min_value', 0.0)),
                              max_value=float(d.get('max_value', 1.0)),
                              value=float(d.get('value', 0.0)),
                              direction=d.get('direction', 'h'),
                              track_color=tuple(d.get('track_color') or (50, 55, 70, 255)),
                              fill_color=tuple(d.get('fill_color') or (80, 140, 220, 255)),
                              handle_color=tuple(d.get('handle_color') or (220, 225, 235, 255)),
                              **kw)
    elif typ == 'toggle':
        elem = loom_ui.Toggle(is_on=bool(d.get('is_on', False)),
                              label=str(d.get('label', '')),
                              label_size=int(d.get('label_size', 16)),
                              box_color=tuple(d.get('box_color') or (70, 80, 100, 255)),
                              check_color=tuple(d.get('check_color') or (80, 200, 120, 255)),
                              label_color=tuple(d.get('label_color') or (230, 230, 230)),
                              **kw)
    elif typ == 'progress_bar':
        elem = loom_ui.ProgressBar(value=float(d.get('value', 0.0)),
                                   bg_color=tuple(d.get('bg_color') or (40, 44, 54, 255)),
                                   fill_color=tuple(d.get('fill_color') or (80, 220, 120, 255)),
                                   **kw)
    elif typ == 'scroll_view':
        elem = loom_ui.ScrollView(content_size=tuple(d.get('content_size') or (300, 800)),
                                  bg_color=tuple(d.get('bg_color') or (30, 34, 44, 255)),
                                  bar_color=tuple(d.get('bar_color') or (120, 130, 150, 255)),
                                  bar_width=int(d.get('bar_width', 8)),
                                  show_bar=bool(d.get('show_bar', True)),
                                  scroll_step=int(d.get('scroll_step', 30)),
                                  **kw)
        if d.get('scroll_pos'):
            elem.scroll_pos = tuple(d['scroll_pos'])
    elif typ == 'dropdown':
        elem = loom_ui.Dropdown(options=list(d.get('options') or []),
                                selected_index=int(d.get('selected_index', 0)),
                                bg_color=tuple(d.get('bg_color') or (70, 80, 100, 255)),
                                hover_color=tuple(d.get('hover_color') or (90, 100, 125, 255)),
                                list_bg=tuple(d.get('list_bg') or (50, 55, 70, 255)),
                                list_hover=tuple(d.get('list_hover') or (80, 140, 220, 255)),
                                text_color=tuple(d.get('text_color') or (255, 255, 255)),
                                font_size=int(d.get('font_size', 14)),
                                item_height=int(d.get('item_height', 28)),
                                **kw)
    elif typ == 'grid_layout':
        cs = tuple(d.get('cell_size') or (64, 64))
        sp = tuple(d.get('spacing') or (8, 8))
        elem = loom_ui.GridLayout(cell_size=cs, spacing=sp,
                                  columns=int(d.get('columns', 4)),
                                  bg_color=tuple(d.get('bg_color') or (0, 0, 0, 0)),
                                  **kw)
        # GridLayout 子元素添加后会自动 reflow (在 add_child 里)
    elif typ == 'input_field':
        elem = loom_ui.InputField(
            text=str(d.get('text', '')),
            placeholder=str(d.get('placeholder', '')),
            max_length=int(d.get('max_length', 200)),
            bg_color=tuple(d.get('bg_color') or (50, 55, 70, 255)),
            focus_bg_color=tuple(d.get('focus_bg_color') or (60, 70, 90, 255)),
            text_color=tuple(d.get('text_color') or (255, 255, 255)),
            placeholder_color=tuple(d.get('placeholder_color') or (140, 140, 150)),
            cursor_color=tuple(d.get('cursor_color') or (220, 220, 230)),
            font_size=int(d.get('font_size', 16)),
            **kw)
    elif typ == 'shape':
        # 2026-10-20 沙盘 2D 绘制（line/polyline/polygon/circle）
        sc = d.get('stroke_color')
        fc = d.get('fill_color')
        elem = loom_ui.Shape(
            shape_type=str(d.get('shape_type') or 'line'),
            points=list(d.get('points') or []),
            radius=float(d.get('radius', 0.0)),
            stroke_color=tuple(sc) if sc else None,
            stroke_width=int(d.get('stroke_width', 2)),
            fill_color=tuple(fc) if fc else None,
            segments=int(d.get('segments', 32)),
            close=bool(d.get('close', False)),
            **kw)
    else:
        print("[sceneio] 警告: 未知 UI 元素类型 %r, 跳过" % typ)
        return None
    # 2026-10-19 P0-5: 恢复声明式事件绑定
    eb = d.get('event_bindings')
    if eb and isinstance(eb, dict):
        try:
            elem.event_bindings = {k: dict(v) if isinstance(v, dict) else v
                                   for k, v in eb.items()}
        except Exception:
            pass
    for cd in (d.get('children') or []):
        ch = _apply_ui_element(cd)
        if ch is not None:
            elem.add_child(ch)
    # GridLayout: 加载完成后强制 reflow (序列化恢复的 child.rect 被自动排列覆盖)
    if typ == 'grid_layout' and hasattr(elem, '_reflow'):
        try:
            elem._reflow()
        except Exception:
            pass
    return elem


def _apply_ui(engine, ui_data):
    """dict -> engine.ui (清空重建). 缺/空 -> 保留一个空默认 Canvas."""
    if not hasattr(engine, 'ui') or engine.ui is None:
        return
    import loom_ui
    engine.ui.clear()
    canvases = (ui_data or {}).get('canvases') or []
    if not canvases:
        # 无 ui 段: 留一个默认 screen Canvas (与引擎 __init__ 一致)
        engine.ui.add_canvas(loom_ui.Canvas(
            canvas_type='screen',
            width=getattr(engine, 'width', 1280),
            height=getattr(engine, 'height', 800)))
        return
    for cd in canvases:
        typ = cd.get('canvas_type', 'screen')
        canvas = loom_ui.Canvas(
            canvas_type=typ,
            width=int(cd.get('width', 1280)),
            height=int(cd.get('height', 800)),
            z_order=int(cd.get('z_order', 0)),
            world_scale=float(cd.get('world_scale', 0.01)),
            billboard=bool(cd.get('billboard', True)))
        # 2026-10-19 第1档序3阶段4: world target 二次绑定
        # 此处 models 尚未建好（_apply_ui 在 _apply_object 之前），暂存 guid，
        # 由 scene_from_dict 末尾 _link_ui_targets 补绑。
        if typ == 'world':
            canvas._pending_target_id = cd.get('target_id')
        for ed in (cd.get('elements') or []):
            root_el = _apply_ui_element(ed)
            if root_el is not None:
                # 第一层元素替换 root (而非作为 root 的子元素)
                canvas.root = root_el
        engine.ui.add_canvas(canvas)


def _link_ui_targets(engine, id_map=None):
    """2026-10-19 第1档序3阶段4: world Canvas target 二次绑定.

    _apply_ui 早于 _apply_object 调用，此时 models 尚未建好。本函数在
    objects + 父链建好后调用，按 guid 把 pending target_id 绑回 GameObject。
    target 不存在（用户删了物体）-> target 保持 None（渲染时跳过）。
    """
    ui = getattr(engine, 'ui', None)
    if ui is None:
        return
    id_map = id_map or {m.guid: m for m in engine.models if m.guid}
    for c in ui.canvases:
        tid = getattr(c, '_pending_target_id', None)
        if tid is None:
            continue
        c.target = id_map.get(tid)
        try:
            delattr(c, '_pending_target_id')
        except Exception:
            pass


def scene_to_dict(engine, camera=None, base_dir=None):
    """引擎场景 -> v7 dict. camera: {'target','distance','yaw','pitch'} 或 None

    base_dir: 场景文件所在目录（Q6=A: skybox 六面图路径按它写成相对形式）。
    保存前校验父链: 成环/不可达抛 SceneCycleError, 绝不静默丢对象."""
    _validate_model_graph(engine.models)
    objs = []
    seen = set()
    for m in engine.models:                    # 只从根开始, DFS 前序
        if m.parent is None:
            _emit_subtree(m, objs, seen)
    # M36 修复 (2026-10-14 小游戏实测): 收集"模型实际引用的材质"—— 未注册进
    # engine.materials 的材质 (脚本/程序化直接赋 Material()) 也一并序列化, 防丢失
    # (原实现只存 engine.materials, 未注册材质的 PBR/贴图/环境全丢 -> 重载变默认材质)。
    mats = list(engine.materials)
    _seen = {id(x) for x in mats}
    for m in engine.models:
        mat = getattr(getattr(m, 'renderer', None), 'material', None)
        if mat is not None and id(mat) not in _seen:
            _seen.add(id(mat))
            mats.append(mat)
    # 2026-11-08 D7=A: 相机投影三件套 (ortho/ortho_size/fov) 是**场景相机属性**,
    # 随场景保存; 写侧与读侧共用 sceneio 的归一 (缺键 -> 取引擎当前值;
    # 非法值 -> 出声后钳制/回落默认) —— 保证"存进去的"和"读回来的"是同一个值。
    if isinstance(camera, dict):
        camera["ortho"] = _b_strict(camera.get("ortho", getattr(engine, "ortho", False)),
                                    False, "保存 camera.ortho")
        camera["ortho_size"] = norm_ortho_size(
            camera.get("ortho_size", getattr(engine, "ortho_size", ORTHO_SIZE_DEFAULT)),
            "保存 camera.ortho_size")
        _fov_deg = camera.get("fov")
        if _fov_deg is None:
            try:
                _fov_deg = math.degrees(float(getattr(engine, "_fov",
                                                      math.radians(FOV_DEFAULT_DEG))))
            except (TypeError, ValueError):
                _fov_deg = FOV_DEFAULT_DEG
        camera["fov"] = norm_fov_deg(_fov_deg, "保存 camera.fov")
    return {"version": SCENE_VERSION, "camera": camera,
            "gravity": getattr(engine, 'gravity', -9.8),   # 2026-08-30: 场景重力加速度
            "materials": [_emit_material(m) for m in mats],
            "lights": [_emit_light(l) for l in engine.lights],
            "cameras": [_emit_camera(c, base_dir) for c in engine.cameras],
            "active_camera": engine.active_camera,
            # 2026-10-19 第1档序13 天空盒 (C3): 场景级默认天空盒
            # 场景级天空盒（Q3=A: **不是**"当前生效的那一个"——相机级覆盖只在渲染时生效，
            # 落盘必须是场景级，否则播放期保存会把相机天空盒烘焙成场景默认）。
            "skybox": _emit_skybox(
                getattr(engine, '_scene_skybox',
                        getattr(engine, '_skybox', None)), base_dir),
            "ui": _emit_ui(getattr(engine, 'ui', None)),   # 2026-10-18: Canvas UI
            "objects": objs}


def scene_from_dict(engine, data, camera_out=None, base_dir=None):
    """dict -> 引擎场景 (容错加载). 返回创建的模型列表.
    camera_out: dict 则把相机字段写进去 (编辑器/运行时自行应用).
    base_dir: 场景文件目录（Q6=A: skybox 相对路径按它解析）。"""
    data = migrate(data)
    # 2026-11-07: 父链成环 -> 拒绝加载 (成环对象无根, DFS 会静默丢整棵).
    # 必须在清空/重建引擎状态之前校验, 保证失败时旧场景不被破坏.
    _objects_in = data.get('objects', [])
    if not isinstance(_objects_in, list):
        _objects_in = []
    _validate_object_graph(_objects_in)
    # 2026-08-30: 场景级重力加速度 (缺失=保留引擎当前值)
    engine.gravity = float(data.get('gravity', getattr(engine, 'gravity', -9.8)))
    # 2026-10-19 第1档序13 天空盒 (C3): 场景级默认天空盒（旧文件无此键 -> None）
    # 2026-11-09 beta5 Q1=A: 缺键/null -> 默认蓝天盒（吃豆人这类旧场景不再是黑底）；
    # Q5=A: 有值但解析失败 -> 出声 + 回退默认蓝，并把 (valid, reason) 挂在引擎上供
    # skybox_get / 编辑器查询（不得静默）。
    _cube, _sb_valid, _sb_reason = _scene_skybox_from_data(data, base_dir)
    # 场景级（落盘/查询用）与"生效"（渲染端只读 _skybox）在加载后是同一个对象；
    # editor 会在 _load_scene 里按 active camera 再算一次生效值（Q3=A）。
    engine._scene_skybox = _cube
    engine._skybox = _cube
    engine._skybox_valid = bool(_sb_valid)
    engine._skybox_error = _sb_reason
    _apply_ui(engine, data.get('ui'))                # 2026-10-18: Canvas UI (清空重建)
    _apply_lights(engine, data.get('lights', []))   # M21: 场景光源 (清空重建)
    cam_links = _apply_cameras(engine, data.get('cameras', []), base_dir)  # 场景摄像机 (清空重建)
    engine.active_camera = data.get('active_camera')  # 玩家视角摄像机
    _apply_materials(engine, data.get('materials', []))  # M23: 材质库 (先于物体, 供引用)
    # 2026-11-07 D2=A: 文件显式登记的材质 (keep_ids) 与 add_model 自建材质区分
    _lib_keep = {id(x) for x in engine.materials}
    objects = _objects_in
    models = []
    for obj in objects:
        m, _ = _apply_object(engine, obj)
        models.append(m)
    _link_parents(objects, models)          # 物体先建父链
    _link_camera_parents(engine, cam_links)  # 2026-08-16 相机物体化: 相机挂父引用物体, 必须在物体之后
    # 2026-11-07 D2=A: 加载时丢弃无引用默认材质 (防 load->save 材质孤儿线性膨胀)
    _drop_orphan_default_materials(engine, _lib_keep, models)
    # 2026-10-19 第1档序3阶段4: world Canvas target 二次绑定（物体已建好）
    try:
        _link_ui_targets(engine)
    except Exception:
        pass
    if camera_out is not None and data.get('camera'):
        cam = data['camera']
        camera_out.update({
            'target': _f3(cam.get('target'), (0, 0, 0)),
            'distance': _f1(cam.get('distance'), 10.0),
            'yaw': _f1(cam.get('yaw'), 0.6),
            'pitch': _f1(cam.get('pitch'), -0.35),
            # 2026-11-08 D7=A: 投影三件套是场景相机属性 -> 与写侧同一套归一
            # (Q4=B: 非法值出声后钳制/回落, 不静默错值、不崩)
            'ortho': _b_strict(cam.get('ortho'), False, '场景 camera.ortho'),
            'ortho_size': norm_ortho_size(cam.get('ortho_size'),
                                          '场景 camera.ortho_size'),
            'fov': norm_fov_deg(cam.get('fov'), '场景 camera.fov'),
        })
    return models


def migrate(data):
    """版本迁移 (原地修改并返回). 旧格式/缺版本一律能加载."""
    v = data.get('version', 1) if isinstance(data, dict) else 1
    if not isinstance(data, dict):
        data = {'version': SCENE_VERSION, 'objects': []}
        v = SCENE_VERSION
    if v < 1:
        data = {'version': SCENE_VERSION, 'objects': list(data.get('objects', []))}
        v = SCENE_VERSION
    if v < 3:
        # v1/v2 -> v3: 补光源数组 (旧存档无光源, 默认空)
        data.setdefault('lights', [])
    if v < 4:
        # v3 -> v4 (M25 组件化): 单 "script" 字段 -> "scripts" 数组 (物体可挂多个脚本)
        for obj in data.get('objects', []):
            sc = obj.get('script')
            if isinstance(sc, dict) and sc.get('id') and 'scripts' not in obj:
                obj['scripts'] = [sc]
            obj.pop('script', None)
    if v < 5:
        # v4 -> v5 (M23 材质资产): 补空材质库; 旧对象无 material_id,
        # _apply_object 会自动按颜色/饱和度自建材质, 无需改写对象.
        data.setdefault('materials', [])
    if v < 6:
        # v5 -> v6 (M28 碰撞体): 旧对象无 collider 字段 -> 加载时按类型自动派生
        # (球=球体, 其他=盒子), 无需改写对象.
        pass
    if v < 7:
        # v6 -> v7 (摄像机实体): 旧存档无摄像机, 补空数组 + active_camera 空
        data.setdefault('cameras', [])
        data.setdefault('active_camera', None)
    if v < 8:
        # v7 -> v8 (M29 光照遮挡/光束): 旧光源补 mode/shape/size/shadow 默认
        for lt in data.get('lights', []):
            lt.setdefault('mode', 'full')
            lt.setdefault('shape', 'circle')
            lt.setdefault('size', 5.0)
            lt.setdefault('shadow', True)
    if v < 9:
        # v8 -> v9 (M41 摄像机度制朝向): 旧摄像机 yaw/pitch 由弧度转度, 补 roll=0
        # 与俯仰角限制默认. **只改 cameras 数组; 顶层编辑器轨道 "camera" dict 仍是
        # 弧度 (那是导航相机不是 CameraState), 不碰.**
        for cm in data.get('cameras', []):
            cm['yaw']   = wrap_deg(math.degrees(cm.get('yaw', 0.0)), 0.0, 360.0)
            cm['pitch'] = wrap_deg(math.degrees(cm.get('pitch', 0.0)), -180.0, 180.0)
            cm['roll']  = wrap_deg(cm.get('roll', 0.0), -180.0, 180.0)
            cm.setdefault('pitch_lock', False)
            cm.setdefault('pitch_min', -85.0)
            cm.setdefault('pitch_max', 85.0)
    if v < 10:
        # v9 -> v10 (2026-08-16 相机物体化): 旧摄像机无父, 补 parent_id=None
        for cm in data.get('cameras', []):
            cm.setdefault('parent_id', None)
    if v == 1:
        # v1: 扁平对象, 有 id 无 parent/prefab; 无 id 就生成一个
        for obj in data.get('objects', []):
            if not obj.get('id'):
                obj['id'] = generate_guid()
            obj.setdefault('parent_id', None)
            obj.setdefault('prefab_ref', None)
    data['version'] = SCENE_VERSION
    return data


def save_json_atomic(path, data):
    """原子写 JSON: 写 .tmp + fsync + os.replace."""
    p = os.path.abspath(path)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    tmp = p + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, p)
    return p


_ENC_MAGIC = "LOOMSC1"   # M38: 混淆场景文件头 (识别 + 防误当明文 JSON)
_XOR_KEY = 0x5A          # 简单 XOR 混淆密钥 (提高门槛, 非绝对保密)


def encode_blob(data):
    """LOOMSC1 混淆编码 dict (压缩+XOR+base64, 2026-08-22 提取供场景/游戏包共用).
    模仿 Unity 二进制资源: 玩家不可直接读, 非绝对保密 (门槛级保护)."""
    text = json.dumps(data, ensure_ascii=False).encode('utf-8')
    comp = zlib.compress(text)
    return _ENC_MAGIC + base64.b64encode(
        bytes(b ^ _XOR_KEY for b in comp)).decode('ascii')


def decode_blob(content):
    """LOOMSC1 混淆解码: 返回原数据; 内容非法/非混淆格式返回 None."""
    if not content.startswith(_ENC_MAGIC):
        return None
    try:
        b = base64.b64decode(content[len(_ENC_MAGIC):])
        return json.loads(zlib.decompress(
            bytes(x ^ _XOR_KEY for x in b)).decode('utf-8'))
    except Exception:
        return None


def save_scene_data(path, data, encrypt=False):
    """M38: 场景数据写盘. encrypt=True 用混淆(压缩+XOR+base64)提高门槛
    (玩家不可直接读, 模仿 Unity 二进制资源; 非绝对保密).
    encrypt=False 明文 JSON (开发者编辑用). 两种都能被 load_scene_data 读回."""
    p = os.path.abspath(path)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    if encrypt:
        content = encode_blob(data)
    else:
        content = json.dumps(data, ensure_ascii=False, indent=2)
    tmp = p + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        f.write(content)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, p)
    return p


def load_scene_data(path):
    """M38: 读场景文件(明文 JSON 或 LOOMSC 混淆), 返回 dict 或 None."""
    try:
        with open(path, 'r', encoding='utf-8') as f:
            text = f.read()
    except OSError:
        return None
    if text.startswith(_ENC_MAGIC):
        return decode_blob(text)
    try:
        return json.loads(text)
    except ValueError:
        return None


# ---------------- 资源资产 (M24 资源浏览器面板) ----------------
# 独立资产文件: 材质 -> assets/materials/*.json, 网格 -> assets/meshes/*.json,
# Prefab -> assets/*.prefab (M16). 材质资产文件内容与 _emit_material 同构 (含 guid),
# 供资源浏览器面板列出/点选预览/拖到场景; 跨文件引用统一走 guid.

ASSET_VERSION = 1


def material_to_dict(mat):
    """Material -> 材质资产 dict (与 _emit_material 同构 + version)"""
    return {** _emit_material(mat), "version": ASSET_VERSION}


def save_material_asset(path, mat):
    """材质落盘为独立资产文件 (assets/materials/*.json). 返回绝对路径."""
    return save_json_atomic(path, material_to_dict(mat))


def load_material_asset(path):
    """读取材质资产文件 -> dict (id/name/color/saturation). 损坏/缺 id 返回 None."""
    try:
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict) or not data.get('id'):
        return None
    data.setdefault('name', '材质')
    data.setdefault('color', None)
    data.setdefault('saturation', 1.0)
    return data


def save_mesh_asset(path, primitive, params):
    """网格落盘为独立资产文件 (assets/meshes/*.json): 基元 spec + 资产 guid.
    返回绝对路径."""
    data = {"version": ASSET_VERSION, "id": generate_guid(),
            "type": primitive or 'cube',
            "params": dict(params) if params else {}}
    return save_json_atomic(path, data)


def load_mesh_asset(path):
    """读取网格资产文件 -> dict (type/params/id). 损坏/缺 type 返回 None."""
    try:
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict) or not data.get('type'):
        return None
    data.setdefault('params', {})
    return data


# ---------------- Prefab ----------------

def prefab_to_dict(root):
    """子树根 -> prefab 资产 dict (局部对象 id, 根 id = prefab guid)"""
    pguid = root.guid or generate_guid()
    objs = []
    _emit_subtree(root, objs)
    return {"version": PREFAB_VERSION,
            "prefab": {"guid": pguid, "name": root.name},
            "objects": objs}


def save_prefab(path, root):
    save_json_atomic(path, prefab_to_dict(root))


def load_prefab(path):
    with open(path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    if data.get('version', 1) < 1:
        data['version'] = 1
    return data


def instantiate_prefab(engine, data, offset=(0, 0, 0)):
    """场景中实例化 prefab: 全部对象重新生成 GUID, 挂 prefab_ref, 根整体平移.
    返回创建的模型列表 (空 prefab 返回 [])."""
    objects = data.get('objects', [])
    if not isinstance(objects, list):
        objects = []
    _validate_object_graph(objects)     # 2026-11-07: Prefab 父链成环拒绝实例化
    pguid = data.get('prefab', {}).get('guid')
    models = []
    old_id_map = {}                       # 模板旧 id -> 新模型
    for obj in objects:
        m, oid = _apply_object(engine, obj)   # 此刻 m.guid = 模板 id
        old_id_map[oid] = m
        m.guid = generate_guid()          # 实例与模板解耦
        m.prefab_ref = pguid
        models.append(m)
    _link_by_map(objects, models, old_id_map)   # 用模板 id 键建父链
    if models:
        r = models[0]                     # DFS 前序根
        r.position = Point3D(r.position.x + offset[0],
                             r.position.y + offset[1],
                             r.position.z + offset[2])
    return models
