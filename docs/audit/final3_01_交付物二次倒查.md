# 倒查 01 · 交付物二次倒查（第十二轮，未参与实现）

- 基线：HEAD `956502e5d611ffc73a00784e82445ee7c5a1c67d`（commit time 2026-11-11 01:40:20），`git status --porcelain` = **0 行**（干净）
- 时间：2026-11-11 01:41~02:05；**所有数字均为本次实测复跑，未引用任何既有报告**
- 只读边界：仓库仅新增本报告 + 3 个 `Loom/tests/_tmp/final3_01_*.py` 探针（该目录被 `Loom/.gitignore:22` 忽略）；包展开/构建/Hub 安装全部在仓库外 `C:\loom_build\final3_01_*`、`f3_*`
- 交付物：`Loom-0.1.0.beta6-source.zip` 365,518,830 B / 7,206 条目；`Loom-0.1.0.beta6-compiled.zip` 139,043,702 B / 537 条目

## 1. 包 vs HEAD 双向对拍（自己复跑）

```
py -3.13 tools/verify_pkg_vs_head.py tools/dist/Loom-0.1.0.beta6-source.zip ^
        tools/dist/Loom-0.1.0.beta6-compiled.zip --json C:\loom_build\final3_01_verify.json
-> exit code 0（实测 $LASTEXITCODE=0）

[source]  包内引擎 .py=93 / HEAD=93，内容不一致=0，包多出=0，包缺失=0
  key sceneio.py / agent_commands.py / loom_post.py / loom_assets.py -> 4xOK（EOL 归一后同哈希）
[source]  meta=0.1.0.beta6 nested=0.1.0.beta6 target=0.1.0.beta6 -> OK
[compiled] meta=0.1.0.beta6 nested=0.1.0.beta6  mode=release  built_at=2026-11-11 01:24:06
[compiled] git_head=153c78963598 / head=956502e5d611 / dirty=False -> OK（引擎等价）
[compiled] smoke_passed_at=2026-11-11 01:37:09  built_at=2026-11-11 01:24:06
```

| 判据 | 要求 | 实测 | 判定 |
|---|---|---|---|
| 双向文件数 | 93/93 且集合相等 | 93 / 93，多 0、缺 0 | 达成 |
| 内容不一致 | 0 | 0 | 达成 |
| meta | 顶层/嵌套 == 0.1.0.beta6 | 两者一致，python 3.13.15 | 达成 |
| git_head | == HEAD | `153c7896` != `956502e5`，但引擎等价 | **部分**（见下） |
| git_dirty | false | false（JSON 布尔） | 达成 |
| 门序 | smoke > built | 01:37:09 > 01:24:06（13 分 3 秒） | 达成 |

**逐字节 `==` 不成立的量化**（反向核对）：`git diff --name-only 153c7896 956502e5` 只有 1 个文件
`docs/handoff/接手须知_beta6当前状态_20261111.md`；加 `-- Loom/` 过滤后 **0 个文件**（`git diff --name-only ... -- Loom/ | Measure-Object -Line` = 0）。
=> 包内引擎与最新 HEAD **逐字节同一**，但包内 `build_info.git_head` 记录的是上一个纯文档提交。
若人类要求「包里写的就是 HEAD」，需在下一个提交后重打（纯文档提交重打包即可，不涉及重新编译）。

## 2. 构建器 P0 是否真的修好（本轮核心）

**(a) 包内目录（ckernels 同级）跑 `--help`**

```
C:\loom_build\final3_01_dist\Loom> build_game.exe --help   （同目录 ckernels\loom_kernels.dll 存在）
EXIT=0   ELAPSED=2.0s
usage: build_game.exe [-h] [--name NAME] [--company COMPANY] [--version VERSION] ...
  --protection {secure,open} / --no-encrypt-content ...
```

**(b) 复制到空目录（无 ckernels）跑一次 —— 要求「说人话」而非裸崩**

```
C:\loom_build\f3_empty> build_game.exe --help      （目录内只有 exe 一个文件）
EXIT=1   ELAPSED=1.9s
RuntimeError: ckernels 官方组件加载失败: loom_kernels.dll 未找到。
  搜索目录 (按优先级): ['C:\loom_build\f3_empty', 'C:\Users\...\Temp\onefile_249112_...']
  尝试路径          : [f3_empty\ckernels\loom_kernels.dll, f3_empty\loom_kernels.dll,
                       onefile_xxx\ckernels\loom_kernels.dll, onefile_xxx\loom_kernels.dll]
  线索: onefile/Nuitka 下 sys.executable 可能指向临时解包目录; 可用 LOOM_CKERNELS_DIR 指定...
```
=> 有「搜索目录 / 尝试路径 / 自救线索」，**不是裸崩**（traceback 尾帧就是该 RuntimeError）。判定 **达成**。

**(c) 追加的 6 组反例（原任务未要求，用于证伪「只在包内目录才对」）**

| 场景 | 结果 |
|---|---|
| cwd = 包的上级 `C:\loom_build\final3_01_dist`，exe 用相对路径 `Loom\build_game.exe` | EXIT=0，打印 usage |
| cwd = `C:\Users\Administrator` | EXIT=0 |
| cwd = `C:\Windows\Temp` | EXIT=0 |
| 空目录 + `LOOM_CKERNELS_DIR=<包>\ckernels\loom_kernels.dll` | EXIT=0 |
| **真出一次包**：`--name F3Probe --scene examples\PacMan2D.json --runtime <包>\player_runtime\game_player.dist --force` | **EXIT=0，2.3s**，产出 `MyGame.exe` 35,334,144 B + `游戏包.lsc` 24,351 B |
| smoke `[6/7]`（cwd 继承=仓库根，非包目录） | PASS，exit=0 |

=> P0 是**真修**，不是「冒烟盖章」。源码侧对应修复在 `Loom/fastpath.py:60-114`：搜索目录改成 5 级
（`LOOM_CKERNELS_DIR -> __compiled__.containing_dir -> argv[0] 目录 -> sys.executable 目录 -> 模块目录`），
包内 `Loom/ckernels/` 随包发布（`loom_kernels.dll` 22,016 B），所以「cwd 无关」成立。
诊断文本在 `fastpath.py:155-162`，含「搜索目录 (按优先级)」「尝试路径」「线索」。

## 3. 包内残渣（直接读 zip 条目，不展开）

```
py -3.13 Loom/tests/_tmp/final3_01_zip_hygiene.py <source.zip> <compiled.zip>
== source.zip ==    entries=7206
   HARD agent_port 0 / editor_state 0 / 崩溃日志 0 / *.log 0 / tests/_tmp 0   -> 全 OK
   soft __pycache__ 844（全部在 python/Lib/site-packages/ 下；cpython-313 838、cpython-312 4、cpython-314 2）
   soft *.bak 2（Loom/core_components/physics/loom_physics.c.bak 及其 player_runtime 副本）
== compiled.zip ==  entries=537
   HARD 同上 5 项全 0；__pycache__ 0；*.bak 2
   top-level = ['Loom', 'Loom.bat', 'README.txt']
VERDICT: CLEAN (hard_hits=0)   exit 0
```
补充：源码包内 `Loom/tests/` = 0 条、`Loom/tests/_tmp/` = 0 条。

代码侧不是「碰巧干净」：`tools/package_engine.py:29-32,204-223` 有 `packaging_excluded()`（状态文件/日志/`崩溃日志/`/`tests/_tmp`），
`package_engine.py:650-660` 在出包后**自检 zip 条目，命中即 `_fail`**（硬闸，不是告警）。判定 **达成**。

## 4. 冒烟 7 项（对包内引擎）

```
py -3.13 tools/smoke.py --dist C:\loom_build\final3_01_dist\Loom ^
        --builder-exe C:\loom_build\final3_01_dist\Loom\build_game.exe
SMOKE PASS [1/7] 能启动（pid=248028）
SMOKE PASS [2/7] 场景已加载（models=126）
SMOKE PASS [3/7] 能播放 2.5s
SMOKE PASS [4/7] 有读数（fps=199.0 tps=30.47）
SMOKE PASS [5/7] 产物元数据自洽（解释器.json / build_info.json）
SMOKE PASS [6/7] 构建器可执行（build_game.exe, exit=0）
SMOKE PASS [7/7] 运行时最小启动（game_player.dist, exit=1）
SMOKE OK  用时 8.5s（预算 60s）        exit 0
```
7/7 PASS、8.5s < 60s、exit 0。`[7/7] exit=1` 是设计内预期（无 `游戏包.lsc` -> 能起但不进游戏，`check_runtime` 接受 0/1）。判定 **达成**。
（本次未加 `--stamp`，故未改动任何 `build_info.json`。）

## 5. Hub 0.1.4

| 判据 | 实测 | 判定 |
|---|---|---|
| 安装包存在 | `tools/dist/LoomHub-0.1.4-Setup.exe` 27,288,908 B，mtime 2026-11-11 00:05:15 | 达成 |
| 版本链① `LoomHub/版本.json` | `0.1.4` | 达成 |
| 版本链② `tools/installer.iss` | `#define MyAppVersion "0.1.4"` | 达成 |
| 版本链③ `Loom/tests/test_release_version.py` | `EXPECT_HUB = '0.1.4'` | 达成 |
| 版本测试 | `test_release_version.py` -> **ALL PASS**（35 项 PASS，含包名/iss/env 分叉拒绝） | 达成 |
| exe 版本资源 | `ProductVersion=0.1.4`、`FileDescription=LoomHub Setup` | 达成 |
| 源码是否比安装包新 | `git log --since="2026-11-11 00:05:00" -- LoomHub tools/installer.iss tools/package_hub.py` -> **空** | 达成 |
| 真载荷（静默安装） | `/VERYSILENT` -> exit 0；装出 `LoomHub.exe` 7,312,140 B、`_internal` 1,101 文件 | 达成 |
| 三处补丁是否真进包 | `final3_01_hub_patch_verify.py` -> **PATCHES_PRESENT (8/8)**：`hub_config` 的 `saved_install_root / user_install_root / scan_install_root(s) / root_writable`、常量 `install_root`；`hub_install` 的 `PermissionError / winerror` | 达成 |

（首轮我按「字符串常量」找 `saved_install_root` 误判 MISSING，用 `final3_01_hub_patch_diag.py` 导出符号表后确认它是**函数名**——已修正探针，避免假阴。）

## 6. 发布前还差什么（按严重度）

| 级别 | 缺口 | 证据 |
|---|---|---|
| **P1（发布闸，非交付缺陷）** | 语义面 **11.5 > 目标 8** 未裁决，beta6 仍被人类定为「中间版本、不发布」 | `docs/handoff/接手须知_beta6当前状态_20261111.md` §1/§9；包内 `解释器.json` 已是 beta6，但发布口径未开 |
| **P2** | 发布说明缺 2 篇：`tools/release_notes/` 只有 engine-beta4/beta5、hub-0.1.2/0.1.3；无 `engine-0.1.0.beta6.md` / `hub-0.1.4.md` | 目录实读；`release_github.py:402-408` 缺失即退回通用条目 |
| **P2** | tag 缺 `engine-v0.1.0.beta6` / `hub-v0.1.4`（现有 9 个 tag，最新 beta5 / hub-0.1.3） | `git tag` |
| **P3** | 包内 `git_head=153c7896` 落后 HEAD 一个纯文档提交 | §1（引擎零 diff） |
| **P3** | 上传未做：`release_github` 从未对远端写入（前置检查缺资产即零写退出，已测） | 无远端 release |
| **P3** | 软残渣：源码包 `python/Lib/site-packages/**/__pycache__` 844 条（含 4 个 cpython-312、2 个 cpython-314 混档）；两包各 2 个 `loom_physics.c.bak`（本机未跟踪产物） | §3；不影响功能，仅体积/洁癖 |
| **P3** | 装出的 `LoomHub.exe` 无 FileVersion/ProductVersion 资源（Setup exe 有 0.1.4） | §5；版本真源仍靠 `版本.json` |

## 7. 统计

| 项 | 结果 |
|---|---|
| 必做 6 项 | 6/6 达成（§5 为「存在 + 三处一致 + 载荷实证」） |
| 复跑命令数 / 探针数 | 7 条命令 / 3 个探针 |
| 反向验证组数 | 6 组（空目录、2 个异 cwd、env 覆盖、真出包、smoke 继承 cwd），全部按预期 |
| 引入问题 | 0（写本报告前 `git status` 仍为 0 行；未改任何源码/包） |
| 新增未跟踪文件 | 本报告 + 3 探针（探针已被 `Loom/.gitignore:22` 忽略） |

## 8. 待裁决

1. `git_head` 严格等于 HEAD 是否作为发布硬判据？（现状：引擎等价、文档落后一提交）
2. 语义面 11.5 > 8 是「未达成记录」还是「按 §9.29 重新定义提案接受」——直接决定 beta6 能不能进发布流程。
3. 软残渣（site-packages `__pycache__`、`*.c.bak`）是否要一并清出包。
