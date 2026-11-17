# 修复报告 · 批次 F_core_scene（scan 01_core + 02_scene）

- **日期**：2026-11-07
- **缺陷来源**：`scan_01_core.md` P-13 / P-09 / P-05，`scan_02_scene.md` P-14（与 P-13 同一缺陷）
- **修改文件**：`matlib.py`、`loom_transform.py`、`loom_game_object.py`
- **新增测试**：`tests/test_matlib_gimbal.py`、`tests/test_parent_children_invariant.py`、`tests/test_scale_normalize.py`（均被 `run_all` 收集）
- **未触碰**：`engine.py` / `editor.py` / `loom_components.py` / `loom_model_gpu.py`（F8 并行修改），`sceneio.py` / `undo.py`（其它并行代理）

---

## 1. 改前 / 改后实测对照

探针：`tests/_tmp/fix_batch_probe.py`（同一脚本在改动前后各跑一次，输出逐字对照）。

| # | 场景 | 改前 | 改后 |
|---|---|---|---|
| 1 | **[P2] `decompose_euler` β=−90°**（α=0.3, γ=0.7）往返 `mat4_rotation(decompose(R))` | 分解 (−1.000000, −1.570796, 0)，**maxerr = 1.683e+00** | 分解 (**+1.000000**, −1.570796, 0)，**maxerr = 1.110e−16** |
| 2 | `decompose_euler` β=+90° / ±89.999° | err 4.19e−17 / 6.19e−13 | 不变（4.19e−17 / 6.19e−13） |
| 3 | **[P2] `set_parent(preserve_world=True)` β=−90°**（父旋转=单位，子世界 β=−90°） | 世界旋转差 **1.682942 rad**，局部 (−1.0, −π/2, 0) | 世界旋转差 **0.0**（测试内 1.11e−16），局部 (+1.0, −π/2, 0) |
| 4 | `set_parent` β=+90° / ±89.999° | 世界旋转差 0 | 不变（0） |
| 5 | **[P2] `GameObject.parent` 直写**（先 `set_parent(c,p)`，再 `c.parent=q`） | `P.children=['C']`（脏）、`Q.children=[]`（缺）、`collect_subtree(P)=['P','C']` | `P.children=[]`、`Q.children=['C']`、`collect_subtree(P)=['P']`、`collect_subtree(Q)=['Q','C']` |
| 6 | 直写挂出的子树 `remove_subtree(父)` | 旧父仍"认领"已移走的子树（会误删） | 连子树删：`models` 只剩无关物体 |
| 7 | **[P2] `m.scale = (1, 2)` 后 `model_world_matrix`** | **IndexError: tuple index out of range** | `m.scale=(1.0,2.0,1.0)`；矩阵对角 `(1,2,1)` |
| 8 | `GameObject(..., scale=(1,2))` 后矩阵路径 | **IndexError** | `(1.0,2.0,1.0)`；矩阵对角 `(1,2,1)` |

改前关键输出（原样）：

```
beta=  -90.000  decomp=(-1.000000,-1.570796,+0.000000)  err=1.683e+00
beta=  -90.000  rot_err=1.682942  pos_err=0.000e+00  local=(-1.0000,-1.5708,0.0000)
P.children=['C'] Q.children=[] c.parent=Q
collect_subtree(P)=['P', 'C'] collect_subtree(Q)=['Q']
scale=(1.0, 2.0) -> IndexError: tuple index out of range
ctor scale=(1,2) -> IndexError: tuple index out of range
```

改后关键输出：

```
beta=  -90.000  decomp=(+1.000000,-1.570796,+0.000000)  err=1.110e-16
beta=  -90.000  rot_err=0.000000  pos_err=0.000e+00  local=(1.0000,-1.5708,0.0000)
P.children=[] Q.children=['C'] c.parent=Q
collect_subtree(P)=['P'] collect_subtree(Q)=['Q', 'C']
scale after set=(1.0, 2.0, 1.0)   model_world_matrix OK diag=[1. 2. 1.]
ctor scale=(1,2) OK scale=(1.0, 2.0, 1.0) diag=[1. 2. 1.]
```

---

## 2. 修复说明（每项一句话）

1. **`matlib.decompose_euler` 万向锁符号**（P-13 ≡ P-14）：`|cosβ|<1e-9` 分支按 β 符号取 `α = atan2(±R[1,0], R[1,1])`（β=+π/2 取 +，β=−π/2 取 −），并补推导注释；β=+π/2 行为逐位不变。
2. **`set_parent` 世界旋转**（P-13 set_parent 侧）：根因即 1，无需改 `Rl = wr @ inv(Rp)` 数学；仅把 `new_parent.children.append` 加 `child not in children` 守卫（与新的 parent setter 幂等共存，兼容非 GameObject 模型桩）。
3. **`GameObject.parent` 双向关系**（P-09）：setter 直写时从旧父摘除、向新父登记（幂等），并保留原 `_LIVE_INSTANCES` 结构代 bump；`children` 改为幂等列表 `_ChildList`（append/insert 去重），兜住 `sceneio._link_by_map` 等仍会手工 append 的旧调用点，避免重复子节点。
4. **`GameObject.scale` 短元组**（P-05，追加项）：setter 与构造入口统一 `_normalize_scale`，1~3 个数值补齐为 3 元组（缺省补 1.0），长度 0/4+ 或非数值显式 `ValueError`，矩阵/SoA 路径不再 IndexError。

设计取舍：
- parent setter **不**委托 `engine.set_parent(v, preserve_world=False)`：该路径需要活引擎实例，而直写可能发生在多引擎/无引擎（脚本、测试桩）场景；setter 只做纯结构维护 + 既有弱引用表 bump。
- `_ChildList` 而非改 `sceneio.py`：本批禁止触碰 sceneio，且旧调用点"写 parent + 手工 append"顺序无法由 setter 单方面消除，幂等列表是零语义漂移的最小兜底。
- scale 归一化在 `loom_game_object.py` 落地，与 F8 在 `loom_components.py` 的入口归一化幂等叠加（F8 未落地时本批已能挡住 IndexError）。

---

## 3. 验收（全部实测）

| 项 | 结果 |
|---|---|
| `python tests/test_matlib_gimbal.py` | **ALL PASS**（59 项；β∈{±90°,±89.999°} 往返 worst 6.186e−13 < 1e−6；set_parent 世界旋转 worst 6.186e−13） |
| `python tests/test_parent_children_invariant.py` | **ALL PASS**（24 项；含 sceneio round-trip children 恰好 1 项、remove_subtree 连子树删） |
| `python tests/test_scale_normalize.py` | **ALL PASS**（20 项；含 `compute_world_matrices` 批量路径） |
| `python tests/test_xform_sync.py` | exit=0 |
| `python tests/test_sceneio.py` | exit=0 |
| `python tests/test_integration.py` | exit=0 |
| 关联回归 `test_decompose / test_reparent_preserve / test_undo / test_hierarchy / test_camera_parent` | 全部 exit=0 |
| `python tests/_tmp/ab_batch.py` | **22/22 PASS**，最大 MAE **0.000082**（≤0.0002），**逐场景与改前逐值相同** |
| `python tests/run_all.py` | **74 个测试文件，exit=0，0 条 FAIL** |

---

## 4. 遗留 / 新发现问题（未在本批修改）

1. **`physics_bridge.py:535-545` `quat_to_euler_batch` 存在同款万向锁符号 bug**：万向锁分支统一取 `arctan2(M[:,1,0], M[:,1,1])`，未按 β 符号取反，β=−π/2 时与 `decompose_euler` 修复前同错。不在本批允许文件内，建议同批后续修复并复用同一符号规则。
2. **`GameObject.parent` 直写仍无环保护**：`c.parent = 子孙` 会成环，`collect_subtree/model_world_matrix` 将无限递归/栈溢出。本批只修 children 一致性；建议加祖先链检测（或统一委托 `set_parent`）。
3. **`TransformComponent.parent` 仍是普通属性**：直写 `m.transform.parent = p` 会绕过 `GameObject.parent` setter，不维护 children。全库生产代码无此写法（grep 仅 `loom_transform.set_parent` 经 `child.parent` 走 property），但属潜在旁路。
4. **`sceneio._link_by_map`（sceneio.py:306-307）仍"写 parent 后手工 append"**：现被 `_ChildList` 幂等兜住，建议后续清理为只写 parent。
5. **`TransformComponent.scale` 直写短元组仍可绕过归一化**（`m.transform.scale = (1,2)` → 矩阵 IndexError）。按分工由 F8 的 `loom_components.py` 入口归一化覆盖；本批只保证 `GameObject.scale`/构造入口。
6. **P-10 删父留子悬空**（`loom_model_gpu.remove_model` 不清理子节点 parent）不在本批范围（F8），本批只保证 `remove_subtree` 能连子树删。
7. **并行修改提示**：跑验收期间 `sceneio.py`/`undo.py` 被其它代理并发修改（`sceneio` 新增"丢弃无引用默认材质"警告），ab_batch 输出因此新增该警告行，但 22 场景 MAE 逐值不变、run_all 仍 exit=0。
