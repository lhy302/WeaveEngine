# -*- coding: utf-8 -*-
"""smoke_audio_3d_step2.py — AudioBackend 3D 接口冒烟 (2026-10-18)"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..'))
os.environ['LOOM_AUDIO_BACKEND'] = 'pygame'    # 不占真实音频设备

import audio_backend as ab

b = ab.AudioBackend()
assert hasattr(b, 'set_listener')
assert hasattr(b, 'play_spatial')
assert hasattr(b, 'update_sound_position')
print('methods OK, mode =', b._ensure(), b.mode)

# pygame 后端: 监听器/位置更新应静默 no-op
b.set_listener((1, 2, 3), (0, 0, -1), (0, 1, 0))
b.update_sound_position('nonexistent.wav', (0, 0, 0))
print('noop paths OK')

# 不存在的音频: play_spatial 返回 None 且不崩
assert b.play_spatial('nonexistent.wav', (0, 0, 0), owner=1) is None
print('play_spatial missing-file OK')
b.shutdown()
print('SMOKE_PASS')
