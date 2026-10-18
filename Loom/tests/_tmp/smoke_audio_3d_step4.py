# -*- coding: utf-8 -*-
"""smoke_audio_3d_step4.py — sceneio 音频 3D 序列化冒烟 (2026-10-18)"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..'))

import sceneio
from loom_game_object import GameObject
from mesh import create_cube


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


BASE = {'id': 'g1', 'name': 'A', 'position': [0, 0, 0], 'rotation': [0, 0, 0]}

# 1) emit 含新字段
e = _Stub()
m = e.add_model(create_cube(1.0), (0, 0, 0), (0, 0, 0), name='A')
m.guid = 'g1'
m.add_audio_source(clip='a.wav', category='voice', min_distance=2.5,
                   max_distance=80.0, rolloff=0.7)
d = sceneio._emit_object(m)['audio_source']
assert d['category'] == 'voice' and d['min_distance'] == 2.5
assert d['max_distance'] == 80.0 and d['rolloff'] == 0.7
print('emit OK:', d)

# 2) 旧场景缺字段 -> 默认
e2 = _Stub()
old = dict(BASE, audio_source={'clip': 'x.wav', 'loop': False, 'volume': 1.0})
m2, _ = sceneio._apply_object(e2, old)
a2 = m2.audio_source
assert (a2.category, a2.min_distance, a2.max_distance, a2.rolloff) == \
       ('sfx', 1.0, 500.0, 1.0), (a2.category, a2.min_distance, a2.max_distance, a2.rolloff)
print('legacy default OK')

# 3) 非法 category -> sfx
e3 = _Stub()
bad_cat = dict(BASE, id='g3', name='B',
               audio_source={'clip': 'x.wav', 'category': 'bogus'})
m3, _ = sceneio._apply_object(e3, bad_cat)
assert m3.audio_source.category == 'sfx'
print('bad category fallback OK')

# 4) min<=0 -> 1.0
e4 = _Stub()
bad_min = dict(BASE, id='g4', name='C',
               audio_source={'clip': 'x.wav', 'min_distance': -3})
m4, _ = sceneio._apply_object(e4, bad_min)
assert m4.audio_source.min_distance == 1.0
print('bad min fallback OK')

# 5) max<=min -> 双双回默认
e5 = _Stub()
bad_max = dict(BASE, id='g5', name='D',
               audio_source={'clip': 'x.wav', 'min_distance': 10, 'max_distance': 5})
m5, _ = sceneio._apply_object(e5, bad_max)
assert (m5.audio_source.min_distance, m5.audio_source.max_distance) == (1.0, 500.0)
print('bad max fallback OK')

# 6) rolloff<=0 -> 1.0
e6 = _Stub()
bad_ro = dict(BASE, id='g6', name='E',
              audio_source={'clip': 'x.wav', 'rolloff': 0})
m6, _ = sceneio._apply_object(e6, bad_ro)
assert m6.audio_source.rolloff == 1.0
print('bad rolloff fallback OK')

# 7) 往返一致
e7 = _Stub()
src = dict(BASE, id='g7', name='F',
           audio_source={'clip': 'z.wav', 'category': 'music',
                         'min_distance': 3.0, 'max_distance': 60.0, 'rolloff': 0.5})
m7, _ = sceneio._apply_object(e7, src)
again = sceneio._emit_object(m7)['audio_source']
for k in ('category', 'min_distance', 'max_distance', 'rolloff'):
    assert again[k] == src['audio_source'][k], (k, again[k], src['audio_source'][k])
print('roundtrip OK')
print('SMOKE_PASS')
