# -*- coding: utf-8 -*-
"""test_aabb_simd.py — D3: AABB 内核 AVX2 与标量**逐位一致** + CPUID 分派可用性.

断言:
  ① 分派查询可用 (loom_aabbs_simd_impl 存在, 返回 0/1) + **独立判据**
     (_avx2_available(): kernel32 的 CPU 特性表, 不经被测对象) 与它不矛盾:
     独立判据说支持而它报 0 -> FAIL(探测坏了, 不是机器不支持), 不许 SKIP
  ② 真实形状 (V=2035/1617/24/4, n 配套) 下 scalar / avx2 / 分派版 三者
     min/max **逐字节相同** (有限输入; 引擎顶点恒有限)
  ③ 尾部路径覆盖: V=1..7 全跑一遍逐位一致 (AVX2 每轮 4 顶点 + 标量尾)
  ④ 无 AVX2 的机器上: 分派版 == scalar (本机若无 AVX2, 合法 SKIP ②③ 的 avx2 对比)
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

import kernels.fastpath as fastpath                                              # noqa: E402

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


# ---------------- 独立判据 (共用): 本机是否支持 AVX2, 不经被测对象 ----------------
# 为什么必须有它 (Q-B7-34-2 发现, Q-B7-35-1 = A 全修):
#   旧写法用**被测对象自己**的探测结果 (fastpath.aabbs_simd_impl()) 决定要不要跑
#   avx2 逐位对比 (②③) 与两个加速门。探测一旦坏掉 (AVX2 机器上恒报 0), ②③ 的
#   avx2 对比与两个加速门就整段跳过, 只剩一行 SKIP -> ALL PASS / exit 0 ——
#   "考生自己说不用考, 监考就不考了"。实测变异 simd_impl_reports_0
#   (Python 层 monkeypatch 恒返回 0) 全绿, 见本任务留痕。
# 独立判据 = kernel32!IsProcessorFeaturePresent(PF_AVX2_INSTRUCTIONS_AVAILABLE=40):
#   · 由 Windows 内核/ntdll 回答 (用内核启动时建的 CPU 特性表), **不经过**
#     loom_kernels.dll, 也不经过 fastpath.aabbs_simd_impl() —— 与本 DLL 里那段
#     __cpuid/_xgetbv 是两条独立代码路径, 探测被改坏不会连带改变它的答案。
#   · 语义与 DLL 的门槛同源: OSXSAVE + AVX + XGETBV(XMM|YMM 已开) + CPUID leaf7
#     EBX.bit5, 即「本进程能否真的执行 AVX2 指令」—— 正是要判的那件事。
#   · 它只可能「漏报支持」(老系统无该 feature id 时返回 FALSE), 不会把不支持的
#     机器误判成支持, 所以不会引入假红。
# ★本文件**只有这一处**实现 (git grep IsProcessorFeaturePresent 可核): ②③ 逐位
#   一致段与性能门禁段共用它, 不许在别处复制第二套。
def _avx2_available():
    """True/False = 本机是否支持 AVX2 (独立于 loom_kernels.dll 的判据);
    None = 该判据在本机不可用 (非 Windows 或取不到 kernel32)。"""
    if sys.platform != 'win32':
        return None
    try:
        import ctypes
        _k32 = ctypes.WinDLL('kernel32', use_last_error=True)
        _fn = _k32.IsProcessorFeaturePresent
        _fn.restype = ctypes.c_int
        _fn.argtypes = [ctypes.c_uint32]
        return bool(_fn(40))       # PF_AVX2_INSTRUCTIONS_AVAILABLE (Win10 1709+)
    except Exception:
        return None


def _avx2_gate(impl):
    """判据组合 (②③ 逐位一致段与性能门禁段**共用同一份**, 顺序即优先级)。

    返回 (cpu_avx2, no_simd_env, probe_broken, do_avx2_cmp):
      cpu_avx2     独立判据 _avx2_available(): True/False/None
      no_simd_env  LOOM_NO_SIMD=1 -> 人为要求走标量 (不是探测坏了)
      probe_broken 独立判据=支持 且 impl!=1 (且非人为强制标量)
                   -> FAIL「探测坏了, 不是机器不支持」, **不许 SKIP**
      do_avx2_cmp  「是否真的要做 avx2 对比」: impl=1 照常; 探测坏了也照做
                   (独立判据说机器支持, 显式走 avx2 路径安全, 且能把 DLL 的真实
                   输出一起验掉); 真正的红由 probe_broken 那条 FAIL 给出,
                   **不靠跳过对比来"过关"**。
    """
    cpu_avx2 = _avx2_available()
    # LOOM_NO_SIMD=1 是**人为要求**走标量 (与 C 侧 _simd_impl 的判据同一写法:
    # 只认正好 "1"), 此时 impl=0 不是探测坏了, 属于合法跳过。
    no_simd_env = (os.environ.get('LOOM_NO_SIMD') == '1')
    probe_broken = (cpu_avx2 is True and impl != 1 and not no_simd_env)
    do_avx2_cmp = (impl == 1) or probe_broken
    return cpu_avx2, no_simd_env, probe_broken, do_avx2_cmp


def main():
    impl = fastpath.aabbs_simd_impl()
    check('① 分派查询可用 (0=标量 / 1=AVX2)', impl in (0, 1), impl)
    # ---------------- 独立判据 + 判据组合 (共用; 实现见模块级 _avx2_available/_avx2_gate) ----------------
    # Q-B7-35-1 = A (全修): ②③ 的 avx2 逐位对比**不许**再由被测对象自报决定要不要测。
    #   ① 独立判据=支持 且 impl!=1 -> FAIL(探测坏了, 不是机器不支持), 不许 SKIP;
    #   ② 独立判据=不支持 且 impl=0 -> 合法 SKIP (保留 SKIP 行并说明);
    #   ③ LOOM_NO_SIMD=1 -> 人为要求标量, 归入合法 SKIP (不是探测坏了);
    #   ④ impl=1 -> 正常做 avx2 逐位对比 (现状)。
    # 性能门禁段用的是同一份 _avx2_gate() 结果, 不复制第二套。
    _impl = impl          # 被测对象自报 (下面 `for impl in (...)` 会覆盖 impl 名字, 故另存)
    _cpu_avx2, _no_simd_env, _probe_broken, _do_avx2_cmp = _avx2_gate(_impl)
    if _cpu_avx2 is None:
        print('  (独立判据 kernel32 CPU 特性表不可用: 退回只看 aabbs_simd_impl(), '
              '该分支不具备「探测坏掉也能抓红」的能力)')
    if _probe_broken:
        check('① 独立判据 vs 分派探测: 本机支持 AVX2 时 aabbs_simd_impl() 必须报 1 '
              '(实测 %r)' % (_impl,),
              False,
              '探测坏了, 不是机器不支持: 独立判据 _avx2_available()=True '
              '(kernel32 PF_AVX2_INSTRUCTIONS_AVAILABLE=40), 而 '
              'fastpath.aabbs_simd_impl()=%r。②③ 的 avx2 逐位对比与入口级/批量级'
              '加速门都**不能**因被测对象自报 0 而整段跳过 —— 那正是静默假绿通道。'
              % (_impl,))

    shapes = [(90, 2035), (90, 1617), (100, 3015), (501, 24), (501, 4)]
    worst = 0
    same = True
    for n, V in shapes:
        vh, m3 = make(n, V, seed=V)
        mn_s, mx_s = run(vh, m3, 'scalar')
        mn_a, mx_a = run(vh, m3, 'auto')
        same = same and np.array_equal(mn_s, mn_a) and np.array_equal(mx_s, mx_a)
        if _do_avx2_cmp:
            mn_v, mx_v = run(vh, m3, 'avx2')
            if not (np.array_equal(mn_s, mn_v) and np.array_equal(mx_s, mx_v)):
                same = False
            worst = max(worst, float(np.abs(mn_s - mn_v).max()) if mn_s.size else 0.0)
    check('② 真实形状 scalar / avx2 / 分派 逐位一致', same, 'max|diff|=%r' % worst)

    tail_ok = True
    for V in range(1, 8):
        vh, m3 = make(7, V, seed=100 + V)
        mn_s, mx_s = run(vh, m3, 'scalar')
        if _do_avx2_cmp:
            mn_v, mx_v = run(vh, m3, 'avx2')
            tail_ok = tail_ok and np.array_equal(mn_s, mn_v) and np.array_equal(mx_s, mx_v)
        mn_a, mx_a = run(vh, m3, 'auto')
        tail_ok = tail_ok and np.array_equal(mn_s, mn_a) and np.array_equal(mx_s, mx_a)
    check('③ 尾部路径 (V=1..7) 逐位一致', tail_ok)

    if not _do_avx2_cmp:
        _skip_why = ('LOOM_NO_SIMD=1 强制标量 (人为要求)' if _no_simd_env
                     else ('本机 CPU 不支持 AVX2 (分派已回退标量)' if _cpu_avx2 is False
                           else '独立判据不可用且分派自报标量'))
        print('SKIP ②③ 的 avx2 对比: %s (独立判据=%r, aabbs_simd_impl()=%r)'
              % (_skip_why, _cpu_avx2, _impl))
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
    from core.primitives import Point3D
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
        if impl == 'avx2' and not _do_avx2_cmp:   # 不用被测对象自报 (Q-B7-35-1)
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

    # ---------------- 性能门禁 (Q-B7-33-3 = A+B, 2026-11-18 重做) ----------------
    # 旧门为什么废 (修前实测, 空载 10 轮, 同一台机器):
    #   入口级 reps=12 单次 scalar->avx2 比较, 单批工作量 ~0.17ms → 总测量 ~2ms,
    #   **噪声量级 = 效应量级**: 比值 0.666 0.737 0.756 0.772 0.796 0.836 0.839
    #   0.963 1.042 (中位 0.784 / 最坏 1.042 / 2-10 轮 >0.90 假红)。真实入口级
    #   加速只有 ~1.2x, 阈值 0.90 仅剩 12% 余量 —— 不是门太严, 是测量方法不成立。
    # 新方法 (A): reps>=200 (单轮测量拉到百毫秒级) + **交替测 7 轮取中位数**
    #   (每轮交换 scalar / AVX2 先后顺序: 温漂与突发负载对两侧对称, 不偏置比值;
    #   中位数滤掉单轮毛刺) + 阈值按实测分布定 (数字见各门注释)。
    # 新位置 (B): **严格加速门移到批量级** —— 单次内核调用吃整个 (n,V) 批,
    #   实测 2.28x, 信噪比足够; 入口级只留宽松门「AVX2 不慢于标量」。
    import statistics as _st
    _PERF_ROUNDS = 7                  # 交替轮数 (取中位数)
    _ENTRY_REPS = 300                 # 入口级: 每轮 300 次 (~60ms/轮, 百毫秒级)
    _BATCH_REPS = 200                 # 批量级: 每轮 200 次 (~200ms/轮)

    def _as_scalar(vh, m3, mn, mx):
        return fastpath.aabbs_minmax_impl(vh, m3, mn, mx, 'scalar')

    def _entry_ms(scalar, reps=_ENTRY_REPS):
        """入口级 _aabbs_batched 单次耗时 (ms)。scalar=True 时把生产分派入口临时
        换成强制标量; False 走**生产分派** (auto = CPUID 选中的实现)。"""
        orig = fastpath.aabbs_minmax
        try:
            if scalar:
                fastpath.aabbs_minmax = _as_scalar
            b._aabb_staging = _th.local()
            for _ in range(3):
                loom_lighting.LightingMixin._aabbs_batched(b, models, fw)
            t0 = _t.perf_counter()
            for _ in range(reps):
                loom_lighting.LightingMixin._aabbs_batched(b, models, fw)
            return (_t.perf_counter() - t0) / reps * 1000.0
        finally:
            fastpath.aabbs_minmax = orig

    # 批量级: 一次内核调用吃整个 (n,V) 批 —— 与 ② 同一真实形状 (n=90, V=2035),
    # 无逐模型 Python 组装开销, 是 AVX2 跨顶点并行收益真正体现的层级。
    _bh, _bm3 = make(90, 2035, seed=2035)
    _bmn = np.empty((_bh.shape[0], 3), dtype=np.float64)
    _bmx = np.empty((_bh.shape[0], 3), dtype=np.float64)

    def _batch_ms(scalar, reps=_BATCH_REPS):
        """批量级单次内核耗时 (ms); scalar / 生产分派 与 _entry_ms 同口径。"""
        orig = fastpath.aabbs_minmax
        try:
            if scalar:
                fastpath.aabbs_minmax = _as_scalar
            for _ in range(3):
                fastpath.aabbs_minmax(_bh, _bm3, _bmn, _bmx)
            t0 = _t.perf_counter()
            for _ in range(reps):
                fastpath.aabbs_minmax(_bh, _bm3, _bmn, _bmx)
            return (_t.perf_counter() - t0) / reps * 1000.0
        finally:
            fastpath.aabbs_minmax = orig

    def _ratio_median(measure, rounds=_PERF_ROUNDS):
        """交替测 scalar / 生产分派, 返回 (每轮比值, 比值中位数, 标量中位数,
        加速版中位数)。每轮交替先后顺序 —— 消温漂/负载漂移偏置。"""
        rs, ts, tas = [], [], []
        for r in range(rounds):
            if r % 2 == 0:
                t_s = measure(True)
                t_a = measure(False)
            else:
                t_a = measure(False)
                t_s = measure(True)
            ts.append(t_s)
            tas.append(t_a)
            rs.append(t_a / max(t_s, 1e-9))
        return rs, _st.median(rs), _st.median(ts), _st.median(tas)

    # ---------------- 性能门禁的独立判据 / 判据组合: 见上方「独立判据 + 判据组合」段 ----------------
    # 独立判据由 Q-B7-34-2 引入 (为什么必须有它, 理由写在模块级 _avx2_available() 上方);
    # Q-B7-35-1 起 ②③ 逐位一致段与本节**共用**模块级 _avx2_available()/_avx2_gate(),
    # 本段不再自带第二套探测 (判据实现只在模块级那一处)。
    if _probe_broken:
        t_scalar = _entry_ms(True, reps=100)
        print('  (探测坏了: 跳过入口级/批量级加速门禁; 上面的 FAIL 已让本测试变红)')
    elif _impl == 1:
        # ---- 入口级: 宽松门 (B) ----
        # 修后实测中位数分布 0.781~0.845 (空载 17 次 + 8 进程背景负载 2 次)。
        # 阈值 1.05; 只挡「AVX2 反而比标量慢」, 不在此设严格门 (入口级真实
        # 加速仅 ~1.2x, 信噪比不够)。
        # ★余量口径 (Q-B7-34-4: 后续调阈值必须按同一把尺比):
        #   本文件说的「留 24% 余量」= **阈值 ÷ 实测最坏 − 1** = 1.05 / 0.841 − 1
        #   = 0.249 ≈ 24.9% (最坏实测取 0.841; 用分布上沿 0.845 则 24.3%)。
        #   另一种常见口径「实测距阈值的相对余量」= (阈值 − 实测) / 阈值 =
        #   (1.05 − 0.841) / 1.05 = 19.9% —— 两个数字都对, 但**不是同一把尺**;
        #   引用时请连口径一起引 (否则「24%」和「19.9%」会看起来像矛盾)。
        e_rs, e_med, t_scalar, t_avx = _ratio_median(_entry_ms)
        print('  入口级 (7 轮交替, reps=%d): scalar=%.3f ms  avx2=%.3f ms  比值[%s] 中位数=%.3f'
              % (_ENTRY_REPS, t_scalar, t_avx,
                 ' '.join('%.2f' % x for x in e_rs), e_med))
        check('性能门禁: 入口级 AVX2 不慢于标量 (<= 1.05x, 实测中位数 %.3f)' % e_med,
              e_med <= 1.05, 'rounds=[%s]' % ' '.join('%.2f' % x for x in e_rs))

        # ---- 批量级: 严格加速门 (B) ----
        # 修后实测中位数分布 0.427~0.458 (空载 17 次 + 8 进程负载 2 次), 真实
        # 加速 2.18~2.34x。阈值 0.65 (= 至少 1.54x); 真回归 (AVX2 收益掉到
        # 1.54x 以下, 例如分派回退标量 → 比值 ~1.0) 必红。
        # ★余量口径 (同入口级, Q-B7-34-4): 「留 42% 余量」= 阈值 ÷ 实测最坏 − 1
        #   = 0.65 / 0.457 − 1 = 0.422 ≈ 42.2% (最坏实测 0.457; 用 0.458 则 41.9%)。
        #   按「实测距阈值的相对余量」口径则是 (0.65 − 0.457) / 0.65 = 29.7% ≈ 30%。
        b_rs, b_med, b_s, b_a = _ratio_median(_batch_ms)
        print('  批量级 (n=90,V=2035; 7 轮交替, reps=%d): scalar=%.3f ms  avx2=%.3f ms  '
              '比值[%s] 中位数=%.3f (加速 %.2fx)'
              % (_BATCH_REPS, b_s, b_a, ' '.join('%.2f' % x for x in b_rs),
                 b_med, 1.0 / max(b_med, 1e-9)))
        check('性能门禁: 批量级 AVX2 <= 0.65x 标量 (>=1.54x 加速, 实测中位数 %.3f)' % b_med,
              b_med <= 0.65, 'ratio=%.3f 加速=%.2fx' % (b_med, 1.0 / max(b_med, 1e-9)))
    else:
        # 合法跳过, 两种来源: (a) 独立判据与 impl 一致认为本机不支持 AVX2;
        # (b) 本进程被 LOOM_NO_SIMD=1 显式要求走标量 (人为要求, 不是探测坏了)。
        t_scalar = _entry_ms(True, reps=100)
        print('  SKIP 入口级/批量级加速门禁: %s (独立判据=%r, aabbs_simd_impl()=%r)'
              % ('LOOM_NO_SIMD=1 强制标量' if _no_simd_env else '本机不支持 AVX2',
                 _cpu_avx2, _impl))
        print('  (无 AVX2: scalar=%.3f ms)' % t_scalar)
    check('性能门禁: 入口级单批绝对上限 (<=40ms, 实测 %.2f)' % t_scalar, t_scalar <= 40.0)

    # LOOM_NO_SIMD=1 -> 强制标量 (子进程验证: 环境在首次探测时读一次)
    import subprocess
    code = ("import os,sys;sys.path.insert(0,%r);os.chdir(%r);"
            "from kernels import fastpath;print(fastpath.aabbs_simd_impl())" % (ROOT, ROOT))
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
