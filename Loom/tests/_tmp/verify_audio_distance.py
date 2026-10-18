# -*- coding: utf-8 -*-
"""verify_audio_distance.py — 3D 音频验收探针 (契约 §12, 2026-10-18)"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..'))

from loom_components import AudioSourceComponent

a = AudioSourceComponent()
a.min_distance = 5.0
a.max_distance = 10.0
assert a.min_distance == 5.0 and a.max_distance == 10.0

# max <= min 应抬到 min*2
a.max_distance = 3.0
assert a.max_distance > a.min_distance, (a.min_distance, a.max_distance)
print('max<=min clamped:', a.min_distance, a.max_distance)

# min <= 0 回退 1.0
a.min_distance = -5
assert a.min_distance == 1.0
# rolloff <= 0 回退 1.0
a.rolloff = 0
assert a.rolloff == 1.0
print('PASS verify_audio_distance')
