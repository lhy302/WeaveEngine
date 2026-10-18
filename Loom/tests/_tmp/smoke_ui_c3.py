# -*- coding: utf-8 -*-
"""smoke_ui_c3.py — C3 淘汰 RuntimeUI 冒烟 (2026-10-18)"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..'))

import loom_ui
from loom_ui import UIManager, Canvas, Text, Panel


class _StubEngine:
    """最小 engine 桩, 只需 ui 属性."""
    def __init__(self):
        self.ui = UIManager()
        self.ui.add_canvas(Canvas(canvas_type='screen', width=1280, height=800))
        self.models = []
        self._count_hits = 0

    def get_collisions(self, obj):
        return []

    def remove_model(self, m):
        if m in self.models:
            self.models.remove(m)


# 1) default_canvas 拿到 Canvas
e = _StubEngine()
c = e.ui.default_canvas()
assert isinstance(c, Canvas), c
assert c.canvas_type == 'screen'
assert c.width == 1280 and c.height == 800
print('default_canvas OK')

# 2) 脚本建元素 (模拟 count_touch on_start)
hud = Text(name='_count_touch_hud', rect=(20, 20, 500, 30),
           text='碰到的彩球: 0', font_size=22)
c.root.add_child(hud)
assert hud in c.root.children
assert hud.text == '碰到的彩球: 0'
print('element added OK')

# 3) 模拟 update 改文本 (不重建元素)
hud.text = '碰到的彩球: 3  (剩余 7)'
assert hud.text == '碰到的彩球: 3  (剩余 7)'
assert hud in c.root.children
print('text update OK')

# 4) draw_all 走一遍 (无 GPU 时用桩 engine)
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

de = _DrawEngine()
e.ui.draw_all(de)
assert any('碰到的彩球' in t for t in de.texts), de.texts
print('draw_all OK:', de.texts)

# 5) resize 同步
e.ui.resize(1920, 1080)
assert c.width == 1920 and c.height == 1080
assert c.root.rect == (0, 0, 1920, 1080)
print('resize OK')

# 6) 多 Canvas + draw_all 按 z_order
c2 = Canvas(canvas_type='screen', width=1920, height=1080, z_order=10)
c2.root.add_child(Panel('overlay', rect=(0, 0, 1920, 1080),
                        bg_color=(0, 0, 0, 100)))
e.ui.add_canvas(c2)
de2 = _DrawEngine()
e.ui.draw_all(de2)
assert len(de2.rects) == 1 and len(de2.texts) == 1
print('multi-canvas draw_all OK')

# 7) scene_driver 的 ui 是 UIManager
import scene_driver
assert hasattr(scene_driver, 'UIManager')
assert not hasattr(scene_driver, '_DriverUI'), '_DriverUI 应已删除'
print('scene_driver OK')

print('SMOKE_PASS')
