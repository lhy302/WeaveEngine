# goal_01 · 批次 A 渲染与后端抽象（第十轮独立达成度扫描）

> 角色：**未参与实现**的独立判定子代理。只读；探针写在 `Loom/tests/_tmp/goal_01_*.py`，本文件为唯一文档写入。
> 快照：HEAD `d1674fa`，`git status --porcelain` 空。环境：Python 3.13.15 / moderngl（GL 4.3.0 NVIDIA 582.78，GTX 1050 Ti）/ wgpu（Vulkan 1.4.309）。
> 方法：**先读原始设计文档抄目标，再自己对每条造可复现证据**；不引用任何实现方报告数字（引用处均标注"仅作对照"）。

## 0. 目标来源与文档口径校正

| 任务书引用 | 实际情况 |
|---|---|
| `docs/design/research_beta6_01_render_pass.md` | **不存在**。同名主题的实际文件是 `docs/design/research_beta6_01_render_pass.md`（本报告以其 §2.1–§2.6 / §③S0–S6 / §⑥ / §⑦ 为原始目标） |
| 计划 §9.1 | **无此编号**。该文件第 9 章以「9. 人类裁决记录（2026-11-09 第二批）」表开头，下一节即 §9.2；本报告把该表当作 §9.1 口径 |

目标清单（从原文抄，不用实现口径）：

- **T1**（research §2.1）一期只做「有序 Pass 列表 + 显式目标声明」FramePlan，不做依赖求解 RenderGraph。
- **T2**（research §2.2/§2.3）PassSpec 是 6 项完整边界：目标 + 状态(depth/raster) + 着色器 + **语义槽绑定** + **参数块** + 绘制源。
- **T3**（research §2.4）**同一份 FramePlan 同时驱动 moderngl 与 wgpu**，逐字段按映射表落地。
- **T4**（research §2.5）不做 GLSL/SPIR-V 双编译；两份镜像由同一份 layout 约束 + **断言测试（WGSL @binding 集合/顺序 == GLSL uniform 名集合/顺序）**。
- **T5**（research §2.6）后处理硬排序：主 pass → bloom(全在 HDR) → tonemap → HUD/UI；新增 color.hdr / bloom.bright / bloom.down / bloom.up。
- **T6**（research §③）S0–S6 每步一提交、先测后改、每步 `ab_batch` 0 失败；S1 删假 `depth_mask`；S5 tonemap 公式**唯一** + HDR 创建失败降级直写 LDR 并告警一次；S6 bloom off 逐字节等于 S5、**无 NaN/Inf**、帧耗增量 ≤15%。
- **T7**（research §⑥）10 条契约必须保持（sceneio 不落地、PresentHealth 单实现、effective_skybox 单一、`_screen_fb/_external_fb`、`draw_frame` 签名、GL render 入口、编辑器 view.draw、HUD/UI 在 tonemap 之后、测试形态、依赖清单不新增 glslang/spirv-cross）。
- **T8**（research §⑦ Q1–Q8）8 个封闭问题的裁决落地。
- **P1**（计划 §9.11）22→23 场景像素门 0 SKIP；313 项测试 FAIL=0；抽象层单帧开销 6.7µs；编辑器 `--auto-close 3` 正常。
- **P2**（计划 §9.13/§9.14）GL/VK 双端 tonemap+bloom，`LOOM_POST=0` 可回退；参数 exposure=1.70 / threshold=1.15 / knee=0.35 / strength=0.70；平均亮度标定到旧基线 ±3%；bloom 晕圈量化证明生效；后处理约 +8% 帧时。
- **P3/P4**（计划 §9.21→§9.22→§9.24）9.21 的"14.3% / 未达成"被 §9.22 上调为 **beta6 必做**：VK 迁入 FramePlan、**重复语义面 14 → ≤8**、清理文档/死代码/env/测试入口证据。
- **P5**（计划 §9.24）新验收硬门：**改 plan 必须改变 VK 输出**；`plan.clear/load` 对 VK 生效；`sky.raster.cull` 两端一致；`TargetDecl.format/scale` 生效；`LOOM_POST_STAGE` 档位不重复；假 `depth_mask` 已删；后处理参数两端共享；`LOOM_POST_STAGE=0 ≡ LOOM_POST=0`。
- **P6**（计划 §9.2/§9.3）GL 4.3 core 与 Vulkan 1.1 **并列为引擎最低要求**并强制（失败必须可见，不静默黑窗）。

## 1. 五条重点逐条判定

### ① FramePlan 是否两个后端都真的由它驱动 —— **达成**

不是 grep，是「改 plan 看输出」的反例矩阵。探针 `Loom/tests/_tmp/goal_01_plan_drive.py`（`py -3.13 tests\_tmp\goal_01_plan_drive.py`），每次改 `loom_pass.frame_plan` 的返回值后分别重渲 GL 与 VK，MAE 对各自同后端基线：

```
场景              反例                          GL MAE     VK MAE
ab_sky.json      删 tonemap pass              0.63026    0.63026
ab_sky.json      删 sky pass                  0.24656    0.24656
ab_sky.json      main.load=load               0.63026    0.63026
ab_sky.json      sky.draws=buckets            0.24656    0.24656
ab_bloom.json    删 bloom.bright              0.00165    0.00165
ab_sky.json      main<->sky 换序              0.24656    0.24656
ab_c_dir_shadow  删 shadow_maps pass           0.00181    0.05955
--- 7/8 类反例两端均 >1e-3 ---
```

补充两组状态面（`tests/_tmp/goal_01_state_fields.py`）：`main.depth.test=False` → GL 0.06089 / VK 0.06089；`sky.raster.cull=back` → GL 0.24656 / VK 0.24656。
`plan.clear` 单独验证（`tests/_tmp/goal_01_clear_write.py`，ab_sky 删 sky + `main.clear=红`）：**GL 0.33381 / VK 0.33381** —— 即 §9.24 登记的 P2「`plan.clear` 对 VK 无效」已修。

> 反例 8（ab_cube `main.clear=红`）两端均为 0.00000，**不是驱动失效**：该场景地面铺满全屏（实测 GL 基线最小亮度 0.349、无 <0.20 像素），清屏色不可见 —— 记录为**我方 oracle 选择失误**，已换场景重做。

代码侧唯一入口：GL `loom_pass_gl.py:103` `for spec, decl, srcs in self._rows(plan)`；VK `vk_renderer.py:2194` `for spec in plan.passes`（`:2204` 未识别 pass 白名单、`:2211` 后处理、`:2218` `_begin_plan_pass`、`:2219` 按 `spec.draws` 派发、`:2242` 单次 submit）。
受跟踪硬门 `Loom/tests/test_frame_plan_vk.py`（V-01 反例矩阵）：**19 PASS / 0 FAIL / ALL PASS**（我复跑）。

**残留不对称**：VK 的 HUD/UI 是"先收集、主链 submit 之后再执行"（`vk_renderer.py:2201-2203, 2251-2257`），所以 plan 里把 ui 排到 main 之前**不会**改变 VK 输出顺序（当前 plan 恒为尾部，未暴露）。

### ② tonemap+bloom 双端一致且可回退 —— **达成**（两个数值口径不复现）

| 检查 | 命令 | 我自己的读数 | 判定 |
|---|---|---|---|
| POST 开：23 场景三向 | `py -3.13 tests/test_ab_gl_vk.py` | 23/23 PASS + 1 UI PASS，0 SKIP；GL/参考 **0.000000**（全场景），VK/参考 ≤ **0.000066**（ab_ui_scene） | 达成 |
| POST 关：旧基线 | `$env:LOOM_POST='0'; py -3.13 tests/test_ab_gl_vk.py --legacy` | 23/23 PASS；GL/参考 0.000000，VK/参考 ≤ **0.000082**；`ab_point_shadow` 0.000063、`ab_sky` 0.000017 —— 与研究 §1.4 的历史基线逐值相符 | 回退达成 |
| `LOOM_POST=0` vs `LOOM_POST_STAGE=0` | `tests/_tmp/goal_01_post_metrics.py` | ab_sky GL **0.00000000** / VK **0.00000000**；ab_bloom 同 | 达成（两端真关） |
| 档位不重复（9.24 P2 死档） | 同上 | ab_bloom STAGE1→2 **0.00053**、2→3 **0.00120**（两端同值）；ab_sky 三档全同（场景无高亮，属场景限制） | 达成 |
| 晕圈量化 | 对**在库参考图**算（不渲染） | ab_bloom 环带 0.3907 → 0.4866 = **+24.5%**；中心 1.000→0.898 | 定性达成；§9.14 的 **+42.5% 未复现**（口径/基线不同） |
| 亮度标定 ±3% | 同上（23 张参考图平均亮度） | POST=0 中位 **0.6085** → POST=on **0.6001（−1.4%）** | 达成（±3% 内）；§9.14 的 0.5700/0.5735 绝对值与我的度量定义不同，未复现 |

参数/开关单点在 `loom_post.py:27-32`（DEFAULTS）、`:53-63`（post_stage）、`:47-50`（post_enabled）—— GL 与 VK 都 import 这一份（`loom_post_gl.py:15,165`；`vk_renderer.py:2317`）。

### ③ 像素门 23 场景三向 —— **达成，但第一向在生成时刻是自证**

`test_ab_gl_vk.py` 每场景判 6 条（`:7-11`）：GL/参考、VK/参考、GL/VK、MAE 漂移、NCC、MAX，UI 场景再加三路。实测共 **24 项检查（23 场景 + 1 UI 子项）/ 0 FAIL / 0 SKIP**，场景数 23（`Loom/tests/ab_scenes/ab_*.json`，含 `ab_bloom.json`），两套基线各 23 条（`ab_gl_vk_baseline.json` / `ab_gl_vk_baseline_next.json`，`scene_count=23`）。

**必须写清的弱点**：参考图由 GL 自己渲染后落盘（`test_ab_gl_vk.py:509` `_save_png(g, rp)`），所以"GL/参考 MAE 恒 0.000000"是**同源自证**，只能抓后续漂移（frozen png + `ref_sha256`），不能当独立 oracle。真正有外部含义的是 VK/参考（≤6.6e-5）与 GL/VK 两路。

### ④ 未共享语义面到底几项 —— **未达成（§9.22 的 14→≤8 没做到）**

以 §9.21 自己列的 14 项为分母，我逐项对着代码与实测判：

| # | 语义面 | 判定 | 证据 |
|---|---|---|---|
| 1 | 阴影目标编码 | 未共享（合理） | GL 真深度附件 `loom_shadow.py:55,60`；VK r32float+手工比较 `vk_renderer.py:2364-2367, 2401-2405` |
| 2 | 阴影提交粒度 | 未共享（合理，但描述字段无消费者） | VK 每面独立 encoder+submit `vk_renderer.py:2356,2377,2415`；`spec.submit` 全仓 **0 消费者** |
| 3 | 天空时机 | **已共享** | 顺序来自 plan（我实测换序两端同幅 0.24656） |
| 4 | 天空几何 | 未共享（合理） | GL 6 顶点 `loom_render.py:229`；VK `rp.draw(3,1,0,0)` `vk_renderer.py:1289` |
| 5 | 天空参数 | 未共享 | GL 3 个具名 uniform `loom_render.py:200-203`；VK 112B 打包 UBO `vk_renderer.py:1213-1215` |
| 6 | 实例布局 | 未共享（合理） | 无 `VertexLayout`（`Loom/**/*.py` 0 命中）；VK 160B/`_INST_BYTES` 与 GL 桶 VBO 各写一遍 |
| 7 | HUD/UI | 部分共享 | pass 存在性/顺序共享；实现两份（`loom_hud.py` + `loom_ui.draw_all` vs `vk_ui.draw_ui`），契约非逐像素 |
| 8 | 着色器 | 未共享（合理） | 无 `ShaderSet`（全仓 0）；GLSL `loom_shaders.py`/后处理 GLSL vs `_POST_WGSL`(`vk_renderer.py:477-544`) |
| 9 | 绑定槽 | 未共享（**不合理**） | `spec.bindings` 全仓 **0 消费者**；GL 手写 unit、VK 手写 `@binding`（`vk_renderer.py:1160-1175`） |
| 10 | 参数块 | 未共享（**不合理**） | `spec.params` 全仓 **0 消费者**；VK `f32[352]` 手工排布 `vk_renderer.py:73,1949-1960` |
| 11 | mip | 未共享（合理） | VK 自建 mip 管线 `vk_renderer.py:1594`（格式已参数化）；GL 走 texture.build_mipmaps |
| 12 | 后处理 | 部分共享 | 参数/开关/阶段/目标名共享（`loom_post.py`）；执行两份：`loom_post_gl.py`（196 行，3 个 GLSL） vs `_record_post_pass``vk_renderer.py:2314-2349` |
| 13 | 目标分配 | 部分共享 | 名字共享；但 `TargetDecl.scale` **只有 VK 读**：把 half.scale 0.5→0.25，**GL 0.000000 / VK 0.000825**；GL 尺寸写死 `loom_post_gl.py:124-125`，VK 读 scale `vk_renderer.py:942-947` |
| 14 | submit 粒度 | 未共享（**不合理**） | `spec.submit` 0 消费者；VK 阴影 own submit、主链+后处理单 submit（`vk_renderer.py:2242`） |

**统计**：14 项里 **1 项完全共享（3）**、**3 项部分共享（7/12/13）**、**10 项仍不共享**。按半权计 ≈ 14 − 1 − 1.5 = **11.5 个重复语义面**，距 §9.22 的 **≤8** 仍差约 3.5。**结论：目标未达成**（相较 §9.24 的"真实共享仅 3 类"确有改善：现在共享类 = pass 存在性/顺序、load/clear、depth/raster 状态、目标语义名、后处理参数+阶段、天空顺序，共 **6 类**）。

另一独立口径（按 research §2.2 的"6 项边界"）：`bindings` / `params` / `submit` 三个字段在**两个后端都没有消费者**，`vertex`(VertexLayout) 与 `ShaderSet` 从未实现 → 描述层实际只承载 **目标 + depth/raster 状态 + 绘制源 + shader 名**（4 项），不是设计的 6 项。9/10/2/14 不是"合理的实现差异"，是"声明了但没接线"（AUDIT-DEADCODE 类）。

### ⑤ GL 4.3 与 VK 1.1 地板是否真强制 —— **达成（带两个缺口）**

探针 `Loom/tests/_tmp/goal_01_floors.py`：

```
3.3 上下文: version_code=330 supports_gl(4.3)=False
PASS require_gl_version(3.3) -> GLVersionError: [GL] 探针低版本上下文 需要 OpenGL 4.3 core 及以上...
4.3 上下文: version_code=430 require-> 430
本机 vulkan_api_version = (1, 4, 309) | 文本: 1.4.309
PASS fake=(1, 0, 0) -> VkBackendInitError: [VK] 探针 不可用：当前 Vulkan API 为 1.0.0，低于地板 1.1...
PASS fake=None -> VkBackendInitError: [VK] %s 不可用：未找到 Vulkan 运行时（vulkan-1.dll）...
== 门是否在唯一的产品入口上 ==
vk_player 里 require_vulkan_api 调用次数 = 1
engine.py / loom_player_window.py / ui\loom_gui.py 各有 1/1/2 个 create_context，门数 1/1/2
```

- GL 门 `loom_gl_version.py:54-74`，4 个产品建上下文点全部紧跟 1 个门：`engine.py:290→293`、`loom_player_window.py:132→134`、`ui/loom_gui.py:193→195, 553→554`。外部注入 ctx 的测试/宿主按设计豁免（模块头 `:12-15`）。
- VK 门 `loom_backend_guard.py:133-161`，**唯一** adapter 创建点 `vk_player.py:357` 之前 `:354` 过门（全仓 `request_adapter_sync` 仅此一处）。
- 文档化：`使用操作指南.txt:29-38` 两条地板并列写明（GL 4.3 core / Vulkan 1.1+，Intel 需 Skylake+）。

两个缺口（见第 2 节 I-1/I-2）：**门校验的是 loader 版本，不是 adapter 的 apiVersion，也没有强制 `backend_type='vulkan'`**（`vk_player.py:357-358` 无该参数）；以及 `ver is None` 分支首行 `%s` 未格式化，用户会看到字面 `[VK] %s 不可用`。

## 2. 引入问题（本轮独立发现）

| ID | 级别 | 问题 | 证据 |
|---|---|---|---|
| I-1 | P3 | VK 门 `ver is None` 分支首行含未格式化的 `%s`，真实缺 loader 时用户看到字面 `%s` | `loom_backend_guard.py:141-147`（`'\n'.join(lines)` 未做 % 替换）；探针实测打印 `[VK] %s 不可用` |
| I-2 | P2 | VK 地板只查 loader 版本；未校验 `adapter.info` 的 apiVersion，也未限定 `backend_type='vulkan'`，若 wgpu 选到别的后端，日志仍写「Vulkan 1.4.309」 | `vk_player.py:357-362`；`loom_backend_guard.py:139-161` |
| I-3 | P2 | `TargetDecl.scale` 只有 VK 消费，GL 尺寸写死 → 共享描述同一字段单端生效（改 half.scale：GL 0.000000 / VK 0.000825） | `loom_post_gl.py:124-125`；`vk_renderer.py:942-947`；`tests/_tmp/goal_01_plan_drive.py` 末行 |
| I-4 | P2 | `PassSpec.bindings/params/submit` 与 `TargetDecl.format` 在 GL 侧零消费者（声明了不驱动）；`shadow.depth` 两端都不消费（GL `owned_by_provider`→None `loom_pass_gl.py:58-59`，VK 忽略 `spec.target` `vk_renderer.py:2354-2367`） | grep `spec.bindings/spec.params/spec.submit` 各 0 命中 |
| I-5 | P3 | 设计 S6 验收点"bloom on 无 NaN/Inf"无受跟踪断言 | `Loom/tests` 内 `isnan/isfinite` 无后处理相关命中 |
| I-6 | P3 | 设计 S5 验收点"HDR 目标创建失败降级直写 LDR 并告警一次"未落：`GLPostChain.ensure` 无 try/except | `loom_post_gl.py:104-133` |
| I-7 | P3 | 文档数字滞后 + 引用失效：计划 §9.11 写 frame_plan「现 49 项」，实测 **55 PASS**；任务书引用的 `research_beta6_01_render_pass.md` 不存在；计划无 §9.1 | `py -3.13 tests/test_frame_plan.py` → PASS=55 FAIL=0；`docs/design` 目录无该文件 |
| I-8 | P3 | 「GL/参考 MAE 恒 0」是自证（参考图由 GL 渲染写入），只在漂移检测上有效 | `test_ab_gl_vk.py:509` |
| I-9 | P3 | VK 的 HUD/UI 先收集后执行，plan 里 ui 排在 main 之前不会改变输出顺序（顺序只对尾部两项生效） | `vk_renderer.py:2201-2203, 2251-2257` |

## 3. 目标达成判定表

| # | 原定目标（来源） | 判定 | 关键证据 |
|---|---|---|---|
| T1 | 有序 Pass 列表 + 显式目标声明，不做 RenderGraph | **达成** | `loom_pass.py:103-137`（`FramePlan`+`validate`）；`reads` 未加（设计列为二期） |
| T2 | PassSpec 6 项完整边界 | **部分达成** | 只有 目标/状态/绘制源/shader 名 真落地；bindings/params/submit 零消费者、VertexLayout 不存在（I-4） |
| T3 | 同一份 FramePlan 驱动两后端 | **达成** | 我的反例矩阵 7/8 两端同幅 + `main.clear` 0.33381/0.33381；`test_frame_plan_vk` 19 PASS（我复跑） |
| T4 | 不做双编译 + 布局一致性断言测试 | **未达成** | 全仓 `ShaderSet` 0；tests 内无 `@binding` 集合断言（仅 `test_vk_two_dir_shadow.py:140` 字符串级） |
| T5 | 后处理排序：main→bloom(HDR)→tonemap→HUD/UI | **达成** | `loom_pass.py:227-298` 的 passes 顺序；HUD/UI 在 tonemap 之后 |
| T6 | S0–S6 验收点（含 Z-fighting 级细节） | **部分达成** | 假 `depth_mask` 已删（`loom_render.py:211,382` 注释 + 全仓无赋值）；tonemap 公式仍是两份镜像（GLSL/WGSL）不是"唯一"；S5 降级(I-6)、S6 NaN 断言(I-5)缺 |
| T7 | 10 条契约不变 | **达成** | `draw_frame` 签名不变（`test_vk_two_dir_shadow`/`ab_gl_vk` 直接调）；`requirements` 无 glslang/spirv（grep 0 命中） |
| T8 | Q1–Q8 裁决落地 | **部分达成** | Q7=A/B 提升已做；Q4=A 的"抽象里做阴影编码能力位"未做（`shadow.depth` decl 两端不消费）；Q5/Q6 符合 |
| P1 | 23 场景 0 SKIP；313 测试 FAIL=0；6.7µs；编辑器 auto-close | **部分达成** | 像素门 24 检查 0 FAIL 0 SKIP（我复跑）；313 全量回归、6.7µs 单帧开销**本次未复跑**（不在 01 五重点内，不判定） |
| P2 | 双端 tonemap+bloom、回退、参数、亮度±3%、晕圈、+8% 帧时 | **部分达成** | 回退/双端/参数/±3% 达成（−1.4%）；晕圈我实测 **+24.5%**（≠42.5%）；+8% 帧时未测 |
| P3 | §9.21 自评 14.3%（历史裁决） | **不适用** | 已被 §9.22/§9.24 推翻并改为必做项，不是现目标 |
| P4 | VK 迁入 FramePlan；重复语义面 **14 → ≤8** | **部分达成**（前半达成、后半未达成） | 迁入达成（①）；语义面实测 ≈11.5 > 8（④） |
| P5 | §9.24 八条硬门 | **部分达成** | 改 plan 改 VK 输出✔、`plan.clear/load` 对 VK 生效✔、`sky.raster.cull` 两端同幅✔、假 depth_mask 已删✔、post 参数共享✔、`POST_STAGE=0≡POST=0` 逐位✔、档位不重复✔（ab_bloom）；**`TargetDecl.format/scale` 只单端生效✘**（I-3） |
| P6 | GL 4.3 / VK 1.1 地板文档化 + 强制 | **达成**（含 I-1/I-2 缺口） | 探针 raise 实测；4/1 个建上下文点各自有门；指南 §:29-38 已写 |

## 4. 复跑与未复跑清单

**我实际跑了**（本报告所有数字均来自这些命令的输出）：
- `py -3.13 tests/test_ab_gl_vk.py` → 23 场景 + 1 UI，**0 FAIL / 0 SKIP**
- `$env:LOOM_POST='0'; py -3.13 tests/test_ab_gl_vk.py --legacy` → 同上，0 FAIL / 0 SKIP
- `py -3.13 tests/test_frame_plan.py` → **PASS=55 FAIL=0**
- `py -3.13 tests/test_frame_plan_vk.py` → **PASS=19 FAIL=0 / ALL PASS**
- 自写探针 5 个（`goal_01_plan_drive` / `goal_01_state_fields` / `goal_01_clear_write` / `goal_01_post_metrics` / `goal_01_floors`）

**未复跑（如实标注，不作判定依据）**：313 项全量回归、抽象层单帧 6.7µs、后处理 +8% 帧时、编辑器 `--auto-close 3`。

## 5. 待裁决

1. **§9.22 的「14 → ≤8」是否按"半权计部分共享"重新定口径**？按严格计（共享=整项不再有两份实现）现状是 14−1=13；按半权 ≈11.5；两种口径都 >8。建议人类先定口径，再决定 beta7/继续打磨的剩余工作量。
2. **描述层里零消费者的字段（bindings/params/submit/format/shadow.depth）怎么处置**：接线（真共享）还是从 PassSpec 删掉（承认不做）？现状是"声明了但两端都不读"，属 AUDIT-DEADCODE。
3. `TargetDecl.scale` 单端生效（I-3）：改 GL 侧读 scale，还是从描述里去掉`scale`只保留语义名？
4. VK 地板门（I-1/I-2）：是否补 adapter apiVersion 校验 + `backend_type='vulkan'` 限定，并修 `%s` 消息。
