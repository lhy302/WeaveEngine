# -*- coding: utf-8 -*-
"""verify_config_fallback.py — Layer/Tag 验收探针 (契约 §10, 2026-10-18)"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..'))

import layer_tag

_TMP = tempfile.mkdtemp(prefix='lt_probe_')
layer_tag.config_path = lambda base=None: os.path.join(_TMP, 'layer_tag.json')
layer_tag.reload()

# 写坏文件 -> load 应回退默认且不抛异常
with open(layer_tag.config_path(), 'w', encoding='utf-8') as f:
    f.write('{ this is not json')
layer_tag.reload()
L = layer_tag.get_layers()
T = layer_tag.get_tags()
assert L[0] == 'Default', L[0]
assert len(L) == 32
assert 'Untagged' in T and len(T) >= 7
print('PASS verify_config_fallback')
