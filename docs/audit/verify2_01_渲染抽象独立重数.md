# verify2_01 · 渲染抽象「真的达成了吗」——独立重数（任务后倒查 · 第九轮）

> 编号：01 ｜ 主题：VK 是否真遍历 plan / 反例矩阵 / 语义面重数 / 三个 P2 复查 ｜ 日期：2026-11-10
> 方式：**只读业务代码**；探针只写 `Loom/tests/_tmp/verify2_01_*.py`（`Loom/.gitignore:22` 已忽略）；本报告写 `docs/audit/`。
> 基线：HEAD `576d18a`（**开始取证时**工作树干净；取证期间并行子代理引入了与本报告无关的改动，见 §7）。Python 3.12.10 / moderngl 5.13.0 / wgpu 0.32.0 / NVIDIA GTX 1050 Ti（Vulkan）。
> **不引用 V-01 / R01 的任何数字作为结论**：下文每个数字都由第 0 节命令当场跑出；历史数字只在第 3、6 节作对照。

---

## 0. 复现命令

```powershell
cd Loom
py -3.12 tests/_tmp/verify2_01_matrix.py legacy   # 反例矩阵，LOOM_POST=0
py -3.12 tests/_tmp/verify2_01_matrix.py post     # 反例矩阵，默认后处理链
py -3.12 tests/_tmp/verify2_01_post_stage.py      # LOOM_POST_STAGE 0..3
py -3.12 tests/_tmp/verify2_01_targets.py         # TargetDecl.scale/format/target
py -3.12 tests/test_frame_plan_vk.py              # 受跟踪测试是否真的全绿
```

方法：GL 走 `editor.EditorApp.render`（真实渲染路径），VK 走 `SceneDriver + VkRenderer.draw_frame`（复用 `tests/test_ab_gl_vk.py` 的 480×320 离屏夹具）；只把 `frame_plan` 这一层返回值（`loom_pass / editor / loom_render` 三个真实调用别名）替换成「改过的描述」，再比同后端基线 `MAE(float64)`。**两端都用同一份改过的 plan**；像素有变化即证明该端消费到了 plan。

---

## 1. 反例矩阵：VK 是否与 GL 同向、幅度是否相近

### 1.1 LOOM_POST=0（主链目标 = 屏幕）

```
MODE=legacy  scene=ab_sky  baseline GL=318a2f577835 VK=ae8b09dafe4b  GL-VK MAE=0.000017
mutation                    GL_dMAE    VK_dMAE GL_hash        VK_hash
drop main                  0.636798   0.636798 91d2d62a5700   91d2d62a5700  plan=('shadow_maps','sky')
swap main<->sky            0.260219   0.260219 aaba86926586   893f7f449e73  plan=('shadow_maps','sky','main')
main.clear=(1,0,0,1)       0.000000   0.000000 318a2f577835   ae8b09dafe4b  plan=('shadow_maps','main','sky')
clear=red + drop sky       0.390707   0.390707 7da7b42c86bf   77c072f42c79  plan=('shadow_maps','main')
main.draws=skybox          0.088698   0.088699 d1d4743ac6b0   d1d4743ac6b0  plan=('shadow_maps','main','sky')
main.load=load             0.636798   0.636798 91d2d62a5700   91d2d62a5700  plan=('shadow_maps','main','sky')
main.depth.test=False      0.088698   0.260219 d1d4743ac6b0   893f7f449e73  plan=('shadow_maps','main','sky')
sky.raster.cull=back       0.000000   0.260219 318a2f577835   893f7f449e73  plan=('shadow_maps','main','sky')
```

### 1.2 默认后处理链（ab_sky，post 开）

```
MODE=post  baseline GL=d3c821b71ee4 VK=eef4a473bedf  GL-VK MAE=0.000012
drop main                  0.630258   0.630257 91d2d62a5700   91d2d62a5700  plan=('shadow_maps','sky','bloom.bright','bloom.down','tonemap')
swap main<->sky            0.246563   0.246563 435ecb44878e   4e0769adee90  plan=('shadow_maps','sky','main',...)
main.clear=(1,0,0,1)       0.000000   0.000000 d3c821b71ee4   eef4a473bedf  plan=('shadow_maps','main','sky',...)
clear=red + drop sky       0.333808   0.333808 afe39b4954e2   4e3306bb38cf  plan=('shadow_maps','main',...)
main.draws=skybox          0.060892   0.060893 730ba1e35672   730ba1e35672  plan=('shadow_maps','main','sky',...)
main.load=load             0.630258   0.630257 91d2d62a5700   91d2d62a5700  plan=('shadow_maps','main','sky',...)
main.depth.test=False      0.060892   0.246563 730ba1e35672   4e0769adee90  plan=('shadow_maps','main','sky',...)
sky.raster.cull=back       0.000000   0.246563 d3c821b71ee4   4e0769adee90  plan=('shadow_maps','main','sky',...)
```

### 1.3 判定

| 反例 | 同向？ | 幅度比 VK/GL | 判定 |
|---|---|---|---|
| 删 main | 是（两端 >1e-3） | **1.000**（legacy 连哈希都相同：`91d2d62a5700`） | 达成 |
| main↔sky 换序 | 是 | **1.000** | 达成 |
| 改 clear（单独） | 是（都 0） | — | **无区分力**：天空盖住底色；必须叠加删 sky |
| 改 clear + 删 sky | 是 | **1.000** | 达成 |
| main.draws=skybox | 是 | **1.000** | 达成 |
| main load=load | 是 | **1.000**（legacy 两端同哈希） | 达成 |
| depth.test=False | 是 | **4.05×**（0.060892 / 0.246563） | 方向同、**幅度与画面语义不同** |
| sky.raster.cull=back（附加） | **否** | GL 0 / VK 0.246563 | 两端相反（见 4.2） |

- **"六类反例同向"成立**：R01 列出的六类在两端都 >1e-3（clear 需按它自己说的叠加删 sky）。
- **"幅度相近"只 5/6 成立**。`depth.test=False` 时 VK 的 0.246563 与"换序/天空剔除"同一张图（哈希 `4e0769adee90`）：因为 `_begin_plan_pass` 在 `depth.test=False` 时**整段不给深度附件**（`vk_renderer.py:2281-2290`），天空 pass 又按 `load` 读一份主 pass 从未写入的深度（`2288-2289`），于是天空以 LEQUAL 压过几何；GL 则仍保留几何、天空只让位。**两端都"响应"，但不是同一语义**。
- `sky.raster.cull` 未被 R01 的六类覆盖，实测仍两端相反（4.2）。

---

## 2. 是否真的遍历 `plan.passes`（静态 + 行号）

### 2.1 主链确实是循环执行（不是"按 id 读存在性 + 固定顺序"）

```
vk_renderer.py:2191   for spec in plan.passes:
vk_renderer.py:2192       pid = spec.id
vk_renderer.py:2193-2197  shadow_maps -> _exec_shadow_maps(...)        # 按 plan 中的位置执行
vk_renderer.py:2198-2200  hud/ui -> 收集，稍后按 plan 相对顺序落 UI 层
vk_renderer.py:2201-2204  未知 id -> 打印并跳过（不静默执行固定 pass）
vk_renderer.py:2205-2208  后处理 id -> _record_post_pass(enc_main, spec, plan, ...)
vk_renderer.py:2211      _decl = plan.target_by_name(spec.target)
vk_renderer.py:2215      rp = _begin_plan_pass(enc_main, spec, plan, view, w, h)
vk_renderer.py:2216      for src in [c.source for c in spec.draws]:
vk_renderer.py:2217-2234     buckets / skybox / world_canvas 按 draws 派发
vk_renderer.py:2237      rp.end()
```

- 主 pass 的目标/格式/load/clear/深度全部取 `spec`：`_begin_plan_pass` 在 `2266-2295`（load/clear 在 `2273-2279`，depth 在 `2281-2290`）。
- 3D 目标名解析：`_target_view` `2257-2264`；后处理单 pass：`_record_post_pass` `2309-2344`。
- **结论：R01 的"真遍历"成立**——主链/后处理/3D 的**顺序、存在性、目标、load/clear、draws** 都由 `plan.passes` 驱动。V-01 当时"全文件 11 处 plan 引用、无一处遍历"已不成立。

### 2.2 残留的"按 id 读"与"固定顺序"（不影响主链结论，但要如实登记）

| 位置 | 行为 | 影响 |
|---|---|---|
| `vk_renderer.py:2185` | `self._frame_sky_spec = plan.pass_by_id('sky')`，供 `_ensure_sky` 烘焙管线 | 多个 sky pass / 改名时只认第一个同名 id |
| `vk_renderer.py:2338` | `any(p.id == 'bloom.down' for p in plan.passes)` 选 tonemap 采样源 | 语义正确，但属"按 id 查询"而非逐 pass 声明 |
| `vk_renderer.py:2247-2254` | HUD/UI 收集后在主链提交之后统一执行 | plan 若把 HUD 放在 main 之前，VK 仍最后执行（GL 按位置执行）→ 顺序语义未完全共享（P3） |

---

## 3. 语义面独立重数（26 项）

口径：把"跨后端一帧渲染必须对齐的语义"逐项列出；**共享** = 同一份声明被两端消费且改之两端都变；**部分** = 有声明但一端不读/只覆盖部分字段/幅度不等价；**未共享** = 两份实现。

| # | 语义面 | 状态 | 证据（HEAD 行号） |
|---|---|---|---|
| 1 | pass 集合（存在性） | **共享** | VK `2191` for；GL `loom_pass_gl.py:103` for；删 main 两端 0.6368/0.6368 |
| 2 | pass 顺序（主链+后处理） | **共享** | 同上；换序 0.2602/0.2602、后处理顺序同循环 |
| 3 | HUD/UI 相对顺序 | 未共享 | VK 收集后统一在主链后执行（`2198-2200,2247-2254`）；GL 按位置（`loom_pass_gl.py:103-127`） |
| 4 | 目标语义名解析 | **共享** | GL `loom_pass_gl.py:53-67`；VK `2257-2264` |
| 5 | 目标分配/生命周期 | 未共享 | GL FBO+renderbuffer（`loom_post_gl.py:112-125`）；VK 纹理+视图（`vk_renderer.py:947-972`） |
| 6 | 目标格式 | 部分 | VK main 读 `decl.format`（`2213,2271`）；GL 全程忽略；VK 后处理仍写死 rgba16float（`963,1003-1005`） |
| 7 | 目标尺寸/scale（含后处理目标） | 未共享 | VK `936-945`；GL 写死 `w//2,w//4`（`loom_post_gl.py:123-125`）；改 half.scale → VK 0.000825 / GL 0.000000 |
| 8 | load/clear（颜色） | **共享** | VK `2273-2279`；GL `106-115`；load=load 两端 0.6368 且 legacy 同哈希 |
| 9 | depth test/func | 共享（幅度不等价） | VK 烘进管线 `902-903`；GL `150-156`；反例 0.0609/0.2466 |
| 10 | depth write | 未共享 | GL 明确 advisory 不落地（`loom_pass_gl.py:157`）；VK 进管线键（`902`） |
| 11 | depth clear / 深度附件 | 部分 | GL 只对非屏幕/provider 目标清（`113-115`），屏幕走 `_clear_main_fbo`；VK 单张 depth 纹理（`2159-2163,2284`） |
| 12 | raster cull/front | 部分 | main 两端都读；**sky 的 cull 被 GL 内部重设覆盖**（`loom_render.py:188-190`），实测 0/0.2466 |
| 13 | raster blend | 部分 | GL `167-174` 真应用；VK 从不读 `raster.blend`（全文件无消费点） |
| 14 | draws 派发源 | **共享** | GL `120-124` 字典派发；VK `2216-2236`；draws=skybox 两端 0.0887 |
| 15 | 绘制实现（实例桶/天空顶点/HUD-UI 光栅） | 未共享 | `_draw_buckets_pass 2297` vs `vao.render`；天空 3 顶点（`1286`）vs 6 顶点（`loom_render.py:144-190`）；`vk_ui` vs `loom_ui` |
| 16 | 着色器源码 | 未共享 | WGSL（`_MAIN_VERT/_SKY_WGSL/_POST_WGSL`）vs GLSL（`loom_shaders.py`） |
| 17 | 绑定槽 | 未共享 | plan `bindings` 定义于 `loom_pass.py:141-156`，全仓 **0 个消费者** |
| 18 | 参数块打包 | 未共享 | plan `params`（`loom_pass.py:233-235`）**0 消费者**；VK f32[352]、GL 具名 uniform |
| 19 | submit 粒度 | 未共享 | `PassSpec.submit`（`loom_pass.py:100`）**0 消费者**；VK 多次 submit（主链 `2239`、阴影 `2372/2410`、UI `1337`）vs GL 立即模式 |
| 20 | 后处理参数 | **共享** | GL `loom_post_gl.py:165-191`；VK `2311-2313` 同调 `loom_post.params()` |
| 21 | 后处理段集合/顺序/目标/源 | **共享** | 同一循环；VK `2309-2344`，GL `137-145` |
| 22 | 后处理管线/目标构建 | 未共享 | GL program+VAO（`loom_post_gl.py:135-143`）；VK render pipeline+bind group（`974-1038`） |
| 23 | 阴影编码 | 未共享 | GL 真深度 `depth_texture`（`loom_shadow.py:51,58`）；VK r32float+手工比较（`vk_renderer.py:886-891,287-288`） |
| 24 | 阴影提交 | 未共享 | GL 立即模式 `fbo.use()`（`loom_shadow.py:98-100`）；VK encoder+submit（`2346-2410`） |
| 25 | 天空几何/参数块 | 未共享 | GL 6 顶点 quad+3 具名 uniform（`loom_render.py:144-171`）；VK 3 顶点+112B UBO（`1210-1215,1272-1286`） |
| 26 | mip 生成 | 未共享 | GL `tex.build_mipmaps()`（`loom_cubemap.py:203`）；VK `_gen_mips`（`vk_renderer.py:1615`） |

**计数：共享 7 / 部分 5 / 未共享 14，合计 26。**

### 3.1 与"14"对照

- V-01 的 14 是**纯重复实现**分母（U1-U14），结论 14/14 未共享。按同一分母逐项复查今天：
  - 仍存在 13/14：U1 目标分配、U2 阴影编码、U3 阴影提交、U5 天空几何、U6 天空参数、U7 实例布局、U8 HUD/UI、U9 着色器、U10 绑定槽、U11 参数块、U12 mip、U13 后处理管线、U14 submit；
  - **已消除 1 项**：U4"天空时机"——plan 顺序已把 sky 固定到 main 之后且两端同一循环（第 1 节换序反例即证）；
  - **新增 2 项**：目标尺寸/scale 单端（#7）、depth.write 单端（#10）；另把 U5/U7/U8 合成一项"绘制实现"（#15），所以我的未共享数仍为 14，但**构成已变**——不是"14 降到 6"。
- 真正扩大的是共享面：V-01 认 3 类真共享，本轮实测可举出 7 项（#1/#2/#4/#8/#14/#20/#21），这是 `e7e2a17` 的真实增量。

### 3.2 与"6"对照

- "6"来自 `6e9e315` 的提交说法（阴影编码+提交→1；天空时机+几何+参数→1；绑定槽+参数块→1；实例布局+submit→1；着色器→1；后处理管线→1），同时丢弃 V-01 的 U1 目标分配 / U12 mip / U13 后处理管线。
- 按这套分桶今天仍能凑出 6 组，但**组内实现一个都没合并**（本表 #15-19、#22-25 共 11 份仍是两份）；且"天空时机"现在已是共享项，说明 6 是**分组口径**而非"重复实现剩 6 份"。**"14→6"仍不成立。**

---

## 4. 此前点名 P2 的复查

### 4.1 `plan.clear/load` 对 VK 生效 —— **已修**

- 代码：`_begin_plan_pass` 读 `spec.load`/`spec.clear`（`vk_renderer.py:2273-2279`），不再硬编码 `CLEAR_COLOR_RGBA/LoadOp.clear`。
- 实测（第 1.1 节）：`main.load=load` → GL 0.636798 / VK 0.636798，且两端同哈希 `91d2d62a5700`；`clear=red + drop sky` → GL 0.390707 / VK 0.390707。**判定：成立。**

### 4.2 `sky.raster.cull` 两端一致 —— **未修**

- 实测：改 `sky.raster.cull='back'` → GL `0.000000`（图哈希不变 `318a2f577835`）；VK `0.246563`（哈希 `893f7f449e73`）。
- 静态：GL 执行器 `_apply` 确实按声明设了剔除（`loom_pass_gl.py:158-166`），但 `_draw_skybox` 内部又无条件 `disable(CULL_FACE)` 并在 finally 里重开（`loom_render.py:188-196`）→ **plan 的 sky.cull 在 GL 侧仍被覆盖**；VK 的 `_ensure_sky` 把 `_frame_sky_spec.raster` 烘进管线（`vk_renderer.py:1181,1203`）→ 生效。
- **判定：P2 仍在（两端相反）。**

### 4.3 `LOOM_POST_STAGE=2` 是否还是死档 —— **已修**

```
STAGE=0  plan=[shadow_maps, main, sky]                              GL=0aca91131780 VK=a9f9b16fe9d0
STAGE=1  plan=[..., tonemap]                                        GL=6c01558f70da VK=ebecea7ec94d
STAGE=2  plan=[..., bloom.bright, tonemap]                          GL=15a855d14bde VK=91ba34e264b4
STAGE=3  plan=[..., bloom.bright, bloom.down, tonemap]              GL=f19e9411558c VK=bd2ebd76f9ee
STAGE 1 vs 2 : GL dMAE=0.000529 DIFF ; VK dMAE=0.000529 DIFF
STAGE 2 vs 3 : GL dMAE=0.001198 DIFF ; VK dMAE=0.001198 DIFF
STAGE 1 vs 3 : GL dMAE=0.001646 DIFF ; VK dMAE=0.001646 DIFF
STAGE0 vs LOOM_POST=0: GL dMAE=0.000000 VK dMAE=0.000000
```

- 档 2 现在与档 1、档 3 都不同，且两端差分**逐位同值**；代码依据：GL 在 `execute` 里按 plan 设 `_post_bloom_src=half`（`loom_pass_gl.py:94-99`），tonemap 读它（`loom_post_gl.py:184-189`）；VK 无 down 时切 `tonemap_half` 组（`vk_renderer.py:2338-2339,1037`）。
- **判定：死档已消除。**（档 0 仍与 `LOOM_POST=0` 逐像素一致。）

### 4.4 附加：`TargetDecl` 的另两个 P2

```
baseline GL=f19e9411558c VK=bd2ebd76f9ee GL-VK=0.000000
half.scale 0.5->0.25     GL_dMAE=0.000000   VK_dMAE=0.000825   # 仍 VK-only
half.format->rgba8unorm  GL_dMAE=0.000000   VK_dMAE=0.000000   # 两端都不读格式
main.target->color.ldr   GL_dMAE=0.197079   VK_dMAE=0.182735   # 不再崩（V-01 的 TypeError 已消失）
```

- `TargetDecl.scale` 仍只对 VK 生效（GL 写死 1/2、1/4）；`format` 对后处理目标两端都无效（VK 写死 rgba16float）。**P2 未完全修**。
- `main.target` 改 LDR 不再抛异常，说明 V-01 的崩溃点已被顺带修掉，但两端幅度仍差 7%（0.197079/0.182735），语义未完全等价。

---

## 5. 受跟踪测试 `test_frame_plan_vk.py` 的质量

```
PASS 反例两端同向：删 main pass  (0.6302583813667297, 0.6302574276924133)
PASS 反例两端同向：main<->sky 换序  (0.2465628683567047, 0.2465628683567047)
PASS 反例两端同向：main.draws=skybox  (0.06089184060692787, 0.06089283153414726)
PASS 反例两端同向：main.load=load  (0.6302583813667297, 0.6302574276924133)
PASS 反例两端同向：main.depth.test=False  (0.06089184060692787, 0.2465628683567047)
PASS 至少 4 类反例两端都 >1e-3（VK 真读 plan）  5/5
PASS 正常路径未劣化（GL vs VK 基线仍很小）  1.1540030754986219e-05
PASS 双 dir 阴影：...（2 槽位 / 2 缓冲 / 2 视图）
ALL PASS
```

- 它确实把 5 类反例固化成了受跟踪测试，**没有锁源码字符串**，方向正确。
- 但判据 `(mg>1e-3)==(mv>1e-3)` 只看"变没变"，不看幅度/图像关系：`depth.test=False` 4.05× 差异仍判 PASS；**clear 不在 `MUTS`**（单独改无区分力，必须叠加删 sky，它没测）；**sky.cull 不在 `MUTS`**（真实不一致项没进网）。按倒查清单"阈值/判据是否悄悄放宽"，这里属于"覆盖面不足"，不是造假。
- 该测试只覆盖 ab_sky 一个场景；world_ui/hud/ui 的 order 语义无行为证据。

---

## 6. 结论（逐条）

| # | 待验证宣称 | 实测 | 判定 |
|---|---|---|---|
| 1 | VK 主链由 `plan.passes` 遍历驱动 | `vk_renderer.py:2191` 真循环；删 main/换序/draws/load/clear 全生效 | **成立**（主链/后处理/3D） |
| 2 | 六类反例下 VK 与 GL 同向且幅度相近 | 6/6 同向；5/6 幅度比 1.000；depth.test 4.05× | **基本成立，1 项例外** |
| 3 | 语义面 14→6 | 26 项中 共享 7 / 部分 5 / 未共享 14；6 是分桶 | **"6"不成立；重复实现仍有 14（构成已变）** |
| 4 | `plan.clear/load` 对 VK 生效 | load 两端同 Δ 同哈希；clear+删 sky 两端 0.390707 | **已修** |
| 5 | `sky.raster.cull` 两端一致 | GL 0.000000 / VK 0.246563；`loom_render.py:188-190` 仍覆盖 | **未修（P2）** |
| 6 | `LOOM_POST_STAGE=2` 死档 | 1vs2 两端 0.000529、2vs3 两端 0.001198 | **已修** |

**新增/遗留问题（按严重度）**

| # | 等级 | 问题 | 证据 |
|---|---|---|---|
| N1 | **P2（语义不等价）** | `depth.test=False` 时 VK 不给深度附件，天空读未写深度→整屏被天空覆盖；GL 保留几何。两端"同向"但画面不同 | 1.1/1.2；`vk_renderer.py:2281-2290` |
| N2 | P2 | `sky.raster.cull` 两端相反（4.2） | 实测 0.000000/0.246563 |
| N3 | P2 | `TargetDecl.scale` 仍只对 VK 生效；`format` 后处理两端都不读 | 4.4 |
| N4 | P3 | HUD/UI 的执行位置不随 plan（VK 统一在主链后 drain） | `vk_renderer.py:2247-2254` |
| N5 | P2（测试质量） | 受跟踪反例测试判据过宽（只看方向）、缺 clear/sky.cull 两类 | 第 5 节 |

**统计**：本报告用 3 个探针文件、5 条命令；反例 8 类×2 种 post 口径=16 次两端渲染（32 次），后处理 4 档×2 端=8 次，目标声明 3 类×2 端=6 次，受跟踪测试 1 轮 10 项。本子代理未改任何受跟踪业务文件（只写 `tests/_tmp` 探针与本报告）；取证后的工作树变化见 §7。

**待裁决**

1. 是否接受"主链真遍历 + 5/6 幅度一致"作为 beta6 渲染抽象的验收口径？若不接受，N1 需补"无深度 pass 时天空语义"的明确规则。
2. `sky.raster.cull`（N2）是明确"两端相反"的现存语义分叉，是否本轮必修 / 还是登记 beta7？
3. N4/N5 建议：受跟踪测试补 `clear(删 sky)`、`sky.cull`、以及"幅度比 ∈ [0.5,2]"判据；HUD/UI 顺序要么写进 plan 合同"UI 恒在最后"，要么让 VK 按位置执行。

---

## 7. 取证期间的并发噪声（与本报告结论无关）

- 22:04:20 工作树出现 `tools/measure_engine.py` 修改、`tools/verify_pkg_vs_head.py` 新增、`examples/pacman_*.py` 新增、`docs/audit/pacman_*.py` 删除，另有 `docs/audit/verify2_02_*.md`。**均非本子代理所写**（本子代理只写 `tests/_tmp/verify2_01_*.py` 与本文件）。
- 本报告所有数字取自 21:53–22:03，期间渲染链文件未变（`vk_renderer.py`、`loom_*.py` 的最后提交仍是 e7e2a17 / 6e9e315），故结论不受并发改动影响；受影响的是"工作树干净"这一环境陈述。
