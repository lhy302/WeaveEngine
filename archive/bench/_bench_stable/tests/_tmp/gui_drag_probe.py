# -*- coding: utf-8 -*-
"""gui_drag_probe.py — 模拟鼠标输入, 测检查器"第一个条"与右分隔条顶部的命中/拖动 (2026-08-15)."""
import os
import sys

BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, BASE)
os.chdir(BASE)
os.environ['LOOM_NO_PARALLEL'] = '1'

import pygame
import editor

eng = editor.EditorApp(1280, 800)
if eng.models:
    eng.selected_index = 0
for _ in range(3):
    eng.render(1.0 / 60.0)

g = eng.view.gui
lay = eng._layout()
insp = lay[3]
w, h = eng.width, eng.height
rw = insp[2]


def run_frame(mouse_pos, pressed=(0, 0, 0)):
    """跑一帧 GUI, 用给定鼠标位置/按键, 返回 (claimed 的 active_id, click_captured)."""
    # 每帧干净状态 (模拟真实帧边界)
    g.active_id = None
    g._focus = None
    g.pressed = set()
    g.released = set()
    eng.mouse_pos = mouse_pos          # 分隔条用 ctl.mouse_pos, 需同步
    # 手动驱动一帧面板 (仿 view.draw 的面板段, 不开 GL)
    g.begin_frame(mouse_pos, pressed, {1} if pressed[0] else set(),
                  set(), 0)
    g.modal = None
    eng.view._handle_panel_resizers(eng)
    eng.view._draw_toolbar()
    eng.view._draw_hierarchy()
    eng.view._draw_resources()
    eng.view._draw_inspector()
    eng.view._draw_status()
    eng.view._draw_panel_overlay(eng)
    g.end_frame()
    aid = g.active_id
    return aid


# —— 候选: 检查器第一个 drag 条 (位置 X) ——
for label, pos, expect in [
        ("位置X滑块", (1012, 184), "insp.position.X"),
        ("位置Y滑块", (1097, 184), "insp.position.Y"),
        ("名称输入框", (1012, 64), "insp.name"),
        ("右分隔条顶部", (997, 40), "div.r"),
        ("右分隔条中部", (997, 300), "div.r"),
        ("右分隔条下部", (997, 700), "div.r")]:
    aid = run_frame(pos, (1, 0, 0))
    hit = "✓命中" if aid == expect else ("✗未命中(active=%s)" % (aid,))
    print("%-12s @%s -> %s" % (label, pos, hit))

eng._stop_parallel()
pygame.quit()
