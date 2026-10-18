# -*- coding: utf-8 -*-
"""verify_ui_grid.py — GridLayout 自动排列坐标验收 (契约 §12, 阶段3)

验收点（契约原文）：GridLayout 自动排列坐标
测试范围：
  1) 单行 / 多行 / 部分满行的子元素坐标精确
  2) cell_size 与 spacing 生效
  3) add_child / remove_child 后自动 reflow
  4) content_height 计算
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..'))

from loom_ui import GridLayout, Panel


# 1) 单行 4 元素
g = GridLayout('g', rect=(0, 0, 400, 300),
               cell_size=(64, 64), spacing=(8, 8), columns=4)
for i in range(4):
    g.add_child(Panel(f'c{i}'))
assert g.children[0].rect == (0, 0, 64, 64)
assert g.children[1].rect == (72, 0, 64, 64)
assert g.children[2].rect == (144, 0, 64, 64)
assert g.children[3].rect == (216, 0, 64, 64)
print('single row OK')

# 2) 多行 / 部分满行 (6 元素, 4 列)
g = GridLayout('g', rect=(0, 0, 400, 300),
               cell_size=(64, 64), spacing=(8, 8), columns=4)
for i in range(6):
    g.add_child(Panel(f'c{i}'))
# 第 5 元素 (i=4) -> 第 2 行第 1 列: (0, 72, 64, 64)
assert g.children[4].rect == (0, 72, 64, 64), g.children[4].rect
assert g.children[5].rect == (72, 72, 64, 64)
print('multi row partial OK')

# 3) spacing / cell_size 不同值
g = GridLayout('g', rect=(0, 0, 400, 300),
               cell_size=(50, 40), spacing=(20, 10), columns=3)
for i in range(3):
    g.add_child(Panel(f'c{i}'))
assert g.children[0].rect == (0, 0, 50, 40)
assert g.children[1].rect == (70, 0, 50, 40)   # 50+20 = 70
assert g.children[2].rect == (140, 0, 50, 40)  # 50+70 = 140
g.add_child(Panel('c3'))
assert g.children[3].rect == (0, 50, 50, 40)   # 40+10 = 50
print('spacing / cell_size OK')

# 4) remove_child 后自动 reflow
g = GridLayout('g', rect=(0, 0, 400, 300),
               cell_size=(100, 100), spacing=(0, 0), columns=2)
for i in range(4):
    g.add_child(Panel(f'c{i}'))
# 初始: [(0,0),(100,0),(0,100),(100,100)]
assert g.children[2].rect == (0, 100, 100, 100)
# 删掉第 1 个 (i=0)，剩下的应重新排到 (0,0),(100,0),(0,100)
g.remove_child(g.children[0])
assert g.children[0].rect == (0, 0, 100, 100), g.children[0].rect
assert g.children[1].rect == (100, 0, 100, 100)
assert g.children[2].rect == (0, 100, 100, 100)
print('remove reflow OK')

# 5) content_height
g = GridLayout('g', rect=(0, 0, 400, 300),
               cell_size=(50, 50), spacing=(10, 10), columns=3)
# 空 -> 0
assert g.content_height() == 0
# 1 元素 -> 50 (单行, 无 spacing 累加)
g.add_child(Panel('a'))
assert g.content_height() == 50
# 3 元素 (满行) -> 50
g.add_child(Panel('b'))
g.add_child(Panel('c'))
assert g.content_height() == 50
# 4 元素 (2 行) -> 50*2 + 10 = 110
g.add_child(Panel('d'))
assert g.content_height() == 110
print('content_height OK')

print('PASS verify_ui_grid')
