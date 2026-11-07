# -*- coding: utf-8 -*-
"""
minimal_editor_view.py — MinimalEditorView: Loom 编辑器第二 UI 实现 (极简只读)
UI 模块化 2026-08-13. 用同一个 EditorController, 证明"换 UI 只换实现类".

与 LoomGUI 的区别: 只画 视口网格 + 底部状态文字, 不提供任何编辑面板
(层级/检查器/资源/gizmo 全无), 且吞掉全部点击 (只读). 演示 UI 完全可替换:
启动 Loom.py --ui minimal 即切换到本视图, 引擎/逻辑零改动.

2026-11-06 恢复: 本文件在 487120c「彻底剥离 pygame 窗口」中被连带删除，
但 editor.py:137 与 build_entry.py:77 仍以它为"未注入 view 时的兜底"，
导致 EditorApp(view=None) / --ui minimal / --ui default(无可加载自定义 GUI)
全部 ModuleNotFoundError，连 test_integration / test_eai_real 等真窗口测试
也无法启动。现按当年源码恢复，并按现状适配:
  - 主循环已剥离 pygame: 输入状态直接读 controller (mouse_pos / buttons /
    pressed / released / mouse_wheel)，不再经 gui.GUI 读 pygame 状态。
  - gui.GUI 仍在 (历史保留模块)，继续用它画面板文字，只是不用它收输入。
  - 绘制入口 = controller.draw_lines / controller.grid_geometry (签名未变)。

实现约定 (见 ui/editor_ui.py 的 IEditorView 契约):
  - 只读状态/命令全走 controller; 本文件不 import undo/sceneio 等逻辑细节。
  - 场景模型渲染仍由 controller.render() 完成 (引擎渲染管线不动),
    draw() 只负责"本视图要叠加的显示层" (网格 + 状态文字)。
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
        """读数优先级: gui (begin_frame 每帧灌入, 与当年源码同源) > controller.
        两者都没有时给安全默认 —— 视图可被 __new__ 构造后单测 (契约测试)。"""
        g = getattr(self, 'gui', None)
        ctl = getattr(self, 'ctl', None)

        def _pick(g_name, c_name, default):
            v = getattr(g, g_name, None) if g is not None else None
            if v is None and ctl is not None:
                v = getattr(ctl, c_name, None)
            return default if v is None else v

        return {'mouse_pos': tuple(_pick('mouse_pos', 'mouse_pos', (0, 0))),
                'buttons': tuple(_pick('buttons', 'buttons', (0, 0, 0))),
                'pressed': set(_pick('pressed', 'pressed', ()) or ()),
                'released': set(_pick('released', 'released', ()) or ()),
                'wheel': _pick('wheel', 'mouse_wheel', 0),
                'click_captured': True,   # 只读视图: 吞掉全部点击 (不编辑)
                'focus_id': None}

    def handle_key_event(self, ev):
        return True   # 只读视图: 吞掉全部按键

    def reset_interaction(self):
        pass          # 无跨帧交互, 无需清理

    def draw(self, controller, delta_time):
        ctl = controller
        try:
            ctl.ctx.scissor = None
        except Exception:
            pass
        self._draw_grid(ctl)
        g = self.gui
        g.begin_frame(tuple(getattr(ctl, 'mouse_pos', (0, 0))),
                      tuple(getattr(ctl, 'buttons', (0, 0, 0))),
                      set(getattr(ctl, 'pressed', ()) or ()),
                      set(getattr(ctl, 'released', ()) or ()),
                      getattr(ctl, 'mouse_wheel', 0))
        g.window_begin((0, ctl.height - 26, ctl.width, 26), bg=(0.10, 0.11, 0.13))
        g.label("Minimal 只读视图 (UI 可更换演示) | 对象 %d | 光源 %d | FPS %d" % (
            len(ctl.models), len(ctl.lights), getattr(ctl, 'fps', 0)),
            10, ctl.height - 20, size=13)
        g.window_end()
        g.end_frame()
        # 外部 GL 上下文 (Qt 宿主 / 测试的 standalone ctx) 没有默认 framebuffer,
        # gui.render() 需要显式 target; 有 _external_fb 时传进去 (GLFW 窗口模式
        # 下为 None, 走 detect_framebuffer, 与原实现一致)。
        _tgt = getattr(ctl, '_external_fb', None)
        if _tgt is not None:
            g.render(target=_tgt)
        else:
            g.render()
        if getattr(ctl, 'ui', None) is not None:
            ctl.ui.draw_all(ctl)   # Canvas UI 游戏 HUD 仍画在最上层

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
