# -*- coding: utf-8 -*-
"""无限网格 (2026-08-14) 纯几何测试: 相机为中心 + 恒定步长 + 范围不随抬头 + 淡出.
无头不建窗口. 回归 2026-08-14: 抬头网格消失 / 网格大小随抬头角度变化."""
import math
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from ui.grid import build_grid_lines

ok = True


def check(label, cond, detail=""):
    global ok
    print(("PASS " if cond else "FAIL ") + label + ("  " + detail if detail else ""))
    if not cond:
        ok = False


# 1. 吸附: 网格中心 = 相机 XZ floor 吸附到整数格. eye=(3.7,5,-2.2) -> 含 x=3 与 z=-3 格线
out = build_grid_lines((3.7, 5.0, -2.2))
check("网格非空", out is not None)
if out is not None:
    verts, cols = out
    xs = np.unique(np.round(verts[:, 0], 6))
    zs = np.unique(np.round(verts[:, 2], 6))
    check("吸附 x=3 格线", np.any(np.isclose(xs, 3.0)), "xs=%s" % xs[:6])
    check("吸附 z=-3 格线", np.any(np.isclose(zs, -3.0)), "zs=%s" % zs[:6])
    check("覆盖相机脚下 x", verts[:, 0].min() <= 3.7 <= verts[:, 0].max())
    check("覆盖相机脚下 z", verts[:, 2].min() <= -2.2 <= verts[:, 2].max())
    check("颜色 4 通道", cols.shape[1] == 4, str(cols.shape))
    # 2. 恒定步长: 相邻格线间距恒 = 1 (核心修复, 不随 cam_dist/抬头变化)
    dxs = np.diff(np.unique(np.round(verts[:, 0], 4)))
    dzs = np.diff(np.unique(np.round(verts[:, 2], 4)))
    check("恒定步长 x", np.allclose(dxs, 1.0, atol=1e-4), "dx=%s" % np.unique(dxs))
    check("恒定步长 z", np.allclose(dzs, 1.0, atol=1e-4), "dz=%s" % np.unique(dzs))

# 3. 半宽固定: 同 eye 不同 cam_dist -> 网格完全一致 (2026-08-30 性能修:
# 线数/范围与距离解耦, 成本恒定, 内容稳定); 抬头仍不改变范围
base = build_grid_lines((0.0, 5.0, -8.0), cam_dist=30.0)
up = build_grid_lines((0.0, -5.0, -8.0), cam_dist=30.0)   # 抬头 (相机在下方)
if base is not None and up is not None:
    check("同 cam_dist 低头/抬头网格顶点数一致", len(base[0]) == len(up[0]),
          "down=%d up=%d" % (len(base[0]), len(up[0])))
    check("抬头网格仍在 y=0", np.all(up[0][:, 1] == 0.0))
    # 4. 不同 cam_dist -> 网格逐位一致 (性能/内容与距离无关, 核心修复)
    far = build_grid_lines((0.0, 5.0, -8.0), cam_dist=200.0)
    if far is not None:
        check("大 cam_dist 顶点数不变", len(far[0]) == len(base[0]),
              "near=%d far=%d" % (len(base[0]), len(far[0])))
        check("大 cam_dist 网格逐位一致", bool(np.array_equal(far[0], base[0]))
              and bool(np.array_equal(far[1], base[1])))
    for _cd in (0.5, 5.0, 32.0, 200.0, 5000.0, 182500.0):
        o = build_grid_lines((0.0, 5.0, -8.0), cam_dist=_cd)
        if o is not None:
            check("cam_dist=%.1f 顶点数恒=%d" % (_cd, len(base[0])),
                  len(o[0]) == len(base[0]))
            check("cam_dist=%.1f 网格逐位一致" % _cd,
                  bool(np.array_equal(o[0], base[0])) and bool(np.array_equal(o[1], base[1])))

# 5. 淡出 alpha 分布: 近全亮 / 边缘全透 / 每顶点 alpha 严格按规则
#    淡出距离 = 线条所在轴坐标到相机的水平距离 (垂直格线 |x-eye.x|, 水平格线 |z-eye.z|)
out = build_grid_lines((0.0, 5.0, 0.0), cam_dist=30.0)   # half=60, fade 24->60
if out is not None:
    verts, cols = out
    alphas = cols[:, 3]
    check("存在近处全亮线", np.any(np.isclose(alphas, 1.0)))
    check("存在边缘全透线", np.any(np.isclose(alphas, 0.0)),
          "min_alpha=%.3f" % alphas.min())
    line_type = np.arange(len(verts)) % 4
    dvec = np.where(line_type < 2, np.abs(verts[:, 0] - 0.0),
                    np.abs(verts[:, 2] - 0.0))
    fade_end = 60.0
    fade_start = 24.0
    expected = np.where(dvec <= fade_start, 1.0,
                        np.where(dvec >= fade_end, 0.0,
                                 (fade_end - dvec) / (fade_end - fade_start)))
    check("alpha 与淡出规则一致", np.allclose(alphas, expected, atol=1e-6))
    order = np.argsort(dvec)
    check("alpha 随距离单调不增", np.all(np.diff(alphas[order]) <= 1e-6))

# 6. 线数恒定有界 (固定半宽 60, step 恒定 1): 极大 cam_dist 顶点数恒 = 4*(2*60+1)
out = build_grid_lines((0.0, 5.0, 0.0), cam_dist=5000.0)
if out is not None:
    verts, cols = out
    n_half = 60           # _GRID_HALF
    bound = 4 * (2 * n_half + 1)
    check("极大 cam_dist 线数有界", len(verts) <= bound,
          "verts=%d bound=%d" % (len(verts), bound))
    check("无非有限值", bool(np.isfinite(verts).all()) and bool(np.isfinite(cols).all()))

# 7. 极远 eye 不产生超大数组 (中心吸附到整数格, 数值稳定)
out = build_grid_lines((5000.0, 5000.0, 5000.0), cam_dist=30.0)
if out is not None:
    verts, cols = out
    check("极远 eye 线数有界", len(verts) <= 4 * (2 * 60 + 1))
    check("极远 eye 无非有限值", bool(np.isfinite(verts).all()))
    check("极远 eye 仍吸附整数格", bool(np.allclose(verts[:, 0] % 1.0, 0.0, atol=1e-3)))

# 8. 任何视角永不返回 None (相机为中心, 无足迹兜底概念)
for pitch in (-1.2, -0.5, 0.0, 0.5, 1.2):
    eye = (0.0, 5.0 * math.cos(pitch), -8.0)
    check("pitch=%.1f 网格非空" % pitch, build_grid_lines(eye, cam_dist=10.0) is not None)

print("总结果: ALL PASS ✅" if ok else "总结果: 有 FAIL ❌")
sys.exit(0 if ok else 1)
