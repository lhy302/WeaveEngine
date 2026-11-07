# 05_player（vk_player / scene_driver / runtime / game_player / run_player / loom_player_window / interp_state）扫描报告

> 只读审计，2026-11-07。被审对象：播放器/运行时/驱动模块，共 7 个文件 2292 行。
> 判定基准一律取自被审对象自身：模块 docstring、函数注释、sceneio/engine 的对应实现、本轮 diff 的自述目标（「双后端同语义」）。
> 全部结论附文件:行号 + 可执行探针 + 实测输出。**本报告不含任何代码修改建议以外的改动**。

---

## 0. 范围与方法

### 0.1 文件清单与行数

| 文件 | 行数 | git diff HEAD | 说明 |
|---|---|---|---|
| vk_player.py | 390 | +224 / -12 | Vulkan 播放器窗口/循环/输入 |
| scene_driver.py | 930 | +489 / -33 | 后端无关中间层（相机/时钟/物理/LOD/输入） |
| interp_state.py | 367 | +142 / -12 | 逻辑帧双快照 + 渲染帧插值 |
| runtime.py | 102 | +5 / -1 | GL PlayerApp |
| game_player.py | 153 | +27 / -8 | 发布链入口 |
| run_player.py | 87 | +17 / -8 | 后端选择 |
| loom_player_window.py | 263 | 0（未改动） | Qt 离屏 GL 玩家窗口 |

### 0.2 跑过的命令（全部定向，未跑 tests/run_all.py）

    git --no-pager diff HEAD -- vk_player.py runtime.py run_player.py game_player.py
    git --no-pager diff HEAD -- scene_driver.py
    git --no-pager diff HEAD -- interp_state.py
    py -3.12 tests/test_vk_camera_align.py          -> 85 PASS / 0 FAIL
    py -3.12 tests/test_interp_state.py            -> OK（10 项）
    py -3.12 tests/test_render_api.py              -> ALL PASS
    py -3.12 tests/test_lod.py                     -> ALL PASS（9 项）
    py -3.12 vk_player.py --mini --frames 8 --size 320x200   -> 真实 Vulkan 出图 8 帧

探针（全部放在 %TEMP%\loom_scan05\，不落工作区）：p_lod.py / p_wheel_cam.py / p_interp.py /
p_mat.py / p_mat2.py / p_cb.py / p_cbfail2.py / p_wheel3.py / p_camrobust.py / p_vkrun.py。
所有探针均设 LOOM_NO_SAVE_MIGRATE=1。

### 0.3 环境污染自查

    git status --porcelain  （审计前 1088 行 / 审计后 1089 行）
    Compare-Object 结果：仅多出 docs/audit/scan_03_gl_render.md（另一子代理产物）

结论：本次审计**未改动任何受跟踪文件**，无需 git checkout 还原。测试自身未重写 tests/_tmp。

### 0.4 本机环境（用于判定可复现性）

    python 3.12.10 / wgpu 0.32.0 / rendercanvas 2.7.2 / pygame 2.6.1
    adapter: NVIDIA GeForce GTX 1050 Ti, backend=Vulkan
    实测交换链 format: bgra8unorm-srgb -> 被 vk_player 改成 bgra8unorm（本机可走通）

---

## 1. 粗筛清单（含跳过项留痕）

### 1.1 疑似项（19 项，进入阶段二）

| ID | 位置 | 标签 | 初步方向 |
|---|---|---|---|
| P-01 | scene_driver.py:480-484, 535 | 性能/REGRESSION | 每渲染帧无条件重算全量世界矩阵 |
| P-02 | scene_driver.py:469-527 + build_models:36-123 | AUDIT-DEADCODE | LOD 配置从不从场景恢复，选模代码永不命中 |
| P-03 | scene_driver.py:146-167 | SEM-MISMATCH/REGRESSION | 材质贴图导入设置有损恢复 |
| P-04 | scene_driver.py:375-376 | SEM-DEFAULT/REGRESSION | 相机默认 yaw/pitch 与 sceneio 默认值分叉 |
| P-05 | scene_driver.py:370,375-376（容错助手 193-208） | IFACE-PRECOND/REGRESSION | 同函数内已有 _f3/_f1 却未用于相机段 |
| P-06 | scene_driver.py:301,449-450,805-812 + vk_player.py:271 | SEM-MISMATCH/REGRESSION | 滚轮字段「读数后清零」在默认配置下不可达 |
| P-07 | vk_player.py:169,180,208-210 | IFACE-PROTOCOL/REGRESSION | 覆盖 rendercanvas 已注册的 5 个 GLFW 回调 |
| P-08 | vk_player.py:136,141-151,245 | BND-RESOURCE/REGRESSION | 句柄验活失败 -> 每帧重试 + 每帧打印 |
| P-09 | vk_player.py:271-272 | SEM-MISMATCH/REGRESSION | 同帧点击+滚轮时滚轮被丢弃 |
| P-10 | vk_player.py:311-315 + game_player.py:83-98 | IFACE-ERROR/REGRESSION | 回退兜底只覆盖 init，loop 内异常直接 os._exit |
| P-11 | game_player.py:31,57,117-118 | AUDIT-DEADCODE | 回退后日志仍报原后端 + 两个无调用者函数 |
| D-01 | interp_state.py:86-170, 271-342 | BND-CONCURRENCY | 身份翻页/停泊行是否行对齐 |
| D-02 | vk_player.py:77-87 | AUDIT-DEADCODE | isinstance(fmt,str) 可能恒假，srgb 分支死代码 |
| D-03 | vk_player.py:114-138 | BND-RESOURCE | canvas._window 私有属性是否可靠 |
| D-04 | vk_player.py:163 | IFACE-UNIT | GLFW mods 位掩码 vs pygame 位掩码 |
| D-05 | scene_driver.py:355-359 | IFACE-PARTIAL | 只调 _apply_ui 未调 _link_ui_targets |
| D-06 | scene_driver.py:62-89 | SEM-MISMATCH | 音频/动画组件字段是否与 sceneio 一致 |
| U-01 | vk_player.py:78-85 | IFACE-VERSION | 非 srgb 交换链在其它驱动/远程桌面的行为 |
| U-02 | game_player.py:83-98 + vk_player.py:311 | SEM-SILENT | 真实失败点落在 init 还是 loop |

### 1.2 跳过登记（四类理由之一）

| 编号 | 位置 | 跳过理由类型 | 出处 |
|---|---|---|---|
| SKIP-01 | scene_driver.py:174-184 build_lights 白名单 | 白名单 3 个新键确被接受（语言/框架保证） | 探针输出 LightState.__init__(..., range=10.0, spot_inner_angle=30.0, spot_outer_angle=60.0)，全键构造成功 |
| SKIP-02 | scene_driver.py:90-107 collider/rigidbody | 同时有回归测试与同源实现 | tests/test_physics_runtime.py 覆盖；字段与 sceneio._apply_object 逐项同名 |
| SKIP-03 | scene_driver.py:717-742 world_position/move_with_collision/get_collisions | 已有回归测试覆盖 | tests/test_scripts_collision.py、tests/test_physics_bridge.py |
| SKIP-04 | scene_driver.py:646-688 FixedUpdate/LateUpdate 派发 | 已有回归测试覆盖 | tests/test_scripts.py 覆盖 order/on_fixed_update/on_late_update |
| SKIP-05 | scene_driver.py:（layer/tag/prefab_ref 未恢复） | 消费方不存在（工具自身声明） | grep .layer 在 vk_renderer.py 命中 0 处（仅 base_array_layer）；prefab_ref 0 处 |
| SKIP-06 | vk_player.py:189-200 _BTN 映射 | 语言规范保证 | dict.get 缺键返回 None，已有 btn is None 分支；pygame 顺序注释与 engine.buttons 一致 |
| SKIP-07 | interp_state.py:65-83 _fit grow-only | 回归测试覆盖 | tests/test_interp_state.py::test_grow_only 通过（输出缓冲 id 不变） |
| SKIP-08 | run_player.py:26-38 resolve_backend | 回归测试覆盖 | tests/test_render_api.py 覆盖 vulkan/opengl/auto/大写/未知值 |
| SKIP-09 | loom_player_window.py（整文件，本轮未改动） | 无 diff（不在本轮回归面） | git diff HEAD 对该文件输出为空；且其依赖 PySide6 离屏 GL，本机无法在非阻塞条件下复现 |

---

## 2. 逐项裁决

### P-01 · PROVED · P2（性能）· [REGRESSION]

**1) 位置**：scene_driver.py:480-484（_update_lod 开头）、:535（render_pose 首行调用）。

**2) 契约**：_update_lod 的 docstring（:470-476）自述「GL 在渲染层按相机距离/屏幕占比给配了 lod_levels 的物体换网格精度……这里逐行照搬」。GL 侧 loom_render.py:308-311 用**本帧已算好的** _frame_world，且 :309-310 在 fw 为 None 时直接 return；GL 每帧只算一次世界矩阵（loom_render.py:734-735）。

**3) 路径枚举**：
- 路径 A：models 为空 -> :478 return（唯一早退）。
- 路径 B：models 非空、所有物体 renderer.lod_levels / lod_screen_levels 均为 None -> :480 仍执行 world_matrices，:494 逐物体 continue。
- 路径 C：models 非空且有物体配 LOD -> 同上 + 选模。
无「没有 LOD 物体就跳过重算」的早退分支；路径 B 是**生产默认路径**（见 P-02）与路径 C 付出相同代价。

**4) 实际行为**：每个渲染帧，render_pose 先调 _update_lod，后者 from vk_renderer import world_matrices 并对**全部** models 走一遍父链 + numpy S@R@T（vk_renderer.py:461-530，含逐物体 id2i 字典与父链深度循环）；随后 vk_renderer.draw_frame 在 :1487 再算一次 world_matrices(vis, interp=interp)。

**5) 差异**：GL 每帧 1 次世界矩阵，VK 每帧 2 次（其中 1 次结果只被用来读平移列）。

**6) 触发条件**：任何非空场景的每一帧（默认路径）。

**7) 验证**：

    py -3.12 %TEMP%\loom_scan05\p_lod.py
    输出:
      load_from_data 500 物体: 27.4 ms
      render_pose 含 _update_lod : 2.180 ms/帧
      render_pose 无 _update_lod : 0.014 ms/帧
      _update_lod 净开销         : 2.166 ms/帧 (15958%)
      world_matrices(500) 单次   : 2.052 ms (draw_frame 每帧本来就要算一次)

（探针把 d.render_pose 跑 60 次取均值，然后把 d._update_lod 换成 lambda: None 再跑 60 次；500 个 cube。）

**8) 影响与等级**：60fps 预算 16.7ms，白付 2.17ms ≈ 13%；与本次「对齐 GL」的目标相反（GL 不付这份钱）。P2（性能），但属于本轮 diff 引入，标 REGRESSION。

---

### P-02 · PROVED · P3（可维护性/死代码）· [REGRESSION]

**1) 位置**：scene_driver.py:488-527（选模主体）、build_models:36-123（物体重建）。

**2) 契约**：_update_lod docstring（:471-474）声明其目标是消除「同一场景远处物体在 Vk 下仍是高模」的双后端差异。

**3) 路径枚举**：
- 进入选模的唯一条件是 renderer.lod_screen_levels 或 renderer.lod_levels 非空（:492-495）。
- 这两个字段唯一的赋值点是 loom_components.py:96,99（__init__ 置 None）与 agent_commands.py:1210（编辑器运行期 set_lod 命令）。
- 场景序列化侧：grep lod 在 sceneio.py 命中 0 处；反序列化侧 build_models 读 material_id/audio_source/animator/collider/rigidbody/scripts/parent，**不读 lod_***。
故播放器（独立进程、只吃场景文件）里两个字段恒为 None -> 选模永不执行。

**4) 实际行为**：播放器的 _update_lod 恒走路径 B（全部 continue），只留下 P-01 的 2.17ms/帧。

**5) 差异**：文档承诺「Vk 现在会换精度」，实际场景播放永远不换（GL 播放器同样不换，因为 GL 也没有反序列化侧；差异只在编辑器内播放态成立）。

**6) 触发条件**：任何通过 .json 场景文件/游戏包启动的播放器。

**7) 验证**：

    py -3.12 %TEMP%\loom_scan05\p_lod.py
    输出（场景里显式写了 lod_levels / lod_screen_levels / lod_bias）:
      obj0 lod_levels=None lod_screen_levels=None lod_bias=1.0
      -> 任意物体配了 LOD: False

**8) 影响与等级**：P3（死代码 + 误导性文档）。与 P-01 叠加后，这份代码的实际净效果是**纯负**（只付代价，无收益）。

---

### P-03 · PROVED · P1 · [REGRESSION]

**1) 位置**：scene_driver.py:146-167（build_materials 的贴图段）。

**2) 契约**：函数 docstring（:127-129）「与 sceneio._apply_materials 同字段语义」；sceneio.py:512-527 对 albedo/normal_map 调 Texture.from_file 时传 mipmaps/wrap/filter_mode/aniso/max_size/compression 六个导入设置。

**3) 路径枚举**：
- 材质 dict 无 albedo/normal_map -> 不进入（无差异）。
- albedo 引用存在且文件可读 -> :153-154 调 Texture.from_file(path, name, guid)，**其余六参取默认值**。
- 文件缺失/解码失败 -> :155-156 except: pass（两侧一致）。
无任何分支转发导入设置。

**4) 实际行为**：VK 使用 默认 mipmaps=True / wrap='repeat' / aniso=1.0 / max_size=0；GL 使用作者值。max_size 与 mipmaps 会直接改变像素尺寸与上传级数（vk_renderer.py:1218 读 tex.mipmaps 决定 mip 级数；Tex.from_file 内部按 max_size 缩放像素）。

**5) 差异**：同一场景、同一材质，GL 128x128 / 1 级，VK 512x512 / 10 级。

**6) 触发条件**：材质里含 albedo/normal_map 且导入设置非默认（编辑器导入面板改过就命中）。

**7) 验证**：

    py -3.12 %TEMP%\loom_scan05\p_mat2.py
    输出:
      VK: 512x512  mipmaps=True -> vk_renderer 上传级数 10  (max_size=0)
      GL: 128x128  mipmaps=False -> vk_renderer 上传级数 1  (max_size=128)
      尺寸一致: False   mip 级数一致: False
      显存占用比 (VK/GL, RGBA8): 16.0

（另有 p_mat.py 对同一 128x128 贴图对比六项导入设置：mipmaps True/False、wrap repeat/clamp、aniso 1.0/8.0 三项不同。）

**8) 影响与等级**：16 倍像素上传 + 采样方式不同 = 「同一场景切后端画面与显存占用都变」。P1（功能错误：违背本轮的双后端一致性契约），且显存/带宽是发布版硬约束。

---

### P-04 · PROVED · P2 · [REGRESSION]

**1) 位置**：scene_driver.py:375-376（self.yaw / self.pitch 默认值）。

**2) 契约**：diff 内注释称「engine 默认 camera_yaw/pitch = 0/0（场景无 'camera' 键时两端必须同视角）」。engine.py:232 确实 camera_yaw=0；但 runtime.PlayerApp 走的是 sceneio.scene_from_dict 的 camera_out，sceneio.py:926-931 只在 data 有 camera 键时填，且 yaw 默认 **0.6**、pitch 默认 **-0.35**。

**3) 路径枚举**：
- 场景无 camera 键 -> sceneio 不填 camera_out -> GL 用引擎默认 0/0；driver 用 0/0。一致（注释描述的就是这条路径）。
- 场景有 camera 键且四字段齐全 -> 两侧都用文件值。一致。
- 场景有 camera 键但缺 yaw 或 pitch -> GL 用 0.6/-0.35；driver 用 0.0/0.0。**不一致**。

**4) 实际行为**：VK 从正面看，GL 从右后上方看。

**5) 差异**：同场景两后端初始视角不同（yaw 差 0.6rad≈34°，pitch 差 0.35rad≈20°）。

**6) 触发条件**：手写/旧版场景只写了 target+distance。

**7) 验证**：

    py -3.12 %TEMP%\loom_scan05\p_wheel_cam.py
    输出:
      === P-CAMDEF-01 ===  VK driver: yaw=0.0 pitch=0.0
                          GL cam_out: yaw=0.6 pitch=-0.35
                          -> 双端默认值一致: False
      === P-CAMDEF-02 ===  VK yaw/pitch = 0.0/0.0 | GL cam_out = {} (空 dict -> 引擎默认 0/0)
                          -> 一致: True

**8) 影响与等级**：P2（默认值/边界）。注意方向：改动前 VK 用的正是 0.6/-0.35，与 sceneio 一致；本轮改成 0/0 后**从一致变成不一致**。

---

### P-05 · PROVED · P1 · [REGRESSION]

**1) 位置**：scene_driver.py:370（target=tuple(...)）、:375-376（float(...)）；容错助手 _f3/_f1 定义在 :193-208（本轮新增）。

**2) 契约**：_f3 docstring（:194）「与 sceneio._f3 同语义：坏数据回落 default, 加载不崩」。同文件 load_from_data 已用 clamp_camera_distance（:373-374）保护 distance，唯独 target/yaw/pitch 仍是裸 float()/tuple()。

**3) 路径枚举**：
- camera 键缺失 -> dict.get 默认值 -> 不抛。
- target 为 3 元素数值列表 -> tuple(...) 正常。
- target 为字符串 'abc' -> tuple('abc') = ('a','b','c') **不抛**，直到 camera_pos（:412-417）做减法才 TypeError。
- target 为 2 元素列表 -> target[2] IndexError（:417）。
- yaw/pitch 为 None 或非数值字符串 -> float() 立刻抛。
- distance 坏值 -> clamp_camera_distance 兜住（不抛）。

**4) 实际行为**：5 个坏样例中 GL 全部正常加载（sceneio._f1/_f3 兜底），VK 3 个在 load_from_data 抛、1 个在 render_pose 抛、1 个正常。render_pose 的异常在 vk_player.py:311-315 被 `except BaseException` 接住并 os._exit(1)。

**5) 差异**：同一份场景文件，GL 能开、VK 进程直接退出且控制台只留一段 traceback。

**6) 触发条件**：场景 camera 段任一字段类型错误或元素数不足 3。

**7) 验证**：

    py -3.12 %TEMP%\loom_scan05\p_camrobust.py
    输出:
      === yaw='abc' ===   GL : OK  camera_out={... 'yaw': 0.6 ...}
                          VK : 抛 ValueError("could not convert string to float: 'abc'")
      === pitch=None ===  GL : OK  camera_out={... 'pitch': -0.35}
                          VK : 抛 TypeError(...)
      === target='abc' === GL : OK  target=(0,0,0)
                          VK : OK target=('a','b','c') -> render_pose 抛 TypeError("unsupported operand type(s) for -: 'str' and 'float'")
      === target=[1,2] === GL : OK  target=(0,0,0)
                          VK : OK target=(1, 2) -> render_pose 抛 IndexError('tuple index out of range')
      === distance='abc' === 两侧都 OK（clamp_camera_distance 生效）

**8) 影响与等级**：P1（进程级失效 + 双后端行为分叉）。修复方向：同一函数内改用已存在的 _f3/_f1（本文件已有，零新增代码）。

---

### P-06 · PROVED · P2 · [REGRESSION]

**1) 位置**：scene_driver.py:301（字段注释「本帧滚轮 (+上/-下), 读数后清零」）、:449-450（dev_mouse 门控）、:805-812（唯一的清零点）、vk_player.py:271-272（累加点）。

**2) 契约**：字段注释声明「本帧滚轮」。GL 侧 loom_glfw_window.py:285 每帧显式 mouse_wheel = 0，:307-308 再写入本帧值；engine.py:399 同注释「本帧滚轮」。

**3) 路径枚举**：
- dev_mouse_enabled 为真 -> advance_logic :449-450 调 apply_dev_camera_mouse -> :811-812 读后清零。符合契约。
- dev_mouse_enabled 缺省/为假 -> :449 不进入；全文件再无 mouse_wheel 赋值点 -> 从不清零。
- vk_player.py:239 把 dev_mouse_enabled 设为 `os.environ.get("LOOM_VK_DEVMOUSE") == "1"` -> **默认 False**。

**4) 实际行为**：默认配置下鼠标滚轮每帧累加，永不归零。

**5) 差异**：GL 每帧读到的是本帧增量；VK 默认读到的是开播以来的总量。

**6) 触发条件**：任何滚轮事件（默认播放器配置）。

**7) 验证**：

    py -3.12 %TEMP%\loom_scan05\p_wheel_cam.py
    输出:
      dev_mouse_enabled 属性存在: False | getattr 默认 = ABSENT
      帧0 后 mouse_wheel = 1
      帧1 后 mouse_wheel = 2
      帧2 后 mouse_wheel = 3
      帧3 后 mouse_wheel = 4
      -> 契约 (scene_driver.py:301 '本帧滚轮, 读数后清零') 满足: False
      === 打开 LOOM_VK_DEVMOUSE 同序列 ===  帧0/1/2 后 mouse_wheel 恒 0，distance 被逐格推拉

**8) 影响与等级**：P2。当前 scripts.py 无任何 mouse_wheel 消费者（grep 命中 0），所以暂无可见症状；但字段契约已被破坏，任何后续脚本读它都会拿到一个单调递增的错误值（Python int 无溢出，不会崩，只会永远是同一个符号）。

---

### P-07 · PROVED · P2 · [REGRESSION]

**1) 位置**：vk_player.py:169（set_key_callback）、:180（set_char_callback）、:208-210（cursor/mouse_button/scroll）。

**2) 契约**：rendercanvas 2.7.2 的 GlfwRenderCanvas 在创建窗口时对同一个 win 注册了这 5 个回调（rendercanvas/glfw.py 中 `glfw.set_key_callback(self._window, weakbind(self._on_key))` 等），用于 submit_event / get_events。

**3) 路径枚举**：
- 若 rendercanvas 未注册 -> 覆盖无副作用。
- 若已注册（本机实测已注册）-> glfw.set_*_callback 是 replace 语义，rendercanvas 的回调被替换掉。
两者互斥，实测命中后者。

**4) 实际行为**：rendercanvas 的 _on_key/_on_char/_on_scroll/_on_cursor_pos/_on_mouse_button 全部不再被调用 -> canvas.get_events()/submit_event 这条事件链静默失活。

**5) 差异**：VK 播放器仍能工作（它自己用回调），但库里的事件 API 变成死路；rendercanvas 后续任何在这些回调里加的行为（指针锁、dpi、快捷键）都不会生效于 VK。

**6) 触发条件**：启动 Vk 播放器即触发（每进程一次）。

**7) 验证**：

    py -3.12 %TEMP%\loom_scan05\p_cb.py
    输出:
      set_key_callback          共 2 次
        #0  rendercanvas.core.coreutils.weakbind.<locals>.proxy
        #1  vk_player.run_vk.<locals>._register_input.<locals>._on_key
      set_char_callback / set_cursor_pos_callback / set_mouse_button_callback / set_scroll_callback 同样各 2 次

**8) 影响与等级**：P2（接口协议/维护风险，当前无可见症状）。建议方向：保存并链式调用上一个回调，或走 rendercanvas 的绑图（保留其事件栈）。

---

### P-08 · PROVED · P3 · [REGRESSION]

**1) 位置**：vk_player.py:136（打印）、:143-151（每帧入口）、:245（draw 首行无条件调用 _register_input）。

**2) 契约**：:141-142 docstring「首帧注册键鼠回调」。设计意图是一次性。

**3) 路径枚举**：
- 成功 -> :232 置 _keys_registered[0]=True，后续帧 :144 早退。
- win is None（句柄验活失败）-> :150-151 直接 return，**不**置标志 -> 下一帧重来；_resolve_glfw_window 在 :136 每次失败都 print。

**4) 实际行为**：窗口句柄一旦拿不到，每帧重试 + 每帧一行日志。

**5) 差异**：承诺一次性，实际是每帧。

**6) 触发条件**：rendercanvas 版本变化导致 _window 属性消失，或 get_current_context 返回无效句柄。

**7) 验证**（把 glfw.get_window_size 在画布创建后置为必失败）：

    py -3.12 %TEMP%\loom_scan05\p_cbfail2.py
    输出:
      帧数=6
      get_window_size 失败调用次数: 6
      '[vk] 拿不到有效 GLFW 窗口' 次数: 6
      '[vk] 输入回调注册失败' 次数: 0
      -> 每帧都在重试并打印: True

**8) 影响与等级**：P3（60Hz 日志 + 每帧一次无效验活）。

---

### P-09 · PROVED · P3 · [REGRESSION]

**1) 位置**：vk_player.py:271-272（`if ui_bridge.last_wheel and not ui_bridge.last_wheel_consumed`）。

**2) 契约**：同两行注释「滚轮: UI (ScrollView) 未消费才交给脚本/开发者相机」。判据应当是「滚轮是否被 ScrollView 消费」。

**3) 路径枚举**：last_wheel_consumed 在 vk_ui.py:799 定义为 `bool(wheel) and consumed`，而 consumed 是 dispatch_mouse 的**整体**返回值（包含「点击命中按钮」这条分支）。故：
- 仅滚轮且未命中 ScrollView -> consumed False -> 交给 driver。
- 同帧有点击被按钮消费 + 滚轮 -> consumed True -> 滚轮被丢弃。

**4) 实际行为**：点一下按钮的同帧滚轮丢失。

**5) 差异**：注释承诺按「滚轮是否被消费」，实现按「本帧鼠标事件是否被消费」。

**6) 触发条件**：点击与滚轮落在同一渲染帧（常见于点击后立即滚动）。

**7) 验证**：

    py -3.12 %TEMP%\loom_scan05\p_wheel3.py
    输出:
      === 同帧点击+滚轮 ===  dispatch_mouse 收到: ({1}, 3)
                            last_wheel=3 last_wheel_consumed=True
                            vk_player 行 271 判定把滚轮给 driver: False
      === 对照: 仅滚轮 ===   last_wheel=3 last_wheel_consumed=False
                            把滚轮给 driver: True

**8) 影响与等级**：P3。叠加 P-06 后，滚轮在默认配置下本来就没人读，症状被掩盖；开启 LOOM_VK_DEVMOUSE 后会看到「偶尔滚不动」。

---

### P-10 · PROVED · P2 · [REGRESSION]

**1) 位置**：game_player.py:83-98（_run_backend_safe，本轮新增 R-06）与 vk_player.py:311-315。

**2) 契约**：_run_backend_safe docstring「发布链最后防线：渲染后端初始化失败时醒目告警并回退 OpenGL」。

**3) 路径枚举**：
- run_vk 在**进入渲染循环前**抛异常 -> 被 :95 except Exception 接住 -> 回退 opengl。覆盖。
- run_vk 在**draw 回调内**抛任何异常（含 KeyboardInterrupt 之外的 BaseException）-> vk_player.py:311-315 os._exit(1)，进程立刻消失 -> 不回退，玩家看到「双击没反应」。
- 渲染卡死 -> vk_player.py:326-332 看门狗 os._exit(9)。同样不回退。

**4) 实际行为**：R-06 只覆盖 init 段，不覆盖运行段。

**5) 差异**：docstring 的「最后防线」语义比实现宽。

**6) 触发条件**：设备丢失、shader 编译期之外的运行时 wgpu 错误、UI 输入结算异常升级、以及 P-05 那类 render_pose 异常。

**7) 验证**：静态事实（两处代码）：

    vk_player.py:311-315   except BaseException: ... os._exit(1)
    game_player.py:93-98   try: run_backend(...) except Exception: run_backend("opengl", ...)
    以及实测：P-05 的 target='abc' 场景 ---> render_pose TypeError ---> 该 except 分支 ---> 进程退出

**8) 影响与等级**：P2（错误模型）。

---

### P-11 · PROVED · P3

**1) 位置**：game_player.py:117-118（打印用 backend 原值）、:31 _run_from_pack、:57 _run_from_scene。

**2) 契约**：:117 打印文案「渲染API=%s」。

**3) 路径枚举**：_start_pack 收到 backend 后交给 _run_backend_safe；后者回退时**不**回传实际后端 -> :117 永远打印入参。

**4) 实际行为**：Vulkan 失败回退 OpenGL 成功后，日志写「渲染API=vulkan」。

**5) 差异**：日志与实际不符；排障时会把 OpenGL 的问题误归到 Vulkan。

**6) 触发条件**：任何一次回退。

**7) 验证**：

    Select-String -Path game_player.py -Pattern '渲染API' -Context 0,1
    -> 117: print("... 渲染API=%s" % (... , backend))    # backend 是入参
    grep -rn "_run_from_pack|_run_from_scene" .  -> 只有定义处（game_player.py:31,57），全仓无调用

**8) 影响与等级**：P3（可维护性 + 日志可信度）。

---

### D-01 · DISPROVED · interp_state 身份翻页 / 停泊行 / 不变量

**1) 基准**：interp_state.py:93-103 的 P-04/P-05 声明（prev 按物体身份翻页；新物体首帧不插值）与 :296-341 的 P-03 声明（停泊行本地直写、_n 与 _ids 同步增长）。

**2) 代码证据**：advance 的三分支（:124 快路径 / :134 冷路径 / :157 首帧）与 _pose_dll_call 的停泊段 :312-341。

**3) 路径枚举（探针实测，6 组）**：

| 场景 | 期望 | 实测 | 结论 |
|---|---|---|---|
| T1 删A(0)加D(1000)：A/B/C -> B/C/D | prev 按身份 = [11,21,1000] | [11.0, 21.0, 1000.0] | 通过 |
| T2 结构重排 C,B,A | prev 按身份 = [20,10,0] | [20.0, 10.0, 0.0] | 通过 |
| T3 渲染帧新增 Z(100) 后 alpha=0.5 | Z 停泊在自身 100 | [2.5, 12.5, 100.0] | 通过 |
| T3 下一逻辑帧 advance 后 alpha=0 | prev = 上帧 curr = [5,15,100] | [5.0, 15.0, 100.0] | 通过 |
| T4 停泊后立刻删除该物体再 advance | 不抛 | 不抛，[1.0, 11.0] | 通过 |
| T5 物体数掉到 0 再恢复 | 不抛、_n 与 _ids 同步 | render_pose=None；恢复后 [7.0]，_n=1 | 通过 |

每一组后都断言 _n == len(_ids)（serial=True）。

**4) 触发条件**：覆盖了 P-04 文档描述的全部三类结构变化（删一加一 / 重排 / 中间插入）以及停泊行与 _ids 增长路径。

**5) 差异**：无。

**6) 验证**：

    py -3.12 %TEMP%\loom_scan05\p_interp.py      （T1..T6 全 PASS）
    py -3.12 tests/test_interp_state.py          （Ran 10 tests, OK）

**7) 残余**：advance 在 planes=None 时仍调用 _grab（:116）算出 ids 数组后丢弃（_ids2），并且第 110 行已另算一次 ids —— 每逻辑帧多一次 O(n) 数组构造。P3 级冗余，不单列。

**8) 判定**：DISPROVED。

---

### D-02 · DISPROVED · srgb 分支是死代码（怀疑不成立）

**怀疑**：wgpu 0.32 的 TextureFormat 是 BaseEnum 非 str，`isinstance(fmt, str)` 恒假 -> :78-85 永不执行。

**证伪**：实测 ctx.get_preferred_format 返回**普通 str**。

    py -3.12 %TEMP%\loom_scan05\p_surface.py
    输出: fmt = 'bgra8unorm-srgb' | type = <class 'str'> | isinstance_str = True | endswith = True
    以及 py -3.12 vk_player.py --mini --frames 8  ->  "设备: NVIDIA ... | format: bgra8unorm"

即分支命中且生效（交换链确实切到非 srgb）。**结论 DISPROVED**。（附带事实：wgpu.TextureFormat 本身确实不是 str 子类，但 get_preferred_format 返回的是 capabilities 里的原始字符串，故 isinstance 成立；若某版本改为返回枚举成员，该分支会静默失效 —— 见 U-01。）

---

### D-03 · DISPROVED · canvas._window 私有属性不可靠

**证伪**：rendercanvas 2.7.2 的 GlfwRenderCanvas 源码含 `self._window = glfw.create_window(...)`；真实运行后 driver 侧证据：

    py -3.12 %TEMP%\loom_scan05\p_vkrun.py   （拦截 SceneDriver.load_from_data 抓 driver）
    输出: dev_mouse_enabled = False | mouse_locked = True | on_mouse_lock_changed 已挂 = True
          _split_enable = True | models = 1 | ui canvases = 1
    且全程无 "[vk] 拿不到有效 GLFW 窗口" / "[vk] 输入回调注册失败" 打印

on_mouse_lock_changed 被挂上只发生在 _register_input 走到 :228，说明 win 解析成功、五个回调注册成功。**DISPROVED**（残余风险见 P-08：失败路径行为不对，但成功路径可用）。

---

### D-04 · DISPROVED · GLFW mods 与 pygame mods 位掩码不一致

**证伪**：vk_player 把 GLFW 原始 mods（GLFW_MOD_SHIFT=1 / CONTROL=2 …）传给 ui_bridge.on_key，GL 传的是 pygame 位掩码（KMOD_CTRL=192 …）。但 loom_ui.py:454-468 的 dispatch_key 签名虽收 mods，**函数体完全不用**（只把 pg_key 翻成名字再 on_key_down(name)）；dispatch_text 只收 text。故当前无任何可观测差异。

    grep -n "mods|KMOD" loom_ui.py   -> 仅 454: def dispatch_key(self, pg_key, mods=0)

**DISPROVED**（潜在：将来 UI 若用 mods 做 Ctrl+A/Shift 选区，两侧会分叉，记入 P3 备注）。

---

### D-05 · DISPROVED · world Canvas target 未二次绑定

**怀疑**：scene_driver.load_from_data 只调 sceneio._apply_ui（:355-359），没有调 scene_from_dict 末尾的 _link_ui_targets（sceneio.py:923）-> world canvas 的 target 恒 None。

**证伪**：vk_renderer.py:957-981 的 render_world_canvases 已在渲染侧按 guid 懒绑并删除 _pending_target_id，注释明确写了「补 driver 缺的那一步」。故数据层缺口被消费方补齐。

**DISPROVED**（归属：修复点位于 vk_renderer，不在本模块；若日后 04_vk_render 改掉懒绑，这里的缺口会立刻暴露 —— 建议在两个报告里交叉登记）。

---

### D-06 · DISPROVED · 音频/动画组件字段与 sceneio 不一致

**证伪**：逐字段比对 build_models:62-89 与 sceneio._apply_object 的音频/动画段，以及序列化端 sceneio.py:129-140。

    add_audio_source(clip, loop, volume, category, min_distance, max_distance, rolloff)
    add_animator(clips, current, loop)   # sceneio 写出 {current, loop, clips:{名:[帧]}}

探针确认 GameObject 实例具备 audio_source / animator / renderer / camera_children（camera_children 是实例属性而非类属性，hasattr(GameObject,'camera_children') 为 False 属正常）。**DISPROVED**。

---

### U-01 · UNKNOWN · 非 srgb 交换链在其它驱动 / 远程桌面的行为

**已尝试**：
1. 本机 NVIDIA 1050Ti：get_preferred_format -> 'bgra8unorm-srgb'，configure 成功，出图 8 帧正常。
2. 源码确认 rendercanvas/glfw 无自动重复 configure（模块源码 grep 'configure(' 命中 0 处），故 resize 不会把格式改回 srgb。
3. 无法构造 Intel/AMD/远程桌面/虚拟显示 的 surface。

**缺什么信息**：这些环境上 formats[0] 是否为 -srgb、非 srgb 变体是否在 capabilities 内、configure 是否抛（若抛则走 :84-85 回退并打印）。

**建议下一步探针**：在目标机型执行

    py -3.12 -c "import wgpu;from rendercanvas.glfw import GlfwRenderCanvas;c=GlfwRenderCanvas(size=(64,64));a=wgpu.gpu.request_adapter_sync(canvas=c);print(c.get_wgpu_context().get_preferred_format(a))"

---

### U-02 · UNKNOWN · 真实失败点落在 init 还是 loop（决定 R-06 兜底的实际覆盖率）

**已尝试**：
1. 本机无法制造「无 Vulkan 设备」的环境（adapter 必然可用）。
2. 静态确认 os._exit 路径存在（P-10），故 loop 内失败一定不可回退。
3. 无法确定典型失败（驱动缺失 / 虚拟显示 / 远程桌面）究竟是 adapter.request_device 阶段抛（可回退）还是首帧 present 阶段抛（不可回退）。

**缺什么信息**：一台无 Vulkan 驱动的 Windows 机器上跑 `run_player.py --backend auto <场景>`，记录异常发生点（是否有 "[vk]" 前缀打印、是否走到 "渲染异常, 终止进程"）。

**建议下一步探针**：在目标机器上设 `LOOM_VK_DEVMOUSE=0` 跑上述命令并观察 stdout 最后一行。

---

## 3. 统计

| 项目 | 数量 |
|---|---|
| 粗筛疑似项 | 19（含 4 项最终判为 DISPROVED 的怀疑） |
| P-PROVED | 11 |
| P-DISPROVED | 6 |
| P-UNKNOWN | 2 |
| P-CONTRADICTION | 0 |
| [REGRESSION]（本轮 diff 引入） | 10（P-01..P-10 中除 P-11 外全部） |
| 跳过登记 | 9 |

**等级分布（PROVED）**：

| 等级 | 数量 | 编号 |
|---|---|---|
| P0 | 0 | — |
| P1 | 2 | P-03（材质导入设置有损）、P-05（相机段坏输入 -> 进程退出） |
| P2 | 5 | P-01（每帧 2.17ms）、P-04（相机默认值分叉）、P-06（滚轮不清零）、P-07（覆盖库回调）、P-10（回退只覆盖 init） |
| P3 | 4 | P-02（LOD 死代码）、P-08（每帧重试打印）、P-09（点击吞滚轮）、P-11（日志/死函数） |

CONTRADICTION 为 0 的解释：本次没有出现「证伪链声称覆盖全部路径且无 bug」与「证真链给出最小复现」同时成立的情形；三条原本怀疑最重的项（D-01/D-02/D-03）在证伪阶段就被实测推翻，未进入正手。

---

## 4. 修复建议排序（只给方向，不含代码）

| 序 | 编号 | 方向 |
|---|---|---|
| 1 | P-03 | build_materials 转发 albedo/normal_map 的六个导入设置（直接复用 sceneio._apply_materials 的取值列表，避免第二份白名单） |
| 2 | P-05 | load_from_data 的相机段改用同文件已有的 _f3/_f1；target 必须校验长度==3 |
| 3 | P-01+P-02 | _update_lod 增加「本帧确有 LOD 物体」的早退，并复用 draw_frame 已算的世界矩阵；同时决定 LOD 是否要进场景序列化（见 §5 问题 1） |
| 4 | P-04 | 统一默认值来源：driver 的 yaw/pitch 默认改为与 sceneio 同一常量，或让 sceneio 的默认值只在一处定义 |
| 5 | P-06 | 在 advance_logic 帧首统一清零 mouse_wheel（与 consume_mouse_input 同位置），dev_mouse 只负责消费 |
| 6 | P-07 | 保存 rendercanvas 已注册的回调并在自身回调里链式转发，或改用 canvas 的事件 API |
| 7 | P-10 | 明确「回退」只保证 init 段（改文档），或把 draw 内的致命异常收敛成可回退信号（需要先定产品语义） |
| 8 | P-08 | 失败路径只打印一次并置「输入不可用」终态标志，不再每帧重试 |
| 9 | P-09 | 滚轮是否交给 driver 应看「滚轮本身是否被 ScrollView 消费」，而不是本帧整体 consumed |
| 10 | P-11 | _start_pack 打印改用实际生效后端；删除或收编 _run_from_pack/_run_from_scene |

---

## 5. 需要人类裁决的封闭问题

**问题 1（P-02）LOD 是否要进场景序列化？**
- A：进（sceneio 增 lod_levels/lod_screen_levels/lod_bias 的 emit+apply，build_models 同步恢复）——代价：场景格式 +1 段，老文件兼容需默认值；收益：本轮 _update_lod 才有意义。
- B：不进（删除 scene_driver._update_lod，LOD 仅保留在编辑器运行期）——代价：放弃「播放器与编辑器同画面」；收益：省 2.17ms/帧。

**问题 2（P-07）VK 播放器的输入是否允许吃掉 rendercanvas 的回调？**
- A：不允许（改为链式转发，保留库事件栈）——代价：需要按其 weakbind 约定包装；收益：跟随库升级。
- B：允许（视为明确取舍，在模块 docstring 记录）——代价：库升级时输入可能静默失效；收益：实现最简。

**问题 3（P-10）发布链「自动回退」的边界是 init 还是整个运行期？**
- A：仅 init（改 R-06 文档与提示文案）——代价：运行期崩溃仍表现为「双击没反应」；收益：无需跨后端热切换。
- B：整个运行期（需要把 draw 内的 os._exit 改成可回退信号 + 状态迁移）——代价：引入热切换状态机；收益：真正做到发布兜底。

---

## 6. 交叉与去重

- **P-05 与 02_scene P-01 同根因**（场景是外部输入，容错只覆盖白名单字段）：02 报告的修法是给 sceneio 补 _f1/_f3；本模块的 scene_driver 已复制了这两个助手（:193-208）却没用在相机段 —— 两个报告需联动，避免只修一侧。
- **P-03 与 02_scene P-04 邻近但不同**：02 的 P-04 是 env_map 的 from_solid 存盘丢失（scene_driver.py:158 同构）；本条是 albedo/normal_map 的导入设置有损。修复时两处都在 build_materials 同一函数内。
- **D-05 的缺口被 04_vk_render 的懒绑补位**（vk_renderer.py:957-981）：若 04 报告改动该函数，需回来补 _link_ui_targets。
- **P-01 的世界矩阵重复计算**在 04_vk_render（vk_renderer.draw_frame:1487）侧也有一份，去重后建议由 driver 把本帧矩阵传给渲染层（单次计算）。
