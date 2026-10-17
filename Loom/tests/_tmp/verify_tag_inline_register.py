# -*- coding: utf-8 -*-
"""verify_tag_inline_register.py — Layer/Tag 验收探针 (契约 §10, 2026-10-18)"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..'))

import layer_tag

_TMP = tempfile.mkdtemp(prefix='lt_probe_')
layer_tag.config_path = lambda base=None: os.path.join(_TMP, 'layer_tag.json')
layer_tag.reload()

from loom_game_object import GameObject
from mesh import create_cube

m = GameObject(create_cube(1.0), (0, 0, 0), (0, 0, 0), name='t')
assert not layer_tag.tag_exists('Enemy')
layer_tag.register_tag('Enemy')
assert layer_tag.tag_exists('Enemy')
m.tag = 'Enemy'
assert m.tag == 'Enemy'
# 幂等: 重复注册返回 False
assert layer_tag.register_tag('Enemy') is False
print('PASS verify_tag_inline_register')
