# -*- coding: utf-8 -*-
"""verify_audio_pygame_fallback.py — 3D 音频验收探针 (契约 §12, 2026-10-18)"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..'))

os.environ['LOOM_AUDIO_BACKEND'] = 'pygame'
import audio_backend as ab

b = ab.AudioBackend()
b._ensure()
assert b.mode == 'pygame', b.mode

# play_spatial 对不存在的文件返回 None 且不崩
assert b.play_spatial('nope.wav', (0, 0, 0), owner=1) is None
assert b._spatial_warned is False, '文件不存在不该触发 3D 警告'

# 直接调 pygame 分支的警告路径 (打桩 ent)
class _S:
    def set_volume(self, v):
        pass

    def play(self, loops=0):
        pass


b._handles[('fake.wav', 7)] = {'kind': 'py', 'obj': _S()}
b.play_spatial('fake.wav', (0, 0, 0), owner=7)
assert b._spatial_warned is True, 'pygame 分支应警告一次'
b.play_spatial('fake.wav', (0, 0, 0), owner=7)   # 第二次不该重复
print('PASS verify_audio_pygame_fallback')
b.shutdown()
