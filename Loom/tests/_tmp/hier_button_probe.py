# -*- coding: utf-8 -*-
"""临时探针: 普通窗口高度下层级底部"添加"按钮仍可点击 (新固定底部布局未破坏按钮)."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))))
import pygame

import editor

app = editor.EditorApp(1280, 800)
hier = app._layout()[2]
# 按新布局推算 "添加" 按钮位置
BTN_H, MIN_LIST, y0 = 130, 48, 48
y1 = min(hier[3] - 4, max(y0 + MIN_LIST, hier[3] - BTN_H))
yb = y1 + 8 + 20                                # -- 操作 -- label 之后
btn = (hier[0] + 2, hier[1] + 2 + yb, 92, 24)   # by = rect[1]+2
print("层级面板高 %d, 列表底 y1=%d, 添加按钮 rect=%s (面板内=%s)" %
      (hier[3], y1, btn, hier[1] + 2 <= btn[1] and btn[1] + 24 <= hier[1] + hier[3] - 2))

n0 = len(app.models)
g = app.view.gui
app.mouse_pos = (btn[0] + 10, btn[1] + 10)
app.pressed = {1}
app.render(0.016)
app.pressed = set()
print("点击添加前对象数 %d -> 后 %d" % (n0, len(app.models)))
assert len(app.models) == n0 + 1, "添加按钮未生效!"
app._stop_parallel()
pygame.quit()
print("HIER BUTTON PROBE OK ✅")
