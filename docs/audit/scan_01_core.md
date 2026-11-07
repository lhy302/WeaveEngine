# 引擎核心与组件模型 扫描报告（scan_01_core）

> 审计日期：2026-11-07 | 只读审计（未修改任何受跟踪源码/测试/文档）
> 依据：`docs/audit/SCAN_PROTOCOL.md`（三阶段/8 段链）+ 桌面两份方法论文档
> 代码根：`D:/my-project - 副本/Loom(py源代码-工作区)/Loom`（git 根为上一级 `Loom(py源代码-工作区)`）

## 0. 范围与方法

### 0.1 文件清单（行数为 read 工具实测）

| 文件 | 行数 | 职责 |
|---|---|---|
| engine.py | 1403 | GLEngine 14 mixin 组装 / 主循环与帧调度 / 脚本调度 / GC 生命周期 / 2D 绘制助手 |
| loom_components.py | 472 | Transform / MeshRenderer / Script / Collider / Rigidbody / AudioSource / AnimationClip / Animator / AudioSystem |
| loom_game_object.py | 369 | GameObject 容器：组件列表、便捷属性委托、layer/tag、脚本管理、SendMessage |
| loom_transform.py | 430 | TransformMixin：世界矩阵 / SoA 快照 / 父链 / 包围盒 / set_parent |
| loom_material.py | 133 | Material 资产（颜色/饱和度/PBR/贴图槽 + 外观代计数器） |

合计 2807 行。跨模块只读引用（不作为本报告裁决对象，仅作调用方/消费方证据）：editor.py、loom_render.py、loom_lighting.py、loom_physics.py、loom_logic_thread.py、interp_state.py、sceneio.py、mesh.py、loom_color.py、layer_tag.py、scripts.py、agent_commands.py。

### 0.2 读过的判定基准

- `docs/audit/SCAN_PROTOCOL.md`（67 行，全读）
- `C:/Users/Administrator/Desktop/论如何正确的vibe coding.md`（614 行，全读）
- `C:/Users/Administrator/Desktop/论如何使用AI自动化工具正确的判断AI给出的黑盒是否符合设计标准.md`（735 行，全读 0-400 行与探针/裁决章节）
- 项目设计/契约文档（按需取证）：`docs/archive/engine-study/考察报告/分离批5_6_架构重对齐.md`、`docs/design/3D音频系统契约_20261018.md`、`docs/design/LayerTag系统契约_20261018.md`

### 0.3 跑过的命令（全部为定向探针，未跑 tests/run_all.py）

环境：Windows，`python` = Python 3.12.10，pygame 2.6.1，moderngl 离屏 `create_standalone_context()`。
探针统一 `LOOM_NO_SAVE_MIGRATE=1`；除特别说明外 `LOOM_NO_PARALLEL=1`；探针文件放临时目录
`C:/Users/Administrator/AppData/Local/Temp/loom_audit_01/probe_*.py`（不在仓库内）。

```
git -C <proj> diff HEAD --numstat -- Loom/engine.py Loom/loom_components.py Loom/loom_game_object.py Loom/loom_transform.py Loom/loom_material.py
  -> 1  0  Loom/engine.py        （唯一未提交改动 = 第 32 行 import sys）
git -C <proj> log --oneline -3 -- <每个文件>              （见 0.4）
git -C <proj> status --porcelain                          （审计前后一致；探针未改受跟踪文件）

python %TEMP%/loom_audit_01/probe_stale_fw2.py       # P-01 纯引擎复现
python %TEMP%/loom_audit_01/probe_editor_play.py     # P-01 真实 EditorApp（同步）
python %TEMP%/loom_audit_01/probe_editor_async2.py   # P-01 真实 EditorApp（生产默认异步逻辑线程）
python %TEMP%/loom_audit_01/probe_player_render.py   # P-01 影响面：Player 基类路径不受影响
python %TEMP%/loom_audit_01/probe_collision_events2.py / probe_collision_events3.py   # P-02
python %TEMP%/loom_audit_01/probe_batch.py           # P-03 / P-06 / P-07 / P-12
python %TEMP%/loom_audit_01/probe_double_dispatch2.py# P-04
python %TEMP%/loom_audit_01/probe_parent.py          # P-05 / P-13
python %TEMP%/loom_audit_01/probe_children.py        # P-09
python %TEMP%/loom_audit_01/probe_misc2.py           # P-10 / P-11
python %TEMP%/loom_audit_01/probe_misc.py            # P-14（import sys 修复实测）
python %TEMP%/loom_audit_01/probe_draw2d.py          # P-15（f0ad76a 新代码冒烟）
python %TEMP%/loom_audit_01/probe_gimbal.py          # P-13（万向锁补充探针，交叉核对 02_scene P-14）
```

第三方复现：把 §附录 的代码块保存为 `%TEMP%/.../probe_x.py`（sys.path 指向 Loom 目录）后执行即可；
下文所有“实测输出”均为上述命令的原样输出（控制台中文乱码为 Windows 代码页所致，数值不受影响）。

### 0.4 特别审查：git diff 结论（[REGRESSION] 判定依据）

`git diff HEAD` 对本模块 5 个文件只有 1 行新增：

```diff
diff --git a/Loom/engine.py b/Loom/engine.py
@@ -29,6 +29,7 @@
                     view_basis_to_angles)   # M29/M41 ...
+import sys                      # P-06 修复: LOOM_SWITCH_INTERVAL (GIL 切换间隔) 依赖; 原缺失导致配置静默失效
```

最近提交（`git log --oneline -3 -- <file>`）：
- engine.py：f0ad76a（沙盘 2D 绘制新增 draw_screen_lines/polygon）、ba4a02f（far 100→1000）、0cca8b1（天空盒修复）
- loom_components.py：bea93ce（Trigger 字段/钩子）、217cfd5（3D 音频字段）
- loom_game_object.py：6e7b188（SendMessage/对象查找）、217cfd5、1b54d4e（layer/tag）
- loom_transform.py / loom_material.py：89141af（Initial commit）后未再改动

→ **本模块没有“Vulkan 对齐”相关的未提交改动**；唯一未提交 diff 是 `import sys`（P-14 判为正确修复）。
→ 本报告 **REGRESSION 清单为空**。P-01/P-02/P-04 均位于已提交历史中（非本轮未提交 diff 引入），
   在 §4 单独标注“归属”，避免主 Agent 误归档为回归。

---

## 1. 粗筛清单（阶段一）

> 标签取自方法论 §4.3：SEM-*/BND-*/IFACE-*/OVERFIT-*/AUDIT-*。粗筛只给方向，不判决。

| ID | 位置 | 标签 | 初步方向（一句话，指向代码事实） | 粗筛证据 |
|---|---|---|---|---|
| P-01 | engine.py:1073-1082、1040-1042；editor.py:1932-1933；loom_render.py:398-403 | SEM-MISMATCH / IFACE-PRECOND | 播放态 `_logic_prep` 复用已有 `_frame_world`，而 Editor 播放分支只在 `_frame_world is None` 时赋值 → 该矩阵自进播放起不再刷新；`_soa_snap` 也随之不刷新 → 渲染矩阵/阴影VP/碰撞AABB/插值平面全部冻结 | `if fw is None or fw.shape[0] != n:`（engine.py:1075）、`if getattr(self,'_frame_world',None) is None: self._frame_world = self._render_world`（editor.py:1932-1933） |
| P-02 | engine.py:1086-1094；loom_lighting.py:737-744 | SEM-SILENT / AUDIT-DOCIMPL | split 播放态只有在 `_frame_pool` 非空且 `n>=32` 时才计算 `_prep_pairs`，否则写 `[]`；渲染 split 路径只派发该列表，无内联兜底 → 小场景/关并行时 on_collision_*、on_trigger_* 永不触发 | `self._prep_pairs = []`（engine.py:1094）+ `if _pairs is not None and self._disp_gen != _lgen: dispatch(_pairs)`（loom_lighting.py:741-744） |
| P-03 | engine.py:846-854；loom_game_object.py:231-237 | SEM-OVERFIT | `_has_scripts_cached` 只以 `_struct_gen` 作失效键；`GameObject.add_script/remove_script` 不 bump 该代 → 无脚本场景运行期挂脚本后 `update_scripts` 仍早退 | `if cache_gen != struct_gen: ... any(bool(m.scripts) ...)`；`add_script` 只 append，无 `_bump_struct` |
| P-04 | engine.py:1031-1035；loom_lighting.py:737-744 | AUDIT-ASYMMETRY | 同一逻辑帧的碰撞对在 `_logic_frame` 内派发一次、渲染 split 路径又派发一次；start/end 因集合差幂等被掩盖，但 stay 类钩子每逻辑帧触发 2 次/物体 | engine.py:1031 注释“每逻辑帧一次” vs loom_lighting.py:740 注释“同一逻辑帧的 pairs 只派发一次” |
| P-05 | loom_components.py:69-74；loom_transform.py:55-57、104-106 | BND-OFFBYONE / IFACE-PRECOND | `scale` setter 接受任意长度元组；长度 <3 时 `mat4_scale(s[0],s[1],s[2])` / SoA 快照 `s[2]` 抛 IndexError（渲染/物理帧内） | `self._scale = tuple(v)` 无长度校验；`s[0]/s[1]/s[2]`（loom_transform.py:106） |
| P-06 | loom_components.py:218-245 | IFACE-UNIT / AUDIT-ASYMMETRY | `max_distance` setter 维护 `max>min`，但 `min_distance` setter 不反向重钳 → 先设 max 再设大 min 可破坏契约 §43 后置条件 | `self._max_distance = f` 前有 `if f <= lo: f = lo*2`；`min_distance` setter 只做 `f>0` |
| P-07 | loom_material.py:57-62；loom_color.py:15 | SEM-DEFAULT / BND-* | `_hex_rgba` 用 `dict.get(c)` 做缓存键，unhashable 的 color（list/ndarray）在进入 try 前抛 TypeError，与 docstring“失败回退灰色”冲突 | `t = _HEX_RGBA_CACHE.get(c)` 在 try 之外 |
| P-08 | loom_transform.py:277-306 | AUDIT-DEADCODE | `_batch_rotations` 无任何调用方（含测试），文件头却把它列为“渲染矩阵”段成员 | `grep` 全库仅定义处与 scheduler.py 注释提及 |
| P-09 | loom_game_object.py:122-138 | AUDIT-ASYMMETRY / IFACE-* | `GameObject.parent` setter 被注释为“脚本/编辑器直写”支持的旁路挂父，但只改指针+bump，不维护 `children`；`collect_subtree/remove_subtree` 仍把该子物体算在旧父下 | setter 内只有 `self.transform.parent = v` + 遍历 `_LIVE_INSTANCES` 调 `_bump_struct` |
| P-10 | loom_transform.py:53-60 vs 200-216；loom_model_gpu.py:260-300 | SEM-MISMATCH | 父物体被 `remove_model` 删除后，子物体 `parent` 悬空：批量路径按“缺失父=根”处理，递归路径仍沿悬空父合成 → 世界矩阵两套语义分叉 | `parent[i] = id2i.get(id(m.parent), -1)`；`M = M @ self.model_world_matrix(m.parent)` |
| P-11 | loom_transform.py:414-430、400-412 | BND-EMPTY | 空网格（Mesh([],[],[])）会让 `_homogeneous_vertices` 的 `np.concatenate(..., axis=1)` 抛 AxisError，`get_bounding_box` 无法返回 AABB | `verts.shape[0]=0` 时 `np.ones((0,1))` 与 1 维数组 concatenate |
| P-12 | loom_components.py:264-399 | SEM-MISMATCH | AnimationClip 快路径（searchsorted+向量化）与慢路径（线性扫）在边界 t（负值/NaN/重复时间/整型 time）可能不等价 | 两套实现并存，docstring 声称逐位一致 |
| P-13 | loom_transform.py:352-391；matlib.decompose_euler | SEM-MISMATCH | `set_parent(preserve_world=True)` 用 `decompose_euler` + 分量相除还原世界旋转/缩放，随机域守恒、万向锁奇点 β=±π/2 处世界旋转被改变 | `Rl = wr @ inv(Rp)` + `ws.x/ps.x`；probe_gimbal 实测 diff=1.68 rad |
| P-14 | engine.py:32（未提交 diff） | SEM-SILENT | 新增 `import sys` 是否引入副作用/重复导入；旧代码是否确实静默失效 | `git diff` 1 行；`sys.setswitchinterval` 在 try/except 内 |
| P-15 | engine.py:692-813（f0ad76a 新代码） | BND-* | `draw_screen_lines/polygon/_px_to_ndc` 的空输入/短输入/颜色通道数边界 | 新代码，无既有测试主链覆盖（仅 tests/_tmp/smoke_sandbox_shape.py） |

### 1.1 跳过项留痕（四类允许理由之一）

| SKIP | 位置 | 跳过理由（类型 + 具体事实） |
|---|---|---|
| SKIP-01 | loom_components.py:340-343（`_np_sync` 只校验 id+len，同长度原地改帧不重建） | **白盒契约明确声明**：类 docstring 275-277 行明写“同长度原地改帧不在校验范围，需调 _np_rebuild() 显式重建（全工程现状无此用法）”；并已 grep 全库 `.frames` 写点，仅构造/读取，无原地 mutate |
| SKIP-02 | loom_transform.py:69-82（`_transform_snapshot` 以 `id(position/rotation/scale)` 钉住缓存） | **语言规范保证**：`Point3D` 为 `collections.namedtuple`（不可变）、`scale` 存 `tuple`（不可变）→ 改值必换对象；结构变更走 `_struct_gen`，列表替换走 `id(models)`（docstring 126-132 已列穷尽失效面） |
| SKIP-03 | loom_transform.py:120-168（返回 `_fw_cache` 矩阵本体、跨帧复用） | **白盒契约明确声明**：docstring 131-132 “★返回对象跨帧复用，消费方禁原地改（已核对: _frame_world 无原地写消费者）”；本报告另做独立 grep：`_frame_world[...]=` / `_render_world[...]=` 全库 0 命中 |
| SKIP-04 | engine.py:186-195、`GLEngine._LIVE_INSTANCES` 弱引用表 | **语言规范保证**：`weakref.ref` 自动失效；`__init__` 每轮用 `r() is not None` 过滤死引用；`_bump_struct` 内部 `except AttributeError` 自愈测试桩 |
| SKIP-05 | engine.py:117-163（`gc_play_enter/exit` 模块级全局 `_gc_thresh_prev/_gc_play_active`） | **白盒契约明确声明**：`gc_play_exit` docstring 声明“幂等: 未 enter 时 unfreeze/collect 亦无害”；调用面 grep 为 editor.toggle_play / PlayerApp.load_scene 单播放会话（多引擎嵌套不属当前契约） |
| SKIP-06 | engine.py:1249-1359（`_dispatch_fixed_update/_late_update/_application_quit/_visibility_changed`） | **白盒契约明确声明**：docstring“异常隔离：打印 + 标记坏脚本（与 _call_collision_cb 一致）”；代码与声明一致（`except Exception` → print → `_script_broken=True`） |
| SKIP-07 | loom_game_object.py:75-101（layer/tag setter） | **白盒契约明确声明**：`docs/design/LayerTag系统契约_20261018.md` 规定越界钳制/未注册自动注册的处置在 sceneio 层完成（sceneio.py:193-217 已实现兜底），组件层按契约抛异常 |
| SKIP-08 | loom_components.py:430-472（AudioSystem 委托 audio_backend） | **工具/框架自身声明**：`audio_backend.AudioBackend` 契约（无设备 no-op、失败静默）；audio_backend 属模块 10 资产审计范围，本报告只审计组件层字段与状态机 |

### 1.2 越界声明（非“跳过判定”，仅说明本轮不重复裁决）

- engine.py:692-813 的 GL 绘制助手：本轮只做冒烟（P-15），像素级正确性归 03_gl_render / 06_editor_ui 模块。
- `GLEngine.remove_model/add_model/clear_scene`（loom_model_gpu.py）与物理桥：只作为 P-10/P-02 的触发/调用方证据，不在本模块结论内。
- `loom_color._HEX_RGBA_CACHE` 无上限增长（loom_color.py:10-23）：loom_color 属模块 10；P-07 只裁决 Material 侧的输入边界。

---

## 2. 逐项裁决（阶段二/三）

> 每条按 8 段式。证伪链与证真链都给出；P-DISPROVED 项给出证伪链 + 证真尝试失败记录。

### P-01 `[P-PROVED / P1]` 编辑播放态：`_frame_world` 与 `_soa_snap` 自进播放起不再刷新 → 渲染/阴影VP/碰撞AABB/插值平面冻结

**反手（证伪链）**
1. 判定基准：`loom_transform.py:176-179`“播放态同步由逻辑帧 advance 翻页天然保证（R3）”；`interp_state.py:86-103` advance “curr <- 新抓取”；`loom_render.py:398`“桶/实例消费渲染矩阵（插值）；_frame_world 保持逻辑位姿”。
2. 代码证据：`engine.py:1074-1078`（fw 非 None 且行数匹配 → 不重算）、`engine.py:1040-1042`（advance 直接喂 `_soa_snap` 平面）、`loom_transform.py:62-82`（快照只在 `compute_world_matrices` 里刷新）、`editor.py:1932-1933`（仅 None 时赋值）、`loom_transform.py:181-182`（`is_playing` 时 `_consume_xform_gen` 提前返回，不失效）。
3. 路径枚举（全部播放态进入点）：
   - 路径 A：Editor + split + 同步逻辑（LOOM_LOGIC_SYNC=1）：editor.render:1913→advance_logic→clk.advance→_logic_frame→_logic_prep；render:1922-1933 播放分支只算 `_render_world`，`_frame_world` 仅当 None 赋值 → 冻结（实测 probe_editor_play）。
   - 路径 B：Editor + split + 异步逻辑线程（默认）：paintGL 调 `_start_logic_thread`（ui/loom_gui.py:579 注释）→ 同一 `_logic_frame`；editor.render 跳过 advance_logic（1912-1913）→ 冻结（实测 probe_editor_async2）。
   - 路径 C：Player 基类 `GLEngine.render`（loom_render.py:734-735）每渲染帧重算 `_frame_world` → 快照刷新 → 不冻结（实测 probe_player_render，只有插值固有的 1 逻辑帧滞后）。
   - 路径 D：split 未启用（logic_fps<=0）：editor.render:1934-1938 每帧重算 → 正常。
   - 无其他写点：`grep "_frame_world\s*="` 全库仅 engine.py:419/1078、loom_transform.py:197（编辑态）、loom_render.py:734（基类 render，Editor 覆写不走）、editor.py:1933/1936（1936 属非播放分支）。
4. 实际行为：播放期 `_logic_prep` 取到进播放时的矩阵对象后永不重算；`_soa_snap` 因此永不重建；`_logic_frame` 把同一份旧平面喂给 `interp.advance` → prev==curr==进播放位姿。
5. 差异：预期“渲染矩阵/阴影VP/AABB 跟随逻辑位姿”，实际“冻结在进播放位姿”。
6. 触发条件：EditorApp（Qt 宿主）+ `is_playing=True` + `logic_fps>0`（默认 30，设置.json:11）——即编辑器默认播放配置。
7. 验证：
   - probe_stale_fw2.py：`frame 1 actual.x=2.00 prep_aabb.x=-0.5 id(fw)_same=True` … `final fresh_aabb.x=7.50`；B 段 `actual.x=0..8, interp_curr.x=0.0, render_pose.x=0.0000`。
   - probe_editor_play.py（真实 EditorApp，2 帧编辑态 render 后 toggle_play，逐步改位）：`frame 4 actual.x=8.00 _render_world[0].tx=0.0 _frame_world[0].tx=0.0 logic_gen=2`。
   - probe_editor_async2.py（生产默认异步，手工启逻辑线程等价 GUI）：`80 渲染帧后: actual.x=237.0 _render_world[0].tx=0.00 _frame_world[0].tx=0.00 logic_gen=12`。
   - probe_player_render.py（对照，基类 render）：`frame 5 actual.x=15.00 render_world.tx=6.00 frame_world.tx=15.00`（_frame_world 当帧跟随；render_world 为插值滞后）。
8. 证伪结论：失败——找不到任何在 Editor 播放态刷新 `_frame_world`/`_soa_snap` 的路径；路径 C/D 不适用于 Editor 播放。

**正手（证真链）**
1. 位置：engine.py:1073-1082（根因判定点）、engine.py:1040-1042（快照喂入）、editor.py:1932-1933（漏洞使能条件）。
2. 契约/预期：逻辑帧是最高同步点（engine.py:973-980），播放态渲染必须跟随物体移动；着色/阴影/碰撞 prep 用逻辑位姿（分离批5 设计 §三）。
3. 路径枚举：同证伪链 A/B/C/D；只有 A/B 命中缺陷。
4. 实际行为：冻结（见上）。
5. 差异方向：少做了“刷新逻辑矩阵/插值快照”。
6. 触发条件：同证伪链第 6 段。
7. 验证：同证伪链第 7 段（三个探针原样输出）。
8. 判定：**P-PROVED，P1（功能错误：编辑器播放画面/碰撞/阴影不随逻辑更新）**。影响面限定为 EditorApp；PlayerApp 基类 render 路径不受影响。归属：非本轮未提交 diff；代码位于 HEAD（分离批5/编辑器播放态分流）。修复方向见 §4-1。


### P-02 [P-PROVED / P1] split 播放态：小场景（n<32）或 `_frame_pool=None` 时 `_prep_pairs=[]` → 碰撞/触发回调永不派发

**反手（证伪链）**
1. 判定基准：engine.py:1086 注释“碰撞对（只读检测; 派发在 _logic_frame 尾部主线程）”；设计文档《分离批5_6 架构重对齐》§三“小场景: 事件走旧内联（改4）”。
2. 代码证据：engine.py:1087-1094（`pool is not None and n >= _COLLISION_PAR_THRESHOLD(=32) and is_playing` 才计算，否则 `self._prep_pairs = []`）；engine.py:1031-1035（派发该列表）；loom_lighting.py:737-744（split 路径只派发 `_logic_snapshot()` 返回的 pairs，无内联分支）；loom_physics.py:671-682（只有 `_update_collision_events` 才有小场景内联分支，而 split 路径不调用它）；loom_physics.py:611（`_COLLISION_PAR_THRESHOLD = 32`）。
3. 路径枚举：
   - (a) split + playing + pool 非空 + n>=32 → 计算 pairs（probe 8c：n=40/有池 → 114 对）→ 派发正常。
   - (b) split + playing + n<32（pool 有无都一样）→ `_prep_pairs=[]` → 派发空列表（probe 8b：n=3 → 0 次回调；对照组旧内联 6 次）。
   - (c) split + playing + `_frame_pool=None`（LOOM_NO_PARALLEL=1 / parallel_enable=false / FramePool 建失败）→ `[]`（probe 8b：n=40 无池 → 0；旧内联 228 次）。
   - (d) 非 split / 非 playing → loom_lighting.py:705-736 旧路径，`_update_collision_events` 内联正常。
   - 无其他派发点：全库 `on_collision_start` 只在 loom_physics.py:732/779 由 `_dispatch_collision_events` 派发；该函数只被 engine.py:1034、loom_lighting.py:729/743 调用（grep 证实）。
4. 实际行为：`_prep_pairs=[]` 是“合法空缓存”，不是 None，渲染侧 `if _pairs is not None` 通过 → 派发空集；`_colliding` 永远为空。
5. 差异：预期“小场景/关并行也能收到 on_collision_start”，实际“永不触发”。
6. 触发条件：默认 `logic_fps=30` + 播放 + 场景物体数 <32（典型小游戏），或用户关闭并行。
7. 验证：
   - probe_collision_events2.py：`n=3 无池: _prep_pairs=[] → split 派发后 0 次；再跑旧内联后累计 6`；`n=3 有池: ... 0 / 6`；`n=40 无池: ... 0 / 228`。
   - probe_collision_events3.py：`n=3 有池 -> _prep_pairs 对数=0；n=40 有池 -> 114`。
8. 证伪结论：失败——无法构造任何一条让 (b)/(c) 场景触发回调的路径。

**正手（证真链）**
1. 位置：engine.py:1086-1094；loom_lighting.py:737-744。
2. 契约：同设计文档“小场景走旧内联”+ engine.py:1031 “每逻辑帧一次”。
3. 路径枚举：同证伪链。
4. 实际行为：见上。
5. 差异方向：设计承诺的内联兜底未实现。
6. 触发条件：见上。
7. 验证：见上。
8. 判定：**P-PROVED，P1（功能错误：碰撞/触发事件静默失效）**。修复方向见 §4-2。

### P-03 [P-PROVED / P2] `update_scripts` 的 `_has_scripts_cached` 不被 `add_script` 失效 → 无脚本场景运行期挂载的脚本永不执行

**反手（证伪链）**
1. 判定基准：engine.py:836-838 注释“快速早退…场景无脚本时 0 迭代直接退出”，属纯优化，语义必须与无缓存版本一致；`GameObject.add_script` docstring“挂一个脚本组件（可多个）”。
2. 代码证据：engine.py:846-854（仅在 `cache_gen != struct_gen` 时重算 `has_scripts`）；loom_game_object.py:231-237（add_script 只 append）；loom_game_object.py:197-204（`script_id` setter 走 add_script）；`_bump_struct` 调用点只覆盖 add/remove_model/clear_scene/set_parent/remove_camera（grep）。
3. 路径枚举：
   - (a) 首次调用时场景已有脚本 → has_scripts=True，后续挂脚本仍 True → 正常。
   - (b) 首次调用时无脚本 → False；之后 `add_script` / `script_id=` 不 bump → 永远 False → 早退（缺陷路径）。
   - (c) 期间发生 add_model/remove_model/set_parent（bump）→ 缓存重建 → 恢复（掩盖缺陷）。
   - (d) 运行期 `remove_script` 不 bump → 仍 True（多算不错算，无缺陷）。
4. 实际行为：False 状态被永久钉住，直到结构变更。
5. 差异：预期“新增脚本组件后该物体脚本被执行”，实际“update_scripts 在入口 return”。
6. 触发条件：播放中通过 EAI `script_add`（agent_commands.py:592-593）/ 脚本内 `add_script` / `script_id=` 给“进入播放时无脚本”的场景挂脚本。
7. 验证：probe_batch.py 第 1 段：
   ```
   after call#1 (no script): updates = 0 _has_scripts_cached = False
   call#2 after attaching script (struct_gen unchanged): updates = 0
   call#3 after _struct_gen+=1: updates = 1   (期望 call#2 就该出现)
   ```
8. 证伪结论：失败——(b) 路径成立且不依赖任何未验证假设。

**正手（证真链）**
1. 位置：engine.py:846-854；loom_game_object.py:231-237。
2. 契约：同第 1 段。
3. 路径枚举：同证伪链。
4. 实际行为：见上。
5. 差异方向：缓存失效键不完整。
6. 触发条件：同证伪链第 6 段。
7. 验证：同证伪链第 7 段（另：tests/test_scripts.py:303-320 全部从“首帧已有脚本”开始，故既有测试不覆盖 False→True 转换）。
8. 判定：**P-PROVED，P2（边界状态下的功能错误；正常编辑器流程不触发）**。

### P-04 [P-PROVED / P2] 同一逻辑帧碰撞对派发两次 → `on_collision_stay`/`on_trigger_stay` 每逻辑帧每物体触发 2 次

**反手（证伪链）**
1. 判定基准：engine.py:1031 注释“碰撞事件派发（消费 _prep_pairs; 每逻辑帧一次）”；loom_lighting.py:740-741 注释“同一逻辑帧的 pairs 只派发一次（多渲染帧同逻辑帧）”。
2. 代码证据：engine.py:1031-1035（`_logic_frame` 内直接 `_dispatch_collision_events(self._prep_pairs)`）；loom_lighting.py:737-744（渲染 split 路径按 `_disp_gen != _lgen` 再派发同一列表）；`_disp_gen` 只在 loom_lighting.py:744 更新，`_logic_frame` 侧不更新。
3. 路径枚举：
   - (a) start/end 类：第一次派发后 `m._colliding` 已更新，第二次集合差为空 → 幂等，不重复。
   - (b) stay 类（`_any_script_needs_stay` 为真，如覆盖 on_collision_stay / on_trigger_stay）：两次派发各进入 `current & prev` 循环 → 每逻辑帧 2 次/物体。
   - (c) 有脚本但集合不变且 has_stay=False：两处都 early-return，无重复。
   - (d) split 关闭/非播放：只走旧路径一次，无重复。
4. 实际行为：稳态 stay 双发。
5. 差异：预期 1 次/逻辑帧/物体，实际 2 次。
6. 触发条件：split 播放态 + 脚本覆盖 on_collision_stay 或 on_trigger_stay（且该物体处于碰撞/触发对）。
7. 验证：probe_double_dispatch2.py：
   ```
   逻辑帧 0: stay 回调次数 = 2
   逻辑帧 1: stay 回调次数 = 4
   逻辑帧 2: stay 回调次数 = 4
   总: start=2 stay=10 end=0        (2 物体 → 稳态每帧每物体 2 次)
   ```
8. 证伪结论：失败——(b) 路径可复现。

**正手（证真链）**
1. 位置：engine.py:1031-1035 与 loom_lighting.py:737-744 的双派发点。
2. 契约：同第 1 段。
3. 路径枚举：同证伪链。
4. 实际行为：见上。
5. 差异方向：多派发一次 stay。
6. 触发条件：同证伪链第 6 段。
7. 验证：同证伪链第 7 段。
8. 判定：**P-PROVED，P2（回调语义错误；持续伤害/持续触发类玩法受影响）**。附加风险：异步逻辑线程下，两次派发分别发生在逻辑线程与渲染线程，脚本回调跨线程并发（`_colliding` 写与脚本状态读无锁）。

### P-05 [P-PROVED / P2] `scale` setter 接受长度 <3 的序列 → 矩阵/SoA 路径 IndexError（渲染帧内崩溃）

**反手（证伪链）**
1. 判定基准：`TransformComponent.scale` setter（loom_components.py:69-74）无长度/类型校验；`loom_transform.py:55-57` 与 `104-106` 假定 `s[0..2]` 存在；`GameObject.scale` setter 同样只 `tuple(v)`（loom_game_object.py:117-121）。
2. 代码证据：见左；另外 `sceneio.py:176` 走 `_f3(...)` 恒 3 分量、EAI `agent_commands.py:1010-1014` 按现有列表下标改值 → 内部调用方不会产生短序列。
3. 路径枚举：
   - (a) 脚本直接 `m.scale = (1, 2)` → 存储成功 → 下一次 `compute_world_matrices` / `model_world_matrix` / `_transform_snapshot` 抛 IndexError（缺陷路径）。
   - (b) 场景加载（sceneio `_f3`）恒 3 分量 → 安全。
   - (c) EAI set_transform（按 `cur` 下标改）→ 安全。
   - (d) 长度 >3：存储为长 tuple，矩阵只用前 3 个，序列化 `list(m.scale)` 会写出 4 个；不崩溃但语义不闭合。
4. 实际行为：短序列在帧内抛 IndexError（无捕获点，向上冒泡终止渲染帧/逻辑帧）。
5. 差异：预期“非法 scale 被拒绝或钳制”，实际“接受后在热路径崩溃”。
6. 触发条件：脚本/插件直接写 `obj.scale`（含 `obj.scale = [1,2]`、错误参数化脚本）。
7. 验证：probe_parent.py：
   ```
   m.scale=(1,2) 接受; 存储: (1.0, 2.0)
   compute_world_matrices -> IndexError tuple index out of range
   model_world_matrix -> IndexError tuple index out of range
   ```
8. 证伪结论：失败——(a) 路径成立。

**正手（证真链）**
1. 位置：loom_components.py:69-74；loom_transform.py:55-57、104-106。
2. 契约：`position/rotation/scale` 三元语义（GameObject docstring“position/rotation/scale 委托”）。
3. 路径枚举：同证伪链。
4. 实际行为：见上。
5. 差异方向：缺少 setter 层边界校验。
6. 触发条件：同证伪链第 6 段。
7. 验证：同证伪链第 7 段。
8. 判定：**P-PROVED，P2（边界输入崩溃；合法内部调用方不触发）**。

### P-06 [P-PROVED / P2] `min_distance` setter 不重钳 `max_distance` → 违反音频契约 §43 后置条件

**反手（证伪链）**
1. 判定基准：`docs/design/3D音频系统契约_20261018.md:43` 后置条件“min_distance > 0；max_distance > min_distance”；loom_components.py:243 注释“必须严格大于 min_distance”。
2. 代码证据：loom_components.py:230-245（max setter 有 `if f <= lo: f = lo*2`）、:218-228（min setter 只判 `f>0`，不回头改 max）。
3. 路径枚举：
   - (a) 构造期（`__init__` 先 min 后 max）→ max 被钳 → 契约成立。
   - (b) 后期只改 min（min > 当前 max）→ 契约破坏（缺陷路径）。
   - (c) 再改 max=500（< min）→ 被钳到 min*2=20000（自愈但语义意外）。
   - (d) EAI `set_audio_3d`（契约 §181 返回 error）在命令层单独校验 → 走 EAI 不破坏；脚本直写字段绕过。
4. 实际行为：min>max 的组合可持久存在并传入 `audio.play_spatial`（loom_frame_components.py:59-63）→ game-audio `set_sound_max_distance`。
5. 差异：预期后置条件恒真，实际可被破坏。
6. 触发条件：脚本/组件层先设 max，再设更大的 min。
7. 验证：probe_batch.py 第 4 段：
   ```
   default min/max/rolloff: 1.0 500.0 1.0
   after min_distance=10000: min=10000.0 max=500.0
   max_distance=500 after min=10000 -> min=10000.0 max=20000.0
   ```
8. 证伪结论：失败——(b) 路径成立且契约文本明确。

**正手（证真链）**
1. 位置：loom_components.py:218-245。
2. 契约：同第 1 段。
3. 路径枚举：同证伪链。
4. 实际行为：见上。
5. 差异方向：setter 之间不变量未闭合。
6. 触发条件：同证伪链第 6 段。
7. 验证：同证伪链第 7 段。
8. 判定：**P-PROVED，P2（契约违例；外部可观察行为需与 audio_backend 联合确认，见 §5-Q4）**。

### P-07 [P-PROVED / P3] `Material(color=<unhashable>)` 抛 TypeError，与 `_hex_rgba` 的“失败回退灰色”承诺冲突

**反手（证伪链）**
1. 判定基准：`loom_color._hex_rgba` docstring：“'#RRGGBB' -> (r,g,b,alpha=1.0) float 元组（失败回退灰色 .5）”；`Material.__init__` docstring：“color: 单色覆盖（hex 字符串）或 None”。
2. 代码证据：loom_color.py:15 `t = _HEX_RGBA_CACHE.get(c)` 位于 try 之外；loom_material.py:58-62 setter 调用 `_hex_rgba(v)` 并 `np.asarray`。
3. 路径枚举：
   - (a) 合法 hex 字符串 / None → 正常。
   - (b) hashable 非法值（int/tuple/坏字符串）→ dict.get 成功 → try 内解析失败 → 灰色（符合 docstring）。
   - (c) unhashable（list/ndarray/dict）→ dict.get 抛 TypeError（缺陷路径，未被 try 捕获）。
   - (d) 调用方：Material.__init__/color setter、GameObject.color/engine.add_material(color=...)（sceneio.py:184/499 直接透传 JSON 字段）。
4. 实际行为：TypeError 逃逸到加载/脚本层。
5. 差异：预期灰色回退，实际异常。
6. 触发条件：脚本 `m.color = [1,0,0]` / `Material(color=np.array(...))`；或 schema 外的场景 JSON。
7. 验证：probe_batch.py 第 3 段：
   ```
   color='#112233' -> ok; color=None -> ok; color=123 -> ok 灰; color='bad' -> ok 灰;
   color=(1,2,3) -> ok 灰; color=[1,2,3] -> TypeError: unhashable type: 'list'
   ```
8. 证伪结论：失败——(c) 路径成立。

**正手（证真链）**
1. 位置：loom_material.py:57-62；loom_color.py:15（跨模块根因）。
2. 契约：同第 1 段。
3. 路径枚举：同证伪链。
4. 实际行为：见上。
5. 差异方向：缓存键取值早于容错分支。
6. 触发条件：同证伪链第 6 段。
7. 验证：同证伪链第 7 段。
8. 判定：**P-PROVED，P3（Material 契约只允许 hex/None，合法输入不触发；属健壮性缺口）**。

### P-08 [P-PROVED / P3] `_batch_rotations` 为死代码（无调用方，文件头却列为渲染矩阵成员）

**反手（证伪链）**
1. 判定基准：无“必须存在”的契约；判据为实际引用面。
2. 代码证据：loom_transform.py:277-306 定义；loom_transform.py:12 文件头把 `_batch_rotations` 列为“段B 渲染矩阵”成员。
3. 路径枚举：全库 grep `_batch_rotations` → 仅定义处 + scheduler.py:186 注释提及（无调用）；`compute_render_matrices` 走 `pipeline_glue.interp_world`，`compute_world_matrices` 走 `pipeline_glue.world_matrices`。
4. 实际行为：永不执行。
5. 差异：文档声明“在用”，实际死代码。
6. 触发条件：N/A。
7. 验证：`grep -rn "_batch_rotations" --include=*.py` 输出 2 行（定义 + scheduler 注释）；`grep -rn "_batch_rotations("` 0 命中。
8. 证伪结论：失败——“无调用方”是可证实事实。

**正手（证真链）**
1. 位置：loom_transform.py:277-306、:12。
2. 契约：文件头职责清单。
3. 路径枚举：同上。
4. 实际行为：见上。
5. 差异方向：文档承诺 vs 实现。
6. 触发条件：N/A。
7. 验证：同证伪链第 7 段。
8. 判定：**P-PROVED，P3（可维护性；AUDIT-DEADCODE）**。


### P-09 [P-PROVED / P2] `GameObject.parent` setter（文档标注的“旁路挂父”路径）不维护 `children` → collect_subtree/remove_subtree 误删/误遍历

**反手（证伪链）**
1. 判定基准：父子不变量 `child.parent is p ⇔ child in p.children`（`set_parent` docstring“换父（children 列表重建）”）；`remove_subtree`/`collect_subtree` 以 `children` 为唯一遍历源（loom_transform.py:393-398、loom_model_gpu.py:304-313）。
2. 代码证据：loom_game_object.py:122-138（setter 只写 `self.transform.parent = v` + 对活引擎 `_bump_struct`；不碰 children）；loom_transform.py:373-379（`set_parent` 才维护 children）。
3. 路径枚举：
   - (a) 走 `set_parent` → 不变量成立。
   - (b) 走 `GameObject.parent` setter（注释明确“脚本/编辑器直写”支持）→ 旧父 children 残留、新父 children 缺失 → 不变量破坏（缺陷路径）。
   - (c) sceneio 加载：`m.parent = par; par.children.append(m)`（sceneio.py:300-307）手工补齐全 → 不受影响。
   - (d) 仅改指针再 `set_parent`：`if child.parent is new_parent: return`（loom_transform.py:366）会跳过修复。
4. 实际行为：同一子物体同时被旧父的 children 与新父的 parent 指针指向。
5. 差异：预期删除 P 时只删 P 子树，实际 `remove_subtree(P)` 会连带删除已改挂到 Q 的 C。
6. 触发条件：脚本 `c.parent = q`（或任何未同时维护 children 的直写）。
7. 验证：probe_children.py：
   ```
   after set_parent(c,p): P.children= ['C'] c.parent= P
   after c.parent=q 直写: P.children= ['C'] Q.children= [] c.parent= Q
   collect_subtree(P) = ['P', 'C']
   collect_subtree(Q) = ['Q']
   ```
8. 证伪结论：失败——(b) 路径可复现。

**正手（证真链）**
1. 位置：loom_game_object.py:122-138。
2. 契约：`set_parent` 的 children 维护语义 + setter 注释“旁路挂父”。
3. 路径枚举：同证伪链。
4. 实际行为：见上。
5. 差异方向：两个挂父入口的语义不一致。
6. 触发条件：同证伪链第 6 段。
7. 验证：同证伪链第 7 段。
8. 判定：**P-PROVED，P2（结构不变量破坏；修复方向依赖 §5-Q3 的父子语义裁决）**。

### P-10 [P-PROVED / P2] 父物体被 `remove_model` 删除后，批量矩阵与递归矩阵世界位置分叉（违反“数值一致”契约）

**反手（证伪链）**
1. 判定基准：loom_transform.py:124 “（compute_world_matrices）与逐模型 model_world_matrix 数值一致”；loom_model_gpu.py:261 “删除单个模型…解除父链引用”。
2. 代码证据：loom_transform.py:209-214（`parent[i] = id2i.get(id(m.parent), -1)`，缺失父按 -1 根处理）vs :53-60（递归无条件沿 `m.parent` 合成）；loom_model_gpu.py:297-300（只清被删物体自己的 parent，不清子物体的 parent）。
3. 路径枚举：
   - (a) 正常父子（父在 models 中）→ 两路一致。
   - (b) `remove_model(parent)` 且子仍在 models → 批量按根、递归沿悬空父 → 分叉（缺陷路径）。
   - (c) `remove_subtree(root)` → 父子一起删，不触发。
   - (d) sceneio 加载（未出现缺失父）→ 正常。
4. 实际行为：子物体在批量路径用局部坐标（视作根），在 world_position/get_bounding_box（传 M=None）路径用“悬空父 + 局部”的世界坐标。
5. 差异：预期两路一致，实际分叉。
6. 触发条件：单物体删除父，保留子（scripts.py:755 `e.remove_model(self.obj)`、editor.py 单删、undo.py remove_model）。
7. 验证：probe_misc2.py：
   ```
   挂父后批量/递归 C.x = 1.000 / 1.000
   remove_model(P) 后: models=['C'] c.parent='P'
     批量 C.x=-4.000  递归 C.x=1.000
   ```
8. 证伪结论：失败——(b) 路径成立。

**正手（证真链）**
1. 位置：loom_transform.py:209-214 vs :53-60；触发点 loom_model_gpu.py:260-300。
2. 契约：同第 1 段。
3. 路径枚举：同证伪链。
4. 实际行为：见上。
5. 差异方向：删除父后的父子语义未定义，两条读取路径各自实现。
6. 触发条件：同证伪链第 6 段。
7. 验证：同证伪链第 7 段。
8. 判定：**P-PROVED，P2（渲染/物理读到的世界位置与脚本 API 不一致）**；修复方向取决于 §5-Q3。

### P-11 [P-PROVED / P3] 空网格使 `_homogeneous_vertices`/`get_bounding_box` 崩溃

**反手（证伪链）**
1. 判定基准：`get_bounding_box` 对任意 Mesh 返回 AABB（docstring 无前置条件）；`Mesh.vertices` 允许为空（mesh.py:25-36 `_validate` 对 0 顶点无断言）。
2. 代码证据：loom_transform.py:425-426（`np.asarray([])` → shape (0,)，`np.ones((0,1))`，`np.concatenate(axis=1)` 需要 2 维）；:409-410（min/max 归约）。
3. 路径枚举：
   - (a) 常规基元/OBJ（非空顶点）→ 正常。
   - (b) 空 OBJ 文件 → `load_obj` 主动抛 ValueError（probe 证实），不会构造空网格。
   - (c) 直接 `Mesh([],[],[])`（公开构造器，校验通过）→ 崩溃（缺陷路径）。
   - (d) 只有 1 个顶点 → `w3t` shape (3,1) min/max 正常。
4. 实际行为：AxisError（`axis 1 is out of bounds for array of dimension 1`）。
5. 差异：预期退化 AABB 或明确拒绝，实际热路径异常。
6. 触发条件：脚本/工具构造空网格并挂物体；随后的 AABB/阴影/碰撞 prep 崩溃。
7. 验证：probe_misc2.py 第 3 段：
   ```
   Mesh([],[],[]) ok; get_bounding_box -> AxisError axis 1 is out of bounds for array of dimension 1
   空 .obj -> ValueError obj 无顶点/面
   ```
8. 证伪结论：失败——(c) 路径成立。

**正手（证真链）**
1. 位置：loom_transform.py:414-430、400-412。
2. 契约：同第 1 段。
3. 路径枚举：同证伪链。
4. 实际行为：见上。
5. 差异方向：空集合归约无守卫。
6. 触发条件：同证伪链第 6 段。
7. 验证：同证伪链第 7 段。
8. 判定：**P-PROVED，P3（合法但罕见的构造器输入；无内部生产者）**。

### P-12 [P-DISPROVED] AnimationClip 快路径 vs 慢路径：随机合法输入下逐位一致

**反手（证伪链）**
1. 判定基准：`AnimationClip` docstring 275-277 “语义以旧实现为准，逐位一致——含首段 t 早于首帧时间的负 f 外推、span<=0 时 f=0.0、末帧保持原对象”。
2. 代码证据：loom_components.py:345-377（快路径）vs 379-399（慢路径）；关键同序：`f = 0 if span<=0 else (t-prev_t)/span`；`a + (b-a)*f`（减→乘→加）。
3. 路径枚举（fuzz 覆盖）：
   - 时间序列：非降序、重复时间（span=0）、t 早于首帧、t 等于帧点、t 越过末帧、dur>0 取模后的 t。
   - 分量：float/int/负零/1e-9，全部 3 通道齐备（快路径前提）。
   - 慢路径特例：NaN t（快路径显式返回末帧原值，与慢路径扫完一致）；`dur<=0` 不取模。
4. 实际行为：24702 个用例逐位相等。
5. 差异：无。
6. 触发条件：N/A。
7. 验证：probe_batch.py 第 2 段：`差分用例: 24702  不一致: 0`（400 组随机帧 × 平均 62 个 t，含负 t/边界 t）。
8. 证伪结论：**成功**（在快路径启用条件域内未找到反例；域外输入按设计降级慢路径，见 SKIP-01）。

**正手（证真链）尝试**：尝试构造“快路径启用但语义不同”的输入——重复时间、t 恰在重复点、负 t、末帧 t<=0、整型时间——均返回与慢路径相同结果；证真失败。
**裁决**：**P-DISPROVED**（附证据：probe 输出；该结论仅覆盖“快路径已启用且 frames 未原地变更”的域）。

### P-13 [P-PROVED / P2，与 02_scene P-14 重复] `set_parent(preserve_world=True)` 在万向锁奇点（β=±π/2）改变世界旋转

**反手（证伪链）**
1. 判定基准：loom_transform.py:355-358 “挂父/脱父那一下物体不会跳。位置用 world_to_local，旋转 R_local = R_world @ inv(R_parent)，缩放分量相除”。
2. 代码证据：:362-391 全流程；`world_to_local`（:337-341）用父世界矩阵求逆；`decompose_euler`（matlib）还原欧拉。
3. 路径枚举：
   - (a) 随机连续欧拉（含非均匀缩放、非单位父旋转）× 200 组 → 守恒（pos 2.66e-15 / rot 1.22e-15 / scale 4.44e-16）。
   - (b) 子物体世界旋转恰在万向锁 β=±π/2 → `decompose_euler` 奇点分支 → 世界旋转改变（缺陷路径，probe_gimbal 实测 1.68 rad）。
   - (c) 位置/缩放路径不经过 decompose_euler → 仍守恒。
4. 实际行为：随机域守恒；奇点域不守恒。
5. 差异：预期“世界旋转不变”，实际在 β=-π/2 时差 1.6829419696 rad。
6. 触发条件：挂父对象当前世界旋转的欧拉分解落在 β=±π/2（或接近奇点的病态区）。
7. 验证：probe_gimbal.py（新增）：
   ```
   child local rotation after set_parent: (-1.0, -1.570796, 0.0)
   world rotation max diff: 1.682941969615793
   ```
   另 probe_parent.py 第 1 段：`set_parent preserve_world fuzz: 200 组, 超差 0`（随机域不含奇点）。
8. 证伪结论：失败——(b) 路径成立（随机 fuzz 因奇点零测度而漏检；补充定向探针后暴露）。

**正手（证真链）**
1. 位置：loom_transform.py:385-389（`Rl = wr @ inv(Rp); decompose_euler(Rl)`）；根因在 `matlib.decompose_euler` 的 β=±π/2 分支。
2. 契约：set_parent docstring“世界旋转不变”。
3. 路径枚举：同证伪链。
4. 实际行为：见上。
5. 差异方向：欧拉分解奇点符号/自由度选择导致重建矩阵不同。
6. 触发条件：同证伪链第 6 段。
7. 验证：同证伪链第 7 段。
8. 判定：**P-PROVED，P2**。**去重说明**：`_scan_ledger.md` 的 02_scene P-14 已记录“decompose_euler 万向锁 β=-90° 符号错（set_parent 实测世界旋转差 1.93）”；本项为同一缺陷在 set_parent 侧的独立复现（数值 1.68 与 1.93 的差异来自所选测试角不同），修复应落在 matlib（模块 02）或 set_parent 改用矩阵/四元数中间层，避免两个模块各修一半。

### P-14 [P-DISPROVED] engine.py 未提交 diff `import sys` 未引入缺陷，且确实修复了 LOOM_SWITCH_INTERVAL 静默失效

**反手（证伪链）**
1. 判定基准：engine.py:494-502 注释“经 LOOM_SWITCH_INTERVAL 可调（秒）”；diff 仅新增 `import sys`。
2. 代码证据：engine.py:32（新增）、:497-502（`sys.setswitchinterval(float(_si))` 在 try/except 内）。
3. 路径枚举：
   - (a) 未设置环境变量 → `_si` 为 None → 不调用（无行为变化）。
   - (b) 设置合法值 → 调用生效（probe：0.005→0.001）。
   - (c) 设置非法值 → float 抛错被 `except Exception: pass` 吞掉（旧行为一致）。
   - (d) 旧代码无 `import sys` → (b) 触发 NameError → 被同一 except 吞掉 = 静默失效（修复动机成立）。
4. 实际行为：修复生效。
5. 差异：无。
6. 触发条件：N/A。
7. 验证：probe_misc.py 第 1 段：
   ```
   before engine init: 0.005000
   after  engine init: 0.001000   (env LOOM_SWITCH_INTERVAL=0.001)
   ```
8. 证伪结论：**成功**——找不到该 diff 引入的新缺陷；且修复是必要的。

**正手（证真链）尝试**：检查重复导入/名称遮蔽（engine.py 无其他 `sys` 定义；模块级 `import sys` 无副作用）→ 证真失败。
**裁决**：**P-DISPROVED**（该 diff 不是 [REGRESSION]）。

### P-15 [P-DISPROVED] f0ad76a 新增 `draw_screen_lines/draw_screen_polygon/_px_to_ndc` 边界冒烟

**反手（证伪链）**
1. 判定基准：engine.py:772-813 docstring（pts_2d 像素坐标、color 0-255、width>=1、close 闭合）。
2. 代码证据：:757-761（NDC 端点）、:772-775（短输入早退）、:800-801（颜色 3/4 分量归一）。
3. 路径枚举：2 点线 / 空列表 / 单点 / close=True / 3 点多边形 / 2 点多边形 / width=5 / 3 色 / 4 色（alpha）。
4. 实际行为：全部无异常；`_px_to_ndc(0,0)=(-1,1)`、`(320,240)=(1,-1)` 符合“像素 y 向下 → NDC y 向上”。
5. 差异：无。
6. 触发条件：N/A。
7. 验证：probe_draw2d.py 输出（7 个用例全 ok；NDC 端点见上）。
8. 证伪结论：**成功**（仅冒烟级；像素级正确性归 03/06 模块）。

**正手（证真链）尝试**：空/单点/短颜色均被早退或补齐；证真失败。
**裁决**：**P-DISPROVED**（域：调用不抛异常 + NDC 端点正确；未做像素级渲染比对）。

---

## 3. 统计（阶段三）

| 四象限 | 数量 | 条目 |
|---|---|---|
| P-PROVED | 12 | P-01、P-02、P-03、P-04、P-05、P-06、P-07、P-08、P-09、P-10、P-11、P-13 |
| P-DISPROVED | 3 | P-12、P-14、P-15 |
| P-UNKNOWN | 0 | — |
| P-CONTRADICTION | 0 | — |
| 合计 | 15 | 粗筛 15 项全部走完双向链 |

等级分布（PROVED）：P1 ×2（P-01、P-02）；P2 ×7（P-03、P-04、P-05、P-06、P-09、P-10、P-13）；P3 ×3（P-07、P-08、P-11）。
去重：P-13 与 02_scene P-14 为同一缺陷（matlib.decompose_euler 万向锁），本模块只做 set_parent 侧复现，修复方不是本模块。
[REGRESSION]：0（§0.4；本模块唯一未提交 diff 为 P-14，判为正确修复）。
跳过留痕：8 项（SKIP-01..08，均给四类理由之一）；越界声明 3 项（§1.2）。
探针：13 个（全部新增于临时目录，仓库内未新增/修改任何文件；`git status --porcelain` 审计前后逐行一致）。

---

## 4. 修复建议排序（只给方向，不含代码）

1. **P-01（P1）**：让播放态逻辑矩阵与插值快照可失效——在 `_logic_prep` 判定中纳入变换代（`TransformComponent._xform_gen`）或直接调用 `compute_world_matrices`（其 `_fw_cache` 在静止帧命中，成本近 0）；同时 `_logic_frame` 不应把可能过期的 `_soa_snap` 平面喂给 `InterpState.advance`。另一种最小改法：Editor 播放分支每帧显式 `_frame_world = None` / 走与基类一致的刷新点——但需保持 Player 路径不变。
2. **P-02（P1）**：split 播放态在“小场景 / 无 `_frame_pool`”时回落到 `_update_collision_events` 内联检测（实现设计文档承诺的“小场景走旧内联”），或无条件计算 pairs（n<32 时 O(n²) 便宜）。
3. **P-03（P2）**：给脚本组件增删建立独立失效键（如 `GameObject._script_gen`），`add_script/remove_script/clear_scripts` bump；`update_scripts` 的早退缓存同时比较该键。不要直接复用 `_bump_struct`（会连带失效 SoA/ancestry，造成无谓重算）。
4. **P-04（P2）**：碰撞对派发保持单一所有者——要么删除 `_logic_frame` 内的派发（渲染帧节流派发为唯一权威），要么让渲染侧只读 `_disp_gen` 不再派发；并在跑合后回归 stay 计数（每逻辑帧 1 次/物体）。
5. **P-05（P2）**：`scale` setter 校验长度==3（或补齐默认 1.0），与 `position/rotation` 的构造期校验对齐。
6. **P-06（P2）**：`min_distance` setter 反向重钳 `max_distance`（或两 setter 共用一个校验函数），保证契约 §43 恒成立。
7. **P-09（P2）**：`GameObject.parent` setter 改为委托 `set_parent(v, preserve_world=False)`（同时维护 children 与结构代），或明确降级为“低层 API”并禁止脚本使用（需人类裁决 §5-Q3）。
8. **P-10（P2）**：明确“删父留子”语义：a) `remove_model` 递归删除子树（Unity 语义）；或 b) 删除父子提升为根并同步 children；同时让 `model_world_matrix/world_position` 对“父不在 models 中”的情形与批量路径一致。
9. **P-07（P3）**：`_hex_rgba` 先做 `isinstance(c, str)` 判定再进缓存，天然兜住 list/ndarray（属模块 10 的 loom_color，需与 10 号审计合并修复）。
10. **P-08（P3）**：删除 `_batch_rotations` 或接入实际渲染矩阵路径；同步修正文件头职责清单。
11. **P-11（P3）**：`_homogeneous_vertices` 对 `verts.shape[0]==0` 返回 (0,4) 空数组，`get_bounding_box` 对 0 顶点返回退化 AABB（mn=mx=局部原点经 M 变换）。
12. **P-13（P2，跨模块去重）**：根因在 `matlib.decompose_euler` 的 β=±π/2 分支（02_scene P-14 已登记）；修复优先在 matlib，或让 `set_parent` 以旋转矩阵/四元数为中间量写回、仅在非奇点调用 decompose_euler。本模块不单独修。

---

## 5. 需要人类裁决的封闭问题

1. **Q1（P-01 优先级）**：编辑器 `toggle_play` 的 GL 播放渲染是否仍在维护目标内？若用户实际只用 `Loom.py --run` / PlayerApp（基类 render 不受影响），P-01 是否按“编辑器功能 P1”修复，还是降级/延后？
2. **Q2（P-02 意图）**：《分离批5_6 架构重对齐》写明“小场景: 事件走旧内联（改4）”，但代码未实现。请确认：小场景碰撞事件是“应实现的内联兜底”，还是“有意只保证大场景（性能取舍）”？若是后者，需在脚本 API 文档标注该限制。
3. **Q3（父子删除语义，决定 P-09/P-10 修复方向）**：删除一个仍有子物体的父对象时，期望语义是 —— (A) Unity 式：连同整棵子树一起删除；还是 (B) 子物体提升为根并保持世界位姿；(C) 其它？直接 `GameObject.parent = p` 的直写是否仍作为受支持 API（必须维护 children），还是应废弃？
4. **Q4（P-06 音频不变量）**：组件层是否需要自愈（脚本直写绕过 EAI 校验时仍保证 max>min），还是维持“只有 EAI 命令层校验”的现状？
5. **Q5（P-04 权威派发点）**：碰撞事件应以“逻辑帧内派发”为唯一权威（渲染侧只做 UI 同步），还是以“渲染帧节流派发”为唯一权威？这决定删除哪一侧以及异步逻辑线程下脚本回调运行在哪个线程。

---

## 附录：探针原样代码（与 §2 实测输出一一对应）

> 说明：运行前 `sys.path` 指向 Loom 目录；所有探针不写仓库文件（仅 P-11 的 OBJ 临时文件写到系统临时目录并在 finally 删除）。

### A1 `probe_stale_fw2.py`（P-01 纯引擎）
```python
# -*- coding: utf-8 -*-
import os, sys
sys.path.insert(0, r"D:/my-project - 副本/Loom(py源代码-工作区)/Loom")
os.environ['LOOM_NO_PARALLEL'] = '1'; os.environ['LOOM_NO_SAVE_MIGRATE'] = '1'
import moderngl, engine as E
from loom_types import Point3D
E.GLEngine._build_gpu = lambda self, m: None

def make():
    ctx = moderngl.create_standalone_context()
    eng = E.GLEngine(320, 240, ctx=ctx)
    eng.is_playing = True
    m = eng.models[0]; m.position = Point3D(0.0, 0.0, 0.0)
    eng._frame_world = eng.compute_world_matrices(eng.models)   # editor.py:1936 编辑态写入
    eng._prep_sig = None; eng._aabb_row_cache = None; eng._prep_aabbs = None
    if eng._interp is not None:
        eng._interp.advance(); eng._interp.align()
    return eng, m

print("=== A: prep AABB vs 实际位形 ===")
eng, m = make(); fw0 = id(eng._frame_world)
for i in range(5):
    m.position = Point3D(2.0*i, 0.0, 0.0)
    eng._logic_frame(eng._clock.fixed_dt)
    print("frame %d actual.x=%.2f prep_aabb.x=%s id(fw)_same=%s"
          % (i, m.position.x, eng._prep_aabbs[0][0].x, id(eng._frame_world) == fw0))
fw_now = eng.compute_world_matrices(eng.models)
print("final fresh_aabb.x=%.2f  (actual.x=%.2f)" % (
    eng._model_aabbs_par(eng.models, fw_now, visible_only=False)[0][0].x, m.position.x))

print("=== B: 插值平面 / 渲染矩阵 ===")
eng2, m2 = make()
for i in range(5):
    m2.position = Point3D(2.0*i, 0.0, 0.0)
    eng2._logic_frame(eng2._clock.fixed_dt)
    pos, _r, _s = eng2._interp.render_pose(0.0, eng2.models)
    cur = float(eng2._interp._curr[0, 0]) if eng2._interp._curr is not None else None
    print("frame %d actual.x=%.2f interp_curr.x=%s render_pose.x=%.4f"
          % (i, m2.position.x, cur, float(pos[0, 0])))
```

### A2 `probe_editor_play.py`（P-01 真实 EditorApp，同步）
```python
# -*- coding: utf-8 -*-
import os, sys
BASE = r"D:/my-project - 副本/Loom(py源代码-工作区)/Loom"
sys.path.insert(0, BASE); os.chdir(BASE)
os.environ['LOOM_NO_SAVE_MIGRATE'] = '1'
os.environ['LOOM_LOGIC_SYNC'] = '1'; os.environ['LOOM_NO_PARALLEL'] = '1'
import moderngl, editor as editor_mod
from loom_types import Point3D
from mesh import create_cube
ctx = moderngl.create_standalone_context()
ed = editor_mod.EditorApp(320, 240, ctx=ctx)
ed._external_fb = ctx.detect_framebuffer()
try:
    _g = ed.view.gui.render
    ed.view.gui.render = lambda *a, **k: _g(target=ed._external_fb)
except Exception:
    pass
for m in list(ed.models):
    ed.remove_model(m)
m = ed.add_model(create_cube(1.0), Point3D(0, 0, 0), Point3D(0, 0, 0), name='probe')
for _ in range(2):
    ed.render(1.0 / 60.0)
print("edit render ok; _frame_world is None:", ed._frame_world is None)
ed.toggle_play()
for i in range(5):
    m.position = Point3D(2.0 * i, 0.0, 0.0)
    ed.render(1.0 / 60.0)
    print("frame %d actual.x=%.2f _render_world[0].tx=%.2f _frame_world[0].tx=%.2f logic_gen=%s"
          % (i, m.position.x, float(ed._render_world[0][3][0]),
             float(ed._frame_world[0][3][0]), getattr(ed, '_logic_gen', None)))
ed.toggle_play(); ed._stop_parallel(); import pygame; pygame.quit()
```

### A3 `probe_editor_async2.py`（P-01 真实 EditorApp，生产默认异步）
```python
# 与 A2 相同，区别：
#   os.environ.pop('LOOM_LOGIC_SYNC', None)
#   toggle_play() 后：clk = ed._ensure_split(); ed._start_logic_thread(clk)
#   循环 80 次：改位 -> ed.render(1/60) -> time.sleep(0.004)
#   退出：ed._stop_logic_thread(); ed.toggle_play(); ed._stop_parallel()
```

### A4 `probe_collision_events2.py` / `3.py`（P-02）
```python
# -*- coding: utf-8 -*-
import os, sys
BASE = r"D:/my-project - 副本/Loom(py源代码-工作区)/Loom"
sys.path.insert(0, BASE); os.chdir(BASE)
os.environ['LOOM_NO_SAVE_MIGRATE'] = '1'; os.environ['LOOM_NO_PARALLEL'] = '1'
import engine as E, parallel
from loom_types import Point3D
from mesh import create_cube
from loom_components import ScriptComponent
E.GLEngine._build_gpu = lambda self, m: None

def make(n_models, pool=None):
    eng = E.GLEngine.__new__(E.GLEngine)
    eng.models = []; eng.materials = []; eng.lights = []; eng.cameras = []
    eng._struct_gen = 0; eng._logic_gen = 0; eng.is_playing = True
    eng._split_enable = True; eng._logic_async = False
    eng._prep_aabbs = None; eng._prep_light_vps = None; eng._prep_pairs = None
    eng._prep_sig = None; eng._disp_gen = -1; eng._frame_pool = pool
    eng._stage_times = {}; eng._stage_calls = {}
    for i in range(n_models):
        m = E.GameObject(create_cube(1.0), Point3D(i * 0.25, 0, 0),
                         Point3D(0,0,0), name='m%d' % i)
        eng.models.append(m)
    eng._frame_world = eng.compute_world_matrices(eng.models)
    return eng

class FakeScript:
    order = 0
    def update(self, dt): pass
    def on_collision_start(self, other): hits.append(other.name)

for label, n, pool in (("n=3 无池", 3, None), ("n=3 有池", 3, 'POOL'), ("n=40 无池", 40, None)):
    eng = make(n)
    if pool == 'POOL':
        eng._frame_pool = parallel.FramePool(2, 0)
    hits = []
    for m in eng.models:
        sc = ScriptComponent('probe'); sc._script = FakeScript(); sc._script_broken = False
        m.scripts.append(sc)
    eng._logic_prep(1/30)
    print("%s: _prep_pairs=%r" % (label, eng._prep_pairs[:3]))
    eng._parallel_shadow_and_collision(1/60, with_events=True)
    print("   -> split 派发后 callbacks =", len(hits))
    eng._update_collision_events(1/60)
    print("   -> 再跑旧内联后累计 =", len(hits))
    if pool == 'POOL':
        eng._frame_pool.shutdown()
# 8c: 只测 _prep_pairs 长度: n=3 有池 -> 0 ; n=40 有池 -> 114
```

### A5 `probe_batch.py`（P-03 / P-06 / P-07 / P-12）
```python
# 1) update_scripts 缓存
import script_glue as sg; sg.handle = lambda: None
calls = []
class FakeScript:
    order = 0
    def update(self, dt): calls.append(dt)
sc = E.ScriptComponent('probe_script'); sc._script = FakeScript()
fake_model = types.SimpleNamespace(scripts=[], name='m0')
eng = E.GLEngine.__new__(E.GLEngine)
eng.models = [fake_model]; eng._struct_gen = 0
eng.update_scripts(1/60)                 # has_scripts=False 入缓存
fake_model.scripts.append(sc)            # 等价 add_script（不 bump _struct_gen）
eng.update_scripts(1/60)
eng._struct_gen += 1; eng.update_scripts(1/60)   # 只有 bump 后才执行

# 2) AnimationClip fast vs slow 差分（400 组随机帧 × 每帧约 62 个 t）
#    clip = AnimationClip(frames); assert clip._np_fast
#    对每个 t: clip.sample(t) == clip._sample_slow(t)
#    -> 差分用例 24702, 不一致 0

# 3) Material 颜色: '#112233'/None/123/'bad'/(1,2,3) 均 ok; [1,2,3] -> TypeError: unhashable type: 'list'
# 4) AudioSourceComponent: 默认 1/500; min=10000 后 max 仍 500; 再 max=500 -> 20000
```

### A6 `probe_double_dispatch2.py`（P-04）
```python
# 2 个模型，各挂 fake script（覆盖 on_collision_start/stay/end）
# _prep_pairs = [(0, 1)]; _split_enable=True; is_playing=True; _disp_gen=-1
for frame in range(3):
    stay0 = calls['stay']
    eng._dispatch_collision_events(eng._prep_pairs)      # engine.py:1034
    eng._logic_gen += 1
    eng._parallel_shadow_and_collision(1/60, with_events=True)  # loom_lighting.py:737-744
    print("逻辑帧 %d: stay = %d" % (frame, calls['stay'] - stay0))
# 实测: 逻辑帧0=2, 逻辑帧1=4, 逻辑帧2=4  (2 物体 -> 稳态每帧每物体 2 次)
```

### A7 `probe_parent.py`（P-05 / P-13）
```python
# 200 组随机父子（位置/旋转/非均匀缩放）:
#   set_parent(c, p, preserve_world=True) 前后比较 world_position / world_rotation_matrix / world_scale
#   实测: 超差 0; 最大偏差 pos=2.66e-15 rot=1.22e-15 scale=4.44e-16
# 批量 vs 递归（正常父子）: 最大差 3.55e-15
# m.scale = (1.0, 2.0) -> compute_world_matrices / model_world_matrix -> IndexError tuple index out of range
```

### A8 `probe_children.py`（P-09）
```python
p = mk('P'); q = mk('Q'); c = mk('C')
eng.set_parent(c, p)        # P.children=['C'], c.parent=P
c.parent = q                # 文档标注的"旁路挂父"
# 实测: P.children=['C'], Q.children=[], c.parent=Q
#       collect_subtree(P)=['P','C'], collect_subtree(Q)=['Q']
```

### A9 `probe_misc2.py`（P-10 / P-11）
```python
# 挂父后: 批量/递归 C.x = 1.000 / 1.000
# remove_model(P) 后: models=['C'] c.parent='P'
#   批量 C.x=-4.000  递归 C.x=1.000      <- 分叉
# Mesh([],[],[]) -> get_bounding_box -> AxisError axis 1 is out of bounds for array of dimension 1
# 空 .obj -> ValueError obj 无顶点/面 (load_obj 主动拒绝)
```

### A10 `probe_misc.py`（P-14）
```python
os.environ['LOOM_SWITCH_INTERVAL'] = '0.001'
print("before:", sys.getswitchinterval())     # 0.005
eng = E.GLEngine(320, 240, ctx=moderngl.create_standalone_context())
print("after :", sys.getswitchinterval())     # 0.001
```

### A11 `probe_draw2d.py`（P-15）
```python
# _px_to_ndc(0,0)=(-1.0, 1.0); _px_to_ndc(320,240)=(1.0, -1.0)
# 2 pt line / empty / 1 pt / closed 2 pt / polygon 3 / polygon 2 / width 5  -> 全 ok
```

### A12 `probe_gimbal.py`（P-13 补充探针）
```python
p = mk('P', (0,0,0), (0, 0, 0))
c = mk('C', (1,0,0), (0.3, -math.pi/2, 0.7))     # 世界旋转命中 β=-π/2
wr_before = eng.world_rotation_matrix(c)
eng.set_parent(c, p, preserve_world=True)
wr_after = eng.world_rotation_matrix(c)
print("world rotation max diff:", float(np.max(np.abs(wr_after - wr_before))))
# 实测: child local rotation after set_parent: (-1.0, -1.570796, 0.0)
#       world rotation max diff: 1.682941969615793
```

---

*报告结束。全部结论只依赖上表命令与源码行号；未修改任何受跟踪文件。*
