# 编号 03 · beta6 四批目标达成度核对（最终验收审计 / 第七轮）

> 只读审计。除本文件与 `Loom/tests/_tmp/_final03_*`（已忽略）外未写入任何受跟踪文件。
> 基线 `08ad3a3`（beta5 发布点）→ HEAD `a0b0ae0`。所有判定 = 承诺条目 + 可复跑证据。

---

## 0. 范围与基线

### 0.1 提交范围（实测）

```
$ git diff --stat 08ad3a3..HEAD | Select-Object -Last 1
 197 files changed, 26283 insertions(+), 875 deletions(-)
$ git rev-parse HEAD
 a0b0ae088ae1cb63e852ae37d87566ec0c42de71
```

派单口径为 189 文件 / +23580 / −837；实测 197 / +26283 / −875 —— 差异来自本轮之前又有 3 个提交
（`1d1f8f6` R6-01 资产整改、`2fc26db` Hub 安装根、`a0b0ae0` 第六轮审计报告）。**以实测为准**。

### 0.2 批次与承诺来源

| 批次 | 承诺来源 | 落地位置 |
|---|---|---|
| 0 工具链 | `research_beta6_06` §2.1/§2.3/§③ + 计划 §7 批次0 | `tools/build_engine.py`(+318)、`build_game.py`(+156)、`package_engine.py`(+390) |
| 0.5 py3.13 | `research_beta6_05` §2.4 + 计划 §9.4/§9.9/§9.12 | `Loom/解释器.json`、三件产物、打包链 |
| A 渲染 | `research_beta6_01` §2.2/§2.4/§③(S0–S6) + 计划 §7 批次A、§9.11/§9.13/§9.14 | `loom_pass.py`(297)、`loom_pass_gl.py`(234)、`loom_post.py`(64)、`loom_post_gl.py`(204) |
| B 资产 | `research_beta6_02` §③(S0–S6) + 计划 §9.15 | `loom_assets.py`(905)、`sceneio.py`(+717)、`migrate_scene_assets_v11.py`(219) |
| C 动画 | `research_beta6_03` §③批次1(S1–S5)+出口判据 + 计划 §9.18 | `loom_components.py`(+520) 的 `evaluate_animations`、`sceneio.py`、`undo.py` |
| D 热点 | `research_beta6_04` §③ + 附录 F/G + 计划 §9.17 | `ckernels/loom_kernels.c`(+305)、`fastpath.py`(+114)、`physics_bridge.py`(+71) |

### 0.3 本轮实跑命令（全部可复现，工作目录 `Loom/`）

| 命令 | 实测输出（要点） |
|---|---|
| `py -3.13 tests/run_all.py` | **133 文件，FAIL 行 0，`全部测试完成 ✅`，exit 0**，PASS 断言 3933 行 |
| `py -3.13 tests/test_ab_gl_vk.py` | **场景 23 / 失败 0 / 跳过 0**；23 场景 GL↔参考 MAE 全 `0.000000` |
| `py -3.13 tests/test_frame_plan.py` | 49 PASS / 0 FAIL |
| `py -3.13 tests/test_animation_base.py` | 115 PASS；`500 动画物体: 旧逐物体 12.743 ms / 新批量 1.448 ms (8.8x)` |
| `py -3.13 tests/test_asset_guid.py` | 152 条 check，`总结果: ALL PASS` |
| `py -3.13 tests/test_bucket_pack.py` | 21 PASS（逐字节一致、v1 导出、provides 登记） |
| `py -3.13 tests/test_aabb_simd.py` | 6 PASS；`分派查询可用 (0=标量/1=AVX2) 1` |
| `py -3.13 tests/test_physics_pose_soa.py` | 10 PASS |
| `py -3.13 tests/test_scene_version_gates.py` | 12 PASS（A–G 七组，含 build_entry --run / 远程回读） |
| `py -3.13 tests/test_post_bloom.py` | 5 PASS；`晕圈: 0.3414 -> 0.4866  Δ=+0.1452 (+42.5%)` |
| `py -3.13 -m nuitka --version` / `pip list` | `4.3.5`；numpy 2.5.4 / moderngl 5.13.0 / PySide6 6.12.0 / wgpu 0.33.0 / glfw 2.11.0 / pygame 2.6.1 / pillow 13.0.0 / culverin 0.14.0 / game-audio 2.1.0 / numba 0.67.0 |

`git status --porcelain` 全程自查：除本文件外无受跟踪文件被改动（见 §3.4）。

---

## 1. 目标达成判定表

判定：✅ 达成（有可复跑证据）／◐ 部分达成（主路径达成但承诺子项缺）／❌ 未达（含人类已豁免）。
### 1.1 批次 0 · 工具链与依赖（14 项）

| # | 原定目标（出处） | 实际交付（证据） | 判定 |
|---|---|---|---|
| 0-1 | Step0 冻结基线 + 回滚四件套（R06 §③） | `pre_py313_freeze.txt` / `post_py313_freeze.txt` / `pre_upgrade_freeze_3.12.txt` / `engine\build_entry.dist.__py312` / `builder\build_game.exe.__py312` / `player_runtime\game_player.dist.__py312` 全部 `Test-Path=True` | ✅ |
| 0-2 | Step1 Nuitka 2.7.1→4.3.5 + 参数现代化 + pyside6 插件 + 断言（R06 §③Step1） | `py -3.13 -m nuitka --version` → `4.3.5`；`build_game.py` 已 `--mode`/`--windows-console-mode`；`tools/build_engine.py` 6 处档位/控制台分支 | ✅ |
| 0-3 | Step2 依赖整链升 stable（R06 §2.1） | pip 实测 numpy 2.5.4 / moderngl 5.13.0 / PySide6 6.12.0 / glfw 2.11.0 / pillow 13.0.0；pygame 2.6.1 不动（符合"无新版"） | ✅ |
| 0-4 | Step3 Python 3.13（R06 §③Step3） | 并入批次 0.5，见 1.2 | ✅ |
| 0-5 | Step4 VS2026 / MSVC 14.5x（R06 §③Step4，可选） | **未做**：R06 §2.2 明写"不在本轮升 VS2026"；计划 §9.9 "D 组…优先换新工具"未落排期；无任何 MSVC 14.5x 构建记录 | ❌ |
| 0-6 | G1 最小 standalone 可跑（R06 §2.3） | 附录 C/E 实测（`build_entry.dist` 142.3MB / `game_player` 140.4MB）；本轮未重编（≈9 分钟/件），以自测表为准 | ✅ |
| 0-7 | G2 `game_player` + `--build-runtime` 全链（同上） | 附录 C/E；`build_game.py` 修掉"`--build-runtime` 后续继续打包而 exit 1" | ✅ |
| 0-8 | G3 编辑器 dist 含 `qt-plugins/platforms/qwindows.dll` 且为构建断言（同上） | 附录 C 负向实测"用无插件 dist 打包 → exit 1"；`package_engine_compiled.py` 断言在链上 | ✅ |
| 0-9 | G4 全量测试全绿（R06 §2.3 记 121 个） | **本轮实跑 133 文件 / FAIL 0 / exit 0**（测试面 121→133，见 §3.1） | ✅ |
| 0-10 | G5 `ab_gl_vk` 不劣化 | 本轮 23/23 PASS、0 SKIP、GL↔参考 MAE 全 0；`ab_c_dir_shadow` VK/参考 0.000051 = 基线 | ✅ |
| 0-11 | G6 包体积 ≤+5%、启动 ≤+10% | 附录 C/D：zip +2.0%→−0.6%；启动 1.57→1.615→1.535s（+2.9%→−4.7%） | ✅ |
| 0-12 | 构建档位 dev/release + 发布硬门（计划 §9.5） | `tools/build_engine.py`（318 行，`--mode dev / release`）；`package_engine_compiled.py` 只接受 `mode=release`（负向 exit 1） | ✅ |
| 0-13 | 打包链 Q1/Q2/Q3/Q4（计划 §9.9） | Q1/Q3：`package_engine.py` 跟随 `解释器.json` 解析 embeddable + 两道版本硬门（负向 exit 1）；Q2：`hub_config.py:638-641,874` 包内权威；Q4：`package_engine.py:349-393` bat 双形态 + README 分形态 | ✅ |
| 0-14 | wgpu 每次升级须记录"Vulkan 地板是否变化"（计划 §9.2#3） | 只有终态单点记录（`架构互联协议总表.md:198` "Vulkan 地板 = 1.1"），**无 0.32→0.33 前后地板对比表**；wgpu 0.33.0 已在位 | ◐ |

**批次 0 完成率**：严格 12/14 = **85.7%**；加权（◐=0.5）**89.3%**。

### 1.2 批次 0.5 · Python 3.13（11 项）

| # | 原定目标（出处） | 实际交付（证据） | 判定 |
|---|---|---|---|
| 0.5-1 | 主线迁 3.13.15（计划 §9.4 裁决①） | `Loom/解释器.json` `"python_version": "3.13.15"`；`py -3.13 -c` → 3.13.15 | ✅ |
| 0.5-2 | 3.13 依赖矩阵全绿（R05 §2.4 判据门） | pip 实测 9 个包全在（含 culverin 0.14.0 / game-audio 2.1.0 / numba 0.67.0） | ✅ |
| 0.5-3 | 121 测试 3.12/3.13 双跑全绿（附录 D） | 附录 D 记 121/121；**本轮 3.13 上 133 文件全绿** | ✅ |
| 0.5-4 | 包体积/启动/import 门禁（附录 D） | −0.6% / −4.7% / import −16.0%、编辑器 import −16.3% | ✅ |
| 0.5-5 | FPS 门禁（R06 §2.3 G5） | **未达**：3.13 满载 78 vs 3.12 90（§9.10 空闲交替 n=5）＝ −13%；人类 §9.4/§9.16 接受并撤销硬门；D1 后回到 95 | ❌（人类已豁免） |
| 0.5-6 | 回滚点保留（pre_py313 + 三件 `__py312`） | 见 0-1，六条路径全部存在 | ✅ |
| 0.5-7 | 1 会话定位任务（§9.4 附加②） | §9.6 + `research_beta6_04`：机制=跨线程 GIL 交接 +83%（Event 乒乓 51.25→93.56µs），`LOOM_LOGIC_SYNC=1` 缺口 15%→3.2%，CPU/帧 12.66→14.45ms | ✅ |
| 0.5-8 | 附加条件① 批次 D 满载 ≥85（§9.4） | §9.17 空闲交替 n=5：C 打包中位 **95** / Python 打包 80（+19%），超 3.12 基线 90 | ✅ |
| 0.5-9 | 附加条件② "给出跨线程交接次数前后对比"（§9.4） | 只有 **after**：`research_04` F.5 `hm_pipe_post 0.587 / hm_pipe_wait 0.294 / hm_logic_wake 0.593` 每帧；**无改前同口径计数** | ◐ |
| 0.5-10 | Q9=A 空闲重测 3.12 vs 3.13（§9.9/§9.10） | §9.10 表：3.12 中位 90 / 3.13 中位 78，n=5 交替、每轮确认 models=501 | ✅ |
| 0.5-11 | 批次 0.5 三项候选 PySide6 6.12 / wgpu 0.33 / VS2026 | 6.12.0 ✅、0.33.0 ✅（ab 无差）、VS2026 ❌（同 0-5） | ◐ |

**批次 0.5 完成率**：严格 8/11 = **72.7%**；加权 **81.8%**。

### 1.3 批次 A · 渲染（FramePlan + tonemap + bloom，11 项）

| # | 原定目标（出处） | 实际交付（证据） | 判定 |
|---|---|---|---|
| A-S0 | `loom_pass.py` + **`loom_pass_gl.py` + `loom_pass_vk.py`（空后端）**；A/B 探针转正；验收"同一份 FramePlan 在 **VK 假设备**产出相同 pipeline/bind-group 计数"（R01 §③S0） | `loom_pass.py` 297 行（PassSpec/TargetDecl/DepthState/RasterState/DrawCmd/FramePlan+validate）、`loom_pass_gl.py` 234 行、A/B 已转正（`test_ab_gl_vk.py` 721 行 + 24 参考图 + 基线 json）；**`loom_pass_vk.py` 不存在**（`Get-ChildItem Loom/loom_pass*.py` 仅 2 个），VK 无假设备计数测试 | ◐ |
| A-S1 | 天空迁入 pass；**删掉假状态 `ctx.depth_mask` 写入**；验收②"日志不得再出现 `[渲染] 天空盒 … depth 状态` 告警"（R01 §③S1） | 天空 pass 在（`test_frame_plan` A5/A6、E7 `draw.sky`）；**假写仍在** `loom_render.py:187/195`、`344/346/354`，beta5 同位置 184/192、343/351（`git show 08ad3a3:Loom/loom_render.py`）；**告警仍打印**：`test_post_bloom`/`test_frame_plan` 实测 `[渲染] 天空盒 读 depth 状态失败 (AttributeError(...depth_mask)) -> 用默认值` ×2 | ◐ |
| A-S2 | 主 pass 迁入 + 编辑器复用同一 builder（R01 §③S2、风险 R7） | `loom_render.py:1170`、`editor.py:2474` 同一 `frame_plan()`；`test_frame_plan` C1–C9 PASS（状态应用/恢复、未注册绘制源 KeyError） | ✅ |
| A-S3 | 阴影迁入（dir/point 面数不变、`ab_c_dir_shadow` ≤7.1e-5） | `test_frame_plan` E3/E4/E9（`shadow.depth` + owned_by_provider）；实测 `ab_c_dir_shadow` 0.000051、`ab_point_shadow` 0.000051（≤基线） | ✅ |
| A-S4 | HUD/UI 迁入（MAE ≤5e-3 + 墨迹 bbox） | `test_frame_plan` E5/E6/E10；实测 `ab_ui_scene [UI] MAE 0.000000` | ✅ |
| A-S5 | tonemap + HDR 目标（R01 §③S5、Q-VIS-1=A） | `test_frame_plan` F1/F3（主链 `color.hdr`）/F6（rgba16float）；`loom_post.py:26-31` exposure=1.70 与 §9.14 一致 | ✅ |
| A-S6 | bloom（半分辨率链 + 亮部场景 + 晕圈量化，R01 §③S6） | `test_frame_plan` F5（0.5/0.25）；`tests/ab_scenes/ab_bloom.json`；`test_post_bloom` 晕圈 +42.5%、暗部 Δ0.0000 | ✅ |
| A-AB | A/B 探针提升受跟踪 + 三向比对 + 参考图（R01 §④R8、计划 §9.8 A-02） | `test_ab_gl_vk.py` + `ab_scenes_ref/` 24 张 + `ab_gl_vk_baseline.json`；本轮 23/23 PASS 0 SKIP，GL/参考恒 0 | ✅ |
| A-BUG1 | 顺手修 VK mip 目标格式写死 `rgba8unorm`（R01 §③S6 前置） | 计划 §9.13 明记已修；`test_frame_plan` F6 断言 HDR=rgba16float，VK 侧 post 走 `_ensure_post_targets` | ✅ |
| A-BUG2 | 顺手删 `ctx.depth_mask` 假状态（R01 §③S1） | **未删**，仅由计划 §9.11 改口径为"GL advisory" | ❌（口径降级为文档标注） |
| A-PERF | 后处理帧耗增量 ≤15%（R01 §③S6 验收③） | §9.14 实测 **+8%** 帧时 | ✅ |

**批次 A 完成率**：严格 8/11 = **72.7%**；加权 **81.8%**。A 批的"乘数"目的只兑现一半 —— 见 §2 P1-1。
### 1.4 批次 B · 资产（9 项）

| # | 原定目标（出处） | 实际交付（证据） | 判定 |
|---|---|---|---|
| B-S0 | 立规：报告裁决后**定稿 `docs/design/资产与GUID契约_<日期>.md`** + 只读盘点脚本（R02 §③S0） | **契约文档不存在**：`glob docs/**/*契约*.md` 无资产项、`glob *GUID*` 无命中；`架构互联协议总表.md` 中 "assets/资产" 命中 **0** 处；只读盘点脚本在 `tests/_tmp`（未跟踪，按设计） | ◐ |
| B-S1 | 索引与解析内核（schema/guid/指纹/越界拒绝/去重/冲突/原子写/损坏不崩） | `loom_assets.py` 905 行 / 43 defs：`os.replace` 原子写（:369）、`.bak-时间戳` 自愈备份（:432）；`test_asset_guid` 152 check ALL PASS | ✅ |
| B-S2 | 贴图 albedo/normal guid 化 + resolve + 失败出声 | 场景只写 guid（`sceneio.py:568-570`）；`scene_assets_check` 在（`agent_commands.py:2517`）；R6-01 V-01~V-05 P-DISPROVED | ✅ |
| B-S3 | 六面图 guid（场景/相机/材质三处同源）+ 边界上移项目根 | R6-01 V-06（天空盒进体检、六面图指纹、可见性）P-DISPROVED | ✅ |
| B-S4 | v11 迁移脚本 + 幂等 + dry-run | `tools/migrate_scene_assets_v11.py` 219 行；R6-01 V-07（字段落盘/dry-run 只读/批处理不中断）P-DISPROVED | ✅ |
| B-S5 | 打包：`game_pack` 增加 `assets` 段（**按 sha256 去重**）+ 播放器用包内 base（R02 §③S5） | 交付方式**改为整目录拷贝**：`build_game.copy_project_assets`（`build_game.py:115`），`game_pack.py` 中 "assets" 命中 **0** 处 → 无 pack 级 sha256 去重；包内 base 已接（`assets_base`）；R6-01 V-08 打包硬失败成立 | ◐ |
| B-S6 | 收尾回归（测试全绿 + `test_eai_real` 命令面不变） | 本轮 133 文件全绿；`test_eai_real` 102 命令 ALL PASS（186 check） | ✅ |
| B-QB13 | 材质真相源单一（Q-B1-3，主审建议 A/C） | **未决**：`待裁决清单_beta6.md:29` 仍 `待答`；assets.json 与场景 `materials[]` 双写仍在（R5-01 P-11 P-PROVED） | ❌ |
| B-D7 | D7 字面承诺"旧引擎明确拒绝新场景"（计划 §6 D7） | **不成立且不可修**：beta5 无 `min_engine_version` 读取点（R6-01 V-07 实测"无输出"）；人类 Q-R6A-1 裁决 A（只能保证新引擎兼容旧场景） | ❌（人类已豁免） |

**批次 B 完成率**：严格 5/9 = **55.6%**；加权 **66.7%**。

### 1.5 批次 C · 动画批次 1（9 项）

| # | 原定目标（出处） | 实际交付（证据） | 判定 |
|---|---|---|---|
| C-S1 | 求值内核抽取、engine 与 scene_driver **删除各自实现**、双宿主逐位相等（R03 §③S1） | `loom_components.evaluate_animations`（:786）；`scene_driver.py:1346` 直接调用、`test_animation_base:130-131` 断言 `co_names` 只含 `evaluate_animations`；两宿主 8 帧位姿逐位一致（:149） | ✅（模块名承诺 `loom_anim.py` → 实际落在 `loom_components.py`，非功能差异） |
| C-S2 | SoA 批量：**500 动画物体 ≤1.0 ms/逻辑帧** + 与逐物体逐位一致（R03 §③S2） | 逐位一致成立（40 组×40 相位）；**性能未达 1.448 ms**（12.743→1.448，8.8x，非承诺的 68.5x）；测试门限被放宽为 **≤2.0ms**（`test_animation_base.py:268`），docstring 仍写 "~1ms"（`loom_components.py:797`） | ❌ |
| C-S3a | 时间基准 + speed/pause/seek/loopMode(once/loop/pingpong)（R03 §③S3） | `seek`（`loom_components.py:602`，once 夹取/loop 取模/pingpong 折返）；测试覆盖 once 末帧、跨多周期、pingpong 端点、seek 不改 playing | ✅ |
| C-S3b | **跨周期计数**（R03 §③S3 同条列出） | 无 `cycle/period_count` 字段或返回值（全仓 0 命中）；`evaluate_animations` 仅返回 advanced/blocked_dynamic/fallback_dynamic | ❌（供批次5 事件用） |
| C-S4a | 序列化 v2：speed/clip_meta 落盘、`time/playing` 不落盘（D6）、v10 兼容 | `animator_to_dict`（:682-706）只写 current/loop/clips/speed/clip_meta；`animator_from_dict`（:709-731）旧文件兼容 + NaN 归一 | ✅ |
| C-S4b | undo 值隔离（clips 深拷贝，含嵌套 ndarray） | `test_animation_base` V-12 组 8 条全 PASS（list/tuple 内嵌 ndarray 深拷、快照不污染） | ✅ |
| C-S5 | 写者优先级 D6 + 一次性告警 + 双路径顺序一致 + 回退不冻结（含 Q-C1-3/U-01） | 返回 `blocked_dynamic/fallback_dynamic/fallback_ms`；R6-02 V-08（回退态 60 帧无漂移）PASS；⑦ 逃生门 vs 分离路径 10 帧逐位一致 | ✅ |
| C-EXIT1 | 出口判据：5 个具名新测试（shared/perf/timebase/serialize_v2/undo_isolation/physics_order/write_priority） | 合并为单一 `test_animation_base.py`（1103 行 / 115 check）；**未按承诺文件名交付**，但 8 个语义组齐 | ◐ |
| C-EXIT2 | 出口判据：`SCENE_VERSION=11` 且 v10 可读、scene_driver 无复刻 | `sceneio.py:58 SCENE_VERSION = 11`；`test_scene_version_gates` 12 PASS（v10/v8 兼容、旧引擎拒绝、播放器弹窗退出）；scene_driver 无复刻 | ✅ |

**批次 C 完成率**：严格 6/9 = **66.7%**；加权 **72.2%**。

### 1.6 批次 D · 热点下沉（6 项）

| # | 原定目标（出处） | 实际交付（证据） | 判定 |
|---|---|---|---|
| D-P0 | P0 插桩闭账：把 `mt_mp_draws` 5.8x 拆到子段并定性（R04 §③、附录 F.4） | `loom_profiler.py` 新增 `per_call_us`/`handoffs`；F.4 拆出 render 1.035 / uniform 0.255 / tex 0.048，结论"40x 差额在驱动提交路径"，据此否决 multi-draw（净收益 2%） | ✅ |
| D-P1 | P1 `bucket_pack` C 内核：逐字节等价 + `buckets` **2.65→≤1.0 ms**（R04 §③、D9） | `loom_bucket_pack_v1`（版本化导出 + provides 登记）；测试 21 PASS；实测 buckets **1.435→0.693（−52%，≤1.0 达成）**；真场景 30 帧×35 桶 0 不一致 | ✅ |
| D-P2 | P2 物理桥 SoA + `loom_pose_sync`：`pipe_wait` **3.99→≤2.0 ms**（R04 §③、D9、N-01） | `_pose_rows` 落地、`LOOM_POSE_SOA=0` 回退；对拍 64 次调用 0 不一致；实测 **pipe_wait 3.985→3.277（−0.71）**，未达 ≤2.0；剩余三段 0.32+0.65+0.18 记为 D2b **未做** | ◐ |
| D-P3 | P3 AABB AVX2：**1.38→≤0.7 ms**（R04 §③、D9） | AVX2 + CPUID 分派（`test_aabb_simd` 分派=1，三路逐位一致 maxΔ=0）；实测 `mt_aabb_minmax` 2.04→1.13、`aabbs` 段 1.05→**0.73**（差 0.03 未达 ≤0.7） | ◐ |
| D-FPS | 满载 FPS ≥85（§9.4 附加①） | §9.17 源码 C 打包中位 **95**（Python 打包 80，+19%）；§9.20 安装版中位 90 | ✅ |
| D-HANDOFF | 交出"跨线程交接次数"前后对比（§9.4 附加②/§9.6） | 只有 after（F.5 每帧 0.587/0.294/0.593）；`beta6优化想法备忘.md:25`（PF-03）明列"交接批量化"仍属未做项 | ◐ |

**批次 D 完成率**：严格 3/6 = **50.0%**；加权 **75.0%**。

### 1.7 beta6 承诺完成率（按条目计）

| 批次 | 条目 | ✅ | ◐ | ❌ | 严格完成率 | 加权（◐=0.5） |
|---|---:|---:|---:|---:|---:|---:|
| 0 工具链 | 14 | 12 | 1 | 1 | 85.7% | 89.3% |
| 0.5 py3.13 | 11 | 8 | 2 | 1 | 72.7% | 81.8% |
| A 渲染 | 11 | 8 | 2 | 1 | 72.7% | 81.8% |
| B 资产 | 9 | 5 | 2 | 2 | 55.6% | 66.7% |
| C 动画 | 9 | 6 | 1 | 2 | 66.7% | 72.2% |
| D 热点 | 6 | 3 | 3 | 0 | 50.0% | 75.0% |
| **合计** | **60** | **42** | **11** | **7** | **70.0%** | **79.2%** |

- 若把人类**已明确豁免**的 2 项（0.5-5 FPS 门禁、B-D7 旧引擎前向拒绝）按达成计：加权 **82.5%（49.5/60）**。
- 只看四个"功能批"（A/B/C/D，35 项）：严格 **62.9%**，加权 **73.9%**。
- 结论：**骨架类承诺基本兑现**（A 的 pass/HDR/bloom、B 的 guid/迁移、D 的 C 内核），但"每条承诺都带数字验收"的条目有系统性打折：7 项 ❌ 中 4 项是数值/机制未到（C-S2、D-P2、D-P3、A-BUG2），3 项是文档/契约缺位（B-S0、B-QB13、0-5）。
---

## 2. 引入问题清单（搭建过程新增，非 beta5 存量）

| # | 类型 | 事实与证据 | 等级 |
|---|---|---|---|
| P1-1 | **架构乘数只兑现一半** | 批次 A 的目标是"一份描述驱动两后端，避免每加效果写两遍"。实际 `loom_pass_vk.py` **不存在**（`Get-ChildItem Loom/loom_pass*.py` → 仅 297/234 行两个文件）；`vk_renderer.py` 只 `from loom_post import params`（:1009），后处理是手写第二份：`_POST_WGSL`（:474-532，59 行）+ `_ensure_post_*`/`_record_post`（:918-1038，121 行）≈180 行，对照 GL `loom_post_gl.py` 204 行；共享面仅 `loom_post.py` 64 行（≈14%）。→ 下一个效果（阴影编码/HUD/新后处理）仍要写两遍 | P1 |
| P1-2 | **性能门禁被测试放宽** | 承诺 ≤1.0 ms（`research_beta6_03:511`），实测 **1.448 ms**，而 `test_animation_base.py:268` 断言写 **≤2.0 ms**；`loom_components.py:797` docstring 仍称 "~1ms"。门禁与文案都比实测乐观 → 后续无法用测试守住 1.0 | P1 |
| P2-1 | **验收条目静默降级** | R01 S1 验收②"日志不得再出现 `[渲染] 天空盒 … depth 状态` 告警"：告警仍在（`test_post_bloom`/`test_frame_plan` 各 2 行），假 `ctx.depth_mask` 写仍在 `loom_render.py:187/195,344/354`；计划 §9.11 只把 `DepthState.write` 标注 advisory，未登记"该验收项未达成" | P2 |
| P2-2 | **打包机制偏离承诺** | `game_pack` 未加 `assets` 段（`game_pack.py` "assets" 命中 0），改由 `build_game.copy_project_assets` 整目录拷贝 → 失去 sha256 去重（R02 S5 明确要求），资产随场景重复拷贝；§9.15 未登记此偏离 | P2 |
| P2-3 | **因果证据不完整** | §9.4 附加②要求"交接次数前后对比"，全仓只有 after 计数（`research_04` F.5），改前同口径未留档 → 无法证明 D2/D3 真的减少了交接（只能证明整帧 FPS 变好） | P2 |
| P3-1 | **契约文档缺位** | B 批 S0 要求定稿 `docs/design/资产与GUID契约_<日期>.md`；`glob docs/**/*契约*.md` 无资产项、`架构互联协议总表.md` 对 assets/资产 **0** 引用 → 后续只有代码与测试，无单页契约 | P3 |
| P3-2 | **工具重复** | `tools/loom_lint_except.py` 与 `tools/lint_except_dist/loom_lint_except.py` sha256 相同（`E10B9B227AECF0A728B4EDCBA9143178F50EA8CD2EC9B1F699FF2509EB85B0B3`），25520B×2 / 626 行×2 | P3 |
| P3-3 | **诊断开关进主线** | `loom_post.py:48-55` `post_stage()` docstring 自述"2026-11-10 编译版崩溃二分；**定稿前清理**"，仍在发布路径，并新增 `LOOM_POST_STAGE` 语义 | P3 |
| P3-4 | **文档数字漂移** | 计划 §9.11 记"22 场景 / frame_plan 27 项 / 313 项测试"，实测 **23 场景 / 49 PASS / 133 文件**；§9.15 记"126 文件绿"，`research_04` F.6 记"128 文件"。复算口径不唯一 | P3 |
| P3-5 | **工作区副作用（未定责）** | 审计窗口内仓根出现未跟踪 `Assets/assets.json`(578B)+`Assets/Textures/_loom_cmd_tex.png`(77B)，创建时间落在 run_all 期间；单独复跑 `test_eai_real` 与 `test_asset_guid` 均**不能**复现（`git status` 干净）→ 归因不明，已核验内容后删除，不影响判定 | P3（观察） |

**已被审计闭环抓住并修复的"新引入缺陷"（正向证据）**：R5-01 P-01 解析失败保存销毁 guid（P1）、R5-02 P-01 常量通道写 plain tuple（P0）、R5-02 P-02 once 负相位分叉（P1）、R6-01 D-01 新建场景复活 dead guid（P1）、R6-02 V-08 回退态双写者（P1）、R6-03 U-01 陈旧源码包（P1）。均可在对应 `docs/audit/scan_beta6_round*` 查到 P-PROVED 与修复后复测。

---

## 3. 统计

### 3.1 代码与测试规模（diff + `wc -l` 实测）

| 区域 | 新增/改动 | 行数 |
|---|---|---:|
| 渲染抽象 | `loom_pass.py` / `loom_pass_gl.py` / `loom_post.py` / `loom_post_gl.py` | 297 / 234 / 64 / 204（defs 5 / 16 / 4 / 11） |
| 资产 | `loom_assets.py`（43 defs）/ `migrate_scene_assets_v11.py` | 905 / 219 |
| 动画 | `loom_components.py` 净增 / `test_animation_base.py` | +520 / 1103（115 check） |
| 热点 | `ckernels/loom_kernels.c` 净增 / `fastpath.py` / `physics_bridge.py` | +305 / +114 / +71 |
| 后端门与地板 | `loom_backend_guard.py` / `loom_gl_version.py` | 184 / 80 |
| 工具链 | `tools/build_engine.py`（新）/ `package_engine.py` 净增 / `build_game.py` 净增 | 318 / +390 / +156 |
| 测试面 | `test_*.py` 文件数 121 → **133**；本轮 PASS 断言 **3933** 行 | — |
| A/B 锚点 | `test_ab_gl_vk.py` 721 行 + 参考图 24 张 + 基线 json 158+164 行 | — |

### 3.2 实测数字一览（本机 3.13.15）

| 指标 | 承诺/目标 | 实测 | 判定 |
|---|---|---|---|
| GL/参考 MAE（23 场景） | =0.000000 | 全 0；VK/参考最大 0.000066 | ✅ |
| 500 动画物体 | ≤1.0 ms | **1.448 ms**（旧 12.743） | ❌ |
| buckets | ≤1.0 ms | **0.693 ms**（旧 1.435） | ✅ |
| pipe_wait | ≤2.0 ms | **3.277 ms**（旧 3.985） | ◐ |
| aabbs 段 / mt_aabb_minmax | ≤0.7 / 1.38 | **0.73** / 1.13 | ◐ |
| 后处理帧耗 | ≤15% | +8% | ✅ |
| bloom 晕圈 | 需量化证明 | 0.3414→0.4866（+42.5%） | ✅ |
| 满载 FPS | ≥85 | 源码 95 / 安装版 90（3.12 基线 90） | ✅ |
| 全量测试 | 121 全绿 | 133 文件 / FAIL 0 / exit 0 | ✅ |

### 3.3 交付物状态

- `tools/dist/`：`Loom-0.1.0.beta6-compiled.zip` 136,396,938B（11-10 14:40）在位；**`Loom-0.1.0.beta6-source.zip` 不在位**（R6-03 U-01 按裁决删除，需用当前代码重建 —— beta6 收尾前必须补）。
- `Loom/解释器.json`：version `0.1.0.beta6`、python_version `3.13.15`（与编译包 meta 一致）。

### 3.4 只读自查

- 本轮写入仅：`docs/audit/final_03_四批目标达成度核对.md`（本文件）+ `Loom/tests/_tmp/_final03_*`（`.gitignore` 已忽略的探针/日志）。
- 收尾 `git status --porcelain` 仅显示本文件；跑 `run_all` 后出现的未跟踪 `Assets/` 已核验内容并删除（P3-5）。

---

## 4. 需人类裁决的问题（封闭式）

1. **Q-03-1 渲染抽象的 VK 半边**：`loom_pass_vk.py` 属 S0 必交付但未写，"一份描述两后端"只兑现 GL 侧（P1-1）。
   A 补做 `loom_pass_vk.py`（VK 消费 FramePlan + 假设备计数测试）／ B 正式把 VK 移出 FramePlan 范围并改写 D2 裁决与 R01 S0 验收／ C 保持现状但登记为 beta7 前置。
   （主审建议 A 或 B；C 会让"加效果写两遍"的成本在 beta7 继续复利。）
2. **Q-03-2 动画性能门禁**：承诺 ≤1.0ms、实测 1.448ms、测试却断言 ≤2.0ms（P1-2）。
   A 恢复 ≤1.0 门禁并把 1.448 记为主线欠账／ B 把承诺改成 ≤2.0 并同步 docstring／ C 再投一轮优化到 ≤1.0。
   （主审建议 B + 登记欠账；A 会让全量测试立刻红。）
3. **Q-03-3 批次 D 数值未达是否阻塞收尾**：`pipe_wait` 3.277（目标 2.0）、`aabbs` 0.73（目标 0.7）未达，但 FPS 已超 3.12 基线（95 vs 90）。
   A 以 FPS 为准收官、D2b/D3 差额登记 beta7／ B 继续做 D2b 到 pipe_wait ≤2.0 再收尾／ C 把 D 批验收口径改为"整帧 FPS"。
4. **Q-03-4 缺失的契约文档与源码包**：`资产与GUID契约_*.md` 缺位、`-source.zip` 未重建。
   A 收尾前补齐两者／ B 只补 source 包、文档登记 beta7／ C 都不补，接受现状。
5. **Q-03-5 交接次数前后对比（§9.4 附加②）是否关账**：现只有 after 计数。
   A 接受以"整帧 FPS + 交接基线"关账／ B 用 `__py312` 产物补一次改前同口径计数／ C 记为未兑现的裁决项。

---

> 附件（可复跑）：`Loom/tests/_tmp/_final03_runall.txt`（133 文件全量）、`_final03_ab.txt`（23 场景）、`_final03_anim.txt`（动画性能行）、`_final03_asset.txt`（152 check）、`_final03_eai.txt`（102 命令）。
