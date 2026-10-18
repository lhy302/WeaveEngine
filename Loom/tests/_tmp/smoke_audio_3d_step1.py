# -*- coding: utf-8 -*-
"""smoke_audio_3d_step1.py — 3D 音频第 1 步冒烟 (2026-10-18)"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..'))

from loom_components import AudioSourceComponent
from loom_game_object import GameObject
from mesh import create_cube
import undo

a = AudioSourceComponent()
assert a.category == 'sfx', a.category
assert a.min_distance == 1.0, a.min_distance
assert a.max_distance == 500.0, a.max_distance
assert a.rolloff == 1.0, a.rolloff
assert a.is_spatial() is True
print('defaults OK')

a.category = 'music'
assert a.is_spatial() is False
a.category = 'voice'
assert a.is_spatial() is True
a.category = 'bogus'
assert a.category == 'sfx', '非法应回退 sfx'
print('category guard OK')

a.min_distance = -5
assert a.min_distance == 1.0
a.max_distance = 0.5
assert a.max_distance > a.min_distance, (a.min_distance, a.max_distance)
a.rolloff = 0
assert a.rolloff == 1.0
print('numeric guard OK')

m = GameObject(create_cube(1.0), (0, 0, 0), (0, 0, 0), name='t')
au = m.add_audio_source(clip='x.wav', category='music', min_distance=2.0)
assert au.category == 'music' and au.min_distance == 2.0
print('gameobject wiring OK')

snap = undo.snapshot(m)
assert len(snap['audio_source']) == 7, len(snap['audio_source'])
au.category = 'sfx'
au.min_distance = 9.0
undo.apply_snapshot(m, snap)
assert m.audio_source.category == 'music'
assert m.audio_source.min_distance == 2.0
print('undo roundtrip OK')

old = tuple(snap['audio_source'][:3])
snap2 = dict(snap, audio_source=old)
m.audio_source.category = 'voice'
undo.apply_snapshot(m, snap2)
assert m.audio_source.category == 'voice', '旧3元快照不该改3D字段'
print('legacy 3-tuple OK')
print('SMOKE_PASS')
