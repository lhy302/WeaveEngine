# -*- coding: utf-8 -*-
"""png_stat.py — PNG 像素统计 (验收链 T1 截图判定): 方差/非背景占比/均色/通道数.
用法: py -3.12 tests\_tmp\png_stat.py <png>...
背景 = 最频色 (mode); 非背景像素 = 与最频色 L1 距离 > 24 的像素."""
import sys
import numpy as np
from PIL import Image

for path in sys.argv[1:]:
    im = Image.open(path).convert('RGB')
    a = np.asarray(im, dtype=np.int32)
    H, W = a.shape[:2]
    # 最频色 (粗量化到 /16 再找众数, 反查原色近似)
    q = (a // 16).reshape(-1, 3)
    (vals, counts) = np.unique(q, axis=0, return_counts=True)
    i = int(np.argmax(counts))
    mode_q = vals[i]
    mode = mode_q * 16 + 8
    dist = np.abs(a - mode).sum(axis=2)
    nonbg = (dist > 24).mean()
    mean = a.reshape(-1, 3).mean(axis=0)
    std = a.reshape(-1, 3).std(axis=0)
    # 行/列亮度概貌 (判断上下左右是否分层)
    gray = a.mean(axis=2)
    print("%s: %dx%d 非背景占比=%.4f mean=%s std=%s bg=%s" % (
        path.split('\\')[-1], W, H, nonbg, np.round(mean, 1), np.round(std, 1), mode))
