# 批次 D1 热点下沉（loom_bucket_pack）独立复核 — beta6 第五轮 / 编号 03

> 审计对象：`470b7bc` perf(render)! 批次D1 loom_bucket_pack（父 `adcc49f`），以及同批的 profiler / engine / logic_thread / sha 重钉。
> 方法依据：桌面两份方法论（粗筛→双向推演→四象限→探针闭环，8 段式）+ `docs/audit/SCAN_PROTOCOL.md`。
> 只读审计：未改任何受跟踪文件、无 git 写操作；探针只写 `Loom/tests/_tmp/audit_b6r5_03_*.py`。

## 0. 范围与方法

### 0.1 文件范围（D1 改动）
| 文件 | D1 改动 |
|---|---|
| `Loom/ckernels/loom_kernels.c` | 新增导出 `loom_bucket_pack`（338-426，Kernel 4） |
| `Loom/fastpath.py` | `_BK` / `bucket_pack_available()` / `bucket_pack()`（D1 提交时 447-518；工作区因在途 D3 已后移至 493-545） |
| `Loom/loom_render.py` | C 打包接线 692-698 / 786-863；buckets 三段计时 546/671/687/700-784；mt_mp_draws 三段 884-950 |
| `Loom/loom_profiler.py` | `_prof_count` 43-52；`profile_snapshot` 增 `per_call_us`/`handoffs` 56-69 |
| `Loom/engine.py` | `_prof_count('hm_pipe_wait')` 1242、`('hm_pipe_post')` 1289 |
| `Loom/loom_logic_thread.py` | `_prof_count('hm_logic_wake')` 101（在 `try:` 之外） |
| `Loom/core_components/{official_manifest.py,registry.json}` | ckernels sha 重钉 `c5d3e271…` |
| `Loom/tests/test_bucket_pack.py` | 新增 16 项内核级断言 |

### 0.2 工作区在途改动（只标注，不据此下结论）
审计期间工作区被并发修改（批次 D3 AABB AVX2）：`git status` 显示 ckernels/loom_kernels.c(+160 行，全部追加在 loom_bucket_pack **之后**，428+)、fastpath.py(+32)、engine.py、physics_pipe.py、run_player.py、scene_driver.py、tests/test_aabb_simd.py。
实测一次重编：DLL 12:59:51 重建、manifest/registry 13:00:40 重钉为 `118e8333…`（D1 提交时是 `c5d3e271…`）。D1 的 `loom_bucket_pack` 函数体未被在途改动触碰（在途 hunk 起点在 428 行后），故结论不受影响；但**探针横跨了这次重编**（探针 A 在重建前，B/C/D/E 在重建后），两版 DLL 上 `test_bucket_pack` 均 ALL PASS。

### 0.3 跑过的命令（均可复现）
| # | 命令 | 作用 |
|---|---|---|
| 1 | `python Loom/tests/test_bucket_pack.py` | 内核 16 项契约/字节断言 |
| 2 | `python Loom/tests/_tmp/audit_b6r5_03_a_ab_boundary.py` | C 打包 vs 旧逐桶路径 11 类边界逐字节对拍（复用 beta5 轮 03 号桩引擎） |
| 3 | `python Loom/tests/_tmp/audit_b6r5_03_b_kernel_edges.py` | 内核契约边界（空/单桶/中间空桶/全剔除/keep>1/NaN/±0/尾部未覆盖/未定义早退） |
| 4 | `python Loom/tests/_tmp/audit_b6r5_03_c_fallback.py` | 三条回退分支返回值+打印 |
| 5 | `python Loom/tests/_tmp/audit_b6r5_03_d_prof_thread.py` | 新指标开销/首帧竞态/并发快照 |
| 6 | `python Loom/tests/_tmp/audit_b6r5_03_e_sha_version_gate.py` | 三方 sha 一致 + 旧 DLL+新引擎判定 |
| 7 | `python Loom/tests/_tmp/d1_pack_bitexact.py 8` | 真场景 8 帧 × 35 桶 × 501 实例 GPU 缓冲对拍（相机转动=可见性翻转） |
| 8 | `python Loom/tests/_tmp/scan_beta5_03_03_buckets_ab.py` | 历史探针原样跑 → 证明 P-01 回归 |

## 1. 粗筛清单（含跳过留痕）

| ID | 位置 | 标签 | 初步方向 |
|---|---|---|---|
| P-01 | loom_render.py:546/671/687 | IFACE-PRECOND | 新增 `self._prof_t0()/_prof_add`，而 RenderMixin 自身没有这两个方法 |
| P-02 | loom_kernels.c:382 + loom_render.py:817 | SEM-SILENT | K>0 且 n_total==0 早退不写 out_main_n，消费侧用 np.empty 取数 |
| P-03 | loom_kernels.c:612/617/660-663 | TOOL-WHITELIST | 新导出未登记 provides/loom_module_has，官方件契约自相矛盾 |
| P-04 | loom_render.py:845-846 | SEM-SILENT(反向) | rc!=0 硬 raise（崩溃）而非"非必需件"降级 |
| P-05 | loom_profiler.py:49-52 | BND-CONCURRENCY | _prof_counts 首帧 getattr→赋值 双线程竞态 |
| P-06 | loom_profiler.py:44 docstring | AUDIT-DOCIMPL | "未开时零开销"但每次仍 os.environ.get |
| P-07 | fastpath.py:84-87 vs loom_render.py:796-805 | AUDIT-DOCIMPL | 回退声明含"DLL 缺失"，该场景在导入期硬 raise |
| P-08 | loom_kernels.c:365-426 vs loom_render.py:719-778 | SEM-MISMATCH | 逐字节等价是否覆盖空/单桶/全剔除/翻转/NaN/负半径 |
| P-09 | official_manifest.py:22 / registry.json:28 / boot_check.py:42-91 | IFACE-VERSION | sha 重钉后旧 DLL+新引擎会不会误判 |
| P-10 | loom_profiler.py:56-69 + loom_render.py:840-863/952-955 | AUDIT-ASYMMETRY | 新分段直写 _stage_times 绕过 _stage_calls → per_call_us 缺键 |
| P-11 | loom_render.py:665-721 | BND-EMPTY | "空 order 但桶非空" ValueError（前轮已裁） |
| P-12 | loom_kernels.c:663 末行无换行 / loom_render.py:851 ent 未用 | — | 风格/死变量 |
| P-13 | loom_render.py:787-806 | — | LOOM_BUCKET_PACK 只读一次并缓存，不支持热切换 |

**跳过登记（四类理由）**：
- SKIP-01 `_bucket_pack_frame` 只上传前 n_main 行 —— **白盒契约明确声明**（C 注释 359-361）+ 与 Python `st[:n_main]` 同语义；探针 A/B 逐字节对拍已覆盖。
- SKIP-02 `memcpy` 对齐/严格别名 —— **语言规范保证**（numpy C 连续缓冲上 memcpy 无对齐要求）；P-08 探针含 NaN/±0/inf 保真实测。
- SKIP-03 `_bucket_pack_staging` 只在扩容分支同时分配 _bp_main/_bp_sha —— **路径枚举**：同一 `if` 体内无异常可插入，不存在"main 有、sha 无"的可达状态；_bp_sha 全仓仅两处引用。
- SKIP-04 `ent` 赋值未使用 / C 文件末行缺换行 —— P3 风格项，不影响可观察行为，不进入双向推演。

## 2. 逐项裁决（8 段式）

### P-01 [REGRESSION] RenderMixin 新增对 ProfilerMixin 的隐式依赖 → 历史对拍探针直接崩
1. **位置**：loom_render.py:546 `_t_seg = self._prof_t0()`、:671/:687 `self._prof_add(...)`；方法定义在 loom_profiler.py:31-41。
2. **契约/预期**：loom_render.py:19 声明 RenderMixin 的宿主依赖只有 _mesh_key/_build_bucket_geo/_grow_bucket_inst；loom_profiler.py:7-9 只声明 ProfilerMixin 依赖 _stage_times/_stage_calls。两份契约都没有"RenderMixin 需要 ProfilerMixin"。
3. **路径枚举**：_prepare_bucket_frame 是唯一入口；_prof_t0 在函数体第 2 条语句无条件求值，无分支可绕。
4. **实际行为**：宿主只有 RenderMixin 时 → `AttributeError: 'Eng' object has no attribute '_prof_t0'`，第一帧即炸。
5. **差异**：D1 之前该函数没有任何 ProfilerMixin 调用（`git show 470b7bc -- Loom/loom_render.py` 中 546/671/687 三行均为新增）。
6. **触发条件**：任何以 RenderMixin 为基类但未混入 ProfilerMixin 的宿主——仓库内至少两处历史审计探针（scan_beta5_03_03_buckets_ab.py:57、scan_beta5_02_*.py）。生产 GLEngine（engine.py:191-193）两者都混入，故线上不炸。
7. **验证**：
   `
   $ python Loom/tests/_tmp/scan_beta5_03_03_buckets_ab.py
     File ".../Loom/loom_render.py", line 546, in _prepare_bucket_frame
       _t_seg = self._prof_t0()
   AttributeError: 'Eng' object has no attribute '_prof_t0'
   `
   打 2 行垫片后同一脚本 11 类边界全部 YES（见 P-08 探针 A）。
8. **影响与等级**：**P2**（接口契约 + 审计证据链断裂）。方向：把 _prof_t0/_prof_add 默认实现下沉到 RenderMixin，或 `getattr(self,'_prof_t0',None)`，不要靠"宿主一定混了 ProfilerMixin"的隐式约定。

### P-02 内核 K>0 且 n_total==0 时早退，out_main_n 保持未初始化
1. **位置**：loom_kernels.c:382 `if (K == 0 || n_total == 0) return 0;`；消费侧 loom_render.py:817 `self._bp_cnt = np.empty(...)` + :856 `n_main = int(cnt[bi])`。
2. **契约/预期**：C 注释 361 行"out_main_n (K,) i32 —— 每桶 main pass 实例数"；363 行"返回 0 成功"。rc=0 时 K 个计数都应已定义。
3. **路径枚举**：K==0 → 无桶可写（合法）；n_total==0 且 K>0 → 提前 return 0，跳过整个 for，out_main_n[0..K) 全未写；其余路径逐桶写满。
4. **实际行为**：cnt 保持调用方 np.empty 残留（探针预填 -999 实测仍 -999）；_draw_main_buckets（loom_render.py:899-901）会把它当 `instances=` 使用。
5. **差异**：后置条件声明"K 个计数已写"，实际在 n_total==0 且 K>0 这一格未写。
6. **触发条件**：当前生产调用方**不可达**（_render_buckets 分组保证每桶非空，loom_render.py:560-563 ⇒ K>0 ⇒ n_total>0；且 665-670 有长度校验）。属未来调用方/单元级边界。
7. **验证**：
   `
   $ python Loom/tests/_tmp/audit_b6r5_03_b_kernel_edges.py
   === E2 K=1 但 n_total=0 (offs=[0,0], 桶空) ===
   rc = 0 | out_main_n 是否被写? cnt = [-999] (初始 -999)
   === E3 K=1 但 n_total=0 且 keep 非 NULL ===
   rc = 0 | cnt = [-999]
   `
8. **影响与等级**：**P2**（契约未定义边界；可观察后果=垃圾实例数）。方向：早退前 `for(b=0;b<K;++b) out_main_n[b]=0;`，或判 rc=1；引擎侧 _bp_cnt 改 np.zeros。

### P-03 新内核未登记进 provides/loom_module_has → 能力查询假阴
1. **位置**：loom_kernels.c:612 `provides_count: 2`、:617 `g_module_provides = {"ckernels.aabbs","ckernels.collide"}`、:660-663 loom_module_has；registry.json:23-26 provides 2 项、note 仍写"aabbs/collide"。
2. **契约/预期**：docs/design/架构互联协议总表.md:54"loom_module_has = 可选能力查询"；module_loader.py:340-341 `iface_has` 是组件层唯一能力查询入口。D1 在官方件新增 C 导出，按同一契约应可查到。
3. **路径枚举**：iface_has("ckernels.bucket_pack") → loom_module_has(strcmp) → 两分支都不命中 → 0 → False；provides_map 只装 2 个 iface（module_registry.py:176-177）。
4. **实际行为**：能力查询返回"没有这个内核"，与实际导出相反。
5. **差异**：DLL 实际 4 个数值内核，契约声明 2 个。
6. **触发条件**：任何经 module_registry/iface_has 的装配期判定（当前 fastpath 用 ctypes hasattr 直取，运行时未受害）。
7. **验证**：
   `
   $ python -c "import ctypes; d=ctypes.CDLL('Loom/ckernels/loom_kernels.dll'); print(hasattr(d,'loom_bucket_pack'), d.loom_module_has(b'ckernels.bucket_pack'))"
   True 0
   `
   （test_bucket_pack ① 只断言 hasattr，不断言 iface 注册，故 16 项全绿发现不了本条）
8. **影响与等级**：**P2**（官方件契约完整性/可审计性）。方向：provides_count=3、加入 g_module_provides、loom_module_has 加 strcmp，同步 registry.json 与 tests/_tmp/module_registry_check.py:92 的 12 项断言。

### P-04 C 返回非 0 时硬 raise（崩溃）而非降级 —— 设计取舍待裁决
1. **位置**：loom_render.py:843-846 `rc != 0 → raise RuntimeError(...)`；调用点 695-698，上游 engine.py:2441 / loom_render.py:1148 的 `self._profile('buckets', ...)`。
2. **契约/预期**：同提交注释 fastpath.py:457-460"打包不是正确性必需件, 只是性能路径"、_bucket_pack_ready docstring"缺导出则大声回退一次"。语义应为"性能件 ⇒ 可降级不可崩"。
3. **路径枚举**：rc==0 / rc==1（NULL、K<0、n_total<0、offs[0]!=0、区间越界）/ rc is None（可用性判定与 _CK['dll'] 不一致），三条非 0 路径全部 raise，且 692-846 段内无 try 兜底。
4. **实际行为**：rc=1 → RuntimeError 冒到主循环 → 帧崩溃（与 P-02 组合最坏为 `instances=` 垃圾）。
5. **差异**：同一文件对"缺导出"打印降级，对"参数违约"崩溃；两者都是"打包坏了"。
6. **触发条件**：offs/n_total 不同源（如未来改了 _render_buckets 未同步 _bucket_offs_np），或 C 侧新增越界校验。
7. **验证**：test_bucket_pack `⑥ offs[0]!=0 -> rc=1`；探针 B E7（offs[-1]<n_total 静默 rc=0，尾部不写）。
8. **影响与等级**：**P-UNKNOWN（需人类裁决）**，风险面 P2。白盒契约空白：A=硬 raise（当前）、B=打印 + _bucket_pack_state=-1 + 本帧重跑 Python。

### P-05 _prof_counts 首帧初始化的双线程竞态（11/3000 次丢计数）
1. **位置**：loom_profiler.py:49-52 `c = getattr(...); if c is None: c = self._prof_counts = {}`；调用方 engine.py:1242（渲染线程）、loom_logic_thread.py:101（逻辑线程）。
2. **契约/预期**：loom_profiler.py:44"交接/事件计数（跨线程交接次数的因果证据）"——D1 自己定义为跨线程观测量，应无丢计。
3. **路径枚举**：A 单线程首调；B 两线程首调交错在 getattr 与赋值之间 → 各建一个 dict，后赋值者覆盖 self._prof_counts，先赋值者那次 +1 落在被遗弃 dict（此后两线程都用存活 dict，丢失有界=每指标 1 次）。
4. **实际行为**：3000 次 barrier 同步双线程首调中 11 次总数 != 2。
5. **差异**："零丢计" vs "首帧可能丢 1 次"（相对数十帧累计量 <0.1%）。
6. **触发条件**：LOOM_PROFILE=1 + 逻辑线程在跑 + 首帧两线程都首次打点。
7. **验证**：
   `
   $ python Loom/tests/_tmp/audit_b6r5_03_d_prof_thread.py
   1) 未开 profile: 300000 次 _prof_count = 358.487 ms -> 1195.0 ns/次; _prof_counts 建立? False
   2) 首帧初始化竞态: 3000 次双线程首调中丢失计数的次数 = 11
   3) profile_snapshot 并发拷贝: 开 3 线程狂写 + 主线程狂拷 20000 次
      异常: None
   4) per_call_us: 12.0ms/4 次 -> {'buckets': 3000.0}
   `
8. **影响与等级**：**P3**（只影响交接口径首帧 1 次；并发快照未观察到 RuntimeError）。方向：_prof_counts 在 __init__ 初始化（_stage_times 就是这么做的）。

### P-06 "未开 profiling 时零开销"与实测 1195 ns/次不符
1. **位置**：loom_profiler.py:44 docstring、:47 `os.environ.get('LOOM_PROFILE')`。
2. **契约/预期**：零开销。
3. **路径枚举**：未开 → 一次 os.environ.get 后 return；开 → 建 dict + 计数。
4. **实际行为**：1195 ns/次（300k 次 358 ms）。
5. **差异**：非零，但量级×频率决定影响：hm_logic_wake ≤1000 次/s（loom_logic_thread.py:107/129 两处 sleep）→ ≤1.2 ms/s ≈ 0.12%；hm_pipe_* 每帧 1-2 次可忽略。
6. **触发条件**：恒发。
7. **验证**：探针 D 第 1 行。
8. **影响与等级**：**P3**（措辞与实现不符；④"不拖慢热路径"整体成立）。方向：docstring 改为"约一次 os.environ.get 量级"或缓存开关。

### P-07 回退声明中的"DLL 缺失"分支实际不可达
1. **位置**：fastpath.py:84-87 模块级 `raise RuntimeError('ckernels 官方组件加载失败…')`；loom_render.py:796-805 `try: import fastpath … except Exception: ok=False`。
2. **契约/预期**：提交信息与 fastpath.py:457-460 声明三种回退：LOOM_BUCKET_PACK=0 / DLL 无导出 / DLL 缺失。
3. **路径枚举**：engine.py:33-35 在导入期 import fastpath → DLL 缺失时 RuntimeError 在 GLEngine 定义前抛出 → _bucket_pack_ready 永不执行；except 只剩"导入后 sys.modules 被破坏"这一理论格（探针 E）。
4. **实际行为**：DLL 缺失 = 启动硬失败（B1 逃生门退役既定契约），不是回退。
5. **差异**：声明 3 条，实际可测 2 条 + 1 条理论。
6. **触发条件**：DLL 缺失/路径错。
7. **验证**：
   `
   $ python Loom/tests/_tmp/audit_b6r5_03_c_fallback.py
   A) 默认(新 DLL 有导出):  (True, 1, '')
   B) LOOM_BUCKET_PACK=0: (False, -1, '[buckets] LOOM_BUCKET_PACK=0 -> 强制走 Python 打包路径 (A/B 或故障回退)')
   C) 旧 DLL 无该导出:     (False, -1, '[buckets] ckernels.loom_bucket_pack 不可用 (旧 DLL 无该导出) -> 回退 Python 打包路径')
   E) fastpath 导入失败:  (False, -1, '[buckets] ckernels.loom_bucket_pack 不可用 (ModuleNotFoundError: import of fastpath halted; None in sys.modules) -> 回退 Python 打包路径')
   `
   → 可测的两条回退都"打印 + 返回 False"（不静默），② 的核心担忧证伪。
8. **影响与等级**：**P3**（措辞精度）。方向：把"DLL 缺失"从回退声明删掉，注明"缺 DLL = 启动硬失败（fastpath.py:84-87）"。

### P-08 C 打包与 Python 打包的逐字节等价（① ⑤ 主管线）— P-DISPROVED
1. **位置**：loom_kernels.c:365-426 vs loom_render.py:719-778（切片 gather / keep 过滤 / 24f 行布局 / sha 全量）。
2. **契约/预期**：loom_kernels.c:345-351"语义 = 现行 Python 路径的逐字节等价；n<=1 不剔除（与 k>1 守卫一致）；padding[17..19]=0"。
3. **路径枚举（逐条对拍）**：空场景 K=0,n=0；单实例/单桶桶（两路都不剔除）；全剔除（两路都不写 main）；可见性翻转多帧（两路都只上传前 n_main 行，残留字节不上屏）；NaN/inf/±0（memcpy vs numpy 位型相同）；负半径（剔除决策不在 C 里，两路吃同一份 numpy keep）；keep=255（两者同真值语义）；中间空桶 offs=[0,3,3,6]；offs[-1]<n_total 尾部不写；畸形输入 rc=1/1/0。
4. **实际行为**：11 类边界 × 每桶 main/sha 全字节 + main_n 全等；真场景 8 帧 × 35 桶 × 501 实例 0 处不一致。
5. **差异**：无可观察差异。
6. **触发条件**：不适用（覆盖全部可枚举边界）。
7. **验证**：
   `
   $ python Loom/tests/_tmp/audit_b6r5_03_a_ab_boundary.py
   0 物体 ... 字节一致=YES
   1 物体 (单实例桶) ... YES
   3 物体 同桶 ... YES
   2 桶 各1 ... YES
   全被剔除(远处) ... YES
   零顶点网格 ... YES
   NaN 世界矩阵 ... YES
   可见性 False ... YES
   关剔除(frustum_cull=0) ... YES
   负半径注入 ... YES
   计划失效(offs 不符) ... YES

   $ python Loom/tests/_tmp/d1_pack_bitexact.py 8
   buckets=35 models=501 pack_ready=True
   frames_checked=8  bad=0  nofrustum_ok=True
   `
   （探针 A 最后一个"空 order"用例会 ValueError，见 P-11，属前轮已知、非 D1 引入）
8. **影响与等级**：**P-DISPROVED**（① ⑤ 无隐患）。残留覆盖缺口（P3 提示，非 bug）：test_bucket_pack 未覆盖 (a) K>0 且 n_total==0（P-02）、(b) keep 为 bool dtype（生产传参前已 uint8 转换）、(c) 单桶场景引擎级 all-culled。

### P-09 sha 重钉后「旧 DLL + 新引擎」不会误判 — P-DISPROVED
1. **位置**：official_manifest.py:20-23、registry.json:19-30、boot_check.py:42-91、module_registry.py:155-170（_sha_gate，LoadLibrary 之前）+ :317-324（AssemblyError）。
2. **契约/预期**：boot_check.py:9-13"官方件 SHA 不符 → 出厂模式报警拒载"；assemble docstring"绝不带病运行"。
3. **路径枚举**：① 出厂 + 旧 DLL（新引擎）→ manifest 比对 modified → AssemblyError；② 新 DLL + manifest 未重钉 → 同①；③ LOOM_DEV=1 → boot_check 跳过，但 _sha_gate 仍比 registry sha（**无 LOOM_DEV 旁路**）→ 仍拒；④ 注入件 official=false → 不参与 sha 门 → 由 bucket_pack_available 兜底；⑤ manifest 被钉到没有该导出的旧 DLL → 门全绿、引擎启动、_bucket_pack_ready 打印回退。
4. **实际行为**：① 拒载（不会带旧 DLL 静默跑）；④⑤ 降级且有打印。
5. **差异**：无一格产生"错误结果"；风险只剩拒载（fail-closed）与降级（有提示）。
6. **触发条件**：见 ③④⑤。
7. **验证**：
   `
   $ python Loom/tests/_tmp/audit_b6r5_03_e_sha_version_gate.py
   1) manifest = 118e833312012ed7 | registry = 118e833312012ed7 | 磁盘 = 118e833312012ed7 | 全等 = True
   2) verify_official -> True [('module_ref','ok'),('ckernels','ok'),('pipeline','ok'),('script','ok'),('physics','ok')]
   5) 注入件(official=false) -> True [... ckernels 不参与 ...] (旧注入 DLL 可启动, 由 bucket_pack_available 兜底)
   `
   （注：verify_official 只比 manifest、不看 registry.sha256；registry sha 由 _sha_gate 独立把关——两条闸都要重钉，D1 两者都改了）
8. **影响与等级**：**P-DISPROVED**（③ 无误判）。待改进（P3，登记不裁决）：pack 导出既无版本化名（如 loom_bucket_pack_v1）也不在 loom_module_has（P-03），未来签名变更只改 sha 重钉则运行期无法发现。

### P-10 per_call_us 对新分段缺键（直写 _stage_times 绕过 _stage_calls）
1. **位置**：loom_profiler.py:56-69 `if _n: _per_call_us[_k] = _v/_n*1000`；loom_render.py:840-842（buckets_pack）、862-863（buckets_write）、952-955（mt_mp_draws_uniform/_tex/_render）、783-784（Python 路径同名分段）。
2. **契约/预期**：loom_profiler.py:58"单次耗时 (µs) 与交接计数 —— 批次 D 的因果证据口径"，读者会假定每个 times 键都有 per_call_us。
3. **路径枚举**：_profile(name,fn) 同时写 times+calls；D1 新增 5 个分段只写 times → snapshot 的 per_call_us 无这些键（缺键，不是 0）。
4. **实际行为**：查 per_call_us['buckets_pack']/'mt_mp_draws_render' → KeyError。
5. **差异**：文档口径 vs 实际字段集。
6. **触发条件**：任何按 times 键遍历 per_call_us 的探针（提交信息里的"29.6us/次"是人工另算的）。
7. **验证**：探针 D 第 4 行"12.0ms/4 次 -> {'buckets': 3000.0}"（只有走 _profile 的键才有）；`grep -n "_stage_calls\['buckets_pack'\]" Loom/loom_render.py` 无命中。
8. **影响与等级**：**P3**（指标口径不对称）。方向：新分段同时 _stage_calls 加 1，或在 per_call_us 里注明"直写分段不含 per-call"。

### P-11 「空 order 但桶非空」ValueError：前轮已裁，D1 未引入（留痕）
1. **位置**：loom_render.py:665-670 守卫只查 len(offs)、:719-721 `g[:k] = G_all[a:b]`。
2. **契约/预期**：守卫应保证 order 与 _render_buckets 同源。
3. **路径枚举**：只有外部注入 _bucket_order=[] + 清 sig 才能命中；生产 order/offs 同分支生成（614-633）。
4. **实际行为**：`ValueError: could not broadcast input array from shape (0,4,4) into shape (2,4,4)` at :721。
5. **差异**：守卫缺 len(order)==offs[-1]（前轮 P-05 已提出，未修）。
6. **触发条件**：私有状态注入。D1 未把该状态接入 C（keep_all 形状不匹配 → C 跳过），行为与 beta5 一致。
7. **验证**：探针 A 最后一例；docs/audit/scan_beta5_round_03_perf_clock_buckets.md:185-195 同结论。
8. **影响与等级**：**P-DISPROVED（作为 D1 回归）**；作为存量防御缺口仍是 P2 建议（零成本补守卫，可与 P-02 合并）。

## 3. 统计

| 判定 | 数量 | 项 |
|---|---|---|
| P-PROVED | 6 | P-01(P2, [REGRESSION])、P-02(P2)、P-03(P2)、P-05(P3)、P-06(P3)、P-07(P3) |
| P-DISPROVED | 4 | P-08(①⑤)、P-09(③)、P-11(存量)、探针 D 的并发快照无异常 |
| P-UNKNOWN | 1 | P-04（错误策略需人类裁决） |
| P-CONTRADICTION | 0 | — |
| 跳过登记 | 4 | SKIP-01…04 |

按派单五问：
1. **①逐字节等价边界** → 实测覆盖且相等（空/单桶/全剔除/可见性翻转/NaN/±0/负半径/keep>1/中间空桶/rc 语义）；P-02 是"未定义边界"而非"不等价"。
2. **②回退路径** → LOOM_BUCKET_PACK=0 与"无导出"实测可跑且有打印；"DLL 缺失"分支不可达（P-07），但缺 DLL 属启动硬失败，不静默。
3. **③sha 重钉误判** → 不会：出厂拒载、开发/注入态降级且有打印（P-09）；残留风险是导出无版本化（P-03/P-09 附注）。
4. **④指标线程安全/热路径** → 首帧有界丢计（P-05，11/3000）；快照并发无异常；关 profile 时 1195 ns/次（P-06，≤0.12%/s）。
5. **⑤NaN/负半径极值** → C 不参与剔除决策，两路共用同一 numpy keep，行为同源；字节层面 memcpy 保真（P-08）。

## 4. 修复建议（按等级，只给方向）

| 序 | 项 | 等级 | 方向 |
|---|---|---|---|
| 1 | P-04 | P2* | 决定"性能件违约"的错误策略（硬 raise 或一次降级+打印+state=-1+本帧重跑 Python），写进白盒契约 |
| 2 | P-02 | P2 | n_total==0 早退前把 out_main_n 清零（或判 rc=1）；引擎侧 _bp_cnt 改 np.zeros |
| 3 | P-01 | P2 | _prof_t0/_prof_add 默认实现放进 RenderMixin（或 getattr 兜底），消除隐式 mixin 依赖；顺带修两个历史探针 |
| 4 | P-03 | P2 | 登记 ckernels.bucket_pack 到 provides_count/g_module_provides/loom_module_has + registry.json（同步 module_registry_check.py:92 的 12 项断言） |
| 5 | P-11 | P2(存量) | 守卫补 len(order)==offs[-1]==sat_all.shape[0]==col_all.shape[0] |
| 6 | P-05 | P3 | _prof_counts 在 __init__ 初始化 |
| 7 | P-06/P-07/P-10 | P3 | 三处口径与实现对齐（零开销 / DLL 缺失 / per_call_us 覆盖范围） |

## 5. 需人类裁决的封闭问题

- **Q1（P-04）**：C 打包内核返回非 0 时——A 保持硬 raise（当前，违约即崩），还是 B 打印 + 关掉 C 路径 + 本帧重跑 Python（性能件降级）？
- **Q2（P-03/P-09）**：新内核是否纳入组件能力契约——A 登记进 provides/loom_module_has 并版本化导出名（loom_bucket_pack_v1）；B 只登记不版本化；C 维持现状（ctypes hasattr 直取，契约里查不到）？
- **Q3（P-01）**：RenderMixin 对 ProfilerMixin 的依赖——A 在 RenderMixin 内提供 no-op 默认实现；B 明确契约并 fail-fast 断言；C 维持隐式约定？

---
_审计者：独立复核子代理（编号 03）。全部结论可用 §0.3 命令复现；探针只写 Loom/tests/_tmp/audit_b6r5_03_*.py，未改任何受跟踪文件。_
