# -*- coding: utf-8 -*-
"""make_assets.py — ab 场景的**密闭**夹具资产生成器（2026-11-11）。

背景：ab_env / ab_nrm / ab_tex / ab_ui_scene 原来引用 `tests/_tmp/*.png`（绝对路径），
那些图从未提交 —— 清理 _tmp 后整个 ab 夹具不可复现。这里用**确定性**规则重新生成：
  · assets/env/env_0..5.png   4x4 纯色六面（+X 红 / -X 青 / +Y 绿 / -Y 品红 / +Z 蓝 / -Z 黄）
  · assets/tex/normalmap.png 8x8 法线贴图（+Z 为主，带固定斜纹）
  · assets/tex/checker.png   16x16 双色棋盘
  · assets/tex/ui_tex_rgba.png 8x8 半透明 RGBA（UI 贴图用）

重跑：py -3.13 tests/ab_scenes/assets/make_assets.py（幂等，逐字节相同）
"""
import os

import numpy as np
from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))


def _save(rel, arr):
    p = os.path.join(HERE, rel)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    Image.fromarray(arr).save(p)
    print('wrote', os.path.relpath(p, HERE))


def main():
    # 六面纯色（4x4）：固定颜色，便于肉眼确认立方体朝向
    faces = [(200, 40, 40), (40, 200, 200), (40, 200, 40),
             (200, 40, 200), (40, 40, 200), (200, 200, 40)]
    for i, c in enumerate(faces):
        arr = np.zeros((4, 4, 3), dtype=np.uint8)
        arr[:, :] = c
        _save(os.path.join('env', 'env_%d.png' % i), arr)

    # 法线贴图（8x8）：主方向 +Z，固定斜纹让 PBR 有可见差异
    nm = np.zeros((8, 8, 3), dtype=np.uint8)
    yy, xx = np.mgrid[0:8, 0:8]
    nm[..., 0] = (128 + (xx - 4) * 6).clip(0, 255)
    nm[..., 1] = (128 + (yy - 4) * 6).clip(0, 255)
    nm[..., 2] = 255
    _save(os.path.join('tex', 'normalmap.png'), nm)

    # 棋盘（16x16）
    ck = np.zeros((16, 16, 3), dtype=np.uint8)
    ck[...] = (230, 230, 230)
    ck[((np.indices((16, 16)).sum(axis=0)) % 2) == 0] = (30, 30, 30)
    _save(os.path.join('tex', 'checker.png'), ck)

    # UI 贴图（8x8 RGBA，半透明斜纹）
    ui = np.zeros((8, 8, 4), dtype=np.uint8)
    ui[..., 0] = 255
    ui[..., 1] = 120
    ui[..., 2] = 40
    ui[..., 3] = np.where(((np.indices((8, 8)).sum(axis=0)) % 2) == 0, 255, 96)
    _save(os.path.join('tex', 'ui_tex_rgba.png'), ui)


if __name__ == '__main__':
    main()
