# -*- coding: utf-8 -*-
"""verify_audio_category.py — 3D 音频验收探针 (契约 §12, 2026-10-18)"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..'))

from loom_components import AudioSourceComponent

a = AudioSourceComponent()
for v in ('music', 'sfx', 'voice', 'MUSIC', 'Sfx'):
    a.category = v
    assert a.category == v.strip().lower(), (v, a.category)
for bad in ('bogus', '', None, 123, '音乐'):
    a.category = bad
    assert a.category == 'sfx', (bad, a.category)
print('PASS verify_audio_category')
