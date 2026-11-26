# -*- coding: utf-8 -*-
"""eai.light_ops — 灯光命令

我负责：light_add / light_set。
我不负责：灯光渲染与阴影实现；相机命令。
"""

from .commit import _apply_fields, _commit, _no_target, _resolve
from .helpers import as_bool, as_float, vec_set
from .inspector import cmd_inspect
from .registry import command

@command('light_add', '添加光源: dir|point|spot（2026-10-19 加聚光灯）')
def cmd_light_add(win, args):
    win.editor._add_light(args.get('kind', 'dir'))
    return {'kind': args.get('kind', 'dir')}


@command('light_set', '光源属性 (一步撤销): {name?, intensity,r,g,b,azimuth,elevation,'
         'roll,size,range,shadow,mode(full|beam),shape(circle|rect),x,y,z}')
def cmd_light_set(win, args):
    ed = win.editor
    kind, l = _resolve(ed, args, ('light',))
    if l is None:
        return _no_target(('light',))
    spec = {'intensity': ('intensity', as_float),
            'azimuth': ('azimuth', as_float), 'elevation': ('elevation', as_float),
            'roll': ('roll', as_float), 'size': ('size', as_float),
            'range': ('range', as_float),
            'shadow': ('shadow', as_bool), 'mode': ('mode', str),
            'shape': ('shape', str)}
    for k in ('mode', 'shape'):
        if k in args and args[k] not in (('full', 'beam') if k == 'mode'
                                         else ('circle', 'rect')):
            return {'error': '%s 只能 %s' % (k, 'full|beam' if k == 'mode'
                                            else 'circle|rect')}

    def apply():
        _apply_fields(args, l, spec)
        if any(c in args for c in 'rgb'):
            col = list(l.color)
            for i, c in enumerate('rgb'):
                if c in args:
                    col[i] = max(0.0, min(1.0, as_float(args[c], col[i])))
            l.color = tuple(col)
        for key, axis in (('x', 'X'), ('y', 'Y'), ('z', 'Z')):
            if key in args:
                vec_set(l, 'position', axis, as_float(args[key]))
    _commit(ed, 'light', l, "命令: 光源属性", apply)
    return cmd_inspect(win, {'name': l.name})
