# -*- coding: utf-8 -*-
"""eai.ui_canvas_ops — UI Canvas 命令

我负责：ui_canvas_add / ui_canvas_set。
我不负责：Canvas 内元素的增删改（ui_element_ops.py）与事件绑定（ui_event_ops.py）。
"""

from .helpers import as_bool, as_float
from .registry import command
from .target import _find_model_by_name
from .ui_common import _push_ui_undo, _ui_canvas

# ================= 2026-10-18 阶段5: UI 编辑命令 =================


@command('ui_canvas_add', '添加 UI Canvas: {type?, width?, height?, z_order?, '
                          'target?, world_scale?, billboard?} '
                          '(type=screen|world, target=物体 name 仅 world 用)')
def cmd_ui_canvas_add(win, args):
    from loom_ui import Canvas
    ui = getattr(win.editor, 'ui', None)
    if ui is None:
        return {'error': '引擎没有 ui 字段'}
    typ = str(args.get('type', 'screen'))
    if typ not in ('screen', 'world'):
        return {'error': 'type 必须是 screen 或 world, 收到 %r' % typ}
    w = int(as_float(args.get('width', 800), 800))
    h = int(as_float(args.get('height', 600), 600))
    z = int(as_float(args.get('z_order', 0), 0))
    ws = as_float(args.get('world_scale', 0.01), 0.01)
    bb = as_bool(args.get('billboard', True), True)
    c = Canvas(canvas_type=typ, width=w, height=h, z_order=z,
               world_scale=ws, billboard=bb)
    if typ == 'world' and args.get('target'):
        tgt = _find_model_by_name(win.editor, str(args['target']))
        if tgt is None:
            return {'error': 'target 物体不存在: %r' % args['target']}
        c.target = tgt
    idx = len(ui.canvases)
    import editor.undo as _undo_mod  # B4: undo.py -> editor/undo/ 包
    cmd = _undo_mod.UIAddCanvasCommand('添加 Canvas', win.editor, c, idx)
    _push_ui_undo(win, cmd)
    out = {'canvas_type': typ, 'width': w, 'height': h, 'z_order': z,
           'total': len(ui.canvases)}
    if typ == 'world':
        out['world_scale'] = c.world_scale
        out['billboard'] = c.billboard
        out['target'] = c.target.name if c.target is not None else None
    return out


@command('ui_canvas_set', '修改 Canvas 属性: {canvas, width?, height?, z_order?, '
                          'type?, world_scale?, billboard?, target?} '
                          '(target="" 清空绑定)')
def cmd_ui_canvas_set(win, args):
    c = _ui_canvas(win, args)
    if c is None:
        return {'error': '找不到 Canvas（传 canvas= 序号）'}
    done = {}
    if 'width' in args:
        c.width = int(as_float(args['width'], c.width))
        c.root.rect = (0, 0, c.width, c.height)
        done['width'] = c.width
    if 'height' in args:
        c.height = int(as_float(args['height'], c.height))
        c.root.rect = (0, 0, c.width, c.height)
        done['height'] = c.height
    if 'z_order' in args:
        c.z_order = int(as_float(args['z_order'], c.z_order))
        done['z_order'] = c.z_order
    if 'type' in args:
        typ = str(args['type'])
        if typ not in ('screen', 'world'):
            return {'error': 'type 必须是 screen 或 world, 收到 %r' % typ}
        c.canvas_type = typ
        done['canvas_type'] = typ
    if 'world_scale' in args:
        c.world_scale = float(as_float(args['world_scale'],
                                       getattr(c, 'world_scale', 0.01)))
        done['world_scale'] = c.world_scale
    if 'billboard' in args:
        c.billboard = as_bool(args['billboard'], True)
        done['billboard'] = c.billboard
    if 'target' in args:
        tv = args['target']
        if tv is None or tv == '':
            c.target = None
            done['target'] = None
        else:
            tgt = _find_model_by_name(win.editor, str(tv))
            if tgt is None:
                return {'error': 'target 物体不存在: %r' % tv}
            c.target = tgt
            done['target'] = tgt.name
    return {'canvas_type': c.canvas_type, 'changed': done}
