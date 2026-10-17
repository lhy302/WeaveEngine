# -*- coding: utf-8 -*-
"""verify_layer_default.py — Layer/Tag 验收探针 (契约 §10, 2026-10-18)"""
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
assert m.layer == 0, 'layer 默认应为 0, 实际 %r' % (m.layer,)
assert m.tag == 'Untagged', 'tag 默认应为 Untagged, 实际 %r' % (m.tag,)
print('PASS verify_layer_default')
