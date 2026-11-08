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


"""test_add_script_cache.py — update_scripts 脚本缓存失效回归 (P-03, 2026-11-07).

缺陷: engine.update_scripts 的 _has_scripts_cached 只以 _struct_gen 作失效键;
GameObject.add_script 只 append 组件、不 bump 结构代 → 无脚本场景运行期挂脚本
后缓存 False 被永久钉住, update_scripts 入口直接 return, 新脚本永不执行。

修复: ScriptComponent.__init__ bump 类级 _script_gen, engine 缓存键 =
(结构代, 脚本创建代)。本测试用真实 GLEngine 桩 + 真实 GameObject/ScriptComponent,
断言 False→True 转换与"早退确实被打开"。
"""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

import script_glue                                       # noqa: E402
from engine import GLEngine, GameObject, ScriptComponent  # noqa: E402
from engine import DEFAULT_ACTIONS   # N3: 桩需要最小键位表（update_scripts 首行轮询解锁键）

ok = True


def check(label, cond, detail=''):
    global ok
    print(('PASS ' if cond else 'FAIL ') + label + ('  ' + str(detail) if detail else ''))
    if not cond:
        ok = False


def _stub_engine():
    e = GLEngine.__new__(GLEngine)
    e.models = []
    e._struct_gen = 0
    # 2026-11-08 N3: 解锁键轮询在 update_scripts 首行, 桩缺 actions/script_keys 时
    # 轮询根本不会执行(假绿)。这里补最小可用输入状态, 让轮询真的跑起来。
    e.actions = dict(DEFAULT_ACTIONS)
    e.script_keys = {}
    e.mouse_locked = False
    return e


def _model(name='s'):
    return GameObject(None, (0.0, 0.0, 0.0), (0.0, 0.0, 0.0), name=name)


def t_false_to_true():
    hits = {'n': 0}
    old = script_glue.handle
    script_glue.handle = lambda: hits.__setitem__('n', hits['n'] + 1)
    try:
        e = _stub_engine()
        m = _model()
        e.models = [m]
        e.update_scripts(0.01)
        check('无脚本场景首帧缓存=False', e._has_scripts_cached is False)
        check('无脚本场景首帧早退 (未调 handle)', hits['n'] == 0, hits['n'])

        g0 = ScriptComponent._script_gen
        m.add_script(None)
        check('add_script 构造 ScriptComponent → 创建代 +1',
              ScriptComponent._script_gen == g0 + 1)
        e.update_scripts(0.01)
        check('P-03 add_script 后缓存失效为 True', e._has_scripts_cached is True)
        check('P-03 add_script 后早退被打开 (handle 被调)', hits['n'] == 1, hits['n'])

        # 结构代不变但再挂一个脚本 → 缓存键继续失效 (仍 True, 不早退)
        m.add_script(None)
        e.update_scripts(0.01)
        check('再次 add_script 仍进入脚本调度', hits['n'] == 2, hits['n'])
    finally:
        script_glue.handle = old


def t_scripts_from_start():
    hits = {'n': 0}
    old = script_glue.handle
    script_glue.handle = lambda: hits.__setitem__('n', hits['n'] + 1)
    try:
        e = _stub_engine()
        m = _model()
        m.add_script(None)
        e.models = [m]
        e.update_scripts(0.01)
        check('首帧已有脚本 → 缓存 True', e._has_scripts_cached is True)
        check('首帧已有脚本 → 不早退', hits['n'] == 1, hits['n'])
    finally:
        script_glue.handle = old


def t_remove_script_does_not_crash():
    old = script_glue.handle
    script_glue.handle = lambda: None
    try:
        e = _stub_engine()
        m = _model()
        m.add_script(None)
        e.models = [m]
        e.update_scripts(0.01)
        m.remove_script(0)
        e.update_scripts(0.01)   # 缓存 True 但无脚本 → 循环空转, 不崩
        check('remove_script 后仍可安全调用 update_scripts',
              e._has_scripts_cached is True)
        m.clear_scripts()
        e.update_scripts(0.01)
        check('clear_scripts 后仍可安全调用 update_scripts', True)
    finally:
        script_glue.handle = old


def t_engine_instances_independent():
    old = script_glue.handle
    script_glue.handle = lambda: None
    try:
        e1 = _stub_engine()
        m1 = _model('a')
        m1.add_script(None)
        e1.models = [m1]
        e1.update_scripts(0.01)
        e2 = _stub_engine()
        m2 = _model('b')
        e2.models = [m2]
        e2.update_scripts(0.01)
        check('另一引擎无脚本 → 自己的缓存 False', e2._has_scripts_cached is False)
        check('引擎间缓存不串用', e1._has_scripts_cached is True)
    finally:
        script_glue.handle = old


t_false_to_true()
t_scripts_from_start()
t_remove_script_does_not_crash()
t_engine_instances_independent()
print()
print('总结果:', 'ALL PASS' if ok else '有 FAIL')
sys.exit(0 if ok else 1)
