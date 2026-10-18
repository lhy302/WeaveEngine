# -*- coding: utf-8 -*-
"""smoke_ui_step2_sceneio.py — 阶段2 交互元素序列化冒烟 (2026-10-18)"""
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
        self.ui.add_canvas(loom_ui.Canvas(canvas_type='screen',
                                          width=1280, height=800))


e = _Eng()
root = e.ui.canvases[0].root

# 建 4 种交互元素
btn = loom_ui.Button('btn', rect=(10, 10, 100, 40), text='开始',
                     font_size=18, on_click=lambda: None,
                     normal_color=(100, 50, 50, 255))
sl = loom_ui.Slider('sl', rect=(10, 60, 200, 24), min_value=0, max_value=100,
                    value=42, direction='h', on_change=lambda v: None)
tg = loom_ui.Toggle('tg', rect=(10, 90, 150, 24), is_on=True, label='全屏',
                    on_change=lambda v: None)
pb = loom_ui.ProgressBar('pb', rect=(10, 120, 200, 18), value=0.75)

for el in (btn, sl, tg, pb):
    root.add_child(el)

d = sceneio.scene_to_dict(e)
cd = d['ui']['canvases'][0]
root_d = cd['elements'][0]
kids = root_d['children']
assert len(kids) == 4, len(kids)

btn_d = [x for x in kids if x['name'] == 'btn'][0]
assert btn_d['type'] == 'button'
assert btn_d['text'] == '开始'
assert btn_d['font_size'] == 18
assert btn_d['normal_color'] == [100, 50, 50, 255]
assert 'on_click' not in btn_d, '事件回调不应序列化'

sl_d = [x for x in kids if x['name'] == 'sl'][0]
assert sl_d['type'] == 'slider'
assert sl_d['min_value'] == 0 and sl_d['max_value'] == 100
assert abs(sl_d['value'] - 42) < 0.01
assert sl_d['direction'] == 'h'
assert 'on_change' not in sl_d

tg_d = [x for x in kids if x['name'] == 'tg'][0]
assert tg_d['type'] == 'toggle'
assert tg_d['is_on'] is True
assert tg_d['label'] == '全屏'
assert 'on_change' not in tg_d

pb_d = [x for x in kids if x['name'] == 'pb'][0]
assert pb_d['type'] == 'progress_bar'
assert abs(pb_d['value'] - 0.75) < 0.01
print('emit OK')

# 往返
e2 = _Eng()
sceneio._apply_ui(e2, d['ui'])
c2 = e2.ui.default_canvas()
b2 = c2.root.find('btn')
assert b2 is not None and b2.ctype == 'button'
assert b2.text == '开始' and b2.font_size == 18
assert b2.normal_color == (100, 50, 50, 255)
assert b2.on_click is None, '回调恢复后应为 None'
s2 = c2.root.find('sl')
assert s2 is not None and s2.ctype == 'slider'
assert abs(s2.value - 42) < 0.01
assert s2.min_value == 0 and s2.max_value == 100
t2 = c2.root.find('tg')
assert t2 is not None and t2.is_on is True
assert t2.label == '全屏'
p2 = c2.root.find('pb')
assert p2 is not None and abs(p2.value - 0.75) < 0.01
print('roundtrip OK')

# 回调可以重新挂载 (运行时由脚本)
s2.on_change = lambda v: None
assert callable(s2.on_change)
print('callback reattach OK')
print('SMOKE_PASS')
