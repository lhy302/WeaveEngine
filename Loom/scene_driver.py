# -*- coding: utf-8 -*-
"""
scene_driver.py — 播放器中间层 (纯逻辑, 后端无关; 2026-08-29 用户指示"中间层")

SceneDriver = 场景数据 + 每帧步进 (脚本/物理/动画/轨道相机), 不碰任何 GPU API:
  - Vk 播放器 / GL 播放器 (PlayerApp) 共用同一份语义 (engine.update_scripts /
    update_animations 的复刻, 与 engine.py 保持同步注释, 勿分叉公式);
  - 由后端层读 driver.models/lights/vp 画帧 (渲染在别处).
  - B1 (2026-08-30): 补上**物理**缺口 —— 每帧步进含桥三段 (pre/step/post,
    culverin 缺失 -> 无物理 (legacy 语义缺失, 打印提示不崩)); 并补齐脚本
    "引擎 API 最小面" (move_with_collision/get_collisions/collider_hit/
    world_position/输入与相机安全默认), 修 Vk 播放器脚本全体 broken.
"""
import math
import os

import numpy as np

from matlib import (mat4_view_yaw_pitch, mat4_perspective, mat4_ortho, mat4_scale,
                    mat4_rotation, mat4_translation, view_basis_to_angles)
from mesh import spec_to_mesh
from engine import GameObject, Point3D, LightState, DEFAULT_ACTIONS
# 2026-11-07 (_fix_summary §5 遗留): LOD 配置代 —— 只在 renderer.lod_* 变化时
# 重建"配了 LOD 的模型"集合, 无 LOD 场景每帧 O(1) 早退 (不再全量扫描).
from loom_components import MeshRendererComponent
# 2026-11-06 相机对齐 (双后端): CameraState 实体 (纯数据类, 无 GL 依赖) ——
# 场景 cameras/active_camera 在 Vk 侧也要还原, 否则"场景里的 Camera 实体"
# 在 Vulkan 播放器里完全不存在, 只能看轨道相机。
from loom_scene_entities import CameraState
from scripts import get_script
from loom_ui import UIManager, Canvas  # 2026-10-18: Canvas UI (替换 _DriverUI 空壳)

# B1: 物理桥 (零 GL; 缺失/导入失败 -> physb=None -> 无物理步进)
try:
    import physics_bridge as physb
except Exception:
    physb = None


def build_models(data, materials=None):
    """场景 dict -> GameObject 列表 (无 GL: 只建组件, 不建 vbo/vao).
    与 engine.sceneio._apply_object 语义对齐 (无 material_id 旧文件路径).
    B1 (2026-08-30): 补 rigidbody/collider (含接触材质 friction/restitution) ——
    旧版缺失 = Vk 播放器物体没有任何刚体, 物理缺口根源之一."""
    models = []
    for obj in data['objects']:
        mesh = spec_to_mesh(obj.get('type', 'cube'), obj.get('params', {}))
        m = GameObject(
            mesh,
            Point3D(*obj.get('position', (0, 0, 0))),
            Point3D(*obj.get('rotation', (0, 0, 0))),
            name=obj.get('name', '物体'),
            scale=obj.get('scale', (1, 1, 1)),
            visible=obj.get('visible', True),
            color=obj.get('color'),
            primitive=obj.get('type', 'cube'),
            params=obj.get('params', {}),
            normal_mode=obj.get('normal_mode', 'flat'),
            saturation=obj.get('saturation', 1.0))
        m.guid = obj.get('id') or obj.get('guid')
        # 材质引用 (M23 资产语义): 文件有 material_id 则挂共享材质
        if materials:
            _mid = obj.get('material_id')
            if _mid and _mid in materials:
                m.renderer.material = materials[_mid]
        # 音频源 (M34): 与 sceneio._apply_object 同字段
        au = obj.get('audio_source')
        if isinstance(au, dict):
            _cat = au.get('category', 'sfx')
            if not isinstance(_cat, str) or _cat.strip().lower() not in ('music', 'sfx', 'voice'):
                _cat = 'sfx'
            else:
                _cat = _cat.strip().lower()
            def _f(key, dflt):
                try:
                    return float(au.get(key, dflt))
                except (TypeError, ValueError):
                    return dflt
            m.add_audio_source(clip=au.get('clip'),
                               loop=au.get('loop', False),
                               volume=_f('volume', 1.0),
                               category=_cat,
                               min_distance=_f('min_distance', 1.0),
                               max_distance=_f('max_distance', 500.0),
                               rolloff=_f('rolloff', 1.0))
        # 动画 (M35): 重建 AnimationClip
        an = obj.get('animator')
        if isinstance(an, dict) and isinstance(an.get('clips'), dict):
            from engine import AnimationClip
            _clips = {name: AnimationClip([dict(fr) for fr in frames])
                      for name, frames in an['clips'].items()}
            m.add_animator(clips=_clips, current=an.get('current'),
                           loop=an.get('loop', True))
        # 碰撞体 (M28 + B1): 文件有 collider 字段则覆盖默认 (缺省=默认, 兼容旧文件)
        col = obj.get('collider')
        if isinstance(col, dict):
            if col.get('shape') in ('box', 'sphere', 'none'):
                m.collider.shape = col['shape']
            m.collider.enabled = bool(col.get('enabled', True))
            m.collider.friction = float(col.get('friction', 0.5))
            m.collider.restitution = float(col.get('restitution', 0.0))
            m.collider.rolling_friction = float(col.get('rolling_friction', 0.1))
        # 刚体 (M31 + B1): 文件有 rigidbody 字段则加刚体 (旧文件无字段=无刚体)
        rb = obj.get('rigidbody')
        if isinstance(rb, dict):
            m.add_rigidbody(mass=rb.get('mass', 1.0),
                            use_gravity=rb.get('use_gravity', True),
                            is_kinematic=rb.get('is_kinematic', False),
                            friction=rb.get('friction', 0.5),
                            restitution=rb.get('restitution', 0.0),
                            rolling_friction=rb.get('rolling_friction', 0.1))
        # 脚本 (M25): 恢复全部脚本组件 (与 engine 语义一致, 惰性实例化见 step)
        scs = obj.get('scripts')
        if scs is None:
            sc = obj.get('script')
            scs = [sc] if isinstance(sc, dict) and sc.get('id') else []
        for s in scs:
            if isinstance(s, dict) and s.get('id'):
                m.add_script(s['id'], s.get('vars') if isinstance(s.get('vars'), dict) else {})
        # LOD (2026-11-07 裁决 A): 场景序列化的 lod_* 段 -> renderer (只读 data)
        apply_lod_from_dict(m, obj)
        models.append(m)
    # 父链 (parent_id -> guid 命中)
    by_guid = {m.guid: m for m in models if m.guid}
    for obj, m in zip(data['objects'], models):
        pid = obj.get('parent_id')
        if pid and pid in by_guid:
            m.parent = by_guid[pid]
    return models


def build_materials(data):
    """场景 dict -> Material 列表 (与 sceneio._apply_materials 同字段语义).

    2026-11-06: Vk 后端此前完全没有材质库, PBR/共享材质在播放器里静默丢失。
    """
    from loom_material import Material
    out = []
    for d in (data.get('materials') or []):
        if not isinstance(d, dict):
            continue
        mat = Material(name=d.get('name'), color=d.get('color'),
                       saturation=d.get('saturation', 1.0))
        if d.get('id'):
            mat.guid = d['id']
        if 'metallic' in d:
            mat.metallic = d.get('metallic', 0.0)
        if 'roughness' in d:
            mat.roughness = d.get('roughness', 0.5)
        if 'pbr' in d:
            mat.pbr = bool(d.get('pbr', False))
        # 2026-11-06 贴图: 与 sceneio._apply_materials 同语义 (文件缺失则跳过)
        # 2026-11-07 P-03 修复: **导入设置必须原样转发**。此前只传 path/name/guid,
        # 其余六项取 Texture 默认值 (mipmaps=True / wrap=repeat / filter=trilinear /
        # aniso=1 / max_size=0) —— 同一材质 GL 是 64x64/1 级, Vk 是 256x256/9 级
        # (实测 16 倍像素上传), 采样方式也不同。取值列表照抄 sceneio._apply_materials
        # (同一个白名单, 不另立第二份), 避免两后端再分叉。
        try:
            from loom_texture import Texture
            for key in ('albedo', 'normal_map'):
                ref = d.get(key)
                if ref and ref.get('path'):
                    try:
                        setattr(mat, key, Texture.from_file(
                            ref['path'], name=ref.get('name'), guid=ref.get('guid'),
                            mipmaps=ref.get('mipmaps', True),
                            wrap=ref.get('wrap', 'repeat'),
                            filter_mode=ref.get('filter_mode', 'trilinear'),
                            aniso=ref.get('aniso', 1.0),
                            max_size=ref.get('max_size', 0),
                            compression=ref.get('compression', 'none')))
                    except Exception:
                        pass
            # 2026-11-06 环境反射: 与 sceneio._apply_materials 同语义 (6 面 paths)
            # 2026-11-07 F7 联动: 纯色环境 (Cubemap.from_solid) 也要往返 —— sceneio
            # 的 _emit_material/_apply_materials 已支持 env_map.solid_color, 这里
            # 只认 paths 会让同一材质在 VK 播放器里丢掉纯色环境反射 (双后端不一致)。
            eref = d.get('env_map')
            if eref:
                try:
                    from loom_cubemap import Cubemap
                    if eref.get('paths'):
                        mat.env_map = Cubemap.from_files(
                            eref['paths'], name=eref.get('name'),
                            guid=eref.get('guid'))
                    elif eref.get('solid_color'):
                        mat.env_map = Cubemap.from_solid(
                            tuple(eref['solid_color']), name=eref.get('name'),
                            guid=eref.get('guid'))
                except Exception:
                    pass
        except Exception:
            pass
        out.append(mat)
    return out


def build_lights(data):
    """场景 dict -> LightState 列表 (与 sceneio 同字段语义)."""
    return [LightState(**{k: v for k, v in d.items()
                          if k in ('kind', 'position', 'direction', 'color',
                                   'intensity', 'name', 'guid', 'mode',
                                   'shape', 'size', 'shadow', 'azimuth',
                                   'elevation', 'roll',
                                   # 2026-11-06 对齐 GL: 这三项此前被白名单丢掉,
                                   # 导致 Vk 里点光 range 恒 10、聚光锥角恒 30/60
                                   # (A/B 聚光场景 MAE 0.0085 的根因)
                                   'range', 'spot_inner_angle',
                                   'spot_outer_angle')})
            for d in data.get('lights', [])]


# ================ 2026-11-06 相机对齐 (active_camera) ================
# Vk 侧此前只有轨道相机, 场景里的摄像机实体 (cameras / active_camera) 被完全
# 忽略 -> 同一场景 GL 播放器从玩家相机看, Vk 播放器从轨道相机看, "切后端
# 画面全变". 下面三个助手把 sceneio._apply_cameras / loom_transform 的世界
# 矩阵语义搬到无 GL 的中间层 (公式与 engine.py / sceneio.py 逐位一致).

def _f3(v, default):
    """容错 3 分量 (与 sceneio._f3 同语义): 坏数据回落 default, 加载不崩."""
    if isinstance(v, (list, tuple)) and len(v) == 3:
        try:
            return tuple(float(x) for x in v)
        except (TypeError, ValueError):
            pass
    return default


def _f1(v, default):
    """容错单数值 (与 sceneio._f1 同语义)."""
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def object_world_matrix(m):
    """物体世界矩阵 (行向量 S@R@T 沿父链) — 与 loom_transform.model_world_matrix 同."""
    M = (mat4_scale(np, m.scale[0], m.scale[1], m.scale[2])
         @ mat4_rotation(np, m.rotation.x, m.rotation.y, m.rotation.z)
         @ mat4_translation(np, m.position.x, m.position.y, m.position.z))
    if m.parent is not None:
        M = M @ object_world_matrix(m.parent)
    return M


def object_world_rotation(m):
    """物体世界旋转矩阵 (忽略缩放) — 与 loom_transform.world_rotation_matrix 同."""
    R = mat4_rotation(np, m.rotation.x, m.rotation.y, m.rotation.z)
    if m.parent is not None:
        R = R @ object_world_rotation(m.parent)
    return R


# ================ 2026-11-07 M36 LOD 进场景序列化 (Vk 侧读取) ================
# 裁决 A (scan_05 §5 问题 1): LOD 进场景序列化 —— 否则播放器 (独立进程只吃
# 场景文件) 里 renderer.lod_levels 恒 None, _update_lod 是纯开销的死代码。
# 序列化写入端由 sceneio 批次实现; 本文件**只读** data, 字段形态按下面的
# 白名单解析 (与写入端约定, 且对缺字段/坏字段一律降级, 老场景零影响):
#   "lod_levels":        [[max_dist, 网格引用], ...]      升序 (距离模式)
#   "lod_screen_levels": [[屏幕占比阈值, 网格引用], ...]  降序 (屏幕占比模式)
#   "lod_bias":          1.0                                LOD 偏移
#   "lod": {"levels": [...], "screen_levels": [...], "bias": ...}  (等价容器写法)
# 网格引用 = {"type": "cube|sphere|plane", "params": {...}} | "cube|sphere|plane"
#          | 已是 Mesh 的对象 (运行期 / 测试直传)。

def _lod_mesh(ref):
    """LOD 级别里的网格引用 -> Mesh; 无法识别返回 None (调用方跳过该级)."""
    if ref is None:
        return None
    if hasattr(ref, 'vertices') and hasattr(ref, 'faces'):
        return ref
    if isinstance(ref, str):
        try:
            return spec_to_mesh(ref, {})
        except Exception:
            return None
    if isinstance(ref, dict):
        typ = ref.get('type') or ref.get('primitive') or ref.get('mesh_type')
        if isinstance(typ, str) and typ:
            params = ref.get('params')
            try:
                return spec_to_mesh(typ, params if isinstance(params, dict) else {})
            except Exception:
                return None
    return None


def _lod_levels(raw, screen=False):
    """[[阈值, 网格引用], ...] -> [(float, Mesh), ...] (坏项跳过, 排序与 GL 一致).

    距离模式 (screen=False) 升序: 选首个 dist <= 限 的级别;
    屏幕占比模式 (screen=True) 降序: 选首个 ratio >= 阈值 的级别。
    """
    out = []
    for item in (raw or []):
        try:
            thr, ref = item[0], item[1]
        except (TypeError, IndexError, KeyError):
            continue
        try:
            thr = float(thr)
        except (TypeError, ValueError):
            continue
        if thr != thr:            # NaN 防御
            continue
        mesh = _lod_mesh(ref)
        if mesh is None:
            continue
        out.append((thr, mesh))
    out.sort(key=lambda t: t[0], reverse=bool(screen))
    return out


def apply_lod_from_dict(m, obj):
    """场景物体 dict 的 LOD 段 -> 物体 renderer (M36 LOD 场景序列化恢复).

    与 agent_commands.set_lod 写入运行期的形态一致 (lod_levels / lod_screen_levels
    是 [(阈值, Mesh), ...], lod_bias 是浮点); 字段缺失 = 无 LOD (零开销).
    """
    r = getattr(m, 'renderer', None)
    if r is None or not isinstance(obj, dict):
        return
    lod = obj.get('lod')
    if not isinstance(lod, dict):
        lod = {}
    lv_d = _lod_levels(obj.get('lod_levels', lod.get('levels')), screen=False)
    lv_s = _lod_levels(obj.get('lod_screen_levels', lod.get('screen_levels')),
                       screen=True)
    bias = obj.get('lod_bias', lod.get('bias'))
    if bias is not None:
        # 下限与 agent_commands.set_lod 同 (bias<=0 会让 ratio 恒 0 = 永远最低模)
        r.lod_bias = max(0.1, _f1(bias, 1.0))
    if lv_d:
        r.lod_levels = lv_d
    if lv_s:
        r.lod_screen_levels = lv_s


def _xform_stamp(m):
    """物体 + 父链的变换快照 (纯比较, 不做矩阵运算).

    用途: LOD 世界位置缓存的有效性判据 —— 变换/父链没变就不重算矩阵。
    """
    out = []
    cur = m
    depth = 0
    while cur is not None and depth < 64:      # 深度上限防父链成环
        p = getattr(cur, 'position', None)
        r = getattr(cur, 'rotation', None)
        s = getattr(cur, 'scale', None)
        out.append((id(cur),
                    getattr(p, 'x', p), getattr(p, 'y', p), getattr(p, 'z', p),
                    getattr(r, 'x', r), getattr(r, 'y', r), getattr(r, 'z', r),
                    s[0] if s else 1.0, s[1] if s else 1.0, s[2] if s else 1.0))
        cur = getattr(cur, 'parent', None)
        depth += 1
    return tuple(out)


def build_cameras(data):
    """场景 dict -> CameraState 列表 (与 sceneio._apply_cameras 同字段语义).
    相机是"不可见实体": 不渲染/不碰撞, 只提供玩家视角位姿与 FOV。"""
    out = []
    for d in (data.get('cameras') or []):
        if not isinstance(d, dict):
            continue
        cam = CameraState(position=_f3(d.get('position'), (0, 0, -5)),
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
        out.append(cam)
    return out


def link_camera_parents(cameras, cam_dicts, models):
    """摄像机父链 (相机挂到 GameObject 下) — 与 sceneio._link_camera_parents 同:
    parent_id -> GameObject.guid; 找不到的父忽略 (孤儿引用保持根)。"""
    id_map = {m.guid: m for m in models if getattr(m, 'guid', None)}
    for cam, d in zip(cameras, cam_dicts or []):
        pid = d.get('parent_id') if isinstance(d, dict) else None
        if pid and pid in id_map:
            parent = id_map[pid]
            cam.parent = parent
            parent.camera_children.append(cam)


class SceneDriver:
    """播放器中间层: 场景 + 每帧步进 (脚本/物理/动画/轨道相机) + VP 计算.

    帧循环 (后端调用):  vp, cam_pos = world.step(dt)  → 后端画 world.models/world.lights
    """

    def __init__(self, data=None):
        self.models = []
        self.materials = []      # 2026-11-06 对齐 GL: 材质资产库 (PBR/共享材质)
        self.lights = []
        self.target = (0.0, 0.0, 0.0)     # 轨道相机目标 (场景文件恢复)
        self.distance = 10.0
        # 2026-11-06 对齐 GL: engine 默认 camera_yaw/pitch = 0/0 (场景无 'camera' 键
        # 时两端必须同视角)。2026-11-07 细化 (scan_05 P-04): 有 camera 键但缺字段时
        # 以 0.6/-0.35 兜底 (= sceneio.scene_from_dict 的 camera_out 默认值),
        # 具体取值在 load_from_data 的相机段按"有没有 camera 键"决定。
        self.yaw = 0.0
        self.pitch = 0.0
        self.fov = math.radians(60.0)
        # 2026-11-07: 暂停 / 退出 (与 EditorApp 同语义, 供脚本统一调用)
        self.logic_paused = False
        self.request_quit = False
        self._request_exit_play = False
        # 2026-11-07 修复: VK 播放器此前**从不加载** scripts/ 游戏脚本目录
        # (GL 播放器继承 GLEngine.__init__ 会加载), 导致打包后自定义脚本不生效。
        try:
            import os as _os
            from scripts import load_script_dir as _lsd
            _lsd(_os.path.join(_os.path.dirname(_os.path.abspath(__file__)), 'scripts'))
        except Exception:
            pass
        self.near = 0.1
        # 2026-11-06 R-02 修复 (双后端一致性): 这里原来写死 100.0, 而 GL 引擎
        # 在 2026-10-20 已把 far 提到 1000.0 (engine.py, 用户做远景/大场景需要)。
        # 同一场景切后端后可见距离差 10 倍 = "API 自由切换"名不副实。
        # 现值与 engine.GLEngine.far 对齐; near 也与之同值 (0.1)。
        self.far = 1000.0
        # B1: 物理桥 (首次 step 惰性建) + 重力 (场景文件覆盖, 默认 -9.8 同引擎)
        self._bridge = None
        self._bridge_disabled = getattr(physb, 'cv_available', False) is not True
        self._bridge_warned = False
        # 2026-11-07 (_fix_summary §5 遗留): 桥步进异常只在**本场**首次打印一条,
        # 后续只累加计数 —— 坏桥每帧抛异常时不再刷屏 (旧实现每帧一条).
        self._bridge_err_logged = False
        self._bridge_err_count = 0
        self.gravity = -9.8
        # B1: 脚本 "引擎 API 最小面" 输入/相机安全默认 (无输入=不动; 后端口喂键时
        # 直接写 key_state / actions)
        self.key_state = {}                      # 键名 -> bool (同 engine.script_keys)
        self.actions = dict(DEFAULT_ACTIONS)     # 动作 -> 键名列表 (同 engine.actions)
        # 2026-11-08 批2 (01 号遗留①): 键位加载改走"只读模板 + 用户层 delta"体系,
        # 权威常量来自 loom_input（模板名只在那里定义一次），用户层覆盖来自
        # game_settings.read_key_bindings()（%LOCALAPPDATA%\Loom\…）。
        # 本文件不再拼 '输入配置.json' 旧路径，也**不写**引擎目录
        # （docs/design/用户配置目录契约_20261108.md §4/§8）。
        try:
            import json as _json
            import game_settings as _gs
            from loom_input import (_ACTION_FILE as _TPL_NEW,
                                    _ACTION_FILE_LEGACY as _TPL_OLD)
            _d = os.path.dirname(os.path.abspath(__file__))
            _p = next((q for q in (os.path.join(_d, _TPL_NEW), os.path.join(_d, _TPL_OLD))
                       if os.path.exists(q)), None)
            _acts = None
            if _p is None:
                # 2026-11-08 批2 (N1): 两份模板都不存在 = 安装/裁剪异常，
                # 必须出声后回落默认（旧实现在这里被 except: pass 连带吞掉，
                # 连"NameError 导致从没读过键位"都看不见）。
                print('[输入] 键位模板缺失 (%s / %s 都不在 %s) -> 用默认键位'
                      % (_TPL_NEW, _TPL_OLD, _d))
            if _p is not None:
                try:
                    with open(_p, 'r', encoding='utf-8') as _f:
                        _tpl = _json.load(_f)
                    _acts = _tpl.get('actions') if isinstance(_tpl, dict) else None
                except Exception as e:
                    print('[输入] 键位模板读取失败 (%r): %s -> 用默认键位' % (e, _p))
            if isinstance(_acts, dict):
                for _a, _ks in _acts.items():
                    try:
                        self.actions[str(_a)] = list(_ks)
                    except Exception as e:
                        print('[输入] 键位模板条目 %r 非法 (%r) -> 跳过该条' % (_a, e))
            for _a, _ks in (_gs.read_key_bindings() or {}).items():
                self.actions[_a] = list(_ks)
        except Exception as e:
            print('[输入] 键位加载失败 (%r) -> 用默认键位' % (e,))
            self.actions = dict(DEFAULT_ACTIONS)
        self.mouse_rel = (0, 0)                  # 本帧鼠标增量 (像素, 同 engine.mouse_rel)
        # 2026-11-08 人类裁决（鼠标锁定语义重构）: **默认不锁** —— 没人要求就不锁。
        # 规则:
        #   · 只有游戏配置里**显式**写了 mouse_lock_allowed / mouse_locked 才生效；
        #     缺省 = allowed False / locked False（旧实现缺省 True/True，打包吃豆人因此被锁死）；
        #   · game_settings 的模块常量仍是旧默认（第 0 批负责改），所以这里按"显式键"判定，
        #     裁决落地不依赖别的批次；配置读不出来时同样按"不锁"处理（并出声）。
        try:
            # 与 GL 播放器**同一份**策略读取（第 3 批在 runtime 提供单点
            # read_mouse_lock_policy: 未配置 = False/False, initial 受 allowed 门控）。
            from runtime import read_mouse_lock_policy as _lock_policy
            self.mouse_lock_allowed, self.mouse_locked = _lock_policy()
        except Exception:
            # runtime 不可用（裁剪包/单测桩）时用同一条规则直读配置：
            # read_bool 缺省 False —— 与 game_settings.mouse_lock_allowed() 在
            # 第 0 批把模块默认改成 False 后完全等价。
            try:
                import game_settings as _gs
                self.mouse_lock_allowed = bool(_gs.read_bool('mouse_lock_allowed', False))
                self.mouse_locked = (bool(_gs.read_bool('mouse_locked', False))
                                     if self.mouse_lock_allowed else False)
            except Exception as e:
                print('[输入] 鼠标锁定策略读取失败 (%r) -> 本游戏不锁鼠标' % (e,))
                self.mouse_lock_allowed = False
                self.mouse_locked = False
        self.mouse_unlock_requested = False      # 玩家解锁意图 (同 engine.mouse_unlock_requested)
        self._ui_capture_mouse = False           # 特殊场景 (UI 菜单) 强制解锁 (同 engine)
        self.mouse_buttons = (False, False, False)   # (左, 中, 右) 同 pygame 顺序
        self.mouse_wheel = 0                     # 本帧滚轮 (+上/-下), 帧末清零(_end_frame_input)
        self.mouse_look_sens = 0.01              # 开发者视角 像素->弧度 (GL editor 同值)
        self.on_mouse_lock_changed = None        # 后端回调: 据此冻结/释放光标 (GL 同语义)
        self._pending_mouse_rel = (0.0, 0.0)     # 后端喂入的增量累积 (帧首结算成 mouse_rel)
        self.camera = Point3D(0, 0, -5)          # 脚本接管相机 (first_person 等)
        self.camera_yaw = 0.0
        self.camera_pitch = 0.0
        self.camera_roll = 0.0                   # 绕视线倾斜 (弧度) — 与 GL camera_roll 同
        # 2026-11-06 相机实体 (Unity Camera 概念): 与 engine.cameras/active_camera 同语义.
        # active_camera 存在 -> 载入即"玩家视角" (apply_camera, 关轨道相机), 与
        # runtime.PlayerApp 完全同一条分支; 不存在 -> 保持轨道相机 (行为不变).
        self.cameras = []
        self.active_camera = None
        self.orbit_mode = True                   # 脚本设置 False 表示脚本接管相机
        # 2026-10-18: 替换 _DriverUI 空壳为真 UIManager —— 数据层无 GPU 依赖,
        # 脚本 (count_touch 等) 用 e.ui.default_canvas() 建的元素树在 driver 层也能工作;
        # draw_all 只在渲染层调用, driver.draw() 是占位, 不会触发绘制.
        self.ui = UIManager()
        self.ui.add_canvas(Canvas(canvas_type='screen',
                                  width=getattr(self, 'width', 1280),
                                  height=getattr(self, 'height', 800)))
        # 方案二 (2026-09-05): 外推渲染模式设置键 (与 engine 同语义)
        try:
            import guiloader as _gl
            self._interp_mode = str(_gl.load_settings('loom').get(
                'interp_mode', 'interpolate'))
        except Exception:
            self._interp_mode = 'interpolate'
        # 分离批1+2: 双 accumulator 时钟 + 插值状态 (与 engine 同实现同语义)
        from core_clock import FixedStepClock, split_enabled
        from interp_state import InterpState
        self._split_enable = split_enabled()      # 设置面 logic_fps<=0 判定
        self._clock = FixedStepClock() if self._split_enable else None
        if self._clock is not None:
            self._clock.on_logic_step.append(self._logic_frame)
            # 批5: 物理不挂 on_physics_step (已删) — 子步在 _logic_frame 内循环
        self._interp = None                        # load_from_data 后建 (需 models)
        # 2026-11-07 LOD 世界位置缓存: id(model) -> (model, 变换戳, (wx,wy,wz))
        # 只在物体/父链变换变化时重算世界矩阵 (见 _lod_world_pos).
        self._lod_wpos = {}
        # 2026-11-07 (_fix_summary §5 遗留): 配了 LOD 的模型集合 —— 加载时登记,
        # 运行期靠 renderer._lod_gen 变化惰性重建; 空集合 = 每帧 O(1) 早退.
        self._lod_models = []
        self._lod_gen = MeshRendererComponent._lod_gen
        if data is not None:
            self.load_from_data(data)

    # ---------------- 加载 ----------------
    def load_from_data(self, data, base_dir=None):
        # 2026-11-06 对齐 GL (双后端一致): 先建材质资产库, 再建物体并挂 material_id,
        # 否则 Vk 播放器里所有 PBR/共享材质都会静默退化成默认材质。
        # 2026-11-06 天空盒 (与 GL 对齐): 场景级 skybox -> Cubemap 实例
        # 2026-11-09 (Q1=A / Q3=A / Q5=A): 与 GL/编辑器**逐条一致** —— 复用 sceneio 的解析
        # 入口: 缺 skybox 键 / null -> **默认蓝**; 失败出声并记 valid/error（不静默、不回退成无天空）。
        # 相机级优先见下方 effective_skybox()。base_dir = 场景文件目录（六面图相对路径用）。
        try:
            import sceneio as _sio
            self.skybox, self._skybox_valid, self._skybox_error = \
                _sio._scene_skybox_from_data(data, base_dir)
        except Exception as e:
            self.skybox, self._skybox_valid = None, False
            self._skybox_error = '天空盒解析入口不可用: %r' % (e,)
            print('[驱动] 天空盒加载失败: %s' % (self._skybox_error,))
        # 2026-11-06 Canvas UI (与 GL scene_from_dict._apply_ui 同源同序):
        # 场景 'ui' 段 -> self.ui (保留模式元素树)。此前 driver 只建了默认空
        # Canvas, 播放器 (Vk) 永远拿不到场景里的 UI —— 数据层无 GPU 依赖,
        # 这里恢复数据, 绘制由渲染层 (VkRenderer.draw_frame(ui=...)) 负责。
        try:
            import sceneio as _sio
            _sio._apply_ui(self, data.get('ui'))
        except Exception as _e:
            print('[driver] UI 恢复失败 (保留现状):', repr(_e))
        self.materials = build_materials(data)
        _mats = {m.guid: m for m in self.materials}
        self._lod_wpos = {}          # 换场景: 旧模型的缓存立刻失效
        self.models = build_models(data, materials=_mats)
        # 换场景: 重新登记配了 LOD 的模型 (空场景 -> _lod_models 空 -> 每帧早退)
        self._rebuild_lod_models()
        # 每场一条物理桥异常日志: 新场景重置"已打印/计数"
        self._bridge_err_logged = False
        self._bridge_err_count = 0
        self.lights = build_lights(data)
        # 2026-11-06 相机实体: 与 sceneio._apply_cameras + _link_camera_parents 同序
        # (先建相机, 物体建好后再连父) —— 顺序影响不到本函数 (父链只改 parent 指针).
        self.cameras = build_cameras(data)
        # 2026-11-09 Q3=A: 相机级 skybox（与 sceneio._apply_cameras 同口径、同 base_dir）
        # 2026-11-09 A6=A: 按**身份**(id/guid)配对, 不按下标 —— build_cameras 会跳过非 dict 段,
        # 按下标配对会把"别人的颜色"塞给激活相机(错色比不画更糟); 数量不匹配时明确告警,
        # 未匹配到的相机不配 skybox（宁可不画）。
        try:
            import sceneio as _sio3
            _cams_d = data.get('cameras') or []
            _by_id = {}
            _bad = 0
            for _cd in _cams_d:
                if isinstance(_cd, dict) and _cd.get('id'):
                    _by_id[str(_cd['id'])] = _cd
                else:
                    _bad += 1
            if _bad:
                print('[驱动] 相机段有 %d 个非法/无 id 条目 -> 这些条目不参与配对' % (_bad,))
            _unmatched = 0
            for _c in self.cameras:
                _cd = _by_id.get(str(getattr(_c, 'guid', '') or ''))
                if _cd is None:
                    _unmatched += 1
                    _c.skybox = None
                    _c._skybox_valid = False
                    _c._skybox_error = '相机无 id 或未匹配到场景相机段（按身份配对, 不猜）'
                    continue
                _raw = _cd.get('skybox')
                _cube, _v, _r = _sio3.skybox_from_dict(_raw, base_dir)
                _c.skybox = _cube
                _c._skybox_valid = bool(_v)
                _c._skybox_error = _r
            if _unmatched:
                print('[驱动] %d 个相机未按身份匹配到场景段 -> 不配 skybox' % (_unmatched,))
        except Exception as e:
            print('[驱动] 相机天空盒解析失败 (%r) -> 该相机沿用场景级' % (e,))
        link_camera_parents(self.cameras, data.get('cameras'), self.models)
        self.active_camera = data.get('active_camera')
        # 2026-11-07 P-05 修复 (相机段坏值不崩 + 默认值不分叉): 场景是外部输入,
        # 相机段此前是裸 float()/tuple(), 而**同一函数内**已有 _f3/_f1 容错助手
        # (sceneio 的对应实现早就用上了) —— 于是一份坏场景 GL 能开、Vk 在
        # load_from_data 或 render_pose 抛异常, 最后被 draw() 的 except 变成
        # os._exit(1)。这里与 sceneio.scene_from_dict 的 camera_out 分支逐条对齐:
        #   · 有 camera 键(且非空 dict) -> 缺字段回落 0.6/-0.35 (GL 同值);
        #   · 完全没有 camera 键 / 空 dict -> 保持引擎默认 0/0 (PlayerApp 同值);
        #   · 任一字段类型错/元素数不足 3 -> 回落默认, 不抛 (GL 同语义).
        cam = data.get('camera')
        _has_cam = isinstance(cam, dict) and bool(cam)
        if not _has_cam:
            cam = {}
        _def_yaw, _def_pitch = (0.6, -0.35) if _has_cam else (0.0, 0.0)
        # 2026-11-08 批2 (P-03-02/03/04/06, D7=A): 投影三件套是**场景相机属性**,
        # 读侧统一走 sceneio 的归一实现（唯一出处）:
        #   · 缺键       -> 默认 (旧场景兼容: fov=60°, ortho=False, size=12)
        #   · 类型非法   -> 出声后回落默认 (Q4=B: 不静默错值, 也不抛 -> B4 契约)
        #   · 数值越界   -> 钳制并警告 (ortho_size<=0 会让 mat4_ortho 除零; fov 越界无意义)
        # 注意: 这里**不再**在下面无条件重置 fov —— 旧实现把读到的场景 fov 立刻覆盖成
        # 60°, 导致 VK 忽略场景 fov 而 GL(PlayerApp) 生效（双后端分叉，审计 P-03-02）。
        try:
            import sceneio as _sio_cam
            _fov_deg = _sio_cam.norm_fov_deg(cam.get('fov'), '场景 camera.fov')
            _ortho_v = _sio_cam._b_strict(cam.get('ortho'), False, '场景 camera.ortho')
            _osz = _sio_cam.norm_ortho_size(cam.get('ortho_size'),
                                            '场景 camera.ortho_size')
        except Exception as e:
            print('[驱动] 相机投影字段归一失败 (%r) -> 用默认' % (e,))
            _fov_deg, _ortho_v, _osz = 60.0, False, 12.0
        self.fov = math.radians(_fov_deg)
        self.ortho = _ortho_v
        self.ortho_size = _osz
        self.target = _f3(cam.get('target'), (0, 0, 0))
        # 2026-11-06 R-03: 场景是外部输入, 距离在**入口**钳制 (与 GL 加载路径同语义).
        # 只钳 setter 会留下"加载路径绕过"的洞 (复核 B 实测 distance=5000 原样进场景).
        from loom_camera import clamp_camera_distance
        self.distance = clamp_camera_distance(_f1(cam.get('distance'), 10.0))
        self.yaw = _f1(cam.get('yaw'), _def_yaw)
        self.pitch = _f1(cam.get('pitch'), _def_pitch)
        # 加载 = 一次新会话基线: 相机 roll 归零 (投影三件套已在上面按场景相机段归一,
        # 有 active_camera 时下面 apply_camera 会用相机自身 fov 覆盖 —— 与 GL 同序)。
        self.camera_roll = 0.0
        # 玩家视角: 场景 active_camera 优先, 否则默认轨道相机 ——
        # 与 runtime.PlayerApp.__init__ 的分支逐条对应 (同一份场景, 同一台相机).
        _ac = self.active_camera_object()
        if _ac is not None:
            self.apply_camera(_ac)
        else:
            self.orbit_mode = True
        # B1 (2026-08-30): 场景 'gravity' 字段 (m/s², 负=向下) — 物理桥 R1 用
        self.gravity = float(data.get('gravity', -9.8))
        # 分离批2: 场景加载边界 (首抓=加载位姿, 首帧不插值)
        if self._split_enable:
            from interp_state import InterpState
            if self._interp is None:
                self._interp = InterpState(self.models)
            self._interp.advance()
            self._interp.align()
            if self._clock is not None:
                self._clock.reset()

    @property
    def camera_pos(self):
        """相机世界位置.
        轨道模式: 由 target/yaw/pitch/distance 反推 (与 engine.apply_orbit_camera
        同公式, 即 loom_camera.apply_orbit_camera).
        玩家相机模式 (orbit_mode=False): 场景 active_camera 经 apply_camera 写入的
        self.camera, 或脚本写入的 self.camera —— 朝向/倾斜由 render_pose 从
        camera_yaw/camera_pitch/camera_roll 读取 (与 GL loom_render 同源)."""
        if not getattr(self, 'orbit_mode', True):
            c = getattr(self, 'camera', None)
            if c is not None:
                return (c.x, c.y, c.z)
        ez = (math.sin(self.yaw) * math.cos(self.pitch),
              math.sin(self.pitch),
              math.cos(self.yaw) * math.cos(self.pitch))
        return (self.target[0] - self.distance * ez[0],
                self.target[1] - self.distance * ez[1],
                self.target[2] - self.distance * ez[2])

    # ---------------- 每帧步进 ----------------
    def _logic_frame(self, fixed_dt):
        """逻辑步 = 最高同步点 (批5): 脚本 → 物理子步 ×N → 动画
        (次序同 engine._logic_frame).
        2026-10-18 阶段1档序10 FixedUpdate：_update_scripts 前派发。"""
        self._dispatch_fixed_update(fixed_dt)
        self._update_scripts(fixed_dt)
        clk = self._clock
        sdt = clk.sub_dt if clk is not None else fixed_dt
        for _ in range(clk.sub_steps if clk is not None else 1):
            self._step_physics(sdt)
        self._update_animations(fixed_dt)
        if self._interp is not None:
            self._interp.advance()

    def set_logic_paused(self, paused):
        """2026-11-07: 统一暂停接口 (VK 播放器)."""
        self.logic_paused = bool(paused)
        # 2026-11-09 暂停重锚（同 GL: engine.toggle_logic_paused 暂停时时钟 reset）
        if self.logic_paused:
            self._pause_reanchored = True
            clk = getattr(self, '_clock', None)
            if clk is not None:
                try:
                    clk.reset()
                except Exception as e:
                    print('[驱动] 暂停重锚失败 (%r)' % (e,))
        else:
            self._pause_reanchored = False

    def request_game_exit(self):
        """2026-11-07: 统一退出接口 (VK 播放器 -> 关窗退出)."""
        self.request_quit = True

    # ---- 渲染后端切换 API (VK 播放器, 与 GLEngine 同签名) ----
    render_api_current = 'vulkan'

    def get_render_api(self):
        return getattr(self, 'render_api_current', 'vulkan')

    def get_saved_render_api(self):
        try:
            import game_settings
            return game_settings.read_render_api()
        except Exception:
            return None

    def set_render_api(self, api):
        """写**用户层**的游戏设置 (重启生效)。返回 {'ok','saved','current','path'?}.

        2026-11-08 批2 (契约 §7/§8.1): 失败时 ok=False + error，且**不打印成功语气**；
        路径取 game_settings.user_path()（用户层唯一落点），不再指向引擎目录。
        """
        ok, val, err, p = False, None, None, None
        try:
            import game_settings
            ok, val, err = game_settings.write_render_api(api)
            p = game_settings.user_path()
        except Exception as e:
            err = '写入失败: %r' % (e,)
        res = {'ok': bool(ok), 'saved': val, 'current': self.get_render_api(),
               'restart_required': True, 'path': (p if ok else None)}
        if err:
            res['error'] = err
        if ok:
            print('[渲染后端] 已写入用户层配置 %r -> %s (重启游戏后生效; 当前 %s)'
                  % (val, p, res['current']))
        else:
            print('[渲染后端] 写入失败: %s (当前 %s)' % (err, res['current']))
        return res

    def _physics_frame(self, phys_dt):
        """分离批1: 60Hz 物理步 (R1: 只改调用时机, 桥三段一行不动)."""
        self._step_physics(phys_dt)

    def advance_logic(self, render_dt=None):
        """分离批1 渲染帧入口: 时钟推进 (排 0~N 逻辑步 + 0~M 物理步).
        logic_fps<=0 → 旧绑死: 直接以 render_dt 跑一遍三段
        (★B7b 2026-10-16: 删 LOOM_NO_SPLIT 逃生门; 绑死模式仅由设置触发)."""
        # 2026-11-06 输入/相机帧首 (与 GL 同序: 鼠标结算 -> 挂父相机重应用 ->
        # 开发者视角鼠标 -> 逻辑步 (脚本)) —— 脚本后写仍覆盖, 契约不变。
        # 2026-11-07 通关暂停: 逻辑帧冻结 (脚本/物理/动画都不走), 渲染继续
        if getattr(self, 'logic_paused', False):
            # 2026-11-09 (与 01 号 GL 侧「暂停重锚」对齐): 暂停期把**本驱动时钟自己的**
            # 锚点清一次（FixedStepClock 的 _acc/_last），保证恢复首帧不补暂停期欠账。
            # 说明: VK 侧时钟吃的是调用方 render_dt（不是墙钟），本来就不会追帧 —— 这里
            # 重锚是防"将来改成墙钟口径/换时钟实现"的回归，并与 GL 的形状保持一致。
            if not getattr(self, '_pause_reanchored', False):
                self._pause_reanchored = True
                clk = getattr(self, '_clock', None)
                if clk is not None:
                    try:
                        clk.reset()
                    except Exception as e:
                        print('[驱动] 暂停重锚失败 (%r)' % (e,))
            # 2026-11-08 批2 (P-03-07): 暂停冻结的是"游戏逻辑", 不能连**输入逃生通道**
            # 一起冻掉 —— 解锁键轮询从逻辑帧移到渲染帧（裁决 D6=A: 引擎独占该键）。
            self.poll_unlock()
            # 暂停期鼠标增量既不结算也不累积: 旧实现让 _pending_mouse_rel 整段累积,
            # 恢复首帧一次性结算成数百像素的巨值（B6 契约: mouse_rel 只能是"本帧"增量）。
            self._pending_mouse_rel = (0.0, 0.0)
            self.mouse_rel = (0, 0)
            self._end_frame_input()
            return (0, 0)
        self._pause_reanchored = False        # 恢复态: 允许下一次暂停再重锚一次
        self.consume_mouse_input()
        self._refresh_player_camera()
        # 2026-11-06 对齐 GL PlayerApp: 播放器本身**没有**开发者视角鼠标
        # (右键转视角/滚轮推拉只存在于 EditorApp 播放态)。默认关闭, 需要时
        # 用 LOOM_VK_DEVMOUSE=1 打开 (vk_player 负责置位)。
        if getattr(self, 'dev_mouse_enabled', False):
            self.apply_dev_camera_mouse()
        if self._split_enable and self._clock is not None:
            r = self._clock.advance(render_dt)
            # 方案二: 外推资格 = 设置开 + 本渲染帧没跑逻辑步 (落点帧回退);
            # 挂到 _interp._extrap_mode 供 vk_renderer.world_matrices 消费
            it = getattr(self, '_interp', None)
            if it is not None:
                it._extrap_mode = (1 if (self._interp_mode == 'extrapolate'
                                         and not self._clock.steps) else 0)
            # 2026-10-18 阶段1档序11 LateUpdate（渲染帧尾, 逻辑步全部跑完之后）
            self._dispatch_late_update(render_dt)
            self._end_frame_input()
            return r
        self._update_scripts(render_dt)
        self._step_physics(render_dt)
        self._update_animations(render_dt)
        # 2026-10-18 阶段1档序11 LateUpdate（绑死模式: update 之后）
        self._dispatch_late_update(render_dt)
        self._end_frame_input()
        return (1, 1)

    def _end_frame_input(self):
        """帧末复位"本帧"输入量 —— 与 GL 同语义 (loom_glfw_window.py:285 每帧
        mouse_wheel = 0, 再写入本帧值)。

        2026-11-07 scan_05 P-06 修复: mouse_wheel 的唯一清零点原先在
        apply_dev_camera_mouse 里, 而该方法被 dev_mouse_enabled 门控 (默认
        False) —— 于是默认配置下滚轮从不清零, 每帧累加, 读到的永远不是
        "本帧滚轮"。现在无论 dev_mouse 开关都清零, 字段契约 (:301) 恢复成立。
        """
        self.mouse_wheel = 0

    def _lod_world_pos(self, m):
        """物体世界位置 (S@R@T 行向量矩阵的平移行) — 按变换戳缓存.

        scan_05 P-01: 旧实现每帧对**全部** models 重算一遍世界矩阵 (2.2ms/帧,
        500 物体), 而结果只用来读平移列。这里只给配了 LOD 的物体算, 且物体/
        父链变换未变时复用缓存 —— 相机移动不使世界矩阵失效, 只影响距离判定。
        """
        stamp = _xform_stamp(m)
        ent = self._lod_wpos.get(id(m))
        if ent is not None and ent[0] is m and ent[1] == stamp:
            return ent[2]
        M = object_world_matrix(m)
        pos = (float(M[3][0]), float(M[3][1]), float(M[3][2]))
        self._lod_wpos[id(m)] = (m, stamp, pos)     # 保引用防 id 复用
        return pos

    def _rebuild_lod_models(self):
        """重建"配了 LOD 的模型"集合 (加载/运行期 LOD 配置变化时的一次性 O(N)).

        2026-11-07 (_fix_summary §5 遗留): 旧 _update_lod 每帧遍历全部 models
        找候选 (~0.11ms/帧 @500 物体, 无 LOD 也白扫)。现在集合只在加载时
        (build_models 之后) 与 renderer._lod_gen 变化时重建, 其余帧 O(1) 早退;
        有 LOD 时只遍历该集合。运行期脚本/撤销/EAI 直接写 renderer.lod_*
        会 bump 代, 下一帧自动重建 (含摘除 LOD 后的剪枝)。
        """
        out = []
        for m in self.models:
            r = getattr(m, 'renderer', None)
            if r is None:
                continue
            if getattr(r, 'lod_screen_levels', None) or getattr(r, 'lod_levels', None):
                out.append(m)
        self._lod_models = out
        self._lod_gen = MeshRendererComponent._lod_gen

    def _update_lod(self):
        """M36 LOD (2026-10-14 GL 侧实现) 的 Vulkan 对齐版 (2026-11-06).

        GL 在渲染层按相机距离/屏幕占比给配了 lod_levels 的物体换网格精度;
        Vk 播放器此前不换精度 -> 同一场景远处物体在 Vk 下仍是高模 (画面与
        性能都不一致)。这里逐行照搬 loom_render._update_lod 的判定, 世界位置
        用本文件同源数学 (object_world_matrix: 行向量 S@R@T 沿父链)。

        2026-11-07 (scan_05 P-01/P-02 + _fix_summary §5 遗留):
          · 维护"配了 LOD 的模型"集合 (加载登记 + _lod_gen 变化重建), 集合为空
            时 O(1) 早退 —— 默认路径不再每帧全量扫描 (旧 0.11ms/帧 @500 物体);
          · 只给配了 LOD 的物体算世界位置, 并按变换戳缓存 (见 _lod_world_pos);
          · LOD 配置现在来自场景文件 (apply_lod_from_dict), 选模不再是死代码。
        """
        if MeshRendererComponent._lod_gen != self._lod_gen:
            self._rebuild_lod_models()      # 运行期挂/摘 LOD 或模型列表变动
        cands = self._lod_models
        if not cands:                       # 早退: 无 LOD 物体 (默认路径)
            return
        cam = self.camera_pos
        cx, cy, cz = cam
        tan_half = math.tan(self.fov * 0.5)
        n_live = 0
        for m in cands:
            r = getattr(m, 'renderer', None)
            if r is None:
                continue
            lv_screen = getattr(r, 'lod_screen_levels', None)
            lv_dist = getattr(r, 'lod_levels', None)
            if not (lv_screen or lv_dist):  # 运行期被摘除 (gen 未覆盖的旁路)
                continue
            n_live += 1
            wx, wy, wz = self._lod_world_pos(m)
            dx, dy, dz = wx - cx, wy - cy, wz - cz
            dist = (dx * dx + dy * dy + dz * dz) ** 0.5
            if lv_screen:
                rad = getattr(r, '_lod_radius', None)
                if rad is None:
                    v = np.asarray(getattr(m.mesh, 'vertices', []), dtype=np.float64)
                    rad = float(np.sqrt((v * v).sum(axis=1)).max()) if len(v) else 1.0
                    r._lod_radius = rad
                denom = max(dist, 1e-3) * tan_half
                bias = float(getattr(r, 'lod_bias', 1.0) or 1.0)
                ratio = (rad / denom) * bias
                pick = lv_screen[-1][1]
                for thr, mesh in lv_screen:
                    if ratio >= thr:
                        pick = mesh
                        break
            else:
                pick = lv_dist[-1][1]
                for lim, mesh in lv_dist:
                    if dist <= lim:
                        pick = mesh
                        break
            if getattr(r, '_lod_cur', None) is not pick:
                r._lod_cur = pick
                m.mesh = pick
                m.primitive = getattr(pick, 'primitive', None)
                m.params = getattr(pick, 'params', None)
        if n_live != len(cands):            # 集合里有失效项 -> 一次性重建剪枝
            self._rebuild_lod_models()

    def render_pose(self, aspect=None):
        """渲染帧: 插值平面状态 + VP 计算 (渲染层每帧调).
        alpha 由 vk_player 从 self._clock.alpha 透传设进 self._interp.
        2026-11-06 对齐 GL (loom_render.render): 轨道相机用 target/yaw/pitch 合成
        (roll 恒 0); 玩家相机 (active_camera / 脚本接管) 用 camera_yaw/pitch/roll
        + 相机自身 fov —— 同一场景两后端看同一台相机。"""
        self._update_lod()          # 2026-11-06: 与 GL 同语义的 LOD 选模
        cam_pos = self.camera_pos
        if getattr(self, 'orbit_mode', True):
            yaw, pitch, roll = self.yaw, self.pitch, 0.0
        else:
            yaw = self.camera_yaw
            pitch = self.camera_pitch
            roll = self.camera_roll
        V = mat4_view_yaw_pitch(np, cam_pos, yaw, pitch, roll)
        if getattr(self, 'ortho', False):
            _h = float(getattr(self, 'ortho_size', 12.0))
            _asp = aspect or 1.6
            P = mat4_ortho(np, -_h * _asp * 0.5, _h * _asp * 0.5,
                           -_h * 0.5, _h * 0.5, self.near, self.far)
        else:
            P = mat4_perspective(np, self.fov, aspect or 1.6, self.near, self.far)
        return V @ P, cam_pos

    def step(self, dt, aspect=None):
        """兼容入口 (旧探针/测试直调): advance_logic(dt) + 返回 VP.
        语义变化说明: 分离开时 dt 只进 accumulator (不再每调用必步进)."""
        self.advance_logic(dt)
        if self._split_enable and self._interp is not None:
            self._interp.alpha = self._clock.alpha
        return self.render_pose(aspect)

    # ---------------- B1: 物理桥 ----------------
    def _ensure_phys_bridge(self):
        """惰性建桥 (首次 step 直调; culverin 缺失/建体失败 -> None, 此后不重试)."""
        if self._bridge_disabled:
            return None
        if physb is None or not physb.cv_available:
            self._bridge_disabled = True
            if not self._bridge_warned:
                self._bridge_warned = True
                print("[驱动] 物理: culverin 不可导入 -> 无物理步进 (legacy 语义缺失)")
            return None
        try:
            br = physb.PhysicsWorldBridge()
            br.build(self.models)
        except Exception as e:
            print("[驱动] 物理桥建体失败 (%r) -> 无物理步进" % (e,))
            self._bridge_disabled = True
            return None
        self._bridge_disabled = False
        print("[驱动] Jolt (Culverin) 物理桥已建立: %d 体" % br.body_count)
        return br

    def _step_physics(self, dt):
        """物理桥三段 (脚本后/动画前, 同 engine 帧序): ensure_models 差量 ->
        pre_step (脏同步+策略R+手动重力 R1) -> step (释放 GIL) -> post_step 回读."""
        br = self._bridge
        if br is None:
            br = self._bridge = self._ensure_phys_bridge()
        if br is None:
            return
        try:
            br.ensure_models(self.models)
            br.pre_step(dt, self.gravity)
            br.step(dt)
            br.post_step()
        except Exception as e:
            # 2026-11-07 (_fix_summary §5 遗留): 坏桥每帧都抛 -> 只在**本场**
            # 首次打印一条, 之后只累加 _bridge_err_count, 不再刷屏。
            self._bridge_err_count += 1
            if not self._bridge_err_logged:
                self._bridge_err_logged = True
                print("[驱动] 物理桥步进异常 (%r) -> 本帧跳过; 本场后续同类异常"
                      "只计数不打印" % (e,))


    def poll_unlock(self):
        """跨批 API（与 GLEngine.poll_unlock 同签名）: True = 本帧发生一次翻转。

        2026-11-08 批2 接线点（第 1 批 01 号定稿）: advance_logic 的 logic_paused
        早退分支**之前**每渲染帧调用一次 —— 暂停只冻结游戏逻辑，不冻结输入逃生通道。
        GL 侧由 GLEngine.update_scripts 内置一次，**不得**在这里重复调用
        （同一帧翻两次就回到 P-03-01 的病灶）。
        """
        return self._poll_mouse_unlock_key()

    def _poll_unlock_now(self):
        """poll_unlock 的驱动内别名（保留旧调用名，语义完全一致）。"""
        return self.poll_unlock()

    # ---- GL 同名按键快照别名 + 一次性告警（D6=A 委托的前置条件） ----
    @property
    def script_keys(self):
        """GL 侧同名按键快照（InputMixin 用 `script_keys`，驱动用 `key_state`）。

        2026-11-08 批2 返修（独立验收 B 条）: `engine.GLEngine._poll_mouse_unlock_key`
        的前置检查要求 `script_keys` 是 dict；缺这个别名时委托**会悄悄失败**并退回
        驱动内的语义拷贝 —— 正是 D6=A 要消灭的"两套语义"。这里把它暴露成
        **同一个 dict**（读写同源，不做拷贝，`key_state` 仍是唯一存储）。
        """
        ks = self.__dict__.get('key_state')
        if ks is None:                      # 未初始化（极端构造顺序）-> 建一个
            ks = self.__dict__['key_state'] = {}
        return ks

    def _warn_once(self, key, msg):
        """一次性告警（每进程每个 key 只打一条，绝不每帧刷屏）。"""
        seen = self.__dict__.setdefault('_warn_once_seen', set())
        if key in seen:
            return
        seen.add(key)
        print(msg)

    def _warn_unlock_poll_unavailable(self, what):
        """engine 唯一实现的"前置缺失"回调（vk_player 解析器要求可调用）。"""
        self._warn_once('unlock_poll_unavailable',
                        '[输入] 解锁键轮询缺 %s -> 本局解锁键不生效' % (what,))

    def _poll_mouse_unlock_key(self):
        """解锁键检测 —— **只做委托**：engine.GLEngine._poll_mouse_unlock_key（D6=A）。

        2026-11-08 批2 返修（独立验收 B 条）: 旧版在本文件留了一份 `_poll_unlock_local`
        语义拷贝，且因缺 `script_keys`/告警回调，vk_player 解析器实际总是走到那份拷贝上
        —— "唯一实现"没达成。现在:
          · 本文件**不再有**任何切换语义（拷贝已删）；
          · `script_keys` property + `_warn_unlock_poll_unavailable` 满足引擎前置，
            解析器会真正绑定到 `GLEngine._poll_mouse_unlock_key`；
          · 只有"engine 不可用/实现缺失"这一条兜底，且用**一次性**告警；
          · 委托调用内部的异常**不吞**（引擎实现自己已按 N3 做了预期内缺失的一次性告警）。
        返回: True = 本帧发生一次翻转（与 GLEngine.poll_unlock 同返回）。
        """
        try:
            from engine import GLEngine as _GE
        except Exception as e:          # 裁剪包: 没有 engine 模块
            self._warn_once('unlock_delegate_import',
                            '[输入] 解锁键委托失败: 无 engine 模块 (%r) -> 本局解锁键不生效'
                            % (e,))
            return False
        impl = getattr(_GE, '_poll_mouse_unlock_key', None)
        if not callable(impl):
            self._warn_once('unlock_delegate_impl',
                            '[输入] 解锁键委托失败: engine.GLEngine 缺 '
                            '_poll_mouse_unlock_key -> 本局解锁键不生效')
            return False
        return bool(impl(self))


    # ---- 键位 API (2026-11-07, 游戏开发者做"改键 UI"用) ----
    def rebind_action(self, name, keys):
        """改键 (VK 播放器): 立即生效 + 写入**用户层**配置。

        2026-11-08 批2 (用户配置目录契约 §7/§8.1): 只写 %LOCALAPPDATA%\Loom\… 的
        game_settings 用户层，绝不写引擎目录的只读模板；**写失败上抛**（不再
        except: pass 假装成功），由 set_action_binding / 改键 UI 如实告知玩家。
        内存里的绑定先改（本局立即生效），落盘失败只影响"下次启动"。
        """
        keys = list(keys)
        self.actions[name] = keys
        import game_settings
        game_settings.write_key_binding(name, keys)
        return keys

    def get_action_bindings(self):
        """全部动作 -> 键名列表 (供 UI 展示当前键位)。"""
        try:
            return {a: list(ks) for a, ks in self.actions.items()}
        except Exception:
            return {}

    def set_action_binding(self, action, keys):
        """改某个动作的按键并**写入用户层配置** (立即生效)。

        2026-11-08 批2 (契约 §7): saved 只在真落盘时为 True；写失败返回
        ok=False + saved=False + error（不再返回 {'ok': True, 'saved': True} 假成功）。

        keys: 'f' 或 ['f','F10']。返回 {'ok','action','keys','saved','path'?}。
        """
        action = str(action)
        keys = [keys] if isinstance(keys, str) else list(keys or [])
        keys = [str(k) for k in keys if str(k)]
        try:
            self.rebind_action(action, keys)
        except Exception as e:
            print('[输入] 写键位失败: %r' % (e,))
            return {'ok': False, 'action': action, 'keys': keys,
                    'saved': False, 'error': repr(e)}
        res = {'ok': True, 'action': action, 'keys': keys, 'saved': True}
        try:
            import game_settings
            res['path'] = game_settings.user_path()
        except Exception as e:
            print('[输入] 取用户层路径失败 (%r)' % (e,))
        return res

    def _update_scripts(self, dt):
        """复刻 engine.GLEngine.update_scripts: 惰性实例化 + update (坏脚本标记跳过).
        组2: 引用迭代 (与 engine 同改; 契约: update 不增删本物体脚本组件).
        2026-10-18 阶段1档序12 执行顺序：按 Script.order 稳定排序后再 update。"""
        # 2026-11-08 批2: 轮询移到 docstring 之后 —— 旧位置让本函数的文档字符串退化
        # 成"无效果字符串表达式"（__doc__ = None, 审计 P-01-10 的同款问题）。
        # 非暂停帧的轮询仍在这里（暂停帧由 advance_logic 的 _poll_unlock_now 负责，
        # 两处都带按下沿检测 _unlock_key_prev，同一帧重复调用不会翻转两次）。
        self._poll_mouse_unlock_key()
        # 先收集所有脚本实例（惰性实例化）
        items = []
        for m in self.models:
            for sc in m.scripts:
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
                    s.engine = self          # 中间层代跑引擎角色 (脚本仅用 models/api)
                    for key, _label, default, *_ in cls.params:
                        if key in sc.script_vars:
                            s.vals[key] = sc.script_vars[key]
                    sc._script = s
                    try:
                        s.on_start()
                    except Exception as e:
                        print("[脚本] %s.on_start 出错: %r" % (m.name, e))
                        sc._script = None
                        sc._script_broken = True
                        continue
                items.append((m, sc, s))
        # 按 order 稳定排序（小者先；同 order 保持物体+脚本顺序）
        if items:
            try:
                items.sort(key=lambda t: getattr(type(t[2]), 'order', 0))
            except Exception:
                pass
        for m, sc, s in items:
            try:
                s.update(dt)
                # 2026-10-18 协程：Vk 路径同步推进
                if hasattr(s, '_drive_coroutines'):
                    s._drive_coroutines(dt)
            except Exception as e:
                print("[脚本] %s(%s) 出错: %r" % (m.name, sc.script_id, e))
                if hasattr(s, 'stop_all_coroutines'):
                    s.stop_all_coroutines()
                sc._script = None
                sc._script_broken = True

    def _dispatch_fixed_update(self, fixed_dt):
        """2026-10-18 阶段1档序10 FixedUpdate（Vk 后端同步版）。"""
        try:
            from scripts import Script as _Base
        except ImportError:
            return
        for m in self.models:
            if not m.scripts:
                continue
            for sc in m.scripts:
                inst = getattr(sc, '_script', None)
                if inst is None or getattr(sc, '_script_broken', False):
                    continue
                if type(inst).on_fixed_update is _Base.on_fixed_update:
                    continue
                try:
                    inst.on_fixed_update(fixed_dt)
                except Exception as e:
                    print("[脚本] %s(%s).on_fixed_update 出错: %r"
                          % (m.name, sc.script_id, e))
                    sc._script_broken = True

    def _dispatch_late_update(self, render_dt):
        """2026-10-18 阶段1档序11 LateUpdate（Vk 后端同步版）。"""
        try:
            from scripts import Script as _Base
        except ImportError:
            return
        for m in self.models:
            if not m.scripts:
                continue
            for sc in m.scripts:
                inst = getattr(sc, '_script', None)
                if inst is None or getattr(sc, '_script_broken', False):
                    continue
                if type(inst).on_late_update is _Base.on_late_update:
                    continue
                try:
                    inst.on_late_update(render_dt)
                except Exception as e:
                    print("[脚本] %s(%s).on_late_update 出错: %r"
                          % (m.name, sc.script_id, e))
                    sc._script_broken = True

    def _update_animations(self, dt):
        """复刻 engine.GLEngine.update_animations: 推进动画插值应用变换."""
        for m in self.models:
            an = m.animator
            if an is None or not an.playing or not an.current:
                continue
            clip = an.clips.get(an.current)
            if clip is None or not clip.frames:
                continue
            an.time += dt
            s = clip.sample(an.time)
            if 'position' in s:
                m.position = Point3D(*s['position'])
            if 'rotation' in s:
                m.rotation = Point3D(*s['rotation'])
            if 'scale' in s:
                m.set_scale(s['scale'])
            if clip.duration > 0 and an.time >= clip.duration:
                if an.loop:
                    an.time -= clip.duration
                else:
                    an.playing = False

    # ================ B1: 脚本 "引擎 API 最小面" (修 Vk 播放器脚本 broken) ================
    # 与 engine.GLEngine 同签名同语义 (几何走 physics_bridge 静态助手, 公式逐位
    # 一致); 输入/相机按安全默认 (无输入=不动), 后端口可喂 key_state。

    def world_position(self, m):
        """物体中心世界坐标 (含父链) — 与 engine.world_position 同."""
        if physb is None:
            p = m.position
            return Point3D(p.x, p.y, p.z) if p is not None else Point3D(0, 0, 0)
        wp = physb.world_position_vec(m)
        return Point3D(float(wp[0]), float(wp[1]), float(wp[2]))

    def move_with_collision(self, m, dx, dy, dz, bounds=None):
        """带碰撞的位移 (M28 响应) — 与 engine.move_with_collision 逐位一致.
        返回 True = 被挡住/发生碰撞."""
        if physb is None:
            return False
        return physb.move_with_collision(self.models, m, dx, dy, dz, bounds)

    def get_collisions(self, m, fw=None, bounds=None):
        """碰撞查询 — 与 engine.get_collisions 同 (其他物体按 models 顺序)."""
        if physb is None:
            return []
        return physb.get_collisions(self.models, m, bounds)

    def collider_hit(self, a, b):
        """两物体是否碰撞 (同树不算) — 与 engine.collider_hit 同."""
        if physb is None:
            return False
        return physb.collider_hit(a, b)

    # ---- 输入 (安全默认: 无键=不动; 后端口喂数据写 key_state / 改 actions) ----
    def is_key(self, name):
        """按键状态查询 — 同 engine.is_key; 默认全 False (无输入=不动)."""
        return bool(self.key_state.get(name, False))

    def get_action(self, name):
        """输入动作层查询 — 同 engine.get_action; 默认 False."""
        for k in self.actions.get(name, (name,)):
            if self.key_state.get(k, False):
                return True
        return False

    # ---- 鼠标 (与 loom_input.InputMixin 同语义: 锁定状态机 + 指针增量) ----
    def set_mouse_lock_allowed(self, allowed):
        """游戏级开关: 本游戏**是否允许**锁定鼠标（人类裁决 2026-11-08, 默认 False）.

        能力②的实现点: 脚本可以在某场景/某时刻显式开关（例如进 FPS 关卡才允许锁）。
        allowed 变 False 时若当前处于锁定态 -> 立即解锁（否则玩家会被永久锁死、
        光标出不来，这正是打包版吃豆人的现场）。返回生效后的 allowed。
        """
        self.mouse_lock_allowed = bool(allowed)
        if not self.mouse_lock_allowed and getattr(self, 'mouse_locked', False):
            self.set_mouse_locked(False)
        return self.mouse_lock_allowed

    def set_mouse_locked(self, locked):
        """锁定/释放鼠标 (True=隐藏+捕获, False=显示+释放) — 同 engine.set_mouse_locked.

        2026-11-08 人类裁决: `mouse_lock_allowed=False` 时 **True 无效**（一次性告警），
        只允许解锁方向；这样"没人要求就不锁"是硬保证，脚本误调也锁不上。
        后端光标副作用只经 `on_mouse_lock_changed` 回调转发（不在这里碰 GLFW），
        与 GL 侧 set_mouse_locked -> view/glfw 的分工保持一致。
        """
        want = bool(locked)
        if want and not bool(getattr(self, 'mouse_lock_allowed', False)):
            self._warn_once('lock_not_allowed',
                            '[输入] 本游戏不允许锁定鼠标 (mouse_lock_allowed=False): '
                            'set_mouse_locked(True) 被忽略; 需要锁定时先调 '
                            'set_mouse_lock_allowed(True) / 在 游戏设置.json 写 '
                            'mouse_lock_allowed=true')
            want = False
        self.mouse_locked = want
        cb = self.on_mouse_lock_changed
        if cb is not None:
            try:
                cb(want)
            except Exception as e:
                self._warn_once('mouse_lock_cb',
                                '[输入] 鼠标锁定回调异常 (%r) -> 后端光标可能不同步' % (e,))

    def _apply_mouse_lock(self):
        """按 [特殊场景标志 | 玩家解锁意图] 计算实际锁定 — 同 InputMixin._apply_mouse_lock."""
        self.set_mouse_locked(not (self._ui_capture_mouse or self.mouse_unlock_requested))

    def toggle_mouse_locked(self):
        """Tab 切换玩家解锁意图 — 同 InputMixin.toggle_mouse_locked
        (特殊场景下强制清零, 退出特殊场景后鼠标自动回锁).

        不允许锁定鼠标的游戏里这个是空操作（意图保持 False，不会"解锁一个本来就没锁的光标"）。
        """
        if not bool(getattr(self, 'mouse_lock_allowed', False)):
            self._warn_once('toggle_not_allowed',
                            '[输入] 本游戏不允许锁定鼠标 -> 解锁键无效果'
                            ' (mouse_lock_allowed=False)')
            self.mouse_unlock_requested = False
            return
        if self._ui_capture_mouse:
            self.mouse_unlock_requested = False
        else:
            self.mouse_unlock_requested = not self.mouse_unlock_requested
        self._apply_mouse_lock()

    def set_ui_capture_mouse(self, capture):
        """特殊场景 (UI 菜单/暂停) 强制显示鼠标并清解锁意图 — 同 InputMixin."""
        self._ui_capture_mouse = bool(capture)
        if capture:
            self.mouse_unlock_requested = False
        self._apply_mouse_lock()

    def feed_mouse_rel(self, dx, dy):
        """后端喂光标增量 (像素). 仅锁定状态累积 —— 与 loom_glfw_window._update_mouse_rel
        (只在该模式 CURSOR_DISABLED 时更新 mouse_rel) 同语义: 解锁后滑动不转视角."""
        if not self.mouse_locked:
            self._pending_mouse_rel = (0.0, 0.0)
            return
        px, py = self._pending_mouse_rel
        self._pending_mouse_rel = (px + float(dx), py + float(dy))

    def consume_mouse_input(self):
        """帧首结算鼠标增量: 累积值 -> mouse_rel (int 截断, 同 GL 的 int(dx)).
        解锁状态不覆盖 mouse_rel (保留上次值, 与 GL 防突跳一致)."""
        px, py = self._pending_mouse_rel
        self._pending_mouse_rel = (0.0, 0.0)
        if self.mouse_locked:
            self.mouse_rel = (int(px), int(py))

    def apply_dev_camera_mouse(self):
        """开发者 (轨道) 相机鼠标: 滚轮推拉 + 右键拖动转视角.
        公式与 GL editor._update_camera 逐位一致 (0.01 弧度/像素, pitch 钳 ±1.55,
        distance *= exp(-wheel*0.1) 再钳 0.5..1000). 只在轨道模式生效 ——
        玩家相机 (active_camera) 接管时与 GL 一样不由鼠标直接改相机; 滚轮读后清零."""
        from loom_camera import CAM_DIST_MIN, CAM_DIST_MAX
        wheel = self.mouse_wheel
        self.mouse_wheel = 0
        if not getattr(self, 'orbit_mode', True):
            return
        if wheel:
            self.distance = max(CAM_DIST_MIN, min(
                CAM_DIST_MAX, self.distance * math.exp(-wheel * 0.1)))
        mx, my = self.mouse_rel
        if self.mouse_buttons[2]:          # 右键按住拖动 = 转视角 (GL 同)
            self.yaw += mx * self.mouse_look_sens
            self.pitch = max(-1.55, min(1.55,
                                        self.pitch - my * self.mouse_look_sens))

    # ---- 摄像机实体 (Unity Camera): 与 loom_camera.CameraMixin 同语义 ----
    def find_camera(self, guid):
        """按 guid 找摄像机, 找不到返回 None."""
        for cam in self.cameras:
            if cam.guid == guid:
                return cam
        return None

    def effective_skybox(self):
        """生效天空盒（Q3=A，与 GLEngine.effective_skybox 同口径）: 相机级优先, 否则场景级。

        2026-11-09 与 GL/编辑器对齐: 上层（命令层/场景运行期）把"当前相机天空盒"写在
        CameraState.skybox，VK 侧不再各写一套优先级。
        """
        try:
            cam = self.active_camera_object()
        except Exception as e:
            print('[驱动] 取激活相机失败 (%r) -> 天空盒回退场景级' % (e,))
            cam = None
        cube = getattr(cam, 'skybox', None) if cam is not None else None
        if cube is not None:
            return cube
        return getattr(self, 'skybox', None)

    def active_camera_object(self):
        """当前玩家视角摄像机对象 (无则 None)."""
        return self.find_camera(self.active_camera) if self.active_camera else None

    def camera_world_position(self, cam):
        """摄像机世界位置 (父链合成) — 与 loom_camera.camera_world_position 同:
        局部位置 @ 父世界矩阵 (含父缩放, 与物体同构)."""
        p = np.array([cam.position.x, cam.position.y, cam.position.z, 1.0])
        if cam.parent is not None:
            p = p @ object_world_matrix(cam.parent)
        return Point3D(float(p[0]), float(p[1]), float(p[2]))

    def camera_world_basis(self, cam):
        """摄像机世界正交基 (ex,ey,ez) 行向量 (= 世界->视图旋转) —
        与 loom_camera.camera_world_basis 同 (同 trig/负绕向, 父链只取旋转部分)."""
        yaw = math.radians(cam.yaw)
        pitch = math.radians(cam.pitch)
        roll = math.radians(cam.roll)
        cy, sy = math.cos(yaw), math.sin(yaw)
        cp, sp = math.cos(pitch), math.sin(pitch)
        ex = (cy, 0.0, -sy)
        ey = (-sy * sp, cp, -cy * sp)
        ez = (sy * cp, sp, cy * cp)
        if roll:
            cr, sr = math.cos(roll), math.sin(roll)
            sn = -sr
            exn = (ex[0] * cr + ey[0] * sn, ex[1] * cr + ey[1] * sn,
                   ex[2] * cr + ey[2] * sn)
            eyn = (ey[0] * cr - ex[0] * sn, ey[1] * cr - ex[1] * sn,
                   ey[2] * cr - ex[2] * sn)
            ex, ey = exn, eyn
        if cam.parent is None:
            return ex, ey, ez
        R3 = np.asarray(object_world_rotation(cam.parent))[:3, :3]
        return (tuple(float(v) for v in np.array(ex) @ R3),
                tuple(float(v) for v in np.array(ey) @ R3),
                tuple(float(v) for v in np.array(ez) @ R3))

    def apply_camera(self, cam):
        """把某摄像机设为玩家视角 — 与 loom_camera.apply_camera 逐位一致:
        世界位置 = 相机世界位置, 世界朝向 = yaw/pitch/roll (度->弧度),
        视角广度 = 相机 fov, 并关闭轨道相机 (自由相机语义). 返回是否成功."""
        if cam is None:
            return False
        self.camera = self.camera_world_position(cam)
        if cam.parent is None:
            self.camera_yaw = math.radians(cam.yaw)
            self.camera_pitch = math.radians(cam.pitch)
            self.camera_roll = math.radians(cam.roll)
        else:
            ex, ey, ez = self.camera_world_basis(cam)
            self.camera_yaw, self.camera_pitch, self.camera_roll =                 view_basis_to_angles(ex, ey, ez)
        self.fov = math.radians(cam.fov)
        self.orbit_mode = False
        return True

    def _refresh_player_camera(self):
        """挂父激活相机每帧重应用 (位姿随父移动) — 与 loom_render.render 帧首
        那个 apply_camera 分支同语义; 根相机 / 无激活相机不做任何事."""
        cam = self.active_camera_object()
        if cam is not None and cam.parent is not None:
            self.apply_camera(cam)

    def player_pitch_limits(self):
        """激活相机的俯仰角限制 (弧度) — 与 loom_camera.player_pitch_limits 同:
        无激活相机或未启用 pitch_lock -> None (脚本走自身默认钳位)."""
        cam = self.active_camera_object()
        if cam is None or not getattr(cam, 'pitch_lock', False):
            return None
        return (math.radians(cam.pitch_min), math.radians(cam.pitch_max))

    # ---- 相机 (脚本读写; 轨道相机与脚本视角分离) ----
    @property
    def camera_target(self):
        return self.target

    @camera_target.setter
    def camera_target(self, v):
        self.target = (float(v[0]), float(v[1]), float(v[2]))

    @property
    def camera_distance(self):
        return self.distance

    @camera_distance.setter
    def camera_distance(self, v):
        # 2026-11-06 R-03 修正 (复核 B 指出原实现制造新分叉):
        # 这里**不钳制**, 与 GL 的 camera_distance 属性语义逐位一致 —— 运行期
        # 写入 (滚轮/脚本) 两侧都原样接受; 钳制只发生在"数据入口"
        # (场景加载 clamp_camera_distance) 与 GL 滚轮的 UI 交互里。
        self.distance = float(v)

    def remove_model(self, m):
        """从模型列表移除 (count_touch 等脚本用; 引擎侧含 GPU 释放, 驱动无 GPU)."""
        if m in self.models:
            self.models.remove(m)
        # LOD 候选集合同步剪枝 (否则被删物体还会被 _update_lod 选模/算世界位置)
        try:
            self._lod_models.remove(m)
        except ValueError:
            pass


# 2026-10-18: _DriverUI 空壳已删除, 改用 loom_ui.UIManager (真数据模型, 无 GPU 依赖).
