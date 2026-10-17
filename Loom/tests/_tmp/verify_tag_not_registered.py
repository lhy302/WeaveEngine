# -*- coding: utf-8 -*-
"""verify_tag_not_registered.py — Layer/Tag 验收探针 (契约 §10, 2026-10-18)"""
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
try:
    m.tag = '不存在的标签XYZ'
    raise AssertionError('未注册 tag 应抛 TagNotRegisteredError')
except layer_tag.TagNotRegisteredError:
    pass
assert m.tag == 'Untagged', '失败后应保持原值'
print('PASS verify_tag_not_registered')
