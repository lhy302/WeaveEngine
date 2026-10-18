# -*- coding: utf-8 -*-
"""verify_audio_undo.py — 3D 音频验收探针 (契约 §12, 2026-10-18)"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..'))

import undo
from loom_game_object import GameObject
from mesh import create_cube

m = GameObject(create_cube(1.0), (0, 0, 0), (0, 0, 0), name='t')
a = m.add_audio_source(clip='x.wav', category='sfx', min_distance=1.0,
                       max_distance=500.0, rolloff=1.0)
snap = undo.snapshot(m)
assert len(snap['audio_source']) == 7, len(snap['audio_source'])

a.category = 'music'
a.min_distance = 5.0
a.max_distance = 100.0
a.rolloff = 0.5
undo.apply_snapshot(m, snap)
assert m.audio_source.category == 'sfx'
assert m.audio_source.min_distance == 1.0
assert m.audio_source.max_distance == 500.0
assert m.audio_source.rolloff == 1.0
print('roundtrip OK')

# 旧 3 元快照兼容
old = dict(snap, audio_source=tuple(snap['audio_source'][:3]))
m.audio_source.category = 'voice'
m.audio_source.min_distance = 9.0
undo.apply_snapshot(m, old)
assert m.audio_source.category == 'voice', '旧快照不该改 3D 字段'
assert m.audio_source.min_distance == 9.0
print('legacy 3-tuple OK')
print('PASS verify_audio_undo')
