# -*- coding: utf-8 -*-
"""验证 decompose_euler: mat4_rotation(euler) -> decompose -> 重构成同一矩阵."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import numpy as np
import math
from matlib import mat4_rotation, decompose_euler

rng = np.random.default_rng(7)
worst = 0.0
n_fail = 0
for _ in range(2000):
    rx, ry, rz = rng.uniform(-math.pi, math.pi, 3)
    R = mat4_rotation(np, rx, ry, rz)
    a, b, g = decompose_euler(R)
    R2 = mat4_rotation(np, a, b, g)
    err = float(np.max(np.abs(R2 - R)))
    worst = max(worst, err)
    if err > 1e-6:
        n_fail += 1
        if n_fail <= 3:
            print("FAIL", (rx, ry, rz), "->", (a, b, g), "err", err)

print("2000 随机角 往返最大误差:", worst)
print("超差次数:", n_fail, "=>", "PASS ✅" if n_fail == 0 else "FAIL ❌")
