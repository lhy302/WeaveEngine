# -*- coding: utf-8 -*-
"""verify_undo_layer_tag.py — Layer/Tag 撤销验收探针 (契约 §4.3, 2026-10-18)"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..'))

import layer_tag
_TMP = tempfile.mkdtemp(prefix='lt_probe_')
layer_tag.config_path = lambda base=None: os.path.join(_TMP, 'layer_tag.json')
layer_tag.reload()

import undo
from loom_game_object import GameObject
from mesh import create_cube

layer_tag.register_tag('Enemy')
m = GameObject(create_cube(1.0), (0, 0, 0), (0, 0, 0), name='t')
m.layer = 3
m.tag = 'Enemy'

# 快照往返
snap = undo.snapshot(m)
assert snap['layer'] == 3, snap.get('layer')
assert snap['tag'] == 'Enemy', snap.get('tag')

m.layer = 7
m.tag = 'Player'
undo.apply_snapshot(m, snap)
assert m.layer == 3, m.layer
assert m.tag == 'Enemy', m.tag
print('snapshot roundtrip OK')

# 旧快照兼容 (无 layer/tag 键): 不应抛异常
old_snap = dict(snap)
old_snap.pop('layer')
old_snap.pop('tag')
m.layer = 9
undo.apply_snapshot(m, old_snap)
assert m.layer == 9, '旧快照不该改动 layer'
print('legacy snapshot OK')
print('PASS verify_undo_layer_tag')
