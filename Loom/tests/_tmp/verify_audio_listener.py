# -*- coding: utf-8 -*-
"""verify_audio_listener.py — 3D 音频验收探针 (契约 §12, 2026-10-18)"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..'))

from loom_frame_components import FrameComponentMixin
from loom_types import Point3D


class _StubAudio:
    def __init__(self):
        self.calls = []

    def set_listener(self, pos, fwd, up):
        self.calls.append((tuple(pos), tuple(fwd), tuple(up)))

    def play(self, *a, **kw):
        pass

    def play_spatial(self, *a, **kw):
        pass

    def stop(self, *a, **kw):
        pass

    def update_sound_position(self, *a, **kw):
        pass


class _Eng(FrameComponentMixin):
    def __init__(self):
        self.audio = _StubAudio()
        self.models = []
        self.camera = Point3D(0.0, 0.0, 10.0)
        self.camera_yaw = 0.0
        self.camera_pitch = 0.0

    def active_camera_object(self):
        return None


e = _Eng()
e.update_audio(0.016)
assert e.audio.calls, 'set_listener 未被调'
pos, fwd, up = e.audio.calls[0]
assert abs(pos[2] - 10.0) < 1e-6, pos
# yaw=0,pitch=0 -> 前向应为 (0,0,-1)
assert abs(fwd[2] + 1.0) < 1e-6, fwd
assert abs(up[1] - 1.0) < 1e-6, up
print('yaw=0 listener OK:', pos, fwd, up)

# 相机移动 -> 监听器跟着动
e.camera = Point3D(5.0, 2.0, 3.0)
e.update_audio(0.016)
pos2 = e.audio.calls[-1][0]
assert abs(pos2[0] - 5.0) < 1e-6 and abs(pos2[1] - 2.0) < 1e-6
print('PASS verify_audio_listener')
