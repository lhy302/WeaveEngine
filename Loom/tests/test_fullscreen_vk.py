# -*- coding: utf-8 -*-
import sys as _sys_utf8
try:
    _sys_utf8.stdout.reconfigure(encoding='utf-8', errors='replace')
    _sys_utf8.stderr.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

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


"""test_fullscreen_vk.py — VK 播放器 F11 假全屏契约（**与 GL 同语义**）。

人类裁决 Q-B7-32-1 = ①（真做出来，2026-11-18）：
  「两个后端暴露给用户的 API 都是一样的…往上暴露的接口都一样。」
  → 同一串输入事件（含按 F11）→ 两端同一串可观察结果。

GL 侧的契约门是 test_fullscreen.py（测 GlfwWindowMixin._set_fullscreen）。本门测 VK 侧
loom_vk_window.VkWindowMixin，判据逐项对齐（三步 + 完整还原）：

  1) allow_fullscreen 默认 True（VK 播放器允许 F11；编辑器 False 不在本门范围）
  2) 进全屏：桌面分辨率 -> DECORATED=FALSE -> set_window_size(桌面) -> set_window_pos(0,0)
            -> Win32 SetWindowPos(HWND_TOPMOST=-1)
  3) 退全屏：DECORATED=TRUE -> 还原进入前的 client 尺寸 -> 还原进入前的位置
            -> SetWindowPos(HWND_NOTOPMOST=-2)
  4) 拿不到窗口句柄 / 非 Windows -> **可见降级**：打印一行明确原因 + allow_fullscreen=False，
     不抛异常、不做任何窗口调用（不许静默 —— 这是修前 VK 的死键现场）
  5) 内核第①步真的会把 F11 交到 _toggle_fullscreen（handle_key_event 走通），
     allow_fullscreen=False 时不再调用
"""
import contextlib
import io
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
os.environ['LOOM_NO_SAVE_MIGRATE'] = '1'
os.environ['LOOM_NO_PARALLEL'] = '1'
os.environ.setdefault('LOOM_NO_DIALOG', '1')

import pygame                                                # noqa: E402
import loom_vk_window as W                                   # noqa: E402
import scene_driver as SD                                    # noqa: E402

ok = True


def check(label, cond, detail=''):
    global ok
    print(('PASS ' if cond else 'FAIL ') + label + ('  ' + str(detail) if detail else ''))
    if not cond:
        ok = False


# ============ 假后端：记录调用，不碰真实窗口系统 ============
class _FakeGlfw:
    """只记录窗口调用；get_window_size 是句柄验活用的，必须不抛。"""

    FALSE = 0
    TRUE = 1
    DECORATED = 0x200D

    def __init__(self):
        self.calls = []

    def get_window_size(self, win):
        return (640, 400)

    def set_window_attrib(self, win, attrib, value):
        self.calls.append(('set_window_attrib', attrib, value))

    def set_window_size(self, win, w, h):
        self.calls.append(('set_window_size', w, h))

    def set_window_pos(self, win, x, y):
        self.calls.append(('set_window_pos', x, y))


class _FakeUser32:
    """记录 SetWindowPos；GetSystemMetrics 给固定桌面。"""

    def __init__(self, metrics=(1920, 1080)):
        self.metrics = metrics
        self.swp = []

    def GetSystemMetrics(self, i):
        return self.metrics[0] if i == 0 else self.metrics[1]

    def SetWindowPos(self, hwnd, insert_after, x, y, cx, cy, flags):
        # insert_after 是 c_void_p(-1)/(-2)：按 64 位句柄取值（GL 那版传裸 -1 会截断）
        try:
            ia = int(insert_after.value)
            if ia >= (1 << 63):          # c_void_p(-1) 读出来是无符号 64 位
                ia -= (1 << 64)
        except AttributeError:
            ia = int(insert_after)
        self.swp.append((ia, int(x), int(y), int(cx), int(cy), int(flags)))
        return 1


_PRE_RECT = (100, 150, 740, 550)

_orig = (W._glfw, W._user32, W._make_hwnd, W._window_rect_now, W._WINDOWS)
FAKE_GLFW = _FakeGlfw()
FAKE_U32 = _FakeUser32()
W._glfw = lambda: FAKE_GLFW
W._user32 = lambda: FAKE_U32
W._make_hwnd = lambda win: 12345
W._window_rect_now = lambda u, hwnd: _PRE_RECT
W._WINDOWS = True


def _mk_driver(win='fake-glfw-window'):
    """不跑 SceneDriver.__init__（不建场景/物理），只装全屏要用的字段。"""
    d = SD.SceneDriver.__new__(SD.SceneDriver)
    d.width, d.height = 640, 400
    d.fullscreen = False
    d.allow_fullscreen = True
    d._window_rect = None
    d._window_client = None
    d._desktop_override = (1920, 1080)
    d._fullscreen_degraded_logged = False
    d._vk_glfw_window = win
    d._vk_canvas = None
    return d


def _calls(kind):
    return [c for c in FAKE_GLFW.calls if c[0] == kind]


print("=== 〇. 真实 SceneDriver 默认允许 F11（修前：属性根本不存在） ===")
_d0 = SD.SceneDriver()
check('SceneDriver 有 allow_fullscreen 属性', hasattr(_d0, 'allow_fullscreen'),
      '缺失 -> 内核 engine_core.py:163 的判据恒 False -> F11 死键')
check('SceneDriver.allow_fullscreen is True（与 GL 的 engine.py:229 同值）',
      getattr(_d0, 'allow_fullscreen', None) is True, getattr(_d0, 'allow_fullscreen', None))
check('SceneDriver 有 fullscreen 状态位（与 GL 同名）', hasattr(_d0, 'fullscreen'),
      getattr(_d0, 'fullscreen', '<缺失>'))
check('_toggle_fullscreen / _set_fullscreen 都在', callable(getattr(_d0, '_toggle_fullscreen', None))
      and callable(getattr(_d0, '_set_fullscreen', None)))

print()
print("=== 一. 进全屏：三步 + 置顶（与 GL 逐项对齐） ===")
FAKE_GLFW.calls.clear()
FAKE_U32.swp.clear()
d = _mk_driver()
r = d._set_fullscreen(True)
check('进全屏返回 True（窗口操作真的做了）', r is True, r)
check('进全屏 fullscreen=True', d.fullscreen is True)
check('进全屏用桌面分辨率 1920x1080', (d.width, d.height) == (1920, 1080), (d.width, d.height))
check('进全屏 DECORATED=FALSE（去边框）',
      ('set_window_attrib', _FakeGlfw.DECORATED, _FakeGlfw.FALSE) in FAKE_GLFW.calls, FAKE_GLFW.calls)
check('进全屏 set_window_size(桌面)',
      ('set_window_size', 1920, 1080) in FAKE_GLFW.calls, FAKE_GLFW.calls)
check('进全屏 set_window_pos(0,0)', ('set_window_pos', 0, 0) in FAKE_GLFW.calls, FAKE_GLFW.calls)
check('进全屏 Win32 置顶 HWND_TOPMOST=-1', bool(FAKE_U32.swp) and FAKE_U32.swp[0][0] == -1,
      FAKE_U32.swp)
check('进全屏前记录了原窗口矩形（真还原的依据）', d._window_rect == _PRE_RECT, d._window_rect)
check('进全屏前记录了原 client 尺寸', d._window_client == (640, 400), d._window_client)
check('进全屏顺序：去边框 -> 铺满 -> 左上角',
      [c[0] for c in FAKE_GLFW.calls] == ['set_window_attrib', 'set_window_size', 'set_window_pos'],
      FAKE_GLFW.calls)

print()
print("=== 二. 退全屏：边框 / 尺寸 / 位置 / 非置顶 全部还原 ===")
FAKE_GLFW.calls.clear()
FAKE_U32.swp.clear()
r = d._set_fullscreen(False)
check('退全屏返回 True', r is True, r)
check('退全屏 fullscreen=False', d.fullscreen is False)
check('退全屏 DECORATED=TRUE（还边框）',
      ('set_window_attrib', _FakeGlfw.DECORATED, _FakeGlfw.TRUE) in FAKE_GLFW.calls, FAKE_GLFW.calls)
check('退全屏还原 client 尺寸 640x400',
      ('set_window_size', 640, 400) in FAKE_GLFW.calls, FAKE_GLFW.calls)
check('退全屏还原位置 (100,150)（= 进入前窗口左上角）',
      ('set_window_pos', 100, 150) in FAKE_GLFW.calls, FAKE_GLFW.calls)
check('退全屏 width/height 回到 640x400', (d.width, d.height) == (640, 400), (d.width, d.height))
check('退全屏 Win32 取消置顶 HWND_NOTOPMOST=-2',
      bool(FAKE_U32.swp) and FAKE_U32.swp[0][0] == -2, FAKE_U32.swp)
check('退全屏后清空 _window_rect（下次进全屏重新记录）', d._window_rect is None, d._window_rect)

print()
print("=== 三. toggle 双向（= F11 连按两次） ===")
FAKE_GLFW.calls.clear()
d2 = _mk_driver()
d2._toggle_fullscreen()
check('toggle #1 进全屏', d2.fullscreen is True and (d2.width, d2.height) == (1920, 1080),
      (d2.fullscreen, d2.width, d2.height))
d2._toggle_fullscreen()
check('toggle #2 退全屏', d2.fullscreen is False and (d2.width, d2.height) == (640, 400),
      (d2.fullscreen, d2.width, d2.height))

print()
print("=== 四. 拿不到窗口句柄 -> 可见降级（打印一行 + 关掉 F11，不静默） ===")
FAKE_GLFW.calls.clear()
FAKE_U32.swp.clear()
d3 = _mk_driver(win=None)
buf = io.StringIO()
try:
    with contextlib.redirect_stdout(buf):
        r3 = d3._set_fullscreen(True)
    crash = None
except Exception as e:                     # noqa: BLE001 - 就是要抓任何异常
    crash = e
    r3 = None
out3 = buf.getvalue()
check('无句柄：不抛异常', crash is None, repr(crash))
check('无句柄：返回 False（降级信号）', r3 is False, r3)
check('无句柄：不做任何窗口调用', FAKE_GLFW.calls == [] and FAKE_U32.swp == [],
      (FAKE_GLFW.calls, FAKE_U32.swp))
check('无句柄：打印了一行明确原因（不静默）',
      out3.strip().startswith('[全屏]') and 'F11 全屏在本机不可用' in out3, repr(out3[:120]))
check('无句柄：allow_fullscreen 被关掉（内核第①步不再空转）',
      d3.allow_fullscreen is False, d3.allow_fullscreen)
check('无句柄：fullscreen 状态位保持 False', d3.fullscreen is False, d3.fullscreen)
buf2 = io.StringIO()
with contextlib.redirect_stdout(buf2):
    d3._set_fullscreen(True)
check('降级只报一次（第二次不再刷屏）', buf2.getvalue() == '', repr(buf2.getvalue()[:80]))

print()
print("=== 五. 非 Windows -> 同样可见降级 ===")
W._WINDOWS = False
d4 = _mk_driver()
buf = io.StringIO()
try:
    with contextlib.redirect_stdout(buf):
        r4 = d4._set_fullscreen(True)
    crash = None
except Exception as e:                     # noqa: BLE001
    crash = e
    r4 = None
out4 = buf.getvalue()
check('非 Windows：不抛异常', crash is None, repr(crash))
check('非 Windows：返回 False 且 allow_fullscreen=False',
      r4 is False and d4.allow_fullscreen is False, (r4, d4.allow_fullscreen))
check('非 Windows：打印原因含"不是 Windows"', 'Windows' in out4, repr(out4[:140]))
W._WINDOWS = True

print()
print("=== 六. _desktop_resolution 与 GL 同源（override 优先，其次 GetSystemMetrics） ===")
d5 = _mk_driver()
d5._desktop_override = None
check('GetSystemMetrics 路径给 1920x1080', d5._desktop_resolution() == (1920, 1080),
      d5._desktop_resolution())
d5._desktop_override = (1280, 720)
check('_desktop_override 优先（单测/无头可钉死）', d5._desktop_resolution() == (1280, 720),
      d5._desktop_resolution())

print()
print("=== 七. 内核第①步：F11 真的交到 _toggle_fullscreen ===")
d6 = _mk_driver()
hits = []
d6._toggle_fullscreen = lambda: hits.append(1)
from types import SimpleNamespace
ev = SimpleNamespace(type='KEYDOWN', key=pygame.K_F11, mod=0, unicode='')
consumed = d6.handle_key_event(ev)
check('F11 被内核第①步消费（返回 True）', consumed is True, consumed)
check('F11 真的调到 _toggle_fullscreen（1 次）', len(hits) == 1, hits)
d7 = _mk_driver()
d7.allow_fullscreen = False
hits2 = []
d7._toggle_fullscreen = lambda: hits2.append(1)
consumed2 = d7.handle_key_event(ev)
check('allow_fullscreen=False 时不再调 _toggle_fullscreen', hits2 == [], hits2)
check('allow_fullscreen=False 时 F11 不被第①步消费（交后续步骤）', consumed2 is False, consumed2)

# 还原（其它门可能同进程复用）
W._glfw, W._user32, W._make_hwnd, W._window_rect_now, W._WINDOWS = _orig

print()
print("总结果:", "ALL PASS ✅" if ok else "有 FAIL ❌")
sys.exit(0 if ok else 1)
