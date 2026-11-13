# 实现报告 · T3b 剩余三块手写 WGSL 单源化（阴影 pass / 天空 / mip，2026-11-13）

> **状态：已完成。**
> 四道门全绿：构建 EXIT 0（11 个 .spv）、`test_ab_gl_vk.py` **23/23 PASS**、`run_all.py` **135 文件全绿**、
> grep 证据满足；**23 场景 MAE 与开工前基线逐值相同（无像素变化）**。
> 纪律：**未 `git add` / 未 `git commit`**；**未改任何基线文件/参考图/测试文件**；临时探针只在
> `%TEMP%\loom_t3b\`，仓库根无临时文件。
>
> 环境：Windows PowerShell / `py -3.13`（3.13.15）/ wgpu 0.33 / glslang 16.6.0（版本 + sha256 校验通过）。
> 开工 HEAD `d25c910`（工作树干净），收尾仍 `d25c910`（未提交）。

---

## 1. 逐块「GL 侧有没有对应实现」（任务强制项）

| 块 | 手写 WGSL（改前） | GL 侧对应物 | 结论 | 单源方式 |
|---|---|---|---|---|
| **阴影 pass** | `vk_renderer._SHADOW_VERT`，**37 行**（vs+fs 同模块） | **有**：`loom_shaders._SHADOW_VERT / _SHADOW_FRAG`（GL 现役，`loom_shadow.py:29` 编译；`_render_to_shadow_map` 每面换 uniform） | **真统一**：GL 也改成读同一份 `shaders/shadow.vert` / `shadow.frag` | 顶点/世界位置/深度公式两端逐字同一；差异全部由 compat 宏吸收：**产物**（GL 有深度附件 -> `gl_FragDepth`；VK 是 r32float 颜色附件 -> `frag_color.r`）与**参数传输**（GL 三个独立 uniform；VK binding 0 的 `ShadowU` UBO） |
| **天空** | `vk_renderer._SKY_WGSL`，**29 行**（vs+fs 同模块） | **有**：`loom_shaders._SKY_VERT / _SKY_FRAG`（GL 现役，`loom_render.py:170-174` 编译） | **真统一**：GL 也改成读同一份 `shaders/sky.vert` / `sky.frag` | 反投影/采样公式两端逐字同一；差异由 compat 宏吸收：**顶点来源**（GL quad VBO 6 顶点 / VK 无顶点缓冲全屏三角 3 顶点）与**参数传输**（GL 独立 uniform；VK `SkyC` UBO + 分离 textureCube/sampler） |
| **mip 降采样** | `vk_renderer._MIP_WGSL`，**14 行**（vs+fs 同模块） | **没有**：GL 侧是驱动 `glGenerateMipmap`（moderngl `texture.build_mipmaps()`，见 `loom_texture.py:182` / `loom_cubemap.py:203`），**没有可单源化的 shader 阶段** | **不是同一份实现**（只供 VK） | 写成 `shaders/mip_downsample.frag` 供 VK 编译 SPIR-V；顶点阶段复用 `shaders/post_fullscreen.vert`。**不假装统一**，差异见 §5（T2 清单候选） |

结论一句话：**阴影 / 天空是真统一（GL 与 VK 同一份 GLSL 源）；mip 是「登记为 VK 单源」的实现差异，不是统一。**

---

## 2. 改了哪些文件 / 多少行

| 文件 | +/−（tracked diff） | 内容 |
|---|---|---|
| `Loom/shaders/loom_shader_compat.glsl` | **+59 / −1**（整文件重写，非字符串替换） | 新增天空宏（`SB_SKY_UBO/CUBE/SAMP`、`DECL_SKY_UNI`、`SKY_INV_VP/CAM/TINT`、`DECL_SKY_INPUT`、`SKY_VERT_NDC`）与阴影宏（`SB_SHADOW_U`、`DECL_SHADOW_UNI/PARAMS/OUT`、`SHADOW_VP/IS_DISTANCE/LIGHT_POS/FAR/STAGE_DEPTH/STORE_DEPTH`）；保留既有全部宏与 VK 的 `PLACEHOLDER 10/11` 常量 |
| `Loom/loom_shaders.py` | **+27 / −54** | 删掉 GL 的第二份 GLSL 文本（阴影 2 段 + 天空 2 段）；新增 `_shared_shader_src(name)`；`_SHADOW_VERT/_SHADOW_FRAG/_SKY_VERT/_SKY_FRAG` 改为从 `shaders/*` 加载（展开 compat + `#version 450→430`）。**导出名不变**（`loom_shadow.py` / `loom_render.py` 无需改） |
| `Loom/vk_renderer.py` | **+41 / −93** | 删 `_SHADOW_VERT`(37 行 WGSL)、`_SKY_WGSL`(29 行)、`_MIP_WGSL`(14 行) 三块手写 WGSL；新增 `_spv_module(name)`（按名缓存 `.spv` -> shader module，缺文件即 `RuntimeError`，不回退 WGSL）；阴影/天空/mip 三个管线改喂 SPIR-V，`entry_point='main'` |
| `Loom/shaders/shadow.vert`（新） | 23 行 | 阴影 pass 顶点单源（实例 world = location 3..6，`gl_Position = SHADOW_VP * world`，`out v_world_pos`） |
| `Loom/shaders/shadow.frag`（新） | 25 行 | 阴影 pass 片段单源（模式 0 = 窗口深度 / 模式 1 = 距离 `/ far`） |
| `Loom/shaders/sky.vert`（新） | 16 行 | 天空顶点单源（`v_ndc` + `gl_Position = vec4(ndc,1,1)`） |
| `Loom/shaders/sky.frag`（新） | 23 行 | 天空片段单源（`clip -> world = invVP*clip -> dir`，`SAMPLECUBE`） |
| `Loom/shaders/mip_downsample.frag`（新） | 17 行 | VK mip 降采样（`gl_FragCoord.xy / (srcSize*0.5)`，`SAMPLE2D_LOD(...,0)`） |
| `Loom/shaders/*.spv` | 新增 5 个（共 11 个） | `shadow.vert.spv` 2308 B / `shadow.frag.spv` 1556 B / `sky.vert.spv` 1220 B / `sky.frag.spv` 2184 B / `mip_downsample.frag.spv` 1084 B |
| `docs/audit/impl_T3_remaining_20261113.md`（本文件） | 新 | 报告 |

> **.spv 数量是 11，不是任务里写的 9。** 原因：glslang 一个源文件只产一个 **stage** 的模块，而阴影/天空的 vs 与 fs
> 现在是两个文件（与主 pass 的 `main.vert`+`main.frag` 同款）——两块各 +2；mip 复用 `post_fullscreen.vert`
> 只 +1。6（原有）+ 5 = **11**。旧的「每个块 1 个 WGSL 模块」在 SPIR-V 世界里最少也要「每 stage 1 个文件」。

**没有改**：`Loom/tests/**`、`docs/design/**`、`docs/handoff/**`、`loom_shadow.py`、`loom_render.py`、`loom_post_gl.py`、`tools/build_shaders.py`（目录扫描已能自动收录新文件，无需改）。

---

## 3. 门 1：构建（`py -3.13 tools/build_shaders.py`）

    [shaders] main.frag                    -> main.frag.spv            33156 bytes
    [shaders] main.vert                    -> main.vert.spv             4424 bytes
    [shaders] mip_downsample.frag          -> mip_downsample.frag.spv   1084 bytes
    [shaders] post_bright.frag             -> post_bright.frag.spv      2144 bytes
    [shaders] post_down.frag               -> post_down.frag.spv        2516 bytes
    [shaders] post_fullscreen.vert         -> post_fullscreen.vert.spv  1312 bytes
    [shaders] post_tonemap.frag            -> post_tonemap.frag.spv     2180 bytes
    [shaders] shadow.frag                  -> shadow.frag.spv           1556 bytes
    [shaders] shadow.vert                  -> shadow.vert.spv           2308 bytes
    [shaders] sky.frag                     -> sky.frag.spv              2184 bytes
    [shaders] sky.vert                     -> sky.vert.spv              1220 bytes
    **EXIT=0**（11 个 .spv）

---

## 4. 门 2：23 场景像素（改前 = 干净 HEAD 实测；改后 = 最终树）

`test_ab_gl_vk.py`：**23/23 PASS，EXIT=0**。**所有 23 场景三向 MAE 与改前逐值相同**（下表「改后」列，
改前列与之完全一致，含 MAX/NCC/漂移）；任务点名的 5 个场景逐值核对如下：

| 场景 | 改前 GL/ref | 改后 GL/ref | 改前 VK/ref | 改后 VK/ref | 改前 GL/VK | 改后 GL/VK |
|---|---|---|---|---|---|---|
| **ab_sky** | 0.000012 | **0.000012** | 0.000012 | **0.000012** | 0.000000 | **0.000000** |
| **ab_tex** | 0.000000 | **0.000000** | 0.000000 | **0.000000** | 0.000000 | **0.000000** |
| **ab_c_dir_shadow** | 0.000029 | **0.000029** | 0.000051 | **0.000051** | 0.000029 | **0.000029** |
| **ab_point_shadow** | 0.000057 | **0.000057** | 0.000046 | **0.000046** | 0.000011 | **0.000011** |
| **ab_scene** | 0.000026 | **0.000026** | 0.000046 | **0.000046** | 0.000028 | **0.000028** |

其余 18 场景（改前 == 改后）：`ab_bloom` 0/0/0、`ab_c_dir+point` 0/0/0、`ab_c_dir_only` 0/0/0、
`ab_c_point_only` 0/0/0、`ab_c_spot_only` 0/0/0、`ab_cube` 0/0/0、`ab_env` 2e-6/2e-6/1e-6、
`ab_env_off` 0/0/0、`ab_nrm` 0/0/0、`ab_nrm_off` 0/0/0、`ab_pbr` 0/0/0、`ab_plane` 0/0/0、
`ab_plane_cube` 1.3e-5/1.3e-5/0、`ab_plane_cube_sun_pt` 1.1e-5/1.1e-5/0、`ab_plane_shfalse` 0/0/0、
`ab_plane_shtrue` 0/0/0、`ab_plane_sphere` 1.6e-5/3.8e-5/2.9e-5、`ab_ui_scene` 2.2e-5/6.6e-5/5.3e-5
（UI 子项 UI MAE 0.000110 亦不变）。

**没有改任何基线 JSON / 参考图**（`git status` 里 `Loom/tests/ab_gl_vk_baseline*.json` 与 `ab_scenes_ref*/` 均无改动）。

---

## 5. 门 3：全量回归（`py -3.13 tests/run_all.py`）

    ...
    运行: test_vk_two_dir_shadow.py
    ...
    运行: test_integration.py
    全部测试完成 ✅
    **EXIT=0**

135 个测试文件（`Get-ChildItem Loom/tests/test_*.py` = 135），**全绿，无一项红**。

---

## 6. 门 4：grep 证据

    # 1) vk_renderer.py 里三块常量名 = 0
    Select-String Loom/vk_renderer.py -Pattern '_SKY_WGSL','_SHADOW_VERT','_MIP_WGSL' -> 无命中

    # 2) vk_renderer.py 里旧 WGSL 采样/类型标记 = 0
    Select-String Loom/vk_renderer.py -Pattern 'textureSample','texture_cube','samplerShadow','textureSampleLevel' -> NONE

    # 3) vk_renderer.py 剩余 WGSL 标记（只剩 P1 逃生舱，见 §9）
    Loom/vk_renderer.py:81:@group(0) @binding(0) var<uniform> per: PerObject;
    Loom/vk_renderer.py:83:@vertex fn vs(@location(0) p: vec3f, @location(1) n: vec3f,
    Loom/vk_renderer.py:92:@fragment fn fs(in: VSOut) -> @location(0) vec4f {

    # 4) #ifdef LOOM_VK 仍只在兼容层（shader 代码范围内；git grep 会命中注释/文档/测试字符串）
    Loom/shaders/loom_shader_compat.glsl:9:#ifdef LOOM_VK
    （其余命中均为注释/文档/测试里的**文本提及**：compat:4、test_vk_two_dir_shadow.py:145、
      tools/build_shaders.py:8、docs/**）

> 说明：`Loom/loom_shaders.py:133` 与 `Loom/loom_shadow.py:18/29/76` 里出现的 `_SHADOW_VERT` 是 **GL 侧
> 单源加载器的导出名**（`_SHADOW_VERT = _shared_shader_src('shadow.vert')`），与 GL 的主 pass 写法
> （`_VERT_SRC = _shared_vert_src()`）完全同款；**不是**第二份 WGSL/GLSL。名字为兼容 `loom_shadow.py`
> 的 import 而保留（该文件不在本次可改范围）。

---

## 7. 实测证据（不是「跑通」就算）

### 7.1 VK 真的加载了这些 SPIR-V 模块（探针在 `%TEMP%\loom_t3b\probe_spv_modules.py`）

    ab_sky.json          | spv modules: ['shadow.frag','shadow.vert','sky.frag','sky.vert']
       sky_pipe=True shadow_pipeline=True mip_pipe=False
    ab_tex.json          | spv modules: ['mip_downsample.frag','post_fullscreen.vert','shadow.frag','shadow.vert','sky.frag','sky.vert']
       sky_pipe=True shadow_pipeline=True mip_pipe=True mip_fmt=rgba8unorm
    ab_c_dir_shadow.json | spv modules: ['shadow.frag','shadow.vert','sky.frag','sky.vert']
    ab_point_shadow.json | spv modules: ['shadow.frag','shadow.vert','sky.frag','sky.vert']

-> mip 模块只在**真有 mip 贴图**的场景被建（ab_tex），证明 `_gen_mips` 走的是新 SPIR-V 管线，且
`_MIP_WGSL` 已不可达（常量已删）。

### 7.2 阴影 pass 真的写入了深度（点光阴影图读回，`probe_point_shadow.py`）

    point shadow depth: min=0.133334 max=1.000000 finite=True
      face 0: min=1.000000 max=1.000000  n<1=0.0%
      face 1: min=0.164383 max=1.000000  n<1=17.2%
      face 2: min=1.000000 max=1.000000  n<1=0.0%
      face 3: min=0.133334 max=1.000000  n<1=56.2%
      face 4: min=1.000000 max=1.000000  n<1=0.0%
      face 5: min=0.164383 max=1.000000  n<1=17.2%

-> `shadow.frag` 的 `SHADOW_STORE_DEPTH`（VK 分支写 r32float 颜色附件）确实产出了非平凡深度
（距离/far 0.133~1.0，无 NaN/Inf），不是全 0/全 1。

---

## 8. 兼容层新增宏（为什么必须这么做）

| 宏 | VK 分支 | GL 分支 |
|---|---|---|
| `DECL_SKY_UNI` / `SKY_INV_VP` / `SKY_CAM` / `SKY_TINT` | `layout(std140,binding=0) uniform SkyC{...} sky;`（字段序/mat4 首地址与 `_draw_sky` 的 28 f32 逐字节对齐） | `uniform mat4 u_inv_view_proj; uniform vec3 u_camera_pos; uniform vec3 u_skybox_tint;` |
| `DECL_SKY_INPUT` / `SKY_VERT_NDC` | 空 / `gl_VertexIndex` 全屏三角 | `in vec2 in_pos;` / `in_pos*2-1`（沿用 `loom_render` 的 quad VBO 与 6 顶点 draw，**不改 GL 调用方**） |
| `DECL_SHADOW_UNI` / `SHADOW_VP` | `layout(std140,binding=0) uniform ShadowU{mat4 sh_vp; vec4 sh_pos; vec4 sh_params;} sh;` | `uniform mat4 u_light_vp;` |
| `DECL_SHADOW_PARAMS` / `SHADOW_IS_DISTANCE` / `SHADOW_LIGHT_POS` / `SHADOW_FAR` | 空（已在 ShadowU 里）/ `params.x>0.5` / `params.xyz` / `max(params.y,1e-3)` | `uniform int u_depth_kind; uniform vec3 u_light_pos; uniform float u_light_far;` / `u_depth_kind>0` / `u_light_pos` / `u_light_far` |
| `SHADOW_STAGE_DEPTH` / `SHADOW_STORE_DEPTH` / `DECL_SHADOW_OUT` | `gl_FragCoord.z` / `frag_color = vec4(d,0,0,1)` / `layout(location=0) out vec4 frag_color;` | `gl_FragCoord.z` / `gl_FragDepth = d` / 空（只有深度附件） |

阴影 pass 的 UBO 字节布局与 `_exec_shadow_maps` 现有写缓冲**逐字节不变**（24 f32：vp[0..16) pos[16..20)
params[20..24)，x=模式 y=far），所以 VK 侧写缓冲代码一行未动。

---

## 9. 遗留不确定点（宁多列）

1. **.spv 数量 11 ≠ 任务描述里的 9**（原因见 §2）；如果主审的「9」是把两块合并计，请以真实构建输出为准。
2. **mip 的 GL/VK 不是同一实现（已登记为 T2 差异）**：GL 由驱动 `glGenerateMipmap` 生成整条链
   （滤镜为驱动实现定义）；VK 用手写片段逐级降采样（目标像素中心映射到源纹素边界 = 2x2 双线性，
   在「尺寸恰为偶数倍」时与 box 平均一致）。当前 `ab_tex` 三向 MAE **0/0/0**，但不保证所有资产
   （奇数尺寸/非 2 的幂/带 alpha 边缘）与 GL 逐像素一致。若后续要严格统一，只能统一成两端各自
   驱动/着色器之一（会改 GL 侧行为），或接受该差异。
3. **VK 天空片段换了角度来源**：从「`gl_FragCoord` + `SkyC.size`」改为「顶点插值 `v_ndc`」。数学上
   二者是同一个线性函数，23 场景逐值相同；但理论上浮点求值路径不同（插值 vs 像素中心除法），
   极端梯度下可能有 ≤1 ulp 差。`SkyC.size` 字段仍保留在 UBO 里（WGSL 时代的历史布局），本次未删。
4. **VK 阴影模式 0 的深度值**从「`in.pos.z/in.pos.w`」改为「`gl_FragCoord.z`」。二者都是窗口深度
   （wgpu NDC z 就是 [0,1]），像素门逐值相同；但严格说是两条计算路径（插值后取 FragCoord vs
   手工除 w），未做逐像素字节级对照。
5. **GL 阴影片段现在「写回同值」**：旧版模式 0 直接 `gl_FragDepth = gl_FragCoord.z`，新版是
   `d = gl_FragCoord.z; gl_FragDepth = d`，语义等价；GL 侧像素逐值相同已证。
6. **P1 逃生舱仍有 16 行手写 WGSL**：`_MAIN_P1_VERT`（11 行）+ `_MAIN_P1_FRAG`（5 行），
   只有 `VkRenderer(stage='p1')`（`vk_player.py --stage p1`）可达，与 GL 无对应、**不在 23 场景覆盖内**。
   本次任务只点名三块，未动它（见 §10）。
7. **`vk_ui.py` 的两块 WGSL 仍未单源化**（`_UI_WGSL` 31 行 + `_WORLD_UI_WGSL` 24 行）；handoff §2
   已登记为「未开始」，本次范围不含。
8. 阴影 UBO 现在由 **vs 与 fs 两个独立 SPIR-V 模块各自声明同一 block（binding 0）**；wgpu 视角是
   两个 stage 引用同一 binding。门 2 与探针均通过，但若后续改用 naga/WGSL 或合并模块需复查。
9. 只验证了「离屏 23 场景 + `test_integration` 真实窗口冒烟」，**没有做窗口交互下的人工目视比对**
   （无头环境）；像素门是本次唯一的视觉证据。
10. `git grep 'ifdef LOOM_VK'` 全仓仍会命中 docs/tools/tests 的**文本提及**（注释、测试切分字符串、
    构建脚本说明），shader 代码里只有 compat 一处；报告里已区分。
11. **发布包未重跑**。核对过 `tools/package_engine.py` 的收集逻辑：`collect_files` 是 `os.walk` 全量遍历，
    `EXCLUDE_EXTS` 只排 `.pyc/.pyo/.log/.tmp`，所以新增的 5 个 `.spv` 与 5 个源文件会被自动收进源码包；
    但**没有实际出包验证**（不在本次验收门内，打包耗时且会覆盖 dist）。

---

## 10. 剩余手写 WGSL（登记）

| 位置 | 行数 | 状态 |
|---|---|---|
| `Loom/vk_renderer.py` `_MAIN_P1_VERT/_MAIN_P1_FRAG` | **16** | **未动**：P1 逃生舱（`--stage p1`），无 GL 对应、无像素门覆盖；不在本次三块范围 |
| `Loom/vk_ui.py` `_UI_WGSL` / `_WORLD_UI_WGSL` | **55**（31 + 24） | 未动：handoff 已登记为「未开始」，不在本次范围 |
| **合计** | **71** | 本次三块（80 行）已清零；剩余 71 行全部登记 |

---

## 11. 下一步建议

1. 主审提交时把 5 个新 `.frag/.vert` + 5 个新 `.spv` 一并 `git add`（`docs/audit` 本文件按需）。
2. 在 `docs/design/T2差异清单_beta6.md` 增两条：
   - **mip 生成**：GL = 驱动 `glGenerateMipmap`；VK = `mip_downsample.frag` 逐级 2x2 双线性。
   - **阴影 pass**：GL = 深度附件 + `gl_FragDepth` + 独立 uniform；VK = r32float 颜色附件 + binding0 UBO。
3. 若要继续收口：`_MAIN_P1_*`（确认 p1 不再使用则删）与 `vk_ui.py` 两块。
4. 建议补一个「奇数尺寸贴图 + mip」的 A/B 场景，把 mip 差异从「当前资产下为 0」变成有覆盖的证据。
