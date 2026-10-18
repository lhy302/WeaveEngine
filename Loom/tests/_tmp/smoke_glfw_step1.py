# -*- coding: utf-8 -*-
"""smoke_glfw_step1.py — loom_glfw_window 模块级冒烟 (2026-10-18)

不开窗口、不需要显示器。验证：
  1) 模块可导入（无 import 期异常）
  2) 键码映射双向一致
  3) loom_input._KEYMAP 全覆盖
  4) GlfwWindowMixin 接口完备
  5) B1 占位字段存在（_ime_preedit = '', _ime_active = False）
  6) preedit 绑定死代码已清除（函数不存在 + 无实际调用）
"""
import os
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..'))

import loom_glfw_window as lgw

# 1) 双向一致
assert len(lgw._GLFW_TO_PG) > 0
assert len(lgw._PG_TO_GLFW) == len(lgw._GLFW_TO_PG), (
    '反查表键数不一致: %d vs %d' % (len(lgw._PG_TO_GLFW), len(lgw._GLFW_TO_PG)))
for gl, pg in lgw._GLFW_TO_PG.items():
    assert lgw._PG_TO_GLFW[pg] == gl, '反查失败 pg=%r' % (pg,)
print('键码映射双向一致 OK: %d 项' % len(lgw._GLFW_TO_PG))

# 2) 关键键位在映射表中
from loom_input import _KEYMAP
missing = [(name, pg_key) for name, pg_key in _KEYMAP.items()
           if pg_key not in lgw._PG_TO_GLFW]
assert not missing, 'loom_input._KEYMAP 有键未覆盖: %r' % (missing,)
print('loom_input._KEYMAP 全覆盖 OK: %d 项' % len(_KEYMAP))

# 3) GlfwWindowMixin 接口完备
required = ['_init_glfw_window', '_handle_events', '_on_resize',
            '_desktop_resolution', '_set_fullscreen', '_toggle_fullscreen',
            '_place_fullscreen_window', '_glfw_swap_buffers', '_glfw_shutdown',
            'on_key_event', 'on_text_input', 'on_quit_request']
for name in required:
    assert hasattr(lgw.GlfwWindowMixin, name), '缺方法: %s' % name
print('GlfwWindowMixin 接口完备 OK: %d 个方法' % len(required))

# 4) B1 占位字段存在
import inspect
src_init = inspect.getsource(lgw.GlfwWindowMixin._init_glfw_window)
assert '_ime_preedit' in src_init, '缺 _ime_preedit 占位'
assert '_ime_active' in src_init, '缺 _ime_active 占位'
print('B1 占位字段 OK (_ime_preedit / _ime_active)')

# 5) preedit 绑定死代码已清除
assert not hasattr(lgw, '_setup_glfw_ime_ctypes'),     'preedit 绑定函数未删除'

# 检查不存在实际的函数调用（不是注释里的提及）
with open(lgw.__file__, 'r', encoding='utf-8') as f:
    src_file = f.read()
# 匹配 dll.glfwSetPreeditCallback(...) 或类似的实际调用
call_pat = re.compile(r'\.glfwSetPreeditCallback\s*\(')
assert not call_pat.search(src_file),     '存在 glfwSetPreeditCallback 实际调用'
# 确认没有 ctypes.CFUNCTYPE 绑定残留
assert 'GLFWpreeditfun' not in src_file, 'CFUNCTYPE 预编辑绑定残留'
print('preedit 死代码已清除 OK（无函数/无调用/无 CFUNCTYPE）')

print('SMOKE_PASS')
