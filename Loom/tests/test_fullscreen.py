# -*- coding: utf-8 -*-
"""
test_fullscreen.py — F11 全屏（无边框假全屏）契约测试 (2026-11-06 重写)

为什么重写：487120c「彻底剥离 pygame 窗口」把窗口实现换成 GLFW，旧测试断言的
pygame.display.set_mode / NOFRAME / FULLSCREEN 契约已经不存在（实现正确、测试
过期）。按方法论"基准唯一"原则，测试基准必须是被审对象**当前**的白盒契约，
故按 GLFW 实现重写：

  1) GLFW 路径（编辑器/播放器有真实窗口）
     - 进全屏：用桌面分辨率 + DECORATED=FALSE + 移到 (0,0)
     - 绝不使用独占全屏标志（不切显示器分辨率 —— 只改装饰/尺寸/位置）
     - 退出全屏：DECORATED=TRUE + 恢复 window_size
     - window_size 在全屏期间不被覆盖（退出时要还原的对象）
  2) 外部 GL 上下文路径（Qt 宿主 QOpenGLWidget / PlayerApp(ctx=...)）
     - 没有 _glfw_win：不得抛异常，不得做任何窗口调用（P-07 回归）
     - 只同步 fullscreen 状态位 + ctx.viewport
  3) _on_resize 只更新 viewport，不重复创建/改窗口尺寸
"""
import sys as _sys_utf8
try:
    _sys_utf8.stdout.reconfigure(encoding='utf-8', errors='replace')
    _sys_utf8.stderr.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

# 2026-11-06 失败退出码闸门 (复核 A 指出: 54 个测试里仅 18 个有 sys.exit(1),
# 其余 FAIL 也 exit 0 -> run_all 假绿, 失败被静默吞掉)。
# 做法: 包一层 stdout, 出现以 "FAIL" 开头的行就在进程退出时把状态码改成 1。
# 只在真出现 FAIL 时才改码, 全 PASS 的测试行为完全不变。
import atexit as _atexit_gate
import os as _os_gate
import sys as _sys_gate


class _FailGateStream:
    def __init__(self, stream):
        self._stream = stream
        self.failed = False

    def write(self, text):
        if isinstance(text, str) and (text.startswith("FAIL") or "\nFAIL" in text):
            self.failed = True
        return self._stream.write(text)

    def __getattr__(self, name):
        return getattr(self._stream, name)


_fail_gate = _FailGateStream(_sys_gate.stdout)
_sys_gate.stdout = _fail_gate


@_atexit_gate.register
def _enforce_fail_exit_code():
    if not _fail_gate.failed:
        return
    try:
        _sys_gate.stdout.flush()
        _sys_gate.stderr.flush()
    except Exception:
        pass
    _os_gate._exit(1)


import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import engine as E
import loom_glfw_window as GW


class _StubCtx:
    def __init__(self):
        self.viewport = None


class _FakeGlfw:
    """记录 GLFW 调用, 不碰真实窗口系统."""
    FALSE, TRUE = 0, 1
    DECORATED = 0x200D     # 任意稳定值; 只用于断言"被调用过"

    def __init__(self):
        self.calls = []

    def set_window_attrib(self, win, attrib, value):
        self.calls.append(('set_window_attrib', attrib, value))

    def set_window_size(self, win, w, h):
        self.calls.append(('set_window_size', w, h))

    def set_window_pos(self, win, x, y):
        self.calls.append(('set_window_pos', x, y))


ok = True


def check(label, cond, detail=""):
    global ok
    print(("PASS " if cond else "FAIL ") + label + ("  " + detail if detail else ""))
    if not cond:
        ok = False


_orig_glfw = GW.glfw
_orig_place = GW.GlfwWindowMixin._place_fullscreen_window
GW.glfw = _FakeGlfw()
GW.GlfwWindowMixin._place_fullscreen_window = lambda self: None   # 置顶走 Win32, 单测跳过


def _make_engine(win="glfw-window"):
    eng = E.GLEngine.__new__(E.GLEngine)
    eng.width, eng.height = 800, 600
    eng.window_size = (800, 600)
    eng.fullscreen = False
    eng._window_rect = None
    eng._desktop_override = (1920, 1080)   # 固定桌面分辨率, 不依赖 GetSystemMetrics
    eng.ctx = _StubCtx()
    if win is not None:
        eng._glfw_win = win
    return eng


def _calls(eng_glfw, kind):
    return [c for c in eng_glfw.calls if c[0] == kind]


# ---- 1) GLFW 路径：进全屏 ----
fake = GW.glfw
fake.calls.clear()
eng = _make_engine()
eng._set_fullscreen(True)
check("进全屏 fullscreen=True", eng.fullscreen is True)
check("进全屏用桌面分辨率 (1920x1080)", (eng.width, eng.height) == (1920, 1080),
      "%s" % ((eng.width, eng.height),))
check("进全屏 DECORATED=FALSE (无边框)",
      ('set_window_attrib', GW.glfw.DECORATED, GW.glfw.FALSE) in fake.calls, str(fake.calls))
check("进全屏窗口移到 (0,0)",
      ('set_window_pos', 0, 0) in fake.calls, str(fake.calls))
check("进全屏窗口尺寸=桌面",
      ('set_window_size', 1920, 1080) in fake.calls, str(fake.calls))
check("window_size 不被覆盖 (退出还原用)", eng.window_size == (800, 600), str(eng.window_size))
check("进全屏同步 ctx.viewport", eng.ctx.viewport == (0, 0, 1920, 1080), str(eng.ctx.viewport))

# ---- 2) GLFW 路径：退出全屏 ----
fake.calls.clear()
eng._set_fullscreen(False)
check("退出全屏 fullscreen=False", eng.fullscreen is False)
check("退出全屏 DECORATED=TRUE",
      ('set_window_attrib', GW.glfw.DECORATED, GW.glfw.TRUE) in fake.calls, str(fake.calls))
check("退出全屏恢复窗口尺寸 (800x600)",
      ('set_window_size', 800, 600) in fake.calls, str(fake.calls))
check("退出全屏恢复 width/height", (eng.width, eng.height) == (800, 600))
check("退出全屏同步 ctx.viewport", eng.ctx.viewport == (0, 0, 800, 600), str(eng.ctx.viewport))

# ---- 3) _toggle_fullscreen 双向 ----
fake.calls.clear()
eng2 = _make_engine()
eng2._toggle_fullscreen()
check("toggle 进全屏", eng2.fullscreen is True and eng2.width == 1920)
eng2._toggle_fullscreen()
check("toggle 退出全屏", eng2.fullscreen is False and eng2.width == 800)

# ---- 4) P-07 回归：外部 GL 上下文（无 GLFW 窗口）不得崩 ----
fake.calls.clear()
eng3 = _make_engine(win=None)
try:
    eng3._set_fullscreen(True)
    eng3._set_fullscreen(False)
    crash = None
except Exception as e:          # noqa: BLE001 - 这里就是要抓任何异常
    crash = e
check("外部 ctx: 无 _glfw_win 不抛异常 (P-07)", crash is None, repr(crash))
check("外部 ctx: 不做任何 GLFW 窗口调用", fake.calls == [], str(fake.calls))
check("外部 ctx: 状态位仍被同步", eng3.fullscreen is False)

# ---- 5) _on_resize 只更新 viewport ----
fake.calls.clear()
eng4 = _make_engine()
eng4._on_resize(1024, 768)
check("_on_resize 不改窗口尺寸", fake.calls == [], str(fake.calls))
check("_on_resize 更新 width/height", (eng4.width, eng4.height) == (1024, 768))
check("_on_resize 更新 viewport", eng4.ctx.viewport == (0, 0, 1024, 768))

# 还原
GW.glfw = _orig_glfw
GW.GlfwWindowMixin._place_fullscreen_window = _orig_place

print()
print("总结果:", "ALL PASS ✅" if ok else "有 FAIL ❌")
sys.exit(0 if ok else 1)
