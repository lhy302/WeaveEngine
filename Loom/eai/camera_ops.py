# -*- coding: utf-8 -*-
"""eai.camera_ops — 相机命令

我负责：camera_add / camera_active / camera_move / camera_look / camera_proj /
camera_set / camera_preview。
我不负责：连贯操作（右键滑动视角等 GUI 老链路，按双链原则命令层不做）。
"""

from .commit import _apply_fields, _commit, _no_target, _resolve
from .helpers import as_bool, as_float, vec_set
from .inspector import cmd_inspect
from .registry import command
from .target import _find

# ---- 视角/移动 命令 = 结果注入 (2026-08-27 用户定原则) ----
# 连贯性操作 (右键滑动视角/中键平移/长按/拖拽) 一律不进命令行:
#   GUI 走老链路 (editor 事件处理, 直接向引擎发连贯操作);
#   命令层只暴露"一次性结果注入" (camera_move 绝对目标 / camera_look
#   绝对角度); Agent 需要连续观察时 = 多次注入结果命令串联 (频率自控),
#   或 GUI 内手动/老链路。camera_drive 等"模拟连贯驱动"命令已拆除
#   (2026-08-27), 避免两套逻辑改同一状态字段造成 GUI 滑动异常.
# 滑杆/拖条类: 只提供 set_* 结果注入命令 (检查器拖块本身不命令化).


@command('camera_add', '添加摄像机')
def cmd_camera_add(win, args):
    win.editor._add_camera()
    return {'ok': True}


@command('camera_active', '设为激活相机: {name} (缺省=取消激活)')
def cmd_camera_active(win, args):
    ed = win.editor
    name = args.get('name')
    if not name:
        ed.set_active_camera(None)
        return {'active': None}
    kind, obj, i = _find(ed, name)
    if obj is None:
        return {'error': '找不到相机: %s' % name}
    ed.set_active_camera(obj)
    return {'active': name}


@command('camera_move', '开发者轨道相机移动: {x,y,z} 绝对目标 或 {dx,dy,dz} 增量, 可选 {distance} '
                        '(2026-11-22 裁定②: 进撤销栈)')
def cmd_camera_move(win, args):
    """开发者轨道相机移动. 2026-11-22 (Q-B7-56-1 裁定②): 命令行移动**进撤销栈**
    —— 走 editor.set_orbit_view (与 camera_proj 的 set_camera_projection 同款:
    先快照后写入, 有变化才 push)。GUI 右键轨道/中键平移/滚轮/WASDQE 老链路不经
    本函数、不进栈 (连贯性操作豁免, 2026-08-27 原则不变)。"""
    ed = win.editor
    target = None
    if 'x' in args:
        target = (float(args['x']), float(args['y']), float(args['z']))
    elif 'dx' in args:
        t = ed.camera_target
        target = (t[0] + float(args['dx']),
                  t[1] + float(args['dy']),
                  t[2] + float(args['dz']))
    distance = float(args['distance']) if 'distance' in args else None
    setter = getattr(ed, 'set_orbit_view', None)
    if setter is not None:
        out = setter(target=target, distance=distance)
        return {'target': list(out['target']), 'distance': out['distance']}
    # 兼容没有 set_orbit_view 的旧桩/老编辑器 (与 cmd_camera_proj 兜底同款):
    # 直接写, 不进撤销 (真实 EditorApp 恒有该方法, 此路只为既有桩测试保命)。
    if target is not None:
        ed.camera_target = target
    if distance is not None:
        ed.camera_distance = distance
    return {'target': list(ed.camera_target), 'distance': ed.camera_distance}


@command('camera_proj', '投影模式: {ortho?:bool, size?, fov?(度)} '
                         '(正交时 size = 可见高度世界单位; 进场景脏判定与撤销)')
def cmd_camera_proj(win, args):
    """切换主相机投影。ortho=True 时用正交投影 (Unity 2D 同款)。

    2026-11-08 批4 (P-03-11 / 对齐第 2 批 D7=A): 投影是**场景相机属性**, 必须走
    ed.set_camera_projection() —— 它负责 sceneio 归一 + 进脏判定 + 进撤销栈。
    旧实现直接写 ed.ortho / ed.ortho_size, 绕过了撤销与归一（改了撤不回、坏值不钳制）。
    """
    ed = win.editor
    setter = getattr(ed, 'set_camera_projection', None)
    if setter is not None:
        setter(ortho=(as_bool(args.get('ortho'), False) if 'ortho' in args else None),
               ortho_size=(args.get('size') if 'size' in args else None),
               fov=(args.get('fov') if 'fov' in args else None))
    else:                                  # 兼容没有该方法的桩/老编辑器
        if 'ortho' in args:
            ed.ortho = as_bool(args.get('ortho'), False)
        if 'size' in args:
            ed.ortho_size = max(1.0, as_float(args.get('size'), 12.0))
    out = {'ortho': bool(getattr(ed, 'ortho', False)),
           'size': float(getattr(ed, 'ortho_size', 12.0))}
    try:
        import math as _m
        out['fov'] = round(_m.degrees(float(getattr(ed, '_fov'))), 6)
    except Exception:
        pass
    return out


@command('camera_look', '开发者相机视角: {yaw,pitch}(度) 绝对 或 {dyaw,dpitch}(度) 增量 '
                        '(2026-11-22 裁定②: 进撤销栈)')
def cmd_camera_look(win, args):
    """开发者相机视角. 2026-11-22 (Q-B7-56-1 裁定②): 命令行转视角**进撤销栈**
    —— 走 editor.set_orbit_view (与 camera_proj 同款快照/恢复语义)。GUI 右键
    轨道/方向键老链路不经本函数、不进栈 (连贯性操作豁免)。"""
    import math
    ed = win.editor
    yaw = pitch = None
    if 'yaw' in args:
        yaw = math.radians(float(args['yaw']))
    elif 'dyaw' in args:
        yaw = ed.camera_yaw + math.radians(float(args['dyaw']))
    if 'pitch' in args:
        pitch = math.radians(float(args['pitch']))
    elif 'dpitch' in args:
        pitch = ed.camera_pitch + math.radians(float(args['dpitch']))
    setter = getattr(ed, 'set_orbit_view', None)
    if setter is not None:
        out = setter(yaw=yaw, pitch=pitch)
        return {'yaw_deg': round(math.degrees(out['yaw']), 1),
                'pitch_deg': round(math.degrees(out['pitch']), 1)}
    # 兼容没有 set_orbit_view 的旧桩/老编辑器 (与 cmd_camera_proj 兜底同款)。
    if yaw is not None:
        ed.camera_yaw = yaw
    if pitch is not None:
        ed.camera_pitch = max(-1.55, min(1.55, pitch))
    return {'yaw_deg': round(math.degrees(ed.camera_yaw), 1),
            'pitch_deg': round(math.degrees(ed.camera_pitch), 1)}


@command('camera_set', '摄像机属性 (一步撤销): {name?, yaw,pitch,roll,fov,'
         'fov_lock,pitch_lock,pitch_min,pitch_max,x,y,z}')
def cmd_camera_set(win, args):
    ed = win.editor
    kind, c = _resolve(ed, args, ('camera',))
    if c is None:
        return _no_target(('camera',))
    spec = {'yaw': ('yaw', as_float), 'pitch': ('pitch', as_float),
            'roll': ('roll', as_float), 'fov': ('fov', as_float),
            'pitch_min': ('pitch_min', as_float),
            'pitch_max': ('pitch_max', as_float),
            'pitch_lock': ('pitch_lock', as_bool)}

    def apply():
        _apply_fields(args, c, spec)
        for key, axis in (('x', 'X'), ('y', 'Y'), ('z', 'Z')):
            if key in args:
                vec_set(c, 'position', axis, as_float(args[key]))
    _commit(ed, 'camera', c, "命令: 摄像机属性", apply)
    if 'fov_lock' in args:
        # fov_locked 语义: True = 锁定玩家调整 (GUI 走 toggle, 这里做成 set)
        if as_bool(args['fov_lock']) != bool(c.fov_locked):
            ed.toggle_cam_fov_locked(c)
    return cmd_inspect(win, {'name': c.name})


@command('camera_preview', '相机预览 (附身看): {name?} / {off=true} 退出预览')
def cmd_camera_preview(win, args):
    ed = win.editor
    if as_bool(args.get('off')):
        ed.exit_camera_preview()
        return {'preview': None}
    kind, c = _resolve(ed, args, ('camera',))
    if c is None:
        return _no_target(('camera',))
    ed.toggle_camera_preview(c)
    return {'preview': getattr(getattr(ed, 'preview_camera', None), 'name', None)}
