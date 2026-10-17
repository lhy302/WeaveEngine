# -*- coding: utf-8 -*-
"""探针: drag_float 右键进入输入模式 (键入数字/Enter提交/Esc取消) + 左键拖动不受影响.
运行: py -3.12 "Loom\tests\_tmp\gui_input_probe.py" (子进程+超时)"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))))
import pygame
import editor

e = editor.EditorApp(400, 300)
g = e.gui
R = (10, 10, 100, 22)
ok = True

def check(name, cond, detail=""):
    global ok
    print(("PASS " if cond else "FAIL ") + name + ("  " + detail if detail else ""))
    if not cond:
        ok = False

def key(unicode=None, k=None):
    return pygame.event.Event(pygame.KEYDOWN, key=k, unicode=unicode)

def frame(pressed, released, pos=(20, 20)):
    g.begin_frame(pos, (1, 0, 0), pressed, released, 0)
    v, a = g.drag_float("t1", R, 5.0, speed=0.1, fmt='%.2f')
    g.end_frame()
    return v, a

# —— 左键拖动仍正常 (位移30 * 0.1 = +3) ——
frame([1], [], (20, 20))
v, a = frame([], [1], (50, 22))
check("左键拖动正常 (位移30->+3)", abs(v - 8.0) < 1e-9 and not a, "v=%s" % v)
check("左键拖动不进入输入模式", g._focus is None)

# —— 右键进入输入模式 + 键入 + Enter 提交 ——
v, a = frame([3], [])                              # 右键按下 -> 输入模式
check("右键进入输入模式", g._focus == "t1" and "t1" in g._num_focus,
      "focus=%s num=%s" % (g._focus, g._num_focus))
for _ in range(5):                                  # 输入过程每帧 render 调 drag_float
    v, a = frame([], [])
check("输入模式持续多帧 _focus 保持 (不被 end_frame 误清)", g._focus == "t1",
      "focus=%s" % g._focus)
g.handle_key_event(key("4")); g.handle_key_event(key("2"))    # 输入 42
check("键入缓冲", g._input.get("t1") == "42", g._input.get("t1"))
g.handle_key_event(key(k=pygame.K_RETURN))
v, a = frame([], [])
check("Enter 提交返回新值", abs(v - 42.0) < 1e-9 and not a, "v=%s a=%s" % (v, a))
check("提交后退出输入模式", g._focus is None and "t1" not in g._num_focus)

# —— Esc 取消 (保持原值) ——
frame([3], [])
check("t2 进入输入模式", g._focus == "t1")
g.handle_key_event(key("9"))
g.handle_key_event(key(k=pygame.K_ESCAPE))
v, a = frame([], [])
check("Esc 取消保持原值", abs(v - 5.0) < 1e-9, "v=%s" % v)

# —— 非法输入兜底: 非数字 -> 0 + notice ——
frame([3], [])
g.handle_key_event(key("a")); g.handle_key_event(key("b")); g.handle_key_event(key("c"))
g.handle_key_event(key(k=pygame.K_RETURN))
v, a = frame([], [])
check("非法输入 'abc' -> 改为 0", abs(v - 0.0) < 1e-9, "v=%s" % v)
check("非法输入有 notice 提醒", g.notice is not None and "无效" in g.notice, str(g.notice))

print("RESULT:", "PASS" if ok else "FAIL")
import pygame as _p; _p.quit()
