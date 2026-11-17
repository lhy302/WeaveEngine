# research_beta6_05 · Python 版本迁移预研（3.13 / 3.14 / free-threading）

> 编号：05 ｜ 主题：Python 版本迁移（3.13 / 3.14 / free-threaded）｜ 日期：2026-11-09
> 性质：**只读调研**。受跟踪文件零改动；未 git add/commit/checkout/stash。唯一产物 = 本文件 + `Loom/tests/_tmp/research_05_*.py`（gitignore：`Loom/.gitignore:20` 的 `tests/_tmp/*`）。
> 实测环境：Windows 10，**18 逻辑核**，MSVC 14.3（cl 14.44.35207），已装 CPython **3.12.10 / 3.13.15 / 3.14.7**（`py -0p`），Nuitka **2.7.1**（3.12/3.13）与 **4.3.5**（3.14），PyPI 可达。
> 全部命令工作目录 = `Loom/`，除非另行注明。行号均为实测。
> **环境副作用声明**：为取得实测证据，在**系统 Python 3.13/3.14**（`%LOCALAPPDATA%\Programs\Python\`）里装过 `glfw / PySide6 6.12.0 / nuitka 2.7.1→4.3.5`。它们不在本仓库内，工作树未被污染（`git status` 只多出未跟踪的调研文档与既有 `tools/lint_except_dist/`）。

---

## 0. 三行结论

1. **3.13：可迁，且成本极低（实测）**——零代码改动下 `import engine` / `import editor` 通过，14 个测试文件 3.12/3.13 双跑全绿，**Nuitka 2.7.1 原样可编 3.13**。但**性能收益有限**：纯 Python 段 −8%~−11%，折到整帧约 −0.2~−0.5 ms，FPS 约 +2%~+5%（这是"顺手"，不是"解药"）。
2. **3.14：当前只被 `pygame 2.6.1` 一项卡死**（无 cp314 wheel；其余 7 项在 3.14 上全部可解析，含 PySide6 abi3、moderngl 5.13.0、numpy 2.5.4），且 Nuitka 需 ≥ 4.0（2.7.1 官方只声明到 3.13）。上 3.14 的前置决策是 `pygame → pygame-ce`。
3. **free-threading（3.13t / 3.14t）：短期不可行、也不建议现在投入**——`PySide6` 只发 `cp310-abi3`，而 CPython 官方明文「free-threaded 构建当前不支持 Limited C API / stable ABI」；`pygame` 无任何 t wheel；`Nuitka` 无 t 支持声明。它才是 beta5「单核 GIL 饥饿」的唯一结构解，但生态门没开。

---

## ① 现状（证据）

### 1.1 事实底账

| 事实 | 证据（文件:行） |
|---|---|
| 解释器元数据写死 3.12.10 | `Loom/解释器.json:4`（`"python_version": "3.12.10"`） |
| 依赖声明（8 项，全是 `>=` 下限、无锁） | `requirements.txt:3-9`；`:2` 注释仍写 `py -3.12` |
| **numba 生产上已退役**（`_NUMBA=False`，冻结环境四连坑） | `Loom/fastpath.py:27-46`（`_NUMBA = False` 在 `:40`） |
| 数值内核已是**纯 C ABI + ctypes**：ckernels / pipeline / physics / script | `Loom/core_components/official_manifest.py:17,21,25,29,33`；`Loom/fastpath.py:68-83` 的 `argtypes` |
| 引擎把 GIL 切换间隔调到 1 ms（beta5 处置） | `Loom/loom_logic_thread.py:35-49`；环境变量门 `Loom/engine.py:519-527` |
| 本机装有 3 个解释器 | `py -0p` → 3.14 / 3.13 / **3.12**（默认）/ 3.11 / 3.10 / 3.9 / 3.8 |
| 本机 3.12 实际包版本 | `python -c "import importlib.metadata as m; ..."` → numpy 2.2.5、moderngl 5.12.0、PySide6 6.11.1、wgpu 0.32.0、pygame 2.6.1、numba 0.67.0、glfw 2.10.2、pillow 13.0.0、**nuitka 2.7.1** |

> 注：任务描述把 `numba` 列为运行时依赖，实证不成立——它既不在 `requirements.txt`，也在源码里被显式退役（`fastpath.py:38-40`「numba 路径全部退役」）。`tests/_tmp/numba_spin_probe.py` 只是历史探针。**这不改变结论，但把 numba 从"必须项"降级为"无约束项"**。

### 1.2 依赖 × 版本 wheel 矩阵（PyPI 实测，2026-11-09）

探测方式（可复现）：读 PyPI PEP 691 simple index（`Accept: application/vnd.pypi.simple.v1+json`）的全部文件名，按 `<py>-<abi>-<plat>` 三元组统计 **win_amd64** 最早可用版本。

| 包 | 仓库要求 | 3.13 最早 wheel | 3.14 最早 wheel | 3.13t | 3.14t | 判定 |
|---|---|---|---|---|---|---|
| numpy | `>=1.24` | **2.1.0** | **2.3.2** | 2.1.3 ~ 2.4.6 | ≥2.3.2 | 3.13/3.14 OK；**3.13t 被 2.5 起断供** |
| moderngl | `>=5.8` | **5.11.0** | **5.13.0（仅此一版）** | **无** | 5.13.0（仅此一版） | 3.13/3.14 OK；**3.13t 硬阻断** |
| PySide6 / shiboken6 | `>=6.6` | `cp310-abi3`（3.13 可用） | `cp310-abi3`（3.14 可用） | **无** | **无** | 3.13/3.14 OK；**t 构建不可用（见 1.4）** |
| wgpu | `>=0.32` | `py3-none-win_amd64` | 同左 | 同左 | 同左 | 版本无关（0.33.0 起依赖 cffi≥1.15） |
| glfw | `>=2.6` | `py2.py3-none-win_amd64` | 同左（2.11.0 另带 cp314 tag） | 同左 | 同左 | 版本无关 |
| pygame | `>=2.5` | **2.6.1（唯一有 cp313 的版本）** | **无** | **无** | **无** | **3.14 硬阻断；t 全阻断** |
| pillow | `>=10.0` | **10.4.0** | **11.3.0** | 11.0.0 | 11.3.0 | 全绿 |
| numba / llvmlite | （不在 requirements） | 0.61.0 / 0.44.0 | 0.63.0b1 / 0.46.0 | **无** | 0.65.0rc1 / 0.47.0rc1 | 已退役，不构成约束 |

**本机 pip 实测（决定性证据）**

```powershell
# 3.13：8 项全可解析（--dry-run，不安装）
py -3.13 -m pip install --dry-run --only-binary=:all: pygame moderngl numpy PySide6 glfw wgpu pillow
# → Would install PySide6-6.12.0 ... glfw-2.11.0 moderngl-5.12.0 numpy-2.2.6 pillow-13.0.0 wgpu-0.33.0   (EXIT 0)

# 3.14：只有 pygame 失败
py -3.14 -m pip install --dry-run --only-binary=:all: pygame moderngl numpy
# → ERROR: Could not find a version that satisfies the requirement pygame (from versions: none)   (EXIT 1)

# 3.14 去掉 pygame 后：
py -3.14 -m pip install --dry-run --only-binary=:all: moderngl numpy glfw wgpu pillow PySide6
# → Would install ... moderngl-5.13.0 numpy-2.5.4 PySide6-6.12.0 wgpu-0.33.0                     (EXIT 0)
```

**结论：矩阵里只剩两处红格 —— `pygame @ 3.14` 与「所有扩展 @ free-threaded」。**

### 1.3 Nuitka 支持状态（官方声明 + 本机实测）

官方声明取自各版本 PyPI 元数据长描述（"**Python 3** (3.4 - 3.xx) are supported"），URL 形如 `https://pypi.org/pypi/Nuitka/<ver>/json`：

| Nuitka | 发布日期 | 官方声明范围 | 结论 |
|---|---|---|---|
| **2.7.1**（仓库当前 pin） | 2025-05-08 | 3.4 – **3.13** | 3.13 **可用**；3.14 **未声明** |
| 2.8.10 | 2026-01-23 | 3.4 – 3.13 | 同上 |
| **4.0** | 2026-02-05 | 3.4 – **3.14** | 3.14 起需 ≥4.0 |
| 4.3.5（最新） | 2026-11-08 | 3.4 – 3.14 | — |

**本机实测（比文档更硬的证据）**

```powershell
# ① 3.13 + 现有 Nuitka 2.7.1 + MSVC 14.3
py -3.13 -m nuitka --standalone --msvc=latest --assume-yes-for-downloads --output-filename=hello13.exe tests\_tmp\research_05_nuitka_hello.py
# → Nuitka: Version '2.7.1' on Python 3.13 ... Backend C compiler: cl (cl 14.3) ... Successfully created ...hello13.exe
# → 运行产物: hello 3.13.15        (EXIT 0)

# ② 3.14（该环境需 Nuitka ≥4.0，先升级再编）
py -3.14 -m nuitka --standalone --msvc=latest --assume-yes-for-downloads --output-filename=hello14.exe tests\_tmp\research_05_nuitka_hello.py
# → Successfully created ...hello14.exe ；运行: hello 3.14.7   (EXIT 0)
```

> 与仓库既有经验交叉验证：`Loom/game_player.py:18-22` 与 `Loom/build_game.py:135-143` 用的就是 `--standalone --msvc=latest`，参数**不需要为新版本改动**；`fastpath.py:47-52` 记录的「Nuitka 常量折叠双坑」是**语义坑不是工具链坑**，换版本不会自动消失，回归时必须复跑（见 ④R5）。
>
> **free-threaded × Nuitka：官方文档无任何支持声明。** 唯一线索是 4.3.5 文档里的编译期常量表含 `{GIL}`（"Python with or without GIL → boolean"），说明它**能识别**该配置，但**不等于能编**。→ 记为**未验证**，不得对外承诺（见 ⑦Q4）。

### 1.4 CPython 侧官方事实（引用 + 日期）

| 事实 | 来源（URL） |
|---|---|
| **3.14：free-threaded 正式支持**（PEP 779），章节标题即 "Free-threaded Python is officially supported" | https://docs.python.org/3.14/whatsnew/3.14.html |
| **3.14：Windows/macOS 二进制开始提供实验性 JIT**（"Windows and macOS binary releases now support the experimental just-in-time compiler"） | 同上 |
| **free-threaded 构建当前不支持 Limited C API / stable ABI**：「The free-threaded build does not currently support the Limited C API or the stable ABI.」→ **PySide6/shiboken6 的 `cp310-abi3` wheel 在 t 解释器上不可用** | https://docs.python.org/3.14/howto/free-threading-extensions.html |
| 3.13：free-threaded 为**实验性**（PEP 703），JIT 实验性 | https://docs.python.org/3.13/whatsnew/3.13.html ；https://peps.python.org/pep-0703/ |
| 3.14.7 发布页同样标注 PEP 779 正式支持 | https://www.python.org/downloads/release/python-3147/ |

> 本机 `py -0p` **没有** t 构建（3.13t/3.14t 未安装），因此所有 free-threaded 结论均来自「官方文档 + wheel tag 存在性」，**不是**本机跑出来的（诚实登记见 附录 B）。静态结论依然成立：abi3 与 t 构建不兼容是官方硬约束。

### 1.5 本机实测：3.13 上直接跑 Loom（零改动）

```powershell
# 3.13 环境仅补装 glfw（numpy/moderngl/pygame 已就位）
py -3.13 -m pip install glfw
cd Loom; $env:LOOM_NO_PARALLEL='1'
py -3.13 -c "import sys; sys.path.insert(0,'.'); import engine; print('engine OK')"
# → engine OK
py -3.13 -c "import sys; sys.path.insert(0,'.'); import editor; print('editor OK')"
# → QOpenGLWidget is not supported on this platform.   (QT_QPA_PLATFORM=offscreen 的预期告警)
# → editor OK
py -3.13 -c "import PySide6, shiboken6; print(PySide6.__version__, shiboken6.__version__)"
# → PySide6 6.12.0 shiboken 6.12.0
```

**14 个测试文件 3.12 / 3.13 双跑全绿**（同一命令、同一 `LOOM_USER_ROOT` 隔离、`QT_QPA_PLATFORM=offscreen`）：

`test_core_clock, test_decompose, test_collision, test_lod_fastpath, test_scheduler_pool, test_parallel, test_physics_body_init, test_qt_tick_input_order, test_qt_gizmo_click_order, test_editor_ui, test_ui, test_scene_load, test_gamepack, test_release_version`

```powershell
foreach ($v in @('3.12','3.13')) { foreach ($t in $tests) { py -$v "tests\$t" } }   # 14 文件 × 2 解释器 → failures: (空)
```

> 覆盖到 DLL 加载链（ckernels/pipeline/physics/script 全在 `import engine` 时加载）、pygame、moderngl、PySide6/Qt、ctypes 回调路径。**没有**覆盖真实窗口集成（`test_integration.py`，见 ④R10）。

### 1.6 解释器代际微基准（本机实测，探针 `Loom/tests/_tmp/research_05_interp_bench.py`）

| 负载（形态对齐 Loom 热路径） | 3.12.10 | 3.13.15 | 3.14.7 | 3.13 vs 3.12 |
|---|---|---|---|---|
| world matrix 组装 501 模型（纯 Python 标量） | 0.628 ms | **0.578 ms** | 0.677 ms | **−8.0%** |
| AABB 视锥剔除 501（纯 Python） | 0.486 ms | **0.431 ms** | 0.581 ms | **−11.3%** |
| 解释器启动（15 次均值） | 104.6 ms | **84.9 ms** | **82.0 ms** | **−18.8%** |

> **3.14 在这两个微负载上反而更慢（+7.8% / +19.5%）**——与官方宣称方向相反，最可能是冷启动/自适应特化尚未预热与 18 核调度噪声，**不能作为结论**，只在 附录 B 登记，需真实引擎 bench 复核。
>
> 量级对照：社区口径「3.13 比 3.12 快 5%~15%」与本文 −8%~−11% 同向；但这些都是**微负载**，与 `docs/design/版本计划_Loom0.1.0.beta6_20261109.md:47` 的「纯 Python 约 5-15%」同级，**不能当整帧收益**。

### 1.7 GIL 实测（收益拆解的数据基础，探针 `research_05_gil_probe.py` / `research_05_numpy_gil.py`）

| 测量 | 3.12.10 | 3.13.15 | 3.14.7 | 说明 |
|---|---|---|---|---|
| 2 线程 / 1 线程 × 定工作量纯 Python **加速比** | **1.02** | **0.97** | **0.98** | 去 GIL 才有解；现状=0 |
| GIL 交接间隔 p50（默认 5 ms） | 7.2 ms | 7.0 ms | 7.4 ms | 单跳 ≈ 1.4 × switchinterval |
| GIL 交接间隔 p50（1 ms，beta5 的处置） | 3.55 ms | 3.53 ms | 3.65 ms | **单跳砍半，与 `loom_logic_thread.py:39` 的处置一致** |
| numpy `np.exp`（ufunc）2 线程加速比 | **1.84** | — | — | ufunc 真释放 GIL |
| numpy BLAS matmul（700×700）2 线程加速比 | **1.29** | — | — | BLAS 自身已多线程，边际收益低 |
| numpy 批量 matmul（48×96×96） | **1.38** | — | — | 同上 |

**与 beta5 现场的一致性**：`docs/handoff/开发日志_LoomHub0.1.3_Loom0.1.0.beta5_20261109.md:43` 记录「满载时逻辑线程每秒只被调度 ~10 次，单步墙钟 15ms→39ms」；本文实测的**单跳**延迟只有 3.5~7.2 ms，**解释不了 100~400 ms 的等待** → 现场是 **convoy（排队雪崩）**：主线程反复短促抢 GIL，逻辑线程每轮要排多次队。这恰好说明：把 switchinterval 从 5 ms 压到 1 ms 只能缓解（单跳减半），根治只能去 GIL 或减少主线程 Python 段。

> **顺带纠正一条仓库内假设**（影响后续并行化决策）：`Loom/fastpath.py:199` 写「np.matmul 批量维度天然释放 GIL 内核」、`Loom/loom_lighting.py:251` 写「池上分块 -> 释放 GIL 真并行」。实测 **ufunc 才 1.84×，BLAS matmul 仅 1.29~1.38×**——批量 matmul 的并行度被 BLAS 线程池与内存带宽吃掉，**不能当作 8 核线性加速的凭据**。这与 04 报告「花式索引在 2/4/6 线程争用下 2.5 µs → 20/58/110 µs」互为佐证：**numpy 路径的线程扩展性远低于直觉**。

### 1.8 free-threaded 可行性判定（逐依赖）

| 依赖 | t 构建可用性 | 判定依据 |
|---|---|---|
| PySide6 / shiboken6 | **不可用** | 只发 `cp310-abi3`；官方：t 构建不支持 stable ABI（1.4） |
| pygame / pygame-ce | **不可用** | 两者均无 `cp313t`/`cp314t` wheel（1.2 实测） |
| moderngl | **仅 3.14t**（5.13.0 单版本） | 无 cp313t |
| numpy | 3.14t 可用；3.13t 仅 ≤2.4.6 | 2.5.x 起不再产 cp313t |
| numba / llvmlite | 仅 3.14t（且已退役） | cp313t 无 |
| wgpu / glfw / pillow | 可用 | 纯 py3 或已有 t wheel |
| **Nuitka** | **未知** | 无官方声明（1.3） |

**结论：只要 `PySide6` 与 `pygame` 还在依赖表里，free-threaded 就**跑不起来**（不是"跑得慢"，是"装不上 / import 失败"）。

### 1.9 迁移面扫描（好消息：没有雷）

| 检查 | 结果 | 命令 |
|---|---|---|
| 3.13/3.14 移除的 stdlib 模块（`cgi/telnetlib/audioop/imghdr/uu/lib2to3/...` 共 27 个） | **0 命中** | `grep -E '^\s*(import|from)\s+<mod>\b' Loom/*.py` |
| `sys.version_info` 硬分支 | **0 命中** | 同上 |
| `distutils` / `pkg_resources` / `imp` 模块 | **0 命中**（`plugin_sandbox.py:133` 的 `_imp` 是 `__import__` 别名） | 同上 |
| `__annotations__` 依赖（3.14 PEP 649 延迟求值） | **0 命中** | 同上 |
| 版本号硬编码点 | `Loom/Loom.py:1`、`Loom/build_entry.py:1` 的 shebang；`Loom.py:422-423`、`build_entry.py:348-349` 的报错文案；`requirements.txt:2` 注释；`Loom/解释器.json:4` | grep `3\.12` |
| 打包脚本硬编码 | `tools/package_engine.py:104-105`（找 `Python312` 目录）、`:116-117`（报错文案）、`:163`（README 文案） | 读文件 |
| **ctypes 回调点**（free-threaded 下需复测） | `Loom/filedialog.py:252-253`（EnumWindows CFUNCTYPE）、`Loom/crash_reporter.py:81`（WINFUNCTYPE 顶层异常过滤器，任意线程触发） | grep `CFUNCTYPE\|WINFUNCTYPE` |
| 插件沙箱的「版本漂移」防线 | `Loom/plugin_sandbox.py:59-65` 注释已明确警示 → **升级后必须复跑 `test_plugin_sandbox_escape.py`** | 读文件 |

---

## ② 目标设计（含数据/接口草案）

### 2.1 三源收益拆解：对 Loom 谁最重要

| 收益来源 | 机制 | 实测/引用 | 对 Loom 的可用性 | 权重 |
|---|---|---|---|---|
| **解释器自提速** | 3.13 特化自适应解释器 / 3.14 增量 GC 等 | 纯 Python −8%~−11%，启动 −19%（1.6） | **今天可用**（零改动） | 低（整帧 +2%~+5% 上限） |
| **free-threading（去 GIL）** | 逻辑线程与渲染线程真并行，消除「单核 GIL 饥饿」 | GIL 下 2 线程纯 Python 加速比 0.97~1.02（1.7）；beta5 现场见 `beta5 日志:43` | **不可用**（PySide6/pygame/Nuitka 三门） | **最高（结构性）** |
| **JIT（3.14 实验性）** | 官方 Windows 二进制已带 | 1.4；无本地实测（3.14 被 pygame 挡） | 不可用（且实验性、与 Nuitka 编译态叠加无先例） | 中低 |

**为什么 free-threading 权重最高**：Loom 的瓶颈早已不是"单条 Python 语句慢"，而是**同一时刻只允许一个线程执行 Python**。证据链：`loom_logic_thread.py:35-42`（逻辑线程被渲染主线程饿住）、`engine.py:519-521`（GIL 让渲染段整体慢 2×：interp 0.53→1.09 ms/帧）、`docs/guides/Loom_引擎操作手册与全功能测试清单.md:26-30`（TPS 上限 25-27 的**根因就是单核 GIL 串行**）。这三条都不是"换解释器能省几毫秒"的量级，而是**并行度=1** 的结构问题。

### 2.2 若只迁 3.13，收益上限的算术（用 04 的实测分母）

04 报告（`docs/design/research_beta6_04_python_hotspots.md`）在编辑器压测场景（500 混合，87.3 FPS，整帧 **12.17 ms**）实测：

| 段 | ms/帧 | 其中"纯 Python 调度"占比（04 §1.4/§1.5） |
|---|---|---|
| `buckets`（`_prepare_bucket_frame`） | 2.65 | 残差 ≈1.25 ms 是 numpy/python 调度（buffer.write 只 0.10） |
| `aabbs` | 2.24 | C 调用 1.38，Python 组装 0.47~0.86 |
| `pipe_wait` | 3.99 | 等待物理线程；根因是物理线程 ~9.5 ms 的 Python 脏检测 |
| `mt_mp_draws` | 1.51 | draw 本身 0.045 |

**保守折算**：3.13 的 −8%~−11% 只作用于「Python 字节码」部分，numpy/BLAS/C DLL 段**不会变快**。按 Python 段合计 ≈ 2.5~3.5 ms/帧、折算 8%~11% → **整帧 −0.2~−0.4 ms，FPS +2%~+3%**；乐观（把 bucket 残差全算 Python）≈ −0.5 ms / +5%。
→ **3.13 是"顺手拿到"，不是"解决瓶颈"**。真正的 −4 ms 级收益在 04 的 C 下沉 + beta5 已做的 numpy 化里，两者与本调研**不冲突、可并行**。

### 2.3 数据/接口草案（只给签名与字段，不给实现）

**① `Loom/解释器.json` v2（向后兼容：LoomHub 的 `validate_meta` 不校验新字段，`hub_config.py:161-184` 只查 `name/version/main/main_exe`）**

```jsonc
{
  "name": "Loom", "version": "0.1.0.beta6",
  "python_version": "3.13.15",   // 三段号，与 package_engine_compiled.py:140 的两段号统一（见 ④R8）
  "py_impl": "cpython",          // "cpython" | "cpython-freethreaded"
  "abi_tag": "cp313",            // 空串 = 未知
  "gil": "enabled",              // "enabled" | "disabled"
  "wheel_matrix": "requirements/3.13-win_amd64.txt"
}
```

**② 依赖矩阵（新增目录 `requirements/`，现 `requirements.txt` 保留为 3.12 基线）**

| 目标 | 底线（必须同时满足） |
|---|---|
| 3.12（现状） | `numpy>=1.24, moderngl>=5.8, pygame>=2.5, PySide6>=6.6` |
| **3.13** | `numpy>=2.1, moderngl>=5.11, pygame>=2.6.1, PySide6>=6.6, pillow>=10.4`（否则旧轮子不存在） |
| **3.14** | `numpy>=2.3.2, moderngl>=5.13, PySide6>=6.6, pillow>=11.3` + **`pygame-ce>=2.6` 替代 `pygame`** |

**③ `tools/check_py_support.py`（新增，唯一出题口）**

```python
def matrix(target: str) -> dict:
    """target ∈ {"3.12","3.13","3.14","3.13t","3.14t"} -> {pkg: {"ok":bool,"why":str,"min_ver":str}}"""

def main(argv) -> int:
    """--target 3.13 [--freethreaded] [--json] [--strict]
    退出码契约: 0=全绿; 2=有依赖缺 wheel(打印缺项+最早可用版本); 3=工具链(Nuitka/解释器)不满足"""
```

**④ `Loom/tests/run_all.py` 增强**：`--pyver 3.13`（选解释器）/ `--skip-integration` / `--json-out`；环境变量 `LOOM_PY_TARGET` 供子测试读取（判定"允许的差异"，如 Qt 版本差异）。

**⑤ 打包链参数化**：`tools/package_engine.py` 的 `find_python_embed(version="3.12")` / `build_embed_pyzip(version, ...)`（现为 `:97-108` 硬查 `Python312`）；`build_game.py` 增加 `--pyexe`（默认 `sys.executable`）与 Nuitka 版本下限断言。

**⑥ 运行期探测（一行，落进启动自检日志）**：`sys._is_gil_enabled()`（3.13+ 才有；低版本用 `getattr` 兜底）→ 写日志与 `bench_result`，让"这台机器是不是 nogil 构建"永远可查。

### 2.4 判定门（Decision Gate，硬条件，任一不过就不迁）

| 门 | 判据 | 现状 |
|---|---|---|
| **G1 依赖门** | 依赖表每项在目标 tag 的 win_amd64 有 wheel（或纯 `py3`） | 3.13 ✅ / 3.14 ❌(pygame) / 3.13t ❌ / 3.14t ❌ |
| **G2 工具链门** | Nuitka 官方声明含目标版本 **且** 本机 standalone 产物可运行 | 3.13 ✅(2.7.1 实测) / 3.14 ✅(4.3.5 实测) / t ❓ |
| **G3 回归门** | 121 个测试文件全绿 + 真实窗口 `test_integration.py` 通过 | 3.13 部分 ✅（14/121，见附录 B） |
| **G4 性能门** | 真实引擎 bench（同场景同驱动，3 次中位数）：FPS/TPS 不劣于基线 −2%，帧抖动不升 | 3.13 未做（计划 S3） |
| **G5 线程安全门**（仅 t） | 依赖全 t wheel + Nuitka 可编 t + 24h 压测零 crash/断言 + `test_parallel/scheduler_pool` 全绿 | 全部未验证 |

---

## ③ 分步落地计划（方案 B：3.13 隔离预研分支，主线不动）

> 与 `docs/design/版本计划_Loom0.1.0.beta6_20261109.md:115,127` 的 Q2=B 一致；本文把"预研"落成**可验收步骤**。

| 步 | 做什么 | 验收（可执行） | 通过判据 | 失败处置 |
|---|---|---|---|---|
| **S0**（0.5 人天） | 冻结基线：记录 3.12 的 `--bench` 三场景与 121 测试结果、启动时间 | `py -3.12 Loom/Loom.py --bench <scene>` ×3；`py -3.12 Loom/tests/run_all.py` | 基线文件入库（含 3 次中位数与标准差） | 无基线则后续全部不可判 → 必须先做 |
| **S1**（0.5） | 落 `tools/check_py_support.py` + `requirements/3.13-win_amd64.txt` | `py -3.12 tools/check_py_support.py --target 3.13` → exit 0；`--target 3.14` → exit 2 且点名 pygame | 输出与本文 1.2 矩阵逐项一致（差异=脚本 bug） | 修脚本，不加白名单 |
| **S2**（1.0） | 建 3.13 venv → 跑**全量 121** + 集成测试，产出差异清单 | `py -3.13 Loom/tests/run_all.py`；`LOOM_PY_TARGET=3.13` | 121 全绿 + 集成绿；任何红必须有 issue 与根因 | 红灯即停，回 S1 定性 |
| **S3**（1.0） | 性能对照：同场景 bench ×3，比对 S0 | `py -3.13 Loom/Loom.py --bench <同三场景>` | G4：FPS/TPS ≥ 基线 −2%，启动不劣化 | 不达标 → 方案 A（不迁），结论回写 beta6 计划 |
| **S4**（1.0） | 打包双轨：3.13 embed + Nuitka（2.7.1 原样）+ 解释器.json v2 | `py -3.13 tools/package_engine.py --version 0.1.0.beta6`；产物内 `Loom/解释器.json` 的 `python_version` = 3.13.x | LoomHub 能扫描/启动该包（`hub_config.discover_interpreter` 非 None）；`validate_meta` 通过 | 回退 `--pyver 3.12` 重打 |
| **S5**（0.25） | 决策会：按 G1~G4 出 A/B/C 建议 | 本报告 2.4 表填实测值 | 人类签字 | — |
| **S6**（1.5，条件触发） | 3.14 前置：`pygame → pygame-ce` 的 API 差异评估（pygame 用在 20 处：`audio_backend.py:99,108`、`loom_font.py:17-18`、`loom_texture.py:22`、`loom_ui.py:799,999` 等） | `py -3.14 -m pip install --dry-run --only-binary=:all: pygame-ce` → 0；3.14 上跑 S2 同套测试 | 121 全绿 + 无渲染/输入回归 | 保持 3.13，3.14 挂起 |
| **S7**（0.25/季） | free-threading 门铃：每季跑一次 `check_py_support.py --target 3.14t --strict` 并记录 PySide6/pygame/Nuitka 状态 | 一条命令 + 一行结论进台账 | 三门齐开才启动 G5 | 长期不开 = 长期不投入 |

**测试点（每步必带）**：S1 的矩阵脚本要有自测（喂假数据断言 exit 2/3 分支）；S2/S3 必须**同机同驱动同场景**，否则数据不可比；S4 必须验证"包里真的是 3.13 解释器"（`python -VV` 打进构建日志），不能只看元数据。

---

## ④ 风险与回滚

| # | 风险 | 触发条件 | 缓解 | 回滚 |
|---|---|---|---|---|
| R1 | **3.13 收益不达预期**（+1%~+3% FPS） | S3 结果 < +1% | 在 S0 就声明"目标只是打通迁移路径"，不承诺 FPS | 分支丢弃，零成本 |
| R2 | **free-threaded 假可行**（有人以为能顺手开） | 尝试 `--enable-gil=off` | G5 门 + 本文 1.8 表；把 PySide6 的 abi3 事实写进团队共识 | 无（根本装不上，不会误上线） |
| R3 | **pygame @ 3.14 长期断供** | 2.6.1 之后一年无 cp314 | 走 S6 的 pygame-ce；API 兼容度高但**音频/字体后端行为需实测** | 留在 3.13 |
| R4 | **Nuitka 版本跃迁风险**（2.7.1 → 4.x 跨 3 个大版本） | 上 3.14 就必须升 | 单独分支先编"编译器自身测试工程"，再编 Loom；`--assume-yes-for-downloads` 保持 | 3.14 分支回退 2.7.1/3.13 |
| R5 | **Nuitka 常量折叠坑复发** | `fastpath.py:47-52` 记录：模块级 if 分派、`_CKERNELS is None` 判断被折叠 → 编译版静默走 numpy | 编译版必须跑 `test_lod_fastpath` + 一条"ckernels 真被调用"的探针（现成 `tests/_tmp/ckernels_bench.py`） | 保持 dict 容器写法（已修） |
| R6 | **numpy 2.2 → 2.5 行为差异** | 3.14 场景默认装 2.5.4 | `requirements/` 锁版本；跑 `test_physics/test_lighting/test_interp_state` 数值回归 | 锁回 2.2.x（3.13 支持） |
| R7 | **PySide6 6.11 → 6.12 行为差异** | 3.13/3.14 默认装 6.12.0 | 14 个 Qt 相关测试已双跑绿；再补 `test_editor_focus/scrollbar/ui_multi_canvas_hit` | 锁 6.11.x（abi3 全版本可用） |
| R8 | **打包元数据格式不一致**（源码包 `3.12.10` vs 编译包 `3.13`） | `Loom/解释器.json:4` vs `tools/package_engine_compiled.py:140` | 统一三段号 + v2 字段；`validate_meta` 只查格式（`hub_config.py:176-177`），改动安全 | 元数据回写旧值（Hub 侧无状态） |
| R9 | **插件沙箱白名单漂移** | 3.13/3.14 新增/改名的 stdlib 模块或属性（`plugin_sandbox.py:59-65` 已警示） | 升级 PR 必附 `test_plugin_sandbox_escape.py` + `test_plugin_trust_toctou.py` 结果 | 沙箱门单独 revert |
| R10 | **集成测试无头不可跑** | CI 无 GPU/显示器 | S2/S3 在本机跑；CI 只跑无头子集（`run_all.py:26-28` 本就把 `test_integration.py` 放最后） | — |
| R11 | **解释器体积/启动** | embed 包内 `python/` 目录 | 实测 stdlib 本体 3.12/3.13/3.14 = 51/52/55 MB（差 <8%），启动 104.6→84.9→82.0 ms | 无（不变差） |
| R12 | **本机多解释器污染** | `py -3.13` 的全局 site-packages 被当测试环境 | S2 起用 venv（`py -3.13 -m venv .venv313`），不依赖全局 | 删 venv |

**回滚成本**：改动收敛在「分支 + `requirements/` 新目录 + `解释器.json` 单字段 + 打包脚本一个参数」，主线净改动 ≤ 200 行；`git revert` 单提交即可，无数据迁移、无用户目录格式变更（`docs/design/用户配置目录契约_20261108.md` 不受影响）。

---

## ⑤ 工作量估计

| 步骤 | 人天 | 会话数 | 前置 |
|---|---|---|---|
| S0 基线冻结 | 0.5 | 1 | 能跑 `--bench`（需 GPU 窗口） |
| S1 矩阵脚本 + 依赖表 | 0.5 | 1 | 无 |
| S2 3.13 全量回归 | 1.0 | 2 | S1 |
| S3 性能对照 | 1.0 | 2 | S0/S2 |
| S4 打包双轨 | 1.0 | 2 | S2 |
| S5 决策文档 | 0.25 | 0.5 | S1~S4 |
| S6 3.14（pygame-ce） | 1.5 | 3 | S3 通过（条件触发） |
| S7 t 门铃/季 | 0.25·n | 0.5/季 | — |
| **合计（到 S5 = "3.13 可发布"）** | **4.25 人天** | **8.5 会话** | |
| 合计（含 S6 = "3.14 可发布"） | 5.75 人天 | 11.5 会话 | |

---

## ⑥ 与现有代码的兼容边界

| 边界 | 结论 | 依据 |
|---|---|---|
| **C 侧 ABI** | ckernels/pipeline/physics/script 全是**无 Python.h 的纯 C DLL**（ctypes `CDLL` + 显式 `argtypes/restype`），与解释器小版本**无关** | `fastpath.py:64-83`、`pipeline_glue.py:164`、`physics_bridge.py:1298` |
| **ctypes 调用约定** | 现有代码已显式声明；升级不改变约定。**风险只在 free-threaded**（回调线程语义） | `filedialog.py:252-253`、`crash_reporter.py:81` |
| **LoomHub 契约** | `validate_meta` 不校验 `python_version` 数值（只查 x.y.z 格式），改版本号无需同步 Hub；`cfg.python_version()` 是**运行时探测 exe** | `LoomHub/hub_config.py:161-184`、`:582-596` |
| **发布说明链路** | `tools/release_github.py:363-377,433` 从包内 `解释器.json` 读 `python_version` 填文案 → 改字段自动生效 | 读文件 |
| **用户目录契约** | 与解释器版本无关（`%LOCALAPPDATA%\Loom` 结构不变） | `docs/design/用户配置目录契约_20261108.md` |
| **与 04（C 下沉）的边界** | **正交**：04 动 DLL 源码与 `.dll` 哈希、需重编；本文只动解释器/依赖/打包参数、**不碰 DLL**。可并行，但合并时共用同一个 121 测试门 | 04 §⑥ |
| **与 01/02/03 的边界** | 无交叠（渲染/资产/动画）；04 的 hot-path 结论是本文 §2.2 收益算术的分母 | 04 报告 |
| **本次不越界** | 未改任何受跟踪文件；探针全在 `Loom/tests/_tmp/`（gitignore）；未执行 git 写操作 | `git status --porcelain` |

---

## ⑦ 需要人类裁决的封闭问题

| # | 问题（封闭式） | 选项 | 建议 |
|---|---|---|---|
| Q1 | 本轮 Python 策略？ | A 不迁 / **B 3.13 隔离分支预研（主线不动）** / C 主线直接迁 3.13 | **B**（G1~G3 实测已过，G4 待 S3；风险全在分支内） |
| Q2 | 是否允许 3.13 专用依赖底线抬高（`moderngl>=5.11`、`numpy>=2.1`、`pygame>=2.6.1`）？ | A 允许（新 `requirements/3.13-*.txt`）/ B 不允许（保持 `>=5.8`，则 3.13 无轮子） | **A**（不改则 S1 直接失败） |
| Q3 | 是否为 3.14 把 `pygame` 换成 `pygame-ce`？ | A 换（唯一通路）/ B 不换（3.14 本轮不碰） | **B（本轮）**，A 留给 S6；pygame 用在 20 处含音频/字体后端，替换需独立回归 |
| Q4 | free-threading 是否给"每季 0.25 人天"门铃预算？ | A 给 / B 不给（等别人先趟） | **A**（成本极低、避免错过生态拐点） |
| Q5 | 若走 3.14，是否允许 Nuitka 脱离 2.7.1 升到 4.x？ | A 允许（独立分支先验）/ B 不允许 | **A**（3.14 的硬前置；2.7.1 官方只到 3.13） |
| Q6 | 3.13 预研分支是否**必须**跑真实窗口集成测试？ | A 必须（本机 GPU）/ B 可豁免（只跑无头子集） | **A**（唯一能抓"3.13 下 GL 上下文行为变化"的门） |
| Q7 | 是否为 3.13 单独出第 2 个发布包（`Loom-0.1.0.beta6-py313.zip`）？ | A 出 / B 不出（只在内部预研） | **B**（beta6 只留一条发布线，降低用户支持面） |
| Q8 | 若 S3 只有 +1%~+3% FPS，还迁吗？ | A 迁（为 3.14/生态提前打通）/ B 不迁（留 3.12） | **A，但降级为"技术债清理"**：收益预期写清——这不是性能项目，是**迁移路径项目** |

---

## 附录 A：可复现证据索引

| 结论 | 证据（命令 / 文件:行） |
|---|---|
| 3.13 全依赖可解析 | `py -3.13 -m pip install --dry-run --only-binary=:all: pygame moderngl numpy PySide6 glfw wgpu pillow` → EXIT 0 |
| 3.14 仅 pygame 失败 | `py -3.14 -m pip install --dry-run --only-binary=:all: pygame moderngl numpy` → `No matching distribution found for pygame` |
| wheel 最早版本矩阵 | PyPI PEP 691 simple index 扫描（文件名三分组统计，输出即 §1.2 表） |
| Nuitka 2.7.1 支持到 3.13 | `https://pypi.org/pypi/Nuitka/2.7.1/json` → "Python 3 (3.4 - 3.13) are supported"（2025-05-08） |
| Nuitka 4.0 起支持 3.14 | `https://pypi.org/pypi/Nuitka/4.0/json` → "3.4 - 3.14"（2026-02-05） |
| Nuitka 2.7.1 可编 3.13 | `py -3.13 -m nuitka --standalone --msvc=latest ... hello13.exe` → 运行输出 `hello 3.13.15` |
| Nuitka 4.3.5 可编 3.14 | 同上（3.14）→ `hello 3.14.7` |
| 3.13 零改动跑引擎/编辑器 | `py -3.13 -c "import engine"` / `import editor` → OK |
| 14 测试文件双跑全绿 | `foreach ($v in @('3.12','3.13')) { py -$v tests\<test>.py }`（清单见 §1.5） |
| 纯 Python 微基准 | `py -3.12/3.13/3.14 Loom/tests/_tmp/research_05_interp_bench.py` |
| GIL 交接/加速比 | `py -3.12/3.13/3.14 Loom/tests/_tmp/research_05_gil_probe.py` |
| numpy 是否释放 GIL | `py -3.12 Loom/tests/_tmp/research_05_numpy_gil.py` |
| beta5 GIL 饥饿现场 | `docs/handoff/开发日志_LoomHub0.1.3_Loom0.1.0.beta5_20261109.md:43`；`Loom/loom_logic_thread.py:35-42` |
| TPS 上限 = 单核 GIL | `docs/guides/Loom_引擎操作手册与全功能测试清单.md:26-30` |
| 每帧成本分母（§2.2） | `docs/design/research_beta6_04_python_hotspots.md` §1.4/§1.5 |

探针文件（全部 gitignore，未改受跟踪文件）：`Loom/tests/_tmp/research_05_interp_bench.py`、`research_05_gil_probe.py`、`research_05_numpy_gil.py`、`research_05_nuitka_hello.py`（Nuitka 产物目录 65 MB 已清理，命令可原样重跑）。

## 附录 B：本次未闭合/未验证项（诚实登记）

1. **未在 free-threaded 解释器上实跑**：本机 `py -0p` 无 3.13t/3.14t，t 相关结论由「官方文档 + wheel tag 存在性」推出（PySide6 的 abi3 与 t 不兼容是官方硬约束），但**没跑过 import 失败现场**。
2. **Nuitka × free-threaded 完全未验证**（无声明、无实测）。
3. **只跑了 14/121 个测试文件**（挑的是无头、跨链路、Qt 相关的代表）；全量与 `test_integration.py` 留给 S2/S3。
4. **3.14 微基准反而变慢 8%~19%**，与官方方向相反，归因冷启动/噪声，**未复现验证**，需 S3 的真实引擎 bench 定论。
5. **未在 3.14 上实测编辑器**（3.14 环境里未装 PySide6）。
6. **未测 `--bench` 真实帧率**（需 GPU 窗口；只读任务里不长跑真实渲染）。
7. **JIT（3.14）完全未评估**——被 pygame 门挡住，且它与 Nuitka 编译态叠加后的行为无先例。
