# -*- coding: utf-8 -*-
"""
interp_check.py — 分离批2 插值层对拍 (纯逻辑桩)

断言 (设计 §九):
  1. alpha=0 → 输出=prev; alpha→1 → 输出→curr;
  2. alpha=1 时 compute_render_matrices 与 compute_world_matrices 逐位一致
     (插值数学=同管道 S@R@T);
  3. 静止场景 (无逻辑位移) render_pose 输出 = 逻辑矩阵 (static_frame=True,
     桶闸仍命中);
  4. 旋转球连续性: 相邻渲染帧插值角度差 = ω×dt渲染 (无 30Hz 阶梯锯齿).
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..', '..'))
os.environ['LOOM_NO_PARALLEL'] = '1'

import numpy as np
import engine as E
from mesh import create_cube, create_sphere

E.GLEngine._build_gpu = lambda self, m: None

ok = True


def check(label, cond, detail=""):
    global ok
    print(("PASS " if cond else "FAIL ") + label + ("  " + detail if detail else ""))
    if not cond:
        ok = False


def make_engine():
    eng = E.GLEngine.__new__(E.GLEngine)
    eng.models = []
    eng.materials = []
    eng.lights = []
    eng.cameras = []
    eng.current_model_index = 0
    eng._split_enable = True
    eng._clock = None
    eng._interp = None
    eng._render_world = None
    eng._logic_steps = 0
    eng._logic_gen = 0
    eng._prep_aabbs = None
    eng._prep_light_vps = None
    eng._prep_pairs = None
    eng._prep_sig = None
    eng._disp_gen = -1
    eng._pipe_disabled = False
    eng.is_playing = True
    E.GLEngine._ensure_split(eng)
    return eng


def main():
    eng = make_engine()
    balls = []
    for i in range(8):
        b = eng.add_model(create_sphere(1.0), E.Point3D(i * 1.0, 3.0 + i * 2.0, 0.0),
                          E.Point3D(0, 0, 0), name='球%d' % i)
        balls.append(b)
    from interp_state import InterpState
    eng._interp = InterpState(eng.models)

    # 抓两个逻辑帧位姿
    eng._logic_frame(1.0 / 30.0)     # 逻辑步1: curr=初值, prev=空→advance 只建 curr
    prev_pos = [b.position.y for b in balls]
    # 模拟物理移动: 直接改位置 (模拟逻辑帧内位移)
    for b in balls:
        b.position = E.Point3D(b.position.x, b.position.y + 0.3, b.position.z)
    eng._interp.advance()            # prev=初值, curr=+0.3

    # ---- 1. alpha 端点 ----
    it = eng._interp
    pos0, _, _ = it.render_pose(0.0, eng.models)
    np.testing.assert_allclose(pos0[:, 1], np.array(prev_pos), atol=1e-12)
    check("alpha=0 输出=prev (上一逻辑帧)", True)
    pos1, _, _ = it.render_pose(1.0, eng.models)
    np.testing.assert_allclose(pos1[:, 1], np.array([b.position.y for b in balls]),
                               atol=1e-12)
    check("alpha=1 输出=curr", True)
    posh, _, _ = it.render_pose(0.5, eng.models)
    mid = (np.array(prev_pos) + np.array([b.position.y for b in balls])) / 2
    np.testing.assert_allclose(posh[:, 1], mid, atol=1e-12)
    check("alpha=0.5 线性中点", True)

    # ---- 2. alpha=1 渲染矩阵 == 逻辑矩阵 ----
    rw = eng.compute_render_matrices(eng.models)
    # 手工把 interp 平面喂到 alpha=1 → 矩阵应等于逻辑位姿矩阵
    it.render_pose(1.0, eng.models)
    rw1 = eng.compute_render_matrices(eng.models)
    lw = eng.compute_world_matrices(eng.models)
    np.testing.assert_allclose(rw1, lw, atol=1e-9)
    check("alpha=1 渲染矩阵==逻辑矩阵 (S@R@T 同管道)", True)

    # ---- 3. 静止场景 static_frame ----
    eng2 = make_engine()
    cubes = [eng2.add_model(create_cube(1.0), E.Point3D(i, 0, 0), E.Point3D(0, 0, 0))
             for i in range(4)]
    eng2._interp = InterpState(eng2.models)
    eng2._interp.advance()
    eng2._interp.advance()
    check("静止场景 static_frame=True (桶闸红利保持)", eng2._interp.static_frame())
    cubes[0].position = E.Point3D(99, 0, 0)
    eng2._interp.advance()
    check("有位移帧 static_frame=False", not eng2._interp.static_frame())

    # ---- 4. 渲染帧连续性 (插值消除 30Hz 阶梯) ----
    eng3 = make_engine()
    sp = eng3.add_model(create_sphere(1.0), E.Point3D(0, 5, 0), E.Point3D(0, 0, 0))
    eng3._interp = InterpState(eng3.models)
    # 逻辑: 每步 y+0.3 (30Hz); 渲染: 120FPS → 每逻辑步间 4 渲染帧
    eng3._interp.advance()
    ys = []
    for step in range(3):
        sp.position = E.Point3D(sp.position.x, sp.position.y + 0.3, sp.position.z)
        eng3._interp.advance()
        for sub in range(4):                     # 每逻辑步 4 渲染帧
            eng3._interp.alpha = sub / 4.0
            pos, _, _ = eng3._interp.render_pose(eng3._interp.alpha, eng3.models)
            ys.append(float(pos[0, 1]))
    diffs = np.diff(ys)
    expect_step = 0.3 / 4.0                       # 每渲染帧应匀速走 0.075
    check("渲染帧连续性 (无 30Hz 阶梯): 每帧增量恒定",
          bool(np.allclose(diffs, expect_step, atol=1e-9)),
          "diffs=%s" % np.round(diffs, 4))

    print("=" * 40)
    print("interp_check: %s" % ("ALL PASS" if ok else "FAIL"))
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
