# -*- coding: utf-8 -*-
"""smoke_ui_inputfield_sceneio.py — InputField 序列化往返 (2026-10-18)"""
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
        self.width = 800
        self.height = 600
        self.ui = loom_ui.UIManager()
        self.ui.add_canvas(loom_ui.Canvas(canvas_type='screen',
                                          width=800, height=600))


e1 = _Eng()
field = loom_ui.InputField(
    'f1', rect=(10, 10, 300, 32),
    text='已输入内容',
    placeholder='请输入...',
    max_length=50,
    bg_color=(30, 35, 45, 255),
    focus_bg_color=(40, 50, 70, 255),
    text_color=(220, 220, 220),
    placeholder_color=(120, 120, 130),
    cursor_color=(200, 200, 210),
    font_size=18,
    on_submit=lambda t: None,
    on_change=lambda t: None)
e1.ui.canvases[0].root.add_child(field)

d = sceneio.scene_to_dict(e1)
cd = d['ui']['canvases'][0]

def find(tree, name):
    if tree.get('name') == name:
        return tree
    for ch in (tree.get('children') or []):
        r = find(ch, name)
        if r:
            return r
    return None

f_d = find(cd['elements'][0], 'f1')
assert f_d is not None and f_d['type'] == 'input_field'
assert f_d['text'] == '已输入内容'
assert f_d['placeholder'] == '请输入...'
assert f_d['max_length'] == 50
assert f_d['bg_color'] == [30, 35, 45, 255]
assert f_d['focus_bg_color'] == [40, 50, 70, 255]
assert f_d['font_size'] == 18
assert 'on_submit' not in f_d, '回调不应序列化'
assert 'on_change' not in f_d, '回调不应序列化'
print('emit OK')

# 往返
e2 = _Eng()
sceneio._apply_ui(e2, d['ui'])
c2 = e2.ui.default_canvas()
f2 = c2.root.find('f1')
assert f2 is not None and f2.ctype == 'input_field'
assert f2.text == '已输入内容'
assert f2.placeholder == '请输入...'
assert f2.max_length == 50
assert f2.bg_color == (30, 35, 45, 255)
assert f2.font_size == 18
assert f2.on_submit is None, '回调恢复后应为 None'
assert f2.on_change is None
print('roundtrip OK')

# 回调可重新挂载
f2.on_submit = lambda t: None
assert callable(f2.on_submit)
print('callback reattach OK')

print('SMOKE_PASS')
