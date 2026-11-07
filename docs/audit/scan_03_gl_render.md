# OpenGL 渲染主链 扫描报告（scan_03_gl_render）

> 审计日期：2026-11-07 | **只读审计**（未修改任何受跟踪源码/测试/文档；未 git add/commit）
> 依据：`docs/audit/SCAN_PROTOCOL.md`（三阶段 / 8 段链 / 四象限）+ 桌面两份方法论
> 代码根：`D:/my-project - 副本/Loom(py源代码-工作区)/Loom`（git 根为上一级 `Loom(py源代码-工作区)`）
> 环境：Windows 10，Python 3.12.10，moderngl 5.12.0，GL_NVIDIA GeForce GTX 1050 Ti / 3.3.0；全程 `LOOM_NO_SAVE_MIGRATE=1`，未跑 `tests/run_all.py`，未启动任何 GUI 长窗口

---

## 0. 范围与方法

### 0.1 文件清单（行数为 read 工具实测）

| 文件 | 行数 | 在渲染主链中的职责 |
|---|---|---|
| loom_render.py | 851 | RenderMixin：主 pass 帧准备（实例化批/视锥剔除/桶脏闸）、主 pass 绘制、天空盒、World Space UI、帧循环 `run()` |
| loom_lighting.py | 902 | LightingMixin：光源管理、`_upload_lights`（uniform + 阴影贴图槽位）、AABB/场景界、平行光/点光 VP、`_parallel_shadow_and_collision`、`_compute_light_vps`、pipeline.dll 路径 |
| loom_shaders.py | 442 | 全部 GLSL 常量：主 pass（Blinn-Phong + PBR + 8 光源 + beam 掩码 + PCF 阴影）、阴影深度 pass、天空盒、HUD/线/WorldUI |
| loom_model_gpu.py | 357 | ModelGpuMixin：材质库、`_mesh_key` 桶键、`_flatten_mesh`、桶级 VBO/实例缓冲/VAO 构建与释放、增删物体/清场/换场景 |
| loom_shadow.py | 107 | ShadowMixin：阴影 depth program、阴影贴图缓存（平行光 1 张 / 点光 6 面）、每帧深度 pass |

合计 **2659 行**。跨模块只读引用（仅作调用方/契约证据，不作本报告裁决对象）：
engine.py（`_logic_prep` 阴影 VP 缓存）、loom_scene_entities.py（`LightState`/`up_vector`）、loom_material.py（外观代计数器）、
loom_transform.py（`compute_world_matrices`/`compute_render_matrices`）、pipeline_glue.py（C 侧适配器）、
core_components/pipeline/loom_pipeline.c（C 侧 VP 算法）、vk_renderer.py（Vulkan 对侧语义）、editor.py / agent_commands.py（可达入口）。

### 0.2 读过的判定基准

1. `docs/audit/SCAN_PROTOCOL.md`（67 行，全读）
2. `C:/Users/Administrator/Desktop/论如何正确的vibe coding.md`（614 行，全读）
3. `C:/Users/Administrator/Desktop/论如何使用AI自动化工具正确的判断AI给出的黑盒是否符合设计标准.md`（735 行，全读）
4. 被审对象自身的白盒契约（代码注释/文档句，逐条引用在 §2 的"1. 判定基准"）：
   - `loom_lighting.py:13-14`（"纯搬家，双分支逐位保留，不得借重构删/改任何分支"）
   - `loom_lighting.py:90-94`（`_upload_lights` docstring：阴影贴图从单元 1 起绑定）
   - `loom_lighting.py:171`（"阴影贴图槽位: 平行光 1 张 / 点光 6 面, 平铺进 u_shadow_maps"）
   - `loom_lighting.py:753`（"★本方法不改任何数值语义"）、`loom_lighting.py:824-825`（缓存键"任一变化 -> 签名变"）
   - `loom_render.py:371`（"保守: 球心到每个内侧平面距离 >= -radius 即可能可见 (不误剔)"）
   - `loom_render.py:413-414`（"用上帧 self._vp (相机静止帧精确; 移动帧保守外扩不误剔)"）
   - `loom_render.py:398-400`（"桶/实例/绘制消费渲染矩阵(插值); _frame_world 保持逻辑位姿 (碰撞/阴影共享源, R3)"）
   - `loom_shaders.py:144-146`（"面索引…须与 mat4_view_forward 视图 NDC 同号 (已核对, 勿改符号)"）、`loom_shaders.py:162`（点光深度 = 距离/far）
   - `loom_shadow.py:34`（`_shadow_point_far = 30.0`）
   - `core_components/pipeline/loom_pipeline.c:163`（`#define PIPE_POINT_FAR 1.0e4  /* engine._shadow_point_far 默认值 */`）
   - `pipeline_glue.py:131-135`（P-11：`aabb_rows is None → return None`）

### 0.3 跑过的命令（定向探针，全部在临时目录，仓库内零写入）

```text
# git 事实
git -C <proj> diff HEAD --numstat -- Loom/loom_render.py Loom/loom_lighting.py Loom/loom_shaders.py Loom/loom_model_gpu.py Loom/loom_shadow.py
  -> 17  0  Loom/loom_lighting.py        （本模块唯一未提交改动）
git -C <proj> diff HEAD --stat -- Loom/vk_renderer.py Loom/vk_player.py Loom/scene_driver.py Loom/loom_lighting.py
  -> scene_driver 489+ / vk_player 224+ / vk_renderer 1113+ / loom_lighting 17+   （同一批"Vulkan 对齐"未提交改动）
git -C <proj> status --porcelain       （审计前后一致；本模块仅既有 " M Loom/loom_lighting.py"）
git -C <proj> blame -L 170,182 / -L 789,806 / -L 823,838 -- Loom/loom_lighting.py

# 既有回归测试（只跑与本模块相关的 4 个，未跑 run_all）
python tests/test_lighting.py        -> 总结果: ALL PASS（12 项，含"三面亮度两两不同/不爆白/点光衰减/饱和度"）
python tests/test_light_occlusion.py -> 总结果: ALL PASS（含 mat4_ortho near->0 far->1、LightState roll/spot 字段、v8 序列化）
python tests/test_lod.py             -> ALL PASS（距离/屏幕占比/bias/无 LOD 不变）
python tests/test_render_api.py      -> 总结果: ALL PASS（GL 不用 wgpu / Vk 不用 moderngl 的后端边界）

# 定向探针（源码见附录 A，均在 %TEMP%\loom_scan03\）
python probe_slots2.py      # P-01/P-02 阴影槽位与纹理单元归属
python probe_vpcache.py     # P-03 编辑态 VP 缓存键 vs roll
python probe_cull2.py       # P-04 视锥剔除半径 vs 实例缩放
python probe_pipeline2.py   # P-05 C/Python VP 路径耗时 + P-17 守卫是否短路 C
python probe_pointfar.py    # P-06 真实离屏 GL：far=30 vs far=1e4 深度图 A/B
python probe_beam.py        # P-07 beam 光每盏重算 AABB 计数
python probe_faces.py       # P-06/D-03 立方体面序：着色器 UV 公式 vs _point_light_vp 投影
python probe_guard.py       # P-05 谁覆盖"无行表"路径（P-17 还是 P-11）
```

所有"实测输出"均为上述命令原样粘贴（Windows 代码页导致的少数乱码不影响数值）。

### 0.4 特别审查：`git diff HEAD -- <本模块>` 逐条判定

本模块 5 个文件里 **只有 loom_lighting.py 有未提交改动，17 行全为新增**，其余 4 个文件与 HEAD 逐字节相同：

```diff
diff --git a/Loom/loom_lighting.py b/Loom/loom_lighting.py
` -786,6 +786,23 ` class LightingMixin:
`+        # 2026-11-06 P-17 修复: C 侧 one_point_light_vp 把远平面**硬编码**为
`+        # PIPE_POINT_FAR = 1.0e4 (loom_pipeline.c:163, 注释称"engine 默认值"),
`+        # 而引擎实际默认是 _shadow_point_far = 30.0 (loom_shadow.py:34),
`+        # 主 pass 采样时也用 30.0 归一 (u_light_far)。两者不一致 → 点光阴影
`+        # 深度比较失效。官方件不改 (改动需重编 DLL), 这里让"含点光阴影"的
`+        # 帧走 Python VP (_point_light_vp 用的是 engine 自己的 far), 保证与
`+        # 着色器 uniform 同源。
`+        if any(l.kind == "point" for l in lights):
`+            return False
`+        # 2026-11-06 P-11 修复: C 侧 loom_pipeline_light_vps 对 aabb_rows == NULL
`+        # 是硬性 LOOM_ERR_PARAM (见 loom_pipeline.c 入口校验), 而这里在"场景里
`+        # 只有点光/光束光 (need_bounds=False)"时 rows 仍是 None —— 于是每帧硬抛
`+        # "pipeline.dll 调用失败 rc=-2"。编辑器加一个点光源就崩渲染帧即此因。
`+        # 这些光源的 VP 根本不需要场景 AABB, 交下面 Python 路径算即可
`+        # (_point_light_vp / _dir_light_vp 均已就绪, 且 B2 未删该回退)。
`+        if rows is None:
`+            return False
```

逐条判定：

| diff 片段 | 判定 | 依据 |
|---|---|---|
| 新增守卫 A：`if any(l.kind == "point" for l in lights): return False`（行 796-797） | **[REGRESSION] R-01（= P-05）** | ①它声称的根因被真实离屏渲染证伪（P-06：far 不参与点光深度比较，far=30 与 1e4 的深度图逐位相同）；②代价实测：3 盏平行光 + 2001 体，C 路径 0.785 ms/帧 → Python 回退 7.221 ms/帧，**+6.44 ms/帧**（120 FPS 预算 8.33 ms 的 77%）；③同一"修复"口径不覆盖 `kind=="spot"`（spot 仍走 C，far 仍是 1e4）→ 自相矛盾 |
| 新增守卫 B：`if rows is None: return False`（行 804-805） | **正确修复（非回归）** | 未提交的 `pipeline_glue.py:131-135` 也使 `aabb_rows is None` 直接返回 None；实测 `probe_guard.py`：只有 spot/point 阴影且无 AABB 行表时本守卫命中（返回 False），C 不再被以 NULL 调用（旧行为 = rc=-2 → `RuntimeError` → 渲染帧中断）。守卫 B 与 glue 守卫语义重复但不冲突，**它单独就足以避免崩溃**，故守卫 A 可整段删除 |
| 两段注释文字 | 部分错误 | P-17 注释中"两者不一致 → 点光阴影深度比较失效"被 P-06 证伪；P-11 注释与 `loom_pipeline.c:254` 入口校验一致，成立 |

**结论：本模块 [REGRESSION] 共 1 条（R-01），0 条为"Vulkan 对侧语义变化未同步到 GL"**——GL 侧本批改动只有上述两段守卫，其余 4 文件未动（`--numstat` 只有一行）。

---

## 1. 粗筛清单（含跳过项留痕）

### 1.1 疑似项（六元组，逐项对应 §2 的裁决）

| ID | 位置 | 标签 | 初步方向（一句话，指向代码事实） | 粗筛证据 |
|---|---|---|---|---|
| P-01 | loom_lighting.py:174,177-179 | SEM-MISMATCH / BND-RESOURCE | `need = 6 if light.kind == 'point' else 1` 对 **spot** 只记 1 个槽位，但 `_ensure_shadow_map` 给 spot 建 6 张纹理、着色器按 6 面采样 → `sampler_units[unit-1+k]` 越界 | 行 174/177-179 与 loom_shadow.py:56-60 对读 |
| P-02 | 同上（同根因） | SEM-MISMATCH / IFACE-ERROR | spot 只 `unit += 1`，后续阴影光把单元 2..7 重新绑定 → spot 的 1..5 面采到"下一盏灯"的深度图 | 行 176-180 的单元推进 vs 着色器 `point_shadow(slot+k)` |
| P-03 | loom_lighting.py:823-838 | SEM-MISMATCH / AUDIT-DOCIMPL | 编辑态 VP 缓存键不含 `roll`，但 `up_vector()` 依赖 roll → 改"倾斜"后阴影 VP 不刷新 | 键元组 827-836 无 roll；loom_scene_entities.py:132-138 用 roll |
| P-04 | loom_render.py:533-542 | SEM-OVERFIT / BND-OVERFLOW | 剔除半径取网格局部 `max‖v‖`，不乘实例缩放；世界行里却含缩放 → 放大物体在屏幕边缘被误剔 | 行 538-542；`_frustum_keep` 只吃标量 radius |
| P-05 | loom_lighting.py:796-797（未提交 diff） | SEM-DEFAULT / OVERFIT-TESTENV | "有阴影点光就整帧放弃 C 路径"的守卫，代价与收益未量化 | `git diff HEAD`：17 行新增之一 |
| P-06 | loom_lighting.py:789-795（注释） | AUDIT-DOCIMPL | P-17 声称 C 的 far=1e4 会让"点光阴影深度比较失效"——但点光深度由 `length/u_light_far` 写入与比较，与 VP 的 far 无关 | loom_shaders.py:404 与 162；loom_shadow.py:89 |
| P-07 | loom_lighting.py:879-881 + 674-675 | AUDIT-ASYMMETRY | `need_bounds=False`（只有 beam/点光）时 `vis_aabbs=None`，而 `_dir_light_vp` 在 aabbs=None 时自查全场景 AABB → 每盏 beam 光各算一遍 | 两处代码对读 |
| P-08 | loom_render.py:417-424 vs 769-772 | BND-CONCURRENCY / AUDIT-DOCIMPL | 剔除用"上帧 `_vp`"，而 `_prepare_bucket_frame`（755）在 `_vp` 更新（772）之前；注释称"保守外扩不误剔" | 行号顺序；且相机停住后 sig 命中会**持久**保留错误剔除集 |
| P-09 | loom_render.py:398-400 vs 547/587 | AUDIT-DOCIMPL | 注释称阴影共享逻辑位姿 `_frame_world`，实际 `inst['sha']` 写入的是插值矩阵 `fw32(_render_world)` | 400 行注释 vs 547/587 写入源 |
| P-10 | vk_renderer.py:1425（对侧） | AUDIT-ASYMMETRY / IFACE-ERROR | VK 读 `self.pbr_enabled`，全库只有 `engine._pbr_enabled` → GL 的 `pbr_enabled=false` 排错后门在 VK 播放器里静默失效 | vk_renderer.py:1425 vs engine.py:465 / loom_render.py:606 |
| D-02 | loom_model_gpu.py:91-117 | SEM-OVERFIT | 桶键缓存 `_bucket_key` 会不会因换网格/换材质贴图而失配 | 行 100-108（3 元组）与 109-117（贴图/PBR 分量） |
| D-03 | loom_shaders.py:147-170 + loom_lighting.py:894-902 | IFACE-UNIT | 立方体阴影"面索引/UV 公式"与 `_point_light_vp` 的面序是否同号 | 着色器注释声明"已核对" |
| U-01 | loom_render.py:219 | BND-RESOURCE | World Space UI 离屏渲染后把 viewport 恢复成 `self.width/height`（逻辑值），而非 FBO 实际像素尺寸 | 行 203-206（用 cur_size）与 219（用 old_w/old_h） |

### 1.2 跳过登记表（四类可审计理由之一；跳过的同样留痕）

| 编号 | 位置 | 跳过理由类别 | 具体依据 |
|---|---|---|---|
| S-01 | loom_shaders.py:95-127（GGX/Smith/Schlick/pbr_light） | 白盒契约明确声明 | 注释逐式给出 Cook-Torrance 公式（95-101 GGX、102-110 Smith、111-113 Schlick），实现与注释公式逐行同式，且输入全部来自 uniform/插值，无外部状态 |
| S-02 | loom_shaders.py:313-371（HUD/WorldUI/Line 着色器） | 语言规范保证 | 三段均为无分支直通（`texture*color` / `in_color`），唯一状态量是 sampler 与 uniform，标准 GLSL 语义；无边界/资源分配 |
| S-03 | loom_shaders.py:411-442（天空盒反投影） | 已有回归测试覆盖 + 白盒契约 | 反投影数学注释（435-437）与 `_draw_skybox` 的 `inv(VP)` 上传约定逐位对应；`tests/test_cubemap.py` 覆盖 cubemap 数据层，`0cca8b1` 已修复"2f 2x 导致黑屏"并留回归 |
| S-04 | loom_model_gpu.py:119-162（`_flatten_mesh` 颜色/UV 分支） | 已有回归测试覆盖 | `tests/test_texture.py` 断言 cube 24 顶点/UV 角点、sphere/plane UV 对齐、材质贴图槽；`tests/test_mesh_import.py` 覆盖导入法线优先 |
| S-05 | loom_model_gpu.py:198-229（实例缓冲生长/VAO 重建） | 白盒契约明确声明 | 注释 199-202 明确"容量变化 → 重建 VAO（VAO 绑定缓冲对象，换缓冲必须重建）"，`"4f 4f 4f 4f 4f 4f/i"` 与 `_VERT_SRC` 的 6 个 per-instance 属性一一对应（loom_shaders.py:21-23） |
| S-06 | loom_shadow.py:36-43（`_release_shadow_map` 的 `except: pass`） | 白盒契约明确声明 | 释放失败即 GL 对象已失效（重复 release）；此处静默是刻意幂等（`remove_light` 可重入），不隐藏业务错误 |
| S-07 | loom_render.py:302-353（`_update_lod` 距离/屏幕占比） | 已有回归测试覆盖 | `tests/test_lod.py` 断言距离模式、屏幕占比、bias 语义、无 LOD 物体不变（本次实跑 ALL PASS） |
| S-08 | loom_model_gpu.py:54,74-78（材质库孤儿增长） | 已有报告覆盖 | **已由 scan_02_scene P-03 裁决（PROVED/P1）**，本报告只登记去重，不重复计数 |
| S-09 | loom_lighting.py:698-745（`_parallel_shadow_and_collision` 派发/缓存） | 已有报告覆盖 | **scan_01_core P-02 已裁决**（小场景 split 碰撞对为空），本报告只登记去重 |
| S-10 | loom_model_gpu.py:260-357（增删物体/清场/换场景） | 已有报告覆盖 | 材质孤儿部分见 S-08；其余（脚本 on_destroy、桶共享解引用、prep 缓存失效）与 scan_01 的 `remove_model`/`load_scene` 条目同源，已裁决 |

**粗筛剔除的"绝对对"**：`matlib` 的矩阵函数、`numpy` 的切片语义、`moderngl` 的 `Framebuffer.use()` 自动设 viewport 等，均属语言/框架自身声明（四类理由第 1/4 类），不作为疑似项。

---

## 2. 逐项裁决

### 2.0 四象限汇总

| ID | 反手（证伪） | 正手（证真） | 判定 | 等级 |
|---|---|---|---|---|
| P-01 | 失败（存在可达路径：spot 且 unit≥11） | 成功（IndexError@179，真实代码） | **P-PROVED** | **P0**（渲染帧/主循环中断） |
| P-02 | 失败（存在"spot 非最后一盏"的绑定顺序） | 成功（单元 2..6 被下一盏灯覆盖） | **P-PROVED** | **P1** |
| P-03 | 失败（roll 不在签名，但影响 up_vector→VP） | 成功（签名相同、\|ΔVP\|=0.176） | **P-PROVED** | **P1** |
| P-04 | 失败（半径不乘缩放，放大实例被误剔） | 成功（8 顶点中 2 个在视锥内仍被剔） | **P-PROVED** | **P1** |
| P-05 | 失败（守卫确实短路 C） | 成功（+6.44 ms/帧；且前提被 P-06 证伪） | **P-PROVED**（[REGRESSION]） | **P2**（性能） |
| P-06 | 成功（深度写入/比较都不含 VP 的 far） | 失败（真实离屏 A/B 深度图逐位相同） | **P-DISPROVED** | —（推翻 R-01 的依据） |
| P-07 | 失败（beam 光走到 aabbs=None 的现算分支） | 成功（3 盏 beam → 3 次 AABB） | **P-PROVED** | **P2** |
| P-08 | 失败（`_vp` 在使用后才更新，且 sig 命中会持久化） | 成功（代码顺序 + 缓存语义） | **P-PROVED** | **P2** |
| P-09 | 失败（写入源是 fw32 而非 _frame_world） | 成功（注释与写入源不一致） | **P-PROVED** | **P3** |
| P-10 | 失败（VK 侧无任何 pbr_enabled 赋值点） | 成功（属性名不一致，getattr 恒 True） | **P-PROVED** | **P2** |
| D-02 | —（证伪成功） | 失败（所有写入口都失效缓存） | **P-DISPROVED** | — |
| D-03 | —（证伪成功） | 失败（9/9 面一致，\|d\|≤1.1e-16） | **P-DISPROVED** | — |
| U-01 | 失败（仅当逻辑尺寸≠FBO 像素尺寸时才错） | 失败（无 HiDPI 宿主可测） | **P-UNKNOWN** | 待裁决 |

---

### 2.1 P-01 · 聚光灯阴影只记 1 个槽位 → `sampler_units` 越界 IndexError

**1) 判定基准**
- `loom_lighting.py:171`："阴影贴图槽位: **平行光 1 张 / 点光 6 面**, 平铺进 u_shadow_maps"。
- `loom_lighting.py:90-92`：`_upload_lights` 负责把阴影贴图绑到纹理单元并设置 sampler 数组。
- `loom_shadow.py:45-62`：`_ensure_shadow_map` 对"非 directional"（含 spot）建 **6 张** 2D depth 纹理。
- `loom_shaders.py:258-260`：`if (u_shadow_slot[i] >= 0) … if (u_light_kind[i] > 0.5) point_shadow(u_shadow_slot[i], …)`；`point_shadow`（147-170）按 slot..slot+5 采 6 面。

**2) 代码证据（原样）**

```python
# loom_lighting.py:172-180
if light.shadow:
    sm = self._shadow_maps.get(light.guid)
    need = 6 if light.kind == 'point' else 1        # ← spot 走 else，只记 1
    if sm is not None and unit + need - 1 <= 15:
        b['slots'][i] = unit - 1     # 数组下标 = 物理单元号 - 1
        for k, tex in enumerate(sm['tex']):          # ← spot 的 tex 有 6 张
            tex.use(unit + k)
            sampler_units[unit - 1 + k] = unit + k   # ← 越界点
        unit += need
# loom_lighting.py:114
'sampler_units': [0] * 16,
```

**3) 证伪链（路径枚举）**

`_upload_lights` 的槽位段只有 4 条进入路径，按 `light.kind × 前置灯数` 枚举：

| 路径 | 进入条件 | 会否命中越界？ |
|---|---|---|
| A | `light.shadow == False` | 否（跳过） |
| B | `sm is None`（该光无阴影贴图） | 否（跳过） |
| C | 守卫 `unit + need - 1 > 15` | 否（跳过） |
| D | 守卫通过 | **对 spot：`unit-1+5` = `unit+4` 可 ≥16** |

`unit` 的推进规则：directional +1、point +6、spot +1（← 本条缺陷）。可达值枚举：1（空）→2（1 平行光）→7（1 点光）→8→13（2 点光）→14→15。故 **unit=13 时 spot 的守卫 13+1-1=13 ≤ 15 通过**，随后 k=5 时 `sampler_units[12+5]=sampler_units[17]` → 越界（列表长度 16）。
路径 D 真实可达；C 不成立；B 不成立（spot 必然建了 6 张）；A 不成立（`add_light` 默认 `shadow=True`，loom_lighting.py:46 / loom_scene_entities.py:58）。
→ **证伪失败**。

**4) 预期**：spot 与 point 同为 6 面立方阴影时，应预留 6 个槽位（`need=6`）并使 `unit+6-1<=15`，绝不越界。

**5) 实际**：`need=1`；`unit≥11` 时内层循环写到 `sampler_units[16..]`。

**6) 差异**：多写了 5 个 sampler 数组元素 / 少记了 5 个槽位 → Python 层 IndexError；即使未越界（unit≤10）也会把 6 张纹理绑到本不属于它的单元（见 P-02）。

**7) 可复现验证**

```text
cd %TEMP%\loom_scan03
set LOOM_NO_SAVE_MIGRATE=1
set PYTHONPATH=D:\my-project - 副本\Loom(py源代码-工作区)\Loom
python probe_slots2.py
  ==============================================================================
  S4 [point(shadow), point(shadow), spot(shadow)]
    !! EXCEPTION: IndexError list assignment index out of range
    at loom_lighting.py:179  sampler_units[unit - 1 + k] = unit + k
```

**8) 判定与影响**：**P-PROVED / P0**。调用链 `render() → _upload_lights()`（loom_render.py:778）无 try/except；GLFW 主循环 `run()`（loom_render.py:823-835）也无 try/except → 异常逃出主循环 = 引擎退出（Qt PlayerApp 每 tick 有 try/except（loom_player_window.py:152），但会变成"每帧黑屏 + 前 3 次打印异常"）。触发条件：**场景里同时存在 ≥2 盏投影点光 + ≥1 盏投影聚光灯**（unit=13）。同一根因的另一症状见 P-02。

---

### 2.2 P-02 · 聚光灯的 5 个面采到"下一盏灯"的深度图

**1) 判定基准**：同 P-01 的 171 行契约（每盏灯的面必须连续铺在自己 slot 起始的 6 个单元上）+ `loom_shaders.py:164-169`（`u_shadow_maps[slot+k]` 恒取 slot 起 6 个）。

**2) 代码证据**：同 P-01 的 172-180；另有 `loom_shaders.py:164-169`：

```glsl
if (face == 0) return pcf_shadow(u_shadow_maps[slot],     uv, ...);
if (face == 1) return pcf_shadow(u_shadow_maps[slot + 1], uv, ...);
... return              pcf_shadow(u_shadow_maps[slot + 5], uv, ...);
```

**3) 证伪链（路径/顺序枚举）**：spot 的 6 张纹理绑到 `unit..unit+5`，但 `unit` 只前进 1。枚举"下一盏阴影光"的三种类型：

| spot 之后的灯 | 其绑定的单元范围 | 对 spot 的 sampler_units[slot+1..slot+5] 的影响 |
|---|---|---|
| point（+6） | `u+1..u+6` | 覆盖 5 项 → spot 面 1..5 全指向 point 的 6 张 depth |
| directional（+1） | `u+1` | 覆盖 1 项（面 1）；其余 4 项仍指向 spot 自己的单元 |
| 无（spot 是最后一盏） | — | 不覆盖 → 正确（probe S5） |

三种情况里两种错，且都在 `unit` 推进规则之内；无任何代码校验 spot 之后是否还有灯。
→ **证伪失败**。

**4) 预期**：spot 的 6 个面各自采样自己的 6 张深度图。
**5) 实际**：面 1..5 采样到后一盏灯的 2D/立方深度图（分辨率、朝向、深度归一都不同）。
**6) 差异**：阴影遮挡关系错乱（亮区出现阴影、暗区漏光），仅 spot 的第一面正确。

**7) 可复现验证**

```text
python probe_slots2.py
  S2 [spot(shadow), point(shadow)]
    spot        slot= 0 units_sampled=[1, 2, 3, 4, 5, 6]
       expect textures=['spo[0]', 'spo[1]', 'spo[2]', 'spo[3]', 'spo[4]', 'spo[5]']
       actual textures=['spo[0]', 'poi[0]', 'poi[1]', 'poi[2]', 'poi[3]', 'poi[4]']   <<< WRONG TEXTURE
  S3 [spot(shadow), dir(shadow)]
    spot  actual textures=['spo[0]', 'dir[0]', 'spo[2]', 'spo[3]', 'spo[4]', 'spo[5]']   <<< WRONG TEXTURE
  S6 [dir(shadow), spot(shadow), point(shadow)]
    spot  actual textures=['spo[0]', 'poi[0]', 'poi[1]', 'poi[2]', 'poi[3]', 'poi[4]']   <<< WRONG TEXTURE
  S1 [dir(shadow), spot(shadow)] / S5 [spot 单独]
    -> OK（spot 在最后且 unit 足够时正确）
```

**8) 判定与影响**：**P-PROVED / P1**。与 P-01 同一行根因（`need`），但症状独立（不崩溃、静默错阴影），故单列；修复方向见 §4（改 `need` + 守卫改用 6，并在超限时跳过整盏灯的 6 张绑定）。

---

### 2.3 P-03 · 编辑态阴影 VP 缓存键漏掉 `roll` → 改"倾斜"后阴影不刷新

**1) 判定基准**：`loom_lighting.py:824-825`："缓存键 … **光源参数指纹。任一变化 -> 签名变**"；`loom_scene_entities.py:118-139`：`up_vector()` 由 d 与 **roll** 共同决定；`loom_lighting.py:672`：`up = light.up_vector()` 参与 `mat4_view_forward`。

**2) 代码证据**

```python
# loom_lighting.py:827-838
lsig = tuple(
    (l.guid, l.kind, bool(getattr(l, 'shadow', False)),
     getattr(l, 'mode', 'full'), getattr(l, 'shape', 'circle'),
     float(getattr(l, 'size', 0.0)),
     ((l.position.x, l.position.y, l.position.z) ...),
     (l.direction.x, l.direction.y, l.direction.z),   # ← 只有 direction，没有 roll
     (l.color[0], l.color[1], l.color[2]), float(l.intensity))
    for l in self.lights[:8])
return (id(fw), getattr(self, '_struct_gen', 0), GameObject._appearance_gen, lsig)
# loom_scene_entities.py:132-138
r = math.radians(self.roll); c = math.cos(r); sn = -math.sin(r)
... return Point3D(up_ref*c + cross*sn, ...)
```

**3) 证伪链（路径枚举）**：可能的失效入口有 4 个：
① `id(fw)` — roll 不影响世界矩阵 → 不变；
② `_struct_gen` — 改 light.roll 不经 GameObject/Transform → 不变；
③ `GameObject._appearance_gen` — 只由 Material/GameObject setter bump → 不变；
④ `lsig` — 元组里无 roll，direction/position/color/intensity 不变 → 不变。
故四路全部不变；而 `up_vector()` 变 → VP 变。无其它失效源（load_scene 等不适用）。
→ **证伪失败**。

**4) 预期**：改 roll 后签名变化一次，下一帧重算 VP。
**5) 实际**：签名不变 → `_compute_light_vps` 在 `loom_lighting.py:852-854` 直接 `return self._light_vps` → 阴影贴图与 beam 截面矩阵继续用旧基向量。
**6) 差异**：VP 数值不同（实测 0.176），阴影方向/光束截面方位滞后。

**7) 可复现验证**

```text
python probe_vpcache.py
  sig(roll=0)   = (1784037826768, 7, 0, (('9ff0...', 'directional', True, 'full', 'circle', 5.0,
                    (0, 10, 0), (0.4394, -0.6428, 0.6275), (1.0,1.0,1.0), 1.0),))
  sig(roll=30)  = (...完全同上...)
  vp(roll=0)  diag = [-0.17447 -0.21453  0.0619   1.     ]
  vp(roll=30) diag = [-0.11606 -0.15366  0.0619   1.     ]
  signature equal      : True
  max |vp1 - vp0|      : 0.1761926082801517
  => cache would REUSE stale VP: True
```

**8) 判定与影响**：**P-PROVED / P1**。仅在 `is_playing == False`（编辑器）走本缓存（`loom_lighting.py:851`）；可达入口：EAI 命令 `light_set roll=...`（agent_commands.py:1498-1516 直接 `setattr`，不 bump 任何计数器）或检查器"倾斜"滑条。播放态不受影响（走 `_logic_prep`，按逻辑帧重算）。用户感知："改了倾斜，阴影没动，直到我再改一次位置/角度"。

---

### 2.4 P-04 · 视锥剔除半径漏乘实例缩放 → 放大物体在屏幕边缘整桶消失

**1) 判定基准**：`loom_render.py:371`："保守: 球心到每个内侧平面距离 >= -radius 即可能可见 (**不误剔**)"；`loom_render.py:378-382`：`_frustum_keep(world_rows, planes, radius)` 的 radius 是**世界空间**球半径。

**2) 代码证据**

```python
# loom_render.py:530-542
if planes is not None and k > 1:
    np.take(fw32, idxs, axis=0, out=g[:k], mode='clip')
    r = mr.get(key)
    if r is None:
        _mesh = self.models[idxs[0]].mesh
        _v = np.asarray(_mesh.vertices, dtype=np.float64)
        r = float(np.sqrt((_v * _v).sum(axis=1)).max()) if len(_v) else 1.0
        mr[key] = r                                   # ← 网格局部半径，无缩放
    keep = self._frustum_keep(g[:k], planes, r)        # ← 世界行 g 含缩放
```

**3) 证伪链（路径枚举）**：object 的缩放只存在于世界矩阵行（`world_rows[:,3,:3]` 是平移）。"不误剔"要成立必须 `r_world >= 真实包围球半径`。三条可能路径：
① 缩放恒为 1 → 成立（但 `loom_game_object.py:117-121` 明确支持任意 scale）；
② 剔除阈值本来保守 → 不成立：平面距离判据 `dist >= -radius`，radius 就是唯一余量；
③ 半径来自世界空间 AABB → 不成立：代码取 `mesh.vertices` 局部值。
→ **证伪失败**。

**4) 预期**：放大 12 倍的立方体在屏幕边缘仍部分可见时应保留。
**5) 实际**：`_frustum_keep` 用 0.866 当半径，判为不可见 → `_main_bucket_n[key] = 0` → `_draw_main_buckets` 跳过整桶。
**6) 差异**：8 个世界顶点中 2 个在视锥内，仍被剔除。

**7) 可复现验证**

```text
python probe_cull2.py
  center y=8 z=10          scale=12   visible_vertices=2/8  _frustum_keep(unscaled r=0.866)=False <<< FALSE CULL
      world-space radius should be 10.39
```

（同一探针里 scale=20 / center x=11.5 因"顶点刚好差一点"未触发，说明触发带确实存在且与缩放/位置相关。）

**8) 判定与影响**：**P-PROVED / P1**。触发前置：同一桶（同 `_mesh_key`）≥2 个实例（`k > 1` 才走剔除，行 530）+ 其中一个实例 scale>1 且中心落在视锥外、真实体积仍侵入视锥（近屏幕边缘）。表现：整个桶突然消失/闪回。修复方向：半径取 `max\|v\| * max(scale)`，或改用世界空间 AABB 检验。

---

### 2.5 P-05 · [REGRESSION] "有投影点光就整帧放弃 C 路径"的守卫

**1) 判定基准**
- `loom_lighting.py:13-14`："pipeline.dll 路径 … **纯搬家，双分支逐位保留**"（C 路径是既定路径，回退需真实理由）。
- `loom_lighting.py:753`："★本方法**不改任何数值语义**"。
- 该守卫自带注释（789-795）声称的理由 —— 由 P-06 单独裁决。

**2) 代码证据**

```python
# loom_lighting.py:756-809（节选）
lights = [l for l in self.lights[:8] if l.shadow]
...
need_bounds = any(l.kind == 'directional' and l.mode == 'full' for l in lights)
if need_bounds and rows is None: ...
if any(l.kind == "point" for l in lights):      # ← 未提交新增
    return False
if rows is None:                                 # ← 未提交新增（P-11，正确）
    return False
vis_idx = [i for i, m in enumerate(self.models) if m.visible] if need_bounds else None
res = pg.light_vps(rows, lights, vis_idx=vis_idx)
```

**3) 证伪链（路径枚举）**：要证明"守卫无害且必要"，需同时满足 〔① 前置分支必然让它只在必要时命中 ② 命中后语义等价 ③ 代价可忽略〕：
① 不成立：`lights` 只含 shadow 光；只要该帧有 1 盏 shadow=True 的 point 光就命中，与场景其余光无关；
② 不成立：命中后 `_compute_light_vps` 走 Python（`loom_lighting.py:862-890`），对**全部**光重新算（含平行光）；C 与 Python 在平行光上同式（`loom_pipeline.c:165-224` vs `_dir_light_vp`），语义等价但成本不等价；
③ 不成立：实测 +6.44 ms/帧（2001 体、3 平行光）。
另：守卫的"理由"（C 的 far=1e4）对 spot 不生效 —— `any(l.kind == "point")` 不匹配 `"spot"`，同一帧 spot 仍走 C。
→ **证伪失败**（守卫既非无害也非必要）。

**4) 预期**：点光阴影帧仍用 C 计算 VP（far 不参与深度比较，见 P-06）；只在"无法提供全量 AABB 行表"时才回退。
**5) 实际**：整帧回退 Python，且理由不成立。
**6) 差异**：多耗 CPU；回退路径在播放态每逻辑帧重复执行。

**7) 可复现验证**

```text
python probe_pipeline2.py
  pipeline.dll assembly: ok
  C path   : ok=True lights=3  0.7853 ms/frame
  Python   : ok=True lights=3  7.2212 ms/frame
  delta    : +6.4359 ms/frame
  with point light    : return=False C_calls=0 vps_filled=0
  without point light : return=True  C_calls=1 vps_filled=3
```

**8) 判定与影响**：**P-PROVED / P2（[REGRESSION] R-01）**。120 FPS 帧预算 8.33 ms，本项在 2001 体的合成场景占 77%；500 体场景按线性估计约 +1.6 ms/帧。**它并非崩溃修复**：崩溃路径由守卫 B（P-11）单独覆盖（`probe_guard.py`：只有 spot/point 阴影且无行表时守卫 B 命中返回 False）。

---

### 2.6 P-06 · P-17 声称的根因（C 的 far=1e4 破坏点光深度比较）不成立

**1) 判定基准**（该守卫自身注释，789-795）："`PIPE_POINT_FAR = 1.0e4` … 引擎实际默认 30.0 … 两者不一致 → 点光阴影**深度比较失效**"。

**2) 代码证据**

```glsl
// loom_shaders.py:393-408  _SHADOW_FRAG（点光/聚光分支）
if (u_depth_kind > 0) gl_FragDepth = clamp(length(v_world_pos - u_light_pos) / u_light_far, 0.0, 1.0);
// loom_shaders.py:162  主 pass 采样
float depth = length(rd) / u_light_far;
```

```python
# loom_shadow.py:89  写深度时用的 far
self._shadow_prog['u_light_far'].value = self._shadow_point_far     # = 30.0（:34）
# loom_lighting.py:208  采样时用的 far
('u_light_far', self._shadow_point_far),
# loom_lighting.py:898  点光 VP 的 far（只影响裁剪，不影响 gl_FragDepth）
proj = mat4_perspective(np, math.radians(90.0), 1.0, 0.05, self._shadow_point_far)
```

**3) 证伪链（路径枚举）**：点光阴影的数值链只有 3 个量参与判定：写入的 `gl_FragDepth`、清屏值 1.0、片元的 `length/u_light_far`。来源枚举：
① 写入深度 ← `_SHADOW_FRAG` 两分支：`u_depth_kind>0`（点/聚光）用 `length/u_light_far`，`u_depth_kind==0`（平行光）用 `gl_FragCoord.z` —— **均不读 VP**（VP 只进 `gl_Position`）；
② `u_light_far` 的赋值点全库只有 `loom_shadow.py:89`（30.0）与 `loom_lighting.py:208`（30.0）—— **不从 VP 派生**；
③ VP 的 far 只影响裁剪空间 z，而 z 被子句 ① 的 `gl_FragDepth` 覆盖；xy 与 far 无关（透视矩阵 xy 只依赖 fov/aspect/near）；
另：far=30 会把 30 单位外的遮挡体裁掉（深度保持清屏 1.0），far=1e4 则让它们写入 `clamp(d/30,0,1)=1.0` —— 与清屏值相同，`GL_LESS` 下 1.0 对 1.0 不通过 → 落盘值相同。
→ 全部路径都不含"VP far 进入深度比较"这一步，**证伪成功**。

**4–6) 预期/实际/差异**：预期（按注释）far 不同 → 深度比较失效；实际按上述链应完全一致。

**7) 可复现验证（真实离屏 GL）**

```text
python probe_pointfar.py
  world point [20.  3.  2.] dist 20.32
    far=30   ndc xyz = [ 0.1      -0.15      0.999165]
    far=1e4  ndc xyz = [ 0.1      -0.15      0.997505]
    |dxy| = 0.0  (only z differs)
  shadow program linked; includes u_depth_kind/u_light_far/u_light_vp
  instances (distance from light): [20.0, 40.0]
  depth(far=30)  min=0.65001 max=1.00000  pixels<1: 36
  depth(far=1e4) min=0.65001 max=1.00000  pixels<1: 36
  max |depth(far=30) - depth(far=1e4)| = 0.0
  identical depth maps: True
```

（用 `moderngl.create_standalone_context()` + 自建 depth FBO，直接复用 `_SHADOW_VERT/_SHADOW_FRAG`；两盏立方体距光源 20 与 40，后者在 far=30 被裁、在 far=1e4 写入 1.0，落盘深度仍逐像素相同。）

**8) 判定与影响**：**P-DISPROVED**。P-17 注释不成立 → R-01（P-05）失去唯一依据；建议连同注释一起删除守卫 A，保留守卫 B。**注意**：这不等于"点光阴影从没坏过"——本次另查明真实故障是 P-01/P-02（槽位/纹理单元）与"无行表时 C 崩溃"（P-11）；修好这两处后 C 路径对点光可用。

---

### 2.7 P-07 · 只有 beam 光时，每盏光各重算一遍全场景 AABB

**1) 判定基准**：`loom_lighting.py:840-844`：`_compute_light_vps` "每帧一次：全部阴影光源的 view-proj … **消除旧代码'每帧对同一光源算两遍包围盒'的重复开销**"。

**2) 代码证据**

```python
# loom_lighting.py:862-881
need_bounds = any(l.kind == 'directional' and l.shadow and l.mode == 'full' for l in self.lights[:8])
if need_bounds: ... vis_aabbs = ...; vis_rows = ...
else:
    vis_aabbs = None          # ← beam/点光场景走这里
    vis_rows = None
for light in self.lights[:8]:
    if light.kind == 'directional':
        vp = self._dir_light_vp(light, vis_aabbs, vis_rows)   # aabbs=None
# loom_lighting.py:674-675
if aabbs is None:
    aabbs = self._model_aabbs_par(self.models, self._frame_world)   # ← 每盏各算一次
```

**3) 证伪链（路径枚举）**：`_dir_light_vp` 的 aabbs 来源只有两条：调用方传入（非 None）或内部自算（None）。`_compute_light_vps` 在 `need_bounds=False` 时恒传 None；`mode=='beam'` 不满足 need_bounds 的第三个条件（`mode == 'full'`）。故"beam 光 + 无 full 平行光"必然每盏各算一次 AABB；"共享"只在 need_bounds=True 时成立。
→ **证伪失败**。

**4) 预期**：3 盏 beam 光共享 1 次 AABB（=1 次 `_model_aabbs_par`）。
**5) 实际**：3 次。
**6) 差异**：n × 全场景顶点变换（n=500 时每遍 ~1 ms 量级，播放态每逻辑帧执行）。

**7) 可复现验证**

```text
python probe_beam.py
  1 beam light, aabbs=None                   _model_aabbs_par calls = 1   vps = 1
  3 beam lights, aabbs=None                  _model_aabbs_par calls = 3   vps = 3
  1 full directional, aabbs=None             _model_aabbs_par calls = 1   vps = 1
  3 full directional, aabbs=None             _model_aabbs_par calls = 1   vps = 3
  3 full directional, aabbs precomputed      _model_aabbs_par calls = 0   vps = 3
```

**8) 判定与影响**：**P-PROVED / P2**（纯性能）。修复方向：在 else 分支先算一次 `vis_aabbs/vis_rows` 再循环（beam 的 near/far 只依赖可见光包围盒，语义不变）。

---

### 2.8 P-08 · 视锥剔除用"上一帧"的 VP，且相机停住后错误剔除集被缓存

**1) 判定基准**：`loom_render.py:413-414`："用上帧 self._vp（相机静止帧精确; **移动帧保守外扩不误剔**）"；`loom_render.py:371`："不误剔"。

**2) 代码证据**

```python
# loom_render.py:417-424（_prepare_bucket_frame，render() 第 755 行调用）
vp = getattr(self, '_vp', None)
if vp is not None:
    planes = self._frustum_planes(vp)          # ← 上一帧的 _vp
...
# loom_render.py:769-772（同一个 render()，在 755 之后）
V = mat4_view_yaw_pitch(...); P = mat4_perspective(...)
self._vp = V @ P                               # ← 本帧的 _vp 此时才更新
```

**3) 证伪链（路径枚举）**：
- 相机只平移不转：旧视锥与新视锥平行，多数方向上旧视锥是更大包络 —— 注释的"保守外扩"**部分**成立；
- 相机绕轴旋转：旧平面与新平面不平行，旧视锥与新视锥互不包含 → 存在"新视锥内、旧视锥外"的对象 → 被剔（**误剔**）；
- 相机停止后：`sig` 含 `_cam_sig`（437-444），相机值不变 → `bk == sig` → 行 445-446 `return`，`_main_bucket_n` 保留上一帧的错误剔除集 → 误剔**持续**到下一次相机/结构/位姿变化。
三条路径里两条不成立 → **证伪失败**。

**4) 预期**：剔除要么用本帧 VP，要么用"上帧 ∪ 本帧"的保守包络。
**5) 实际**：用上帧 VP，且结果被脏闸缓存。
**6) 差异**：快速转视角后屏幕边缘整桶物体消失，直到再动一次相机。

**7) 可复现验证**：代码顺序即证据（755 先于 772）；脏闸缓存语义见 425-447。未做像素级 A/B：需要"第 N 帧转 30°、第 N+1 帧静止"的受控帧序列并读取 `_main_bucket_n` 才能给数值对照 —— 见 §5 第 2 条探针建议；按"三次探针"规则尚未升级为人类裁决项（代码链已闭合）。

**8) 判定与影响**：**P-PROVED / P2**。修复方向：把 `_prepare_bucket_frame` 移到 `_vp` 更新之后；或用"上帧 + 本帧"平面并集；或在 `_cam_sig` 变化的首帧强制 `planes=None`。

---

### 2.9 P-09 · "阴影共享逻辑位姿"的注释与实际写入源不一致

**1) 判定基准**：`loom_render.py:398-400`（R3 红线注释）："桶/实例/绘制消费渲染矩阵(插值); **_frame_world 保持逻辑位姿（碰撞/阴影共享源, R3）**"。

**2) 代码证据**

```python
# loom_render.py:401-403
fw = getattr(self, '_render_world', None)      # 插值平面
...
buf[:n] = fw                                   # fw32 = 插值
# loom_render.py:547 / 587
inst['sha'].write(g[:k], 0)    # 阴影实例 = 同一份 g（来自 fw32 = 插值）
```

**3) 证伪链（路径枚举）**：阴影 pass 的几何来源只有 `_render_to_shadow_map` 里的 `ent['sha_vao']`（loom_shadow.py:107），其实例缓冲只在 `_prepare_bucket_frame` 的 547/587 两处写入，写入的都是 `g = np.take(fw32, idxs)`，而 `fw32 ← _render_world`（401-403、448-453）。无第三条写入路径。
→ 注释对"阴影共享 `_frame_world`"的描述不成立 → **证伪失败**。

**4) 预期**：阴影几何用 `_frame_world`（逻辑位姿），或注释改口。
**5) 实际**：阴影几何用插值位姿；只有**阴影 VP 的包围范围**来自 `_logic_prep` 的 `_frame_world` AABB（engine.py:1080-1085）。
**6) 差异**：文档与实现不一致；副作用是"VP 包围盒按当前逻辑位姿算、几何按 prev→curr 插值画"，快速运动时 alpha≈0 的位姿可能超出该包围盒 → 阴影边缘被裁剪（一帧级）。

**7) 可复现验证**：写入源唯一（547/587）+ 数据源唯一（401-403）即闭合；无需渲染 A/B。
**8) 判定与影响**：**P-PROVED / P3**（口径/文档，附带一帧级阴影裁剪风险）。修复方向：择一 —— 阴影改用 `_frame_world` 重填实例缓冲（+1 次写），或把注释改为"阴影几何=插值、阴影 VP=逻辑 AABB"并给 VP 包围盒加插值外扩余量。

---

### 2.10 P-10 · GL 的 `pbr_enabled` 排错后门在 VK 播放器里失效（跨后端语义不一致）

**1) 判定基准**：`loom_render.py:604-607`（B7b 2026-10-16）："改设置项 `pbr_enabled=false` 排错后门"；`vk_renderer.py:1416-1425` 自称 "misc.x = 全局 PBR 开关（GL u_pbr_mode 同语义）"。

**2) 代码证据**

```python
# loom_render.py:606-607（GL）
self.prog['u_pbr_mode'].value = (1.0 if getattr(self, '_pbr_enabled', True) else 0.0)
# engine.py:465
self._pbr_enabled = bool(_s.get('pbr_enabled', True))
# vk_renderer.py:1425（VK）
buf[_R_MISC] = 1.0 if getattr(self, 'pbr_enabled', True) else 0.0   # ← 属性名少一个下划线
```

**3) 证伪链（路径枚举）**：全库赋值点枚举：`pbr_enabled=` 只出现在 `engine.py:465` 与 `engine.py:512`（都写 `self._pbr_enabled`，带下划线）；`VkRenderer` 构造（vk_player.py:90）只接收 `device/fmt/stage`，无 settings 注入。`getattr(self,'pbr_enabled',True)` 的三个来源（实例属性/类属性/继承）都不存在 → 恒 True。
→ **证伪失败**。

**4) 预期**：VK 也遵守 `设置.json: pbr_enabled=false`（关 PBR 走 Blinn-Phong）。
**5) 实际**：VK 恒开 PBR。
**6) 差异**：同一场景 GL/VK 出图不同；"排错后门"在 VK 上不可用。

**7) 可复现验证**：`grep -n "pbr_enabled" *.py` 仅 3 处（engine.py:465/512、vk_renderer.py:1425）+ `vk_player.py:90` 构造实参；无赋值点即闭合。
**8) 判定与影响**：**P-PROVED / P2**。`vk_renderer.py` 属 04_vk_render 范围，本报告只作为"GL 语义未被对侧等价实现"的交叉证据登记（统计计入 PROVED，修复归属 04，与 04 报告去重）。

---

### 2.11 D-02 · 桶键缓存 `_bucket_key` 不会因换网格/换材质而失配（证伪成功）

**1) 判定基准**：`loom_model_gpu.py:95-99`："几何键缓存挂 GameObject（`_bucket_key`, **setter 置脏**）… 材质是共享资产，物体缓存感知不到材质变化，故该分量每帧从 model 现取"。

**2) 代码证据**：见 §0.4 引用的 100-117 行；写入口：
- `loom_game_object.py:147-151`（mesh setter：`_bucket_key = None` + `_appearance_gen += 1`）
- `loom_game_object.py:162-178`（normal_mode/primitive/params setter：均置 `_bucket_key = None`）
- `loom_material.py:71-113`（color/saturation/albedo/normal_map/env_map/metallic/roughness/pbr 全部 `_bump_appearance`；贴图 setter 同时改 `_tex_guid/_nrm_guid/_env_guid`）

**3) 证伪链（路径枚举）**：能让桶键失配的 5 条路径逐条排除：
① 换 mesh → setter 置脏 + bump；② 改 primitive/params/normal_mode → setter 置脏；③ 换材质颜色/饱和度 → bump（分组签名变）；
④ 换贴图/PBR → 键的 3..6 分量每帧现取，且 bump 触发重分组；⑤ LOD 换 mesh（`loom_render.py:349-353`）→ 走 ① 的 setter。
唯一剩下的口子是"原地改 `mesh.params`/`mesh.vertices` 不经 setter"，而 `loom_game_object.py:71-72` 明确声明全库无此用法（白盒契约）。→ 五条路径全部闭合。

**4) 正手**：构造"改网格后仍用旧桶"的可执行复现必须绕过 setter 直接改顶点数组，那恰好违反 ⑤ 所引的契约 → 无可执行复现 → **证真失败**。
**8) 判定**：**P-DISPROVED**。附注：该结论依赖 `loom_game_object.py:71-72` 的"全库无原地 mutate"声明；若将来有人原地改 params，键会静默失配 —— 建议补一条"params 必须整体赋值"的自检。

---

### 2.12 D-03 · 立方体阴影的面序/UV 与着色器手工公式一致（证伪成功）

**1) 判定基准**：`loom_shaders.py:144-146`："面索引是片元级变量 … 负向面(-X/-Y/-Z)的 fc 公式须与 mat4_view_forward 视图 NDC 同号（**已核对, 勿改符号**）"；`loom_lighting.py:895-901`：面序与 up 定义。

**2) 代码证据**：`_point_light_vp` 的 `axes/ups`（899-900）与 `point_shadow` 的 6 个 fc 分支（151-160）。

**3) 证伪链（路径枚举）**：6 个面各取正向/负向两条路径 + 3 个偏轴方向，对每个方向比较"着色器手工 fc 公式"与"用 `_point_light_vp`[face] 投影的 uv"；任一不匹配即面序不符。

**7) 验证**

```text
python probe_faces.py
  rd=(10, 0.2, 0.1)   face=0  uv_manual=[0.505 0.49 ]  uv_from_vp=[0.505 0.49 ]  |d|=0.00e+00 OK
  rd=(-10, 0.2, 0.1)  face=1  ... OK    rd=(0.2,10,0.1)   face=2 ... OK
  rd=(0.2,-10,0.1)    face=3  ... OK    rd=(0.1,0.2,10)   face=4 ... OK
  rd=(0.1,0.2,-10)    face=5  ... OK    rd=(7,3,2)        face=0 ... OK
  rd=(-4,-8,1)        face=3  ... OK    rd=(2,-3,-9)      face=5 ... OK
  faces consistent: 9/9
```

**8) 判定**：**P-DISPROVED**（面序与 UV 同号，符号无需改动；该结果同时证明 P-01/P-02 的病灶在"纹理单元绑定"而非"面公式"）。

---

### 2.13 U-01 · World Space UI 之后恢复的 viewport 依赖"逻辑尺寸 == FBO 像素尺寸"

**1) 判定基准**：`loom_render.py:195-220`：离屏渲染临时把 `self.width/height` 改成 canvas 尺寸，最后恢复 `old_w/old_h` 并 `self.ctx.viewport = (0,0,old_w,old_h)`。

**2) 代码证据**

```python
old_w, old_h = self.width, self.height
...
self.ctx.viewport = (0, 0, cur_size[0], cur_size[1])
...
finally:
    self.ctx.viewport = (0, 0, old_w, old_h)     # ← 逻辑尺寸
    self._screen_fb().use()                       # moderngl 会按该 FBO 尺寸重设 viewport
```

**3) 证伪链**：moderngl 的 `Framebuffer.use()` 会把 viewport 设为该 FBO 尺寸（框架声明），因此紧随其后的 `use()` 覆盖 `viewport` 赋值 → **正常 DPI 下无害**；但函数内部在 `canvas → main` 切换期间用的是逻辑尺寸，且 `ui._draw_elem` 也可能读 `self.width/height` 作缩放基准。若宿主 FBO 像素尺寸 ≠ 逻辑尺寸（devicePixelRatio≠1），是否有错取决于宿主。

**4) 正手**：需要 devicePixelRatio=2 的 QOpenGLWidget 宿主，读 `render()` 结束后 `ctx.viewport` 与 `_screen_fb().size` 并截图 HUD。本机无 HiDPI 宿主、离屏 FBO 尺寸恒等于传入尺寸 → 构造不出反例 → **证真失败**。

**8) 判定**：**P-UNKNOWN**。已用探针：① 代码路径枚举（有 `use()` 兜底）；② 框架文档（`Framebuffer.use()` 设 viewport）。**还缺**：HiDPI 宿主实测。建议探针（≤3 次）：在 200% 缩放的 QWidget 上打印 `ctx.viewport / _screen_fb().size / self.width / self.height` 一次即可定论。

---

## 3. 统计（四象限与等级）

### 3.1 数量表

| 维度 | 数量 | 明细 |
|---|---|---|
| 粗筛疑似项 | **13** | P-01…P-10、D-02、D-03、U-01（粗筛跳过登记 **10** 条：S-01…S-10） |
| **P-PROVED** | **9** | P-01、P-02、P-03、P-04、P-05、P-07、P-08、P-09、P-10 |
| **P-DISPROVED** | **3** | P-06、D-02、D-03 |
| **P-UNKNOWN** | **1** | U-01 |
| **P-CONTRADICTION** | **0** | 见 3.3 解释 |
| **[REGRESSION]** | **1** | R-01 = P-05（本批未提交改动引入） |
| 定向探针 | **9** | probes：slots2 / vpcache / cull2 / pipeline2 / pointfar / beam / faces / guard / dir（辅助） |
| 既有回归测试实跑 | **4** | test_lighting / test_light_occlusion / test_lod / test_render_api —— 全 PASS |

### 3.2 等级与标签分布

| 等级 | 数量 | 条目 |
|---|---|---|
| **P0**（崩溃/主循环中断） | 1 | P-01 |
| **P1**（功能错误） | 3 | P-02、P-03、P-04 |
| **P2**（边界/性能/后端语义） | 4 | P-05、P-07、P-08、P-10 |
| **P3**（文档/口径） | 1 | P-09 |

| 标签 | 命中项 |
|---|---|
| SEM-MISMATCH | P-01、P-02、P-03 |
| SEM-OVERFIT | P-04、D-02 |
| SEM-DEFAULT | P-05 |
| AUDIT-DOCIMPL | P-06、P-08、P-09 |
| AUDIT-ASYMMETRY | P-07、P-10 |
| IFACE-ERROR / IFACE-UNIT | P-02 / D-03 |
| BND-CONCURRENCY / BND-RESOURCE | P-08 / U-01 |

信噪比：PROVED / 粗筛 = 9/13 = 69%；DISPROVED 3 条均为"证伪成功"而非"找不到反例"（P-06 有真实离屏 A/B、D-02 有 5 路写入口枚举、D-03 有 9/9 数值对照）。

### 3.3 关于 P-CONTRADICTION = 0 的说明

唯一一次"看起来矛盾"的是 P-06：P-17 注释声称 far 不一致导致"深度比较失效"，而实机 A/B 证明逐位相同。按 5.4 表，这既可能是 CONTRADICTION（两条链都有漏洞），也可能是 DISPROVED（注释链不成立）。核对结果：证真链（"far 影响比较"）缺失"far → gl_FragDepth"这一步（`"2) 代码证据"` 两行 `u_light_far` 都来自常数 30，不来自 VP），属**单侧链条错误**，故判 DISPROVED，未触发矛盾检测。除该项外，本模块没有出现"证伪与证真同时成立"的项。

### 3.4 交叉去重（避免与其它报告重复计数）

| 本报告条目 | 关联报告 | 处理 |
|---|---|---|
| S-08（材质库孤儿，loom_model_gpu.py:54,74-78） | **scan_02_scene P-03** | 只登记，不计数 |
| S-09（`_parallel_shadow_and_collision` 派发/缓存，loom_lighting.py:698-745） | **scan_01_core P-02** | 只登记，不计数 |
| P-10（`pbr_enabled` 双后端语义） | 04_vk_render | 本报告举证，**修复归属 04** |
| P-03（roll 缓存） | 无 | 独立 |
| P-08（上帧 VP） | 无 | 独立 |

---

## 4. 修复建议排序（只给方向，不含代码）

### P0（先做，否则"加灯即崩"）

1. **P-01**：把槽位预留从"kind == 'point' ? 6 : 1"改成"**非 directional（含 spot）= 6 面**"，并把守卫条件改为按 6 面判断（`unit + 6 - 1 <= 15`）；不满足时**整盏灯**不参与阴影（slots=-1），而不是只少记 1 个位。同步检查 `_render_shadow_maps` 是否应对"无槽位"的灯跳过 6 面深度 pass（现在会白渲染 6 面）。**回归测试**：用 3 灯顺序（point, point, spot）断言 `slots`/`sampler_units` 映射且不抛异常；再加 (spot, point) 断言 6 面纹理归属（本报告 probe_slots2 可直接改成断言版）。

### P1（功能错误，用户可见）

2. **P-02**：与 P-01 同一处修复；修完后必须验证"任何顺序下每盏灯占用的 6 个 sampler 索引 == 它自己的 6 张纹理"。
3. **P-03**：编辑态 VP 缓存键补 `float(l.roll)`（以及任何参与 `up_vector()` 的量）；或干脆用 `up_vector()` 的三分量入签名。**回归测试**：同一灯光只改 roll，断言签名变化且 VP 变化。
4. **P-04**：剔除半径改为世界空间量（网格半径 × 该实例最大缩放，或按世界 AABB/球心+缩放逐实例算）。**回归测试**：scale=12、中心在视锥外 2.2 单位、体积仍侵入的用例必须 `keep=True`。

### P2（性能/边界/后端语义）

5. **P-05（R-01）**：删除"有投影点光就整帧放弃 C 路径"的守卫及其 P-17 注释（根因已被 P-06 证伪；崩溃由 P-11 守卫覆盖，probe_guard 已证）。若担心回归，可加一次性 `LOOM_*` 观测计数而不是永久回退。
6. **P-07**：在 `need_bounds=False` 分支先统一算一次 `vis_aabbs/vis_rows` 再进循环（beam 的 near/far 只依赖可见包围盒，数值不变）。
7. **P-08**：把 `_prepare_bucket_frame` 挪到 `_vp` 更新之后（最小改动），或让 `_cam_sig` 变化的首帧强制 `planes=None`（保守一帧全量）。
8. **P-10**（归属 04）：VK 侧读 `_pbr_enabled`（或由宿主把 settings 注入 `VkRenderer.pbr_enabled`），与 GL 的 `u_pbr_mode` 同源。

### P3（口径）

9. **P-09**：择一 —— 阴影实例缓冲改用 `_frame_world`，或修订 R3 注释为"阴影几何=插值位姿、阴影 VP 包围=逻辑 AABB"，并给 VP 包围盒加插值外扩余量。
10. **U-01**：先补 HiDPI 实测，再决定是否把 viewport 恢复改为 `_screen_fb().size`。

### 回归资产（把本轮反例固化）

- `probe_slots2.py` 的 S2/S3/S4/S6 断言化（覆盖 P-01/P-02）；
- `probe_vpcache.py` 断言化（覆盖 P-03）；
- `probe_cull2.py` 的 scale=12 用例（覆盖 P-04）；
- `probe_pointfar.py` 的 A/B 深度图（锁死"far 与深度比较无关"的结论，防再次误修）。

---

## 5. 需要人类裁决的封闭问题（3 条）

### Q1（决定 P-01/P-02 的修法）：聚光灯是否支持"6 面立方阴影"？
- **A. 支持**（则 `need` 必须按非定向 = 6，槽位预留/守卫/绑定全部按 6；代价：最多只放得下 2 盏非定向阴影光）
- **B. 不支持**（则 `add_light`/`LightState` 对 `kind=='spot'` 强制 `shadow=False`，GUI/EAI 灰掉该开关，并在 sceneio 迁移里清值；代价：聚光灯失去阴影能力）
- **C. 支持但限制为 1 盏**（slot 固定 0..5，其余非定向阴影光自动降级无阴影）
> 现状是"代码按 A 建贴图/采样、按 B 记账"，必须选一个。

### Q2（决定 P-05/R-01 的方向）：GL 点光阴影的 VP 是否继续走 pipeline.dll？
- **A. 保留 C 路径**（删除 P-17 守卫；依据：far 不参与深度比较，真实离屏 A/B 深度图逐位相同；2001 体 3 光实测 0.785 vs 7.221 ms/帧）
- **B. 永久改 Python**（接受 +6.4 ms/帧@2001 体的代价，并把该数字写进性能基线；同时应把 spot 也一起纳入守卫，否则口径不一致）

### Q3（决定 P-03 的修法）：编辑器改"倾斜(roll)"是否必须立刻反映到阴影？
- **A. 必须**（sig 补 roll；代价：每次改 roll 触发一次全场景 VP 重算，n=501 约 0.9 ms）
- **B. 允许延迟**（保持现状，但在 `_light_vps_cache_sig` docstring 与用户文档中声明"roll 需下一次其它光照属性变更才生效"）

---

## 附录 A · 探针源码（外部可复现）

> 全部位于 `C:\Users\Administrator\AppData\Local\Temp\loom_scan03\`（仓库外）。执行前设
> `LOOM_NO_SAVE_MIGRATE=1` 与 `PYTHONPATH=<Loom 目录>`；探针**不修改任何仓库文件**（已用
> `Get-ChildItem -Recurse | Where LastWriteTime -gt 审计开始` 自查：仓库内 0 个源文件被写）。

### A.1 probe_slots2.py（P-01 / P-02 决定性证据）

```python
import os, sys, traceback
os.environ['LOOM_NO_SAVE_MIGRATE'] = '1'
LOOM = r"D:\my-project - 副本\Loom(py源代码-工作区)\Loom"
sys.path.insert(0, LOOM)
import numpy as np
from loom_lighting import LightingMixin
from loom_scene_entities import LightState

class FakeU:
    def __init__(self): self.value=None; self.raw=None
    def write(self, data): self.raw = data
class FakeProg:
    def __init__(self): self.u={}
    def __getitem__(self, k): return self.u.setdefault(k, FakeU())
class FakeTex:
    def __init__(self, tag): self.tag=tag
    def use(self, unit): UNIT_MAP[unit] = self.tag

UNIT_MAP = {}

class Eng(LightingMixin):
    def __init__(self, lights):
        self.lights = lights
        self.prog = FakeProg(); self._u = {}; self._u_last = {}
        self._shadow_maps = {}; self._shadow_res = 1024
        self._shadow_point_res = 512; self._shadow_point_far = 30.0
        self._light_vps = {}; self.models = []
        self._frame_world = np.zeros((0, 4, 4))

def mk(specs):
    eng = Eng([])
    for kind, shadow in specs:
        if kind == 'directional':
            l = LightState(kind=kind, position=(0,10,0), azimuth=0, elevation=-90, shadow=shadow)
        else:
            l = LightState(kind=kind, position=(0,5,0), shadow=shadow)
        eng.lights.append(l)
        if shadow:
            n = 1 if kind == 'directional' else 6
            eng._shadow_maps[l.guid] = {'tex': [FakeTex('%s[%d]' % (kind[:3], i)) for i in range(n)], 'fbo': []}
    return eng

def run(title, specs):
    global UNIT_MAP
    UNIT_MAP = {}
    eng = mk(specs)
    print('=' * 78); print(title)
    try:
        eng._upload_lights()
    except Exception as e:
        print('  !! EXCEPTION:', type(e).__name__, e)
        tb = traceback.extract_tb(sys.exc_info()[2])[-1]
        print('  at %s:%d  %s' % (os.path.basename(tb.filename), tb.lineno, tb.line))
        return
    b = eng._light_bufs
    print('  slots =', [int(x) for x in b['slots']][:len(eng.lights)])
    for i, l in enumerate(eng.lights[:8]):
        slot = int(b['slots'][i])
        if slot < 0: continue
        n = len(eng._shadow_maps[l.guid]['tex'])
        sampled_units = b['sampler_units'][slot:slot+n]
        actual = [UNIT_MAP.get(u, '<unbound>') for u in sampled_units]
        expect = ['%s[%d]' % (l.kind[:3], k) for k in range(n)]
        print('  %-11s slot=%2d units_sampled=%s' % (l.kind, slot, sampled_units))
        print('     expect textures=%s' % expect)
        print('     actual textures=%s   %s' % (actual, 'OK' if actual == expect else '<<< WRONG TEXTURE'))
    print('  final unit->texture:', {k: UNIT_MAP[k] for k in sorted(UNIT_MAP)})

run('S1 [dir(shadow), spot(shadow)]', [('directional',True), ('spot',True)])
run('S2 [spot(shadow), point(shadow)]', [('spot',True), ('point',True)])
run('S3 [spot(shadow), dir(shadow)]', [('spot',True), ('directional',True)])
run('S4 [point(shadow), point(shadow), spot(shadow)]', [('point',True), ('point',True), ('spot',True)])
run('S5 [spot(shadow)] alone', [('spot',True)])
run('S6 [dir(shadow), spot(shadow), point(shadow)]', [('directional',True), ('spot',True), ('point',True)])
```

### A.2 probe_vpcache.py（P-03）

```python
import os, sys
os.environ['LOOM_NO_SAVE_MIGRATE'] = '1'
sys.path.insert(0, r"D:\my-project - 副本\Loom(py源代码-工作区)\Loom")
import numpy as np
from loom_lighting import LightingMixin
from loom_scene_entities import LightState
from loom_types import Point3D

class Eng(LightingMixin):
    def __init__(self, light):
        self.lights = [light]
        self._frame_world = np.zeros((3, 4, 4))
        self._struct_gen = 7
        self._light_vps = {}
        self.models = []
        self._stage_times = {}
    def _model_aabbs_par(self, *a, **k):
        return AABBS

AABBS = [(Point3D(-1,-1,-1), Point3D(1,1,1)),
         (Point3D(2,0,-3), Point3D(4,2,-1))]

l = LightState(kind='directional', position=(0, 10, 0), azimuth=35.0, elevation=-40.0, roll=0.0, shadow=True)
eng = Eng(l)

s0 = eng._light_vps_cache_sig()
vp0 = eng._dir_light_vp(l, AABBS)
print('sig(roll=0)   =', s0)
print('vp(roll=0)  diag =', np.round(np.diag(vp0), 5))

l.roll = 30.0
s1 = eng._light_vps_cache_sig()
vp1 = eng._dir_light_vp(l, AABBS)
print('sig(roll=30)  =', s1)
print('vp(roll=30) diag =', np.round(np.diag(vp1), 5))
print()
print('signature equal      :', s0 == s1)
print('max |vp1 - vp0|      :', float(np.abs(np.asarray(vp1) - np.asarray(vp0)).max()))
print('=> cache would REUSE stale VP:', (s0 == s1) and float(np.abs(np.asarray(vp1)-np.asarray(vp0)).max()) > 1e-9)
```

### A.3 probe_cull2.py（P-04）

```python
import os, sys
os.environ['LOOM_NO_SAVE_MIGRATE'] = '1'
sys.path.insert(0, r"D:\my-project - 副本\Loom(py源代码-工作区)\Loom")
import numpy as np
from matlib import mat4_perspective, mat4_view_yaw_pitch
from loom_render import RenderMixin

eng = RenderMixin()
V = mat4_view_yaw_pitch(np, (0.0, 0.0, 0.0), 0.0, 0.0, 0.0)   # 本引擎 yaw=0 朝 +z
P = mat4_perspective(np, np.radians(60.0), 1280/720, 0.1, 1000.0)
planes = eng._frustum_planes(V @ P)
cube = np.array([[x,y,z,1.0] for x in (-0.5,0.5) for y in (-0.5,0.5) for z in (-0.5,0.5)])
R = float(np.linalg.norm([0.5,0.5,0.5]))          # 网格局部半径（引擎用的就是这个）

def M(s, t):
    m = np.zeros((4,4)); m[0,0]=m[1,1]=m[2,2]=s; m[3,:3]=t; m[3,3]=1.0; return m

def probe(label, center, scale):
    m = M(scale, center)
    world = (cube @ m)[:, :3]
    inside = [bool(((planes[:,:3] @ c + planes[:,3]) >= 0).all()) for c in world]
    keep = bool(eng._frustum_keep(m.reshape(1,4,4), planes, R)[0])
    print('%-24s scale=%-4g visible_vertices=%d/8  _frustum_keep(unscaled r=%.3f)=%s %s'
          % (label, scale, sum(inside), R, keep,
             '<<< FALSE CULL' if (sum(inside) and not keep) else ''))
    print('    world-space radius should be %.2f' % (R*scale))

probe('center x=11.5 z=10', (11.5, 0.0, 10.0), 20.0)
probe('center x=11.5 z=10', (11.5, 0.0, 10.0), 1.0)
probe('center x=4.0 z=10',  (4.0, 0.0, 10.0), 4.0)
probe('center y=8 z=10',    (0.0, 8.0, 10.0), 12.0)
```

### A.4 probe_pointfar.py（P-06 的决定性证据：真实离屏 GL）

```python
import os, sys
os.environ['LOOM_NO_SAVE_MIGRATE'] = '1'
sys.path.insert(0, r"D:\my-project - 副本\Loom(py源代码-工作区)\Loom")
import numpy as np, moderngl
from matlib import mat4_perspective, mat4_view_forward
from loom_shaders import _SHADOW_VERT, _SHADOW_FRAG

def vp_for(far):
    proj = mat4_perspective(np, np.radians(90.0), 1.0, 0.05, far)
    view = mat4_view_forward(np, (0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0))
    return view @ proj

p = np.array([20.0, 3.0, 2.0, 1.0])
a = p @ vp_for(30.0); b = p @ vp_for(1e4)
print('  far=30   ndc xyz =', np.round(a[:3]/a[3], 6))
print('  far=1e4  ndc xyz =', np.round(b[:3]/b[3], 6))
print('  |dxy| =', float(np.abs(a[:2]/a[3]-b[:2]/b[3]).max()))

ctx = moderngl.create_standalone_context()
prog = ctx.program(vertex_shader=_SHADOW_VERT, fragment_shader=_SHADOW_FRAG)

cube_v = np.array([
 -0.5,-0.5, 0.5,  0.5,-0.5, 0.5,  0.5, 0.5, 0.5, -0.5,-0.5, 0.5,  0.5, 0.5, 0.5, -0.5, 0.5, 0.5,
 -0.5,-0.5,-0.5, -0.5, 0.5,-0.5,  0.5, 0.5,-0.5, -0.5,-0.5,-0.5,  0.5, 0.5,-0.5,  0.5,-0.5,-0.5,
 -0.5, 0.5,-0.5, -0.5, 0.5, 0.5,  0.5, 0.5, 0.5, -0.5, 0.5,-0.5,  0.5, 0.5, 0.5,  0.5, 0.5,-0.5,
 -0.5,-0.5,-0.5,  0.5,-0.5,-0.5,  0.5,-0.5, 0.5, -0.5,-0.5,-0.5,  0.5,-0.5, 0.5, -0.5,-0.5, 0.5,
  0.5,-0.5,-0.5,  0.5, 0.5,-0.5,  0.5, 0.5, 0.5,  0.5,-0.5,-0.5,  0.5, 0.5, 0.5,  0.5,-0.5, 0.5,
 -0.5,-0.5,-0.5, -0.5,-0.5, 0.5, -0.5, 0.5, 0.5, -0.5,-0.5,-0.5, -0.5, 0.5, 0.5, -0.5, 0.5,-0.5,
], dtype='f4')

def inst(s, t):
    m = np.zeros((4,4), dtype='f4'); m[0,0]=m[1,1]=m[2,2]=s; m[3,:3]=t; m[3,3]=1.0; return m

math_ = np.stack([inst(1.0, (20.0, 0.0, 0.0)), inst(1.0, (40.0, 0.0, 0.0))]).astype('f4')
RES = 256
tex = ctx.depth_texture((RES, RES))
fbo = ctx.framebuffer(depth_attachment=tex)
vbo = ctx.buffer(cube_v.tobytes()); ibo = ctx.buffer(math_.tobytes())
vao = ctx.vertex_array(prog, [(vbo, '3f', 'in_pos'), (ibo, '4f 4f 4f 4f/i', 'a_w0', 'a_w1', 'a_w2', 'a_w3')])
prog['u_depth_kind'].value = 1
prog['u_light_pos'].value = (0.0, 0.0, 0.0)
prog['u_light_far'].value = 30.0
ctx.enable(moderngl.DEPTH_TEST); ctx.disable(moderngl.CULL_FACE)

def render(far):
    fbo.clear(depth=1.0); fbo.use()
    prog['u_light_vp'].write(np.ascontiguousarray(vp_for(far).astype('f4')).tobytes())
    vao.render(moderngl.TRIANGLES, instances=2)
    depth = fbo.read(components=1, dtype='f4', attachment=-1)
    return np.frombuffer(depth, dtype='f4').reshape(RES, RES).copy()

d30 = render(30.0); d9 = render(1e4)
print('depth(far=30)  min=%.5f max=%.5f  pixels<1: %d' % (d30.min(), d30.max(), int((d30<0.999).sum())))
print('depth(far=1e4) min=%.5f max=%.5f  pixels<1: %d' % (d9.min(), d9.max(), int((d9<0.999).sum())))
print('max |depth(far=30) - depth(far=1e4)| =', float(np.abs(d30-d9).max()))
print('identical depth maps:', bool(np.array_equal(d30, d9)))
```

### A.5 其余探针（源码要点已在 §2 正文引用，输出为原样）

| 探针 | 覆盖 | 关键输出 |
|---|---|---|
| probe_pipeline2.py | P-05：C/Python VP 耗时；P-17 守卫是否短路 | `C 0.7853 ms/frame / Python 7.2212 ms/frame / delta +6.4359；with point light C_calls=0；without C_calls=1` |
| probe_beam.py | P-07：beam 光 AABB 重算次数 | `1 / 3 / 1 / 1 / 0 次`（1 beam / 3 beam / 1 full / 3 full / 3 full+预计算） |
| probe_faces.py | D-03：面序与 UV | `faces consistent: 9/9`，最大偏差 1.11e-16 |
| probe_guard.py | P-05：谁覆盖"无行表"崩溃路径 | `spot-shadow only -> False（命中 P-11 守卫）；point-shadow only -> False（命中 P-17 守卫）` |
| probe_slots2.py S1/S5 | P-02 的反向对照 | 单 spot / dir+spot 时映射正确（证明不是"所有情况都错"，而是顺序相关） |

---

## 附录 B · 本轮自审（方法论 §11.5 checklist）

```text
[x] 第 7 节 8 条硬要求：基准唯一（全部引用本仓库代码注释/常量）／代码原样／路径枚举／预期-实际对照／
    命令可跑（附录 A 全源码）／措辞可审计／跳过留痕（S-01…S-10）／矛盾不忽略（P-06 已查清是注释单侧错误）
[x] 每条链引用被审对象自身契约，无外部标准混用（唯一"外部"依据是 moderngl/Python 标准库语义，
    属四类跳过理由第 1/4 类）
[x] 每条证伪链第 3 段都有路径枚举表（P-01 四路径 / P-02 三顺序 / P-03 四入口 / P-04 三路径 /
    P-05 三条件 / P-06 三来源 / P-07 两来源 / P-08 三路径 / P-09 两写入点 / P-10 三来源）
[x] 每条证真链第 7 段都有可跑命令（附录 A 或正文代码块）
[x] 跳过登记表每条都有四类理由之一的出处
[x] P-UNKNOWN = 1（U-01），非 0；P-PROVED = 9，非 0
[x] P-CONTRADICTION = 0，已在 §3.3 说明唯一候选为何归 DISPROVED
[x] P-PROVED 未写修复代码（§4 只给方向）；未修改任何受跟踪文件
[x] P-UNKNOWN 探针 <= 3 次（U-01 用了 2 次：路径枚举 + 框架文档）
[x] 人类裁决项都是封闭问题（Q1 三选一、Q2 二选一、Q3 二选一）
[x] 未出现"我认为/经验上/看起来/应该是"作为结论依据
[x] 严格只读：git status 审计前后一致；探针全在 %TEMP%；未跑 tests/run_all.py
```

**本轮等级自评：A6**（A4 的双向链 + 矛盾检测、A5 的探针与三次升级、A6 的白盒推广与裁决格式均已具备；
A7 要求"跳过留痕 + 自我合理化失败模式清单作为审计项"，本报告已在 §1.2 与附录 B 落地，但按方法论
"A7 需外部复核"，不自评 A7）。

**已知局限（供复核者优先质疑）**
1. P-04 的判定在 `_frustum_keep` 单元层完成，未在真实 500 体场景里做"整桶消失"的像素级复现
   （需构造 >=2 实例同桶 + 缩放 + 边缘构图）。
2. P-08 只有代码顺序证据，未做受控帧序列的数值 A/B（见 §5 建议）。
3. P-10 属 04_vk_render 范围，本报告只做 GL 侧语义对照，不裁决 VK 修复方式。
4. 未覆盖 `_draw_hud` / `loom_ui` / 线框绘制（不在本模块 5 文件内）。

---

*报告结束。所有实测输出为 2026-11-07 本机原样输出；探针未污染仓库。*
