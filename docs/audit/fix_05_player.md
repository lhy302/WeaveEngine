# fix_05_player — 播放器/驱动批次修复报告（scan_05_player + scan_11_build 的 Loom.py 部分）

> 修复子代理交付 | 2026-11-07 | 工程：`D:\my-project - 副本\Loom(py源代码-工作区)\Loom`（Windows / python 3.12.10）
> 依据：`docs/audit/scan_05_player.md`（P-01..P-11）与 `docs/audit/scan_11_build.md` 的 Loom.py 部分（P-07/P-08 及 Q6 后端策略）。
> 只改允许清单内文件：**scene_driver.py / vk_player.py / Loom.py / run_player.py / game_player.py**（`git status` 复核，无其它源文件改动，未 git add/commit）。

## 0. 结论摘要

| # | 缺陷 | 等级 | 状态 | 证据位置 |
|---|---|---|---|---|
| 1 | build_materials 丢贴图导入设置 | P1 | 已修 | §1 |
| 2 | 相机坏值崩溃（裸 float/tuple） | P1 | 已修 | §2 |
| 3 | LOD 不进场景序列化 + 每帧全量世界矩阵 | P2 | 已修（裁决 A） | §3 |
| 4 | 相机默认 0/0 与 GL 分叉 | P2 | 已修 | §2 |
| 5 | wheel 永不清零（P-06） | P2 | 已修 | §4 |
| 6 | 覆盖 rendercanvas 回调（P-07） | P2 | 已修（裁决 A 链式转发） | §5 |
| 7 | 句柄验活失败每帧重试+打印 | P3 | 已修 | §6 |
| 8 | 滚轮被 UI 消费时丢弃（P-09） | P3 | 已修 | §7 |
| 9 | draw() 内 except → os._exit | P2 | 已修（分段失败信号） | §8 |
| 10 | 后端回退策略（Q6） | — | 已实现 | §9 |
| 11 | `_launch_player` docstring 与实现不符 | P2 | 已修（选择"实现分支"） | §10 |

验收数字（全部实测，命令与输出见 §11）：

* `python tests/_tmp/ab_batch.py` → **22 场景全 PASS**，门槛 MAE ≤ 0.0002，最大 0.000082（与改前逐行同值）
* `python tests/_tmp/ab_gl_vk_ui.py` → **MAE = 0.00000009**（门槛 1e-6）
* `python tests/run_all.py` → **exit=0**（新增 4 个测试已进收集）
* `python vk_player.py --mini --frames 8` → 真实 Vulkan 出图 8 帧，exit=0

---

## 1. P-03 [P1 回归] build_materials 丢贴图导入设置

**位置**：`scene_driver.py:146-167`（build_materials 的 albedo/normal_map 段）

**根因**：只给 `Texture.from_file` 传了 `path/name/guid`，其余六项导入设置
（mipmaps/wrap/filter_mode/aniso/max_size/compression）全取 Texture 默认值。
而 `sceneio._apply_materials`（sceneio.py:512-527）会原样转发这六项 —— 同一份场景，
GL 与 VK 得到**不同像素尺寸、不同 mip 级数、不同采样方式**的贴图。

**改法**：在 `Texture.from_file` 调用处补上六个关键字参数，取值列表**逐字照抄**
`sceneio._apply_materials`（不另立第二份白名单，避免将来再分叉）。

**改前/改后实测**（同一材质：256x256 PNG，`max_size=64 / mipmaps=False / wrap=clamp /
filter=point / aniso=4.0 / compression=none`；GL 侧走真实 `sceneio._apply_materials`）：

    # 改前
    VK(driver)   256x256  mipmaps=True  上传级数=9  wrap=repeat  filter=trilinear  aniso=1.0  max_size=0
    GL(sceneio)  64x64    mipmaps=False 上传级数=1  wrap=clamp   filter=point      aniso=4.0  max_size=64
    尺寸一致: False  mip级数一致: False  四项设置一致: False
    旧调用显存像素比 (VK/GL): 16.0

    # 改后
    GL: (64, 64, False, 1, 'clamp', 'point', 4.0, 64, 'rgb24')
    VK: (64, 64, False, 1, 'clamp', 'point', 4.0, 64, 'rgb24')
    非默认导入设置: VK 与 GL 完全一致  (64, 64, False, 1, 'clamp', 'point', 4.0, 64, 'rgb24')

**新增测试**：`tests/test_vk_material_tex_settings.py`（同材质 GL vs VK 的
尺寸/mip 级数/wrap/filter/aniso/max_size/compression 全等；默认设置、normal_map 槽、
文件缺失容错三组对照）。

### 1b. 追加（F7 联动）：`env_map.solid_color` 纯色环境贴图

**位置**：`scene_driver.py` build_materials 的 env_map 段。

**根因**：该段此前只认 `env_map.paths`（6 面文件）。F7 在 `sceneio` 侧补齐了
`_emit_material` 写 `solid_color`、`_apply_materials` 用 `Cubemap.from_solid` 还原，
但 VK 播放器的 `build_materials` 仍只走 `from_files` 分支 —— 同一材质在 VK 侧
`mat.env_map` 恒 None（GL 有 cubemap），纯色环境反射在播放器里丢失。

**改法**：与 `sceneio._apply_materials` 逐条对齐 ——
`eref.get('paths')` → `Cubemap.from_files`；`elif eref.get('solid_color')` →
`Cubemap.from_solid(tuple(...), name=..., guid=...)`；仍整体包 try/except（坏数据降级）。

**改前/改后实测**（探针 p_env.py；"改前"= 旧分支代码的忠实复现）：

    # 改前
    旧分支: eref and eref.get('paths') -> 纯色 dict 无 paths -> 不进分支
    VK build_materials(...).env_map = None          (GL 侧: Cubemap 4x4x6)

    # 改后
    改后: Cubemap(环境A 4) | size=4 面数=6 首像素=(58, 123, 213, 255) solid=(58, 123, 213, 255)
    -> 纯色 env 现在能拿到 cubemap: True

**新增/扩展测试**：`tests/test_vk_material_tex_settings.py`
* `t_env_solid_color`：纯色 env → VK/GL 签名全等（size=4、面数 6、首像素
  (58,123,213,255)、`_solid_color` 保留可再次存盘、name/guid 保留）；
* `t_env_solid_color_roundtrip`：`sceneio._emit_material` 写出的 `solid_color`
  段（无 paths）→ `build_materials` 读回 cubemap（F7 的 emit/apply 契约闭环）；
* `t_env_paths_still_work`：6 面 paths 分支未被这次重构破坏（尺寸/面数/路径保留）；
* `t_env_missing_tolerated`：文件缺失 / `solid_color` 非法 / 空对象 → 两端都 None 且不抛。

---

## 2. P-05 [P1 回归] 相机坏值崩溃 + P-04 [P2 回归] 相机默认值分叉

**位置**：`scene_driver.py:369-376`（load_from_data 相机段）；容错助手 `_f3/_f1` 在 :193-208

**根因（P-05）**：相机段是裸 `tuple(cam.get('target', ...))` / `float(cam.get('yaw', 0.0))`，
而**同一文件内已有** `_f3/_f1`（与 sceneio 同语义）却没用上。于是同一份坏场景：GL 正常加载，
VK 在 `load_from_data` 或 `render_pose` 抛异常，最后被 `draw()` 的 `except` 变成 `os._exit(1)`。

**根因（P-04）**：默认值口径错了。sceneio.scene_from_dict 只在 `data.get('camera')` 为真时
填 camera_out，且 yaw/pitch 默认 **0.6/-0.35**；无 camera 键时用引擎默认 **0/0**。
VK 一律 0/0 —— "有 camera 键但缺字段"这条路径与 GL 分叉（差 34°/20°）。

**改法**：
* target → `_f3(cam.get('target'), (0,0,0))`（长度≠3/含非数 → 回落默认，不再让 render_pose 崩）；
* yaw/pitch → `_f1(...)`，默认值按"有没有非空 camera 键"取：有键 → 0.6/-0.35（GL 同值），
  无键/空 dict → 0/0（PlayerApp 同值）；camera 键不是 dict 时按"无键"处理；
* distance 保持 `clamp_camera_distance`（已有），但先过 `_f1`，坏值语义更明确。

**改前/改后实测**（探针 p_cam.py，GL 参考值直接取自 sceneio 的 `_f3/_f1` 同算法）：

    # 改前
    yaw='abc'      VK: 抛 ValueError: could not convert string to float: 'abc'
    pitch=None     VK: 抛 TypeError: float() argument must be ... not 'NoneType'
    target='abc'   VK: 抛 TypeError: unsupported operand type(s) for -: 'str' and 'float'
    target=[1,2]   VK: 抛 IndexError: tuple index out of range
    distance='abc' VK: yaw=0.000 pitch=0.000            (GL: 0.6 / -0.35)
    缺字段          VK: yaw=0.000 pitch=0.000            (GL: 0.6 / -0.35)

    # 改后
    yaw='abc'      VK: yaw=0.600 pitch=-0.350   GL: 0.6 / -0.35   ✅
    pitch=None     VK: yaw=0.600 pitch=-0.350   GL: 0.6 / -0.35   ✅
    target='abc'   VK: target=(0,0,0)           GL: (0,0,0)       ✅
    target=[1,2]   VK: target=(0,0,0)           GL: (0,0,0)       ✅
    distance='abc' VK: dist=10.000 yaw=0.600    GL: 10.0 / 0.6    ✅
    缺字段          VK: yaw=0.600 pitch=-0.350   GL: 0.6 / -0.35   ✅
    无 camera 键    VK: yaw=0.000 pitch=0.000    GL: 空 -> 引擎默认 0/0 ✅

**新增测试**：`tests/test_camera_robust_vk.py`（8 个坏相机段样例均不崩且与 GL 参考值逐项一致；
默认值三条路径：有键缺字段 0.6/-0.35、无键 0/0、空 dict 0/0；坏值后 VP 仍有限）。

---

## 3. P-01/P-02 [P2 回归] LOD 不进场景序列化 + 每帧全量重算世界矩阵（裁决 A）

**位置**：`scene_driver.py`（build_models 尾部新增 `apply_lod_from_dict` 调用；新增
`_lod_mesh/_lod_levels/apply_lod_from_dict/_xform_stamp`；重写 `_update_lod`；新增 `_lod_world_pos`）

**裁决**：按任务给定的**默认 A —— LOD 进场景序列化**。sceneio 的写入端由别的批次实现，
本文件**只读 data、不写 sceneio**。

**根因**：
* P-02：`renderer.lod_levels/lod_screen_levels` 唯一赋值点是编辑器运行期的 `set_lod` 命令，
  场景序列化侧完全没有 lod_* 字段 → 播放器（独立进程只吃场景文件）里这两个字段恒 None，
  选模代码永不命中 = 纯死代码；
* P-01：`_update_lod` 每渲染帧无条件 `from vk_renderer import world_matrices` 对**全部** models
  重算一遍世界矩阵（500 物体实测 2.2ms/帧），而 draw_frame 里还会再算一次 —— 且这份结果
  只被用来读平移列。

**改法**：
1. **读取端**（在 sceneio 之外实现）：新增 `apply_lod_from_dict(m, obj)`，按白名单解析
   `lod_levels`（升序，距离模式）/ `lod_screen_levels`（降序，屏幕占比模式）/ `lod_bias`
   （下限 0.1，与 set_lod 同），并兼容 `"lod": {"levels": [...], "screen_levels": [...], "bias": ...}`
   容器写法；网格引用支持 `{"type","params"}` / 基元名字符串 / 已是 Mesh 三种形态；
   坏项（缺阈值、阈值非数、网格不可识别）逐项跳过，老场景零影响。
2. **性能**：
   * **早退**：先扫一遍 `lod_*`（纯 getattr），没有任何 LOD 物体直接 return ——
     生产默认路径**零世界矩阵开销**；
   * **按需 + 缓存**：只给配了 LOD 的物体算世界位置（`object_world_matrix`，本文件同源数学，
     不再 import vk_renderer），并按 `_xform_stamp`（物体 + 父链的变换快照）缓存；
     物体/父链不动就不重算，相机移动只影响距离判定。
3. `load_from_data` 时清空 `_lod_wpos`（换场景旧缓存立即失效）。

**改前/改后实测**（探针 p_lod.py；场景里显式写了 lod_levels / lod_screen_levels / lod_bias）：

    # 改前
    lod_levels      = None
    lod_screen_levels = None
    任意物体配了 LOD: False
    500 物体默认场景 render_pose:
      含 _update_lod : 2.214 ms/帧
      无 _update_lod : 0.013 ms/帧
      _update_lod 净开销: 2.201 ms/帧 (16656%)

    # 改后
    lod_levels      = [(5.0, 63), (30.0, 20)]          # 阈值 + 顶点数
    lod_screen_levels = [(0.1, 425), (0.0, 63)]
    任意物体配了 LOD: True
    500 物体默认场景 render_pose:
      含 _update_lod : 0.125 ms/帧
      无 _update_lod : 0.013 ms/帧
      _update_lod 净开销: 0.112 ms/帧 (854%)          # 2.201ms -> 0.112ms

**新增测试**：`tests/test_scene_driver_lod.py`
* 场景 lod_* → renderer 字段还原（乱序输入被排成升序/降序、bias 恢复、网格引用解析成 Mesh）；
* 6 组坏 LOD 段不崩（字符串/缺阈值/阈值非数/网格不可识别/bias=None/bias=0 钳到 0.1）；
* 距离模式选模（3 → 高模，20 → 低模）、屏幕占比模式选模（近 → 高模，远 → 低模）；
* **早退证据**：20 物体无 LOD，3 帧内 `object_world_matrix` 调用 **0 次**；
* **缓存证据**：有 LOD 物体首帧算 1 次，后续 5 帧静止仍 1 次，移动物体后 2 次。

---

## 4. P-06 [P2 回归] wheel 永不清零

**位置**：`scene_driver.py:301`（字段注释）、`advance_logic` 帧末新增 `_end_frame_input()`

**根因**：`mouse_wheel` 的唯一清零点在 `apply_dev_camera_mouse`，而该方法被
`dev_mouse_enabled` 门控（vk_player 里默认 `LOOM_VK_DEVMOUSE != '1'` → False）。
默认配置下滚轮只累加不清零，"本帧滚轮"契约被破坏（GL 是 loom_glfw_window 每帧显式清 0）。

**改法**：新增 `_end_frame_input()`（当前只有 `mouse_wheel = 0`），在 `advance_logic`
**两条返回路径**（分离时钟 / 绑死模式）末尾都调用 —— 与 dev_mouse 开关无关。

**改前/改后实测**（探针 p_wheel_frame.py，与 scan_05 探针同形：每帧先写入 1 格再推进）：

    # 改前（scan_05 P-06 原文）
    帧0 后 mouse_wheel = 1
    帧1 后 mouse_wheel = 2
    帧2 后 mouse_wheel = 3
    帧3 后 mouse_wheel = 4
    -> 契约 (本帧滚轮, 读数后清零) 满足: False

    # 改后
    帧0..3 后 mouse_wheel = [0, 0, 0, 0]
    -> 契约 (本帧滚轮, 读数后清零) 满足: True

**新增测试**：`tests/test_scene_driver_lod.py::t_wheel_reset_each_frame`
（dev_mouse False/True 两种都逐帧归零；dev_mouse=1 时滚轮仍按 GL 公式推拉 distance）。

---

## 5. P-07 [P2 回归] 覆盖 rendercanvas 已注册的 GLFW 回调（裁决 A：链式转发）

**位置**：`vk_player.py` 新增 `_chain_callback()`；5 处 `glfw.set_*_callback` 调用点

**根因**：rendercanvas 的 GlfwRenderCanvas 建窗时对同一 win 注册了
key/char/cursor_pos/mouse_button/scroll 五个回调（其 `submit_event/get_events` 事件链依赖它们）；
pyGLFW 的 `set_*_callback` 是 replace 语义 —— 直接覆盖让库的事件 API 静默失活。

**改法（裁决 A）**：新增 `_chain_callback(setter, win, our_cb, tag)`：
pyGLFW 的 `set_*_callback` **返回上一个回调**，先注册自己的拿到库回调，再用一个
`_chained` 包装重新注册：**先调库回调（异常只提示不拖垮输入），再处理自己的**。
库未注册（返回 None）时退化为直接注册（= 旧行为）。五个回调统一走这条路径。

**改前/改后实测**（探针 p_cb.py 拦截 `glfw.set_*_callback`，记录每次返回的"上一个回调"）：

    # 改前（scan_05 P-07 原文）
    set_key_callback 共 2 次
      #0  rendercanvas.core.coreutils.weakbind.<locals>.proxy
      #1  vk_player.run_vk.<locals>._register_input.<locals>._on_key
    （其余 4 个回调同样各 2 次 -> 库回调被替换掉）

    # 改后
    set_key_callback           注册 3 次, prev: ['无', '有', '有']
    set_char_callback          注册 3 次, prev: ['无', '有', '有']
    set_cursor_pos_callback    注册 3 次, prev: ['无', '有', '有']
    set_mouse_button_callback  注册 3 次, prev: ['无', '有', '有']
    set_scroll_callback        注册 3 次, prev: ['无', '有', '有']
    5 个回调都捕获到库旧回调 (链式转发的前提): True

（#1 = rendercanvas 自己注册；#2 = vk_player 注册，返回库回调=链上；#3 = 链式包装注册，
返回的是 vk_player 自己的回调。真实运行 `vk_player.py --mini --frames 8` 无任何
"[vk] 输入回调注册失败"，出图正常。）

**新增测试**：`tests/test_scene_driver_lod.py::t_vk_helpers`
（用假 setter 验证"先库后自己"的调用顺序，以及库无回调时退化为直接注册）。

---

## 6. P-08 [P3 回归] 句柄验活失败：每帧重试 + 每帧打印

**位置**：`vk_player.py` 新增 `_InputRetry`；`_resolve_glfw_window` 不再自己打印；`_register_input` 走预算

**根因**：`win is None` 时 `_register_input` 直接 return 且**不置成功标志**，下一帧重来；
`_resolve_glfw_window` 每次失败都 print → 60Hz 日志风暴 + 每帧一次无效验活。

**改法**：`_InputRetry(limit=3)`：失败计次，第 1/2 次各打印一行"重试 i/3"，
第 3 次打印一次"输入不可用…本次运行不再尝试"并进入终态（`can_try()=False`），
之后**不再重试、不再打印**；终态后再调用 `failed()` 也不累计。

**改前/改后实测**（探针 p_retry.py：画布建好后把 `glfw.get_window_size` 置为必失败，跑 6 帧）：

    # 改前（scan_05 P-08 原文）
    帧数=6
    get_window_size 失败调用次数: 6
    '[vk] 拿不到有效 GLFW 窗口' 次数: 6
    -> 每帧都在重试并打印: True

    # 改后
    get_window_size 失败调用次数: 3
    输入相关打印行数: 3
      [vk] 输入回调注册失败 (拿不到有效 GLFW 窗口 (OSError('invalid window handle'))) —— 重试 1/3
      [vk] 输入回调注册失败 (拿不到有效 GLFW 窗口 (OSError('invalid window handle'))) —— 重试 2/3
      [vk] 输入不可用 (…) —— 已重试 3 次仍失败, 本次运行不再尝试 (键盘/鼠标/滚轮不会生效)
    -> 有限重试并停止打印: True

**新增测试**：`tests/test_scene_driver_lod.py::t_vk_helpers`（3 次后 given_up、终态后计数不再增长）。

---

## 7. P-09 [P3 回归] 同帧点击被 UI 消费时滚轮被丢弃

**位置**：`vk_player.py` draw() 的滚轮结算；新增 `_wheel_taken_by_scrollview()`

**根因**：`vk_ui.UIInputBridge.last_wheel_consumed` = `bool(wheel) and consumed`，
而 `consumed` 是 `dispatch_mouse` 的**整体**返回值（含"点中按钮"分支）。
于是"同帧点按钮 + 滚轮"时滚轮被当成已消费而丢弃。

**改法**（只改 vk_player，不动 vk_ui —— 非本批文件）：把判定**合并**成
"整体 consumed **且** 滚轮专属判据成立"：`_wheel_taken_by_scrollview(ui, pos)`
按 `UIManager.dispatch_mouse` 的同一判据复核（指针下命中 ScrollView 且 `can_scroll()`）；
UI 判不了（无 `_hit_scroll_view`）时保守返回 True（保持旧行为，不引入重复消费）。

**改前/改后实测**（探针 p_wheel.py，UI 桩：`dispatch_mouse` 恒 True = 点击被按钮消费）：

    # 改前（scan_05 P-09 原文）
    === 同帧点击+滚轮 ===  dispatch_mouse 收到: ({1}, 3)
                          last_wheel=3 last_wheel_consumed=True
                          vk_player 行 271 判定把滚轮给 driver: False   <- 丢

    # 改后
    === 同帧点击 + 滚轮 ===
      last_wheel=3 last_wheel_consumed=True
      旧判定(交给 driver)=False   新判定(交给 driver)=True     <- 不再丢
    === 指针下确有可滚 ScrollView ===   旧判定=False  新判定=False  （仍归 UI，不重复消费）
    === ScrollView 内容不溢出 ===       旧判定=False  新判定=True   （空滚轮区不再吞）

**新增测试**：`tests/test_scene_driver_lod.py::t_vk_helpers`（4 种 UI 形态的判定矩阵）。

---

## 8. P-10 [P2 回归] draw() 内 except → os._exit（改为分段失败信号）

**位置**：`run_player.py` 新增 `VkInitError/VkRunError`；`vk_player.py` 初始化段包装 + draw() 异常处理 + 循环后抛出

**根因**：`draw()` 里 `except BaseException: … os._exit(1)` —— 进程当场消失，发布链的
`_run_backend_safe` 只覆盖 init 段，玩家看到的是"双击没反应"，排障也拿不到异常对象。

**改法（按任务给定的最小语义：init 段才回退，loop 段打印后退出并说明）**：
* **初始化段**（建窗/取 adapter/device/交换链/configure/VkRenderer）包 try/except →
  抛 `VkInitError`（可回退信号，带上原因与类型）；
* **渲染循环内**：不再 `os._exit`。打印 traceback + 一行中文说明，记录异常、`canvas.close()`
  结束循环；循环返回后 `run_vk` 抛 `VkRunError`（"Vulkan 已初始化, 未回退 OpenGL"）→ 上层以
  非零码退出并留下可诊断信息；
* `run_backend` / `_run_backend_safe` 对 `VkRunError` **不**回退（见 §9）。

**改前/改后实测**（探针 p_loop.py：把 `VkRenderer.draw_frame` 换成必抛）：

    # 改前（源码事实）
    vk_player.py:311-315  except BaseException: traceback.print_exc(); os._exit(1)
    -> 进程立即消失, 无异常对象, 不执行 finally/atexit

    # 改后
    Traceback (most recent call last): ... RuntimeError: 模拟渲染期 device lost
    抛出的异常: VkRunError | 是 VkRunError: True
    异常消息: Vulkan 渲染循环异常: RuntimeError: 模拟渲染期 device lost (Vulkan 已初始化, 未回退 OpenGL)
    进程仍活着 (能走到这里打印): True
    说明行出现: True
      [vk] 渲染循环内异常 (RuntimeError: 模拟渲染期 device lost) —— Vulkan 已初始化,
            无法在本进程内回退 OpenGL; 结束渲染循环并按失败退出

**新增测试**：`tests/test_backend_fallback_policy.py::t_loop_failure_not_swallowed`
（auto / 显式 / 设置三条路径下 VkRunError 都不被回退吞掉）。

---

## 9. Q6 定制：后端策略（Loom.py + run_player.py + game_player.py）

**位置**：`run_player.py`（`_persist_backend/_handle_vk_init_failure/run_backend(explicit=)`）、
`Loom.py::_launch_player`、`game_player.py::_run_backend_safe/_start_pack/main`

**契约（按任务给定）**：
* 默认后端仍是 **vulkan**（`resolve_backend` 与 `设置.json render_api` 不动）；
* **Vulkan 初始化失败**且非显式指定时：打印
  「Vulkan 后端不兼容（<原因>），已把设置回退为 OpenGL，下次启动将使用 OpenGL」，
  把 `设置.json` 的 `render_api` 写成 `opengl`（若文件里另有 `backend` 键一并同步），
  本次进程 **SystemExit(1)** —— 崩一次，不伪装成功；
* **显式 `--backend vulkan`**：不改写设置，只报错并 SystemExit(1)；
* **`--backend auto`**：仍自动回退 OpenGL，**不写设置**；
* 渲染循环内失败（`VkRunError`）任何模式下都不回退。

> 注：任务文本写的是"把设置.json 的 backend 写成 opengl"，本工程实际的键名是
> `render_api`（`resolve_backend` 只读它），故写 `render_api`；若旧配置里存在
> `backend` 键则一并写成 opengl，避免两套口径。

**改前/改后实测**（探针 p_backend.py：桩 `_run_vulkan` 抛"无法创建 Vulkan 设备"，设置指向临时目录）：

    # 改前
    --- 默认/设置路径 (explicit=False) ---
      抛出: RuntimeError code=None msg=在当前设备上无法创建 Vulkan 设备 (adapter 空)
      设置.json render_api = vulkan            <- 没回退, 下次还是崩
    --- 显式 --backend vulkan (explicit=True) ---
      抛出: RuntimeError …                     设置.json render_api = vulkan
    --- --backend auto ---
      [run_player] Vulkan 不可用 (…), 回退 OpenGL   返回: gl | render_api = vulkan

    # 改后
    --- 默认/设置路径 (explicit=False) ---
      [run_player] Vulkan 后端不兼容（在当前设备上无法创建 Vulkan 设备 (adapter 空)），
                   已把设置回退为 OpenGL，下次启动将使用 OpenGL
      抛出: SystemExit code=1
      设置.json render_api = opengl            <- 下次启动即 GL
    --- 显式 --backend vulkan (explicit=True) ---
      [run_player] Vulkan 后端不可用 (…)
      [run_player] 显式 --backend vulkan: 不改写设置, 直接报错退出
      抛出: SystemExit code=1        设置.json render_api = vulkan   <- 未改写
    --- --backend auto ---
      [run_player] Vulkan 不可用 (…), 回退 OpenGL   返回: gl | render_api = vulkan

**新增测试**：`tests/test_backend_fallback_policy.py`（默认路径写设置+非零退出+提示含"不兼容"；
显式 vulkan 不改设置；auto 回退不写设置；VkRunError 不回退；发布链不吞 SystemExit；
旧键名 `backend` 同步）。

---

## 10. scan_11 P-07：`_launch_player` docstring 与实现不符（选择"实现分支"）

**位置**：`Loom.py:93-101`（`_launch_player`）

**根因**：docstring 声明 `LOOM_REMOTE_MODE=1` 时"必须优先"强制 GL/离屏窗口，
但函数体里没有任何该环境变量的分支；只有 `--run` 分支在调用前提前 return，
**游戏配置.json 分支（打包游戏双击启动）完全没有远程模式兜底** → 远程/虚拟显示仍命中 P0-1 白屏。

**改法（二选一里选"实现"）**：在 `_launch_player` 内实现该分支
（`LOOM_REMOTE_MODE=1` → `loom_player_window.run_player_window(scene, w, h)` 并 return），
两条调用路径（--run / 游戏配置.json）自动都受保护。
**理由**：白屏兜底是真实需求（4f46650 修的 P0-1 就是它），删 docstring 只会把"打包游戏在远程桌面
下白屏"这个真实缺口藏起来。同时 `_launch_player` 现在把 CLI 后端是否显式（`--backend`）
传给 `run_backend(explicit=...)`，供 §9 的策略使用。

**改前/改后实测**（探针 p_remote.py：桩掉 `loom_player_window` 与 `run_player.run_backend`）：

    # 改前（scan_11 P-07 原文，字节码事实）
    LOOM_REMOTE_MODE=1 -> run_backend 收到 [('RESOLVED(None)', 'scene.json', {...})]
    LOOM_REMOTE_MODE=0 -> run_backend 收到 [('RESOLVED(None)', 'scene.json', {...})]
    docstring 有 / 函数体字节码里出现: False

    # 改后
    LOOM_REMOTE_MODE=1 -> [('remote', 'scene.json', 1280, 800)]        <- 走离屏 GL 窗口
    LOOM_REMOTE_MODE=0 -> [('backend', 'vulkan', 'scene.json',
                            {'width': 1280, 'height': 800, 'explicit': False})]
    docstring 的规则在函数体内生效: True

（远程模式需要真实 Qt/PySide6 离屏环境，本机未启动该窗口，未做端到端跑图验证 —— 见 §13 遗留 7。）

---

## 11. 验收实测

### 11.1 A/B 批量（门槛 MAE ≤ 0.0002）

```
python tests/_tmp/ab_batch.py
场景                         MAE        MAX        NCC        模型数      结论
ab_c_dir+point.json        0.000000   0.0039     1.0000     3/3      PASS
ab_c_dir_only.json         0.000000   0.0039     1.0000     3/3      PASS
ab_c_dir_shadow.json       0.000071   0.0784     1.0000     3/3      PASS
ab_c_point_only.json       0.000000   0.0039     1.0000     3/3      PASS
ab_c_spot_only.json        0.000000   0.0000     1.0000     3/3      PASS
ab_cube.json               0.000000   0.0000     1.0000     1/1      PASS
ab_env.json                0.000001   0.0039     1.0000     1/1      PASS
ab_env_off.json            0.000000   0.0039     1.0000     1/1      PASS
ab_nrm.json                0.000000   0.0039     1.0000     1/1      PASS
ab_nrm_off.json            0.000000   0.0000     0.9999     1/1      PASS
ab_pbr.json                0.000000   0.0039     1.0000     3/3      PASS
ab_plane.json              0.000000   0.0039     1.0000     1/1      PASS
ab_plane_cube.json         0.000019   0.0588     1.0000     2/2      PASS
ab_plane_cube_sun_pt.json  0.000018   0.0549     1.0000     2/2      PASS
ab_plane_shfalse.json      0.000000   0.0039     1.0000     1/1      PASS
ab_plane_shtrue.json       0.000000   0.0039     1.0000     1/1      PASS
ab_plane_sphere.json       0.000052   0.0784     1.0000     2/2      PASS
ab_point_shadow.json       0.000063   0.1255     1.0000     2/2      PASS
ab_scene.json              0.000068   0.0745     1.0000     4/4      PASS
ab_sky.json                0.000017   0.0510     1.0000     2/2      PASS
ab_tex.json                0.000000   0.0000     0.9999     1/1      PASS
ab_ui_scene.json           0.000082   0.0980     1.0000     3/3      PASS
场景数 22, 门槛 MAE <= 0.0002, 失败 0
全部通过 ✅
```

改前基线（同一命令，修复前跑的一次）逐行数值与本表**完全一致**（例如 ab_scene 0.000068、
ab_point_shadow 0.000063、ab_ui_scene 0.000082），即本批修复没有引入任何像素级劣化。

### 11.2 UI A/B（门槛 MAE ≤ 1e-6）

```
python tests/_tmp/ab_gl_vk_ui.py
GL(UI) vs VK(UI)  MAE=0.00000009  MAX=0.003922  NCC=0.99998569  (diff>0 像素数=4/153600)
exit=0
```

### 11.3 全量回归

```
python tests/run_all.py
...
============================================================
运行: test_integration.py
============================================================
============================================================
全部测试完成 ✅
exit=0
```

* 收集 **90** 个 `tests/test_*.py`（并行批次陆续加入后的总数；含本批新增的
  `test_backend_fallback_policy.py` / `test_camera_robust_vk.py` /
  `test_scene_driver_lod.py` / `test_vk_material_tex_settings.py`，已确认出现在运行列表里）；
* 输出中 **0 条 FAIL 行**，无"有失败"汇总，退出码 **0**。

### 11.4 新增测试（全部 PASS，已进 run_all 收集）

```
python tests/test_vk_material_tex_settings.py   -> ALL PASS  (exit=0)   # 含 §1b 的 4 组 env_map 断言
python tests/test_camera_robust_vk.py           -> ALL PASS  (exit=0)
python tests/test_backend_fallback_policy.py    -> ALL PASS  (exit=0)
python tests/test_scene_driver_lod.py           -> ALL PASS  (exit=0)
```

F7 联动追加后的复验（同一轮）：

```
python tests/test_vk_material_tex_settings.py
  === 纯色 env_map (solid_color) GL vs VK ===
  GL: (4, 6, (58, 123, 213, 255), (58, 123, 213, 255), '环境A', 'g-env')
  VK: (4, 6, (58, 123, 213, 255), (58, 123, 213, 255), '环境A', 'g-env')
  PASS 纯色 env: VK 侧拿到 cubemap / 面数=6 / 尺寸=4x4 / 像素颜色 / _solid_color 保留 / name+guid 保留
  PASS 纯色 env_map: sceneio emit -> VK build_materials 往返
  PASS 6 面 paths 环境贴图 (回归)      PASS 坏 env_map 容错
  ALL PASS   exit=0

python tests/_tmp/ab_batch.py
场景数 22, 门槛 MAE <= 0.0002, 失败 0 -> 全部通过 ✅

python tests/run_all.py
90 个 test_*.py, 0 条 FAIL 行, "全部测试完成 ✅", exit=0
```

### 11.5 真实 Vulkan 播放器冒烟

```
python vk_player.py --mini --frames 8 --size 320x200
加载 压测50球.json: 物体 1, 相机 轨道 target=(0.0, 1.0, 0.0) dist=6.0 | 物理后端: Culverin (Jolt)
设备: NVIDIA GeForce GTX 1050 Ti | format: bgra8unorm
=== Vk 播放 (物体 1) | 帧数 8 | 114.398 ms/帧 | FPS 8.7 ===
exit=0
```

---

## 12. 改动文件清单

| 文件 | 改动要点 |
|---|---|
| `scene_driver.py` | 贴图导入设置透传；**env_map 支持 `solid_color`（F7 联动，见 §1b）**；相机段 `_f3/_f1` + 默认值分键；LOD 读取（`apply_lod_from_dict` 等）+ `_update_lod` 早退/缓存（`_lod_world_pos/_xform_stamp`）；帧末 `_end_frame_input` 清滚轮 |
| `vk_player.py` | `_InputRetry` 限次重试；`_chain_callback` 链式转发 5 个 GLFW 回调；`_wheel_taken_by_scrollview` 滚轮消费合并；初始化段 → `VkInitError`、循环内异常 → `VkRunError`（不再 os._exit） |
| `run_player.py` | `VkInitError/VkRunError`；`_persist_backend`/`_handle_vk_init_failure`；`run_backend(explicit=)` 三段策略；`main` 传 explicit |
| `Loom.py` | `_launch_player` 实现 `LOOM_REMOTE_MODE` 分支；传 `explicit=(--backend 是否显式)` |
| `game_player.py` | `_run_backend_safe(explicit=)` 不吞 SystemExit/VkRunError、其余异常仍回退；`_start_pack`/`main` 透传 explicit |
| `tests/test_vk_material_tex_settings.py` | 新增（§1；§1b 追加 4 组 env_map 断言） |
| `tests/test_camera_robust_vk.py` | 新增（§2） |
| `tests/test_backend_fallback_policy.py` | 新增（§8/§9） |
| `tests/test_scene_driver_lod.py` | 新增（§3/§4/§5/§6/§7） |

`git status` 复核：仅上述 5 个源文件为 M，4 个测试为 ??（未 git add/commit）。
`Loom/tests/设置.json` 显示 M 但 `git diff` 为空（内容与 HEAD 逐字节等价，仅行尾/stat 差异，
是既有测试写设置的副作用，非本批修复引入）。

---

## 13. 遗留 / 新发现（未改，登记备查）

1. **`vk_ui.last_wheel_consumed` 的语义本身有缺陷**（P-09 根因在 `vk_ui.py:799`）：
   它是"本帧鼠标事件整体是否被消费"。本批只在 vk_player 侧合并判定（不改非本批文件）；
   若 vk_ui 批次修成"滚轮专属 consumed"，vk_player 的合并判定仍然成立（二者取与）。
2. **`yaw/pitch = "nan"` 字符串**：`float("nan")` 合法 → 两端都得到 NaN（GL 同样）。
   跨后端一致、不崩，但会让 VP 全 NaN；不在本批缺陷清单内，未改（建议 sceneio/scene_driver
   统一加 `isfinite` 校验）。
3. **`_update_lod` 的候选扫描**：无 LOD 时仍有 ~0.11ms/帧（500 物体，纯 getattr 扫描）。
   若要归零需缓存候选列表，但那会让运行期 `set_lod` 失效 —— 本批按"与 GL 同语义（每帧扫）"保留。
4. **`sceneio` 的 LOD 写入端尚未实现**（由别的批次负责）。本批读取端已兼容
   `lod_levels/lod_screen_levels/lod_bias` 与 `lod:{levels,screen_levels,bias}` 两种形态；
   若写入端最终形态不同，需要对齐 `apply_lod_from_dict` 的白名单。
5. **`game_player._start_pack` 的日志仍打印入参 backend**（scan_11 P-11，不在本批缺陷清单）：
   回退发生后 "渲染API=" 与实际生效后端可能不符。未改。
6. **vk_player 的看门狗 `os._exit(9)`**（渲染无进展 60s）未改 —— 本批 P-10 只覆盖
   draw 内异常；看门狗是"防卡死"最后手段，语义另议。
7. **远程模式（`LOOM_REMOTE_MODE=1`）未做端到端跑图验证**：需要真实 PySide6 离屏环境，
   本机未启动该窗口；代码路径与参数已按 `loom_player_window.run_player_window` 现有签名接线。
8. **`_update_lod` 与 vk_renderer.draw_frame 的世界矩阵仍是两份**（scan_05 §6 交叉建议）：
   彻底去重需要 vk_renderer 把本帧矩阵回传给 driver（非本批文件），本批只在 driver 侧
   做到"只给 LOD 物体算 + 缓存"。
