# -*- coding: utf-8 -*-
"""smoke_layer_tag_step4.py — 第 4 步 sceneio 序列化冒烟 (2026-10-18)

纪律: 只验证「不崩 + 数据能往返」, 完整边界测试留到第 1 档档末。
绕开 test_sceneio.py 里硬编码的非法临时路径 (既有缺陷, 另行记录).
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..'))

import layer_tag
import sceneio
from engine import GLEngine
from loom_types import Point3D
from mesh import create_cube


from loom_game_object import GameObject


class _Stub:
    def __init__(self):
        self.models = []
        self.materials = []
        self.lights = []
        self.cameras = []
        self.gravity = -9.8
        self.scene_name = 't'

    def add_model(self, mesh, position, rotation, **kw):
        m = GameObject(mesh, tuple(position), tuple(rotation),
                       name=kw.get('name'), scale=kw.get('scale'),
                       visible=kw.get('visible', True),
                       normal_mode=kw.get('normal_mode', 'flat'))
        self.models.append(m)
        return m


eng = _Stub()
m1 = _obj = None

# 用真实 GameObject 走 _emit_object / _apply_object
from loom_game_object import GameObject
m1 = GameObject(create_cube(1.0), (0, 0, 0), (0, 0, 0), name='A')
m1.guid = 'g1'
m1.layer = 5
layer_tag.register_tag('Enemy')
m1.tag = 'Enemy'
eng.models.append(m1)

d = sceneio._emit_object(m1)
assert d['layer'] == 5, d.get('layer')
assert d['tag'] == 'Enemy', d.get('tag')
print('emit OK:', d['layer'], d['tag'])

# 旧场景兼容: 缺字段
old = {'id': 'g2', 'name': 'B', 'position': [0, 0, 0], 'rotation': [0, 0, 0]}
m2, _ = sceneio._apply_object(eng, old)
assert m2.layer == 0 and m2.tag == 'Untagged', (m2.layer, m2.tag)
print('legacy default OK')

# 越界 layer 钳制
bad = dict(old, id='g3', name='C', layer=999, tag='Player')
m3, _ = sceneio._apply_object(eng, bad)
assert m3.layer == 0, m3.layer
assert m3.tag == 'Player', m3.tag
print('layer clamp OK, tag restored:', m3.tag)

# 未注册 tag 自动注册
unreg = dict(old, id='g4', name='D', tag='Boss')
m4, _ = sceneio._apply_object(eng, unreg)
assert m4.tag == 'Boss'
assert layer_tag.tag_exists('Boss')
print('auto register OK:', m4.tag)

# 非法 tag 回退
illegal = dict(old, id='g5', name='E', tag='bad tag!')
m5, _ = sceneio._apply_object(eng, illegal)
assert m5.tag == 'Untagged', m5.tag
print('illegal fallback OK:', m5.tag)
print('SMOKE_PASS')
