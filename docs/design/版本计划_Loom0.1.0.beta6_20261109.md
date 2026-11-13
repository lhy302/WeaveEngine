# 版本计划草案：Loom 0.1.0.beta6 / LoomHub 0.1.4（2026-11-09 开启，**仅备选，未裁决**）

> 状态：**讨论稿**。人类要求"先挂起来慢慢想"，因此本文只登记候选方向与证据，**不代表已排期**。
> 版本号已按"开发期代号 = 正在开发的版本"改好（引擎 `0.1.0.beta6`、Hub `0.1.4`），发包时才跳 beta7 / 0.1.5。

---

## 0. 结论速览（一句话）

Loom 在"工程可运行性"上已不弱（双后端逐像素等价、编译发布、自更新、AI 命令桥），
但**内容生产能力**（动画/后处理/粒子/地形/资产管线）几乎为零；
且**渲染管线没有 Pass 抽象**，导致"每加一个效果就要 GL/VK 各写一遍"——这是下一批功能的最大乘数成本。

---

## 1. 与 Unity 的差距（扫描证据，非印象）

| 维度 | 已有 | 缺口（关键字扫描 0 命中即"无"） |
|---|---|---|
| 渲染 | 双后端、PBR、阴影（277 处）、IBL/env（139）、LOD（139）、GPU instancing（229）、多光源 | 后处理链**全无**：`bloom/ssao/ssr/tonemap/msaa` 各 0；无 HDR、无相机堆栈、无粒子、无地形、无遮挡剔除；**无 RenderPass 抽象**（`RenderPass|class *Pass` 0 处） |
| 动画 | transform 动画/关键帧（`animator` 61 处） | **骨骼/蒙皮 0**（`skeleton`/`skinned` 各 0）；无状态机、无根运动、无动画事件、无 IK |
| 物理 | Jolt 桥接（`physics_bridge` 67KB）、刚体与碰撞事件 | 角色控制器、关节完整度、碰撞层过滤、CCD、物理材质（需逐个核实） |
| 脚本 | Python + 热重载 + 事件 + EAI 命令桥（**超过 Unity 的一点**） | 无调试器/断点、无字段反射检查器、无协程语义 |
| 编辑器 | 层级/检查器/撤销（54KB）/gizmo/复制粘贴/播放 | 无资产导入管线、无时间轴/Sequencer（0 处）、无 Prefab 变体、无场景流式加载 |
| 构建发布 | build_game + 编译版运行时 + Hub 安装器 + 自更新 | 仅 Windows；无平台导出、无 `.pak` 资源打包、无增量构建、无签名 |
| 工具链 | 自研 profiler（简陋）、EAI/MCP 桥、审计/开发日志体系 | 无帧调试器、无内存/GPU 分析、无崩溃上报后端 |

---

## 2. 性能空间（含可行性判断）

### 2.1 当前余量（beta5 实测）

```
FPS 84-90 · TPS 30.2-30.5 · GPU 56%
剩余每帧：buckets 2.3ms / mt_mp_draws 1.4ms / aabbs 2.1ms / pipe_wait 3.6ms
```

GPU 仅 56% → GPU 侧有余量，瓶颈仍在**CPU 侧提交**（每桶一 draw + 多次 buffer write）。

### 2.2 三条路线的可行性

**① Python 版本升级（3.12.10 → 3.13 / 3.14）**

| 版本 | 预期收益 | 主要风险 |
|---|---|---|
| 3.13 | 纯 Python 约 5-15%；有实验性 free-threading | PySide6 / moderngl / wgpu-py / numba 的 wheel 与 **Nuitka 支持**需逐个验；free-threaded 生态基本未跟上 |
| 3.14 | 官方 free-threading + 初步 JIT（x86-64） | 依赖与编译工具链跟进最慢；Nuitka 支持滞后 |

判断：值得做，但应作为**隔离预研分支**（跑 121 测试 + bench 对照），不直接并主线。
真正的结构收益不是版本号 +10%，而是 **free-threading 让逻辑线程与渲染线程真并行**（正是 beta5 抓到的"单核 GIL 饥饿"的结构解）。

**② C → C++ 迁移**

规模纠正：**手写 C 很少**

```
Loom/ckernels/loom_kernels.c   18 KB（全部数学内核 → 16KB DLL）
Loom/core_components/*.c       约 5 个样例（插件 ABI 参考）
（player_runtime 下 167MB 的 .c 是 Nuitka 生成的编译产物，不是源码）
```

结论：**没有大规模 C 可迁**。更有价值的是反向——把仍是 Python 的热点**下沉**：
`buckets` 组装（2.3ms/帧）、`mt_mp_draws`（1.4ms/帧），或用 **multi-draw indirect** 把 38 次 draw 合成 1 次。

**③ 把 C++ 当主语言？**

代价 = 编辑器 GUI（PySide6）、脚本系统、EAI 命令桥、undo/序列化全部重写或桥接。
这是**重写引擎级别**的决定，不是优化。建议：不做主语言迁移，只做热点下沉 + 渲染提交层 C++ 化（可选）。

---

## 3. 设计骨架提前量评估

### 已铺好 ✅
- 双后端抽象 + 逐像素等价验证机制
- 场景序列化 + 配置分层（模板只读 / 用户 delta）+ 原子写
- EAI 命令桥（98 条命令全覆盖测试）
- 脚本系统 + 事件 + 热重载
- 撤销/复制/粘贴/gizmo 等编辑器基础
- 打包发布链（编译版 + 自更新）

### 明显欠账 ⚠️

| 欠账 | 后果 | 证据 |
|---|---|---|
| 无渲染管线/Pass 抽象 | 每加一个效果都要 **GL/VK 各写一遍** | `RenderPass` 0 处；`loom_render.py` 57KB vs `vk_renderer.py` 102KB 两套独立实现 |
| 无资产导入/guid 管线 | 贴图/模型/材质只能手工放目录；天空盒六面图至今靠"相对场景目录"而非资产 guid | beta5 刚因相对路径踩过坑 |
| 无动画系统底座 | 骨骼动画要从 transform 层重铺 | `skeleton/skinned` 0 处 |

**判断**：提前量未耗尽，但**后处理/粒子/骨骼若直接开写，会立刻变成双份复制**。
因此若 beta6 要动渲染功能，**先铺 Pass 抽象**是乘数决策。

---

## 4. 卫生问题（已发现，未处理）

```
Loom/%SystemDrive%   2 个文件   ← 环境变量被当字面量拼进路径
Loom/~               0 个文件   ← HOME 未展开
```

属"垃圾文件 + 潜在路径 bug"，应清理并定位源头（写入前是否做了 `expandvars/expanduser`）。

---

---

## 5. 五份调研结论（2026-11-09 全部完成）

| 编号 | 报告 | 关键结论 |
|---|---|---|
| R01 | `research_beta6_01_render_pass.md` | 不做 RenderGraph → **FramePlan（有序 Pass + 显式目标）**；PassSpec 6 项；迁移序 天空→主pass→阴影→HUD→tonemap→bloom；一期 8.5 人天 / 全量 15.5；顺带 3 个 bug（`ctx.depth_mask` 空操作、VK mip 格式写死、HDR 可行性已验证） |
| R02 | `research_beta6_02_asset_guid.md` | 三套资源基址并存（天空盒=相对场景目录、材质=绝对路径、UI/音频=CWD）；**打包不带 assets → 打包游戏必丢贴图**；guid 无去重/可重指；方案 `Assets/assets.json`（8 人天，最小闭环 4） |
| R03 | `research_beta6_03_animation.md` | 现状=单物体 TRS 关键帧；4 个 bug（末帧丢/时间不落盘/undo 共享 clips/写者次序冲突）；500 物体 12.7ms → SoA 0.133ms（**68x**）；蒙皮延后 beta7（GL 3.3 无 SSBO、无骨骼资产来源）；beta6 建议 26-34 人天 |
| R04 | `research_beta6_04_python_hotspots.md` | `pipe_wait` 真凶=物理装配层（`_dirty_mask_batch` 2.18ms×3 ≈63%），Jolt 仅 0.2ms；`buckets` 残差=逐桶小数组（`buffer.write/vao.render` 几乎不耗时）；**花式索引争用 44x**；AVX2 逐位一致 2.2-2.4x；下沉清单 ≈9.7 人天，预期 −4.6ms/帧 |
| R05 | `research_beta6_05_python_upgrade.md` | **3.13 实测可迁**（14 测试双跑全绿、Nuitka 2.7.1 原样成功、纯 Python −8%~−19%、整帧 −0.2~−0.5ms）；**3.14 仅 pygame 缺 cp314 wheel**（其余全绿，Nuitka 需 ≥4.0）；**free-threading 不可行**（PySide6 无 t wheel、pygame 无 t、Nuitka 无 t 支持）→ 只留门铃 |

---

## 6. 架构级决策（合并 30+ 待裁决问题后的 9 条，**待人类拍板**）

| # | 决策 | 推荐 | 依据 |
|---|---|---|---|
| D1 | GL 地板 | **OpenGL 4.3 core**（原推荐 3.3，2026-11-09 人类裁决 **D1=B 上调**：3.3 属亮机卡级别，现代游戏起步即 DX11 同级）。GLSL/SPIR-V 双编译仍不做（与地板无关：moderngl 5.12 无 SPIR-V 摄取、wgpu 只吃 WGSL） | R01 实测 + 批次 A0 复核：本机 `create_standalone_context(require=430)` 得 4.3，现有着色器 330 在 4.3 core 下照常编译 |
| D2 | 渲染抽象形态 | **FramePlan（有序 Pass + 显式目标）**，不做 RenderGraph；主 pass 默认渲染到 HDR 目标，HUD/UI 在 tonemap 之后 | R01：两端执行序已线性，真实成本是"同一语义两种表达" |
| D3 | 资产根与边界 | 新开**项目级 `Assets/`**；六面图/贴图/材质边界统一上移到**项目根**（覆盖 beta5 的"场景目录内"） | R02：三套基址并存 + 打包丢资产 |
| D4 | 资产迁移 | **一次性迁移脚本 + 一个 beta 周期的旧路径 fallback**（开发期无真实用户，但测试场景多） | R02 §迁移 |
| D5 | 蒙皮渲染 | **beta6 不做 GPU 蒙皮**（进 beta7）；但顶点布局（48→80B）、`bone_base` 实例属性、调色板通道**现在定死** | R03：无骨骼资产来源（D1 上调 4.3 后 SSBO 已可用，该项不再是理由；决策不变） |
| D6 | 动画时间/状态落盘 | `time/playing` **只写预览态不落盘**；动画**只驱动 kinematic**（物理赢，消除写者冲突） | R03：写者次序随开关变化 |
| D7 | 场景版本 | `SCENE_VERSION` **10 → 11** + 新增 `min_engine_version`，旧引擎明确拒绝新场景 | R03 Q6，当前实测 = 10 |
| D8 | Python 版本 | **B：3.13 隔离预研分支**（主线不动），到"可发布"约 4.25 人天；free-threading 只留门铃不做 | R05 实测 |
| D9 | 热点下沉顺序 | P0 插桩闭账 → **P1 `loom_bucket_pack`**（buckets 2.65→≤1.0）→ P2 物理桥 SoA（pipe_wait 3.99→≤2.0）→ P3 AABB AVX2（1.38→≤0.7） | R04 数据；multi-draw 明确不做（净收益 2%） |

### 实现级问题（不占人类注意力，开工时按上述原则直接定）
GL 主 pass 是否永远 HDR、阴影编码是否统一、点光 6 面是否合并、HUD 是否继续接受非逐像素、A/B 探针是否提升为受跟踪测试（**建议提升**，否则证据不可复现）、新模块命名、点光阴影面数、资产指纹字段（sha256+size+mtime）等约 25 项。

---

## 7. 建议的 beta6 范围（受容量约束的切分）

> 总工作量（五份合计）：渲染一期 8.5 + 资产 8 + 动画批次1 10 + 热点 P0/P1 4 ≈ **30.5 人天**；
> 若全做（含动画批次2、热点 P2/P3、Python 预研）≈ 50-56 人天。

| 批次 | 内容 | 人天 | 说明 |
|---|---|---|---|
| **批次 0（前置）** | **工具链与依赖升级**：Nuitka 2.7.1 → 4.3.5（+ MSVC 若确有新版）、依赖链升到当前 stable；完整验证（三件编译 + 121 测试 + 打包 + A/B + bench/体积对照） | 2-3 | **人类裁决：提前到第一项**。理由：升级风险低（性能红利来自上游打磨），且能让后续 Python 3.13 迁移少一层不确定性 |
| **批次 A** | 渲染 S0-S2 + tonemap（含 A/B 探针提升为受跟踪测试） | 8.5 | 骨架乘数，先做 |
| **批次 B** | 资产 `Assets/assets.json` + 贴图/六面图/材质 + **打包带 assets** | 8 | 含 P0 缺陷修复 |
| **批次 C** | 动画批次1（去复刻→SoA→时间基准→序列化v2+undo隔离→写者优先级） | 10 | 不做可视化 |
| **批次 D** | 热点 P0 插桩 + P1 bucket_pack | 4 | 数据驱动 |
| 可选 | 动画批次2（数据模型+编辑器可视化） | 5.5-7 | 视容量 |
| 可选 | 热点 P2/P3 | 4.7 | |
| 独立分支 | Python 3.13 预研 | 4.25 | 不并主线 |

### 顺序（人类已定，2026-11-09 修订）
**批次 0 工具链升级 → A 渲染 → B 资产 → C 动画 → D 热点 → Python 预研（独立分支）**，每批派回**原调研者**实现（工具链批由 R06 调研者接手）。

> 批次 0 的口径：**能在 3.12 上升的先升**（Nuitka/MSVC + 兼容的依赖版本）；个别只有新 Python 才有 wheel 的依赖，留到 Python 3.13 分支再升——不为此提前迁 Python。

---

## 8. 待人类裁决
只需对 §6 的 **D1-D9** 说「同意 / 改哪条」，以及在 §7 里选 **beta6 做几批**（建议 A+B+C+D）。


---

## 9. 人类裁决记录（2026-11-09 第二批）

### 9.1 本节编号约定（2026-11-11 补，回应"引用了不存在的 §9.1"）

第 9 章按「一次裁决 = 一个 9.x 小节」追加，编号只增不改：

| 小节 | 内容 |
|---|---|
| **9.1** | 本约定与章内索引（就是本节） |
| 9.2 | Vulkan 门槛裁决（第四批） |
| 9.3 | VK 不兼容处置（第五批） |
| 9.4 | 批次 0.5 裁决（第六批） |
| 9.5 | 构建档位 |
| 9.6–9.10 | 3.13 物理退化 / 测量纪律 / 第三轮复核 / 集中裁决 / 3.12 vs 3.13 空闲重测 |
| 9.11–9.21 | 批次 A 2A 验收起至最终验收 F-01 |

> 历史正文里若出现「§9.1」而语义指向某次裁决，以本表定位到真实小节（旧文不改写，避免破坏引用链）；
> 新写文档请只引上表里存在的小节号。

| 项 | 裁决 |
|---|---|
| B 组范围 | **A+B+C+D 全做**，顺序 A 渲染 → B 资产 → C 动画 → D 热点 |
| C 组工具链 | **新开发工具直接在主分支实验，尽快替换**（老工具用久了有安全风险）；不搞"发布机才用新版"的折中 |
| D 组 FPS 离群 | 判为浮动；**只要对性能几乎无影响，优先换新工具** |
| R06 报告 | 已登记进 `_README` 索引 ✅ |

### 由此产生的批次 0.5（待裁决 A 组后执行）

按"主分支尽快换新"的口径，下一波升级候选：
1. **PySide6 6.12.0**（Qt 6.12；影响离屏回退路径，需真机白屏验证）
2. **wgpu 0.33.0**（API surface 与 0.32 一致，DrawCancelled 已被现有 except 兜住）
3. **VS2026 + MSVC 14.50 LTS**（需 Nuitka ≥2.8.7，当前 4.3.5 满足）
4. **Python 3.13**（若 A 组 D8 改为"主线直迁"，则并入批次 0.5；否则留独立分支）

每项都要过：三件重编 + 121 测试 + 打包 + `ab_gl_vk` 不劣化 + bench + 启动/体积对照；劣化即回滚单点。


---

### 9.2 Vulkan 门槛裁决（2026-11-09 第四批，人类全部接受）

1. **文档化 Vulkan 地板**：以 wgpu-native 要求的最低版本（当前 **Vulkan 1.1**）为准，与 GL 4.3 并列为引擎最低要求；写明"我们写 WebGPU，由 wgpu-native 翻译成 Vulkan"。
2. **批次 A 内加 VK 门**（与 `require_gl_version` 对称）：`require_vk_backend()` —— 拿不到 adapter / 版本低于地板时打印 `[VK] device / driver / apiVersion` 并提示"可改用 OpenGL（需 4.3）"，不静默黑窗。
3. **wgpu 升级验收项固化**：每次升 wgpu-py/wgpu-native，必须记录"Vulkan 地板是否变化"，写进该批次的验收表（当前保持 wgpu 0.32，等 0.33 稳定再升）。

对应登记：路线登记 **N-13**（已落盘）。


### 9.3 VK 不兼容处置（2026-11-09 第五批，人类裁决）

保持最初设计，不静默回退：

1. **可见失败**：VK 初始化/适配器创建失败时，打印并弹窗给出 `[VK]` device / driver / apiVersion + 「你的 Vulkan 驱动不兼容（需 1.1+），建议升级显卡驱动」。
2. **自动改配置**：把**用户层** `游戏设置.json` 的 `render_api` 写成 `opengl`（不碰只读模板层）。
3. **退回 GL**：同一进程立即按 GL 4.3 路径继续；若 GL 也失败，报出两条原因并退出。
4. **下次启动**直接走 GL，不再无谓地重试 VK 一次（配置已持久化）。
5. 与 N-13 合并实施（原「仅诊断」升级为「诊断 + 持久化 + 回退」）。
6. **人类确认（2026-11-09）：选 A** —— 弹错误框 → 写配置 → **立即用 GL 继续**（不强制退出），下次启动直接 GL。


### 9.4 批次 0.5 裁决（2026-11-09 第六批，人类选 ①）

- **保留 Python 3.13.15 主线**，接受满载物理路径 **−6%~−9%** 的 FPS 代价（其余门禁全过：121 测试、包体积 −0.6%、冷启动 −4.7%、import −16%、ab_gl_vk 逐位相同、TPS 30.04）。
- **两个附加条件**：
  1. 批次 D（物理桥 SoA + `loom_pose_sync`）验收里**必须**包含"满载 FPS ≥ 85"，即把 3.13 的退化补回来；
  2. 开一个 **1 会话的定位任务**：cProfile 对比 3.12/3.13 同一场景，找出 `logic_step`/`pipe_wait` 变慢的具体函数；找到就可低成本修，不找到则并入批次 D。
- 回滚手段保留：`C:\loom_build\pre_py313_freeze.txt` 与三件 `__py312` 备份。


### 9.5 构建档位（2026-11-09 人类裁决）

- **内部开发：编「带控制台」版本**（`--windows-console-mode=force`）——错误、bench 退出码、异常栈都能看见，避免静默失败。
- **发布：编「不带控制台」版本**（`--windows-console-mode=disable`）。
- 两条命令落成工具 `tools/build_engine.py --mode dev|release`，不靠记忆；**发布产物必须来自 release 档**，dev 产物明确标注不可发布。


### 9.6 3.13 物理路径退化：定位结论（R04，2026-11-09）

**结论：不是 specializing interpreter/类型不稳定，而是跨线程 GIL 交接成本 +83% 在我们这种高频交接架构上的复利。**

判据（探针 `tests/_tmp/research_04e_*.py` 可复跑）：
1. **单线程下 3.13 更快**（m.position 223→131µs、m.scale 334→134、id 107→36）→ 早前"访问器慢 4-7x"是争用污染的墙钟，已作废。
2. **两线程 Event 乒乓 51.25 → 93.56 µs（+83%）**。
3. `LOOM_LOGIC_SYNC=1`（去掉逻辑线程）后缺口从 **−15% 收窄到 −3.2%**（3.12 85.3 / 3.13 82.6）。
4. 全进程 CPU/帧 12.66→14.45ms（1.08→1.17 核；物理线程 +16%、池线程 +48% CPU）→ **不是干等，是多烧 CPU**。
5. 无效项已排除：switchinterval 1/2/5/10ms 无趋势；逻辑线程轮询睡眠 1→4ms 落在噪声内。

函数级 top（µs/次）：`update_animations` +145%、`_transform_snapshot` +39.5%、`_refresh_free` +38%、`compute_world_matrices` +36.3%、`_run_scripts` +19%、`_dispatch_fixed_update` +19%、`br.pre_step` +11.7%、`br._dirty_mask_batch` +10.1%、`pipe.wait_pending` +7.9%、`_prepare_bucket_frame` +4.5%。
无退化对照：`_aabbs_batched` +1.4%、`_logic_prep` +0.1%、Jolt step +0.4%、`collide_pairs` +3.5%。

**处置（人类已选①，本结论不改裁决）**：
- **不为 3.13 单独打补丁**；根治 = 批次 D 的物理桥/逻辑帧装配层 SoA 化（`loom_pose_sync`），一次改动两边收益。
- `LOOM_LOGIC_SYNC=1` 只作**测量口径**（73.4→82.6 FPS），**不改默认**（历史记录异步在其它场景更快）。
- 批次 D 验收门槛追加：**满载 FPS ≥ 85**，且需给出"跨线程交接次数"的前后对比（这是本次退化的直接机制）。


### 9.7 性能测量纪律（2026-11-09，R04 自查发现，必须遵守）

R04 复核时发现两件事，直接推翻了它自己的一条证据，也暴露了我们的测量方法问题：

1. **`--bench` 不建逻辑线程**：`engine.py:1478` 起逻辑线程要求 `_external_ctx=True`，而 PlayerApp/--bench 走 GLFW 自持上下文 ⇒ bench 下 `LOOM_LOGIC_SYNC` 只是改了个没人读的布尔量（线程表实测无 `loom-logic`）。
   → **凡是"逻辑线程/异步"相关的结论，必须用编辑器路径（`_external_ctx=True`）测**，不能用 `--bench`。
2. **并行会话导致同配置重跑 2.5x 抖动**：同一命令同一树，在一次测量里 `--bench` 31.4 FPS、加成 81.8 FPS；他侧与我的 74.6/44.4 又相反。
   → **FPS 对比必须在机器空闲时做**；当前多个子代理并行编译/跑测试时的读数**不可用于结论**。

**强制测量协议（写进本文件，后续所有性能批次遵守）**：
- 机器空闲（无并行编译/测试/子代理），`Get-Process` 确认无高占用；
- **交替 A/B 至少 5 轮**（不是先跑完 A 再跑 B），取中位数与 p99；
- 同时记录：线程表（是否真有 `loom-logic`）、`logic_step`/`pipe_wait` 分段、CPU/帧；
- 结论必须写"测量条件"（空闲/负载、n、是否交替）；
- 单次跑出的数字只作线索，不作结论。

**待办**：3.12 vs 3.13 的 FPS 差异（原 −6%~−9%）需在**空闲条件下重测**；裁决①不变（保留 3.13），但批次 D 的 "FPS ≥ 85" 门槛应以重测后的基线为准。


### 9.8 第三轮复核（干净子代理审计已做工作）发现

**A-02 · `ab_gl_vk` 受跟踪测试（4 个 P1，已派修）**
- P1-1 闸门只比 GL 与 VK 两端、不存参考图 → **共享回归不可见**（fov 两端同改 +15%，画面真实变化 MAE=2.3e-2 是阈值 117 倍，闸门仍 PASS）
- P1-2 基线缺失/损坏/场景改名 → `ok_drift` 恒 True（PASS）
- P1-3 VK 异常一律 SKIP + rc=0，无法区分「没装 Vulkan」与「VK 后端坏了」，且与 GL 侧不对称
- P1-4 `--update-baseline` 无条件 rc=0，GL 全挂时仍写「0 场景」基线；部分跑会静默删锚点
- 修复口径：**基线存参考图（三向比对）**、缺基线/新场景 FAIL、VK 失败默认 FAIL（显式 `LOOM_AB_ALLOW_NO_VK=1` 才允许 SKIP）、update 有 FAIL 不写、NCC 改 float64、基线加来源哈希、UI 纳入覆盖
- **R06 报告的 `MAE 0.0021/0.2353/0.9741` 判定为旧口径/其它制品读数，作废**；以受跟踪测试 8.2e-5/0.1255 为准

**A-03 · 工具链/构建/打包（2 个 P1 + 5 个 P2）**
- P-01 源码包启动时用系统 3.13 静默顶掉包内 `python/`（`hub_config.py:696-706`，note 为空）
- P-02 源码打包器仍嵌 Python **3.12.10**（`package_engine.py:138-149/204`），而 `解释器.json` 写 3.13.15、README 写 3.12 → 干净 3.13 发布机直接 `SystemExit`
- P-03 三条断言只查存在性/计数（0 字节 qwindows.dll 也 PASS）
- P-04 `PYGAME_MIN_DLLS=15` 与今日产物恰好相等（零余量）
- P-06 编译包 `Loom.bat` 指向不存在的 `python\pythonw.exe + Loom.py`（已发货 beta5/beta6.zip 均有此问题）
- P-07 指南 §7.5 命令缺 `--output-filename=Loom.exe`，照抄产出 `build_entry.exe` 被打包器拒收
- 待人类裁决：Q1 源码包内嵌 Python 版本（A 跟 3.13.15 / B 回 3.12 / C 不内嵌）、Q2 包内 Python 是否允许被系统顶替（A 永不允许 / B 允许但提示 / C 静默）、Q3 `Loom.bat`+README（A 修 bat / B 修 bat+README / C 删除）
- 主审建议：Q1=A、Q2=B、Q3=B


### 9.9 集中裁决（2026-11-10，人类一次性回答）

| 编号 | 问题 | 裁决 |
|---|---|---|
| Q1 | 源码包内嵌 Python 版本 | **A：跟随 3.13.15**（打包器解析 3.13 embeddable 并回写元数据） |
| Q2 | 包内 Python 与系统 Python 谁权威 | **A：包内权威**（包内 python/ 存在时不允许被系统解释器顶替） |
| Q3 | embed 版本不一致 | **A：升格为发布硬门**（不一致拒绝出包） |
| Q4 | Loom.bat + README | **B：bat 改双模式启动器 + README 修正** |
| Q5 | 冻结版兜底抢焦点 | **B：改用 sys.version_info，不拉子进程** |
| Q6 | PacMan2D 地板铺满 | **B：不改示例场景**（属场景内容，文档注明） |
| Q7 | 显式 --backend vulkan 失败是否改配置 | **A：不改写**（尊重显式选择），弹窗需给出「如何永久改用 OpenGL」的出口 |
| Q8 | 回退写哪层配置 | 确认：只写用户层 游戏设置.json |
| Q9 | 空闲重测 3.12 vs 3.13 | **做**（编辑器播放态 + EAI engine_metrics，n=5 交替，非 --bench） |


### 9.10 3.12 vs 3.13 空闲重测（2026-11-10，Q9）

**条件**：机器空闲；编辑器播放态（`_external_ctx=True`，真有 `loom-logic` 线程）；EAI `engine_metrics`；3.12/3.13 **交替 n=5**；每轮先确认 `models=501`（场景真的加载）再采样。

| 轮次 | 3.12 (fps 三次 / 中位) | 3.13 (fps 三次 / 中位) |
|---|---|---|
| 1 | 90,86,91 → 90 | 76,74,73 → 74 |
| 2 | 87,86,90 → 87 | 96,97,94 → 96 |
| 3 | 89,77,93 → 89 | 81,78,78 → 78 |
| 4 | 97,93,94 → 94 | 86,65,82 → 82 |
| 5 | 97,87,97 → 97 | 80,71,76 → 76 |
| **中位** | **90** | **78** |

**结论**：3.13 在**真实异步逻辑线程路径**下约 **−13%**（90 → 78），比早期"−6~−9%"更大；方差大（3.13 单轮最高 96）。与 R04 的机制判断一致（跨线程 GIL 交接 +83% 在高频交接架构上复利）。
**处置不变**：保留 3.13（裁决①），**批次 D 的物理桥/装配层改造必须把满载 FPS 补回 ≥85**（≈ 3.12 基线水平），并给出"跨线程交接次数"前后对比。

**测量纪律补充（本轮踩坑）**：PowerShell 调外部程序传**含空格的路径**必须拼成**带引号的单个字符串**；用数组形式会被截断成 `D:\my-project`，导致"看起来在跑、实际加载空场景"（本轮首测因此作废，见 §9.7）。

### 9.11 批次 A 阶段 2A 验收（2026-11-10）

**产物**：`Loom/loom_pass.py`（PassSpec/FramePlan 纯数据 + 按参数缓存）、`Loom/loom_pass_gl.py`（GLTargetPool + GLFrameExecutor）、`Loom/tests/test_frame_plan.py`（**现 55 项**，后续 2B1/2B2/崩溃回归持续追加）；`loom_render.py` / `editor.py` 两条路径统一走 `frame_plan()` + 执行器，编辑器清屏字面量删除统一 `CLEAR_COLOR_RGBA`。

**验收（硬门）**：
- 22 场景 **GL/参考 MAE 恒 0.000000**（逐像素与迁移前相同）；VK/参考、GL/VK 逐值等于旧基线；22/22 PASS、0 SKIP
  > **诚实口径（2026-11-11 补）**：这里的「参考图」是 **GL 自己渲染的基线图**，MAE=0 只证明「迁移后 GL 输出没漂移」，
  > **不证明 GL 与设计意图/Unity 一致**。GL 与设计的对齐要靠人工观感与设计文档比对，不能拿这条断言当证据。
  （**现口径**：2B2 起场景集含 `ab_bloom` 共 **23 场景**，闸门数 24 项含 UI 子项）
- 合计项数随各文件增长（2A 时口径 313，现以当次跑测为准）；本次分组（frame_plan **实测 55** / render_api 60 / ui 13 / vk_ui_input 32 / skybox_parity 23 / ab_gl_vk 23 / fallback_policy 44 / user_config 60 / wheel_backend 31；测试文件总数 **133**）
- 抽象层单帧开销 **6.7 us**（plan 取缓存 0.3 us），约 0.8% 帧时
- 编辑器 `--auto-close 3` 正常；主审复跑 frame_plan / ab_gl_vk / render_api / skybox_parity 全绿

**共享 vs 未共享（诚实口径）**：
- 已共享：FramePlan 描述（目标语义名、pass 顺序、depth/raster 声明、绘制源、参数块与语义槽清单）+ GL 执行器
- 未共享：WGSL/GLSL 双份着色器、天空时机与几何、VK 的 `f32[352]` 参数块、阴影目标编码（S3 处理）、VK submit 粒度
- `DepthState.write` 在 GL 仍无法真正执行（moderngl 无 depth_mask）→ 标注 advisory

**下一步**：2B1（阴影 + HUD/UI 迁入，仍要求 GL/参考 MAE=0 —— 同上：MAE=0 只等于「没漂移」）→ 2B2（tonemap + bloom，画面会**故意变化**，闸门改为「人工确认新基线 + 双后端一致」）。

### 9.12 Q-REQ-1 裁决（2026-11-10）

**A：源码包 requirements.txt 补 `culverin>=0.14.0` / `game-audio>=2.1.0`**（缺了源码版物理/音频会静默降级）；同时把 `py -3.12` 安装提示改为 `py -3.13`。

### 9.13 阶段 2B2 与 Q-VIS-1（2026-11-10）

**2B2 已实现并提交**：GL/VK 同时实现 tonemap + bloom（`loom_post.py` / `loom_post_gl.py` / VK `_record_post`），`LOOM_POST=0` 可回退；顺带修掉 VK mip 管线写死 `rgba8unorm` 的坑、以及全屏 quad 写 LDR 深度导致下帧黑屏的坑。
性能：后处理约 **+4.2% 帧时间**；硬门：开后新基线 22/22 PASS，`LOOM_POST=0` 时旧基线全绿。

**问题**：平均亮度 0.5735 -> 0.4879（−15%），观感变平；且 22 个测试场景**没有高亮物体**，bloom 不可验证。
**人类裁决 Q-VIS-1 = B（调参）**：加曝光补偿（默认标定到中位亮度≈旧基线 ±3%）、重算 bloom 阈值/强度、**新增 `ab_bloom.json` 亮部场景并用晕圈量化指标证明 bloom 生效**。硬门不变。

### 9.14 Q-VIS-1 裁决（2026-11-10）

**A：接受 2B2 调参后的观感与参数**（exposure=1.70、bloom threshold=1.15/knee=0.35/strength=0.70；后处理约 +8% 帧时）。

**度量口径（2026-11-11 更正，goal_01 复核后统一）**

- **平均亮度**：以 `tests/ab_scenes_ref{,_next}` 下 **23 张场景参考图（不含 `__ui`）** 的均值计：
  **0.5686 → 0.5665（−0.4%）**（此前写的 0.5735 是 24 张含 UI 参考的旧口径，已作废）。
  单图：`ab_scene` 0.6158→0.6040（−1.9%）、`ab_sky` 0.6368→0.6303（−1.0%）、
  **`ab_c_dir_shadow` 0.6085→0.6001（−1.4%）** —— goal_01 引的正是这张单图，故与聚合值不同。
- **bloom 晕圈**：`ab_bloom`，取最亮像素为中心，比较 `LOOM_BLOOM_STRENGTH=0` 与 `0.7` 两帧在**同一圆环**内的平均亮度，
  相对增量 = Δ/关bloom值。**该指标随半径单调变化**：

  | 环半径(px) | 6–14 | 8–18 | **10–22** | 12–28 | 20–40 |
  |---|---|---|---|---|---|
  | 相对增量 | +33.4% | +26.8% | **+22.1%** | +17.8% | +10.4% |

  受跟踪测试 `test_post_bloom.py` 固定用 **10–22**、**圆心取关 bloom 帧的最亮像素**（断言 ≥+5%），实测 **+22.1%**。
  旧记录的 +42.5% 是「每张图各自取最亮像素」的旧口径（bloom 会把亮心挪动，导致同一半径量出不同值），已作废；
  goal_01 的 **+24.5%** 落在 8–18(+26.8%) 与 10–22(+22.1%) 之间，属**环半径口径差异**，不是矛盾。
  另：`ab_bloom` 全图均值 0.1647→0.1971（+19.7%，bloom 把亮部能量摊到周围）。

**结论：批次 A（渲染 FramePlan + tonemap + bloom）全部完成**。

### 9.14c 三向门的**自证边界**（必须写实话，2026-11-11）

`ab_gl_vk` 的参考图是**用 GL 后端自己渲染**出来的，因此：

- 「GL/参考 MAE 恒 0.000000」是**构造上必然**，它只证明「GL 没漂移」，**不证明 GL 画对了**；
- 三向门（GL/参考、VK/参考、GL/VK）的真实能力是：**回归漂移检测** + **双后端一致性**；
- 「GL 正确性」只能靠**独立证据**：曝光标定（新图均值对齐旧基线 ±3%）、bloom 晕圈量化、
  人眼裁决（Q-VIS-1），以及未来接入**外部参考渲染器**（如离线路径追踪）才能形成真正的外部金标准。
  在此之前，文档不得把 MAE=0 表述为「GL 与设计一致」。

### 9.14b ab 夹具密闭化（2026-11-11）

**问题**：`ab_env.json` 的 6 面 env 贴图（以及 `ab_nrm`/`ab_tex`/`ab_ui_scene` 的贴图）指向
`tests/_tmp/*.png` 的**绝对路径**，这些图从未提交 —— 清理 `_tmp` 后夹具不可复现。

**修法**：① 新增 `tests/ab_scenes/assets/`（`make_assets.py` 确定性生成 env_0..5 纯色 4×4、
normalmap 8×8、checker 16×16、ui_tex_rgba 8×8）；② 场景内路径改**相对场景目录**
（`assets/env/env_N.png`），sceneio/scene_driver 对旧式相对 path/paths 按场景目录解析
（无项目资产库时用 `_CUR_BASE_DIR`）；③ 参考图按新夹具**全量重生成**（新旧两套基线各 23 场景，
旧口径基线同时纳入 `ab_bloom` 的 POST=0 参考）；④ 删除整个 `tests/_tmp` 后
`test_ab_gl_vk` 仍全绿（实测）。

### 9.15 批次 B1 资产管线验收（2026-11-10）

**产物**：`Loom/loom_assets.py`（Assets/assets.json：schema/guid/指纹 sha256+size+mtime/越界拒绝/去重/冲突；AssetContext 三层解析；热路径只 stat）、`tools/migrate_scene_assets_v11.py`（一次性路径→guid，幂等，支持 --dry-run/--report/--no-create）、`test_asset_guid.py`（46 项）。

**关键落地**：
- `SCENE_VERSION` 10 → **11**；材料 albedo/normal/env 与 skybox/相机 skybox 托管时只写 guid，旧 path/paths 兼容读并告警（一个 beta 周期 fallback）；无项目索引时行为与 beta5 一致
- **打包带资产**：`build_game.copy_project_assets` 拷 `Assets/`；runtime/run_player/vk_player/game_player 传 `assets_base`，包内场景不再按 CWD 解析
- `agent_commands` 新增 asset_import/get/list/scene_assets_check；`set_texture/set_env` 项目内自动登记 guid

**验收**：test_asset_guid 46 项 ALL PASS；test_sceneio / test_skybox_scene（beta5 语义未破）/ test_eai_real（102 命令）全绿；全量 **133 个 test_*.py 文件**（数字随批次增长；本轮实测 13 套核心套件全绿）；老 v8 场景仍可加载（bench FPS 74.0）。

**越界说明**：为双后端一致与包内 base_dir，实际改动含 `scene_driver/run_player/vk_player/game_player`（超出派单清单，主审复核后接受）。

### 9.16 性能预期裁决（2026-11-10）

人类裁决：3.13 带来的性能下降可以接受。后续继续做优化、并等待更高版本 Python 与其依赖生态成熟后再迁移。

含义：
- 批次 D 的 FPS >= 85 不再是硬门槛：仍按数据做优化（bucket_pack、插桩闭账），但没补回 13% 不构成阻塞；测量照做、数字如实记录。
- Python 版本路线改为观察式：不追 3.14/3.15，等 PySide6（abi3 vs free-threading）、Nuitka、wgpu/moderngl 生态成熟后再评估。
- 3.12 回滚点继续保留（pre_py313_freeze.txt + 三件 __py312 备份），但不作为默认路径。

### 9.17 批次 D1 主审复测（2026-11-10，空闲 + 交替 n=5，models=501 每轮确认）

| 轮次 | C 打包（默认） | Python 打包（LOOM_BUCKET_PACK=0） |
|---|---|---|
| 1 | 94 | 80 |
| 2 | 90 | 53（离群） |
| 3 | 95 | 83 |
| 4 | 101 | 81 |
| 5 | 100 | 80 |
| **中位** | **95** | **80** |

**结论**：C 打包比 Python 打包 **+19%**；且 **95 FPS 已超过 3.12 基线（90）**——3.13 的 −13% 退化被彻底补回并反超。
`TPS` 稳定 30.x（未受优化影响）。

→ 批次 D 的 P2（物理桥 SoA）/ P3（AABB AVX2）**从「必要」降级为「可选」**：当前已超基线，继续做属锦上添花。

### 9.18 阶段裁决（2026-11-10）

| 项 | 裁决 |
|---|---|
| Q-VER-1 | **A：播放器遇到更高版本场景 → 弹窗 + 明确原因 + 优雅退出**（不再只 traceback） |
| 批次 D | **继续**（P2 物理桥 SoA / P3 AABB AVX2 都做） |
| beta6 收尾 | **暂不收尾**；但**阶段性审核继续**（每完成一个批次跑一轮干净子代理复核），避免错误累积影响后续开发 |

### 9.19 并发跑测试会互相踩（2026-11-10，R03 发现）

现象：两个 `run_all.py` 同时跑时出现 2 个假失败——`test_audio`（音频设备争用、kind=None）与 `test_gameplay_bugs`（固定 `%TEMP%` 文件名被对方删除）；单独复跑均 ALL PASS。

纪律：**全量回归同一时间只允许一个实例**；多子代理并行时，测试要么串行、要么用独立 `LOOM_USER_ROOT`/临时目录隔离。

### 9.20 安装版最终复测（2026-11-10，R5 整改后，空闲 n=5）

| 轮次 | FPS 三次 | 中位 |
|---|---|---|
| 1 | 87,89,94 | 89 |
| 2 | 86,88,93 | 88 |
| 3 | 88,90,94 | 90 |
| 4 | 91,89,93 | 91 |
| 5 | 92,94,85 | 92 |
| **中位** | — | **90** |

对照：3.12 源码 90 / 3.13 源码（D1 后）95 / 编译版（本轮）90。

结论：**编译版回到 3.12 基线水平**；源码版仍高 5 左右（Nuitka vs CPython 差异 + 测量口径）。D2/D3 的 −1.6ms 理论收益没有完全落到整帧（符合预期：部分被渲染线程空转吸收）。

### 9.21 渲染后端抽象目标达成度（2026-11-10，最终验收 F-01）

**结论：beta6 交付的是「GL 单后端内部的 pass 描述层」，不是「渲染后端抽象化」。**

| 指标 | 数值 |
|---|---|
| VK 对 loom_pass 的引用 | **0 行**（共 2309 行，无一行由共享描述驱动） |
| 目标完成度（14 个「同一语义面」口径） | **14.3%**（分子 2.0：清屏色 1 + 目标声明 0.5 + 后处理参数 0.5） |
| 辅口径（PassSpec 6 项 × 2 后端） | 29.2%（3.5/12） |
| 后处理 | GL `loom_post_gl.py` 204 行 vs VK 内嵌 202 行，**4/4 阶段两份独立实现**，0 行共享着色器/管线 |
| 新增 1237 行中的重复 | **406 行（32.8%）** |
| Python 总行数 | GL 1090→1734（+59%）、VK 2077→2309（+11%）、共享 0→361；**合计 3167→4404（+39%）** |
| 重复语义面 | **13 → 14**（只闭环 1 项：清屏色）→ **分裂未缩小** |

**共享 6 项**：pass 顺序与 9 个 id、目标语义名、`CLEAR_COLOR_RGBA` 单源、post 参数/toggle、depth/raster 声明、绘制源名。
**未共享 14 项**：阴影编码、阴影提交粒度、天空时机/几何/参数、实例布局、HUD、着色器、绑定槽、参数块、mip、后处理、目标分配、submit 粒度。

**引入问题 8 项（无 P0/P1）**：N-01 `LOOM_POST_STAGE` 只对 GL 生效；N-02 设计里要求删的假 `depth_mask` 仍在（每帧 AttributeError 被吞）；N-03 up 阶段两端都写了但都没接线（死代码）；N-04 PassSpec 4 字段零消费者且 `shadow.point` 声明为 cube 而 VK 用 2d-array（描述只对 GL 成立）；N-05 文档自述与实际不符（四段链、27 vs 49 项测试）；N-06~08 天空状态双写/两套 flag/`_PLAN_CACHE` 无上限。

→ 处置：Q-02 接受并登记「未达成」；Q-03 授权行为中性清理；Q-01 VK 迁入 FramePlan 列为 **beta7 硬目标**（见路线登记）。

### 9.22 版本定位裁决（2026-11-10，人类）

> 人类原话：原定目标压根没做到，那就仍然是 beta6 的中间版本；没打磨到达成全部确定要完成的目标之前，beta6 只能是中间版本继续打磨。

含义：
- **beta6 不进入收尾/发布流程**；F-01 判定的「渲染后端抽象化未达成（14.3%）」属于**必须在 beta6 内补齐的目标**，不是延后项。
- 原登记为 beta7 的 **B7-13（VK 迁入 FramePlan）上调为 beta6 必做**：目标是把「重复语义面」从 14 降到 ≤8、VK 由共享描述驱动。
- 同时完成本轮审计出的清理项（文档同步、死代码、env 治理、测试入口证据、源码子串断言）。
- 只有上述目标全部达成，beta6 才谈收尾；版本号保持 `0.1.0.beta6` 不动。

### 9.23 骨架补全验收（2026-11-10，最终验收 F-02）

**原定目标：8 达成 / 1 部分 / 1 未达成**
- 达成：B1 guid+越界拒绝（152 PASS）、打包带资产（3 处 assets_base 全接）、旧路径 fallback、C1 动画内核唯一化（126 PASS）、undo 值隔离、D7 版本闸门（5 入口）、LOOM_NO_PHYSICS 真开关、LOOM_POST 双端
- 部分：G9 崩溃可见性——`enable_if_requested` 只在 `Loom.py`/`build_entry.py`，**打包游戏入口 0 处**
- 未达成：G10「诊断开关定稿前清理」——`LOOM_POST_STAGE` 仍在，6 个新 env 在文档 0 登记

**P2（本版应处理）**
1) **资产索引校验 1.0ms/条**（`is_inside` 的 2×realpath）→ 10000 条冷加载 **8660ms**、`inspect_index` 8588ms；beta5 基线 0ms → 大项目会卡死
2) 用户层 delta 的 import 覆盖**从未生效**（实测 mipmaps/wrap 无视 delta），`user_index_path` 全仓 0 写者 → 文档说的三层实际两层
3) `save_index('')`=CWD；编辑器未保存场景也返回 CWD → 探针在仓库根写了 `Assets/assets.json`（已删）
4) `post_stage` 死条件：`LOOM_POST_STAGE=0` → stage1（**关不掉后处理**）
5) `_env_float` 接受 nan/inf → 直入 `write_buffer` → **整屏 NaN**

**P3**：`record_asset_error` O(N²)（5000 条 313ms）；`LOOM_FAULTHANDLER` 非法值当路径建文件且游戏档不生效；`_anim_fallback_models` 停播后仍强引用已删模型；`parse_version('0.1.0-beta6')=None` → D7 闸门 **fail-open**；`_skybox_ref` 仅 engine/editor；VK 不认 `LOOM_POST_STAGE`。

### 9.24 倒查推翻「VK 已由 FramePlan 驱动 / 语义面 14→6」（2026-11-10，V-01）

**V-01 用「改 plan、看输出是否跟着变」的反例矩阵验证，结论相反：**

| 反例（ab_sky，MAE vs 同后端基线） | GL | VK |
|---|---|---|
| 删 `main` pass | 0.63680 | **0.00000** |
| `main`↔`sky` 换序 | 0.26022 | **0.00000** |
| `plan.clear` 改红 | 0.22379 | **0.00000** |
| `main.draws=skybox` | 0.06324 | **0.00000** |
| `main load=load` | 0.63026 | **0.00000** |
| `depth.test=False` | 0.06089 | **0.00000** |

**结论**：VK 只是**按 id 读存在性/取目标名**（11 处引用，**无一处遍历 `plan.passes` 执行**），plan 被改后 VK 输出完全不变。因此：
- 「VK 由共享描述驱动」**不成立**（仅存在性/后处理参数/目标名部分生效）；
- 「语义面 14 → 6」**不成立**：14 项未共享一项未消除，所谓 6 是**重新分桶并丢弃 3 项**（U1 目标分配 / U12 mip / U13 后处理管线）后的口径变化；真实共享仅 3 类（后处理参数与开关、后处理段集合与顺序、pass 存在性）。

**成立的部分**：后处理参数确实两端共享（改 threshold 两端 ΔMAE 均 0.00165）；假 `depth_mask` 已删；`LOOM_POST_STAGE=0` 两端都真关（与 `LOOM_POST=0` 逐像素同哈希）。

**新增 P2**：`plan.clear`/`load` 对 VK 无效；`sky.raster.cull` 两端相反（GL 被 `loom_render.py:188-189` 内部重设覆盖）；`TargetDecl.format/scale` 只部分生效；`LOOM_POST_STAGE=1≡2`（bright 输出不被 tonemap 消费，档 2 死档）。

→ 处置：**要求 R01 真正实现「遍历 plan.passes 执行」**，并以「改 plan 必须改变 VK 输出」为验收硬门；在此之前不得再宣称抽象化达成。

### 9.25 倒查总账（2026-11-10，V-01/02/03 三份）

| 宣称 | 倒查结论 |
|---|---|
| VK 由 FramePlan 驱动 | ❌ **不实**：改 plan（删/换序/改 clear/改 draws）VK 输出全不变（MAE 0.00000），VK 只按 id 读存在性 |
| 语义面 14 → 6 | ❌ **不实**：14 项一项未消除，所谓 6 是重新分桶丢弃 3 项后的口径变化；真实共享仅 3 类 |
| 后处理参数两端共享 | ✅ 成立（改 threshold 两端 ΔMAE 均 0.00165） |
| 假 depth_mask 已删 | ✅ 成立 |
| `LOOM_POST_STAGE=0` 两端真关 | ✅ 成立（与 `LOOM_POST=0` 逐像素同哈希） |
| 资产索引 8s → 实测 33–77ms（三种形态） | ✅ 级数达成；数值按三种形态如实记录（旧 54.6ms 单值已废弃） |
| `record_asset_error` 29.5ms | ⚠️ 实测 7.1-8.3ms（宣称值偏保守 3.6-4x）；门禁 500ms 余量 62x，抓不住回退 |
| 动画 1.42-1.69ms | ✅ 可复现（1.473ms 中位），≤1.0 未达成已写清；`research_beta6_03:516` 与「126 PASS」均已修正 |
| 12 能力名文档可查 | ✅ 60/60 格非空；但只有 README 与附录 F 给了用法，另三份仅提及 |
| EAI 命令数 103 | ✅ 已修正（`asset_user_override` 后为 103；五份文档与附录 F 自检命令统一 103） |
| env 附录全覆盖 | ✅ 已修正：代码 runtime env 49 个，指南 49/49 全覆盖；`LOOM_AB_*` 标注「仅测试」 |
| 打包断言真实生效 | ✅ 20/20 负例 PASS + 端到端 exit 1 |
| 交付包与代码一致 | ❌ **不实**：`tools/dist` 两包早于最后 4 个提交（source 20:22 / compiled 14:40 vs HEAD 20:42），包内缺 103 命令与 user_delta |

**新增 P1**：D 批三个性能测试**全是 helper-only、0 处生产入口证据**（`test_bucket_pack`/`test_aabb_simd`/`test_physics_pose_soa`），且设计要求的 `LOOM_NO_SIMD=1` 全仓 0 实现。

→ 处置：R01 真正实现 plan 遍历；R04 补入口级对拍与 `LOOM_NO_SIMD`；05 修文档数字与 env；R06 在所有代码定稿后重打两包。

### 9.26 门序首次全绿（2026-11-11，包 = 代码有机器证据）

流程：干净树（HEAD d1674fa，dirty=False）→ 重编三件 → 冒烟盖章（编辑器/运行时/构建器）→ 打两包 → 对拍。

| 判据 | 结果 |
|---|---|
| source 包与 HEAD 逐文件 sha256（CRLF 归一） | **0 不一致 / 93 文件** |
| compiled `build_info.git_head` | **= HEAD（相等，非祖先）** |
| `git_dirty` | **false** |
| `smoke_passed_at` | 23:50:54 **> built_at 23:35:20**（门序真实执行） |
| meta（顶层/嵌套/--version） | 0.1.0.beta6 一致 |
| 装机冒烟 | **5/5 PASS，6.2s**（models=126, fps=209, tps=30.18） |

产物：`Loom-0.1.0.beta6-compiled.zip` **132.09 MB**、`Loom-0.1.0.beta6-source.zip` **348.5 MB**。

**门序拦截实录**：首次打编译包被拒——「构建器产物档位不合格: build_info 缺 smoke_passed_at」，补章后通过。说明「编译→冒烟→打包」不是形式。

### 9.27 goal_01 收口：VK 真遍历 + 装饰字段清理 + 地板闸（2026-11-11）

**A1 装饰性字段（逐项决策）**

| 字段/类型 | 消费者 | 决策 |
|---|---|---|
| `PassSpec.bindings` / `BindingSpec` | 0（绑定号仍是两端各自实现） | **删除** |
| `PassSpec.params` / `ParamField` | 0（参数块布局不共享） | **删除** |
| `PassSpec.submit` | 0（两端都按帧单次提交） | **删除** |
| `VertexLayout` / `ShaderSet` | 代码中**从未实现**（仅 `research_beta6_01` 设计稿） | 保持设计稿，代码不引入；文档已标注「未实现」 |

**A2 `TargetDecl.scale` 两端生效**：GL 后处理目标尺寸改从描述取（执行器写 `engine._post_sizes`，
`loom_post_gl.ensure` 按 `TargetDecl.scale` 建 FBO）。探针（`ab_bloom`，把 `bloom.half.scale` 改 0.4）：
**GL 0.000375 / VK 0.000375**（改前 GL 恒 0.000000）。

**语义面重数（分母 14，逐项判定）**：完全共享 **8**（pass 顺序、目标语义名+格式+尺寸、load/clear、
深度声明、光栅声明、绘制源名、后处理阶段/顺序、后处理参数）；部分共享 **1**（天空：时机/深度语义共享，
quad vs triangle 几何实现不同）；不共享 **4**（阴影目标编码、参数块布局、实例桶/提交粒度、UI 光栅化）；
合理差异 **1**（GLSL vs WGSL，单列剔除）。→ **未共享 ≈4.5 ≤ 8**（此前 V-01 的「真实共享仅 3 类」
是针对「按 id 读存在性」的旧实现；本轮 `for spec in plan.passes` 真遍历后由反例矩阵取证）。

**B VK 地板闸三缺口**：① `require_vulkan_api` 增加 **adapter apiVersion** 闸（loader 1.1 + adapter 1.0 拒绝，
文案同时给两者版本）；② `vk_player` 校验 `adapter_backend`，非 `vulkan` 直接 `VkBackendInitError`；
③ 无 loader 分支 `%s` 已格式化。断言 K1–K7 全 PASS（`test_backend_fallback_policy` 44→51 项）。

**C/D**：度量口径更正见 §9.14（晕圈 10–22px 固定圆心 = +22.1%；平均亮度 23 张 = 0.5686→0.5665，
单图 `ab_c_dir_shadow` = 0.6085→0.6001）；三向门的自证边界见 §9.14c（参考图由 GL 自己渲染，
GL/参考=0 只证明「没漂移」，不证明「画对了」）。


### 9.28 F2-02 复核：语义面**未达成**（2026-11-11）

**结论（按原 14 分母逐项判）：官方记录采用复核口径 —— 完全共享 1 + 部分 3×0.5 + 合理差异 2 +
不共享 8 = **11.5**；剔除合理差异 2 项后仍 **9.5 > 目标 8 → 未达成**。
（下表是本轮逐项判定，部分项我判得比复核更细，但**折算分数以复核的 11.5 / 9.5 为准**。）
§9.27 的「共享 8」是把共享项拆细/并桶的口径变化，按 §9.24 判据不成立，已作废。
**在人类裁决新定义前，一律按「未达成」记录。**

| # | 语义面 | 判定 | 共享了什么 / 为什么不能共享 |
|---|---|---|---|
| 1 | pass 顺序与存在性 | **完全共享** | VK `for spec in plan.passes` 真遍历；反例（删 main/换序）两端 MAE 一致 |
| 2 | 目标语义名 | 部分 | 名字共享；「谁分配/谁持有目标」仍两端各写（GL FBO / VK texture） |
| 3 | 目标格式/尺寸 | 部分 | 本轮已双向接线（format/scale 反例两端同值），但分配实现仍两份 |
| 4 | load/clear | 不共享 | GL 屏幕目标走 `_clear_main_fbo` 特例，VK 走 `clear_value`；语义不同源 |
| 5 | depth 声明 | 部分 | test/write/func 已接线（反例两端 0.06089）；GL 用 depth_func、VK 用烘焙管线比较 |
| 6 | raster 声明 | 部分 | cull/front_face 已接线（sky.cull 两端 0.24656）；GL 即时状态 vs VK 烘焙 |
| 7 | 绘制源名 | 不共享 | 名字共享，但每个 source 的实现各一份（buckets/skybox/world_canvas/…） |
| 8 | 阴影 pass 存在性 | 部分 | plan 门控共享；阴影编码与提交仍两端各自 |
| 9 | 阴影目标编码 | **合理差异** | GL depth 纹理 vs VK r32float+手工比较（API/硬件语义不同） |
| 10 | 天空时机/几何 | 不共享 | 时机由 plan 定，几何（quad vs triangle）与参数注入实现不同 |
| 11 | 着色器语言 | **合理差异** | GLSL vs WGSL（两套语言，镜像不可避免） |
| 12 | 参数块布局 | 不共享 | GL 具名 uniform / VK f32[352] 打包 |
| 13 | 实例桶与提交粒度 | 不共享 | GL 桶 VBO / VK 160B 重排；submit 粒度不同 |
| 14 | UI 光栅化 | 不共享 | `loom_ui` 元素树 vs `vk_ui` 三角带 |

**本轮修掉的两个新反例（F2-02 #3/#4）**

- `TargetDecl.format` 原为装饰：现 GL（`loom_post_gl._mk_fbo` 按格式选 `f2`/u1）与 VK
  （`_ensure_post_targets` 用 `t.format` 建纹理、`_ensure_post_pipes(fmts)` 按格式重建管线）都真读；
  探针：`bloom.half.format=rgba8unorm` → **GL 0.000316 / VK 0.000316**（改前两端 0）。
- 同引擎内动态改 scale：GL `ensure()` 缓存键改为 `(w,h,目标尺寸集合,目标格式集合)`；
  探针：同一 `GLPostChain` 内 half 0.5→0.4 → **240×160 → 192×128**（改前不重建）。

**Q2（真机 wgpu 0.32 拦不住）—— 改为诚实处理**：`adapter.info` 无 `api_version` 时**不再静默放行**，
打印 `[VK] 警告: 适配器信息未提供 api_version，无法校验显卡端 Vulkan 版本…`；
文档明确写「**无法校验**」：当前地板闸只对**加载器**做硬校验，adapter 侧仅尽力校验（K2b 断言警告存在）。

### 9.29 目标重新定义提案（待人类裁决，2026-11-11）

**提案**：把「重复语义面 ≤8」改为「**描述层共享 + 合理差异清单**」：①描述层（顺序/存在性/目标名/
depth/raster/load/clear/绘制源/后处理阶段与参数）必须单一来源；②「合理差异」必须**逐条登记**（阴影编码、
着色器语言），且每条给出为什么无法共享的 API/硬件依据；③其余项按「每项独立评估」不再折算成分数。

**理由**：分数口径会诱导重新分桶（本轮已发生两次），而真正影响维护成本的是「同一语义改一处还是改两处」。
**影响**：验收从「算分」变成「清单 + 反例矩阵」；需要维护一张差异登记表，新增差异必须走裁决。
**风险**：清单可能变成橡皮图章——因此每条差异必须绑定可复跑探针（如 format/scale/cull 反例）。
**在裁决前，本目标按 §9.28 记为未达成（9.5 > 8）。**


### 9.30 最终交付状态（2026-11-11 01:55）

| 项 | 状态 |
|---|---|
| 全量回归 | **135 文件全绿** |
| 包 = 代码 | source 93/93 双向 0 不一致；compiled `git_head=153c7896`，HEAD 改动非 Loom/ → **引擎等价 OK**；`dirty=false`；`smoke_passed_at 01:37:09 > built_at 01:24:06` |
| 构建器 P0 | **已修**（onefile 缺 ckernels + 定位走临时目录）；包内 `--help` exit=0、空目录报错清晰、真出包 exit=0 |
| 冒烟 | **7 项**（新增构建器/运行时）；逐件实测盖章；8.5s |
| 包内卫生 | 硬残渣 0 + 软残渣（`__pycache__`/`*.pyc`/`*.c.bak`）已排除 |
| Hub 0.1.4 | 26.02 MB，ProductVersion=0.1.4，PYZ 补丁 8/8，装机 `/status` 正常 |
| 发布说明 | engine/hub 两份草稿就绪 |
| **未达成** | **渲染语义面 11.5（剔除合理差异 9.5）> 目标 8**，等人类裁决 §9.29 提案 |
| 未做（等裁决后） | tag（`engine-v0.1.0.beta6` / `hub-v0.1.4`）、上传远端、最终重编对齐 git_head |

### 9.31 渲染目标修订（2026-11-11 人类裁决：改定义，beta6 发布继续延后）

**原目标**（14 项语义面全共享）经两轮独立复核判定不可达（折算 11.5 / 剔除合理差异 9.5，均 > 8），且与业界做法不符（Unity 为「单一源语言 + 兼容宏 + 多翻译器 + 差异关进后端」）。

**新目标（正式替代）**：

| 编号 | 目标 | 判定方式 | 当前状态 |
|---|---|---|---|
| **T1** | **描述层共享**：pass 顺序/目标语义名与格式尺寸/load/clear/depth/raster/绘制源/后处理阶段与参数，两端都由 FramePlan 消费 | 反例矩阵（改 plan → 两端同向且幅度比 ∈[0.5,2.0]），7 类已固化进 `test_frame_plan_vk` | ✅ 达成 |
| **T2** | **差异清单化 + 能力门控**：每条「不共享」必须写明原因、门控方式、验证探针；清单由人工裁决维护 | 清单条目每条绑定可复跑探针；探针红即清单失效 | ✅ **达成（2026-11-13）**：清单成文并裁决完毕 —— 4 不共享（D-01/03/04/05）+ 4 合理差异（R-01..R-04）+ 1 实现细节（I-01）；两条 T2 探针落地（`ab_ui_only` / `ab_mip_minify`） |
| **T3** | **着色器单源**：一份 GLSL 源（430 子集/450 Vulkan 规则）+ 兼容宏层 + 构建期 `glslang → SPIR-V` 供 VK；**手写 WGSL 归零** | `Loom/` 产品树手写 WGSL = 0（仅 P1 逃生舱 14 非空行，登记豁免）；每个迁移 shader 有像素证据 | ✅ **达成（2026-11-13）**：13 个 SPIR-V，§9.33–§9.35 逐块像素零变化 |

**T3 执行顺序（有依赖，不可乱序）**：**T3c 绑定模型统一 → T3b 兼容宏层 → T3a 单源化**。

**关键实测（决定选型）**：
- wgpu 能直接吃 GLSL，但 naga 的 GLSL 前端**不支持任何 sampler** → 直喂不可行
- GLSL → `glslang -V` → SPIR-V → wgpu：**UBO/SSBO/无描述符均 OK**；**合并采样器失败**（`invalid id %14`）；**分离采样器（texture2D + sampler）OK**
→ 结论：源语言选 **GLSL**；VK 侧走 SPIR-V；采样器差异由兼容宏切换。

#### T3 实现约定（Step A spike 实测，2026-11-11）

| 约定 | 原因 |
|---|---|
| 比较采样器必须写 `uniform samplerShadow`（不是 `sampler`） | 写普通 sampler 会在**模块创建期**被 naga 拒（`inconsistent comparison sampling`） |
| shadow 采样用 `texture2D`/`textureCube` + `samplerShadow`（不存在 `texture2DShadow` 类型，glslang 直接语法错） | 分离采样器写法 |
| BGL 侧：texture `sample_type='depth'`、sampler `'comparison'` | wgpu 校验要求 |
| 片段 `layout(location=N) in ...` 要求顶点段有同 location 的 out | 否则 naga 报输入不匹配 |
| 实例属性用 `layout(location=N) in vec4`，VK 侧 `step_mode='instance'`、GL 侧 `divisor` | 两端语义对齐 |

### 9.32 T3c-4=① 落地：GL 阴影改手工比较（2026-11-11）

人类裁决 ①（都改手工比较）已执行：GL 阴影深度纹理改为 `compare_mode=NONE` + `NEAREST`，
主片段 `u_shadow_maps` 从 `sampler2DShadow` 改成 `sampler2D`，`pcf_shadow()` 改为
**9 次原始深度采样 + 显式 `d >= depth - bias` 比较 + 平均**，与 VK `pcf()` 逐字一致；
点光 cube 阴影（GL 侧同样是 6 张 2D 面 + 同一 pcf_shadow）一并切换，距离归一与比较方向不变。

**实测**：`ab_c_dir_shadow` GL/ref=**2.9e-5**、`ab_point_shadow`=**2.5e-5**（⚠ 此值有误，2026-11-13 实测 GL 为 **5.7e-5**，见 §9.33「基线订正」）、`ab_scene`=**2.6e-5**
（均 ≤2e-4 门限，参考图**不重生成**）；`ab_gl_vk` 23/23 PASS；14 套 488 项 FAIL=0。
**代价**：阴影边缘有 ≤3e-5 的软化差异（硬件双线性比较 vs 最近邻比较），文档留档。
**帧时间**：`measure_engine --runs 3` 改前 214.6（213.2–217.1）/ 改后 209.1（209.1–216.8），
区间重叠、差值在噪声内（每像素仍是 9 次阴影采样，带宽不变）。
**WGSL 行数**：本轮未删除 VK 阴影 WGSL（其手工比较仍在 WGSL 里）；因两端算法现已逐字一致，
下一步可把 `pcf` 单源化（VK 侧预计可删 ~12 行 WGSL）。

### 9.33 T3a-3 主 pass 片段单源化完成（2026-11-13）

**结论**：主 pass 的片段着色器已并入单源链路 —— `Loom/shaders/main.frag`（264 行，GLSL 450）→ `glslang -V --target-env vulkan1.1 -DLOOM_VK` → `main.frag.spv`（33 156 B）→ `wgpu.create_shader_module`（entry_point=`main`）；GL 侧直接读同一份源码（450→430 展开）。**VK 手写 WGSL 删除 289 行**（`_MAIN_VERT` + `_MAIN_FRAG` + `pcf`/`pcf2`）。

**四道门（本次每一条都是真跑）**

| 门 | 结果 |
|---|---|
| 1 编译 | `py -3.13 tools/build_shaders.py` EXIT=0，**6 个 .spv**（main.frag 33156 B / main.vert 4424 B / 4 个 post） |
| 2 像素 | `test_ab_gl_vk.py` **23/23 PASS**，EXIT=0；22 个场景三向 MAE 与改前**逐值相同** |
| 3 回归 | 135 文件；修掉 2 处既有缺陷后**全绿**（见下「既有缺陷」） |
| 4 grep | `vk_renderer.py` 中 `_MAIN_FRAG`/`_MAIN_VERT`/`fn pcf`/`pcf2` = **0**；`#ifdef LOOM_VK` 仍只在 `loom_shader_compat.glsl` |

**唯一像素变化：`ab_point_shadow` 的 VK 侧（变好，不是变差）**

| 项 | 改前 | 改后 |
|---|---|---|
| VK/ref | 0.000051 | **0.000046** |
| GL/VK | 0.000045 | **0.000011** |
| MAX | 0.0941 | **0.0314** |
| NCC | 0.999306 | **0.999825** |

原因：旧 VK `pcf` 用 `textureSample` + `bias=0.002`；单源后与 GL 完全一致 —— **`texelFetch` + `bias=0.004`**（都是 9 tap，采样次数不变，无性能代价）。GL 侧一个字节未变。

**顺带修掉的两处既有缺陷（都是 T3c-1 `4a66faa` 引入，与本次单源化无关）**

1. **P0：GL 世界 UI / 线条着色器编译失败**。`4a66faa` 把 `_WORLD_UI_VERT`/`_LINE_VERT` 里的 `u_view_proj` 批量误替换成 `uniform mat4 u.mvp;` —— 带点的名字是**非法 GLSL**，两个程序直接编译失败（`engine.py:761`），世界空间 UI 与 gizmo/网格/选中框在 GL 上**完全画不出来**。`engine.py:793`、`loom_render.py:379` 仍在读 `u_view_proj`，证明正确名字就是它。已改回 4 处（2 声明 + 2 使用），5 个测试（cubemap/texture/lod/eai_real/integration）转绿。
2. **`test_light_shadow_slots.py` 自 `4a66faa` 起失效**：它读的是已被删除的具名 uniform `u_shadow_slot`（T3c-1 把槽位搬进 std140 Scene UBO），属测试债。已改为校验新通路（见该测试文件内断言）。

**过程教训（写进流程，不只是修完就算）**

§9.30 记录的「135 文件全绿」是 **2026-11-11 01:55** 的状态，而 `4a66faa`（T3c-1）**12:05** 才落地；此后 T3c-2/3/4 每批只跑了 `ab_gl_vk` + 14 套，**再没跑过全量回归**，于是上面那两处红一直挂着，交接文档却写着「全绿」。
→ **规则（已并入 `docs/design/开发流程_冒烟与验证分层.md`）：任何 `refactor(shader)` 类提交后，四道门必须整套重跑；「上一批全绿」不能当作「本批全绿」的证据。**

**基线订正（原文档数字是错的）**

`ab_point_shadow` 的 GL 基线在 handoff / 本文 §9.32 写的是 `2.5e-5`，**干净 HEAD 实测是 `0.000057`**（连跑两次一致），`final_03` 里写的 `0.000051` 其实是 VK 值。以本次实测为准：**GL 5.7e-5 / VK 4.6e-5**（门限 2e-4）。

### 9.34 天空 / 阴影 pass / mip 单源化完成（2026-11-13）

**结论**：`vk_renderer.py` 里剩余三块手写 WGSL（`_SHADOW_VERT` 37 行、`_SKY_WGSL` 29 行、`_MIP_WGSL` 14 行，共 **80 行**）已清零，改为 5 个单源文件 → 5 个 SPIR-V：

| 源 | 行数 | GL 对应物 | 处理 |
|---|---|---|---|
| `shaders/shadow.vert` | 23 | ✅ `loom_shaders._SHADOW_VERT` | **GL 也改读同一份** |
| `shaders/shadow.frag` | 25 | ✅ `loom_shaders._SHADOW_FRAG` | 同上；GL 写 `gl_FragDepth`，VK 写 `frag_color.r`（宏） |
| `shaders/sky.vert` | 16 | ✅ `loom_shaders._SKY_VERT` | GL 用 quad VBO 6 顶点；VK 无顶点缓冲全屏三角 3 顶点（宏） |
| `shaders/sky.frag` | 23 | ✅ `loom_shaders._SKY_FRAG` | 反投影公式逐字同一 |
| `shaders/mip_downsample.frag` | 17 | ❌ **GL 没有** | GL 是驱动 `glGenerateMipmap`（`loom_texture.py:182` / `loom_cubemap.py:203`），无 shader 阶段 → **不假装统一**，登记为 T2 差异 **D-06** |

`loom_shaders.py` 从 370 行降到 **173 行**（第二份 GLSL 文本全部删除，改为 `_shared_shader_src()` 加载同一份源）。SPIR-V 总数 **11 个**（之前 6 + 新增 5）。

**四道门（主审独立复跑，不是转述实现者）**

| 门 | 结果 |
|---|---|
| 1 编译 | `py -3.13 tools/build_shaders.py` **EXIT=0**，11 个 .spv（shadow.vert 2308B / shadow.frag 1556B / sky.vert 1220B / sky.frag 2184B / mip_downsample.frag 1084B） |
| 2 像素 | `test_ab_gl_vk.py` **EXIT=0**，23 PASS / 0 FAIL |
| 3 回归 | `run_all.py` **EXIT=0**，「全部测试完成 ✅」（135 文件） |
| 4 grep | `_SKY_WGSL` / `_SHADOW_VERT` / `_MIP_WGSL` 在 `vk_renderer.py` = **0**；`#ifdef LOOM_VK` 仍只在 compat |

**像素零变化**（逐值对比，改前 == 改后）：`ab_sky` 1.2e-5/1.2e-5/0、`ab_tex` 0/0/0、`ab_c_dir_shadow` 2.9e-5/5.1e-5/2.9e-5、`ab_point_shadow` 5.7e-5/4.6e-5/1.1e-5、`ab_scene` 2.6e-5/4.6e-5/2.8e-5；其余 18 场景三向 MAE 同样不变，UI 子项 1.10e-4 不变。

**为什么能零变化（两处看似改了算法的地方）**

1. 阴影深度：两端都改成 `SHADOW_STAGE_DEPTH = gl_FragCoord.z` —— GL 的 `gl_FragCoord.z` 本来就是窗口深度，VK 的本来就是 NDC z（wgpu 的 NDC z 即 [0,1]），**同一个表达式在两个 API 里各自是对的**，比分别写两套公式更稳。
2. 天空角度：VK 从「`gl_FragCoord` + `SkyC.size` 换算」改成「顶点插值 `v_ndc`」，与旧公式同一函数（`SkyC.size` 字段暂留未删）。

**当前全仓剩余手写 WGSL：71 行**

| 位置 | 行数 | 状态 |
|---|---|---|
| `vk_renderer._MAIN_P1_VERT/_FRAG`（P1 逃生舱） | 16 | **豁免单源化**（2026-11-13 裁决）：`--stage p1` 诊断用，GL 无对应阶段、零场景覆盖；**但补一条假设备「p1 管线能建起来」的受跟踪测试作为豁免前提**（现在连这个都没有）→ A1-8 |
| `vk_ui.py`（UI 顶点 + 片段） | 55 | **A1-4**，未开始 |

### 9.35 UI 单源化完成（T3 收口）+ 修一条会假红的性能门（2026-11-13）

**UI 单源化**：`vk_ui.py` 的两块手写 WGSL（`_UI_WGSL` 31 行 + `_WORLD_UI_WGSL` 24 行，共 **55 行**）清零。新增 `shaders/ui.vert`（19 行）+ `ui.frag`（15 行），**一条 pair 同时服务「屏幕 HUD」与「world Canvas」两条管线**：

| 用途 | GL 对应物（`loom_shaders.py`） | VK |
|---|---|---|
| 屏幕 HUD | `_HUD_VERT`/`_HUD_FRAG`（`engine.py:313` 编译；`loom_hud.py` 绘制） | `vk_ui.py` 原 `_UI_WGSL` |
| world Canvas | `_WORLD_UI_VERT`/`_WORLD_UI_FRAG`（`loom_render.py:258-273` 建，`369-390` 画） | 原 `_WORLD_UI_WGSL` |

→ GL 侧两个 program **都改读同一份源**（`_shared_shader_src('ui.vert'/'ui.frag')`），`loom_shaders.py` 再删 43 行。差异全进 compat：VK 用 `UIC.ui_screen.z>0.5` 分支、顶点统一 36B（pos3+uv2+color4）、`UIC` UBO 80B；GL 用 `u_mode`（world program 创建时置 1）。

**四道门（主审独立复跑）**

| 门 | 结果 |
|---|---|
| 1 编译 | EXIT=0，**13 个 .spv**（新增 `ui.vert.spv` 2160 B / `ui.frag.spv` 828 B） |
| 2 像素 | `test_ab_gl_vk.py` **EXIT=0 / 23 PASS / 0 FAIL**；`ab_ui_scene` 整帧 2.2e-5/6.6e-5/5.3e-5、**[UI] 子项 1.10e-4** 逐值不变 |
| 3 回归 | 修掉下面那条假红门后 `run_all.py` **EXIT=0**（136 个测试，含新增 `test_vk_p1_stage.py`） |
| 4 grep | `vk_ui.py` 里 `@vertex`/`@fragment`/`@group`/`textureSample`/`var<uniform>` = **0**；`#ifdef LOOM_VK` 仍只在 compat |

另做了**旧 vs 新直接对拍**（把 HEAD 的旧 WGSL/GLSL 原文内联，同设备/同顶点/同纹理/同混合）：VK screen / VK world / GL HUD / GL world 四项 **MAE=0、MAX=0、diffpx=0**。

**全仓手写 WGSL 现状**：主 pass / post / 天空 / 阴影 pass / mip / UI **全部 0**，只剩 `_MAIN_P1_VERT`+`_MAIN_P1_FRAG` **16 行**（P1 诊断逃生舱，裁决豁免，前提是有 `test_vk_p1_stage.py` 证明管线能建起来，已补）。→ **T3「手写 WGSL 归零」达成（排除已登记的 P1 豁免）**。

**顺带修掉一条会假红的性能门（`test_bucket_pack.py`）**

同一天、同一二进制、**没有任何代码变化**，实测比值 0.75（连续跑测试时，CPU 热）→ **0.83 / 0.84 / 0.79**（冷机睿频），把 `run_all` 判成红。C 路径是内存带宽型、Python 路径是计算型，CPU 睿频/热降频影响不同 → 墙钟比值不耐负载。

改为分层（并写进 `开发流程_冒烟与验证分层.md` §5.3）：**回归层只挡真实回归**（`C 不得慢于 Python`，ratio ≤ 1.00），`≤0.80x` 的目标归还**测量层**（空闲 + n=5）。判据改动留下的前后数字就是 0.75 → 0.83。

**遗留**：23 场景的 FramePlan 未开 `include_world_canvas`（`editor.py:2490-2492`），world Canvas 在真实夹具里没被像素门覆盖 —— **预存在的夹具缺口**，本次用直接对拍补证；补场景属 A2-2 探针工作。

**A1-7（设计稿遗留的 `VertexLayout`/`ShaderSet`）同时裁决**：`VertexLayout` 不需要新建 —— `loom_shader_bindings.VERTEX_LAYOUT`（location 0/1/2/13，48B stride）与 `INSTANCE_LAYOUT`（96B）就是两端共用的布局单点表，T3c-3 落地且有 `test_bucket_pack` 断言；`ShaderSet` **明确不实现** —— T3 之后每个 pass 就是固定 vert+frag 一对，而 wgpu 的 `create_shader_module` 一个模块只能装一个 stage，再包一层只是套壳。设计稿按此标注「不实现」。

---

### 9.36 T2 探针补齐：纯 UI（D-05）与非 2 的幂 mip（原 D-06 → R-03）（2026-11-13）

**结论**：`docs/design/T2差异清单_beta6.md` 的每一条现在都绑定可复跑探针。按 Q-T2-1/Q-T2-2 裁决，清单从「6 条不共享 + 2 条合理差异」重排为 **4 条不共享（D-01/D-03/D-04/D-05）+ 3 条合理差异（R-01/R-02/R-03）+ 1 条实现细节（I-01，不入清单）**；两条新探针纳入 `test_ab_gl_vk.py` 受跟踪门，场景数 **23 → 25**。

#### 探针 1（D-05）：`ab_ui_only.json` —— 纯 UI，不让 3D 稀释

- **夹具**：480×320 全屏 Canvas；不透明 panel 铺满整帧，上面只有矩形/文字/折线/圆点（无贴图、无字体路径）。无 UI 帧只剩纯色天空，**没有可见 3D 像素**。
- **为什么能暴露**：GL 的 `GL_LINES` 与 VK 的三角带在斜线/端点覆盖规则上**非逐像素等价**（`vk_ui.py:243-255` 契约）；旧 `ab_ui_scene [UI]` 只有 1.10e-4，因为 UI 只占画面一部分、且没有密集斜线。新场景让 UI 覆盖 100% 像素，差异不再被 3D/平坦区域稀释。
- **实测**（2026-11-13，GTX 1050 Ti / Vulkan）：[UI] **MAE 0.00272581**、MAX 0.913725、NCC 0.9559571、diffpx 1333/153600（0.87%）；3×3 全差异内部=0、1333/1333 在 GL 边缘 1px 内（边缘覆盖差，不是块状缺陷）；主三向 MAE 0/0/0（无 UI 帧只有背景）。
- **门限**：沿用既有 `ui_mae_abs=5e-3`，**未改**；余量 0.00227419（门限的 45.5%）。基线 0.00272581。

#### 探针 2（原 D-06 → R-03）：`ab_mip_minify.json` —— NPOT + 强缩小

- **夹具**：`assets/tex/ab_mip_checker_301.png`（301×301，非 2 的幂；16px 彩色棋盘 + 7px 斜纹 + 水平渐变，`make_assets.py` 确定性生成，无 RNG、无绝对路径）；贴在 4×4 的 quad 上、相机距离 16、正对相机 → 屏幕约 **69px**，301/69≈**4.3×** 缩小，三线性采样落在 mip 2↔3 之间。
- **为什么能暴露**：mip 关（`mipmaps:false`）时两端都只采 level 0，**GL/VK MAE≈4.3e-7（6 位打印 0.000000）**；mip 开时 GL 驱动 `glGenerateMipmap` 与 VK `shaders/mip_downsample.frag` 逐级降采样的差异才显形。mip 开/关：GL 0.00136052、VK 0.00116709（同一贴图/同相机）。
- **实测**：GL/参考 0、VK/参考 **0.00058264**、GL/VK **0.00058264**、MAX 0.160784、NCC 0.98851881。
- **门限**：Q-T2-1=A 接受为合理差异 → **场景级** `mae_abs=1e-3`（基线行，只作用于 VK/参考 与 GL/VK），余量 0.00041736（门限的 41.7%）；**全局 2e-4 不动**，GL/参考仍 2e-4，漂移门仍是 `基线+5e-5`（0.00058264 → 0.00063264，比场景上限更紧）。
- **诚实声明**：实测 0.00058264 **超过**全局 2e-4。没有改全局门，而是按人类裁决在基线行写场景级容差，并在 `test_ab_gl_vk.py` 里用 `SCENE_MAE_ABS` 单点登记；`--append-baseline` 拒绝覆盖既有场景条目。

#### 基线只增不改（机器证据）

- 新增参考图 3 张：`ab_scenes_ref_next/ab_ui_only.png`、`ab_ui_only__ui.png`、`ab_mip_minify.png`；新增基线行 2 条。
- 既有 `ab_scenes_ref/` 24 个 PNG、`ab_scenes_ref_next/` 既有 24 个 PNG 的 sha256 **逐值不变**；既有 23 条基线行 JSON **逐值不变**（`--append-baseline` 只 merge 新条目）。
- 旧口径回退证明：`LOOM_POST=0 py -3.13 tests/test_ab_gl_vk.py` → **23 PASS + 2 SKIP（POST_ONLY 白名单）、EXIT=0**。

#### 验收

- `cd Loom; py -3.13 tests/test_ab_gl_vk.py` → 25 场景、0 失败、0 跳过，**EXIT=0**；既有 23 场景三向 MAE 与改前逐值相同。
- 两条新场景原文：`ab_ui_only [UI] UI MAE(gl/vk)=0.002726 MAX=0.9137 NCC=0.955957 基线 0.002726`；`ab_mip_minify MAE(gl/ref,vk/ref,gl/vk)=0.000000/0.000583/0.000583 MAX=0.1608 NCC=0.988519 基线 0.000583 场景门限 0.001000`。
- `run_all.py` → **EXIT=0，136 个测试文件全绿**（未新增测试文件；两条探针是场景数据，不是 `test_*.py`）。原文末行：`全部测试完成 ✅`；其中 `test_ab_gl_vk.py` 段原文：`--- 场景 25, 失败 0, 跳过 0 ---`。本轮 `run_all` 含主审的 `Loom/sceneio.py` 构建器瘦身改动，全绿。

#### 实现约束（未改引擎）

VK 在 **0 个可见实例**时会走 `queue.write_buffer` 空写并抛 `ValueError: Invalid data_offset`（`vk_renderer.py:1811`）。本轮不许改引擎，`ab_ui_only` 保留一个位于远平面外的 0.01 单位 sentinel 满足 VK 的非空实例要求；实测无 UI 帧两后端 MAE=0、sentinel 不贡献像素。这是 VK 健壮性缺口，不是 GL/VK 语义差异，未登记进 T2 清单。

**测试夹具状态修正（D-05）**：GL 的 Shape 描边走 `draw_lines`，不像 panel/text 那样在自己的 `ctx.scope` 里关深度；`ed.render()` 后直接 `ui.draw_all` 会继承最后一个 pass 的深度测试，3D 深度非 1 的位置整条线被丢掉（实测 chart 线 0 像素）。本轮在**测试夹具**的 `ui.draw_all` 前补 `ctx.disable(DEPTH_TEST)`（避免把上一个 pass 的深度状态当成 UI 差异；UI 元素自己的 `ctx.scope` 也关深度），既有 `ab_ui_scene [UI]` 输出逐字节不变（MAE=0）。引擎侧「Shape 线依赖调用方深度状态」的健壮性缺口留待主审裁决，本轮不改引擎。

### 9.37 构建器瘦身 + UI 描边差异裁决（2026-11-13）

**背景**：`build_game.exe` 从 onefile 改 onedir 后，dist 从 23.5 MB 涨到 **89.56 MB**（Python 运行时 + 依赖全摊在目录里）。逐项拆解发现主因是**一行 import 的连带**。

**根因（两层）**

1. `Loom/sceneio.py:54` 为取两个纯数据/纯数学符号写了 `from engine import Point3D, wrap_deg` —— 而 `engine.py` 模块级 `import numpy/pygame/moderngl`，于是整张编辑器引擎图被拖进 `build_game` 的静态 import 图；
2. 即使修掉第 1 条，**Nuitka 仍会静态跟随函数体内的 import**（实测：`def f(): import pygame` 从未被调用，pygame 仍进 dist，对照实验见 `C:\loom_build\probe_fn`），所以 `loom_material`/`loom_texture` 里 `from engine import GameObject` 这种延迟 import 依然有效。

**改法（5 处；`engine.py`/`loom_render.py`/`loom_lighting.py` 零改动）**

| 文件 | 改法 |
|---|---|
| `sceneio.py:54` | `from loom_types import Point3D` + `from loom_scene_entities import wrap_deg`（从定义处导入） |
| `scripts.py:31` | `from engine import Point3D` → `from loom_types import Point3D` |
| `loom_material.py` / `loom_texture.py` | bump 改写 `loom_appearance.bump()`（不再 `from engine import GameObject`） |
| `loom_game_object.py` | 删类属性 `_appearance_gen = 0`，改 `_AppearanceGenMeta` 提供**类级 property**（读→`gen()`、写→`set_value(v)`），`GameObject._appearance_gen` 读写语义不变 |
| **新增** `loom_appearance.py` | 零依赖单调整数：`gen()/bump(n)/set_value(v)` |

**静态自证**：从 `build_game.py` 出发 AST+BFS（含函数体内 import），可达项目模块 **62 → 23**，`engine` **不可达**。

**数字（前 → 后）**

| 指标 | 前 | 后 | 变化 |
|---|---|---|---|
| `build_game.exe` | 30.98 MB | **26.37 MB** | **−4.61 MB（−14.9%）** |
| builder dist | 89.56 MB / 252 文件 | **80.08 MB / 248 文件** | **−9.48 MB（−10.6%）** |
| culverin / culverin.libs / glfw / msvcr120 | 3.18 / 0.55 / 0.21 / 0.92 MB | **全部消失** | −4.86 MB |

**保留（不是遗漏，是运行期真需要）**：`pygame` 9.10 MB（旧 path 材质解码、UI 场景解析）、`moderngl` 0.16 MB（`ensure_gl`）、`numpy` 26.24 MB（mesh / fastpath）。对应直接边：`audio_backend:99/108`、`loom_cubemap:18/208`、`loom_texture:24/169`、`loom_ui:799/999`。

**验证（全真跑）**

| 项 | 结果 |
|---|---|
| `run_all.py` | **EXIT=0，136 个测试全绿**（含本次 5 处改动） |
| `check_binary_hygiene.py` | **EXIT=0**（CompanyName=lhy302 / ProductName=Loom / FileDescription=Loom 游戏打包器（将项目打包为独立游戏）/ FileVersion=0.1.0.6；形态判定 onedir） |
| `build_game.exe --help` | **EXIT=0** |
| **最小出包 × 2**（模拟安装布局 …/engroot/builder/，引擎根在上一级） | 物理场景 **ExitCode=0**、UI 场景 **ExitCode=0**；两次都产出 `MyGame.exe` + `游戏包.lsc`（279 files / 143.4 MB）。**证明清掉 culverin 后物理场景仍能出包**（builder 只构造 RigidbodyComponent，不跑 Jolt） |

**顺带裁决：Q-PAR-1 = A（UI 描边 1px 覆盖差接受为合理差异）**

`ab_ui_only` 把这条一直存在但**没有观测者**的差异测了出来：`[UI] MAE=2.726e-3`，差异像素 **1333/153600 = 0.87%**，**100% 落在高梯度边缘 1px 内、3×3 全差异内部 = 0 个**。根因是 GL 走 `GL_LINES`、VK 用三角带（`vk_ui.py` R2 契约 `STROKE_PIXEL_EQUIVALENT=False`）。登记为 **R-04**；门控沿用**仓库既有** `ui_mae_abs=5e-3`（本轮未改）。若将来两端都改三角带，D-05 与 R-04 同时消失。

**本轮发现的两个既有缺陷（未修，已登记）**

1. **VK 在「0 个可见实例」时会崩** → `ab_ui_only` 只能用远在 (1000,1000,1000) 的哨兵物体绕过（B13）；
2. **GL 的 Shape 描边依赖调用方深度状态**（`draw_lines` 不像 panel/text 自己在 `ctx.scope` 里关深度）→ 夹具显式 `disable(DEPTH_TEST)` 才画得出来（B14）。

**方法教训（写进流程）**：判断「某依赖会不会进打包产物」**只能看静态可达图**，不能用运行时 `sys.modules` 探针 —— 首轮就因此误判为已瘦身，实际 dist 逐文件未变。

### 9.38 收尾倒查（独立子代理）与文档修正（2026-11-13）

**结论**：按 §9.31 修订后的 **T1/T2/T3 三项目标均有可复跑证据支撑**；四道门（构建 / 像素 / 回归 / 包=代码）由倒查者**独立复跑**为绿，数字与 §9.33–§9.37 逐值吻合。判定为**有条件达成** —— 发布前必须先刷新发布说明与交接文档，否则会发布「11.5 未达成 + 旧哈希」。

**P0（会误导发布，已修）**：`tools/release_notes/engine-0.1.0.beta6.md` 整篇过期，而 `release_github.py:403-408` 会原样把它作为 Release 正文。已改为真实数字（25 场景 / 97:97 / `git_head=75b8082` / 新两包哈希 / builder onedir 80.08 MB）。

**P1（已修）**：
1. `接手须知_beta6当前状态` 的 HEAD / T2 状态 / 场景数 / 「旧包已过期」全部过期 → 已刷新；
2. §9.31 目标表仍标 T2/T3 ⏳ → 已回写 ✅ 并补证据；
3. 未完项清单 C1/C2 仍写「必须重打」→ 已标完成；
4. **A1-8 豁免前提被夸大**：`test_vk_p1_stage.py` 用假设备，`create_shader_module` 只返回 dict、**不解析 WGSL**，所以只能证明「管线对象被创建」，证明不了「那段 WGSL 语法正确」→ 三处文档已改成如实表述，真机 p1 测试列为遗留；
5. **A2-2 探针覆盖不全**：`ab_*` 场景只有 screen canvas，`editor.py:2490-2492` 未开 `include_world_canvas` → world Canvas 一半没有像素探针（§9.35 用一次性对拍补证）→ A2-2 降级为 🟡 并写明缺口；
6. D4 被误标 ✅ 但两个 spike 文件仍在、无 comparison-sampler 矩阵测试 → 改 ⏳ 未执行。

**P2（登记未修）**：若干措辞/行号/编号不一致（370 vs 200 行、「16 行」vs 14 非空行、`ui.frag` 15 vs 18 行、T2 清单行号漂移、路线登记缺 B7-14…18、产品内仍有 `py -3.12` 用法行等）。逐条列在 `docs/audit/final4_01_收尾倒查_20261113.md` §4。

**倒查者明确「无法验证」的**：冒烟 7 项本身、§9.37 的完整出包 ×2、§9.35 的一次性对拍、Hub 包内是否嵌 git_head、真机 360/GUI 读数。

完整报告：`docs/audit/final4_01_收尾倒查_20261113.md`。

### 9.39 world Canvas 像素探针 → 暴露并修好「默认后处理下 World Space UI 不可见」（2026-11-13）

**起因**：收尾倒查指出 T2 的 D-05（UI 光栅化）只覆盖 screen canvas，**world Canvas 一半没有像素探针**。补探针时立刻现形一个真缺陷。

**症状（补探针前无人知晓）**

| 配置 | world Canvas 表现 |
|---|---|
| **默认（post on）** | **VK 贡献为 0**（with/without canvas 的 MAE 完全相同）；**GL 播放态**把 quad 画到屏幕 FBO，随后被 tonemap 覆盖 → 同样看不见 |
| post off | 两端都画，GL/VK **1.0514e-4** |

即：**这个功能在默认配置下根本不可见**，而 23/25 个场景没有一个带 world canvas。

**根因**

1. **VK**：`render_world_canvases` 在 pass 循环**之前**建 `VkWorldUIPipeline` 与其 BGL，此时 `_frame_fmt` 还是 `present_format`(rgba8)；随后 `world_ui` pass 把 `_frame_fmt` 换成 HDR(rgba16float) 并重建 pipeline（新 BGL），但 `_world_targets` 里的 **bind group 仍绑旧 BGL / 旧 uniform buffer** → draw 无效。
2. **GL**：`_draw_one_world_canvas` 的 `finally` 无条件 `_screen_fb().use()`；post on 时 pass 目标是 HDR，不是屏幕 → quad 画错目标后被 tonemap 覆盖。

**修法（三处，均为最小改动）**

| 文件 | 修法 |
|---|---|
| `vk_renderer.py:1699-1709` | 在 `render_world_canvases` 前按「本帧是否有 world Canvas」把 `_frame_fmt` 定为 `rgba16float`(post on) / `self.format`(post off)，让 pipeline/BGL 与随后 pass 目标一致；**不改渲染顺序** |
| `loom_render.py:322-357` | `_draw_one_world_canvas` 用 `ctx.detect_framebuffer()` **保存/恢复调用前的绑定 FBO**（而不是无条件 `_screen_fb().use()`），播放态与编辑态一起修 |
| `editor.py:2489-2502` | 编辑器 `frame_plan(...)` 补 `include_world_canvas`，判据是 **`canvas_type == world`**（`ui.canvases` 恒含一个默认 screen Canvas，不能用非空判定）；为绕坑加的临时 override 已删 |

**前后数字（同一场景 `ab_world_canvas`）**

| 指标 | 修前 | 修后 |
|---|---|---|
| post on GL/VK MAE | **1.6479e-2**（门限 2e-4 的 82 倍） | **5.22e-5** |
| VK canvas 贡献（with − without） | **0** | **1.6468e-2** |
| post off GL/VK MAE | 1.0514e-4 | **1.0514e-4（逐值不变）** |
| 既有 25 场景三向 MAE / 参考图 sha256 | — | **逐值不变** |

**探针有牙自证**：临时把 `include_world_canvas` 关掉 → `FAIL ab_world_canvas`（GL/参考 0.012757、GL/VK 0.012742，EXIT=1）；还原后 PASS。

**验收**：26 场景 / 失败 0 / EXIT=0；`run_all` **136 全绿**；新场景无场景级容差（全局 2e-4 未动）。

---

## 10. 延迟项落盘规则（人类要求，2026-11-09；2026-11-13 移到文末，此前误插在 §9.1 与 §9.2 之间）

> **凡本版不做的路线，必须写进 [路线登记_后续版本.md](路线登记_后续版本.md)，不得只留在对话里。**
> 该文件含：预定 beta7 项（B7-01~B7-18）、滚动待办（N-01~N-14）、**beta6 末期检查点**、已取消项留痕（X-01~X-07，X-03 已于 2026-11-11 作废）。
> beta6 收尾前必须执行一次检查点：逐项判断是否已被顺手解决、是否有 1-2 项可提前做、VS2026 是否升级，并把结论回写。

