# -*- coding: utf-8 -*-
# test_post_bloom.py — bloom 的**量化**验证（2026-11-10 阶段 2B2 调参 / Q-VIS-1=B）
#
# 为什么需要它：22 个旧场景里没有高亮物体，`MAE 变化`只能证明"画面变了"，不能证明
# "bloom 真的在起作用的区域起作用"。这里用 ab_bloom（暗场 + 白球）分别以
# strength=0 与 strength=0.7 渲染，比较**球周围晕圈**与**远处背景**：
#   · 晕圈必须显著变亮（相对 +5% 以上；圆心取关 bloom 帧的最亮像素，环半径 10–22px
#     实测 +22.1%，半径越小增量越大：6–14px +33.4%、8–18px +26.8%、20–40px +10.4%）；
#   · 远处背景必须几乎不变（|Δ| <= 0.005，实测 0.0000）—— 证明暗部没被糊亮。
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
sys.path.insert(0, HERE)
os.environ.setdefault('LOOM_NO_PARALLEL', '1')
os.environ['LOOM_NO_SAVE_MIGRATE'] = '1'
os.environ.setdefault('LOOM_NO_DIALOG', '1')

_fails = []


def check(name, cond, detail=''):
    print(('PASS ' if cond else 'FAIL ') + name + ('  ' + str(detail) if detail else ''))
    if not cond:
        _fails.append(name)


def _halo(img, center=None):
    """晕圈/远处亮度。center 必须来自**关 bloom** 那帧 —— 否则亮心会随 bloom 漂移，
    同一半径会量出不同结果（实测 +22.1% vs +42.5%），指标失去可复现性。"""
    lum = img.mean(axis=2)
    if center is None:
        cy, cx = np.unravel_index(int(np.argmax(lum)), lum.shape)
    else:
        cy, cx = center
    yy, xx = np.mgrid[0:lum.shape[0], 0:lum.shape[1]]
    r = np.sqrt((yy - cy) ** 2 + (xx - cx) ** 2)
    ring = (r >= 10) & (r <= 22)
    # 远处用「顶部黑天空」而不是同一圈的远处：那一圈仍有受光地面，bloom 尾巴会
    # 合理扩散；黑天空区域（距球心 >70px 且无场景内容）才代表「暗部不糊」。
    far = np.zeros_like(lum, dtype=bool)
    far[0:36, 120:360] = True
    return float(lum[ring].mean()), float(lum[far].mean()), float(lum[cy, cx]), (int(cy), int(cx))


def main():
    os.environ["LOOM_POST"] = "1"
    import test_ab_gl_vk as AB
    path = os.path.join(AB.SCENES_DIR, 'ab_bloom.json')
    check('场景 ab_bloom.json 存在', os.path.isfile(path), path)
    data = AB._load_scene(path)

    os.environ["LOOM_BLOOM_STRENGTH"] = "0.0"
    g0 = AB.render_gl(data)
    os.environ["LOOM_BLOOM_STRENGTH"] = "0.7"
    g1 = AB.render_gl(data)
    os.environ.pop("LOOM_BLOOM_STRENGTH", None)

    r0, f0, c0, pos = _halo(g0)
    r1, f1, c1, _ = _halo(g1, center=pos)      # 同一圆心，两帧可比
    delta = r1 - r0
    rel = delta / max(1e-6, r0)
    print('球心=%s  中心亮度=%.3f' % (pos, c0))
    print('晕圈: %.4f -> %.4f  Δ=%+.4f (%+.1f%%)' % (r0, r1, delta, 100 * rel))
    print('远处: %.4f -> %.4f  Δ=%+.4f' % (f0, f1, f1 - f0))

    check('亮物体中心确实很亮', c0 > 0.6, c0)
    check('bloom 让球周晕圈显著变亮（相对 +5% 以上）', rel >= 0.05, '%.1f%%' % (100 * rel))
    check('bloom 不糊暗部（远处背景 |Δ| <= 0.005）', abs(f1 - f0) <= 0.005,
          '%.4f' % (f1 - f0))
    check('bloom 只影响亮部附近（晕圈增量 > 远处增量的 10 倍）',
          delta > 10 * max(1e-6, abs(f1 - f0)), (delta, f1 - f0))

    print('=' * 60)
    if _fails:
        print('失败:', _fails)
        return 1
    print('ALL PASS')
    return 0


if __name__ == '__main__':
    sys.exit(main())
