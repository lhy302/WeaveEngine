# 批次 B1 资产管线 · 独立复核报告（beta6 轮5 / 编号 01）

- 审计对象：`f2d43b1`（批次 B1 资产）引入的逻辑，以及其与后续 C1/D1 提交的交互
- 审计者：独立复核子代理（不参与实现，只读）
- 日期：2026-11-10
- 结论摘要：**17 项疑似 → 14 P-PROVED（P1×3 / P2×7 / P3×4）、2 P-DISPROVED、1 P-UNKNOWN**（另有 3 条不计入判定的观察项）。
  最严重一条：**v11 场景在"资产解析失败"后被保存，会把 guid 引用永久销毁**（P-01）。

---

## 0. 范围与方法

### 0.1 提交范围（`git log --oneline`）

| 提交 | 与 B1 的关系 |
|---|---|
| `f2d43b1` | B1 本体（loom_assets / sceneio / agent_commands / editor / build_game / runtime / run_player / vk_player / migrate 工具） |
| `79b7e1a` | 仅 docs（验收记录） |
| `3a35f8f` | C1 动画底座（未改 B1 文件） |
| `d635f35` | C1 遗留版本闸（改 sceneio/editor，**与 B1 迁移产物交互 → P-07**） |
| `470b7bc` / `cc62480` / `0b38bc0` | D1 / 打包 / 文档（未改 B1 文件） |

`git log --oneline f2d43b1..HEAD -- Loom/sceneio.py Loom/loom_assets.py tools/migrate_scene_assets_v11.py Loom/build_game.py Loom/agent_commands.py Loom/editor.py`
→ 只有 `3a35f8f`、`d635f35`、`0b38bc0`。**结论：B1 的 loom_assets.py / build_game.py / 迁移脚本自 `f2d43b1` 起未被改动**，本报告对这些文件的结论一并对当前 HEAD 成立。

### 0.2 在途改动（只标注，不据此下结论）

审计期间工作区出现并发在途改动（12:59 之后出现，非本审计产生；本审计未执行任何 git 写操作）：

```
 M Loom/ckernels/loom_kernels.c      M Loom/core_components/official_manifest.py
 M Loom/core_components/registry.json M Loom/engine.py
 M Loom/fastpath.py                  M Loom/physics_bridge.py
 M Loom/physics_pipe.py              M Loom/run_player.py
 M Loom/scene_driver.py
?? Loom/tests/test_aabb_simd.py  ?? Loom/tests/test_physics_pose_soa.py
?? Loom/tests/test_scene_version_player.py
```

- `scene_driver.py` / `run_player.py` 在被审范围内，但**正在被他人在途修改** → 对这两个文件的判断只作为"观察/旁证"，不作为 P-PROVED 的唯一依据（P-03 另有 sceneio 侧独立证据）。
- 本审计前工作区只有 `tools/lint_except_dist/`、`tools/loom_lint_except.py` 两个未跟踪项。

### 0.3 读过什么 / 跑了什么

阅读：`Loom/loom_assets.py`(617)、`Loom/sceneio.py` 资产段（58-240、812-983、1067-1200、1590-1806）、`Loom/editor.py`(907-950、1045-1271、1440-1479)、`Loom/agent_commands.py`(1693-1748、1833-1877、2374-2498)、`Loom/build_game.py`(36-71、231-359)、`Loom/runtime.py`(111-148)、`Loom/run_player.py`(271-279)、`Loom/vk_player.py`(308-328)、`Loom/game_player.py`(111-147、240-261)、`tools/migrate_scene_assets_v11.py`、`Loom/tests/test_asset_guid.py`、`docs/design/版本计划_Loom0.1.0.beta6_20261109.md` §9.15-9.17。

跑过：

```powershell
cd Loom; python tests/test_asset_guid.py     # ALL PASS（46 项）
cd Loom; python tests/test_sceneio.py        # ALL PASS
cd Loom; python tests/test_skybox_scene.py   # ALL PASS
```

自建探针（只写 `Loom/tests/_tmp/audit_b6r5_*`，全部位于系统临时目录，不碰受跟踪文件）：

| 编号 | 探针 | 证明什么 |
|---|---|---|
| 01 | `audit_b6r5_01_p01_guid_save_loss.py` | 解析失败后保存会销毁 guid 引用（A/B/C 三情形） |
| 02 | `audit_b6r5_01_p02_cubemap_fingerprint.py` | 六面图指纹字段语义与校验缺失 |
| 03 | `audit_b6r5_01_p03_name_traversal.py` | name 未净化 → 写出 Assets/ 之外 |
| 04 | `audit_b6r5_01_p04_migrate_gate.py` | 迁移产物缺 min_engine_version / dry-run 失效 / 高版本场景抛异常 |
| 05 | `audit_b6r5_01_p05_legacy_and_remigrate.py` | v8/v10 真实场景加载；悬空 guid 再迁移静默 |
| 06 | `audit_b6r5_01_p06_skybox_check_blind.py` | 悬空天空盒 guid 不进 scene_assets_check |
| 07 | `audit_b6r5_01_p07_pack_no_index.py` | 打包找不到索引时不失败，包内留死 guid |
| 08 | `audit_b6r5_01_p08_material_asset.py` | 材质资产端到端（未被现有 46 项覆盖）+ 双源 |
| 09 | `audit_b6r5_01_p09_index_recovery.py` | 索引坏一条 → 导入永久失效且诊断信息错误 |
| 10 | `audit_b6r5_01_p10_user_delta.py` | 用户层 delta 坏条目 → 场景加载崩溃 |

运行命令统一加 `$env:PYTHONIOENCODING='utf-8'`（否则 GBK 控制台吞中文证据）。

---

## 1. 粗筛清单（含跳过留痕）

### 1.1 疑似项

| ID | 位置 | 标签 | 初步方向 |
|---|---|---|---|
| P-01 | sceneio.py:1103-1141 / 1631-1650 | SEM-SILENT / IFACE-PARTIAL | 解析失败的槽位在保存时被直接丢弃；天空盒被换成默认纯色 |
| P-02 | loom_assets.py:188-190, 283-290 | SEM-SILENT / TOOL-SCOPE | 索引里一条坏条目 → 整本索引作废，且无法用 create 自愈 |
| P-03 | loom_assets.py:335-336 | BND / SEM-SILENT | 用户层 delta 值非 dict → `.get` 抛 AttributeError |
| P-04 | loom_assets.py:450-459, 485-490 | BND / IFACE-PRECOND | name 直接拼路径，可 `../` 逃出 Assets |
| P-05 | sceneio.py:898-908, 1128-1131 | SEM-SILENT / AUDIT-ASYMMETRY | 天空盒失败不进 `_asset_errors`，体检假绿 |
| P-06 | loom_assets.py:342-346, 542-546 | AUDIT-DEADCODE / SEM-SILENT | 六面图 fingerprint 不参与校验，size 是面数不是字节 |
| P-07 | migrate 工具:131 / sceneio.py:1793-1797 | IFACE-VERSION | 迁移产物没有 min_engine_version，D7 闸门形同虚设 |
| P-08 | migrate 工具:57 | TOOL-CLI / AUDIT-DOCIMPL | `--dry-run` 在"新项目"场景直接失败 |
| P-09 | build_game.py:352-359 | SEM-SILENT | 场景有 guid 但找不到项目索引 → 只打印，构建继续 |
| P-10 | migrate 工具:62-79 | SEM-SILENT | 悬空 guid 既不报 failure 也不改写 |
| P-11 | sceneio.py:1650 + agent_commands:2420 | AUDIT-DOCIMPL | 材质资产在 assets.json 与场景 materials[] 各存一份 |
| P-12 | build_game.py:354 | AUDIT-DEADCODE | `config['assets']` 无消费者 |
| P-13 | migrate 工具:159-175 | IFACE-VERSION | 遇更高版本场景抛未捕获异常，整批中断 |
| P-14 | sceneio.py:210-240（兼容闸门） | SEM-MISMATCH | 无 assets.json 时是否与 beta5 完全一致 |
| P-15 | sceneio.py:1735-1806（migrate） | IFACE-VERSION | v8/v10 旧场景是否都能加载 |
| P-16 | loom_assets.py:236-250 | BND-CONCURRENCY | 固定 `.tmp` 名 + 无锁 → 并发写坏索引 |
| P-17 | editor.py:1197-1271 / 全仓 | SEM-SILENT | 资产问题只 print，GUI 用户不可见 |

### 1.2 跳过登记表（四类理由之一）

| 位置 | 跳过理由 | 出处 |
|---|---|---|
| loom_assets.py:104-117 `is_inside` 的 realpath/commonpath 分支 | 语言/标准库规范保证：`commonpath` 跨盘符抛 `ValueError` 已被捕获并返回 False | Python `os.path.commonpath` 文档 |
| loom_assets.py:139-164 sha256/stat 实现 | 已有回归覆盖（test_asset_guid ⑧/⑪ + 本轮探针 02 实测 sha 计算正确） | test_asset_guid.py:267-277 |
| sceneio.py:141-163 版本闸 `check_engine_version` | 属 C1/D7（`d635f35`）契约，本轮只审"B1 产物是否吃到闸门"（见 P-07）；闸门自身已有 test_eai_real/test_scene_load 覆盖 | 提交 `d635f35`；本轮不在 B1 派单范围 |
| sceneio.py:426-512 `_emit_object`/`_apply_object` 的父链、脚本、刚体段 | 与资产无关，B1 只加了 `ctx.material` 回查（已用探针 08 实测） | 探针 08 |
| scene_driver.py:131-234 的 GL/VK 重复实现 | 该文件正在在途修改（`git status: M`），无法把当前内容当定论 | 0.2 节 |
| agent_commands.py 其余 100+ 命令 | B1 只新增 4 条命令 + 改 2 条（set_texture/set_env），其余不在范围 | `git show --stat f2d43b1` |
| editor.py:1440-1479 资产面板每帧调 `_asset_context()` | 性能属 D1 计量范畴，且 `load_index` 命中 stat 缓存；未做帧耗时实测 → 不作为本轮结论 | loom_assets.py:179-182 缓存键 |

---

## 2. 逐项裁决（8 段式）

### P-01 · 解析失败后保存会**销毁** guid 引用 · **P-PROVED（P1）**

1. **位置**：`Loom/sceneio.py:1103-1141`（`_apply_material_texture`）、`1144-1171`（`_apply_material_env`）、``1631-1657``（`scene_to_dict` 写天空盒/材质）、`Loom/editor.py:1159-1181`（`_save_scene` 无资产闸门）。
2. **契约/预期**：版本计划 §9.15「材料 albedo/normal/env 与 skybox/相机 skybox 托管时只写 guid，旧 path/paths 兼容读并告警（**一个 beta 周期 fallback**）」；即"解析失败必须降级但不得改写引用"。`loom_assets.py:327` 也写明 `reason 非空但 valid=True = 资产可用但过期（应出声）`——出声，而非删除。
3. **路径枚举**（写侧 `_emit_material` / `_emit_skybox`）：
   - 路径 1：`mat.albedo is not None` → 写 guid 或 guid+path（1108-1121）；**任一路径都要求对象存在**。
   - 路径 2：`mat.albedo is None` → `if alb is not None`（1079-1081）整段跳过 → **场景里 albedo 键消失**。
   - 路径 3：`env_map` 同理（1085-1089）。
   - 路径 4：`_scene_skybox` 已被 908 行替换成 `default_skybox()`（纯色）→ `_emit_skybox` 走 946-948 写 `solid_color`，原 guid 消失。
   读侧把"解析失败"映射为 `None`（1111 只在 `tex is not None` 时 setattr；1135-1141 只记错误），所以路径 2/4 是**可达的**。
4. **实际**（探针 01，三种情形实测）：
   - A 缺贴图文件：`[资产] materials.albedo: 资产文件缺失: Assets/Textures/a.png` → 再保存 `materials[0]` 键集合 = `['color','env_map','id','metallic','name','pbr','roughness','saturation']`，**albedo 整键消失**。
   - B 缺 assets.json：天空盒 → `{'name':'默认蓝天','guid':'8bb159f1…','solid_color':[58,155,213,255]}`（原 guid `2fca7d4e…` 消失），albedo/env_map 全丢。
   - C 索引坏一条（同 P-02）：同样丢天空盒与 albedo。
5. **差异**：预期=保留引用并持续告警；实际=一次保存即永久丢失，且只留控制台 1 行 print。
6. **触发条件**：任何一次"贴图/六面图文件被删/改名/索引缺失/索引损坏"之后，用户打开场景并按 Ctrl+S（含 `_confirm_unsaved` 的"保存"分支、recovery 自动保存、`save_scene`）。
7. **验证**：
   ```powershell
   $env:PYTHONIOENCODING='utf-8'; cd Loom; python tests/_tmp/audit_b6r5_01_p01_guid_save_loss.py
   # [A] 再次保存后 albedo = None
   # [B] 再次保存后 skybox = {'name': '默认蓝天', 'guid': '8bb159f1…', 'solid_color': [...], ...}
   ```
8. **影响与等级**：**P1 功能错误（不可逆资产丢失）**。B1 让"场景只写 guid"，但没有让"写侧在解析失败时保留旧值"，于是把 beta5 时代"路径还能救"的场景变成"一存即残"。这是本轮最重要的一条。

### P-02 · 索引坏一条 → 整本作废，且无法自愈 · **P-PROVED（P1）**

1. **位置**：`Loom/loom_assets.py:195-233`（`validate_index` 任一 reason → ok False）、`188-190`（`load_index` 直接返回 `None`）、`283-290`（`for_dir` 找到 root 后 `return cls.open_root(root)`，**丢掉 create 参数**）、`293-301`（`open_root(create=True)` 的"建空索引覆盖"分支）。
2. **契约**：`validate_index` docstring「坏条目剔除并记 reason」（196 行）——预期是剔除个别坏条目后继续；版本计划 §9.15「越界拒绝」也只要求拒绝越界条目。
3. **路径枚举**：
   - 路径 A：`assets.json` 不存在 → `find_project_root` 返回 None → `for_dir(create=True)` 走 286-289 建空索引 → 可自愈。
   - 路径 B：`assets.json` 存在且全部合法 → 正常。
   - 路径 C：存在但**任一条目非法**（或 JSON 损坏）→ `load_index` → None → `for_dir` 290 行 `open_root(root)`（create=False）→ 293-297 `return None` → 编辑器/命令全部当"无资产库"；`create=True` 因被丢弃而**永不生效**。
   - 路径 D：若真调用 `open_root(root, create=True)`（当前无调用方），则 298-300 用空索引覆盖原文件 → 其余好条目也丢。
   路径 C/D 证实"一条坏 = 全盘失效或全盘覆盖"。
4. **实际**（探针 09 / 01-C）：
   ```
   索引含 1 个坏条目时再次导入 -> {"error": "无法创建项目资产库: …\proj"}
     scene_assets_check -> {"ok": true, "count": 0, "errors": [], "project": null}
     asset_list -> {"assets": [], "project": null, "valid": false,
                    "reason": "当前项目没有资产库（缺 Assets/assets.json）"}
   索引 JSON 损坏时导入 -> {"error": "无法创建项目资产库: …\proj"}
     for_dir(create=True) = None
   ```
   同时场景加载侧把原因说成"**缺** Assets/assets.json"（探针 01-C 输出 `天空盒是资产 guid … 但当前项目没有资产索引（缺 Assets/assets.json）`），而文件其实存在——**诊断信息错误**。
5. **差异**：预期=剔除坏条目/明确报出"索引损坏：<reason>"并可继续导入；实际=整本不可用 + 原因串被丢弃（`open_root` 297 行直接 `return None`，`why` 无人接收）+ 提示内容与事实相反 + 导入永久失败。
6. **触发条件**：任意一条历史/手改/半写条目非法（如 `src` 为绝对路径、`type` 拼错、缺 `assets` 键），或写入中断导致 JSON 截断。
7. **验证**：`python tests/_tmp/audit_b6r5_01_p09_index_recovery.py`（见上）；`python tests/_tmp/audit_b6r5_01_p01_guid_save_loss.py` 的 `[C]` 段。
8. **影响与等级**：**P1**。与 P-01 叠加构成完整事故链：坏一条 → 全项目退化成旧路径模式 → 打开场景告警 → 保存即按 P-01 销毁引用。

### P-03 · 用户层 delta 坏条目 → 场景加载崩溃 · **P-PROVED（P1）**

1. **位置**：`Loom/loom_assets.py:335-336`（`delta = self.user_delta.get(guid) or {}` 后立刻 `delta.get('src')`）；调用链 `sceneio.py:1108-1109 → ctx.texture → resolve`，`sceneio.py:1670-1707` 无 try；`editor.py:1240-1247`（崩溃前已 `remove_model` 全部 + `undo.clear()`）。
2. **契约**：`loom_assets.py:8`「解析失败一律返回 (obj, valid, reason)」；`editor.py:1214-1216` F7 收口「父链成环等对象图错误必须在**清空旧场景之前**拒绝，旧顺序会先丢当前工作」。
3. **路径枚举**：
   - 路径 1：`user_delta[guid]` 为 dict（正常）→ 继续。
   - 路径 2：`user_delta[guid]` 为 str/list/int/bool → `or {}` 只在假值（''/0/[]/False）时兜底；非空 str → `delta.get` → AttributeError。
   - 路径 3：`user_delta` 整体非 dict → `_load_user_delta` 已拦（257 行）。
   路径 2 可达且无异常边界。
4. **实际**（探针 10）：
   ```
   用户层 delta 路径 = …\projects\dir-dbcb54b8\assets.json
   user_delta = {'a6220457…': 'oops-not-a-dict'}
   resolve 抛 = AttributeError 'str' object has no attribute 'get'
   scene_from_dict 抛 = AttributeError 'str' object has no attribute 'get'
   ```
   VK 侧同一输入不崩（`scene_driver.py:137-141` 把 `ctx.texture` 包在 try 里）→ **同一场景两端行为不同**，且 GL 崩溃发生在 `remove_model` 之后（F7 承诺被击穿）。
5. **差异**：预期=`resolve` 返回 `(None, e, False, reason)`；实际=异常穿透到 `_load_scene`，当前场景已被清空。
6. **触发条件**：用户层 `%LOCALAPPDATA%/Loom/projects/<pid>/assets.json` 中某 guid 的值不是对象（手改、未来写入端半写、迁移脚本写坏）。
7. **验证**：`python tests/_tmp/audit_b6r5_01_p10_user_delta.py`。
8. **影响与等级**：**P1**（加载崩溃 + 丢工作）。可达性受限（当前仓库无写用户层 delta 的代码），但白盒契约要求"一律 reason 不抛"，且 B1 已经把该层接入热路径。

### P-04 · 资产名未净化 → 写出 `Assets/` 之外，打包静默漏资产 · **P-PROVED（P2）**

1. **位置**：`loom_assets.py:450-459`（`_unique_dest` 直接 `os.path.join(d, stem+ext)`）、`485-490`（`base_name = name or basename`，未净化）、`542-546`（cubemap 目录名同源）；调用方 `agent_commands.py:2437`（`name=args.get('name')` 原样透传）、`editor.py:939`。
2. **契约**：模块 docstring `loom_assets.py:5`「资产正文 = 项目根下 `Assets/<Type>/…`」；`validate_index` 224-227 只校验"在项目根内"，不校验"在 Assets 下"。
3. **路径枚举**：
   - 路径 1：name 正常 → `Assets/Textures/name.ext`。
   - 路径 2：name 含 `../` 且浅（`../../x`）→ 父目录存在 → `shutil.copy2` 成功 → 文件落在项目根；`os.path.relpath` 得 `x.png`（无 `..`）→ **索引校验通过**。
   - 路径 3：name 含更深的 `../`（父目录不存在）→ copy2 抛 FileNotFoundError → 未被捕获 → 命令层 500/异常。
   路径 2 静默成功。
4. **实际**（探针 03）：
   ```
   import_texture(name="../../escaped") -> 8882ba5c… True None
     proj 根下出现文件 = ['Assets', 'escaped.png']
     Assets/Textures 内 = []
     索引 load_index = True why = None
     条目 src = escaped.png
     resolve = (True, None)
     打包时 copy_project_assets 会带吗? Assets/ 下文件 = ['Assets\\assets.json']
   import_cubemap(name="../../evile") -> a2d5da52… True True
   ```
   即：资产在 Assets 外 → `build_game.copy_project_assets` 只拷 `Assets/` → **玩家侧必然缺图**，而编辑器里一切显示正常。
5. **差异**：预期=导入路径必须落在 `Assets/<KIND_DIRS>` 下；实际=可写到项目任意位置（再深一级就出项目根，属于信任边界破口）。
6. **触发条件**：EAI/脚本调用 `asset_import {name:"../x"}`，或编辑器把外部文件名当作 name 传入（外部文件名可能含 `..`）。
7. **验证**：`python tests/_tmp/audit_b6r5_01_p03_name_traversal.py`。
8. **影响与等级**：**P2**（需要非默认输入；后果是打包漏资产 + 路径越界写）。

### P-05 · 悬空天空盒 guid 不进 `scene_assets_check`（假绿） · **P-PROVED（P2）**

1. **位置**：`sceneio.py:898-908`（`_scene_skybox_from_data` 只 `print` + 写 `_skybox_valid/_skybox_error`，**不调 `record_asset_error`**）、对照 `1113/1117/1132/1137/1140`（贴图槽都调了）、`agent_commands.py:2488-2497`（`scene_assets_check` 只读 `asset_errors`）。
2. **契约**：命令自述 `scene_assets_check` =「场景资产体检: 本次加载记录的引用问题（valid/reason）**对齐 skybox_get 口径**」；§9.15「EAI 命令 scene_assets_check 可查」。
3. **路径枚举**：
   - 路径 1：天空盒 guid 缺失/索引无此 guid → 908 行 `return default_skybox(), False, reason` → `asset_errors` 保持空。
   - 路径 2：材质贴图 guid 缺失 → 1138 行 `record_asset_error` → 进列表。
   两条并列失败路径只有一条进体检 → 不对称。
4. **实际**（探针 06）：
   ```
   只坏天空盒:
     engine._skybox_valid = False | _skybox_error = 天空盒资产解析失败: 资产 guid 未在项目索引中: cafebabe…
     sceneio.asset_errors = []
     scene_assets_check  -> {"ok": true, "count": 0, "errors": [], "project": "…"}
   只坏材质贴图:
     scene_assets_check  -> {"ok": false, "count": 1, "errors": [{…}]}
   ```
5. **差异**：预期=`ok:false, count>=1`；实际=`ok:true, count:0` → 自动化流水线会据此认为"场景干净"。
6. **触发条件**：场景天空盒是资产 guid，而索引缺该 guid（删资产/换项目/索引坏）。
7. **验证**：`python tests/_tmp/audit_b6r5_01_p06_skybox_check_blind.py`。
8. **影响与等级**：**P2**（体检假阴性；与 P-01 联动——假绿之后保存即丢引用）。

### P-06 · 六面图指纹是死字段，内容变更完全不检测 · **P-PROVED（P2）**

1. **位置**：`loom_assets.py:342-346`（`if e.get('type')=='cubemap'` 只判目录存在，**提前 return，永不比对 fingerprint**）、`542-546`（写入 `'size': len(abses)` 即面数 6，`mtime` 取 6 个源文件的 max）。
2. **契约**：`loom_assets.py:6-9`「指纹 sha256+size+mtime」「热路径只 stat」；§9.15「指纹 sha256+size+mtime」。字段语义应为"内容指纹"。
3. **路径枚举**：
   - 路径 1 texture：`349-361` stat 比对 → 不符则算 sha → 内容变 → `valid=True + reason='内容已变更…'`。
   - 路径 2 cubemap：342-346 直接返回 `(abs_p, e, True, None)` → **任何面被替换都无感**。
   - 路径 3 cubemap 缺面 → 398-400 有 reason（存在性有覆盖，内容没有）。
4. **实际**（探针 02）：
   ```
   texture  entry.fingerprint = {'mtime': …, 'sha256': '56b2d7f5…', 'size': 75}
   cubemap  entry.fingerprint = {'mtime': …, 'sha256': 'd8252025…', 'size': 6}
   texture 内容被改 -> resolve = (…, True, '资产内容已变更（sha256 不符，建议 asset_reimport）: Assets/Textures/t.png')
   cubemap 内容被改 -> resolve = (…, True, None)
   cubemap 内容被改 -> cubemap() = (True, None)
   ```
5. **差异**：预期=cubemap 也报"内容已变更"（或至少 `size` 是字节数）；实际=既无告警，字段还承载面数。
6. **触发条件**：六面图被外部工具重画/替换（美术迭代最常见）。
7. **验证**：`python tests/_tmp/audit_b6r5_01_p02_cubemap_fingerprint.py`。
8. **影响与等级**：**P2**（静默用旧画面；同时是 AUDIT-DEADCODE：写进去的 sha256/size/mtime 对 cubemap 永不被读）。

### P-07 · 迁移产物缺 `min_engine_version`，D7 闸门对迁移场景无效 · **P-PROVED（P2）**

1. **位置**：`tools/migrate_scene_assets_v11.py:131`（`data = sceneio.migrate(data)`）、`sceneio.py:1793-1797`（v10→v11 只 `pass`）、`1805`（只写 `data['version']`）；对照 `sceneio.py:1644-1647`（`scene_to_dict` 才写 `min_engine_version`）、`141-163`（闸门只认该字段）。
2. **契约**：§9.15「SCENE_VERSION 10→11」+ `d635f35` 提交说明「旧引擎读新场景会静默丢字段 → 写 min_engine_version 让旧引擎明确拒绝」。
3. **路径枚举**：
   - 路径 1 编辑器正常保存 → `scene_to_dict` → 有 `min_engine_version` → beta5 拒绝加载 ✅
   - 路径 2 迁移脚本产出 → 只有 `version: 11` → `check_engine_version` 151-152 行无字段直接放行 → **beta5 会照常打开**，其 `_apply_material_texture` 只读 `path`（本工具已删除 path）→ 贴图/天空盒静默消失。
   - 路径 3 手改场景 → 同路径 2。
4. **实际**（探针 04）：
   ```
   迁移后 version = 11 | min_engine_version = None
   check_engine_version(迁移后场景) = True
   scene_to_dict -> version = 11 | min_engine_version = 0.1.0.beta6
   ```
5. **差异**：预期=迁移产物与编辑器保存产物在版本闸门字段上等价；实际=差一个字段，恰好是保证"旧引擎别读"的那个字段。
6. **触发条件**：任何用该工具迁移过、且随后被 beta5 打开的场景。
7. **验证**：`python tests/_tmp/audit_b6r5_01_p04_migrate_gate.py`（第 2/3 段）。
8. **影响与等级**：**P2**（跨界使用才出问题；但 B1 迁移脚本正是一次性批量写盘的场景，影响面是全部旧场景）。

### P-08 · `--dry-run` 在"还没有资产库"的项目上直接失败 · **P-PROVED（P2）**

1. **位置**：`tools/migrate_scene_assets_v11.py:57`（`AssetContext.for_dir(root, create=(create and not dry_run))`）→ `58-60`（None → `failures.append('无法打开/创建项目资产库…')`）；`159-175`（`main` 把 failures 汇总成 `bad>0 → return 1`）。
2. **契约**：文件头 `10-17` 行「`--dry-run` / `--report` / `--no-create`」「幂等」；三种用法默认是"先 dry-run 看报告再真跑"。
3. **路径枚举**：
   - 路径 1：项目已有合法 `Assets/assets.json` → dry-run 正常预演。
   - 路径 2：项目**没有**索引（正是最需要迁移的旧项目）→ dry-run 不创建 → ctx None → 每个场景都记 failure、`changed=0`、`version_after=None`、退出码 1。
4. **实际**（探针 04 第 1 段）：
   ```
   dry_run 报告 = {"changed": 0, "failures": ["无法打开/创建项目资产库（可用 --no-create 只迁已有项目）"],
                   "version_before": 10, "version_after": null, "dry_run": true}
   ```
5. **差异**：预期=dry-run 只读预演、给出"将新建索引 + 将改 N 处"；实际=对目标项目一律报失败，与"预演"语义相反。
6. **触发条件**：对任何未建 Asset 库的旧项目跑 `--dry-run`（默认扫描 examples/Projects/docs/audit，多半都没索引）。
7. **验证**：`python tests/_tmp/audit_b6r5_01_p04_migrate_gate.py`（第 1 段）。
8. **影响与等级**：**P2**（工具可用性；会诱导用户跳过预演直接改盘）。

### P-09 · 打包找不到项目索引时不失败，发布包带死 guid · **P-PROVED（P2）**

1. **位置**：`Loom/build_game.py:352-359`（`_has_assets = copy_project_assets(...)`；False 只 `print`，随后 `361` 照常 `game_pack.pack`）、`41-49`（找不到 root 返回 None）、`59-71`（只拷 `Assets/`）。
2. **契约**：§9.15「打包带资产：build_game.copy_project_assets 拷 Assets/；runtime/run_player/vk_player/game_player 传 assets_base，包内场景不再按 CWD 解析」——目的是消灭"玩家侧贴图全丢"的 P0；修复不完整时应当**拒绝出包**。
3. **路径枚举**：
   - 路径 1 场景在项目内且索引存在 → 拷 `Assets/Assets.json` + 正文 → 运行时 `assets_base=发布夹` 可解析 ✅
   - 路径 2 场景目录上没有索引（场景被单独拷出/流水线在别处构建/目录改名漏拷）→ False → 构建继续 → `.lsc` 里仍是纯 guid → 玩家侧全部回退/丢失，**没有任何硬失败**。
   - 路径 3 索引存在但资产 `src` 在 Assets 之外（见 P-04）→ True，但漏文件 → 同上。
4. **实际**（探针 07）：
   ```
   场景目录无 assets.json -> copy_project_assets = False
     发布夹内容 = []
     场景里仍有 guid 引用 = ('aaaa…aaaa', 'bbbb…bbbb')
   有索引 -> copy_project_assets = True
   ```
5. **差异**：预期=检测到"场景含 guid 引用但无法随包"时 `raise SystemExit`（与 `_runtime_dist`/`ckernels` 自洽断言同级）；实际=一行提示后照常出包。
6. **触发条件**：`--scene` 指向项目外的场景副本；或项目根定位失败（`find_project_root` 依赖 `Assets/assets.json` 存在）。
7. **验证**：`python tests/_tmp/audit_b6r5_01_p07_pack_no_index.py`。
8. **影响与等级**：**P2**（构建期可拦却放行，故障暴露在玩家侧）。

### P-10 · 再迁移对"悬空 guid"零报告 · **P-PROVED（P3）**

1. **位置**：`migrate 工具:62-70`（`if isinstance(g,str) and g and ctx.owns(...): return ref, False`；`if not paths: return ref, False`）→ 悬空 guid（既 owns 不到、又没有 paths）静默返回。
2. **契约**：工具头 `15-18`「一次性迁移…只跑一次」+ `rep['failures']` 的存在意义就是报告不可迁移项。
3. **路径枚举**：路径 1 已迁移且索引有效 → 正确跳过；路径 2 有 paths → 迁移；路径 3 guid 存在但索引没有 + 无 paths → **与路径 1 同一条 `return ref, False`**（不可区分）。
4. **实际**（探针 05 第 2 段）：`{"changed": 0, "failures": [], ... "version_before": 11, "version_after": 11}`，文件未被改写（`文件被改写 = False`），而随后加载报 `资产 guid 未在项目索引中: deadbeef…`。
5. **差异**：预期=failures 里点名"guid 悬空"；实际=报告全绿。
6. **触发条件**：换项目/删资产后对同一场景再跑迁移（正是"已迁移场景再迁移"场景）。
7. **验证**：`python tests/_tmp/audit_b6r5_01_p05_legacy_and_remigrate.py`。
8. **影响与等级**：**P3**（不造成新损坏，但让"迁移完成"的结论不可信）。

### P-11 · 材质资产双源：assets.json 与场景 `materials[]` 各存一份 · **P-PROVED（P3）**

1. **位置**：`agent_commands.py:2419-2420`（`asset_import type=material` → `ctx.import_material`）、`loom_assets.py:594-599`（写入 `value`）、`sceneio.py:1650`（`materials` 段照常 `_emit_material`）、`sceneio.py:1178-1199`（加载时先建场景内联材质）。
2. **契约**：`loom_assets.py:5`「索引 = Assets/assets.json（**唯一真相**）」；`sceneio.py:530-534` 的 `ctx.material` 回查暗示"材质正文在资产库"。
3. **路径枚举**：
   - 路径 1 场景 `materials[]` 含同 guid 的内联副本 → `_apply_materials` 先登记 → `_find_material(mat_id)` 命中 → `_apply_object` 530 行 `ctx.material` 不执行 → **场景副本胜出**。
   - 路径 2 场景 `materials[]` 为空、只有 `material_id` → `ctx.material` 生效（探针 08 验证可用）。
   两条路径并存 ⇒ 同一 guid 两个真相源。
4. **实际**（探针 08）：导入材质资产后，场景里 `materials` 段再次出现完整材质（同 guid `374f1e35…`），`objects[0].material_id` 也指向它 → `材质数 = 1` 但磁盘上有两份定义。
5. **差异**：预期=材质资产只存在于 assets.json（场景只留 `material_id`）；实际=可编辑的副本进了场景，改资产库对已有场景无影响。
6. **触发条件**：任何一次 `asset_import type=material` 之后保存场景。
7. **验证**：`python tests/_tmp/audit_b6r5_01_p08_material_asset.py`。
8. **影响与等级**：**P3**（功能可用，但违反"唯一真相"的 B1 设计前提，后续资产热更新会踩坑）。附带事实：`import_material`/`ctx.material` 这条路径在 `test_asset_guid` 的 46 项里**没有任何覆盖**（本轮探针 08 是首次实测）。

### P-12 · `config['assets']` 是死字段 · **P-PROVED（P3）**

1. **位置**：`build_game.py:354` 写 `config['assets'] = bool(_has_assets)`；全仓 grep 无读取点（`game_player.py` 只用 `cf.get('title')` / `name`）。
2. **契约**：字段存在的意义应是运行时可判"本包是否带资产"。
3. **路径枚举**：写完 → `game_pack.pack(out, config, …)` 落盘 → 播放器 `gm['config']` 解出 → **无人读**。
4. **实际**：`Select-String -Path Loom/*.py -Pattern "config\['assets'\]"|"get\('assets'\)"` 只命中 `build_game.py:354` 的写侧。
5. **差异**：预期=播放器可据此提示/降级；实际=纯冗余字段（AUDIT-DEADCODE）。
6. **触发条件**：无（恒成立）。
7. **验证**：`git grep -n "assets" -- Loom/build_game.py Loom/game_player.py Loom/game_pack.py`。
8. **影响与等级**：**P3**。

### P-13 · 迁移脚本遇更高版本场景抛未捕获异常，整批中断 · **P-PROVED（P3）**

1. **位置**：`migrate 工具:159-167`（循环内无 try）→ `sceneio.py:1741` `check_engine_version` → `159-162` `raise SceneVersionError`。
2. **契约**：工具 `10-19` 承诺逐场景报告 `failures`，`174-175` `return 1 if bad else 0` 的批次语义。
3. **路径枚举**：路径 1 目标场景版本 ≤ 当前 → 正常；路径 2 目标场景 `min_engine_version` 更高（未来版本/他人机器产出）→ 异常冒泡 → `main` 终止 → **后续场景一个都不迁、`--report` 也不写**。
4. **实际**（探针 04 第 4 段）：
   ```
   更高版本场景 migrate_scene 抛 = SceneVersionError 场景要求引擎 >= 9.9.9, 当前引擎 0.1.0.beta6…
   main() 抛 = SceneVersionError …
   ```
5. **差异**：预期=`failures.append(...)` 并继续；实际=整批 abort（默认扫描目录里混入一个未来场景即可复现）。
6. **触发条件**：默认目标集（examples / Projects / docs/audit）里出现高版本场景。
7. **验证**：`python tests/_tmp/audit_b6r5_01_p04_migrate_gate.py`（第 4 段）。
8. **影响与等级**：**P3**（一次性工具，重跑即可）。

### P-14 · ①兼容闸门：无 assets.json 时与 beta5 等价 · **P-DISPROVED（无 bug）**

1. **位置**：`sceneio.py:175-184`（`asset_context`）、`1668-1669`、`1598`；`210-221`/`224-240`（emit 分支）、`1103-1141`（apply 分支）。
2. **契约**：§9.15「无项目索引时行为与 beta5 一致」；`asset_context` docstring「None = 旧路径模式…一切行为与 beta5 完全一致」。
3. **路径枚举**（证伪链：枚举所有 ctx 取值 × 引用形态）：
   - ctx None × 材质贴图（path 存在）→ 1120-1130 与 beta5 同参同默认值（`mipmaps/wrap/filter_mode/aniso/max_size/compression` 逐项同默认）→ 行为同；**唯一差异**是多了 1117-1119 的 `旧路径引用` 告警（用户可见文本，不是行为）。
   - ctx None × emit 未托管贴图 → 210-221 输出的键集合与 `git show f2d43b1` 里旧实现的 8 键一致（`guid/path/name` + 6 个 import 键）；旧实现无条件写、新实现 `if v is not None`，而 `Texture` 这 6 项恒有值 → 无差异。
   - ctx None × cubemap 有 paths/纯色 → 931-949 与旧实现一致。
   - ctx None × cubemap **既无 paths 又无 solid** → 新实现 950 行 `return None`（旧实现会写 `{guid,name}`）。**不可达**：`loom_cubemap.py` 只有 `from_files`（设 paths）与 `from_solid`（设 `_solid_color`）两个构造口（45、80、134 行），无第三条构造路径。
   - ctx None × skybox dict 只有 guid → 832-834 返回 `valid=False` + 更具体 reason；旧实现落到 882 行 `缺少 paths/solid_color` → 两者都被 `_scene_skybox_from_data` 转成"默认蓝 + valid=False"，净行为同。
   - 真实旧场景：探针 05 加载 `压测50球.json`(v8)/`压测500混合.json`(v8)/`PacMan2D.json`(v10)/`场景.json`(v10) → `资产上下文=None`、`资产问题 0`、物体/材质数与文件一致。
4. **实际/差异**：无行为差异；只有"旧路径告警"这条新增文本（且 VK 侧 `scene_driver.py:157` 在 ctx None 时**不**告警 → 两后端噪声不一致，属观察项，因该文件在途修改不单列 P）。
5. **触发条件**：不适用（这是"应当无 bug"的那一侧）。
6. **验证**：`python tests/_tmp/audit_b6r5_01_p05_legacy_and_remigrate.py`（第 1 段）+ `python tests/test_skybox_scene.py`。
7. **判定**：**DISPROVED** —— 兼容闸门成立（含"唯一差异是告警文本"这一条）。

### P-15 · ⑤ v8/v10 旧场景在 SCENE_VERSION=11 下都能加载 · **P-DISPROVED（无 bug）**

1. **位置**：`sceneio.py:58`、`1735-1806`（`migrate`，v<11 只 `pass`，`1805` 抬 version）、`1662-1732`（加载入口）。
2. **契约**：§9.15「老 v8 场景仍可加载（bench FPS 74.0）」。
3. **路径枚举**：版本 1..10 各自 `if v < N` 补齐 → 都落到 `v<11` 空操作 → `data['version']=11`；坏版本（非 dict/`v<1`）走 1743-1748 重建。四条真实场景实测覆盖 v8/v10，另 test_sceneio/test_skybox_scene 覆盖坏字段。
4. **实际**（探针 05 第 1 段）：
   ```
   v8  压测50球.json   -> 物体 51, 材质 51, 天空盒 valid=True, 资产问题 0, 资产上下文=None
   v8  压测500混合.json -> 物体 501, 材质 501, 天空盒 valid=True, 资产问题 0
   v10 PacMan2D.json  -> 物体 126, 材质 126, 天空盒 valid=True, 资产问题 0
   v10 场景.json      -> 物体 3, 材质 17, 天空盒 valid=True, 资产问题 0
   ```
5. **判定**：**DISPROVED**（v8/v10 均可加载、无资产报错；v11 闸门只作用于写侧 + `min_engine_version` 读侧）。

### P-16 · 并发写 assets.json 可能写坏索引 · **P-UNKNOWN**

1. **位置**：`loom_assets.py:236-250`（`tmp = p + '.tmp'` 固定名，无锁；并发两个上下文各自 `open(tmp,'w')`+写+fsync+`os.replace`）。
2. **契约**：`save_index` docstring「原子写」；原子性只保证"不出现半个文件被 replace"，**不保证两个写者互不踩**。
3. **路径枚举**：A 串行 → 后者胜（丢前者的新增条目，属"最后写入者覆盖"设计缺失）；B 真并发 → 两个 fd 同时写同一 tmp，长度不同 → 可能产生"前者的长内容 + 后者的短覆盖"混合体 → `json.load` 失败 → 触发 P-02 全盘作废。
4. **实际**：未能构造确定性复现（缓冲写小于一页时 OS 常表现为整体覆盖）。已尝试的探针：无（本轮时间预算内无法做可靠压测）。
5. **差异**：无法判定"是否真能写出非法 JSON"；**能判定的是**：即使不出非法 JSON，也会丢条目（A 路径），而丢条目在有 `import_texture` 自动 `save()` 的多入口（编辑器 + EAI 命令 + 迁移脚本）下是现实场景。
6. **触发条件**：两个进程/线程同时对同一项目导入资产。
7. **验证（建议的下一步探针）**：起 2 进程各 200 次 `import_texture`（不同源图），结束后 `load_index` 计数并校验 JSON；统计条目丢失率与 JSON 损坏率。若条目丢失率 > 0 → 升级为 P-PROVED（P2，丢失即 P-01 的触发器）。
8. **影响与等级**：**P-UNKNOWN**（本条保留，不计入 P1/P2 统计）。

### P-17 · ③三类失败对 GUI 用户不可见 · **P-PROVED（P2）**

1. **位置**：`sceneio.py:202`（唯一出口是 `print`）、`editor.py:1197-1271`（`_load_scene` 全程无 `_notify`）、`agent_commands.py:2488-2497`（唯一结构化出口是 EAI 命令）。
2. **契约**：`record_asset_error` docstring「形状对齐 `_skybox_valid/_skybox_error`」；而天空盒失败在 beta5 是有 UI 口径的（`skybox_get` 可查、编辑器可提示）——B1 的三类失败（guid 解析失败/文件缺失/指纹不符）应有同等可见性。
3. **路径枚举**：
   - 加载路径 A：编辑器 `_load_scene` → 只 `print`（无 `_notify`/状态栏/对话框）→ GUI 用户看不到。
   - 加载路径 B：release 播放器 → 无控制台（`run_player` 注释明确"发布档无控制台"）→ 完全不可见，只看到画面缺图。
   - 查询路径 C：EAI `scene_assets_check` → 可见，但**天空盒不在其中**（P-05）。
4. **实际**：`grep -n "_asset_errors|asset_errors|资产问题" Loom/*.py` 的命中全部在 `sceneio/agent_commands/scene_driver`，无一处进入 `_notify`/GUI 面板；`editor.py:1246` 之后也无二次检查。
5. **差异**：预期=打开含坏引用的场景时至少有可见提示（如 `_notify('资产问题 2 条')`）；实际=仅控制台。
6. **触发条件**：任意一次缺资产打开（配合 P-01 就是"看不见 → 顺手保存 → 丢资产"）。
7. **验证**：`Select-String -Path Loom/editor.py -Pattern "_notify" ` 附近的 `_load_scene` 段（1197-1271）无资产分支；探针 01/06 的 stdout 是唯一出口。
8. **影响与等级**：**P2**（可见性违约，是 P-01 的放大器；不单独造成损坏）。

---

## 3. 统计

| 判定 | 数量 | 编号 |
|---|---|---|
| **P-PROVED** | **14** | P-01…P-13, P-17 |
| ├ P1（功能错误/不可逆丢失/崩溃） | 3 | P-01 保存销毁 guid、P-02 一条坏条目废整本、P-03 用户层坏条目崩加载 |
| ├ P2（边界/接口/可见性） | 7 | P-04 name 越界、P-05 天空盒体检假绿、P-06 六面图无指纹校验、P-07 迁移产物缺版本闸、P-08 dry-run 失效、P-09 打包静默漏资产、P-17 失败不可见 |
| └ P3（可维护性/审计层） | 4 | P-10 悬空 guid 无报告、P-11 材质双源、P-12 死字段、P-13 高版本场景中断整批 |
| P-DISPROVED | 2 | P-14 兼容闸门成立、P-15 v8/v10 可加载 |
| P-UNKNOWN | 1 | P-16 并发写索引（无确定性探针） |
| P-CONTRADICTION | 0 | 无（双向链未出现互斥结论） |
| 观察项（不计入判定） | 3 | ① GL/VK 旧路径告警不对称（scene_driver.py:157 处文件在途修改）② 资产面板每帧 `_asset_context()`（缓存命中，未实测帧耗时）③ `set_texture` 去重时 import_settings 被丢弃（loom_assets.py:482-484） |

- 跳过登记：7 条（1.2 节），每条均给四类理由之一。
- 全部 P-PROVED 附可跑命令 + 实测输出；探针文件位于 `Loom/tests/_tmp/audit_b6r5_*`。
- 本轮工具产生的受跟踪文件改动：**0**（只写 `_tmp` 探针与本报告；`git status` 中的 M 项均为他人并发在途改动，见 0.2）。

## 4. 修复建议排序（只给方向，不含代码）

1. **P-01（P1，最高优先）**：写侧"解析失败不得改写引用"。方向：`scene_to_dict` 增加"资产引用快照"——加载时把每个槽位/天空盒的原始 ref 记到引擎（`_asset_refs`），写侧在对象为 None 时回写原始 ref 并保持告警；`_save_scene` 在 `asset_errors` 非空时给可见提示（"本次保存将保留 N 条失效引用"），而不是让用户无感地丢资产。
2. **P-02（P1）**：`validate_index` 改为"剔除坏条目 + 返回 ok/reasons"，`load_index` 只有在**完全无法解析**（JSON 坏 / 缺 assets 键）时才返回 None；`for_dir` 把 `create` 透传给 `open_root`，并让 `open_root(create=True)` 在覆盖前先备份 `assets.json.bak`；诊断串必须区分"缺文件"与"索引损坏"。
3. **P-03（P1）**：`resolve` 对 delta/entry 逐层做类型判定（非 dict 一律视为无 delta 并记 reason）；`scene_from_dict` 的资产段整体包一层 try/reason，保证任何资产异常都不穿透到"已清空场景"的状态。
4. **P-04（P2）**：`_unique_dest`/`import_cubemap` 对 name 做 `basename + 非法字符替换 + 保留 `..` 检测`；`validate_index` 追加"src 必须在 `Assets/` 之下"（否则导入成功但打包必漏）。
5. **P-09（P2）**：`build_game` 在 `copy_project_assets` 返回 False 时扫描场景 dict，若存在 guid-only 引用则 `SystemExit`（"场景引用了项目资产库，但找不到 Assets/assets.json"），与 `ckernels`/`解释器.json` 自洽断言同级。
6. **P-05 + P-17（P2）**：天空盒失败也走 `record_asset_error`（或 `scene_assets_check` 合并 `_skybox_valid/_skybox_error`）；编辑器加载后若有 `asset_errors` 用 `_notify` 汇总一条。
7. **P-06（P2）**：cubemap 的 fingerprint 改为"逐面 sha256 + 总字节数"，并在 `resolve` 的目录分支里比对（成本用"仅当 mtime/size 变时才逐面 sha"控制）。
8. **P-07（P2）**：迁移脚本复用 `sceneio.scene_to_dict` 的版本字段约定（或直接把 `min_engine_version` 写进 `migrate()` 的 v11 段）。
9. **P-08 / P-13（P2/P3）**：`--dry-run` 用"内存临时索引"预演（或在报告里显式区分"将新建索引"）；逐场景 try/except `SceneVersionError` → 记 failure 继续。
10. **P-10 / P-11 / P-12（P3）**：迁移报告区分"已迁移"与"悬空 guid"；材质资产的 `value` 与场景 `materials[]` 二选一为真相源（另一方只写 id）；`config['assets']` 要么被玩家侧消费，要么删除。

---

## 5. 需人类裁决的封闭问题

1. **Q1：资产解析失败后保存，应该"保留失效引用"还是"清空槽位"？**
   - A（推荐）：保留原始 ref + 持续告警 —— 代价：场景里长期存在失效引用，需要 `scene_assets_check` 常态化。
   - B：清空槽位 —— 代价：P-01 现行为（不可逆丢失），但场景"干净"。
2. **Q2：`assets.json` 中一条坏条目，应该"剔除该条继续"还是"整本拒绝"（现行为）？**
   - A（推荐）：剔除 + 明示条数与原因。
   - B：整本拒绝 —— 代价：一条手改错误即让全项目退化为旧路径模式（配合 Q1 会丢资产）。
3. **Q3：材质资产的唯一真相源放哪？**
   - A：只放 `Assets/assets.json`（场景只写 `material_id`）—— 代价：材质不再是"场景自包含"，换项目即失效。
   - B：只放场景 `materials[]`（资产库仅登记指针）—— 代价：无法跨场景复用/热更新。
   - C：现状双写（需明确"谁覆盖谁"的规则，否则 P-11 无解）。