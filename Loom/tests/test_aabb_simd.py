# -*- coding: utf-8 -*-
"""test_aabb_simd.py — D3: AABB 内核 AVX2 与标量**逐位一致** + CPUID 分派可用性.

断言:
  ① 分派查询可用 (loom_aabbs_simd_impl 存在, 返回 0/1)
  ② 真实形状 (V=2035/1617/24/4, n 配套) 下 scalar / avx2 / 分派版 三者
     min/max **逐字节相同** (有限输入; 引擎顶点恒有限)
  ③ 尾部路径覆盖: V=1..7 全跑一遍逐位一致 (AVX2 每轮 4 顶点 + 标量尾)
  ④ 无 AVX2 的机器上: 分派版 == scalar (本机若无 AVX2, 跳过 ②③ 的 avx2 对比)
  ⑤ 公开入口 aabbs_minmax 走分派版, 与 scalar 逐位一致
注意: AVX2 只做**跨顶点**并行, 同一顶点的运算顺序与标量一字不改 —— 这是逐位的根据。
"""
import sys as _sys_utf8
try:
    _sys_utf8.stdout.reconfigure(encoding='utf-8', errors='replace')
    _sys_utf8.stderr.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
os.chdir(ROOT)

import fastpath                                              # noqa: E402

ok = True


def check(label, cond, detail=''):
    global ok
    print(('PASS ' if cond else 'FAIL ') + label + ('  ' + str(detail) if detail else ''))
    if not cond:
        ok = False


def make(n, V, seed=0):
    rng = np.random.RandomState(seed)
    vh = rng.rand(n, V, 4)
    vh[:, :, 3] = 1.0                 # 齐次 w=1
    m3 = rng.rand(n, 4, 3)
    return np.ascontiguousarray(vh), np.ascontiguousarray(m3)


def run(vh, m3, impl):
    mn = np.empty((vh.shape[0], 3), dtype=np.float64)
    mx = np.empty((vh.shape[0], 3), dtype=np.float64)
    fastpath.aabbs_minmax_impl(vh, m3, mn, mx, impl)
    return mn, mx


def main():
    impl = fastpath.aabbs_simd_impl()
    check('① 分派查询可用 (0=标量 / 1=AVX2)', impl in (0, 1), impl)

    shapes = [(90, 2035), (90, 1617), (100, 3015), (501, 24), (501, 4)]
    worst = 0
    same = True
    for n, V in shapes:
        vh, m3 = make(n, V, seed=V)
        mn_s, mx_s = run(vh, m3, 'scalar')
        mn_a, mx_a = run(vh, m3, 'auto')
        same = same and np.array_equal(mn_s, mn_a) and np.array_equal(mx_s, mx_a)
        if impl == 1:
            mn_v, mx_v = run(vh, m3, 'avx2')
            if not (np.array_equal(mn_s, mn_v) and np.array_equal(mx_s, mx_v)):
                same = False
            worst = max(worst, float(np.abs(mn_s - mn_v).max()) if mn_s.size else 0.0)
    check('② 真实形状 scalar / avx2 / 分派 逐位一致', same, 'max|diff|=%r' % worst)

    tail_ok = True
    for V in range(1, 8):
        vh, m3 = make(7, V, seed=100 + V)
        mn_s, mx_s = run(vh, m3, 'scalar')
        if impl == 1:
            mn_v, mx_v = run(vh, m3, 'avx2')
            tail_ok = tail_ok and np.array_equal(mn_s, mn_v) and np.array_equal(mx_s, mx_v)
        mn_a, mx_a = run(vh, m3, 'auto')
        tail_ok = tail_ok and np.array_equal(mn_s, mn_a) and np.array_equal(mx_s, mx_a)
    check('③ 尾部路径 (V=1..7) 逐位一致', tail_ok)

    if impl == 0:
        print('SKIP ②③ 的 avx2 对比: 本机 CPU 不支持 AVX2 (分派已回退标量)')
    check('④ 分派版与 scalar 一致 (无 AVX2 机器即"自动回退"证据)', same)

    # ⑤ 公开入口 (= 生产路径) 与 scalar 一致, 且空批/边界不炸
    vh, m3 = make(32, 2035, seed=7)
    mn = np.empty((32, 3)); mx = np.empty((32, 3))
    fastpath.aabbs_minmax(vh, m3, mn, mx)
    mn_s, mx_s = run(vh, m3, 'scalar')
    check('⑤ 公开入口 aabbs_minmax 与 scalar 逐位一致',
          np.array_equal(mn, mn_s) and np.array_equal(mx, mx_s))
    mn0 = np.empty((0, 3)); mx0 = np.empty((0, 3))
    fastpath.aabbs_minmax(np.empty((0, 4, 4)), np.empty((0, 4, 3)), mn0, mx0)
    check('⑤ 空批 (n=0) 不炸', True)

    print()
    print('test_aabb_simd:', 'ALL PASS' if ok else 'HAS FAILURES')
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
