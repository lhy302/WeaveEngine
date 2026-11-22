# -*- coding: utf-8 -*-
"""test_line_degenerate_segment_parity.py — 退化段判据「两端一致」（Q-B7-53-3 门）。

## 为什么有这个门（2026-11-22，审核 1/3 查出）

Q-B7-48-1 裁决 B 把「垂直偏移」数学收成唯一一份
`mathlib/line_geometry.py::expand_segment`：VK 的 UI 描边
（`render/vk/ui.py::VkUIEngine.draw_screen_lines`）与编辑器/GL 的粗线
（`build_line_quads`）都调它。替换内联实现时注释写了「与旧实现逐位相同」——
事实不成立，两处差异：

  · 长度算法换了：旧内联 `(dx*dx + dy*dy) ** 0.5`，新 `math.hypot(dx, dy)`
    -> 随机 20 万条线段里 3356/800000 个分量**逐位不同**，最大 5.7e-14
    （双精度舍入级，视觉无差）-> 注释改为「语义等价」；
  · 退化段判据换了：旧内联 `ln < 1e-6 -> 跳过`，新 `ln >= 1e-9 -> 保留`
    -> 长度落在 [1e-9, 1e-6) 的段**旧丢新画**。这是**行为变更**，不是等价。

## 本门的最高准则：两端一致

判据只许**一份**。GL 的粗线与 VK 的 UI 描边都走 `expand_segment`，所以
「1e-9 才保留」这个判据天然两端同源；反过来，若为了迁就旧 VK 内联而把判据
回退到 1e-6，就得在 GL 侧**新增**一个它从来没有过的门槛 —— 那才是新的两端
不一致。故保留 1e-9，并用本门钉死四件事：

  A 判据唯一（源码层）：两个调用点都调 `expand_segment`，可执行代码里不再
    出现内联的 `** 0.5` 长度公式与 `ln < 1e-6` 判据；
  B 语义等价（数值层）：新旧实现（hypot vs ** 0.5）的角点分量差 <= 1e-12（双精度舍入级；审核样本 20 万段实测 6e-14，本门宽域样本（坐标 ±2000px）实测 2.3e-13，同量级）；
  C 退化段判据（行为层）：长度 5e-7 的段**两端都画**、长度 1e-10 的段**两端都不画**；
  D 两端一致表：一组长度上「画/不画」的判定，GL 路径与 VK 路径逐项相同。

## 为什么保留 1e-9（理由留痕，不是随手改阈值）

  · 屏幕上 5e-7 像素长的段仍有方向（双精度下 dx,dy 的相对误差 ~1e-16），
    2px 宽的四边形照样覆盖像素；丢掉它会在 UI 折线的极短段处留 1px 缺口；
  · 1e-9 以下方向已不可信（归一化把误差放大），且远小于任何光栅化量化单位
    —— 跳过它不产生可见缺口。

## 修前必红（实跑原文见交付报告）

把 `render/vk/ui.py::draw_screen_lines` 换回修前内联实现（`** 0.5` + `ln < 1e-6`）
后跑本门：A 红（可执行代码里出现内联公式）、C/D 红（5e-7 段 GL 画、VK 不画）。
"""
import inspect
import os
import sys

import numpy as np

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)
os.chdir(BASE)

from mathlib.line_geometry import expand_segment, build_line_quads  # noqa: E402
from render.vk.ui import VkUIEngine                                # noqa: E402

W, H = 1000, 600
HW = 1.0                      # 半线宽（像素）；两端同一个值
_SEG_LEN = 5e-7               # 审核点名的长度：旧判据 1e-6 会丢、新判据 1e-9 会画
_TINY_LEN = 1e-10             # 1e-9 以下：两端都该丢

ok = True


def check(label, cond, detail=""):
    global ok
    print(("PASS " if cond else "FAIL ") + label + ("  " + str(detail) if detail else ""))
    if not cond:
        ok = False


def _old_inline(p0, p1, hw):
    """修前 VK 内联实现（660a5d8 之前 vk_ui.py 的那 8 行，逐字照抄）。"""
    x0, y0 = float(p0[0]), float(p0[1])
    x1, y1 = float(p1[0]), float(p1[1])
    dx, dy = x1 - x0, y1 - y0
    ln = (dx * dx + dy * dy) ** 0.5
    if ln < 1e-6:
        return None
    nx, ny = -dy / ln * hw, dx / ln * hw
    return ((x0 + nx, y0 + ny), (x1 + nx, y1 + ny), (x1 - nx, y1 - ny), (x0 - nx, y0 - ny))


def _code_only(src):
    """去掉注释行后的源码（注释里会写 '1e-6 -> 1e-9' 这类历史说明，不算代码）。"""
    return "\n".join(l for l in src.splitlines() if not l.strip().startswith("#"))


# ---------------------------------------------------------------- A 判据唯一
def part_a():
    lg_src = inspect.getsource(expand_segment)
    vk_src = _code_only(inspect.getsource(VkUIEngine.draw_screen_lines))
    check("A1 expand_segment 的退化段判据是 1e-9（唯一判据所在处）",
          "ln >= 1e-9" in lg_src, [l.strip() for l in lg_src.splitlines() if "1e-9" in l])
    check("A2 VK UI 描边调用共享 expand_segment（垂直偏移数学不各自再抄一份）",
          "expand_segment(" in vk_src)
    check("A3 VK UI 描边的可执行代码里没有内联长度公式（(dx * dx + dy * dy) ** 0.5）",
          "(dx * dx + dy * dy)" not in vk_src)
    check("A4 VK UI 描边的可执行代码里没有内联退化判据（ln < 1e-6）",
          "ln < 1e-6" not in vk_src)
    check("A5 GL/编辑器的粗线也走同一个 expand_segment（build_line_quads 内调用）",
          "expand_segment(" in inspect.getsource(build_line_quads))


# ---------------------------------------------------------------- B 语义等价
def part_b():
    rng = np.random.RandomState(20261122)
    n = 200000
    p0 = rng.uniform(-2000.0, 2000.0, size=(n, 2))
    p1 = rng.uniform(-2000.0, 2000.0, size=(n, 2))
    max_diff = 0.0
    diff_components = 0
    total_components = 0
    for k in range(n):
        a = expand_segment(p0[k], p1[k], HW)
        b = _old_inline(p0[k], p1[k], HW)
        if a is None or b is None:
            continue
        for ca, cb in zip(a, b):
            for u, v in zip(ca, cb):
                total_components += 1
                if u != v:
                    diff_components += 1
                    max_diff = max(max_diff, abs(u - v))
    check("B1 新旧实现的角点分量差 <= 1e-12（双精度舍入级，语义等价）",
          max_diff <= 1e-12,
          "max=%.3e 逐位不同 %d/%d 分量" % (max_diff, diff_components, total_components))
    check("B2 前置：真的量到了足量分量（20 万段 x 8 分量）",
          total_components == n * 8, total_components)


# ------------------------------------------------------- C/D 两端行为一致
def _gl_draws(seg_len_px):
    """GL/编辑器粗线路径：屏幕空间长 seg_len_px 的段 -> 是否产出三角形顶点。"""
    dx_ndc = 2.0 * seg_len_px / W
    verts = np.array([[0.0, 0.0, 0.5], [dx_ndc, 0.0, 0.5]], dtype=np.float32)
    cols = np.array([[1.0, 1.0, 1.0], [1.0, 1.0, 1.0]], dtype=np.float32)
    out_v, _c, _vp = build_line_quads(verts, cols, np.eye(4, dtype=np.float32),
                                      width_px=HW * 2.0, viewport_size=(W, H),
                                      mode="lines")
    return len(out_v)


def _vk_draws(seg_len_px):
    """VK UI 描边路径：同一段（像素坐标）-> 是否产出三角形顶点。"""
    eng = VkUIEngine(pipeline=None)          # 本段只走 _emit 收集，不需要 GPU 管线
    eng.begin_frame(W, H)
    eng.draw_screen_lines([(500.0, 300.0), (500.0 + seg_len_px, 300.0)],
                          (1.0, 1.0, 1.0), width=HW * 2.0)
    n = 0
    for _tex, _sc, vs in eng._ops:
        n += len(vs)
    return n


def part_cd():
    gl_seg, vk_seg = _gl_draws(_SEG_LEN), _vk_draws(_SEG_LEN)
    check("C1 长度 5e-7 的段在 GL/编辑器粗线上会画（产出 6 顶点）", gl_seg == 6, gl_seg)
    check("C2 长度 5e-7 的段在 VK UI 描边上会画（产出 6 顶点）", vk_seg == 6, vk_seg)
    gl_tiny, vk_tiny = _gl_draws(_TINY_LEN), _vk_draws(_TINY_LEN)
    check("C3 长度 1e-10 的段在 GL/编辑器粗线上不画（0 顶点）", gl_tiny == 0, gl_tiny)
    check("C4 长度 1e-10 的段在 VK UI 描边上不画（0 顶点）", vk_tiny == 0, vk_tiny)

    table = []
    mismatch = []
    for seg in (0.0, 1e-12, 5e-10, 1e-9, 5e-7, 1e-3, 0.5, 2.0):
        g, v = _gl_draws(seg), _vk_draws(seg)
        gd, vd = g > 0, v > 0
        table.append((seg, gd, vd))
        if gd != vd:
            mismatch.append((seg, g, v))
    check("D1 两端「画/不画」判定逐项一致（8 个长度：0/1e-12/5e-10/1e-9/5e-7/1e-3/0.5/2.0）",
          not mismatch, "不一致 %r | 表 %r" % (mismatch, table))
    check("D2 前置：两端一致表里既有「画」也有「不画」（不是全同的平凡一致）",
          any(t[1] for t in table) and any(not t[1] for t in table), table)


def main():
    part_a()
    part_b()
    part_cd()
    print()
    if not ok:
        print("FAIL: test_line_degenerate_segment_parity.py")
        sys.exit(1)
    print("ALL PASS (test_line_degenerate_segment_parity.py)")


main()
