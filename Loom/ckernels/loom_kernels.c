/* loom_kernels.c -- Loom engine C numeric kernels (2026-09-07)
 *
 * Goal: replace numba kernels with an independent C DLL (numba is unusable
 * inside Nuitka frozen builds, see fastpath.py header). Plain C ABI, ctypes.
 *
 * Kernel 1: loom_aabbs_minmax      -- serial (frame-path default, == numba njit)
 * Kernel 2: loom_aabbs_minmax_par  -- Win32-thread parallel (large-batch hatch)
 * Kernel 3: loom_collide_pairs     -- SAP window scan + yz + ancestry + overlap
 *                                     (2026-09-07 collide_pairs hot-section C port)
 *
 * Data layout (identical to engine._aabbs_batched staging buffers, all f64):
 *   vh:     (n, V, 4) C-contiguous -- V homogeneous vertices per model
 *   m3:     (n, 4, 3) C-contiguous -- world matrix slice M[:, :3] per model
 *   out_mn: (n, 3) C-contiguous -- per-model min(x,y,z)
 *   out_mx: (n, 3) C-contiguous -- per-model max(x,y,z)
 *
 * Numeric semantics = fastpath._aabbs_minmax_impl scalar transposition:
 *   x = vh0*m00 + vh1*m10 + vh2*m20 + vh3*m30   (k=4 ascending sum, no FMA)
 *   min/max pure comparison; v==0 row init (first vertex, bit-equal to numba).
 *   => bit-equal to numba f64 path; ~4 ULP vs numpy dgemm (1e-16 level,
 *      D6 standard 1e-7, verified by aabb cross-check probes).
 *
 * NOTE on parallelism: MSVC OpenMP frontend on this machine emits C3015 even
 * on textbook-minimal samples (toolchain issue, isolated 2026-09-07), so the
 * parallel kernel uses raw Win32 threads over contiguous row ranges -- no
 * OpenMP dependency at all. num_threads<=0/1 -> serial fallback.
 *
 * Build: /O2 /LD /MD   (no /fp:fast -- it would reorder the k=4 sum)
 */
#include <stdint.h>
#include <windows.h>

/* ---- core: one model row, bit-equal to fastpath._aabbs_minmax_impl ---- */
static void _aabb_one_row(const double *vh_row,   /* (V,4) */
                          const double *m3_row,   /* (4,3) */
                          double *mn, double *mx, /* (3,) */
                          int64_t V)
{
    double mn0 = 0.0, mn1 = 0.0, mn2 = 0.0;
    double mx0 = 0.0, mx1 = 0.0, mx2 = 0.0;
    const double *m = m3_row;            /* m[k*3+j] = m3[k][j] */
    double m00 = m[0], m01 = m[1], m02 = m[2];
    double m10 = m[3], m11 = m[4], m12 = m[5];
    double m20 = m[6], m21 = m[7], m22 = m[8];
    double m30 = m[9], m31 = m[10], m32 = m[11];

    for (int64_t v = 0; v < V; ++v) {
        const double *p = vh_row + v * 4;
        double a = p[0], b = p[1], c = p[2], d = p[3];
        double x = a * m00 + b * m10 + c * m20 + d * m30;
        double y = a * m01 + b * m11 + c * m21 + d * m31;
        double z = a * m02 + b * m12 + c * m22 + d * m32;
        if (v == 0) {
            mn0 = mx0 = x;
            mn1 = mx1 = y;
            mn2 = mx2 = z;
        } else {
            if (x < mn0) mn0 = x; else if (x > mx0) mx0 = x;
            if (y < mn1) mn1 = y; else if (y > mx1) mx1 = y;
            if (z < mn2) mn2 = z; else if (z > mx2) mx2 = z;
        }
    }
    mn[0] = mn0; mn[1] = mn1; mn[2] = mn2;
    mx[0] = mx0; mx[1] = mx1; mx[2] = mx2;
}

/* ---- kernel 1: serial ---- */
__declspec(dllexport) int loom_aabbs_minmax(const double *vh, const double *m3,
                                            double *out_mn, double *out_mx,
                                            int64_t n, int64_t V)
{
    if (n < 0 || V < 0) return 1;
    if (n == 0 || V == 0) return 0;
    for (int64_t i = 0; i < n; ++i) {
        _aabb_one_row(vh + i * V * 4, m3 + i * 12,
                      out_mn + i * 3, out_mx + i * 3, V);
    }
    return 0;
}

/* ---- kernel 2: Win32-thread parallel over contiguous row ranges ---- */
typedef struct {
    const double *vh, *m3;
    double *out_mn, *out_mx;
    int64_t V, row0, row1;               /* [row0, row1) */
} _aabb_range;

static DWORD WINAPI _aabb_worker(LPVOID arg)
{
    _aabb_range *r = (_aabb_range *)arg;
    const double *vh = r->vh, *m3 = r->m3;
    double *mn = r->out_mn, *mx = r->out_mx;
    int64_t V = r->V;
    for (int64_t i = r->row0; i < r->row1; ++i) {
        _aabb_one_row(vh + i * V * 4, m3 + i * 12, mn + i * 3, mx + i * 3, V);
    }
    return 0;
}

__declspec(dllexport) int loom_aabbs_minmax_par(const double *vh, const double *m3,
                                                double *out_mn, double *out_mx,
                                                int64_t n, int64_t V, int num_threads)
{
    if (n < 0 || V < 0) return 1;
    if (n == 0 || V == 0) return 0;
    if (num_threads <= 1 || n < 4)       /* tiny batch: threads cost more */
        return loom_aabbs_minmax(vh, m3, out_mn, out_mx, n, V);
    {
        int nt = num_threads > 64 ? 64 : num_threads;
        if ((int64_t)nt > n) nt = (int)n;
        {
            _aabb_range ranges[64];
            HANDLE th[64];
            int64_t chunk = n / nt, rem = n % nt, row = 0;
            int started = 0;
            for (int t = 0; t < nt; ++t) {
                int64_t cnt = chunk + (t < rem ? 1 : 0);
                ranges[t].vh = vh; ranges[t].m3 = m3;
                ranges[t].out_mn = out_mn; ranges[t].out_mx = out_mx;
                ranges[t].V = V; ranges[t].row0 = row; ranges[t].row1 = row + cnt;
                row += cnt;
                th[t] = CreateThread(NULL, 0, _aabb_worker, &ranges[t], 0, NULL);
                if (th[t]) started++;
                else {                  /* fall back to inline work on failure */
                    _aabb_worker(&ranges[t]);
                }
            }
            WaitForMultipleObjects(started, th, TRUE, INFINITE);
            for (int t = 0; t < started; ++t) CloseHandle(th[t]);
        }
    }
    return 0;
}

/* ==========================================================================
 * Kernel 3: loom_collide_pairs (2026-09-07)
 *
 * Bit-exact C port of engine._collision_pairs_parallel SAP pipeline (C path),
 * evidence-driven (tests/_tmp/collide_prof.py + collide_prof2.py):
 *   - candidate SoA extraction moves to Python side (vectorized, 2x faster
 *     than per-object loop); kernel consumes pure numeric arrays only.
 *   - Python side block-scan + per-pair ancestry etc (3.4ms total) is all
 *     interpreter overhead -> collapsed into this single C call.
 *
 * Inputs (all C-contiguous, caller-owned):
 *   cmn/cmx : (K,3) f64  -- coarse AABBs of the K colliders (subset order)
 *   bmn/bmx : (K,3) f64  -- exact AABB rows (refine: box-box / box-sphere)
 *   scn     : (K,3) f64  -- sphere centers (refine)
 *   rad     : (K,)  f64  -- sphere radii (refine)
 *   kind    : (K,)  i64  -- 0=box 1=sphere (collider-local)
 *   cand    : (K,)  i64  -- model index per collider (cand[u])
 *   tin/tout: (n,)  i64  -- DFS ancestry intervals over all models (global)
 *   n       : model count (for i<j normalize), K: collider count
 *   (2026-09-07 rev2: refine arrays are collider-local (K) -- the global
 *    per-model arrays made the Python side build (n,3) buffers + scatter,
 *    defeating the point. Local rows are bit-identical: box rows = exact
 *    AABB, sphere center/radius = AABB midpoint / max half-length.)
 *
 * Algorithm (== python block-scan semantics, bit-exact):
 *   1. order = argsort(cmn[:,0], stable)  (iterative merge sort, tie=original)
 *   2. for each t: u-window = (t, lo) where lo = lower_bound(xmns, cmx[kt,0])
 *      (strict window: pairs with cmx_t == xmn_u excluded, == refine test)
 *   3. per u: y/z interval test (strict <)  -> candidate pair
 *   4. ancestry: NOT((tin[a]<=tin[b]<tout[a]) OR swapped) keeps pair
 *   5. refine _pair_overlap_vec semantics on the ORIGINAL bmn/bmx/scn/rad/kind
 *      arrays indexed by model index (box/box, sphere/sphere, mixed)
 *   6. normalize (min,max), dedup by key = a*(n+1)+b, ascending sort (unique)
 *
 * Output buffer: cap_pairs >= K*(K-1)/2 safe upper bound; returns the number
 * of final pairs written as int64. Never writes beyond cap_pairs (returns -1
 * if capacity would be exceeded, caller falls back to numpy path).
 * ========================================================================== */
typedef struct {
    const double *cmn, *cmx;             /* (K,3) */
    const int64_t *cand;                 /* (K,) */
    int64_t K, n;
    int64_t *order;                      /* workspace (K) */
    /* candidate pair accumulation (pre-refine), grown geometrically */
    int64_t *pi, *pj;
    int64_t cnt, cap;
    int overflow;
} _collide_ws;

static void _collide_push(_collide_ws *w, int64_t a, int64_t b)
{
    if (w->cnt >= w->cap) { w->overflow = 1; return; }
    w->pi[w->cnt] = a;
    w->pj[w->cnt] = b;
    w->cnt++;
}

/* iterative merge sort (stable) of 0..K-1 by key=cmn[v*3] ascending */
static void _collide_argsort_x(const double *cmn, int64_t K, int64_t *order,
                               int64_t *tmp)
{
    for (int64_t i = 0; i < K; ++i) order[i] = i;
    if (K < 2) return;
    for (int64_t width = 1; width < K; width <<= 1) {
        for (int64_t lo = 0; lo < K; lo += width << 1) {
            int64_t mid = lo + width; if (mid > K) mid = K;
            int64_t hi = lo + (width << 1); if (hi > K) hi = K;
            int64_t l = lo, r = mid, o = lo;
            while (l < mid && r < hi) {
                if (cmn[order[r] * 3] < cmn[order[l] * 3])
                    tmp[o++] = order[r++];       /* strict: right only on < */
                else
                    tmp[o++] = order[l++];       /* tie keeps left = stable */
            }
            while (l < mid) tmp[o++] = order[l++];
            while (r < hi)  tmp[o++] = order[r++];
        }
        for (int64_t i = 0; i < K; ++i) order[i] = tmp[i];
    }
}

/* lower_bound: first index s in the x-sorted sequence with
   cmn[order[s]*3] >= v  (i.e. count of entries with xmn strictly < v) */
static int64_t _collide_lower_bound(const double *cmn, const int64_t *order,
                                    int64_t K, double v)
{
    int64_t lo = 0, hi = K;
    while (lo < hi) {
        int64_t mid = lo + ((hi - lo) >> 1);
        if (cmn[order[mid] * 3] < v) lo = mid + 1;
        else hi = mid;
    }
    return lo;
}

static int _collide_cmp_i64(const void *a, const void *b)
{
    int64_t x = *(const int64_t *)a, y = *(const int64_t *)b;
    return (x > y) - (x < y);
}

__declspec(dllexport) int64_t loom_collide_pairs(
    const double *cmn, const double *cmx, const int64_t *cand,
    const int64_t *tin, const int64_t *tout,
    const double *bmn, const double *bmx,
    const double *scn, const double *rad, const int64_t *kind,
    int64_t n, int64_t K,
    int64_t *out_pairs, int64_t cap_pairs,
    int64_t *order_ws, int64_t *tmp_ws, int64_t *pi_ws, int64_t *pj_ws,
    int64_t ws_cap)
{
    if (K < 0 || n < 0) return -2;
    if (K < 2) return 0;
    if (ws_cap < K) return -2;
    int64_t need = (K * (K - 1)) / 2;
    if (cap_pairs < K || ws_cap < need) return -1;

    _collide_ws w;
    w.cmn = cmn; w.cmx = cmx; w.cand = cand; w.K = K; w.n = n;
    w.order = order_ws;
    w.pi = pi_ws; w.pj = pj_ws;
    w.cnt = 0; w.cap = need; w.overflow = 0;

    _collide_argsort_x(cmn, K, order_ws, tmp_ws);
    const int64_t *order = order_ws;

    /* ---- x-window scan (strict, == refine semantics) + yz filter ---- */
    for (int64_t t = 0; t < K; ++t) {
        int64_t kt = order[t];
        double xmn_t = cmn[kt * 3];
        double ymn_t = cmn[kt * 3 + 1], zmn_t = cmn[kt * 3 + 2];
        double xmx_t = cmx[kt * 3], ymx_t = cmx[kt * 3 + 1],
               zmx_t = cmx[kt * 3 + 2];
        int64_t lo = _collide_lower_bound(cmn, order, K, xmx_t);
        for (int64_t s = t + 1; s < lo; ++s) {
            int64_t ku = order[s];
            if (ymn_t < cmx[ku * 3 + 1] && cmn[ku * 3 + 1] < ymx_t &&
                zmn_t < cmx[ku * 3 + 2] && cmn[ku * 3 + 2] < zmx_t) {
                _collide_push(&w, kt, ku);
                if (w.overflow) return -1;
            }
        }
    }

    /* ---- ancestry + refine + normalize + dedup ---- */
    /* dedup buffer reuses out_pairs as key array (keys <= cap_pairs entries) */
    int64_t *keys = out_pairs;
    int64_t nkeys = 0;
    for (int64_t p = 0; p < w.cnt; ++p) {
        int64_t t2 = w.pi[p], u2 = w.pj[p];            /* collider-local */
        int64_t i = cand[t2], j = cand[u2];            /* model indices */
        if (i > j) { int64_t t3 = i; i = j; j = t3; }
        /* collider-local rows for model i and j: cand is injective, so the
           row of model i is whichever of t2/u2 has cand == i */
        int64_t ri = (cand[t2] == i) ? t2 : u2;
        int64_t rj = (cand[t2] == j) ? t2 : u2;
        if ((tin[i] <= tin[j] && tin[j] < tout[i]) ||
            (tin[j] <= tin[i] && tin[i] < tout[j]))
            continue;                                  /* related: skip */
        int64_t ki = kind[ri], kj = kind[rj];
        int hit;
        if (ki == 0 && kj == 0) {
            hit = (bmn[ri * 3]     < bmx[rj * 3]     && bmn[rj * 3]     < bmx[ri * 3]     &&
                   bmn[ri * 3 + 1] < bmx[rj * 3 + 1] && bmn[rj * 3 + 1] < bmx[ri * 3 + 1] &&
                   bmn[ri * 3 + 2] < bmx[rj * 3 + 2] && bmn[rj * 3 + 2] < bmx[ri * 3 + 2]);
        } else if (ki == 1 && kj == 1) {
            double dx = scn[ri * 3] - scn[rj * 3];
            double dy = scn[ri * 3 + 1] - scn[rj * 3 + 1];
            double dz = scn[ri * 3 + 2] - scn[rj * 3 + 2];
            double rr = rad[ri] + rad[rj];
            hit = dx * dx + dy * dy + dz * dz < rr * rr;
        } else {
            int64_t sidx = (ki == 1) ? ri : rj;        /* collider-local */
            int64_t bidx = (ki == 1) ? rj : ri;
            double cxv = scn[sidx * 3];
            double cyv = scn[sidx * 3 + 1];
            double czv = scn[sidx * 3 + 2];
            double lx = bmn[bidx * 3], hx = bmx[bidx * 3];
            double ly = bmn[bidx * 3 + 1], hy = bmx[bidx * 3 + 1];
            double lz = bmn[bidx * 3 + 2], hz = bmx[bidx * 3 + 2];
            cxv = cxv < lx ? lx : (cxv > hx ? hx : cxv);
            cyv = cyv < ly ? ly : (cyv > hy ? hy : cyv);
            czv = czv < lz ? lz : (czv > hz ? hz : czv);
            double dx = scn[sidx * 3] - cxv;
            double dy = scn[sidx * 3 + 1] - cyv;
            double dz = scn[sidx * 3 + 2] - czv;
            double r = rad[sidx];
            hit = dx * dx + dy * dy + dz * dz < r * r;
        }
        if (!hit) continue;
        keys[nkeys++] = i * (n + 1) + j;
    }
    /* sort ascending + compact adjacent duplicates (O(P log P), no quadratic
       dedup; scan above emits each unordered collider pair at most once, so
       compacting is defensive only) */
    qsort(keys, (size_t)nkeys, sizeof(int64_t), _collide_cmp_i64);
    int64_t w2 = 0;
    for (int64_t q = 0; q < nkeys; ++q) {
        if (w2 == 0 || keys[w2 - 1] != keys[q]) keys[w2++] = keys[q];
    }
    return w2;
}

/* ==========================================================================
 * M1-4 契约化无侵入追加 (2026-09-08, DLL 化战役 M1)
 * ==========================================================================
 * 本段为向文件末尾"无侵入追加"的 loom_module.h v1.0 契约导出 (最小函数集
 * 7 个), 追加后既有三内核 (loom_aabbs_minmax / loom_aabbs_minmax_par /
 * loom_collide_pairs) 的签名/语义/求和序一概不动, fastpath.py 的 ctypes
 * 直调链不受任何影响 (导出表只增不改, 原符号地址不变)。
 * 本 DLL 因此持有契约 7 导出, 成为注册表 (registry.json) 的合法公民, 可被
 * module_loader.py 按 M1 契约流程 LoadLibrary → 验 7 导出 → 校验 magic/abi
 * → 读 provides/depends → init 正常加载。
 * 写法逐一对齐 core_components\loom_module_ref.c (契约参考实现范本);
 * C 风格守约: 声明在块顶 (C89 形态) / uint32_t 入参 / 返回值与契约
 * typedef (loom_module_info_fn 等 6 个) 严格一致。
 * ========================================================================== */
#include "../core_components/loom_module.h"   /* 引号相对 include: MSVC 按含入文件所在目录解析 */
#include <string.h>                          /* strcmp (loom_module_has 用) */

/* ---- 静态模块信息 (进程生命期有效; 不返回栈指针) -------------------------- */
static const LOOM_MODULE_INFO g_module_info = {
    LOOM_MODULE_MAGIC,
    LOOM_ABI_VERSION_CURRENT,
    "ckernels",            /* 模块 id: 与 registry.json 条目 module_id 同名 */
    "1.0.0",
    1,                     /* official: 1=官方组件 (随引擎发行, 不走用户信任闸) */
    2,                     /* provides_count: ckernels.aabbs + ckernels.collide */
    0,                     /* depends_count: 数值内核无依赖 */
    0                      /* reserved: 置 0 */
};

static const char *g_module_provides[] = { "ckernels.aabbs", "ckernels.collide" };

/* ---- 契约导出 1) 模块信息: 返回静态存储指针 ------------------------------- */
__declspec(dllexport) const LOOM_MODULE_INFO *loom_module_info(void)
{
    return &g_module_info;
}

/* ---- 契约导出 2) 枚举 provides: 越界返回 NULL ----------------------------- */
__declspec(dllexport) const char *loom_module_provide(uint32_t index)
{
    if (index >= g_module_info.provides_count) return NULL;
    return g_module_provides[index];
}

/* ---- 契约导出 3) 枚举 depends: 本模块无依赖, 越界/任意入参均返 NULL ------- */
__declspec(dllexport) const char *loom_module_depend(uint32_t index)
{
    (void)index;
    return NULL;           /* depends_count = 0 */
}

/* ---- 契约导出 4) 资源建立: 返 LOOM_OK (数值内核无设备资源, init 可重入) --- */
__declspec(dllexport) int32_t loom_module_init(void)
{
    return LOOM_OK;
}

/* ---- 契约导出 5) 资源释放: 空 (无资源可释放, 热重载零迁移) ---------------- */
__declspec(dllexport) void loom_module_deinit(void)
{
}

/* ---- 契约导出 6) ABI 版本快捷查询 ------------------------------------------ */
__declspec(dllexport) uint32_t loom_module_abi(void)
{
    return LOOM_ABI_VERSION_CURRENT;
}

/* ---- 契约导出 7) 能力查询: 对两个接口名 strcmp, NULL 入参返 0 -------------- */
__declspec(dllexport) int32_t loom_module_has(const char *iface_name)
{
    if (iface_name == NULL) return 0;
    if (strcmp(iface_name, "ckernels.aabbs")   == 0) return 1;
    if (strcmp(iface_name, "ckernels.collide") == 0) return 1;
    return 0;
}
