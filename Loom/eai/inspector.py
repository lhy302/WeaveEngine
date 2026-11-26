# -*- coding: utf-8 -*-
"""eai.inspector — 检查器读回与通用写入命令

我负责：engine_metrics / inspect 读回，set_transform / set_visible /
set_saturation / set_color / set_normal_mode 通用写入。
我不负责：目标解析与提交前置（commit.py）、材质域写入（material_ops.py）。
"""

from .commit import _commit, _no_target, _resolve
from .helpers import as_bool, as_float, vec_set
from .registry import command

@command('engine_metrics', '引擎时钟只读指标: FPS/TPS/帧长std/逻辑暂停态/插值模式 '
                          '(方案一②观测面 + 分离功能自检, 无副作用)')
def cmd_engine_metrics(win, args):
    ed = win.editor
    out = {}
    for attr in ('fps', 'is_playing', '_logic_paused', '_logic_steps',
                 '_interp_mode', 'gravity'):
        out[attr.lstrip('_')] = getattr(ed, attr, None)
    for meth in ('get_tps', 'get_frame_jitter'):
        if hasattr(ed, meth):
            try:
                out[meth] = getattr(ed, meth)()
            except Exception as e:
                out[meth] = 'err:%r' % e
    clk = getattr(ed, '_clock', None)
    if clk is not None:
        out['clock'] = {'logic_fps': clk.logic_fps, 'alpha': round(clk.alpha, 4),
                        'steps': clk.steps, 'phys_steps': clk.phys_steps}
    # 2026-11-09 E1: **累计**体检面 —— clock.steps 是'上一次调用'的步数, 不是累计值,
    # 用它做差分会得到 0; 这里给可累计字段 + 时间账本 + 丢步/截断计数。
    try:
        _ratio = None
        if hasattr(ed, 'get_logic_time_ratio'):
            _ratio = ed.get_logic_time_ratio()
        out['logic_metrics'] = {
            'steps_total': getattr(ed, '_logic_steps_total', None),
            'calls_total': getattr(ed, '_logic_calls_total', None),
            'dt_sum': round(getattr(ed, '_logic_dt_sum', 0.0), 4),
            'wall_sum': round(getattr(ed, '_logic_wall_sum', 0.0), 4),
            'ratio': (None if _ratio is None else round(_ratio, 4)),
            'clock_steps_total': getattr(clk, 'steps_total', None),
            'clock_calls_total': getattr(clk, 'calls_total', None),
            'drop_events': getattr(clk, 'drop_events', None),
            'drop_time': round(getattr(clk, 'drop_time', 0.0), 4),
            'clamp_frames': getattr(clk, 'clamp_frames', None),
            'clamp_time': round(getattr(clk, 'clamp_time', 0.0), 4),
            'max_steps_per_frame': getattr(clk, 'max_steps_per_frame', None),
            'same_clock_as_clock_field': (clk is getattr(ed, '_clock', None)),
            'calls_by_thread': dict(getattr(ed, '_clock_calls_by_thread', {}) or {}),
            'max_gap_s': round(getattr(ed, '_clock_max_gap', 0.0), 4),
            'logic_async': bool(getattr(ed, '_logic_async', False)),
            'external_ctx': bool(getattr(ed, '_external_ctx', False)),
            'logic_thread_alive': bool(getattr(getattr(ed, '_logic_thread', None), 'is_alive', lambda: False)()),        }
    except Exception as e:
        out['logic_metrics'] = 'err:%r' % e
    # LOOM_PROFILE=1 时附阶段耗时快照 (编译版诊断用: exe 内存不可直读)
    st_t = getattr(ed, '_stage_times', None)
    if st_t:
        out['stage_times'] = dict(sorted(st_t.items(), key=lambda kv: -kv[1])[:40])
    # ★M3 (2026-09-09): 主线程分段归因快照 (帧数 + 逐段累计 ms + 调用数),
    #   供探针做 per-frame 归一化 (stage_times 本身是全程累计值, 不能直接当 ms/帧).
    if hasattr(ed, 'profile_snapshot'):
        try:
            out['mt_profile'] = ed.profile_snapshot()
        except Exception as e:
            out['mt_profile'] = 'err:%r' % e
    fb = getattr(ed, '_frame_buf', None)
    if fb is not None:
        out['frame_buffer'] = fb.metrics()
    rb = getattr(ed, '_render_buf', None)
    if rb is not None:
        out['render_buffer'] = rb.metrics()
    # 调度重构期1 (2026-09-07): NgilPool 观测面 (池计数/降级态)
    sp = getattr(ed, '_sched_pool', None)
    if sp is not None:
        try:
            out['sched_pool'] = sp.metrics_snapshot()
        except Exception:
            pass
    return out


@command('inspect', '读回目标完整状态: {name?} (Agent 自检/断言用, 无副作用)')
def cmd_inspect(win, args):
    ed = win.editor
    kind, obj = _resolve(ed, args)
    if obj is None:
        return _no_target(('model', 'light', 'camera'))
    out = {'kind': kind, 'name': obj.name}
    if kind == 'model':
        out.update({
            'position': list(obj.position), 'rotation': list(obj.rotation),
            'scale': list(obj.scale), 'visible': obj.visible,
            'saturation': getattr(obj, 'saturation', None),
            'parent': getattr(getattr(obj, 'parent', None), 'name', None),
            'prefab_ref': getattr(obj, 'prefab_ref', None),
            'material': getattr(getattr(getattr(obj, 'renderer', None),
                                        'material', None), 'name', None),
            'material_color': getattr(getattr(getattr(obj, 'renderer', None),
                                            'material', None), 'color', None),
            'collider': (None if getattr(obj, 'collider', None) is None
                         else {'enabled': obj.collider.enabled}),
            'rigidbody': (None if getattr(obj, 'rigidbody', None) is None
                          else {'use_gravity': obj.rigidbody.use_gravity,
                                'is_kinematic': obj.rigidbody.is_kinematic,
                                'mass': obj.rigidbody.mass,
                                'friction': obj.rigidbody.friction,
                                'restitution': obj.rigidbody.restitution,
                                'velocity': list(obj.rigidbody.velocity)}),
            'audio': (None if getattr(obj, 'audio_source', None) is None
                      else {'clip': obj.audio_source.clip,
                            'loop': obj.audio_source.loop,
                            'playing': obj.audio_source.playing,
                            'volume': obj.audio_source.volume}),
            'animator': (None if getattr(obj, 'animator', None) is None
                         else {'loop': obj.animator.loop,
                               'playing': obj.animator.playing,
                               'current': obj.animator.current,
                               # beta6 C1: 读取面补 time/speed/每片段循环模式
                               'time': obj.animator.time,
                               'speed': obj.animator.speed,
                               'clips': list(obj.animator.clips or []),
                               'clip_loop_modes': {k: c.loop_mode
                                                   for k, c in
                                                   obj.animator.clips.items()}}),
            'scripts': [{'id': s.script_id, 'vars': dict(s.script_vars)}
                        for s in getattr(obj, 'scripts', [])],
        })
    elif kind == 'light':
        out.update({'position': list(obj.position), 'kind_of': obj.kind,
                    'intensity': obj.intensity, 'color': list(obj.color),
                    'shadow': obj.shadow, 'mode': getattr(obj, 'mode', None),
                    'shape': getattr(obj, 'shape', None),
                    'size': getattr(obj, 'size', None),
                    'range': getattr(obj, 'range', None),
                    'azimuth': getattr(obj, 'azimuth', None),
                    'elevation': getattr(obj, 'elevation', None),
                    'roll': getattr(obj, 'roll', None)})
    else:
        out.update({'position': list(obj.position), 'yaw': obj.yaw,
                    'pitch': obj.pitch, 'roll': obj.roll, 'fov': obj.fov,
                    'fov_locked': obj.fov_locked, 'pitch_lock': obj.pitch_lock,
                    'pitch_min': obj.pitch_min, 'pitch_max': obj.pitch_max,
                    'parent': getattr(getattr(obj, 'parent', None), 'name', None),
                    'active': (getattr(ed, 'active_camera', None) == obj.guid)})
    return out


@command('set_transform', '物体变换 (一步撤销): {name?, x,y,z | rx,ry,rz(度) | sx,sy,sz}')
def cmd_set_transform(win, args):
    import math
    ed = win.editor
    kind, m = _resolve(ed, args, ('model',))
    if m is None:
        return _no_target(('model',))
    if not any(k in args for k in ('x', 'y', 'z', 'rx', 'ry', 'rz',
                                   'sx', 'sy', 'sz')):
        return {'error': '至少给一个字段: x/y/z (位置) rx/ry/rz (旋转度) sx/sy/sz (缩放)'}

    def apply():
        for key, axis in (('x', 'X'), ('y', 'Y'), ('z', 'Z')):
            if key in args:
                vec_set(m, 'position', axis, as_float(args[key]))
        for key, axis in (('rx', 'X'), ('ry', 'Y'), ('rz', 'Z')):
            if key in args:
                # 检查器旋转行是度制显示 / 引擎存弧度 (与 GUI 同一换算).
                # rotation 是 Point3D namedtuple: 必须整体重建 (vec_set),
                # setattr 会抛 AttributeError —— Qt 检查器就栽在这里.
                vec_set(m, 'rotation', axis, math.radians(as_float(args[key])))
        if any(k in args for k in ('sx', 'sy', 'sz')):
            cur = list(m.scale)
            for i, key in enumerate(('sx', 'sy', 'sz')):
                if key in args:
                    cur[i] = as_float(args[key], cur[i])
            m.set_scale(tuple(cur))
    _commit(ed, 'model', m, "命令: 变换", apply)
    return {'name': m.name, 'position': list(m.position),
            'rotation_deg': [round(math.degrees(v), 3) for v in m.rotation],
            'scale': list(m.scale)}


@command('set_visible', '显隐: {name?, on?} (缺 on = 切换, 同层级[显隐]按钮)')
def cmd_set_visible(win, args):
    ed = win.editor
    kind, m = _resolve(ed, args, ('model',))
    if m is None:
        return _no_target(('model',))
    want = None if args.get('on') is None else as_bool(args.get('on'))
    if want is None or want != bool(m.visible):
        ed.toggle_visible(m)        # GUI 同一入口 (自带撤销)
    return {'name': m.name, 'visible': bool(m.visible)}


@command('set_saturation', '饱和度: {name?, value 0..2}')
def cmd_set_saturation(win, args):
    ed = win.editor
    kind, m = _resolve(ed, args, ('model',))
    if m is None:
        return _no_target(('model',))
    v = max(0.0, min(2.0, as_float(args.get('value'), 1.0)))
    _commit(ed, 'model', m, "命令: 饱和度", lambda: setattr(m, 'saturation', v))
    return {'name': m.name, 'saturation': m.saturation}


@command('set_color', '改颜色: {name?, color=#RRGGBB} (材质单色覆盖)')
def cmd_set_color(win, args):
    ed = win.editor
    kind, m = _resolve(ed, args, ('model',))
    if m is None:
        return _no_target(('model',))
    color = args.get('color')
    if color is None:
        return {'error': '需要 color=#RRGGBB'}
    _commit(ed, 'model', m, "命令: 颜色",
            lambda: setattr(m, 'color', color if color else None))
    return {'name': m.name, 'color': m.color}


@command('set_normal_mode', '改法线模式: {name?, mode=flat|vertex}')
def cmd_set_normal_mode(win, args):
    ed = win.editor
    kind, m = _resolve(ed, args, ('model',))
    if m is None:
        return _no_target(('model',))
    mode = (args.get('mode') or '').lower()
    if mode not in ('flat', 'vertex'):
        return {'error': 'mode 只能 flat|vertex'}
    _commit(ed, 'model', m, "命令: 法线模式",
            lambda: setattr(m, 'normal_mode', mode))
    return {'name': m.name, 'normal_mode': m.normal_mode}
