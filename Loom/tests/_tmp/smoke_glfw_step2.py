# -*- coding: utf-8 -*-
"""smoke_glfw_step2.py — GLEngine 引入 GLFW 后的 import 冒烟 (2026-10-18)

不开窗口。只验证：
  1) engine.py 可导入
  2) GLEngine 类继承 GlfwWindowMixin
  3) editor.py 可导入（EditorApp 也继承 GLEngine）
  4) runtime.py 可导入（PlayerApp 也继承 GLEngine）
  5) loom_window.py 已删除（旧 pygame 窗口层彻底剥离）
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..'))

# 1) engine 可导入
import engine
print('engine imported OK')

# 2) GLEngine 继承 GlfwWindowMixin（旧 loom_window 已删）
from loom_glfw_window import GlfwWindowMixin
assert issubclass(engine.GLEngine, GlfwWindowMixin), \
    'GLEngine 未继承 GlfwWindowMixin'
print('GLEngine -> GlfwWindowMixin OK')

# 3) editor 可导入
import editor
print('editor imported OK')
assert issubclass(editor.EditorApp, GlfwWindowMixin)
print('EditorApp -> GlfwWindowMixin OK')

# 4) runtime 可导入
import runtime
print('runtime imported OK')
assert issubclass(runtime.PlayerApp, GlfwWindowMixin)
print('PlayerApp -> GlfwWindowMixin OK')

# 5) loom_window.py 已删
loom_window_path = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), '..', '..', 'loom_window.py')
loom_window_path = os.path.abspath(loom_window_path)
assert not os.path.exists(loom_window_path), \
    'loom_window.py 未删除: %s' % loom_window_path
print('loom_window.py 已删 OK')

# 6) ui/minimal_editor_view.py 已删
minimal_path = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), '..', '..', 'ui',
    'minimal_editor_view.py')
minimal_path = os.path.abspath(minimal_path)
assert not os.path.exists(minimal_path), \
    'ui/minimal_editor_view.py 未删除: %s' % minimal_path
print('ui/minimal_editor_view.py 已删 OK')

print('SMOKE_PASS')
