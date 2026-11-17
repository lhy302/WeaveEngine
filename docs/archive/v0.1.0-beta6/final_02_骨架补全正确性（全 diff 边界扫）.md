# 编号 02：骨架补全正确性（beta6 全 diff 边界扫）

> 只读审计。基线 `08ad3a3`（beta5 发布点）→ 当前 HEAD `a0b0ae0`。
> 方法依据：`docs/audit/SCAN_PROTOCOL.md`（粗筛→双向推演→实操）+ 桌面两份方法论文档。
> 探针全部在 `Loom/tests/_tmp/final_02_*.py`，不写任何受跟踪文件（见 §0.4 自查）。

---

## 0. 范围与基线

### 0.1 范围（12 个派单文件）

`git diff --numstat 08ad3a3..HEAD -- <12 文件>`：

| 文件 | + | − | 文件 | + | − |
|---|---|---|---|---|---|
| `Loom/sceneio.py` | 599 | 118 | `Loom/scene_driver.py` | 150 | 73 |
| `Loom/loom_assets.py` | **905** | 0 | `Loom/run_player.py` | 197 | 39 |
| `Loom/loom_components.py` | 519 | 1 | `Loom/game_player.py` | 33 | 17 |
| `Loom/loom_frame_components.py` | 25 | 22 | `Loom/build_game.py` | 150 | 6 |
| `Loom/undo.py` | 22 | 8 | `Loom/runtime.py` | 11 | 1 |
| `Loom/editor.py` | 190 | 50 | `Loom/agent_commands.py` | 262 | 21 |
| **合计** | **3063** | **356** | | | |

新增公共函数（diff 提取，逐文件）：`sceneio +40`、`loom_assets +43(新文件)`、`loom_components +17`、
`scene_driver +6`、`run_player +10`、`build_game +6`、`agent_commands +7`、`editor +8`、
`game_player +1`、`undo/loom_frame_components/runtime +0`。

### 0.2 跑过的命令（全部可复跑）

```
git diff --stat 08ad3a3..HEAD                       # 197 文件 / +26283 / -875
git diff 08ad3a3..HEAD -- Loom/<每个文件>            # 逐文件读 diff
python Loom/tests/_tmp/final_02_env.py              # ② env 开关/版本闸门边界
python Loom/tests/_tmp/final_02_import.py           # ⑤ import 时间 (子进程隔离, n=3 取 min)
python Loom/tests/_tmp/final_02_state2.py           # ①③④ 退化输入/状态/缓存
python Loom/tests/_tmp/final_02_scale.py            # 索引规模曲线 + realpath 归因
python Loom/tests/_tmp/final_02_scale2.py           # is_inside 单次成本
python Loom/tests/_tmp/final_02_saveidx.py          # save_index 合并/校验成本
python Loom/tests/_tmp/final_02_deg.py              # 17 公共函数 x 10 退化值分类
python Loom/tests/_tmp/final_02_root.py             # 空根 ('') 语义
cd Loom && python tests/test_asset_guid.py          # PASS=152 FAIL=0
cd Loom && python tests/test_animation_base.py      # PASS=115 FAIL=0
cd Loom && python tests/test_scene_version_gates.py # ALL PASS
cd Loom && python tests/test_scene_version_player.py# ALL PASS
```

**测量条件**：机器空闲、无并行编译/测试；解释器 **Python 3.12.10**（系统 PATH），
而 `Loom/解释器.json` 声明 `python_version=3.13.15` —— 本报告全部耗时数字是 3.12 读数。

### 0.3 判定口径

P0=崩溃/安全，P1=功能错误，P2=边界/性能/规模，P3=可维护性/文档实现不一致。
"目标达成"= 设计文档（`版本计划…beta6_20261109.md` §9.11–9.17 + B1/C1/D7 口径）声明的行为，
能在本机用命令复现，且退化输入下不越界。

### 0.4 只读自查

```
git status --porcelain        ->  (空)
```
- 探针 `final_02_deg.py` 调用 `save_index('', '')` 时，**在仓库根意外落盘了 `Assets/assets.json`（36 字节空索引）**——
  这既是探针副作用，也是本报告 **F-03** 的现场证据。已 `Remove-Item -Recurse Assets`（确认该目录仅含此 1 个文件），
  `git status` 恢复为空，无受跟踪文件被改动。
- `Loom/tests/_tmp/final_02_*.py` 为探针（`tests/_tmp` 未被跟踪）；探针创建的临时项目目录已 `rmtree`。

---

## 1. 目标达成判定表

| # | beta6 原定目标（出处） | 判定 | 实测证据 |
|---|---|---|---|
| G1 | B1 资产 guid：场景只写 guid、索引唯一真相、越界拒绝（§9.15） | **达成** | `test_asset_guid` 152/152 PASS；`sceneio.py:316-324` 越界/相对路径逐条剔除；`is_inside` 7 组边界全对（探针 C8） |
| G2 | B1 打包带资产：包内不再按 CWD 解析（§9.15） | **达成** | `build_game.py:115 copy_project_assets`；`runtime.py:141-147`、`vk_player.py:326-327`、`game_player.py:134/266` 三处 `assets_base` 全部接线（无遗漏入口） |
| G3 | B1 旧路径 fallback：无索引 = beta5 语义，一次 beta 周期兼容（D4） | **达成** | `sceneio.py:175-184` 无 `assets.json` → `None` → 旧路径；`test_asset_guid` 内含 fallback 用例全 PASS |
| G4 | C1 动画内核**唯一实现**：GL 与 SceneDriver 共用 `evaluate_animations`（§9.15/research_03） | **达成** | `loom_frame_components.py:100` 与 `scene_driver.py:1346` 均只调 `loom_components.evaluate_animations`；旧逐物体采样已删（`loom_components.py:634-649`）；`test_animation_base` 115/115 PASS |
| G5 | C1 undo 隔离：clips 按值拷贝、speed 入快照、旧 3 元快照兼容（research_03 §1.5） | **达成** | `undo.py:123-127`（存时 copy）、`undo.py:220-235`（写回再 copy、`len(val)>3` 兼容）；`test_animation_base` 115 PASS 含 V-12 |
| G6 | D7 场景版本闸门：写 `min_engine_version`、旧引擎明确拒绝、无字段/脏版本不拦（D7） | **达成（有洞）** | 写入 `sceneio.py:1822/2144`；入口 5 处全接（editor 2 / sceneio 场景+prefab 2 / scene_driver 1）；`test_scene_version_gates`+`_player` 全 PASS。**洞**：`0.1.0-beta6` 形态解析为 `None` → 闸门静默跳过（F-07） |
| G7 | B4 `LOOM_NO_PHYSICS` 从"只写在注释里"变成真开关，且双端一致（R6 V-10） | **达成** | `loom_physics.py:471` 物理整段跳过；`loom_frame_components.py:98` / `scene_driver.py:1079,1329` 同判据；`test_animation_base` ⑧ 三连 PASS |
| G8 | 2B2 后处理开关 `LOOM_POST=0` 回退旧路径 + 参数可由 env 微调（§9.13） | **达成** | `loom_post.py:41-44`；GL `loom_render.py:35/1173`、`editor.py:25/2476`；VK `vk_renderer.py:736-737/2233/2293` 双端都有 |
| G9 | 崩溃可见性：release 无控制台也能取证（loom_debug 文档串） | **部分达成** | `Loom.py:26`、`build_entry.py:28` 接线；**打包游戏入口（`game_player.py`/`run_player.py`/`vk_player.py`）0 处调用** → 游戏档该开关无效（F-05） |
| G10 | 诊断开关"定稿前清理"（`loom_post.py:48` 自述） | **未达成** | `LOOM_POST_STAGE` 仍在且被 `loom_pass.py:172` 使用；`LOOM_POST_STAGE`/`LOOM_FAULTHANDLER`/`LOOM_BLOOM_*`/`LOOM_POST_EXPOSURE` 在全部 `.md`/`.txt` 中 **0 次**登记（`git grep` 实证；`使用操作指南.txt` 仅登记 `LOOM_NO_FRAMEBUF` 1 个） |

---

## 2. 引入问题清单

### 2.1 ① 新增/修改公共函数的边界（空值/None/异常/并发/大输入）

**F-01 [P2] 索引校验 1.0 ms/条，1 万条资产冷加载 8.8 s（大输入）**
- 位置：`Loom/loom_assets.py:278-330`（`validate_index` 每条调用 `is_inside`）→ `loom_assets.py:143-156`（`is_inside` 每次 2 次 `os.path.realpath`）。
- 契约：`loom_assets.py:9` "热路径只 stat（mtime+size）"；加载路径被当作轻量操作。
- 路径枚举：`sceneio.asset_context`（`sceneio.py:175-184`）→ `context_for_scene`（`loom_assets.py:899`）→ `for_dir` → `load_index` → `validate_index`；`inspect_index`（`loom_assets.py:251-275`）**不走缓存**，被 `asset_list`（`agent_commands.py:2495`）与 `scene_assets_check`（`agent_commands.py:2528`）每次调用。
- 实测（`final_02_scale.py`，root=真实临时项目）：
```
N         validate_index   每条约    is_inside x N
100         105.0 ms    1.050 ms      99.2 ms
1000        998.2 ms    0.998 ms     966.5 ms
5000       5004.9 ms    1.001 ms    5002.1 ms
validate_index(1000): realpath 调用 2000 次 (每条 2 次)
validate_index(1000, root=None) = 2.3 ms      <- 成本 100% 在 is_inside
C3 validate_index(10000 条) = 9876.1 ms
C3 load_index(10000) 冷 8660.4 ms / 热 0.13 ms; inspect_index(10000) 8587.6 ms
```
  `final_02_scale2.py`：`is_inside` 单次 0.583–0.847 ms，**与文件是否存在无关**（存在 0.612 / 不存在 0.716）→ 结构性成本。
- 影响：资产数 500 → 每次开场景 +0.5 s；2000 → +2 s；10000 → +8.6 s。每次 `scene_assets_check`（EAI）在编辑线程上再付一次全量。beta5 基线为 0 ms（无该层）。
- 建议方向（不含代码）：只在"导入/索引被外部改写"时全量校验；加载路径改惰性逐条解析（`resolve` 已按需 stat），或把越界判定降为 `normpath` + 前缀比较。

**F-02 [P2] 用户层 delta 的 `import` 覆盖从未生效；该层全仓 0 个写者（文档承诺 ≠ 实现）**
- 位置：`loom_assets.py:13`（模块 docstring "用户层 … 只存 delta（src/import 覆盖）"）、`loom_assets.py:476`（注释）vs `loom_assets.py:483`（只取 `src`）、`loom_assets.py:536-542`（`_import_settings` 只读 `entry['import']`）。
- 实测（探针 C7）：delta 要求 `mipmaps=False/wrap='clamp'` → 实际 `mipmaps=True / wrap='repeat'`。
- 且 `user_index_path`（`loom_assets.py:115-140`）全仓仅被 `_load_user_delta` 以 `'r'` 打开（`loom_assets.py:374-382`），**没有任何写入点**——该层对产品而言不可达。
- 影响：D3/§9.15 声明的三层解析实际只有两层；未来若按文档写用户层 delta，`src` 生效而 `import` 静默无效（半生效最难排查）。
- 建议方向：删掉 `import` 覆盖的声明与 `user_delta` 机制（诚实两层），或补齐（解析后按 delta 覆盖 import + 提供写入口）。

**F-03 [P2] `save_index('')` 把资产库建到进程 CWD（空根未拒绝）**
- 位置：`loom_assets.py:107-108`（`assets_dir` 直接 `os.path.abspath(root)`）、`loom_assets.py:340-371`（`save_index` 无空根校验）。
- 实测（探针 G，cwd=临时目录）：`assets_dir('') -> <cwd>/Assets`；`save_index('', {})` → `<cwd>/Assets/assets.json` 落盘=True。
  **本报告 §0.4 的意外落盘就是这个调用在仓库根发生的一次**（`Assets/assets.json`，36 字节）。
- 相关路径：`Loom/editor.py:905` `_scene_dir()` 在"场景未保存"时返回 `os.getcwd()`；`editor.py:916-922` `_asset_context()` 会据此向上找项目根。
  `editor.py:928-934` 已用 `_scene_path` 守卫（注释明写"避免把 Assets/ 建到引擎目录/CWD 污染仓库"），但 `loom_assets` 层本身没有守卫。
- 影响：任何第三方/EAI 新调用点传 `''`/`'.'` 就会在 CWD 建资产库；一旦 CWD 下出现 `Assets/assets.json`，`find_project_root` 会让**引擎目录下所有子场景**都认它为项目根（探针 G 实测从 `_tmp` 爬到仓库根）。
- 建议方向：`assets_dir`/`save_index` 对 `''`/`'.'` 显式报错；`find_project_root` 增加"不得越过引擎安装目录"的停止条件。

**F-04 [P3] `record_asset_error` 线性去重 + 无上限打印（O(N²) 与刷屏）**
- 位置：`sceneio.py:187-202`（`if item in errs` + 每条 `print`）。
- 实测（探针 C5）：`N=500 → 5.0ms/510 行`、`2000 → 54.3ms/2510 行`、`5000 → 313.3ms/7510 行`；N 增 10 倍时间增 **63.1 倍**。
- 影响：一个索引坏掉的项目（成千条引用失败）会同时吃掉 CPU 与 stdout；`scene_assets_check` 的 `errors` 数组也无上限。
- 建议方向：`errs` 改 `set` 或"前 N 条详情 + 计数"。

**F-05 [P3] `LOOM_FAULTHANDLER` 非法值 = 在 CWD 建同名文件；且打包游戏入口未接线**
- 位置：`loom_debug.py:18-30`（非 on/off 一律当路径 `open(v,'w')`）；接线点仅 `Loom.py:26`、`build_entry.py:28`。
- 实测（探针 A4）：`LOOM_FAULTHANDLER='garbage'` → 句柄 `TextIOWrapper name='garbage'`，`落地文件存在=True`。
- 影响：拼错一次就在启动目录留一个垃圾文件（与 §4 "`Loom/%SystemDrive%` 环境变量字面量" 同一类卫生问题）；release 游戏档该开关**不生效**，与 `loom_debug.py:7` "release 档取证" 的声明不符。

**F-06 [P3] `_anim_fallback_models` 在"停止播放"不清 → 持有已移除模型**
- 位置：`loom_frame_components.py:103`、`scene_driver.py:1348`（每帧赋值）；`editor.py:2181` 起的退出播放分支无该字段（grep 0 命中）。
- 实测（探针 C6）：物理不可用 → `fallback_models=1`；把模型从 `models` 移除 + `gc.collect()` 后 **weakref 仍存活**；只有 `del engine` 才释放。
- 影响：编辑器"播放中脚本 spawn 物体 → 停止"后，被删模型至少多活一个播放周期（强引用）；`_update_physics_legacy` 在编辑态不被调用，所以当前无功能错误，属资源边界。

**F-07 [P3] `parse_version` 对连字符/前缀形态返回 None → 版本闸门 fail-open**
- 位置：`sceneio.py:96-138`。
- 实测（探针 A6，16 个形态）：`'0.1.0-beta6' -> None`、`'v0.1.0' -> None`、`'0.1.0.rc1' -> None`、`''/None/11 -> None`；`check_engine_version({'min_engine_version': '0.1.0-beta6'}) -> True`（打印"跳过版本闸门"后放行）。
- 影响：D7 的判据是 `ENGINE_VERSION`（读 `Loom/解释器.json`）。若发布工程把 version 写成 semver 连字符形态，场景里写的就是不可解析串，**整条闸门失效且无人报错**（`0.1.0.beta7` 这种点分形态才有效）。
- 建议方向：写盘前用 `parse_version` 自检一次（不可解析就 warning）；或解析器接受 `-`/`+` 分隔。

### 2.2 ② 新增 env 开关清单（默认/非法值/文档登记）

| 开关 | 默认 | 非法值实测行为 | 文档登记 | 证据 |
|---|---|---|---|---|
| `LOOM_POST` | 开 | `0/off/false/no/空` → 关；其它（含 `garbage`）→ 开 | 版本计划 §9.13 ✓ | A1 |
| `LOOM_POST_STAGE` | 3 | **`0`→1（不是关闭）**；`-5`→1；`99`→3；`x`/`2.7`→3 | **0 次**（仅代码注释，且自述"定稿前清理"） | A2 + `min(post_stage over 200 inputs)=1` |
| `LOOM_BLOOM_THRESHOLD` | 1.15 | 非数值→默认；**`nan`/`inf` 原样接受** | **0 次** | A3 |
| `LOOM_BLOOM_STRENGTH` | 0.70 | 同上（`nan`→nan、`-5`→-5 不夹取） | **0 次** | A3 |
| `LOOM_BLOOM_KNEE` | 0.35 | 同上 | **0 次** | `loom_post.py:60-64` |
| `LOOM_POST_EXPOSURE` | 1.70 | `nan`/`inf`/`0` 原样接受 | **0 次** | A3 |
| `LOOM_FAULTHANDLER` | 关 | 非 on/off **当文件路径**（见 F-05） | **0 次** | A4 |
| `LOOM_NO_PHYSICS` | 关 | `abc`/`2`/` 1 ` → **开（禁用物理）**；文档只列 1/true/yes/on | **0 次**（`scan_beta6_round6_02` 还写着"该开关不存在"——已过期） | A5 |
| `LOOM_POSE_SOA` | 开 | 仅 `'0'` 关 | research_04 ✓ | `engine.py:1238` |
| `LOOM_BUCKET_PACK` | 开 | 仅 `'0'` 关 | research_04 ✓ | `loom_render.py:797` |
| `LOOM_BUCKET_LEGACY` | 关 | 仅 `'1'` 开 | audit 报告 ✓ | `loom_render.py:668` |
| `LOOM_AB_ALLOW_NO_VK` | 未设=FAIL | `'1'` 才允许 SKIP | 版本计划 §9.8 ✓ | `test_ab_gl_vk.py:417` |
| `LOOM_AB_SCENES` | 空=glob | `','` → 空集 → **rc=1 FAIL**（轮2 P1-2 已修） | 版本计划 §9.8 ✓ | `test_ab_gl_vk.py:418-421/708-710` |
| `LOOM_AB_<GATE>` | `DEFAULT_GATE` | 非数值**静默用默认** | 未逐项 | `test_ab_gl_vk.py:81-90` |

**F-08 [P2] `LOOM_POST_STAGE=0` 无法关闭后处理；`post_enabled` 的第 2 个条件恒真**
- 位置：`loom_post.py:44`（`... and post_stage() > 0`）、`loom_post.py:53`（`max(1, min(3, ...))`）。
- 实测（A2）：`LOOM_POST_STAGE` 取 -100..99 共 200 个值，`min(post_stage)=1` → `post_stage() > 0` **永真**（死条件）；`LOOM_POST_STAGE=0` 得到 stage=1（仍开后处理）。
- 影响：想用"分级开关"二分崩溃的人会把 `0` 当关闭，实际拿到 stage1（HDR+tonemap 仍在），排查方向被误导。

**F-09 [P2] `_env_float` 接受 `nan/inf`，无夹取，直接进后处理参数**
- 位置：`loom_post.py:34-38`；消费点 `loom_post_gl.py:14`（`params`）、`vk_renderer.py:1009-1028`（`np.array(..., dtype='f4')` 直接 `write_buffer`）。
- 实测（A3）：`LOOM_POST_EXPOSURE=nan` → `params['exposure']=nan`，`finite=False`；`threshold`/`strength` 同理。`-1`/`-5`/`1e308` 也原样通过。
- 影响：一个手滑的 env 就让 tonemap 输出 NaN（整屏异常），代码没有任何"非法参数 → 回默认 + 告警"的闸门。

### 2.3 ③ 全局状态在「新建/加载/播放/停止」四态的重置

| 状态 | 新建 | 加载 | 播放 | 停止 |
|---|---|---|---|---|
| `_asset_errors` | ✅ `editor.py:1321-1324`（`test_asset_guid:836-849` 断言不再谎报上一场景） | ✅ `sceneio.py:1846`（每次加载清空） | ✅ `scene_driver.py:620`（驱动自建，与编辑器互不污染） | ⚠️ 编辑器侧不清（播放期不产生资产错误，当前无实害） |
| `_skybox_ref` | ✅ `editor.py:1320` | ✅ `sceneio.py:1872-1876`（成功则 None） | ❌ **`scene_driver.py` 0 处**（F-10） | ✅ 不参与 |
| `_skybox_valid/_skybox_error` | ✅ `editor.py:1318-1319` | ✅ `sceneio.py:1866-1867` | ✅ `scene_driver.py:621-626/686-687` | ✅ 不参与 |
| `_anim_fallback_models` | — | — | ✅ 每帧赋值 | ❌ 不清（F-06） |

**F-10 [P3] `_skybox_ref` 只在 engine/编辑器一侧实现，SceneDriver（播放器路径）缺失**
- 位置：`sceneio.py` 6 处、`editor.py` 3 处、`scene_driver.py` **0 处**（探针 C9）。
- 影响：播放端不保存场景，故当前无功能损失；但 `sceneio.asset_refs_kept/digest` 在 player 引擎上恒为空，"保留失效引用"这条 B1 语义只在编辑器路径成立——属"只在一端修"的登记项，不是 bug。

### 2.4 ④ "只在一条后端/一个入口修"的遗漏清单

| 语义 | GL | VK / Player | 判定 |
|---|---|---|---|
| `LOOM_POST` | `loom_render.py:35/1173`、`editor.py:25/2476` | `vk_renderer.py:736-737/2233/2293` | 双端齐 |
| `LOOM_POST_STAGE` | `loom_pass.py:172`（FramePlan 分级） | **VK `_record_post` 不读**（`vk_renderer.py:1006-1038` 恒 3 段） | **遗漏**（F-11） |
| `LOOM_NO_PHYSICS` | `loom_physics.py:471` + `loom_frame_components.py:98` | `scene_driver.py:1079/1329` | 双端齐 |
| `LOOM_POSE_SOA` | `engine.py:1238` | 无对应概念（走 bridge post_step） | N/A（登记） |
| `LOOM_BUCKET_PACK/LEGACY` | `loom_render.py:797/668` | VK 无 bucket 提交层 | N/A（登记） |
| `LOOM_FAULTHANDLER` | `Loom.py:26`、`build_entry.py:28` | **`game_player/run_player/vk_player` 0 处** | **遗漏**（F-05） |
| `min_engine_version` 闸门 | `sceneio.scene_from_dict:1939`、prefab `2159/2169`、`editor 1229/1442` | `scene_driver.py:611` + 播放器弹窗 `run_player.py:278-298`、`loom_player_window.py:56` | 齐（无遗漏入口） |
| `_asset_errors` | `sceneio.py:187-207` | `scene_driver.py:620/640/690` | 齐 |
| `assets_base` | `runtime.py:141-147` | `vk_player.py:326-327` / `game_player.py:134/266` | 齐 |

**F-11 [P3] VK 后处理不认 `LOOM_POST_STAGE`，且 `'up'` 分支是死代码**
- 位置：`vk_renderer.py:1017-1025`（`rows` 固定 bright/down/tonemap 三段）、`vk_renderer.py:1032`（`LoadOp.load if name == 'up' else clear`——`rows` 里没有 `up`）。
- 影响：2B2 崩溃二分只在 GL 有效；VK 上设 stage=1/2 行为与 3 完全一致（人会误判"分级无效"）。

### 2.5 ⑤ 新增 import 对启动的影响（实测）

| 模块 | 本进程 import（n=3 min） | 是否在启动路径 |
|---|---|---|
| `loom_post` | **0.7 ms** | `editor.py:25`、`loom_render.py:35` 顶层（≈0 成本） |
| `loom_debug` | **0.8 ms** | `Loom.py:26` 函数内 |
| `loom_assets` | 51.8 ms（其中 stdlib 集合 `hashlib/json/re/shutil/threading/uuid` 单独 47.6 ms） | **全懒加载**：`sceneio.py:181`、`build_game.py:37`、`editor.py:911/919/931`、`agent_commands.py:2489/2521` 均在函数体内 |
| `sceneio` HEAD | 735.1 ms | vs beta5 776.2 ms → **-41.1 ms（噪声内，无回归）** |
| `loom_components` HEAD | 192.3 ms | vs beta5 202.7 ms → -10.4 ms |
| `loom_pass`/`loom_pass_gl` | 63.4 / 73.6 ms | 渲染路径，非本次范围 |

**（已证伪，登记 D-08）新依赖拖累启动**：`numpy` 在 `vk_renderer.py` 新增的是函数内 import（`vk_renderer.py:1008`）；
`loom_assets` 无第三方依赖（7 个 stdlib），调用点全部懒加载 → **本范围内新增启动成本 ≈ 1.5 ms**，`sceneio` 反而略快（噪声）。

### 2.6 附带发现（先证伪再证真，全部为"已确认无问题"）

| ID | 命题 | 结论 | 证据 |
|---|---|---|---|
| D-01 | `_CACHE` 无界增长 | **DISPROVED** | 50 个项目各 load+save 后 `len(_CACHE)=1`（`save_index` 每次 `clear()`，`loom_assets.py:370`） |
| D-02 | `safe_asset_name` 处理非法名会崩/越界 | **DISPROVED** | 500 个随机串（含控制字符/保留名/超长）→ 非法结果 **0**，最长 60 字符 |
| D-03 | `is_inside` 前缀兄弟/跨盘/None/`..` 误判 | **DISPROVED** | 7 组边界全对：`D:/p` vs `D:/pq/a` → False；跨盘 → False；`..` 归一 → True |
| D-04 | 17 个公共函数对 10 类退化值会崩 | **部分 DISPROVED** | 340 次调用的异常全部是"参数类型不是路径/元数不匹配"（`save_index(root,index)` 需 2 元），无静默错算；唯一静默错算的是空根（F-03） |
| D-05 | `LOOM_AB_SCENES=','` 空集仍 rc=0 | **DISPROVED（已修）** | `test_ab_gl_vk.py:418-421` 与 `708-710` 均 `return 1` |
| D-06 | 版本闸门有入口漏接 | **DISPROVED** | 5 个加载入口全接 + 播放器弹窗；`test_scene_version_gates`/`_player` 全 PASS |
| D-07 | `LOOM_NO_PHYSICS` 只在一端兑现 | **DISPROVED** | 3 处同判据（见 §2.4），`test_animation_base` ⑧ 三连 PASS |
| D-08 | 新增 import 拖慢启动 | **DISPROVED** | 见 §2.5 |

### 2.7 [REGRESSION] 相对 beta5 的行为变化

| ID | 变化 | 判定 |
|---|---|---|
| R-01 | `SCENE_VERSION` 10→11 + 写 `min_engine_version`（`sceneio.py:58/1822`） | 设计内（D7）。beta5 引擎**不会**拦 v11 场景（它不认该字段），v11 的 `animator.speed/clip_meta` 会被 beta5 静默丢弃 → 见 §4 Q2 |
| R-02 | `undo.snapshot` 动画槽从 3 元变 4 元（`undo.py:123-127`） | 兼容（`len(val)>3`），并修掉"改快照污染模型"的旧 bug |
| R-03 | 新增 `Assets/` 向上扫描（`find_project_root` ≤10 层，`loom_assets.py:159-175`） | 设计内；风险见 F-03 |
| R-04 | 加载成本 0 ms → 1 ms/条（F-01） | 新增成本，规模相关（本报告首要） |

---

## 3. 统计

| 项 | 数量 |
|---|---|
| 审查文件 / 新增行 | 12 个 / **+3063 −356** |
| 新增公共函数（12 文件） | **138**（sceneio 40、loom_assets 43、loom_components 17、run_player 10、editor 8、agent_commands 7、scene_driver 6、build_game 6、game_player 1） |
| 探针 | 8 个（`final_02_env/import/state2/scale/scale2/saveidx/deg/root.py`） |
| 退化输入调用 / 异常 | 340 次 / 全部为"参数类型/元数"（D-04） |
| env 开关核对 | 14 个（默认+非法值**实测**），其中 **6 个零文档登记** |
| 结论：PROVED（引入问题） | **11**（F-01…F-11） |
| 结论：DISPROVED | **8**（D-01…D-08） |
| 结论：P-UNKNOWN | **2**（见下） |
| 等级分布 | P1 = 0；P2 = 5（F-01/F-02/F-03/F-08/F-09）；P3 = 6（F-04…F-07/F-10/F-11） |
| 复跑测试 | `test_asset_guid` 152 PASS / 0 FAIL；`test_animation_base` 115 PASS / 0 FAIL；`test_scene_version_gates` / `_player` ALL PASS |
| 受跟踪文件改动 | 0（`git status --porcelain` 为空） |

**P-UNKNOWN（需更多信息才能定）**
- U-01：VK 侧 `LOOM_POST=0` 与 GL 的逐像素一致性——需 GPU 跑 `test_ab_gl_vk.py`（本轮未跑，属 01/渲染范围）。
- U-02：F-01 在真实大项目上的用户可感时延——仓库内无 1 万条资产的真实项目，数字来自合成索引（口径已如实标注）。

---

## 4. 需人类裁决的问题（封闭式）

1. **F-01 索引校验成本是否本版必修？**
   A：不动（当前项目资产数 <50，1 ms/条 不可感，登记 beta7）；
   B：加载路径改惰性 + 只对"已存在文件"做 realpath（预计 1 ms/条 → `0.02 ms/条，改动集中 `loom_assets.py:278-330/143-156`）；
   C：给 `validate_index` 加"条数上限 + 抽样"（会弱化越界保证）。
   （主审倾向 B，因为 `inspect_index` 每次 EAI 调用都全量重跑。）

2. **D7 与旧引擎的关系要不要补一条硬证据？**
   R-01 表明：beta5 引擎读 v11 场景**不会**拒绝（它不认识 `min_engine_version`），只会静默丢 `speed/clip_meta`。
   A：接受（D7 只约束"beta6 及以后"）；
   B：在发布说明里明确写"beta6 场景不可回退到 beta5 编辑"；
   C：在场景里额外写字段让旧引擎至少告警（需先确认 beta5 的 `migrate` 行为）。

3. **6 个零文档的 env 开关怎么处理？**
   （`LOOM_POST_STAGE`/`LOOM_FAULTHANDLER`/`LOOM_BLOOM_THRESHOLD`/`LOOM_BLOOM_KNEE`/`LOOM_BLOOM_STRENGTH`/`LOOM_POST_EXPOSURE`）
   A：全部补进 `使用操作指南.txt` 的"逃生门/诊断开关"一节（含默认值与合法值）；
   B：删掉诊断类（`LOOM_POST_STAGE` + `LOOM_BLOOM_*`/`LOOM_POST_EXPOSURE`），只留 `LOOM_POST` 与 `LOOM_FAULTHANDLER` 并补文档；
   C：只补文档，不动代码（`loom_post.py:48` 的"定稿前清理"继续挂着）。
