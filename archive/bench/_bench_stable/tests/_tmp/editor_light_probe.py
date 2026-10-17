# -*- coding: utf-8 -*-
"""编辑器平行光冒烟: 真实窗口, 加平行光(3角度) -> 选中渲染检查器 -> 拖改朝向 -> 渲染不崩.
运行: py -3.12 "Loom\tests\_tmp\editor_light_probe.py" (子进程+超时)"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))))
os.chdir(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
import pygame
import numpy as np
import editor
from engine import wrap_deg

e = editor.EditorApp(640, 480)
lt = e.add_light('directional', azimuth=0, elevation=-45, roll=10, shadow=True)
# 选中光源 -> 检查器渲染 (3 角度拖拽)
e.selected_light_index = len(e.lights) - 1
for _ in range(3):
    e.render(0.016)
print("初始: az=%.1f el=%.1f roll=%.1f dir=%s" % (
    lt.azimuth, lt.elevation, lt.roll, tuple(round(x, 2) for x in lt.direction)))

# 模拟检查器拖拽: 朝向往 +380 拖 (应环绕回 20), 俯仰往 190 拖 (应环绕回 -170)
lt.azimuth = wrap_deg(360 + 20, 0, 360)
lt.elevation = wrap_deg(190, -180, 180)
lt.roll = wrap_deg(-200, -180, 180)
print("环绕后: az=%.1f el=%.1f roll=%.1f dir=%s" % (
    lt.azimuth, lt.elevation, lt.roll, tuple(round(x, 2) for x in lt.direction)))
for _ in range(3):
    e.render(0.016)   # 改向后再渲染, 不崩

ok = (abs(lt.azimuth - 20) < 0.1 and abs(lt.elevation - (-170)) < 0.1
      and abs(lt.roll - 160) < 0.1)
print("RESULT:", "PASS" if ok else "FAIL", " az=%.1f el=%.1f roll=%.1f" % (
    lt.azimuth, lt.elevation, lt.roll))
pygame.quit()
