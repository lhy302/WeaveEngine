# -*- coding: utf-8 -*-
"""
test_scrollbar.py — 滚动条组件测试 (2026-08-14, 全无头).
gui.py 新增 scrollbar_v / scrollbar_h (面板内容超高/超宽时开放拉条):
  滚轮滚动 / 拖拇指拖动 / scroll 范围 clamp / 无溢出不出现 / 拉条消失自动清 active.
用 GUI.__new__(GUI) 绕过 GL 上下文初始化, 手动铺帧状态, 只测滚动条数学与交互状态机.
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from gui import GUI

_FAILS = []


def check(name, cond, extra=""):
    print(("PASS " if cond else "FAIL ") + name + ("  " + str(extra) if extra else ""))
    if not cond:
        _FAILS.append(name)


class _FakeEng:
    mouse_press_pos = {}


def new_gui():
    """绕过 __init__ (需要 GL ctx), 手工铺滚动条所需字段."""
    g = GUI.__new__(GUI)
    g.engine = _FakeEng()
    g._widget_rects = []
    g._panel_rects = []
    g._draw_cmds = []
    g._scissor = None
    g._scissor_stack = []
    g._sb_drag = {}
    g._hsb_drag = {}
    g._drag = {}
    g._input = {}
    g._focus = None
    g.modal = None
    g.active_id = None
    g.hot_id = None
    g.mouse_pos = (0, 0)
    g.pressed = set()
    g.released = set()
    g.wheel = 0
    g.click_captured = False
    g.s_col_btn = (0.24, 0.25, 0.30)
    g.s_col_btn_active = (0.42, 0.45, 0.55)
    return g


PANEL = (100, 100, 280, 300)    # 面板可视区 (宽 280 同检查器)
CONTENT_H = 900                  # 内容超高 -> 必然溢出


# ============ 垂直滚动条 ============
def t_v_clamp():
    g = new_gui()
    g.begin_frame((200, 200), (0, 0, 0), set(), set(), 0)
    s = g.scrollbar_v("insp", PANEL, CONTENT_H, 999)
    check("超高内容 clamp 到 [0, max]", 0 < s <= (CONTENT_H - (PANEL[3] - 4)), s)
    s2 = g.scrollbar_v("insp", PANEL, CONTENT_H, -50)
    check("负 scroll clamp 到 0", s2 == 0.0, s2)
    g.end_frame()


def t_v_wheel():
    g = new_gui()
    g.begin_frame((200, 200), (0, 0, 0), set(), set(), 1)    # 滚轮上 (+1)
    s = g.scrollbar_v("insp", PANEL, CONTENT_H, 100)
    check("滚轮上滚 -> scroll 减小 (向起始)", s < 100, s)
    g.begin_frame((200, 200), (0, 0, 0), set(), set(), -1)   # 滚轮下 (-1)
    s2 = g.scrollbar_v("insp", PANEL, CONTENT_H, 100)
    check("滚轮下滚 -> scroll 增大 (看下方)", s2 > 100, s2)
    g.end_frame()


def t_v_wheel_outside():
    g = new_gui()
    g.begin_frame((10, 10), (0, 0, 0), set(), set(), 1)      # 鼠标在面板外
    s = g.scrollbar_v("insp", PANEL, CONTENT_H, 100)
    check("鼠标不在面板内滚轮不滚动", s == 100, s)
    g.end_frame()


def t_v_no_overflow():
    g = new_gui()
    g.begin_frame((200, 200), (0, 0, 0), set(), set(), 1)
    s = g.scrollbar_v("insp", PANEL, 200, 50)                # 内容不高
    check("内容不高 -> scroll 归 0 (不出现拉条)", s == 0.0, s)
    check("内容不高 -> 不注册轨道 (无控件)", len(g._widget_rects) == 0,
          g._widget_rects)
    g.end_frame()


def t_v_drag():
    g = new_gui()
    track_x = PANEL[0] + PANEL[2] - 5                         # 轨道内 x
    # 帧1: 按下轨道
    g.begin_frame((track_x, PANEL[1] + 20), (1, 0, 0), {1}, set(), 0)
    s0 = g.scrollbar_v("insp", PANEL, CONTENT_H, 0)
    check("按下轨道后 active 认领", g.active_id == "sb.insp", g.active_id)
    check("按下帧不跳变", s0 == 0.0, s0)
    check("按下被 GUI 吞掉 (防误入视口)", g.click_captured is True)
    g.end_frame()
    # 帧2: 往下拖 30px
    g.begin_frame((track_x, PANEL[1] + 50), (1, 0, 0), set(), set(), 0)
    s1 = g.scrollbar_v("insp", PANEL, CONTENT_H, s0)
    check("拖动后 scroll 增大", s1 > 0.0, s1)
    g.end_frame()
    # 帧3: 松开
    g.begin_frame((track_x, PANEL[1] + 50), (0, 0, 0), set(), {1}, 0)
    g.scrollbar_v("insp", PANEL, CONTENT_H, s1)
    check("释放后 active 清空", g.active_id is None, g.active_id)
    check("释放后拖拽状态清空", not g._sb_drag, g._sb_drag)
    g.end_frame()


def t_v_disappear_cleanup():
    """拉条按下后内容变短 -> 拉条消失 -> 释放事件无人处理, end_frame 自动清 active."""
    g = new_gui()
    track_x = PANEL[0] + PANEL[2] - 5
    g.begin_frame((track_x, PANEL[1] + 20), (1, 0, 0), {1}, set(), 0)
    g.scrollbar_v("insp", PANEL, CONTENT_H, 0)
    g.end_frame()
    check("拉条按下 active", g.active_id == "sb.insp", g.active_id)
    g.begin_frame((200, 200), (0, 0, 0), set(), {1}, 0)
    s = g.scrollbar_v("insp", PANEL, 100, 0)                  # 内容变短 -> 返回 0 不注册
    g.end_frame()
    check("内容变短返回 0", s == 0.0, s)
    check("拉条消失 -> end_frame 自动清 active", g.active_id is None, g.active_id)


# ============ 水平滚动条 ============
def t_h_clamp_wheel():
    g = new_gui()
    panel = (0, 0, 1208, 36)                                  # 工具栏可视区
    content_w = 1600                                          # 内容超宽
    g.begin_frame((100, 20), (0, 0, 0), set(), set(), 1)
    s = g.scrollbar_h("tool", panel, content_w, 999)
    check("水平超高 clamp 到 [0, max]", 0 < s <= (content_w - (panel[2] - 4)), s)
    g.begin_frame((100, 20), (0, 0, 0), set(), set(), -1)
    s2 = g.scrollbar_h("tool", panel, content_w, 100)
    check("水平滚轮下滚 -> scroll 增大", s2 > 100, s2)
    g.end_frame()


def t_h_drag():
    g = new_gui()
    panel = (0, 0, 1208, 36)
    content_w = 1600
    ty = panel[1] + panel[3] - 2                               # 底部轨道 y
    g.begin_frame((100, ty), (1, 0, 0), {1}, set(), 0)
    s0 = g.scrollbar_h("tool", panel, content_w, 0)
    check("水平按下轨道后 active", g.active_id == "hsb.tool", g.active_id)
    check("水平按下帧不跳变", s0 == 0.0, s0)
    g.end_frame()
    g.begin_frame((200, ty), (1, 0, 0), set(), set(), 0)       # 右拖 100px
    s1 = g.scrollbar_h("tool", panel, content_w, s0)
    check("水平拖动后 scroll 增大", s1 > 0.0, s1)
    g.end_frame()
    g.begin_frame((200, ty), (0, 0, 0), set(), {1}, 0)
    g.scrollbar_h("tool", panel, content_w, s1)
    check("水平释放后 active 清空", g.active_id is None, g.active_id)
    g.end_frame()


def t_h_no_overflow():
    g = new_gui()
    panel = (0, 0, 1208, 36)
    g.begin_frame((100, 20), (0, 0, 0), set(), set(), 1)
    s = g.scrollbar_h("tool", panel, 1000, 50)                 # 内容不超宽
    check("内容不超宽 -> scroll 归 0", s == 0.0, s)
    g.end_frame()


# ============ 裁剪区子栈 (工具栏滚动内容区用) ============
def t_h_toolbar_drag_stable():
    """回归 (2026-08-14): 工具栏 content_w 若随 scroll 变 (旧 x+60, x=8-scroll) 长拖会
    震荡; 用未滚动宽度 (x+scroll+60 恒定) 则长拖单调不回跳."""
    panel = (0, 0, 1208, 36)
    ty = panel[1] + panel[3] - 2
    CONTENT = 1600
    # 新公式: content_w = x+scroll+60 恒定
    cws = [(8 - sc) + sc + 60 for sc in (0, 50, 200)]
    check("content_w = x+scroll+60 恒定不随 scroll 变", len(set(cws)) == 1, cws)
    # 新行为: 固定内容宽, 长距离右拖 scroll 单调不减 (不震荡)
    g = new_gui()
    g.begin_frame((100, ty), (1, 0, 0), {1}, set(), 0)
    s = g.scrollbar_h("tool", panel, CONTENT, 0)
    g.end_frame()
    prev, stable, mx = s, True, 100
    for _ in range(25):
        mx += 60
        g.begin_frame((mx, ty), (1, 0, 0), set(), set(), 0)
        s = g.scrollbar_h("tool", panel, CONTENT, prev)
        g.end_frame()
        if s < prev - 1e-6:
            stable = False
        prev = s
    check("固定内容宽长拖 scroll 单调不减 (不震荡)", stable, "scroll=%.1f" % prev)
    # 旧公式复现: content_w 随 scroll 缩小 -> max_scroll 缩 + clamp 回跳 = 震荡
    g = new_gui()
    g.begin_frame((100, ty), (1, 0, 0), {1}, set(), 0)
    s = g.scrollbar_h("tool", panel, CONTENT, 0)
    g.end_frame()
    prev, osc, mx = s, False, 100
    for _ in range(25):
        mx += 60
        cw_old = max(200, CONTENT - prev)      # 旧公式 content_w = (8-scroll)+增量+60 = 常量-scroll
        g.begin_frame((mx, ty), (1, 0, 0), set(), set(), 0)
        s = g.scrollbar_h("tool", panel, cw_old, prev)
        g.end_frame()
        if s < prev - 1e-6:
            osc = True
        prev = s
    check("旧公式(content_w 随 scroll 缩)复现回跳震荡", osc, "scroll=%.1f" % prev)


def t_scissor_stack():
    g = new_gui()
    g.push_scissor((0, 2, 100, 32))
    check("push 后 scissor 生效", g._scissor == (0, 2, 100, 32), g._scissor)
    g.push_scissor((5, 5, 50, 20))
    check("嵌套 push", g._scissor == (5, 5, 50, 20), g._scissor)
    g.pop_scissor()
    check("pop 回到外层", g._scissor == (0, 2, 100, 32), g._scissor)
    g.pop_scissor()
    check("pop 回 None", g._scissor is None, g._scissor)
    g.pop_scissor()
    check("空栈再 pop 不崩", True)


def t_draw_cmds_registered():
    """滚动条可见时轨道+拇指都进绘制命令, 且落在 window_begin 真实裁剪区内."""
    g = new_gui()
    clip = (PANEL[0] + 2, PANEL[1] + 2, PANEL[2] - 4, PANEL[3] - 4)   # window_begin 的裁剪区
    g.push_scissor(clip)
    g.begin_frame((200, 200), (0, 0, 0), set(), set(), 0)
    g.scrollbar_v("insp", PANEL, CONTENT_H, 0)
    g.end_frame()
    rects = [c[2] for c in g._draw_cmds if c[1] == 'rect']
    check("滚动条绘制轨道+拇指 (2 个矩形)", len(rects) == 2, len(rects))
    cx0, cy0, cw, ch = clip
    check("滚动条矩形都在面板裁剪区内", all(
        r[0] >= cx0 and r[0] + r[2] <= cx0 + cw
        and r[1] >= cy0 and r[1] + r[3] <= cy0 + ch
        for r in rects), rects)


if __name__ == "__main__":
    print("========== Loom GUI 滚动条测试 ==========")
    t_v_clamp()
    t_v_wheel()
    t_v_wheel_outside()
    t_v_no_overflow()
    t_v_drag()
    t_v_disappear_cleanup()
    t_h_clamp_wheel()
    t_h_drag()
    t_h_no_overflow()
    t_h_toolbar_drag_stable()
    t_scissor_stack()
    t_draw_cmds_registered()
    if _FAILS:
        print("总结果: FAIL ❌", _FAILS)
        sys.exit(1)
    print("总结果: ALL PASS ✅")
