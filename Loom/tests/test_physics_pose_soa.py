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

    print()
    print('test_physics_pose_soa:', 'ALL PASS' if ok else 'HAS FAILURES')
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
