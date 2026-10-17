# -*- coding: utf-8 -*-
"""临时探针: 面板分隔条拖动 + 收起 (2026-08-14 晚)."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))))
import pygame

import editor

app = editor.EditorApp(1280, 800)
view = app.view
g = view.gui

for _ in range(3):
    app.render(0.016)
print("[1] 初始: left_w=%d right_w=%d hier_frac=%.2f" %
      (app.panel_left_w, app.panel_right_w, app.panel_hier_frac))

# —— 左分隔条拖动: 按下 -> 移动 -> 松开 ——
lw0 = app.panel_left_w
app.mouse_pos = (lw0, 100)          # 在左分隔条
app.pressed = {1}
app.render(0.016)                    # 认领 div.l
app.pressed = set()
print("  认领后 active_id=%s" % g.active_id)
assert g.active_id == "div.l", "左分隔条未认领!"
app.mouse_pos = (lw0 + 50, 100)     # 右移 50
app.render(0.016)                    # 拖动
print("[2] 左分隔条拖动后 left_w=%d (期望 %d)" % (app.panel_left_w, lw0 + 50))
assert app.panel_left_w == lw0 + 50, "左分隔条拖动未生效!"
app.released = {1}
app.render(0.016)
app.released = set()

# —— 右分隔条拖动 (往右拖 -> 检查器变窄, 分隔条跟鼠标走) ——
_rw0 = app.panel_right_w
_rdx = app._layout()[3][0]           # 右分隔条 x = w - rw
app.mouse_pos = (_rdx, 100)
app.pressed = {1}
app.render(0.016)
app.pressed = set()
assert g.active_id == "div.r", "右分隔条未认领!"
app.mouse_pos = (_rdx + 40, 100)     # 往右拖 40
app.render(0.016)
print("[2b] 右分隔条往右拖后 right_w=%d (期望 %d)" % (app.panel_right_w, _rw0 - 40))
assert app.panel_right_w == _rw0 - 40, "右分隔条方向反了!"
app.released = {1}
app.render(0.016)
app.released = set()

# —— 水平分隔条拖动 (层级/资源) ——
hier = app._layout()[2]
hy = hier[1] + hier[3]
frac0 = app.panel_hier_frac
app.mouse_pos = (100, hy)
app.pressed = {1}
app.render(0.016)
app.pressed = set()
app.mouse_pos = (100, hy + 40)      # 下移 40 -> 层级更高
app.render(0.016)
print("[3] 水平分隔条拖动后 hier_frac=%.3f (期望 > %.3f)" % (app.panel_hier_frac, frac0))
assert app.panel_hier_frac > frac0, "水平分隔条拖动未生效!"
app.released = {1}
app.render(0.016)
app.released = set()

# —— 右侧收起按钮 ——
rw = app._layout()[3][2]
app.mouse_pos = (app.width - rw - 1, 49)   # coll.right 在 (w-rw-9, 40, 18, 18)
app.pressed = {1}
app.render(0.016)
app.pressed = set()
app.released = {1}
app.render(0.016)
app.released = set()
print("[4] 点右收起后 right_collapsed=%s" % app.panel_right_collapsed)
assert app.panel_right_collapsed is True
lay = app._layout()
print("  右收起后检查器宽=%d 视口=%s" % (lay[3][2], lay[4]))
assert lay[3][2] == 24, "右收起后检查器应为薄条!"

# —— 左侧收起 -> 视口更大 -> 展开 ——
lw_now = app._layout()[2][2]
app.mouse_pos = (lw_now - 1, 49)
app.pressed = {1}
app.render(0.016)
app.pressed = set()
app.released = {1}
app.render(0.016)
app.released = set()
print("[5] 点左收起后 left_collapsed=%s" % app.panel_left_collapsed)
assert app.panel_left_collapsed is True
vp_collapsed = app._layout()[4][2]
assert app._layout()[2][2] == 24
app.mouse_pos = (12, 52)             # 展开按钮 (0,40,24,24)
app.pressed = {1}
app.render(0.016)
app.pressed = set()
app.released = {1}
app.render(0.016)
app.released = set()
print("[6] 点展开后 left_collapsed=%s 视口宽 %d -> %d" %
      (app.panel_left_collapsed, vp_collapsed, app._layout()[4][2]))
assert app.panel_left_collapsed is False
assert app._layout()[4][2] < vp_collapsed, "展开后视口应变小 (收起时更大)!"

app._stop_parallel()
pygame.quit()
print("PANEL RESIZER PROBE OK ✅")
