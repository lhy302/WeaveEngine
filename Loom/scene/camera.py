# -*- coding: utf-8 -*-
"""scene/camera.py — **相机投影归一 + 摄像机实体**序列化（B2 自 sceneio.py 拆出，函数体逐字一致）。

内容（= 旧 sceneio.py 同名段）:
  投影归一: ORTHO_SIZE_*/FOV_*/_TRUE_WORDS/_FALSE_WORDS/_b_strict/
            norm_ortho_size/norm_fov_deg（D7=A / Q4=B，editor 与 scene_driver 复用）
  摄像机:   _emit_camera / _emit_camera_skybox / _keep_cam_skybox_ref /
            _apply_cameras / camera_parent_links / _link_camera_parents
"""
import math

from scene.asset import record_asset_error
from scene.object import _f1, _f3
from scene.sky import _emit_skybox_checked, skybox_from_dict




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



# ---------------- 摄像机 (Unity Camera 概念) ----------------

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
        "parent_id": cam.parent.guid if cam.parent is not None else None,   # 父 guid：物体或相机
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
    返回 [(cam, parent_id)] 供 _link_camera_parents 在物体建链后连父 (相机引用物体/相机)."""
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



# ---------------- 相机父链（GL/VK 唯一实现，Q-B7-57-1 序列化补全） ----------------

def camera_parent_links(cameras, cam_dicts):
    """CameraState 列表与场景 cameras[] 原始段配对 -> [(cam, parent_id)]（唯一配对实现）。

    正常场景两者等长 -> 按序配对（旧场景相机段可能没有 id，按序才连得上父）。
    _apply_cameras / build_cameras 会跳过非 dict 段（数量不等）-> 按身份 id 配对；
    无 id 且匹配不到的相机没有可引用身份，parent 视为 None（保持根）。
    """
    cams = list(cameras or ())
    ds = list(cam_dicts or ())
    if len(cams) == len(ds):
        return [(cam, (d.get('parent_id') if isinstance(d, dict) else None))
                for cam, d in zip(cams, ds)]
    by_id = {}
    for d in ds:
        if isinstance(d, dict) and d.get('id'):
            by_id[str(d['id'])] = d
    out = []
    for cam in cams:
        d = by_id.get(str(getattr(cam, 'guid', '') or ''))
        out.append((cam, (d.get('parent_id') if isinstance(d, dict) else None)))
    return out


def _camera_link_set_parent(cam, parent):
    """只改父指针 + 父/旧父的 camera_children（加载期不做世界换算）。"""
    old = getattr(cam, 'parent', None)
    if old is parent:
        if parent is not None:
            kids = getattr(parent, 'camera_children', None)
            if kids is not None and cam not in kids:
                kids.append(cam)
        return
    if old is not None:
        kids = getattr(old, 'camera_children', None)
        if kids is not None and cam in kids:
            kids.remove(cam)
    cam.parent = parent
    if parent is not None:
        kids = getattr(parent, 'camera_children', None)
        if kids is not None and cam not in kids:
            kids.append(cam)


def _link_camera_parents(engine, links, id_map=None):
    """摄像机父链解析（GL/VK 唯一实现）: parent_id -> GameObject.guid | CameraState.guid.

    Q-B7-57-1（2026-11-22）: 相机也能当父（相机挂相机）。修前 id_map 只含物体，
    相机段里的 parent_id 指向相机 guid 时被静默忽略 -> 保存再加载回落根。
    本实现同时收物体与相机 guid，并处理两种坏引用（场景是不可信输入）:
      · 成环（含 A→B 后再 B→A、自指、文件里直接写出的环）-> **整次链接拒绝**，
        打印「[场景] 相机父链成环: ...」原因，已存在的父指针一个不动（迭代遍历，不递归爆栈）；
      · 父 guid 不存在（父已删除/悬空引用）-> 该相机脱根 + 打印告警，不崩溃；
      · 空/缺 parent_id -> 根（显式 null 也会脱掉旧父，与场景数据语义一致）。

    id_map: 可选既有映射（旧调用面）；仍会补进 engine.cameras 的 guid。
    返回实际建立的链接数（成环拒绝时 0，且不改任何状态）。
    """
    cams = list(getattr(engine, 'cameras', None) or ())
    maps = {}
    for m in (getattr(engine, 'models', None) or ()):
        g = getattr(m, 'guid', None)
        if g:
            maps[g] = m
    for cam in cams:
        g = getattr(cam, 'guid', None)
        if g:
            maps[g] = cam
    if id_map:
        maps.update(id_map)          # 旧调用面显式给的映射优先（语义与旧实现一致）

    pairs = list(links or ())
    cam_by_guid = {}
    desired = {}
    for cam in cams:
        g = getattr(cam, 'guid', None)
        if not g:
            continue
        cam_by_guid[g] = cam
        par = getattr(cam, 'parent', None)
        pg = getattr(par, 'guid', None)
        desired[g] = pg if (pg and pg in maps) else None

    explicit = {}
    for cam, pid in pairs:
        g = getattr(cam, 'guid', None)
        if not g:
            continue
        pid = pid if isinstance(pid, str) and pid else None
        explicit[id(cam)] = pid          # 按对象身份存，重复 guid 的坏场景也不会串
        desired[g] = pid

    # 防环：沿"期望父链"逐跳走（只跟相机 guid；物体父是终点），迭代 + visited，绝不递归。
    for start in cam_by_guid:
        seen = []
        seen_set = set()
        cur = start
        while cur is not None:
            if cur in seen_set:
                try:
                    i = seen.index(cur)
                except ValueError:
                    i = 0
                cyc = seen[i:] + [cur]
                print('[场景] 相机父链成环: %s -> 拒绝本次相机父链链接'
                      '（相机保持原样，不递归）' % ' -> '.join(cyc))
                return 0
            seen.append(cur)
            seen_set.add(cur)
            if cur not in cam_by_guid:
                break
            cur = desired.get(cur)

    applied = 0
    for cam, pid in pairs:
        g = getattr(cam, 'guid', None)
        if not g or id(cam) not in explicit:
            continue
        pid = explicit[id(cam)]
        if pid is None:
            if getattr(cam, 'parent', None) is not None:
                _camera_link_set_parent(cam, None)
            continue
        parent = maps.get(pid)
        if parent is None:
            if getattr(cam, 'parent', None) is not None:
                _camera_link_set_parent(cam, None)
            print('[场景] 相机 %r 的父 guid=%r 不存在（父已删除）-> 脱根（不崩溃）'
                  % (getattr(cam, 'name', '?'), pid))
            continue
        _camera_link_set_parent(cam, parent)
        applied += 1
    return applied


# 兼容旧名：GL sceneio 门面 / VK driver 都 import 这一份（函数对象 is 同源）。
link_camera_parents = _link_camera_parents
