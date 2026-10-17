# -*- coding: utf-8 -*-
"""临时探针: 左侧层级+资源面板滚动条 —— 压缩窗口高度, 多对象/多光源/多资产时验证:
  ①面板渲染不崩 ②滚轮能滚到后面的选项 ③底部操作按钮/预览条固定可见."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))))
import pygame

import editor

app = editor.EditorApp(640, 320)   # 压缩高度 (正常 800 -> 320), 面板必然超高
# 造多对象/多光源/多摄像机 (层级超高)
for i in range(30):
    app._add_primitive('cube')
for i in range(8):
    app._add_light('point')
for i in range(4):
    app._add_camera()
# 造资产 (资源超高)
import gui  # noqa
g = app.view.gui
print("[1] 层级列表行数:", len(app._hierarchy_rows()), "光源:", len(app.lights),
      "摄像机:", len(app.cameras))

# 渲染几帧 (面板超高, 应出现滚动条不崩)
for _ in range(3):
    app.render(0.016)
print("[2] 超高面板渲染 3 帧 OK, hier_scroll=%s res_scroll=%s" %
      (app.view._hier_scroll, app.view._res_scroll))

# 模拟滚轮: 鼠标在层级列表区, 发滚轮事件 -> scroll 应变大
# (begin_frame 从 ctl.mouse_wheel/ctl.mouse_pos 读取, 设引擎侧)
hier_rect = app._layout()[2]
app.mouse_pos = (hier_rect[0] + 100, hier_rect[1] + 80)
app.mouse_wheel = -3            # 向上滚 (负数)
app.render(0.016)
app.mouse_wheel = 0
print("[3] 滚轮后 hier_scroll:", app.view._hier_scroll)
assert app.view._hier_scroll > 0, "层级滚轮未生效!"

# 资源面板滚轮
res_rect = app._layout()[5]
app.mouse_pos = (res_rect[0] + 100, res_rect[1] + 40)
app.mouse_wheel = -3
app.render(0.016)
app.mouse_wheel = 0
print("[4] 滚轮后 res_scroll:", app.view._res_scroll)
assert app.view._res_scroll > 0, "资源滚轮未生效!"

# 滚到底后 clamp (不越界)
app.mouse_pos = (hier_rect[0] + 100, hier_rect[1] + 80)
app.mouse_wheel = -9999
app.render(0.016)
app.mouse_wheel = 0
print("[5] 滚到底 hier_scroll:", app.view._hier_scroll)
assert app.view._hier_scroll >= 0, "层级 scroll 越界!"

# —— 操作按钮区独立滚动 (2026-08-14 晚: 操作区独立滚动条) ——
# 计算操作区位置: y0=48, avail=hier_h-48-4, btn_h=min(150, avail//2), by_btn=y0+list_h
y0, avail = 48, hier_rect[3] - 48 - 4
btn_h = max(1, min(150, avail // 2))
by_btn = y0 + (avail - btn_h)
# 鼠标在操作区中部, 滚轮 -> _hier_btn_scroll 应变大
app.mouse_pos = (hier_rect[0] + 100, hier_rect[1] + by_btn + btn_h // 2)
app.mouse_wheel = -3
app.render(0.016)
app.mouse_wheel = 0
print("[6] 操作区滚轮后 _hier_btn_scroll:", app.view._hier_btn_scroll)
assert app.view._hier_btn_scroll > 0, "操作区滚轮未生效!"
# 操作区滚到底 clamp 非负
app.mouse_wheel = -9999
app.render(0.016)
app.mouse_wheel = 0
print("[7] 操作区滚到底:", app.view._hier_btn_scroll)
assert app.view._hier_btn_scroll >= 0, "操作区 scroll 越界!"
# 普通高度下操作区按钮可点: 添加按钮 (在操作区内容 y=20, 滚动后位置)
view = app.view
# 重建一个正常高度 app 验证按钮点击
import pygame as _pg
app2 = editor.EditorApp(1280, 800)
h2 = app2._layout()[2]
a2 = h2[3] - 48 - 4
bh2 = max(1, min(150, a2 // 2))
bb2 = 48 + (a2 - bh2)          # by_btn
btn_y = bb2 + 20 - app2.view._hier_btn_scroll        # 操作区顶 by_btn + 首按钮行 y=20
btn = (h2[0] + 2, h2[1] + 2 + btn_y, 92, 24)
n0 = len(app2.models)
app2.mouse_pos = (btn[0] + 10, btn[1] + 10)
app2.pressed = {1}
app2.render(0.016)
app2.pressed = set()
print("[8] 普通高度添加按钮点击: %d -> %d (btn_y=%d)" % (n0, len(app2.models), btn_y))
assert len(app2.models) == n0 + 1, "操作区按钮点击未生效!"
app2._stop_parallel()
_pg.quit()

app._stop_parallel()
pygame.quit()
print("HIER/RES SCROLL PROBE OK ✅")
