# 倒查 03：文档 / 版本 / 打包一致性复核

- 倒查时间：2026-11-10 20:45–20:55
- 基线：HEAD = `ee83e4b`（`git log --oneline -1`），`git status --porcelain` 空
- 执行解释器：系统 Python 3.12.10（发布链用 3.13.15；本文所有计数为源码级，与解释器版本无关）
- 只读声明：本报告未改任何源码；探针只写 `Loom/tests/_tmp/verify_03_*.py`，夹具全部建在 `%TEMP%`
- 报告文件名说明：任务给定的 `verify_03_文档/版本/打包一致性复核.md` 含斜杠（Windows 非法），落盘时以 `_` 替代，内容范围不变。

范围：五份顶层文档（`README.md` / `代码架构.txt` / `使用操作指南.txt` / `开发进度与Unity对照.txt` / `docs/design/架构互联协议总表.md`）、`Loom/sceneio.py`、`Loom/build_entry.py`、`Loom/run_player.py`、`tools/package_engine*.py`、`tools/build_engine.py`。

---

## 0. 判定总表

| 项 | 宣称 | 实测 | 判定 |
|---|---|---|---|
| ① 12 个能力名可查 | 五份文档逐份 grep 无缺失，每项给实现位置与用法 | 12×5 全命中（0 空），但“实现位置+用法”只有 README 与附录 F 给全 | **部分达成** |
| ② EAI 命令数 102 | 数字纠错为 102 | `command_names()` = **103**；102 是 0f060bf 时点的快照 | **不实** |
| ③ SCENE_VERSION 11 | 代码与文档一致 | 代码 = 11，五份文档 5 处提及全为 11 | **达成** |
| ④ env 附录覆盖 | 41 个运行时 env 41/41 全覆盖 | 41 条运行时条目确实都存在；但“全量清单”漏 4 个（含 1 个运行时） | **部分不实** |
| ⑤ 打包断言真的会失败 | 负向 6 例全 exit 1 | 断言 20/20 负例全部触发；但**发版产物与 HEAD 不一致** | 断言**达成**，交付**不达成** |
| ⑥ 版本闸覆盖入口 | --run/--open/编辑器/VK/GL/远程回读 | 10 个在册入口 10/10 有闸，其中 2 个真实子进程实测 rc=1 | **达成**（--bench 属例外，见 §6.2） |

---

## 1. 验证项 ①：12 个能力名在五份文档是否真的可查

命令（`Select-String -SimpleMatch`，大小写不敏感，统计行数）：

```
frame_plan/loom_pass/bloom/tonemap/LOOM_POST/assets.json/loom_assets/
asset_import/min_engine_version/bucket_pack/AVX2/_pose_rows × 五份文档
```

实测矩阵（每格为非零命中行数）：

| 名字 | README | 代码架构 | 使用操作指南 | 开发进度 | 协议总表 |
|---|---|---|---|---|---|
| frame_plan | 1 | 1 | 1 | 2 | 1 |
| loom_pass | 4 | 4 | 4 | 5 | 4 |
| bloom | 1 | 1 | 5 | 2 | 1 |
| tonemap | 1 | 1 | 2 | 2 | 1 |
| LOOM_POST | 4 | 3 | 5 | 3 | 3 |
| assets.json | 1 | 1 | 1 | 2 | 5 |
| loom_assets | 2 | 2 | 2 | 3 | 4 |
| asset_import | 2 | 2 | 2 | 3 | 2 |
| min_engine_version | 1 | 1 | 1 | 2 | 4 |
| bucket_pack | 1 | 1 | 2 | 2 | 1 |
| AVX2 | 1 | 1 | 1 | 2 | 1 |
| _pose_rows | 1 | 1 | 2 | 2 | 1 |

结论：60/60 格非空，**不存在缺失项**。宣称里更强的那半句“每项给实现位置与用法”，只在两处成立：
- `README.md:128-139`（12 行表：能力名 / 实现文件 / 用法）
- `使用操作指南.txt:719-732`（附录 F，同结构，另给自检命令）
另外三份文档（`代码架构.txt` / `开发进度与Unity对照.txt` / `架构互联协议总表.md`）是上下文提及，不含“在哪儿/怎么用”逐项说明。**按“可查”算达成，按“每项给位置与用法”算部分达成。**

---

## 2. 验证项 ②：EAI 命令数是否真是 102

**不实。实测 103。**

```
> cd Loom; python -c "import agent_commands as ac; print(len(ac.command_names()))"
COUNT= 103
相较文档时点新增：asset_user_override（agent_commands.py 的 cmd_asset_user_override）
```

历史与原因（`git` 取证）：

```
> git show 0f060bf:Loom/agent_commands.py  -> @command 装饰器 102
> HEAD:Loom/agent_commands.py             -> @command 装饰器 103
> git log -S 'asset_user_override' --oneline -- Loom/agent_commands.py
80ee837 perf/fix(assets)!: 索引 10k 8190ms->54.6ms + delta 覆盖真正生效 ...
> git log -4 --format='%h %ad %s' --date=format:'%m-%d %H:%M'
ee83e4b 11-10 20:42 ...
5ebd57b 11-10 20:42 ...
80ee837 11-10 20:36 ...   <- 新增命令
6e9e315 11-10 20:33 ...
0f060bf 11-10 20:30 docs(governance): ... 数字纠错 19 处：EAI 102 ...
```

即：文档纠错提交（20:30）之后 6 分钟，资产批又加了一条命令（`asset_user_override`，F-02 的用户层 delta 唯一写入口），文档没跟着改。

仍写 102 的文档行（共 8 处）：

| 文件:行 | 原文片段 |
|---|---|
| 代码架构.txt:1710 | “实测口径：EAI 命令 102 条 / HUB-EAI 21 条 / SCENE_VERSION = 11 / 测试文件 133 个。” |
| 使用操作指南.txt:475 | “… 共 102 条命令,” |
| 使用操作指南.txt:735 | `print(len(ac.command_names()))` -> 102 |
| 开发进度与Unity对照.txt:26 | “(102/21 条命令, 测试全绿)” |
| 开发进度与Unity对照.txt:285 | “agent_commands.py 102 条命令” |
| 架构互联协议总表.md:3 | “EAI 102 / MCP 72 Tools…” |
| 架构互联协议总表.md:220 | “102 个 cmd 方法” |
| 架构互联协议总表.md:235 / :419 | “EAI 命令分类（102 个…” / 自检表 “EAI 命令 | 102” |

**最硬的一条**：`使用操作指南.txt:735` 与 `架构互联协议总表.md:419` 都给了可复跑自检命令，任何人照着跑都会拿到 103 —— 文档自带的验证命令与文档数字互相矛盾。

同批准的其它数字（顺带复核，全部成立）：

```
HUB-EAI: hub_commands.command_names() = 21
测试文件: Loom/tests/test_*.py = 133
SCENE_VERSION: 11
```

---

## 3. 验证项 ③：SCENE_VERSION 是否 11 且文档一致

**达成。**

```
> cd Loom; python -c "import sceneio; print(sceneio.SCENE_VERSION)"
11
> Loom/sceneio.py:58  SCENE_VERSION = 11  # v11 (beta6 B1 资产 guid) ...
```

文档 5 处提及，全为 11：
`代码架构.txt:704`、`代码架构.txt:1710`、`使用操作指南.txt:736`、`架构互联协议总表.md:365`、`架构互联协议总表.md:421`。

---

## 4. 验证项 ④：env 附录是否覆盖代码里全部 env

探针：`Loom/tests/_tmp/verify_03_env.py`、`verify_03_env2.py`、`verify_03_envcount.py`
（正则覆盖 `environ.get('X')` / `environ['X']` / `getenv('X')` / `_env_float|int|bool|str('X')`；排除 tests/archive/dist/_stage）

**附录 E 结构实测**（`使用操作指南.txt:646-712`）：具体条目 47 条 = 运行模式/路径 10 + 渲染/后处理 10 + 物理/并行 21（= 宣称的 41 个运行时）+ 构建/发布 5 + 契约族名 1。

**代码侧**：字面量 env 读取点 45 个，另有 3 个经变量名读取（`LOOM_AUDIO_BACKEND` @ `audio_backend.py:72` 的 `_MODE_ENV`；`LOOM_ENGINE_VERSION`/`LOOM_HUB_VERSION` @ `release_github.py:48` 的 `env_name`）。

**附录漏收（代码真实读取、附录无条目）4 个**：

| env | 代码读取点 | 性质 | 附录位置 |
|---|---|---|---|
| **LOOM_POST_EXPOSURE** | `Loom/loom_post.py:71`（`_env_float('LOOM_POST_EXPOSURE', ...)`） | **运行时开关**，与已收录的 `LOOM_BLOOM_KNEE/STRENGTH/THRESHOLD`（:68-70）同文件同函数 | 缺 |
| LOOM_BUILD_ROOT | `tools/build_engine.py:31` | 构建路径 | 缺（§四 构建/发布 只列 5 条） |
| LOOM_PYEMBED_CACHE | `tools/package_engine.py:205` | 打包缓存路径 | 缺 |
| LOOM_PYEMBED_DIR | `tools/package_engine.py:259` | 嵌入式 Python 来源 | 缺 |

**附录多收（代码侧只在测试里读）2 个**：`LOOM_AB_SCENES`、`LOOM_AB_ALLOW_NO_VK`（非测试代码 grep 0 命中，仅 `Loom/tests/test_ab_gl_vk.py` 等使用）——写在 §三“物理/并行/计算”里，属于口径混入。

结论：宣称的“41 个运行时 env 41/41 覆盖”在这 41 条口径内**成立**；但标题写的是“环境变量**全量**清单”，且明确包含构建段，因此 **漏 1 个运行时 env（LOOM_POST_EXPOSURE）+ 3 个构建 env** 是实打实的缺口，尤其 LOOM_POST_EXPOSURE 与已收录的三兄弟同函数，属明显疏漏。

---

## 5. 验证项 ⑤：打包断言是否真的会失败

### 5.1 断言本身：20/20 负例全部触发（PASS）

探针 `Loom/tests/_tmp/verify_03_pkg.py`（结果 `RESULT: 20/20 PASS`）：

| 用例 | 断言点 | 实测 |
|---|---|---|
| M1/M2/M3 | `meta_version_problems` `package_engine.py:113` | 缺文件/版本不符均报错；相符放行 |
| B0–B6 | `build_info_problems` `package_engine.py:132` | mode=dev、python=3.13、nuitka=abc、built_at=x、缺文件、缺 nuitka 字段 —— 全部报错；release 合法产物放行 |
| Z0–Z5 | `_verify_zip` `package_engine.py:559` | 全一致通过；顶层 meta 不符、**嵌套运行时版本不符**、包名不符、精简标记不符、正式包缺 exe —— 全部 `SystemExit` 且**删坏包** |
| P1/P2 | `make_zip` `package_engine.py:423` | `--version` 与源码 meta 不符 -> SystemExit，且 dist 未产生任何 zip |
| A1/A2 | `build_engine._assert_meta` `build_engine.py:126` | dist meta 与源码不符 -> SystemExit(1) |

关键输出（节选，乱码为控制台 GBK，内容正确）：

```
PASS Z2 嵌套运行时版本不符 -> 失败并删包
  [错误] 发版自检未通过（已删除坏包）: 1 项 -> ["嵌套运行时元数据版本 '0.1.0.beta5' != 目标 '0.1.0.beta6'"]
PASS P2 拒绝时未创建任何 zip
```

端到端复核（真实 CLI，非函数级）：

```
> python tools/package_engine.py --version 0.1.0.beta9
[错误] 源码元数据版本与目标版本不符，拒绝出包: 解释器.json version='0.1.0.beta6' != 发布版本 '0.1.0.beta9'
EXITCODE=1      # tools/dist 前后文件列表一致，未产出任何新 zip
```

一处防御深度不对称（非缺陷）：源码包 zip 回读含嵌套校验（`package_engine.py:595-605`），编译包 zip 回读只验顶层 `解释器.json`（`package_engine_compiled.py:222-232`），嵌套一致性依赖拷包前的目录校验（:118-129）。

### 5.2 交付物一致性：**不成立（P1）**

`tools/dist` 里两个 beta6 产物的时间点都早于最后 4 个提交：

| 产物 | mtime | 包内 meta.version | 包内命令数 | 与 HEAD 哈希不同的文件 |
|---|---|---|---|---|
| Loom-0.1.0.beta6-source.zip（348.5 MB） | 2026-11-10 **20:22** | 0.1.0.beta6 | **102**（HEAD 103） | **11** |
| Loom-0.1.0.beta6-compiled.zip（130.1 MB） | 2026-11-10 **14:40** | 0.1.0.beta6 | 无源码 | — |

`git log`：`6e9e315 20:33`（VK 迁入 FramePlan）、`80ee837 20:36`（资产 P1）、`5ebd57b 20:42`（动画门禁/回退名单）、`ee83e4b 20:42` 均晚于 20:22。

逐文件哈希比对（`verify_03_zipdiff.py`，范围 `Loom/**/*.py|json|dll`，排除 tests/dist/player_runtime）：

```
一致=107  不一致=11  包内缺=16(仅 Projects/ 压测样例, 符合 EXCLUDE_DIRS 设计)
DIFF Loom/agent_commands.py   DIFF Loom/editor.py        DIFF Loom/loom_assets.py
DIFF Loom/loom_pass.py        DIFF Loom/loom_pass_gl.py  DIFF Loom/loom_post.py
DIFF Loom/loom_post_gl.py     DIFF Loom/sceneio.py       DIFF Loom/vk_renderer.py
DIFF Loom/解释器.json(仅格式重排, 字段无差异)  DIFF Loom/editor_state.json
```

也就是说：发布包里的 sceneio.py / editor.py 缺的是 **80ee837 的资产整批**（不是版本闸文案）。

内容级 diff（`verify_03_zipdiff2.py`，unified diff 计数）证明不是格式噪声：

```
Loom/loom_post.py       zip=64 行  HEAD=72 行   +14/-6  <- 缺 stage 0..3 语义 + _env_float 拒 nan/inf（6e9e315）
Loom/agent_commands.py  zip=3973      HEAD=4027   +55/-1  <- 缺 asset_user_override / user_delta / effective_import（80ee837）
Loom/sceneio.py         zip=2200      HEAD=2241   +54/-13 <- 缺 ASSET_ERROR_LIMIT / reset_asset_errors / user delta 辅助（80ee837）
Loom/editor.py          zip=2884      HEAD=2887   +8/-5   <- 缺「未保存场景不得建库」的空根写保护（80ee837）
Loom/loom_assets.py     zip=969       HEAD=1044   +92/-17 <- 缺 delta 生效与错误记录 O(1)（80ee837）
```

（注：`sceneio.parse_version` 的分隔符归一**包内已存在**，逐字符一致，不计入差异。）

即：发布包缺 6e9e315 的后处理/计划段与 80ee837 的整批资产修复。而 `使用操作指南.txt:449` 自己写着“源码包重建（发布前必做；…改动代码后必须重打）”。按这条规则，当前 dist 是过期产物；`release_github.py` 取包（优先 compiled，其次 source），用户拿到的 beta6 不是 20:42 的 HEAD。

这一条对“文档/版本/打包一致性”是硬伤：文档与代码自洽，但**发布物与代码不自洽**。

---

## 6. 验证项 ⑥：版本闸入口覆盖矩阵

### 6.1 矩阵（10 个在册入口，10/10 有闸）

| # | 入口 | 加载路径 | 闸门位置 | 失败呈现 | 证据 |
|---|---|---|---|---|---|
| 1 | `Loom.exe --run` / `python Loom/build_entry.py --run` | build_entry -> PlayerApp | `sceneio.py:1991`（scene_from_dict）→ 异常在 `build_entry.py:437-444` 捕获 | 弹窗/打印 + `SystemExit(1)` | **实测** rc=1 / 1.3s / 含 99.0.0 / 无 Traceback |
| 2 | `--open`（Qt 编辑器打开项目） | `build_entry.py:424-425` → `ui/loom_gui.py:198` → EditorApp | `editor.py:1235-1239`（`_load_scene` 内，清空旧场景**之前**） | notify 红字“加载失败: …”，保留当前场景 | 静态（避免起 GUI 窗口） |
| 3 | 旧 `游戏配置.json` 直连 PlayerApp | build_entry 内同上 | 同 #1 | 同 #1 | 静态（同一 except 分支 `build_entry.py:439`） |
| 4 | `Loom.py --run` | `Loom.py:449` → `_launch_player`(`:189-214`) → `run_player.run_backend` | `run_player.py:404-410` | `handle_scene_version_error`(`:295-298`)：打印+弹窗+`SystemExit(1)` | **实测**（走 #5 路径）rc=1 |
| 5 | 远程回读（`LOOM_REMOTE_MODE=on`） | `loom_player_window.py:149-161` | 同 #1 抛错 → `_scene_version_fatal`(`:77-89`) | 报道 + 关窗 + `_exit_now(1)`（`os._exit` 前显式 flush） | **实测** rc=1 / 1.9s / 无白窗残留 |
| 6 | VK 后端 | `scene_driver.py:611-616` | 显式 `check_engine_version`（原缺口，beta6 补） | 抛 `SceneVersionError`，由 run_player/game_player 统一 | 静态 |
| 7 | GL 后端 | runtime.PlayerApp → `sceneio.py:1897` scene_from_dict | `sceneio.py:1991` | 同 #1/#4 | 静态 |
| 8 | 打包游戏 `MyGame.exe` | `game_player.py:193-241` → `run_player.run_backend` | `run_player.py:404-410` | 同 #4 | 静态 |
| 9 | 编辑器放 Prefab | `editor.py:1445-1450` `load_prefab` | `sceneio.py:2211/2221` | notify 红字“放置失败: …” | 静态 |
| 10 | EAI `scene_load` | `agent_commands.py` `cmd_scene_load` → `ed._load_scene` | `editor.py:1235` | 命令返回 `{'loaded': path}` 且场景未变（静默失败语义，见下） | 静态 |

真实子进程实测输出（`verify_03_gate_run.py`，高版本场景 `min_engine_version=99.0.0` 写在 %TEMP%）：

```
[E build_entry.py --run]  rc = 1 (1.3s)  含99.0.0=True 含Traceback=False
   | [场景] 这个场景要求**更新的引擎版本**，当前播放器无法加载。
   | 场景要求引擎 >= 99.0.0, 当前引擎 0.1.0.beta6: 拒绝加载 (…)
[F Loom.py --run (远程回读 on)]  rc = 1 (1.9s)  含99.0.0=True 含Traceback=False
```

### 6.2 矩阵外的两个观察（不属任务列表，但影响“全入口”说法）

1. `--bench`（`Loom.py:396-415` → `build_entry._bench_scene`）**没有**版本闸的友好处理：`check_engine_version` 的 `SceneVersionError` 会以 traceback 冒到 stderr、退出码非 0。文档 §7.4 约定“bench 失败 = traceback + 退出码 2”，所以这是**已知约定**而非漏洞，但严格说 bench 入口是“能失败、不友好”。
2. `EAI scene_load` 的失败是**静默**的：`editor._load_scene` 内部 `return`，`cmd_scene_load` 仍返回 `{'loaded': path}`；Agent 侧无法区分“加载成功”与“被版本闸拒绝”。属于可改进项（P2），不是本次宣称范围。

---

## 7. 不实之处汇总（按严重度）

| # | 宣称 | 事实 | 定位 |
|---|---|---|---|
| P1-1 | 发布包 = beta6 交付物 | dist 两包均早于最后 4 个提交；源码包 102 命令、11 文件与 HEAD 不同（缺 6e9e315 后处理段 + 80ee837 整批资产修复） | `tools/dist/Loom-0.1.0.beta6-source.zip` mtime 20:22 vs 提交 20:33–20:42；`使用操作指南.txt:449` |
| P2-2 | EAI 命令 102 条 | 实测 103 条（80ee837 新增 `asset_user_override`） | 8 处文档，见 §2；自检命令 `使用操作指南.txt:735` 会自证矛盾 |
| P2-3 | env 附录“全量清单 / 41/41” | 漏 `LOOM_POST_EXPOSURE`（运行时，loom_post.py:71）+ 3 个构建 env；另混入 2 个仅测试用开关 | `使用操作指南.txt:649` vs §4 表 |
| P3-4 | 12 个能力名“每项给实现位置与用法” | 只有 README:128-139 与附录 F:719-732 给全；其余三份仅提及 | §1 |

## 8. 复跑方式（全部只读）

```
python Loom/tests/_tmp/verify_03_env.py        # env 初筛
python Loom/tests/_tmp/verify_03_env2.py       # env 精筛(含 helper 传名)
python Loom/tests/_tmp/verify_03_envcount.py   # 附录 E 条目分类计数
python Loom/tests/_tmp/verify_03_pkg.py        # ⑤ 打包断言 20 例负例
python Loom/tests/_tmp/verify_03_zip.py        # 已发版 zip 元数据抽查
python Loom/tests/_tmp/verify_03_zipdiff.py    # zip vs HEAD 逐文件哈希
python Loom/tests/_tmp/verify_03_zipdiff2.py   # 关键文件内容级 diff
python Loom/tests/_tmp/verify_03_parsever.py   # parse_version 逐字符对照
python Loom/tests/_tmp/verify_03_frameplan.py  # FramePlan 引用量对照
python Loom/tests/_tmp/verify_03_metadiff.py   # 包内 解释器.json 字段比对
python Loom/tests/_tmp/verify_03_gate_run.py   # ⑥ 两个入口真实子进程
```

## 9. 结论

- **达成**：③ SCENE_VERSION=11 全链一致；⑤ 打包断言本身（meta / 嵌套运行时 / build_info / 包名 / 精简标记）20/20 负例真实触发，端到端 `--version` 冲突 exit 1 且不落包；⑥ 10 个在册入口 10/10 有版本闸，2 个入口子进程实测 rc=1 且无 traceback。
- **部分不达成**：① 能力名“可查”成立、“每项位置+用法”只有两份文档成立；④ 41 条运行时条目本身存在，但“全量”漏 1 个运行时 env 与 3 个构建 env。
- **不达成**：② EAI 数字 102（实际 103），且文档自带自检命令会打出相反结果；⑤ 的交付一致性——dist 里 beta6 两包早于 HEAD 的 4 个提交，按文档自己的“改动代码后必须重打”规则属过期产物，**当前发布物缺 6e9e315 的后处理段与 80ee837 的资产批次**。
- 待裁决：发布前是否重打 source/compiled 两包；102→103 与 env 缺口是否随下次文档批修正。
