# 版本计划：LoomHub 0.1.3 / Loom 0.1.0.beta5（2026-11-09 启动）

> 人类裁决：**接下来所有修复都进这两个版本**，不再往 beta4 / hub 0.1.2 回填。
> 交付方式不变：编译版引擎包 + Hub 安装器，双 Release（`engine-v0.1.0.beta5` / `hub-v0.1.3`），发版闸门（默认跑全套回归）必须绿。

## 0. 已实测、必须修的（来自 2026-11-09 现场数据）

| # | 问题 | 证据 | 归属 |
|---|---|---|---|
| H1 | **Hub 无条件注入 `LOOM_REMOTE_MODE=1`**，引擎走"离屏 GL + QImage 回读"兜底路径 | 同场景同引擎 A/B：直连 **55/59/61 FPS**，remote-mode **38/38/41 FPS**；GPU 34%→31%、TPS 23.7→18.9 | LoomHub 0.1.3 |
| H2 | **Hub 自更新缺失**（只能手动下 Setup 覆盖装） | 全仓无 `self_update`/`check_update`；`test_hub` 里"远程下载接口"仍是 NotImplementedError | LoomHub 0.1.3 |
| E1 | **TPS 打不到目标**：配置 `logic_fps=30`，实测 23.7；同时 CPU 1.33 核、GPU 34% —— 串行等待型瓶颈（`pipe_wait` 约 2ms/帧 + Qt 定时器节奏） | `engine_metrics` 采样 + `--bench` 阶段拆解 | Loom beta5 |
| E2 | （可选）remote-mode 改**自动降级**：先试原生 present，失败才切兜底 | — | Loom beta5 |

## 1. H1：remote-mode 变设置项，默认关闭

- Hub 侧 `hub_controller.open_project` / `hub_commands.launch_spec` 不再硬写 `env['LOOM_REMOTE_MODE']='1'`。
- 新增设置项 `remote_mode`（Hub 设置，用户层 delta）：`auto|off|on`，**默认 `off`**；
  `auto` 留给 E2 的引擎侧自动降级；`on` 保留给"确实白屏"的机器。
- 设置项要有可发现入口（设置面板一行 + 说明"离屏回读兜底，会明显降帧率"）。

## 2. H2：LoomHub 自更新（对齐 DSH 策略）

人类明确要求的行为：

1. 发现新版本 → 下载安装包；
2. **暂时关闭 LoomHub**；
3. **静默后台安装**新版本；
4. **安装完不自动启动**，由用户手动打开。

实现要点（必须按此口径）：

| 环节 | 做法 |
|---|---|
| 检查 | 启动后台线程，延迟 ~10s、每 24h 最多一次；GET `/repos/lhy302/WeaveEngine/releases`，筛 `hub-v*` tag，与本地 `LoomHub/版本.json` 做语义版本比较；失败/无网**静默** |
| 提示 | 仅在"远端更新"时提示（版本号 + 链接）；设置项 `check_update_enabled`（默认 true）可关 |
| 下载 | 取 `LoomHub-<ver>-Setup.exe` 到 `%LOCALAPPDATA%\Loom\hub\updates\`；校验 size，若 release asset 带 `digest`（sha256）则校验；非 https 拒绝 |
| 安装 | 先写一个**后台 updater 脚本**（`updates\apply_update.cmd` 或 .ps1）：等当前进程 PID 退出 → 运行 `setup.exe /VERYSILENT /SUPPRESSMSGBOXES /NORESTART /ALLUSERS /SP-` → 结束 |
| 提权 | 安装目录在 Program Files 时需要管理员：用 `ShellExecuteW(..., 'runas', ...)` 触发 UAC（用户点一次"是"），或明确提示"需要管理员权限" |
| 关闭自身 | 提交安装任务后 Hub **主动退出**（这就是"暂时关闭"），不再弹"更新完成请重启" |
| 不自动启动 | 安装器静默模式本身不跑 `[Run] postinstall`；**updater 不得再拉起 LoomHub** |
| 失败可见 | 下载/校验/安装任一步失败 → 写 `%LOCALAPPDATA%\Loom\hub\updates\update.log` 并在下次启动时提示（不得静默吞） |

**明确不做**：不自动提权静默（UAC 必须用户确认）、不在更新时弹进度窗阻塞、不自动重启 LoomHub。

## 3. E1：TPS 不达标排查（Loom beta5）

- 先取数：`engine_metrics`（fps/tps/jitter/clock）+ `--bench` 阶段拆解，对比"编辑器播放态"与"PlayerApp"两条路径。
- 重点怀疑：渲染线程与逻辑线程的 `pipe_wait` 握手（约 2ms/帧）、Qt 定时器周期、`logic_fps=30` 与渲染节奏的相位关系。
- 要求：给出"改前/改后"同一场景的 FPS/TPS/阶段耗时对照；若短期不可修，写清根因与下一步探针。

## 4. 版本与发布物

| 项 | 0.1.3 / beta5 口径 |
|---|---|
| LoomHub 版本 | `LoomHub/版本.json` = `0.1.3`（唯一真源；`release_github` 缺省、`installer.iss` MyAppVersion、`test_release_version` 断言同步） |
| Loom 版本 | `Loom/解释器.json` = `0.1.0.beta5` |
| 发布说明 | `tools/release_notes/hub-0.1.3.md`、`engine-0.1.0.beta5.md` |
| Release | `hub-v0.1.3`（含自更新能力）、`engine-v0.1.0.beta5`（编译版 zip） |
| 闸门 | `release_github.py` 默认先跑 `Loom/tests/run_all.py`，非零即中止且零远端写 |

## 4.0 版本号策略（2026-11-09 人类裁决，长期有效）

> **代码里的版本号 = 正在开发的版本号**。开发期间内部代号一直不变；
> **该版本线真正发包之后**才跳到下一个号。两条版本线**互相独立**。

- 现在：引擎 `0.1.0.beta5`、LoomHub `0.1.3` 都是「**beta5 / 0.1.3 的中间版本开发状态**」；
- 直到 **beta5 正式上传**之前，引擎版本号一直叫 `0.1.0.beta5`，**不会**变成 beta6；
- 直到 **0.1.3 正式上传**之前，LoomHub 版本号一直叫 `0.1.3`，**不会**变成 0.1.4；
- 两条线各跳各的：只发了 Hub 0.1.3、引擎还没发 → Hub 下一轮开发改叫 0.1.4，引擎仍叫 beta5；
- 因此**开发期打出来的包就叫 `Loom-0.1.0.beta5.zip` / `LoomHub-0.1.3-Setup.exe`** —— 这是预期行为；
- 发布说明 `tools/release_notes/engine-0.1.0.beta5.md` / `hub-0.1.3.md` 就是这两版的说明，发包时直接使用。

## 4.1 发布状态（2026-11-09 人类补充）

**beta5 与 0.1.3 均为内测版本：本轮只打包 + 本机安装 + 实测，不推 GitHub Release、不打 tag、不上传资产。**
- 允许：编译、打包、覆盖安装、实机验证、版本号与发布说明文件照常准备（下一轮直接可用）；
- 禁止：`release_github.py` 任何形式的发布动作。

## 5. 交付顺序

1. H1 + H2 + E1 各自落地并带断言；
2. 全量回归绿；
3. 重编编辑器/构建器/运行时 → 打 beta5 编译版包 + Hub 0.1.3 安装器；
4. 本机覆盖安装 + 实机验证（帧率、自更新流程）；
5. 台账更新（**不发 Release**：内测版本，只本机安装 + 实测）。
