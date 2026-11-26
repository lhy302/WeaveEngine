# -*- coding: utf-8 -*-
"""eai.audio_ops — 音频命令

我负责：audio / set_audio_3d / get_audio_3d。
我不负责：音频系统实现（audio/ 包）。
"""

from .commit import _Ambiguous, _commit, _no_target, _resolve
from .helpers import as_float
from .registry import command

@command('audio', '音频源: {name?, action=add|remove|loop|play|clip|volume, clip?, value?}')
def cmd_audio(win, args):
    ed = win.editor
    kind, m = _resolve(ed, args, ('model',))
    if m is None:
        return _no_target(('model',))
    act = (args.get('action') or 'add').lower()
    if act == 'add':
        ed.add_audio_source(m)
    else:
        au = getattr(m, 'audio_source', None)
        if au is None:
            return {'error': '没有音频源 (先 audio action=add)'}
        if act == 'remove':
            ed.remove_audio_source(m)
        elif act == 'loop':
            ed.toggle_audio_loop(m)
        elif act == 'play':
            ed.toggle_audio_playing(m)
        elif act == 'clip':
            ed.set_audio_clip(m, args.get('clip') or '', au.clip)
        elif act == 'volume':
            v = max(0.0, min(1.0, as_float(args.get('value'), au.volume)))
            ed.commit_model(m, "命令: 音量", lambda: setattr(au, 'volume', v))
        else:
            return {'error': 'action 只能 add|remove|loop|play|clip|volume'}
    au = getattr(m, 'audio_source', None)
    return {'name': m.name, 'action': act,
            'audio': None if au is None else {'clip': au.clip, 'loop': au.loop,
                                              'playing': au.playing,
                                              'volume': au.volume}}


@command('set_audio_3d', '设置音频 3D 参数: {name?, category?, min_distance?, max_distance?, rolloff?}')
def cmd_set_audio_3d(win, args):
    ed = win.editor
    try:
        kind, obj = _resolve(ed, args, kinds=('model',))
    except _Ambiguous as e:
        return {'error': str(e)}
    if obj is None:
        return {'error': '找不到物体: %s (先 object_list 看全部)'
                % (args.get('name') or '(未选中)')}
    a = obj.audio_source
    if a is None:
        return {'error': '物体无 AudioSource 组件 (先 audio action=add)'}
    # 显式校验 (组件 setter 静默回退, 命令层必须把错误告诉调用方)
    updates = {}
    if 'category' in args:
        cat = str(args['category']).strip().lower()
        if cat not in ('music', 'sfx', 'voice'):
            return {'error': 'category 只能是 music/sfx/voice, 收到 %r'
                    % (args['category'],)}
        updates['category'] = cat
    for k in ('min_distance', 'max_distance', 'rolloff'):
        if k in args:
            try:
                v = float(args[k])
            except (TypeError, ValueError):
                return {'error': '%s 必须是数字, 收到 %r' % (k, args[k])}
            if v <= 0:
                return {'error': '%s 必须大于 0, 收到 %r' % (k, v)}
            updates[k] = v
    mn = updates.get('min_distance', a.min_distance)
    mx = updates.get('max_distance', a.max_distance)
    if mx <= mn:
        return {'error': 'max_distance (%r) 必须大于 min_distance (%r)' % (mx, mn)}
    if not updates:
        return {'category': a.category, 'min_distance': a.min_distance,
                'max_distance': a.max_distance, 'rolloff': a.rolloff}

    def _apply():
        for k, v in updates.items():
            setattr(a, k, v)

    _commit(ed, kind, obj, '设置音频 3D', _apply)
    return {'category': a.category, 'min_distance': a.min_distance,
            'max_distance': a.max_distance, 'rolloff': a.rolloff}


@command('get_audio_3d', '查询音频 3D 参数: {name?}')
def cmd_get_audio_3d(win, args):
    ed = win.editor
    try:
        kind, obj = _resolve(ed, args, kinds=('model',))
    except _Ambiguous as e:
        return {'error': str(e)}
    if obj is None:
        return {'error': '找不到物体: %s (先 object_list 看全部)'
                % (args.get('name') or '(未选中)')}
    a = obj.audio_source
    if a is None:
        return {'error': '物体无 AudioSource 组件'}
    return {'category': a.category, 'min_distance': a.min_distance,
            'max_distance': a.max_distance, 'rolloff': a.rolloff,
            'is_spatial': a.is_spatial()}
