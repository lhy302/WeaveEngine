# -*- coding: utf-8 -*-
"""eai.skybox_ops — 天空盒命令

我负责：skybox_set / skybox_clear / skybox_get 与描述前置 (_skybox_source /
_skybox_describe / _vk_skybox_info)。
我不负责：天空盒数据面与 VK 侧实现。
"""

import os
from .registry import command

# ---- 天空盒命令 (2026-10-19 C3 起; 2026-11-09 beta5 按人类裁决 Q4/Q5/Q6 重写) ----
# 白盒契约:
#   Q4=A 颜色只认 0..255 的整数（或整值浮点）—— 0-1 浮点**明确拒绝**并给原因，
#        绝不 int() 静默截断（旧实现 [0.2,0.4,0.8] -> int -> (0,0,0) 全黑）；
#   Q5=A 失败可见：返回 ok=False + error（不改状态），get 带 valid/reason；
#   Q6=A 六面图路径按**场景目录**存相对形式，缺文件直接报错。
def _skybox_source(cube):
    """Cubemap -> 'files' | 'solid' | None（get/set 共用）。"""
    if getattr(cube, 'paths', None):
        return 'files'
    if getattr(cube, '_solid_color', None):
        return 'solid'
    return None


def _skybox_describe(cube):
    """Cubemap -> 可序列化描述（含相对路径原样回写）。"""
    if cube is None:
        return None
    out = {'name': getattr(cube, 'name', None),
           'guid': getattr(cube, 'guid', None),
           'source': _skybox_source(cube)}
    paths = getattr(cube, '_source_paths', None) or getattr(cube, 'paths', None)
    if paths:
        out['paths'] = [str(p) for p in paths]
    solid = getattr(cube, '_solid_color', None)
    if solid:
        out['solid_color'] = [int(c) for c in solid]
    return out


@command('skybox_set',
         '设置场景级天空盒: {paths: [6 张图(必须在场景目录内)]} 或 '
         '{solid_color: "#RRGGBB"|[r,g,b,a]}, 可选 {name}。'
         '要黑天空用 solid_color=#000000；"清空"请用 skybox_clear（=恢复默认蓝天）')
def cmd_skybox_set(win, args):
    """设置**场景级**天空盒（相机级覆盖仍优先，见 camera_* 命令）。

    失败一律 {'ok': False, 'error': ...} 且**不改状态**（Q5=A）。
    """
    import sceneio
    ed = win.editor
    if getattr(ed, 'is_playing', False):
        # P2-2: 播放期改"场景级天空盒"会让场景真值在编辑态/播放态之间漂移
        # （退出播放要还原编辑态场景，播放期写进去的值无处安放）；与 _save_scene
        # "播放中不可保存"同一口径：拒绝并说明，而不是静默半生效。
        return {'ok': False,
                'error': '播放中不允许修改场景天空盒（请先停止播放，再设置）'}
    paths = args.get('paths')
    solid = args.get('solid_color')
    name = args.get('name')
    base_dir = ed._scene_dir() if hasattr(ed, '_scene_dir') else os.getcwd()
    if paths:
        if not isinstance(paths, (list, tuple)) or len(paths) != 6:
            return {'ok': False,
                    'error': 'paths 必须是 6 个路径的数组 (px,nx,py,ny,pz,nz)'}
        rel = []
        for i, p in enumerate(paths):
            q = str(p)
            ab = q if os.path.isabs(q) else os.path.join(base_dir, q)
            if not os.path.isfile(ab):
                return {'ok': False,
                        'error': '第 %d 面图片不存在: %s' % (i, os.path.abspath(ab))}
            try:
                rel.append(os.path.relpath(os.path.abspath(ab), base_dir))
            except Exception:
                rel.append(os.path.abspath(ab))     # 跨盘符无法 relpath -> 保绝对
        cube, valid, reason = sceneio.skybox_from_dict(
            {'paths': rel, 'name': name}, base_dir)
        if not valid:
            return {'ok': False, 'error': reason}
    elif solid is not None:
        rgba, reason = sceneio.parse_color(solid)
        if rgba is None:
            return {'ok': False, 'error': reason}
        cube, valid, reason = sceneio.skybox_from_dict(
            {'solid_color': list(rgba), 'name': name}, base_dir)
        if not valid:
            return {'ok': False, 'error': reason}
    else:
        return {'ok': False, 'error': '需要 paths 或 solid_color'}
    ed._scene_skybox = cube
    ed._skybox_valid = True
    ed._skybox_error = None
    # P1-1: 不再自己把 _skybox 置 None（那会让渲染面在接下来一直是 None）；
    # 由 _refresh_effective_skybox 负责"场景级写回 + 变更时 reset_sky_state"。
    eff = ed._refresh_effective_skybox() if hasattr(
        ed, '_refresh_effective_skybox') else cube
    return {'ok': True, 'name': cube.name, 'guid': cube.guid,
            'source': _skybox_source(cube),
            'skybox': _skybox_describe(cube),
            'effective': ('camera' if eff is not None and eff is not cube else 'scene')}


@command('skybox_clear',
         '恢复**默认蓝天盒**（不是"没有天空盒"; 要黑天空请 skybox_set solid_color=#000000）')
def cmd_skybox_clear(win, args):
    """A1 语义（人类裁决 2026-11-09）: **清空 = 恢复默认蓝天**.

    为什么不是"设成 None": 场景的缺省天空盒就是默认蓝（Q1=A），"清空"若等于 None，
    会与"场景没写 skybox 键"的语义打架（加载时又变回默认蓝 = 用户看到"清空没生效"）。
    所以这里显式恢复默认蓝：clear 之后编辑器/播放器都仍是蓝天，只是回到出厂值。
    想要黑天空：`skybox_set {"solid_color": "#000000"}`（用户显式选择，可持久化）。
    """
    import sceneio
    ed = win.editor
    if getattr(ed, 'is_playing', False):
        return {'ok': False,
                'error': '播放中不允许修改场景天空盒（请先停止播放，再恢复默认蓝天）'}
    cube = sceneio.default_skybox()
    ed._scene_skybox = cube
    ed._skybox_valid = True            # 回到出厂值 = 正常态, 不是解析失败
    ed._skybox_error = None
    # P1-1: refresh 负责"场景级写回 _skybox + 变更时 reset_sky_state"
    eff = ed._refresh_effective_skybox() if hasattr(
        ed, '_refresh_effective_skybox') else cube
    desc = _skybox_describe(eff or cube)
    return {'ok': True, 'reset_to_default': True,
            'skybox': _skybox_describe(cube),
            'effective': desc}


def _vk_skybox_info(win, ed):
    """Q5=A 在 VK 侧也成立: 取 VK 驱动（SceneDriver）的天空盒错误/生效值.

    编辑器进程通常没有 VK 驱动实例（VK 是独立进程）；宿主若挂了驱动句柄
    （测试桩 / 未来的 VK 预览），从 win.vk_driver|driver 或 ed._vk_driver|driver 取。
    无驱动 -> None（调用方据此判断"这一侧没有信息"，而不是假装成功）。
    """
    drv = None
    for holder, attrs in ((win, ('vk_driver', 'driver')),
                          (ed, ('_vk_driver', 'driver'))):
        if holder is None:
            continue
        for a in attrs:
            d = getattr(holder, a, None)
            if d is not None and callable(getattr(d, 'effective_skybox', None)):
                drv = d
                break
        if drv is not None:
            break
    if drv is None:
        return None
    eff = None
    try:
        eff = drv.effective_skybox()
    except Exception as e:
        print('[天空盒] VK 侧取生效天空盒失败: %r' % (e,))
    err = getattr(drv, '_skybox_error', None)
    return {'name': getattr(eff, 'name', None),
            'valid': bool(getattr(drv, '_skybox_valid', err is None)),
            'error': err,
            '_skybox_error': err,          # 与 scene_driver 字段同名，便于按名取用
            'has_skybox': eff is not None}


@command('skybox_get', '读天空盒信息（场景级 + 当前生效的那一个 + valid/reason + VK 侧错误）')
def cmd_skybox_get(win, args):
    """Q5=A: 场景里存了但解析不了时，valid=False + reason 能让调用方看出来。"""
    ed = win.editor
    scene_cube = getattr(ed, '_scene_skybox', None)
    eff = None
    try:
        eff = ed._effective_skybox()
    except Exception as e:
        print('[天空盒] 取生效天空盒失败: %r' % (e,))
    eff_src = None
    if eff is not None:
        try:
            cam = ed.active_camera_object()
        except Exception:
            cam = None
        eff_src = 'camera' if (cam is not None
                               and getattr(cam, 'skybox', None) is eff) else 'scene'
    desc = _skybox_describe(eff)
    if desc is not None:
        desc['source'] = eff_src
    # P2-1: 相机级天空盒的 valid/reason 也要能查（Q5=A 在相机级同样成立）；
    # 相机"没有"天空盒 = 正常态（valid=True，不伪造 reason）。
    try:
        _cam = ed.active_camera_object()
    except Exception as e:
        print('[天空盒] 取激活相机失败: %r' % (e,))
        _cam = None
    cam_info = None
    if _cam is not None:
        cam_info = {'name': getattr(_cam, 'name', None),
                    'guid': getattr(_cam, 'guid', None),
                    'has_skybox': getattr(_cam, 'skybox', None) is not None,
                    'valid': bool(getattr(_cam, '_skybox_valid', True)),
                    'reason': getattr(_cam, '_skybox_error', None)}
    scene_valid = bool(getattr(ed, '_skybox_valid',
                               getattr(ed, '_skybox_error', None) is None))
    scene_reason = getattr(ed, '_skybox_error', None)
    # 顶层 valid = 场景级正常 且 激活相机（若有）正常；失败原因优先给场景级，其次相机级
    cam_bad = cam_info is not None and cam_info['valid'] is False
    valid = scene_valid and not cam_bad
    reason = scene_reason
    if reason is None and cam_bad:
        reason = cam_info.get('reason') or '激活相机的天空盒解析失败'
    return {'skybox': _skybox_describe(scene_cube),
            'valid': valid,
            'reason': reason,
            'scene_valid': scene_valid,
            'scene_reason': scene_reason,
            'active_camera_skybox': cam_info,
            'effective': desc,
            # Q5=A: VK 侧天空盒失败也要能在查询里看见（无驱动时 None）
            'vk': _vk_skybox_info(win, ed)}
