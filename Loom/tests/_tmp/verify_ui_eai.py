# -*- coding: utf-8 -*-
"""verify_ui_eai.py — 阶段5 EAI 命令全分支验收 (契约 §12)

覆盖 7 个命令 + 错误分支 + 撤销/重做：
  ui_canvas_add / ui_add / ui_set / ui_remove / ui_list / ui_reparent / ui_move_child
"""
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


def call(cmd, **kw):
    return ac._COMMANDS[cmd](w, kw)


# 1) ui_canvas_add（+ 撤销）
n = len(w.editor.ui.canvases)
r = call('ui_canvas_add', type='screen', width=1024, height=768)
assert r['total'] == n + 1
w.editor.undo.undo()
assert len(w.editor.ui.canvases) == n
print('ui_canvas_add + 撤销 OK')

# 2) ui_add 11 种类型（全类型覆盖 + 撤销）
for typ in ac._UI_TYPE_NAMES:
    n_undo = len(w.editor.undo.undo_stack)
    r = call('ui_add', type=typ)
    assert 'error' not in r, '%s: %r' % (typ, r)
    assert len(w.editor.undo.undo_stack) == n_undo + 1
print('ui_add 11 种类型 + 撤销 OK')

# 撤销全部 11 次
for _ in range(11):
    w.editor.undo.undo()
assert len(w.editor.ui.default_canvas().root.children) == 0
print('ui_add 批量撤销 OK')

# 3) ui_set 通用字段 + type-specific
call('ui_add', type='button', name='b1', text='x')
n_undo = len(w.editor.undo.undo_stack)
r = call('ui_set', name='b1', rect=(10, 20, 100, 40), text='修改后', font_size=20)
assert 'error' not in r
assert r['changed']['rect'] == [10, 20, 100, 40]
assert r['changed']['text'] == '修改后'
assert len(w.editor.undo.undo_stack) == n_undo + 1
w.editor.undo.undo()
btn = w.editor.ui.default_canvas().root.find('b1')
assert btn.text == 'x' and btn.rect == (0, 0, 120, 36)
print('ui_set 通用+type + 撤销 OK')

# 4) ui_set 无变化不压栈
n_undo = len(w.editor.undo.undo_stack)
r = call('ui_set', name='b1', text='x')
assert len(w.editor.undo.undo_stack) == n_undo
print('ui_set 无变化不压栈 OK')

# 5) ui_set 不存在元素
r = call('ui_set', name='nope', visible=False)
assert 'error' in r
print('ui_set 不存在 -> error OK')

# 6) ui_remove + 撤销
call('ui_add', type='panel', name='p1')
n_undo = len(w.editor.undo.undo_stack)
r = call('ui_remove', name='p1')
assert 'removed' in r
assert len(w.editor.undo.undo_stack) == n_undo + 1
w.editor.undo.undo()
assert w.editor.ui.default_canvas().root.find('p1') is not None
print('ui_remove + 撤销 OK')

# 7) ui_remove 不存在
r = call('ui_remove', name='nope')
assert 'error' in r
print('ui_remove 不存在 -> error OK')

# 8) ui_list 全/单个 canvas
r = call('ui_list')
assert r['total'] >= 1
r = call('ui_list', canvas=0)
assert len(r['canvases']) == 1
print('ui_list OK')

# 9) ui_reparent 有效 + 撤销
call('ui_add', type='panel', name='pa')
call('ui_add', type='panel', name='pb')
call('ui_add', type='button', name='b2', parent='pa')
n_undo = len(w.editor.undo.undo_stack)
r = call('ui_reparent', name='b2', new_parent='pb')
assert 'error' not in r
root = w.editor.ui.default_canvas().root
assert root.find('b2').parent is root.find('pb')
assert len(w.editor.undo.undo_stack) == n_undo + 1
w.editor.undo.undo()
assert root.find('b2').parent is root.find('pa')
print('ui_reparent + 撤销 OK')

# 10) ui_reparent 循环依赖拒绝
# 当前状态: b2 在 pa 里 (测试9撤销后), pa 在 root
# 把 pa 挂到 b2 下 -> pa -> b2 -> pa 成环 -> 应拒绝
r = call('ui_reparent', name='pa', new_parent='b2')
assert 'error' in r, '应拒绝循环依赖 (pa -> b2), 实际: %r' % r
print('ui_reparent 循环 -> error OK')

# 11) ui_reparent 同类父拒绝
r = call('ui_reparent', name='b2', new_parent='pa')
assert 'error' in r
print('ui_reparent 同类父 -> error OK')

# 12) ui_reparent 自身拒绝
r = call('ui_reparent', name='pa', new_parent='pa')
assert 'error' in r
print('ui_reparent 自身 -> error OK')

# 13) ui_move_child + 撤销
call('ui_add', type='panel', name='x1')
call('ui_add', type='panel', name='x2')
call('ui_add', type='panel', name='x3')
names_before = [c.name for c in root.children]
x1_idx = names_before.index('x1')
x3_idx = names_before.index('x3')
n_undo = len(w.editor.undo.undo_stack)
r = call('ui_move_child', name='x1', to_index=x3_idx)
assert 'error' not in r and r['moved'] is True
assert len(w.editor.undo.undo_stack) == n_undo + 1
w.editor.undo.undo()
assert [c.name for c in root.children] == names_before
print('ui_move_child + 撤销 OK')

# 14) ui_move_child 越界拒绝
r = call('ui_move_child', name='x1', to_index=999)
assert 'error' in r
print('ui_move_child 越界 -> error OK')

# 15) ui_move_child 同位置不压栈
n_undo = len(w.editor.undo.undo_stack)
r = call('ui_move_child', name='x1', to_index=x1_idx)
assert r.get('moved') is False
assert len(w.editor.undo.undo_stack) == n_undo
print('ui_move_child 同位置不压栈 OK')

print('PASS verify_ui_eai')
