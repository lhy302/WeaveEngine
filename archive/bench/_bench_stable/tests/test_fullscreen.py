# -*- coding: utf-8 -*-
"""F11 全屏切换 (无边框假全屏) 无头逻辑测试.

不建真实窗口 (GLEngine.__new__ 桩 + mock pygame.display):
  - 进全屏: 用桌面分辨率 + NOFRAME, 绝不带 pygame.FULLSCREEN 标志
    (独占模式会真实切换显示器分辨率 -> GPU 驱动模式切换/可能重置, 还会把
     终端窗口带崩 —— 假全屏只铺满屏幕, 不切分辨率)
  - 退出全屏: 恢复 window_size + 去掉 NOFRAME
  - _on_resize 只更新 viewport, 不重复 set_mode (SDL 已缩放好)
  - 全屏期间 window_size 不被覆盖 (VIDEORESIZE guard 保护的对象)
  - get_wm_info 抛异常时 _place_fullscreen_window 静默降级
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import pygame
import engine as E

class _StubCtx:
    def __init__(self):
        self.viewport = None

class _StubInfo:
    current_w, current_h = 1920, 1080

calls = []          # 捕获 set_mode 调用: (size, flags)
_info = _StubInfo()
_wm_ok = True       # True: get_wm_info 返回假 hwnd; False: 抛异常 (模拟无窗口)

def _fake_set_mode(size, flags):
    calls.append((tuple(size), int(flags)))
    return "window"

def _fake_info():
    return _info

def _fake_wm_info():
    if not _wm_ok:
        raise RuntimeError("no window")
    return {"window": 12345}

_orig = (pygame.display.set_mode, pygame.display.Info, pygame.display.get_wm_info)

def _make_engine():
    eng = E.GLEngine.__new__(E.GLEngine)
    eng.width, eng.height = 800, 600
    eng.window_size = (800, 600)
    eng.fullscreen = False
    eng._window_rect = None
    eng._desktop_size = (1920, 1080)      # init 时 Info() 抓的桌面尺寸 (窗口创建前)
    eng._desktop_override = (1920, 1080)  # 固定桌面分辨率, 不依赖真实 GetSystemMetrics
    eng.window = "window"
    eng.ctx = _StubCtx()
    return eng

ok = True
def check(label, cond, detail=""):
    global ok
    print(("PASS " if cond else "FAIL ") + label + ("  " + detail if detail else ""))
    if not cond:
        ok = False

def _setup():
    global calls, _wm_ok
    calls = []
    _wm_ok = True
    pygame.display.set_mode = _fake_set_mode
    pygame.display.Info = _fake_info
    pygame.display.get_wm_info = _fake_wm_info

def _teardown():
    pygame.display.set_mode, pygame.display.Info, pygame.display.get_wm_info = _orig

# ---- 1) 进全屏: 桌面分辨率 + NOFRAME, 绝不带 FULLSCREEN (核心: 不切分辨率) ----
_setup()
eng = _make_engine()
eng._set_fullscreen(True)
check("进全屏 fullscreen=True", eng.fullscreen)
check("进全屏用桌面分辨率 (1920x1080)",
      len(calls) == 1 and calls[-1][0] == (1920, 1080), str(calls[-1][0] if calls else None))
fl = calls[-1][1] if calls else 0
check("进全屏带 NOFRAME", bool(fl & pygame.NOFRAME), "flags=%s" % hex(fl))
check("进全屏不带 FULLSCREEN (关键: 不切分辨率)",
      not (fl & pygame.FULLSCREEN), "FULLSCREEN flag 会切显示器分辨率/崩终端")
check("width/height 更新为桌面", (eng.width, eng.height) == (1920, 1080))
check("window_size 不被覆盖 (VIDEORESIZE guard 保护)",
      eng.window_size == (800, 600), str(eng.window_size))

# ---- 2) 退出全屏: 恢复 window_size + 去 NOFRAME ----
eng._set_fullscreen(False)
check("退出全屏 fullscreen=False", not eng.fullscreen)
last = calls[-1]
check("退出全屏恢复窗口尺寸 (800x600)", last[0] == (800, 600), str(last[0]))
check("退出全屏去 NOFRAME", not (last[1] & pygame.NOFRAME))
check("退出全屏也不带 FULLSCREEN", not (last[1] & pygame.FULLSCREEN))
check("width/height 恢复窗口尺寸", (eng.width, eng.height) == (800, 600))

# ---- 3) _toggle_fullscreen 双向切换 ----
eng2 = _make_engine()
eng2._toggle_fullscreen()
check("toggle 进全屏 fullscreen=True", eng2.fullscreen and eng2.width == 1920)
eng2._toggle_fullscreen()
check("toggle 退出全屏 fullscreen=False", not eng2.fullscreen and eng2.width == 800)
all_flags = [f for _, f in calls]
check("全程所有 set_mode 都不带 FULLSCREEN (杜绝切分辨率)",
      all(not (f & pygame.FULLSCREEN) for f in all_flags))

# ---- 4) _on_resize 只更新 viewport, 不重复 set_mode ----
eng3 = _make_engine()
n0 = len(calls)
eng3._on_resize(1024, 768)
check("_on_resize 不调 set_mode", len(calls) == n0, "set_mode 次数=%d" % len(calls))
check("_on_resize 更新 width/height", (eng3.width, eng3.height) == (1024, 768))
check("_on_resize 更新 viewport", eng3.ctx.viewport == (0, 0, 1024, 768))

# ---- 5) get_wm_info 抛异常时静默降级 (无头/无窗口环境) ----
_wm_ok = False
eng4 = _make_engine()
try:
    eng4._set_fullscreen(True)
    eng4._set_fullscreen(False)
    check("get_wm_info 异常被捕获 (静默降级)", True)
except Exception as e:
    check("get_wm_info 异常被捕获 (静默降级)", False, repr(e))

_teardown()
print()
print("总结果:", "ALL PASS ✅" if ok else "有 FAIL ❌")
sys.exit(0 if ok else 1)
