# -*- coding: utf-8 -*-
# 探针: 运行时 UI 真实窗口验证. EditorApp 播放期挂自定义 UI 脚本
# (声明 文字/进度条/按钮), 渲染确认不崩 + UI 命令被绘制.
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))))
os.chdir(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
import pygame
import editor
import scripts

@scripts.register
class HudDemo(scripts.Script):
    script_id = '_hud_demo'
    name = 'HUD演示'
    def update(self, dt):
        ui = self.engine.ui
        ui.text('分数: 100', 20, 20, size=26)
        ui.text('生命: 3', 20, 52)
        ui.bar((20, 84, 200, 18), 0.7)
        ui.button('restart', (20, 116, 130, 34), '重新开始')

e = editor.EditorApp(640, 480)
e.clear_scene()
demo = e.add_model(__import__('mesh').create_cube(1.0), editor.Point3D(0, 0, 0),
                   editor.Point3D(0, 0, 0), name="演示")
demo.add_script('_hud_demo')
e.toggle_play()
for _ in range(8):
    e.render(0.016)
cmd_n = len(e.ui.cmds) if e.ui is not None else -1
print("播放期 UI 命令数 =", cmd_n, " (脚本 update 已声明, draw 后应清 0)")
e.toggle_play()
print("退出播放不崩")
import pygame as _p; _p.quit()
print("RESULT: PASS (运行时 UI 绘制不崩)")
