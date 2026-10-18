# -*- coding: utf-8 -*-
"""smoke_ui_undo.py — UI 撤销命令冒烟 (2026-10-18)"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..'))

import undo
import loom_ui


class _Eng:
    def __init__(self):
        self.ui = loom_ui.UIManager()
        self.ui.add_canvas(loom_ui.Canvas(
            canvas_type='screen', width=800, height=600))
        self.undo = undo.UndoManager()


e = _Eng()
c = e.ui.default_canvas()
root = c.root


# 1) UIStateCommand: 改字段 -> 撤销 -> 重做
btn = loom_ui.Button('b1', rect=(0, 0, 100, 30), text='原文本')
root.add_child(btn)
before = undo.ui_elem_snapshot(btn)
btn.text = '新文本'
btn.font_size = 20
after = undo.ui_elem_snapshot(btn)

cmd = undo.UIStateCommand('改文本', e, btn, before, after)
e.undo.push(cmd)   # push 会调 do()，此时状态已是 after
assert btn.text == '新文本'
e.undo.undo()
assert btn.text == '原文本', btn.text
assert btn.font_size == 16, btn.font_size   # Button 默认 font_size=16
e.undo.redo()
assert btn.text == '新文本' and btn.font_size == 20
print('UIStateCommand do/undo/redo OK')

# 2) UIAddCommand: 加元素 -> 撤销 -> 重做
e2 = _Eng()
r2 = e2.ui.default_canvas().root
new_btn = loom_ui.Button('nb', rect=(50, 50, 80, 24))
cmd = undo.UIAddCommand('加按钮', e2, r2, new_btn)
e2.undo.push(cmd)
assert new_btn in r2.children and new_btn.parent is r2
e2.undo.undo()
assert new_btn not in r2.children and new_btn.parent is None
e2.undo.redo()
assert new_btn in r2.children and new_btn.parent is r2
print('UIAddCommand do/undo/redo OK')

# 3) UIRemoveCommand: 删元素 -> 撤销恢复
e3 = _Eng()
r3 = e3.ui.default_canvas().root
p1 = loom_ui.Panel('p1')
p2 = loom_ui.Panel('p2')
p3 = loom_ui.Panel('p3')
for p in (p1, p2, p3):
    r3.add_child(p)
# 删除中间的 p2
cmd = undo.UIRemoveCommand('删面板', e3, p2)
e3.undo.push(cmd)
assert p2 not in r3.children
assert [p.name for p in r3.children] == ['p1', 'p3']
e3.undo.undo()
assert p2 in r3.children
assert [p.name for p in r3.children] == ['p1', 'p2', 'p3'], [p.name for p in r3.children]
print('UIRemoveCommand do/undo OK')

# 4) UIReparentCommand: 换父
e4 = _Eng()
r4 = e4.ui.default_canvas().root
parent_a = loom_ui.Panel('A')
parent_b = loom_ui.Panel('B')
child = loom_ui.Button('c')
r4.add_child(parent_a)
r4.add_child(parent_b)
parent_a.add_child(child)
# 从 A 移到 B
cmd = undo.UIReparentCommand('挂父', e4, child, parent_a, 0, parent_b)
e4.undo.push(cmd)
assert child.parent is parent_b
assert child not in parent_a.children
e4.undo.undo()
assert child.parent is parent_a
assert child in parent_a.children
print('UIReparentCommand do/undo OK')

# 5) UIMoveChildCommand: 同级换序
e5 = _Eng()
r5 = e5.ui.default_canvas().root
items = [loom_ui.Panel('m%d' % i) for i in range(4)]
for it in items:
    r5.add_child(it)
# m0 从 index 0 移到 index 2
cmd = undo.UIMoveChildCommand('调序', e5, items[0], 0, 2)
e5.undo.push(cmd)
assert [p.name for p in r5.children] == ['m1', 'm2', 'm0', 'm3'],     [p.name for p in r5.children]
e5.undo.undo()
assert [p.name for p in r5.children] == ['m0', 'm1', 'm2', 'm3']
print('UIMoveChildCommand do/undo OK')

# 6) UIAddCanvasCommand: 加 Canvas
e6 = _Eng()
new_canvas = loom_ui.Canvas(canvas_type='screen', width=1024, height=768)
n_before = len(e6.ui.canvases)
cmd = undo.UIAddCanvasCommand('加 Canvas', e6, new_canvas)
e6.undo.push(cmd)
assert len(e6.ui.canvases) == n_before + 1
assert new_canvas in e6.ui.canvases
e6.undo.undo()
assert len(e6.ui.canvases) == n_before
e6.undo.redo()
assert len(e6.ui.canvases) == n_before + 1
print('UIAddCanvasCommand do/undo/redo OK')

# 7) GridLayout 有子元素时撤销 add：验证 reflow
e7 = _Eng()
r7 = e7.ui.default_canvas().root
grid = loom_ui.GridLayout('g', rect=(0, 0, 400, 300),
                          cell_size=(64, 64), spacing=(8, 8), columns=2)
r7.add_child(grid)
# 加 2 个
g1 = loom_ui.Panel('g1', rect=(100, 100, 10, 10))  # 故意给错 rect
g2 = loom_ui.Panel('g2', rect=(200, 200, 10, 10))
grid.add_child(g1)
grid.add_child(g2)
# g1, g2 应已被 reflow 到 (0,0) (72,0)
assert g1.rect == (0, 0, 64, 64), g1.rect
assert g2.rect == (72, 0, 64, 64), g2.rect
# 撤销加 g2
snapshot_before = undo.ui_elem_snapshot(g2)
cmd = undo.UIRemoveCommand('删 g2', e7, g2)
e7.undo.push(cmd)
assert g2 not in grid.children
e7.undo.undo()
# g2 应恢复（在 grid 里）
assert g2 in grid.children
# 位置由 reflow 决定
assert g2.rect == (72, 0, 64, 64), g2.rect
print('GridLayout reflow in undo OK')

print('SMOKE_PASS')
