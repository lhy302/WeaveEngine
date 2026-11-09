# 天空盒场景参数链 扫描报告（beta5 · 场景参数链子模块）

> 审计范围：颜色有没有被**保存 / 读回 / 生效**。
> 依据：桌面《论如何正确的 vibe coding》《论如何使用AI自动化工具正确的判断AI给出的黑盒是否符合设计标准》（下称"方法论"）+ `docs/audit/SCAN_PROTOCOL.md`。
> 只读审计：未修改任何受跟踪文件；探针只写在 `Loom/tests/_tmp/`（`.gitignore` 第 20 行 `tests/_tmp/*` 已忽略）。
> 执行时间：2026-11-09。

---

## 结论摘要（先给答案）

1. **场景级纯色天空盒的"保存→读回→渲染"全链是通的**：`#3A9BD5` 经 `skybox_set` → 渲染读出像素 **(58,155,213)** → 落盘 `solid_color=[58,155,213,255]` → 重新加载后渲染仍为 **(58,155,213)**。三次独立测量逐通道相等。
2. **但人类报告的"偏黑天空"有两个真因，都不在天空盒渲染管线里**：
   - **真的没有天空盒**：`examples/PacMan2D.json:1208` 顶层 `"skybox": null`；`Loom/Projects/场景.json`、`Loom/Projects/压测500混合.json` **连 skybox 键都没有**。无天空盒时背景 = 硬编码清屏色 `(0.10,0.12,0.16)` → 屏幕 **RGB(25,31,41)**（实测）。
   - **就算设了也看不见**：`examples/PacMan2D.json:6855-6878` 的 `地板` 平面 `params 10×10 × scale(3.0,1.0,3.0)` = **30×30 世界单位**，把正交视口（`ortho_size=13`）铺满；材质颜色 `#101822`（近黑）。实测：设 `#3A9BD5` 后天空色像素 **0 / 76800**。
3. **"默认蓝色天空"从未实现**：全仓没有任何一处把默认 skybox 设成蓝色。`engine.py:309` 默认 `None`、`editor.py:1181` 新建场景置 `None`、`sceneio.py:1177` 缺键置 `None`；文档 `开发进度与Unity对照.txt:98` 明写"天空盒 ❌ 无（默认清屏色）"。→ 属**设计缺口 + 需求变更**，不是"曾经蓝过后来变黑"的回归（见 §5 Q1）。
4. **"多次修复从未生效"这个怀疑：前两次成立，第三次起成立**。历史 4 个 skybox 提交逐个核对结果见 §2.2 · P-DIS-06 与 §6 Q5：
   - `6a3ad07`（初版）绑了未声明的 `in_uv` → KeyError 被裸 `except` 吞 → 永久禁用；
   - `6deccd2`（"根因修复"）改成 `'2f 2x'` —— 这个格式本身又让顶点数据错乱（被下个提交自己承认），**并且当时编辑器主 pass 压根没调 `_draw_skybox`**，所以那份"根因修复"在编辑器里不可能生效；
   - `0cca8b1`（第三次）的三条修复**当前确实生效**（本报告用像素实测证明）。
5. **真正"至今从未生效"的是相机级覆盖**：`CameraState.skybox` 有明确白盒契约（`loom_scene_entities.py:172-175`："非 None 时优先于场景级"），序列化两端都做了，但**全仓零渲染消费者**。实测：只设 `cam.skybox=#FF0000` → 画面仍是清屏色。这是本项目 N1 同型的"代码存在但路径没走到"。

---

## 0. 范围与方法

### 0.1 文件清单（含行数）

| 文件 | 行数 | 本报告关注点 |
|---|---|---|
| `Loom/sceneio.py` | 1800+ | `_emit_skybox`(543-561)、`_apply_skybox`(564-578)、相机级 emit/apply(596-597 / 621)、场景级 emit/apply(1155-1156 / 1173-1177)、`migrate`(1216-1277) |
| `Loom/editor.py` | 3100+ | `_new_scene`(1156-1197)、`_scene_digest`(948-971)、`_save_scene`(1059-1080)、`_load_scene`(1096-1154)、主 pass 天空盒调用(2278-2284) |
| `Loom/agent_commands.py` | 3300+ | `skybox_set/clear/get`(967-1027) |
| `Loom/loom_render.py` | 851 | `_draw_skybox`(39-117)、播放器清屏色(780)、播放器调用点(814-815) |
| `Loom/loom_cubemap.py` | 196 | `from_files`(45-77)、`from_solid`(80-122) |
| `Loom/loom_shaders.py` | 442 | `_SKY_VERT`/`_SKY_FRAG`(418-442) |
| `Loom/loom_scene_entities.py` | 300+ | `CameraState` `skybox` 契约(151-175) |
| `Loom/engine.py` | 91929B | `_skybox/_sky_prog/_sky_vao/_sky_vbo/_skybox_tint` 默认(305-310) |
| `Loom/scene_driver.py` | 74K | VK 数据链 `skybox`(563-568) |
| `Loom/vk_player.py` / `Loom/vk_renderer.py` | 35K / 99K | VK `sky=` 接线(583) / 清屏色(1960)+天空 pass(1964-1972) |
| `Loom/loom_mcp.py` | 71K | `loom_skybox_set` schema(260-271) |
| `examples/PacMan2D.json` | 156259B | 真实场景内容（126 对象 / skybox:null / 地板 30×30） |
| `docs/audit/pacman2d_scene.json` | 156259B | 与 examples 同内容（skybox:null） |
| `Loom/Projects/场景.json`、`压测500混合.json` | 8943B / 348343B | 无 skybox 键 |
| `docs/audit/scan_02_scene.md` | 60K | 历史审计 P-04/P-10/P-11/P-18 与"建议 12 项" |

### 0.2 判定基准清单（唯一来源，均为本项目自身契约）

| 编号 | 契约原文 | 出处 |
|---|---|---|
| C1 | "相机级天空盒覆盖。语义: 非 None 时优先于场景级 `engine._skybox`；None 时用场景默认。" | `loom_scene_entities.py:172-175` |
| C2 | "`solid_color`：RGBA 数组 [r,g,b] 或 [r,g,b,a]，**0-255**" | `loom_mcp.py:264-269` |
| C3 | "`from_solid(color)` … color=(r,g,b,a) 0-255 或 '#RRGGBB' … **tuple 路径：若所有通道都 ≤ 1.0 视为 0-1 浮点（含 alpha=1.0），也乘 255**" | `loom_cubemap.py:81-87` |
| C4 | "`_apply_skybox`：dict -> Cubemap 实例（**失败返回 None，容错**）" | `sceneio.py:564-565` |
| C5 | "天空盒不随场景继承（默认无天空盒 = 清屏深色底）" | `editor.py:1180` |
| C6 | "`_emit_skybox`：… 都无则返回 None（视为无天空盒）… 内存态 cubemap 无法序列化" | `sceneio.py:543-561` |
| C7 | "编辑器主 pass 之前没调 `_draw_skybox`（只有 PlayerApp 的 GLEngine.render 调了），所以编辑器里设了天空盒也永远看不到" | `editor.py:2278-2279`（0cca8b1 自称的修复对象） |
| C8 | "天空盒 ❌ 无 (默认清屏色)" | `开发进度与Unity对照.txt:98`（同义见 :206） |
| C9 | "用户拍板 A1+B1: 全屏 quad + fragment 反投影采样 cubemap。绘制时机: `_draw_main_buckets` 之后" | `loom_render.py:40-49` |

### 0.3 本轮跑过的命令与探针（全部可复现）

工作目录：`D:\my-project - 副本\Loom(py源代码-工作区)\Loom`

```powershell
python tests/_tmp/skybox_scene_chain.py       # A 场景级链: set->渲染->存->载->渲染 + 相机级覆盖
python tests/_tmp/skybox_entry_color.py       # B 入口颜色语义 (hex / 0-255 / 0-1 浮点)
python tests/_tmp/skybox_pacman_render.py     # C 真实场景 PacMan2D 离屏像素统计
python tests/_tmp/skybox_pacman_cover.py      # D 视口覆盖归因 (谁把天空挡住了)
python tests/_tmp/skybox_state_and_paths.py   # E 哨兵残留 / 脏判定 / 绝对路径可移植性
python tests/_tmp/skybox_range.py             # F 越界颜色 (300 / -5 / 1.5)
```

GL 离屏方式：`moderngl.create_standalone_context()` + 自建 color/depth FBO，把 `EditorApp._external_ctx=True` 并令 `_external_fb` 指向该 FBO（与 `Loom/ui/loom_gui.py:197-199` 的宿主注入方式同构），不启动任何 GUI 窗口。
全部探针均以 `LOOM_NO_SAVE_MIGRATE=1` 运行，且 `editor.DEFAULT_SAVE_DIR`/`_LEGACY_SAVE_DIR` 重定向到临时目录（沿用 `tests/test_cubemap.py:121-127` 的既有纪律），因此**未触碰 `Loom/Projects/` 与仓库内任何受跟踪文件**。

自查：`git status --porcelain` 仅列出本任务开始前就存在的两行未跟踪项（`?? tools/lint_except_dist/`、`?? tools/loom_lint_except.py`），**无受跟踪文件被改动**，不需要 `git checkout` 还原。

Vulkan：本机无可用 Vulkan 设备，`vk_renderer._draw_sky` 的**运行时**表现标 UNVERIFIED（见 §2.3 · P-UNK-03），只做数据链代码推演。

---

## 1. 粗筛清单（含跳过项留痕）

| ID | 位置 | 标签 | 初步方向（指向具体代码事实） |
|---|---|---|---|
| S-01 | `editor.py:2239` / `loom_render.py:780` / `vk_renderer.py:1960` | SEM-MISMATCH | 同一"无天空盒"状态的底色三处常量不一致：编辑器 (0.10,0.12,0.16)、GL 播放器 (0.05,0.05,0.1)、VK (0.10,0.12,0.16) |
| S-02 | `loom_scene_entities.py:172-175` vs 全仓 | AUDIT-DOCIMPL | 契约声明"相机级优先"，但 `grep \.skybox` 在渲染层零命中 |
| S-03 | `loom_render.py:55,83` + `editor.py:1181` + `sceneio.py:1175` | SEM-SILENT | `_sky_prog=False` 哨兵"永久跳过"，只有 `skybox_set/clear` 复位；`_new_scene`/`_load_scene` 不复位 |
| S-04 | `sceneio.py:576-577` | SEM-SILENT | `except Exception: pass` → 天空盒加载失败与"从未设置"不可区分 |
| S-05 | `loom_cubemap.py:77` → `sceneio.py:555` | BND-RESOURCE | `from_files` 存 **abspath** 进场景 JSON；换机器/挪目录即静默无天空盒 |
| S-06 | `agent_commands.py:985-996` | OVERFIT-HARDCODE / AUDIT-ASYMMETRY | `tuple(int(x) for x in solid)` 把 0-1 浮点截成 0；而 `Cubemap.from_solid` 自己承诺"0-1 浮点也乘 255" |
| S-07 | `examples/PacMan2D.json:6855-6878` | SEM-SILENT | `地板` 平面 10×10 × scale 3.0 = 30×30，铺满 `ortho_size=13` 的视口，天空被完全遮挡 |
| S-08 | `sceneio.py:1216-1277` + `:57` | DESIGN-DRIFT | `SCENE_VERSION` 仍是 10，`migrate()` 无任何 skybox 分支；老 v8/v10 文件缺键 = 静默无天空盒 |
| S-09 | `editor.py:948-979` | (排除) | 天空盒变更是否进脏判定 —— 若否，关窗口不提示保存 |
| S-10 | `agent_commands.py:967-1027` | AUDIT-ASYMMETRY | `skybox_set/clear` 不入撤销栈（其余场景级状态都可撤销） |
| S-11 | `sceneio.py:557-561` | SEM-DEFAULT | 内存态 cubemap（`Cubemap(size, faces=...)`）emit 成 None = 静默丢 |
| S-12 | `loom_render.py:103-117` | (排除) | `depth_mask/depth_func` 临时改写与恢复是否污染后续绘制 |

**跳过登记表（每项都给出四类理由之一的出处）**

| 跳过项 | 跳过理由（四类之一） | 出处 |
|---|---|---|
| SK-01 `loom_shaders.py:418-442` 反投影数学（行/列主序、`world.w` 归一） | **已有证据覆盖**：本轮像素实测输入 `#3A9BD5` 输出 (58,155,213) 逐通道相等（探针 A · 1c/PROBE_PASS），数学生效；另 `scan_03_gl_render.md:139` S-03 已审 | `Loom/tests/_tmp/skybox_scene_chain.py` 输出 PASS 1c |
| SK-02 `loom_render.py:103-117` 深度状态保存/恢复 | **已有证据覆盖**：空场景 50.5% 像素为清屏色（天空未越界覆盖几何）、PacMan 0% 天空像素（几何之后画天空、仅 depth==1 通过）→ 遮挡语义正确；另 `scan_04_vk_render.md:392` D-12 已裁决 VK/GL"几何前/后"等价 | 探针 A 输出 0c；探针 C 输出"天空色像素 0" |
| SK-03 `vk_renderer.py:1887,1930` `clear_value=(1,0,0,1)` | **语言/框架自身声明**：两处位于 world-canvas 离屏 pass 与调试底，不是背景 pass；同函数内 1960 行的背景 pass 才是 (0.10,0.12,0.16) | `vk_renderer.py:1958-1963` 上下文 |
| SK-04 `sceneio.py:664-720` 材质 `env_map.solid_color` 往返 | **已有回归测试覆盖**：`tests/test_scene_solid_env_roundtrip.py` 全 PASS（历史输出 `tests/_tmp/_fix_r_vk_stroke_run_all2.txt:2706-2711`）；且材质 env 属另一子代理模块边界 | 同上输出文件 |
| SK-05 `migrate()` 的 v1..v10 迁移逐条 | **白盒契约明确声明**：本模块只需覆盖"缺键=未设置"（C6），迁移表内无 skybox 关键，逐条读过无相关分支 | `sceneio.py:1216-1277` |

统计：疑似项 12 个（S-01..S-12，其中 S-09/S-12 在粗筛后即转为"待证伪"），跳过 5 项，全部有出处。

---

## 2. 逐项裁决

> 每条链的"验证"段给出的命令均在工作目录 `...\Loom` 下可直接运行，输出为本轮实测原样。

### 2.1 P-PROVED（证伪失败 + 证真成功）

---

#### P-PRO-01 · 相机级 `cam.skybox` 有契约、有序列化、但零渲染消费者 · **P2**
`[REGRESSION?] 否（自 6a3ad07 起就未实现，是能力缺口）`

1. **位置**：`loom_scene_entities.py:151-175`（契约）、`sceneio.py:596-597`（emit）、`sceneio.py:621`（apply）。
2. **契约/预期**：C1 —— "非 None 时优先于场景级 `engine._skybox`"。
3. **路径枚举**（证伪：想证明"优先级在渲染层某处实现了"）：
   - 路径 1：`loom_render._draw_skybox` → 只读 `self._skybox`（`loom_render.py:51,98-99`），不读 `self.cameras`/active_camera；
   - 路径 2：`loom_render.render` 调用点 → `if self._skybox is not None`（:814），无相机分支；
   - 路径 3：`editor.py` 主 pass 调用点 → `getattr(self, '_skybox', None)`（:2280），无相机分支；
   - 路径 4：`vk_renderer.draw_frame(sky=...)` → `vk_player.py:583` 传的是 `driver.skybox`（场景级），无相机分支；
   - 路径 5：`grep -n "\.skybox" --include=*.py` 全仓 → 命中仅 `loom_scene_entities.py:175`（赋值）、`sceneio.py:621`（赋值）、`scene_driver.py:566,568`（场景级）——**没有任何读取点**。
   → 路径全部枚举完毕，无一条消费 `CameraState.skybox`。**证伪失败**。
4. **实际行为**（证真）：写入 `cam.skybox = Cubemap.from_solid('#FF0000')`、场景级 `_skybox=None`、渲染一帧 → 背景像素 `(25,31,41)`（清屏色），**不是红色**。
5. **差异**：预期红色天空覆盖背景；实际仍是清屏色。
6. **触发条件**：任何设置相机级天空盒的场景（编辑器、GL 播放器、VK 播放器均同）。
7. **验证**：
   ```
   python tests/_tmp/skybox_scene_chain.py
   [3] 相机级 skybox 已设, 场景级 = None
   PASS 3a) 相机级 cam.skybox 不被渲染 (背景仍是清屏色)  (25, 31, 41)
   PROBE_PASS
   ```
   另：`grep -n "skybox" Loom/loom_render.py` 输出中 `skybox` 全部是 `self._skybox`，无 `camera`。
8. **影响与等级**：**P2**。功能静默缺失 + 契约与实现冲突；用户在相机面板/API 设置后"保存成功、读回成功、画面不动"，且 `skybox_get` 只报场景级（:1020 `getattr(win.editor, '_skybox', None)`），连"设过相机级"都读不到。

---

#### P-PRO-02 · `_sky_prog=False` 哨兵跨 `_load_scene`/`_new_scene` 残留 → 加载含天空盒的场景仍不画 · **P2** · **[REGRESSION: 6deccd2 引入]**
`[REGRESSION] 由 6deccd2 引入（"永久跳过"哨兵），0cca8b1 只补了 set/clear 两处复位。`

1. **位置**：`loom_render.py:53-56`（`if self._sky_prog is False: return`）、`loom_render.py:81-84`（置哨兵）、`agent_commands.py:999-1004 / 1011-1014`（仅这两处复位）、`editor.py:1181`/`sceneio.py:1175`（新场景/加载场景**不复位**）。
2. **契约/预期**：C7 与 C9 —— 设了天空盒就该画出来；场景加载后 `engine._skybox` 被重建（`sceneio.py:1175`），新数据应当能被绘制。
3. **路径枚举**（证伪：想证明"哨兵必然被某个复位点清掉"）：
   - 路径 1：`skybox_set` → 复位（`agent_commands.py:1002-1004`）✓；
   - 路径 2：`skybox_clear` → 复位（:1012-1014）✓；
   - 路径 3：`_new_scene`（`editor.py:1156-1197`）→ **只置 `_skybox=None`，不碰 `_sky_prog`** ✗；
   - 路径 4：`_load_scene` → `scene_from_dict`（`sceneio.py:1174-1177`）→ **只改 `_skybox`，不碰 `_sky_prog`** ✗；
   - 路径 5：`_draw_skybox` 内部自愈？→ 只有 `is None` 才重建 program，`False` 直接 return ✗。
   → 存在"哨兵不被清除"的可达路径。**证伪失败**。
4. **实际行为**：正常渲染天空色像素 3202 → 令 `_sky_prog=False`（模拟上一次编译失败留下的哨兵）→ **0**；再 `skybox_set` → 恢复 3202；此后再次 `_sky_prog=False` 并 `_load_scene`（该文件里含 `skybox.solid_color`）→ `_sky_prog` **仍是 False**、像素 **0**；`_new_scene` 后仍 False。
5. **差异**：预期"加载了一份带天空盒的场景 → 天空盒出现"；实际"数据已加载、程序永久跳过 → 画面无天空盒"，且**无任何日志**。
6. **触发条件**：任意一次 `ctx.program(...)` 失败（GL 上下文重建 / 驱动异常 / 修改着色器后语法错误 —— `loom_render.py:54` 注释明说"用户改 shader 后"）之后，只要不重新 `skybox_set`，天空盒就永远不再画。
7. **验证**：
   ```
   python tests/_tmp/skybox_state_and_paths.py
   B0 正常渲染天空色像素 = 3202
   B1 哨兵 False 后天空色像素 = 0
   B2 重新 skybox_set 后天空色像素 = 3202
   [编辑器] 已加载 0 个对象
   B3 load_scene 后 _sky_prog = False (False=哨兵仍在, 天空盒继续不画)
   B4 加载含天空盒场景后天空色像素 = 0
   B5 _new_scene 后 _sky_prog = False  _skybox = None
   ```
8. **影响与等级**：**P2**。这是最像"(修复代码存在，但状态把它挡住)"的现存路径；排查者会看到 `_skybox` 有值、`solid_color` 正确、代码在，却永远画不出。

---

#### P-PRO-03 · `skybox_set` 入口把 0-1 浮点颜色截成 0 → 纯黑天空，且返回 `ok=True` · **P2** · **[REGRESSION: 0cca8b1 引入数组支持时带出]**
`[REGRESSION] 0cca8b1 在同一提交里既修"hex 0-1 浮点被 int 成 0"，又新增数组入口 `int()` 截断 —— 同类缺陷从字符串路径搬到了数组路径。`

1. **位置**：`agent_commands.py:985-996`（`rgba = tuple(int(x) for x in solid)`，:991）对比 `loom_cubemap.py:89-93`（`_to_255`：0-1 视为浮点并乘 255）。
2. **契约/预期**：C3 —— `Cubemap.from_solid` 的公开契约明确"tuple 路径：若所有通道都 ≤ 1.0 视为 0-1 浮点，也乘 255"。命令层把参数先 `int()` 再转交，等于在调用 `from_solid` 之前就毁掉了它承诺支持的输入。
3. **路径枚举**（证伪：想证明"两个入口对同一输入结果一致"）：
   - 路径 1：`solid_color` 为 str → `Cubemap.from_solid(str)`（:988-989）→ 走 `_hex_rgba` → 正确 ✓；
   - 路径 2：`solid_color` 为 0-255 int 数组 → `int()` 无损 → 正确 ✓；
   - 路径 3：`solid_color` 为 0-1 float 数组 → `int(0.23)=0` → 全黑 ✗（与 C3 冲突）；
   - 路径 4：`solid_color` 为 0-1 且带 alpha=1.0 → 同上全黑 ✗。
   → 路径 3/4 与 C3 冲突。**证伪失败**。
4. **实际行为**（证真，最小复现）：
   ```python
   ac.dispatch('skybox_set', {'solid_color': [0.23, 0.61, 0.84]}, win)
   # -> ok=True, win.editor._skybox._solid_color == (0, 0, 0, 255)   # 纯黑
   Cubemap.from_solid((0.23, 0.61, 0.84))._solid_color
   # -> (59, 156, 214, 255)                                          # 同一入参，直调正确
   ```
5. **差异**：预期 (59,156,214)；命令路径实际 (0,0,0)，且**静默**（`ok=True`、无 error、`skybox_get` 也看不出颜色）。
6. **触发条件**：任何用 0-1 浮点数组设置纯色天空盒的调用方（AI/脚本最容易这么写，Unity 的 `Color` 就是 0-1）。
7. **验证**：
   ```
   python tests/_tmp/skybox_entry_color.py
   hex #3A9BD5                                -> ok=True _solid_color=(58, 155, 213, 255)
   int 0-255 [58,155,213]                     -> ok=True _solid_color=(58, 155, 213, 255)
   float 0-1 [0.23,0.61,0.84]                 -> ok=True _solid_color=(0, 0, 0, 255)
   float 0-1 + alpha [0.23,0.61,0.84,1.0]     -> ok=True _solid_color=(0, 0, 0, 255)
   float 0-1 + alpha [0.23,0.61,0.84,255]     -> ok=True _solid_color=(0, 0, 0, 255)
   --- Cubemap.from_solid 直调 (绕开入口 int()) ---
   (0.23, 0.61, 0.84)             -> _solid_color=(59, 156, 214, 255)
   ```
8. **影响与等级**：**P2**。这是"设了天空盒却是黑的"最省力的自造途径之一，且错误方向恰好与人类的报告一致（偏黑）。

---

#### P-PRO-04 · 真实场景 PacMan2D：天空盒设了也 0 像素可见（地板 30×30 铺满视口） · **P1（用户症状真因）**

1. **位置**：`examples/PacMan2D.json:6855-6878`（`地板`：`type=plane`、`params {width:10,depth:10}`、`scale [3.0,1.0,3.0]`、`color "#101822"`）、`:1208`（`"skybox": null`）；渲染侧 `editor.py:2239`（清屏 0.10,0.12,0.16）。
2. **契约/预期**：天空盒是"背景 pass"（C9），只能出现在**没有几何覆盖**的像素上；因此若视口 100% 被几何覆盖，天空盒必然不可见。
3. **路径枚举**（证伪：想证明"设了天空盒在 PacMan 场景里能看到"）：
   - 路径 1：`skybox=null` → `_draw_skybox` 直接 return（`loom_render.py:51`）→ 无天空盒；
   - 路径 2：设纯色天空盒 → 天空 quad 在 z=1.0、`depth_func='<='`，仅在 depth==1.0 的像素通过；地板 30×30（世界单位）在正交视口 `ortho_size=13`（`editor.py:2257-2260`）内覆盖全部像素 → 天空无法通过；
   - 路径 3：把相机拉远/倾斜到看见地板外缘 → 天空才会出现（未做，仅说明几何语义）。
   → 两条可达路径都不产生天空像素。**证伪失败**。
4. **实际行为**：
   ```
   [pac] models=126 ortho=True ortho_size=13.0 skybox=None cameras=1
   [pac 无天空盒] 清屏色像素 = 0 / 76800 (0.0%)
   [pac] 设 #3A9BD5 后天空色像素 = 0 (0.0%)
   ```
   视口主色为 `(42,50,59) 19.6%`（受光后的 `#101822` 地板）与 `(53,65,99) 10.1%`（`#1B2A6B` 墙）。
5. **差异**：预期"设了颜色 → 背景变蓝"；实际"背景是地板网格，天空 0 像素"。
6. **触发条件**：任何相机视角被大地面/背景体完全覆盖的场景（PacMan2D、绝大多数 2D 俯视场景）。
7. **验证**：
   ```
   python tests/_tmp/skybox_pacman_render.py
   python tests/_tmp/skybox_pacman_cover.py
   # cover 输出: corner top-left=(47,55,63) 众数 (42,50,59) x 19.6% ; floor pos (0,0,0) scale (3.0,1.0,3.0) color #101822
   ```
8. **影响与等级**：**P1**（人类报告的直接解释）。判定要点：**引擎天空盒管线不是元凶**，元凶是（a）场景里没有天空盒数据、（b）场景内容把视口铺死。修复方向在场景/资产层与工具提示，不在渲染器。

---

#### P-PRO-05 · 无天空盒时底色三处常量不一致（GL 播放器更暗） · **P2**
1. **位置**：`editor.py:2239` `_clear_main_fbo(0.10, 0.12, 0.16)`；`loom_render.py:780` `_clear_main_fbo(0.05, 0.05, 0.1)`；`vk_renderer.py:1960` `clear_value (0.10,0.12,0.16,1.0)`。
2. **契约/预期**：同一份场景、同一个"无天空盒"状态，双后端/编辑器三处应给出同一底色（`渲染API与双后端一致性审计_20261106.md:12` 明确把"切换后同一游戏少东西/不同"列为不可接受）。
3. **路径枚举**（证伪：想证明"三处其实同一个值或存在统一来源"）：
   - 路径 1：编辑器主 pass → 0.10/0.12/0.16；
   - 路径 2：GL 播放器（`GLEngine.render`）→ 0.05/0.05/0.1；
   - 路径 3：VK 播放器 → 0.10/0.12/0.16；
   - 路径 4：是否存在共享常量（如 `CLEAR_COLOR`）？`grep -n "clear_color|CLEAR_COLOR"` 全仓零命中 → 三处都是字面量。
   → 三处数值不统一，且无单一来源。**证伪失败**。
4. **实际行为**：0.10,0.12,0.16 → 8bit (25,31,41)（探针 A 实测）；0.05,0.05,0.1 → 8bit (13,13,26)。
5. **差异**：同一无天空盒场景，编辑器/VK 亮一档，GL 播放器明显更黑（差约 2 倍亮度）。
6. **触发条件**：任何没有天空盒的场景，用 GL 播放器打开。
7. **验证**：
   ```
   grep -n "0.10, 0.12, 0.16" Loom/editor.py Loom/vk_renderer.py
   grep -n "0.05, 0.05, 0.1"   Loom/loom_render.py
   python tests/_tmp/skybox_scene_chain.py   # 编辑器背景实测 (25,31,41)
   ```
8. **影响与等级**：**P2**（一致性/可预期性；不崩不丢数据）。它也是"偏黑"体感的放大器：若不看编辑器而看 GL 播放器，背景会更黑。

---

#### P-PRO-06 · `skybox_set/clear` 不入撤销栈（其余场景级状态都可撤销） · **P3**
1. **位置**：`agent_commands.py:967-1015`（只做赋值）；对照 `editor.py:629,634,727,795,817,933,1582` 等对光源/相机/物体/材质/投影都 `undo.push(...)`。
2. **契约/预期**：项目对"场景级状态变更"的统一承诺是可撤销（`tests/test_undo_full_coverage.py` 逐项覆盖光源/相机/材质/LOD/投影）。
3. **路径枚举**：`skybox_set`(:969-1005)、`skybox_clear`(:1009-1015) 两条入口，均无 `undo.push`；`UndoManager` 侧也没有天空盒命令类（`grep -n "Skybox" Loom/undo.py` 零命中）。→ **证伪失败**。
4. **实际行为**：设天空盒后按 Ctrl+Z，天空盒不变（撤销的是更早的操作）。
5. **差异**：预期可撤销；实际不可撤销，且不会破坏更早的撤销链（静默不同步）。
6. **触发条件**：误设天空盒后想撤销。
7. **验证**：
   ```
   grep -n "skybox" Loom/undo.py            # 无输出
   grep -n "undo.push" Loom/agent_commands.py | Select-String skybox   # 无输出
   ```
8. **影响与等级**：**P3**（可维护性/一致性）。

---

### 2.2 P-DISPROVED（证伪成功）

---

#### P-DIS-01 · 场景级纯色天空盒 保存/读回/渲染 不一致？ · **P-DISPROVED**
1. **位置**：`agent_commands.py:985-1005` → `sceneio.py:543-561` → `:1155-1156` → `:564-578` → `:1173-1177` → `editor.py:2278-2284` → `loom_render.py:39-117`。
2. **契约/预期**：`skybox_set` 设的颜色应"存得进、读得回、画得出"（C7/C9 + `skybox_get` 的"读当前场景级天空盒信息"）。
3. **路径枚举**（证伪：逐条走完全部 5 段）：
   - 路径 1 设置：`cmd_skybox_set` → `Cubemap.from_solid('#3A9BD5')` → `_solid_color=(58,155,213,255)` ✓；
   - 路径 2 渲染：`editor.py:2280` 判非 None → `_draw_skybox` → 像素 (58,155,213) ✓；
   - 路径 3 序列化：`scene_to_dict` → `_emit_skybox` → `{"name","guid","solid_color":[58,155,213,255]}` ✓；
   - 路径 4 加载：`scene_from_dict` → `_apply_skybox` → `Cubemap.from_solid(tuple(solid_color))` → `_solid_color` 相同 ✓；
   - 路径 5 再次渲染：像素仍 (58,155,213) ✓。
   → 五段全通过，**证伪成功**（不存在"存/读/画"断裂）。
4. **实际行为**：见验证输出（三次采样逐通道相等）。
5. **差异**：无。
6. **触发条件**：不适用。
7. **验证**：
   ```
   python tests/_tmp/skybox_scene_chain.py
   PASS 0a) 默认背景 = 清屏色 (26,31,41)±2  (25, 31, 41)
   PASS 1c) 设纯色后背景 ≈ #3A9BD5 (58,155,213) ±3  (58, 155, 213)
   PASS 2b) solid_color = [58,155,213,255]
   PASS 2e) 重载后画面 ≈ #3A9BD5  (58, 155, 213)
   PROBE_PASS
   ```
8. **影响与等级**：无缺陷。**下次粗筛遇到"天空盒存不住/读不回"可直接引用本编号跳过。**

---

#### P-DIS-02 · 编辑器主 pass 不调用 `_draw_skybox`（历史 Bug B）仍存在？ · **P-DISPROVED**
1. **位置**：`editor.py:2278-2284`（0cca8b1 加入的调用）、`ui/loom_gui.py:263`/`:603`（宿主每帧调 `e.render(delta)`）。
2. **契约/预期**：C7 —— 编辑器主 pass 必须调 `_draw_skybox`。
3. **路径枚举**：
   - 路径 1：Qt 正常视口 `paintGL`(`loom_gui.py:180`) → ... → `:263 e.render(delta)` → `editor.py:2172 render` → :2280 调用 ✓；
   - 路径 2：Remote 离屏模式 `_tick`(`loom_gui.py:551`) → `:603 e.render(delta)` → 同上 ✓；
   - 路径 3：无头探针直调 `ed.render()` → 同一条 `render()` ✓（本轮探针正是走这条路并成功出像素）。
   → **证伪成功**：调用点在真实宿主路径上且生效。
4. **实际行为**：探针 A 1c/2e 与探针 C 都实现了天空色像素（3202 / 29228 量级）。
5. **差异**：无。
6. **触发条件**：不适用。
7. **验证**：`grep -n "\.render(delta" Loom/ui/loom_gui.py` → `263:`、`603:`；`python tests/_tmp/skybox_scene_chain.py` → `PASS 1c`。
8. **影响与等级**：无缺陷（第三次修复真实生效）。

---

#### P-DIS-03 · 老场景文件"缺 skybox 键"是缺陷？ · **P-DISPROVED**
1. **位置**：`sceneio.py:57`（`SCENE_VERSION = 10`）、`:1216-1277`（`migrate`，无 skybox 分支）、`:1173-1175`（`data.get('skybox')` 缺键即 None）。
2. **契约/预期**：C6 —— "旧文件无此键 -> None（视为无天空盒）"。skybox 是 v10 之上的**可选键**，不升版本、无迁移位。
3. **路径枚举**：
   - `Loom/Projects/压测500混合.json`（version 8，无键）→ None ✓（契约允许）；
   - `Loom/Projects/场景.json`（version 10，无键）→ None ✓；
   - `examples/PacMan2D.json:1208`（version 10，`"skybox": null`）→ None ✓；
   - 有键且合法 → Cubemap ✓。
   → 四种形态行为一致且符合契约，**证伪成功**。
4. **实际行为**：全部解析为"无天空盒"，不抛异常、不误判。
5. **差异**：无（缺键 ≡ null ≡ 未设置，语义统一）。
6. **触发条件**：不适用。
7. **验证**：
   ```
   python -c "import json;d=json.load(open('examples/PacMan2D.json',encoding='utf-8'));print(d['version'],d['skybox'],d['cameras'][0]['skybox'])"
   -> 10 None None
   ```
8. **影响与等级**：无缺陷。附带说明：**"旧场景没有天空盒"是数据结构演进的正常结果**，不是数据丢失。

---

#### P-DIS-04 · 天空盒改动不进脏判定（关窗口静默丢）？ · **P-DISPROVED**
1. **位置**：`editor.py:948-979`（`_scene_digest` 用 `sceneio.scene_to_dict` 全量摘要）。
2. **契约/预期**：场景内容改动必须置脏（否则关窗口不问保存）。
3. **路径枚举**：`scene_to_dict` → `_emit_skybox(engine._skybox)`（`sceneio.py:1156`）→ 纯色 cubemap 输出 `solid_color` → 摘要变化 ✓；文件源输出 `paths` → 摘要变化 ✓；内存态 cubemap → None（但该态无 UI 入口，见 P-DIS-05）。
   → **证伪成功**。
4. **实际行为**：`mark_saved()` 后 `skybox_set` → `scene_is_dirty() == True`；`skybox_clear` → 回到 `False`。
5. **差异**：无。
6. **触发条件**：不适用。
7. **验证**：
   ```
   python tests/_tmp/skybox_state_and_paths.py
   A0 新建基线 dirty = False
   A1 设天空盒后 dirty = True (应为 True, 否则关窗口不提示保存)
   A2 清除后 dirty = False
   ```
8. **影响与等级**：无缺陷。

---

#### P-DIS-05 · 内存态 cubemap 被 emit 成 None（静默丢）违反契约？ · **P-DISPROVED**
1. **位置**：`sceneio.py:557-561`。
2. **契约/预期**：C6 明确"内存态 cubemap 无法序列化 → 返回 None"。
3. **路径枚举**：无 `paths` 且无 `_solid_color` → None（唯一分支）；有 `paths` → 走 paths；有 `_solid_color` → 走 solid_color。三路与注释逐字一致。
4. **实际行为**：`_emit_skybox(Cubemap(size=2))` → `None`（探针 B 输出 "无来源 cubemap … = None"）。
5. **差异**：无（契约即此）。
6. **触发条件**：仅当代码直接 `Cubemap(size, faces=[...])` 并挂到 `_skybox`；`agent_commands`/`sceneio` 两条公开入口都不会产生该形态。
7. **验证**：`python tests/_tmp/skybox_entry_color.py` → `=== 无来源 cubemap (paths=None, _solid_color=None) ===` 行输出 `None`。
8. **影响与等级**：无缺陷（记 P3 备注：若将来支持程序化天空盒，需补 emit 分支）。

---

#### P-DIS-06 · `6deccd2` 声称的"天空盒一直黑的根因修复"当年生效？ · **P-DISPROVED（历史主张不成立；当前代码已由 0cca8b1 取代并生效）**
1. **位置**：`git show 6deccd2 -- Loom/loom_render.py Loom/editor.py`；`loom_render.py:62-67`（0cca8b1 的注释自证）。
2. **契约/预期**：提交标题"天空盒一直黑的根因（VAO 绑了未声明的 in_uv → KeyError → 被 except 吞掉 → 天空盒永久禁用）"暗示修完即可见。
3. **路径枚举**（当年 vs 现在）：
   - 当年路径 1：编辑器 `render()` 里**没有** `_draw_skybox` 调用（该调用在 `0cca8b1` 才加入，见 `git show 0cca8b1 -- Loom/editor.py` 的 `+ if getattr(self, '_skybox', None) is not None: self._draw_skybox()`）→ 编辑器里无论 VAO 对错都画不到；
   - 当年路径 2：`6deccd2` 把 VAO 格式改成 `'2f 2x'`，而 `loom_render.py:62-67` 的现行注释写明"moderngl 的 '2f 2x' 不是 padding 语义…顶点坐标读到垃圾数据 -> quad 不覆盖屏幕"→ 该"修复"自己制造了新的黑屏原因；
   - 现在路径：独立 `2f` VBO（:69-75）+ 编辑器调用点（:2280）+ hex/数组颜色修正 → 探针实测可见。
   → **证伪成功**："6deccd2 让天空盒可见"不成立（两条路径堵死）；但"当前代码可见"成立（另一件事，见 P-DIS-01）。
4. **实际行为**：见 §0.3 探针 A/C。
5. **差异**：历史提交标题与当年可达性不符（AUDIT-DOCIMPL，无代码缺陷残留）。
6. **触发条件**：不适用（历史）。
7. **验证**：`git show 6deccd2 --stat`（只动 editor/loom_render/tests，**不含**编辑器主 pass 调用）；`git show 0cca8b1 -- Loom/editor.py | Select-String "_draw_skybox"` → 显示该调用是新增行。
8. **影响与等级**：无现存缺陷；但正是人类怀疑的"修复从未生效"N1 模式的两个真实历史实例（另见 §6 Q5）。

---

### 2.3 P-UNKNOWN（证伪与证真都失败 → 已写探针，仍需人类/设计裁决）

#### P-UNK-01 · 6 面图片天空盒把**绝对路径**写进场景 → 换机/挪目录后静默消失
- **已尝试探针**：`python tests/_tmp/skybox_state_and_paths.py`
  ```
  C0 emit paths 绝对? = True C:\Users\ADMINI~1\AppData\Local\Temp\loom_faces_9b7v8r4n\f0.png
  C1 文件缺失后 _apply_skybox -> None | 打印输出 = ''
  C2 skybox_get 能区分"从未设置"与"加载失败"吗? 两者都是 skybox=None -> 不能
  ```
- **证伪为何失败**：`Cubemap.from_files` 契约（`loom_cubemap.py:45-77`）只承诺"从 6 张图片加载"，没承诺"路径可移植"；而项目另有资产体系（`assets/`+`guid`）与 `export` 流程，说明"资产应可移植"是项目级期待。两条判据互不覆盖 → 无法判定"绝对路径写盘"是否违约。
- **证真为何失败**：无法给出"预期值"——`sceneio` 没有"路径必须相对"的契约句。
- **还缺什么**：一个白盒裁决 —— 天空盒图片是否必须走资产系统（相对路径/guid 引用），还是允许存机器绝对路径。
- **建议下一步探针**：把含 `skybox.paths` 的场景整体复制到另一目录后加载，比较 `skybox_get`（本机已可复现 C1 行为，但"是否可接受"是设计问题）。

#### P-UNK-02 · 越界颜色（>255 / <0）在**场景加载路径**静默丢弃，在**命令路径**才报错
- **已尝试探针**：`python tests/_tmp/skybox_range.py`
  ```
  {'solid_color': [300, 0, 0]}   -> ok=False err=纯色天空盒创建失败: OverflowError(...)
  {'solid_color': [-5, 0, 0]}    -> ok=False err=... OverflowError(...)
  --- _apply_skybox 越界 (场景加载路径) ---
  {'solid_color': [300, 0, 0, 255]} -> None | log=''
  {'solid_color': [-5, 0, 0, 255]}  -> None | log=''
  ```
- **证伪为何失败**：C4 写明"失败返回 None，容错"，故加载路径静默不算违约；但同一数值在命令路径会出声，两条入口策略不一致。
- **证真为何失败**：项目从未定义"非法颜色"的处理策略（拒绝/钳制/回落默认），无法判违约。
- **还缺什么**：非法输入策略的白盒声明。
- **建议下一步探针**：把 `{solid_color:[300,0,0,255]}` 的场景加载后查询 `skybox_get`，确认"有键但被吞"与"无键"完全同形（已由 C2 结论覆盖）。

#### P-UNK-03 · VK 后端天空盒运行时是否真的出图 · **UNVERIFIED**
- **已尝试**：`vk_renderer.py:1956-1972` 逻辑读通（`sky is not None` → `_draw_sky`，清屏色 0.10/0.12/0.16，几何其后完整覆盖）；数据链 `scene_driver.py:563-568` → `vk_player.py:583` 完整。
- **证伪/证真都失败的原因**：本机无可用 Vulkan 设备，`_draw_sky` 需真实 device/pipeline 才能出像素。
- **还缺什么**：一台有 Vulkan 设备的机器 + `tests/_tmp/ab_gl_vk.py` 的 A/B 对比。
- **建议下一步探针**：`python tests/_tmp/ab_gl_vk.py`（需 VK 设备），对 `{"skybox":{"solid_color":[58,155,213,255]}}` 场景做 MAE。

---

### 2.4 P-CONTRADICTION

#### P-CON-01 · `_apply_skybox` 静默容错：「符合自身契约」与「不可诊断」同时成立 → 白盒层契约冲突
1. **位置**：`sceneio.py:564-578`（`except Exception: pass`）、`agent_commands.py:1018-1027`（`skybox_get`）、对照 `scene_driver.py:576-577`（同类加载失败**会打印** `[driver] UI 恢复失败`）。
2. **契约/预期**：C4 —— "失败返回 None，容错"。
3. **推理链 A（证伪：证明不是 bug）**：路径 1 无段→None；路径 2 文件齐全→Cubemap；路径 3 文件缺失/越界→异常被捕获→None；路径 4 纯色→from_solid。四条路径**逐条符合 C4**（`scan_02_scene.md:674-683` 也据此判 P-DISPROVED）→ 证伪成功。
4. **推理链 B（证真：证明是缺陷）**：同一项目内 `_apply_ui` 的失败路径打印"UI 恢复失败"（`scene_driver.py:576`）、音频字段有显式告警（`scan_02_scene.md:876` 亦称"与音频 category 的显式告警对齐"）；而天空盒失败**零输出**，且 `skybox_get` 对"从未设置"与"加载失败"返回同一个 `{'skybox': None}` → 用户无法定位"为什么我的天空盒没了" → 证真成功。
5. **矛盾点与判定**：两条链都成立，且**不是推理错误** —— 冲突在判定基准层：C4（容许静默）与项目级"加载失败要出声"约定互相冲突。按方法论 §8.2，属**白盒层 DESIGN-CONFLICT**，AI 不得自行改契约。
6. **触发条件**：天空盒 6 面图被移动/改名、或 solid_color 越界。
7. **验证**：
   ```
   python tests/_tmp/skybox_range.py     # 加载路径 log=''（零输出）
   python tests/_tmp/skybox_state_and_paths.py  # C1 log='' ; C2 "两者都是 skybox=None"
   grep -n "UI 恢复失败" Loom/scene_driver.py    # 576: 同类失败会打印
   ```
8. **影响与等级**：**P2**（可诊断性）。处理方式：升级为人类裁决（§5 Q2），不在本轮改任何代码/契约。

---

## 3. 统计

| 判定 | 数量 | 编号 |
|---|---|---|
| P-PROVED | 6 | P-PRO-01..06 |
| P-DISPROVED | 6 | P-DIS-01..06 |
| P-UNKNOWN | 2 | P-UNK-01、P-UNK-02（另 P-UNK-03 为 UNVERIFIED：无 Vulkan 设备） |
| P-CONTRADICTION | 1 | P-CON-01（已按白盒层处理，交人类裁决） |
| **合计** | **15** | |
| 跳过留痕 | 5 | SK-01..SK-05 |

- **P-UNKNOWN 非 0 的说明**：本模块的两处不确定都源于"契约本身没定义"（路径可移植性、非法输入策略），不是探测不足 —— 方法论 §6.4 定义的"人类裁决项"正是这种形态。
- **P-PROVED 非 0**：其中 P-PRO-01/02/03/05/06 是代码级缺陷，P-PRO-04 是"人类症状真因"（责任在场景内容，非引擎）。
- **P-DISPROVED 警告说明**：6 条证伪成功里，P-DIS-01/02/04 是本轮**用像素实测**确认的（不是"读代码觉得对"），可直接复用为后续跳过依据；P-DIS-06 是历史主张审计，不是现存缺陷。
- **[REGRESSION] 清单**：P-PRO-02（6deccd2 引入哨兵）、P-PRO-03（0cca8b1 引入数组 int() 截断）。

---

## 4. 修复建议排序（只给方向，不含代码）

| 序 | 等级 | 编号 | 建议方向（方向性描述，不含实现） |
|---|---|---|---|
| 1 | P1 | P-PRO-04 | 场景层：`地板` 的 `scale 3.0` 与本意（10×10 地台）不符，需人工确认后修正场景数据；工具层建议在"设了天空盒但当前视角 0 像素可见"时给一次可见提示，避免同类误判为引擎 bug |
| 2 | P2 | P-PRO-01 | 二选一由人类裁决：**要么**在渲染层落实 C1 的相机级优先级（取 active_camera/preview_camera 的 skybox，None 回落场景级），**要么**删掉/改写 C1 契约与 `_emit_camera`/`_apply_cameras` 的相机 skybox 段，避免"存了不用" |
| 3 | P2 | P-PRO-02 | 把"编译失败哨兵"的复位点收敛到**唯一的资源失效入口**（换场景/新建/换 cubemap 都走同一处），而不是散落在 set/clear 两个命令里 |
| 4 | P2 | P-PRO-03 | 命令层把颜色归一交给 `Cubemap.from_solid`（已在 C3 实现），入口不再自行 `int()`；非法值走"出声 + 按策略回落"，与 P-UNK-02 的策略裁决一起做 |
| 5 | P2 | P-PRO-05 | 抽出唯一的"无天空盒底色"常量并让编辑器/GL 播放器/VK 三处引用同一值；顺带决定它是否应为天空蓝（见 §5 Q1） |
| 6 | P2 | P-CON-01 | 按人类对 §5 Q2 的裁决，给天空盒加载失败补一次可见告警；并让 `skybox_get` 能区分"未设置 / 加载失败 / 已设置"（例如返回 `origin` 或 `lost` 标记） |
| 7 | P3 | P-PRO-06 | 天空盒纳入撤销栈（与其他场景级状态同构） |
| 8 | P3 | P-UNK-01/02 | 裁决后再定：天空盒图片是否资产化/相对路径；非法颜色策略（拒绝 or 钳制） |

---

## 5. 需要人类裁决的封闭问题（最多 5 条，均为"选 A 还是选 B"）

**Q1（默认天空盒到底应该是什么？—— 直接对应人类的"默认应该是蓝色"）**
本仓事实：`engine.py:309` 默认 `_skybox=None`；`editor.py:1181` 新建场景置 None（注释：C5"默认无天空盒 = 清屏深色底"）；`开发进度与Unity对照.txt:98` 记"天空盒 ❌ 无（默认清屏色）"；全仓无任何"默认蓝色"的实现或需求文档（`grep "默认天空盒|默认.*蓝色|#87CEEB|#3A7BD5"` 零命中）。请选：
- **A**：这是**有意设计**（无天空盒 = 深色底），"默认蓝"是新增需求 → 需要新增：`_new_scene` 建默认纯色天空盒（蓝色取值请指定 hex），且**同时**保留"用户清空后回到深色底"的语义；
- **B**：这是**从未实现的缺口**（早期就该有默认天空盒，只是没人写）→ 等价于 A 的施工，但需回填"历史需求依据"以免再次被判为回归；
- **C**：保持现状，但把三处硬编码清屏色统一（P-PRO-05），并明确"想蓝请自己设天空盒"。

**Q2（天空盒加载失败要不要出声？—— P-CON-01）**
- **A**：出声（失败打印一次 + `skybox_get` 标注"加载失败"），代价是旧场景首次加载会多几行日志；
- **B**：保持静默容错（改契约 C4 的措辞为"静默容错是明确设计"），代价是继续无法定位"天空盒为什么没了"。

**Q3（相机级天空盒怎么处理？—— P-PRO-01）**
- **A**：实现它（按 C1：非 None 优先于场景级，active/preview 相机生效）；
- **B**：废弃它（删契约与序列化字段），代价是旧场景里已存的 `cameras[].skybox` 成为无效字段。

**Q4（天空盒图片路径可移植性？—— P-UNK-01）**
- **A**：必须资产化（存相对路径/guid，与 `assets/` 体系一致），代价是要动 sceneio 的路径写入与资产解析；
- **B**：允许绝对路径（明确"天空盒图片只在本机有效"写进契约），代价是换机器必丢。

**Q5（颜色数组的合法域？—— P-PRO-03 / P-UNK-02）**
- **A**：只认 0-255（MCP schema 现状），0-1 浮点一律出声报错并拒绝；
- **B**：两者都认（与 `Cubemap.from_solid` 的 C3 承诺一致，按"全 ≤1.0 视为浮点"判定），代价是 (1,1,1) 这种输入会有歧义。

---

## 6. 五个指定问题的直接回答

### Q1 场景 JSON 里 skybox 字段的真实形态

| 场景文件 | version | 顶层 `skybox` | `cameras[].skybox` | 备注 |
|---|---|---|---|---|
| `examples/PacMan2D.json`（= `docs/audit/pacman2d_scene.json`） | 10 | **null**（:1208） | **null**（:1204） | 126 对象；扫描 6 面图 → **无**，纯色 → **无**。即"两种来源都没有" |
| `Loom/Projects/场景.json` | 10 | **键不存在** | 无相机 | 早于 skybox 功能保存的老文件 |
| `Loom/Projects/压测500混合.json` | 8 | **键不存在** | 无相机 | 同上 |
| `docs/audit/pacman3d_scene.json` | 10 | **null** | 无相机 | 同上 |

结论：**现存所有场景都没有天空盒数据**；形态上"顶层 skybox: null"与"缺键"等价（C6），不存在 `solid_color` 或 6 张图的真实样例。

### Q2 往返一致性（skybox_set → 保存 → 重新加载 → skybox_get）
**一致**，并且是**像素级**一致（不只是字段级）：

| 阶段 | 结果 |
|---|---|
| `skybox_set({'solid_color':'#3A9BD5'})` | `_solid_color=(58,155,213,255)` |
| 渲染像素（0.5,0.05 处） | (58,155,213) |
| `skybox_get` | `{'name':'probe_blue','guid':..., 'source':'solid'}` |
| 落盘 | `"skybox": {"name","guid","solid_color":[58,155,213,255]}` |
| 重载 + 渲染 | (58,155,213) |
| `skybox_get` 重载后 | `source: 'solid'` |

注意两点局限：(a) `skybox_get` **不返回颜色**，只返回 name/guid/source —— 人类无法用 API 自证颜色是否正确；(b) 0-1 浮点数组入口会静默变黑（P-PRO-03），这是"设置成功但颜色错"的唯一代码级途径。

### Q3 相机级覆盖与场景级谁优先？有没有"设置了但被 None 覆盖"的路径？
- **实际优先级：不存在**。渲染层只认 `self._skybox`（场景级），相机级零消费者（P-PRO-01 五路枚举 + 像素实测：只设相机级 → 背景依旧是清屏色）。
- **"被 None 覆盖"的可达路径**（都符合各自契约，但会让人以为天空盒"丢了"）：
  1. `editor.py:1181` 新建场景 → 场景级置 None；
  2. `sceneio.py:1175/1177` 加载场景 → 键缺失/非法 → 置 None（**覆盖掉加载前内存里的天空盒**）；
  3. `sceneio.py:621` 每台相机加载时无条件 `cam.skybox = _apply_skybox(...)`（旧文件无键 → None，覆盖任何先前值）；
  4. `agent_commands.py:1010` `skybox_clear` → None。
  以上 1/2/3 都是"整场景替换"语义下的正确行为，不是 bug；真正的缺陷是相机级那条**根本不参与渲染**。

### Q4 新建场景"默认无天空盒"是有意设计还是从未实现？
**证据链**（全部列出）：
- 有意设计的证据：`editor.py:1180` 注释"C5：天空盒不随场景继承（默认无天空盒 = 清屏深色底）"（该行为是在 `6deccd2` 中作为 P0-4"防场景污染"主动加入的，提交信息明确写了）；`engine.py:309` `_skybox = None`；`开发进度与Unity对照.txt:98` "天空盒 ❌ 无（默认清屏色）"、`:206` "❌ 后处理 + 天空盒 —— gamma 是唯一固定后段, 默认清屏色"；`docs/design/功能补全5档施工路线图_20261017.md:97,328` 把天空盒列为"❌ 未开始"。
- "默认蓝"的证据：**零**。全仓 grep 无任何默认蓝色天空盒实现、无需求句、无设计文档（`docs/design/天空盒设计.md` 被 `docs/handoff/下一阶段工程路线分叉与施工交接.md:188` 引用，但**该文件不存在**）。
- 因此判定：**"不继承天空盒"是有意的（防止 A 场景的天空盒污染 B 场景）；"从没有任何默认蓝天空盒"是缺口**。人类说"默认应该是蓝色"属于**新增需求/需求变更**，不是回归。→ 见 §5 Q1。

### Q5 历史修复是否生效（逐个核对可达性）

| 提交 | 声称修的路径 | 当前代码里是否可达/生效 | 证据 |
|---|---|---|---|
| `6a3ad07` feat(skybox) | A1 全屏 quad 反投影 + B1 depth + C3 **场景级/相机覆盖** + 序列化/EAI/MCP | 场景级：**生效**（像素实测）；**相机覆盖：从不生效**（零消费者）；初版 VAO 绑 `in_uv` → KeyError 被吞 → 当时**永久禁用** | P-DIS-01、P-PRO-01、P-DIS-06 |
| `6deccd2` fix(render+editor) "天空盒一直黑的**根因**" | ① VAO 只绑 `in_pos`（改成 `'2f 2x'`）② 编译失败用 False 哨兵 ③ `_new_scene` 清天空盒 | ① **未生效且引入新黑屏原因**（`loom_render.py:62-67` 自证 `'2f 2x'` 会读到垃圾顶点）② 哨兵是**现存 P-PRO-02 的来源** ③ 生效（且是 Q4 的"有意设计"证据） | `git show 6deccd2`、探针 E |
| `0cca8b1` fix(skybox) "3 个独立 Bug" | ① hex 0-1 浮点被 int 成 0 ② 编辑器主 pass 没调 `_draw_skybox` ③ `2f 2x` 需独立 2f VBO | ① **生效**（`loom_cubemap.py:95-99`）；但同一提交新增的**数组**入口仍 `int()` 截断（P-PRO-03）② **生效**（`editor.py:2280` 在真实宿主路径上）③ **生效**（探针实测出图） | P-DIS-01/02、`loom_gui.py:263,603` |
| `ce5a791` version bump | — | 仅版本号 | `git show --stat` |

**结论**：本项目"修了但没生效"的 N1 模式在本模块**确实发生过两次**（`6a3ad07` 的 VAO、`6deccd2` 的 `2f 2x` —— 且后者还是"根因修复"），**第三次（`0cca8b1`）真实生效**。但**相机级覆盖从第一天起就没生效过**，是唯一"至今仍未生效"的遗留路径；另外 `scan_02_scene.md:876` 建议的"skybox 丢失时打印一次可见日志"在 beta5 仍未落地（`sceneio.py:576-577` 仍是裸 pass）。

---

## 7. 本轮报告自审（A6 checklist）

```
[x] 基准唯一：只引用本项目自身契约（§0.2 C1-C9），无外部标准
[x] 代码原样：所有引用带 文件:行号
[x] 路径完备：每条证伪链都有路径枚举表
[x] 预期/实际可对照：P-PROVED 均给出预期 vs 实际
[x] 命令可跑：§0.3 六个探针 + 输出原样贴出
[x] 措辞可审计：无"我认为/看起来/应该是/经验上"
[x] 跳过留痕：SK-01..SK-05 各有四类理由之一及出处
[x] 矛盾不忽略：P-CON-01 已查清"两条链都没错，是白盒契约冲突"
[x] P-UNKNOWN 不为 0（2 项）且说明了原因
[x] P-PROVED 不为 0（6 项），均有探针输出
[x] 只读：未改任何受跟踪文件；探针仅在 tests/_tmp（gitignore）
[x] 未启动 GUI 窗口；GL 走 moderngl 独立上下文 + 自建 FBO
```

**本轮等级：A6**（双向链完整 + 探针 + 跳过留痕 + 白盒层推广 + 人类裁决项封闭化）。差距项：VK 侧因无设备未能实测（P-UNK-03 UNVERIFIED），这是环境限制而非流程放水。
