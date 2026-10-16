# -*- coding: utf-8 -*-
r"""physics_dll_val_check.py — M4: AUDIT-42 / AUDIT-43 physics.dll 动力学组件与多子步闭环数值对拍与契约自检

对拍对象:
  1. physics_glue.pre_step (C 原生) vs Python 纯数学重力与滚动衰减:
     - 动态体重力累加 vy += g * dt
     - 滚动摩擦指数衰减 f = max(0, 1 - mu * roll * K * dt)
     - 水平残速与角残速死带清除
  2. physics_glue.post_step (C 原生) vs 睡眠态残速归零
  3. physics_glue.substep_loop (C 闭环推进) vs 串行多子步推进
  4. 注册表第 5 官方组件装配自检: provides, depends, sha256 钉扎有效性

★B4 退役 (2026-10-16): 删原第 5 条「LOOM_NO_PHYSICS_DLL=1 逃生门降级测试」——
physics.dll 为唯一路径, 无 Python 逐体回退。

判据: 全部用例 max|diff| == 0.0 (逐位一致); 全部测试 100% 通过, 否则 sys.exit(1)。
用法: py -3.12 tests\_tmp\physics_dll_val_check.py
"""
import math
import os
import sys
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
LOOM = os.path.abspath(os.path.join(HERE, '..', '..'))
sys.path.insert(0, LOOM)

import physics_glue as pg
import module_registry as mr

ROLLING_K = 23.0
ROLLING_ANG_EPS = 0.06
V_STALL_EPS = 0.03
W_STALL_EPS = 0.3
VY_STOP_GATE = 1.0

def py_ref_pre_step(lin_vel, ang_vel, is_dynamic, use_gravity, is_active, friction, rolling_fric, gravity_y, dt):
    lv = lin_vel.copy()
    av = ang_vel.copy()
    n = lv.shape[0]
    for i in range(n):
        if not is_dynamic[i]:
            continue
        if use_gravity[i] and is_active[i]:
            lv[i, 1] += gravity_y * dt
        if is_active[i]:
            wx, wy, wz = av[i, 0], av[i, 1], av[i, 2]
            ang_speed = math.sqrt(wx * wx + wy * wy + wz * wz)
            if ang_speed > ROLLING_ANG_EPS:
                decay = max(0.0, 1.0 - friction[i] * rolling_fric[i] * ROLLING_K * dt)
                av[i, :] *= decay
                lv[i, 0] *= decay
                lv[i, 2] *= decay
            vx, vy, vz = lv[i, 0], lv[i, 1], lv[i, 2]
            vh = math.sqrt(vx * vx + vz * vz)
            if vh < V_STALL_EPS and ang_speed < W_STALL_EPS and abs(vy) < VY_STOP_GATE:
                lv[i, 0] = 0.0
                lv[i, 2] = 0.0
                av[i, :] = 0.0
    return lv, av

def py_ref_post_step(lin_vel, ang_vel, is_active):
    lv = lin_vel.copy()
    av = ang_vel.copy()
    n = lv.shape[0]
    for i in range(n):
        if not is_active[i]:
            lv[i, :] = 0.0
            av[i, :] = 0.0
    return lv, av

def test_pre_step_bitwise():
    print("--- 1. AUDIT-42: physics.dll pre_step 数值逐位对拍 ---")
    np.random.seed(42)
    cases = [
        ("n0_empty", 0),
        ("n1_single", 1),
        ("n10_mixed", 10),
        ("n100_bodies", 100),
        ("n500_scene", 500),
    ]
    dt = 1.0 / 60.0
    g = -9.8

    for name, n in cases:
        if n == 0:
            lin = np.empty((0, 3), dtype=np.float64)
            ang = np.empty((0, 3), dtype=np.float64)
            dyn = np.empty(0, dtype=np.uint8)
            grav = np.empty(0, dtype=np.uint8)
            act = np.empty(0, dtype=np.uint8)
            fric = np.empty(0, dtype=np.float64)
            roll = np.empty(0, dtype=np.float64)
        else:
            lin = np.random.uniform(-10.0, 10.0, size=(n, 3)).astype(np.float64)
            ang = np.random.uniform(-5.0, 5.0, size=(n, 3)).astype(np.float64)
            dyn = np.random.choice([0, 1], size=n, p=[0.2, 0.8]).astype(np.uint8)
            grav = np.random.choice([0, 1], size=n, p=[0.1, 0.9]).astype(np.uint8)
            act = np.random.choice([0, 1], size=n, p=[0.3, 0.7]).astype(np.uint8)
            fric = np.random.uniform(0.1, 0.8, size=n).astype(np.float64)
            roll = np.random.uniform(0.0, 0.3, size=n).astype(np.float64)

        ref_lin, ref_ang = py_ref_pre_step(lin, ang, dyn, grav, act, fric, roll, g, dt)
        
        c_lin = lin.copy()
        c_ang = ang.copy()
        rc = pg.pre_step(c_lin, c_ang, dyn, grav, act, fric, roll, g, dt)
        assert rc == 0, f"pre_step failed rc={rc}"

        diff_lin = float(np.max(np.abs(ref_lin - c_lin))) if n > 0 else 0.0
        diff_ang = float(np.max(np.abs(ref_ang - c_ang))) if n > 0 else 0.0
        pass_ = (diff_lin == 0.0 and diff_ang == 0.0)
        status = "PASS" if pass_ else "FAIL"
        print(f"{name:<20} {status:<8} diff_lin={diff_lin:.3e} diff_ang={diff_ang:.3e} (n={n})")
        if not pass_:
            return False
    return True

def test_post_step_bitwise():
    print("\n--- 2. AUDIT-42: physics.dll post_step 数值逐位对拍 ---")
    np.random.seed(123)
    cases = [("n0_empty", 0), ("n10_mixed", 10), ("n500_scene", 500)]
    for name, n in cases:
        if n == 0:
            lin = np.empty((0, 3), dtype=np.float64)
            ang = np.empty((0, 3), dtype=np.float64)
            act = np.empty(0, dtype=np.uint8)
        else:
            lin = np.random.uniform(-10.0, 10.0, size=(n, 3)).astype(np.float64)
            ang = np.random.uniform(-5.0, 5.0, size=(n, 3)).astype(np.float64)
            act = np.random.choice([0, 1], size=n, p=[0.4, 0.6]).astype(np.uint8)

        ref_lin, ref_ang = py_ref_post_step(lin, ang, act)
        c_lin = lin.copy()
        c_ang = ang.copy()
        rc = pg.post_step(c_lin, c_ang, act)
        assert rc == 0, f"post_step failed rc={rc}"

        diff_lin = float(np.max(np.abs(ref_lin - c_lin))) if n > 0 else 0.0
        diff_ang = float(np.max(np.abs(ref_ang - c_ang))) if n > 0 else 0.0
        pass_ = (diff_lin == 0.0 and diff_ang == 0.0)
        status = "PASS" if pass_ else "FAIL"
        print(f"{name:<20} {status:<8} diff_lin={diff_lin:.3e} diff_ang={diff_ang:.3e} (n={n})")
        if not pass_:
            return False
    return True

def test_substep_loop_closure():
    print("\n--- 3. AUDIT-43: physics.dll substep_loop 纯 C 闭环推进测试 ---")
    np.random.seed(999)
    n = 200
    lin = np.random.uniform(-5.0, 5.0, size=(n, 3)).astype(np.float64)
    ang = np.random.uniform(-2.0, 2.0, size=(n, 3)).astype(np.float64)
    dyn = np.ones(n, dtype=np.uint8)
    grav = np.ones(n, dtype=np.uint8)
    act = np.ones(n, dtype=np.uint8)
    fric = np.full(n, 0.5, dtype=np.float64)
    roll = np.full(n, 0.1, dtype=np.float64)
    sub_dt = 1.0 / 180.0 # 3 sub steps per 60Hz frame
    num_substeps = 3
    g = -9.8

    # 1. Python 连续跑 3 子步
    ref_lin = lin.copy()
    ref_ang = ang.copy()
    for _ in range(num_substeps):
        ref_lin, ref_ang = py_ref_pre_step(ref_lin, ref_ang, dyn, grav, act, fric, roll, g, sub_dt)
        ref_lin, ref_ang = py_ref_post_step(ref_lin, ref_ang, act)

    # 2. C 闭环跑 3 子步
    c_lin = lin.copy()
    c_ang = ang.copy()
    rc = pg.substep_loop(c_lin, c_ang, dyn, grav, act, fric, roll, g, sub_dt, num_substeps)
    assert rc == 0, f"substep_loop failed rc={rc}"

    diff_lin = float(np.max(np.abs(ref_lin - c_lin)))
    diff_ang = float(np.max(np.abs(ref_ang - c_ang)))
    pass_ = (diff_lin == 0.0 and diff_ang == 0.0)
    print(f"3 子步 C 闭环推进 vs Python 串行: diff_lin={diff_lin:.3e}, diff_ang={diff_ang:.3e}")
    assert pass_, "C 多子步闭环数值有偏差"
    print("PASS: 多子步纯 C 闭环推进与参考实现 100% 逐位一致")
    return True

def test_registry_integration():
    print("\n--- 4. 注册表 5 官方组件与 SHA256 自检 ---")
    asm = mr.assemble(persist=False)
    mods = sorted(asm.modules.keys())
    print(f"已成功装配官方模块 ({len(mods)} 个): {mods}")
    assert 'physics' in mods, "缺少 physics 组件"
    h = asm.get('physics')
    assert h.official, "physics 必须为官方组件"
    assert h.has('physics.pre_step'), "缺少 physics.pre_step 导出"
    assert h.has('physics.post_step'), "缺少 physics.post_step 导出"
    assert h.has('physics.substep_loop'), "缺少 physics.substep_loop 导出"
    print("PASS: physics.dll 官方组件契约完备并网")
    return True

if __name__ == '__main__':
    ok = True
    ok = ok and test_pre_step_bitwise()
    ok = ok and test_post_step_bitwise()
    ok = ok and test_substep_loop_closure()
    ok = ok and test_registry_integration()
    if ok:
        print("\n=== AUDIT-42 / AUDIT-43 ALL VERIFICATIONS PASSED ===")
        sys.exit(0)
    else:
        print("\n=== AUDIT-42 / AUDIT-43 SOME TESTS FAILED ===")
        sys.exit(1)
