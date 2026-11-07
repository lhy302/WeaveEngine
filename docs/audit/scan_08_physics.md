# 物理（physics_bridge / loom_physics / physics_pipe / physics_glue / parallel）扫描报告

> 审计协议：docs/audit/SCAN_PROTOCOL.md（2026-11-07，只读审计）
> 方法论依据：桌面《论如何正确的 vibe coding》《论如何使用 AI 自动化工具正确的判断 AI 给出的黑盒是否符合设计标准》
> 审计对象工作区：D:/my-project - 副本/Loom(py源代码-工作区)/Loom
> 审计日期：2026-11-07

## 0. 范围与方法（文件清单 + 行数 + 跑过什么命令）

### 0.1 文件清单（HEAD = 4f4665011e7891d221934ac0300ef42544eab90d）

| 文件 | 行数 | HEAD blob sha1 | 工作区 blob sha1 |
|---|---|---|---|
| Loom/physics_bridge.py | 1194 | 644e22cf6683b9de5ecc0bbf8376af0f57585fbc | 同 HEAD |
| Loom/loom_physics.py | 911 | 6ce5f544361bf33e3134704973f394dd2a9a01df | 同 HEAD |
| Loom/physics_pipe.py | 116 | 530c66332cacbdf1e36b573181b35487154e7c3f | 同 HEAD |
| Loom/physics_glue.py | 83 | f1caf47ac044a073e9f0b3753c1b3442355f006a | 同 HEAD |
| Loom/parallel.py | 536 | e22036d775f9ebef6b0f4d9cbe0cab1af82b928c | 同 HEAD |

合计 2840 行。附带读取（只读、不判定、用于确认契约与调用方）：core_components/physics/loom_physics.c、core_components/loom_module.h、engine.py（_logic_frame / update_physics 调用点）、editor.py（toggle_trigger）、ui/loom_gui.py（检查器）、sceneio.py、matlib.py、loom_components.py、tests/test_physics*.py。

### 0.2 [REGRESSION] 专项：git diff 结果

    cd "D:/my-project - 副本/Loom(py源代码-工作区)/Loom"
    git diff HEAD --stat -- physics_bridge.py loom_physics.py physics_pipe.py physics_glue.py parallel.py
    # 输出：（空）
    git status --porcelain -- physics_bridge.py loom_physics.py physics_pipe.py physics_glue.py parallel.py
    # 输出：（空）
    git hash-object <每个文件>  ==  git ls-tree HEAD 的 blob   （5/5 全部相等，见 0.1 表）

结论：**本模块 5 个文件相对 HEAD 零改动**，本轮"Vulkan 对齐"未触碰物理模块，因此本报告不存在"由本轮 diff 引入"的 [REGRESSION] 项（统计见 §3.3）。

为避免"零 diff 就交差"，我对本模块的**跨模块依赖面**逐个复核了 diff：

| 依赖 | 是否被本轮改 | 与本模块相关的改动 | 判定 |
|---|---|---|---|
| pipeline_glue.py（physics_bridge 用 local_matrices / dirty_mask） | 是（+5 行） | 只在 light_vps 加 aabb_rows is None 早退，未触及 local_matrices / dirty_mask | 无影响 |
| engine.py（物理调用点 _logic_frame / update_physics） | 是 | git diff 过滤 phys/pipe/gravity **无命中行** | 无影响 |
| fastpath.py、ckernels/、core_components/pipeline/ | 否 | — | 无影响 |
| scene_driver.py（Vk 播放器，串行调 br.pre/step/post） | 是（+489 行） | 物理调用序列仍是 ensure_models -> pre_step -> step -> post_step（scene_driver.py:586-589），参数与桥契约一致 | 无回归；但**会复现本报告 P-07/P-08**（见 §3.3 备注） |

### 0.3 事实基线：定向回归测试（未跑全量 tests/run_all.py）

    $env:LOOM_NO_SAVE_MIGRATE='1'; $env:PYTHONIOENCODING='utf-8'
    python tests/test_physics.py            -> 总结果: ALL PASS ; exit=0
    python tests/test_physics_runtime.py    -> 总结果: ALL PASS ; exit=0
    python tests/test_physics_bridge.py     -> 总结果: ALL PASS ; exit=0（22 条 PASS，含 10a 停止=3.633s / 11 落定入眠 / 12a 自由跌落 4.982m）

基线结论：当前物理模块的既有用例全绿。下面所有 P-PROVED 项都是**既有用例覆盖不到的路径**（新证据，不是"测试挂了"）。

### 0.4 探针目录与命令（全部在临时目录，未写入仓库）

探针目录：C:/Users/Administrator/AppData/Local/Temp/phys_audit（脚本自包含；common_fake.py 提供鸭子类型模型/网格/碰撞体/刚体，与 physics_bridge 的"零 GL、按鸭子类型"契约一致，不需要 engine/GL 窗口）。

    $env:LOOM_NO_SAVE_MIGRATE='1'; $env:PYTHONIOENCODING='utf-8'
    python probe_a_diff_sync.py        # P-04 / P-05 初筛：is_trigger 签名、_last_sync 清理
    python probe_a2_rebuild.py         # P-05 / P-06 / P-09：同步字典无界增长、树位轮转、重建丢角速度
    python probe_bcd_pipe.py           # P-01 / P-02 / P-03 初探（race / 吞错 / stop）
    python probe_b2_race.py            # P-01 定案：S1 假同步（受控放大竞态窗口）
    python probe_d2_stop.py            # P-03 定案：stop() 超时后并发 step + destroy 在飞
    python probe_ef_glue.py            # P-10：physics_glue 入参契约（长度/dtype/连续性）
    python probe_g_rebuild_loop.py     # P-11：桥异常 -> 每帧重建桥+线程
    python probe_ij.py                 # P-16 反解自洽 / P-17 FramePool 释放语义
    python probe_k_initial_rot.py      # P-07：建体 identity 旋转 + _last_sync 预置 -> 初始旋转被抹平
    python probe_k5_offset.py          # P-08：偏心网格 -> 首帧瞬移
    python probe_l_parent_sync.py      # P-12：父无碰撞体 -> 子体不同步
    python probe_h_pairvec.py          # P-14：_pair_overlap_vec 与标量等价（780 对 + 边界）
    python probe_h5.py                 # P-14 方向交换复核

环境：Python 3.12.10 / numpy / culverin 0.14.0（gil-enabled, double-precision, release）/ Windows。

### 0.5 只读自证

- 审计前 git status --porcelain（受跟踪部分）：14 个 M + 11 个 staged D（均为其它模块/历史遗留），与审计后**逐行一致**。
- 审计后唯一新增是未跟踪文件 docs/audit/scan_08_physics.md（本报告，位于工作区级 docs/audit，与 scan_01 / scan_02 同目录）。
- 5 个受审计文件 git status --porcelain 恒为空；未跑 tests/run_all.py；三个定向测试运行前后 tests/_tmp 无新增（最后修改时间均早于本轮 30 分钟）。
- 未启动任何常驻 GUI 窗口；探针全部 headless。

---

## 1. 粗筛清单（含跳过项留痕）

六类标签：契约 / 不变量 / 错误模型 / 资源边界 / 并发 / 边界输入（协议 §1）。P-13..P-16 为阶段二"证伪成功"回填项，P-20 为探针不足项。

| ID | 位置 | 标签 | 初步方向（一句话，指向代码事实） | 结论 |
|---|---|---|---|---|
| P-01 | physics_pipe.py:74-81 | BND-CONCURRENCY | _done.set() 在 with self._lock 之外，post() 的 _done.clear() 可插在 pending 归零与 set 之间 | PROVED P2 |
| P-02 | physics_pipe.py:71-73,97-99 | SEM-SILENT | 成功子步执行 self._err = None，会覆盖前序子步的异常 | PROVED P1 |
| P-03 | physics_pipe.py:109-116 + loom_physics.py:585-596 | BND-CONCURRENCY / IFACE-LIFECYCLE | stop() 的 join(timeout=2.0) 返回值不校验，超时后桥仍被销毁且引擎转主线程串行 | PROVED P1 |
| P-04 | physics_bridge.py:673-689 / 752-760 | SEM-MISMATCH | 形态签名不含 is_trigger，而 is_sensor 只在 create_body 生效（culverin 无 set_sensor） | PROVED P2 |
| P-05 | physics_bridge.py:811-819（对照 835） | BND-RESOURCE | 移除体分支不清理 _last_sync，重建分支却 pop（不对称） | PROVED P2 |
| P-06 | physics_bridge.py:646-670, 811-819 | SEM-MISMATCH / AUDIT-ASYMMETRY | _tree_bit 按"累计曾出现的根 id"分配且从不回收，>31 后轮转复用位 | PROVED P2 |
| P-07 | physics_bridge.py:756-760, 785-786, 853-855 | SEM-MISMATCH | 建体 rot=(0,0,0,1) 且 _last_sync 预置为当前位姿 -> 首帧 dirty=False -> post_step 把 identity 旋转写回模型 | PROVED P1 |
| P-08 | physics_bridge.py:756, 1164-1178 | SEM-MISMATCH | 建体位置取世界 AABB 中心（pos=c），root 回读写 lp=wp -> 偏心网格首帧瞬移 | PROVED P1 |
| P-09 | physics_bridge.py:761-767, 832-838, 958-969 | SEM-MISMATCH | 重建体只恢复 set_linear_velocity，角速度/睡眠态丢失 | PROVED P2 |
| P-10 | physics_glue.py:34-78 | IFACE-PRECOND | 只按 lin_vel.shape[0] 取 n，无 dtype/长度/连续性校验，C 端 LOOM_ERR_PARAM 的形状/dtype 语义不可达 | PROVED P2 |
| P-11 | loom_physics.py:436-443, 501-506 | IFACE-ERROR / SEM-MISMATCH | 桥步进异常只 destroy 不置 _phys_bridge_disabled -> 下一帧 _ensure_phys_bridge 立即重建 | PROVED P1 |
| P-12 | physics_bridge.py:875-915 | SEM-MISMATCH | 祖先脏传播只在 entries 内建 id2idx，父无碰撞体则 pidx=-1，父移动不会让子体脏 | PROVED P1 |
| P-13 | physics_bridge.py:1128-1136 | IFACE-PRECOND | _mu/_roll/_isd/_ug 按 len(dyn) 建，_lv/_av/_wsu 按 valid 过滤，若出现无效行则参数错位 | DISPROVED（潜在） |
| P-14 | loom_physics.py:156-188 | SEM-MISMATCH | 向量化 _pair_overlap_vec 与标量 _pair_overlap 是否逐位等价 | DISPROVED |
| P-15 | physics_pipe.py:36-41, 66-68 | SEM-MISMATCH | _batch_first 只在批首 ensure_models，跨帧连发时会漏掉结构变更 | DISPROVED |
| P-16 | physics_bridge.py:1167-1176 | IFACE-UNIT | 有父体回读时 Rl = Rw @ inv(world_rotation_3x3(p)) 的往返是否自洽（父级非均匀缩放+旋转） | DISPROVED |
| P-17 | parallel.py:322-361 | 资源边界 / 生命周期 | FramePool.shutdown(wait=False) 不取消排队任务、worker 非 daemon | PROVED P3 |
| P-18 | engine.py:994-996,1013-1014 + loom_physics.py:581 | AUDIT-DOCIMPL | 管道超时永久降级无任何用户可见示踪（HUD 只看 _phys_pipe_sysfail，后者只在建线程失败时置位） | PROVED P3 |
| P-19 | physics_glue.py:13-33,36,51,66 / physics_bridge.py:1138-1139 / physics_pipe.py:63 | AUDIT-DEADCODE | 只写不读的 _STATE 字段、未使用的 numpy import、不可达的 rc 分支、未被使用的 job 第 4 元 | PROVED P3 |
| P-20 | engine.py:998-1017（与本模块 pre/post 并发） | BND-CONCURRENCY | 批6 流水线在 wait_pending() 之前跑 update_animations，动画写 m.position/rotation，与物理线程 pre/post 的读写无同步 | P-UNKNOWN |

### 1.1 跳过登记表（每项给出四类理由之一的出处）

| ID | 位置 | 跳过理由类型 | 具体出处 / 事实 |
|---|---|---|---|
| SKIP-01 | loom_physics.py:132-154 _pair_overlap 三种几何 | 已有回归测试覆盖 | test_physics_bridge.py 我实跑 ALL PASS，case_land（球落盒停点）、case_same_tree（5a 父子穿模 / 5b 异树被挡）、case_kinematic（挡停不穿模）直接依赖该判定；同时与 physics_bridge.py:263-284 逐语句同构（可 diff）。 |
| SKIP-02 | loom_physics.py:290-372 _push_out 最小穿透轴 | 白盒契约明确 + 间接覆盖 | 注释给出闭式语义（每轴最小位移、取较小者、零厚盒不退化），实现与 physics_bridge.py:331-407 同构；case_land/case_kinematic 的落点与挡停数值（y=-0.019、dyn x=4.000）间接锁定。 |
| SKIP-03 | physics_bridge.py:452-550 欧拉/四元数转换 | 已有回归测试覆盖 | case_r4 我实跑：点旋转 Δ=0.00e+00、往返 Δ=2.22e-16。**留痕**：万向锁分支（|cos beta|<1e-9）无独立用例，属覆盖率缺口（非 bug，登记 P3 建议）。 |
| SKIP-04 | loom_physics.py:610-647 并行/池阈值常量 | 白盒契约明确 | 全部是性能闸门（_AABB_POOL_THRESHOLD 等），不参与正确性判定；注释中的性能数字属调优记录，本轮不审计"性能声明是否属实"。 |
| SKIP-05 | parallel.py:24-114 CPU 拓扑结构体 | 工具/框架自身声明 | 结构体布局出自 Windows SDK winnt.h（注释给出偏移），且 detect_topology 全路径 try/except 回退 _fallback_count，失败只降级为不绑定。 |
| SKIP-06 | parallel.py:119-224 mask_of/compute_policy/apply_* | 语言规范保证 + 白盒契约 | mask_of 对 max(ids)>=64 返回 0 放弃绑定；compute_policy 显式"至少留 1 个大核"；apply 失败只返回 False。纯函数、无副作用。 |
| SKIP-07 | parallel.py:447-536 MainThreadCoreScheduler | 工具自身声明 | OpenThread+SetThreadAffinityMask 失败即返回 False（_pin_main 全包 try）；disable_pin 供测试。另核对：CPython/Win32 下 threading.get_ident() 返回原生线程 id，OpenThread 可用（非缺陷）。 |
| SKIP-08 | loom_physics.py:871-893 C 一体内核分支 | 白盒契约明确（退役纪律） | ex[0] is None / res_c is None 的硬 raise 由 B1/B2/B5 退役文档规定；数值等价由既有碰撞用例间接覆盖。 |
| SKIP-09 | parallel.py:403-444 NtQuerySystemInformation 采样 | 工具自身声明 | 只读诊断，失败返回 None（_rebalance 直接 return），不改变线程亲和以外的任何状态。 |
| SKIP-10 | physics_glue.py:64-78 substep_loop | 无生产调用方（不可达） | 全库 grep：唯一调用在 tests/_tmp/physics_dll_val_check.py:173；生产桥只走 pre_step/post_step。登记为 P-19 死代码观察，不作为 bug。 |
| SKIP-11 | physics_bridge.py:143-258 顶点/矩阵缓存 | 白盒契约明确 | 缓存键含对象身份（id(mesh)+mesh.vertices 身份），且 _tmp_cache 在每次 pre_step/post_step 开头 clear（930-931、1096-1097），不存在跨帧陈旧。 |

---

## 2. 逐项裁决（8 段式：位置 / 契约 / 路径枚举 / 实际 / 差异 / 触发 / 验证 / 等级）

### P-01（PROVED P2）S1 同步点假同步：_done.set() 在锁外

**1) 位置**：physics_pipe.py:74-81（worker finally 段）、83-89（post）、91-99（wait_pending）。

**2) 契约/预期**：模块 docstring（physics_pipe.py:5-11）声明"主线程 post 提交子步后不等待 … 到真正需要物理结果的同步点 (S1) 才 wait_pending()"，即 wait_pending 返回后**所有已提交子步已完成**，主线程才读模型属性。

**3) 路径枚举**（_done 的全部写点 + 等待点，共 4 条）：

    (a) post():  with lock: jobs.append; _pending += 1; _done.clear(); _go.set()
    (b) worker:  finally: with lock: _pending -= 1; empty = _pending <= 0
                 if empty: _batch_first = True; _done.set()      <- 在 lock 之外
    (c) stop():  不触碰 _done
    (d) waiter:  wait_pending(): self._done.wait(timeout)

    路径 1：post 仅在 worker 空闲（_pending==0 已 set）后发生 -> clear 后 worker 重新 set -> 正确。
    路径 2：post 发生在 worker 取活之后、_pending 归零之前 -> 归零判断为 False -> 不 set -> 正确。
    路径 3：post 发生在 (b) 的"归零判断为 True"与 "_done.set()" 之间（跨线程无锁窗口）-> post 先 clear，
            随后 worker 的 set 把"仍有 1 个在飞子步"的状态标成"已清空" -> wait_pending 立刻返回。**命中**。
    路径 4：stop() 之后 post（引擎不会：_pipe_disabled 保护）-> 无影响。

**4) 实际行为**：路径 3 下 wait_pending 在最后一个子步仍于 C 层 step 中时返回；主线程开始读 m.position/rotation，而 worker 随后在 post_step 写同一批属性（无锁）。

**5) 差异**：预期"返回即队列清空"，实际"返回时队列仍非空（pending=1）"。

**6) 触发条件**：主线程 post(k+1) 恰好落在 worker 完成子步 k 的"pending 归零 -> set"之间。窗口只有两条字节码（释放锁到 set），约 µs 级；批6 的连发模式（engine.py:1002-1003 的 for _ in range(nsub): pipe.post(...)）提供了物理上必需的调用序列，是否命中取决于单子步耗时是否短于 post 循环步进（空/少动态体场景 step 仅数 µs 时成立）。

**7) 验证**（探针受控放大该窗口，不新增窗口；放大手段 = 包一层 Event，使 set() 在"归零之后"阻塞到主线程完成第二次 post）：

    python $env:TEMP/phys_audit/probe_b2_race.py
    PROBE B2 wait_pending() 返回: 耗时=0.000s 已完成子步=1/2 pending=1 第2子步在飞行中=True

  对照：把 set() 移进锁内则窗口消失（本次未改源码，仅由路径枚举与放大实验确认）。

**8) 影响与等级**：主线程与 worker 对同一批模型位姿的并发读写（撕裂读：Point3D 三次赋值可被读到半新半旧）；该子步物理结果被推迟一帧。P2（时序/数据一致性，命中概率低）。

### P-02（PROVED P1）前序子步异常被后续成功覆盖（静默丢步）

**1) 位置**：physics_pipe.py:64-73（try/except），71（self._err = None），76-81（finally），97-99（wait_pending 抛错）。

**2) 契约**：模块 docstring 第 14 行"超时降级 … 调用方永久降级主线程直跑"；类内契约"pending 计数队列（多子步连发不丢步）"（第 9 行）。wait_pending 是 S1 唯一的错误出口（97-99 行）。

**3) 路径枚举**：
    路径 1：单子步且失败 -> _err=e，pending 归零 -> set -> wait_pending 抛 e。正确。
    路径 2：末子步失败 -> _err 保持 e -> 抛。正确。
    路径 3：前序子步失败 + 后续子步成功 -> 后续成功执行 self._err = None（71 行）-> 抛不出来。**命中**。
    路径 4：全部成功 -> _err=None -> 不抛。正确。

**4) 实际行为**：3 个子步、第 1 个抛异常时，wait_pending 不抛，只有 2 个子步真正推进。

**5) 差异**：预期"任一子步失败必须报错并按 P2 契约降级"，实际"错误被吞，管线继续使用"。

**6) 触发条件**：逻辑帧内 nsub>1（core_clock 子步数 >=2）且中间某个子步的 pre/step/post 抛一次（非持续性）异常。

**7) 验证**：

    python $env:TEMP/phys_audit/probe_bcd_pipe.py
    PROBE C 3 子步, 第 1 个抛异常 -> wait_pending 未抛 (错误被吞); 实际执行成功子步=2/3
    PROBE C 末子步失败 -> 抛出 RuntimeError('injected failure on substep 2') (符合契约)

  对照：末子步失败路径确实抛（证明检测链本身有效，只是被 71 行覆盖）。

**8) 影响与等级**：静默丢一步物理（该步位移/接触/重力全部缺失）；引擎因此不会执行 engine.py:1011-1014 的降级分支，继续用可能已坏的管线。P1（功能错误 + 静默失败）。

### P-03（PROVED P1）stop() 超时后仍并发 step，且桥销毁发生在飞行中的 step 期间

**1) 位置**：physics_pipe.py:109-116（stop）、loom_physics.py:585-596（_destroy_phys_bridge）、599-608（_stop_phys_pipe）、engine.py:1009-1017（超时 -> _stop_phys_pipe + _pipe_disabled -> 下一帧串行）。

**2) 契约**：loom_physics.py:588 注释"分离批4: 先停物理线程再销毁桥 (线程持有 _w 引用, 顺序不可反!)"；physics_pipe.py:110 注释"停止: 哨兵 -> join. 幂等"。

**3) 路径枚举**：
    路径 1：worker 空闲或在 µs 级子步内 -> join 正常结束 -> 顺序成立。正确。
    路径 2：worker 正在执行 >2s 的子步 -> join(2.0) 超时返回，stop() **不检查 is_alive**，调用方认为已停 -> 紧接着 br.destroy()（_w=None）+ 引擎下一帧在主线程对同一 br 调 pre/step/post。**命中**。
    路径 3：worker 在 stop() 的 _jobs=[] 之后仍持有一个已 pop 的 job（一次 step）-> 同上。
    路径 4：stop() 时 _pending 被置 0，worker 完成当前 job 后再 _pending-=1 -> -1；empty=True -> _done.set()，随后检查 _stop 退出。无额外危害（仅计数为负）。

**4) 实际行为**（探针 D2，FakeWorld 在 step 内记录并发进入数，模拟 2.5s 单子步）：

    PROBE D2 stop() 返回耗时=2.00s (join timeout=2.0s)
    PROBE D2 返回时 worker 线程存活=True, world 内正在 step=True
    PROBE D2 主线程串行 step 时 world 最大并发进入数=2 (1=安全, 2=并发步进同一 Jolt world)
    PROBE D2 事件时间线=[('enter', -0.2, 'loom-physics'), ('enter', 2.0, 'MainThread'),
                          ('step-after-destroy', 2.3, 'loom-physics'), ('step-after-destroy', 4.5, 'MainThread')]
    PROBE D2 destroy() 之后仍完成的子步数=2

**5) 差异**：预期"stop() 返回 = 线程已退出 = 可以 destroy/改串行"，实际"返回时线程仍在 step，destroy 之后仍完成 1 个子步"。

**6) 触发条件**：任一逻辑帧物理耗时 > 2s（超大场景、Jolt 内部线程池争用、断点/挂起）叠加 wait_pending 1s 超时（超时 -> 引擎 _stop_phys_pipe + _pipe_disabled -> 下一帧主线程串行）。

**7) 验证**：同 4)；复跑 python probe_d2_stop.py（约 2.6s）。

**8) 影响与等级**：culverin/Jolt 的 PhysicsWorld 不保证多线程并发 step 安全；并发进入同一 world 的后果是原生崩溃/状态损坏（本地以 FakeWorld 复刻并发进入，未触发真实崩溃——真实崩溃需构造 >2s 的 Jolt 子步，本轮只做只读取证，未在真实 Jolt 上压测）。P1。

### P-04（PROVED P2）is_trigger 不在形态签名 -> 运行时切换触发器不重建 sensor 体

**1) 位置**：physics_bridge.py:673-689（_entry_signature）、752-760（_build_one 的 is_sensor）、801-841（ensure_models 差量）。

**2) 契约**：_entry_signature 的注释标题即"形态签名 (ensure_models 差量)"，且 676-678 行明确"数值字段用 float() 而非 bool() 参与签名 —— 原 bool() 区分不了 0.5 vs 0.2 的摩擦改动 (播放期调摩擦不会重建体)"，即**凡是影响建体形态的字段都必须进签名**。loom_components.py:144-148 定义 is_trigger=True -> 物理层传 is_sensor -> 不产生接触力、可重叠穿过。

**3) 路径枚举**：
    路径 1：建体前设定 is_trigger -> create_body(is_sensor=...) 生效。正确。
    路径 2：建体后修改 is_trigger -> 签名不含该字段 -> sig==ent['signature'] -> 不重建 -> 实体保持原有 sensor 属性。**命中**。
    路径 3：同时改 shape/friction 等 -> 重建 -> 新的 is_sensor 生效（巧合正确）。
    路径 4：culverin 侧有无 set_sensor 补救？hasattr(cv.PhysicsWorld,'set_sensor') == False（实测）。走不通。

**4) 实际行为**：

    PROBE A1 切换 is_trigger 后 ensure_models -> created=0 destroyed=0 rebuilt=0
    PROBE A1 signature 变化: False (False=未感知)
    PROBE A1 旧签名=('box', True, 0.5, 0.0, 0.1, None)
    PROBE A1 新签名=('box', True, 0.5, 0.0, 0.1, None)
    PROBE A1 反向再切一次 -> rebuilt=0
    PhysicsWorld 是否有 set_sensor: False

**5) 差异**：预期"is_trigger 改动最终反映为实体 sensor/实心状态变化"，实际"物理实体不变"；而事件层 loom_physics.py:92-99（_is_trigger_pair）是**实时**读 is_trigger 的，于是同一次改动在"事件分流"里立刻生效、在"物理接触"里永不生效。

**6) 触发条件**：播放中由脚本/EAI/编辑器命令修改 collider.is_trigger（editor.py:1545-1550 提供该命令；GUI 检查器在播放中被禁用——见 loom_gui.py:2352-2353，但脚本路径不受此限制）。

**7) 验证**：同 4)；复跑 python probe_a_diff_sync.py。

**8) 影响与等级**：事件说"进入触发器"，物理上却仍然挡人/产生接触力（Unity 语义下不可能同时成立）。P2（需运行期修改，脚本路径可达；GUI 路径当前被播放态禁用）。

### P-05（PROVED P2）移除体不清理 _last_sync（重建分支清理、移除分支不清理）

**1) 位置**：physics_bridge.py:811-819（移除分支）、832-838（重建分支，835 行 _last_sync.pop）、638-643（destroy 清理）。

**2) 契约**：_last_sync 的定义为"id(m) -> [pos3, rot3, vel3]（float 元组）"，是模型位姿与实体位姿的差分基准；rebuild 分支显式 pop 说明"实体不存在时基准必须失效"。

**3) 路径枚举**：
    路径 1：模型仍在 models -> 保留条目。正确。
    路径 2：模型被移除 -> destroy_body + entries 移除，但 _last_sync 保留。**命中**。
    路径 3：rebuild -> pop 后 _build_one 重新写入。正确（与路径 2 不对称）。
    路径 4：destroy()（播放结束）-> _last_sync.clear()。正确，但只发生在整场结束。

**4) 实际行为**（探针保留被移除模型的引用，模拟编辑器 undo 栈/脚本缓存持有对象，防止 id 复用掩盖增长）：

    PROBE A2' 50 轮 建/删 后: 活跃体=1 _last_sync=51 _tree_bit=51 body_count=1
    PROBE A2' 已移除但仍在字典里的 sync 条目数=50
    PROBE A2' 重建分支后该模型仍在 _last_sync: True (rebuild 会 pop 再重建)

**5) 差异**：预期"活跃体数 == 基准条目数"，实际"基准条目数随累计建体次数单调增长"。

**6) 触发条件**：同一播放会话内反复 add/remove 模型（刷怪、销毁子弹、预制体实例化），且被移除对象仍被外部引用（undo 栈、脚本列表、事件闭包）。

**7) 验证**：同 4)；复跑 python probe_a2_rebuild.py。

**8) 影响与等级**：内存随累计建体数线性增长（每条约 200B，10 万次建删约 20MB 级）；且被移除模型的 id 若被新对象复用，新对象会继承旧基准（本次探针中 id 复用导致字典反而"不再增长"，说明两条路径都有问题：不复用时泄漏、复用时串用基准）。P2（资源边界）。

### P-06（PROVED P2）_tree_bit 按累计根数分配且不回收 -> >31 根树后静默共用 category 位

**1) 位置**：physics_bridge.py:646-670（_root_of / _tree_bit_for）、811-819（移除分支不释放 bit）。

**2) 契约**：类 docstring 第 34-36 行"树位: 每根根树 1 位 category … >31 根轮转位+警告（收窄项=表亲同树不再互撞, 已列人工裁决）"——契约承诺的是"**同时在场的根树** >31 才轮转"。

**3) 路径枚举**：
    路径 1：根 id 已有 bit -> 复用。正确。
    路径 2：新根且 t=len(_tree_bit) <= 31 -> bit=1<<t。正确。
    路径 3：新根且 t>31 -> bit=1<<(t%32)，与前 32 个根之一**共用**；由于 mask=ALL and ~bit，两棵共用位的树互检为 0 -> 不互撞。**命中**。
    路径 4：树被移除 -> _tree_bit 不删（探针证实）-> t 只增不减，轮转更容易发生。

**4) 实际行为**：

    [物理] WARN 树数>31: 第 33 根树轮转位=0b1 (与其它树共用位 -> 其间不互撞)
    [物理] WARN 树数>31: 第 34 根树轮转位=0b10
    [物理] WARN 树数>31: 第 35 根树轮转位=0b100
    PROBE A2' 50 轮 建/删 后: 活跃体=1 _last_sync=51 _tree_bit=51 body_count=1

  注意第 33 根树拿回 0b1 = 第 1 根树的位；警告计数 _warned_tree_rot 上限 3（663 行），第 36 根起**不再提示**。

**5) 差异**：预期"32 棵同时树才轮转"，实际"累计出现过 32 个根就轮转"；且轮转警告只报 3 次。

**6) 触发条件**：单次播放会话累计创建 >32 个根对象（含被销毁的），例如刷怪/关卡流式加载/预制体。

**7) 验证**：同 4)；复跑 python probe_a2_rebuild.py。

**8) 影响与等级**：两棵不相关树共用 category 位 -> 它们之间**静默失去碰撞**（不是"同树不互撞"的已知收窄，而是跨树漏检）；P2（已知设计的边界被"累计计数"提前触发，且后期无提示）。

### P-07（PROVED P1）建体用 identity 旋转 + _last_sync 预置为当前位姿 -> 动态体初始旋转被回读抹平

**1) 位置**：physics_bridge.py:756-760（create_body(rot=(0,0,0,1))）、785-786（_last_sync 预置为模型当前位姿）、853-855（_model_dirty）、950-982（pre_step 只同步 dirty）、1177-1178（post_step 写回模型 rotation）。

**2) 契约**：桥 docstring 第 9 行"本模块不改变任何契约语义, 只做 模型 <-> Jolt 世界 的每帧桥梁"；R3（29-31 行）把 identity 旋转描述为**碰撞形状的近似**（box=世界 AABB 半长 + identity 旋转），并未声明可以改写模型自身旋转。post_step 的职责是"回读解算结果"，即不应在模型位姿未被物理改变时改写它。

**3) 路径枚举**：
    路径 1：模型建体时 rotation=(0,0,0) -> identity == 模型旋转 -> 回读写 0，无害。
    路径 2：模型 rotation!=0 且首帧 dirty（脚本/动画先动过它）-> pre_step 同步世界旋转 -> post_step 读回同一旋转 -> 保持不变。探针 K4 证实。
    路径 3：模型 rotation!=0 且首帧不 dirty（只读场景、无脚本动它——最常见）-> 实体停在 identity -> post_step 的 root 分支 lp=wp、lrot=lpq（identity 反解=0）-> **模型旋转被写成 0**。命中。
    路径 4：有父链且父有旋转 -> 实体 identity，post_step 算 Rl = I @ inv(R_parent) -> 子体局部旋转被改成 inv(R_parent) 的欧拉分解。命中。

**4) 实际行为**：

    PROBE K1 建体时实体旋转=[0. 0. 0. 1.]
    PROBE K1 _last_sync 是否等于当前位姿(=>首帧不脏): True
    PROBE K K1 根动态体 初始旋转(0.4,0.2,0.1) 1帧  旋转 (0.4, 0.2, 0.1) -> (0.0, -0.0, 0.0) | 位置 (0, 3, 0) -> (0.0, 3.0, 0.0)
    PROBE K K1 再 60 帧 (是否持续)                旋转 (0.0, -0.0, 0.0) -> (0.0, -0.0, 0.0)
    PROBE K K2 球 初始 rot.y=0.9 落地 60 帧       旋转 (0.0, 0.9, 0.0) -> (0.0, -0.0, 0.0)
    PROBE K K3 子体(父旋转) 1帧                   旋转 (0, 0, 0) -> (0.08216, -0.57125, -0.64699)
    PROBE K K4 先制造 dirty 再 1 帧: 旋转=(0.4, 0.2, 0.1)     <- 对照：dirty 就保留

**5) 差异**：预期"未被物理扰动的动态体保持作者设定的旋转"，实际"首帧旋转被清零（root）/ 被改写为 inv(R_parent)（子体）"。

**6) 触发条件**：任何 rotation!=0 的带刚体模型进入播放（或 Vk 播放器 scene_driver 的同类路径）；子体场景额外需要父有旋转。

**7) 验证**：python probe_k_initial_rot.py（K4 是对照组，排除"物理真的把它转回去了"的解释：K4 里同样初始旋转、只多一次 dirty，旋转得以保留）。

**8) 影响与等级**：带旋转的动态/运动学物体在播放首帧丢失朝向（视觉 + 脚本读到的 rotation 全部错误）；同时碰撞盒是"旋转后网格的 AABB + identity"，与该近似设计一致但与模型姿态不一致。P1（功能错误，覆盖面广；既有 22 条桥用例全部把 rotation 设为 0，故无覆盖）。

### P-08（PROVED P1）建体位置取世界 AABB 中心 -> 偏心网格首帧瞬移

**1) 位置**：physics_bridge.py:731-735（box 用 AABB 中心 c）、756（create_body(pos=c)）、1164-1166（root 回写 lp=wp）、1170-1171（父体回写 lpv = wp - parent）。

**2) 契约**：同上"只做桥梁、不改语义"；模型位置的权威来源是 m.position（局部）经父链组合出的世界位置。

**3) 路径枚举**：
    路径 1：网格顶点关于原点对称（cube/sphere/plane 等内置图元）-> AABB 中心 == 世界位置 -> 回写无差异。既有用例全在此路径。
    路径 2：网格顶点整体偏心（门轴、悬臂、骨骼网格、导入模型）-> AABB 中心 != 世界位置 -> post_step 把 AABB 中心写进 m.position。**命中**。
    路径 3：子体 + 父有缩放/旋转 -> AABB 中心仍对称（对称网格）-> 无差异；偏心网格同样瞬移。

**4) 实际行为**：

    PROBE K5 建体前模型位置=V3(x=0, y=3, z=0)
    PROBE K5 Jolt 实体位置=[3. 3. 0.]
    PROBE K5 1 帧后模型位置=Point3D(x=3.0, y=3.0, z=0.0) (AABB 中心=世界原点+3)

**5) 差异**：预期"位置保持 (0,3,0)"，实际"首帧跳到 (3,3,0)"。

**6) 触发条件**：碰撞体所在网格的原点不在其包围盒中心（偏心网格）。

**7) 验证**：python probe_k5_offset.py（把 cube 顶点整体平移 +3 后建体，1 帧后模型位置被改成 3.0）。

**8) 影响与等级**：播放首帧物体瞬移（且此后以瞬移后的位置为基准继续模拟），碰撞体与视觉错位。P1（功能错误；与 P-07 同源：建体后没有用模型世界变换做一次 set_position/set_rotation，且 _last_sync 预置使首帧无法自愈）。

### P-09（PROVED P2）重建体丢角速度（任何签名变化或静态升级都会触发）

**1) 位置**：physics_bridge.py:761-767（只推线性速度 v0）、832-838（签名变 -> destroy+rebuild）、958-969（STATIC->KINEMATIC 销毁重建）。

**2) 契约**：ensure_models 注释"collider/rb 形态变 -> 重建"；重建的语义应是"换形状/材质，动力学状态延续"（否则"播放期调摩擦"会让物体凭空停转）。768-774 行注释强调新体要"activate 保证第一帧就参与模拟"，同样隐含"状态延续"。

**3) 路径枚举**：
    路径 1：不改签名 -> 不重建 -> 角速度保留。正确。
    路径 2：运行中改 rb.friction/restitution/rolling_friction/mass/use_gravity/is_kinematic 或 collider.shape/enabled -> 签名变 -> rebuild -> 新体角速度=0。**命中**。
    路径 3：静态体被脚本移动 -> pre_step 升级重建 -> 新体角速度=0（静态体本无角速度，影响小）。
    路径 4：睡眠态同样丢失（新体默认清醒），保底帧 guard_left 重置。

**4) 实际行为**：

    PROBE A3' 重建前角速度=array([ 0.     , 47.08462,  0.     ], dtype=float32)
    PROBE A3' 改摩擦 -> rebuilt=1; 新体角速度=array([0., 0., 0.], dtype=float32)
    PROBE A3' 角速度被清零: True

**5) 差异**：预期"改材质只影响摩擦/滚动衰减，角动量延续"，实际"角速度清零（视觉上自转/滚动体瞬间停转）"。

**6) 触发条件**：播放期修改被签名覆盖的任一字段（脚本/EAI 可做；GUI 检查器播放中被禁用）；或静态体被移动。

**7) 验证**：python probe_a2_rebuild.py（用 w.apply_angular_impulse 制造 47.08 rad/s 的真实角速度，再改 rb.friction 触发 rebuilt=1）。

**8) 影响与等级**：违反"桥只做映射、不改语义"；对滚动球/陀螺类玩法是可见的行为突变。P2（功能错误，需运行期改字段；但 pre_step 的静态升级路径使它在"移动平台"场景必然发生）。

### P-10（PROVED P2）physics_glue 无 dtype/长度/连续性校验：C 端错误码的形状语义不可达

**1) 位置**：physics_glue.py:34-46（pre_step）、49-61（post_step）、64-78（substep_loop）；对照 core_components/physics/loom_physics.c:43-50 与 core_components/loom_module.h:80-86。

**2) 契约**：loom_module.h:82 定义 LOOM_ERR_PARAM = "参数非法 (空指针/形状错误/dtype 不符)"，C 实现按该契约只检查空指针与 n<0；glue 层（"接线层"）是唯一知道 Python 侧形状/dtype 的一层，但其 docstring 没有声明入参前置条件，也没有校验。

**3) 路径枚举**：
    路径 1：float64 + C 连续 + 各数组长度==n -> 正确。
    路径 2：float32 输入 -> .ctypes.data_as(POINTER(c_double)) 把 4B/元素 的缓冲当 8B/元素 用 -> C 写越界。命中。
    路径 3：某数组长度 < n（除 lin_vel 外）-> C 按 n 循环越界读/写。命中。
    路径 4：非连续视图（负步长/切片）-> data_as 拿到基址 -> 静默操作错误的行。命中。
    路径 5：lin_vel 不是 numpy（list）-> AttributeError（不是 LOOM 错误码）。命中（契约未声明）。

**4) 实际行为**：

    PROBE F  正常 float64 (n=4) rc=0
    PROBE F1 mu 长度=1 < n=4: rc=0 (无长度校验, C 越界读 friction[0..3])
    PROBE F2 float32 输入 rc=0 -> C 按 double* 写入 (每元素 8B), 缓冲区按 4B/元素 分配
    PROBE F3 lv 视图 C_CONTIGUOUS=False strides=(48, -8)
    PROBE F4 ang_vel 只有 1 行而 n=4: rc=0 (C 越界读写 ang_vel)

**5) 差异**：预期"参数形状/dtype 不符 -> 非零 rc 或异常"，实际"rc 恒 0，越界读写发生在无人察觉处"（rc 只能反映空指针/n<0）。

**6) 触发条件**：任何新调用方（bench/探针/未来批处理）传 float32、切片视图、或长度不齐的数组。当前生产调用方（physics_bridge.py:1134-1137）显式使用 ascontiguousarray + copy + float64，因此现状不触发。

**7) 验证**：python probe_ef_glue.py。

**8) 影响与等级**：内存安全（越界写可破坏堆）+ 静默数值错误；属于"偷懒的接线层"而非"被违反的调用"。P2（当前无调用方违规，但错误模型在 ABI 上不可达，且没有任何断言兜底）。

### P-11（PROVED P1）桥步进异常后"回退 legacy"不持久 -> 每帧重建桥 + 新物理线程

**1) 位置**：loom_physics.py:491-508（except -> print -> _destroy_phys_bridge -> _update_physics_legacy）、436-443（update_physics 的 _phys_bridge_auto 重建分支）、510-545（_ensure_phys_bridge）、525/528/539（只在建桥失败时置 _phys_bridge_disabled）。

**2) 契约**：501-506 行注释"桥异常: 本帧回退 legacy 并释放桥 (静默降级, 游戏不崩; 控制台留痕)"；512 行注释"建体失败 -> 置 _phys_bridge_disabled 标记, 不再重试 (legacy)"。语义应为：异常 -> 本帧 legacy，并把"不要再用桥"这件事记下来。

**3) 路径枚举**：
    路径 1：首次 update_physics，桥未建 -> _ensure_phys_bridge 建桥；若建体失败 -> _phys_bridge_disabled=True -> 永久 legacy。正确。
    路径 2：桥存在但 enabled=False -> _phys_bridge=None -> 走 legacy（随后也会重建，但 enabled=False 只可能是库缺失，此时已 disabled）。
    路径 3：桥存在且 enabled -> _update_physics_bridge 抛异常 -> except -> destroy（_phys_bridge=None，**不置 disabled**）-> legacy 本帧；下一帧 update_physics 发现 _phys_bridge is None 且 _phys_bridge_auto=True（engine.py:226 真实置 True）-> 重新建桥 + 新线程。**命中**。
    路径 4：持续性故障 -> 每帧重复路径 3。命中。

**4) 实际行为**（桩引擎 + 注入"step 必抛"的桥；桩显式置 _phys_bridge_auto=True，与 engine.py:226 的真实 __init__ 一致）：

    [物理] Jolt (Culverin) 物理桥已建立: 1 体
    [物理] 桥步进异常 (RuntimeError('C 层内部错误 (模拟持续故障)')) -> 释放桥并回退 legacy
    PROBE G 第1帧后: 桥构造=1 build=1 destroy=1 异常=1 新物理线程=1 停线程=1
    PROBE G 第2帧后: 桥构造=2 build=2 destroy=2 异常=2 新物理线程=2 停线程=2
    PROBE G 第3帧后: 桥构造=3 build=3 destroy=3 异常=3 新物理线程=3 停线程=3
    PROBE G 3 帧累计: 每帧重建桥=True 每帧新建线程=True

**5) 差异**：预期"一次异常 -> 本场播放不再用桥"，实际"每帧重建（含 N 个体 + 1 个 OS 线程），并每帧打 2 行日志"。

**6) 触发条件**：桥路径出现持续性异常（culverin 版本不匹配、世界参数非法、某体数据异常）。

**7) 验证**：python probe_g_rebuild_loop.py（monkeypatch physics_bridge.PhysicsWorldBridge / physics_pipe.PhysicsPipeThread 为记录桩）。

**8) 影响与等级**：从"降级 legacy 保命"退化成"每帧 O(N) 建体 + 线程创建/销毁 + 日志洪泛"，帧率崩塌且控制台被淹没。P1（功能/性能，且与注释承诺不符）。

### P-12（PROVED P1）父对象无碰撞体时，父移动不会让带刚体子体脏 -> 子体不跟随且局部位置被写坏

**1) 位置**：physics_bridge.py:875-915（_dirty_mask_batch：ids 只含 entries 的模型，pidx = id2idx.get(pidd, -1)）、950-982（pre_step 只同步 dirty）、1167-1176（post_step 用**当前**父矩阵把世界位置反解为局部）。

**2) 契约**：870 行注释"传播 (父脏→子脏) 结果随基础 dirty 一同缓存"（即明确承诺祖先脏传播）；pre_step docstring"① 脏检测 -> set_position/set_rotation (世界位姿, R4)"。

**3) 路径枚举**：
    路径 1：父在 entries（有碰撞体）-> pidx 指向父，C 端 dirty_mask 传播 -> 子脏 -> set_position 世界位姿。正确（探针 L 上半）。
    路径 2：父无碰撞体/碰撞体禁用/shape='none' -> 父不在 entries -> id2idx 无此 id -> pidx=-1（按"根"处理，不传播）-> 子不脏 -> 实体停在旧世界位置；随后 post_step 用**新**父矩阵反解 -> 子局部位置被改写。**命中**。
    路径 3：父自身有刚体但无碰撞体（_free 名单）-> 同样不在 entries -> 同样不传播。命中。
    路径 4：父链多级、中间层无碰撞体 -> 传播在断点处截断。命中。

**4) 实际行为**：

    PROBE L 父有碰撞体(进entries)   子局部位置 (1.0, 0.0, 0.0) -> (1.0, 0.0, 0.0) | Jolt 实体位置 [6. 0. 0.] -> [6. 0. 0.]
    PROBE L 父无碰撞体(不进entries) 子局部位置 (1.0, 0.0, 0.0) -> (-4.0, 0.0, 0.0) | Jolt 实体位置 [1. 0. 0.] -> [1. 0. 0.]
    （期望：局部保持 (1,0,0) 且实体世界位置 x 约 6.0）

**5) 差异**：父位移 +5 后，子体实体没动（应到 6.0），且模型局部位置被写成 -4.0（子体被"拽回"世界 1.0）。

**6) 触发条件**：父对象无碰撞体（空物体/动画根/装饰节点），且子对象带刚体 + 碰撞体；父被脚本/动画移动。

**7) 验证**：python probe_l_parent_sync.py（两组对照，唯一差异是父是否进 entries）。

**8) 影响与等级**：子体不再跟随父（视觉上"掉了"），局部 transform 被污染并持续；碰撞体停留在旧位置（错位碰撞）。P1（功能错误，常见结构：空物体挂刚体子件/动画根挂受击盒）。

### P-13（DISPROVED）post_step 的 _mu/_roll/_isd/_ug 未按 valid 过滤

**1) 位置**：physics_bridge.py:1109-1136。
**2) 契约**：C 端以 n = len(lin_vel) 循环读取 friction[i]/rolling_fric[i]/is_dynamic[i]/use_gravity[i]，故这些数组第 i 行必须与 _lv 第 i 行同源。
**3) 路径枚举（证伪目标：证明 valid 恒为全 True）**：
    - row_full[bid] < 0 需要 bid 不在 w.user_data 里。bid 单调分配（_next_id），user_data 取自实体。
    - 建体路径：build() 末尾 w.step(0.0) 冲刷（794-795）；ensure_models 在 created/rebuilt/destroyed 后 w.step(0.0)（817-819、839-840）；pre_step 的 STATIC->KINEMATIC 重建之后，调用方必然紧接 step(dt)（physics_pipe.py:68-70 / loom_physics.py:498-499 / scene_driver.py:587-589）-> 新建体在 post_step 前已可读。
    - 销毁路径：destroy_body 与 _entries.remove 同一次 ensure_models 内成对完成，且随后 w.step(0.0)。
    - 于是 post_step 看到的 entries 与 user_data 一一对应，valid 全 True，_mu/_roll 前 n 行与 _lv 对齐。
**4) 实际**：探针 E 对 5 种生命周期（基础球+地面 / 碰撞体禁用进出 Jolt / 静态体移动升级 / 运行时切 shape / 移除动态体）逐次记录 C 调用入参长度，全部满足 lin==ang==isd==ug==act==mu==roll：

    PROBE E 基础球+地面                 调用1次 长度组合=[(1, 1, 1, 1, 1, 1, 1)]
    PROBE E 运行时 shape sphere->box    调用2次 长度组合=[(1, 1, 1, 1, 1, 1, 1)]
    （球碰撞体禁用/静态升级/移除动态体三种状态无动态体 -> post_step 早退，C 未被调用）

**5) 差异**：无（潜在错位在当前所有路径不可达）。
**6) 触发条件**：仅当外部直接 w.destroy_body 绕过 ensure_models，或 culverin 的 user_data 行数少于 count 时才会触发——两者都不在契约内。
**7) 验证**：python probe_ef_glue.py（含 spy 包装的 E 段）。
**8) 等级**：P-DISPROVED；但建议改为按 valid 切片（_mu[valid] 等）以消除"依赖不变式"的脆弱性（P3）。

### P-14（DISPROVED）_pair_overlap_vec 与标量 _pair_overlap 的等价性

**1) 位置**：loom_physics.py:156-188（向量化）、132-154（标量）。
**2) 契约**：157-162 行 docstring"返回 bool(K), 与 _pair_overlap 逐位一致 (严格 <, 贴边不算碰撞)"。
**3) 路径枚举**：box-box / sphere-sphere / box-sphere / sphere-box 四个分支 + 严格小于边界。
**4) 实际**：780 个随机对（15 盒 / 25 球，kind 混合）+ 4 个边界用例，与标量参考逐对比对 0 不一致：

    PROBE H 随机 780 对 (box/sphere 混合): 不一致=0, 命中=76, kind 分布 box=15 sphere=25
    PROBE H 贴边 box-box (a.max==b.min=1.0): vec=False (期望 False)
    PROBE H 相切 sphere-sphere (dist=2.0=r0+r1): vec=False (期望 False)
    PROBE H 球心在盒内 (dist=0<r): vec=True (期望 True)
    PROBE H 球贴盒面外 (dist=0.05<r=0.1): vec=True (期望 True)
    PROBE H a=盒 b=球: vec=True scalar=True      （方向交换；首次探针因造数错误得 False，修正数据后一致）

**5)-7)**：无差异。
**8) 等级**：P-DISPROVED（附注：该路径仅在 n_c > 2048（A 内存兜底）或 n_pairs >= 100000（池分块）时才被使用，既有用例未覆盖；本次用直接对拍补上）。

### P-15（DISPROVED）_batch_first 只在批首 ensure_models 会漏掉结构变更

**1) 位置**：physics_pipe.py:36-41、66-68、74-80。
**2) 契约**：注释"ensure_models 只在批次首子步跑 (逻辑帧内结构不会变 …)"。
**3) 路径枚举（证伪目标：证明"新批次开始前 pending 必为 0"）**：
    - 引擎调用序列：engine.py:1001-1010 先连发 nsub 个 post，再 wait_pending()；wait_pending 只有 pending 归零才会返回（physics_pipe.py:76-81 的唯一 set 点）。
    - 因此同一逻辑帧内不会出现"上一帧的子步仍在队列"时投递下一帧子步；_batch_first 在归零时恢复 True。
    - 唯一跨帧叠加的路径是 P-01 的假同步：wait 提前返回后下一帧 post 时 pending>0。但 P-01 的后果是"少一次 ensure_models"，其触发前提已被 P-01 单列；此处不重复计为独立缺陷（且修 P-01 即消除）。
    - 超时降级路径：stop() 清空 _jobs/_pending，pipe 被弃用（_pipe_disabled=True），不会再投递。
**4)-7)**：无独立可复现反例（除 P-01 的窗口外）。
**8) 等级**：P-DISPROVED（依赖 P-01 的窗口，已并入 P-01；建议 ensure_models 的批首判据改为"逻辑帧号"而不是 pending 归零）。

### P-16（DISPROVED）有父体回读的世界->局部反解（父级非均匀缩放+旋转）是否自洽

**1) 位置**：physics_bridge.py:1167-1176。
**2) 契约**：R4/回读注释"有父: 世界 -> 局部 (逐体)"；组合式 world = local @ parent（行向量 S@R@T 链）。
**3) 路径枚举**：父无缩放 / 均匀缩放 / 非均匀缩放 / 父旋转 / 组合 / 子有初速。
**4) 实际**（每例 120 帧，子体无重力无初速，只有首帧的一次回写）：

    PROBE I 父=无缩放无旋转        局部位置漂移=0.000000 局部旋转漂移=0.000000
    PROBE I 父=均匀缩放 2          局部位置漂移=0.000000 局部旋转漂移=0.000000
    PROBE I 父=非均匀缩放 (2,1,0.5) 局部位置漂移=0.000000 局部旋转漂移=0.000000
    PROBE I 父=旋转 (0.3,0.5,0.7)  局部位置漂移=0.000000 局部旋转漂移=0.646994   <- 首帧一次性跳变
    PROBE I 父=非均匀缩放+旋转      局部位置漂移=0.000000 局部旋转漂移=0.646994
    PROBE I 父=非均匀缩放+旋转+子初速 局部位置漂移=0.000000 局部旋转漂移=0.646994

  额外验证（K3 再跑 60 帧）：跳变后的局部旋转 (0.08216, -0.57125, -0.64699) 保持不变 -> 反解本身自洽（idempotent），漂移只发生在首帧。
**5) 差异**：无往返误差；首帧跳变归因于 P-07（建体 identity 旋转 + sync 预置），不是反解公式错误。
**6) 触发条件**：如上（首帧）。
**7) 验证**：python probe_ij.py。
**8) 等级**：P-DISPROVED（父级非均匀缩放的 inv(pw[:3,:3]) 位置反解在 120 帧内零漂移）。

### P-17（PROVED P3）FramePool.shutdown(wait=False) 的释放语义

**1) 位置**：parallel.py:322-361；调用点 engine.py:1382-1389（_stop_parallel 退出链）。
**2) 契约**：FramePool docstring 只写"每帧 CPU 预计算线程池"，shutdown 注释为"shutdown(wait=False)"；未声明"排队任务会被取消"或"退出不等待"。
**3) 路径枚举**：路径 1 无在飞任务 -> 立即返回；路径 2 有排队任务 -> 不取消，worker 继续执行（非 daemon，进程退出时 atexit 会 join）-> shutdown 返回后仍有代码在跑。命中路径 2。
**4) 实际**：

    PROBE J shutdown(wait=False) 返回耗时=0.000s, 返回时任务仍在跑=True, worker daemon=[False, False]
    PROBE J 释放后任务仍完成并写状态=True (排队任务不被取消)

**5)** 预期"释放 = 不再有任务作用于旧状态"，实际"释放后任务继续读写共享数组"。
**6)** 触发条件：退出/重开时仍有预计算块在队列中（大场景 + 关闭瞬间）。
**7)** 验证：python probe_ij.py（J 段）。
**8)** 影响：退出期数据竞争窗口 + 非 daemon 线程可能延迟进程退出（若任务阻塞）。P3（当前任务只读旧数组，装载-退出场景未见可见错误）。

### P-18（PROVED P3）管道超时永久降级无用户可见示踪

**1) 位置**：engine.py:994-996（pipe_ok 判据）、1013-1014（超时 -> _stop_phys_pipe + _pipe_disabled=True）、engine.py:458/508（标志初始化/重启保留）、loom_hud.py:297（HUD 只读 _phys_pipe_sysfail）、loom_physics.py:581（_phys_pipe_sysfail 只在线程创建失败时置位）。
**2) 契约**：loom_physics.py:551-554 说明"降级主线程串行跑物理 + 醒目双语告警 + 置 _phys_pipe_sysfail 标志 (供 HUD / 状态栏暴露)"——针对线程创建失败。管道超时同样降级，但未进入该示踪链。
**3)** 路径：超时 -> _pipe_disabled=True（永久，engine.py:458 只初始化一次；play-stop 循环不重置）-> HUD 不显示。
**4)** 实际：flag 只写不读（除 pipe_ok 判定），HUD 读取的是另一个变量。**5)** 预期"用户可见的降级提示"，实际"静默永久降级"。**6)** 任意一次 wait_pending 超时。**7)** 代码事实（无需运行）：grep 结果 = _pipe_disabled 4 处（458/508/995/1014），_phys_pipe_sysfail 3 处（loom_physics 581、loom_hud 297、loom_gui 3284）。**8)** P3（可观测性）。

### P-19（PROVED P3）死字段 / 不可达分支 / 未使用入参

    物理 glue：_STATE['error'] 只在 30-32 行写 None，全库无读取；_STATE['tried'] 只写不读（13/31 行）-> handle() 的失败态从未被记录（失败直接 raise）。
    physics_bridge.py:1138-1139：if _rc != 0: raise ... 不可达 —— physics_glue.pre_step 已把 rc != 0 转成 RuntimeError（physics_glue.py:44-46）。
    physics_glue.py:36/51/66：import numpy as np 后未使用。
    physics_pipe.py:63：models, dt, g, ev = job —— ev 从未使用；engine.py:1049 固定传 False，第 4 参数是死参数。

等级：P3（可维护性；不改变行为）。

### P-20（UNKNOWN）批6 流水线：动画/脚本主线程写位姿 vs 物理线程 pre/post 读写同一批模型

**1) 位置**：engine.py:1001-1017（post 连发 -> update_audio/update_animations -> wait_pending）；physics_pipe.py:66-70（worker 内 ensure/pre/step/post）；physics_bridge.py:975-1007（pre_step 读 m.position/rotation）、1177-1187（post_step 写）。
**2) 契约**：physics_pipe.py:9-11"全部桥状态只物理线程触碰; 主线程在 S1 后读模型属性"；批6 的实现把"音频/动画"放在 S1 之前执行。
**3) 路径枚举**：只要 update_animations 写的模型与桥 entries/_free 里的模型有交集（动画驱动的父对象带动刚体子件、或动画直接驱动刚体件），两者就会对同一字段并发读写。若交集的模型全部有刚体且动画不驱动它们，则无竞争。
**4) 实际**：代码路径存在（engine.py:1006-1007 在 wait 之前），但"是否产生可见撕裂/丢更新"需要在真实引擎 + 动画场景中观测；本轮只做只读取证，未开 GUI、未跑长时播放，无法给出实测反例。
**5) 差异**：待定。
**6) 触发条件**：播放中动画/脚本在物理子步执行期间写模型位姿（尤其是物理对象本身或它的父级）。
**7) 已尝试探针**：静态代码路径枚举（engine.py 帧序 + physics_pipe worker 段）+ 桥侧确认 pre_step 读/post_step 写同一属性。缺的信息：真实播放中是否能观测到半新半旧的位姿（需要带动画的场景 + 逐帧位姿采样）。
**8) 建议下一步探针**：headless 启动 PlayerApp，造 10 个"动画父 + 刚体子"的模型，在 main 线程的 update_animations 里插入随机位移，同时 worker 侧 pre_step 记录读到的父/子位姿；统计"子体世界位姿抖动 > 1 帧位移"的次数。若为 0 则升级为 P-DISPROVED。
**等级**：待定（若可复现 -> P1 数据竞争）。

---

## 3. 统计

### 3.1 四象限

| 结论 | 数量 | 编号 |
|---|---|---|
| P-PROVED | 15 | P-01,02,03,04,05,06,07,08,09,10,11,12,17,18,19 |
| P-DISPROVED | 4 | P-13,14,15,16 |
| P-UNKNOWN | 1 | P-20 |
| P-CONTRADICTION | 0 | — |

CONTRADICTION=0 的说明（方法论要求解释）：本模块所有进入阶段二的项，证伪链要么成功（P-13/14/15/16，均给出路径枚举或随机对拍），要么在路径枚举中直接找到一条会产生疑似行为的分支（P-01/02/03 等）。后者按方法论 §5.3 的第 1 步即转入证真，因此没有出现"证伪与证真同时成功"的对峙；我没有把任何"证伪成功"的项改判为 PROVED，也没有把拿不准的项悄悄标成 DISPROVED（唯一拿不准的是 P-20，保留为 UNKNOWN）。

### 3.2 等级分布

| 等级 | 数量 | 编号 |
|---|---|---|
| P0（安全/崩溃） | 0 | — |
| P1（功能错误） | 6 | P-02, P-03, P-07, P-08, P-11, P-12 |
| P2（边界/并发/资源） | 6 | P-01, P-04, P-05, P-06, P-09, P-10 |
| P3（可维护/可观测） | 3 | P-17, P-18, P-19 |
| 待定 | 1 | P-20 |

### 3.3 [REGRESSION] 统计

| 结论 | 数量 |
|---|---|
| 本轮 diff 直接引入（本模块 5 文件） | **0**（5/5 与 HEAD 逐字节相同） |
| 本轮 diff 经依赖面间接影响本模块 | 0（pipeline_glue 仅改 light_vps 空表早退；engine.py 物理调用点零改动） |
| 因本模块缺陷而在 Vk 播放器路径复现 | 2（P-07 / P-08 在 scene_driver.py:586-589 的同一序列下同样成立） |

---

## 4. 修复建议排序（只给方向，不含代码）

**P1（先修，按影响面排序）**

1. **P-07 + P-08（同源，一次修）**：_build_one 建体后立即用模型的世界位姿 set_position/set_rotation（或在 build/ensure 后对新建体强制同步一次），并把 _last_sync 置为"实体实际位姿"而不是"模型当前位姿"；碰撞形状仍可用 AABB 近似（保留 R3 的设计），但**不得**把 identity 旋转回写给模型。验收：probe_k / probe_k5 的两个场景位置与旋转均不变。
2. **P-12**：祖先脏传播改为对"模型森林"而不是"entries 集合"建 id2idx（或按父链逐级向上找 entries 里的最近祖先）；同时 post_step 反解局部位姿时以"实体上一帧的世界位姿"为基准，避免用未同步的新父矩阵。验收：probe_l 的两组输出一致（局部 (1,0,0)、实体 x=6）。
3. **P-02**：_err 改为"首个未消费错误保持到 wait_pending"，成功路径不得清空；或按子步累积错误列表。
4. **P-11**：桥步进异常后置 _phys_bridge_disabled（本场播放不再重建），或限次重试 + 日志节流；保证"一次异常 -> 本场 legacy"。
5. **P-03**：stop() 增加 join 后的 is_alive 复查并在超时时拒绝后续 destroy/串行切换（或直接 raise 给上层的"系统极限工况"通道）；同时 _destroy_phys_bridge 需在"线程确认退出"后再 destroy。

**P2**

6. **P-04**：_entry_signature 加入 is_trigger（与 shape/enabled 同组）；或改为"建体后按 is_trigger 与实体现状比对，不一致则重建"。
7. **P-06**：_tree_bit 在模型移除时释放对应根（引用计数），并把"轮转位"的警告改成每棵新树一次 + 状态栏累计计数；树位容量需产品决策（见 §5）。
8. **P-05**：移除体分支同步 pop _last_sync（与 rebuild 分支一致），并按 entries 数量做一次防御性裁剪。
9. **P-09**：重建时把实体角速度/睡眠态搬过去（set_angular_velocity；激活态可由 is_active 决定）。
10. **P-10**：glue 增加前置断言（dtype==float64、C 连续、各数组 len==n、lin_vel 为 ndarray），失败抛 ValueError；或在 docstring 显式声明前置条件并由桥侧断言。
11. **P-01**：把 _done.set() 移进 with self._lock，并让 wait_pending 在返回前复查 _pending==0（双保险）。
12. **P-18**：管道超时降级也置 _phys_pipe_sysfail（或独立标志），由 HUD 显示"物理管线降级（性能）"。

**P3**

13. **P-17**：shutdown 用 cancel_futures=True + 明确注释"退出不等待"；或改为 wait=True 并测量退出耗时。
14. **P-19**：清理死字段/死参数/未使用 import；把 1138-1139 的不可达 rc 分支删掉或改成断言。
15. **P-13 防御化**：_mu/_roll 按 valid 切片（即使当前不可达）。
16. **SKIP-03 覆盖缺口**：给 quat_to_euler_batch 补万向锁（|cos beta|<1e-9）用例。

---

## 5. 需要人类裁决的封闭问题

**Q1（P-06 树位容量）**：category 位宽只有 32，当前实现按"累计出现过的根数"分配、且不回收。
- A. 回收树位（根被移除时释放 bit，引用计数）：改动小，但"移除后再新增"会让同一棵树的 category 位在会话内变化（需要确保没有缓存 cat/mask）。
- B. 扩到多 category 位（每个根分配多个位 / 分层 GroupFilter）：能容纳更多树，但改变碰撞过滤语义，需要重做 >31 树的回归。
- C. 维持现状，但把"累计"改成"当前在场"并把警告升级为状态栏常驻计数：最省事，仍会在 >31 同时在场的树时静默失去跨树碰撞。

**Q2（P-07/P-08 建体初值）**：是否接受"建体后立刻用模型世界变换覆盖实体位姿（并让碰撞形状仍是世界 AABB 的近似）"这一语义？
- A. 接受（推荐）：修复首帧旋转抹平/偏心瞬移，R3 的 AABB 近似保持不变（形状仍是近似，姿态正确）。
- B. 不接受：改为"播放首帧强制全量同步一次"（不重建体，只在第一帧把所有 entries 标脏）——改动更小，但首帧仍会以 identity 姿态参与一次 step(0) 冲刷。
- C. 保持现状并在文档里登记"带旋转的动态体在播放首帧会被摆正"——需要确认这是产品上可接受的行为。

**Q3（P-11 桥异常策略）**：桥步进异常后的降级应"本场一次性"还是"限次重试"？
- A. 本场一次性（置 _phys_bridge_disabled，播放停止后重建）：与现有"建体失败"纪律一致，异常场景直接走 legacy。
- B. 限次重试（例如同一场播放最多 3 次重建，超出后置 disabled）：容忍偶发异常，但每次重建有 O(N) 开销。
- C. 维持每帧重建，仅加日志节流：保持"自愈"能力，但持续性故障下帧率崩塌。

---

## 附录 A：证据 -> 探针对照

| 项 | 探针文件 | 关键输出（见 §2） |
|---|---|---|
| P-01 | probe_b2_race.py | wait_pending 0.000s / 已完成 1of2 / pending=1 |
| P-02 | probe_bcd_pipe.py | 未抛异常，成功子步 2/3 |
| P-03 | probe_d2_stop.py | stop 2.00s / alive=True / max_inside=2 / destroy 后仍完成 2 步 |
| P-04 | probe_a_diff_sync.py | rebuilt=0 / signature 不变 / 无 set_sensor |
| P-05, P-06 | probe_a2_rebuild.py | _last_sync=51 _tree_bit=51 活跃体=1 / 树位轮转警告 |
| P-07 | probe_k_initial_rot.py | (0.4,0.2,0.1)->(0,0,0) / 子体 0->(0.082,-0.571,-0.647) / K4 对照保留 |
| P-08 | probe_k5_offset.py | (0,3,0)->(3,3,0) |
| P-09 | probe_a2_rebuild.py | 47.08462 -> 0 |
| P-10 | probe_ef_glue.py | F1/F2/F4 全 rc=0 |
| P-11 | probe_g_rebuild_loop.py | 3 帧各重建 1 次桥与线程 |
| P-12 | probe_l_parent_sync.py | 父无碰撞体：子 (1,0,0)->(-4,0,0)，实体停在 1.0 |
| P-13 | probe_ef_glue.py（E 段 spy） | 各数组长度恒等 |
| P-14 | probe_h_pairvec.py / probe_h5.py | 780 对不一致=0；边界全一致 |
| P-16 | probe_ij.py | 父旋转/非均匀缩放：位置漂移 0，旋转仅首帧 0.646994 |
| P-17 | probe_ij.py | shutdown 0.000s / 任务仍在跑 / daemon=False |

## 附录 B：本次未审/未覆盖边界（如实登记）

1. 未在真实 Jolt 上构造 >2s 子步以触发 P-03 的原生崩溃（只读审计，不做压测）；P-03 的并发进入用 FakeWorld 复刻。
2. 未启动 GUI/播放场景，因此 P-20 无法实测；P-07/P-08/P-12 用物理桥直接调用路径验证（与 engine/scene_driver 的调用序列一致：build/ensure -> pre -> step -> post）。
3. 未审计 grep 命中但不属于本模块文件的物理相关代码：scene_driver.py 的桥封装（模块 05）、editor.py 的 toggle_trigger 命令（模块 06）、ui/loom_gui.py 的接触材质检查器（模块 06）。
4. 未跑 tests/run_all.py（协议禁止）；只跑了 3 个定向物理测试（均 ALL PASS）。
5. 报告正文中的 Windows 路径为可读性改用正斜杠，实际路径分隔符为反斜杠。
