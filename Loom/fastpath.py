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
import os
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
_FROZEN = (getattr(sys, 'frozen', False) or '__compiled__' in globals()
           or os.environ.get('LOOM_NO_NUMBA') == '1')   # 诊断: 源码模拟冻结降级
# ★B2 退役 (2026-10-16): numba 路径全部退役 (aabbs 已随 B1 删, depths/ancestry
# 随 B2 删)。_NUMBA 保留为 False 常量供诊断探针读取 (语义 = "生产不用 numba")。
_NUMBA = False

# ---- C 内核 DLL (2026-09-07): 源码/编译版同源同速, 绕开 numba×Nuitka 四连坑 --
# loom_kernels.dll 由 ckernels\build_ckernels.bat (MSVC /O2 /LD) 编出, ctypes
# 直调朴素 C ABI。aabbs 内核 f64 全程, 算法逐位直译 _aabbs_minmax_impl (标量
# 升序求和 + 纯比较) —— 与 numba f64 路径逐位一致, 与 numpy dgemm ~4 ULP
# (1e-16 级, D6 标准 1e-7 内)。B1 退役后: 加载失败 = 硬 raise (不再静默降级)。
# ★Nuitka 常量折叠双坑 (2026-09-07 第 8/9 次重编实测): ①模块级 if 分派被
#   静态折叠 ②函数体内 `if _CKERNELS is not None` 同样被折叠 (Nuitka 对
#   编译期=None 的模块全局做激进的常量传播, 运行时赋值不生效) → 编译版
#   aabbs 恒走 numpy。对策 = DLL 句柄存进 **dict** (容器内容Nuitka无法
#   折叠, 运行时键访问真实发生), 包装函数查 _CK['dll']。
_CK = {'dll': None, 'ctypes': None}
_CKERNELS = None      # engine 侧可见别名 (运行时属性访问不折叠; collide 用)
# B1 逃生门退役 (2026-10-16): ckernels 为官方组件, 硬加载; 加载失败 = 引擎缺陷,
# 模块级 raise (不为官方件兜底; 兜底责任在组件内部, 见 docs/design/逃生门退役设计.md)。
import ctypes as _ctypes
_CK['ctypes'] = _ctypes
_cands = [os.path.join(os.path.dirname(os.path.abspath(__file__)),
                       'ckernels', 'loom_kernels.dll')]
if getattr(sys, 'frozen', False) or '__compiled__' in globals():
    # 冻结环境: DLL 与 exe 同级投放 (assemble 脚本负责拷贝)
    _cands.insert(0, os.path.join(os.path.dirname(os.path.abspath(sys.executable)),
                                  'ckernels', 'loom_kernels.dll'))
_dll = None
for _p in _cands:
    if os.path.isfile(_p):
        _dll = _ctypes.CDLL(_p)
        # int loom_aabbs_minmax(const double*, const double*,
        #                       double*, double*, int64, int64)
        _dll.loom_aabbs_minmax.restype = _ctypes.c_int
        _dll.loom_aabbs_minmax.argtypes = [
            _ctypes.POINTER(_ctypes.c_double), _ctypes.POINTER(_ctypes.c_double),
            _ctypes.POINTER(_ctypes.c_double), _ctypes.POINTER(_ctypes.c_double),
            _ctypes.c_int64, _ctypes.c_int64]
        # int loom_aabbs_minmax_par(..., int64, int64, int)
        _dll.loom_aabbs_minmax_par.restype = _ctypes.c_int
        _dll.loom_aabbs_minmax_par.argtypes = [
            _ctypes.POINTER(_ctypes.c_double), _ctypes.POINTER(_ctypes.c_double),
            _ctypes.POINTER(_ctypes.c_double), _ctypes.POINTER(_ctypes.c_double),
            _ctypes.c_int64, _ctypes.c_int64, _ctypes.c_int]
        _CK['dll'] = _dll
        _CKERNELS = _dll
        break
if _dll is None:
    raise RuntimeError(
        'ckernels 官方组件加载失败: loom_kernels.dll 未找到, 尝试路径 %r'
        % (_cands,))

# C 内核并行线程数: 默认物理核数的一半 (AABB 单行工作量小, 满核易 spin 税;
# 0 = DLL 内部默认)。引擎 _AABB_PAR_MIN_MODELS 闸门仍决定是否走并行版。
_C_PAR_THREADS = max(1, (os.cpu_count() or 4) // 2)


# ★B2 退役 (2026-10-16): _njit_or_py 装饰器工厂已删 (numba 路径全退役)。


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


# ★P0-2 aabbs 冻结内核提速 (2026-09-02, 终版方案 B': 连续归约布局):
#   性能取证 (aabb_perf_probe2/3.py, 500球形态 n=500 V=2035 单线程):
#     - matmul 本体只占 ~9ms, **min/max axis=1 (中轴跨步) 归约占 77ms**
#       (跨步步长 12B, 641MB/s —— 内存布局才是真瓶颈, 不是 BLAS);
#     - f32 sgemm (原方案A) 只加速 matmul 小头, 全路径 81ms ≈ 无效;
#     - B' = matmul 落 (n,V,3) 复用缓冲 + 一次 transpose-copy 到 (n,3,V)
#       连续末轴 + min/max axis=2: 86→16.7ms (**5.2×**), f64 全程零数值风险
#       (min/max 纯比较无求和序 —— 与旧内核逐位一致, aabb_f32_check 实证).
#   einsum 'nvk,nkj->njv' 直达 (n,3,V) 为 31ms (转置段融合反慢于显式 copy),
#   故取 B'. 挂钩所有 numpy 降级路径 (冻结 exe + 无 numba 源码环境);
#   源码 numba 路径不变 (标量循环, 9.9ms 本来就快).
def _aabbs_minmax_np(vh, m3, out_mn, out_mx):
    n, V = vh.shape[0], vh.shape[1]
    cache = getattr(_w_np, 'bufs', None)
    if cache is None:
        cache = _w_np.bufs = {}
    ent = cache.get((n, V))
    if ent is None:
        ent = cache[(n, V)] = (
            np.empty((n, V, 3), dtype=np.float64),
            np.empty((n, 3, V), dtype=np.float64))
    w, wt = ent
    np.matmul(vh, m3, out=w)
    np.copyto(wt, w.transpose(0, 2, 1))     # (n,V,3)->(n,3,V) 末轴连续
    wt.min(axis=2, out=out_mn)
    wt.max(axis=2, out=out_mx)
    return out_mn, out_mx


# 公开入口: 装了 numba = @njit(nogil) 编译版; 没装/冻结 = 快路径分派 ——
#   aabbs 走 numpy 批量内核 (上方 d), 深度 DP/ancestry DFS 纯 Python 直译
#   (n=节点数, 500 物体 ~0.2ms 级, 不是热点).
# ★B2 退役 (2026-10-16): 删 numba/Python 兜底分派 (pipeline 官方件唯一路径)。
# _depths_impl / _ancestry_dfs_impl 保留为纯 Python 参考 (测试基准用, 不进生产)。
from pipeline_glue import depths, ancestry_dfs   # noqa: E402  (C 唯一路径)


# ---------------------------------------------------------------------------
# c) AABB 批量归约 (组3层3): 每模型 (V,4) 齐次顶点 @ (4,3) 矩阵切片 -> min/max.
# B1 退役后: 生产路径只走 ckernels.loom_aabbs_minmax[_par] 原生 C 内核;
#   numba 路径已删 (Q1 决策: 不留死代码). _aabbs_minmax_np 保留为**测试参考**
#   (aabb_f32_check.py 对拍基准), 不进生产分派.
# ---------------------------------------------------------------------------
# ---- C 内核包装 (ctypes 直调; 输入须 C 连续 f64 numpy 数组) -----------------
def _aabbs_minmax_c(vh, m3, out_mn, out_mx, par=False):
    _dll = _CK['dll']
    _ct = _CK['ctypes']
    n, V = vh.shape[0], vh.shape[1]
    _pd = _ct.POINTER(_ct.c_double)
    vh_p = vh.ctypes.data_as(_pd)
    m3_p = m3.ctypes.data_as(_pd)
    mn_p = out_mn.ctypes.data_as(_pd)
    mx_p = out_mx.ctypes.data_as(_pd)
    if par:
        rc = _dll.loom_aabbs_minmax_par(vh_p, m3_p, mn_p, mx_p,
                                        n, V, _C_PAR_THREADS)
    else:
        rc = _dll.loom_aabbs_minmax(vh_p, m3_p, mn_p, mx_p, n, V)
    if rc != 0:
        # B1 退役: 官方件不兜底; ctypes 侧已保证形参, rc!=0 是契约违约
        raise RuntimeError(
            'loom_aabbs_minmax%s 失败 rc=%d (形参不符?)'
            % ('_par' if par else '', rc))
    return out_mn, out_mx


# ★Nuitka 常量折叠坑 (2026-09-07 编译版实测, 第 8/9 次重编): 模块级 `if
#   _CKERNELS is not None:` 分派与函数体内同条件判断都被 Nuitka 静态折叠
#   (编译期 None → C 分支裁掉, 运行时 DLL 加载成功也走不进) → 编译版 aabbs
#   恒走 numpy 替身 (collide 无此问题因 engine 侧运行时属性访问)。修复 =
#   公开入口运行时查 **dict 键** _CK['dll'] (容器内容 Nuitka 无法折叠)。
# B1 退役: 公开入口直走 C (无 numba/numpy 兜底; DLL 缺席时模块级已 raise)。
# 保留 dict 键判断 (Nuitka 折叠防御, 见上方注释): 判断恒真, 但删掉会触发编译版裁枝。
def aabbs_minmax(vh, m3, out_mn, out_mx):
    if _CK['dll'] is not None:
        return _aabbs_minmax_c(vh, m3, out_mn, out_mx)
    return _aabbs_minmax_c(vh, m3, out_mn, out_mx)


def aabbs_minmax_par(vh, m3, out_mn, out_mx):
    if _CK['dll'] is not None:
        return _aabbs_minmax_c(vh, m3, out_mn, out_mx, par=True)
    return _aabbs_minmax_c(vh, m3, out_mn, out_mx, par=True)


# ---------------------------------------------------------------------------
# e) collide_pairs SAP 一体内核 (2026-09-07, 任务 collide_pairs 4.2→≤1.5ms):
#    engine._collision_pairs_parallel 的 C 路径候选段 (排序/窗口扫描/yz 过滤/
#    ancestry/精判/归一去重) 全部搬进 loom_kernels.dll 的 loom_collide_pairs
#    (取证 collide_prof.py: Python 相位合计 3.4ms/帧, 候选重过滤只 0.29ms,
#     解释器开销才是大头 -> 单次 C 调用收编全部相位).
#    语义红线: 输出 = (i<j, key 升序去重) 与 numpy 段位相同集合 (对拍闸门
#    collide_val_check.py 逐帧一致). 候选提取段留在 Python (向量化 2× 更快,
#    见 collide_prof2.py), 内核只吃纯数值数组.
#    B1 退役: 容量拒绝 (rc<0) 硬 raise, 不再回退 (ckernels 为官方组件, 不兜底).
#    ★Nuitka 折叠防御: argtypes 接线与函数体内句柄统一走 _CK['dll'] dict
#    (第 8/9 次重编实测模块级 if/函数体模块全局判断都会被静态折叠)。
if _CK['dll'] is not None:
    _dll_ck = _CK['dll']
    _ct_ck = _CK['ctypes']
    _dll_ck.loom_collide_pairs.restype = _ct_ck.c_int64
    _dll_ck.loom_collide_pairs.argtypes = [
        _ct_ck.POINTER(_ct_ck.c_double),        # cmn (K,3)
        _ct_ck.POINTER(_ct_ck.c_double),        # cmx (K,3)
        _ct_ck.POINTER(_ct_ck.c_int64),         # cand (K,)
        _ct_ck.POINTER(_ct_ck.c_int64),         # tin (n,)
        _ct_ck.POINTER(_ct_ck.c_int64),         # tout (n,)
        _ct_ck.POINTER(_ct_ck.c_double),        # bmn (n,3)
        _ct_ck.POINTER(_ct_ck.c_double),        # bmx (n,3)
        _ct_ck.POINTER(_ct_ck.c_double),        # scn (n,3)
        _ct_ck.POINTER(_ct_ck.c_double),        # rad (n,)
        _ct_ck.POINTER(_ct_ck.c_int64),         # kind (n,)
        _ct_ck.c_int64,                         # n (模型总数)
        _ct_ck.c_int64,                         # K (碰撞体数)
        _ct_ck.POINTER(_ct_ck.c_int64),         # out_pairs (2*cap) i64 对
        _ct_ck.c_int64,                         # cap_pairs (对容量)
        _ct_ck.POINTER(_ct_ck.c_int64),         # order_ws
        _ct_ck.POINTER(_ct_ck.c_int64),         # tmp_ws
        _ct_ck.POINTER(_ct_ck.c_int64),         # pi_ws
        _ct_ck.POINTER(_ct_ck.c_int64),         # pj_ws
        _ct_ck.c_int64]                         # ws_cap (工作区容量)

_collide_ws = threading.local()          # 工作区按容量复用 (grow-only, 免锁)


def _collide_pairs_c(cmn, cmx, cand, tin, tout, bmn, bmx, scn, rad, kind, n):
    """SAP 一体内核包装. 返回 (ai, bj) int64 数组 (key 升序, 与 numpy 段位同);
    内核不可用/容量拒绝 -> None (engine 回退 numpy 段).
    输入约定: 全部 C 连续 f64/int64, cand 长度 K>=2, tin/tout 长度 n."""
    K = cand.shape[0]
    if K < 2:
        return np.empty(0, dtype=np.int64), np.empty(0, dtype=np.int64)
    cap = K * (K - 1) // 2
    # ★ ws_cap 语义对齐 C 侧 (loom_kernels.c:248 `if (ws_cap < K) return -2`):
    #   C 的 ws_cap 要求覆盖 order/tmp (各 K 槽); 原代码误传 cap,
    #   K=2 时 cap=1 < K=2 → 合法小场景被误判"容量拒绝"回退 numpy.
    ws_cap = max(cap, K)
    ws = getattr(_collide_ws, 'bufs', None)
    if ws is None or ws[0] < ws_cap:
        ws = _collide_ws.bufs = (ws_cap,
                                 np.empty(2 * cap, dtype=np.int64),   # out_pairs
                                 np.empty(ws_cap, dtype=np.int64),    # order (>= K)
                                 np.empty(ws_cap, dtype=np.int64),    # tmp   (>= K)
                                 np.empty(cap, dtype=np.int64),       # pi    (>= cap)
                                 np.empty(cap, dtype=np.int64))       # pj
    _, out2, order, tmp, pi, pj = ws
    _dll = _CK['dll']
    _ct = _CK['ctypes']
    _pd = _ct.POINTER(_ct.c_double)
    _pi64 = _ct.POINTER(_ct.c_int64)
    npairs = _dll.loom_collide_pairs(
        cmn.ctypes.data_as(_pd), cmx.ctypes.data_as(_pd),
        cand.ctypes.data_as(_pi64), tin.ctypes.data_as(_pi64),
        tout.ctypes.data_as(_pi64),
        bmn.ctypes.data_as(_pd), bmx.ctypes.data_as(_pd),
        scn.ctypes.data_as(_pd), rad.ctypes.data_as(_pd),
        kind.ctypes.data_as(_pi64),
        int(n), int(K),
        out2.ctypes.data_as(_pi64), int(max(cap, K)),
        order.ctypes.data_as(_pi64), tmp.ctypes.data_as(_pi64),
        pi.ctypes.data_as(_pi64), pj.ctypes.data_as(_pi64),
        int(ws_cap))
    if npairs < 0:
        return None          # 容量/参数拒绝 -> 回退 numpy 段
    keys = out2[:npairs]                       # key = i*(n+1)+j (升序去重)
    return keys // (n + 1), keys % (n + 1)


def collide_extract(cand, aabb_rows, shapes, n):
    """候选碰撞体 SoA 提取 (2026-09-07, collide_prof2.py 取证 2× 快):
    flat-list 一次 append + np.array 单次转换 + 向量化派生, 产出 C 内核输入:
      返回 (cmn, cmx, bmn, bmx, scn, rad, kind, cand_arr) — 全部 C 连续:
        cmn/cmx (K,3) f64 粗筛盒 (sphere=[c-r,c+r]³ ⊇ 球, box=AABB — 与
          engine._collider_from_aabb 数值逐位同: 中心=中点, r=最大半长×0.5);
        bmn/bmx (K,3) 精确盒行 (refine 用, box=其 AABB);
        scn (K,3) 球心 / rad (K,) 球半径 / kind (K,) int64 0=box 1=sphere;
        cand_arr (K,) int64 模型下标.
    数值红线: 从同一 AABB (mn,mx) 点值出发的纯比较/乘 0.5/加法, 与旧逐对象
    Point3D 路径逐位一致 (对拍 collide_val_check.py 断言全等).
    aabb_rows 长度 != len(cand) 或形状异常 -> 全 None (engine 回退 numpy 段)."""
    K = len(cand)
    if K != len(aabb_rows) or K != len(shapes) or K < 2:
        return None, None, None, None, None, None, None, None
    flat = []
    ap = flat.append
    kinds_l = []
    kp = kinds_l.append
    for i, (mn, mx) in zip(cand, aabb_rows):
        ap(mn.x); ap(mn.y); ap(mn.z)
        ap(mx.x); ap(mx.y); ap(mx.z)
        kp(1 if shapes[len(kinds_l)] == 'sphere' else 0)
    try:
        a6 = np.array(flat, dtype=np.float64).reshape(K, 6)
    except (ValueError, TypeError):
        return None, None, None, None, None, None, None, None
    mn6 = np.ascontiguousarray(a6[:, 0:3])
    mx6 = np.ascontiguousarray(a6[:, 3:6])
    ext = mx6 - mn6
    cen = (mn6 + mx6) * 0.5
    r_all = np.maximum(np.maximum(ext[:, 0], ext[:, 1]), ext[:, 2]) * 0.5
    kind = np.array(kinds_l, dtype=np.int64)
    # 粗筛盒: sphere=[c-r,c+r]³ (旧 cmn/cmx 派生式), box=其 AABB
    cmn = np.where(kind[:, None] == 1, cen - r_all[:, None], mn6)
    cmx = np.where(kind[:, None] == 1, cen + r_all[:, None], mx6)
    # refine 数组 (碰撞体局部): box 行 = 精确 AABB; 球行 = 中心/半径
    bmn = np.where(kind[:, None] == 1, cen, mn6)
    bmx = np.where(kind[:, None] == 1, cen, mx6)
    scn = cen
    rad = r_all
    return (np.ascontiguousarray(cmn), np.ascontiguousarray(cmx),
            np.ascontiguousarray(bmn), np.ascontiguousarray(bmx),
            np.ascontiguousarray(scn), np.ascontiguousarray(rad),
            kind, np.asarray(cand, dtype=np.int64))


def collide_extract_local(ci, bmn, bmx, scn, rad, kind):
    """fw 直调路 (aabbs=None) 的 C 内核输入组装: 全局碰撞体数组已由调用方
    现算 (collider_bounds 路径), 这里只按候选下标切局部行 (fancy index 拷贝,
    数值与全局行逐位同 — 同一数组的子集切片). 输出与 collide_extract 同构."""
    if ci is None or len(ci) < 2:
        return None, None, None, None, None, None, None, None
    bmn_l = np.ascontiguousarray(bmn[ci])
    bmx_l = np.ascontiguousarray(bmx[ci])
    scn_l = np.ascontiguousarray(scn[ci])
    rad_l = np.ascontiguousarray(rad[ci])
    kind_l = np.ascontiguousarray(kind[ci])
    # 粗筛盒 = 旧派生式 (kind 行向量化 where)
    cmn = np.where(kind_l[:, None] == 1, scn_l - rad_l[:, None], bmn_l)
    cmx = np.where(kind_l[:, None] == 1, scn_l + rad_l[:, None], bmx_l)
    return (np.ascontiguousarray(cmn), np.ascontiguousarray(cmx),
            bmn_l, bmx_l, scn_l, rad_l, kind_l,
            np.asarray(ci, dtype=np.int64))
