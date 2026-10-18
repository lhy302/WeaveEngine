# -*- coding: utf-8 -*-
"""verify_ui_sceneio.py — UI 序列化往返 (契约 §8, 阶段1)"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..'))

import sceneio
import loom_ui


class _Eng:
    def __init__(self):
        self.models = []
        self.materials = []
        self.lights = []
        self.cameras = []
        self.active_camera = None
        self.gravity = -9.8
        self.width = 1280
        self.height = 800
        self.ui = loom_ui.UIManager()
        self.ui.add_canvas(loom_ui.Canvas(canvas_type='screen', width=1280, height=800))


# 建树
e = _Eng()
c = e.ui.canvases[0]
c.root.add_child(loom_ui.Panel('bg', rect=(0, 0, 1280, 800), bg_color=(20, 20, 40, 200)))
bg = c.root.find('bg')
bg.add_child(loom_ui.Text('title', rect=(100, 50, 400, 40),
                          text='标题 😀', font_size=32, color=(255, 220, 100),
                          align='center', wrap_width=350))
bg.add_child(loom_ui.Panel('btn', rect=(500, 300, 200, 60), bg_color=(80, 120, 200, 255)))

d = sceneio.scene_to_dict(e)
assert 'ui' in d
cd = d['ui']['canvases'][0]
assert cd['width'] == 1280 and cd['height'] == 800
root_d = cd['elements'][0]
bg_d = root_d['children'][0]
assert bg_d['name'] == 'bg'
title_d = [x for x in bg_d['children'] if x['name'] == 'title'][0]
assert title_d['text'] == '标题 😀'
assert title_d['font_size'] == 32
assert title_d['align'] == 'center'
assert title_d['wrap_width'] == 350

# 往返
e2 = _Eng()
sceneio._apply_ui(e2, d['ui'])
c2 = e2.ui.default_canvas()
bg2 = c2.root.find('bg')
assert bg2 is not None and bg2.bg_color == (20, 20, 40, 200)
title2 = c2.root.find('title')
assert title2 is not None
assert title2.text == '标题 😀'
assert title2.font_size == 32 and title2.align == 'center'
assert title2.wrap_width == 350
btn2 = c2.root.find('btn')
assert btn2 is not None and btn2.bg_color == (80, 120, 200, 255)

# 缺 ui 段 -> 默认 Canvas
e3 = _Eng()
sceneio._apply_ui(e3, None)
assert len(e3.ui.canvases) == 1
assert e3.ui.canvases[0].canvas_type == 'screen'

# 未知类型跳过
e4 = _Eng()
sceneio._apply_ui(e4, {'canvases': [{'canvas_type': 'screen',
                                     'width': 800, 'height': 600,
                                     'elements': [{'type': 'unknown', 'name': 'x'}]}]})
assert e4.ui.canvases[0].root.name == 'root'

print('PASS verify_ui_sceneio')
