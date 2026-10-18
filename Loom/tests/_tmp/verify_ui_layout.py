# -*- coding: utf-8 -*-
"""verify_ui_layout.py — anchor/pivot 布局 (契约 §4.1, 阶段1)"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..'))

from loom_ui import UIElement

PARENT = (100.0, 50.0, 400.0, 300.0)

cases = [
    ((0, 0, 100, 40), (0, 0), (0, 0), (100.0, 50.0, 100.0, 40.0), '左上'),
    ((0, 0, 100, 40), (1, 1), (1, 1), (400.0, 310.0, 100.0, 40.0), '右下'),
    ((0, 0, 100, 40), (0.5, 0.5), (0.5, 0.5), (250.0, 180.0, 100.0, 40.0), '居中'),
    ((5, 7, 100, 40), (1, 0), (1, 0), (405.0, 57.0, 100.0, 40.0), '右上'),
    ((5, 7, 100, 40), (0, 1), (0, 1), (105.0, 317.0, 100.0, 40.0), '左下'),
]
for rect, anchor, pivot, expect, label in cases:
    e = UIElement('x', rect=rect, anchor=anchor, pivot=pivot)
    got = e.screen_rect(PARENT)
    for i in range(4):
        assert abs(got[i] - expect[i]) < 1e-6, (label, got, expect)

# 钳制
e = UIElement('c', rect=(0, 0, -10, -5))
assert e.rect[2] == 0.0 and e.rect[3] == 0.0
e.anchor = (5, -1)
assert e.anchor == (1.0, 0.0)
e.pivot = (-2, 3)
assert e.pivot == (0.0, 1.0)

# 嵌套: 子元素相对父元素计算
root = UIElement('r', rect=(0, 0, 400, 300))
p = UIElement('p', rect=(50, 50, 200, 100), anchor=(0, 0), pivot=(0, 0))
root.add_child(p)
ch = UIElement('c', rect=(10, 20, 50, 30), anchor=(0, 0), pivot=(0, 0))
p.add_child(ch)
rects = root.screen_rect_recursive((0, 0, 400, 300))
assert rects[id(p)] == (50.0, 50.0, 200.0, 100.0)
assert rects[id(ch)] == (60.0, 70.0, 50.0, 30.0)

print('PASS verify_ui_layout')
