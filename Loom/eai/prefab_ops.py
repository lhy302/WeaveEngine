# -*- coding: utf-8 -*-
"""eai.prefab_ops — 导入与 Prefab 命令

我负责：import_obj / prefab_save / prefab_place / prefab_unlink。
我不负责：资产库 guid 命令（asset_ops.py）与 .obj 解析（mesh 层）。
"""

import os
from .commit import _no_target, _resolve
from .registry import command
from .whitelist import _safe_write_path

@command('import_obj', '导入 .obj 模型: {path} (同工具栏[导入.obj], 免文件对话框)')
def cmd_import_obj(win, args):
    ed = win.editor
    path = args.get('path')
    if not path:
        return {'error': 'import_obj 需要 path (.obj 文件路径; 命令行无文件对话框)'}
    if not os.path.isfile(path):
        return {'error': '文件不存在: %s' % path}
    ed._import_obj(path)
    return {'imported': path,
            'model': getattr(ed._selected(), 'name', None),
            'count': len(ed.models)}


@command('prefab_save', 'Prefab 存模板: {path?} (缺省用工具栏 Prefab 名; 白名单外拒绝)')
def cmd_prefab_save(win, args):
    p = args.get('path')
    if p:
        ok, full = _safe_write_path(p, 'prefab_save', win)
        if not ok:
            return {'error': full}
        p = full
    win.editor._save_prefab(p)
    return {'saved': p or getattr(win.editor, 'prefab_name', None)}


@command('prefab_place', 'Prefab 放实例: {path?}')
def cmd_prefab_place(win, args):
    ed = win.editor
    ed._instantiate_prefab(args.get('path'))
    return {'placed': args.get('path') or getattr(ed, 'prefab_name', None),
            'count': len(ed.models)}


@command('prefab_unlink', '与 Prefab 断开连接: {name?}')
def cmd_prefab_unlink(win, args):
    ed = win.editor
    kind, m = _resolve(ed, args, ('model',))
    if m is None:
        return _no_target(('model',))
    ed.unlink_prefab(m)
    return {'name': m.name, 'prefab_ref': getattr(m, 'prefab_ref', None)}
