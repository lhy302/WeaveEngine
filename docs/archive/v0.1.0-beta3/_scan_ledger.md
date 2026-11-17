# 全量扫描总账（滚动更新）

> 只读审计。每个模块一行摘要 + 关键发现；详情见 docs/audit/scan_<NN>_*.md。

| 模块 | 状态 | 粗筛 | PROVED | DISPROVED | UNKNOWN | CONTRADICTION | REGRESSION | 报告 |
|---|---|---|---|---|---|---|---|---|
| 01_core | **完成** | 15 | 12 | 3 | 0 | 0 | 0 | scan_01_core.md |
| 02_scene | **完成** | 24 | 11 | 12 | 1 | 0 | 0 | scan_02_scene.md |
| 03_gl_render | **完成** | 13 | 9 | 3 | 1 | 0 | **1** | scan_03_gl_render.md |
| 04_vk_render | 排队 | - | - | - | - | - | - | - |
| 05_player | **完成** | 19 | 11 | 6 | 2 | 0 | **10** | scan_05_player.md |
| 06_editor_ui | **完成** | 27 | 16 | 9 | 2 | 0 | R-03b | scan_06_editor_ui.md |
| 07_eai | **完成** | 24 | 19 | 4 | 1 | 0 | 2 | scan_07_eai.md |
| 08_physics | **完成** | 20 | 15 | 4 | 1 | 0 | 0 | scan_08_physics.md |
| 09_scripting | **完成** | 26 | 17 | 6 | 3 | 0 | 0 | scan_09_scripting.md |
| 10_assets | **完成** | 38 | 26 | 8 | 4 | 0 | 0 | scan_10_assets.md |
| 11_build | **完成** | 28 | 19 | 7 | 2 | 0 | **2** | scan_11_build.md |
| 12_misc | **完成** | 14 | 14 | 7 | 1 | 0 | **2** | scan_12_misc.md |


## 01_core（engine / loom_components / loom_game_object / loom_transform / loom_material，2807 行）

**统计**：粗筛 15 → PROVED 12（P1×2 / P2×7 / P3×3）、DISPROVED 3、UNKNOWN 0、CONTRADICTION 0；探针 13 个；**REGRESSION 0**（本模块仅 `engine.py:32 import sys` 一行改动，判为正确修复：实测 `LOOM_SWITCH_INTERVAL` 0.005→0.001，旧代码 NameError 被 except 吞掉）。

### P1（2 条，均非本轮 diff 引入）

| ID | 位置 | 结论 | 证据 |
|---|---|---|---|
| P-01 | engine.py:1073-1082 + 1040-1042（使能条件 editor.py:1932-1933） | 编辑器**播放态** `_frame_world/_soa_snap` 自进播放起不刷新 → 渲染矩阵 / 阴影 VP / 碰撞 AABB / 插值平面全部冻结 | 真实 EditorApp：物体 `actual.x=237` 时 `_render_world[0].tx=0`、`_frame_world=0`、`logic_gen=12`；异步与同步都可复现；PlayerApp 基类 render 路径不受影响 |
| P-02 | engine.py:1086-1094 + loom_lighting.py:737-744 | split 播放态只有在 `_frame_pool` 非空且 `n>=32` 时才产 `_prep_pairs`，否则写 `[]`，渲染侧**无内联兜底** → 小场景 / 关并行时 `on_collision_*` / `on_trigger_*` **永不触发** | 实测 n=3（有无池）0 次、旧内联 6 次；n=40 无池 0 次、旧内联 228 次；n=40 有池才 114 对 |

### P2 摘要
- P-03：`update_scripts` 的 `_has_scripts_cached` 不被 `add_script` 失效 → 运行期挂脚本不执行
- P-04：同一逻辑帧派发两次 → `on_collision_stay/on_trigger_stay` 每逻辑帧 2 次/物体（异步下还跨线程）
- P-05：`scale=(1,2)`（2 元组）被接受，矩阵路径 IndexError
- P-06：`min_distance` 可破坏 `max>min` 契约（契约 §43）
- P-09：`GameObject.parent` 直写不维护 `children`（`remove_subtree` 误删）
- P-10：`remove_model` 删父后"批量矩阵 vs 递归矩阵"分叉（-4 vs 1）
- P-13：`set_parent` 在万向锁 β=±π/2 世界旋转差 1.68 rad —— **与 02_scene P-14 同根因（matlib.decompose_euler），总账去重**

### 去重提醒（子代理主动提出）
- **P-01** 涉及 03_gl_render（loom_render 播放分支）与 06_editor_ui（editor.render）→ 归属待 03/06 报告确认后定
- **P-02 / P-04** 涉及 03（loom_lighting split 派发）与 08_physics（内联兜底中）→ 同上去重
- **P-13 ≡ 02_scene P-14**（matlib 根因），只计一次

### 需人类裁决（封闭问题）
1. 编辑器 `toggle_play` 的 GL 播放渲染是否仍属维护目标？（决定 P-01 是否按 P1 修）
2. 小场景碰撞事件：文档写"走旧内联"但未实现 —— 补内联兜底，还是有意只保证 n≥32 的大场景？
3. 删父留子语义：Unity 式连子树删 / 子提升为根 / 其它？（决定 P-09/P-10 修复方向）

## 03_gl_render（loom_render / loom_lighting / loom_shaders / loom_model_gpu / loom_shadow，2659 行）

**统计**：粗筛 13（另跳过登记 10）→ PROVED 9 / DISPROVED 3 / UNKNOWN 1；**REGRESSION 1**；探针 9 个，实跑 4 个既有测试全 PASS；仓库零写入。

### P0（1 条）
| ID | 位置 | 结论 | 证据 |
|---|---|---|---|
| P-01 | loom_lighting.py:174,177-179 | 聚光灯阴影只记 1 个槽位：**≥2 盏投影点光 + 1 盏投影聚光灯** → `sampler_units[17]` IndexError（render()/run() 无 try）→ 引擎退出 / Qt 每帧黑屏 | 探针复现 |

### P1（3 条）
- 同根因：spot 不是最后一盏时，面 1..5 采到**后一盏灯**的深度图（静默错阴影）
- `loom_lighting.py:823-838` 编辑态阴影 VP 缓存键**缺 roll**：`light_set` 改 roll 后签名不变而 `|ΔVP|=0.176` → 阴影不刷新
- `loom_render.py:533-542` 视锥剔除半径**不乘实例缩放**：scale=12 的边缘物体 8 个顶点中 2 个仍在视锥内却被整桶剔除（需同桶 ≥2 实例）

### REGRESSION R-01（**是主 Agent 本轮引入的**）
- **位置**：`loom_lighting.py:796-797` —— 我加的"有投影点光就整帧弃用 C 路径"守卫。
- **前提被证伪**：点光深度用 `length/u_light_far` 写入/比较，与 VP 的 far 无关；实测离屏 `far=30` 与 `far=1e4` 深度图**逐位相同**（max diff 0.0）。
- **代价**：+6.44 ms/帧（2001 体/3 平行光：C 路径 0.785ms → Python 7.221ms）。
- **口径自相矛盾**：守卫不覆盖 spot，spot 仍走 C（far 仍 1e4）；崩溃路径已被同批新增的 `rows is None` 守卫（804-805）单独覆盖。
- **结论**：796-797 可整段删除（保留 804-805）。

### 跨后端交叉（归属 04）
- `vk_renderer.py:1425` 读 `self.pbr_enabled`，但全库只有 `engine._pbr_enabled` → **GL 的 `pbr_enabled=false` 后门在 VK 失效**（03 的 P-10）。

### 需人类裁决（封闭）
1. 聚光灯阴影契约：A 支持 6 面（最多 2 盏非定向阴影光）／B spot 不投影／C 仅允许 1 盏？
2. 点光阴影 VP：A 保留 `pipeline.dll`（删 P-17 守卫）／B 永久 Python（接受 +6.4ms/帧 @2001 体并写入性能基线）？
3. 编辑器 roll 是否必须即时反映到阴影：A 必须（sig 加 roll，+~0.9ms/次）／B 允许延迟（文档声明）？

## 09_scripting（scripts / plugin_loader / plugin_sandbox / script_glue / loom_events / scheduler）

**统计**：粗筛 26 → PROVED 17 / DISPROVED 6 / UNKNOWN 3；**P0×2、P1×4、P2×7、P3×4**；REGRESSION 0（本模块最后改动早于 Vulkan 轮）。

### P0（2 条：受限插件沙箱可逃逸）
| ID | 位置 | 结论 | 证据 |
|---|---|---|---|
| P-01 | plugin_sandbox.py:41-45,69-73 + plugin_loader.py:235-258 | 一条 `import collections; collections._sys.modules["builtins"].open(...)` 即拿到真 builtins 并写出插件目录外文件；`random._os` / `json.codecs` / `re.enum.sys` 同类 | 实测 PWNED 落盘，AST+运行时快检均放行 |
| P-02 | plugin_loader.py:193-200 | `e.__traceback__.tb_next.tb_frame.f_globals` 直接拿到 plugin_loader 的 globals（os/sys/importlib），**不依赖任何白名单模块** | 实测 PWNED2 落盘 |

### P1（4 条）
- `register(api)` 部分注册后抛异常 → 脚本/工具栏/sys.modules 残留，且不在 `_LOADED` 故无法卸载
- 脚本 id 无所有权：插件覆盖内建 `rotate`，卸载后内建**永久消失**；两插件同 id 时卸载 A 误删 B 的脚本
- `loom_events.clear()` 在派发中立即生效（丢事件），与"取消延迟应用"及 `off()` 语义相反
- Lua VM 每次播放分配，`on_disable/on_destroy` 未实现、`close()` 全仓无调用 → **每次播放/停止泄漏一个 Lua state**

### 需人类裁决（封闭）
1. 普通插件受限环境：A 安全边界（必修 P-01/P-02）／B 仅误用护栏（降 P2、改文档，边界交给 L2 子进程）
2. 插件脚本 id 冲突：A 禁止覆盖任何已存在 id／B 卸载按"原持有者栈"恢复／C 维持现状
3. NgilPool：A 标记 experimental 暂不接线、先修超时/shutdown／B 接线并同步修并发写与代际计数

## 10_assets（mesh / texture / font / raycast / audio / layer_tag / color / types）

**统计**：候选 38 = PROVED 26（P1×1、P2×13、P3×12）+ DISPROVED 8 + UNKNOWN 4；跳过登记 18；**零 P0、零 REGRESSION**。

### P1（1 条）
| ID | 位置 | 结论 | 证据 |
|---|---|---|---|
| P-01 | mesh.py:84-87,129-145 + sceneio.py:160-163 | 场景 JSON `{"type":"sphere","params":{"stacks":0}}`（slices=0 同）→ `ZeroDivisionError`，不在 sceneio 的 `except (ValueError, TypeError)` 内 → **场景加载半途中断** | 已实测 |

### P2 要点
- 网格：负 stacks/slices → 0 顶点空网格被 `_validate` **全绿放行**（静默隐形物体）；OBJ 上限只护 v/f，vt/vn 无上限
- 贴图：`ensure_gl` 用 `id(ctx)` 作缓存键且换 ctx **从不 release 旧 GL 纹理**（实测切 5 次泄漏 5 张）；`loom_cubemap.py:123,147` 同模式 → 与 02_scene 联动
- 字体：U+200D 等零宽字符被判"有字形"路由到 msgothic，`split("👨‍👩‍👧")` 被拆 5 段（92px vs 27px）；`_missing` 判定随字号变 → 跨字号永久污染
- 射线：`visible` 过滤只在几何路径，物理路径命中隐藏物体；层过滤上限 100 → 第 101 个目标静默漏检；`raycast_all` 物理侧多 collider 重复
- 配置：`load()` 不校验 tag 字符集/长度（与 `validate_tag` 契约 §9 不一致）；`register_tag` 吞掉落盘失败且"下次启动重试"实测为假
- 音频：`_handles` 无淘汰（2000 条实测）、shutdown 不清空；`mode` 永不为 None
- 层标记位宽：**已证伪**（存储 32 / EAI 0..31 / sceneio 钳制 / raycast 0..31 四侧一致），仅类型归一缺失与 `layer_name(1.9)` 截断

### 跨模块联动（重要）
- `vk_renderer.py:1212` 存在**死代码** `tex.ensure_gl(None) if False else None` —— 主 Agent 写的 VK 贴图接线残留，修复阶段清理
- `raycast` 物理距离 `ratio*max_dist` 语义需 05/08 用真实 Culverin 确认（若返回绝对距离，会被放大 max_dist 倍）

### 需人类裁决（封闭）
1. 隐藏物体是否应被 raycast 命中？A 与可见性无关（Unity 语义）／B 跳过隐藏／C 新增参数区分
2. 字形覆盖是否允许随字号变化？A 不允许（与字号解耦）／B 允许（内存×字号数）
3. `raycast_all` 语义？A 物体粒度+世界单位／B 碰撞体粒度／C 两者并存并声明不可比
4. 程序目录不可写时注册 tag 如何失败？A 抛错／B 内存成功+重试+首败警告／C 重定向 %APPDATA%

## 11_build（build_entry / build_game / game_pack / Loom.py / crash_reporter / log / profiler / single_instance / logic_thread / core_clock）

**统计**：粗筛 28 → PROVED 19（P1×6 / P2×6 / P3×7）/ DISPROVED 7 / UNKNOWN 2；**REGRESSION 2**。

### P1（6 条）
| ID | 位置 | 结论 |
|---|---|---|
| P1-1 | loom_logic_thread.py:33-45,53 | `stop` 先把 `_logic_stop` 置 None，而循环判活字段就是它 → **join 恒 2.00s 超时、线程永存**；二次 start 后 2 条逻辑线程双驱同一 clk（实测 607 次 advance/0.5s）。当前唯一调用点在 Qt 宿主不可达 → 潜在，接线即炸 |
| P1-2 | crash_reporter.py 全模块 | **未接线**：81 个生产 .py 命中 12 处全在自身，`install()/write_dump()` 零调用 → 崩溃无 .dmp，docstring 承诺的"Loom.py 早期接线"不存在 |
| P1-3 | build_entry.py | 编译版真入口未同步本轮 R-04：`--backend`/`resolve_backend` 命中 0、无单实例锁、无 `_self_check_sources`、无 `LOOM_REMOTE_MODE` → **发布物仍 GL-only、仍可连点开 N 个编辑器** |
| P1-4 | build_entry.py:262 | `--bench` 必崩 `NameError`（`import pygame` 在 :287，晚于 :275 的 `--bench` 分支）→ bench 结果写出后 exit 1 |
| P1-5 | build_game.py:149-154 | `--output . --force` → `rmtree(引擎源码根)`、`..` → 仓库根，**无任何路径守卫**（探针拦截实测，未真删） |
| P1-6 | game_pack.py | secure 互验可绕过：改 `.lpc` + 用引擎自带 `decode_blob`（XOR 0x5A 常量）改 `.lsc` 期望哈希 → 装载通过并 exec 攻击者 entry（本地发布夹，无提权） |

### REGRESSION（2 条，**均来自主 Agent 本轮对 Loom.py 的改动**）
- **P-07** `Loom.py:93-101`：`_launch_player` docstring 称 `LOOM_REMOTE_MODE` 优先，但函数体 co_consts 里**没有该常量**；`游戏配置` 分支（:338）仍走 Vk → **P0-1 白屏在双击启动路径未修**。
- **P-08** `Loom.py:304-306/336-339`：`--run` 由"恒 GL"改为"设置默认 vulkan 且显式 vulkan **无回退**"（`设置.json:15=vulkan`）→ **无 Vulkan 的机器从可用变为启动失败**。

### 证伪结论（值得记录）
- 定步时钟 1.2e6 帧（10000s）实测漂移 **0.000000000 步** → "累积误差"不成立
- `step_once` 恒 1 步、`LOOM_QUIET` 不吞运行期错误、单实例不误伤 `--run` 均 DISPROVED

### 需人类裁决（封闭）
1. `--run` 默认后端：A 保持 vulkan + 失败提示／B 改 auto 自动回退／C 默认 opengl
2. secure 模式威胁模型：A 只需防"误改半改"（降 P3 + 文档写明）／B 需防有意改包（加签名锚，按 P1 修）
3. 两入口收敛：A build_entry 改薄壳转调 Loom.py／B 双文件 + CI 断言能力齐平／C 删 build_entry（Nuitka 直接以 Loom.py 为入口，需确认编译版 `--bench` 是否仍需保留）

## 04_vk_render（vk_renderer / vk_ui）

**统计**：粗筛 25 → PROVED 13 / DISPROVED 12 / UNKNOWN 2；跳过登记 12；**本轮新增代码路径缺陷按回归登记 8 条**。

### P1（2 条）
| ID | 位置 | 结论 | 证据 |
|---|---|---|---|
| **P-01** | vk_renderer.py:1672/1592/1633 | 桶实例用 `first_instance = idxs[0] + len(idxs)`，但实例行按 `vis` 原序写入；**同键物体被其它物体隔开时，绘制覆盖到别的桶**（漏画 + 错形） | 我加贴图进桶键后，旧版可正确渲染的"同网格 3 连 + 不同贴图"现在错位；probe_regress.py 给出 HEAD 单桶 `[0,1,2]` vs 工作区 `{0,2}/{1}` 对照 |
| **P-02** | vk_renderer.py:1373 | `vis` 为空 + 任一平行光 `shadow=True` → 每帧 `ValueError`（`_dir_light_vp` 对空集取 min）；`vk_player` 的 `except BaseException` 直接 `os._exit(1)` = **闪退** | 离线假 device 复现 |

### P2（6 条）
- P-03 法线贴图上传失败回落**白纹理**而非平直法线（1198/1229）→ 法线错误
- P-04 env 缓存用 `id(cube)` 且不留引用 + 无淘汰（1278）→ id 复用/内存增长
- P-05 `vk_ui` 文本 LRU 淘汰**不 release**、`_groups` 无界（524）
- P-07 贴图 `wrap/filter_mode` 被忽略（728）
- **P-08** PBR 开关属性名错（1425）：读 `self.pbr_enabled`，真实开关是 `_pbr_enabled` → **`pbr_enabled=false` 在 VK 失效**
- P-13 多平行光阴影只用 1 张贴图（1545/1575）

### P3（5 条）
- P-06 UI 桥吞任意含 `_dragging` 的 AttributeError 并清状态（763-792）——`loom_ui.py:597` 已修 → 已成死代码
- P-09 `renderer=None` 时 AttributeError（1526）；P-10 4 元组 `light.color` 崩（1442）
- P-11 桶键含贴图 → 同网格多份 VBO（1568）；P-12 死符号/注释 208B-132B-160B 不一致

### 需人类裁决（封闭）
1. 实例缓冲：A 单缓冲 + 按桶重排（修复 P-01 的正解）／B 每桶独立缓冲（与 GL 同构）
2. 是否接受"VK 仅 1 盏点光 + 1 盏平行光阴影"为已知限制？
3. `vk_ui.STROKE_PIXEL_EQUIVALENT=False` 是否纳入"允许非逐像素等价"基线？

### 跨模块转交
- `loom_lighting.py:174` 对 spot 只绑 1 个 sampler 单元却建 6 张阴影图（GL 侧问题，与 03 的 P-01 同根因）

## 05_player（vk_player / scene_driver / runtime / game_player / run_player / loom_player_window / interp_state）

**统计**：粗筛 19 → PROVED 11 / DISPROVED 6 / UNKNOWN 2；**REGRESSION 10（全部来自本轮对齐改动）**；跳过登记 9。

### P1 回归（2 条）
| ID | 位置 | 结论 | 证据 |
|---|---|---|---|
| P-03 | scene_driver.py:146-167 `build_materials` | 丢贴图导入设置（`max_size/mipmaps/wrap/aniso/filter`）→ 同材质 **VK 512²/10 级 vs GL 128²/1 级**，16× 像素量 | p_mat2.py 实测 |
| P-05 | scene_driver.py:370,375-376 | 同文件已有 `_f3/_f1` 却未用于相机段 → `target="abc"`/`[1,2]`、`yaw="abc"`、`pitch=None`：**GL 5/5 正常，VK 3 例抛异常 +1 例在 render_pose 抛 → vk_player `os._exit(1)`** | p_camrobust.py 实测 |

### 其余 8 条回归（P2/P3）
- **P-01** `scene_driver.py:480-484/535`：`_update_lod` **每渲染帧无条件重算全量世界矩阵** → +2.166ms/帧 @500（`render_pose` 0.014→2.180ms）
- **P-02** LOD 配置**从不从场景恢复**（sceneio 无 lod；build_models 不读 `lod_*`）→ 选模永远 no-op，**P-01 是纯代价**
- **P-04** 相机默认 yaw/pitch `0.6/-0.35 → 0/0`：**场景有 camera 键但缺字段时 GL 用 0.6/-0.35、VK 用 0/0** → 行为分叉
- **P-06** dev_mouse 默认关 → `mouse_wheel` 永不清零，逐帧累积 1→2→3→4，违反 scene_driver.py:301 契约（GL 每帧清零）
- **P-07** `vk_player.py:169/180/208-210` 覆盖 rendercanvas 已注册的 5 个 GLFW 回调（实测各 2 次注册）→ **库事件链静默失活**
- **P-08** 句柄验活失败 → 每帧重试 + 每帧打印（6 帧 6 条日志）
- **P-09** 同帧"点击被 UI 消费"+"滚轮" → 滚轮被丢弃（`last_wheel_consumed` 混用）
- **P-10** `vk_player.py:311-315` `draw()` 内 `except BaseException → os._exit(1)`：发布链"自动回退"只覆盖 init 段

### DISPROVED（防止重复怀疑，值得留档）
- interp 身份翻页/停泊/不变量 T1-T6 全过
- srgb 分支实测生效（`fmt="bgra8unorm-srgb" → bgra8unorm`）
- `canvas._window` 可靠（回调注册成功 / `mouse_locked=True`）
- GLFW mods 无差异（`loom_ui.dispatch_key` 忽略 mods）
- world Canvas 已由 `vk_renderer:957` 懒绑补位；音频/动画字段与 sceneio 一致

### 交叉去重
- **P-05 ≡ 02_scene P-01** 同根因（scene_driver 复制了 `_f1/_f3` 却没用上）
- P-03 与 02_scene P-04 同在 `build_materials`
- P-01 的世界矩阵与 `04_vk_render vk_renderer.py:1487` 重复计算 → 应改单次计算并复用

### 需人类裁决（封闭）
1. LOD 是否进场景序列化？A 进（改 sceneio + build_models）／B 不进（删 `_update_lod`，省 2.17ms/帧）
2. VK 输入是否允许吃掉 rendercanvas 回调？A 链式转发／B 明确取舍并写进 docstring
3. 发布链"自动回退"边界是 init 还是整个运行期？A 只 init（改文档）／B 运行期（把 `os._exit` 改成可回退信号）

## 06_editor_ui（editor / loom_ui / loom_hud / gui / ui/*）

**统计**：P0=0；**P1=3**、P2=6、P3=7；既有 6 个 UI 相关测试**全 PASS**（说明 P1 都在测试覆盖之外）。

### P1（3 条）
| ID | 位置 | 结论 | 证据 |
|---|---|---|---|
| **P-01** | ui/loom_gui.py:1307-1308 → 1320 → editor.py:2120 | **Qt 编辑器在 UI 分发前清空 `pressed/released`** → `dispatch_mouse` 永远收到空集合 → **官方编辑器里 11 种 Canvas 元素的鼠标/键盘交互全部失效**（Button/Slider/Toggle/Dropdown/InputField），只有 hover 可能生效 | probe_qt.py 真实 `LoomGUI._on_tick`：tick 前 `pressed={1}`，分发时 `(set(), set(), 3.0)`，按钮点击 0 次；不清空时点击 1 次 |
| **P-02** | loom_ui.py:417-426,222-237,289-295 | 顶层 Canvas 的 root 是整屏矩形且 `enabled` → `hit_test` 逆序先命中 root 并 break → **低层 Canvas 的元素永远无法命中** | 多 Canvas 探针复现 |
| **P-03** | editor.py:2120 附近 | `_dispatch_ui_mouse` **没有把 `mouse_wheel` 传给 UI**；UI 也不消费滚轮 | probe_c.py 复现 |

### P2/P3 摘要
- P-04 播放边界不还原脚本对 `engine.ui` 的运行时修改（models/lights/cameras 都还原）
- P-05 `GLViewport.resizeEvent` 不调 `ui.resize`
- P-06 同帧滚轮+点击合帧时丢事件；P-07 拖动用错 Canvas 算 screen_rect；P-08 UI 树摘要漏 visible/enabled/z_order；P-09 编辑态不画 UI
- R-03b：`vk_ui` 里对 `loom_ui` 的兜底已成死代码（因 `loom_ui.py:597` 已修）
- **UNKNOWN（不猜）**：① `input_state.focus_id` 恒 None，输入框聚焦时相机是否仍响应 WASD；② 同一 `pressed.clear()` 是否也打断 3D 拾取（取决于 paintGL 与 timer 事件顺序）

### 需人类裁决（封闭）
1. **多 Canvas 命中语义**：顶层 root 是否参与命中？A 不参与（root 仅容器）／B 参与且全屏拦截（当前行为）／C 只吞空白（root 未命中子元素时继续下探）
2. **播放边界**：停止播放时脚本对 UI 的运行时修改是否必须还原？A 必须／B 不还原但刷新"已保存"基线／C 可配置
3. **编辑态预览**：Qt 编辑器在编辑态是否实时绘制 Canvas UI？A 需要／B 不需要（当前，需文档写明）／C 可开关

## 08_physics（physics_bridge / loom_physics / physics_pipe / physics_glue / parallel，2840 行）

**统计**：P0=0、**P1=6**、P2=6、P3=3、待定 1；5 个文件与 HEAD **逐字节相同**（blob sha1 全等）→ **本模块零回归**。

### P1（6 条）
| ID | 位置 | 结论 |
|---|---|---|
| P-02 | physics_pipe.py:71-73,97-99 | 成功子步执行 `self._err = None`，**覆盖前序子步的异常**（静默吞错） |
| P-03 | physics_pipe.py:109-116 + loom_physics.py:585-596 | `stop()` 的 `join(timeout=2.0)` 返回值不校验 → 超时后桥仍被销毁、引擎转主线程串行 |
| **P-07** | physics_bridge.py:756-760,785-786,853-855 | 建体 `rot=(0,0,0,1)` 且 `_last_sync` 预置为当前位姿 → 首帧 `dirty=False` → **post_step 把 identity 旋转写回模型** |
| **P-08** | physics_bridge.py:756,1164-1178 | 建体位置取**世界 AABB 中心** → 偏心网格首帧**瞬移** |
| P-11 | loom_physics.py:436-443,501-506 | 桥步进异常只 destroy 不置 `_phys_bridge_disabled` → 下一帧立即重建（崩溃循环） |
| P-12 | physics_bridge.py:875-915 | 祖先脏传播只在 entries 内建 `id2idx`，父无碰撞体时 `pidx=-1` → **父移动不会让子体脏** |

### P2/P3 摘要
- P-04 形态签名不含 `is_trigger`（`is_sensor` 只在 create_body 生效）；P-05 移除体不清理 `_last_sync`（与重建分支不对称）
- P-06 `_tree_bit` 按累计根 id 分配且从不回收，>31 后轮转复用位
- P-09 重建体只恢复线速度，角速度/睡眠态丢失；P-10 glue 无 dtype/长度/连续性校验
- P-17 `FramePool.shutdown(wait=False)` 不取消排队任务且 worker 非 daemon；P-18 管道超时降级无用户可见示踪

### 需人类裁决（封闭）
1. `_tree_bit` 容量：>31 棵树时轮转复用（当前）／扩位宽／拒绝新建碰撞树？
2. 桥步进异常后的策略：本次播放永久降级 legacy（推荐）／限次重试／崩溃退出？

## 07_eai（agent_commands / loom_mcp / loom_glfw_window / loom_input）

**统计**：POLISHED 24 项 → PROVED 19 / DISPROVED 4 / UNKNOWN 1 / CONTRADICTION 0；**REGRESSION 2**（均为本轮 diff 引入，但影响面有限）。
**契约闭合**：EAI 91 条命令全唯一；MCP 72 工具 ↔ 分支 ↔ 65 个被引用 EAI 命令**三方 0 缺口**；删除重复 `@command(scripts)` 无行为变化（HEAD 上第二个 def 本就覆盖）。

### P0（1 条，可致进程退出）

| ID | 位置 | 结论 | 证据 |
|---|---|---|---|
| P-01 | agent_commands.py:2062-2064 → loom_hud.py:220 | `ui_add` 的颜色字段用 `tuple()` 收字符串 → `bg_color=("#","F","F","0","0","0","0")`，渲染帧 `TypeError`；GLFW 播放器 `run()` 无 try → **进程退出** | 探针实测进程退出 |

### P1（4 条）
- `ui_add/ui_set` 用 `bool("false")=True`，绕过本文件 135-137 行的 `as_bool` 契约（实测 `visible="false"`→True）
- `object_select` 遇歧义/越界 index 用 `"or hits"` 静默取第一个；MCP `unity_gameobject_delete/duplicate` 先 select 再执行 → **删/复制错对象**
- `loom_mcp.py:578-588`：`unity_script_write_file` **无白名单**，`../../x.py` 可越出 base_dir、绝对路径直写（实测 isError=False），与 `agent_commands.py:83-132` 白名单契约冲突
- `loom_input.py:107-116` + `loom_glfw_window.py:276-279`：外部模式下 `script_keys` **永不刷新** → `LOOM_REMOTE_MODE=1` 的玩家窗口 WASD/鼠标全失效

### REGRESSION（2 条，均为 P2/P3）
- `loom_glfw_window.py:207-224`：外部模式全屏把 `width/height/viewport` 改成桌面分辨率，宿主 FBO 不变且不 resize UI（实测 viewport 2560x1440 vs FBO 1280x720）；**该分支生产不可达**（仅 GLFW F11 回调调用）
- `loom_glfw_window.py:200-206`：注释声称"F11 一按即崩（玩家发布路径默认该模式）"经全仓调用图穷举**不可达** → P-DISPROVED（P3，文档失真）

### 补充实测（子代理额外发现）
- 真实隐藏 GLFW 窗口：**F11 退出全屏不恢复原尺寸**（800x600 → 1920x1055，`window_size` 被 size 回调覆盖）；`test_fullscreen.py:142` 属**假绿**（桩掉了回调）
- MCP 契约缺陷：通知（无 id）回 error；坏 JSON 无 `-32700`；畸形参数未捕获异常会杀 stdio 进程（`run_stdio_server` 未包 try）

### 需人类裁决（封闭）
1. `ui_add` 颜色是否允许 `#RRGGBB`？A 与 `ui_set` 对齐（需补测）／B 收到字符串即报错（与 MCP 沙盘工具约定冲突）
2. `LOOM_REMOTE_MODE=1` 的 Qt 玩家窗口是否要求同等键鼠输入？A 是（补 `key_state→script_keys` 适配）／B 否（文档标注不可用，P1 降 P3）
3. 写路径白名单是否要求抵御 junction/symlink（改用 `os.path.realpath`）？A 要求／B 不要求并登记为已知边界）

## 12_misc（undo / filedialog / loom_net / frame_buffer / guiloader）

**统计**：粗筛 14（跳过 7）→ PROVED 14 / DISPROVED 7 / UNKNOWN 1；P1×4、P2×5、P3×5；**REGRESSION 2**。5 个源码文件 `git diff HEAD` 为空。

### P1（4 条）
| ID | 位置 | 结论 | 证据 |
|---|---|---|---|
| P-01 | undo.py:158-204 | 光源 `range` 不在 `light_snapshot` → `light_set`/`unity_light_set` 的"一步撤销"**实际不入栈** | probe：`before==after True`，apply 后仍 3.0 |
| P-02 | undo.py:27-68 + editor.py:1433-1439 | snapshot 缺 `normal_mode/prefab_ref/材质 albedo/PBR/env/LOD` → `set_normal_mode/unlink_prefab/set_texture/set_pbr/set_env/set_lod` **不产生撤销项**；GUI"与 Prefab 断开连接"不可撤销 | 探针复现 |
| P-03 | filedialog.py:244-247 | `SHBrowseForFolderW` 未设 `restype`（64 位截断）→ 回退 `SHGetPathFromIDListW` 实测 **access violation OSError**；现代 COM 失败时触发 | 实测 |
| P-04 | frame_buffer.py:188-194,210-218 + ui/loom_gui.py:1261-1272 + editor.py:1957 | 预画 FBO 与 `_screen_fb` 冲突：`render` 画到 widget FBO，离屏从未写入，blit 拷空 FBO → **开 FPS 缓冲时黑帧** | probe：绿→黑 |

### REGRESSION（2 条）
- **P-04** `undo.py:591-769` 缺 `ctype="shape"` 分支（`f0ad76a` 新增 Shape 未同步撤销层；EAI `ui_set` / MCP `loom_ui_set` 可达）
- **P-09** `loom_net.py:201-204` cancel 后后台线程**覆写结果**（`de1bc51` 新文件；0.8s 后 `result` 返回真实响应）

### P2/P3 摘要
- P-03 材质库 undo/redo 不配对；P-05 `event_bindings` 无撤销；P-12 `ensure_canvas` 无深度附件（**无深度画布遮挡反了**）
- P-06 删子树 undo 兄弟顺序变；P-08 `_parent_hwnd` 刷 GLFWError；P-10 `http_post_json` 抛 TypeError；P-13 ledger 非数值 TypeError；P-14 guiloader BOM/tab 标记失效

### 需人类裁决（封闭）
1. 撤销覆盖：A 扩快照全覆盖／B 明确不可撤销并改标签／C 资产级独立命令
2. FPS 缓冲：A 修 FBO 切换+深度／B 删预画留 TPS／C 仅 2D 可用
3. `loom_net`：cancel A 永久丢弃／B 改文档；解码 A 按 Content-Type charset／B 保持 UTF-8+latin-1 并写进文档

## 02_scene（sceneio / loom_scene_entities / loom_cubemap / matlib）

### P0/P1（4 条，均可复现）

| ID | 位置 | 结论 | 证据摘要 |
|---|---|---|---|
| P-01 | sceneio.py:292,230-235,281,903,914-918,446 | **P1** 加载容错只保护 `_f3/_f1` 白名单；collider/rigidbody/animator/gravity/光源角度/相机限角/UI 数值/objects 容器坏值直接抛 ValueError/TypeError/AttributeError → `scene_from_dict` 半途中断（editor.py:997 在 try 外） | 实测 9 例全部抛异常 |
| P-03 | sceneio.py:171-187 + 879-889；loom_model_gpu.py:54,74-78 | **P1** 每轮 load→save 材质库 +1 个孤儿默认材质 | 实测 2→3→4→5，存档线性膨胀 |
| P-04 | sceneio.py:486-489 vs 529-537 | **P1** `Cubemap.from_solid` 的 env_map 只写 `paths: null`，apply 只认 paths → 保存即丢（EAI `set_env` 纯色路径可达；scene_driver.py:158 同构） | 保存-加载回读为 None |
| P-05 | sceneio.py:300-307,873-875；loom_transform.py:328-335 | **P1** 父链成环不被拒绝（违反格式注释"父一定在子之前"）→ 再序列化静默丢环上对象；`world_scale` 死循环 | 实测对象 3→1；子进程 6s 超时 |

### P2 摘要
- P-02：bool 字符串语义（`"false"` → 真值）
- P-06：prefab 跨场景丢 PBR
- P-14：`decompose_euler` 万向锁 β=-90° 符号错（`set_parent` 实测世界旋转差 1.93）
- P-18：`from_solid` 越界通道 `OverflowError`

### 需人类裁决（封闭问题）
1. **场景/存档文件是否视为"不可信输入"？** A 是（P-01/P-05 按 P0/P1 全量防御）／B 否（允许报错退出，二者降 P2）
2. **材质库保存时是否裁剪无引用条目？** A 只在加载时阻止孤儿／B 保存时裁剪／C 两者 + 资产标记
3. **Prefab 是否携带材质资产？** A 携带 materials 段／B 按 guid 回查工程材质库／C 文档声明不支持

### 交叉观察
- 本模块 `git diff HEAD` 为空 → 无本轮回归；但 `scene_driver.py`（05_player）**复制了本模块的加载语义**，P-01/P-04 同构 → 修复时必须联动。