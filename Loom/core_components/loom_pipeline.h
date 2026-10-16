/* ============================================================================
 * loom_pipeline.h — pipeline.dll 组件接口 (M2a, 2026-09-08)
 * ============================================================================
 * 地位: loom_module.h (通用 C ABI v1.0) 之上的**组件专属头**。本文件只声明
 *       pipeline 组件对外暴露的热路径函数; 通用契约 (7 导出/LOOM_TENSOR/
 *       错误码) 仍由 loom_module.h 定义。
 *
 * 数值纪律 (M2 验收① 逐位对拍的前提):
 *   本组件所有浮点运算必须复刻 engine.py / matlib.py 现行实现的**运算顺序**
 *   (角点填充序 / matmul 求和序 / min-max 比较序), 全部 f64, 禁 /fp:fast。
 *   任何"优化"若改变求和序或比较序 → 逐位对拍立刻失败, 视为缺陷。
 *
 * 归属边界 (M2 设计文档 §2): 本组件只吃"已算好的 AABB 行表"和"光源描述",
 *   输出 VP 矩阵/包围盒; 不碰场景图、不碰物理、不持跨帧状态。
 * ========================================================================== */
#ifndef LOOM_PIPELINE_H
#define LOOM_PIPELINE_H

#include <stdint.h>

/* 导出宏: 本头声明的热路径函数均为 DLL 导出符号 (声明与定义必须同链接属性) */
#ifdef _WIN32
#  define LOOM_PIPE_API __declspec(dllexport)
#else
#  define LOOM_PIPE_API
#endif

#ifdef __cplusplus
extern "C" {
#endif

/* ---- 光源描述 (与 engine.Light 字段一一对应) ----------------------------- */
#define LOOM_LIGHT_DIRECTIONAL 0
#define LOOM_LIGHT_POINT       1

#define LOOM_LIGHT_MODE_FULL   0   /* 正交 XY 覆盖场景 bbox */
#define LOOM_LIGHT_MODE_BEAM   1   /* 正交 XY = [-size,size]^2, near=0 */

typedef struct LOOM_LIGHT {
    int32_t kind;          /* LOOM_LIGHT_DIRECTIONAL / LOOM_LIGHT_POINT */
    int32_t shadow;        /* 1=投影 (0 的光源基座直接跳过, 不会传进来) */
    int32_t mode;          /* LOOM_LIGHT_MODE_* (仅 directional 有意义) */
    int32_t _pad;          /* 对齐填充, 置 0 */
    double  position[3];   /* 世界位置 (eye) */
    double  direction[3];  /* 行进方向 (directional; 内部归一化, 长度<1e-6 返失败) */
    double  up[3];         /* roll 倾斜 (engine: light.up_vector()) */
    double  size;          /* beam 截面半宽 (mode=beam) */
} LOOM_LIGHT;

/* ---- AABB 行表 ------------------------------------------------------------
 * (n, 6) f64, 行序与 models 下标对齐, 列序:
 *   [mn.x, mn.y, mn.z, mx.x, mx.y, mx.z]
 * 与 engine._aabb_shadow_rows 同口径同序 (shadow/collision 共享那份)。 */
#define LOOM_PIPE_AABB_STRIDE 6

/* ---- ① 光源 view-proj 批量计算 --------------------------------------------
 * 逐位对齐 engine._compute_light_vps / _dir_light_vp / _point_light_vp。
 *   aabb_rows : (n,6) f64 全量对齐 AABB 行表; n==0 时允许 NULL
 *   vis_idx   : 可选可见行下标 (n_vis 个); NULL/0 = 用全量行表 (full 模式)
 *   lights    : (n_lights) 光源数组
 *   out_vp    : (n_lights, 4, 4) f64 行主序, 每光源写 4x4 (点光写 6 个, 见 out_kind)
 *   out_kind  : (n_lights) int32 输出: 0=单矩阵 (directional) 1=6 面 (point)
 *              对于 point, out_vp 需 (n_lights, 6, 4, 4); 调用方按 out_kind 解读。
 *              为避免歧义, 本函数对 point 光源把 6 个矩阵**连续写**在该光源槽位,
 *              故 out_vp 必须按 max(1,kind==point?6:1) 槽位预留 —— 推荐调用方
 *              直接传 (n_lights, 6, 4, 4) 大小, directional 只用第 0 个。
 * 返回: LOOM_OK / LOOM_ERR_PARAM (空指针 / n<0 / 方向退化返回 LOOM_ERR_UNSUPPORTED
 *       并置 out_kind=-1 表示该光源无 VP, 基座跳过 —— 与 Python 返回 None 等价)
 */
LOOM_PIPE_API int32_t loom_pipeline_light_vps(const double *aabb_rows, int64_t n,
                                const int32_t *vis_idx, int64_t n_vis,
                                const LOOM_LIGHT *lights, int64_t n_lights,
                                double *out_vp, int32_t *out_kind);

/* ---- ② 场景光照包围盒 ------------------------------------------------------
 * 把 aabb_rows 的每行 8 个角点用 view_4x4 变换到 view 空间, 取全局 min/max。
 * 逐位对齐 engine._scene_light_bounds_par (角点序见 .c 内注释)。
 *   view_4x4  : (4,4) f64 行主序
 *   aabb_rows : (n,6) f64; n==0 → 返回 LOOM_ERR_PARAM (Python 侧返回 None)
 *   out_mn/out_mx : (3,) f64
 */
LOOM_PIPE_API int32_t loom_pipeline_scene_bounds(const double *view_4x4,
                                   const double *aabb_rows, int64_t n,
                                   double *out_mn, double *out_mx);

/* ---- ③ AABB 批量归约 (与 ckernels 内核逐位同序的组件内副本) ---------------
 * vh (n,V,4) f64 行主序 + m3 (n,4,3) f64 → out_mn/out_mx (n,3) f64。
 * 运算序严格照抄 ckernels\loom_kernels.c:_aabb_one_row (标量升序求和 +
 * 纯比较), 保证与 fastpath C 路径逐位一致。
 * 返回: 0=OK, 1=参数非法 (n<0 或 V<0) —— 沿用 ckernels 返回码惯例。
 */
LOOM_PIPE_API int32_t loom_pipeline_aabbs(const double *vh, const double *m3,
                            double *out_mn, double *out_mx,
                            int64_t n, int64_t V);

/* ---- ④ 光源 VP 便捷入口 (基座最常用: 一次算完所有阴影光源) ----------------
 * 等价于先 loom_pipeline_scene_bounds 再按光源 mode 组装正交/透视投影,
 * 但省去 Python 侧往返。语义与 loom_pipeline_light_vps 完全一致。
 * (本阶段基座走 ①, 本入口供 M2b 批量化使用; 实现复用 ① 内部逻辑。) */
LOOM_PIPE_API int32_t loom_pipeline_shadow_prep(const double *aabb_rows, int64_t n,
                                  const LOOM_LIGHT *lights, int64_t n_lights,
                                  double *out_vp, int32_t *out_kind);

/* ---- ⑤ 对拍辅助: 暴露本组件所用的 4x4 行主序乘法 (k 升序求和) -------------
 * 探针用它验证「C 乘法 vs numpy @」的 1 ULP 界 (M2 设计文档 §4 例外条款):
 * 逐元素运算必须逐位为 0, 矩阵乘法允许 1 ULP (numpy 走 BLAS/SIMD 求和序不同)。
 * 本函数**不是**热路径 API, 仅供数值取证。 */
LOOM_PIPE_API void loom_pipeline_mat4_mul_ref(const double *a, const double *b,
                                              double *out);

/* ---- ⑥ 世界矩阵批量 (M2 续: _logic_frame 链的 world_matrices 段) ----------
 * 逐位对齐 engine.compute_world_matrices + scheduler.sched_wm_chunk:
 *   局部: R = Rx@Ry@Rz (左结合) → local = S@R@T (左结合 (S@R)@T)
 *         Rx/Ry/Rz 逐元素同 matlib/sched_wm_chunk 构造式 (含 0 初始化)
 *   世界: 按 depth 升序, d=0 → local, 否则 world[i] = local[i] @ world[parent[i]]
 * 输入 (全 C 连续 f64):
 *   rot  (n,3) 弧度 / scl (n,3) / pos (n,3)
 *   parent (n,) int64 (-1 = 根)   depth (n,) int64
 *   local_out (n,4,4) 可选 (NULL = 内部临时分配; 非 NULL = 复用调用方缓冲)
 *   world_out (n,4,4) 结果
 * 返回: LOOM_OK / LOOM_ERR_PARAM / LOOM_ERR_INTERNAL (分配失败)
 * 注: depth 由调用方算 (fastpath.depths 已在线), 本函数不做深度 DP。 */
LOOM_PIPE_API int32_t loom_pipeline_world_matrices(const double *rot,
                                                   const double *scl,
                                                   const double *pos,
                                                   const int64_t *parent,
                                                   const int64_t *depth,
                                                   int64_t n, int64_t max_depth,
                                                   double *local_out,
                                                   double *world_out);

/* ---- ⑦ 渲染帧插值平面 (M3-N4, 2026-09-09: InterpState.render_pose 整段) ----
 * 逐位对齐 interp_state.render_pose 的 numpy 实现 (行映射 + pos/rot/scl 插值):
 *   slot = searchsorted(known_sorted, cur_ids, side='left') → min(slot, known_n-1)
 *   loc  = order[slot]        (order = argsort(known))
 *   pos/scl: out = (curr - prev) * a + prev
 *   rot    : d = (curr - prev + π) mod 2π - π;  out = prev + d * a
 * 输入 (全 C 连续):
 *   cur_ids (n,) int64          — 当前 models 行序的 id
 *   known_sorted (known_n,)     — _ids[:known_n] 的 argsort 结果 (升序)
 *   order (known_n,) int64      — argsort(_ids[:known_n])
 *   prev_/curr_ pos/rot/scl (cap,3) f64 — 双快照平面 (按 _ids 行序)
 *   n, a (插值系数; 外推时 a>1, 由调用方封顶)
 *   loc_out (n,) int64 — 每输出行 → _ids 行号 (调用方据此判 miss)
 *   out_pos/out_rot/out_scl (n,3) f64 — 输出 (调用方缓冲, 本函数不分配)
 * 返回: LOOM_OK / LOOM_ERR_PARAM。 */
LOOM_PIPE_API int32_t loom_pipeline_interp_pose(
    const int64_t *cur_ids, const int64_t *known_sorted, const int64_t *order,
    int64_t known_n,
    const double *prev_pos, const double *curr_pos,
    const double *prev_rot, const double *curr_rot,
    const double *prev_scl, const double *curr_scl,
    int64_t n, double a,
    int64_t *loc_out, double *out_pos, double *out_rot, double *out_scl);

/* ---- ⑧ 渲染帧「插值平面 → 世界矩阵」整段 (M3-N6, 2026-09-09) ---------------
 * ⑦ + ⑥ 合并为一次调用 (中间 pos/rot/scl 平面留在 C 内, 免两次 ctypes 往返)。
 * 数值口径与「先 ⑦ 再 ⑥」逐位相同。输入见 .c 注释; 输出 loc_out(n,) 与
 * world_out(n,4,4)。 */
LOOM_PIPE_API int32_t loom_pipeline_interp_world(
    const int64_t *cur_ids, const int64_t *known_sorted, const int64_t *order,
    int64_t known_n,
    const double *prev_pos, const double *curr_pos,
    const double *prev_rot, const double *curr_rot,
    const double *prev_scl, const double *curr_scl,
    const int64_t *parent, const int64_t *depth, int64_t max_depth,
    int64_t n, double a,
    int64_t *loc_out, double *world_out);

/* ---- ⑨ 桶级实例缓冲打包 (M3 渲染预计算: _prepare_bucket_frame 汇聚段) -------
 * 逐位对齐 engine._prepare_bucket_frame 内的实例打包逻辑:
 *   - 将 fw32 中第 idxs[i] 行 (4x4 f32 = 16 floats) 提取并填入 out_sha (16 floats);
 *   - 将同一矩阵填入 out_main 的前 16 列;
 *   - 将 sat[i] (若非空) 填入 out_main 第 16 列 (17..19 列置 0.0 对齐);
 *   - 将 rgba[i*4..i*4+3] (若非空) 填入 out_main 的第 20..23 列。
 * 输入 (全连续 f32 / i32):
 *   fw32      : (n_models, 4, 4) f32 全量世界矩阵表
 *   n_models  : 总模型数
 *   idxs      : (k,) int32 当前桶引用的模型全局序号
 *   k         : 实例数量
 *   sat       : (k,) f32 饱和度 (可选, NULL 置 0.0)
 *   rgba      : (k, 4) f32 颜色 (可选, NULL 置 0.0)
 * 输出:
 *   out_main  : (k, 24) f32 主 pass 实例数据缓冲
 *   out_sha   : (k, 16) f32 阴影 pass 实例数据缓冲 (可选, NULL 跳过)
 * 返回: LOOM_OK (0) / LOOM_ERR_PARAM (-2)
 */
LOOM_PIPE_API int32_t loom_pipeline_pack_bucket_instances(
    const float *fw32, int64_t n_models,
    const int32_t *idxs, int64_t k,
    const float *sat, const float *rgba,
    float *out_main, float *out_sha);

/* ---- ⑩ 物理位姿脏检测与祖先链传播 (physics_bridge._dirty_mask_batch) --------
 * 逐位对齐 physics_bridge._dirty_mask_batch 的数学语义:
 *   - cur_rows vs old_rows 任一分量 != 则标记 dirty (float != float 逐位一致)
 *   - 沿 pidx 父链拓扑迭代传播 (父脏则子脏)
 * 输入:
 *   cur_rows  : (n, 6) f64 [px, py, pz, rx, ry, rz]
 *   old_rows  : (n, 6) f64 上次同步位姿
 *   pidx      : (n,) int64 父节点在 [0, n-1] 内部序号 (-1 表示无父)
 *   n         : 刚体/实体数量
 * 输出:
 *   out_mask  : (n,) uint8 脏位标记 (1=脏, 0=干净)
 * 返回: LOOM_OK (0) / LOOM_ERR_PARAM (-2)
 */
LOOM_PIPE_API int32_t loom_pipeline_dirty_mask(
    const double *cur_rows,
    const double *old_rows,
    const int64_t *pidx,
    int64_t n,
    uint8_t *out_mask);

/* ---- ⑪ 局部矩阵批量构建 (physics_bridge._local_matrices_batch) --------------
 * 逐位对齐 physics_bridge._local_matrices_batch 的局部变换计算:
 *   local = (S @ Rx @ Ry @ Rz) @ T (与 wm_one_row 逐位一致)
 * 输入:
 *   rot       : (n, 3) f64 欧拉角弧度
 *   scl       : (n, 3) f64 缩放
 *   pos       : (n, 3) f64 平移
 *   n         : 物体数量
 * 输出:
 *   out_m     : (n, 4, 4) f64 局部变换矩阵
 * 返回: LOOM_OK (0) / LOOM_ERR_PARAM (-2)
 */
LOOM_PIPE_API int32_t loom_pipeline_local_matrices(
    const double *rot,
    const double *scl,
    const double *pos,
    int64_t n,
    double *out_m);

#ifdef __cplusplus
} /* extern "C" */
#endif

#endif /* LOOM_PIPELINE_H */
