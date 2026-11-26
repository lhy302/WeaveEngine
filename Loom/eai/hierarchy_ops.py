# -*- coding: utf-8 -*-
"""eai.hierarchy_ops — 层级关系命令

我负责：reparent（挂父/脱父，物体与相机各自成链）。
我不负责：层级树 GUI 交互与撤销实现（editor/undo/cmd_object.py）。
"""

from .registry import command
from .target import _find

@command('reparent', '挂父/脱父: {child, parent?} (缺 parent = 脱父; 物体与相机各自成链)')
def cmd_reparent(win, args):
    ed = win.editor
    cname = args.get('child')
    if not cname:
        return {'error': '需要 child (物体名或相机名)'}
    kind, src, _i = _find(ed, cname)
    if src is None or kind == 'light':
        return {'error': '找不到可挂父的目标 (物体/相机): %s' % cname}
    pname = args.get('parent')
    if not pname:
        if getattr(src, 'parent', None) is None:
            return {'child': cname, 'parent': None, 'nochange': True}
        ed.detach(src) if kind == 'model' else ed.detach_camera(src)
        return {'child': cname, 'parent': None}
    kind2, dst, _j = _find(ed, pname)
    if dst is None:
        return {'error': '找不到父目标: %s' % pname}
    if dst is src:
        return {'error': '不能挂到自己身上'}
    if kind == 'model' and kind2 == 'model':
        # 与 GUI 拖拽同判据: 不许挂到自己的后代 (会成环)
        p = dst
        while p is not None:
            if p is src:
                return {'error': '不能挂到自己的子孙上 (会成环): %s' % pname}
            p = getattr(p, 'parent', None)
        ed.reparent(src, dst)
    elif kind == 'camera':
        ed.reparent_camera(src, dst)
    else:
        return {'error': '物体只能挂物体, 相机可挂物体/相机'}
    return {'child': cname, 'parent': pname}
