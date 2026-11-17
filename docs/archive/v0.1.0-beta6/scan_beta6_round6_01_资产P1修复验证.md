# 资产 P1 修复验证 · 独立复核（beta6 轮6 / 编号 01）

- 复核对象：HEAD = `308a6d1`；被验修复提交 `4de3b4b`（R5-01 三个 P1 + 6 个 P2；其中 P1-2 主体实际落在 `fb4857f` 携带的 loom_assets/sceneio 改动里，见 §0.2）
- 复核者：独立复核子代理（只读，不参与实现）
- 方法：SCAN_PROTOCOL 三阶段 + 桌面两份方法论（白盒契约/黑盒实现/灰盒验证；粗筛→双臂推演→实操闭环）
- **判定标准：能否证伪**。每条"已修复"的宣称，先构造反例尝试打破；打不破才记 P-DISPROVED（修复成立）
- 结论摘要：**修复主体成立（11 项反例打不破）；但发现 1 个 P1 级回归（新建场景复活上一场景失效引用）+ 4 个 P2 + 2 个 P3 残留**
- 本轮受跟踪文件改动：**0**（只写 `Loom/tests/_tmp/audit_b6r6_01_*` 与本报告；`git status` 里的 3 个 M / 1 个 ?? 均为其他并发子代理在途改动，见 §0.3）

---

## 0. 范围与方法

### 0.1 文件清单（行数取自 `(Get-Content <f>).Count`）

| 文件 | 行数 | 本轮读/验的段 |
|---|---|---|
| `Loom/loom_assets.py` | 762 | 53-67 name 净化、199-310 load/inspect/validate、313-340 save/user_delta、363-399 for_dir/open_root、402-490 resolve、578-634 import |
| `Loom/sceneio.py` | 2189 | 187-298 资产问题/保留引用、976-1119 天空盒、1189-1325 材质槽、1328-1423 孤儿材质、1755-1834 scene_to_dict、1837-1930 scene_from_dict |
| `Loom/editor.py` | 2867 | 907-949 项目根/上下文、1120-1185 保存、1230-1285 加载、1287-1316 新建场景 |
| `Loom/build_game.py` | 435 | 41-126 资产引用识别/硬失败、286-435 main |
| `tools/migrate_scene_assets_v11.py` | 213 | 44-156 migrate_scene、177-209 main |
| `Loom/agent_commands.py` | 3973 | 1693-1752 set_texture、1836-1875 set_env、2425-2530 asset_import/get/list + scene_assets_check |
| `Loom/tests/test_asset_guid.py` | 817 | 433-811 轮5 新增断言（含 P2-⑤ 的 helper 直调） |
| `Loom/scene_driver.py` | — | 131-234 资产解析、599-700 VK load_from_data（P1-3 "VK 入口"） |

### 0.2 提交事实（先说清"谁修的"）

```
git log --oneline -6 -- Loom/loom_assets.py
# 4de3b4b / fb4857f / f2d43b1
git show --stat --format='%h %s' fb4857f -- Loom/loom_assets.py Loom/sceneio.py
# fb4857f（一个物理/AABB 提交）同时改了 loom_assets.py +232 / sceneio.py +256
git show 4de3b4b -- Loom/loom_assets.py
# 4de3b4b 对 loom_assets.py 只有 +17 行（告警文本统一）
```

结论：**P1-2/P1-3 的主要实现混在 `fb4857f`（物理提交）里**，`4de3b4b` 只补了 P1-1/打包/迁移/可见性。轮5 报告的"B1 文件自 `f2d43b1` 起未被改动"只在 `fb4857f` 之前成立。这是**提交卫生问题**（P2/可维护性），不是功能 bug，但与"整改可审计"直接冲突：整改内容无法从提交信息追溯。

### 0.3 环境与纪律

- Python 3.12.10；所有探针加 `$env:PYTHONIOENCODING='utf-8'`，`LOOM_USER_ROOT`/`LOOM_GAME_DIR` 指到系统临时目录（`%LOCALAPPDATA%` 零改动）。
- 探针只写 `Loom/tests/_tmp/audit_b6r6_01_*.py`（已被 `Loom/.gitignore:22 tests/_tmp/*` 忽略）；工作区验证产物全部在 `tempfile.mkdtemp()`。
- `git status --porcelain` 中 `M Loom/loom_components.py`、`M Loom/loom_frame_components.py`、`M Loom/loom_physics.py`、`M Loom/scene_driver.py`、`M Loom/tests/test_animation_base.py`、`M docs/design/待裁决清单_beta6.md`、`?? docs/audit/scan_beta6_round6_0{2,3}_*` **不是本审计产生**（并发子代理），本审计未做任何 git 写操作。
- 其中 `scene_driver.py` 的在途改动只落在 26 / 1078-1079 / 1318-1350 行（`git diff -U0` 的 hunk 头可查），**未触及**本轮 V-04 使用的资产段 131-234 与 599-700，故 VK 侧结论不受影响。

### 0.4 本轮跑过的命令（只读 + 临时目录）

| 命令 | 用途 | 结果 |
|---|---|---|
| `cd Loom; python tests/test_asset_guid.py` | 官方回归（轮5 扩到 110 条断言） | `PASS=110 FAIL=0 总结果: ALL PASS` |
| `python tests/test_sceneio.py` / `test_skybox_scene.py` | 相邻模块回归（防修复引入连带破坏） | 两者 `ALL PASS` |
| `python tests/_tmp/audit_b6r6_01_p1_1_preserve_refs.py` | P1-1 反例矩阵 A–J | `PASS=52 FAIL=0` |
| `..._p1_1b_new_scene_stale_ref.py` | 新建场景的反向边界 | `PASS=3 FAIL=3`（发现 D-01） |
| `..._p1_2_index_partial.py` | P1-2 partial/三态/自愈 | `PASS=13 FAIL=1`（D-05） |
| `..._p1_3_delta_guard.py` | P1-3 delta 8 种坏值 × GL/VK | `PASS=43 FAIL=0` |
| `..._p2_1_asset_name.py` | name 净化 28 个反例 | `PASS=96 FAIL=2`（D-06） |
| `..._p2_4_migrate.py` | 迁移闸门/只读/批处理 | `PASS=14 FAIL=0`（含 D-03/D-07 的复现断言） |
| `..._p2_5_build_pack.py` | **真实 build_game.main()** 四种布局 | `PASS=11 FAIL=1`（D-02） |
| `..._p16_index_concurrency.py` | 两进程确定性交错写索引 | `PASS=2 FAIL=1`（D-04） |
| `git show engine-v0.1.0.beta5:Loom/sceneio.py | Select-String 'min_engine_version|check_engine_version'` | 旧引擎是否读闸门字段 | **无输出**（beta5 无读取点） |

---

## 1. 粗筛清单（含跳过登记）

### 1.1 疑似项（按"宣称的修复"逐条落位）

| ID | 宣称/位置 | 标签 | 初筛方向 |
|---|---|---|---|
| V-01 | P1-1 `_asset_ref_slots`/`_skybox_ref`/`cam._skybox_ref`（sceneio.py:210-284, 1199-1284, 1809-1813, 1868-1878） | SEM-SILENT / IFACE-PARTIAL | 是否所有失败路径都保留？写回是否会被"成功分支"覆盖？ |
| V-02 | P1-1 显式清空 `clear_asset_slot`（sceneio.py:241-247 + agent_commands.py:1704-1715, 1855-1865） | SEM-SILENT | 是否只有这两条清空入口？其它置 None 的路径会不会让旧引用复活？ |
| V-03 | P1-1 新建场景（editor.py:1287-1316） | SEM-SILENT / [REGRESSION] | 换场景时 `_skybox_ref/_skybox_valid/_asset_errors` 是否随场景清空？ |
| V-04 | P1-2 `validate_index`/`load_index`/`inspect_index`/`open_root`（loom_assets.py:199-310, 379-399） | AUDIT-DEADCODE / IFACE-PARTIAL | partial 是否真可用？坏条目剔除后是否会被写回？诊断串是否区分缺失/损坏？ |
| V-05 | P1-2 `asset_list`/`scene_assets_check`（agent_commands.py:2486-2530） | SEM-MISMATCH | 三态是否齐全？partial 会不会被报成 ok/missing？ |
| V-06 | P1-2 导入自愈（loom_assets.py:599-634） | SEM-SILENT | 正文被删后 `asset_import` 是否真的修复？ |
| V-07 | P1-3 `resolve` delta 判定（loom_assets.py:434-439）+ VK `_asset_tex/_asset_env`（scene_driver.py:131-185） | BND / IFACE-ERROR | 非 dict delta 是否所有入口都只"跳过+告警"？ |
| V-08 | P2-① `safe_asset_name`/`_unique_dest`/`import_cubemap`（loom_assets.py:56-67, 578-591, 657-668） | BND-UNICODE / TOOL-HEURISTIC | 绝对路径/`..\\`/保留名/超长名能否绕过？ |
| V-09 | P2-② 天空盒进体检（sceneio.py:1877-1878） | AUDIT-ASYMMETRY | 是否与材质槽同口径？会不会重复计数？ |
| V-10 | P2-③ 六面图逐面指纹（loom_assets.py:445-474, 669-691） | AUDIT-DEADCODE | `face_stats` 缺失时是否静默？mtime 相同内容不同能否发现？ |
| V-11 | P2-④ 迁移闸门（migrate:143-156） | IFACE-VERSION | 字段是否"写进去"？旧引擎是否真的拒绝？n=0 时呢？ |
| V-12 | P2-⑤ 打包硬失败（build_game.py:59-111, 408-415） | SEM-SILENT / OVERFIT-TESTENV | 真实 `main()` 是否能走到 `has_assets=True` 的拦截分支？会不会误伤 path-only 场景？ |
| V-13 | P2-⑥ 可见性（editor.py:1174-1180, 1269-1279；game_player.py:135-142） | SEM-SILENT | `_notify` 是否只在保存时？新建场景的误报呢？ |
| V-14 | R5 P-16 `save_index`（loom_assets.py:313-327） | BND-CONCURRENCY | `tmp` 已 PID 化，丢条目是否仍在？ |

### 1.2 跳过登记（四类理由之一）

| 位置 | 跳过理由 | 出处 |
|---|---|---|
| `loom_assets.py:123-136 is_inside` | 语言/标准库规范保证：`commonpath` 跨盘抛 `ValueError` 已捕获返回 False；探针 05 用 UNC 绝对路径实测未逃逸 | Python `os.path.commonpath` 文档 + probe 05 |
| `sceneio.py:1044-1119 _emit_skybox_checked` 的越界判定 | 属 beta5 A3=B 契约，非本轮 P1 修复内容；本轮只验"失败时是否写回原引用" | 轮5 报告 P-01 修复范围 |
| `loom_assets.py:330-338 _load_user_delta` 的构造 | 用户层只读；本轮 probe 04 覆盖"文件非对象/`assets` 非 dict" | probe 04 |
| `editor.py:1440-1479` 资产面板每帧 `_asset_context()` | 性能属 D1 计量，`load_index` 有 stat 缓存；轮5 已登记为观察项，本轮无新证据 | 轮5 报告 0.2 |
| `loom_assets.py:501-534 ctx.texture/cubemap` 的 Texture/Cubemap 构造 | 有既有回归（test_asset_guid ①–⑥/⑬）且本轮 probe 01 端到端重载通过 | test_asset_guid.py:139-430 |

---

## 2. 逐项裁决（8 段式）

> 记法：**V-xx = 宣称的修复行为**（反例打不破 → P-DISPROVED = 修复成立）；**D-xx = 本轮发现的缺陷**（P-PROVED）。8 段式统一按：位置 → 契约 → 路径枚举 → 实际 → 差异 → 触发 → 验证 → 影响。

### V-01 P1-1 主路径（缺贴图 / 索引坏 / 索引缺 / 六面图缺一面 / delta 坏）→ **P-DISPROVED（修复成立）**

1. **位置**：`sceneio.py:210-284`（保留槽位/计数）、`1228-1284`（贴图槽四个失败分支都 `_keep_slot_ref`）、`1189-1215`（`_emit_material._slot` 在对象为 None 时回写 kept ref）、`1809-1813`（天空盒回写）、`1101-1108`/`1111-1119`（相机天空盒回写）、`1868-1878`（加载时置 `_skybox_ref`）、`1377-1382`（只有失效引用的材质不算孤儿）。
2. **契约**：Q-B1-1=A「解析失败原样保留引用；只有用户显式清空才移除」（`sceneio.py:211-216, 241-247`）。
3. **路径枚举**（读侧失败形态 × 写侧槽位）：
   - 贴图：文件缺失 → `1244`；旧 path 解码失败 → `1266`；只有 guid 且无索引/条目不存在 → `1271`；资产段异常 → `1281`。四分支全覆盖。
   - 环境贴图：`1298/1311/1319/1323` 四分支全覆盖。
   - 场景天空盒：加载失败且 raw 是 dict → `sceneio.py:1868-1878` 保留；`scene_to_dict:1810-1813` 在 `_sb_dict is None or _skybox_valid is False` 时整体替换为 kept ref。
   - 相机天空盒：`_apply_cameras:1159-1171` 保留、`_emit_camera_skybox:1104-1108` 在发射结果为 None 时回写。
   - 写回优先级：对象存在 → 写当前对象（成功分支已 `_clear_slot_ref`）；对象 None → 写 kept ref。
4. **实际**（probe 01；每例"打开 → 保存 → 重开 → 再保存"）：
   ```
PASS 前置: 落盘只写 guid（材质+场景天空盒）  {'name': 'sky', 'guid': '30ddfa86…'}
PASS A 保存后 albedo.guid 不变  {'guid': '4277ba4a…', 'name': 'a'}       # 缺贴图文件
PASS B 保存后 场景天空盒 guid 不变  {'name': 'sky', 'guid': '30ddfa86…'}  # 六面图缺 py.png
PASS C 保存后 场景天空盒 guid 不变  …                                    # 索引 JSON 损坏
PASS D 保存后 场景天空盒 guid 不变  …                                    # 索引文件缺失
PASS E delta 坏 -> 仍按项目层解析出贴图（不是"保留失效引用"）
PASS J 坏 delta + 缺文件: 原因点名文件缺失（delta 不掩盖真因）
PASS H 资产修复后重开：无资产问题 / 贴图+六面图解析成功
PASS H 修好后再保存：仍写原 guid（不漂移、不回退 path）
```
   连续两次保存 guid 不漂移；相机的两条天空盒（资产 guid + 旧 paths）都未被改写。
5. **差异**：无。预期"保留 + 持续告警"与实际一致；每轮 `asset_issue_notice` 都返回"N 条失效引用已保留"。
6. **触发条件**：不适用（这是"应当无 bug"侧；上述 5 种输入全部命中）。
7. **验证**：`cd Loom; python tests/_tmp/audit_b6r6_01_p1_1_preserve_refs.py`（`RESULT: ALL PASS`，52 条断言）。
8. **影响与等级**：P-DISPROVED —— 轮5 P-01（P1，保存销毁 guid）**已修复**，含"连续保存不漂移"与"资产修好后自愈"。

### V-02 显式清空仍能清掉 → **P-DISPROVED（修复成立）**

1. **位置**：`sceneio.py:241-247 clear_asset_slot`；调用点只有 `agent_commands.py:1704-1715`（`set_texture` 无 path）与 `1855-1865`（`set_env` 无 paths/color）。
2. **契约**：Q-B1-1=A 的边界「用户主动清空才算移除」（`sceneio.py:244-245`）。
3. **路径枚举**：贴图 → `set_texture`；环境贴图 → `set_env`；场景天空盒"清空" → `skybox_clear`（A1 语义=恢复默认蓝天，必须写 solid_color 而不是旧 guid）。全仓置 None 的业务路径只有这两条（其余命中在 `loom_material.py` 初始化与测试桩）。
4. **实际**（probe 01 F/G）：
   ```
PASS F set_texture 无 path -> 显式清空 ok  {'ok': True, 'result': {... 'albedo': None}}
PASS F 显式清空后 albedo 键消失（旧引用不得复活）
PASS G 显式恢复默认蓝天后，保存写 solid_color（不再写 deadsky）
```
5. **差异**：无（清空后没有 `_asset_ref_slots` 复活）。
6. **触发条件**：不适用。
7. **验证**：同一探针 F/G 段。
8. **影响与等级**：P-DISPROVED。**唯一例外见 D-01**（新建场景不是"显式清空"，没走 `clear_asset_slot`）。

### V-03 P1-2 partial 索引可用 / 三态 / 自愈备份 → **P-DISPROVED（修复成立）**

1. **位置**：`loom_assets.py:258-310 validate_index`（逐条剔除）、`199-231 load_index`（ok / partial+reason / None）、`231-256 inspect_index`、`379-399 open_root`（create 透传 + `.bak-时间戳` 备份 + 覆盖）。
2. **契约**：Q-B1-2=A「剔除坏条目 + 明示条数与原因」；`load_index` docstring（`201-203`）「ok=True + reason 非空 = 部分可用」。
3. **路径枚举**：A 文件缺失 → `inspect=missing`、`for_dir(None)`；B 全合法 → ok；C 单条坏（未知 type / 越界 src / import 非 dict）→ 剔除+其余可用；D JSON 坏 → corrupt + `create=True` 备份后重建；E 顶层非对象/缺 `assets` → invalid。
4. **实际**（probe 03）：
   ```
PASS P1-2a 一条坏 -> 索引仍可用（ok=True）  索引有 2 条坏条目已剔除: bbbb…: 未知类型 'nonsense'; cccc…: src 越界/相对路径 (收到 '../escape.png')
PASS P1-2c 好条目保留 / 坏条目剔除  ['4f0ca919…']
PASS P1-2e partial 索引下 asset_import 仍可用（坏条目不被 resurrect）
PASS P1-2f asset_list: partial + valid=True + warnings  ('partial', [...])
PASS P1-2g asset_list: corrupt 不谎报"缺文件"  ('corrupt', "资产索引损坏 (JSONDecodeError…")
PASS P1-2h scene_assets_check: 索引坏 -> ok=False（不再假绿）  (False, 'corrupt')
PASS P1-2j create=True 可自愈 + 先备份  ['…assets.json.bak-20261110-141459']
PASS P1-2k 备份内容是原坏文件（可人工抢救）  { broken json
PASS P1-2m asset_list: missing 三态之一  missing
```
   附注：partial 状态下**首次 import 落盘后**坏条目被永久剔除（`save_index` 写的是已剔除的 index），随后 `asset_list` 报 `ok` —— 这是设计预期的"自愈"；"先测 asset_list 再 import"已验证 partial 能报出。
5. **差异**：无。
6. **触发条件**：不适用。
7. **验证**：`cd Loom; python tests/_tmp/audit_b6r6_01_p1_2_index_partial.py`。
8. **影响与等级**：P-DISPROVED —— 轮5 P-02（P1）**已修复**；诊断串区分 missing/corrupt/invalid/partial。

### V-04 P1-3 非 dict delta 全入口不崩 → **P-DISPROVED（修复成立）**

1. **位置**：`loom_assets.py:434-438`（`delta is not None and not isinstance(dict)` → `_warn` 后 `delta=None`）；入口：GL/编辑器/GL 播放器共用 `sceneio.scene_from_dict`（`runtime.py:148` PlayerApp），VK 侧 `scene_driver.py:615-645`（`asset_context` → `build_materials` → `_asset_tex:136-141`）。
2. **契约**：`loom_assets.py:8`「解析失败一律返回 `(obj, valid, reason)`」；F7「资产异常不得击穿已清空场景」。
3. **路径枚举**：delta 取值 8 种（str/int/list/bool/None/`{'src':[...]}`/`{'src':{...}}`/`{'foo':1}`）× 2 后端；另加用户层文件整体非对象 / `assets` 非 dict。
4. **实际**（probe 04）：
   ```
PASS GL/编辑器 delta=str 不崩 / PASS VK load_from_data delta=str 不崩
PASS VK delta=str 有出声  '[资产] 用户层 delta 条目不是对象 (ff683cfb…) -> 已忽略，按项目层解析'
…（int / list / bool 同）
PASS GL/编辑器 delta=list 保存引用不漂移  {'guid': '4c099109…', 'name': 't'}
PASS user_delta 顶层 assets 非 dict -> 不崩（整体忽略）/ 用户层文件不是对象 -> 不崩
```
   `None` 视为"没有 delta"（不告警），`{'foo':1}` 视为合法 dict（不告警）—— 二者都不是坏值，判定正确。
5. **差异**：无（8 种坏值 × 两端，无一抛出；GL 与 VK 同口径）。
6. **触发条件**：不适用。
7. **验证**：`cd Loom; python tests/_tmp/audit_b6r6_01_p1_3_delta_guard.py`（`ALL PASS`，43 断言）。
8. **影响与等级**：P-DISPROVED —— 轮5 P-03（P1）**已修复**。残留观察（P3，不计入）：delta **dict 但 src 不是字符串**时不做类型判定，`str(src)` 会把 `['Assets/Textures/t.png']` 当文件名，reason 变成"资产文件缺失: ['Assets/…']"——不崩但措辞失真（`loom_assets.py:439-444`）。

### V-05 P2-① name 净化：越界堵死 → **P-DISPROVED（核心宣称成立）**；保留名/超长 → **见 D-06**

1. **位置**：`loom_assets.py:56-67 safe_asset_name`（basename + 非法字符表 + 去首尾点空格 + `..`→`_`）、`578-591 _unique_dest`（拆分 stem/ext 后再 `is_inside(assets_dir, dest)` 兜底）、`657-668`（cubemap 目录名同源）、第二道闸 `validate_index:296-304`（src 必须在 `Assets/` 之下）。
2. **契约**：`loom_assets.py:5`「资产正文 = 项目根下 `Assets/<Type>/…`」；轮5 P-04 修复方向「basename + 非法字符替换 + `..` 检测；validate_index 追加 src 必须在 Assets 之下」。
3. **路径枚举**：`../../escaped`、`..\\..\\escaped`、`C:\\Windows\\evil`、`C:/x`、`\\\\?\\C:\\x`、中文名、`evil. `/`evil.`、`.`/`..`/空、`a/b/c.png`、CON/NUL/AUX/COM1/LPT1/CON.png/NUL.png、300 字符、含 `\\x00`、首尾空格；每例独立项目 + 独立源内容（否则 sha 去重短路 —— 探针前两版因此全部"假绿"）。
4. **实际**（probe 05）：
   ```
PASS 贴图 name='../../escaped' 落在 Assets/Textures 下  Assets/Textures/escaped.png
PASS 贴图 name='C:\\Windows\\evil' 落在 Assets/Textures 下  Assets/Textures/evil.png
PASS 贴图 name='\\\\?\\C:\\x4' 落在 Assets/Textures 下  Assets/Textures/x4.png
PASS 贴图 name='中文贴图' 落在 Assets/Textures 下  Assets/Textures/中文贴图.png
PASS 贴图 name='CON' 落在 Assets/Textures 下  Assets/Textures/CON_2.png    # 被 exists() 碰撞顺延
PASS 所有用例都没有写出 <proj>/Assets/ 之外
PASS 索引里越界 src 被剔除（第二道闸）
FAIL 贴图 name='LPT1' 不抛异常  ValueError("资产目标路径越界（必须是 Assets/ 之下）: …Assets\\Textures\\LPT1.png")
FAIL 贴图 name='aaaaaaaaaaaaaaaaaa...' 不抛异常  OSError(22, '文件名、目录名或卷标语法不正确。', …)
```
   cubemap：`../../evil dir → Assets/Cubemaps/evil dir`、`C:\\abs → Assets/Cubemaps/abs`、`CON/NUL` 被拒绝（有 reason）。
5. **差异**：核心契约（不得写出 `Assets/` 之外、不得逃出项目根）**成立**；但"净化"不完整：Windows 保留设备名未被识别，且 `is_inside` 对 `LPT1.png` 的 realpath 判定制造了一个**误导性"越界"异常**；300 字符名越过 Win32 文件名上限（255）抛 `OSError(22)`。两者都被 `agent_commands.dispatch:355-357` 兜住（返回 `{'ok':False,'error':repr(e)}`），编辑器不崩，但 EAI 用户看到的是异常字符串。
6. **触发条件**：资产名恰为 LPT1/NUL，或名字 > 255 字符。来源：脚本/EAI `asset_import` 传 name、编辑器把外部文件名当 name。
7. **验证**：`cd Loom; python tests/_tmp/audit_b6r6_01_p2_1_asset_name.py`（96 PASS / 2 FAIL）。
8. **影响与等级**：核心 P2-① **P-DISPROVED**；保留名/超长 → **D-06 = P-PROVED（P3）**。

### V-06 P2-② 天空盒进体检 / P2-③ 六面图指纹 / P2-⑥ 可见性 → **P-DISPROVED（修复成立）**

1. **位置**：`sceneio.py:1877-1878`（场景天空盒失败 → `record_asset_error('skybox',…)'`）、`1168-1170`（相机天空盒 → `'cameras[].skybox'`）、`loom_assets.py:445-474`（resolve 逐面 stat→sha）、`669-691`（导入写 `face_stats` + 总字节数）、`editor.py:1174-1180/1269-1279`（保存/打开 `_notify`）、`game_player.py:135-142`（发布版日志出口）。
2. **契约**：轮5 P-05「天空盒失败必须进 `scene_assets_check`」；P-06「`fingerprint` = 内容指纹」；P-17「GUI 可见」。
3. **路径枚举**：天空盒失败三态（guid 不在索引 / 缺面 / 缺目录）→ 全部 `valid=False` + `record_asset_error`；六面图三态（mtime 变内容不变 / 内容变 / 缺面）→ 分别"不打扰"/"内容已变更"；可见性三入口（编辑器打开、编辑器保存、播放器启动）。
4. **实际**：probe 01 B/C/D 的 `asset_errors` 都含 `('skybox', guid, '六面图缺面: py.png')` 与 `('cameras[].skybox',…)`；`test_asset_guid.py:637-652`（`ok:false, count>=1`）与 `656-674`（`size>6`、`face_stats` 6 项、"内容已变更"）PASS；`test_asset_guid.py:755-792` 保存后 `_notify` 捕获"已保存（资产：2 条资产问题，2 条失效引用已保留…）"。
5. **差异**：无。
6. **触发条件**：不适用。
7. **验证**：`cd Loom; python tests/test_asset_guid.py` 中 P2-②/P2-③/P2-⑥ 段全 PASS。
8. **影响与等级**：P-DISPROVED（轮5 P-05/P-06/P-17 已修复）。

### V-07 P2-④ 迁移：字段落盘 / dry-run 只读 / 批处理不中断 → **P-DISPROVED**；"旧引擎拒绝" → **D-03（P2）**；n=0 不补字段 → **D-07（P3）**

1. **位置**：`migrate_scene_assets_v11.py:150-155`（`data['min_engine_version'] = ENGINE_VERSION`；`if n and not dry_run` 才 `save_json_atomic`）、`57`（dry-run `create=(create or dry_run), readonly=dry_run`）、`187-194`（逐场景 try）、`208-209`（bad → 1）。
2. **契约**：轮5 P-07「迁移产物与编辑器保存产物在版本闸门字段上等价」+ P-08「dry-run 只读预演」+ P-13「逐场景报告不中断」。
3. **路径枚举**：v10 有 path 引用（dry-run/真跑）；已迁移 v11 且无字段（n 可能为 0）；高版本场景混在批中间；索引损坏 + dry-run。
4. **实际**（probe 06）：
   ```
PASS dry-run: 新项目可预演（changed>=2、无失败）  {… 'min_engine_version': '0.1.0.beta6', 'dry_run': True}
PASS dry-run: 不写 Assets/（真只读）  ['scene.json', 'sky', 'tex']
PASS 迁移产物 min_engine_version 已落盘  0.1.0.beta6
PASS 迁移产物在当前引擎可加载且资产 0 问题
PASS 批处理: 高版本之后的场景仍被迁移（不整批中断）  [('ok3.json', 11, []), ('future.json', None, ['版本闸门拒绝: …']), ('ok4.json', 11, [])]
PASS 已迁移 v11 无变化: 报告说 min_engine_version=0.1.0.beta6
PASS R6 发现: 报告写"已带闸门字段"，但磁盘文件根本没被改写（字段仍缺）  (0, None)
PASS R6 发现: 该文件仍能通过当前闸门（无字段=不设闸）
```
   旧引擎侧（只读 git 证据）：
   ```
git show engine-v0.1.0.beta5:Loom/sceneio.py | Select-String 'min_engine_version|check_engine_version'
# （无输出：beta5 没有任何读取点）
git show engine-v0.1.0.beta5:Loom/sceneio.py | Select-Object -Skip 900 -First 45
# if ref and ref.get('path'):  → 只有 guid 的引用直接跳过（贴图静默丢失）
```
   字段引入提交：`git log -S 'min_engine_version' --oneline -- Loom/sceneio.py` → `d635f35`（beta6 C1）。
5. **差异**：① 字段"写进去"成立，但"旧引擎明确拒绝"对 **beta5**（tag `engine-v0.1.0.beta5`）不成立 —— 旧引擎不认这个字段，仍会静默打开 v11 场景、并因只读 `path` 丢贴图/天空盒。该修复只能防"C1 之前的 beta6 构建"，**不能防 beta5**。② 已迁移 v11 场景（旧工具产物、无字段）再跑迁移时 `n=0` → 文件不落盘，而 `rep['min_engine_version']` 已写 beta6 → 报告失真、闸门字段永远补不上。
6. **触发条件**：① 用户用 beta5 打开迁移产物（轮5 P-07 的原始场景）；② 对"旧版迁移工具已处理过"的场景再跑本工具。
7. **验证**：`cd Loom; python tests/_tmp/audit_b6r6_01_p2_4_migrate.py`；旧引擎证据用上面的 `git show`。
8. **影响与等级**：字段/dry-run/批处理 = P-DISPROVED；**D-03 = P-PROVED（P2：宣称的"旧引擎拒绝"不成立，原始风险仍在）**；**D-07 = P-PROVED（P3：n=0 时报告与磁盘不一致）**。

### V-08 P2-⑤ 打包硬失败 → **P-DISPROVED（主场景成立）**；索引坏时拦截 → **D-02（P2）+ [OVERFIT-TESTENV]**

1. **位置**：`build_game.py:69-85 scene_asset_refs`、`88-111 require_assets_or_exit`、`408-415`（`_has_assets = copy_project_assets(...)`；**只有 else 分支**调 `require_assets_or_exit`）、`114-126 copy_project_assets`（`find_project_root` 只看 `assets.json` 是否存在，`loom_assets.py:139-155`）。
2. **契约**：轮5 P-09「场景含 guid 引用但无法随包 → `SystemExit`」+ 修复提交宣称「资产夹在、但索引坏了 -> 必须拦」。
3. **路径枚举**：A 无索引 + 纯 guid；B 无索引 + 只有 path/纯色；C 索引文件存在但 JSON 坏 + 纯 guid；D 索引可用 + guid。`has_assets=True` 分支（`98-106`）在 `main()` 下不可达 —— `_has_assets` 为 True 时根本不调用该函数。
4. **实际**（probe 07，**真实 `main()`**，伪 runtime/伪 BIN_DIR，pack 真实落盘）：
   ```
[A] rc='场景引用了项目资产库（4 条 guid 引用），但找不到 Assets/assets.json: …'
PASS A 真实 main(): 有 guid 无资产库 -> SystemExit
PASS A 没有产出游戏包（硬失败先于 pack）
PASS B 真实 main(): 无托管引用且无资产库 -> 正常出包（不误伤）
PASS B 产出 游戏包.lsc
[C] rc=None err=None
FAIL C 真实 main(): 索引损坏 + guid 引用 -> 应拒绝出包  (None, 'None')
PASS C 索引坏时包内确实带着坏索引（玩家侧死 guid）
PASS D 真实 main(): 索引可用 + guid 引用 -> 不拦
```
5. **差异**：`require_assets_or_exit(..., has_assets=True)` 的"索引不可用 → 拒绝"分支是**死代码**；官方用例 `test_asset_guid.py:746` 直接调 helper（`require_assets_or_exit(bscene, data, True)`）所以"绿"，但真实入口 `main()` 永远走不到 —— 典型 **OVERFIT-TESTENV**（测了可达性不存在的分支）。
6. **触发条件**：项目 `Assets/assets.json` 被写坏/半写（P-02 的触发器），同时场景有纯 guid 引用 → 构建绿、包内带坏索引、玩家侧贴图全丢。
7. **验证**：`cd Loom; python tests/_tmp/audit_b6r6_01_p2_5_build_pack.py`（11 PASS / 1 FAIL）；静态对照 `build_game.py:408-415` 与 `98-106`。
8. **影响与等级**：主场景（无索引+guid → 硬失败；path-only 不误伤）= P-DISPROVED；**D-02 = P-PROVED（P2：P-09 修复不完整 + 测试过拟合）**。附：`guid+path=None` 的引用不被计入托管（`_ref_is_managed` 只看键存在性），迁移产物里可能残留这种引用 → 硬失败漏报（P3 观察）。

### D-01 [REGRESSION] 新建场景复活上一场景的失效引用 → **P-PROVED（P1）**

1. **位置**：`editor.py:1287-1316 _new_scene`（只换 `_scene_skybox`/`_skybox`，**不清** `_skybox_valid`/`_skybox_ref`/`_asset_errors`）；消费点 `sceneio.py:1810-1813`（`_skybox_valid is False` → 用 `_skybox_ref` 覆盖本次发射结果）、`sceneio.py:250-284 asset_refs_kept`、`287-298 asset_issue_notice`。
2. **契约**：`editor.py:1295-1297` 注释明写「新建场景必须清 UI/材质/**天空盒**（防场景互相污染）」；`sceneio.py:1846` 注释「每次加载重置（跨场景不累积）」—— 新建场景同样是"换场景"，应同等重置。
3. **路径枚举**：
   - 路径 A：打开含失效天空盒的场景 → `_skybox_valid=False` + `_skybox_ref={guid}` → `_new_scene()` → 保存 → 写回**上一场景**的 `deadsky-old`。
   - 路径 B：材质槽不泄漏 —— `_new_scene` 里 `materials.clear()` 丢弃旧材质对象（含 `_asset_ref_slots`）。
   - 路径 C：`_asset_errors` 也不清 → 新空场景的 `asset_issue_notice`/`scene_assets_check` 报上一场景的问题。
   - 路径 D：正常场景（无失败）→ `_skybox_valid=True`、ref=None → 不受影响（所以官方用例全绿）。
4. **实际**（probe 01b）：
   ```
PASS 前置: 旧场景加载后保留 2 条失效引用  (2, [('skybox','deadsky-old',…), ('materials.albedo','deadtex-old',…)])
PASS 新建场景保存: materials 已清空（无旧材质）
FAIL 新建场景: 上一场景的失效引用必须清零（引用数=0、valid 回到 True）
     (1, False, {'guid': 'deadsky-old'}, '资产：2 条资产问题，1 条失效引用已保留（保存不会改写）…')
FAIL 新建场景保存: skybox 不得写回上一场景的 deadsky-old  {'guid': 'deadsky-old'}
```
5. **差异**：预期 = 新场景从默认蓝天出发、无资产问题；实际 = 新场景保存后 `skybox: {'guid': 'deadsky-old'}`，并在通知里谎报"1 条失效引用已保留"。
6. **触发条件**：任何一次"打开坏天空盒场景 → 新建场景（Ctrl+N）→ 保存"。这是 `4de3b4b` 新引入 `_skybox_ref` 机制后才存在的路径（旧版没有"保留引用"，新建场景后保存写默认蓝）。
7. **验证**：`cd Loom; python tests/_tmp/audit_b6r6_01_p1_1b_new_scene_stale_ref.py`（3 PASS / 3 FAIL）；静态点 `editor.py:1311-1316` + `sceneio.py:1810`。
8. **影响与等级**：**P1（跨场景污染 + 错误引用写入新场景）**。新场景被写入一个不属于它的资产 guid：若新场景保存到别的项目，该引用永远悬空；若留在本项目，用户看到"莫名其妙的资产问题"；`asset_issue_notice` 的"已保留"提示在新场景上失真。**修复方向**：`_new_scene` 与 `scene_from_dict` 同口径重置 `_skybox_valid=True`、`_skybox_ref=None`、`_asset_errors=[]`（相机对象随 `cameras.clear()` 丢弃，天然安全）。

### D-04 R5 P-16 升级：并发写索引仍会丢条目 → **P-PROVED（P2）**（原 P-UNKNOWN 结案）

1. **位置**：`loom_assets.py:313-327 save_index`（`tmp` 已 PID 化（320 行）但无锁/CAS）；`AssetContext.save:747-751`（写整本 `self.index`）。
2. **契约**：`save_index` docstring「原子写」—— 原子性只保证"不出现半个文件"，不保证多写者不互相覆盖；`loom_assets.py:5`「索引 = 唯一真相」。
3. **路径枚举**：串行（后者覆盖前者）与真并发（先加载后写 = lost update）；tmp 名冲突（已被 PID 化消除）。
4. **实际**（probe 08，两进程确定性交错：都先 `for_dir(proj)` → A 导入落盘 → B 导入落盘）：
   ```
gid_a=f0d1dab3… gid_b=5871364752…（两个正文文件都写进了 Assets/）
PASS 两个正文文件都写进了 Assets/（文件层不丢）
FAIL 索引里两条都在（否则 = 丢条目）  ['58713647524042cb957f70e8de122af0']
[发现] 丢失 guid: ['f0d1dab3…']（正文在盘上但索引无条目 -> 永久不可解析）
```
5. **差异**：预期"两次导入 → 两条索引"；实际只剩 1 条，丢失条目的正文成孤儿（对照 V-01：场景里对它的引用会被"保留"；对照 V-08：它又会触发打包硬失败）。
6. **触发条件**：编辑器/EAI 与迁移脚本（或两个 EAI 进程）同时向同一项目导入资产。
7. **验证**：`cd Loom; python tests/_tmp/audit_b6r6_01_p16_index_concurrency.py`。
8. **影响与等级**：P-PROVED（P2）。修复方向：`save_index` 写前重读 + 按 guid 合并，或加跨进程锁 + index `rev` 做 CAS。

### D-05 reimport 不能修复被删的正文 → **P-PROVED（P2）**

1. **位置**：`loom_assets.py:614-616`（`_find_by_sha` 命中即返回 `(same, False, None)`，**不检查正文是否存在**）；`import_texture:599-634`。
2. **契约**：`resolve` 的 reason 建议 "建议 asset_reimport"（`loom_assets.py:486`）；轮5 修复说明「修复资产/缺文件后自动恢复」（`sceneio.py:1817`）—— 用户按提示重新导入应当恢复。
3. **路径枚举**：正文在 → 去重正确（同 guid、不重复复制）；正文被删 → 仍走 `_find_by_sha`（sha 来自**源文件**，与正文存在性无关）→ 返回同 guid 但不复制。
4. **实际**（probe 03 `P1-2n`）：
   ```
FAIL P1-2n 正文被删后重新导入: 是否真的修复文件  (True, False, None, False, '资产文件缺失: Assets/Textures/a.png')
# 解读: (同 guid=True, created=False, why=None, resolve.ok=False, reason=资产文件缺失)
```
5. **差异**：预期 = 重新导入后 `resolve` 可用；实际 = `created=False` 且正文仍缺失、`resolve` 依旧失败，命令却返回成功（`{'guid':…,'created':False,'warning':None}`）。
6. **触发条件**：正文被外部删除/改名后，用户按 `scene_assets_check`/`asset_get` 的提示重新 `asset_import` 同一源文件。
7. **验证**：`cd Loom; python tests/_tmp/audit_b6r6_01_p1_2_index_partial.py`（唯一 FAIL 即此条）。
8. **影响与等级**：P-PROVED（P2）。与 V-01 联动：保留引用让用户"必须修好资产才会恢复"，但唯一官方修复入口不生效。

### D-06 Windows 保留名/超长名未被净化 → **P-PROVED（P3）**

1. **位置**：`loom_assets.py:53 _ILLEGAL_NAME`（只列 `<>:"/\\|?*` + 控制字符）、`56-67 safe_asset_name`（无保留名映射、无长度裁剪）、`582-591 _unique_dest`（`is_inside` 对设备名 realpath 判定失败 → `raise ValueError`）。
2. **契约**：P2-①「name 净化后必须落在 `Assets/<Type>` 下且可用」。
3. **路径枚举**：CON/NUL/AUX/COM1/LPT1 及带扩展名形态；>255 字符。实测四类结果：CON/NUL/COM1/AUX → `exists()` 为真 → 顺延成 `CON_2.png`（可用但名字被篡改）；LPT1 → `is_inside` 假阴性 → ValueError；300 字符 → `os.stat/copy2` OSError(22)；cubemap 的 CON/NUL → 返回 reason（无异常）。
4. **实际**：见 V-05 引用的两行 FAIL。
5. **差异**：预期"任一 name 要么落在 Assets 下可用、要么返回结构化 reason"；实际两种输入抛出未捕获异常（命令层转成 `repr(e)` 字符串）。
6. **触发条件**：name 恰为 `LPT1` 或长度 > 255（Win32 文件名上限）。
7. **验证**：`cd Loom; python tests/_tmp/audit_b6r6_01_p2_1_asset_name.py`。
8. **影响与等级**：P-PROVED（P3：不逃逸、不损坏数据；EAI 仍是 `{'ok':False}`，编辑器不崩）。

### D-07 已迁移 v11 场景不补闸门字段、报告失真 → **P-PROVED（P3）**

1. **位置**：`migrate:150-155`（`data['min_engine_version']` 无条件写进内存；落盘条件 `if n and not dry_run`）。
2. **契约**：`migrate:149` 注释「与编辑器保存产物等价 —— 写出 `min_engine_version`」。
3. **路径枚举**：n>0 → 落盘带字段；n=0（已迁移 v11、无 path 可迁）→ 不落盘但 `rep` 已赋值；dry-run → 永不落盘（预期）。
4. **实际**：probe 06 `(0, None)` —— `changed=0`、报告 `min_engine_version='0.1.0.beta6'`、磁盘 `None`；该文件 `check_engine_version` 仍放行（无字段=不设闸）。
5. **差异**：报告与磁盘不一致；"迁移后与编辑器产物等价"对 n=0 场景不成立。
6. **触发条件**：对旧版迁移工具已处理过（v11、无字段）的场景再跑一次。
7. **验证**：`cd Loom; python tests/_tmp/audit_b6r6_01_p2_4_migrate.py`。
8. **影响与等级**：P-PROVED（P3：一次性工具的产物一致性；可重跑但不会自愈）。

### 观察项（不计入判定）

1. `resolve` 对 delta dict 的 `src` 不做类型判定（`str(src)`）—— 见 V-04 末；不崩但 reason 失真。
2. `_ref_is_managed` 用"键存在"判定 `path`/`paths`/`solid_color`，`path: null` 的死 guid 不被计入托管 → 打包硬失败漏报（`build_game.py:66`）；probe 07 有对应 PASS 断言（证明其"漏"）。
3. `asset_list` 在 `root is None` 时返 `state='missing'`，而 `scene_assets_check` 同场景返 `index='missing'` 且 `ok` 只由 errs 决定 —— 语义一致，仅命名不同（无影响）。

---

## 3. 统计

| 判定 | 数量 | 编号 |
|---|---|---|
| **P-DISPROVED（宣称的修复成立，反例打不破）** | **11** | V-01 P1-1 主路径、V-02 显式清空、V-03 P1-2 三态、V-04 P1-3 delta、V-05 P2-① 越界堵死、V-06 P2-②③⑥、V-07 P2-④ 字段/只读/批处理、V-08 P2-⑤ 无索引硬失败+不误伤 |
| **P-PROVED（本轮新发现/残留）** | **7** | D-01、D-02、D-03、D-04、D-05、D-06、D-07 |
| ├ P1 | 1 | D-01 新建场景复活失效引用（并谎报资产问题）[REGRESSION] |
| ├ P2 | 4 | D-02 索引坏打包不拦（测试过拟合）、D-03 旧引擎不拒绝、D-04 并发丢条目、D-05 reimport 不修缺文件 |
| └ P3 | 2 | D-06 保留名/超长名、D-07 迁移报告与磁盘不一致 |
| **P-UNKNOWN** | **2** | U-01、U-02（见下） |
| **P-CONTRADICTION** | **0** | 无（双臂未出现互斥结论） |
| 观察项 | 3 | 见 §2 末 |

- 断言级证据：本轮探针 **PASS 234 / FAIL 8**；8 条 FAIL 全部对应 D-01/D-02/D-04/D-05/D-06（D-03/D-07 用"PASS 即复现"的断言方式留痕）。
- 官方回归 `test_asset_guid.py`：110 PASS / 0 FAIL（与提交声称"扩到 90+"一致）；`test_sceneio.py`/`test_skybox_scene.py` 均 ALL PASS。

### P-UNKNOWN 明细（不为 0，按协议保留）

- **U-01 并发写是否还会产生"非法 JSON"（而不只是丢条目）**：本轮已证明 lost update（D-04），但 `tmp` 已 PID 化 + `os.replace` 使"半文件"路径不可达；未构造出确定性的 JSON 损坏。还需要的信息：Windows 上同 PID 复用 + 多个 `AssetContext` 线程同时 `save()` 的压测（同进程内 `_CACHE` 共享 index 对象，可能掩盖问题）。
- **U-02 用户层 delta 的端到端链路**：仓库内没有"写用户层 delta"的代码（`grep user_delta` 只有读侧），本轮只验证了读侧容错；无法验证"谁写、何时写、写坏时上游是否可见"。还需要的信息：未来写入方（B1 预留）的实现或设计文档。

---

## 4. 修复建议排序（只给方向，不含代码）

1. **D-01（P1，最高优先）**：`_new_scene` 与 `scene_from_dict` 同口径重置 `_skybox_valid/_skybox_ref/_asset_errors`；补"打开坏天空盒场景 → 新建 → 保存 → 必须是默认蓝天"的回归。
2. **D-02（P2）**：把 `require_assets_or_exit` 提到 `main()` 的 if/else 之外（或让 `copy_project_assets` 返回"索引可用"而非"目录存在"），并把官方用例改为驱动真实 `main()`。
3. **D-04（P2）**：`save_index` 写前重读并按 guid 合并（或加跨进程锁 + `rev` CAS）；把"正文在、索引无"列为 `scene_assets_check` 的一项。
4. **D-05（P2）**：`_find_by_sha` 命中后校验正文存在；缺失则同 guid 重新拷贝（`created=True` + reason），而不是返回成功。
5. **D-03（P2，需人类裁决）**：写 `min_engine_version` 无法让 beta5 拒读。要么文档声明"beta5 不支持 v11"，要么 v11 场景一个 beta 周期同时保留 `path` 兼容字段 —— 见 §5 Q1。
6. **D-06/D-07（P3）**：`safe_asset_name` 增加保留名映射（CON→CON_ 等）与长度上限；迁移工具在 `n=0` 但缺字段时仍落盘（或报告里不写 `min_engine_version`）。

---

## 5. 需人类裁决的封闭问题

1. **Q1：v11 场景对 beta5 的兼容策略**
   - A（现状）：只写 `min_engine_version`，beta5 照常打开并静默丢贴图（D-03 实证）。
   - B：迁移/保存时**同时**写 `path`（一个 beta 周期的 fallback），beta5 可读、beta6 优先 guid。
   - 代价：B 增加体积与"双真相源"；A 让旧引擎用户遇到"静默丢贴图"。
2. **Q2：`asset_import` 的"重复导入"语义**
   - A（现状）：按源 sha 去重，返回 `created=False`，正文缺失时也不修复（D-05）。
   - B：去重前先验证正文存在，缺失则按同 guid 重拷并 `created=True`。
   - 代价：A 让官方提示 "asset_reimport" 成为空操作；B 让一次导入可能写盘（readonly/dry-run 需保持不写）。
3. **Q3：并发写索引的策略**（影响 D-04 修法）
   - A：合并式 `save_index`（重读 + 按 guid 并集），实现简单，但"删除"语义需要额外 tombstone；
   - B：锁文件 + 失败重试，进程内/跨进程都安全，但要与"加载路径无副作用"契约划清边界。

---

## 6. 探针与产物清单（全部 `Loom/tests/_tmp/`，已被 `.gitignore` 忽略）

| 文件 | 覆盖 | 结果 |
|---|---|---|
| `audit_b6r6_01_p1_1_preserve_refs.py` | P1-1 A–J、显式清空、自愈 | 52 PASS / 0 FAIL |
| `audit_b6r6_01_p1_1b_new_scene_stale_ref.py` | D-01 新建场景泄漏 | 3 PASS / 3 FAIL |
| `audit_b6r6_01_p1_2_index_partial.py` | P1-2 三态/自愈/D-05 | 13 PASS / 1 FAIL |
| `audit_b6r6_01_p1_3_delta_guard.py` | P1-3 delta 8×2 | 43 PASS / 0 FAIL |
| `audit_b6r6_01_p2_1_asset_name.py` | P2-① 28 反例 + D-06 | 96 PASS / 2 FAIL |
| `audit_b6r6_01_p2_4_migrate.py` | P2-④ + D-03/D-07 | 14 PASS / 0 FAIL |
| `audit_b6r6_01_p2_5_build_pack.py` | 真实 `main()` 四种布局 + D-02 | 11 PASS / 1 FAIL |
| `audit_b6r6_01_p16_index_concurrency.py` | D-04 双进程交错 | 2 PASS / 1 FAIL |
