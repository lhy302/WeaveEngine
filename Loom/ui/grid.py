# -*- coding: utf-8 -*-
"""ui/grid.py — 无限网格纯几何 (2026-08-14)

跟随相机的"无限"地面网格:
  * 相机 XZ 为中心, 原点吸附到整数格 (线恒为世界整数格坐标, 相机移动不"游泳")
  * **恒定步长** step=1 世界单位 —— 间距不随视角/缩放变化 (经典无限网格)
  * **半宽固定 60** (2026-08-30 性能修): 范围/线数与相机距离**无关** —— 旧实现
    半宽=dist*6 导致线数随距离增长 (距离 32 → ~770 段, 逐线 Python 生成
    1.75ms/帧, 且内容随距离变), 本实现全 numpy 一次成形, 成本=常数级
    (验收线: 性能消耗与相机距离无关)。
  * 远处线条按离相机水平距离淡出 (软边界, 视觉上无限延伸)
  * 相机在地面下方 (抬头, 轨道相机绕到目标下方 eye.y<0) 时网格在头顶上方照常
    渲染, 不会消失、不会跑到视角后面

纯函数无 GL / 无 pygame, LoomGUI 与 MinimalEditorView 共用, 可无头单元测试.

2026-08-14 两次修复 (用户实测反馈):
  ① 抬头网格消失: 旧实现用"视锥足迹"定范围 + 按足迹做 step 分级, 抬头时足迹退化
     兜底网格消失. 改为相机为中心 + 恒定 step + 范围随相机距离.
  ② 网格大小随抬头角度变化: 旧实现 step 分级 (足迹大 -> step 变粗 1→2→5→10),
     间距肉眼可见变化. 现恒定 step=1, 范围只随缩放不随抬头.
2026-08-30 性能修: 范围不再随缩放 (半宽固定), 全 numpy 生成 (成本常数级,
  内容稳定); 淡出公式与旧版逐位同源 (数值参考基准=旧半宽自适应版, 见测试).
"""
import math

import numpy as np

_BASE_RGBA = (0.35, 0.37, 0.42, 1.0)
_STEP = 1.0          # 恒定步长 (世界单位)
_GRID_HALF = 60.0    # 固定半宽 (与相机距离无关: 成本恒定, 内容不随距离变)
_FADE_RATIO = 0.4    # 淡出起点 = 半宽 * 该比例


def _fade_alpha(dist, fade_start, fade_end):
    """离相机水平距离 dist 的线条 alpha (1 近 → 0 远)."""
    if dist <= fade_start:
        return 1.0
    if dist >= fade_end:
        return 0.0
    return (fade_end - dist) / (fade_end - fade_start)


def _fade_vec(d, fade_start, fade_end):
    """向量化 _fade_alpha (f64 运算, 逐元素与标量版同值)."""
    a = np.ones_like(d)
    a[d >= fade_end] = 0.0
    msk = (d > fade_start) & (d < fade_end)
    a[msk] = (fade_end - d[msk]) / (fade_end - fade_start)
    return a


def build_grid_lines(eye, cam_dist=None, max_half=_GRID_HALF,
                     fade_start=None, fade_end=None, step=_STEP):
    """返回 (verts (N,3) f4, cols (N,4) f4) 的地面网格线段; 永不返回 None.

    参数:
      eye      (x,y,z) 相机世界位置 (网格中心 = eye XZ 吸附到整数格)
      cam_dist 兼容保留 (旧"范围随缩放自适应"参数; 2026-08-30 起不参与几何,
               线数/范围恒定)。
    """
    # 范围: 固定半宽 (与相机距离解耦) —— 性能消耗/内容均不随距离变化;
    # max_half 参数兼容保留 (不再参与几何, 恒用 _GRID_HALF)
    half = _GRID_HALF
    if fade_end is None:
        fade_end = half
    if fade_start is None:
        fade_start = half * _FADE_RATIO
    # 原点吸附相机 XZ 到整数格 (线不"游泳")
    ox = math.floor(eye[0] / step) * step
    oz = math.floor(eye[2] / step) * step
    n = int(math.ceil(half / step))
    m = 2 * n + 1
    # 全 numpy 一次成形 (旧版逐线 Python 循环/append; 顺序 = 旧版逐 i:
    # x 线两点 + z 线两点, 输出逐位同源)
    idx = np.arange(-n, n + 1, dtype=np.float64)
    line_cx = ox + idx * step          # x 线所在 x 坐标 / z 线所在 z 坐标
    line_cz = oz + idx * step
    ax = _fade_vec(np.abs(line_cx - eye[0]), fade_start, fade_end)
    az = _fade_vec(np.abs(line_cz - eye[2]), fade_start, fade_end)
    verts = np.empty((4 * m, 3), dtype='f4')
    verts[0::4, 0] = line_cx
    verts[0::4, 1] = 0.0
    verts[0::4, 2] = oz - half
    verts[1::4, 0] = line_cx
    verts[1::4, 1] = 0.0
    verts[1::4, 2] = oz + half
    verts[2::4, 0] = ox - half
    verts[2::4, 1] = 0.0
    verts[2::4, 2] = line_cz
    verts[3::4, 0] = ox + half
    verts[3::4, 1] = 0.0
    verts[3::4, 2] = line_cz
    cols = np.empty((4 * m, 4), dtype='f4')
    cols[0::4, 0:3] = _BASE_RGBA[:3]
    cols[1::4, 0:3] = _BASE_RGBA[:3]
    cols[2::4, 0:3] = _BASE_RGBA[:3]
    cols[3::4, 0:3] = _BASE_RGBA[:3]
    cols[0::4, 3] = ax
    cols[1::4, 3] = ax
    cols[2::4, 3] = az
    cols[3::4, 3] = az
    return verts, cols
