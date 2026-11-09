# 入口 / 构建 / 打包链 扫描报告（beta5 第三轮专项 · 编号 05）

> 只读审计。基线 `71b31ac..HEAD`（已发布 beta4 之后的全部改动）。
> 方法论：粗筛 → 双向推演（先证伪再证真）→ 四象限 → 探针闭环；每条结论 = 文件:行号 + 逻辑链 + 可执行命令 + 实测输出。

## 0. 范围与方法

### 0.1 文件与 diff 规模（`git diff --numstat 71b31ac..HEAD`）

| 文件 | +/- | 本轮是否改动 |
|---|---|---|
| `Loom/Loom.py` | +131 / -18 | 是（`--bench` 转发 + E2 远程三态） |
| `Loom/build_entry.py` | +25 / -2 | 是（实测 dt + TPS/ratio 输出） |
| `tools/package_hub.py` | +26 / -0 | 是（版本真源入包 + iss [Code]） |
| `tools/installer.iss` | +23 / -1 | 是（生成物：0.1.3 + [Code]） |
| `Loom/tests/test_release_version.py` | +16 / -6 | 是（EXPECT_ENGINE / EXPECT_HUB 派生） |
| `tools/package_engine_compiled.py` | 0 / 0 | **未改动**（按要求复核其失败路径与 DATA_DIRS） |

关键函数清单：`Loom.py: _remote_mode / _install_present_watch / _launch_native / _launch_player / __main__ 的 --bench 转发`；
`build_entry.py: _bench_scene / __main__ 的 --bench 分支`；`package_hub.py: load_version / ISS_TEMPLATE / write_iss / run_inno`；
`package_engine_compiled.py: main（失败路径 / DATA_DIRS / Projects 规则）`。

### 0.2 跑过的命令（全部本机实测）

- `python Loom/tests/test_release_version.py` → ALL PASS（exit 0）
- `python Loom/Loom.py --bench <scene> 0`、`--bench <缺失文件>`、`--bench <带空格路径> abc`、`--benchmark --bench ...`（两入口各一次）
- `python Loom/build_entry.py --bench <缺失文件>`
- 探针（`Loom/tests/_tmp/scan_beta5_05_0*.py`，gitignore 目录）：01 假 runtime 驱动 `_bench_scene` 的 n_frames 边界；02 假 PlayerApp 驱动 `_install_present_watch`；03/04 模板 vs 生成物字节比对；05 AST 调用点扫描；06 路径含空格/写盘；08 写盘失败；09 编译版打包失败路径；11 ratio 取值域；12 真实 ISCC 编译生成物。

### 0.3 污染自查（协议 `0.4）

`Loom/bench_result.txt` 是**受跟踪文件**，被实测 `--bench` 运行改写（见 P-05-09）。已用 `git show HEAD:Loom/bench_result.txt` 的原始 blob 字节精确还原（904 字节，`git status --porcelain -- Loom/bench_result.txt` = CLEAN），未使用 checkout/stash。
仓库里 `M docs/audit/scan_beta3_05_packaging_release.md` 与若干 `??` 文件属**其它并行子代理**的既有改动，本代理未触碰。


### 0.4 锚点时效（并行代理改动的行号漂移）

扫描期间另一个并行子代理在 14:23–14:24 修改了 `Loom/engine.py`(+16/-1)、`Loom/loom_render.py`(+3/-0)、`Loom/sceneio.py`(+40/-19)（`git status` 可见这三个 M，本代理未触碰）。它们使本报告引用的**跨文件**行号发生漂移；语义已复核未变（`dt_eff = max(...)` 仍在、`get_logic_time_ratio` 仍为 `Σdt/Σwall`）。对应关系：

| 引用点 | 扫描时行号（本报告所用） | 14:25 复核时的行号 |
|---|---|---|
| `engine.py` `dt_eff = max(render_dt, wall_dt)` | 1389 | 1395 |
| `engine.py` `get_logic_time_ratio` | 1540-1551 | 1555-1566 |
| `engine.py` `get_tps` | 1553 | 1568 |
| `loom_render.py` `def run(self)` | 982 | 985 |
| `loom_render.py` `_stop_parallel()` / `audio.shutdown()` | 1016 / 1020 | 1019 / 1023 |

`_glfw_shutdown` 的**调用点仍为 0**（`grep _glfw_shutdown` 只命中定义 `loom_glfw_window.py:402` 与审计文档），P-05-07 结论不受影响。

---

## 1. 粗筛清单（含跳过留痕）

| ID | 位置 | 标签 | 初步方向 |
|---|---|---|---|
| P-05-01 | build_entry.py:239 + Loom.py:392 | BND-EMPTY / IFACE-PRECOND | `--bench scene 0` 帧数为 0 → FPS 计算除零 |
| P-05-02 | build_entry.py:252-256 | BND-OFFBYONE | 空帧表索引（n_frames<=0） |
| P-05-03 | Loom.py:386-398 | IFACE-PRECOND / AUDIT-ASYMMETRY | 转发分支无 isfile、无脚本目录解析，与 build_entry 口径分叉 |
| P-05-04 | Loom.py:157-158 | SEM-SILENT | 监视线程 `except Exception: return` 永久静默退出 |
| P-05-05 | Loom.py:130-131, 168-170 | SEM-SILENT / 重入 | 二次安装返回永不更新的 state |
| P-05-06 | Loom.py:205 + run_player.py:264-274 + 设置.json | IFACE-PRECOND | 默认 vulkan 后端不经 PlayerApp.run → auto 监控根本不启动 |
| P-05-07 | Loom.py:206-213 + loom_render.py:1005-1022 | BND-RESOURCE | 原生 run() 返回后继续跑 Qt，GLFW 窗口/上下文从不销毁 |
| P-05-08 | build_entry.py:240-241 | AUDIT-DOCIMPL | "ratio<1 = 时钟被欠账" 与实现方向相反 |
| P-05-09 | build_entry.py:274-275 | BND-RESOURCE | 结果写到**受跟踪**文件 Loom/bench_result.txt |
| P-05-10 | Loom.py:392 / build_entry.py:52 | SEM-SILENT | 帧数非数字静默回落 300 |
| P-05-11 | Loom.py:387 vs build_entry.py:301-305 | AUDIT-ASYMMETRY | 混合 `--benchmark --bench` 两入口优先级相反 |
| P-05-12 | Loom.py:386-401 | TOOL-SCOPE | `--bench` 绕过 `_self_check_sources()` 与依赖自检 |
| P-05-13 | build_entry.py:223-226 vs engine.py:1390 | AUDIT-DOCIMPL | 体检累计量未清零，含 40 帧热身 |
| P-05-14 | build_entry.py:242-245 | SEM-DEFAULT | `get_tps` 缺失时打印 "TPS: -1.00"，与真实值不可区分 |
| P-05-15 | package_engine_compiled.py:86-90 vs 50-52 | BND-RESOURCE | 失败路径残留 dist/_compiled_tmp_<ver> |
| P-05-16 | package_hub.py:39 / package_engine_compiled.py:19 | AUDIT-NOCHAIN | 示例/提示版本号陈旧（0.1.2 / beta4） |

### 跳过留痕（判定无风险，附具体事实）

1. **`_benchmark_math`（Loom.py:215-322 / build_entry.py:85-192）**：本轮 diff 未触碰；参数经 `.isdigit()` 过滤，`n_tri//2` 有 `max(4, …)` 下限。跳过。
2. **`--bench` 的"连续两次 CLI 调用"**：两次独立进程、结果文件整体覆盖、无并发读者 → 语言/进程语义已保证。跳过（程序内两次调用的资源件见 P-05-15 同族问题）。
3. **`--bench` 缺 scene 参数**：实测打印用法并 `sys.exit(1)`（见 D-1）。跳过。
4. **结果文件编码**：`open(..., 'w', encoding='utf-8')`；受跟踪旧产物 904 字节、无 BOM、`decode('utf-8')` OK（探针 11）。跳过。
5. **`installer.iss` 的 [Code] Pascal 语法与 utf-8 无 BOM**：真实 `ISCC.exe` 在 %TEMP% 编译生成物，exit=0、产物 2 101 358 字节（探针 12）。跳过（见 D-3）。
6. **`package_engine_compiled.py` 的 DATA_DIRS**：7 个目录逐一 Test-Path 均 True，两个 DATA_FILES 均存在，本轮 diff 未新增运行时目录。跳过（见 D-5）。
7. **`run_player.resolve_backend / _handle_vk_init_failure`**：本轮 diff 未改动，仅在 P-05-06 中作为"auto 的前置条件"引用。跳过。

---

## 2. 逐项裁决

### P-05-01（P-PROVED，P2）`--bench <scene> 0` 除零崩溃

1) **位置**：build_entry.py:235-239（`fps = n_frames / wall` → `1000.0 / fps`）；入口 Loom.py:391-393、build_entry.py:34-53。
2) **契约**：`--bench <scene> [帧数]` 是"用法错误必须明确拒绝"的 CLI 参数，帧数 0 不是合法测量窗口。
3) **路径枚举**：① `Loom.py --bench s 0` → Loom.py:392 `'0'.isdigit()` 为 True → n_frames=0；② `build_entry.py --bench s 0` → 同一 isdigit 判定 → bench_frames=0；③ `grep '_bench_scene'` 仅这两处调用，无第三方下界钳制。
4) **实际行为**：`range(0)` 不执行 → `fps = 0/wall = 0.0` → `1000.0/0.0` 抛 ZeroDivisionError；bench_result.txt 不写出。
5) **差异**：预期"参数校验失败 + 明确提示"，实际"未捕获 traceback + 无结果文件"。
6) **触发条件**：帧数参数恰为 `0`（isdigit 通过）；编译版 `--windows-disable-console` 下完全静默。
7) **验证**：
```
> python "Loom\Loom.py" --bench "examples\PacMan2D.json" 0
  File "...\Loom\build_entry.py", line 239, in _bench_scene
    lines.append("FPS: %.1f  (平均帧时间 %.3f ms)" % (fps, 1000.0 / fps))
ZeroDivisionError: float division by zero
exit=1
```
8) **影响与等级**：P2（诊断链静默失败，不崩溃主机、不损坏数据）。

### P-05-02（P-PROVED，P3）n_frames<=0 时空帧表索引越界

- 位置：build_entry.py:252-256（`p50 = dms[int(0.50*len(dms))]`、`dms[-1]`）。
- 路径：仅程序化调用 `_bench_scene(scene, n_frames=-1)`（CLI 的 `-1` 被 isdigit 过滤，当前不可达）。
- 实测（探针 01）：`n_frames=0 -> ZeroDivisionError`；`n_frames=-1 -> IndexError: list index out of range`。
- 等级 P3（当前仅库级可达）；修复与 P-05-01 同一处：入参下界校验。

### P-05-03（P-PROVED，P2）`Loom.py --bench` 缺文件直接 traceback，且与 build_entry 口径分叉

1) **位置**：Loom.py:386-398（转发块）；对照 build_entry.py:305-313。
2) **契约**：本次修复的自我目标写在 Loom.py:383-385 —— "显式转发到同一实现，避免两个入口口径分叉"。
3) **路径枚举**：① 缺文件；② 相对路径（build_entry 按脚本目录解析，Loom.py 按 CWD）；③ 正常路径；④ 非数字帧数。
4) **实际行为**：Loom.py 转发分支内 `isfile` / `exists` / `dirname(abspath` 出现次数均为 **0**（探针 05 [5]）→ 缺失场景直达 `runtime.PlayerApp`，先建 GLFW 窗口再在 runtime.py:133 抛 ValueError；该异常不在 Loom.py:408 的 try 覆盖范围内 → 原样 traceback。
5) **差异**：同一缺陷两种 UX；"口径一致"只覆盖正常路径。
6) **触发条件**：`Loom.py --bench <不存在的路径>`，或从非脚本目录用相对路径启动。
7) **验证**：
```
A: python "Loom\Loom.py" --bench "不存在的场景.json" 3
  File "...\Loom\runtime.py", line 133, in __init__
    raise ValueError("无法加载场景: %s" % scene_path)
ValueError: 无法加载场景: 不存在的场景.json          exit=1
B: python "Loom\build_entry.py" --bench "不存在的场景.json" 3
[错误] 场景不存在: D:\...\Loom\不存在的场景.json     exit=1
```
8) **影响**：P2（诊断可读性 + 相对路径语义不一致）。

### P-05-04（P-PROVED，P3）监视线程 `except Exception: return` 永久静默失效

- 位置：Loom.py:157-158。
- 路径：`_watch` 首次 `should_fallback_remote()` / `present_health()` 抛异常 → return → 线程结束、**零打印**；而 Loom.py:99 docstring 承诺"打印一行明确原因"，同一函数在装不上监视器时（Loom.py:128）也确有打印（AUDIT-ASYMMETRY）。
- 实测（探针 02 [C]）：判据从第 2 次起恒 True、询检次数停在 1、state 始终 fallback=False、stdout/stderr 无输出。
- 等级 P3（GL 引擎实例都带该 API，触达面窄）。

### P-05-05（P-PROVED，P3）二次安装返回永不更新的 state

- 位置：Loom.py:130-131（已安装则返回**新建的** state）、168-169（只 patch 一次，闭包绑定 st1）。
- 实测（探针 02 [B]）：`st1 is st2 = False`；一次真实降级后 `st1={'fallback': True,…}` 而 `st2={'fallback': False,…}` → 第二次 `_launch_player` 判定"不降级"。
- 等级 P3：当前唯一调用点 Loom.py:205 在一次进程内只执行一次；宿主复用即命中。

### P-05-06（P-PROVED，P2）默认 Vulkan 后端下 `auto` 完全无效（且零输出）

1) **位置**：Loom.py:205（装监视器）→ Loom.py:206 `_launch_native` → run_player.py:146（缺省 render_api='vulkan'）→ run_player.py:259-261 `_run_vulkan`。
2) **契约**：Loom.py:95-99 / 188-189：auto = "先试原生，上屏连续失败就降级一次"。
3) **路径枚举**：① `render_api=vulkan`（本机 `Loom/设置.json` 实测 `"vulkan"`，代码缺省值同）；② `opengl`；③ `auto`（run_player 侧回退）。
4) **实际行为**：patch 挂在 `runtime.PlayerApp.run` 上，监视线程**只在 run() 内部**创建；Vulkan 路径从不实例化 runtime.PlayerApp，`vk_player.py` 中 `present_health` / `should_fallback_remote` 出现 **0 次** → `state.fallback` 永远 False，Loom.py:207-208 直接 return，一行日志都没有。
5) **差异**：文档承诺"任一后端上屏失败都可自动降级"，实际只有 OpenGL 具备该能力。
6) **触发条件**：未改过设置的机器 + `LOOM_REMOTE_MODE=auto`（恰恰是"想让它自动兜底"的默认场景）。
7) **验证**（探针 02 [D]）：
```
[D] run_backend(vulkan) 返回='vk-ran'; 假 PlayerApp.run 调用次数=0
[D] 引擎 设置.json render_api = 'vulkan' (默认后端来源)
[D] vk_player.py 中 present_health=0 次, should_fallback_remote=0 次
```
8) **影响**：P2（auto 在默认配置下是"看起来装了、实际没装"的静默 no-op）。

### P-05-07（P-PROVED，P2 · [REGRESSION]）auto 降级后原生 GLFW 窗口不销毁 → 残留无响应窗口

1) **位置**：Loom.py:206-213（**本轮新增**的"原生 run() 返回后同进程继续启动 Qt"路径）；loom_render.py:988-1022（run() 尾部）；loom_glfw_window.py:402-407（`_glfw_shutdown`）。
2) **契约**：loom_glfw_window.py:402 docstring 自称"GLEngine.run 退出时调（替代 pygame.quit 的窗口部分）"。
3) **路径枚举**：① 正常退出（此后紧跟 `sys.exit(0)`，进程结束由 OS 收窗）；② **auto 降级**（run 返回后进程继续 → 必须显式销毁）；③ `--run` 直接 `sys.exit(0)`。
4) **实际行为**：run() 尾部调用名集合 = `['_dispatch_application_quit','_handle_events','_stop_parallel','min','move_camera','perf_counter','print','render','rotate_camera','set_mouse_locked','shutdown','sleep']`，不含 `_glfw_shutdown`；全仓 `_glfw_shutdown` 调用点数 = **0**（只有定义）；`destroy_window` 全仓 0 处；`glfw.terminate` 仅出现在 create_window 失败的 except 里（loom_glfw_window.py:131）。
5) **差异**：路径 ② 是新引入的"run 返回后继续运行"分支，窗口没有生命周期终点。
6) **触发条件**：`LOOM_REMOTE_MODE=auto` + OpenGL 后端 + 连续 3 次上屏失败（正是白屏机器）。
7) **验证**（探针 05）：
```
[2] _glfw_shutdown 被"调用"的次数 = 0
[3] loom_render.run() 内调用名: [... '_stop_parallel', ... 'shutdown'(音频) ...]
[4] run() 内是否调用 _glfw_shutdown: False
```
8) **影响**：P2（该特性为白屏机器设计；降级后原生窗口不再泵事件，成为"未响应"残窗压在 Qt 窗口上，用户观感仍是白屏/卡死）。

### P-05-08（P-PROVED，P2 · [REGRESSION]）TPS 体检口方向写反：ratio<1 结构性不可能

1) **位置**：build_entry.py:240-241（**本轮新增**的注释与输出文案）对照 engine.py:1383-1391、1540-1551；同一句判据在 engine.py 自己的 docstring 里也抄了一遍（扫描时 engine.py:1546，复核时 engine.py:1561），修复时两处必须同步。
2) **契约**：注释写"ratio≈1 = dt 口径没问题；ratio<1 = 时钟被欠账"。
3) **路径枚举**：`_clock_advance` 只累加 `dt_eff = max(render_dt, wall_dt)`（engine.py:1389）与 `wall_dt`（≥0，engine.py:1383-1388），故 `ratio = Σdt_eff / Σwall_dt ∈ [1, +∞)`，下界由 dt=0 那一帧取到 1.0。
4) **实际行为**（探针 11，真实 `GLEngine._clock_advance` + 假时钟）：
```
旧口径 1/120 dt, 快循环      ratio=4.194
新口径 实测 dt, 慢帧          ratio=1.495
dt 远大于墙钟                 ratio=96.959
dt=0（纯墙钟）                ratio=1.0
长卡顿 0.4s > 最大 delta      ratio=1.0
```
真实 bench（300 帧）：`TPS: 30.85  (logic dt/墙钟 ratio=1.0006)`。
5) **差异**：病态方向是 `ratio >> 1`（逻辑时钟被**超额**推进），`ratio < 1` 永不出现 → 报告里的"分流"建议无法执行。
6) **触发条件**：任何读这一行的人/脚本；发布说明 `tools/release_notes/engine-0.1.0.beta5.md:29` 照抄了同一判据。
7) **验证**：`python "Loom\tests\_tmp\scan_beta5_05_11_ratio.py"`（输出见上）。
8) **影响**：P2（体检口把人指向错误根因，不崩溃）。

### P-05-09（P-PROVED，P2）bench 结果写入**受跟踪**文件，每次运行弄脏工作树

1) **位置**：build_entry.py:274-275（`os.path.dirname(os.path.abspath(sys.argv[0]))` + `bench_result.txt`）。
2) **契约**：docstring（build_entry.py:18-19）说"结果写 bench_result.txt（编译版靠文件收结果）"；`.gitignore` 只有 `_bench_ws/`。
3) **路径枚举**：① 源码运行（argv[0]=Loom/Loom.py → 写进仓库 `Loom/bench_result.txt`）；② 编译版（argv[0]=exe → 写安装目录）；③ `runpy` 等宿主（argv[0] 被改写，落点随宿主）。
4) **实际行为**：`git ls-files Loom/bench_result.txt` 有输出（受跟踪）；一次 `--bench` 后 `git status --porcelain` = `M Loom/bench_result.txt`。
5) **差异**：契约只考虑"编译版收结果"，未考虑源码运行会改写版本控制内的文件。
6) **触发条件**：开发机执行文档里的 `python Loom.py --bench <scene>`。
7) **验证**（探针 10）：
```
exit = 0 | 实际帧数 = 300
git status(bench_result 受污染) = M Loom/bench_result.txt
还原后 = CLEAN
```
8) **影响**：P2（可维护性/误提交风险）；本代理已按 git blob 字节还原（`0.3）。

### P-05-10（P-PROVED，P3）帧数非数字静默回落 300

- 位置：Loom.py:391-393；build_entry.py:52-54。
- 实测（探针 10）：`--bench <scene> abc` → `exit=0`、`实际帧数 = 300`、无任何提示。
- 差异：用法行（Loom.py:17）未定义非法帧数策略；与 `--benchmark` 同款静默，但此处会把测量时间放大 100 倍。P3。

### P-05-11（P-PROVED，P3）混合 `--benchmark --bench` 两入口优先级相反

- 位置：Loom.py:387（转发块先于 `_parse_args`）vs build_entry.py:301-305（先判 benchmark）。
- 实测：`Loom.py --benchmark --bench <scene> 3` → "场景基准: True / 数学管线基准: False"；`build_entry.py` 同参数 → 相反。
- 等级 P3（参数混用非正常路径，但正是"两入口口径"问题的残留）。

### P-05-12（P-PROVED，P3）`--bench` 绕过源码自检与依赖自检

- 位置：Loom.py:386-398 位于 Loom.py:400-415（`_self_check_sources()`、pygame/moderngl ImportError 友好提示）之前。
- 影响：AV 全零篡改 / 缺 moderngl 时 bench 路径只给原始 traceback。P3。

### P-05-13（P-PROVED，P3）TPS/ratio 累计量未随测量窗口清零

- 位置：build_entry.py:223（只清 `_stage_times`）vs engine.py:1390-1391（`_logic_dt_sum/_logic_wall_sum` 累计）。
- 证据（探针 11）：`build_entry.py` 里 `_logic_dt_sum` 出现 0 次、`_stage_times.clear` 1 次。
- 影响：打印的 ratio/TPS 含 40 帧预热（首帧 dt 被钳到 1e-4），与"测量窗口"口径不一致。P3。

### P-05-14（P-PROVED，P3）`get_tps` 缺失时打印 "TPS: -1.00"

- 位置：build_entry.py:242-251。实测（探针 08 第二段）：`TPS: -1.00  (logic dt/墙钟 ratio=n/a)`，无"取不到"措辞，与真实测量值不可区分（SEM-DEFAULT）。P3。

### P-05-15（P-PROVED，P3）编译版打包失败路径残留 dist/_compiled_tmp_<ver>

- 位置：package_engine_compiled.py:86-90（先建 tmp）vs 50-52（`_fail` → `sys.exit(1)`，无 rmtree）。
- 路径：:90 之后任何 `_fail`（写 运行时.json / validate_meta / 写 解释器.json）都留下整棵 tmp 树；下次运行 :87-88 会 rmtree 自愈。P3。

### P-05-16（P-PROVED，P3）陈旧版本示例

- `tools/package_hub.py:39` 提示仍写 `{"version": "0.1.2"}`（真源 0.1.3）；`tools/package_engine_compiled.py:19` 用法示例仍 `--version 0.1.0.beta4`。仅提示文本（AUDIT-NOCHAIN）。P3。

---

### P-DISPROVED（证伪成功，附证据）

**D-1 bench 缺 scene 参数 → 用法 + exit 1**（Loom.py:394-396）：
```
$ python "Loom\Loom.py" --bench
用法: python Loom.py --bench <scene.json> [帧数]     exit=1
```

**D-2 bench 写盘失败路径已覆盖**（build_entry.py:276-280）：假 runtime/engine + 让 `open` 对 bench_result.txt 抛 PermissionError（探针 08）：
```
[bench] 结果写盘失败 (PermissionError(13, 'Permission denied')), 仅有 stdout
[写盘失败] 函数正常返回 fps=588217.4 (未抛出)
```
只读目录/文件被占用不会把"报了结果"变成"报失败"。

**D-3 `tools/installer.iss` 与模板生成物字节一致，且能真正编译**：
- `ISS_TEMPLATE % {'version': '0.1.3'}` 以 `write_iss` 同样的文本模式写盘后与磁盘文件**逐字节相同**（74 行、全 CRLF、无 BOM，探针 04）。
- `ISCC.exe /Q` 编译该生成物：`exit = 0`、产物 `LoomHub-0.1.3-Setup.exe` 2 101 358 字节（探针 12）→ [Code] 的 `CurUninstallStepChanged` / `DelTree(UserCfg,True,True,True)` / `UninstallSilent` / `#13#10` / `%%LOCALAPPDATA%%` 转义全部正确，不存在"手改被覆盖"的分叉。
- **残留风险（非 bug）**：没有测试守护该等式（`test_release_version.py` 里 `ISS_TEMPLATE/write_iss` 出现 0 次），见 `4 建议 8。

**D-4 `package_engine_compiled.py` 失败路径与依赖签名齐全**（探针 09）：
```
[1] 无参数                     exit=2  error: the following arguments are required: --editor-dist, --builder-exe
[2] editor-dist 里没有 Loom.exe exit=1  [编译包] 错误: --editor-dist 里没有 Loom.exe: ...
[3] builder-exe 不存在         exit=1  [编译包] 错误: --builder-exe 不存在: ...
[4] --version 1.0/../x         exit=1  [错误] --version 非法: '1.0/../x'（版本号须为 x.y.z 或 x.y.z.betaN）
[sig] _runtime_dist(dir_path) / _hub_config() / write_launcher(out_dir) / write_meta_readme(out_dir, version, slim=False) 均存在
[5] player_runtime 存在: True   [6] examples 存在: True
```

**D-5 DATA_DIRS 无遗漏、Projects 规则生效**：`scripts/GUI/assets/ckernels/core_components/core_plugins/plugins` 7 个目录 Test-Path 全 True；`输入配置.default.json` / `设置.json` 存在；本轮 `git diff --name-only` 未新增运行时目录；`Loom/Projects` 里 7 个开发压测场景确实不随包（只取 `examples/` 的 1 个 json）。

**D-6 版本单一事实源在"未发布"状态下自洽**：`Loom/解释器.json = 0.1.0.beta5 = release_github.ENGINE_VERSION = package_engine.load_version()`；`LoomHub/版本.json = 0.1.3 = release_github.HUB_VERSION = installer.iss #MyAppVersion = package_hub.load_version()`；`python "Loom\tests\test_release_version.py"` → `总结果: ALL PASS`（exit=0）。

**D-7 路径含空格 OK**：`--bench "<...>/a b 空格/Pac Man 2D.json" abc` 正常跑完（探针 06，`SystemExit(0)`）。

**D-8 结果文件编码 OK**：utf-8 无 BOM，`decode('utf-8')` 通过（探针 11）。

### P-UNKNOWN（3 条，需额外条件才能定）

1) **两个 bench 进程并发写同一 bench_result.txt**：`open(...,'w')` 是"截断+写"，理论上存在读到半截内容的窗口；但本仓无并发读者，无法构造有意义的差异。**需要**：确认是否存在外部自动化在 bench 运行期读取该文件。
2) **编译版（`--windows-disable-console`）下 bench 失败的可观测性**：`[错误] 场景不存在` 与 traceback 都只走 stdout，编译版无控制台 → 用户侧完全静默（本次未构建 Nuitka 产物）。**需要**：一份真实 Nuitka dist。
3) **Program Files 只读目录下 bench_result.txt 写失败的真实路径**：本机源码运行落在可写目录，只验证了 OSError 分支（D-2）。**需要**：安装到 `C:\Program Files` 的实机运行。

---

## 3. 统计

| 结论 | 数量 | 明细 |
|---|---|---|
| P-PROVED | 16 | P2×6（01/03/06/07/08/09）、P3×10 |
| P-DISPROVED | 8 | D-1…D-8 |
| P-UNKNOWN | 3 | 并发写 / 编译版无控制台可见性 / Program Files 只读实测 |
| P-CONTRADICTION | 0 | — |
| 跳过留痕 | 7 | `1 列表 |

按等级：**P0 = 0**；**P1 = 0**；**P2 = 6**；**P3 = 10**。

[REGRESSION] 三条：**P-05-07**（本轮新增"原生 run() 返回后同进程继续"，此前该返回点紧跟 `sys.exit(0)`，窗口销毁由进程退出兜底）；**P-05-08**（本轮新增的 ratio 注释/文案方向写反）；**P-05-03**（本轮新增的 `--bench` 转发分支以"避免口径分叉"为名，却复制了一份不完整的参数解析）。

---

## 4. 修复建议排序（只给方向，不含代码）

1. **P2 · P-05-01/02/10**：在 `_bench_scene` 入口（或两入口参数解析处）对 `n_frames` 做下界校验（`>= 1`），不合法即用法提示 + 非零退出；把 `isdigit()` 换成"显式解析 + 失败即报错"。
2. **P2 · P-05-09**：结果文件移出仓库（用户目录 / `LOOM_BENCH_OUT` 覆盖），或把它从版本控制移除并加入 `.gitignore`；二者择一，禁止"源码运行改写受跟踪文件"。
3. **P2 · P-05-08**：体检判据改双向（`ratio` 明显 >1 = 时钟被超额推进 → 查 `max(dt,wall)` 与 `maximum_logic_delta`；≈1 才正常），并同步修正 build_entry 注释与发布说明里的同一句话。
4. **P2 · P-05-06**：`auto` 要么在 Vulkan 路径明确打印"本后端不支持自动降级"（消除静默），要么给 `vk_player` 补同构的 `present_health/should_fallback_remote`。
5. **P2 · P-05-07**：降级前显式收口原生窗口（调用已存在却从未被调用的 `_glfw_shutdown`，或 `glfw.destroy_window` + `ctx.release`）。
6. **P2 · P-05-03**：Loom.py 转发分支补齐"存在性检查 + 相对路径按脚本目录解析"；最省事是直接复用 build_entry 的 `__main__` 分支口径，不要再手写第二份解析。
7. **P3 · P-05-04/05/11/12/13/14**：监视器异常改为"打一行 + 退出监视"；二次安装复用同一 state 或显式报错；混合参数优先级二选一并统一；bench 前补自检；测量前清零体检累计量；TPS 取不到打印 `n/a`。
8. **P3 · P-05-15/16 + D-3 测试缺口**：失败路径 `finally: rmtree(tmp)`；给 installer.iss 加"生成物 == 模板替换"断言（放进 `test_release_version.py`）；顺手修 0.1.2/beta4 的陈旧示例。

---

## 5. 需要人类裁决的封闭问题（3 条）

1) **bench_result.txt 落点**：A）改写到用户目录/可配置路径（放弃"exe 同目录"便携性，仓库与安装目录都不再被写脏）；B）保持 exe 同目录，但把它移出版本控制并加 `.gitignore`（保留便携性，接受开发机源码运行把文件丢在 Loom/ 下）。选 A 还是 B？
2) **auto 的适用范围**：A）只对 OpenGL 生效，并在 `render_api=vulkan` 时明确打印"本后端不支持自动降级"（承认现状、消除静默）；B）扩展到 Vulkan，需在 `vk_player` 侧新增同构健康判据（工作量大，但才符合"auto 应在上屏失败时兜底"的对外承诺）。选 A 还是 B？
3) **帧数非法值策略**：A）沿用 `--benchmark` 的"静默回落默认值"（一致性优先，但用户可能以为跑了 3 帧实际跑了 300 帧）；B）非法帧数一律报错退出（可预期性优先，风格与 --benchmark 分叉）。选 A 还是 B？
