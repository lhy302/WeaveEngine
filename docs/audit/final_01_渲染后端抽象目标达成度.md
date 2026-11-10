# final_01 · 渲染后端抽象目标达成度（beta6 最终验收审计）

> 审计编号：01 ｜ 主题：渲染后端抽象化 / 停止多后端代码分裂 ｜ 日期：2026-11-10
> 审计方式：只读（未改任何受跟踪文件；探针仅写 `Loom/tests/_tmp/final_01_*.py`，该目录被 `Loom/.gitignore:22` 忽略）
> 判定口径：本报告的"完成度"一律给出分母；不接受"看起来已完成"。

---

## 0. 范围与基线

### 0.1 基线事实（实测，与派单书数字不一致，以实测为准）

```powershell
git rev-parse HEAD          # a0b0ae088ae1cb63e852ae37d87566ec0c42de71
git rev-parse 08ad3a3       # 08ad3a361b90cccbaeacbcff68cd1acc13033f2a
git diff --stat 08ad3a3..HEAD | Select-Object -Last 1
# 197 files changed, 26283 insertions(+), 875 deletions(-)
git status --porcelain      # （空）
```

- 派单书写"189 文件 / +23580 / -837"，实测 **197 / +26283 / -875**（差 8 文件 / +2703 / -38）。差异来自派单后又落了 3 个 docs/audit 提交（`a0b0ae0` 等）。**本报告所有数字以 `08ad3a3..a0b0ae0` 实测为准**。

### 0.2 审计范围（9 文件）

`Loom/loom_pass.py`、`loom_pass_gl.py`、`loom_post.py`、`loom_post_gl.py`、`loom_render.py`、`vk_renderer.py`、`engine.py`、`editor.py`、`loom_shaders.py`。

### 0.3 行数口径声明（**重要**，避免与其它轮次数字冲突）

本报告用 Python `str.splitlines()` 计数（**含空行**），且与 `git diff --numstat` 自洽（例：`loom_render.py` 1090 − 69 + 275 = 1296 ✓）。PowerShell `Measure-Object -Line` 会**跳过空行**，同一文件只报 1236 行 —— 若看到 1236/1042 这类数字，那是另一口径，不是另一个版本。

| 文件 | beta5 (08ad3a3) | beta6 (HEAD) | Δ |
|---|---:|---:|---:|
| loom_render.py | 1090 | 1296 | +206 |
| vk_renderer.py | 2077 | **2309** | +232 |
| loom_pass.py | — | **297** | +297（新） |
| loom_pass_gl.py | — | **234** | +234（新） |
| loom_post.py | — | **64** | +64（新） |
| loom_post_gl.py | — | **204** | +204（新） |
| loom_shaders.py | 449 | 449 | 0 |
| engine.py | 1754 | 1784 | +30 |
| editor.py | 2737 | 2877 | +140 |

**聚合（③）**：

| 侧 | beta5 | beta6 | Δ |
|---|---:|---:|---:|
| GL 专属（loom_render + loom_pass_gl + loom_post_gl） | 1090 | **1734** | **+644 (+59.1%)** |
| VK 专属（vk_renderer） | 2077 | **2309** | **+232 (+11.2%)** |
| 共享描述（loom_pass + loom_post） | 0 | **361** | +361 |
| 合计 | 3167 | **4404** | +1237 (+39.1%) |
| VK−GL 差值 / 比值 | 987 / 1.91 | **575 / 1.33** | 收窄 |

### 0.4 跑过的命令（全部可复现）

```powershell
py -3.13 tests/test_frame_plan.py                                  # 49 PASS / 0 FAIL / ALL PASS
py -3.13 tests/_tmp/final_01_probe.py                              # 结构/行数/字段消费统计
py -3.13 tests/_tmp/final_01_shaders.py                            # WGSL/GLSL 字面量行数
py -3.13 -c "import moderngl;c=moderngl.create_standalone_context();print(hasattr(moderngl.Context,'depth_mask'))"
git show 08ad3a3:Loom/loom_shaders.py | Select-String CLEAR_COLOR_RGBA
git show --stat eba750f / 6861603                                  # 批次 A 两个功能提交的落点
```

---

## 1. 目标达成判定表

**被审目标（原文）**：「渲染后端抽象化、停止多种后端的代码分裂」。
**设计承诺**（`docs/design/research_beta6_01_render_pass.md` §2.3 / §③ S0-S6）：PassSpec = 目标 + 状态 + 着色器 + 绑定 + 参数块 + 绘制源 六项，"任何一项不进描述，就必然在两后端各写一遍"；S0 要建 `loom_pass_vk.py`（空后端）并用假设备断言 VK 产出同样的 pipeline/bind-group 计数。

### 1.1 ① FramePlan 共享了什么（6 项，实测）

| # | 共享项 | 证据 |
|---|---|---|
| 1 | pass 顺序与 9 个 pass id 词表 | `loom_pass.py:186-296`；实测 `pass_ids_declared` = shadow_maps/main/sky/world_ui/bloom.bright/bloom.down/tonemap/hud/ui |
| 2 | 目标语义名与格式 | `loom_pass.py:199-224`（color.ldr/color.hdr/bloom.half/bloom.quarter/shadow.depth）、`loom_post.py:16-18` |
| 3 | 清屏色单源 `CLEAR_COLOR_RGBA` | `loom_shaders.py:415`；VK `vk_renderer.py:32,2244`；**编辑器字面量已删**（beta5 `editor.py` 有 `_clear_main_fbo(0.10,0.12,0.16,1.0)`，beta6 无） |
| 4 | 后处理参数/阈值/开关 | `loom_post.py:26-64`；GL `loom_post_gl.py:172`、VK `vk_renderer.py:1009` 都调 `params()`；两端都用 `post_enabled()` |
| 5 | 深度/光栅/混合**声明** | `DepthState/RasterState`，GL 执行器按声明 apply/restore（`loom_pass_gl.py:141-186`） |
| 6 | 9 个绘制源语义名 | `loom_pass.py:79-81`；`loom_pass_gl.py:223-234` 全部注册 |

### 1.2 ① FramePlan **没有**共享什么（14 项，逐项给行号）

| # | 语义面 | GL 侧 | VK 侧 | 是否同一实现 |
|---|---|---|---|---|
| 1 | 目标分配 | `loom_pass_gl.py:48-68`（只按 name 解析）+ `loom_post_gl.py:111-140`（自建 FBO） | `vk_renderer.py:918-935`（自建 texture） | 两份 |
| 2 | 阴影编码 | 真深度附件 + `sampler2DShadow`：`loom_shadow.py:51-60`、`loom_shaders.py:82,133-169` | `r32float` + 手工比较：`vk_renderer.py:1083-1107,153-178,284-303` | 两份 |
| 3 | 阴影提交粒度 | 立即模式逐面 `fbo.use()`：`loom_shadow.py:98-100` | 逐面 `encoder+submit`：`vk_renderer.py:2164,2206` | 两份 |
| 4 | 天空时机 | 几何**之后** + LEQUAL：`loom_pass.py:236-246` | 几何**之前** + `depth_compare='always'`：`vk_renderer.py:1196-1197,2248-2273` | 两份（plan 只编码了 GL 语义） |
| 5 | 天空几何 | CPU 6 顶点 quad：`loom_render.py:144-147` | `draw(3)` 全屏三角：`vk_renderer.py:1277` | 两份 |
| 6 | 天空参数块 | 3 个具名 uniform：`loom_render.py:166-171` | 112B UBO：`vk_renderer.py:1202-1203,1263-1274` | 两份 |
| 7 | 实例数据布局 | 桶级 VBO + `vao.render(instances)`：`loom_render.py:873-962` | 定长实例缓冲 + `draw(nv,n,0,bstart)`：`vk_renderer.py:2276-2283` | 两份 |
| 8 | HUD/UI 叠加 | plan 里 2 个 pass + `loom_ui.draw_all` | 独立 render pass + `VkUIEngine`：`vk_renderer.py:2303+` | 两份 |
| 9 | 着色器源码 | GLSL 398 行（`loom_shaders.py`）+ 56 行后处理 GLSL | WGSL **458 行**（`vk_renderer.py` 8 个字面量：57/247/37/11/5/29/58/14） | 两份（0 行共享） |
| 10 | 绑定槽 | texture unit / 具名 uniform | `@group(0)@binding(N)`：`vk_renderer.py:134-151` | 两份 |
| 11 | 参数块打包 | 14 组具名 uniform：`loom_lighting.py:89-225` | `f32[352]` std140：`vk_renderer.py:70,1937-1994` | 两份 |
| 12 | mip 生成 | 驱动 `tex.build_mipmaps()`：`loom_cubemap.py:203` | 手写 downsample 管线：`vk_renderer.py:1582-1624`（注释自认"与 GL 的 mipmap=True 对齐"：1607） | 两份 |
| 13 | 后处理管线构建 | `ctx.program`：`loom_post_gl.py:142-150` | `create_render_pipeline`：`vk_renderer.py:954-973` | 两份 |
| 14 | `submit` 粒度 | 无（立即模式，`loom_pass_gl.py:96-120`） | 3 次 `queue.submit`：`vk_renderer.py:2164,2206,2295` | `PassSpec.submit`（`loom_pass.py:100`）**零消费者** |

### 1.3 ② 后处理：GL 与 VK 的行数与"是否两份独立实现"

| | GL | VK |
|---|---|---|
| 位置 | `Loom/loom_post_gl.py` 全文件 **204 行** | `Loom/vk_renderer.py` **内嵌 202 行** |
| 着色器 | GLSL **56 行**（`_VS`8 / `_BRIGHT`14 / `_DOWN`13 / `_UP`7 / `_TONEMAP`14，行 18-77） | WGSL **58 行**（`_POST_WGSL`，行 474-532） |
| 目标/管线/绘制 | `ensure` 111-140、`_program` 142-150、`draw` 171-204（合计 **148 行 py**） | `_ensure_main_pipe` 896-916(22) + `_ensure_post_targets` 918-935(19) + `_ensure_post_pipes` 937-982(46) + `_ensure_post_groups` 984-1004(22) + `_record_post` 1006-1038(34) = **143 行 py** |
| 共享的部分 | 仅 `loom_post.py` 的 4 个参数 + 开关（64 行），**0 行着色器/0 行管线代码** | 同左 |

**结论：是两份独立实现。** 4/4 个阶段（bright / down / up / tonemap）在 GLSL 与 WGSL 各写一遍；同一公式（`pow(2.2)` → 亮度 0.2126/0.7152/0.0722 → smoothstep(threshold,knee) → Reinhard `c/(1+c)` → `pow(1/2.2)`）存在 2 份文本（`loom_post_gl.py:35-39,71-76` vs `vk_renderer.py:498-530`）。后处理是本轮**新增**的重复实现：**406 行（204+202）全部是两端各一份，占本轮新增 1237 行的 32.8%**。

### 1.4 ③ 分裂是缩小了还是扩大了

三个可量化指标，结论不一致，必须一起看：

| 指标 | beta5 | beta6 | 判定 |
|---|---|---|---|
| GL/VK 行数比 | 1.91 | **1.33** | 数字"收窄" |
| VK−GL 绝对差 | 987 | **575** | 收窄 |
| **VK 侧消费共享描述的行数** | 0 | **0** | **无变化** |
| **两端各写一遍的语义面数** | 13 | **14**（+后处理） | **扩大** |
| 已闭环为单源的语义面 | 0 | **1**（清屏色） | +1 |
| 新增一个后处理效果的代码落点 | — | **8 个代码文件 / 792 行**（`eba750f`），其中后端专属实现仍 **2 处** | 未减少 |

- "比例收窄"是**分子分母同时膨胀的副产品**：GL 侧 +644 行 = 新增 4 个文件中 438 行 GL 专属实现（loom_pass_gl 234 + loom_post_gl 204）+ loom_render.py 内 +206 行改造；共享层另 361 行（loom_pass 297 + loom_post 64）。VK 侧 +232 行**全部是新功能，0 行是适配共享层**（`git diff 08ad3a3..HEAD -- Loom/vk_renderer.py` 的 9 行删除全部在 VK 内部：格式参数化、mip 格式、pipe 缓存键）。
- 因此：**分裂没有缩小，只是被一层"只服务 GL"的描述层部分遮盖；VK 的每一个 pass 仍是自己写的。**

### 1.5 ④ "同一逻辑写两遍"具体清单（7 项指定 + 4 项新增）

| # | 逻辑 | GL | VK | 重复性质 |
|---|---|---|---|---|
| 1 | 阴影编码 | `loom_shadow.py:51-60`（depth_texture）、`loom_shaders.py:82`（sampler2DShadow）、`133-169`（PCF） | `vk_renderer.py:1083-1107`（r32float）、`153-178,284-303`（手工 `d >= depth - bias`） | 目标类型不同 + 比较逻辑重写 |
| 2 | 参数块 | `loom_lighting.py:89-225`（14 组具名 uniform，137 行） | `vk_renderer.py:1937-1994`（f32[352] 偏移打包，58 行） | 同一光源模型的 2 个打包器 |
| 3 | 天空时机 | plan 声明"几何后 + lequal"（`loom_pass.py:236-246`），实现在 `loom_render.py:97-199` | "几何前 + always"（`vk_renderer.py:1196-1197, 2248-2273`） | plan 只编码 GL 语义，VK 无法用它 |
| 4 | submit 粒度 | 立即模式（`loom_pass_gl.py:96-120`） | `2164/2206/2295` 三次 submit | `PassSpec.submit` 字段存在但**无人读**（全仓 0 引用） |
| 5 | mip 生成 | `loom_cubemap.py:203` 一行驱动调用 | `vk_renderer.py:1582-1624`（49 行手写管线） | VK 注释自认是"与 GL 对齐"的重写 |
| 6 | 后处理链（新增） | `loom_post_gl.py` 204 行 | `vk_renderer.py:474-532,896-1038` 202 行 | 4/4 阶段两份 |
| 7 | HDR/bloom 目标分配（新增） | `loom_post_gl.py:111-140` | `vk_renderer.py:918-935` | 尺寸/格式规则两处各写 |
| 8 | 管线状态表达 | 逐 pass apply/restore（`loom_pass_gl.py:141-186`） | pipeline 对象烘焙（`896-916, 954-973`） | 同一状态两种表达（架构性差异，可接受） |
| 9 | 实例/顶点布局 | `loom_render.py:873-962` | `vk_renderer.py:2276-2283` + 160B 实例缓冲 | 两份 |
| 10 | 清屏 | `engine._clear_main_fbo` | `load_op=clear + CLEAR_COLOR_RGBA`（`2242-2244`） | **色值单源 ✓，机制不同** |
| 11 | 天空 quad 几何 | `loom_render.py:144-147`（6 顶点 quad） | `draw(3)`（`1277`） | 两份 |

### 1.6 ⑤ 结论（一句话 + 表）

**一句话**：beta6 交付的是"**GL 单后端内部的 pass 描述层**"，不是"渲染后端抽象化"——VK 侧对 `loom_pass` 的引用数为 **0**（2309 行里 0 行由共享描述驱动），"同一语义写两遍"的项数从 13 增到 14，只闭环了 1 项（清屏色）。

| 口径 | 分子/分母 | 完成度 |
|---|---|---|
| **主口径：14 个"同一语义面"**（研究文档 §1.3 九项 + §2.3 着色器/绑定/参数块 + §⑤ 后处理） | 2.0 / 14（清屏色 1 + 目标声明 0.5 + 后处理参数 0.5） | **14.3%** |
| 辅口径 A：PassSpec 6 项 × 2 后端 = 12 单元（真实被执行器消费） | GL 3.5/6（target/state/draw 执行，depth.write 仅 advisory，shader/bindings/params 不执行）+ VK 0/6 | **29.2%** |
| 辅口径 B：VK 渲染代码被共享描述驱动的比例 | 0 / 2309 行 | **0%** |

**目标判定：未达成。** 按设计文档自己的验收（S0 建 `loom_pass_vk.py` + 假设备断言同 pipeline 计数；S1 删假状态；R8 提升 `tests/pass_ab.py`），六步里"两端共用一份描述"达成 0 步；GL 侧的 4 步（天空/主 pass/阴影/HUD）与后处理 2 步在**GL 内部**是达成的。

---

## 2. 引入问题清单

> 说明：本范围**未发现 P0/P1**（无崩溃、无功能性破坏；`test_frame_plan` 49/49 PASS）。以下 8 项均为 P2/P3。

| # | 等级 | 问题 | 证据 | 引入点 |
|---|---|---|---|---|
| N-01 | P2 | `LOOM_POST_STAGE` 只对 GL 生效：GL 可降到 stage=1/2 的短链，VK 恒跑全链 → 同一开关两端画面不同，A/B 在该开关下不可比 | `loom_pass.py:172,260,267` 读 `post_stage()`；`vk_renderer.py:737` 只读 `post_enabled()`，全文件 0 次 `post_stage` | `eba750f`（2B2） |
| N-02 | P2 | 设计 S1 明确要求删除的"假 `depth_mask` 状态"仍在，且**每帧触发 AttributeError 被吞**；与 `DepthState.write=False` 声明直接矛盾 | `loom_render.py:187,195`（天空）、`344-354`（world canvas）；实测 `hasattr(moderngl.Context,'depth_mask')=False`，赋值只加实例属性；`test_frame_plan` D 段输出 `[渲染] 设置天空 depth 状态失败 (AttributeError(...depth_mask)) -> 用默认值` | 未做（beta6 承诺未兑现，非新引入） |
| N-03 | P2 | 两端都写了 **`up` 阶段却都没接线**（死代码）：GL `_UP` 7 行 + `'post.up'` 注册 + `draw` 分支；VK `'up'` pipeline + bind group + additive blend + `load_op == 'up'` 三元 | `loom_post_gl.py:56-62,188-191`；`loom_pass_gl.py:232`；`loom_pass.py:79-81` 声明了 `post.up` 但 `_build_plan` 从不产出；`vk_renderer.py:964-971,1001,1032` | `eba750f` |
| N-04 | P2 | `PassSpec` 4 个字段（`shader`/`bindings`/`params`/`submit`）**零消费者**：描述与执行脱节，且 `bindings` 的 `shadow.point` 声明为 `texturecube`（`loom_pass.py:146`）而 VK 实际用 `texture_2d_array`（`vk_renderer.py:138`）→ 该描述只对 GL 成立 | 全仓 grep `spec.bindings/params/shader/submit` = 0 命中；`loom_pass_gl.execute` 只读 7/11 个 PassSpec 字段 | `6861603`（2A） |
| N-05 | P2 | 模块文档自述与实现不符：`loom_post_gl.py:4-8` 与 `loom_post.py:5-6` 都写"bright→down→**up**→tonemap"四段链，实际只有 3 个 pass | 同上 N-03 | `eba750f` |
| N-06 | P3 | 状态双写：天空的 `depth_func`/`cull` 先由 plan 执行器 apply（`loom_pass_gl.py:141-159`），再由 `_draw_skybox` 内部重设一遍（`loom_render.py:186-197`）→ 同一状态两处表达，改一处不会同步另一处 | 两处行号 | `6861603` 后并存 |
| N-07 | P3 | 编辑器与播放器的"共享 plan"实为**两套 flag 组合**：播放器 `include_sky=True/include_world_canvas=True/include_hud=True`（`loom_render.py:1170-1173`），编辑器只有 shadow/sky/post（`editor.py:2474-2476`）。与 beta5 行为一致（beta5 编辑器也没画 world canvas/HUD，已核 `git show 08ad3a3:Loom/editor.py`），**不算回归**，但"单一份 plan"的表述需限定为"同一构造器 + 两套参数" | 行号见左 | `6861603` |
| N-08 | P3 | `_PLAN_CACHE` 无上限，键含 clear_color 元组（`loom_pass.py:161-183`）；当前仅 2 个调用点且都用默认常量（实测），暂不泄漏，属潜在风险 | 行号 + 调用点计数 | `6861603` |

**已证伪（反手结论，不计入问题）**：

| 假设 | 结论 | 证据 |
|---|---|---|
| 编辑器迁入 plan 后丢了 world canvas / HUD | DISPROVED | beta5 `editor.py` render 只调 `_draw_main_buckets`/`_draw_skybox`，本来就没有这些（`git show 08ad3a3:Loom/editor.py` 实测） |
| 后处理把 HUD 二次调色 | DISPROVED | GL plan 顺序 `tonemap → hud → ui`（`loom_pass.py:277-296`，测试 F4）；VK 先 submit 后 UI pass（`vk_renderer.py:2295,2303`） |
| `LOOM_POST=0` 时两端回到旧路径 | DISPROVED（对 GL）/ 部分成立（对 VK） | GL：`post_enabled()` 进 plan 键，测试 F8；VK：`_post_on` 在 `__init__` **只算一次**（`vk_renderer.py:737`），运行期改环境变量不生效 |
| 插入 plan 层造成显著帧耗 | DISPROVED（引用既有实测） | plan 取缓存 0.3us / 单帧 6.7us（计划 §9.11），本报告未复测 |

---

## 3. 统计

| 指标 | 数值 |
|---|---:|
| 疑似项总数 | 12 |
| P-PROVED（问题成立） | **8**（P2×5、P3×3） |
| P-DISPROVED | **4** |
| P-UNKNOWN | 0 |
| P-CONTRADICTION | 0 |
| P0 / P1 | **0 / 0** |
| 受审文件数 / 行数 | 9 / **9514**（HEAD，含空行；=1296+2309+297+234+64+204+449+1784+2877） |
| FramePlan 数据类 / 字段 | 8 类 / **42 字段** |
| 被 GL 执行器真实消费的 PassSpec 字段 | **7 / 11**（shader/bindings/params/submit 为 0） |
| `TargetDecl` 被消费字段 | **2 / 8**（name、owned_by_provider；format/scale/fixed/depth/depth_format 被忽略） |
| `BindingSpec` 实例 | 8 个（`loom_pass.py:141-156`），**0 个被读取** |
| `ParamField` 实例 | 6 个（main 3 + sky 3），**0 个被读取** |
| VK 对 `loom_pass/FramePlan` 的引用 | **0** |
| 后处理重复行数 | **406 行**（GL 204 + VK 202），占新增 1237 行的 **32.8%** |
| 着色器重复 | GLSL 454 行（398+56） vs WGSL 458 行 |
| 测试：`test_frame_plan.py` | **49 PASS / 0 FAIL**；对 VK 的断言 **0 条** |
| 设计 S0 交付物 | `loom_pass.py` ✓、`loom_pass_gl.py` ✓、**`loom_pass_vk.py` ✗**、**`tests/pass_ab.py` ✗**（后者以受跟踪的 `tests/test_ab_gl_vk.py` 部分替代，641 行） |
| 目标完成度（主口径） | **14.3%**（2.0 / 14 个语义面） |

---

## 4. 需人类裁决的问题（封闭式）

| # | 问题 | 选项 | 影响 |
|---|---|---|---|
| Q-01 | "渲染后端抽象化"是否以 **VK 迁入 FramePlan** 为 beta7 硬目标？ | A：定为硬目标（否则该目标连续两个版本未达成）／B：明确降级为"GL 内部 pass 层"，在发行说明写清"FramePlan 仅 GL" | 决定本目标的验收措辞与 beta7 容量 |
| Q-02 | 是否接受 **14.3%** 作为本目标的验收结论（分母 = 14 个语义面）？ | A：接受该口径并据此登记"未达成"／B：改用"GL 内部收敛已完成"口径（则需同时声明 VK 未纳入） | 影响发布说明与后续复盘 |
| Q-03 | 是否授权做三处**行为中性**清理（不改像素）：删两端 `up` 死代码 + 删 `depth_mask` 假状态（`loom_render.py:187,195,346,354`）+ 修 `loom_post_gl.py:8`/`loom_post.py:5` 的链路自述？ | A：做（P2/P3 一次性清）／B：只删 `depth_mask`（S1 承诺项）／C：全部留到 beta7 | 决定是否在 beta6 收尾补 1 个行为中性提交 |

---

## 附录：探针与原始输出

- `Loom/tests/_tmp/final_01_probe.py` —— 数据类/字段/消费点/行数统计（输出 JSON 已摘入本报告 1.1-1.4、§3）
- `Loom/tests/_tmp/final_01_shaders.py` —— WGSL 8 个字面量 458 行 / GLSL 12 个字面量 398 行
- `git show --stat eba750f` —— 2B2 落点 8 个代码文件 / 792 行（`vk_renderer.py +249`、`loom_post_gl.py +202`、`loom_pass.py +65`）
- 全部探针目录由 `Loom/.gitignore:22`（`tests/_tmp/*`）忽略；收尾 `git status --porcelain` 为空。
