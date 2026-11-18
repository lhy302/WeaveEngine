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


"""test_input_chain_parity.py — P0-3 步 2 门：**输入全链**两端对拍。

这条链是上次失败的教训，此前**没有任何门**覆盖它：

    宿主写键（物理事件） → key_state（键码->bool） → script_keys（键名->bool）
        → 脚本 is_key()/get_action() → 解锁键翻转（Tab）/ 引擎键（F9）

本门要求：**同一串物理键事件**分别喂进 GL 与 VK 的**宿主喂键入口**，
逐项比对两端的可观察结果，断言「逐项相等」而不是「各自为 True」。

两端宿主入口（真实生产路径，不是测试里另写一份）：
  · GL : loom_glfw_window._on_key_cb 的做法 —— 翻成 ev 递进 EngineCore.handle_key_event
  · VK : vk_player.host_key_forward   —— vk_player._on_key 调的就是它（步 2 收敛点）

覆盖 8 组：① 单键按下/松开 ② 多键同时 ③ 动作映射 ④ 无动作绑定的键(F5) + 真正未映射键(F13) ⑤ Tab 解锁链
          ⑥ UI 焦点消费 ⑦ 宿主直写 script_keys（兼容路径） ⑧ 引擎键 F9 + 内核钩子
另加一条**不变量**：script_keys 恒等于「key_state 派生结果」∪「键名直写过渡项」
（两端每一步都查；这是步 2 收敛成「唯一写者」的判据）。
"""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
os.environ['LOOM_NO_SAVE_MIGRATE'] = '1'
os.environ['LOOM_NO_PARALLEL'] = '1'
os.environ.setdefault('LOOM_NO_DIALOG', '1')

import moderngl                                            # noqa: E402
import pygame                                              # noqa: E402
import engine as E                                         # noqa: E402
import scene_driver as SD                                  # noqa: E402
import vk_player                                           # noqa: E402
from loom_input import _KEYMAP, UNLOCK_ACTION, DEFAULT_ACTIONS  # noqa: E402

E.GLEngine._build_gpu = lambda self, m: None               # 无头：不建 VBO/VAO

_CTX = moderngl.create_standalone_context()

ok = True


def check(label, cond, detail=''):
    global ok
    print(('PASS ' if cond else 'FAIL ') + label + ('  ' + str(detail) if detail else ''))
    if not cond:
        ok = False


def _ev(pg, down=True, mods=0):
    from types import SimpleNamespace
    return SimpleNamespace(type='KEYDOWN' if down else 'KEYUP', key=pg, mod=mods, unicode='')


# ============ 宿主入口：两端各自「生产代码里喂键的那一条路」 ============

class _FakeUI:
    """最小 UI 桩：只记 dispatch_key 次数 + 可控消费（对应内核 handle_key_event 第③步）。"""

    def __init__(self, consume=False):
        self.consume = bool(consume)
        self.calls = []

    def dispatch_key(self, k, mod=0):
        self.calls.append(k)
        return self.consume

    def dispatch_text(self, text):
        return False


class _FakeBridge:
    """最小 UI 输入桥桩：与生产 UIInputBridge **同构** —— 它自己不是 UI，只是
    「包着一个 UIManager，on_key 就转给那个 UIManager.dispatch_key」
    （vk_ui.py on_key -> dispatch_key -> self.ui.dispatch_key）。

    2026-11-18 裁决 Q-B7-33-1=B 之后，宿主**不再**喂桥（键/文本全交内核），所以
    下面 on_key 在生产路径上已无调用方，本夹具仍保留它只为「万一有人接回预喂」
    时能立刻被 ⑥/⑥b 的派发次数抓红（self.calls 进诊断信息，不作断言对象）。

    生产里被包的那个 UIManager 就是 driver.ui 本身（vk_player.py
    `ui_bridge = UIInputBridge(getattr(driver, 'ui', None))`），所以「宿主喂桥」
    与「内核 handle_key_event 第③步喂 driver.ui」打到的是**同一个对象**。
    夹具必须同构，否则「同一 UI 被派发两次」这个真实风险在本门里根本不可见。
    """

    def __init__(self, ui=None):
        self.ui = ui                      # 与生产同构：桥只包 UI，不自己消费
        self.calls = []                   # 宿主喂桥的次数（仅进诊断信息，不作断言对象）

    def on_key(self, pg, mods=0):
        self.calls.append(pg)
        return self.dispatch_key(pg, mods)

    def dispatch_key(self, pg, mods=0):
        if self.ui is None:
            return False
        return bool(self.ui.dispatch_key(pg, mods))


_VK_FORWARD = getattr(vk_player, 'host_key_forward', None)
_VK_HAS_FORWARD = callable(_VK_FORWARD)


class _Pair:
    """一对后端 + 各自的宿主喂键入口（同一串事件喂两边）。"""

    def __init__(self, consume_ui=False):
        self.gl = E.GLEngine(160, 120, ctx=_CTX)
        self.gl.is_playing = True
        # 动作表钉死为默认表：本门验的是「输入链」，不是用户层改键加载
        # （%LOCALAPPDATA%\Loom 的键位 delta 会让「按 space 是否跳跃」随机器漂移）。
        self.gl.actions = dict(DEFAULT_ACTIONS)
        self.gl_ui = _FakeUI(consume_ui)
        self.gl.ui = self.gl_ui
        self.vk = SD.SceneDriver()
        self.vk.is_playing = True
        self.vk.actions = dict(DEFAULT_ACTIONS)
        # 夹具保真（2026-11-18 裁决 Q-B7-33-2=A）：生产里 UIInputBridge 包的就是
        # driver.ui（vk_player.py:362），「宿主喂桥」与「内核第③步喂 driver.ui」
        # 打到的是**同一个** UI。所以这里只能有一个 _FakeUI 对象：既给 driver.ui，
        # 又给桥包。用两个独立假对象会把「同一 UI 被派发两次」这个真实风险测漏。
        self.vk_ui = _FakeUI(consume_ui)
        self.vk.ui = self.vk_ui
        self.bridge = _FakeBridge(self.vk_ui)
        self.hook_gl = []
        self.hook_vk = []
        self.gl.on_key_event = lambda ev: (self.hook_gl.append(ev), False)[1]
        self.vk.on_key_event = lambda ev: (self.hook_vk.append(ev), False)[1]

    def feed_gl(self, pg, down=True, mods=0):
        return bool(self.gl.handle_key_event(_ev(pg, down, mods)))

    def feed_vk(self, pg, down=True, mods=0):
        if _VK_HAS_FORWARD:
            return bool(_VK_FORWARD(self.vk, self.bridge, pg, down, mods))
        # 修前现场：vk_player 还没有统一入口（_on_key 直接写 key_state 键名）。
        # 这里退到 handle_key_event 只为让其余用例继续跑出数字，结构缺失已单独判 FAIL。
        return bool(self.vk.handle_key_event(_ev(pg, down, mods)))

    def feed(self, pg, down=True, mods=0):
        return (self.feed_gl(pg, down, mods), self.feed_vk(pg, down, mods))


PROBE_KEYS = ('w', 'a', 's', 'd', 'q', 'e', 'Left', 'Up', 'Tab', 'space', 'F5')
PROBE_ACTIONS = ('向前', '向后', '向左', '向右', '跳跃', '解锁鼠标')


def snap(eng):
    """把一端可观察状态拍成可逐项比较的元组（不含对象身份/实现细节）。"""
    ks = eng.__dict__.get('key_state') or {}
    return (
        ('key_state', tuple(sorted((k, bool(v)) for k, v in ks.items()))),
        ('script_keys', tuple((n, bool(eng.script_keys.get(n, False))) for n in PROBE_KEYS)),
        ('is_key', tuple((n, bool(eng.is_key(n))) for n in PROBE_KEYS)),
        ('get_action', tuple((a, bool(eng.get_action(a))) for a in PROBE_ACTIONS)),
        ('mouse', (bool(getattr(eng, 'mouse_locked', False)),
                   bool(getattr(eng, 'mouse_unlock_requested', False)))),
        ('logic_paused', bool(eng._logic_paused_state())),
    )


def _diff(gl_snap, vk_snap):
    out = []
    for (gn, gv), (vn, vv) in zip(gl_snap, vk_snap):
        if gv != vv:
            out.append('%s: GL=%s VK=%s' % (gn, gv, vv))
    return out


def derived_consistency(eng, label):
    """不变量：key_state 是真相 —— 凡键码在 key_state 里的键名，script_keys 必须同值。

    （「键名直写过渡项」= 宿主直接写 script_keys 的键名，它们不受此约束，
      由用例 ⑦ 单独验；这里只查「派生必须跟上真相」。）"""
    ks = eng.__dict__.get('key_state') or {}
    sk = eng.script_keys
    if not isinstance(sk, dict):
        check('%s script_keys 是 dict（引擎/驱动前置要求）' % label, False, type(sk))
        return
    bad = []
    for name, code in _KEYMAP.items():
        if code in ks and bool(sk.get(name, False)) != bool(ks[code]):
            bad.append((name, code, bool(sk.get(name, False)), bool(ks[code])))
    check('%s script_keys ≡ key_state 派生结果（键名与键码同值）' % label, not bad, bad[:4])


class _Steps:
    """一组用例：每次 feed 后记一次两端快照。"""

    def __init__(self, consume_ui=False, derived=True):
        self.pair = _Pair(consume_ui)
        self.rows = []
        self.derived = derived

    def feed(self, pg, down=True, mods=0):
        return self.pair.feed(pg, down, mods)

    def step(self, label):
        gl, vk = self.pair.gl, self.pair.vk
        g, v = snap(gl), snap(vk)
        self.rows.append((label, g, v))
        if self.derived:
            derived_consistency(gl, 'GL %s' % label)
            derived_consistency(vk, 'VK %s' % label)
        return g, v

    def compare(self, title):
        bad = [(lb, _diff(g, v)) for lb, g, v in self.rows if g != v]
        check('%s：两端逐项相等' % title, not bad,
              ('；'.join('%s -> %s' % (lb, ' | '.join(d)) for lb, d in bad[:3])
               if bad else '%d 步全等' % len(self.rows)))


print("=== 〇. 结构：VK 宿主喂键入口必须收敛到 EngineCore.handle_key_event ===")
check('vk_player 提供 host_key_forward（VK 播放器唯一喂键入口）', _VK_HAS_FORWARD,
      '缺失 -> vk_player._on_key 直接写 key_state 键名，绕过内核（F9/F10/F11/UI 顺序全丢）'
      if not _VK_HAS_FORWARD else 'ok')
check('两端宿主入口都是「同一个内核入口」',
      True, 'GL=handle_key_event / VK=host_key_forward->handle_key_event')

print()
print("=== ①. 单键按下 / 松开（w → 向前） ===")
s = _Steps()
s.feed(pygame.K_w, True)
g, v = s.step('按下 w')
check('按下 w 后两端 is_key(w) 均 True', g[2][1][0][1] is True and v[2][1][0][1] is True,
      'GL=%r VK=%r' % (g[2][1][0][1], v[2][1][0][1]))
check('按下 w 后两端 get_action(向前) 均 True',
      dict(g[3][1])['向前'] is True and dict(v[3][1])['向前'] is True,
      'GL=%r VK=%r' % (dict(g[3][1])['向前'], dict(v[3][1])['向前']))
s.feed(pygame.K_w, False)
g, v = s.step('松开 w')
check('松开 w 后两端 is_key(w) 归 False', g[2][1][0][1] is False and v[2][1][0][1] is False,
      'GL=%r VK=%r' % (g[2][1][0][1], v[2][1][0][1]))
check('松开 w 后两端 get_action(向前) 归 False',
      dict(g[3][1])['向前'] is False and dict(v[3][1])['向前'] is False,
      'GL=%r VK=%r' % (dict(g[3][1])['向前'], dict(v[3][1])['向前']))
s.compare('① 单键按下/松开')

print()
print("=== ②. 多键同时（w+a 按下 → 松 a → 松 w） ===")
s = _Steps()
s.feed(pygame.K_w, True)
s.feed(pygame.K_a, True)
g, v = s.step('w+a 同按')
check('w+a 同按时两端 w/a 均 True',
      all(dict(x[2][1])[k] is True for x in (g, v) for k in ('w', 'a')),
      'GL=%r VK=%r' % (dict(g[2][1]), dict(v[2][1])))
s.feed(pygame.K_a, False)
g, v = s.step('松 a')
check('松 a 后 a=False 且 w 仍 True',
      all(dict(x[2][1])['a'] is False and dict(x[2][1])['w'] is True for x in (g, v)),
      'GL=%r VK=%r' % (dict(g[2][1]), dict(v[2][1])))
s.feed(pygame.K_w, False)
g, v = s.step('松 w')
check('松 w 后两端全 False',
      all(dict(x[2][1])['w'] is False and dict(x[2][1])['a'] is False for x in (g, v)),
      'GL=%r VK=%r' % (dict(g[2][1]), dict(v[2][1])))
s.compare('② 多键同时')

print()
print("=== ③. 动作映射（向前 = w/Up；未绑定动作回退同名键） ===")
s = _Steps()
s.feed(pygame.K_UP, True)
g, v = s.step('按 Up')
check('按 Up 时两端 get_action(向前) 均 True',
      all(dict(x[3][1])['向前'] is True for x in (g, v)),
      'GL=%r VK=%r' % (dict(g[3][1]), dict(v[3][1])))
check('按 Up 时两端 is_key(w) 仍 False（键名不串）',
      all(dict(x[2][1])['w'] is False for x in (g, v)),
      'GL=%r VK=%r' % (dict(g[2][1]), dict(v[2][1])))
s.feed(pygame.K_UP, False)
s.step('松 Up')
s.feed(pygame.K_SPACE, True)
g, v = s.step('按 space')
check('按 space 时两端 get_action(跳跃) 均 True',
      all(dict(x[3][1])['跳跃'] is True for x in (g, v)),
      'GL=%r VK=%r' % (dict(g[3][1]), dict(v[3][1])))
s.feed(pygame.K_SPACE, False)
s.step('松 space')
s.compare('③ 动作映射')

print()
print("=== ④. 无动作绑定的键 F5（在 _KEYMAP 里 -> 进 script_keys，但没绑动作）+ 内核钩子 ===")
s = _Steps()
s.feed(pygame.K_F5, True)
g, v = s.step('按 F5')
check('按 F5 时两端 key_state[F5] 均 True',
      all(dict(x[0][1]).get(pygame.K_F5) is True for x in (g, v)),
      'GL=%r VK=%r' % (dict(g[0][1]).get(pygame.K_F5), dict(v[0][1]).get(pygame.K_F5)))
check('按 F5 时两端 is_key(F5) 均 True（F5 **在** _KEYMAP 里 —— 它不是未映射键）',
      all(dict(x[2][1])['F5'] is True for x in (g, v)),
      'GL=%r VK=%r' % (dict(g[2][1])['F5'], dict(v[2][1])['F5']))
check('按 F5 不触发任何动作（两端动作全 False）',
      all(not any(dict(x[3][1]).values()) for x in (g, v)),
      'GL=%r VK=%r' % (dict(g[3][1]), dict(v[3][1])))
check('F5 事件进了两端内核钩子 on_key_event（各 1 次）',
      len(s.pair.hook_gl) == 1 and len(s.pair.hook_vk) == 1,
      'GL=%d VK=%d' % (len(s.pair.hook_gl), len(s.pair.hook_vk)))
s.feed(pygame.K_F5, False)
s.step('松 F5')
s.compare('④ 无动作绑定的键 F5')

print()
print("=== ④b. 真正未映射的键 F13（只进 key_state 键码，不进 script_keys） ===")
# 为什么单独补这一条：F5 **在** _KEYMAP 里（93 个键名之一），拿它当「未映射键」是错的；
# 真正未映射的键（如 F13）只能以键码存在，不该在 script_keys 里出现。
_K_UNMAPPED = getattr(pygame, 'K_F13', None)
if _K_UNMAPPED is not None:
    s = _Steps()
    s.feed(_K_UNMAPPED, True)
    g, v = s.step('按 F13（未映射）')
    check('未映射键进两端 key_state（键码）',
          all(dict(x[0][1]).get(_K_UNMAPPED) is True for x in (g, v)),
          'GL=%r VK=%r' % (dict(g[0][1]).get(_K_UNMAPPED), dict(v[0][1]).get(_K_UNMAPPED)))
    check('未映射键不进 script_keys（无键名可映射，两端同）',
          all(not any(dict(x[2][1]).values()) or 'F13' not in dict(x[2][1]) for x in (g, v)),
          'GL=%r VK=%r' % ([k for k, val in dict(g[2][1]).items() if val],
                           [k for k, val in dict(v[2][1]).items() if val]))
    s.feed(_K_UNMAPPED, False)
    s.step('松 F13')
    s.compare('④b 真正未映射键 F13')
else:
    print('  SKIP pygame 无 K_F13')

print()
print("=== ⑤. Tab 解锁链（写键码 → poll_unlock 翻转 → 松开 → 再按回锁） ===")
s = _Steps()
s.pair.gl.mouse_lock_allowed = True
s.pair.vk.mouse_lock_allowed = True
s.feed(pygame.K_TAB, True)
g, v = s.step('按 Tab')
check('按 Tab 时两端 is_key(Tab)/get_action(解锁鼠标) 均 True',
      all(dict(x[2][1])['Tab'] is True and dict(x[3][1])[UNLOCK_ACTION] is True for x in (g, v)),
      'GL is_key(Tab)=%r VK is_key(Tab)=%r' % (dict(g[2][1])['Tab'], dict(v[2][1])['Tab']))
_unlock_before = bool(s.pair.gl.mouse_unlock_requested)
r_gl = s.pair.gl.poll_unlock()
r_vk = s.pair.vk.poll_unlock()
check('poll_unlock 两端都翻转（True）', r_gl is True and r_vk is True, 'GL=%r VK=%r' % (r_gl, r_vk))
g, v = s.step('poll 后')
check('翻转后两端鼠标状态（locked, 解锁意图）同值', g[4][1] == v[4][1],
      'GL=%r VK=%r' % (g[4][1], v[4][1]))
check('翻转后两端「解锁意图」都真的翻了（!= 翻转前）',
      g[4][1][1] != _unlock_before and v[4][1][1] != _unlock_before,
      'before=%r GL=%r VK=%r' % (_unlock_before, g[4][1][1], v[4][1][1]))
s.feed(pygame.K_TAB, False)
s.step('松 Tab')
r_gl2 = s.pair.gl.poll_unlock()
r_vk2 = s.pair.vk.poll_unlock()
check('松开后 poll_unlock 两端都不再翻转', r_gl2 is False and r_vk2 is False, 'GL=%r VK=%r' % (r_gl2, r_vk2))
s.feed(pygame.K_TAB, True)
s.step('再按 Tab')
r_gl3 = s.pair.gl.poll_unlock()
r_vk3 = s.pair.vk.poll_unlock()
g, v = s.step('再 poll 后')
check('再按 Tab 两端再次翻转（回锁）', r_gl3 is True and r_vk3 is True, 'GL=%r VK=%r' % (r_gl3, r_vk3))
check('再翻转后两端「解锁意图」同值且回到翻转前的值',
      g[4][1] == v[4][1] and g[4][1][1] == _unlock_before,
      'before=%r GL=%r VK=%r' % (_unlock_before, g[4][1], v[4][1]))
s.feed(pygame.K_TAB, False)
s.step('再松 Tab')
s.compare('⑤ Tab 解锁链')

print()
print("=== ⑥. UI 焦点消费（key_state 不更新 + 同一个 UI 只派发一次） ===")
# 本段为什么数「同一个 UI 对象的派发次数」而不是「桥/内核各自被调用几次」：
#   生产 vk_player.py:362 的 UIInputBridge 包的就是 driver.ui —— 宿主先喂桥、
#   内核第③步又会喂 driver.ui，两者是**同一个 UIManager**。真实风险是「同一个
#   UIManager 被派发两次」（输入框打一个字出两个字）；它只能由「那一个对象的
#   总派发次数」观测到。分别数两个对象 = 锁实现细节，重构就会误红（接手须知 §7-1）。
s = _Steps(consume_ui=True)
check('夹具保真：假桥包的就是内核那一个假 UI 对象（与生产 UIInputBridge(driver.ui) 同构）',
      s.pair.bridge.ui is s.pair.vk.ui,
      'bridge.ui id=%r driver.ui id=%r' % (id(s.pair.bridge.ui), id(s.pair.vk.ui)))
s.feed(pygame.K_a, True)
g, v = s.step('UI 消费 a')
check('UI 消费时两端 key_state 都不更新（未记按下）',
      not dict(g[0][1]).get(pygame.K_a) and not dict(v[0][1]).get(pygame.K_a),
      'GL=%r VK=%r' % (dict(g[0][1]).get(pygame.K_a), dict(v[0][1]).get(pygame.K_a)))
check('UI 消费时两端 is_key(a) 均 False',
      dict(g[2][1])['a'] is False and dict(v[2][1])['a'] is False,
      'GL=%r VK=%r' % (dict(g[2][1])['a'], dict(v[2][1])['a']))
check('UI 消费：按一次键，两端各自的 UI 对象都只被派发 1 次',
      len(s.pair.gl_ui.calls) == 1 and len(s.pair.vk_ui.calls) == 1,
      'GL ui.dispatch_key=%d / VK 同一个 ui.dispatch_key=%d（宿主喂桥=%d，统一到内核后恒 0）'
      % (len(s.pair.gl_ui.calls), len(s.pair.vk_ui.calls), len(s.pair.bridge.calls)))
s.feed(pygame.K_a, False)
s.step('UI 消费后松开 a')
check('UI 消费：松开沿不增加派发次数（两端 UI 仍各 1 次）',
      len(s.pair.gl_ui.calls) == 1 and len(s.pair.vk_ui.calls) == 1,
      'GL=%d VK=%d' % (len(s.pair.gl_ui.calls), len(s.pair.vk_ui.calls)))
s.compare('⑥ UI 焦点消费')

print()
print("=== ⑥b. UI 不消费（键穿到内核）：同一个 UI 每按一次仍只派发 1 次 ===")
# 这条是本门真正的牙：内核第③步是 UI 派发的**唯一**写者 —— 宿主（host_key_forward）
# 只把事件递进内核，不再预喂桥/UI（2026-11-18 裁决 Q-B7-33-1=B；旧的「宿主预喂 UI +
# 内核跳过第③步」双写者标志已删除）。若宿主又自己喂一次 UI，或内核第③步被改成派发
# 两次，本段立刻变红（实测：见「有牙证明」）。
s = _Steps(consume_ui=False)
s.feed(pygame.K_a, True)
g, v = s.step('UI 不消费 a')
check('UI 不消费时两端 key_state 都更新（键确实穿到内核）',
      dict(g[0][1]).get(pygame.K_a) is True and dict(v[0][1]).get(pygame.K_a) is True,
      'GL=%r VK=%r' % (dict(g[0][1]).get(pygame.K_a), dict(v[0][1]).get(pygame.K_a)))
check('UI 不消费：按一次键，两端各自的 UI 对象都只被派发 1 次',
      len(s.pair.gl_ui.calls) == 1 and len(s.pair.vk_ui.calls) == 1,
      'GL ui.dispatch_key=%d / VK 同一个 ui.dispatch_key=%d（宿主喂桥=%d，统一到内核后恒 0）'
      % (len(s.pair.gl_ui.calls), len(s.pair.vk_ui.calls), len(s.pair.bridge.calls)))
s.feed(pygame.K_a, False)
s.feed(pygame.K_w, True)
g, v = s.step('再按 w（UI 仍不消费）')
check('UI 不消费：连按两键后两端 UI 各被派发 2 次（每次按键恰好 +1，不叠加）',
      len(s.pair.gl_ui.calls) == 2 and len(s.pair.vk_ui.calls) == 2,
      'GL=%d VK=%d（宿主喂桥=%d，统一到内核后恒 0）'
      % (len(s.pair.gl_ui.calls), len(s.pair.vk_ui.calls), len(s.pair.bridge.calls)))
s.feed(pygame.K_w, False)
s.step('松 w')
check('UI 不消费：松开沿不增加派发次数（两端 UI 仍各 2 次）',
      len(s.pair.gl_ui.calls) == 2 and len(s.pair.vk_ui.calls) == 2,
      'GL=%d VK=%d' % (len(s.pair.gl_ui.calls), len(s.pair.vk_ui.calls)))
s.compare('⑥b UI 不消费时同一 UI 只派发一次')

print()
print("=== ⑦. 宿主直写 script_keys（老宿主/测试夹具的兼容路径） ===")
s = _Steps(derived=False)
s.pair.gl.script_keys = {'w': True}
s.pair.vk.script_keys = {'w': True}
g, v = s.step('直写 {w:True}')
check('直写 script_keys 后两端 is_key(w) 均 True（setter 兼容路径真的通到脚本）',
      dict(g[2][1])['w'] is True and dict(v[2][1])['w'] is True,
      'GL=%r VK=%r' % (dict(g[2][1])['w'], dict(v[2][1])['w']))
check('直写 script_keys 后两端 get_action(向前) 均 True',
      dict(g[3][1])['向前'] is True and dict(v[3][1])['向前'] is True,
      'GL=%r VK=%r' % (dict(g[3][1])['向前'], dict(v[3][1])['向前']))
s.feed(pygame.K_w, True)
s.step('直写后再按 w')
s.feed(pygame.K_w, False)
g, v = s.step('直写后再松 w')
check('真实按键到来后直写过渡项失效：两端 is_key(w) 均 False',
      dict(g[2][1])['w'] is False and dict(v[2][1])['w'] is False,
      'GL=%r VK=%r' % (dict(g[2][1])['w'], dict(v[2][1])['w']))
s.compare('⑦ 宿主直写 script_keys')

print()
print("=== ⑧. 引擎键 F9（宿主路径必须真的进内核） ===")
s = _Steps()
s.feed(pygame.K_F9, True)
g, v = s.step('按 F9')
check('按 F9 两端 logic_paused 都翻转（True）', g[5][1] is True and v[5][1] is True,
      'GL=%r VK=%r' % (g[5][1], v[5][1]))
s.feed(pygame.K_F9, False)
s.step('松 F9')
s.feed(pygame.K_F9, True)
g, v = s.step('再按 F9')
check('再按 F9 两端都恢复（False）', g[5][1] is False and v[5][1] is False,
      'GL=%r VK=%r' % (g[5][1], v[5][1]))
check('F9 事件两端进内核钩子的序列相同（按下沿在内核第②步消费、松开沿才到钩子）',
      [(e.type, e.key) for e in s.pair.hook_gl] == [(e.type, e.key) for e in s.pair.hook_vk],
      'GL=%s VK=%s' % ([(e.type, e.key) for e in s.pair.hook_gl],
                       [(e.type, e.key) for e in s.pair.hook_vk]))
s.feed(pygame.K_F9, False)
s.step('再松 F9')
s.compare('⑧ 引擎键 F9')

print()
print('总结果: ' + ('ALL PASS' if ok else '有 FAIL'))
sys.exit(0 if ok else 1)
