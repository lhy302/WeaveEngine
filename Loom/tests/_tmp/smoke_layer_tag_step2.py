# -*- coding: utf-8 -*-
"""smoke_layer_tag_step2.py — 第 2 步施工冒烟 (2026-10-18)

纪律: 本阶段只验证「引擎不崩」, 不做完整功能正确性测试 (留到第 1 档档末)。
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..'))

import layer_tag
from loom_game_object import GameObject
from mesh import create_cube

m = GameObject(create_cube(1.0), (0, 0, 0), (0, 0, 0), name='t')
assert m.layer == 0, m.layer
assert m.tag == 'Untagged', m.tag
print('default OK:', m.layer, m.tag)

m.layer = 5
assert m.layer == 5
print('set_layer OK:', m.layer, layer_tag.layer_name(5))

try:
    m.layer = 99
    raise AssertionError('越界未抛异常')
except ValueError:
    print('layer_guard OK')

try:
    m.tag = 'NotExistTag'
    raise AssertionError('未注册未抛异常')
except layer_tag.TagNotRegisteredError:
    print('tag_guard OK')

layer_tag.register_tag('Enemy')
m.tag = 'Enemy'
assert m.tag == 'Enemy'
print('set_tag OK:', m.tag)
print('SMOKE_PASS')
