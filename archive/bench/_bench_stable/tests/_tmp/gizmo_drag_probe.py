# -*- coding: utf-8 -*-
"""gizmo_drag_probe.py — 验证拖动卡顿修复: 面板 pass 跳过时 gizmo 拖动读新鲜鼠标 (2026-08-15).

模拟真实拖动: 加立方体(选中), 置 gizmo_drag 平移状态, 每帧移动鼠标; 无新按键/滚轮
(had_input=False) + gui_dirty=False + 长心跳 -> 面板 pass 被跳过. 修前 g.mouse_pos
只在 begin_frame 更新 -> 拖动用过期鼠标位置, 物体 0.5s 才跳一次 (卡顿). 修后每帧跟手.
"""
import os
import sys

BASE = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))))
sys.path.insert(0, os.path.join(BASE, 'Loom'))
os.chdir(BASE)
os.environ['LOOM_NO_PARALLEL'] = '1'

import numpy as np
import pygame
import editor

eng = editor.EditorApp(1280, 800)
eng._add_primitive('cube')
t = eng._selected()                  # _add_primitive 已 _select_model 选中新立方体
eng.gizmo_mode = 'translate'
eng.gizmo_drag = ('X', np.array([t.position.x, t.position.y, t.position.z], dtype=np.float64),
                  (t.position.x, t.position.y, t.position.z))
eng.buttons = (1, 0, 0)
eng.pressed = set()
eng.released = set()
# 模拟拖动期面板 pass 被跳过: 无 dirty/输入 + 长心跳 (拖动卡顿场景)
eng.view.gui.gui_dirty = False
eng.view._gui_heartbeat = 99.0

pos_history = []
for frame in range(30):
    eng.mouse_pos = (640 + frame * 2, 400)   # 鼠标沿 +X 移动
    eng.render(1.0 / 120.0)                  # render 内 _update_gizmo 应用拖动
    pos_history.append((t.position.x, t.position.y, t.position.z))

# 断言: 物体 X 每帧跟随鼠标递增 (面板跳过时也跟手)
dx = [pos_history[i][0] - pos_history[i - 1][0] for i in range(1, len(pos_history))]
moving = sum(1 for d in dx if abs(d) > 1e-6)
print("X 位置变化的帧数: %d / %d" % (moving, len(pos_history) - 1))
print("X 位移: %.3f -> %.3f" % (pos_history[0][0], pos_history[-1][0]))
ok = moving >= 25          # 核心: 面板跳过时物体每帧都跟随鼠标移动 (修前 0 帧移动)
print("结论: 拖动跟手 =", "PASS ✅" if ok else "FAIL ❌ (卡顿)")

eng._stop_parallel()
pygame.quit()
sys.exit(0 if ok else 1)
