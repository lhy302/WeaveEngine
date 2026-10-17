# -*- coding: utf-8 -*-
"""fastpath.py — 组3 公共静态化模块 (numba 可选加速, 未安装自动降级纯 Python).

背景 (2026-08-30, 组3层1/2 桥接, 代理 B):
  Loom 引擎热路径里有两类纯数组算法——深度 DP (compute_world_matrices 沿父链
  爬根) 和 ancestry DFS (EAI/A1 祖先区间查询). 它们都是 O(n) 纯 Python 循环,
  n 大时解释器开销占比高. 本模块为它们提供 Numba @njit 版本; numba 未安装时
  自动退回纯 Python 实现, **数值逐位同源** (同一算法直译, 仅速度差).

降级路径说明:
  纯 Python 降级 = 参考实现本体, 与 numba 编译版算法/数据类型完全一致
  (np.int64 一维数组进出, 同样的循环语义), 因此两种路径下结果逐位相同.
  装上 numba 后无需改任何调用点.

接线状态:
  - engine.compute_world_matrices 深度 DP 循环 -> depths()   (已接)
  - engine._ancestry_ranges           -> ancestry_dfs()      (已接, D1)
  - engine._aabbs_batched             -> aabbs_minmax()      (已接; 2026-08-31 起
    默认串行版, prange 版 aabbs_minmax_par 留作大规模逃生门, 见下方 spin 治理注)
"""
import functools
import sys
import threading

import numpy as np

# ---- numba 可选依赖探测 (装没装都能 import 本模块) --------------------------
# ★冻结环境 (Nuitka standalone) 定案 (2026-09-02 四连坑实测): numba 在 Nuitka
#   产物内根本不可用 —— 坑1 standalone 默认 numba-disable-jit=yes 全降级;
#   坑2 njit(cache=True) "no locator available"; 坑3 njit 本体对 Nuitka 编译
#   函数崩 "Compiled function bytecode used" (numba 要取 Python 字节码, Nuitka
#   C 编译产物没有); 坑4 连 fastpath.py 以真实源文件随包投放 (build4) 都在
#   llvmlite 初始化阶段死锁 (CPU 零增长). ⇒ 冻结环境**不 import numba**,
#   aabbs 走 numpy 批量快路径 (_aabbs_minmax_np, 见下方定义), 其余纯 Python
#   直译 (小 n 足够快). 编译版速度 = Nuitka C 编译 + numpy C 内核承担.
_FROZEN = getattr(sys, 'frozen', False) or '__compiled__' in globals()
_NUMBA = False
if not _FROZEN:
    try:
        from numba import njit, prange  # noqa: F401  (prange 是层3 nogil 并行钩子)
        _NUMBA = True
    except ImportError:
        _NUMBA = False


def _njit_or_py(**kw):
    """装饰器工厂: 装了 numba -> njit(**kw)(fn); 没装/冻结环境 -> 纯透传.

    - nogil=True 是层3 多线程的钩子: numba 路径下在编译代码里释放 GIL,
      可被层3 用线程池并行驱动; 纯 Python 降级时 nogil 无法生效 (解释器
      执行), 透传包装直接丢弃该参数, 没装 numba 也绝不报错.
    - cache=True: numba 编译产物落盘, 进程间复用 (省冷启动 JIT). 仅源码
      路径生效; 冻结环境根本不 import numba (见上方四连坑定案).
    - 降级路径用 functools.wraps 透传 (保留 __name__/__doc__/签名元数据),
      行为等价于原函数本体; 数值与 numba 路径同源, 仅速度差.
    """
    if _NUMBA:
        def deco(fn):
            return njit(**kw)(fn)
        return deco

    def deco(fn):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            return fn(*args, **kwargs)
        return wrapper
    return deco


# ---------------------------------------------------------------------------
# a) 深度 DP: 每节点沿 parent 数组爬到 -1 的深度
#    语义直译自 engine.compute_world_matrices 现循环:
#        d, cur = 0, i
#        while parent[cur] >= 0 and d < n:
#            cur, d = int(parent[cur]), d + 1
#        depth[i] = d
#    d < n 是防环截断 (环上节点 depth 取 n 上限值, 与 engine 版逐位一致).
# ---------------------------------------------------------------------------
def _depths_impl(parent):
    # 参数约定 (numba 路径强制): parent 为 np.int64 一维数组.
    n = parent.shape[0]
    depth = np.zeros(n, dtype=np.int64)
    for i in range(n):
        d = 0
        cur = i
        while parent[cur] >= 0 and d < n:
            cur = int(parent[cur])   # int() 转换后再当下标 (engine 版同款)
            d = d + 1
        depth[i] = d
    return depth


# ---------------------------------------------------------------------------
# b) ancestry DFS: 森林 DFS 序区间, a 是 b 祖先 ⟺ tin[a]<=tin[b]<tout[a]
#    语义逐位直译自 engine._ancestry_ranges (engine.py) 的 DFS 部分:
#      children 构建 (父的子列表=下标升序) / 根序=parent<0 的下标升序 /
#      栈式 DFS, tin 进栈时赋值(timer++), tout 出栈时赋值 /
#      环内已入栈不重入 / 兜底: 环/孤儿当独立根补全 (tin=timer, tout=timer+1).
#    children 的 list-of-list 用 CSR (start/child_arr) 表达——numba 对
#    嵌套 list 支持差, 且 CSR 填充顺序 (i 升序) 与 append 顺序完全一致.
# ---------------------------------------------------------------------------
def _ancestry_dfs_impl(parent):
    # 参数约定 (numba 路径强制): parent 为 np.int64 一维数组.
    n = parent.shape[0]
    # -- children CSR 构建: cnt[p]=父 p 的孩子数, start=前缀和 -------------
    cnt = np.zeros(n, dtype=np.int64)
    for i in range(n):
        p = parent[i]
        if p >= 0:
            cnt[p] += 1
    start = np.zeros(n + 1, dtype=np.int64)
    for p in range(n):
        start[p + 1] = start[p] + cnt[p]
    child_arr = np.zeros(start[n], dtype=np.int64)
    fill = start[:n].copy()
    for i in range(n):                    # i 升序 -> children 顺序=下标升序
        p = parent[i]
        if p >= 0:
            child_arr[fill[p]] = i
            fill[p] += 1
    # -- 栈式 DFS -----------------------------------------------------------
    # 栈用两个数组模拟 (节点, 子游标 k); 每节点至多入栈一次 (in_forest 拦),
    # 栈深 <= n, 开 n+1 冗余.
    tin = np.zeros(n, dtype=np.int64)
    tout = np.zeros(n, dtype=np.int64)
    timer = 0
    in_forest = np.zeros(n, dtype=np.int64)   # 0/1 标记 (numba 友好的 bool)
    snode = np.zeros(n + 1, dtype=np.int64)
    sk = np.zeros(n + 1, dtype=np.int64)
    sp = 0                                    # 栈顶指针 (栈大小=sp)
    for r in range(n):                        # 根序 = parent<0 下标升序
        if parent[r] < 0:
            if in_forest[r] == 1:
                continue
            in_forest[r] = 1
            snode[0] = r
            sk[0] = 0
            sp = 1
            while sp > 0:
                u = snode[sp - 1]
                k = sk[sp - 1]
                if k == 0:                    # 首次到栈顶: 记 tin
                    tin[u] = timer
                    timer += 1
                if k < cnt[u]:
                    v = child_arr[start[u] + k]
                    sk[sp - 1] = k + 1        # 先推进游标 (engine 版同款)
                    if in_forest[v] == 0:     # 环内已入栈不重入 (防御)
                        in_forest[v] = 1
                        snode[sp] = v
                        sk[sp] = 0
                        sp += 1
                else:                         # 子树走完: 记 tout 出栈
                    tout[u] = timer
                    sp -= 1
    # -- 兜底: 环/孤儿当独立根补全 (engine 版同款) ---------------------------
    for i in range(n):
        if in_forest[i] == 0:
            tin[i] = timer
            timer += 1
            tout[i] = timer
    return tin, tout


# ---------------------------------------------------------------------------
# d) 冻结环境 numpy 快路径 (numba 缺席时唯一 C 级内核, 2026-09-02 定案):
#    批量 matmul (n,V,4)@(n,4,3)->(n,V,3) 一次 C 调用 + min/max 归约.
#    数值 = numpy dgemm 路径, 与 numba 升序标量求和有 ~4 ULP 舍入差
#    (与旧 numpy 参考实现同源, D6 标准 "逐位/1e-7 内", 实测 8.9e-16 合格).
#    编译版里本函数被 Nuitka C 编译 —— 纯 numpy 调用无解释循环, aabbs 从
#    降级版的 452ms/帧 回到 ~ms 级 (v1 坑实锤: 纯 Python 逐顶点循环才是慢源).
#    np.matmul 批量维度天然释放 GIL 内核; par 版别名同实现 (冻结环境无
#    numba 线程池, 引擎 _AABB_PAR_MIN_MODELS 闸门切过来也无害).
def _aabbs_minmax_np(vh, m3, out_mn, out_mx):
    w = np.matmul(vh, m3)                     # (n,V,4)@(n,4,3) -> (n,V,3)
    np.min(w, axis=1, out=out_mn)
    np.max(w, axis=1, out=out_mx)
    return out_mn, out_mx

# ★matmul 输出缓冲复用 (2026-09-02, 50球冒烟 aabbs 10.46ms → 预期 ~1-2ms):
#   上面朴素版每帧 np.matmul 新分配 (n,V,3) 大缓冲 (500球=24.5MB) —— 每帧全新
#   页 = zero-fill page fault 风暴, 实测 aabbs 占 10.46ms/帧 (源码 numba 版 1.13ms).
#   改 threading.local 按 (n,V) 键预分配 out= 复用 (与 engine._aabb_staging 同款
#   线程局部免锁模式; 池 worker 各持一份). 数值不变 (同 dgemm, 只是落进复用缓冲).
_w_np = threading.local()


def _aabbs_minmax_np(vh, m3, out_mn, out_mx):
    n, V = vh.shape[0], vh.shape[1]
    cache = getattr(_w_np, 'bufs', None)
    if cache is None:
        cache = _w_np.bufs = {}
    w = cache.get((n, V))
    if w is None:
        w = cache[(n, V)] = np.empty((n, V, 3), dtype=np.float64)
    np.matmul(vh, m3, out=w)
    w.min(axis=1, out=out_mn)
    w.max(axis=1, out=out_mx)
    return out_mn, out_mx


# 公开入口: 装了 numba = @njit(nogil) 编译版; 没装/冻结 = 快路径分派 ——
#   aabbs 走 numpy 批量内核 (上方 d), 深度 DP/ancestry DFS 纯 Python 直译
#   (n=节点数, 500 物体 ~0.2ms 级, 不是热点).
depths = _njit_or_py(nogil=True)(_depths_impl)
ancestry_dfs = _njit_or_py(nogil=True)(_ancestry_dfs_impl)


# ---------------------------------------------------------------------------
# c) AABB 批量归约 (组3层3): 每模型 (V,4) 齐次顶点 @ (4,3) 矩阵切片 -> min/max.
#    语义 = get_bounding_box 的 w3t.min/max (纯比较无舍入) + matmul 段:
#    out[i, v, j] = Σ_k vh[v, k] * M3[k, j] 标量升序求和. 与 numpy dgemm 有
#    ~4 ULP (1e-16 级) 舍入差 (BLAS SIMD 分块求和顺序不可复现) —— 组3 D6
#    验收标准 "逐位/1e-7 内", 实测最大 8.9e-16 合格 (对拍 aabb_par_check.py).
#    nogil = 编译路径全程释放 GIL, 可被层3 用线程池并行驱动; 纯 Python 降级 =
#    同算法直译 (慢, 仅保证 numba 缺席时正确性).
#
# ★ spin-wait 治理 (2026-08-31, 用户实测 18 核满载却只 +20 帧):
#    aabbs_minmax 原为 parallel=True (prange 模型维并行). 实测 (numba_spin_probe.py):
#    51球×2035顶点每帧真实工作仅 ~54µs, 但 numba 线程池 (NUMBA_NUM_THREADS=18)
#    在每次 prange 后 worker 不睡眠、busy-wait 等活 —— 帧间隔 ~6.5ms 期间 18 线程
#    全程 100% 空烧 (60 次调用窗内 CPU 消耗 8969ms ≈ 21 核全程, 真实工作仅 3.2ms,
#    99.96% CPU 是无效负载). 根因: 该负载对 18 核是杯水车薪, 并行版 53.6µs vs
#    串行 njit ~104µs 差距可忽略, spin 税却是 18 核 x 全程.
#    ⇒ 帧路径默认走**串行 njit 版** (aabbs_minmax, nogil 但无 prange);
#      prange 并行版保留为 aabbs_minmax_par (逃生门): 仅当单次工作量足够大
#      (engine._AABB_PAR_MIN_MODELS 闸门, 摊得开 spin 税) 才切换. 引擎不设
#      环境变量, 闸门随代码走 (打包 exe 同行为).
# ---------------------------------------------------------------------------
def _aabbs_minmax_impl(vh, m3, out_mn, out_mx):
    # vh: (n, V, 4) f64 C 连续; m3: (n, 4, 3) f64; out_*: (n, 3) f64 (预清零/任意)
    n = vh.shape[0]
    V = vh.shape[1]
    for i in range(n):                    # 串行: 模型维普通循环 (无线程池接触)
        # 就地算每模型 min/max (不用额外 (n,3,V) 大缓冲)
        mn0 = mn1 = mn2 = 0.0
        mx0 = mx1 = mx2 = 0.0
        for v in range(V):
            x = vh[i, v, 0] * m3[i, 0, 0] + vh[i, v, 1] * m3[i, 1, 0] \
                + vh[i, v, 2] * m3[i, 2, 0] + vh[i, v, 3] * m3[i, 3, 0]
            y = vh[i, v, 0] * m3[i, 0, 1] + vh[i, v, 1] * m3[i, 1, 1] \
                + vh[i, v, 2] * m3[i, 2, 1] + vh[i, v, 3] * m3[i, 3, 1]
            z = vh[i, v, 0] * m3[i, 0, 2] + vh[i, v, 1] * m3[i, 1, 2] \
                + vh[i, v, 2] * m3[i, 2, 2] + vh[i, v, 3] * m3[i, 3, 2]
            if v == 0:
                mn0 = mx0 = x
                mn1 = mx1 = y
                mn2 = mx2 = z
            else:
                if x < mn0: mn0 = x
                elif x > mx0: mx0 = x
                if y < mn1: mn1 = y
                elif y > mx1: mx1 = y
                if z < mn2: mn2 = z
                elif z > mx2: mx2 = z
        out_mn[i, 0] = mn0
        out_mn[i, 1] = mn1
        out_mn[i, 2] = mn2
        out_mx[i, 0] = mx0
        out_mx[i, 1] = mx1
        out_mx[i, 2] = mx2
    return out_mn, out_mx


def _aabbs_minmax_par_impl(vh, m3, out_mn, out_mx):
    # 与串行版同算法, 仅模型维 prange 并行 (逃生门: 大规模才用, 见上 spin 治理注).
    n = vh.shape[0]
    V = vh.shape[1]
    for i in prange(n):
        mn0 = mn1 = mn2 = 0.0
        mx0 = mx1 = mx2 = 0.0
        for v in range(V):
            x = vh[i, v, 0] * m3[i, 0, 0] + vh[i, v, 1] * m3[i, 1, 0] \
                + vh[i, v, 2] * m3[i, 2, 0] + vh[i, v, 3] * m3[i, 3, 0]
            y = vh[i, v, 0] * m3[i, 0, 1] + vh[i, v, 1] * m3[i, 1, 1] \
                + vh[i, v, 2] * m3[i, 2, 1] + vh[i, v, 3] * m3[i, 3, 1]
            z = vh[i, v, 0] * m3[i, 0, 2] + vh[i, v, 1] * m3[i, 1, 2] \
                + vh[i, v, 2] * m3[i, 2, 2] + vh[i, v, 3] * m3[i, 3, 2]
            if v == 0:
                mn0 = mx0 = x
                mn1 = mx1 = y
                mn2 = mx2 = z
            else:
                if x < mn0: mn0 = x
                elif x > mx0: mx0 = x
                if y < mn1: mn1 = y
                elif y > mx1: mx1 = y
                if z < mn2: mn2 = z
                elif z > mx2: mx2 = z
        out_mn[i, 0] = mn0
        out_mn[i, 1] = mn1
        out_mn[i, 2] = mn2
        out_mx[i, 0] = mx0
        out_mx[i, 1] = mx1
        out_mx[i, 2] = mx2
    return out_mn, out_mx


# (公开入口统一移到文件末尾 numba 探测块: aabbs_minmax / aabbs_minmax_par /
#  depths / ancestry_dfs 按 _NUMBA 分派 —— numba 版或 numpy 批量快路径.)
if _NUMBA:
    # 帧路径默认 = 串行 njit (nogil 仍释放 GIL, 但无线程池无 spin);
    # 逃生门 = prange 并行版 (engine._aabbs_batched 按 _AABB_PAR_MIN_MODELS 闸门切换).
    aabbs_minmax = _njit_or_py(nogil=True)(_aabbs_minmax_impl)
    aabbs_minmax_par = _njit_or_py(nogil=True, parallel=True)(_aabbs_minmax_par_impl)
else:
    # numba 缺席/冻结环境: numpy 批量内核 (C 级, 无解释循环).
    aabbs_minmax = _aabbs_minmax_np
    aabbs_minmax_par = _aabbs_minmax_np
