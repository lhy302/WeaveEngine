# 修复批次 08 — 物理桥建体/线程生命周期 (scan_08_physics)

- 批次: fix_08_physics
- 改动文件: physics_bridge.py, physics_pipe.py, physics_glue.py, loom_physics.py
  （另新增测试 tests/test_physics_body_init.py, tests/test_physics_pipe_errors.py + 本文档）
- 未执行任何 git add / git commit
- 验收:
  - python tests/_tmp/ab_batch.py → 22/22 PASS，最大 MAE 0.000082（门槛 ≤0.0002）
  - python tests/test_physics*.py → 5 个文件全 PASS（含 2 个新增，共 32 项断言）
  - python tests/run_all.py → exit=0
  - 改前/改后数值对照见各节（旧代码用 git show HEAD:Loom/... 原样 exec 实测）

---

## 1. [P1] 建体 identity 旋转被首帧写回模型

位置: physics_bridge.py::_build_one（旧 756-760 / 785-786 / 853-855）

根因: create_body(rot=(0,0,0,1)) 建在 AABB 中心 + identity 旋转，
而 _last_sync 预置成模型当前位姿 → 首帧 dirty=False，post_step 把
Jolt 的 identity 旋转反解后写回模型（初始旋转清零）。

改法:
- 建体即用模型世界位姿：pos = model_world_matrix(m)[3,:3]，
  rot = quat_from_mat3(world_rotation_3x3(m))；
- _last_sync 仍存模型局部位姿（脏检测的比较基准就是局部位姿），
  因此首帧 dirty=False 时 body 与模型世界位姿一致，回读为恒等；
- 盒体半长改为体局部坐标系极值（_box_half_extents_local）：
  体已带世界旋转，若仍用"世界 AABB 半长"会把已含旋转的 AABB 再转一次
  （45° 立方体膨胀 √2）。无旋转/均匀缩放时与旧世界 AABB 半长逐位一致。

改前/改后实测（动态体 rot=(0.4,0.2,0.1)，use_gravity=False，5 帧）:

| | 初始旋转回读 |
|---|---|
| 改前 | (0.0, -0.0, 0.0)（被 identity 写回） |
| 改后 | (0.39999998, 0.19999999, 0.09999999) |

旋转父（rot=(0.2,0.3,0.1)）下子体局部 rot=(0.4,0.2,0.1)：
改前会被写成 inv(R_parent)；改后保持 (0.4,0.2,0.1)（误差 <1e-3）。
新测试 1a/1b/2/2b 锁定。

---

## 2. [P1] AABB 中心建体导致瞬移

位置: physics_bridge.py::_build_one（旧 756, 1164-1178）

根因: 体建在世界 AABB 中心，post_step 回读后把世界 AABB 中心写回
模型位置 → 偏心网格（网格原点 ≠ AABB 中心）首帧瞬移。

改法: 同第 1 项 —— body 位置 = 模型世界位置（碰撞形状仍用 AABB 近似）。

实测（立方体网格顶点整体 +3x，模型 position=(0,3,0)，无重力 1 帧）:

| | 模型位置 |
|---|---|
| 改前 | (3.0, 3.0, 0.0)（被 AABB 中心拽走） |
| 改后 | (0.0, 3.0, 0.0) |

新测试 3 锁定。

---

## 3. [P1] 祖先脏传播断链（父无碰撞体）

位置: physics_bridge.py::_dirty_mask_batch（旧 875-915）

根因: id2idx 只用 _entries（有碰撞体的模型）。父无碰撞体时不建体、
不在 entries 里 → 子体的 pidx=-1 → 父移动不传播 → 子体停在旧世界位姿，
post_step 用新父矩阵反算局部位置 → 局部被写成 -4.0。

改法:
- 脏检测节点集 = 有体模型 + 完整祖先链（"模型森林"）：祖先节点也参与
  位姿比较与 C 传播，子体 pidx 指向链上父节点；
- _build_one 建体时给祖先链补 _last_sync 基线（否则父在 build 后移动，
  首次脏检测会把"移动后"当基线而漏传播）；
- 祖先节点（无体）的基线在每次脏检测后推进到当前位姿，只在"相对上一帧
  移动"时传播脏，不重复标脏子树；有体条目仍由 pre_step/post_step 对齐。
- 缓存键扩为完整节点集（ids/位姿/sync/父链），语义不变。

实测（父 collider.enabled=False，子体 use_gravity=False，父 +4x，2 帧）:

| | 子体局部位置 | 子体世界位置 |
|---|---|---|
| 改前 | (-4.0, 0.0, 0.0) | (0.0, 0.0, 0.0)（不跟随） |
| 改后 | (0.0, 0.0, 0.0) | (4.0, 0.0, 0.0) |

新测试 4a/4b 锁定。tests/_tmp/phys_dmb_equiv_check.py 的 E1-E6
（含 reparent/缓存命中/污染防护）全部仍 PASS。

---

## 4. [P1] 子步异常被后续成功子步覆盖

位置: physics_pipe.py::_loop（旧 71-73, 97-99）

根因: 成功路径 self._err = None 会清掉同一批前序子步刚记录的异常，
wait_pending 永远看不到错误（静默吞异常）。

改法: 删除成功路径清空；异常分支改为 if self._err is None: self._err = e
（首个未消费错误保持到 wait_pending 消费）。wait_pending 语义不变
（抛出并清空，只消费一次）。

实测（同一批两个子步：第 1 个抛 RuntimeError('boom')，第 2 个成功）:

| | wait_pending 结果 |
|---|---|
| 改前 | NO-RAISE（异常被吞） |
| 改后 | RAISE: boom；后续成功批次不重复抛 |

新测试 test_physics_pipe_errors.py::1a/1b 锁定。

---

## 5. [P1] stop() join 超时不校验 → 线程存活时销毁桥

位置: physics_pipe.py::stop（旧 109-116）+ loom_physics.py（旧 585-596）

根因: join(timeout=2.0) 返回后不查 is_alive()，超时被静默忽略；
随后 _destroy_phys_bridge 直接 br.destroy()，物理线程仍持有 Jolt 世界
→ use-after-free 风险。

改法:
- PhysicsPipeThread.stop(timeout=2.0): join 后复查 is_alive()，仍存活则
  置 _degraded=True 并抛 RuntimeError；
- _stop_phys_pipe() 返回 bool：超时 → 保留 _phys_pipe 引用（供重试 join）、
  置 _pipe_disabled=True（调度切串行）、返回 False；
- _destroy_phys_bridge(): _stop_phys_pipe() 为 False 时拒绝销毁桥并
  抛 RuntimeError 给上层；线程确认退出后才 destroy；
- 默认销毁（播放结束）清本场禁用标志，下一场可重试建桥。

实测（子步阻塞在 pre_step，stop(timeout=0.2)）:

| | 是否抛错 | stop 后线程存活 |
|---|---|---|
| 改前（stop() 固定 join 2s） | 否（静默返回） | True |
| 改后 | 是（RuntimeError） | True（放行后再次 stop 可确认退出） |

_destroy_phys_bridge 拒绝路径实测: raised=True, destroyed=False,
bridge 保留, _pipe_disabled=True。新测试 2a/2b/4a/4b 锁定。

---

## 6. [P1] 桥异常每帧重建（裁决 A：本场一次性 disabled）

位置: loom_physics.py::_update_physics_bridge（旧 436-443, 501-506）

根因: 异常分支只 _destroy_phys_bridge()，下一帧 update_physics 见
_phys_bridge is None + _phys_bridge_auto → 重新 _ensure_phys_bridge()。
确定性异常会逐帧"建桥→炸→销毁→再建"并逐帧刷屏。

改法（裁决 A）:
- 异常分支置 _phys_bridge_disabled=True（本场不再建桥/用桥）；
- 新增 _log_phys_bridge_failure()：每场只打印 1 条（节流）；
- update_physics 开头检查 disabled → 直接 legacy；
- _ensure_phys_bridge 建桥成功时重置日志额度；播放结束 _destroy_phys_bridge
  清 disabled（下一场可重试）。

实测（桥 ensure_models 必抛异常，连续 5 帧）:

| | ensure 调用次数 | 异常日志条数 | 后续 |
|---|---|---|---|
| 改前 | 5（每帧重建） | 5 | 每帧重建 |
| 改后 | 1 | 1 | 本场 disabled，走 legacy（重力生效 y=3→2.959） |

新测试 3a/3b/3c/3d 锁定。

---

## 7. [P2] 形态签名不含 is_trigger

位置: physics_bridge.py::_entry_signature（旧 673-689 / 752-760）

改法: 签名加入 bool(collider.is_trigger)。播放中勾/取消 Trigger 会触发
差量重建（Jolt is_sensor 与模型一致）。

实测（建体后 is_trigger=True，ensure_models）:

| | created/destroyed/rebuilt |
|---|---|
| 改前 | (0, 0, 0)（不重建） |
| 改后 | (0, 0, 1)（重建 1 个） |

新测试 5 锁定。

---

## 8. [P2] 移除体不清理 _last_sync

位置: physics_bridge.py::ensure_models（旧 811-819）

改法: 移除分支与重建分支对称 self._last_sync.pop(id(model), None)；
并在每次 ensure_models 末尾清掉已不在场景中的模型同步基线（含无碰撞体
祖先），防 id() 复用后陈旧 sync 造成漏脏。

---

## 9. [P2] _tree_bit 不回收（裁决 A：回收树位）

位置: physics_bridge.py（旧 646-670, 811-819）

改法:
- 新增 _tree_ref（id(root) → 存活体引用计数）与 _release_tree(ent)；
  体销毁（移除/重建/静态升级）时递减，最后一个体销毁则回收位；
- _tree_bit_for 改为按"当前空闲位"分配（旧实现用 len(dict) 取位，
  回收后会与存活树撞位）；>32 棵存活树才轮转位 + 每场最多 3 条警告。

实测（两棵根树，移除其中一棵的体）:

| | 移除后 _tree_bit 数量 |
|---|---|
| 改前 | 2（位泄漏） |
| 改后 | 1（回收；重新建树分配不同位，不撞位） |

新测试 6a/6b/6c 锁定。

---

## 10. [P2] 重建体丢角速度/睡眠态

位置: physics_bridge.py::_build_one（旧 761-767 / 832-838 / 958-969）

改法: 新增 _capture_runtime(ent) 在 destroy 前抓 get_angular_velocity +
is_active；_build_one(..., carry=...) 建体后 set_angular_velocity 并按
旧激活态 activate/deactivate。ensure_models 重建分支与 pre_step 静态
升级分支都传入 carry；旧体睡眠时重建体 guard_left=0（不把继承来的睡眠
再次唤醒）。首次建体（carry=None）保留原 P2 浮空保底 activate 语义。

实测（体 ω=(0,5,0) + deactivate，改摩擦触发重建）:

| | 重建后角速度 | 重建后激活态 |
|---|---|---|
| 改前 | (0.0, 0.0, 0.0) | True（被唤醒） |
| 改后 | (0.0, 5.0, 0.0) | False（保持睡眠） |

新测试 7a/7b 锁定。

---

## 11. [P2] physics_glue 无前置校验（静默 rc=0）

位置: physics_glue.py（旧 34-78）

改法: 新增 _check_vec(name, arr, dtype, n, cols)：断言 numpy.ndarray、
一维（速度数组为 (n,3)）、dtype（float64/uint8）、C 连续、长度一致；
失败抛 ValueError。pre_step/post_step/substep_loop 全部先校验再传裸指针，
n==0 也不再绕过校验静默返回 0。substep_loop 另校验 num_substeps 为整数。

实测（float32 速度数组 / 长度不一致）:

| | 改前 | 改后 |
|---|---|---|
| float32 lin_vel | rc=0（静默，C 按错步长读） | ValueError |
| 标志数组长度 n-1 | rc=0（越界读） | ValueError |

新测试 8a-8g 锁定。tests/_tmp/physics_dll_val_check.py 的
pre_step/post_step/substep_loop 逐位对拍仍全部 diff=0.000e+00。

---

## 12. [追加] quat_to_euler_batch 万向锁符号 bug（与 F9 matlib 同款）

位置: physics_bridge.py::quat_to_euler_batch

根因: |cos β|<1e-9 分支对 β=+90° 与 β=-90° 都取
alpha=atan2(R[1,0], R[1,1])。β=-90° 时正确取法是
atan2(-R[1,0], R[1,1])（matlib.decompose_euler 的 P-13/P-14 修复同款）。

改法:
- 按 β 符号取 s = +1 / -1，alpha=atan2(s*R[1,0], R[1,1])；
- 另发现 quat→matrix 往返在真奇点会把 asin 参数压到 1-1.1e-16
  （cos β≈1.5e-8 > 1e-9，锁分支根本不命中，回读仍是错解）。增加
  "asin 参数饱和到 1-1e-12 内 → 吸附 ±90°"，让锁分支真正命中；
- β=+90° 的取法与旧实现逐位一致（s=+1），既有结果不变。

改前/改后实测（euler=(0.3, ±90°, 0) → quat → euler → 矩阵，最大误差）:

| 用例 | 改前 | 改后 |
|---|---|---|
| β=+90° | 0.000e+00（既有结果） | 0.000e+00（不变） |
| β=-90° | 5.910e-01（alpha 符号反，-0.3 vs +0.3） | 0.000e+00（alpha=+0.3） |
| β=-90°, γ=0.7（近奇点） | 2.597e-01 | 1.110e-16 |

新测试 9/9b/9c 锁定（往返矩阵误差 <1e-6；β=+90° 既有 alpha 不变）。

---

## 新增测试

- tests/test_physics_body_init.py（23 项）：初始旋转/位置不被写回、
  旋转父下子体局部旋转、偏心网格不瞬移、父无碰撞体时子跟随、
  is_trigger 重建、树位回收、角速度/睡眠态继承、glue 校验、万向锁。
- tests/test_physics_pipe_errors.py（9 项）：子步异常不被覆盖且只消费一次、
  join 超时被检测、桥异常本场 disabled + 日志节流、线程未退出拒绝销毁桥。

tests/run_all.py 自动收集（test_*.py glob），本轮 exit=0。

---

## 遗留 / 新发现（未改，超出允许文件范围）

1. scene_driver.py::_step_physics（744-758）与旧 loom_physics 同款：
   桥异常每帧 print 且不置 disabled（渲染驱动路径，非编辑器路径）。
   本次未改（不在允许文件清单），建议后续按第 6 项同款处理。
2. tests/_tmp/phys_dmb_equiv_check.py 全部断言 PASS，但末尾 print("✅")
   在 GBK 控制台抛 UnicodeEncodeError → 进程 exit=1（既有探针未做
   UTF-8 reconfigure，非本次改动引入；不作为 run_all 收集项）。
3. 万向锁锁阈值 1e-9 对"矩阵直解"够用，但对"quat→matrix→euler"路径偏严
   （往返噪声 ~1.5e-8）；本次用"饱和吸附 ±90°"解决，未改 matlib 侧。
