# -*- coding: utf-8 -*-
"""ui_probe.py — Canvas UI 真实窗口探针 (2026-10-18, 替换 M33 RuntimeUI 探针)

EditorApp 播放期挂 UI 脚本 (Canvas 元素树), 渲染确认不崩 + 元素被绘制.
"""
import sys, os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))))
os.chdir(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import pygame
import editor
import scripts
import loom_ui


@scripts.register
class HudDemo(scripts.Script):
    script_id = '_hud_demo'
    name = 'HUD演示'

    def on_start(self):
        e = self.engine
        canvas = e.ui.default_canvas()
        canvas.root.add_child(loom_ui.Text(
            name='score', rect=(20, 20, 300, 26),
            text='分数: 100', font_size=26))
        canvas.root.add_child(loom_ui.Text(
            name='life', rect=(20, 52, 300, 24),
            text='生命: 3', font_size=18))
        canvas.root.add_child(loom_ui.Panel(
            name='bar_bg', rect=(20, 84, 200, 18),
            bg_color=(40, 44, 54, 255)))
        canvas.root.add_child(loom_ui.Panel(
            name='bar_fill', rect=(20, 84, 140, 18),
            bg_color=(80, 220, 120, 255)))

    def update(self, dt):
        pass


e = editor.EditorApp(640, 480)
e.clear_scene()
demo = e.add_model(__import__('mesh').create_cube(1.0),
                   editor.Point3D(0, 0, 0),
                   editor.Point3D(0, 0, 0), name="演示")
demo.add_script('_hud_demo')
e.toggle_play()
for _ in range(8):
    e.render(0.016)
canvas = e.ui.default_canvas()
n_children = len(canvas.root.children)
print("播放期 Canvas 元素数 =", n_children)
assert n_children >= 4, "元素应已建立"
e.toggle_play()
print("退出播放不崩")
import pygame as _p
_p.quit()
print("RESULT: PASS (Canvas UI 绘制不崩)")
