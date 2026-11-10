# final2_02 · 上一轮「未达成/部分」项独立复核（第十一轮倒查）

> 编号：02 ｜ 主题：复核上一轮 5 条宣称（语义面 / TargetDecl.scale / VK 地板闸 / 晕圈口径 / P3-1）｜ 日期：2026-11-11
> 基线：HEAD `e34d4d8e`。**本人开跑后工作树被他代理改动**（见 §0.2），本报告只对自己实测到的字节负责。
> 方法：不引用实现方任何数字；每条都构造反例，跑出可复现输出。探针全部在 `Loom/tests/_tmp/`（gitignore 已覆盖，`git status` 无新增）。

## 0. 基线与方法

### 0.1 命令（全部在 `Loom/` 下，`py -3.12`）

| 编号 | 命令 | 用途 |
|---|---|---|
| P1 | `py tests\_tmp\final2_02_scale.py` | 改 `bloom.half.scale` 0.5/0.4/0.25，两端 MAE + **实际目标尺寸**；附带 `format` 反例 |
| P1b | `py tests\_tmp\final2_02_scale_dyn.py` | 同一 GL 引擎内 scale 0.5→0.4（动态生效反例） |
| P2 | `py tests\test_frame_plan_vk.py` | 受跟踪的「改 plan 两端都变」矩阵（复跑确认绿） |
| P3 | `py tests\_tmp\final2_02_vk_gate.py` | loader 1.1+adapter 1.0 / 非 vulkan / 无 loader 文案 / **真机 adapter_info 形状** |
| P4 | `py tests\test_post_bloom.py` + `py tests\_tmp\final2_02_halo.py` | 晕圈固定圆心 10–22px；另复算旧口径 |
| P5 | `py tests\_tmp\final2_02_pkg_guard.py` | 子进程跑真实 `build_game.main()`（材质引用场景 + 缺资产库） |

### 0.2 基线偏差（必须记录）

我起跑时（00:48）`git status` 干净；01:02–01:03 出现**非我所为**的改动：
`Loom/fastpath.py`(+87 行 ckernels 搜索目录)、`tools/package_engine.py`(+36)、`tools/package_engine_compiled.py`(+28)、`tools/smoke.py`(34 行改动)，另有未跟踪的 `docs/audit/final2_01_…`。
→ 这 4 个文件**与本轮 5 条判定无关**（我只用了 `build_game.py` / `loom_pass*` / `vk_*` / `loom_backend_guard.py`，均未被改动）。但「工作树应干净」的前提**不成立于我的取证时刻**，打包类结论（P5）只对当时字节有效。

## 1. 逐条判定

| # | 上一轮宣称 | 我的判定 | 一句话证据 |
|---|---|---|---|
| 1 | 语义面 ≤8（8 共享 / 1 部分 / 4 不共享 / 1 合理差异）；bindings·params·submit 已删；VertexLayout/ShaderSet 不存在 | **删除类宣称 ✅；≤8 ❌ 未达成（换分母构成）** | 同一 14 分母下未共享折算 **9.5–11.5 > 8**；旧 14 未共享项被并成 6 桶、旧「共享 6」被拆成 8 |
| 2 | 改 `bloom.half.scale` 0.4 → GL 0.000375 / VK 0.000375 | **✅ 成立（首次建链路径）**，但**动态改描述只 GL 不跟**（新发现） | GL/VK 实际 half 目标 240→192；同进程内改描述 GL 仍 240 |
| 3 | loader 1.1+adapter 1.0 拒 / 非 vulkan 拒 / 无 loader 文案已格式化 | **① 部分（仅字符串形状生效，真机形状下闸是空闸）②③ ✅** | 真机 `adapter.info` **无 api_version 字段** → `aver=None` 短路；嵌套 dict 形状 `_parse_api_version` 返回 None |
| 4 | 固定圆心 + 环 10–22px = +22.1%，旧 +42.5% 作废 | **✅ 成立（复现 22.1%）**，旧口径确为「逐帧各自取最亮像素」 | 0.3414→0.4168(+22.1%)；旧口径圆心漂 6px → 0.3414→0.4866(+42.5%) |
| 5 | 只有材质引用 + 缺资产库 → 真实 main() 拒绝出包且无包 | **✅ 成立**（补：发布夹残留 1 个文件） | rc=1、无 `游戏包.lsc`、报错点名 assets.json；对照场景正常出包 |

## 2. 证据明细

### 2.1 语义面重数（分母 14，自判，不抄）

原 F-01 的 14 是「两端各写一遍的语义面」。**逐项判**（依据 `vk_renderer.py:2194 for spec in plan.passes` 之后的实际消费）：

| # | 语义面 | 判定 | 证据（HEAD） |
|---|---|---|---|
| 1 | 目标分配 | **部分** | 名/尺寸来自 `TargetDecl`（`vk_renderer.py:939-948`、`loom_pass_gl.py:98-104`）；**`format` 两端都不消费**（§2.2 反例 MAE=0） |
| 2 | 阴影编码 | 不共享 | GL `sampler2DShadow`(`loom_shaders.py:82,133`) vs VK r32float 手工比较 |
| 3 | 阴影提交粒度 | 合理差异 | `vk_renderer.py:2356,2377,2382,2415` 每槽位独立 encoder；GL 立即模式 |
| 4 | 天空时机 | **共享** | VK 按 plan 顺序在 main 之后单独 pass（`2218-2240`），深度语义取 `spec.depth`（`1182-1183`） |
| 5 | 天空几何 | 部分 | GL 6 顶点 quad vs VK `draw(3)` |
| 6 | 天空参数块 | 不共享 | GL 具名 uniform vs VK 112B UBO（`1214`） |
| 7 | 实例数据布局 | 不共享 | GL 桶 VBO vs VK 160B/64B（`2066` 注释） |
| 8 | HUD/UI 叠加 | 部分 | 存在性/顺序来自 plan（`2201-2203`），光栅化两套（VkUIEngine vs loom_ui） |
| 9 | 着色器源码 | 合理差异 | GLSL vs WGSL 两份（含后处理公式两份） |
| 10 | 绑定槽 | 不共享 | `PassSpec.bindings` 已删，绑定号仍两端各写 |
| 11 | 参数块打包 | 不共享 | `loom_lighting.py` 具名 uniform vs VK `f32[352]` |
| 12 | mip 生成 | 不共享 | `loom_cubemap.py:203 build_mipmaps()` vs `vk_renderer.py:1594-1636` 手写 downsample |
| 13 | 后处理管线构建 | 部分 | 段集合/顺序/参数/目标来自 plan，管线对象两端各建（GL `ctx.program` vs VK `create_render_pipeline`） |
| 14 | submit 粒度 | 合理差异 | GL 无该概念；VK 阴影 1 次(`2377/2415`)+主链 1 次(`2242`)+UI 各 1 次(`1340`) |

**统计**：完全共享 **1**、部分 **3**、合理差异 **2**、不共享 **8**（合计 14）。
未共享折算（半权、不剔除合理差异）= 14−1−1.5 = **11.5**；剔除合理差异 = **9.5**。两种都 **> 8**。

**为什么上一轮得出 ≤8**：其分母虽也写 14，但**构成完全不同**——把原本就共享的「6 项」拆成 8 项（顺序/目标名+格式+尺寸/load-clear/深度/光栅/绘制源名/post 阶段/post 参数），再把旧 14 未共享项**并成 6 桶**（天空时机+几何+参数块→1，阴影编码+提交→1，实例布局+桶+submit→1，参数块打包，UI 光栅化，GLSL/WGSL）。这正是 §9.24 判过的那类「重新分桶」。
**真实新增**（本轮真有进步，应予肯定）：`load/clear`、深度声明、光栅声明、后处理阶段/顺序、**天空时机**、目标名+scale 由描述驱动——VK 已真遍历 `plan.passes`（`test_frame_plan_vk` 7/7 反例两端同向，GL≈VK 比值 1.000）。

**删除类宣称（逐项验证，全仓 `*.py`）**：`BindingSpec|ParamField|VertexLayout|ShaderSet` → `Loom` 子树 **仅 1 命中，且是注释**（`loom_pass.py:58`）；`.bindings/.submit/.params` 命中 53 处**全是无关对象**（mesh/线程池/组件 params）。`loom_pass.py:63-85` 的 `PassSpec` 已无该三字段。
**措辞偏差**：`research_beta6_01_render_pass.md:109` 写的是「接口草案（dataclass 级，**不实现**）」，全库无字面「未实现」标注——语义等价，但 §9.27 说「文档已标注『未实现』」不精确。

### 2.2 `TargetDecl.scale`：两端生效（含反例）

```
基线: GL 半目标=(240, 160) | VK sizes={'bloom.half': (240, 160), ...} 后处理链在 plan 里=True
scale=0.50 GL半目标=(240, 160) VK半目标=(240, 160) | GL MAE=0.000000 VK MAE=0.000000
scale=0.40 GL半目标=(192, 128) VK半目标=(192, 128) | GL MAE=0.000375 VK MAE=0.000375
scale=0.25 GL半目标=(120, 80) VK半目标=(120, 80) | GL MAE=0.000825 VK MAE=0.000825
[反例] bloom.half.format rgba16float->rgba8unorm: GL MAE=0.000000 VK MAE=0.000000
```
尺寸与像素都跟随（480×0.4=192，期望一致）；**但 `format` 改了两端都毫无变化**（描述里的格式仍是装饰）。
**动态反例**（同一 GL 引擎，改描述不重建）：
```
第 1 帧组: scale=0.50 engine._post_sizes[half]=(240,160) 实际 FBO=(240,160)
第 3 帧组: scale=0.40 engine._post_sizes[half]=(192,128) 实际 FBO=(240,160)  ← 描述读了、目标没换
```
根因：`loom_post_gl.py:104-107 ensure()` 以**屏幕尺寸**为早退键，scale 变化不触发重建；VK `_ensure_post_targets` 的 key 含 sizes 会重建。→ 两端对**同一份**动态描述响应不一致（窗口 resize 才自愈）。

### 2.3 VK 地板闸

```
PASS G1 loader1.1+adapter1.0(字符串) -> 拒  VkBackendInitError
PASS G1 文案同时给两者版本  “显卡驱动的 Vulkan API 为 1.0.0，低于地板 1.1（…加载器报 1.1.0）”
G2 嵌套 dict {major:1,minor:0} -> ret=(1,1,0) err=None  parse=None     ← 未拒
G3 真机 adapter_info_dict = {'vendor':'NVIDIA', … ,'backend_type':'Vulkan'}   ← **无 api_version**
PASS G3 真机 info 里没有 api_version 字段  None
PASS G3 生产形状的 adapter_info -> 闸不拦（aver=None 短路）
PASS G4 真 run_vk 选到 d3d12 -> VkBackendInitError / 文案含「非 Vulkan」
PASS G5 无 loader -> 拒，文案含调用方名、无字面 %s
```
结论：②③ 成立；**① 只在「`api_version` 是字符串」的合成形状下成立**。生产路径 `vk_player.py:361,369` 传的 `adapter_info_dict(adapter)` 在 wgpu 0.32（本机）里**根本没有 api_version**，`loom_backend_guard.py:197` 的 `aver is not None` 直接短路 → 「loader 1.1 + adapter 1.0」在真机上不会被这道闸拦住。测试 K1/K3 用的是 `'api_version': '1.0.0'`（`test_backend_fallback_policy.py:405,415`），属**形状过拟合**。

### 2.4 晕圈口径

```
口径 A 固定圆心（关 bloom 帧最亮像素 = (112,234)）
 环  6-14: 0.3800 -> 0.5070 (+33.4%)
 环  8-18: 0.3618 -> 0.4586 (+26.8%)
 环 10-22: 0.3414 -> 0.4168 (+22.1%)   ← 与文档一致
 环 12-28: 0.3077 -> 0.3624 (+17.8%)
 环 20-40: 0.2362 -> 0.2607 (+10.4%)
口径 B 每帧各自取最亮像素（旧口径）: 圆心 (112,234) -> (118,233) 位移(6,-1)
 环 10-22: 0.3414 -> 0.4866 (+42.5%)   ← 旧记录就是它
```
受跟踪测试 `py tests\test_post_bloom.py` 复跑 5/5 PASS，打印 `晕圈: 0.3414 -> 0.4168 Δ=+0.0754 (+22.1%)`。
文档侧：`版本计划:395` 明确「旧记录的 +42.5% … 已作废」，`:390-392` 的五档表与我的实测**逐档一致**。
残留（P4）：历史审计 `final_03_四批目标达成度核对.md:46,105,218` 仍把 +42.5% 当达成证据且未加作废标记，容易被再次引用。

### 2.5 P3-1（真实 main()）

```
== A. 只有材质引用 + 无资产库 ==
   rc=1 pkg=False 残留文件=1
   stderr: 请把场景放回项目目录（项目根 = 含 Assets/assets.json 的目录）后重新构建…
== B. 无任何引用（对照）        == rc=0 pkg=True
== C. 旧格式内联材质（不算引用）== rc=0 pkg=True
== D. 失败后的发布夹残留      == 发布夹存在=True 文件数=1 样例=['MyGame.exe']
```
成立。**但**：`build_game.py:434` 先 `copy_project_assets` + `382-395` 已 `os.makedirs(out)` 并拷运行时，守卫在 `:439` 才抛 → 失败后留下半成品发布夹（本例仅 1 个 stub 文件，真实构建会留整套运行时）。属「有包才算成功」的边界瑕疵，不是死 guid 包。

## 3. 新发现（本轮独立，非上一轮转述）

| ID | 级别 | 内容 |
|---|---|---|
| F2-02-N1 | **P2** | VK adapter 版本闸在生产形状下**恒不生效**（真机 `adapter.info` 无 api_version；嵌套 dict 也解析成 None）。要么用 `adapter.info.api_version` 之外的来源（`vkGetPhysicalDeviceProperties`/`adapter.limits`）补，要么在文档里降级为「仅 loader 闸」。测试 K1/K3 需要换成真实形状 |
| F2-02-N2 | **P2** | `TargetDecl.format` 仍是装饰字段：改 `bloom.half.format` 两端 MAE=0；GL `_mk_fbo` 写死 f2、VK post 目标写死 rgba16float。§9.27「目标语义名+**格式**+尺寸」共享不成立 |
| F2-02-N3 | P3 | 动态改描述时 GL 不重建后处理目标（`ensure()` 早退键是屏幕尺寸）→ 「描述驱动」只在首次建链/分辨率变化时成立；两端不一致 |
| F2-02-N4 | P3 | 死条目：`DrawCmd` 的 `'fullscreen'` 字面量无注册无使用；GL `_DEFAULT_DRAWS` 有 `'post.up'` 但 plan 从不产出该源（`loom_pass_gl.py:250` vs `loom_pass.py:66-68`） |
| F2-02-N5 | P3 | VK 对 `hud`/`ui`/`shadow_maps` 三个 pass **按 id 分派、不读 `spec.draws`**（`vk_renderer.py:2196-2203`）→ 「绘制源名 9/10 项共享」实际覆盖 6–7 项 |
| F2-02-N6 | P4 | 失败出包会留半成品发布夹（见 2.5）；建议守卫前挪到 `copy_project_assets` 之前 |

## 4. 统计

| 项 | 结果 |
|---|---|
| 复核目标 5 条 | **2 条完全成立**（4 晕圈、5 P3-1）、**1 条成立但有动态缺口**（2 scale）、**1 条部分成立**（3 VK 闸）、**1 条不成立**（1 语义面 ≤8） |
| 语义面同一 14 分母 | 共享 1 / 部分 3 / 合理差异 2 / 不共享 8 → 未共享折算 **9.5–11.5 > 8** |
| 删除类宣称 | 3 字段 + 2 类型：**代码 0 引用，成立** |
| 探针 | 5 个，均在 `Loom/tests/_tmp/final2_02_*`（gitignored）；无受跟踪文件改动 |

## 5. 待裁决

| ID | 问题 | 选项 |
|---|---|---|
| Q-1 | 「重复语义面 ≤8」是否接受**更换分母构成**（把旧共享 6 拆成 8、旧未共享 14 并成 6 桶）？ | A 不接受，按原 14 未共享口径判「未达成」，继续 beta6 打磨／B 接受新口径并同时改写 §9.22 的分母定义与验收标准 |
| Q-2 | VK adapter 版本闸（N1）本轮补还是降级为「仅 loader 闸 + 文档说实话」？ | A 补真实来源＋改 K1/K3 用真形状／B 降级并登记 |
| Q-3 | 动态 scale（N3）与失败残留发布夹（N6）是否本轮修？ | A 都修（各 <15 行）／B 登记后续 |
