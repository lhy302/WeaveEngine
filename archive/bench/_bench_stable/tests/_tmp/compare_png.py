# -*- coding: utf-8 -*-
"""compare_png.py — Vk/GL 两张 offscreen 图逐像素定量对比 (2026-08-29)."""
import sys

import numpy as np
import pygame

pygame.init()

def load(p):
    s = pygame.image.load(p)
    a = pygame.surfarray.pixels3d(s)      # (W, H, 3) 行序= 屏幕 x/y 转置
    return np.array(a).transpose(1, 0, 2)  # -> (H, W, 3)

a = load(sys.argv[1]).astype(np.float32)
b = load(sys.argv[2]).astype(np.float32)
print("Vk:", a.shape, " GL:", b.shape)
lum_a = a.mean(axis=2)
lum_b = b.mean(axis=2)

def centroid(l):
    nz = np.indices(l.shape)[0]
    mz = np.indices(l.shape)[1]
    w = l - l.min()
    if w.sum() == 0:
        return (0, 0)
    return (float((nz * w).sum() / w.sum()), float((mz * w).sum() / w.sum()))

ca, cb = centroid(lum_a), centroid(lum_b)
print("亮度质心 (y,x): Vk=(%.0f,%.0f) GL=(%.0f,%.0f)" % (ca[0], ca[1], cb[0], cb[1]))
print("平均亮度: Vk=%.1f GL=%.1f" % (lum_a.mean(), lum_b.mean()))

# 4x4 子区域平均亮度 (定位差异区域)
for name, l in (('Vk', lum_a), ('GL', lum_b)):
    rows = [name]
    H, W = l.shape
    for r in range(4):
        rows.append('  '.join("%4.0f" % l[int(r * H / 4):int((r + 1) * H / 4),
                                          int(c * W / 4):int((c + 1) * W / 4)].mean()
                              for c in range(4)))
    print('\n'.join(rows))

# 归一化互相关 (整体相似度 1=完全一致)
dev_a = lum_a - lum_a.mean()
dev_b = lum_b - lum_b.mean()
ncc = float((dev_a * dev_b).sum() / (np.sqrt((dev_a ** 2).sum() * (dev_b ** 2).sum()) + 1e-9))
print("NCC 相似度: %.3f (1.0=完全一致, <0.8=构图/光照明显不同)" % ncc)
