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


"""test_collision_events_small_scene.py — 小场景/关并行碰撞事件兜底 (P-02, 2026-11-07).

缺陷: engine._logic_prep 只在 _frame_pool 非空且 n>=32 时算 _prep_pairs, 否则写
[]; 渲染 split 路径只派发该列表 → n<32 或 LOOM_NO_PARALLEL 时 on_collision_* /
on_trigger_* 永不触发 (旧内联路径能触发)。

本测试用真实 GLEngine (离屏 GL 上下文 + 无 GPU 桩) 驱动真实检测/派发:
  · n=3 小场景 → 3 对 → 6 次 start (有池/无池都一样);
  · n=40 无池 → split 派发次数与旧内联路径逐位一致 (且 >0);
  · trigger 对 → on_trigger_enter 正常派发。
"""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
os.environ['LOOM_NO_SAVE_MIGRATE'] = '1'
os.environ['LOOM_NO_PARALLEL'] = '1'   # 确定性: 不建帧池/脚本线程

import moderngl                                          # noqa: E402
import engine as E                                       # noqa: E402
from engine import GLEngine, Point3D                     # noqa: E402
from mesh import create_cube                             # noqa: E402

E.GLEngine._build_gpu = lambda self, m: None             # 无头: 不建 VBO/VAO

ok = True


def check(label, cond, detail=''):
    global ok
    print(('PASS ' if cond else 'FAIL ') + label + ('  ' + str(detail) if detail else ''))
    if not cond:
        ok = False


_CTX = moderngl.create_standalone_context()


class Counter:
    def __init__(self):
        self.start = 0
        self.trigger = 0

    def on_collision_start(self, other):
        self.start += 1

    def on_trigger_enter(self, other):
        self.trigger += 1


def attach(m):
    sc = m.add_script(None)
    c = Counter()
    sc._script = c
    return c


def fresh(n, spacing=0.4, trigger_first=False):
    e = GLEngine(320, 240, ctx=_CTX)
    for m in list(e.models):
        e.remove_model(m)
    e.is_playing = True
    e.parallel = None
    e._collision_pool = None
    e._frame_pool = None
    out = []
    for i in range(n):
        m = e.add_model(create_cube(1.0),
                        Point3D(i * spacing, 0.0, 0.0),
                        Point3D(0.0, 0.0, 0.0), name='c%d' % i)
        if trigger_first and i == 0:
            m.collider.is_trigger = True
        out.append(m)
    return e, out


def reset(ms, counters):
    for c in counters:
        c.start = 0
        c.trigger = 0
    for m in ms:
        m._colliding = set()


def t_small_scene_no_pool():
    e, ms = fresh(3)
    cs = [attach(m) for m in ms]
    e._frame_world = e.compute_world_matrices(e.models)
    e._logic_prep(1.0 / 30.0)
    check('P-02 n=3 无池 _prep_pairs 非空',
          e._prep_pairs is not None and len(e._prep_pairs) == 3,
          None if e._prep_pairs is None else len(e._prep_pairs))
    e._dispatch_collision_events(e._prep_pairs)
    check('P-02 n=3 无池 start 事件 = 6',
          sum(c.start for c in cs) == 6, sum(c.start for c in cs))


def t_small_scene_with_pool_object():
    e, ms = fresh(3)
    cs = [attach(m) for m in ms]
    e._frame_pool = object()      # 模拟"池已建但 n<32"分支
    e._frame_world = e.compute_world_matrices(e.models)
    e._logic_prep(1.0 / 30.0)
    e._dispatch_collision_events(e._prep_pairs)
    check('P-02 n=3 有池 start 事件 = 6',
          sum(c.start for c in cs) == 6, sum(c.start for c in cs))


def t_large_scene_no_pool_matches_inline():
    e, ms = fresh(40)
    cs = [attach(m) for m in ms]
    # 旧内联路径基线 (parallel=None → _collision_events_inline)
    e._frame_world = e.compute_world_matrices(e.models)
    e._update_collision_events(1.0 / 30.0)
    inline = sum(c.start for c in cs)
    reset(ms, cs)

    # split prep 路径 (无帧池)
    e._frame_pool = None
    e._prep_sig = None
    e._logic_prep(1.0 / 30.0)
    n_pairs = 0 if e._prep_pairs is None else len(e._prep_pairs)
    e._dispatch_collision_events(e._prep_pairs)
    split = sum(c.start for c in cs)
    check('P-02 n=40 无池 _prep_pairs 非空', n_pairs > 0, n_pairs)
    check('P-02 n=40 无池 split 事件 == 旧内联 (逐位同口径)',
          split == inline and inline > 0, 'split=%d inline=%d' % (split, inline))
    check('P-02 n=40 无池 每对派发两次 (i/j 各一次)',
          n_pairs * 2 == inline, 'pairs=%d inline=%d' % (n_pairs, inline))


def t_trigger_events_small_scene():
    e, ms = fresh(2, trigger_first=True)
    cs = [attach(m) for m in ms]
    e._frame_world = e.compute_world_matrices(e.models)
    e._logic_prep(1.0 / 30.0)
    e._dispatch_collision_events(e._prep_pairs)
    check('P-02 n=2 trigger 对派发 on_trigger_enter = 2',
          sum(c.trigger for c in cs) == 2, sum(c.trigger for c in cs))


t_small_scene_no_pool()
t_small_scene_with_pool_object()
t_large_scene_no_pool_matches_inline()
t_trigger_events_small_scene()
print()
print('总结果:', 'ALL PASS' if ok else '有 FAIL')
sys.exit(0 if ok else 1)
