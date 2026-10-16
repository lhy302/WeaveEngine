# -*- coding: utf-8 -*-
"""临时探针: 最终真机综合冒烟 (并行开 + 网格 + 设置面板新开关 + 播放 + 退出)."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))))
import pygame

import editor

app = editor.EditorApp(800, 600)
print("[1] show_grid=%s parallel_enable=%s runner=%s" %
      (app.show_grid, app.parallel_enable,
       "on" if app._script_runner else "off"))

# 网格几何 (真实控制器)
out = app.grid_geometry()
assert out is not None, "grid_geometry None"
verts, cols = out
print("[2] 网格顶点 %d (线数 %d), 颜色通道 %d" %
      (len(verts), len(verts) // 2, cols.shape[1]))
assert cols.shape[1] == 4 and len(verts) > 0

# 渲染几帧 (默认网格开)
for _ in range(5):
    app.render(0.016)
print("[3] 网格开渲染 5 帧 OK")

# 设置面板 (含新开关) 渲染
app._show_settings = True
app.view.draw(app, 0.016)
print("[4] 设置面板渲染 OK")

# 关网格再渲染
app.show_grid = False
for _ in range(3):
    app.render(0.016)
print("[5] 网格关渲染 OK")

# 播放 + 脚本线程 (种子模型挂 rotate)
m = app.models[0]
m.add_script('rotate', {})
app.toggle_play()
for _ in range(5):
    app.render(0.016)
print("[6] 播放 5 帧 rotation.y=%.4f" % m.rotation.y)
assert abs(m.rotation.y) > 0.001, "脚本未跑!"
app.toggle_play()

app._stop_parallel()
pygame.quit()
print("FINAL PROBE OK ✅")
