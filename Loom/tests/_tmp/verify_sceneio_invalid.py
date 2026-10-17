# -*- coding: utf-8 -*-
"""verify_sceneio_invalid.py — Layer/Tag 验收探针 (契约 §10, 2026-10-18)"""
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
base = {'position': [0, 0, 0], 'rotation': [0, 0, 0]}
# layer 越界 -> 钳制 0
m, _ = sceneio._apply_object(eng, dict(base, id='g1', name='A', layer=999))
assert m.layer == 0, m.layer
# tag 未注册 -> 自动注册
m2, _ = sceneio._apply_object(eng, dict(base, id='g2', name='B', tag='Boss'))
assert m2.tag == 'Boss'
assert layer_tag.tag_exists('Boss')
# tag 非法字符 -> 回退 Untagged
m3, _ = sceneio._apply_object(eng, dict(base, id='g3', name='C', tag='bad tag!'))
assert m3.tag == 'Untagged', m3.tag
print('PASS verify_sceneio_invalid')
