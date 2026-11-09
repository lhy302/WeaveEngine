# 天空盒 · 场景与命令侧（01 号）beta5 新修复扫描报告

日期：2026-11-09　扫描者：01 号子代理　基线：71b31ac..HEAD　结论对象：**本轮新代码引入的、未被处理的边界/未定义行为**

---

## 0. 范围与方法

### 0.1 文件与 diff 规模（git diff --stat 71b31ac..HEAD）

| 文件 | 变更行 | 关键函数（本次改动面） |
|---|---|---|
| Loom/sceneio.py | 226 | default_skybox / parse_color / skybox_from_dict / _apply_skybox / _scene_skybox_from_data / _apply_skybox_or_default / _emit_skybox / _emit_camera / _apply_cameras / scene_to_dict / scene_from_dict |
| Loom/agent_commands.py | 224 | cmd_skybox_set / cmd_skybox_clear / cmd_skybox_get / _skybox_source / _skybox_describe / _vk_skybox_info（另含 engine_metrics 段，非本号范围） |
| Loom/editor.py | 71 | _scene_dir / _effective_skybox / _refresh_effective_skybox / _scene_digest / _load_scene / _new_scene / set_active_camera / toggle_play / render |
| Loom/loom_scene_entities.py | 4 | CameraState.skybox 注释（白盒契约声明） |

合计 4 文件：**+431 / -94**。改前版本用 git show 71b31ac:<file> 对照；被删掉的关键旧保护是：旧 _apply_skybox 的 except Exception: pass，以及旧 scene_from_dict 外层的 try/except -> engine._skybox = None。

### 0.2 跑过的命令（全部只读；探针落 Loom/tests/_tmp/，被 Loom/.gitignore:20 的 tests/_tmp/* 忽略）

```
git diff 71b31ac..HEAD -- Loom/{sceneio,editor,agent_commands,loom_scene_entities}.py
python tests/_tmp/scan_beta5_01_probe.py    # P01-A/B/C/D/E/F/G/H/I
python tests/_tmp/scan_beta5_01_probe2.py   # P01-J/L/M/N（+ dispatch）
python tests/_tmp/scan_beta5_01_probe3.py   # P01-O/P/Q
python tests/_tmp/scan_beta5_01_probe4.py   # P01-R/S/T（含 VK driver 对照）
python tests/_tmp/scan_beta5_01_probe5.py   # P01-U/V/W
python tests/test_skybox_scene.py           # 既有回归：ALL PASS
python tests/test_skybox_engine_parity.py   # 既有回归（真 moderngl 离屏）：ALL PASS
git status --porcelain                       # 自查：无受跟踪文件被本号改动
```

git status --porcelain 自查（收尾时刻）：`?? docs/audit/scan_beta5_round_01_skybox_scene.md`（本报告）、` M docs/audit/scan_beta3_05_packaging_release.md`、`?? tools/lint_except_dist/`、`?? tools/loom_lint_except.py`。后三项在本号开始前既存。

另需登记（非本号动作）：`Loom/bench_result.txt` 在本号开始时是 ` M`，收尾时已回到与 HEAD 一致（mtime 2026/11/9 14:16:57）。全仓只有 build_entry.py:275 会写该文件，本号从未运行 build_entry / Loom.py --bench，故判为并发会话（其它子代理或编辑器）写入后又还原；本号全程未执行 git checkout / add / commit / stash。

GL 证据形态：EditorApp.__new__ + GLEngine._build_gpu 无头桩（与既有 test_skybox_scene.py 同款）；真 moderngl 离屏已由 test_skybox_engine_parity.py 跑通（证明本机 GL 可用）。本号未做像素级核验，见 U-02。

---

## 1. 粗筛清单（含跳过留痕）

| ID | 位置 | 标签 | 初步方向 |
|---|---|---|---|
| P01-A | agent_commands.py:1040-1049 | IFACE-PRECOND / AUDIT-DOCIMPL | skybox_set 先把 _skybox 置 None 再算"生效"，生效值可能恒为 None |
| P01-B | sceneio.py:605-611 + 1319 | BND-EMPTY / IFACE-PRECOND | skybox_from_dict 直接 d.get，非 dict 值没有可控错误路径；旧 try/except 已删 |
| P01-C | agent_commands.py:1053-1062 | SEM-DEFAULT | skybox_clear 落盘 null，重载按 Q1=A 变回默认蓝 |
| P01-D | sceneio.py:686-688 | SEM-MISMATCH | _source_paths 无条件优先回写，与"相对当前场景目录"语义冲突 |
| P01-E | sceneio.py:751-754 | AUDIT-ASYMMETRY | 相机没有 skybox 也被标 _skybox_valid=False + 假原因 |
| P01-F | agent_commands.py:1121-1123 | SEM-SILENT | skybox_get 的 valid/reason 只来自场景级，相机级失败不可查询 |
| P01-G | editor.py:2037 / 2075-2077 | BND-CONCURRENCY | 播放期改天空盒无守卫、toggle_play 不快照 _scene_skybox |
| P01-H | sceneio.py:586-589 | AUDIT-DOCIMPL | nan/inf 的报错文案断言"看起来是 0-1 浮点" |
| P01-I | sceneio.py:644-649 | AUDIT-DEADCODE | _apply_skybox 已无调用方；空 dict 不出声与 docstring 矛盾 |
| P01-J | sceneio.py:556-559 | IFACE-ERROR | default_skybox 未包 try，而同文件 skybox_from_dict 包了 |

**跳过留痕（判定无风险并跳过，理由必须是可外部审计的四类之一）**

| SKIP | 位置 | 跳过理由（第几类 + 具体事实） |
|---|---|---|
| S-01 | sceneio.py:561-596 parse_color 主逻辑 | 第 3 类：既有回归 test_skybox_scene.py ③④ 覆盖，且本号 P01-H 用 30 组输入复测一致 |
| S-02 | sceneio.py:682-703 _emit_skybox 的 solid 分支 | 第 1 类：_solid_color 由 Cubemap.from_solid 构造为 4 元组，`if solid:` 恒真（源码事实） |
| S-03 | editor.py:888-891 _scene_dir | 第 1 类：纯 dirname(abspath) 表达式，无分支 |
| S-04 | editor.py:2339 绘制门 + loom_render.py:73-79 | 第 3 类：test_skybox_scene.py ⑦ 已断言源码门表达式；本号只补"门为 False 的可达性"证据 |
| S-05 | loom_scene_entities.py:170-178 | 本次仅注释，无代码变更（diff 事实） |

---
## 2. 逐项裁决（8 段式）

### P-01 · PROVED · P1 · [REGRESSION] skybox_set 之后"生效天空盒"恒为 None —— 设置命令在编辑器里完全不生效

1. **位置**：Loom/agent_commands.py:1040-1049（核心是 1043 行 ed._skybox = None）
2. **契约/预期**：命令 docstring 与 test_skybox_scene.py ④ 隐含"设置即生效"；editor.py:1229 注释明写"engine 侧字段保持**场景默认**语义"，即 _skybox 是渲染端唯一读取面（engine.py:1339 `return getattr(self, "_skybox", None)`）。
3. **路径枚举**（effective_skybox() 全部路径，engine.py:1331-1339）：
   - 路径1：有激活相机且 cam.skybox is not None -> 返回相机级（不受 _skybox 影响）；
   - 路径2：无激活相机 / 相机 skybox 为 None -> 返回 self._skybox（**此命令已置 None**）；
   - 无第三条。命令本身只有 paths / solid / 错误返回三条分支，且都在 1043 行之前完成取值。
4. **实际行为**：新 Cubemap 只写进 _scene_skybox（1040），随后 _skybox = None（1043），_refresh_effective_skybox()（editor.py:906-922）只比较对象并调 reset_sky_state()，**不写回 _skybox**（该方法全文无赋值）。
5. **差异**：预期"设置后立刻可见"；实际"设置后渲染端读到 None"，且返回值 1049 行三元式在 eff is None 时仍报 effective=scene —— 与事实相反。
6. **触发条件**：任何 skybox_set（solid 或 paths），只要当前激活相机的 skybox is None（即绝大多数场景）。
7. **验证**：python tests/_tmp/scan_beta5_01_probe.py
```
skybox_set -> {"ok": true, "effective": "scene", "source": "solid"}
ed._scene_skybox = (10, 200, 30, 255)
ed._skybox (渲染端场景级字段) = None
ed.effective_skybox() = None
editor.render 的绘制门 (effective_skybox() is not None) -> False
scene_to_dict 落盘的 skybox -> {name: 绿, guid: fa1562…, solid_color: [10, 200, 30, 255]}
```
第三道独立证据：loom_render.py:73-79 —— `cube = eff()` 之后 `if cube is None: return`，即便绘制门被改，_draw_skybox 仍空转。
8. **影响与等级**：**P1 功能错误**。[REGRESSION] 改前 skybox_set 直接写 ed._skybox = cube，设置立即可见；本轮为"强制 refresh 走变更分支"加入 1043 行后功能丢失。既有测试没抓到：test_skybox_scene.py:173-174 只断言 ok is True，test ④ 只断言落盘与**重载后**一致，无一条断言"设置后 effective_skybox() 非空"。

### P-02 · PROVED · P1 · [REGRESSION] 场景 skybox 为非 dict 的非空值时 GL 侧 AttributeError 崩溃，且旧场景已被清空

1. **位置**：Loom/sceneio.py:611（`paths = d.get("paths")`）；调用点 sceneio.py:1319（旧 try/except 已删）；编辑器入口 editor.py:1167-1176。
2. **契约/预期**：sceneio.py:1316-1318 新注释明写"Q5=A 有值但解析失败 -> 出声 + 回退默认蓝 … 不得静默"；_scene_skybox_from_data docstring 承诺返回 (cube, valid, reason)；skybox_from_dict docstring 称"失败一律给 reason（不抛、不静默）"。
3. **路径枚举**（scene_from_dict 里 skybox 的可达输入类）：
   - 缺键 / None / {} / 0 / 空串 -> `if not d` 早退 -> 默认蓝（安全）；
   - dict -> skybox_from_dict 内部 try 覆盖（安全）；
   - **非空非 dict：str / list / int / float / bool** -> 直接 d.get -> AttributeError，无 except。实测五类全部触发。
4. **实际行为**：异常从 sceneio.py:1319 冒泡到 editor._load_scene:1175，该处**没有 try**；而 _load_scene 此前已执行 remove_model 全部模型（1170）、undo.clear()（1172），并已把 _scene_path 改成坏文件（1167）。
5. **差异**：预期"回退默认蓝 + valid=False + reason"；实际"崩溃 + 当前场景被清空 + _scene_path/_scene_dir 指向坏文件"。与同文件 1151-1153 行自己立的 F7 不变量（坏场景不得先丢当前工作）直接冲突 —— 那次收口只覆盖了 _validate_object_graph，没覆盖 skybox。
6. **触发条件**：任何 "skybox": "…" / "skybox": [...] / "skybox": 1 的旧/手写/脚本写坏/合并坏的场景文件（mcp_procedural_arena 类生成物是高危来源）。GL 编辑器崩；VK 的 SceneDriver.load_from_data（scene_driver.py:567-574）有 try，只报错不崩 —— 同一文件一个崩一个开。
7. **验证**：
```
# probe.py B 段
skybox=abc       -> 抛 AttributeError: "str" object has no attribute "get"
skybox=[1,2,3]   -> 抛 AttributeError: "list" object has no attribute "get"
skybox=5         -> 抛 AttributeError: "int" object has no attribute "get"
skybox=True      -> 抛 AttributeError: "bool" object has no attribute "get"
skybox=3.5       -> 抛 AttributeError: "float" object has no attribute "get"
# probe2.py J/W 段
_load_scene 抛 AttributeError: "str" object has no attribute "get"
加载后 models = 0（旧场景被清空）  _scene_path = …/bad.json
_scene_path 是否已指向坏文件 = True
失败后 _scene_dir() = …/dirB（已指向坏文件目录 = True）
# probe4.py S 段（VK 对照）
skybox=oops -> VK: skybox=None valid=False error=天空盒解析入口不可用: AttributeError(…)   # 不崩
              GL: 抛 AttributeError: "str" object has no attribute "get"
```
另外 AC.dispatch 会把异常转成 {"ok": false, "error": "AttributeError(…)"}（agent_commands.py:352-354），即 **Agent 侧只看到一条 error，编辑器里的场景已经没了**。
8. **影响与等级**：**P1（崩溃 + 数据丢失）**。[REGRESSION] 改前为 `try: engine._skybox = _apply_skybox(...) except Exception: engine._skybox = None`，且旧 _apply_skybox 自带 `except Exception: pass` —— 同类输入改前被降级为"无天空盒"，改后崩溃。修复方向：skybox_from_dict 首行加 isinstance(d, dict) 判据 -> (None, False, "skybox 必须是对象")；并（或）把 skybox 解析纳入 _load_scene 的"加载前校验区"。

### P-03 · PROVED · P1 · 六面图相对路径的"基准目录"保存时不重算 —— 新建场景/另存为都会把天空盒写坏

1. **位置**：Loom/sceneio.py:686-688（_source_paths 无条件优先）；产生相对路径的两处：sceneio.py:629（加载时）与 agent_commands.py:1015-1029（skybox_set，基准 = ed._scene_dir()）。
2. **契约/预期**：Q6=A（sceneio.py:541-548 注释）"六面图 paths 以**相对场景目录**的形式序列化，加载时按 base_dir 解析"；editor.py:888-891 说明未存盘场景的基准只能是 CWD —— 但保存时的场景目录不一定等于当时的 CWD。
3. **路径枚举**（相对路径的三种来历）：
   - a) 从文件加载 -> _source_paths = 原文件里的相对串（基准 = 原文件目录）；
   - b) skybox_set 且场景已存盘 -> rel 相对 _scene_dir()（= 场景目录，正确）；
   - c) skybox_set 且场景**未存盘** -> rel 相对 CWD（保存后即错位）；
   - d) 跨盘符 -> except 回退绝对路径（agent_commands.py:1024-1025，此路正确，实测 P01-D valid=True）。
   a/b/c 三种都在 _emit_skybox 命中 `if src and len(src)==len(paths)` 分支被**原样回写**，base_dir 参数不再参与。
4. **实际行为**：保存到新目录后文件里的相对路径仍以旧基准为准 -> 重载按新目录拼接 -> isfile False -> 回退默认蓝（_scene_skybox_from_data:664-665）。
5. **差异**：预期"另存/首次保存后天空盒仍可用"；实际"静默换成默认蓝天盒"（只留一行 stdout，valid=False）。
6. **触发条件**：① 新建场景（_scene_path=None 故 _scene_dir()=CWD）设六面图后**首次保存**到任意目录；② 打开 A 目录场景后**另存为**到 B 目录。
7. **验证**：
```
# probe3.py O 段（同盘、未存盘场景）
_scene_dir() (=CWD) = D:/…/Loom
stored = [tests/_tmp/sbscan01/assets/px.png, …]
存到 proj/ 写入 = [tests/_tmp/sbscan01/assets/px.png, …]        # 基准没有重算
从 proj/ 重载: valid=False error=第 0 面图片不存在: D:/…/proj/tests/_tmp/sbscan01/assets/px.png
# probe.py E 段（另存为）
加载 dirA 后 _source_paths = [px.png, …]
另存到 dirB 时写出的 paths = [px.png, …]
从 dirB 重载: valid=False error=第 0 面图片不存在: …/B/px.png
```
8. **影响与等级**：**P1（用户资产丢失，且改前不存在该路径）**。修复方向：_emit_skybox 不盲信 _source_paths，而是把解析后的绝对路径按**本次 base_dir** 重新 relpath（跨盘/relpath 失败再回退绝对），即"保存时以当前场景目录为准"；或 skybox_set 在场景未存盘时只保存绝对路径。

### P-04 · PROVED · P2 · skybox_clear 不可持久化：落盘 null -> 重载按 Q1=A 复活默认蓝（"清不掉"且无任何提示）

1. **位置**：Loom/agent_commands.py:1053-1062（清空 + _skybox_valid=True，注释"显式清空 = 用户意图"）；读取侧 sceneio.py:658-660（`if not d: return default_skybox()`）。
2. **契约/预期**：命令描述"清空场景级天空盒"，返回 {"ok": True, "cleared": True}；注释把"用户意图"当作与"解析失败"区分的依据。
3. **路径枚举**：清空后可落盘的三种可能 —— ① 写 "skybox": null（当前实现，_emit_skybox(None) -> None）-> 重载命中 `not d` -> **默认蓝**；② 不写该键 -> 同样默认蓝；③ 写"显式关闭"标记 -> 当前**不存在这种表示**。三条路没有一条能表达"关掉天空盒"。
4. **实际行为**：clear -> 保存 -> 重载 得到 (58,155,213,255) 默认蓝。
5. **差异**：预期"清空是可持久状态"；实际"该状态在数据模型里不可表示"。
6. **触发条件**：任何一次 skybox_clear + 保存 + 重开。
7. **验证**（probe.py C 段）：
```
skybox_clear -> {"ok": true, "cleared": true, "effective": null}
落盘 skybox = None
重载后 _scene_skybox = (58, 155, 213, 255)  valid= True
重载后 effective_skybox() = (58, 155, 213, 255)
```
8. **影响与等级**：**P2（语义/可持久化缺口）**。这是 Q1=A 的直接推论，需人类裁决（见 §5 Q-1）；代码侧至少要**出声**（返回值里显式说明 cleared 仅本会话有效），否则 EAI/用户会认为文件已改。

### P-05 · PROVED · P2 · 相机级天空盒失败不可查询；"没有相机天空盒"被伪造成解析失败

1. **位置**：Loom/sceneio.py:751-757；查询面 agent_commands.py:1099-1126。
2. **契约/预期**：loom_scene_entities.py:170-178 与 sceneio.py:749-750 注释"相机级 skybox 非 None 时优先，None 时用场景默认" —— **None 是合法语义**，不是错误；Q5=A 要求解析失败可见（skybox_get 带 valid/reason）。
3. **路径枚举**：
   - 相机无 skybox 键 -> skybox_from_dict(None) -> (None, False, "缺少 paths/solid_color") -> cam._skybox_valid=False（**伪错误**）；
   - 相机 skybox 为坏 dict（如 [0.2,0.4,0.8]）-> valid=False + reason，cam.skybox=None -> 静默回落场景级；
   - skybox_get 只读 ed._skybox_valid / ed._skybox_error（1121-1123）-> 上述两条**都进不了查询面**。
4. **实际行为**：坏相机天空盒只打一行 stdout（755-757 有 d.get("skybox") 守卫，故"缺失"不刷屏）；skybox_get 的 valid 仍是场景级的 True。
5. **差异**：预期"相机级失败也能被 skybox_get 看见"（命令描述写明 valid/reason）；实际只有场景级。
6. **触发条件**：任何相机 skybox 报错（改坏/删图）；以及任何"检查 cam._skybox_valid 判断相机天空盒有效性"的未来消费方（当前仓库无消费方，属潜在雷）。
7. **验证**（probe.py F 段）：
```
cam.skybox = None  cam._skybox_valid = False  cam._skybox_error = 缺少 paths/solid_color
# 坏相机天空盒：GL 只 print，skybox_get[valid] 仍为 True（与 probe3 M/N 段同源证据）
```
8. **影响与等级**：**P2**。修复方向：① 相机 skybox 为 None 时应为 valid=True/error=None（"继承场景级"）；② skybox_get 增 cameras 段（每相机 valid/error），或把当前激活相机的 error 并入顶层 reason。

### P-06 · PROVED · P2 · 双后端对"天空盒入口异常"的回落不一致：VK 落 None（黑底），GL 落默认蓝或崩

1. **位置**：Loom/scene_driver.py:567-574（VK 的 except 分支 self.skybox, self._skybox_valid = None, False）vs sceneio.py:1319-1325（GL 无 try）。
2. **契约/预期**：scene_driver.py:564-566 注释"与 GL/编辑器**逐条一致** … 缺键/null -> 默认蓝；失败出声并记 valid/error（不静默、不回退成无天空）"；Q1=A"打开场景**一定**有天空盒"。
3. **路径枚举**：入口异常只有两种来源 —— (i) 非 dict 值（P-02）；(ii) import loom_cubemap / sceneio 失败。两者在 VK 都落到 skybox=None；在 GL 都无 except。
4. **实际行为**：同一份坏文件：VK 打开成功但 effective_skybox() = None（黑底），GL 抛异常。
5. **差异**：契约"不静默、不回退成无天空"被 VK 的 except 分支自己违背。
6. **触发条件**：P-02 的输入类别；或运行环境缺 loom_cubemap。
7. **验证**（probe4.py S 段）：
```
skybox=oops      -> VK: skybox=None valid=False error=天空盒解析入口不可用: AttributeError(…)
                    GL: 抛 AttributeError: "str" object has no attribute "get"
skybox=[1, 2, 3] -> VK: skybox=None valid=False
skybox={"solid_color":[0.2,0.4,0.8]} -> VK: (58,155,213,255) valid=False   # 这条两端一致，正确
```
8. **影响与等级**：**P2（多后端语义分叉）**。修复方向：让 _scene_skybox_from_data 永不抛；VK 的 except 分支改为回落 default_skybox()（与 GL 同一条）。

### P-07 · PROVED · P3 · 播放期 skybox_set 污染编辑场景（无守卫 + toggle_play 不快照 _scene_skybox），与新注释"播放前后恒等"不符

1. **位置**：agent_commands.py:1011-1049（无 is_playing 守卫）；editor.py:2037-2038 / 2075-2077。
2. **契约/预期**：editor.py:2076 新注释"退出播放后按恢复的 active_camera 重算生效的那一个（**播放前后恒等**）"；toggle_play 对其他场景态（models/lights/cameras/active_camera/投影）全部快照恢复。
3. **路径枚举**：toggle_play 的 _play_* 字段实测为 [_play_active_camera, _play_camera_snap, _play_cameras, _play_edit_cam, _play_edit_proj, _play_exit_*, _play_light_snap, _play_lights, _play_models, _play_parents, _play_snap] —— **无任何 skybox 字段**；且 `"_scene_skybox" in toggle_play` = False。
4. **实际行为**：播放期 skybox_set 直接写 ed._scene_skybox，退出播放后不回滚 -> 下一次保存把它写进文件。
5. **差异**：预期"播放是隔离沙箱"（其余状态均如此）；实际"播放期改天空盒会写进编辑场景"。注释里的"恒等"只对"按 active_camera 重算"成立，对"播放期被改写"不成立。
6. **触发条件**：播放中点 EAI skybox_set（或脚本/命令面板调用）。
7. **验证**（probe3.py Q 段）：
```
ed.is_playing = True; skybox_set(solid_color=[255,0,0]) -> ok=True
_scene_skybox = (255, 0, 0, 255)          # 编辑期基线 = (58,155,213,255)
播放期 scene_to_dict 会写出的 skybox = [255, 0, 0, 255]
toggle_play 里 "_scene_skybox" 出现? False
```
8. **影响与等级**：**P3（状态机/可维护性）**；注意**非本轮引入**（改前 _skybox 同样被播放期命令直改），但本轮把"落盘源"从 _skybox 改成 _scene_skybox 后两个字段都需要快照，风险面翻倍，建议随本轮一并收口（_play_scene_skybox）。

### P-08 · PROVED · P3 · _apply_skybox 成死代码且"空 dict 不出声"，与自身 docstring 不符

- 位置 sceneio.py:644-649。全仓 grep 只剩定义本身（唯一旧调用点已被 skybox_from_dict 直接取代）；_apply_skybox_or_default（668-671）同样无调用方。docstring "失败: **出声** + 返回 None" 与 `if not valid and d:`（空 dict -> 不出声）矛盾。等级 P3。

### P-09 · PROVED · P3 · parse_color 的报错文案对 nan/inf 指向错误原因；接受不带 # 的 hex（比契约宽）

- 位置 sceneio.py:586-589、sceneio.py:572。实测 [nan,0,0] -> "颜色通道 #0=nan 不是 0..255 的整数（看起来是 0-1 浮点）; 请乘 255"（nan 不是 0-1 浮点，乘 255 仍是 nan）；"3A9BD5"（无 #）被接受，而 docstring 只承诺 #RRGGBB。等级 P3（文案/宽松度）。

### P-10 · PROVED · P3 · 目录当文件时报错文案说"图片不存在"

- 位置 sceneio.py:621-622 / agent_commands.py:1019-1021。实测 paths=[assets]*6 -> "第 0 面图片不存在: …/assets"（该路径是**存在的目录**）。isfile 判定本身正确（拒绝），只是文案误导。P3。

---
### D-01 · DISPROVED · 默认天空盒每次新建 -> 是否造成假脏/撤销错乱（对应重点 ⑥⑦）

1. 位置：editor.py:1228-1231（default_skybox() 每次新 guid）。
2. 契约：_scene_digest 表示"自上次保存/加载后有改动"；_new_scene 末尾 mark_saved()。
3. **路径枚举**（脏判定的三条进入路径）：① _new_scene（1228 设新 cube -> 1247 mark_saved 重算基线）；② _load_scene（1192 同步两字段 -> 1199 mark_saved）；③ save_scene（成功后 mark_saved）。三者都是"改对象 + 重算基线"成对出现，没有只改一半的路径。
4. 实测：新建后 scene_is_dirty() = False；再新建一次 guid 变化 = True（64b7ed… / 1de901…）；新建后仍 scene_is_dirty() = False；加载缺 skybox 键的旧场景后 scene_is_dirty() = False（probe5.py V 段）。
5. 差异：无假脏。唯一副作用：旧场景"打开后另存"会把默认天空盒**补写**进文件（内容变化，但不是假脏提示），与 Q1=A 一致。
6. 撤销：skybox_set / _new_scene 都不产生 undo 记录（改前亦然），不存在"撤销后天空盒与脏判定不一致"的更早基线问题。
7. 结论 **DISPROVED**（默认天空盒不影响脏判定/撤销）。

### D-02 · DISPROVED · skybox 缺键 / null / 空 dict 的语义（重点 ①）

{}、None、缺键 -> 默认蓝 + valid=True（GL 与 VK 逐位相同，既有 test_skybox_engine_parity.py A 段 ALL PASS）；{"name":"x"} / {"paths":[],"solid_color":null} -> 默认蓝 + valid=False + reason"缺少 paths/solid_color"（probe2.py N 段）。与 Q1=A"有值但解析失败 -> 出声 + 回退默认蓝"一致。

### D-03 · DISPROVED · parse_color 30 组边界（重点 ②）

实测（probe.py H 段）与 Q4=A 逐条相符：顶层标量 0/255/-1/256/12.5/None/True/False 全部拒绝；[] / [1,2] / [1,2,3,4,5] 长度错误拒绝；[True,1,2] / ["a",1,2] / [None,1,2] 拒绝；[300,0,0] 越界拒绝；[0.2,0.4,0.8] 拒绝（旧病灶）；[58.0,123.0,213.0] / [255.0,0.0,0.0,255.0] 放行并按 0..255 取值；#RRGGBB / #rrggbbaa / 大小写 / strip 空格 放行；[255,255,255,0] 保留 alpha 0。nan/inf 被拒绝（仅文案问题见 P-09）。

### D-04 · DISPROVED · 相机级优先的异常组合（重点 ⑤）

probe2.py M 段：两相机同 guid -> find_camera 取第一个（绿）；active_camera 指向不存在 guid -> 回落场景级（红）；删除激活相机对象后同 guid 的另一台被取到。三条路径都**不抛**、都回落到可用对象；set_active_camera(None/cam) 均调 _refresh_effective_skybox()（editor.py:1896-1902）。遗留的同 guid 歧义（数据层允许 id 重复且无唯一性契约）未单列 PROVED，仅记录。

### D-05 · DISPROVED · 六面图数量/目录/中文路径（重点 ④）

probe3.py P 段：目录当文件 -> 拒绝并报路径；缺一面(5)/多一面(7) -> 拒绝并给出应有顺序 px,nx,py,ny,pz,nz；中文文件名 -> ok=True 且相对路径正确。`..` 越界**被允许**（probe4.py R 段：../assets/px.png 解析为场景目录外的绝对路径，valid=True）—— 属"允许读本地任意文件"的设计取舍，非崩溃缺陷，列入 §5 Q-3。

### D-06 · DISPROVED · skybox_set 失败不改状态

probe.py I 段：skybox_set([1,2]) 失败后 skybox_get 的 valid 与 solid_color 与失败前逐位相同（True / [58,155,213,255]）；test_skybox_scene.py ③ 亦断言 _scene_skybox is before。

---

### U-01 · UNKNOWN · 六面图路径的大小写敏感性（重点 ④ 的"大小写"）

已知：Windows NTFS 大小写不敏感，本机无法构造反例。需什么信息才能定：在 Linux/macOS（大小写敏感文件系统）跑同一场景；代码侧 skybox_from_dict:621 用 os.path.isfile 未做 normcase 或大小写回退 —— 若要求跨平台相对路径，则缺一层"大小写容错或明确报错"。建议探针：CI linux runner + 同名不同大小写文件。

### U-02 · UNKNOWN · skybox_set 之后"零天空盒"的端到端像素证据

逻辑链已闭合（P-01 的绘制门 + loom_render 早退），但**未做像素级核验**：editor.render 需要 GLFW 真窗口（扫描协议 §0.5 禁止启动 GUI 窗口）。需什么信息：可离屏化的 editor.render 路径，或把门/早退抽成纯函数。当前用两级源码事实 + 无头桩实测取代像素证据；若要 A6 级"实测输出"，需人类批准启动一次 GUI 截图。

### U-03 · UNKNOWN · numpy 数值通道是否算合法输入

实测 parse_color([np.int64(58),0,0,255]) -> 拒绝（"颜色通道 #0 必须是数值"），np.float64(58.0) -> 放行（probe5.py U 段）。仓内唯一调用方是 JSON 入参（skybox_set）与场景文件解析，**不存在** numpy 通道来源 -> 按不可达判不成立；但近期 buckets numpy 化若把颜色改成 numpy 表示，会静默拒绝。需什么信息：是否有计划把 _solid_color 改成 numpy 表示。

---

## 3. 统计

| 结论 | 数量 | 编号 |
|---|---|---|
| P-PROVED | 10 | P-01…P-10（P1 x3、P2 x3、P3 x4） |
| P-DISPROVED | 6 | D-01…D-06 |
| P-UNKNOWN | 3 | U-01…U-03 |
| P-CONTRADICTION | 0 | — |

分级：**P0 = 0**；**P1 = 3**（P-01 / P-02 / P-03）；**P2 = 3**（P-04 / P-05 / P-06）；**P3 = 4**（P-07 / P-08 / P-09 / P-10）。

P-UNKNOWN 非 0 的原因：两项受平台/交互限制（跨平台大小写、需 GUI 窗口的像素核验），一项依赖未来数据表示决策；每项均已写明"需要什么信息才能定"。

[REGRESSION] 清单（由 71b31ac..HEAD 引入）：**P-01（P1，功能丢失）、P-02（P1，崩溃 + 数据丢失）**。P-03 / P-04 属"新契约下的新缺口"（改前无六面图相对路径能力、改前 clear 可持久），随本轮一并计入。

---

## 4. 修复建议排序（只给方向，不含代码）

| 序 | 项 | 方向 |
|---|---|---|
| 1 | P-01 (P1) | skybox_set 不得把渲染端字段清成 None：要么同时写 _skybox = cube，要么让 _refresh_effective_skybox 把 eff 写回 _skybox（保持"渲染端只读 _skybox"这条 Q3 声明）。_draw_skybox 已有 `_sky_prog_for is not cube` 的重编译判定（loom_render.py:81-85），不需靠 None 触发；同时修 1049 行三元式（eff 为 None 时不能报 scene）。补一条"set 后 effective_skybox() is cube"的回归断言。 |
| 2 | P-02 (P1) | skybox_from_dict 首行加 isinstance(d, dict) 判据 -> (None, False, "skybox 必须是对象")；把 skybox 解析前移到 _validate_object_graph 同一"加载前校验区"（或加 try），让"坏场景不毁当前场景"的不变量对 skybox 也成立。 |
| 3 | P-03 (P1) | _emit_skybox 以"保存时的 base_dir"重新 relpath，不要盲信 _source_paths；或把 _source_paths 的基准目录一并记下，保存时发现 base_dir 变了就重算。 |
| 4 | P-04 (P2) | 引入"显式关闭天空盒"的可序列化表示（如 {"enabled": false}）；否则 skybox_clear 必须在返回值里明确"仅本会话有效"。 |
| 5 | P-05 (P2) | 相机 skybox 为 None 时应 valid=True/error=None；skybox_get 增加相机级 valid/error 面（至少当前激活相机）。 |
| 6 | P-06 (P2) | VK except 分支回落 default_skybox()，或让 _scene_skybox_from_data 永不抛而删掉该 except。 |
| 7 | P-07 (P3) | skybox_set/clear 加 is_playing 守卫，或增加 _play_scene_skybox 快照。 |
| 8 | P-08/09/10 (P3) | 删死代码 _apply_skybox；修 nan/inf 文案；目录/文件用语区分；hex 是否允许省略 # 写进契约。 |

---

## 5. 需要人类裁决的封闭问题

**Q-1（对应 P-04）**"关闭天空盒"是否需要**可持久化**？
- A：需要 -> 数据层新增显式关闭表示（代价：场景格式多一个语义位，GL/VK 两个解析器都要同步）；
- B：不需要（默认蓝就是项目一贯底色，clear 只作本会话调试手段）-> skybox_clear 返回值必须写明"不持久化"（代价：用户仍会误以为文件被改）。

**Q-2（对应 P-05）**相机级天空盒解析失败，是否必须进 skybox_get 的 valid/reason？
- A：必须（Q5=A 对相机级同样生效）-> 查询面加相机段（代价：返回结构变更，可能影响既有 EAI 消费方）；
- B：只按"回落到场景级"处理并保留 stdout 一行（代价：EAI 无法机器判定某相机天空盒坏了）。

**Q-3（对应 D-05）**六面图路径是否允许越出场景目录（../ 与绝对路径）？
- A：允许（当前行为；本地编辑器无安全边界诉求）-> 在 Q6=A 文案里显式写明；
- B：禁止 -> skybox_from_dict 增加 realpath 前缀校验并给 reason（代价：共享资产目录/跨盘工程需搬迁图片）。
