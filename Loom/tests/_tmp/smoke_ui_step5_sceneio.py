# -*- coding: utf-8 -*-
"""smoke_ui_step5_sceneio.py — Canvas UI 序列化冒烟 (2026-10-18)"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..'))

import sceneio
import loom_ui


class _StubEngine:
    """最小 engine 桩: scene_to_dict/_apply_ui 只读 ui/width/height/models 等."""
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
        self.ui.add_canvas(loom_ui.Canvas(canvas_type='screen',
                                          width=1280, height=800))


# 1) 空 UIManager -> 空 canvases
e = _StubEngine()
d = sceneio.scene_to_dict(e)
assert 'ui' in d
assert len(d['ui']['canvases']) == 1
assert d['ui']['canvases'][0]['canvas_type'] == 'screen'
print('empty ui emit OK')

# 2) 建一棵有内容的 UI 树
c = e.ui.canvases[0]
root = c.root
root.add_child(loom_ui.Panel('bg', rect=(0, 0, 1280, 800),
                             bg_color=(20, 20, 40, 200)))
panel = root.find('bg')
panel.add_child(loom_ui.Text('title', rect=(100, 50, 400, 40),
                             text='游戏标题 😀',
                             font_size=32, color=(255, 220, 100),
                             align='center'))
panel.add_child(loom_ui.Panel('btn', rect=(500, 300, 200, 60),
                              bg_color=(80, 120, 200, 255)))

d2 = sceneio.scene_to_dict(e)
cd = d2['ui']['canvases'][0]
assert cd['width'] == 1280 and cd['height'] == 800
# root 是一层, 下面有 bg -> title/btn
root_d = cd['elements'][0]
assert root_d['type'] == 'element'  # 默认 UIElement 的 ctype
bg_d = root_d['children'][0]
assert bg_d['name'] == 'bg' and bg_d['type'] == 'panel'
assert bg_d['bg_color'] == [20, 20, 40, 200]
title_d = [x for x in bg_d['children'] if x['name'] == 'title'][0]
assert title_d['text'] == '游戏标题 😀'
assert title_d['font_size'] == 32
assert title_d['align'] == 'center'
btn_d = [x for x in bg_d['children'] if x['name'] == 'btn'][0]
assert btn_d['bg_color'] == [80, 120, 200, 255]
print('tree emit OK')

# 3) 往返
e2 = _StubEngine()
sceneio._apply_ui(e2, d2['ui'])
c2 = e2.ui.default_canvas()
bg2 = c2.root.find('bg')
assert bg2 is not None, 'bg 未恢复'
assert bg2.bg_color == (20, 20, 40, 200), bg2.bg_color
title2 = c2.root.find('title')
assert title2 is not None
assert title2.text == '游戏标题 😀', title2.text
assert title2.font_size == 32 and title2.align == 'center'
assert title2.color == (255, 220, 100), title2.color
btn2 = c2.root.find('btn')
assert btn2 is not None and btn2.bg_color == (80, 120, 200, 255)
print('roundtrip OK')

# 4) 旧场景缺 ui 段 -> 默认空 Canvas
e3 = _StubEngine()
sceneio._apply_ui(e3, None)
assert len(e3.ui.canvases) == 1
assert e3.ui.canvases[0].canvas_type == 'screen'
print('legacy (no ui) OK')

# 5) 未知类型 -> 跳过 + 警告
e4 = _StubEngine()
bad_ui = {'canvases': [{'canvas_type': 'screen', 'width': 800, 'height': 600,
                        'z_order': 0,
                        'elements': [{'type': 'unknown_widget', 'name': 'x',
                                      'rect': [0, 0, 10, 10]}]}]}
sceneio._apply_ui(e4, bad_ui)
# root 保持默认 (未知类型被跳过)
assert e4.ui.canvases[0].root.name == 'root'
print('unknown type skip OK')

# 6) 多 Canvas (screen + world 占位)
e5 = _StubEngine()
e5.ui.clear()
e5.ui.add_canvas(loom_ui.Canvas(canvas_type='screen', width=800, height=600, z_order=0))
e5.ui.add_canvas(loom_ui.Canvas(canvas_type='screen', width=800, height=600, z_order=10))
d5 = sceneio.scene_to_dict(e5)
assert len(d5['ui']['canvases']) == 2
assert [c['z_order'] for c in d5['ui']['canvases']] == [0, 10]
print('multi canvas emit OK')

print('SMOKE_PASS')
