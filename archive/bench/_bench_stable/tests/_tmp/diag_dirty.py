# -*- coding: utf-8 -*-
"""诊断: 场景未修改为何 scene_is_dirty 误判. 子进程跑."""
import sys, os, json
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from editor import EditorApp
import pygame

ed = EditorApp(640, 480)   # 真实窗口 + 种子场景 + __init__ 里已 mark_saved
print("dirty 初始:", ed.scene_is_dirty())
d0 = ed._scene_digest()
for _ in range(5):
    ed._handle_events()
    ed.render(0.016)
print("dirty 5帧后:", ed.scene_is_dirty())
d1 = ed._scene_digest()
if d0 != d1:
    import difflib
    print("digest 变了! 差异:")
    a = json.dumps(json.loads(d0), indent=1, ensure_ascii=False).split('\n')
    b = json.dumps(json.loads(d1), indent=1, ensure_ascii=False).split('\n')
    for line in difflib.unified_diff(a, b, lineterm=''):
        print(line)
else:
    print("digest 稳定 (5 帧内)")
pygame.quit()
