# -*- coding: utf-8 -*-
"""verify_audio_default.py — 3D 音频验收探针 (契约 §12, 2026-10-18)"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..'))

from loom_components import AudioSourceComponent
from loom_game_object import GameObject
from mesh import create_cube

a = AudioSourceComponent()
assert a.category == 'sfx', a.category
assert a.min_distance == 1.0, a.min_distance
assert a.max_distance == 500.0, a.max_distance
assert a.rolloff == 1.0, a.rolloff

m = GameObject(create_cube(1.0), (0, 0, 0), (0, 0, 0), name='t')
au = m.add_audio_source(clip='x.wav')
assert au.category == 'sfx' and au.min_distance == 1.0
print('PASS verify_audio_default')
