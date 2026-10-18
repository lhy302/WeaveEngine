# -*- coding: utf-8 -*-
"""verify_ui_panel_text_image.py — 三种基础元素绘制 (契约 §3.3, 阶段1)

只验证 draw() 调用不崩 + 绘制参数正确 (真实截图对比留档末).
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..'))

from loom_ui import Panel, Text, Image

PNG = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                   '..', '..', 'assets', '图像素材', 'camera.png')


class _FakeTex:
    def __init__(self, size):
        self.size = size


class _Engine:
    def __init__(self):
        self.rect_calls = []
        self.text_calls = []
        self.tex_calls = []

    def draw_screen_rect(self, rect, color):
        self.rect_calls.append((rect, color))

    def draw_text_quad(self, text, x, y, color=(255, 255, 255), size=None):
        self.text_calls.append((text, x, y, size))

    def draw_texture_quad(self, tex, rect, tint=(255, 255, 255, 255)):
        self.tex_calls.append((tex, rect, tint))

    def _measure_text(self, text, size=None):
        return (len(text) * 10, 18)

    def _surf_to_tex(self, surf):
        return _FakeTex(surf.get_size())


e = _Engine()

# Panel 四元组颜色
p = Panel('p', rect=(10, 10, 100, 50), bg_color=(255, 0, 0, 128))
p.draw(e, (10, 10, 100, 50))
assert e.rect_calls[0][1] == (255, 0, 0, 128)

# Text 三种对齐
e.text_calls.clear()
t = Text('t', rect=(0, 0, 200, 30), text='Hi', font_size=16)
t.draw(e, (5, 5, 200, 30))
assert e.text_calls[0][1] == 5
e.text_calls.clear()
t.align = 'center'
t.draw(e, (0, 0, 200, 30))
assert e.text_calls[0][1] == 90       # lw=20, (200-20)/2 = 90
e.text_calls.clear()
t.align = 'right'
t.draw(e, (0, 0, 200, 30))
assert e.text_calls[0][1] == 180

# Image: 无路径 -> 灰底; 有效路径 -> draw_texture_quad
e.rect_calls.clear(); e.tex_calls.clear()
i1 = Image('i1', rect=(0, 0, 100, 100), texture_path='')
i1.draw(e, (0, 0, 100, 100))
assert len(e.rect_calls) == 1 and e.rect_calls[0][1] == (80, 80, 80, 255)
assert len(e.tex_calls) == 0

assert os.path.exists(PNG), '测试图不存在: ' + PNG
e.rect_calls.clear(); e.tex_calls.clear()
i2 = Image('i2', rect=(10, 20, 50, 50), texture_path=PNG, fit='stretch')
i2.draw(e, (10, 20, 50, 50))
assert len(e.tex_calls) == 1
_, r, tint = e.tex_calls[0]
assert r == (10, 20, 50, 50)
assert tint == (255, 255, 255, 255)

print('PASS verify_ui_panel_text_image')
