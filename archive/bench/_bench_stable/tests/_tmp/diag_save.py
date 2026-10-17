# -*- coding: utf-8 -*-
"""诊断: 保存/另存为. 有文件时保存应直接存不弹框. 子进程跑."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
import filedialog as FD
from editor import EditorApp
import pygame

ed = EditorApp(640, 480)   # 种子场景, _scene_path = None
print("初始 _scene_path:", ed._scene_path)

calls = []
def fake_save(*a, **k):
    calls.append('save_file被调')
    return os.path.join(os.environ['TEMP'], "s1.json")
_sv = FD.save_file
FD.save_file = fake_save
try:
    r = ed.save_scene()
    print("无文件保存: 弹框次数=%d 结果=%s _scene_path=%s" % (len(calls), r, ed._scene_path))
    calls.clear()
    r2 = ed.save_scene()
    print("有文件保存: 弹框次数=%d 结果=%s _scene_path=%s" % (len(calls), r2, ed._scene_path))
finally:
    FD.save_file = _sv
pygame.quit()
