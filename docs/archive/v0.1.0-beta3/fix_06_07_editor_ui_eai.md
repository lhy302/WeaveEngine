# 修复报告 — EAI 颜色/布尔/歧义 + 多 Canvas 命中 + Qt 输入顺序（批次：eai_color_multicanvas）

- 工程：`D:\my-project - 副本\Loom(py源代码-工作区)\Loom`（Windows / Python 3.12.10）
- 依据：`scan_07_eai.md` + `scan_06_editor_ui.md` 中分配给本批次的 6 项（第 7 项按要求不动）
- 只改：`agent_commands.py`、`loom_mcp.py`、`loom_ui.py`、`ui/loom_gui.py`；新增 3 个回归测试
- 未执行任何 `git add/commit`

---

## 1. [P0] `ui_add` 颜色字段：`tuple()` 收字符串 → 渲染帧 TypeError → 播放器退出

**位置**：`agent_commands.py` `cmd_ui_add`（原 2063/2068/2074/2080-2083… 等 30 余处 `take('xxx_color', tuple)`）、`_COLOR_FIELDS`（原 160-165）、`parse_color`（现 198）

**根因**
1. `tuple('#ff0000')` 得到 `('#','f','f','0','0','0','0')` —— 长度 7、元素是 `str`；
2. 该坏元组被写进元素属性，渲染帧 `loom_hud.draw_screen_rect` 里 `color[0] / 255.0` → `TypeError: unsupported operand type(s) for /: 'str' and 'float'`；
3. 渲染帧异常一路上抛，播放器（`game_player` / 播放态编辑器）整帧退出；
4. `ui_set` 只对 `_COLOR_FIELDS` 里的名字做 parse_color 重定向，而该表漏了
   `focus_bg_color / placeholder_color / cursor_color / list_bg / list_hover / bar_color`
   六个真实存在的颜色字段 —— 这些字段即使走 `ui_set` 也还是坏元组。

**改法**
- `_COLOR_FIELDS` 补齐上述 6 个字段（`agent_commands.py:187-195`）；
- 新增 `_coerce_color_args(args, cmd)`（`agent_commands.py:233-248`）：**在建立元素之前**把所有颜色字段统一过 `parse_color`，非法值直接 `{'error': ...}` 返回，绝不产生半成品元素；
- `cmd_ui_add`（`2106`）与 `cmd_ui_set`（`2260`）共用该入口，符合"统一 `_parse_color`、`ui_set` 同步复用"的裁决；
- `parse_color` 增加分量范围校验（0-255），`(300,0,0)` 这类"坏 tuple"同样报错（`226-229`）；
- 允许的输入 = `#RRGGBB` / `#RRGGBBAA` / `#RGB` / 无 `#` 前缀 / `[r,g,b]` / `(r,g,b)` / `(r,g,b,a)`。

**前后证据（实测）**

改前：
```
--- A) ui_add panel bg_color='#ff0000' ---
result: {'ok': True, 'result': {'name': 'panel_0', ...}}
elem.bg_color = ('#', 'f', 'f', '0', '0', '0', '0') len= 7
render FAILED: TypeError unsupported operand type(s) for /: 'str' and 'float'
```

改后：
```
bg_color = (255, 0, 0, 255)
#00ff0080 -> (0, 255, 0, 128)
toggle box_color='#123456' / check_color=(1,2,3) / label_color=[4,5,6,7]
  -> (18, 52, 86, 255) (1, 2, 3, 255) (4, 5, 6, 7)
ui_add panel bg_color='not-a-color' -> ok=False  "ui_add 字段 bg_color 非法: 颜色格式非法 ..."
ui_add panel bg_color=(1,2)        -> ok=False  "... 颜色数组需 3 或 4 项 ..."
ui_add panel bg_color=(300,0,0)    -> ok=False  "... 颜色分量越界 (需 0-255) ..."
input_field focus_bg_color='#112233' -> (17, 34, 51, 255)     # 原漏表字段
render: (1.0, 0.0, 0.0, 1.0)
```

**新增测试**：`tests/test_eai_color_parse.py`（合法 11 例 / 非法 18 例 / 12 种元素字段端到端 + 渲染桩 / 非法不留半成品 / ui_set 复用 / 布尔字符串语义）

---

## 2. [P1] 布尔参数字符串语义：`bool("false") == True`

**位置**：`agent_commands.py` `cmd_ui_add` 原 2051-2056（`visible`/`enabled`）、`take('is_on', bool)`、`take('show_bar', bool)`、`take('close', bool)`；`cmd_ui_set` 原 2196-2201 及同款三处

**根因**：命令参数来自 GUI 控制台字符串 / HTTP JSON，裸 `bool('false')` 为 `True`（本文件 159-161 行注释早已记录过同类事故，`as_bool` 就是为此而建，但 UI 命令没改用它）。

**改法**：全部改走 `as_bool` —— `ui_add` `visible/enabled`（`2127-2130`）、`is_on/show_bar/close`（`2170/2188/2228`）；`ui_set` `visible/enabled`（`2280-2283`）、`is_on/show_bar/close`（`2329/2345/2386`）。`ui_set` 的默认值取当前值（`as_bool(v, elem.visible)`），语义更稳。

**前后证据（实测）**

改前：
```
ui_add toggle is_on='false'   -> is_on = True
ui_add button visible='false' -> visible = True
ui_set button visible='false' -> changed {'visible': True}, visible = True
```
改后：
```
ui_add toggle is_on='false'   -> False
ui_add button visible='false', enabled='0' -> visible=False enabled=False
ui_set button visible='true', enabled='yes' -> changed {'visible': True, 'enabled': True}
```
`false/0/no/off/none/''` 全部判假；`true/1/yes/on` 判真（见新增测试）。

**新增测试**：`tests/test_eai_color_parse.py` 第 7 节（8 个假值 × 2 字段、6 个真值 × 2 字段、`is_on/show_bar/close`、`ui_set` 往返）

---

## 3. [P1] `object_select` 重名/越界 `index` 静默取第一个

**位置**：`agent_commands.py` `cmd_object_select`（现 551-582，原 507-513）

**根因**：`hits = [h for h in hits if h[2] == want] or hits` —— `or hits` 是兜底：
- 无 `index` 时直接选 `hits[0]`（只回一个 `ambiguous: True` 提示，动作已经发生了）；
- `index` 越界时兜底回全量 `hits`，**仍然选 `hits[0]`**；
- 只按序号过滤、不区分类型，`model#1` 与 `light#1` 会同时命中。
MCP 的 `unity_gameobject_delete` / `_duplicate` 正是"先 `object_select` 再动手"，
静默选错 = 删错/复制错对象，不可逆。

**改法**：重名一律拒绝，复用本文件既有的 `_Ambiguous` 契约（与 `prefab_unlink` 等同一条），错误串里列出全部候选 `kind#index`；`index` 必须精确命中唯一一个，否则同样拒绝。

**前后证据（实测，场景 `[dup, dup, solo]`）**

改前：
```
object_select {name:'dup'}           -> ok=True  {'selected':'dup','index':0,'ambiguous':True}  选中 idx 0
object_select {name:'dup',index:99}  -> ok=True  {'selected':'dup','index':0,'ambiguous':True}  选中 idx 0
```
改后：
```
object_select {name:'dup'}           -> ok=False "重名 'dup' (匹配 2 个, 需要 index= 指定序号, 先 run object_list 查看): ['model#0', 'model#1']"  选中 idx -1
object_select {name:'dup',index:99}  -> ok=False 同上  选中 idx -1
object_select {name:'dup',index:1}   -> ok=True  index 1
object_select {name:'solo'}          -> ok=True  index 2, ambiguous False
object_select {index:99}             -> ok=False 'index 越界: 99 (物体数 3)'   # 老契约不变
```

**新增测试**：`tests/test_eai_safety_guards.py` A 段（重名无 index / index 越界 / 跨类型同序号 / GUID 寻址 / 找不到），并保留 `tests/test_eai_real.py` 既有重名用例。

---

## 4. [P1] MCP `unity_script_write_file` 无写路径白名单

**位置**：`loom_mcp.py` `dispatch_tool` → `unity_script_write_file`（现 620-626，原 578-588）

**根因**：`full_path = os.path.join(scripts_dir, fname)` 直接用模型给的 `filename`：
- `'../../x.py'` → 写到工程外；
- 绝对路径（`C:/Windows/x.py`）→ `os.path.join` 丢弃前缀，直接落盘任意位置；
- 即使只做字符串前缀校验，`scripts/evil` 放一个 junction 指向别处也能绕过。
MCP 是给大模型用的接口，参数来自模型输出（可被提示词注入），必须当不可信输入。

**改法**
- 新增 `_safe_script_path(base_dir, fname)`（`loom_mcp.py:314-346`）：两层闸门
  1. `realpath` 归属：解析 junction/符号链接后必须真落在 `<工程>/scripts/` 内；
  2. 复用 EAI 白名单 `agent_commands._safe_write_path`（`agent_commands.py:131`），
     并把它自己的工程目录作为 `extra_roots` 传入（工程不在程序目录/用户目录/临时目录时
     不会被误杀）；白名单模块不可用时**失败关闭**（拒绝写入）。
- `_safe_write_path` 增加 realpath 前缀比较（`_realpath`，`agent_commands.py:119`），
  返回值仍是 `abspath`（既有验收依赖该字形，未改）。这样 `scene_save / asset_save /
  prefab_save / screenshot / quit save` 一并获得 junction 逃逸防护。

**前后证据（实测，工程 = 临时目录）**

改前：
```
B1 ../../escape_proof.py -> 脚本写入成功: ...\proj\scripts\../../escape_proof.py (8 bytes)  落地: True
B2 绝对路径            -> 脚本写入成功: C:\Users\...\Temp\abs_proof.py (8 bytes)
```
改后：
```
B1 player.lua           -> OK   ...\proj\scripts\player.lua (8 bytes)
B2 ../escape_proof.py   -> ERR 脚本路径越域: ... (必须落在 ...\proj\scripts 之内; 不接受 ../ 或脚本目录之外的绝对路径)
B3 ../../escape_proof.py-> ERR 同上
B4 绝对路径             -> ERR 同上
```

**新增测试**：`tests/test_eai_safety_guards.py` B 段（正常名 / `../` / `../../` / `a/../../../` / 绝对路径 / 非 .lua.py / junction 逃逸 / 目录内子目录）

---

## 5. [P1] Qt 编辑器 UI 输入全失效（`pressed/released` 在 UI 分发之前被清空）

**位置**：`ui/loom_gui.py` `LoomGUI._on_tick`（原 1307-1308 清空、1320 `_update_camera()`；现 1325 `_update_camera()`、1329-1330 清空）

**根因**：`pressed/released` 是 Qt 事件回调（`mousePressEvent/mouseReleaseEvent`）攒下的"本帧新按下/松开"；唯一消费者是 `editor._update_camera()` 第一行的 `_dispatch_ui_mouse()` → `loom_ui.UIManager.dispatch_mouse()`。原顺序在 `_update_camera()` **之前**清空，UI 树每帧拿到空集合 → HUD/面板上的按钮、滑条、输入框、下拉全部点不动。pygame 主线自己轮询鼠标，所以只有 Qt 版坏。

**改法**（按要求只改 `ui/loom_gui.py`）：把 `e.pressed.clear()` / `e.released.clear()` 移到 `e._update_camera()` 之后（UI 分发 + 相机输入都消费完），并留注释说明为什么不能提前。

**前后证据（源码顺序）**

改前：`e.pressed.clear()` @1307 → `e._update_camera()` @1320
改后：`e._update_camera()` @1325 → `e.pressed.clear()` @1329 / `e.released.clear()` @1330

**新增测试**：`tests/test_qt_tick_input_order.py`（源码级顺序守卫，不启动 Qt：断言两个 `clear()` 都晚于 `_update_camera()`、且 `editor._update_camera` 内部确实调 `_dispatch_ui_mouse`；回退旧顺序立刻 FAIL）

---

## 6. [P1] 多 Canvas 命中：顶层 root 吞掉一切（裁决 Q7=C 只吞空白）

**位置**：`loom_ui.py` `UIManager.hit_test`（原 417-426）；同规则的重复实现 `dispatch_mouse`（原 504-512）、`update_hover_only`（原 653-660）

**根因**：`hit_test` 从最上层 Canvas 往下测，"第一个非 None 就返回"。screen Canvas 的 root 铺满整屏，所以最上层 Canvas **永远**返回 root → 低一层 Canvas 上的按钮/列表/输入框永远点不到（也 hover 不到、滚轮滚不动）。

**改法**：新增 `UIManager._hit_screen(pos)`（`loom_ui.py:417-446`）实现 Q7=C：
1. 命中**子元素** → 立刻返回（上层优先，老行为不变）；
2. 只命中 root（空白）→ **继续下探**低层 Canvas；
3. 全部 Canvas 都没命中子元素 → 返回**最上层** root（吞空白，空白点击仍算 UI 消费，不漏到 3D 拾取/相机）。
`hit_test`（448）成为稳定入口；`dispatch_mouse`（533）、`update_hover_only`（674）改为共用它，避免三处各写一遍再漂移。

**前后证据（实测，同场景：顶层 z=10 只有角落面板，低层 z=0 有 (100,100,60,30) 按钮）**

```
pos=(120, 110)  改前=(z=10, root)   改后=(z=0, btn_low)     # 低层按钮从"永远点不到"变成可点
pos=(10, 10)    改前=(z=10, hud_bg) 改后=(z=10, hud_bg)     # 顶层子元素优先不变
pos=(190, 190)  改前=(z=10, root)   改后=(z=10, root)       # 空白仍吞
```
端到端：修复前 `dispatch_mouse` 在低层按钮上按下/松开 `on_click` 永不触发；修复后 `clicks == ['low']`。

**新增测试**：`tests/test_ui_multi_canvas_hit.py`（19 条断言：空白吞 / 子元素优先 / 低层可命中 / world Canvas 跳过 / 空管理器 / 低层按钮真点击 / 顶层仍最先响应 / hover 同规则 / 低层 ScrollView 滚轮 / 单 Canvas 老行为回归）

---

## 7. [P2] `event_bindings` 无撤销 / 材质库 undo 不配对

按要求**不动**（属 12 号批次）。

---

## 8. 收尾追加 ①：`RemoteViewport._tick` 与 `GLViewport` 对齐

**位置**：`ui/loom_gui.py` `RemoteViewport._tick`（现 579-592，插在 `self._fbo.use()` 之后）

**根因**：远程/虚拟显示走的 `RemoteViewport` 只做"渲染 + 回读 + 显示"，整条输入链缺两段：
1. 从不调用 `e._update_camera()` —— 而 UI 树分发 (`editor._dispatch_ui_mouse`) 就在它第一行，
   所以远程模式下相机（WASD/右键转视角/滚轮推拉）和 HUD 按钮/滑条/输入框全部无响应；
2. 从不清 `e.pressed` / `e.released` —— 这两个集合只增不减，按下一次鼠标后
   `pressed` 永远非空，等于永久"按下态"。

**改法**：按 `_on_tick` 的逐行顺序补齐输入段：
`QCursor` 同步 mouse_pos → `e._update_camera()`（内部先分发 UI）→ `e.mouse_wheel = 0`
→ `e.pressed.clear()` / `e.released.clear()`，位置在 `advance_logic`/`render` 之前
（与 GL 路径"帧首采输入、再逻辑、再渲染"一致）。

**前后证据**：改前 `_tick` 内 `_update_camera` / `pressed.clear` / `released.clear` 出现次数 = 0；
改后 = 1/1/1，且顺序为 `_update_camera` → clear。Qt 远程模式需要真实显示器，
本机无法无头启动，故用源码级守卫锁定（`tests/test_qt_tick_input_order.py` 新增 6 条断言）。

## 9. 收尾追加 ②：`ui_add` 的 `rect/anchor/pivot` 仍裸 `tuple()`

**位置**：`agent_commands.py` `cmd_ui_add` 原 2161-2166 / `cmd_ui_set` 同款；新增
`_VEC_FIELDS` / `_as_vec` / `_coerce_vec_args`（现 252-292）

**根因**：与颜色字段同一类坏输入。`tuple('0,0,120,40')` → 字符元组（10 项），
`tuple('0100')` → 4 个字符；`loom_ui` 的 `rect/anchor/pivot` setter 是
`try: float(...) except: return` —— **静默丢弃**，于是命令回 `ok=True` 但元素尺寸/锚点
根本没变（"命令成功但界面没反应"）。

**改法**：`_as_vec(v, n, field, cmd)` 统一规整：字符串按逗号/空白切分（方便控制台
`rect=0,0,100,20`）、数组原样；项数不符 / 非数值 / NaN·Inf 一律 `ValueError`；
`_coerce_vec_args` 与 `_coerce_color_args` 同款（返回新 dict、调用方转 `{'error':...}`），
在 `ui_add`/`ui_set` 的同一 try 块里串联调用 —— 非法输入在任何字段被改动、任何元素被创建之前返回。

**前后证据（实测）**
```
改前 (复刻旧写法 tuple(str) 实测):
  rect='0,0,120,40' -> tuple() 得 10 个字符 -> loom_ui setter 解包失败且不赋 _rect
                     -> 元素 .rect 首次访问 AttributeError (布局/渲染帧崩)
  rect='0100'       -> ('0','1','0','0') -> rect=(0.0,1.0,0.0,0.0)   # 静默错几何
  ui_set rect='10,20,30,40' -> 11 项 -> setter 静默丢弃 -> ok=True 但字段没变
改后:
  ui_add rect='0,0,120,40'  -> ok=True, elem.rect=(0.0,0.0,120.0,40.0)
  ui_add anchor='0.5 0.5' / pivot=(0,1) -> anchor=(0.5,0.5) pivot=(0.0,1.0)
  ui_add rect='0100'        -> ok=False  "ui_add 字段 rect 需要 4 个数 (收到 1 项)"
  ui_add rect=[1,2]         -> ok=False  "... 需要 4 个数 (收到 2 项)"
  ui_add rect='a,b,c,d'     -> ok=False  "... 含非数值项"
  ui_add rect=[1,2,nan,4]   -> ok=False  "... 含 NaN/Inf"
  ui_add rect=123           -> ok=False  "... 需要数组或逗号分隔数字"
  ui_set rect='10,20,30,40' -> ok=True,  elem.rect=(10.0,20.0,30.0,40.0)
  ui_set rect='1,2,3'       -> ok=False, 字段不变
```

## 10. 收尾追加 ③：`run_stdio_server` 未包 try/except（工具异常打死 MCP 进程）

**位置**：`loom_mcp.py` `run_stdio_server`（现 947-980）

**根因**：`res = server.handle_request(req)` 没有保护。任何工具抛异常（例如
`unity_script_write_file` 写不存在的子目录 → `FileNotFoundError`）都会穿透 stdio 循环，
整个 MCP 服务进程退出 —— 客户端整条链路掉线，只能重启；而这类异常往往只是单条命令的参数问题。

**改法**：包一层 `try/except`，异常时向 stderr 打一行诊断，并回一条 JSON-RPC error
（`code -32603`，`id` 对齐请求；请求不是 dict 时 id=None），循环继续处理后续请求。

**前后证据（实测，桩服务第一条请求抛 `RuntimeError('kaboom')`）**
```
改前: 异常穿透 -> run_stdio_server 抛出, 进程结束, 后续请求无人处理
改后: [{"jsonrpc":"2.0","id":1,"error":{"code":-32603,"message":"tool error: RuntimeError('kaboom')"}},
       {"jsonrpc":"2.0","id":2,"result":{"ok":true}}]        # 两条响应, 进程存活
```

---

## 11. 追加（用户 Q3）：Qt 编辑器删除父物体无确认提示

**位置**：`ui/loom_gui.py` —— `attach()`（972-979）、新增 `_inject_delete_confirm()`（981-989）、
`bind_editor()`（991-997）、删除入口 `_cmd_del()`（2029-2038）、新增 `_ask_delete_confirm()`（3813-3838）

**根因**：F8 在 `editor.py` 加了钩子 `self._confirm_delete_callback = None`（`(model, n_children) -> bool`，
`delete_object()` 在 `n_children > 0` 时调用，返回 False 就不删），但 **Qt 编辑器从未注入它** ——
`getattr` 拿到 None，于是 Qt 里删一个带子物体的父物体 = **静默连整棵子树删掉**，没有任何提示。

**改法**
1. `LoomGUI._ask_delete_confirm(model, n_children)`：`QMessageBox.question`，
   N>0 → 「该物体有 N 个子物体，删除将一并删除，是否继续？」；N=0 → 「确定删除该物体？」；
   标题带物体名；**默认按钮 = 否**（误按 Enter 不会删子树），关窗/Esc 都按否处理；
   弹框本身异常 → 返回 True（保持旧行为，不阻断删除）。
2. 注入点三处（幂等）：`attach()`（契约口）、`bind_editor()`、删除入口 `_cmd_del()`。

**踩到的顺序陷阱（重要）**：`editor.py` 里 `view.attach(self)` 在 **:140**，而
`self._confirm_delete_callback = None` 在 **:158** —— 只在 `attach()` 里注入会被 `__init__`
随后覆盖成 None，功能等于没做。真正生效的是 `bind_editor()`（`__init__` 返回后宿主调用，
`ui/loom_gui.py:172` / `:546`）与 `_cmd_del()` 的幂等重挂。已在测试里复现并锁住。

**前后证据（实测）**
```
改前: editor._confirm_delete_callback = None (Qt 从不注入)
      删除父物体 P (有 1 个子物体) -> 直接连子树删, 无任何弹窗
改后: N=1 -> 弹「该物体有 1 个子物体，删除将一并删除，是否继续？」
      选否 -> models 仍是 ['P','C'] (没删); 选是 -> models == [] (连子树删, 可撤销)
      N=3 -> 「该物体有 3 个子物体，…」; N=0 直接调回调 -> 「确定删除该物体？」
      复现顺序陷阱: attach 注入 -> 置 None -> bind_editor 重挂 -> 钩子可调用
```

**注**：`docs/audit/fix_08_core_editor.md` 落盘时不存在，本项按 `editor.py` 里的**实际实现**对齐
（签名 `(model, n_children) -> bool`、仅在 N>0 时回调）。因此 N=0 的普通删除确认分支虽然已实现并
单测，但从 UI 删无子物体对象时**不会弹框**（editor 的 `if n_children > 0` 门槛决定）；若要求每次删除都
确认，需在 `editor.py` 去掉该门槛（不在本批次范围，未动）。

---

## 验收数字（改前 → 改后）

| 项目 | 改前 | 改后 |
|---|---|---|
| `python tests/_tmp/ab_batch.py` | 22 场景全 PASS，失败 0（MAE 最大 0.000082） | **22 场景全 PASS，失败 0（逐场景 MAE 与改前完全一致）** |
| `python tests/_tmp/ab_gl_vk_ui.py` | GL(UI) vs VK(UI) MAE=0.00000009，MAX=0.003922 | **MAE=0.00000009，MAX=0.003922（未变；本批次不改渲染）** |
| `python tests/test_ui.py` | ALL PASS | **ALL PASS** |
| `python tests/test_editor_ui.py` | ALL PASS | **ALL PASS** |
| `python tests/test_eai_real.py` | ALL PASS（91 条命令全覆盖） | **ALL PASS（91 条命令全覆盖）** |
| `python tests/test_hub_eai.py` | ALL PASS（18 条） | **ALL PASS（18 条）** |
| `python tests/test_agent_commands.py` | ALL PASS | **ALL PASS**（白名单用例全绿） |
| `python tests/test_vk_ui_input.py` | exit=0 | **exit=0** |
| `python tests/test_eai_color_parse.py` | （新增） | **ALL PASS** |
| `python tests/test_ui_multi_canvas_hit.py` | （新增） | **ALL PASS** |
| `python tests/test_qt_tick_input_order.py` | （新增） | **ALL PASS** |
| `python tests/run_all.py` | （改前未跑） | **exit=0，`全部测试完成 ✅`，无 FAIL 行（含 5 个新增测试文件；§8-§10 与 §11 改完后各完整跑过一次，均全绿）** |

## 新增回归测试（`run_all.py` 自动收集，命名 `tests/test_*.py`）

1. `tests/test_eai_color_parse.py` —— 颜色解析（合法 11 例 / 非法 18 例）+ `_COLOR_FIELDS` 覆盖 + 12 种元素颜色字段端到端（含渲染桩，证明不再 TypeError）+ 非法颜色不留半成品 + `ui_set` 复用 + 布尔字符串语义（8 假值 / 6 真值 / `is_on`/`show_bar`/`close`）。
2. `tests/test_ui_multi_canvas_hit.py` —— Q7=C 语义（19 条：空白吞、子元素优先、低层可命中、world Canvas 跳过、低层按钮真点击、顶层仍最先响应、hover 同规则、低层 ScrollView 滚轮、单 Canvas 老行为回归）。
3. `tests/test_qt_tick_input_order.py` —— `ui/loom_gui.py` 两条 tick 路径的输入顺序守卫（源码级，无需 Qt）：`LoomGUI._on_tick` 的 `pressed/released` 清空必须晚于 `_update_camera()`；`RemoteViewport._tick` 必须调 `_update_camera()` 且在其后清 `pressed/released`、清 `mouse_wheel`；并锁住 `editor._update_camera → _dispatch_ui_mouse` 这条依赖。
4. `tests/test_qt_delete_confirm.py` —— Q3 删除确认（Qt offscreen + monkeypatch `QMessageBox`）：`attach` 注入钩子、N=1/N=3 文案含子物体数、取消不删、确认才删（连子树）、默认按钮=否、N=0 文案、弹框异常兜底、**顺序陷阱复现**（attach 注入被 `__init__` 覆盖 → `bind_editor`/`_cmd_del` 重挂生效）。
5. `tests/test_eai_safety_guards.py` —— A) `object_select` 歧义/越界拒绝（含跨类型同序号、GUID 寻址）；B) MCP 脚本写路径白名单（`../`、绝对路径、junction/symlink 逃逸、非 .lua/.py）；C) `rect/anchor/pivot` 字符串/数组/项数/非数值/NaN 全路径（含"元素必须真有 `_rect`"）；D) `run_stdio_server` 异常不打死进程（桩服务第一条请求抛异常，断言两条响应且进程继续）。

## 遗留 / 发现但未动的问题（按要求只记录）

1. **Qt 编辑器 3D 点选/gizmo 仍然拿不到本帧点击**：`editor.render()` 末尾的 `_update_gizmo()` 也读 `self.pressed`，而 `render` 由 `paintGL` 在 `_on_tick` 返回后执行，此时 `pressed` 已清。要彻底修需要把清空点挪到 `paintGL` 末尾（或给"已消费"打代际标记），属 `editor.py`/`loom_gui.paintGL` 的另一处改动，**不在本批次范围**，未动。远程模式（`RemoteViewport`）本轮已补输入段，但同一条 `_update_gizmo` 依赖同样受此限制。
2. `tests/_tmp/smoke_p0_6_p1_3_p1_5.py` 里对 `_COLOR_FIELDS` 重定向写法的源码断言仍成立（该行未删），但它属于 `_tmp` 探针、不在 `run_all` 收集范围。
3. `ui_add` 的 `rect/anchor/pivot` 现在只做"合法数值"校验，不做范围钳制（`anchor/pivot` 仍由 `loom_ui` setter 钳到 0-1，`rect` 宽高由 setter 钳到 >=0）—— 语义未变，只是非法输入改为报错。

> 收尾追加（§8/§9/§10）已并入本轮；`RemoteViewport` 与 `run_stdio_server` 两项因为需要真实 Qt 显示器 / 真实 stdio 会话，行为验证用源码级守卫 + 桩服务完成。
