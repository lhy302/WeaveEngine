# -*- coding: utf-8 -*-
"""verify_layer_range.py — Layer/Tag 验收探针 (契约 §10, 2026-10-18)"""
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
for ok in (0, 31):
    m.layer = ok
    assert m.layer == ok
for bad in (-1, 32, 999):
    try:
        m.layer = bad
        raise AssertionError('layer=%r 应抛 ValueError' % (bad,))
    except ValueError:
        pass
print('PASS verify_layer_range')
