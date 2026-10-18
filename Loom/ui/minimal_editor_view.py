# -*- coding: utf-8 -*-
"""
minimal_editor_view.py — MinimalEditorView: Loom 编辑器第二 UI 实现 (极简只读)
UI 模块化 2026-08-13. 用同一个 EditorController, 证明"换 UI 只换实现类".

与旧版GUI 的区别: 只画 视口网格 + 底部状态文字, 不提供任何编辑面板
(层级/检查器/资源/gizmo 全无), 且吞掉全部点击 (只读). 演示 UI 完全可替换:
启动 Loom.py --ui minimal 即切换到本视图, 引擎/逻辑零改动.

实现约定 (见 ui/editor_ui.py 的 IEditorView 契约):
  - 只读状态/命令全走 controller; 本文件不 import undo/sceneio 等逻辑细节.
  - 场景模型渲染仍由 controller.render() 完成 (引擎渲染管线不动),
    draw() 只负责"本视图要叠加的显示层" (网格 + 状态文字).
"""
import moderngl

from gui import GUI
from .editor_ui import IEditorView


class MinimalEditorView(IEditorView):
    def __init__(self, controller=None):
        self.ctl = controller
        self.gui = None
        if controller is not None:
            self.attach(controller)

    def attach(self, controller):
        self.ctl = controller
        if self.gui is None:
            self.gui = GUI(controller)

    def input_state(self):
        g = self.gui
        return {'mouse_pos': g.mouse_pos, 'buttons': g.buttons,
                'pressed': g.pressed, 'released': g.released,
                'wheel': g.wheel,
                'click_captured': True,   # 只读视图: 吞掉全部点击 (不编辑)
                'focus_id': None}

    def handle_key_event(self, ev):
        return True   # 只读视图: 吞掉全部按键

    def reset_interaction(self):
        pass          # 无跨帧交互, 无需清理

    def draw(self, controller, delta_time):
        ctl = controller
        ctl.ctx.scissor = None
        self._draw_grid(ctl)
        g = self.gui
        g.begin_frame(ctl.mouse_pos, ctl.buttons, ctl.pressed,
                      ctl.released, ctl.mouse_wheel)
        g.window_begin((0, ctl.height - 26, ctl.width, 26), bg=(0.10, 0.11, 0.13))
        g.label("Minimal 只读视图 (UI 可更换演示) | 对象 %d | 光源 %d | FPS %d" % (
            len(ctl.models), len(ctl.lights), ctl.fps), 10, ctl.height - 20, size=13)
        g.window_end()
        g.end_frame()
        g.render()
        if getattr(ctl, 'ui', None) is not None:
            ctl.ui.draw_all(ctl)   # 2026-10-18: Canvas UI 游戏 HUD 仍画在最上层

    def _draw_grid(self, ctl):
        """无限网格 (2026-08-14): 跟随相机, 远处淡出, 可 show_grid 开关."""
        if not getattr(ctl, 'show_grid', True):
            return
        out = ctl.grid_geometry()
        if out is None:
            return
        verts, cols = out
        with ctl.ctx.scope(framebuffer=ctl.ctx.detect_framebuffer(),
                           enable_only=moderngl.DEPTH_TEST | moderngl.BLEND):
            ctl.draw_lines(verts, cols)
