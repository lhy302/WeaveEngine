# 调研报告 04：Python 热点下沉 C/C++ 研判（beta6）

> 编号：04／beta6
> 状态：**调研（只读）**，不含实现代码；接口与数据结构为草案。
> 仓库根：D:\my-project - 副本\Loom(py源代码-工作区)，本文行号以本次实测工作树为准。
> 口径：**能跑的一律跑**。所有"ms/帧"都注明测量宿主（编辑器 Loom.py --agent / 播放器 `runtime.PlayerApp`）与采样窗口。
> 复现命令见附录 A（探针全部落在 gitignore 的 Loom/tests/_tmp/research_04_*.py，未改任何受跟踪文件）。

---

## 0. 一句话结论

beta5 遗留的四个"每帧成本"里，**只有一个是真正的 Python 热点、且值得下沉**：

| beta5 说法 | 本次实测 | 下沉价值 |
|---|---|---|
| `buckets` 2.3 ms | 编辑器 **2.65 ms/帧**（播放器 1.45） | **值得**：成本不是 GL 上传（仅 0.10），是 **~250–350 次小数组 numpy 调用**（逐桶花式索引）。单次花式索引在 2/4/6 线程争用下从 2.5 µs 膨胀到 20/58/110 µs（8x/23x/44x） |
| `mt_mp_draws` 1.4 ms | 编辑器 **1.51 ms/帧**；同一段代码在播放器 **0.26 ms/帧** | **暂不值得**：35 次 `vao.render` 实测仅 **0.045 ms/帧（1.3 µs/次）**，多绘间接天花板≈2% 帧时间；且编辑器 1.5 vs 播放器 0.26 有 1.25 ms **归因未闭合**（见 附录 B） |
| `aabbs` 2.1 ms | 编辑器 **2.24 ms/帧**（= 6.48 ms/逻辑帧） | **C 内核已存在**：C 调用本身 1.38 ms/帧，Python 组装 0.47–0.86 ms/帧。**下沉 Python 段收益小，但 C 内核 SIMD 化实测 2.2–2.4x 且逐位一致** |
| `pipe_wait` 3.6 ms | 编辑器 **3.99 ms/帧**（每次等待 11.6 ms） | **真正的头号成本，但根因不在"Python 慢"**：物理线程每逻辑帧干 ~9.5 ms Python 活（`_dirty_mask_batch` 2.18 ms × 3 子步），Jolt step 只占 0.2 ms。**下沉脏检测装配层**可同时省主线程等待 |

**最大单项收益**：把物理桥"逐体属性抓取 + 拼数组"的装配段换成"引擎已有 SoA 平面 → 一次 C 调用"，
预估主线程 **−2.0 ms/帧**（`pipe_wait` 3.99 → ~2.0），且顺带削掉一个持 GIL 大户。

---

## ① 现状（证据）

### 1.1 现有"原生面"盘点（先纠正规模）

| 资产 | 规模 | 事实 |
|---|---|---|
| `Loom/ckernels/loom_kernels.c` | 18 321 B → `loom_kernels.dll` 16 896 B | 导出 3 个数值内核 + 7 个 `loom_module_*` 契约导出：`loom_aabbs_minmax` / _par（C:68、C:100）、`loom_collide_pairs`（C:236） |
| `Loom/core_components`/*.dll | 5 个官方组件 | 不是"样例"：`pipeline.dll`（光源 VP/AABB 归约/世界矩阵/**脏检测**/插值世界矩阵）、`physics.dll`（`pre_step`/`post_step`/`substep_loop`）、`script.dll`、`module_ref.dll` 都在**生产路径**上（`pipeline_glue.dirty_mask` 被 `physics_bridge.py`:1057 调用；interp_state.py:259 调 pg.`interp_world`；`physics_bridge.py`:1295 调 `_phys_glue`.`pre_step` 做摩擦+残速） |
| 编译方式 | `ckernels`/`build_ckernels.bat` | cl /O2 /Brepro /LD /MD，**禁 /fp:fast**（保求和序），可复现构建 |

结论：**"手写 C 很少"是误判**。真实情况是"数值内核已 C 化，**装配/派发/同步**这层留在 Python"。
因此本报告的议题不是"再写多少 C"，而是"**Python 侧的装配层还要不要继续下沉**"。

### 1.2 一次完整分段测量（编辑器，压测500混合，87.3 FPS）

命令（本次实跑，产物 Loom/tests/_tmp/`mt_profile_on_r04.json`）：

    cd 'D:\my-project - 副本\Loom(py源代码-工作区)\Loom'
    py -3.12 tests/_tmp/`mt_profile_check.py` --scene 压测500混合.json --secs 6 --suffix _r04

窗口：播放态稳态 6.00 s / 524 渲染帧 / 501 模型 / **35 桶**（16×20 + 18×10 + 1 实例 = 501）/ 35 draw/帧 / TPS 30.06。

| 段 | ms/帧 | 调用/帧 | µs/调用 | 备注 |
|---|---:|---:|---:|---|
| **`pipe_wait`** | **3.994** | 0.35 | 11 562 | 主线程阻塞等物理线程（S1 同步点） |
| **`buckets`** | **2.648** | 1.00 | 2 648 | 桶重排 + 实例缓冲打包上传（`loom_render.py`:914-915） |
| **aabbs** | **2.239** | 0.345 | 6 481 | `loom_lighting.py`:248-442 |
| ├ `aabbs_inner` | 2.216 | 0.345 | — | 同上（内层计时，与外层同源） |
| ├ `mt_aabb_minmax` | 1.379 | 2.07 | 665 | **C 内核** `fastpath.aabbs_minmax` |
| ├ `mt_aabb_out` | 0.359 | 2.07 | 173 | 行表写回（numpy 散写） |
| └ 组装/分组/去重残差 | ≈0.47 | — | — | 501 行属性 + 分组 + 唯一行表 |
| **`mt_main_pass`** | 1.868 | 1.00 | 1 868 | 含下两项 + 相机 + 天空盒 |
| **`mt_mp_draws`** | **1.513** | 1.00 | 1 513 | `_draw_main_buckets`（`editor.py`:2337-2339） |
| **`collide_pairs`** | **1.116** | 0.34 | 3 250 | **C 内核** `loom_collide_pairs` |
| **interp** | **0.910** | 0.99 | 919 | `mt_interp_world_dll` 0.897 → **C（`pipeline.dll`）** |
| `mt_shadow_maps` | 0.883 | 1.00 | 883 | 阴影 pass 35×sha_vao.render |
| **`world_matrices`** | **0.713** | 0.35 | 2 064 | numpy 批量（父链分层 matmul） |
| **`mt_dispatch`** | **0.552** | 0.34 | 1 607 | 碰撞事件派发（`engine.py`:1249-1252） |
| **`mt_scripts`** | **0.430** | 0.34 | 1 251 | 脚本回调 |
| lod | 0.295 | 1.00 | 295 | |
| `shadow_bounds` | 0.250 | 0.35 | 725 | |
| `mt_qt_tick` / `mt_fixed_update` / `mt_editor_view` | 0.200 / 0.177 / 0.166 | — | — | Qt 胶水 / FixedUpdate / 编辑器 UI |
| `mt_mp_uniforms` | 0.110 | 1.00 | 110 | VP + 灯光整块上传 |

> 闭合校验：`mt_paint_total` 7.175 = `mt_paint_advance` + `mt_paint_render` (7.138) + 胶水 0.037，OK（探针 closure.ok=true）。

### 1.3 物理线程的真实账本（`LOOM_PROFILE` 看不到的部分）

`LOOM_PROFILE` 的 `phys_bridge_pre/post/step` 只覆盖**串行降级路径**（engine.update_physics）；
播放态走 `physics_pipe.PhysicsPipeThread`（`physics_pipe.py`:63-84），**这三段在物理线程上，无插桩**。
用 perf_counter 包 `PhysicsBridge` 方法实测（播放器，501 模型，120 帧，75 FPS）：

| 物理线程函数 | ms/帧 | 次/帧 | ms/次 | 说明 |
|---|---:|---:|---:|---|
| `pre_step` | 2.401 | 0.83 | **2.88** | 含下一行 |
| ├ `_dirty_mask_batch` | 1.815 | 0.83 | **2.18** | `physics_bridge.py`:988-1071 |
| ├ 其余（逐脏体 set_position/rotation + 速度策略） | 0.586 | — | — | |
| `ensure_models` | 0.453 | 0.42 | 1.09 | `physics_bridge.py`:920-972 |
| **step（Jolt C）** | **0.202** | 0.83 | 0.24 | Jolt 本身极便宜 |
| `post_step` | 0.056 | 0.83 | 0.07 | 摩擦/残速已下沉 C（`physics_bridge.py`:1295） |
| `_refresh_free` | 0.037 | 0.42 | 0.09 | |
| （主线程）pipe.`wait_pending` | 3.22 | 0.42 | **7.7** | 主线程阻塞 |

**归因**：主线程 `pipe_wait` ≈ 物理线程 Python 装配时间 + GIL 交接延迟。
编辑器 30 TPS、3 子步/逻辑帧时，物理线程每逻辑帧 ≈ 3 × (2.88 + 0.24) + 1.09 ≈ **10.4 ms**，
与实测"每次 wait 11.6 ms"吻合；而其中 ** `_dirty_mask_batch` 占 6.5 ms（≈63%）**。

同时它解释了 `_dirty_mask_batch` 为什么慢：它是**纯 Python 对象风暴**——
501 节点各取 m.position（新建 Point3D）、m.rotation（Quat）、getattr(m,'parent')、
self.`_last_sync`.get(id(m))，再拼 5 个 list、2 个 numpy 数组、3 个 dict（`physics_bridge.py`:1013-1071）。
而 C 侧真正的比较内核 `pipeline_glue.dirty_mask`（n=501）实测只要 **0.020 ms**（见 §1.5）。

### 1.4 `buckets`：钱花在哪（A/B 实测，非推断）

方法：在探针进程内把 `_bucket_inst`[key]['main'/'sha'] 换成计时代理（真写）→ 再换成 no-op；
把 `_bucket_geo`[key]['vao'] 换成代理（真 draw）→ 再 no-op。同一场景、同一 60 帧窗口（`research_04_ab_split.py`）。

| 项目 | 播放器实测 | 说明 |
|---|---:|---|
| `_prepare_bucket_frame` 全量 | **1.45 ms/帧** | 编辑器同函数 **2.65** |
| ├ `buffer.write` 合计 | **0.103 ms/帧** | 70 次/帧（35 桶 × main+sha），**1.5 µs/次** |
| ├ `vao.render` 合计 | **0.045 ms/帧** | 35 次/帧，**1.3 µs/次** |
| ├ 全局 gather `fw32[order]` | 0.0125 ms | 501 行一次性 gather（2026-11-09 Q8=A 已改） |
| ├ 35 桶 staging 逐桶打包 | 0.050 ms | `st[:k,0:16]` = ... |
| └ **残差（逐桶 numpy/python 调度）** | **≈1.25 ms** | 见下 |

残差来源可直接从源码数出来（`loom_render.py`:682-742）：视锥剔除默认开启（`engine.py`:536），
于是**每个桶**都要走 `keep.sum()` / `np.where(keep)[0]` / `g[:k][sel]` / `sat_k[sel]` / `col_k[sel]`
+ 3 次 staging 赋值 + 2 次 write —— 每桶 7–9 次小数组 numpy 调用，**35 桶 ≈ 250–350 次/帧**。
按实测单次成本（§1.6）就是 0.6–1.2 ms。**不是 Python for 循环体慢，是 numpy 每次调用的固定开销 + 花式索引。**

### 1.5 内核级微基准（真实形状）

| 测量 | 结果 | 来源 |
|---|---:|---|
| `fastpath.aabbs_minmax`（出厂 DLL） | **173–180 Mvert/s**（V=1617/2035/2501/3015，n=90） | `research_04_kernels_micro.py` |
| 同上 V=24 / V=4 | 47 / 0.3 Mvert/s | 小网格被行开销支配 |
| `pipeline_glue.dirty_mask`（n=501） | **0.020 ms/次** | 同上 |
| 501 次属性链抓取（position/rotation/parent） | **0.369 ms（0.74 µs/模型）** | 同上 |
| 同上但直接写 numpy 行 | 0.666 ms | 更慢（逐元素 setitem） |
| `fw32[order]` 501 行 gather | 0.0125 ms | 同上 |
| 单次 concatenate 打包 501×16 f4 | 0.038 ms | 对比逐桶 0.050 ms |

出厂内核 173 Mvert/s ≈ 5.8 ns/顶点 ≈ 20+ 周期/顶点（4 GHz），**说明标量循环没有向量化**
（内层是 if (x<mn) ... else if (x>mx) 依赖链，C:47-65）。

### 1.6 争用敏感性：为什么同一段代码在两个宿主差 2 倍

`research_04_contention.py`（同一进程，只改后台线程压力，6 条 numpy+纯 Python 线程）：

| 阶段 | 无压力 | 6 线程压力 | 放大 |
|---|---:|---:|---:|
| 帧墙钟 | 12.17 ms | 64.02 ms | 5.26x |
| `_prepare_bucket_frame`（`buckets`） | 1.454 ms | 10.512 ms | **7.23x** |
| `_draw_main_buckets`（draw） | 0.259 ms | 0.261 ms | **1.01x** |

`research_04_numpy_gil3.py` 把放大源钉到具体算子（单次 µs，随争用线程数）：

| 算子 | 0 线程 | 1 | 2 | 3 | 4 | 6 | 最大放大 |
|---|---:|---:|---:|---:|---:|---:|---:|
| **花式索引 `w16[idx20]`** | 2.48 | 7.08 | 20.03 | 32.52 | 58.17 | 109.6 | **44x** |
| `np.take`(..., out=, mode='clip') | 1.75 | 4.07 | 15.42 | 40.5 | 59.3 | 96.8 | 55x |
| 切片赋值 `a[:20,:16]=b[:20]` | 1.24 | 1.28 | 1.30 | — | — | 1.29 | 1.04x |
| `np.empty` / copy / `np.where` | 0.78–1.01 | — | — | — | — | 0.81–1.02 | ~1x |
| moderngl `uniform.value=` | 0.796 | — | — | — | — | 0.787 | 0.99x |
| moderngl `buffer.write`(1.4KB) | 1.121 | — | — | — | — | 0.839 | 0.75x |

即：**被放大的是"按索引取数"这一类 numpy 路径（内部走缓冲迭代器/分配），不是全部 numpy，
也不是 GL 调用**。这精确解释了 `buckets` 的 2.65（编辑器，有 2–3 条忙线程）vs 1.45（播放器），
也说明"把 35 桶的花式索引合并成 1 次全局 gather + 1 次 C 打包"在**争用环境下收益会翻倍**。

### 1.7 多绘间接（Q4 的可行性前沿）

本机实测（`research_04_indirect_probe3.py`，NVIDIA GTX 1050 Ti / 驱动 582.78）：

| 检查项 | 结果 |
|---|---|
| moderngl 5.12 是否有间接绘制 | **有**：`VertexArray.render_indirect`(buffer, mode, count, first)（`moderngl/__init__.py:1370-1378`） |
| 索引缓冲（→ `glMultiDrawElementsIndirect`） | **可用**：命令缓冲 [`count, instanceCount, firstIndex, baseVertex, baseInstance`] 5×int32，**回读像素验证真的画出来了** |
| 无索引缓冲（数组间接） | **可用**（同样像素验证通过） |
| 3.3 上下文是否可用 | **可用**（`GL 3.3`/4.3/4.6 三种上下文均成功；NVIDIA 驱动在 3.3 core 下仍解析 4.3 入口） |
| `gl_DrawID`（4.6/ARB_shader_draw_parameters） | 仅 4.6 上下文可编译；引擎请求的是 **3.3 core**（`loom_glfw_window.py`:123-126） |
| 一次 indirect 能跨几个 VAO | **只能 1 个**：moderngl 无 multi-VAO 间接；35 桶是 35 个 VAO（`loom_model_gpu.py`:218-229） |
| wgpu（VK 后端） | 有 `draw_indirect` / `draw_indexed_indirect`（`wgpu/_classes.py:1894/1928`），**没有 multi-draw**；VK 侧现在就是每桶一次 rp.draw(...)（vk_renderer.py:1942/1984/2053） |

**结论**：GL 侧要用上多绘间接，必须先把 35 个桶**合并成一个 VAO**（合并 VBO + baseVertex，
实例数据进同一缓冲，材质参数进 per-instance 字段或按 `gl_DrawID` 查表 → 要 4.6 上下文），
且**贴图**（albedo/normal/env 每桶不同）需要 texture array / bindless。
而可省的 CPU 开销上界 = 35 × 1.3 µs + 每桶 6 次 uniform（≈0.21 ms）≈ **0.26 ms/帧（约占帧时间 2%）**。

---

## ② 目标设计（含数据/接口草案）

### 2.1 设计原则

1. **先问"该不该在 Python 里"，再问"该不该在 C 里"。** 本次证据显示：C 内核本身不慢，慢的是
   ①逐体属性抓取装配 ②逐桶小数组调度 ③跨线程 GIL 交接。
2. **不新增第 6 个 DLL。** 全部候选塞进既有 `ckernels`（`loom_kernels.c`）或既有官方组件，
   复用 `loom_module.h` 契约 + `registry.json` 声明，避免打包/自检面扩大。
3. **逐位一致是硬约束**（现有对拍基线 `aabb_par_check.py` / `pipeline_val_check.py` / snap 对拍）。
   C 侧禁用 FMA 折叠与求和重排；跨顶点向量的 SIMD 是安全的（每个顶点的表达式顺序不变，min/max 精确）。
4. **GIL 只在"进 C 前取一次、出 C 后放一次"。** 目标是把每帧 ~300 次 GIL 进出压到 2–3 次。

### 2.2 候选内核 A：桶打包（`loom_bucket_pack`）

把 `loom_render.py`:664-742 的"全局 gather → 逐桶切 → 视锥剔除 → staging 交错 → 写缓冲"合成一次 C 调用。

    /* 输入: 纯数值平面, 全部 caller-owned / C 连续 (与 `loom_collide_pairs` 同风格) */
    /* w32   : (n,16) f32  世界矩阵 (已 f32 化, 逐行)
     * order : (n,) i64    全局 gather 顺序 (桶拼接序)
     * offs  : (K+1,) i64  每桶在 order 中的区间
     * planes: (6,4) f64   视锥 6 平面 (已归一; NULL = 不剔除)
     * rad   : (n,) f64    逐实例剔除半径
     * sat   : (n,) f32 ; col : (n,4) f32
     * OUT main_inst (n,24) f32 = world16 + sat + pad + col
     *     sha_inst  (n,16) f32 = world16
     *     main_n    (K,) i32 每桶主 pass 实例数 (剔除后已重排到桶段前部) */
    int `loom_bucket_pack`(const float *w32, int64_t n, const int64_t *order,
                         const int64_t *offs, int32_t K, const double *planes,
                         const double *rad, const float *sat, const float *col,
                         float *main_inst, float *sha_inst, int32_t *main_n);
    /* rc: 0 成功; 1 参数非法; 2 容量不足 (调用方扩容重试, 语义同 `collide_pairs`) */

Python 侧只剩 3 步（伪代码）：

    G = `fw32[order]`                       # 1 次 numpy gather (0.0125 ms)
    `loom_bucket_pack`(G, order, offs, planes, rad, sat, col, main_buf, sha_buf, main_n)
    for k in `buckets`: main_buf.write(main_view[k]); sha_buf.write(sha_view[k])   # 70 次, 0.10 ms

**验收口径**：与现行 Python 路径**逐字节相同**（main_inst/sha_inst 直接做 `bytes` 比较，
不要只比渲染图）；并保持"相机静止 + 结构不变时命中脏闸整段跳过"（`loom_render.py`:540-541）不变。

### 2.3 候选内核 B：物理桥脏检测装配（`loom_pose_sync`）

现状：`_dirty_mask_batch` 每逻辑帧 2.18 ms，其中 >90% 是 Python 对象抓取与容器构造（§1.3）。
引擎**已经有 SoA 平面**：`_transform_snapshot` 产出 pos/rot/scl（`loom_transform.py`:62-118），
父链索引由 `_render_parent_depth` 提供（`loom_transform.py`:141）。

    /* cur_rows : (n,6) f64  pos(xyz)+rot(xyz), 可直接来自 `_soa_snap` 的 pos/rot 平面
     * old_rows : (n,6) f64  桥自持的 SoA 同步基线平面 (替换 dict[int,list])
     * pidx     : (n,) i64   父行下标 (-1 = 无父)
     * out_mask : (n,) u8
     * 语义与 `pipeline_glue.dirty_mask` 完全一致 (它就是现成内核); 新增的只是把
     * "祖先传播 + sync 平面推进"也放进 C, 免去 Python 侧 n 次 round-trip。 */
    int `loom_pose_sync`(const double *cur_rows, double *old_rows, const int64_t *pidx,
                       int64_t n, uint8_t *out_mask);   /* 原地推进 old_rows */

配套数据结构改动（草案）：

    # 现在: self.`_last_sync`: dict[int(id), [tuple3, tuple3, tuple3]]   (`physics_bridge.py`:975-982)
    # 目标: self._sync_rows: (cap,6) f64 + self._row_of_id: dict[int,int] (仅结构变更时重建)
    #        + self._sync_ids: (cap,) i64 (身份校验, 复用现有 `_entry_signature` 失效面)

**语义红线**：`_last_sync` 现在的键是 id(m)，注释写明"id 复用后会让新体被误判未动"
（`physics_bridge.py`:933-935、966-971）。换行下标必须保留**同一失效面**（结构 stamp + 对象 id 快照），
否则会复活 P2-⑧ 的 bug。

### 2.4 候选内核 C：AABB 内核 SIMD 化（既有 C 的优化，不是下沉）

已在研究版 DLL 中实测（`research_04_simd_bench.c` + `research_04_simd_run.py`）：

| 形态 | 出厂标量 | AVX2（4 顶点/轮，无 FMA） | 加速 | 逐位 |
|---|---:|---:|---:|---|
| V=2035, n=90 | 1.057 ms (173 Mvert/s) | 0.462 ms (396 Mvert/s) | **2.29x** | **一致** |
| V=1617, n=90 | 0.807 | 0.366 | 2.20x | 一致 |
| V=24, n=501 | 0.130 | 0.054 | 2.40x | 一致 |
| V=4, n=501 | 0.032 | 0.032 | 1.00x | 一致 |

实现要点：**只做跨顶点并行**（同一顶点的 x=((a*m00+b*m10)+c*m20)+d*m30 顺序一字不改），
min/max 用 `_mm256_min_pd/max_pd`（精确、与顺序无关）→ 天然逐位一致。
需要 **CPUID 运行时分派**（出厂 DLL 要跑在无 AVX2 的机器上），并保留标量回退路径。

---

## ③ 分步落地计划（每步可验收、含测试点）

> 排序 = 收益/成本比。每步单独可回滚（都是"新导出 + 开关"形态，开关默认关 → 灰度 → 默认开）。

### 步骤 0（P0，先做）：把 `pipe_wait` / `mt_mp_draws` 变成"可观测"

- **做什么**：①给物理线程三段加插桩（`LOOM_PROFILE` 门控），落到 `pt_pre_step` / `pt_dirty` / `pt_step` / `pt_post` / `pt_ensure`；②把 `_draw_main_buckets` 拆成 `mt_mp_draws_uniform` / _tex / _render 三段。
  依据：目前 phys_bridge_* 只覆盖串行降级路径（§1.3），且 draw 段 1.5 vs 0.26 未闭合（附录 B）。
- **验收**：编辑器播放态 `sum(pt_*)` ≈ `pipe_wait`（误差 < 20%）；三 draw 子段之和 ≈ `mt_mp_draws`（误差 < 10%）；关 `LOOM_PROFILE` 零开销。
- **测试点**：`research_04_bridge_glue.py` 改造成回归探针；tests/`test_physics_pipe_errors.py` 全绿。
- **成本**：1.0 人天。

### 步骤 1（P0）：`loom_bucket_pack`（候选 A）

- **做什么**：加 C 导出 + fastpath ctypes 包装，默认 `LOOM_BUCKET_PACK`=0，A/B 用；视锥剔除与 staging 交错一次算完；main_n 回传，Python 侧不再逐桶 `np.where`/sel。
- **验收**：①main_inst/sha_inst 与旧路径 **`bytes` 逐字节相同**（501 实例、剔除开/关两档）；②`buckets` 段：编辑器 2.65 → **≤1.0 ms/帧**（播放器 1.45 → ≤0.5）；③争用档（`research_04_contention.py` B 相）不出现 >2x 放大。
- **测试点**：新增 tests/`test_bucket_pack_bitexact.py`（纯 numpy 桩，不需要 GL：喂合成 w32/order/offs/planes 对比 Python 参考实现的输出字节）；渲染等价用既有 tests/`test_vk_bucket_order.py` + GL/VK 截图 A/B。
- **成本**：2.5–3.5 人天。

### 步骤 2（P1）：物理桥 SoA 通道 + `loom_pose_sync`（候选 B）

- **做什么**：桥改吃 (n,6) 位姿平面（来自 `_soa_snap`）+ 父下标；`_last_sync` 改 SoA 行表（保留 id 失效面）。
- **验收**：①脏集合与现行实现**逐位一致**（同一帧对拍 `_dirty_mask_batch` 返回值）；②物理线程每逻辑帧 Python 时间 ≤4 ms（现 ~10.4）；③编辑器 `pipe_wait` 3.99 → **≤2.0 ms/帧**，TPS 不下降。
- **测试点**：tests/`test_physics_bridge.py`（23 KB，覆盖祖先传播/挂父/重建）+ 新增 tests/`test_physics_dirty_soa.py`（id 复用、reparent preserve_world、增删体三类回归）。
- **成本**：3–4 人天（含失效面复核）。

### 步骤 3（P2）：AABB 内核 SIMD（候选 C）

- **做什么**：`_aabb_one_row` 的跨顶点向量化 + 运行时分派；`fastpath.aabbs_minmax` 签名不变。
- **验收**：`mt_aabb_minmax` 1.38 → **≤0.7 ms/帧**；与旧 DLL 输出**逐位一致**（全场景 5 万行对拍）；无 AVX2 时自动走标量（`LOOM_NO_SIMD`=1 模拟验证）。
- **测试点**：tests/_tmp/`aabb_par_check.py`（现有对拍）+ 新增"逐位"断言；pipeline_val_check 不受影响。
- **成本**：1–1.5 人天。

### 步骤 4（P3，观察项）：`mt_dispatch` 与 `_aabbs_batched` 组装段

- **做什么**：先只加子段插桩（事件派发里"筛选/去重" vs "脚本回调"），再决定是否把筛选向量化。
- **验收**：给出 1.6 ms/逻辑帧的内部切分；若回调占比 >60% 则**明确不优化**。
- **成本**：0.5 人天（只测量）。

---

## ④ 风险与回滚

| 风险 | 具体形态 | 缓解 | 回滚 |
|---|---|---|---|
| **逐位不一致**（最高） | C 打包/SIMD 改变字节 → 阴影/主 pass 像素差 | 对拍用 `bytes` 而非图像；C 禁 /fp:fast、禁 FMA 折叠；SIMD 只跨顶点 | 开关 LOOM_* 回旧 Python 路径（保留旧实现一版） |
| 失效面重写引入幽灵 | 物理桥 id→行下标改造复活 P2-⑧（id 复用误判"未动"） | 保留 `_entry_signature` + 结构 stamp + id 快照三重判据；专门回归用例 | 桥保留 `_last_sync` dict 作为影子，双写比对一版 |
| 出厂 DLL 哈希/自检失败 | `ckernels` 在 `registry.json` 有 provides + sha256，`official_manifest.py`:20-23 钉死；`diag_check_dll_integrity` 会报 modified | 重编后跑 tests/_tmp/`gen_official_manifest.py` 重生成基准；开发期 `LOOM_DEV`=1 跳过校验 | 还原 DLL + registry + manifest 三件（版本库内） |
| 打包漏带 | `package_engine_compiled.py`:42 的 DATA_DIRS 已含 `ckernels`；`build_game.py`:235-236 同 | 发版前 compiled_verify / boot_check | 无（只增导出，不改路径） |
| 调度抖动 | 打包改成 C 后单帧 2 ms 的 C 段若放主线程，可能形成新长段 | 保持现有"每帧一次"粒度；必要时按桶分段（K 很小） | 开关 |
| 过度优化错靶 | 若编辑器 `mt_mp_draws` 1.5 ms 实为 GPU 背压，则任何 CPU 侧改动都无效 | **步骤 0 先闭合测量**，再决定是否动 draw 路径 | 不投入即无风险 |

---

## ⑤ 工作量估计（人天 / 会话数）

| 步骤 | 内容 | 人天 | 会话数 | 风险等级 |
|---|---|---:|---:|---|
| 0 | 物理线程插桩 + draw 三分插桩（闭合本报告两个未闭合项） | 1.0 | 1–2 | 低 |
| 1 | `loom_bucket_pack`（C + ctypes + 逐字节对拍 + 开关） | 3.0 | 3–4 | 中 |
| 2 | 物理桥 SoA + `loom_pose_sync`（含失效面复核与回归） | 3.5 | 4 | **中高** |
| 3 | AABB SIMD + 运行时分派 | 1.2 | 1–2 | 低 |
| 4 | 发版配套（manifest/registry/打包/编译版验证） | 1.0 | 1 | 低 |
| — | **合计（不含多绘间接）** | **≈9.7 人天** | **10–13 会话** | |
| ✗ | （不推荐）多绘间接：合并几何 + 材质表 + 纹理数组 + GL4.6 + VK 分支 | 10–15 | — | 高 |

预期收益汇总（编辑器口径，帧 11.5 ms / 主线程 7.17 ms）：

    `buckets`   2.65 → ~0.8   (−1.85 ms/帧, 争用下更明显)
    `pipe_wait` 3.99 → ~2.0   (−2.0  ms/帧, 依赖步骤 2)
    aabbs     2.24 → ~1.45  (−0.79 ms/帧, 步骤 3)
    ────────────────────────────────────
    合计 ≈ −4.6 ms/帧 的主线程/同步开销 → 87 FPS 场景有 ~40% 余量可换成 GPU 侧效果

---

## ⑥ 与现有代码的兼容边界

| 边界 | 现状（证据） | 本设计如何不破坏 |
|---|---|---|
| `ckernels` ABI 契约 | `loom_module.h` 七导出 + provides（`registry.json`: `ckernels`.aabbs / `ckernels`.collide） | **只追加**导出，不动既有签名/求和序（与 `pipeline.dll` 追加 `dirty_mask` 的做法一致，registry note 已写明"末尾无侵入追加"） |
| fastpath 硬加载 | B1 退役后 DLL 缺失 = 模块级 raise（`fastpath.py`:84-87） | 新导出必须与 DLL 同批发布；旧 DLL + 新 Python 会 AttributeError → 用 `hasattr` 探测 + 明确错误信息 |
| 出厂哈希 | `official_manifest.py`:20-23 钉 `ckernels` sha256；`LOOM_DEV`=1 跳过 | 每次重编跑 `gen_official_manifest.py`，与 DLL 同 commit |
| 打包链 | `package_engine_compiled.py`:42（DATA_DIRS 含 `ckernels`）、`build_game.py`:235-236 | 无需改动；发版需重跑 `compiled_verify.py` |
| 逐位基线 | aabb_par_check / `aabb_assembly_check` / pipeline_val_check / snap 对拍（`loom_render.py`:604-609 注释里的"逐位同一字节"） | 新内核以"字节相等"为验收，不以"看起来一样" |
| 测试面 | 121 个 tests/test_*.py；相关：`test_physics_bridge.py`(23KB)、`test_physics_pipe_errors.py`、`test_vk_bucket_order.py`、`test_render_api.py` | 每步先跑对应测试文件，再跑全量 |
| 脏闸语义 | `_bucket_frame_sig` 四维（stamp/keys/pose/cam，`loom_render.py`:520-541） | 打包内核只在"闸开"时调用，闸判不动 |
| 视锥剔除开关 | `_frustum_cull` 默认 True（`engine.py`:536） | 内核必须同时支持 planes=NULL（不剔除）两档 |
| GIL 假设 | 引擎把 switch interval 调到 1 ms（`loom_logic_thread.py`:41-45），注释记录了"渲染段慢 2x" | 新 C 段天然不持 GIL，与 1 ms 间隔互补，不冲突 |

---

## ⑦ 需要人类裁决的封闭问题

| # | 问题 | 选项 | 主审倾向（基于实测） |
|---|---|---|---|
| Q1 | beta6 是否**动 C 内核**（会重编 DLL + 改出厂哈希 + 需编译版复验）？ | A 不动，只做 Python 侧 / B 只做 AABB SIMD（最小面）/ C 做 `buckets`+物理桥（收益最大） | **C**（−4.6 ms/帧，回滚成本低） |
| Q2 | 物理桥 SoA 改造（唯一"中高"风险项）是否本版做？ | A 做 / B 先只做步骤 0 插桩，观察一版再定 | **B**（先用一版数据确认 `pipe_wait` 构成，再动语义面） |
| Q3 | `buckets` 打包内核放 `ckernels`（数学内核目录）还是 `pipeline.dll`（逻辑帧 prep 组件）？ | A `ckernels` / B pipeline | **B**（语义贴 pipeline：都是"每帧数据准备"，也避免 `ckernels` 变杂物间） |
| Q4 | 多绘间接：**本轮明确不做**，是否接受？ | A 接受，写入"不必要下沉清单" / B 仍要预研 GL 侧原型 | **A**（上界 0.26 ms/帧，VK 无 multi-draw，必然后端分叉） |
| Q5 | 是否允许把"SIMD 运行时分派"引入出厂 DLL（增加 CPU 判定分支）？ | A 允许（AVX2+标量两路）/ B 只允许 SSE2（x64 基线，约 2x）/ C 不 SIMD | **A**（2.3x，逐位已验证；无 AVX2 自动回退） |
| Q6 | 验收是否统一改为"**字节级相等**"（而非阈值/截图）？ | A 是，写入 beta6 验收口径 / B 沿用图像 A/B | **A**（代码注释里已多处承诺"逐位同一字节"，只是没测试固化） |
| Q7 | 若步骤 0 测出 `mt_mp_draws` 的 1.25 ms 差额是 **GPU 背压**，是否放弃 draw 侧优化整条线？ | A 放弃 / B 转去做"减少 GL 状态切换" | **A**（那就不是语言问题，是管线/带宽问题） |

---

## 附录 A：可复现证据索引（探针均 gitignore，未改受跟踪文件）

    cd 'D:\my-project - 副本\Loom(py源代码-工作区)\Loom'

    # A. 编辑器分段（权威口径, 产物 tests/_tmp/`mt_profile_on_r04.json`）
    py -3.12 tests/_tmp/`mt_profile_check.py` --scene 压测500混合.json --secs 6 --suffix _r04

    # B. 物理桥 Python 粘连层真实耗时（物理线程, 计时包装）
    py -3.12 tests/_tmp/`research_04_bridge_glue.py` 120          # -> research_04_bridge_glue.json

    # C. `buckets` / draws A/B 切分（write 代理 vs no-op, draw 代理 vs no-op）
    py -3.12 tests/_tmp/`research_04_ab_split.py`                 # -> research_04_ab_split.json

    # D. 争用放大（同进程只改后台线程压力）
    py -3.12 tests/_tmp/`research_04_contention.py`               # -> research_04_contention.json
    py -3.12 tests/_tmp/`research_04_numpy_gil3.py`               # 花式索引随线程数 2.5->110 us

    # E. 函数级 cProfile（会跨线程采样, 数字被放大, 只用相对排序）
    py -3.12 tests/_tmp/`research_04_cprofile.py` 60              # -> research_04_cprofile.json

    # F. 内核微基准 + SIMD 对照（需 MSVC; dll 已在 tests/_tmp）
    py -3.12 tests/_tmp/`research_04_kernels_micro.py`            # 出厂内核吞吐 / `dirty_mask` / 属性抓取
    py -3.12 tests/_tmp/`research_04_simd_run.py`                 # 标量 vs AVX2 逐位对拍

    # G. 多绘间接可行性（回读像素验证）
    py -3.12 tests/_tmp/`research_04_indirect_probe3.py`

| 结论 | 证据文件 | 关键行 |
|---|---|---|
| 桶打包循环 | `Loom/loom_render.py` | 682-742 |
| 桶绘制循环（每桶 uniform+draw） | `Loom/loom_render.py` | 744-805 |
| `mt_mp_draws` 插桩点 | `Loom/editor.py` | 2337-2339 |
| `pipe_wait` 插桩点 | `Loom/engine.py` | 1226-1227 |
| 逻辑帧 prep | `Loom/engine.py` | 1232-1234 |
| 脏检测装配 | `Loom/physics_bridge.py` | 988-1071 |
| `pre_step` | `Loom/physics_bridge.py` | 1079-1106 |
| 物理线程主循环 | `Loom/physics_pipe.py` | 63-84 |
| AABB 公共层 + 记忆化 | `Loom/loom_lighting.py` | 248-442 |
| AABB 批量化/分组 | `Loom/loom_lighting.py` | 444-473+ |
| AABB C 内核（标量内层） | `Loom/ckernels/loom_kernels.c` | 47-79 |
| C ABI 包装 | `Loom/fastpath.py` | 68-80 |
| 桶 VAO/实例缓冲格式 | `Loom/loom_model_gpu.py` | 186-229 |
| GL 3.3 core 上下文 | `Loom/loom_glfw_window.py` | 123-126 |
| 出厂哈希钉扎 | `Loom/core_components/official_manifest.py` | 20-23 |
| 组件声明 | `Loom/core_components/registry.json` | `ckernels` 条目 |
| 打包目录 | `tools/package_engine_compiled.py` | 42 |
| DLL 编译参数 | `Loom/ckernels/build_ckernels.bat` | 全文件 |
| GIL 切换间隔处理 | `Loom/loom_logic_thread.py` / `Loom/engine.py` | 41-45 / 519-527 |

## 附录 B：本次测量未能闭合的两点（诚实登记）

1. **编辑器 `mt_mp_draws` 1.51 ms vs 播放器同函数 0.26 ms（5.8x）**：
   已排除：Python 逐桶 uniform 赋值（6×35 次，实测 0.99 µs/次）、`vao.render`（1.3 µs/次）、
   `buffer.write`、GIL 争用（draw 循环在 6 线程压力下 1.01x 不变）。
   **未排除**：Qt paintGL 目标 FBO 的驱动状态/背压、编辑器 program 的 sampler 集合差异。
   解法 = 步骤 0 的三分插桩。
2. **`pipe_wait` 11.6 ms vs 物理线程可归因 ~10.4 ms**：残差 1–2 ms 疑为线程唤醒/交接延迟，
   需步骤 0 的物理线程插桩在同一窗口内闭合。

---

## 附录 E：3.13 下物理路径 FPS 退化的定位（2026-11-09，1 会话，只定位不修）

> 触发：R06 实测 3.12→3.13 后满载 FPS 84.2~88.8 → 79.5~80.3，logic_step / pipe_wait 同时变大。
> 本附录记录**同机同场景**的复现、函数级定位，以及"是什么 / 不是什么"的判据。探针同属 gitignore。

### E.1 复现（本机，压测500混合，300 帧，与 build_entry._bench_scene 同口径）

| 版本 | FPS | 帧时间 | logic_step | pipe_wait | aabbs | world_matrices | buckets | collide_pairs |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| 3.12.10 | **86.5** | 11.56 ms | 3.82 | 2.56 | 0.81 | 0.54 | 1.32 | 1.42 |
| 3.13.15 | **73.4** | 13.63 ms | 5.23 | 3.66 | 1.02 | 0.84 | 1.38 | 1.47 |

方向与 R06 一致（本机跌幅更大；多次运行落在 -5% ~ -15%，说明对调度状态敏感）。
**C 侧不背锅**：`collide_pairs`（C）+3.5%、`br.step`（Jolt）+0.4%、`interp`（C DLL）甚至 -11%；
`buckets` / `_draw_main_buckets`（只在主线程）+4.5% / +2.9%。**退化集中在逻辑线程/物理线程上的 Python 代码。**

### E.2 函数级差异 top 10（perf_counter 计时包装，非 cProfile；µs/次，同场景同帧数）

| # | 函数 | 3.12 | 3.13 | Δ | 所在线程 | 性质 |
|---|---|---:|---:|---:|---|---|
| 1 | `update_animations` | 17.3 | 42.3 | **+145%** | 主线程* | 纯 Python 循环（绝对值小） |
| 2 | `_transform_snapshot` | 526.6 | 734.6 | **+39.5%** | 主线程* | 501×属性链 + 逐元素 SoA 写 |
| 3 | `_refresh_free` | 84.7 | 117.2 | **+38%** | 物理 | [m for m in models if ...] |
| 4 | `compute_world_matrices` | 593.8 | 809.6 | **+36.3%** | 主线程* | numpy 批量 + 上述快照 |
| 5 | `_run_scripts` | 876.9 | 1044.6 | +19.1% | 主线程* | 脚本回调 |
| 6 | `_dispatch_fixed_update` | 127.5 | 151.5 | +18.8% | 主线程* | 事件派发 |
| 7 | `br.pre_step` | 3252.8 | 3632.3 | +11.7% | 物理 | 脏检测装配（§1.3 那段） |
| 8 | `br._dirty_mask_batch` | 2568.6 | 2828.2 | +10.1% | 物理 | 501×属性链抓取 |
| 9 | `pipe.wait_pending` | 8395 | 9055 | +7.9% | 主线程 | 等物理（GIL 交接的直接账单） |
| 10 | `_prepare_bucket_frame` | 1347.4 | 1407.4 | +4.5% | 主线程 | 纯主线程，几乎不受影响 |

对照组（**没有**退化）：`_aabbs_batched` +1.4%、`_logic_prep` +0.1%、`_model_aabbs_par` +1.4%、
`br.ensure_models` +3.1%、`br.post_step` -5.7%。它们要么是 numpy 主循环、要么是 C 调用。

### E.3 关键否证：**不是** specializing interpreter / 类型不稳定

三条独立证据都指向"单线程下 3.13 更快"：

1. **停掉全部引擎线程、关 GC 后，同批访问器 3.13 全部更快**（research_04e_bisect.py，501 模型）：
   m.position（2 跳 property）223.3 → **130.8 µs**；m.transform.position 104.8 → 67.6；
   m.position.x（property+namedtuple 字段）207.3 → 145.3；m.scale 333.9 → **133.9**；id(m) 106.7 → 35.6。
2. **合成属性链基准**（research_04e_propchain.py，同形态 2 跳 property + namedtuple）：
   3.12 191.0 µs → 3.13 **174.6 µs**（更快）。
3. **namedtuple 字段访问没有退化**：两版本 Point3D.x 都是 C 层 collections._tuplegetter
   （实测 30.1 → 25.3 µs），排除"3.13 把 tuplegetter 改成 Python 实现"这条常见猜测。
4. 微基准全家桶（属性 / dict / getattr / 循环 / numpy 花式索引 / ctypes 空调用）3.13 一律持平或更快
   （属性 -11%、循环 -9%、list.append -13%；numpy 花式索引 2.55→2.66 µs，切片 0.32 vs 0.32）。

⇒ 早前"真实访问器慢 4~7x"的观测是**线程争用污染的墙钟**，不是代码退化；已作废并在此登记。

### E.4 真正的机制：**跨线程 GIL 交接变贵**（本报告最有价值的结论）

| 判据 | 3.12 | 3.13 | 说明 |
|---|---:|---:|---|
| 两线程 Event 乒乓（research_04e_gil.py，2 万轮） | **51.25 µs/次** | **93.56 µs/次** | **+83%**，同机同脚本 |
| 纯 Python 互抢放大 | 1.79x | 1.56x | GIL 公平性没变差 |
| ~~关掉逻辑线程（`LOOM_LOGIC_SYNC=1`）后 FPS~~ | ~~85.3~~ | ~~82.6~~ | **已作废（E.7）**：bench 宿主根本没有逻辑线程，该开关在此入口是空操作 |
| 全进程 CPU/帧（research_04e_cpu.py，GetThreadTimes） | 12.66 ms（1.08 核） | **14.45 ms（1.17 核）** | 不是干等，是**多烧 14% CPU** |
| 同上分线程：MainThread / loom-physics / 8 池 | 7.27 / 2.50 / 1.16 | 7.66 / **2.89** / **1.72** | 物理线程 +16%、池线程 **+48%** CPU |

即：3.13 每次 GIL 交接/唤醒更贵，而引擎恰好是"主线程 + 逻辑线程 + 物理线程 + 8 池"的高频交接结构
（逻辑线程 1 ms 轮询 loom_logic_thread.py:100-128；物理线程每子步 post→wait），
账单一层层叠在 pipe_wait 与逻辑帧装配段上——这解释了"变慢的全是 Python 密集段"。

**试过但无效（登记，别重复尝试）**：
- 切换间隔扫描 1/2/5/10 ms（research_04e_switch.py；3.13：75.3/75.0/76.4/73.2 FPS）——无趋势。
  说明代价在 **acquire/wake 路径**，不在时间片长度。
- 逻辑线程轮询睡眠 1 ms → 4 ms（research_04e_fix_ab.py；3.13 76.5→78.0→72.3）——落在噪声内；
  3.12 同档 88.6/88.4/89.7 证明探针稳定，是 3.13 侧方差大。

### E.5 最小修法评估（均无需改业务代码即可先验证）

| 方案 | 代价 | 预期 / 实测 | 判定 |
|---|---|---|---|
| A. 运行时 `LOOM_LOGIC_SYNC=1`（已有开关） | 零代码 | ~~3.13：73.4 → 82.6~~ **数据作废（E.7）**：该开关只在`_external_ctx=True` 的宿主（编辑器/播放窗口）才真正移除逻辑线程；在 `--bench` 宿主上无效果，两份`--bench` 数据都是负载噪声 | **需在编辑器路径重测后再判**；不建议改默认 |
| B. 降交接频次：缩短物理线程 Python 段（R04 §③ 步骤 2 的 `loom_pose_sync` / SoA） | 3.5 人天 | pre_step 2.9 ms → ~0.4 ms，交接窗口同缩；预计 pipe_wait 3.66 → ~2.6、logic_step 回 ~3.8 | **正解，属批次 D**——本报告确认它同时是 3.13 的最优解 |
| C. 逻辑帧装配段（`_transform_snapshot` / `compute_world_matrices`）也改吃 SoA 平面 | 1.5 人天 | 逻辑线程 Python 时间 -30~40%，交接次数不变但每次窗口更短 | 可与 B 合并 |
| D. 调 switchinterval / 加大轮询睡眠 | — | 实测无效（E.4） | **不做** |
| E. 等 CPython 侧（3.14 free-threading / GIL 优化） | 外部 | 3.14 才有 free-threading 正式版 | 记入"版本升级预研"清单 |

### E.6 结论（一句话）

**3.13 的退化不是某个函数被去优化，而是跨线程 GIL 交接成本 +83% 在"高频交接架构"上的复利**；
函数级"变慢"是墙钟表象（单线程实测 3.13 更快）。可低成本缓解的运行时开关在**编辑器路径**尚待重测（bench 上的 82.6 已作废，见 E.7）；**根治要等批次 D 把物理桥/逻辑帧装配层改成 SoA + 单次 C 调用**
（与 R04 的 P1/P2 是同一件事，做一次两边都赚）。在此之前**不建议**为 3.13 单独打补丁。

> 环境说明（2026-11-09 复核后更新）：两版本现均为 **numpy 2.5.4 / moderngl 5.13.0**（批次 0 已升级，实测确认）。为排除该混淆：E.3 第 4 条的 numpy 微基准显示两版本算子耗时差 <5%，
> 且 E.4 仍然有效的证据（乒乓、线程 CPU 分解、E.3 的单线程对照）都不依赖 numpy 版本。

### E.7 更正记录（复核 R06 的反例，2026-11-09 追加）

**R06 反例成立，我附录 E 的第 3 条证据作废。** 逐条核对：

1. **场景/入口**：我当时跑的是 `cd Loom; py -3.13 Loom.py --bench 压测500混合.json 300`
   （= `Loom/压测500混合.json`，与 `Loom/Projects/压测500混合.json` **SHA256 完全相同**：
   `208E43E4…66C4488`，所以场景不是差异源）。入口就是 `--bench`（转 `build_entry._bench_scene` → `runtime.PlayerApp`）。
2. **其它环境变量**：当次只设了 `LOOM_LOGIC_SYNC=1`；`LOOM_PROFILE` 由 `_bench_scene` 自身 setdefault。**但这不是重点**。
3. **82.6 是 FPS**（bench 自己算的 `n_frames/wall`，同一行还有 TPS 30.10），没有读错列。
4. **真正的问题：这个开关在 `--bench` 宿主上是空操作。**
   - `engine.py:1478`：`if self._logic_async and getattr(self, '_external_ctx', False): self._start_logic_thread(clk)`
     —— 逻辑线程要求 `_external_ctx=True`（编辑器/播放窗口），`PlayerApp` 走 GLFW 自持上下文，**从来不建逻辑线程**；
   - `loom_render.py:851`：`is_async_active = _logic_async and _external_ctx` → 两种取值下都为 False，逻辑一律在渲染线程内联跑；
   - 实测线程表（`research_04e_sync_probe.py`，3.13）：无论 `LOOM_LOGIC_SYNC` 有无，
     `threads = [MainThread, loom-physics, loom-scripts, loom-sched-0..2, ThreadPoolExecutor-0_0..7]`，**没有 loom-logic**。
   ⇒ 我用"`--bench` + 开关`"测"去掉逻辑线程"，测的是一个不存在的线程，数值差只能是运行间噪声。
5. **自证噪声**：复核时同一命令、同一工作树重复跑，符号翻转——
   `--bench` 无 env：FPS **31.4**（logic_step 17.26、pipe_wait 11.32）；`--bench` 加 `LOOM_LOGIC_SYNC=1`：FPS **81.8**（logic_step 4.33）。
   与"先前 73.4 → 82.6"方向相反；直接探针（无 bench 头）两种设置都只有 ~21.7 FPS。
   结论：**本机这段时间被并行任务压着，两次 bench 之间不可比**（同配置重跑可差 2.5x）。

**E.4 更正后只剩三条支撑**（主结论仍成立，但证据结构要改口径）：

| 仍有效的证据 | 数值 | 为什么它不受上面问题影响 |
|---|---|---|
| GIL 交接乒乓 | 51.25 → **93.56 µs/次（+83%）** | 纯两线程、无引擎、无负载假设；唯一变量是解释器 |
| 全进程 CPU/帧 + 分线程 CPU | 12.66 → **14.45 ms/帧（+14%）**；loom-physics +16%、8 池合计 **+48%** | 同进程 GetThreadTimes，与 FPS 噪声解耦；说明是"多烧 CPU"而非"干等" |
| 单线程下 3.13 更快（E.3 全部四条） | 访问器 1.5~2.5x 更快 | 停线程 + 关 GC 后测，排除争用 |

另外两条**间接**支撑保留但要降级表述：C 侧段不退化（Jolt +0.4%、collide +3.5%、interp −11%）而
Python 密集段与"跨线程汇合点"（`pipe_wait` +7.9%/次）同向变差；以及 3.13 侧帧时方差显著更大（p99 25→34 ms）。

**E.2 线程列的更正**：`--bench` 宿主无逻辑线程，所以 E.2 里
`compute_world_matrices` / `_transform_snapshot` / `_run_scripts` / `_dispatch_fixed_update` / `update_animations`
实际都在**渲染线程内联**执行（已改为"主线程*"）。只有 `pre_step` / `_dirty_mask_batch` / `ensure_models` / `post_step` 在 `loom-physics`。
这也意味着：本次能确证的是**渲染线程 ↔ 物理线程**这条交接；**逻辑线程那条（编辑器/播放窗口路径）本次没有测到**。

**要验证"逻辑线程交接"这件事，正确入口是编辑器/播放窗口路径**（`_external_ctx=True` 才会起 `loom-logic`）：

    cd 'D:\my-project - 副本\Loom(py源代码-工作区)\Loom'
    # A/B 各跑一次, 先确认线程表里出现/消失 loom-logic
    $env:LOOM_LOGIC_SYNC='1'; py -3.13 tests/_tmp/mt_profile_check.py --scene Projects/压测500混合.json --secs 12 --suffix _r04e_sync
    Remove-Item Env:LOOM_LOGIC_SYNC; py -3.13 tests/_tmp/mt_profile_check.py --scene Projects/压测500混合.json --secs 12 --suffix _r04e_async
    # 每次先看 tests/_tmp/mt_profile_on_*.json 的 derived/ms_per_frame; 两组都要在**空载**机器上跑

**建议 R06 复测口径**：同一台机、同一次会话内交替跑 async/sync 各 3 轮取中位数，且记录
`threads` 快照与 `p50/p99`；否则 ±10 FPS 的负载噪声足以把结论翻面（本次已实证）。

---

## 附录 F：批次 D1 落地记录（P0 插桩闭账 + P1 loom_bucket_pack，2026-11-10）

> 口径：所有数字同机实测（3.13.15 主线）。性能为**交替采样**（L/C/L/C 多轮取均值），
> 单次数字不作结论；正确性以逐字节对拍 + 像素门 + 全量测试为准。

### F.1 改了什么

| 文件 | 改动 | 说明 |
|---|---|---|
| `Loom/ckernels/loom_kernels.c` | +92 行，新导出 `loom_bucket_pack` | 逐桶 main/sha 实例打包（世界 16f + sat + 常量 pad + col）；语义 = Python 路径逐字节等价；桶内 n<=1 时不做剔除（同 Python 的 k>1 守卫） |
| `Loom/fastpath.py` | +72 行，`bucket_pack_available()` / `bucket_pack()` | **可选件**语义（与 aabbs/collide 的硬加载不同）：旧 DLL 无该导出 → 返回 None，调用方大声回退 |
| `Loom/loom_render.py` | 分段插桩 + C 打包快路径 | `buckets_gather/frustum/pack/write`、`mt_mp_draws_uniform/tex/render`；`_bucket_pack_ready/_staging/_frame`；`LOOM_BUCKET_PACK=0` 强制旧路径；缺导出时打印一行并回退 |
| `Loom/loom_profiler.py` | `_prof_count()` + `profile_snapshot()` 扩字段 | 新增 `per_call_us` / `handoffs`（交接次数，批次 D 因果证据） |
| `Loom/engine.py` / `Loom/loom_logic_thread.py` | 计数点 | `hm_pipe_post` / `hm_pipe_wait` / `hm_logic_wake` |
| `core_components/registry.json` + `official_manifest.py` | ckernels sha256 重钉 | 新 DLL `c5d3e271584f6b71…`（生成脚本 refresh/gen 各跑一次） |
| `Loom/tests/test_bucket_pack.py` | 新增单测 | 16 断言（见 F.2） |

**回退/降级**：`LOOM_BUCKET_PACK=0` → 打印一行并走旧 Python 路径；DLL 缺该导出 → 同样打印
`[buckets] ckernels.loom_bucket_pack 不可用 (...) -> 回退 Python 打包路径`；C 返回非 0 → 硬 raise
（官方件契约违约，沿用 aabbs/collide 纪律）。

### F.2 逐字节对拍（正确性硬门）

- 单测 `tests/test_bucket_pack.py`：无剔除 / 带空洞剔除 / 单实例桶守卫 / 全剔除桶 /
  契约错误码（offs[0]!=0、区间越界、K=0）→ **16/16 PASS**。
- 真场景（`压测500混合`，501 模型 / 35 桶）：同一帧同一世界状态下先后跑两条路径，
  直接比 **GPU 实例缓冲前缀字节**（main `n_main*96B` / sha `k*64B`）+ 每桶实例数；
  相机逐帧转动制造不同 keep 集合，**30 帧 × 35 桶，不一致 0 处**；剔除关闭档（planes=None）同样全等。

### F.3 性能（交替采样）

**A) 播放器进程内 3 轮交替（每轮 120 帧，ms/帧）**

| 指标 | Python 路径 | C 内核 | Δ |
|---|---:|---:|---:|
| `buckets` 合计 | 1.435 | **0.693** | **−0.742（−52%）** |
| ├ `buckets_gather` | 0.049 | 0.048 | −0.001 |
| ├ `buckets_frustum` | 0.234 | 0.231 | — |
| ├ `buckets_pack` | 0.865 | **0.066** | **−0.799** |
| └ `buckets_write` | 0.107 | 0.160 | +0.053（改为大 staging 切片写） |
| FPS | 77.3 | **86.9** | **+9.7** |
| p50 帧时间 | 7.58 ms | 6.73 ms | −0.86 |

**B) `--bench` 4 轮交替（300 帧，压测500混合）**

| 轮次 | 打包 | FPS | buckets |
|---|---|---:|---:|
| 1 | Python | 79.6 | 1.36 |
| 1 | C | **85.3** | **0.70** |
| 2 | Python | 79.2 | 1.41 |
| 2 | C | **87.1** | **0.71** |

### F.4 P0 闭账：mt_mp_draws 的 5.8x 是什么（编辑器 102 FPS，1226 帧）

编辑器 `mt_mp_draws` = 2.691 ms/帧（这是 FramePlan 执行总时长），拆开：

| 子段 | ms/帧 | 占比 | 说明 |
|---|---:|---:|---|
| `mt_mp_draws_render` | **1.035** | 38% | 35 次 `vao.render` → **29.6 µs/次** |
| `mt_mp_draws_uniform` | 0.255 | 9.5% | 每桶 6 次 uniform 赋值 |
| `mt_mp_draws_tex` | 0.048 | 1.8% | 每桶 2–3 次纹理绑定 |
| 其余（天空盒/后处理/状态应用/执行器） | ~1.35 | 50% | 不属于桶绘制 |

**结论**：Python 侧（uniform + tex）每帧只占 **0.30 ms**；同一份 `vao.render` 在播放器里
35 次合计 0.026 ms（**0.75 µs/次**），编辑器里 1.035 ms（**29.6 µs/次**）——**40x 差额在
驱动/宿主 FBO 的提交路径上（GPU 队列深度相关），不是语言层**。因此"把绘制循环下沉 C"无效；
多绘间接只有在能真正摊薄"每次提交的驱动成本"时才值得（本轮不做）。

另：`mt_mp_fbo` 在本次探针里报 8.85 ms/帧，但同一帧 `mt_main_pass` 只有 1.89 ms —
这是既有的 `_t_mp` 取点问题（阴影 pass 缺席时计时起点不刷新），与 D1 无关，登记待后续修。

### F.5 交接次数口径（编辑器播放态，每帧 / 每秒）

| 计数 | 每帧 | 每秒（102 FPS） |
|---|---:|---:|
| `hm_pipe_post` | 0.587 | ~60 |
| `hm_pipe_wait` | 0.294 | ~30 |
| `hm_logic_wake` | 0.593 | ~60 |
| `pipe_wait` 单次 | — | **12.6 ms/次**（`per_call_us`） |

### F.6 验收

- 逐字节对拍：单测 16/16 PASS；真场景 30 帧 × 35 桶 **0 不一致**（含剔除关闭档）。
- 像素门 `test_ab_gl_vk.py`：**23 通过 / 0 失败 / 0 跳过**（GL/VK MAE 与迁移前同量级）。
- `test_render_api.py` / `test_ui.py` / `test_vk_bucket_order.py`：ALL PASS。
- 全量 `tests/run_all.py`（128 文件）：见本次回报（若本轮未跑完则由下一轮补记）。

---

## 附录 G：批次 D2/D3 落地 + R5-03 审核整改（2026-11-10）

### G.1 D2 · 位姿 SoA（`_dirty_mask_batch` 取数段）

**改动链**：`engine._logic_frame` 在脚本跑完、物理子步投递前抓一次
`_transform_snapshot(self.models)` → `pipe.post(..., pose=(models,pos,rot))` →
`PhysicsPipeThread` 作业携带 → `PhysicsWorldBridge.pre_step(dt,g,pose)` →
`_dirty_mask_batch(entries, pose)` → 新增 `_pose_rows(nodes, pose)`：
id→行 映射一次性 fancy-gather 出 `(n,6) f64`；**任一节点不在平面里就返回 None 回退属性链**
（宁可慢不可错，与 P2-⑧ id 复用同纪律）。`LOOM_POSE_SOA=0` 强制旧路径。

**逐位对拍**（`tests/_tmp/d2_pose_soa_check.py`，真实场景 30 帧）：包一层
`_dirty_mask_batch`，先跑 legacy 记掩码 A 与后态，再恢复 `_last_sync` 跑 SoA 记掩码 B 与后态 ——
**64 次调用（含子步）掩码与后态 dict 全等，0 不一致**；中途注入「换父 / 删刚体再加回」仍全等（struct=ok）。

**回归断言**（`tests/test_physics_pose_soa.py`，10 条）：正常逐位取数 / pose=None /
形状·列数·models 长度不符 / **节点不在平面里 → None（防 id 复用错配）** / 换 models 列表后旧节点 → None / 空集不炸。

**性能**（同进程 4 组合交替 ×2 轮 ×90 帧）：

| 指标 | SoA 开 | SoA 关 | Δ |
|---|---:|---:|---:|
| `_dirty_mask_batch` /次 | **1.736 ms** | 2.515 ms | **−0.78（−31%）** |
| `pipe_wait` /帧 | **3.277 ms** | 3.985 ms | **−0.71** |
| `pipe_wait` /次 | **8.67 ms** | 9.19 ms | −0.52 |

未达 "≤2.0 ms/帧"：剩余是 ①501 次 `getattr(parent)` 父链走查（≈0.32ms）
②`old` 行仍从 `_last_sync` dict 组装（≈0.65ms）③`id2idx/pidx`（≈0.18ms）。
这三块是 **D2b**（`_last_sync` → numpy 行表 + 拓扑缓存）的剩余工作面，需连同 pre/post_step
的 sync 写入一起改，本轮未做（中高风险，留给下一轮）。

### G.2 D3 · AABB AVX2 + CPUID 分派

**改动**：AVX2 版（4 顶点/轮，无 FMA，同顶点运算序一字不改）+ `_cpu_has_avx2()`
（CPUID leaf1 OSXSAVE/AVX + XGETBV XMM|YMM + leaf7 EBX bit5）+ 显式导出
`loom_aabbs_minmax_scalar` / `_avx2` / `loom_aabbs_simd_impl`；
`loom_aabbs_minmax` 与并行 worker 均按运行时探测分派。AVX2 函数 `noinline`、
编译**不开** `/arch:AVX2`（老机器可加载，永不执行到 AVX2 指令）。

**对拍**（`tests/test_aabb_simd.py`）：V=2035/1617/3015/24/4、尾路径 V=1..7、空批，
scalar / avx2 / 分派版三路 min/max **逐字节相同**（max|diff|=0）。

**性能**：`mt_aabb_minmax` **2.04 → 1.13 ms/帧（−45%）**，`aabbs` 段 1.05 → 0.73（−30%）；
微基准 2.29x（V=2035,n=90）。
> 过程登记：首轮 A/B 显示零收益 —— 定位到只在 DLL 里加了导出、公开入口 `loom_aabbs_minmax`
> 仍走标量，补上分派才生效。"分派必须接在公开入口" 已写进验收清单。

### G.3 R5-03 审核整改（本轮顺手修）

| 编号 | 整改 |
|---|---|
| P-02 契约边界 | `loom_bucket_pack_v1` 去掉 `n_total==0` 提前返回：K>0 且全空桶时逐桶写 `out_main_n=0`；新增断言 `offs[K]==n_total`（区间必须铺满），违反返回 1。测试 ⑦ 用垃圾初值 count 抓"未写"，⑥ 覆盖未铺满 |
| Q-D1-2 契约登记 | `provides_count 2→3`、`g_module_provides` 与 `loom_module_has` 加 `ckernels.bucket_pack`；registry.json provides 同步；导出改版本化 **`loom_bucket_pack_v1`** 并保留旧名别名；测试 ⑧ 断言 has=1 与 provides 含该项 |
| P3-05 计数竞态 | `_prof_counts` 懒初始化加模块级锁（首次临界区，稳态零锁），修 3000 次丢 11 次的统计丢失 |
| P3-06 口径 | `_prof_count` docstring 改为实测口径：**未开时约 1.2µs/次**（非"零开销"），当前 ≤3 次/帧；并注明"要加到高频点必须先做模块级开关缓存" |
| P3-07 回退声明 | 声明改为实话：**DLL 缺失不可达**（导入期 B1 硬 raise）；可达的只有「DLL 在但无该导出」与「LOOM_BUCKET_PACK=0」 |
| P3-10 per_call_us | `buckets_pack/buckets_write`、`mt_mp_draws_uniform/tex/render` 直写 `_stage_times` 时同步 +1 `_stage_calls`，`per_call_us` 键齐全（= ms/帧） |

**DLL sha 演进（收尾统一重钉）**：D1 提交 `c5d3e271…` → D3 首版 `118e8333…` →
AVX2 分派 `730671ac…` → **最终（provides + v1 + 边界修正）`7bf7a7710e6479f034a264317c76ccbe6aecc1ccc7605e706ab65b2d05b8270f`**
（registry.json 与 official_manifest.py 已同批重生成；`LOOM_DEV=1` 可跳过校验）。

---

## 附录 H：V-02 倒查补强（入口级对拍 + LOOM_NO_SIMD + 性能门禁，2026-11-10）

> 倒查结论接受：D 批三个性能测试此前都是 **helper-only**（只调 `fastpath.*` / 私有 `_pose_rows`），
> 既不经过生产入口、也不测回退开关、更没有性能门禁。本附录记录补强后的**两种口径**。

### H.1 入口级对拍（新增，全部可复跑）

| 测试 | 入口 | 断言 |
|---|---|---|
| `test_bucket_pack` | `loom_render.RenderMixin._prepare_bucket_frame`（真方法；仅 GL 资源用假 buffer/VAO） | `LOOM_BUCKET_PACK=1` vs `0` 下 main/sha **逐字节一致**（35 桶 / 490 实例）；剔除开启/关闭两档都比；并断言"确有桶 n_main<k"证明剔除真生效 |
| `test_aabb_simd` | `loom_lighting.LightingMixin._aabbs_batched`（真方法；stub 只给 `_homogeneous_vertices` 与 thread-local staging） | scalar / avx2 / 分派三路 AABB 列表**逐位相等** |
| `test_physics_pose_soa` | `PhysicsWorldBridge._dirty_mask_batch`（真方法；120 节点 + 父子树） | pose 开/关两路 **掩码 dict 全等 + 后态 `_last_sync` 全等**；并断言祖先传播真的发生 |

### H.2 两种口径的实测（同机）

| 指标 | helper 级（D1-D3 原口径） | 入口级（本次） |
|---|---|---|
| 桶打包 | 播放器 `buckets` 1.435 → 0.693 ms/帧（−52%） | `_prepare_bucket_frame` **0.366 → 0.247 ms/次**（比值 0.67） |
| AABB | 微基准 V=2035,n=90：1.06 → 0.46 ms（2.29x） | `_aabbs_batched` **0.184 → 0.145 ms/批**（比值 0.79） |
| 位姿脏检测 | 真场景 `_dirty_mask_batch` 2.47 → 1.74 ms/次 | 120 节点桩：**0.59 ms/次**（入口可达、掩码与属性链路径全等） |

> 入口级比值不如 helper 级亮眼是正常的：入口还包含 gather / 视锥 / 逐桶循环等不随实现改变的部分。

### H.3 `LOOM_NO_SIMD=1`（设计承诺已落地）

`loom_kernels.c::_simd_impl()` 首次探测时读一次 `getenv("LOOM_NO_SIMD")`：
等于 `"1"` 时强制标量，否则走 CPUID+XGETBV 判定（**运行中改 env 无效**，热路径零 getenv）。
测试用子进程验证：`LOOM_NO_SIMD=1` → `aabbs_simd_impl()==0`；无该 env → 与 CPUID 判定一致。

### H.4 性能门禁（CI 可抓回退）

| 测试 | 门禁 | 实测/余量 |
|---|---|---|
| `test_bucket_pack` | 入口级 C ≤ **0.80×** Python 路径；绝对上限 12 ms | 0.67×（余量 ~20%） |
| `test_aabb_simd` | 入口级 AVX2 ≤ **0.90×** 标量；绝对上限 40 ms | 0.79×（余量 ~12%） |
| `test_physics_pose_soa` | `_dirty_mask_batch` ≤ **3.0 ms/次**（120 节点） | 0.59 ms（余量 5x） |

门禁均为"同进程相邻测量"的相对值或宽松绝对值，避免机器负载误报；回退 20-40% 即被抓。

### H.5 统一重钉

最终 DLL（含 `LOOM_NO_SIMD`）：`95bc00bfeb9ca4fda67f3231afffd07a00aadae436abb01a145dd31df0bd0e5b`；
`registry.json` provides = `['ckernels.aabbs', 'ckernels.collide', 'ckernels.bucket_pack']`，
`official_manifest.py` 同批重生成。


