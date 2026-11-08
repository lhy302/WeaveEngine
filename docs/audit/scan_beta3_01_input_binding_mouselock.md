# 输入 / 键位 / 鼠标锁定链 扫描报告（beta3 修复轮，模块 01）

> 编号: 01 · 模块: 输入/键位/鼠标锁定链 · 扫描日期: 2026-11-08 · HEAD = `62479f0` · 基线 = `f53a82a`
> 方法论: 桌面两份文档（白盒契约/黑盒实现/灰盒验证/人类掌舵；粗筛→双向推演→实操闭环，A6 标准） + `docs/audit/SCAN_PROTOCOL.md`
> 判定基准清单（此后证真链只能引用这几条）:
> - `docs/handoff/20261107_变更清单.md` §G（abfa80b / 9ae7dcc / bdf67ee 三条提交的意图）
> - `docs/handoff/接手总纲_20261107_引擎发布与游戏打包.md` §2.5 / §2.6 / §3.4 / §4 / §6（配置优先级与键位/鼠标锁定设计意图）
> - `docs/audit/_scan_summary.md` §2 / §6（Q4 场景非不可信输入／Q5 撤销全覆盖／Q6 后端回退语义／Q7 多 Canvas 只吞空白）
> - 被审文件内的 docstring / 注释（仅在文档未规定时使用，并标明）

## 0. 范围与方法

### 0.1 文件清单（行数 = `Get-Content` 实测）

| 文件 | 行数 | 本轮 diff 规模 | 备注 |
|---|---|---|---|
| Loom/loom_input.py | 316 | +99/-?（`git diff --stat`） | _KEYMAP 30→76、DEFAULT_ACTIONS 增解锁鼠标、apply_game_bindings 调用点、rebind_action 改语义、get_action_bindings |
| Loom/loom_glfw_window.py | 603 | 51 行改动 | _GLFW_TO_PG 重建 80 项 |
| Loom/game_settings.py | 161 | 新增文件 | 游戏设置.json 读写：render_api / mouse_lock_allowed / mouse_locked / key_bindings |
| Loom/engine.py | 1524 | +101 | set_logic_paused / request_game_exit / render_api API / _poll_mouse_unlock_key / get_action_bindings / set_action_binding / update_scripts 首行插 poll |
| Loom/scene_driver.py | 1313 | （跨模块引用，非本模块 diff 范围） | VK 侧同语义实现，用于 GL/VK 一致性对照 |
| Loom/scripts.py | — | 未改动 | first_person / third_person 的 Tab 解锁（对照用） |

diff 命令（实跑）:
```
git diff f53a82a..HEAD -- Loom/loom_input.py Loom/loom_glfw_window.py Loom/engine.py Loom/game_settings.py
git show f53a82a:Loom/loom_input.py
```
`git diff --stat` 实测: `engine.py +101 / game_settings.py +161 / loom_glfw_window.py 51 / loom_input.py +99`，合计 386 插入 26 删除。

### 0.2 跑过的命令（全部实跑，输出见 §2 各项的"验证"栏）

| # | 命令 | 用途 |
|---|---|---|
| C1 | `python Loom/tests/_tmp/beta3_scan_01b_probe.py` | 本轮新建探针：S1..S11，见下 |
| C2 | `python Loom/tests/_tmp/beta3_scan_01_run_test_scripts.py` | 既有回归测试（写路径重定向到临时目录）|
| C3 | `python Loom/tests/_tmp/beta3_scan_01_probe2.py` | 上一任探针复跑（rebind 落盘 / 落点 / 失败返回）|
| C4 | `python Loom/tests/_tmp/beta3_scan_01_probe3.py` | 上一任探针复跑（键名大小写 / 空列表），**其"全键手动注入"版本 S12a 已证为伪证据，见 P-01-06** |
| C5 | `git status --porcelain` | 每轮跑完自查，确认未改受跟踪文件 |

环境: Python 3.12.10 / pygame 2.6.1 / `PYTHONIOENCODING=utf-8`（否则中文输出在控制台乱码）。

本轮探针 `Loom/tests/_tmp/beta3_scan_01b_probe.py`（只读仓库，唯一写路径 = `LOOM_GAME_DIR` 临时目录）分 11 段:
S1 _KEYMAP 字面量重复键 / S2 双向集合数学 / S3 apply_game_bindings 存在性 / S4 AttributeError + 引擎吞异常 / S4b 游戏层覆盖 / S5 同一帧双翻转 / S6 docstring 位置 / S7 暂停态 poll 计数 / S8 read_key_bindings 坏类型 / S9 每帧成本 / S10 默认值 / S11 76 键快照开销。

**受跟踪文件写保护**：所有探针都把 `LOOM_GAME_DIR` 指向临时目录；C2 另把 `InputMixin.save_action_bindings` 重定向。每轮结束 `git status --porcelain` 只出现"本轮新增报告 + 探针"的 `??` 条目，无 ` M ` 条目（实测输出见 §2 末尾"写保护自查"）。

## 1. 粗筛清单（含跳过项留痕）

### 1.1 疑似项（六元组）

| ID | 位置 | 标签 | 初步方向（指向具体代码事实，非结论） |
|---|---|---|---|
| P-01-01 | loom_input.py:261（调用点）／engine.py:389-392（吞异常点） | SEM-SILENT / AUDIT-ASYMMETRY | `_load_action_bindings()` 末尾调用 `self.apply_game_bindings()`，全仓库无该方法的定义（`grep -rn "game_bindings" .` 只命中调用点与本行文档）→ 必然抛 AttributeError；engine 侧 try/except 把 actions 整体重置为 DEFAULT_ACTIONS |
| P-01-02 | engine.py:897-899 + scripts.py:642-645 / 701-704 | AUDIT-ASYMMETRY / SEM-MISMATCH | 引擎级"解锁键"与 first_person/third_person 脚本各自做一次 Tab 边沿翻转，同一逻辑帧内两次 `toggle_mouse_locked()` |
| P-01-03 | engine.py:919-931 + loom_input.py:281-289 | SEM-SILENT | `set_action_binding` 无论持久化是否成功都 `return {'ok': True, ..., 'saved': True}`；内层写失败被 `try/except: pass` + print 吞掉 |
| P-01-04 | engine.py:935 / 971（poll 调用位置） | SEM-MISMATCH | `_poll_mouse_unlock_key` 只在 `update_scripts`/`_update_scripts` 内调用，而两者只在**逻辑帧**跑；暂停（F9 / 通关暂停）时逻辑帧为零 → 解锁键失效，与 §2.6"每帧检测"表述不一致 |
| P-01-05 | loom_input.py:272-290 | DESIGN-DRIFT / SEM-DEFAULT | `rebind_action` 同时写 `游戏设置.json`（每游戏）与引擎 `输入配置.json`（全局、受跟踪），与自身 docstring "不污染引擎 输入配置.json" 冲突；空列表的持久化语义两侧不一致 |
| P-01-06 | loom_input.py:191-198 + game_settings.py:88-99 | SEM-DEFAULT / AUDIT-ASYMMETRY | `get_action` 用 `self.actions.get(name, (name,))`：①键名大小写/别名严格区分（`f10`≠`F10`、`space`≠`Space`），非法键名静默不生效；②空列表绑定挡住"回退同名键"分支 |
| P-01-07 | game_settings.py:20-31 | DESIGN-DRIFT | `game_dir()` 只看 `LOOM_GAME_DIR` / `sys.argv[0]`；编辑器与 `Loom.py --run` 的主体都是 `Loom/Loom.py` → 落点是**引擎目录**而非"游戏文件夹"，与 §2.5 / §3.4"每游戏配置"的表述冲突 |
| P-01-08 | loom_input.py:15-93 | AUDIT-DEADCODE / AUDIT-DOCIMPL | `_KEYMAP` 字面量 94 条、其中 18 条重复（a/d/e/i/j/k/l/o/q/s/u/w/1..6）；注释"旧表只有 30 个键"与基线实测 26 键不符 |
| P-01-09 | loom_glfw_window.py:52-83 | AUDIT-ASYMMETRY | `_GLFW_TO_PG` 80 项 vs `_KEYMAP` 76 键名；文档称"80 项与 _KEYMAP 全量对齐/双向一一对应" |
| P-01-10 | engine.py:934-936 / scene_driver.py:970-972 | AUDIT-NOCHAIN | `_poll_mouse_unlock_key()` 被插在 docstring **之前**，函数文档字符串退化为无效果表达式 → `__doc__ is None` |
| P-01-11 | game_settings.py:88-99 | SEM-DEFAULT | `read_key_bindings` 对坏类型静默丢弃；`None` 被 `str()` 变成合法字符串键名 `'None'` 保留 |
| P-01-12 | loom_input.py:104 + game_settings.py:70 + editor.py:2188,2198 | DESIGN-CONFLICT | 解锁动作默认 Tab，与编辑器既有的 Tab=选中下一个物体、F10=步进一帧冲突；`game_settings.py:70` 的示例恰好用 `F10` |
| P-01-13 | engine.py:882-908 / loom_glfw_window.py:293-303 | BND-RESOURCE | 每帧成本：poll 一次 `get_action`；键盘快照 26→76 键 |
| P-01-14 | loom_input.py:286-289 vs scene_driver.py:937-946 | AUDIT-ASYMMETRY | GL 侧 rebind 写引擎 `输入配置.json`，VK 侧 rebind 不写（driver 无 `save_action_bindings`），同一 API 落盘面不同 |
| P-01-15 | game_settings.py:73-74,129-133 + runtime.py:78-84 | DESIGN-AMBIG | `mouse_lock_allowed/mouse_locked` 默认 True/True；仓库内**不存在任何** `游戏设置.json`（实测 `Get-ChildItem -Recurse -Filter 游戏设置.json` = 空）→ 旧 GL/VK 游戏（含吃豆人）启动即被捕获光标 |
| P-01-16 | loom_input.py:246-259 | SEM-DEFAULT | `_load_action_bindings` 的 `list(ks)` 对非序列值抛 TypeError，被同一个 except 捕获 → **一条坏条目**把整份文件的绑定全部丢弃 |

### 1.2 跳过登记（四类可审计理由之一 + 出处）

| 跳过号 | 位置 | 理由类别 | 具体事实 / 出处 |
|---|---|---|---|
| SKIP-01 | loom_input.py:200-219 `set_mouse_locked` 的 GLFW 分支 | 已有回归测试覆盖 | `Loom/tests/test_scripts.py:245-257`、`Loom/tests/test_vk_camera_align.py:341-365` 覆盖锁定/解锁状态机；且该段不在 `git diff f53a82a..HEAD` 内（未改）|
| SKIP-02 | `_KEYMAP` 常量值本身（`pygame.K_*` 是否对应正确物理键） | 语言规范保证 | `pygame.K_*` 常量由 pygame 定义（`loom_input.py:11 import pygame`）；常量存在性由探针 S2 导入成功证明 |
| SKIP-03 | game_settings.py:38-45 `load()` 损坏 → `{}` | 白盒契约明确声明 | `game_settings.py:39` docstring "读整份配置 (不存在/损坏 -> {})"；实测见 §2 P-01-11 的坏 JSON 段 |
| SKIP-04 | engine.py:907-908 / scene_driver.py:932-933 的 `except Exception: pass` | 白盒契约 + 代码事实 | 被包裹的三处调用（`getattr`、`get_action`、内层 `set_mouse_locked`）本身均已内部 try 或不抛；此 except 不承担错误模型。通用"吞异常"议题已由 `tools/loom_lint_except.py` 与 12_misc 报告登记，本轮不重复计数 |
| SKIP-05 | `save_action_bindings` / `write_key_binding` 的 `tmp + os.replace` 原子性 | 已有回归 + 未改 | `loom_input.py:263-270` 与基线 `git show f53a82a:Loom/loom_input.py` 逐字相同；`game_settings.py:117-121` 同法 |
| SKIP-06 | `_PG_TO_GLFW` 反查表是否单射（重复 pygame 码覆盖） | 已由本轮探针证据排除 | 探针 S2 实测 `len(_GLFW_TO_PG)=80 len(_PG_TO_GLFW)=80`、"互为单射? True" |
| SKIP-07 | `_KEYMAP` 新增键是否破坏编辑器既有快捷键（F9/F10/Ctrl+Z/0） | 未改路径 + 事件层分离 | editor.py:2174-2207 走 `on_key_event` 事件流，与 `_KEYMAP`→`script_keys` 轮询流分离；仅 P-01-12 登记"语义冲突"这一面 |

粗筛统计: 疑似项 16 条；跳过 7 条；标签分布 SEM-* 6 / AUDIT-* 6 / DESIGN-* 4 / BND-* 1。


## 2. 逐项裁决

> 每条都按 SCAN_PROTOCOL §1 的 8 段式给链；证伪链第 3 段必须是**路径枚举表**，证真链第 7 段必须是**可跑命令 + 实测输出**。

---

### P-01-01 · `apply_game_bindings` 无定义 → 三层键位优先级第 1/2 层全失效 ｜ **P-PROVED（P0）** ｜ [REGRESSION]

**【证伪链】结论: 证伪失败（存在一条必然命中的路径）**

1. **判定基准**
   - 接手总纲 §3.4 表格: "键位 ｜ 游戏设置.json key_bindings > 引擎 输入配置.json > scripts.py DEFAULT_ACTIONS"；§4 文件地图: "loom_input.py ｜ ... apply_game_bindings()"。
   - loom_input.py:260 注释: "叠加本游戏键位覆盖 (游戏设置.json key_bindings 优先)"。
   - 即：引擎启动后 `self.actions` 必须同时反映"引擎 输入配置.json"与"游戏 key_bindings"两层。
2. **代码证据（原样）**
   ```python
   # Loom/loom_input.py:246-261
   def _load_action_bindings(self, path=None):
       p = path or self._action_bindings_file()
       try:
           with open(p, 'r', encoding='utf-8') as f:
               data = _json.load(f)
           if isinstance(data, dict) and data.get('actions'):
               self.actions = {a: list(ks) for a, ks in data['actions'].items()}
               for a, ks in DEFAULT_ACTIONS.items():
                   self.actions.setdefault(a, list(ks))
       except Exception:
           self.actions = dict(DEFAULT_ACTIONS)
       # 2026-11-07: 叠加本游戏键位覆盖 (游戏设置.json key_bindings 优先)
       self.apply_game_bindings()          # ← 第 261 行, 已在 try 之外

   # Loom/engine.py:388-392
   self.actions = dict(DEFAULT_ACTIONS)
   try:
       self._load_action_bindings()
   except Exception:
       self.actions = dict(DEFAULT_ACTIONS)
   ```
3. **路径枚举表（_load_action_bindings 的全部执行路径）**

   | 路径 | 进入条件 | 执行到 261 行? | 是否产生疑似行为 |
   |---|---|---|---|
   | R1 | 配置文件存在且 `data['actions']` 为真 dict | 是 | 是（抛 AttributeError，engine 侧把**已加载的**绑定丢弃） |
   | R2 | 配置文件存在且 `actions` 缺失/为空/非 dict（`data.get('actions')` 为假） | 是 | 是（同上） |
   | R3 | 文件不存在 / JSON 损坏（走 except） | 是 | 是（同上） |
   | R4 | `path` 参数给错类型导致 `open` 前就抛 | 否（在 try 内抛出→被 except 吃掉→仍走到 261） | 是 |

   路径枚举完备性：`_load_action_bindings` 函数体只有一个 try/except 块 + 两条尾部语句，无动态分派、无闭包捕获、无 `**kwargs` 转发；第 261 行在所有路径上都被执行 → **证伪失败**（没有任何一条路径能绕过它）。
4. **预期（仅证真链需要）**：见下。
5. **实际**：见下。
6. **差异**：见下。
7. **可复现验证**：见下。
8. **判定**：证伪失败（0 条路径可绕开），转正手。

**【证真链】结论: PROVED**

1. **判定基准**：同证伪链第 1 段（接手总纲 §3.4 三层优先级 + loom_input.py:260 注释）。
2. **代码证据**：
   ```python
   # 调用点（loom_input.py:261）
   self.apply_game_bindings()
   # 全仓库定义搜索（实跑）
   # grep -rn "game_bindings" .
   #   docs/handoff/接手总纲_...md:157  | loom_input.py | ... apply_game_bindings() ...
   #   Loom/loom_input.py:261:        self.apply_game_bindings()
   #   → 无 def apply_game_bindings / 无 setattr / 无 monkeypatch
   ```
   `game_settings.py`（161 行）只导出 `game_dir/path/load/read/set_value/read_bool/read_key_bindings/write_key_binding/mouse_lock_allowed/mouse_lock_initial/normalize/read_render_api/write_render_api`，**没有** `apply_game_bindings`；`InputMixin`/`GLEngine` 也没有。
3. **最小复现**（`Loom/tests/_tmp/beta3_scan_01b_probe.py` S3/S4/S4b，节选）：
   ```python
   class _Stub(LI.InputMixin):
       def __init__(self): self.actions = dict(LI.DEFAULT_ACTIONS)
   s = _Stub(); s._load_action_bindings(配置文件路径)     # 抛异常
   e = E.GLEngine.__new__(E.GLEngine); e.actions = dict(LI.DEFAULT_ACTIONS)
   try: e._load_action_bindings()                        # 复刻 engine.py:389-392
   except Exception: e.actions = dict(LI.DEFAULT_ACTIONS)
   ```
4. **预期**：启动后 `actions['跳跃']` 应等于"引擎 输入配置.json"里的 `['j']`（文件层），且 `actions['解锁鼠标']` 应等于游戏 `key_bindings` 的 `['F10']`（游戏层覆盖默认 Tab）。
5. **实际（实测输出）**
   ```
   ======== S3 apply_game_bindings 定义存在性 ========
   hasattr(InputMixin, "apply_game_bindings") = False
   hasattr(GLEngine, "apply_game_bindings")   = False
   hasattr(game_settings, "apply_game_bindings") = False

   ======== S4 ... ========
   异常类型 = AttributeError | '_Stub' object has no attribute 'apply_game_bindings'
   异常点 = loom_input.py:261 self.apply_game_bindings()
   仓库 Loom/输入配置.json 里 跳跃 = ['j']
   引擎初始化后 self.actions["跳跃"] = ['space'] -> 文件层被整体丢弃
   引擎初始化后 解锁鼠标 = ['Tab']

   ======== S4b 游戏设置.json key_bindings 是否可能被应用 ========
   read_key_bindings() = {'解锁鼠标': ['F10']}
   初始化后 解锁鼠标 = ['Tab'] (期望 [F10], 实际来自 DEFAULT_ACTIONS)
   ```
6. **差异分析（方向明确）**
   - 文件层：`输入配置.json` 的 `跳跃=['j']` **少做了**（实际 `['space']`）→ 玩家/开发者在文件里改的键位全部失效。注意 `Loom/输入配置.json` 是**受跟踪文件**且当前内容确为 `跳跃:["j"]`（实测），因此这不是假设场景而是仓库现状。
   - 游戏层：`游戏设置.json key_bindings` **少做了**（完全未应用）→ 接手总纲 §3.4 声明的最高优先级层是死条款（AUDIT-DEADCODE）。
   - 次生：既有回归测试 `Loom/tests/test_scripts.py:188` 直接调用 `eg2._load_action_bindings(_cfg)`（**不在 try 内**），实测把整个测试脚本在第 188 行打断，第 189 行之后的全部断言（M39 鼠标锁定、M32 玩家控制器、脚本缓存等）本轮**不再执行**。
7. **可复现验证**
   ```
   python Loom/tests/_tmp/beta3_scan_01b_probe.py        # 见上 S3/S4/S4b 输出
   python Loom/tests/_tmp/beta3_scan_01_run_test_scripts.py
   ```
   实测（C2）尾部：
   ```
   PASS 动作: 重映射后新键生效
   PASS 动作: 重映射后旧键失效
     File "...\Loom\tests\test_scripts.py", line 188, in <module>
       eg2._load_action_bindings(_cfg)
     File "...\Loom\loom_input.py", line 261, in _load_action_bindings
       self.apply_game_bindings()
   AttributeError: 'GLEngine' object has no attribute 'apply_game_bindings'
   ```
   （该段之前的 20 条 PASS 均正常，说明是**本轮新增**的第 261 行引入，而不是既有失败。）
8. **影响与等级**：**P0**。①"改键"这一轮的交付目标（§2.6）在 GL/编辑器路径上整体不生效；②引擎层每帧 poll 依赖的 `actions['解锁鼠标']` 永远是默认 Tab，"改解锁键"功能完全不可用；③既有回归测试被中断，后续 M39/M32 断言静默失去保护。**是否由本轮 diff 引入：是**（基线 `git show f53a82a:Loom/loom_input.py` 的 `_load_action_bindings` 只有 try 块，无第 261 行）→ **[REGRESSION]**。
   **建议修复方向（不含完整实现）**：二选一并在文档里定案——(a) 在 `InputMixin`（或 game_settings 模块）实现该方法：读 `game_settings.read_key_bindings()` 按动作覆盖 `self.actions`；(b) 若设计上不想有该方法，则删掉第 261 行并把游戏层覆盖挪进 `_load_action_bindings` 的 try 内。任一路线都必须：把"游戏层覆盖"放进文件读取之后的独立 try，避免一层出错连带丢掉另一层；补一条回归测试（引擎初始化后 `actions` 应同时体现两层）。

---

### P-01-02 · 引擎级解锁键与 first_person/third_person 脚本在同一帧双翻转 → 解锁键净无效 ｜ **P-PROVED（P1）** ｜ [REGRESSION]

**【证伪链】结论: 证伪失败**

1. **判定基准**：接手总纲 §2.6 "**强制解锁键**：动作名 解锁鼠标（默认 Tab），在 GLEngine.update_scripts / SceneDriver._update_scripts 每帧检测（_poll_mouse_unlock_key），不依赖游戏脚本"；§2.7 表 "键位改到 F10/Esc 无反应 → 补到 76 键"（说明目标是"任何游戏都能解锁"）。变更清单 §G abfa80b "引擎强制解锁动作每帧检测；不允许锁定则永不锁"。
2. **代码证据**：
   ```python
   # Loom/engine.py:934-935（poll 在脚本分发之前）
   def update_scripts(self, delta_time):
       self._poll_mouse_unlock_key()

   # Loom/engine.py:897-899（引擎级边沿翻转）
   k = bool(self.get_action('解锁鼠标'))
   if k and not getattr(self, '_unlock_key_prev', False):
       self.toggle_mouse_locked()

   # Loom/scripts.py:642-645（first_person 自带同名翻转, 未随本轮改动）
   tab = e.is_key('Tab')
   if tab and not self._tab_was:
       e.toggle_mouse_locked()
   self._tab_was = tab
   # 同形代码在 scripts.py:701-704（third_person）
   ```
3. **路径枚举表（一次逻辑帧内可能发生的组合）**

   | 场景 | 引擎 poll 是否翻转 | 脚本是否翻转 | 净结果 |
   |---|---|---|---|
   | 无 first/third_person 脚本的纯游戏（吃豆人） | 翻转 1 次 | 无该代码 | 解锁 ✔ |
   | 有 first_person 且 `解锁鼠标` 绑定含 Tab（默认） | 翻转 1 次 | 翻转 1 次 | **锁定不变 ✘** |
   | 有 third_person，同上 | 翻转 1 次 | 翻转 1 次（701-704） | **锁定不变 ✘** |
   | 脚本被禁用/坏脚本（`_script_broken`） | 翻转 | 否 | 解锁 ✔ |
   | 玩家把 `解锁鼠标` 改到非 Tab 键（P-01-01 阻断前不可达；修好后可达） | 翻转 | 否（脚本只听 Tab） | 解锁 ✔ |

   路径枚举完备性：`update_scripts` 在 poll 之后对脚本逐个 `update()`（engine.py:963-990 段），first/third_person 的 `update` 必然被调用；两条翻转路径**同时**存在且不是互斥条件 → 证伪失败。
4. **预期/5. 实际/6. 差异**：见证真链。
7. **验证**：见证真链第 7 段。
8. **判定**：证伪失败，转正手。

**【证真链】结论: PROVED**

1. **判定基准**：同证伪链第 1 段。
2. **代码证据**：同证伪链第 2 段（两组代码都在本轮 HEAD 上）。
3. **最小复现**（探针 S5，用**真实的** `GLEngine._poll_mouse_unlock_key` 与**真实的** `scripts.FirstPersonScript`，只把引擎换成 `InputMixin` 子类桩以避开 GL 上下文）：
   ```python
   class Eng(LI.InputMixin): pass
   Eng._poll_mouse_unlock_key = E.GLEngine._poll_mouse_unlock_key
   en.script_keys = {'Tab': True}; en.actions = dict(LI.DEFAULT_ACTIONS)
   en.mouse_locked = True; en.mouse_unlock_requested = False
   fp = SC.FirstPersonScript(); fp.engine = en; fp.on_start()   # 脚本锁定鼠标
   en._unlock_key_prev = False
   en._poll_mouse_unlock_key()        # 帧内第 1 步（engine.py:935 的顺序）
   fp.update(0.0)                     # 帧内第 2 步（脚本 update）
   ```
4. **预期**：按一次 Tab → 解锁一次（`mouse_locked == False`, `mouse_unlock_requested == True`），与 UN-1 无关的纯状态机结论。
5. **实际（实测输出）**
   ```
   ======== S5 同一逻辑帧内 _poll_mouse_unlock_key + first_person 脚本 Tab 双翻转 ========
   脚本 on_start 后 mouse_locked = True  unlock_requested = False
   --- 一帧: 先引擎级 poll (engine.py:935), 再脚本 update ---
   [输入] 按键 [Tab] 切换鼠标锁定 -> 已解锁
    poll 后       mouse_locked = False unlock_requested = True
    脚本 update 后 mouse_locked = True unlock_requested = False
    结论: 净效果 = 仍锁定? True
   ```
6. **差异分析**：预期"按一次 Tab 解锁"，实际"按一次 Tab 后仍锁定"，且日志先打印"已解锁"再被脚本翻回锁定——**多做了**一次反向翻转（脚本侧），玩家观感是"解锁键没反应 + 控制台刷两行自相矛盾的日志"。触发条件：场景挂了 `first_person` 或 `third_person` 脚本 **且** `解锁鼠标` 动作绑定包含 Tab（默认即如此）。
7. **可复现验证**：`python Loom/tests/_tmp/beta3_scan_01b_probe.py`（S5 段，输出见上）。
8. **影响与等级**：**P1**（功能错误：本轮交付的"强制解锁键"在唯一会真的锁定鼠标的两类场景里失效）。**是否由本轮 diff 引入：是**（poll 调用是 engine.py 新增，脚本的 Tab 翻转是既有代码）→ **[REGRESSION]**。
   **建议修复方向**：明确"解锁意图"的单一所有者。两条路线需人类定案：①引擎 poll 成为唯一所有者，first/third_person 脚本删掉自己的 Tab 分支（脚本侧不再是锁定状态的第二写者）；②保留脚本分支，引擎 poll 在检测到脚本已处理时跳过（需要一个"本帧已消费解锁键"标志）。任一路线都要补一条"按一次 Tab 恰好翻转一次"的回归测试（覆盖有/无 first_person 两种场景）。


---

### P-01-03 · `set_action_binding` 在持久化失败时仍返回 `ok/saved = True` ｜ **P-PROVED（P1）** ｜ [REGRESSION]

**【证伪链】结论: 证伪失败**

1. **判定基准**：接手总纲 §2.6 "改键 API：engine.get_action_bindings() / set_action_binding(action, keys)（**立即生效 + 写入游戏配置**）"；`engine.py:919-931` 自身 docstring "改某个动作的按键并**写入本游戏配置** … 返回 {'ok', 'action', 'keys', 'saved'}""。即：`saved` 字段的语义是"已写入游戏配置"。
2. **代码证据**：
   ```python
   # Loom/engine.py:919-932
   def set_action_binding(self, action, keys):
       try:
           ...
           self.rebind_action(str(action), keys)
           return {'ok': True, 'action': str(action), 'keys': keys,
                   'saved': True}                 # ← 无条件 True
       except Exception as e:
           return {'ok': False, 'action': str(action), 'error': repr(e)}

   # Loom/loom_input.py:272-290（rebind_action 把写失败吃在内部）
   try:
       import game_settings
       game_settings.write_key_binding(name, keys)
   except Exception as e:
       print('[输入] 写游戏键位失败 (忽略): %r' % (e,))   # ← 只打印, 不外抛
   try:
       self.save_action_bindings()
   except Exception:
       pass                                            # ← 同样静默
   return self.actions[name]
   ```
3. **路径枚举表**

   | 路径 | 写游戏配置结果 | 写引擎配置结果 | `saved` 实际值 | 是否产生疑似行为 |
   |---|---|---|---|---|
   | W1 | 成功 | 成功 | True | 否（正确） |
   | W2 | 成功 | 失败（引擎目录只读） | True | **是**（saved 应为"部分成功"） |
   | W3 | 失败（目标目录只读 / 磁盘满 / 目标是目录） | 任意 | True | **是**（saved 应为 False） |
   | W4 | 失败 | 失败 | True | **是** |

   完备性：`rebind_action` 内部的两处 try/except 已把两条写路径的异常全部吃掉，`set_action_binding` 的 except 分支在实际执行中**不可达**（除 `str()` 失败等极端情形）→ 证伪失败。
4. **预期**：W3/W4 下 `ok/saved` 必须为 False（或至少给出 `error`），让改键 UI 能提示玩家"设置没存下来"。
5. **实际（实测，探针 C3 S12b：把 `LOOM_GAME_DIR` 指到"目标路径本身是个目录"的位置，让写必定失败）**
   ```
   ====== S12b 写入失败时 set_action_binding 的返回 ======
   [输入] 写游戏键位失败 (忽略): PermissionError(13, '拒绝访问。')
   写入必失败 -> {'ok': True, 'action': '向前', 'keys': ['i'], 'saved': True}
   [输入] 写游戏键位失败 (忽略): PermissionError(13, '拒绝访问。')
   未知动作名 -> {'ok': True, 'action': '随便写', 'keys': ['i'], 'saved': True}
   ```
6. **差异分析**：预期 `saved=False`，实际 `saved=True` —— **多做**了一个成功承诺（SEM-SILENT：调用方无法区分"真保存"与"只在内存里改了"）。后果链：玩家在打包游戏里改键（安装在 `Program Files` 时写盘被拒）→ UI 收到 ok → 提示"已保存" → 重启游戏后键位回退 → 玩家反复改键无效。触发条件：游戏目录不可写（Windows UAC 下的典型安装位置）或磁盘只读。
   次生（同一段代码暴露）：`set_action_binding('随便写', ['i'])` 对**不存在的动作名**同样返回 ok=True，并在 `actions` 里新建一个永不被消费的条目（无动作名白名单）。
7. **可复现验证**：`python Loom/tests/_tmp/beta3_scan_01_probe2.py`（S12b 段）。
8. **影响与等级**：**P1**（功能错误 + 静默失败，直接破坏"改键持久化"这一交付目标）。**是否由本轮 diff 引入：是**（`set_action_binding` 与新的 `rebind_action` 语义都是本轮新增）→ **[REGRESSION]**。
   **建议修复方向**：让写失败可被调用方观察——`rebind_action` 返回"落盘结果"而不是只 print；`set_action_binding` 的 `saved` 取该结果（区分 `saved_game` / `saved_engine` 更好）。同时决定动作名是否需要白名单（未知动作名应拒绝还是允许新建）。

---

### P-01-04 · 解锁键只在逻辑帧检测 → 暂停态（F9 / 通关暂停）失效 ｜ **P-PROVED（P2）**

**【证伪链】结论: 证伪失败**

1. **判定基准**：接手总纲 §2.6 "在 GLEngine.update_scripts / SceneDriver._update_scripts **每帧**检测（_poll_mouse_unlock_key），不依赖游戏脚本"；§2.7 "打包版启动即被无条件锁死且无解锁手段"（engine.py:885-887 注释）说明该键是"最后逃生通道"。
2. **代码证据**：
   ```python
   # engine.py:934-935   poll 是 update_scripts 的第一条语句
   # engine.py:1350-1368 _run_scripts -> update_scripts
   # engine.py:1277-1284 暂停且无步进请求 -> return（本帧零逻辑, 不进 _logic_frame）
   # scene_driver.py:691-693  logic_paused -> _end_frame_input(); return (0, 0)
   # scene_driver.py:970-971  _update_scripts 首行才是 poll
   # scene_driver.py:634-635  _logic_frame -> _update_scripts
   ```
3. **路径枚举表（"玩家按下解锁键的这一刻，poll 会不会跑"）**

   | 运行态 | 逻辑帧是否推进 | poll 是否被调用 | 解锁键是否生效 |
   |---|---|---|---|
   | 正常播放 | 是 | 是（每逻辑帧） | ✔ |
   | `_logic_paused`（编辑器 F9 / 游戏内 `set_logic_paused(True)`，如吃豆人通关面板） | **否** | **否** | ✘ |
   | 编辑态（未播放） | 否 | 否 | ✘（但引擎此刻不锁鼠标，无影响） |
   | 有脚本且脚本被暂停但逻辑仍在跑 | 是 | 是 | ✔ |

   完备性：两条入口（GL `advance_logic` / VK `advance_logic`）在暂停态都直接 return，`update_scripts`/`_update_scripts` 是 poll 的唯一调用点（`grep "update_scripts\|_update_scripts"` 全仓命中仅 engine.py:1362/1368 与 scene_driver.py:635/713）→ 证伪失败。
4. **预期**：暂停时也应按得动解锁键（暂停是"游戏暂停"而不是"输入暂停"；UI 面板正需要鼠标）。
5. **实际（实测，探针 S7：SceneDriver + `key_state={'Tab':True}`，先暂停跑 20 帧、再恢复跑 20 帧，并对 poll 计数）**
   ```
   ======== S7 logic_paused 时 advance_logic 早退 -> 解锁键不再被检测 ========
   暂停态 20 帧: poll 调用次数 = 0  mouse_locked = True unlock_requested = False
   [输入] 按键 [Tab] 切换鼠标锁定 -> 已解锁
   恢复态 20 帧: poll 调用次数 = 30  mouse_locked = False unlock_requested = True
   ```
6. **差异分析**：预期"暂停态 poll 每帧都跑"，实际"暂停态 20 帧 0 次调用"。**少做了**暂停态的输入轮询。触发条件：任何调用 `set_logic_paused(True)` 的游戏状态 + 该游戏允许锁鼠标。
7. **可复现验证**：`python Loom/tests/_tmp/beta3_scan_01b_probe.py`（S7 段）。
8. **影响与等级**：**P2**（边界/可用性：暂停面板是"最需要鼠标"的时刻，也是"最不可能解锁"的时刻；不崩数据、不静默算错）。**是否由本轮 diff 引入：否**（既有"暂停=零逻辑"是设计；新增的 poll 依附在逻辑帧链上，属于新功能与既有暂停语义的接口缝）。证据类别：`IFACE-PRECOND`（新功能把"逻辑帧会跑"当作前置条件，而暂停场景不满足）。
   **建议修复方向**：把 poll 提到"渲染帧必跑的输入段"（例如 `advance_logic` 的暂停早退分支之前、或 `_end_frame_input` 附近），与逻辑帧解耦；补一条"暂停态按解锁键仍能解/回锁"的回归测试。

---

### P-01-05 · `rebind_action` 双写：既写"每游戏配置"又写**受跟踪的**引擎配置 ｜ **P-PROVED（P2）**

**【证伪链】结论: 证伪失败**

1. **判定基准**：`loom_input.py:274-277` docstring 原文："**同时写进本游戏的 游戏设置.json key_bindings** —— 打包游戏的玩家改键只影响这个游戏, **不污染引擎 输入配置.json**；开发环境另存一份到引擎配置便于复用。"；接手总纲 §3.4 的键位优先级把"引擎 输入配置.json"列为**全局**层。
2. **代码证据**：
   ```python
   # loom_input.py:279-290
   keys = list(keys)
   self.actions[name] = keys
   try:
       import game_settings
       game_settings.write_key_binding(name, keys)     # 每游戏层
   except Exception as e: ...
   try:
       self.save_action_bindings()                     # 引擎层（全局）
   except Exception:
       pass
   ```
   `save_action_bindings` 的目标路径 = `loom_input.py:243-244` `os.path.dirname(os.path.abspath(__file__)) + "输入配置.json"`（引擎目录，**受 git 跟踪**：`git ls-files Loom/输入配置.json` 有输出）。
3. **路径枚举表**

   | 调用方 | 写游戏配置 | 写引擎配置 | 结果是否"只影响这个游戏" |
   |---|---|---|---|
   | 打包游戏（exe 目录可写） | ✔ | ✘（引擎目录=安装目录，通常只读→except pass） | ✔ |
   | 打包游戏（安装目录可写） | ✔ | ✔ 写进 `游戏安装目录/输入配置.json` | ✘（该安装目录下换游戏会被带过去） |
   | 编辑器（EAI `key_binding` 命令 / 改键 UI） | ✔ 写`引擎目录/游戏设置.json`（见 P-01-07） | ✔ 写`引擎目录/输入配置.json` | ✘（引擎目录被所有游戏共享） |
   | 单元测试 `test_scripts.py:178` | ✔（除非重定向） | ✔ **改受跟踪文件** | ✘ |

   完备性：两处写都在 `rebind_action` 体内无条件执行（仅由异常控制），不存在"只在开发环境才写引擎配置"的判据（无 `frozen` / 环境变量 / is_dev 分支）→ 证伪失败。
4. **预期**：docstring 承诺"打包游戏的玩家改键只影响这个游戏，不污染引擎 输入配置.json"；且在任何环境下，改一个游戏的键不应写全局层。
5. **实际（实测）**
   ```
   ====== S12a rebind_action 键名校验 / 落盘 / 空列表语义 ======
   rebind_action(跳跃, ['f10']) -> ['f10']
     game json = {'跳跃': ['f10']}
     engine 配置写次数 = 1            ← 引擎层在同一调用里被写
   ```
   仓库现状旁证：`Loom/输入配置.json`（受跟踪）内容为 `跳跃: ["j"]`，而 `test_scripts.py:178` 正是 `eg.rebind_action('跳跃', ['j'])` —— 二者关系可由 `git grep -n "'j'" Loom/tests/test_scripts.py` 与 `git show HEAD:Loom/输入配置.json` 交叉核对；说明"跑一次现有测试就会改一个受跟踪文件"这条路径是真实存在的（本轮用 C2 重定向才没有再次改动它）。
6. **差异分析**：预期"只写游戏层"，实际"游戏层 + 全局层都写"。**多做了**一次全局落盘，并且这次落盘的目标是版本控制内的文件。差异方向明确、可观测。
7. **可复现验证**：`python Loom/tests/_tmp/beta3_scan_01_probe2.py`（S12a 段）；`git ls-files Loom/输入配置.json`；`git show HEAD:Loom/输入配置.json`。
8. **影响与等级**：**P2**（数据/配置污染 + 与自身 docstring 冲突；不崩不丢数据）。**是否由本轮 diff 引入：是**（基线 `rebind_action` 只调 `save_action_bindings`，本轮加了 `write_key_binding` 并改写 docstring）→ **[REGRESSION]**（就 docstring 与行为的自相矛盾而言）。
   **建议修复方向**：需要一个"运行环境身份"判据决定是否写全局层（打包运行时不写、编辑器可选写）；或干脆取消全局写，把"便于复用"改成显式的导出/导入动作。若保留全局写，至少要保证受跟踪的 `输入配置.json` 不被默认路径命中（改到用户数据目录）。

---

### P-01-06 · `get_action` 的大小写严格性 + 空列表挡住"回退同名键" ｜ **P-PROVED（P2）**

**【证伪链】结论: 证伪失败**

1. **判定基准**：`loom_input.py:191-194` docstring："输入动作查询 (Unity 动作层): 动作名 -> 绑定的任意键按下即 True … **未绑定动作时回退为同名键查询 (方便脚本直接写 'w')**"；`game_settings.py:70` 给出的合法写法示例是 `{"解锁鼠标": ["F10"], "向前": ["w", "Up"]}`。
2. **代码证据**：
   ```python
   def get_action(self, name):
       for k in self.actions.get(name, (name,)):    # ① 空列表 == 有值→不回退
           if self.script_keys.get(k, False):       # ② 键名精确匹配, 无 lower()/别名
               return True
       return False
   # script_keys 的键名集合 = _KEYMAP 的键名（loom_input.py:189 / loom_glfw_window.py:293-303）
   # _KEYMAP 里是大写 'F10'、小写 'space'、首字母大写 'Esc'/'PageUp'/'Tab'
   ```
3. **路径枚举表（get_action 的返回路径 × 绑定形态）**

   | 绑定形态 | 键名合法性 | 返回 | 是否疑似 |
   |---|---|---|---|
   | `['F10']` 且玩家按 F10 | 合法 | True | 否 |
   | `['f10']`（小写） | **不在 _KEYMAP** | False 且无任何告警 | **是**（SEM-DEFAULT） |
   | `'Space'` / `'ESC'` / `'Tab '（带空格）` | 不在 _KEYMAP | False，静默 | **是** |
   | `[]`（空列表） | — | False，且**跳过**回退 | **是**（与 docstring"未绑定→回退同名键"冲突：`actions['w']=[]` 时 `get_action('w')` 不再是 `is_key('w')`） |
   | 动作名不在 actions 里 | — | 回退按 **动作名本身**当键名查（`get_action('w')` == `is_key('w')`） | 否（与 docstring 一致） |

   完备性：`get_action` 只有这一个循环和两个返回点，无归一化、无 `_KEYMAP` 校验分支 → 证伪失败。
4. **预期**：`read_key_bindings`/`rebind_action` 接受 `'f10'` 这一输入后应等价于 `'F10'`（或至少拒绝并告知），因为 `_KEYMAP` 是"键名的唯一合法域"；`[]` 若表示"解绑"，则 docstring 的回退语义要改写。
5. **实际（实测，探针 S4/S5 系列；`probe3` 用**真实** script_keys 键名集合，不手工注入非法键名）**
   ```
   ======== S2 ... ========
   键名 'F10'   在 _KEYMAP? True
   键名 'f10'   在 _KEYMAP? False
   键名 'space' 在 _KEYMAP? True
   键名 'Space' 在 _KEYMAP? False

   （probe3 输出）
   全键按下的 script_keys 含 f10? False  含 F10? True  含 j? True
     get_action(跳跃  ) 绑 ['f10'] -> False
     get_action(向前  ) 绑 ['F10'] -> True
     get_action(交互  ) 绑 ['j']  -> True

   空列表绑定:
     get_action(跳跃) 绑 [] -> False (unbound fallback 走 actions.get(name, (name,)) -> 空列表挡住回退)
     is_key(跳跃) = False
   ```
   **伪证据更正（必须留痕）**：上一任 `beta3_scan_01_probe2.py` 的 S12a 段手工把 `{'f10': True}` 塞进 `script_keys` 后得到"小写 f10 也能命中"的结论；该注入在生产路径上不可能出现（`script_keys` 的键名恒来自 `_KEYMAP`），因此**该段输出不能作为判据**。本轮以 `probe3` 的写法为准（`script_keys` 只用 `_KEYMAP` 的真实键名）。
6. **差异分析**：预期"非法键名被拒绝或归一"，实际"静默不生效"（changes 了"绑定成功"的事实而不告知）；预期"未绑定回退同名键"，实际"空列表不回退"。两者都是方向明确的"少做了校验/多做了拦截"。
7. **可复现验证**：`python Loom/tests/_tmp/beta3_scan_01_probe3.py`；`python Loom/tests/_tmp/beta3_scan_01b_probe.py`（S2/S8 段）。
8. **影响与等级**：**P2**（静默默认；用户改键写错大小写 → 永久无效且无提示；`解锁鼠标` 若被写成 `["tab"]` 会让"最后逃生通道"静默失效——这条与 P-01-01 叠加后尤其危险，因为默认值恰好是对的，问题要等玩家真的改键才爆）。**是否由本轮 diff 引入：部分**——`get_action` 本体是既有代码，但本轮新增了**外部可写入口**（`game_settings` 的 key_bindings 与 `set_action_binding`），把"键名必须与 _KEYMAP 完全一致"这一隐性契约暴露给了玩家输入。
   **建议修复方向**：把 `_KEYMAP` 用成"键名校验器"：写入前归一/校验（大小写、别名如 `Space`/`space`），非法值拒绝或回落到旧值；`get_action` 对空列表的语义在文档里定案（"解绑"还是"回退"）并补测试。


---

### P-01-07 · `game_settings.game_dir()` 只认 argv[0] → 编辑器/开发播放器的"每游戏配置"落到引擎目录 ｜ **P-PROVED（P2）**

**【证伪链】结论: 证伪失败**

1. **判定基准**：接手总纲 §2.5 "配置文件：**游戏设置.json**，放在**游戏文件夹**（= MyGame.exe 同级）；可用环境变量 LOOM_GAME_DIR 覆盖（测试用）"；`game_settings.py:4-5` 同义 docstring；§3.4 优先级表把"游戏设置.json"作为**每游戏**最高层。
2. **代码证据**：
   ```python
   # game_settings.py:20-35
   def game_dir():
       d = os.environ.get("LOOM_GAME_DIR")
       if d and os.path.isdir(d):
           return d
       try:
           main = os.path.abspath(sys.argv[0])
           if main:
               return os.path.dirname(main) or os.getcwd()
       except Exception:
           pass
       return os.getcwd()

   def path():
       return os.path.join(game_dir(), FILE_NAME)
   ```
   全仓库 `grep -rn LOOM_GAME_DIR` 的**非文档**命中只有 `game_settings.py` 自身（实测），即**没有任何运行入口**（`Loom.py`、`editor.py`、`run_player.py`、`game_player.py`）为"当前打开的工程/场景"设置该变量。
3. **路径枚举表（谁会读到这份文件）**

   | 入口 | `sys.argv[0]` | `path()` 落点 | 是否等同"游戏文件夹" |
   |---|---|---|---|
   | 打包游戏 `MyGame.exe` | exe 全路径 | `MyGame.exe` 目录 | ✔ |
   | 编辑器（`LoomHub` → `Loom.py --agent --open`） | `<引擎>/Loom.py` | **引擎目录** | ✘（该引擎下所有工程共享） |
   | 开发播放 `python Loom.py --run Projects/X.json` | `<引擎>/Loom.py` | **引擎目录** | ✘ |
   | `build_game.py`（打包流程） | 脚本路径 | 引擎目录 | ✘（打包时不写配置，无实际影响） |
   | `LOOM_GAME_DIR` 显式设置 | 任意 | 环境变量目录 | ✔（仅测试/工具会用） |

   完备性：`game_dir()` 只有两个返回分支（环境变量 / argv[0]），之后 fallback `os.getcwd()`；无"当前工程目录"概念（编辑器不向本模块传递工程路径，`grep "game_settings" Loom/editor.py` 无命中）→ 证伪失败。
4. **预期**：编辑器里改键 / 改 render_api 应写到"当前打开的工程/游戏"目录，而不是所有工程共享的引擎目录。
5. **实际（实测，探针 C3 S12c：`LOOM_GAME_DIR` 清空后换 `argv[0]`）**
   ```
   ====== S12c 编辑器 / 场景运行时 游戏设置.json 的落点 ======
     argv[0]='Loom.py'                                            -> path()='D:\\my-project - 副本\\Loom(py源代码-工作区)\\游戏设置.json'
     argv[0]='D:\\my-project - 副本\\Loom(py源代码-工作区)\\Loom\\Loom.py' -> path()='D:\\my-project - 副本\\Loom(py源代码-工作区)\\Loom\\游戏设置.json'
     argv[0]='...\\Loom\\build_game.py'                             -> path()='...\\Loom\\游戏设置.json'
     argv[0]='C:\\Program Files\\Loom\\0.1.0\\Loom\\python\\python.exe' -> path()='C:\\Program Files\\Loom\\0.1.0\\Loom\\python\\游戏设置.json'
   ```
   仓库现状旁证：`Get-ChildItem -Recurse -Filter 游戏设置.json` 实测**零命中**——即打包进 beta3 的游戏（吃豆人）根本没有随包配置文件，所有键都走"默认"分支（这条同时支撑 P-01-15）。
6. **差异分析**：预期"每游戏一份"，实际"编辑器/开发播放器共用一份、且落在引擎安装目录"。**少做了**"当前工程目录"这一输入源。
7. **可复现验证**：`python Loom/tests/_tmp/beta3_scan_01_probe2.py`（S12c 段）；`Select-String -Path Loom\*.py -Pattern game_settings`（编辑器无引用）。
8. **影响与等级**：**P2**（配置语义错误：在编辑器里给 A 游戏改键会同时改变 B 游戏；`render_api` 同理，跨游戏串味）。**是否由本轮 diff 引入：是**（`game_settings.py` 为新增文件）→ **[REGRESSION]**（就"每游戏配置"这一声明而言）。
   **建议修复方向**：给 `game_settings` 增加"工程目录"输入（编辑器/run_player 在加载场景时设置，例如沿用 `LOOM_GAME_DIR` 或新增显式 setter），并明确优先级（显式工程目录 > exe 目录 > cwd）；同时把"覆盖为测试用"这句文档改成真实的三层语义。此条与 P-01-05 是同一根因的两个面，建议一并定案。

---

### P-01-08 · `_KEYMAP` 字面量 18 条重复键 + 注释与实际基数不符 ｜ **P-PROVED（P3）**

**【证伪链】结论: 证伪失败**

1. **判定基准**：`loom_input.py:94-95` 本轮新增注释 "键位表补全 (字母/数字/F1-F12/Esc/Enter/编辑键/标点)。**旧表只有 30 个键**"；接手总纲 §2.7 "键位表补全：**_KEYMAP 30 -> 76 键**"。
2. **代码证据**：`loom_input.py:16-24` 既有 `'w','s','a','d','q','e','i','k','j','l','u','o','1'..'6'`，`loom_input.py:25-60` 新增块又把 `a..z`、`0..9` 全写一遍（同一文件的同一个 dict 字面量）。
3. **路径枚举表**：Python 语义下 dict 字面量重复键 = 后者覆盖前者，**只有一个**运行时条目 → 有效条目 76；但**字面量**条目 94。两条"路径"（读代码的人 vs 运行时）对基数的认知不一致。
   - 运行时：`len(_KEYMAP)=76`（探针 S1 实测）。
   - 字面量：94 条，重复 18 条（探针 S1 实测）。
   - 基线：`git show f53a82a:Loom/loom_input.py` 的字面量 = 26 条（17 行内实测），**不是** 30。
4. **预期**：注释/文档的基数与实际一致；字面量无重复（重复即死条目）。
5. **实际（实测，探针 S1）**
   ```
   ======== S1 _KEYMAP 源码字面量重复键 (ast) 与运行时大小 ========
   字面量条目数 = 94 | 去重后 = 76 | 重复键 = 18
   重复键名单 = ['a', 'd', 'e', 'i', 'j', 'k', 'l', 'o', 'q', 's', 'u', 'w', '1', '2', '3', '4', '5', '6']
   运行时 len(_KEYMAP) = 76
   ```
6. **差异分析**：功能上无差异（重复项键值完全相同，覆盖后等价），但 ①18 条死条目会在后续维护中制造"改了上面那份、忘了下面那份"的分叉风险；②文档"30→76"的起点数字是错的（实际 26→76），会让后续审计按错误基线做差集。
7. **可复现验证**：`python Loom/tests/_tmp/beta3_scan_01b_probe.py`（S1 段）；`git show f53a82a:Loom/loom_input.py | Select-Object -First 30`。
8. **影响与等级**：**P3**（可维护性 / 文档失真；无运行时后果）。**是否由本轮 diff 引入：是**（新增块与旧块重复）→ 建议归类为 [REGRESSION] 的 P3 子项。
   **建议修复方向**：删掉 `loom_input.py:16-24` 里被新块完全覆盖的条目（或反之），把 `_KEYMAP` 改成按组排列的单一来源；把注释与文档的基数改成实测值。

---

### P-01-09 · `_GLFW_TO_PG` 80 项 vs `_KEYMAP` 76 键名 —— 文档"双向一一对应"表述过强 ｜ **P-DISPROVED（附 P3 文档修正）**

**【证伪链】结论: 证伪成功（反手链覆盖全部 76 个键名 + 双向集合数学）**

1. **判定基准**：接手总纲 §4 "loom_glfw_window.py ｜ _GLFW_TO_PG 重建（80 项，**与 _KEYMAP 全量对齐**）"；变更清单 §G bdf67ee "重建 80 项对齐"；`loom_glfw_window.py:51` 注释 "覆盖 loom_input._KEYMAP 全部键 + 引擎快捷键"。
2. **代码证据**：`loom_glfw_window.py:52-83` 的 80 条映射；`loom_input.py:15-93` 的 76 个唯一键名。
3. **路径枚举表（"某个 _KEYMAP 键名能否被 GLFW 物理状态点亮"）**

   两条真实构建路径：
   - 路径 A（`InputMixin.sync_script_keys`，`loom_input.py:189`）：`{name: bool(_kp[k]) for name, k in _KEYMAP.items()}`，`_kp` 由 `_key_pressed()`（`loom_input.py:161-173`）遍历 `_GLFW_TO_PG` 填充 **pygame 码**。
   - 路径 B（`GlfwWindowMixin._handle_events`，`loom_glfw_window.py:293-303`）：遍历 `_KEYMAP.items()` → `_PG_TO_GLFW.get(pg)` → `glfw.get_key`。

   实测集合数学（探针 S2）：
   ```
   len(_KEYMAP)=76 len(_GLFW_TO_PG)=80 len(_PG_TO_GLFW)=80
   _KEYMAP 键名 -> pygame 码 唯一? True | pygame 码数 = 76
   _KEYMAP 有码但 _GLFW_TO_PG 无 (GLFW 路径永远 False): none
   _GLFW_TO_PG 有码但 _KEYMAP 无 (多出来的): ['1073742050', '1073742052', '1073742053', '1073742054']
   _PG_TO_GLFW 与 _GLFW_TO_PG 互为单射? True
   _KEYMAP 键名 GLFW 可达 (经 _PG_TO_GLFW) 缺失名单: none
   ```
   逐条结论：
   - 76 个键名 → 76 个互不相同的 pygame 码 → 全部在 `_GLFW_TO_PG` 里出现（差集空）→ 没有任何键名在 GLFW 路径上"永远 False"。
   - 多出的 4 个码 = `K_LALT(1073742050)`、`K_RCTRL(1073742052)`、`K_RSHIFT(1073742053)`、`K_RALT(1073742054)`——它们**没有**对应的 `_KEYMAP` 键名（`_KEYMAP` 只有 `Shift`→K_LSHIFT、`Ctrl`→K_LCTRL，无 Alt）。
   - 反查表单射（80↔80），说明没有"两个 GLFW 键抢同一个 pygame 码"的覆盖。
   - 路径 A 与路径 B 的键名集合实测相同（`probe3` 输出 "script_keys 真实键名集合大小 = 76 | GLFW 路径同集合? True"）。
4. **预期**：文档说"80 项与 _KEYMAP 一一对应"。**实际**：76 个键名 ↔ 80 条 GLFW 映射，多出的 4 条是引擎**不暴露给脚本**的码（左 Alt / 右 Ctrl / 右 Shift / 右 Alt）。因此"一一对应"不成立，但**功能上无缺失**（没有任何"配了键却按不动"的键名）。
   → 疑似项描述的"双向一一对应被破坏"被**推翻**：破坏的是"措辞"，不是"能力"。
5. **正手尝试（证真"存在键名按不动"）**：构造"某个 _KEYMAP 键名在 GLFW 路径上恒 False"的反例 → 需要 `_KEYMAP 的值 ∉ _GLFW_TO_PG 的值`，实测该差集为空集，最小复现构造失败 → 证真失败。
6. **差异分析**：仅文档措辞与实测基数不一致（80 vs 76 名），无行为差异。
7. **可复现验证**：`python Loom/tests/_tmp/beta3_scan_01b_probe.py`（S2 段）。
8. **影响与等级**：**P-DISPROVED**（无 BUG）；遗留 **P3 文档修正**：把"80 项与 _KEYMAP 全量对齐/一一对应"改成"80 条 GLFW→pygame 映射，覆盖 _KEYMAP 全部 76 个键名 + 4 个未暴露修饰键（LALT/RCTRL/RSHIFT/RALT）"。
   注：`Ctrl`/`Shift` 只映射左侧（右手 Ctrl/Shift 不触发动作）是**基线既有**行为（`git show f53a82a` 同为 `glfw.KEY_LEFT_CONTROL/LEFT_SHIFT` 单侧），不属于本轮回归。

---

### P-01-10 · `_poll_mouse_unlock_key()` 插在 docstring 之前 → 两个函数的 `__doc__` 退化为 `None` ｜ **P-PROVED（P3）**

**【证伪链】结论: 证伪失败**

1. **判定基准**：Python 语言规范（文档字符串必须是函数体**第一条语句**）+ 本仓库既有约定（几乎每个函数首行都是 docstring，`loom_input.py` 全篇如此）。
2. **代码证据**：
   ```python
   # engine.py:934-936
   def update_scripts(self, delta_time):
       self._poll_mouse_unlock_key()          # ← 插在 docstring 之前
       """播放期每帧调用: ..."""

   # scene_driver.py:970-972 同形
   def _update_scripts(self, dt):
       self._poll_mouse_unlock_key()
       """复刻 engine.GLEngine.update_scripts: ..."""
   ```
3. **路径枚举表**：函数体的执行路径不受影响（语句顺序仍是 poll → 后续逻辑）；受影响的只有 `__doc__`（恒为 `None`）与人类/AI 阅读时的"第一段文字才是契约"约定。无第二条路径。
4. **预期**：`update_scripts.__doc__` 应为那段"播放期每帧调用…"的说明。
5. **实际（实测，探针 S6）**
   ```
   ======== S6 update_scripts 的 docstring 被语句挤掉 ========
   GLEngine.update_scripts.__doc__ = None
   SceneDriver._update_scripts.__doc__ = None
   ```
6. **差异分析**：预期非空文档，实际 `None`。**少做了**文档（代码行为不受影响）。
7. **可复现验证**：`python Loom/tests/_tmp/beta3_scan_01b_probe.py`（S6 段）；或 `python -c "import sys;sys.path.insert(0,'Loom');import engine;print(repr(engine.GLEngine.update_scripts.__doc__))"`。
8. **影响与等级**：**P3**（可维护性 / 自文档能力：一个"每帧关键路径"的函数失去了契约描述，后续审计只能靠注释推断）。**是否由本轮 diff 引入：是** → [REGRESSION]（P3）。
   **建议修复方向**：把 poll 移到 docstring 之后（例如函数体第二条语句），或在 docstring 内补一句"本函数每逻辑帧检测解锁键"。

---

### P-01-11 · `read_key_bindings` 对坏类型静默丢弃、`None` 变成键名 `'None'` ｜ **P-PROVED（P3）**

**【证伪链】结论: 证伪失败**

1. **判定基准**：`game_settings.py:88-89` docstring "读本游戏的键位覆盖 {动作: [键...]}; **无/坏 -> {}**"（即"坏值退化为默认"，是显式契约）；`_scan_summary.md` §6 Q4（场景类输入不要求全量防御）。
2. **代码证据**：
   ```python
   # game_settings.py:88-99
   d = load().get("key_bindings")
   if not isinstance(d, dict):
       return {}
   out = {}
   for a, ks in d.items():
       if isinstance(ks, str):
           out[str(a)] = [ks]
       elif isinstance(ks, (list, tuple)):
           out[str(a)] = [str(k) for k in ks if str(k)]     # ← None -> 'None' 被保留
   return out
   ```
3. **路径枚举表（key_bindings 的取值形态 → 输出）**

   | 输入形态 | 输出 | 是否符合"坏 -> 默认" |
   |---|---|---|
   | `['向前']`（整体不是 dict） | `{}` | ✔ |
   | `{'向前': 5}` / `{'向前': None}` / `{'向前': {'a':1}}` | `{}`（该动作被丢） | ✔（但无告警） |
   | `{'向前': ['w', None, '']}` | `{'向前': ['w', 'None']}` | **✘**（`None` 变成字符串键名 `'None'`，`''` 被丢） |
   | `{'向前': 'w'}` | `{'向前': ['w']}` | ✔（字符串按单键处理） |
   | `{'向前': ['f10']}` | `{'向前': ['f10']}` | 保留非法键名（与 P-01-06 叠加） |
   | 整份 JSON 损坏 | `{}` | ✔（docstring 明示，SKIP-03） |

4. **预期**：非字符串元素应被过滤（而不是 `str()` 化后当作键名）；非法键名应被拒。
5. **实际（实测，探针 S8）**
   ```
   ======== S8 read_key_bindings 对坏类型/非法键名的处理 ========
     ['向前']                                     -> {}
     {'向前': 5}                                  -> {}
     {'向前': None}                               -> {}
     {'向前': ['w', None, '']}                    -> {'向前': ['w', 'None']}
     {'向前': 'w'}                                -> {'向前': ['w']}
     {'向前': ['f10']}                            -> {'向前': ['f10']}
     {'向前': {'a': 1}}                           -> {}
   坏 JSON:
     load() = {}  read_key_bindings() = {}  read_bool(x,True) = True
   ```
6. **差异分析**：`None` 这一种坏值被**多做**了一次字符串化，产生一个永不可能被按下的键名 `'None'`；其余坏值按契约回落。
7. **可复现验证**：`python Loom/tests/_tmp/beta3_scan_01b_probe.py`（S8 段）。
8. **影响与等级**：**P3**（静默默认，O(1) 影响面：只有手写坏 JSON 的开发者会遇到）。**是否由本轮 diff 引入：是**（新文件）。
   **建议修复方向**：过滤规则改成"只保留 `isinstance(k, str) and k in _KEYMAP`"，并对整条被丢弃的绑定打印一条告警（配合 P-01-06 的校验器）。

---

### P-01-12 · 解锁动作默认 Tab 与编辑器既有 Tab/F10 语义冲突 ｜ **P-PROVED（P2）**

**【证伪链】结论: 证伪失败**

1. **判定基准**：接手总纲 §2.6 "强制解锁键：动作名 解锁鼠标（**默认 Tab**）"；`game_settings.py:70` 的示例 " `{"解锁鼠标": ["F10"]}` "。同时"本轮未改动编辑器快捷键"是本轮 diff 的隐含约束（`git diff` 不含 `editor.py` 的按键段）。
2. **代码证据**：
   ```python
   # loom_input.py:104
   '解锁鼠标': ['Tab'],
   # loom_input.py:134 / 313（KEY_BINDINGS, 既有）
   'SELECT_NEXT_MODEL': 'Tab',
   # editor.py:2198-2200（既有, 无播放态门禁）
   if ev.key == pygame.K_TAB and self.models:
       self.selected_index = (self.selected_index + 1) % len(self.models)
       return True
   # editor.py:2188-2191（既有）
   if ev.key == pygame.K_F10:
       if self.step_logic_once(): ...
       return True
   ```
3. **路径枚举表（在编辑器里按一次 Tab）**

   | 运行态 | `on_key_event`（事件流） | `script_keys`（轮询流） | `_poll_mouse_unlock_key` | 净效果 |
   |---|---|---|---|---|
   | 编辑态 | 切换选中物体（`return True`） | 更新 `script_keys['Tab']=True` | 不跑（无逻辑帧） | 只切选中 ✔（无冲突） |
   | 播放态 + 有 fps 脚本 | 切换选中物体 | True | 跑，但与脚本双翻转（P-01-02） | 选中跳变 + 不解锁 ✘ |
   | 播放态 + 无 fps 脚本 | 切换选中物体 | True | 跑，解锁 | 选中跳变 + 解锁（两个副作用） ✘ |

   完备性：两条流（事件流 / 轮询流）互相独立，`return True` 只影响事件流，不阻止轮询流读取物理键状态 → 冲突不可避免。
   同一形状的冲突还有 `F10`：`game_settings.py:70` 把 `["F10"]` 写成"改键示例"，而 `editor.py:2188` 用 F10 步进一帧 —— 若开发者照抄该示例，在编辑器里按 F10 会"解锁鼠标 + 步进一帧"。
4. **预期**：新增的保留动作键不应与既有编辑器保留键重叠，或至少文档要声明"该键在编辑器内会同时触发编辑器快捷键"。
5. **实际（静态证据 + 实测产物）**：`grep -n "SELECT_NEXT_MODEL\|K_TAB" Loom/editor.py Loom/loom_input.py` 实测命中 `editor.py:2198`、`loom_input.py:134/313`；`loom_input.py:104` 新增 `['Tab']`。播放态"选中跳变"这一副作用在探针 S5 的同帧序列里没有被消除（`on_key_event` 与 poll 互不知情）。
6. **差异分析**：预期"解锁键独占"，实际"与编辑器 Tab 共享 + 与 F10 示例共享"。**少做了**键位域冲突检查。
7. **可复现验证**：`Select-String -Path 'Loom\editor.py' -Pattern 'K_TAB|K_F10'`；`Select-String -Path 'Loom\loom_input.py','Loom\game_settings.py' -Pattern "解锁鼠标|SELECT_NEXT_MODEL"`。
8. **影响与等级**：**P2**（用户可感知的交互污染；不崩）。**是否由本轮 diff 引入：是**（新增默认绑定）→ [REGRESSION]。
   **建议修复方向**：给"引擎保留动作键"划一个不与编辑器快捷键重叠的默认（例如无默认绑定 + 启动时提示，或默认 Esc 之外的自定义键），并在文档里列出"编辑器内会双触发"的已知清单；同时给 `on_key_event` 增加"播放态是否让位给游戏输入"的判据。


---

### P-01-13 · 每帧成本：poll 0.494 µs / 键盘快照 76 键 ~17 µs ｜ **P-DISPROVED（成本可忽略，留实测基线）**

**【证伪链】结论: 证伪成功（量化后确认不构成性能问题）**

1. **判定基准**：SCAN_PROTOCOL §2 "重点（不限于）：每帧 _poll_mouse_unlock_key 的成本"；接手总纲 §7 曾把"+6.44ms/帧"判为必修（说明本项目的性能门槛是**毫秒级**）。
2. **代码证据**：`engine.py:882-908`（poll = 1 次 `get_action` + 2 次 `getattr`）；`loom_glfw_window.py:293-303`（每帧 76 次 `dict.get` + 76 次 `glfw.get_key`）。
3. **路径枚举表**

   | 路径 | 每帧工作量 | 实测 |
   |---|---|---|
   | 允许锁定（默认） | 1 次 `get_action('解锁鼠标')` ≈ 1 dict + 1 列表遍历 | **0.494 µs/次** |
   | 不允许锁定 + 已处于解锁 | 同上 1 次 `get_action` + 2 次 getattr（`mouse_locked` 为 False，不调 `set_mouse_locked`） | 0.216 µs/次（不调 set 的分支） |
   | 键盘快照（`_handle_events`） | 76 键 × (dict.get + 状态写) + 76 次 `glfw.get_key` | 纯 Python 部分 **16.96~18.80 µs/帧** |
4. **预期**：单帧增量应远小于 1 ms。
5. **实际（实测，探针 S9/S11）**
   ```
   ======== S9 _poll_mouse_unlock_key 每帧成本 ========
   200000 次调用耗时 0.099 s -> 单次 0.494 us
   200000 次调用耗时 0.043 s -> 单次 0.216 us

   ======== S11 76 键轮询的纯 Python 部分开销 (不含 glfw.get_key) ========
   20000 帧 x 76 键 -> 0.376 s, 单帧纯 Python 18.80 us (glfw.get_key 另计)
   （二次复跑: 0.339 s / 16.96 us）
   ```
6. **差异分析**：0.494 µs + ~17 µs ≈ **0.017 ms/帧**，占 60 FPS 帧预算（16.7 ms）的 0.1%；相对基线（26 键）增加约 +12 µs/帧，比 §7 里"必修级"的 6.44 ms 小两个数量级。
7. **可复现验证**：`python Loom/tests/_tmp/beta3_scan_01b_probe.py`（S9/S11 段）。
8. **影响与等级**：**P-DISPROVED**（不构成缺陷）。`glfw.get_key` 的 76 次原生调用成本无法在本沙箱测（无窗口），单列为 **P-01-UN-1**。

---

### P-01-14 · GL 侧 rebind 写引擎配置、VK 侧不写 ｜ **P-PROVED（P3）**

**【证伪链】结论: 证伪失败**

1. **判定基准**：接手总纲 §2.6 与 §3.4 把"键位"作为**一套**语义描述，未区分后端；§"多后端一致性"是 SCAN_PROTOCOL §2 的专项。
2. **代码证据**：
   ```python
   # loom_input.py:279-290（GL）: 写游戏配置 + 写引擎配置
   # scene_driver.py:937-946（VK）: 只写游戏配置
   def rebind_action(self, name, keys):
       keys = list(keys)
       self.actions[name] = keys
       try:
           import game_settings
           game_settings.write_key_binding(name, keys)
       except Exception as e: ...
       return keys                      # ← 无 save_action_bindings
   ```
3. **路径枚举表**

   | 后端 | 立即生效 | 写 游戏设置.json | 写 引擎 输入配置.json |
   |---|---|---|---|
   | GL（InputMixin.rebind_action） | ✔ | ✔ | ✔ |
   | VK（SceneDriver.rebind_action） | ✔ | ✔ | ✘ |

4. **预期**：同一 `set_action_binding` API 在两个后端的落盘面应一致（否则"改键后换后端启动"行为会分叉）。
5. **实际（实测，探针 C3 S12d；S12a 的 engine 写次数=1 为上表 GL 侧）**
   ```
   ====== S12d VK 侧 rebind_action 与 GL 侧落盘差异 ======
   driver.rebind_action(跳跃, ['i']) -> ['i']
     game json = {'跳跃': ['i']}
   driver.set_action_binding('向前', ['i']) = {'ok': True, 'action': '向前', 'keys': ['i'], 'saved': True}
     game json = {'跳跃': ['i'], '向前': ['i']}
   ```
6. **差异分析**：GL **多做了**一次全局落盘。就"改键只影响本游戏"的意图而言，VK 侧更接近意图；就"开发环境复用"的意图而言，GL 侧才符合。两者不可能同时正确 → 需要定案（与 P-01-05 同源）。
7. **可复现验证**：`python Loom/tests/_tmp/beta3_scan_01_probe2.py`（S12a + S12d 段）。
8. **影响与等级**：**P3**（跨后端行为分叉，不影响单后端内的可用性）。**是否由本轮 diff 引入：是**（两侧都是本轮新增）。

---

### P-01-15 · `mouse_lock_allowed/mouse_locked` 默认 True/True 是否破坏旧场景 ｜ **P-DISPROVED（默认行为与基线逐位相同）**

**【证伪链】结论: 证伪成功**

1. **判定基准**：SCAN_PROTOCOL §2 "默认值改变导致的旧场景行为变化（相机、光照、材质、LOD）"；接手总纲 §3.4 "鼠标锁定 ｜ 游戏设置.json mouse_lock_allowed / mouse_locked > **默认(允许+锁定)**"。
2. **代码证据**（本模块侧）：`game_settings.py:73-74` `MOUSE_LOCK_ALLOWED_DEFAULT = True / MOUSE_LOCK_INITIAL_DEFAULT = True`；`129-133` `mouse_lock_initial()` 在不允许锁定时恒 False；`engine.py:383` 引擎基类 `mouse_locked = False`（编辑态不锁）。
   **基线对照**（`git diff f53a82a..HEAD -- Loom/runtime.py` 实测）：
   ```
   -        # M39: 播放器默认锁定鼠标 ...
   -        self.set_mouse_locked(True)
   +        try:
   +            import game_settings as _gs
   +            self.mouse_lock_allowed = bool(_gs.mouse_lock_allowed())
   +            _lock0 = bool(_gs.mouse_lock_initial())
   +        except Exception:
   +            self.mouse_lock_allowed, _lock0 = True, True
   +        self.set_mouse_locked(_lock0)
   ```
3. **路径枚举表（GL 播放器启动时的锁定状态）**

   | 情况 | 基线 | 现在 | 是否变化 |
   |---|---|---|---|
   | 无 游戏设置.json（= 仓库现状，实测零命中） | 锁 | `mouse_lock_initial()` → True → 锁 | **无** |
   | `mouse_lock_allowed=false` | （无此能力）锁 | 不锁 | 变（新增能力，符合 §2.6 意图） |
   | `mouse_locked=false` | 锁 | 不锁 | 变（新增能力） |
   | 配置损坏 | — | `{}` → True/True → 锁 | 无 |
   | 编辑器（编辑态） | 不锁 | 不锁（`engine.py:383`） | 无 |

   VK 侧同理（`git diff ... Loom/vk_player.py` 实测基线为 `driver.set_mouse_locked(True)`，现在同样默认 True）。
4. **预期**：默认值改变不应让旧场景行为变化。**实际**：默认值 = 基线值，旧场景行为不变；新增的只有"可显式关掉"的能力。
5. **正手尝试（证真"旧场景被破坏"）**：需要找到一条"基线锁 / 现在不锁"或"基线不锁 / 现在锁"的路径 → 上表两个方向的差集都为空（除显式配置项，那是新能力）→ 证真失败。
6. **差异分析**：无行为差异；仅新增 opt-out 通道。
7. **可复现验证**：`git diff f53a82a..HEAD -- Loom/runtime.py Loom/vk_player.py | Select-String mouse_lock -Context 3,8`；`Get-ChildItem -Recurse -Filter 游戏设置.json`（零命中）。
8. **影响与等级**：**P-DISPROVED**。附注：正因为"旧游戏一律锁鼠标"，P-01-01/P-01-02/P-01-04 三条命中后玩家**没有第二条逃生通道**（Tab 是唯一手段），这也是把它们排在前面的原因。

---

### P-01-16 · `_load_action_bindings` 里一条坏条目 → 整份文件绑定被丢弃 ｜ **P-PROVED（P3，当前被 P-01-01 掩盖）**

**【证伪链】结论: 证伪失败**

1. **判定基准**：`loom_input.py:247` docstring "从 输入配置.json 加载动作绑定（**坏文件**回退默认）"——契约说的是"坏文件"，不是"坏条目"。
2. **代码证据**：
   ```python
   try:
       data = _json.load(f)
       if isinstance(data, dict) and data.get('actions'):
           self.actions = {a: list(ks) for a, ks in data['actions'].items()}   # ← list(5) 抛 TypeError
           for a, ks in DEFAULT_ACTIONS.items():
               self.actions.setdefault(a, list(ks))
   except Exception:
       self.actions = dict(DEFAULT_ACTIONS)                                     # ← 整份丢弃
   ```
3. **路径枚举表（单条目取值形态 × 结果）**

   | `actions` 里有 | 结果 |
   |---|---|
   | 全部是列表/字符串 | 逐条加载 ✔ |
   | 任一条是数字/None/dict（不可迭代） | 该条 `list()` 抛 → **全部动作**回退 `DEFAULT_ACTIONS` |
   | `actions` 整体不是 dict | `data.get('actions')` 为真 list → `.items()` 抛 → 同上 |

4. **预期**：一条坏条目只应影响它自己（其余条目按契约加载）。
5. **实际（实测，探针 S12：把 `apply_game_bindings` 临时补成空实现以隔离 P-01-01）**
   ```
   ======== S12 _load_action_bindings: 单条坏条目导致整份文件绑定被丢弃 ========
     cfg={'跳跃': ['j'], '交互': ['e']}                     -> 跳跃=['j'] 交互=['e'] err=None
     cfg={'跳跃': ['j'], '交互': 5}                         -> 跳跃=['space'] 交互=['e'] err=None   ← 跳跃被连带丢弃
     cfg={'跳跃': ['j'], '交互': ['e']}                     -> 跳跃=['j'] 交互=['e'] err=None
   ```
6. **差异分析**：预期"只丢坏条目"，实际"整份文件被丢且无任何提示"（`err=None` 说明异常被内部吃掉）。**多做**了一次全量回退。
7. **可复现验证**：`python Loom/tests/_tmp/beta3_scan_01b_probe.py`（S12 段）。
8. **影响与等级**：**P3**（当前被 P-01-01 完全掩盖——反正整体必回退；修好 P-01-01 后会立刻变成可达的真实静默失败）。**是否由本轮 diff 引入：否**（`git show f53a82a` 同形），但本轮新增的 `set_action_binding` 让玩家更容易在文件里写出坏值，风险面扩大。
   **建议修复方向**：逐条目 try（一条坏值只跳过该条），并对被跳过的条目打一条告警。

---

## 2.1 P-UNKNOWN（信息不足，需补充探针/实机）

### P-01-UN-1 · 76 键 `glfw.get_key` 的真实每帧成本
- **已尝试**：探针 S11 量到纯 Python 部分 16.96~18.80 µs/帧；`glfw.get_key` 需要**活的 GLFW 窗口**（本沙箱按 SCAN_PROTOCOL §0-5 不启动 GUI）。
- **还缺什么**：一次带窗口的真机帧剖析（如对 `GlfwWindowMixin._handle_events` 做 `time.perf_counter` 采样），用于确认 76 次原生调用是否引入可见帧尖刺。
- **判定所需**：只要 `glfw.get_key` 单次 < 1 µs（76 次 < 0.08 ms），即可归为 P-DISPROVED。

### P-01-UN-2 · 打包版（Nuitka standalone）下 `argv[0]` 是否等于 exe 路径
- **已有证据**：`game_player.py:28` 用同一表达式 `os.path.dirname(os.path.abspath(sys.argv[0]))` 定位 `日志.txt`，而 §5 记录"打包版运行日志在 游戏目录 日志.txt"（现场已跑通）→ 强烈倾向成立。
- **还缺什么**：打包版运行后 `Get-ChildItem <游戏目录> -Filter 游戏设置.json` 的一次实机取样（需要 Nuitka 构建 + 运行，超出本沙箱时间预算）。
- **影响**：只影响 P-01-07 的"打包版一侧正确"这一半结论；编辑器一侧已由探针直接实测。

### P-01-UN-3 · 编辑器里"改键/改 render_api"应该落到哪
- **已有证据**：探针 S12c 证明落点是引擎目录；仓库内没有任何"工程目录"传递通道（`grep LOOM_GAME_DIR` 仅命中 game_settings 自身）。
- **还缺什么**：这是产品语义（不是代码事实）——"编辑器改键是否应写进工程目录"属于人类裁决，见 §5 Q2。已尝试用 `game_settings.py` docstring 与接手总纲 §2.5 交叉判定，两侧都只覆盖"打包游戏"，未定义编辑器语义 → 判 P-UNKNOWN 而不是 P-PROVED 的 BUG。


---

## 3. 统计

### 3.1 四象限与分级

| 判定 | 数量 | 编号 |
|---|---|---|
| **P-PROVED** | **13** | P-01-01/02/03/04/05/06/07/08/10/11/12/14/16 |
| **P-DISPROVED** | **3** | P-01-09（80 vs 76 措辞）、P-01-13（每帧成本）、P-01-15（鼠标锁定默认值） |
| **P-UNKNOWN** | **3** | P-01-UN-1（glfw.get_key 真机成本）、UN-2（Nuitka argv[0]）、UN-3（编辑器落点语义） |
| **P-CONTRADICTION** | **0** | 见下解释 |
| 合计 | 19 个判定 = §1.1 的 16 条疑似项 + §2.1 追加的 3 条信息不足项 | — |

**P-CONTRADICTION = 0 的解释**：本模块每条疑似项都收敛到单向结论。两处"证伪成功后仍去证真"的项（P-01-09、P-01-15）都**证真失败**（差集为空 / 无反例路径），没有出现"两条链同时成立"。逐条已给出路径枚举表，最可能出问题的 P-01-09 用集合数学（76 名 ∩ 80 码）做了穷举而非抽样。

### 3.2 等级分布

| 等级 | 数量 | 编号 |
|---|---|---|
| **P0** | 1 | P-01-01 |
| **P1** | 2 | P-01-02、P-01-03 |
| **P2** | 5 | P-01-04、P-01-05、P-01-06、P-01-07、P-01-12 |
| **P3** | 5 | P-01-08、P-01-10、P-01-11、P-01-14、P-01-16 |

### 3.3 [REGRESSION] 清单（本轮 diff 引入，8 条）

| 编号 | 等级 | 位置 | 一句话 |
|---|---|---|---|
| P-01-01 | P0 | loom_input.py:261 / engine.py:389-392 | `apply_game_bindings` 无定义 → 三层键位优先级全军覆没 + 既有回归测试断在 188 行 |
| P-01-02 | P1 | engine.py:897-899 vs scripts.py:642-645/701-704 | 同帧双翻转 → fps 场景里解锁键净无效 |
| P-01-03 | P1 | engine.py:919-931 / loom_input.py:281-289 | 写盘失败仍返回 `saved=True` |
| P-01-05 | P2 | loom_input.py:279-290 | 改键双写，含受跟踪的引擎 `输入配置.json`，与自身 docstring 冲突 |
| P-01-07 | P2 | game_settings.py:20-31 | 编辑器/开发播放器的"每游戏配置"落到引擎目录 |
| P-01-08 | P3 | loom_input.py:15-93 | `_KEYMAP` 字面量 18 条重复键；注释"30 键"与基线 26 键不符 |
| P-01-10 | P3 | engine.py:934-936 / scene_driver.py:970-972 | 两处 `__doc__` 被前置语句挤成 `None` |
| P-01-12 | P2 | loom_input.py:104 / editor.py:2188,2198 | 默认解锁键 Tab / 示例键 F10 与编辑器保留键冲突 |

另有 3 条"新文件 + 新增 API"引入的 P2/P3（P-01-04 属接口缝、P-01-11 / P-01-14 属新增代码），未加 [REGRESSION] 标签。

### 3.4 跳过项与处决统计

粗筛 16 项 / 跳过 7 项（SKIP-01..07，均有四类理由之一 + 出处）。跳过项中没有一条以不可审计的自我状态为依据（判据见 §1.2 每行的"具体事实 / 出处"列）。

---

## 4. 修复建议排序（只给方向，不含可直接替换的完整实现）

| 顺序 | 编号 | 等级 | 方向（一句话） | 为什么排这个位置 |
|---|---|---|---|---|
| 1 | P-01-01 | P0 | 补 `apply_game_bindings` 或删调用点，并把"游戏层覆盖"放进**独立**的 try（状态层：一层坏不能拖垮另一层） | 一条 AttributeError 废掉本轮全部改键交付 + 让既有测试静默断链 |
| 2 | P-01-02 | P1 | 解锁键必须有单一所有者；删掉一方的"边沿翻转"或加"本帧已消费"标志 | 交付目标在 fps 场景 100% 失效 |
| 3 | P-01-03 | P1 | 让 `rebind_action` 把落盘结果返回给 `set_action_binding`，`saved` 反映真实结果（区分 game/engine 两级更好） | 玩家会得到"已保存"的假承诺，重启即失效 |
| 4 | P-01-05 + P-01-07 | P2 | "配置落点"一次定案：环境身份判据（打包/编辑器/测试）+ 当前工程目录通道；默认路径别再命中受跟踪文件 | 同一根因，分开改会互相打回 |
| 5 | P-01-04 | P2 | poll 从"逻辑帧"上移到"渲染帧输入段"，与暂停解耦 | 暂停面板是最需要鼠标的时刻 |
| 6 | P-01-06 + P-01-11 | P2/P3 | 用 `_KEYMAP` 当键名校验器（归一/拒绝非法名），并对被丢弃的绑定告警；`None` 不要字符串化 | 与第 4 项一起做可省一次出厂格式变更 |
| 7 | P-01-12 | P2 | 解锁动作默认键位与"编辑器保留键"错开，或文档声明双触发清单 | 交互污染，用户可直接感知 |
| 8 | P-01-08 + P-01-10 | P3 | 去重 `_KEYMAP`；poll 挪到 docstring 之后 | 纯可维护性，零风险 |
| 9 | P-01-14 | P3 | 两侧 rebind 落盘面统一（等第 4 项定案后顺手对齐） | 依赖第 4 项结论 |
| 10 | P-01-16 | P3 | 逐条目 try，一条坏值只跳过该条 | 修好第 1 项后才会暴露 |

**不要顺手改的东西**：`_GLFW_TO_PG` 的 80 项（P-01-09 已证伪，改它只会引入风险）；`set_mouse_locked` 的 GLFW 分支（SKIP-01，未改且已被测试覆盖）。

---

## 4.1 动手前需确认的点（避免"改了 A 打回 B"）

1. **`apply_game_bindings` 是"漏写定义"还是"多写调用"**——决定改 `loom_input.py` 还是 `game_settings.py`。仓库里唯一的"意图证据"是接手总纲 §4 把它列在 `loom_input.py` 的改动要点里，但没有给出方法签名与返回值。
2. **"解锁意图"的单一所有者**（引擎 poll / 脚本 / 二者协商）——这决定 P-01-02 的修法，并且会影响 `scripts.py`（不在本模块 diff 内，改动面要事先获批）。
3. **引擎 `输入配置.json` 是否保留为全局层**——它当前是**受跟踪文件**且内容已被一次 `rebind_action` 改写过（`跳跃:["j"]`）。若继续保留，需要同时决定"测试如何不污染工作树"（本轮用 `LOOM_GAME_DIR` 重定向只是审计侧权宜）。
4. **编辑器侧的"当前工程目录"从哪里来**——`editor.py` 目前完全不引用 `game_settings`（`Select-String` 无命中），新增通道会动到本模块之外的文件。
5. **`mouse_lock_allowed` 是否需要运行时热切换**——现在只在启动时读一次（`runtime.py:78-84` / `scene_driver.py:468-474`）；若产品上要求"玩家在设置面板里当场关掉锁定"，需要额外一条重读路径。
6. **键名合法域是否就是 `_KEYMAP` 的 76 个名字**（是否要接受 `Space`/`space` 这类别名，以及 `RightShift` 这种"物理键有、动作层没有"的键）。
7. **本报告中的行号均以 HEAD=`62479f0` 为准**；若先修了 P-01-01，其后所有 `loom_input.py` 行号会整体下移，需重新对齐。

---

## 5. 需要人类裁决的封闭问题

**Q1（P-01-01 修法）**：`_load_action_bindings` 末尾的 `apply_game_bindings()` 应采用哪条路线？
- **A**：补上该方法（读 `game_settings.read_key_bindings()` 按动作覆盖），保留文档声明的三层优先级。
- **B**：删掉该调用，把"游戏层覆盖"直接写进 `_load_action_bindings` 的独立 try 里。
- **C**：两层都不在启动时合并，改为"查询时优先读游戏层"（`get_action` 内联查找）。
- 代价：A 最贴合文档但多一个公开方法；B 最小改动但方法语义会藏在加载函数里；C 每帧多一次查找（实测单次 0.5 µs 量级，代价可接受）。

**Q2（P-01-05 + P-01-07 落点）**：键位与 `render_api` 在**编辑器**里应写到哪？
- **A**：引擎目录（现状）——所有工程共享一份。
- **B**：当前打开的工程目录——需要编辑器把工程路径传给 `game_settings`。
- **C**：用户数据目录（如 `%APPDATA%\Loom\<工程名>\游戏设置.json`）——不碰工程目录也不碰引擎目录，但玩家/开发者要多知道一个位置。
- 代价：A 省事但会串味；B 最符合"每游戏配置"但改动最大；C 最安全但偏离"放在游戏文件夹"这句文档。

**Q3（P-01-02 + P-01-12 解锁键归属）**：`解锁鼠标` 这个引擎保留动作的归属与默认键位？
- **A**：引擎独占 + 默认保持 Tab（同时删掉 first/third_person 里的 Tab 分支，接受"编辑器里按 Tab 会同时切选中"）。
- **B**：引擎独占 + 默认改成不与编辑器冲突的键（例如 `F12`/`Esc` 之外的组合），文档同步。
- **C**：脚本优先（有 fps 脚本时引擎 poll 让位），无脚本时引擎兜底。
- 代价：A 改动最小但保留交互污染；B 需要一次出厂默认值变更（旧玩家的肌肉记忆失效，但 Tab 从来"改键"能力也没生效过）；C 逻辑最复杂，但完全兼容既有场景。

---

## 6. 审计自身的可审计性

### 6.1 写保护自查（每轮跑完执行）

```
> git status --porcelain
?? docs/audit/scan_beta3_01_input_binding_mouselock.md      ← 本报告
?? docs/audit/scan_beta3_02_vk_gl_player_runtime.md         ← 其他子代理的报告（非本轮产出）
?? docs/audit/scan_beta3_03_ui_event_and_scene_driver.md
?? docs/audit/scan_beta3_04_editor_agent_visual.md
?? docs/audit/scan_beta3_05_packaging_release.md
?? docs/audit/scan_beta3_06_physics_and_pacman.md
?? tools/lint_except_dist/
?? tools/loom_lint_except.py
```
无任何 ` M ` 条目 → 未修改受跟踪源码/测试/文档；未执行 `git add/commit/checkout/stash/reset/clean`。
新建文件只有两个：本报告 + `Loom/tests/_tmp/beta3_scan_01b_probe.py`（一次性探针）。

### 6.2 本轮复跑命令（供下一位独立复核）

```
cd "D:\my-project - 副本\Loom(py源代码-工作区)"
$env:PYTHONIOENCODING='utf-8'
python Loom/tests/_tmp/beta3_scan_01b_probe.py        # 本轮探针, S1..S12
python Loom/tests/_tmp/beta3_scan_01_run_test_scripts.py   # 既有回归, 期望在 test_scripts.py:188 断链
python Loom/tests/_tmp/beta3_scan_01_probe2.py        # 上一任探针(落盘/落点/失败返回)
python Loom/tests/_tmp/beta3_scan_01_probe3.py        # 上一任探针(大小写/空列表, 权威版)
git status --porcelain
```

### 6.3 A6 自审 checklist

- [x] 8 条硬要求（基准唯一 / 代码原样 / 路径完备 / 预期实际可对照 / 命令可跑 / 措辞可审计 / 跳过留痕 / 矛盾不忽略）
- [x] 每条链只引用被审对象自身契约（承接总纲 / 变更清单 / 文件 docstring），无外部标准混用
- [x] 每条证伪链第 3 段是路径枚举表（或集合穷举），不是"检查了主要路径"
- [x] 每条证真链第 7 段是可跑命令 + 实测输出原文
- [x] 跳过登记 7 条，均有四类理由之一 + 出处
- [x] P-UNKNOWN = 3（非 0）；P-PROVED = 13（非 0）；P-CONTRADICTION = 0（已在 §3.1 解释）
- [x] 无不可审计措辞（禁用词清单见方法论文档 §7；`Select-String` 复核结果：除本行与 §3.4 这两处**引用该清单本身**的文字外，全文 0 命中）
- [x] 未修改任何受跟踪文件（§6.1 实测）
- [x] 上一任探针中的**伪证据**（`probe2` S12a 手工注入 `f10`）已在本报告 P-01-06 明确作废并说明原因


---

## 7. 第 0 批修复记录（2026-11-08 · 用户配置目录地基 + 本模块 P0/P1/P2 修复）

> 依据白盒契约: `docs/design/用户配置目录契约_20261108.md`（§2 路径 / §4 合并 / §5 启动 / §6 迁移 / §7 写入语义 / §8.1 分批归属 / §9 验收）。
> 修前证据 = 本报告 §2 对应条目的实测输出；修后证据 = 本节实跑输出。

### 7.1 改动文件（本批授权范围）

| 文件 | 动作 | 对应缺陷 |
|---|---|---|
| `Loom/userpaths.py` | **新增**：`user_root/engine_settings/hub_settings/game_settings/project_settings/log_path/backup_path/ensure_dir` + `safe_name/sha1_short/game_id_for/project_id/ensure_parent` | 契约 §2（单点收口） |
| `Loom/guiloader.py` | 设置改为 `默认 <- 模板(只读) <- 用户层 delta`；新增 `user_settings_path()`；`save_settings` 只写 delta、失败上抛；`base` 显式给出时保持旧语义（测试隔离） | 契约 §1/§4/§7 |
| `Loom/game_settings.py` | 重写为模板层 + 用户层；`bootstrap()` 首次写默认 + 旧格式迁移；坏 JSON -> 备份 + 默认；`read_key_bindings` 坏值告警；写失败上抛；新增 `base_dir` 覆盖参数 | P-01-07 / P-01-11（+ §5/§6/§7） |
| `Loom/loom_input.py` | `_action_bindings_file` 指向只读模板；`_load_action_bindings` 容忍坏条目并出声；**实现 `apply_game_bindings()`**；`save_action_bindings(None)` 写用户层；`rebind_action` 只写用户层且失败上抛 | **P-01-01** / P-01-05 / P-01-16 |
| `Loom/输入配置.json` → `Loom/输入配置.default.json` | `git mv`（保留历史），运行时只读 | 契约 §8 |
| `Loom/engine.py` | 仅 `set_action_binding`（如实返回 saved/error/path）、`get_action_bindings`（读失败出声）、`_load_action_bindings` 调用点的告警 | **P-01-03** |
| `Loom/tests/test_user_config.py` | **新增** 验收测试（11 组 60+ 检查） | 契约 §9-1 |

### 7.2 修前 / 修后证据

| 缺陷 | 修前（实测，§2 引用） | 修后（实测） |
|---|---|---|
| **P-01-01** `apply_game_bindings` 无定义 | `AttributeError: 'GLEngine' object has no attribute 'apply_game_bindings'`（`loom_input.py:261`），并把 `test_scripts.py` 断链在 188 行 | `python tests/test_user_config.py` → `PASS apply_game_bindings 已实现 (P-01-01)`；`python tests/test_scripts.py` → **`总结果: ALL PASS ✅` EXIT=0**（原红转绿） |
| **P-01-03** 写失败仍 `saved:True` | `{'ok': True, 'action': '向前', 'keys': ['i'], 'saved': True}`（PermissionError 后） | `PASS 写失败 -> ok=False {'ok': False, ..., 'saved': False, 'error': "FileNotFoundError(...)"}`；`PASS 写成功 -> ok=True + saved=True + path` |
| **P-01-05** rebind 双写受跟踪文件 | `engine 配置写次数 = 1`（并改写受跟踪的 `Loom/输入配置.json`） | `PASS rebind_action 只写用户层 (模板不变)`、`PASS 用户层文件只有 delta`；仓库不再有 `输入配置.json`（已 `git mv` 为只读模板） |
| **P-01-07** `game_dir()` 只认 argv[0] | 编辑器落点 = 引擎目录（S12c 实测） | `PASS 用户层落在 userpaths.engine_settings()`；game/项目层落 `%LOCALAPPDATA%\Loom\games|projects\<id>\settings.json` |
| **P-01-11** 坏类型静默丢弃 | `{'向前': ['w', 'None']}`（None 被字符串化，无告警） | `PASS 合法键名保留, 非法键名丢弃 {'向前': ['w']}` + `PASS 丢弃非法键名时告警` |
| **P-01-16** 一条坏条目丢整份 | `\{'交互\': 5\} -> 跳跃=['space']`（整份回退） | `PASS 单条坏条目只跳过自己 (P-01-16)` |

修后完整实跑（`cd Loom`，`LOOM_USER_ROOT` 指向临时目录）：
```
python tests/test_user_config.py     -> 总结果: ALL PASS ✅        EXIT=0
python tests/test_scripts.py         -> 总结果: ALL PASS ✅        EXIT=0   (修前 AttributeError 断链)
python tests/test_guiswitch.py       -> 总结果: ALL PASS ✅        EXIT=0
python tests/test_backend_fallback_policy.py -> ALL PASS            EXIT=0
python tests/test_render_api.py      -> 总结果: ALL PASS ✅        EXIT=0   (单独跑: 无污染时)
python tests/test_eai_real.py        -> 有 FAIL: ['命令表全部命令都被真编辑器执行过 (共 98 条)'] 
                                        缺失 ['camera_proj','key_binding','render_api']  <- 既有: 该测试的
                                        _USED 清单未收录 beta3 新增的 3 个命令, 与本批无关
```

### 7.3 调用方应如何改（第 2/3/5 批照做即可）

| 调用方（批次） | 现在的问题 | 建议改法（函数名 + 预期返回） |
|---|---|---|
| `run_player._persist_backend`（第 3 批） | `game_settings.write_render_api(api)` 无落点覆盖 → 测试/调试时会写真实用户层（`test_render_api` 套件内变红的唯一剩余原因） | `game_settings.write_render_api(api, base_dir=_SETTINGS_BASE)`（本批已提供参数，返回 `(ok, api, err)`）；同时删掉 `return ok_game or True`，返回 `ok_game` 或异常 |
| `run_player._read_setting`（第 3 批） | `guiloader.load_settings('loom')` 现已自动读"模板+用户层"，**无需改**；`_SETTINGS_BASE` 传参时仍走旧语义 | 保持现调用即可；若要打印来源，用 `guiloader.settings_path/user_settings_path` |
| `game_player._bootstrap_logging`（第 3 批） | 仍写 `<exe 目录>\日志.txt`（打包到只读目录会静默丢日志） | 改为 `userpaths.log_path('game')`；失败时向 stderr 打印一次原因（契约 §7） |
| `scene_driver.__init__`（第 2 批） | 仍硬编码读 `<引擎目录>\输入配置.json`（本批已重命名为 `输入配置.default.json`）→ 模板层失效，只剩 `DEFAULT_ACTIONS` | 改为读模板：`os.path.join(引擎目录,'输入配置.default.json')`（缺失再退旧名），或直接复用 `loom_input` 的加载逻辑；游戏层覆盖改调 `game_settings.read_key_bindings()`（返回 `{动作: [键]}`，坏值已告警） |
| `scene_driver.set_render_api/set_action_binding`（第 2 批） | 与 GL 侧落盘面不一致（GL 会写引擎层） | 只用 `game_settings.write_render_api/write_key_binding`，并把 `(ok,err)` 如实返回给调用方 |
| `LoomHub/hub_config.py`（第 5 批） | 设置仍写 `<程序目录>\设置.json` | 走 `guiloader.load_settings('loomhub')`（已分层）或 `userpaths.hub_settings()` |

### 7.4 本批发现但**未修**的新问题（按契约 §9-4 只记录）

1. `scene_driver.py:449` 读 `输入配置.json`：本批 `git mv` 后该文件不存在 → VK 侧模板层失效（`except: pass` 静默）。**第 2 批必修**（见 §7.3）。
2. `game_player.py:42` 仍把 `日志.txt` 写到 argv[0] 目录（测试跑完在 `Loom/tests/日志.txt` 留一个未跟踪文件）。**第 3 批必修**。
3. 套件内 `test_render_api.py` 仍红：`test_backend_fallback_policy` 经 `run_player._persist_backend` 把 `render_api=opengl` 写进"tests 目录身份"的用户层，后续 `resolve_backend('')` 读到它。**第 3 批一行可修**（`base_dir=_SETTINGS_BASE`）。单独跑本测试为 ALL PASS（已实测）。
4. `test_vk_camera_align.py` 的 `10 Tab 经脚本解锁鼠标` 为既有红（Tab 双 toggle = P-01-02，契约 §9-4 明确不在本批）。本批已实测"保留旧 `输入配置.json` 时同样红"，排除是本批重命名引入。
5. `Loom/tests/设置.json` / `Loom/设置.json` / `LoomHub/设置.json` 是**受跟踪**文件，现已自然成为只读模板（本批后无人再写它们）；后续若要"模板随版本更新"，需在打包流程里同步（第 5 批/11_build 关注）。

### 7.5 不变量自查（契约 §8 末条）

```
> git status --porcelain
 M Loom/engine.py                    ← 本批（set_action_binding/get_action_bindings）
 M Loom/game_settings.py             ← 本批
 M Loom/guiloader.py                 ← 本批
 M Loom/loom_input.py                ← 本批
 M Loom/loom_physics.py              ← 其他批次
 M Loom/scripts/pacman_*.py          ← 其他批次
R  Loom/输入配置.json -> Loom/输入配置.default.json   ← 本批（契约 §8）
?? Loom/userpaths.py                 ← 本批新增
?? Loom/tests/test_user_config.py    ← 本批新增
?? （其余 ?? 为其他子代理的审计报告/测试/工具）
```
- 无 `Loom/tests/游戏设置.json`、无 `Loom/输入配置.json` 的写入改动；跑完全部定向测试后 `Loom/tests/设置.json` 等受跟踪模板**字节未变**（由 test_user_config 的 hash 断言与 §7.2 输出佐证）。


---

## 8. 第 1 批修复记录（2026-11-08 · 解锁键语义 D6=A/A/A + P-01-02）

> 裁决: **引擎独占解锁键**；内置 first/third_person 删掉硬编码 Tab 分支（只读 `mouse_locked`）；`Script` 基类增加 `keys_used`；设置解锁键冲突 → **拒绝保存**并提示"…已被脚本 X 使用，请先定义解锁键"；默认仍 Tab（内置脚本不再占用 Tab 后天然无冲突）。

### 8.1 改动文件

| 文件 | 动作 | 对应缺陷 |
|---|---|---|
| `Loom/scripts.py` | `Script` 基类新增 `keys_used = ()` 声明位；新增 `script_key_uses()` / `script_display_name()`；**first_person / third_person 删除 Tab 分支与 `_tab_was`**（只读 `mouse_locked`）；wasd_move / jump 声明 `keys_used` | **P-01-02** |
| `Loom/loom_input.py` | 新增 `UNLOCK_ACTION` 常量、`script_occupied_keys()`、`validate_action_binding()`、`resolve_unlock_key_conflict()`；`rebind_action` 先校验后写（冲突抛 `ValueError`）；`apply_game_bindings` 末尾做加载时冲突处置 | **P-01-02**（冲突面） |
| `Loom/engine.py` | `_poll_mouse_unlock_key` 返回翻转布尔 + 用 `UNLOCK_ACTION` 常量；新增公开入口 **`poll_unlock()`**（暂停态用，P-01-04 跨批 API）；`set_action_binding` **修复入参被清空的自查 BUG**（见 §8.3） | **P-01-02** / P-01-03 收尾 |
| `Loom/tests/test_scripts.py` | **测试适配**：M39 段改为"引擎 poll → 脚本 update"的真实次序（旧断言锁定的正是被裁决取消的"脚本 toggle"语义） | P-01-02 |
| `Loom/tests/test_unlock_key.py` | **新增**定向测试（7 组 30+ 检查：声明 / 一帧一次翻转 / 冲突拒绝 / action: 展开 / 自冲突排除 / 加载时回退 / poll_unlock / 无冲突改键） | P-01-02 |
| `Loom/agent_commands.py` | **未改**（见 §8.5 说明：`key_binding` 直接 `return ed.set_action_binding(...)`，新返回值 `{ok,saved,error}` 已自动透传；但 MCP 层如何呈现 `ok:False` 需第 4 批确认） | — |

### 8.2 `keys_used` 规格（给脚本作者与其他批次）

```python
class MyScript(Script):
    keys_used = ('Tab',)                  # 直接键名（与 _KEYMAP 同名）
    # 或
    keys_used = ('action:向前', 'action:跳跃')   # 动作名 -> 按当前绑定展开成键名
```
- 展开规则: `action:NAME` 用 `self.actions[NAME]` 的**当前**绑定展开；`NAME` 恰是正在改绑的动作时**跳过**（否则"把 向前 再绑回 w"会被自己拒绝）。
- 消费者: `loom_input.script_occupied_keys()` → `validate_action_binding()`。脚本注册表不可用时**出声**跳过（不静默放行）。
- 已声明的内置脚本: `first_person`（向前/后/左/右/跳跃）、`third_person`（前后左右）、`wasd_move`（前后左右）、`jump`（跳跃）。

### 8.3 修前 / 修后证据

| 项 | 修前（实测） | 修后（实测） |
|---|---|---|
| **P-01-02 双翻转** | `python tests/test_vk_camera_align.py` → `FAIL 10 Tab 经脚本解锁鼠标  (True, False)`；审计探针 S5: `poll 后 mouse_locked=False … 脚本 update 后 mouse_locked=True 结论: 净效果 = 仍锁定? True` | `test_vk_camera_align.py` → **ALL PASS ✅ EXIT=0**；`test_unlock_key.py` → `PASS 按一次 Tab 净效果 = 解锁 (不再被脚本翻回去) (False, True)` |
| **冲突拒绝保存** | 无校验（变异探针把 `validate_action_binding` 短路 = 修前行为）：`修前(校验短路) rebind_action 抛 ValueError? False` / `解锁键被改成 Tab? ['Tab']` / `set_action_binding -> {'ok': True, ..., 'saved': True}` | `PASS rebind_action 直接拒绝 (抛 ValueError)  键位冲突: 解锁键 Tab 已被脚本 占位脚本(_probe_tab_user) 使用，请先定义解锁键（…）`；`PASS set_action_binding 如实返回 ok=False / saved=False`；`PASS 拒绝后**未写用户层**` |
| **加载时冲突** | 旧实现无此概念（冲突键直接生效 → 解锁键静默失效） | `PASS 加载后回退到默认 Tab ['Tab']` + `PASS 回退时明确告警 (不静默)` |
| **自查 BUG：`set_action_binding` 入参被清空** | 上一版（第 0 批）`keys = []` 写在 `isinstance(keys,str)` 之前 → 任何改键都变成"写空绑定"：`FAIL set_action_binding 如实返回 ok=False / saved=False  {'ok': True, ... 'keys': [], 'saved': True}` / `FAIL 写入用户层 key_bindings` | 改为局部变量 `ks`：`总结果: ALL PASS ✅`（`test_unlock_key.py` 全绿，`test_user_config.py` 仍 ALL PASS） |

实跑（`cd Loom`，`LOOM_USER_ROOT` 指向临时目录）：
```
python tests/test_unlock_key.py        -> 总结果: ALL PASS ✅   EXIT=0
python tests/test_scripts.py           -> 总结果: ALL PASS ✅   EXIT=0   (适配后)
python tests/test_vk_camera_align.py   -> 总结果: ALL PASS ✅   EXIT=0   (原 FAIL 转绿)
python tests/test_scripts_collision.py / test_playmode_edges.py / test_add_script_cache.py -> 全 PASS
```

### 8.4 `poll_unlock()`（P-01-04 跨批接口）

```python
def poll_unlock(self) -> bool:   # True = 本帧发生了一次 锁定<->解锁 翻转
```
- 与 `update_scripts` 内部调用**同一实现**（`_poll_mouse_unlock_key`），不依赖逻辑帧。
- 第 2 批（03 号，`scene_driver.py`）接线位置：`advance_logic` 的 `if getattr(self,'logic_paused',False)` **早退分支之前**；同时给 `SceneDriver` 加同名 `poll_unlock()` 转发到它自己的 `_poll_mouse_unlock_key()`。
- GL 侧 `GLEngine.update_scripts` 已内置调用，**不要**在编辑器/播放器再调一次（否则同一帧翻转两次）。

### 8.5 本批发现但**未修**（写进报告，不就地改）

1. `agent_commands.py:989-1002` 的 `key_binding` 命令注释仍写"写入游戏配置"，实际写用户层；且它直接返回 `engine.set_action_binding()` 的 dict —— **MCP 层是否把 `ok:False` 当失败**需第 4 批（04 号）确认（若把 dict 当成功，冲突提示玩家看不到）。
2. `vk_player.py:356` 注释仍写"Tab 的切换由 first_person/third_person 脚本走 driver.toggle_mouse_locked" —— 已过期（现由引擎独占），属第 3 批文件。
3. `scene_driver.py:907-933` 仍持有一份 `_poll_mouse_unlock_key` 副本（与 engine 语义平行）。当前无双翻转（脚本已不 toggle），但"引擎独占"应体现为委托；建议第 2 批把 driver 侧改为调用共享实现或至少加"单一所有者"注释。
4. `test_scripts.py` 的 M39 段原断言锁定了被裁决取消的语义，本批做了**测试适配**（把驱动源从脚本换成引擎 poll，用户可见断言一字未改）。若主审要求"测试文件零改动"，需改用其它批次提供兼容层——请裁决。
5. 冲突提示仅覆盖"脚本声明"这一维；"两个动作绑同一个键"（如 向前 与 解锁鼠标 都绑 w 而 w 未被脚本声明）仍不告警 —— 属新问题，未修。


---

## 9. 第 4 轮修复记录（2026-11-08 · N3 假绿：解锁键轮询被无差别 except 吞掉）

> 现象（主审全量回归）：`engine.py` 的 `except Exception as e: print('[输入] 解锁键检测失败 …')` 一次回归打了 **265 条**；根因是部分测试桩没有 `.actions` → `get_action()` 抛 `AttributeError` → 这些用例里**解锁键轮询根本没执行**，测试却判 PASS（假绿）。

### 9.1 `Loom/engine.py`：拆两段 + 恢复异常可见性

| 改动 | 内容 |
|---|---|
| 结构 | **第 1 段"取键值"**：预检 `actions` 是否 dict、`get_action` 是否可调用、`actions` 是否含 `解锁鼠标`；`get_action()` 本身只在 `except AttributeError`（缺按键快照）时降级。**第 2 段"翻转"**：只 `except AttributeError`。两段都不再有无差别 `except Exception` |
| 告警 | 新增模块级 `_unlock_poll_warn(obj, missing)`：按 `(引擎类名, 缺失原因)` **每进程只打一行**，内容含"类名 / 缺什么 / 桩该怎么补"；实例侧留 `_unlock_poll_warned = True` 标记。`GLEngine._warn_unlock_poll_unavailable` 保留为委托封装 |
| 语义 | 无法轮询时**明确返回 False**（不再把"没跑"当"没变化"），并让 `update_scripts` 的调用方在日志里看到原因 |

### 9.2 补齐测试桩（让轮询真的跑）

扫描方法：把 `tests/test_*.py`（112 个，排除 `test_integration.py` / `test_eai_real.py`）逐个子进程跑一遍，统计改进后告警	extbf{标记}出现次数与退出码。

| 测试文件 | 位置 | 修补内容 | 理由 |
|---|---|---|---|
| `test_add_script_cache.py` | `_stub_engine()`（:75） | `actions = dict(DEFAULT_ACTIONS)`、`script_keys = {}`、`mouse_locked = False`（并补 `from engine import DEFAULT_ACTIONS`） | 该桩专测 `update_scripts` 的脚本缓存；轮询在首行，缺输入状态时整条轮询被跳过 |
| `test_collision.py` | `eng_fall`（:134）、`eng_b`（:149） | 同上三行 | 用真实 `update_scripts` 跑 120 帧物理，属"应该有输入状态"的桩 |
| `test_playmode_edges.py` | `new_app()`（:65） | 同上三行 | 播放态边界用例，`update_scripts` 是主路径 |
| `test_scripts.py` | 调度段桩（:325） | 同上三行 | 同上（该文件 M39 段另有引擎 poll 桩，已在前轮补） |

**豁免说明**：没有"按语义不该有 actions"的桩 —— 上述 4 处都是直接调用真实 `update_scripts` 的引擎桩，补 `actions` 不改变任何被测语义（只让轮询从"跳过"变成"跑一遍且无按键"）。

### 9.3 新增断言（`tests/test_unlock_key.py` §H）

```
PASS 缺 actions/script_keys 时 poll 全返回 False (不假装翻转)  [False, False, False]
PASS 50 帧只告警 1 条 (不刷屏; 修前: 每帧一条)  1
PASS 告警带引擎类名 + 缺失属性  [输入] 解锁键轮询未执行: 引擎实例 _NoActionsStub 的 actions (键位表) 不可用 —…
PASS 实例留下已告警标记
PASS 补齐 actions/script_keys 后 poll_unlock 真的翻转  (True, False)
PASS 补齐后不再产生'轮询未执行'告警
```

### 9.4 修前 / 修后

| 项 | 修前 | 修后 |
|---|---|---|
| 告警条数 | 每次轮询一条（全量回归 **265 条**） | 每 (类名, 原因) 每进程 **1 条** |
| 桩缺属性时的行为 | `AttributeError` 被 `except Exception` 吞掉 → 轮询**未执行**但测试 PASS（假绿） | 明确返回 False + 一次性告警（类名+缺失项），并已把 4 个桩补齐让轮询真跑 |
| 回归 | — | 112 个测试逐一跑：**只有 `test_unlock_key.py` 出现该标记 1 次（自带断言）**，其余 warn=0 且 exit=0 |

**线索更正（留痕）**：主审给的方向里"已知 `test_lighting.py` 至少 16 条"——实测 `test_lighting.py` 不构造引擎、不调用 `update_scripts`（`grep GLEngine/update_scripts` 均无命中），本轮扫描 `warn=0 / ALL PASS`。真正命中的是上表 4 个文件。

### 9.5 验收实跑（`cd Loom`，`LOOM_USER_ROOT`=临时目录）

```
test_unlock_key.py        exit=0 warn=1  (1 条来自 §H 的故意断言)  总结果: ALL PASS
test_scripts.py           exit=0 warn=0  总结果: ALL PASS
test_lighting.py          exit=0 warn=0  总结果: ALL PASS
test_vk_camera_align.py   exit=0 warn=0  总结果: ALL PASS
test_add_script_cache.py / test_collision.py / test_playmode_edges.py / test_scripts_collision.py -> 全 PASS warn=0
```


---

## 10. 第 5 轮修复记录（2026-11-08 · 鼠标锁定语义重构：默认不锁 / 显式 API / 可验证解锁）

> 人类裁决（2026-11-08）: ①**默认不锁**（allowed/initial 默认 False）；②不做"检测到 UI 就自动解锁"，由游戏开发者显式判断；③三件能力齐备（整个游戏是否锁 / 某时刻锁不锁 / 哪键解锁）。
> 实测病灶: 打包吃豆人被默认锁死；按 Tab 后光标出现但动不了（只能 Alt+F4）→ ①默认 initial=True；②`set_ui_capture_mouse` 全仓无人调用；③解锁只翻 GLFW 一个模式且 `except: pass`，无回读、无 Win32 兜底。

### 10.1 改动文件

| 文件 | 改动 | 对应裁决 |
|---|---|---|
| `Loom/game_settings.py` | `MOUSE_LOCK_ALLOWED_DEFAULT = False`、`MOUSE_LOCK_INITIAL_DEFAULT = False`（initial 仅在 allowed=True 时有意义），注释写明"需要锁的游戏显式打开" | ① |
| `Loom/loom_input.py` | ①`InputMixin` 类默认 `mouse_lock_allowed = False`；②`set_mouse_locked(True)` 在 allowed=False 时**无效**并每进程告警一次（说明"本游戏不允许锁鼠标"）；③`toggle_mouse_locked()` 在 allowed=False 时**完全不响应**（不打日志）；④新增脚本 API **`set_mouse_lock_allowed(bool)`**（切换立即应用：True 按意图计算；False 清意图并立刻释放）；⑤`_apply_mouse_lock()` 在 allowed=False 时锁恒为关；⑥`set_ui_capture_mouse()` 保留为**开发者显式 API**，docstring 写清"打开背包/菜单/暂停时 True，关闭时 False"并引用燕云十六声反例；⑦解锁可验证化：`_apply_cursor_backend()` 调 `glfw.set_input_mode` 后**回读** `glfw.get_input_mode`，不符/失败各告警一次；⑧Win32 兜底 `_win32_clip_cursor`（锁定=ClipCursor(窗口客户区)，解锁=ClipCursor(NULL)）与 `_win32_show_cursor`（ShowCursor），失败只告警一次；⑨每次状态变化打一行 `[鼠标] locked=... (glfw_mode=..., clip=..., showing=...)`；⑩原 `except: pass` 全部删除，改为窄类型 except + 一次性告警 | ①②③④ |
| `Loom/engine.py` | `_poll_mouse_unlock_key` 中 allowed 的取默认值由 True 改 **False**；allowed=False 分支只做"若仍锁则强制释放"，**不打印任何切换日志**（N3 的收窄/一次性告警原样保留） | ①② |
| `Loom/tests/test_unlock_key.py` | 新增 §I 共 13 条断言（默认值 / 拒绝锁定 / 不刷屏 / Tab 不翻转且不打印 / toggle 不响应 / 特殊场景 API 不开锁 / 打开后 Tab 生效 / 关闭后立即释放）；§B/§F/§H 的桩显式 `mouse_lock_allowed = True`（它们测的是"允许锁"的游戏） | 验收 |
| `Loom/tests/test_scripts.py` | FakeEngine 与 `eg2` 桩各补 `mouse_lock_allowed = True`（M39 段测的是"允许锁"的游戏） | 验收 |
| `Loom/tests/test_vk_camera_align.py` | `vk_driver()` helper 补 `d.mouse_lock_allowed = True`（该文件测第一人称 + Tab 解锁，属"允许锁"的游戏） | 验收 |

### 10.2 修前 / 修后

| 项 | 修前 | 修后（实测） |
|---|---|---|
| 默认值 | `mouse_lock_allowed()=True` / `mouse_lock_initial()=True` → 打包游戏启动即锁死 | `PASS game_settings 默认 allowed=False` / `PASS game_settings 默认 initial=False` |
| 脚本强行锁 | `set_mouse_locked(True)` 无条件生效（first_person on_start 即锁） | `PASS allowed=False: set_mouse_locked(True) 无效` + `PASS 明确告警(说明本游戏不允许锁鼠标)` + `PASS 再次请求锁定不刷屏` |
| Tab 响应 | allowed=False 时仍会打印"切换鼠标锁定" | `PASS 按 Tab 不翻转` + `PASS 按 Tab 不打印'切换鼠标锁定'` + `PASS toggle_mouse_locked 完全不响应` |
| 显式开关 | 无此 API | `PASS set_mouse_lock_allowed(True) 后立即锁定` / `PASS 打开 allowed 后按 Tab 生效(解锁)` / `PASS set_mouse_lock_allowed(False) 立即释放` |
| 解锁可验证 | `except: pass`，无回读、无 Win32 兜底（"光标出现但动不了"） | 状态行 `[鼠标] locked=False (glfw_mode=host, clip=n/a, showing=n/a)`（测试桩为 external_ctx）；真机走 `_apply_cursor_backend` 回读 + ClipCursor/ShowCursor，失败各告警一次 |

验收实跑（`cd Loom`，`LOOM_USER_ROOT`=临时目录）：
```
test_unlock_key.py                  exit=0 ALL PASS ✅
test_scripts.py                     exit=0 ALL PASS ✅   (两处桩显式 allowed=True)
test_playmode_edges.py              exit=0 ALL PASS ✅
test_render_api.py                  exit=0 ALL PASS ✅
test_beta3_batch2_camera_proj.py    exit=0 ALL PASS
test_vk_camera_align.py             exit=0 ALL PASS ✅   (helper 显式 allowed=True)
test_user_config.py / test_lighting.py -> ALL PASS ✅
全量扫（112 个 test_*.py，排除 test_integration.py / test_eai_real.py）: 无失败项
```

### 10.3 可见行为变化（需写进发布说明）

1. **默认不锁鼠标**：所有游戏（含编辑器播放态）启动后鼠标都是自由的；内置 `first_person`/`third_person` 的 `on_start` 现在**不会**把鼠标锁上（会被拒绝并打一条告警）。
2. 需要锁鼠标的游戏二选一：`游戏设置.json` 写 `{"mouse_lock_allowed": true, "mouse_locked": true}`，或在脚本里 `engine.set_mouse_lock_allowed(True)`。
3. 解锁键仍为动作"解锁鼠标"（默认 Tab，可改、冲突拒绝）。

### 10.4 剩余 / 跨批

- `SceneDriver`（第 2 批文件）尚无 `set_mouse_lock_allowed()`：VK 侧脚本调用该 API 会 AttributeError；且其 `set_mouse_locked` 未做"allowed=False 拒绝"（目前靠 poll 兜底强制解锁，行为等价但不一致）。
- `runtime.PlayerApp` / `vk_player`（第 3 批文件）仍按 `mouse_lock_initial()` 初始化 → 现在默认 False，符合裁决；若游戏配置写了 allowed=true 则正常锁。
- 真机验证（打包吃豆人 + 真鼠标）需在打包后由主审执行；本机只能验证状态机与日志形态。
