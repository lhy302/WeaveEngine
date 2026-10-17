# -*- coding: utf-8 -*-
"""find_color.py — 在 PNG 中找目标色像素簇 (验收链 T1):
py find_color.py <png> <r> <g> <b> <tol> —— 输出簇 数/nx/ny 及去重中心点列表"""
import sys
import numpy as np
from PIL import Image

path = sys.argv[1]
r, g, b = int(sys.argv[2]), int(sys.argv[3]), int(sys.argv[4])
tol = int(sys.argv[5]) if len(sys.argv) > 5 else 30
a = np.asarray(Image.open(path).convert('RGB')).astype(np.int32)
mask = (np.abs(a[:, :, 0] - r) <= tol) & (np.abs(a[:, :, 1] - g) <= tol) & (np.abs(a[:, :, 2] - b) <= tol)
ys, xs = np.nonzero(mask)
print("%s: %d px, x[%d..%d] y[%d..%d]" % (path.split('\\')[-1], len(xs),
      xs.min() if len(xs) else -1, xs.max() if len(xs) else -1,
      ys.min() if len(ys) else -1, ys.max() if len(ys) else -1))
# 按 20px 网格聚类去重 (给出密度轮廓)
if len(xs):
    cells = {}
    for x, y in zip(xs, ys):
        k = (int(x) // 20, int(y) // 20)
        cells[k] = cells.get(k, 0) + 1
    top = sorted(cells.items(), key=lambda kv: -kv[1])[:8]
    for (cx, cy), n in top:
        print("  cluster cell(%d,%d) n=%d" % (cx * 20, cy * 20, n))
