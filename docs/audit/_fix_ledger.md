# 修复台账（滚动更新）

| 批次 | 状态 | 修复项 | 验收 | 报告 |
|---|---|---|---|---|
| R1_core_hygiene | **完成** | 物理桥日志节流、scale 全路径、parent 环保护、LOD 快路径 | ab_batch 22/22；run_all exit=0 | fix_r10.md |
| R5_stroke_line | **完成（负结论）** | line-list 实验无改善已回退；定位 alpha 差异主因是多边形填充 | 描边数值未劣化；多边形 alpha 修正后差异像素 10044→1073 | fix_r_vk_stroke.md |
| R2_plugin_residual | **完成** | 卸载清 sys.modules、TOCTOU、once 重入、调度器 mask/metrics/超时/shutdown | ab_batch 22/22；run_all exit=0（102 文件） | fix_r_scan09.md |
| R4_vk_multi_shadow | **完成** | VK 平行光阴影 1 → 2 张（binding 10/11），第 3 盏+ 警告无阴影 | ab_batch 22/22；probe MAE 0.000089（旧 0.004560）；run_all exit=0 | fix_r4_vk_two_dir_shadow.md |
| F7_scene_undo_misc | **完成** | 父链成环、材质孤儿、纯色 env、撤销全覆盖、Shape 撤销、文件对话框、FPS FBO、net cancel/charset、纹理 ctx release、guiloader | ab_batch 22/22；run_all exit=0；新增 8 测试 | fix_02_scene_misc_assets.md |
| F6_physics | **完成** | 建体位姿/AABB、祖先脏传播、子步异常、join 超时、桥异常禁用、tree_bit 回收、角速度恢复、glue 校验、万向锁 | ab_batch 22/22；run_all exit=0；physics_dll_val 逐位 0 | fix_08_physics.md |
| F8_engine_editor | **完成** | 播放态矩阵、小场景碰撞兜底、重复派发、脚本缓存、scale 归一化、删子树+确认、gizmo 代际 | ab_batch 22/22；run_all 89 文件 exit=0 | fix_08_core_editor.md |
| F9_transform_math | **完成** | 万向锁、set_parent 世界旋转、parent/children 不变式、scale 归一化 | ab_batch 22/22；run_all 74 文件 exit=0 | fix_01_02_core_scene.md |
| F3_eai_ui | **完成** | P0 ui_add 颜色、as_bool、object_select 报错、MCP 写白名单(realpath)、Qt 清空时机、多 Canvas 命中 Q7=C | ab_batch 22/22；UI 9e-8；run_all 绿 | fix_06_07_editor_ui_eai.md |
| F4_plugin_sandbox | **完成** | 两条 P0 沙箱逃逸、注册事务回滚、脚本 id 禁覆盖、事件 clear 延迟、Lua VM 释放 | ab_batch 22/22；UI 9e-8；run_all exit=0（70 文件） | fix_09_scripting.md |
| F5_player_backend | **完成** | 贴图导入设置、相机坏值、LOD 序列化+缓存、相机默认值、wheel 清零、回调链式转发、Q6 后端策略、LOOM_REMOTE_MODE | ab_batch 22/22；UI 9e-8；run_all 70 测试 exit=0；VK 真窗口出图 | fix_05_player.md |
| F1_vk_render | **完成** | 桶实例偏移(P1)、PBR 开关、法线回落、env 缓存、文本 LRU、wrap/filter、阴影灯数限制、死代码 | ab_batch 22/22；UI 9e-8；run_all exit=0（70 文件） | fix_vk_render_batch.md |
| F2_gl_lighting | **完成** | 聚光槽位 P0、面图绑定、删 P-17 守卫、roll 缓存键、视锥剔除乘缩放 | ab_batch 22/22；UI 9e-8；run_all exit=0（59 测试） | fix_03_gl_render.md |
| F8_core_editor | **完成** | P-01 播放态矩阵冻结、P-02 小场景碰撞兜底、P-04 双派发、P-03 脚本缓存失效、P-05 scale 归一化、P-09/P-10 删父连子树、P-22 Qt gizmo 点击顺序、加载非法场景先校验后清空 | ab_batch 22/22（MAE≤0.000082）；run_all 91 文件 exit=0；6 个新增测试全 PASS | fix_08_core_editor.md |
## F2_gl_lighting（loom_lighting.py / loom_render.py）

| # | 项 | 改前 | 改后 |
|---|---|---|---|
| 1 | **[P0] 聚光灯槽位** | 2 点光+1 聚光+1 平行光 → `IndexError`（:179） | 无异常；`slots=(0,6,-1,12)`，超预算的灯降级 + 只警告一次 |
| 2 | 聚光面 1..5 串到后一盏灯 | 面图按数组位置取 | 按本灯 guid 绑定；测试断言 `face_units == [slot+1..slot+6]` |
| 3 | **删 P-17 守卫（Q3=A）** | 2001 体：`_compute_light_vps` 6.468ms | **0.909ms**；`_pipeline_light_vps` 0.004→0.953ms（真跑 C）；`ab_point_shadow` MAE 0.000063 逐位不变 |
| 4 | 阴影 VP 缓存键缺 roll | 改 roll 签名不变、VP 复用（maxdiff=0） | 签名变化、VP 变化 1.19e-1；roll 回 0 精确复原 |
| 5 | 视锥剔除半径不乘缩放 | 缩放 20、中心 (30,0,0) 误剔 `keep=False` | `keep=True`；代价 `_frustum_keep` k=500：119.8→193.3µs（仅脏帧） |

**新增测试**：`tests/test_light_shadow_slots.py`（24 项）、`tests/test_light_vp_cache_roll.py`（12 项），均被 run_all 收集。

**遗留（未改，报告 §6）**：① 降级永久性（删灯后需手动重勾阴影）；② 降级按灯序无优先级；③ C 侧点光 far 仍硬编码 1e4（靠 `gl_FragDepth` 显式 `length/far` 保证等价）；④ 聚光灯仍用 6 面立方阴影（6×512²）；⑤ `_light_vps_cache_sig` 未含 `_shadow_point_far/_shadow_res`。

## F1_vk_render（vk_renderer.py / vk_ui.py）

| # | 项 | 改前 | 改后 |
|---|---|---|---|
| 1 | **[P1] 桶实例偏移** | `first_instance = idxs[0]+len(idxs)` 假设连续 → 同网格被隔开时画到别家 | 新增 `bucket_layout()` 单缓冲按桶重排，三处 draw 用重排后桶起点；探针（同网格 3 连体+不同贴图+中间插球）：**MAE 0.003197 / 2093 错像素 → 0.000001 / 0 错**（修复前并排图漏画一个 cube、另一个串成别家贴图） |
| 2 | PBR 开关属性名 | 读 `self.pbr_enabled`（不存在） | 改 property 落 `_pbr_enabled`，缺省 True，支持构造参数；`misc.x` 可关 |
| 3 | 法线贴图失败回落 | 白纹理 | `_flat_nrm_view`（平直法线），缓存键按用途分开 |
| 4 | env 缓存 | `id(cube)` 键、不留引用、无淘汰 | guid 键 + 持引用 + LRU 16（淘汰先摘 bind group 再 destroy） |
| 5 | 文本 LRU / `_groups` | 淘汰不 release、无界 | 淘汰 destroy 纹理并清 group；`_groups` 512 上限 LRU |
| 6 | wrap/filter_mode | 被忽略 | clamp↔clamp-to-edge、point/bilinear/trilinear↔nearest/linear；默认复用原采样器对象（老场景逐位不变） |
| 7 | 多投影灯 | 无限制 | 按裁决 A 记为已知限制：docstring 声明 + `_pack_light_vps` 打印一次警告，不崩 |
| 8 | 死代码 | `ensure_gl(None) if False`、注释 132B/208B 不一致 | 删除；统一 160B（grep 残留 0） |

**验收**：ab_batch 22/22（最大 MAE 0.000082，与改前逐值相同）；UI A/B 9e-8 不变；`run_all` exit=0（70 文件，0 FAIL）；新增 CPU 测试 42 断言全 PASS。

**遗留**：无 guid 贴图共用一条 `_tex_cache`；`_mesh_corners/_geo/_tex_cache` 同样无淘汰且用 `id()` 键；docstring "4 灯" 陈旧；多平行光阴影仍为已知限制。

> 备注（已澄清）：中途一次 `run_all` 报 `test_eai_color_parse` 失败，是 F3 改写测试辅助函数的中间态；F3 交付时已全绿。

## F5_player_backend（scene_driver / vk_player / Loom.py / run_player / game_player）

| # | 项 | 改前 | 改后 |
|---|---|---|---|
| 1 | P-03 贴图导入设置 | 丢 mipmaps/wrap/filter/aniso/max_size/compression | 照抄 sceneio 透传；**256×256/mip9 vs 64×64/mip1 → 完全一致** |
| 2 | P-05 相机坏值 | 4 个坏样例抛异常 → `os._exit` | 改用 `_f3/_f1`，8 个坏样例不再崩 |
| 3 | P-01/P-02 LOD | 每帧全量重算世界矩阵 +2.17ms；LOD 配置读不到 | 读 `lod_levels/lod_screen_levels/lod_bias`（只读 data）+ 无 LOD 早退 + 变换戳缓存 → **500 物体 2.201ms → 0.112ms/帧** |
| 4 | P-04 相机默认 | 有 camera 键缺字段也用 0/0 | 有键缺字段→0.6/-0.35（GL 同）；无键/空 dict→0/0（PlayerApp 同） |
| 5 | P-06 滚轮 | 帧末不清零（1,2,3,4 累积） | `_end_frame_input()` 帧末清零（→0,0,0,0），与 dev_mouse 开关无关 |
| 6 | P-07 回调覆盖 | 覆盖 rendercanvas 的 5 个回调 | `_chain_callback`：先库后自己，5 个全部捕获到库回调 |
| 7 | P-08 句柄重试 | 每帧重试+打印 | `_InputRetry(limit=3)`，失败 3 次进终态（6 帧 6 条 → 3 条） |
| 8 | P-09 滚轮被吞 | 同帧点击吞滚轮 | `_wheel_taken_by_scrollview` 与 `last_wheel_consumed` 取与；真 ScrollView 消费仍归 UI |
| 9 | P-10 `os._exit` | draw 内直接退出 | init→`VkInitError`（可回退）；循环内→`VkRunError`（可诊断的非零退出） |
| 10 | **Q6 后端策略** | `--run` 无回退 → 无 Vulkan 机器启动失败 | 默认仍 vulkan；**非显式 init 失败 → 打印"不兼容" + 写 `render_api=opengl` + `SystemExit(1)`**；显式 `--backend vulkan` 只报错不改设置；auto 回退不写设置；`VkRunError` 任何模式不回退 |
| 11 | scan_11 P-07 | docstring 声称 `LOOM_REMOTE_MODE` 优先但函数体无该常量 | 选择**实现**该分支（游戏配置双击路径也受保护），理由见报告 §10 |

**验收**：ab_batch 22/22（最大 MAE 0.000082，与改前逐行同值）；UI 9e-8；`run_all` 70 测试 exit=0；`vk_player --mini --frames 8` 真实出图 exit=0。

**遗留**：`vk_ui.last_wheel_consumed` 语义仍偏（非本批文件）；`"nan"` 字符串 yaw 两端都得 NaN；`_update_lod` 无 LOD 仍有 ~0.11ms/帧 扫描；sceneio 的 LOD **写入端**待另一批对齐；`game_player` 的 "渲染API=" 日志仍打印入参；看门狗 `os._exit(9)` 未动；远程模式未端到端跑图。

## F4_plugin_sandbox（plugin_sandbox / plugin_loader / scripts / script_glue / loom_events）

| # | 项 | 改前 | 改后 |
|---|---|---|---|
| 1 | **[P0 链1]** 模块内部引用逃逸 | `collections._sys` / `random._os` / `json.codecs` / `re.enum` 全可拿到真模块并**写出 PWNED 文件** | 白名单模块 → 运行时 `_ModuleProxy`（拒下划线属性、拒子模块、真模块藏 slots）；改后 `AttributeError` 且**未落盘** |
| 2 | **[P0 链2]** traceback globals 逃逸 | `f_globals` 含 os/sys 并写出文件 | `_GuardedApi/_GuardedCall`：宿主异常在 except 外重抛"同类型同消息"新异常（无宿主帧、`__context__=None`）+ AST 名单 traceback/frame/code 族；改后栈只剩 `[插件帧, 沙箱帧]` |
| 3 | [P1] register 部分注册残留 | 3 张表全残留 | `_load_one`/`load_plugin_from_pack` 事务化（注册表快照 + 回滚 SCRIPTS/按钮/sys.modules）→ 全空 |
| 4 | [P1] 脚本 id 无所有权（Q2=A） | 内建 `rotate` 被顶掉 | `register_script` 禁止覆盖已存在 id（同插件同类幂等）→ 冲突 broken 且 `rotate` 身份不变 |
| 5 | [P1] `clear()` 派发中立即生效 | `seen=["h1"] emit=1` | 延迟入队（与 `off` 同语义）→ `["h1","h2"] emit=2`，本轮后清空；非派发期仍立即 |
| 6 | [P1] Lua VM 泄漏 | 停止播放 `close=0` | `on_disable/on_destroy→close`（重入/构造失败也释放），`close` 幂等 + `__del__` 兜底 → `close=1` |

**验收**：ab_batch 22/22（逐场景 MAE 与改前一致）；UI 9e-8；`run_all` exit=0（70 文件）；新增 4 个测试文件（含两条攻击用例固定回归）。

**遗留**：P-10 卸载不清 sys.modules、P-03 TOCTOU、P-07 once 重入、P-08 cancel、P-11/12/13/14 调度器、P-15 下划线脚本文件。
**残余风险（诚实声明）**：进程内无强隔离（`_GuardedApi` 为兼容既有用法仍转发下划线属性）；模块代理不支持 `from x import *`；Lua 泄漏字节数未计量。

## F3_eai_ui（agent_commands / loom_mcp / loom_ui / ui/loom_gui）

| # | 项 | 改前 | 改后 |
|---|---|---|---|
| 1 | **[P0] ui_add 颜色** | `("#","f","f","0","0","0","0")` → 渲染帧 TypeError | `_COLOR_FIELDS` 补 6 个漏字段 + `_coerce_color_args` 统一 `parse_color`（#RRGGBB/#RRGGBBAA/#RGB/(r,g,b[,a])），非法直接 error 不留半成品 → `(255,0,0,255)` 渲染正常 |
| 2 | [P1] 布尔 | `"false"→True` | `visible/enabled/is_on/show_bar/close` 全走 `as_bool` → False |
| 3 | [P1] object_select | `index=99` 静默选中 #0 | 去掉 `or hits`，重名/越界一律 raise `_Ambiguous` 并列候选（model#0/model#1/light#0）→ `ok=False` 且选中态不变 |
| 4 | [P1] MCP 写脚本 | `../../x.py`、绝对路径、junction 全可落盘 | `_safe_script_path`（realpath 必须在 `<工程>/scripts` 内）+ `_safe_write_path` 改 realpath 前缀比较 → 全部拒绝；junction 逃逸同样被挡 |
| 5 | [P1] Qt UI 输入 | `pressed/released` 在 `_update_camera()` **之前**清空 → UI 永远收空集 | 移到之后（1325 → 1329/1330） |
| 6 | [P1] 多 Canvas 命中（Q7=C） | (120,110) 返回顶层 root，低层按钮永不可点 | 新增 `_hit_screen`：子元素优先 → 下探低层 → 全未命中才返顶层 root 吞空白；`hit_test/dispatch_mouse/update_hover_only` 共用 → 返回 `btn_low` 且 on_click 真触发 |

**验收**：ab_batch 22/22（最大 0.000082 与改前一致）；UI 9e-8；`run_all` exit=0；新增 4 测试（`test_eai_color_parse` / `test_ui_multi_canvas_hit` / `test_qt_tick_input_order` / `test_eai_safety_guards`）全 PASS 并被收集。

**F3 收尾（追加 3 项，已完成）**：
- RemoteViewport._tick 补齐输入段并与 _on_tick 同序（改前这三样出现 0 次 → 远程模式相机+UI 全哑）；
- ui_add/ui_set 的 rect/anchor/pivot 增加 _VEC_FIELDS/_as_vec/_coerce_vec_args（字符串按逗号/空白切分，项数/非数值/NaN·Inf 一律 error 且在任何字段改动前返回）——改前 tuple("0,0,120,40") 让 setter 解包失败、.rect AttributeError，tuple("0100") 静默错几何；
- run_stdio_server 包 try/except（异常回 JSON-RPC -32603 且 id 对齐，循环继续）——改前异常穿透打死进程。
**遗留（未动）**：① `editor.render` 的 `_update_gizmo` 也读 `self.pressed`，`paintGL` 在 `_on_tick` 之后跑 → Qt 编辑器 3D 点选/gizmo 仍拿不到本帧点击（属 editor.py，已转 F8）；② `RemoteViewport._tick` 从不清 pressed/released 也不调 `_update_camera`；③ `loom_mcp.run_stdio_server` 未包 try/except；④ `ui_add` 的 rect/anchor/pivot 仍裸 `tuple()`。

## F9_transform_math（matlib / loom_transform / loom_game_object）

| # | 项 | 改前 | 改后 |
|---|---|---|---|
| 1 | decompose_euler 万向锁 | β=-90 往返 **1.683 rad** | **1.11e-16**；β=+90/±89.999 不变 |
| 2 | set_parent 世界旋转 | β=-90 差 **1.682942** | **0**（根因是 children append 非幂等，Rl 数学未改） |
| 3 | parent 直写 | P.children=[C] 但 Q.children=[] | setter 维护双向；children 改 _ChildList（append/insert 去重，兜住 sceneio 等旧调用点） |
| 4 | scale=(1,2) | IndexError | (1,2,1)；model/批量矩阵对角 (1,2,1) |

**新增测试**：test_matlib_gimbal.py（59）、test_parent_children_invariant.py（24）、test_scale_normalize.py（20），全 PASS（gimbal worst 6.19e-13）。
**验收**：ab_batch 22/22（逐值同改前）；run_all 74 文件 exit=0、0 FAIL。
**遗留**：① physics_bridge.quat_to_euler_batch 同款万向锁 bug（已转 F6）；② GameObject.parent 直写无环保护；③ TransformComponent.scale 直写短元组仍可绕过（F8 入口归一化）；④ sceneio._link_by_map 仍手工 append（被幂等列表兜住）；⑤ P-10 删父悬空属 F8。

## F8_engine_editor（engine / editor / loom_components / loom_model_gpu / loom_lighting 空表回退）

| # | 项 | 改前 | 改后 |
|---|---|---|---|
| 1 | **P-01 播放态矩阵冻结** | actual.x=237 但 frame/soa/render = **0/0/0** | **237/237/237**（`_logic_prep` 每逻辑帧重算；editor 抽 `_refresh_play_matrices`，不把插值矩阵写进逻辑矩阵） |
| 2 | **P-02 小场景碰撞** | n=3 触发 0 次；n=40 无池 0 次 | playing 时无条件算 `_prep_pairs`（池不可用则主线程串行）；n=3 → pairs=3/start=6；n=40 无池 → **154=154 与旧内联一致** |
| 3 | P-04 重复派发 | 2 次/帧 | `_disp_gen=_logic_gen+1`，渲染侧不再二次派发 → 1 次 |
| 4 | P-03 脚本缓存 | 运行期挂脚本不执行 | `ScriptComponent.__init__` bump `_script_gen`；缓存键 `(struct_gen, script_gen)` → handle() 0→1 |
| 5 | P-05 scale | `(1,2)` → IndexError | `_normalize_scale` → `(1,2,1)`；0/>3 显式 ValueError（与 F9 同语义） |
| 6 | **P-09/P-10 删父（Q3=A）** | 删父后 models=[C]、悬空 parent | `remove_model` 有子→`remove_subtree`（逐节点删、剩余子提升为根）；editor 删除前调 `_confirm_delete_callback(model, N)` |
| 7 | **P-22 gizmo 时序** | Qt 3D 点选/gizmo 拿不到本帧点击 | 选 A 代际标记（`_gizmo_consumed_press`，兼容反向顺序）→ 拾取 1 次、同击不重放、UI 命中 0 次 |

**验收**：ab_batch 22/22（最大 0.000082）；`run_all` **89 文件 exit=0**；新增 5 个测试全 PASS。

**遗留**：① 审计里 n=40 无池 228 依赖其随机场景，本批以同场景旧内联 154=154 证明同口径；② **Qt 删除确认框需 `ui/loom_gui.py` 注入 `_confirm_delete_callback`（F3 文件，当前 Qt 删除无提示但功能正确）**；③ F9 侧建议 `model_world_matrix` 对"父不在 models"与批量路径对齐；④ `_framebuf_prefetch` 注释与派发行为不符（既有）。

## F6_physics（physics_bridge / physics_pipe / physics_glue / loom_physics）

| # | 项 | 改前 | 改后 |
|---|---|---|---|
| 1 | **P1 建体 identity 写回** | 动态体初始 rot `(0.4,0.2,0.1)` 被写成 `(0,0,0)`；旋转父下子局部被改成 `inv(R_parent)` | 建体即用模型世界位姿（pos+quat），盒体半长改体局部极值 → 初始旋转恢复、子局部不再被改 |
| 2 | **P1 AABB 中心瞬移** | 偏心网格 `(0,3,0)` → `(3,3,0)` | 改回 `(0,3,0)` |
| 3 | **P1 祖先脏传播** | 父无碰撞体 +4x，子局部被写成 `-4.0` | 脏检测节点集 = 有体模型 + 完整祖先链（build 时补祖先基线）→ 子局部 0.0、世界跟随 `(4,0,0)` |
| 4 | **P1 子步异常** | 成功路径清 `_err` → `NO-RAISE` | 首个未消费异常保持到 `wait_pending` → `RAISE: boom` |
| 5 | **P1 join 超时** | 超时仍销毁、切串行 | stop 复查 `is_alive` 并抛错；`_stop_phys_pipe` 返回 bool、超时切串行保留引用；未确认退出拒绝销毁并抛 RuntimeError |
| 6 | **P1 桥异常** | 每帧重建（5 帧 5 次 + 5 条日志） | 裁决 A：本场一次性 `_phys_bridge_disabled` → ensure 5→1、日志 5→1，仍回退 legacy |
| 7 | P2 `is_trigger` 进签名 | 运行时切 trigger 不重建 | rebuilt 0→1 |
| 8 | P2 移除体清 `_last_sync` | 泄漏（50 轮 51 条） | 清理并清场景外基线 |
| 9 | P2 树位回收 | 不回收（>31 串位） | 引用计数回收（移除后 2→1，重分配不撞位） |
| 10 | P2 重建丢角速度/睡眠态 | ω 丢失 | 搬 `set_angular_velocity` 与激活态（ω 0→5，active True→False） |
| 11 | P2 glue 无校验 | n=0 静默 rc=0 | 校验 dtype/形状/长度/连续性 → ValueError |
| 12 | **追加：`quat_to_euler_batch` 万向锁** | β=-90° 矩阵误差 **5.91e-01**；近奇点 2.597e-01 | 按 β 符号取 `atan2(±R[1,0],R[1,1])` + asin 饱和吸附 → **0 / 1.11e-16**；β=+90° 不变 |

**验收**：ab_batch 22/22（max 0.000082）；`tests/test_physics*.py` 5 文件全 PASS；`run_all` exit=0；`physics_dll_val_check` 逐位 diff=0。

**遗留**：`scene_driver._step_physics` 仍每帧打印桥异常（不在本批文件清单，建议同款节流）；`tests/_tmp/phys_dmb_equiv_check.py` 末尾 ✅ 在 GBK 控制台 exit=1（既有探针编码问题）。

## F7_scene_undo_misc（sceneio / undo / filedialog / frame_buffer / loom_net / guiloader / loom_texture / loom_cubemap）

| # | 项 | 改前 | 改后 |
|---|---|---|---|
| 1 | 父链成环 | load 2 对象 → save **0 对象**（静默丢） | 加载/保存均抛 `SceneCycleError` |
| 2 | 材质孤儿 | 连续 5 次 load→save 材质数 **[6,9,12,15,18]** | **[3,3,3,3,3]** |
| 3 | 纯色 env 往返 | 保存-回读 `None/None` | `[51,102,153,255]` |
| 4 | **撤销快照（Q5=A）** | 缺 normal_mode/prefab_ref/材质 albedo+PBR+env/LOD/光源 range | 全部补齐 |
| 5 | Shape 撤销 | 无 `ctype="shape"` 分支 | 已补 |
| 6 | 文件对话框 64 位 | `SHBrowseForFolderW` 未设 restype → access violation | `restype=c_void_p` + 异常捕获 |
| 7 | **FPS 预画 FBO（Q8=A）** | 离屏从未写入 → 黑帧 | 预画时临时重定向 `engine._external_fb` 到离屏 FBO + 深度附件（未改 GUI） |
| 8 | net cancel / 解码 | cancel 后被覆写；解码固定 | cancel 永久丢弃 + 按 `Content-Type` charset |
| 9 | 纹理换 ctx | 不 release（5 次泄漏 5 张） | 先 release 旧纹理 + weakref ctx 归属 |
| 10 | guiloader BOM/tab | 头解析失效 | 已修 |

**验收**：ab_batch 22/22（逐场景 MAE 与改前相同，最大 0.000082）；`run_all` exit=0；新增 8 个测试全 PASS。

**遗留**：① `editor.py::_load_scene` 先清空再 `scene_from_dict` → 拒绝时旧场景已丢（最小改动：清空前调 `sceneio._validate_object_graph`，属 editor.py）；② `scene_driver.py` 的 `env_map` 仍只处理 paths（不认 solid_color）。

## R4_vk_multi_shadow（vk_renderer.py）

| 项 | 改前 | 改后 |
|---|---|---|
| 平行光阴影贴图数量 | **1 张**（第 2 盏开阴影静默无阴影） | **2 张**：槽 0 = 纹理 1 / 采样器 2（沿用）；槽 1 = 纹理 **10** / 采样器 **11**（新增），同属 `@group(0)` 单个完整 bind group，无动态纹理数组索引 |
| 主着色器选择 | 只有 `t_shadow` | 按 `LightX.params.w`（0/1/-1）分支选 `t_shadow` / `t_shadow2` |
| 阴影 pass | 单槽 | 按槽位各烘一张，每槽独立 uniform + 独立实例缓冲（`_inst_sha_buf` / `_inst_sha_buf2`） |
| 第 3 盏及以后 | 无定义 | **打印一次警告 + 该灯无阴影**（非静默、不拿错图）；实测槽位 `[0,1]`、`params.w=[0,1,-1]`、警告恰 1 条 |

**验收**：ab_batch 22/22（与改前逐值相同）；新探针 `probe_two_dir_shadow.py` **MAE=0.000089 PASS**（改前对照"旧单图语义" MAE=0.004560 / **8855 错像素**）；CPU 测试 30 条全 PASS；`run_all` exit=0、0 FAIL。

**遗留**：第 3 盏+平行光无阴影（警告一次）；第 2 盏点光仍无阴影（本批未改）；固定 2×1024² r32float（+4MB）。
**附带改动**：`tests/test_vk_bucket_order.py` 第 7 段原断言"2 盏平行光必须告警"，随本批改为新语义（只动该段 3 条断言）。

## R2_plugin_residual（plugin_loader / loom_events / scheduler）

| # | 项 | 改前 | 改后 |
|---|---|---|---|
| 1 | P-10 卸载不清 `sys.modules` | 残留 | 按对象身份只摘自己那份；系统模块/他人模块不动（retained True→False） |
| 2 | P-03 TOCTOU | 检查后被替换仍执行 | 核心入口一次读 bytes → 按信任表重算 SHA256 → 编译同一份 bytes；malicious executed **True→False**，broken 含 TOCTOU |
| 3 | **P-07 once 重入** | cap=10 触发 **10 次**（无 cap 实测 499） | 调用前置 `alive=False` 消费，移除仍延迟入队 → **10→1** |
| 4 | P-11 mask | `hasattr(_mask)` False | True；5 生效，worker 真绑核 |
| 5 | P-12 metrics | packages 0 | 3（按 worker 实际执行累加） |
| 6 | P-13 超时 | 直接返回 False，串行兜底与在途包并发写 | 先 drain 在途包再返回 False（`worker_write_at_return` False→True） |
| 7 | P-14 shutdown | pending -1 | 只减未开始包 + `_cancelled` → pending 0；wait True→False |

**验收**：ab_batch 22/22（max 0.000082）；`run_all` exit=0（**102 文件**，0 FAIL）；新增 4 个测试全 PASS。
**报告**：`docs/audit/fix_r_scan09.md`，含 §2「P-07 修法与 F4 语义兼容性证据」。
**遗留/取舍**：P-13 drain 使 wait 实际耗时可超 timeout（正确性优先，无生产提交点）；P-08/P-15..17 未在本批；`sched_pool_check` 的 `batches>0` 是陈旧预期。
**备注**：ab_batch 改前基线 10:32 撞上 R4 改 `vk_renderer` 的中间态（binding 10），10:37 后重跑全绿。

## R5_stroke_line（vk_ui.py）—— 负结论 + 一个真发现

| 项 | 结论 |
|---|---|
| line-list 实验（width≤1 用 wgpu line-list） | **无改善**：与三角带逐像素相同（5 角度 GPU 直测每角度 0 差）。根因：**WebGPU 线宽恒 1px**，而残差 858px 全在 `width>=2` |
| 处理 | **已回退**，最终仍三角带；只保留契约注释（`STROKE_PIXEL_EQUIVALENT=False` + docstring） |
| 真发现 | alpha 场景 10044 差异像素里 **~9500 是多边形填充的 alpha 语义差**（GL 的 `draw_screen_polygon` 也走 `draw_lines`，BLEND 关闭 → alpha 被忽略），**不是描边** |
| 验收 | 不透明 0.00357361 / alpha 0.00680006（与改前相同，未劣化）；ab_batch 22/22；run_all exit=0（102 文件）；新增 `tests/test_vk_ui_stroke.py`（14 断言） |

### 主 Agent 追加修复：多边形填充 alpha
按 R5 的发现，`VkUIEngine.draw_screen_polygon` 也强制 `alpha=1`（复刻 GL 的无混合状态）：

| 场景 | 改前 | 改后 |
|---|---|---|
| `ui_lines_alpha_scene` | MAE 0.00680006 / **10044** 差异像素 | **MAE 0.00473871 / 1073** 差异像素 |
| `ui_lines_scene`（不透明） | 0.00357361 / 858 px | 0.00357361 / 858 px（不变） |

**遗留**：`width>=2` 描边残差（WebGPU 线宽恒 1px）；1px 水平线 GL/VK row20/19 tie-break；均属图元级差异，已契约化。
**事故记录**：R5 回退时曾整文件恢复 09:37 备份误伤 R3 改动，已恢复并复跑验证；之后仅局部 patch。

## R1_core_hygiene（scene_driver / loom_components / loom_game_object）

| # | 项 | 改前 | 改后 |
|---|---|---|---|
| 1 | 物理桥异常日志 | 每帧 1 条（5 帧 5 条） | 本场首次 1 条 + 后续只计数（count=5），`load_from_data` 重置 |
| 2 | `TransformComponent.scale` | 直写 `(1,2)` 可绕过 | F8 已落地归一化，本批复核**全部公开路径**并补回归（`(1,2)`→`(1,2,1)`，矩阵对角 `(1,2,1)`） |
| 3 | `GameObject.parent` 成环 | `collect_subtree` 损坏环 → **RecursionError** | setter 沿父链上溯遇自己抛 **ValueError**，DFS 有限 |
| 4 | `_update_lod` 空扫 | 500 物体无 LOD **0.191481ms/帧** | 候选集合加载登记 + `_lod_gen` 增量重建 + 空集合 O(1) 早退 → **0.000248ms/帧**（门槛 0.02ms） |

**验收**：ab_batch 22/22（逐场景数值与改前完全相同）；`run_all` exit=0（首跑因并行代理改名 `test_r5_wheel_backend.py` 出现 file-not-found，重跑绿）。
**新增测试**：`test_scene_driver_physics_log.py`(17) / `test_scale_all_paths.py`(36) / `test_parent_cycle_guard.py`(27) / `test_lod_fastpath.py`(18)，全 PASS。
**测试适配**：`tests/test_scene_cycle_reject.py` 用例 3 原用 `GameObject.parent` 直写造环（现会抛 ValueError），改为在 `TransformComponent` 层直写构造损坏环，验证 sceneio 保存前防御语义不变（报告 §5）。
**遗留**：`TransformComponent.parent` 层直写仍可造环（sceneio 保存前 `_validate_model_graph` 会拒绝）；直接改 `driver.models` 列表（不走 remove_model/load）时 LOD 集合可能滞后一帧。

## A1_agent_core（agent_commands / undo / editor）—— Agent 操作可视化（A/E/D/C）

| 项 | 实现 | 验收 |
|---|---|---|
| **A 逐条 + 节奏** | `drain()` 每拍最多 1 条；距上次 < `pace_ms`（默认 **120**，env `LOOM_AGENT_PACE_MS`）直接返回；执行后 `_agent_progress` → `_agent_after_command()`；队列空转非空 `_agent_busy(True)`、空闲 0.8s `_agent_busy(False)`；`pace=0` 一次排空 = 旧行为 | `tests/test_agent_pacing.py` ALL PASS（改前 exit=1） |
| **E 步进模式** | `LOOM_AGENT_STEP=1` 时每条执行完 `paused=True`，drain 返回；`resume_step()` 解除并立即执行下一条（`_draining` 防重入） | 同上 |
| **D 批次撤销** | `UndoManager.begin_batch/end_batch/cancel_batch` + `batch_active/batch_size`；`BatchCommand` undo 逆序 / redo 正序，`end_batch` 不重复执行；EAI `agent_batch_begin/end/cancel`；未 end 又 begin 自动 cancel 旧批并告警；空批不压栈 | `tests/test_undo_batch.py` ALL PASS（3 条命令 undo 一步全回退、redo 一步全恢复） |
| **C 相机聚焦** | `editor.focus_on_object(index, smooth=True)`：世界 AABB 中心 + 包围球半径 ×2.6，180ms 线性插值（播放态不推进；用户滚轮/平移/转视角取消）；EAI `view_focus{name?|index?,smooth?}`；`object_add`/`object_select` 成功后自动聚焦（`settings.agent_auto_focus` 缺省 True） | `tests/test_editor_focus.py` ALL PASS |

**验收**：`run_all` exit=0（全部测试完成）；`ab_batch` 22/22，MAE max 0.000082（与改前一致）。
**职责外改动**：`tests/test_eai_real.py` 命令台账补 4 条新命令（命令表 95 条全绿），否则覆盖率闸门必红；无业务代码改动。
**遗留**：① 步进模式下 HTTP `submit` 仍 30s 超时（命令会等人点击后执行，Agent 重试可能重复提交）；② `preview_camera` 期间聚焦不可见（不强制退预览）。

## A2_agent_ui（ui/loom_gui.py）—— 可视化指示（B）与步进按钮（E）

| 项 | 实现 | 验收 |
|---|---|---|
| **B 状态栏进度** | `_agent_progress`：`AI: <cmd> <k=v摘要≤40> (done/total)`；1.5s 空闲 token 防重入恢复默认 | `tests/test_agent_ui_indicator.py` 18/18 PASS |
| **B 忙态指示** | `_agent_busy`：工具栏红点「● AI 操作中」显隐 + 状态栏 `#e06c75` 变色/复位 | 同上 |
| **A 立即出图** | `_agent_after_command`：`viewport.update()+repaint()` | 同上 |
| **E 步进按钮** | 工具栏「下一步」仅 `service.step_mode` 可见，点击 `resume_step()`，状态栏显示「AI 等待下一步」；`--agent` 分支改 `_bind_agent_service(agent)`（含 QToolBar QWidgetAction 重藏坑的 singleShot 重同步） | 同上 |

**验收**：`run_all` exit=0；`ab_batch` 22/22（MAE 0.000082）；`test_agent_pacing` 26/26 PASS。

## 端到端可视化验收（真实窗口，2026-11-07）

`tests/_tmp/probe_agent_e2e_real.py`：起真实 `Loom.py --agent` 窗口 → HTTP 连发 **6 条 `object_add`** → 每条后截屏。

| step | 结果 | 耗时 |
|---|---|---|
| 0 | ok | 255ms |
| 1..5 | ok | 69/29/49/15/10ms |

相邻截图差异：每步 **~21750 像素（1.05%）** 变化（新立方体出现 + 选中高亮），最后一步 2.77% 变化（相机聚焦动画）。
截图可见：Hierarchy 出现 `AI_0..AI_5`、AI_5 选中、视口聚焦到该物体、**状态栏显示 `AI: object_add primitive=cube name=AI_5 position=[10.0... (6/6)`**、工具栏「AI 操作中」红字。
证据图：`docs/audit/agent_visual_step05.png`。

**步进模式超时修复（主 Agent 追加）**：步进模式下命令要等人点「下一步」，原 30s 超时会让 Agent 误判失败并**重试同一条命令** → 重复提交。已改为 `LOOM_AGENT_STEP_TIMEOUT`（默认 600s），超时返回 `timeout: true, retry_risk: "duplicate"` 提示调用方先查 status。
