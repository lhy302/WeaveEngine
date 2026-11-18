# beta6 待裁决清单（人类：集中回答，不打断执行）

> 规则（2026-11-09 人类指示）：**所有需要人类拍板的问题先缓存到本文件**；等没有子代理/后台任务在跑时**一次性提出、一次性回答**。
> 不需要裁决的操作照常推进。每项打 `待答` / `主审暂定（可推翻）` / `已实现（主审暂定）` / `已关闭`。**2026-11-13 核对：A 组当前无待答项**；历史条目全部已关闭或已实现（证据见各行与 `docs/archive/v0.1.0-beta6/doc_closeout_20261113.md`）。

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
> **2026-11-13 收口核对**：A 组已无「待答 / 主审暂定（未落地）」行。`已关闭` = 有人类裁决记录（指向计划 §9.x 或本文件原记录）；`已实现（主审暂定）` = 主审暂定方案已落地且有代码或受跟踪测试证据，但尚未由人类追认。逐条证据见 `docs/archive/v0.1.0-beta6/doc_closeout_20261113.md`。

### A2. 2026-11-13 T2 差异清单裁决（3 条，均已关闭）

| 编号 | 问题 | 裁决结论 | 状态 |
|---|---|---|---|
| **Q-T2-1** | **mip 生成是否允许长期双实现**？GL 走驱动 `glGenerateMipmap`，VK 走 `shaders/mip_downsample.frag` 逐级降采样，两条算法不可能逐像素相等 | **已关闭（A）**：接受为「合理差异」+ **场景级容差**，但必须有能真正暴露它的探针。落地：原 D-06 → **R-03**；新增 `ab_mip_minify`（301×301 非 2 的幂 + 强缩小），实测 GL/VK MAE **5.8264e-4**，基线行 `mae_abs=1e-3`（余量 4.174e-4）；**全局 2e-4 与 GL/参考门不变**。证据：`Loom/tests/test_ab_gl_vk.py` 25/25、`docs/design/T2差异清单_beta6.md` R-03 | 已关闭 |
| **Q-T2-2** | **「绘制源实现体」算不算不共享**？`buckets`/`skybox`/`world_canvas` 的语义面（名字/顺序/存在性）已由 FramePlan 共享，执行体天然两份 | **已关闭（不算）**：降级为「实现细节」，从 D 组移到 **I-01**（不入清单）；语义面已有 `test_frame_plan_vk` 7 类反例覆盖。证据：`docs/design/T2差异清单_beta6.md` §2.1 | 已关闭 |
| **Q-PAR-1** | **UI 描边 GL/VK 的 1px 覆盖差要不要接受**？GL 描边走 `GL_LINES`，VK 用三角带近似（`vk_ui.py` R2 契约 `STROKE_PIXEL_EQUIVALENT=False`）；`ab_ui_only` 首次把它测出来：`[UI] MAE=2.726e-3`，差异像素 **0.87%**，**100% 在高梯度边缘 1px 内、块状内部 0 个**。选项：A 接受并登记；B 两端都改三角带（重写 GL 描边，回归面大） | **已关闭（A）**：接受为「合理差异」→ 登记 **R-04**（D-05 的视觉后果），门控用**仓库既有** `ui_mae_abs=5e-3`（本轮未改，2e-4 只是主图门；`ab_ui_only` 主图 0/0/0）。若将来两端都走三角带，D-05 与 R-04 同时消失 | 已关闭 |

> 三条均已裁决，清单已按结论更新：原「6 条不共享 + 2 条合理差异」→ **4 条不共享（D-01/D-03/D-04/D-05）+ 4 条合理差异（R-01/R-02/R-03/R-04）+ 1 条实现细节（I-01，不入清单）**。

## A-b7. beta7 新增待裁决（2026-11-17）

| # | 问题 | 选项 / 建议 | 影响 | 状态 |
|---|---|---|---|---|
| **Q-B7-24-1** | **B7-24 四类划分**（A 脚本会用 / B 有等价物只是形态不同 / C 后端宿主专属 / D 内部助手）与「A 37 条必须进 `IEngineAPI`」这条边界，认可吗？重点看：`toggle_logic_paused`、`get_tps`、`world_scale`、`world_to_local` 判 A（脚本会用）；`compute_world_matrices`、`world_rotation_matrix` 判 D（内部） | 建议认可 A 边界；认为某条不该进就移到 C/D，我按裁决改表 | 决定契约正文多大 | **已关闭（2026-11-17 人类裁决：认可 A 边界）**：A 40 条（v2 口径，含 3 个鼠标属性）必须进契约；C 20 / D 12 排除；见 `docs/design/契约_IEngineAPI_20261117.md` §3/§6/§7；已关闭 |
| **Q-B7-24-2** | **属性面要不要进契约**：GL 有 4 个公开属性（`mouse_locked`/`mouse_lock_allowed`/`mouse_unlock_requested`/`render_api_current`），VK 有 `camera_pos` 等 property。当前矩阵门口径 v1 **不含属性**（历史 105/38/77 就是这口径） | **建议 A：要进**。否则「API 对齐了但脚本读状态仍 AttributeError」。代价：口径升 v2，GL 109 / VK 39 / GL-only 80，历史数字需重新登记留痕 | 契约覆盖面 | **已关闭（2026-11-17 人类裁决：要进）**：口径升 v2（含普通类属性）→ GL 109 / VK 39 / 共同 29 / GL 独有 80 / VK 独有 10；门已升级并复验有牙；已关闭 |
| **Q-B7-24-3** | **C 类 20 条「仅 GL 可用」怎么声明**：(a) 契约列「仅 GL」表 + VK 侧访问时显式抛 `NotSupportedOnBackend`；(b) 只写文档不抛 | **建议 (a)**：显式失败优于静默不存在 | VK 下脚本错误可见性 | **已关闭（2026-11-17 人类裁决：(a)）**：VK 下访问仅 GL 的 API 必须抛 `NotSupportedOnBackend`（显式失败优于静默不存在）；契约 §6 给出异常类型与文本模板；已关闭 |
| **Q-B7-24-4** | **批 0 是否拆两段**：原估 4-6 人天是粗估；看清后 A 37 + B 18 条要落实现，4-6 装不下（对照 B7-20 门面收敛单独 5-8）。建议 **0a = 契约正文 + 矩阵门 + C/D 排除声明（3-4 人天）**，**0b = A/B 55 条落地（估 8-12 人天，并入批 1）** | **建议拆**：0a 一完成，后面每批都有「照哪张表写」的依据 | beta7 总账 46-72 需重算 | **已关闭（2026-11-17 人类裁决：拆）**：0a = 契约正文 + 门升级 + C/D 声明（3-4 人天，已交付）；0b = A 40 + B 15 条落地（估 8-12 人天，并入批 1）；B7-24 总估 4-6 → **11-16 人天**；已关闭 |

| **Q-B7-24-5** | **B 类 15 条「形态统一」往哪边统一**：VK 的 `step`/`render_pose`/`load_from_data`/`camera_pos`/`apply_dev_camera_mouse` 与 GL 的 `advance_logic`/`render`/`load_scene`/`camera_world_position`/`apply_orbit_camera` 是同一件事两种形态 | **主审暂定（可推翻）：以 GL 形态为契约形态**。理由：编辑器只有 GL 一条腿、beta7 零新功能（改 GL 形态=语义变更）、存量内容按 GL 写、VK 侧只有 7 条要改。逐条落法见契约 §4.3 | 决定 0b 的 15 条改哪一侧 | **主审暂定（可推翻）** |

| **Q-B7-26-1** | **VK 的碰撞对从哪来**：(A) 抽 GL 那套配对管线（SAP + C 内核）成共享模块，两端都调；(B) 用 VK 的 Jolt 桥接触对 | **主审建议 A**。B 会让「有没有 culverin」变成看不见的行为开关（culverin 缺失时 VK 无碰撞事件、GL 仍有），且 Jolt「接触」与 GL「AABB 相交」语义不同，事件序列无法逐条对拍 | 决定 B7-26 的 3-4.5 人天怎么花 | **已关闭（2026-11-17 人类裁决：按主审建议 A）**：抽 `Loom/loom_collision.py` 共享配对/判重/派发，GL 与 VK 调同一份；已落地并过「配对集合对拍」门；已关闭 |
| **Q-B7-26-2** | **B7-26 里「抽共享配对模块」那 1-1.5 天记在哪个条目名下**：B7-26 还是 B7-20（门面收敛）？ | **主审建议记 B7-20**（它是门面收敛的第一块），B7-26 只记「VK 补 3 段 + 对拍门」 | 影响两笔账的口径（总数不变） | **已关闭（2026-11-17 人类裁决：按主审建议）**：抽共享模块的工时记 **B7-20** 名下，B7-26 只记「VK 补 3 段 + 对拍门」；已关闭 |

| **Q-B7-28-1** | **收敛形状选哪个**（人类 2026-11-17 已定方向「不受后端影响 / JVM 模型」，但**形状没定**）：**(A)** `GLEngine` 为唯一门面、`SceneDriver` 降为内部后端驱动（估 5-8，不动编辑器）；**(B)** 抽中立内核 `EngineCore`，两宿主都只做「宿主+后端」（估 12-18，最干净但动编辑器链路）；**(A→B)** 先 A 后 B | **主审建议 A→B**：A 做完用户层就已「不受后端影响」，B 只是内部更干净；beta7 定位是扫尾，B 更适合 beta8 | 决定 S1~S4 的 14-23 人天怎么排 | **已关闭（2026-11-17 人类裁决：B）**：抽中立内核 `EngineCore`，两宿主都只做「宿主+后端」。人类理由：「beta7本来就是针对工程问题的扫尾，这种其实也属于工程问题，属于之前一直遗留的失误，必须清掉。」已落地 S2-1/S1/S2-3（见 `docs/audit/impl_S1S2_单一引擎门面_20261117.md`）；已关闭 |

> **2026-11-17 路线偏差留痕**：B7-24 之后我按「逐条补 VK 的 40 条」推进，人类指出这偏了 —— 目标是「用户只看到一个引擎、一套事件 API，后端被屏蔽」，不是「两端方法名一样」。纠正方案与分步见 `docs/design/设计_单一引擎门面_后端下沉_20261117.md`；已做的 B7-18/B7-21/B7-26 不作废（真缺陷修复），B7-24 的矩阵门降级为「差异可见化仪表盘」。

| **Q-B7-29-1** | **Hub 侧两件事**：① `test_hub_update.py` **打印 FAIL 却退出码 0**（`run_all` 从未抓到，HEAD 上即如此，已 `git stash` 验证）；② `is_program_files('C:\Program Files\LoomHub')` 返回 **False**（应为 True）→ 装到 Program Files 时**不加 `/ALLUSERS`、不触发 UAC** | **主审建议**：两项都归 **Hub 0.1.5**（本次不修，属 Hub 侧）；①的机制**未核**（有 `sys.exit(1)` + fail-gate 却退 0，不猜） | 影响 Hub 安装权限语义与回归可信度 | **待答** |

| **Q-B7-30-1** | **独立审查判定「未达标」**（2026-11-17，未参与实现的子代理）：三道门全绿但判据被证伪 —— F9/F10/F11/Tab 在 VK 上无效、`key_state` 两套键空间、`vk_player` 未接 `handle_key_event`、14 条 API 在 VK 仍 AttributeError | **主审建议**：本轮已修 P0-5/P0-6/P0-4/c4/`is_playing`（一整类 AttributeError 已消灭）；**P0-2/P0-3（键空间重构 + vk_player 接入）单独立项**，估 2-3 人天；其余 a1~a14 估 3-5 人天 | 决定「两后端合并」能否在 beta7 收口 | **部分执行后回退（2026-11-18）**：P0-3/P0-2 尝试一次，3 个测试文件变红（`test_unlock_key` / `test_render_api` / `test_vk_camera_align` + `test_beta3_batch2`），已整批 `git checkout` 回退，基线 clean。根因：`script_keys` 有 4 个写者（GLFW 泵/editor 帧头/外部 ctx/测试夹具），不是一次 P0 补丁能改的。失败点与下次两步走法见 `docs/audit/scan_P0-3键空间_P0-2接入_20261118.md`；**已推进（2026-11-18）**：按文档两步走法完成 —— 步 1 `32c9cee`（key_state 键码化，两端 is_key/get_action 同一份）、步 2 `76220e9`（script_keys 收敛 + `vk_player.host_key_forward` 接统一入口 + 新门 `test_input_chain_parity`）。lead 独立验收通过（`docs/audit/verify_P0-3步2_验收_20261118.md`）：6 条门全绿、run_all 177.5s、独立探针 5 组全绿。**遗留**：GL 泵每帧写 key_state（行为变化已留痕）、VK 播放器 F9/F10/F11 未真窗口点验；已关闭（有条件） |

| **Q-B7-31-1** | **用户 API 等价是否已达标**：9 条用户 API 已收进 `EngineCore`（同一函数对象），两端共同公开成员 **97**，GL 独有 15 / VK 独有 10（全部登记为后端内部并写明理由） | **主审判定：达标**（`test_user_api_parity` 8 条断言全绿 + lead 独立探针 9 条功能全绿 + 对象身份全 True）。剩余「后端内部」25 条按设计不该是用户 API | 决定 S4 能否收口 | **已关闭（达标）** |
| **Q-B7-31-2** | 子代理报告「VK 的 `clear_scene`/`load_scene` 不派发脚本 `on_destroy`」，建议留待裁决 | **主审判定：不留，已补** —— 这是用户可观察的副作用差异（脚本生命周期钩子），按「两端 API 一样」的要求必须一致。修法：`remove_model` 收进 `EngineCore`（子树递归 + on_destroy），删掉两端各自的副本 | 影响脚本在 VK 上的生命周期语义 | **已关闭（已修）** |

| **Q-B7-32-1** | **VK 播放器 F11 全屏缺失**（真窗口实测：`allow_fullscreen` 属性不存在 → 内核第①步直接跳过，按键被静默忽略；GL 有） | **主审建议：单独立项，不在本轮硬做** —— VK 窗口由 rendercanvas 管理，切 monitor 会重建 surface/交换链，可能把刚修好的 VK 播放器再打挂。需要：`EngineCore.allow_fullscreen` 默认值 + VK 侧 `_toggle_fullscreen` 窗口实现 + 回归 | 用户按 F11 在 VK 下无反应（GL 正常） | **已关闭（2026-11-18 裁决 ①，已实现 `4f46189`）**：新增 `Loom/loom_vk_window.py`（`VkWindowMixin`，全私有成员 → 不进用户 API 面）；`SceneDriver.allow_fullscreen=True`；三步语义与 GL 同序同常量（去边框/铺桌面/置顶）；**退出真还原**。前置探针 12 项全 PASS（深度/后处理 size-keyed 自动重建；阴影/实例/几何/管线与尺寸无关）。真窗口修前红（F11 完全无反应）→ 修后绿（DECORATED 1→0、640x400→1920x1080、pos→(0,0)、TOPMOST False→True，退出全还原）。**但发现 GL 侧两个既有缺陷，见 Q-B7-36-1/2**；已关闭 |
| **Q-B7-32-2** | **性能门禁在机器负载下假红**：`test_aabb_simd` 报 `ratio=0.92`（阈值 0.90），但单独连跑 3 次全过、`ratio` 稳定 **0.80** | **主审建议：门改成「预热 + 取 5 次中位数 + 同机基线」** —— 现在的单次采样在负载下必然假红，会训练人「忽略性能门」 | 影响回归可信度 | **待答** |

| ~~Q-B7-33-1~~ | **宿主输入是否统一到内核**（含 IME 文本路径）：现在键盘走「宿主先喂 UI + 内核跳过第③步」，文本走 `ui_bridge.on_text`；GL 则是「内核第③步派发 + `handle_text_input`」 | **已裁决 B（2026-11-18，人类原话：「两个后端暴露给用户的 API 都是一样的……类似于 JVM 虚拟机」）**：键盘与 IME 文本两条路径全部收进内核 —— `vk_player.host_key_forward` 只把 ev 递给 `handle_key_event`、`_on_char` 只把 ev 递给 `handle_text_input`；宿主预喂 UI 与「内核跳过第③步」的双写者标志已删除。行为门 `test_input_chain_parity` 106 PASS（⑥/⑥b 断言「同一个 UI 每按一次只派发 1 次」原样保留，另有新造变异实测变红） | 输入子系统一致性 | **已关闭（B，已实现）** |
| **Q-B7-33-2** | **门 `test_input_chain_parity` 的夹具失真**：`_FakeBridge` 与 `_FakeUI` 是两个对象，而生产里 `UIInputBridge.ui is driver.ui`（同一个 UIManager）→ 「同一 UIManager 被派发两次」这个真实风险该门测不到 | **主审建议：让 `_FakeBridge.ui is _FakeUI`，把「每按一次只派发 1 次」改成**行为断言**（数同一个 UI 的派发次数），去掉 `bridge.on_key 未被调用` 这种结构断言（违反 §7-1） | 门覆盖面 | 已修（2026-11-18，`10e593e`）：删掉 `_FakeBridge`，夹具直接用**生产那个类** `vk_ui.UIInputBridge(getattr(driver,"ui",None))`（与 `vk_player.run_vk()` 同式）；修前红（夹具改成包 None）→ 105 PASS/1 FAIL，还原后 106 PASS。真桥构造无副作用（只写 `__slots__` 字段）；已关闭 |
| **Q-B7-33-3** | **`test_aabb_simd` 性能门必抖**：审核实测空载 10 轮 `ratio` 中位数 **0.86**、最坏 **1.16**，阈值 0.90 只剩 ~12% 余量 | **主审建议：`reps≥200` + 交替 7 轮取中位数 + 阈值按实测重定（或改「与同机基线比」）**；光加中位数不够（中位数 0.86 仍会红） | 回归可信度 | **待答** |

| **Q-B7-34-1** | **①「夹具保真」断言守不到生产**（独立审核）：`test_input_chain_parity.py:418` 断言的是**假桥**包着假 UI；生产侧 `vk_player.py:360 UIInputBridge(getattr(driver,'ui',None))` 若改成包 `None`，该断言照样绿。且该桥在键/文本路径上已无调用方，这条断言基本空转 | **主审建议**：改成构造**真** `UIInputBridge(driver.ui)` 再断言 `bridge.ui is driver.ui`（断言生产构造式，而不是假桥自身） | 门覆盖面 | **已修（2026-11-18，`10e593e`）**：删掉 `_FakeBridge`，夹具直接用**生产那个类** `vk_ui.UIInputBridge(getattr(driver,"ui",None))`（与 `vk_player.run_vk()` 同式）；修前红（夹具改成包 None）→ 105 PASS/1 FAIL，还原后 106 PASS。真桥构造无副作用（只写 `__slots__` 字段）；已关闭 |
| **Q-B7-34-2** | **③ 性能门有一条静默假绿通道**（独立审核实测）：`test_aabb_simd.py:251` 用**被测对象自己**的 `fastpath.aabbs_simd_impl()` 决定要不要跑两个加速门；若探测本身坏掉（AVX2 机器上恒报 0），两门**整段跳过** → `ALL PASS / exit 0`，只剩一行 SKIP。实测变异 `simd_impl_reports_0` → 全绿 | **主审建议**：另取**独立判据**（CPUID / `ckernels` 导出信息 / 编译期常量）；本机确证支持 AVX2 而 `aabbs_simd_impl()` 报 0 → **FAIL（不是 SKIP）**，理由行写「探测坏了，不是机器不支持」 | 门可信度 | 已修（2026-11-18，`10e593e`）：独立判据改为 `kernel32!IsProcessorFeaturePresent(PF_AVX2_INSTRUCTIONS_AVAILABLE=40)`（不经过本 DLL，探测坏掉不连带）；「支持但 impl≠1」→ **FAIL**（不再 SKIP）；`LOOM_NO_SIMD=1` 归入合法 SKIP。修前红（变异 `simd_impl_reports_0` → 原代码 ALL PASS 假绿）→ 修后 FAIL 并贴理由；已关闭 |
| **Q-B7-34-3** | **② 未完全执行裁决**（独立审核）：Q-33-1=B 字面要求「`ui_bridge` 只留鼠标/滚轮」，实际 `vk_ui.py:827 on_key / :833 on_text / :913 dispatch_key / :921 dispatch_text` 全部保留。真实原因（提交信息未写）：`Loom/tests/test_vk_ui_input.py:162-177` 用它们做 UI 层对拍 | **主审建议（二选一）**：**(a)** 删掉 4 个方法 + 同步改 `test_vk_ui_input.py`；**(b)** 保留但在本清单登记「偏离裁决」+ 补一条静态断言「`vk_ui.UIInputBridge.on_key/on_text` 无生产调用方」。否则将来任何宿主直调 = 绕过内核的第二个 UI 写者，而门抓不到 | 输入子系统一致性 | **已修（方案 b，2026-11-18，实施子代理）**：四个方法（`on_key` / `on_text` / `dispatch_key` / `dispatch_text`）全保留 —— `dispatch_key`/`dispatch_text` 是 `test_vk_ui_input` 第 1) 段 UI 层对拍的对照物，删掉就得整段重写且失去桥这一层的对照；选 b 而非 a 的理由见下。偏离裁决的部分改为**静态断言**守住：`Loom/tests/test_vk_ui_input.py` 新增第 5) 段，用 `ast` 扫 `Loom/**.py`（排除 `tests/` 与 `vk_ui.py` 自身定义，实扫 **109** 个生产文件），断言生产代码里**没有任何** `.on_key(...)` / `.on_text(...)` 调用点，也没有 `getattr(x, 'on_key'\；'on_text')` 间接取用（只扫这两个名字：`dispatch_key`/`dispatch_text` 被内核第③步在 `engine_core.py:193/235` 对 UIManager 正当地调用，纯按名字扫会假红）。**修前红实测**：在 `vk_player.py:368` 临时插一行 `ui_bridge.on_key(0)` → `FAIL 静态断言: 生产代码无 UIInputBridge.on_key / on_text 调用方 … 命中 1 处: [('vk_player.py', 368, 'on_key')]`（33 PASS / 1 FAIL，exit 1）；删除后 34 PASS / 0 FAIL / exit 0。另附**扫描器自检**（把同一段直调写成临时样本必须被抓到），防止这条断言空转。选 b 而不选 a 的理由：a 只删方法、不补任何门，等于把「将来有人接回宿主直喂 UI」这条路彻底变成无人看守；b 保留了兼容面但把它钉死在静态断言上。 |
| **Q-B7-34-4** | **③ 余量口径未写清**：自报「留 24% / 42% 余量」用的是「阈值 ÷ 实测最坏 − 1」（1.05/0.841=1.249、0.65/0.457=1.422）；若按「实测距阈值的相对余量」则是 19.9% / 30%。数字可复现但口径含糊 | **主审建议**：把算法写进测试注释，后续调阈值才有可比性 | 可审计性 | 已修（2026-11-18，`10e593e`）：注释补明 VK 无 `allow_fullscreen` → F11 在 VK 仍空操作（Q-B7-32-1）；余量口径写清「阈值÷实测最坏−1」= 24.9%/42.2%，并注明另一种口径是 19.9%/30%；已关闭 |

| **Q-B7-35-1** | **②③ 逐位一致段仍以 `impl == 1` 决定是否做 avx2 对拍**（`test_aabb_simd.py:69/80/154`）：探测坏掉时那几段仍会静默跳过。本次只修了**性能门**（新增 FAIL 已让整条测试变红，不再是全绿假象），一致段未改 | **主审建议：把独立判据（`IsProcessorFeaturePresent`）复用到那几处**，让「支持却报 0」在一致段也 FAIL | 门可信度 | **已关闭（2026-11-18 裁决 A，已实现 `adcb2df`）**：抽 `_avx2_available()` + `_avx2_gate(impl)` 共用（全文件唯一实现）；②③ 与性能段共用同一判据；「独立判据说支持而 impl≠1」→ FAIL（不再 SKIP）；`LOOM_NO_SIMD=1` 归合法 SKIP。修前红（历史版 5475d1e + 变异恒报 0 → ②③ 静默跳过 + ALL PASS）→ 修后 FAIL 且 ②③ 照做对比；`np.array_equal` 10 处一行未动；已关闭 |

| **Q-B7-36-1** | **GL 退出全屏其实没还原**（VK 实机点验时发现）：`loom_glfw_window.py:248-255` 在 `set_window_size(全屏尺寸)` + `set_window_pos(0,0)` **之后**才在 `_place_fullscreen_window()` 里 `GetWindowRect` 存 `_window_rect` → 存的是**全屏后**的矩形；退出时 `w,h = self.window_size` 拿到的也是全屏尺寸 → 实测退出后是 **1920x1055 @ (0,0)**（原 640x400 @ (73,102)） | **主审建议：修 GL** —— 进入全屏**前**记录 `_window_rect` + 原 client 尺寸，退出时按记录还原。VK 侧已按正确语义实现，修完两端才真一致 | 两端窗口几何不一致 | **待答** |
| **Q-B7-36-2** | **GL 置顶在 x64 上静默失效**：`loom_glfw_window.py:288` `user32.SetWindowPos(hwnd, -1, ...)` **未声明 argtypes** → `HWND_TOPMOST(-1)` 被当 32 位 int 截断 → 返回 0（失败）、`WS_EX_TOPMOST` 从未置位；整段包在 `try/except pass` 里 → **完全不可见**。VK 侧用了私有 `ctypes.WinDLL('user32')` + 显式 argtypes，实测真置顶 | **主审建议：修 GL** —— 声明 argtypes（`c_void_p` 传 -1/-2），并去掉 `except: pass` 或至少打印一次 | GL 的「置顶」从未生效（用户可感知：全屏后仍会被其他窗口盖住） | **已关闭（2026-11-18 裁决 A，已实现 `2c615c3`）**：新增私有 `_user32()`（`ctypes.WinDLL` + 显式 argtypes）+ `c_void_p(-1)/(-2)`；失败改走 `_fullscreen_warn()` 打印一次（不再 `except: pass` 静默）。实测 `WS_EX_TOPMOST` 真置位（exstyle 262416→262168→262416）；已关闭 |

| **Q-B7-37-1** | **「两端无用户可感知差异」还差哪些面**（本轮把全屏做成对拍门后暴露的方法论问题）：目前**已有对拍门**的只有 全屏 / 事件面 / 输入链 / 用户 API 集合 / 逻辑帧段序 / 时钟传播 / beam 灯 / A/B 像素。**尚无对拍门**的面：① 鼠标锁定与光标捕获（有单测无两端对拍）② UI 命中与焦点（有单测）③ 场景加载/切换的用户可见结果 ④ 音频播放状态（有实现无对拍）⑤ 相机轨道/开发者视角 ⑥ 暂停/单步的**观感**（已有数值对拍但无窗口级） | **主审建议**：按「用户脚本能感知什么」逐面补对拍门，**优先级 = 用户脚本最常碰的**（③ 场景加载 → ① 鼠标锁定 → ② UI 命中） | 决定「JVM 式一致」的完成度口径 | **已排优先级（2026-11-18 人类：「继续一面一面补上」）**：P1 场景加载 → P2 鼠标锁定 → P3 UI 命中 → P4 音频 → P5 相机 → P6 暂停观感。**强制流程已落盘**：`docs/guides/开发要求_后端API一致_JVM模型.md` | 按面推进 | |

| **Q-B7-38-1** | **混合文件拆分排期**（人类 2026-11-18：「一个功能一个文件…全部解耦化对于开发有利」）：实测 `agent_commands.py` 4049 行 / **25 个顶层功能区块**、`sceneio.py` 2379 行 / **13 区块**、`editor.py` 2906 行 / 151 def。要求已落盘 `docs/guides/开发要求_功能解耦与模块化.md` | **主审建议拆序**：① `sceneio.py` 的版本迁移（= B7-16，已定）→ ② `sceneio.py` 其余按域拆（light/camera/sky/material/prefab）→ ③ `agent_commands.py` 按域拆 `eai/` 包 → ④ `editor.py` 先抽播放态与 gizmo。每次纯搬家 + run_all 全绿 | beta7 工作量会显著增加，需你定「拆到哪一层」 | **待答** |

| **Q-B7-39-1** | **R1（P2 门修前红）**：GL 暂停期 `mouse_rel` 逐帧继续结算（`loom_glfw_window._update_mouse_rel` 无 `logic_paused` 门控；`engine.py:1446-1459` 暂停分支不清 `mouse_rel`），VK 符合 B6「暂停不结算不累积」。实测 `GL=((250,105),(40,20)) VK=((250,105),(0,0))` | **主审建议：修 GL**（加暂停门控 + 清 `mouse_rel`），VK 是对的 | F9 暂停时脚本读 `mouse_rel`：GL 视角转 / VK 不转 | **已修（2026-11-18）**：`loom_glfw_window._update_mouse_rel` 加逻辑暂停门控（暂停期只推进 `_prev_cursor` 基线、不结算 `mouse_rel`）+ `engine.advance_logic` 暂停分支清 `mouse_rel=(0,0)`（与 `scene_driver.py:1059-1062` 逐行同语义）。门 `test_mouse_lock_parity.py` ⑤ 修前红原文 `暂停 feed(250,105): GL=((250,105),(40,20)) VK=((250,105),(0,0))` → 修后 37 条全绿（3 连跑稳定）。未改 VK |
| **Q-B7-39-2** | **F-1**：VK `set_mouse_locked`/`toggle_mouse_locked` 返回 **None**，GL 返回 True/False（GL docstring 明写「返回: True=已应用; False=被拒绝」）→ 脚本 `if engine.toggle_mouse_locked():` 两端走不同分支 | **主审建议：VK 补齐返回值**（与 GL 同语义） | 脚本分支不一致 | **已修（2026-11-18 `15e295e`）**：VK `set_mouse_locked` 补 `return not denied`、`toggle_mouse_locked` 两分支补 True/False、`_install_lock_policy_guard` 守卫分支 `return False`；门组⑨ 4 条锁住（含被拒那条），修前红实测 `GL=False VK=None` | 已关闭 |
| **Q-B7-39-3** | **F-2**：锁定中幂等 `set_mouse_locked(True)`（脚本每帧重申的常见写法）→ VK 下一帧 `mouse_rel=(0,0)` 断流一帧，GL 连续（根因：VK 每次调用都触发 `on_mouse_lock_changed` → `_apply_cursor_mode` 重置 `_prev`） | **主审建议：VK 状态未变时不触发回调** | 视角抖动（每帧重申锁定的脚本） | **已修（2026-11-18 `15e295e`）**：VK 状态未变时不触发 `on_mouse_lock_changed`（新增 `_lock_backend_applied`）；两个例外：后端未落地时必须触发、被拒请求仍转发一次（既有门 `test_beta3_batch2_camera_proj` 4c 钉住）。门组⑩ 3 条：连续 3 帧重申 `mouse_rel` 两端都 `[(10,5),(10,5),(10,5)]` | 已关闭 |
| **Q-B7-39-4** | **F-3**：F9 暂停期间按解锁键：VK 能解锁，GL **无人轮询**（GL 唯一轮询点 `update_scripts` 首行 `engine.py:995`，暂停时不执行） | **主审建议：修 GL**（暂停分支也要 poll 解锁键，与 VK 同） | 暂停时按解锁键：VK 能松、GL 不能 | **已修（2026-11-18）**：GL 三条暂停分支各 poll 一次（`engine.advance_logic` 暂停分支 / `loom_render.render` 暂停分支 = GLFW run() 主循环 / `loom_logic_thread` 暂停分支 = Qt 宿主异步播放态），按下沿判定保证同帧重复 poll 不翻两次。门 `test_mouse_lock_parity.py` 新增组⑦（修前红 `GL=(True,False,True) VK=(False,True,False)` → 修后两端都解锁）。未改 VK |
| **Q-B7-39-5** | **F-6**：`mouse_pos` 成员面 —— GL 有 `engine.mouse_pos`（int），VK `SceneDriver` **无此成员** → 脚本直读在 VK 上 AttributeError | **主审建议：按契约裁定它是否 ① 层用户 API**；若是则 VK 补成员（与 GL 同类型） | 脚本 `engine.mouse_pos` 在 VK 崩 | **已裁决（2026-11-18 人类）：「用户 API，VK端补全」** → `mouse_pos` 判为 ① 层用户 API，VK 必须补成员（类型与 GL 一致：int 像素坐标）；补完在 `test_mouse_lock_parity.py` 加断言锁两端同值。**待修（已排单）** |
| **Q-B7-39-6** | **F-7**：`set_mouse_lock_allowed` 两方向语义不齐：GL True→立即应用（锁）/ False→清 requested+解锁；VK True→**什么都不做**、False→只解锁**不清 requested** | **主审建议：VK 对齐 GL**（GL 侧已被 `test_unlock_key` I 段钉住） | 脚本切 allowed 后两端行为不同 | **已修（2026-11-18 `15e295e`）**：VK `set_mouse_lock_allowed` 与 `InputMixin:347-365` 逐行同语义（True→`_apply_mouse_lock()` 立即应用；False→清 requested + 解锁）。门组⑪ 3 条三元组逐项相等 | 已关闭 |

| **Q-B7-40-1** | **我们修完 VK 后，GL 打包播放器反而分叉了**（`agent-19` 留痕 §6.2）：`runtime.PlayerApp.set_mouse_locked`（GL **打包/播放器**路径）**仍 `return None`** 且被拒分支早退不落地后端；而 `GLEngine`（InputMixin）返回 True/False、VK `SceneDriver` 修后也返回 True/False → **打包游戏上 GL=None vs VK=True/False** | **主审建议：修 GL 的 `runtime.PlayerApp.set_mouse_locked`**（补返回值 + 被拒分支也对齐），否则 F-1 的修复在**用户实际发布的打包路径上没生效**，反而制造新分叉 | 打包游戏里 `if engine.set_mouse_locked(True):` 两端不同 | **已修（2026-11-18 `bb9083e`）**：`runtime.PlayerApp.set_mouse_locked` 改为**委托 `InputMixin.set_mouse_locked`**（`return super().set_mouse_locked(locked)`），旧私有实现整段删除（拒绝闸门/被拒先解锁/后端落地/状态变化才打日志 只剩 `loom_input.py:367-403` 一份）。实测三端返回值逐项相等（被拒 False/False/False；允许 True/True/True），且**被拒后 PlayerApp 现在真的释放光标捕获**（修前捕获位仍 True）。门组⑫ 10 条锁住 + 4 条结构锚点「不得再长出第二份实现」 | 已关闭 |

> 证据与逐条表：`docs/audit/impl_B7-24_API矩阵_20261117.md`（§3 全 77 条 / §4 VK 独有 10 条 / §6 这四个问题）。

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