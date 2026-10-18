# -*- coding: utf-8 -*-
"""smoke_ui_step3_image.py — Image 冒烟 (2026-10-18)"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..'))

from loom_ui import Image

PNG = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                   '..', '..', 'assets', '图像素材', 'camera.png')
assert os.path.exists(PNG), '测试图片不存在: ' + PNG


class _FakeTex:
    def __init__(self, size):
        self.size = size


class _Engine:
    def __init__(self):
        self.rect_calls = []
        self.tex_calls = []

    def draw_screen_rect(self, rect, color):
        self.rect_calls.append((rect, color))

    def draw_texture_quad(self, tex, rect, tint=(255, 255, 255, 255)):
        self.tex_calls.append((tex, rect, tint))

    def _surf_to_tex(self, surf):
        return _FakeTex(surf.get_size())


e = _Engine()

# 1) 无路径 -> 灰底占位
img = Image('i', rect=(0, 0, 100, 100), texture_path='')
img.draw(e, (0, 0, 100, 100))
assert len(e.rect_calls) == 1 and e.rect_calls[0][1] == (80, 80, 80, 255)
assert len(e.tex_calls) == 0
print('no path -> placeholder OK')

# 2) 无效路径 -> 也占位
img2 = Image('i2', rect=(0, 0, 100, 100), texture_path='nonexistent.png')
img2.draw(e, (0, 0, 100, 100))
assert len(e.rect_calls) == 2
assert len(e.tex_calls) == 0
print('invalid path -> placeholder OK')

# 3) 有效路径 stretch
img3 = Image('i3', rect=(10, 20, 50, 50), texture_path=PNG, fit='stretch')
img3.draw(e, (10, 20, 50, 50))
assert len(e.tex_calls) == 1
tex, r, tint = e.tex_calls[0]
assert r == (10, 20, 50, 50), r
assert tint == (255, 255, 255, 255), tint
tw, th = tex.size
print('stretch OK: img %dx%d -> rect %s' % (tw, th, r))

# 4) contain (等比装入)
img4 = Image('i4', rect=(0, 0, 200, 200), texture_path=PNG, fit='contain')
img4.draw(e, (0, 0, 200, 200))
tex4, r4, _ = e.tex_calls[1]
tx, ty, tw4, th4 = r4
# contain: 短边等于容器尺寸 (在长边的方向留空)
assert max(tw4, th4) <= 200 + 0.01
assert abs(max(tw4, th4) - 200) < 0.01
assert abs(tx + tw4 / 2 - 100) < 0.01
assert abs(ty + th4 / 2 - 100) < 0.01
print('contain OK: %s' % (r4,))

# 5) cover (等比填满)
img5 = Image('i5', rect=(0, 0, 200, 200), texture_path=PNG, fit='cover')
img5.draw(e, (0, 0, 200, 200))
tex5, r5, _ = e.tex_calls[2]
tx, ty, tw5, th5 = r5
assert min(tw5, th5) >= 200 - 0.01
assert abs(min(tw5, th5) - 200) < 0.01
print('cover OK: %s' % (r5,))

# 6) tint 支持
img6 = Image('i6', rect=(0, 0, 100, 100), texture_path=PNG,
             tint=(255, 100, 100, 200), fit='stretch')
img6.draw(e, (0, 0, 100, 100))
assert e.tex_calls[3][2] == (255, 100, 100, 200)
print('tint OK')

print('SMOKE_PASS')
