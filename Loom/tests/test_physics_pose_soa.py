# -*- coding: utf-8 -*-
"""test_physics_pose_soa.py — D2: 位姿 SoA 取数 (_pose_rows) 的回退面断言.

断言（这是 D2 的"宁可慢不可错"闸门）:
  ① 正常: (models,pos,rot) 平面 -> (n,6) f64 行, 数值**逐位等于**同一批 Point3D 分量
  ② pose=None -> None (调用方回退属性链)
  ③ 形状不符 (行数/列数/pos 与 rot 不一致) -> None
  ④ 节点不在平面 models 里 (祖先/幽灵) -> None  ← 防 id 复用错配
  ⑤ models 列表换了 (identity 变) -> 缓存重建, 旧节点仍返回 None
  ⑥ 空节点集 -> (0,6) 空行 (不炸)
"""
import sys as _sys_utf8
try:
    _sys_utf8.stdout.reconfigure(encoding='utf-8', errors='replace')
    _sys_utf8.stderr.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
os.chdir(ROOT)

import physics_bridge                                        # noqa: E402


class StubModel:
    """最小模型桩: 只需 position / rotation 两个 Point3D 属性."""

    def __init__(self, p, r):
        self.position = tuple(float(v) for v in p)
        self.rotation = tuple(float(v) for v in r)


ok = True


def check(label, cond, detail=''):
    global ok
    print(('PASS ' if cond else 'FAIL ') + label + ('  ' + str(detail) if detail else ''))
    if not cond:
        ok = False


def main():
    br = physics_bridge.PhysicsWorldBridge.__new__(physics_bridge.PhysicsWorldBridge)
    ms = [StubModel((1, 2, 3), (0, 0, 0)),
          StubModel((4, 5, 6), (0.1, 0.2, 0.3)),
          StubModel((-1, -2, -3), (1.0, 0.0, 0.0))]
    pos = np.array([[m.position[0], m.position[1], m.position[2]] for m in ms],
                   dtype=np.float64)
    rot = np.array([[m.rotation[0], m.rotation[1], m.rotation[2]] for m in ms],
                   dtype=np.float64)
    pose = (ms, pos, rot)

    rows = br._pose_rows(ms, pose)
    check('① 形状 (n,6)', rows is not None and rows.shape == (3, 6), None if rows is None else rows.shape)
    exp = np.hstack([pos, rot])
    check('① 数值逐位等于 Point3D 分量', rows is not None and np.array_equal(rows, exp))

    check('② pose=None -> None', br._pose_rows(ms, None) is None)

    check('③ 行数不符 -> None',
          br._pose_rows(ms, (ms, pos[:2], rot[:2])) is None)
    check('③ rot 形状不一致 -> None',
          br._pose_rows(ms, (ms, pos, rot[:, :2])) is None)
    check('③ models 长度与平面不符 -> None',
          br._pose_rows(ms, (ms[:2], pos, rot)) is None)

    ghost = StubModel((9, 9, 9), (0, 0, 0))
    check('④ 不在平面里的节点 -> None (防 id 复用错配)',
          br._pose_rows(ms + [ghost], pose) is None)

    # ⑤ models 列表 identity 变 -> 缓存重建; 旧节点不在新表 -> None
    ms2 = [StubModel((1, 1, 1), (0, 0, 0))]
    pos2 = np.array([[1.0, 1.0, 1.0]]); rot2 = np.zeros((1, 3))
    check('⑤ 换 models 列表后旧节点 -> None', br._pose_rows(ms, (ms2, pos2, rot2)) is None)
    rows2 = br._pose_rows(ms2, (ms2, pos2, rot2))
    check('⑤ 新列表节点取数正常', rows2 is not None and np.array_equal(rows2, np.hstack([pos2, rot2])))

    empty = br._pose_rows([], pose)
    check('⑥ 空节点集 -> (0,6)', empty is not None and empty.shape == (0, 6))

    # ---------------- 入口级 (V-02 补): _dirty_mask_batch 真实入口 A/B ----------------
    import copy as _copy
    import time as _t
    from collections import namedtuple as _nt
    _P3 = _nt('_P3', 'x y z')

    class _Go:
        """GameObject 最小面: position/rotation/parent (与 Point3D 同读法)."""
        __slots__ = ('position', 'rotation', 'parent', 'name')

        def __init__(self, i):
            self.position = _P3(float(i), 0.0, 0.0)
            self.rotation = _P3(0.0, 0.0, 0.0)
            self.parent = None
            self.name = 'g%d' % i

    nodes_models = [_Go(i) for i in range(120)]
    # 造一条父子树: 20..39 挂在 0..19 下, 40..59 挂在 20..39 下 (祖先链传播可观测)
    for i in range(20, 40):
        nodes_models[i].parent = nodes_models[i - 20]
    for i in range(40, 60):
        nodes_models[i].parent = nodes_models[i - 20]
    entries = [{'model': m} for m in nodes_models[:100]]

    b2 = physics_bridge.PhysicsWorldBridge.__new__(physics_bridge.PhysicsWorldBridge)
    b2._last_sync = {}
    b2._entries = entries

    def _planes():
        pos = np.array([m.position for m in nodes_models], dtype=np.float64)
        rot = np.array([m.rotation for m in nodes_models], dtype=np.float64)
        return (nodes_models, pos, rot)

    # 首帧: 惰性基线建立 -> 全不脏
    m0 = b2._dirty_mask_batch(entries, pose=_planes())
    check('入口级: 首帧全不脏 (惰性基线)', all(v is False for v in m0.values()), sum(m0.values()))

    # 移动一部分 (含祖先 -> 传播给子)
    for i in (0, 25, 45, 70, 99):
        nodes_models[i].position = _P3(float(i) + 0.5, 0.0, 0.0)
    snap = {k: [list(v[0]), list(v[1]), list(v[2])] for k, v in b2._last_sync.items()}
    a = b2._dirty_mask_batch(entries, pose=None)          # 属性链路径
    post_a = {k: (tuple(v[0]), tuple(v[1]), tuple(v[2])) for k, v in b2._last_sync.items()}
    b2._last_sync.clear()
    b2._last_sync.update(snap)
    b2._dmb_cache = None
    bb = b2._dirty_mask_batch(entries, pose=_planes())    # SoA 路径
    post_b = {k: (tuple(v[0]), tuple(v[1]), tuple(v[2])) for k, v in b2._last_sync.items()}
    check('入口级: 掩码与属性链路径全等', a == bb,
          [(k, a.get(k), bb.get(k)) for k in set(a) | set(bb) if a.get(k) != bb.get(k)][:3])
    check('入口级: 后态 _last_sync 全等', post_a == post_b)
    check('入口级: 祖先传播生效 (0 的子 20/40 也被标脏)',
          bool(bb.get(id(nodes_models[20])) or bb.get(id(nodes_models[40]))),
          {k: bb.get(k) for k in (id(nodes_models[20]), id(nodes_models[40]))})

    # 性能门禁 (2-3x 余量): SoA 路径单次 <= 3ms (120 节点, 实测 ~0.3-0.6ms)
    b2._last_sync = {}
    b2._dmb_cache = None
    for _ in range(3):
        b2._dirty_mask_batch(entries, pose=_planes())
    t0 = _t.perf_counter()
    for _ in range(30):
        b2._last_sync = {}
        b2._dmb_cache = None
        b2._dirty_mask_batch(entries, pose=_planes())
    dt = (_t.perf_counter() - t0) / 30 * 1000.0
    check('性能门禁: _dirty_mask_batch <= 3.0 ms/次 (120 节点, 实测 %.2f)' % dt, dt <= 3.0)

    print()
    print('test_physics_pose_soa:', 'ALL PASS' if ok else 'HAS FAILURES')
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
