# -*- coding: utf-8 -*-
"""一次性探针: 现代 IFileOpenDialog 目录选择 (子进程跑, 父进程 6s 后杀).
A) 纯 COM 创建+配置 (不 Show): 验 vtable 偏移无错
B) 真 Show 阻塞: 6s 后被父进程杀 = 对话框正常打开未崩"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
import ctypes
from ctypes import POINTER, byref, cast, c_void_p, c_uint, c_ulong, c_long

import filedialog

print("== A. COM 创建+配置 (不 Show) ==")
ole32 = ctypes.windll.ole32
shell32 = ctypes.windll.shell32
ole32.CoInitialize(None)
dlg = c_void_p()
hr = ole32.CoCreateInstance(
    byref(filedialog._guid_str("{DC1C5A9C-E88A-4DDE-A5A1-60F82A20AEF7}")), None, 1,
    byref(filedialog._guid_str("{D57C7288-D4AD-4768-BE02-9D969532D960}")), byref(dlg))
print("CoCreateInstance hr=%08x dlg=%s" % (hr, bool(dlg)))
ok = (hr == 0 and dlg)
vtbl = cast(dlg, POINTER(POINTER(c_void_p)))[0]
r = ctypes.CFUNCTYPE(c_long, c_void_p, c_uint)(vtbl[9])(dlg, 0x20)
print("SetOptions(9) hr=%08x" % r)
ok = ok and (r == 0)
r = ctypes.CFUNCTYPE(c_long, c_void_p, ctypes.c_wchar_p)(vtbl[17])(dlg, "选择目录")
print("SetTitle(17) hr=%08x" % r)
item = c_void_p()
hr = shell32.SHCreateItemFromParsingName(
    "C:\\", None, byref(filedialog._guid_str("{43826D1E-E718-42EE-BC55-A1E261C37BFE}")),
    byref(item))
print("SHCreateItemFromParsingName hr=%08x item=%s" % (hr, bool(item)))
if hr == 0 and item:
    r = ctypes.CFUNCTYPE(c_long, c_void_p, c_void_p)(vtbl[12])(dlg, item)
    print("SetFolder(12) hr=%08x" % r)
    ctypes.CFUNCTYPE(c_ulong, c_void_p)(cast(item, POINTER(POINTER(c_void_p)))[0][2])(item)
ctypes.CFUNCTYPE(c_ulong, c_void_p)(vtbl[2])(dlg)
ole32.CoUninitialize()
print("== A " + ("PASS" if ok else "FAIL") + " ==")

print("== B. 真 Show (阻塞, 6s 后被杀 = 正常打开) ==")
import pygame
pygame.init()
win = pygame.display.set_mode((320, 240))
pygame.display.set_caption("dlg_probe")
path = filedialog.choose_directory("探针: 选目录", initial_dir="C:\\")
print("choose_directory 返回:", path)
pygame.quit()
print("== B done ==")
