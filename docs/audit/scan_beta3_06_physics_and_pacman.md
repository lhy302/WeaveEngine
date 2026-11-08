# 物理碰撞与吃豆人脚本 扫描报告（beta3 补丁回归审计 · 子代理 06）

- 报告编号：beta3_scan_06
- 审计对象：`f53a82a..HEAD`（29 个提交）中与本模块相关的改动
- 仓库根：`D:\my-project - 副本\Loom(py源代码-工作区)`（下文路径均相对此根）
- 审计日期：2026-11-08 · HEAD = `62479f0`
- 被审对象类型：**黑盒实现 + 白盒契约混合**（loom_physics 的实现 vs 其函数注释/交接文档声明的语义；吃豆人脚本的实现 vs 场景 JSON 契约 + 引擎 API 契约）
- 本次目标等级：**A6**（双向链 + 路径枚举 + 可跑复现 + 探针 + 白盒推广 + 人类裁决格式）；自检见 §3.3

---

## 0. 范围与方法

### 0.1 文件清单（行数按 `Get-Content | Measure-Object -Line`）

| 文件 | 行数 | 字节 | 本轮状态 |
|---|---|---|---|
| `Loom/loom_physics.py` | 908 | 52969 | 修改（提交 `2193cbe` 只改这一个源文件：+23/−7 行） |
| `Loom/scripts/pacman_player.py` | 168 | 7013 | **新增**（`95865c6`→`86cfc24` 演进，本报告按 HEAD 版本审） |
| `Loom/scripts/pacman_ghost.py` | 95 | 3926 | **新增**（同上） |
| `docs/audit/pacman2d_scene.json` | — | 156259 | 本轮新增（`c440646`/`734eccc`/`86cfc24` 三次更新，HEAD 未再改） SHA256=`D34A1E44D1EC78E9CABCC836B5E9BBAA2072EAC9EF008D2FFFB88A3B53963752` |
| `Projects/PacMan2D.json` | — | — | **在仓库中不存在**（见 P-06-08） |

### 0.2 本轮补丁事实（先固化 diff，避免误判"原始设计"）

```
$ git show --stat --oneline 2193cbe
2193cbe 修碰撞穿墙：盒-球推出改走最近面（+ 相机快照归位）
 Loom/loom_physics.py                    | 23 ++++++++++++++++-------
 docs/audit/3D吃豆人实机演示_20261107.md | 24 ++++++++++++++++++++++++
 2 files changed, 40 insertions(+), 7 deletions(-)
```

即：`_push_out` 是本轮**唯一**被改的物理代码，改动完全落在 `if dist < 1e-9:`（球心在盒内）这一分支内；
盒-盒分支、球-球分支、球-盒"球心在盒外"分支**一行未动**（差分实证见 §2 P-06-03 与 P-06-11）。
本轮**没有**改动任何 `Loom/tests/` 下的碰撞/物理测试（`git diff --stat f53a82a..HEAD -- Loom/tests/` 只列出 6 个与本模块无关的新测试文件）。

改动前（`f53a82a`，原始设计基线）与改动后（HEAD）对照，均取自 `git show f53a82a:Loom/loom_physics.py` 与 `Loom/loom_physics.py:355-371`：

| | 推出方向 | 推出量 |
|---|---|---|
| 旧（f53a82a） | `u = normalize(球心 - 盒中心)`；两者重合时 `u=(0,0,0)`（0/1e-6） | `need = r + 1e-4` |
| 新（HEAD） | 三轴六个面里取 `min(到 -面距离, 到 +面距离)`，沿该轴 ±1 方向 | `need = 最近面距离 + r + 1e-4` |

### 0.3 判定基准清单（证真链只允许引用这四条中的出处）

| 编号 | 基准 | 出处 |
|---|---|---|
| B1 | `_push_out` 的自我声明："把 a 推出 b 的碰撞体（仅已相交时调用）… 盒-盒走最小穿透轴（滑墙自然），含球时沿球心连线推出。只改 a.position" | `Loom/loom_physics.py:291-294`（HEAD）；旧文本见 `git show f53a82a:Loom/loom_physics.py` |
| B2 | 本轮修复的设计意图："改为沿**最近面**推出（与盒-盒最小穿透轴一致）：永远走最短路径出去" | `Loom/loom_physics.py:356-359` 注释；`docs/handoff/接手总纲_20261107_引擎发布与游戏打包.md` §2.7 表格 |
| B3 | 引擎 API 契约：`set_logic_paused(paused)`／`request_game_exit()`／`get_action(name)`／`world_position(m)`／`ui.canvases` | `Loom/engine.py:834-844`、`Loom/scene_driver.py:644-650`、`Loom/loom_input.py:191-198`、`Loom/loom_transform.py:314`、`Loom/loom_ui.py:380` |
| B4 | 场景契约：墙命名 `墙_<x>_<z>`、豆子命名 `豆子_<x>_<z>`、整数格心；`docs/handoff…` §2.4 "11x11 迷宫（63 墙 + 58 豆）… 网格移动（目标格是墙就不走）… 幽灵防重叠（掉头 + 0.1s 冷却）… 通关（吃完可见豆 -> 暂停 + 面板）… 退出语义" | `docs/audit/pacman2d_scene.json`（实测 63 墙 / 58 豆 / 3 幽灵 / 1 玩家）；`Loom/scripts/pacman_ghost.py:4`（命名约定原文）；`Loom/scripts/pacman_player.py:5-6,27` |

> 说明：`Projects/PacMan2D.json` 不在仓库（`Test-Path Projects` → False，`git ls-files Projects` → 空），因此**场景侧判定基准只能用 `docs/audit/pacman2d_scene.json` 这一份入库副本**。该副本与发布场景是否同源不可证（P-06-08）。

### 0.4 跑过的命令与关键输出索引

| # | 命令（在仓库根或 `Loom/`） | 结论 |
|---|---|---|
| C1 | `python tests/test_collision.py` 等 10 个测试逐个直跑（`Loom/` 下） | **10/10 全 PASS，exit=0**（见 §0.5） |
| C2 | `python Loom/tests/_tmp/beta3_scan_06_pushout.py` | 球心在盒内 5 个用例：NEW 全部一次分离；OLD 有 3 个用例推不出 |
| C3 | `python Loom/tests/_tmp/beta3_scan_06_pushout2.py` | 球心在盒外分支差分 diff=0/110；同分方向 ±1e-9 翻面；盒-球反向单次位移放大 5.9×/∞ |
| C4 | `python Loom/tests/_tmp/beta3_scan_06_pacman.py` | 网格移动 24 组 × 1200 帧无穿墙；通关/重开/退出/无敌边界全 PASS |
| C5 | `python Loom/tests/_tmp/beta3_scan_06_ghost.py` | 幽灵 200s：0 帧入墙、0 NaN；**同格同向 3s 完全重合** |
| C6 | `python Loom/tests/_tmp/beta3_scan_06_ui.py` | 按钮 click 只经 `UIManager.dispatch_mouse`；GL 播放器不含该调用 |
| C7 | `python Loom/tests/_tmp/beta3_scan_06_cov.py <test>` ×10 | 只有 `test_physics.py` 命中改动分支 **1 次**，其余 9 个为 0 次 |
| C8 | `python Loom/tests/_tmp/beta3_scan_06_floor2.py` | 定位那 1 次命中：球(球心恰好落进立方体 A)被向下推 0.5002 |
| C9 | `python Loom/tests/_tmp/beta3_scan_06_invuln.py` | `invuln` 参数三档取值实测无敌时长恒为 1.5167s → 参数无效 |
| C10 | `git diff --stat f53a82a..HEAD -- Loom/tests/`、`git status --porcelain` | 本轮未改碰撞测试；工作树只有 2 个**非本代理造成**的未跟踪项 |

探针文件（均在 gitignore 的 `Loom/tests/_tmp/` 内，`git check-ignore` 已确认，无产品代码 import 它们）：
`beta3_scan_06_scene.py / _pushout.py / _pushout2.py / _pacman.py / _ghost.py / _ui.py / _cov.py / _floor.py / _floor2.py / _invuln.py` 及对应 `.log`。

### 0.5 10 个碰撞/物理测试实跑输出（要求贴原始输出）

```
===== test_collision.py =====        (末尾) 总结果: ALL PASS ✅        [exit=0]
===== test_collision_edges.py =====  (末尾) 总结果: ALL PASS ✅        [exit=0]
===== test_scripts_collision.py =====(末尾) 总结果: ALL PASS ✅        [exit=0]
===== test_collision_events_small_scene.py ===== 总结果: ALL PASS      [exit=0]
===== test_physics.py =====          (末尾) 总结果: ALL PASS ✅        [exit=0]
===== test_physics_bridge.py =====   (末尾) 总结果: ALL PASS ✅        [exit=0]
===== test_physics_runtime.py =====  (末尾) 总结果: ALL PASS ✅        [exit=0]
===== test_physics_body_init.py =====(末尾) 总结果: ALL PASS ✅        [exit=0]
===== test_physics_pipe_errors.py ===(末尾) 总结果: ALL PASS ✅        [exit=0]
===== test_scene_driver_physics_log.py ===== 总结果: ALL PASS          [exit=0]
```

补充事实（可复核）：这 10 个文件全是**独立脚本式**测试（0 个 `def test_`，`pytest` 收集时因模块级 `sys.exit()` 触发 `INTERNALERROR: SystemExit`），
必须用 `python tests/<f>.py` 逐个跑；用 `pytest` 直接跑会在第一个文件处 abort（实测 `mainloop: caught unexpected SystemExit!`）。
这个"用错跑法会假失败/直接中断"的事实会影响后续任何想一键跑回归的人，登记在 §4 建议里。

### 0.6 工作树自查（硬约束 8）

```
$ git status --porcelain
?? tools/lint_except_dist/
?? tools/loom_lint_except.py
```

这两项在本代理开工**之前**就已存在（`tools/loom_lint_except.py` 是上一轮 loom_lint_except 审计的产物，非本模块），
本代理未创建、未修改、未删除它们；本代理新建的文件全部落在 `Loom/tests/_tmp/`（gitignore）与本报告。
**本代理未改动任何受跟踪文件**（无 `git checkout`/`stash`/`reset`，也未发生需要还原的误改）。

---

## 1. 粗筛清单（含跳过项留痕）

### 1.1 疑似项（六元组）

| ID | 位置 | 标签 | 初步方向（指向具体代码事实） |
|---|---|---|---|
| P-06-01 | `Loom/runtime.py:18-118`（PlayerApp）＋全仓 `dispatch_mouse` 调用点 | IFACE-PARTIAL / SEM-SILENT | 本轮把"重开/退出"做成**唯一 UI 入口**（`pacman_player.py:85-118` 的 `on_restart`/`on_quit` 只由 `_fire_binding('click')` 触发），而 GL 播放器 `runtime.PlayerApp` 全类无任何 `dispatch_mouse` 调用 |
| P-06-02 | `Loom/loom_physics.py:360-371` | BND-OVERFLOW / AUDIT-DOCIMPL | 三轴六面向量里 `lo == hi` 时只保留先到者（轴序 x→y→z，各轴先 `lo` 后 `hi`），注释却声称"与盒-盒最小穿透轴一致"，而盒-盒分支有显式稳定破同分规则（`loom_physics.py:320-322`） |
| P-06-03 | `Loom/loom_physics.py:360-381` | SEM-MISMATCH / AUDIT-ASYMMETRY | `dist<1e-9` 分支算出的是"把**球**推出盒"的方向，但 `a` 是盒时（`a_is_sphere=False`）**未取反**就直接加在 `a.position` 上；且 `need` 由 `r+1e-4` 变成"最近面距离+r+1e-4"，单次位移量级可放大到盒的半边长 |
| P-06-04 | `Loom/tests/test_physics.py:78-86`（唯一命中点） | OVERFIT-ORACLE / TOOL-SCOPE | 改动分支在 10 个测试里只被"偶然"命中 1 次，且命中处的断言在几十行之前，等于**无回归覆盖** |
| P-06-05 | `Loom/scripts/pacman_ghost.py:67-88` | SEM-SILENT / BND-CONCURRENCY | `_avoid` 只会"两只都掉头"；同格同向时两只同时掉头 → 位移完全相同 → 永远重合且每 0.1s 同步抖动 |
| P-06-06 | `Loom/scripts/pacman_player.py:85-89` vs `27-30` | SEM-MISMATCH / AUDIT-DOCIMPL | `total` 只统计 `visible` 的豆，`on_restart` 却把**所有**豆（含设计时隐藏的）设为可见 → 与"隐藏的不算目标"契约漂移 |
| P-06-07 | `pacman_player.py:31-45`、`pacman_ghost.py:24-37,42-43` | IFACE-PRECOND / DESIGN-DRIFT | 关卡几何靠**对象名**（`墙_x_z`/`豆子…`/`幽灵…`）与"整数格心"隐式契约；引擎/编辑器/场景 JSON 都不校验，`round()` 吸附格心会让半格摆放瞬移 ≤0.5 |
| P-06-08 | `Projects/PacMan2D.json`（不存在） | DESIGN-GAP / TOOL-SCOPE | 发布场景不在仓库，`build_game.py` 却按该路径出包；审计只能对 `docs/audit` 副本做常量校验 |
| P-06-09 | `pacman_player.py:130-152` | BND-OFFBYONE / SEM-OVERFIT | 网格移动在斜向/连击/帧率抖动下是否真不穿墙（`at_center` 容差 1e-3、`step` 无上限钳制、只取 dx 忽略 dz） |
| P-06-10 | `pacman_ghost.py:45-104` | BND-EMPTY / AUDIT-DEADCODE | `_choose_dir` 无候选且 `_dir is None` 时回退 `[(1,0)]`，可能把墙格当目标；寻路是否死循环/抖死 |
| P-06-11 | `loom_physics.py:340-343,353-374` | OVERFIT-TESTENV | 盒-盒与球-球、球-盒"外部"分支是否被无意改动（差分自检） |
| P-06-12 | `docs/audit/pacman2d_scene.json` × 脚本常量 | OVERFIT-HARDCODE | 速度 4.0、无敌 1.5s、捕获 0.55、eat_r、网格尺寸是否与场景真值一致 |
| P-06-13 | `pacman_player.py:73-83,98-103,110-113`；`engine.py:834`；`scene_driver.py:644,691` | IFACE-ERROR / BND-CONCURRENCY | 通关暂停后 UI 按钮是否还点得动（暂停是否冻结 UI 派发）；`set_logic_paused` 与 `toggle_logic_paused` 语义是否等价 |
| P-06-14 | `pacman_player.py:20,161` | AUDIT-DEADCODE / SEM-MISMATCH | `params` 声明 `invuln` 可调，`update` 里却硬编码 `self._invuln = 1.5` |
| P-06-15 | `pacman_player.py:179` | BND-EMPTY | `if self.total and self.score >= self.total`：total=0（无豆场景）永不通关；score 是否可能超过 total |

### 1.2 跳过登记表（四类可审计理由之一 + 出处）

| SKIP | 位置 | 跳过理由类型 | 出处 |
|---|---|---|---|
| SKIP-01 | `loom_physics.py:303-329` 盒-盒分支 | 白盒契约明确声明 + 已有回归测试覆盖 | 本轮 diff 未触碰（`git diff` 只涉及 353-381 区间）；`test_collision_edges.py:118-124` 覆盖盒盒重合推挤；C3 探针 400 组随机差分 diff=0 |
| SKIP-02 | `loom_physics.py:331-343` 球-球分支 | 同上 | 同上；`test_collision.py:93-94`、`test_collision_edges.py:111-116` |
| SKIP-03 | `loom_physics.py:372-376`（球心在盒外分支） | 同上 | C3 探针 110 组随机差分 diff=0（"逐位未变"） |
| SKIP-04 | `loom_physics.move_with_collision` 的 `bounds` 调用内缓存精度 | 白盒契约明确声明（已登记为已知项） | `docs/handoff/接手总纲…` §6.3 "move_with_collision 盒-盒多物体同帧推挤仍用调用内缓存（极端场景精度问题，已修球心入盒翻面）"；本轮 diff 未触碰该方法 |
| SKIP-05 | `pacman_player.py:51-63` `_find_ui` 的 `try/except` 吞异常 | 白盒契约明确声明（API 存在且路径已枚举） | `Loom/loom_ui.py:380` `self.canvases = []`、`:366-367` `Canvas.find`；`engine` 侧 `ui` 恒存在（`engine.py:388` 之后 `UIManager()` 初始化）；C4 探针实测 `_panel` 非 None |
| SKIP-06 | 场景 screen Canvas 1008×935 vs 窗口 1280×800 的命中坐标 | 白盒契约明确声明（已登记为已知未修项） | `docs/handoff/接手总纲…` §6.1（TL;DR 列为"剩余最关键问题"）；属 UI 子模块范围 |
| SKIP-07 | `pacman_ghost.py` 的 `random` 未播种 | 语言规范保证 | Python 文档：`random` 默认由系统熵源播种，脚本不需要确定性；C5 用 `random.seed` 固定后再统计 |
| SKIP-08 | `pacman_player.py:159` 捕获半径 0.55 硬编码 | 白盒契约明确声明 | `docs/handoff…` §2.4 未把它列为可调参数；脚本 `params` 表（`pacman_player.py:18-20`）里也没有该项 → 无"可调"承诺可违反 |
| SKIP-09 | `Point3D.__getitem__` 是否存在（新代码 `sc.__getitem__(i)`） | 语言规范保证 | `Loom/loom_types.py:10` `Point3D = namedtuple(...)` → tuple 支持下标；同函数既有 `amn[i]` 用法亦证明 |
| SKIP-10 | `engine.get_action` 的动作名 `向右/向左/向前/向后` 是否存在 | 白盒契约明确声明 | `Loom/loom_input.py:105-108` |

---

## 2. 逐项裁决

> 每条链按 SCAN_PROTOCOL §1 的 8 段式：位置 / 契约预期 / 路径枚举 / 实际行为 / 差异 / 触发条件 / 验证命令+实测输出 / 影响与等级。
> 证伪链的第 3 段必须是**路径枚举表**；证真链的第 7 段必须是**可跑命令**。

---

### P-06-01 【P-PROVED · P1 · [REGRESSION]】GL 播放器没有 UI 鼠标派发通道 → 通关面板"新开一局/退出游戏"永久失效

**1) 位置**
- 契约使用方：`Loom/scripts/pacman_player.py:85-104`（`on_restart`）、`:106-118`（`on_quit`）、`:46-47,65-67`（通关面板显隐）
- 场景侧绑定：`docs/audit/pacman2d_scene.json` UI 树的 `event_bindings: {"click": {"script": "pacman_player", "method": "on_restart"/"on_quit"}}`
- 缺失方：`Loom/runtime.py:18`（`class PlayerApp(GLEngine)`，docstring 原文"只读场景播放器: 无编辑器 UI"）

**2) 契约/预期**
B4（handoff §2.4）："UI：Canvas 通关面板（标题 + 新开一局 + 退出游戏），事件绑定到 pacman_player.on_restart / on_quit"；"退出语义（编辑器回编辑态 / 播放器关窗）"。
→ 期望：**任何**播放器后端下点击面板按钮都会执行脚本回调。

**3) 路径枚举（证伪：穷举"按钮能被点动"的全部可能路径）**

| # | 运行时 | UI 树绘制 | 鼠标事件进入 UI 的调用链 | 结论 |
|---|---|---|---|---|
| 1 | 编辑器（Qt）播放态 | `ui/loom_gui.py:1041` | `editor._update_camera`(`editor.py:2339`) → `_dispatch_ui_mouse`(`editor.py:567,580`) → `UIManager.dispatch_mouse` | ✅ 可点 |
| 2 | VK 播放器 | `vk_renderer.py:1054` `eng.draw_all(ui, script_host=engine)` | `vk_player.py:397` `ui_bridge.begin_frame()` → `vk_ui.py:853` `ui.dispatch_mouse(...)` | ✅ 可点（坐标系问题见 SKIP-06） |
| 3 | GL 播放器 `runtime.PlayerApp` | `loom_render.py:821` `self.ui.draw_all(self)` | **不存在**：`runtime.py / loom_render.py / loom_glfw_window.py / engine.py / loom_frame_components.py` 中 `dispatch_mouse` 出现次数均为 **0** | ❌ 死 |
| 4 | 打包版 `MyGame.exe` | 同 3 或 2 | `game_player.py:226` → `_start_pack` → `run_player.run_backend`；`api=='opengl'` → `_run_opengl` → `runtime.PlayerApp(...).run()`（`run_player.py:147,155-161`） | ❌ 死（走 opengl 时） |

补充枚举（"是否存在绕过 dispatch_mouse 的点击入口"）：`Button.on_mouse_up` 全仓唯一调用点 `loom_ui.py:617`，位于 `UIManager.dispatch_mouse` 内；
`_fire_binding(self,'click')` 唯一触发点 `loom_ui.py:1051`（`Button.on_mouse_up`）。⇒ 无旁路。
**证伪失败**：路径 3/4 会产生"按钮点了没反应"。

**4) 实际行为（代码事实）**
`runtime.PlayerApp` 与 UI 有关的只有：继承 `GLEngine`（`self.ui = UIManager()` 负责**画**）与 docstring 的"游戏自己的 UI 照常在 render 里画"（`runtime.py:117`）。
输入侧只有 `loom_glfw_window` 的键鼠采集（喂相机与 `get_action`，`loom_glfw_window.py:303` 刷新 `script_keys`），从未把 `pressed/released` 交给 `UIManager`。

**5) 差异**
预期：点"新开一局"→ `on_restart`（豆子复现、score 归零、解除暂停）。实际：`_pressed` 永不置位 → `on_mouse_up` 不发生 → `click` 绑定永不触发 → **通关后只能关窗口**。

**6) 触发条件**
`游戏设置.json` 的 `render_api=opengl`（handoff §3.4 列为合法可选项），
或 Vulkan 初始化失败后 `run_player._handle_vk_init_failure` 自动把配置改成 opengl（`run_player.py:108-126`；handoff §2.5 设计的正是这条回退链）→ **下一次启动必现**。无 Vulkan 的机器（虚拟机/远程桌面/老显卡）正是这条链的目标用户。

**7) 验证（可跑）**
```
$ python Loom/tests/_tmp/beta3_scan_06_ui.py
  runtime.py                   dispatch_mouse 出现 0 次 | 调用行: []
  loom_render.py               dispatch_mouse 出现 0 次 | 调用行: []
  loom_glfw_window.py          dispatch_mouse 出现 0 次 | 调用行: []
  engine.py                    dispatch_mouse 出现 0 次 | 调用行: []
  loom_frame_components.py     dispatch_mouse 出现 0 次 | 调用行: []
  editor.py                    dispatch_mouse 出现 1 次 | 调用行: ['consumed = ui.dispatch_mouse(']
  vk_ui.py                     dispatch_mouse 出现 5 次 | 调用行: ['consumed = bool(ui.dispatch_mouse(self.pos, pressed, released, wheel))']
PASS GL 播放器 runtime.py 不做 UI 鼠标派发
PASS GL 渲染共享路径 loom_render.py 不做 UI 鼠标派发
PASS GL 窗口层 loom_glfw_window.py 不做 UI 鼠标派发
PASS 引擎核心 engine.py 不做 UI 鼠标派发
   loom_ui.py:617  if self._pressed_elem.on_mouse_up(pos):
PASS on_mouse_up 只在 UIManager(loom_ui) 内被调用
PASS 只画不派发 -> 按钮不触发  []
PASS 经 dispatch_mouse 按下+松开 -> 按钮触发  [1]
PASS runtime.PlayerApp 源码无 dispatch_mouse/_pressed 相关派发
```
（后两行是功能对照：同一个 Button，"只画"永不触发，"派发一次按下+松开"必触发 ⇒ 差异只在派发通道）

**8) 判定与等级**
**P-PROVED，P1（功能错误：玩家无法重开/退出）**。**[REGRESSION]**：面板与"通关即暂停+面板=唯一出口"是本轮 `86cfc24` 新增；
引擎侧 GL 播放器从来没有 UI 输入通道（`git show f53a82a:Loom/runtime.py` 同样 0 处 `dispatch_mouse`），
是新游戏**依赖了一个只在编辑器/VK 存在的通道**才把缺陷显性化。

**修复方向（只给方向）**
- 首选位置：`Loom/runtime.py`（PlayerApp）或 `Loom/loom_render.py` 的渲染帧入口——补一条"每帧把本帧新按下/松开交给 `self.ui.dispatch_mouse(...)`"的链，语义对齐 `editor._dispatch_ui_mouse`（`editor.py:567-592`：dispatch → 未消费则 `update_hover_only`）。
- 必须保持的白盒契约：①`UIManager.dispatch_mouse` 是唯一入口，不得新增旁路（否则编辑器/VK/GL 三侧语义分叉）；②与 VK 同语义：每帧最多一次、帧首清空 pressed/released（`vk_ui.UIInputBridge.begin_frame` 既有行为）；③播放态相机不被 UI 吞掉（`editor.py:2343-2348` 的 `ui_consumed` 语义）；④不改变 `PlayerApp` "无编辑器 UI"的定位（只加输入派发）。
- 波及调用方：`run_player._run_opengl`、`game_player._start_pack`、`Loom.py --run`、所有依赖 Canvas 按钮的样例场景（吃豆人是第一个）。
- 不可取的替代：在脚本里加键盘重开只会绕过 UI 契约，属路线选择（见 §5 Q1）。

---

### P-06-02 【P-CONTRADICTION（已消解）→ 窄口径 P-PROVED · P2】"最近面"同分不稳定：±1e-9 即翻面；球心正好落在零厚度盒（地面平面）上被推向 `-y`

**1) 位置**：`Loom/loom_physics.py:360-371`
```python
best = None
for i in (0, 1, 2):
    lo = (sc.__getitem__(i) - bmn[i]) + r    # 推向 -面
    hi = (bmx[i] - sc.__getitem__(i)) + r    # 推向 +面
    if best is None or lo < best[0]:
        best = (lo, i, -1.0)
    if hi < best[0]:
        best = (hi, i, +1.0)
```

**2) 契约/预期**
B2 注释原文："改为沿**最近面**推出（**与盒-盒最小穿透轴一致**）：永远走最短路径出去"。
而盒-盒分支的破同分是**显式确定性**的：`loom_physics.py:320-322`「相等: 朝远离对方中心方向」。

**3) 路径枚举（证伪：证明"同分怎么选都行 ⇒ 不算 bug"）**

| 路径 | 进入条件 | 是否产生疑似行为 |
|---|---|---|
| 3-a | 三轴都不同分 | 否：唯一最小面，方向确定（C2 用例 (1,0,0)/(0.9,0,0)/(0.02,0,0) 实测正确分离） |
| 3-b | 某轴 `lo == hi`（球心在该轴正中） | **是**：`hi < best[0]` 严格小于 ⇒ 同分保留先到的 `lo`（-向） |
| 3-c | 球心恰在零厚度盒平面上（`bmn[i]==bmx[i]==sc[i]`） | **是**：`lo = hi = r`，同 3-b |
| 3-d | 球心在盒中心（三轴全同分） | **是**：x 轴 -向获胜（轴序优先），推量 = 半边长 + r |
| 3-e | 浮点噪声使 `lo`/`hi` 差 1e-16 量级 | **是**：方向由噪声决定 |

**证伪结论**：仅就"几何最短"这一维度，同分两侧等价且都能分离 ⇒ 看似无 bug；
**但证伪链漏了 B2 声明的第二个维度"与盒-盒最小穿透轴一致"**——盒-盒有确定性破同分，球-盒没有。这是证伪链的漏洞（矛盾消解记录见第 8 段）。

**4) 实际行为（正手，最小复现）**
墙 `cube size=1.0 × scale(0.92,0.5,0.92)`（y∈[0,0.5]），球 r=0.25，球心在墙正中 y=0.25：
```
$ python Loom/tests/_tmp/beta3_scan_06_pushout2.py
=== G. 同分 (lo==hi) 时推出方向对浮点噪声的敏感性 ===
  [墙 y[0,0.5] 球心正中部 y=0.25 (干净半整数)] AABB=(-0.460000,0.000000,-0.460000)..(0.460000,0.500000,0.460000) 球心y输入=0.250000000000 -> 推出后 (0.000000, -0.250100, 0.000000)  方向=向下(-y)
  [同上, 球心 y=0.25+1e-9]                    球心y输入=0.250000001000 -> 推出后 (0.000000,  0.750100, 0.000000)  方向=向上(+y)
  [同上, 球心 y=0.25-1e-9]                    球心y输入=0.249999999000 -> 推出后 (0.000000, -0.250100, 0.000000)  方向=向下(-y)
```
**同一几何、只改 1e-9 输入位置，推出方向"向上→向下"翻转**；向下意味着球心从 0.25 被送到 **-0.2501**，即穿到 `y=0` 地板（本场景地板就是 y=0 的零厚度 plane）下方。

退化盒（地面）表现：
```
=== C. 退化盒 (零厚度平面 y=0, 8x8) ===
  [球心正好在平面上 (0,0,0)] NEW pos=(0.000000, -0.200100, 0.000000) 分离=True | OLD pos=(0.000000, 0.000000, 0.000000) 分离=False
  [球心在平面上方 0.05]      NEW pos=(0.000000,  0.200100, 0.000000) 分离=True | OLD pos=(0.000000,  0.200100, 0.000000) 分离=True
  [球心在平面下方 0.02]      NEW pos=(0.000000, -0.200100, 0.000000) 分离=True | OLD pos=(0.000000, -0.200100, 0.000000) 分离=True
```
第 1 行：旧实现遇到"球心正好在平面上"**完全不推**（零向量卡住），新实现推了但推到 **-y（地板下方）**。

**5) 差异**：预期"同分有确定性、可解释的破同分规则"（盒-盒先例）；实际"轴序 + 严格小于 + 浮点微差"，1e-9 即翻向，且可选结果之一是"从地板下方出去"。

**6) 触发条件**：球心落在盒某轴中点 ±1e-9 内（"低墙 + 球贴墙心"、"球正好落在平面地板上"都在此带）；零厚度碰撞体（plane）且球心落在其平面内——这是**地面平面的正常物理状态**。

**7) 验证**：见第 4) 段命令与输出。

**8) 判定与等级 + 矛盾消解**
- 初判：证伪（"几何等价，怎么推都对"）与证真（"注释声称与盒-盒一致，实际不一致；1e-9 就翻面"）**同时成立 ⇒ P-CONTRADICTION**。
- 按方法论 §9.2 自查两条链：证伪链第 3 段只枚举了"最短路径"一个判据维度，漏了 B2 的"与盒-盒最小穿透轴一致"维度 ⇒ **证伪链有漏洞**，矛盾消解。
- 最终判定：**P-PROVED（窄口径）**——不是"最短路径算错"，而是「实现与自身注释承诺不一致（AUDIT-DOCIMPL）+ 同分方向对浮点噪声敏感」。等级 **P2**（边界、需特定几何）。

**修复方向**：在 `loom_physics.py:360-371` 的选面循环里给出**显式稳定**的破同分规则（与盒-盒同一套思想），并对零厚度轴给出确定偏好（例如同分时优先"球心相对盒中心更靠外的一侧"，完全对称时优先 +轴/重力反方向）。
必须保持：①"最近面/最短路径"不变（B2 前半句）；②"球心在盒外"分支逐位不变（C3 已证 diff=0）；③`need` 的 `+1e-4` 缓冲保留（贴边=不碰撞的严格 `<` 判定依赖它）。
波及：`resolve_collisions`、`move_with_collision`、`_update_physics_legacy`，以及所有用 `plane` 做地面的场景。

---

### P-06-03 【P-PROVED · P2】`a` 是盒、`b` 是球且球心在盒内时方向未取反；单次推出位移从 `r+1e-4` 放大到"最近面距离+r+1e-4"（实测 5.9×，最深 1.20）

**1) 位置**：`loom_physics.py:346-381`（对比 `else` 分支的取反：`:375-376` `if not a_is_sphere: u = (-u[0],-u[1],-u[2])`）

**2) 契约/预期**：B1「把 **a** 推出 **b** 的碰撞体…只改 a.position」。当 `a`=盒、`b`=球且球心在盒内，应把**盒**推离球（方向与"把球推出盒"相反，正如 else 分支所做）。

**3) 路径枚举（证伪：证明"最终能分开 ⇒ 不算 bug"）**

| 路径 | 进入条件 | 结果 |
|---|---|---|
| 3-a | `a` 是球 | 方向正确、一次分离（C2 A 组 5/5） |
| 3-b | `a` 是盒且球心在盒内 | **不取反**：盒沿"球的最近出口方向"移动 ⇒ 单次调用**不分离**，位移 = 最近面距离+r |
| 3-c | 同上经 `resolve_collisions(max_iter=4)` | "最近面"随盒移动而换 ⇒ 4 次后**最终分开**（C3 H 组：0.9→-0.3001、0.02→1.2201、0.0→-1.2001 全部分离） |

**证伪结论**：3-c 成立 ⇒ "卡死/永远推不开"的指控**不成立**（该口径证伪成功）；但证伪覆盖不到"单次位移被放大"这一指控。

**4) 实际行为（正手）**
```
$ python Loom/tests/_tmp/beta3_scan_06_pushout2.py
=== H. 盒 a / 球 b (球心在盒内): 单次推出位移量级 (旧 r+1e-4 vs 新 最近面+r) ===
  球心(0.9, 0, 0): 盒单次位移 NEW=0.300100 OLD=0.200100 (倍数 1.50)
     resolve_collisions(4) 末位形 盒=(-0.300100, 0.000000, 0.000000) 分离=True
  球心(0.02, 0, 0): 盒单次位移 NEW=1.180100 OLD=0.200100 (倍数 5.90)
     resolve_collisions(4) 末位形 盒=(1.220100, 0.000000, 0.000000) 分离=True
  球心(0.0, 0, 0): 盒单次位移 NEW=1.200100 OLD=0.000000 (倍数 inf)
     resolve_collisions(4) 末位形 盒=(-1.200100, 0.000000, 0.000000) 分离=True
```
2×2×2 的盒，球心刚进 0.02（几乎贴身）时**盒单次被搬 1.18**（旧 0.2）；球心在盒心时旧实现搬 0（卡住）、新实现搬 1.20。
`resolve_collisions` 的中间位形也很野：0 → +0.3001 → +0.9002 → -0.2999 → -0.3001（C2 B 组实测），**4 帧内来回搬约 2.8 个单位**才收敛。

**5) 差异**：预期"每次只走最小必要距离、方向朝远离球一侧"；实际"方向朝球一侧、单次位移最大可到半边长+r"。
（方向问题旧实现同样存在——旧实现也是 `u=盒中心→球心` 不取反；**本轮新引入的是位移量级放大**：`r` → `最近面距离+r`。）

**6) 触发条件**：移动体是**盒**（`step = min 半边长`，`loom_physics.py:413`，可远大于球半径）且球心进入盒内。例：大箱子被 `move_with_collision` 快速推过一颗球。

**7) 验证**：见第 4) 段输出。

**8) 判定与等级**：**P-PROVED，P2**（极端场景位置突跳）。**[REGRESSION 部分]**：位移量级 5.9×/∞ 由本轮 `need` 公式改变引入。

**修复方向**：`dist<1e-9` 分支补上 `else` 分支那套 `a_is_sphere` 取反（两分支方向语义一致）；`a` 是盒时钳制单次推出量（例如 ≤ 盒最小半边长）。
必须保持：①`a` 是球时"一次必分离"（C2 A 组不能被改坏）；②不改盒-盒/球-球分支；③`need` 恒 ≥0。

---

### P-06-04 【P-PROVED · P3】改动分支在 10 个回归测试里只"偶然"命中 1 次且命中处无断言 → 修复无回归栅栏

**1) 位置**：`Loom/tests/test_physics.py:78-86`（球落地面）、`:114-125`（真正触发配对的"碰撞事件"段）

**2) 契约/预期**：SCAN_PROTOCOL §2 要求"由 diff 引入的可疑点必须能被测试挡住"；handoff §5 用"本轮碰撞相关 10/10 PASS"作为验证证据。

**3) 路径枚举（证伪：证明"测试其实覆盖了这条分支"）**——monkeypatch 计数，逐个文件跑（`beta3_scan_06_cov.py`）：

| 测试文件 | `_push_out` 调用 | 球-盒调用 | 改动分支命中 |
|---|---|---|---|
| test_collision.py | 120 | 0 | **0** |
| test_collision_edges.py | 19 | 0 | **0** |
| test_scripts_collision.py | 821 | 0 | **0** |
| test_collision_events_small_scene.py | 0 | 0 | 0 |
| **test_physics.py** | 158 | 158 | **1** |
| test_physics_bridge.py | 1 | 0 | 0 |
| test_physics_runtime.py | 0 | 0 | 0 |
| test_physics_body_init.py | 0 | 0 | 0 |
| test_physics_pipe_errors.py | 0 | 0 | 0 |
| test_scene_driver_physics_log.py | 0 | 0 | 0 |

⇒ 证伪**部分成功**（不是 0 覆盖），但只有 1 次，其余 9 个文件 0 次。

**4) 实际行为（正手：那 1 次命中断言了什么）**
```
$ python Loom/tests/_tmp/beta3_scan_06_floor2.py
== test_physics.py: dist<1e-9 分支命中 1 次 ==
  a='球'(sphere) b='A'(box)
   球心=(0, -0.4998999999999999, 0) r=0.5 盒=[(-0.5,-0.5,-0.5) .. (0.5,0.5,0.5)]
   a.position 前=(0.0, -0.4998999999999999, 0.0) 后=(0.0, -1.0001, 0.0)  => dy=-0.500200
```
这次命中来自"第 4 节碰撞事件"新增的立方体 A（原点）与**第 1 节已落地的球**（球心 y=-0.4999）重叠：球心落进 A 的 AABB ⇒ 进入改动分支 ⇒ 球被**向下推 0.5002**（穿到 y=-1 地面下方）。
而该球的断言 `abs(ball.position.y-(-0.5))<0.1` 在第 83 行、早已执行完，**不会再观察这个球**。

**5) 差异**：预期"改动分支有回归用例（球心在盒内/盒面/盒角/零穿透/退化盒）"；实际一个都没有，只有 1 次副作用命中。

**6) 触发条件**：任何人后续再动这条分支（含按 P-06-02/03 修复）时，**没有任何测试会变红**。

**7) 验证**：见第 3)/4) 段命令与输出。

**8) 判定与等级**：**P-PROVED，P3（验证缺口）**。

**修复方向**：在 `Loom/tests/test_collision_edges.py` 的 A2 段（已构造 `sph_corner`/`sph_in`）补**推挤断言**（不只 `collider_hit`）：球心在盒心/盒面/盒角/盒内深处/零厚度平面/`a` 是盒而球在内 六种，断言"推出后不重叠 + 位移方向 + 单次位移上限"。
必须保持：测试风格与现有文件一致（独立脚本 + `check()` + `sys.exit`），不能引入 pytest 收集（现有 10 个文件在 pytest 下会 INTERNALERROR，见 §0.5）。

---

### P-06-05 【P-PROVED · P2（潜伏）】幽灵防重叠在"同格同向"时完全失效：两只幽灵 3 秒始终完全重合，且每 ~0.115s 同步掉头（抖动）

**1) 位置**：`Loom/scripts/pacman_ghost.py:67-88`（`_avoid`）；`:45-53`（`_choose_dir` 不检查占格）

**2) 契约/预期**：B4（变更清单 `86cfc24` / handoff §2.4）："幽灵防重叠（掉头 + 0.1s 冷却）"；脚本自述 `pacman_ghost.py:5`："发现与同伴距离过近时立刻掉头，并有 0.1s 冷却防抖动"。
期望：两只幽灵不会长期重叠；掉头不产生高频抖动。

**3) 路径枚举（证伪：证明"所有相遇拓扑都能被 _avoid 分开"）**

| 路径 | 相遇拓扑 | `_avoid` 的实际效果 | 是否分开 |
|---|---|---|---|
| 3-a | 相向而行（距离 < avoid_r） | 双方各自反向 ⇒ 各退一步 | ✅ |
| 3-b | 同向、一前一后 | 后者掉头 | ✅ |
| 3-c | **同格且同向**（位置完全相同） | 双方同时掉头，位移函数相同 ⇒ 相对距离恒 0 | ❌ 永不分开 |
| 3-d | 同格反向 | 掉头后变相向 ⇒ 退化为 3-a | ✅ |
| 3-e | 同格且某只 `back` 是墙（`pacman_ghost.py:83-86`） | 该只目标=当前格（原地） | ✅ |

**证伪失败**：路径 3-c 会产生"长期完全重合 + 高频掉头"。

**4) 实际行为（正手，确定性最小复现）**
两只幽灵同格同向（`_cx=_cz=0`、`_dir=(1,0)`、`_avoid_cd=0`）：
```
$ python Loom/tests/_tmp/beta3_scan_06_ghost.py
=== 同格同向复现 (确定性) ===
3s 内最大两两距离=0.0000 最小=0.0000 方向改变次数=26 (两只会同步翻转)
PASS 同格同向: 3s 内两幽灵始终完全重合 (防重叠失效)  max=0.000000
```
对照基线（真实场景 3 只幽灵 200 秒）：
```
幽灵 200s: 处于墙格帧=0 偏离格心线帧=0 NaN帧=0 目标格是墙帧=0 最小两两距离=0.6667
方向改变次数: [187, 182, 174]  每秒 0.91 次/只
```
⇒ 自然游走 200s 最小间距 0.6667（从未重合）⇒ 本缺陷在当前场景**潜伏**；但 `_choose_dir` 允许选到有幽灵的格（`pacman_ghost.py:47-53` 无占格检查），两只同格同向即可复现。

**5) 差异**：预期"掉头把两只分开"；实际"同向同格时掉头是共同位移，相对位形不变"，只剩 0.1s 周期的同步翻转。

**6) 触发条件**：两只幽灵 `(_cx,_cz)` 与 `_dir` 相同。可达路径：从不同方向先后进入同一格，且 `random.choice` 选中同一方向。

**7) 验证**：见第 4) 段命令与输出。

**8) 判定与等级**：**P-PROVED，P2（潜伏的功能/视觉缺陷）**。

**修复方向**：`_avoid` 在"距离≈0"时需要**非对称**处置（按对象序号/角色固定谁让谁，让位方转向一个可用邻居而非掉头），或 `_choose_dir` 对"目标格已有同伴"降权。
必须保持：①`avoid_cd` 冷却参数语义（`:21,87`）；②走廊寻路不得入墙（P-06-10 已证 0 帧入墙，不能改坏）；③不新增引擎 API 依赖。

---

### P-06-06 【P-PROVED · P3】`on_restart` 把所有 `豆子*` 设为可见（含设计时隐藏的），而 `total` 只在 `on_start` 统计可见豆

**1) 位置**：`pacman_player.py:27-30`（注释"只统计**可见**的豆子（隐藏的不算目标, 便于分关卡/调试）"）vs `:87-89`

**2) 契约/预期**：B4「通关（吃完可见豆 -> 暂停 + 面板）」⇒ 隐藏豆不参与目标；重开一局不应把"设计上隐藏"的豆变成目标。

**3) 路径枚举（证伪）**

| 路径 | 场景形态 | 结果 |
|---|---|---|
| 3-a | 无隐藏豆（= 当前 `pacman2d_scene.json`，58/58 visible，C5 实测） | 无差异 ⇒ **证伪成功** |
| 3-b | 有隐藏豆 + 点"新开一局" | 隐藏豆被点亮 ⇒ 可用分值变大而 `total` 不变 ⇒ 未吃完全部可见豆即可通关 |

**4) 实际行为（正手）**（C4 第 4 段：57 颗设 `visible=False`，只留 1 颗）
```
  on_start: total=1 score=0
PASS on_restart: 所有豆子恢复可见 (含本被隐藏的 57 颗)  vis=58
```

**5) 差异**：预期"只恢复本局吃掉的豆"；实际"恢复全部豆"，与 27 行注释的分层设计冲突。

**6) 触发条件**：某关卡用 `visible=false` 隐藏豆 + 通关后点"新开一局"。（当前唯一入库场景无隐藏豆 ⇒ 潜伏。）

**7) 验证**：`python Loom/tests/_tmp/beta3_scan_06_pacman.py`。

**8) 判定与等级**：**P-PROVED，P3**。
**修复方向**：`on_restart` 只恢复"本局吃掉的豆"（记录 `on_start` 的可见集合或吃豆时记录 id），并同步重算 `total`；保留 `if self.total and ...` 守卫。

---

### P-06-07 【P-PROVED · P3】关卡几何依赖"对象名 + 整数格心"隐式契约；解析失败静默跳过、非整数坐标瞬移

**1) 位置**：`pacman_player.py:31-45`、`pacman_ghost.py:24-37,42-43`

**2) 契约/预期**：B4 命名约定（`pacman_ghost.py:4` "约定: 墙名 墙_<x>_<z>"）+ 整数格心；引擎/编辑器/场景 schema 无任何校验。

**3) 路径枚举（证伪：证明"契约有别的护栏"）**

| 路径 | 可能的护栏 | 实测 |
|---|---|---|
| 3-a | 场景 schema 校验命名 | `sceneio` 只校验类型/字段，name 是自由字符串（`pacman2d_scene.json` 63 个墙名恰好合规） |
| 3-b | 脚本对不合规名字兜底 | 有 `try: int(parts[1]) except ValueError: pass`（`pacman_player.py:37-40`）⇒ **静默跳过** ⇒ 该墙不在 `_walls` ⇒ 玩家可走进"墙"里（SEM-SILENT） |
| 3-c | 非整数坐标 | `int(round(p.x))` ⇒ 首次 `update` 吸附格心，**瞬移 ≤0.5** |

**4) 实际行为**：当前场景合规（63 墙名 `墙_-5_-5`…全部可解析；豆 58/58 可见；幽灵格 2 个邻居；BFS 死胡同 0）。

**5) 差异**：预期"契约显式声明/校验"；实际"命名约定 + 静默降级"。

**6) 触发条件**：手工建关、复制预制体改名、缩放后坐标带小数。

**7) 验证**：`python Loom/tests/_tmp/beta3_scan_06_ghost.py`（第 1 段）、`python Loom/tests/_tmp/beta3_scan_06_scene.py`（墙名样本）。

**8) 判定与等级**：**P-PROVED，P3**。
**修复方向**：命名/格心约束写进关卡模板与文档，并对"解析失败的墙名"打一次告警而非静默 `pass`；首帧把非整数坐标显式对齐而非静默 `round`。不改场景数据（本轮只审不改）。

---

### P-06-08 【P-UNKNOWN】`Projects/PacMan2D.json` 不在仓库：无法证明"发布场景"与 `docs/audit/pacman2d_scene.json` 同源

**1) 位置**：`Projects/PacMan2D.json`（handoff §3.3 与 `build_game.py` 的入参）vs `docs/audit/pacman2d_scene.json`

**2) 契约/预期**：校验"脚本硬编码常量 vs 场景真值"必须拿到**真正用于出包**的场景。

**3) 路径枚举（证伪：证明"审计副本等价于发布场景"）**
- 3-a `Get-ChildItem Projects` → 无输出（目录不存在）
- 3-b `git ls-files Projects` → 空
- 3-c `git log --all --oneline -- 'Projects/PacMan2D.json'` → 空
- 3-d `docs/audit/pacman2d_scene.json` 入库（`c440646/734eccc/86cfc24`）且工作树未改（`git status` 干净）
⇒ 无法由以上任一事实推出"两者一致"。

**4) 实际行为**：只能对审计副本做常量校验（P-06-12 全部通过）；若发布场景被改（起点/豆数/速度），本报告常量结论**不覆盖**发布物。

**5) 差异**：需 (a) 发布场景文件，或 (b) `游戏包.lsc` 解包出的场景，或 (c) 两者 SHA256 对照，才能闭合。

**6) 判定与等级**：**P-UNKNOWN**。还缺的信息：出包时实际读取的场景文件或其哈希（人类提供一条信息即可闭合）。

---

### P-06-09 【P-DISPROVED】网格移动在斜向/连续按键/帧率抖动/零 dt 下均不穿墙

**1) 位置**：`pacman_player.py:130-152`

**2) 契约/预期**：B4「网格移动（目标格是墙就不走，杜绝卡墙/穿墙）」。

**3) 路径枚举（证伪链：证明"不存在能进墙的路径"）**

玩家位置只可能由三条代码路径改变：
- 3-a `pacman_player.py:141`（无方向键时吸附当前格心）：`(self._cx, self._cy)` 都来自 `_open` 校验过的格；
- 3-b `:149`（`step >= dist` 时贴到目标格）：目标格只在 `_open(nx,nz)` 为真时被写入（`:138-139`）；
- 3-c `:151-152`（按 `step` 沿直线插值）：起点与终点都在同一条"格心→相邻格心"线段上，线段不跨墙格。
另外 `at_center`（`:130`，容差 1e-3）保证"只在格心改目标"，所以不会出现斜向/中途改向。
斜向双键（dx、dz 同时为 1）走 `:134-137` 的 `if dx: ... else: ...` ⇒ 只取 x 分量，不产生对角位移。
**路径完备性**：函数内无动态分派、无 `**kwargs`、无异步回调改位（`update` 是唯一写入点）；`obj.position` 在脚本内只有这 4 处赋值（`:93,141,149,151,162`，其中 `:162` 回出生点）。

**4) 实际行为（正手尝试）** 24 组（6 按键序列 × 4 dt 模式：60fps / 抖动 / 卡帧 0.25~0.5s / dt=0）× 1200 帧，每帧校验"位置必须落在 (当前格→目标格) 闭线段上，且两端都是通路格、目标与当前相邻"：
```
$ python Loom/tests/_tmp/beta3_scan_06_pacman.py
PASS 网格移动: 所有按键/dt 组合均未进入墙格 (共 24 组)  []
PASS 长按向右: 停在走廊尽头 (4,0) 不进墙  实际 (4,0) pos=(4.0, 0.0)
PASS dt=0 反复调用: 位置不漂  Point3D(x=1.0, y=0.3, z=0.0)
```
**5) 差异**：无。
**6) 触发条件**：无（需同时破坏 `_open` 与线段插值两条不变量）。
**7) 验证**：见上。
**8) 判定**：**P-DISPROVED**（反手成功、正手失败）。
**残留观察（不构成本项 bug）**：斜向双键时 x 轴优先（`若同按右与前，只走右`），是设计取舍不是缺陷；`step` 无钳制但目标只有一格，`step>=dist` 直接贴合 ⇒ 不会跳格。

---

### P-06-10 【P-DISPROVED】幽灵走廊寻路不穿墙、不 NaN、不抖死（含"死胡同兜底"路径在本场景不可达）

**1) 位置**：`pacman_ghost.py:45-65`（`_choose_dir`）、`:90-104`（`update`）

**2) 契约/预期**：B4「幽灵走廊寻路（不再绕圈）」。

**3) 路径枚举（证伪）**——`_tx/_tz` 只可能在四处被写入：
- 3-a `on_start` → `_choose_dir()`（`_dir=None`，cands = 所有开放邻居）
- 3-b `_choose_dir` 正常分支（cands 只含 `_open` 的格，`pacman_ghost.py:47-53`）
- 3-c `_choose_dir` 无候选分支：`_dir is not None` → `cands=[反向]`（来路必开放）`pacman_ghost.py:54-58`
- 3-d `_avoid`：`back` 经 `_open` 校验，否则目标=当前格（`:81-86`）
唯一"会指向墙格"的分支是 3-c 的 `_dir is None` 兜底 `cands=[(1,0)]`，它**只在 `on_start` 时`_dir` 为 None 且该格四邻全是墙**时可达 —— 要求幽灵出生在孤立格。
**本场景实测**：三只幽灵出生格 (-4,-4)/(4,-4)/(-4,4) 各有 2 个开放邻居，BFS 全图死胡同（仅 1 个通路邻居的格）**0 个** ⇒ 该兜底**不可达**。

**4) 实际行为（正手尝试）** 200 秒（12000 帧）三只幽灵同时跑：
```
幽灵 200s: 处于墙格帧=0 偏离格心线帧=0 NaN帧=0 目标格是墙帧=0 最小两两距离=0.6667
方向改变次数: [187, 182, 174]  每秒 0.91 次/只
```
**5) 差异**：无。
**6) 触发条件**：兜底分支需"孤立格出生"，本场景无。
**7) 验证**：`python Loom/tests/_tmp/beta3_scan_06_ghost.py`。
**8) 判定**：**P-DISPROVED**（0 帧入墙 / 0 NaN / 0.91 次·秒⁻¹ 转向率不属于"抖死"）。
**残留建议（不构成本项 bug）**：若未来关卡允许"出生在孤立格"，`:58` 的 `cands=[(1,0)]` 会命令幽灵走进墙里（无碰撞保护，位置直接写入 `obj.position`）——建议把它改成"原地不动 + 一次告警"。

---

### P-06-11 【P-DISPROVED】盒-盒 / 球-球 / 球-盒"球心在盒外"三个分支逐位未变（改动被限定在 `dist<1e-9`）

**1) 位置**：`loom_physics.py:303-329`、`:331-343`、`:372-376`

**2) 契约/预期**：SCAN_PROTOCOL §2「默认值/分支改变是否波及其他语义」；B2"与盒-盒最小穿透轴一致"隐含"盒-盒行为不变"。

**3) 路径枚举（证伪）**：把旧实现（`git show f53a82a` 原文）复制成独立函数，与新实现做**逐位差分**：
- 盒-盒随机 400 组（有相交的样本）
- 球-盒"球心在盒外"随机 110 组
**4) 实际行为**：
```
$ python Loom/tests/_tmp/beta3_scan_06_pushout.py
  盒-盒随机组逐位差异数 = 0 (0 = 盒-盒分支行为完全未变)
PASS 盒-盒分支行为逐位未变  diff=0
$ python Loom/tests/_tmp/beta3_scan_06_pushout2.py
=== F2. 球-盒 且球心明确在盒外 (至少一轴超出 AABB) 的差分 ===
  n=110, 逐位差异=0
PASS 球心在盒外的球-盒分支行为逐位未变  diff=0
```
（首次 F 组曾有 28/104 差异，原因是采样把 `x∈[0.9,1.0)` 的"球心其实在盒内"样本混进来了；改用"至少一轴超出 AABB"的口径后归零——这条修正过程本身留痕，防止把采样错误当成代码缺陷。）
**5) 差异**：0。
**8) 判定**：**P-DISPROVED**。改动面严格限定在 `dist<1e-9` 分支。

---

### P-06-12 【P-DISPROVED】脚本硬编码常量与场景真值一致（速度 4.0/4.0、豆 58、格 11×11、墙 0.92×0.6、球半径 0.25、eat_r 0.5）

**1) 位置**：`pacman_player.py:18-20`、`pacman_ghost.py:18-21`、`docs/audit/pacman2d_scene.json`

**2) 契约/预期**：任务书要求"硬编码常量是否与场景 JSON 实际数据一致（校验真值，不照抄注释）"。

**4) 实际行为（实测真值）**
```
$ python Loom/tests/_tmp/beta3_scan_06_ghost.py
场景真值: 墙=63 豆=58 幽灵=3 玩家=吃豆人
出生格=(1, 0) 可达格数=58/58
PASS 所有豆子从出生格可达 (通关判定可达成)  []
PASS 豆子格与墙格无交集
幽灵出生格: [(-4, -4), (4, -4), (-4, 4)]
PASS 幽灵出生格都是通路格
PASS 每个幽灵出生格的非反向邻居 >= 1 (避免 _choose_dir 兜底乱走)  [2, 2, 2]
死胡同格数 (只有 1 个通路邻居): 0 []
=== 常量 vs 场景真值 ===
玩家脚本 vars: {'speed': 4.0, 'eat_r': 0.5}  参数默认: speed=4.0 eat_r=0.55 invuln=1.5
PASS 玩家速度: 场景 4.00 == 脚本默认 4.0
PASS 双方速度一致 (玩家 4.00 / 幽灵 [4.0, 4.0, 4.0])
PASS eat_r 场景值 0.5 < 半格 0.5 -> 只吃当前格豆
玩家球半径(世界)=0.250, 幽灵球半径=0.250, 硬编码捕获半径=0.55
墙: cube size=1.0 * scale=[0.92, 0.6, 0.92] -> 半宽 0.46, 高 0.60, 中心 y=0.30
地板: plane 10.0x10.0 * scale [3.0, 1.0, 3.0] -> 顶面 y=0.00
PASS 玩家球 y=0.3 r=0.25 底面 0.05 > 地板 0 -> 初始不与地板/墙相交
```
迷宫（由 JSON 反解，z 行 → x 列，`#`=墙）：11×11 边界封闭、格心整数、共 63 墙 / 58 豆，58 个豆格全部可从出生格 (1,0) BFS 到达。
**5) 差异**：无（`eat_r` 场景覆盖脚本默认 0.55→0.5，两者都不跨格，行为等价）。
**8) 判定**：**P-DISPROVED**（常量与真值一致；"速度双方 4.0"正是 `734eccc` 的修复目标）。

---

### P-06-13 【P-DISPROVED】通关暂停不会冻结 UI 输入（编辑器/VK 两侧），`set_logic_paused` 冻结的是逻辑帧而非输入帧

**1) 位置**：`pacman_player.py:73-83`；`engine.py:834-836,1249-1294`；`scene_driver.py:644-650,684-693`；`loom_render.py:702-732`

**2) 契约/预期**：B4「通关（吃完可见豆 -> 暂停 + 面板）」⇒ 面板必须还能点（否则暂停即死锁）。

**3) 路径枚举（证伪：证明"暂停不会连带冻结 UI 派发"）**

| # | 运行时 | 逻辑帧冻结点 | UI 鼠标派发点 | 是否被 `_logic_paused` 拦住 |
|---|---|---|---|---|
| 1 | 编辑器 | `engine.advance_logic` `:1277-1294` 早退 | `editor._update_camera`:2339 → `_dispatch_ui_mouse`（在 `:2335` 的 `is_playing` 判断**之前**；`:2343` 播放态早退发生在 dispatch **之后**） | ❌ 不拦 |
| 2 | VK 播放器 | `scene_driver.advance_logic` `:691-693` 早退（先 `_end_frame_input()`） | `vk_player.py:397` `ui_bridge.begin_frame()`（渲染循环内，与 logic 无关） | ❌ 不拦 |
| 3 | GL 播放器 | `loom_render.py:713-723` 冻结时钟 | 无派发点 | 不适用（见 P-06-01） |

**4) 实际行为**：暂停后 `_logic_paused`/`logic_paused` 只让时钟停走 → 脚本/物理/动画不走；UI 派发仍按渲染帧进行。
**5) 差异**：无（就"暂停不冻结 UI"这一断言成立）。
**6) 触发条件**：—
**7) 验证**：`python Loom/tests/_tmp/beta3_scan_06_pacman.py` 的第 4 段（通关后 `stub.paused is True`、面板 `visible=True`），加上述四处行号路径枚举。
**8) 判定**：**P-DISPROVED**。
**残留观察（P3，跨模块，供引擎侧裁决）**：`engine.set_logic_paused`（本轮新增，`engine.py:834`）与 `engine.toggle_logic_paused`（`:1313-1329`）**语义不等价**——后者在暂停边界做 `self._clock.reset()`、`_interp.align()`、`_render_world = None` 三件收尾，前者只置标志。脚本走的是前者 ⇒ 暂停/恢复边界少了"清 accumulator + 对齐插值"，理论上恢复瞬间可能多补一帧。**建议**：把"暂停边界收尾"下沉成一个共享内部方法供两个入口调用，或让 `set_logic_paused` 复用 `toggle_logic_paused` 的收尾逻辑。

---

### P-06-14 【P-PROVED · P2】`invuln` 参数是死参数：`params` 声明可调（默认 1.5），`update` 里硬编码 `1.5`，改场景值/面板值一律无效

**1) 位置**：`pacman_player.py:20`（`("invuln", "复活无敌秒", 1.5, 0.0, 5.0, "%.2f")`）vs `:161`（`self._invuln = 1.5`）；`self.vals["invuln"]` 在全文**从未被读取**（`grep -n invuln` 只命中 20/26/123/124/161 行）。

**2) 契约/预期**：B4（handoff §2.4 + 变更清单 `15718a5`）："复活无敌 1.5s…invuln 参数（默认 1.5s）"；
脚本 `params` 表是**引擎/编辑器的可调参数契约**（`scripts.py:202,215-216`：`params` 生成 `vals`），声明即可调。

**3) 路径枚举（证伪：证明"参数确实生效"）**

| 路径 | 进入条件 | 结果 |
|---|---|---|
| 3-a | 场景 `scripts[].vars` 给了 `invuln` | 仅写进 `vals["invuln"]`；`:161` 不读 ⇒ 无效 |
| 3-b | 编辑器面板改参数 | 同上 ⇒ 无效 |
| 3-c | `:123-124` 递减 | 递减的是 `self._invuln`（唯一写入点 `:161`）⇒ 恒从 1.5 起 |

**4) 实际行为（正手，三档取值实测）**
```
$ python Loom/tests/_tmp/beta3_scan_06_invuln.py
vals['invuln']=1.5  ->  捕获后 _invuln=1.5000, 下一次被抓于 1.5167s (实测无敌时长)
vals['invuln']=5.0  ->  捕获后 _invuln=1.5000, 下一次被抓于 1.5167s (实测无敌时长)
vals['invuln']=0.2  ->  捕获后 _invuln=1.5000, 下一次被抓于 1.5167s (实测无敌时长)
```
（幽灵被强制压在出生点，构造"复活即被咬"的最坏情形；无敌时长按"下一次被抓的时刻"实测。）

**5) 差异**：预期 `invuln=0.2` 时 0.2s 就能再被抓、`5.0` 时 5s 内免疫；实际三档全部 1.5167s —— 参数被彻底忽略。
**6) 触发条件**：任何试图调这个参数的场景/面板操作（本场景未设置 `invuln`，所以线上恰好"看起来正常"）。
**7) 验证**：见第 4) 段命令。
**8) 判定与等级**：**P-PROVED，P2**（"可调参数"承诺失效；属 AUDIT-DEADCODE）。
**修复方向**：`:161` 改读 `float(self.vals["invuln"])`（并在 `on_start` 打印/校验一次范围）；保留"无敌期内跳过捕获判定"（`:155`）与 `caught` 计数语义不变。
必须保持：默认值仍 1.5（B4 与 handoff 的对外承诺）、`params` 表的 min/max 区间（0.0~5.0）。

---

### P-06-15 【P-DISPROVED】通关判定边界（`total=0` 永不通关；`score` 不会超过 `total`）

**1) 位置**：`pacman_player.py:179` `if self.total and self.score >= self.total: self._win()`

**3) 路径枚举（证伪）**

| 路径 | `total` | `score` 变化 | 结果 |
|---|---|---|---|
| 3-a | 0（无豆场景） | 恒 0 | 永不通关 ⇒ 有意守卫（`if self.total and` 短路），不是死锁（玩家仍可退出） |
| 3-b | 58 | 每帧对每个未吃豆 +1（吃掉后 `visible=False` 且 `:173-174` 跳过） | 单调 +1，最多 +58 |
| 3-c | 58 + 玩家吃豆半径跨格 | `eat_r=0.5` < 半格距离 0.5 ⇒ 只在当前格吃掉 1 颗 | 无重复计数 |
| 3-d | 通关后 | `:121-122` `if self.won: return` | 不再计分/不再 `_win()` 重入 |

**4) 实际行为**：C4 实测 `score=1 / total=1` → `won=True`，随后 120 帧 `update` 早退（`score` 与物体数都不变）。
**5) 差异**：无。
**8) 判定**：**P-DISPROVED**。


---

## 3. 统计

### 3.1 数量表

| 项目 | 数量 |
|---|---|
| 粗筛疑似项 | **15**（P-06-01 … P-06-15） |
| 跳过项（留痕） | **10**（SKIP-01 … SKIP-10，见 §1.2） |
| P-PROVED | **8**（01, 02, 03, 04, 05, 06, 07, 14） |
| P-DISPROVED | **6**（09, 10, 11, 12, 13, 15） |
| P-UNKNOWN | **1**（08） |
| P-CONTRADICTION | **0**（初判 1 例：P-06-02；按方法论 §5.4/§9.2 查链后消解，见该项第 8 段） |

### 3.2 等级分布（仅 PROVED）

| 等级 | 数量 | 编号 |
|---|---|---|
| P0（安全/崩溃） | 0 | — |
| P1（功能错误） | **1** | P-06-01（GL 播放器 UI 按钮全失效） |
| P2（边界/潜伏功能） | **4** | P-06-02（同分翻面）、P-06-03（位移放大 5.9×）、P-06-05（幽灵同格抖动）、P-06-14（invuln 死参数） |
| P3（可维护性/验证缺口） | **3** | P-06-04（无回归覆盖）、P-06-06（重开点亮隐藏豆）、P-06-07（命名/格心隐式契约） |

[REGRESSION]（本轮引入）：**1 项** — P-06-01；**部分 REGRESSION**：P-06-03（位移量级放大）。
其余 PROVED 项属"本轮新增代码自带缺陷"（吃豆人两个脚本是本轮新文件）或"本轮修复没覆盖到的旧偏差"。

### 3.3 关于"某类为 0"的解释（方法论 §11.3 硬要求）

- **P-UNKNOWN = 1（不为 0）**：P-06-08。它需要的不是推演而是**一条外部信息**（发布场景文件或其哈希），
  这条信息缺失本身来自仓库事实（`Projects/` 不存在、`git ls-files`/`git log --all` 皆空）⇒ 判 UNKNOWN 而不是猜 DISPROVED。
  另有两处"本场景不可达的潜伏路径"（P-06-10 的孤立格兜底、P-06-13 的暂停边界收尾差异）：
  它们的**当前行为**已被实测证伪，只是未来场景可能触发，故写在各项"残留观察"里而不是升格成 UNKNOWN，理由已逐条写明。
- **P-CONTRADICTION = 0**：本模块改动面极窄（一个 `if` 分支），"两条链都闭合"的项只有 P-06-02 一例；
  它的证伪链第 3 段漏了 B2 注释的第二个判据维度，被当场找出漏洞 ⇒ 按方法论"禁止两说并存"消解为窄口径 PROVED。
  **后来者若把 P-06-02 直接当"没事"关掉，就是把矛盾选边站**（方法论 §9.2 失败模式之"矛盾无视"），此处留证。

### 3.4 本轮报告自审 checklist（方法论 §11.5）

```
[x] §7 八条硬要求（基准唯一/代码原样/路径完备/预期-实际对照/命令可跑/措辞可审计/跳过留痕/矛盾不忽略）
[x] 每条链只引用 B1-B4 四类判定基准，未混用外部标准
[x] 每条证伪链第 3 段都是路径枚举表（P-06-01 运行时矩阵、P-06-02 六面向量、P-06-03 三路径、
    P-06-04 覆盖表、P-06-05 相遇拓扑表、P-06-07 护栏表、P-06-09/10/11/13/15 各自枚举）
[x] 每条证真链第 7 段都可跑（探针文件 + 命令 + 粘贴的实测输出）
[x] 跳过登记表 10 条，每条给四类理由之一 + 出处
[x] P-UNKNOWN 数量 = 1（不为 0）并解释
[x] P-PROVED 数量 = 8（不为 0）
[x] 出现过的 P-CONTRADICTION 已查明哪条链有漏洞（P-06-02 证伪链漏维度）
[x] P-PROVED 未写修复代码（只给方向 + 约束 + 波及面）；本轮未改任何受跟踪文件
[x] 人类裁决项都是封闭问题（选 A / 选 B）
[x] 全文无"我认为/经验上/看起来/应该是"（除引用他人注释原文处）
```

---

## 4. 修复建议排序（只给方向，不含可直接替换的实现）

> 排序依据：先"玩家可感知的坏"（P1），再"潜伏但会突然咬人"（P2），最后可维护性（P3）。
> 同一函数的多个问题建议**同批次改**（审一次、测一次），否则互相掩盖。

| 序 | 关联项 | 建议动作（方向） | 必须保持的白盒契约 | 波及面 |
|---|---|---|---|---|
| 1 | P-06-01 | 给 GL 播放器补"每帧把本帧新按下/松开交给 `self.ui.dispatch_mouse`"的链（位置：`runtime.py` 或 `loom_render.py` 渲染帧入口），语义对齐 `editor._dispatch_ui_mouse` | `dispatch_mouse` 唯一入口；每帧一次、帧首清空；播放态相机不被吞 | run_player(gl) / game_player / 所有 Canvas 按钮场景 |
| 2 | P-06-02 + P-06-03（同函数同批） | `loom_physics._push_out` 的 `dist<1e-9` 分支：①同分给显式稳定规则；②`a_is_sphere=False` 时补方向取反；③必要时钳制单次位移 | 最短路径语义；`+1e-4` 缓冲；外部分支逐位不变；`a` 是球时一次必分离 | resolve_collisions / move_with_collision / legacy 物理 / 所有 plane 地面 |
| 3 | P-06-04 | 补 6 种几何的**推挤断言**（扩 `test_collision_edges.py` 或新建 `test_collision_inside.py`），风格沿用独立脚本 | 不引入 pytest 收集；与第 2 序同批提交 | 回归基线（handoff §5 的 10/10 需重算） |
| 4 | P-06-14 | `pacman_player.py:161` 改读 `float(self.vals["invuln"])` | 默认 1.5、范围 0~5、无敌期跳过捕获、`caught` 计数语义 | 吃豆人调参、编辑器参数面板 |
| 5 | P-06-05 | `pacman_ghost._avoid` 在"距离≈0"时做非对称让位（或 `_choose_dir` 对同格降权） | `avoid_cd` 语义；走廊不入墙；不新增引擎 API | 幽灵 AI（未来追逐 AI 会放大该缺陷） |
| 6 | P-06-06 | `on_restart` 只恢复本局吃掉的豆 + 重算 `total` | `total=0` 守卫；`_win` 唯一入口 | 分关卡/隐藏豆关卡 |
| 7 | P-06-07 | 命名/格心契约写进关卡模板与文档；解析失败打一次告警；首帧显式对齐坐标 | 不改场景数据；不改 `_open` 语义 | 建关工作流、关卡复制/改名 |
| 8 | P-06-10 残留 | `_choose_dir` 孤立格兜底 `cands=[(1,0)]` 改为"原地 + 告警" | 不改正常分支的随机性 | 未来关卡（当前场景不可达） |
| 9 | P-06-13 残留 | `engine.set_logic_paused` 复用 `toggle_logic_paused` 的暂停边界收尾（`_clock.reset`/`_interp.align`/`_render_world=None`） | 两个入口对外签名不变；GL/VK 语义等价 | 任何脚本暂停（吃豆人是第一个用户） |
| 10 | §0.5 事实 | 把"碰撞/物理测试必须 `python tests/x.py` 逐个跑，`pytest` 会 INTERNALERROR"写进 `Loom/tests` 的 README/run_all | — | 后续所有回归执行方式（否则易出假绿/假红） |
| 11 | P-06-08 | 闭合 UNKNOWN：提供发布用场景文件或 `游戏包.lsc` 解包场景/哈希 | — | 本报告结论的可信边界 |

### 4.1 动手前需确认的点（真正需要人类拍板的路线分叉；其余按推荐默认即可）

| # | 分叉 | A | B | 我建议的默认 |
|---|---|---|---|---|
| **D1** | GL 播放器的 UI 按钮怎么救（P-06-01） | **A：给 GL 播放器补 UI 鼠标派发链**（治本，三后端语义统一） | B：让该类游戏强制走 VK，或 C：脚本加键盘重开作兜底 | **A**（B/C 只能掩盖） |
| **D2** | `_push_out` 同分/零厚度轴偏好（P-06-02） | **A：显式规则——同分时偏向"球心相对盒中心更靠外的一侧"，完全对称再取 +y** | B：保持现状，只把注释改成"同分方向未定义"（承认不稳定） | **A** |
| **D3** | `a` 是盒时的单次位移（P-06-03） | **A：只补方向取反，不钳制**（保持"一次推干净"语义） | B：同时钳制到 ≤ 盒最小半边长（更稳，但可能多迭代几次） | **A**（先对齐方向，量级交给迭代） |
| **D4** | 幽灵同格（P-06-05） | **A：固定序号让位（确定、可复现）** | B：`_choose_dir` 对"目标格有同伴"降权（更自然，但依赖随机） | **A** |
| **D5** | 回归测试落点（P-06-04） | A：扩 `test_collision_edges.py` 的 A2 段（已有盒-球构造） | **B：新建 `test_collision_inside.py`** | **B**（议题独立、便于单独跑） |
| **D6** | 场景真值如何入库（P-06-08） | A：把 `Projects/PacMan2D.json` 纳入仓库（可审计，仓库 +156KB） | **B：只入库出包场景哈希/校验清单** | **B**（不扩仓库体积又能闭合审计） |

---

## 5. 需要人类裁决的封闭问题（各"选 A 还是选 B"）

**Q1（P-06-01，P1）** 通关面板在 GL 播放器里点不动：是
**A. 给 GL 播放器补一条 UI 鼠标派发链**（三后端语义统一；改动在 `runtime.py`/`loom_render.py`，需回归编辑器与 VK 的既有 `ui_consumed` 语义），还是
**B. 不改引擎，改为让吃豆人这类"面板驱动"的游戏强制使用 VK 后端**（改动在游戏配置/发布流程，代价是 GL 后端永久不支持 UI 按钮）？

**Q2（P-06-02，P2）** `_push_out` 在"球心正好在盒面/盒中心/零厚度轴上"这类同分情形：是
**A. 补一条显式、确定的破同分规则**（例如优先"球心相对盒中心更靠外的一侧"，完全对称时取 +y；可预测、可写测试，但属行为变更，需要新回归基线），还是
**B. 算法不变、只把注释与文档改成"同分时方向未定义"**（零行为风险，但把"1e-9 就翻面、可能从地板下方推出"固化进契约）？

**Q3（P-06-08，P-UNKNOWN）** 场景侧常量校验只能对 `docs/audit/pacman2d_scene.json`（SHA256 `D34A1E44…`）做，因为 `Projects/PacMan2D.json` 从未入库：是
**A. 把发布场景文件纳入仓库**（以后每次审计都能对真值校验，仓库多约 156KB），还是
**B. 只在发布流程产出并入库"场景哈希清单"**（体积小，但审计仍需人工取到场景本体才能复算）？

---

### 附：探针清单（可复跑）

| 探针 | 用途 | 关键结论 |
|---|---|---|
| `Loom/tests/_tmp/beta3_scan_06_scene.py` | 场景 JSON 结构/迷宫/墙豆真值 | 63 墙 / 58 豆 / 3 幽灵 / 11×11 / 墙 0.92×0.6 |
| `beta3_scan_06_pushout.py` | 新 vs 旧 `_push_out` 差分 | 盒-盒 diff=0；球心在盒内 5 用例 NEW 全分离、OLD 3 个推不出 |
| `beta3_scan_06_pushout2.py` | 外部分支差分 + 同分敏感性 + 位移量级 | 外部 diff=0/110；±1e-9 翻面；放大 5.9×/∞ |
| `beta3_scan_06_pacman.py` | 玩家脚本（网格/捕获/通关/重开/退出） | 24 组×1200 帧无穿墙；通关/重开/退出/无敌边界全 PASS |
| `beta3_scan_06_ghost.py` | 幽灵不变量 + 常量校验 + BFS 可通关性 | 200s 0 入墙；同格同向 3s 完全重合 |
| `beta3_scan_06_ui.py` | UI 派发链路（静态 + 功能对照） | GL 播放器 0 处 dispatch_mouse；click 只经 dispatch_mouse |
| `beta3_scan_06_cov.py` | 10 个测试对改动分支的覆盖 | 只有 test_physics.py 命中 1 次 |
| `beta3_scan_06_floor2.py` | 定位那 1 次命中 | 球被向下推 0.5002（穿到 y=-1 地面下方） |
| `beta3_scan_06_invuln.py` | `invuln` 参数是否生效 | 三档取值无敌时长恒 1.5167s ⇒ 死参数 |

（全部为一次性探针，位于 gitignore 的 `Loom/tests/_tmp/`，无产品代码 import 它们；跑完保留供复核，可随时删除。）

---

## 6. 修复记录（第 6 批 · 修复轮）· 2026-11-08

> 本章是**修复轮**留痕（审计轮的结论在 §0–§5，未改动）。
> 本轮只改下列文件：`Loom/loom_physics.py`、`Loom/scripts/pacman_player.py`、`Loom/scripts/pacman_ghost.py`、
> 新增 `examples/PacMan2D.json`、新增 3 个测试 `Loom/tests/test_pacman_*.py`。
> **未**动 `Loom/runtime.py`（P-06-01 已划给第 3 批 02 号，见 §6.4）、未动 `Projects/`、未改 `.gitignore`（实测无需，见 §6.3）。

### 6.1 修复项 → 缺陷编号 → 证据

| # | 缺陷 | 文件:行（修后） | 改法（方向） | 修前 | 修后 | 回归测试 |
|---|---|---|---|---|---|---|
| 1 | **P-06-02**（D12=A）同分不稳定 | `Loom/loom_physics.py:37-41`（阈值常量 `_PUSH_TIE_EPS=1e-9`）、`:367-390` | 在"球心在盒内"选面循环里补**显式破同分**：仍取最小距离；两面等距（`|lo-hi|<=1e-9`）时朝"远离盒中心"一侧（与盒-盒分支 `:320-322` 同源）；球心正在盒中心时固定取 **+** 侧；跨轴同分沿用轴序优先 | 球心在 y=0.25 的低墙中分面 → 被推到 **-0.2501（地板下方）**；球在立方体中心 → 推到 **-1.2001（-x）** | 同输入 → **+0.7501（+y，抬出）**；立方体中心 → **+1.2001（+x）**；零厚度平面 → **+0.2001** | `test_pacman_inside_push.py` 1-1/1-2/1-3/1-4 |
| 2 | **P-06-03** 盒-球方向未取反 | `Loom/loom_physics.py:395-399` | 与"球心在盒外"分支（`:403-404`）同语义：`a` 是盒时把推出向量取反，让**盒**远离球 | 球心 (0.9,0,0) 在盒内：盒被推向 **+0.3001** 且**仍重叠**；深处 (0.02)：**+1.1801 且仍重叠** | 盒被推向 **-0.3001 / -1.1801**，**一次调用即分离**，位移量 = 几何最小分离量 | `test_pacman_inside_push.py` 2-1(a/b) + 护栏 2-2/2-3 |
| 3 | **P-06-14** invuln 死参数 | `Loom/scripts/pacman_player.py:174-176` | 捕获时读 `self.vals['invuln']`（`max(0.0, …)`），不再硬编码 1.5 | `invuln` 取 0.2/1.5/5.0 → 无敌时长恒 **1.5167s** | 0.2 → **0.2167s**；1.5 → **1.5167s**；5.0 → **5.0167s** | `test_pacman_scripts.py` 1-1/1-2/1-3 |
| 4 | **P-06-05** 幽灵同格同向长期重合+抖动 | `Loom/scripts/pacman_ghost.py:76-134` | `_avoid` 加**方向判据**（只有同伴在我**前方**、点积>0 才让位）+ **同格序号仲裁**（距离²≤1e-4 时只有 models 下标大的掉头，小下标本帧不改状态 ⇒ 与 update 顺序无关） | 同格同向 3s：距离恒 **0.0000**、方向翻转 **26 次** | 3s：最小距离 **0.1333**、最大 **11.31**、末帧 **8.03**、翻转 **3 次** | `test_pacman_scripts.py` 2-1/2-2 + 护栏 2-3 |
| 5 | **P-06-06** 重开点亮设计隐藏豆 | `pacman_player.py:28-33`（`_beans`/`total`）、`:99-101`（`on_restart`） | `on_start` 记录"本局目标豆"列表；`on_restart` 只恢复这些 | 57 颗设 `visible=false` 时，restart 后可见 = **58** | restart 后可见 = **1**（= total），隐藏豆仍 **57** 颗隐藏 | `test_pacman_scripts.py` 3-1/3-2/3-3 |
| 6 | **P-06-07** 墙名解析静默 | `pacman_player.py:49-53`、`pacman_ghost.py:40-44` | 解析失败计数，`on_start` 末尾打**一条**告警（不再静默 `pass`） | 无任何输出 | `[吃豆人] 墙名不合规, 已忽略 2 个 (需要 墙_<整数x>_<整数z>)` / `[幽灵] 墙名不合规, 已忽略 2 个 …` | `test_pacman_scripts.py` 4-1/4-2 |
| 7 | **P-06-08**（D13=A）场景未入库 | 新增 `examples/PacMan2D.json` | 按人类裁决放 `examples/`（不动 `Projects/` 的忽略约定） | `examples/` 不存在 → 测试 1-1 红 | 入库 156259 B，与审计快照**同 SHA256** | `test_pacman_scene_contract.py` 全绿 |

### 6.2 10 个物理回归测试的位形差异（D12=A 要求"记录"）

修前/修后各跑一遍，逐文件 `Compare-Object`：

| 测试 | 结果 | 输出差异 |
|---|---|---|
| test_collision.py | PASS, exit=0 | **逐行完全一致** |
| test_collision_edges.py | PASS, exit=0 | **逐行完全一致** |
| test_scripts_collision.py | PASS, exit=0 | **逐行完全一致** |
| test_collision_events_small_scene.py | PASS, exit=0 | **逐行完全一致** |
| test_physics.py | PASS, exit=0 | 仅 1 行 `RigidbodyComponent object at 0x…`（内存地址） |
| test_physics_bridge.py | PASS, exit=0 | **逐行完全一致** |
| test_physics_runtime.py | PASS, exit=0 | **逐行完全一致** |
| test_physics_body_init.py | PASS, exit=0 | 仅 1 行 `bits={…}`（内存地址作 key） |
| test_physics_pipe_errors.py | PASS, exit=0 | 仅 1 行 `<__main__._BoomBridge object at 0x…>`（内存地址） |
| test_scene_driver_physics_log.py | PASS, exit=0 | **逐行完全一致** |

**为什么一位小数都没变**：全套 10 个文件里"球心在盒内"分支只被命中 **1 次**（`test_physics.py` 第 4 节，
球心 (0,-0.4999,0) 落在立方体 A 内），而那一次 `lo=0.5001 != hi=1.4999` **不是同分**、且 `a` 是**球**
（不走新加的取反）⇒ 方向与位移都不变（修后仍 `dy=-0.5002`，见 `Loom/tests/_tmp/fix06_floor2_post.log`）。
这同时说明：**新加的断言是本分支唯一的栅栏**（P-06-04 的缺口已由 `test_pacman_inside_push.py` 补上）。

### 6.3 examples 场景与 SHA256 对照（D13=A / P-06-08）

| 角色 | 路径 | 字节 | SHA256 |
|---|---|---|---|
| 场景快照（入库，本次新增） | `examples/PacMan2D.json` | 156259 | `d34a1e44d1ec78e9cabcc836b5e9bbaa2072eac9ef008d2fffb88a3b53963752` |
| 审计基线（既有入库副本） | `docs/audit/pacman2d_scene.json` | 156259 | `d34a1e44d1ec78e9cabcc836b5e9bbaa2072eac9ef008d2fffb88a3b53963752` |
| **发布物**（出包机侧，待补） | `Projects/PacMan2D.json` 或 `游戏包.lsc` 解包场景 | — | **待出包机补**（仓库里没有，见 §2 P-06-08） |

- 复核命令：`python Loom/tests/test_pacman_scene_contract.py`（1-3 断言两者同哈希；任一漂移即变红）。
- `.gitignore`：实测 `git check-ignore -v examples/PacMan2D.json` **未命中任何规则**（返回非 0），故按"仅加 examples 例外"的许可**没有**修改 `.gitignore`（改了就是无意义规则）。
- 闭合方式：出包机对产物算一次 SHA256，与上表比对即闭合 P-06-08；本批不臆造该值。

### 6.4 移交：GL 播放器缺 UI 鼠标派发的"最小接入点"（供第 3 批 02 号，P-06-01）

> 本批**不改** `Loom/runtime.py`。以下只给接入位置与必须保持的契约，不含实现代码。

1. **接入点（二选一，推荐后者）**
   - `Loom/runtime.py` 的 `PlayerApp`：新增一个"每渲染帧调用一次"的 UI 输入分发方法；
   - `Loom/loom_render.py` 渲染帧入口（`render()` 开头，世界矩阵/绘制之前）：一处即覆盖"GL 播放器 + 打包版 opengl 分支"两条运行路径。
2. **需要的最小数据**：本帧**新按下**、本帧**新松开**的鼠标键集合 + 当前鼠标位置 + 本帧滚轮。
   GLFW 侧已有这些状态（`Loom/loom_glfw_window.py` 维护 `mouse_pos / buttons / pressed / released` 类语义）；
   语义范式可直接照抄 `vk_ui.UIInputBridge`（`vk_ui.py:792-890`："回调只缓存 → 帧首一次 dispatch"）。
3. **调用形状**：`self.ui.dispatch_mouse(pos, pressed, released, wheel)` → 若返回 False 再 `self.ui.update_hover_only(pos)`；
   把返回值记进 `self.ui_consumed`，供相机/拾取逻辑跳过（对齐 `editor.py:567-592` 与 `:2346-2348`）。
4. **必须保持的白盒契约**
   - `UIManager.dispatch_mouse` 是**唯一**入口（`loom_ui.py:617` 的 `on_mouse_up` 是按钮点击的唯一触发点）；
   - 每帧最多一次、帧首清空 pressed/released（与 VK 侧同语义，避免"一次点击触发两次"）；
   - 播放态相机不被 UI 吞掉，只有 UI 命中时才 `ui_consumed=True`；
   - `PlayerApp` 仍是"无编辑器 UI"，只加输入派发，不要引入编辑交互。
5. **不要做的**：不要把 `vk_ui.UIInputBridge` 整个搬到 GL（它带着 VK 侧的滚轮/命中超宽表判据）；不要用"脚本里加键盘重开"绕过（那会改掉 handoff §2.4 的 UI 契约，属路线选择，见 §5 Q1）。
6. **验收建议**：起 `PlayerApp`（或 GL 播放器）加载 `examples/PacMan2D.json`，把通关面板设为可见后合成一次"按下+松开"，
   断言 `pacman_player.score/caught` 被复位（on_restart 生效）；再在编辑器与 VK 各回归一次，确认 `ui_consumed` 语义未变。

### 6.5 审计阶段的结论修正（诚实留痕，不改历史结论口径）

- **P-06-03 的"位移放大 5.9×"** 经修复轮实测需要修正表述：`1.1801` 正好等于该位形的**几何最小分离量**
  （球心 0.02 在 2×2×2 盒内，盒沿 -x 走到 `box.max = 球.minx` 需 1.18）。也就是说量级本身不是缺陷，
  **真正的缺陷是方向**（旧代码朝球那侧推，位移白费且不分离）。审计轮把它描述成"放大"是口径偏差，
  修复按 D3=A 只改方向、不钳制；新测试把"位移量 = 几何最小分离量"写成断言固化（`test_pacman_inside_push.py` 2-1 第三条）。
- **P-06-02 的"±1e-9 翻面"** 同样需要精确化：跨越中分面时方向按"真实最近面"翻转是**数学正确**的；
  被修掉的是**恰好同分**时的非确定性（浮点噪声决定方向、可把物体塞到地板下方）。修后：
  精确同分 → 固定 +侧；`y-1e-9` → 仍按真实最近面取 -y（`fix06_pushout2_post.log` G 段第三行），这是预期行为，不是回归。

### 6.6 本批新增测试（跑法必须逐个 `python`，pytest 会把它们也当模块导入而不执行/或直接中断）

| 文件 | 覆盖 | 检查点 | 修前 → 修后 |
|---|---|---|---|
| `Loom/tests/test_pacman_inside_push.py` | P-06-02 / P-06-03 | 15 | **8 FAIL** → ALL PASS |
| `Loom/tests/test_pacman_scripts.py` | P-06-14 / P-06-05 / P-06-06 / P-06-07 | 12 | **8 FAIL** → ALL PASS |
| `Loom/tests/test_pacman_scene_contract.py` | P-06-08 / P-06-12（持续校验） | 17 | **1 FAIL**（examples 缺失）→ ALL PASS |

三个文件都是仓库既有风格（独立脚本 + `check()` + `FAIL` 闸门 + `sys.exit`），已被 `tests/run_all.py` 的
`glob("test_*.py")` 自动纳入（`run_all.py:18`）。

### 6.7 剩余未解决项（本批未动，需要别的批次或人类输入）

| 项 | 状态 | 说明 |
|---|---|---|
| P-06-01 GL 播放器 UI 派发 | **未修（移交第 3 批 02 号）** | 接入点见 §6.4；本批不动 `runtime.py` |
| P-06-08 发布物哈希 | **半闭合** | 场景已入库且与快照同哈希；发布物侧仍需出包机补一次 SHA256 |
| P-06-10 残留：孤立格兜底 `cands=[(1,0)]` | 未修 | 当前场景不可达（BFS 0 死胡同），风险留给未来关卡设计；本批不顺手改 |
| P-06-13 残留：`engine.set_logic_paused` 与 `toggle_logic_paused` 收尾不一致 | 未修 | 属引擎核心（`engine.py`），不在本批文件清单内 |
| 审计探针 `_tmp/beta3_scan_06_pacman.py`、`_ghost.py` | 已过期 | 它们断言的是**修复前**行为（如"restart 后 58 颗可见"、"两幽灵完全重合"），留着作历史证据；请勿当回归跑，回归以 §6.6 的三个新测试为准 |
