# -*- coding: utf-8 -*-
"""scene/io.py — **场景装配**（scene_to_dict / scene_from_dict，吃 prepare 的结果）+ 存盘/读盘。

B2 自 sceneio.py 按域拆出（除注明 2 处强制差异外函数体逐字一致）。

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
import base64
import json
import math
import os
import zlib

import scene.material as _sio_material
from scene.asset import (asset_context, asset_errors, asset_refs_kept,
                         record_asset_error, reset_asset_errors)
from scene.camera import (_apply_cameras, _b_strict, _emit_camera,
                          _link_camera_parents, norm_fov_deg, norm_ortho_size,
                          FOV_DEFAULT_DEG, ORTHO_SIZE_DEFAULT)
from scene.contract import (CURRENT_VERSION as SCENE_VERSION, ENGINE_VERSION,
                            prepare)
from scene.light import _apply_lights, _emit_light
from scene.material import (_apply_materials, _drop_orphan_default_materials,
                            _emit_material_refs)
from scene.object import (_apply_object, _apply_ui, _emit_subtree, _emit_ui,
                          _f1, _f3, _link_parents, _link_ui_targets,
                          _validate_model_graph, _validate_object_graph)
from scene.sky import _emit_skybox_checked, _scene_skybox_from_data




# ---------------- 场景 ----------------

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
    # Q-B1-3=A: 材质只写引用；真正保存（camera 非 None）时把未登记/被编辑的
    # 材质同步回资产库（digest 模式 camera=None 不写盘、不产生副作用）。
    _mats_out, _mats_migrated = _emit_material_refs(
        mats, ctx, engine, sync=(ctx is not None and camera is not None))
    try:
        engine._materials_migrated = _mats_migrated
    except Exception:
        pass
    if _mats_migrated and camera is not None:
        print('[资产] 本次保存已把 %d 个材质迁移到资产库（场景只写引用）'
              % (_mats_migrated,))
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
                    "materials": _mats_out,
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
    # B2 拆分注: 旧实现写本模块全局 _CUR_BASE_DIR；拆分后唯一真源在 scene/material.py
    # （唯一读者 _resolve_scene_rel），写方 = 本函数 + scene_driver.VK 装配路径，语义不变。
    _sio_material._CUR_BASE_DIR = base_dir          # 密闭夹具：无项目资产库时相对资源路径仍按场景目录解析
    # B7-16: 场景契约唯一入口（闸门 + 迁移）。**闸门在这里仍然生效**（prepare -> migrate
    # 第一步就是 gate），但"先校验、后清空"的顺序保证**不在本函数**：本函数被调用时，调用方
    # （editor.py:1245 / loom_model_gpu._load_scene_data / scene_driver.load_from_data /
    # agent_commands.py:549）已经在**任何状态变更之前**调过一次 prepare()，版本过高在那里
    # 就抛了，走不到这里。这里再调一次是幂等的（version 已是当前版本 -> 迁移分支全部跳过）；
    # 同时保证"直接调 scene_from_dict"的老调用点也一定经过闸门与迁移。
    # 注（2026-11-18 复查 P1-3 改正）：runtime.PlayerApp 初始化是**先建默认场景、后 prepare**
    # （runtime.py:114-115 清掉构造函数自建的默认模型，:148 才进本函数）—— 这是既有行为，
    # 清的是默认模型、不是用户当前场景，因此不违反 R5（R5 说的是"加载失败不许把用户当前
    # 场景清掉"）。旧注释写成"PlayerApp 已在清空旧场景之前调过 prepare"，与事实相反。
    data = prepare(data)
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
    _apply_ui(engine, data.get('ui'), base_dir)                # 2026-10-18: Canvas UI (清空重建)
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



# ============================================================================
# B7-16（2026-11-18）：migrate() **已搬去**场景契约模块（原 loom_scene_contract.py，B2 归位 scene/contract.py）
# ----------------------------------------------------------------------------
# 迁移是纯数据 -> 数据（只改 dict），所以它和版本号/闸门一起搬进契约模块，本文件只
# re-export（sceneio 门面 from scene.contract import ... migrate）。
# 想改迁移规则请改 scene.contract.migrate —— 这里**不要再写一份**（各端各写一份
# 正是 B7-17 的根因：VK 装配路径没经过迁移，v8 相机 yaw 停在 1.5707963）。
# ============================================================================


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
