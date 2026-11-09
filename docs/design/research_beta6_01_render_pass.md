# research_beta6_01 · 渲染管线与 Pass 抽象调研

> 编号：01 ｜ 主题：渲染管线与 Pass 抽象 ｜ 日期：2026-11-09
> 性质：**只读调研**（未改任何受跟踪文件；未 git add/commit/checkout/stash）。唯一写入 = 本文件。
> 代码根：`D:/my-project - 副本/Loom(py源代码-工作区)/Loom`（下称 `Loom/`，行号均为该目录下实测）
> 环境实测：Windows 10，Python 3.12.10，moderngl 5.12.0，wgpu 0.32.0，NVIDIA GeForce GTX 1050 Ti，GL 3.3.0
> 全部命令的工作目录 = `Loom/`；探针文件 = `Loom/tests/_tmp/research_01_*.py`（gitignore：`Loom/.gitignore:20`）

---

## ① 现状（证据）

### 1.1 结构事实（复核 beta6 计划的 4 条断言）

| 断言 | 实测 | 证据 |
|---|---|---|
| 两套独立实现 | `loom_render.py` 58,512 B / `vk_renderer.py` 103,985 B | `Get-ChildItem Loom -Filter '*render*'` |
| 全仓 `RenderPass\|class *Pass` 0 命中（代码） | 代码 0；4 处全在文档（`docs/design/版本计划_…beta6….md:87`、`Loom模块化插件化分析.txt`、`docs/handoff/…开发日志…beta5….md`） | 全仓 grep |
| `loom_shaders.py` 只有裸 GLSL | 429 行全是 `#version 330` 字符串（`_VERT_SRC:13` … `_SKY_FRAG:434`），**无任何编译/反射逻辑**；编译点在 `engine.py:302-303`、`loom_shadow.py:29`、`loom_render.py:138,220`、`gui.py:78`、`engine.py:751` | 读文件 + grep `new_program\|program(` |
| 后处理 0 命中 | `(?i)postprocess\|post_process\|postfx\|后处理` 在 `Loom/**/*.py` = **0**；`bloom\|tonemap` = 0（代码）；`ssao` = 0；`msaa\|multisample` 在 `Loom/*.py` 只有 1 处无关命中（`tests/test_frame_pacing.py:173` 变量名） | grep |

补充：`vk_player.py:342-345` 明确记录了"交换链若用 `-srgb` 会二次伽马 → 与 GL 不可能逐像素一致"，因此两端当前都是**线性 8bit 输出 + 着色器内手工 `pow(1/2.2)`**。这是后处理的现实起点（见 ⑤/⑦）。

### 1.2 一帧到底有哪些阶段（实测调用序列）

探针：`py -3.12 tests\_tmp\research_01_frame_trace.py tests\_tmp\ab_sky.json`
（GL 侧 = `EditorApp` + 离屏 FBO，同 `tests/_tmp/ab_gl_vk.py:46-80` 口径；VK 侧 = `VkRenderer` 直接对离屏纹理渲染，同 `ab_gl_vk.py:83-124` 口径）

**GL 播放器（`loom_render.RenderMixin.render`，`loom_render.py:821-981`）实测顺序：**

| # | 阶段 | 行号 | 实测 |
|---|---|---|---|
| 1 | 逻辑/物理/动画步进（非渲染） | 842-887 | — |
| 2 | 世界矩阵 / LOD / 插值矩阵 | 894-906 | — |
| 3 | 阴影 VP 准备 + 桶实例化数据 | 909-915 | `_parallel_shadow_and_collision` ×1、`_prepare_bucket_frame` ×1 |
| 4 | **阴影 pass** | 918 → `loom_shadow.py:64-107` | 每光源每面一次 FBO 绘制（平行光 1 面 / 点光 6 面）；探针实测 dir=1、point=6 |
| 5 | 绑定目标 + 清屏 | 922-924 | `_clear_main_fbo(*CLEAR_COLOR_RGBA)` ×1 |
| 6 | 相机/VP/光照 uniform | 928-951 | `_upload_lights` ×1 |
| 7 | **主 pass 几何** | 953-956 → 744-805 | `_draw_main_buckets` ×1（桶数 2 → 2 次 draw） |
| 8 | **天空** | 960 → 94-196 | `_draw_skybox` ×1（几何**之后**） |
| 9 | World Canvas（离屏+合成 quad） | 964 → 200-353 | 无 world canvas 时 0 次 |
| 10 | HUD 文本 | 968 → `loom_hud.py:68-73` | 实测 `hud lines: 2` |
| 11 | Canvas UI 元素树 | 969-970 → `loom_ui.py:716` | 实测 `ui.draw_all` ×1 |
| 12 | FPS/预取/上屏 | 973-980 | — |

**GL 编辑器（`editor.py:2234-2363`）**：1-9 同构，但**清屏写死字面量** `editor.py:2301`（`0.10,0.12,0.16,1.0`，与 `loom_shaders.CLEAR_COLOR_RGBA:415` 值同源但**不是同一来源**）；天空有额外门判 `editor.effective_skybox() is not None`（2344）；**没有** `_draw_hud`/`ui.draw_all`，叠加层走 `self.view.draw(self, delta_time)`（2353）；帧首强制 `self.ctx.scissor = None`（2236）。

**VK（`vk_renderer.VkRenderer.draw_frame`，`vk_renderer.py:1795-2077`）实测：**

| # | 阶段 | 行号 | 实测（ab_sky / ab_point_shadow） |
|---|---|---|---|
| 1 | 逻辑步进（在播放循环内） | `vk_player.py:576` | — |
| 2 | 光源 VP + 世界矩阵 + 实例数 | 1800-1803 | `_pack_light_vps` ×1 |
| 3 | World Canvas **离屏**（先于主 pass） | 1808-1818 → 1175-1244 | `render_world_canvases` ×1 |
| 4 | scene UBO / 实例缓冲 / 阴影实例缓冲 | 1820-1916 | — |
| 5 | **平行光阴影**（每槽 1 个 render pass，独立 encoder+submit） | 1919-1944 | pass#1 `r32float load=clear` |
| 6 | **点光 6 面**（独立 encoder+submit） | 1946-1986 | 6 个 `r32float` pass（共 7 pass / 15 draw） |
| 7 | 深度纹理 + 取交换链纹理 | 1996-2010 | — |
| 8 | **主 pass**（begin，带 depth32float） | 2012-2017 | pass#2 `rgba8unorm load=clear +depth(depth32float)` |
| 9 | **天空（在主 pass 内、几何之前）** | 2035-2043 → 1028-1063 | `_draw_sky` ×1（`draw(3,1)` 全屏三角） |
| 10 | 几何 | 2044-2053 | 2 次 draw |
| 11 | World Canvas quad（同 pass） | 2056-2061 | — |
| 12 | end + submit + 上屏记账 | 2062-2070 | 合计 **2 pass / 5 draw / 4 pipeline / 3 次 pipeline 切换** |
| 13 | **UI/HUD 独立 pass**（`load_op=load`、无深度） | 2071-2077 → 1074-1114 | 无内容时不产生 pass（`draw_ui:1082-1083` 早退） |

### 1.3 GL / VK 差异点（决定抽象边界的地方）

| 维度 | GL | VK | 差异性质 |
|---|---|---|---|
| 目标数量 | 剩余 1 个目标（窗口 / 宿主 FBO），所有叠加层共用（`loom_render.py:370-379`） | 交换链纹理 + UI 另一个 pass（`2012`/`2071`） | GL 的"HUD 是状态切换"，VK 的"HUD 是 pass" |
| 阴影编码 | **真深度附件**（`loom_shadow.py:51,55,58,60`） | **`r32float` 颜色 + 着色器手工比较**（`vk_renderer.py:785-786, 819-824`） | 同一逻辑 pass，目标"种类"不同 → 抽象必须允许后端改写目标编码 |
| 阴影提交粒度 | 每面 `fbo.use()`（`loom_shadow.py:98-100`） | 每 face 一个 encoder+submit（`1920,1944`；点光 `1951,1986`） | 抽象需 `submit: own \| frame` |
| 天空时机 | 几何**之后**，`depth_func='<='` + `depth_mask=False`（`loom_render.py:184-187`） | 几何**之前**，`depth_compare='always'`、`depth_write=False`（`981-984`） | 视觉等价、机制不同 → 只抽象"语义"，不抽象"指令序" |
| 天空几何 | CPU 6 顶点 quad（`141-147`） | 程序化全屏三角 `draw(3)`（`1062`） | draw 源要可声明 |
| 天空参数 | 3 个具名 uniform（`163-168`） | 一个 112B 打包 UBO（`986-988, 1048-1059`） | 参数块需双打包器 |
| 实例数据 | 桶级 VBO + `vao.render(instances=n)`（`805`） | 160B/实例的 GPU 缓冲 + `rp.draw(nv, n, 0, bstart)`（`1823, 2053`） | 顶点/实例布局要显式描述 |
| 清屏色来源 | 播放器走 `CLEAR_COLOR_RGBA`（924），编辑器写字面量（`editor.py:2301`） | 同一常量（`2014`） | 已有"单源"裁决，编辑器未收口 |
| HUD | 播放器无条件画（`968`） | 默认关，`LOOM_VK_HUD=1` 才画（`vk_player.py:600-609`） | 现有**明确记录**的差异，A/B 不能直接比 HUD |

### 1.4 已存在、可直接复用的能力

- **GL/VK 逐像素 A/B 探针已成熟**：`tests/_tmp/ab_gl_vk.py`（`render_gl:46` / `render_vk:83` / `compare:127`，门槛写在 `ab_active_gl_vk.py:10-11` 与 `ab_batch.py:5`：**MAE ≤ 0.0002**）。本轮实测（`py -3.12 tests\_tmp\ab_batch.py`）：**22 个场景全部 PASS，MAE 0.000000 ~ 0.000082，MAX 最大 0.1255**（`ab_point_shadow.json`）。这就是本设计所有"等价"判据的现实基线。
- **共享计数/判据已有先例**：`PresentHealth` 只在 `loom_render.py:41-73` 定义，VK 复用（`vk_renderer.py:1012-1026`）——证明"一份语义、两后端"在本仓是可行模式。
- **离屏目标已有两种实现**：GL 预画 FBO（`frame_buffer.py:184-206`，RGBA8+深度）与 VK world canvas 纹理（`vk_renderer.py:1139-1163`）、VK mip 生成 pass（`1386-1404`，含 `draw(3)` 全屏三角）。
- **HDR 目标可用性已实测**（`py -3.12 tests\_tmp\research_01_hdr_feasibility.py`）：
  - GL 3.3：`rgba16f` renderbuffer 读回 `2.5` ✅；对其做 `SRC_ALPHA/ONE` 混合得 `5.0` ✅；`rgba32f` 亦可 ✅；`rgba16f` 纹理 + `LINEAR` 采样读回 `3.0` ✅。
  - wgpu：`rgba16float` 目标 + blend pipeline 构建/读回 `2.5` ✅。

---

## ② 目标设计

### 2.1 先回答：Pass 还是 RenderGraph

**推荐 beta6 只做"有序 Pass 列表 + 显式目标声明"（FramePlan），不做依赖求解的 RenderGraph。**

理由（全部基于 1.2/1.3 的事实）：
1. 两端现有执行序**已经是线性**的（GL: 918→924→956→960→964→968；VK: 1919→1946→2012→2071），没有需要自动拓扑排序的分支。
2. 真正的成本不在"排序"，而在**同一件事写两遍**：阴影目标编码、天空时机、参数块打包、pipeline 状态（1.3 六行全部是"同一语义两种表达"）。
3. RenderGraph 的收益（transient 别名、pass 裁剪、异步计算）依赖**读写下标**，而当前代码里根本没有资源读写的显式声明；先建立"声明"这一层，二期再加调度，符合本仓"先铺骨架再要功能"的一贯做法（`docs/design/版本计划…beta6….md:113-114, 129`）。
4. 反过来，直接做 RenderGraph 会立刻引入 barrier/aliasing 的对称性问题：wgpu 自动做状态转移，GL 完全没有 barrier 概念——一期做图只会在一个后端上是"真收益"，违反"两后端共用一份描述"的初衷。

**二期扩展路径**（写在接口里预留，不实现）：给 `PassSpec` 增加 `reads: tuple[str,...]` → 用声明做**校验**（断言顺序合法）而不改执行；三期再上 transient 别名、pass 裁剪、bloom 的 async compute。

### 2.2 最小可行边界：PassSpec = 目标 + 状态 + 着色器 + 绑定 + 参数块 + 绘制源

一次 pass 的**全部**跨后端语义就是这 6 项。任何一项不进描述，就必然在两后端各写一遍——这正是当前 1.3 六大差异的成因。不把"绘制次数/顺序/缓冲具体内容"放进描述（那是 FrameContext 的职责）。

### 2.3 接口草案（dataclass 级，不实现；落地为 `Loom/loom_pass.py` + 两个后端）

```python
# ---- 语义资源描述（不含任何 GL/VK 句柄）----
Format = Literal['rgba8unorm', 'rgba16float', 'r32float', 'depth32float']

@dataclass(frozen=True)
class TargetDecl:                  # 一张帧内目标（由 TargetPool 按尺寸/格式池化）
    name: str                      # 'color.ldr' / 'color.hdr' / 'shadow.dir0' / 'bloom.mip1'
    format: Format = 'rgba8unorm'
    size: Literal['screen', 'shadow', 'fixed'] = 'screen'
    scale: float = 1.0             # 0.5 = 半分辨率链
    fixed: tuple[int, int] | None = None
    depth: Literal['none', 'own', 'shared'] = 'none'
    depth_format: Format = 'depth32float'
    transient: bool = True         # 二期的别名候选标记（一期只做标记）

@dataclass(frozen=True)
class DepthState:
    test: bool = True
    write: bool = True             # GL 端 advisory（见风险 R3）
    func: Literal['less', 'lequal', 'always'] = 'less'
    clear: float | None = 1.0

@dataclass(frozen=True)
class RasterState:
    cull: Literal['none', 'back', 'front'] = 'back'
    front_face: Literal['cw', 'ccw'] = 'cw'
    topology: Literal['triangle-list', 'triangle-strip'] = 'triangle-list'
    blend: Literal['none', 'alpha', 'additive'] = 'none'

@dataclass(frozen=True)
class BindingSpec:                 # 语义槽，而不是 unit / @binding 号
    slot: str                      # 'scene' / 'inst' / 'shadow.dir0' / 'albedo' / 'sampler.albedo'
    stage: Literal['vertex', 'fragment', 'both']
    kind: Literal['uniform', 'texture2d', 'texture2darray', 'texturecube', 'sampler']
    sample_type: Literal['float', 'unfilterable-float', 'depth'] = 'float'

@dataclass(frozen=True)
class ParamField:                  # 参数块字段（GL: 具名 uniform；VK: std140 偏移）
    name: str                      # 'u_view_proj' / 'misc' / 'light0'
    dtype: Literal['f32', 'i32']
    count: int                     # mat4 = 16
    stage: Literal['vertex', 'fragment', 'both'] = 'fragment'

@dataclass(frozen=True)
class VertexLayout:
    buffers: tuple[tuple[str, int, Literal['vertex', 'instance']], ...]  # ('geo', 48, 'vertex')
    attrs: tuple[tuple[str, str, int, str], ...]   # (name, 'f32x3', offset, buffer)

@dataclass(frozen=True)
class DrawCmd:
    source: Literal['buckets', 'instanced_range', 'fullscreen', 'quad_list', 'world_canvas']
    key: str | None = None         # 几何键（GeometryProvider 解析）
    count: int | None = None
    first: int | None = None
    instances: int | None = None

@dataclass(frozen=True)
class PassSpec:
    id: str
    shader: str                    # ShaderKey: 'main' | 'shadow' | 'sky' | 'tonemap' | 'bloom.down'
    target: str                    # TargetDecl.name
    load: Literal['clear', 'load', 'dontcare'] = 'clear'
    clear: tuple[float, float, float, float] | None = None
    depth: DepthState | None = None
    raster: RasterState = RasterState()
    bindings: tuple[BindingSpec, ...] = ()
    params: tuple[ParamField, ...] = ()
    vertex: VertexLayout | None = None
    draws: tuple[DrawCmd, ...] = ()
    submit: Literal['frame', 'own'] = 'frame'   # VK: own = 独立 encoder + submit

@dataclass(frozen=True)
class FramePlan:
    targets: tuple[TargetDecl, ...]
    passes: tuple[PassSpec, ...]    # 顺序即执行序（一期不做拓扑排序，只做校验）
```

**后端协议**（同一份 FramePlan 驱动两套 API 的唯一接缝）：

```python
class PassBackend(Protocol):
    def ensure_target(self, decl: TargetDecl, size: tuple[int, int]) -> object: ...
    def program(self, shader: str, target_fmt: Format) -> object: ...
    def begin(self, spec: PassSpec, target) -> object: ...      # 返回 pass 句柄
    def set_binding(self, h, b: BindingSpec, res) -> None: ...
    def set_params(self, h, fields, values) -> None: ...
    def draw(self, h, cmd: DrawCmd, ctx) -> None: ...
    def end(self, h) -> None: ...
```

### 2.4 它如何同时驱动 moderngl 与 wgpu（映射表）

| PassSpec 字段 | moderngl（`loom_pass_gl.py`） | wgpu（`loom_pass_vk.py`） |
|---|---|---|
| `shader` | `ctx.program(ShaderSet.glsl_vs, .glsl_fs)`，按 `shader` 缓存 | `create_shader_module(ShaderSet.wgsl)` + `create_render_pipeline`，**按 `(shader, target_fmt, depth_fmt)` 缓存** |
| `target` / `load` / `clear` | `TargetPool` → `ctx.texture` / `depth_texture` + `ctx.framebuffer`；`fbo.use()` + `ctx.clear` | `TargetPool` → `create_texture(usage=RENDER_ATTACHMENT\|TEXTURE_BINDING)`；`begin_render_pass(load_op/clear_value)` |
| `bindings` | 按 `slot` 字典序分配纹理单元（**取代现在手写的 0=文字 / 1..=阴影**，`loom_lighting.py:133`）；采样器 uniform 只在建 program 时设一次 | `create_bind_group_layout`（按 slot 排序）+ `create_bind_group`；采样器按 `sample_type` 选 filtering / non-filtering |
| `params` | `_uniform(name)` 句柄缓存（沿用 `loom_lighting.py:81-87`）+ `_u_last` 差分上传 | 一份 UBO，偏移由 `ParamField` 顺序推导；WGSL 侧结构体顺序必须一致（断言测试） |
| `vertex` | `ctx.vertex_array(prog, [(buf, '3f 4f', 'in_pos', 'in_nm')])` 由 `VertexLayout` 生成 | `vertex={'buffers':[{array_stride, step_mode, attributes:[{shader_location, offset, format}]}]}` |
| `raster` / `depth` | `ctx.enable/disable`、`ctx.depth_func`、`ctx.blend_func`、`ctx.front_face`（**每次 begin 全量设置，不做差分**） | pipeline 不可变字段（构建期烘焙） |
| `draws` | `vao.render(TRIANGLES, instances=n)` / `vertices=6`（全屏 quad） | `rp.set_vertex_buffer` + `rp.draw(nv, n, 0, first_instance)` / `rp.draw(3, 1, 0, 0)` |
| `submit='own'` | 无对应概念（GL 指令序即时） | 独立 `create_command_encoder` + `queue.submit`（现阴影路径，`1919-1944`） |
| `submit='frame'` | 同上 | 与主 pass / 后处理共用一个 encoder（后处理必须与主 pass 同 encoder，避免跨提交可见性假设） |

### 2.5 资源句柄的中间表示（问题 3 的正面回答）

**结论：用"语义槽 + 声明"做中间表示，不用原生句柄、也不引 GLSL/SPIR-V 双编译。**

- 句柄：`TextureHandle(slot, format, size, generation)` / `BufferHandle(slot, stride, count, generation)` / `PipelineHandle(shader, target_fmt, generation)`。后端各持 `dict[handle.id] -> native`；`generation` 递增即失效（对标现有 `_ensure_shadow_map` 的缓存思路 `loom_shadow.py:45-62`、VK 的 `_sky_cube_key` 失效判定 `vk_renderer.py:960-962`）。
- **不做 SPIR-V / GLSL 双编译**，三条硬证据：
  1. GL 地板是 `#version 330`（`loom_shaders.py:13` 等 12 处），消费 SPIR-V 需要 GL 4.6 / `GL_ARB_gl_spirv`；本机 `GL_VERSION 330`（探针实测）。
  2. moderngl 5.12 **不提供** SPIR-V 摄取路径（`moderngl.Context` 无相关接口；`requirements.txt:4` 钉 `moderngl>=5.8`）。
  3. wgpu 0.32 不消费 GLSL / SPIR-V（`create_shader_module(code=...)` 只吃 WGSL，见 `vk_renderer.py:737,750,787,968,1369`）。
  引入 glslang / spirv-cross 等于新增原生工具链 + 交叉编译差异风险，收益只是"少写一份镜像"；本仓当前 0 原生工具链依赖（`requirements.txt:3-9` 全为纯 Python 轮子）。
- 替代方案（推荐）：`ShaderSet(key='main', glsl=(vs, fs), wgsl=str, layout=(bindings, params))` —— **镜像仍存在，但被同一份 `layout` 约束住**；加一个测试断言"WGSL 的 `@binding` 集合/顺序 == GLSL 的 uniform 名集合/顺序"（字符串级校验即可，无需 AST）。
- 参数块单源：`ParamLayout` 一张表同时产出 GL 具名 uniform 写入与 VK 的 `f32[352]` 偏移（现状 `vk_renderer.py:1717-1774` 的 352 float 手工排布 = 与 GL 具名 uniform 逐值对齐，靠人肉维持，是当前最大的隐性耦合）。

---

### 2.6 后处理链第一步（tonemap + bloom）的具体挂点与新资源

**排序约束（硬）**：主 pass → （bloom，全在 HDR 空间）→ tonemap → HUD/UI。理由：HUD/UI 是 UI 颜色，不能被 tonemap 二次调色；bloom 必须在 HDR 上做（8bit 目标上做加法会立刻削顶）。

**GL 挂点（两处，必须同时改）**

| 位置 | 现状 | 改法 |
|---|---|---|
| `loom_render.py:922` | `self._screen_fb().use()`（主 pass 直接写窗口 / 宿主 FBO） | 改为 `targets.acquire('color.hdr').use()`；深度附件挂在 `color.hdr` 的 `TargetDecl(depth='own')` |
| `loom_render.py:964-968` 之间 | world canvas 之后、`_draw_hud` 之前**没有**挂点 | 插入 `bloom.*` 与 `tonemap` 的 pass；tonemap 的目标 = `_screen_fb()`（保持 4/8 号契约不变） |
| `editor.py:2349-2353` | `mt_main_pass` 结束 → `view.draw` | 同一位置插入后处理（编辑器与播放器共用同一个 `FramePlan` builder，见 R7） |
| `frame_buffer.py:296-304` | `copy_framebuffer(target_fb, self._fbo)` 整块上屏 | 预画离屏 FBO 必须扮演 `color.ldr` 的角色（`_external_fb` 指向它），否则预画出来的是 HDR 未 tonemap 的图 |

**VK 挂点（一处）**

| 位置 | 现状 | 改法 |
|---|---|---|
| `vk_renderer.py:2012-2017` | 主 pass 的 color attachment = 交换链 `view` | 换成 `color.hdr` 的 view；`view` 只在 tonemap pass 使用 |
| `2062-2071` 之间 | `rp.end()` + `queue.submit` 之后直接 `draw_ui` | 在**同一个 encoder** 里追加 bloom / tonemap pass（`submit='frame'`），最后 `submit` 一次；`draw_ui` 仍以 `view` 为 `load_op=load` 目标（`1107-1110`），语义自然正确 |
| `1996-2000` | 深度纹理按屏幕尺寸建 | 改为跟随 `color.hdr`（同尺寸；若 `color.hdr` 也全分辨率则逻辑不变） |

**新增资源清单（全部可由 `TargetDecl` 表达）**

| 资源 | 格式 | 尺寸 | 用途 | 备注 |
|---|---|---|---|---|
| `color.hdr` | `rgba16float` | screen | 主 pass 目标 | 需 `depth='own'`（`depth32float`）；GL 侧实测可建、可读回 `2.5` |
| `bloom.bright` | `rgba16float` | screen × 0.5 | 亮度提取 | 半分辨率起点 |
| `bloom.down1` | `rgba16float` | screen × 0.25 | 降采样 / 模糊 | 二期可扩到 3~4 级 mip 链 |
| `bloom.up` | `rgba16float` | screen × 0.5 | 升采样 | 与 `color.hdr` 做 additive 合成（blend=additive） |
| `color.ldr` | 交换链格式 / `_screen_fb()` | screen | tonemap 输出、HUD/UI 目标 | **不是**新分配：就是今天的最终目标，保持契约 |

**新增 shader（两份镜像，仍走 `ShaderSet`）**：`tonemap`（全屏三角、读 `color.hdr` + 曝光参数、写 `color.ldr`，gamma 公式与今日 `pow(1/2.2)` 逐位一致）、`bloom.bright` / `bloom.down` / `bloom.up`（均无顶点缓冲，`draw(3)` / 4 顶点 quad；VK 已有 `draw(3)` 先例 `1062`、`1402`；GL 已有 `_quad_vbo` 先例 `loom_render.py:141-147`）。

**采样约束（已实测的部分）**：GL `rgba16f + LINEAR` 读回 `3.0` ✅；VK `rgba16float` 作为 `sample_type='float'` + filtering sampler 组合属标准路径，但**本轮未实测**——列为 S5 的第一个验收点（不达标则退回 `unfilterable-float` + 手动双线性，代价 +0.5 人天）。

---

## ③ 分步落地计划（每步可验收、含测试点）

> 纪律：每步一个可回退提交；每步**先测后改**；每步结束跑 `ab_batch.py`（22 场景）保持 0 失败。
> 基线（本轮实测，作为回归闸门）：`ab_c_dir_only 0`、`ab_sky 0.000017`、`ab_c_dir_shadow 0.000071`、`ab_plane_sphere 0.000052`、`ab_point_shadow 0.000063`、`ab_scene 0.000068`、`ab_ui_scene 0.000082`。

| 步 | 内容 | 验收（可执行） | 测试点 |
|---|---|---|---|
| **S0** | 地基：新增 `loom_pass.py`（spec）/ `loom_pass_gl.py` / `loom_pass_vk.py`（空后端）；把 A/B 探针**从 _tmp 提升为受跟踪** `tests/pass_ab.py`（现 `ab_gl_vk.py:46-146` 原样搬迁）；`FramePlan` 只做"能构造、能校验" | `py tests\test_pass_spec.py` 全 PASS；`py tests\_tmp\ab_batch.py` 仍 0 失败 | ① 同一份 FramePlan 在 GL 后端产出与今日相同的 program 数（4）；② 在 VK **假设备**（复用 `tests/test_vk_two_dir_shadow.py:93-116` 的 `_FakeDevice`）上产出相同 pipeline / bind-group 计数（今日实测 4 pipeline / 4 shader module） |
| **S1** | 迁 **天空**（最小闭环）：`PassSpec('sky', target='color.ldr', load='load', depth=lequal/no-write, raster=cull none, draws=[fullscreen])`；顺手**删掉假状态** `ctx.depth_mask` 写入（`loom_render.py:184,192`）+ world canvas 同类（`343,351`）——moderngl 5.12 无此 API，实测为"静默无效"（见 R3） | `ab_sky` MAE ≤ 2e-5（基线 1.7e-5）；`ab_plane` / `ab_cube` MAE ≤ 1e-5 | ① 画面：`ab_sky` 的 GL/VK 图 `MAX` 不得劣化；② 状态：日志不得再出现 `[渲染] 天空盒 ... depth 状态` 告警；③ 语义：VK 侧 `_draw_sky` 的 `buf[0:16]/[16:19]/[20:23]` 与 GL 三个 uniform 逐值比对（新增断言，锁住双打包器） |
| **S2** | 迁 **主 pass**：`PassSpec('main', target='color.ldr', load='clear', clear=CLEAR_COLOR_RGBA, depth=own, draws=[buckets])`；桶级 uniform（`loom_render.py:756-804`：`u_albedo/u_normal_map/u_env/u_metallic/u_roughness/u_material_pbr/u_has_env/u_env_max_lod`）改为 `ParamField` + 逐桶派生值；编辑器入口 `editor.py:2334-2348` 改为**复用同一 builder**，不再复写 | `ab_batch` 22 场景全 PASS 且每个 ≤ 基线 + 1e-5 | ① 绘制序 / 实例数：用 `research_01_frame_trace.py` 的桶序做 oracle（改前 / 改后逐项相等）；② 像素：22 场景矩阵；③ 编辑器：`py tests\test_skybox_engine_parity.py`（现有 272 行）+ 编辑器清屏改走 `CLEAR_COLOR_RGBA`（`editor.py:2301`）后 GL 图不变 |
| **S3** | 迁 **阴影**：`PassSpec('shadow.dirN')` / `('shadow.pointN.faceF')`；`TargetDecl(depth='own', format='depth32float')` + 后端能力位 `shadow_encoding`（取 `depth` 或 `r32float`；VK 翻译为现有 `r32float` + 手工比较） | `ab_c_dir_shadow` ≤ 7.1e-5、`ab_point_shadow` ≤ 6.3e-5、`ab_plane_shtrue/shfalse` 不变 | ① pass 数：VK dir=2 / point=7（本轮实测值）必须不变；② 面数：GL 每光源 6 面不变；③ 语义：`_pack_scene` 中 `params.w` 槽位（`vk_renderer.py:1770`）与 GL 阴影槽位逐灯一致（已有 A/B 覆盖） |
| **S4** | 迁 **HUD / UI**：`PassSpec('ui', target='color.ldr', load='load', depth=None, blend=alpha)`；GL 侧 HUD 与 `ui.draw_all` 合并为一次 begin/end（文本 quad 与 Canvas 元素树同批） | `ab_ui_scene` ≤ 8.2e-5；GL HUD 墨迹 bbox 逐像素一致 | ① 混合态：`ctx.scope`（`loom_hud.py:111,128`）语义不变；② VK：默认关 HUD（`vk_player.py:600-609`）行为不变；③ 事件：`draw_ui` 的 `engine` 透传（`1099`，P0 修复）不得丢 |
| **S5** | 后处理①：`color.hdr`（rgba16float）接管主 pass，新增 `PassSpec('tonemap', target='color.ldr', draws=[fullscreen])`；**gamma 公式必须唯一**（现在两端各写 `pow(1/2.2)`，`vk_player.py:342-345`） | ① 纯 tonemap 输出与 `pow(c,1/2.2)` 差 ≤ 1/255（合成图单元测试）；② `ab_batch` 22 场景 ≤ 2e-4（等价今日口径）；③ HDR 目标创建失败时降级为直写 LDR 并告警一次 | ① 精度：`rgba16f` 读回 `2.5`（已实测）；② 目标池：resize / 切换场景不泄漏（对标 `frame_buffer.py:306-334` 的 `_release` 顺序）；③ Qt 宿主 FBO 路径（`_external_fb`）与预画 blit（`frame_buffer.py:296-304`）都仍落到**最终 LDR 目标** |
| **S6** | 后处理②：bloom（半分辨率链：`bloom.bright(H/2)` → `bloom.down1(H/4)` → `bloom.up` → 合成 add 到 `color.hdr`），`scale=0.5` 由 `TargetDecl` 表达 | ① bloom off 时逐字节等于 S5 输出（png 全等）；② bloom on：无 NaN/Inf，最大亮度 ≤ 阈值；③ 帧耗：5 场景 `mt_render_total` 增量 ≤ 15% | ① 目标格式：VK 现有 mip 生成把目标格式写死 `rgba8unorm`（`vk_renderer.py:1381`），半分辨率链必须是 `rgba16float` → S6 前先修此硬编码；② 采样滤波：GL 侧 `rgba16f + LINEAR` 已实测读回 `3.0`；VK 侧 `sample_type='float'` + filtering sampler（列入 S5 首个验收点） |

---

## ④ 风险与回滚

| # | 风险 | 证据 / 机制 | 缓解 | 回滚 |
|---|---|---|---|---|
| R1 | 像素等价回归（跨后端） | 今日基线 MAE ≤ 8.2e-5、MAX ≤ 0.1255（22 场景） | 每步跑 `ab_batch`（0 失败为闸门），每步独立提交 | 逐步 `git revert`（每步一个提交，互不依赖） |
| R2 | VK pipeline 与目标格式绑死 | pipeline 在构建期烘焙 `self.format`（`vk_renderer.py:748,784,984`），而 mip pass 写死 `rgba8unorm`（`1381`）；交换链可能是 `bgra8unorm`（`vk_player.py:336-358` 显式剥 `-srgb`） | `PipelineHandle` 的 key 必须含 `(shader, target_fmt, depth_fmt)`；加"换格式必须重建"的单测（假设备） | 去掉格式字段 = 恢复现状，但 S5 会立刻踩到 |
| R3 | **GL 无法表达 depth_write=False** | 实测：`moderngl 5.12.0` 的 `Context` **无** `depth_mask` 属性；`ctx.depth_mask = False` 只是给 Python 对象加了实例属性（实测输出 `class has: False` / `instance now has: True False`），**GL 深度写掩码未变**。现有天空 / 世界 quad 的"不写深度"是**假的**，实际靠"最后画 + LEQUAL 等值通过" | `DepthState.write` 记为 **advisory**，文档写明；不引入新依赖去碰 GL 私有扩展；测试断言**像素**而非状态 | 保留现状（本来就没生效），只是把假状态从代码里删掉 |
| R4 | GL 状态泄漏（全局状态机） | `loom_hud.py:111` 用 `ctx.scope` 保存/恢复；天空手动存取 `depth_func`（`loom_render.py:177-196`）；编辑器帧首清 scissor（`editor.py:2236`）——说明状态确实会漏 | 每个 pass **begin 时全量声明**（不做差分），`ctx.scope` 作为兜底 | 保留 `scope` 用法，按 pass 回退到旧写法 |
| R5 | 后处理必须在主 pass 同 encoder（VK） | 现阴影是 `own` 提交（`1920,1944`），后处理若也 `own` 会产生跨提交可见性假设 | `submit='frame'` 用于主 pass + tonemap + bloom；`own` 只给阴影 | 后处理拆成独立提交 + 每 pass 前空转 `queue.submit`（性能退化但可回） |
| R6 | HUD 非逐像素等价 | `vk_ui.py:48-60` 已记录：三角带 vs line-list 有 0.56% 像素差、MAE 0.00357；VK HUD 默认关（`vk_player.py:600-609`） | HUD pass 的判据改为 `MAE ≤ 5e-3 + 墨迹 bbox 相等`，**不承诺逐像素** | HUD 留在抽象外（只做 UI 元素树 pass） |
| R7 | 双入口（编辑器 / 播放器）分叉 | `editor.py:2234` 覆写 `render`，与 `loom_render.py:821` 各写一遍阶段序（清屏、天空门判、HUD） | S2 起编辑器 render 只做"build plan + 提交"，阶段序唯一 | 编辑器保留旧 render（回退面小） |
| R8 | 证据不可复现 | 最有力的 A/B 探针在 `tests/_tmp/`（`Loom/.gitignore:20` 忽略），干净 clone 下**无法重跑本报告的实测** | S0 必须把它提升为受跟踪 `tests/pass_ab.py` | 无（不提升则本设计无法验收，属前置条件） |
| R9 | 无 CI、依赖本机 GPU | 全仓无 pytest 配置 / 无 CI；测试是 `py tests/test_x.py` + `FAIL` 行改退出码（`test_vk_two_dir_shadow.py:6-30`） | 判据用**数值容差**而非哈希；无 GPU 时 skip 并打印原因 | 单测只留"规格 / 布局"类（无 GPU 可跑），像素类走 A/B |

---

## ⑤ 工作量估计（人天 / 会话数）

| 项 | 人天 | 说明 |
|---|---|---|
| S0 地基 + A/B 提升 | 2.5 | 新增 3 个模块骨架 + 1 个受跟踪测试助手 + 迁移约 150 行探针 |
| S1 天空 | 1.5 | GL / VK 各 0.5，测试 0.5（最划算的第一步） |
| S2 主 pass | 3.0 | 桶级参数改 `ParamField` + 编辑器入口收口（R7） |
| S3 阴影 | 2.0 | 目标编码能力位 + 面数 / pass 数回归 |
| S4 HUD / UI | 1.5 | 混合态与事件透传 |
| S5 tonemap + HDR 目标 | 1.5 | 目标池 + 公式单源 + 降级 |
| S6 bloom（半分辨率链） | 2.5 | 含修 VK mip 格式硬编码 |
| 回归 / 文档 / 登记 | 1.0 | 22 场景 × 每步 + `docs/design/_README.md` 登记 |
| **合计** | **约 15.5 人天** | 按"一次会话 1.5–2 人天（双后端 + 测试）"折算 **约 8–10 个会话** |
| 一期（S0 + S1 + S2 + S5-tonemap）最小可见收益 | 约 8.5 人天 / 4–5 会话 | 出"共用 description + 一份 HDR 后处理挂点" |

---

## ⑥ 与现有代码的兼容边界

**必须保持不变（改动即破契约）：**

1. 场景 JSON / `sceneio` 格式：`PassSpec` 纯内部，不落地到文件。
2. `PresentHealth` 单实现（`loom_render.py:41-73`）与 `present_health()/should_fallback_remote()` 语义（`1024-1034`、`vk_renderer.py:1012-1026`）——上屏降级判据在两后端已同源。
3. `effective_skybox()` 单一判定源（`loom_render.py:109`、`vk_renderer.py:2027`、`editor.py:2344`）：Pass 只消费，不重算。
4. `_screen_fb()` / `_external_fb` 契约（`loom_render.py:370-379`）：预画（`frame_buffer.py:243-265`）靠临时改写 `_external_fb` 实现，后处理链的"最终 LDR 目标"必须仍是它。
5. VK `draw_frame(ctx, models, lights, vp, camera_pos, interp=..., sky=..., ui=..., hud_lines=..., cam_basis=..., engine=...)` 签名（`1795-1796`）：被 `ab_gl_vk.py:103-107` 与 `tests/test_vk_two_dir_shadow.py` 直接调用。
6. GL `render(delta_time)` 入口与 `advance_logic` 分离协议（`loom_render.py:842-877`）：Pass 只接管渲染段，不碰逻辑推进 / 插值。
7. 编辑器 `view.draw(self, delta_time)` 仍在 3D 之后（`editor.py:2353`）；Gizmo / 拾取（`2356-2357`）不变。
8. HUD / UI 必须**在 tonemap 之后**（它们是 UI 颜色，不该被后处理二次调色）。
9. 测试形态：`py tests/test_x.py` + `check()` + `FAIL` 行闸门，不引入 pytest 依赖。
10. 依赖清单不变（`requirements.txt:3-9`）：**不新增** glslang / spirv-cross。

**允许变化（有意识改动，需在提交说明里写明）：**

- 主 pass 输出从"直接写交换链 / 宿主 FBO"变为"写 `color.hdr`，再由 tonemap 写最终目标"（S5）——GL 上多 1 次全屏绘制；VK 上交换链纹理从主 pass 附件降级为 tonemap 的附件。**8bit 目标上的舍入点后移**，可能出现 ±1 LSB 差异（今日 MAE 已 ≤ 8.2e-5，预算内）。
- 编辑器清屏改走 `CLEAR_COLOR_RGBA`（值与现值相同）。
- 删除 `ctx.depth_mask` 的无效赋值（R3，行为不变）。
- 新增 `Loom/loom_pass*.py` 与 `Loom/tests/pass_ab.py` 两类新文件。

**文档维护冲突（需上层处理）**：`docs/design/_README.md:36` 规定"新增设计文档必须在本索引登记"。本任务只允许写报告一个文件，**索引登记未做**，请由主代理或人类补登记一行（`research_beta6_01_render_pass.md`）。

---

## ⑦ 需要人类裁决的封闭问题

| # | 问题 | 选项 | 影响面 |
|---|---|---|---|
| Q1 | GL 3.3 是否仍是地板？ | A 保持 3.3（现状，本机实测）／B 提到 4.6 以便 SPIR-V 与分层阴影 | 若 B，"不做 GLSL/SPIR-V 双编译"的结论需重估；若 A，GPU 特性上限锁死 |
| Q2 | 主 pass 是否**永远**走 HDR（即使 bloom 关） | A 永远 HDR（管线唯一、舍入点后移）／B 按需切换（两条路径，违背"一份描述"） | S5 的实现复杂度与像素回归面 |
| Q3 | beta6 是否连**编辑器**入口一起迁（`editor.py:2234`） | A 一起迁（消除 R7 双入口）／B 只迁播放器，编辑器下期 | 工作量 +1.0~1.5 人天；不迁则双入口继续漂移 |
| Q4 | 阴影目标编码是否统一 | A 保留现状（GL depth 附件 / VK r32float），抽象里做"能力位"／B VK 改真深度附件（大改） | B 会动 `vk_renderer.py:819-824` 与阴影着色器，回归面大 |
| Q5 | 点光 6 面是否合并为 1 个 pass（VK 分层附件 / GL cubemap 附件） | A 本期不合并（6 pass，实测 7 pass / 15 draw）／B 本期合并 | B 两端都要改阴影目标结构，S3 翻倍 |
| Q6 | HUD 是否继续保持"已知非逐像素等价" | A 保持（`vk_ui.py:48-60` 契约）／B 借 Pass 抽象统一描边光栅化 | A 则 HUD pass 只验 bbox / MAE ≤ 5e-3；B 是独立战役 |
| Q7 | A/B 探针是否提升为受跟踪测试（`tests/pass_ab.py`，+约 150 行） | A 提升（否则 R8 无法验收）／B 不提升（本设计不可复现） | 影响"真实证据"纪律能否成立 |
| Q8 | 新模块命名 | A `loom_pass.py` / `loom_pass_gl.py` / `loom_pass_vk.py`／B 并入 `loom_render.py` + `vk_renderer.py` | B 会让 60KB / 100KB 两个文件继续膨胀（当前 1970 行 / 429 行镜像） |

---

## 附：本报告全部实测命令（工作目录 `Loom/`）

```powershell
py -3.12 tests\_tmp\research_01_frame_trace.py tests\_tmp\ab_sky.json        # 帧阶段 / 每 pass / draw 计数
py -3.12 tests\_tmp\research_01_frame_trace.py tests\_tmp\ab_point_shadow.json
py -3.12 tests\_tmp\ab_batch.py                                             # 22 场景 GL/VK MAE 基线
py -3.12 tests\_tmp\ab_gl_vk.py tests\_tmp\ab_sky.json tests\_tmp\research01_sky
py -3.12 tests\_tmp\research_01_hdr_feasibility.py                          # rgba16f/32f 目标 + 混合
py -3.12 -c "import moderngl;c=moderngl.create_standalone_context();print(hasattr(moderngl.Context,'depth_mask'))"
```

**实测输出要点（逐字摘录）**：

- GL 顺序：`_prepare_bucket_frame` ×1 → `_render_shadow_maps` ×1（`shadow_face_draw` ×1）→ `_clear_main_fbo` ×1 → `_upload_lights` ×1 → `_draw_main_buckets` ×1 → `_draw_skybox` ×1；`buckets: 2`、`shadow_faces_drawn_total: 2`（2 帧累计）。
- VK 顺序：`BEGIN_PASS#1 r32float load=clear` → `BEGIN_PASS#2 rgba8unorm load=clear +depth(depth32float)`；`render_passes: 2, draw_calls: 5, pipelines_built: 4, pipeline_switches: 3`。
- 点光场景：VK `render_passes: 7 / draw_calls: 15 / draws_by_pass 1..6 各 2、7 号 3`。
- `场景数 22, 门槛 MAE <= 0.0002, 失败 0 / 全部通过`。
- `[GL] HDR 读回中心像素 = [2.5, 0.25, 0.0]`、`混合后 = [5.0, 0.5, 0.0]`、`rgba32f = [2.5, 0.25, 0.0]`、`rgba16f sampler+linear = [3.0, 0.5, 0.0]`。
- `[VK] rgba16float 中心像素 = [2.5, 0.25, 0.0]`。
