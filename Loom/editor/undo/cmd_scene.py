# -*- coding: utf-8 -*-
"""
场景/UI 域撤销命令（原 Loom/undo.py「UI 撤销命令 (2026-10-18 阶段5)」段；
目录重构 B4 批按域拆分 —— Canvas/UI 树属于场景域，故落 cmd_scene，逐行未动）。

成员: ui_elem_snapshot / ui_apply_snapshot / _ui_add_at / _ui_detach /
UIStateCommand / UIAddCommand / UIRemoveCommand / UIReparentCommand /
UIMoveChildCommand / UIAddCanvasCommand。
"""
from editor.undo.registry import Command


# ---------------- UI 撤销命令 (2026-10-18 阶段5) ----------------
# 决策：UI 编辑全部进撤销栈（选项2 用户拍板），GUI 层所有操作走 EAI 命令（命令壳）。

def ui_elem_snapshot(elem):
    """UIElement 可撤销字段 -> dict（与 ui_apply_snapshot 成对）.

    只存"设计期"字段，不含运行时状态（_hover/_pressed/_focused/_cursor/_ime_*）。
    按 ctype 收集 type-specific 字段。
    """
    snap = {
        'ctype': elem.ctype,
        'name': elem.name,
        'rect': tuple(elem.rect),
        'anchor': tuple(elem.anchor),
        'pivot': tuple(elem.pivot),
        'visible': bool(elem.visible),
        'enabled': bool(elem.enabled),
        'z_order': int(elem.z_order),
    }
    typ = elem.ctype
    if typ == 'panel':
        snap['bg_color'] = tuple(elem.bg_color)
    elif typ == 'text':
        snap['text'] = elem.text
        snap['font_size'] = int(elem.font_size)
        snap['color'] = tuple(elem.color)
        snap['align'] = elem.align
        snap['wrap_width'] = int(elem.wrap_width)
    elif typ == 'image':
        snap['texture_path'] = elem.texture_path
        snap['tint'] = tuple(elem.tint)
        snap['fit'] = elem.fit
    elif typ == 'button':
        snap['text'] = elem.text
        snap['font_size'] = int(elem.font_size)
        snap['text_color'] = tuple(elem.text_color)
        snap['normal_color'] = tuple(elem.normal_color)
        snap['hover_color'] = tuple(elem.hover_color)
        snap['pressed_color'] = tuple(elem.pressed_color)
    elif typ == 'slider':
        snap['min_value'] = float(elem.min_value)
        snap['max_value'] = float(elem.max_value)
        snap['value'] = float(elem.value)
        snap['direction'] = elem.direction
        snap['track_color'] = tuple(elem.track_color)
        snap['fill_color'] = tuple(elem.fill_color)
        snap['handle_color'] = tuple(elem.handle_color)
    elif typ == 'toggle':
        snap['is_on'] = bool(elem.is_on)
        snap['label'] = elem.label
        snap['label_size'] = int(elem.label_size)
        snap['box_color'] = tuple(elem.box_color)
        snap['check_color'] = tuple(elem.check_color)
        snap['label_color'] = tuple(elem.label_color)
    elif typ == 'progress_bar':
        snap['value'] = float(elem.value)
        snap['bg_color'] = tuple(elem.bg_color)
        snap['fill_color'] = tuple(elem.fill_color)
    elif typ == 'scroll_view':
        snap['content_size'] = tuple(elem.content_size)
        snap['scroll_pos'] = tuple(elem.scroll_pos)
        snap['bg_color'] = tuple(elem.bg_color)
        snap['bar_color'] = tuple(elem.bar_color)
        snap['bar_width'] = int(elem.bar_width)
        snap['show_bar'] = bool(elem.show_bar)
        snap['scroll_step'] = int(elem.scroll_step)
    elif typ == 'input_field':
        snap['text'] = elem.text
        snap['placeholder'] = elem.placeholder
        snap['max_length'] = int(elem.max_length)
        snap['bg_color'] = tuple(elem.bg_color)
        snap['focus_bg_color'] = tuple(elem.focus_bg_color)
        snap['text_color'] = tuple(elem.text_color)
        snap['placeholder_color'] = tuple(elem.placeholder_color)
        snap['cursor_color'] = tuple(elem.cursor_color)
        snap['font_size'] = int(elem.font_size)
    elif typ == 'shape':
        # 2026-11-07 REGRESSION: ui_set 可改 Shape 字段, 快照/回写必须有 shape 分支
        snap['shape_type'] = str(getattr(elem, 'shape_type', 'line'))
        snap['points'] = [tuple(p) for p in (getattr(elem, 'points', []) or [])]
        snap['radius'] = float(getattr(elem, 'radius', 0.0))
        sc = getattr(elem, 'stroke_color', None)
        snap['stroke_color'] = tuple(sc) if sc else None
        snap['stroke_width'] = int(getattr(elem, 'stroke_width', 2))
        fc = getattr(elem, 'fill_color', None)
        snap['fill_color'] = tuple(fc) if fc else None
        snap['segments'] = int(getattr(elem, 'segments', 32))
        snap['close'] = bool(getattr(elem, 'close', False))
    elif typ == 'dropdown':
        snap['options'] = list(elem.options)
        snap['selected_index'] = int(elem.selected_index)
        snap['bg_color'] = tuple(elem.bg_color)
        snap['hover_color'] = tuple(elem.hover_color)
        snap['list_bg'] = tuple(elem.list_bg)
        snap['list_hover'] = tuple(elem.list_hover)
        snap['text_color'] = tuple(elem.text_color)
        snap['font_size'] = int(elem.font_size)
        snap['item_height'] = int(elem.item_height)
    elif typ == 'grid_layout':
        snap['cell_size'] = (float(elem.cell_w), float(elem.cell_h))
        snap['spacing'] = (float(elem.spacing_x), float(elem.spacing_y))
        snap['columns'] = int(elem.columns)
        snap['bg_color'] = tuple(elem.bg_color)
    return snap

def ui_apply_snapshot(elem, snap):
    """把快照写回 UIElement（undo/redo 共用）."""
    elem.name = snap['name']
    elem.rect = tuple(snap['rect'])
    elem.anchor = tuple(snap['anchor'])
    elem.pivot = tuple(snap['pivot'])
    elem.visible = snap['visible']
    elem.enabled = snap['enabled']
    elem.z_order = snap['z_order']
    typ = snap['ctype']
    if typ == 'panel':
        elem.bg_color = snap['bg_color']
    elif typ == 'text':
        elem.text = snap['text']
        elem.font_size = snap['font_size']
        elem.color = snap['color']
        elem.align = snap['align']
        elem.wrap_width = snap['wrap_width']
    elif typ == 'image':
        elem.texture_path = snap['texture_path']
        elem.tint = snap['tint']
        elem.fit = snap['fit']
        # 纹理缓存失效：下次 draw 重新加载
        if hasattr(elem, '_tex'):
            elem._tex = None
    elif typ == 'button':
        elem.text = snap['text']
        elem.font_size = snap['font_size']
        elem.text_color = snap['text_color']
        elem.normal_color = snap['normal_color']
        elem.hover_color = snap['hover_color']
        elem.pressed_color = snap['pressed_color']
    elif typ == 'slider':
        elem.min_value = snap['min_value']
        elem.max_value = snap['max_value']
        elem._value = snap['value']
        elem.direction = snap['direction']
        elem.track_color = snap['track_color']
        elem.fill_color = snap['fill_color']
        elem.handle_color = snap['handle_color']
    elif typ == 'toggle':
        elem.is_on = snap['is_on']
        elem.label = snap['label']
        elem.label_size = snap['label_size']
        elem.box_color = snap['box_color']
        elem.check_color = snap['check_color']
        elem.label_color = snap['label_color']
    elif typ == 'progress_bar':
        elem._value = snap['value']
        elem.bg_color = snap['bg_color']
        elem.fill_color = snap['fill_color']
    elif typ == 'scroll_view':
        elem._content_size = snap['content_size']
        elem.scroll_pos = snap['scroll_pos']
        elem.bg_color = snap['bg_color']
        elem.bar_color = snap['bar_color']
        elem.bar_width = snap['bar_width']
        elem.show_bar = snap['show_bar']
        elem.scroll_step = snap['scroll_step']
    elif typ == 'input_field':
        elem.text = snap['text']
        elem.placeholder = snap['placeholder']
        elem.max_length = snap['max_length']
        elem.bg_color = snap['bg_color']
        elem.focus_bg_color = snap['focus_bg_color']
        elem.text_color = snap['text_color']
        elem.placeholder_color = snap['placeholder_color']
        elem.cursor_color = snap['cursor_color']
        elem.font_size = snap['font_size']
        if hasattr(elem, '_cursor'):
            elem._cursor = min(elem._cursor, len(elem.text))
    elif typ == 'shape':
        elem.shape_type = snap['shape_type']
        elem.points = [tuple(p) for p in snap['points']]
        elem.radius = snap['radius']
        elem.stroke_color = snap['stroke_color']
        elem.stroke_width = snap['stroke_width']
        elem.fill_color = snap['fill_color']
        elem.segments = snap['segments']
        elem.close = snap['close']
    elif typ == 'dropdown':
        elem.options = list(snap['options'])
        elem.selected_index = snap['selected_index']
        elem.bg_color = snap['bg_color']
        elem.hover_color = snap['hover_color']
        elem.list_bg = snap['list_bg']
        elem.list_hover = snap['list_hover']
        elem.text_color = snap['text_color']
        elem.font_size = snap['font_size']
        elem.item_height = snap['item_height']
    elif typ == 'grid_layout':
        elem.cell_w, elem.cell_h = snap['cell_size']
        elem.spacing_x, elem.spacing_y = snap['spacing']
        elem.columns = snap['columns']
        elem.bg_color = snap['bg_color']
        if hasattr(elem, '_reflow'):
            elem._reflow()

def _ui_add_at(parent, child, index):
    """把 child 插入 parent.children 的 index 位置，并维护 parent 指针.

    不用 add_child（GridLayout 会覆盖 child.rect + 自动 reflow）；
    本函数用于"撤销恢复"等需要保留原始 rect 的场景。
    GridLayout 等容器若有 _reflow()，插入后手动触发。
    """
    child.parent = parent
    if index is None or index < 0 or index > len(parent.children):
        parent.children.append(child)
    else:
        parent.children.insert(index, child)
    if hasattr(parent, '_reflow'):
        try:
            parent._reflow()
        except Exception:
            pass

def _ui_detach(child):
    """从父节点摘除，返回原 index（无父返回 -1）."""
    p = child.parent
    if p is None:
        return -1
    try:
        idx = p.children.index(child)
    except ValueError:
        return -1
    p.children.pop(idx)
    child.parent = None
    if hasattr(p, '_reflow'):
        try:
            p._reflow()
        except Exception:
            pass
    return idx

class UIStateCommand(Command):
    """UI 元素属性修改（ui_set）: before/after 是 ui_elem_snapshot."""

    def __init__(self, label, engine, elem, before, after):
        self.label = label
        self.engine = engine
        self.elem = elem
        self.before = before
        self.after = after

    def do(self):
        ui_apply_snapshot(self.elem, self.after)

    def undo(self):
        ui_apply_snapshot(self.elem, self.before)

class UIAddCommand(Command):
    """添加 UI 元素（ui_add）. do() 插入 parent，undo() 摘除."""

    def __init__(self, label, engine, parent, child, index=None):
        self.label = label
        self.engine = engine
        self.parent = parent
        self.child = child
        self.index = index

    def do(self):
        _ui_add_at(self.parent, self.child, self.index)

    def undo(self):
        _ui_detach(self.child)

class UIRemoveCommand(Command):
    """删除 UI 元素（ui_remove）. do() 摘除，undo() 插回原位置."""

    def __init__(self, label, engine, elem):
        self.label = label
        self.engine = engine
        self.elem = elem
        self.parent = elem.parent
        self.index = -1
        if self.parent is not None:
            try:
                self.index = self.parent.children.index(elem)
            except ValueError:
                pass

    def do(self):
        _ui_detach(self.elem)

    def undo(self):
        if self.parent is not None:
            _ui_add_at(self.parent, self.elem, self.index)

class UIReparentCommand(Command):
    """UI 父子重排（ui_reparent）. 记录 old/new parent + old/new index."""

    def __init__(self, label, engine, elem, old_parent, old_index,
                 new_parent, new_index=None):
        self.label = label
        self.engine = engine
        self.elem = elem
        self.old_parent = old_parent
        self.old_index = old_index
        self.new_parent = new_parent
        self.new_index = new_index

    def do(self):
        _ui_detach(self.elem)
        _ui_add_at(self.new_parent, self.elem, self.new_index)

    def undo(self):
        _ui_detach(self.elem)
        _ui_add_at(self.old_parent, self.elem, self.old_index)

class UIMoveChildCommand(Command):
    """UI 同级顺序调整（ui_move_child）. 记录 old/new index."""

    def __init__(self, label, engine, elem, old_index, new_index):
        self.label = label
        self.engine = engine
        self.elem = elem
        self.parent = elem.parent
        self.old_index = old_index
        self.new_index = new_index

    def do(self):
        if self.parent is None:
            return
        try:
            cur = self.parent.children.index(self.elem)
        except ValueError:
            return
        self.parent.children.pop(cur)
        idx = max(0, min(self.new_index, len(self.parent.children)))
        self.parent.children.insert(idx, self.elem)
        if hasattr(self.parent, '_reflow'):
            try:
                self.parent._reflow()
            except Exception:
                pass

    def undo(self):
        if self.parent is None:
            return
        try:
            cur = self.parent.children.index(self.elem)
        except ValueError:
            return
        self.parent.children.pop(cur)
        idx = max(0, min(self.old_index, len(self.parent.children)))
        self.parent.children.insert(idx, self.elem)
        if hasattr(self.parent, '_reflow'):
            try:
                self.parent._reflow()
            except Exception:
                pass

class UIAddCanvasCommand(Command):
    """添加 Canvas（ui_canvas_add）. do() 追加到 ui.canvases，undo() 移除."""

    def __init__(self, label, engine, canvas, index=None):
        self.label = label
        self.engine = engine
        self.ui = getattr(engine, 'ui', None)
        self.canvas = canvas
        self.index = index

    def do(self):
        if self.ui is None:
            return
        if self.index is None or self.index < 0 or self.index > len(self.ui.canvases):
            self.ui.canvases.append(self.canvas)
        else:
            self.ui.canvases.insert(self.index, self.canvas)

    def undo(self):
        if self.ui is None:
            return
        try:
            self.ui.canvases.remove(self.canvas)
        except ValueError:
            pass
