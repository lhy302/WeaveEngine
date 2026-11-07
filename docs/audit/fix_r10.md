# 修复报告 · 批次 R10（_fix_summary §5 遗留收尾）

> 2026-11-07 | 允许文件：scene_driver.py、loom_components.py、loom_game_object.py
> 新增测试：tests/test_scene_driver_physics_log.py、tests/test_scale_all_paths.py、
> tests/test_parent_cycle_guard.py、tests/test_lod_fastpath.py（均被 run_all 收集）
> 未 git add/commit；未触碰其它生产文件。

## 1. 改动文件

| 文件 | 改动 |
|---|---|
| scene_driver.py | ① 物理桥异常"每场一条 + 计数"；② LOD 候选集合（加载登记 + _lod_gen 增量重建 + 空集合 O(1) 早退）；③ remove_model 同步剪枝；④ load_from_data 重置日志计数 |
| loom_components.py | MeshRendererComponent 新增 lod_levels / lod_screen_levels property（写入 bump 类级 _lod_gen），供驱动感知运行期挂/摘 LOD |
| loom_game_object.py | GameObject.parent setter 增加成环保护（沿父链上溯遇自己 -> ValueError，另加 10000 层上限） |
| tests/test_scene_cycle_reject.py | **附带最小适配（2 行，见 §5）**：该用例原先用 GameObject.parent 直写构造环；守卫落地后改为 TransformComponent 层直写构造"已损坏父链"，继续验证 sceneio 保存前防御 |

## 2. 逐项：根因 / 改法 / 改前-改后实测

### 2.1 物理桥异常每帧刷屏（P3）
- 根因：_step_physics 的 except 每帧 print，坏桥持续异常 -> 每秒 60 条。
- 改法：本场首次异常打印 1 条（含 repr + "后续只计数"），之后仅 _bridge_err_count += 1；
  load_from_data 重置（每场一条）；ensure_models/pre_step/step/post_step 任一异常同规则。
- 实测（假桥 step 持续抛 RuntimeError，5 帧）：
  - 改前（旧函数体等价复现）：**5 条**日志；
  - 改后：**1 条**日志，_bridge_err_count = 5。
- 测试：test_scene_driver_physics_log.py（17 项；含 advance_logic 路径、换场景重置、健康桥 0 条）。

### 2.2 TransformComponent.scale 直写绕过归一化（P3）
- 现状：F8 已把 TransformComponent 构造器与 scale setter 改为共用 _normalize_scale
  （loom_components.py，工作树内已存在）；本批复核所有公开写入路径，补回归测试锁死，未重复改源码。
- 实测：
  - 改前（旧 setter 结果等价：_scale 直存 (1,2)）-> model_world_matrix：**IndexError: tuple index out of range**；
  - 改后：transform.scale=(1,2) -> **(1.0,2.0,1.0)**，世界矩阵对角 **(1,2,1)**。
- 测试：test_scale_all_paths.py（36 项）：TransformComponent 构造/直写、GameObject 构造/setter/set_scale、
  非法输入 0/>3/非数值/标量在各入口均 ValueError 且旧值不破坏、直写后矩阵/批量 SoA 正确、_xform_gen bump、父链世界缩放。

### 2.3 GameObject.parent 直写无环保护（P2）
- 根因：引擎 set_parent 早已防环，但 m.parent = p 直写只维护 children；写出 A<->B 后
  collect_subtree 无限递归（保存/删除/Prefab/包围盒全走它）。
- 改法：setter 改指针前沿 v 父链上溯，遇 self 抛 ValueError（拒绝且零副作用）；
  父链 >=10000 层视为已损坏同样拒绝。
- 实测：
  - 改前（等价损坏环：指针 + children 双向成环，recursionlimit=300）：collect_subtree -> **RecursionError**；
  - 改后：b.parent=a -> **ValueError**，状态不变；collect_subtree 返回有限列表 **['B2','A2']**。
- 测试：test_parent_cycle_guard.py（27 项）：自环/二元/多元/50 层回挂祖先、合法换父脱父不误伤、拒绝零副作用、DFS 可终止。

### 2.4 _update_lod 无 LOD 仍每帧全量扫描（P3）
- 根因：旧实现每帧遍历全部 models 用 getattr 找候选（500 物体 ~0.11ms/帧）。
- 改法：
  - SceneDriver 维护 _lod_models 候选集合；load_from_data 后登记一次（O(N)）；
  - MeshRendererComponent.lod_levels / lod_screen_levels 改为 property，写入 bump 类级 _lod_gen；
    驱动比较 _lod_gen，变化才重建集合（运行期脚本/撤销/EAI 直接写 renderer.lod_* 也能感知）；
  - 集合为空 -> 只做整数比较 + 空判断（O(1)）；有配置时只遍历该集合；
  - remove_model 同步剪枝；集合内失效项（旁路置 None）一帧后重建剪枝。
- 实测（500 物体、无 LOD、1000 次均值）：
  - 改前（旧全量扫描等价复现）：**0.191481 ms/帧**；
  - 改后：**0.000248 ms/帧**（验收门槛 <0.02ms，约 770 倍下降）。
- 测试：test_lod_fastpath.py（18 项）：500 物体快路径 <0.02ms、5 帧 0 次世界矩阵、
  加载只登记配置项、运行期挂/摘 LOD 自动感知、remove_model 剪枝、距离选模语义不变。

## 3. 验收

| 项 | 改前 | 改后 |
|---|---|---|
| python tests/_tmp/ab_batch.py | 22/22 PASS，最大 MAE 0.000082 | **22/22 PASS，最大 MAE 0.000082**（逐场景数值与改前完全相同） |
| python tests/run_all.py | exit=0（基线） | **exit=0**（第二次全量；首跑因并行代理中途把 test_r5_wheel_backend.py 改名导致 file-not-found，与代码无关） |
| 4 个新增测试单跑 | — | **全部 ALL PASS**（physics_log / scale_all_paths / parent_cycle_guard / lod_fastpath） |
| 相关旧测试 | — | test_scene_driver_lod / test_scale_normalize / test_scene_cycle_reject / test_physics* / test_hierarchy / test_parent_children_invariant / test_reparent_preserve / test_sceneio / test_undo_full_coverage / test_xform_sync 全 PASS |

## 4. 遗留 / 说明
- 成环守卫只覆盖 GameObject.parent 公开入口；TransformComponent.parent 层直写仍可构造损坏环
  （sceneio 保存前 _validate_model_graph 仍会拒绝；test_scene_cycle_reject 正是用该路径造损坏态）。
- 直接对 driver.models 做 list.remove/append（不走 remove_model / load_from_data）不会触发 _lod_gen，
  候选集合可能滞后一帧或保留已摘除对象；现有脚本 API 均走 remove_model，未扩大改动。
- 物理异常计数目前只暴露 _bridge_err_count（无周期汇总打印），符合"首次后静默"选项。
