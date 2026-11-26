# -*- coding: utf-8 -*-
"""eai.animator_ops — 动画命令

我负责：animator。
我不负责：动画组件实现与关键帧数据（组件层）。
"""

from .commit import _no_target, _resolve
from .registry import command

@command('animator', '动画组件: {name?, action=add|remove|loop|play|clip|speed|seek|loop_mode, '
                         'clip?, value?, t?, mode?} (speed/loop_mode 可写可读; seek 只写)')
def cmd_animator(win, args):
    ed = win.editor
    kind, m = _resolve(ed, args, ('model',))
    if m is None:
        return _no_target(('model',))
    act = (args.get('action') or 'add').lower()
    if act == 'add':
        ed.add_animator(m)
    else:
        an = getattr(m, 'animator', None)
        if an is None:
            return {'error': '没有动画组件 (先 animator action=add)'}
        if act == 'remove':
            ed.remove_animator(m)
        elif act == 'loop':
            ed.toggle_anim_loop(m)
        elif act == 'play':
            ed.toggle_anim_playing(m)
        elif act == 'clip':
            name = args.get('clip')
            if not name:
                return {'error': 'clip 缺参数 (可用: %s)' % list(an.clips or [])}
            ed.play_anim(m, name)
        elif act == 'speed':
            # 读: 不传 value; 写: value=<数值> (beta6 C1: 可撤销, 写进场景)
            val = args.get('value', args.get('speed'))
            if val is not None:
                try:
                    ed.set_anim_speed(m, val)
                except ValueError as e:
                    return {'error': str(e)}
        elif act == 'seek':
            t = args.get('t', args.get('time'))
            if t is None:
                return {'error': 'seek 缺参数 t (秒)'}
            try:
                an.seek(t)
            except (TypeError, ValueError) as e:
                return {'error': 'seek 失败: %s' % (e,)}
        elif act == 'loop_mode':
            name = args.get('clip') or an.current
            if not name:
                return {'error': '没有当前片段 (给 clip 参数或先 action=clip)'}
            mode = args.get('mode')
            if mode is not None:
                try:
                    ed.set_anim_loop_mode(m, name, mode)
                except ValueError as e:
                    return {'error': str(e)}
        else:
            return {'error': 'action 只能 add|remove|loop|play|clip|speed|seek|loop_mode'}
    an = getattr(m, 'animator', None)
    if an is None:
        return {'name': m.name, 'action': act, 'animator': None}
    return {'name': m.name, 'action': act,
            'animator': {'loop': an.loop,
                         'playing': an.playing,
                         'current': an.current,
                         'time': an.time,
                         'speed': an.speed,
                         'loop_mode': an.effective_loop_mode(),
                         'clips': list(an.clips or []),
                         'clip_loop_modes': {k: c.loop_mode
                                             for k, c in an.clips.items()}}}
