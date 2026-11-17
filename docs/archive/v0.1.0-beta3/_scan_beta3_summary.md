# beta3 修补回补审计 · 跨模块总账（2026-11-08）

> 汇总 6 份模块审计报告：`scan_beta3_01..06_*.md`。判据三件套：桌面《论如何正确的 vibe coding》《论如何使用AI自动化工具正确的判断AI给出的黑盒是否符合设计标准》+ 本仓库 `docs/audit/SCAN_PROTOCOL.md`。
> **本轮只审计不改码**：所有子代理均被约束为只读，修复动作待人类裁决后由"发现者本人"执行。

## 0. 范围与方法

| 项 | 值 |
|---|---|
| 被审对象 | 上一 Agent 的"新内测版（beta3）修补" |
| 提交区间 | `f53a82a..HEAD`（29 个提交） |
| 源码改动 | 25 改 + 3 新增（Loom/*.py、LoomHub/*、tools/*） |
| 审计分组 | 6 组并行子代理（输入键位 / VK·GL 播放器 / UI·驱动 / 编辑器·Agent / 打包发布 / 物理·吃豆人） |
| 原始设计基线 | `git show f53a82a:<file>` + `docs/handoff/20261107_*` + `_scan_summary.md §6` 的人类裁决 Q4~Q8 |
| 只读证据 | 审计起点 `HEAD=62479f0`；全程 `git diff` 为空；仅新增 6 份报告 + 本台账（`??`）+ 探针在 `Loom/tests/_tmp/`（gitignore） |
| 一次已还原的污染 | 主审跑 `tests/run_all.py` 取证时，测试自身改写了两个**受跟踪**文件：`Loom/tests/设置.json`（键序被 `guiloader.save_settings` 重写）与 `Loom/输入配置.json`（新增 `"解锁鼠标": ["Tab"]`）。已 `git checkout --` 精确还原，还原后 `git diff` 为零。**这次污染本身是 01·P-01-05 的现场复现**：改键路径会把运行时绑定写回受跟踪的引擎配置 |

## 1. 覆盖率与四象限（各报告自报）

| 组 | 模块 | 粗筛 | 跳过 | PROVED | DISPROVED | UNKNOWN | CONTRADICTION | [REGRESSION] | 等级分布（PROVED） |
|---|---|---|---|---|---|---|---|---|---|
| 01 | 输入/键位/鼠标锁定 | 16 | 7 | 13 | 3 | 3 | 0 | 8 | P0 1 / P1 2 / P2 5 / P3 5 |
| 02 | VK/GL 播放器运行时 | 18 | 8 | 12 | 4 | 2 | 0 | 6 | P1 4 / P2 5 / P3 3 |
| 03 | UI 事件派发与驱动层 | 18 | 7 | 9 | 6 | 3 | 0 | 9 | P0 1 / P1 3 / P2 5 |
| 04 | 编辑器与 Agent 可视化 | 25 | 5 | 11 | 12 | 2 | 0 | 4 | P1 3 / P2 5 / P3 3 |
| 05 | 打包与发布链 | 23 | 8 | 17 | 5 | 1 | 0 | 8 | P1 3 / P2 10 / P3 4 |
| 06 | 物理碰撞与吃豆人脚本 | 15 | 10 | 8 | 6 | 1 | 0（1 例已消解） | 2 | P1 1 / P2 4 / P3 3 |
| **合计** | — | **115** | **45** | **70** | **36** | **12** | **0** | **37** | P0 2 / P1 16 / P2 34 / P3 18 |

口径说明：01 的 3 条 UNKNOWN 编号在 16 条粗筛之外（另计）；06 的 P-06-02 初判 CONTRADICTION，查链后按窄口径收敛为 PROVED 并留痕。等级是各报告自评，主审对 P0 口径有保留（见 §7）。

## 2. 主审亲手复核的证据（不采信"报告写得像"，只采信我能重跑）

| # | 项 | 我做的事 | 实测结果 |
|---|---|---|---|
| V1 | 05 · P-05-01 `--agent` 打破既有断言 | `python tests/test_hub.py` | `总结果: FAIL ❌ ['.py 用系统默认 python + --open', '.py 纯启动无场景参数', '.exe 直接运行 + --open']` EXIT=1 |
| V2 | 03 · P-03-01 Tab 解锁净无效 | `python tests/test_vk_camera_align.py` | `FAIL 10 Tab 经脚本解锁鼠标 (True, False)` EXIT=1（同时打印"按键 [Tab] 切换鼠标锁定 -> 已解锁"，即脚本解了又锁回） |
| V3 | 01 · P-01-01 `apply_game_bindings` 无定义 | 全仓库 grep + `python tests/test_scripts.py` | 仅 2 处命中（1 处文档、1 处调用），**无任何 def**；实跑 `AttributeError: 'GLEngine' object has no attribute 'apply_game_bindings'` EXIT=1 |
| V4 | 02 · P-02-01 `or True` 掩盖写失败 | 读 `run_player.py:100-105` | `return ok_game or True` 恒真；`_handle_vk_init_failure` 的 `if not ok`（:124）为死分支 |
| V5 | 02+03 · P-02-04 / P-03-02 `camera.fov` 被覆盖 | 读 `scene_driver.py:574-597` | :576 读入后 :589 `self.fov = math.radians(60.0)` 无条件覆盖（死赋值），GL 侧应用场景值 → 双后端分叉 |
| V6 | 05 · P-05-07 版本事实源不一致 | 读 `解释器.json` 等四处 | `解释器.json=0.1.0.beta2` / `release_github 缺省=0.1.0.beta3` / `版本.json=0.1.0` / `installer.iss=0.1.1` |
| V7 | 06 · P-06-01 GL 播放器无 UI 派发 | 全仓库 grep `dispatch_mouse` | 仅调用点 `editor.py:580` 与 `vk_ui.py:853`；`runtime.py` 无派发代码（仅注释） |
| V8 | 06 · P-06-14 `invuln` 死参数 | grep `_invuln` | 声明于 :20，写入仅 :26 初始化 0.0 与 :161 硬编码 1.5；参数从未被读 |
| V9 | 04 · P-04-06/03 撤销丢记录 | 读 `undo.py:1120-1170` | `undo()` 先 pop 再 `cmd.undo()` 无容错；`cancel_batch()` 不清 `redo_stack`（`_append` 才清） |
| V10 | 04 · P-04-01 播放污染编辑态投影 | 读 `editor.py:231-232 / 956-963` + grep `ortho|_fov` | `ortho/ortho_size/_fov` 仅初值与 `_apply_camera` 写入；停止播放只还原 models/lights/cameras 快照，**无一处还原这三个视图属性** |

10/10 与报告一致；未发现伪造或夸大的项。唯一的**等级分歧**见 §7。

## 3. 全量回归基线（主审实跑，权威红名单）

命令：`cd Loom && python tests/run_all.py`（106 个 `test_*.py`，输出 tee 到 `tests/_tmp/beta3_runall_baseline.log`）

```
有失败: ['test_eai_real.py', 'test_hub.py', 'test_render_api.py', 'test_scripts.py', 'test_vk_camera_align.py']
EXIT=1
```

| 红文件 | 对应结论 | 是否被子代理报告 |
|---|---|---|
| `test_hub.py` | 05 · P-05-01（`--agent` 追加打破 3 条断言） | 是 |
| `test_vk_camera_align.py` | 03 · P-03-01 / 01 · P-01-02（Tab 双翻转） | 是（两组独立命中） |
| `test_scripts.py` | 01 · P-01-01（`apply_game_bindings` 无定义） | 是 |
| `test_render_api.py` | 02 · P-02-07（`游戏设置.json` 落点=dirname(argv[0])） | 是（P2），**主审确认已造成真实红**：`Loom/tests/游戏设置.json` 残留 `{"render_api":"opengl","key_bindings":{"跳跃":["j"]}}` → `resolve_backend('')` 返回 opengl，测试期望 vulkan |
| `test_eai_real.py` | **本轮无人报告**：`FAIL 命令表全部命令都被真编辑器执行过（共 98 条）['camera_proj','key_binding','render_api']` | **否** |

结论：本轮新增的 EAI 命令表扩了 3 条（camera_proj / key_binding / render_api），但其覆盖率测试未同步扩展 → 红。属"新功能未纳入自身验收口径"，等级 P2（不是运行期 bug，但会持续污染闸门）。

## 4. 跨报告去重后的主题（同类缺陷反复出现，说明是习惯而非偶然）

### 4.1 多后端等价性系统性失守（**本轮头号主题**，5 条独立证据）
| 语义 | GL/编辑器侧 | VK 侧 | 来源 |
|---|---|---|---|
| 场景 `camera.fov` | 应用 | 复位 60° | 02 P-02-04 + 03 P-03-02（双证实测 75°/60°、100°/60°）|
| UI 鼠标事件 | 编辑器有 | VK 有、**GL 播放器无** | 06 P-06-01 |
| 强制解锁键 | 引擎 poll + 内置脚本各 toggle 一次 | 同（净无效） | 01 P-01-02 + 03 P-03-01 |
| screen Canvas 尺寸同步 | 仅 GLFW 一处（`loom_glfw_window:186`） | 从不 resize | 02 P-02-15 + 03 §2.S |
| 解锁键在暂停态 | 逻辑帧停 → 失效 | 同 + 鼠标增量积压 | 03 P-03-07 + 01 P-01-04 |

### 4.2 "写配置/回写元数据失败 → 打印一行 → 当成功"
`run_player.py:101 return ok_game or True`（02）｜`set_action_binding` 写盘被拒仍 `saved:True`（01 P-01-03）｜`package_engine` 元数据回写 `except: pass`（05 P-05-05）｜`agent_commands` `saved` 恒 True（04 P-04-08）。四处同一模式。

### 4.3 死代码 / 死参数 / 死条款
`apply_game_bindings` 无定义（01 P-01-01）｜`invuln` 参数不生效（06 P-06-14）｜`_LAST_SOURCE` 只写不读（02 P-02-10）｜`_poll_mouse_unlock_key` 插在 docstring 前使两个函数 `__doc__=None`（01 P-01-10）｜`.gitignore` 死模式（05 P-05-17）｜`--include-package-data=wgpu_native` 指向不存在的包（05 P-05-19）｜步进模式移除后的 `LOOM_AGENT_STEP` 残flag（04 P-04-11）。

### 4.4 撤销/批次状态机
悬挂批次锁死撤销（04 P-04-05）｜批内 undo 弹掉批外命令且 redo 被抹（04 P-04-04）｜单条失败丢整批（04 P-04-06）｜`cancel_batch` 不清 redo（04 P-04-03）｜`camera_proj` 不进脏判定、不进撤销（04 P-04-02）。

### 4.5 发布闸门失效
缺预置运行时只警告仍出"正式包"（05 P-05-04）｜版本缺省值互相矛盾可发空 release 并烧 tag（05 P-05-07）｜上传失败重跑必 422、删同名 asset 分支永不命中（05 P-05-08）。

## 5. 流程缺陷（比单个 bug 更值得修）

1. **闸门接错了管子**：本轮验收口径是"MCP 40/40 + 定向探针"，验的是"功能能不能用"，**不验"既有断言还成不成立"**；而仓库本来就有 `tests/run_all.py` 一键全量回归（106 个测试）。结果是 5 个红文件发版前无人看见。
2. **MCP 验收与被改模块无交集**：40 项里没有一条会去跑 `build_launch_command`、Tab 解锁、`apply_game_bindings`。
3. **文档与实现三处不一致**（AUDIT-DOCIMPL）：交接总纲 §6.1 根因写错（02+03 双双证伪：命中与绘制共用同一像素空间，真凶是光标锁死 + Tab 失效）；交接总纲 §4 声称 `apply_game_bindings()` 已实现（实际无定义）；`_handle_vk_init_failure` docstring 说写"设置.json"、实现写"游戏设置.json"。
4. **测试与发版产物解耦**：`游戏设置.json` / `日志.txt` 会落在 `Loom/tests/`（未被 gitignore，主审取证后已删除），使"同一份代码在不同 CWD 下结论不同"；实测残留内容 `{"render_api":"opengl","key_bindings":{"跳跃":["j"]}}` 直接把 `test_render_api.py` 弄红。
5. **测试会改写受跟踪配置**：跑一次全量回归就让 `Loom/输入配置.json` 与 `Loom/tests/设置.json` 变脏（主审已还原）。这意味着"干净 clone 上跑测试 → 工作树变脏 → 下一次提交夹带配置漂移"，是审计可重复性的隐患。

> 建议（成本极低）：`release_github.py` 在推 tag 前先跑 `tests/run_all.py`，非零即中止；`package_engine` 在收尾前从 zip 读回元数据过 `validate_meta`。

## 6. 裁决记录（原始 15 道归并为 13 道；**2026-11-08 已全部锁定**）

### 6.0 最终裁决（人类拍板，作为修复轮的验收依据）

| # | 裁决 | 落地口径（修复轮按此验收） |
|---|---|---|
| D1 | **A** | 打包时回写 `Loom/解释器.json`；`release_github` 读它做发布前校验；包名/包内元数据/tag 三者一致。**版本号口径（2026-11-08 人类补充）：正式发包前内部开发名一律 = `0.1.0.beta4`，不得改名**；现存的 `解释器.json=0.1.0.beta2` 与 `release_github` 缺省 `0.1.0.beta3` 都要统一到 `0.1.0.beta4`。LoomHub 侧保持 `0.1.1` 不随引擎改（`版本.json` 的 `0.1.0` 属陈旧值，统一为 `0.1.1`） |
| D2 | **B** | 缺 `player_runtime` 默认失败；要出瘦包必须显式 `--allow-missing-runtime`，并在包内元数据/README 标记"精简包" |
| D3 | **B** | `build_launch_command` 恢复纯拼装；`--agent` 由 `hub_controller` 负责（`hub_commands` 已有，不动）；双 `--agent` 顺带消失；补"恰好一个 `--agent`"断言 |
| D4 | **A** | `camera_proj`/`key_binding`/`render_api` 三条新命令补进 `test_eai_real` 的"全命令被执行"清单并真跑 |
| D5 | **用户目录方案** | 见 §6.0.1：默认模板层（发布夹，只读）+ 用户层（`%LOCALAPPDATA%\Loom\…`）+ schema 迁移 + 失败备份 + 写失败即报错（不做冗余兜底） |
| D6 | **A/A/A** | 引擎独占解锁键；内置 first/third_person 删掉硬编码 `Tab` 分支（只读 `mouse_locked` 状态）；`Script` 增加 `keys_used` 声明；设置冲突键时**拒绝保存**并提示"Tab 已被脚本 X 使用，请先定义解锁键" |
| D7 | **A** | `ortho/ortho_size/fov` 归为场景相机属性：进脏判定、进撤销、播放前后恒等；实现后必须重跑 `ab_batch` 像素基线 |
| D8 | **A** | 给 `runtime.PlayerApp` 补 UI 鼠标派发链，三后端语义统一（**不得按交接 §6.1 的错误根因去修**） |
| D9 | **随 D5 而定** | 打包游戏：exe 旁仅放开发者默认模板；实际配置落用户目录；编辑器态按**工程标识**分目录；测试强制 `LOOM_GAME_DIR` |
| D10 | **A+B** | 批次租约 30s 自动收口；状态栏显示"Agent 批次进行中（剩余 Xs）"；批内 Ctrl+Z 提示"批次进行中，暂不可撤销" |
| D11 | **A** | 看门狗以**窗口状态**（是否最小化/不可见）为判据暂停计时，不以"停帧时长"为判据（否则等于拆掉看门狗） |
| D12 | **A** | `_push_out` 补显式破同分规则（最大轴/`+y` 优先，与盒-盒一致），重跑 10 个物理测试并记录位形差异 |
| D13 | **A** | 吃豆人工程场景入库（放 `examples/`，不改 `Projects/` 的忽略约定）；发布物与快照做哈希对照 |

### 6.0.1 D5 细化（用户目录配置体系的 5 个细节）

| 子项 | 裁决 | 落地点 |
|---|---|---|
| Q1 用户目录标识 | **A** | 开发者声明 `game_id`（缺省回退"标题 + exe 目录 hash"）；编辑器态用工程标识 |
| Q2 用户层存什么 | **A** | 只存用户改过的键（delta）；合并 = 默认模板为底 + 用户层覆盖 + 未知键保留 |
| Q3 迁移失败 | **A** | 备份 `settings.bak-<时间戳>.json` 后写默认模板 |
| Q4 便携模式 | **B** | 不做便携覆盖，一律用户目录 |
| Q5 编辑器归属 | **A** | 引擎/Hub 按应用；每游戏配置按工程标识 |

### 6.0.2 由此新增的待办（本轮审计发现，需并入修复轮）

1. **用户目录配置体系是一次全局改造**，不是局部修补：涉及 `guiloader.settings_path/save_settings`、`game_settings.game_dir/path`、`loom_input._action_bindings_file`、`run_player._persist_backend/_read_setting`、`scene_driver`、`engine.set_render_api`、`game_player._bootstrap_logging`、LoomHub 的 `hub_config` 设置读写，以及 `LOOM_GAME_DIR` 的测试强制。
2. **`Loom/输入配置.json` 降级为只读模板**（改名 `输入配置.default.json`），运行时写入一律走用户目录 —— 根治 P-01-05，也让"跑测试不弄脏工作树"成立。
3. **卸载器选项**：`installer.iss` 增加"是否同时删除用户配置"（`%LOCALAPPDATA%\Loom\…`）。
4. **工程移除要清理对应配置**：删除工程时同步删除其用户层配置目录；另提供"列出孤儿配置"与"一键清理"入口（**不做静默自动删除**——工程可能在临时未挂载的磁盘上）。
5. **日志落点**：`日志.txt` 进 `%LOCALAPPDATA%\Loom\logs\<app>\`，不再写程序目录（也解释"打包版没日志"的一种成因）。

### 6.1 阻塞发版（必须在下次发版前定）
| # | 问题 | 选项 | 出处 |
|---|---|---|---|
| D1 | 版本单一事实源 | A 打包回写 `解释器.json`（进 git）/ B 新增 `VERSION` 单点、`解释器.json` 降级为运行期元数据 | 05-Q3 |
| D2 | 缺预置运行时是否致命 | A 直接失败退出 / B 保留但必须显式 `--allow-missing-runtime` | 05-Q2 |
| D3 | `--agent` 归属 | A 保留在配置层、改 3 条测试断言 / B 移到调用方、保住 `build_launch_command` 纯拼装 | 05-Q1 |
| D4 | EAI 新命令的覆盖率口径 | A 把 3 条新命令补进 `test_eai_real` 的"全命令被执行"清单 / B 放宽该测试为"关键命令"白名单 | 主审 §3（无人报） |

### 6.2 决定修复方案形状（可分批，但建议一并定）
| # | 问题 | 选项 | 出处 |
|---|---|---|---|
| D5 | 配置写入失败的统一语义 | A 一律"失败即失败"（返回值/退出码如实） / B 分级：玩家可见配置失败必须上报，缓存类可降级 | 02-Q1 + 01-Q3 + 05-Q2 同源 |
| D6 | 解锁键权威归属 | A 引擎独占该键、内置脚本删 Tab 分支 / B 脚本优先、引擎只置意图 / C 引擎独占但改默认键位避开编辑器 Tab/F10 | 01-Q3 + 03-Q1 |
| D7 | 相机投影属性归属（`ortho/ortho_size/fov`） | A 场景属性（进脏判定 + 进撤销 + 播放前后恒等，修代码+跑 ab_batch）/ B 编辑器视图设置（移除 sceneio 写侧、只改文档、接受 GL/VK 长期分叉） | 03-Q3 + 04-Q2 |
| D8 | GL 播放器 UI 派发缺口 | A 补 UI 鼠标派发链（三后端统一）/ B 该类游戏强制走 VK（回退 GL 的机器将无法通关） | 06-Q1 |
| D9 | 键位/每游戏配置落点目录 | A 引擎目录（现状，跨游戏串味）/ B 当前工程目录（编辑器传工程路径）/ C 用户数据目录 | 01-Q2 + 02 P-02-07 |
| D10 | 批次悬挂收敛 | A 租约到期自动 `end_batch`（历史保留）/ B 批次期间 undo 一律拒绝并提示 / C cancel 整体回滚（推翻现契约） | 04-Q1 |

### 6.3 可延后（不阻塞发版，但需记账）
| # | 问题 | 选项 | 出处 |
|---|---|---|---|
| D11 | 看门狗"最小化 >60s"是否算渲染无进展 | A 不算（暂停计时）/ B 仍 `os._exit(9)`（现状，最小化 70s 实测 t=65s 被杀） | 02-Q2 |
| D12 | `_push_out` 同分方向 | A 补显式破同分规则（行为变更需新基线）/ B 只改注释承认"同分未定义" | 06-Q2 |
| D13 | 吃豆人场景真值入库 | A 把 `Projects/PacMan2D.json` 入库 / B 只入库出包场景哈希清单 | 06-Q3 |

## 7. 主审保留意见

1. **P0 口径分歧**：01 的 P-01-01 按协议标 P0（协议 P0=安全/崩溃），但它不崩、只是功能失效 + 配置层被丢弃；我倾向 P1。**若不统一"P0 定义"，修复排序会失真**；建议把协议里 P0 明确为"崩溃/安全/数据丢失/发版不可逆"，其余最高 P1。03 的 P-03-01（Tab 解锁失效）按同口径也应落在 P1，但它影响"玩家被锁死在锁定光标"这一逃生动作，可按"体验级 P0"处理。
2. **未覆盖**：GPU 像素级 A/B 基线（`ab_batch` / `ab_gl_vk`）本轮无代理实跑（需真实 GL+VK 设备），D7 若选 A 必须在修复轮补跑。
3. **UNKNOWN 保留 12 条**（如内存峰值、无控制台打包版日志行为、窗口销毁后定时器），均写清"还缺什么信息"，未擅自降级为 PASS。
4. **子代理自评等级不可当验收**：本轮能站住的结论全部来自"可重跑的复现命令"，凡只有推理没有运行的段落已在各报告 §2 标注。

## 8. 修复轮派单方案（待人类放行后执行）

原则：**谁发现谁修**（根因在他手里），**改的人不自证**（由另一子代理复跑最小复现 + 全量回归）。

| 序 | 承接 | 范围 | 验收标准（硬） |
|---|---|---|---|
| 1 | 01 号 | P-01-01/02/03 + D6/D9 落地 | `test_scripts.py` 转绿；Tab 解锁在 fps 与暂停态均生效；写盘失败必须如实上报 |
| 2 | 02 号 | P-02-01/02/03/07/08 + D5 | `or True` 消除；只读安装目录下"崩一次→下次 GL"真实成立；`test_render_api.py` 转绿 |
| 3 | 03 号 | P-03-01/02/03/07 + D7/D6 | `test_vk_camera_align.py` 转绿；GL/VK 同场景 fov 一致；ab_batch 基线不放宽 |
| 4 | 04 号 | P-04-01/02/03/04/05/06 + D10 | 悬挂批次不锁死撤销；播放前后投影恒等；批内失败不得丢整批 |
| 5 | 05 号 | P-05-01/04/05/06/07/08 + D1/D2/D3 | `test_hub.py` 转绿；缺运行时/版本不一致必须非零退出；发布前预检零写操作 |
| 6 | 06 号 | P-06-01/02/03/05/14 + D8 | GL 播放器能通关后重开/退出；`invuln` 生效；物理 10 测试保持 PASS |
| 7 | 主审（我） | 合并后统一复跑 `run_all.py` + 指纹比对 | 5 红清零或经裁决豁免；受跟踪文件改动全部可解释 |

跨轮次铁律：修复动作与审计动作解耦；每个修复必须附"修前失败 / 修后通过"两条输出；禁止顺手改报告外的地方。

## 9. 修复轮落地状态（2026-11-08）

### 9.1 批次与验证

| 批 | 承接 | 内容 | 主审独立复核 |
|---|---|---|---|
| 0 | 01 | 用户目录配置地基（`userpaths.py` + `guiloader`/`game_settings`/`loom_input`/`engine` + 契约文档） | `test_user_config` ALL PASS；`test_scripts` 由 `AttributeError` 转绿；`输入配置.json` 为 0 改动重命名 |
| 1 | 01 | D6=A/A/A 解锁键 + P-01-02 | `test_vk_camera_align` 由 `FAIL 10` 转绿；`test_unlock_key` 新增并绿 |
| 2 | 03 | D7=A 投影归属 + P-03-02/03/04/06/07/08/09 + N1 | `fov` 死赋值确认删除（:607 走 sceneio 归一）；`import os` 已补；4 个定向测试全绿 |
| 3 | 02 | P-02-01/02/03/07/08/09/10 + D8=A + D11=A | `test_render_api` 转绿；看门狗"最小化 70s 不死、可见卡死仍杀"双向实测 |
| 5 | 05 | D1=A(beta4)/D2=B/D3=B/D4=A + P-05-04/05/06/07/08/10/11 | `test_hub`(3 断言) / `test_eai_real`(98 条) / `test_release_version` 全绿；四处版本号收敛 |
| 5b | 05 | LoomHub 设置与台账迁用户目录（含迁移） | 4 个 Hub 测试全绿；`icacls deny` 造只读目录仍能保存 |
| 6 | 06 | D12=A 破同分 + D13=A 场景入库 + P-06-03/05/06/07/14 | 3 个新测试全绿；`examples/PacMan2D.json` 与审计快照 SHA256 一致 |
| 4 | 04 | D10=A+B 租约 + P-04-03/04/05/06/07/08/09/10/11 + P-03-11 | 租约/拒绝提示/逐条容错均新增断言；`test_undo*` 系列绿 |

### 9.2 修复轮中新发现（审计阶段未抓到）

| 编号 | 内容 | 为什么审计漏了 | 处置 |
|---|---|---|---|
| **N1** | `scene_driver.py` **HEAD 无模块级 `import os`**（只有 `import os as _os`），键位加载块 `os.path.join` 抛 NameError 且被 `except: pass` 吞 → **VK 播放器"补读键位配置"从上线起就没生效过** | 异常被吞 → 不报错、行为只是"回落默认"，任何只看异常/看表面的探针都抓不到 | 第 2 批已修（补 import + 模板缺失出声 + 断言） |
| N2 | 未隔离的测试会写**真实** `%LOCALAPPDATA%\Loom`（实测 `games\tests-<hash>`、`engine\settings.json`） | 审计时配置体系还没落地，不存在这条污染面 | 主审修：`run_all.py` + `test_scripts.py` + `test_eai_real.py` 加 `LOOM_USER_ROOT` 隔离；残留已清理 |

**方法论结论（值得写进项目规范）**：`except: pass` / `or True` / 假 `saved:True` 这类"报喜不报忧"，不只是掩盖一次错误——它让**此后所有人**（包括审计 Agent）都失去观测手段。N1 就是活例：一个 P1 功能失效在仓库里躺了整个 beta3。

### 9.3 仍未验证 / 未关闭（诚实清单）

| 项 | 状态 | 缺什么 |
|---|---|---|
| GPU 像素级 A/B 基线（`ab_batch`/`ab_gl_vk`） | **未跑** | 需真实 GL+VK 设备；D7 选了 A，建议有卡机器补跑一次 |
| 打包版真鼠标点击验收 | **未跑** | 需打包产物 + 真窗口；§6.1 的根因已被证伪，但"真鼠标能点"仍需实机确认 |
| P-05-16（332MB 整包读入内存峰值） | P-UNKNOWN | 需内存受限机器 |
| P-02-16/17（打包版日志引导行为） | P-UNKNOWN | 需无控制台打包产物实测 |
| U-01（`editor` 帧末裸 except 包 `toggle_play`） | 待裁决 | "退出播放是否必须原子" |
| U-02（`_agent_idle` 的 `_refresh_status` 未包 try） | 待裁决 | 需窗口销毁后定时器实测 |
| `--require-tests` 发布闸门 | 已实现、**默认关闭** | 等全量回归清零后由主审改默认 |
| `LoomHub/interpreters.json`/`projects.json` 是否移出版本库 | 待裁决 | 建议保留一代作为迁移源 |

## 10. 交付状态（2026-11-08 收尾）

| 项 | 状态 |
|---|---|
| 全量回归 | `run_all.py` 114 个测试文件 / **0 FAIL** / exit 0（发版闸门已默认开启，见 `release_github.want_test_gate`） |
| 独立验收 | 两轮独立子代理复跑：第一轮 8/8、第二轮 11/11 全 PASS；两轮各自带回的问题（N1/N2/N3/N4/N5、A/B）已全部返修并再次验证 |
| 代码提交 | 10 个逻辑提交（带审计编号），已推送 `origin/main`（`0a8e28a..bf1f183`）；**未创建 tag、未发 Release**（按人类要求） |
| 引擎包 | `tools/dist/Loom-0.1.0.beta4.zip`（332.73 MB），自检"包名/元数据/运行时一致"通过 |
| 播放器运行时 | 2026-11-08 16:38 重编（Nuitka），96.9 MB / 99 文件（含今日全部修复） |
| LoomHub | `LoomHub-0.1.2-Setup.exe`（23.79 MB）；覆盖安装成功，注册表 `DisplayVersion=0.1.2`、`InstallLocation=C:\Program Files\LoomHub\`（单一条目，同 AppId 原地升级） |
| 安装校验 | 引擎 `C:\Program Files\Loom\0.1.0.beta4`：元数据 `0.1.0.beta4`、预置运行时存在、`输入配置.default.json` 有而 `输入配置.json` 无；自带 python 导入 `userpaths`/`engine` 正常，`user_root()=C:\Users\<u>\AppData\Local\Loom` |
| 实机测试 | **待人类执行** → `docs/audit/beta4实机测试清单_20261108.md` |

### 10.1 交付时仍未验证
见 §9.3（GPU 像素基线、真鼠标打包版验收、3 条 P-UNKNOWN、`--require-tests` 已在本次改为默认开启并有断言）。
