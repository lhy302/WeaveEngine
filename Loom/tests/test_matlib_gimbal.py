# -*- coding: utf-8 -*-
"""
test_matlib_gimbal.py — decompose_euler 万向锁符号修复回归
(scan_01_core P-13 ≡ scan_02_scene P-14, 2026-11-07)

背景
----
matlib.decompose_euler 的万向锁分支 (|cosβ| < 1e-9) 只对 β=+90° 正确:
原代码统一取 α = atan2(R[1,0], R[1,1]), 但由 R = Rx@Ry@Rz 展开:
  β=+π/2: R[1,0]= sin(α-γ), R[1,1]=cos(α-γ)  -> α=atan2( R[1,0], R[1,1])
  β=-π/2: R[1,0]=-sin(α+γ), R[1,1]=cos(α+γ)  -> α=atan2(-R[1,0], R[1,1])
所以 β=-90° 时分解出的 α 符号相反, 重建矩阵与世界旋转最多差 ~2 (实测 1.683 rad)。
受影响真实路径: loom_transform.set_parent(preserve_world=True) 与 editor gizmo。

本文件断言:
  A: β ∈ {±90°, ±89.999°} 往返 mat4_rotation(decompose(R)) == R, 误差 < 1e-6。
  B: 显式命中 |cosβ| < 1e-9 分支 (β=±90° 精确点), 且 α/γ 非零、正负都覆盖。
  C: set_parent(preserve_world=True) 在 β=±90° / ±89.999° 保持世界旋转 < 1e-6。
  D: 一般角域 200 组随机往返不回归 (最大误差 < 1e-6)。

运行: python tests\test_matlib_gimbal.py   (无头, 无 GPU)
"""
import sys as _sys_utf8
try:
    _sys_utf8.stdout.reconfigure(encoding='utf-8', errors='replace')
    _sys_utf8.stderr.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

import math
import os
import sys
import uuid

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
os.environ.setdefault('LOOM_NO_PARALLEL', '1')
os.environ.setdefault('LOOM_NO_SAVE_MIGRATE', '1')

import numpy as np

from matlib import mat4_rotation, decompose_euler

_FAILS = []


def check(name, cond, extra=""):
    print(("PASS " if cond else "FAIL ") + name + ("  " + str(extra) if extra else ""))
    if not cond:
        _FAILS.append(name)


def roundtrip_err(alpha, beta, gamma):
    R = mat4_rotation(np, alpha, beta, gamma)
    a, b, g = decompose_euler(R)
    return float(np.max(np.abs(mat4_rotation(np, a, b, g) - R))), (a, b, g)


# ====================================================================
# A: 指定角域往返 (验收: β ∈ {±90°, ±89.999°}, 误差 < 1e-6)
# ====================================================================
def t_acceptance_angles():
    angles = [math.radians(d) for d in (90.0, -90.0, 89.999, -89.999)]
    combos = [(0.3, 0.7), (-0.3, -0.7), (1.2, -0.4), (0.0, 0.0), (math.pi, -math.pi)]
    worst = 0.0
    for b in angles:
        for a, g in combos:
            err, dec = roundtrip_err(a, b, g)
            worst = max(worst, err)
            check("[A] beta=%+.3f° alpha=%+.2f gamma=%+.2f 往返" % (math.degrees(b), a, g),
                  err < 1e-6, "err=%.3e decomp=(%.6f,%.6f,%.6f)" % (err, *dec))
    check("[A] 全部角域最大往返误差 < 1e-6", worst < 1e-6, "worst=%.3e" % worst)


# ====================================================================
# B: 精确命中万向锁分支 (|cosβ| < 1e-9), 符号两向都验
# ====================================================================
def t_gimbal_branch_exact():
    for deg, sign in ((90.0, +1.0), (-90.0, -1.0)):
        beta = math.radians(deg)
        cb = math.cos(beta)
        check("[B] beta=%+.0f° 确实命中 |cosβ|<1e-9" % deg, abs(cb) < 1e-9, "|cosβ|=%.1e" % abs(cb))
        # 万向锁下 γ 被吸收进 α, 只需重建矩阵一致; 用 (α∓γ) 的符号方向验证
        for a, g in ((0.3, 0.7), (-0.3, 0.7), (0.7, -0.3), (-1.1, -0.9)):
            R = mat4_rotation(np, a, beta, g)
            alpha, b, gamma = decompose_euler(R)
            err = float(np.max(np.abs(mat4_rotation(np, alpha, b, gamma) - R)))
            check("[B] beta=%+.0f° alpha=%+.2f gamma=%+.2f 重建" % (deg, a, g),
                  err < 1e-6, "err=%.3e decomp=(%.6f,%.6f,%.6f)" % (err, alpha, b, gamma))
        # β=-90° 的解析解: γ=0 时 α 必须 = +(α0+γ0), 而不是 -(α0+γ0)
        R = mat4_rotation(np, 0.3, beta, 0.7)
        alpha, _, gamma = decompose_euler(R)
        check("[B] beta=%+.0f° 分解取 gamma=0" % deg, abs(gamma) < 1e-12, gamma)
        expect = (0.3 - 0.7) if sign > 0 else (0.3 + 0.7)
        d = math.atan2(math.sin(alpha - expect), math.cos(alpha - expect))
        check("[B] beta=%+.0f° alpha 解析值 %+.4f" % (deg, expect), abs(d) < 1e-9,
              "alpha=%.6f" % alpha)


# ====================================================================
# C: set_parent 在奇点保持世界旋转 (P-13 的真实路径)
# ====================================================================
def t_set_parent_gimbal():
    import engine as E
    from mesh import create_cube

    E.GLEngine._build_gpu = lambda self, m: None

    def mk(name, pos=(0, 0, 0), rot=(0, 0, 0), scale=(1, 1, 1)):
        m = E.GameObject(create_cube(1.0), E.Point3D(*pos), E.Point3D(*rot),
                         name=name, scale=scale)
        m.guid = uuid.uuid4().hex
        return m

    def new_eng(models):
        e = E.GLEngine.__new__(E.GLEngine)
        e.models = models
        e.materials = []
        e.lights = []
        e.cameras = []
        e.active_camera = None
        e.current_model_index = 0
        return e

    worst = 0.0
    for deg in (90.0, -90.0, 89.999, -89.999):
        p = mk('P', (3.0, -2.0, 1.5))                 # 父旋转为单位 -> 局部 β 命中奇点
        c = mk('C', (1.0, 2.0, 0.5), (0.3, math.radians(deg), 0.7))
        e = new_eng([p, c])
        wr0 = e.world_rotation_matrix(c)
        wp0 = e.world_position(c)
        ws0 = e.world_scale(c)
        e.set_parent(c, p, preserve_world=True)
        wr1 = e.world_rotation_matrix(c)
        wp1 = e.world_position(c)
        ws1 = e.world_scale(c)
        rerr = float(np.max(np.abs(wr1 - wr0)))
        perr = max(abs(wp1.x - wp0.x), abs(wp1.y - wp0.y), abs(wp1.z - wp0.z))
        serr = max(abs(ws1.x - ws0.x), abs(ws1.y - ws0.y), abs(ws1.z - ws0.z))
        worst = max(worst, rerr)
        check("[C] set_parent beta=%+.3f° 世界旋转保持" % deg, rerr < 1e-6,
              "rot_err=%.3e" % rerr)
        check("[C] set_parent beta=%+.3f° 世界位置保持" % deg, perr < 1e-9,
              "pos_err=%.3e" % perr)
        check("[C] set_parent beta=%+.3f° 世界缩放保持" % deg, serr < 1e-9,
              "scale_err=%.3e" % serr)
        check("[C] 子已挂到父下", c.parent is p and c in p.children)
    check("[C] set_parent 奇点最大世界旋转差 < 1e-6", worst < 1e-6, "worst=%.3e" % worst)


# ====================================================================
# D: 一般角域随机往返 (防修奇点分支时劣化通用分支)
# ====================================================================
def t_random_domain():
    rng = np.random.default_rng(7)
    worst = 0.0
    for _ in range(200):
        rx, ry, rz = rng.uniform(-math.pi, math.pi, 3)
        R = mat4_rotation(np, rx, ry, rz)
        a, b, g = decompose_euler(R)
        worst = max(worst, float(np.max(np.abs(mat4_rotation(np, a, b, g) - R))))
    check("[D] 200 组随机角往返 < 1e-6", worst < 1e-6, "worst=%.3e" % worst)


if __name__ == "__main__":
    print("========== decompose_euler 万向锁符号 (scan P-13/P-14) ==========")
    t_acceptance_angles()
    t_gimbal_branch_exact()
    t_set_parent_gimbal()
    t_random_domain()
    print()
    if _FAILS:
        print("总结果: FAIL ❌", _FAILS)
        sys.exit(1)
    print("总结果: ALL PASS ✅")
