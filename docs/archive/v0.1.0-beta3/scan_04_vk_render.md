# Vulkan 渲染器与 Vulkan UI 管线 扫描报告（scan_04）

> 只读审计 · 2026-11-07 · 范围：`Loom/vk_renderer.py`（1686 行，git 状态 M）、`Loom/vk_ui.py`（831 行，git 状态 ??，本轮首次入库无 HEAD 基线）
> 依据：`docs/audit/SCAN_PROTOCOL.md`；桌面《论如何正确的 vibe coding》《论如何使用AI自动化工具正确的判断AI给出的黑盒是否符合设计标准》

---

## 0. 范围与方法

### 0.1 被审对象

| 文件 | 行数 | git 状态 | 本轮 diff |
|---|---|---|---|
| `vk_renderer.py` | 1686 | `M` | `git diff HEAD`：+1066 / −47（HEAD 版本 627 行） |
| `vk_ui.py` | 831 | `??`（未跟踪） | 无 HEAD 基线，按"全新文件"审 |

### 0.2 白盒契约来源（判定基准清单，证真/证伪只引用这些）

1. `vk_renderer.py:1-13,28-47,79-82,670-679,1416-1420` 模块 docstring / 布局注释 / 常量注释。
2. `vk_ui.py:2-35,45-55,236-242,434-439,583-593,692-703` 模块 docstring / R2 契约 / 混合语义注释。
3. 同语义 GL 参考实现（双后端一致性基准）：
   `loom_render.py:120-273`（world canvas）、`loom_render.py:760-799`（帧序）、
   `loom_hud.py:68-73,108-154,177-212,249-254`（HUD 布局/文字/scissor/yaw）、
   `loom_texture.py:132-187`（wrap/filter 导入设置）、`loom_lighting.py:136-210,882-901`（8 灯打包/点光 6 面 VP）、
   `loom_shadow.py:45-106`（阴影贴图数量与面序）、`loom_transform.py:321-326`（世界旋转矩阵）。
4. `loom_ui.py:481-605,650-719,920-974`（dispatch_mouse / draw_all / Image）、`loom_material.py:36-38`（`_pbr` 默认 False）。
5. `vk_player.py:66-90,141-234,243-321`（交换链格式、输入回调、draw_frame 调用点、异常出口）。

### 0.3 跑过的命令（全部可复现）

```powershell
# 1) 通读 + diff
git diff --stat HEAD -- vk_renderer.py vk_ui.py     -> vk_renderer.py | 1113 +++--; vk_ui.py 无输出(未跟踪)
git show HEAD:Loom/vk_renderer.py | Measure-Object -Line   -> 627
# 2) 死符号 / 被忽略设置 / 无调用者
Select-String vk_renderer.py -Pattern '_VERT_FLOATS|_point_sampler|pbr_enabled|\.wrap|filter_mode'
Select-String vk_ui.py       -Pattern 'clear_cache'
Select-String (git show HEAD:Loom/vk_renderer.py) -Pattern 'params\.|L\.size'   -> 旧 shader 只读 params.x/.y
# 3) 离线探针（假 device，不碰 GPU；脚本在 %TEMP%\loom_scan04\，不写仓库）
$env:LOOM_NO_SAVE_MIGRATE='1'
python %TEMP%\loom_scan04\probe_renderer.py    # 空场景/法线回落/env 缓存/桶下标
python %TEMP%\loom_scan04\probe_regress.py     # 旧桶键 vs 新桶键 对照
python %TEMP%\loom_scan04\probe_ui.py          # 文本 LRU / bind group / 输入桥
python %TEMP%\loom_scan04\probe_layout.py      # 8 灯场景块逐灯偏移 / color 边界
```

未跑全量 `tests/run_all.py`（按任务约定）；未启动 GPU/窗口（本机有驱动死锁史，协议 §0.5）。

### 0.4 只扫不改自查

`git status --porcelain -- Loom/vk_renderer.py Loom/vk_ui.py` 运行前后一致（`M` / `??`，均为本轮开工前既有状态）；探针与临时文件全部落在 `%TEMP%\loom_scan04\`；未执行 `git add/commit`，未改动任何受跟踪文件。本报告为新增文件。

---

## 1. 粗筛清单（广度过筛，非判定；跳过项留痕）

### 1.1 疑似项（27）

| ID | 位置 | 标签 | 初步方向（一句话，指向代码事实） |
|---|---|---|---|
| P-01 | vk_renderer.py:1672（另 1592/1633） | BND-OFFBYONE / IFACE-PARTIAL | `rp.draw(nv, len(idxs), 0, idxs[0])` 把桶内实例当成连续区间，但实例行号由 `enumerate(vis)` 顺序写入 |
| P-02 | vk_renderer.py:1373-1374（调用点 1488） | BND-EMPTY | `_dir_light_vp` 对 `w[:, :3].min(axis=0)` 无空集保护，而它无条件对每盏平行光阴影调用 |
| P-03 | vk_renderer.py:1198,1201,1229-1231 | SEM-DEFAULT | 法线贴图上传失败回落 `_white_view`(255,255,255)，而 `_has_nrm` 仍为 True，着色器 `nm=(1,1,1)` |
| P-04 | vk_renderer.py:1278-1282,1321 | BND-RESOURCE | env cubemap 缓存键是 `id(cube)` 且不保留引用；`_env_cache` 无淘汰 |
| P-05 | vk_ui.py:524-525,459,470-479,528-531 | BND-RESOURCE | 文本 LRU 淘汰只 `popitem` 不 `release`，`_groups` 只增不减（GL 侧 `loom_hud.py:122` 有 `old_tex.release()`） |
| P-06 | vk_ui.py:763-792 | AUDIT-DEADCODE / SEM-SILENT | 用 `'_dragging' in repr(e)` 当分类器，吞掉任意同形 AttributeError 并清空 UI 按下态 |
| P-07 | vk_renderer.py:728-730 | IFACE-PRECOND | 单一样器固定 repeat+linear，`Texture.wrap/filter_mode` 从未被读取（全文件 grep 为空） |
| P-08 | vk_renderer.py:1425 | SEM-MISMATCH | 读 `self.pbr_enabled`，而全库唯一开关名是 `_pbr_enabled`（engine.py:465/512、loom_render.py:606） |
| P-09 | vk_renderer.py:1526 | IFACE-PRECOND | `getattr(m,'renderer',None).material if hasattr(...)`：属性存在但为 None 时抛 AttributeError |
| P-10 | vk_renderer.py:1442 | BND-OVERFLOW | `buf[b+4:b+7] = l.color` 要求长度恰为 3，`LightState.color=tuple(color)` 不校验长度 |
| P-11 | vk_renderer.py:1568 + 682-694 | BND-RESOURCE | 桶键并入贴图 guid，`_geo` 按整键缓存几何 → 同网格多份 VBO，且永不淘汰 |
| P-12 | vk_renderer.py:27,79,623,1212,724 | AUDIT-NOCHAIN | 死常量/死表达式/死采样器 + 注释与实现不符（160B 写成 208B/132B） |
| P-13 | vk_renderer.py:1575-1594 + 1545-1550 | SEM-MISMATCH | 只有 1 张 `_shadow_tex` 与 1 份 `inst_sha`，多盏平行光阴影时第 2 盏采样第 1 盏深度 |
| D-01 | vk_renderer.py:39-47,1412-1459 | IFACE-UNIT | 8 灯场景块 CPU/GPU 偏移是否对齐（重点项，先证伪） |
| D-02 | vk_renderer.py:1455 | SEM-MISMATCH | `params.z` 由 `l.size` 改成 `_POINT_FAR`，是否破坏 beam 截面 |
| D-03 | vk_renderer.py:1425,1530-1532 | SEM-DEFAULT | 新 PBR 路径是否改变旧场景默认外观 |
| D-04 | vk_renderer.py:1456-1458 | SEM-DEFAULT | range/spot 默认值是否与 GL 不同源 |
| D-05 | vk_ui.py:729-744 ↔ vk_player.py:189-200 | IFACE-UNIT | UI 左键键码 1/2/3 是否与 GLFW 0/1/2 错位 |
| D-06 | vk_ui.py:386-398 ↔ loom_hud.py:253 | AUDIT-ASYMMETRY | HUD 偏航角公式是否与 GL 不一致 |
| D-07 | vk_renderer.py:1025-1070 ↔ loom_render.py:154-160,225-236 | SEM-MISMATCH | 世界 Canvas billboard/旋转基是否与 GL 同源 |
| D-08 | vk_renderer.py:1396-1409 ↔ loom_shadow.py:50-62,84-92 | SEM-MISMATCH | 聚光灯是否像 GL 一样走 6 面 |
| D-09 | vk_renderer.py:1545-1546 | BND-OFFBYONE | `shape==(4,4)` 过滤是否漏掉/误取 VP |
| D-10 | vk_renderer.py:1206-1208 | IFACE-PRECOND | 贴图缓存以 guid 为键，guid 是否可能重复/为空 |
| D-11 | vk_ui.py:353-367 | IFACE-UNIT | scissor y 轴是否漏了 GL 的上下翻转 |
| D-12 | vk_renderer.py:1655-1663 ↔ loom_render.py:788-790 | SEM-MISMATCH | 天空盒从"几何后"改到"几何前"是否不等价 |
| U-01 | vk_renderer.py:1219-1232 | BND-RESOURCE | `_upload_tex` 只留 view 不留 texture 句柄 |
| U-02 | vk_renderer.py:1686 / 889-895 | BND-RESOURCE | 同帧对同一 swapchain texture 连开两个 render pass 的呈现语义 |

### 1.2 跳过登记（12，且理由必须属四类之一）

| ID | 位置 | 跳过理由（四类之一） | 证据 |
|---|---|---|---|
| S-01 | vk_renderer.py:423-458 `flatten_mesh` 的颜色解析 | 白盒契约明确声明 | 输入 `face_colors` 由 `Mesh.face_colors` 提供，格式 `#RRGGBB`（loom_model_gpu.py:152 同式 `_hex_rgba(c)`） |
| S-02 | vk_renderer.py:461-534 `world_matrices` 数学 | 已有回归测试覆盖 | tests/test_vk_camera_align.py（相机/父链对齐）+ tests/test_xform_sync.py；本轮未改该函数 |
| S-03 | vk_renderer.py:1099-1118 quad 三角化 | 已有 A/B 证据 | vk_ui.py:49-53 记录的 A/B（480x320，MAE=0.0036），且 GL `loom_render.py:244-256` 是同一组四角与 UV |
| S-04 | vk_ui.py:126-139 `surf_to_rgba` 行序 | 白盒契约明确声明 | 与 loom_hud.py:75-85 `_surf_to_tex` 的 transpose+倒序等价（注释已给出推导） |
| S-05 | vk_ui.py:91-98 `_c4` | 语言规范保证 | `color` 为 3/4 元组时 `len()` 分支完备；调用方（loom_ui 各元素）只传 3/4 元组 |
| S-06 | vk_ui.py:279-295 scissor 栈 | 已有回归测试覆盖 | tests/test_scrollbar.py / test_ui.py 覆盖嵌套裁剪；本轮未改该段 |
| S-07 | vk_renderer.py:1168-1186 `_gen_mips` | 已有 A/B 证据 | 注释 vk_renderer.py:255-256 记载翻转/不翻转实测（MAE 0.0004→0.0058） |
| S-08 | vk_renderer.py:1642-1646 深度纹理重建 | 语言规范保证 | 旧 tuple 被整体替换后无外部引用，wgpu-py `GPUObjectBase.__del__ -> _release`（site-packages/wgpu/_classes.py:617-619,629-645） |
| S-09 | vk_ui.py:534-556 `prepare` 顶点组装 | 语言规范保证 | `np.empty((total,8))` 与逐 op 切片长度自洽（total=sum(shape[0])） |
| S-10 | vk_renderer.py:861-896 `draw_ui` 的 `except Exception` | 白盒契约明确声明 | 注释 882 行声明"UI 异常不得拖垮 3D 帧"，且失败时 `has_content()==False` 不产生 pass |
| S-11 | vk_player.py:66-90 交换链 srgb | 已有回归测试覆盖 | test_render_api.py 锁后端选择；且 `fmt[:-5]` 失败会回退并打印（非静默） |
| S-12 | vk_ui.py:370-403 `hud_lines_from_driver` 三角形计数 | 白盒契约明确声明 | 注释 371-377 明示"可用子集"，且与 loom_hud.py:255 `total_faces` 同式（全部模型，非仅可见） |

---

## 2. 逐项裁决（先证伪，后证真；8 段链）

> 说明：所有探针均为"假 device + 假 ctx"离线驱动（不创建 GPU 设备），因此不影响仓库、不触碰驱动。以下输出的 ASCII 数值逐字保留，中文在 GBK 控制台会乱码，已按语义转录。

### P-01 · 桶内实例下标不连续 → 错误世界矩阵 + 漏画 · **P-PROVED · P1 · [REGRESSION]**

1. **位置**：vk_renderer.py:1672（主 pass）、1592（平行光阴影）、1633（点光阴影）。
2. **契约/预期**：`rp.draw(nv, len(idxs), 0, idxs[0])` 的 `first_instance` 必须指向该桶在实例缓冲中的**连续**区间；实例行号由 vk_renderer.py:1522-1542 `inst[i, ...] = worlds[i]`（i=`enumerate(vis)`）定义。GL 侧为每桶独立实例缓冲（loom_render.py:516 `_bucket_inst[key]`），不要求下标连续。
3. **路径枚举**：桶构造只有一处（1554-1572），键= `_mesh_key(m)+(albedo_guid, normal_guid, env_guid)`；`vis` 顺序 = `models` 过滤后原序（1484，无排序）。故桶内下标连续当且仅当同键物体在 `models` 中相邻。三种情况：(a) 全部同键→单桶→连续；(b) 每键各 1 个→`len(idxs)==1`→`first_instance` 恰为自身→正确；(c) 某键 ≥2 个且被其他键隔开→**不连续**。
4. **实际行为**：情况 (c) 下 `draw` 覆盖 `[idxs[0], idxs[0]+len(idxs))`，命中别的桶的实例行。
5. **差异**：预期覆盖 `{0,2}`，实际覆盖 `{0,1}`。
6. **触发条件**：同一 primitive/params 的两个物体之间夹了另一个桶的物体（含**同网格不同贴图**——本轮新键把它拆开）。
7. **验证**（`%TEMP%\loom_scan04\probe_regress.py`，场景 [cube+texA, cube+texB, cube+texA]）：
```
旧桶(HEAD, 只 primitive+params) = {"('cube', '{}')": [0, 1, 2]}
   旧 draw(nv, 3, 0, 0) 覆盖 instance[0..2]          <- 旧行为正确
新桶(工作区, +贴图 guid) draw 调用:
   draw(nv=3, n_inst=2, first_vertex=0, first_instance=0) 覆盖 instance[0..1]
   draw(nv=3, n_inst=1, first_vertex=0, first_instance=1) 覆盖 instance[1..1]
```
另一场景 [cube, sphere, cube]（primitive 不同）同样复现：`draw(3, 2, 0, 0)` + `draw(3, 1, 0, 1)`（probe_renderer.py 输出）。
8. **影响与等级**：第 3 个物体永久丢失；第 2 个位置被画成 cube（形体错 + 与自身重叠 z-fighting）。**P1（功能错误）**。本条为**本轮 diff 引入的回归**：HEAD 的同网格三连物体合成单桶且连续；本轮把贴图 guid 并入桶键（1568 行），使"同网格不同贴图"在旧版可正确渲染的场景被拆成交错桶。

### P-02 · 可见物体为空 + 平行光阴影 → 每帧 ValueError → 播放器进程退出 · **P-PROVED · P1**

1. **位置**：vk_renderer.py:1373-1374（`_dir_light_vp` 内 `w[:, :3].min(axis=0)`），调用点 1488 `_pack_light_vps(lights, vis, worlds)` 无 `if vis` 守卫。
2. **契约/预期**：空场景/全部隐藏是合法输入（`vis` 由 1484 行过滤可见性产生），渲染层应平稳出图。
3. **路径枚举**：`_pack_light_vps`（1388-1401）对 `lights[:8]` 逐盏：(a) directional+shadow → `_dir_light_vp`；(b) point/spot+shadow → `_point_light_vp6`（不读 vis）；(c) 其余 → 跳过。`_dir_light_vp` 内 `n=len(vis)`，`corners=np.empty((0,4))`，1369-1372 的循环 0 次，`w` 形状 (0,4)，1373 行 `w[:, :3].min(axis=0)` 必抛。唯一早退在 1354-1356（方向长度 <1e-6），与 vis 无关。
4. **实际行为**：抛 `ValueError: zero-size array to reduction operation minimum which has no identity`。
5. **差异**：预期渲染空场景；实际抛异常。
6. **触发条件**：场景里 `models` 为空或全部 `visible=False` **且** 至少一盏 `kind='directional', shadow=True` 的光。
7. **验证**（probe_renderer.py）：
```
EMPTY: ValueError: zero-size array to reduction operation minimum which has no identity
```
8. **影响与等级**：vk_player.py:311-315 `except BaseException: ... os._exit(1)` 把渲染异常升级为**进程退出**，用户看到的是播放器闪退。**P1**。该行在 HEAD 已存在，非本轮 regression。

### P-03 · 法线贴图上传失败回落"白"而非"平直法线" · **P-PROVED · P2**

1. **位置**：vk_renderer.py:1198/1201（`_nview = _upload_tex(ntex)`）、1229-1231（`except -> v = self._white_view`）、1559（`_has_nrm = bool(_nguid)`）、着色器 269-283。
2. **契约/预期**：模块注释 1191-1192："无法线贴图时回落 1x1 平直法线 (0.5,0.5,1)，采样恒等"（737-744 行确实建了 `_flat_nrm_tex`=(128,128,255)）。
3. **路径枚举**：`_upload_tex` 三个出口：(a) 缓存命中→返回缓存 view；(b) 上传成功→真实 view；(c) 任意异常→`_white_view`。`_tex_view` 在 (c) 下仍返回非空 `_nguid`，故 1559 判 True，着色器走 `bkt.x>0.5` 分支。静默失败无法从外部区分（仅 print）。
4. **实际行为**：`nm = textureSample(t_normal,...).rgb*2-1 = (1,1,1)`，`n = normalize(T+B+n)` —— 得到与真实法线无关的斜向量，光照整体错误（远亮于正确值）。
5. **差异**：预期"恒等"（n 不变），实际 n 被改写。
6. **触发条件**：法线贴图上传抛异常（显存不足、非法尺寸、`_rgba` 缺失）。生产路径 `Texture.from_file/from_rgba` 必带 `_rgba`，触发面窄（故定 P2 而非 P1）。
7. **验证**（probe_renderer.py，构造 `_rgba=None` 的法线贴图）：
```
NRM fallback: nguid='n1'  has_nrm=True  view_is_white=True  view_is_flat=False
```
8. **影响与等级**：失败时该材质光照错误而非退化为正确光照。**P2**。

### P-04 · env cubemap 缓存以 `id()` 为键且不留引用 → 复用旧 view · **P-PROVED · P2**

1. **位置**：vk_renderer.py:1278-1282（`key = id(cube)`，`self._env_cache[key] = out`），1321 存 `(view, maxlod)`。
2. **契约/预期**：缓存键必须唯一标识对象身份；已释放对象的 id 可被新对象复用（CPython 语义）。对照：`_upload_tex`（1206）用稳定 `guid`；`_world_targets`（940）额外存 `ent['canvas']` 并做 `is` 校验。
3. **路径枚举**：`_upload_cube_env` 三个出口：(a) 无 `_faces`→`(None,0.0)`；(b) 命中 `_env_cache[id(cube)]`→直接返回；(c) 未命中→建纹理/6 面 mip→写入。`_env_cache` 只增不减（全文件无 pop/clear）。
4. **实际行为**：旧 cube 被释放后，新 cube 若落在同一地址，命中 (b) 并拿到**另一份** cubemap 的 view。
5. **差异**：预期采样新 cube；实际采样旧 cube。
6. **触发条件**：编辑器里反复替换 `Material.env_map`（旧 Cubemap 失去引用），或场景重载后新建 Cubemap。
7. **验证**（probe_renderer.py）：
```
ENV: cache_keeps_cube_alive=False ; new_cube_same_id=True ; same_view=True ; cache_size=1
```
（`cache_keeps_cube_alive=False` = 缓存不保活→地址可复用；`same_view=True` = 不同 cubemap 拿到同一 view。）
8. **影响与等级**：贴错环境反射；且 `_env_cache` 无淘汰，每换一次 env 就多一份 6 面 mip 纹理。**P2**。本轮新增代码引入。

### P-05 · 文本 LRU 淘汰不释放纹理，`_groups` 无界增长 · **P-PROVED · P2**

1. **位置**：vk_ui.py:524-525（`while len>MAX: popitem(last=False)`，无 release）、459/470-479（`_groups[key]=(g,view)`，无删除）、528-531（`clear_cache` 是唯一清理入口）。
2. **契约/预期**：GL 同语义实现 `loom_hud.py:120-122` 明确 `old_tex.release()`；模块注释 vk_ui.py:43 "`_TEXT_CACHE_MAX = 400 # 与 engine._text_cache_max 一致`" 表明上限语义应与 GL 对齐。
3. **路径枚举**：`texture_for_text` 三出口（命中/新建/失败）；新建路径必 `self._text_cache[key]=tex` 并可能 `popitem`。`submit` 对每个 op 调 `group_for(tex)`（348），后者 (a) 命中 `_groups[id(view)]`→复用；(b) 未命中→新建并写入。`clear_cache` 全库零调用者。
4. **实际行为**：LRU 淘汰只断 `_text_cache` 的引用，`_groups` 仍持有 view（进而保活纹理），且条目数随"历史出现过多少条不同文本"单调增长。
5. **差异**：预期 GPU 纹理随淘汰释放、表有界；实际两者都无界。
6. **触发条件**：任何长时间运行、文本内容持续变化的 UI（FPS/坐标类 HUD 最典型）。
7. **验证**（probe_ui.py，把 `_TEXT_CACHE_MAX` 设 2，连续 6 条文本后各调一次 `group_for`）：
```
_text_cache 条数 = 2 (上限 2)
_groups 条数 = 6 (随"历史出现过的文本"单调增长)
```
8. **影响与等级**：显存/句柄随运行时长增长。**P2**。本轮新增文件引入。

### P-06 · UI 输入桥把任意含 `_dragging` 的 AttributeError 当已知缺陷吞掉 · **P-PROVED · P3**

1. **位置**：vk_ui.py:763-792（判定式 773 `if "_dragging" in repr(e)`，兜底 779-790）。
2. **契约/预期**：注释 767-772 声明该分支只用于 `loom_ui` 的已知缺陷"`self._dragging_elem._dragging = False if ... else None`"。
3. **路径枚举**：`dispatch_mouse` 抛异常 → (a) repr 含 `_dragging` → 打印"已知缺陷"+强制清 `_pressed_elem/_dragging_elem/_last_pointer_down`；(b) 不含 → 打印"UI dispatch_mouse 异常"。(a) 的判定只看子串，不校验异常来源/类型。
4. **实际行为**：任意元素 `on_mouse_up` 抛 `AttributeError("...'_dragging_xxx'")` 也会走 (a)，被当作已修缺陷，UI 按下态被强制清空。
5. **差异**：预期只兜底已知缺陷；实际误伤任意同形异常。
6. **触发条件**：(i) 第三方/脚本自定义 UI 元素在 `_emit_pointer('up')` 路径抛含该子串的 AttributeError；(ii) 更重要的事实：`loom_ui.py:597-603`（2026-11-07）已把原缺陷改成 `if self._dragging_elem is not None:`，**该分支对原目标已不可达**（死代码）。
7. **验证**（probe_ui.py，令 `dispatch_mouse` 抛 `AttributeError("'Text' object has no attribute '_dragging_old'")`）：
```
begin_frame 返回 = False | 未抛异常 = True
_pressed_elem = None | _dragging_elem = None | _last_pointer_down = None
```
8. **影响与等级**：误分类 + 静默清状态，掩盖真实 UI 异常。**P3**（可维护性/可观测性）。本轮新增文件引入。

### P-07 · 贴图 `wrap` / `filter_mode` 导入设置被 VK 忽略 · **P-PROVED · P2**

1. **位置**：vk_renderer.py:728-730（`_tex_sampler` 固定 `mag/min='linear'`、`address_mode_u/v='repeat'`），全文件无 `.wrap` / `filter_mode` 引用（grep 输出为空）。
2. **契约/预期**：`Texture` 带 `wrap`/`filter_mode` 导入设置（loom_texture.py:30-31,55-59），GL 在 `ensure_gl` 落实（161-179）。
3. **路径枚举**：`_tex_view`→`_upload_tex` 只拷像素与 mip，不读 wrap/filter；`_tex_group` 固定绑 `self._tex_sampler`。故所有材质贴图共用同一采样状态，无分支。
4. **实际行为**：`wrap='clamp'` 的纹理在 VK 侧按 repeat 采样；`filter_mode='point'` 被强制成 linear。
5. **差异**：导入设置静默失效。
6. **触发条件**：任何显式设置 clamp/point 的纹理（UI 图集、贴花、像素风）。
7. **验证**：
```
Select-String vk_renderer.py -Pattern '\.wrap|filter_mode'   -> 0 命中
Select-String vk_renderer.py -Pattern '_tex_sampler'         -> 728(创建) / 770 / 1266(仅绑定)
loom_texture.py:161-179                                       -> GL 侧按 wrap/filter 设置采样状态
```
8. **影响与等级**：双后端外观不一致（接缝/锐利度）。**P2**。本轮新增贴图路径引入。

### P-08 · PBR 全局开关读错属性名，`pbr_enabled=false` 在 VK 侧无效 · **P-PROVED · P2 · [REGRESSION]**

1. **位置**：vk_renderer.py:1425 `getattr(self, 'pbr_enabled', True)`。
2. **契约/预期**：engine.py:465 `self._pbr_enabled = bool(_s.get('pbr_enabled', True))`，loom_render.py:604-606 `u_pbr_mode = getattr(self,'_pbr_enabled', True)`；B7b 文档声明该开关是"排错后门"。
3. **路径枚举**：`VkRenderer.__init__`（550-584）不设任何 pbr 字段；全库 `pbr_enabled` 只出现在 1425 这一处读取（engine.py 侧是 `_pbr_enabled`，不会命中）。故 `getattr` 恒返回默认值 True，无分支可达 False。
4. **实际行为**：`sc.misc.x` 恒 1.0，PBR 永远全局开启。
5. **差异**：用户/排错开关在 VK 上无效。
6. **触发条件**：设置 `pbr_enabled: false` 且材质 `mat._pbr=True` → GL 走 Blinn-Phong，VK 走 PBR。
7. **验证**：
```
Select-String -Path *.py -Pattern 'pbr_enabled'  -> vk_renderer.py:1425 一处读取; engine.py 用 _pbr_enabled
Select-String vk_renderer.py -Pattern 'pbr_enabled =' -> 0 命中 (从未赋值)
```
8. **影响与等级**：同一工程切后端画面变化 + 排错后门失效。**P2**。本轮新增 PBR 路径引入（旧 VK 无 PBR）。

### P-09 · `renderer` 存在但为 None 时 AttributeError，回退分支不可达 · **P-PROVED · P3**

1. **位置**：vk_renderer.py:1526。
2. **契约/预期**：1536 行注释"测试桩/无 Material: 旧路径回退"声明存在无 renderer 的回退路径。
3. **路径枚举**：`hasattr(m,'renderer')` 为 True（属性存在，值为 None）→ 执行 `getattr(m,'renderer',None).material` → `None.material` 抛错；只有 `hasattr` 为 False 才走 else。
4. **实际行为**：抛 `AttributeError: 'NoneType' object has no attribute 'material'`。
5. **差异**：预期回退旧路径；实际崩溃。
6. **触发条件**：任何 `m.renderer = None` 的鸭子类型模型。生产 `GameObject.__init__` 恒赋 `MeshRendererComponent`（loom_game_object.py:46-48），全库无 `.renderer = None` 赋值 → 真实场景不可达。
7. **验证**（probe_renderer.py 首版 stub 即复现）：
```
File "vk_renderer.py", line 1526, in draw_frame
    mat = getattr(m, 'renderer', None).material if hasattr(m, 'renderer') else None
AttributeError: 'NoneType' object has no attribute 'material'
```
8. **影响与等级**：仅测试桩/扩展对象；回退分支形同虚设。**P3**。

### P-10 · 4 元组 `light.color` → `_pack_scene` ValueError · **P-PROVED · P3**

1. **位置**：vk_renderer.py:1442 `buf[b+4:b+7] = l.color`。
2. **契约/预期**：GL 侧只取前 3 分量（loom_lighting.py:139 `b['cols'][i] = (color[0],color[1],color[2])`），对长度 ≥3 均可用。
3. **路径枚举**：`LightState.color = tuple(color)`（loom_scene_entities.py:75）不校验长度；sceneio 走 `_f3`（3 元组），编辑器/MCP 走默认值 → 正常路径恒 3。脚本可直接赋值 4 元组。
4. **实际行为**：`ValueError: could not broadcast input array from shape (4,) into shape (3,)`。
5. **差异**：GL 容忍，VK 崩溃。
6. **触发条件**：脚本/插件把 RGBA 直接赋给 `light.color`。
7. **验证**（probe_layout.py）：
```
color 长度 4 -> ValueError: could not broadcast input array from shape (4,) into shape (3,)
```
8. **影响与等级**：渲染帧崩溃（→ vk_player os._exit）。触发面窄。**P3**。

### P-11 · 桶键并入贴图 guid → 同网格几何按贴图组合重复建 VBO，且 `_geo` 永不淘汰 · **P-PROVED · P3**

1. **位置**：vk_renderer.py:1568（`k = self._mesh_key(m) + (_tguid,_nguid,_eguid)`）→ 1589/1630/1668 `_ensure_geo_data(k, mesh, nm)`→ 682-694 `self._geo[key] = ent`。
2. **契约/预期**：`_mesh_key` 注释（1462-1467）声明桶键语义是"同几何共享缓冲 (P4 最小 draw)"；`_geo` 注释（683）"每帧只做一次 flatten"。
3. **路径枚举**：`_ensure_geo_data` 只按传入 key 命中，不区分"键里的贴图部分"与"几何部分"；`_geo` 无删除路径（无 clear/pop）。
4. **实际行为**：同一 mesh 配 N 种贴图 → N 份完全相同的顶点缓冲；换材质/换贴图后旧键常驻。
5. **差异**：几何复用度预期=1 份/网格；实际=1 份/(网格,贴图组合)。
6. **触发条件**：同网格多材质实例（换色/换图皮肤）。
7. **验证**：
```
Select-String vk_renderer.py -Pattern '_geo'   -> 682/693(_geo[key]=ent)/1589/1630/1668；无 pop/clear
```
8. **影响与等级**：显存随材质数线性膨胀。**P3**（本轮新键引入）。

### P-12 · 死常量 / 死表达式 / 死采样器 / 注释失真 · **P-PROVED · P3**

1. **位置**：vk_renderer.py:27（`_VERT_FLOATS`）、1212（`tex.ensure_gl(None) if False else None`）、724-725（`_point_sampler` 创建后无引用）、79（注释"每实例 208B"）、623（注释"实例(132B)"）。
2. **契约/预期**：注释与常量应反映实现（`_INST_BYTES=160`，28 行）。
3. **路径枚举**：grep 结果：`_VERT_FLOATS` 仅 27 行定义；`_point_sampler` 仅 724 行赋值；`if False else None` 恒为 None（死三元）。
4. **实际行为**：死符号常驻，注释误导 reader（208B/132B/160B 三种数字并存）。
5. **差异**：注释 vs 实现。
6. **触发条件**：任何按注释理解内存布局的后续修改。
7. **验证**：
```
Select-String vk_renderer.py -Pattern '_VERT_FLOATS'   -> 27
Select-String vk_renderer.py -Pattern '_point_sampler' -> 724
Select-String vk_renderer.py -Pattern 'if False'       -> 1212
```
8. **影响与等级**：**P3**（可维护性，AUDIT-NOCHAIN）。

### P-13 · 多盏平行光阴影只有 1 张贴图 / 1 份阴影实例缓冲 · **P-PROVED · P2**

1. **位置**：vk_renderer.py:1545-1550（`lvp = next(...)` 只取第一盏；`inst_sha` 只写这一份）、1575-1594（只渲染这一盏）、1426-1458（每盏灯都写自己的 `ortho`）。
2. **契约/预期**：`_pack_scene` 为每盏灯独立写 ortho 意味着着色器会按各自 VP 采样；GL 侧每盏灯独立 `_shadow_maps[guid]`（loom_shadow.py:47-61）与独立 sampler 单元（loom_lighting.py:171-180）。
3. **路径枚举**：`_light_vps` 可含多盏平行光 4x4 VP；`inst_sha` 只有一份（1550 写入）；阴影 pass 只为 `lvp` 渲染（1575）；`_shadow_view` 只有一张（703-709）。着色器对每盏 `shadow>0.5` 的灯都走 pcf（246-255）。
4. **实际行为**：第 2 盏灯用**第 1 盏灯的深度图** + 自己的 ortho 计算 uv/depth → 阴影位置错误。
5. **差异**：预期每盏灯独立阴影；实际串用。
6. **触发条件**：场景中 ≥2 盏 `kind='directional', shadow=True`。
7. **验证**：
```
Select-String vk_renderer.py -Pattern '_shadow_tex|_shadow_view' -> 708/709 单张；无 per-guid 贴图
Select-String vk_renderer.py -Pattern 'lvp' -> 1545(取第一个 4x4)/1547/1575/1637
loom_shadow.py:45-62 -> GL 每灯一份 sm['tex']
```
8. **影响与等级**：多平行光阴影错位。**P2**（非本轮 regression：HEAD 也是单张 `_shadow_tex`）。

---

### D-01 · 8 灯场景块 CPU/GPU 偏移错误？ · **P-DISPROVED**

1. 位置：vk_renderer.py:39-47（CPU 常量）、51-59（WGSL struct）、1421-1459（打包）。
2. 契约：注释 39/1413-1419 声明 `mvp[0..16) cam[16..20) cnt[20..24) cnt2[24..28) misc[28..32) L0..L7[32..)`，每灯 40 f32。
3. 路径枚举（WGSL uniform 布局，成员按 16B 对齐）：`mvp` 16 floats @0；`cam` @16；`cnt` @20；`cnt2` @24；`misc` @28；`LightX{4f32(16B), color, dir, pos, mat4, params, extra}` = 40 floats @32+i*40；总 352。CPU 侧 1427-1431 的 cnt/cnt2 分支（i<4→20+i，否则 24+(i-4)）、1433 `b = 32 + i*40`、1441/1442/1444/1446/1452/1455/1458 与上述逐段对应。
4. 实际：`_SCENE_FLOATS = 32 + 8*40 = 352`。
5. 差异：无。
6. 触发：8 灯全开。
7. 验证（probe_layout.py）：
```
len(buf) = 352  _SCENE_FLOATS = 352
8 灯逐灯偏移正确 = True
cnt = (1,1,1,1) cnt2 = (1,1,1,1)
misc = (1,0,0,0)
```
8. 判定：无 bug（该重点项证伪）。

### D-02 · `params.z` 由 `l.size` 改为 `_POINT_FAR` 破坏 beam？ · **P-DISPROVED**

1. 位置：vk_renderer.py:1455；旧值见 `git show HEAD:Loom/vk_renderer.py`。
3. 路径枚举：旧 shader 中 `L.params` 的全部读取点为 `pcf(uv, depth, L.params.x, L.params.y)`（旧文件唯一命中）。beam 截面尺寸在 CPU 侧 `_dir_light_vp`（1375-1378 `s = max(light.size, 0.01)`）就烘进 ortho；shader 只读 `L.ortho` 与 `L.shape`。故 `params.z` 旧版是**未被读取的填充位**。
4/5/6/7. 验证：`git show HEAD:... | Select-String 'params\.'` 输出只有 `L.params.x, L.params.y`。
8. 判定：无 bug。

### D-03 · 新增 PBR 改变旧场景默认外观？ · **P-DISPROVED**

1. 位置：vk_renderer.py:291（`use_pbr = misc.x && matv.w>0.5`）、1530-1532。
3. 路径枚举：`matv.w` 来自 `mat._pbr`，默认 False（loom_material.py:38）；`use_pbr` 需两者同时为真。故默认材质恒走 320-322 行旧分支，输出与 HEAD 相同代码路径。
7. 验证：`Select-String loom_material.py -Pattern '_pbr'` → `self._pbr = False`。
8. 判定：无 bug（默认值未变）。

### D-04 · range / spot 默认值与 GL 不同源？ · **P-DISPROVED**

1. 位置：vk_renderer.py:1456-1458。
3. 路径枚举：`getattr(l,'spot_inner_angle',30.0)` 与 loom_lighting.py:152-153 同默认值、同 `cos(radians())`；`getattr(l,'range',10.0)` 与 loom_lighting.py:148、LightState 默认 10.0（loom_scene_entities.py:59,83）一致。LightState 恒有这三个属性 → 默认值分支不可达。
8. 判定：无 bug。

### D-05 · UI 左键键码错位？ · **P-DISPROVED**

1. 位置：vk_ui.py:729-735 接收；vk_player.py:189-200 `_BTN = {LEFT:1, MIDDLE:2, RIGHT:3}`。
3. 路径枚举：唯一调用点 200 `ui_bridge.on_mouse_button(btn, down)`，btn 已转 1/2/3；loom_ui.py:488-489 `left_down = 1 in pressed`。
8. 判定：无 bug。

### D-06 · HUD 偏航角公式不一致？ · **P-DISPROVED**

1. 位置：vk_ui.py:386-387；loom_hud.py:253-254。
3. 路径枚举：两侧逐字符相同 `360 - math.degrees(yaw) % 360`（含 `%` 优先级导致的 360 边界行为）。
8. 判定：无 bug（差异仅在数据源 `driver.yaw` vs `camera_yaw`，已在注释 371-377 声明为"可用子集"）。

### D-07 · world Canvas billboard/旋转基与 GL 不同源？ · **P-DISPROVED**

1. 位置：vk_renderer.py:1025-1051、1053-1070、1072-1129；loom_render.py:154-160、225-236、244-256。
3. 路径枚举：(a) billboard：GL 取 `mat4_view_yaw_pitch(...)` 的 `V[0]/V[1]` 行；VK `_camera_billboard_basis` 走同一函数同一取法，且 vk_player.py:283-295 用同一函数算 `cam_basis` 显式传入（避免反解误差）。(b) 非 billboard：GL `world_rotation_matrix`（loom_transform.py:321-326）= `R_local @ R_parent` 递归；VK `_target_rotation_basis` 逐父右乘同一 `mat4_rotation`。(c) 尺寸/四角：`hw=cw*scale*0.5` 与 GL 234-247 同式。
8. 判定：无 bug（代码同源；本轮未跑 GPU A/B，见 U-02）。

### D-08 · 聚光灯阴影面数与 GL 不同？ · **P-DISPROVED**

1. 位置：vk_renderer.py:1396-1409；loom_shadow.py:45-62、84-92。
3. 路径枚举：GL `_ensure_shadow_map` 对 `kind != 'directional'` 一律建 6 张深度纹理（56-60），`_render_shadow_maps` 对非平行光用 `u_depth_kind=1`（84-92）；VK 对 `kind in ('point','spot')` 同样 6 面 + 距离/far（221-245）。面序 `+X,-X,+Y,-Y,+Z,-Z` 与 up 向量逐项相同（loom_lighting.py:899-900 vs vk_renderer.py:1407-1408）。
8. 判定：无 bug。（跨模块观察：GL 的 sampler 槽位分配 loom_lighting.py:174 用 `need = 6 if kind=='point' else 1`，对 spot 只绑 1 个单元却建 6 张图——属 GL 侧问题，转交 scan_01/02 范围。）

### D-09 · `shape==(4,4)` 过滤漏取 VP？ · **P-DISPROVED**

1. 位置：vk_renderer.py:1545-1546。
3. 路径枚举：`_light_vps` 的值只有两种：`_dir_light_vp` 返回的 `np.ndarray(4,4)`（1385-1386）与 `_point_light_vp6` 返回的 `list[6]`（1409）。`list` 无 `.shape` → `getattr` 返回 None；`ndarray` 返回 (4,4)。无双 4x4 元素、无其它类型。
8. 判定：无 bug（该过滤是必要的：HEAD 版本 `next(iter(...))` 在本轮加入点光列表后会拿到 list）。

### D-10 · 贴图缓存 guid 冲突？ · **P-DISPROVED**

1. 位置：vk_renderer.py:1206-1208、1232。
3. 路径枚举：`Texture.guid = guid or uuid.uuid4().hex`（loom_texture.py:47）→ 恒非空且唯一；`Cubemap.guid` 同（loom_cubemap.py:29）。仅当调用方显式传重复 guid 才冲突，属上游契约。
8. 判定：无 bug（真实缺陷在 P-04 的 `id()` 键，不在 guid 键）。

### D-11 · scissor y 轴漏翻转？ · **P-DISPROVED**

1. 位置：vk_ui.py:353-367；loom_hud.py:204-212。
3. 路径枚举：GL 把"左上原点"矩形转成 GL 的左下原点 `(int(x), int(height-(y+h)), int(w), int(h))`；VK 的 `set_scissor_rect` 参数本身就是**左上原点**（WebGPU 约定），故不需要翻转。两侧输入语义相同（loom_ui 传入 sr 为左上原点）。
8. 判定：无 bug（取整方式 int vs round 最多 1px，属 P3 级差异，未单独计数）。

### D-12 · 天空盒从"几何后"改到"几何前"不等价？ · **P-DISPROVED**

1. 位置：vk_renderer.py:1655-1663；loom_render.py:788-790。
3. 路径枚举：GL 在几何后画天空，`depth_func='<='` + `depth_mask=False`（loom_render.py:105-113）只在 depth==1 处着色；VK 在几何前用 `depth_compare='always'`、`depth_write=False`（801-802）铺满，再由几何覆盖。主管线无混合（`targets:[{format}]`，无 blend 字段，600/630 行）→ 主 pass 全不透明，后画的几何必然覆盖先画的天空；天空只画一次、无 overdraw。
8. 判定：无 bug（在不透明主 pass 前提下视觉等价）。

---

### U-01 · `_upload_tex` 只留 view 不留 texture 句柄 · **P-UNKNOWN**

- **已尝试**：(1) 读 wgpu-py 源码：`GPUObjectBase.__del__ -> _release()`（site-packages/wgpu/_classes.py:617-619,629-645），native 后端 `_release` 走 `wgpuTextureRelease`（_api.py:1049/1059/1384）；(2) 对照同文件其它路径：`_sky_tex`（823）与 `_world_targets`（940）都保留了 texture 对象，只有 `_upload_tex`（1219-1232）在函数返回后丢弃本地 `t`，缓存里只有 `t.create_view()`。
- **为什么定不了**：wgpu-native 的 `wgpuTextureRelease` 是否因仍有 `TextureView`/bind group 引用而保活底层纹理，属 native 所有权语义，Python 层看不到；本机有驱动死锁史，未开 GPU 设备验证。
- **还缺什么**：一次 GPU 探针——建 1x1 红纹理→取 view→`del tex; gc.collect()`→建 bind group→`textureLoad` 读回像素，比较 `(255,0,0)` 与 `(0,0,0)`。若读回黑，则所有材质贴图在真实 GPU 上都可能失效（P0）；若读回红，则只是所有权风格不一致（P3）。

### U-02 · 同帧对同一 swapchain texture 连开两个 render pass · **P-UNKNOWN**

- **已尝试**：代码层面主 pass（1648-1682）与 UI pass（1686→889-895）顺序 submit，第二个 pass `load_op=load` 且无深度附件；wgpu 规范允许同 texture 多次 pass。vk_player.py:311-315 的 `except BaseException -> os._exit(1)` 说明作者对该路径的稳定性没有把握。
- **为什么定不了**：rendercanvas 的 `get_current_texture()` 在"回调内多次 submit"时的呈现语义属窗口后端行为，需真实窗口实测；本机驱动有绑定组死锁史，协议禁止起 GUI。
- **还缺什么**：`vk_player --frames 8` 冒烟 + 抓 wgpu 验证层错误输出（若出现 texture 正在使用/present 竞态，则升级为 P1）。

---

## 3. 统计

| 判定 | 数量 | 编号 |
|---|---|---|
| P-PROVED | 13 | P-01 ~ P-13 |
| P-DISPROVED | 12 | D-01 ~ D-12 |
| P-UNKNOWN | 2 | U-01, U-02 |
| P-CONTRADICTION | 0 | — |
| 粗筛跳过（留痕） | 12 | S-01 ~ S-12 |

等级分布（P-PROVED）：P0 = 0；P1 = 2（P-01, P-02）；P2 = 6（P-03,04,05,07,08,13）；P3 = 5（P-06,09,10,11,12）。

[REGRESSION]（本轮 diff 引入或放大）：**P-01（放大后成为新回归）**、**P-08（新增路径，开关失效）**；另 P-03/P-04/P-05/P-06/P-07/P-11 为本轮新增代码/新文件引入的缺陷（NEW-CODE），一并按回归登记。

P-CONTRADICTION = 0 的说明：初筛时 P-01（`first_instance` 失效）与 D-09（`shape` 过滤必要）表面上都成立（若过滤漏取 VP 则平行光阴影全黑，与"P-01 只影响主 pass"冲突）。逐条枚举 `_light_vps` 取值类型后确认二者作用域不相交，矛盾消解，无双成立链。

---

## 4. 修复建议排序（只给方向，不含代码）

**P0**：无。

**P1**
1. **P-01（先修）**：实例行号必须与桶一一对应。两条路线：(a) 维持单实例缓冲，但按桶重排实例行并在 `draw` 前用 `idxs` 的回写表把 `world/nm/sat/color` 搬到连续区间；(b) 与 GL 同构，每桶独立实例缓冲（`_bucket_inst[key]`），`first_instance` 恒 0。修完必须补一条"同 primitive 交错三物体"的回归用例（现有 tests 无此覆盖）。
2. **P-02**：`_pack_light_vps` 在 `vis` 为空时短路，或 `_dir_light_vp` 对空集返回 None。补"空场景 + 平行光阴影"冒烟。

**P2**
3. **P-08**：统一开关名为 `_pbr_enabled`（或由 vk_player 显式注入），并加"设置关 PBR 后 `sc.misc.x==0`"的断言。
4. **P-07**：按 `Texture.wrap/filter_mode` 分桶缓存 sampler（当前是全局单采样器）。
5. **P-04**：缓存键改用 `cube.guid`（与 `_upload_tex` 同风格）并加容量上限/淘汰。
6. **P-05**：LRU 淘汰时释放纹理（对齐 loom_hud.py:120-122），`_groups` 随 `_text_cache` 同步清理；或把 bind group 挂到 `UiTexture` 上随纹理一起淘汰。
7. **P-03**：法线贴图失败回落 `_flat_nrm_view`（而不是白纹理），并在 `_has_nrm` 判定里带上"上传是否成功"。
8. **P-13**：多平行光阴影要么按 guid 分贴图（GL 同构），要么在 `_pack_scene` 里只给第一盏写 ortho+shadow 标志（其余置 0），避免用错图。

**P3**
9. **P-06**：删除该兜底分支（原缺陷已在 loom_ui.py:597-603 修复），或把判定收紧到"异常类型 + 具体消息模板"。
10. **P-09/P-10**：`renderer` 取值改成嵌套 `getattr`；`light.color` 取前 3 分量（与 GL 同式）。
11. **P-11**：几何缓存键与材质键解耦（`_ensure_geo_data` 只用 `_mesh_key`）。
12. **P-12**：清死符号/死三元/死采样器，统一实例步长注释为 160B。

---

## 5. 需要人类裁决的封闭问题（最多 3 条，均为"A 还是 B"）

**Q1（架构路线，对应 P-01）**：Vulkan 实例缓冲怎么组织？
- A. 单缓冲 + 按桶重排（改动集中在 `draw_frame` 的实例写入段，draw 次数保持每桶 1 次，内存最省）——代价：每帧多一次 `idxs` 散射写，且排序表要跟着桶缓存一起失效。
- B. 每桶独立缓冲（与 GL `_bucket_inst` 完全同构，`first_instance` 恒 0）——代价：缓冲数量随桶数增长，但语义最简单、与 GL 逐行可对照。
> 需要人类选择：**A 还是 B**（本报告不替工程路线拍板）。

**Q2（验收基线，对应 P-13）**：本轮是否接受"VK 只支持 1 盏点/聚光阴影 + 1 盏平行光阴影"作为已知限制？
- A. 接受为已知限制（写入双后端一致性验收基线，VK 侧灯数>1 时不宣称阴影一致）。
- B. 不接受，须在合并前做到 per-guid 阴影贴图（工作量约等于 GL `_shadow_maps` 全套搬迁）。
> 需要人类选择：**A 还是 B**。

**Q3（像素等价口径，对应 vk_ui.py:45-55 自声明）**：`STROKE_PIXEL_EQUIVALENT=False`（Shape 描边 1px 覆盖差、alpha 描边被钉成不透明）是否正式纳入"允许非逐像素等价"清单？
- A. 纳入（保留现状 + 契约声明，A/B 仅作参考）。
- B. 不纳入（要求 VK 描边走几何膨胀并复刻 GL 关闭混合的 alpha 语义，代价是新增分支与 A/B 重跑）。
> 需要人类选择：**A 还是 B**。

---

### 附：本轮已复跑的验证输出原文（供第三方独立核对）

```
$ python %TEMP%\loom_scan04\probe_renderer.py
NRM fallback: nguid='n1'  has_nrm=True  view_is_white=True  view_is_flat=False
EMPTY: ValueError: zero-size array to reduction operation minimum which has no identity
ENV: cache_keeps_cube_alive=False ; new_cube_same_id=True ; same_view=True ; cache_size=1
BUCKETS keys = [('cube', '{}'), ('sphere', '{}')]
MAIN draw (nv, n_inst, first_vertex, first_instance):
    (3, 2, 0, 0) 覆盖 instance[0..1]
    (3, 1, 0, 1) 覆盖 instance[1..1]

$ python %TEMP%\loom_scan04\probe_regress.py
旧桶(HEAD, 只 primitive+params) = {"('cube', '{}')": [0, 1, 2]}
   旧 draw(nv, 3, 0, 0) 覆盖 instance[0..2]
新桶(工作区, +贴图 guid) draw 调用:
   draw(nv=3, n_inst=2, first_vertex=0, first_instance=0) 覆盖 instance[0..1]
   draw(nv=3, n_inst=1, first_vertex=0, first_instance=1) 覆盖 instance[1..1]

$ python %TEMP%\loom_scan04\probe_ui.py
_text_cache 条数 = 2 (上限 2)
_groups 条数 = 6 (随"历史出现过的文本"单调增长)
begin_frame 返回 = False | 未抛异常 = True
_pressed_elem = None | _dragging_elem = None | _last_pointer_down = None

$ python %TEMP%\loom_scan04\probe_layout.py
len(buf) = 352  _SCENE_FLOATS = 352
8 灯逐灯偏移正确 = True
cnt = (1,1,1,1) cnt2 = (1,1,1,1)
misc = (1,0,0,0)
color 长度 4 -> ValueError: could not broadcast input array from shape (4,) into shape (3,)
```
