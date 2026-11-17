# 编号 02 · beta6 性能与门禁数字复核（任务后倒查 / 第八轮）

> 只读倒查。未参与实现。基线 `git rev-parse HEAD` = `ee83e4b`（工作区无并发修改）。
> 除本文件与 `Loom/tests/_tmp/verify_02_*.py`（本轮探针）外，未写入任何文件。
> 所有"实测"均为本轮独立复跑（探针自造负载），**不引用交付方报告里的数值**；交付方数字只作为"宣称值"列在对照表里。

## 0. 范围、基线与复跑环境

| 项 | 值 |
|---|---|
| 仓库根 | `D:\my-project - 副本\Loom(py源代码-工作区)` |
| HEAD | `ee83e4b chore: 收尾 loom_pass_gl 与两份最终验收报告（F-03/F-04）` |
| 主解释器 | `py -3.13` = Python 3.13.15（项目主线，与 final_03 的跑法一致） |
| 交叉解释器 | `python` = 3.12.10（说明数字对解释器的敏感性） |
| 派单范围 | `Loom/loom_assets.py`、`Loom/loom_components.py`、`tests/test_animation_base.py`、`tests/test_bucket_pack.py`、`tests/test_aabb_simd.py`、`tests/test_physics_pose_soa.py` |
| 范围外但实际承载项② | `record_asset_error` 在 **`Loom/sceneio.py:218`**（不在派单文件清单里），本轮一并复核 |

复跑命令（工作目录 `Loom/`）：

```
python tests/_tmp/verify_02_a_assets.py          # ① 10k 索引（V02_ENTRY=plain|import|fingerprint）
python tests/_tmp/verify_02_c_err_sinks.py      # ② 5000 次错误（三种 stdout 汇）
python tests/_tmp/verify_02_b_anim.py           # ③ 500 动画物体 3 次取中位
py -3.13 tests/test_animation_base.py           # ④ 阈值/docstring 现场
py -3.13 tests/test_bucket_pack.py
py -3.13 tests/test_aabb_simd.py
py -3.13 tests/test_physics_pose_soa.py
```

---

## 1. 验证项与实测对照

### ① 资产索引 10k 条：`load_index` / `validate_index` / `inspect_index`

自造 10k 条（临时目录，按 `save_index` 的生产写盘格式 `indent=2, sort_keys=True`），三种条目形态各跑 3 次：

| 形态（每条的字段） | 文件大小 | `load_index` 冷（3 次） | 中位 | `validate_index` | `inspect_index` 冷 | `load_index` 热 |
|---|---|---|---|---|---|---|
| `{type,src}` | 940,039 B | 29.6 / 33.1 / 32.9 ms | **32.9 ms** | 19.4 ms | 30.8 ms | 0.114–0.220 ms |
| `{type,src,import}`（默认导入设置） | 2,910,039 B | 60.5 / 59.8 / 61.1 ms | **60.5 ms** | 20.0 ms | — | — |
| `{type,src,import,fingerprint}`（真实导入形态） | 4,661,063 B | 73.9 / 77.2 / 80.5 ms | **77.2 ms** | 19.7 ms | 80.6 ms | — |

结论：
- **"10k 冷加载从 8 秒级降到几十毫秒"成立**（8190.8/8660 ms → 33–77 ms，约 100–260x）。`validate_index` 已无逐条文件系统调用（`loom_assets.py:297-321` 纯字符串判定），实测 1.94 µs/条。
- **宣称值 54.6 ms 无法精确复现**：本机三种形态给出 32.9 / 60.5 / 77.2 ms，54.6 落在区间内但不对应任何一种可复述的条目形态（提交信息未写文件大小/条目字段）。热路径（`_index_snapshot` 缓存，`loom_assets.py:227-261`）实测 0.11–0.22 ms，与"二次读 ≤50ms"的宣称一致（远好于）。
- `validate_index` 宣称 24.3 ms，实测 19.4–20.0 ms（3.13）/ 23.6–25.1 ms（3.12）——在 3.12 上可复现，3.13 上快约 20%。

### ② `record_asset_error` 5000 次耗时与截断

三种输出汇（同一个 5000 次唯一错误循环，探针 `verify_02_c_err_sinks.py`）：

| 汇 | 3.13 实测 | 3.12 实测 |
|---|---|---|
| `io.StringIO` | 7.3 ms | 7.3 ms |
| `os.devnull` | 7.1 ms | 8.1 ms |
| 真 stdout | 8.3 ms | 8.0 ms |

截断/计数（`sceneio.py:244-252`）：

```
len(errs)=200  limit=200  overflow=4800  count=5000  printed_lines=200
第201条: len=200 count=201 overflow=1 末项=('w','g199','r199')
5000 次重复(全去重): len=1 count=1  3.2 ms
```

结论：
- **截断语义与宣称完全一致**：列表硬上限 200（`ASSET_ERROR_LIMIT=200`，`sceneio.py:205`）、超出只累加 `_asset_error_overflow`（`sceneio.py:246-250`）、总数 `asset_error_count` 含溢出（`sceneio.py:260-267`）、去重后重复项不增长（`sceneio.py:241-243`）。
- **耗时对不上**：交付方宣称 `386.9ms → 29.5ms/5000 条`（提交 `80ee837` 信息），实测 **7.1–8.3 ms**（3.13/3.12 × StringIO/devnull/真 stdout 六个组合），比宣称快约 3.6–4x。方向是"宣称更慢"，不是夸大；但 29.5 ms 这个数在本机无法复现，口径（终端/sink/是否含预热）未记录。
- **受跟踪测试的门禁过松**：`tests/test_asset_guid.py:1166` 断言 `dt <= 500` ms。相对实测 8 ms 有 62x 余量——一次 50x 的性能回退（8→400ms）仍会绿。这条不是本次派单文件，但它是②唯一进门禁的断言。

### ③ 500 动画物体 `update_animations` 单帧耗时（3 次取中位）

自建 500 模型 + 11 帧片段（不 import 被测测试文件），60 帧/次 × 3 次：

| 解释器 | 3 次 | 中位 | 测试脚本自身 3 次 | 旧逐物体（同脚本内联） | 倍率 |
|---|---|---|---|---|---|
| 3.13.15 | 1.440 / 1.473 / 1.490 ms | **1.473 ms** | 1.348 / 1.395 / 1.402 ms（另一次 1.414） | 12.770–13.196 ms | 9.2–9.5x |
| 3.12.10 | 1.403 / 1.559 / 1.468 ms | **1.468 ms** | 1.534 / 1.555 / 1.583 / 1.675 ms | 11.6–12.6 ms | 7.5–8.0x |

结论：
- 复跑区间 **1.35–1.69 ms**：3.13 测试脚本 1.35–1.41、独立探针中位 1.47、3.12 最高 1.675；宣称区间 1.42–1.69 覆盖探针与 3.12，但比 3.13 脚本实测偏高约 1–5%。`2.0 ms` 门禁通过且有余量（约 18–48%）。
- **`≤1.0 ms` 目标确实未达成**（1.47 > 1.0，探针直接判定 False）；`≈8–9x` 在 3.13 上被实测超过（9.2–9.5x），3.12 上为 7.5–8.0x——**倍率是解释器相关数**，设计文档未标注这一点。

### ④ 门禁与承诺：测试阈值 / docstring / 设计报告 三处是否统一

| 位置 | 数字 | 是否承认 ≤1.0 未达成 |
|---|---|---|
| `tests/test_animation_base.py:268-275` | 稳定门禁 **2.0 ms** + 相对旧实现 **≥5x**；标签写明"实测≈1.5ms; ≤1.0ms 目标未达成" | ✅ 明说 |
| `loom_components.py:799-804`（`evaluate_animations` docstring） | "**1.42–1.69ms/逻辑帧**（旧 12.7–13.1ms，约 8–9x）… 想真到 ≤1ms 需要 batch2 重构" | ✅ 明说 |
| `docs/design/research_beta6_03_animation.md:511`（S2 行） | 原文 ~~≤1.0ms~~ 划掉，写"**实测 1.42–1.69ms，目标未达成**；落地口径 2.0ms + ≥5x" | ✅ 明说 |
| `docs/design/research_beta6_03_animation.md:516`（批次 1 出口判据） | 仍写"**500 物体动画 ≤1ms**"，无划线/未达成标注 | ❌ **残留** |
| `docs/design/版本计划_...:465` | "C1 动画内核唯一化（**115 PASS**）" | 实测 `test_animation_base.py` = **126 PASS**（3.13/3.12 同） |
| 提交 `5ebd57b` 信息 | "统一为实测 **1.61ms**（1.613ms）" | 与 1.42–1.69 区间一致；但测试标签写死"≈1.5ms"、3.12 实测单次可到 1.675 |

判定：
- **三处核心表述已统一**：测试、docstring、设计 S2 都把 1.0 标为"未达成"，2.0 只作"稳定门禁"且写明原因；**没有"用 2.0 冒充 1.0"的代码/注释残留**（`≤1ms` 在代码注释里只剩 `loom_components.py:802` 的"未达成"陈述；测试 :270/:273 也明写未达成）。
- **残留 1（文档）**：设计报告 §516 的"出口判据 ≤1ms"没跟着 S2 更新，仍把未达成目标当出口条件（与 511 自相矛盾）。
- **残留 2（计数）**：版本计划 9.23 的 "115 PASS" 已过期（现 126）；条数只增不减，属陈旧而非夸大。
- **口径残留 3（倍率/平台）**：8–9x 是 3.13 数字，3.12 实测 7.5–8.0x；文档未标平台。

### ⑤ 三个内核测试是否"只调 helper、没有入口证据"

逐个核对（受跟踪测试文件，非 `_tmp`）：

**A. `tests/test_bucket_pack.py` —— 只测 `fastpath.bucket_pack` 本身，无生产入口**

- 该文件只 `import fastpath`（`:30`），只调 `fastpath.bucket_pack(...)`（`:77`）；参考实现是**手工直译的副本** `ref_pack`（`:42-65`，注释自认"现行 _prepare_bucket_frame 的语义直译"）。
- 全仓 grep `_bucket_pack_frame|_bucket_pack_ready|_prepare_bucket_frame|LOOM_BUCKET_LEGACY` 在受跟踪测试里**只命中本文件的注释**（`:11/:43`），0 处调用。
- 生产入口在 `loom_render.py:693-697`（条件 + `_bucket_pack_frame`）→ `loom_render.py:841`（真正调 `fastpath.bucket_pack`），另有 `LOOM_BUCKET_LEGACY=1` 的 A/B 开关（`loom_render.py:666`）和 `_bucket_pack_ready` 的不可用回退（`loom_render.py:790-808`）。
- **缺的证据**：① 驱动 `_prepare_bucket_frame` 一次真实帧、与 Python 逐桶路径逐字节对拍（现在对拍的是手抄副本，入口改坏/漂移测试不会红）；② 内核不可用时 `_bucket_pack_ready=False` 的回退字节一致；③ `LOOM_BUCKET_LEGACY` 两档产物一致；④ `_main_bucket_n`/staging buffer 与真实 buffer 写入的一致性；⑤ 该文件**没有任何耗时断言**（D1 的 `buckets ≤1.0ms` 承诺没有受跟踪门禁）。

**B. `tests/test_aabb_simd.py` —— 只测 `fastpath` 包装，且"分派"不可观测**

- 只 `import fastpath`（`:30`），调 `aabbs_minmax_impl`（`:53`）、`aabbs_minmax`（`:94`）。生产链是 `loom_lighting.py:444` `_aabbs_batched` → `:614-617`（按 n×V 工作量闸门切串行/并行）；受跟踪测试 grep `_aabbs_batched|aabbs_minmax` 仅命中本文件 5 行，**0 处调生产入口**。
- 断言②/④ 比较"scalar vs avx2 vs auto **逐位相同**"——但设计本身规定三者逐位相同，所以**相等无法证明 avx2 分派真的被选中**；在无 AVX2 机器上 `:87-88` 直接 SKIP 仍绿。`:96` 的"公开入口"实为 `fastpath.aabbs_minmax` 包装（`fastpath.py:288-291`），不是生产调用点。
- **缺的证据**：① 用 spy/计数证明 `loom_aabbs_minmax` 内部分派到 avx2（或至少驱动 `aabbs_minmax_impl(...,'avx2')` 与 `'scalar'` 在真实组形态下逐位）；② `loom_lighting` 分组与 `_AABB_PAR_MIN_WORK` 闸门（`loom_physics.py:744`）的入口覆盖；③ 生产入口的空批/非连续/形状错误路径；④ **设计验收要求的 `LOOM_NO_SIMD=1` 回退开关在代码中不存在**（`research_beta6_04:291`；全仓 grep 0 命中），无 AVX2 的回退只能靠换机器验证；⑤ 无耗时断言（D1 `buckets ≤1.0ms`、D3 `mt_aabb_minmax ≤0.7ms` 均未进门禁）。

**C. `tests/test_physics_pose_soa.py` —— 只测私有 `_pose_rows`，不测消费方**

- 用 `PhysicsWorldBridge.__new__` + `StubModel`（`:51-54`），9 处直接调 `br._pose_rows(...)`（`:61-86`）。受跟踪测试里 `_dirty_mask_batch|LOOM_POSE_SOA|_pose_rows` 只命中本文件，**0 处调 `pre_step`/`_dirty_mask_batch`**。
- 生产链：`engine.py:1237-1246` 抓 `(models,pos,rot)` 平面（受 `LOOM_POSE_SOA=0` 控制）→ `physics_pipe.py:63-68` 传 `pose=` → `physics_bridge.py:1147` `_dirty_mask_batch(...,pose=)` → `:1062` `_pose_rows`。测试只覆盖最末端的纯函数。
- **缺的证据**：① `_dirty_mask_batch(entries, pose) == _dirty_mask_batch(entries, None)` 的随机对拍（同一批位姿，SoA 与属性链两条路给出同一 dirty 集合）；② `pre_step` 级入口（真实 entries/祖先链）在 `pose=None` 与 `pose≠None` 下结果一致；③ `LOOM_POSE_SOA=0` 逃生门覆盖；④ 平面形状对但节点是祖先/幽灵的真实场景（当前 ④ 用 `ms + [ghost]` 覆盖了 ghost 查表，但仍在私有函数层）。
- 附注：④/`:77` 的 `_pose_rows(ms + [ghost], pose)` 之所以返回 None 是"节点不在平面 id 表"（`physics_bridge.py:1008-1011`），测试意图成立；但整份文件仍是 private-helper 级，不构成入口证据。

---

## 2. 不实 / 对不上的地方（按严重度）

| # | 级别 | 内容 | 证据 |
|---|---|---|---|
| V-02-1 | **P1（门禁缺口）** | 三个内核测试全部只调 helper，0 处生产入口调用；入口接错/回退坏/分派失效均不会被现有测试抓到 | 上节 A/B/C；grep 命中仅注释/私有函数 |
| V-02-2 | **P1（门禁缺口）** | D1/D3 的**性能承诺没有受跟踪门禁**（`test_bucket_pack`/`test_aabb_simd` 无耗时断言）；②的唯一定时门禁是 500ms（`test_asset_guid.py:1166`，62x 余量）；D3 验收要求的 `LOOM_NO_SIMD=1` 回退开关在代码中 0 命中（`research_beta6_04:291`） | 文件全文 + `:1166`；grep |
| V-02-3 | **P2（数字不可复现）** | 10k 冷加载宣称 54.6ms；实测 32.9 / 60.5 / 77.2ms（三种条目形态），54.6 无对应形态、提交信息未记录文件大小 | `80ee837` 提交信息；探针 A 输出 |
| V-02-4 | **P2（数字对不上）** | 5000 次错误宣称 29.5ms；实测 7.1–8.3ms（三 sink 两解释器）。偏保守，但数字不可复现 | `80ee837`；探针 C |
| V-02-5 | **P2（文档自相矛盾）** | 设计 §516 "批次1出口判据 500 动画物体 ≤1ms" 未随 §511 更新，仍把未达成目标当出口条件 | `research_beta6_03:516` vs `:511` |
| V-02-6 | **P3（陈旧计数）** | "C1 115 PASS" 与实测 126 PASS 不符；"8–9x" 只在 3.13 成立（9.2–9.5x；3.12 为 7.5–8.0x） | `版本计划:465`；本轮跑数 |
| V-02-7 | **P3（口径不一）** | 旧基线在三处写成 313ms（版本计划:476）/ 386.9ms（提交 80ee837）/ 8190.8ms（提交）vs 8660ms（版本计划:470） | 三处原文 |
| V-02-8 | **P3（测试过拟合）** | `test_aabb_simd.py:89` 的④与②重复且恒真（设计上两路逐位相同）；`test_animation_base.py:273` 标签写死"≈1.5ms"，不做中位/多跑 | 文件行号 |

**没有发现**的（反手证伪通过）：截断/溢出/去重语义与宣称一致；`once` 末帧、`LOOM_POSE_SOA` 等行为不在本轮范围；"用 2.0 冒充 1.0"在测试/docstring/S2 三处已消除，只剩 §516 一条陈旧出口判据。

---

## 3. 结论

| 验证项 | 判定 | 一句话 |
|---|---|---|
| ① 10k 索引 | ✅ 达成（数量级），◐ 数字不可精确复现 | 33–77ms（形态相关），8 秒级问题已消除；54.6ms 口径缺失 |
| ② 5000 错误 + 截断 | ✅ 达成 | 7–8ms；200 条 + 溢出 4800 + 总数 5000 精确；门禁 500ms 过松 |
| ③ 500 动画单帧 | ✅ 达成（1.0 目标未达成已如实登记） | 中位 1.47ms（3 次 1.44–1.49），2.0 门禁通过，≤1.0 明确未达 |
| ④ 门禁/承诺一致 | ◐ 部分 | 三处核心一致、无 2.0 冒充 1.0；§516 出口判据陈旧，115 PASS 陈旧，8–9x 平台相关 |
| ⑤ 入口证据 | ❌ 未达成 | 三测试均 helper-only；缺入口调用、回退对拍、分派可观测性、性能门禁 |

给主审的建议：
1. **P1 补测试**（不改实现）：给 `_prepare_bucket_frame`/`_bucket_pack_frame`、`loom_lighting` AABB 调用点、`_dirty_mask_batch(pose)` 各加一条入口级对拍/回退测试；这是"只修一条路径"的高风险面。
2. **P2 收紧门禁**：`record_asset_error` 的门禁从 500ms 收到 ≤100ms（或写相对回归比）；给 bucket/AABB 加耗时断言或明确"不承诺门禁"。
3. **P2 文档回写**：`research_beta6_03:516` 的出口判据改为"实测 1.42–1.69ms，≤1.0 未达成（落地 2.0ms 门禁）"；版本计划 115→126；54.6/29.5 补条目形态与测量口径（或直接改为本轮复跑值）。
4. **待人类裁决**：`≤1.0ms` 是"接受降级（2.0ms）"还是"批次2补 SoA"——提交 `5ebd57b` 说选 B（不做二期），但设计 §516 未改，需明确。

---

## 4. 复跑原始输出（节选）

```text
$ py -3.13 tests/_tmp/verify_02_a_assets.py    # V02_ENTRY=fingerprint
entry shape = fingerprint
index file bytes=4661063
load_index(10000) ms=['73.9', '77.2', '80.5'] median=77.2
  ok=True reason=None count=10000 warnings=0? True
load_index 热(缓存命中) ms=['0.220', '0.130', '0.114']
validate_index(10000) ms=['19.8', '19.4', '19.7'] median=19.7 ok=True warns=0
inspect_index(10000) ms=['77.2', '80.6', '81.8'] median=80.6 state='ok' count=10000
```

```text
$ py -3.13 tests/_tmp/verify_02_a_assets.py    # V02_ENTRY=plain
load_index(10000) ms=['29.6', '33.1', '32.9'] median=32.9
validate_index(10000) ms=['19.4', '19.4', '19.4'] median=19.4
validate_index 每条 = 1.942 us
load_index 热 = 0.114–0.220 ms
```

```text
$ py -3.13 tests/_tmp/verify_02_c_err_sinks.py
SINK=StringIO  ms=7.3 len=200 count=5000
SINK=devnull   ms=7.1 len=200 count=5000
SINK=real-stdout ms=8.3 len=200 count=5000
（a 探针同段）len(errs)=200 limit=200 overflow=4800 count=5000 printed_lines=200
第201条: len=200 count=201 overflow=1
```

```text
$ py -3.13 tests/_tmp/verify_02_b_anim.py
gc enabled = True | python 3.13.15 | models 500
trials(60 frames avg) ms=['1.490', '1.473', '1.440']
median=1.473  min=1.440  max=1.490
verdict <=2.0ms: True | <=1.0ms: False
```

```text
$ py -3.13 tests/test_animation_base.py      # 单个样本（另跑三次见下）
     500 动画物体: 旧逐物体 13.012 ms / 新批量 1.414 ms (9.2x)
PASS ② 500 动画物体 ≤ 2.0ms 稳定门禁 (实测≈1.5ms; ≤1.0ms 目标未达成, 见上)  new=1.414 ms
总结果: ALL PASS ✅
$ 3.13 另三次: 1.348 / 1.395 / 1.402 ms（旧 12.77–13.20 = 9.2–9.5x）
$ 3.12 四次: 1.534 / 1.555 / 1.583 / 1.675 ms（旧 11.6–12.6 = 7.5–8.0x）
```

```text
$ py -3.13 tests/test_bucket_pack.py   -> 21 PASS / 0 FAIL，exit 0
$ py -3.13 tests/test_aabb_simd.py     -> 6 PASS，impl=1 (AVX2)
$ py -3.13 tests/test_physics_pose_soa.py -> 10 PASS
$ py -3.13 tests/test_animation_base.py   -> 126 PASS / 0 FAIL
```
