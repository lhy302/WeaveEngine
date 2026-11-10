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
from loom_components import animator_from_dict, animator_to_dict
from mesh import create_cube, spec_to_mesh

SCENE_VERSION = 11  # v11 (beta6 B1 资产 guid): 贴图/六面图引用只写 guid (旧路径字段可读+告警)
PREFAB_VERSION = 1

# ============================================================================
# beta6 C1/D7: 引擎版本闸门
# ----------------------------------------------------------------------------
# 背景: migrate() 只抬 version、不认"更高版本写下的新字段" —— 旧引擎读新场景
# 会把 animator.speed / clip_meta 等未知键**静默丢弃** (research_beta6_03 §④ R1)。
# 现在场景写入 min_engine_version(=当前引擎版本), 加载时低版本引擎明确拒绝。
# 兼容: 旧场景/第三方(Hub)写出的场景没有该字段 -> 不设闸, 行为与以前一致。
# ============================================================================
# 兜底常量：只在"产物里没有 解释器.json"时触发（旧包/手工拷贝）。
# 2026-11-10 起 build_engine / package_engine_compiled 都会把 解释器.json 带进
# dist 并在构建时断言版本一致 —— 正常产物必带，不应走到这里。
_ENGINE_VERSION_FALLBACK = '0.1.0.beta6'


def _read_engine_version():
    """当前引擎版本. 单一事实源 = 引擎目录 解释器.json; 读不到 -> 常量兜底."""
    try:
        p = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                         '解释器.json')
        with open(p, 'r', encoding='utf-8') as f:
            v = json.load(f).get('version')
        if isinstance(v, str) and v.strip():
            return v.strip()
    except Exception:
        pass
    return _ENGINE_VERSION_FALLBACK


ENGINE_VERSION = _read_engine_version()


class SceneVersionError(ValueError):
    """场景要求的引擎版本高于当前引擎 —— 明确拒绝加载 (不静默丢字段)."""


def parse_version(text):
    """版本串 -> 可比较 5 元组; 无法解析 -> None.

    '0.1.0.beta6' / '0.1.0-beta6' -> (0, 1, 0, 0, 6)   第 4 位 0 = 预发布
    '0.1.0'                       -> (0, 1, 0, 1, 0)   第 4 位 1 = 正式版
    '1.2'                         -> (1, 2, 0, 1, 0)
    '1.2.3+build.5'               -> (1, 2, 3, 1, 0)   (丢弃 '+' 之后的构建元数据)

    R6 F-02: 分隔符统一 ('.' / '-' / '_' 等价) —— 旧实现把 '0.1.0-beta6'
    判成不可解析, 而 check_engine_version 那时是"解析失败即放行" -> 闸门静默
    fail-open。现在解析失败在**要求侧**是拒绝 (见 check_engine_version)。
    """
    if not isinstance(text, str):
        return None
    s = text.strip().lower()
    if not s:
        return None
    s = s.split('+', 1)[0]              # 构建元数据不影响比较
    for ch in ('-', '_'):
        s = s.replace(ch, '.')
    nums = []
    beta = None
    for part in s.split('.'):
        part = part.strip()
        if not part:
            continue
        if part.isdigit():
            nums.append(int(part))
        elif part.startswith('beta'):
            tail = part[4:]
            if tail and not tail.isdigit():
                return None
            beta = int(tail) if tail else 0
        else:
            return None                 # 未知段 (rc1/alpha/日期) -> 不可判定
    if not nums:
        return None
    while len(nums) < 3:
        nums.append(0)
    if beta is None:
        return (nums[0], nums[1], nums[2], 1, 0)
    return (nums[0], nums[1], nums[2], 0, beta)


def version_lt(current, required):
    """current 是否低于 required. 任一不可解析 -> False (无法判定则不拦)."""
    a = parse_version(current)
    b = parse_version(required)
    if a is None or b is None:
        return False
    return a < b


def check_engine_version(data, engine_version=None):
    """加载前版本闸门. 不满足抛 SceneVersionError(带原因), 通过返回 True.

    - 无 min_engine_version (旧场景 / Hub 写出的场景) -> 不设闸 (向后兼容);
    - min_engine_version **不可解析** -> 拒绝 (R6 F-02: 旧实现"解析失败即放行"
      等于闸门静默 fail-open —— 更旧的引擎会带着未知字段静默加载);
    - 引擎自身版本不可解析 -> 显式告警后放行 (无法比较; 但不静默, 打一行);
    - 当前引擎低于要求 -> 拒绝, 原因里同时给出"要求版本 / 当前版本".
    """
    if not isinstance(data, dict):
        return True
    need = data.get('min_engine_version')
    if not isinstance(need, str) or not need.strip():
        return True
    need = need.strip()
    cur = engine_version if engine_version is not None else ENGINE_VERSION
    need_p = parse_version(need)
    if need_p is None:
        raise SceneVersionError(
            '场景 min_engine_version=%r 无法解析: 拒绝加载 (无法判定版本要求时'
            '不放行, 以免旧引擎静默丢字段; 请修正该字段或删掉它)' % (need,))
    cur_p = parse_version(cur)
    if cur_p is None:
        print('[场景] 当前引擎版本 %r 无法解析: 无法比较 min_engine_version=%r,'
              ' 本次放行 (请修正 解释器.json 的 version)' % (cur, need))
        return True
    if cur_p < need_p:
        raise SceneVersionError(
            '场景要求引擎 >= %s, 当前引擎 %s: 拒绝加载 (旧引擎读新场景会静默丢字段, '
            '请先升级引擎, 或用旧版引擎"导出兼容场景"后重试)' % (need, cur))
    return True


def generate_guid():
    return uuid.uuid4().hex


# ---------------- 资产身份层 (beta6 B1: 项目 Assets/ + guid) ----------------
_TEXTURE_IMPORT_KEYS = ('mipmaps', 'wrap', 'filter_mode', 'aniso', 'max_size',
                        'compression')


def asset_context(base_dir=None, create=False):
    """场景目录 -> 资产上下文；无项目 <root>/Assets/assets.json 时返回 None。

    None = **旧路径模式**（无项目资产库）：一切行为与 beta5 完全一致（兼容闸门）。
    """
    try:
        from loom_assets import context_for_scene
        return context_for_scene(base_dir, create=create)
    except Exception:
        return None


# F-02: 资产问题上限（超出只计数，不再 append/print）——旧实现 item in errs
# 是 O(N) 扫描 -> 5000 条 313ms；现在 set 去重 O(1) + 打印上限 200。
ASSET_ERROR_LIMIT = 200


def reset_asset_errors(engine):
    """清空资产问题（换场景/新建场景统一入口；连同去重键与溢出计数）。"""
    try:
        engine._asset_errors = []
        engine._asset_error_keys = set()
        engine._asset_error_overflow = 0
    except Exception:
        pass


def record_asset_error(engine, where, guid, reason):
    """把资产解析失败/过期挂到引擎（形状对齐 _skybox_valid/_skybox_error）。

    O(1) 追加：去重键放在 set 里（不再线性扫描列表）；超过 ASSET_ERROR_LIMIT
    只累加 overflow 计数，不 append、不打印（避免脏场景刷屏 + 二次方耗时）。
    """
    if not reason:
        return
    try:
        errs = getattr(engine, '_asset_errors', None)
        if errs is None:
            errs = []
            engine._asset_errors = errs
            engine._asset_error_keys = set()
            engine._asset_error_overflow = 0
        keys = getattr(engine, '_asset_error_keys', None)
        if not isinstance(keys, set):
            keys = set(errs)
            engine._asset_error_keys = keys
    except Exception:
        return
    gid = guid if isinstance(guid, str) else None
    item = (str(where), gid, str(reason))
    if item in keys:
        return
    keys.add(item)
    if len(errs) >= ASSET_ERROR_LIMIT:
        try:
            engine._asset_error_overflow = int(
                getattr(engine, '_asset_error_overflow', 0) or 0) + 1
        except Exception:
            pass
        return
    errs.append(item)
    print('[资产] %s: %s%s' % (where, reason, ('  (guid=%s)' % gid) if gid else ''))


def asset_errors(engine):
    """引擎上累积的资产问题 [(where, guid, reason)]（只读副本，已截断到上限）。"""
    return list(getattr(engine, '_asset_errors', None) or [])


def asset_error_count(engine):
    """资产问题总数（含超出上限被折叠的计数）。"""
    errs = getattr(engine, '_asset_errors', None) or []
    try:
        over = int(getattr(engine, '_asset_error_overflow', 0) or 0)
    except Exception:
        over = 0
    return len(errs) + over


def _keep_slot_ref(mat, slot, ref):
    """Q-B1-1=A: 解析失败时把**原始引用**留在材质对象上，保存时原样写回。

    没有这一步，一次 Ctrl+S 就会把 guid 引用永久销毁（轮5 审计 P-01：
    贴图文件被删/索引缺失/索引坏 -> 打开告警 -> 保存后 albedo 整键消失、
    天空盒被替换成"默认蓝天 + 新随机 guid"）。
    """
    if not isinstance(ref, dict) or not ref:
        return
    try:
        slots = getattr(mat, '_asset_ref_slots', None)
        if not isinstance(slots, dict):
            slots = {}
            mat._asset_ref_slots = slots
        slots[slot] = dict(ref)
    except Exception:
        pass


def _clear_slot_ref(mat, slot):
    """槽位解析成功 -> 丢掉保留的旧引用（不让旧 ref 覆盖新资产）。"""
    try:
        slots = getattr(mat, '_asset_ref_slots', None)
        if isinstance(slots, dict):
            slots.pop(slot, None)
            if not slots:
                mat._asset_ref_slots = None
    except Exception:
        pass


def clear_asset_slot(mat, slot):
    """用户**显式清空**某个槽位时调用：连"保留的失效引用"一起清掉。

    Q-B1-1=A 的边界：解析失败保留引用；用户主动清空才算移除（否则一次 Ctrl+S
    之后旧引用又从 _asset_ref_slots 复活）。
    """
    _clear_slot_ref(mat, slot)


def asset_refs_kept(engine):
    """本次保存会"原样写回"的失效引用条数（材质槽 + 场景/相机天空盒）。"""
    n = 0
    seen = set()
    try:
        mats = list(getattr(engine, 'materials', None) or [])
        for mdl in list(getattr(engine, 'models', None) or []):
            mat = getattr(getattr(mdl, 'renderer', None), 'material', None)
            if mat is not None:
                mats.append(mat)
        for mat in mats:
            if id(mat) in seen:
                continue
            seen.add(id(mat))
            slots = getattr(mat, '_asset_ref_slots', None)
            if isinstance(slots, dict):
                # 与 _emit_material 完全同口径：只有"槽位为空 + 有保留引用"才会写回
                for slot, ref in slots.items():
                    if not isinstance(ref, dict) or not ref:
                        continue
                    if getattr(mat, slot, None) is None:
                        n += 1
    except Exception:
        pass
    try:
        if isinstance(getattr(engine, '_skybox_ref', None), dict) \
                and getattr(engine, '_skybox_valid', True) is False:
            n += 1
        for cam in list(getattr(engine, 'cameras', None) or []):
            if isinstance(getattr(cam, '_skybox_ref', None), dict) \
                    and getattr(cam, 'skybox', None) is None:
                n += 1
    except Exception:
        pass
    return n


def asset_issue_notice(engine, where='打开'):
    """给编辑器/播放器的一句可见提示（没有资产问题返回 None）。"""
    n_err = asset_error_count(engine)
    kept = asset_refs_kept(engine)
    if not n_err and not kept:
        return None
    parts = []
    if n_err:
        parts.append('%d 条资产问题' % (n_err,))
    if kept:
        parts.append('%d 条失效引用已保留（保存不会改写）' % (kept,))
    return '资产：%s —— scene_assets_check 可查看明细' % ('，'.join(parts))


def _texture_ref_dict(tex, ctx=None):
    """Texture -> 场景引用 dict。项目托管资产**只写 guid**（路径永不落盘）。"""
    guid = getattr(tex, 'guid', None)
    if ctx is not None and ctx.owns(guid, 'texture'):
        return {'guid': guid, 'name': getattr(tex, 'name', None)}
    ref = {'guid': guid, 'path': getattr(tex, 'path', None),
           'name': getattr(tex, 'name', None)}
    for k in _TEXTURE_IMPORT_KEYS:
        v = getattr(tex, k, None)
        if v is not None:
            ref[k] = v
    return ref


def _cubemap_ref_dict(cube, ctx=None):
    """Cubemap -> 引用 dict。托管资产只写 guid；否则沿用 beta5 的 paths/纯色。"""
    if cube is None:
        return None
    guid = getattr(cube, 'guid', None)
    out = {'name': getattr(cube, 'name', None), 'guid': guid}
    if ctx is not None and ctx.owns(guid, 'cubemap'):
        return out
    paths = getattr(cube, 'paths', None)
    if paths:
        out['paths'] = list(paths)
        return out
    solid = getattr(cube, '_solid_color', None)
    if solid:
        out['solid_color'] = [int(c) for c in solid]
        return out
    return None


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


def _emit_object(m, ctx=None):
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
        # M35 动画 / beta6 C1: 序列化走唯一实现 (speed + 每片段 loop_mode 是
        # v11 的增量字段; time/playing **不落盘** —— 只作编辑器预览态, 存盘=回
        # 起点, 见 animator_to_dict 的契约说明与 test_animation_base.py).
        "animator": animator_to_dict(m.animator),
    }


def _emit_subtree(m, out, seen=None, ctx=None):
    """DFS 前序输出子树. seen 共享集合用于检测重复/成环 (防无限递归)."""
    if seen is None:
        seen = set()
    key = id(m)
    if key in seen:
        raise SceneCycleError(
            "序列化父链成环/对象重复: %r" % (getattr(m, 'name', m),))
    seen.add(key)
    out.append(_emit_object(m, ctx))
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


def _apply_object(engine, obj, ctx=None):
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
        if mat is None and ctx is not None and ctx.owns(mat_id, 'material'):
            # beta6 B1: 材质资产（assets.json）里的 guid 终于能回查到（修探针 I 段缺陷）
            mat, _mok, _mwhy = ctx.material(mat_id)
            if _mwhy:
                record_asset_error(engine, 'objects.material_id', mat_id, _mwhy)
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
    # 动画 (M35): 文件有 animator 字段则加 (重建 AnimationClip).
    # beta6 C1: 解析收敛到 loom_components.animator_from_dict —— 与
    # scene_driver.load_from_data 共用同一份 (旧文件无 speed/clip_meta 兼容).
    an = obj.get('animator')
    if isinstance(an, dict) and isinstance(an.get('clips'), dict):
        clips, cur, loop, speed = animator_from_dict(an)
        m.add_animator(clips=clips, current=cur, loop=loop)
        m.animator.speed = speed
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
#   · A3=B 六面图**必须位于场景目录内（允许子目录）**：
#         加载时绝对路径与 `..` 越界一律拒绝（valid=False + reason 点名）；
#         保存时若算出的相对路径越界（绝对 / `..` 开头 / 跨盘符）-> **不写出该天空盒**
#         并把原因记进 _skybox_valid/_skybox_error（绝不静默写一个将来加载必然失败的值）。
DEFAULT_SKYBOX_COLOR = (58, 155, 213, 255)      # #3A9BD5 —— 默认蓝天（白盒契约）
DEFAULT_SKYBOX_NAME = '默认蓝天'


def default_skybox():
    """Q1=A: 默认纯色天空盒（新建场景 / 场景无 skybox 键 / 值解析失败时使用）。"""
    from loom_cubemap import Cubemap
    return Cubemap.from_solid(DEFAULT_SKYBOX_COLOR, name=DEFAULT_SKYBOX_NAME)


def parse_color(v):
    """Q4=A 颜色白盒契约 -> ((r,g,b,a) | None, reason | None).

    接受: '#RRGGBB' / '#RRGGBBAA' / [r,g,b] / [r,g,b,a]，通道必须是 0..255 的 int
    （bool 不算）或**整值浮点**（58.0 可以, 0.2 不行）。
    拒绝（Q4=A 收严，P2-3）: '# 前缀缺失'（'3A9BD5' 不再放行）、0-1 浮点、nan/inf、
    越界、长度不是 3/4、非数值 —— 每条都带各自的原因，便于调用方提示。
    """
    import math as _m
    import re as _re
    if isinstance(v, str):
        s = v.strip()
        m = _re.match(r'^#([0-9a-fA-F]{6})([0-9a-fA-F]{2})?$', s)
        if not m:
            return None, ('颜色字符串必须是 #RRGGBB 或 #RRGGBBAA（**必须带 # 前缀**）: %r'
                          % (v,))
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
            if not _m.isfinite(float(x)):
                return None, ('颜色通道 #%d 不是有限数 (nan/inf): %r'
                              % (i, x))          # P2-3: 不再误报成"0-1 浮点"
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


def _inside_scene_dir(abs_path, base_dir):
    """A3=B: 路径必须落在场景目录（含子目录）内 -> (ok, reason)。

    用 realpath + commonpath 比较（Windows 下不区分大小写，且 realpath 会解析
    符号链接/8.3 短名）；跨盘符时 commonpath 抛 ValueError -> 视为越界。
    """
    try:
        root = os.path.realpath(os.path.abspath(base_dir))
        p = os.path.realpath(os.path.abspath(abs_path))
    except Exception as e:
        return False, '路径规范化失败: %r' % (e,)
    win = (os.name == 'nt') or (len(root) > 1 and root[1] == ':')
    root_c, p_c = (root.lower(), p.lower()) if win else (root, p)
    try:
        same = (os.path.commonpath([root_c, p_c]) == root_c)
    except ValueError:
        return False, '与场景目录不在同一盘符（越界）'
    if same:
        return True, None
    return False, '不在场景目录内'


def skybox_from_dict(d, base_dir=None, ctx=None):
    """Q5=A/Q6=A: dict -> (cube | None, valid: bool, reason | None).

    v11 新增: {"guid": ...} = 项目资产（走 ctx 解析，越界/缺文件都给 reason）。
    paths 的相对项按 base_dir（场景目录）解析；成功时把**原始（可能相对的）paths**
    记到 cube._source_paths，供 _emit_skybox 原样回写。
    """
    if not isinstance(d, dict):
        # P1-2（回归修复）: 场景里的 'skybox' 可能是 str / list / int / bool（手改或旧工具写入）。
        # 绝不能走到 d.get() 抛 AttributeError —— 那会让整个 scene_from_dict 崩，而编辑器
        # _load_scene 此时已经改掉 _scene_path、清空了旧模型 => 用户直接丢当前场景（违背 F7）。
        return None, False, "'skybox' 必须是对象 (dict)，实际 %s: %r" % (
            type(d).__name__, d)
    if not d:
        return None, False, '缺少 guid/paths/solid_color'
    _guid = d.get('guid')
    _legacy_payload = ('paths' in d) or ('solid_color' in d)
    if isinstance(_guid, str) and _guid and not _legacy_payload:
        # 只有 "纯 guid 引用" 才是项目资产；带 paths/solid_color 的是 beta5 旧字段
        # （guid 只是历史身份），继续走旧解析 —— 兼容闸门。
        if ctx is None:
            return None, False, ('天空盒是资产 guid (%s) 但当前项目没有资产索引'
                                 '（缺 Assets/assets.json）' % (_guid,))
        cube, _ok, _why = ctx.cubemap(_guid, d)
        if cube is None:
            return None, False, '天空盒资产解析失败: %s' % (_why,)
        return cube, True, _why
    try:
        from loom_cubemap import Cubemap
    except Exception as e:
        return None, False, 'Cubemap 模块不可用: %r' % (e,)
    paths = d.get('paths')
    if paths:
        if not isinstance(paths, (list, tuple)) or len(paths) != 6:
            return None, False, ('paths 必须是 6 个路径 (px,nx,py,ny,pz,nz): 收到 %r'
                                 % (paths,))
        # A3=B（人类裁决 2026-11-09）: 六面图**必须位于场景目录内（允许子目录）**;
        # 绝对路径与 `..` 越界一律拒绝（换机/越权读盘都不允许）。
        root = os.path.abspath(base_dir or os.getcwd())
        abs_paths = []
        for i, p in enumerate(paths):
            q = str(p)
            if os.path.isabs(q):
                return None, False, ('第 %d 面是绝对路径 (%s); 六面图必须放在场景目录'
                                     '（含子目录）内, 请改用相对路径' % (i, q))
            q = os.path.join(root, q)
            _ok, _why = _inside_scene_dir(q, root)
            if not _ok:
                return None, False, ('第 %d 面%s (%s); 六面图必须放在场景目录'
                                     '（含子目录）内' % (i, _why, os.path.abspath(q)))
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


def _apply_skybox(d, base_dir=None, ctx=None):
    """dict -> Cubemap 实例（兼容旧签名）。失败: **出声** + 返回 None（Q5=A）。"""
    cube, valid, reason = skybox_from_dict(d, base_dir, ctx)
    if not valid and d:
        print('[场景] 天空盒解析失败: %s' % (reason,))
    return cube


def _scene_skybox_from_data(data, base_dir=None, ctx=None):
    """场景级天空盒 -> (cube, valid, reason)；Q1=A: 缺键/null -> 默认蓝。

    有值但解析失败: 出声 + 回退默认蓝（保证"打开场景一定有天空盒"），valid=False
    由调用方转成可查询的 _skybox_valid/_skybox_error（skybox_get 用）。
    """
    d = data.get('skybox')
    # 只有"没写"(None) 或空对象才按缺省处理；非 dict（str/list/int/bool…）是**坏值**，
    # 必须 valid=False 报出来（P1-2），不能悄悄当成"没配"。
    if d is None or (isinstance(d, dict) and not d):
        return default_skybox(), True, None
    cube, valid, reason = skybox_from_dict(d, base_dir, ctx)
    if valid:
        return cube, True, None
    print('[场景] 天空盒解析失败 (%s) -> 回退默认蓝天盒' % (reason,))
    return default_skybox(), False, reason


def _apply_skybox_or_default(d, base_dir=None, ctx=None):
    """只要 cube 的便捷口（场景级）；缺键/null/解析失败都回落默认蓝。"""
    cube, _valid, _reason = _scene_skybox_from_data({'skybox': d}, base_dir, ctx)
    return cube


def _emit_skybox(cube, base_dir=None, ctx=None):
    """Cubemap -> dict（None 时返回 None）；**不做越界判定**（那是 _emit_skybox_checked 的事）。

    Q6=A: paths 写**相对当前场景目录**的形式。给了 base_dir 就**一律重算**
    （P1-3 回归修复: _source_paths 只是内存态；"新建后首次另存/另存为到别的目录"必须
    按新目录重算，否则重载按新目录解析 -> valid=False -> 静默回退默认蓝丢资产）。
    无 base_dir 时才退回内存态形式；再无则写绝对路径。
    """
    if cube is None:
        return None
    out = {"name": getattr(cube, 'name', None),
           "guid": getattr(cube, 'guid', None)}
    if ctx is not None and ctx.owns(getattr(cube, 'guid', None), 'cubemap'):
        return out                       # 项目资产: 只写 guid（路径不落盘）
    paths = getattr(cube, 'paths', None)
    if paths:
        if base_dir:
            rel = []
            for p in paths:
                try:
                    rel.append(os.path.relpath(p, base_dir))
                except Exception:
                    rel.append(str(p))      # 跨盘符无法 relpath -> 保绝对
            out["paths"] = rel
        elif getattr(cube, '_source_paths', None):
            out["paths"] = [str(p) for p in cube._source_paths]
        else:
            out["paths"] = list(paths)
        return out
    solid = getattr(cube, '_solid_color', None)
    if solid:
        out["solid_color"] = [int(c) for c in solid]
        return out
    return None   # 无可用来源（内存态 cubemap 无法序列化）


def _emit_skybox_checked(cube, base_dir=None, ctx=None):
    """A3=B（人类裁决 2026-11-09）: 落盘前的路径限制检查 -> (dict | None, reason | None).

    规则: 六面图**必须位于场景目录内（允许子目录）**。给了 base_dir 时逐面算相对路径:
      · 跨盘符 / 算出来是绝对路径 / 以 '..' 开头  -> **不写出**（整体返回 None）并给 reason；
      · 调用方负责出声，并把 reason 记进 engine._skybox_valid/_skybox_error，
        绝不静默写一个"将来加载必然失败"的值（那等于丢资产还看不见）。
    无 base_dir 的旧调用（不落盘的场合）沿用 _emit_skybox 的行为，不判越界。
    """
    if cube is None:
        return None, None
    if ctx is not None and ctx.owns(getattr(cube, 'guid', None), 'cubemap'):
        return _emit_skybox(cube, base_dir, ctx), None
    if not base_dir or not getattr(cube, 'paths', None):
        return _emit_skybox(cube, base_dir, ctx), None
    root = os.path.abspath(base_dir)
    rel = []
    for i, p in enumerate(cube.paths):
        try:
            r = os.path.relpath(os.path.abspath(str(p)), root)
        except Exception:
            return None, ('第 %d 面与场景目录不在同一盘符 (%s); 六面图必须放在场景目录'
                          '（含子目录）内 -> 本次不写入' % (i, p))
        if os.path.isabs(r) or r.split(os.sep)[0] == '..' or r.split('/')[0] == '..':
            return None, ('第 %d 面不在场景目录内 (%s); 六面图必须放在场景目录（含子目录）'
                          '内 -> 本次不写入' % (i, r))
        rel.append(r)
    out = {"name": getattr(cube, 'name', None),
           "guid": getattr(cube, 'guid', None),
           "paths": rel}
    return out, None


def _emit_camera(cam, base_dir=None, ctx=None):
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
        # A3=B: 相机级同样受"必须在场景目录内"限制；越界 -> 不写出 + 出声
        "skybox": _emit_camera_skybox(cam, base_dir, ctx),
    }


def _emit_camera_skybox(cam, base_dir=None, ctx=None):
    """相机级 skybox 落盘：解析失败过则原样写回旧引用（Q-B1-1=A），否则常规发射。"""
    out = _emit_skybox_checked(getattr(cam, 'skybox', None), base_dir, ctx)[0]
    if out is None:
        ref = getattr(cam, '_skybox_ref', None)
        if isinstance(ref, dict) and ref:
            return dict(ref)
    return out


def _keep_cam_skybox_ref(cam, raw, valid):
    """相机级天空盒：解析失败时保留原始引用（保存写回），成功时清掉。"""
    try:
        if (not valid) and isinstance(raw, dict) and raw:
            cam._skybox_ref = dict(raw)
        else:
            cam._skybox_ref = None
    except Exception:
        pass


def _apply_cameras(engine, cam_dicts, base_dir=None, ctx=None):
    """摄像机 dict 列表 -> engine.cameras (清空重建; 文件 id 覆盖 guid).
    返回 [(cam, parent_id)] 供 _link_camera_parents 在物体建链后连父 (相机引用物体)."""
    engine.cameras.clear()
    links = []
    for _ci, d in enumerate(cam_dicts):
        # 2026-11-09 (第三轮审计 P-02-xx / 02 号报告): 相机段不是 dict 时旧实现直接
        # d.get(...) -> AttributeError，GL 加载整场景失败；而 VK 侧只报错继续。
        # 统一为：跳过该段 + 出声，其它相机照常建（与 _apply_skybox 的容错口径一致）。
        if not isinstance(d, dict):
            print('[场景] 第 %d 个相机段不是对象 (%s) -> 跳过该段'
                  % (_ci, type(d).__name__))
            continue
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
        # Q5=A: 解析失败出声并记录原因（skybox_get 可查询）。
        # P2-1 修复: **没有**相机天空盒是正常态（用场景默认），不能再伪造成
        # valid=False + 假 reason（那会让 skybox_get 把"正常"报成"坏了"）。
        _raw = d.get('skybox')
        if not _raw:
            cam.skybox = None
            cam._skybox_valid = True
            cam._skybox_error = None
            cam._skybox_ref = None
        else:
            _cube, _valid, _reason = skybox_from_dict(_raw, base_dir, ctx)
            cam.skybox = _cube
            cam._skybox_valid = bool(_valid)
            cam._skybox_error = _reason
            if not _valid:
                print('[场景] 相机 %r 的天空盒解析失败: %s'
                      % (getattr(cam, 'name', '?'), _reason))
                # Q-B1-1=A: 保留原始引用（保存时不改写）；P-05: 进资产体检
                _keep_cam_skybox_ref(cam, _raw, _valid)
                record_asset_error(engine, 'cameras[].skybox',
                                   (_raw or {}).get('guid') if isinstance(_raw, dict) else None,
                                   _reason)
            else:
                _keep_cam_skybox_ref(cam, None, True)
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

def _emit_material(mat, ctx=None):
    """Material -> dict (v11: 项目托管贴图/立方图**只写 guid**；未托管沿用旧字段)

    ctx 为 None（无项目资产库）时行为与 beta5 完全一致 —— 这是兼容闸门。
    """
    d = {"id": mat.guid, "name": mat.name,
         "color": mat.color, "saturation": mat.saturation,
         "metallic": getattr(mat, 'metallic', 0.0),
         "roughness": getattr(mat, 'roughness', 0.5),
         "pbr": getattr(mat, 'pbr', False)}
    kept = getattr(mat, '_asset_ref_slots', None)
    kept = kept if isinstance(kept, dict) else {}

    def _slot(key, attr):
        obj = getattr(mat, attr, None)
        if obj is not None:
            return (_texture_ref_dict(obj, ctx) if attr != 'env_map'
                    else _cubemap_ref_dict(obj, ctx))
        ref = kept.get(key)
        return dict(ref) if isinstance(ref, dict) and ref else None

    for key, attr in (('albedo', 'albedo'), ('normal_map', 'normal_map'),
                      ('env_map', 'env_map')):
        ref = _slot(key, attr)
        if ref is not None:
            d[key] = ref
    return d


def _warn_dup_guid(engine, kind, guid, where):
    """重复 guid 告警（beta6 B1: 现状是静默首条胜出 -> 必须出声）。"""
    if not guid:
        return
    _find = getattr(engine, '_find_material', None)
    if kind == 'material' and callable(_find) and _find(guid) is not None:
        print('[资产] 材质 guid 重复 (%s, 位置 %s) -> 同 guid 只保留首个，其余不生效'
              % (guid, where))


def _apply_material_texture(engine, mat, slot, ref, ctx):
    """材质贴图槽: guid 优先（项目资产）；旧 path 兼容读 + 告警；失败一律有声。

    Q-B1-1=A: **任何失败都保留原引用**（_keep_slot_ref），保存时原样写回，
    绝不因为"这次没解析出来"就把 guid 从场景里抹掉。
    """
    if not isinstance(ref, dict) or not ref:
        return
    guid = ref.get('guid')
    try:
        if ctx is not None and guid and ctx.owns(guid, 'texture'):
            tex, ok, why = ctx.texture(guid, ref)
            if tex is not None:
                setattr(mat, slot, tex)
                _clear_slot_ref(mat, slot)
            else:
                _keep_slot_ref(mat, slot, ref)
            if why:
                record_asset_error(engine, 'materials.%s' % slot, guid, why)
            return
        path = ref.get('path')
        if path:
            record_asset_error(engine, 'materials.%s' % slot, guid,
                               '旧路径引用（beta6 兼容期；建议 asset_import 迁移为 guid）: %s'
                               % (path,))
            try:
                from loom_texture import Texture
                tex = Texture.from_file(
                    path, name=ref.get('name'), guid=guid,
                    mipmaps=ref.get('mipmaps', True),
                    wrap=ref.get('wrap', 'repeat'),
                    filter_mode=ref.get('filter_mode', 'trilinear'),
                    aniso=ref.get('aniso', 1.0),
                    max_size=ref.get('max_size', 0),
                    compression=ref.get('compression', 'none'))
                setattr(mat, slot, tex)
                _clear_slot_ref(mat, slot)
            except Exception as e:
                _keep_slot_ref(mat, slot, ref)
                record_asset_error(engine, 'materials.%s' % slot, guid,
                                   '贴图加载失败 (%r): %s' % (e, path))
            return
        if guid:
            _keep_slot_ref(mat, slot, ref)
            if ctx is not None:
                record_asset_error(engine, 'materials.%s' % slot, guid,
                                   '资产 guid 未在项目索引中（可能被删/换了项目）: %s'
                                   % (guid,))
            else:
                record_asset_error(engine, 'materials.%s' % slot, guid,
                                   '只有 guid 但没有项目资产索引（缺 Assets/assets.json）')
    except Exception as e:
        # 资产层任何异常都不许穿透到"已清空场景"之后（F7 / 两端一致）
        _keep_slot_ref(mat, slot, ref)
        record_asset_error(engine, 'materials.%s' % slot, guid,
                           '资产解析异常 (%r)' % (e,))


def _apply_material_env(engine, mat, ref, ctx):
    """材质环境贴图: guid 优先；旧 6 面 paths / 纯色兼容读。失败保留原引用。"""
    if not isinstance(ref, dict) or not ref:
        return
    guid = ref.get('guid')
    try:
        if ctx is not None and guid and ctx.owns(guid, 'cubemap'):
            cube, ok, why = ctx.cubemap(guid, ref)
            if cube is not None:
                mat.env_map = cube
                _clear_slot_ref(mat, 'env_map')
            else:
                _keep_slot_ref(mat, 'env_map', ref)
            if why:
                record_asset_error(engine, 'materials.env_map', guid, why)
            return
        from loom_cubemap import Cubemap
        if ref.get('paths'):
            record_asset_error(engine, 'materials.env_map', guid,
                               '旧路径引用（6 面路径，beta6 兼容期；建议 asset_import）')
            try:
                mat.env_map = Cubemap.from_files(ref['paths'], name=ref.get('name'),
                                                 guid=guid)
                _clear_slot_ref(mat, 'env_map')
            except Exception as e:
                _keep_slot_ref(mat, 'env_map', ref)
                record_asset_error(engine, 'materials.env_map', guid,
                                   '环境贴图加载失败 (%r)' % (e,))
        elif ref.get('solid_color'):
            mat.env_map = Cubemap.from_solid(tuple(ref['solid_color']),
                                             name=ref.get('name'), guid=guid)
            _clear_slot_ref(mat, 'env_map')
        elif guid:
            _keep_slot_ref(mat, 'env_map', ref)
            record_asset_error(engine, 'materials.env_map', guid,
                               '资产 guid 未在项目索引中（可能被删/换了项目）: %s' % (guid,))
    except Exception as e:
        _keep_slot_ref(mat, 'env_map', ref)
        record_asset_error(engine, 'materials.env_map', guid,
                           '环境贴图加载失败 (%r)' % (e,))


def _apply_materials(engine, mat_dicts, ctx=None):
    """材质 dict 列表 -> engine.materials (清空重建; 文件 id 覆盖 guid).
    必须在创建物体之前调用, 这样物体才能通过 material_id 引用库中材质.
    v11: 贴图/环境贴图按 guid 从项目资产解析；旧 path 字段兼容读并告警。"""
    engine.materials.clear()
    for d in mat_dicts:
        if not isinstance(d, dict):
            print('[场景] 材质段不是对象 (%s) -> 跳过该段' % (type(d).__name__,))
            continue
        _warn_dup_guid(engine, 'material', d.get('id'), 'materials[]')
        try:
            mat = engine.add_material(color=d.get('color'),
                                      saturation=d.get('saturation', 1.0),
                                      name=d.get('name'),
                                      guid=d.get('id'))
        except Exception as _e:
            record_asset_error(engine, 'materials[]', d.get('id'),
                               '材质创建失败 (%r)' % (_e,))
            continue
        if d.get('id'):
            mat.guid = d['id']
        # M36 PBR: 恢复金属度/粗糙度/PBR 开关
        try:
            mat.metallic = d.get('metallic', 0.0)
            mat.roughness = d.get('roughness', 0.5)
            mat.pbr = d.get('pbr', False)
        except Exception:
            pass
        for slot, key in (('albedo', 'albedo'), ('normal_map', 'normal_map')):
            _apply_material_texture(engine, mat, slot, d.get(key), ctx)
        _apply_material_env(engine, mat, d.get('env_map'), ctx)


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
    # Q-B1-1=A: 只有"失效引用"的材质不是默认材质 —— 不能被孤儿规则丢掉
    # （否则保存后 ref 也没了，等于换个方式丢资产）
    if isinstance(getattr(mat, '_asset_ref_slots', None), dict) \
            and any(isinstance(v, dict) and v
                    for v in mat._asset_ref_slots.values()):
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


def scene_to_dict(engine, camera=None, base_dir=None, ctx=None):
    """引擎场景 -> v11 dict. camera: {'target','distance','yaw','pitch'} 或 None

    base_dir: 场景文件所在目录（Q6=A: skybox 六面图路径按它写成相对形式）。
    ctx: 资产上下文（beta6 B1）。None 时按 base_dir 自动探测；探测不到 = 旧路径模式。
    保存前校验父链: 成环/不可达抛 SceneCycleError, 绝不静默丢对象."""
    _validate_model_graph(engine.models)
    if ctx is None:
        ctx = asset_context(base_dir)
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
    # A3=B: 落盘前检查六面图是否都在场景目录内；越界 -> **不写出** + 记 valid/reason
    # （绝不静默写一个将来加载必然失败的值）。digest（camera=None）不出声避免刷屏。
    _sb_dict, _sb_reason = _emit_skybox_checked(
        getattr(engine, '_scene_skybox', getattr(engine, '_skybox', None)),
        base_dir, ctx)
    if _sb_reason:
        try:
            engine._skybox_valid = False
            engine._skybox_error = _sb_reason
        except Exception:
            pass
        if camera is not None:
            print('[场景] 天空盒未写入: %s' % (_sb_reason,))
    # Q-B1-1=A: 加载时天空盒解析失败过 -> 保存**原样写回旧引用**（不换成默认蓝/新 guid）
    if _sb_dict is None or getattr(engine, '_skybox_valid', True) is False:
        _sb_ref = getattr(engine, '_skybox_ref', None)
        if isinstance(_sb_ref, dict) and _sb_ref:
            _sb_dict = dict(_sb_ref)
    # Q-B1-1=A: 保存时若有"保留的失效引用"，出声告知（不静默、不删除）
    _kept = asset_refs_kept(engine)
    if _kept and camera is not None:
        print('[资产] 本次保存保留了 %d 条失效引用（原样写回，未改写；修复资产/缺文件后自动恢复）'
              % (_kept,))
    return {"version": SCENE_VERSION,
            # D7: 写出时声明"最低引擎版本" —— 旧引擎读新场景会明确拒绝,
            # 而不是把 animator.speed / clip_meta 等未知键静默丢掉.
            "min_engine_version": ENGINE_VERSION,
            "camera": camera,
            "gravity": getattr(engine, 'gravity', -9.8),   # 2026-08-30: 场景重力加速度
            "materials": [_emit_material(m, ctx) for m in mats],
            "lights": [_emit_light(l) for l in engine.lights],
            "cameras": [_emit_camera(c, base_dir, ctx) for c in engine.cameras],
            "active_camera": engine.active_camera,
            # 2026-10-19 第1档序13 天空盒 (C3): 场景级默认天空盒
            # 场景级天空盒（Q3=A: **不是**"当前生效的那一个"——相机级覆盖只在渲染时生效，
            # 落盘必须是场景级，否则播放期保存会把相机天空盒烘焙成场景默认）。
            "skybox": _sb_dict,
            "ui": _emit_ui(getattr(engine, 'ui', None)),   # 2026-10-18: Canvas UI
            "objects": objs}


def scene_from_dict(engine, data, camera_out=None, base_dir=None, ctx=None):
    """dict -> 引擎场景 (容错加载). 返回创建的模型列表.
    camera_out: dict 则把相机字段写进去 (编辑器/运行时自行应用).
    base_dir: 场景文件目录（Q6=A: skybox 相对路径按它解析；也用于探测项目资产库）。
    ctx: 资产上下文（beta6 B1）。None 时按 base_dir 自动探测；探测不到 = 旧路径模式。"""
    data = migrate(data)
    if ctx is None:
        ctx = asset_context(base_dir)
    reset_asset_errors(engine)             # 每次加载重置（跨场景不累积，含去重键）
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
    _cube, _sb_valid, _sb_reason = _scene_skybox_from_data(data, base_dir, ctx)
    # 场景级（落盘/查询用）与"生效"（渲染端只读 _skybox）在加载后是同一个对象；
    # editor 会在 _load_scene 里按 active camera 再算一次生效值（Q3=A）。
    engine._scene_skybox = _cube
    engine._skybox = _cube
    engine._skybox_valid = bool(_sb_valid)
    engine._skybox_error = _sb_reason
    # Q-B1-1=A: 天空盒解析失败 -> 保留原引用（保存时写回，不替换成默认蓝）；
    # P-05: 同时进资产体检（scene_assets_check 不再假绿）。
    _sb_raw = data.get('skybox')
    try:
        engine._skybox_ref = (dict(_sb_raw)
                              if (not _sb_valid and isinstance(_sb_raw, dict) and _sb_raw)
                              else None)
    except Exception:
        engine._skybox_ref = None
    if not _sb_valid and isinstance(_sb_raw, dict) and _sb_raw:
        record_asset_error(engine, 'skybox', _sb_raw.get('guid'), _sb_reason)
    _apply_ui(engine, data.get('ui'))                # 2026-10-18: Canvas UI (清空重建)
    _apply_lights(engine, data.get('lights', []))   # M21: 场景光源 (清空重建)
    try:
        cam_links = _apply_cameras(engine, data.get('cameras', []), base_dir, ctx)  # 场景摄像机 (清空重建)
    except Exception as _e:                          # 资产层异常不得击穿 F7
        print('[场景] 相机段解析异常 (%r) -> 跳过相机' % (_e,))
        cam_links = []
    engine.active_camera = data.get('active_camera')  # 玩家视角摄像机
    try:
        _apply_materials(engine, data.get('materials', []), ctx)  # M23: 材质库 (先于物体, 供引用)
    except Exception as _e:
        print('[场景] 材质段解析异常 (%r) -> 跳过材质库' % (_e,))
    # 2026-11-07 D2=A: 文件显式登记的材质 (keep_ids) 与 add_model 自建材质区分
    _lib_keep = {id(x) for x in engine.materials}
    objects = _objects_in
    models = []
    for obj in objects:
        m, _ = _apply_object(engine, obj, ctx)
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
    _errs = asset_errors(engine)
    if _errs:
        print('[场景] 资产问题 %d 条（详见上文；EAI 命令 scene_assets_check 可查）'
              % (len(_errs),))
    return models


def migrate(data):
    """版本迁移 (原地修改并返回). 旧格式/缺版本一律能加载.

    beta6 C1/D7: 第一步就过"引擎版本闸门" —— 场景要求更高版本时抛
    SceneVersionError (明确拒绝), 绝不带着未知字段静默加载。
    """
    check_engine_version(data)
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
    if v < 11:
        # v10 -> v11 (beta6 B1 资产 guid): **不在 migrate 里改写数据**（保持纯函数、可重复）。
        # 旧 path/paths 字段由加载侧兼容读并告警（一个 beta 周期的 fallback）；
        # 真正的"路径 -> guid"补全交给一次性脚本 tools/migrate_scene_assets_v11.py。
        pass
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


def material_to_dict(mat, ctx=None):
    """Material -> 材质资产 dict (与 _emit_material 同构 + version)"""
    return {** _emit_material(mat, ctx), "version": ASSET_VERSION}


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

def prefab_to_dict(root, ctx=None):
    """子树根 -> prefab 资产 dict (局部对象 id, 根 id = prefab guid)"""
    pguid = root.guid or generate_guid()
    objs = []
    _emit_subtree(root, objs, ctx=ctx)
    return {"version": PREFAB_VERSION,
            # R5-02 P-04: prefab 物体同样带 animator.speed / clip_meta,
            # 旧引擎读新 prefab 会静默丢 (once 变永远循环) —— 与场景同一道闸。
            "min_engine_version": ENGINE_VERSION,
            "prefab": {"guid": pguid, "name": root.name},
            "objects": objs}


def save_prefab(path, root, ctx=None):
    save_json_atomic(path, prefab_to_dict(root, ctx))


def load_prefab(path):
    with open(path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    if data.get('version', 1) < 1:
        data['version'] = 1
    # R5-02 P-04: prefab 与场景共用版本闸门 (旧 prefab 无该字段 -> 不拦)。
    check_engine_version(data)
    return data


def instantiate_prefab(engine, data, offset=(0, 0, 0), ctx=None):
    """场景中实例化 prefab: 全部对象重新生成 GUID, 挂 prefab_ref, 根整体平移.
    返回创建的模型列表 (空 prefab 返回 []). ctx: 资产上下文（贴图/材质按 guid 解析）。

    R5-02 P-04: 入口再校验一次版本 —— undo 的 PrefabPlaceCommand 持有已读出的
    data 并在 redo 时重放, 不能只靠 load_prefab 那一处。"""
    check_engine_version(data)
    objects = data.get('objects', [])
    if not isinstance(objects, list):
        objects = []
    _validate_object_graph(objects)     # 2026-11-07: Prefab 父链成环拒绝实例化
    pguid = data.get('prefab', {}).get('guid')
    models = []
    old_id_map = {}                       # 模板旧 id -> 新模型
    for obj in objects:
        m, oid = _apply_object(engine, obj, ctx)   # 此刻 m.guid = 模板 id
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
