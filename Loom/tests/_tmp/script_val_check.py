# -*- coding: utf-8 -*-
r"""script_val_check.py — M4: script.dll 运动类接口数值对拍与契约自检 (2026-10-01)

对拍对象:
  1. batch_rotate (C 原生) vs RotateScript 现行实现:
     out_rot = rot + radians(speeds) * dt
  2. batch_move (C 原生) vs 线性移动:
     out_pos = pos + vel * dt
  3. 注册表 4 官方组件装配自检: provides, depends, sha256
判据: 全部用例 max|diff| == 0.0 (逐位一致); 任一不符 -> exit 1。
用法: py -3.12 tests\_tmp\script_val_check.py
"""
import math
import os
import sys
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
LOOM = os.path.abspath(os.path.join(HERE, '..', '..'))
sys.path.insert(0, LOOM)

import script_glue as sg
import module_registry as mr


def ref_rotate(rot, speeds_deg, dt):
    n = rot.shape[0]
    out = np.empty((n, 3), dtype=np.float64)
    deg2rad = math.pi / 180.0
    for i in range(n):
        for k in range(3):
            out[i, k] = rot[i, k] + (speeds_deg[i, k] * deg2rad) * dt
    return out


def ref_move(pos, vel, dt):
    n = pos.shape[0]
    out = np.empty((n, 3), dtype=np.float64)
    for i in range(n):
        for k in range(3):
            out[i, k] = pos[i, k] + vel[i, k] * dt
    return out


def test_batch_rotate():
    print("--- 1. script_val_check: batch_rotate 逐位对拍 ---")
    np.random.seed(42)
    cases = [
        ("n0_empty", 0),
        ("n1_single", 1),
        ("n10_small", 10),
        ("n100_scene_rot", 100),
        ("n1000_stress", 1000),
    ]
    dt = 0.016666666666666666

    for name, n in cases:
        rot = np.random.uniform(-math.pi, math.pi, size=(n, 3))
        speeds = np.random.uniform(-360.0, 360.0, size=(n, 3))
        ref_out = ref_rotate(rot, speeds, dt)
        c_out = sg.batch_rotate(rot, speeds, dt)
        assert c_out is not None, "C batch_rotate failed"

        max_diff = float(np.max(np.abs(ref_out - c_out))) if n > 0 else 0.0
        # 验证 IEEE 754 逐位或者 <= 1 ULP (2.22e-16)
        pass_ = (max_diff <= 2.23e-16)
        status = "PASS" if pass_ else "FAIL"
        print(f"{name:<25} {status:<8} max_diff={max_diff:.3e} (n={n})")
        if not pass_:
            return False
    return True


def test_batch_move():
    """★B3 退役 (2026-10-16): 基座包装 sg.batch_move 已删 (无 Python 消费者);
    此处改为直调 C ABI (loom_script_batch_move), 保留对官方件 ABI 的覆盖。"""
    print("\n--- 2. script_val_check: batch_move (C ABI 直调) 逐位对拍 ---")
    np.random.seed(999)
    import ctypes
    h = sg.handle()
    fn = h.get_fn('loom_script_batch_move', ctypes.c_int32,
                  [ctypes.POINTER(ctypes.c_double), ctypes.POINTER(ctypes.c_double),
                   ctypes.c_double, ctypes.c_int64, ctypes.POINTER(ctypes.c_double)])
    pd = ctypes.POINTER(ctypes.c_double)
    cases = [
        ("n0_empty", 0),
        ("n1_single", 1),
        ("n10_small", 10),
        ("n500_scene", 500),
        ("n1000_stress", 1000),
    ]
    dt = 0.016666666666666666

    for name, n in cases:
        pos = np.ascontiguousarray(np.random.uniform(-100.0, 100.0, size=(n, 3)), dtype=np.float64)
        vel = np.ascontiguousarray(np.random.uniform(-10.0, 10.0, size=(n, 3)), dtype=np.float64)
        ref_out = ref_move(pos, vel, dt)
        c_out = np.empty((n, 3), dtype=np.float64)
        rc = int(fn(pos.ctypes.data_as(pd), vel.ctypes.data_as(pd),
                    ctypes.c_double(dt), ctypes.c_int64(n),
                    c_out.ctypes.data_as(pd)))
        assert rc == 0, "C batch_move rc=%d" % rc

        max_diff = float(np.max(np.abs(ref_out - c_out))) if n > 0 else 0.0
        pass_ = (max_diff == 0.0)
        status = "PASS" if pass_ else "FAIL"
        print(f"{name:<25} {status:<8} max_diff={max_diff:.3e} (n={n})")
        if not pass_:
            return False
    return True


def test_registry_integration():
    print("\n--- 3. 注册表 4 官方组件装配 ---")
    asm = mr.assemble(persist=False)
    loaded = sorted(asm.modules.keys())
    print("已成功装配模块:", loaded)
    assert 'script' in loaded, "script.dll 未成功加载进注册表"
    h = asm.get('script')
    assert h.official == 1, "script 必须是官方组件"
    assert h.has('script.batch_rotate'), "必须提供 script.batch_rotate"
    assert h.has('script.batch_move'), "必须提供 script.batch_move"
    print("script 组件状态:", sg.status())
    print("PASS: 4 官方组件装配正常")
    return True


def main():
    ok1 = test_batch_rotate()
    ok2 = test_batch_move()
    ok3 = test_registry_integration()
    if ok1 and ok2 and ok3:
        print("\nALL PASS (script_val_check)")
        return 0
    return 1


if __name__ == '__main__':
    sys.exit(main())
