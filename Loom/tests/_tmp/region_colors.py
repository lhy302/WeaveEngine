# -*- coding: utf-8 -*-
"""region_colors.py — 区域内主色统计: py region_colors.py png x0 y0 x1 y1"""
import sys
import numpy as np
from PIL import Image

path, x0, y0, x1, y1 = sys.argv[1], int(sys.argv[2]), int(sys.argv[3]), int(sys.argv[4]), int(sys.argv[5])
a = np.asarray(Image.open(path).convert('RGB')).astype(np.int32)[y0:y1, x0:x1]
q = (a // 8).reshape(-1, 3)
vals, cnt = np.unique(q, axis=0, return_counts=True)
order = np.argsort(-cnt)[:10]
for i in order:
    print("  rgb~%s n=%d" % ((vals[i] * 8 + 4).tolist(), cnt[i]))
