# -*- coding: utf-8 -*-
"""_glfw_symbol_probe.py — 探测 glfw3.dll 的 IME 相关符号 (2026-10-18)"""
import ctypes
import ctypes.util
import os

import glfw

print("glfw 包路径:", os.path.dirname(glfw.__file__))
print("glfw version string:", glfw.get_version_string())
print()

# 加载 DLL
dll = ctypes.CDLL(ctypes.util.find_library('glfw3') or 'glfw3.dll')

# 探测所有已知的 glfwSet* 符号
symbols = [
    'glfwSetPreeditCallback',   # GLFW 3.4 预期有
    'glfwSetCharCallback',       # 3.0+
    'glfwSetKeyCallback',
    'glfwSetCursorPosCallback',
    'glfwSetMouseButtonCallback',
    'glfwSetScrollCallback',
    'glfwSetWindowSizeCallback',
    'glfwSetWindowCloseCallback',
    'glfwGetWin32Window',        # Windows 平台
    'glfwGetWindowUserPointer',
    'glfwSetWindowUserPointer',
    'glfwCreateWindow',
    'glfwInit',
    'glfwTerminate',
    'glfwGetVersionString',
    'glfwGetVersion',
]
for s in symbols:
    print("%-30s: %s" % (s, 'YES' if hasattr(dll, s) else 'NO'))

# 也探测 glfwGetVersion 的返回（确认 DLL 实际版本）
try:
    major = ctypes.c_int(0)
    minor = ctypes.c_int(0)
    rev = ctypes.c_int(0)
    dll.glfwGetVersion(ctypes.byref(major), ctypes.byref(minor), ctypes.byref(rev))
    print()
    print("DLL 实际版本: %d.%d.%d" % (major.value, minor.value, rev.value))
except Exception as e:
    print("getVersion failed:", repr(e))
