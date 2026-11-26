# -*- coding: utf-8 -*-
"""eai.ui_element_ops — UI 元素命令

我负责：ui_add / ui_set / ui_remove / ui_list / ui_reparent / ui_move_child
与元素树前置（父元素解析/自动命名/序列化）。
我不负责：Canvas 级属性（ui_canvas_ops.py）与声明式事件（ui_event_ops.py）。
"""

from .helpers import (
    _COLOR_FIELDS, _coerce_color_args, _coerce_vec_args, as_bool,
    as_float, parse_color
)
from .registry import command
from .ui_common import _push_ui_undo, _ui_canvas

_UI_TYPE_NAMES = ('panel', 'text', 'image', 'button', 'slider', 'toggle',
                  'progress_bar', 'scroll_view', 'input_field', 'dropdown',
                  'grid_layout', 'shape')


def _ui_parent(win, args):
    """找父元素: args['parent'] 指定 name, 缺省 = canvas root. 返回 (canvas, parent)."""
    c = _ui_canvas(win, args)
    if c is None:
        return None, None
    pname = args.get('parent')
    if not pname:
        return c, c.root
    hit = c.root.find(pname)
    if hit is None:
        return c, None
    return c, hit


def _ui_auto_name(parent, typ):
    """自动生成唯一 name（{typ}_{n}，从 0 开始找未占用的）."""
    n = 0
    while True:
        name = '%s_%d' % (typ, n)
        if parent.find(name) is None:
            return name
        n += 1


def _ui_to_dict(elem):
    """UIElement -> dict（用于 ui_list）."""
    return {
        'type': elem.ctype,
        'name': elem.name,
        'rect': list(elem.rect),
        'anchor': list(elem.anchor),
        'pivot': list(elem.pivot),
        'visible': bool(elem.visible),
        'enabled': bool(elem.enabled),
        'z_order': int(elem.z_order),
        'children': [_ui_to_dict(ch) for ch in elem.children],
    }


@command('ui_add', '添加 UI 元素: {type, name?, parent?, canvas?, ...字段} '
                   '(type: panel|text|image|button|slider|toggle|progress_bar|'
                   'scroll_view|input_field|dropdown|grid_layout)')
def cmd_ui_add(win, args):
    typ = str(args.get('type', ''))
    if typ not in _UI_TYPE_NAMES:
        return {'error': 'type 必须是以下之一: %s, 收到 %r'
                         % (', '.join(_UI_TYPE_NAMES), typ)}
    # 2026-11-07 P0: 颜色字段先统一解析 (#RRGGBB / #RRGGBBAA / (r,g,b[,a]))。
    # 必须在建元素前做: 非法颜色直接拒绝, 不产生半成品元素 / 坏元组。
    try:
        args = _coerce_color_args(args, 'ui_add')
        # 2026-11-07 收尾: rect/anchor/pivot 同样不能裸 tuple() 收字符串
        args = _coerce_vec_args(args, 'ui_add')
    except ValueError as e:
        return {'error': str(e)}
    c, parent = _ui_parent(win, args)
    if c is None:
        return {'error': '找不到 Canvas（传 canvas= 序号, 先 ui_list 查看）'}
    if parent is None:
        return {'error': '找不到父元素: %r' % args.get('parent')}
    name = args.get('name') or _ui_auto_name(parent, typ)
    import loom_ui

    kw = {'name': name}
    if 'rect' in args:
        kw['rect'] = tuple(args['rect'])
    if 'anchor' in args:
        kw['anchor'] = tuple(args['anchor'])
    if 'pivot' in args:
        kw['pivot'] = tuple(args['pivot'])
    # 2026-11-07 P1: 布尔一律走 as_bool —— 控制台/HTTP 传的是字符串,
    # 裸 bool('false') == True, 会让 ui_add visible=false 反而显示出来。
    if 'visible' in args:
        kw['visible'] = as_bool(args['visible'], True)
    if 'enabled' in args:
        kw['enabled'] = as_bool(args['enabled'], True)
    if 'z_order' in args:
        kw['z_order'] = int(as_float(args['z_order'], 0))

    def take(key, conv=lambda v: v):
        if key in args:
            kw[key] = conv(args[key])

    if typ == 'panel':
        take('bg_color', tuple)
        elem = loom_ui.Panel(**kw)
    elif typ == 'text':
        take('text', str)
        take('font_size', lambda v: int(as_float(v, 16)))
        take('color', tuple)
        take('align', str)
        take('wrap_width', lambda v: int(as_float(v, 0)))
        elem = loom_ui.Text(**kw)
    elif typ == 'image':
        take('texture_path', str)
        take('tint', tuple)
        take('fit', str)
        elem = loom_ui.Image(**kw)
    elif typ == 'button':
        take('text', str)
        take('font_size', lambda v: int(as_float(v, 16)))
        take('text_color', tuple)
        take('normal_color', tuple)
        take('hover_color', tuple)
        take('pressed_color', tuple)
        elem = loom_ui.Button(**kw)
    elif typ == 'slider':
        take('min_value', float)
        take('max_value', float)
        take('value', float)
        take('direction', str)
        take('track_color', tuple)
        take('fill_color', tuple)
        take('handle_color', tuple)
        elem = loom_ui.Slider(**kw)
    elif typ == 'toggle':
        take('is_on', as_bool)
        take('label', str)
        take('label_size', lambda v: int(as_float(v, 16)))
        take('box_color', tuple)
        take('check_color', tuple)
        take('label_color', tuple)
        elem = loom_ui.Toggle(**kw)
    elif typ == 'progress_bar':
        take('value', float)
        take('bg_color', tuple)
        take('fill_color', tuple)
        elem = loom_ui.ProgressBar(**kw)
    elif typ == 'scroll_view':
        take('content_size', tuple)
        take('scroll_pos', tuple)
        take('bg_color', tuple)
        take('bar_color', tuple)
        take('bar_width', lambda v: int(as_float(v, 8)))
        take('show_bar', as_bool)
        take('scroll_step', lambda v: int(as_float(v, 30)))
        elem = loom_ui.ScrollView(**kw)
    elif typ == 'input_field':
        take('text', str)
        take('placeholder', str)
        take('max_length', lambda v: int(as_float(v, 200)))
        take('bg_color', tuple)
        take('focus_bg_color', tuple)
        take('text_color', tuple)
        take('placeholder_color', tuple)
        take('cursor_color', tuple)
        take('font_size', lambda v: int(as_float(v, 16)))
        elem = loom_ui.InputField(**kw)
    elif typ == 'dropdown':
        take('options', list)
        take('selected_index', lambda v: int(as_float(v, 0)))
        take('bg_color', tuple)
        take('hover_color', tuple)
        take('list_bg', tuple)
        take('list_hover', tuple)
        take('text_color', tuple)
        take('font_size', lambda v: int(as_float(v, 14)))
        take('item_height', lambda v: int(as_float(v, 28)))
        elem = loom_ui.Dropdown(**kw)
    elif typ == 'grid_layout':
        take('cell_size', tuple)
        take('spacing', tuple)
        take('columns', lambda v: int(as_float(v, 4)))
        take('bg_color', tuple)
        elem = loom_ui.GridLayout(**kw)
    elif typ == 'shape':
        # 2026-10-20 沙盘 2D 绘制（line/polyline/polygon/circle）
        take('shape_type', str)
        take('points', list)
        take('radius', float)
        take('stroke_color', parse_color)
        take('stroke_width', lambda v: max(1, int(as_float(v, 2))))
        take('fill_color', parse_color)
        take('segments', lambda v: max(8, int(as_float(v, 32))))
        take('close', as_bool)
        elem = loom_ui.Shape(**kw)
    else:
        return {'error': '内部错误: type %r 未实现' % typ}

    idx = len(parent.children)
    # 2026-10-18 阶段5: 撤销（决策选项2，UI 编辑全进撤销栈）
    import editor.undo as _undo_mod  # B4: undo.py -> editor/undo/ 包
    _push_ui_undo(win, _undo_mod.UIAddCommand('添加 UI 元素', win.editor,
                                              parent, elem, idx))
    return {'name': name, 'type': typ, 'parent': parent.name,
            'canvas': c.canvas_type, 'total': len(parent.children)}


@command('ui_set', '修改 UI 元素字段: {name, canvas?, ...字段} '
                   '(支持 rect/anchor/pivot/visible/enabled/z_order + type-specific)')
def cmd_ui_set(win, args):
    name = args.get('name')
    if not name:
        return {'error': '必须传 name=（先 ui_list 查看所有元素）'}
    c = _ui_canvas(win, args)
    if c is None:
        return {'error': '找不到 Canvas（传 canvas= 序号）'}
    elem = c.root.find(name)
    if elem is None:
        return {'error': '找不到 UI 元素: %r' % name}
    if elem is c.root:
        return {'error': '不能修改 Canvas root（用 ui_add / ui_set 改具体元素）'}

    # 2026-11-07 P0: 颜色字段与 ui_add 共用同一个解析入口。放在这里: 元素不存在
    # 之类的错误优先报出来, 且非法颜色在**任何字段被改动之前**就返回。
    try:
        args = _coerce_color_args(args, 'ui_set')
        args = _coerce_vec_args(args, 'ui_set')
    except ValueError as e:
        return {'error': str(e)}

    # 2026-10-18 阶段5: 改前快照（撤销用）
    import editor.undo as _undo_mod  # B4: undo.py -> editor/undo/ 包
    before = _undo_mod.ui_elem_snapshot(elem)

    done = {}
    if 'rect' in args:
        elem.rect = tuple(args['rect'])
        done['rect'] = list(elem.rect)
    if 'anchor' in args:
        elem.anchor = tuple(args['anchor'])
        done['anchor'] = list(elem.anchor)
    if 'pivot' in args:
        elem.pivot = tuple(args['pivot'])
        done['pivot'] = list(elem.pivot)
    # 2026-11-07 P1: as_bool (裸 bool('false') == True 会让 visible=false 变显示)
    if 'visible' in args:
        elem.visible = as_bool(args['visible'], elem.visible)
        done['visible'] = elem.visible
    if 'enabled' in args:
        elem.enabled = as_bool(args['enabled'], elem.enabled)
        done['enabled'] = elem.enabled
    if 'z_order' in args:
        elem.z_order = int(as_float(args['z_order'], 0))
        done['z_order'] = elem.z_order

    # 2026-10-20：parse_color / _COLOR_FIELDS 已提到模块级（cmd_ui_add 共用）
    def take(key, conv=lambda v: v):
        if key in args and hasattr(elem, key):
            try:
                # 颜色字段即使调用方传了 tuple 也强制走 parse_color（防字符数组 bug）
                c = parse_color if (key in _COLOR_FIELDS and conv is tuple) else conv
                setattr(elem, key, c(args[key]))
                done[key] = getattr(elem, key)
            except Exception as e:
                done[key] = 'error: %r' % e

    typ = elem.ctype
    if typ == 'panel':
        take('bg_color', tuple)
    elif typ == 'text':
        take('text', str)
        take('font_size', lambda v: int(as_float(v, 16)))
        take('color', tuple)
        take('align', str)
        take('wrap_width', lambda v: int(as_float(v, 0)))
    elif typ == 'image':
        take('texture_path', str)
        take('tint', tuple)
        take('fit', str)
    elif typ == 'button':
        take('text', str)
        take('font_size', lambda v: int(as_float(v, 16)))
        take('text_color', tuple)
        take('normal_color', tuple)
        take('hover_color', tuple)
        take('pressed_color', tuple)
    elif typ == 'slider':
        take('min_value', float)
        take('max_value', float)
        take('value', float)
        take('direction', str)
        take('track_color', tuple)
        take('fill_color', tuple)
        take('handle_color', tuple)
    elif typ == 'toggle':
        take('is_on', as_bool)
        take('label', str)
        take('label_size', lambda v: int(as_float(v, 16)))
        take('box_color', tuple)
        take('check_color', tuple)
        take('label_color', tuple)
    elif typ == 'progress_bar':
        take('value', float)
        take('bg_color', tuple)
        take('fill_color', tuple)
    elif typ == 'scroll_view':
        take('content_size', tuple)
        take('scroll_pos', tuple)
        take('bg_color', tuple)
        take('bar_color', tuple)
        take('bar_width', lambda v: int(as_float(v, 8)))
        take('show_bar', as_bool)
        take('scroll_step', lambda v: int(as_float(v, 30)))
    elif typ == 'input_field':
        take('text', str)
        take('placeholder', str)
        take('max_length', lambda v: int(as_float(v, 200)))
        take('bg_color', tuple)
        take('focus_bg_color', tuple)
        take('text_color', tuple)
        take('placeholder_color', tuple)
        take('cursor_color', tuple)
        take('font_size', lambda v: int(as_float(v, 16)))
    elif typ == 'dropdown':
        take('options', list)
        take('selected_index', lambda v: int(as_float(v, 0)))
        take('bg_color', tuple)
        take('hover_color', tuple)
        take('list_bg', tuple)
        take('list_hover', tuple)
        take('text_color', tuple)
        take('font_size', lambda v: int(as_float(v, 14)))
        take('item_height', lambda v: int(as_float(v, 28)))
    elif typ == 'grid_layout':
        take('cell_size', tuple)
        take('spacing', tuple)
        take('columns', lambda v: int(as_float(v, 4)))
        take('bg_color', tuple)
        if hasattr(elem, '_reflow'):
            try:
                elem._reflow()
            except Exception:
                pass
    elif typ == 'shape':
        # 2026-10-20 沙盘 2D 绘制字段
        take('shape_type', str)
        take('points', list)
        take('radius', float)
        take('stroke_color', parse_color)
        take('stroke_width', lambda v: max(1, int(as_float(v, 2))))
        take('fill_color', parse_color)
        take('segments', lambda v: max(8, int(as_float(v, 32))))
        take('close', as_bool)

    if not done:
        return {'error': '没有可改的字段（检查参数名）', 'type': typ}
    # 2026-10-18 阶段5: 撤销（仅当字段真的有变化时压栈）
    import editor.undo as _undo_mod  # B4: undo.py -> editor/undo/ 包
    after = _undo_mod.ui_elem_snapshot(elem)
    if after != before:
        _push_ui_undo(win, _undo_mod.UIStateCommand('修改 UI 属性',
                                                    win.editor, elem,
                                                    before, after), auto_do=False)
    return {'name': name, 'type': typ, 'changed': done}


@command('ui_remove', '删除 UI 元素: {name, canvas?}')
def cmd_ui_remove(win, args):
    name = args.get('name')
    if not name:
        return {'error': '必须传 name=（先 ui_list 查看所有元素）'}
    c = _ui_canvas(win, args)
    if c is None:
        return {'error': '找不到 Canvas（传 canvas= 序号）'}
    if name == c.root.name:
        return {'error': '不能删除 Canvas root（用其他方式清空）'}
    elem = c.root.find(name)
    if elem is None:
        return {'error': '找不到 UI 元素: %r' % name}
    parent = elem.parent
    if parent is None:
        return {'error': '元素没有父节点，无法删除'}
    # 2026-10-18 阶段5: 撤销
    import editor.undo as _undo_mod  # B4: undo.py -> editor/undo/ 包
    cmd = _undo_mod.UIRemoveCommand('删除 UI 元素', win.editor, elem)
    _push_ui_undo(win, cmd)
    return {'removed': name, 'parent': parent.name,
            'remaining': len(parent.children)}


@command('ui_list', '列出 UI 树: {canvas?} (缺省=全部 Canvas)')
def cmd_ui_list(win, args):
    ui = getattr(win.editor, 'ui', None)
    if ui is None:
        return {'error': '引擎没有 ui 字段'}
    only_canvas = args.get('canvas')
    out = []
    for i, c in enumerate(ui.canvases):
        if only_canvas is not None and int(as_float(only_canvas, -1)) != i:
            continue
        item = {
            'index': i,
            'canvas_type': c.canvas_type,
            'width': c.width,
            'height': c.height,
            'z_order': c.z_order,
            'root': _ui_to_dict(c.root),
        }
        if c.canvas_type == 'world':
            tgt = getattr(c, 'target', None)
            item['target'] = tgt.name if tgt is not None else None
            item['world_scale'] = float(getattr(c, 'world_scale', 0.01))
            item['billboard'] = bool(getattr(c, 'billboard', True))
        out.append(item)
    return {'canvases': out, 'total': len(ui.canvases)}


@command('ui_reparent', '移动 UI 元素到另一个父元素: {name, new_parent, canvas?, index?} '
                            '(new_parent 缺省 = Canvas root; 检查循环依赖)')
def cmd_ui_reparent(win, args):
    name = args.get('name')
    if not name:
        return {'error': '必须传 name=（先 ui_list 查看所有元素）'}
    c = _ui_canvas(win, args)
    if c is None:
        return {'error': '找不到 Canvas（传 canvas= 序号）'}
    elem = c.root.find(name)
    if elem is None:
        return {'error': '找不到 UI 元素: %r' % name}
    if elem is c.root:
        return {'error': '不能移动 Canvas root'}

    new_parent_name = args.get('new_parent')
    if new_parent_name:
        new_parent = c.root.find(new_parent_name)
        if new_parent is None:
            return {'error': '找不到新父元素: %r' % new_parent_name}
    else:
        new_parent = c.root

    if new_parent is elem:
        return {'error': '不能把元素挂到自己下面'}
    # 循环依赖检查: new_parent 不能是 elem 的子孙
    p = new_parent
    while p is not None:
        if p is elem:
            return {'error': '不能把元素挂到自己的子孙下面（会造成循环）'}
        p = p.parent

    old_parent = elem.parent
    if old_parent is None:
        return {'error': '元素没有父节点，无法移动'}
    if old_parent is new_parent:
        return {'error': '新旧父元素相同（如需调整同级顺序用 ui_move_child）'}
    try:
        old_idx = old_parent.children.index(elem)
    except ValueError:
        old_idx = -1

    new_idx = None
    if 'index' in args:
        ni = int(as_float(args['index'], -1))
        if ni >= 0:
            new_idx = ni

    import editor.undo as _undo_mod  # B4: undo.py -> editor/undo/ 包
    cmd = _undo_mod.UIReparentCommand('移动 UI 父节点', win.editor,
                                      elem, old_parent, old_idx,
                                      new_parent, new_idx)
    _push_ui_undo(win, cmd)
    return {'name': name, 'old_parent': old_parent.name,
            'new_parent': new_parent.name,
            'old_index': old_idx,
            'new_index': elem.parent.children.index(elem)
            if elem.parent is new_parent else -1}


@command('ui_move_child', '同一父元素内调整顺序: {name, to_index, canvas?}')
def cmd_ui_move_child(win, args):
    name = args.get('name')
    if not name:
        return {'error': '必须传 name=（先 ui_list 查看所有元素）'}
    c = _ui_canvas(win, args)
    if c is None:
        return {'error': '找不到 Canvas（传 canvas= 序号）'}
    elem = c.root.find(name)
    if elem is None:
        return {'error': '找不到 UI 元素: %r' % name}
    if elem is c.root:
        return {'error': '不能移动 Canvas root'}
    parent = elem.parent
    if parent is None:
        return {'error': '元素没有父节点，无法移动'}
    if 'to_index' not in args:
        return {'error': '必须传 to_index=（同级列表中的目标位置，0 起）'}
    try:
        cur_idx = parent.children.index(elem)
    except ValueError:
        return {'error': '元素不在父节点列表中'}
    to_idx = int(as_float(args['to_index'], -1))
    if to_idx < 0 or to_idx >= len(parent.children):
        return {'error': 'to_index 范围超限（0~%d），收到 %d'
                         % (len(parent.children) - 1, to_idx)}
    if to_idx == cur_idx:
        return {'name': name, 'moved': False, 'index': cur_idx,
                'message': '位置相同，未移动'}

    import editor.undo as _undo_mod  # B4: undo.py -> editor/undo/ 包
    cmd = _undo_mod.UIMoveChildCommand('调整 UI 顺序', win.editor,
                                       elem, cur_idx, to_idx)
    _push_ui_undo(win, cmd)
    return {'name': name, 'moved': True,
            'old_index': cur_idx, 'new_index': to_idx,
            'siblings': [ch.name for ch in parent.children]}
