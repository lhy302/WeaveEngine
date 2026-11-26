# -*- coding: utf-8 -*-
"""eai.physics_ops — 物理命令

我负责：collider / rigidbody / physics_simulate。
我不负责：物理求解器实现（physics/ 包）。
"""

from .commit import _no_target, _resolve
from .helpers import as_bool, as_float
from .registry import command

@command('collider', '碰撞器: {name?, on?} (裸 {name} 缺 on = 切换 enabled; '
                      '带 is_trigger/friction/restitution/rolling_friction 字段时 '
                      'enabled 不动, on 仍可显式设); '
                      '{name?, is_trigger?} 切/设触发器; '
                      '{name?, friction?/restitution?/rolling_friction?} 设接触材质'
                      ' (Q-B7-56-2 扩参数: GUI 检查器触发器按钮/摩擦数值行同一命令体)')
def cmd_collider(win, args):
    ed = win.editor
    kind, m = _resolve(ed, args, ('model',))
    if m is None:
        return _no_target(('model',))
    if getattr(m, 'collider', None) is None:
        return {'error': '该物体没有碰撞器组件'}
    # 接触材质 (B1): friction/restitution/rolling_friction 单设 (一步撤销)
    _col_fields = (('friction', 'friction'), ('restitution', 'restitution'),
                   ('rolling_friction', 'rolling_friction'))
    if any(k in args for k, _a in _col_fields):
        def _apply_contact():
            for k, a in _col_fields:
                if k in args:
                    setattr(m.collider, a, as_float(args[k]))
        ed.commit_model(m, "命令: 碰撞器接触材质", _apply_contact)
    # 触发器 (2026-10-18 档序17): is_trigger 传 bool = 设值, 传 None/缺省带键 = 切换
    if 'is_trigger' in args:
        want_t = None if args.get('is_trigger') is None \
            else as_bool(args.get('is_trigger'))
        if want_t is None or want_t != bool(getattr(m.collider, 'is_trigger', False)):
            ed.toggle_trigger(m)
    # 启用开关 (终审 F-67, 2026-11-22 agent-68): 裸 collider {name} 缺 on =
    # 切换 (既有语义不变, 门 F3 对照组 + test_eai_real 锁定); 携带组件字段
    # (is_trigger/friction/restitution/rolling_friction) 时只改给定字段,
    # enabled **不动** (on 仍可与字段同传显式设值) —— 命令语义自洽为
    # "改我给的那些": 本批 GUI 触发器按钮/接触材质行只传单字段, 旧
    # "缺 on 无条件切换"会把 enabled 静默翻转 (修前红留痕 F9 组).
    _has_comp_field = 'is_trigger' in args or any(k in args for k, _a
                                                  in _col_fields)
    if _has_comp_field:
        if args.get('on') is not None:
            want = as_bool(args.get('on'))
            if want != bool(m.collider.enabled):
                ed.toggle_collider(m)
    else:
        want = None if args.get('on') is None else as_bool(args.get('on'))
        if want is None or want != bool(m.collider.enabled):
            ed.toggle_collider(m)
    return {'name': m.name, 'enabled': bool(m.collider.enabled),
            'is_trigger': bool(getattr(m.collider, 'is_trigger', False)),
            'friction': getattr(m.collider, 'friction', None),
            'restitution': getattr(m.collider, 'restitution', None),
            'rolling_friction': getattr(m.collider, 'rolling_friction', None)}


@command('rigidbody', '刚体: {name?, action=add|remove|gravity|set} '
                      '(set 精设 mass/use_gravity/is_kinematic/friction/restitution/velocity)')
def cmd_rigidbody(win, args):
    ed = win.editor
    kind, m = _resolve(ed, args, ('model',))
    if m is None:
        return _no_target(('model',))
    act = (args.get('action') or 'add').lower()
    if act == 'add':
        ed.add_rigidbody(m)
    elif act == 'remove':
        ed.remove_rigidbody(m)
    elif act == 'gravity':
        if getattr(m, 'rigidbody', None) is None:
            return {'error': '没有刚体 (先 rigidbody action=add)'}
        ed.toggle_rigidbody_gravity(m)
    elif act == 'set':
        rb = getattr(m, 'rigidbody', None)
        if rb is None:
            return {'error': '没有刚体 (先 rigidbody action=add)'}

        def _apply():
            if 'mass' in args:
                rb.mass = as_float(args['mass'], rb.mass)
            if 'use_gravity' in args:
                rb.use_gravity = as_bool(args['use_gravity'], rb.use_gravity)
            if 'is_kinematic' in args:
                rb.is_kinematic = as_bool(args['is_kinematic'], rb.is_kinematic)
            if 'friction' in args:
                rb.friction = as_float(args['friction'], rb.friction)
            if 'restitution' in args:
                rb.restitution = as_float(args['restitution'], rb.restitution)
            if 'rolling_friction' in args:      # Q-B7-56-2: GUI 滚动摩擦行同一命令体
                rb.rolling_friction = as_float(args['rolling_friction'],
                                               rb.rolling_friction)
            if 'velocity' in args and args['velocity']:
                v = list(args['velocity'])
                if len(v) == 3:
                    rb.velocity = type(rb.velocity)(float(v[0]), float(v[1]),
                                                    float(v[2]))
        ed.commit_model(m, '命令: 刚体参数', _apply)
    else:
        return {'error': 'action 只能 add|remove|gravity|set, 收到 %s' % act}
    rb = getattr(m, 'rigidbody', None)
    return {'name': m.name, 'action': act,
            'rigidbody': None if rb is None else {
                'use_gravity': rb.use_gravity,
                'is_kinematic': rb.is_kinematic,
                'mass': rb.mass,
                'friction': rb.friction,
                'restitution': rb.restitution,
                'velocity': list(rb.velocity)}}


@command('physics_simulate', '确定性推进 N 个逻辑帧 (物理对拍, 需在播放态): {frames=整数}')
def cmd_physics_simulate(win, args):
    """物理对拍专用: 直接驱动逻辑时钟跑 N 帧 (每帧 = _logic_frame 完整链路:
    脚本→物理子步×N→音频→动画→prep), 不依赖真实墙钟 — 结果可复现.
    命令与渲染同在主线程串行, 执行期间渲染帧不会插队."""
    ed = win.editor
    if not getattr(ed, 'is_playing', False):
        return {'error': '未在播放态: 先 play on=true (物理仅播放期运行)'}
    frames = int(as_float(args.get('frames'), 0))
    if frames <= 0:
        return {'error': 'frames 需为正整数, 收到 %r' % args.get('frames')}
    clk = ed._ensure_split()
    if clk is None:
        return {'error': '逻辑时钟未启用 (分离未开/NO_SPLIT)'}
    # 冻结引擎自走的逻辑帧 (渲染帧照跑但零逻辑), 只让本命令手动步进 —
    # 否则渲染帧按真实墙钟并发推进, 与手动帧叠加, 物理对拍不可复现.
    # reset 清 accumulator 欠账: play 后到本调用之间渲染帧已积压若干帧,
    # 不清则 step_once 会一并补跑, 起点污染 (实测 frame=1 已含~3帧).
    was_paused = getattr(ed, '_logic_paused', False)
    try:
        ed._logic_paused = True
        clk.reset()
        for _ in range(frames):
            clk.step_once()
    finally:
        ed._logic_paused = was_paused
    return {'frames': frames, 'fixed_dt': clk.fixed_dt,
            'sub_steps': clk.sub_steps, 'sub_dt': clk.sub_dt}
