# -*- coding: utf-8 -*-
"""verify_find_by_tag.py — Layer/Tag 验收探针 (契约 §10, 2026-10-18)"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..'))

import layer_tag

_TMP = tempfile.mkdtemp(prefix='lt_probe_')
layer_tag.config_path = lambda base=None: os.path.join(_TMP, 'layer_tag.json')
layer_tag.reload()

from engine import GLEngine
from loom_game_object import GameObject
from mesh import create_cube


class _Stub:
    def __init__(self):
        self.models = []


eng = _Stub()
eng.models = [GameObject(create_cube(1.0), (0, 0, 0), (0, 0, 0), name='A'),
              GameObject(create_cube(1.0), (0, 0, 0), (0, 0, 0), name='B'),
              GameObject(create_cube(1.0), (0, 0, 0), (0, 0, 0), name='C')]
layer_tag.register_tag('Enemy')
eng.models[0].tag = 'Enemy'
eng.models[2].tag = 'Enemy'
hits = GLEngine.find_by_tag(eng, 'Enemy')
assert [h.name for h in hits] == ['A', 'C'], [h.name for h in hits]
# 大小写不敏感
assert len(GLEngine.find_by_tag(eng, 'enemy')) == 2
# 不存在返回空
assert GLEngine.find_by_tag(eng, 'Player') == []
print('PASS verify_find_by_tag')
