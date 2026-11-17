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


"""test_host_event_parity.py — S1 门：**宿主事件 API 与后端无关**。

人类裁决（2026-11-17）：
  「用户不管用的是VK后端还是GL后端都用的是完全一样的**事件API**，底层的区别由引擎进行屏蔽。」

因此本门验的不是「两端方法名一样」（那只是必要条件），而是：
  ① 结构：GLEngine 与 SceneDriver **都**继承同一个后端无关内核 EngineCore；
  ② 入口：两端都暴露同一组宿主事件入口（handle_key_event / handle_text_input /
     handle_quit_request）与同一组可覆写钩子（on_key_event / on_text_input / on_quit_request）；
  ③ 语义：**同一串事件喂进两端 → 同一串可观察结果**（key_state 变化、是否被消费、退出许可）。

为什么必须有这一条：方法名对齐 ≠ 不受后端影响。若一端由 GLFW 回调触发、另一端由播放器手调，
宿主仍然要写两套代码 —— 那还是受后端影响。本门把「同一串事件 → 同一结果」钉死。
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
from engine_core import EngineCore                         # noqa: E402

E.GLEngine._build_gpu = lambda self, m: None               # 无头：不建 VBO/VAO

ok = True


def check(label, cond, detail=''):
    global ok
    print(('PASS ' if cond else 'FAIL ') + label + ('  ' + str(detail) if detail else ''))
    if not cond:
        ok = False


_CTX = moderngl.create_standalone_context()

ENTRY = ('handle_key_event', 'handle_text_input', 'handle_quit_request')
HOOKS = ('on_key_event', 'on_text_input', 'on_quit_request')


def mk_gl():
    return E.GLEngine(160, 120, ctx=_CTX)


def mk_vk():
    return SD.SceneDriver()


def key_ev(k, down=True, mod=0):
    from types import SimpleNamespace
    return SimpleNamespace(type='KEYDOWN' if down else 'KEYUP', key=k, mod=mod, unicode='')


def text_ev(s):
    from types import SimpleNamespace
    return SimpleNamespace(type='TEXTINPUT', text=s)


print("=== 一. 结构：两端继承同一个后端无关内核 ===")
check('GLEngine 继承 EngineCore', issubclass(E.GLEngine, EngineCore),
      [c.__name__ for c in E.GLEngine.__mro__[:4]])
check('SceneDriver 继承 EngineCore', issubclass(SD.SceneDriver, EngineCore),
      [c.__name__ for c in SD.SceneDriver.__mro__[:4]])
check('EngineCore 不是 GLEngine/SceneDriver 的别名（同一个类对象）',
      E.EngineCore is SD.EngineCore is EngineCore)

print()
print("=== 二. 入口与钩子：两端都有、都是同一份实现 ===")
for name in ENTRY + HOOKS:
    g = getattr(E.GLEngine, name, None)
    v = getattr(SD.SceneDriver, name, None)
    check('两端都有 %s' % name, callable(g) and callable(v),
          'GL=%s VK=%s' % (g is not None, v is not None))
check('宿主入口是 EngineCore 的实现（不是各写一遍）',
      all(getattr(E.GLEngine, n) is getattr(EngineCore, n) for n in ENTRY),
      [n for n in ENTRY if getattr(E.GLEngine, n) is not getattr(EngineCore, n)])

print()
print("=== 三. 语义对拍：同一串事件 → 同一串结果 ===")


def run_sequence(mk):
    """喂同一串事件，返回可观察结果（两端必须逐项相等）。"""
    eng = mk()
    out = []
    k_w = pygame.K_w
    # 1) 未绑定键按下：不应进 key_state，也不应被消费
    out.append(('unknown_key_press', eng.handle_key_event(key_ev(k_w, True))))
    # 2) 已知动作键按下（actions 里的第一个键）
    k_known = list(getattr(eng, 'key_state', {}) or {})
    if k_known:
        kk = k_known[0]
        out.append(('known_key_press', eng.handle_key_event(key_ev(kk, True)),
                    bool(eng.key_state.get(kk))))
        out.append(('known_key_release', eng.handle_key_event(key_ev(kk, False)),
                    bool(eng.key_state.get(kk))))
    else:
        out.append(('known_key_press', 'NO_KEY_STATE', None))
    # 3) 文本输入（默认钩子不消费）
    out.append(('text_default', eng.handle_text_input(text_ev('x'))))
    # 4) 退出请求（默认允许）
    out.append(('quit_default', eng.handle_quit_request()))
    return out


gl_seq = run_sequence(mk_gl)
vk_seq = run_sequence(mk_vk)
print('  GL: %s' % (gl_seq,))
print('  VK: %s' % (vk_seq,))
check('同一串事件 → 两端结果逐项相等', gl_seq == vk_seq,
      'GL=%s VK=%s' % (gl_seq, vk_seq))

print()
print("=== 四. 钩子覆写：消费/拒绝在两端同语义 ===")


class ConsumingGL(E.GLEngine):
    def on_key_event(self, ev):
        return True          # 全消费

    def on_quit_request(self):
        return False         # 拒绝退出


class ConsumingVK(SD.SceneDriver):
    def on_key_event(self, ev):
        return True

    def on_quit_request(self):
        return False


def run_override(cls, ctor):
    eng = ctor()
    k_known = list(getattr(eng, 'key_state', {}) or {})
    res = []
    if k_known:
        kk = k_known[0]
        res.append(('consumed', eng.handle_key_event(key_ev(kk, True)),
                    bool(eng.key_state.get(kk))))
    else:
        res.append(('consumed', 'NO_KEY_STATE', None))
    res.append(('quit_denied', eng.handle_quit_request()))
    return res


gl_ov = run_override(ConsumingGL, lambda: ConsumingGL(160, 120, ctx=_CTX))
vk_ov = run_override(ConsumingVK, lambda: ConsumingVK())
print('  GL: %s' % (gl_ov,))
print('  VK: %s' % (vk_ov,))
check('钩子覆写后两端结果逐项相等', gl_ov == vk_ov, 'GL=%s VK=%s' % (gl_ov, vk_ov))
check('消费键后 key_state **不**更新（两端同）',
      (gl_ov[0][2] is False) and (vk_ov[0][2] is False),
      'GL=%s VK=%s' % (gl_ov[0][2], vk_ov[0][2]))
check('钩子拒绝退出 → 两端都返回 False',
      gl_ov[-1] == vk_ov[-1] == ('quit_denied', False),
      'GL=%s VK=%s' % (gl_ov[-1], vk_ov[-1]))

print()
print('总结果: ' + ('ALL PASS' if ok else '有 FAIL'))
sys.exit(0 if ok else 1)
