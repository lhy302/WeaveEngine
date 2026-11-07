# 编辑器与 UI 框架 扫描报告（scan_06_editor_ui）

> 只读审计，2026-11-07。依据 `docs/audit/SCAN_PROTOCOL.md` 与桌面两份方法论（粗筛→双向推演→四象限裁决）。
> 本报告只给结论与修复方向，未修改任何受跟踪源码/测试/文档。

## 0. 范围与方法

### 0.1 文件清单（行数 = `sum(1 for _ in open(...))`）

| 文件 | 行数 | 角色 |
|---|---|---|
| `editor.py` | 2242 | EditorApp：布局/拾取/gizmo/相机/存档迁移/播放边界 |
| `loom_ui.py` | 1661 | Canvas UI 数据模型、布局、命中测试、鼠标/键盘分发、11 种元素 |
| `loom_hud.py` | 336 | GL HUD/文字纹理管线、draw_screen_rect、scissor 栈 |
| `gui.py` | 585 | 历史即时模式 GUI（仅 MinimalEditorView 与 2 个测试使用） |
| `ui/loom_gui.py` | 3968 | 官方 Qt 编辑器（主循环、事件→引擎字段、设置面板、关闭/保存） |
| `ui/minimal_editor_view.py` | 109 | 第二 UI 实现（兜底/只读） |
| `ui/qt_console.py` | 186 | 命令坞 |
| `ui/qt_uitree.py` | 353 | UI 树 dock（阶段5 GUI 编辑器） |
| `ui/grid.py` / `ui/editor_ui.py` / `ui/__init__.py` | 103 / 66 / 10 | 网格几何 / 视图接口契约 / 包说明 |

### 0.2 判定基准（白盒契约，仅引用被审对象自身文档）

- `docs/design/CanvasUI系统契约_20261018.md`（下称「UI 契约」）：§3.1/§3.2 数据模型，§3.3 元素字段，§4.1/§4.3 布局与 resize，§5.1~§5.3 渲染顺序与挂载点，§6.1~§6.4 输入/命中/独占/焦点，§8 序列化，§9 错误模型，§十 资源边界。
- 模块自身 docstring/注释（`loom_ui.py:2-12`、`gui.py:5-26`、`loom_hud.py:177-179`、`editor.py:1722-1724`、`ui/editor_ui.py:10-19`）。
- 现有回归测试（`tests/test_ui.py`、`tests/test_editor_ui.py`、`tests/test_vk_ui_input.py`、`tests/test_scrollbar.py`、`tests/test_gameplay_bugs.py`、`tests/test_grid.py`）。

### 0.3 跑过的命令（全部在本机 python 3.12.10 / moderngl 5.12.0 / PySide6 实测）

1. `git diff HEAD -- Loom/editor.py Loom/loom_ui.py Loom/ui/loom_gui.py`（本轮 diff 全量，仅 3 文件 26 增 6 删）。
2. 定向回归（未跑 `tests/run_all.py`）：`test_ui.py`、`test_editor_ui.py`、`test_vk_ui_input.py`、`test_scrollbar.py`、`test_gameplay_bugs.py`、`test_grid.py` → **全部 ALL PASS**。
3. 无头探针（临时目录 `%TEMP%\loom_audit06\`，`LOOM_NO_SAVE_MIGRATE=1`、`SDL_VIDEODRIVER=dummy`、Qt 用 `QT_QPA_PLATFORM=offscreen`）：
   `probe_a.py`（命中/滚轮/焦点）、`probe_b.py`+`probe_b2.py`（多 Canvas 命中/拖动）、`probe_c.py`（滚轮与点击合帧、wheel 转发）、`probe_d.py`（scissor/摘要/重名）、`probe_gl.py`+`probe_gl2.py`+`probe_gl_scroll2.py`（真实 GL 离屏 scissor）、`probe_qt.py`（真实 `LoomGUI._on_tick`）、`probe_play_ui.py`（播放边界 UI 还原）、`probe_version.py`（HEAD 版 vs 工作区版）、`probe_migrate2.py`（迁移开关）。
4. 收尾自查：`git status --porcelain` 收尾时 1097 条，其中新增的未跟踪条目全部是 `docs/audit/scan_*.md`（并行审计同伴与本报告）；`Get-ChildItem -Recurse | ? LastWriteTime -gt now-45min` 只命中两个文件：`Loom/输入配置.json`（受跟踪，内容与 HEAD 逐字节一致，`git diff` 为空——引擎初始化原样重写）、`Loom/editor_state.json`（未跟踪，test_editor_ui 写入）。**无需 `git checkout` 还原任何受跟踪文件**；新增的唯一文件是本报告（`docs/audit/scan_06_editor_ui.md`）。
5. 未启动长期 GUI；真实 GL 判定用 `moderngl.create_standalone_context()` + `simple_framebuffer` 离屏读回。

---

## 1. 粗筛清单（含跳过项留痕）

标签取自方法论 §4.3（SEM/BND/IFACE/OVERFIT/AUDIT）。本节只给方向，不判定。

| ID | 位置 | 标签 | 初步方向 | 粗筛证据 |
|---|---|---|---|---|
| P-01 | `ui/loom_gui.py:1307-1320` + `editor.py:2120` | IFACE-PRECOND / SEM-SILENT | Qt 主循环在 UI 分发前清空 pressed/released，UI 永远收不到点击 | `e.pressed.clear()` 在 `e._update_camera()` 之前；`_update_camera` 第一行才是 `_dispatch_ui_mouse()` |
| P-02 | `loom_ui.py:417-426` + `loom_ui.py:222-295` | SEM-MISMATCH | 顶层 Canvas 的 root（全屏、enabled）先命中，低层 Canvas 元素永远不可点 | `for c in reversed(self.canvases): hit = c.root.hit_test(...)`；root 是整屏 UIElement |
| P-03 | `editor.py:571-574` vs `loom_ui.py:486-499` | IFACE-PRECOND | 编辑器从不把 wheel 传给 `dispatch_mouse`，ScrollView 滚轮永远无效且被相机吃掉 | 调用只传 3 个位置参数；`dispatch_mouse(pos, pressed, released, wheel=0)` |
| P-04 | `editor.py:1730-1744` vs `1790-1859` | SEM-MISMATCH | 播放边界只快照 models/lights/cameras，UI 树不进快照，退出后脚本改的 HUD 残留 | `_play_snap = {id(m): ... for m in self.models}`，全文无 `_play_ui` |
| P-05 | `ui/loom_gui.py:304-311` vs `loom_glfw_window.py:178-183` | IFACE-UNIT | Qt resize 只改 engine 尺寸，不调 `ui.resize`，右/下锚点 UI 不跟随窗口 | `GLViewport.resizeEvent` 无 `ui.resize`；GLFW 侧有 |
| P-06 | `loom_ui.py:491-499` + `605` | SEM-MISMATCH | 同帧 wheel 被 ScrollView 消费后 `return True`，其后的 left_down/left_up 整段跳过 | 早退在「3) 按下」之前 |
| P-07 | `loom_ui.py:564-575` | IFACE-UNIT | 拖动时用「鼠标命中的 Canvas」尺寸算 `screen_rect`，不是元素所属 Canvas | `sr = self._dragging_elem.screen_rect((0,0,hit_canvas.width,...))` |
| P-08 | `ui/qt_uitree.py:232-239` | AUDIT-ASYMMETRY | 刷新摘要不含 visible/enabled，树上的 √/× 与 (禁用) 永久陈旧 | `_compute_digest` 只拼 ctype/name/rect/anchor/pivot |
| P-09 | `ui/loom_gui.py:996-1002` | SEM-MISMATCH | Qt 编辑器只在播放态画 Canvas UI，编辑态无实时预览 | `if ctl.is_playing: ... draw_all ... return` |
| P-10 | `loom_ui.py:259-295` | AUDIT-DOCIMPL | docstring 称禁用元素「整个子树跳过」，实现只跳过自身 | 子元素先测，`enabled` 只影响自身返回 |
| P-11 | `loom_hud.py:178-195` | BND-OFFBYONE | 负坐标裁剪区只钳 x/y 不改 w/h，右/下边界外扩 | `cur=(max(0,x), max(0,y), max(0,w), max(0,h))` |
| P-12 | `gui.py:487-495` + `gui.py:9` | AUDIT-DOCIMPL | 文档称嵌套 scissor「求交」，实现直接替换 | `self._scissor = tuple(rect)` |
| P-13 | `loom_ui.py:936-952` | SEM-SILENT | 贴图缺失契约要求「占位+警告」，实现只占位 | `except Exception: self._tex = None`，无 print |
| P-14 | `loom_ui.py:1346` vs UI 契约 §十 | AUDIT-DOCIMPL | max_length 默认 200，契约写 256 | `max_length=200` |
| P-15 | `loom_ui.py:272-287` | AUDIT-DEADCODE | ScrollView 命中分支两次 `_point_in_rect(pos, sr)` 恒真 | 进入分支前已保证 pos∈sr |
| P-16 | `loom_ui.py:703-717` + `loom_hud.py:108-154` | BND-RESOURCE | scissor 是否只裁文字不裁矩形（可疑：`enable_only` 会关 scissor） | `draw_screen_rect` 用 `scope(enable_only=BLEND)` |
| P-17 | `loom_ui.py:532-543` | SEM-MISMATCH | Dropdown 展开时任何左键都被吞掉（含别的按钮） | `handle_expanded_click` 恒 `return True` |
| P-18 | `loom_ui.py:638-648` + `1288-1307` | SEM-MISMATCH | 内层 ScrollView 不能滚时滚轮不冒泡给外层 | `_hit_scroll_view` 只返回最近一层 |
| P-19 | `loom_ui.py:545-551` | SEM-MISMATCH | 点击 Dropdown 列表走 2.5 早退，焦点不失焦 | 2.5 在 2.6 前 `return True` |
| P-20 | `ui/loom_gui.py:967-975` + `editor.py:2204` | IFACE-PRECOND | Qt 的 `focus_id` 恒 None，输入框聚焦时相机 WASD 判断失效 | `'focus_id': None` 写死 |
| P-21 | `ui/qt_uitree.py:284-285` | AUDIT-ASYMMETRY | 树以 name 作唯一键，同名元素互相覆盖 | `('elem', canvas_idx, child.name)`；`loom_ui` 明确允许重名（`find_all`） |
| P-22 | `ui/loom_gui.py:1307` | BND-CONCURRENCY | 同一 clear 是否也打断 3D 拾取（`editor.py:616`）取决于 paintGL 与 timer 顺序 | `_on_tick` 清空；`_update_gizmo` 在 `render()` 里读同一字段 |
| R-01 | `editor.py:161-165`（diff） | — | 新增 `LOOM_NO_SAVE_MIGRATE` 开关 | diff hunk |
| R-02 | `editor.py:927-929`（diff） | — | 场景恢复钳制 camera_distance | diff hunk |
| R-03 | `loom_ui.py:597-603`（diff） | — | 原 `a.b = X if cond else Y` 的 AttributeError 修复 | diff hunk |
| R-04 | `ui/loom_gui.py:3364-3382`（diff） | — | render_api 下拉新增 auto | diff hunk |

### 1.1 跳过登记表（四类允许理由之一）

| ID | 位置 | 跳过理由（类型） | 具体出处 |
|---|---|---|---|
| SKIP-01 | `loom_ui.py:129-164` rect/anchor/pivot 钳制 | 白盒契约明确声明 | UI 契约 §九「rect 宽/高为负 → 钳制到 0；anchor/pivot 越界 → 钳制到 [0,1]」 |
| SKIP-02 | `loom_ui.py:267-269` 不可见元素整树跳过 | 已有回归测试覆盖 | `tests/_tmp/verify_ui_hit_test.py:30-35`「不可见元素及子树跳过」 |
| SKIP-03 | `loom_ui.py:417-421` world Canvas 不参与命中 | 白盒契约明确声明 | UI 契约 §6.2 与代码注释「world Canvas 命中留到阶段4」 |
| SKIP-04 | `loom_ui.py:1007-1027` 按钮「按下+松开同元素才触发」 | 已有回归测试覆盖 | `tests/_tmp/verify_ui_button_slider_toggle.py:35-37`（移出再松开不触发）；本轮 `test_ui.py` 复跑 PASS |
| SKIP-05 | `ui/grid.py:53-103` 网格几何（淡出/吸附/范围） | 已有回归测试覆盖 | 本轮 `tests/test_grid.py` 全 PASS（含极远 eye、pitch ±1.2） |
| SKIP-06 | `ui/qt_console.py:39-56` `parse_line` | 语言规范保证 | `str.split()`/`split('=', 1)` 不会抛异常；空输入显式返回 `('', {})` |
| SKIP-07 | `loom_hud.py:75-85` 纹理转置/翻转 | 已有回归测试覆盖 + 本轮离屏实测 | `test_vk_ui_input`/AB 探针沿用同源实现；本轮 `probe_gl_scroll2` 读回无上下翻转 |
| SKIP-08 | `ui/loom_gui.py:1869-1887` `_wait_until` 混合等待 | 已有回归测试覆盖 | `tests/test_frame_pacing.py:77-80` 直接覆盖该函数；本轮未改动 |

---

## 2. 逐项裁决（8 段式双向链）

> 每条都先反手（证伪）后正手（证真）。「路径枚举」若列出全部控制流路径则该链有效。

### P-01｜[P-PROVED / P1] Qt 编辑器在 UI 分发前清空 pressed/released，Canvas UI 输入整体失效

1. **位置**：`ui/loom_gui.py:1307-1308`（清空）、`ui/loom_gui.py:1320`（`e._update_camera()`）、`editor.py:2120`（唯一 UI 分发点）、`editor.py:571-574`（读 `self.pressed/self.released`）、`loom_ui.py:488-489`（`1 in pressed`）。
2. **契约/预期**：`editor.py:558-563` 明确写「两条路径（pygame 主循环与 Qt loom_gui）都走本方法，所以这里是唯一的插入点」；UI 契约 §6.1/§6.3 要求 UI 先做命中/分发并把事件独占。故 Qt 路径下 `_dispatch_ui_mouse()` 必须看到本帧新按下/松开的键码。
3. **路径枚举**（`_update_camera` 的入口到分发）：
   - 路径 A：`_on_tick`（Qt 定时器，`loom_gui.py:927` 唯一连接）→ 1307/1308 清空 → 1320 `_update_camera()` → 2120 `_dispatch_ui_mouse()` → 571 读空集合。**无其他调用点**（`grep -rn "_update_camera("` 全仓结果：`ui/loom_gui.py:1320` 与 tests 直调；`grep -rn "_dispatch_ui_mouse("` 只有 `editor.py:2120`）。
   - 路径 B：`GLViewport.mousePressEvent`（`loom_gui.py:327-341`）只写 `e.pressed`，不调用分发。
   - 路径 C：`RemoteViewport` 同构（`loom_gui.py:662-673`），同样只写字段。
   - 无第四路径（无信号/无 timer 二次分发）。
4. **实际行为**：每拍固定执行「先 `pressed.clear()`/`released.clear()`，再 `_update_camera()`」，因此 `dispatch_mouse` 收到的始终是 `set(), set()`。
5. **差异**：预期 UI 收到本帧点击；实际 UI 永远收到空事件集 ⇒ `dispatch_mouse` 的 left_down/left_up 段（`loom_ui.py:488-605`）永不执行，`_focused` 永不建立。
6. **触发条件**：任何通过官方 Qt 编辑器（默认入口 `run_loom_gui`）在编辑态或播放态点击 Canvas UI 元素；100% 复现。
7. **验证**：
   ```
   # probe_qt.py（真实 LoomGUI._on_tick + 真实 EditorApp._dispatch_ui_mouse）
   tick 前 engine.pressed = {1}
   tick 中 _update_camera 看到的 (pressed, released, wheel) = (set(), set(), 3.0)
   清空后 dispatch_mouse: ui_consumed=False 按钮点击次数=0
   不清空时:            ui_consumed=True  按钮点击次数=1
   ```
8. **影响与等级**：官方编辑器里 11 种 Canvas 元素的鼠标交互（Button/Slider/Toggle/Dropdown/InputField）与键盘输入（InputField 需先获焦）全部不可用；只有纯 hover 效果可能生效（`update_hover_only` 仍被 `_dispatch_ui_mouse` 调用）。**P1**。修复方向：把「清空瞬态」移到 `_update_camera()`（或 UI 分发）之后，或让 Qt 事件直接喂 `UIInputBridge`（`vk_ui.py:707` 已有可复用实现）。

### P-02｜[P-PROVED / P1] 顶层 Canvas 的 root 全屏拦截，低层 Canvas 的元素永远无法命中

1. **位置**：`loom_ui.py:417-426`（`UIManager.hit_test` 逆序取第一个非 None）、`loom_ui.py:222-237`（root 矩形 = 整屏）、`loom_ui.py:289-295`（子元素都没中则返回自身）。
2. **契约/预期**：UI 契约 §3.2「screen Canvas 数量任意」+ §5.1「Canvas 按 z_order 升序绘制」⇒ 多 Canvas 是受支持形态，低层 Canvas 的可见元素应可交互；§6.2「元素 visible 且 enabled 且点在屏幕矩形内 → 命中」。
3. **路径枚举**：
   - 路径 1：低层 Canvas 元素在点内 → 但 `reversed(canvases)` 先测高层 Canvas；高层 root 为 `(0,0,W,H)`、`enabled=True`、无子元素命中 → `hit_test` 返回 root（`loom_ui.py:295`），循环 `break`。低层元素不参与。
   - 路径 2：高层 Canvas 只覆盖部分屏幕且点在其外 → 返回 None → 继续测低层（可命中）。
   - 路径 3：高层 root 被设 `visible=False`/去掉 → 低层可命中。
   - 路径 4：点不在任何 Canvas 内 → 无命中。
   - 无其他分支（root 无子元素时必走 295）。
4. **实际行为**：只要存在 ≥2 个 screen Canvas 且高层 root 未隐藏，低层 Canvas 的任何子元素都不可命中；点击被交给 3D（`consumed=False`，因为 root.`on_mouse_down` 返回 False）。
5. **差异**：低层 Canvas 元素「可见、enabled、点在矩形内」却不命中，与 §3.2/§5.1 的多 Canvas 支持冲突。
6. **触发条件**：≥2 个 screen Canvas（任意 z_order 顺序、两者尺寸可相同）。
7. **验证**：
   ```
   # probe_b.py
   hit_test(50,20) = (z_order=10, 'root')
   dispatch consumed(press) = False ; dispatch consumed(release) = False ; clicks= {}
   high.root.visible=False -> hit = 'lowbtn'
   press/release after hiding top root -> clicks= (True, True, {'n': 1})
   ```
8. **影响与等级**：多 Canvas 场景（HUD 层 + 菜单层是典型用法）下低层 UI 完全不可点击；且点击穿透到 3D 会误选中物体。**P1**。修复方向：`hit_test` 跳过 Canvas 根自身（root 只作容器），或在 root 命中时继续下探其它 Canvas。**是否需要 root 吞空白点击需人类裁决（Q1）**。

### P-03｜[P-PROVED / P1] 编辑器不转发 wheel，ScrollView 滚轮失效且被相机缩放抢走

1. **位置**：`editor.py:571-574`（调用缺 wheel）、`loom_ui.py:486-499`（wheel 参数与 ScrollView 转发）、`loom_ui.py:1298-1307`（`on_mouse_wheel`）、`editor.py:2160-2164`（滚轮缩放相机）。
2. **契约/预期**：UI 契约 §6.3「先做 UI 命中测试；命中任何 UI 元素 → 该事件不传给 3D 世界」；ScrollView 的 `on_mouse_wheel` 是阶段3 交付项（契约 §7 阶段3 第10条）。
3. **路径枚举**：
   - 路径 1：编辑器路径 `_dispatch_ui_mouse` → `dispatch_mouse(pos, pressed, released)`（wheel 取默认 0）→ `if wheel:`（492）为假 → 永不调用 `_hit_scroll_view`/`on_mouse_wheel`。
   - 路径 2：Vk 播放器路径 `vk_ui.UIInputBridge.begin_frame`（`vk_ui.py:764`）显式传 wheel → 可用。
   - 路径 3：测试/脚本直调 `dispatch_mouse(..., wheel=1)` → 可用（`tests/_tmp/smoke_ui_step3_scroll.py`）。
   - 只有路径 1 缺参数，其余两条都传。
4. **实际行为**：Qt 编辑器里滚轮永远只走 `editor.py:2160` 的相机缩放；ScrollView 的 `scroll_pos` 不变，`_ui_lock` 仍为 False。
5. **差异**：命中 ScrollView 时事件本应被 UI 消费，实际被 3D 相机消费（与 §6.3 相反）。
6. **触发条件**：编辑态/播放态把鼠标放在 ScrollView 上滚动滚轮。
7. **验证**：
   ```
   # probe_c.py
   mouse_wheel= -3  scroll_pos (-0.0,-30.0) -> (-0.0,-30.0)   ui_consumed= False
   ```
   （对照：`probe_c.py C1` 直调 `dispatch_mouse((10,10), {1}, set(), wheel=-1)` 时 `scroll_pos` 从 (0,0) 变成 (0,-30) ⇒ `dispatch_mouse` 本身支持滚轮，缺的是编辑器转发。）
8. **影响与等级**：Canvas ScrollView 在官方编辑器内是「看得见、滚不动、还会缩放相机」。**P1**。修复方向：`_dispatch_ui_mouse` 把 `self.mouse_wheel` 传入并在消费后不再缩放相机（`mouse_wheel` 的清零时机必须与 UI 分发同拍）。

### P-04｜[P-PROVED / P2] 播放模式不还原 UI 树：停止播放后 HUD 改动残留且场景被标脏

1. **位置**：`editor.py:1730-1744`（进入播放只快照 models/lights/cameras）、`editor.py:1780-1859`（退出还原同样只覆盖三者）、`editor.py:837-856`（`_scene_digest` 走 `sceneio.scene_to_dict`，含 `ui` 段）。
2. **契约/预期**：`editor.py:1723-1724`「退出：丢弃播放期所有运行时改动，还原编辑态场景（所见即所得）」；UI 契约 §8「场景文件新增 ui 段」⇒ UI 是场景内容的一部分。
3. **路径枚举**：
   - 路径 1：进入播放 → 脚本/玩家改 `engine.ui` 下元素字段（Text.text、Button 颜色、新增/删除元素）→ 退出：只对 models/lights/cameras 做 snapshot 还原，`self.ui` 未被触碰（全文 grep 无 `_play_ui`/`ui.*snapshot`）→ 改动保留。
   - 路径 2：播放期不改 UI → 无差异。
   - 路径 3：播放期改 UI 后手动 Undo → `toggle_play` 进入时已 `undo.clear()`（1733），不可撤销。
   - 无第四路径（`_new_scene` 会清 UI，但那是新建而非停止播放）。
4. **实际行为**：停止播放后 UI 保持运行时值；`scene_is_dirty()` 变为 True（digest 含 ui 段）。
5. **差异**：预期「丢弃播放期改动」，实际 UI 改动跨播放边界泄漏，且用户什么都没编辑却被提示「未保存」。
6. **触发条件**：播放期任何脚本/玩家对 `engine.ui` 的写操作（分数、血条、弹窗是常规用法）。
7. **验证**：
   ```
   # probe_play_ui.py（真实 EditorApp + 独立 GL 上下文）
   baseline: text='0' dirty=False
   during play: text='999' dirty=True
   after stop : text='999' dirty=True playing=False
   => UI 是否被还原: False
   ```
8. **影响与等级**：播放 → 停止 → 保存会把运行时 HUD 写进场景；下次进入游戏从脏状态开始；「所见即所得」承诺破坏。**P2**。修复方向：进入播放时对 `ui` 做与 `sceneio` 同构的快照，退出时重建（并把该快照排除在 undo 之外）。

### P-05｜[P-PROVED / P2] Qt 编辑器窗口 resize 不同步 Canvas 尺寸（右/下锚点 UI 不跟随）

1. **位置**：`ui/loom_gui.py:304-311`（`GLViewport.resizeEvent`）、`loom_ui.py:356-360`（`Canvas.resize`）、`loom_ui.py:411-415`（`UIManager.resize`）、对照 `loom_glfw_window.py:171-183`（GLFW 侧有 `ui.resize`）。
2. **契约/预期**：UI 契约 §4.3「Canvas width/height 变化时（窗口 resize），所有元素按新父矩形重算」+ §3.2「screen 模式 width/height 默认跟随窗口」。
3. **路径枚举**：
   - 路径 1：GLFW 窗口 resize → `_on_resize` → `ui.resize(w,h)`（`loom_glfw_window.py:181`）→ 生效。
   - 路径 2：Qt 编辑器 resize → `GLViewport.resizeEvent` 只设置 `e.width/e.height`、`ctx.viewport`、`gui_dirty` → **不调用** `e.ui.resize`。全仓 grep `ui.resize` 只有 `loom_glfw_window.py:181` 一处生产调用。
   - 路径 3：`UIManager.draw_all`/`render` 也不回写 canvas 尺寸（`loom_ui.py:683-687` 直接用 `c.width/height`）。
   - 无第四路径。
4. **实际行为**：Qt 编辑器内 Canvas 保持创建/加载时的宽高（如 1280×800），窗口放大后右侧/底部锚点元素停在旧边界。
5. **差异**：`parent_rect` 仍是旧 Canvas 尺寸，与 §4.3 不符；且与 GLFW 播放器行为不一致（同一场景两后端布局不同）。
6. **触发条件**：Qt 编辑器拉伸/最大化窗口后，查看 anchor 不是 (0,0) 的 Canvas 元素。
7. **验证**：全仓 grep `ui\.resize` 的生产调用只有 `loom_glfw_window.py:181`（其余命中在 tests/_tmp）；`ui/loom_gui.py:304-311` 全文无 `ui` 写入；`loom_ui.py:411-415` 的 `UIManager.resize` 无 Qt 侧调用者。
8. **影响与等级**：右/下锚定的 HUD/菜单在窗口变化后错位；编辑器与播放器布局不一致。**P2**。修复方向：`resizeEvent` 里调用 `e.ui.resize(w,h)`（并注意 dpr 物理像素）。

### P-06｜[P-PROVED / P2] 同帧「滚轮 + 左键」时点击被吞（`dispatch_mouse` 早退）

1. **位置**：`loom_ui.py:491-499`（wheel 命中即 `return True`）、`loom_ui.py:530-605`（其后的 hover/按下/松开全被跳过）。
2. **契约/预期**：`dispatch_mouse` docstring「每帧分发鼠标事件…返回 True = 本帧点击被 UI 消费」；UI 契约 §6.3 只要求把命中的事件独占，不要求丢弃同帧其它事件。
3. **路径枚举**：
   - 路径 1：`wheel` 真且命中可滚 ScrollView → `return True`，本帧 left_down/left_up 不处理（`_last_pointer_down` 也不记录）。
   - 路径 2：`wheel` 真但未命中 ScrollView（或不可滚）→ 继续正常流程。
   - 路径 3：`wheel` 为 0 → 正常流程。
   - 所有路径已枚举（wheel 分支只有这两个出口）。
4. **实际行为**：一帧内既有滚轮又有按下时，按下被丢弃；下一帧 pressed 已被调用方清空，按钮永远不会收到 click。
5. **差异**：同帧两个事件只消费一个，另一个丢失且无补偿。
6. **触发条件**：`pressed` 与 `wheel` 同帧到达（Vk 桥每帧聚合 wheel+按键，可发生；GL/Qt 路径当前因 P-03 传 0，被掩盖）。
7. **验证**：
   ```
   # probe_c.py
   consumed= True  scroll_pos= (0,-30)  pressed_elem= None
   松开帧: clicked= 0      => 点击丢失
   ```
8. **影响与等级**：滚轮滚动时快速点击会「点不动」，且无日志。**P2**。修复方向：wheel 消费后不要 return，继续处理按下/松开（用独立 consumed 变量并合并返回值）。

### P-07｜[P-PROVED / P2] 拖动时用「鼠标命中的 Canvas」尺寸计算元素 screen_rect

1. **位置**：`loom_ui.py:564-575`（`hit_canvas` 来自 501-512 的 hover 命中，而 `_dragging_elem` 可能属于另一个 Canvas）。
2. **契约/预期**：`loom_ui.py:1125-1131` `drag_to(pos, screen_rect)` 的 screen_rect 必须是「该元素在自己的 Canvas 上的屏幕矩形」（`screen_rect` 的语义见 `loom_ui.py:222-237`，依赖父容器尺寸）。
3. **路径枚举**：
   - 路径 1：单 Canvas（或拖动元素所在 Canvas 恰为 hover 命中的 Canvas）→ 尺寸相同，无差异。
   - 路径 2：多 Canvas 且尺寸不同，指针从元素 Canvas 拖到另一个（更小/更大）Canvas 的范围内 → `hit_canvas` 变成后者，`screen_rect` 用错父矩形。
   - 路径 3：指针移出所有 Canvas → `hit_canvas=None` → 整段 drag 不执行（拖动冻结），也非契约行为。
   - 无第四路径。
4. **实际行为**：竖直 Slider 的 `_pos_to_value` 用错 y 基准，值按错误比例换算（水平 Slider 因只用 x 影响较小，anchor 非 0 时更明显）。
5. **差异**：预期按 A Canvas（800×600）算出 t>1 → 值 1.0；实际按 B Canvas（400×300）算出 t=0.5 → 值保持 0.5。
6. **触发条件**：≥2 个尺寸不同的 screen Canvas，且其中一个元素在拖动中跨入另一个 Canvas 的区域。
7. **验证**：
   ```
   # probe_b2.py
   slider screen_rect A= (0,250,200,100)   B= (0,100,200,100)
   press at (100,300) -> pressed= v dragging= v value= 0.5
   drag to (100,150) -> hit_canvas z=10 value= 0.5   # 按 A 应为 1.0
   ```
8. **影响与等级**：多 Canvas 下滑条/拖动元素数值跳变或不动。**P2**。修复方向：`_dragging_elem` 记录所属 Canvas（按下时解析一次），拖动时用该 Canvas 尺寸。

### P-08｜[P-PROVED / P2] UI 树刷新摘要漏 visible/enabled，树显示永久陈旧

1. **位置**：`ui/qt_uitree.py:220-239`（`refresh_if_changed` → `_compute_digest`）、`ui/qt_uitree.py:276-289`（显示 `√/×`、`(禁用)`）。
2. **契约/预期**：`ui/qt_uitree.py:7-13`「树形展示所有 Canvas 与 UI 元素（可折叠、可选中）」+「每次操作后命令日志留下等价 EAI 命令」⇒ 树是编辑结果的唯一可视反馈，必须随元素状态刷新。
3. **路径枚举**：
   - 路径 1：`ui_set visible=false` / `enabled=false` → 摘要不含这两个字段 → `dig = _last_digest` → 不刷新 → 树仍显示 `√`。
   - 路径 2：改 rect/anchor/pivot/name → 摘要变化 → 刷新（正常）。
   - 路径 3：增删元素 → walk 序列变化 → 刷新（正常）。
   - 路径 4：改 text/颜色/scroll_pos 等 → 摘要不含 → 不刷新（但树也不显示这些字段，影响小）。
   - 已枚举全部字段组合。
4. **实际行为**：`visible`/`enabled` 是树明确展示的两项，却不在摘要里。
5. **差异**：UI 状态变化后树不更新（除非恰好同时改了 rect）。
6. **触发条件**：EAI/GUI 修改 `visible` 或 `enabled`。
7. **验证**：
   ```
   # probe_d.py
   visible=False 后摘要变化: False   enabled=False 后摘要变化: False
   ```
8. **影响与等级**：用户看到「√」但元素实际隐藏；与检查器/视口状态矛盾，属于审计类不一致。**P2**（编辑体验/误导）。修复方向：摘要加入 `visible/enabled/z_order`（或直接序列化 `sceneio` 的 ui 段做 digest）。

### P-09｜[P-PROVED / P2] Qt 编辑器编辑态不绘制 Canvas UI（无实时预览），与 MinimalEditorView 不一致

1. **位置**：`ui/loom_gui.py:996-1002`（只有 `is_playing` 分支调用 `ctl.ui.draw_all`，随后 `return`）；对照 `ui/minimal_editor_view.py:96-97`（无条件 `ctl.ui.draw_all(ctl)`）。
2. **契约/预期**：UI 契约 §5.3「在 `_draw_hud()` 之后追加 `_draw_canvas_ui()`」并未限定播放态；§7 阶段5 要求「GUI 编辑器面板（在属性面板外挂 UI 树编辑器）」——编辑 UI 时必须能看到结果。
3. **路径枚举**：
   - 路径 1：Qt 编辑态（`is_playing=False`）→ 画网格/选中框/gizmo/图标后结束，不画 UI。
   - 路径 2：Qt 播放态 → `ctl.ui.draw_all`。
   - 路径 3：MinimalEditorView → 任何时刻都画 UI。
   - 路径 4：独立播放器（GLEngine/Vk）→ 各自 `draw_all`。
4. **实际行为**：官方编辑器里改完 UI 只能靠「播放」确认，且播放会走 P-01/P-04 的问题路径。
5. **差异**：两个 IEditorView 实现行为不一致；UI 契约未要求只在播放态绘制。
6. **触发条件**：Qt 编辑态。
7. **验证**：代码路径枚举 + 全仓 `draw_all` 调用点：`loom_render.py:798`（GL 引擎渲染末尾，无条件）、`ui/loom_gui.py:1001`（仅播放分支）、`ui/minimal_editor_view.py:97`（无条件）、`vk_renderer.py:881` / `vk_ui.py:309`（Vk 侧，无条件）。
8. **影响与等级**：UI 编辑功能不可视化验证（与 `qt_uitree` 的编辑功能不闭环）。**P2**。修复方向：编辑态也调用 `draw_all`（可加「显示 UI」开关），保证与播放态同一份元素树。

### P-10｜[P-PROVED / P3] 禁用父元素不屏蔽子树，与 `hit_test` docstring 矛盾

1. **位置**：`loom_ui.py:259-295`（docstring 263-265 与实现 288-295）。
2. **契约/预期**：docstring「自身不可见/禁用 -> 整个子树跳过」；UI 契约 §6.2 仅规定「元素 visible 且 enabled 才命中」，未规定子树语义。
3. **路径枚举**：
   - 路径 1：父 `enabled=False`、子 `enabled=True`、点在子内 → 先递归子元素 → 子返回自身（命中）。
   - 路径 2：父 `enabled=False`、点在父空白 → 子未命中 → `if not self.enabled: return None` → 不命中。
   - 路径 3：父 `visible=False` → 287 行前直接 None → 整树跳过（与 docstring 一致）。
   - 路径 4：父与子都 enabled → 正常。
4. **实际行为**：禁用父元素只禁用「自身空白区」，不禁用子树。
5. **差异**：docstring 与实现不一致（AUDIT-DOCIMPL）；两种语义都能自圆其说，属设计意图问题。
6. **触发条件**：给容器（Panel/ScrollView/GridLayout）设 `enabled=false` 期望整块置灰不可点。
7. **验证**：
   ```
   # probe_a.py A1
   hit = ('b','button')      # 父 Panel(enabled=False) 的按钮仍被命中
   ```
8. **影响与等级**：禁用容器无法阻断子树交互。**P3**（当 UI 契约未定义，需人类裁决 Q1 的配套问题；也可直接修 docstring 以对齐实现）。

### P-11｜[P-PROVED / P3] `loom_hud.push_scissor` 负坐标只钳 x/y 不改 w/h

1. **位置**：`loom_hud.py:178-195`（`cur=(max(0,x), max(0,y), max(0,w), max(0,h))`）。
2. **契约/预期**：`loom_hud.py:179`「推入一个屏幕矩形裁剪区…嵌套时求交」——裁剪区必须等价于「可见部分」，钳制 x 时应同步缩短 w（否则右边界右移）。
3. **路径枚举**：
   - 路径 1：rect 各分量 ≥0 → 与直接使用等价。
   - 路径 2：`x<0`（元素部分移出屏幕左缘）→ `cur=(0,y,w,h)`，右边界从 `x+w` 变成 `w`，多露出一段。
   - 路径 3：`y<0` → 同理下边界下移。
   - 路径 4：已有 `_ui_scissor_cur`（嵌套）→ 走 186-192 求交分支，不受此影响（但若外层本身已被错误钳制，误差会传递）。
4. **实际行为**：`(-50,10,200,100)` → `(0,10,200,100)`；正确应为 `(0,10,150,100)`。
5. **差异**：裁剪区宽度外扩 50px。
6. **触发条件**：ScrollView（或任意 push_scissor 调用）的屏幕矩形出现负 x/y（元素拖出屏幕、anchor/pivot 造成负偏移）。
7. **验证**：
   ```
   # probe_d.py D1
   push((-50,10,200,100)) -> cur = (0,10,200,100)     # 期望 (0,10,150,100)
   嵌套 (50,60,300,200) ∩ (100,100,400,400) = (100,100,250,160)  # 求交正确
   ```
8. **影响与等级**：部分移出屏幕的 ScrollView 会漏画/多画边缘内容（裁剪不足导致内容溢出到可视区外）。**P3**（需特定布局，视觉瑕疵）。修复方向：钳制时用 `min(x+w, ...)-max(x,0)` 计算宽高。

### P-12｜[P-PROVED / P3] `gui.py` 的 scissor 栈文档声称「嵌套求交」，实现为直接替换

1. **位置**：`gui.py:9-10`（模块 docstring）、`gui.py:487-495`（`push_scissor`/`pop_scissor`）；测试 `tests/test_scrollbar.py:274-284` 按「替换」断言。
2. **契约/预期**：模块 docstring 自称「提供经过实战验证的 scissor 栈实现（push_scissor/pop_scissor，含嵌套求交）」。
3. **路径枚举**：
   - 路径 1：单层 push → 生效。
   - 路径 2：嵌套 push（外层为面板 `window_begin` 的裁剪区，内层为滚动内容区）→ 实现直接覆盖，内层裁剪区不收缩到外层内。
   - 路径 3：pop → 恢复栈顶。
   - 无其他分支。
4. **实际行为**：`gui.py:489-490` 只赋值 `tuple(rect)`，不与 `self._scissor` 求交。
5. **差异**：内层裁剪区可越出外层面板边界，绘制内容可能画到相邻面板上。
6. **触发条件**：同帧先 `window_begin` 再 `push_scissor` 且内层矩形超出外层。
7. **验证**：
   ```
   # probe_d.py D2
   嵌套 push 后 _scissor = (200,2,100,32)    # 与外层 (0,2,100,32) 完全不相交，未被求交
   # 对照 tests/test_scrollbar.py:274-284「嵌套 push (5,5,50,20)」按替换语义通过
   ```
8. **影响与等级**：`gui.py` 已无生产调用（`ui/minimal_editor_view.py` 只画一条状态栏，且被 P-09 的 Canvas UI 覆盖），影响面小；但「文档承诺 ≠ 实现 ≠ 测试断言」会让后续复用者踩坑。**P3**。

### P-13｜[P-PROVED / P3] Image 贴图缺失只画占位、无警告（契约要求「占位 + 警告」）

1. **位置**：`loom_ui.py:936-952`（`_load` 的 `except Exception: self._tex = None`）；UI 契约 §九。
2. **契约/预期**：契约 §九「Image 贴图文件缺失 | 画纯色占位 + 警告」。
3. **路径枚举**：
   - 路径 1：`texture_path` 为空 → 占位（无警告，合理）。
   - 路径 2：路径存在但加载失败（格式/权限）→ `except` → `_tex=None` → 占位，无任何输出。
   - 路径 3：加载成功 → 正常。
   - 无其他分支。
4. **实际行为**：静默降级，用户只能看到灰块。
5. **差异**：缺「警告」这一半契约。
6. **触发条件**：场景引用不存在/损坏的贴图。
7. **验证**：`grep -n "print" loom_ui.py` 在 936-952 区间为空；代码原样（`except Exception:` 后仅 `self._tex = None`）。
8. **影响与等级**：资源错误不可诊断（SEM-SILENT）。**P3**。修复方向：失败时 `print('[UI] 贴图加载失败: %r' % path)`（每元素一次，避免每帧刷屏——`_tex_loaded` 已保证一次）。

### P-14｜[P-PROVED / P3] InputField `max_length` 默认 200 与契约 §十 的 256 漂移

1. **位置**：`loom_ui.py:1346`（`max_length=200`）；`sceneio.py:763`、`agent_commands.py:2267` 同为 200。
2. **契约/预期**：UI 契约 §十 资源边界「InputField max_length | 默认 256 | 防超长」。
3. **路径枚举**：构造缺省 → 200；显式传值 → 按传入（两处序列化/命令默认也 200）。
4. **实际行为**：默认上限 200。
5. **差异**：文档 256 vs 实现 200（40 字符差）。
6. **触发条件**：不写 `max_length` 的 InputField。
7. **验证**：`python -c "from loom_ui import InputField; print('max_length =', InputField().max_length)"` → 实测输出 `max_length = 200`。
8. **影响与等级**：文档/实现漂移，用户按文档预期会少输 56 字符。**P3**。修复方向：统一为 256 或改文档（需人类确认哪个是准）。

### P-15｜[P-DISPROVED] ScrollView 命中分支的「可视区二次检查」是死代码，但不产生行为差异

- 位置：`loom_ui.py:272-287`。
- 路径枚举（反手）：`hit_test` 在 269-271 已保证 `pos` 落在 `sr` 内；因此 277 与 282 的 `self._point_in_rect(pos, sr)` 恒为 True，删除与否不改变任何返回值。子元素使用 `child_parent`（`sr+offset`），与绘制 `_draw_elem`（`loom_ui.py:709-712`）逐位一致。
- 差异：无（仅维护性：注释声称在做「命中结果仍在可视区」的检查，实际未检查元素矩形）。
- 验证：`probe_a.py A2` —— `scroll_by(0,-400)` 后 `hit` 随偏移变化；未滚出可视区时点击可命中，滚出后不命中。
- 判定：**P-DISPROVED**（无行为缺陷）；建议仅清理死代码/注释（P3 可维护性），不改逻辑。

### P-16｜[P-DISPROVED] ScrollView scissor 在 GL 路径确实生效（含 `enable_only=BLEND`）

- 位置：`loom_hud.py:108-154`（`draw_text_quad` 恢复 scissor）、`loom_hud.py:214-231`（`draw_screen_rect` 用 `scope(enable_only=BLEND)`）、`loom_ui.py:703-717`（push/pop）。
- 反手路径枚举：`moderngl` 5.12 的 `ctx.scissor` 绑定在 **当前 FBO** 上（`moderngl.Context.scissor` getter/setter 走 `self.mglo.fbo.scissor`），`scope(framebuffer=fb, enable_only=BLEND)` 不改变该 FBO 的 scissor 盒；真实离屏读回显示裁剪生效。
- 实测（`probe_gl_scroll2.py`，真实 GTX 1050 Ti 独立上下文 + `simple_framebuffer`）：
  ```
  ScrollView(0,0,100,100) 内画 Panel(0,0,100,300):
  屏幕 y=10/50/95/99 -> (255,0,0)：红色可见
  屏幕 y=100/101/110/150/199 -> (0,0,0)：被裁掉
  红色像素总数 = 10000，其中屏幕 y>=100 的 = 0
  ```
- 判定：**P-DISPROVED**（临时疑点：`enable_only` 会关 scissor —— 实测不成立，且 `draw_text_quad` 的显式恢复是冗余保护）。注意 P-11 的矩形钳制问题仍成立。

### P-17｜[P-DISPROVED] Dropdown 展开时吞掉其它控件的点击，是弹窗语义而非缺陷

- 位置：`loom_ui.py:532-543` + `1562-1578`。
- 反手路径枚举：展开态左键 → 2.5 先处理；点列表内 → 选中并收起（`handle_expanded_click` 1575）；点列表外 → 收起并消费（1578）。两条路径都先关闭弹层，符合「点击外部关闭弹层且不穿透」的通用模态语义。
- 实测（`probe_a.py A3`）：展开后点另一按钮 → `consumed=True`、`expanded=False`、按钮未触发；再点一次即可触发。
- 契约：UI 契约未规定「关闭弹层的同一次点击是否穿透」，从 §6.3「命中任何 UI 元素 → 独占」可自洽。
- 判定：**P-DISPROVED**（行为可解释且一致）。

### P-18｜[P-PROVED / P3] 内层 ScrollView 不可滚时滚轮不冒泡，外层 ScrollView 收不到

1. **位置**：`loom_ui.py:638-648`（`_hit_scroll_view` 返回最近祖先 ScrollView）+ `loom_ui.py:492-499`（只调一次）。
2. **契约/预期**：`loom_ui.py:1298-1307` `on_mouse_wheel` 返回 False 表示未消费，调用方应视作「未消费」并继续寻找可消费者（docstring 644-648 只描述「最近的 ScrollView」）。
3. **路径枚举**：
   - 路径 1：最近 ScrollView 可滚 → 消费。
   - 路径 2：最近 ScrollView 不可滚（`can_scroll()==False`）→ 返回 False → `dispatch_mouse` 不 return，但也**不会**尝试外层 → 滚轮丢失。
   - 路径 3：无 ScrollView → 不处理。
4. **实际行为**：嵌套滚动容器（如面板内一个小列表不可滚、外层表单可滚）内滚轮完全无效，且不会落到相机（`consumed=False` → 相机缩放在 GL 路径仍会执行）。
5. **差异**：与「未消费应继续传递」的常规分发语义不符。
6. **触发条件**：嵌套 ScrollView，内层内容不超出。
7. **验证**：
   ```
   # probe_a.py A6
   wheel consumed= False  outer.scroll_pos (0,0) -> (0,0)
   ```
8. **影响与等级**：特定嵌套布局下滚轮失效。**P3**。修复方向：`_hit_scroll_view` 返回祖先链，逐个尝试直到有人消费。

### P-19｜[P-DISPROVED] 点击 Dropdown 列表时 InputField 不失焦——实际不可达

- 反手路径枚举：要让 2.5 提前 return 必须已有展开的 Dropdown；打开 Dropdown 的那次点击（`loom_ui.py:546-551`）本身就把焦点交给了 Dropdown 分支（`hovered.ctype != 'input_field'` → `blur_focused()`），所以「焦点仍在 InputField + Dropdown 已展开」这一前提无法通过鼠标操作同时成立（仅可用脚本直接设置 `_focused`）。
- 实测（`probe_c.py C3`）：点击 Dropdown 后 `focused=None`，再点空白仍为 None。
- 判定：**P-DISPROVED**（鼠标路径不可达）。

### P-20｜[P-UNKNOWN] Qt 的 `focus_id` 恒为 None，是否导致「输入框聚焦时相机仍响应 WASD」

- 位置：`ui/loom_gui.py:967-975`（写死 `'focus_id': None`）、`editor.py:2204`（`if self.view.input_state()['focus_id'] is None:` 才读 WASD）。
- 证伪尝试：Qt 下键盘事件只在 viewport 有焦点时到达 `GLViewport.keyPressEvent`→`on_key_event`；QLineEdit 有焦点时事件被原生控件消费，viewport 的 `key_state` 不会更新（`loom_gui.py:377-397`），因此「输入框聚焦 + 相机移动」未必成立。
- 证真尝试失败点：需要真实 GUI 复现「viewport 按下 W（未松开）→ 点进 QLineEdit → 松开 W（release 事件给到 QLineEdit，viewport 收不到）」，才能判定 `key_state[K_w]` 是否残留为 True 并造成持续移动。
- 缺什么信息：真实窗口下焦点切换时的按键释放事件路由（`QLineEdit.hasFocus()` 与 viewport `keyReleaseEvent` 的先后）。
- 建议探针（第 1/3 次）：用 `LoomGUI(scene_path=None)` 真窗口，`QTest.keyPress(viewport, Qt.Key_W)` → `lineedit.setFocus()` → `QTest.keyRelease(lineedit, Qt.Key_W)` → 观察 `e.key_state[K_w]` 与 `camera_target` 是否持续变化。
- 判定：**P-UNKNOWN**（不猜，不顺手改）。

### P-21｜[P-PROVED / P3] UI 树用 name 作唯一键，同名元素会互相覆盖

1. **位置**：`ui/qt_uitree.py:284-285`（`('elem', canvas_idx, child.name)`）、`ui/qt_uitree.py:270-274`（按该键恢复选中）、`agent_commands.py:2176/2392/2442`（`c.root.find(name)` 只取第一个）。
2. **契约/预期**：`loom_ui.py:206-213` `find_all` docstring「重名允许, 返回列表」；`loom_ui.py:186` 等树操作也允许重名 ⇒ UI 模型层明确支持重名。
3. **路径枚举**：
   - 路径 1：唯一 name → 树选中/删除/reparent 正确。
   - 路径 2：同名兄弟 → 树两个节点 UserRole 相同；`refresh()` 恢复选中时命中第一个；右键删除走 `ui_remove(name=...)` → 删第一个匹配（可能不是用户点的那一个）。
   - 路径 3：同名不同父 → 同上（key 不含父路径）。
4. **实际行为**：见路径 2/3。
5. **差异**：树是「按名字寻址」的编辑器，而模型允许重名 ⇒ 编辑操作可能作用到错误元素。
6. **触发条件**：两个及以上元素同名。
7. **验证**：
   ```
   # probe_d.py D4
   find_all('dup') 数量 = 2 ; 树数据键 = ('elem',0,'dup')   # 两节点键相同
   ```
8. **影响与等级**：同名元素可被误删/误改（`ui_remove` 无二次确认）。**P3**（取决于用户是否会被允许重名，见「需要的信息」）。修复方向：树键改用元素对象 id（`id(elem)`）或父路径 + name，并让命令层支持唯一 id。

### P-22｜[P-UNKNOWN] 同一 `pressed.clear()` 是否也导致 3D 拾取失效（`editor.py:616`）

- 位置：`ui/loom_gui.py:1307` 与 `editor.py:2002-2004`（`render()` 内 `_update_gizmo()`）、`editor.py:616`（`if 1 not in self.pressed ... return`）。
- 证伪：若 `paintGL` 的触发排在本拍 `_on_tick` 之前（上一拍 `viewport.update()` 已排队的 paint 事件先被处理），则 `render()` 能看到 `mousePressEvent` 刚写入的 `pressed`，拾取正常；生产上「点击选中物体」可用，间接支持这一顺序。
- 证真：无法在无 GUI 环境下确定 Qt 事件队列中 paint 与 timer 的相对顺序（两事件都在 press 之后）。
- 缺什么信息：真实 `LoomGUI` 一拍内的事件顺序（`paintGL` vs `QTimer._on_tick`）。
- 建议探针（第 1/3 次）：真窗口 `LoomGUI`，在 `GLViewport.paintGL` 与 `_on_tick` 首行打点（记录 `perf_counter` 与 `1 in e.pressed`），点一次视口后读日志。
- 判定：**P-UNKNOWN**（P-01 的 UI 分发结论不依赖它，因为 `_update_camera` 是唯一 UI 分发入口且必定晚于 clear）。

---

## 3. 本轮 "Vulkan 对齐" diff 专项审查（REGRESSION）

本轮 `git diff HEAD` 在我负责范围内只改 3 个文件（26+/6-）：`editor.py`（2 处）、`loom_ui.py`（1 处）、`ui/loom_gui.py`（1 处）。逐条按「证伪：这里没有新 BUG」优先处理：

### R-01｜`editor.py:161-165` 迁移前新增 `LOOM_NO_SAVE_MIGRATE` 开关 —— **无 REGRESSION（P-DISPROVED）**

- 契约：`editor.py:155-160` 注释「测试/CI/批量工具应设 LOOM_NO_SAVE_MIGRATE=1 关掉，而不是各自重定向常量」。
- 路径枚举：①env=="1" → 跳过 rename；②env 缺失/其他值 + 保存/ 存在 + Projects/ 不存在 → rename；③rename 抛 OSError → 打印并继续；④保存/ 不存在 → 跳过。四条路径均无新增异常点（`os.environ.get` 不会抛）。
- 实测（`probe_migrate2.py`）：
  ```
  gate=1 -> (legacy, projects, DEFAULT_SAVE_DIR) = (True, True, True)     # 未迁移
  gate=0 -> (legacy, projects, DEFAULT_SAVE_DIR) = (False, True, True)    # 已迁移 + 打印
  ```
- 判定：**P-DISPROVED**（行为与注释一致；无路径产生新副作用）。

### R-02｜`editor.py:927-929` 场景恢复钳制 `camera_distance` —— **无 REGRESSION（P-DISPROVED）**

- 契约：`loom_camera.py:24-47` 定义唯一合法区间 `[0.5, 1000]`，并声明「非数值回落到 default，不抛异常」；`editor.py:2163` 滚轮路径本来就钳在 `[0.5, 1000]`。
- 路径枚举：①合法 float → 原样；②None/字符串 → default 10.0（旧代码会把 None 传给 `apply_orbit_camera` 并在 `* dist` 处 TypeError）；③nan/inf → 10.0；④<0.5 → 0.5（旧代码保留，编辑器自身不会产生该值，只可能来自外部场景/脚本）。
- 差异：旧场景若手写 `distance<0.5`，恢复值会变大（钳到 0.5）——这正是 R-03 注释声明的「与 Vk 后端一致」目标，不是缺陷。
- 实测：`python -c "from loom_camera import clamp_camera_distance as c; print(c(None), c('abc'), c(float('nan')), c(0.1), c(5000))"` → 实测输出 `10.0 10.0 10.0 0.5 1000.0`。
- 判定：**P-DISPROVED**（无路径产生新错误；默认值变化是设计目标）。

### R-03｜`loom_ui.py:597-603` 修复 `a.b = X if cond else Y` —— **修复真实缺陷，无 REGRESSION（P-DISPROVED）**

- 契约：`loom_ui.py:583-605` 的松开清理必须「清 `_pressed`、清 `_pressed_elem`、清 `_dragging_elem`」。
- 路径枚举：①非 Slider 松开（旧代码在 STORE_ATTR 目标求值时抛 AttributeError）→ 旧版 `_pressed_elem`/`_dragging_elem` 残留；新版正常清理；②Slider 松开 → 新旧一致；③无 `_pressed_elem` 的松开 → 该段不进入。
- 实测（`probe_version.py`，HEAD 版与工作区版同场景对比）：
  ```
  HEAD : 松开抛异常 AttributeError("'NoneType' object has no attribute '_dragging'") clicked=1 pressed_elem=<Button> dragging_elem=None
  now  : 松开无异常 consumed=True clicked=1 pressed_elem=None dragging_elem=None
  ```
- 副作用评估：旧版残留 `_pressed_elem` 在 GL 编辑器里会被下一次按下覆盖（实测无幽灵点击：`probe_ghost2.py` 旧版/新版点击次数都为 1），但在 Vk 播放器里 `UIInputBridge.begin_frame`（`vk_ui.py:800-807`）把它当作「UI 仍按住」→ `wants_camera()` 永久 False。新版修好后该根因消失。
- 副作用（唯一）：`vk_ui.py:767-792` 的兜底分支从此不可达（见下 R-03b）。
- 判定：**P-DISPROVED**（无新缺陷）。

### R-03b｜[REGRESSION]（P3，非故障）`vk_ui.py:767-792` 的 loom_ui 缺陷兜底成为死代码

- 位置：`vk_ui.py:767-792`（`except Exception as e: if "_dragging" in repr(e): ...`）。
- 契约依据：`vk_ui.py:767-772` 注释「兼容 loom_ui 当前版本的已知缺陷…不修改 loom_ui.py，这里按它原本要执行的清理补完」。
- 路径枚举：①新 loom_ui 不再抛该异常 → 分支永不进入（永不打印已修复提示）；②未来若有其它含 `_dragging` 字样的异常 → 仍会进入并错误地清空 UI 交互态（掩盖真实错误）；③其它异常 → 走 print 分支。
- 差异：本轮 diff 使 ① 恒成立；② 成为唯一触发可能（且语义错误）。
- 触发条件：任何在 `dispatch_mouse` 中抛出的、异常文本含 `_dragging` 的新缺陷。
- 验证：`probe_version.py` 新版无异常（`consumed=True`），因此 `except` 不执行；`grep -n "_PENDING_UP_BUG_WARNED"` 仅定义处与分支内。
- 影响：不产生当前故障；属本轮 diff 的副作用（遗留兜底 + 潜在错误掩盖）。**P3**，建议同批删除该兜底或改为版本探测。

### R-04｜`ui/loom_gui.py:3364-3382` render_api 下拉新增 auto —— **无 REGRESSION（P-DISPROVED）**

- 契约：`run_player.py:26-38` 合法值集合 `{'vulkan','opengl','auto'}`，且 `_read_setting` 读 `guiloader.load_settings('loom')` 的同一 key `render_api`；`guiloader.py:44` 默认 `'vulkan'`。
- 路径枚举：①设置值 auto/vulkan/opengl → `aid ==` 命中并 `setCurrentIndex`（0/1/2）；②未知值 → 停在 0（显示「自动」），仅显示不准，未写盘；③打开设置不改 → `currentIndexChanged` 不触发（connect 在 setCurrentIndex 之后），不会误写；④用户改动 → 写 `render_api` 并提示重启（`run_player` 每次启动读设置，提示正确）。
- 实测：`python -c "import run_player; print(run_player.resolve_backend('auto'), run_player.resolve_backend('vulkan'))"` → `auto vulkan`；控件索引映射由代码顺序保证（0=auto,1=vulkan,2=opengl，默认值 vulkan 命中 1）。
- 判定：**P-DISPROVED**（三项与解析器集合严格一致）。

### R-05｜[P-DISPROVED] `loom_ui.py` 修复是否改变 GL 侧 consumed 语义

- 旧版非 Slider 松开会抛异常 → `editor._dispatch_ui_mouse` 的 `except` 把 `consumed` 置 False；新版返回 True。审查结论：这是修复方向（松开应被 UI 消费），并且 `_update_camera` 的 `_ui_lock` 只影响本帧鼠标相机控制（`editor.py:2125-2173`），不存在「松开帧永久锁相机」的路径（下一帧 `_pressed_elem=None`）。
- 判定：**P-DISPROVED**。

**REGRESSION 小结**：本轮 diff **未引入功能性 REGRESSION**；唯一副作用类项 = R-03b（P3 死代码/潜在错误掩盖）。

---

## 4. 统计

| 判定 | 数量 | 编号 |
|---|---|---|
| P-PROVED | 16 | P-01~P-14, P-18, P-21 |
| P-DISPROVED | 9 | P-15, P-16, P-17, P-19, R-01, R-02, R-03, R-04, R-05 |
| P-UNKNOWN | 2 | P-20, P-22 |
| P-CONTRADICTION | 0 | — |
| [REGRESSION] | 1（P3 非故障） | R-03b |

> 疑似项总数 = 16 PROVED + 9 DISPROVED + 2 UNKNOWN + 1 REGRESSION（R-03b，与 R-03 同处）+ 1 处 diff 副作用 = 28 条登记（含 R-01~R-05 的 diff 专项）。

> 说明：P-CONTRADICTION = 0 是因为每条疑似项在写正手前都先完成了反手路径枚举，未出现「既证明无 bug 又证明有 bug」的冲突链；P-UNKNOWN 保留 2 条（方法论 §9.4 要求不得全绿/全红）。

**按等级分布**：P0 = 0；P1 = 3（P-01/P-02/P-03）；P2 = 6（P-04/P-05/P-06/P-07/P-08/P-09）；P3 = 7（P-10~P-14, P-18, P-21）+ R-03b。

**回归测试结果**：`test_ui.py` / `test_editor_ui.py` / `test_vk_ui_input.py` / `test_scrollbar.py` / `test_gameplay_bugs.py` / `test_grid.py` 全部 ALL PASS —— 说明上述 P1 全部落在现有测试覆盖之外（测试桩直接调 `dispatch_mouse`/记录 push/pop，未覆盖 Qt 事件时序与真实 GL 裁剪的集成）。

---

## 5. 修复建议排序（只给方向，不含代码）

| 顺序 | 项 | 方向 | 风险 |
|---|---|---|---|
| 1 | P-01 | Qt 主循环把「清空瞬态」移到 UI 分发之后；或统一改走 `vk_ui.UIInputBridge` 那套「帧首聚合→一次分发」模型（`vk_ui.py:707` 已可复用） | 高收益；需同步回归 `test_frame_pacing`、`test_vk_ui_input` |
| 2 | P-02 | `hit_test` 跳过 Canvas root（root 仅作容器）；若需 root 吞空白点击，改为「只吞空白、不阻挡更低 Canvas 的前景元素」 | 语义变更，需人类裁决 Q1 |
| 3 | P-03 | `_dispatch_ui_mouse` 传 `self.mouse_wheel`；UI 消费后不再缩放相机并把 `mouse_wheel` 清零挪到分发之后 | 中等；注意 P-06 同帧合帧 |
| 4 | P-04 | 播放边界对 `ui` 做 `sceneio` 同构快照/还原（不入 undo） | 中等；注意 `ui.default_canvas` 引用失效重置 |
| 5 | P-05 | `GLViewport.resizeEvent` 调 `e.ui.resize(w,h)`（物理像素） | 低 |
| 6 | P-06 | wheel 消费后继续处理按下/松开，合并 consumed | 低 |
| 7 | P-07 | 按下时记录 `_dragging_elem` 所属 Canvas，拖动用它算 screen_rect | 低 |
| 8 | P-08 | UI 树摘要纳入 `visible/enabled/z_order`（或直接用 ui 段 JSON） | 低 |
| 9 | P-09 | 编辑态也 `draw_all`（可加开关） | 低 |
| 10 | P-10~P-14, P-18, P-21 | 文档/实现对齐与边界钳制修正；P-21 需先定「name 是否唯一」 | 低 |
| 11 | R-03b | 删除/改写 vk_ui 的 loom_ui 兜底（同批清理） | 低 |

---

## 6. 需要人类裁决的封闭问题

**Q1（多 Canvas 命中语义，关联 P-02/P-10）**：当存在 ≥2 个 screen Canvas 时，顶层 Canvas 的 root 是否应参与命中？
- A. 不参与（root 仅作布局容器，低层 Canvas 可交互）——语义最一致，但「点空白不误选 3D」需要另找载体；
- B. 参与且全屏拦截（当前行为，低层 Canvas 仅作展示）——需要文档明确「低层不可交互」；
- C. 参与但只吞空白：root 命中时继续下探更低 Canvas，仅当无人命中时才由 root 消费点击。
（另：禁用容器时是否连子树一起禁用，请在 A/B/C 之外单独确认。）

**Q2（播放边界，关联 P-04）**：停止播放时，脚本对 `engine.ui` 的运行时修改是否必须还原？
- A. 必须还原（与 models/lights/cameras 一致，「所见即所得」）；
- B. 不还原（UI 视为运行时状态，允许跨播放保留，但需要停止时刷新「已保存」基线，避免假脏）；
- C. 可配置（默认 A）。

**Q3（编辑态预览，关联 P-09）**：官方 Qt 编辑器在「编辑态」是否需要在视口实时绘制 Canvas UI？
- A. 需要（与 Unity 一致，且 UI 树/检查器编辑才能所见即所得）；
- B. 不需要（仅在播放态预览，当前行为），文档需写明；
- C. 需要但做成可开关（默认开）。

---

## 7. 附：本次审计的可复现探针清单

| 探针 | 目的 | 关键输出 |
|---|---|---|
| `probe_a.py` | 禁用子树命中、ScrollView 命中、Dropdown 吞点击、嵌套滚轮、dispatch_key 消费 | 见 P-10/P-18/P-17 |
| `probe_b.py` / `probe_b2.py` | 多 Canvas 命中优先级、拖动跨 Canvas | 见 P-02/P-07 |
| `probe_c.py` | wheel+click 合帧、wheel 不转发 | 见 P-03/P-06 |
| `probe_d.py` | hud scissor 钳制、gui 嵌套 scissor、树摘要、同名键 | 见 P-11/P-12/P-08/P-21 |
| `probe_gl_scroll2.py` | 真实 GL 离屏 ScrollView 裁剪 | 见 P-16 |
| `probe_qt.py` | 真实 `LoomGUI._on_tick` + 真实 `EditorApp._dispatch_ui_mouse` | 见 P-01 |
| `probe_play_ui.py` | 播放边界 UI 还原 | 见 P-04 |
| `probe_version.py` / `probe_ghost2.py` | HEAD 版 vs 工作区版松开清理 | 见 R-03 |
| `probe_migrate2.py` | 迁移 env 开关 | 见 R-01 |

> 探针均在 `%TEMP%\loom_audit06\` 下执行，运行环境：`LOOM_NO_SAVE_MIGRATE=1`、`SDL_VIDEODRIVER=dummy`；Qt 相关用 `QT_QPA_PLATFORM=offscreen`。仓库内未新增/修改任何受跟踪文件。
