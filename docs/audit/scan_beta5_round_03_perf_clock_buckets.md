# 性能改造·时钟与桶管线 扫描报告（scan_beta5_round_03）

> 子代理编号 03。范围基线 `71b31ac..HEAD`（beta4 已发布之后的全部改动）。
> 判定基准只引用本仓库自身的白盒契约（docstring / 注释 / 既有测试名），不引用外部标准。
> 全文只读：未修改任何受跟踪文件，探针全部落在 `Loom/tests/_tmp/scan_beta5_03_*.py`（gitignore）。

---

## 0. 范围与方法

### 0.1 diff 规模（`git diff --stat 71b31ac..HEAD`）

| 文件 | 本范围改动 |
|---|---|
| `Loom/loom_render.py` | 323 行（+/- 合计，含 buckets numpy 化、天空盒失败可见、`_present_swap`） |
| `Loom/agent_commands.py` | 224 行（含 `engine_metrics` 的 `logic_metrics`） |
| `Loom/engine.py` | 118 行（含 `_clock_advance` / `get_logic_time_ratio`） |
| `Loom/loom_logic_thread.py` | 24 行（GIL 1ms + 改走 `_clock_advance`） |
| `Loom/loom_lighting.py` | 20 行（AABB `visible_only` 同帧记忆化） |
| `Loom/core_clock.py` | 13 行（截断/丢积压/累计计数） |
| 6 文件合计 | 580 insertions / 142 deletions |

### 0.2 关键函数清单

- `loom_render._prepare_bucket_frame`（555-693：全局桶计划 order/offs/sat_all/col_all/radius_all 生成，606-615 守卫，650-654 切片 gather，663-693 主/影通道写入）
- `loom_render._draw_main_buckets`（695-…，消费 `_main_bucket_n`）
- `loom_render` 文件尾 `shutdown`（1017-1022）
- `engine._clock_advance`（1365-1417）、`engine.get_logic_time_ratio`（1540-1551）、`engine.advance_logic`（1449-1512）、`engine.toggle_logic_paused`（1514-1530）
- `engine._logic_prep`（1277-1319）
- `loom_logic_thread._start/_stop/_logic_loop`（24-103）
- `loom_lighting._model_aabbs_par`（248-442，含 277-293 记忆化、433-437 发布）
- `agent_commands.cmd_engine_metrics`（1376-1440）

### 0.3 跑过的命令（全部在本机实测，python 3.12.10 / pygame 2.6.1）

```
python -m pytest tests/test_core_clock.py -q          -> 10 passed in 0.20s
python tests/_tmp/scan_beta5_03_01_logic_stop.py     -> RESULT: orphan_alive=1 second_start_threads=2 join_s=2.001
python tests/_tmp/scan_beta5_03_02_clock_advance.py  -> [A][B][C][D][E] 见 §2 P-02
python tests/_tmp/scan_beta5_03_03_buckets_ab.py     -> 11 个边界全部"字节一致=YES"
python tests/_tmp/scan_beta5_03_04_aabb_memo.py      -> [1]..[5] 见 §2 P-06
python tests/_tmp/scan_beta5_03_05_memo_mem.py       -> 单槽 5 元组，额外常驻 0.2 KB
```

> 说明：`tests/test_vk_bucket_order.py` 在模块级调用 `sys.exit(0)`（脚本式用例），
> 与 pytest 收集器冲突（`INTERNALERROR ... SystemExit: 0`），因此桶路径改用自建对拍探针
> （`scan_beta5_03_03`），对拍口径是**上传字节**而不是断言。

---

## 1. 粗筛清单（含跳过留痕）

| ID | 位置 | 标签 | 初步方向（指向具体代码事实） |
|---|---|---|---|
| P-01 | `loom_render.py:1017-1022` | BND-RESOURCE / AUDIT-DEADCODE | `run()` 退出段 `self._glfw_shutdown()` 被删，全仓再无生产调用点 |
| P-02 | `engine.py:1388-1389` | BND-TIME / SEM-MISMATCH | `wall_dt=min(now-last, maximum_logic_delta)`，而 `last` 只在 `_clock_advance` 内更新；暂停期无人更新 → 恢复首帧吃满 0.333 s |
| P-03 | `loom_logic_thread.py:50,73` | BND-CONCURRENCY / BND-RESOURCE | `_stop_logic_thread` 先把 `self._logic_stop=None` 再 `ev.set()`，循环条件读的是 `self._logic_stop` |
| P-04 | `loom_render.py:555-693` | IFACE-PARTIAL / BND-EMPTY | 桶计划与旧逐桶路径是否在所有边界逐位一致 |
| P-05 | `loom_render.py:610-611` | AUDIT-ASYMMETRY | 守卫只校验 `len(offs)`，不校验 `len(order)==offs[-1]` 与 `sat_all.shape[0]==len(order)` |
| P-06 | `loom_lighting.py:285-293` | OVERFIT-HARDCODE / AUDIT-DOCIMPL | 记忆化键只含 `(fw 身份, n, stamp3, 可见性序列)`，不含 fw 内容与 `id(models)` |
| P-07 | `engine.py:1549` | SEM-DEFAULT | `get_logic_time_ratio` 裸读 `self._logic_wall_sum`，同函数族其它读法全部 `getattr(..., 0.0)` 兜底 |
| P-08 | `core_clock.py:66-71` vs `engine.py:1523-1525` | DESIGN-CONFLICT | 时钟契约"每渲染帧最多追 maximum_logic_delta 秒"，暂停契约"不补暂停期欠账"，两条同时成立时互相矛盾 |

### 跳过登记表（每项附可审计理由）

| ID | 位置 | 跳过理由（四类之一 + 出处） |
|---|---|---|
| SKIP-01 | `loom_render.py:400-428` `_spheres_in_frustum/_frustum_keep` | 语言/API 规范保证：纯 numpy 向量运算，无分支副作用；且 71b31ac..HEAD 无 diff（`git diff` 未列出该区间） |
| SKIP-02 | `loom_render.py:663` `planes is not None and k > 1` | 非本轮引入：`git show 71b31ac:Loom/loom_render.py` 同一行同一条件；单实例桶不参与视锥剔除是既有语义 |
| SKIP-03 | `loom_raycast.py:162` `aabbs[i]` 用全量下标索引 `visible_only=True` 的过滤列表 | 非本轮引入（该文件不在 `71b31ac..HEAD` 的改动集内）；本轮记忆化不改变其返回内容的顺序或内容，行为与 71b31ac 相同 |
| SKIP-04 | `loom_lighting.py:918-934` `vis_aabbs=[aabbs[i] for i in vis_idx]` | 同上：不在本轮 diff 内；且 `need_bounds` 分支的过滤面与 `visible_only` 的语义冲突属 2026-09 历史问题 |
| SKIP-05 | `loom_render.py:926-975` `_present_swap/present_health/should_fallback_remote` | 契约明确声明：docstring 写"只给判据，不自行切换"，切换由入口层决定；本函数无未定义边界（`_glfw_win` 缺失被显式分支） |
| SKIP-06 | `core_clock.py:113-118` NaN 传播 | 新旧行为逐位相同（见 §2 P-09 实测）；本轮只新增计量字段，未改变 NaN 语义 |
| SKIP-07 | `engine.py:1320-1362 / loom_render.py 天空盒段` | 属"天空盒专项"（另一编号）范围，本报告只在 `_draw_skybox` 与桶/时钟无耦合处登记 |

---

## 2. 逐项裁决

### P-01 · `run()` 不再 `glfw.terminate()` —— 【P-PROVED / P2 / REGRESSION】

1. **判定基准**：`loom_glfw_window.py:402-407` 的 `_glfw_shutdown` docstring 原文："GLEngine.run 退出时调（替代 pygame.quit 的窗口部分）"。即契约规定 `run()` 退出必须调用它。
2. **代码证据**（原样引用）：
   - `git show 71b31ac:Loom/loom_render.py` 尾段：`        except Exception:\n            pass\n        # 2026-10-18 A2: GLFW terminate（原 pygame.quit）\n        self._glfw_shutdown()`
   - `HEAD` 版本 `loom_render.py` 尾段实测字节：`b'...try:\\n            self.audio.shutdown()\\n        except Exception:\\n            pass'`（无换行、无 `_glfw_shutdown`）
   - 删除提交：`git log -S "_glfw_shutdown()" -- Loom/loom_render.py` → `5042d68 fix(skybox): 默认蓝天 + ...`
3. **路径枚举（反手/证伪用）**——需要退出 GL 的**全部**路径：
   | 路径 | 是否调用 `_glfw_shutdown` |
   |---|---|
   | `RenderMixin.run()` 正常退出（`while self._running` 结束） | **否（已被删）** |
   | `RenderMixin.run()` 抛异常逃生 | 否（无 finally 包裹） |
   | Qt 宿主 `editor.py` 关闭 | 否（编辑器走 `_external_ctx`，从不建 GLFW 窗口，不需要） |
   | `build_entry.py:281` bench 收尾 | 否（同上） |
   | `loom_glfw_window._init_glfw_window` `create_window` 失败 | 是（`loom_glfw_window.py:131` 直接 `glfw.terminate()`，与本条无关） |
   → 枚举完备：`git grep -n "glfw.terminate" -- Loom/*.py` 只剩 `loom_glfw_window.py:131` 与 `:405`（`:405` 已无生产调用者）。
4. **实际行为**：`_glfw_shutdown` 成为**死代码**；`GLEngine.run()` 返回后进程继续持有一个未 terminate 的 GLFW 全局状态与窗口对象，直到进程退出由 OS 回收。
5. **差异**：契约要求"run 退出时终止 GLFW"，实际不终止。
6. **触发条件**：任何一个用 GLFW 窗口启动的播放器进程正常关闭（`Loom.py` 主路径 `engine.run()`）。
7. **验证**：
   ```
   git log -S "_glfw_shutdown()" -- Loom/loom_render.py     # 5042d68 删除
   git grep -n "_glfw_shutdown" -- Loom/*.py                # 只剩定义(loom_glfw_window.py:402)与 tests/_tmp 调用
   python -c "print(repr(open('Loom/loom_render.py','rb').read()[-60:]))"
   # b'try:\n            self.audio.shutdown()\n        except Exception:\n            pass'
   ```
8. **影响与等级**：P2（资源生命周期 / 可维护性）。窗口在 `run()` 返回后的收尾窗口期内不受 GLFW 管理；`_glfw_shutdown` 的 docstring 与实现冲突（AUDIT-DEADCODE）。

---

### P-02 · `_clock_advance` 把"停顿时长"补进逻辑时间 —— 【P-PROVED / P1 / REGRESSION】

1. **判定基准**：`engine.py:1523-1525` `toggle_logic_paused` 原文注释："暂停边界: 清 accumulator 余量 (恢复时从整拍开始, **不补暂停期欠账**)"，并紧接 `self._clock.reset()`。
2. **代码证据**：
   - `engine.py:1381-1389`：`last = getattr(self, '_logic_wall_last', None)` / `wall_dt = 0.0 if last is None else (now - last)` / `self._logic_wall_last = now` / `wall_dt = min(wall_dt, clk.maximum_logic_delta)` / `dt_eff = max(float(render_dt or 0.0), wall_dt)`
   - `engine.py:1477-1484`（暂停态）与 `loom_logic_thread.py:81-87`（暂停态）**都在调用 `_clock_advance` 之前 return/continue** → `_logic_wall_last` 在暂停期间冻结。
3. **路径枚举**：`_clock_advance` 的三个调用者——`engine.advance_logic:1497`、`engine.render` 自驱 `loom_render.py:819`、`loom_logic_thread._logic_loop:90`。三者都在"暂停态"被前置分支挡掉，因此**每一个调用者**都会在恢复后的第一次调用里看到 `now - _logic_wall_last = 暂停时长`。无路径能更新该值。
4. **预期**：恢复首帧沿用调用方 dt（≈8 ms），不补暂停期欠账（`toggle_logic_paused` 契约）。
5. **实际**：`wall_dt` 被截断到 `maximum_logic_delta=0.333`，`dt_eff=0.333`，`max_steps_per_frame=round(0.333/fdt)=10`，于是一帧内连跑 9~10 个逻辑帧。
6. **差异**：暂停 0.5 s 后恢复，旧路径该帧 0 步，新路径 9 步（`_acc` 0.0 → 0.025 余量）。多出的 9 步 = 暂停期欠账。
7. **验证**（实测输出，`scan_beta5_03_02_clock_advance.py`）：
   ```
   [A 0.5s 停顿] 旧: 总步=9 峰值单帧=1 | 新: 总步=19 峰值单帧=10 | 差=10 步
      旧逐帧[18:23]=[0, 0, 1, 0, 0]
      新逐帧[18:23]=[0, 0, 10, 1, 0]
   [B 暂停恢复] 旧首帧步=0 | 新首帧步=9
   ```
   复现命令：`cd Loom/tests/_tmp; python scan_beta5_03_02_clock_advance.py`
8. **影响与等级**：P1（功能正确性）。恢复瞬间脚本/物理/音频看到 0.333 s 时间跳跃：`on_update` 里按 dt 累计的计时器提前触发、物理一次追 10 帧、插值 alpha 跳变；且该"补账"不受暂停与卡顿区分——窗口拖动、模态文件对话框、场景加载后的第一帧同样命中。**注意**：对"掉帧补偿"而言这是设计目的（见 P-08 的设计冲突），但对"暂停"它直接违反 `toggle_logic_paused` 的显式契约。

---

### P-03 · 逻辑线程停止路径永不可达 + join 必超时 2 s —— 【P-PROVED / P2 / PRE-EXISTING】

1. **判定基准**：`loom_logic_thread.py:45-46` `_stop_logic_thread` docstring："停逻辑线程 (幂等; 退出/换场景调)"；`:61-63` 的 `t.join(timeout=2.0)` 隐含契约"停止后线程应已退出"。
2. **代码证据**：
   - `:49-50` `self._logic_thread = None` / `self._logic_stop = None`（**先清引用**）
   - `:59-60` `if ev is not None: ev.set()`（`ev` 是 `:47` 捕获的局部引用）
   - `:73` `while not (self._logic_stop is not None and self._logic_stop.is_set()):` —— 循环每轮读的是 `self._logic_stop`，此时恒为 `None`
3. **路径枚举**：循环退出只有两种可能——(a) `self._logic_stop` 被重新赋成"已 set 的 Event"；(b) `self._logic_stop is None` 时条件为 `not (False and ...)` = `True` → **继续循环**。代码中没有任何地方在 `_stop_logic_thread` 之后重新赋值 `_logic_stop`（`grep` 只有 `:28` 新建、`:50` 置 None），故 (a) 不成立 → 线程永不退出。
4. **预期**：`ev.set()` 后线程在一个循环体内退出，`join` 立刻返回。
5. **实际**：线程继续在 `is_playing` 分支每轮调 `_clock_advance`，`join` 等满 2.0 s。
6. **差异**：退出被延迟 2 s；进程留下一个永久 daemon 线程。
7. **验证**（`scan_beta5_03_01_logic_stop.py` 实测）：
   ```
   start: alive(loom-logic)=1
   stop: _stop_logic_thread() 耗时 2.001 s (内部 join timeout=2.0)
   stop 后 _logic_thread=None  _logic_stop=None
   stop 后 alive(loom-logic)=1
   stop 后 0.30s 内 _clock_advance 仍被调用 178 次
   再次 start 后 alive(loom-logic)=2  (1=正常复用, 2=双线程)
   ```
8. **影响与等级**：P2。**[PRE-EXISTING]**：`:73` 与 `:49-50` 在 71b31ac 中已如此（`git diff 71b31ac..HEAD -- Loom/loom_logic_thread.py` 只动了 GIL 段与 `:90` 的 `_clock_advance` 调用）。但**本轮改动放大了它**：孤儿线程现在也会写 `_logic_wall_last / _logic_dt_sum / _clock_calls_by_thread`，一旦"停→再启"出现双线程（实测 2 个），两个驱动者互相把对方的 `wall_dt` 压到 ≈0 → P-02 的"墙钟下限"静默失效，`logic_metrics.calls_by_thread` 会同时出现 `loom-logic` 与主线程两个键。E1 体检面本来就是为了判"是否双推"才加的，这个键正好把根因指出来了。

---

### P-04 · buckets numpy 化 vs 旧逐桶路径的边界等价性 —— 【P-DISPROVED】

1. **判定基准**：`loom_render.py:601-605` 注释："每帧只做 fw32[order] 一次 gather, 桶内退化为小切片拷贝 —— 字节源完全相同, 故数值逐位一致"；`loom_render.py:616-619`："算法与逐桶版逐项同源"。
2. **代码证据**：`G_all = fw32[order]`（615）；`g[:k] = G_all[a:b]`（652）；旧路径 `np.take(fw32, idxs, axis=0, out=g[:k], mode='clip')`（656）。`offs` 由每桶 `len(mc[0])`（恒等于 `kk`，因为 `mats[key][0]` 就是 `np.empty(kk)`）累加（574-576），故 `order[a:b] == idxs`。
3. **路径枚举**：0 物体 / 单物体 / 单实例桶 / 多桶 / 全剔除 / 零顶点网格 / NaN 矩阵 / 可见性 False / 关剔除（`frustum_cull=0`）/ 负半径注入 / 计划长度不符（11 条）。
4. **预期**：11 条边界下，每个桶 `main`/`sha` 缓冲写入字节与 `_main_bucket_n` 完全一致。
5. **实际**：11/11 一致（下表实测）。
6. **差异**：无。
7. **验证**（`scan_beta5_03_03_buckets_ab.py`，逐桶字节比对）：
   ```
   0 物体                          桶=0  mbn={}                          字节一致=YES
   1 物体 (单实例桶)                桶=1  mbn={('mesh','m1'): 1}          字节一致=YES
   3 物体 同桶                      桶=1  mbn={('mesh','m1'): 3}          字节一致=YES
   2 桶 各1                        桶=2  mbn={('mesh','m1'): 1, ...}      字节一致=YES
   全被剔除(远处)                    桶=2  mbn={('mesh','m1'): 0, ...}      字节一致=YES
   零顶点网格                       桶=1  mbn={('mesh','m0'): 2}          字节一致=YES
   NaN 世界矩阵                     桶=2  mbn={('mesh','m1'): 2, ...}      字节一致=YES
   可见性 False                    桶=2  mbn={('mesh','m1'): 1, ...}      字节一致=YES
   关剔除(frustum_cull=0)          桶=2  mbn={('mesh','m1'): 2, ...}      字节一致=YES
   负半径注入                       桶=2  mbn={('mesh','m1'): 0, ...}      字节一致=YES
   计划失效(offs 不符)              桶=2  mbn={('mesh','m1'): 2, ...}      字节一致=YES
   ```
8. **影响与等级**：无（P3 仅性能）。附带实测两条既有语义（非本轮引入）：单实例桶因 `k > 1` 门槛完全不进视锥测试；NaN 世界矩阵的实例会被剔除（`dist >= -rad` 对 NaN 恒 False），两条路径表现一致。

---

### P-05 · 桶计划守卫只校验 `len(offs)` —— 【P-DISPROVED（生产不可达）/ 建议加固】

1. **判定基准**：`loom_render.py:610-612` 注释 "计划不可用 -> 逐桶回退 (旧语义)"，即守卫的意图是"计划与当前桶集不一致时必须回退"。
2. **代码证据**：`if (order is None or offs is None or sat_all is None or col_all is None or len(offs) != len(self._render_buckets) + 1): order = None`。守卫**不**校验 `len(order) == offs[-1]`，也**不**校验 `sat_all.shape[0] == len(order)`。
3. **路径枚举（反手）**：计划四个字段 + `_render_buckets` 的全部写入点——`loom_render.py:510`（桶表）、`:577/:578/:579/:581`（计划四件）、`:598`（radius）、以及 `engine.py:322`/`loom_model_gpu.py:258`（构造期置空）。结论：**除构造期置空外，`_render_buckets` 与四个计划字段只在同一个 `if _bucket_grp_sig != stamp3 ...` 块内被同时重建**，顺序固定为先桶表后计划；中途抛异常会终止本渲染帧（`editor.py:2287` 的 `_profile('buckets', ...)` 不吞异常），下一帧因 `_bucket_grp_sig` 已置而跳过该块——但此时旧计划与新桶表的**数量**必然不同（否则同一 stamp 下不会重建），`len(offs)` 守卫即命中回退。逐条枚举后没有一条能构造出"数量相同而内容不同"的组合。
4. **预期**：任何"计划与桶集不一致"都回退旧路径，不得崩溃。
5. **实际**：**外部注入**不一致状态（先跑一帧生成计划，再把 `_bucket_order` 换成空数组并清 `_bucket_frame_sig`）→ `ValueError: could not broadcast input array from shape (0,4,4) into shape (2,4,4)`，抛出点 `loom_render.py:652`。
6. **差异**：守卫不足以防"长度合法但内容错"，但该状态无生产构造路径。
7. **验证**：
   ```
   cd Loom/tests/_tmp; python scan_beta5_03_03_buckets_ab.py
   # 最后一项 '空 order 但桶非空' -> ValueError at loom_render.py:652
   ```
8. **影响与等级**：P2（防御深度）。四象限里这一项曾同时"反手成功 + 正手成功"，按 §9.2 复查发现正手链的触发条件用的是**私有状态注入**（`_bucket_order=[]`+`_bucket_frame_sig=None`），不是合法输入/真实状态，故正手链作废，降级为 P-DISPROVED。**仍建议**把守卫扩成 `len(order) == offs[-1] and sat_all.shape[0] == len(order) == col_all.shape[0]`，成本为零。

---

### P-06 · AABB `visible_only` 同帧记忆化的失效面 —— 【P-DISPROVED】

1. **判定基准**：`loom_lighting.py:282-284` 注释："按 (fw 对象本体, n, stamp3, 可见性序列) 记忆化 … **数值与首次逐位相同**"；`:292` "★键里持 fw 强引用 (活对象 id 唯一, 不会与后建数组 id 复用)"。
2. **代码证据**：`:285-293` 命中判定；`:435-437` 发布 `self._aabb_vis_cache = (fw, n, stamp3, _vis_key, out)`。
3. **路径枚举（反手）**——要求：所有能让"内容变而键不变"的写者都被排除。
   | 让 fw 内容变的途径 | 是否改变键 | 结论 |
   |---|---|---|
   | 位姿变化 → `compute_world_matrices` → `pipeline_glue.world_matrices`（`pipeline_glue.py:242` `world = np.empty((n,4,4))` **每次新分配**） | `fw is` 变 | 失效 ✔ |
   | 静止帧 → `_fw_cache` 命中返回**同一对象**（`loom_transform.py:148-153`） | 内容本就未变 | 命中合法 ✔ |
   | 就地改 `_frame_world` | 键不变 | **需排除写者**：`loom_transform.py:131` "★返回对象跨帧复用, 消费方禁原地改 (已核对: `_frame_world` 无原地写消费者)"；`grep -n "_frame_world\[" Loom/*.py` 无赋值型写者 |
   | `m.mesh` 改（桶/LOD） | `GameObject._appearance_gen += 1`（`loom_game_object.py:219`） | 失效 ✔ |
   | `m.visible` 改 | `_appearance_gen += 1`（`loom_game_object.py:259`）+ 键里另有 `_vis_key` | 双保险失效 ✔ |
   | 增删物体 | `_struct_gen`/`n` | 失效 ✔ |
   `stamp3` 的 `_appearance_gen` 是**类级全局计数器**（`loom_game_object.py:66`），单调递增、无回绕风险（Python int 无溢出）。
4. **预期**：键不变 ⟹ AABB 内容必然相同。
5. **实际**：实测三种"键不变而内容变"的构造（就地改 fw；桩对象直改 `.mesh` 不 bump stamp；不同 models 列表同 fw）确实返回陈旧 list，但三条都依赖**违反白盒契约**的写者（见第 3 段表格），生产代码无此写者。
6. **差异**：无（在契约内）。
7. **验证**：
   ```
   cd Loom/tests/_tmp; python scan_beta5_03_04_aabb_memo.py
   [1 同 fw 同模型] 同 list 对象=True  AABB 相同=True
   [2 新 fw 对象(物体移动 100)] 命中旧值=False  新 AABB x=99.00
   [3 fw 就地改写] 命中=True  AABB x=-1.00      <- 违反"禁原地改"契约才发生
   [4 可见性翻转] 前=2 项 后=1 项               <- 正确失效
   [5 换网格但 stamp 不变] 返回同一 list=True   <- 桩对象不 bump _appearance_gen 才发生
   ```
   内存：`scan_beta5_03_05` 300 帧（每帧新 fw 对象）后 `_aabb_vis_cache` 仍是 5 元组单槽，
   额外常驻 = 1 个 fw 数组 + 1 个 out list（2 模型 0.2 KB），**不随帧数增长**。
8. **影响与等级**：P3（仅加固建议：把 `id(models)` 加进键可消除"外部传不同 models 列表"这一档；但当前无生产调用者传非 `self.models`）。

---

### P-07 · `get_logic_time_ratio()` 裸读未初始化字段 —— 【P-DISPROVED（不会外溢成崩溃）/ P3】

1. **判定基准**：同文件相邻代码一律用 `getattr(self, '_logic_dt_sum', 0.0)`（`engine.py:1390-1391`）、`agent_commands.py:1401-1415` 全量 `getattr` 兜底；`engine._ensure_split` docstring 明写"测试桩 `__new__` 路径兜底: `__init__` 未跑时…"。
2. **代码证据**：`engine.py:1549-1551` `if self._logic_wall_sum <= 1e-9: return None` / `return self._logic_dt_sum / self._logic_wall_sum` —— 唯一一处裸属性读。
3. **路径枚举**：调用者只有两处——`build_entry.py:246-249`（`try/except` 包住，失败 → `ratio=n/a`）、`agent_commands.py:1398-1400`（整个 `logic_metrics` 组装块被 `try/except` 包住，失败 → `out['logic_metrics'] = 'err:...'`）。两处都不会让异常外溢成崩溃。
4. **预期**：桩引擎上返回 None（"还没采到样本"）。
5. **实际**：`AttributeError("'GLEngine' object has no attribute '_logic_wall_sum'")'`（`scan_beta5_03_05` 实测）。
6. **差异**：返回值类型从 `None` 变成异常；消费方降级（`err:` 整块丢失其余 14 个字段）。
7. **验证**：`python tests/_tmp/scan_beta5_03_05_memo_mem.py` → `[metrics] 桩引擎 get_logic_time_ratio() 抛: AttributeError(...)`
8. **影响与等级**：P3。生产路径 `__init__` 必跑，故不可达；但同族代码风格不一致，且 `logic_metrics` 会从"可读的一条"退化成"一个错误串"。

---

### P-08 · 白盒层设计冲突：掉帧补偿 vs 暂停不补账 —— 【P-UNKNOWN → HUMAN-ARBITRATION】

1. **判定基准（两条互斥的自身契约）**：
   - A：`core_clock.py:66-71` "步数上限自适应…**每渲染帧最多追 maximum_logic_delta 秒的逻辑时间** (Unity Time.maximumDeltaTime 精神)" —— 追帧是**设计目的**。
   - B：`engine.py:1523-1525` "暂停边界: 清 accumulator 余量 (**恢复时从整拍开始, 不补暂停期欠账**)" —— 停顿后的欠账**必须丢弃**。
2. **代码证据**：两条契约由**同一个** `_clock_advance` 实现（`engine.py:1388-1389`），代码里没有任何"这次间隔是暂停还是掉帧"的区分信号。
3. **推理**：P-02 已证真"恢复首帧吃满 0.333 s"。要判定这是 bug 还是补偿机制的必然代价，必须先判"停顿 0.333 s 的成因属于掉帧还是品'停'"，而 `_clock_advance` 只有 `(render_dt, wall_dt)` 两个输入，信息不足以区分。
4. **反手（证伪"这是 bug"）失败**：无法构造"停顿永远等价于掉帧"的证明——暂停/窗口拖动/模态对话框/场景加载与真实掉帧在时钟视角下不可分辨。
5. **正手（证真"这是 bug"）失败**：对"掉帧补偿"而言 10 步正是 W 契约要求的正确行为；只有站 B 契约才叫 bug。判据本身冲突。
6. **差异**：无法在没有设计裁决的情况下定方向。
7. **验证**：P-02 的 `[A]/[B]` 两组实测输出即为全部证据。
8. **判定**：P-UNKNOWN（白盒层 `DESIGN-CONFLICT`）。需要的裁决见 §5 Q1。

---

### P-09 · NaN / 负 dt / 0 dt 三条边界（对照旧行为） —— 【P-DISPROVED（非回归）】

1. **判定基准**：`core_clock.py:113-117` `_raw = max(render_dt, 0.0)` / `dt = min(_raw, maximum_logic_delta) * time_scale`。
2. **代码证据**：新旧都经过 `core_clock.advance`；新入口只是把 `render_dt` 换成 `dt_eff = max(render_dt, wall_dt)`。
3. **路径枚举**：`dt` 为 NaN / 负 / 0 → 旧径 `clk.advance(dt)`；新径 `_clock_advance(dt, clk)`。
4. **预期/实际**（`scan_beta5_03_02` 实测）：
   ```
   [C dt=负(-0.5)] 旧步=0 旧acc=0.0            | 新步=1 新acc=0.025078566706428926
   [C dt=零(0.0)]  旧步=0 旧acc=0.0            | 新步=1 新acc=0.025007466747115056
   [C dt=NaN]      旧步=0 旧acc=nan            | 新步=0 新acc=nan
   [D NaN 之后] 新: acc=nan steps=0 alpha=0.0 | 旧: acc=nan steps=0 alpha=0.0 | ratio=nan
   ```
5. **差异**：负/0 dt 从"零推进"变成"按墙钟推进一帧"（语义变更，但无调用者传非正 dt：三处调用者分别传 `render_dt`、`delta_time` 与实测 `dt`，`step_once` 走 `clk.advance(0.0)` 不经本入口）。
   NaN 两条路径**同样**把 `_acc` 永久污染成 NaN（`min(nan, 0.333) = nan`），非本轮引入。
6. **新增暴露面**：NaN 之后 `_logic_dt_sum` 变 NaN、`_logic_wall_sum` 仍有限 → `get_logic_time_ratio()` 返回 `nan` 而不是契约里的 `None`，`engine_metrics.logic_metrics.ratio` 打印 `nan`。
7. **验证**：同上命令。
8. **影响与等级**：P3。`perf_counter` 是单调钟，不存在回绕；`wall_dt < 0` 已有 `:1383-1384` 钳制。

---

### P-10 · 指标字段的线程安全与读数一致性 —— 【P-DISPROVED（仅诊断面，不影响推进）/ P3】

1. **判定基准**：`agent_commands.py:1394-1395` 注释把 `logic_metrics` 定位为"只读体检面"；`loom_logic_thread.py:95` 注释"单点发布 (原子引用替换), 渲染侧一次读, 不混用新旧半套"。
2. **代码证据**：`_logic_dt_sum/_logic_wall_sum/_logic_steps_total/_logic_calls_total` 在逻辑线程里 `getattr + 加 + 赋回`（`engine.py:1390-1391, 1411-1412`），主线程在 `agent_commands.py:1401-1404` 读同一个属性。
3. **路径枚举**：正常单驱动（`is_async_active` 门控，`editor.py:2256` / `loom_render.py:802`）→ 只有**一个**写者、一个读者，GIL 保证 float/int 单次赋值原子，读者最多看到"少加一次的中间值"，不会读到半个对象。P-03 的孤儿线程场景 → 两个写者，读数会重复计数，但该场景本身已由 P-03 单独立项。
4. **预期**：诊断字段允许 ±1 次采样误差，不影响推进。
5. **实际**：符合。唯一语义陷阱：`clock.steps_total`（`core_clock.py:139`）在 F10 单步路径（`step_once` 不走 `_clock_advance`）也会 +1，而 `engine._logic_steps_total` 不会 → `logic_metrics` 里两个累计值会出现固定差额。两个值并列给出（`agent_commands.py:1401` 与 `:1406`），读数者可自行对账。
6. **差异**：无功能影响，只是两套账本口径不同。
7. **验证**：`Select-String -Path Loom\engine.py -Pattern "_logic_steps_total|steps_total"`；`core_clock.py:139`。
8. **影响与等级**：P3（可维护性）。

---

## 3. 统计

| 结论 | 数量 | 明细 |
|---|---|---|
| P-PROVED | **3** | P-01（P2，`_glfw_shutdown` 删除 / REGRESSION）、P-02（P1，暂停恢复补 0.333 s / REGRESSION）、P-03（P2，`_logic_stop` 永不可见 → join 2 s + 孤儿线程 / PRE-EXISTING） |
| P-DISPROVED | **5** | P-04（桶 A/B 11 边界逐字节相同）、P-05（计划守卫不足但生产不可达）、P-06（AABB 记忆化失效面完备、内存单槽）、P-07（桩引擎 AttributeError 不外溢）、P-09（NaN/负 dt 非回归）、P-10（诊断字段线程安全） |
| P-UNKNOWN | **1** | P-08（白盒层设计冲突：掉帧补偿 vs 暂停不补账 → 人类裁决） |
| P-CONTRADICTION | **0** | 曾出现一次疑似矛盾（P-05"反手成功且正手成功"），按方法论 §9.2 复查后查明**正手链用私有状态注入当触发条件**，正手链作废 → 降级 DISPROVED。除此之外没有两项链同时成立的项。 |
| 跳过项 | 7 | SKIP-01..07，每条附四类理由之一与出处 |
| REGRESSION 标记 | 2 | P-01、P-02（均由 71b31ac..HEAD 引入） |

---

## 4. 修复建议排序（只给方向，不含代码）

| 序 | 项 | 等级 | 方向 |
|---|---|---|---|
| 1 | P-02 | P1 | 给 `_clock_advance` 加"停顿归零"契约：暂停/进入播放/场景切换时把 `_logic_wall_last` 一并置 None（与 `clk.reset()` 同点），或让调用方显式告知"本次间隔可信"。判据必须与 `toggle_logic_paused` 的"不补暂停期欠账"同源。 |
| 2 | P-01 | P2 | 恢复 `run()` 退出段的 `_glfw_shutdown()`，用 `try/finally` 包住整个退出清理，使异常逃生路径也终止 GLFW。 |
| 3 | P-03 | P2 | 停止时要么先 `ev.set()` 再清 `self._logic_stop`，要么让循环只读捕获的局部 `ev`（当前读的是实例字段）。修完补一条"stop 后 `_logic_thread` 已死 + join < 100 ms"的回归。 |
| 4 | P-05 | P2 | 守卫补 `len(order)==offs[-1]==sat_all.shape[0]==col_all.shape[0]`（三项零成本断言，把"物理不可达"变成"结构上不可能"）。 |
| 5 | P-06 | P3 | 记忆化键补 `id(models)`；并在 `_aabb_vis_cache` 命中分支补一条"debug 模式下 value 复算断言"的逃生门。 |
| 6 | P-07/P-10 | P3 | `get_logic_time_ratio` 改 `getattr(..., 0.0)`；`logic_metrics` 增加 `steps_total_engine` / `steps_total_clock` 的差字段说明。 |
| 7 | P-09 | P3 | `_clock_advance` 对 `dt_eff` 做 `math.isfinite` 闸：非有限值 `return (0, 0)` 并打一次告警，避免一次 NaN 永久废掉时钟与 ratio。 |

---

## 5. 需要人类裁决的封闭问题

**Q1（P-08 / P-02 的方向）**：`_clock_advance` 用 `wall_dt` 做下限时，"两次推进之间的长间隔"应如何处理？

- A：**一律补偿**（当前实现），最大 0.333 s／帧 —— 掉帧时的 TPS 读数真实，但暂停/窗口拖动/场景加载后恢复瞬间会一次跑 9~10 个逻辑帧（违反 `toggle_logic_paused` 的"不补暂停期欠账"）。
- B：**暂停点显式归零**：在 `toggle_logic_paused`、`is_playing` 翻转、`clk.reset()` 三处同时把 `_logic_wall_last` 置 None（补偿保留给掉帧，暂停不补账）。
- C：**一律不补偿**（回退到 `render_dt` 单输入），保留 `ratio` 只做读数 —— TPS 会重新被 dt 口径低估（E1 的原始现象回归）。

请裁决 A / B / C（B 为本报告的倾向，因为它同时满足两条契约；但这是路线选择，不由 AI 拍板）。

**Q2（P-01）**：`run()` 退出清理是否允许改成 `try/finally` 包裹（会在 `_dispatch_application_quit` 之前就终止 GLFW，影响"退出时脚本还要用引擎"的时序）？

- A：保持现时序，只在最后补回 `_glfw_shutdown()`（异常逃生仍不终止）。
- B：`try/finally` 包裹，退出清理全部纳入，异常逃生也终止 GLFW（时序变化需确认 `on_application_quit` 契约）。

**Q3（P-03）**：修 `_stop_logic_thread` 时是只改循环退出条件（最小改动，保留"停→启"会起新线程的语义），还是同时禁止同一引擎实例重复起线程（更严格，但会让"停→启"变成 no-op，需确认 Qt 宿主关窗/开窗流程）？
