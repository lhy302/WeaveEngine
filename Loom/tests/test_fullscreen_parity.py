# -*- coding: utf-8 -*-
"""test_fullscreen_parity.py — GL / VK 两端 F11 假全屏**语义对拍**门（真窗口，2026-11-18）。

为什么要有这一门（人类原话，反复重申）：
  「最后的目标一定是两种后端没有用户可感知的差异，还是那个目标：如同 JVM 虚拟机在
    任何 CPU 上都保证字节码解析效果一样，那样不管选择什么后端对用户脚本的表现一致。」
所以不能"各自能跑就行"，必须**逐项对拍**同一串输入事件在两端的可观察结果。

输入事件（两端**同一串**）：
    SimpleNamespace(type='KEYDOWN', key=pygame.K_F11, mod=0, unicode='')
      -> handle_key_event(ev)          # 内核 engine_core 第①步 -> _toggle_fullscreen
各按一次 = 进全屏，再按一次 = 退全屏。

两端宿主（真窗口，主线程）：
  · GL：engine.GLEngine(640, 400) —— GLEngine 自己建 GLFW 窗口那条路（_init_glfw_window）
  · VK：scene_driver.SceneDriver() + loom_vk_window.VkWindowMixin，宿主句柄经
        driver._vk_glfw_window 注入（= vk_player._register_input 的真实注入点）
        注入的句柄是一个**真 GLFW 窗口**（GLFW_NO_API，640x400），不是假对象。

对拍的可观察量（逐项必须相等；不等 = 红）：
  A. fullscreen 状态位翻转序列            False -> True -> False
  B. DECORATED 属性                       1 -> 0 -> 1
  C. client 尺寸   进全屏 == 桌面尺寸；退出 == 进入前尺寸（逐像素相等）
  D. 窗口位置      进全屏 == (0,0)；退出 == 进入前位置（逐像素相等）
  E. 置顶 WS_EX_TOPMOST 位                False -> True -> False
  F. 同串事件都被内核第①步消费（返回 True）+ allow_fullscreen 两端同值

**已知差异登记**：无。本门不允许"差不多"：任何一条对不上就是红，必须修到一致，
或在此处登记「已知差异 + 原因」并在报告里单列（当前登记表为空）。

修前（GL 侧 Q-B7-36-1 / Q-B7-36-2 未修）本门实测红：
  GL 退出全屏后 1920x1055 @ (0,0)（原 640x400 @ (73,102)），进全屏时 WS_EX_TOPMOST 未置位；
  VK 侧 640x400 @ (73,102)、置顶真置位 —— 两端逐项不等。
"""
import sys as _sys_utf8
try:
    _sys_utf8.stdout.reconfigure(encoding='utf-8', errors='replace')
    _sys_utf8.stderr.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

# 失败退出码闸门（与 test_fullscreen.py / test_fullscreen_vk.py 同款）：
# 出现以 "FAIL" 开头的行 -> 进程退出码改 1，run_all 不会假绿。
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


import ctypes                                                      # noqa: E402
import os                                                          # noqa: E402
import sys                                                         # noqa: E402
import time                                                        # noqa: E402
from ctypes import wintypes                                        # noqa: E402
from types import SimpleNamespace                                  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
os.environ['LOOM_NO_SAVE_MIGRATE'] = '1'
os.environ['LOOM_NO_PARALLEL'] = '1'
os.environ['LOOM_NO_DIALOG'] = '1'

import glfw                                                        # noqa: E402
import pygame                                                      # noqa: E402

import engine as E                                                 # noqa: E402
import render.vk.driver as SD                                          # noqa: E402
from render.gl.window import _make_hwnd                            # noqa: E402

ok = True
LINES = []


def check(label, cond, detail=''):
    global ok
    print(('PASS ' if cond else 'FAIL ') + label + ('  ' + str(detail) if detail else ''))
    if not cond:
        ok = False


# ---------------- Win32（本门自己的私有 user32，显式 argtypes） ----------------
_u = ctypes.WinDLL('user32', use_last_error=True)
_u.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
_u.GetWindowRect.restype = wintypes.BOOL
_u.GetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int]
_u.GetWindowLongW.restype = wintypes.LONG
_u.GetClientRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
_u.GetClientRect.restype = wintypes.BOOL
_u.ClientToScreen.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.POINT)]
_u.ClientToScreen.restype = wintypes.BOOL

GWL_EXSTYLE = -20
WS_EX_TOPMOST = 0x00000008

# 两端统一的起始几何（用户在真机上报的那组：640x400 @ (73,102)）
START_W, START_H = 640, 400
START_X, START_Y = 73, 102


def pump(n=25, dt=0.02):
    """等窗口管理器把 set_window_* 真正落地（异步）。"""
    for _ in range(n):
        try:
            glfw.poll_events()
        except Exception:
            pass
        time.sleep(dt)


def key_f11():
    return SimpleNamespace(type='KEYDOWN', key=pygame.K_F11, mod=0, unicode='')


def snapshot(win, owner, tag):
    """一端的全部可观察量（两端**同一份**取法，避免"取法不同"造成的假差异）。"""
    hwnd = _make_hwnd(win) if win else None
    ex = _u.GetWindowLongW(hwnd, GWL_EXSTYLE) if hwnd else None
    r = wintypes.RECT()
    c = wintypes.RECT()
    p = wintypes.POINT(0, 0)
    if hwnd:
        _u.GetWindowRect(hwnd, ctypes.byref(r))
        _u.GetClientRect(hwnd, ctypes.byref(c))
        _u.ClientToScreen(hwnd, ctypes.byref(p))
    return {
        'tag': tag,
        'hwnd': hwnd,
        'fullscreen': getattr(owner, 'fullscreen', '<缺失>'),
        'allow_fullscreen': getattr(owner, 'allow_fullscreen', '<缺失>'),
        'decorated': int(glfw.get_window_attrib(win, glfw.DECORATED)),
        'size': tuple(int(v) for v in glfw.get_window_size(win)),
        'pos': tuple(int(v) for v in glfw.get_window_pos(win)),
        'topmost': (bool(ex & WS_EX_TOPMOST) if ex is not None else None),
        'winrect': (int(r.left), int(r.top), int(r.right), int(r.bottom)) if hwnd else None,
        'client': (int(c.right - c.left), int(c.bottom - c.top)) if hwnd else None,
        'client_origin': (int(p.x), int(p.y)) if hwnd else None,
    }


def show(name, s):
    print('  [%s] fullscreen=%r decorated=%r size=%r pos=%r topmost=%r winrect=%r'
          % (name, s['fullscreen'], s['decorated'], s['size'], s['pos'],
             s['topmost'], s['winrect']))


# ============================ 一. 真窗口准备 ============================
print("=== 〇. 真窗口准备（GL：GLEngine 自建 GLFW 窗口 / VK：注入真 GLFW 窗口句柄） ===")
eng = E.GLEngine(START_W, START_H)              # 这一步才 glfw.init()
GL_WIN = eng._glfw_win
desktop = tuple(int(v) for v in eng._desktop_resolution())
check('GL 真窗口已建立', bool(GL_WIN), GL_WIN)
check('桌面分辨率（两端对拍的基准）', desktop[0] > 0 and desktop[1] > 0, desktop)

glfw.window_hint(glfw.CLIENT_API, glfw.NO_API)   # 只要真 Win32 窗口，不要第二个 GL 上下文
VK_WIN = glfw.create_window(START_W, START_H, 'Loom VK parity (fullscreen gate)', None, None)
check('VK 宿主真窗口已建立', bool(VK_WIN), VK_WIN)
if not VK_WIN:
    print('FAIL 拿不到 VK 宿主窗口，本门无法对拍（不许跳过）')
    ok = False

glfw.set_window_pos(GL_WIN, START_X, START_Y)
glfw.set_window_pos(VK_WIN, START_X, START_Y)
pump(40)

driver = SD.SceneDriver()
driver._vk_glfw_window = VK_WIN               # = vk_player._register_input 的真实注入点
driver._vk_canvas = None

print()
print("=== 一. 进入前基线（两端起始几何相同） ===")
gl_before = snapshot(GL_WIN, eng, 'GL before')
vk_before = snapshot(VK_WIN, driver, 'VK before')
show('GL', gl_before)
show('VK', vk_before)
check('两端进入前 client 尺寸相同', gl_before['size'] == vk_before['size'],
      (gl_before['size'], vk_before['size']))
check('两端进入前位置相同', gl_before['pos'] == vk_before['pos'],
      (gl_before['pos'], vk_before['pos']))
check('两端进入前 DECORATED 相同（都有边框）', gl_before['decorated'] == vk_before['decorated'] == 1,
      (gl_before['decorated'], vk_before['decorated']))
check('两端进入前都非置顶', gl_before['topmost'] is False and vk_before['topmost'] is False,
      (gl_before['topmost'], vk_before['topmost']))
check('两端 allow_fullscreen 同值 True',
      gl_before['allow_fullscreen'] is True and vk_before['allow_fullscreen'] is True,
      (gl_before['allow_fullscreen'], vk_before['allow_fullscreen']))

# ============================ 二. 按 F11 进全屏 ============================
print()
print("=== 二. F11 #1 进全屏（同一串事件喂两端） ===")
gl_eaten_on = bool(eng.handle_key_event(key_f11()))
vk_eaten_on = bool(driver.handle_key_event(key_f11()))
pump(60)
gl_on = snapshot(GL_WIN, eng, 'GL on')
vk_on = snapshot(VK_WIN, driver, 'VK on')
show('GL', gl_on)
show('VK', vk_on)

check('F11 #1 两端都被内核第①步消费（返回 True）',
      gl_eaten_on is True and vk_eaten_on is True, (gl_eaten_on, vk_eaten_on))
check('A 进全屏 fullscreen 两端同为 True',
      gl_on['fullscreen'] is True and vk_on['fullscreen'] is True,
      (gl_on['fullscreen'], vk_on['fullscreen']))
check('B 进全屏 DECORATED 两端同为 0（去边框）',
      gl_on['decorated'] == vk_on['decorated'] == 0, (gl_on['decorated'], vk_on['decorated']))
check('C 进全屏 client 尺寸两端 == 桌面尺寸 %r' % (desktop,),
      gl_on['size'] == desktop and vk_on['size'] == desktop, (gl_on['size'], vk_on['size']))
check('D 进全屏窗口位置两端 == (0,0)',
      gl_on['pos'] == (0, 0) and vk_on['pos'] == (0, 0), (gl_on['pos'], vk_on['pos']))
check('E 进全屏 WS_EX_TOPMOST 两端同为 True（真置顶，不是只调了 API）',
      gl_on['topmost'] is True and vk_on['topmost'] is True,
      (gl_on['topmost'], vk_on['topmost']))

# ============================ 三. 再按 F11 退全屏 ============================
print()
print("=== 三. F11 #2 退全屏（同一串事件喂两端） ===")
gl_eaten_off = bool(eng.handle_key_event(key_f11()))
vk_eaten_off = bool(driver.handle_key_event(key_f11()))
pump(60)
gl_off = snapshot(GL_WIN, eng, 'GL off')
vk_off = snapshot(VK_WIN, driver, 'VK off')
show('GL', gl_off)
show('VK', vk_off)

check('F11 #2 两端都被内核第①步消费（返回 True）',
      gl_eaten_off is True and vk_eaten_off is True, (gl_eaten_off, vk_eaten_off))
check('A 退全屏 fullscreen 两端同为 False',
      gl_off['fullscreen'] is False and vk_off['fullscreen'] is False,
      (gl_off['fullscreen'], vk_off['fullscreen']))
check('B 退全屏 DECORATED 两端同为 1（还边框）',
      gl_off['decorated'] == vk_off['decorated'] == 1, (gl_off['decorated'], vk_off['decorated']))
check('C 退全屏 client 尺寸 == 进入前尺寸（两端各自真还原）',
      gl_off['size'] == gl_before['size'] and vk_off['size'] == vk_before['size'],
      (gl_off['size'], gl_before['size'], vk_off['size'], vk_before['size']))
check('D 退全屏窗口位置 == 进入前位置（两端各自真还原）',
      gl_off['pos'] == gl_before['pos'] and vk_off['pos'] == vk_before['pos'],
      (gl_off['pos'], gl_before['pos'], vk_off['pos'], vk_before['pos']))
check('E 退全屏 WS_EX_TOPMOST 两端同为 False（取消置顶）',
      gl_off['topmost'] is False and vk_off['topmost'] is False,
      (gl_off['topmost'], vk_off['topmost']))

# ============================ 四. 逐项对拍（两端相等） ============================
print()
print("=== 四. 逐项对拍：两端同一阶段的可观察量必须逐项相等 ===")
for stage, g, v in (('进入前', gl_before, vk_before),
                    ('全屏中', gl_on, vk_on),
                    ('退出后', gl_off, vk_off)):
    for field in ('fullscreen', 'decorated', 'size', 'pos', 'topmost'):
        check('%s: %s 两端相等' % (stage, field), g[field] == v[field], (g[field], v[field]))
    check('%s: 窗口矩形（含边框）两端相等' % (stage,), g['winrect'] == v['winrect'],
          (g['winrect'], v['winrect']))
    check('%s: client 屏幕原点两端相等' % (stage,), g['client_origin'] == v['client_origin'],
          (g['client_origin'], v['client_origin']))

# 状态位翻转序列（A）逐项对拍
check('A 翻转序列 两端一致：False->True->False',
      [gl_before['fullscreen'], gl_on['fullscreen'], gl_off['fullscreen']] ==
      [vk_before['fullscreen'], vk_on['fullscreen'], vk_off['fullscreen']] ==
      [False, True, False],
      ([gl_before['fullscreen'], gl_on['fullscreen'], gl_off['fullscreen']],
       [vk_before['fullscreen'], vk_on['fullscreen'], vk_off['fullscreen']]))
check('B 翻转序列 两端一致：1->0->1',
      [gl_before['decorated'], gl_on['decorated'], gl_off['decorated']] ==
      [vk_before['decorated'], vk_on['decorated'], vk_off['decorated']] ==
      [1, 0, 1],
      ([gl_before['decorated'], gl_on['decorated'], gl_off['decorated']],
       [vk_before['decorated'], vk_on['decorated'], vk_off['decorated']]))
check('E 翻转序列 两端一致：False->True->False（置顶位）',
      [gl_before['topmost'], gl_on['topmost'], gl_off['topmost']] ==
      [vk_before['topmost'], vk_on['topmost'], vk_off['topmost']] ==
      [False, True, False],
      ([gl_before['topmost'], gl_on['topmost'], gl_off['topmost']],
       [vk_before['topmost'], vk_on['topmost'], vk_off['topmost']]))

# ============================ 五. 可重复性（第二次往返同样一致） ============================
print()
print("=== 五. 第二次 F11 往返：两端仍然逐项一致（可重复，不是一次性巧合） ===")
eng.handle_key_event(key_f11())
driver.handle_key_event(key_f11())
pump(45)
gl_on2 = snapshot(GL_WIN, eng, 'GL on2')
vk_on2 = snapshot(VK_WIN, driver, 'VK on2')
eng.handle_key_event(key_f11())
driver.handle_key_event(key_f11())
pump(45)
gl_off2 = snapshot(GL_WIN, eng, 'GL off2')
vk_off2 = snapshot(VK_WIN, driver, 'VK off2')
show('GL off2', gl_off2)
show('VK off2', vk_off2)
check('第二次全屏中：两端逐项相等（尺寸/位置/边框/置顶）',
      (gl_on2['size'], gl_on2['pos'], gl_on2['decorated'], gl_on2['topmost']) ==
      (vk_on2['size'], vk_on2['pos'], vk_on2['decorated'], vk_on2['topmost']) ==
      (desktop, (0, 0), 0, True),
      ((gl_on2['size'], gl_on2['pos'], gl_on2['decorated'], gl_on2['topmost']),
       (vk_on2['size'], vk_on2['pos'], vk_on2['decorated'], vk_on2['topmost'])))
check('第二次退出后：两端逐项还原到进入前（尺寸/位置/边框/非置顶）',
      (gl_off2['size'], gl_off2['pos'], gl_off2['decorated'], gl_off2['topmost']) ==
      (vk_off2['size'], vk_off2['pos'], vk_off2['decorated'], vk_off2['topmost']) ==
      (gl_before['size'], gl_before['pos'], 1, False),
      ((gl_off2['size'], gl_off2['pos'], gl_off2['decorated'], gl_off2['topmost']),
       (vk_off2['size'], vk_off2['pos'], vk_off2['decorated'], vk_off2['topmost'])))

# ============================ 六. 已知差异登记表（必须为空） ============================
print()
print("=== 六. 已知差异登记表 ===")
KNOWN_DIFFS = []      # [(条目, 原因)] —— 有内容就必须在交付报告里单列；不许拿它放宽断言
check('已知差异登记表为空（两端无登记在案的差异）', KNOWN_DIFFS == [], KNOWN_DIFFS)

# ============================ 收尾 ============================
try:
    glfw.destroy_window(VK_WIN)
except Exception:
    pass
try:
    glfw.destroy_window(GL_WIN)
except Exception:
    pass
try:
    glfw.terminate()
except Exception:
    pass

print()
print("总结果:", "ALL PASS ✅" if ok else "有 FAIL ❌")
sys.exit(0 if ok else 1)
