# verify_01 · 渲染抽象达成度复核（任务后倒查 · 第八轮）

> 编号：01 ｜ 主题：VK 是否真由 FramePlan 驱动 / 后处理共享 / depth_mask / POST_STAGE ｜ 日期：2026-11-10
> 方式：**只读**（受跟踪文件零改动）；探针只写 `Loom/tests/_tmp/verify_01_*.py`（`Loom/.gitignore:22` 已忽略）。
> 基线：HEAD `ee83e4b`（探针运行前 `git status --porcelain` 为空），Python 3.12.10 / moderngl 5.13.0 / wgpu 0.32.0 / NVIDIA GTX 1050 Ti（Vulkan 后端）。
> 不抄任何报告数字：每个结论都由下述命令当场复跑得到。

---

## 0. 复现命令一览

```powershell
py -3.12 tests/_tmp/verify_01_plan_matrix.py    # ① ②：PassSpec 字段篡改 → GL/VK 像素差分矩阵
py -3.12 tests/_tmp/verify_01_post_stage.py     # ③ ⑤：后处理参数共享 / LOOM_POST_STAGE 0..3
py -3.12 tests/_tmp/verify_01_apply_clear.py    # ① ④：plan.clear / draws 消费 + depth_mask 运行期
py -3.12 tests/_tmp/verify_01_post_order.py     # ②：后处理 pass 顺序 / TargetDecl.scale
py -3.12 tests/test_frame_plan.py               # 49 PASS / ALL PASS（对 VK 断言 0 条）
```

GL 侧走 `editor.EditorApp.render`（编辑器真实路径，`editor.py:2484`），VK 侧走 `SceneDriver + VkRenderer.draw_frame`（播放器真实路径；复用受跟踪的 `tests/test_ab_gl_vk.py` 离屏夹具，480×320）。指标 = 与同后端基线的 `MAE(float64)`，>1e-5 记为"变"。

---

## 1. ① VK 是否真的由 `frame_plan()` 驱动

### 1.1 VK 里每个 pass 消费 plan 的代码位置（实测读代码）

| pass | VK 读 plan 的位置 | 消费到的字段 | 没消费的字段 |
|---|---|---|---|
| shadow_maps | `vk_renderer.py:2213`（存在性）、`:2243`（点光 6 面分支） | 仅"存在" | depth/raster/目标 |
| main | `:2309` 取 spec、`:2310-2317` 目标名→HDR/LDR 视图+format、`:2319-2320` depth/raster→`:896-931` 烘焙管线 | id、target、format、depth(write/func)、raster(cull/front/topology) | **clear/load**（`:2322-2327` 硬编码 CLEAR_COLOR_RGBA + LoadOp.clear）、**draws**（`:2354-2363` 硬编码画 buckets） |
| sky | `:2308` 存 spec→`:1232-1260`（depth.write/func、cull/front_face 进管线 key）、`:2345` 存在性 | 存在、depth、raster | load、几何、参数 |
| world_ui | `:2366` 存在性；`:2368` 调 `_draw_world_quads` | 仅"存在" | depth/raster/draws |
| bloom.bright / bloom.down | `:2373-2377` 按 plan 顺序过滤 → `:1065-1080` | 顺序、存在、target、draws[0].source | load/depth/raster |
| tonemap | 同上 | 顺序、存在、target、draws[0].source | load/depth/raster |
| hud / ui | `:2392-2394` 两个布尔 | 仅"存在"（顺序固定 HUD→UI） | draws/状态 |

补充：`self._frame_plan = plan`（`:2105`）只是存起来；全文件对 `plan` 的引用共 **11 处**（`:936,2105,2213,2308,2309,2310,2345,2366,2373,2392,2393`），**没有一处遍历 `plan.passes` 执行**（唯一遍历是 `:2373` 的后处理过滤）。对照 GL：`loom_pass_gl.py:95` `for spec, decl, srcs in self._rows(plan)`，`:112-116` 按 `spec.draws` 派发。

### 1.2 反例（改 plan，看两端像素是否跟着变）

```
# verify_01_plan_matrix.py（ab_sky.json；末段标 LOOM_POST=0）
mutation                      | GL-ΔMAE  | VK-ΔMAE  | 判定
order: main<->sky             | 0.24656  | 0.00000  | GL-only
presence: drop sky            | 0.24656  | 0.24656  | both
presence: drop tonemap        | 0.63026  | 0.63026  | both
presence: drop shadow_maps    | 0.00087  | 0.07222  | both
target: main->color.ldr       | 0.63026  | EXC TypeError: 'NoneType' object is not subscriptable | EXC
clear: main=(1,0,0,1)         | 0.00000  | 0.00000  | （天空盖住底色，另测见下）
load: main=load               | 0.63026  | 0.00000  | GL-only
depth.test: main=False        | 0.06089  | 0.00000  | GL-only
raster.cull: sky=back         | 0.00000  | 0.24656  | VK-only（方向相反）
shader/bindings/params/submit | 0.00000  | 0.00000  | 两端都不读（见 ②）
--- LOOM_POST=0 ---
drop main                     | 0.63680  | 0.00000  | GL-only
swap main<->sky               | 0.26022  | 0.00000  | GL-only

# verify_01_apply_clear.py（ab_plane + 强制 include_sky=False，背景=清屏色）
BASE            GL=4c23bfb5065d VK=4c23bfb5065d  角落像素 (0.1255,0.1529,0.2)
clear=(1,0,0,1) GL=1ff7df6e0b43 VK=4c23bfb5065d  角落 GL=(0.8118,0,0) VK=(0.1255,0.1529,0.2)
                ΔMAE GL=0.22379 VK=0.00000
main draws=skybox GL=37f5455d1532 VK=0f90f5213e24  ΔMAE GL=0.06324 VK=0.00000

# verify_01_post_order.py（ab_bloom.json）
order bright<->down              GL=0.00000 VK=0.00165
target bloom.half scale .5->.25  GL=0.00000 VK=0.00083
target color.hdr scale 1->0.5    GL=0.00000 VK=EXC
```

说明：GL 的 `bright<->down` 显示 0 是探针伪像（`render_gl` 连跑 3 帧、GL 后处理纹理跨帧复用，静态场景里顺序错位一帧即收敛），不是"GL 不读顺序"；`loom_pass_gl.py:95` 明确按 plan 顺序执行。VK 每次新建 renderer，纹理不复用，故能显出顺序变化（0.00165）。

### 1.3 判定 ①

- **不是"只 import"**：VK 每帧调 `frame_plan()`（`:2098-2104`）并真实消费 6 个 pass 的存在性、main 的目标名/format、main/sky 的 depth/raster、后处理段顺序/目标/绘制源。上轮"VK 引用 0 行"的结论已过时。
- **但"由 plan 驱动"只对部分语义成立**：13 个信息性反例中 VK 只有 **6 个**响应（drop sky / drop tonemap / drop shadow_maps / sky.cull / 后处理顺序 / bloom.half scale）；**6 个不响应**（主链顺序、drop main、clear、load、depth.test、draws 源）；**2 个崩溃**（main 改 LDR、hdr scale 改 0.5）。
- 结论：**部分达成**。plan 对 VK 是"开关表 + 少量烘焙参数"，不是执行序；"pass 顺序读同一份"不成立（`main↔sky` 两端 ΔMAE 0.24656 / 0.00000）。

---

## 2. ② 语义面清单（自列，不抄报告；对照"14 → 6"）

### 2.1 已真正共享（两端消费且改之两端都变）

| # | 语义面 | 证据 |
|---|---|---|
| S1 | 后处理参数（threshold/knee/strength/exposure） | GL `loom_post_gl.py:165`、VK `vk_renderer.py:1042-1043` 都调 `loom_post.params()`；改 DEFAULTS threshold→5.0 两端 ΔMAE 均 0.00165（第 3 节） |
| S2 | 后处理段（bright/down/tonemap）的集合与顺序、目标/绘制源名 | GL 按 plan 顺序派发（`loom_pass_gl.py:95,112-116`）；VK 按 `plan.passes` 过滤（`:2373`）并取 `draws[0].source`（`:1066`）、`target`（`:1080`） |
| S3 | 阴影/天空/后处理 **pass 存在性** | 删 sky/tonemap/shadow_maps 两端都变（0.24656 / 0.63026 / 0.07222 vs 0.00087） |

### 2.2 仍各自实现（**14 项，与上轮同口径逐项复核，无一项被消除**）

| # | 语义面 | GL 现位置 | VK 现位置 |
|---|---|---|---|
| U1 | 目标分配（FBO/纹理创建、深度附件） | `loom_post_gl.py:111-125`；屏幕目标 `loom_pass_gl.py:61` | `vk_renderer.py:944-969`、`:1141-1147`、`:2291-2295` |
| U2 | 阴影编码 | `loom_shadow.py:51,58` depth_texture + `loom_shaders.py:82` sampler2DShadow | `vk_renderer.py:1141-1145` r32float + `:287-306` 手工比较 |
| U3 | 阴影提交粒度 | `loom_shadow.py:100` `fbo.use()` 立即模式 | `vk_renderer.py:2224-2239`、`:2267-2281` encoder+submit |
| U4 | 天空时机 | plan 写"几何后+lequal"（`loom_pass.py:227-240`、`loom_render.py:98-104`） | `vk_renderer.py:2345` 在几何 `:2354` 之前 + always |
| U5 | 天空几何 | `loom_render.py:149,190` CPU 6 顶点 quad | `vk_renderer.py:1338-1340` `rp.draw(3,1,0,0)` |
| U6 | 天空参数块 | `loom_render.py:166-171` 3 个具名 uniform | `vk_renderer.py:1264-1266` 112B UBO |
| U7 | 实例/顶点布局与桶重排 | `loom_render.py:480` `_prepare_bucket_frame` + `vao.render` | `vk_renderer.py:2131-2151` 160B 实例块 + `:2363` |
| U8 | HUD/UI 光栅化 | `loom_pass_gl.py:215-219` `ui.draw_all` | `vk_renderer.py:2394-2398` + `vk_ui.py` |
| U9 | 着色器源码 | `loom_shaders.py` GLSL + `loom_post_gl.py:19-70` | `vk_renderer.py:478-532`（_POST_WGSL）+ 主/天空 WGSL |
| U10 | 绑定槽 | plan `bindings` 11 个实例（`loom_pass.py:142-156`）**0 消费者** | 同左（VK 用 `binding`，`:1215-1226`） |
| U11 | 参数块打包 | plan `params` 6 个实例**0 消费者**；GL 具名 uniform（`loom_lighting.py:96-98`） | `vk_renderer.py:2000-2057` f32[352] |
| U12 | mip 生成 | `loom_cubemap.py:203` `build_mipmaps()` | `vk_renderer.py:1645-1687` `_gen_mips` |
| U13 | 后处理管线/目标构建 | `loom_post_gl.py:135-143` `ctx.program` | `vk_renderer.py:971-1012` `create_render_pipeline` |
| U14 | submit 粒度 | 立即模式（`loom_pass_gl.py:96-120`） | `vk_renderer.py:2239,2281,2378` 三次 `queue.submit`；`PassSpec.submit` 0 消费者 |

### 2.3 "14 → 6" 的来历（复核结论：口径变化，不是减少）

- 上轮 14 项在代码里**仍全部存在**（本表 U1-U14 逐项给了现行号），本轮没有删除/合并任何一份实现。
- 提交信息里的"仍各自实现 6 项"= 把 14 项**重新分桶**：阴影编码+提交粒度→1；天空时机+几何+参数块→1；绑定槽+参数块→1；实例布局+submit→1；着色器→1；UI→1。同时**丢弃 3 项**：U1 目标分配 / U12 mip 生成 / U13 后处理管线构建（这 3 项代码里仍是两份，只是不在新分母里）。
- "共享 8 项"高估：两端都有可见效果的只有 S1-S3（3 类）；目标名、depth/raster 声明、draws 源都只部分（1.2：main 改 target VK 崩、sky.cull 两端相反、draws 只对后处理生效）。
- 量化：**未共享 14/14（0 项闭环）；新增真共享 3 类（不在原 14 项内）**。无论用哪种记分，都不是"降到 6"。

---

## 3. ③ 后处理是否真的共享描述

```
# verify_01_post_stage.py（ab_bloom.json）
default(threshold=1.15)  GL=f19e9411558c VK=bd2ebd76f9ee
threshold=5.0            GL=6c01558f70da VK=ebecea7ec94d   ΔMAE GL=0.00165 VK=0.00165
strength=0.0             GL=6c01558f70da VK=ebecea7ec94d   ΔMAE GL=0.00165 VK=0.00165
loom_post_gl.params is loom_post.params = True
```

- 改 `loom_post.DEFAULTS['threshold']`（即 `params()` 返回的阈值）→ **两端同时变，且 ΔMAE 完全相等**；`strength=0` 时两端也同时退化为同一张"无 bloom"图（说明公式路径一致）。
- 代码：GL 每次 draw 读 `params()`（`loom_post_gl.py:165`），VK 每次 `_record_post` 读（`vk_renderer.py:1042-1043`）。
- 小保留：GL 在 import 时就绑定了函数对象（`loom_post_gl.py:15`），VK 在调用时 `from loom_post import params`；所以"运行期替换 `loom_post.params` 这个函数本身"只有 VK 会跟随；改 `DEFAULTS`/环境变量两端都跟随（这正是用户可用的两个旋钮）。
- **判定 ③：成立（真共享，不是同名函数）。**

---

## 4. ④ 假 `depth_mask` 是否真的没了

- 静态：`grep depth_mask Loom` 只剩注释/文档字符串：`loom_pass.py:12,45`、`loom_pass_gl.py:11,149`、`loom_render.py:179-181,343-344`、`vk_ui.py:647`；**无任何赋值**。
- 运行期（`verify_01_apply_clear.py`，ab_sky 跑一帧）：
```
hasattr(moderngl.Context, "depth_mask") = False
跑帧日志行数 = 1 ; 日志含 depth_mask = False ; 日志含 AttributeError = False
   | [渲染] 天空盒 读 depth_func 失败 (NotImplementedError()) -> 用默认值
```
- **判定 ④：成立**（假属性写已删，跑帧不再有该 AttributeError）。
- 残留（P3，不改变判定）：
  1. 每帧仍走异常兜底读 `ctx.depth_func`（moderngl 5.13 的 getter 抛 `NotImplementedError`，`loom_render.py:183-186`；`_sky_warn` 只打一次）。不是 depth_mask，但"状态读取靠异常"依旧。
  2. `loom_render.py:104` 文档串仍写"不写 depth mask"，与已删代码的表述不一致（注释级）。
  3. world-canvas 分支（原 `:343-354`）本机探针未跑到（编辑器路径不画 world canvas；`ab_ui_scene.json` 只有 `screen` canvas），仅静态验证。

---

## 5. ⑤ `LOOM_POST_STAGE=0` 两端是否真关掉后处理

```
# verify_01_post_stage.py（ab_bloom.json；每档两端各渲染一次，VK 每次新建 renderer）
default(stage=3) GL=f19e9411558c VK=bd2ebd76f9ee | GL plan=[main,sky,bright,down,tonemap] | VK plan=[shadow_maps,main,sky,bright,down,tonemap]
STAGE=0          GL=0aca91131780 VK=a9f9b16fe9d0 | GL plan=[main,sky] | VK plan=[shadow_maps,main,sky]
    STAGE=0 vs stage3: GL ΔMAE=0.03345  VK ΔMAE=0.03345
LOOM_POST=0      GL=0aca91131780 VK=a9f9b16fe9d0 | GL plan=[main,sky] | VK plan=[shadow_maps,main,sky]
    STAGE=0 vs POST=0: GL ΔMAE=0.00000  VK ΔMAE=0.00000
STAGE=1 → plan=[main,sky,tonemap] / VK=[shadow_maps,main,sky,tonemap]；STAGE=2 → +bright
```

- 两端 plan 词表都去掉 bright/down/tonemap（`loom_pass.py:172-174` + `loom_post.py:53-63`），且 **STAGE=0 与 LOOM_POST=0 逐像素同哈希**、与 stage3 有明显差（0.03345）。
- **判定 ⑤：成立**（两端都真的关掉，且等价 LOOM_POST=0）。
- 保留项：
  1. VK 的开关在 `__init__` 只算一次（`vk_renderer.py:735`），运行期改环境变量不生效；GL 每帧读（`loom_render.py:1171` / `editor.py:2486`）。启动前设置则两端一致。
  2. **STAGE=1 与 STAGE=2 逐像素相同**（GL 6c01558f70da / VK ebecea7ec94d），且都与"bloom 关闭"相同（threshold=5.0 同哈希）→ 分级档 2（+bright）**无可见效果**，因为 tonemap 只读 quarter（`loom_pass_gl.py:184`、`vk_renderer.py:1032`），bright 的输出（half）不进合成。P2 级语义问题（分级名义存在、档 2 是死档），不影响 stage=0 的结论。

---

## 6. 实测对照（宣称 vs 实测）

| 宣称 | 实测 | 判定 |
|---|---|---|
| VK "删一个 pass / 改顺序，输出跟着变"、"pass 顺序…读同一份" | 删 main：GL Δ0.63680 / VK Δ0.00000；swap main↔sky：GL 0.26022-0.24656 / VK 0.00000 | **不实（主链）** |
| VK 由 `frame_plan()` 驱动 | 11 处引用；6 个 pass 存在性 + main/sky 烘焙参数 + 后处理段；13 个反例中 6 个响应 | **部分达成** |
| 语义面 14 → 6 | 14 项重复实现一项未消除；6 = 重新分桶 + 丢弃 U1/U12/U13 | **不实（口径）** |
| 共享 8 项 | 真共享 3 类（S1-S3）；目标名/depth/raster/draws 各只部分 | **高估** |
| 目标语义名与格式共享 | plan 写 `shadow.depth=format depth32float`（`loom_pass.py:224`），VK 实为 r32float（`:1145`）；bloom 目标格式 VK 硬编码 rgba16float（`:959`） | **仅 GL 成立** |
| 后处理目标尺寸取 `TargetDecl.scale` | 改 bloom.half scale：VK Δ0.00083，GL Δ0.00000（GL 硬编码 w//2,w//4，`loom_post_gl.py:124-125`） | **VK-only** |
| 后处理参数共享 | 改 threshold/strength 两端 ΔMAE 相等 | **成立** |
| 假 depth_mask 已删 | grep 无赋值；跑帧无 AttributeError | **成立** |
| LOOM_POST_STAGE=0 两端等价 POST=0 | ΔMAE 0.00000 两端、同哈希 | **成立** |
| LOOM_POST_STAGE 分级 0..3 有意义 | 档 1 ≡ 档 2 ≡ bloom-off | **档 2 死档（P2）** |

---

## 7. 不实之处（按严重度）

| # | 等级 | 不实点 | 证据 |
|---|---|---|---|
| V01-1 | **P1（验收叙述）** | "VK 由共享描述驱动主链（顺序/存在性）"不成立：删 main、改 main↔sky 顺序 VK 像素不变 | 1.2 表；`vk_renderer.py:2309,2322,2354` |
| V01-2 | **P1（数字）** | "语义面 14 → 6" 是分母重分组（丢 3 项、并 5 组），重复实现仍是 14 项 | 2.2/2.3 |
| V01-3 | P2 | `plan.clear/load` 对 VK 无效（硬编码 CLEAR_COLOR_RGBA/LoadOp.clear） | 1.2：GL 0.22379 / VK 0.00000 |
| V01-4 | P2 | main target 改 LDR → VK `TypeError: 'NoneType' object is not subscriptable`（后处理目标分配挂在 `main.target==HDR`，而非 `plan.targets`） | `vk_renderer.py:2311-2313,1044-1059` |
| V01-5 | P2 | 同一 `sky.raster.cull` 声明两端行为相反：VK 生效（0.24656），GL 被 `_draw_skybox` 内部重设覆盖（0.00000） | `loom_render.py:188-189`；1.2 表 |
| V01-6 | P2 | `TargetDecl.format`/`scale` 只对 main（format）或只对 VK（scale）生效；GL 目标尺寸仍硬编码 | `vk_renderer.py:938-941,959` vs `loom_post_gl.py:124-125` |
| V01-7 | P2 | `LOOM_POST_STAGE=2` 与档 1 逐像素相同（bright 不被 tonemap 消费）→ 分级名义 4 档、实际 3 档 | 第 5 节哈希 |
| V01-8 | P3 | 每帧仍走 `ctx.depth_func` getter 异常兜底；`loom_render.py:104` 文档串仍提"不写 depth mask" | 第 4 节 |
| V01-9 | P3 | `plan.bindings/params/shader/submit` 仍 0 消费者（上轮 N-04 未消除，"共享"叙事包含它们） | 2.2 U10/U11/U14 |

---

## 8. 结论

1. **① 部分达成**：VK 已从"0 引用"变为"每帧调 `frame_plan()`" + 11 处消费，但在主链顺序、main 存在性、clear/load、非后处理 draws 上仍**不是** plan 驱动；13 个反例里只有 6 个让 VK 输出变化。
2. **② "14→6" 不成立**：14 项重复实现一项未消除（U1-U14 现证据齐全）；6 是重分桶+丢项后的分母。真共享只有 3 类（后处理参数/开关、后处理段集合与顺序、pass 存在性）。
3. **③ 成立**：`loom_post.params()` 是两端单源，改 threshold/strength 两端同幅变化。
4. **④ 成立**：假 `depth_mask` 写已删，跑帧无该 AttributeError（残留每帧 depth_func 异常兜底与一条过期注释）。
5. **⑤ 成立**：`LOOM_POST_STAGE=0` 两端都真关后处理，与 `LOOM_POST=0` 逐像素一致；档 2 无可见效果（P2）。
6. **需裁决**：是否接受"pass 存在性 + 后处理参数"作为 beta6 渲染抽象的验收口径？若不接受，V01-1/V01-2 必须写回版本计划（补做"VK 主链顺序由 plan 驱动"或明确把 14 项中的 U1/U12/U13 保留为 beta7 债）。
