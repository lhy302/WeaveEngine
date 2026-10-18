# -*- coding: utf-8 -*-
"""verify_audio_sceneio.py — 3D 音频验收探针 (契约 §12, 2026-10-18)"""
import os
import sys
import tempfile

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
eng = _Stub()

# 缺字段 -> 默认
m, _ = sceneio._apply_object(eng, dict(BASE, audio_source={'clip': 'x.wav'}))
a = m.audio_source
assert (a.category, a.min_distance, a.max_distance, a.rolloff) == ('sfx', 1.0, 500.0, 1.0)
print('legacy default OK')

# 全字段 -> 正确恢复 + emit 一致
src = {'clip': 'z.wav', 'category': 'voice', 'min_distance': 2.0,
       'max_distance': 50.0, 'rolloff': 0.8}
m2, _ = sceneio._apply_object(eng, dict(BASE, id='g2', name='B', audio_source=src))
out = sceneio._emit_object(m2)['audio_source']
for k in ('category', 'min_distance', 'max_distance', 'rolloff'):
    assert out[k] == src[k], (k, out[k], src[k])
print('roundtrip OK')

# 四类非法各自回退
bad = dict(BASE, id='g3', name='C',
           audio_source={'clip': 'x.wav', 'category': 'bogus',
                         'min_distance': -1, 'max_distance': 0, 'rolloff': 0})
m3, _ = sceneio._apply_object(eng, bad)
a3 = m3.audio_source
assert a3.category == 'sfx' and a3.min_distance == 1.0
assert a3.max_distance == 500.0 and a3.rolloff == 1.0
print('PASS verify_audio_sceneio')
