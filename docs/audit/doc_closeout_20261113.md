# 文档收口报告 · beta6 §D（2026-11-13）

> 执行者：文档收口员（子代理）。基线：`HEAD=50bc81a`（开工时工作树干净；执行中另一实现者正在做 T3a-3，工作树已变脏，见 §5.1）。
> **本报告全部为静态证据**（`read` / `grep` / `git ls-files` / `Get-FileHash` / 版本查询），**未运行引擎、未跑测试、未构建**。
> 本次只改 `docs/`，未改任何 `.py` / `Loom/` 实现文件，未 `git add` / `git commit`。

## 0. 结论速览

| 项 | 结果 |
|---|---|
| **D-1 待裁决清单状态列** | ✅ 33 行逐条核对；**A 组已无「待答 / 主审暂定（未落地）」**：5 条按人类裁决改「已关闭」，13 条按代码/测试证据改「已实现（主审暂定）」；全部同行写证据 |
| **D-2 裁决可检索性** | ✅ 覆盖表见 §2；发现 **7 类缺口**，其中 4 类已补指针（§9.9 裸 Q1–Q9 ↔ Q-xxx 的断链是最大风险），3 类（Q-HUB-2 无测试、路线登记 N-13/N-08 过期、U-01 重号）留主审 |
| **D-3 `_tmp` 夹具** | ✅ 传闻**属实**：`git ls-files Loom/tests/_tmp` = **24 个**；**没有任何受跟踪测试读取其中任何夹具**；目录本身不能删（两个测试会写入） |
| **D-4 一次性探针** | ✅ 二选一结论：`shadow_pcf_spike.py` → **删除**；`shader_spike.py` → **升格为受跟踪测试**（文件未删、测试未改，留主审执行） |

---

## 1. D-1 待裁决清单状态列校正（`docs/design/待裁决清单_beta6.md`）

### 1.1 改法约定

> 上一轮 `7ca66c3` 只关了 7 条（Q-PKG-1/2/3、Q-VK-1/2、Q-PERF-1、Q-HUB-1），其余行的状态列一直滞后。本轮新增关闭/落地 **18 条**（5 已关闭 + 13 已实现）。

- 有人类裁决记录 → 标 `已关闭`，并在同一行写「计划 §9.x / 原记录」。
- 只有主审暂定但**代码/受跟踪测试已落地** → 标 `已实现（主审暂定）`（不冒充人类裁决）。
- 找不到证据 → 不动。**本次没有出现找不到证据的行**。

### 1.2 逐行改动（行号为改后行号）

| 行 | 编号 | 新状态 | 证据（同一行已写入） |
|---|---|---|---|
| 10 | Q-PKG-1 | 已关闭（补 §9.9 Q1 指针） | 计划 §9.9 Q1；`tools/package_engine.py:383-388`、`research_beta6_06_toolchain_upgrade.md:450-458` |
| 11 | Q-PKG-2 | 已关闭（补 §9.9 Q2 指针） | `LoomHub/hub_config.py:862-868`（包内 python 权威） |
| 12 | Q-PKG-3 | 已关闭（补 §9.9 Q4 指针） | `tools/package_engine.py:420-441`（bat 双形态） |
| 13 | Q-VK-1 | 已关闭（补 §9.9 Q7/§9.3 指针） | `Loom/tests/test_backend_fallback_policy.py:171-185` |
| 14 | Q-VK-2 | 已关闭（补 §9.9 Q8/§9.3 指针） | `Loom/tests/test_backend_fallback_policy.py:491-503` |
| 15 | Q-PERF-1 | 已关闭（补 §9.10/§9.16 指针） | 计划 §9.10（重测 90/78）、§9.16（性能下降可接受） |
| 17 | **Q-HUB-2** | **待答 → 已关闭（A，§9.9 Q3）** | `tools/package_engine.py:383-388` 版本不一致拒绝出包；负向实测 `research_beta6_06_toolchain_upgrade.md:458` |
| 18 | **Q-HUB-3** | **待答 → 已关闭（B，§9.9 Q5）** | `LoomHub/hub_config.py:697-703`（直接读 `sys.version_info`，冻结态返回 None、不拉子进程）；`Loom/tests/test_hub_python_version.py:351-386` |
| 20 | **Q-PKG-4** | **主审暂定 → 已实现（主审暂定）** | `tools/package_engine.py:614,650-654,718-719`（`--kind` 分名）；`Loom/tests/test_release_version.py:110-113` |
| 21 | **Q-VIS-1** | **待答 → 已关闭（B→A，§9.13/§9.14）** | 调参 exposure=1.70/bloom 0.70 后接受；`Loom/tests/test_post_bloom.py:72`（≥+5%，实测 +22.1%） |
| 22 | **Q-VER-1** | **待答 → 已关闭（A，§9.18）** | `Loom/run_player.py:265,401`、`Loom/scene_driver.py:620-627`；`Loom/tests/test_scene_version_player.py:1-5,123-136` |
| 23 | **Q-VER-2** | **主审暂定 → 已实现（主审暂定）** | `tools/build_engine.py:141-159`、`tools/package_engine.py:114-128`（缺/版本不符即失败） |
| 25 | **Q-D1-2** | **主审暂定 → 已实现（主审暂定）** | `Loom/ckernels/loom_kernels.c:384`（`loom_bucket_pack_v1`）；`Loom/tests/test_bucket_pack.py:148-167`（⑧ provides/has/版本化）；登记 `research_beta6_04_python_hotspots.md:709` |
| 27 | **Q-B1-1** | **主审暂定 → 已实现（主审暂定）** | `Loom/sceneio.py:282,1237,1302`；`Loom/tests/test_asset_guid.py:509-565`（A/B/C 段） |
| 28 | **Q-B1-2** | **主审暂定 → 已实现（主审暂定）** | `Loom/loom_assets.py:356,415,637`；`Loom/tests/test_asset_guid.py:568-594`（P1-2） |
| 29 | Q-B1-3 | 已关闭（补 §9.15 指针） | 计划 §9.15（v12 材质只写引用） |
| 30 | **Q-C1-1** | **主审暂定 → 已实现（主审暂定）** | `Loom/loom_components.py:959-977`；`Loom/tests/test_animation_base.py:685-736`（P-01） |
| 31 | **Q-C1-2** | **主审暂定 → 已实现（主审暂定）** | `Loom/loom_components.py:873-892`；`Loom/tests/test_animation_base.py:738-766`（P-02） |
| 32 | **Q-C1-3** | **主审暂定 → 已实现（主审暂定）** | `Loom/loom_components.py:836-841,928-933`；`Loom/tests/test_animation_base.py:836-848`（P-06）、`:1068`（V-11） |
| 33 | **U-01** | **主审暂定 → 已实现（主审暂定）** | `Loom/loom_physics.py:496-519`（掩码排除）；`Loom/tests/test_animation_base.py:954-980`（V-08） |
| 34 | **U-02** | **主审暂定 → 已实现（主审暂定）** | `Loom/loom_components.py:370-424`（容器递归规范化/深拷）、`:846-865`（NaN speed 降级）；`Loom/tests/test_animation_base.py:935-944`（V-05）、`:1072-1108`（V-12） |
| 35 | **U-03** | **主审暂定 → 已实现（主审暂定）** | `Loom/loom_components.py:881-889`；`Loom/tests/test_animation_base.py:922-930`（V-04） |
| 39 | Q-R6A-1 | 已关闭（补发布说明位置） | `tools/release_notes/engine-0.1.0.beta6.md:6-12` |
| 40 | **Q-R6A-2** | **主审暂定 → 已实现（主审暂定）** | `Loom/loom_assets.py:933`；`Loom/tests/test_asset_guid.py:1047-1064` |
| 41 | **Q-R6A-3** | **主审暂定 → 已实现（主审暂定）** | `Loom/loom_assets.py:466`；`Loom/tests/test_asset_guid.py:998-1031` |
| 42 | **Q-SCN-1** | **待答 → 已关闭（B，§9.9 Q6）** | 不改示例场景（场景内容，非引擎缺陷）；旁证 `docs/handoff/开发日志_LoomHub0.1.3_Loom0.1.0.beta5_20261109.md:86` |

**未改的行**：A 表其余行原本就是 `已关闭`，只补了可检索指针（Q-PKG-1/2/3、Q-VK-1/2、Q-PERF-1、Q-B1-3、Q-R6A-1）。`§B` 的 C-1～C-6 原本已关闭，未动。

### 1.3 重要口径

- **Q-HUB-2 没有常驻测试**：只有代码硬门 + 研究文档里的负向实测（`LOOM_PYEMBED_DIR=Python312` + meta=3.13.15 → exit 1）。按「代码或测试有证据」判为可关闭；如果主审要求回归级覆盖，应补一条打包负例测试（见 §5 G-2）。
- **Q-VIS-1 的裁决是「先 B 调参、后 A 接受」两段**（§9.13 与 §9.14），不是一次拍板；行内已写明 B→A。
- **Q-SCN-1 的人类裁决与「主审建议 A」相反**（人类选 B 不改场景）。原表状态列一直写「待答」，是典型的「已裁决但没回写」。

---

## 2. D-2 遗留裁决可检索性覆盖表

### 2.1 待裁决清单里的 Q-xxx / U-xx（33 条）

| 编号 | 裁决结论 | 落盘位置（可检索） | 风险 |
|---|---|---|---|
| Q-PKG-1 | A：跟随 `解释器.json` 的 3.13.15 | 待裁决:10；计划 §9.9 Q1；research_06:450-458；package_engine:383-388 | 低 |
| Q-PKG-2 | A：包内解释器权威 | 待裁决:11；计划 §9.9 Q2；hub_config:862-868 | 低 |
| Q-PKG-3 | B：Loom.bat 双形态 + README | 待裁决:12；计划 §9.9 Q4；package_engine:420-441 | 低 |
| Q-VK-1 | A：显式 `--backend vulkan` 失败不改写配置 | 待裁决:13；计划 §9.9 Q7/§9.3；test_backend_fallback_policy:171-185 | 低 |
| Q-VK-2 | A：回退只写用户层 `游戏设置.json` | 待裁决:14；计划 §9.9 Q8/§9.3；同测试:491-503 | 低 |
| Q-PERF-1 | 3.13 性能下降可接受，FPS≥85 非硬门 | 待裁决:15；计划 §9.10/§9.16 | 低 |
| Q-HUB-1 | 包内权威（与 Q-PKG-2 同口径） | 待裁决:16；hub_config:862-868；test_hub_python_version | 低 |
| Q-HUB-2 | A：embed 版本不一致拒绝出包（发布硬门） | 待裁决:17；**计划 §9.9 Q3**；package_engine:383-388；research_06:458 | 中（无测试） |
| Q-HUB-3 | B：冻结版读 `sys.version_info`，不拉子进程 | 待裁决:18；**计划 §9.9 Q5**；hub_config:697-703；test_hub_python_version:351-386 | 低 |
| Q-REQ-1 | A：requirements 补 culverin/game-audio，提示 3.13 | 待裁决:19；计划 §9.12；requirements.txt:12-13 | 低 |
| Q-PKG-4 | A：source/compiled 分名 | 待裁决:20；package_engine:614,650-654,718-719；test_release_version:110-113 | 低 |
| Q-VIS-1 | B 调参 → A 接受新基线 | 待裁决:21；计划 §9.13/§9.14；test_post_bloom:72 | 低 |
| Q-VER-1 | A：弹窗+原因+优雅退出 | 待裁决:22；计划 §9.18；run_player:265,401；scene_driver:620-627；test_scene_version_player | 低 |
| Q-VER-2 | A：打包带 `解释器.json` 并断言 | 待裁决:23；build_engine:141-159；package_engine:114-128 | 低 |
| Q-D1-1 | A：C 返回非 0 保持硬 raise | 待裁决:24；接手须知 §4 硬纪律 2 | 低 |
| Q-D1-2 | A：`loom_bucket_pack_v1` + provides 登记 | 待裁决:25；research_04:709；loom_kernels.c:384；test_bucket_pack:148-167 | 低 |
| Q-D1-3 | A：RenderMixin 提供默认空实现 | 待裁决:26 | 低 |
| Q-B1-1 | A：保留失效引用 + 持续告警 | 待裁决:27；sceneio:282,1237,1302；test_asset_guid:509-565 | 低 |
| Q-B1-2 | A：坏条目剔除 + 告警 | 待裁决:28；loom_assets:356,415,637；test_asset_guid:568-594 | 低 |
| Q-B1-3 | A：材质只认 `assets.json` | 待裁决:29；计划 §9.15 | 低 |
| Q-C1-1 | A：常量通道统一 Point3D | 待裁决:30；loom_components:959-977；test_animation_base:685-736 | 低 |
| Q-C1-2 | A：once 负相位夹 [0,dur] | 待裁决:31；loom_components:873-892；test_animation_base:738-766 | 低 |
| Q-C1-3 | A：物理不可用回退动画驱动 | 待裁决:32；loom_components:836-841,928-933；test_animation_base:836-848 | 低 |
| U-01 | A：物理掩码排除动画驱动体 | 待裁决:33；loom_physics:496-519；test_animation_base:954-980 | 低 |
| U-02 | A：容器递归规范化/深拷 + NaN speed | 待裁决:34；loom_components:370-424,846-865；test_animation_base:935-944,1072-1108 | 低 |
| U-03 | A：dur==0 夹 0 停播 | 待裁决:35；loom_components:881-889；test_animation_base:922-930 | 低 |
| U-01(R6-03) | A：删除陈旧 source 包 | 待裁决:36（ID 与 U-01 重名，见 §5） | 低（编号冲突） |
| U-02(R6-03) | B：`min_engine_version` 非法值拒绝加载 | 待裁决:37；sceneio:157；test_animation_base:1159-1185 | 低（编号冲突） |
| U-03(R6-03) | 版本信任基：只做 meta/build_info 一致性，签名留后续 | 待裁决:38 | 低（编号冲突） |
| Q-R6A-1 | A：接受 v12 单向不兼容 | 待裁决:39；release_notes:6-12 | 低 |
| Q-R6A-2 | A：去重前校验正文存在 | 待裁决:40；loom_assets:933；test_asset_guid:1047-1064 | 低 |
| Q-R6A-3 | A：写前重载并按 guid 合并 | 待裁决:41；loom_assets:466；test_asset_guid:998-1031 | 低 |
| Q-SCN-1 | **B：不改 PacMan2D 场景** | 待裁决:42；计划 §9.9 Q6；开发日志 beta5:86 | 低 |

**结论**：33 条全部有落盘位置，**不存在「只活在对话里」的 Q-xxx**。风险集中在「落盘位置用了另一套编号」而不是「没写」。

### 2.2 计划 §9 各节裁决 → 落盘位置

| 小节 | 裁决/结论 | 落盘位置 |
|---|---|---|
| §9.2 | VK 地板 = wgpu-native 最低 1.1 + `require_vk_backend` | 计划:217-221；路线登记 N-13:45；loom_backend_guard.py:177；test_backend_fallback_policy:405-480 |
| §9.3 | VK 不兼容：可见失败 + 只写用户层 + 立即 GL | 计划:224-233；test_backend_fallback_policy:145-206,491-503 |
| §9.4 | 保留 3.13.15 主线，接受性能代价 | 计划:236-242；research_06:388-393 |
| §9.5 | 构建档位 dev=force / release=disable | 计划:245-249；build_engine.py `--mode`；待裁决 C-4:52 |
| §9.6 | 3.13 退化根因 = 跨线程 GIL 交接 | 计划:252-269；research_04 |
| §9.7 | 性能测量纪律（空闲/交替/线程表） | 计划:272-288；接手须知 §3 |
| §9.8 | 第三轮复核 A-02/A-03 修复口径 | 计划:291-309；待裁决 C-3:51 |
| §9.9 | Q1–Q9 集中裁决 | **计划:312-325 只有裸 Q1–Q9**；映射见本报告 §2.1（已由 D-1 在待裁决行补指针） |
| §9.10 | 3.12 vs 3.13 空闲重测 90/78 | 计划:327-343 |
| §9.11 | 批次 A 2A 验收（MAE=0 的诚实口径） | 计划:345-363；test_frame_plan.py |
| §9.12 | Q-REQ-1 = A | 计划:365-367；requirements.txt:12-13 |
| §9.13/§9.14 | Q-VIS-1 = B 调参后 A 接受 | 计划:369-399；test_post_bloom.py:72 |
| §9.14b/§9.14c | 夹具密闭化 / 三向门自证边界 | 计划:401-421；test_ab_gl_vk:29-60 |
| §9.15 | B1 资产管线验收（v12 / 打包带资产） | 计划:423-434；test_asset_guid |
| §9.16 | 性能下降可接受；FPS≥85 非硬门 | 计划:436-443；Q-PERF-1 行（已补指针） |
| §9.17 | D1 复测：C 打包 +19%，95 FPS | 计划:445-459 |
| §9.18 | Q-VER-1=A；批次 D 继续；beta6 暂不收尾 | 计划:461-467；run_player/scene_driver/test_scene_version_player |
| §9.19 | 全量回归单实例 | 计划:469-473；接手须知 §4 |
| §9.20 | 安装版复测中位 90 | 计划:475-488 |
| §9.21 | F-01：抽象化未达成（14.3%） | 计划:490-509 |
| §9.22 | beta6 继续打磨；B7-13 上调必做 | 计划:511-519；路线登记 B7-13:26 |
| §9.23 | F-02 骨架验收 8/1/1 | 计划:521-535 |
| §9.24 | V-01 推翻「VK 已由 FramePlan 驱动」 | 计划:537-558 |
| §9.25 | 倒查总账（含包落后 4 提交） | 计划:560-580 |
| §9.26 | 门序首次全绿（包=代码证据） | 计划:582-597 |
| §9.27 | goal_01：VK 真遍历 + 装饰字段清理 | 计划:599-626 |
| §9.28 | F2-02：语义面未达成（11.5/9.5） | 计划:629-664 |
| §9.29 | 目标重新定义提案（待裁决） | 计划:666-675 |
| §9.30 | 最终交付状态 | 计划:678-690 |
| §9.31 | T1/T2/T3 正式替代目标 + T3 实现约定 | 计划:692-719；T3 接手须知 §2/§5 |
| §9.32 | T3c-4：GL 改 9-tap 手工比较 | 计划:721-735；T3 接手须知:20,84 |

### 2.3 缺口（按严重度）

| # | 缺口 | 影响 | 本次处理 |
|---|---|---|---|
| **G-1** | **§9.9 用裸 `Q1`–`Q9`，与 Q-xxx / Q-HUB-2 等编号无交叉引用**；且 `Q2` 在 `scan_beta6_round5_03` 里又指 Q-D1-2（另一个问题） | 搜 `Q-HUB-2` 在计划里 0 命中，只能靠人记住「Q3 就是 Q-HUB-2」 | ✅ 已在待裁决行写「计划 §9.9 Q3/Q5/…」反向桥接；建议后续把 §9.9 表加一列 `编号`（本轮未改计划正文） |
| **G-2** | Q-HUB-2 的硬门**没有常驻测试** | 打包器回退时无人报警 | 已在行内注明；建议补打包负例（`LOOM_PYEMBED_DIR` 版本错配 → exit 1） |
| **G-3** | Q-VK-1/2 的实质政策只在 §9.3，§9.3 不含编号 | 搜 Q-VK-1 找不到 §9.3 | ✅ 已补指针 |
| **G-4** | §9.16（性能可接受）是独立小节，Q-PERF-1 行原无指针 | 搜 Q-PERF-1 找不到「FPS≥85 非硬门」的裁决 | ✅ 已补指针 |
| **G-5** | 路线登记 **N-13 仍写「待做」**（实际已实现并有测试）、**N-08 仍写「待做」**（清单 B9 已写「已闭合」） | 下一任会重复做/误判未做 | ❌ 未改（超出 §D 四条，且属路线登记维护）；见 §5.4 |
| **G-6** | 待裁决清单 **U-01 编号重复**（line 33 与 line 36 都叫 U-01，后者靠 `(R6-03)` 区分） | 搜 U-01 命中两条不同问题 | ❌ 未改（改名会破坏既有引用）；建议下一版改 `R6A-U01` |
| **G-7** | 接手须知 Q-D1-1 行原引「流程§5」，但 `开发流程_冒烟与验证分层.md` §5 与 Q-D1-1 无关 | 断链 | ✅ 已改为「本文件 §4 硬纪律 2」 |

---

## 3. D-3 `Loom/tests/_tmp` 受跟踪夹具盘点

### 3.1 数量核实

```
$ git ls-files Loom/tests/_tmp | Measure-Object -Line
24
```

**传闻 24 个属实。** 这 24 个是 `Loom/.gitignore:21-41` 用 `!tests/_tmp/...` 白名单强行保留的；目录里另有大量**未跟踪且被忽略**的日志/探针（`git check-ignore` 命中 `Loom/.gitignore:22 tests/_tmp/*`），例如 `final_runall*.log`、`goal_02_*.py`、`pcf_*.png`。

### 3.2 引用关系（静态 grep，排除文件自身）

| # | 夹具 | 使用者（文件:行） | 能否清理 | 原因 |
|---|---|---|---|---|
| 1 | `ab_active_gl_vk.py` | 仅 `docs/design/research_beta6_01_render_pass.md:82` | ⚠️ 可删（先归档引用） | 无测试/代码 import；文档只是历史引用 |
| 2 | `ab_batch.py` | `docs/audit/_fix_summary.md:79` 等历史审计；被 `ab_gl_vk.py` 间接使用 | ⚠️ 成组删 | 旧 A/B 批量入口，已被 `tests/test_ab_gl_vk.py` 取代 |
| 3 | `ab_gl_vk.py` | `ab_batch.py:29`（import）；旧审计大量引用 | ⚠️ 成组删 | 现受跟踪像素门是 `tests/test_ab_gl_vk.py`，不依赖本文件 |
| 4 | `ab_gl_vk_ui.py` | `docs/audit/fix_r_vk_stroke.md:39,98-100` 等 | ⚠️ 成组删 | 同上；UI 已被 `test_ab_gl_vk` 的 `__ui` 子项覆盖 |
| 5 | `ab_scene.json` | `ab_gl_vk.py:150-151`、`probe_vk_smoke.py:7`、`ab_batch` glob | ⚠️ 成组删 | 仅旧探针默认场景；`tests/ab_scenes/ab_scene.json` 是当前夹具 |
| 6 | `ab_ui_scene.json` | `ab_gl_vk_ui.py:223-225`、`probe_vk_ui_smoke.py:7` | ⚠️ 成组删 | 同上；且它是 `ui_tex_rgba.png` 的唯一引用者（:405） |
| 7 | `cam_align_probe.py` | `docs/audit/_fix_summary.md:83` | ⚠️ 可删（先归档） | 一次性相机对齐取证 |
| 8 | `checker.png` | 无代码引用；仅 `research_beta6_02:389` 作为「绝对路径」证据 | ✅ 可删 | `tests/ab_scenes/assets/tex/checker.png` 由 `make_assets.py` 确定性生成（哈希不同） |
| 9 | `e2e_mcp_full.py` | `docs/handoff/接手总纲:51,214`、`audit/e2e_mcp_summary.md:4` | ⚠️ 不能直接删 | MCP 40/40 的**唯一**复现脚本；删了证据链断。建议先升格/归档再删 |
| 10-15 | `env_0.png` … `env_5.png` | **无**（`ab_env.json:26-31` 指向 `assets/env/env_N.png`，是另一套文件） | ✅ 可删 | 完全无引用；当前夹具由 `make_assets.py` 生成 |
| 16 | `normalmap.png` | **无**（`ab_nrm.json:24` 指向 `assets/tex/normalmap.png`） | ✅ 可删 | 同上（哈希不同） |
| 17 | `probe_bucket_reorder.py` | `docs/audit/fix_vk_render_batch.md:45,253,266`、`_fix_summary:82` | ⚠️ 可删（先归档） | 桶重排 P1 的一次性复现探针 |
| 18 | `probe_vk_smoke.py` | **无**（且 :7 写死本机绝对路径） | ✅ 可删 | 无任何引用；路径不可移植 |
| 19 | `probe_vk_ui_smoke.py` | **无**（:7 同样写死绝对路径） | ✅ 可删 | 同上 |
| 20 | `ui_lines_scene.json` | 仅注释：`Loom/vk_ui.py:49`、`tests/test_vk_ui_stroke.py:12`；审计数字 `fix_vk_render_batch:210`、`fix_r_vk_stroke:44,98` | ❌ 不能单删 | 受跟踪测试**不加载**它，但两处注释与审计数字拿它当复现源；删前先把注释改成「历史数据，夹具已删」 |
| 21 | `ui_lines_alpha_scene.json` | 仅注释：`vk_ui.py:49`、`test_vk_ui_stroke.py:12`；审计 `fix_vk_render_batch:211`、`fix_r_vk_stroke:45,99` | ❌ 不能单删 | 同上 |
| 22 | `ui_tex_rgba.png` | 仅 `_tmp/ab_ui_scene.json:405` | ⚠️ 成组删 | 与 #6 同生共死；`ab_scenes/assets/tex/ui_tex_rgba.png` 已有生成版 |
| 23 | `ui_world_scene.json` | 仅 `verify_world_ui_depth.py:32` | ⚠️ 成组删 | 与 #24 同生共死 |
| 24 | `verify_world_ui_depth.py` | 仅自身（无外部引用） | ⚠️ 成组删 | 一次性 world-UI 深度取证 |

### 3.3 关键结论

1. **没有任何受跟踪测试读取这 24 个夹具**。`Loom/tests/run_all.py:28-30` 只收集 `tests/test_*.py`（`test_integration.py` 最后），不会执行 `_tmp` 下的脚本；`test_ab_gl_vk.py:49` 的夹具目录是 `tests/ab_scenes`。
2. **目录本身不能删**：`Loom/tests/test_eai_real.py:100-101` 与 `Loom/tests/test_integration.py:74-75` 会 `os.makedirs(TMP)` 并往 `tests/_tmp` 写运行产物。清理只能清**文件**，不能 `rm -rf _tmp`。
3. **成组删除清单**（若主审决定清）：#2/#3/#4/#5/#6/#22 一组；#23/#24 一组；#10-16、#18、#19 可单独删；#9/#17/#1/#7 先归档/升格；#20/#21 先改注释。
4. `Loom/.gitignore:21-41` 的白名单要从 24 行缩到剩余项，否则删掉的文件会被重新 add。**本次未改 .gitignore**。

---

## 4. D-4 一次性探针处置

### 4.1 `tools/shadow_pcf_spike.py` → **删除**

**它验证什么**（文件 :2-8）：GL 旧实现 = 9 次 `sampler2DShadow` 硬件比较（LINEAR，硬件 2×2 双线性）；候选① = 原始深度 + 手工比较（= VK 算法）。探针把阴影贴图 filter 从 LINEAR 改 NEAREST，量化两者像素差。

**结论是否已被常驻测试覆盖：是（以最终行为计）**

| 依据 | 位置 |
|---|---|
| 人类裁决①「都改手工比较」已执行：GL 阴影改 `compare_mode=NONE`+`NEAREST`，`pcf_shadow()` 改 9 次原始深度采样 + 显式比较 | `docs/design/版本计划_Loom0.1.0.beta6_20261109.md:721-730`（§9.32） |
| 代价（边缘 ≤3e-5 软化）已留档 | 同 §9.32:730；T3 接手须知 `:20,84` |
| 最终画面由受跟踪像素门三向把关（GL/参考、VK/参考、GL/VK，含 `ab_c_dir_shadow`、`ab_point_shadow`，阈值 2e-4） | `Loom/tests/test_ab_gl_vk.py:4-11,62-68`；23/23 PASS 见 §9.32:729 |
| 生产实现位置（T3a-3 后） | `Loom/shaders/main.frag:75-100`（`pcf_shadow`/`pcf_shadow_cube`）；迁移前在 `Loom/loom_shaders.py` 同名函数 |

**为什么删而不是升格**：

- 探针比较的是「硬件双线性比较 vs 最近邻比较」这个**已废弃候选**；生产已经不用硬件比较，复跑不再测生产路径。
- 它每次运行会改 GPU 纹理 filter、并往 `tests/_tmp` 写 6 张 `pcf_*.png`（:66,88-92），这些 png 已被 gitignore，无消费者。
- 它的唯一量化结论（≤3e-5）已在两处文档留档，删除不丢结论。

**给主审的执行项**：删除 `tools/shadow_pcf_spike.py`（仅此一个文件）；无需改测试。若想保留「≤3e-5」的可复跑证据，可把 `test_ab_gl_vk` 的 `mae_abs` 从 2e-4 收紧到 1e-4（不建议本轮做）。

### 4.2 `tools/shader_spike.py` → **升格为受跟踪测试**

**它验证什么**（:2-6,25-76）：5 个 case 走 `glslang -V` → 读 SPIR-V → `wgpu.create_shader_module` → `create_render_pipeline`：
1. `shadow2d`（`texture2D`+`samplerShadow`，BGL `sample_type='depth'`/`'comparison'`）
2. `shadowcube`（`textureCube`+`samplerShadow`）
3. `cube`（普通 cube 采样器）
4. `inst_attr`（两条 instance 顶点属性）
5. `multi_sampler`（2D shadow + 2D + cube 同管）

**结论是否已被常驻测试覆盖：否（静态证据）**

- `grep shader_spike` 仅命中自身与未完项清单，**无任何测试引用**。
- `grep samplerShadow Loom` → **0 命中**；`sampler2DShadow` 仅 1 处（`Loom/tests/test_integration.py:556` 的无关着色器字符串）。**当前宏层已不走比较采样器**：`Loom/shaders/loom_shader_compat.glsl:44-52` 用 `texture(sampler2D(...))` / `texelFetch`（手工比较），故 spike 的 case 1/2 是历史选型（当时方案）。
- `tools/build_shaders.py:85-115` 只做 glslang 编译 + 文件大小检查，**从不创建 wgpu shader module / render pipeline** → 不覆盖 naga 的接受面。
- `§9.31` 的「T3 实现约定」表（计划:711-719）是**文档结论**，不可执行。
- `test_ab_gl_vk` 的 VK 路径会用已迁移的 SPIR-V 建管线：在 `HEAD=50bc81a` 时只有 main.vert + post 链（case 3/4 的分离 sampler/实例属性已端到端覆盖）；`main.frag` 仍是 `.wip`，所以 case 1/2/5 的阴影 sampler 模式当时无覆盖。
- 结论不依赖「比较采样器是否还会用」：spike 的 5 个 case 是 naga 接受面的**能力矩阵**，即使当前生产改用 texelFetch 手工比较，保留它也能防止未来换回比较采样器时踩同一个坑。
- ⚠️ **执行中变化（2026-11-13 13:06）**：另一实现者已把 `main.frag` 迁入并生成 `main.frag.spv`、改 `vk_renderer.py`（未提交）。若该改动落地且 `test_ab_gl_vk` 的 VK 阴影场景跑绿，则 case 1/2/5 会获得端到端覆盖；**在未验证前，仍按「无覆盖」处置**。

**建议的升格形态**（本次不写）：

```
Loom/tests/test_shader_spv_naga.py
  · 复用 tools/shader_spike.py 的 5 个 case（去掉打印，改成 check()/退出码）
  · 固定 py -3.13 + wgpu 0.33；无 GPU/无 Vulkan 时按现有约定 FAIL（LOOM_AB_ALLOW_NO_VK 不适用，这是能力测试）
  · 纳入 run_all.py（文件名前缀 test_）
```

**为什么不直接删**：它是 T3 选型（源语言 GLSL、分离采样器、naga 接受面）的**唯一可执行证据**；虽然当前实现已改用 `texelFetch` 手工比较，矩阵仍固化了「哪些 GLSL/SPIR-V 写法 naga 收、哪些不收」的边界。wgpu/glslang 升级后若 naga 改变接受面，`build_shaders` 仍会绿，但 VK 管线会在运行时才炸。升格能以秒级成本把这条边界钉住；若主审确认 T3a-3 后 ab 门已端到端覆盖全部生产写法，也可改判删除（届时以本报告 §4.2 的 grep 证据失效为准）。

---

## 5. 另外发现的文档不一致（宁可多列）

| # | 不一致 | 证据 | 建议 |
|---|---|---|---|
| 5.1 | **工作树在我执行期间变脏**：开工时 `git status` 干净；13:06 起另一实现者在做 T3a-3（`Loom/loom_shaders.py`、`vk_renderer.py`、`build_shaders.py` 修改；`main.frag.wip` 删除、`main.frag` 新增） | `git status --porcelain`：十余个 M/D + 3 个 ??（随后我改了多个 docs/） | 本报告所有 `Loom/` 行号以 2026-11-11 稳定文件为准；T3 相关结论待其提交后复核 |
| 5.2 | **HEAD pin 全过期**：T3 接手须知 `:3` 写 `1086640`；beta6 接手须知 `:4` 写「已到 `7ca66c3` 之后」；实际 `50bc81a` | `git rev-parse HEAD` | 已有一份写「HEAD 以 `git log -1` 为准」，建议 T3 那份也改成不钉 SHA |
| 5.3 | **requirements.txt 的 wgpu 下界是 0.32**，而 T3 结论依赖 0.33 | `requirements.txt:8` `wgpu>=0.32`；`research_beta6_06:390` 写 0.33.0；实测 `py -3.13` → 0.33.0、裸 `python` → 0.32.0 | 建议改 `wgpu>=0.33`（本次仅报告，不改依赖文件） |
| 5.4 | **路线登记 N-13/N-08 过期**：写「待做」，实际 N-13 已实现并有 44→51 项测试；N-08 已被清单 B9 判「已闭合」 | `路线登记_后续版本.md:40,45` vs `loom_backend_guard.py:177`、`test_backend_fallback_policy.py:405-480`、`beta6未完项清单:44` | 下一轮把 N-13/N-08 状态回写 |
| 5.5 | **待裁决清单 U-01 重号**：line 33 的「双写者」与 line 36 的「陈旧 source 包」都叫 U-01 | `待裁决清单_beta6.md:33,36` | 后者已有 `(R6-03)` 后缀，建议正式改 `R6A-U01` |
| 5.6 | **§10 插在 §9.1 与 §9.2 之间**：计划 `:208` 是 §10，`:215` 才是 §9.2 | `版本计划…md:208-215` | 结构问题，不改内容只调序即可（风险低） |
| 5.7 | **「流程§5」断链**已修（见 G-7） | `接手须知_beta6:81` | — |
| 5.8 | **开发日志的测试数过期**：「121 个测试文件」，当前 `run_all` 收集的是 135 个 | `开发日志…:138`；`ls Loom/tests/test_*.py` = 135 | 历史日志可不改，但在「命令速查」处加「数字以当次运行为准」 |
| 5.9 | **docs/README 描述不全**：line 4 写「A/B/C/D/F」漏 E 组；line 10 写「6 个待裁决问题」而 §6 是 D1–D9 | `docs/README.md:4,10` | ✅ 已修（补 E 组；改「9 条架构决策 D1–D9」） |
| 5.10 | **build_all.bat 是 3.12 时代脚本**：内部 `py -3.12` 且调用 `tests/_tmp` 下大量**已被 gitignore 的探针**，干净 clone 必失败 | `Loom/build_all.bat:8,64,69,163` | 建议标注「历史脚本，勿用」或删除；它不是当前四道门 |
| 5.11 | **解释器事实已核对**：`Loom/解释器.json:4` = 3.13.15 ✅；`Loom/Loom.py:1` shebang = `python3.13` ✅；裸 `python` = 3.12.10/wgpu 0.32.0，`py -3.13` = 3.13.15/wgpu 0.33.0 ✅ | 实测命令见 §7 | 只有 requirements 的 0.32 下界不一致（5.3） |

---

## 6. 本次改动清单

| 文件 | 改动 |
|---|---|
| `docs/README.md` | 修 D 组漏写 E、计划「6 个待裁决问题」→「9 条架构决策（D1–D9）」 |
| `docs/design/待裁决清单_beta6.md` | 33 行核对；5 行改「已关闭」、13 行改「已实现（主审暂定）」、8 行补可检索指针；表后加 2026-11-13 核对说明 |
| `docs/handoff/beta6未完项清单_20261111.md` | §D D1–D4 全部标 ✅ 并写明结果/报告指针；§F 四道门命令改 `py -3.13` + `LOOM_NO_DIALOG=1` + 修正 `cd Loom` 重复 |
| `docs/handoff/接手须知_beta6当前状态_20261111.md` | §3 命令改 `py -3.13` + env；§7 新增第 9 条「解释器必须 3.13」；修 Q-D1-1 断链 |
| `docs/handoff/接手须知_T3着色器单源化_20261111.md` | §4 命令改 `py -3.13` + env；§5.1 加解释器警告；§7 命令改 `py -3.13` |
| `docs/handoff/开发日志_LoomHub0.1.3_Loom0.1.0.beta5_20261109.md` | §8 命令改 `py -3.13` + env（历史日志，按主审要求统一命令） |
| `docs/design/开发流程_冒烟与验证分层.md` | §5 增加 2026-11-13 探针处置表（D-4 结论落盘） |
| `docs/audit/doc_closeout_20261113.md` | 本报告 |

**未改**：所有 `.py`、`Loom/` 实现、`tools/` 探针、`Loom/tests/`、`.gitignore`；未删任何文件；未 `git add/commit`。

---

## 7. 环境事实（本次实测，供报告核对）

```
python --version                      -> Python 3.12.10
python -c "import wgpu; ..."          -> wgpu 0.32.0
py -3.13 --version                    -> Python 3.13.15
py -3.13 -c "import wgpu; ..."        -> wgpu 0.33.0
py -3.13 -c "import moderngl; ..."    -> moderngl 5.13.0
Loom/Loom.py:1                        -> #! python3.13
Loom/解释器.json:4                     -> "python_version": "3.13.15"
requirements.txt:8                    -> wgpu>=0.32
```

---

## 8. 留给主审的动作（按顺序）

1. 复核 D-1 的 13 条「已实现（主审暂定）」——尤其 **Q-HUB-2 无测试**、**U-01/U-02 与 (R6-03) 重号**；确认后可把「（主审暂定）」去掉或追加人类追认。
2. 处置 D-4：删 `tools/shadow_pcf_spike.py`；把 `tools/shader_spike.py` 的 5 个 case 升格为 `Loom/tests/test_shader_spv_naga.py`（建议在 T3a-3 提交后做，避免与在途改动冲突）。
3. 处置 D-3：按 §3.3 的成组清单清理；**不要删目录**；同步缩 `Loom/.gitignore:21-41` 白名单。
4. 回写路线登记 N-13/N-08（§5.4），以及计划 §9.9 的编号列（G-1）。
5. 若同意 5.3，改 `requirements.txt:8` 为 `wgpu>=0.33`（本次未动）。
