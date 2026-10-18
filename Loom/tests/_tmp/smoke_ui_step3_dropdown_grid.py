# -*- coding: utf-8 -*-
"""smoke_ui_step3_dropdown_grid.py — Dropdown + GridLayout 冒烟 (2026-10-18)"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..'))

from loom_ui import (UIManager, Canvas, Button, Dropdown, GridLayout, Panel)
import sceneio


class _DrawEngine:
    def __init__(self):
        self.rects = []
        self.texts = []

    def draw_screen_rect(self, rect, color):
        self.rects.append(rect)

    def draw_text_quad(self, text, x, y, color=(255, 255, 255), size=None):
        self.texts.append(text)

    def _measure_text(self, text, size=None):
        return (len(text) * 10, 18)

    def push_scissor(self, rect):
        pass

    def pop_scissor(self):
        pass


def make_ui():
    m = UIManager()
    c = Canvas(canvas_type='screen', width=800, height=600)
    m.add_canvas(c)
    return m, c


# 1) Dropdown 展开 + 选中
m, c = make_ui()
changes = []
dd = Dropdown('dd', rect=(100, 100, 200, 32),
              options=['低', '中', '高'], selected_index=0,
              on_change=lambda v: changes.append(v))
c.root.add_child(dd)
assert dd._expanded is False
assert dd.selected_value == '低'
# 点击展开
consumed = m.dispatch_mouse((110, 110), {1}, set())
assert consumed is True
assert dd._expanded is True
print('expand OK')
# 点击第 3 项 (列表 y 从 132 开始, item_h=28; 第 3 项 y=132+2*28=188)
# 注意 dispatch_mouse 需要 pos 在展开列表位置
consumed = m.dispatch_mouse((110, 190), {1}, set())
assert consumed is True
assert dd._expanded is False
assert dd.selected_index == 2 and dd.selected_value == '高'
assert changes == ['高']
print('select item 3 OK')

# 2) Dropdown 二次绘制不崩
dd._expanded = True
e = _DrawEngine()
m.draw_all(e)
assert any('低' in t for t in e.texts), e.texts
assert any('高' in t for t in e.texts)
print('draw_all expanded OK')

# 3) GridLayout 自动 reflow
m, c = make_ui()
grid = GridLayout('grid', rect=(0, 0, 400, 300),
                  cell_size=(64, 64), spacing=(8, 8), columns=4)
c.root.add_child(grid)
for i in range(6):
    grid.add_child(Panel(f'cell{i}', rect=(0, 0, 10, 10)))
# 期望:
#   cell0: (0, 0, 64, 64)
#   cell1: (72, 0, 64, 64)
#   cell2: (144, 0, 64, 64)
#   cell3: (216, 0, 64, 64)
#   cell4: (0, 72, 64, 64) (第二行)
#   cell5: (72, 72, 64, 64)
assert grid.children[0].rect == (0, 0, 64, 64)
assert grid.children[1].rect == (72, 0, 64, 64)
assert grid.children[4].rect == (0, 72, 64, 64)
assert grid.children[5].rect == (72, 72, 64, 64)
assert grid.content_height() == 72 + 64   # 2行 + 间距 = 136
print('grid reflow OK, content_h=', grid.content_height())

# 4) 序列化往返 (Dropdown + GridLayout)
class _Eng:
    def __init__(self):
        self.models = []
        self.materials = []
        self.lights = []
        self.cameras = []
        self.active_camera = None
        self.gravity = -9.8
        self.width = 800
        self.height = 600
        self.ui = UIManager()
        self.ui.add_canvas(Canvas(canvas_type='screen', width=800, height=600))


e1 = _Eng()
e1.ui.canvases[0].root.add_child(Dropdown(
    'dd2', rect=(10, 10, 200, 32), options=['a', 'b', 'c'], selected_index=1))
e1.ui.canvases[0].root.add_child(GridLayout(
    'grid2', rect=(10, 100, 400, 300),
    cell_size=(50, 50), spacing=(10, 10), columns=3))
d = sceneio.scene_to_dict(e1)
cd = d['ui']['canvases'][0]
# 找 dd2 / grid2
def find_in_tree(tree, name):
    if tree.get('name') == name:
        return tree
    for ch in (tree.get('children') or []):
        r = find_in_tree(ch, name)
        if r:
            return r
    return None

dd_d = find_in_tree(cd['elements'][0], 'dd2')
assert dd_d is not None and dd_d['type'] == 'dropdown'
assert dd_d['options'] == ['a', 'b', 'c']
assert dd_d['selected_index'] == 1
grid_d = find_in_tree(cd['elements'][0], 'grid2')
assert grid_d is not None and grid_d['type'] == 'grid_layout'
assert grid_d['cell_size'] == [50, 50]
assert grid_d['spacing'] == [10, 10]
assert grid_d['columns'] == 3
print('emit OK')

# 往返
e2 = _Eng()
sceneio._apply_ui(e2, d['ui'])
c2 = e2.ui.default_canvas()
dd2 = c2.root.find('dd2')
assert dd2 is not None and dd2.ctype == 'dropdown'
assert dd2.options == ['a', 'b', 'c']
assert dd2.selected_index == 1
assert dd2.selected_value == 'b'
grid2 = c2.root.find('grid2')
assert grid2 is not None and grid2.ctype == 'grid_layout'
assert grid2.cell_w == 50 and grid2.cell_h == 50
assert grid2.columns == 3
print('roundtrip OK')

print('SMOKE_PASS')
