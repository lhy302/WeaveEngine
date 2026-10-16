# -*- coding: utf-8 -*-
"""端到端: 真实按钮路径验证 保存/另存为 发出的指令. 子进程跑."""
import sys, os, tempfile
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
import filedialog as FD
from editor import EditorApp
import pygame

ed = EditorApp(640, 480)
g = ed.view.gui
save_btn = (124, 5, 46, 26)     # 保存
saveas_btn = (176, 5, 54, 26)   # 另存为
calls = []


def fake_save(*a, **k):
    calls.append('save_file被调')
    return os.path.join(tempfile.mkdtemp(), "s.json")


def click(rect):
    g.begin_frame((rect[0] + 5, 16), (1, 0, 0), {1}, set(), 0)
    ed.view._draw_toolbar()
    g.end_frame()
    g.begin_frame((rect[0] + 5, 16), (0, 0, 0), set(), {1}, 0)
    ed.view._draw_toolbar()
    g.end_frame()


_sv = FD.save_file
FD.save_file = fake_save
try:
    print("初始 _scene_path:", ed._scene_path)
    click(save_btn)
    print("点[保存] 无文件: 弹框=%d _scene_path=%s" % (len(calls), ed._scene_path))
    calls.clear()
    click(save_btn)
    print("点[保存] 有文件: 弹框=%d (期望 0) _scene_path=%s" % (len(calls), ed._scene_path))
    calls.clear()
    click(saveas_btn)
    print("点[另存为]: 弹框=%d (期望 1) _scene_path=%s" % (len(calls), ed._scene_path))
finally:
    FD.save_file = _sv
pygame.quit()
