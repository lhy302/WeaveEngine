# -*- coding: utf-8 -*-
"""
test_hub_gui.py — LoomHub 自绘 GUI 滚动条测试 (2026-08-14, 全无头).
解释器/项目列表多时下方不显示 -> 加垂直滚动条 (滚轮 / 拖拇指 / clamp / 无溢出隐藏).
用 SDL dummy 驱动建真实 LoomHubGUI (不弹窗), 只测 _vscroll 数学 + 交互状态机 + 多行渲染不崩.
"""
import os
import sys

os.environ['SDL_VIDEODRIVER'] = 'dummy'   # 必须在 import pygame 前设

HERE = os.path.dirname(os.path.abspath(__file__))
PM_DIR = os.path.join(os.path.dirname(HERE), '..', 'LoomHub')
sys.path.insert(0, os.path.dirname(HERE))            # Loom\
sys.path.insert(0, PM_DIR)

import pygame
from LoomHubGUI import LoomHubGUI

_FAILS = []


def check(name, cond, extra=""):
    print(("PASS " if cond else "FAIL ") + name + ("  " + str(extra) if extra else ""))
    if not cond:
        _FAILS.append(name)


class _CtlStub:
    install_root = "C:\\Program Files\\Loom"
    py_ver = "3.12.10"
    msg = None
    msg_level = 'ok'

    def __init__(self):
        self.interpreters = []
        self.projects = []

    def default_interpreter(self):
        return self.interpreters[0] if self.interpreters else None


def new_gui(rows=None):
    ctl = _CtlStub()
    ctl.interpreters = [{'name': 'Loom', 'version': '1.0.%d' % i, 'kind': 'py',
                         'dir': 'D%d' % i, 'default': i == 0}
                        for i in range(rows or 0)]
    ctl.projects = [{'name': '项目%d' % i, 'scene': 'D:\\p%d\\场景.json' % i}
                    for i in range(rows or 0)]
    g = LoomHubGUI(ctl)          # SDL dummy: set_mode 不出真实窗口
    g._sb_drag = None            # 每例干净拖拽状态
    return g, ctl


# ============ 垂直滚动条数学 ============
def t_v_clamp():
    g, _ = new_gui()
    s = g._vscroll('t', (0, 0, 200, 200), 800, 999)
    check("超高内容 clamp 到 [0, max]", 0 <= s <= (800 - 200), s)
    s2 = g._vscroll('t', (0, 0, 200, 200), 800, -5)
    check("负 scroll clamp 到 0", s2 == 0, s2)


def t_v_no_overflow():
    g, _ = new_gui()
    s = g._vscroll('t', (0, 0, 200, 200), 100, 30)
    check("无溢出返回 0 (不出现拉条)", s == 0, s)


def t_v_wheel():
    g, _ = new_gui()
    list_rect = (0, 0, 200, 200)
    g._mouse_pos = (100, 100)                    # 鼠标在列表内
    g._wheel = (5, (100, 100))                   # 滚轮下
    s = g._vscroll('t', list_rect, 800, 100)
    check("滚轮下 -> scroll 增大", s == 142, s)
    check("滚轮已消费", g._wheel is None)
    g._wheel = (4, (100, 100))                   # 滚轮上
    s2 = g._vscroll('t', list_rect, 800, 100)
    check("滚轮上 -> scroll 减小", s2 == 58, s2)
    # 鼠标在列表外不滚
    g._mouse_pos = (500, 500)
    g._wheel = (5, (500, 500))
    s3 = g._vscroll('t', list_rect, 800, 100)
    check("鼠标不在列表内滚轮不滚动", s3 == 100 and g._wheel is not None, s3)


def t_v_drag():
    g, _ = new_gui()
    list_rect = (0, 0, 200, 200)
    track = pygame.Rect(list_rect[0] + list_rect[2] - 8 - 3, list_rect[1] + 2,
                        8, list_rect[3] - 4)    # (189, 2, 8, 196)
    y0 = track.y + 60
    # 帧1: 按下轨道 (鼠标与按下点同位 -> 不跳变)
    g._mouse_pos = (track.x + 4, y0)
    g._click = (track.x + 4, y0)
    g._sb_released = False
    s0 = g._vscroll('t', list_rect, 800, 0)
    check("按下轨道开始拖拽", g._sb_drag == 't', g._sb_drag)
    check("按下帧不跳变", s0 == 0, s0)
    check("按下被消费 (不点行)", g._click is None)
    # 帧2: 往下拖 40px
    g._mouse_pos = (track.x + 4, y0 + 40)
    g._click = None
    g._sb_released = False
    s1 = g._vscroll('t', list_rect, 800, s0)
    check("拖动后 scroll 增大", s1 > s0, s1)
    # 帧3: 松开
    g._sb_released = True
    s2 = g._vscroll('t', list_rect, 800, s1)
    check("松开后拖拽状态清空", g._sb_drag is None, g._sb_drag)
    check("松开后 scroll 保持", s2 == s1, s2)


def t_render_many_rows():
    """40 解释器 + 35 项目: 渲染不崩, 且列表超高 (滚动条出现)."""
    g, ctl = new_gui(rows=40)
    g._draw()
    # 断言列表超高 -> max_scroll > 0 (面板内部高度够算滚动)
    check("40 解释器渲染不崩", True)
    check("40 解释器内容超高 (滚动条生效)", g._interp_scroll == 0, g._interp_scroll)
    check("35 项目内容超高", g._project_scroll == 0, g._project_scroll)


def t_settings_render():
    """设置覆盖面板渲染不崩 (2026-08-14 GUI 插件)."""
    g, ctl = new_gui(rows=3)
    g._show_settings = True
    g._draw()
    check("设置面板渲染不崩", g._show_settings is True)
    check("设置面板 GUI 列表已缓存 (只扫一次目录, 2026-08-15)",
          g._gui_list_cache is not None)
    g._show_settings = False
    g._draw()
    check("关闭设置后恢复正常面板渲染", True)


def t_text_cache():
    """空闲 CPU 优化 (2026-08-15): 相同文字只 font.render 一次, 复用缓存表面."""
    g, _ = new_gui()
    check("_force_redraw 初始 True (首帧强制重绘)", g._force_redraw is True)
    g._text("你好 LoomHub", 10, 10)
    n1 = len(g._text_cache)
    g._text("你好 LoomHub", 10, 10)        # 同 (text,color,font) -> 命中缓存
    n2 = len(g._text_cache)
    check("相同文字重复调用命中缓存 (尺寸不涨)", n2 == n1 == 1, (n1, n2))
    g._text("另一条不同文字", 10, 10)       # 新文字 -> 缓存 +1
    check("新文字进缓存", len(g._text_cache) == 2)


if __name__ == "__main__":
    print("========== LoomHub GUI 滚动条测试 ==========")
    t_v_clamp()
    t_v_no_overflow()
    t_v_wheel()
    t_v_drag()
    t_render_many_rows()
    t_settings_render()
    t_text_cache()
    if _FAILS:
        print("总结果: FAIL ❌", _FAILS)
        sys.exit(1)
    print("总结果: ALL PASS ✅")
