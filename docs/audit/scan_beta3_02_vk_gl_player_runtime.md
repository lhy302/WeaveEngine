# 播放器运行时链（VK/GL）beta3 补丁扫描报告

> 子代理编号：beta3_scan_02　|　审计对象：上一轮 Agent 对 beta3 内测版的 29 个提交（f53a82a..HEAD）
> 本轮只分析、不改代码。所有结论均附「文件:行号 + 命令 + 实测输出」；修复方向只写方向，不贴可直接替换的实现。


## TL;DR（给主审的 60 秒版）

- 18 项疑似 → **12 PROVED / 4 DISPROVED / 2 UNKNOWN / 0 CONTRADICTION**；跳过 8 项（均留痕）。
- 本轮补丁**引入**了 6 个问题（REGRESSION），最要紧三个：
  1. `run_player._persist_backend` 的 `return ok_game or True` 让「游戏配置写失败」完全不可见 → Q6 的「持久化回退」在只读安装目录下失效，**每次启动都崩**，且提示语还在说「下次启动将使用 OpenGL」（P-02-01/02）。
  2. 新 `游戏设置.json` 被旧 `游戏配置.json` 的 render_api 压过 → Q6 写回被作废，且 `_LAST_SOURCE` 谎报成 `cli`（P-02-03）。
  3. `runtime.py` 新增的场景 fov 读取，在 VK 侧被 `scene_driver.py:589` 无条件复位 → **同一场景 GL 75° / VK 60°**（基线两端一致，本轮引入分叉）（P-02-04）。
- 本轮宣称「修掉 P0：VK 看门狗 60 秒必杀」只修了一半：**窗口最小化 70 秒实测在 t=65s 触发 os._exit(9)**（P-02-05，非本轮引入但 DOCIMPL）。
- 证据链最硬的两个正向结论：`request_quit` 关窗/退出码**正确**（5 帧内返回、无异常）；VK UI 的 `script_host` 转发链**已打通**（`_ACTIVE_ENGINE=driver`、`_fire_binding` 命中并调用脚本）。
- 一条重要的**反向提醒**：交接文档 §6.1 的根因「GL 会把 canvas 尺寸跟窗口同步」在代码里不存在，按它给的处方只在 VK 侧同步画布尺寸会**制造新的 GL/VK 分叉**（P-02-15）。

## 0. 范围与方法

### 0.1 文件范围与规模

| 文件 | 行数 | 本轮 diff 行数 |
|---|---|---|
| Loom/vk_player.py | 586 | +50 |
| Loom/vk_renderer.py | 1999 | +16/-4 |
| Loom/vk_ui.py | 923 | +10/-3 |
| Loom/run_player.py | 182 | +44/-3 |
| Loom/game_player.py | 245 | +56 |
| Loom/runtime.py | 118 | +22/-3 |
| Loom/game_settings.py（本轮新增，被上述文件依赖） | 161 | 新增 |

命令：`git diff --stat f53a82a..HEAD -- <上述文件>`（6 文件 +183/-15，game_settings.py 为新增文件）。

### 0.2 判定基准清单（白盒契约，证真/证伪只能引这些）

| 编号 | 基准 | 出处 |
|---|---|---|
| C1 | Q6 后端回退精确语义：默认 vulkan；初始化失败时 a) 明确提示原因 b) 把配置写成 opengl（持久化、只写一次、避免每次启动都崩）c) 本次非零退出；下次启动读配置=opengl；**显式 --backend vulkan 不改写设置只报错退出** | `docs/audit/_scan_summary.md` §6「Q6 精确语义」（人类 2026-11-07 定稿） |
| C2 | 渲染后端优先级：CLI `--backend` > 游戏设置.json render_api > 引擎 设置.json render_api > 默认 vulkan | `docs/handoff/接手总纲_20261107_引擎发布与游戏打包.md` §3.4 + `run_player.py:51-75` 文档串 |
| C3 | 相机优先级：场景 camera 段（target/distance/yaw/pitch/ortho/ortho_size/**fov**）——播放时强制套用 | 同上 §3.4 |
| C4 | GL/VK 双后端等价性（同一场景同语义） | `docs/handoff/...` §1 分层表 + §9.2 A/B 基线；`vk_ui.py:7-35` 模块文档「与 GL 一一对应的最小面」 |
| C5 | 播放器退出必须释放鼠标捕获 | `docs/handoff/...` §2.6 + commit e848afc 标题 |
| C6 | 鼠标锁定由游戏配置驱动（mouse_lock_allowed / mouse_locked），运行时永远提供解锁键 | 同上 §2.6；`game_settings.py:64-74` |
| C7 | 看门狗用途 = 「防卡死」，不是杀正常渲染窗口 | `vk_player.py:503` 打印文案「watchdog: 渲染无进展 60s, 强制退出 (防卡死)」 |
| C8 | UI 声明式事件必须能找到脚本实例（`_ACTIVE_ENGINE` 必须是脚本宿主） | `loom_ui.py:16-20,694-706`；`docs/handoff/...` §2.7 表格第 2 行（本轮 P0） |
| C9 | `UIManager.draw_all(engine)` 的 engine = **绘制目标**；脚本宿主另传 | `loom_ui.py:694-703` 函数文档 |

### 0.3 跑过的命令与探针（全部可复跑）

| 编号 | 探针 | 用途 | 结果摘要 |
|---|---|---|---|
| PR-1 | `python Loom/tests/_tmp/beta3_scan_02_probe_q6.py` | Q6 回退语义（写失败/显式/两配置） | 见 P-02-01/02 |
| PR-2 | `python Loom/tests/_tmp/beta3_scan_02_probe_camera.py` | GL(runtime.PlayerApp) vs VK(scene_driver) 相机/锁定 | 见 P-02-04 |
| PR-3 | `python Loom/tests/_tmp/beta3_scan_02_probe_watchdog.py 8` / `70` | 最小化时 last_ok 是否停滞、看门狗是否误杀 | 见 P-02-05 |
| PR-4 | `python Loom/tests/_tmp/beta3_scan_02_probe_dupmodule.py` | `python run_player.py` 入口下 VkInitError 类身份 | 见 P-02-06 |
| PR-5 | `python Loom/tests/_tmp/beta3_scan_02_probe_uibridge.py` | VK UI script_host 转发链 | 见 P-02-14 |
| PR-6 | `python Loom/tests/_tmp/beta3_scan_02_probe_confprec.py` | 配置优先级 / 落点 / 读写隔离 | 见 P-02-03/07/09 |
| PR-7 | `python Loom/tests/_tmp/beta3_scan_02_probe_quit.py` | request_quit 关窗与返回 | 见 P-02-11 |
| PR-8 | `python Loom/tests/_tmp/beta3_scan_02_probe_cursor.py check/lock/check/restore` | os._exit(9) 后光标是否残留 | 见 P-02-13 |
| PR-9 | `python Loom/tests/test_backend_fallback_policy.py` | 既有 Q6 回归测试 | ALL PASS，且产生两个副作用文件（见 P-02-07/08） |

探针只落在 `Loom/tests/_tmp/`（该目录被 .gitignore 覆盖），未修改任何受跟踪文件。

### 0.4 工作树自查（硬约束 8）

执行 `git status --porcelain`：

```
?? docs/audit/scan_beta3_04_editor_agent_visual.md      (其他子代理的报告，非我)
?? docs/audit/scan_beta3_05_packaging_release.md        (其他子代理的报告，非我)
?? tools/lint_except_dist/                              (任务书已声明的既有未跟踪目录，未动)
?? tools/loom_lint_except.py                            (同上，未动)
```

**无受跟踪文件被改动。** 我唯一新建的受跟踪文件是本报告；探针在 `Loom/tests/_tmp/`（gitignore 覆盖，git status 不显示）。

运行既有 Q6 测试 `test_backend_fallback_policy.py` 时，**产品代码自身**生成了两个未跟踪文件：
`Loom/tests/游戏设置.json`（内容 `{"render_api": "opengl"}`）与 `Loom/tests/日志.txt`。
这两者不是误改、而是本轮补丁的副作用（P-02-07 / P-02-08 的直接证据）；取证后我已删除，`git status` 恢复原状。

## 1. 粗筛清单（含跳过留痕）

### 1.1 疑似项（18 项，编号 P-02-NN）

| ID | 位置 | 标签 | 初步方向 |
|---|---|---|---|
| P-02-01 | run_player.py:88-105,121-126 | SEM-SILENT / AUDIT-DEADCODE | `return ok_game or True` 使「游戏配置写失败」不可见；提示与下次启动真实行为相反；可形成崩溃循环 |
| P-02-02 | run_player.py:121-125 | AUDIT-ASYMMETRY | 先打印「已回退为 OpenGL/下次启动将使用 OpenGL」，再判 `ok` → 写失败也已宣布成功 |
| P-02-03 | game_player.py:123-136 + run_player.py:51-75 | IFACE-PRECOND / DESIGN-DRIFT | 旧 `游戏配置.json` 的 render_api 被当作 requested（最高优先）→ 新 `游戏设置.json` 的 Q6 写回被作废；且 `_LAST_SOURCE` 误标 `cli` |
| P-02-04 | runtime.py:59-67 vs scene_driver.py:574-589 | SEM-MISMATCH / 双后端不等价 | 同一场景 camera.fov：GL 生效 75°，VK 恒 60°（新增读取被下一行复位覆盖） |
| P-02-05 | vk_player.py:477-505 | BND-RESOURCE / 状态机 | `last_ok` 只在「有帧渲染」时喂；窗口最小化时 rendercanvas 停帧 → 60s 后 os._exit(9)；heartbeat 无停止条件 |
| P-02-06 | vk_player.py:35 + run_player.py:144-145 | IFACE-ERROR | `python run_player.py` 入口下 run_player 被加载两次 → VkInitError 双类身份 → Q6 回退链（提示+写配置）整体不执行 |
| P-02-07 | game_settings.py:20-35 + run_player.py:66-70 | BND-RESOURCE / DESIGN-DRIFT | 游戏配置落点 = dirname(argv[0])：在源码目录 `--run` 或测试进程里会把引擎目录当游戏目录 |
| P-02-08 | game_player.py:31-84 | OVERFIT-TESTENV / AUDIT-DOCIMPL | `_bootstrap_logging()` 在模块级执行：`import game_player` 即改写 sys.stdout/stderr 并建 `日志.txt`；日志 append 无上限 |
| P-02-09 | run_player.py:30-36 vs 96-100 | AUDIT-ASYMMETRY | `_read_setting` 忽略 `_SETTINGS_BASE`，测试隔离只覆盖写侧 |
| P-02-10 | run_player.py:39,61-73 | AUDIT-DEADCODE | `_LAST_SOURCE` 只写不读 |
| P-02-11 | vk_player.py:479-493 | 状态机 / 退出码 | request_quit 关窗是否抛异常、退出码是否正常 |
| P-02-12 | vk_player.py:482-493 | IFACE-PRECOND | draw 包装改 `*a/**k` 是否掩盖参数错误 |
| P-02-13 | vk_player.py:507-528 | BND-RESOURCE | `_release_cursor` 在 os._exit(9)/崩溃路径不执行 → 光标残留？ |
| P-02-14 | vk_ui.py:321-331 + vk_renderer.py:1029-1055,1748-1998 | IFACE-PRECOND | VK 侧 script_host 转发链是否完整、与 GL 语义是否真有等价 |
| P-02-14b | vk_ui.py:321 / loom_ui.py:706 | AUDIT-ASYMMETRY | `script_host` 缺省 = self，省略即复现旧 P0（陷门） |
| P-02-15 | editor.py:567-592 + vk_ui.py:792-900 | AUDIT-DOCIMPL / DESIGN-DRIFT | 交接文档 §6.1 的根因「GL 会把 canvas 尺寸跟窗口同步」与代码不符；两端都用窗口像素直接命中 canvas 坐标 |
| P-02-16 | game_player.py:45-71 | IFACE-VERSION | `_Tee` 缺 `encoding/fileno/buffer`，第三方库（Nuitka/pygame/wgpu）若访问会 AttributeError |
| P-02-17 | game_player.py:38-84 | OVERFIT-TESTENV | 打包版（无控制台、Program Files 只读目录）下 open(日志.txt)/faulthandler 的真实行为未知 |

### 1.2 跳过登记表（四类可审计理由）

| 跳过项 | 位置 | 理由类别 | 出处 |
|---|---|---|---|
| 双后端 gamma/交换链格式、阴影容量、描边像素差 | vk_renderer.py 主 pass 区域 | ④工具/框架自身声明（已契约化差异） | `vk_ui.py:45-60` 与 `docs/handoff/...` §9.2「已知契约化差异」 |
| 物理桥/脚本/输入回调链（`_InputRetry`、`_chain_callback`） | vk_player.py:40-131,258-368 | ③已有回归测试覆盖 | `Loom/tests/test_vk_ui_input.py`、`test_vk_camera_align.py`（本轮未改这段，diff 无涉） |
| 键位表 `_KEYMAP`/`_GLFW_TO_PG` 扩容 | loom_input.py、loom_glfw_window.py | 不属我的文件范围 | 任务书文件清单 |
| `game_settings.read_bool` 对 `"false"` 字符串的处理 | game_settings.py:77-85 | ②契约明确声明 | `game_settings.py:64-74` 注释声明支持 bool/str/num 三形态，`"false"→False` 符合声明 |
| `set_value` 写临时文件 + os.replace 的原子性 | game_settings.py:52-61 | ①语言/标准库规范 | `os.replace` 同目录原子替换（Python 文档） |
| `write_render_api` 对非法值的拒绝 | game_settings.py:152-161 | ①白盒契约声明 | 函数文档「render_api 必须是 vulkan/opengl/auto」 |
| `_release_cursor` 里 `ctypes.windll` 在非 Windows 抛 AttributeError | vk_player.py:513-521 | ②契约声明 | 调用点包在 `try/except Exception: pass`，且项目仅发布 Windows 包 |
| `draw()` 内 `canvas.close()` 后 rendercanvas 仍 present 一次（日志噪声） | vk_player.py:487 | ③框架自身声明 | `base.py:588 log_exception("Present init error")` 明确「报告并继续」 |

（说明：粗筛共 18 疑似 + 8 跳过；疑似项数量约为本模块公开函数数的 0.6 倍，未超协议上限。）


## 2. 逐项裁决

### 2.1 P-02-01 [REGRESSION] 游戏配置写失败被 `or True` 掩盖 → Q6「持久化回退」失效、可形成崩溃循环

**1) 位置**　`Loom/run_player.py:85-105`（`_persist_backend`）、`Loom/run_player.py:121-126`（`_handle_vk_init_failure`）。本轮 diff 把 `return True` 改成 `return ok_game or True`（见 `git diff f53a82a..HEAD -- Loom/run_player.py`）。

**2) 契约/预期**　C1 第 2b 条：「把配置里的 backend 写成 opengl（持久化，只写一次，避免每次启动都崩）」+ C2 优先级「游戏设置.json > 引擎 设置.json」→ 因此**真正决定下次启动的是游戏设置.json**；它写失败必须被如实上报（C1 要求的「不静默、不掩盖」）。

**3) 反手（证伪）：枚举 `_persist_backend` 返回值的全部路径**

| 路径 | 条件 | 代码事实 | 返回值 | 是否符合契约 |
|---|---|---|---|---|
| R1 | game 写成功，engine 写成功 | 88-89 / 100 | `ok_game or True` = True | ✔ |
| R2 | game 写失败，engine 写成功 | 88-91 打印失败 → 100 覆盖 → 101 | `False or True` = **True** | ✘ 应报 False |
| R3 | game 写抛异常，engine 写成功 | 92-93 → 100-101 | `False or True` = **True** | ✘ |
| R4 | engine 写抛异常 | 102-105 | **False** | ✔ |

R1/R4 正确，R2/R3 恒为 True —— `or True` 使 `ok_game` 在布尔结果中不起任何作用（AUDIT-DEADCODE：`if not ok:` 只在 R4 触发）。**反手失败**：存在一条（且是真实部署最常见的「游戏目录不可写」）路径会产生疑似行为。

**4) 正手（证真）：最小复现**　探针 PR-1 的 S2：LOOM_GAME_DIR 指到临时游戏目录，写入 `游戏设置.json={"render_api":"vulkan"}`，把 `game_settings.write_render_api` 换成返回 `(False, None, 'PermissionError')`，再调 `run_player._handle_vk_init_failure(RuntimeError(...), False)`。

**5) 实际（实测输出）**

```
--- S2 游戏配置写失败 ---
S2 起始 | 游戏设置.json=vulkan 设置.json=opengl
[run_player] 写游戏配置失败: PermissionError 目标不可写
[run_player] Vulkan 后端不兼容（no vulkan device），已把设置回退为 OpenGL，下次启动将使用 OpenGL
S2 SystemExit code = 1
S2 写后 | 游戏设置.json=vulkan 设置.json=opengl
S2 下次启动 resolve_backend() = vulkan   <== 判定点: 是否真的回退了 OpenGL
S2 _persist_backend("opengl") -> True  (ok_game=False, 引擎写成功)
```

同一探针的 S1（两份都可写）对照：`游戏设置.json=opengl 设置.json=opengl`、`下次启动 resolve_backend() = opengl` —— 说明 R1 通、R2 不通，差异只在「游戏配置是否写得进」。

**6) 差异分析**　少做了：没有把「决定性的那个文件写失败」转成 False/告警；多做了一件：向用户承诺「下次启动将使用 OpenGL」。后果链：下次启动 `resolve_backend()`（run_player.py:68-73 先读游戏配置）→ 仍 vulkan → 再次 VkInitError → 再次回退失败 → **每次启动都崩**，正是 C1 第 2b 条要避免的场景。

**7) 可复现验证**　`cd <repo> && python Loom/tests/_tmp/beta3_scan_02_probe_q6.py`（贴上面 S2 段）。反向验证既有回归测试为何没抓到：`python Loom/tests/test_backend_fallback_policy.py` → `ALL PASS`，因为该测试 `_Harness` 只写 `设置.json`、并且只断言「设置.json render_api 已写成 opengl」（`test_backend_fallback_policy.py:146`），**从不调用 `resolve_backend()` 验证「下次启动真的用 OpenGL」**。这属于「已有回归测试覆盖」被证伪：测试覆盖的是写日志/写设置，不是 C1 的承诺。

**8) 影响与等级**　P1（功能错误 + 可导致「永远起不来」的循环）。触发条件：游戏文件夹不可写（Program Files 安装、只读介质、被杀软锁）且游戏配置里是 vulkan。

**建议修复方向（方向，不含实现）**：`_persist_backend` 的返回值应以「决定下次启动的那个文件是否写成功」为准（game 优先，engine 只作兜底），不要用 `or True` 短路；`_handle_vk_init_failure` 里「宣布成功」的文案必须在拿到 ok 之后再打印，ok=False 时改成明确的失败提示。**必须保持的契约**：C1 全部四条（尤其 4「显式 --backend vulkan 不改写」实测已满足，见 P-02-01 附表 S4）。**波及调用方**：`vk_player` 不调用；`game_player._run_backend_safe` 靠 SystemExit 传播，不依赖返回值；`test_backend_fallback_policy.py` 的 5 条断言会受影响（需同步扩测）。

### 2.2 P-02-02 [REGRESSION] 「已回退为 OpenGL／下次启动将使用 OpenGL」先于 ok 判断打印

**1) 位置**　`run_player.py:121-125`。
**2) 契约**　C1 第 2a+2b：提示必须描述真实后果（「不静默、不掩盖」，`_scan_summary.md` §6 原话）。
**3) 反手**　枚举 `_handle_vk_init_failure` 的两条分支：(a) `explicit=True` → 118-120，文案「不改写设置，直接报错退出」与实际一致（实测 S4：目录无变化、SystemExit(1)、`resolve_backend()` 仍 vulkan）→ 该分支无问题；(b) `explicit=False` → 121 `ok=_persist_backend(...)`，122-123 **无条件**打印「已把设置回退为 OpenGL，下次启动将使用 OpenGL」，124-125 才 `if not ok:`。当 R2/R3（P-02-01）时 ok 恒 True，`if not ok` 是死分支，于是「宣布成功 + 无任何告警」。反手失败。
**4) 正手/5) 实际**　同 P-02-01 的 S2 输出：先打印「已把设置回退为 OpenGL，下次启动将使用 OpenGL」，紧接着（真实）`resolve_backend() = vulkan`；**全程没有**「设置写入失败」告警（该告警在 S3 才出现，因为 S3 让 engine 写也抛异常）。
**6) 差异**　提示语与事实相反，且缺少任何降级告警。
**7) 验证**　`python Loom/tests/_tmp/beta3_scan_02_probe_q6.py`，对比 S2（无告警，但下次仍 vulkan）与 S3（有告警：「设置写入失败…请手动把 设置.json 的 render_api 改成 opengl」）。
**8) 等级**　P2（误导性诊断；单独出现不会崩，但与 P-02-01 叠加时让崩溃循环完全无痕迹）。

**建议修复方向**：把「结论性文案」移动到 `ok` 判定之后；写失败时给出可执行的补救路径（真实文件路径 + 手动改法），而不是笼统的「设置写入失败」。契约同上。

### 2.3 P-02-03 [REGRESSION] 旧 `游戏配置.json` 的 render_api 仍压过新 `游戏设置.json` → Q6 写回在旧发布夹里被作废

**1) 位置**　`game_player.py:123-136`（`_pick_backend` 读 `<exe>/游戏配置.json` 并把它作为 `requested` 传入）+ `run_player.py:51-75`（`requested` 优先级最高、并把 `_LAST_SOURCE` 标成 `cli`）。本轮 5b453b3 新增了「每游戏 游戏设置.json」这一层，但**没有处理旧文件的优先级**。

**2) 契约**　C2 只声明三层：CLI > 游戏设置.json > 引擎 设置.json > 默认。「`游戏配置.json` 的 render_api」不在 C2 里，却抢到了比 CLI 之下的第一优先级；同时 C1-2b 要求「写回的配置下次启动生效」。

**3) 反手**　枚举打包玩家的后端解析路径：

| 路径 | 是否有 游戏配置.json | `requested` | 结果 |
|---|---|---|---|
| A | 无（build_game 新式散装包，只有 游戏包.lsc） | None | 走 游戏设置.json ✔ |
| B | 有且无 render_api 键 | None | 走 游戏设置.json ✔ |
| C | 有且 render_api=vulkan | 'vulkan' | **压过 游戏设置.json** ✘ |

路径 C 由旧发布夹/旧示例游戏触发（`Loom/tests/_tmp/make_demo_game.py:47` 就写这种文件）。反手失败。

**4) 正手/5) 实际（PR-6 实测）**

```
=== B) 旧 游戏配置.json vs 新 游戏设置.json ===
  游戏配置.json render_api=vulkan (旧) + 游戏设置.json render_api=opengl (新)
  _pick_backend() -> vulkan
  resolve_backend(_pick_backend()) -> vulkan | _LAST_SOURCE = cli
```

**6) 差异**　Q6 明明把 `游戏设置.json` 写成 opengl（`game_settings.write_render_api('opengl')` 已成功），下次启动仍取 vulkan → 崩溃循环；且 `_LAST_SOURCE` 谎报来源为 `cli`（用户没传任何参数）。

**7) 验证**　`python Loom/tests/_tmp/beta3_scan_02_probe_confprec.py`（B 段）。

**8) 等级**　P1（功能错误；与 P-02-01 组合即为「每次启动都崩」）。仅影响带旧 `游戏配置.json` 的发布夹与旧示例。

**建议修复方向**：让一个概念只有一个文件——把旧 `游戏配置.json` 的 `render_api` 读入后**降级**为「未显式」来源（不得抢占比 游戏设置.json 更高的优先级），或做一次迁移写进 游戏设置.json 并从旧文件删除该键（迁移只做一次）。**必须保持的契约**：C2 三层优先级、C1-4「显式 --backend 不改写」、旧发布夹仍能双击启动（scene 键语义不能丢）。**波及**：`game_player._pick_backend`、`run_player.resolve_backend` 的 `_LAST_SOURCE`、`test_render_api.py:153-190`（其断言的就是「游戏配置.json > 设置.json」这条**将失效**的优先级，需同步改测）。

### 2.4 P-02-04 [REGRESSION] 同一场景 camera.fov：GL 75° / VK 恒 60°（本轮新增分叉）

**1) 位置**　GL 侧 `runtime.py:59-67`（本轮新增：把 `cam_out['fov']` 写进 `self._fov`）；VK 侧 `scene_driver.py:574-589`（本轮新增 576 行从 `cam.get('fov')` 读入，但 **589 行无条件复位 `self.fov = radians(60.0)`**）。

**2) 契约**　C3：场景 camera 段的 fov「播放时强制套用」；C4：同一场景两后端等价。

**3) 反手**　枚举 VK 侧 `self.fov` 的赋值点：576（读场景 fov）→ 589（**无条件**复位 60°）→ 595 `apply_camera(_ac)`（仅当场景有 active_camera 物体时用相机自身 fov 覆盖，`scene_driver.py:1262`）。因此只有「有 active_camera 物体」时场景 fov 才生效；**轨道相机场景（无 cameras/active_camera）恒 60°**。反手失败：存在一条被 589 行吃掉的路径。基线对照 `git show f53a82a:Loom/scene_driver.py` 该函数里只有 `self.fov = math.radians(60.0)`（基线 541 行），而基线 runtime.py 根本不读 fov → **基线两端一致（都 60°），HEAD 两端分叉**。

**4) 正手/5) 实际（PR-2 实测，同一份 scene dict：`camera.fov=75, 无 active_camera`）**

```
[VK] fov(deg)=60.0000 ortho=False ortho_size=13.0 orbit_mode=True mouse_lock_allowed=False mouse_locked=False
[GL] fov(deg)=75.0000 ortho=False ortho_size=13.0 orbit_mode=True mouse_lock_allowed=False mouse_locked=False
[IO] camera_out fov 提取 = 75.0 | runtime 会把它写进 _fov (=1.3090 rad)
[VK-ortho] ortho=True ortho_size=13.0
[GL-ortho] ortho=True ortho_size=13.0
```

**6) 差异**　同一场景 VK 视角 60°、GL 视角 75°；ortho/ortho_size 与鼠标锁定状态两端一致（这两项本轮实现正确）。

**7) 验证**　`python Loom/tests/_tmp/beta3_scan_02_probe_camera.py`。基线对比命令：`git show f53a82a:Loom/scene_driver.py | Select-String "fov"`（只有 60° 一处）与 `git diff f53a82a..HEAD -- Loom/runtime.py`（新增 fov 读取）。

**8) 等级**　P1（功能错误 / 双后端不等价）。触发：3D 轨道相机场景 + `camera.fov != 60`（2D ortho 吃豆人不受影响，因为 ortho 分支不用 fov）。

**建议修复方向**：VK 侧删掉 589 行那次「加载基线复位」，或把「读场景 fov」放在复位之后（两者取一，保持「无 camera 段 → 60°」的默认不变）。**必须保持的契约**：C3；`scene_driver.py:587-589` 注释所声明的「同 PlayerApp 的 self._fov 初值」语义（即场景无 camera 段时仍是 60°）；有 active_camera 时以相机自身 fov 为准。**波及**：`test_vk_camera_align.py`（相机对齐基线）、`tests/_tmp/ab_*.py` 的 A/B 基线（若某些场景 fov≠60，改后 VK 侧像素会变，属预期收敛而非回归）。


### 2.5 P-02-05 看门狗未闭环：窗口最小化 ≥60s 必被 `os._exit(9)` 硬杀；heartbeat 无停止条件

**1) 位置**　`vk_player.py:477`（`last_ok = [time.perf_counter()]`）、**482-493**（包装 draw，成功后 `last_ok[0] = time.perf_counter()`）、**499-505**（`while True: sleep(5); if 停滞>60: os._exit(9)`）。本轮 15718a5 的修复目标是「每成功渲染一帧就喂狗」。

**2) 契约**　C7：看门狗语义是「防卡死」，不是「窗口不可见也照杀」；`vk_player.py:503` 自己的文案就是这么写的。

**3) 反手（证伪）：枚举「哪些情况下 draw 不被调用而进程仍活着」**

| 路径 | draw 是否被调用 | last_ok 是否被喂 | 结论 |
|---|---|---|---|
| N1 正常渲染 | 是 | 是 | ✔ 已修好（本轮修复主体成立） |
| N2 逻辑暂停（`set_logic_paused`） | 是（只跳逻辑，不跳渲染） | 是 | ✔ 不会被误杀 |
| N3 `--frames N` 达标后 `canvas.close()` | 该帧内 return，随后循环结束 | 否（无需） | ✔ 进程随即退出 |
| N4 渲染循环内异常 | 抛异常 → `_loop_error` → 关窗 | 否（无需） | ✔ 主动结束，不是看门狗 |
| N5 **窗口最小化/不可见** | **否** | 否 | ✘ 60s 后被杀 |
| N6 run_vk 已返回但宿主进程仍存活 | 否 | 否 | ✘ 60s 后被杀（heartbeat 是 `while True`，永不退出） |

N5 的机制出处（第三方框架自身声明）：`rendercanvas/glfw.py:266-268` `_on_iconify → self._set_visible(not iconified)`；`rendercanvas/base.py:650-660` `_set_visible() → scheduler.set_enabled(visible)`（文档原文：「If not visible, frames are not rendered」）；`rendercanvas/core/scheduler.py:31-34`（「When the window is minimized, the draw will not occur until the window is shown again.」）。反手在 N5/N6 失败。

**4) 正手（证真）：最小复现**　PR-3 探针按 `vk_player.py:477/491-492/499-505` 逐行同构搭台（只把 `os._exit(9)` 换成记录），用真实 `GlfwRenderCanvas` + `glfw.iconify_window()` 最小化。

**5) 实际（8s 冒烟 + 70s 判定两次实测）**

```
# 8s 冒烟
[probe] 最小化前: 帧数=2967 (2s 内已渲染)
[probe] 最小化 8s: 帧数 2967 -> 2967 (增量 0); last_ok 停滞 8.0s
[probe] 恢复后 2s: last_ok 停滞 0.00s, 帧数=5749

# 70s 判定（跨过 60s 阈值）
[heartbeat] WOULD_CALL os._exit(9): 渲染无进展 63.0s > 60s (t=65.0s)
[probe] 最小化 70s: 帧数 2917 -> 2917 (增量 0); last_ok 停滞 70.0s
[probe] 恢复后 2s: last_ok 停滞 0.00s, 帧数=5663
[probe] heartbeat 触发记录 = [65.0]
```

**6) 差异**　渲染确实完全停（增量 0），但进程**仍活着**；按 `> 60s` 判据在 t≈65s 必然触发 `os._exit(9)`。玩家最小化/被完全遮挡超过 1 分钟即丢存档式硬杀；且 `os._exit` 连 `finally` 都不执行（P-02-13）。

**7) 验证**　`python Loom/tests/_tmp/beta3_scan_02_probe_watchdog.py 8` 与 `... 70`。另可佐证 N6：`python Loom/tests/_tmp/beta3_scan_02_probe_quit.py` 在 `run_vk` 正常返回后（3.89s）仍于 t≈60s 打印 `watchdog: 渲染无进展 60s, 强制退出 (防卡死)` 并以 `EXIT=9` 结束（该探针的计时器线程是探针自身造成的存活，故 N6 只算**代码事实**：heartbeat 无退出条件）。

**8) 等级**　P1（非本轮引入，但本轮宣称「修掉引擎级 P0：VK 看门狗 60 秒必杀」（`接手总纲` §2.7）→ 属 DOCIMPL：修了一半）。最小化是普通玩家动作，命中即进程被杀，按「崩溃」口径可升 P0。

**建议修复方向**：把看门狗的判据从「无帧」改成「不可见不算停滞」——在喂狗处同时接受「画布不可见/最小化」这一合法状态（例如监听 iconify/gui-poll 状态或让 heartbeat 读画布可见性），并给 heartbeat 一个退出条件（渲染循环结束时置位，避免宿主进程存活就被杀）。**必须保持的契约**：C7（真卡死仍要杀）、`os._exit` 只在真停滞时使用、不能改成「永不触发」（否则回到「假死不退」）。**波及**：`--frames`/`--keep` 探针路径、任何未来嵌入 run_vk 的宿主（`Loom.py` 与 `game_player` 目前都在 run_vk 返回后立即 `sys.exit`，所以 N6 暂不显形）。

### 2.6 P-02-06 `python run_player.py` 入口：VkInitError 双类身份 → Q6 回退链整体不执行

**1) 位置**　`vk_player.py:35` `from run_player import VkInitError, VkRunError` + `run_player.py:143-146` `except VkInitError as e: _handle_vk_init_failure(e, explicit)`。

**2) 契约**　C1 第 2a/2b 条必须在该入口成立；`run_player.py:10` 文档串把 `py -3.12 run_player.py <场景.json> [--backend ...]` 写成正式用法。

**3) 反手**　枚举入口：(a) `Loom.py --run` → `from run_player import resolve_backend, run_backend`（Loom.py:112）→ 模块名 `run_player`，与 vk_player 内 `import run_player` 同一对象 → 类身份一致 ✔；(b) `game_player` → `import run_player`（game_player.py:157/223/234）→ 一致 ✔；(c) `python run_player.py` → 该文件是 `__main__`，vk_player 的 `from run_player import ...` 会**第二次执行** run_player.py，得到另一个模块对象 → 两个 `VkInitError` 类 ✘。反手在 (c) 失败。

**4) 正手/5) 实际（PR-4 实测，用 exec 以 `__main__` 身份执行真实 run_player.py 源码）**

```
__main__ 版 VkInitError id = 2700071507744 | __module__ = __main__
import run_player 与 __main__ 是同一模块对象 ? False
run_player.VkInitError is __main__.VkInitError ? False
vk_player.VkInitError is __main__.VkInitError ? False
vk_player.VkInitError is run_player.VkInitError ? True
捕获结果: 未被 __main__ 版 except 接住 -> 冒泡为 VkInitError: simulated: vulkan init failed
```

**6) 差异**　在 CLI 入口，`except VkInitError` 永不命中 → 不打印「Vulkan 后端不兼容…已回退」、不写任何配置（2a/2b 全失效），只剩未捕获 traceback（**退出码仍非零**，2c 形式上满足）。

**7) 验证**　`python Loom/tests/_tmp/beta3_scan_02_probe_dupmodule.py`。

**8) 等级**　P2（非本轮引入的机制，但使本轮 Q6 的「持久化回退」在文档化的 CLI 入口完全不生效；玩家/开发者最常用的还是 exe 双入口，故不升 P1）。

**建议修复方向**：把两个异常类搬到不依赖入口身份的模块（或让 run_player 在 `__main__` 情况下也注册别名），使「按名字 import」与「作为脚本运行」拿到同一个类；不要用「把 except 放宽成 Exception」来绕过（会破坏 P-10 的段划分）。**必须保持的契约**：初始化失败=可回退信号、循环内失败=VkRunError 不可回退、显式 vulkan 不改写。**波及**：`run_player` 的三个入口、`test_backend_fallback_policy.py`（可加一条「以 __main__ 运行」的回归）。

### 2.7 P-02-07 [REGRESSION] `游戏设置.json` 落点 = dirname(argv[0])：源码目录 `--run` 与测试进程都会把「引擎目录」当「游戏目录」

**1) 位置**　`game_settings.py:20-35`（`game_dir()`：LOOM_GAME_DIR > `dirname(abspath(sys.argv[0]))` > cwd）、`run_player.py:66-70`（`_game_api()` 优先读它）。

**2) 契约**　`game_settings.py:4-5` 文档：「落盘位置：**游戏文件夹**（打包后 = MyGame.exe 同级）」。

**3) 反手**　枚举调用者：(a) 打包游戏 exe → argv[0]=MyGame.exe → 游戏夹 ✔；(b) `Loom.py --run` / `python run_player.py` → argv[0] 在引擎源码目录 → 落点 = `Loom/游戏设置.json` ✘；(c) 测试进程（argv[0]=测试脚本）→ 落点 = `Loom/tests/游戏设置.json` ✘。反手失败。

**4) 正手/5) 实际（PR-6 A 段 + PR-9 副产品）**

```
=== A) game_dir 落点 ===
  argv[0]=...\Loom\run_player.py -> ...\Loom\游戏设置.json
  argv[0]=...\Loom\Loom.py      -> ...\Loom\游戏设置.json
  argv[0]=D:\game\MyGame.exe    -> D:\game\游戏设置.json
  LOOM_GAME_DIR 生效 -> %TEMP%\loom_conf_xxx\game\游戏设置.json
```

以及跑既有测试的副产品（`git status --porcelain` 直接可见）：

```
?? Loom/tests/日志.txt
?? Loom/tests/游戏设置.json        # 内容 {"render_api": "opengl"}
```

**6) 差异**　一旦有人在源码目录跑过一次 `--run`（或某次 Vk 初始化失败触发写回），`Loom/游戏设置.json` 就被创建并**永久压过** `Loom/设置.json`（C2 优先级），之后所有 `--run` 的后端都被这个文件粘住；测试进程更是把 opengl 写进测试目录，污染后续所有在该目录启动的进程。

**7) 验证**　`python Loom/tests/_tmp/beta3_scan_02_probe_confprec.py`（A 段）；`python Loom/tests/test_backend_fallback_policy.py` 后 `git status --porcelain Loom/tests`。

**8) 等级**　P2（环境/仓库污染 + 后端被粘住；影响开发与 CI，不影响已发布游戏的玩家）。

**建议修复方向**：区分「游戏夹」与「程序目录」——只有在存在游戏包/游戏配置的语境下才启用 游戏设置.json；非游戏语境（源码 `--run`、headless 测试）回落到引擎 设置.json 或显式开关（如要求 LOOM_GAME_DIR）。测试侧应默认设置 LOOM_GAME_DIR 到临时目录（与 `_SETTINGS_BASE` 同等对待）。**必须保持的契约**：C2 优先级、C6（游戏配置驱动鼠标锁定/键位）、打包游戏仍从 exe 同级读配置。**波及**：`run_player._game_api`、`scene_driver`（键位/鼠标锁定读同一路径）、`engine.set_render_api`、所有测试。

### 2.8 P-02-08 [REGRESSION] `game_player._bootstrap_logging()` 在模块级执行：import 即改写 stdout/stderr 并创建 `日志.txt`

**1) 位置**　`game_player.py:31-84`（函数定义 + 第 84 行模块级调用 `_bootstrap_logging()`）。

**2) 契约**　`game_player.py:32` 文档：「打包版无控制台，崩溃信息全丢 → 落盘到 exe 旁 日志.txt」——限定语境是**打包版**；模块文档（1-23）声明本模块是「纯 Player 游戏入口」。

**3) 反手**　枚举执行时机：`game_player` 作为脚本运行 → 合理 ✔；被 `import game_player`（`test_backend_fallback_policy.py:205`、`test_render_api.py:157`、`test_wheel_backend_semantics.py:244/310`、`tests/_tmp/*`）→ 同样执行 ✘。反手失败（模块级副作用不可选）。

**4) 正手/5) 实际（PR-9）**　跑既有 Q6 测试后：

```
===== 启动 2026-11-08 12:15:16 | exe=Loom\tests\test_backend_fallback_policy.py =====
?? Loom/tests/日志.txt
```

该测试本身并不想写日志，却把测试输出（含 PASS/FAIL 行）复制进 `日志.txt`，并把**测试进程**的 sys.stdout/sys.stderr 换成 `_Tee`。

**6) 差异**　(a) 导入即产生仓库/磁盘副作用；(b) 日志 append 且无上限、无轮转（游戏目录长期运行会无限增长，见 `game_player.py:43` `open(path,'a')`）；(c) `_Tee` 只实现 write/flush/isatty，缺 `encoding/fileno/buffer`（见 P-02-16）。

**7) 验证**　`python Loom/tests/test_backend_fallback_policy.py` 后 `git status --porcelain Loom/tests`（上面已贴）；`Get-Content Loom/tests/日志.txt -TotalCount 6`。

**8) 等级**　P2（测试污染 + 资源增长；打包版玩家侧行为尚可接受）。

**建议修复方向**：把日志引导从模块级挪到「确定自己是玩家进程」的位置（`if __name__ == '__main__'` 或 main() 首行），并对非打包/非脚本调用保持零副作用；给 `日志.txt` 加上限（按大小截断/轮转一次）。**必须保持的契约**：打包版崩溃可取证（traceback + faulthandler 栈仍要落盘）、`--windows-disable-console` 下不得因日志引导失败而崩溃（现有 `try/except` 兜底必须保留）。**波及**：全部 import game_player 的测试；`build_entry.py` 若复用本模块需确认。


### 2.9 P-02-09 `_read_setting` 忽略 `_SETTINGS_BASE`（读写隔离不对称）

**1) 位置**　`run_player.py:30-36`（读，无 base）vs `run_player.py:96-100`（写，有 `base=_SETTINGS_BASE`）。
**2) 契约**　`run_player.py:26-27` 注释：「测试用: 设置.json 所在目录 (None = guiloader 默认)」——注释语义是「设置所在目录」，应同时作用于读写；`test_backend_fallback_policy.py:100,117` 也依赖它把设置指到临时目录。
**3) 反手**　枚举 `_SETTINGS_BASE` 的使用点：只有 `_persist_backend`（96、100 行）；`_read_setting`（33 行）完全不看它 → 反手失败（隔离只覆盖写）。
**4) 正手/5) 实际（PR-6 C 段）**

```
=== C) 读写隔离: _SETTINGS_BASE 只对写生效? ===
  _read_setting(render_api) = vulkan  (临时目录里写的是 opengl)
  写后 临时目录 设置.json = opengl
```

**6) 差异**　写进临时目录，读却读真实程序目录（此处是 `Loom/设置.json`，其 render_api=vulkan）。**7) 验证**　`python Loom/tests/_tmp/beta3_scan_02_probe_confprec.py`（C 段）。
**8) 等级**　P3（测试基础设施缺陷；当前测试都用显式 api 调 `run_backend`，所以没造成假绿，但后续任何「先写后读」的用例会读到真实配置）。

**建议修复方向**：读路径同样传 `base=_SETTINGS_BASE`，让一个变量同时控制读写；或用统一的 `_settings_path()` 助手。契约：不改生产默认行为（`_SETTINGS_BASE=None` 时仍指程序目录）。波及：`resolve_backend` 的 engine 分支。

### 2.10 P-02-10 `_LAST_SOURCE` 只写不读（死变量）

**1) 位置**　`run_player.py:39、61-73`。**2) 契约**　该变量的注释「本次后端来自哪: cli / game / engine / default」暗示要对外可见；`run_player.py:66-67` 的注释也把它当作可观测事实。
**3) 反手**　`grep -n _LAST_SOURCE Loom/*.py` → 只有定义与 3 处赋值，无任何读取点（唯一读取出现在我自己的探针里）。反手失败。
**4) 正手**　最小复现即上面那条 grep（无需运行）；`_handle_vk_init_failure`/`game_player` 都不用它。
**5) 实际**　值永远不被消费 → 既不能用于日志，也不能用于「显式 vs 设置」判定（真正的 explicit 判定走 `explicit` 形参）。**6) 差异**　注释承诺的可观测性不存在。
**7) 验证**　`Select-String -Path Loom\*.py -Pattern "_LAST_SOURCE"`。**8) 等级**　P3（可维护性；但正是它掩盖了 P-02-03 的「来源误标 cli」）。

**建议修复方向**：要么在 `_handle_vk_init_failure` 的提示里真正输出它（让 Q6 提示能说清「是配置要的 vulkan 还是你显式要的」），要么删除以免误导。契约：C1 提示不得含糊。

### 2.11 P-02-11 request_quit → 关窗 → run_vk 正常返回（**DISPROVED**：无异常、退出码正常）

**1) 位置**　`vk_player.py:479-493`（包装 draw 里先判 `driver.request_quit` → `canvas.close()` → `return`）、`vk_player.py:523-533`（`finally: _release_cursor()`，随后若 `_loop_error` 为 None 则正常返回）、`scene_driver.py:648-650`（`request_game_exit` 置位）。
**2) 契约**　C1-2c 的「非伪成功」反面：脚本主动退出属正常结束（GL 侧 `engine.request_game_exit` 也是 `self._running=False`，`engine.py:838-844`）。

**3) 反手（枚举可能出问题的点）**

| 子猜想 | 结果 |
|---|---|
| A 关窗后仍继续渲染 → 后续 `draw` 访问已销毁的 ctx 抛异常 | 不成立：`canvas.close()` 后 rendercanvas 不再调度（`base.py:570-578` 的取消分支），且本帧内已 return |
| B 关窗顺序导致 `run()` 不返回/挂死 | 不成立：实测 5 帧内返回 |
| C 退出时被误判为循环内失败（`_loop_error`）抛 VkRunError → 非零退出 | 不成立：`_loop_error` 仅在异常分支写入（`vk_player.py:454-468`） |
| D `finally` 里释放光标在窗口已销毁时抛异常 | 不成立：`SceneDriver.set_mouse_locked → cb(_apply_cursor_mode)` 内部对 `glfw.*` 全部 `try/except`（`vk_player.py:340-352`） |

**4) 正手（尝试证真）**　PR-7：真实 `run_vk(mini=True)`，在第 5 次 `advance_logic` 后置 `request_quit=True`。实际输出：

```
=== Vk 播放 (物体 1) | 帧数 5 | 172.666 ms/帧 | FPS 5.8 ===
[quit] ret=None exc=None frames=5 elapsed=3.89s
[quit] 判定: 正常返回 = True
```

**5) 差异**　无（证真失败：既没有异常也没有挂死，`run_vk` 返回 `None` = 最后一帧 FPS 占位，符合 `run_vk` 返回约定）。
**6) 触发条件**　脚本调用 `engine.request_game_exit()`（`scripts/pacman_player.py:112-113` 的「退出游戏」按钮就走这条）。**7) 验证**　`python Loom/tests/_tmp/beta3_scan_02_probe_quit.py`。
**8) 结论/等级**　**DISPROVED**（关窗顺序与退出码在进程内是正确的：返回 → 上层返回 → 进程以 0 退出）。唯一遗留是「返回后 heartbeat 仍在跑」，已归入 P-02-05 的 N6。

### 2.12 P-02-12 draw 包装签名改 `*a/**k` 是否掩盖参数错误（**DISPROVED**）

**1) 位置**　`vk_player.py:482-493`。**2) 契约**　`rendercanvas` 的 draw 回调约定（`rendercanvas/base.py:439-444`：`_draw_frame`「The method to call to draw a frame」，实际调用点 `base.py:588-596` 为 `self._draw_frame()`，**无实参**）。
**3) 反手**　枚举可能被掩盖的错误：(a) 调用方多传参数 → 包装把参数原样转发给 `_orig_draw`，若真多传会在 `_orig_draw` 抛 TypeError，异常**不在**包装的 try 内（try 只包 `request_quit` 判断），会冒泡进 `base.py:588 log_exception("Draw error")` 并被打印（打包版还会 tee 进 日志.txt）→ 不会静默；(b) 调用方少传参数 → 同样冒泡；(c) `*a/**k` 让签名检查消失 → 只是把「导入期报错」推迟到「首帧报错」，仍可见。
**4) 正手**　无法构造「静默失败」的最小复现：删掉副作用的唯一途径是包装**吞掉**异常，而包装只在 `request_quit` 判断上 try/except（`getattr` 不会因签名问题抛）。证真失败。
**5/6) 差异**　无。**7) 验证**　`Select-String -Path <site-packages>/rendercanvas/base.py -Pattern "_draw_frame\(\)"`（第 590 行）+ 上面的 `run_vk` 实跑（正常渲染 5 帧、无 TypeError 日志）。
**8) 结论/等级**　**DISPROVED**。附一条正向说明：这个包装同时修掉了真实缺陷——旧写法固定 `_orig_draw(dt)` 会撞上 `draw()` 无参签名（`87b2977` 的提交说明记录了该 Draw error）。

### 2.13 P-02-13 `_release_cursor` 覆盖路径（含崩溃/os._exit）（**DISPROVED 用户影响**）

**1) 位置**　`vk_player.py:507-528`。**2) 契约**　C5：退出必须释放鼠标捕获（`e848afc`）。
**3) 反手（枚举全部退出路径）**

| 路径 | `finally` 是否执行 | 光标是否释放 |
|---|---|---|
| 正常关窗 / 关面板退出 | ✔ | ✔ |
| `KeyboardInterrupt` | ✔（except 后 finally） | ✔ |
| `run()` 抛异常 | ✔ | ✔ |
| `VkRunError` 抛出点（532） | 在 finally 之后 | ✔ 已释放 |
| 初始化段失败（未注册输入/未锁） | 无需 | ✔（本来没锁） |
| **`os._exit(9)`（看门狗，P-02-05）** | ✘ | 代码层面✘ |

**4) 正手（尝试证真）**　PR-8：子进程 `CURSOR_DISABLED` 后 `os._exit(9)` 模拟看门狗，父侧再用 `GetClipCursor`/`GetCursorInfo` 观测。实测：

```
[cursor] state = {'clip': (0, 0, 1536, 864), 'screen': (1536, 864), 'clip_is_fullscreen': True, 'cursor_showing': True}
[cursor] 锁定后 state = {'clip': (41, 70, 281, 250), 'screen': (1920, 1080), 'clip_is_fullscreen': False, 'cursor_showing': False}
[cursor] 现在 os._exit(9) 模拟看门狗 (finally 不执行)
EXIT=9
[cursor] state = {'clip': (0, 0, 1536, 864), 'screen': (1536, 864), 'clip_is_fullscreen': True, 'cursor_showing': True}
```

**5) 差异**　锁定期确实建立了裁剪区（clip=窗口矩形）并隐藏了光标；子进程被 `os._exit(9)` 杀掉后，系统**自动恢复**为全屏裁剪 + 光标可见 → **用户不可见残留**。证真失败。
**6) 触发条件**　仅 `os._exit`/被强杀路径（正常路径已验证释放）。**7) 验证**　`python Loom/tests/_tmp/beta3_scan_02_probe_cursor.py check|lock|check|restore`。
**8) 结论/等级**　**DISPROVED**（无用户影响）；但「finally 在 os._exit 下不执行」是语言事实，若将来去掉看门狗或宿主进程共享桌面，建议在 `os._exit` 之前先显式释放一次（低成本保险）。


### 2.14 P-02-14 VK 侧 `script_host` 转发链完整性与 GL 语义等价（**DISPROVED**：转发链已打通）

**1) 位置**　`vk_ui.py:321-331`（`VkUIEngine.draw_all(ui_manager, script_host=None)` → `ui_manager.draw_all(self, script_host=script_host)`）、`vk_renderer.py:1029-1055`（`draw_ui(..., engine=None)` → `eng.draw_all(ui, script_host=engine)`）、`vk_renderer.py:1748-1752,1993-1998`（`draw_frame(..., engine=None)` 透传）、`vk_player.py:448-453`（生产调用点 `engine=driver`）、`loom_ui.py:694-706`（`_ACTIVE_ENGINE = script_host if script_host is not None else engine`）。

**2) 契约**　C8/C9：`_ACTIVE_ENGINE` 必须是脚本宿主（有 `.models`），绘制目标另给。

**3) 反手（枚举四处必须同时成立的点）**：① vk_player 真的传了 engine？→ `vk_player.py:449`（本轮 diff `+engine=driver`）✔；② draw_frame 真的把 engine 传给 draw_ui？→ `vk_renderer.py:1996-1997` ✔；③ draw_ui 真的传给 VkUIEngine.draw_all？→ `vk_renderer.py:1054` ✔；④ UIManager 真的把它当脚本宿主？→ `loom_ui.py:706` ✔。另需 ⑤ SceneDriver 的 models/scripts 形态满足 `_find_script_instances`（`loom_ui.py:23-41` 读 `m.scripts`、`sc.script_id`、`sc._script`）→ `scene_driver.py:977-1004` 正是这一形态。四条链 + 数据形态均成立 → 反手**成功**（这就是「不应该有 bug」的路径枚举）。

**4) 正手（尝试证真）：最小复现**　PR-5：构造真实 `SceneDriver`（1 个挂 `pacman_player` 的物体）+ 真实 `UIManager`（Button 绑 `on_quit`），走 A/B/C/D 四步。

**5) 实际（实测输出）**

```
model.scripts = [('pacman_player', 'PacmanPlayerScript')]
A) VkUIEngine.draw_all 转发: engine=VkUIEngine, script_host is driver=True
B) _ACTIVE_ENGINE is driver ? True
C) _find_script_instances(pacman_player) 命中数 = 1
C) _fire_binding(click) = True | on_quit 调用次数 = 1
D) 不传 script_host -> _ACTIVE_ENGINE 类型 = DrawEngine | 有 models 属性 = False | _find_script_instances 命中数 = 0
```

**6) 差异**　无：A/B/C 全部成立（本轮 08649e6 的 P0 修复有效，且与 GL 侧 `loom_render.py:821 self.ui.draw_all(self)`（engine==script_host）在语义上等价：GL 用「引擎自己就是宿主」，VK 用「显式宿主」，`_ACTIVE_ENGINE` 最终都指向含 `.models` 的对象）。

**7) 验证**　`python Loom/tests/_tmp/beta3_scan_02_probe_uibridge.py`。

**8) 结论/等级**　**DISPROVED**（转发链完整、事件派发在 VK/GL 两侧语义等价）。

### 2.15 P-02-14b `script_host` 缺省 = self 的「陷门」仍然存在（**PROVED**，潜伏）

**1) 位置**　`vk_ui.py:321-331`（`script_host=None` 时 `ui_manager.draw_all(self, script_host=None)`）+ `loom_ui.py:706`（`else engine`）。
**2) 契约**　C8。**3) 反手**　枚举现有调用方：`grep -n "draw_all(" Loom/*.py` → 生产路径只有 `vk_renderer.py:1054`（带 script_host）与 GL 的 `loom_render.py:821`（engine 即宿主）→ 当前**无**触发者，反手在「现状」上成立、在「未来」上不成立。
**4) 正手/5) 实际**　PR-5 的 D 步即最小复现：不传 `script_host` → `_ACTIVE_ENGINE` = 绘制桩、`hasattr(models)=False`、`_find_script_instances` 命中 0。这与 `_scan_summary.md` §2.7 记录的原始 P0 现象完全一致（「打包版 UI 按钮点不动”）。
**6) 差异**　同一处代码既支持正确用法也支持「正确编译、错误运行」的旧用法，且默认值站在错误一侧。
**7) 验证**　同 PR-5。**8) 等级**　P3（当前无生产触发者；`Loom/tests/_tmp/ab_gl_vk_ui.py:172` 仍在无 engine 的形态下调用，若它将来被用作事件回归基线会静默回归）。

**建议修复方向**：`engine=` 缺省时不要静默退回旧语义——在 `draw_ui` 里当 `engine is None` 且存在声明式绑定时打印一次明确告警（或让 `draw_all` 在 `script_host is None` 时保留**上一帧**的宿主而不是覆盖为绘制目标）。契约：C8/C9 不变；不得让「省略参数」等于「静默失效」。波及：`vk_renderer.draw_frame/draw_ui` 的所有调用方、`tests/_tmp/ab_gl_vk_ui.py`。

### 2.16 P-02-15 交接文档 §6.1 的根因「GL 会把 canvas 尺寸跟窗口同步」与代码不符（**PROVED** → DOCIMPL/DESIGN-DRIFT）

**1) 位置**　文档：`docs/handoff/接手总纲_20261107_引擎发布与游戏打包.md` §6.1（「GL 路径因为编辑器/播放器都会把 canvas 尺寸跟窗口同步，所以不受影响」+ 修复方向「在 VK 播放器每帧把 screen Canvas 的 width/height 同步为物理窗口尺寸」）。代码：`editor.py:567-592`（GL 侧分发）、`vk_ui.py:833-853`（VK 侧分发）。

**2) 契约**　C4（GL/VK 等价）+ 文档即白盒契约（§6.1 既是现状声明也是修复处方）。

**3) 反手（尝试证明「文档说的是对的」）**　枚举 GL 侧的尺寸同步点：`grep -n "canvas.width|c.width =" Loom/*.py` → 只有 `agent_commands.py:2274`（编辑器 UI 面板改画布尺寸的**人工**命令）与 `loom_ui.py` 的读取点，**没有任何**「每帧把 canvas 尺寸同步为窗口尺寸」的代码；`grep -n "ui.width|ui.height"` 亦无。反手失败。

**4) 正手（证真）**　代码事实：GL 侧 `editor._dispatch_ui_mouse()` 直接把 `self.mouse_pos`（窗口像素）交给 `ui.dispatch_mouse`，无任何缩放/换算（`editor.py:579-583`）；VK 侧 `UIInputBridge.begin_frame()` 同样把 `self.pos`（GLFW 光标，窗口像素）交给 `ui.dispatch_mouse`（`vk_ui.py:852-853`）。两端都拿**窗口像素**去命中**场景里保存的画布坐标**。

**5) 实际 vs 预期**　文档说「GL 会同步尺寸所以不受影响」，代码里两端都不做这件事。**6) 差异**　文档给出的根因不成立；由此推导出的「只在 VK 侧同步画布尺寸」处方，若实施会**制造新的 GL/VK 分叉**（VK 的 Canvas 变成窗口尺寸、GL 仍是场景尺寸 → 同一场景两端 UI 布局/命中都不再一致，C4 被破坏）。

**7) 验证**　`Select-String -Path Loom\*.py -Pattern "canvas\.width"`（只命中 agent_commands.py:2274）；`Select-String -Path Loom\editor.py -Pattern "_dispatch_ui_mouse" -Context 0,20`（第 580-583 行直接传 mouse_pos）。**8) 等级**　P2（文档失真 + 处方有反向风险；现象本身是已知 open issue，不属本轮引入）。

**建议修复方向**：先把「UI 坐标空间」定义成**一个**契约（画布坐标 ↔ 窗口像素的换算放在 `UIManager.dispatch_mouse`/`hit_test` 的入口，而不是各后端）——即选一处做换算，GL/VK 共用；文档 §6.1 的根因句必须改正。契约：C4 不得破坏（两端必须同时改变或同时不变）。波及：`editor._dispatch_ui_mouse`、`vk_ui.UIInputBridge`、`loom_ui.dispatch_mouse/_hit_screen`、`ab_gl_vk_ui.py` 基线。

### 2.17 P-02-16 `_Tee` 缺 `encoding/fileno/buffer`（**UNKNOWN**）

**1) 位置**　`game_player.py:45-71`（`_Tee` 只实现 `write/flush/isatty`），随后 `sys.stdout = _Tee(sys.__stdout__, f)`。
---

### 6.6 补充说明（实现取舍留痕）

---

## 7. 最后一轮修复（N4 解锁采样/首帧顺序 + P-02-06 入口一致性）

### 7.1 改动（仍只动本批文件）

| 项 | 落点 | 改法（方向） |
|---|---|---|
| N4① 采样频率 | `vk_player.poll_unlock_frame()`（新增，模块级）+ `run_vk` 的 `draw()` | 每**渲染帧**采样一次，不再只在逻辑步；`draw()` 把它排在 `driver.advance_logic()` **之后**，因此首帧 `on_start` 的初始锁定先落定，首个 poll 不会把状态拧反 |
| N4 委托 | `vk_player._unlock_poll_fn()`（新增） | 不复制语义：满足 engine 实现前置（`script_keys` dict + `_warn_unlock_poll_unavailable`）时直接绑 `engine.GLEngine._poll_mouse_unlock_key`；否则用驱动自带的 `_poll_unlock_local()`（批 2 的回退实现）。解析结果按 driver 缓存 |
| N4 状态一致 | `vk_player.poll_unlock_frame()` 尾部 | 若 `mouse_locked=True` 且 `mouse_unlock_requested=True`（脚本直接 `set_mouse_locked(True)` 撞上玩家解锁意图）→ 调 driver 自己的 `_apply_mouse_lock()` 按玩家意图解锁，**每局只报一次** |
| P-02-06 根因 | `run_player.py` 末尾 `__main__` 分支 | `sys.modules.setdefault('run_player', sys.modules[__name__])` —— 脚本方式运行时把自身登记为 `run_player`，vk_player 的 `from run_player import ...` 拿到同一模块对象（同一异常类） |
| P-02-06 兜底 | `run_player.py` 的异常段标记 + `run_backend` | 给两个异常类加 `segment` 类属性（`vulkan-init` / `vulkan-run`），`_is_vk_error()` 按标识识别；`auto` 段不再用裸 `except VkRunError` 而是「类或 segment」，`vulkan` 段只把**初始化段**当回退信号，其余原样上抛 |
| 共性（except 收窄） | 全部新增 except | `except ImportError`（engine 不可用）/ `except (AttributeError, TypeError)`（缓存失败）/ `except (TypeError, ValueError)`（wheel 坏值）；其余带原因的告警一律**只打一次** |

### 7.2 修前 / 修后（真实输出）

**（1）N4 — 短按不解锁 / 首帧状态矛盾**

修前（独立验收 + 我的审计复现）：VK 侧仅在逻辑步（30Hz）采样，`advance_logic` 未推进时完全不解锁；且 `on_start` 的 `set_mouse_locked(True)` 排在首个 poll 之后 → `locked=True` 与 `unlock_requested=True` 并存（矛盾态）。

修后（`python tests/test_render_api.py` 的 `t_unlock_sampling_parity`，全程不推进任何逻辑时钟）：

```
PASS VK 渲染帧采样: 未跑任何逻辑步也能解锁 (短按不丢)  (True, False, True)
PASS 按住不放不重复翻转  True
PASS 松开帧不翻转
PASS 复现矛盾态 (locked=True 且 requested=True)  (True, True)
[输入] 锁定状态与解锁意图矛盾 (locked=True / requested=True) -> 已按玩家意图解锁 (本局只报一次)
PASS 渲染帧采样消除矛盾态 (按玩家意图解锁, locked=False)  (False, True)
PASS VK 侧不复制解锁语义 (无 def _poll_mouse_unlock_key)
PASS SceneDriver.poll_unlock 委托 engine.GLEngine 唯一实现
PASS GL 侧同一按键同样翻转 (两后端同一实现 -> 采样等价)  (True, False)
```

真机路径未回归：`beta3_scan_02_probe_quit.py`（真实 `run_vk(mini=True)`，含新的每帧 poll）→
`[quit] ret=None exc=None frames=5 elapsed=3.86s`（正常返回，无异常）。

**（2）P-02-06 — 脚本入口异常身份 / Q6 回退链**

修前（审计轮 PR-4）：

```
run_player.VkInitError is __main__.VkInitError ? False
vk_player.VkInitError is __main__.VkInitError ? False
捕获结果: 未被 __main__ 版 except 接住 -> 冒泡为 VkInitError: simulated: vulkan init failed
```

修后（`t_run_player_entry_identity`，用 exec 以 `__main__` 身份执行真实 run_player.py）：

```
PASS 脚本入口把自身登记为 run_player 模块  <module '__main__' from '...\Loom\run_player.py'>
PASS VkInitError 类身份唯一 (脚本入口)  (<class '__main__.VkInitError'>, <class '__main__.VkInitError'>)
PASS 脚本入口: 初始化失败 -> 非零退出 (不再冒泡成未捕获异常)  ('SystemExit', 1)
PASS 脚本入口: 提示含「不兼容」并走回退  [run_player] 已初始化用户配置: %TEMP%\tmpXXXX\游戏设置.json
PASS 脚本入口: 回退已写入配置 (Q6 持久化真的发生)  %TEMP%\tmpXXXX\设置.json
```

### 7.3 验收（本轮实跑）

| 测试 | 结果 |
|---|---|
| `python tests/test_render_api.py` | **ALL PASS**（含本轮新增 13 条断言） |
| `python tests/test_backend_fallback_policy.py` | **ALL PASS** |
| `python tests/test_unlock_key.py` | **ALL PASS** |
| `python tests/test_user_config.py` | **ALL PASS** |
| `python tests/test_wheel_backend_semantics.py` / `test_vk_ui_input.py` / `test_vk_camera_align.py` | **ALL PASS** |
| `python -m py_compile` 四个改动文件 | OK |
| `git status --porcelain`（本批文件） | 仅 5 个 `M`，无 pyc / 日志 / 配置残留 |

### 7.4 本轮新发现（跨批，交回主审）

| # | 位置 | 现象 | 影响 | 建议 |
|---|---|---|---|---|
| N5 | `engine.py:934` | 引擎唯一实现的**前置条件**里要求 `self.script_keys` 是 dict（GL 的属性名），而 `SceneDriver` 用的是 `key_state`；且实现内部会调 `self._warn_unlock_poll_unavailable`（SceneDriver 没有该方法） | `SceneDriver.poll_unlock()` 的委托**必然失败**并**每帧**打印 `委托引擎解锁键实现失败 ... 用驱动内回退实现`（120Hz 刷屏），VK 实际一直走 `_poll_unlock_local` | 二选一：① 引擎实现接受 `script_keys` 或 `key_state` 任一（并容忍缺 `_warn_*`）；② `scene_driver` 补一个 `script_keys` 别名 + 把 `_warn_unlock_poll_unavailable` 交给骰子。本轮我在 `vk_player._unlock_poll_fn` 侧规避了刷屏（满足前置才绑引擎实现，否则直接用驱动自带实现），但**根因仍在批 1/批 2 文件里** |

### 7.5 剩余（不属本批 / 未实测）

| 项 | 状态 |
|---|---|
| P-02-04（camera.fov GL/VK 分叉） | 落点 `scene_driver.py:589`（批 2），未改 |
| `_external_ctx`（`LOOM_REMOTE_MODE=1` 的 Qt 宿主播放器）UI 派发 | 未覆盖（重复点击风险，需宿主侧帧增量语义） |
| 真鼠标 / 打包版（无控制台、Program Files）实机 | 未实测（本轮无打包环境） |