# EAI 命令 / MCP / 窗口与输入 扫描报告（scan_07_eai）

> 审计对象：`agent_commands.py` / `loom_mcp.py` / `loom_glfw_window.py` / `loom_input.py`
> 审计方式：只读（未修改任何受跟踪源码/测试/文档）；定向探针放 %TEMP%\eai_audit，设 LOOM_NO_SAVE_MIGRATE=1。
> 审计日期：2026-11-07　执行者：模块子代理（只读审计员）

## 0. 范围与方法

### 0.1 文件清单（read 全文，逐行）

| 文件 | 行数 | 本轮 diff | 说明 |
|---|---|---|---|
| `agent_commands.py` | 2958 | -6 行 | 删除一处重复 `@command('scripts')` |
| `loom_mcp.py` | 938 | 无改动 | MCP stdio 服务 + TOOLS/RESOURCES/PROMPTS |
| `loom_glfw_window.py` | 598 | +31/-9 行 | `_set_fullscreen` 新增"无 GLFW 窗口"分支（代码注释自称 P-07 修复） |
| `loom_input.py` | 223 | 无改动 | `_KEYMAP` / 动作层 / 鼠标锁定 / 脚本键刷新 |

`git diff HEAD` 的实测范围：

```
$ git --no-pager diff HEAD --stat -- agent_commands.py loom_glfw_window.py loom_mcp.py loom_input.py
 Loom/agent_commands.py   |  6 ------
 Loom/loom_glfw_window.py | 31 ++++++++++++++++++++++++++++---
 2 files changed, 28 insertions(+), 9 deletions(-)
```

结论：本轮"Vulkan 对齐"未改 `loom_mcp.py` 与 `loom_input.py`；两个改动文件见 §2 的 P-01/P-18/P-19。

### 0.2 跑过的命令（可复跑）

```
# 1) 命令注册表 / 工具面 / 异常隔离 / 写路径（纯无头）
python %TEMP%\eai_audit\probeA.py     # P-02..P-08、P-11..P-15、P-18
python %TEMP%\eai_audit\probeC.py     # object_select 歧义（P-05）
python %TEMP%\eai_audit\probeD.py     # MCP 未捕获异常（P-12）、通知响应（P-13）
python %TEMP%\eai_audit\probeE.py     # 键名映射完备性（P-22..P-24）
# 2) 输入链路 + 真实 GLFW 隐藏窗口回调（VISIBLE=FALSE）
python %TEMP%\eai_audit\probeB2.py    # P-20、P-21
# 3) 定向既有测试（未跑 tests/run_all.py）
python tests/test_fullscreen.py       # ALL PASS (exit=0)
python tests/test_agent_commands.py   # ALL PASS (exit=0)
```

### 0.3 工作树自查

运行前后 `git status --porcelain` 各 1088 行，`Compare-Object` 无差异（探针不改仓库文件；测试自清理），未需要 `git checkout --` 还原任何文件。
注：工作树中 `tests/_tmp/*` 的 `D` 条目是审计开始前已存在的他人改动，未触碰。

### 0.4 判定基准（只引用被审对象自身契约）

- `agent_commands.py:135-137`：命令参数可能是字符串，必须走 `as_bool`（"裸 bool('false') == True —— 曾让 play on=false 反而开始播放"）。
- `agent_commands.py:210-216`：`@command` 是命令注册装饰器；`223-229`：未知命令报错；`246-248`：命令异常不得崩进程。
- `agent_commands.py:83-132`：写路径白名单（程序目录/场景目录/用户目录），"Agent（含提示词注入）发出的写文件命令只能落这些根之下"。
- `agent_commands.py:445`："场景里重名是允许的（复制/Prefab 实例常见），命令层必须知道有没有歧义"；`819-821`：歧义必须拒绝并给 index=。
- `engine.py:199-201`：`window_size` 是"窗口模式尺寸（F11 全屏恢复用）"；`engine.py:265`："外部模式: 无 pygame 窗口（Qt 宿主管窗口）"。
- `loom_input.py:107-112`：`sync_script_keys` 契约 = "由引擎渲染帧头调用，与 pygame 路径每帧刷新同语义"。
- `tests/test_fullscreen.py:14`："window_size 在全屏期间不被覆盖（退出时要还原的对象）"。
- `loom_mcp.py:2-8`：MCP = JSON-RPC 2.0 标准协议通道；`90`："85 个 EAI 命令始终可用"。

## 1. 粗筛清单（含跳过项留痕）

| ID | 位置 | 标签 | 初步方向 |
|---|---|---|---|
| P-01 | agent_commands.py:1414 区域（diff 删除点） | SEM-MISMATCH | 删除重复注册是否改变最终 handler |
| P-02 | agent_commands.py:210-216 | AUDIT-DEADCODE | 注册表无唯一性守卫，后注册静默覆盖 |
| P-03 | agent_commands.py:2051-2054 / 2196-2201 / 2095 / 2113 / 2153 | SEM-MISMATCH | 字符串 "false" 被 bool() 判真 |
| P-04 | agent_commands.py:2062-2064 对照 2210-2212 | BND-EMPTY（类型边界） | 字符串颜色被 tuple() 拆成 7 个字符 |
| P-05 | agent_commands.py:510-512 | AUDIT-ASYMMETRY | 越界/歧义 index 被 or hits 静默吞掉 |
| P-06 | agent_commands.py:304,313 | AUDIT-DEADCODE | delay 重复赋值 |
| P-07 | agent_commands.py:1897,2615 | AUDIT-DEADCODE | _find_model_by_name 重复定义 |
| P-08 | loom_mcp.py:90 与实测 91；docs/guides 说 "24 项 Tools" 与实测 72 | AUDIT-DOCIMPL | 文档数字与实现漂移 |
| P-09 | agent_commands.py:126-130 | TOOL-SCOPE | 白名单仅字符串前缀，junction/短名未覆盖 |
| P-10 | loom_input.py:173-186 | SEM-SILENT | 坏配置文件静默回退默认（是否违约） |
| P-11 | loom_mcp.py:578-588 | TOOL-WHITELIST | MCP 写脚本无白名单，../ 与绝对路径可逃逸 |
| P-12 | loom_mcp.py:907-916 / 365-881 | IFACE-ERROR | dispatch_tool 无异常隔离，畸形参数杀 stdio 进程 |
| P-13 | loom_mcp.py:315-340 | AUDIT-ASYMMETRY | 通知（无 id）收到 error 响应 |
| P-14 | loom_mcp.py:463-468 对照 agent_commands.py:1572-1603 | IFACE-PRECOND | keep_world 被 EAI 静默忽略 |
| P-15 | loom_mcp.py:96 对照 editor.py:669-672 | IFACE-PRECOND | primitive 枚举含 'none'，引擎必 KeyError |
| P-16 | loom_mcp.py:87-299 vs 365-881 | TOOL-SCOPE | 工具/分支/EAI 命令三方覆盖是否闭合 |
| P-17 | loom_mcp.py:909-916 | IFACE-VERSION | 非法 JSON 行静默丢弃（无 -32700） |
| P-18 | loom_glfw_window.py:207-224（diff 新增） | **[REGRESSION]** SEM-MISMATCH | 外部模式把 width/height/viewport 改成桌面分辨率，宿主 FBO 不变，且不 resize UI |
| P-19 | loom_glfw_window.py:200-206（diff 新增注释） | **[REGRESSION]** AUDIT-DOCIMPL | 注释称"F11 一按即崩（玩家发布路径默认就是这个模式）"，需验证可达性 |
| P-20 | loom_glfw_window.py:234-243 + 568-575 | IFACE-PARTIAL | 全屏退出用被回调覆盖的 window_size 恢复 |
| P-21 | loom_input.py:75-100/107-116 + loom_glfw_window.py:276-279 | SEM-SILENT | 外部模式（Qt 玩家窗口）script_keys 永不刷新 |
| P-22 | loom_input.py:44-62 与 203-221 | AUDIT-DEADCODE | KEY_BINDINGS 定义两次 |
| P-23 | loom_input.py:31-39 与 44-62 | AUDIT-ASYMMETRY | 'e' 同时是相机下移与"交互"动作键 |
| P-24 | loom_input.py:22 / loom_glfw_window.py:62-67 | AUDIT-ASYMMETRY | 右 Shift/右 Ctrl 有 GLFW 映射但无键名 |

### 跳过登记（必须留痕）

| 跳过项 | 位置 | 跳过理由（四类之一） |
|---|---|---|
| S-01 | agent_commands.py:2106-2114 grid_layout 的 columns | 已有回归测试覆盖：tests/test_ui.py 覆盖 grid 绘制；本模块只做参数搬运 |
| S-02 | agent_commands.py:2868-2871 Content-Length 无上限 | 白盒契约明确声明：EAI 仅 bind 127.0.0.1 + 令牌（agent_commands.py:13-21, 2903），未声明请求体上限 |
| S-03 | agent_commands.py:2782-2790 token 落盘权限 | 白盒契约明确声明：.agent_port.json 就是本地令牌传递机制（13-15 行），文件权限非本模块承诺 |
| S-04 | agent_commands.py:2797 log_message 空实现 | 白盒契约明确声明："静默 request 日志进 LOG_RING"（行内注释即契约） |
| S-05 | agent_commands.py:368 win.grab() 依赖 Qt | 白盒契约明确声明：full=true 抓整窗（命令描述）；无 Qt 即报错，不静默 |
| S-06 | loom_mcp.py:845-866 registry.json 缺失分支 | 语言规范保证：exists 检查在前；缺失返回 _err，非静默 |
| S-07 | 未跑 tests/run_all.py / 未启动 GUI | 任务硬约束（模块派发指令），协议 §0.5 禁止阻塞式 GUI |
## 2. 逐项裁决

> 每条链按 8 段式（位置/契约/路径/实际/差异/触发/验证/影响）。探针源码见附录 A。

---

### P-01 · `@command('scripts')` 重复注册被删除 —— **P-DISPROVED**

1. 位置：`agent_commands.py:1414-1460`（diff 删除第一份 `cmd_scripts`）。
2. 契约：`@command` 把 `_COMMANDS[name] = fn`（210-216 行）；同名后写覆盖先写。
3. 路径枚举：
   - 路径 1：HEAD 上第一次 `@command('scripts')` 注册 fn1 → `_COMMANDS['scripts']=fn1`；
   - 路径 2：随后 `def cmd_scripts` 重新绑定模块名，第二次装饰器注册 fn2 → `_COMMANDS['scripts']=fn2`；
   - 路径 3：删除 fn1 后只剩 fn2 → `_COMMANDS['scripts']=fn2`；
   - 无第三条注册、无延迟导入、无 `__all__` 影响。
4. 实际：三条路径最终值都是 fn2（按源序执行）。
5. 差异：无。被删的 fn1 在 HEAD 上从未被调用（模块名与注册表都被第二个 def 覆盖）。
6. 触发：任何 `scripts` 调用。
7. 验证：
   ```
$ git show HEAD:Loom/agent_commands.py | Select-String "command\('scripts'|def cmd_scripts"
> @command('scripts', '可用脚本清单 (script_add 的 sid 取这里)')
> def cmd_scripts(win, args):
> @command('scripts', '列出所有已注册的游戏脚本 (id + 名称 + 参数)')
> def cmd_scripts(win, args):
   ```
8. 影响与等级：无行为变化（删除正确）；真正缺陷见 P-02。

---

### P-02 · 命令注册表无唯一性守卫 —— **P-PROVED（P3）**

1. 位置：`agent_commands.py:210-216`。
2. 契约：`_COMMANDS` 是"命令名 -> fn"的唯一映射（47 行），命令表 = GUI 功能清单（25-26 行）。
3. 路径枚举：装饰器被调用 N 次、同名 M 次 → 只有赋值，无重复检测/告警/断言。
4. 实际：同名注册静默覆盖，先注册者永久不可达。
5. 差异：契约要求"命令表=GUI 功能清单"（一一对应），实现允许 1:N 覆盖且无信号；HEAD 上已真实发生一次（P-01）。
6. 触发：任何新增同名 `@command`。
7. 验证（探针 A）：
   ```
[A2] duplicate registry silently overwrites:
     _COMMANDS[__probe_dup__]() -> second (no exception, no warning)
[A1] _COMMANDS count = 91  unique = 91
   ```
8. 影响：当前 91 条全部唯一，无现存功能错误；下一次同名注册不会报错（P3）。建议方向：注册时检测重复并 WARN；测试断言命令名集合大小等于注册条数。

---

### P-03 · UI 命令的布尔字符串绕过 as_bool —— **P-PROVED（P1）**

1. 位置：`agent_commands.py:2051-2056`（ui_add 的 visible/enabled）、`2095/2113/2153`（is_on/show_bar/close）、`2196-2201/2246-2262/2303`（ui_set 同名字段）。
2. 契约：`135-137 行` 明文"命令参数一律可能是字符串…裸 bool('false') == True —— 曾让 play on=false 反而开始播放"；`140-148 as_bool` 是"命令层统一入口"。
3. 路径枚举：
   - 路径 1（HTTP JSON 真布尔）：`bool(False)` → False，正确；
   - 路径 2（控制台/字符串 "false"）：`bool('false')` → True，错误；
   - 路径 3（"0"/"off"）：`bool('0')` → True，错误；
   - 路径 4（缺省）：不进分支。
4. 实际：ui_add / ui_set / toggle 专用字段全部用 `bool()`，未用 `as_bool()`。
5. 差异：契约要求 "false"→False，实现返回 True。
6. 触发：控制台 `ui_set name=tg visible=false`，或 MCP `loom_ui_set` 直接透传 args。
7. 验证（探针 A）：
   ```
[B4] ui_add toggle visible="false" is_on="false" -> visible=True is_on=True
[B5] ui_set visible="false" is_on="false" -> visible=True is_on=True changed={"visible": true, "is_on": true}
[B6] as_bool("false") = False  / bool("false") = True
   ```
8. 影响：显隐/启用/开关/闭合全部反语义（P1 功能错误，不崩）。建议方向：统一 as_bool，并把该探针转成回归用例。

---

### P-04 · ui_add 颜色字符串被拆成 7 元素 tuple → 渲染帧抛 TypeError —— **P-PROVED（P0：崩溃）**

1. 位置：`agent_commands.py:2062-2064`（`take('bg_color', tuple)`）及其余颜色字段；对照 `2210-2212`（ui_set 对 `_COLOR_FIELDS` 强制 `parse_color`，"防字符数组 bug"）。
2. 契约：`agent_commands.py:2210-2211` 与 `_COLOR_FIELDS`（159-165） 声明颜色字段接受字符串；`loom_ui.py:846` 声明 `bg_color=(r,g,b) 或 (r,g,b,a) 0~255`；`loom_hud.py:214-217` 声明 `color=(r,g,b/a) 0..255`。
3. 路径枚举：
   - 路径 1：`[r,g,b]` 数组 → `tuple` → 正确；
   - 路径 2：`'#RRGGBB'` 字符串 → `tuple('#FF0000')` = 7 个字符 → 错误；
   - 路径 3：`'#RGB'` → 4 字符 tuple → 错误（3 位被当成 a 通道）；
   - 路径 4：缺省 → 默认值，正确。
4. 实际：`Panel.bg_color = ('#','F','F','0','0','0','0')`；绘制时 `loom_hud.py:220` 执行 `color[3] / 255.0` → `'F' / 255.0` → TypeError。
5. 差异：契约（字符串颜色合法）vs 实现（接受并存入非法类型）；错误被推迟到渲染帧。
6. 触发：`ui_add` 任一颜色字段传字符串（控制台 `bg_color=#FF0000`、MCP `loom_ui_add` 透传）。
7. 验证（探针 A）：
   ```
[B1] ui_add panel bg_color="#FF0000" -> {"ok": true, "result": {... "name": "panel_0" ...}}
[B2] stored bg_color = ('#', 'F', 'F', '0', '0', '0', '0') len = 7
[B3] bg_color[3]/255.0 raises: TypeError("unsupported operand type(s) for /: 'str' and 'float'")
   ```
   叠加证据：`loom_render.py:795-798` 的 `self.ui.draw_all(self)` 无 try；`loom_render.py:813-835 run()` 的 while 循环对 `self.render()` 无 try → GLFW 播放器进程直接退出；外部模式 Qt paintGL 每帧抛错。
8. 影响：P0（命令被接受 → 后续渲染崩溃；播放器进程退出 / 编辑器每帧异常）。建议方向：ui_add 颜色字段与 ui_set 共用 parse_color + `_COLOR_FIELDS`，非法值在命令层报错。

---

### P-05 · object_select 歧义/越界 index 静默取第一个，与 _resolve 契约相反 —— **P-PROVED（P1）**

1. 位置：`agent_commands.py:510-512`。
2. 契约：`445 行`（重名必须让命令层知道）、`819-821`（歧义 → 拒绝并给 index="命令层对上错对象比报错更糟"）。
3. 路径枚举：
   - 路径 1：无重名 → hits 长度 1，正常；
   - 路径 2：重名 + index 命中 → 过滤，正常；
   - 路径 3：重名 + index 越界 → `[...] or hits` 回退全量，取 hits[0]；
   - 路径 4：重名 + 无 index → 取 hits[0]，返回 `ambiguous: true` 但仍 `ok:true`；
   - 路径 5：无重名 + index 越界 → `len(hits)>1` 为假，根本不看 index，直接用 hits[0]。
4. 实际：越界 index 被静默忽略；歧义时仍返回 ok 并选中第一个。
5. 差异：`_resolve`（所有写命令共用）对同一输入抛 `_Ambiguous`；object_select 静默成功。
6. 触发：两个同名物体（Prefab 实例/复制），MCP `unity_gameobject_delete` / `unity_gameobject_duplicate`（loom_mcp.py:447-461）先 select 再执行 → 删/复制第一个同名对象。
7. 验证（探针 C）：
   ```
[I1] object_select name=同名 index=99 -> {"ok": true, "result": {"selected": "同名", "kind": "model", "index": 0, "ambiguous": true}}
[I2] 选中了 index = 0 (越界 index 被静默忽略, 不是报错)
[I4] _resolve 重名无 index 抛 _Ambiguous: 重名 '同名' (匹配 2 个, 需要 index= 指定序号…)
   ```
8. 影响：P1（销毁/复制错对象，返回值无法区分）。建议方向：去掉 `or hits`，越界与歧义都返回 error（与 _resolve 同语义）。

---

### P-06 · cmd_quit 重复赋值 delay —— **P-PROVED（P3）**

1. 位置：`agent_commands.py:304` 与 `313`。
2. 契约：304 行注释表明 after 只应决定延时关窗一次。
3. 路径枚举：两行之间只插入 `_suppress_confirm` 赋值（308-312），无副作用；两行表达式完全相同。
4. 实际：第二次赋值覆盖同值，无行为差异。
5. 差异：无行为差异；属死代码/重复逻辑。
6. 触发：任何 quit。
7. 验证：read `agent_commands.py:304,313`（两次 `as_float(args.get('after', 0.15), 0.15)`）。
8. 影响：P3（若将来只改一处会埋雷）。

---

### P-07 · _find_model_by_name 重复定义 —— **P-PROVED（P3）**

1. 位置：`1897-1904` 与 `2615-2619`。
2. 契约：模块内单一事实；UI Canvas world target 与 raycast ignore 共用。
3. 路径枚举：导入时第二次 def 覆盖第一次；两处调用点（1970/2020/2553）都在覆盖之后。
4. 实际：生效的是 2615 版本（多 `or []` 空值保护），1897 版本不可达。
5. 差异：行为等价，但"改一处不生效"。
6. 触发：修改 1897 版本的人。
7. 验证：`grep -n "def _find_model_by_name" agent_commands.py` → 1897、2615。
8. 影响：P3。建议方向：保留 2615，删除 1897。

---

### P-08 · 命令/工具数量文档漂移 —— **P-PROVED（P3）**

1. 位置：`loom_mcp.py:90`（"85 个 EAI 命令"）、`docs/guides/Loom_MCP协议接入…md:14,66`（"24 项 Tools"）。
2. 契约：注释/文档数字是对 Agent 的容量承诺。
3. 路径枚举：`_COMMANDS` 构建路径唯一（装饰器）；`TOOLS_DEF` 是静态列表。
4. 实际：91 条命令、72 个工具。
5. 差异：85≠91，24≠72。
6. 触发：Agent 依文档推断能力边界。
7. 验证（探针 A）：
   ```
[A1] _COMMANDS count = 91
[A3] loom_mcp.py 注释声称的 EAI 命令数: ['85']
[C1] TOOLS_DEF count = 72 unique = 72
   ```
8. 影响：P3（误导，不崩溃）。建议方向：数字从常量派生。

---

### P-09 · 写路径白名单只做字符串前缀（junction/短名/大小写未覆盖） —— **P-UNKNOWN**

1. 位置：`agent_commands.py:119-132`。
2. 契约：83-86 行"写文件命令只能落这些根之下"（安全边界）。
3. 路径枚举：`abspath(normpath)` 消除 `..`；随后 `startswith(root + sep)`。已枚举：`..` 逃逸（被 normpath 消掉）、根本身（拒绝）、大小写差异（误拒，方向安全）、8.3 短名（误拒，方向安全）。
4. 实际：未见字符串级"允许根外路径"。
5. 差异：未验证 NTFS junction/symlink——白名单根内若存在指向根外的 junction，前缀判定会放行、物理落点在外。
6. 触发：需预先存在 junction（mklink /J）。
7. 验证：未做。已尝试：静态枚举 + 既有测试三条白名单用例全 PASS（仅覆盖字符串路径）。
8. 影响：P-UNKNOWN（安全边界）。需要的信息：是否为该函数增加 realpath 归一化。建议探针：临时目录建 junction → 指向根外 → 调 _safe_write_path 看是否放行（≤3 次）。

---

### P-10 · _load_action_bindings 坏文件静默回退默认 —— **P-DISPROVED**

1. 位置：`loom_input.py:173-186`。
2. 契约：docstring 明写"坏文件回退默认"（175 行）。
3. 路径枚举：文件缺失 / JSON 坏 / 结构不对 / `actions` 为空 → 全部 `except` → 默认；结构合法 → 合并默认补新动作（183-184）。
4. 实际：与 docstring 完全一致，无"部分绑定被吞"的半成功。
5. 差异：无。
6. 触发：无（契约即如此）。
7. 验证：read `loom_input.py:173-186`；`tests/test_scripts.py:171-187` 覆盖改键语义。
8. 影响：无（备注：回退无日志，改键用户看不出配置被忽略，但这是声明过的行为）。
---

### P-11 · unity_script_write_file 可越出 scripts/ 任意写 —— **P-PROVED（P1 安全）**

1. 位置：`loom_mcp.py:578-588`。
2. 契约：工具描述"在**项目 scripts/ 目录下**编写或更新"；EAI 侧同语义写操作必须过白名单（`agent_commands.py:83-132`，理由"Agent（含提示词注入）发出的写文件命令只能落这些根之下"）。
3. 路径枚举：
   - 路径 1：`fname='a.lua'` → 正常；
   - 路径 2：`fname='../../x.py'` → `os.path.join(scripts_dir, ...)` 不规范化 `..` → 越出；
   - 路径 3：`fname` 为绝对路径 → `os.path.join` 丢弃前缀（语言规范）→ 任意绝对路径；
   - 校验只有 `endswith('.lua'/'.py')`（581-582），无白名单、无 realpath。
4. 实际：两条越界路径都写入成功且 `isError=False`。
5. 差异：契约"scripts/ 目录下"vs 实际可写任意 Python/Lua 后缀落点；与 EAI 白名单不一致（同一威胁模型两套边界）。
6. 触发：MCP 客户端传 `../` 或绝对路径（提示词注入即可）。
7. 验证（探针 A）：
   ```
[C8] unity_script_write_file filename="../../escape_probe.py" -> isError=False | 脚本写入成功: ...\scripts\../../escape_probe.py (3 bytes)
[C9] 实际落盘路径 = ...\escape_probe.py exists = True  越出 base_dir = True
[C10] 绝对路径 filename -> isError=False exists=True
   ```
8. 影响：P1（任意文件投放面）。建议方向：MCP 侧复用 `_safe_write_path`（或 realpath + scripts/ 前缀 + 拒绝绝对路径）。

---

### P-12 · dispatch_tool 无异常隔离，畸形参数杀死 stdio 服务 —— **P-PROVED（P2 崩溃）**

1. 位置：`loom_mcp.py:907-916`（handle_request 不在 try 内）+ `365-881`（dispatch_tool 无 try）。
2. 契约：MCP = JSON-RPC 2.0 标准通道（2-8 行），任何请求都应返回响应或 error；对照 EAI 的显式契约"命令报错不会崩编辑器：记录日志并返回错误"（`agent_commands.py:224-225`）。
3. 路径枚举：
   - 路径 1：请求体不是对象（`[]` / `123`）→ `req.get` → AttributeError；
   - 路径 2：参数类型错（`filename=123`）→ `(123 or '').strip()` → AttributeError；
   - 路径 3：数组长度不足（`position=[1]`）→ `p[2]` → IndexError；
   - 路径 4：正常工具 → `c.call` 内部 try 捕获网络异常。
4. 实际：路径 1-3 的异常穿透 handle_request → run_stdio_server → 进程退出，客户端断连。
5. 差异：契约要求"返回响应"，实现是"进程退出"。
6. 触发：任何一次畸形 tools/call（模型幻觉参数即可）。
7. 验证（探针 D）：
   ```
[J] 非对象 JSON ([] 作为请求) -> UNCAUGHT AttributeError("'list' object has no attribute 'get'")
[J] tools/call filename=123 (错误类型) -> UNCAUGHT AttributeError("'int' object has no attribute 'strip'")
[J] tools/call position=[1] (长度不足) -> UNCAUGHT IndexError('list index out of range')
   ```
8. 影响：P2（单次坏请求使 MCP 服务不可用）。建议方向：handle_request 外层 try → -32603；run_stdio_server 对 handle_request 加 try；参数入口做类型校验。

---

### P-13 · 通知（无 id）收到 error 响应 —— **P-PROVED（P3）**

1. 位置：`loom_mcp.py:315-340`（else 分支）。
2. 契约：JSON-RPC 2.0：通知不得有响应；`notifications/initialized` 已按此处理（321 行）。
3. 路径枚举：`notifications/initialized` → None（正确）；其它 `notifications/*` → else → 返回 id=null 的 -32601 错误；未知请求方法 → 同样 else（正确）。
4. 实际：非 initialized 的通知也收到响应。
5. 差异：违反"通知无响应"。
6. 触发：客户端发 `notifications/cancelled` / `notifications/roots/list_changed`。
7. 验证（探针 C/D）：
   ```
[C7] notification response = {"jsonrpc": "2.0", "id": null, "error": {"code": -32601, "message": "Method not found: notifications/cancelled"}}
[J] 未知通知 notifications/roots/list_changed -> ok, id= None
   ```
8. 影响：P3（客户端 error 日志/误判）。建议方向：`method.startswith('notifications/')` → return None。
---

### P-14 · keep_world 参数被 EAI 静默丢弃 —— **P-PROVED（P2）**

1. 位置：`loom_mcp.py:463-468` 发送 keep_world；`agent_commands.py:1572-1603` 不读取。
2. 契约：工具 schema 声明 keep_world = "是否保持世界坐标不变"（`loom_mcp.py:101`）。
3. 路径枚举：EAI cmd_reparent 只取 child/parent；全函数无 keep_world 消费点（inspect.getsource 实测 False）。
4. 实际：参数被忽略，物体随父变换移动。
5. 差异：契约承诺"保持世界坐标"，实现不保证。
6. 触发：`unity_gameobject_set_parent(..., keep_world=true)`。
7. 验证（探针 A）：
   ```
[D1] cmd_reparent 是否读取 keep_world: False
[D2] MCP set_parent 发送的 payload 键: ['child', 'parent', 'keep_world']
   ```
8. 影响：P2（Agent 排版位置错乱，无提示）。建议方向：实现 keep_world 或从 schema 删除并说明总是保持局部变换。

---

### P-15 · primitive 枚举含 none，引擎必 KeyError —— **P-PROVED（P2）**

1. 位置：`loom_mcp.py:96`（enum cube/sphere/plane/none）→ `agent_commands.py:426-435` → `editor.py:669-672`。
2. 契约：工具 schema 的 enum 是"合法输入域"声明（96 行）。
3. 路径枚举：cube/sphere/plane → 字典命中；none → 字典取值 KeyError；其它值同样 KeyError（无校验）。
4. 实际：primitive=none 100% 失败。
5. 差异：声明的合法值不在实现域内。
6. 触发：MCP 客户端按 schema 传 none（"只建空物体"意图）。
7. 验证（探针 A）：
   ```
[E1] _add_primitive("none") raises: KeyError('none')
[E2] unity_gameobject_create primitive enum: ['cube', 'sphere', 'plane', 'none']
   ```
8. 影响：P2（每次必错）。建议方向：删掉 none 或先实现空物体分支。

---

### P-16 · 工具 ↔ 分支 ↔ EAI 命令三方覆盖 —— **P-DISPROVED（无缺口）**

1. 位置：`loom_mcp.py:87-299`（声明）vs `365-881`（分支）。
2. 契约：`loom_eai_list` 描述"MCP 工具只是 EAI 命令的子集"（91-92 行）。
3. 路径枚举：逐个 TOOLS_DEF.name 对 dispatch_tool 的分支名；再对工具内 `c.call(...)` 的命令名对 `_COMMANDS`；再校验 schema 的 required 是否都在 properties 内。
4. 实际：72/72 有分支、0 个多余分支、65 个被引用的 EAI 命令全部存在、required 全部在 properties 内。
5. 差异：无。
6. 触发：无。
7. 验证（探针 A）：
   ```
[C3] declared-but-not-dispatched = []
[C4] dispatched-but-not-declared = []
[C5] MCP 引用的 EAI 命令数 = 65  其中 EAI 不存在 = []
[C6] required 不在 properties 的 schema = []
   ```
8. 影响：无（本轮契约闭合的正面证据；建议固化成 tests/test_mcp_contract.py 防漂移）。

---

### P-17 · 非法 JSON 行静默丢弃（无 -32700） —— **P-PROVED（P3）**

1. 位置：`loom_mcp.py:909-916`。
2. 契约：JSON-RPC 2.0：解析错误应回 -32700（id=null）；客户端按请求 id 等响应。
3. 路径枚举：空行 → continue（可接受）；json.loads 失败 → except 后 continue（丢弃，无响应）；成功 → 处理。
4. 实际：坏 JSON 被吞，客户端只能等超时。
5. 差异：契约要求错误响应，实现是静默。
6. 触发：客户端写入半行/多字节截断（stdio 管道常见）。
7. 验证：read `loom_mcp.py:909-916`（except 后 continue，无 log 无 write）。
8. 影响：P3（客户端挂起/超时重试）。建议方向：回 -32700 + 写 stderr。
---

### P-18 · [REGRESSION] 外部模式全屏把 width/height/viewport 改成桌面分辨率 —— **P-PROVED（P2）**

1. 位置：`loom_glfw_window.py:207-224`（本轮 diff 新增）。
2. 契约：`engine.py:265`"外部模式: 无 pygame 窗口（Qt 宿主管窗口）"→ 尺寸由宿主拥有；`loom_glfw_window.py:171-183 _on_resize` 是外部模式唯一同步尺寸并 resize UI 的路径；`loom_player_window.py:128-130` 每帧用 widget 尺寸覆写 `e.width/e.height`（宿主是真源）。
3. 路径枚举：
   - 路径 1（进入）：want=True → width/height=桌面分辨率 → viewport=(0,0,桌面) → 返回，不调 ui.resize、不碰宿主窗口；
   - 路径 2（退出）：用 window_size 还原（外部模式无回调，仍是初值）→ viewport 回初值；
   - 路径 3：ctx.viewport 赋值抛异常 → except 后 pass，静默；
   - 路径 4：宿主下一帧 _tick 覆写 width/height → 与 fullscreen=True 状态位永久不一致。
4. 实际：进入"全屏"后 viewport 2560×1440，宿主 FBO 仍 1280×720；UI 未 resize。
5. 差异：契约（宿主拥有尺寸）vs 实现（引擎单方面改尺寸与视口）。
6. 触发：外部 ctx 模式下直接调用 `_set_fullscreen(True)` / `_toggle_fullscreen()`。
7. 验证（探针 B 的 F 段）：
   ```
[F1] 外部模式进全屏: width/height=(2560, 1440) viewport=(0, 0, 2560, 1440) ui.resize=None
[F2] 宿主 FBO 仍为 1280x720 -> viewport 越界 = True
[F3] 退出全屏: width/height=(1280, 720) viewport=(0, 0, 1280, 720) ui.resize=None
[F4] 对照 _on_resize: ui.resize=(1280, 720) (外部模式唯一会 resize UI 的路径)
   ```
8. 影响：P2（一旦有调用方，画面被裁切/UI 与渲染尺寸错位；可达性见 P-19）。建议方向：外部模式只写 fullscreen 状态位，不改 width/height/viewport；若必须改，走 _on_resize。

---

### P-19 · [REGRESSION] 注释声称的"F11 一按即崩（玩家发布路径默认就是这个模式）"不可达 —— **P-DISPROVED**

1. 位置：`loom_glfw_window.py:200-206`（新增 docstring）。
2. 契约：docstring 断言该分支修复了"玩家发布路径默认就是这个模式"下的 F11 崩溃。
3. 路径枚举（全仓调用方穷举）：
   - 路径 1：`_on_key_cb` 的 F11 分支（436-437）——只有真实 GLFW 窗口才有该回调，因此 `_glfw_win` 必非 None → 不进新分支；
   - 路径 2：`EditorApp`（外部 ctx）→ allow_fullscreen=False（editor.py:128），且 Qt 侧 F11 被 `ui/loom_gui.py:2126` 用于 UI 树坞；
   - 路径 3：`loom_player_window.PlayerWidget.keyPressEvent`（167-178）只写 key_state 并调 on_key_event，不调 _toggle_fullscreen；
   - 路径 4：`Loom.py:299-302` 的 LOOM_REMOTE_MODE=1 走路径 3；
   - 路径 5：全仓 grep 这两个方法名 → 仅 `loom_glfw_window.py:437` + tests/_tmp 探针。
4. 实际：生产代码不存在"外部 ctx + 触发 _set_fullscreen"的路径；HEAD 旧实现（直接取 _glfw_win）在这些路径下同样不会被调用。
5. 差异：注释把"测试桩没有 _glfw_win"当成"玩家发布路径会崩"。
6. 触发：无。
7. 验证：
   ```
$ grep -rn "_toggle_fullscreen" --include=*.py .
loom_glfw_window.py:249-250 (def), :437 (GLFW 按键回调)
tests/_tmp/*.py (探针)
$ grep -n "allow_fullscreen" editor.py engine.py
editor.py:128: self.allow_fullscreen = False
engine.py:201: self.allow_fullscreen = True
   ```
8. 影响：P3（文档/理由失真）；说明 P-18 是"死代码里的错误语义"，实际风险低于其标称等级。

---

### P-20 · GLFW 路径 F11 退出全屏不恢复原尺寸/位置 —— **P-PROVED（P2）**

1. 位置：`loom_glfw_window.py:234-243`（退出）+ `568-575`（_on_window_size_cb 无条件写 window_size）+ `252-273`（_window_rect 在改尺寸后才抓）。
2. 契约：`engine.py:199`"window_size 是窗口模式尺寸（F11 全屏恢复用）"；`tests/test_fullscreen.py:14`"window_size 在全屏期间不被覆盖（退出时要还原的对象）"。
3. 路径枚举：
   - 路径 1：进入 → set_window_size(桌面) → GLFW 触发 size 回调 → _on_window_size_cb 写 window_size=(1920,1055)（fullscreen=True 只跳过 _on_resize，不跳过 window_size 赋值）；
   - 路径 2：退出 → 读 window_size 恢复 → 用被覆盖的值；
   - 路径 3：_window_rect 在 set_window_size/set_window_pos 之后才 GetWindowRect → 存的是全屏矩形。
4. 实际：退出后窗口停在 1920×1055、位置 (0,0)。
5. 差异：契约要求恢复 800×600/原位置，实现恢复成全屏尺寸。
6. 触发：真实窗口按 F11 两次。
7. 验证（探针 B 的 H 段，真实隐藏 GLFW 窗口 + 真实回调）：
   ```
[H3] 初始 window_size = (800, 600)
[H4] set_window_size(1920,1080) 后 window_size = (1920, 1055)  -> 800x600 被覆盖 = True
[H5] 退出全屏 _set_fullscreen(False) 将按 window_size 恢复 = (1920, 1055)
   ```
   测试盲区：`tests/test_fullscreen.py:111-121` 用 _FakeGlfw 桩掉 set_window_size 且不触发回调，因此第 142 行"window_size 不被覆盖"是假绿（测的是初始化值，不是回调行为）。
8. 影响：P2（用户可见的窗口尺寸/位置丢失）。建议方向：全屏期间不改 window_size；_window_rect 在改尺寸前抓取；退出恢复宽高+位置。

---

### P-21 · 外部模式（Qt 玩家窗口）script_keys / 鼠标链路不通 —— **P-PROVED（P1）**

1. 位置：`loom_input.py:107-116`（sync_script_keys 只读 view）+ `loom_glfw_window.py:276-279`（外部模式 _handle_events 直接 return，不刷 script_keys/buttons/_mods/mouse_rel）。
2. 契约：`loom_input.py:109-112`"由引擎渲染帧头调用，与 pygame 路径每帧刷新同语义"；`67-73` 声明依赖 self.view。
3. 路径枚举：
   - 路径 1（EditorApp，外部 ctx，有 view）：editor.py:1903 调 sync_script_keys → view.key_pressed_array() → 正常（ui/loom_gui.py:407 实现）；
   - 路径 2（PlayerApp(ctx=...)，无 view，loom_player_window.py:104-114）：_key_pressed() 返回空 defaultdict；且全仓只有 editor.py 调 sync_script_keys → script_keys 恒空；
   - 路径 3（宿主按键）：keyPressEvent 只写 engine.key_state（171/184 行），无消费者把 key_state 转成 script_keys；
   - 路径 4（鼠标）：_update_mouse_rel 只在 _handle_events 内调用 → 外部模式早退 → mouse_rel 恒 (0,0)；set_mouse_locked（127-146）对无该方法的 view 只改状态。
4. 实际：is_key('w') / get_action('向前') 恒 False；key_state 被写入但无人读取。
5. 差异：契约"与 pygame 路径每帧刷新同语义"vs 外部玩家路径无刷新、无数据源。
6. 触发：`Loom.py:299-302`（LOOM_REMOTE_MODE=1 → run_player_window）下的 WASD 移动/跳跃脚本、鼠标转视角。
7. 验证（探针 B 的 G 段）：
   ```
[G1] _key_pressed() -> {} (view 缺失 -> 空)
[G2] sync_script_keys() -> 全 False = True
[G3] is_key("w") = False  get_action("向前") = False
[G4] 手写 script_keys 后 is_key("w") = True (缺口只在刷新环节)
[G5] loom_player_window 写 key_state 的方式: True
   ```
8. 影响：P1（该入口下玩家输入整体失效）。建议方向：给 PlayerApp 外部路径提供 key_pressed_array（读 key_state）并在渲染帧头调 sync_script_keys；或 _key_pressed 的 view 缺失分支回退 key_state。
---

### P-22 · KEY_BINDINGS 重复定义 —— **P-PROVED（P3）**

1. 位置：`loom_input.py:44-62` 与 `203-221`。
2. 契约：模块顶层常量应单一事实（`engine.py:338` 用它建 self._key）。
3. 路径枚举：导入时第二份覆盖第一份；两份内容逐字段相同（含同一条 2026-08-28 注释）。
4. 实际：生效的是 203-221；44-62 不可达。
5. 差异：无功能差异。
6. 触发：将来只改第一份 → 不生效。
7. 验证（探针 E）：`[K8] KEY_BINDINGS 定义次数 = 2`。
8. 影响：P3。

---

### P-23 · 'e' 同时是相机下移与"交互"动作键 —— **P-PROVED（P3）**

1. 位置：`loom_input.py:51`（CAMERA_DOWN='e'）与 `37`（'交互': ['e']）。
2. 契约：`59-61 行` 记录了同类冲突的处理先例："删除 'RESET_ALL': 'space' —— 与输入动作'跳跃'共用空格键，玩家游戏内按空格被复位回出生点"（即动作键不得与相机键共用）。
3. 路径枚举：路径 1（编辑态）：只读 _key_pressed() → _update_camera 用 KEY_BINDINGS，脚本不跑；路径 2（播放态，PlayerApp 默认 orbit_mode=True）：_update_camera 与 update_scripts 同帧读取 → 按 E 同时下移相机与触发"交互"。
4. 实际：双语义同时生效。
5. 差异：同类问题（space）已被修，'e' 残留。
6. 触发：播放态按 E（交互），轨道相机会同时下移。
7. 验证（探针 E）：`[K5] KEY_BINDINGS 与 DEFAULT_ACTIONS 交叉键: ['Down','Left','Right','Up','a','d','e','s','w']`。
8. 影响：P3（WASD 重叠是设计选择；'e' 的"交互 vs 相机下移"是语义冲突）。建议方向：CAMERA_DOWN 改键或明确文档化。

---

### P-24 · 右 Shift / 右 Ctrl 无键名 —— **P-PROVED（P3）**

1. 位置：`loom_input.py:22`（只有 Shift 到 K_LSHIFT、Ctrl 到 K_LCTRL）；`loom_glfw_window.py:62-67` 同时映射了 LEFT/RIGHT 两套。
2. 契约：DEFAULT_ACTIONS['加速']=['Shift']（38 行）意图是"任意 Shift"。
3. 路径枚举：物理右 Shift → _GLFW_TO_PG 有 K_RSHIFT，但 _KEYMAP 无名字 → script_keys 不含该键 → get_action('加速') 为 False；_KEYMAP 全部 26 键的值都有 GLFW 反向映射（探针 K3=[]），说明不是映射缺失而是键名覆盖缺失。
4. 实际：右 Shift/右 Ctrl 不触发任何动作/相机键。
5. 差异：契约"Shift"包含左右，实现只认左。
6. 触发：玩家按右 Shift 加速。
7. 验证（探针 E）：`[K7] RightShift=False RightCtrl=False`。
8. 影响：P3。建议方向：_KEYMAP 增 RShift 或把动作绑定改成键码列表。

## 3. 统计

| 结论 | 数量 | 编号 |
|---|---|---|
| P-PROVED | 19 | P-02,03,04,05,06,07,08,11,12,13,14,15,17,18,20,21,22,23,24 |
| P-DISPROVED | 4 | P-01,10,16,19 |
| P-UNKNOWN | 1 | P-09 |
| P-CONTRADICTION | 0 | — |
| 合计 | 24 | |

**CONTRADICTION=0 的说明**：四条 DISPROVED 的证伪链都建立在"路径/分支穷举"上（P-01 两份注册按源序覆盖；P-10 函数体四条 except 路径全覆盖；P-16 72 个工具名与全部分支双向穷举；P-19 全仓调用方穷举），各自的正手链在同一基准下无法构造反例，因此不存在"两边都成立"。
**P-18 与 P-19 不是矛盾**：P-18 证的是"分支被调用时语义错误"（直接调用即复现），P-19 证的是"该分支在生产调用图中不可达"——判定对象不同（语义正确性 vs 可达性），合并结论是"死代码中的错误语义"，已写入 P-18 的影响说明。

**P-UNKNOWN=1 的说明**：P-09（junction 逃逸）需要构造 NTFS junction 才能判定，属环境前提，已给出下一次探针（最多 3 次）。

## 4. 修复建议排序（只给方向，不含代码）

| 序 | 等级 | 项 | 方向 |
|---|---|---|---|
| 1 | P0 | P-04 | ui_add 颜色字段复用 parse_color + _COLOR_FIELDS；非法值在命令层返回 error；补"字符串颜色 → 渲染不崩"回归用例 |
| 2 | P1 | P-03 | ui_add/ui_set 的 visible/enabled/is_on/show_bar/close 统一 as_bool |
| 3 | P1 | P-05 | object_select 去掉 or hits；歧义/越界返回 error；MCP delete/duplicate 先按 guid 定位 |
| 4 | P1 | P-11 | MCP 写脚本复用 _safe_write_path（realpath + scripts/ 前缀 + 拒绝绝对路径） |
| 5 | P1 | P-21 | 外部玩家路径补 key_pressed_array（读 key_state）并每帧 sync_script_keys；鼠标 rel 同源 |
| 6 | P2 | P-12 | handle_request / run_stdio_server 加异常隔离 → -32603 |
| 7 | P2 | P-14/P-15 | schema 与实现对齐（删 none / 删 keep_world，或实现之） |
| 8 | P2 | P-18 | 外部模式 _set_fullscreen 只同步状态位；如需改尺寸走 _on_resize |
| 9 | P2 | P-20 | 全屏期间不覆盖 window_size；_window_rect 改尺寸前抓取；退出恢复宽高+位置 |
| 10 | P3 | P-02/P-08/P-13/P-17/P-22/P-23/P-24 | 注册重复守卫、数字派生、通知不响应、-32700、删重复常量、'e' 改键、右 Shift 键名 |
| 11 | P3 | P-06/P-07 | 删重复赋值/重复函数 |
| 12 | P-UNKNOWN | P-09 | 先做 junction 探针，再决定是否 realpath |

## 5. 需要人类裁决的封闭问题

1. **P-04 的颜色字符串**：ui_add 的颜色字段是否允许 '#RRGGBB' 字符串（与 ui_set 一致）？A. 允许，ui_add 改为 parse_color；B. 不允许，ui_add 收到字符串即报错。代价：A 与现状 ui_set 一致但需补测试；B 会与 MCP 沙盘工具（loom_ui_add_line 传字符串）产生两套约定。
2. **P-21 的投入**：是否要求 LOOM_REMOTE_MODE=1（Qt 玩家窗口）达到与 GLFW 玩家窗口同等的键鼠输入？A. 是（需补 key_state 到 script_keys 的适配层 + 鼠标 rel）；B. 否（该入口只做"远程可见"，文档标注输入不可用，P1 降级为 P3）。
3. **P-09 的白名单强度**：写路径白名单是否要求抵御 junction/符号链接逃逸（即改用 os.path.realpath）？A. 要求（多一次 realpath 与最强路径一致性）；B. 不要求（本机单用户，接受现状并记录为已知边界）。

## 附录 A：探针源码（脚本留在 %TEMP%\eai_audit，不入库）

均以 `LOOM_NO_SAVE_MIGRATE=1`、`sys.path.insert(0, BASE)`、`os.chdir(BASE)` 开头，BASE 为引擎目录；输出见正文各链第 7 段。

```python
# probeA.py 摘要 (P-01..P-15, P-18)
import agent_commands as AC
print(len(AC._COMMANDS))                                  # 91
AC.command('__probe_dup__')(lambda w,a:'first'); AC.command('__probe_dup__')(lambda w,a:'second')
print(AC._COMMANDS['__probe_dup__'](None,None))            # second
import loom_ui
class _Ed: ui = loom_ui.UIManager(); undo = None
class _Win: editor = _Ed()
w=_Win(); AC.dispatch('ui_canvas_add', {'width':800,'height':600}, w)
AC.dispatch('ui_add', {'type':'panel','bg_color':'#FF0000'}, w)
e=w.editor.ui.canvases[0].root.find('panel_0'); print(e.bg_color)   # 7 字符 tuple
try: e.bg_color[3]/255.0
except Exception as ex: print('TypeError:', ex)
AC.dispatch('ui_add', {'type':'toggle','name':'tg','visible':'false','is_on':'false'}, w)
print(w.editor.ui.canvases[0].root.find('tg').visible)     # True
import loom_mcp as M, inspect, re
src=inspect.getsource(M.LoomMCPServer.dispatch_tool)
print(len(M.TOOLS_DEF), sorted(set(re.findall(r"name == '([^']+)'", src)) - {t['name'] for t in M.TOOLS_DEF}))
print([c for c in set(re.findall(r"c\.call\('([^']+)'", src)) if c not in AC._COMMANDS])
srv=M.LoomMCPServer(client=M.LoomEngineClient(base_dir=tempfile.mkdtemp()))
print(srv.handle_request({'jsonrpc':'2.0','method':'notifications/cancelled','params':{}}))
print(srv.dispatch_tool('unity_script_write_file', {'filename':'../../x.py','code':'x=1'})['isError'])
print('keep_world in cmd_reparent:', 'keep_world' in inspect.getsource(AC.cmd_reparent))
import loom_glfw_window as GW
# 外部全屏: width/height/viewport 被改成桌面, ui 未 resize

# probeD.py 摘要 (P-12)
for req in ([1,2],
            {'jsonrpc':'2.0','id':2,'method':'tools/call','params':{'name':'unity_script_write_file','arguments':{'filename':123}}},
            {'jsonrpc':'2.0','id':3,'method':'tools/call','params':{'name':'unity_gameobject_create','arguments':{'position':[1]}}}):
    try: srv.handle_request(req)
    except Exception as ex: print('UNCAUGHT', repr(ex))

# probeB2.py 摘要 (P-20, P-21) —— 真实 GLFW 隐藏窗口
import glfw, loom_glfw_window as GW
glfw.window_hint(glfw.VISIBLE, glfw.FALSE); win=glfw.create_window(800,600,'p',None,None)
glfw.set_window_user_pointer(win, fe); glfw.set_window_size_callback(win, GW._on_window_size_cb)
glfw.set_window_size(win, 1920, 1080); glfw.poll_events()
print(fe.window_size)     # (1920, 1055) -> 原 800x600 被覆盖
```

> 完整探针输出已在正文逐条引用；脚本与输出均留在 %TEMP%\eai_audit（仓库外，不入库），复跑直接执行同名文件即可。
