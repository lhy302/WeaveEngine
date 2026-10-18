# -*- coding: utf-8 -*-
"""verify_audio_eai.py — 3D 音频验收探针 (契约 §12, 2026-10-18)"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..'))

import agent_commands as ac
import undo
from loom_game_object import GameObject
from mesh import create_cube


class _Stack:
    def __init__(self):
        self.items = []

    def push(self, cmd):
        self.items.append(cmd)


class _Ed:
    def __init__(self):
        self.models = [GameObject(create_cube(1.0), (0, 0, 0), (0, 0, 0), name='A'),
                       GameObject(create_cube(1.0), (0, 0, 0), (0, 0, 0), name='NoAu')]
        self.lights = []
        self.cameras = []
        self.selected_index = 0
        self.undo = _Stack()

    def _selected(self):
        return self.models[0]

    def _selected_light(self):
        return None

    def _selected_camera(self):
        return None

    def commit_model(self, m, label, apply_fn, before=None):
        before = before if before is not None else undo.snapshot(m)
        apply_fn()
        after = undo.snapshot(m)
        if after != before:
            self.undo.push(undo.StateCommand(label, self, m, before, after))


class _Win:
    def __init__(self):
        self.editor = _Ed()


w = _Win()
w.editor.models[0].add_audio_source(clip='x.wav')

# 正常设置
r = ac._COMMANDS['set_audio_3d'](w, {'name': 'A', 'category': 'voice',
                                     'min_distance': 2.0, 'max_distance': 80.0,
                                     'rolloff': 0.5})
assert r.get('category') == 'voice' and r.get('min_distance') == 2.0, r

# 非法 category
r = ac._COMMANDS['set_audio_3d'](w, {'name': 'A', 'category': 'x'})
assert 'error' in r
# 无音频源
r = ac._COMMANDS['set_audio_3d'](w, {'name': 'NoAu', 'category': 'sfx'})
assert 'error' in r
# 非数字
r = ac._COMMANDS['set_audio_3d'](w, {'name': 'A', 'min_distance': 'abc'})
assert 'error' in r
# max <= min
r = ac._COMMANDS['set_audio_3d'](w, {'name': 'A', 'min_distance': 10,
                                     'max_distance': 5})
assert 'error' in r

# 查询
r = ac._COMMANDS['get_audio_3d'](w, {'name': 'A'})
assert r.get('category') == 'voice' and r.get('is_spatial') is True
print('PASS verify_audio_eai')
