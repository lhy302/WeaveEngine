/* ============================================================================
 * loom_pipeline.c — 逻辑帧 prep 链 C 实现 (M2a, 2026-09-08)
 * ============================================================================
 * 组件: pipeline.dll (module_id="pipeline", official=1)
 * 契约: ../core_components/loom_module.h (通用) + ../core_components/loom_pipeline.h
 * 施工依据: D:\my-project\M2设计文档_pipeline_20260908.txt §3/§4
 *
 * ★数值纪律: 本文件所有浮点运算复刻 engine.py / matlib.py 现行实现的运算序,
 *   全部 f64, 禁 /fp:fast。逐位对拍 (tests\_tmp\pipeline_val_check.py) 是唯一
 *   验收口径 —— 任何改动必须重跑该探针。
 *
 * 本阶段实现:
 *   ① loom_pipeline_scene_bounds   ← engine._scene_light_bounds_par (2720)
 *   ② loom_pipeline_light_vps      ← engine._dir_light_vp (2775) /
 *                                     _point_light_vp (2902) / _compute_light_vps (2863)
 *   ③ loom_pipeline_aabbs          ← ckernels._aabb_one_row 同序副本
 *   ④ loom_pipeline_shadow_prep    ← ①②的便捷组合
 * ========================================================================== */
// @jev-block:imports:begin
#include "../core_components/loom_module.h"
#include "../core_components/loom_pipeline.h"
#include <math.h>
#include <stdlib.h>
#include <string.h>
// @jev-block:imports:end

/* ---- 行主序 4x4 小工具 (与 matlib.py 逐位同序) ---------------------------- */

/* 行主序存 m[row*4+col]; 结果 = a @ b (与 numpy a @ b 同序: 逐 k 升序求和) */
static void mat4_mul(const double *a, const double *b, double *out)
{
    int i, j, k;
    for (i = 0; i < 4; ++i) {
        for (j = 0; j < 4; ++j) {
            double s = 0.0;
            for (k = 0; k < 4; ++k) s += a[i * 4 + k] * b[k * 4 + j];
            out[i * 4 + j] = s;
        }
    }
}

/* 对拍用: 暴露本文件所用的同序 4x4 乘法 (探针用它验证与 numpy @ 的 1 ULP 界) */
__declspec(dllexport) void loom_pipeline_mat4_mul_ref(const double *a,
                                                      const double *b,
                                                      double *out)
{
    mat4_mul(a, b, out);
}

/* matlib.mat4_ortho (199): 行主序, clip.z 映射 [near->0, far->1] */
static void mat4_ortho(double left, double right, double bottom, double top,
                       double near, double far, double *m)
{
    memset(m, 0, sizeof(double) * 16);
    m[0]  = 2.0 / (right - left);
    m[5]  = 2.0 / (top - bottom);
    m[10] = 1.0 / (far - near);
    m[12] = -(right + left) / (right - left);
    m[13] = -(top + bottom) / (top - bottom);
    m[14] = -near / (far - near);
    m[15] = 1.0;
}

/* matlib.mat4_perspective (99): 行主序, fov_y 弧度, clip.z 映射 [near->0, far->1] */
static void mat4_perspective(double fov_y, double aspect, double near, double far,
                             double *m)
{
    double f = 1.0 / tan(fov_y * 0.5);
    memset(m, 0, sizeof(double) * 16);
    m[0]  = f / aspect;
    m[5]  = f;
    m[10] = far / (far - near);
    m[11] = 1.0;
    m[14] = -near * far / (far - near);
}

/* matlib.mat4_view_forward (212): 沿 forward 观察, +z_view = forward, det=+1 */
static int mat4_view_forward(const double *eye, const double *forward,
                             const double *up, double *m)
{
    double fx = forward[0], fy = forward[1], fz = forward[2];
    double ux = up[0], uy = up[1], uz = up[2];
    double fl, rx, ry, rz, rl, px, py, pz;
    fl = sqrt(fx * fx + fy * fy + fz * fz);
    if (fl < 1e-300) return 0;
    fx /= fl; fy /= fl; fz /= fl;
    rx = fy * uz - fz * uy;              /* right = forward × up */
    ry = fz * ux - fx * uz;
    rz = fx * uy - fy * ux;
    rl = sqrt(rx * rx + ry * ry + rz * rz);
    if (rl < 1e-300) rl = 1.0;
    rx /= rl; ry /= rl; rz /= rl;
    px = fy * rz - fz * ry;              /* up' = forward × right */
    py = fz * rx - fx * rz;
    pz = fx * ry - fy * rx;
    memset(m, 0, sizeof(double) * 16);
    m[0] = rx;  m[1] = px;  m[2] = fx;
    m[4] = ry;  m[5] = py;  m[6] = fy;
    m[8] = rz;  m[9] = pz;  m[10] = fz;
    m[12] = -(rx * eye[0] + ry * eye[1] + rz * eye[2]);
    m[13] = -(px * eye[0] + py * eye[1] + pz * eye[2]);
    m[14] = -(fx * eye[0] + fy * eye[1] + fz * eye[2]);
    m[15] = 1.0;
    return 1;
}

/* ---------------------------------------------------------------------------
 * ② 场景光照包围盒 — 逐位对齐 engine._scene_light_bounds_par (2720)
 * 角点序 (与 numpy tile/repeat 展开逐位一致, Python 注释明写):
 *   (ax,ay,az)(bx,ay,az)(ax,by,az)(bx,by,az)(ax,ay,bz)(bx,ay,bz)(ax,by,bz)(bx,by,bz)
 * 变换后 w = view @ corner (行主序: w[j] = Σ_k view[j*4+k]*c[k]), 取 min/max。
 * ------------------------------------------------------------------------- */
__declspec(dllexport) int32_t loom_pipeline_scene_bounds(const double *view_4x4,
                                   const double *aabb_rows, int64_t n,
                                   double *out_mn, double *out_mx)
{
    int64_t i;
    int c;
    double mn0 = 0.0, mn1 = 0.0, mn2 = 0.0;
    double mx0 = 0.0, mx1 = 0.0, mx2 = 0.0;
    int first = 1;

    if (view_4x4 == NULL || aabb_rows == NULL || out_mn == NULL || out_mx == NULL)
        return LOOM_ERR_PARAM;
    if (n <= 0)
        return LOOM_ERR_PARAM;           /* Python: `if not aabbs: return None` */

    for (i = 0; i < n; ++i) {
        const double *row = aabb_rows + i * LOOM_PIPE_AABB_STRIDE;
        double ax = row[0], ay = row[1], az = row[2];
        double bx = row[3], by = row[4], bz = row[5];
        for (c = 0; c < 8; ++c) {
            double cx = (c & 1) ? bx : ax;
            double cy = (c & 2) ? by : ay;
            double cz = (c & 4) ? bz : az;
            /* w = view @ corner, 行主序: w[j] = Σ_k view[j*4+k]*c[k] (k 升序) */
            double w0 = view_4x4[0] * cx + view_4x4[4] * cy
                      + view_4x4[8] * cz + view_4x4[12];
            double w1 = view_4x4[1] * cx + view_4x4[5] * cy
                      + view_4x4[9] * cz + view_4x4[13];
            double w2 = view_4x4[2] * cx + view_4x4[6] * cy
                      + view_4x4[10] * cz + view_4x4[14];
            if (first) {
                mn0 = mx0 = w0;
                mn1 = mx1 = w1;
                mn2 = mx2 = w2;
                first = 0;
            } else {
                if (w0 < mn0) mn0 = w0; else if (w0 > mx0) mx0 = w0;
                if (w1 < mn1) mn1 = w1; else if (w1 > mx1) mx1 = w1;
                if (w2 < mn2) mn2 = w2; else if (w2 > mx2) mx2 = w2;
            }
        }
    }
    out_mn[0] = mn0; out_mn[1] = mn1; out_mn[2] = mn2;
    out_mx[0] = mx0; out_mx[1] = mx1; out_mx[2] = mx2;
    return LOOM_OK;
}

/* ---------------------------------------------------------------------------
 * ① 光源 VP 批量 — 逐位对齐 engine._dir_light_vp / _point_light_vp
 * ------------------------------------------------------------------------- */
#define PIPE_POINT_FAR 1.0e4            /* engine._shadow_point_far 默认值 */

static int32_t one_dir_light_vp(const LOOM_LIGHT *L,
                                const double *rows, int64_t n,
                                const int32_t *vis_idx, int64_t n_vis,
                                double *out4)
{
    double D[3], eye[3], up[3], view[16], ortho[16], tmp[16];
    double ln;
    double mn[3], mx[3];
    double left, right, bottom, top, near, far;
    double pad, s;
    int32_t rc;

    D[0] = L->direction[0]; D[1] = L->direction[1]; D[2] = L->direction[2];
    ln = sqrt(D[0] * D[0] + D[1] * D[1] + D[2] * D[2]);
    if (ln < 1e-6) return LOOM_ERR_UNSUPPORTED;      /* Python: return None */
    D[0] /= ln; D[1] /= ln; D[2] /= ln;
    eye[0] = L->position[0]; eye[1] = L->position[1]; eye[2] = L->position[2];
    up[0] = L->up[0]; up[1] = L->up[1]; up[2] = L->up[2];
    if (!mat4_view_forward(eye, D, up, view)) return LOOM_ERR_UNSUPPORTED;

    /* 可见行过滤后的子表: 逐位等价 Python 侧 vis_aabbs = [aabbs[i] for i in vis_idx]
     * ★越界下标 = 调用方参数错误 → 返回 LOOM_ERR_PARAM(-2) 作为"硬错误"标记,
     *   由 loom_pipeline_light_vps 置 out_kind=-1 后原样返回 rc 如实上抛
     *   (不吞成 rc=LOOM_OK / out_kind=-1; D5 修复)。 */
    if (vis_idx != NULL && n_vis > 0) {
        int64_t k;
        double *sub = (double *)malloc((size_t)n_vis * LOOM_PIPE_AABB_STRIDE
                                       * sizeof(double));
        if (sub == NULL) return LOOM_ERR_INTERNAL;
        for (k = 0; k < n_vis; ++k) {
            int32_t si = vis_idx[k];
            if (si < 0 || (int64_t)si >= n) { free(sub); return LOOM_ERR_PARAM; }
            memcpy(sub + k * LOOM_PIPE_AABB_STRIDE,
                   rows + (int64_t)si * LOOM_PIPE_AABB_STRIDE,
                   sizeof(double) * LOOM_PIPE_AABB_STRIDE);
        }
        rc = loom_pipeline_scene_bounds(view, sub, n_vis, mn, mx);
        free(sub);
    } else {
        rc = loom_pipeline_scene_bounds(view, rows, n, mn, mx);
    }
    if (rc != LOOM_OK) return rc;        /* Python: bounds None → return None */

    if (L->mode == LOOM_LIGHT_MODE_BEAM) {
        s = L->size > 0.01 ? L->size : 0.01;
        left = -s; right = s; bottom = -s; top = s;
        near = 0.0;
        far = mx[2] + 2.0; if (far < 1.0) far = 1.0;
    } else {
        pad = 1.5;
        left = mn[0] - pad; right = mx[0] + pad;
        bottom = mn[1] - pad; top = mx[1] + pad;
        near = mn[2] - 2.0; if (near > 0.0) near = 0.0;
        far = mx[2] + 2.0; if (far < 1.0) far = 1.0;
    }
    mat4_ortho(left, right, bottom, top, near, far, ortho);
    mat4_mul(view, ortho, tmp);          /* Python: view @ mat4_ortho(...) */
    memcpy(out4, tmp, sizeof(double) * 16);
    return LOOM_OK;
}

static int32_t one_point_light_vp(const LOOM_LIGHT *L, double *out6x16)
{
    static const double AXES[6][3] = {
        { 1, 0, 0}, {-1, 0, 0}, {0, 1, 0}, {0, -1, 0}, {0, 0, 1}, {0, 0, -1}
    };
    static const double UPS[6][3] = {
        {0, 1, 0}, {0, 1, 0}, {0, 0, 1}, {0, 0, 1}, {0, 1, 0}, {0, 1, 0}
    };
    double eye[3], proj[16], view[16], tmp[16];
    int f;
    eye[0] = L->position[0]; eye[1] = L->position[1]; eye[2] = L->position[2];
    /* matlib.mat4_perspective(radians(90), 1.0, 0.05, _shadow_point_far) */
    mat4_perspective(1.5707963267948966, 1.0, 0.05, PIPE_POINT_FAR, proj);
    for (f = 0; f < 6; ++f) {
        if (!mat4_view_forward(eye, AXES[f], UPS[f], view))
            return LOOM_ERR_UNSUPPORTED;
        mat4_mul(view, proj, tmp);
        memcpy(out6x16 + f * 16, tmp, sizeof(double) * 16);
    }
    return LOOM_OK;
}

__declspec(dllexport) int32_t loom_pipeline_light_vps(const double *aabb_rows, int64_t n,
                                const int32_t *vis_idx, int64_t n_vis,
                                const LOOM_LIGHT *lights, int64_t n_lights,
                                double *out_vp, int32_t *out_kind)
{
    int64_t i;
    if (aabb_rows == NULL || lights == NULL || out_vp == NULL || out_kind == NULL)
        return LOOM_ERR_PARAM;
    if (n < 0 || n_lights < 0) return LOOM_ERR_PARAM;
    for (i = 0; i < n_lights; ++i) {
        const LOOM_LIGHT *L = lights + i;
        double *slot = out_vp + i * 6 * 16;      /* 统一 6 槽位预留 */
        int32_t rc;
        if (L->kind == LOOM_LIGHT_DIRECTIONAL) {
            rc = one_dir_light_vp(L, aabb_rows, n, vis_idx, n_vis, slot);
            if (rc == LOOM_OK) {
                out_kind[i] = 0;
            } else if (rc == LOOM_ERR_PARAM) {
                /* 调用方参数错误 (如 vis_idx 越界) → 如实上抛, 不吞成 -1 (D5) */
                out_kind[i] = -1;
                return rc;
            } else {
                out_kind[i] = -1;                /* 与 Python None 等价: 跳过该光源 */
            }
        } else {
            rc = one_point_light_vp(L, slot);
            if (rc == LOOM_OK) {
                out_kind[i] = 1;
            } else if (rc == LOOM_ERR_PARAM) {
                out_kind[i] = -1;
                return rc;
            } else {
                out_kind[i] = -1;
            }
        }
    }
    return LOOM_OK;
}

__declspec(dllexport) int32_t loom_pipeline_shadow_prep(const double *aabb_rows, int64_t n,
                                  const LOOM_LIGHT *lights, int64_t n_lights,
                                  double *out_vp, int32_t *out_kind)
{
    return loom_pipeline_light_vps(aabb_rows, n, NULL, 0, lights, n_lights,
                                   out_vp, out_kind);
}

/* ---------------------------------------------------------------------------
 * ③ AABB 批量归约 — 逐位照抄 ckernels\loom_kernels.c:_aabb_one_row
 * ------------------------------------------------------------------------- */
static void aabb_one_row(const double *vh_row, const double *m3_row,
                         double *mn, double *mx, int64_t V)
{
    double mn0 = 0.0, mn1 = 0.0, mn2 = 0.0;
    double mx0 = 0.0, mx1 = 0.0, mx2 = 0.0;
    const double *m = m3_row;
    double m00 = m[0], m01 = m[1], m02 = m[2];
    double m10 = m[3], m11 = m[4], m12 = m[5];
    double m20 = m[6], m21 = m[7], m22 = m[8];
    double m30 = m[9], m31 = m[10], m32 = m[11];
    int64_t v;

    for (v = 0; v < V; ++v) {
        const double *p = vh_row + v * 4;
        double a = p[0], b = p[1], c = p[2], d = p[3];
        double x = a * m00 + b * m10 + c * m20 + d * m30;
        double y = a * m01 + b * m11 + c * m21 + d * m31;
        double z = a * m02 + b * m12 + c * m22 + d * m32;
        if (v == 0) {
            mn0 = mx0 = x; mn1 = mx1 = y; mn2 = mx2 = z;
        } else {
            if (x < mn0) mn0 = x; else if (x > mx0) mx0 = x;
            if (y < mn1) mn1 = y; else if (y > mx1) mx1 = y;
            if (z < mn2) mn2 = z; else if (z > mx2) mx2 = z;
        }
    }
    mn[0] = mn0; mn[1] = mn1; mn[2] = mn2;
    mx[0] = mx0; mx[1] = mx1; mx[2] = mx2;
}

__declspec(dllexport) int32_t loom_pipeline_aabbs(const double *vh, const double *m3,
                            double *out_mn, double *out_mx,
                            int64_t n, int64_t V)
{
    int64_t i;
    if (n < 0 || V < 0) return 1;
    if (n == 0 || V == 0) return 0;
    if (vh == NULL || m3 == NULL || out_mn == NULL || out_mx == NULL) return 1;
    for (i = 0; i < n; ++i)
        aabb_one_row(vh + i * V * 4, m3 + i * 12,
                     out_mn + i * 3, out_mx + i * 3, V);
    return 0;
}

/* ============================================================================
 * ⑥ 世界矩阵批量 — 逐位对齐 engine.compute_world_matrices +
 *    scheduler.sched_wm_chunk (2026-09-08 M2 续)
 * ========================================================================== */

/* 单行局部矩阵: R = Rx@Ry@Rz → local = (S@R)@T
 * Rx/Ry/Rz/S/T 的构造式逐元素照抄 sched_wm_chunk (含 zeros 初始化语义) */
static void wm_one_row(double rx, double ry, double rz,
                       double sx_, double sy_, double sz_,
                       double px, double py, double pz, double *local)
{
    double cx = cos(rx), sxn = sin(rx);
    double cy = cos(ry), syn = sin(ry);
    double cz = cos(rz), szn = sin(rz);
    double Rx[16], Ry[16], Rz[16], R1[16], R[16], S[16], T[16], tmp[16];
    int i;

    for (i = 0; i < 16; ++i) { Rx[i] = 0.0; Ry[i] = 0.0; Rz[i] = 0.0;
                               S[i] = 0.0; T[i] = 0.0; }
    Rx[0] = 1.0;
    Rx[5] = cx;  Rx[6] = sxn;
    Rx[9] = -sxn; Rx[10] = cx;
    Rx[15] = 1.0;
    Ry[0] = cy;  Ry[2] = -syn;
    Ry[5] = 1.0;
    Ry[8] = syn; Ry[10] = cy;
    Ry[15] = 1.0;
    Rz[0] = cz;  Rz[1] = szn;
    Rz[4] = -szn; Rz[5] = cz;
    Rz[10] = 1.0; Rz[15] = 1.0;
    mat4_mul(Rx, Ry, tmp);          /* R1 = Rx @ Ry */
    mat4_mul(tmp, Rz, R);           /* R  = R1 @ Rz */
    S[0] = sx_; S[5] = sy_; S[10] = sz_; S[15] = 1.0;
    T[0] = 1.0; T[5] = 1.0; T[10] = 1.0; T[15] = 1.0;
    T[12] = px; T[13] = py; T[14] = pz;
    mat4_mul(S, R, tmp);            /* (S @ R) */
    mat4_mul(tmp, T, local);        /* local = (S@R) @ T */
}

__declspec(dllexport) int32_t loom_pipeline_world_matrices(
    const double *rot, const double *scl, const double *pos,
    const int64_t *parent, const int64_t *depth,
    int64_t n, int64_t max_depth, double *local_out, double *world_out)
{
    int64_t i, d;
    double *local;
    int own = 0;

    if (rot == NULL || scl == NULL || pos == NULL || parent == NULL
            || depth == NULL || world_out == NULL)
        return LOOM_ERR_PARAM;
    if (n < 0 || max_depth < 0) return LOOM_ERR_PARAM;
    if (n == 0) return LOOM_OK;
    local = local_out;
    if (local == NULL) {
        local = (double *)malloc((size_t)n * 16 * sizeof(double));
        if (local == NULL) return LOOM_ERR_INTERNAL;
        own = 1;
    }
    for (i = 0; i < n; ++i) {
        wm_one_row(rot[i * 3], rot[i * 3 + 1], rot[i * 3 + 2],
                   scl[i * 3], scl[i * 3 + 1], scl[i * 3 + 2],
                   pos[i * 3], pos[i * 3 + 1], pos[i * 3 + 2],
                   local + i * 16);
    }
    /* 沿 depth 升序合成 (d=0 直接拷 local, 否则 local[i] @ world[parent[i]]) */
    for (d = 0; d <= max_depth; ++d) {
        for (i = 0; i < n; ++i) {
            int64_t p;
            if (depth[i] != d) continue;
            if (d == 0) {
                memcpy(world_out + i * 16, local + i * 16, sizeof(double) * 16);
            } else {
                p = parent[i];
                if (p < 0 || p >= n) {
                    memcpy(world_out + i * 16, local + i * 16, sizeof(double) * 16);
                } else {
                    mat4_mul(local + i * 16, world_out + p * 16, world_out + i * 16);
                }
            }
        }
    }
    if (own) free(local);
    return LOOM_OK;
}

/* ============================================================================
 * 契约导出 (loom_module.h v1.0 最小函数集 7 个)
 * 写法逐一对齐 core_components\loom_module_ref.c
 * ========================================================================== */
static const LOOM_MODULE_INFO g_info = {
    LOOM_MODULE_MAGIC,
    LOOM_ABI_VERSION_CURRENT,
    "pipeline",            /* module_id: 与 registry.json 条目同名 */
    "1.0.0",
    1,                     /* official=1: 官方组件 */
    4,                     /* provides_count */
    0,                     /* depends_count */
    0
};

static const char *g_provides[] = {
    "pipeline.light_vps", "pipeline.scene_bounds", "pipeline.aabbs",
    "pipeline.world_matrices"
};

__declspec(dllexport) const LOOM_MODULE_INFO *loom_module_info(void)
{
    return &g_info;
}

__declspec(dllexport) const char *loom_module_provide(uint32_t index)
{
    if (index >= g_info.provides_count) return NULL;
    return g_provides[index];
}

__declspec(dllexport) const char *loom_module_depend(uint32_t index)
{
    (void)index;
    return NULL;           /* depends_count = 0 */
}

__declspec(dllexport) int32_t loom_module_init(void)
{
    return LOOM_OK;        /* 无设备资源; init 可重入 */
}

__declspec(dllexport) void loom_module_deinit(void)
{
}

/* ---- ⑦ 渲染帧插值平面 (M3-N4, 2026-09-09) -----------------------------------
 * 逐位对齐 interp_state.InterpState.render_pose 的 numpy 实现:
 *   映射  : slot = searchsorted(known_sorted, cur_ids, side='left'), 再 min(slot, known_n-1);
 *           loc = order[slot]                     (order = argsort(known))
 *   pos/scl: out = (curr - prev) * a + prev       (numpy: subtract → *= a → += prev)
 *   rot    : d = (curr - prev + π) mod 2π - π; out = prev + d * a
 *            mod 用 fmod + 负值补 2π (= numpy remainder 同语义)
 * 输入全 C 连续; loc_out 回传供调用方检测 miss (known[loc] != cur_ids, 即新物体)
 * 并走停泊逻辑; 输出平面由调用方提供 (无内部分配)。
 * 逃生门: 引擎侧 LOOM_NO_INTERP_POSE_DLL=1 → 回 numpy 路径。 */
__declspec(dllexport) int32_t loom_pipeline_interp_pose(
    const int64_t *cur_ids, const int64_t *known_sorted, const int64_t *order,
    int64_t known_n,
    const double *prev_pos, const double *curr_pos,
    const double *prev_rot, const double *curr_rot,
    const double *prev_scl, const double *curr_scl,
    int64_t n, double a,
    int64_t *loc_out, double *out_pos, double *out_rot, double *out_scl)
{
    const double LOOM_PI = 3.14159265358979323846;
    const double LOOM_TWO_PI = 6.28318530717958647692;
    int64_t i, k, lo, hi, mid, slot, loc;

    if (cur_ids == NULL || known_sorted == NULL || order == NULL
            || prev_pos == NULL || curr_pos == NULL
            || prev_rot == NULL || curr_rot == NULL
            || prev_scl == NULL || curr_scl == NULL
            || loc_out == NULL || out_pos == NULL || out_rot == NULL
            || out_scl == NULL)
        return LOOM_ERR_PARAM;
    if (n < 0 || known_n <= 0) return LOOM_ERR_PARAM;
    for (i = 0; i < n; ++i) {
        int64_t key = cur_ids[i];
        lo = 0; hi = known_n;
        while (lo < hi) {
            mid = lo + ((hi - lo) >> 1);
            if (known_sorted[mid] < key) lo = mid + 1; else hi = mid;
        }
        slot = lo;
        if (slot >= known_n) slot = known_n - 1;
        loc = order[slot];
        loc_out[i] = loc;
        for (k = 0; k < 3; ++k) {
            double pg = prev_pos[loc * 3 + k];
            double cg = curr_pos[loc * 3 + k];
            double d;
            out_pos[i * 3 + k] = (cg - pg) * a + pg;
            pg = prev_scl[loc * 3 + k];
            cg = curr_scl[loc * 3 + k];
            out_scl[i * 3 + k] = (cg - pg) * a + pg;
            pg = prev_rot[loc * 3 + k];
            cg = curr_rot[loc * 3 + k];
            d = (cg - pg) + LOOM_PI;
            d = fmod(d, LOOM_TWO_PI);
            if (d < 0.0) d += LOOM_TWO_PI;
            d = d - LOOM_PI;
            out_rot[i * 3 + k] = pg + d * a;
        }
    }
    return LOOM_OK;
}

/* ---- ⑧ 渲染帧「插值平面 → 世界矩阵」整段 (M3-N6, 2026-09-09) ----------------
 * 把 ⑦ (interp_pose) 与 ⑥ (world_matrices) 合并为**一次** C 调用: 中间
 * pos/rot/scl 平面留在 C 内, 免去两次 ctypes 往返与 6 个平面的 Python↔C 编组。
 * 数值口径与「先 ⑦ 再 ⑥」逐位相同 (同一 wm_one_row / mat4_mul, 同插值式)。
 * 输入: cur_ids(n,) / known_sorted(order 前像)(known_n,) / order(known_n,) int64;
 *       prev_/curr_ pos/rot/scl (cap,3) f64; parent(n,) / depth(n,) int64;
 *       max_depth; n; a (插值系数, 外推已由调用方封顶)
 * 输出: loc_out(n,) int64 (供调用方判 miss); world_out(n,4,4) f64
 * 返回: LOOM_OK / LOOM_ERR_PARAM / LOOM_ERR_INTERNAL */
__declspec(dllexport) int32_t loom_pipeline_interp_world(
    const int64_t *cur_ids, const int64_t *known_sorted, const int64_t *order,
    int64_t known_n,
    const double *prev_pos, const double *curr_pos,
    const double *prev_rot, const double *curr_rot,
    const double *prev_scl, const double *curr_scl,
    const int64_t *parent, const int64_t *depth, int64_t max_depth,
    int64_t n, double a,
    int64_t *loc_out, double *world_out)
{
    const double LOOM_PI = 3.14159265358979323846;
    const double LOOM_TWO_PI = 6.28318530717958647692;
    int64_t i, k, d, lo, hi, mid, slot, loc;
    double *local;

    if (cur_ids == NULL || known_sorted == NULL || order == NULL
            || prev_pos == NULL || curr_pos == NULL
            || prev_rot == NULL || curr_rot == NULL
            || prev_scl == NULL || curr_scl == NULL
            || parent == NULL || depth == NULL
            || loc_out == NULL || world_out == NULL)
        return LOOM_ERR_PARAM;
    if (n < 0 || known_n <= 0 || max_depth < 0) return LOOM_ERR_PARAM;
    if (n == 0) return LOOM_OK;
    local = (double *)malloc((size_t)n * 16 * sizeof(double));
    if (local == NULL) return LOOM_ERR_INTERNAL;
    for (i = 0; i < n; ++i) {
        int64_t key = cur_ids[i];
        double p[3], r[3], s[3];
        lo = 0; hi = known_n;
        while (lo < hi) {
            mid = lo + ((hi - lo) >> 1);
            if (known_sorted[mid] < key) lo = mid + 1; else hi = mid;
        }
        slot = lo;
        if (slot >= known_n) slot = known_n - 1;
        loc = order[slot];
        loc_out[i] = loc;
        for (k = 0; k < 3; ++k) {
            double pg = prev_pos[loc * 3 + k];
            double cg = curr_pos[loc * 3 + k];
            double dd;
            p[k] = (cg - pg) * a + pg;
            pg = prev_scl[loc * 3 + k];
            cg = curr_scl[loc * 3 + k];
            s[k] = (cg - pg) * a + pg;
            pg = prev_rot[loc * 3 + k];
            cg = curr_rot[loc * 3 + k];
            dd = (cg - pg) + LOOM_PI;
            dd = fmod(dd, LOOM_TWO_PI);
            if (dd < 0.0) dd += LOOM_TWO_PI;
            dd = dd - LOOM_PI;
            r[k] = pg + dd * a;
        }
        wm_one_row(r[0], r[1], r[2], s[0], s[1], s[2], p[0], p[1], p[2],
                   local + i * 16);
    }
    for (d = 0; d <= max_depth; ++d) {
        for (i = 0; i < n; ++i) {
            int64_t pp;
            if (depth[i] != d) continue;
            if (d == 0) {
                memcpy(world_out + i * 16, local + i * 16, sizeof(double) * 16);
            } else {
                pp = parent[i];
                if (pp < 0 || pp >= n) {
                    memcpy(world_out + i * 16, local + i * 16,
                           sizeof(double) * 16);
                } else {
                    mat4_mul(local + i * 16, world_out + pp * 16,
                             world_out + i * 16);
                }
            }
        }
    }
    free(local);
    return LOOM_OK;
}

// @jev-block:pack_bucket_instances:begin
LOOM_PIPE_API int32_t loom_pipeline_pack_bucket_instances(
    const float *fw32, int64_t n_models,
    const int32_t *idxs, int64_t k,
    const float *sat, const float *rgba,
    float *out_main, float *out_sha)
{
    int64_t i;
    if (fw32 == NULL || idxs == NULL || out_main == NULL) return LOOM_ERR_PARAM;
    if (n_models < 0 || k < 0) return LOOM_ERR_PARAM;
    if (k == 0) return LOOM_OK;

    for (i = 0; i < k; ++i) {
        int32_t idx = idxs[i];
        if (idx < 0 || idx >= n_models) return LOOM_ERR_PARAM;
        const float *src = fw32 + (size_t)idx * 16;
        float *dst_m = out_main + (size_t)i * 24;

        /* 矩阵 16 floats (64 字节) */
        memcpy(dst_m, src, sizeof(float) * 16);
        if (out_sha != NULL) {
            memcpy(out_sha + (size_t)i * 16, src, sizeof(float) * 16);
        }

        /* 材质属性: sat + pad3 + rgba4 */
        dst_m[16] = (sat != NULL) ? sat[i] : 0.0f;
        dst_m[17] = 0.0f;
        dst_m[18] = 0.0f;
        dst_m[19] = 0.0f;

        if (rgba != NULL) {
            memcpy(dst_m + 20, rgba + (size_t)i * 4, sizeof(float) * 4);
        } else {
            dst_m[20] = 0.0f;
            dst_m[21] = 0.0f;
            dst_m[22] = 0.0f;
            dst_m[23] = 0.0f;
        }
    }
    return LOOM_OK;
}
// @jev-block:pack_bucket_instances:end

// @jev-block:dirty_mask:begin
LOOM_PIPE_API int32_t loom_pipeline_dirty_mask(
    const double *cur_rows,
    const double *old_rows,
    const int64_t *pidx,
    int64_t n,
    uint8_t *out_mask)
{
    int64_t i, k;
    int changed;
    int64_t round;
    if (cur_rows == NULL || old_rows == NULL || out_mask == NULL)
        return LOOM_ERR_PARAM;
    if (n < 0) return LOOM_ERR_PARAM;
    if (n == 0) return LOOM_OK;

    /* 基础脏检测: 与 Python (cur != old) 逐位完全一致 */
    for (i = 0; i < n; ++i) {
        const double *c = cur_rows + i * 6;
        const double *o = old_rows + i * 6;
        uint8_t is_dirty = 0;
        for (k = 0; k < 6; ++k) {
            if (c[k] != o[k]) {
                is_dirty = 1;
                break;
            }
        }
        out_mask[i] = is_dirty;
    }

    /* 祖先链传播: 父脏则子脏 (循环直到无新增, 限制最多 n 轮防环) */
    if (pidx != NULL) {
        changed = 1;
        round = 0;
        while (changed && round < n) {
            changed = 0;
            for (i = 0; i < n; ++i) {
                int64_t p = pidx[i];
                if (p >= 0 && p < n) {
                    if (out_mask[p] && !out_mask[i]) {
                        out_mask[i] = 1;
                        changed = 1;
                    }
                }
            }
            round++;
        }
    }
    return LOOM_OK;
}
// @jev-block:dirty_mask:end

// @jev-block:local_matrices:begin
LOOM_PIPE_API int32_t loom_pipeline_local_matrices(
    const double *rot,
    const double *scl,
    const double *pos,
    int64_t n,
    double *out_m)
{
    int64_t i;
    if (rot == NULL || scl == NULL || pos == NULL || out_m == NULL)
        return LOOM_ERR_PARAM;
    if (n < 0) return LOOM_ERR_PARAM;
    if (n == 0) return LOOM_OK;

    for (i = 0; i < n; ++i) {
        wm_one_row(rot[i * 3], rot[i * 3 + 1], rot[i * 3 + 2],
                   scl[i * 3], scl[i * 3 + 1], scl[i * 3 + 2],
                   pos[i * 3], pos[i * 3 + 1], pos[i * 3 + 2],
                   out_m + i * 16);
    }
    return LOOM_OK;
}
// @jev-block:local_matrices:end

// @jev-block:depths:begin
LOOM_PIPE_API int32_t loom_pipeline_depths(
    const int64_t *parent,
    int64_t n,
    int64_t *out_depth)
{
    int64_t i;
    if (parent == NULL || out_depth == NULL) return LOOM_ERR_PARAM;
    if (n < 0) return LOOM_ERR_PARAM;
    if (n == 0) return LOOM_OK;

    for (i = 0; i < n; ++i) {
        int64_t d = 0;
        int64_t cur = i;
        while (cur >= 0 && cur < n && parent[cur] >= 0 && d < n) {
            cur = parent[cur];
            d++;
        }
        out_depth[i] = d;
    }
    return LOOM_OK;
}
// @jev-block:depths:end

// @jev-block:ancestry_dfs:begin
LOOM_PIPE_API int32_t loom_pipeline_ancestry_dfs(
    const int64_t *parent,
    int64_t n,
    int64_t *out_tin,
    int64_t *out_tout)
{
    int64_t i, r, p, timer, sp;
    int64_t *cnt = NULL, *start = NULL, *child_arr = NULL, *fill = NULL;
    int64_t *in_forest = NULL, *snode = NULL, *sk = NULL;

    if (parent == NULL || out_tin == NULL || out_tout == NULL) return LOOM_ERR_PARAM;
    if (n < 0) return LOOM_ERR_PARAM;
    if (n == 0) return LOOM_OK;

    cnt = (int64_t *)calloc((size_t)n, sizeof(int64_t));
    start = (int64_t *)calloc((size_t)(n + 1), sizeof(int64_t));
    fill = (int64_t *)malloc((size_t)n * sizeof(int64_t));
    in_forest = (int64_t *)calloc((size_t)n, sizeof(int64_t));
    snode = (int64_t *)malloc((size_t)(n + 1) * sizeof(int64_t));
    sk = (int64_t *)malloc((size_t)(n + 1) * sizeof(int64_t));

    if (!cnt || !start || !fill || !in_forest || !snode || !sk) {
        free(cnt); free(start); free(fill); free(in_forest); free(snode); free(sk);
        return LOOM_ERR_INTERNAL;
    }

    for (i = 0; i < n; ++i) {
        p = parent[i];
        if (p >= 0 && p < n) cnt[p]++;
    }
    for (p = 0; p < n; ++p) {
        start[p + 1] = start[p] + cnt[p];
    }
    child_arr = (int64_t *)malloc((size_t)(start[n] + 1) * sizeof(int64_t));
    if (!child_arr) {
        free(cnt); free(start); free(fill); free(in_forest); free(snode); free(sk);
        return LOOM_ERR_INTERNAL;
    }
    memcpy(fill, start, (size_t)n * sizeof(int64_t));
    for (i = 0; i < n; ++i) {
        p = parent[i];
        if (p >= 0 && p < n) {
            child_arr[fill[p]] = i;
            fill[p]++;
        }
    }

    timer = 0;
    sp = 0;
    for (r = 0; r < n; ++r) {
        if (parent[r] < 0) {
            if (in_forest[r]) continue;
            in_forest[r] = 1;
            snode[0] = r;
            sk[0] = 0;
            sp = 1;
            while (sp > 0) {
                int64_t u = snode[sp - 1];
                int64_t k = sk[sp - 1];
                if (k == 0) {
                    out_tin[u] = timer++;
                }
                if (k < cnt[u]) {
                    int64_t v = child_arr[start[u] + k];
                    sk[sp - 1] = k + 1;
                    if (v >= 0 && v < n && !in_forest[v]) {
                        in_forest[v] = 1;
                        snode[sp] = v;
                        sk[sp] = 0;
                        sp++;
                    }
                } else {
                    out_tout[u] = timer;
                    sp--;
                }
            }
        }
    }
    for (r = 0; r < n; ++r) {
        if (!in_forest[r]) {
            out_tin[r] = timer;
            out_tout[r] = timer + 1;
            timer++;
        }
    }

    free(cnt); free(start); free(fill); free(child_arr);
    free(in_forest); free(snode); free(sk);
    return LOOM_OK;
}
// @jev-block:ancestry_dfs:end


__declspec(dllexport) uint32_t loom_module_abi(void)
{
    return LOOM_ABI_VERSION_CURRENT;
}

__declspec(dllexport) int32_t loom_module_has(const char *iface_name)
{
    if (iface_name == NULL) return 0;
    if (strcmp(iface_name, "pipeline.light_vps") == 0) return 1;
    if (strcmp(iface_name, "pipeline.scene_bounds") == 0) return 1;
    if (strcmp(iface_name, "pipeline.aabbs") == 0) return 1;
    if (strcmp(iface_name, "pipeline.world_matrices") == 0) return 1;
    if (strcmp(iface_name, "pipeline.pack_bucket_instances") == 0) return 1;
    if (strcmp(iface_name, "pipeline.dirty_mask") == 0) return 1;
    if (strcmp(iface_name, "pipeline.local_matrices") == 0) return 1;
    if (strcmp(iface_name, "pipeline.depths") == 0) return 1;
    if (strcmp(iface_name, "pipeline.ancestry_dfs") == 0) return 1;
    return 0;
}
