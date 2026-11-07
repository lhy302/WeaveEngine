# 撤销 / 文件对话框 / 网络 / 帧缓冲 / GUI 加载 扫描报告（scan_12_misc，2026-11-07）

> 只读审计。仓库写入：仅本报告。探针全部在 %TEMP%\loom_scan12，仓库零改动。
> 环境：Windows，Python 3.12.10，moderngl 5.12.0，glfw 2.10.2，pygame 2.6.1。
> 探针运行前置：PYTHONDONTWRITEBYTECODE=1、LOOM_NO_SAVE_MIGRATE=1；未运行 tests/run_all.py。

## 0. 范围与方法

### 0.1 文件清单（行号均以本报告所引 HEAD 为准）

| 文件 | 行数 | 语言 | 本轮最后改动 commit |
|---|---|---|---|
| undo.py | 1018 | Python | 75c889d 2026-10-19（聚光灯快照加 spot 内外锥角） |
| filedialog.py | 259 | Python/ctypes | 49aff0b 2026-10-18（_parent_hwnd pygame→GLFW） |
| loom_net.py | 211 | Python 标准库 | de1bc51 2026-10-20（**本轮新增文件**） |
| frame_buffer.py | 243 | Python（纯逻辑） | 89141af 初始提交（本轮未改） |
| guiloader.py | 233 | Python（纯逻辑） | 89141af 初始提交（本轮未改） |

### 0.2 git 前置核对（先做，再谈回归）

- HEAD = 4f46650（2026-10-20 11:15:57 +0800）。
- git diff HEAD -- Loom/undo.py Loom/filedialog.py Loom/loom_net.py Loom/frame_buffer.py Loom/guiloader.py 输出为空；git status --porcelain 对这 5 个文件也为空 → **本模块工作区无未提交改动**。
- 因此 [REGRESSION] 只能来自"本轮已提交改动"：
  - f0ad76a 2026-10-20 新增 UI Shape 元素（agent_commands/loom_ui/sceneio/loom_mcp），**undo.py 未被改动** → 见 P-04；
  - de1bc51 2026-10-20 新增 loom_net.py → 该文件所有缺陷都属本轮引入，见 P-09/P-10；
  - 75c889d 2026-10-19 改 undo.py 聚光灯快照：diff 仅加 spot_inner_angle/spot_outer_angle 两键（快照/应用成对），**未发现该 diff 引入的新缺陷**；
  - 49aff0b 2026-10-18 改 filedialog _parent_hwnd：diff 仅换 pygame→GLFW，见 P-08；
  - frame_buffer.py/guiloader.py 自初始提交未改 → 本模块无这两文件的回归。

### 0.3 跑过的命令与已跑测试

| 命令 | 结果 |
|---|---|
| python tests/test_undo.py | ALL PASS（exit 0，约 40 项 PASS） |
| python tests/test_frame_buffer.py | Ran 18 tests ... OK（exit 0） |
| python probe_undo.py | 见 P-01/P-02/P-03/P-04 各链第 7 段原文输出 |
| python probe_undo_order.py | 见 P-06 |
| python probe_filedialog.py | 见 P-07/P-08 |
| python probe_net.py、probe_net_cancel.py | 见 P-09/P-10/D-07/U-01 |
| python probe_frame_buffer.py、probe_preframe_fbo.py | 见 P-11/P-12/P-13 |
| python probe_guiloader.py | 见 P-14/D-04 |

**已有测试的盲区（本轮证据）**：test_undo.py 只测了 Add/Delete/State/材质引用/相机参数槽位，**未测** 光源 range、normal_mode、prefab_ref、材质 albedo/PBR/LOD、UI Shape、event_bindings、材质库登记；test_frame_buffer.py 的 T6 只测记账/闸门，**未创建任何 GL 画布**（commit() 无 FBO 时故意不置 ready），因此 P-11/P-12 的 GL 行为完全无覆盖。

## 1. 粗筛清单（六元组；含跳过留痕）

> 粗筛不是判决；每条只说明"值得推演"的具体代码事实。阶段二结论见 §2。

### 1.1 疑似项

| ID | 位置 | 标签 | 初步方向 | 粗筛证据（代码事实） |
|---|---|---|---|---|
| P-01 | undo.py:158-204 | SEM-MISMATCH / AUDIT-ASYMMETRY | 光源 range 可经 EAI/GUI 改，但 light_snapshot/apply_light_snapshot 不含该字段 → 撤销无效 | light_snapshot 键集合无 range；LightState.__init__ 有 self.range（loom_scene_entities.py:83）；agent_commands.py:1508 'range': ('range', as_float) |
| P-02 | undo.py:27-68 + editor.py:1433-1439 | SEM-MISMATCH / AUDIT-DEADCODE | snapshot() 只存材质引用/基础字段；commit_model 用快照相等性决定是否压栈 → 若干"已宣布可撤销"的命令实际不产生撤销项 | snapshot 无 normal_mode/prefab_ref/lod_*/材质 albedo/PBR/env；commit_model 的 if after != before: push |
| P-03 | undo.py:441-493 + loom_model_gpu.py:74-89,291-296 | IFACE-PARTIAL | 物体删除/重挂的 do/undo 不配对：材质库登记只在 add_model 时发生 | remove_model 会把无引用材质移出 engine.materials；attach_model/DeleteObjectCommand.undo 不重新登记 |
| P-04 | undo.py:591-769 + loom_ui.py:768-803 | SEM-MISMATCH / AUDIT-DEADCODE（**本轮 REGRESSION**） | 新增 ctype='shape' 未进 UI 快照 → 改 shape 字段后 before==after，ui_set 不压撤销；即使压栈也不还原 shape 字段 | ui_elem_snapshot 分支止于 grid_layout；cmd_ui_add/ui_set 已有 shape 分支（agent_commands.py:2144-2154, 2294-2303）；loom_ui.Shape 新增字段 shape_type/points/radius/stroke_color/stroke_width/fill_color/segments/close |
| P-05 | undo.py:591-679 + agent_commands.py:2348-2378 | SEM-MISMATCH | event_bindings（序列化设计数据）不在快照；ui_bind_event/ui_unbind_event 根本不压撤销栈 | sceneio.py:643-645 序列化 event_bindings；两个 EAI/MCP 命令直接改 dict 后 return |
| P-06 | undo.py:481-493 | SEM-MISMATCH | 删除子树撤销只恢复父链不恢复兄弟顺序 | parent_of 只存 parent，不存 parent.children 索引；undo 用 par.children.append(m) |
| P-07 | filedialog.py:244-248 | BND-RESOURCE / IFACE-PRECEDN | SHBrowseForFolderW 返回指针但未声明 restype，64 位下默认 c_long 截断低 32 位；随后未声明的 SHGetPathFromIDListW 用截断值当指针 | 模块内只给 GetSaveFileNameW/GetOpenFileNameW 设了 restype/argtypes；shell32 两函数均未设置 |
| P-08 | filedialog.py:69-84（49aff0b 改动） | TOOL-SIDE / SEM-SILENT | 编辑器无 GLFW 窗口时调用 glfw.get_current_context() 会触发 GLFW "not initialized" 警告 | 探针 stderr：GLFWError: (65537) b'The GLFW library is not initialized' |
| P-09 | loom_net.py:201-204 + 182-189 | BND-CONCURRENCY / SEM-MISMATCH（**本轮新文件**） | cancel() 宣称"让结果被丢弃"，但后台线程完成后会覆写 _result | _run 在 finally 前无条件 self._result = ...；cancel 只写 _result/_done |
| P-10 | loom_net.py:151-157 | IFACE-ERROR | http_post_json 对不可 JSON 序列化对象抛 TypeError，与模块其余路径"返回错误 dict"不一致 | _json.dumps(obj) 在无 try 的函数体 |
| P-11 | frame_buffer.py:188-194,210-218 + ui/loom_gui.py:1261-1272 + editor.py:1957 | IFACE-PRECOND / SEM-MISMATCH | begin() 绑定离屏 FBO，但 EditorApp.render 显式 _screen_fb().use() 回 widget FBO → 预画从未写进离屏，blit 把未初始化 FBO 拷上屏 | _screen_fb() 外部模式返回 _external_fb；paintGL 缓存 _widget_fb；begin 只 self._fbo.use()，无 _external_fb 切换 |
| P-12 | frame_buffer.py:178-186 | AUDIT-DOCIMPL / BND-RESOURCE | ensure_canvas 文档写 "RGB + 深度"，实际只建 color attachment，无 depth | docstring 179 行 vs 183-186 行 ctx.framebuffer(color_attachments=[self._fb]) |
| P-13 | frame_buffer.py:50-57,107-111 | BND-EMPTY | configure/ledger_from_settings 对 None/字符串做比较/取整会抛 TypeError | 无类型归一 |
| P-14 | guiloader.py:144-161 | BND-UNICODE / TOOL-HEURISTIC | 头部标记解析按 strip().lower().replace(' ','')；UTF-8 BOM 或 tab 分隔会使合法标记失效 | 探针：BOM 首行 / #\tgui:\tloom 均被判非法 |

### 1.2 跳过登记（四类理由之一 + 出处）

| SKIP | 位置 | 跳过理由（类型） | 具体事实 |
|---|---|---|---|
| S-01 | loom_net.py:56-66 SSL 上下文 | 白盒契约明确声明（模块 docstring 第 6-7 行：内置 CA、verify=True 校验） | 代码与声明一致；_make_ssl_context 有 cafile 兜底 |
| S-02 | filedialog.py:19-66 Windows API 绑定 | 白盒契约明确声明（文件 docstring 第 3 行："Windows 原生文件对话框"） | 项目发布目标为 Windows（build_all.bat / wintypes / _glfw Win32 调用）；非 Windows 导入失败不在契约内 |
| S-03 | guiloader.py:35-46 DEFAULT_SETTINGS | 语言规范保证 + 已有测试覆盖（test_guiswitch.py t_settings） | dict() 浅拷贝只含标量；坏文件回默认有测试 |
| S-04 | frame_buffer.py:35-104 Ledger 记账深度/预算/闸门 | 已有回归测试覆盖（test_frame_buffer.py T1/T2/T5 全绿） | 深度封顶、12ms 红线、闸门均有断言 |
| S-05 | undo.py:962-1018 UndoManager 栈语义 | 已有回归测试覆盖（test_undo.py 全部 PASS，含 redo 清空/深撤） | 双栈 push/undo/redo/limit 路径 |
| S-06 | undo.py:226-247 apply_camera_snapshot(engine=None) 丢父 | 路径枚举证明生产不可达（见 D-01） | 四个调用点全传 engine |
| S-07 | guiloader.py:115-134 设置读写原子性 | 白盒契约明确声明（"坏文件/缺文件回默认"；tmp+os.replace） | 有 test_guiswitch 覆盖 round-trip/坏 JSON |

## 2. 逐项裁决（8 段式）

### 【P-01 · 证真 · P-PROVED】光源 range 不在撤销快照 → 命令"一步撤销"实际不入栈
1. **判定基准**：undo.py:159 light_snapshot docstring"光源可撤销字段 -> dict（与 apply_light_snapshot 成对）"；editor.py:1476"光源字段命令"；agent_commands.py:1498 light_set 描述"光源属性 (一步撤销)"；MCP loom.py:120 unity_light_set 暴露 range。
2. **代码证据**：undo.py:161-178 返回键为 kind/position/direction/color/intensity/name/mode/shape/size/shadow/azimuth/elevation/roll/spot_inner_angle/spot_outer_angle，**无 range**；undo.py:181-204 同样不写 l.range；loom_scene_entities.py:83 self.range=float(range)；agent_commands.py:1508 'range': ('range', as_float)；editor.py:1487-1492 commit_light 仅在 after != before 时 push LightStateCommand。
3. **路径枚举**：(a) 只改 range → before==after → 不压栈；(b) 同时改 intensity 等已覆盖字段 → 压栈，但 undo() 用 apply_light_snapshot(before) 不写 range；(c) redo() 写 after 也不写 range；(d) 保存场景 → sceneio.py:334 序列化 l.range，保存的是"撤销未生效的新值"。四条路径都不产生"撤销恢复 range"。
4. **预期**：range 修改后 Ctrl+Z 恢复旧值（如 10.0），与 intensity 等字段同语义。
5. **实际**：probe_undo.py 实测：range 改动 before==after: True | 'range' in light snap: False；apply(before) 后 l.range: 3.0（期望 10.0）。
6. **差异**：预期 10.0，实际保持新值 3.0；撤销栈里根本没有该次修改的记录（路径 a），后续 Ctrl+Z 会回退更早的无关操作。
7. **可复现验证**：cd %TEMP%\loom_scan12；set PYTHONIOENCODING=utf-8；python probe_undo.py（输出见上）。
8. **影响与等级**：P1 功能错误（命令宣称可撤销但静默不入栈；EAI/MCP 可达；GUI 检查器当前无 range 行，故主要暴露面是 AI 命令与 unity_light_set）。

### 【P-02 · 证真 · P-PROVED】snapshot 未覆盖 normal_mode / prefab_ref / 材质属性 / LOD → 多条 commit_model 命令不产生撤销项
1. **判定基准**：editor.py:1433-1435 commit_model docstring"单次字段命令: 取 before 快照(可覆盖) -> apply_fn -> 压撤销"；undo.py:28 snapshot docstring"物体可撤销字段 -> dict (不变式: 与 apply 成对)"；各命令描述均写"一步撤销/命令撤销"。
2. **代码证据**：undo.py:29-68 snapshot 键为 position/rotation/scale/color/saturation/visible/name/layer/tag/material/scripts/collider/rigidbody/audio_source/animator；editor.py:1438-1439 if after != before: undo.push；未覆盖字段与命令：normal_mode（GameObject 属性 loom_game_object.py:159-164；cmd agent_commands.py:1058-1069）、prefab_ref（loom_game_object.py:36；editor.py:1651-1652 unlink_prefab）、材质 albedo/PBR/env（agent_commands.py:1128,1144,1174,1233,1247）、LOD（agent_commands.py:1195,1211）。
3. **路径枚举**：(a) 仅改上述字段 → snapshot before==after → 不压栈；(b) 与其他已覆盖字段同批改 → 压栈，但 undo 不恢复这些字段；(c) 保存场景 → sceneio.py:91/103/104 等会序列化对应字段，撤销未生效的新值被落盘。三类路径均不满足"可撤销"。
4. **预期**：set_normal_mode / unlink_prefab / set_texture / set_pbr / set_env / set_lod 各自产生撤销项，Ctrl+Z 恢复旧字段。
5. **实际**：probe_undo.py 实测 normal_mode 改动 before==after: True；材质 metallic/pbr 改动 before==after: True；prefab_ref 改动 before==after: True；LOD 改动 before==after: True；且 snapshot 键中对应键均不存在（'normal_mode' in snap False 等）。
6. **差异**：预期撤销栈新增 1 条，实际 0 条；用户点"与 Prefab 断开连接"（GUI 按钮 ui/loom_gui.py:2922）后无法撤销，Ctrl+Z 会回退更早操作。
7. **可复现验证**：cd %TEMP%\loom_scan12；python probe_undo.py。
8. **影响与等级**：P1 功能错误（撤销栈完整性；GUI 可达 unlink_prefab，EAI/MCP 可达其余）。

### 【P-03 · 证真 · P-PROVED】AddObjectCommand.redo / DeleteObjectCommand.undo 不恢复材质库登记（do/undo 不配对）
1. **判定基准**：undo.py:442 AddObjectCommand amortized"撤销删除, 重做重新挂载"；undo.py:467 DeleteObjectCommand"构造时记录恢复所需全部信息"；loom_model_gpu.py:81 attach_model"重新挂载已存在的 GameObject (撤销删除/Prefab 实例化)"；loom_model_gpu.py:54 add_model 会 _register_model_material。
2. **代码证据**：loom_model_gpu.py:74-78 _register_model_material 把 model.renderer.material 加入 self.materials；loom_model_gpu.py:291-296 remove_model 在无其他物体引用时 self.materials.remove(mat)；undo.py:81-89 attach_model 只重建 GPU 并插入列表，**不调用 _register_model_material**；undo.py:481-493 DeleteObjectCommand.undo 只恢复 models/父链/GPU。
3. **路径枚举**：(a) AddObjectCommand undo（remove_model 移出材质）→ redo（attach_model 不登记）→ 材质永久离开材质库；(b) DeleteObjectCommand undo（模型回来，材质库不回来）；(c) scene_to_dict 兜底收集模型引用材质（sceneio.py:876-888）→ 存档不丢材质，但材质库/检查器/共享引用语义已不一致。三条路径实证。
4. **预期**：undo/redo 后 engine.materials 与 do 前一致（材质可被材质库面板与后续共享引用看到）。
5. **实际**：probe_undo.py：do 后材质在库 True（库 2）；undo 后 False（库 1）；redo 后 False（库 1，期望 True）。DeleteObject undo 后库中仍 False（模型已在场景 True）。scene_to_dict 材质数 3 且两 guid 均在（说明存档兜底存在，降低到 P2 而非 P1）。
6. **差异**：undo/redo 不是逆操作；engine.materials 少一个条目。
7. **可复现验证**：cd %TEMP%\loom_scan12；python probe_undo.py。
8. **影响与等级**：P2 边界/一致性问题（存档不丢；材质库/检查器/共享引用与状态不符）。

### 【P-04 · 证真 · P-PROVED · [REGRESSION]】UI Shape（ctype='shape'）未接入 ui_elem_snapshot/ui_apply_snapshot
1. **判定基准**：undo.py:592"UIElement 可撤销字段 -> dict（与 ui_apply_snapshot 成对）. ... 按 ctype 收集 type-specific 字段"；agent_commands.py:2307"撤销（仅当字段真的有变化时压栈）"；loom_ui.Shape docstring 声明 8 个专属字段。
2. **代码证据**：undo.py:607-679 snapshot 的 ctype 分支只有 panel/text/image/button/slider/toggle/progress_bar/scroll_view/input_field/dropdown/grid_layout，**无 shape**；undo.py:691-769 apply 同样无 shape；loom_ui.py:768-803 Shape 字段 shape_type/points/radius/stroke_color/stroke_width/fill_color/segments/close；agent_commands.py:2144-2154（ui_add shape）、2294-2303（ui_set shape）；git：f0ad76a 新增 Shape 但未改 undo.py（git log --oneline -S 'shape' -- undo.py 只命中初始提交）。
3. **路径枚举**：(a) ui_set 只改 shape 专属字段 → before==after → 2309-2313 不压栈；(b) 同时改 rect 等已覆盖字段 → 压栈，但 undo 只还原基础字段，shape 字段保持新值；(c) 保存场景 → sceneio 保存 shape 字段（f0ad76a 同步加），撤销未生效值落盘。
4. **预期**：loom_ui_add_line/polygon/circle 之后的 ui_set（例如改 stroke_color/points）应可撤销；undo 后 shape 字段回旧值。
5. **实际**：probe_undo.py：shape 快照键仅 ['anchor','ctype','enabled','name','pivot','rect','visible','z_order']；shape 字段改动 before==after: True；apply(before) 后 stroke_color 仍 (1,2,3,4)、points/radius 不变（期望回旧值）。
6. **差异**：快照缺 8 个 shape 字段，撤销命令不记录或不还原。
7. **可复现验证**：cd %TEMP%\loom_scan12；python probe_undo.py（末段）。
8. **影响与等级**：P2 边界/功能一致（**本轮 REGRESSION**：f0ad76a 新增元素类型未同步撤销层；EAI ui_set / MCP loom_ui_set 可达）。

### 【P-05 · 证真 · P-PROVED】event_bindings 既不在 UI 快照，ui_bind_event/ui_unbind_event 也不压撤销栈
1. **判定基准**：undo.py:592-595"只存设计期字段"；sceneio.py:643-645 把 event_bindings 作为设计期数据序列化；agent_commands.py:2317-2379 两个命令描述为常规 EAI 编辑命令（同类 ui_add/ui_set 均接撤销）。
2. **代码证据**：loom_ui.py:127 self.event_bindings={}；undo.py:597-606 snapshot 基础键无 event_bindings，各 ctype 分支也无；agent_commands.py:2350-2355 直接 elem.event_bindings[event]=binding 后 return；2370-2379 直接 del/clear 后 return，全程无 undo.push/_push_ui_undo。
3. **路径枚举**：(a) ui_bind_event → 无撤销项；(b) ui_unbind_event(event) → 无撤销项；(c) ui_unbind_event 清空 → 无撤销项；(d) 先 bind 再 ui_set 其他字段 → ui_set 的 before/after 也不含 event_bindings，撤销会保留 binding。四路径均无撤销能力。
4. **预期**：绑定/解绑可作为设计期编辑撤销（与 ui_add/ui_set 同决策"UI 编辑全部进撤销栈"）。
5. **实际**：probe_undo_order.py：event_bindings 在快照里: False | 快照键无 event_bindings；代码路径无压栈。
6. **差异**：撤销栈零记录；Ctrl+Z 回退无关操作。
7. **可复现验证**：cd %TEMP%\loom_scan12；python probe_undo_order.py（末两行）。
8. **影响与等级**：P2（MCP loom_ui_bind_event/unbind_event 可达；设计期数据无撤销）。

### 【P-06 · 证真 · P-PROVED】DeleteObjectCommand.undo 恢复父链时改变兄弟顺序
1. **判定基准**：undo.py:467-468"删除 root 整棵子树. 构造时记录恢复所需全部信息"；undo.py:473"记录: DFS 顺序, 各物体原父, 原平铺列表顺序"——未声明记录兄弟索引，但同文件 UI 版 UIRemoveCommand 记录 index 并插回原位（undo.py:844-864），说明项目内"删除撤销保序"的既有语义。
2. **代码证据**：undo.py:475 self.parent_of = {id(m): m.parent}；undo.py:485-489 恢复时 par.children.append(m)（只判 not in，不按原 index 插入）。
3. **路径枚举**：(a) 删除父下第一个子 → undo 追加到 children 末尾 → 顺序变；(b) 删除最后一个子 → 追加后顺序与原相同（巧合）；(c) 删除无父根 → 仅 models 列表恢复（models_before 保留原序）。路径 a 产生可观测差异。
4. **预期**：undo 后父 children 顺序与删除前一致（层级树/序列化 DFS 顺序稳定）。
5. **实际**：probe_undo_order.py：删除前 A.children ['B','C']；删B后 ['C']；undo 后 ['C','B']；顺序保持 False。
6. **差异**：子顺序由 B,C 变为 C,B。
7. **可复现验证**：cd %TEMP%\loom_scan12；python probe_undo_order.py。
8. **影响与等级**：P3 可维护性/顺序稳定（3D 渲染不受影响，但层级树展示与 scene_to_dict DFS 顺序会变）。

### 【P-07 · 证真 · P-PROVED】经典目录对话框回退：SHBrowseForFolderW 返回指针被截断 → 访问违例/异常
1. **判定基准**：filedialog.py:145-146 _choose_directory_modern"任何 COM 设置/调用失败抛异常, 由 choose_directory 回退到经典对话框"；filedialog.py:215-216 _choose_directory_classic"返回目录路径, 取消 None"；filedialog.py:254-259 choose_directory 的经典回退在 try 之外（异常直接上抛调用方）。
2. **代码证据**：filedialog.py:244 pidl = shell32.SHBrowseForFolderW(ctypes.byref(bi))；模块只对 comdlg32.GetSaveFileNameW/GetOpenFileNameW 设 restype/argtypes（filedialog.py:63-66），**shell32 两函数均未设**（filedialog.py:229 shell32 = ctypes.windll.shell32；244/247 直接调用）；ctypes 默认 restype 为 c_long（Windows 32 位），返回的 64 位 LPITEMIDLIST 只保留低 32 位。
3. **路径枚举**：(a) 现代 COM 成功 → 不进入经典路径（P-07 不触发）；(b) 现代 COM 抛异常 → choose_directory except 调 _choose_directory_classic；(c) 经典路径用户取消 → pidl 为 0，返回 None（安全）；(d) 经典路径用户选中目录 → pidl 为 64 位指针 → 247 行 SHGetPathFromIDListW(pidl, path) 传截断值 → 读非法地址 → ctypes 抛 OSError（实测）或进程终止；(e) 截断值恰为 0 → 静默返回 None。d 为触发路径。
4. **预期**：经典回退在 COM 不可用时仍能返回所选目录（docstring 承诺）。
5. **实际**：probe_filedialog.py：SHBrowseForFolderW.restype = <class 'ctypes.c_long'>，argtypes = None；同机制 GetProcessHeap 默认 restype 返回 153944064(0x92d0000)，c_void_p 返回 2023083540480(0x1d7092d0000)，高位截断 True；把截断值传给 SHGetPathFromIDListW → OSError('exception: access violation reading 0x00000000092D0000')。
6. **差异**：预期返回路径，实际抛访问违例异常；回退路径不可用（且 choose_directory 无外层 try，异常直达调用方）。
7. **可复现验证**：cd %TEMP%\loom_scan12；python probe_filedialog.py（末段原文）。
8. **影响与等级**：P1 功能/安全（进程级访问违例；仅在 modern COM 失败时触发，触发概率取决于线程 COM 单元状态/系统策略；另：pidl 未 CoTaskMemFree，属附带泄漏）。

### 【P-08 · 证真 · P-PROVED】_parent_hwnd 在无 GLFW 初始化时产生 GLFWError 警告（本轮 49aff0b 改动）
1. **判定基准**：filedialog.py:70-73 _parent_hwnd docstring"编辑器模式（Qt）: 无 GLFW 窗口，返回 0（对话框独立，Qt 有自己的模态）"——预期编辑器下静默返回 0。
2. **代码证据**：filedialog.py:75-76 import glfw; win = glfw.get_current_context()；pyglfw 在库未初始化时调用会经 glfwGetError 发 GLFWError 65537 并 warnings.warn（site-packages/glfw/__init__.py:917，探针 stderr 原文）。
3. **路径枚举**：(a) 玩家运行时 GLFW 已 init 且有当前上下文 → 正常取 HWND；(b) 编辑器 Qt 无 GLFW 上下文 → glfw.get_current_context() 触发警告后返回 None → 返回 0；(c) glfw 未安装 → ImportError 被 except 吞 → 0。b 为触发路径。
4. **预期**：编辑器内每次弹文件对话框静默返回 0。
5. **实际**：probe_filedialog.py 调用 _parent_hwnd() 时 stderr 输出 GLFWError: (65537) b'The GLFW library is not initialized'，返回 0。
6. **差异**：功能结果正确（0），但每次调用产生警告噪声；pythonw 构建下 stderr 可能为 None，warnings 输出可能丢失或无影响。
7. **可复现验证**：cd %TEMP%\loom_scan12；python probe_filedialog.py 2>&1（末行）。
8. **影响与等级**：P3 可维护性/日志噪声（本轮 49aff0b 引入；非功能性）。

### 【P-09 · 证真 · P-PROVED · [REGRESSION]】loom_net.cancel() 后后台线程覆写结果，cancel 语义失效
1. **判定基准**：loom_net.py:201-204 cancel docstring"尝试取消（只能让结果被丢弃，不能中断已发的网络请求）"；async 用法文档 161-170"主线程轮询 is_done()/result()"。
2. **代码证据**：loom_net.py:182-189 _run 无条件 self._result = http_request(...)，随后 finally self._done.set()；loom_net.py:201-204 cancel 只写 self._result = {'ok': False, 'error': '已取消'}; self._done.set()；无锁、无取消标志。
3. **路径枚举**：(a) cancel 后立刻 result() → 读到"已取消"（探针第一次）；(b) cancel 后线程完成 → 线程覆写 _result 为真实响应，随后 result() 读到真实响应（探针 0.8s 后）；(c) cancel 后 wait=True timeout 未到但线程完成 → 同上；(d) 从不 cancel → 正常。b/c 违反契约。
4. **预期**：cancel 后任何时刻 result() 返回 {'ok': False, 'error': '已取消'}（或被丢弃的语义上不可见）。
5. **实际**：probe_net_cancel.py：cancel 立刻读 {'ok': False, 'error': '已取消'}；0.8s 后读 {'ok': True, 'status': 200, headers..., 'body': 'late-real-body', 'bytes': 14}；is_done True。
6. **差异**：已取消的请求结果在完成时"复活"，调用方可能把过期响应当当前状态处理。
7. **可复现验证**：cd %TEMP%\loom_scan12；python probe_net_cancel.py。
8. **影响与等级**：P2 并发/语义（**本轮新文件 de1bc51 引入**；游戏脚本在场景卸载后 cancel，仍可能收到回调式轮询结果）。

### 【P-10 · 证真 · P-PROVED】http_post_json 序列化失败抛 TypeError，破坏模块"错误 dict"模型
1. **判定基准**：loom_net.py 模块 docstring 34-37"r = http_get(...); if r['ok'] ... else print('失败:', r['error'])"，全模块错误均以 dict 返回；http_post_json docstring"HTTP POST JSON 简写。自动 Content-Type: application/json"。
2. **代码证据**：loom_net.py:155 body = _json.dumps(obj, ensure_ascii=False).encode('utf-8')，位于无 try 的函数体；对比 http_request 139-142 把异常转 {'ok': False, 'error': ...}。
3. **路径枚举**：(a) 可序列化 obj → dict 返回；(b) 含 set/自定义对象 → _json.dumps 抛 TypeError（未捕获）；(c) 含 NaN → json 默认允许 NaN（不抛）。b 为触发路径。
4. **预期**：与其他入口一致返回 {'ok': False, 'error': ...}（调用方可统一判断 r['ok']）。
5. **实际**：probe_net.py：POST JSON 不可序列化对象 → 抛出异常: TypeError Object of type object is not JSON serializable（无返回 dict）。
6. **差异**：异常 vs dict；调用方按 r['ok'] 使用会在序列化错误时崩溃。
7. **可复现验证**：cd %TEMP%\loom_scan12；python probe_net.py（POST JSON 段）。
8. **影响与等级**：P3 接口错误模型不一致（EAI/MCP 层可捕获，游戏脚本按文档写法会抛异常）。

### 【P-11 · 证真 · P-PROVED】FPS 预画 FBO 与 render 的 _screen_fb 绑定冲突：预画内容从未进离屏，blit 拷入空 FBO 黑帧
1. **判定基准**：frame_buffer.py:114-127 RenderFrameBuffer docstring"把下一渲染帧预画进离屏 FBO, 到节拍点 paintGL 直接 blit 上屏"；frame_buffer.py:188-194 begin"预画开始: 绑定离屏 FBO"；210-218 blit"预画帧整块上屏（目标 = widget FBO）"。
2. **代码证据**：frame_buffer.py:192-193 ensure_canvas 后 self._fbo.use()；ui/loom_gui.py:1261-1267 rb.begin(...) → e.render(0.0) → rb.commit()；但 editor.py:1957 self._screen_fb().use()，loom_render.py:296-298 外部模式返回 self._external_fb，ui/loom_gui.py:197-199 paintGL 把 self._widget_fb 写入 e._external_fb；_clear_main_fbo（loom_render.py:284-287）也再次 _screen_fb().use()。begin 从不切换 _external_fb。
3. **路径枚举**：(a) 预画 enabled 且 Qt 外部 ctx（唯一使用点 _preframe_in_gap）→ render 把画面画到 widget FBO，离屏 FBO 保持未初始化；(b) 下一拍 paintGL rb.has_ready() → rb.blit 把未初始化离屏拷到 widget → 黑/垃圾帧；(c) 预画 disabled → 不进入；(d) 若未来有人用 _external_ctx=False 的裸 GLFW 路径调用 begin，_screen_fb 返回 ctx.screen，同样绕过离屏。a→b 为生产路径。
4. **预期**：预画后的下一拍显示与正常帧一致的画面（离屏 FBO 收到完整 render 输出）。
5. **实际**：probe_preframe_fbo.py（moderngl standalone，按真实调用序模拟）：预画期间 widget FBO 中心 (0,255,0)；commit 后 ready；blit 后 widget 中心 (0,0,0)；离屏中心 (0,0,0)（从未被 render 写入）。说明 blit 用空画布覆盖了上一拍的正常画面。
6. **差异**：预期绿色预画帧，实际黑色空帧；预画期间画面反而被提前画到屏幕（时序副作用）。
7. **可复现验证**：cd %TEMP%\loom_scan12；python probe_preframe_fbo.py。
8. **影响与等级**：P1 功能/视觉（FPS 缓冲开启且重启后生效时，每个被消费的预画拍显示空帧；默认 frame_buffer_fps=False，且 UI 开关"重启播放生效"本身不准确——见 §5 裁决 Q3）。

### 【P-12 · 证真 · P-PROVED】ensure_canvas 无深度附件（文档声明 RGB+深度）
1. **判定基准**：frame_buffer.py:179 ensure_canvas docstring"离屏画布 (RGB + 深度), 尺寸变化重建"；frame_buffer.py:121-124"GL 状态由 render 自身建立 (与正常帧同一管线)"；loom_render.py:784 render 内 ctx.enable(moderngl.DEPTH_TEST)。
2. **代码证据**：frame_buffer.py:183-186 只 ctx.texture((w,h),4,dtype='f1') 与 ctx.framebuffer(color_attachments=[self._fb])，无 depth_attachment；__init__ 只有 _fb/_fbo/_size，无 depth 字段。
3. **路径枚举**：(a) 预画 FBO 无深度 + render 开 DEPTH_TEST → 深度测试无附件（等价永远通过），遮挡按绘制顺序；(b) 若 P-11 修复后预画真正生效 → 预画帧遮挡错误；(c) 关闭 FPS 缓冲 → 不触发。b 为修复 P-11 后的暴露路径。
4. **预期**：离屏画布带深度，预画帧遮挡与正常帧一致。
5. **实际**：probe_frame_buffer.py：同样绘制顺序（近绿先画、远红后画），frame_buffer 同款无深度画布中心 RGB=(255,0,0)（远覆盖近），带 depth_texture 画布中心 RGB=(0,255,0)（近保留）。
6. **差异**：无深度画布丢失遮挡关系。
7. **可复现验证**：cd %TEMP%\loom_scan12；python probe_frame_buffer.py。
8. **影响与等级**：P2 视觉正确性（仅在 FPS 缓冲启用且 P-11 修复后暴露；当前被 P-11 掩盖）。

### 【P-13 · 证真 · P-PROVED】FrameBufferLedger.configure / ledger_from_settings 对非数值输入抛 TypeError（潜伏边界）
1. **判定基准**：frame_buffer.py:51 configure docstring"由设置.json 决定开关。闸门: logic_fps >= 30 才可开"；107-111 ledger_from_settings"设置.json -> Ledger"。
2. **代码证据**：frame_buffer.py:53-54 want...; self.enabled = bool(want and logic_fps >= 30.0)（无归一）；109 int(settings.get('frame_buffer_depth', 2))（None 会 TypeError）。engine.py:469-472 先 _lf=float(...) 再 configure，且整块 455-478 包 try/except。
3. **路径枚举**：(a) engine 路径 logic_fps 已 float、depth 缺省 2 → 不触发；(b) 直接调用 configure(..., None/'30') → TypeError；(c) ledger_from_settings(depth=None) → TypeError。b/c 当前只有测试/外部调用者会触发。
4. **预期**：非法输入降级为关闭（与 configure 的 fps_limit 处理风格一致，frame_buffer.py:150-155 有 try/except）。
5. **实际**：probe_frame_buffer.py：logic_fps=None → TypeError "'>=' not supported between instances of 'NoneType' and 'float'"；str"30" → TypeError；ledger_from_settings(depth=None) → TypeError int() argument...
6. **差异**：异常 vs 降级。
7. **可复现验证**：cd %TEMP%\loom_scan12；python probe_frame_buffer.py（首段）。
8. **影响与等级**：P3 潜伏边界（engine 已挡；若其他调用者引入则启动期异常被外层吞掉，副作用是整块设置解析跳过）。

### 【P-14 · 证真 · P-PROVED】guiloader 头部标记对 BOM/tab 不容错
1. **判定基准**：guiloader.py:10-13"文件头部（前 8 行内）含前部标识： # gui: loom ... 只做文本解析、不 import —— 只有标识合法的文件才进可用列表"；<br>即"前 8 行内含标识"即可用。
2. **代码证据**：guiloader.py:148 open(..., 'r', encoding='utf-8')（非 utf-8-sig）；152 low = line.strip().lower()；157-158 low.startswith('# gui:')；marker = low.replace(' ', '')（只去空格，不去 tab）。
3. **路径枚举**：(a) 无 BOM + 空格分隔 → 合法；(b) BOM 在首行且标识在首行 → low 以 '\ufeff# gui:' 开头 → 不匹配；(c) BOM 在首行、标识在第 2 行 → 匹配；(d) 标识用 tab 分隔 → '#\tgui:\tloom' 经 replace(' ','') 仍含 tab → 不匹配。b/d 产生差异。
4. **预期**：前 8 行内出现合法标识的文件均可用（BOM 是文件编码前缀，不属于内容）。
5. **实际**：probe_guiloader.py：scan ids ['LoomGUI','Bom2GUI','NormalGUI']；BOM 且标识在首行 False；tab 分隔 False；BOM 第二行 True；普通 True。
6. **差异**：合法投放的 GUI 文件被静默排除（无日志）。
7. **可复现验证**：cd %TEMP%\loom_scan12；python probe_guiloader.py。
8. **影响与等级**：P3 容错/可用性（"放文件即换界面"的契约对 Notepad 默认 BOM 不成立）。

### 【D-01 · 证伪 · P-DISPROVED】apply_camera_snapshot(engine=None) 会丢相机父链
1. 判定基准：undo.py:226-228 docstring"engine 传则按 parent guid 解析父 (找不到=父被删 -> 脱父)"。
2. 代码证据：undo.py:239-247：engine is None 时 new_parent=None，且会从旧父 camera_children 移除。
3. 推理链（路径枚举）：调用点共 4 处——editor.py:1710、editor.py:1815（回滚）/ undo.py:350、353（CameraStateCommand）全部显式传 self/self.engine；undo.py 之外无调用（grep apply_camera_snapshot 全仓仅这 4 处 + 定义）。不存在 engine=None 的生产路径。
4. 预期：无。
5. 实际：无。
6. 差异：无。
7. 验证：grep -n "apply_camera_snapshot" *.py（仅上述 4 调用 + 定义）。
8. 判定：DISPROVED（P3 仅防御性 API 风险；不构成 bug）。

### 【D-02 · 证伪 · P-DISPROVED】apply_light_snapshot 只写角度不写 direction 会与渲染方向不一致
1. 判定基准：undo.py:159 light_snapshot docstring"M30 加平行光方向 3 角度"；loom_scene_entities.py:53"direction 现在是派生只读属性 (行进方向), 由 azimuth+elevation 算得"。
2. 代码证据：loom_scene_entities.py:94-108 @property direction 由 (azimuth, elevation, roll) 现算并缓存；110-116 setter 反算角度；undo.py:197-203 有 azimuth 键时写三角度、否则写 direction 触发反算。
3. 推理链（路径枚举）：(a) 新快照有 azimuth → 写角度 → direction 属性下次读取即派生新值；(b) 旧快照只有 direction → setter 反算角度，direction 一致；(c) 旧快照有 azimuth 但无 roll → roll 取 0，方向仍一致（仅自旋归零，快照本就不含 roll 语义）。无路径产生方向不一致。
4. 预期/实际：一致。
5. 差异：无。
6. 验证：python -c 读 LightState.direction 属性源码（loom_scene_entities.py:94-108）+ probe_undo.py 中 apply 后 l.range 与角度恢复。
7. 判定：DISPROVED。

### 【D-03 · 证伪 · P-DISPROVED】OPENFILENAMEW 结构体布局/IFileDialog vtable 索引有误
1. 判定基准：filedialog.py:33-34"64 位 Windows 下的 OPENFILENAMEW 结构体布局"；filedialog.py:168"IFileDialog vtable: 3=Show, 9=SetOptions, 12=SetFolder, 17=SetTitle, 20=GetResult"。
2. 代码证据：filedialog.py:35-59 字段序与 win32 OPENFILENAMEW 一致；168/194 行注释表；188 行 IShellItem vtable 5=GetDisplayName。
3. 推理链（路径枚举）：(a) 结构体大小——probe 实测 sizeof=152（与 Win64 期望一致）；(b) vtable 索引——Show(3)/SetOptions(9)/SetFolder(12)/SetTitle(17)/GetResult(20)/IShellItem::GetDisplayName(5)/Release(2) 与 COM 接口定义一致；无动态分派。
4. 预期/实际：一致。
5. 差异：无。
6. 验证：cd %TEMP%\loom_scan12；python probe_filedialog.py 首段（sizeof = 152）。
7. 判定：DISPROVED（P-07 的问题在未设置 restype/argtypes，不在布局）。

### 【D-04 · 证伪 · P-DISPROVED】guiloader.load_settings 对坏设置文件未兜底
1. 判定基准：guiloader.py:116"读 设置.json, 坏文件/缺文件回默认"。
2. 代码证据：guiloader.py:118-124 try/open/json.load/isinstance/except Exception: pass → 返回默认合并结果。
3. 推理链（路径枚举）：(a) 缺文件 → except → 默认；(b) 坏 JSON → except → 默认；(c) 顶层非 dict → isinstance False → 默认；(d) 合法 dict → update。probe 覆盖 a-c。
4. 预期/实际：probe：缺文件 LoomGUI；坏 JSON LoomGUI；顶层非 dict LoomGUI。
5. 差异：无。
6. 验证：cd %TEMP%\loom_scan12；python probe_guiloader.py（设置容错段）。
7. 判定：DISPROVED（契约明确允许静默回默认）。

### 【D-05 · 证伪 · P-DISPROVED】FrameBufferLedger 深度/预算/闸门记账有误
1. 判定基准：frame_buffer.py:64-93 docstring 与实现。
2. 代码证据：frame_buffer.py:70-78/80-93；测试 test_frame_buffer.py T1/T2/T5。
3. 推理链（路径枚举）：(a) enabled False → False；(b) outstanding>=max_depth → 拒绝并计数；(c) budget>0.012 → 拒绝；(d) 其余 → True；consume 只在 outstanding>0 递减。测试逐条验证。
4. 预期/实际：python tests/test_frame_buffer.py Ran 18 tests OK（exit 0）。
5. 差异：无。
6. 验证：python tests/test_frame_buffer.py。
7. 判定：DISPROVED。

### 【D-06 · 证伪 · P-DISPROVED】UndoManager 压栈/清 redo/深度限制错误
1. 判定基准：undo.py:968-984 docstring"执行 cmd 并压入撤销栈, 同时清空重做栈"。
2. 代码证据：undo.py:968-984 与 tests/test_undo.py 的"新 push 后 redo 栈空/撤销到初始"。
3. 推理链（路径枚举）：(a) push → do+append+清 redo；(b) 超 limit → pop(0)；(c) undo/redo 正常；测试覆盖 a-c。
4. 预期/实际：test_undo.py ALL PASS。
5. 差异：无。
6. 验证：python tests/test_undo.py。
7. 判定：DISPROVED。

### 【D-07 · 证伪 · P-DISPROVED】loom_net 超时/HTTP 错误分支未捕获
1. 判定基准：loom_net.py:72-77 返回模型"失败返回 {'ok': False, 'error': ...}"。
2. 代码证据：loom_net.py:127-142 分别捕获 HTTPError/URLError/socket.timeout/Exception。
3. 推理链（路径枚举）：(a) 200 → ok dict；(b) 4xx/5xx → HTTPError → status+body；(c) 连接/读超时 → URLError 或 socket.timeout（3.12 下 TimeoutError 别名）→ error 文本；(d) 其他 → generic。probe 覆盖 a/c。
4. 预期/实际：probe_net.py 超时返回 {'ok': False, 'status': None, 'error': '超时 (0.1s)'}（timeout=0.05 显示为一位小数是 %.1f 舍入，非缺陷）。
5. 差异：无。
6. 验证：cd %TEMP%\loom_scan12；python probe_net.py（timeout 段）。
7. 判定：DISPROVED（HTTPError 分支未实测，但代码路径与契约一致；见 U-01 的编码问题另行登记）。

### 【U-01 · 证伪与证真均不足 · P-UNKNOWN】响应编码是否必须遵循 Content-Type charset？
1. 判定基准：loom_net.py:119-123"尝试按 UTF-8 解码（失败则用 latin-1 保底）"——文档只承诺该策略；HTTP 语义通常按 Content-Type charset 解码，但模块未声明。
2. 代码证据：loom_net.py:120-123 body_text = decode('utf-8') except UnicodeDecodeError: decode('latin-1','replace')；未读取 headers['Content-Type'] 的 charset。
3. 推理链（路径枚举）：(a) UTF-8 响应 → 正确；(b) GBK 响应 → latin-1 成功但乱码；(c) 二进制 → 乱码但不抛；(d) 调用方自行按 headers 重新编码 body.encode('latin-1').decode('gbk') 可恢复（http_request 返回原 headers）。b 的行为符合模块文档，但是否符合"游戏脚本调中文 API"的产品预期未知。
4. 预期（未定）：代码注释策略 vs HTTP 标准策略，二者都自洽。
5. 实际：probe_net.py：GBK 响应 body repr='ÖÐÎÄÏìÓ¦'（期望"中文响应"）。
6. 差异：按 HTTP charset 预期不一致；按模块文档一致。
7. 验证：cd %TEMP%\loom_scan12；python probe_net.py（非 UTF-8 段）。
8. 判定：UNKNOWN（契约未定 → 见 §5 Q2；若要求 charset 感知则升级 P2）。

## 3. 统计

| 维度 | 数量 | 明细 |
|---|---|---|
| 粗筛疑似项 | 14 | P-01..P-14 |
| 跳过登记 | 7 | S-01..S-07（四类理由均有出处） |
| P-PROVED | 14 | P-01..P-14 |
| P-DISPROVED | 7 | D-01..D-07 |
| P-UNKNOWN | 1 | U-01（编码契约未定） |
| P-CONTRADICTION | 0 | 见下"为什么 0" |
| REGRESSION | 2 | P-04（f0ad76a 新增 Shape 未接撤销）、P-09（de1bc51 新文件 cancel 竞态） |
| P1 | 4 | P-01、P-02、P-07、P-11 |
| P2 | 5 | P-03、P-04、P-05、P-09、P-12 |
| P3 | 5 | P-06、P-08、P-10、P-13、P-14 |

**为什么 P-CONTRADICTION = 0**：14 条 PROVED 均由探针给出实测输出（含两条跨文件链 P-11/P-07），7 条 DISPROVED 均给出完整调用点/路径枚举（D-01、D-02 为"生产不可达"论证）。没有任何一项出现"证伪链声称覆盖全部路径"与"证真链给出反例"同时成立的情况。残余风险：D-03/D-07 对 COM/HTTPError 分支未做真实 UI/服务端交互（见各链第 7 段），若后续实测出现反例，应升级为 P-CONTRADICTION 并重跑阶段二。

**证据强度说明**：
- P-11 是跨文件集成缺陷（frame_buffer 契约 + ui/loom_gui 调用方 + editor/_screen_fb），探针在 moderngl standalone 上按真实调用序复现；未启动 Qt 编辑器窗口（协议禁止阻塞 GUI），因此第 7 段是"机制级复现"而非整窗截图。
- P-07 未真实弹出经典目录对话框（会阻塞），用同语义指针 API 复现截断与访问违例（见第 7 段），并给出 COM 回退触发路径。
- 其余 PROVED 均为直接调用被测函数的最小复现（不依赖 GUI/网络外网）。

## 4. 修复建议排序（只给方向，不含代码）

| 顺序 | 项 | 方向 |
|---|---|---|
| 1 | P-07 | 给 shell32.SHBrowseForFolderW 设 restype=c_void_p、SHGetPathFromIDListW 设 argtypes/restype；选完 CoTaskMemFree(pidl)；choose_directory 把经典回退包 try 并降级返回 None。 |
| 2 | P-11 | 明确"预画目标"归属：预画期间临时把 engine._external_fb 指向 rb 的离屏 FBO（结束后恢复），或让 _screen_fb 在 _preframing 时返回 detect_framebuffer/预画 FBO；同时保证 commit/blit 后状态与 widget FBO 绑定复原。 |
| 3 | P-01/P-02 | 扩展 snapshot/apply_snapshot、light_snapshot/apply_light_snapshot 覆盖 normal_mode、prefab_ref、lod_*、材质资产字段与 range；或按 §5 Q1 明示"这些命令不可撤销"并移除误导性标签。注意材质是共享资产：材质级字段进入撤销需定义"共享材质改动影响其他物体"的语义。 |
| 4 | P-04/P-05 | ui_elem_snapshot/ui_apply_snapshot 增加 shape 分支（8 字段）与 event_bindings 深拷贝；ui_bind_event/ui_unbind_event 改走 UIStateCommand（before/after 快照）。 |
| 5 | P-09 | _run 赋值前检查 cancelled 标志（或把 cancel 结果与真实结果分槽）；result()/is_done() 保持 cancel 后恒定。 |
| 6 | P-12 | ensure_canvas 建 depth_texture 并传给 depth_attachment（同时更新 _release 释放）；或改文档明确"无深度、仅限 2D/HUD 预画"。 |
| 7 | P-03 | attach_model 或 DeleteObjectCommand.undo 末尾重新登记材质到 engine.materials（幂等）；同时确认 AddObjectCommand.redo 路径。 |
| 8 | P-06 | DeleteObjectCommand 记录每个 m 在原 parent.children 的 index，undo 按 index 插回。 |
| 9 | P-10 | http_post_json 把 dumps/序列化错误包成 {'ok': False, 'error': ...}，与 http_request 对齐。 |
| 10 | P-13 | configure 增加 try/except 或 float() 归一（与 RenderFrameBuffer.configure 同风格）。 |
| 11 | P-14 | _parse_header 用 encoding='utf-8-sig'；marker 归一改为去除全部空白（re.sub(r'\s+', '', low)）。 |
| 12 | P-08 | 编辑器路径先判 glfw 是否可初始化/是否已有当前上下文，避免每次对话框刷 GLFW 警告（或直接 try 前静默 glfw 错误）。 |

## 5. 需要人类裁决的封闭问题（≤3，每条给出选项与代价）

**Q1 · 撤销覆盖范围（P-01/P-02/P-04/P-05 的共同根因）**
当前 undo.snapshot 只覆盖"基础字段 + 材质引用"，而 EAI/GUI 已把 normal_mode、prefab_ref、材质 albedo/PBR/env、LOD、光源 range、UI shape、event_bindings 暴露为可编辑。选哪条：
- A. 扩展快照，全部纳入撤销（代价：材质是共享资产，材质级修改会影响所有引用者，需定义"共享材质撤销"语义；快照体积/比较成本上升）。
- B. 明确这些字段"不可撤销"，同步修改命令描述/提示（代价：用户/AI 会失去对材质、LOD、Prefab 断开等操作的回退能力；需在 UI 上禁用或标注）。
- C. 只把"资产级"改动改成独立资产命令（材质/Prefab/LOD），基础字段仍走快照（代价：实现量最大，但语义最干净）。

**Q2 · FPS 渲染缓冲是否保留（P-11/P-12）**
当前 FPS 缓冲（frame_buffer_fps，默认 False）实现与 render 的 FBO 选择冲突，且离屏缺深度。选哪条：
- A. 修复并保留：预画时切换渲染目标 + 建深度附件，使其与正常帧逐位一致（代价：需覆盖 Qt/GLFW 两种宿主，需 GL 回归图）。
- B. 删除 FPS 预画，只保留 TPS 记账（代价：损失该实验特性，代码更简单）。
- C. 保留但降级为"仅 2D/HUD 场景可用"，文档标注 3D 遮挡不可靠（代价：限制用途，避免误用）。

**Q3 · loom_net 取消与解码契约（P-09/U-01）**
- 取消语义：A. cancel 后结果永久丢弃（加 cancelled 标志，线程完成也不写回）；B. 文档改为"cancel 仅标记，后台结果仍会到达"，调用方自行判断（代价：违反当前"已取消"语义，但实现最小）。
- 解码：A. 按 Content-Type charset 解码（需解析 headers，GBK 等正确显示）；B. 维持 UTF-8/latin-1 兜底并把"调用方需自行处理非 UTF-8"写进文档（代价：中文 API 返回乱码，脚本需二次解码）。

## 6. 附：自审 checklist（按方法论 §11.5）

- [x] 每条结论有文件:行号 + 可执行命令 + 实测输出（14 PROVED 均有探针；7 DISPROVED 有路径枚举）。
- [x] 证伪链均给出路径枚举，未用"检查了/看起来"措辞。
- [x] 跳过项 S-01..S-07 均引用四类理由之一的具体出处。
- [x] P-UNKNOWN 非 0（U-01），P-PROVED 非 0，P-CONTRADICTION 为 0 已解释。
- [x] 未修改任何受跟踪源码/测试；未 git add/commit；未跑 tests/run_all.py；探针全部在 %TEMP%\loom_scan12；LOOM_NO_SAVE_MIGRATE=1、PYTHONDONTWRITEBYTECODE=1。
- [x] 报告外无仓库写入；git status 对这 5 个目标文件为空（见 §0.2）。
- 说明：本报告只读审计，未对任何 PROVED 项实施修复（修复留待主 Agent 决策，见 §5）。
