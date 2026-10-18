# -*- coding: utf-8 -*-
"""verify_audio_is_spatial.py — 3D 音频验收探针 (契约 §12, 2026-10-18)"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..'))

from loom_components import AudioSourceComponent

a = AudioSourceComponent()
a.category = 'music'
assert a.is_spatial() is False
a.category = 'sfx'
assert a.is_spatial() is True
a.category = 'voice'
assert a.is_spatial() is True
print('PASS verify_audio_is_spatial')
