# -*- coding: utf-8 -*-
"""真实运行时 GPU 探针 (2026-08-22, A11): gizmo 恒可见回归.
场景: 立方体@(0,1,0) 选中 + 相机正上方俯视目标中心 → Y 棒 (0.2,0.9,0.2)
从中心向 +Y 纵穿立方体, 投影压缩在视口中心一个点. 修复前: 主 pass 残留
DEPTH_TEST=on 裸调 draw_lines → Y 棒被立方体顶面挡, 中心无绿色; 修复后
(scope enable_only=0) 中心含 Y 棒绿. 用 QWidget.grab 抓视口读像素.
光源指示线/相机朝向线同一修复 (无独立读回断言, 同路径代码已覆盖)."""
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
LOOM_DIR = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, LOOM_DIR)

import plugin_loader
plugin_loader.plugin_dir = lambda program='loom', base=None: os.path.join(LOOM_DIR, 'plugins')

from PySide6.QtWidgets import QApplication

from ui.loom_gui import LoomGUI

FAILS = []


def check(name, cond, extra=""):
    print(("PASS " if cond else "FAIL ") + name + ("  " + str(extra) if extra else ""))
    if not cond:
        FAILS.append(name)


app = QApplication(sys.argv)
win = LoomGUI(scene_path=None, width=1024, height=720)
win.show()
app.processEvents()
e = win.editor

win._cmd_add('cube')          # 立方体@(0,1,0), _add_primitive 自动选中
app.processEvents()
e.camera_target = (0, 1, 0)   # 目标=立方体中心
e.camera_yaw = 0.0
e.camera_pitch = 1.5708       # 正上方俯视
e.camera_distance = 3.0
e.camera_roll = 0.0
e.show_grid = False

# 等待渲染帧 (QTimer 120fps 驱动): 0.6s 足够
for _ in range(30):
    app.processEvents()
    time.sleep(0.02)

img = win.viewport.grab().toImage()
W, H = img.width(), img.height()
cx, cy = W // 2, H // 2
print("viewport %dx%d center=(%d,%d)" % (W, H, cx, cy), flush=True)

found_green = False
found_model = False
for dy in range(-6, 7):
    for dx in range(-6, 7):
        x = max(0, min(W - 1, cx + dx))
        y = max(0, min(H - 1, cy + dy))
        c = img.pixelColor(x, y)
        r, g, b = c.red(), c.green(), c.blue()
        if g > 150 and r < 120 and b < 120:
            found_green = True          # Y 棒绿 (0.2,0.9,0.2)
        if r > 150 and g < 150:         # 立方体顶面 #FF5555 照亮后偏亮红/粉
            found_model = True
check("视口中心含 Y 棒绿 (gizmo 恒可见, 不被立方体顶面遮挡)", found_green,
      "model_present=%s" % found_model)
check("中心附近模型顶面可见 (渲染正常, 不是纯绿/纯背景)", found_model)

win.close()
print("总结果:", "ALL PASS ✅" if not FAILS else "FAIL ❌ " + str(FAILS))
sys.exit(1 if FAILS else 0)
