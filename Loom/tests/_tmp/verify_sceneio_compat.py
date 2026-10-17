# -*- coding: utf-8 -*-
"""verify_sceneio_compat.py — Layer/Tag 验收探针 (契约 §10, 2026-10-18)"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..'))

import layer_tag

_TMP = tempfile.mkdtemp(prefix='lt_probe_')
layer_tag.config_path = lambda base=None: os.path.join(_TMP, 'layer_tag.json')
layer_tag.reload()

import sceneio
from loom_game_object import GameObject
from mesh import create_cube


class _Stub:
    def __init__(self):
        self.models = []
        self.materials = []
        self.lights = []
        self.cameras = []
        self.gravity = -9.8
        self.scene_name = 't'

    def add_model(self, mesh, position, rotation, **kw):
        m = GameObject(mesh, tuple(position), tuple(rotation),
                       name=kw.get('name'), scale=kw.get('scale'),
                       visible=kw.get('visible', True),
                       normal_mode=kw.get('normal_mode', 'flat'))
        self.models.append(m)
        return m


eng = _Stub()
# 旧场景: 无 layer/tag 字段
old = {'id': 'g1', 'name': 'A', 'position': [0, 0, 0], 'rotation': [0, 0, 0]}
m, _ = sceneio._apply_object(eng, old)
assert m.layer == 0 and m.tag == 'Untagged'
# 新场景: 带字段
layer_tag.register_tag('Enemy')
new = dict(old, id='g2', name='B', layer=5, tag='Enemy')
m2, _ = sceneio._apply_object(eng, new)
assert m2.layer == 5 and m2.tag == 'Enemy'
# emit 往返
d = sceneio._emit_object(m2)
assert d['layer'] == 5 and d['tag'] == 'Enemy'
print('PASS verify_sceneio_compat')
