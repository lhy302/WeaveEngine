# 编辑器与 Agent 可视化链 扫描报告（beta3 补丁回归审计）

- 报告编号：**beta3_scan_04**
- 审计对象：`git diff f53a82a..HEAD`（29 个提交，HEAD=62479f0）对我负责的 4 个文件：
  - `Loom/editor.py`（+170 / 共 2301 行）
  - `Loom/ui/loom_gui.py`（+133 / 共 3909 行）
  - `Loom/undo.py`（+96 / 共 1023 行）
  - `Loom/agent_commands.py`（+326 / 共 3036 行）
- 方法：`docs/audit/SCAN_PROTOCOL.md` 三阶段（粗筛 → 双向逻辑推演 → 实操闭环）；判定基准只引用被审对象自身的白盒契约与本项目的**人类裁决**（§0.3）。
- 本轮**只分析不改代码**：报告只写修复方向；唯一新建文件是本报告与 `Loom/tests/_tmp/beta3_scan_04_probe{,2,3,4}.py`（已 gitignore，不被产品代码 import）。

---

## 0. 范围与方法

### 0.1 本轮 diff 要点

| 文件 | `git diff f53a82a..HEAD -- <file>` 的改动要点 |
|---|---|
| editor.py | `ortho/ortho_size` 字段；`_apply_camera` 记录 `_scene_cam` 并套用 fov；进播放强制套用场景相机 + 视口 `setFocus()`；`_request_exit_play` 帧末退出；`focus_on_object/_advance_focus_anim/_cancel_focus_anim`；播放态相机输入冻结；正交投影分支 |
| ui/loom_gui.py | 工具栏红点 + 状态栏进度 + 1.5s 空闲恢复 token；`_refresh_status` 让位保护；`_bind_agent_service` 提前绑定 |
| undo.py | `BatchCommand`；`UndoManager.begin/end/cancel_batch`、`batch_active/batch_size`；`_append` 抽出；`clear()` 复位批次；**Q5=A 快照扩字段**（材质 albedo/PBR/env、法线模式、LOD、prefab_ref、光源 range） |
| agent_commands.py | `agent_batch_begin/end/cancel`、`view_focus`、`key_binding`、`render_api`、`camera_proj`、`_auto_focus`；`AgentService` 节奏化 `drain/_run_one/progress/last_info` |

### 0.2 实跑命令与结果（全部真跑）

| # | 命令 | 结果 |
|---|---|---|
| E1 | `python tests/test_undo_batch.py` | `总结果: ALL PASS`，EXIT=0 |
| E2 | `python tests/test_agent_pacing.py` | `总结果: ALL PASS`，EXIT=0 |
| E3 | `python tests/test_editor_focus.py` | `总结果: ALL PASS`，EXIT=0 |
| E4 | `python tests/test_agent_ui_indicator.py` | `agent UI indicator: ALL PASS`，EXIT=0 |
| E5 | `python tests/test_undo_full_coverage.py` | `总结果: ALL PASS`，EXIT=0（Q5 成对测试） |
| P1 | `python tests/_tmp/beta3_scan_04_probe.py` | 批次配对 + Q5 快照成对性（原文见 §2.1） |
| P2 | `python tests/_tmp/beta3_scan_04_probe2.py` | 播放期相机污染 + set_lod 撤销缺口 + 新命令语义 |
| P3 | `python tests/_tmp/beta3_scan_04_probe3.py` | set_lod bias（选定目标）+ 批次部分失败 + 命令级 Q5 |
| P4 | `python tests/_tmp/beta3_scan_04_probe4.py` | camera_proj 与"场景已改动"判定 |

### 0.3 判定基准清单（证真链只引用这些）

| 基准 | 出处 |
|---|---|
| B1 逐条 120ms 节奏 / 忙态 / 三个 GUI 钩子契约 | `docs/audit/fix_agent_visual_pacing_batch_focus.md` §1-§2 |
| B2 批次撤销契约（begin/end/cancel 语义、悬挂自动 cancel、空批不压栈、end 不重复执行） | 同上 §4 + `docs/audit/_fix_ledger.md:247` |
| **B3 Q5=A 撤销全覆盖（人类 2026-11-07 裁决）** | `docs/audit/_scan_summary.md:87`：「快照纳入光源 range、材质 albedo/PBR/env、法线模式、LOD、prefab 断开；补成对测试」 |
| **B4 Q4=B 场景不是不可信输入（人类裁决）** | `docs/audit/_scan_summary.md:86`：不做全量防御 |
| B5 播放期相机语义（"编辑态乱拖不影响"、播放态禁用相机键鼠） | `docs/handoff/接手总纲_20261107_引擎发布与游戏打包.md` §2.4；`editor.py:1817` 注释；`editor.py:2340-2342` 注释 |
| B6 步进模式 E 已按用户要求**完整移除** | `docs/audit/_fix_ledger.md:280-292` |
| B7 `draw_all(engine, script_host=None)` 双参数契约（VK P0 修复） | `loom_ui.py:694-706` |
| B8 场景相机保存/加载契约（ortho/ortho_size/fov 随场景保存） | `sceneio.py:1049-1058`（写）、`sceneio.py:1109-1118`（读）、`editor.py:954-976`（应用） |

### 0.4 工作树自查（本轮只读）

```
$ git status --porcelain
?? docs/audit/scan_beta3_05_packaging_release.md     <- 另一子代理的报告，非我所为
?? tools/lint_except_dist/                          <- 任务说明中已声明的既有未跟踪文件
?? tools/loom_lint_except.py                        <- 同上
```

- **未修改任何受跟踪文件**（无 `M` 条目，`git diff --stat` 空白）；未执行 add/commit/checkout/stash/reset/clean。
- 我新建的只有本报告与 4 个 `Loom/tests/_tmp/beta3_scan_04_probe*.py`（`Loom/.gitignore:20 tests/_tmp/*`，`git check-ignore -v` 实测确认已忽略）。
- 一次 `git status` 中曾出现 `?? Loom/tests/日志.txt`（播放器日志路径的附带产物，未跟踪），下一次检查已自行消失，未做任何操作。

---

## 1. 粗筛清单（含跳过项留痕）

### 1.1 疑似项（25 条，全部进入阶段二）

| ID | 位置 | 标签 | 初步方向 | 疑点代码事实 |
|---|---|---|---|---|
| C-01 | `editor.py:954-976` / `1817-1823` / `1905-1908` | SEM-MISMATCH, DESIGN-DRIFT | 播放强制套用场景相机后编辑态投影是否被永久改写 | `_apply_camera` 写 `ortho/ortho_size/_fov`，退出播放只还原 `_play_edit_cam` 的 6 个轨道字段 |
| C-02 | `agent_commands.py:1018-1030` + `editor.py:866-881` | SEM-SILENT | 新命令 `camera_proj` 改的属性是否纳入"场景已改动"判定 | `_scene_digest` 调 `scene_to_dict(self, camera=None)`，而 `scene_to_dict` 仅在 camera 是 dict 时补 ortho |
| C-03 | `undo.py:1120-1128` | AUDIT-ASYMMETRY | `cancel_batch` 不清 redo_stack（对照 `_append` 会清） | cancel 只置 `_batch=None` |
| C-04 | `undo.py:1156-1170` + `1106-1118` | IFACE-PARTIAL | 批次进行中调 `undo()` 是否破坏栈配对 | `undo()` 不查 `self._batch`；`end_batch` 走 `_append` 会清 redo |
| C-05 | `undo.py:1138-1145` + `1120-1128` + `agent_commands.py:779-791` | IFACE-PARTIAL, BND-RESOURCE | 批次悬挂期间 push 去哪了 | `push`：批内只 `self._batch.append(cmd)`，不进 undo 栈 |
| C-06 | `undo.py:1072-1074` + `1156-1162` | IFACE-ERROR | 批内某条 undo 抛异常时批次的原子性 | `BatchCommand.undo` 无 try；`UndoManager.undo` 先 pop 再 append redo |
| C-07 | `agent_commands.py:1463-1499` | SEM-SILENT, DESIGN-DRIFT(Q5) | `set_lod {bias}` 是否进撤销栈；报错时是否已改状态 | `r.lod_bias = ` 在 `commit_model` 之外；对非 sphere 返回 error 在改动之后 |
| C-08 | `agent_commands.py:991-1005` + `loom_input.py:272-300` | TOOL-WHITELIST, SEM-SILENT | 改键是否校验动作名；`saved` 是否可信 | `rebind_action` 直接 `self.actions[name]=keys`；写盘异常被 print 吞；`set_action_binding` 恒 `saved:True` |
| C-09 | `agent_commands.py:779-791` vs `fix_agent_visual_pacing_batch_focus.md:49` | AUDIT-DOCIMPL | 返回键名与契约文档是否一致 | 文档写 `had_stale`，实现返回 `cancelled_stale` |
| C-10 | `agent_commands.py:818-855` + `editor.py:2248-2296` | AUDIT-DOCIMPL | `view_focus` 错误文案是否区分真因 | `focus_on_object` 用同一个 False 表示"播放态"与"AABB 取不到" |
| C-11 | `editor.py:1849-1850`、`tests/_tmp/probe_agent_e2e_real.py:12` | AUDIT-DEADCODE | 步进模式 E 移除后是否残留配置/定时器/标志 | 源码 0 命中；探针仍设 `LOOM_AGENT_STEP='0'`；`_dev_cam_*` 只写不读 |
| C-12 | `editor.py:2126-2133` | SEM-SILENT, IFACE-PARTIAL | 帧末退出被裸 except 包住 | `try: self.toggle_play() except Exception: pass`（退出播放=整场景还原） |
| C-13 | `ui/loom_gui.py:1797-1812` | BND-RESOURCE | 1.5s 空闲定时器在窗口销毁后触发 | `_agent_idle` 里 `_refresh_status()` 在 try 之外（另两处 statusBar 调用都在 try 内） |
| C-14 | `agent_commands.py:3322-3357` | BND-CONCURRENCY | 120ms 节奏是否阻塞 UI 线程 | drain 由 QTimer(4ms) 在主线程触发，需确认有无 sleep/长循环 |
| C-15 | `editor.py:976` | SEM-SILENT | `_scene_cam = dict(cam)` 浅拷贝是否被后续改写 | dict 内 target 是可变 list |
| C-16 | `editor.py:2079-2087` | IFACE-UNIT | 正交矩阵参数顺序/坐标系 | `mat4_ortho(np,l,r,b,t,near,far)`；引擎为 +z 前向 |
| C-17 | `editor.py:1827-1832` | AUDIT-DEADCODE | `view.viewport.setFocus()` 是否真有该属性 | 三连 getattr |
| C-18 | `agent_commands.py:1007-1016` + `engine.py:861-884` + `game_settings.py:152-161` | SEM-DEFAULT | `render_api {api:乱写}` 会不会写入坏值 | `write_render_api` 有 normalize 校验 |
| C-19 | `agent_commands.py:579-591` | BND-RESOURCE | 每条 object_add/object_select 都读设置文件 | `guiloader.load_settings('loom')` 每次调用 |
| C-20 | `undo.py:27-66` + `69-122` | DESIGN-GAP(Q5) | `_material_state` 是否漏字段 | Material 有 10 个可写字段，快照取 8 个（不含 name/guid） |
| C-21 | `undo.py:1147-1154` | IFACE-PARTIAL | `push_no_do` 在批次中是否成对 | 批内只 append；redo 时 `BatchCommand.do()` 才补执行 |
| C-22 | `undo.py:1186-1191` | BND-CONCURRENCY | 换场/清栈时批次是否复位 | `clear()` 复位 `_batch/_batch_label` |
| C-23 | `ui/loom_gui.py:3433-3477` | AUDIT-ASYMMETRY | 300ms 轮询会不会盖掉 Agent 进度 | `_agent_status_active` 保护位在物理告警之后 |
| C-24 | `editor.py:2343-2345` | SEM-MISMATCH | 播放态早退是否切掉 UI 分发/gizmo | 早退在 `_dispatch_ui_mouse()` 之后 |
| C-25 | `agent_commands.py:991-1005`（副作用） | TOOL-SCOPE | 改键是否写进**受跟踪**的 `Loom/输入配置.json` | `save_action_bindings()` → `_ACTION_FILE = "输入配置.json"`；`git ls-files` 显示受跟踪 |

### 1.2 跳过登记（5 条，四类可审计理由）

| ID | 位置 | 跳过理由 | 出处 |
|---|---|---|---|
| S-01 | `undo.py:665-864`（`ui_elem_snapshot` / `ui_apply_snapshot` 全 ctype 分支） | **已有回归测试覆盖**（shape 分支为本轮新增成对测试；其余分支非本轮 diff） | `Loom/tests/test_undo_full_coverage.py:100-126`（实跑 ALL PASS，E5）；`git diff` 未触及该区间 |
| S-02 | `editor.py:2151-2167`（`_draw_selection_box`）等渲染辅助 | **白盒契约明确声明**：渲染正确性由 03/04 渲染模块与 A/B 基线负责，不在本模块判定基准内 | `docs/audit/SCAN_PROTOCOL.md` §2；handoff §5 ab_batch 基线 |
| S-03 | `Loom/scripts/pacman_*.py` | **不属于本任务文件清单**（任务书只列 4 个文件），仅作为 `_request_exit_play` 的调用方被引用 | 派单文件范围声明 |
| S-04 | `agent_commands.py:1280-1300`（`_commit` / 变换类命令） | **非本轮 diff + 已有回归覆盖**：`git diff` 该区间为空；真编辑器命令台账 95 条 | `fix_agent_visual_pacing_batch_focus.md:93-97` |
| S-05 | `ui/loom_gui.py:1755-1777`（`_agent_args_summary` / `_agent_tb_visible`） | **已有回归测试覆盖**（摘要 ≤40、截断、显隐切换） | `Loom/tests/test_agent_ui_indicator.py`（E4 ALL PASS） |
---

## 2. 逐项裁决

### 2.1 P-PROVED（11 条）

---

#### P-04-01 [REGRESSION][P2] 播放强制套用场景相机后，编辑态投影参数（ortho / ortho_size / _fov）被改写且退出播放不还原

1) **位置**
   - `editor.py:954-976`（`_apply_camera` 写 `ortho` / `ortho_size` / `_fov` / `_scene_cam`）
   - `editor.py:1813-1815`（`_play_edit_cam` 只装 6 个轨道字段）与 `editor.py:1905-1908`（退出播放只还原这 6 个）
   - `editor.py:1817-1823`（进入播放强制套用 `_scene_cam`）
2) **契约/预期**：B5 —— `editor.py:1817` 注释"播放强制相机：编辑态滑到哪都不影响，一律回到场景相机"，配套语义见 `_play_edit_cam` 注释"编辑器轨道视角, 退出恢复"。隐含后置条件：**进/出播放是编辑态相机的恒等变换**。另 `camera_proj`（本轮新增，`agent_commands.py:1018`）的用途就是"切换主相机透视/正交"。
3) **路径枚举**（全覆盖）
   - 进入播放：`_apply_camera(_scene_cam)` → 写 `ortho`(957)、`ortho_size`(958)、`_fov`(960-965)、`_scene_cam`(976)。
   - 退出播放：只有 `self.camera_target, self.camera_distance, self.camera_yaw, self.camera_pitch, self.camera_roll, self.orbit_mode = self._play_edit_cam`（1906-1907）+ `apply_orbit_camera()`（1908）。**`_fov` / `ortho` / `ortho_size` 无任何还原写入点**。
   - 写点穷举：`grep -n "_fov *= " Loom/editor.py` 只有 963；`ortho` 只有 231/232（init）、957/958（_apply_camera）与读取点 2079；`camera_proj` 写的是 `ed.ortho/ed.ortho_size`。无动态分派。
4) **实际行为**：进入播放把编辑态投影改成场景值；退出后编辑态投影永久等于场景投影。
5) **差异**：预期"编辑态相机进/出播放不变"，实际"投影模式与 fov 被单向覆盖，且无撤销记录、无提示"。
6) **触发条件（最小）**：场景 camera 段 `ortho=true, ortho_size=13`；用 `camera_proj {ortho:false, size:12}` 切透视；按播放→停止。
7) **可复现验证**（P2 探针 §3 原文）
```
3.0 加载场景后: ortho=True  ortho_size=13.0  fov_deg=60.0
3.1 camera_proj 切透视后: result={'ortho': False, 'size': 12.0}  ortho=False  ortho_size=12.0
3.2 进入播放后: ortho=True  ortho_size=13.0  fov_deg=60.0
3.3 退出播放后: ortho=True  ortho_size=13.0  fov_deg=60.0
3.3 编辑态原值 = (False, 12.0, 60.0)
3.3 是否被播放改写 = True
```
   复跑：`cd Loom && python tests/_tmp/beta3_scan_04_probe2.py`
8) **影响与等级**：**P2**。2D 工作流"改投影→试播→再改"会静默吃掉刚设的投影；属本轮"播放强制相机"新语义的未闭合部分 → **[REGRESSION]**。

**修复方向**：把 `_play_edit_cam` 扩成"编辑态投影快照"（`_fov / ortho / ortho_size`，可选含 `_scene_cam`），退出播放时与轨道字段一并还原；或给 `_apply_camera` 增加"仅播放期生效"形参，把"写投影"与"写轨道字段"分离。
**必须保持的白盒契约**：① B5 播放期仍必须强制套用场景相机；② 播放态禁用相机键鼠（`editor.py:2343-2345`）不得回退；③ 旧场景无 `ortho` 键时按 False/12.0（957-958 已有 getattr 兼容）；④ 退出播放仍须整体还原场景（`apply_snapshot` / 光源 / 相机 / 物理桥 / GC）。
**波及调用方**：`toggle_play`（播放按钮、EAI `play` 命令、`_request_exit_play` 帧末退出）；`camera_proj` 返回值语义不变。

---

#### P-04-02 [REGRESSION][P2] 新命令 `camera_proj` 改的投影属性不进"场景已改动"判定 → 未保存退出无提示即丢失

1) **位置**：`agent_commands.py:1018-1030`（`cmd_camera_proj` 只写 `ed.ortho / ed.ortho_size`）、`editor.py:866-881`（`_scene_digest` 固定 `camera=None`）、`editor.py:991`（`_save_scene` 传 `self._camera_dict()`）、`sceneio.py:1049-1058`（保存时才 `setdefault` 补 ortho / ortho_size / fov）
2) **契约/预期**：B8 —— 投影模式**是会被保存的场景属性**（`sceneio.py:1049-1058` 显式写 `camera["ortho"]`），因此必须参与"是否有未保存改动"判定，否则"关闭时提示保存"对它失效。
3) **路径枚举**：`scene_is_dirty()` → `_scene_digest()` → `sceneio.scene_to_dict(self, camera=None)`；`scene_to_dict` 中 `if isinstance(camera, dict):` 才补投影字段（1050-1058）→ `camera=None` 时投影**完全不在摘要里**。对照：物体位置在 objects 段，会被判脏。
4) **实际行为**：`camera_proj` 之后 `scene_is_dirty()` 仍为 False。
5) **差异**：预期"改了可保存属性 → 判脏"，实际"改了但判不脏"。
6) **触发条件**：任何 `camera_proj {ortho|size}` 调用后未保存直接关窗/新建。
7) **可复现验证**（P4 探针原文）
```
初始 dirty = False
camera_proj -> {'ortho': True, 'size': 13.0}
改投影后 dirty = False
ortho= True ortho_size= 13.0
改物体位置后 dirty = True          <- 对照组：物体改动判脏
保存 camera 段 = {"target": [0, 0, 0], "distance": 10.0, "yaw": 0.0, "pitch": 0.0, "ortho": true, "ortho_size": 13.0, "fov": 44.97718691776962}
```
   复跑：`cd Loom && python tests/_tmp/beta3_scan_04_probe4.py`
8) **影响与等级**：**P2**（SEM-SILENT：可持久化却不可感知）。新命令本轮引入 → **[REGRESSION]**。

**修复方向**：让 `_scene_digest` 的 camera 段携带"仅投影字段"（或让 `scene_to_dict` 在 `camera=None` 时也带引擎侧投影字段），使投影参与脏判定；**不要**把轨道相机算进脏判定。
**必须保持的契约**：① 轨道相机（target / distance / yaw / pitch）仍不算场景改动（`editor.py:867-869` 注释 + 2026-08-13 用户实测 A01 结论）；② `_norm` 继续把 int/float 统一（否则渲染侧 `m.update` 会造成"没改也判脏"）；③ `sceneio` v7 保存格式不变。
**波及调用方**：`scene_is_dirty` / `mark_saved` / 关闭确认 / 新建场景提示 / 相关测试断言。

---

#### P-04-03 [P2] `cancel_batch` 不清重做栈 → 取消批次后陈旧 redo 仍可重放（叠加在未入栈的改动之上）

1) **位置**：`undo.py:1120-1128`（`cancel_batch`）、对照 `undo.py:1130-1136`（`_append` 会 `redo_stack.clear()`）
2) **契约/预期**：B2 + 撤销栈不变式 —— 任何**已发生**的编辑都应让重做栈失效（`undo.py:1139` push 的 docstring 写明"同时清空重做栈"；`_append` 是 push / push_no_do / end_batch 共用入口）。`cancel_batch` 明确声明"批内命令已执行过的 do() 不回滚"，即它**确实是已发生的编辑**。
3) **路径枚举**：批内 `push` → `cmd.do()`（真改场景）+ `_batch.append`（不入栈）→ `cancel_batch` 只置 `_batch=None`，**不碰 redo_stack**。对照：非批次 push 与成功的 end_batch 都经 `_append` → 清 redo。**只有 cancel 这一条路径漏了。**
4) **实际行为**：取消批次后 redo_stack 保留旧命令，`redo()` 照常执行。
5) **差异**：同一"发生编辑"语义在 cancel 路径上少了 redo 失效。
6) **触发条件**：用户先 Ctrl+Z 撤销某操作 → Agent 开批并改动 → 批被 cancel（主动 cancel 或下一次 begin 自动 cancel 悬挂批）→ 用户 Ctrl+Y。
7) **可复现验证**（P1 探针 1.1 原文）
```
1.1 step1 (undo A): models=[]  undo=0  redo=1
1.1 step2 (batch add B -> cancel): cancel_n=1  models=['B']  undo=0  redo=1     <- redo 没被清
1.1 step3 (redo after cancel): redo_label='add A'  models=['A', 'B']
1.2 普通 push 后 redo 应清 0: redo=0
```
   复跑：`cd Loom && python tests/_tmp/beta3_scan_04_probe.py`
8) **影响与等级**：**P2**。用户的"重做"把先前撤销的对象叠加到 Agent 新改动之上；仍可再撤销（`redo()` 会压回 undo 栈），故不升 P1。

**修复方向**：`cancel_batch` 丢弃批记录时同步清 redo_stack（与 `_append` 一致）；若产品上要"取消=什么都没发生"，则应整体回滚批内命令 —— 二者择一，不可混用。
**必须保持的契约**：① B2"cancel 不回滚已执行 do()"（`tests/test_undo_batch.py:152-161` 已把该语义写死为契约，改语义须同步改测试与文档）；② `limit` 与栈长语义不变。
**波及调用方**：`cmd_agent_batch_cancel` 的 `cancelled` 计数、`begin_batch` 的悬挂自动 cancel、GUI Ctrl+Y。
---

#### P-04-04 [P1] 批次进行中按 Ctrl+Z 会弹掉**批次之外**的命令，随后 `end_batch` 把它的 redo 记录抹掉 → 不可恢复

1) **位置**：`undo.py:1156-1162`（`undo()` 不查 `_batch`）、`undo.py:1106-1118`（`end_batch` → `_append` → `redo_stack.clear()`）、`undo.py:1138-1145`（批内命令不进 undo 栈）
2) **契约/预期**：撤销栈是**线性时间序**；一次 undo 应撤销"最近一次已记录的编辑"。批内命令虽未进 undo 栈，但**已经改了场景**，所以"最近一次编辑"就是批内最后一条，而不是批次之前那条。B2 的"一轮=一步"隐含：批未结束前，撤销不应跨过批。
3) **路径枚举**
   - 批未开始：`undo()` pop 最近记录 → 正常。
   - 批进行中且 undo_stack 非空：pop 的是**批之前**的命令（批内命令不在栈里）→ 该命令被 undo 并 append 到 redo_stack。
   - 紧接着 `end_batch` → `_append(batch)` → `redo_stack.clear()`：上一步保住的 redo 记录也被清掉。
   - 批进行中且 undo_stack 为空：`undo()` 直接返回 None → 用户 Ctrl+Z 静默无效（与 P-04-05 同源）。
4) **实际行为**：场景被回退了一条**更早**的操作，而批内改动仍在；随后 redo 记录消失。
5) **差异**：预期"撤销最近一次编辑"，实际"跨过批撤销了更早的编辑且不可重做"。
6) **触发条件**：Agent 批处理期间（120ms/条 → 85 个物体的批持续约 10 秒）用户按 Ctrl+Z。窗口真实且足够长。
7) **可复现验证**（P1 探针 1.3 原文）
```
1.3 step0 (A 在栈, B 在批): models=['A', 'B']  undo=1  batch=1
1.3 step1 (批中 undo 弹出的对象): popped_label='add A'  models=['B']  undo=0  redo=1
1.3 step2 (end_batch): batch_cmds=1  undo=1  redo=0  models=['B']
1.3 结论: A 已被回退但 redo 记录被 end_batch 清掉 -> A 无法再恢复
```
   复跑：`cd Loom && python tests/_tmp/beta3_scan_04_probe.py`
8) **影响与等级**：**P1**（静默、不可恢复的数据丢失）。修法只涉及 undo 层，风险低。

**修复方向**：`undo()/redo()` 入口检测 `batch_active`，二选一：① 拒绝并返回明确错误（"批次进行中不可撤销"），② 先把批内已执行命令就地视为隐式批次再整体 undo。无论选哪种，`end_batch` 清 redo 之前必须保证"跨批撤销"没有发生。
**必须保持的契约**：① B2 的"end_batch 不重复执行、空批不压栈"；② GUI Ctrl+Z 必须给出一致反馈而非静默无效；③ `tests/test_undo_batch.py` 现有 5 组断言继续绿。
**波及调用方**：GUI 撤销/重做入口、EAI `undo` / `redo` 命令、`editor.toggle_play` 里的 `undo.clear()`（清栈时批次状态一并复位，`undo.py:1186-1191`，本轮已做对）。

---

#### P-04-05 [P1] 悬挂批次（begin 后中断）会让**后续所有用户操作**都不进撤销栈，且下一次 begin 永久丢弃这些记录；无超时/看门狗

1) **位置**：`undo.py:1138-1145`（`push` 在批次中只 append）、`undo.py:1147-1154`（`push_no_do` 同）、`undo.py:1120-1128`（`cancel_batch` 丢弃）、`agent_commands.py:779-791`（只有"下一次 begin"才发现悬挂）
2) **契约/预期**：B2 只规定"未 end 又 begin → 自动 cancel 旧批"。但 `push` docstring 说"批内只收进批列表, 等 end_batch 合成一步" —— 其前置条件（有人会 end）在进程/客户端中断时不成立。用户的撤销能力不该依赖 Agent 是否记得 end。
3) **路径枚举**
   - 正常：`begin → push xN → end` → 栈里 1 条。
   - 中断：`begin` → 客户端死/超时/崩溃 → `_batch` 永久非 None。
     - 用户 GUI 编辑走 `push` → 进 `_batch`，undo_stack 不增长 → `can_undo` 可能为 False → Ctrl+Z 无效；
     - `push_no_do`（`ui_set` 路径）→ 同上；
     - 下一次 `agent_batch_begin` → `cancel_batch()` 丢弃 N 条 → 这些编辑**永久没有撤销记录**（场景仍是改后的）。
   - 唯一复位路径：`undo.clear()`（进播放 `editor.py:1804` / 换场景 `undo.py:1186-1191`）—— 它把整个历史清空。
4) **实际行为**：用户撤销栈静默失效 + 记录永久丢失。
5) **差异**：预期"Agent 中断不影响人的撤销权"，实际"人的撤销权被 Agent 的未闭合状态绑死"。
6) **触发条件**：MCP 客户端在 `agent_batch_begin` 之后崩溃/被 kill/会话关闭（无 `end`）。注意 `submit` 的 30s 超时只覆盖单条命令，**不覆盖"批次未 end"这种跨命令状态**。
7) **可复现验证**（P1 探针 1.4 原文）
```
1.4 批次悬挂时用户操作: models=['user1', 'user2']  undo=0  can_undo=False  batch=2
1.4 结论: can_undo=False -> 用户 Ctrl+Z 完全失效, 且这两条永远不会进撤销栈
1.4 新 begin 后: had_stale=True  undo=0  models=['user1', 'user2']
1.4 结论: 旧批被丢弃 -> user1/user2 的撤销记录永久丢失 (修改仍在场景里)
```
   复跑：`cd Loom && python tests/_tmp/beta3_scan_04_probe.py`
8) **影响与等级**：**P1**（用户可见功能失效 + 数据不可恢复）。这是"一轮=一批"设计在异常路径上的必然缺口（任务书点名要查的"半批次残留"）。

**修复方向**：给批次加"租约/超时"语义（批次空闲超过 N 秒自动 `end_batch`，把已收命令**合成一步**而不是丢弃），或在 `AgentService.stop()` / HTTP 客户端断开处兜底 end。核心：**悬挂批必须收敛为"可撤销的一步"，而不是"丢弃记录"**。
**必须保持的契约**：① B2 的"end_batch 不重复执行"；② `tests/test_undo_batch.py:164-177`（悬挂 begin 自动 cancel + `had_stale=True`）的既有断言 —— 若改成"自动 end"，必须同步改测试与 `docs/audit/_fix_ledger.md:247`；③ 批次不应跨越播放/换场景边界（`clear()` 已复位，别破坏）。
**波及调用方**：`cmd_agent_batch_begin/end/cancel` 的返回字段；`_fix_ledger.md` 与 `fix_agent_visual_pacing_batch_focus.md` §4 的契约描述需要同步。

---

#### P-04-06 [REGRESSION][P2] `BatchCommand.undo` 无逐条容错 + `UndoManager.undo` 先 pop 后 append → 单条失败 = 半批次回退 + 整批记录丢失

1) **位置**：`undo.py:1072-1074`（`for c in reversed(self.cmds): c.undo()` 无 try）、`undo.py:1156-1162`（pop 之后才 `redo_stack.append`）
2) **契约/预期**：`BatchCommand` docstring（`undo.py:1058-1062`）声明"把批内多条命令合成'一步'撤销" —— "一步"意味着要么整批回退、要么整批保持，不允许"回退一半且记录也没了"。
3) **路径枚举**
   - 全部 undo 成功 → 整批回退 → 进 redo 栈。
   - 第 k 条 undo 抛异常 → 前 k-1 条（逆序）已回退、第 k 条之后未处理；异常冒泡到 `UndoManager.undo` 的 `cmd.undo()` 行 → `redo_stack.append` **不执行** → 批次既不在 undo 栈（已 pop）也不在 redo 栈。
   - 对照：单条命令时代同样会丢记录（`undo.py:1159-1161` 是旧结构），但**新代码把"一次失败"变成"最多 N 次失败机会"，且后果是部分回退的场景**。
4) **实际行为**：场景处于"批内前几条已回退、后几条未回退"的中间态，且**整批不可重做**。
5) **差异**：预期"一步"原子，实际"部分 + 丢记录"。
6) **触发条件**：批内任一命令的 `undo()` 抛异常（例：`DeleteObjectCommand.undo` 的 `_build_gpu` 失败、`UIStateCommand` 目标元素已被移出树、`AddObjectCommand.undo` 内 `remove_model` 异常）。批越大命中概率越高。
7) **可复现验证**（P3 探针 §6 原文，用严格遵循 `Command` 契约的探针命令）
```
6.0 批次压栈: cmds=3  undo_depth=1
6.1 undo 抛异常: RuntimeError('undo boom 2')
6.1 部分回退后: log=['do1', 'do2', 'do3', 'undo3', 'undo2']  undo_depth=0  redo_depth=0
6.1 结论: 逆序只走到第 3 条就中断; 批次已出栈且未进 redo 栈 -> 1/2 两条的修改永久留在场景里
6.2 单条命令 undo 抛异常: log=['dosolo', 'undosolo']  undo_depth=0  redo_depth=0
```
   复跑：`cd Loom && python tests/_tmp/beta3_scan_04_probe3.py`
8) **影响与等级**：**P2**（失败路径的数据不一致；正常路径不受影响）。新增类 `BatchCommand` 引入 → **[REGRESSION]**（放大既有结构缺陷，且"一步"承诺不成立）。

**修复方向**：`BatchCommand.undo/do` 内逐条 try 并收集失败项；`UndoManager.undo/redo` 用 try/finally 保证 cmd 一定被迁到另一侧栈，并把失败信息回传给调用方（不要静默吞）。
**必须保持的契约**：① 单条命令的正常 undo/redo 与栈长语义不变（`tests/test_undo_batch.py:126-131`）；② 不改变 `Command.do/undo` 接口（所有既有子类）；③ 异常必须可见（SEM-SILENT 是本次审计反复命中的缺陷类型）。
**波及调用方**：所有 `UndoManager.push/undo/redo` 调用点（GUI Ctrl+Z、EAI `undo/redo`、`editor.commit_model`）。
---

#### P-04-07 [P1] Q5=A 未闭合：`set_lod {bias}` 在 `commit_model` 之外直写 → 无撤销记录；且对非 sphere 返回 error 时改动**已生效**

1) **位置**：`agent_commands.py:1463-1499`，关键 `1471-1472`（`r.lod_bias = max(0.1, as_float(...))` 在 `ed.commit_model` 之前且之外）、`1498`（返回 error 的分支在改动之后）
2) **契约/预期**：B3 —— 人类 2026-11-07 裁决 Q5=A："快照纳入……LOD……；补成对测试"。本轮 `undo.py:88-96` 已把 `lod_levels / lod_screen_levels / lod_bias` 加进 `snapshot()`，`Loom/tests/test_undo_full_coverage.py:60-84` 已补成对测试 —— **但该测试直接构造 `StateCommand`，不经过 EAI 命令层**，所以它证明"快照能存"，不证明"命令会存"。
3) **路径枚举**（该函数只有 4 个出口）
   - `set_lod {bias}` → 1471-1472 直写（**无 undo**）→ 若 `prim == 'sphere'` 继续 1483-1497（`_on` 走 commit，但 commit 的 before 已包含改后的 bias → bias 永远不在任何 before 快照里）→ 返回。
   - `set_lod {bias}` 打在非 sphere 上 → 1481-1482 / 1498：**在 1471-1472 已经改了 bias 之后**返回 `{'error': '仅 sphere 基元支持自动 LOD'}`。
   - `set_lod {on:false}` → 1473-1479 走 `commit_model`（只覆盖 `lod_levels / lod_screen_levels`），bias 若在同一次调用里给出，仍在 commit 之外。
   - `set_lod {screen}` 且 sphere → 1490-1497 走 `commit_model`（bias 同上）。
4) **实际行为**：`lod_bias` 改了但没有撤销记录；对 cube 报错时状态也已改。
5) **差异**：Q5=A 要求 LOD 可撤销（含 bias），实际只有 `screen` / `on` 两条子路径可撤销；同时"报错=未生效"的常规约定被破坏（IFACE-PARTIAL）。
6) **触发条件**：`set_lod {bias: 2.5}`（任意物体）；或 `set_lod {bias: 2.5}` 打在 cube 上。
7) **可复现验证**（P3 探针 §4 原文）
```
4.0 选中后的初始值: lod_bias=1.0  undo_depth=0
4.1 set_lod bias=2.5: result={'name': '立方体', 'error': '仅 sphere 基元支持自动 LOD (其它网格无细分可降)', 'primitive': 'cube'}  lod_bias=2.5  undo_depth=0
4.2 set_lod screen=0.3 ...: undo_depth=0  lod_screen=False  lod_bias=2.5
4.3 结论: bias=2.5 不在任何快照的可逆范围内 (撤销后仍是 2.5)
```
   复跑：`cd Loom && python tests/_tmp/beta3_scan_04_probe3.py`
8) **影响与等级**：**P1**（人类裁决的契约未闭合 + 错误语义破坏）。注意：**该函数本轮未被修改**（`git show f53a82a:Loom/agent_commands.py` 中逐字节相同），故不标 [REGRESSION]；但 Q5=A 是本轮定稿的裁决内容，"落地 Q5"的交付不完整（DESIGN-DRIFT）。

**修复方向**：把 `r.lod_bias` 的写入挪进 `commit_model` 的 apply 闭包（或为"只改 bias"单开一次 commit）；并把"是否支持 LOD"的参数校验前移到任何写操作之前（先校验后改）。
**必须保持的契约**：① Q5=A 的"LOD 可撤销"（`test_undo_full_coverage.py` 的 6 条 LOD 断言继续绿）；② bias 下限 0.1（1472）与 `_lod_cur` 失效逻辑（1477）不变；③ 仍要区分"仅 sphere 支持自动 LOD"这一产品语义（不要让错误变成静默成功）。
**波及调用方**：MCP 工具 `unity_lod_set`（`loom_mcp.py` 转发）；GUI 检查器**没有** LOD bias 控件（`grep -n lod_bias Loom/ui/loom_gui.py` 0 命中），所以本缺口只在 Agent / EAI 路径暴露 —— 恰好落在"一轮 AI 操作=一批"的撤销范围内。

---

#### P-04-08 [P2] `key_binding` 无动作名白名单：拼错动作名会静默创建"幽灵动作"并落盘；`saved` 恒为 True

1) **位置**：`agent_commands.py:991-1005`（`cmd_key_binding`）、`engine.py:919-932`（`set_action_binding` 恒 `saved: True`）、`loom_input.py:272-300`（`rebind_action` 直接 `self.actions[name] = keys`；写盘异常被 print 吞）
2) **契约/预期**：命令自述"键位: 查询 / 改键 (写入游戏配置, 立即生效)"；动作名来自 `DEFAULT_ACTIONS`（8 个，`loom_input.py:101-112`）与 `key_bindings` 覆盖（handoff §3.4）。改一个**不存在**的动作，正确语义是拒绝（与项目其它命令的 `_no_target` / `{'error': ...}` 风格一致）。
3) **路径枚举**
   - 合法动作 → `actions[name] = keys` → `game_settings.write_key_binding` → `save_action_bindings`（写 `输入配置.json`）→ 返回 `saved: True`。
   - 非法动作 → **完全相同的路径**（`loom_input.py:284` 无存在性检查）→ 幽灵动作进入 `self.actions` 并**被持久化**到两份配置。
   - 写盘失败 → `except Exception as e: print(...)` → 仍 `saved: True`（`engine.py:930`）。
4) **实际行为**：错误动作名被接受并落盘；写盘失败也报成功。
5) **差异**：预期"非法动作名 → error；未写成功 → saved False"，实际都是"OK"。
6) **触发条件**：`key_binding {action: "解锁鼠标 ", keys: "F10"}`（尾随空格）或 `{action: "任意", keys: "x"}`。
7) **可复现验证**：静态路径可审计（`loom_input.py:284` 无校验；`engine.py:926-931` 无条件 `saved: True`）。落盘目标见 C-25：`_ACTION_FILE = "输入配置.json"`，且 `git ls-files` 显示 `Loom/输入配置.json` **受跟踪**。为避免改动受跟踪文件，本轮**未**在真编辑器执行 `key_binding` 的动态验证（见 §4.1-X2，属需要人类拍板的写盘边界）。
8) **影响与等级**：**P2**（配置数据污染 + 返回语义撒谎；无崩溃）。新命令本轮引入 → 语义缺口属新代码。

**修复方向**：`cmd_key_binding` 写入前对 `action` 做白名单校验（`ed.actions` 的 key 集合），未命中返回 `{'error': ..., 'available': [...]}`；`set_action_binding` 的 `saved` 回填真实写盘结果（失败时附 `warn`）。
**必须保持的契约**：① 键位优先级（游戏设置 > 引擎 输入配置 > DEFAULT_ACTIONS，handoff §3.4）不变；② `解锁鼠标` 是引擎保留动作，任何改键实现都不能把它删掉（`game_settings.py:72`）；③ `游戏设置.json` 的 `{action: [keys]}` 格式不变。
**波及调用方**：MCP 侧改键调用方；GUI 改键 UI（若有）；`loom_input.load_action_bindings` 的"补新动作"逻辑（`loom_input.py:250-256`）。

---

#### P-04-09 [P3] `agent_batch_begin` 返回键 `cancelled_stale` 与契约文档 `had_stale` 不一致；`begin_batch()` 自己的返回值被丢弃

1) **位置**：`agent_commands.py:779-791`（自己 `stale = bool(getattr(um, 'batch_active', False))` + 自己 cancel + 返回 `cancelled_stale`）；`undo.py:1097-1104`（`begin_batch` 返回 `had_stale`）
2) **契约/预期**：`docs/audit/fix_agent_visual_pacing_batch_focus.md:49`："悬挂保护: 未 end 又 `begin_batch` -> 自动 cancel 旧批并返回 `had_stale=True`"
3) **路径枚举**：无悬挂 → `cancelled_stale: False`；有悬挂 → `True`。两条路径都不产出 `had_stale` 键。
4) **实际行为**：键名不同；`um.begin_batch()` 的返回值被忽略，命令层另算了一次（当前实现下等价，但留下两份真值来源）。
5) **差异**：文档键名 ≠ 实现键名。
6) **触发条件**：读取该响应字段的调用方（MCP `loom_eai_call` 客户端 / 自动化脚本）。
7) **可复现验证**（P2 探针 5.1 / 5.2 原文）
```
5.1 agent_batch_begin 首次: keys=['batch', 'cancelled_stale', 'label']  result={'batch': True, 'label': 'L1', 'cancelled_stale': False}
5.2 悬挂 begin 第二次: keys=['batch', 'cancelled_stale', 'label']  result={'batch': True, 'label': 'L2', 'cancelled_stale': True}
```
   复跑：`cd Loom && python tests/_tmp/beta3_scan_04_probe2.py`
8) **影响与等级**：**P3**（契约漂移，无功能影响；`tests/test_undo_batch.py:228-229` 已按实现断言，测试不会暴露）。

**修复方向**：文档与实现二选一对齐（建议以文档为准并保留旧键做别名，避免破坏已按 `cancelled_stale` 写的调用方）；把 `begin_batch` 的返回值作为唯一真值来源。
**必须保持的契约**：B2"未 end 又 begin 自动 cancel 并告警"的行为不变。

---

#### P-04-10 [P3] `view_focus` 把"播放态"与"AABB 取不到"两种 False 压成同一句错误

1) **位置**：`editor.py:2248-2296`（`focus_on_object` 在播放态返回 False（2250-2253），`_focus_aabb` 失败返回 False（2266-2267））、`agent_commands.py:818-855`（`if not fn(...): return {'error': '聚焦失败 (播放态不能移动编辑器相机)'}`）
2) **契约/预期**：B1 §5 要求"越界/找不到/播放态 -> 明确 error"；错误文案应可指导下一步。
3) **路径枚举**：`is_playing` → False；`index` 非 int → False；越界 → False；`_focus_aabb` 两次异常 → None → False；`mn/mx is None` → False。`view_focus` 对这 5 种 False 全部回同一句"播放态不能移动编辑器相机"。
4) **实际行为**：编辑态下 AABB 取不到时，用户/Agent 被误导为"正在播放"。
5) **差异**：错误文案与实际原因不符（AUDIT-DOCIMPL）。
6) **触发条件**：`view_focus` 打在一个 `get_bounding_box` 抛异常或返回空的物体上。
7) **可复现验证**：源码路径枚举（`editor.py:2250-2268` 与 `agent_commands.py:848-849`）。本轮未构造出"AABB 失败"的真实网格（罕见路径），故只登记为 P3 文档-实现不一致。
8) **影响与等级**：**P3**。

**修复方向**：`focus_on_object` 返回三态（成功 / 播放态 / 无包围盒）或抛具名异常；命令层据此给不同 error。
**必须保持的契约**：B5"播放态不动播放相机"（`editor.py:2250-2253` 的拒绝语义不能变）。

---

#### P-04-11 [P3] 步进模式 E 移除后的残留（探针里的死环境变量 + 编辑器内的死标志）

1) **位置**：`tests/_tmp/probe_agent_e2e_real.py:12`（`env['LOOM_AGENT_STEP'] = '0'`）；`editor.py:1849-1850`（`_dev_cam_active / _dev_cam_moved` 在 editor.py 内只写不读）
2) **契约/预期**：B6 —— E 已**完整移除**（"`LOOM_AGENT_STEP` / `LOOM_AGENT_STEP_TIMEOUT` 环境变量……已删除"）。
3) **路径枚举**：`grep -rn "step_mode|resume_step|LOOM_AGENT_STEP|_agent_step" Loom --include=*.py` → 源码 0 命中，仅 `tests/_tmp/probe_agent_e2e_real.py:12` 命中；`_dev_cam_active` 在 `Loom/editor.py` 只有 1849 的写、读点 0（`grep -n _dev_cam Loom/editor.py` 只有 1849/1850 与注释 2070）。
4) **实际行为**：残留一个无效环境变量设置（探针）与两个死标志（编辑器）。
5) **差异**：与"完整移除"的表述略有出入，但**不影响任何行为**。
6) **触发条件**：无（纯静态）。
7) **可复现验证**：上面的 grep 输出；探针不在产品路径。
8) **影响与等级**：**P3**（AUDIT-DEADCODE，可维护性）。**未发现**任务书要求排查的"定时器 / 超时逻辑 / 配置项"残留（`_draining` / `_idle_release_s` 都在用，无 step 相关定时器）。

**修复方向**：删掉探针里的 `LOOM_AGENT_STEP` 设置；`_dev_cam_*` 两行连同注释一起清理（或恢复其读取点，若仍是功能）。
**必须保持的契约**：B1 的 120ms 节奏与忙态语义。
### 2.2 P-DISPROVED（12 条）

> 每条给出路径枚举与"为什么所有出口都不成立"；因结论是"无缺陷"，正手链不适用（方法论 §5.4：证伪成功 + 证真失败 → DISPROVED）。

**D-01（对应 C-14）120ms 节奏阻塞 UI 线程 → DISPROVED**
- 路径枚举：`drain()`（`agent_commands.py:3322-3357`）只有三种出口 —— 队列空 `return 0`；`pace_ms` 未到 `break`；执行 1 条后 `break`。**没有 `time.sleep`**（`grep -n "sleep" Loom/agent_commands.py` 0 命中），因此它每 4ms 被 QTimer 唤醒、立即把控制权交回 Qt 事件循环。
- 结论：节奏是"时间戳门控 + 早退"，不是"阻塞等待"。`_agent_after_command` 的 `repaint()`（`loom_gui.py:1843-1851`）确实在主线程同步重绘，但那是"每条命令一次出图"的设计（B1），不是节奏实现引入的阻塞源。

**D-02（C-15）`_scene_cam = dict(cam)` 浅拷贝导致后续污染 → DISPROVED**
- 路径枚举：`_scene_cam` 只有两处被读（`editor.py:976` 写、`editor.py:1819` 读）；`_apply_camera` 内部对 target 走 `tuple(...)`、对 ortho/ortho_size/fov 走 bool/float 复制；**没有任何路径原地修改 `_scene_cam['target']` 这个 list**。
- 结论：浅拷贝在此不可观测（唯一可变成员无人原地改）。

**D-03（C-16）正交矩阵参数顺序 / 坐标系不匹配 → DISPROVED**
- 路径枚举：`matlib.mat4_ortho(xp, left, right, bottom, top, near, far)`；调用点 `editor.py:2083-2084` 逐槽对上 `(left=-h*asp/2, right=+h*asp/2, bottom=-h/2, top=+h/2, near, far)`。坐标系：`loom_camera.apply_orbit_camera:54-65` 明确 `ez` 为**相机 +z 前向**，故可见点 `z_view` 为正、`clip.z = z/(far-near) - near/(far-near)` 落在 [0,1]，与 `w=1` 及 `mat4_perspective` 的深度约定自洽（`mat4_ortho` docstring 亦明示"配合引擎深度测试约定"）。
- 结论：参数顺序、符号与深度域均正确。

**D-04（C-17）`view.viewport.setFocus()` 是死代码 → DISPROVED**
- 证据：`LoomGUI.__init__` 无条件设 `self.viewport = RemoteViewport(...)` 或 `GLViewport(...)`（`loom_gui.py:922/924`）；`EditorApp.view` 就是该 LoomGUI（`editor.py` 用 `self.view.reset_interaction / input_state / draw`，实现于 `loom_gui.py:1024-1041`）；`GLViewport` 是 `QOpenGLWidget`（`loom_gui.py:144`），具备 `setFocus`。
- 结论：属性存在；三连 getattr 只是防御（`MinimalEditorView` 无 viewport 时安全跳过）。

**D-05（C-18）`render_api` 写入非法后端 → DISPROVED**
- 证据：`engine.set_render_api`（`engine.py:861-884`）→ `game_settings.write_render_api` → `normalize()` 不在 `("vulkan","opengl","auto")` 就返回 `(False, None, 错误串)`，不落盘。
- 实测（P2 探针 5.3）：`{'ok': False, 'saved': None, 'current': 'opengl', 'restart_required': True, 'path': None, 'error': 'render_api 必须是 vulkan / opengl / auto'}`。

**D-06（C-19）自动聚焦每命令读设置文件的开销 → DISPROVED**
- 实测（P2 探针 5.7）：`_auto_focus_enabled 单次耗时 0.074 ms`（200 次平均）。
- 结论：不构成性能问题（对照：聚焦本身一次 `compute_world_matrices` 是 0.1ms 量级，`fix_agent_visual_pacing_batch_focus.md` §7-2 已记录）。

**D-07（C-11 的一半）步进模式 E 的配置项 / 定时器 / 超时逻辑残留 → DISPROVED**
- 证据：`grep -rn "step_mode|resume_step|LOOM_AGENT_STEP|LOOM_AGENT_STEP_TIMEOUT" Loom --include=*.py` 源码 0 命中；`submit` 已恢复 30s（`ev.wait(30.0)`）。
- 说明：唯一残留在 `tests/_tmp` 探针里（已登记为 P-04-11）。

**D-08（C-20）`_material_state` 漏材质字段 → DISPROVED（除 name 外）**
- 路径枚举：`Material` 可写字段 = color / saturation / name / albedo / normal_map / env_map / metallic / roughness / pbr / guid；`_material_state` 覆盖 8 个（`undo.py:35-44`）。`name` 无任何改值入口（`grep -n "mat.name|material.name ="` 只有创建与序列化），`guid` 是身份不可变。
- 实测：P1 探针 2.0-2.2 全字段往返一致（`apply_snapshot(snap0)` → metallic=0.0/pbr=False/albedo=None/env_map=None；`apply_snapshot(snap1)` → metallic/pbr/albedo/env_map 全回来）。

**D-09（C-21）`push_no_do` 在批次中不成对（redo 重复执行）→ DISPROVED**
- 路径枚举：批内 `push_no_do` 只 append（不 do）；`end_batch` 不调 do；`redo` → `BatchCommand.do()` → 每条 `c.do()`（对 `UIStateCommand` 即应用 after 快照，恰好一次）。批外 `push_no_do` 行为未变（`undo.py:1147-1154`）。
- 佐证：`tests/test_undo_batch.py` 的 ⑤ 组"end 不重复执行"（E1 ALL PASS）。

**D-10（C-23）300ms 状态栏轮询覆盖 Agent 进度 / 掩盖物理告警 → DISPROVED**
- 路径枚举：`_refresh_status`（`loom_gui.py:3433-3477`）中物理线程告警分支在**前**（命中即 return）；`_agent_status_active` 保护在**后** → 告警优先级仍最高；`_agent_idle` 到期主动回调 `_refresh_status` 恢复默认文本（`loom_gui.py:1797-1812`）。

**D-11（C-22）批次状态跨场景 / 播放边界悬挂 → DISPROVED**
- 证据：`undo.clear()`（`undo.py:1186-1191`）复位 `_batch / _batch_label`；`editor.toggle_play` 进入分支第一件事就是 `self.undo.clear()`（`editor.py:1804`）。
- 残留语义：换场景后 Agent 再 `agent_batch_end` 会得到"没有进行中的批次"（`agent_commands.py:799`），属已文档化的拒绝语义（`tests/test_undo_batch.py:216-218`）。

**D-12（C-24）播放态 `_update_camera` 早退切掉了必需步骤 → DISPROVED**
- 路径枚举：早退点（`editor.py:2343-2345`）在 `_advance_focus_anim`（2334-2336）与 `_dispatch_ui_mouse()`（2339）之后 → UI 事件 / HUD 按钮 / 聚焦门控都保留；gizmo 由 `render` 的 `if not self.is_playing: self._update_gizmo()`（2116-2117）单独门控；`self._cam_prev_mouse = self.mouse_pos` 保持鼠标增量基准，避免退出播放首帧跳变。

**另两条"按人类裁决豁免"的登记（不是 UNKNOWN，而是有明确判据的豁免）**
- `_apply_camera` 的 `try/except: pass` 包住 fov 写入（`editor.py:960-965`）与 `ortho_size` 无钳制：按 **B4（Q4=B 场景不是不可信输入）** 判为不构成缺陷 —— `ortho_size` 的生产写入方只有 `camera_proj`（已 `max(1.0, ...)` 钳制，`agent_commands.py:1027`）与 `sceneio._f1`（归一化）；手改 JSON 造出 `ortho_size=0` 属 Q4 明确豁免的范畴。仅建议补对称钳制（§4 第 14 行，低优先）。
- `key_binding` 写 `Loom/输入配置.json`（受跟踪）：`loom_input.py:263-270` 的 docstring 明说"开发环境另存一份到引擎配置便于复用"，属**设计意图**（handoff §2.6），不判缺陷；只作为版本控制卫生问题登记（§4 第 15 行）。

### 2.3 P-UNKNOWN（2 条）

**U-01（C-12）`_request_exit_play` 帧末退出被裸 `except Exception: pass` 包住 → 可能"半还原场景 + 无提示"**
- 位置：`editor.py:2126-2133`
- 已有证据：退出播放是复合还原（移除播放期新物体 → `apply_snapshot` → 父链 → 光源 → 相机 → 物理桥销毁 → GC 解冻，`editor.py:1868-1973`），任一步抛异常都会留下半还原场景；异常被 `pass` 吞掉，且 `is_playing` 已置 False、`_play_*` 快照已被部分消费 → 下次进播放会以半还原场景为新基线。
- 为什么判 UNKNOWN：**未能构造真实可达的异常源**。已尝试：① 用 `tests/test_playmode_edges.py` 的无头 `toggle_play` 桩走完整进出（正常场景不抛）；② 逐条检查 `apply_snapshot` 可能抛的分支（`add_script` 未知 script_id、`rigidbody` 槽位不符）—— 均需注入才会触发，属"探针改目标"（方法论 §6.2 判为不合格探针）。
- 还缺什么信息：一个**真实场景/素材**（或一段真实 MCP 会话）使 `toggle_play` 退出路径抛异常；或由人类裁定"退出播放是否必须原子"（若必须，则无需可达性证明，直接要求加错误上报）。
- 建议下一步探针：在修复轮把退出分支包"失败即回滚到播放态 + 可见报错"，用注入式异常验证告警可见性。

**U-02（C-13）`loom_gui._agent_idle` 的 `_refresh_status()` 不在 try 内，窗口销毁后 1.5s 定时器触发可能抛 RuntimeError**
- 位置：`loom_gui.py:1797-1812`（第三个调用 `self._refresh_status()` 未包 try，前两个 `statusBar().*` 都在 try 内）；注册点 `loom_gui.py:1791`（`QTimer.singleShot(1500, lambda: self._agent_idle(tok))` 的闭包持有 self）
- 已有证据：静态不对称明确；PySide6 在 C++ 对象销毁后调用其方法会抛 `RuntimeError: Internal C++ object already deleted`。
- 为什么判 UNKNOWN：未实跑"构造 LoomGUI → close → 等 1.5s"的时序；`tests/test_agent_ui_indicator.py` 虽用 Qt offscreen 构造 LoomGUI，但未覆盖"窗口销毁后定时器仍在"的路径。
- 还缺什么信息：一次 Qt offscreen 探针（构造 → `_agent_progress(...)` → `win.close()/deleteLater()` → 等 1.6s → 捕获 stderr 的 unraisable）。初判影响 **P3**（最坏是关窗后 stderr 多一条 traceback，不改行为）。

### 2.4 P-CONTRADICTION = 0 的说明

- 每条 PROVED 都是先写"全部出口枚举 + 每个出口为何不成立"，再写正手复现；**没有出现"反手成功且正手也成功"的项**。
- 两处最可能矛盾的项被逐行否证后才进正手：P-04-01 的反手尝试"退出播放其实还原投影"（若 `_play_edit_cam` 含 `_fov/ortho`）—— 被 `editor.py:1813-1815` / `1906-1907` 只列 6 字段否证；P-04-07 的反手尝试"`commit_model` 的 before 快照能覆盖 bias"（若 commit 发生在 bias 写入之前）—— 被 `agent_commands.py:1471-1472` 在 1478/1494 之前否证。
- 因此本轮矛盾链为 0，**不是**"两边都成立选了一边"。
---

## 3. 统计

| 判定 | 数量 | 编号 |
|---|---|---|
| **P-PROVED** | **11** | P-04-01 … P-04-11 |
| **P-DISPROVED** | **12** | D-01 … D-12（另 2 条按人类裁决豁免已单独登记，见 §2.2 末） |
| **P-UNKNOWN** | **2** | U-01、U-02 |
| **P-CONTRADICTION** | **0** | 理由见 §2.4 |
| 疑似项总数 | **25** | C-01 … C-25 |
| 跳过项（登记留痕） | **5** | S-01 … S-05 |
| 其中 **[REGRESSION]（本轮引入）** | **4** | P-04-01、P-04-02、P-04-06，以及 P-04-05（本轮"一轮=一批"新机制在异常路径的缺口） |

**等级分布**：P0 = **0**；**P1 = 3**（P-04-04、P-04-05、P-04-07）；**P2 = 5**（P-04-01、P-04-02、P-04-03、P-04-06、P-04-08）；**P3 = 3**（P-04-09、P-04-10、P-04-11）+ 待定 P3 两条（U-01、U-02）。

**P-UNKNOWN 为何不为 0**：两条都卡在"缺少可达路径/时序证据"（U-01 缺真实异常源，U-02 缺窗口销毁后的定时器实测）；我没有把它们悄悄改判为 DISPROVED —— 它们的静态不对称是确定的，只是"是否真抛/是否真半还原"未实测。

**回归测试结果（E1-E5 实跑全绿）说明什么**：现有测试覆盖的是**正常路径** ——
- 批次测试只覆盖 begin→push→end→undo/redo 与 `cancel` 的"不回滚"语义；**未**覆盖"批中 undo / 悬挂期间用户 push / 批内单条 undo 失败 / cancel 后 redo"；
- Q5 成对测试直接构造 `StateCommand`，不经过 EAI 命令层 → `set_lod {bias}` 缺口不可见；
- 聚焦/节奏测试用桩 `win/ed`，不覆盖真实 `toggle_play` 的投影还原与 `camera_proj` 的脏判定。

---

## 4. 修复建议排序（只给方向，不含可直接替换的实现）

> 状态列 = 2026-11-08 第 4 批（D10=A+B）落地情况；P-04-01/02 已由第 2 批（D7=A）关闭并独立复核。

| 序 | 编号 | 优先级 | 建议方向（改哪个函数 / 哪条分支） | 状态 |
|---|---|---|---|---|
| 1 | P-04-05 | P1 | 批次租约收敛：悬挂批自动 `end_batch`（合成一步）而非 cancel | **已修**（`UndoManager.BATCH_LEASE_S=30` + `tick_batch` + `AgentService._tick_batch`） |
| 2 | P-04-04 | P1 | `undo/redo` 入口按 `batch_active` 拒绝并出声，任何情况下不丢批外历史 | **已修**（`undo_block_reason` → GUI/EAI 双路提示） |
| 3 | P-04-07 | P1 | `cmd_set_lod`：bias 进 `commit_model`；参数校验前移 | **已修** |
| 4 | P-04-01 | P2 | 播放前快照/退出还原投影三件套 | **已由第 2 批关闭** |
| 5 | P-04-02 | P2 | `_scene_digest` 纳入投影字段 | **已由第 2 批关闭** |
| 6 | P-04-06 | P2 | `BatchCommand` 逐条容错 + `undo/redo` 保证记录迁移并出声 | **已修**（`BatchCommandError` + peek-then-pop） |
| 7 | P-04-03 | P2 | `cancel_batch` 与 `_append` 口径统一（清 redo） | **已修** |
| 8 | P-04-08 | P2 | `cmd_key_binding` 动作白名单 + 透传真实 `saved` | **已修** |
| 9 | P-04-09 | P3 | `agent_batch_begin` 返回契约键 `had_stale`（+兼容别名） | **已修** |
| 10 | P-04-10 | P3 | `focus_on_object` 失败原因三态，`view_focus` 分开报错 | **已修** |
| 11 | P-04-11 | P3 | 清死环境变量 + 死标志 | **已修** |
| 12 | P-03-11 | P3 | `cmd_camera_proj` 改走 `set_camera_projection()` | **已修** |
| 13 | U-01 | P3（待裁决） | `render` 帧末退出加错误上报（不要裸 pass） | 未动 |
| 14 | U-02 | P3（待裁决） | `_agent_idle` 的 `_refresh_status()` 并入 try | 未动 |
| 15 | 观察 | P3 | 落盘类命令（`key_binding` / `render_api`）在源码工作区的写入边界 | 未动（见 §4.1-X2） |

### 4.1 动手前需确认的点（需人类拍板的路线分叉；其余按上表推荐默认执行）

- **X-1（已裁决 D10=A+B，留档）**：批次与人的撤销权冲突 → 采用"租约 30s 自动收口 + 租约内拒绝并提示"。剩余待定：**租约时长是否 30s 合适**（`begin_batch(lease_s=...)` 已可配，`agent_batch_begin` 支持 `lease_s` 参数）。
- **X-2（仍需裁决）：Agent 命令的写盘权限边界** —— **A**「接受 Agent 命令改本地配置（验收用 `LOOM_GAME_DIR` / `LOOM_USER_ROOT` 隔离）」／**B**「源码工作区默认拒绝配置写入（需显式开关）」。本轮测试全部走 A 方案（临时目录），未写任何受跟踪配置。
- **X-3（已由第 2 批裁决 D7=A，留档）**：`camera_proj` = 场景相机属性（进脏判定 + 进撤销 + 播放前后恒等）。本轮已把 EAI 命令接到同一条路径（P-03-11）。

---

## 5. 需要人类裁决的封闭问题（1 条待定 + 2 条留档）

1. **（待定）Agent 命令的写盘权限边界**：选 **A**「接受 Agent 命令改本地配置（验收/CI 用 `LOOM_GAME_DIR` + `LOOM_USER_ROOT` 隔离）」还是 **B**「源码工作区默认拒绝配置写入（需显式开关）」？
   - A 代价：`git status` 可能出现配置改动（本轮已用临时目录规避）；B 代价：打包/游戏开发场景要多一步授权。
2. **（留档 D10）批次租约**：默认 30s、租约内 undo 拒绝并提示 —— 已落地；若需调整时长，改 `UndoManager.BATCH_LEASE_S` 或调用方传 `lease_s`。
3. **（留档 D7）`camera_proj` 归属**：已按 **A（场景相机属性）** 落地。

---

## 6. 修复轮记录（2026-11-08 第 4 批：撤销/批次状态机 D10=A+B + agent_commands 收尾）

人类裁决 **D10 = A+B**：批次租约 30s 自动收口（`end_batch`，历史保留）；租约内 undo/redo 拒绝并提示"Agent 批次进行中（剩余 Xs），暂不可撤销"；状态栏可视化"Agent 批次进行中（剩余 Xs）"。

| 原编号 | 状态 | 落地位置（改哪个函数/分支） |
|---|---|---|
| **P-04-01** | **已由第 2 批关闭（独立复核通过）** | `editor.py` 播放前快照 `_play_edit_proj`、退出还原（复核探针：进/出播放投影恒等 = True） |
| **P-04-02** | **已由第 2 批关闭（独立复核通过）** | `_scene_digest` 纳入 `_camera_proj`（复核探针：改投影后 dirty=True，撤销可回原值） |
| P-04-03 | 已修 | `UndoManager.cancel_batch`：丢弃批记录时清 `redo_stack`（与 `_append` 口径统一） |
| P-04-04 | 已修 | `UndoManager.undo/redo` + `undo_block_reason()`：批次租约内拒绝并写 `last_refusal`；`editor._history_op` → `agent_commands.cmd_undo/redo` → GUI toast，任何情况下不弹批外历史 |
| P-04-05 | 已修 | `UndoManager.BATCH_LEASE_S=30` + `tick_batch()`（自动 `end_batch`）+ `AgentService._tick_batch()` 每拍维护；`agent_batch_begin` 先收口过期悬挂批 |
| P-04-06 | 已修 | `BatchCommand._run` 逐条容错 + `BatchCommandError`；`UndoManager.undo/redo` 改为"peek → 成功才弹栈"，失败写 `last_error`（记录保留可重试） |
| P-04-07 | 已修 | `cmd_set_lod`：校验先行（非 sphere 直接拒绝、零字段改动）+ `lod_bias` 与 levels 一起进 `commit_model` |
| P-04-08 | 已修 | `cmd_key_binding`：动作名白名单（未知动作拒绝并列出可用）+ 透传 `set_action_binding` 的真实 `ok/saved/error/path`（失败由 `dispatch` 变 `ok:False`） |
| P-04-09 | 已修 | `cmd_agent_batch_begin` 返回契约键 `had_stale`（保留 `cancelled_stale` 兼容别名，两者恒等）+ `lease_s` + `closed_stale` |
| P-04-10 | 已修 | `focus_on_object` 写 `_focus_fail`（playing/bad_index/no_aabb）；`cmd_view_focus` 按原因给不同 error |
| P-04-11 | 已修 | `editor.py` 删死标志 `_dev_cam_active/_dev_cam_moved`；`tests/_tmp/probe_agent_e2e_real.py` 删死环境变量 `LOOM_AGENT_STEP` |
| P-03-11 | 已修 | `cmd_camera_proj` 改调 `ed.set_camera_projection()`（sceneio 归一 + 进脏判定 + 进撤销），无该方法时保留旧直写兜底 |
| U-01 | 未动（仍 P3 待裁决） | `render` 帧末 `except: pass` 包住 `toggle_play` —— 需要人类裁定"退出播放是否必须原子" |
| U-02 | 未动（仍 P3 待裁决） | `_agent_idle` 的 `_refresh_status()` 未包 try —— 缺"窗口销毁后定时器触发"实测 |

**设计要点（新增契约，供后续维护）**
1. **"一条 EAI 命令 = 一个 Agent 命令单位"**：`agent_commands.dispatch()` 统一给 `UndoManager` 打 `agent_command_begin/end` 作用域。批次（`absorb=False`）只吸作用域内的写命令；检查器/gizmo/层级面板的编辑不走 `dispatch`，因此是"用户编辑"——不进批、不续租，且会先把已收到的批命令收口成一步再单独压栈（保时间顺序）。
2. **租约只由批内写命令续租**；`begin_batch(lease_s<=0)` = 不设租约（仅供测试/兼容）。
3. **拒绝语义**：`undo_block_reason()` 是唯一判定源，GUI（`_cmd_undo/_cmd_redo`、Ctrl+Z 键路径）与 EAI（`cmd_undo/cmd_redo`）都读它，避免"某条路径静默无效"。

**测试**
- 新增 `Loom/tests/test_beta3_batch4_undo_lease.py`（A-M 共 13 组，覆盖 D10=A/B、P-04-03/04/05/06/07/08/09/10、P-03-11、状态栏文案、AgentService 集成）。
- 加强 `Loom/tests/test_undo_batch.py`：⑤ 组按"EAI 命令 = Agent 命令单位"用 `_push_agent()` 模拟真实链路；新增"批外（用户）编辑不进批/单独成一步"与 `had_stale` 断言；`cancel` 断言按 P-04-03 口径更新（撤销栈不变 + 重做栈清空，附理由注释）。
- 验收全绿：`test_undo` / `test_undo_batch` / `test_undo_full_coverage` / `test_agent_pacing` / `test_editor_focus` / `test_eai_real`（98 条命令全覆盖）/ `test_beta3_batch2_camera_proj` / `test_beta3_batch4_undo_lease`；旁证 `test_editor_ui` / `test_assetbrowser` / `test_playmode_edges` / `test_camera_preview` / `test_unlock_key` / `test_render_api` / `test_agent_ui_indicator` 全绿。

**修前/修后对照（同一审计探针 `tests/_tmp/beta3_scan_04_probe{,3}.py`）**
```
probe1 1.1 step2: 修前 redo=1 (陈旧 redo 可重放)   ->  修后 redo=0
probe1 1.1 step3: 修前 models=['A','B']（旧对象被重放） -> 修后 redo_label=None models=['B']
probe1 1.3 step1: 修前 popped='add A'/models=['B']（跨批撤销） -> 修后 popped=None/models 不变/undo=1
probe1 1.3 step3: 修前 A 永久丢失 -> 修后 undo=2（批外与批各一步）、可逐步撤销
probe3 4.1:       修前 bias=2.5（报错仍改状态） -> 修后 bias=1.0（零改动）
probe3 6.1:       修前 undo3,undo2 中断且 undo_depth=0 -> 修后 undo3,undo2,undo1 全部回退、undo_depth=1（记录保留）
```
> 注：probe1 里那几行"结论: ..."是 2026-11-07 审计时写死在探针里的旁白文案，数字才是实测值；本轮未改探针叙事。

---

## 附：本报告的自审 checklist（方法论 §11.5）

- [x] 7 条可审计硬要求：基准唯一（§0.3 清单）/ 代码原样（行号 + 原文片段）/ 路径完备（每条 PROVED 都有出口枚举）/ 预期-实际可对照 / 命令可跑（探针给了复跑命令）/ 措辞可审计（无"我认为/看起来/应该是/经验上"）/ 跳过留痕（§1.2 五条 + 理由出处）
- [x] 每条证伪链给出路径枚举；每条证真链给出最小复现 + 实跑输出
- [x] P-UNKNOWN 不为 0，且写清"还缺什么信息"（U-01/U-02 至今仍待裁决）
- [x] 人类裁决项均为封闭问题（选 A / B）
- [x] 修复轮记录（§6）标明每条的原编号、落地位置与"修前/修后"实测对照

---

## 7. 收尾轮（U-01 / U-02，2026-11-08 人类裁决 A）

| 编号 | 裁决 | 落地 | 修前 → 修后（实测） |
|---|---|---|---|
| **U-01** | **A 原子化**：退出播放要么完整成功，要么回滚到播放态并明确告警 | `editor.py` 新增 `_exit_play_atomic()`：先快照播放记录（模型/光源/相机/三张快照表/编辑态相机与投影），失败时整体还原并把 `is_playing` 置回 True；render 帧末改为调它（删掉裸 `except: pass`）。告警：`_play_exit_warned` 只打一次（日志+traceback+`_notify` 红字），后续失败只累加 `_play_exit_fail_count`；成功退出后复位告警开关。不捕 `BaseException`（SystemExit/KeyboardInterrupt 上抛） | 修前：退出失败 = 半还原场景 + `is_playing=False` + 无人知情（无 `_exit_play_atomic`）；修后：`test_playmode_edges` A9 组 9 条全 PASS —— 失败回滚后 `is_playing=True`、快照仍在可重试、原因记入 `_play_exit_error`、toast 可见、二次失败计数=2 且不重复告警、故障消除后重试完整退出 |
| **U-02** | 包 `try` + 只告警一次 + **静默停表** | `ui/loom_gui.py`：新增 `_agent_gui_alive()`（`statusBar()` 抛 `RuntimeError` 即判"窗口已销毁"并置 `_agent_gui_dead`）与 `_agent_gui_warn_once()`（stderr 只打一次，含异常类型+原因）；`_agent_idle` 先判存活、`setStyleSheet/clearMessage/_refresh_status` 三段各自收窄到 `RuntimeError`（非 RuntimeError 的异常也带 `%r` 原因告警一次）；`_agent_progress` 在 `_agent_gui_dead` 时直接返回 —— 不再碰 QWidget、也不再排新的空闲定时器 | 修前：`_refresh_status()` 在 try 之外 → 销毁后定时器一触发就抛 `RuntimeError`（且每来一条命令再抛一次）；修后：`test_agent_ui_indicator` §5 共 5 条全 PASS —— 不抛、`_agent_gui_dead=True`、stderr 恰好一条含 `RuntimeError` 的告警、`_agent_progress` 不再碰 QWidget、token 不再增长 |

**边界确认**：本轮只改 `editor.py` / `ui/loom_gui.py` 与本批测试（`test_playmode_edges.py`、`test_agent_ui_indicator.py`）；未跑 `run_all.py`；未做任何 git 写操作。
**定向验收（实跑 exit=0）**：`test_editor_focus` / `test_playmode_edges` / `test_agent_ui_indicator` / `test_beta3_batch4_undo_lease`；旁证 `test_camera_preview` / `test_integration` / `test_eai_real`（98 命令）。
