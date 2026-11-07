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


"""test_editor_playback_matrix.py — 编辑器播放态矩阵/快照刷新回归 (P-01, 2026-11-07).

缺陷: engine._logic_prep 只在 _frame_world 为 None/行数不符时重算, 而 EditorApp
播放分支 (editor.py) 也只在 None 时赋值 → 进播放后 _frame_world/_soa_snap 永久
冻结; 渲染矩阵/阴影 VP/碰撞 AABB/插值平面全部停在进播放位姿。

本测试用真实 EditorApp (无头桩) + 真实 _logic_prep / _refresh_play_matrices /
compute_*_matrices, 断言 actual.x=237 时逻辑矩阵、SoA 快照、渲染矩阵都 ≈237。
"""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
os.environ.setdefault('LOOM_NO_SAVE_MIGRATE', '1')

import numpy as np                                      # noqa: E402

from editor import EditorApp                            # noqa: E402
from engine import GameObject, Point3D                  # noqa: E402
from interp_state import InterpState                    # noqa: E402

ok = True


def check(label, cond, detail=''):
    global ok
    print(('PASS ' if cond else 'FAIL ') + label + ('  ' + str(detail) if detail else ''))
    if not cond:
        ok = False


def tx(mat):
    """行向量约定: 平移在 M[3][0]。"""
    return float(mat[0][3, 0])


def _make_editor():
    ed = EditorApp.__new__(EditorApp)
    m = GameObject(None, (0.0, 0.0, 0.0), (0.0, 0.0, 0.0), name='播放测试体')
    ed.models = [m]
    ed.materials = []
    ed.lights = []
    ed.cameras = []
    ed.is_playing = True
    ed._struct_gen = 0
    ed._logic_gen = 0
    ed._prep_sig = None
    ed._prep_aabbs = None
    ed._prep_light_vps = None
    ed._prep_pairs = None
    ed._disp_gen = -1
    ed._interp = InterpState(ed.models)
    ed._render_world = None
    ed._frame_world = None
    ed._profile = lambda name, fn: fn()
    # 只测矩阵/快照链: AABB/光源/碰撞对用零成本桩 (它们另有测试)
    seen = {'fw': None}
    ed._model_aabbs_par = lambda models, fw, visible_only=False: seen.__setitem__('fw', fw) or []
    ed._compute_light_vps = lambda aabbs: {}
    ed._collision_pairs_parallel = lambda aabbs=None: []
    return ed, m, seen


def t_playback_matrix_follows_actual():
    ed, m, seen = _make_editor()
    # 进播放: 编辑态矩阵 (x=0) + 插值快照对齐
    ed._frame_world = ed.compute_world_matrices(ed.models)
    ed._interp.advance()
    ed._interp.align()
    check('进播放初态逻辑矩阵 tx=0', abs(tx(ed._frame_world)) < 1e-9, tx(ed._frame_world))

    m.position = Point3D(237.0, 0.0, 0.0)
    ed._logic_prep(1.0 / 30.0)

    check('P-01 逻辑矩阵跟随 actual.x=237',
          abs(tx(ed._frame_world) - 237.0) < 1e-9, tx(ed._frame_world))
    snap = getattr(ed, '_soa_snap', None)
    check('P-01 SoA 快照跟随 actual.x=237',
          snap is not None and abs(float(snap[2][0, 0]) - 237.0) < 1e-9,
          None if snap is None else float(snap[2][0, 0]))
    check('P-01 AABB prep 用的是新矩阵', seen['fw'] is ed._frame_world)

    planes = (snap[2], snap[3], snap[4]) if snap is not None else None
    ed._interp.advance(planes)
    ed._interp.alpha = 1.0
    ed._render_world = None
    ed._refresh_play_matrices(ed._interp)
    check('P-01 渲染矩阵跟随 actual.x=237',
          abs(tx(ed._render_world) - 237.0) < 1e-9, tx(ed._render_world))

    # 连续逻辑帧: 不能停在第一次刷新
    m.position = Point3D(10.0, 0.0, 0.0)
    ed._logic_prep(1.0 / 30.0)
    check('P-01 后续逻辑帧继续刷新 (不冻结)',
          abs(tx(ed._frame_world) - 10.0) < 1e-9, tx(ed._frame_world))


def t_first_frame_does_not_alias_render_matrix():
    ed, m, _seen = _make_editor()
    m.position = Point3D(237.0, 0.0, 0.0)
    # 模拟旧 bug 的使能条件: _frame_world=None 而 _render_world 已有一份插值矩阵
    sentinel = np.eye(4, dtype=np.float64)[None, :, :]
    sentinel[0, 3, 0] = 999.0
    ed._render_world = sentinel
    ed._interp.static_frame = lambda: True
    ed._refresh_play_matrices(ed._interp)
    check('首帧兜底不把 _render_world 别名给 _frame_world',
          ed._frame_world is not ed._render_world)
    check('首帧兜底 _frame_world 用当前位形 (237)',
          abs(tx(ed._frame_world) - 237.0) < 1e-9, tx(ed._frame_world))
    check('_render_world 保持插值矩阵不被覆盖',
          abs(tx(ed._render_world) - 999.0) < 1e-9, tx(ed._render_world))


t_playback_matrix_follows_actual()
t_first_frame_does_not_alias_render_matrix()
print()
print('总结果:', 'ALL PASS' if ok else '有 FAIL')
sys.exit(0 if ok else 1)
