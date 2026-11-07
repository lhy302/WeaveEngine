# F8_core_editor 修复报告（2026-11-07）

> 范围：scan_01_core P-01/P-02/P-03/P-04/P-05/P-09/P-10 + F3 遗留 P-22（Qt gizmo 点击顺序）
> 改动文件：engine.py、editor.py、loom_components.py、loom_model_gpu.py、loom_lighting.py（仅 P-02 空表回退分支）
> 未动：loom_game_object.py / loom_transform.py（F9 独占）、ui/loom_gui.py（F3）

## 0. 结论

| # | 项 | 改前实测 | 改后实测 |
|---|---|---|---|
| 1 | **P-01 编辑器播放态矩阵冻结** | actual.x=237 → _frame_world[3,0]=0、_soa_snap.pos=0、_render_world[3,0]=0 | **237 / 237 / 237**；后续逻辑帧继续跟随（10.0） |
| 2 | **P-02 小场景碰撞事件永不触发** | n=3：_prep_pairs=[]、start=0；n=40 无池：pairs=0、事件=0（旧内联 154） | n=3：pairs=3、**start=6**（有池/无池同）；n=40 无池：pairs=77、**事件=154 = 旧内联 154** |
| 3 | **P-04 同一逻辑帧派发两次** | _logic_frame 后 1 次，渲染 split 再派发 → 2 次 | _logic_frame 后 1 次、_disp_gen==_logic_gen → 渲染侧 0 次，**总 1 次** |
| 4 | **P-03 _has_scripts_cached 不被 add_script 失效** | 无脚本场景挂脚本后仍 False，handle() 0 次 | 挂脚本后 True，handle() 1 次（再次挂载 2 次） |
| 5 | **P-05 scale=(1,2) 后 IndexError** | transform.scale=(1,2) 存储 (1,2) → compute_world_matrices **IndexError** | 归一化 (1.0,2.0,1.0) → 矩阵 (1,4,4) 正常；长度 0/>3 显式 ValueError |
| 6 | **P-09/P-10 删父悬空** | remove_model(P) 后 models=['C']、C.parent=P 悬空 | remove_model(P) **连子树删** → models=[]、C.parent=None；批量/递归矩阵一致 |
| 7 | **P-22/F3 Qt gizmo 点击顺序** | _on_tick 清 pressed 后 paintGL 的 _update_gizmo 拿不到点击（拾取 0 次） | 代际点击消费：**拾取 1 次**；同击不重放；UI 命中 0 次 |
| 8 | **F7 收口：加载非法场景先清空旧场景** | 成环场景 B 加载 → 旧场景 A 已被 remove_model 清空（用户丢工作） | 清空前 _validate_object_graph：**A 原样保留**、红字提示、_scene_path 不变 |

## 1. 逐项实现

### P-01（engine.py _logic_prep + editor.py _refresh_play_matrices）
- _logic_prep：is_playing 时每个逻辑帧都走 compute_world_matrices（内部 _fw_cache 静止帧直接返回缓存对象，动态帧才真算），同时 _transform_snapshot 刷新 _soa_snap 供 interp.advance 翻页。
- editor.render 播放分支抽出 _refresh_play_matrices(it)：渲染矩阵走插值；_frame_world 只由逻辑帧维护，首帧（逻辑帧未跑）才用 compute_world_matrices 补一次 —— **不再把插值矩阵写进逻辑矩阵**（旧 _frame_world = _render_world 是冻结使能条件）。

### P-02（engine.py _logic_prep + loom_lighting.py 空表回退）
- _logic_prep：is_playing 时无条件算 _prep_pairs；_collision_pairs_parallel 池不可用就在调用线程串行跑（同一检测器，输出集合与旧内联逐位一致）。删除旧的 pool is not None and n>=32 门。
- loom_lighting._parallel_shadow_and_collision split 路径：_pairs is None（进播放首帧/异步逻辑线程未起）时回退旧串行 _update_collision_events，按 _disp_gen 节流；未回退 F2 的任何改动。

### P-04（engine.py _logic_frame）
- 逻辑帧派发后置 self._disp_gen = self._logic_gen + 1（随后 _logic_gen += 1），渲染 split 路径 _disp_gen != _lgen 不再成立 → stay 类钩子每逻辑帧 1 次/物体。
- 预取帧语义未改（仍是 _logic_frame 内派发一次）。

### P-03（engine.py 缓存键 + loom_components.ScriptComponent）
- ScriptComponent.__init__ bump 类级 _script_gen（全库唯一构造点）；update_scripts 缓存键改为 (struct_gen, ScriptComponent._script_gen)。remove/clear 不 bump 只会多扫一帧（多算不错算）。

### P-05（loom_components.py 入口归一化）
- 新增 _normalize_scale（1~3 数值 → 3 元组补 1.0；None→(1,1,1)；0/>3/非数值 → ValueError），TransformComponent.__init__ 与 scale setter 共用。与 F9 在 loom_game_object._normalize_scale 的同名语义一致（F9 负责 GameObject setter；本批负责 TransformComponent 直写入口）。

### P-09/P-10（loom_model_gpu.py + editor.py）
- remove_model：有子物体 → remove_subtree（Q3=A 连子树删，Unity 语义）；无子物体 → _remove_one_model。
- remove_subtree 逐节点走 _remove_one_model（避免父节点再次触发子树删除的递归/重复）；_remove_one_model 删父后把剩余子物体 set_parent(..., preserve_world=False) 提升为根，保证批量/递归矩阵一致。
- editor.delete_object：删除前 collect_subtree 数出 N；N>0 时调用 UI 注入的 _confirm_delete_callback(model, N)，返回 False 取消。无注入（无头/最小视图）保持旧行为直接删。
- **F9 侧配合点**：GameObject.parent 直写已由 F9 维护 children（_ChildList），本批依赖该不变量；TransformComponent.scale 直写短元组由本批归一化兜住。

### F7 收口（editor.py _load_scene 先校验后清空）
- 旧顺序：json 读取 → 记录 _scene_path → remove_model 全部 + undo.clear → sceneio.scene_from_dict（校验在其内部）。
- 新顺序：json 读取 → 顶层 dict + objects 列表检查 → sceneio._validate_object_graph → 通过后才记录 _scene_path/save_last_dir → 清空 + 载入。失败时 _notify 红字提示并原样保留旧场景、undo、材质库与 _scene_path。

### P-22/F3（editor.py 代际点击）
- _update_camera 在 UI 分发后、清空 pressed 前：若本拍左键按下且 UI 未消费，记 _gizmo_click_gen += 1 + _gizmo_click_pos。
- _update_gizmo：代际点击消费一次（无论命中/点面板/Alt/UI 抢走都只消费一次）；无代际时保留旧 pressed 路径。另用 _gizmo_consumed_press（坐标对象身份）防"paintGL 先于 _on_tick"反向顺序重复拾取。
- **方案选择：A（代际标记），不选 B（把清空再往后移到 paintGL 之后）**。理由：
  1. _on_tick 与 paintGL 是两个独立 Qt 回调，QTimer 无法可靠知道 paintGL 何时完成；B 要么依赖"下一拍再清"（跨帧语义混乱），要么把清空塞进 render（渲染层承担输入生命周期，破坏分层）。
  2. B 还必须改 ui/loom_gui.py（F3 文件）；A 完全落在 editor.py，且同时兼容"paintGL 先到"的反向顺序（_gizmo_consumed_press 身份去重）。
  3. A 的消费点唯一（_update_gizmo），UI 命中时 _ui_lock 直接不登记，满足"UI 抢走不进 gizmo"。

## 2. 新增回归测试（均被 run_all 收集）

- tests/test_editor_playback_matrix.py（9 断言）
- tests/test_collision_events_small_scene.py（7 断言）
- tests/test_add_script_cache.py（12 断言）
- tests/test_remove_subtree_semantics.py（17 断言）
- tests/test_qt_gizmo_click_order.py（9 断言）
- tests/test_editor_load_reject_keeps_scene.py（9 断言）

## 3. 验收

- python tests/_tmp/ab_batch.py：**22/22 PASS，最大 MAE 0.000082 ≤ 0.0002**（与改前同值）。
- tests/test_integration.py / test_editor_ui.py / test_gameplay_bugs.py / test_sceneio.py：exit=0。
- python tests/run_all.py：**exit=0，91 个 test_*.py 全绿（含 6 个新增；0 FAIL）**。
- 新增 5 个测试单跑全 PASS。

## 4. 遗留 / 未做

1. **审计探针的 n=40 无池 228 次**依赖其特定随机场景（仓库内无该探针脚本）；本批用"同场景旧内联基线对拍"证明逐位同口径（154=154）。若必须复刻 228，需提供 probe_collision_events2.py。
2. **UI 确认框接线**：_confirm_delete_callback 需 ui/loom_gui.py 注入（弹 QMessageBox 显示 N）。该文件属 F3，本批未动 —— 当前 Qt 编辑器删除有子物体的父对象会直接删（无提示），功能正确但缺提示。
3. remove_script/clear_scripts 不 bump _script_gen：缓存 True 会多扫一帧（无害），未改（add_script 在 F9 文件）。
4. P-10 的"外部直接把 child.parent 指向不在 models 的物体"仍会在 loom_transform.model_world_matrix 沿悬空父合成；根因在 F9 的 loom_transform.py（本批只在删除路径保证不产生悬空）。建议 F9 在 model_world_matrix 对"父不在 models"与批量路径对齐。
5. _framebuf_prefetch 的注释声称"预取帧不派发"，实际 _logic_frame 内仍派发（既有行为，本批未改；如需改属性能语义，需单独裁决）。
