# -*- coding: utf-8 -*-
"""smoke_audio_3d_step5.py — EAI 音频 3D 命令冒烟 (2026-10-18)"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..'))

import agent_commands as ac
import undo
from loom_game_object import GameObject
from mesh import create_cube


class _TinyStack:
    def __init__(self):
        self.items = []

    def push(self, cmd):
        self.items.append(cmd)


class _FakeEditor:
    def __init__(self):
        self.models = [GameObject(create_cube(1.0), (0, 0, 0), (0, 0, 0), name='A'),
                       GameObject(create_cube(1.0), (0, 0, 0), (0, 0, 0), name='NoAudio')]
        self.lights = []
        self.cameras = []
        self.selected_index = 0
        self.undo = _TinyStack()

    def _selected(self):
        return self.models[0] if self.models else None

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


class _FakeWin:
    def __init__(self):
        self.editor = _FakeEditor()


names = ac.command_names()
assert 'set_audio_3d' in names and 'get_audio_3d' in names
print('registered OK')

win = _FakeWin()
win.editor.models[0].add_audio_source(clip='x.wav')

# 成功设置
r = ac._COMMANDS['set_audio_3d'](win, {'name': 'A', 'category': 'music',
                                       'min_distance': 2.0, 'max_distance': 100.0,
                                       'rolloff': 0.8})
assert r.get('category') == 'music' and r.get('min_distance') == 2.0, r
assert r.get('max_distance') == 100.0 and r.get('rolloff') == 0.8, r
assert len(win.editor.undo.items) == 1, '应压一次撤销'
print('set OK:', r)

# 非法 category
r = ac._COMMANDS['set_audio_3d'](win, {'name': 'A', 'category': 'bogus'})
assert 'error' in r, r
print('bad category guard OK')

# 无音频源
r = ac._COMMANDS['set_audio_3d'](win, {'name': 'NoAudio', 'category': 'sfx'})
assert 'error' in r and 'AudioSource' in r['error'], r
print('no audio source guard OK')

# max <= min
r = ac._COMMANDS['set_audio_3d'](win, {'name': 'A', 'min_distance': 10,
                                       'max_distance': 5})
assert 'error' in r, r
print('max<=min guard OK')

# 非数字
r = ac._COMMANDS['set_audio_3d'](win, {'name': 'A', 'min_distance': 'abc'})
assert 'error' in r, r
print('non-numeric guard OK')

# 查询
r = ac._COMMANDS['get_audio_3d'](win, {'name': 'A'})
assert r.get('category') == 'music' and r.get('is_spatial') is False, r
print('get OK:', r)
print('SMOKE_PASS')
