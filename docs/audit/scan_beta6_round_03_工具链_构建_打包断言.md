# 工具链 / 构建 / 打包断言 复核报告（beta6 第四轮 · 编号 03）

> 审计者：独立复核子代理（只读）。范围 = 已提交 git diff 7c734e8..HEAD 中与本编号相关的部分。
> 判定基准一律引用**被审对象自身的白盒契约**（脚本 docstring / 注释 / 版本计划裁决 / 指南命令），不引外部标准。
> 本文件是全量报告；回给派发方的消息为 30 行摘要。

## 0. 结论速览

| 项 | 结论 |
|---|---|
| 统计 | **PROVED 8 / DISPROVED 3 / UNKNOWN 2 / CONTRADICTION 0**（明细见 §4） |
| 新增断言是否"真的会失败" | **会**（P-12 实测：缺 qwindows.dll / 缺 pygame DLL / 旧布局 / cupy 四类都命中），但**内容残缺可绕过**（P-03） |
| pygame 布局断言 vs 真实 3.13+Nuitka 4.3.5 | **一致**（5 份真机产物统一 15 DLL + 无根 SDL2；beta5 发货包 0 DLL 正是它要拦的坏包） |
| 根目录 SDL2.dll 判死会误拒合法产物? | **今日不会**（本机 4 份 4.3.5 产物均无根 SDL2）→ P-DISPROVED，但判据无法区分"无害根副本"（P-05 尾巴） |
| 解释器.json 3.13.15 三处自洽? | **不自洽**：源码打包器仍嵌 **3.12.10**（P-02）；编译包版本取自**打包器进程**（P-09） |
| assets 口径不一致 | **仍存在**，但源码包缺 assets 不构成坏包（实测降级到内置三网格）→ P-DISPROVED + P3 备注 |
| 文档命令 vs 实际脚本 | 三处不一致：缺 `--output-filename=Loom.exe`（P-07）、**dev 档位命令在已提交文档里不存在**（P-13）、编译包 Loom.bat/README 仍写源码包结构（P-06） |

**必须先看的两条**（直接伤 beta6 发货）：

- **P-01（P1）**：源码包启动时 Hub 用**系统 3.13** 顶掉包内**自带 python/**，且静默；没有 3.13 的机器则对自足包误报"可能启动失败"。
- **P-02（P1）**：源码打包器仍以 **Python312** 为嵌入式运行时（实测包内 = 3.12.10），而包内 解释器.json 写 **3.13.15** —— 与 P-01 叠加后，"包内 798MB python/" 成了被弃用的死重。

### 疑似在途（只标注，不据此下结论）

`git status --porcelain` 显示以下文件在审计时仍未定稿，本报告不对其内容下结论，只在相关条目注明"在途已覆盖 / 在途待验证"：
`tools/package_engine.py`（+26 行：ckernels/core_components 断言、build_info_problems 档位校验）、
`tools/package_engine_compiled.py`（+16 行：档位校验）、
`Loom/build_entry.py`、`Loom/build_game.py`、`使用操作指南.txt`（新增 dev/release 两档段）、`tools/build_engine.py`（未跟踪）、
`docs/audit/scan_beta3_05_packaging_release.md`。

---

## ① 范围与方法

### 1.1 文件清单（已提交部分，行号为 HEAD 行号）

| 文件 | 关注点 | 本轮引入? |
|---|---|---|
| tools/package_engine.py | L84-89 断言常量；L92-118 三个断言函数；L254-262 make_zip 调用 | **是**（cd27aae） |
| tools/package_engine_compiled.py | L83-87 Qt 断言、L89-93 cupy 断言、L101-105 运行时布局断言、L160 python_version、L173-174 启动器/README | **是**（cd27aae） |
| Loom/解释器.json | L4 python_version 3.12.10→3.13.15 | **是**（42d5d55） |
| LoomHub/hub_config.py | L553-556 python_xy、L559-611 resolve_python_for、L613-628 interp_python_note、L644-650 嵌入式优先、L696-706 版本覆盖 | **是**（cb6aa5d） |
| LoomHub/hub_commands.py | L493-497 新增 python_note、L523-526 out | **是**（cb6aa5d） |
| LoomHub/hub_controller.py | L596 提示拼接 | **是**（cb6aa5d） |
| 使用操作指南.txt | L411-431 §7.5 构建命令、L22-57 环境与启动命令 | **是**（cd27aae / 42d5d55） |
| docs/design/版本计划…beta6…md | L226-234 §9.5 构建档位裁决、L219-227 §9.4 3.13 裁决 | **是** |
| Loom/tests/test_hub_python_version.py | 新增 186 行测试 | **是** |

### 1.2 方法（对齐 SCAN_PROTOCOL + 两份方法论文档）

1. 粗筛按"契约/不变量/错误模型/资源边界/并发/边界输入"六类打标签；跳过项按四类允许理由留痕（§2.2）。
2. 每项先**反手证伪**（必须做完整路径枚举）再**正手证真**（必须给最小复现 + 可跑命令）。
3. 能跑的不猜：所有"是否一致"的结论都落到探针或真实产物上。
4. 只读：未修改任何受跟踪文件；探针全部写在 `Loom/tests/_tmp/audit_b6_03_*.py`。审计结束 `git status --porcelain` 与开工逐行一致。

### 1.3 跑过的命令与探针（可复跑）

```
# 1) 环境事实
py -0p                              # 3.14 / 3.13(3.13.15) / 3.12(3.12.10, 默认) / 3.11 / 3.10 / 3.9 / 3.8
py -3.13 -m nuitka --version        # 3.13.15 + Nuitka 4.3.5
py -3.13 -m nuitka --plugin-list    # 含 pyside6 / tk-inter
py -3.13 -m nuitka --help           # --windows-console-mode / --mode=COMPILATION_MODE / --output-filename / --output-dir

# 2) 用 HEAD 版断言函数跑真实产物
py -3.13 Loom\tests\_tmp\audit_b6_03_probe_head_asserts.py
# 3) 断言可绕过性
py -3.13 Loom\tests\_tmp\audit_b6_03_probe_bypass.py
# 4) 证伪侧 + 根 SDL2 + 编译包 Loom.bat
py -3.13 Loom\tests\_tmp\audit_b6_03_probe_neg.py
# 5) Hub 启动命令 vs 包内嵌入式 python
py -3.13 Loom\tests\_tmp\audit_b6_03_probe_embedded.py
# 6) 源码打包器嵌入运行时 vs 包内元数据
py -3.13 Loom\tests\_tmp\audit_b6_03_probe_meta.py
# 7) 发货 zip 实际布局（beta5 / beta6）
py -3.13 Loom\tests\_tmp\audit_b6_03_probe_zip.py
py -3.13 Loom\tests\_tmp\audit_b6_03_probe_zip2.py
py -3.13 Loom\tests\_tmp\audit_b6_03_probe_readme.py
# 8) 排除 assets 后资源面板是否降级
py -3.13 Loom\tests\_tmp\audit_b6_03_probe_assets.py
# 9) 回归
py -3.13 Loom\tests\test_hub_python_version.py    -> ALL PASS
py -3.13 Loom\tests\test_hub_controller.py        -> ALL PASS
```

---

## ② 粗筛（含跳过留痕）

### 2.1 疑似项清单（粗筛不判决）

| ID | 位置(HEAD) | 标签 | 初步方向 |
|---|---|---|---|
| P-01 | hub_config.py:696-706 vs :644-650 | IFACE-PRECOND / SEM-MISMATCH | python_version 覆盖发生在"嵌入式优先"之后且无条件 → 源码包被换成系统解释器 |
| P-02 | package_engine.py:138-149, :204 / 解释器.json:4 | IFACE-VERSION / AUDIT-DOCIMPL | 打包器仍找 Python312（实测 3.12.10），包内元数据写 3.13.15 |
| P-03 | package_engine.py:92-95, :105-118 | TOOL-HEURISTIC | 只用 os.path.exists / 计数，内容残缺可通过 |
| P-04 | package_engine.py:89, :113 | OVERFIT-HARDCODE | PYGAME_MIN_DLLS=15 恰等于今日产物 15，零余量 |
| P-05 | package_engine.py:116-117 | AUDIT-ASYMMETRY | "根有 SDL2"一律判死，不区分是否同时缺 pygame/SDL2 |
| P-06 | package_engine.py:183-196 + compiled:173 | AUDIT-DOCIMPL | 编译包沿用源码包的 Loom.bat/README（指向 python\pythonw.exe + Loom.py） |
| P-07 | 使用操作指南.txt:411-414 | TOOL-CLI | 编辑器编译命令缺 --output-filename=Loom.exe，产物名与打包器期望不符 |
| P-08 | hub_commands.py:497 vs :525 | AUDIT-DEADCODE | 新增 python_note 在命令层从未被消费 |
| P-09 | package_engine_compiled.py:160 | IFACE-UNIT | python_version 取打包器 sys.version_info，非产物真实版本 |
| P-10 | package_engine.py:112 (os.listdir) | SEM-SILENT | pygame/ 不可读时抛 OSError，而非返回问题列表 |
| P-11 | package_engine.py:23-24 vs compiled:42 | DESIGN-DRIFT | 源码包排除 assets，编译包显式包含 |
| P-12 | package_engine.py:84-118（正面核查项） | TOOL-SCOPE | 断言是否与真实 3.13+Nuitka 4.3.5 产物一致、是否死代码 |
| P-13 | 使用操作指南.txt:411-414 vs 版本计划:228-234 | AUDIT-DOCIMPL | §9.5 要求 dev(force)/release(disable) 两档，已提交文档只有 disable 一档 |

### 2.2 跳过登记（四类允许理由）

| 编号 | 位置 | 跳过理由类别 | 具体依据 |
|---|---|---|---|
| SKIP-01 | 指南 L417-419"漏 --enable-plugin=pyside6 → 缺 qwindows.dll 且体积小 ~8MB" | 无法在只读预算内取得对照（缺"故意不带插件"的真实产物） | 需一次完整 Nuitka 编译（10min+）并写产物；现有 4 份产物都带该插件，无从证伪，故不判 |
| SKIP-02 | 软链（mklink /J）绕过 | 工具/语言规范保证 | `os.path.exists` 对 junction 返回 True，但 `os.walk` 不把 junction 当 symlink（scandir 视为目录）→ zip 会顺着收内容，对产物无实质危害，合入 P-03 说明 |
| SKIP-03 | `--nofollow-import-to=cupy` 是否真挡住 123MB | 已有实测覆盖 | C:\loom_build\engine = 141.6MB 且无 cupy；engine_dbg = 269.6MB 且含 cupy/cupy_backends/cupyx → 与 L99-100 注释一致 |
| SKIP-04 | `Loom/bench_result_对比台账.txt` 里的 force 档历史命令 | 与本次断言无关（历史台账） | 已确认为 bench 版历史记录，非发布流程契约 |
| SKIP-05 | archive/ 下 bench_stable 同类脚本 | 非受跟踪业务路径（archive 为归档） | 粗筛范围限定在 tools/ + LoomHub/ + 指南 + Loom/build_*.py |

---

## ③ 逐项裁决（8 段式）

### P-01 · 源码发布包启动时被系统 3.13 顶掉包内嵌入式 python/ **[P-PROVED / P1]**

**反手（证伪：这里不可能出问题）**

1. 判定基准：hub_config.py:644 注释"1. 引擎自带嵌入式 Python 优先（发布包 zip 设计如此：开箱即用）"；package_engine.py:200-207 README"嵌入式 Python 运行时已内置，双击 Loom.bat 启动"。契约 = **有包内 python/ 就用它**。
2. 代码证据：L697 `py_exe = default_python(engine_dir=info.get('dir'))`（可能已是嵌入式）→ L701-706 `if kind != 'exe' and _want: _matched = resolve_python_for(_want); if _matched: py_exe = _matched`（**无条件覆盖**）。
3. 反手路径枚举（build_launch_command 全部路径）：
   - 路径 a：kind='exe' → L701 条件为假 → 不覆盖。**不成立**。
   - 路径 b：kind='py' 且 python_version 空/缺失 → L702 得空串 → 不覆盖。**不成立**（但见 P-02：beta6 元数据非空）。
   - 路径 c：kind='py' 且 python_version 非空、resolve 失败 → 不覆盖（保留嵌入式）。**不成立**。
   - 路径 d：kind='py' 且 python_version 非空、resolve 成功 → **覆盖**，嵌入式被丢弃。
   → 存在路径 d，证伪失败（无法覆盖全部路径）。
4. 实际行为：见第 7 段实测。
5. 差异：契约"包内 runtime 优先" vs 实际"系统 runtime 优先"；且 L613-628 的提示函数同样只看系统（resolve 成功即返回空串 → 用户完全无感）。
6. 触发条件：任何 beta6 **源码包**（顶层 Loom/ + python/）在装有匹配 major.minor 解释器的机器上被 LoomHub 启动。
7. 验证（实测）：

   ```
   $ py -3.13 Loom\tests\_tmp\audit_b6_03_probe_embedded.py
   info.kind            = py
   info.python_version  = 3.13.15
   default_python(嵌入) = ...\Temp\b6_03_pkg_v43owjt1\0.1.0.beta6\python\python.exe
   resolve_python_for   = C:\Users\Administrator\AppData\Local\Programs\Python\Python313\python.exe
   launch cmd[0]        = C:\Users\Administrator\AppData\Local\Programs\Python\Python313\python.exe
   用的是包内 python/ ? = False
   python_note          = ''

   --- 场景2: 本机没有 3.13(模拟) ---
   launch cmd[0]        = ...\0.1.0.beta6\python\python.exe      <- 用包内(正确)
   python_note          = '引擎要求 Python 3.13.15，本机未找到匹配解释器，已回退默认 Python（可能启动失败，请安装 Python 3.13 或 py -3.13）'
   ```

   安装路径可达性已核实：hub_install.py:118-130 解压到 `<root>/<version>/` 后登记 `<root>/<version>/Loom` → default_python 能找到同级 `python/`（L646-650）。
8. 影响与等级：**P1**。① 发布包"开箱即用"承诺失效——包内 798MB python/ 被弃用，改吃宿主 site-packages（宿主 3.13 若没装 moderngl/PySide6 即 ModuleNotFoundError，而包内本来是全的）；② 反向场景对自足包误报"可能启动失败"，属假警报，会诱导用户去装 3.13。

---

### P-02 · 源码打包器仍嵌 Python 3.12.10，包内元数据却写 3.13.15 **[P-PROVED / P1]**

**反手（证伪）**

1. 判定基准：版本计划 §9.4"保留 Python 3.13.15 主线"；指南 L22"Python 3.13.15（py -3.13 命令；2026-11-09 主线已迁 3.13）"；package_engine.py:5 docstring"嵌入式 Python 3.12"。
2. 代码证据：L164-176 `find_python_embed()` 只找 `%LOCALAPPDATA%\Programs\Python\Python312` / `C:\Python312` / `tools/python-embed`；L183-184 失败文案同为 3.12；L204 README 写"嵌入式 Python 3.12"；make_zip L300-313 只回写 `version`，**python_version 原样保留**。
3. 反手路径枚举（包内 python_version 的三种来源）：
   - a. 源 解释器.json 直接拷入 → 3.13.15（本轮已改）。**成立** → 即"3.12 embed + 3.13.15 声明"。
   - b. make_zip 回写时重算 → 代码无此逻辑。不成立。
   - c. 打包时探测真实嵌入版本并覆盖 → 代码无此逻辑。不成立。
   → 只能走 a，证伪失败。
4. 实际行为：包内 python/ = 3.12.10；包内 解释器.json python_version = 3.13.15；README 写 "python/ <- 嵌入式 Python 3.12"。
5. 差异：三处对同一事实给出两个版本号，且与 §9.4 主线声明冲突。
6. 触发条件：每次 `py tools/package_engine.py`。**若打包机没有 3.12**（主线已迁 3.13 的干净发布机）→ L155-158 直接 `SystemExit('找不到 Python 3.12 运行时')`，**根本发不出源码包**。
7. 验证（实测）：

   ```
   $ py -3.13 Loom\tests\_tmp\audit_b6_03_probe_meta.py
   PE.__file__ = ...\tools\package_engine.py
   find_python_embed() = C:\Users\Administrator\AppData\Local\Programs\Python\Python312
   包内 python/ 实际版本 = Python 3.12.10
   源元数据 python_version = 3.13.15
   包内 解释器.json python_version = 3.13.15
   README:   python/           <- 嵌入式 Python 3.12（含依赖）
   package_engine 里写死 3.12 的位置: L5, L6, L171-172, L183-184, L230
   ```

   本机 3.12 仍在，所以是"静默产出不一致包"；干净发布机会直接失败（见第 6 段）。
8. 影响与等级：**P1**。与 P-01 叠加成"要么系统 3.13 跑（可能缺依赖）、要么包内 3.12 跑（并误报可能失败）"；README 与实际版本对不上，用户按 README 排查会得到错误结论。

---

### P-03 · 三个断言是"存在性/计数"判据，内容残缺可绕过 **[P-PROVED / P2]**

**反手（证伪：判据足够严，不存在绕过）**

1. 判定基准：L80-83 注释"用'路径存在/DLL 数量'作硬判据"。若注释即完整契约，则"内容残缺放行"不算违反契约 —— 这是本条唯一的免罪路径。
2. 代码证据：L94-95 `return [rel for rel in QT_REQUIRED_PATHS if not os.path.exists(...)]`；L112-115 `len(dlls) < PYGAME_MIN_DLLS`。
3. 反手路径枚举（判定的输入域）：`os.path.exists` 真值域 = {不存在, 存在且为文件(含 0 字节), 存在且为目录, 存在且为链接}。代码无 size / PE 头 / 可读性检查 → 三种"存在但无内容"落在同一分支，不可能被判失败。→ 证伪失败。
4. 实际行为：0 字节 qwindows.dll / 同名目录 / 无任何 PySide6 绑定的 dist 全部返回 []（PASS）。
5. 差异：承诺"缺 Qt 依赖就拒绝"，实际只做到"缺路径就拒绝"；Loom.exe 会因缺 QtWidgets.pyd 启动即崩，判据放行。
6. 触发条件：手工拼装 / 不完整拷贝（robocopy 中断、杀软隔离、跨机漏文件）的 dist。
7. 验证（实测）：

   ```
   $ py -3.13 Loom\tests\_tmp\audit_b6_03_probe_bypass.py
   QT_REQUIRED_PATHS = ('PySide6', 'PySide6\qt-plugins', 'PySide6\qt-plugins\platforms\qwindows.dll')
   场景1 0字节 qwindows.dll      -> editor_dist_problems = []
   场景2 qwindows.dll 是目录     -> editor_dist_problems = []
   场景3 全小写路径             -> editor_dist_problems = []
   场景4 真实 dist PySide6 顶层条目数 = 6  其中 .pyd = 5

   $ py -3.13 Loom\tests\_tmp\audit_b6_03_probe_neg.py
   缺 qwindows.dll            -> ['PySide6\qt-plugins\platforms\qwindows.dll']
   缺整个 PySide6             -> ['PySide6', 'PySide6\qt-plugins', 'PySide6\qt-plugins\platforms\qwindows.dll']
   只有 3 条路径、无任何 .pyd -> [] (PASS: 绑定 .pyd 缺了也放行)
   ```

8. 影响与等级：**P2**。断言对"漏 plugin / 旧布局 / cupy"三类真问题有效（见 P-12），但对"内容残缺"无效；建议至少加"qwindows.dll 大小 > 0"与"PySide6/QtWidgets.pyd 存在"，或对 dist 做一次 `Loom.exe --version` 冒烟。

---

### P-04 · PYGAME_MIN_DLLS=15 与今日产物恰好相等（零余量） **[P-UNKNOWN / P2]**

**反手（证伪：不会误拒任何合法产物）**

1. 判定基准：requirements.txt"pygame>=2.5"（**下限，非锁定**）+ L80-83"用 DLL 数量作硬判据"。
2. 代码证据：L89 `PYGAME_MIN_DLLS = 15`；L113 `if len(dlls) < PYGAME_MIN_DLLS`。
3. 反手路径枚举（合法产物的可能来源）：
   - a. 本机 build_game.py（pygame 2.6.1 / Nuitka 4.3.5）→ 15，**通过**（实测）。
   - b. 3.12 环境重打（.__py312）→ 15，**通过**。
   - c. 从旧安装包拷一份（指南 L425-431 的"零编译器"路径）→ 2.7.1 平铺布局 → 命中 P-05 判据，属**预期拒绝**。
   - d. pygame 2.5.x / 更新版本环境 → **本机无法枚举**（未安装，无 wheel 缓存可核）。→ 路径 d 不可枚举 = 证伪失败。
4. 实际行为：阈值与 15 相等，任一 DLL 缺失即 fail；5 份产物全是 15（零余量）。
5. 差异：若某 pygame 版本 wheel 就是 14 个 DLL，判据会以"处理: 用 Nuitka 4.x 重新跑 build_game.py --build-runtime"回应一个**重编也修不掉**的产物（误导性建议）。
6. 触发条件：升级/降级 pygame（requirements 未锁定）后重打运行时。
7. 验证（实测）：

   ```
   $ py -3.13 -c "import pygame;print(pygame.version.ver)"   -> 2.6.1 (SDL 2.28.4)
   $ py -3.13 Loom\tests\_tmp\audit_b6_03_probe_head_asserts.py
   runtime game_player.dist             []
   runtime game_player.dist.__py312     []
   editor engine / engine_dbg / engine_dev  pygameDLLs=15
   beta6 发货 zip 实测 pygame/ .dll = 15（与阈值相等）
   ```

   **还缺什么才能定**：一次 pygame 2.5.x（或其他合法版本）的 `build_game.py --build-runtime` 产物，数一遍 pygame/ 下 DLL 数。若 ≠15 → 升为 P-PROVED（会误拒）；若 =15 → P-DISPROVED。
8. 影响与等级：**P2**，"魔法数 == 今日产物"型判据；建议改为**点名必需 DLL**（SDL2 / SDL2_image / SDL2_mixer / SDL2_ttf / freetype …）而非计数。

---

### P-05 · "根目录出现 SDL2.dll"判死是否误拒合法产物 **[P-DISPROVED / P3]**

**反手（证伪：会误拒）→ 失败；正手（证真：会误拒）→ 亦失败（无合法反例）**

1. 判定基准：L116-117 注释"SDL2.dll 仍在 dist 根 (旧布局残留)"——判据语义是"旧布局残留"，不是"根上多一个文件"。
2. 代码证据：L116-117 `if os.path.isfile(os.path.join(dist,'SDL2.dll')): problems.append(...)`。
3. 路径枚举（本机全部可获得产物）：

   | 产物 | 根 SDL2 | pygame/ DLL | runtime_layout_problems |
   |---|---|---|---|
   | Loom/player_runtime/game_player.dist | 无 | 15 | [] |
   | game_player.dist.__py312 | 无 | 15 | [] |
   | game_player.dist.__old271（Nuitka 2.7.1） | **有 sdl2.dll** | **0** | ['pygame/ 下 DLL 只有 0 个', 'SDL2.dll 仍在 dist 根'] |

   → 2/3 合法产物通过，唯一命中的是真正的旧布局 → 无合法反例，正手失败 → **P-DISPROVED**。
4. 反手侧的残留风险（保留为 P3 尾巴）：判据**无法区分**"旧布局（pygame/ 无 SDL2）"与"根上多一份无害副本（pygame/ 也有 SDL2）"。
5. 差异：语义与实现不完全一致（代码只看根，不看 pygame/ 是否也有）。今天无合法反例，属**未被触发**的不对称。
6. 触发条件（未来）：任何显式把 SDL2.dll 也放根的命令（`--include-data-files`、自定义拷贝脚本）。
7. 验证（实测）：

   ```
   $ py -3.13 Loom\tests\_tmp\audit_b6_03_probe_neg.py
   完整 pygame/ 无根 SDL2      -> []
   完整 pygame/ + 根 SDL2.dll  -> ['SDL2.dll 仍在 dist 根 (旧布局残留)']
   $ py -3.13 Loom\tests\_tmp\audit_b6_03_probe_head_asserts.py
   runtime game_player.dist.__old271  ['pygame/ 下 DLL 只有 0 个 (要求 >=15)', 'SDL2.dll 仍在 dist 根 (旧布局残留)']
   ```

8. 影响与等级：**P3**（今日不误拒）。建议把判据收紧为"根有 SDL2 **且** pygame/ 下没有 SDL2"才判死。

---

### P-06 · 编译包的 Loom.bat / README 仍是源码包写法（实测双击必失败） **[P-PROVED / P2 · [已有]，非本轮 diff]**

**反手（证伪：编译包不用 Loom.bat）**

1. 判定基准：compiled L3-16 docstring 声明包结构（Loom/Loom.exe + build_game.exe + 运行时数据），**不含 python/、不含 .py 主程序**；package_engine.py:190-196 的 bat 写死 `python\pythonw.exe` + `Loom\Loom.py`。
2. 代码证据：compiled L173 `PE.write_launcher(tmp)`、L174 `PE.write_meta_readme(tmp, version, slim=slim)` —— 复用的正是源码包写手。
3. 路径枚举：bat 的两处被调路径 `python\pythonw.exe`、`Loom\Loom.py` 在编译包内是否存在？编译包内容由 L112-152 决定（编辑器 dist + build_game.exe + DATA_DIRS + examples），两者都**不会**出现。
4. 实际行为：bat 执行 → cmd 报 "The system cannot find the path specified."，exit 1。
5. 差异：README 声称"嵌入式 Python 运行时已内置，双击 Loom.bat 启动 / Loom.py <- 主程序"，实际两者都不存在。
6. 触发条件：用户按 README 双击 Loom.bat（发行包头号入口）。
7. 验证（实测，含**已发货** beta6.zip）：

   ```
   $ py -3.13 Loom\tests\_tmp\audit_b6_03_probe_neg.py
   Loom.bat 内容: "%~dp0python\pythonw.exe" "%~dp0Loom\Loom.py" %*
   包内 python\pythonw.exe 存在 ? False
   包内 Loom\Loom.py 存在 ?      False
   cmd /c Loom.bat exit = 1 | stderr = 'The system cannot find the path specified.'

   $ py -3.13 Loom\tests\_tmp\audit_b6_03_probe_zip2.py
   beta5.zip: Loom.bat=True Loom/Loom.py=False python/pythonw.exe=False
   beta6.zip: Loom.bat=True Loom/Loom.py=False python/pythonw.exe=False

   $ py -3.13 Loom\tests\_tmp\audit_b6_03_probe_readme.py
   README.txt: 嵌入式 Python 运行时已内置，双击 Loom.bat 启动。/ python/ <- 嵌入式 Python 3.12 / Loom.py <- 主程序
   顶层条目: ['Loom', 'Loom.bat', 'README.txt']
   ```

8. 影响与等级：**P2**。[已有]——7c734e8 与 HEAD 均如此，不属本轮引入；但**本轮修改了同一批打包文件**（cd27aae 在 compiled 加了 3 条断言）仍未修这条，属"审到了但没顺手修"的既有债，建议本轮收尾一并处理。

---

### P-07 · §7.5 的编辑器编译命令缺 `--output-filename=Loom.exe` **[P-PROVED / P2]**

**反手（证伪：照抄命令能得到打包器要的产物）**

1. 判定基准：指南 L409-420"实际打包…这里只记要点"；compiled L75-76 要求 `--editor-dist` 里必须有 `Loom.exe`。
2. 代码证据：指南 L411-414 命令 = `py -3.13 -m nuitka --mode=standalone --msvc=latest --enable-plugin=pyside6 --windows-console-mode=disable --nofollow-import-to=cupy build_entry.py` —— 无 `--output-filename`、无 `--output-dir`。
3. 路径枚举：Nuitka 未给 --output-filename 时 exe 名 = 主脚本名 → `build_entry.exe`；dist 目录名 = 主脚本名 → `build_entry.dist`。三条旁证：C:\loom_build\builder\**build_game.exe**（脚本名，未改名）、C:\loom_build\engine\build_entry.dist 内是 **Loom.exe**（真机构建给了该旗标）、player_runtime/game_player.dist 内是 **MyGame.exe**（build_game.py L142 给了 `--output-filename=MyGame.exe`）。
4. 实际行为：照抄命令得 `build_entry.exe`；再跑 `package_engine_compiled.py --editor-dist <...>\build_entry.dist` → L75-76 立刻 `_fail('--editor-dist 里没有 Loom.exe')`。
5. 差异：文档命令不可产出打包器接受的产物（链断了），且本轮**还编辑过这段命令**（cd27aae 把它改成 4 行）。
6. 触发条件：任何按指南从零构建编辑器 exe 的人。
7. 验证：

   ```
   $ git show HEAD:使用操作指南.txt | Select-Object -Skip 408 -First 8
   编辑器   py -3.13 -m nuitka --mode=standalone --msvc=latest \
               --enable-plugin=pyside6 --windows-console-mode=disable \
               --nofollow-import-to=cupy \
               build_entry.py   (Loom\ 下)

   $ py -3.13 -m nuitka --help | Select-String 'output-filename|output-dir'
     --output-filename=FILENAME
     --output-dir=DIRECTORY

   $ Get-ChildItem C:\loom_build\builder -File          -> build_game.exe（脚本名，未改名）
   $ Get-ChildItem C:\loom_build\engine                  -> build_entry.dist（内含 Loom.exe）
   $ Get-ChildItem C:\loom_build -Recurse -Filter build_entry.exe -> 0 命中
   ```

8. 影响与等级：**P2**（发布链断点）。指南"只记要点"的免责降低严重度，但要点里少掉的恰好是唯一决定产物名的旗标。

---

### P-08 · 新增 `python_note` 在命令层从未被消费（GUI/命令两入口不一致） **[P-PROVED / P3]**

**反手（证伪：字段被下游使用）**

1. 判定基准：hub_commands.py:500-501 命令 'launch_engine' 的输出即 `cmd_launch_engine` 的返回 dict（L525-526）。
2. 代码证据：L497 `'python_note': cfg.interp_python_note(info)`；L523-526 `out = {'pid'…, 'command'…, 'interpreter'…, 'cwd'…, 'prefer'…, 'mode'…}` —— 无 python_note。
3. 路径枚举（`launch_spec` 的两个消费者）：a. `cmd_launch_engine` → out 不含该键；b. GUI `hub_controller.open_project` → 不走 launch_spec，L596 自己调 `cfg.interp_python_note`（有提示）。→ 字段在 a 路径上死掉。
4. 实际行为：`git grep python_note` 全仓库只有 3 处生产代码（定义/计算/controller），无读取方。
5. 差异：注释 L496"源码引擎要求的 Python 版本匹配不上时的提示"暗示会传给调用者，实际丢弃；GUI 有提示、EAI 命令无提示 → 两入口不一致（而 launch_spec 的存在意义正是"与 GUI 逐字段同构"，见 L457-460）。
6. 触发条件：通过 Hub-EAI `launch_engine` 启动源码引擎且版本不匹配。
7. 验证：

   ```
   $ git grep -n "python_note" HEAD -- LoomHub
   LoomHub/hub_commands.py:497: 'python_note': cfg.interp_python_note(info)}, None
   LoomHub/hub_config.py:613: def interp_python_note(info):
   LoomHub/hub_controller.py:596: py_note = cfg.interp_python_note(interp)
   （cmd_launch_engine 的 out 在 L525-526，无该键）
   ```

8. 影响与等级：**P3**（死载荷 + 两入口不一致）。修法方向：在 `out` 里带上该键，或删掉 L497。

---

### P-09 · 编译包 python_version 取自"打包器进程"而非产物 **[P-PROVED / P3]**

**反手（证伪：取到的一定是产物真实版本）**

1. 判定基准：解释器.json 的 python_version 语义 = 该引擎产物构建所用 Python（版本计划 §9.4 用它表达主线 3.13.15；Hub UI 显示它：NovaHubGUI:442 / hub_view_tk:385）。
2. 代码证据：compiled L160 `'python_version': '%d.%d.%d' % sys.version_info[:3]` —— 取的是**执行打包脚本**的解释器。
3. 路径枚举：a. 用 py -3.13 打包 3.13 产物 → 一致（beta6.zip 实测 3.13.15 ✔）；b. 用 py -3.12 打包 3.13 产物 → 写 3.12.10（错）；c. 产物 3.12 而用 3.13 打包 → 写 3.13.15（错）。
4. 实际行为：版本号与产物解耦；本轮把 '3.12' 改成 '3.13.15'（`%d.%d` → `%d.%d.%d`）后，错误只会更"精确地错"。
5. 差异：元数据应描述**产物**，实现描述**工具进程**。
6. 触发条件：构建与打包用不同解释器（指南/脚本 docstring L19-21 的用法示例只写 `python tools/package_engine_compiled.py`，没锁版本）。
7. 验证：

   ```
   $ py -3.12 -c "import sys;print(sys.version_info[:3])"  -> (3, 12, 10)
   $ py -3.13 -c "import sys;print(sys.version_info[:3])"  -> (3, 13, 15)
   $ py -3.13 Loom\tests\_tmp\audit_b6_03_probe_zip.py   -> beta6.zip python_version='3.13.15'（本次恰好一致）
   产物内真实版本可从 dist 根的 python313.dll 或 build_info.json 读出（真机 dist 根有 python313.dll）
   ```

8. 影响与等级：**P3**（只影响元数据展示与 Hub 台账显示；kind=exe 不读该字段启动）。建议改为从 dist 根 `python3XX.dll` 或 build_info.json 推导。

---

### P-10 · `runtime_layout_problems` 对"pygame/ 不可读"抛 OSError 而非返回问题列表 **[P-UNKNOWN / P3]**

**反手（证伪：异常路径不可达）**

1. 判定基准：函数 docstring L106"返回问题列表（空=通过）"——契约是**总是返回列表**。
2. 代码证据：L112 `dlls = [f for f in os.listdir(pygame_dir) if ...]` —— 无 try/except；调用方 make_zip L254-259 与 compiled L101-105 也无 try。
3. 路径枚举：`os.listdir` 的失败模式 = PermissionError / OSError（目录被并发删除）。要触发需"isdir 为真但 listdir 失败"——窗口极窄（ACL 拒绝或扫描后被删）；本机无法在只读约束下制造 ACL 拒绝（会改安全描述符）。
4. 实际行为：一旦触发，打包器以 **traceback 结束**，而不是"[错误] … 拒绝打包"。
5. 差异：错误模型不一致（契约要求结构化返回，实际抛异常）。
6. 触发条件：pygame/ 被 ACL 拒绝读取（杀软冻结）或并发删除。
7. 验证：静态路径枚举 + 代码事实；**未做 ACL 探针**（只读约束，不改安全描述符）→ 故判 UNKNOWN。合成探针（把 os.listdir 换成抛 PermissionError）只能证明"无 except"，不能证明"真实可触发"。
8. 影响与等级：**P3**。**还缺什么**：一个可控的 ACL 拒绝目录（需 `icacls` 写操作）才能升为 PROVED。

---

### P-11 · 源码包排除 assets / 编译包包含 assets 的口径不一致 **[P-DISPROVED / P3]**

**反手（证伪：不一致会导致"源码包缺 assets"复发为坏包）**

1. 判定基准：package_engine.py:22 注释"player_runtime 由 make_zip 显式预置"——排除集是**有意**的引擎载荷裁剪；research_beta6_02_asset_guid.md:63 已把"引擎打包排除 assets"写成既有事实；上一轮 scan_beta3_05 P-05-23 已判 DISPROVED（判定基准 C2 只要求"运行时在不在"）。
2. 代码证据：package_engine.py:23-24（含 'assets'）vs compiled:42 `DATA_DIRS = ['scripts','GUI','assets',…]`。
3. 路径枚举（缺 assets 时编辑器还有没有内容）：editor.py:1378-1381 内置三网格恒在；:1385 `if os.path.isdir(d)`；:1393 `if os.path.isdir(base)` → 三次文件系统访问全部有守卫。
4. 实际行为：assets 不存在时资源面板返回 3 个内置网格，**不抛异常**。
5. 差异：两份打包器对 assets 策略不同（源码包 = 纯引擎；编译包 = 运行时数据包），属产品口径差异而非缺陷。
6. 触发条件：解压源码包后打开资源面板。
7. 验证（实测）：

   ```
   $ py -3.13 Loom\tests\_tmp\audit_b6_03_probe_assets.py
   assets 目录不存在 -> [{'type':'mesh','key':'builtin.cube'…},{'…builtin.sphere'…},{'…builtin.plane'…}]
   assets 空目录     -> ['builtin.cube', 'builtin.sphere', 'builtin.plane']

   $ Get-ChildItem Loom -Recurse -Directory -Filter assets
   Loom\assets ; Loom\tests\ab_scenes\assets ; Loom\tests\_tmp\sbscan01\assets
   （除 Loom/assets 外没有别的运行时 assets 目录会被误排）
   ```

8. 影响与等级：**P3**，只丢 10 个示例资产文件（materials / meshes / *.prefab / 假车库.mtl）。若产品上决定"源码包也要带示例资产"，应在打包器显式加白名单目录（与 P-05-18"黑名单式收集"同源）。

---

### P-12 · 布局断言与真实 3.13 + Nuitka 4.3.5 产物是否一致、是否死代码 **[P-DISPROVED（断言无问题）]**

**反手（证伪：断言与真实产物不符 → 断言是错的）**

1. 判定基准：L80-83 注释"4.x 把 pygame 依赖 DLL 放进 dist 的 pygame/ 子目录（2.7 平铺在根）"；L110"缺 pygame/ 子目录 (Nuitka>=4 的 DLL 布局)"。
2. 代码证据：L105-118。
3. 路径枚举（本机全部可获得产物，5 份）：

   | 产物 | 构建链 | pygame/ DLL | 根 SDL2 | 断言结果 |
   |---|---|---|---|---|
   | C:\loom_build\engine\build_entry.dist | 4.3.5 / 3.13 | 15 | 无 | qt=[] bloat=[] |
   | C:\loom_build\engine_dbg\build_entry.dist | 4.3.5 / 3.13（带 cupy） | 15 | 无 | bloat=['cupy','cupy_backends','cupyx'] |
   | C:\loom_build\engine_dev\build_entry.dist | 4.3.5 / 3.13 | 15 | 无 | [] |
   | Loom/player_runtime/game_player.dist（及 .__py312） | 4.3.5 | 15 | 无 | [] |
   | game_player.dist.__old271 | **2.7.1** / 3.12 | **0** | **有 sdl2.dll** | 两条都命中 |

4. 实际行为：断言与真实布局**逐项吻合**：4.3.5 产物全部通过，2.7.1 产物两条都命中。
5. 差异：无（正面核查项）。
6. 触发条件：—
7. 验证（实测）：

   ```
   $ py -3.13 Loom\tests\_tmp\audit_b6_03_probe_head_asserts.py
   editor engine        qt=[] bloat=[]
   editor engine_dbg    qt=[] bloat=['cupy', 'cupy_backends', 'cupyx']
   editor engine_dev    qt=[] bloat=[]
   runtime game_player.dist          []
   runtime game_player.dist.__py312  []
   runtime game_player.dist.__old271 ['pygame/ 下 DLL 只有 0 个 (要求 >=15)', 'SDL2.dll 仍在 dist 根 (旧布局残留)']

   # 该断言要拦的真实坏包确实存在过（beta5 发货包 pygame/ 0 个 DLL、全包无 SDL2.dll）：
   $ py -3.13 Loom\tests\_tmp\audit_b6_03_probe_zip2.py
   beta5.zip pygame/ 文件 34, 其中 .dll 0 -> []
   beta6.zip pygame/ 文件 49, 其中 .dll 15 -> ['SDL2.dll','SDL2_image.dll',…]
   ```

8. 影响与等级：断言**不是死代码**，且与 3.13 + Nuitka 4.3.5 真机产物一致；beta5 的 0-DLL 包是它的现实依据（这也回答"② 是否一致"：一致）。

---

### P-13 · §9.5 要求 dev/release 两档，已提交文档只有 disable 一档 **[P-PROVED / P2 · 疑似在途已覆盖]**

**反手（证伪：dev 档在已提交材料里有落点）**

1. 判定基准：版本计划 L226-234 §9.5"内部开发：编「带控制台」版本（--windows-console-mode=force）… 发布：disable … 两条命令落成工具 tools/build_engine.py --mode dev|release，不靠记忆"。
2. 代码证据（已提交树）：`git grep "console-mode=force" HEAD` 只命中"版本计划 L230（裁决文字）"与历史台账；`git grep "'nuitka'" HEAD -- '*.py'` 只命中 Loom/build_game.py:135（玩家运行时，恒 disable）。Loom/build_entry.py 内**没有任何 nuitka 调用**（只有 L19/L219 两句注释）。
3. 路径枚举（拿到"带控制台编辑器"的三条可能途径）：a. tools/build_engine.py（**未跟踪**，在途）→ 已提交树不存在；b. 指南 §7.5 手抄命令 → 只有 disable；c. Loom/build_entry.py → 无编译入口。→ 已提交状态下**没有**可达路径。
4. 实际行为：已提交树只有 release 档命令。
5. 差异：裁决要求"两条命令落成工具、不靠记忆"，已提交状态是"零条命令落成工具 + 一条手抄 release 命令"。
6. 触发条件：内部开发需要看 stdout / 异常栈时（§9.5 明确说这是为了避免静默失败）。
7. 验证：

   ```
   $ git grep -n "console-mode=force" HEAD -- ':!archive'
   HEAD:Loom/bench_result_对比台账.txt:41: … --windows-console-mode=force
   HEAD:docs/design/版本计划_Loom0.1.0.beta6_20261109.md:230: - **内部开发：编「带控制台」版本**（--windows-console-mode=force）…
   $ git grep -n "'nuitka'" HEAD -- '*.py'
   HEAD:Loom/build_game.py:135: cmd = [sys.executable, '-m', 'nuitka', '--mode=standalone', …
   ```

8. 影响与等级：**P2**（口径落盘不完整）。**疑似在途已覆盖**：工作区未跟踪的 `tools/build_engine.py` 与 使用操作指南.txt 工作区版已出现 dev/release 两档说明——按任务约束不据此下结论，只登记。

---

## ④ 统计

| 判定 | 数量 | 编号 |
|---|---|---|
| P-PROVED | 8 | P-01, P-02, P-03, P-06, P-07, P-08, P-09, P-13 |
| P-DISPROVED | 3 | P-05, P-11, P-12 |
| P-UNKNOWN | 2 | P-04, P-10 |
| P-CONTRADICTION | 0 | — |

**P-CONTRADICTION = 0 的原因**：13 项里没有出现"证伪链声称覆盖全部路径且无 bug"与"证真链给出反例"同时成立的情形——凡证伪成功的项（P-05 / P-11 / P-12），正手都确实构造不出反例（分别是：无合法产物带根 SDL2、缺 assets 不崩、断言与产物逐项吻合）；凡证伪失败的项，都明确留下了"无法枚举的路径"（P-04 的 pygame 2.5.x、P-10 的 ACL、P-01 的路径 d）。

**P-UNKNOWN ≠ 0**：符合方法论第 9.4 节对"结构性放水"的告警要求——两项都写明"还缺什么信息才能定"。

严重度分布：**P1 × 2**（P-01, P-02）；**P2 × 5**（P-03, P-04, P-06, P-07, P-13）；**P3 × 6**（P-05, P-08, P-09, P-10, P-11, P-12）。

---

## ⑤ 修复建议排序（只给方向，不含代码）

**P1（发货前必须定）**

1. **P-01**：把"包内 python/ 优先"提升为硬前置——`default_python(engine_dir)` 命中嵌入式时**不再**被 python_version 覆盖；并把 `interp_python_note` 的"回退"提示条件限定为"既无嵌入式、也无匹配系统解释器"（否则自足包误报）。
2. **P-02**：源码打包器的嵌入式运行时与 解释器.json 的 python_version 必须**同源**。两条可选路线（需人类选，见 §6）：① 打包器按元数据版本解析解释器（3.13.15 → 3.13 安装）+ 探测真实版本回写；② 元数据 python_version 改为"打包时探测到的真实嵌入版本"，README 同步。任一路线都要顺手修 L5 / L183-184 / L204 三处写死的 "3.12"。

**P2（本轮收尾尽量做）**

3. **P-07**：指南 §7.5 命令补 `--output-filename=Loom.exe`（并建议补 `--output-dir`，使其与回滚说明引用的 C:\loom_build\engine 路径自洽）。
4. **P-06**：编译包不要复用源码包的 `write_launcher / write_meta_readme`；应生成"启动 Loom.exe"的 bat 与"编译版目录结构"的 README（并去掉"嵌入式 Python 3.12"字样）。
5. **P-03**：断言从"存在性"升级为"存在性 + 最小内容判据"（qwindows.dll 大小 > 0、PySide6/QtWidgets.pyd 存在，或对 dist 做一次 `Loom.exe --version` 冒烟）。
6. **P-13**：把 dev/release 两档命令落成**受跟踪**脚本，并在指南里用脚本调用替换手抄命令（在途的 tools/build_engine.py 需转正）。
7. **P-04**：`PYGAME_MIN_DLLS` 改成点名必需 DLL 集合，阈值只作辅助。

**P3（记入待办）**

8. **P-05**：判据收紧为"根有 SDL2 **且** pygame/ 无 SDL2"。
9. **P-08**：`cmd_launch_engine` 的 out 带上 python_note（或删 L497），使 GUI/命令两入口同构。
10. **P-09**：python_version 从产物推导（dist 根 python3XX.dll / build_info.json），不取 sys.version_info。
11. **P-10**：给 `os.listdir` 包 try → 变成一条 problem 字符串。
12. **P-11**：如决定源码包也带示例资产，在打包器加显式白名单（与 P-05-18"黑名单式收集"同源）。

---

## ⑥ 需要人类裁决的封闭问题

**Q1（P-02 路线）**：源码发布包（package_engine.py 产出）的嵌入式 Python 应该是哪一个？

- A. 跟随主线 3.13.15（打包器解析 3.13 安装并探测真实版本回写）；代价：需要一台稳定的 3.13 打包机 + 依赖快照。
- B. 继续 3.12.10（回滚环境），并把 解释器.json 的 python_version 改成"包内真实 3.12.10"；代价：元数据与主线声明分叉，Hub 提示"要求 3.12"。
- C. 源码包不再内置 python/（改为"需要本机 Python 3.13"）；代价：失去"开箱即用"，与 hub_config.py:644 契约冲突。

**Q2（P-01 口径）**：Hub 启动**自带 python/ 的源码包**时，是否允许用系统解释器顶替包内运行时？

- A. 永不允许（包内优先；只有没有包内运行时才按 python_version 解析）；代价：包内运行时坏了只能靠用户重装包。
- B. 允许，但"顶替发生"时必须提示（note 非空）；代价：自足包在开发机上每次启动都有提示噪音。
- C. 维持现状（静默顶替）；代价：= P-01 现状。

**Q3（P-06/P-13 交付形态）**：beta6 收尾时，编译包是否必须做到"双击 Loom.bat 就能启动"？

- A. 必须（改 write_launcher/README 为编译版语义）；代价：多一处打包路径维护。
- B. 不必须（README 明说"直接双击 Loom/Loom.exe"）；代价：与 Unity 类"一键启动"体验有差距，但改动最小。
- C. 本版先删掉 Loom.bat 与 README（避免误导）；代价：包内无使用说明。

---

## 附：审计足迹自查

- 只读遵守：未修改任何受跟踪文件；未执行 git add / commit / checkout / stash。
- 探针文件（全部在 Loom/tests/_tmp/，非受跟踪）：`audit_b6_03_pkg_head.py`（HEAD 版 package_engine 快照）、`audit_b6_03_pkgc_head.py`（HEAD 版 compiled 快照）、`audit_b6_03_probe_asserts.py`、`audit_b6_03_probe_head_asserts.py`、`audit_b6_03_probe_bypass.py`、`audit_b6_03_probe_neg.py`、`audit_b6_03_probe_embedded.py`、`audit_b6_03_probe_meta.py`、`audit_b6_03_probe_zip.py`、`audit_b6_03_probe_zip2.py`、`audit_b6_03_probe_readme.py`、`audit_b6_03_probe_assets.py`、`audit_b6_03_guide_head.txt`、`audit_b6_03_prev_audit.txt`。
- `git status --porcelain` 收尾 vs 开工：开工 6 项在途 + 2 项未跟踪；收尾多出 `M Loom/tests/test_ab_gl_vk.py` 与未跟踪 `docs/audit/scan_beta6_round_02_...md`。**这两项来自并行兄弟子代理（编号 02 的 ab_gl_vk 审计），本代理从未写该路径**（本代理全部写入 = `Loom/tests/_tmp/audit_b6_03_*` + 本报告）。除此外与开工一致。
- 未启动任何 GUI 长期窗口（仅命令行探针；未打开编辑器/播放器窗口）。
