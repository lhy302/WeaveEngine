# 天空盒·渲染侧与播放器一致性 扫描报告（beta5 第三轮 / 编号 02）

- 审计对象：Loom 天空盒在 **渲染端（GL）· 播放器（GL/VK）· 驾驶层（SceneDriver）** 的生效/失效、资源生命期与双后端一致性
- 基线：`71b31ac..HEAD`（HEAD=d994b2e），即已发布 beta4 之后的全部改动
- 判定基准优先序：被审对象自身白盒契约（人类裁决 Q1/Q2/Q3/Q4/Q5/Q6=A 的记录、函数 docstring、sceneio 契约注释）> 语言/库规范 > 已有回归测试
- 只读：未改动任何受跟踪文件（§0.4 附 git status 证据）
- **行号口径**：文中所有 @@文件:行号@@ 均以基线仓库 d994b2e（审计开始时的工作树）为准。审计进行中，工作树被**并行的修复 agent** 改动（见 §0.5 对账），当前行号可能已漂移；结论与复测输出不受影响。

---

## 0. 范围与方法

### 0.1 文件清单与 diff 规模

| 文件 | 行数 | 本轮 diff | 本报告负责的函数/段 |
|---|---|---|---|
| Loom/engine.py | 1586 | +118/−0 | `effective_skybox` 1324-1339、`reset_sky_state` 1341-1352、`_warn_sky_once` 1354-1362、`__init__` 304-310 |
| Loom/loom_render.py | 983 | +248/−75 | `_sky_warn` 41-56、`_draw_skybox` 58-147、`_clear_main_fbo` 307-319、render 清屏 871-872、天空盒调用点 903-911、`_present_swap` 933-964、`run` 982-1019 |
| Loom/vk_renderer.py | 1916 | +27/−4 | `_ensure_sky` 947-999、`_draw_sky` 1001-1023、主 pass clear+天空 1962-1992、`draw_frame` 签字 1755 |
| Loom/loom_shaders.py | 429 | +8/−1 | `CLEAR_COLOR_RGBA` 415、_SKY_* 415-450（未改） |
| Loom/loom_cubemap.py | 189 | +34/−34 | `from_solid` 80-136、`ensure_gl` 155-187 |
| Loom/scene_driver.py | 1382 | +39/−7 | `load_from_data` 560-611（相机级 skybox 597-609）、`effective_skybox` 1383-1398、`build_cameras` 361-381 |
| Loom/runtime.py | 278 | +5/−1 | `PlayerApp.__init__` base_dir 134-138 |
| Loom/vk_player.py | 668 | +4/−1 | `run_vk` base_dir 279-282、draw_frame 调用 583-588 |

`git diff --stat 71b31ac..HEAD` 合计 8 文件 +474/−130（含他人专项的桶计划/时钟改动；本报告只裁天空盒与清屏段）。

### 0.2 跑过的命令（全部只读；探针落在 Loom/tests/_tmp/，gitignore 覆盖）

```
python tests/_tmp/scan_beta5_02_a_cubemap.py      # Cubemap.from_solid 32 组边界 + ensure_gl 缺面/尺寸
python tests/_tmp/scan_beta5_02_b_effective.py    # skybox_set/clear -> 生效天空盒（真实 EditorApp/GLEngine 方法体）
python tests/_tmp/scan_beta5_02_c_gl_lifecycle.py # GL 状态机/资源/失败恢复（真实 moderngl 独立上下文 + 像素读回）
python tests/_tmp/scan_beta5_02_d_vk_sky.py       # VK _ensure_sky 缓存键/缺面/尺寸/tint（真实 wgpu 设备）
python tests/_tmp/scan_beta5_02_e_clear_tint.py   # 清屏底色实测 + GL tint 类型边界
python tests/_tmp/scan_beta5_02_f_camera_index.py # VK 相机级天空盒下标配对 vs build_cameras 跳项
python tests/_tmp/scan_beta5_02_g_parity.py       # GL/VK 缺面对称性 + packaged(scene_data) base_dir
python tests/_tmp/scan_beta5_02_h_realid.py       # 真实两次场景加载的 VK 缓存键
python tests/test_skybox_scene.py && python tests/test_skybox_engine_parity.py && python tests/test_cubemap.py   # 既有回归（全绿）
```

环境：Python 3.12.10 / moderngl 5.12.0 / GL `NVIDIA GTX 1050 Ti 3.3.0`（离屏 `create_standalone_context()`）/ wgpu Vulkan 适配器**可用**（`backend_type='Vulkan', DiscreteGPU`）→ 本报告 VK 侧结论均为实跑，无 UNVERIFIED。

### 0.3 关键函数清单（审查面）

`effective_skybox`（GL/VK 两份同口径）→ `_draw_skybox`（GL）→ `_ensure_sky`/`_draw_sky`（VK）→ `Cubemap.ensure_gl`（GL 资源）→ `from_solid`（颜色口径入口）→ `_clear_main_fbo`/`CLEAR_COLOR_RGBA`（清屏）→ `reset_sky_state`/`_warn_sky_once`/`_sky_prog` 哨兵（复位与告警）→ `SceneDriver.build_cameras` + 相机 skybox 配对（VK 数据层）→ `runtime.PlayerApp`/`run_vk` 的 base_dir（相对路径解析）。

### 0.4 只读自查

审计开始时（工作树干净）与本报告写完时的 `git status --porcelain` 对比：

```
# 审计开始 (T0) —— 与我在本任务中的任何写操作无关
 M docs/audit/scan_beta3_05_packaging_release.md
?? tools/lint_except_dist/            ?? tools/loom_lint_except.py

# 审计结束 (T1) —— 出现**他人并行修复**的未提交改动（非本报告所为）
 M Loom/agent_commands.py  Loom/editor.py  Loom/loom_logic_thread.py
 M Loom/loom_render.py     Loom/sceneio.py Loom/tests/test_skybox_scene.py
 M LoomHub/hub_commands.py LoomHub/hub_controller.py LoomHub/hub_update.py
?? docs/audit/scan_beta5_round_0{1,3,4,5}_*.md   (兄弟 agent 报告)
?? Loom/tests/test_clock_pause_restart.py
```

本报告**只写了两类路径**：`docs/audit/scan_beta5_round_02_skybox_render.md`（本文件）与 `Loom/tests/_tmp/scan_beta5_02_*.py`（8 个探针，被 `Loom/.gitignore:20 tests/_tmp/*` 覆盖，`git check-ignore -v` 已验）。上面 T1 的 `M` 条目我一次都没有 edit/write。

### 0.5 并发修复对账（截至本报告写完时的工作树）

| 项 | 当前状态 | 证据（当前工作树） |
|---|---|---|
| P-02-01（P1） | **已被并行修复**，复测通过 | editor.py:913-917 新增 `self._skybox = getattr(self,'_scene_skybox',None)` 写回；复测 `A1 渲染端 effective_skybox() = (255,0,0,255) -> 绘制门 = True`（基线时为 None/False） |
| P-02-14（P3） | **已被并行修复** | loom_render.py:1035 `self._glfw_shutdown()` 已恢复（并留了说明注释 1010-1012） |
| P-02-13（P3） | 仍存在（行号漂移到 editor.py:2301） | `_clear_main_fbo(0.10, 0.12, 0.16, 1.0)` 仍硬编码 |
| P-02-02（P2） | 仍存在 | scene_driver.py:602 `_cd = _cams_d[_i] ...` 未变 |
| P-02-03（UNK） | 仍存在 | vk_renderer.py:950 `key = (id(cube), ...)` 未变 |
| P-02-06（P2） | 仍存在 | loom_cubemap.py:122 `if not (0.0 <= fv <= 255.0)` 未变 |
| P-02-10（P3） | 仍存在 | engine.py:1358 `_sky_fail_logged` 仍无读者 |
| P-02-12（P2） | 仍存在 | runtime.py:136 `_base = ... if scene_path else None` 未变 |
| P-02-04/05/07/08/09/11/15/16 | 仍存在 | 对应文件本轮未被并行改动（loom_cubemap/vk_renderer/engine 的另两处/loom_render 的 `_draw_skybox` 段） |

> 该对账只说明"当前工作树有没有动到"，不等于修复已验收；P-02-01 的修复方向与我 §4 建议的 B 方案一致（命令层/刷新层写回 `_skybox`），复测输出见上表。

---

## 1. 粗筛清单（含跳过项留痕）

### 1.1 疑似项（六元组）

| ID | 位置 | 标签 | 初步方向（指向具体代码事实） |
|---|---|---|---|
| P-02-01 | agent_commands.py:1040-1049 + engine.py:1324-1339 | SEM-SILENT / SEM-DEFAULT | `skybox_set` 把 cube 写进 `_scene_skybox` 后立刻 `_skybox = None`，而 `effective_skybox()` 只回落到 `_skybox` |
| P-02-02 | scene_driver.py:596-609 | IFACE-PRECOND / AUDIT-ASYMMETRY | 相机级 skybox 用 `enumerate(self.cameras)` 下标索引 `data['cameras']`，而 `build_cameras` 会 `continue` 跳过非 dict 项 |
| P-02-03 | vk_renderer.py:950-951 | BND-RESOURCE / OVERFIT-HARDCODE | 缓存键 `(id(cube), guid, size)`：id() 在对象释放后会被 CPython 复用 |
| P-02-04 | loom_cubemap.py:163-167 vs vk_renderer.py:953-955 | AUDIT-ASYMMETRY / SEM-SILENT | 同一 `faces=None` 的 cube：GL 造 1x1 白纹理，VK `return False` 不画且零日志 |
| P-02-05 | vk_renderer.py:986-992 | BND-EMPTY / IFACE-PARTIAL | `for i in range(6): f = faces[i]` 对 5 面 cube 抛 IndexError，且不在任何 try 内 |
| P-02-06 | loom_cubemap.py:118-126 | SEM-MISMATCH | Q4=A 契约「0-1 浮点 -> 明确报错」，实现只校验 `0<=v<=255` → `(0.2,0.4,0.8)` 静默成 (0,0,1) |
| P-02-07 | loom_render.py:120-121 | AUDIT-ASYMMETRY | `_skybox_tint = None` 时 GL 把 None 传给 uniform 抛错→天空盒消失；VK 1014-1015 会回落 (1,1,1) |
| P-02-08 | loom_render.py:110-147 | SEM-SILENT / AUDIT-DEADCODE | 只有**编译**失败会置 `_sky_prog=False`；`bind`/`draw` 失败只告警不失效，`_sky_prog` 永久是死对象 |
| P-02-09 | loom_render.py:78-87 | BND-RESOURCE | `cube is None` 提前 return 在复位块之前 → `_sky_prog_for` 强引用旧 cube，其 `_gl_tex` 不释放 |
| P-02-10 | engine.py:1352 + 1354-1362 | AUDIT-DEADCODE | `reset_sky_state` 写 `_sky_fail_logged=False`，全仓库无读者；且不清 `_sky_warned` |
| P-02-11 | loom_render.py:86-108 + grep | SEM-DEFAULT | 上下文丢失后 `_sky_prog` 无失效入口（`reset_sky_state` 只被 editor 换天空盒时调） |
| P-02-12 | runtime.py:134-138 / vk_player.py:279-282 | IFACE-PRECOND | `scene_data is not None` 时 `scene_path is None` → base_dir=None → 六面图相对路径按 CWD 解析 |
| P-02-13 | editor.py:2296 vs loom_shaders.py:415 | AUDIT-DOCIMPL | `CLEAR_COLOR_RGBA` 注释称「唯一定义处」，editor.py 仍硬编码同一字面量（引用该常量的模块不含 editor.py） |
| P-02-14 | loom_render.py:1015-1019（旧版尾部为 `self._glfw_shutdown()`） | SEM-DEFAULT / BND-RESOURCE | `run()` 退出不再 terminate GLFW；生产代码中已无 `_glfw_shutdown` 调用点 |
| P-02-15 | loom_render.py / loom_shaders.py / loom_cubemap.py 尾行 | AUDIT-DOCIMPL | diff 三处 `\ No newline at end of file` |
| P-02-16 | loom_render.py:903-911 vs editor.py:2339 | AUDIT-ASYMMETRY | 播放器无条件 `try: _draw_skybox()`；editor.render 仍有前置门（两入口语义不一致，且该门依赖 P-02-01 的缺陷值） |

### 1.2 跳过登记（可审计理由）

| SKIP | 位置 | 跳过理由（四类之一 + 出处） |
|---|---|---|
| SKIP-01 | loom_shaders 的 _SKY_VERT/_SKY_FRAG | 四类③：本轮 diff 未改 shader 源码（`git diff 71b31ac..HEAD -- Loom/loom_shaders.py` 只有 CLEAR_COLOR_RGBA + 行尾）；能力由既有 `tests/_tmp/smoke_skybox_vao.py` A/B/C/D 覆盖 |
| SKIP-02 | 六面图**采样朝向**（FACES 顺序） | 四类③：`Cubemap.FACES` 26 行与 `from_files` 53-75 行本轮均未改（diff 无该 hunk）；已有 `tests/_tmp/skybox_orient_probe.py` |
| SKIP-03 | `Cubemap.ensure_gl` 的 mipmap/filter 段（172-184） | 四类④：moderngl 文档保证 `build_mipmaps` 失败抛异常、`filter` 可写；代码已 try/except 且只在 has_mip 时用 MIPMAP filter（防"mip 链不完整采样黑"经典陷阱） |
| SKIP-04 | runtime.py 除 134-138 外全部 | 四类③：diff 仅 3 行（`import os` + base_dir），其余非天空盒面；键鼠锁定段属别的专项 |
| SKIP-05 | vk_player.py 除 279-282 外全部 | 四类③：diff 仅 4 行；UI 输入桥/循环退出语义非天空盒面 |
| SKIP-06 | `loom_render._prepare_bucket_frame` 全局桶计划（+175 行） | 四类③：属 01 号「性能·桶」专项（`docs/audit/scan_beta5_round_01_skybox_scene.md` 覆盖） |
| SKIP-07 | `engine._clock_advance` / `get_logic_time_ratio`（+67 行） | 四类③：属 03 号「时钟/TPS」专项（`docs/audit/scan_beta5_round_03_perf_clock_buckets.md`） |
| SKIP-08 | editor.py 相机/投影/gizmo 段 | 四类③：非天空盒面；本报告只引用 `editor.render` 2339-2343 的绘制门与 `_refresh_effective_skybox` 906-922 |

粗筛计数：疑似 16 项 / 跳过 8 项（跳过率 33%，全部有可审计出处，无「看起来简单」类理由）。

---

## 2. 逐项裁决

> 每项先**反手（证伪：枚举全部路径试图证明无 bug）**，再**正手（证真：最小复现）**。8 段式：1 判定基准 / 2 代码证据 / 3 路径枚举（反手）/ 4 最小复现（正手）/ 5 预期 vs 实际 / 6 差异 / 7 可复现验证 / 8 等级。

---

### P-02-01 【REGRESSION】skybox_set 之后生效天空盒变 None —— 编辑器视口天空盒直接消失且不自愈 — P-PROVED（P1）

**1 判定基准**
- 人类裁决 Q3=A（engine.py:1324-1329 docstring）：「**生效**天空盒: 相机级 (active_camera.skybox) 优先, 否则场景级」。
- `skybox_set` 命令语义（agent_commands.py:968 装饰器）：「设置场景级天空盒」——成功即应看得见。

**2 代码证据（原样引用）**
```python
# agent_commands.py:1040-1049
ed._scene_skybox = cube
ed._skybox_valid = True
ed._skybox_error = None
ed._skybox = None                  # 强制 refresh 走"变更"分支（重编 GPU 资源）
eff = ed._refresh_effective_skybox() if hasattr(ed, '_refresh_effective_skybox') else cube
...
'effective': ('camera' if eff is not None and eff is not cube else 'scene')}

# engine.py:1336-1339
cube = getattr(cam, 'skybox', None) if cam is not None else None
if cube is not None:
    return cube
return getattr(self, '_skybox', None)      # <- 只认 _skybox，不认 _scene_skybox

# editor.py:2339-2343
if self.effective_skybox() is not None:
    try: self._draw_skybox()
```

**3 路径枚举（反手：试图证明不会丢）**
- 路径 A：`active_camera_object()` 非 None 且 `cam.skybox` 非 None → 返回相机级 → **不受** `_skybox=None` 影响（探针 b/C1：'effective'='camera'，绿）。排除。
- 路径 B：`active_camera_object()` 为 None 或 `cam.skybox is None` → `return getattr(self,'_skybox',None)`，此刻 `_skybox` 被命令层置 None → 返回 None。**命中**。
- 路径 C：`_refresh_effective_skybox()` 会把 `_scene_skybox` 写回 `_skybox`？editor.py:906-922 全文只有"比较 `_sky_eff_last` → 调 `reset_sky_state()` → 返回 eff"，无任何写 `_skybox` 的语句。排除。
- 路径 D：其它 `_skybox` 写点 —— grep 全仓（排除 tests）：`sceneio.py:1323`（加载场景时与 `_scene_skybox` 同时写）、`editor.py:1229`（新建场景）；两者都不在命令路径上。排除。
→ 反手失败（存在会产生疑似行为的路径 B）。

**4 最小复现（正手）**：`tests/_tmp/scan_beta5_02_b_effective.py`（EditorApp/GLEngine **真实方法体** + `__new__` 桩，与 `tests/test_skybox_scene.py` 同款 harness）

**5 预期 vs 实际（实测输出）**
```
=== A) 新建场景后 -> skybox_set 红 -> 渲染端读到的"生效天空盒" ===
A0 新建后 _scene_skybox = (58, 155, 213, 255)  _skybox = (58, 155, 213, 255)  effective = (58, 155, 213, 255)
A0 editor.render 绘制门 (effective_skybox() is not None) = True
A1 skybox_set -> {'ok': True, 'effective': 'scene', 'error': None}
A1 命令返回后: _scene_skybox = (255, 0, 0, 255)  _skybox = None
A1 渲染端 effective_skybox() = None  -> 绘制门 = False
=== B) 再调一次 _refresh_effective_skybox（编辑器每帧/换场景都会调） ===
B1 refresh 返回 = None  _skybox = None  effective = None
```
预期：设置场景级红色天空盒后视口显示红天空盒（beta4 `ed._skybox = cube` 即如此）。
实际：视口不画天空盒（裸清屏底色 25,31,41），每次 `_refresh_effective_skybox()` 仍 None、不会自愈；命令还回 `'effective': 'scene'`（误导）。

**6 差异**：场景级 cube 被写进**不参与渲染判定**的字段；渲染端读的是被清空的字段 → 功能缺失，且查询层（`skybox_get`）与视口不一致（静默失败）。

**7 可复现验证**
```
cd Loom && python tests/_tmp/scan_beta5_02_b_effective.py
git show 71b31ac:Loom/agent_commands.py | Select-String "ed._skybox = cube"
```

**8 影响与等级**：P1（用户可见的功能错误）+ [REGRESSION]（Q 系列新代码引入；旧实现直接写 `_skybox`）。

> **状态（T1 复测）**：已被并行修复 agent 修好 —— editor.py:913-917 新增 `self._skybox = getattr(self,'_scene_skybox',None)` 后，同一探针输出变为
> `A1 渲染端 effective_skybox() = (255, 0, 0, 255)  -> 绘制门 = True`、`B1 refresh 返回 = (255, 0, 0, 255)`。
> 该修复方向 = §4 的 B 方案；本项保留在报告里作为**回归证据**（谁把 `_scene_skybox`/`_skybox` 双字段拆开，就会重新触发）。

---

### P-02-02 VK 相机级天空盒按**下标**配对，build_cameras 跳项导致错配到别的相机 — P-PROVED（P2）

**1 判定基准**：scene_driver.py:597 注释「与 sceneio._apply_cameras **同口径**、同 base_dir」——同口径意味着 cube 必须挂在**它自己那条 camera 记录**上。

**2 代码证据**
```python
# scene_driver.py:596-604
self.cameras = build_cameras(data)           # build_cameras: 非 dict 项 continue (361-367)
_cams_d = data.get('cameras') or []
for _i, _c in enumerate(self.cameras):
    _cd = _cams_d[_i] if _i < len(_cams_d) else None      # <- 下标来自"过滤后"列表
```

**3 路径枚举（反手）**
- 路径 A：`data['cameras']` 全是 dict → 过滤前后等长 → 下标对齐，无 bug（探针 f/A1：c1=绿 c2=红，正确）。
- 路径 B：含 ≥1 个非 dict 项 → `build_cameras` 少产 1 个相机 → 之后每个 `_i` 错位一位。**命中**。
- 路径 C：`build_cameras` 还有别的跳过条件？通读 361-381，只有 `if not isinstance(d, dict): continue` 一处。排除。
- 路径 D：`_cams_d` 为空/None → `_cd=None` → 仍会执行 `_c.skybox = None`（把相机级清空、回落场景级）；是另一种错误但无崩溃。
→ 反手失败。

**4 最小复现**：`tests/_tmp/scan_beta5_02_f_camera_index.py`（真实 `SceneDriver.load_from_data`）

**5 预期 vs 实际（实测）**
```
=== A) 干净数据 ===
A1 cameras = [('c1', (0, 255, 0, 255)), ('c2', (255, 0, 0, 255))]
A2 effective_skybox = (0, 255, 0, 255)
=== B) 相机段含 1 个非 dict 项 (null) ===
B1 cameras = [('c1', None), ('c2', (0, 255, 0, 255))]     # 期望 c1=绿 c2=红
B3 active c2 -> effective_skybox = (0, 255, 0, 255)        # 期望 红
=== C) GL 侧对照: 同一份数据走 sceneio._apply_cameras ===
C1 GL _apply_cameras RAISE AttributeError 'NoneType' object has no attribute 'get'
```

**6 差异**：激活相机 c2 拿到**本应属于 c1 的绿色**；c1 变无相机级。同时暴露两端错误模型分叉：GL 直接 AttributeError（加载期炸、有人看得见），VK 静默错配。

**7 可复现验证**：`cd Loom && python tests/_tmp/scan_beta5_02_f_camera_index.py`

**8 影响与等级**：P2（静默视觉错误；场景文件由工具/人手写 JSON 时 `cameras: [null, ...]` 可达）。注：同源的 `link_camera_parents` (384-393) 用 `zip` 也有同类错位，说明这是**被复制的既有坏模式**，但"相机天空盒"是本轮新写。

---

### P-02-03 VK 天空盒缓存键含 id(cube)：id 复用可能让旧立方纹理不被替换 — **P-UNKNOWN**

**1 判定基准**：vk_renderer.py:948 docstring「懒建…（cube 变化才重建）」——"cube 变化"应指内容/身份变化，不应依赖内存地址。

**2 代码证据**：`key = (id(cube), getattr(cube,'guid',None), getattr(cube,'size',0))`（950）；`if self._sky_pipe is not None and self._sky_cube_key == key: return True`（951-952）。

**3 路径枚举（反手）**
- 路径 A：新旧 `id` 不同 → 键不等 → 重建（正确）。
- 路径 B：新旧 `guid` 或 `size` 不同 → 键不等 → 重建（正确）。
- 路径 C：`guid` 与 `size` 相同 **且** 旧 cube 释放后新 cube 复用同一地址 → 键相等 → **不重建（陈旧纹理）**。
→ 反手失败（C 存在）。

**4 最小复现（正手，两次不同现实度）**
- c/D（最小序列，同进程紧邻分配）：**复现**
```
A1 _ensure_sky = True  key = (2849338294880, 'guid-same', 4)
B1 新 cube guid=guid-same size= 4  key = (2849338294880, 'guid-same', 4)
B2 key 与上一次相等 = True
B3 _ensure_sky(B) = True  _sky_tex 是否被重建 = False      # <- 仍是红纹理, 场景要的是蓝
```
- h（真实两次 `scene_from_dict` 换场景）：**未复现**（中间分配把槽位用掉了）
```
1) scene1 skybox guid = guid-fixed-0001  id = 1678367684608
2) scene2 skybox guid = guid-fixed-0001  id = 1678367478160
   key 相等 = False   _ensure_sky = True   纹理被重建 = True
```

**5 预期 vs 实际**：预期键只由"内容身份"决定；实际由"地址 + guid + size"决定，地址可复用。

**6 差异**：键**不健全**（最小序列已证明可相等并导致陈旧纹理），但真实换场景序列未触发 → 无法给出必现的最小复现。

**7 已尝试探针（2 次）**：c/D、h。**还缺的信息**：CPython pymalloc 在 `load_from_data` 这种"释放后紧跟大量其它分配"的序列里是否仍会给同尺寸对象回同一地址。**建议第 3 次探针（未跑）**：循环 200 次同 guid/不同色 `scene_from_dict`，统计 `key 相等` 次数；>0 即升 P-PROVED。

**8 等级**：P-UNKNOWN。修复方向：键改用单调递增 generation 或"guid+内容指纹"，不用 `id()`。

---

### P-02-04 同一 faces=None 的 cube：GL 画全白、VK 不画且零日志 — P-PROVED（P2）

**1 判定基准**：`Cubemap` docstring「CPU 侧持 6 面 RGBA」；Q 系列要求双后端同一语义，且"画不出来"必须可见（Q5=A 的"失败必须可见"）。

**2 代码证据**
```python
# loom_cubemap.py:164-167  (GL)
faces = self._faces
if not faces:
    faces = [np.full((1, 1, 4), 255, dtype=np.uint8) for _ in range(6)]
    self.size = 1                       # 顺带就地改 size
# vk_renderer.py:953-955  (VK)
faces = getattr(cube, '_faces', None)
if not faces:
    return False                        # 静默: 无日志; 调用方 1002-1003 也直接返回
```

**3 路径枚举（反手）**：GL 两条（`_faces` 有值→真纹理；None→1x1 白兜底）；VK 两条（有值→纹理；None→False）。调用方 `_draw_sky` 1002-1003 `if not self._ensure_sky(cube): return False`，外层 `if self._draw_sky(...): pass` 无 else → 全程无日志。两条链都不产生"报警" → 反手（无差异）失败。

**4 最小复现 + 5 预期 vs 实际**
```
d/C1  _ensure_sky(faces=None) = False                       # VK: 不建纹理
d/H1  _draw_sky(...) = False                                # VK: 静默返回, 无 print
g/A1  GL pixel = (255, 255, 255)                            # GL: 全白天空
g/A2  ensure_gl 后 size 被就地改成 = 1
```

**6 差异**：同一 Cubemap → GL 全白、VK 裸清屏；VK 无诊断；GL 还就地把 `size` 从 4 改成 1（副作用，影响 VK 缓存键的 size 维度）。

**7 可复现验证**：`python tests/_tmp/scan_beta5_02_d_vk_sky.py`（C/H）+ `python tests/_tmp/scan_beta5_02_g_parity.py`（A）

**8 等级**：P2（双后端视觉不一致 + 静默）。

---

### P-02-05 VK 侧缺面（<6）抛 IndexError 且穿透到渲染循环 — P-PROVED（P2，可达性受限）

**1 判定基准**：Q5=A「解析失败必须可见，并让调用方拿到原因」——失败应是可判定错误，而不是把渲染循环带崩；GL 侧同段（`faces[:6]`）不炸。

**2 代码证据**：`for i in range(6): f = faces[i]`（986-992）无长度检查；`_ensure_sky` 整体不在 try 内；调用方 `vk_player.py:583-603` 用 `except BaseException` 结束整个渲染循环。

**3 路径枚举（反手）**
- 正常来源全部强制 6 面：`from_files` 49-50、`skybox_from_dict` 613-615 → 不可达。
- 直接构造 `Cubemap(size, faces=[...5...])`（脚本/EAI/未来接口）→ 可达。
- `_faces` 为 5 项 tuple 等其它序列 → 同样命中。
→ 反手失败（可达性限于外部 API）。

**4 最小复现 + 5 预期 vs 实际**
```
d/D1 RAISE IndexError list index out of range             # VK
a/   GL: ensure_gl(5 faces) 无异常(第 6 层留黑)            # GL 对照
d/E1 VK _ensure_sky(mixed 4x4/8x8) = True                  # GL 对照: Error data size mismatch 256 != 64
```

**6 差异**：①缺面：VK 抛错（播放器升级为终止循环），GL 静默留黑层；②各面尺寸不一致：VK 竟**返回 True** 并用 `bytes_per_row=w*4` 把 8x8 面裁成垃圾（无报错），GL 抛 size mismatch。

**7 可复现验证**：`python tests/_tmp/scan_beta5_02_d_vk_sky.py`（D/E 段）+ `python tests/_tmp/scan_beta5_02_a_cubemap.py`（5 面/混合尺寸段）

**8 等级**：P2（崩溃路径，当前仅外部 API 可达）+ 双后端失败模型不一致 + VK 静默脏写入。

---

### P-02-06 from_solid 仍静默接受 0-1 浮点（Q4=A 契约未落地）— P-PROVED（P2）

**1 判定基准**
- sceneio.py:548-549（Q4=A 契约原文）：「颜色只认 0..255 的整数（或**整值浮点**）; **0-1 浮点** / 越界 / 长度错 -> **明确报错，不得用 int() 静默截断**（历史病灶: [0.2,0.4,0.8] -> int -> (0,0,0) 全黑）」。
- loom_cubemap.py:84-87（新 docstring）：「越界 / 非数值 / 非法颜色串一律 ValueError（命令层由 03 号负责给出可读拒绝，**这里是最后一道防御**）… 会把 0.5 这类非法输入静默变成合法颜色 128」。

**2 代码证据**
```python
# loom_cubemap.py:118-125
for i, v in enumerate(rgba):
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise ValueError(...)
    fv = float(v)
    if not (0.0 <= fv <= 255.0):            # 0-1 浮点完全在范围内 -> 不报错
        raise ValueError(...)
    out.append(int(round(fv)))              # 0.2 -> 0 ; 0.8 -> 1
```

**3 路径枚举（反手）**
- `skybox_set` 命令 → 先过 `sceneio.parse_color`（586-589 明确拒绝非整值浮点）→ 挡住。排除。
- `sceneio.skybox_from_dict(solid=...)` → 也走 `parse_color`（633）→ 挡住。排除。
- `agent_commands.cmd_set_env` 1765-1778：`color = args.get('color')` **直接** `Cubemap.from_solid(color, size=16)`，不过 parse_color → **命中**（0-1 浮点不会报错）。
- 脚本直接 `Cubemap.from_solid((0.2,0.4,0.8))` → 命中。
→ 反手失败。

**4 最小复现 + 5 预期 vs 实际**
```
a) 0-1 floats (was auto*255)  -> OK   _solid_color=(0, 0, 1, 255)      # 预期 ValueError
a) 1.0 floats (was 255)       -> OK   _solid_color=(1, 1, 1, 255)      # 预期 ValueError
a) fraction 85.0              -> OK   _solid_color=(85, 0, 0, 255)     # 非整值浮点, 预期报错
a) NaN ch0                    -> RAISE ValueError 通道 0 越界 (nan)    # 这条是对的
a) numpy int array            -> RAISE ValueError 通道 0 不是数值: np.int64(58)   # 见 P-02-06b
```

**6 差异**：契约说"0-1/非整值浮点 → 明确报错"，实现只拦越界与非数值；`(0.2,0.4,0.8)→(0,0,1)`、`1.0→(1,1,1)` 静默近黑——正是 Q4=A 要消灭的病灶。docstring 里"0.5 会变 128"的假设与实际（0.5→0）也不一致。

**7 可复现验证**：`python tests/_tmp/scan_beta5_02_a_cubemap.py`；可达路径见 agent_commands.py:1765-1778（`cmd_set_env`）

**8 等级**：P2（静默错色，命令层可达）。附 **P-02-06b（P3）**：`from_solid` 拒绝 numpy 整数（`np.int64` 不是 `int`），而本仓库颜色普遍以 numpy 传递；`bytearray` 反而被接受。

---

### P-02-07 _skybox_tint = None：GL 天空盒消失，VK 照常 — P-PROVED（P3）

**1 判定基准**：`_draw_skybox`/`_draw_sky` 的 tint 契约是「vec3 乘子，缺省 (1,1,1)」；非法值应回落而非静默丢整个天空盒。

**2 代码证据**：GL `self._sky_prog['u_skybox_tint'].value = getattr(self,'_skybox_tint',(1.0,1.0,1.0))`（120-121）——`getattr` 默认值只在**属性缺失**时生效，属性存在且为 None 就把 None 交给 moderngl；VK `if tint is None: tint = getattr(self,'skybox_tint',(1.0,1.0,1.0))`（1014-1015）显式处理。

**3 路径枚举（反手）**：tint 只有 3 态：缺失（GL→(1,1,1) OK）、正常三元组（OK）、存在但 None/四分量（GL 抛，VK 回落）。→ 反手失败。

**4 最小复现 + 5 预期 vs 实际**
```
e/D  3 float -> OK     4 float -> RAISE error: pack expected 3 items for packing (got 4)
e/D  None    -> RAISE TypeError: Value after * must be an iterable, not NoneType
g/B1 正常 tint -> (0, 200, 0)      g/B2 tint=None -> (0, 0, 0)   # 天空盒整块消失(VK 会回落照画)
```

**6 差异**：GL 把"参数非法"放大成"天空盒消失"（`_sky_warn` 只报一次，后续无声）；VK 只丢 tint。

**7 可复现验证**：`python tests/_tmp/scan_beta5_02_e_clear_tint.py`（D）+ `python tests/_tmp/scan_beta5_02_g_parity.py`（B）

**8 等级**：P3（当前无命令写 tint，仅脚本可触）。

---

### P-02-08 只有"编译失败"会失效化；bind/draw 失败后 _sky_prog 永是死对象且无自动重建入口 — P-PROVED（P2）

**1 判定基准**：loom_render.py:67-70 docstring「编译失败不再是**永久**哨兵：按生效天空盒对象隔离，换了对象/场景会重试一次」+「任何失败都'告警一次 + 本帧跳过'」——复位语义应覆盖**全部失败类**。

**2 代码证据**：只有 105-109 的 except 写 `self._sky_prog = False`；`bind` 失败（124-126）与 `draw` 失败（139-140）只 return/告警，**不改状态** → 下一帧 `is False` 为假、`is None` 为假 → 不再重建。

**3 路径枚举（反手）**：复位触发器全集 = ①`_sky_prog_for is not cube`（81-85，要求对象身份变化）；②`reset_sky_state()`（grep 全仓调用点只有 `editor._refresh_effective_skybox` editor.py:916，且只在 `eff is not _sky_eff_last` 时）。GL **播放器（PlayerApp）** 内 `reset_sky_state` 调用点为 0 → 播放器里"cube 不变 + 程序失效"= 永不恢复。→ 反手失败。

**4 最小复现 + 5 预期 vs 实际**（真实 GL 上下文；把 `_sky_prog` 换成任何访问都抛的桩，等价于程序失效/上下文丢失）
```
E1..E5 pixel = (0, 0, 0)  _sky_prog 类型 = _DeadProgram     # 5 帧全黑
E6 5 帧后 _sky_prog 仍是失效对象 = True  累计 __getitem__ 次数 = 5
E7 reset_sky_state() 后: pixel = (10, 20, 30)  _sky_prog 类型 = Program   # 手动复位即恢复
```

**6 差异**：恢复能力存在（`reset_sky_state` 有效），但**没有任何自动入口**在失败后调用它；告警还被 `_sky_warned` 锁死（见 P-02-10）→ 用户看到"天空盒突然永久消失且无日志"。

**7 可复现验证**：`python tests/_tmp/scan_beta5_02_c_gl_lifecycle.py`（E 段）

**8 等级**：P2（一旦触发即永久缺功能）；触发源的现实可达性见 P-02-11（UNKNOWN）。

---

### P-02-09 _skybox=None 时旧 prog/VAO/VBO 与旧 cube 的 GPU 立方纹理继续被强引用 — P-PROVED（P3）

**1 判定基准**：`Cubemap.ensure_gl` 已立纪律（158-163）「换 ctx 时先 release 旧纹理, 防旧 GPU 资源泄漏」——天空盒状态机应对称释放/丢弃。

**2 代码证据**：`if cube is None: return`（78-79）位于复位块（81-85）**之前** → cube 变 None 时 `_sky_prog_for` 仍持旧 cube；`_sky_prog/_sky_vao/_sky_vbo` 也不释放。

**3 路径枚举（反手）**：路径 A 换 cube（≠None）→ 81-85 复位 → 旧引用丢弃 → 可回收（实测 c/B2 = True），无泄漏；路径 B cube→None → 提前 return，引用保留（**命中**）；路径 C 进程退出 → OS 回收（不构成正当）。→ 反手失败。

**4 最小复现 + 5 预期 vs 实际**
```
B2 旧 cubemap A 可回收 = True                    # 换 cube 路径: 正常
C2 _sky_prog 仍非空 = True  _sky_vao 仍非空 = True  _sky_prog_for 仍指向 B = True
C3 旧 cubemap B 可回收 = False                   # <- 强引用, GPU 立方纹理随对象存活
C4 B._gl_tex 仍在 = True
```

**6 差异**：`skybox_clear` / 无天空盒场景期间，一张 6 面立方纹理（真实场景 512–4K×6）与一套 VAO 一直挂在渲染端；`reset_sky_state()` 也不释放它们（c/D2 显示旧 prog/VAO 仅靠引用计数被回收）。

**7 可复现验证**：`python tests/_tmp/scan_beta5_02_c_gl_lifecycle.py`（B/C/D）

**8 等级**：P3（有界保留 1 份，量级随天空盒分辨率；但违反同文件 ensure_gl 已立纪律）。

---

### P-02-10 _sky_fail_logged 是死字段；reset_sky_state 不清 _sky_warned — P-PROVED（P3）

**1 判定基准**：`reset_sky_state` docstring「哨兵/程序/VAO 全部失效, 下次绘制重编译」——"复位"应由状态字段驱动；写了不读的字段属 AUDIT-DEADCODE。

**2 代码证据**：engine.py:1352 写 `self._sky_fail_logged = False`；全仓 grep 读者 = 0（只有 `tests/test_skybox_scene.py:318/322` 的断言与 `_tmp/_edit_sky_engine.py` 的补丁文本）；真正决定是否打印的是 `_sky_warned`（1354-1362），`reset_sky_state` 不动它。

**3 路径枚举（反手）**：`_sky_warn_once` 只有 2 个实现（engine 1354-1362、loom_render 50-56），都用 `_sky_warned`；`_sky_fail_logged` 无读点 → 不参与任何判定。→ 反手失败。

**4 最小复现 + 5 预期 vs 实际**
```
c/D3 _sky_warned 是否被清 = {'program': 1}   _sky_fail_logged = False
```
预期："复位 → 重新能告警"；实际：`_sky_warned` 仍在 → 复位后的同类失败不再打印。（`tests/test_skybox_scene.py:322` 只断言 `_sky_fail_logged is False`，该死字段因此被测试"保护"着。）

**6 差异**：注释/测试宣称的"失败标记复位 → 重新告警"链路不存在。

**7 可复现验证**：`python tests/_tmp/scan_beta5_02_c_gl_lifecycle.py`（D3）；`Select-String -Path Loom\*.py -Pattern _sky_fail_logged`（0 读点）

**8 等级**：P3（可观测性/可维护性）。

---

### P-02-11 GL 上下文丢失/重建后的恢复可达性 — **P-UNKNOWN**

**1 判定基准**：`Cubemap.ensure_gl` 已有换 ctx 保护（158-163）；天空盒 program/VAO 无同类保护，二者应当对称。

**2 代码证据**：loom_cubemap.py:138-153 `_same_ctx/_remember_ctx`；loom_render 侧 `_sky_prog` 无任何 ctx 记录/校验。

**3 路径枚举（证伪尝试）**
- 仓库内 `self.ctx = ` 写点：engine.py:289/293（构造期一次）、gui.py:77、loom_player_window.py:89、ui/loom_gui.py:166/471/519（`_init_offscreen_gl` 每次**新建 EditorApp/引擎**，不复用旧引擎）→ **未找到"活的引擎换 ctx"入口**。
- 外部 Qt 宿主重建 `QOpenGLContext`（GPU 重置/驱动恢复）→ 会同时重建 EditorApp，理论上不会留在旧引擎上。
→ 仓库内证伪成功、进程外（GPU 重置/远程桌面上下文丢失）无法枚举 → 判不了。

**4-6 正手尝试**：不做真实上下文切换（跨 ctx 使用 moderngl 对象属未定义行为，可能段错误，且会把探针变成制造事故）。已用 c/E 的等价机制证明**状态机缺口**（P-02-08 PROVED）与**存在复位函数**；缺的一环是"现实里谁能把 `_sky_prog` 弄坏"。

**7 已尝试探针**：c/E（程序失效等价路径）、全部 `.ctx` 写点 grep。**还缺的信息**：是否存在宿主侧"保留引擎、重建上下文"的入口（需看 `loom_player_window.py` / `qt_view.paintGL` 与 GLFW 窗口重建路径，属宿主专项）。**建议下一步**：`grep -n "glfw.destroy_window|QOpenGLContext()" Loom/`"。

**8 等级**：P-UNKNOWN（状态机缺口已证，触发源待定）。

---

### P-02-12 打包（scene_data）模式 base_dir=None → 六面图相对路径按 CWD 解析 — P-PROVED（P2）

**1 判定基准**：Q6=A（runtime.py:134-135 注释原文）「场景目录作为 base_dir —— skybox 六面图的**相对路径**按它解析（**不传的话播放器按 CWD 解析，换目录启动就找不到图** -> 只能回退默认蓝）」——这正是要消灭的病灶。

**2 代码证据**
```python
# runtime.py:128-138
if scene_data is not None:            # 打包/游戏包模式: scene_path 为 None
    data = scene_data
...
_base = (os.path.dirname(os.path.abspath(scene_path)) if scene_path else None)
sceneio.scene_from_dict(self, data, camera_out=cam_out, base_dir=_base)
# vk_player.py:280-282 同构: _base_dir = dirname(abspath(scene)) if scene else None
```

**3 路径枚举（反手）**
- 路径 A：明文场景文件（`--run scene.json`）→ base_dir=场景目录 → 正确（探针 g/C3 + 既有 `test_skybox_engine_parity` C 段全绿）。
- 路径 B：`.lsc` 游戏包 → `scene_data` + `scene_path=None` → base_dir=None → 相对路径按**进程 CWD** → **命中**。
- 路径 C：调用方在打包路径额外传 base_dir？`PlayerApp.__init__` 无此参数（110-112）；`run_vk` 只用 `scene`。排除。
→ 反手失败。

**4 最小复现 + 5 预期 vs 实际**
```
C1 base_dir=None (CWD=场景目录) -> valid=True
C2 换目录启动 + base_dir=None  -> valid=False reason=第 0 面图片不存在: ...\Temp\px.png
C3 同一份数据 + base_dir=场景目录 -> valid=True paths=True
```

**6 差异**：与文件模式的播放器不同，**打包模式**下"换目录启动"仍丢六面图（回退默认蓝 + 一条 reason）——Q6=A 只覆盖一半。

**7 可复现验证**：`python tests/_tmp/scan_beta5_02_g_parity.py`（C 段）

**8 等级**：P2（发布形态相关；有回退与日志，故非 P1）。

---

### P-02-13 CLEAR_COLOR_RGBA 并非"唯一定义处"：editor.py 仍硬编码 — P-PROVED（P3）

**1 判定基准**：loom_shaders.py:411-415 注释「编辑器 / VK / GL 播放器必须共用这一个值 —— 旧实现三处字面值…」，即"单点定义"。

**2 代码证据**：`editor.py:2296`（基线）/ `editor.py:2301`（T1 工作树）`self._clear_main_fbo(0.10, 0.12, 0.16, 1.0)`；实测引用 `CLEAR_COLOR_RGBA` 的模块 = {loom_shaders, loom_render, vk_renderer}（不含 editor.py）。**T1 复测：仍未引用常量，本项仍成立。**

**3 路径枚举（反手）**：编辑器主 pass 走 `EditorApp.render`（自有 render，override 基类），唯一清屏点 = 2296；`_clear_main_fbo` 另一调用点 872 属 RenderMixin.render（播放器/基类）。两条路径各自硬编码/引用 → "单点"不成立。

**4 最小复现 + 5 预期 vs 实际**：`e/C1`（editor.py 命中 `_clear_main_fbo(0.10, 0.12, 0.16, 1.0)`）、`e/C2` 数值相等=True（今晚看不出偏差，改常量即分叉）、`e/C3` 引用模块清单。

**6 差异**：注释承诺单点，实际两处。
**7 可复现验证**：`python tests/_tmp/scan_beta5_02_e_clear_tint.py`（C 段）
**8 等级**：P3（漂移风险）。

---

### P-02-14 【REGRESSION】run() 退出不再调用 _glfw_shutdown() — P-PROVED（P3）

**1 判定基准**：旧版 71b31ac 的 `run()` 尾部（注释「2026-10-18 A2: GLFW terminate（原 pygame.quit）」）；`_glfw_shutdown` = `glfw.terminate()`（loom_glfw_window.py:402-406）。

**2 代码证据（git 事实）**
```
$ git show 71b31ac:Loom/loom_render.py | Select-Object -Last 12
        try:
            self.audio.shutdown()
        except Exception:
            pass
        # 2026-10-18 A2: GLFW terminate（原 pygame.quit）
        self._glfw_shutdown()

$ git diff 71b31ac..HEAD -- Loom/loom_render.py    # 末尾该 3 行被删; 现文件尾是 "except Exception: pass" (且无换行)
```

**3 路径枚举（反手）**：`_glfw_shutdown` 调用点 grep（排除 tests/_tmp）= 0；`editor.py:2370` 只调 `_glfw_swap_buffers` → 生产代码中 GLFW 永不 terminate。→ 反手失败。

**4/5**：`Select-String -Path Loom\*.py -Pattern _glfw_shutdown` → 仅定义处 loom_glfw_window.py:402；预期"run 结束即 terminate"，实际无调用。
**6 差异**：窗口/GLFW 全局状态不释放（同进程后续再开窗口/远程回读模式会叠窗）。
**7 可复现验证**：上面两条命令。
**8 等级**：P3（关闭路径资源回归；进程退出时 OS 兜底）。

> **状态（T1 复测）**：已被并行修复 —— 当前工作树 loom_render.py:1035 重新出现 `self._glfw_shutdown()`（并附 1010-1012 说明注释）。本项保留作回归证据。

---

### P-02-15 三个文件尾行失去换行符 — P-PROVED（P3）

`git diff` 在 loom_render.py / loom_shaders.py / loom_cubemap.py 尾部均标 `\ No newline at end of file`。影响：POSIX 工具链噪声、部分编辑器/打包脚本按行拼接行为；无运行期影响。等级 P3。

---

### P-02-16 播放器与编辑器入口的天空盒"绘制门"语义不一致 — P-PROVED（P3）

**1 判定基准**：`_draw_skybox` 已内建"cube is None → return"（78-79）与全路径 try，"绘制门"冗余；两入口应一致。
**2 代码证据**：`loom_render.py:905-911`（无条件 try 调用）；`editor.py:2339`（`if self.effective_skybox() is not None:` 再 try，且外层 2342 是**每帧** print 而非 `_sky_warn` once）。
**3 路径枚举（反手）**：门为真时两端等价；门为假时编辑器不进 `_draw_skybox`（只少一次早退，无功能差异）。**但**该门**自身**依赖 `effective_skybox()`，于是 P-02-01 的 None 让门永久为假 —— 门成了缺陷放大器 → 差异存在（非纯冗余）。
**4-6**：见 P-02-01 实测（A1 门=False）。
**7**：`python tests/_tmp/scan_beta5_02_b_effective.py`
**8 等级**：P3（可维护性；与 P-02-01 联动）。

---

### 已证伪项（P-DISPROVED，留证避免重复粗筛）

**P-02-D1 换 cubemap 未显式 release 旧 program/VAO/VBO → 泄漏？** — 反手成功：三条路径（换 cube / reset_sky_state / 进程退出）中前两者让旧对象引用计数归零，moderngl 在 `__del__` 释放 GL 句柄；实测 `weakref` 证旧 cubemap 可回收（c/B2 = True）、旧 Program/VAO reset 后不再存活（c/D2 = False）。→ 无泄漏（真问题在 P-02-09 的 None 路径与 P-02-08 的失败路径）。

**P-02-D2 loom_render 外层 except 会每帧刷屏？** — 反手成功：`_draw_skybox` 内 72-147 全路径覆盖（取 cube / 复位块 / 建程序 / inv / uniform 绑定 / 读状态 / 绘制 / finally），唯一未包裹的是纯属性赋值与 `cube is None` 的 return；实测 5 帧失效场景只 1 条告警（c/E1..E5）。→ 外层 print 实际不可达（留着无害，但一旦可达就是每帧刷屏）。

**P-02-D3 Q2=A 清屏底色改动造成"无天空盒无地板"可见性回归？** — 反手成功（3 条路径）：①编辑器 2296 本来就是 0.10/0.12/0.16（未变）；②VK 本就是 0.10/0.12/0.16（引用常量、数值未变）；③只有 GL 播放器从 (0.05,0.05,0.1) 变为 (0.10,0.12,0.16)，实测像素 (13,13,25)→(25,31,41)（e/B1、e/B2），即底色变亮而非变黑/闪；且 Q1=A 后场景加载**必然**带默认天空盒（sceneio 1319-1323），裸清屏只在 `skybox_clear` 或 GPU 侧建纹理失败时可见。→ 属设计意图内的可见性变化（是否需要提示人类，见 §5 Q2）。

**P-02-D4 播放器无条件调用 _draw_skybox() 引入每帧额外开销？** — 反手成功：无天空盒时 `effective_skybox()→None → 78-79 立刻 return`（一次 `active_camera_object`（`find_camera` 线性扫相机）+ 两次 getattr），无 GL 调用。→ 可忽略。

**P-02-D5 ⑥ VK tint 接线后未初始化时是否 NaN/未定义？** — 反手成功：`_tint = getattr(engine,'_skybox_tint',None)`（1974）；VK 播放器传的 `engine` 是 `SceneDriver`（vk_player.py:584），该对象无 `_skybox_tint` 也无 `skybox_tint`（grep scene_driver 0 命中）→ 走 1014-1015 回落 (1.0,1.0,1.0)（实测 f/F1-F3）。→ 默认值确定、无 NaN。**但**注释「tint 的唯一来源是引擎的 `_skybox_tint`」在 VK 播放器链路上**没有实际来源**（两端 tint 的权威对象不同：GL=GLEngine，VK=SceneDriver 实例），故本轮 P-06 的接线对玩家路径**无实效** —— 记 AUDIT-DOCIMPL（P3），非运行期 bug。另：4 分量 tint 触发 `ValueError: could not broadcast (4,) into (3,)`（d/G1），被 draw_frame 1985 的 try 收走 → 本帧跳过，可接受。

**P-02-D6 六面图非 2 的幂 / 顺序错？** — 反手成功：四类理由第③④类——`from_files` 强制正方形 + 各面等尺寸（66-73）；GL 3.3 与 VK 均允许 NPOT 立方纹理 + mipmap（本机 GTX1050Ti 3.3.0 实测 `smoke_skybox_vao.py` C/D 通过）；FACES 顺序本轮未改（SKIP-02）。→ 无新增风险。

---

## 3. 统计

| 判定 | 数量 | 编号 |
|---|---|---|
| P-PROVED | 14 | 01、02、04、05、06（+06b）、07、08、09、10、12、13、14、15、16 |
| P-DISPROVED | 6 | D1、D2、D3、D4、D5、D6 |
| P-UNKNOWN | 2 | 03（VK 缓存键 id 复用触发率）、11（GL ctx 丢失可达性） |
| P-CONTRADICTION | 0 | — |

- **P-UNKNOWN ≠ 0**（协议要求）：两项都是"缺口已在代码层存在、触发率/触发源无法在当前仓库内枚举"的项，见各自 §7 的"还缺什么信息"。
- **P-CONTRADICTION = 0 的解释**：无任何一项出现"证伪链声称覆盖全部路径且每路无 bug，同时又构造出反例"；两项 UNKNOWN 均为**反手失败 + 正手未成**（不是两边都成功）。粗筛 16 项中 01/02/05 在写证伪链过程中直接发现反例路径，按协议判"反手失败 → 直接进正手"。
- 等级分布：P1×1（01）、P2×6（02、04、05、06、08、12）、P3×7（07、09、10、13、14、15、16）、UNKNOWN×2。合计 16 个裁决单元。
- [REGRESSION]：2 项（01 由 `cmd_skybox_set` 改动引入、旧版 `ed._skybox = cube`；14 由 run() 尾部删 `_glfw_shutdown` 引入）。
- 自审（A6）：8 条硬要求全满足；每条证伪链第 3 段有"路径枚举表"；每条证真链第 7 段是可直接跑的命令（已跑、输出已贴）；跳过 8 项均有四类理由之一 + 出处；无不可审计措辞。

---

## 4. 修复建议排序（只给方向，不含代码）

| 序 | 项 | 方向 |
|---|---|---|
| 1 | P-02-01（P1/REG） | 让"生效天空盒"回落链**包含** `_scene_skybox`（相机级 → 场景级生效值 → None），或让命令层写 `_scene_skybox` 后同步写 `_skybox` —— **二选一，别两边都改**；同时让 `cmd_skybox_set` 返回真实生效值而非 `eff`。回归断言：`skybox_set` 后 `effective_skybox() is 新 cube`。 |
| 2 | P-02-02（P2） | VK 相机级 skybox 配对改成"相机 dict 与相机对象一一对齐"（如 `build_cameras` 返回 `[(cam, d)]`，或先过滤 dict 再遍历）；并统一 GL 侧同数据的 AttributeError 错误模型。 |
| 3 | P-02-08 + 11（P2/UNK） | `bind`/`draw` 失败分支把 `_sky_prog` 失效化（置 None + 计一次"已重试"），给播放器一个重试上限；`reset_sky_state` 作为唯一复位口保持幂等。 |
| 4 | P-02-06（P2） | `from_solid` 对齐契约：0-1 区间（且非整值浮点）一律 ValueError；`cmd_set_env` 复用 `sceneio.parse_color`。 |
| 5 | P-02-12（P2） | 打包路径把游戏根目录（LOOM_GAME_DIR / pack 解包根）作为 base_dir 传下去。 |
| 6 | P-02-04 + 05（P2） | 统一"无效 cubemap"处置：建议两端"拒绝 + 一次可见告警"，删掉 GL 的 1x1 白兜底（它会把配置错误伪装成白天空），VK 的缺面/尺寸不一致改成显式校验、不脏写入。 |
| 7 | P-02-03（UNK） | 缓存键去掉 `id()`，换"guid+内容指纹"或渲染端自增 generation。 |
| 8 | P-02-07/09/10/13/14/15/16（P3） | 清理：editor 清屏引用常量；删 `_sky_fail_logged` 或真正消费它；`cube is None` 分支补一次释放/丢弃；`run()` 恢复 `_glfw_shutdown()`；三文件补行尾换行；统一入口"门"；tint 非法值回落 (1,1,1)。 |

---

## 5. 需要人类裁决的封闭问题

**Q1（P-02-01 修复落点）**：`skybox_set` 之后"生效天空盒"为 None，根因横跨命令层（`_skybox=None`）与引擎（`effective_skybox` 不认 `_scene_skybox`）。请裁决改哪一侧：
- A：引擎侧 —— 回落链加入 `_scene_skybox`（渲染端自洽，命令层不必同步两字段）；
- B：命令层 —— 写 `_scene_skybox` 后同时写 `_skybox`（与 `_new_scene`/`_load_scene` 现有写法一致）；
- C：两侧同时做（双保险，多一条不变量要维护）。
代价：A 需明确"`_scene_skybox` 与 `_skybox` 谁是真源"；B 保留两字段同步负担；C 最稳但最啰嗦。

**Q2（Q2=A 清屏底色的可见性变化可否接受）**：GL 播放器裸清屏像素由 (13,13,25) 变 (25,31,41)（亮度约 ×1.9，实测 e/B1、e/B2）。请裁决：
- A：接受（三端统一的价值 > 播放器底色变化）；
- B：接受统一，但 `skybox_clear` 之后的裸背景需要明确的视觉意图（如"无天空盒"提示）；
- C：GL 播放器单独保留旧底色（放弃三端统一）。

**Q3（P-02-04/05 的"无效 cubemap"错误模型）**：缺面/全无面/各面尺寸不一致时，双后端统一为哪一种？
- A：**拒绝 + 一次可见告警 + 不画**（GL 去掉 1x1 白兜底）；
- B：回退"默认蓝天盒"（与场景级解析失败的回退一致）；
- C：保持现状各写各的（GL 白兜底 / VK 静默不画）。
代价：A 让配置错误立刻可见但会"黑一块"；B 视觉最稳但可能掩盖数据问题；C 继续双端分叉。

---

*生成方式：粗筛 → 每项双向推演（先证伪后证真）→ 探针闭环（8 个探针脚本，全在 `Loom/tests/_tmp/scan_beta5_02_*`，gitignore 覆盖）→ 四象限裁决。所有结论均附"文件:行号 + 逻辑链 + 可执行命令 + 实测输出"。等级自评：**A6**（8 段式链 + 探针机制 + 白盒契约引用 + 跳过留痕；A7 要求的"自我合理化失败模式清单作为机器审计项"目前是手工过一遍）。*
