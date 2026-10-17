# -*- coding: utf-8 -*-
"""verify_eai_set_layer.py — EAI layer/tag 命令验收探针 (契约 §5, 2026-10-18)"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..'))

import layer_tag
_TMP = tempfile.mkdtemp(prefix='lt_probe_')
layer_tag.config_path = lambda base=None: os.path.join(_TMP, 'layer_tag.json')
layer_tag.reload()

import agent_commands as ac
import undo
from loom_game_object import GameObject
from mesh import create_cube


class _TinyStack:
    """极简撤销栈桩: 只验证 push 发生, 不依赖 undo.py 的具体栈类名."""

    def __init__(self):
        self.items = []

    def push(self, cmd):
        self.items.append(cmd)

    def undo(self):
        if self.items:
            return self.items.pop().undo()

    def redo(self):
        pass


class _FakeEditor:
    def __init__(self):
        self.models = [GameObject(create_cube(1.0), (0, 0, 0), (0, 0, 0), name='方块')]
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

    def layer_name(self, i):
        return layer_tag.layer_name(i)

    def tag_exists(self, t):
        return layer_tag.tag_exists(t)

    def register_tag(self, t):
        return layer_tag.register_tag(t)


class _FakeWin:
    def __init__(self):
        self.editor = _FakeEditor()


win = _FakeWin()
m = win.editor.models[0]

r = ac._COMMANDS['set_layer'](win, {'name': '方块', 'layer': 5})
assert r.get('layer') == 5, r
assert r.get('layer_name') == 'UI', r
assert m.layer == 5
assert len(win.editor.undo.items) == 1, 'set_layer 应压一次撤销'
print('set_layer OK:', r)

r = ac._COMMANDS['set_layer'](win, {'name': '方块', 'layer': 999})
assert 'error' in r, r
assert m.layer == 5, '越界不应改动 layer'
print('set_layer range guard OK')

r = ac._COMMANDS['set_tag'](win, {'name': '方块', 'tag': 'Enemy'})
assert r.get('tag') == 'Enemy', r
assert layer_tag.tag_exists('Enemy')
assert m.tag == 'Enemy'
print('set_tag auto-register OK')

r = ac._COMMANDS['set_tag'](win, {'name': '方块', 'tag': 'bad tag!'})
assert 'error' in r, r
print('set_tag illegal guard OK')

r = ac._COMMANDS['get_layer_tag'](win, {'name': '方块'})
assert r.get('layer') == 5 and r.get('tag') == 'Enemy', r
print('get_layer_tag OK:', r)

r = ac._COMMANDS['list_tags'](win, {})
assert 'Enemy' in r.get('tags', []), r
r = ac._COMMANDS['list_layers'](win, {})
assert r.get('layers', {}).get('0') == 'Default', r
print('list_tags/list_layers OK')
print('PASS verify_eai_set_layer')
