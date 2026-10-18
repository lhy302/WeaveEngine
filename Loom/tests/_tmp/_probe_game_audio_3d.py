# -*- coding: utf-8 -*-
"""_probe_game_audio_3d.py — 探测 game-audio 3D API 能力 (2026-10-18)"""
import game_audio as ga

print('=== Vec3 ===')
print([a for a in dir(ga.Vec3) if not a.startswith('_')])
print()
print('=== AudioManager ===')
print([a for a in dir(ga.AudioManager) if not a.startswith('_')])
print()
print('=== SoundHandle ===')
print([a for a in dir(ga.SoundHandle) if not a.startswith('_')])
print()
print('=== TrackHandle ===')
print([a for a in dir(ga.TrackHandle) if not a.startswith('_')])
print()
print('=== GroupHandle ===')
print([a for a in dir(ga.GroupHandle) if not a.startswith('_')])
