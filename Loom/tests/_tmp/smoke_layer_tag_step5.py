# -*- coding: utf-8 -*-
"""smoke_layer_tag_step5.py — 第 5 步 EAI 命令冒烟 (2026-10-18)

纪律: 只验证命令已注册、模块可导入, 不做功能正确性测试 (留到档末)。
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..'))

import agent_commands as ac

names = ac.command_names()
need = ['set_layer', 'set_tag', 'get_layer_tag', 'list_tags', 'list_layers']
for n in need:
    assert n in names, '命令未注册: ' + n
    print('registered OK:', n, '->', names[n][:30])
print('SMOKE_PASS')
