# -*- coding: utf-8 -*-
"""smoke_audio_3d_step3.py — update_audio 3D 分流冒烟 (2026-10-18)"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..'))

from loom_frame_components import FrameComponentMixin
from loom_game_object import GameObject
from loom_types import Point3D
from mesh import create_cube


class _StubAudio:
    def __init__(self):
        self.calls = []

    def set_listener(self, pos, fwd, up):
        self.calls.append(('listener', tuple(pos)))

    def play(self, clip, loop, vol, owner=None):
        self.calls.append(('play2d', clip))

    def play_spatial(self, clip, pos, loop=False, volume=1.0,
                     min_distance=1.0, max_distance=500.0, rolloff=1.0,
                     owner=None):
        self.calls.append(('play3d', clip, tuple(pos)))

    def stop(self, clip, owner=None):
        self.calls.append(('stop', clip))

    def update_sound_position(self, clip, pos, owner=None):
        self.calls.append(('upd', clip, tuple(pos)))


class _Eng(FrameComponentMixin):
    def __init__(self):
        self.audio = _StubAudio()
        self.models = []
        self.camera = Point3D(0.0, 0.0, 10.0)
        self.camera_yaw = 0.0
        self.camera_pitch = 0.0

    def active_camera_object(self):
        return None

    def world_position(self, m):
        return m.position


e = _Eng()

m_music = GameObject(create_cube(1.0), (5, 0, 5), (0, 0, 0), name='bgm')
m_music.add_audio_source(clip='bgm.wav', category='music')
m_music.audio_source.playing = True

m_sfx = GameObject(create_cube(1.0), (3, 0, 0), (0, 0, 0), name='sfx')
m_sfx.add_audio_source(clip='hit.wav', category='sfx')
m_sfx.audio_source.playing = True

e.models = [m_music, m_sfx]

e.update_audio(0.016)
kinds = [c[0] for c in e.audio.calls]
assert 'listener' in kinds, kinds
assert ('play2d', 'bgm.wav') in e.audio.calls, e.audio.calls
assert any(c[0] == 'play3d' and c[1] == 'hit.wav' for c in e.audio.calls), e.audio.calls
print('listen/2d/3d OK:', kinds)

# 位置变化 -> update_sound_position
e.audio.calls.clear()
m_sfx.position = Point3D(9, 0, 0)
e.update_audio(0.016)
ups = [c for c in e.audio.calls if c[0] == 'upd']
assert ups and abs(ups[0][2][0] - 9.0) < 1e-6, e.audio.calls
print('position update OK:', ups[0])

# 位置不变 -> 不重复更新
e.audio.calls.clear()
e.update_audio(0.016)
assert not [c for c in e.audio.calls if c[0] == 'upd'], e.audio.calls
print('no redundant update OK')

# music 移动也不触发位置更新
e.audio.calls.clear()
m_music.position = Point3D(0, 0, 0)
e.update_audio(0.016)
assert not [c for c in e.audio.calls if c[0] == 'upd'], e.audio.calls
print('music never spatial OK')
print('SMOKE_PASS')
