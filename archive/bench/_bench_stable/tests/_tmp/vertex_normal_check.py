# -*- coding: utf-8 -*-
"""vertex_normal_check.py — 法线变换等价性数值验证 (2026-08-29).

验证两路径逐向量一致:
  A 引擎 GLSL: transpose(inverse(mat3(M_col))) * n   (列主序, GL 语义)
  B 我 CPU 打包: nm = inv(M_row).T 存槽, WGSL: nm_col * vec4(n,0)
WGSL 列主序效果 B 数学上 =? A.
"""
import numpy as np

# 随机模型矩阵 (行主序数学: S@R@T 行向量式)
rx, ry, rz = 0.3, 0.6, -0.4
cx, sx = np.cos(rx), np.sin(rx)
cy, sy = np.cos(ry), np.sin(ry)
cz, sz = np.cos(rz), np.sin(rz)
Rx = np.array([[1, 0, 0, 0], [0, cx, sx, 0], [0, -sx, cx, 0], [0, 0, 0, 1]])
Ry = np.array([[cy, 0, -sy, 0], [0, 1, 0, 0], [sy, 0, cy, 0], [0, 0, 0, 1]])
Rz = np.array([[cz, sz, 0, 0], [-sz, cz, 0, 0], [0, 0, 1, 0], [0, 0, 0, 1]])
M_row = Rx @ Ry @ Rz * 1.0
M_row[:3, :3] *= np.array([[2.0, 1, 0.5], [0.3, 1.5, 0.2], [0.1, 0.2, 1.2]])  # 非等比

n = np.array([0.3, 0.8, 0.5]); n = n / np.linalg.norm(n)

# A: GLSL 列主序 M_col = M_row.T; mat3 = 左上3x3
M_col = M_row.T
A = np.linalg.inv(M_col[:3, :3]).T @ n      # transpose(inverse(mat3)) * n

# B: CPU → nm_row = inv(M_row).T (3x3), 存槽 bytes → wgpu 读为列主序 nm_col = nm_row.T
W_row = np.zeros((4, 4)); W_row[:3, :3] = np.linalg.inv(M_row)[:3, :3].T
nm_row = W_row
nm_col = nm_row.T                            # 字节再解释为列主序
B = nm_col[:3, :3] @ n

print("A(GLSL):", A)
print("B(WGSL):", B)
print("最大差: %.3e  → %s" % (np.abs(A - B).max(),
                           "一致" if np.abs(A - B).max() < 1e-5 else "不一致!"))
