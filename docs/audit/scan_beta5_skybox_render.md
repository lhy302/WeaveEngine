# 天空盒渲染链扫描报告（beta5 · 子代理 · 只读）

> 判定基准 = 被审对象自身白盒契约（源码注释 / 文档 / 已有回归测试）。禁止引用外部标准。
> 所有结论 = 文件:行号 + 逻辑链 + 可执行命令 + 实测输出。探针一律落在 `Loom/tests/_tmp/`（`Loom/.gitignore:20 tests/_tmp/*`，git 已确认忽略）。

## 0. 范围与方法

| 文件 | 行数 | 本轮读到的区域 |
|---|---|---|
| Loom/loom_render.py | 930 | 全文件：`_draw_skybox`(39-117)、`_clear_main_fbo`(276-288)、`_screen_fb`(290-299)、`render`(681-839)、`run`(887-929) |
| Loom/editor.py | ~2600 | `render`(2172-2313)、`_new_scene`(1156-1197) |
| Loom/engine.py | — | 215-364（`_skybox`/`_sky_*/`_skybox_tint` 初值）、`_external_ctx` |
| Loom/loom_shaders.py | 442 | 411-442（`_SKY_VERT`/`_SKY_FRAG`） |
| Loom/loom_cubemap.py | 195 | 全文件（`from_solid` 80-122、`ensure_gl` 141-173） |
| Loom/vk_renderer.py | ~2000+ | 432-461(`_SKY_WGSL`)、945-1018(`_ensure_sky`/`_draw_sky`)、1950-1992(主 pass) |
| Loom/vk_player.py | — | 520-605（`sky=` 接线） |
| Loom/scene_driver.py | — | 560-568（skybox 加载）、890-912（`render_pose`） |
| Loom/sceneio.py | — | 543-578（`_emit_skybox`/`_apply_skybox`）、1149-1177、596-621 |
| Loom/agent_commands.py | — | 967-1027（`skybox_set/clear/get`） |
| Loom/loom_scene_entities.py | — | 151-175（`CameraState.skybox` 契约） |
| Loom/loom_mcp.py | — | 259-275（`loom_skybox_set` schema） |

跑过的命令（全部在仓库根、`$env:PYTHONIOENCODING='utf-8'`）：

```
python Loom\tests\_tmp\skybox_gl_probe.py        # 编辑器路径：清屏/纯色/相机级
python Loom\tests\_tmp\skybox_occlusion_probe.py # 天空 vs 几何 遮挡 4 组
python Loom\tests\_tmp\skybox_paths_probe.py     # 播放器路径 / 相机覆盖 / EAI 输入 / from_solid 边界
python Loom\tests\_tmp\skybox_vk_probe.py       # VK 离屏（真实设备 GTX 1050 Ti, wgpu 0.32）
python Loom\tests\_tmp\skybox_orient_probe.py   # 6 面异色 cubemap 的朝向/反投影 + tint + 每帧调用计数
python Loom\tests\_tmp\skybox_ab_probe.py       # GL 播放器 vs VK 播放器 逐像素 A/B
python Loom\tests\_tmp\skybox_swallow_probe.py  # 异常吞没 + _sky_prog=False 哨兵
```

环境：Python 3.12.10 / moderngl 5.12.0 / wgpu 0.32.0 / NVIDIA GTX 1050 Ti。
本轮回写自查：`git status --porcelain` 仅 `?? tools/lint_except_dist/`、`?? tools/loom_lint_except.py`（本轮之前既存未跟踪项），**无任何受跟踪文件被改动**。

## 1. 粗筛清单（含跳过项留痕）

| ID | 位置 | 标签 | 初步方向 |
|---|---|---|---|
| P-01 | loom_render.py:780 vs vk_renderer.py:1960 vs editor.py:2239 | SEM-MISMATCH | 三个"默认背景"清屏色不同：GL 播放器 (0.05,0.05,0.1)，编辑器/VK (0.10,0.12,0.16) |
| P-02 | loom_scene_entities.py:172-175 / sceneio.py:596,620 ↔ loom_render.py:39-117 | AUDIT-DOCIMPL / SEM-MISMATCH | 注释承诺"相机级 skybox 非 None 时优先于场景级"，但 `_draw_skybox` 只读 `self._skybox`，全仓无 `cam.skybox` 消费者 |
| P-03 | agent_commands.py:991 | IFACE-PRECOND / SEM-SILENT | `tuple(int(x) for x in solid)` 在 `Cubemap.from_solid` 的 0-1 浮点判定之前截断 → 浮点纯色变全黑（Bug A 同类残留） |
| P-04 | loom_render.py:55-56,81-84 + sceneio.py:1173-1177 | AUDIT-DEADCODE / SEM-SILENT | `_sky_prog=False` 永久哨兵在换场景时**不重置**，且命中路径零日志 |
| P-05 | editor.py:2280-2284 vs loom_render.py:814-815 + 905 | AUDIT-ASYMMETRY | 同一故障编辑器吞掉（只 print），播放器外泄并终止整个 `run()` 循环 |
| P-06 | vk_renderer.py:1010 vs engine.py:310 | AUDIT-ASYMMETRY / IFACE | VK 读 `self.skybox_tint`，GL 读 `self._skybox_tint`；前者全仓无赋值点 |
| P-07 | loom_cubemap.py:100-112 | SEM-OVERFIT / SEM-DEFAULT | "全部通道 ≤1.0 就乘 255"的启发式对整数小值 (0,0,1,1) 静默放大成 (0,0,255,255) |
| P-08 | loom_shaders.py:418-442 / vk_renderer.py:444-460 | （待判） | 反投影矩阵方向/行列主序、cubemap swizzle、gamma 是否与 VP 约定一致 |
| P-09 | loom_render.py:104-117 / vk_renderer.py:964-972 | （待判） | depth bias / cull / depth_compare 是否把天空整块挡掉或反过来盖住几何 |
| P-10 | editor.py:2278-2282 | （待判） | "Bug B 修复"是否真的每帧执行（包在 try 里，异常被吞） |
| P-11 | 全仓文档/代码 | DESIGN-GAP | 是否存在"默认天空盒 = 蓝色"的白盒契约 |
| P-12 | 交付场景资产 | （待判） | 用户看到的"偏黑"是否等于"场景根本没配天空盒" |
| P-13 | Qt 宿主 widget FBO | （待判，UNKNOWN） | 编辑器天空依赖 depth==1.0；宿主 FBO 无深度附件时天空会盖满全屏 |

### 跳过登记（每条必须有可审计出处）

- **SKIP-01** `loom_render.py:208 ctx.clear(0.0,0.0,0.0,0.0)`：World Canvas 离屏纹理清屏。跳过理由＝**白盒契约明确声明**：同行注释 "透明底：透明处不遮挡场景"，且它不是主渲染目标（`_clear_main_fbo` 才是）。不在天空链上。
- **SKIP-02** `vk_renderer.py:1354,1538 clear_value (0,0,0,0)`：离屏 UI/world-quad 纹理。理由同上（`vk_renderer.py:645` 注释 "透明底, 与 GL clear(0,0,0,0) 同"）。
- **SKIP-03** `vk_renderer.py:1887,1930 clear_value (1.0,0.0,0.0,1.0)`：阴影 pass 颜色附件。跳过理由＝**工具/框架自身声明 + 已有轮次裁定**：阴影深度编码进颜色附件属于 scan_04 已覆盖区域，不在天空链。
- **SKIP-04** `sceneio.py:543-578` 内存态 cubemap 无法序列化 → `None`：**已有回归测试 + 上一轮已裁定**，见 `docs/audit/scan_02_scene.md:674-695`（P-11 · P-DISPROVED），本轮不重复推演。
- **SKIP-05** `loom_render.py:290-299 _screen_fb`：纯目标选择，无颜色/深度语义。理由＝**语言/API 规范保证**（moderngl `detect_framebuffer` 语义）+ 本轮探针在两种模式下实测均正确出图。

## 2. 逐项裁决

### P-01 · PROVED · 三个"默认背景"清屏色不一致（P1）

**1) 位置**：`Loom/loom_render.py:780`（GL 播放器）、`Loom/editor.py:2239`（编辑器）、`Loom/vk_renderer.py:1960`（VK 播放器）。

**2) 契约/预期**：`vk_renderer.py:1964-1966` "2026-11-06 天空盒… sky=None 时保持原清屏色"，而 `loom_render.py:780`/`editor.py:2239` 的注释（loom_render.py:277 "pygame 与 Qt 外部模式同一路径"）都把清屏当作"同一路径"。同一份场景、同一个后端无关的默认背景，应当是同一个颜色。

**3) 路径枚举**（清屏色写入点全仓穷尽，`clear_color|glClearColor|_clear_main_fbo|clear_value` grep 345 命中中属于主渲染目标的仅 4 处）：
- 路径 1 `loom_render.py:780 render()` → GL 播放器/打包版 GL → (0.05,0.05,0.1)
- 路径 2 `editor.py:2239 render()` → Qt 编辑器视口 → (0.10,0.12,0.16)
- 路径 3 `vk_renderer.py:1960` 主 pass 颜色附件 → VK 播放器 → (0.10,0.12,0.16)
- 路径 4 无天空盒时三者都**只**画清屏色（`_draw_skybox` 首行 51-52 直接 return；VK 1967 `if sky is not None`）→ 背景 = 清屏色。

**4) 预期**（同一后端语义）：同场景同无天空盒 → 同一像素。**实际**：GL 播放器 (13,13,25)，编辑器/VK (25,31,41)。

**5) 差异**：GL 播放器与另两端差 (12,18,16)/通道，且 A/B 里 24519/38400 像素（＝被天空覆盖的那块）恒差。

**6) 触发条件**：任何**没有 skybox 段**的场景在两后端分别播放（这正是仓库里全部 15 个交付场景的现状）。

**7) 验证**：`python Loom\tests\_tmp\skybox_ab_probe.py`（GL 播放器 vs VK 播放器，同场景）
```
GL  无天空盒 (12,12) 角像素 = (13, 13, 25)
VK  无天空盒 (12,12) 角像素 = (25, 31, 41)
GL vs VK (无天空盒): MAE=9.791  MAX=18  差异>2 的像素=24519/38400
```

**8) 影响与等级**：**P1**（双后端同一场景可见背景不同，用户侧表现为"编辑器是灰蓝、游戏里更黑"）。

---

### P-02 · PROVED · 相机级天空盒契约无实现（P1）

**1) 位置**：契约 `Loom/loom_scene_entities.py:172-175`（"非 None 时优先于场景级 engine._skybox"）、`Loom/sceneio.py:596,620`（emit/apply 也写它）；渲染端 `Loom/loom_render.py:39-117,813-815`、`Loom/vk_renderer.py:1967-1972`。

**2) 契约/预期**：仅设 `CameraState.skybox`（engine._skybox=None）时应画出相机天空盒；场景级 + 相机级同时存在时，相机级胜出。

**3) 路径枚举**（渲染取天空盒的全部读取点，`skybox` grep 225 命中中属于"渲染读"的穷尽）：
- 路径 1 `loom_render.py:51`（`if self._skybox is None: return`）→ 只读引擎级
- 路径 2 `loom_render.py:98-99`（`self._skybox.ensure_gl/use`）→ 只读引擎级
- 路径 3 `loom_render.py:814`（`if self._skybox is not None` 门控）→ 只读引擎级
- 路径 4 `vk_renderer.py:1967`（`sky` 形参）← `vk_player.py:583` `getattr(driver,'skybox',None)` ← `scene_driver.py:566`（场景级）
- 路径 5 相机级：`CameraState.skybox` 仅在 `sceneio.py:597`（emit）、`621`（apply）、`undo/序列化` 出现，**全仓无任何绘制侧读取**（`grep -n "skybox" ` 确认无 `camera.skybox`/`.skybox` 消费者）。

**4) 预期**：B1 绿、B2 绿。**实际**：B1 = 清屏色（完全没画），B2 = 场景红（相机绿被忽略）。

**5) 差异**：整条相机覆盖语义"只存不画"。

**6) 触发条件**：任何只给相机配天空盒、或相机想覆盖场景天空盒的场景。

**7) 验证**：`python Loom\tests\_tmp\skybox_paths_probe.py`
```
B1 仅相机 skybox=绿      _skybox=None  corner(4,4)=(13, 13, 25)   # 应为绿
B2 场景=红 + 相机=绿     _skybox=Cubemap(...) corner(4,4)=(255, 0, 0) # 应为绿
```

**8) 影响与等级**：**P1**（序列化/契约齐备、功能缺失；属"注释承诺 ≠ 代码行为"的 AUDIT-DOCIMPL）。

---

### P-03 · PROVED · EAI 纯色天空盒浮点输入静默变全黑（P1，Bug A 同类残留）

**1) 位置**：`Loom/agent_commands.py:985-996`（`cmd_skybox_set`），第 991 行 `rgba = tuple(int(x) for x in solid)`；对照契约 `Loom/loom_cubemap.py:83-107`（"tuple 路径：若所有通道都 ≤ 1.0 视为 0-1 浮点，也乘 255"）。

**2) 契约/预期**：`from_solid` 文档明确接受 0-1 浮点；命令层 docstring（agent_commands.py:968）写 `[r,g,b,a]` 未限 0-255；MCP schema（loom_mcp.py:264-269）只写 "0-255" 但 `loom_skybox_set` 与 `skybox_set` 走同一实现。

**3) 路径枚举**：
- 路径 1 字符串 "#RRGGBB" → `from_solid(str)` → 正确（实测 (58,123,213,255)）
- 路径 2 整数 [58,123,213,255] → `int()` 无损 → 正确
- 路径 3 **0-1 浮点 [0.227,0.482,0.835,1.0]** → 第 991 行 `int()` 先截断成 (0,0,0,1) → `from_solid` 再按 ≤1 判定乘 255 → (0,0,0,255) **全黑**
- 路径 4 直接调 `Cubemap.from_solid([0.227,...])`（绕过命令）→ 正确（实测 (58,123,213,255)）

**4) 预期**：(58,123,213,255)。**实际**：`(0,0,0,255)`，且命令返回 `{'ok': True}` —— 无声失败。
**5) 差异**：颜色信息在接口层（P-03 前置换算）被清零，下游契约承诺的兜底被前置步骤破坏（IFACE-PRECOND）。
**6) 触发条件**：Agent/脚本用 0-1 浮点数组设置天空盒颜色（这类"规范化颜色"输入是常见的模型产出格式）。

**7) 验证**：`python Loom\tests\_tmp\skybox_paths_probe.py`
```
C) EAI skybox_set:
  hex "#3a7bd5"                      -> ok  _solid_color=(58, 123, 213, 255)
  int255 [58,123,213,255]            -> ok  _solid_color=(58, 123, 213, 255)
  float01 [0.227,0.482,0.835,1.0]    -> ok  _solid_color=(0, 0, 0, 255)     <== 全黑
  float01 (0.2,0.4,0.6,1.0)          -> ok  _solid_color=(0, 0, 0, 255)     <== 全黑
```

**8) 影响与等级**：**P1**（用户/Agent 觉得"我设了颜色，天空还是黑的"，且无任何错误提示）。

---

### P-04 · PROVED · `_sky_prog=False` 永久哨兵跨场景不复位（P1，N1 同类：修复存在但永不执行）

**1) 位置**：`Loom/loom_render.py:53-56`（哨兵判定）、`81-84`（写哨兵）；复位点仅 `Loom/agent_commands.py:1002,1012`；场景加载 `Loom/sceneio.py:1173-1177` 不触碰。

**2) 契约/预期**：`loom_render.py:53-54` 注释自称"编译失败用 False 哨兵（避免每帧重试刷屏）；**同时不 nuke _skybox（保留数据，用户改 shader 后可 _sky_prog=None 恢复）**" —— 即存在一条"恢复"路径；而"换场景"是本项目里最常规的恢复动作，且 `sceneio.scene_from_dict` 会重置 `_skybox`。

**3) 路径枚举**（`_sky_prog` 的全部赋值点，grep 穷尽 5 处）：
- 引擎新建 → None（engine.py:306）
- 编译失败 → False（loom_render.py:83）
- EAI skybox_set/clear → None（agent_commands.py:1002,1012）
- **场景加载 → 无赋值**（sceneio.py:1173-1177 只写 `engine._skybox`）
→ 路径：一旦某帧编译失败（驱动差异/换 ctx/首帧 GL 未就绪），此后**所有场景**的 `_draw_skybox` 在第 55-56 行直接 return，且不再打印任何信息（打印只在设置哨兵那一次）。

**4) 预期**：换场景后应重新尝试（或至少报错）。**实际**：换带天空盒的场景后画面仍是清屏色。
**5) 差异**：天空盒"数据在、永不绘制、零日志"，正是人类怀疑的"修复代码存在但从未执行"形态。
**6) 触发条件**：`ctx.program(...)` 任一次失败（例如宿主重建 GL 上下文：`_sky_prog` 属旧 ctx 的 program，新 ctx 上渲染会抛异常 → 编辑器吞掉 → 用户看到"天空没了"）。

**7) 验证**：`python Loom\tests\_tmp\skybox_swallow_probe.py`
```
C) _sky_prog=False 哨兵是否会被"换场景"重置
  换场景后 _sky_prog = False  _skybox = Cubemap(立方体贴图 4)
  画面中心 = (25, 31, 41)   # 期望 (58,123,213)
```

**8) 影响与等级**：**P1**（不可恢复 + 静默，用户侧无法自救，只能重启进程）。

---

### P-05 · PROVED · 天空盒异常处理在编辑器/播放器不对称（P2）

**1) 位置**：`Loom/editor.py:2280-2284`（`try/except` + print）、`Loom/loom_render.py:813-815`（无 try）、`Loom/loom_render.py:897-909`（`run()` 循环无 try）。

**2) 契约/预期**：`editor.py:2278-2279` 注释把该调用描述为"Bug B 修复"，意在两端都看得到天空；同一子系统同一故障，两端后果应同量级。

**3) 路径枚举**：
- 路径 1 编辑器：异常 → 第 2283 行吞掉 → 只 print 一行 → 帧继续（后续 `view.draw`/`_update_gizmo` 照常）
- 路径 2 GL 播放器：异常 → 第 815 行外泄 → 穿透 `run()` 第 905 行（无保护）→ 整个渲染循环终止
- 路径 3 VK：`vk_renderer.py:1967-1972` 有 try + print（与编辑器同类）

**4) 预期**：两端要么都降级、要么都报错。**实际**：编辑器静默降级，GL 播放器进程级失败。
**5) 差异**：三端三套策略（吞 / 崩 / 吞）。
**6) 触发条件**：uniform 名缺失（`loom_render.py:95` 的 `u_skybox_tint` **没有** try 保护，与 78-80 的 `u_skybox` 不对称）、ctx 失效、cubemap 绑定失败等。

**7) 验证**：`python Loom\tests\_tmp\skybox_swallow_probe.py`
```
A) 编辑器: [渲染] 天空盒绘制失败: RuntimeError('PROBE_FAULT') → 未抛异常, 中心=(25,31,41)
B) 播放器: player.render 抛出 'RuntimeError' → run() 无 try/except => 渲染循环终止
```

**8) 影响与等级**：**P2**（异常路径；但它是"修复可能从未生效"之所以不可见的结构性原因之一）。

---

### P-06 · PROVED · VK 天空盒 tint 未接线且与 GL 命名分叉（P3）

**1) 位置**：`Loom/vk_renderer.py:1010` `tint = getattr(self,'skybox_tint',(1.0,1.0,1.0))`；GL 侧 `Loom/engine.py:310` `self._skybox_tint` + `loom_render.py:95`。
**2) 契约/预期**：`vk_renderer.py:944` "天空盒（对齐 GL A1+B1）"；两侧对同一语义（颜色乘子）应可对照设置。
**3) 路径枚举**：`skybox_tint` 全仓 grep 仅 1 处读（vk_renderer.py:1010）、**0 处赋值**；`_skybox_tint` 仅 engine.py:310 定义、仅 loom_render.py:95 读。→ VK 端该属性恒为默认 (1,1,1)。
**4) 预期**：设 tint=(1,0,0) 天空应偏红。**实际**：VK 无论设 `_skybox_tint` 还是 `skybox_tint`（在 driver 上）都仍是白色；GL 设 `_skybox_tint` 立即变红。
**5) 差异**：GL 生效、VK 永久失效，且属性名不一致（即便将来在校验方设置也会分叉）。
**6) 触发条件**：任何用 tint 做调试/风格的调用（当前无调用者，属潜伏缺陷）。
**7) 验证**：`python Loom\tests\_tmp\skybox_orient_probe.py`
```
GL _skybox_tint=(1,0,0) -> center=(255, 0, 0)          # 生效
VK 仅设 _skybox_tint=(1,0,0) -> center=(255, 255, 255)  # 无效
VK 改设 skybox_tint=(1,0,0)  -> center=(255, 255, 255)  # 无效(设在 driver, 渲染期读 renderer)
```
**8) 影响与等级**：**P3**（无当前调用者；但属双后端接口分叉）。

---

### P-07 · PROVED · `from_solid` 的 0-1 启发式会静默放大整数小值（P3）

**1) 位置**：`Loom/loom_cubemap.py:100-112`。
**2) 契约/预期**：同文件 81 行 docstring 声明支持 "color=(r,g,b,a) 0-255 或 '#RRGGBB'" 与 83-87 的 0-1 浮点；两种解释对 (0,0,1,1) 这类输入**互斥**，代码选择了"浮点优先"而无任何提示。
**3) 路径枚举**：所有通道 ≤1.0 → ×255（第 105-108 行）；任一通道 >1.0 → 保留整数；字符串 → 独立分支。
**4) 预期**：调用者若按 0-255 传 (0,0,1,1)（近乎黑的深蓝）应得到近乎黑。**实际**：得到 (0,0,255,255) 纯蓝。
**5) 差异**：颜色被放大 255 倍，方向明确（多做了什么）。
**6) 触发条件**：0-255 语义下所有通道都 ≤1 的颜色。
**7) 验证**：`python Loom\tests\_tmp\skybox_paths_probe.py` 的 D 段
```
  (0, 0, 1, 1)      -> _solid_color=(0, 0, 255, 255)
  (1, 1, 1, 1)      -> _solid_color=(255, 255, 255, 255)
  (255, 255, 255)   -> _solid_color=(255, 255, 255, 255)
  [17, 34, 51, 255] -> _solid_color=(17, 34, 51, 255)
```
**8) 影响与等级**：**P3**（歧义输入；有明确文档但无法区分意图，属"设计上必须由人类裁决的输入语义"）。

---

### P-08 · DISPROVED · "反投影/朝向/swizzle/gamma 有错"

**1) 位置**：`loom_shaders.py:418-442`、`vk_renderer.py:444-460`。
**2) 契约/预期**：`loom_shaders.py:415-416` "反投影数学（与 engine._ray_from_screen 逐位一致: 行向量约定 clip @ inv(VP) = world）"；matlib.py:6-7 行向量约定、mat4_view_yaw_pitch 前方 ez=(sinYaw·cosPitch, sinPitch, cosYaw·cosPitch)（matlib.py:159-161）。
**3) 路径枚举 + 最小复现**：把 cubemap 六个面涂成六种可辨识色（px红/nx绿/py蓝/ny黄/pz白/nz品红），令相机位于原点并分别朝 ±X/±Y/±Z，读回屏幕中心像素；两后端各跑一遍：
```
GL yaw=0 pitch=0   期望 +Z -> center=(255,255,255) pz白
GL yaw=90 pitch=0  期望 +X -> center=(255,  0,  0) px红
GL yaw=180 pitch=0 期望 -Z -> center=(255,  0,255) nz品红
GL yaw=0 pitch=+80  期望 +Y -> center=(  0,  0,255) py蓝
GL yaw=0 pitch=-80  期望 -Y -> center=(255,255,  0) ny黄
VK 同上 5 行结果逐位相同
```
**4) 预期 vs 实际**：5/5 位姿、2/2 后端全部命中预期面，无上下/左右/前后翻转，无 BGR 交换。gamma：纯色 (58,123,213) 输入输出**逐位相等**（`skybox_gl_probe.py` S2 = MATCH；(58,123,213) 未出现 0-1 gamma 变换），VK 亦然（`vk_player.py:307-328` 显式请求非 srgb 交换链，故两端同为线性 8bit）。
**7) 验证**：`python Loom\tests\_tmp\skybox_orient_probe.py`（上表即其输出）。
**8) 判定**：**DISPROVED**。排除原因：5 条朝向路径 × 2 后端全覆盖，含 pitch ±80° 的极角，若存在 swizzle/转置错必在 +X/±Y 处暴露。
（补充说明：已有冒烟 `tests/_tmp/smoke_skybox_vao.py` 用 identity 矩阵测天空，**无法**覆盖本项——本轮新增的六面异色探针补上了这个覆盖缺口。）

---

### P-09 · DISPROVED · "depth/cull 把天空挡掉或天空盖住几何"

**1) 位置**：`loom_render.py:104-117`（`depth_mask=False`、`depth_func='<='`、`disable(CULL_FACE)`）、`loom_render.py:47-48,276-288`（深度每帧清 1.0）、`vk_renderer.py:967-970`（`cull_mode:'none'`、`depth_write_enabled:False`、`depth_compare:'always'`）。
**2) 契约/预期**：注释 `loom_render.py:44-48` "天空盒 quad 在 z=1.0（远平面），depth_func='<=' 允许等值通过；几何覆盖的像素 depth<1.0 无法通过 → 跳过（无 overdraw）"。
**3) 路径枚举**（4 组交叉，两后端）：
- 路径 1 无天空盒 + 立方体 → 中心=几何(111,111,111)，角=清屏(25,31,41)
- 路径 2 红天空盒 + 立方体 → 中心=(111,111,111)（几何未被天空覆盖），角=(255,0,0)（天空生效）
- 路径 3 红天空盒 + 立方体 + 禁用 `_draw_skybox` → 角回落清屏色（证明前一条的红确实来自天空而非别处）
- 路径 4 红天空盒 + 无几何 → 整屏 (255,0,0)（证明天空覆盖全屏，不会被"整块挡掉"）
VK 侧 V1/V2 同样得到 center=(111,111,111)、corner=(58,123,213)。
**4) 预期 vs 实际**：与注释逐条一致，无偏差。
**7) 验证**：`python Loom\tests\_tmp\skybox_occlusion_probe.py`、`python Loom\tests\_tmp\skybox_vk_probe.py`
```
A 无天空盒 + 立方体   models=1 center=(111,111,111) corner=(25,31,41)
B 红天空盒 + 立方体   models=1 center=(111,111,111) corner=(255,0,0)
C 红天空+立方体+禁天空 models=1 center=(111,111,111) corner=(25,31,41)
D 红天空盒 + 无几何   models=0 center=(255,0,0)     corner=(255,0,0)
V1 无 skybox + 立方体 center=(111,111,111) corner=(25,31,41)
V2 纯色 skybox + 立方体 center=(111,111,111) corner=(58,123,213)
```
**8) 判定**：**DISPROVED**。

---

### P-10 · DISPROVED · "编辑器 Bug B 修复没有每帧执行"

**1) 位置**：`editor.py:2278-2284`。
**2) 契约/预期**：注释"编辑器主 pass 之前没调 _draw_skybox（只有 PlayerApp 的 GLEngine.render 调了），所以编辑器里设了天空盒也永远看不到"→ 修复后应每帧执行。
**3) 路径枚举**：编辑器 render 只有这一处调用天空；门控条件 `getattr(self,'_skybox',None) is not None`；异常被 2283 吞。
**4) 实际**：包装计数探针显示 10 次 render → `_draw_skybox` 命中 10 次（100%）；像素侧 S2 中心 (58,123,213) 与期望逐位相等。
**5) 差异**：无（修复确实每帧执行且生效）。
**7) 验证**：`python Loom\tests\_tmp\skybox_orient_probe.py`
```
编辑器 _draw_skybox 实际调用次数 = 10 (2 帧 x 5 位姿 = 10 次渲染)
```
**8) 判定**：**DISPROVED**（但见 P-04/P-05：它"执行"的前提是 `_sky_prog` 不是 False，且异常会被吞）。

---

### P-11 · DISPROVED · "存在『默认天空盒=蓝色』白盒契约"

**证据链（条款反向）**：
- `editor.py:1180-1181`：**"2026-10-19 Fix 4: 天空盒不随场景继承（默认无天空盒 = 清屏深色底）" → `self._skybox = None`**（这是唯一一处直写"默认"的契约条款）
- `engine.py:309`：`self._skybox = None  # 场景级默认天空盒（Cubemap 实例或 None）`
- `sceneio.py:1173`："场景级默认天空盒（旧文件无此键 -> None）"
- 文档侧：全仓 md 里 `skybox|天空盒` 35 处，`默认天空|蓝色` **0 处**；`docs/design/*` 只写"天空盒背景 pass / 资产槽"，无默认颜色要求。
- 资产侧：15 个交付场景（`Loom/Projects/*`、`封装测试材料/跳台试炼场景_明文.json`）**全部无 `skybox` 键**（逐文件 Select-String 实测）。

**判定**：**DISPROVED**（"默认蓝色"在本项目白盒层不存在）。人类看到的"偏黑"是**设计缺口 + 默认值选择**，不是实现 bug：
> 若判定基准是"新建/交付场景应有蓝色天空"，则缺的是**契约**（DESIGN-GAP），实现忠于现行契约。

---

### P-12 · UNKNOWN · 用户实际运行的那份场景是否含 skybox 段

**已尝试**：枚举仓库内全部 15 个场景 → 全部无 `skybox` 键；检查保存路径 `sceneio.py:1156`（`_emit_skybox(None)` → 写 `"skybox": null`）；检查设置面板/新建场景默认（`editor.py:1156-1197`，无天空盒）。
**仍缺的信息**：用户点击"运行/播放"时打开的具体场景文件路径（或编辑器里是否曾执行过 `skybox_set`）。
**拿到后即可判定**：该文件 `"skybox"` 为 null / 缺失 → 归因"没配"（P-11 设计缺口）；为 `solid_color` 且值为全 0 → 归因 P-03；相机段才有 → 归因 P-02。
**建议下一步探针**：对该文件跑 `python -c "import json;d=json.load(open(P,encoding='utf-8'));print(d.get('skybox'), [c.get('skybox') for c in d.get('cameras',[])])"`。

---

### P-13 · UNKNOWN · Qt 宿主 widget FBO 是否有深度附件（天空可能盖满全屏）

**为什么可疑**：GL 天空的"不遮挡几何"完全依赖 depth==1.0 + `depth_func='<='`（loom_render.py:44-48, 111）。编辑器渲染目标是宿主缓存的 widget FBO（`_screen_fb` 290-299），若该 FBO 无深度附件，`DEPTH_TEST` 恒通过 → 天空会把整帧涂成纯色。
**已尝试**：离屏探针自建了 depth renderbuffer（`ab_gl_vk.py:54` 的注释也是这个理由），因此**探针无法代表 Qt 宿主**；本轮不能启动 Qt 长窗口（协议 §0.5）。
**仍缺**：Qt `QOpenGLWidget` 的 `defaultFramebufferObject` 是否带 `GL_DEPTH24_STENCIL8`（glGetFramebufferAttachmentParameteriv 一次即可）。
**落地探针**：在 `qt_view.paintGL` 内临时打印 `ctx.detect_framebuffer().depth_attachment` 与一次 `ctx.fbo.depth_mask`；有附件则该点关闭。

## 3. 统计

| 判定 | 数量 | 明细 |
|---|---|---|
| P-PROVED | 7 | P-01(P1) P-02(P1) P-03(P1) P-04(P1) P-05(P2) P-06(P3) P-07(P3) |
| P-DISPROVED | 4 | P-08 朝向/swizzle/gamma、P-09 depth/cull、P-10 编辑器每帧执行、P-11 默认蓝契约 |
| P-UNKNOWN | 2 | P-12 用户实际场景文件、P-13 Qt FBO 深度附件 |
| P-CONTRADICTION | 0 | —— |
| 跳过登记 | 5 | SKIP-01..05（均附可审计出处） |

**P-UNKNOWN 不为 0 的说明**：两项都是"判据在仓库外"（用户手里的场景文件 / Qt 宿主运行时 FBO 属性），仓库内证据已穷尽（15/15 场景无 skybox、探针走自建 FBO），故如实标 UNKNOWN 而非硬判。
**P-CONTRADICTION = 0 的说明**：P-08/P-09/P-10 的证伪链在写成时即被探针直接正面推翻（预期面 5/5 命中、4/4 遮挡组一致、10/10 调用），没有出现"证伪与证真同时成立"的情形；证真链无从成立，故无矛盾对。
**信噪比自检**：7 PROVED / 4 DISPROVED —— 双向都有产出，非"全 PROVED"或"全 DISPROVED"的异常形态。

## 4. 修复建议排序（只给方向，不含代码，本轮不改任何文件）

| 优先级 | 项 | 方向 |
|---|---|---|
| P0→无 | —— | 本轮未发现崩溃/安全问题（P-05 播放器侧异常外泄属"故障后行为"，触发需先有异常） |
| P1 | P-04 | 换场景/换 ctx 时必须复位 `_sky_prog`（含"False 只在同 ctx 内有效"的判据），且天空被跳过时**每场景报一次**日志 |
| P1 | P-03 | 命令层把 0-1 浮点判定交给 `from_solid`（不要先 `int()`），或显式拒绝 <1 的浮点并报错 |
| P1 | P-02 | 要么实现相机级 skybox（渲染层读 active camera），要么从序列化/契约里删掉该字段，禁止"存而不用" |
| P1 | P-01 | 三处清屏色收敛到唯一出处（建议由引擎级常量提供，含"是否随场景保存"的人类裁决） |
| P2 | P-05 | GL 播放器侧天空调用加与编辑器同级的降级处理（或统一三端策略） |
| P3 | P-06 | 统一 tint 属性名并接线（否则删掉） |
| P3 | P-07 | 给 `from_solid` 的 0-1/0-255 歧义定一条显式规则（人类裁决项 H-2） |

## 5. 需要人类裁决的封闭问题

**H-1（P-11/P-12 归因）**：新建场景与打包场景的"默认背景"取哪一条？
- A. 保持现状（无天空盒 = 清屏深色底，现行代码即此），把"蓝天空"降级为文档示例 → 代价：用户第一眼仍觉得"黑"。
- B. 新建场景注入一个默认纯色天空盒（值由人类给，例如 #3a7bd5）→ 代价：所有旧场景加载后背景**不变**（旧文件无此键=None），会出现"新建蓝、旧档黑"的分裂，需同时决定旧档迁移策略。
- C. 只改清屏色为浅蓝（不引入天空盒）→ 代价：无地平线/无 cubemap，与"天空盒"概念不同，且 P-01 的三处颜色仍需收敛。

**H-2（P-07 输入语义）**：`Cubemap.from_solid` 收到所有通道 ≤1 的元组时，按哪条解释？
- A. 现状（视为 0-1 浮点并 ×255）→ 代价：0-255 语义下的 (0,0,1,1) 静默变纯蓝。
- B. 只在**显式 float 类型**时按 0-1，整数元组一律按 0-255 → 代价：浮点调用方若传 0.5 会得到"取值 0"的全黑。
- C. 直接拒绝该歧义输入并抛错 → 代价：破坏 `from_solid` 现有调用方（需逐个核对）。

**H-3（P-01 后端一致性）**：GL 播放器与编辑器/VK 的默认背景色，哪个是"权威"？
- A. 统一到 (0.10,0.12,0.16)（编辑器/VK 现用）→ 代价：GL 打包版观感变化（略亮）。
- B. 统一到 (0.05,0.05,0.1)（GL 播放器现用）→ 代价：编辑器视口变暗，网格对比度下降。
- C. 由场景文件显式保存 `background_color`，缺省时各端仍不一致 → 代价：新增字段 + 迁移，问题被推迟而非消除。
