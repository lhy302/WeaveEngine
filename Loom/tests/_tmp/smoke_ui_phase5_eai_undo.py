# -*- coding: utf-8 -*-
"""smoke_ui_phase5_eai_undo.py — 阶段5 EAI 命令撤销冒烟 (2026-10-18)"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..'))

import agent_commands as ac
import loom_ui
import undo as undo_mod


class _Ed:
    def __init__(self):
        self.ui = loom_ui.UIManager()
        self.ui.add_canvas(loom_ui.Canvas(
            canvas_type='screen', width=800, height=600))
        self.undo = undo_mod.UndoManager()


class _Win:
    def __init__(self):
        self.editor = _Ed()


w = _Win()


def call(cmd_name, **kwargs):
    fn = ac._COMMANDS.get(cmd_name)
    if fn is None:
        raise KeyError('命令不存在: %s' % cmd_name)
    return fn(w, kwargs)


# 1) ui_add 进撤销栈
n_undo = len(w.editor.undo.undo_stack)
r = call('ui_add', type='button', name='b1', text='OK')
assert 'error' not in r
assert len(w.editor.undo.undo_stack) == n_undo + 1, 'ui_add 未进撤销栈'
# 撤销 -> 元素应消失
w.editor.undo.undo()
assert w.editor.ui.default_canvas().root.find('b1') is None
# 重做 -> 元素回来
w.editor.undo.redo()
assert w.editor.ui.default_canvas().root.find('b1') is not None
print('ui_add 撤销/重做 OK')

# 2) ui_set 进撤销栈（push_no_do：不重复执行）
n_undo = len(w.editor.undo.undo_stack)
r = call('ui_set', name='b1', text='修改后')
assert r['changed']['text'] == '修改后'
assert len(w.editor.undo.undo_stack) == n_undo + 1, 'ui_set 未进撤销栈'
# 撤销 -> text 恢复原值
w.editor.undo.undo()
btn = w.editor.ui.default_canvas().root.find('b1')
assert btn.text == 'OK', btn.text
# 重做 -> 回到修改后
w.editor.undo.redo()
assert btn.text == '修改后'
print('ui_set 撤销/重做 OK')

# 3) ui_set 无实际变化时不进撤销栈
n_undo = len(w.editor.undo.undo_stack)
r = call('ui_set', name='b1', text='修改后')   # 同值
# 注意: 命令函数仍会调 setattr, 但 after==before 时不该 push
assert len(w.editor.undo.undo_stack) == n_undo, \
    'ui_set 无变化不应进撤销栈, 实际 %d->%d' % (n_undo, len(w.editor.undo.undo_stack))
print('ui_set 无变化不压栈 OK')

# 4) ui_remove 进撤销栈
n_undo = len(w.editor.undo.undo_stack)
r = call('ui_remove', name='b1')
assert 'removed' in r
assert len(w.editor.undo.undo_stack) == n_undo + 1, 'ui_remove 未进撤销栈'
assert w.editor.ui.default_canvas().root.find('b1') is None
w.editor.undo.undo()
btn = w.editor.ui.default_canvas().root.find('b1')
assert btn is not None, '撤销 ui_remove 后元素应恢复'
print('ui_remove 撤销 OK')

# 5) ui_canvas_add 进撤销栈
n_undo = len(w.editor.undo.undo_stack)
n_canvases = len(w.editor.ui.canvases)
r = call('ui_canvas_add', type='screen', width=1024, height=768)
assert len(w.editor.undo.undo_stack) == n_undo + 1
assert len(w.editor.ui.canvases) == n_canvases + 1
w.editor.undo.undo()
assert len(w.editor.ui.canvases) == n_canvases
print('ui_canvas_add 撤销 OK')

# 6) ui_reparent 进撤销栈
# 新建两个 panel 和一个 button
call('ui_add', type='panel', name='pa')
call('ui_add', type='panel', name='pb')
call('ui_add', type='button', name='b2', parent='pa')
root = w.editor.ui.default_canvas().root
pa = root.find('pa')
pb = root.find('pb')
b2 = root.find('b2')
assert b2.parent is pa
n_undo = len(w.editor.undo.undo_stack)
r = call('ui_reparent', name='b2', new_parent='pb')
assert 'error' not in r, r
assert b2.parent is pb
assert len(w.editor.undo.undo_stack) == n_undo + 1
w.editor.undo.undo()
assert b2.parent is pa, '撤销后应恢复到 pa'
w.editor.undo.redo()
assert b2.parent is pb
print('ui_reparent 撤销/重做 OK')

# 7) ui_reparent 循环依赖拒绝
# 真正的循环依赖场景: 把父元素挂到它自己的子孙下
# 当前: b2 在 pb 里 -> 把 pb 挂到 b2 下 (b2 是 pb 的子孙) -> 应拒绝
assert b2.parent is pb, '前置: b2 应在 pb 里'
r = call('ui_reparent', name='pb', new_parent='b2')
assert 'error' in r, '应拒绝循环依赖 (pb -> b2), 实际: %r' % r
# 再加一层: pb -> b2, 试把 pb 挂到 b2 (直接子 -> 应拒)
assert '循环' in r['error'] or '子孙' in r['error'], r
print('ui_reparent 循环依赖拒绝 OK')

# 8) ui_reparent 同类父拒绝
r = call('ui_reparent', name='b2', new_parent='pb')   # b2 已经在 pb 里
assert 'error' in r
print('ui_reparent 同类父拒绝 OK')

# 9) ui_move_child 进撤销栈
call('ui_add', type='panel', name='p1')
call('ui_add', type='panel', name='p2')
call('ui_add', type='panel', name='p3')
# p1 p2 p3 在 root 里现在顺序? 看 children
names_before = [ch.name for ch in root.children]
assert 'p1' in names_before and 'p2' in names_before and 'p3' in names_before
# 找 p1 当前 index
p1_idx = names_before.index('p1')
# 移到 index 2 位置（同级换序）
n_undo = len(w.editor.undo.undo_stack)
# to_index 是目标位置, 但不能超 len-1
# 目标: 把 p1 移到 p3 之后
target_idx = names_before.index('p3')
r = call('ui_move_child', name='p1', to_index=target_idx)
assert 'error' not in r, r
assert r['moved'] is True
assert len(w.editor.undo.undo_stack) == n_undo + 1
# 撤销
w.editor.undo.undo()
names_after = [ch.name for ch in root.children]
assert names_after == names_before, (names_after, names_before)
print('ui_move_child 撤销 OK')

# 10) ui_move_child 越界拒绝
r = call('ui_move_child', name='p1', to_index=999)
assert 'error' in r
print('ui_move_child 越界拒绝 OK')

# 11) ui_move_child 同类位置不变
r = call('ui_move_child', name='p1', to_index=p1_idx)
assert 'error' not in r
assert r['moved'] is False
print('ui_move_child 同位置 OK')

# 12) ui_set 不存在元素无撤销栈变化
n_undo = len(w.editor.undo.undo_stack)
r = call('ui_set', name='no_such_elem', visible=False)
assert 'error' in r
assert len(w.editor.undo.undo_stack) == n_undo
print('ui_set 不存在的元素不压栈 OK')

# 13) 桩环境（无 undo 字段）时不崩
class _EdNoUndo:
    def __init__(self):
        self.ui = loom_ui.UIManager()
        self.ui.add_canvas(loom_ui.Canvas(
            canvas_type='screen', width=800, height=600))


class _WinNoUndo:
    def __init__(self):
        self.editor = _EdNoUndo()


w_no = _WinNoUndo()
r = ac._COMMANDS['ui_add'](w_no, {'type': 'panel', 'name': 'nop'})
assert 'error' not in r
print('桩环境无 undo 时不崩 OK')

print('SMOKE_PASS')
