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

    # ---------------- 入口级 (V-02 补): loom_lighting._aabbs_batched 真实入口 ----------------
    import time as _t
    import threading as _th
    from loom_types import Point3D
    import loom_lighting

    class _Mesh:
        def __init__(self, V):
            self.vertices = np.random.RandomState(V).rand(V, 3)

    class _Mat:
        _sat_f32 = 1.0
        _rgba = None
        albedo = None
        normal_map = None
        env_map = None

    class _Rend:
        material = _Mat()

    class _Model:
        def __init__(self, V, visible=True):
            self.mesh = _Mesh(V)
            self.renderer = _Rend()
            self.visible = visible
            self.normal_mode = 'flat'

    class _Batch:
        """只提供 _aabbs_batched 需要的引擎面 (无 GL)."""
        _AABB_PAR_MIN_WORK = 10 ** 12      # 强制串行内核
        def __init__(self):
            self._aabb_staging = _th.local()
            self._vh = {}
        def _prof_t0(self):                 # 计时钩子 (未开 LOOM_PROFILE 时等价 no-op)
            return 0.0
        def _prof_add(self, *a):
            return None
        def _homogeneous_vertices(self, mesh):
            k = id(mesh)
            if k not in self._vh:
                v = np.asarray(mesh.vertices, dtype=np.float64)
                vh = np.empty((v.shape[0], 4))
                vh[:, 0:3] = v
                vh[:, 3] = 1.0
                self._vh[k] = vh
            return self._vh[k]

    b = _Batch()
    models = [_Model(2035) for _ in range(6)] + [_Model(24) for _ in range(6)]
    fw = np.tile(np.eye(4), (len(models), 1, 1)).astype(np.float64)
    ref = None
    for impl in ('scalar', 'avx2', 'auto'):
        if impl == 'avx2' and fastpath.aabbs_simd_impl() == 0:
            continue
        b._aabb_staging = _th.local()
        if impl == 'auto':
            got = loom_lighting.LightingMixin._aabbs_batched(b, models, fw)
        else:
            orig = fastpath.aabbs_minmax
            try:
                fastpath.aabbs_minmax = (
                    lambda vh, m3, mn, mx, _i=impl:
                    fastpath.aabbs_minmax_impl(vh, m3, mn, mx, _i))
                got = loom_lighting.LightingMixin._aabbs_batched(b, models, fw)
            finally:
                fastpath.aabbs_minmax = orig
        if impl == 'scalar':
            ref = got
            check('入口级 _aabbs_batched 可跑 (scalar 基准)',
                  got is not None and len(got) == len(models))
        else:
            same = (ref is not None and got is not None
                    and len(got) == len(ref)
                    and all(tuple(x) == tuple(y) for x, y in zip(got, ref)))
            check('入口级 _aabbs_batched 逐位一致 (%s vs scalar)' % impl, bool(same))

    # 性能门禁 (入口级, 2-3x 余量): AVX2 版必须明显快于标量版
    def _timed(impl, reps=12):
        orig = fastpath.aabbs_minmax
        try:
            if impl != 'auto':
                fastpath.aabbs_minmax = (
                    lambda vh, m3, mn, mx, _i=impl:
                    fastpath.aabbs_minmax_impl(vh, m3, mn, mx, _i))
            b._aabb_staging = _th.local()
            for _ in range(3):
                loom_lighting.LightingMixin._aabbs_batched(b, models, fw)
            t0 = _t.perf_counter()
            for _ in range(reps):
                loom_lighting.LightingMixin._aabbs_batched(b, models, fw)
            return (_t.perf_counter() - t0) / reps * 1000.0
        finally:
            fastpath.aabbs_minmax = orig

    t_scalar = _timed('scalar')
    if fastpath.aabbs_simd_impl() == 1:
        t_avx = _timed('auto')
        print('  入口耗时: scalar=%.3f ms  avx2=%.3f ms  (比值 %.2f)'
              % (t_scalar, t_avx, t_avx / max(t_scalar, 1e-9)))
        check('性能门禁: 入口级 AVX2 <= 0.90x 标量', t_avx <= t_scalar * 0.90,
              'ratio=%.2f' % (t_avx / max(t_scalar, 1e-9)))
    else:
        print('  (无 AVX2: 跳过入口级加速门禁, scalar=%.3f ms)' % t_scalar)
    check('性能门禁: 入口级单批绝对上限 (<=40ms, 实测 %.2f)' % t_scalar, t_scalar <= 40.0)

    # LOOM_NO_SIMD=1 -> 强制标量 (子进程验证: 环境在首次探测时读一次)
    import subprocess
    code = ("import os,sys;sys.path.insert(0,%r);os.chdir(%r);"
            "import fastpath;print(fastpath.aabbs_simd_impl())" % (ROOT, ROOT))
    env_no = dict(os.environ); env_no['LOOM_NO_SIMD'] = '1'
    out_no = subprocess.run([sys.executable, '-c', code], capture_output=True,
                            text=True, env=env_no, timeout=120)
    check('LOOM_NO_SIMD=1 -> 分派强制标量 (子进程 impl=0)',
          out_no.stdout.strip().endswith('0'), out_no.stdout.strip()[-40:] + out_no.stderr[-120:])
    env_off = dict(os.environ); env_off.pop('LOOM_NO_SIMD', None)
    out_def = subprocess.run([sys.executable, '-c', code], capture_output=True,
                             text=True, env=env_off, timeout=120)
    check('默认 (无该 env) 分派结果与 CPUID 一致 (0/1)',
          out_def.stdout.strip()[-1:] in ('0', '1'), out_def.stdout.strip()[-40:])

    print()
    print('test_aabb_simd:', 'ALL PASS' if ok else 'HAS FAILURES')
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
