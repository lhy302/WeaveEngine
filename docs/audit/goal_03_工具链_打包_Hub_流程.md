# goal_03 · 工具链 / 打包 / Hub / 流程 —— 目标达成度独立扫描（第十轮）

> 立场：只判定，不改实现。全部结论来自**本轮亲自跑的命令**，不引用任何实现报告的自报数字。
> 基线：探查时 HEAD=`5b0a91d`（docs-only 提交），产物来源提交 `d1674fa`；`git status` 干净。
> 时间：2026-11-10 23:48–23:59。探针：`Loom/tests/_tmp/goal_03_*.py`（6 个），产物 json 同目录。

## 0. 目标原文（先抄目标，再判）

| # | 目标（出处原文） |
|---|---|
| T1 | Nuitka **4.3.5**；`--standalone`→`--mode=`；`--windows-disable-console`→`--windows-console-mode=disable`（research_06 §2.1 / Step 1.2） |
| T2 | 编辑器构建必须显式 `--enable-plugin=pyside6`，并把「dist 内 `PySide6/qt-plugins/platforms/qwindows.dll` 存在」**写成构建后断言**，不用体积断言（§2.3 G3、§7 Q2、Step 1.3） |
| T3 | 依赖矩阵：numpy 2.5.4 / moderngl 5.13.0 / PySide6 6.12.0 / wgpu 0.33.0 / glfw 2.11.0 / pillow 13.0.0 / pygame 2.6.1（不动）/ Python 3.12→3.13.15、MSVC 14.44 不动（§2.1、附录 D） |
| T4 | 判定门 **G1–G6**（§2.3）：G1 最小 standalone 可跑、G2 运行时全链路、G3 编辑器能起+qwindows、G4 121 测试全绿、G5 ab_gl_vk 不劣化 + 帧时间退化≤5%、G6 包体积≤+5% 启动≤+10% |
| T5 | 打包链硬断言：编辑器 dist 含 PySide6/qt-plugins/qwindows.dll、运行时 `pygame/` 新布局（≥15 DLL、根目录无 SDL2.dll）、`build_info` mode=release、元数据版本一致、内嵌 Python 版本一致（附录 C/E/F） |
| T6 | 冒烟：**5 条正向检查、整轮 <60s、红了不许打包**；禁止异常/回退/阈值/资产一致性（开发流程_冒烟与验证分层 §2、§3） |
| T7 | 测量层「只记录不判定（或按明确门禁）」（同一文档 §1、手持手册 §3） |
| T8 | 「包 = 代码」可机证：source 包 `.py` 与 HEAD 0 不一致；compiled 包 `git_head` 是 HEAD 祖先且 `Loom/` 零 diff；`git_dirty=false`；version 2 处 / python 3 处（附录 F/G、计划 §9.25） |
| T9 | Hub 侧：版本号单一真源 `LoomHub/版本.json`；发版自检与安装侧共用同一份 `hub_config.validate_meta`；Hub 0.1.4 随 beta6 |
| T10 | 流程：任务后**必须**派未参与实现的新子代理倒查（开发流程_任务后倒查 §2）；**每完成一个批次跑一轮干净子代理复核**（计划 §9.18）；全量回归单实例（§9.19） |
| T11 | 计划 §9.16–9.20：FPS≥85 **不再是硬门槛**（数据照记）、Python 版本路线改观察式、3.12 回滚点保留、编译版回到基线 |

## 1. 达成判定表（每条带可复现证据）

| # | 判定 | 证据（命令 → 输出 / 文件:行） |
|---|---|---|
| T1 | **达成** | `py -3.13 -m nuitka --version` → `4.3.5`；`Loom/build_game.py:236` `--mode=standalone`、`:244` `--windows-console-mode=%s`（无 `--standalone`/`--windows-disable-console` 残留，grep 0 命中）；`tools/build_engine.py:206-209` 同款新式 flag + `--nofollow-import-to=cupy` |
| T2 | **达成** | `tools/build_engine.py:207` `--enable-plugin=pyside6`；`:216-220` 构建后硬断言 qwindows.dll；`tools/package_engine.py:90-103` `QT_REQUIRED_PATHS` 路径存在断言（不判体积）；负例见 T5（N1 exit 1） |
| T3 | **达成** | `py -3.13 -m pip list` → numpy 2.5.4 / moderngl 5.13.0 / PySide6 6.12.0 / wgpu 0.33.0 / glfw 2.11.0 / pillow 13.0.0 / pygame 2.6.1 / culverin 0.14.0 / game-audio 2.1.0；`Loom/解释器.json` `python_version=3.13.15`；`vswhere -latest -property catalog_productDisplayVersion` → `17.14.37`（=14.44，按目标不动）；`requirements.txt` 已含 culverin/game-audio（附录 F 遗留②已闭合） |
| T4 | **部分达成** | G3：`C:\loom_build\engine\build_entry.dist` 下 Loom.exe / qwindows.dll / ckernels\loom_kernels.dll / core_components / 解释器.json **5/5 存在**；G2：`Loom/player_runtime/game_player.dist` MyGame.exe ✓、`pygame/` 15 个 DLL ✓、根目录无 SDL2.dll ✓。G5/G6 **本轮未复测**（归 02 主题；我只补一个独立帧率：`measure_engine.py --scene Loom/Projects/压测500混合.json --frames 300 --runs 3` → FPS 中位 **95.9**（89.9/95.9/97.7）、TPS 30.00，与 §9.17 口径同量级；按 §9.16 该门已非硬门）。G4 121 测试**未复测**（并发跑测试会互相踩，§9.19；且属 02 主题）。G6 包体积：本轮实测 compiled **132.09MB**、source **348.57MB** |
| T5 | **达成（7/7 负例真拦）** | `py -3.13 Loom/tests/_tmp/goal_03_pkg_negatives.py`：N1 缺 qwindows.dll / N2 档位 dev / N3 缺 `smoke_passed_at` / N4 冒烟早于 `built_at` / N5 带 cupy 重包 / N6 元数据版本 beta5 / N7 源码包 `--version beta10` → **全部 exit=1 且命中预期文案**；`tools/dist` 未产生 beta10 残留 zip。断言实现：`tools/package_engine.py:100/106/113/132/182`、`tools/package_engine_compiled.py:104-149` |
| T6 | **达成（含 2 处灰区，见 P3）** | 正向实跑：`py -3.13 tools/smoke.py` → `SMOKE OK 用时 6.2s（预算 60s）`，[1/5]–[4/5] PASS、[5/5] SKIP（源码模式）。只做正向：`smoke.py:128-153` 只判 models>0 / playing / fps>0 且 tps>0（**无阈值**），代码内无版本闸/回退/降级/资产一致性断言（grep 0 命中）。负例 3 条（`goal_03_smoke_negative.py`）：A 空 objects 场景 → exit 1（[2/5] 红）；C `--dist` 无 Loom.exe → exit 1；D 假 exe → exit 1 |
| T7 | **达成** | `tools/measure_engine.py:123-136` 只在显式 `--min-fps` 时判门；默认只打印中位并写 json。实跑两次（默认/压测场景）均 rc=0 且不判阈值 |
| T8 | **部分达成（工具存在盲区，见 P1）** | 真包实跑：`py -3.13 tools/verify_pkg_vs_head.py tools/dist/Loom-0.1.0.beta6-source.zip tools/dist/Loom-0.1.0.beta6-compiled.zip --version 0.1.0.beta6` → `[source] py 文件 93，与 HEAD 不一致 0，HEAD 不存在 0`；4 个 key 文件 OK；`[source] meta/nested -> OK`；`[compiled] git_head=d1674fa364b9 head=5b0a91dee498 dirty=False -> OK（引擎等价）`；`smoke_passed_at=2026-11-10 23:50:54 > built_at=23:35:20`；**EXIT=0，8.2s**。我另做的双向完整性对拍：`goal_03_pkg_completeness.py` → 打包器应拷 **237** / 包内实际 **237**，缺 0、多 0（现状真实完整） |
| T9 | **部分达成** | `LoomHub/版本.json`=`0.1.4`、`tools/installer.iss:3` `MyAppVersion "0.1.4"`、Hub 侧 beta6 提交在案（`2fc26db/aa31ca3/cb6aa5d`）；两包元数据过 Hub 判据（`goal_03_hub_accept.py`）：source/compiled 均 `validate_meta -> OK`、`interpreter_problem -> None`、主程序在包内（source main=Loom.py✓ / compiled main_exe=Loom.exe✓）。**但 Hub 0.1.4 安装器从未构建**：`tools/dist` 只有 `LoomHub-0.1.3-Setup.exe`（2026-11-09 15:28），`C:\loom_build` 全盘无 0.1.4 产物 |
| T10 | **部分达成** | 执行证据（按文件时间排序，非自报）：`docs/audit` 下 beta6 阶段性审核 **10 份**（`scan_beta6_round_01..04` 11-09 23:18–23:29、`round5_01..03` 11-10 13:07–13:16、`round6_01..03` 11-10 14:18–14:38）+ 倒查 **9 份**（`final_01..04` 15:07–15:14、`verify_01..03` 20:57、`verify2_01..02` 22:02–22:05）。**缺口**：最后一次倒查 22:05 之后，23:35 重编三件 + 23:49/23:51 重打两包这一段**没有对应倒查产物**（`docs/audit` 无 `goal_*`，R06 重打包亦无独立倒查文件）——即「交付动作本身」尚未按 §2.1 走过倒查 |
| T11 | **达成** | FPS 非硬门已落地：`measure_engine.py` 默认不判门；§9.16/§9.17 记录与我的 95.9 实测同量级；单实例纪律写进 `docs/handoff/接手须知_beta6当前状态_20261111.md:26,94`；3.12 回滚点保留（`C:\loom_build\pre_py313_freeze.txt` 类文件不在仓库内，属环境侧，未核） |

## 2. 本轮引入/发现的缺口（按严重度）

- **P1-1 `verify_pkg_vs_head.py` 只做单向对拍，存在两类假绿**（实测，`goal_03_verify_negative.py`）：
  - S1 源码包**一个引擎 `.py` 都没有** → `exit=0`，输出 `[source] py 文件 0，与 HEAD 不一致 0，HEAD 不存在 0`（分母为 0 的真空通过）；
  - S2 源码包**多出 HEAD 不存在的 `Loom/ghost_deleted_in_head.py`** → `exit=0`，只打印 `HEAD 不存在 1`。
  代码根因：`verify_pkg_vs_head.py:235-237` 的 `bad` 只含 `mismatch`，**不含 `missing_in_head`，也没有"HEAD→包"方向的完整性比对**（`check_source` 只遍历 zip 内名字，`:127-137`）。现状包是完整的（我补测 237/237），但这个门抓不住"少文件/多文件"的回归。
- **P1-2 源码包未接「档位 / 冒烟」门**：`tools/package_engine.py:435-508`（`make_zip`）对内嵌运行时只调 `meta_version_problems`(:113) 与 `runtime_layout_problems`(:182)，**从不调 `build_info_problems`(:132)**；grep 证据：`build_info_problems` 仅被 `package_engine_compiled.py:110/115/137` 调用。后果：可把 dev 档/未冒烟的 `game_player.dist` 内嵌进源码包而全链不红（compiled 侧同一条会被拦，N2/N3 已证）。
- **P1-3 Hub 0.1.4 无安装器产物**：版本账已对齐 0.1.4，但 `tools/dist` 仍是 `LoomHub-0.1.3-Setup.exe`；`package_hub.py` 会以 `版本.json`/`installer.iss` 交叉校验版本，因此**必须在本版执行一次 `py tools/package_hub.py`**，否则 beta6 只能配 beta5 的 Hub。
- **P2-1 冒烟 60s 只是提示**：`tools/smoke.py:176-177` `if dt > BUDGET_S and not fails: print(...)` —— 超预算不改退出码，与分层文档 §2「整轮 < 60 秒」的硬约束不一致（现状 6.2s，非当下风险）。
- **P2-2 冒烟 [5/5] 是复述**：`tools/smoke.py:163-167` 只要 `proc.poll() is not None` 就打印 `[5/5] 编译版产物能起`，未对包内任何文件做断言（等价于 [1/5] 的重复）。真正"包能起"的信息量全在 [1/5]。
- **P2-3 交付目录混放旧版**：`tools/dist` 同时有 `Loom-0.1.0.beta5.zip`(11-09)、`LoomHub-0.1.3-Setup.exe`、`loom-lint-except-0.1.1.zip`，与 beta6 两包并存，误上传/误分发风险实存。
- **P3-1 `--dist` 冒烟未复跑（方法说明，非缺陷）**：`smoke.py --dist` 会给真实 dist 的 `build_info.json` 盖章（写操作），本轮为只读审计未执行；现有章 `smoke_passed_at=23:50:54` 由他人盖上，我以 `built_at < smoke_passed_at` 的事实核对（T8）。

## 3. 统计

- 实跑命令 **9** 条；构造负例 **12** 条（冒烟 3、打包 7、对拍 2），**12/12 按预期变红**。
- 现状态绿项（我实测）：冒烟 6.2s / 压测 500 混合 FPS 中位 95.9（n=3）/ 对拍 exit 0（source 93 py 0 差异、compiled 引擎等价、dirty=false）。
- 目标 11 条：**达成 7**（T1 T2 T3 T5 T6 T7 T11）／**部分 4**（T4 T8 T9 T10）／**未达成 0**／**不适用 0**。

## 4. 发布前还必须做什么（清单，按门序排）

1. 补 `verify_pkg_vs_head.py` 的 HEAD→包 completeness 比对，并把 `missing_in_head` 纳入退出码（P1-1）；补一条自测（0 文件包 / 多文件包必须 exit 1）。
2. `package_engine.make_zip` 对内嵌 `game_player.dist` 加 `build_info_problems`（mode=release + smoke 章）（P1-2）。
3. 构建 **LoomHub 0.1.4** 安装器（`py tools/package_hub.py`），并核 `版本.json == installer.iss MyAppVersion == 产物名`（P1-3）。
4. 在**最终发布 HEAD** 上重编三件 → 冒烟盖章 → 重打两包 → 对拍；`build_info.git_head` 必须等于**发布 tag 指向的提交**，`git_dirty=false`（当前 git_head=`d1674fa` 而 HEAD=`5b0a91d`：仅 docs 差异，按引擎等价可接受，但**打 tag 前必须二选一**：tag 打 d1674fa，或在新 HEAD 重编）。
5. 交付动作本身补一轮倒查产物（`docs/audit/goal_*/final_*`），覆盖"重编→冒烟→打包→对拍"这条链；现有 9 份倒查都早于最后一次重打包（T10）。
6. 复跑全量回归（单实例）与 `ab_gl_vk`：本轮未复测（§9.19 并发纪律 + 归属 02 主题），发布前必须有一次同日证据。
7. 清理 `tools/dist` 旧版产物（beta5 zip、Hub 0.1.3 Setup、loom-lint），或挪出发布目录（P2-3）。
8. 二选一收口冒烟灰区：把超预算改成红，或在分层文档里明确"预算只告警"并把 [5/5] 改成实名（当前文案高估了它的检查力）（P2-1/P2-2）。
9. 发布说明需写明 `SCENE_VERSION=12` 对 beta5 的单向不兼容（Q-R6A-1=A），以及 §9.22 的"目标未全达成不收尾"前置条件。

## 5. 待裁决（供人类）

- Q3-1：`verify_pkg_vs_head.py` 的完整性比对是**硬门**（缺/多文件一律 exit 1）还是**告警**？（现状两者皆无）
- Q3-2：源码包内嵌运行时是否也要求 `smoke_passed_at`？（现状不要求，与 compiled 侧不一致）
- Q3-3：`tools/dist` 是否改为按版本分目录（例如 `dist/0.1.0.beta6/`），从机制上消除旧包混放？

---
### 附：本轮探针与产物
`Loom/tests/_tmp/goal_03_smoke_negative.py`、`goal_03_version_gate.py`、`goal_03_pkg_negatives.py`、`goal_03_verify_negative.py`、`goal_03_pkg_completeness.py`、`goal_03_hub_accept.py`；输出 `goal_03_verify.json`、`goal_03_measure.json`、`goal_03_measure_stress.json`。
