# UI 事件派发与驱动层（loom_ui / scene_driver / sceneio / loom_render）扫描报告

> 扫描轮次：beta3 补丁轮（git 区间 `f53a82a..HEAD`，29 个提交）
> 子代理编号：beta3_scan_03　疑似项编号前缀：`P-03-NN`
> 本轮只扫不改：本报告不含任何可直接替换的实现代码，只给修复方向与必须保持的契约。

---

## 0. 范围与方法

### 0.1 文件清单（HEAD 实测行数）

| 文件 | 行数 | 本轮 diff 规模 |
|---|---|---|
| `Loom/loom_ui.py` | 1687 | +20 −? （两处：`_fire_binding` 目标解析、`draw_all(engine, script_host=None)`） |
| `Loom/scene_driver.py` | 1313 | +165（暂停/退出/键位/鼠标锁定/正交/fov/scripts 目录/解锁键/render_api） |
| `Loom/sceneio.py` | 1361 | +14（相机段 ortho/ortho_size/fov 读与写） |
| `Loom/loom_render.py` | 879 | +17（正交分支 + 退出释放鼠标捕获） |

```
git diff --stat f53a82a..HEAD -- Loom/loom_ui.py Loom/scene_driver.py Loom/sceneio.py Loom/loom_render.py
 Loom/loom_render.py  |  17 +++++-
 Loom/loom_ui.py      |  20 +++++--
 Loom/scene_driver.py | 165 ++++++++++++++++++++++++++++++++++++++++++++++++++-
 Loom/sceneio.py      |  14 +++++
 4 files changed, 207 insertions(+), 9 deletions(-)
```

### 0.2 判定基准清单（证真链只允许引用以下条目）

| 编号 | 基准原文 | 出处 |
|---|---|---|
| B1 | `Q7 多 Canvas 命中语义 = C「只吞空白」`：root 未命中子元素时必须继续下探低层，只有无人命中才由 root 消费 | 人类 2026-11-07 裁决，`docs/audit/_scan_summary.md §6`（本轮由主审转发）；代码实现 `loom_ui.py:421-457` |
| B2 | `Q4 场景是否不可信输入 = B「否」`：不做全量防御，但"会死循环/丢数据"的仍必须拒绝；报错即可，**不得引入死循环或静默错值** | 同上（主审转发） |
| B3 | 相机优先级声明：`场景 camera 段（target/distance/yaw/pitch/ortho/ortho_size/fov）——播放时强制套用` | `docs/handoff/接手总纲_20261107_引擎发布与游戏打包.md §3.4`（第 139 行） |
| B4 | `scene_driver.load_from_data` 的相机段契约："与 sceneio.scene_from_dict 的 camera_out 分支逐条对齐 …… 任一字段类型错/元素数不足 3 -> 回落默认, 不抛 (GL 同语义)" | 文件内白盒注释 `scene_driver.py:559-566` |
| B5 | `_end_frame_input` 契约："mouse_wheel 的唯一清零点 …… 无论 dev_mouse 开关都清零, 字段契约 (`:301) 恢复成立" | `scene_driver.py:721-730` |
| B6 | `consume_mouse_input` 契约："帧首结算鼠标增量 …… 解锁状态不覆盖 mouse_rel"（即 mouse_rel 表示"本帧"增量） | `scene_driver.py:1175-1182` |
| B7 | `_fire_binding` 契约："在 _ACTIVE_ENGINE 里找挂 sid 的脚本实例，调用 instance.method(*args)。返回 是否触发成功"；异常不向上抛但要打印 | `loom_ui.py:44-88` 文档串 + `loom_ui.py:127-131`（声明式绑定语义） |
| B8 | 申明引擎级强制解锁键的设计意图："现在: ① mouse_lock_allowed=False 的游戏永远不锁; ② 其余游戏始终可按 Tab 切换（Tab 是引擎保留键）" | `engine.py:882-888`、`scene_driver.py:907-916` |
| B9 | 内置脚本既有语义："Tab 的切换由 first_person/third_person 脚本走 driver.toggle_mouse_locked" | `vk_player.py:355-356` 注释 + `scripts.py:641-645, 700-704` |
| B10 | 双后端一致性：同一场景同一相机，GL/VK 应"看同一台相机" | `scene_driver.py:596-597, 833-835`；`runtime.py:59-67` |

### 0.3 跑过的命令（全部实测，可外部复跑）

```
cd "D:\my-project - 副本\Loom(py源代码-工作区)"
git log --oneline f53a82a..HEAD            # 29 个提交
git diff f53a82a..HEAD -- Loom/{loom_ui,scene_driver,sceneio,loom_render}.py
git show f53a82a:Loom/scene_driver.py | Select-String '_poll_mouse_unlock_key|logic_paused|request_quit|ortho'
   -> 空输出（基线无这些符号 = 本轮新增）
git show f53a82a:Loom/tests/test_vk_camera_align.py   # 该测试自 f53a82a 起未改动

# 既有脚本式测试（Loom/tests 多数是脚本，不是 pytest 用例）
cd Loom
python tests\test_ui.py                          -> exit=0  总结果: ALL PASS
python tests\test_ui_multi_canvas_hit.py         -> exit=0  总结果: ALL PASS（19 项，含 Q7=C）
python tests\test_sceneio.py                    -> exit=0  总结果: ALL PASS ✅
python tests\test_vk_ui_input.py                -> exit=0
python tests\test_wheel_backend_semantics.py    -> exit=0
python tests\test_scene_driver_lod.py           -> exit=0
python tests\test_scene_driver_physics_log.py   -> exit=0  总结果: ALL PASS
python tests\test_render_api.py                 -> exit=0  总结果: ALL PASS ✅
python tests\_tmp\verify_ui_dropdown.py         -> exit=0
python tests\_tmp\verify_ui_scroll_clip.py      -> exit=0
python tests\_tmp\smoke_ui_c3.py                -> exit=0
python tests\test_vk_camera_align.py            -> exit=1  FAIL 10 Tab 经脚本解锁鼠标 (True, False)   ★

# 本轮探针（只读，不 import 进产品代码）
python tests\_tmp\beta3_scan_03_probe1.py   # 相机字段读/写 + UI 绑定链初测
python tests\_tmp\beta3_scan_03_probe2.py   # UI 绑定链（正确调用序）+ 正交退化值
python tests\_tmp\beta3_scan_03_probe3.py   # 仓库场景字段普查 + VK UI 命中空间 + 暂停态输入
python tests\_tmp\beta3_scan_03_probe4.py   # 解锁键双触发 A/B + 假值脚本实例
python tests\_tmp\beta3_scan_03_probe5.py   # GL/VK 对同一 camera 段的消费对比 + 旧场景重置
```

### 0.4 工作树自查（硬约束 8）

```
git status --porcelain          # 扫描开始时（含他人未跟踪文件）
?? tools/lint_except_dist/
?? tools/loom_lint_except.py
# 扫描中途一次：?? Loom/tests/日志.txt  ← 我自己跑 test_wheel_backend_semantics.py 产生
#   （内容首行 "===== 启动 2026-11-08 12:09:32 | exe=tests\test_wheel_backend_semantics.py ====="）
#   已确认为我的副产物并删除（未改任何受跟踪文件）。
# 扫描结束时
?? docs/audit/scan_beta3_05_packaging_release.md   ← 其它子代理的报告，未动
?? tools/lint_except_dist/  ?? tools/loom_lint_except.py   ← 本轮之前既有，未动
```

**未修改任何受跟踪文件**；未执行 git add/commit/checkout/stash。我新建的文件仅：
本报告 + `Loom/tests/_tmp/beta3_scan_03_probe{1..5}.py`。

### 0.5 本轮目标等级

按方法论 §10 判 A6：双向链（8 段）齐全、有 `P-UNKNOWN` 且给出"还缺什么"、跳过项逐条留痕、
人类裁决项收敛为"选 A 还是 B"。**未**执行修复（硬约束 1/7）。

---

## 1. 粗筛清单（含跳过登记）

### 1.1 疑似项（六元组）

| ID | 位置 | 标签 | 初步方向（指向具体代码事实） | 是否本轮引入 |
|---|---|---|---|---|
| P-03-01 | `scene_driver.py:970-971` + `scripts.py:641-645,700-704` + `engine.py:935` | STATE-MACHINE / AUDIT-ASYMMETRY | 引擎级"强制解锁键"每次按下沿 toggle 一次，而内置 first_person/third_person 脚本**也**在同一帧对 Tab toggle 一次 → 两次抵消 | 是（基线无 `_poll_mouse_unlock_key`） |
| P-03-02 | `scene_driver.py:574-578` 与 `:589` | SEM-DEADCODE / DESIGN-DRIFT | 场景 `camera.fov` 读进 `self.fov` 后第 589 行**无条件**重置为 60° | 是（新增的读被写覆盖） |
| P-03-03 | `scene_driver.py:579` | IFACE-PRECOND / SEM-MISMATCH | `ortho_size` 是该函数里**唯一**没走 `_f1` 容错的相机数值字段，与 B4"不抛"自相矛盾 | 是 |
| P-03-04 | `sceneio.py:1117` | SEM-SILENT / BND-TYPE | `bool(cam.get('ortho', False))` 对字符串 `'false'` 得 True（静默错值），与 B2 冲突 | 是 |
| P-03-05 | `sceneio.py:1109` + `editor.py:1056` | SEM-SILENT / IFACE-PARTIAL | 场景**没有** `camera` 键时完全不产出 `camera_out` → 消费端不重置 → 旧投影状态残留，并会被写回旧文件 | 是（写侧新增使残留可落盘） |
| P-03-06 | `scene_driver.py:579,845-851`；`loom_render.py:787-791`；`editor.py:2079-2084` | BND-OFFBYONE / BND-RESOURCE | `ortho_size` 无合法域校验：0 → `mat4_ortho` 里 `2/(right-left)` 除零；负数 → 左右反号（水平镜像）；NaN → 整屏不可见 | 是 |
| P-03-07 | `scene_driver.py:691-693`（提前 return）+ `:970-971`（解锁键在 `_update_scripts` 内） | STATE-MACHINE / IFACE-UNIT | 暂停后 `_update_scripts` 整段不跑 ⇒ 解锁键与**惰性脚本实例化**同时失效；且 `consume_mouse_input` 不结算 ⇒ VK 的 `_pending_mouse_rel` 整段暂停期累积 | 是 |
| P-03-08 | `loom_ui.py:74-79` | SEM-SILENT / AUDIT-ASYMMETRY | `target = getattr(sc,'_script',None) or sc`：运行时实例若"假值"（自定义 `__len__`/`__bool__`）会静默回落组件 → 方法找不到 → 事件丢弃；未实例化时打印"无方法"误导 | 是 |
| P-03-09 | `vk_renderer.py:1029,1054,1998-1999`（`engine=None` 默认值） | SEM-SILENT / AUDIT-ASYMMETRY | 不传 `engine` 时 `_ACTIVE_ENGINE` 回落成绘制门面 `VkUIEngine`（无 `.models`）→ 事件静默不派发；`loom_ui.draw_all` 的 `script_host=None` 默认值同样静默 | 是 |

### 1.2 跳过登记（四类可审计理由之一）

| 跳过号 | 位置 | 理由类型 | 出处/证据 |
|---|---|---|---|
| S-03-01 | `loom_ui.py:134-200`（rect/anchor/pivot 钳制与布局数学） | ③已有回归测试覆盖 | `python tests\test_ui.py` → 总结果 ALL PASS（13 项，含左上/右下/居中/自动换行） |
| S-03-02 | `loom_ui.py:421-457`（多 Canvas Q7=C 命中）、`:512-630`（点击/拖动/焦点/滚轮分支） | ③已有回归测试覆盖 | `python tests\test_ui_multi_canvas_hit.py` → ALL PASS 19 项（含"顶层空白+低层子元素命中""低层 ScrollView 滚轮""按下/松开消费"）；`tests\_tmp\verify_ui_dropdown.py`、`verify_ui_scroll_clip.py` exit=0 |
| S-03-03 | `sceneio.py:1124-1200`（migrate v1..v10 版本迁移、坏字段容错） | ③已有回归测试覆盖 | `python tests\test_sceneio.py` → ALL PASS ✅（含"坏 position/rotation/scale/光源/摄像机/轨道相机字段不崩"） |
| S-03-04 | `sceneio.py:1032,1075-1080`（父链成环拒绝） | ③已有回归测试覆盖 | `tests\test_scene_cycle_reject.py`、`tests\test_editor_load_reject_keeps_scene.py`（成环 → `SceneCycleError` 且旧场景保留）；与 B2"会死循环/丢数据的必须拒绝"一致 |
| S-03-05 | `loom_render.py:836-879`（主循环限帧 120FPS / 退出钩子派发顺序） | ②白盒契约明确声明 | `loom_render.py:842-845` 注释写明限帧语义与 `pygame.time.Clock.tick(120)` 等价；本轮 diff 只在该函数末尾插入"释放鼠标捕获"4 行，未改循环体 |
| S-03-06 | `loom_ui.py:759-789`（`_KEY_CODE_TO_NAME` 键码表） | ①语言规范保证 | 惰性初始化用 `try: import pygame / except Exception: {}`，缺失时 `dispatch_key` 直接 `return False`（`loom_ui.py:491-499`）；无 ValueError 路径 |
| S-03-07 | `scene_driver.py:680-682`（`_physics_frame`） | ②白盒契约明确声明 | 注释声明"R1: 只改调用时机, 桥三段一行不动"，diff 未触及该函数 |

---

## 2. 逐项裁决

> 记号：反手 = 努力证明"这里没有 bug"；正手 = 努力证明"这里有 bug"。
> 每条链按 8 段式（判定基准 / 代码证据 / 推理链+路径枚举 / 预期 / 实际 / 差异 / 验证 / 判定）。

---

### P-03-01　解锁键被"引擎轮询 + 内置脚本"各 toggle 一次 → 净效果为零　【P-PROVED · P0 · [REGRESSION]】

**反手（证伪：这里没有 bug）**

1. 判定基准：B8 声明"其余游戏始终可按 Tab 切换"，B9 声明"Tab 的切换由 first_person/third_person 脚本走 driver.toggle_mouse_locked"。若两者作用于不同键名/不同状态位，则不冲突。
2. 代码证据：`scene_driver.py:907-926`（`_poll_mouse_unlock_key` 读 `self.get_action('解锁鼠标')`，默认键 = `DEFAULT_ACTIONS['解锁鼠标']`）与 `scripts.py:641-645`（`tab = e.is_key('Tab')` → `e.toggle_mouse_locked()`）。
3. 推理链（路径枚举）：
   - 路径 1：游戏没挂 first_person/third_person，且键位把"解锁鼠标"改到非 Tab 键 → 只有一个 toggle 源 → 无冲突（**成立**，吃豆人即此路径）。
   - 路径 2：游戏挂了 first_person（GL/VK 默认"自由视角"示例脚本），"解锁鼠标"仍为默认 Tab → 两个 toggle 源同帧命中。
   - 路径 3：`mouse_lock_allowed=False` → 轮询直接早退，只剩脚本 toggle → 无冲突。
   - 路径 2 无法排除 ⇒ 反手必须靠"两次 toggle 不会发生在同一帧"或"脚本不处理 Tab"来成立；两者都被代码否掉（同一 `_update_scripts` 调用内顺序执行；脚本硬编码 Tab）。
   → **反手失败**（存在会产生疑似行为的路径）。
4. 5-8 段见正手链。

**正手（证真：这里有 bug）**

1. 判定基准：B8（引擎保留解锁键必须真的能解锁）+ B9（内置脚本也在同一键上 toggle）。
2. 代码证据：
   ```python
   # scene_driver.py:970-971（本轮新增，位于 update_scripts 的第一句）
   def _update_scripts(self, dt):
       self._poll_mouse_unlock_key()
   # scene_driver.py:907-926
   k = bool(self.get_action('解锁鼠标'))
   if k and not getattr(self, '_unlock_key_prev', False):
       self.toggle_mouse_locked()
   # scripts.py:641-645（既有内置脚本，两处：641-645 与 700-704）
   tab = e.is_key('Tab')
   if tab and not self._tab_was:
       e.toggle_mouse_locked()
   self._tab_was = tab
   ```
3. 推理链：`_update_scripts` 第一句先 toggle（解锁）→ 随后遍历脚本 `update()`，first_person 看到**同一个** Tab 按下沿 → 再 toggle（回锁）→ 净状态不变；`_unlock_key_prev` 与脚本的 `_tab_was` 都在本帧置 True，下一帧不会补偿。
4. 预期（B8）：按一次 Tab，`mouse_locked` 变为 False 且保持到再按一次。
5. 实际：`mouse_locked` 保持 True。
6. 差异：少做了一次"最终生效的解锁"（被第二次 toggle 抵消）。
7. 可复现验证：
   ```
   $ python tests\_tmp\beta3_scan_03_probe4.py
   [H0] after on_start: mouse_locked=True unlock_requested=False
   [输入] 按键 [Tab] 切换鼠标锁定 -> 已解锁
   [H1] after engine _poll_mouse_unlock_key: locked=False requested=True
   [H2] after first_person.update (same frame): locked=True requested=False
   [H3] second Tab press (full _poll+script): locked=True requested=False
   [H4] poll disabled -> Tab press: locked=False requested=True  (expect False/True)
   [H5] engine.GLEngine also polls unlock key: True
   [H6] built-in scripts toggling on Tab edge: 2 sites
   ```
   仓库自带回归测试**已经变红**（该测试文件自 f53a82a 起未改动，见 §0.3 `git log`）：
   ```
   $ python tests\test_vk_camera_align.py
   PASS 10 玩家脚本 on_start 锁定鼠标
   [输入] 按键 [Tab] 切换鼠标锁定 -> 已解锁
   FAIL 10 Tab 经脚本解锁鼠标  (True, False)
   总结果: 有 FAIL ❌ ['10 Tab 经脚本解锁鼠标']
   ```
   A/B 对照（`[H4]`：把本轮新增的引擎轮询临时置空，不碰产品文件）→ 同一序列恢复 PASS 行为，因果闭合。
8. 判定：**P-PROVED，等级 P0（玩家交互功能完全失效：无法释放光标），[REGRESSION]：基线 `git show f53a82a:Loom/scene_driver.py | Select-String _poll_mouse_unlock_key` 为空。**

**影响面**：任何挂了内置 `first_person`/`third_person`（或任何自己在 Tab 上 toggle 的第三方脚本）的游戏；GL 与 VK 同源（`engine.py:935` 同样把它放在 `update_scripts` 第一句）。吃豆人这类不挂自由视角脚本的游戏不受影响，所以开发机自测容易漏。

**修复方向（不含代码）**：把"强制解锁键"与"脚本解锁意图"收敛为单一权威：
- 方向 A（推荐）：让引擎轮询**不**直接 toggle，而是只置"解锁意图"（`mouse_unlock_requested`）并让 `_apply_mouse_lock` 幂等收敛；
- 方向 B：引擎轮询检测到该键按下沿后，跳过本帧给脚本的键可见性（对"解锁鼠标"动作做一次性掩码）。
无论哪个方向都必须保持：① `mouse_lock_allowed=False` 时永不锁（B8①）；② 第三方脚本仍可用 `e.toggle_mouse_locked()`（B9 不能破）；③ `_ui_capture_mouse`（特殊场景）优先级不变（`scene_driver.py:1146-1164`）；④ GL/VK 同步修（`engine.py:935` 有同源代码），否则制造新的后端分叉。
**波及调用方**：`engine.py:882-935`（GL 同源）、`scripts.py:641-645,700-704`、`runtime.py:84`、`vk_player.py:355-364`、`tests\test_vk_camera_align.py §10`、`tests\test_scripts.py:245-275`。

---

### P-03-02　场景 `camera.fov` 在 VK 驱动里"读了又被覆盖"　【P-PROVED · P1 · [REGRESSION]】

**反手（证伪）**

1. 基准：B3 把 `fov` 列入"播放时强制套用"的场景相机段；B4 要求与 `camera_out` 分支逐条对齐。
2. 代码证据：`scene_driver.py:574-578`（读 `cam['fov']`，异常则 pass）→ `:587-589`（注释"加载 = 一次新会话基线: FOV 回到默认 60°" + `self.fov = math.radians(60.0)`）。
3. 路径枚举（该函数中所有能决定最终 `self.fov` 的路径）：
   - 路径 1：场景有 `active_camera`（`:593-595` → `apply_camera` → `:1262` `self.fov = radians(cam.fov)`）→ 最终 fov 来自**相机实体**，与 camera 段 fov 无关 → 疑似项不成立（这是 B3 未覆盖的情形，合法）。
   - 路径 2：无 `active_camera`（`:597` `orbit_mode = True`）→ 落在 `:589`，覆盖了 `:576` 的读 → 疑似项成立。
   - 路径 3：`load_from_data` 之外（`__init__:413` 默认 60°）→ 与 `:589` 同值。
   路径 2 存在且是"轨道相机 + 场景 fov"的唯一路径 ⇒ **反手失败**。
4. 其余见正手。

**正手（证真）**

1. 基准：B3 明文"场景 camera 段（… fov）——播放时强制套用"；B10 双后端一致。
2. 代码证据：`scene_driver.py:576` 与 `:589`（同一函数内 13 行后无条件覆盖）；对照 GL 侧 `runtime.py:59-67` 把 `cam_out['fov']` 写成 `self._fov`、`editor.py:959-965` 同样写入。
3. 推理链：`fov=100` 的场景 → `:576` 得 1.7453 rad → `:589` 强制 1.0472 rad → `render_pose` 用 60° 出 VP；GL 侧同场景用 100° 出 VP ⇒ 同一场景两后端画面不同。
4. 预期：VK 播放器按场景 100° 出图。
5. 实际：60°。
6. 差异：少做 40° 的视场（画面内容明显不同，非数值误差）。
7. 验证：
   ```
   $ python tests\_tmp\beta3_scan_03_probe5.py
   [I1] GL camera_out fov=100.0 ortho=True ortho_size=13.0
        runtime.PlayerApp would set _fov=1.7453 rad (100.0 deg)
   [I2] VK  driver.fov=1.0472 rad (60.0 deg)  ortho=True ortho_size=13.0
   $ python tests\_tmp\beta3_scan_03_probe1.py
   [A fov] scene=fov90 fov_deg_in=90.0 -> driver.fov_deg=60.0000
   [A fov] scene=fov45 fov_deg_in=45.0 -> driver.fov_deg=60.0000
   ```
8. 判定：**P-PROVED，P1（B3 明文契约不成立 + 双后端不等价），[REGRESSION]（该读语句是本轮新增，且新增位置在既有重置之前）。**

**可达性说明（不夸大）**：仓库内现有场景（`压测50球/压测500球/压测500混合/场景.json/pacman2d_scene/pacman3d_scene/跳台试炼`）的 `camera.fov` 全部 = 60（`probe3 §1` 普查），所以"当下可见故障"尚未出现；但只要场景来自手工编辑/外部工具（`sceneio` 写侧会忠实写出 `_fov`，见 D 段）或将来加 fov 调节 UI，就会立刻分叉。**等级按契约定 P1，按当下可见性算 P2**，请在 §5-Q3 裁决。

**修复方向**：把"场景 fov"的生效点放在`重置之后`（要么删掉 `:589` 的默认重置、要么把默认值作为 `:576` 的 `except`/缺键兜底）；必须保持：① 无 `camera` 键时仍等价于引擎默认 60°（与 `PlayerApp` 的 `_fov` 初值一致，`scene_driver.py:587-589` 注释）；② `active_camera` 存在时相机实体 fov 仍最高优先（`:1262`）；③ GL 侧 `_f1(cam.get('fov'),60.0)` 的容错语义不变。
**波及**：`scene_driver.load_from_data` / `render_pose` / `_update_lod`（`:788` 用 `self.fov` 算 LOD 屏幕占比 → 改 fov 会同时改 LOD 选模，需回归 `tests\test_scene_driver_lod.py`）。

---

### P-03-03　`ortho_size` 是唯一未容错的相机字段 → 坏场景 VK 启动失败并静默回退 GL　【P-PROVED · P1 · [REGRESSION]】

**反手（证伪）**

1. 基准：B4 白盒注释"任一字段类型错/元素数不足 3 -> 回落默认, **不抛** (GL 同语义)"；B2"报错即可，不得静默错值"。
2. 代码证据：`:573` `bool(cam.get(...))` 不抛；`:575-578` try/except；`:579` `float(cam.get('ortho_size', 12.0))` **裸 float**；`:580` `_f3`（容错）、`:584-586` `_f1`（容错）。
3. 路径枚举：
   - 路径 1：`ortho_size` 缺键 → 12.0，不抛。
   - 路径 2：数值/数字字符串 → float 成功，不抛。
   - 路径 3：非数字字符串/None/list → `ValueError`/`TypeError` 直冲 `load_from_data` 之外。
   - 路径 4：`ortho_size` = 0/负数/NaN → 不抛但进 P-03-06。
   路径 3 存在 ⇒ **反手失败**。
4. 其余见正手。

**正手（证真）**

1. 基准：B4（"不抛，GL 同语义"）。
2. 代码证据：`scene_driver.py:579`；对照同语义 GL 路径 `sceneio.py:1118` `'ortho_size': _f1(cam.get('ortho_size'), 12.0)`（`_f1` 定义在 `sceneio.py` 顶部："容错单数值: 可转 float 才用, 否则 default (坏场景文件不崩)"）。
3. 推理链：`{"camera":{"ortho_size":"abc"}}` → VK `load_from_data` 抛 `ValueError`（`vk_player.py:146-147` 调用点无 try）→ `run_backend('vulkan')` 只 catch `VkInitError`（`run_player.py:141-146`）→ 冒泡到 `game_player._run_backend_safe` 的 `except Exception`（`game_player.py:182-185`）→ **静默改走 OpenGL**。GL 路径：`_f1` → 12.0 → 正常打开。
4. 预期：坏字段回落默认、两后端都能开。
5. 实际：VK 打不开该场景（异常），打包版玩家被无声换到 GL。
6. 差异：VK 少了容错；后端切换无提示（发布链只在 stdout 打一行，打包版无控制台）。
7. 验证：
   ```
   $ python tests\_tmp\beta3_scan_03_probe1.py
   [B bad {'ortho_size': 'abc'} ] load RAISED ValueError: could not convert string to float: 'abc'
   [B render_pose {'ortho_size': 'abc'}] RAISED ValueError: could not convert string to float: 'abc'
   [C bad ortho types] camera_out={'target': (0.0, 0.0, 0.0), 'distance': 10.0, 'yaw': 0.6,
                                   'pitch': -0.35, 'ortho': True, 'ortho_size': 12.0, 'fov': 60.0}
   ```
   （最后一行证明 GL 侧同一份坏数据被 `_f1` 收敛成 12.0。）
8. 判定：**P-PROVED，P1（后端健康度/玩家可见行为），[REGRESSION]。**

**修复方向**：`:579` 改走与同函数其余字段一致的容错取值（`_f1`/try），并顺带做合法域检查（见 P-03-06）；必须保持：① B4"不抛"；② B2"不得静默错值"——即类型错回落默认、数值非法（≤0/NaN）明确报出或钳制，不要静默接受。
**波及**：`scene_driver.load_from_data`、`render_pose`；GL 侧 `editor.py:958`、`runtime.py:62` 是**同类裸 float**（见 §4 的 P2 建议：三处一起收口，否则一处修完仍会分叉）。

---

### P-03-04　`bool(cam.get('ortho'))` 把字符串 `'false'` 当 True　【P-PROVED · P2 · [REGRESSION]】

**反手（证伪）**

1. 基准：B2"不得静默错值"；JSON 场景里布尔应是 `true/false`（`sceneio` 写侧写的是 Python bool）。
2. 代码证据：`sceneio.py:1117` `'ortho': bool(cam.get('ortho', False))`；`scene_driver.py:573` 同款。
3. 路径枚举：
   - 路径 1：键存在且是 bool → 正确。
   - 路径 2：键缺失 → False（旧场景兼容正确）。
   - 路径 3：键是 0/1 → bool() 语义可接受（0→False/1→True）。
   - 路径 4：键是字符串 `'false'`/`'0'`/`'no'`（JSON 作者笔误、或从别的工具导入的字符串布尔）→ **True**。
   - 路径 5：键是空 dict/list → False。
   路径 4 存在且产生静默错值 ⇒ **反手失败**。
4. 其余见正手。

**正手（证真）**

1. 基准：B2（不得静默错值）。
2. 代码证据：同上；对照项目内已有的布尔容错帮手 `game_settings.read_bool`（把 `"false"/"0"/"no"` 判 False）——说明项目已有"字符串布尔按文本语义解析"的既有标准，sceneio 未采用。
3. 推理链：`{"ortho": "false"}` → `bool('false')` = True → 场景被当正交加载；GL 与 VK **都**错（`camera_out` 与 `cam` 两条读侧各自 `bool()`）。
4. 预期：按文本语义解析或明确报错。
5. 实际：静默变正交（画面从透视变"平推"，用户观感是"透视没了"，且 `fov` 一并失效）。
6. 差异：静默错值，无任何日志。
7. 验证：
   ```
   $ python tests\_tmp\beta3_scan_03_probe1.py
   [B bad {'ortho': 'false'} ] load OK -> ortho=True ortho_size=12.0 fov_deg=60.0000
   [B render_pose {'ortho': 'false'}] VP finite=True diag=[0.1041, 0.1592, 0.00095, 1.0]   # 正交矩阵
   [C bad ortho types] camera_out={... 'ortho': True ...}                                   # GL 侧同样错
   ```
8. 判定：**P-PROVED，P2（边界输入/静默错值；不崩、不丢文件），[REGRESSION]。**

**修复方向**：`ortho` 读侧统一走一个"布尔容错"取值（可复用项目既有文本布尔语义），非法类型按 B2 的口径报出而非静默；GL/VK 两侧同改（`sceneio.py:1117` 与 `scene_driver.py:573`），否则又是单边修。

---

### P-03-05　没有 `camera` 键的旧场景：不产出 `camera_out` → 编辑器不重置投影，且残留值会被写回文件　【P-PROVED · P2 · [REGRESSION]】

**反手（证伪）**

1. 基准：B3（相机段播放时强制套用）+ 旧场景兼容要求（`sceneio` 读侧"缺字段回落默认"）。
2. 代码证据：`sceneio.py:1109` `if camera_out is not None and data.get('camera'):` → 没有 `camera` 键时**整块跳过**；消费端 `editor.py:1056-1057` `if cam_out: self._apply_camera(cam_out)`；对照 `scene_driver.py:567-573` `if not _has_cam: cam = {}` 后**无条件**执行 `self.ortho = bool(cam.get('ortho', False))`（即会重置）。
3. 路径枚举：
   - 路径 1：场景有 `camera` 且含 `ortho` → camera_out 完整，编辑器重置 ✓。
   - 路径 2：场景有 `camera` 但缺 `ortho` → `:1117` 给 False → 重置 ✓。
   - 路径 3：场景**完全没有** `camera` 键（`projects\mcp_procedural_arena.json` 实测 `camera=None`；v1-era 旧存档同理）→ camera_out 为空 → 消耗端不执行 → 编辑器保留上一场景的 `ortho/ortho_size/_fov`；而 VK 会重置为 False。
   路径 3 存在 ⇒ **反手失败**。
4. 其余见正手。

**正手（证真）**

1. 基准：B3 + 双后端一致（B10）+ 旧场景兼容（B2 的"不得静默错值"）。
2. 代码证据：`sceneio.py:1109-1120`；`editor.py:1054-1057`（`cam_out = {}` → `scene_from_dict(..., camera_out=cam_out)` → `if cam_out:`）；写侧 `sceneio.py:1049-1058` 用 `getattr(engine,"ortho",False)` 落盘。
3. 推理链：编辑器先开正交场景 → `self.ortho=True` → 再开一个无 `camera` 键的旧场景 → `cam_out` 空 → `_apply_camera` 不调用 → `self.ortho` 仍 True（旧场景被以正交显示）→ 此时点保存：`scene_to_dict(self, camera=self._camera_dict())` 的 `setdefault("ortho", engine.ortho=True)` 把 `ortho/ortho_size/fov` **写进**这份旧场景文件（原本没有这些键）。
4. 预期：旧场景按缺键默认（透视 60°）打开，编辑器的空 `_camera_dict()` 只补写默认值。
5. 实际：继承上一场景投影，并把继承值固化进旧文件。
6. 差异：多写了 3 个键 + 用错了投影模式（"静默错值 + 静默改写用户文件"）。
7. 验证：
   ```
   $ python tests\_tmp\beta3_scan_03_probe5.py
   [I3] VK  load scene WITHOUT camera key -> ortho=False (reset)
   [I4] GL  camera_out={} -> editor 'if cam_out:' branch NOT taken -> engine.ortho=True
   $ python tests\_tmp\beta3_scan_03_probe1.py
   [C no camera key] camera_out={}  (consumer: 'if cam_out: apply')
   ```
   仓库内真的存在无 `camera` 段的场景：`probe3` 普查输出 `mcp_procedural_arena.json version=1.0 camera=None`。
8. 判定：**P-PROVED，P2（不崩但静默错值 + 用户文件被改写），[REGRESSION]（写侧 3 个 `setdefault` 是本轮新增，使残留可落盘）。**

**修复方向**：读侧要么在"无 `camera` 段"时也向 `camera_out` 填默认值（`ortho=False, ortho_size=12, fov=60`，与缺字段路径一致），要么由消费端在 `cam_out` 为空时显式重置；**不要**只在编辑器里补——VK 的 `load_from_data` 已经是"无条件重置"语义，两处必须表达同一个不变量。必须保持：① 旧场景兼容（缺键 → 默认透视 60°，`probe1 [C camera w/o ortho]` 已证明含 camera 键时行为正确）；② `scene_to_dict(camera=None)`（脏检查调用，`editor.py:881`）不得因此变化，否则会破坏脏检查语义。

---

### P-03-06　`ortho_size` 无合法域校验：0 直接除零、负数镜像、NaN 全黑　【P-PROVED · P2 · [REGRESSION]】

**反手（证伪）**

1. 基准：B2"报错即可，不得引入死循环或静默错值"；投影三处都应在同一合法域上工作。
2. 代码证据：三处投影分支公式一致（`scene_driver.py:845-851`、`loom_render.py:787-791`、`editor.py:2079-2084`），全部用 `_h = float(getattr(self,'ortho_size',12.0))` 后 `mat4_ortho(np, -_h*asp*0.5, _h*asp*0.5, -_h*0.5, _h*0.5, near, far)`；`matlib.mat4_ortho` 是 `2/(right-left)`。
3. 路径枚举：
   - 路径 1：`ortho_size > 0` → 正常。
   - 路径 2：`ortho_size = 0` → `right-left = 0.0` → Python float 除零 → `ZeroDivisionError`。
   - 路径 3：`< 0` → 上下界互换（`left>right`）→ 水平镜像，不报错。
   - 路径 4：NaN → 矩阵全 NaN → 全部几何被裁掉（黑屏），不报错。
   - 路径 5：`ortho=False` → 该值不参与，无影响。
   路径 2/3/4 存在 ⇒ **反手失败**。
4. 其余见正手。

**正手（证真）**

1. 基准：B2（不得静默错值；会丢数据/崩溃的必须拒绝）。
2. 代码证据：同上；入口唯一钳制出现在 `agent_commands.py:1024` `ed.ortho_size = max(1.0, as_float(args.get('size'), 12.0))`（**只有 EAI 命令钳制**，场景加载路径没有）。
3. 推理链：场景 `{"ortho":true,"ortho_size":0}` → `scene_driver.load_from_data` 通过（P-03-03 的路径 4）→ 每帧 `render_pose` 抛 `ZeroDivisionError` → `vk_player.draw` 的 `except BaseException`（`vk_player.py:454-468`）→ `canvas.close()` → `run_vk` 抛 `VkRunError` → 游戏退出。同一场景在 GL 侧 `loom_render.py:790` 同样除零。
4. 预期：非法尺寸被拒绝或钳制（B2：报错即可）。
5. 实际：VK 直接终止运行；负数静默镜像；NaN 静默黑屏。
6. 差异：崩溃 / 静默错值两类都违反 B2。
7. 验证：
   ```
   $ python tests\_tmp\beta3_scan_03_probe2.py
   [G {'ortho': True, 'ortho_size': 0}  ] render_pose RAISED ZeroDivisionError: float division by zero
   [G {'ortho': True, 'ortho_size': -5} ] VP finite=True diag=[-0.25, -0.382135, 0.000955, 1.0]   # 负号
   [G {'ortho': True, 'ortho_size': 12} ] VP finite=True diag=[0.104167, 0.159223, 0.000955, 1.0]  # 正常
   [G {'ortho': True, 'ortho_size': nan}] VP finite=False diag=[nan, nan, 0.000955, 1.0]
   ```
8. 判定：**P-PROVED，P2（需要构造场景；一旦构造则是崩溃级 → 若人类认为"崩溃级一律 P1"可上调），[REGRESSION]。**

**修复方向**：在**数据入口**（`scene_driver.load_from_data`、`sceneio` 读侧）与**消费点**双保险，采用与 `clamp_camera_distance`（`scene_driver.py:581-584` 注释"场景是外部输入, 距离在入口钳制"）完全同款的既有做法：入口钳制 + 非法值拒绝。必须保持：① 与 EAI 命令 `max(1.0, ...)` 的下界一致；② 三处投影（editor/PlayerApp/SceneDriver）取同一套公式与同一套钳制，否则修复本身制造新的后端分叉（这正是 §9.2 的 A/B 基线关心的）。

---

### P-03-07　暂停冻结 `_update_scripts` 的连带效应：解锁键失效 + VK 独占的鼠标增量积压　【P-PROVED · P1 · [REGRESSION]】

**反手（证伪）**

1. 基准：B8（解锁键"其余游戏始终可按"）、B6（`mouse_rel` = 本帧增量）、B10（双后端一致）。
2. 代码证据：`scene_driver.py:691-693`
   ```python
   if getattr(self, 'logic_paused', False):
       self._end_frame_input()
       return (0, 0)
   ```
   后续 `consume_mouse_input()` / `_refresh_player_camera()` / `_update_scripts()` 全部不执行；`_poll_mouse_unlock_key()` 是 `_update_scripts` 的第一句（`:970-971`）。
3. 路径枚举：
   - 路径 1：未暂停 → 一切照旧（无问题）。
   - 路径 2：暂停 + `mouse_locked=False`（吃豆人这类 `mouse_lock_allowed=False` 或已解锁）→ 解锁键失效无实际影响。
   - 路径 3：暂停 + `mouse_locked=True`（默认配置 `MOUSE_LOCK_INITIAL_DEFAULT=True`，`game_settings.py`）→ 玩家无法解锁 → 光标不可达 → 暂停期的"结算面板"点不到（与 P-03-01 叠加后更严重：连 Tab 都是双触发）。
   - 路径 4：暂停期间 `feed_mouse_rel` 被持续调用（`vk_player.py:398-403` 帧首无条件喂增量；`feed_mouse_rel` 只在解锁时清零，`scene_driver.py:1166-1173`）→ `_pending_mouse_rel` 累积，恢复首帧一次性结算 → `mouse_rel` 巨值（B6 契约"本帧增量"被破坏）。
   - 路径 5：暂停期间 UI 仍能派发事件（`vk_player.py:397` `ui_bridge.begin_frame()` 在 `advance_logic` **之前**）→ 点击事件本身没被暂停阻断（这是好的一面，需在报告里说清，避免误判）。
   路径 3/4 存在 ⇒ **反手失败**。
4. 其余见正手。

**正手（证真）**

1. 基准：B8 + B6 + B10。
2. 代码证据：`:691-693`、`:970-971`、`:1175-1182`；对照 GL 的每帧刷新点 `loom_glfw_window.py:362` `self._update_mouse_rel()`（在 `_handle_events`，位于 `loom_render.run()` 循环首，不受 `_logic_paused` 影响）。
3. 推理链：
   - 解锁键：暂停 → `advance_logic` 提前 return → `_update_scripts` 不跑 → `_poll_mouse_unlock_key` 不跑 → `key_state['Tab']` 为真也没人消费。
   - 鼠标增量：暂停 10 帧每帧 `feed_mouse_rel(30,20)` → 累积 (300,200) → 恢复首帧 `consume_mouse_input` 一次性写出 `mouse_rel=(300,200)`；而 GL 侧 `mouse_rel` 每帧由窗口层刷新，暂停期不会累积（**VK 独占的差异**）。
4. 预期：暂停期解锁键仍生效（B8）；`mouse_rel` 永远是"本帧增量"（B6）。
5. 实际：解锁键在做冻结的帧里彻底静默；恢复首帧给脚本一个 10 帧的合成位移。
6. 差异：两处契约不一致，其中积压问题只在 VK 侧（后端不平权）。
7. 验证：
   ```
   $ python tests\_tmp\beta3_scan_03_probe3.py
   paused: key_state['Tab']=True get_action=True mouse_locked=True unlock_requested=False
      (Tab pressed while paused -> unlock not applied)
   paused 10 frames: pending_mouse_rel=(300.0, 200.0) mouse_rel=(0, 0)
   first frame after resume: mouse_rel=(300, 200) (one-frame spike)
   === 3 ... advance_logic while paused returns (0, 0)  clock.steps= 0  clock.alpha= 0.0
   ```
8. 判定：**P-PROVED，P1（暂停态玩家无法释放光标 → 面板不可点；若人类认定该类只在特定配置下发生，可降 P2），[REGRESSION]（暂停与解锁键都是本轮新增，两者的组合效应未覆盖）。**

**诚实标注（对称性）**：GL 侧 `advance_logic` 暂停分支同样跳过 `update_scripts`（`engine.py:1277-1284`），因此"暂停期解锁键失效"**不是 VK 独有**；只有"鼠标增量积压"是 VK 独有。修复时若只改 `scene_driver`，GL 侧的同一缺陷会留下 → 必须在 `engine.py` 同改，或把解锁键轮询移出"逻辑帧"（移到渲染帧首）。

**修复方向**：把"引擎保留解锁键"的轮询从"逻辑帧（可被暂停冻结）"移到"渲染帧必跑的一段"（例如 `advance_logic` 提前 return 之前的输入结算段）；暂停分支里同时把 `_pending_mouse_rel` 清零（B6：不得把暂停期位移结算成"本帧增量"）。必须保持：① `_end_frame_input` 仍清零 `mouse_wheel`（B5）；② 暂停期 UI 事件继续派发（`vk_player.py:397` 顺序不能动）；③ 暂停期脚本/物理/动画仍全冻结（吃豆人通关面板依赖这个语义）。

---

### P-03-08　`_fire_binding` 的 `or sc` 兜底会让"假值运行时实例"静默丢事件　【P-PROVED · P2 · [REGRESSION]】

**反手（证伪）**

1. 基准：B7（返回是否触发成功；异常不抛但要打印）。
2. 代码证据：`loom_ui.py:74` `target = getattr(sc, '_script', None) or sc`；`:76-79` 找不到方法时打印"脚本 %r 无方法 %r"。
3. 路径枚举：
   - 路径 1：`_script` 是真值实例 → 走实例 → 正常（`probe2 [F2]/[F4]` fire=True）。
   - 路径 2：`_script is None`（脚本还没被惰性实例化）→ 回落组件 → 组件无用户方法 → 打印"无方法" → 返回 False。
   - 路径 3：`_script` 是"假值实例"（类定义了 `__len__` 返回 0 或 `__bool__` 返回 False，例如把脚本写成列表子类/容器式脚本）→ 同样回落组件 → 打印"无方法" → 事件丢弃。
   - 路径 4：方法确实不存在 → 打印"无方法" → 丢弃（正确行为）。
   路径 3 存在 ⇒ **反手失败**（判定为"编辑期不可见的静默丢事件"，只在用户脚本自定义布尔语义时触发）。
4. 其余见正手。

**正手（证真）**

1. 基准：B7 + `loom_ui.py:127-131`（声明式绑定必须真的派发到脚本方法）。
2. 代码证据：同上；`_script` 的赋值点 `engine.py:997`、`scene_driver.py:996`、`loom_game_object.py:289`。
3. 推理链：用户脚本类定义 `__len__`（很常见：背包/路径点容器脚本）→ `getattr(sc,'_script') or sc` 求值为组件 → `getattr(组件,'on_click',None)` = None → 打印"无方法"并 return False → 玩家点击无反应，日志只给一句容易误读的"无方法"。
4. 预期：只要运行时实例存在（哪怕布尔假值）就派发到实例。
5. 实际：丢事件。
6. 差异：派发对象选错；且诊断信息误导（真实原因是"未实例化"或"实例布尔假"，文案却写"无方法"）。
7. 验证：
   ```
   $ python tests\_tmp\beta3_scan_03_probe4.py
   [H7] falsy (len==0) script instance: fire=False on_click hits=0
   $ python tests\_tmp\beta3_scan_03_probe2.py
   [F1 GL-style] _ACTIVE_ENGINE is host=True  _script=None -> fire=False
   [UI 事件] 脚本 'sid1' 无方法 'on_click'（触发自 'obj_g1'.'b1'）   # 实际是"未实例化"
   ```
8. 判定：**P-PROVED，P2（可达性依赖用户脚本写法；一旦命中就是"点不动"且难排查），[REGRESSION]。**

**修复方向**：把兜底判断从"真值判断"改成"存在性判断"（`is None`），并在两处诊断消息里区分"未实例化 / 实例缺方法 / 无宿主"。必须保持：① 未实例化时仍安全返回 False（不能抛）；② 不改变 `_find_script_instances` 的 `owner_guid` 过滤；③ 保持调用次数（`insts` 可能多实例，任一成功即 `fired=True`）。
**波及**：`vk_ui.py:321-332`（转发链）、`tests\_tmp\beta3_scan_02_probe_uibridge.py`（并行子代理的探针，结论一致需合并）。

---

### P-03-09　`draw_frame/draw_ui` 的 `engine=None` 默认值 → 事件静默退化为"无宿主"　【P-PROVED · P2 · [SEM-SILENT]】

**反手（证伪）**

1. 基准：B7（`_ACTIVE_ENGINE` 必须有 `.models`）。
2. 代码证据：`vk_renderer.py:1029` `def draw_ui(self, view, w, h, ui=None, hud_lines=None, hud=None, engine=None)`；`:1054` `eng.draw_all(ui, script_host=engine)`；`:1998-1999` `self.draw_ui(..., engine=engine)`；`loom_ui.py:706` `_ACTIVE_ENGINE = script_host if script_host is not None else engine`。
3. 路径枚举：
   - 路径 1：`vk_player.py:448-453` 传 `engine=driver` → 正确（生产路径 ✓）。
   - 路径 2：调用方不传 `engine` → `script_host=None` → `_ACTIVE_ENGINE` = `VkUIEngine`；`VkUIEngine` 动态实测 `hasattr(models)=False`、`hasattr(scripts)=False`、类内无 `__getattr__` → `_find_script_instances` 返回 [] → 只打印一行"找不到脚本实例"→ 返回 False。
   - 路径 3：`ui is None and not hud_lines` → `draw_ui` 在 `:1037-1038` 提前 return，根本不写 `_ACTIVE_ENGINE`（见 D-03-04）。
   路径 2 在仓库内**真实存在**（`tests\_tmp\ab_gl_vk_ui.py:172-176` 未传 `engine=`）⇒ **反手失败**（虽然只影响工具、不影响玩家路径）。
4. 其余见正手。

**正手（证真）**

1. 基准：B7。
2. 代码证据：同上 + 动态证据：
   ```
   $ python -c "import vk_ui;print(hasattr(vk_ui.VkUIEngine,'models'), hasattr(vk_ui.VkUIEngine,'scripts'))"
   False False
   ```
3. 推理链：可选参数 + "缺省即坏值"的组合 = 新调用方一旦忘记传 `engine`，UI 视觉全对、事件全丢，只在点击瞬间往 stdout 打一行（打包版无控制台 → 完全不可见）。
4. 预期：`script_host` 缺失时应显式告警/失败，或从 `ui` 侧拿不到宿主就不渲染可交互层。
5. 实际：静默降级为"纯绘制"。
6. 差异：GL 侧 `loom_render.py:821` `self.ui.draw_all(self)` 没有这种可选性 → 两端 API 语义不对称（AUDIT-ASYMMETRY）。
7. 验证：
   ```
   $ python tests\_tmp\beta3_scan_03_probe2.py
   [F5 default script_host=None] _ACTIVE_ENGINE type=Drawer has .models=True ... fire=False
   （Drawer 是桩；真实 VkUIEngine 的 hasattr 结果见上一行的 python -c 实测 False False）
   ```
8. 判定：**P-PROVED，P2（当前仅工具/未来调用方受影响；玩家路径已正确传参）。**

**修复方向**：把 `script_host` 从"可选默认 None"改为"必须显式传入"（或让 `VkUIEngine` 持有一个显式的 `script_host` 门面属性，取不到时在**首次**点击前就打印明确告警）。必须保持：① `draw_all(engine)` 的旧签名对 GL 仍可用（`loom_render.py:821`、`loom_gui.py:1041`、`minimal_editor_view.py:97` 三个调用点）；② 绘制目标与脚本宿主分离的修复成果（`probe2 [F2]/[F4]` 已证有效）不能回退。

---

### D-03-01　Q7=C「只吞空白」命中语义未被本轮改动破坏　【P-DISPROVED】

1. 判定基准：B1。
2. 代码证据：`loom_ui.py:421-457`（`_hit_screen` 逐 Canvas 下探，仅当全部无人命中才返回 `top`）；本轮 diff 只改 `_fire_binding:74` 与 `draw_all:706`，**未触及** `_hit_screen`/`hit_test`/`dispatch_mouse`（`git diff f53a82a..HEAD -- Loom/loom_ui.py` 只有这两个 hunk）。
3. 路径枚举（全部命中入口）：`dispatch_mouse:537`、`update_hover_only:678`、`_hit_scroll_view:665`、`UIManager.hit_test:452` —— 四个入口都走同一个 `_hit_screen`。
4. 预期：顶层空白不吞低层子元素；无人命中时顶层 root 吞空白。
5. 实际：与预期一致。
6. 差异：无。
7. 验证：`python tests\test_ui_multi_canvas_hit.py` → 19 项全 PASS（含"顶层空白 + 低层子元素 → 命中的是低层按钮"、"低层 ScrollView 滚轮真滚动"）。
8. 判定：**DISPROVED**（B1 未被破坏；且新增的 `script_host` 只影响"谁来当脚本宿主"，不移动任何几何/命中判定）。

---

### D-03-02　"draw_all 分离绘制目标与脚本宿主"这条 P0 修复本身有效　【P-DISPROVED（针对"修复无效"假设）】

1. 基准：B7 + 交接总纲 §2.7（该条已列为 P0 并声称修好）。
2. 代码证据：`loom_ui.py:706`、`vk_ui.py:321-332`、`vk_renderer.py:1048-1054`、`vk_player.py:448-449`。
3. 路径枚举：GL（`draw_all(self)` → `_ACTIVE_ENGINE=GLEngine` 有 `.models`）、VK（`script_host=driver` → `SceneDriver.models` 每个 `ScriptComponent` 带 `_script`，`scene_driver.py:996`）、旧形态（不传 → 回落绘制门面，见 P-03-09）。
4. 预期：点击触发运行时脚本方法。
5. 实际：触发。
6. 差异：无。
7. 验证：
   ```
   $ python tests\_tmp\beta3_scan_03_probe2.py
   [F2 runtime inst] fire=True calls=[()]
   [F4 VK-style] _ACTIVE_ENGINE is host=True fire=True
   [F3 old path getattr(comp,'on_click')=None      # 证明旧实现确实永远找不到方法
   ```
8. 判定：**DISPROVED**（修复有效）。**但**：仓库里**没有任何**受跟踪测试覆盖这条修复
   （`Select-String -Path 'Loom\tests\*.py','Loom\tests\_tmp\*.py' -Pattern 'script_host|_fire_binding|_ACTIVE_ENGINE|event_bindings'` 命中全部来自本轮子代理探针，无 `tests\test_*.py`）→ 建议把 `probe2 [F1][F2][F4]` 的三条断言收编为正式回归测试（见 §4-P2-4）。

---

### D-03-03　`loom_render` 新增正交分支不影响透视路径与 A/B 基线　【P-DISPROVED】

1. 基准：旧行为必须逐位保持；A/B 基线阈值 MAE<=0.0002（交接总纲 §5）。
2. 代码证据：`loom_render.py:786-794`
   ```python
   if getattr(self, 'ortho', False):
       _h = float(getattr(self, 'ortho_size', 12.0))
       _asp = self.width / max(1, self.height)
       P = mat4_ortho(np, -_h*_asp*0.5, _h*_asp*0.5, -_h*0.5, _h*0.5, self.near, self.far)
   else:
       P = mat4_perspective(np, self._fov, self.width / self.height,
                            self.near, self.far)
   ```
   基线（`git show f53a82a:Loom/loom_render.py`）= `P = mat4_perspective(np, self._fov, self.width / self.height, self.near, self.far)`，**参数序列逐字一致**（仅换行）。
3. 路径枚举：
   - 路径 1：`self` 没有 `ortho` 属性（`GLEngine` 类无此属性，实测 `hasattr(engine.GLEngine,'ortho')=False`；`loom_render.py` 全文无 `self.ortho` 赋值）→ `getattr(...)=False` → 走 else，**与基线同一条表达式**。
   - 路径 2：`PlayerApp` 从 `cam_out` 置位（`runtime.py:59-67`），场景 `ortho=false` → 仍走 else。
   - 路径 3：`ortho=True` → 新分支（新增能力，基线没有对应场景）。
   路径 1/2 覆盖全部既有场景 ⇒ 透视路径不变。
4. 预期：既有 22 场景 A/B 基线不受影响。
5. 实际：数学表达式未变，A/B 输入不变。
6. 差异：无（唯一潜在差异是 `height==0` 时：else 分支 `self.width/self.height` 会除零，而 ortho 分支用 `max(1,h)` —— 这是**基线既有**行为，不是本轮引入；见 §4-P3-2）。
7. 验证：
   ```
   $ python tests\_tmp\beta3_scan_03_probe5.py
   [I5] GLEngine has 'ortho' attr: False | loom_render.py mentions self.ortho: False | runtime.py sets it: True
   [I6] ... else-branch text: True
   ```
   说明：我**没有**跑 22 场景 A/B（需要真实 GL+VK 设备与 `tests\_tmp\ab_batch.py` 的完整夹具，且本轮只读约束下不适合长跑 GPU 基线）；此处以"表达式逐字未变 + 属性不可达"作证，若要求像素级复核，请人类/修复轮执行 `python tests\_tmp\ab_batch.py`（我在报告 §5-Q3 里留了这条）。
8. 判定：**DISPROVED**（就"本轮改坏透视路径"这一命题）。

---

### D-03-04　`_ACTIVE_ENGINE` 在异常/重入路径下无脏值残留　【P-DISPROVED】

1. 基准：B7（`_ACTIVE_ENGINE` 必须指向当前帧的脚本宿主）。
2. 代码证据：`loom_ui.py:704-706` —— 赋值是 `draw_all` 的**第一句**，先于任何 `_draw_elem`/dropdown 绘制（可能抛异常的只有 `_draw_elem` → `elem.draw`，由 `vk_ui.draw_all:329-332` 与 GL 调用点各自兜住）。
3. 路径枚举：
   - 路径 1：`_draw_elem` 抛异常 → `_ACTIVE_ENGINE` 已写入正确宿主（不是残留）。
   - 路径 2：`draw_ui` 因 `ui is None and not hud_lines` 提前 return（`:1037-1038`）→ 不写 `_ACTIVE_ENGINE`；生产路径 `vk_player.py:452` 恒传 `ui=driver.ui`（`SceneDriver.__init__:495-498` 保证非 None）→ 不成立。
   - 路径 3：同一帧内多次 `draw_all` 不同宿主（多 UIManager 叠加）→ 后写覆盖前写；仓库内 `draw_all` 的调用点只有三处且互斥（`loom_render.py:821` 播放器 / `loom_gui.py:1041` / `minimal_editor_view.py:97` 两个编辑器宿主）。
   - 路径 4：宿主对象被销毁后仍有 UI 点击 → 属"跨引擎生命周期"的外推，仓库内无此场景（`SceneDriver` 只在 `vk_player.py:146` 一处构造）。
4. 预期：每帧派发前宿主正确。
5. 实际：正确。
6. 差异：无（"全局变量无显式清理"属维护性备注，见 §4-P3-1）。
7. 验证：`probe2 [F4]`（VK 形态下 `_ACTIVE_ENGINE is host` True）+ 上面路径枚举的代码位置。
8. 判定：**DISPROVED**（本轮不构成 bug）。

---

### D-03-05　`scene_driver` 新增 `scripts/` 目录加载与 GL 同源、无重复副作用　【P-DISPROVED】

1. 基准：交接总纲 §2.7"VK 不加载 scripts/"这条 P0 的修法应与 GL 一致。
2. 代码证据：`scene_driver.py:418-425` 与 `engine.py:371-372` 使用同一个 `scripts.load_script_dir`、同一条相对路径规则（`os.path.dirname(os.path.abspath(__file__))` + `scripts`）。
3. 路径枚举：`SceneDriver` 的唯一构造点是 `vk_player.py:146`（`Select-String 'SceneDriver\('` 只此一处），VK 播放器进程里**不会**同时构造 `GLEngine`（`game_player`/编辑器走另一分支）→ 无同进程双加载；打包链的游戏脚本由 `register_sources`（`game_player.py:203-204`）先注册，dir 扫描只是补充。
4. 预期：GL/VK 同源加载。
5. 实际：同源。
6. 差异：无（唯一未知：打包 dist 里 `Loom/scripts/` 的内容是否与包内脚本版本一致 → U-03-02）。
7. 验证：两处代码对照 + `Select-String` 结果。
8. 判定：**DISPROVED**（本轮实现正确；剩余不确定性移交 U-03-02）。

---

### D-03-06　`loom_render` 退出前 `set_mouse_locked(False)` 无害　【P-DISPROVED（附顺序备注）】

1. 基准：退出时必须释放系统鼠标捕获（交接总纲 §2.6 最后一条）；同时不能破坏 `on_application_quit` 派发。
2. 代码证据：`loom_render.py:859-863`（`try: self.set_mouse_locked(False) except Exception: pass`）位于 `:866-869` 的 `_dispatch_application_quit()` **之前**。
3. 路径枚举：
   - 路径 1：有 GLFW 窗口 → `set_mouse_locked` 走 `glfw.set_input_mode` → 释放 ✓。
   - 路径 2：外部 ctx（Qt 宿主）→ `run()` 在 `:838-840` 已提前 return，不进入本段 ✓。
   - 路径 3：窗口已销毁 → 异常被 `except Exception: pass` 吞掉 → 不改变退出流程。
   - 路径 4：脚本在 `on_application_quit` 里**重新锁定**鼠标 → 清理被抵消。仓库内无脚本这么做（`Select-String 'on_application_quit'` 只有引擎侧派发点），故当前不构成 bug。
4. 预期：退出后光标可用。
5. 实际：符合。
6. 差异：无。
7. 验证：`loom_render.py:838-869` 代码路径 + `loom_glfw_window` 的 `set_mouse_locked` 实现（InputMixin）。
8. 判定：**DISPROVED**；备注：若将来有脚本在 `on_application_quit` 中加锁，需把清理移到钩子之后（写进 §4-P3 建议）。

---

### 2.S 专项登记：交接总纲 §6.1「VK 播放器 UI 命中坐标系不一致」的实际状态

**结论：代码事实只支持一半；被点名的"根因"（命中坐标系错位导致按钮点不动）在我能构造的最小复现里不成立，需改写为两条独立问题。**

（1）**确认为真（代码事实）**：VK 播放器**从不**把 screen Canvas 尺寸同步到窗口。
```
$ Select-String -Path 'Loom\**\*.py','Loom\*.py' -Pattern 'ui\.resize|\.resize\('
loom_glfw_window.py:186: ui.resize(self.width, self.height)     ← 只有 GL(GFW 窗口) 播放器同步
loom_ui.py:419: c.resize(width, height)                          ← Canvas 自身实现
Loom/vk_player.py / vk_ui.py / vk_renderer.py / scene_driver.py：**零调用**
```
后果（可量化）：`anchor/pivot` 依赖 Canvas 尺寸（`loom_ui.UIElement.screen_rect(parent_rect)`），
`probe3` 实测：在 1008×935 的 Canvas 上，`anchor=(1,1)` 的元素布局到 `y=895..935`，
而 VK 窗口高 800 → **135px 完全落在窗口外**（既看不见也点不到）；全屏 root/遮罩宽 1008 而窗口宽 1280 → 右侧 272px 无遮罩。

（2）**被证伪（命题："canvas≠窗口 ⇒ 命中错位 ⇒ 按钮点不动"）**：
`probe3` 用仓库里真实的吃豆人 UI（`docs/audit/pacman2d_scene.json`，Canvas 1008×935）做最小复现：
```
root       screen_rect=(0.0, 0.0, 1008.0, 935.0)
  通关面板  screen_rect=(255.0, 120.0, 400.0, 220.0)
    重开按钮 screen_rect=(285.0, 230.0, 160.0, 56.0)  binding={'script':'pacman_player','method':'on_restart'}
重开按钮 center: (365.0, 258.0)
hit_test at center -> 重开按钮
dispatch_mouse(center, pressed={1}) -> True ; press-release -> True ; pac.on_restart hits = 1
```
原因：绘制与命中共用**同一空间**——`VkUIEngine.draw_screen_rect(rect)` 直接以元素 `screen_rect`（Canvas 像素）为屏幕像素，
而 `dispatch_mouse` 用窗口光标像素与同一批 `screen_rect` 比较（`loom_ui.py:441-442`）。Canvas 尺寸只参与**布局**
（anchor/pivot/root 尺寸），不参与"缩放映射"。所以坐标**没有**被缩放或偏移，按钮中心点击是命中的。

（3）**因此 §6.1 应有的两条独立条目**：
- 真问题 A（P2，跨轮既有）：VK 缺 Canvas↔窗口尺寸同步 → 只影响 anchored/全屏元素与窗口外裁剪（已量化）。
- 真问题 B（P-03-01/P-03-07，本轮引入）：默认 `mouse_locked=True` + 解锁键双触发 → 玩家**无法把光标移到按钮上**。
  这条比"坐标错位"更符合"面板能显示但点不动"的现场：光标被 `CURSOR_DISABLED` 冻结时，`dispatch_mouse` 收到的位置永远是冻结点。
  （该因果链需要"打包游戏实际 `游戏设置.json` 的 `mouse_lock_allowed/mouse_locked`"才能闭合 → 记入 U-03-03。）

（4）**文档与实现不一致（AUDIT-DOCIMPL，供主审改文档）**：§6.1 写"GL 路径因为编辑器/播放器都会把 canvas 尺寸跟窗口同步"——
实测**编辑器（Qt 宿主）也不调用 `ui.resize`**（`loom_gui.py:304-311`、`:200-204` 只写 `e.width/e.height` 与 viewport），
所以"编辑器会同步 Canvas 尺寸"这句不成立；受影响的只有走 GLFW 的 GL 播放器（`loom_glfw_window.py:186`）。

---

### U-03-01　"打包版通关面板点不动"的真机根因　【P-UNKNOWN】

- 已尝试的探针：`probe2`（绑定链 A/B）、`probe3`（真实 UI 命中 + 真实 `dispatch_mouse` 触发 `on_restart`）、`probe5`（GL/VK 相机对比）、代码路径全枚举（§2.S）。
- 已排除：① 事件派发链（`probe2/3` 证明能触发）；② "canvas≠窗口导致命中错位"（`probe3` 证伪）。
- 还缺什么信息（最多 3 条）：
  1. 打包游戏目录下 `游戏设置.json` 的实际 `mouse_lock_allowed/mouse_locked` 取值（决定"问题 B"是否成立）；
  2. 一次**真鼠标**点击的现场取证：`LOOM_VK_HUD=1` + 在 `dispatch_mouse` 前打印 `(pos, pressed, released)`（只需临时探针）；
  3. 玩家的显示器 DPI 缩放（125%/150% 下 `glfw.get_cursor_pos` 与 `wgpu` `physical_size` 是否同单位）。
- 建议下一步探针：在 `vk_player.py` 的 `draw()` 里加一次性 `print('[uiprobe]', ui_bridge.pos, w, h, driver.mouse_locked)`（**下一轮**、且只读一次性），真鼠标点一次即可闭合。
- 为什么不能现在就定：GUI 长窗口禁止启动（硬约束 3），且打包产物不在仓库内（`player_runtime` 已 gitignore）。

### U-03-02　打包 dist 的 `Loom/scripts/` 是否与包内游戏脚本版本一致　【P-UNKNOWN】

- 已知：`scene_driver.py:418-425` 每次构造都会扫 `<engine dir>/scripts`；`game_player._start_pack` 先 `register_sources(pack scripts)`（`game_player.py:203-204`）→ **后**扫磁盘目录。
- 潜在风险：同名脚本若磁盘版本更旧，会覆盖包内注册；`load_script_dir` 用 `exec_module` 逐次重执行（`scripts.py:146-150`），无版本戳/去重。
- 还缺什么：`Loom/player_runtime/game_player.dist/Loom/scripts/` 的实际文件清单与版本（产物被 `.gitignore` 排除，仓库内不可见）。
- 建议下一步探针：解压 `tools/dist/Loom-0.1.0.beta3.zip` 检查 `Loom/scripts/`，与 `游戏包.lsc` 内脚本哈希对比。

### U-03-03　暂停态 + 锁定光标是否让"通关面板"在真机不可点　【P-UNKNOWN】

- 已知（代码）：暂停期 UI 事件仍派发（`vk_player.py:397` 在 `advance_logic` 之前）；暂停期解锁键失效（`probe3` 实测）；默认 `mouse_locked=True`（`game_settings.MOUSE_LOCK_INITIAL_DEFAULT`）。
- 还缺什么：该游戏 `游戏设置.json` 是否写了 `mouse_lock_allowed=false`（吃豆人仓库内没有这份文件；`probe3` 普查显示仓库根目录与 `Projects/` 均无 `游戏设置.json`）。
- 建议下一步探针：在打包目录读该 JSON（一行 `python -c`），或直接观察启动后光标是否被隐藏。

---

## 3. 统计

| 四象限 | 数量 | 编号 |
|---|---|---|
| **P-PROVED** | **9** | P-03-01 … P-03-09 |
| **P-DISPROVED** | **6** | D-03-01 … D-03-06 |
| **P-UNKNOWN** | **3** | U-03-01、U-03-02、U-03-03 |
| **P-CONTRADICTION** | **0** | — |

- 疑似项 9 条；跳过登记 7 条（理由③ 4 条 / 理由② 2 条 / 理由① 1 条）。
- 分级分布（PROVED）：**P0 × 1**（P-03-01）、**P1 × 3**（P-03-02、P-03-03、P-03-07）、**P2 × 5**（P-03-04/05/06/08/09）、P3 × 0（P3 建议集中在 §4）。
- **[REGRESSION] 标注：9 条**（P-03-01…P-03-09 全部由本轮 diff 引入或由本轮新增逻辑暴露）。
- 修复后新增：**P-03-10**（P-PROVED，见 §6.4）、**P-03-11**（跨批文件，未修，见 §6.4）。

**P-CONTRADICTION = 0 的解释**：本轮 9 个疑似项的两条链**都没有出现"证伪成功且证真成功"**——
它们要么反手在路径枚举阶段就失败（找到会产生疑似行为的具体路径），要么只能用回归测试/代码位置把反手做成功。
我特意把三个最容易出现"两说并存"的位置做了冲突检查，并都落成了单边结论：
① §6.1 的"坐标错位"根因（反手成功=probe3 命中触发，正手失败 → DISPROVED，但配套的"canvas 不同步"事实成立 → 另立 P2）；
② Q7=C 命中语义（反手成功=19 项回归测试全绿 → DISPROVED）；
③ A/B 基线（反手成功=透视表达式逐字一致 → DISPROVED）。
另外，**P-UNKNOWN ≠ 0 且不是"不敢判"**：三条都是"需要仓库外/需要真机/需要 GUI"的硬边界（每条已写明缺什么）。

---

## 4. 修复建议排序（只给方向，不含代码）

> 排序原则：先修"玩家立刻可感知 / 阻断游戏闭环"的，再修"静默错值"，最后修维护性。
> 全部修复必须遵守 B1（Q7=C 命中语义）、B2（Q4=B 场景输入）、B3（相机段播放套用）、B4（相机段不抛）、
> B5/B6（`mouse_wheel`/`mouse_rel` 的"本帧"语义）、B7（声明式绑定必须派发到运行时实例）、
> 以及 GL/VK 必须同改（否则制造新分叉）。**本批（第 2 批）已完成 1~10 的落地，见 §6。**

### P0
1. **P-03-01 解锁键双触发**（`scene_driver.py:970-971` + `scripts.py:641-645,700-704` + `engine.py:935`）
   —— 收敛为单一权威（见该项"修复方向"），并把 `tests\test_vk_camera_align.py §10` 重新跑绿作为验收门。
   不能碰：B8 的两条语义、第三方脚本仍可 `toggle_mouse_locked()`、`_ui_capture_mouse` 优先级。

### P1
2. **P-03-02 场景 fov 被覆盖**（`scene_driver.py:574-578 / 589`）—— 让场景 fov 在"重置"之后生效；
   连带回归 `tests\test_scene_driver_lod.py`（LOD 用 `self.fov`）。不能碰：无 `camera` 键时=60°；`active_camera` 优先。
3. **P-03-03 `ortho_size` 未容错**（`scene_driver.py:579`；同类 `editor.py:958`、`runtime.py:62`）—— 与 B4 对齐；
   建议三处同一个"读相机字段"的窄函数收口，避免又一处分叉。
4. **P-03-07 暂停冻结的连带效应**（`scene_driver.py:691-693`；GL 同源 `engine.py:1277-1284`）—— 解锁键轮询移出逻辑帧；
   暂停分支清 `_pending_mouse_rel`。不能碰：暂停期 UI 事件派发顺序（`vk_player.py:397`）、脚本/物理/动画全冻结语义。

### P2
5. **P-03-05 无 `camera` 键时 `camera_out` 为空**（`sceneio.py:1109`）—— 读侧补齐默认 or 消费端显式重置；
   不能把 `scene_to_dict(camera=None)`（脏检查）拉进改动。
6. **P-03-06 `ortho_size` 合法域**（三处投影 + 入口）—— 与 `clamp_camera_distance` 同款"入口钳制"；
   与 EAI `max(1.0,...)` 下界一致。
7. **P-03-04 字符串布尔**（`sceneio.py:1117` + `scene_driver.py:573`）—— 复用项目既有文本布尔语义；左右两端同改。
8. **P-03-08 `or sc` 兜底**（`loom_ui.py:74`）—— 存在性判断 + 诊断文案分层。
9. **P-03-09 `engine=None` 默认值**（`vk_renderer.py:1029/1054`）—— 必填或显式告警；保持 `draw_all(engine)` 旧签名可用。
10. **回归测试缺口（D-03-02 附带）**：把 `probe2 [F1][F2][F4]`、`probe4 [H1..H4][H7]` 的断言收编为正式回归测试
    （当前**零受跟踪测试**覆盖"声明式 UI 事件派发"这条 P0 修复）→ 已由 `tests\test_beta3_batch2_camera_proj.py` 建覆盖。

### P3（维护性，可与上批合并）
1. `_ACTIVE_ENGINE` 无显式清理/恢复：建议在引擎关闭路径置 None（防跨引擎生命周期的悬空引用）。
2. `loom_render.py:789` 用 `max(1,height)`、else 分支用裸 `self.width/self.height`：同一函数两种除零态度，建议统一（基线既有，非本轮引入）。
3. `loom_render.py:859-863` 清理在 `on_application_quit` 之前：若将来有脚本在该钩子里加锁会被抵消，建议移到钩子之后或加注释约束。
4. `scene_driver.py:970-971` / `engine.py:934-935`：`_poll_mouse_unlock_key()` 被插在文档串**之前**，函数 docstring 已失效（实测 `SceneDriver._update_scripts.__doc__ is None`）。
5. `scene_driver.py:417` `self._request_exit_play = False` 在 `SceneDriver` 内**无任何读取点**（`Select-String` 只命中这一行）→ 与 GL 的 `editor.py:2128` 同名不同用，建议删或补说明。
6. `scene_driver.py:665-678` `set_render_api` 在写入失败时仍 `print` 一条"已保存"格式的日志 → 本批已改为失败语气独立。

### §4.1 动手前需确认的点（真正需要人类拍板的路线分叉）

| 编号 | 分叉 | 选项 | 代价 / 影响 |
|---|---|---|---|
| C1 | "强制解锁键"的权威归属 | **A**：引擎轮询只置"解锁意图"（脚本仍可 toggle，两者幂等收敛） / **B**：引擎轮询吞掉该键、脚本看不到（对"解锁鼠标"动作做一次性掩码） | A 改动小、对第三方脚本最友好；B 语义最干净（引擎独占保留键）但会**改变**"脚本能看到 Tab"的既有行为 —— **人类已裁决 D6=A（引擎独占 + 内置脚本删 Tab 分支），本批按此接线** |
| C2 | `ortho_size` 非法值（≤0/NaN）的处理策略 | **A**：钳制到 `max(1.0, v)`（与 EAI 命令一致，永不失败） / **B**：拒绝加载该场景并明确报错（B2"报错即可"） | 本批按 **A + WARN** 实现（ASSERT：不静默、也不让玩家双击没反应）；若改判 B，需在 `sceneio` 读侧抛错并由加载方兜底 |
| C3 | 场景 `camera.fov` 的契约强度 | **A**：`fov` 属于"播放时强制套用"（B3 现文），VK 必须修 / **B**：`fov` 只是"轨道相机基线"，允许引擎默认覆盖 | 人类已裁决 **D7=A**（fov 归场景相机属性）；本批按 A 落地，A/B 像素基线未跑（见 §6.3 的替代证据） |

---

## 5. 需要人类裁决的封闭问题

**Q1（对应 C1，已裁决 D6=A）** 解锁键冲突修哪个方向？—— **已定 A**：引擎独占该键、内置 first/third_person 删掉自己的 Tab 分支。
第 2 批按此在 VK 驱动暂停分支接 `poll_unlock()`（不重复调用），并委托 `engine` 的唯一实现避免语义漂移。**仅剩一项待确认**：

**Q1'** `scene_driver` 里那份手抄 `_poll_mouse_unlock_key` 是否按"委托 engine 实现 + guard 回退"处理？
- **选 A**（本批已实现）：委托 `engine.GLEngine._poll_mouse_unlock_key(self)`，engine 不可用时回退本文件 `_poll_unlock_local`。
- **选 B**：删掉本文件实现，VK 驱动直接 `import engine` 强依赖（裁剪包会崩）。

**Q2（对应 C2）** 场景里 `ortho_size` 非法（0/负数/NaN）时，播放器应该？
- **选 A**（本批已实现）：钳制到 `max(1.0, v)` 并打 WARN（永不因此打不开游戏）。
- **选 B**：拒绝加载该场景并给出明确错误（符合 B2"报错即可，不得静默错值"）。

**Q3（对应 C3 与 D-03-03 的验证强度）** 场景 `camera.fov` 与 A/B 基线的口径按哪个执行？
- **选 A**（人类已裁决 D7=A，本批已落地）：`fov` 属"播放时强制套用"→ 已修 `scene_driver`/editor；**像素基线仍未跑**，需在有 GPU 的机器执行 `python tests\_tmp\ab_batch.py`（阈值 MAE<=0.0002 不放宽）。
- **选 B**：若复核认为"未跑基线不能算完成"，则本批相关结论降为"待像素复核"，不改变代码。

---

## 6. 修复记录（第 2 批落地，2026-11-08）

> 本节是审计报告的一部分：记录"审计结论 -> 修复动作"的对应关系与实测证据。
> 依据人类裁决 **D7=A**（`ortho/ortho_size/fov` = 场景相机属性：进脏判定、进撤销、播放前后恒等）、
> **D6=A**（引擎独占解锁键）、**Q4=B**（场景输入不做全量防御，但不得静默错值/不得崩）、
> **Q7=C**（多 Canvas 只吞空白）与第 0 批《用户配置目录契约_20261108》。

### 6.1 改动文件 ↔ 缺陷编号

| 文件 | 缺陷 | 改动要点 |
|---|---|---|
| `Loom/scene_driver.py` | P-03-02 | 删掉"读完场景 fov 后无条件重置 60°"的死赋值；fov 改为在重置**之后**按场景段生效（无 camera 段仍 = 60°） |
| `Loom/scene_driver.py` | P-03-03/04/06 | 相机段三个投影字段统一走 `sceneio` 的归一（`norm_fov_deg`/`_b_strict`/`norm_ortho_size`），异常分支出声回落；不再裸 `float()`、不再 `bool('false')` |
| `Loom/sceneio.py` | P-03-03/04/06/05 | 新增**唯一**归一实现 `_b_strict / norm_ortho_size / norm_fov_deg`（+ 常量 `ORTHO_SIZE_DEFAULT/MIN`、`FOV_DEFAULT_DEG`）；写侧与读侧共用同一套（存进去 == 读回来） |
| `Loom/scene_driver.py` | P-03-07 | `advance_logic` 暂停分支内每渲染帧调 `poll_unlock()`（跨批 API）；暂停期 `_pending_mouse_rel/mouse_rel` 清零，恢复首帧不再出巨值 |
| `Loom/scene_driver.py` | P-01-10 同类 | `_poll_mouse_unlock_key` 不再手抄一份，改为**委托** `engine.GLEngine._poll_mouse_unlock_key(self)`（guard 回退 `_poll_unlock_local`）；docstring 移到调用之前 |
| `Loom/loom_ui.py` | P-03-08 | `_fire_binding` 用存在性判断（`is None`）替代 `or sc`；"未实例化"与"缺方法"分开报 |
| `Loom/loom_ui.py` | P-03-09 | `draw_all` 检测宿主缺 `.models/.scripts` 时**出声一次**（`_warn_script_host_once`），不再静默丢事件 |
| `Loom/editor.py` | P-03-03/04/06 + D7=A | `_apply_camera` 走同一归一；`_camera_dict()` 显式写出投影三件套；`_scene_digest()` 纳入 `_camera_proj`（改投影 = 场景已改动）；新增 `set_camera_projection()` + `_CameraProjCommand`（进撤销）；`toggle_play` 快照/还原投影（播放前后恒等）；`_load_scene`（无 camera 段）/`_new_scene` 重置投影并清空 `_scene_cam` |
| `Loom/scene_driver.py` | 01 遗留① | 键位加载改读 `输入配置.default.json`（旧名仅兼容读）+ `game_settings.read_key_bindings()` 用户层；`set_action_binding/rebind_action` **只写用户层**且写失败可判定（`saved` 只在真落盘为 True）；`set_render_api` 路径取 `user_path()`、失败不再打印成功语气 |
| `Loom/tests/test_beta3_batch2_camera_proj.py`（新增） | 全部 | 8 组断言（fov / 归一 / 读写成对 / 暂停解锁与增量 / UI 派发 / 脏判定+撤销+播放恒等 / 旧场景重置 / 键位用户层写入） |

### 6.2 修前 → 修后证据（同一命令，实跑）

```
# P-03-02 场景 fov（修前 probe1 / 修后 probe6）
修前: [A fov] scene=fov90 fov_deg_in=90.0 -> driver.fov_deg=60.0000
修后: [A fov 90.0 -> driver] 90.0 ；[A fov 45.0 -> driver] 45.0 ；[A no camera key -> (60.0, False, 12.0)]

# P-03-03/04/06（修前 probe1/probe2 / 修后 probe6）
修前: [B bad {'ortho_size': 'abc'} ] load RAISED ValueError: could not convert string to float: 'abc'
修前: [B bad {'ortho': 'false'} ] load OK -> ortho=True           # 静默错值
修前: [G {'ortho': True, 'ortho_size': 0}] render_pose RAISED ZeroDivisionError
修后: [B {'ortho_size': 'abc'}] (False, 12.0, True)  [场景] ... 非数值 ('abc') -> 用默认 12
修后: [B {'ortho_size': 0}] (False, 1.0, True)      [场景] ... =0 过小 -> 钳到 1
修后: [B {'ortho_size': -5}] (False, 1.0, True)     [场景] ... =-5 过小 -> 钳到 1
修后: [B {'ortho_size': nan}] (False, 12.0, True)   [场景] ... 非有限数 (nan) -> 用默认 12
修后: [B {'ortho': 'false'}] (False, 12.0, True)    [B {'ortho': 'true'}] (True, 12.0, True)

# P-03-07 暂停态解锁键 / 鼠标增量（修前 probe3 / 修后 probe6 + 新测试）
修前: paused: key_state['Tab']=True get_action=True mouse_locked=True unlock_requested=False
修前: paused 10 frames: pending_mouse_rel=(300.0, 200.0) ; first frame after resume: mouse_rel=(300, 200)
修后: [C paused Tab press -> locked/unlock_requested] (False, True)
修后: [C paused pending/mouse_rel] ((0.0, 0.0), (0, 0)) ; [C resume first-frame mouse_rel] (0, 0)
修后(测试): PASS 暂停态 poll_unlock 返回 True / PASS advance_logic 暂停分支内也能解锁
           PASS 暂停期 pending 不累积（修前 (300,200)）/ PASS 恢复首帧 mouse_rel 不是巨值
           PASS 按住解锁键只翻一次（翻两次 = P-03-01 双触发病灶）

# P-03-08/09（修前 probe2/probe4 / 修后 probe6 + 新测试）
修前: [H7] falsy (len==0) script instance: fire=False on_click hits=0
修前: [UI 事件] 脚本 'sid1' 无方法 'on_click'（真实原因是未实例化，文案误导）
修前: draw_all(ui, 无 models 的绘制门面) -> 静默
修后: [D falsy instance fire/hits] (True, 1)
修后: [UI 事件] 脚本 's9' 的运行时实例尚未创建（惰性实例化未运行）: event='click' ... -> 本次事件丢弃
修后: [UI 事件] 脚本宿主缺少 .models/.scripts: host=_DrawFacade ... （每进程只打印一次）-> [D host warn fired] True

# D7=A 脏判定 / 撤销 / 播放前后恒等（新测试）
PASS 初始不脏 / PASS camera_proj 改完 -> 场景已改动（修前恒为 False）
PASS 撤销 -> 回到改前投影 / PASS 撤销后不再脏 / PASS 重做 -> 又回到 13/75/正交
PASS 播放套用了场景正交 / PASS 停止播放还原编辑态投影
PASS 无 camera 段 -> 投影回默认（修前残留正交）/ PASS 清空 _scene_cam

# 01 遗留① / P-03-10（修前 NameError 被吞 / 修后真读到模板）
修前: (无日志 —— `except Exception: pass` 把 NameError("name 'os' is not defined") 吞掉)
修后: [输入] 键位加载失败 ... 不再出现；PASS actions 含 解锁鼠标 动作 / PASS 解锁鼠标 默认绑定 = Tab
      PASS set_action_binding -> saved=True + path 落在隔离配置目录 / PASS 写盘真的发生
```

### 6.3 验收（本轮定向测试，皆为本机实跑）

```
cd Loom
python tests\test_vk_camera_align.py            -> exit=0  总结果: ALL PASS ✅   (修前 FAIL 10 Tab 经脚本解锁鼠标)
python tests\test_ui_multi_canvas_hit.py       -> exit=0  总结果: ALL PASS       (Q7=C 未被回退)
python tests\test_wheel_backend_semantics.py   -> exit=0  ALL PASS
python tests\test_beta3_batch2_camera_proj.py  -> exit=0  总结果: ALL PASS       (新增，8 组断言)
# 连带回归（不放宽）
python tests\test_sceneio.py                   -> exit=0  ALL PASS ✅
python tests\test_ui.py                       -> exit=0  ALL PASS
python tests\test_render_api.py                -> exit=0  ALL PASS ✅
python tests\test_editor_load_reject_keeps_scene.py -> exit=0 ALL PASS
python tests\test_scene_cycle_reject.py        -> exit=0  ALL PASS
python tests\test_scripts.py                   -> exit=0  ALL PASS ✅
python tests\test_scene_driver_physics_log.py  -> exit=0  ALL PASS
python tests\test_user_config.py               -> exit=0  ALL PASS ✅（第 1 批地基，未被我改坏）
python tests\test_pacman_scripts.py / test_pacman_scene_contract.py / test_unlock_key.py -> exit=0 全 PASS
```

**GPU 像素基线（`ab_batch` / `ab_gl_vk`）：未跑。** 原因：需要真实 GL+VK 设备与完整离屏夹具，且本轮定位是
"透视路径必须逐位不变"——我用两条更强、可复跑的静态+运行证据替代：
① `loom_render.py` 的 else 分支与基线（`git show f53a82a:Loom/loom_render.py`）**参数序列逐字一致**（仅换行）；
② `hasattr(engine.GLEngine,'ortho') is False` 且 `loom_render.py` 全文无 `self.ortho` 赋值 → 未开正交的场景走的就是基线表达式。
**新增的正交分支**则用 `test_beta3_batch2_camera_proj.py` 的矩阵断言兜底（60° vs 90° 的 VP 必须不同、正交 VP 必须有限）。
若主审要求像素级复核，请在具备 GPU 的机器上跑 `python tests/_tmp/ab_batch.py`（阈值 MAE<=0.0002 不放宽）。

### 6.4 修复过程中发现的新问题（登记，未擅自扩大改动）

| 编号 | 位置 | 现象 | 证据 | 结论 |
|---|---|---|---|---|
| **N1（= P-03-10）** | `scene_driver.py`（2026-11-07 键位块，原 445-464） | 该块用 `os.path.join(...)` 但**整个文件没有 `import os`** → `NameError` 被外层 `except Exception: pass` 吞掉 → "VK 播放器读键位配置"这项 2026-11-07 的交付**从未生效**（模板与用户层绑定都读不到，永远用 DEFAULT_ACTIONS） | 修前探针日志：`[输入] 键位加载失败 (NameError("name 'os' is not defined")) -> 用默认键位`（本批修复后才可见，因为我把静默 pass 改成出声）；`Select-String 'import os' Loom/scene_driver.py` 在修前为空 | **P-PROVED [REGRESSION]**，已在本批一并修（补 `import os` + 重写加载路径），新增断言 `PASS actions 含 解锁鼠标 动作 / 解锁鼠标 默认绑定 = Tab` |
| **P-03-11** | `agent_commands.py:1017-1026`（camera_proj） | 仍直接写 `ed.ortho / ed.ortho_size`，绕过新的 `EditorApp.set_camera_projection()`；**脏判定已覆盖**（`_scene_digest` 读引擎状态），但**撤销栈拿不到这一步** | `Select-String 'camera_proj' Loom/agent_commands.py` → 直接赋值；本批文件范围不含 `agent_commands.py` | 未修（跨批文件）。建议该批把两行改为 `ed.set_camera_projection(ortho=..., ortho_size=...)`，即可同时获得脏判定+撤销+归一 |

### 6.4.1 N1（= P-03-10）独立登记：HEAD 已存在的潜伏 P1，由本批顺带修掉

- **性质**：不是本轮 beta3 补丁引入，而是 **2026-11-07"键位可配置"那一轮留下的潜伏 P1**；HEAD 版本里它被
  `except Exception: pass` 完全掩盖，所以前一轮（只读审计）只能靠代码事实推出"这段可能死掉"，无法给运行证据。
- **HEAD 侧独立核对**（主审已复核）：
  ```
  git show HEAD:Loom/scene_driver.py | Select-String 'import os'   -> 只有 "import os as _os"（函数内, 局部名）
  git show HEAD:Loom/scene_driver.py | Select-String 'os\.'         -> 仅键位块 2 处（os.path.join / os.path.dirname）
  ```
  → 模块级 `import os` 缺失 + 块内 `os.path.join` + 整块 `except Exception: pass` = **NameError 被吞，键位加载从未执行**。
- **修前证据**（本批把静默 pass 改为出声后立刻显形）：
  ```
  [输入] 键位加载失败 (NameError("name 'os' is not defined")) -> 用默认键位
  ```
- **修后证据**（`python tests\test_beta3_batch2_camera_proj.py` 第 8 组，全部实跑）：
  ```
  PASS 模板文件存在 (输入配置.default.json)
  PASS actions 含 解锁鼠标 动作
  PASS 解锁鼠标 默认绑定 = Tab
  PASS 驱动 actions 与模板逐条一致 (修前恒为 DEFAULT_ACTIONS)
  PASS 用户层 key_bindings 覆盖生效 (解锁鼠标 -> F10)
  PASS 模板缺失 -> 有告警 (修前整块被 except: pass 吞掉)
        [输入] 键位模板缺失 (__no_such_template__.json / __no_such_legacy__.json 都不在 ...) -> 用默认键位
  PASS 模板缺失 -> 回落 DEFAULT_ACTIONS
  PASS set_action_binding -> saved=True + path 落在隔离配置目录
  PASS 写盘真的发生 / PASS 内存立即生效
  ```
- **防再犯的两条断言**（比原测试更贴近真实失败）：
  1. **模板一致性**：从 `输入配置.default.json` 读出全部动作，逐条与 `SceneDriver().actions` 比对
     ——"没读到"会立刻暴露（修前 100% 不等）；
  2. **失败必须出声**：把 `loom_input._ACTION_FILE/_ACTION_FILE_LEGACY` 临时改成不存在的文件名，
     用 `contextlib.redirect_stdout` 捕获，断言输出里出现"键位模板缺失"且 `actions` 回落 DEFAULT_ACTIONS
     ——防"无声回退"再次发生（为此在 `scene_driver.__init__` 的加载块里补了模板缺失告警）。

### 6.4.2 D6=A 返修（独立验收 B 条）：委托"唯一实现"从口头落到代码

**验收发现（主审实测）**：`SceneDriver` 没有 `script_keys`（用 `key_state`），
`engine.GLEngine._poll_mouse_unlock_key` 的前置检查因此不满足 → `vk_player._unlock_poll_fn`（`vk_player.py:147-164`）
实际解析到的是**驱动自带的那份 `_poll_unlock_local` 语义拷贝**，而不是引擎唯一实现；`scene_driver.py` 里那条
"委托失败"的 `print` 也还活着。行为结果虽然一致，"两套语义"正是 D6=A 要消灭的东西。

**返修（只改 `Loom/scene_driver.py`）**：
1. 新增 `script_keys` property → 返回 `self.key_state`（**同一个 dict**，读写同源，不做拷贝）；
2. 新增 `_warn_unlock_poll_unavailable(what)`（`vk_player` 解析器的前置回调）与 `_warn_once(key,msg)`（每 key 只打一条）；
3. `_poll_mouse_unlock_key` 改为**纯委托**：`from engine import GLEngine` → 取 `GLEngine._poll_mouse_unlock_key` → `impl(self)`；
   只有"无 engine 模块 / 实现缺失"两条兜底，且为**一次性**告警；委托调用内部异常**不再吞**（引擎实现自己按 N3 处理预期内缺失）；
4. **删除 `_poll_unlock_local`** —— 本文件不再保留任何切换语义。

**证据（全部实跑）**：
```
# 解析器真的走主分支（read-only 检查：看 lambda 闭包里捕获的是谁）
$ python -c "...; fn = vk_player._unlock_poll_fn(SceneDriver()); print([...closure qualnames...])"
closure: ['SceneDriver', 'GLEngine._poll_mouse_unlock_key']
primary branch (impl==GLEngine method): True
fallback to local: False
has local copy: False
script_keys dict: True

# 委托命中引擎实现（测试内打桩 engine 的唯一实现，观察 SceneDriver.poll_unlock 是否命中）
PASS script_keys 与 key_state 是同一个 dict (引擎前置)  (1793265422848, 1793265422848)
PASS 写 key_state 后 script_keys 立即可见（同源）
PASS _poll_unlock_local 语义拷贝已删除 (D6=A: 只允许一套实现)
PASS 提供 _warn_unlock_poll_unavailable（vk_player 解析器前置）
PASS poll_unlock 真的调用了 engine.GLEngine._poll_mouse_unlock_key  ['SceneDriver']
PASS 委托后行为不变: 一次翻转解锁  (True, False)
PASS mouse_lock_allowed=False -> 永不锁
PASS 按住不重复翻转  (True, False, False)
```
```
$ python tests\test_vk_camera_align.py          -> exit=0  ALL PASS ✅
$ python tests\test_beta3_batch2_camera_proj.py -> exit=0  ALL PASS（新增第 4b 组 8 条断言）
$ python tests\test_unlock_key.py              -> exit=0  ALL PASS ✅
$ python tests\test_playmode_edges.py          -> exit=0  ALL PASS ✅
```

### 6.4.3 鼠标锁定语义重构（人类裁决 2026-11-08，驱动层 03 号）

**病灶（实测）**：打包吃豆人被默认锁死；按 Tab 光标出现但动不了（只能 Alt+F4）。三条根因：①`mouse_lock_initial` 默认 True；
②`set_ui_capture_mouse` 全仓无人调用；③解锁只翻一个 glfw CURSOR 模式且包在 `except: pass` 里。

**裁决**：①默认**不锁**（allowed/initial 均 False）；②**不做**"检测到 UI 就自动解锁"（引擎只提供显式 API，判断权归游戏开发者）；
③三件能力必须齐：整局是否锁 / 某时刻锁不锁（脚本显式调用）/ 哪个键解锁（动作"解锁鼠标"，默认 Tab、可改、冲突拒绝）。

**本批（驱动层）落地 —— 只改 `Loom/scene_driver.py`**：
1. `__init__`：锁定策略改调 **`runtime.read_mouse_lock_policy()`**（第 3 批提供的单点：未配置 = False/False；initial 受 allowed 门控）；
   runtime 不可用时按同一条规则直读 `game_settings.read_bool(..., False)`；再失败则"不锁"并出声。
   ——**不再**调用 `mouse_lock_allowed()/mouse_lock_initial()`（它们仍带旧的模块默认 True，属第 0 批待改）。
2. `set_mouse_locked(True)` 在 `mouse_lock_allowed=False` 时**无效 + 一次性告警**（每进程一条），只允许解锁方向；
   回调 `on_mouse_lock_changed` 按**有效状态**转发（本层不碰 GLFW，副作用留给后端）。
3. 新增 `set_mouse_lock_allowed(bool)`（能力②）：置 False 时若正锁定 → **立即解锁**（防永久锁死）。
4. `toggle_mouse_locked()` 在 allowed=False 时空操作 + 一次性告警（不让玩家"解锁一个本来就没锁的光标"）。
5. 委托关系不变：`script_keys` → `key_state`，`engine.GLEngine._poll_mouse_unlock_key` 直接吃 driver 的同名属性；
   allowed 语义与 engine/loom_input/runtime 一致（三处都按"未配置 = False"）。

**证据（实跑，`tests/test_beta3_batch2_camera_proj.py` 第 4c 组）**：
```
PASS driver 默认不锁 (allowed=False, locked=False)                    # 修前 True/True
PASS allowed=False -> set_mouse_locked(True) 无效
PASS allowed=False -> 一次性告警（只 1 条，不刷屏）
PASS 回调按"有效状态"转发（仍为 False，后端不会误锁）  [False, False]
PASS set_mouse_lock_allowed(True) -> 可锁
PASS set_mouse_lock_allowed(False) 时立即解锁
PASS allowed=True 时暂停态 Tab 仍可解锁（P-03-07）  (False, True)
PASS 显式 mouse_lock_allowed=true/mouse_locked=true -> 启动即锁（能力①）
PASS 配置改回 false -> 新 driver 不锁
```

**因默认值变化而必须同步的既有测试（契约更新，非产品代码）**：`Loom/tests/test_vk_camera_align.py` 的 §6/§7/§9/§10
四处 fixture 追加 `d.set_mouse_lock_allowed(True)`（这些用例测的是"允许锁"的游戏，原本靠旧默认 True 才成立）。
```
$ python tests\test_vk_camera_align.py          -> exit=0  ALL PASS ✅
$ python tests\test_beta3_batch2_camera_proj.py -> exit=0  ALL PASS
$ python tests\test_render_api.py              -> exit=0  ALL PASS ✅
$ python tests\test_playmode_edges.py          -> exit=0  ALL PASS ✅
$ python tests\test_vk_ui_input.py             -> exit=0  ALL PASS
```

**并行批次导致的既红测试（非本批文件，未修）**：`tests\\test_unlock_key.py`（9 项）与 `tests\\test_scripts.py`（2 项"非特殊场景 Tab 解锁/
退出特殊场景回锁"）——两个文件**均不引用 SceneDriver**（`Select-String 'SceneDriver'` 无命中），失败点是第 1 批 `loom_input`
新增的 `mouse_lock_allowed` 门禁（默认 False）撞上测试桩未声明该属性（`eg2 = GLEngine.__new__` 无 `mouse_lock_allowed`）。
属第 1 批收尾范围。

### 6.5 明确未做（避免越界）

1. `vk_renderer.draw_frame/draw_ui` 的 `engine=None` **默认值本身**未改（文件属 02 批）；我在 `loom_ui.draw_all` 侧加了"宿主缺失必须出声一次"的兜底告警，使该缺陷不再静默。
2. `§6.1 的"命中坐标系不一致"根因未按其修复**（审计已证伪）；仍缺 VK 侧 Canvas↔窗口尺寸同步（P-03 报告 §2.S 的真问题 A，P2），本批未动（属 02 批 UI 管线）。
3. GL 侧 `engine.py` 的同源暂停分支（`_logic_paused` 早退）未改 —— 第 1 批已提供 `poll_unlock()` 并由其接线；本批只在 VK 驱动补调用（按第 1 批"不要重复调用"要求）。
