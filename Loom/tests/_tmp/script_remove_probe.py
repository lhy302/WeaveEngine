# -*- coding: utf-8 -*-
"""script_remove_probe.py — 复现"挂脚本后点✕移除崩溃" (2026-08-15)."""
import os
import sys
import traceback

BASE = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))))
sys.path.insert(0, os.path.join(BASE, 'Loom'))
os.chdir(BASE)
os.environ['LOOM_NO_PARALLEL'] = '1'

import pygame
import editor
from mesh import create_cube

eng = editor.EditorApp(1280, 800)
eng._add_primitive('cube')          # 添加立方体
m = eng._selected()

# 挂一个脚本
from scripts import SCRIPTS
sid = 'rotate'
m.add_script(sid)
print("已挂脚本:", [s.script_id for s in m.scripts])

# 先测直接移除 (非 GUI 路径)
try:
    m.remove_script(0)
    print("直接 remove_script(0): OK, 剩余脚本:", len(m.scripts))
    # 重新挂上用于 GUI 测试
    m.add_script(sid)
except Exception as e:
    print("直接 remove_script 异常:", repr(e))

g = eng.view.gui

def run_frame(mouse_pos, pressed_btn):
    g.active_id = None
    eng.mouse_pos = mouse_pos
    g.begin_frame(mouse_pos, pressed_btn, {1} if pressed_btn else set(), set(), 0)
    g.modal = None
    eng.view._handle_panel_resizers(eng)
    eng.view._draw_toolbar()
    eng.view._draw_hierarchy()
    eng.view._draw_resources()
    eng.view._draw_inspector()
    eng.view._draw_status()
    eng.view._draw_panel_overlay(eng)
    g.end_frame()

# 找检查器中第一个脚本的✕按钮矩形 (insp.srm.0)
# 先跑一帧 (无点击) 看它注册的矩形
run_frame((0, 0), False)
rect = None
for uid, r in g._widget_rects:
    if uid == "insp.srm.0":
        rect = r
        break
print("insp.srm.0 矩形:", rect)
if rect is None:
    print("找不到 insp.srm.0 按钮 (检查器未显示脚本区?)")
else:
    cx, cy = rect[0] + rect[2] // 2, rect[1] + rect[3] // 2
    print("点击位置:", (cx, cy), " (点击前脚本数:", len(m.scripts), ")")
    try:
        run_frame((cx, cy), (1, 0, 0))
        print("点击后脚本数:", len(m.scripts), " active_id:", g.active_id)
        # 下一帧 (无输入, 看移除后重绘是否崩)
        try:
            run_frame((cx, cy), False)
            print("下一帧重绘: OK")
        except Exception:
            print("下一帧重绘异常:")
            traceback.print_exc()
    except Exception:
        print("点击帧异常:")
        traceback.print_exc()

eng._stop_parallel()
pygame.quit()
