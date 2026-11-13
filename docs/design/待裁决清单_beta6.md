# beta6 待裁决清单（人类：集中回答，不打断执行）

> 规则（2026-11-09 人类指示）：**所有需要人类拍板的问题先缓存到本文件**；等没有子代理/后台任务在跑时**一次性提出、一次性回答**。
> 不需要裁决的操作照常推进。每项打 `待答` / `主审暂定（可推翻）` / `已实现（主审暂定）` / `已关闭`。**2026-11-13 核对：A 组当前无待答项**；历史条目全部已关闭或已实现（证据见各行与 `docs/audit/doc_closeout_20261113.md`）。

## A. 裁决记录（2026-11-13 核对：无待答项）

| # | 问题 | 选项 | 主审建议 | 状态 |
|---|---|---|---|---|
| ~~Q-PKG-1~~ | 源码包内嵌哪个 Python | **已关闭（A，计划 §9.9 Q1）**：打包器按 `解释器.json.python_version` 解析 embeddable（现 3.13.15），版本不一致即打包失败 | — | 已关闭 |
| ~~Q-PKG-2~~ | 包内 `python/` 被系统 Python 顶替 | **已关闭（A，计划 §9.9 Q2）**：人类裁决**包内解释器权威**（不顶替）；实现 `LoomHub/hub_config.py:862-868`；Hub 侧同口径（Q-HUB-1 一并关闭） | — | 已关闭 |
| ~~Q-PKG-3~~ | 编译包里的 `Loom.bat` | **已关闭（B，计划 §9.9 Q4）**：bat 现优先 `Loom\Loom.exe`（编译版）再回退 python；实现 `tools/package_engine.py:420-441`；README 同步 | — | 已关闭 |
| ~~Q-VK-1~~ | 显式 `--backend vulkan` 失败是否改写配置 | **已关闭（A，计划 §9.9 Q7/§9.3）**：不改写；实现与断言 `Loom/tests/test_backend_fallback_policy.py:171-185` | — | 已关闭 |
| ~~Q-VK-2~~ | VK 回退写哪层配置 | **已关闭（A，计划 §9.9 Q8/§9.3）**：只写用户层 `游戏设置.json`；断言 `Loom/tests/test_backend_fallback_policy.py:491-503` | — | 已关闭 |
| ~~Q-PERF-1~~ | 3.12 vs 3.13 FPS 重测 | **已关闭**：已测（计划 §9.10：3.12/3.13 交替 n=5，中位 90/78）+ 人类裁决**性能下降可接受**（计划 §9.16），`FPS>=85` 不再是硬门 | — | 已关闭 |
| ~~Q-HUB-1~~ | Hub 用包内还是系统解释器 | **已关闭**：与 Q-PKG-2 同口径——**包内权威**；已实现 + `test_hub_python_version` 覆盖 | — | 已关闭 |
| ~~Q-HUB-2~~ | 源码包 embed 版本是否升格为发布硬门（元数据 3.13.15 与包内 3.12 不一致时拒绝出包） | **已关闭（A，计划 §9.9 Q3）**：不一致拒绝出包；实现 `tools/package_engine.py:383-388`（负向实测见 `research_beta6_06_toolchain_upgrade.md:458`） | — | 已关闭 |
| ~~Q-HUB-3~~ | 冻结版（LoomHub.exe）兜底找解释器会再拉起 Hub 抢焦点 | **已关闭（B，计划 §9.9 Q5）**：改用 `sys.version_info`，不拉子进程；实现 `LoomHub/hub_config.py:697-703`；`Loom/tests/test_hub_python_version.py:351-386` 覆盖 | — | 已关闭 |
| ~~Q-REQ-1~~ | 源码包 requirements 是否补 culverin/game-audio | **已裁决 A（2026-11-10）**：已补进 requirements.txt 并把安装提示改 3.13 | — | 已关闭 |
| **Q-PKG-4** | 源码包与编译包默认写**同一个** `Loom-<version>.zip`（会互相覆盖；R06 已把源码包另存到别处规避） | **A（已实现）**：按 `--kind` 分名 `Loom-<ver>-source.zip` / `-compiled.zip`；`tools/package_engine.py:614,650-654,718-719`；`Loom/tests/test_release_version.py:110-113` 断言 | **A** | 已实现（主审暂定） |
| **Q-VIS-1** | 阶段 2B2 引入 tonemap + bloom 后**画面会故意变化**：新视觉基线是否接受（需要你/人眼确认一组参考图） | **已关闭（B→A，计划 §9.13/§9.14）**：先调参（exposure=1.70、bloom 0.70）再接受新基线；`Loom/tests/test_post_bloom.py` 量化断言（晕圈 ≥+5%，实测 +22.1%） | — | 已关闭 |
| ~~Q-VER-1~~ | 播放器遇到「场景要求更高引擎版本」时，现在是 `SceneVersionError` 以 traceback 呈现（发布版无控制台 = 无提示）；是否改成「弹窗 + 明确原因 + 优雅退出」 | **已关闭（A，计划 §9.18）**：弹窗 + 明确原因 + 优雅退出；实现 `Loom/run_player.py:265,401`、`Loom/scene_driver.py:620-627`；`Loom/tests/test_scene_version_player.py` 覆盖 | — | 已关闭 |
| **Q-VER-2** | 打包产物是否带 `解释器.json`（现在 Nuitka 产物没有它，`ENGINE_VERSION` 走常量兜底 `0.1.0.beta6`；每次发版必须手改这一行） | **A（已实现）**：打包链把 `解释器.json` 带进产物并断言；`tools/build_engine.py:141-159`、`tools/package_engine.py:114-128`（缺/版本不符即失败） | **A** | 已实现（主审暂定） |
| ~~Q-D1-1~~ | C 打包返回非 0 时的行为 | **已裁决 A（2026-11-10）**：保持硬 raise。人类原话：内核返回错误码说明内核稳定性有问题，该死磕的是内核稳定性；**组件之间不互相兜底**，自己的稳定性自己死磕一直是开发要求。可加日志便于排查，但不降级 | — | 已关闭 |
| **Q-D1-2** | `bucket_pack` 是否登记进 `provides` / `loom_module_has` 并**版本化导出名**（现在 hasattr=True 但能力查询返回 0，官方件契约自相矛盾） | **A（已实现）**：版本化导出 `loom_bucket_pack_v1` + `provides`/`loom_module_has` 登记；`Loom/ckernels/loom_kernels.c:384`、`Loom/tests/test_bucket_pack.py:148-167`（⑧）；登记记录 `research_beta6_04_python_hotspots.md:709` | **A** | 已实现（主审暂定） |
| ~~Q-D1-3~~ | RenderMixin 对 ProfilerMixin 的隐式依赖 | **已裁决 A**：RenderMixin 内提供默认空实现（profiler 混入时覆盖） | — | 已关闭 |
| **Q-B1-1** | 资产解析失败后**保存场景**：现在会永久销毁 guid 引用（缺贴图/索引坏 → Ctrl+S 后 albedo/env_map 整键消失、天空盒被替换成默认纯色新 guid） | **A（已实现）**：解析失败保留失效引用、保存原样写回；`Loom/sceneio.py:282,1237,1302`；`Loom/tests/test_asset_guid.py:509-565`（A/B/C 段）覆盖 | **A** | 已实现（主审暂定） |
| **Q-B1-2** | 资产索引里**一条坏条目**：现在整个 `load_index` 返回 None（整本作废）+ `for_dir` 丢掉 create 参数 → asset_import 永久失败、asset_list 谎报缺文件 | **A（已实现）**：坏条目剔除 + 告警，索引整体仍可用；`Loom/loom_assets.py:356,415,637`；`Loom/tests/test_asset_guid.py:568-594`（P1-2）覆盖 | **A** | 已实现（主审暂定） |
| ~~Q-B1-3~~ | 材质真相源 | **已裁决 A（2026-11-10）**：只认 `assets.json`，场景 `materials[]` 降级为引用；**直接做干净迁移不留尾巴**（内测期没有用户，正是做干净的时候）；落地见计划 §9.15 | — | 已关闭 |
| **Q-C1-1** | SoA 批量把**常量通道**写成 plain tuple（`(2,5,3)`）→ `.x` 读取点 AttributeError（编辑器/存盘/脚本链会崩）；触发=轮子/风扇/平移平台这类正常片段 | **A（已实现）**：常量通道统一写 `Point3D`；`Loom/loom_components.py:959-977`；`Loom/tests/test_animation_base.py:685-736`（P-01） | **A** | 已实现（主审暂定） |
| **Q-C1-2** | `once` + 负相位（speed<0 或负 dt）：批量路径外推（y=-25 且永真播放），`sample(-t)` 取模回绕（y=7.5）→ 同函数两路径语义分叉 | **A（已实现）**：once + 负相位夹到 [0,dur] 并停播；`Loom/loom_components.py:873-892`；`Loom/tests/test_animation_base.py:738-766`（P-02） | **A** | 已实现（主审暂定） |
| **Q-C1-3** | 物理不可用时 D6「动画只驱动 kinematic」把动画整条跳过 → 物体 120 帧位姿不变 =「动画永久不动」 | **A（已实现）**：物理不可用回退动画驱动；`Loom/loom_components.py:836-841,928-933`；`Loom/tests/test_animation_base.py:836-848`（P-06）与 `1068`（V-11） | **A** | 已实现（主审暂定） |
| **U-01** | P-06 修复引入**双写者**：回退动画驱动后 legacy 物理仍写同一批动态刚体，实测偏移 0.098/帧线性增长（需一次 GL 播放会话采样确认真实幅度） | **A（已实现）**：物理侧按 `fallback_models` 掩码排除本帧动画驱动体；`Loom/loom_physics.py:496-519`；`Loom/tests/test_animation_base.py:954-980`（V-08） | **A**（按此执行） | 已实现（主审暂定） |
| **U-02** | 嵌套 ndarray（list/tuple 内嵌）破坏 undo 值隔离+同内容判不等；NaN speed 静默冻结——真实可达性缺少发布级脚本证据 | **A（已实现）**：容器递归规范化 + 深拷，NaN/非法 speed 降级；`Loom/loom_components.py:370-424,846-865`；`Loom/tests/test_animation_base.py:935-944`（V-05）、`1072-1108`（V-12） | **A**（按此执行） | 已实现（主审暂定） |
| **U-03** | `dur == 0` 的 once 负相位漂移（与 seek 不一致） | **A（已实现）**：dur==0 once 与 seek 同构（夹 0 停播）；`Loom/loom_components.py:881-889`；`Loom/tests/test_animation_base.py:922-930`（V-04） | **A**（按此执行） | 已实现（主审暂定） |
| **U-01（R6-03）** | `tools/dist/Loom-0.1.0.beta6-source.zip`（07:35）内 SCENE_VERSION=10、无版本闸、meta 仍写 beta6 —— **陈旧包被误发布就是 P1** | A 删除并发布前重建（**已删除**）／ B 保留 | **A**（已执行） | 已关闭 |
| ~~U-02（R6-03）~~ | `min_engine_version` 非法值 | **已裁决 B**：拒绝加载（坏字段 = 数据损坏，与「失败必须可见」一致） | — | 已关闭 |
| ~~U-03（R6-03）~~ | 版本信任基 | **已裁决**：本版只做「meta 与 build_info 一致性」轻量校验；签名/构建身份绑定留独立版本 | — | 已关闭 |
| ~~Q-R6A-1~~ | v11 对 beta5 兼容 | **已裁决 A**：接受单向不兼容，发布说明写明「beta6 场景不能用 beta5 打开」；已落盘 `tools/release_notes/engine-0.1.0.beta6.md:6-12` | — | 已关闭 |
| **Q-R6A-2** | `asset_import` 去重只看指纹命中，**不校验正文是否存在**（重导入缺文件仍 created=False，resolve 仍失败） | **A（已实现）**：去重前校验正文，缺失按同 guid 重写 `created=True`；`Loom/loom_assets.py:933`；`Loom/tests/test_asset_guid.py:1047-1064` 覆盖 | **A**（按此修） | 已实现（主审暂定） |
| **Q-R6A-3** | 并发写索引：现在先加载后写，两进程会确定性丢条目（实测 2 条只剩 1） | **A（已实现）**：写前重新加载并按 guid 合并；`Loom/loom_assets.py:466`；`Loom/tests/test_asset_guid.py:998-1031` 覆盖 | **A**（按此修，锁作为后续） | 已实现（主审暂定） |
| ~~Q-SCN-1~~ | 示例场景 `PacMan2D` 的"地板"铺满整个正交视口（30×30 vs ortho_size=13），导致默认蓝天看不见 | **已关闭（B，计划 §9.9 Q6）**：不改示例场景（属场景内容，不是引擎缺陷）；另见 `handoff/开发日志_LoomHub0.1.3_Loom0.1.0.beta5_20261109.md:86` | — | 已关闭 |

> **编号说明（2026-11-13 加）**：`U-01/U-02/U-03` 在**两个批次**里各出现一次——动画/物理批（本表上方）与 R6-03 发布批（本表下方，带 `（R6-03）` 后缀）。引用时必须带批次后缀写成 `U-01` 或 `U-01（R6-03）`，否则会指错条。**不重编号**（会打断既有文档引用）。
>
> **2026-11-13 收口核对**：A 组已无「待答 / 主审暂定（未落地）」行。`已关闭` = 有人类裁决记录（指向计划 §9.x 或本文件原记录）；`已实现（主审暂定）` = 主审暂定方案已落地且有代码或受跟踪测试证据，但尚未由人类追认。逐条证据见 `docs/audit/doc_closeout_20261113.md`。

## B. 已关闭（不再需要回答，留痕备查）

| # | 问题 | 结论 |
|---|---|---|
| C-1 | `ab_gl_vk` 闸门语义 | **承诺是「画面不回归」**：基线存参考图、三向比对（GL↔参考、VK↔参考、GL↔VK） |
| C-2 | 无 Vulkan 机器上 ab 测试 | 默认 **FAIL**；仅 `LOOM_AB_ALLOW_NO_VK=1` 显式允许 SKIP |
| C-3 | R06 报告的 `MAE 0.0021/0.2353/0.9741` | **作废**（旧口径/其它制品读数）；以受跟踪测试 8.2e-5/0.1255 为准 |
| C-4 | 构建档位 | dev 带控制台（`force`）／ release 不带（`disable`）；发布产物必须来自 release |
| C-5 | VK 地板 | 文档化 wgpu-native 地板（当前 1.1），与 GL 4.3 并列；VK 不兼容 → 可见失败 + 写配置 + 立即 GL |
| C-6 | 3.13 迁移 | 已裁决接受，批次 D 需补回 FPS（门槛待 Q-PERF-1 定） |

## C. 不需要裁决、照常推进的操作（正在/待做）

- A-02 四项修复（参考图三向比对、缺基线 FAIL、VK 失败 FAIL+白名单、update-baseline 有 FAIL 不写、NCC float64、基线来源哈希、UI 覆盖）
- A-01 三项修复（仅 GL 且 <4.3 要可见失败、VK 诊断字段改名适配、建窗后失败关窗、P3 文案/重复前缀）
- A-03 的 P2/P3：断言加"文件大小/关键 .pyd 清单"、`PYGAME_MIN_DLLS` 加余量、指南 §7.5 补 `--output-filename=Loom.exe`
- R06：`build_engine.py --mode dev|release` + dist 自洽（ckernels/ckernels 断言）+ 编译版 bench 复现
- 清掉 `Loom/%SystemDrive%` 与 `Loom/~` 垃圾目录（路线登记 N-12，P0 卫生项）
