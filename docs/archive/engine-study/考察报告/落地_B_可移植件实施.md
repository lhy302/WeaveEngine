# 落地_B: 可移植件批 (组6 buckets 上传路径) 实施规格

日期: 2026-09-02 | 前置: 组1/2/3/6 已完成 (staging 持久/SoA 快照/持久 _fw32), 本批为剩余热点收尾。
锚点: engine.py `_prepare_bucket_frame` L3995 / `_transform_snapshot` L2575 / `compute_world_matrices` L2622 / `draw_lines` L2469 (vp 走 self._vp L2495) / `Material` L673 / `MeshRendererComponent` L356 / render() L4070。
总红线: 逐帧语义完全不变 (脏检测误判=渲染错误, 宁可不落地) | 50球守护 ≥163.8FPS | 全量回归 tests/run_all.py | 在 Loom(py源代码-工作区) 开发。

## 已核对前提 (前次会话结论, 直接采信)
- `_frame_world` 无原地写消费者 → 可安全缓存/复用。
- `_transform_snapshot` 唯一生产调用方是 compute_world_matrices (L2642), 语义铁律见 L2588-2596 (Point3D/tuple 不可变, 改值必换对象, id 钉住防复用)。
- `draw_lines` L2469/L2495 vp 全走显式参数或 self._vp, 无隐藏逐帧 uniform 重复上传。
- `MeshRendererComponent.material` 库内 6 处赋值点可单点收口为 property setter。
- build_entry 不在上传路径, 本批不涉及。
- L3995 write 已零拷贝 (staging 持久原地写)。

---

## 件1: 桶 _dirty 总闸 + 脏区间合并提交 — 判定: 落地 (最小改法=整帧跳过, 不做区间级)

**改哪里**: engine.py
1. `Engine.__init__` (L1547 附近): 增 `self._bucket_dirty = True`。
2. `Material.color/saturation` setter (L694-706): 各 bump 类级 `Material._asset_gen += 1` (用引擎实例钩子转 `self._bucket_dirty=True` 可选; 类级计数更简单, 引擎侧记上次值)。
3. `MeshRendererComponent.material` 收口为 property setter (L367 处 6 赋值点全走它): setter 内置 `self._mat = v` 并标记引擎脏 (经弱引用或类级 gen)。
4. `GameObject.visible` setter (L840) / `mesh` setter (L800): 各调 `self._engine_ref._bucket_dirty = True` + `_bump_struct()` (保守, 触发频率极低)。
5. `compute_world_matrices` L2622: 开头快照命中与否记录 `self._transform_changed = (快照 miss)` (命中=O(1) 读已有 _soa_snap; miss 本来就走重建路径, 零新增成本)。
6. `_prepare_bucket_frame` L3995 开头: `if not (self._bucket_dirty or self._transform_changed): return` —— 实例缓冲/staging/`_render_buckets` 保持上帧内容 (相机移动/VP 变化不影响实例数据, 静止场景整段跳过)。提交成功后 `_bucket_dirty=False`。

**关键形态**: 脏信号三类 = 结构变更 (已有 `_bump_struct`) + 材质变更 (新增 gen, property setter 按构造穷尽所有赋值) + 变换变更 (复用 `_soa_snap` id 钉住精确判定, 非启发式)。三者任一为真才提交。**不做脏区间合并**: 桶内实例本是"全量重排+整段 write", 区间化收益小于复杂度风险 (最小改法优先)。

**验收**: (a) 50球守护 ≥163.8FPS; (b) 阶段计时 'buckets' 子阶段: 编辑态静止场景 → ~0ms, 播放态脚本动物体 → 恢复原值; (c) 像素对拍: 静止场景+轨道相机旋转 N 帧逐帧一致; 播放态脚本动画 N 帧与不带闸基线逐帧一致 (防漏失效)。

## 件2: 上传零拷贝 — 判定: 落地 (仅验证+留档, 不改代码)

**结论**: L4058-4059 `inst['main'].write(st[:k], 0)` / `inst['sha'].write(g[:k], 0)` —— moderngl Buffer.write 直吃 buffer 协议切片, 单次 glBufferSubData, 无 tobytes 中间拷贝; staging `np.zeros` 仅在桶建/扩容帧分配 (L4034-4037), 稳态零分配; gather 缓冲同寿命 (L4038-4042)。前次会话已确认, 本件复核无反例。**动作**: 本节即留档, 附行号证据, 代码不动。

**验收**: 无代码 diff; 复跑 50球守护确认无回归即可。

## 件3: uniform 句柄+值差分缓存 — 判定: 落地 (证据充分)

**改哪里**: engine.py
1. 句柄缓存: program 构建完成后一次性 `self._u = {name: self.prog[name] for ...}` (同法 `_shadow_prog`/`_line_prog`/`hud_prog`), 每帧 `self._u['u_view_proj']` 替代 `self.prog['u_view_proj']` 字符串哈希+uniform 查找。热点实测点: L4121-4123 (u_view_proj write + u_view_pos) 每帧; L2114-2129 (_upload_lights 8×`ascontiguousarray().tobytes()` + 6×.value) 每帧。
2. 值差分: 每个 (program, uniform) 记上次写入值; 新值与旧值相等 (`==`/`np.array_equal`) 则跳过 glUniform/glBufferSubData。GL uniform 状态机保证同值跳过语义等价。
3. 安全面: self.prog 的全部写点已 Grep 穷尽 (L2057/2114-2129/4121/4123, 其余属 shadow/line/hud 独立 program), 单一所有者, 无旁路写点 → 差分缓存不会与外部写打架。program 重建点 (若有热重载) 必须同步清句柄缓存 (fail-safe: 重建函数末尾 `self._u=None` 惰性重建)。
4. `draw_lines` L2523 的 `_line_prog['u_view_proj'].write(...ascontiguousarray...tobytes())`: vp 来自参数/self._vp, 可用同一差分; tobytes 顺手消掉 (write 直吃数组)。

**验收**: (a) 阶段计时: 灯光静止场景 u_upload 段耗时下降 (8×tobytes+8×glUniform → 跳过); (b) 像素对拍: 静止场景 N 帧一致; 动态灯场景 (灯每帧动) 与基线一致; (c) 50球守护 ≥163.8FPS; (d) tests/run_all.py 全绿。

## 件4: world_matrices 静止缓存 — 判定: 落地 (失效面按构造穷尽, 非枚举写者)

**改哪里**: engine.py
1. `_transform_snapshot` L2575: 把当帧 `keys` (无论命中或重建路径) 存 `self._soa_last_keys` 返回路径带上 (命中时即 snap[1], 零额外计算)。
2. `compute_world_matrices` L2622: 快照后以 `(stamp, keys)` 查 `self._fw_cache`; 命中 → 直接返回缓存矩阵对象; miss → 现行批量计算后 `(stamp, keys, fw)` 入缓存。

**失效面论证** (为何可穷举): 世界矩阵输入 = 三变换对象本体 + 父链结构。Point3D/tuple 不可变 → 任何改值必换对象 → id 必变 → keys 必失配 (L2588-2596 既有铁律, 含 id 钉住防复用); 结构/挂父变更走既有 `_bump_struct` 进 stamp; 列表替换走 `id(models)`。**不枚举写者 (脚本/物理/动画/undo 全覆盖), 按构造穷尽, 无启发式漏报**。判定成本: 复用快照命中检查 —— 该检查 compute_world_matrices 本来就每帧支付 (L2642), 新增成本≈0, 满足"失效判定不增负"红线 (严格 O(1) 计数器方案因有漏报风险被否决)。
**缓存命中返回同一数组对象**: `_frame_world` 无原地写消费者 (已核对前提) → 安全; 在 L2622 docstring 注明"返回对象跨帧复用, 禁原地改"。

**验收**: (a) 像素对拍: 编辑态静止 N 帧一致; 播放态脚本动画 N 帧与基线一致; (b) 阶段计时 'world_matrices': 编辑态 → ~0ms, 播放态 (每帧动) 与基线持平 (不劣化); (c) 50球守护 ≥163.8FPS; (d) tests/run_all.py 全绿。

---

## 落地顺序与守护
1. 件2 留档 (零风险) → 件3 (独立, 收益直接) → 件4 (复用件3同批对拍基建) → 件1 (依赖件4的 _transform_changed 信号, 最后落)。
2. 每件独立提交, 独立跑: 50球守护 ≥163.8FPS + tests/run_all.py + 像素对拍 (静止/播放两态)。
3. 任一件对拍不一致或守护掉线 → 该件回滚不落地, 其余继续。
