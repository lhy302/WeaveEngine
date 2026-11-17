# 构建/打包/启动/日志/时钟 扫描报告（scan_11_build）

> 审计日期：2026-11-07 | **只读审计**（未修改任何受跟踪源码/测试/文档，未 git add/commit）
> 依据：`docs/audit/SCAN_PROTOCOL.md`（67 行，全读）+ 桌面两份方法论文档（vibe coding 614 行 / 自审方法论 735 行，全读）
> 代码根：`D:/my-project - 副本/Loom(py源代码-工作区)/Loom`（git 根为其上一级 `Loom(py源代码-工作区)`）
> 本次自评等级：**A5**（双向链齐备 + 探针回填 + 跳过留痕 + 人类裁决项；白盒层冲突 2 条按 A6 格式提交）

## 0. 范围与方法

### 0.1 文件清单（行数为 read 工具 totalLines 实测）

| 文件 | 行数 | 职责 |
|---|---|---|
| Loom.py | 368 | 源码入口：参数解析 / 自检 / 插件加载 / 编辑器·播放器·游戏配置三分支 |
| build_entry.py | 367 | **编译版 Loom.exe 的真实入口**（Nuitka 源），与 Loom.py 平行分叉 |
| build_game.py | 221 | 游戏构建器（场景+脚本+插件+运行时 → 发布夹） |
| game_pack.py | 137 | 游戏包 .lsc / 插件包 .lpc 打包与玩家端装载（含 secure 哈希互验） |
| crash_reporter.py | 293 | dbghelp Minidump 落盘 + 场景备份回调 + unhandled filter |
| loom_log.py | 36 | 启动日志开关（LOOM_QUIET） |
| loom_profiler.py | 53 | LOOM_PROFILE 阶段耗时插桩 mixin |
| loom_single_instance.py | 95 | 编辑器单实例互斥 + 窗口激活 |
| loom_logic_thread.py | 90 | 异步逻辑帧线程启停与主循环（LogicThreadMixin） |
| core_clock.py | 186 | FixedStepClock 单 accumulator 定步时钟 |

合计 **1646 行**。
跨模块只读引用（仅作调用方/消费方证据，不做本模块裁决对象）：
engine.py（430-509 设置块 / 493 异步开关 / 1098-1107 _ensure_split / 1361-1366 _stop_parallel）、
loom_render.py:815-842、ui/loom_gui.py:240-265,570-590、editor.py:125-140、run_player.py、game_player.py、
sceneio.py:1014-1070、plugin_loader.py:539-627、tests/_tmp/assemble_release.py、解释器.json。

### 0.2 判定基准清单（后续证真链只能引用这里）

| 编号 | 基准出处 | 原文要点 |
|---|---|---|
| C1 | loom_logic_thread.py:33-34 | `_stop_logic_thread` 文档串：「停逻辑线程 (幂等; 退出/换场景调)」 |
| C2 | crash_reporter.py:26-33 | 「用法 (引擎启动期, **Loom.py 早期接线**)」+ install() 安装 filter |
| C3 | build_game.py:7-8 / game_pack.py:6-8 | 发布夹「无任何明文脚本/场景」「玩家拿不到源码」 |
| C4 | build_game.py:11-14（用法块）+ 149-154 | `--output` 发布夹；`--force` = 允许覆盖 |
| C5 | build_entry.py:14 | 用法块声明 `python build_entry.py --bench <场景> [帧数]` 可用 |
| C6 | game_pack.py:117-119 / build_game.py:104-109 | 「哈希互验」「插件包被修改或校验失败…防修改校验拦截」「secure(竞技防作弊)」 |
| C7 | Loom.py:93-101 | `_launch_player` docstring：「LOOM_REMOTE_MODE=1 … 强制 GL … 必须优先」 |
| C8 | Loom.py:93-94 | 「按 --backend > 设置 render_api > 默认 的统一策略启动播放器」 |
| C9 | loom_single_instance.py:1-19 | 「连点开 17 个窗口」→「同一时间只允许一个编辑器」 |
| C10 | Loom.py:213-222 | 自检目标：「Python 启动时抛 source code string cannot contain null bytes … 给出明确指引」 |
| C11 | core_clock.py:157-163 | 「设置.json -> FixedStepClock」，未声明异常契约 |
| C12 | core_clock.py:66-68 | 注释：「默认收紧到 0.05s」 |
| C13 | loom_profiler.py:16-21 | 「记录 fn 阶段耗时到 _stage_times（累计 ms）」+ engine.py:493 异步逻辑线程**默认开启** |
| C14 | loom_single_instance.py:29-63 | ctypes 直接调 user32；同仓 crash_reporter.py:89 用 WinDLL(use_last_error=True) |
| C15 | Loom.py:61-69 | 恢复说明：「editor.py:137 与 build_entry.py:77 仍调用本函数 —— 删除直接造成 ModuleNotFoundError」 |
| C16 | Loom.py:80-86 | 「这里只解析参数」+ 注释只示范空格分隔形式 |

### 0.3 跑过的命令（全部定向探针，**未跑 tests/run_all.py**）

环境：Windows，`py -3.12` = Python 3.12.10，pygame 2.6.1。
探针目录：`C:/Users/ADMINI~1/AppData/Local/Temp/loom_scan11/`（不在仓库内），全部 `LOOM_NO_SAVE_MIGRATE=1`，
**未启动任何 GUI 窗口**（PlayerApp/runtime/engine 一律桩替换，见各探针头注释）。

~~~
git -C <repo> diff HEAD --stat -- Loom/{10 个文件}      -> 仅 Loom.py 47+/6-
git -C <repo> diff HEAD -- Loom/Loom.py                  -> 全文已审（见 0.4）
git -C <repo> log --oneline -2 -- Loom/<每个文件>        -> 见 0.4 归属表
git -C <repo> status --porcelain                         -> 审计前后一致（探针只写 TEMP 与 __pycache__）

py -3.12 %TEMP%/loom_scan11/probe_clock.py           # P-11 / P-21 / P-15 / P-20
py -3.12 %TEMP%/loom_scan11/probe_logic_thread.py    # P-01
py -3.12 %TEMP%/loom_scan11/probe_single_instance.py # P-09 / P-14
py -3.12 %TEMP%/loom_scan11/probe_bench_entry.py     # P-04
py -3.12 %TEMP%/loom_scan11/probe_build_game.py      # P-05
py -3.12 %TEMP%/loom_scan11/probe_launch.py          # P-07 / P-08 / P-17
py -3.12 %TEMP%/loom_scan11/probe_selfcheck.py       # P-10
py -3.12 %TEMP%/loom_scan11/probe_pack_integrity.py  # P-06
py -3.12 %TEMP%/loom_scan11/probe_crash_wiring.py    # P-02
py -3.12 %TEMP%/loom_scan11/probe_timescale.py       # P-13 / P-20
py -3.12 %TEMP%/loom_scan11/probe_backend_default.py # P-08
py -3.12 %TEMP%/loom_scan11/probe_build_inputs.py    # P-18 / P-19
~~~

第三方复现：把附录 A 的脚本原样存到临时目录后执行即可（脚本内 `sys.path` 已指向 Loom 目录）。

### 0.4 特别审查：git diff HEAD（[REGRESSION] 判定依据）

本模块 10 个文件中**只有 Loom.py 有未提交改动**（其余 9 个 `git diff HEAD` 为空）：

~~~
 Loom/Loom.py | 53 +++++++++++++++++++++++++++++++++++++++++++++++------
 1 file changed, 47 insertions(+), 6 deletions(-)
~~~

改动内容（全文已逐行审）：
1. 恢复 `_make_editor_view`（61-76）；
2. 新增 `_cli_backend`（79-90）与 `_launch_player`（93-101）；
3. `--run` 分支不再直连 `runtime.PlayerApp`，改走 `_launch_player` + `sys.exit(0)`（304-306）；
4. 游戏配置.json 分支同上（336-339）。

文件归属（`git log --oneline -2 -- <file>`）：

| 文件 | 最近提交 | 与本轮 Vulkan 对齐的关系 |
|---|---|---|
| Loom.py | 4f46650（P0-1 白屏）/ ca48b3b | **有未提交改动 = 本轮 R-04** |
| build_entry.py | 5f015a8 / 487120c | 未随 Loom.py 同步（P-03） |
| build_game / game_pack / crash_reporter / loom_profiler / loom_logic_thread / core_clock | 89141af（Initial commit） | 本轮未改，问题为存量 |
| loom_single_instance.py | c2fea49 | 存量 |
| loom_log.py | 145e4f2 | 存量 |

→ **REGRESSION 清单 2 条：P-07、P-08**（均由本轮 93-101 / 304-306 / 336-339 的新增路由引入）。

### 0.5 运行期自查

审计前后 `git status --porcelain` 完全一致；探针只写 `TEMP/loom_scan11/` 与 `Loom/__pycache__/`（后者已被 .gitignore 覆盖，`git check-ignore` 命中）。
**未还原任何受跟踪文件**（因为没有任何受跟踪文件被本次探针改动）。
注：审计开始时仓库已存在 11 个 `tests/_tmp/*` 的**已暂存删除**（D 前缀）与若干 M 测试文件，均为本会话开始前的既有状态，非本审计产生。

---

## 1. 粗筛清单（阶段一）

> 标签取自方法论 §4.3。粗筛只给方向，不判决。「初步方向」必须指向具体代码事实。

| ID | 位置 | 标签 | 初步方向 |
|---|---|---|---|
| P-01 | loom_logic_thread.py:33-45,47-53 | SEM-MISMATCH / BND-CONCURRENCY | stop 先把 `self._logic_stop` 置 None，而循环条件正是 `self._logic_stop is not None and …is_set()` → 线程永远看不到 set 事件 |
| P-02 | crash_reporter.py:26-33,270-293 | AUDIT-DOCIMPL / SEM-SILENT | 文档串要求「Loom.py 早期接线」，但全仓生产代码无一处 import/调用 |
| P-03 | build_entry.py:267-367 | IFACE-PRECOND / AUDIT-ASYMMETRY | 编译版入口与源码入口能力分叉（无 --backend / 无单实例 / 无自检 / 无远程模式） |
| P-04 | build_entry.py:262 vs 287 | SEM-MISMATCH | `_bench_scene` 里的 `pygame.quit()` 引用模块全局，而 `import pygame` 在 --bench 分支**之后**才执行 |
| P-05 | build_game.py:149-154 | BND-RESOURCE / 破坏性操作 | `--output` 取任意路径后 `shutil.rmtree` 无任何守卫（不比对 BIN_DIR/盘根） |
| P-06 | game_pack.py:110-130 + sceneio.py:1014-1036 | AUDIT-ASYMMETRY / OVERFIT-ORACLE | 期望哈希与被校验文件同夹同链，且解码器（zlib+XOR 0x5A+base64）随运行时发布 |
| P-07 | Loom.py:93-101 / 320-339 | AUDIT-DOCIMPL | docstring 声明 LOOM_REMOTE_MODE 优先，函数体字节码里没有该常量 |
| P-08 | Loom.py:304-306,336-339 → run_player.py:36-52 | SEM-DEFAULT | 默认 `render_api=vulkan` 且显式 vulkan 分支无回退，原「恒 GL」路径消失 |
| P-09 | loom_single_instance.py:66-94 | BND-CONCURRENCY / SEM-SILENT | 第二实例在首实例窗口未建好时找不到 HWND；`scene_path is None` 时零输出直接 exit |
| P-10 | Loom.py:213-266 | OVERFIT-HARDCODE | 判据是「前 8KB **全部**为 0」，而真实故障是「**任意** NUL 字节」 |
| P-11 | core_clock.py:164-171 → engine.py:439,478-482 | IFACE-ERROR / SEM-SILENT | `float()` 直接抛；唯一生产调用方用 `except Exception: pass` 兜底 → 半初始化 |
| P-12 | build_game.py:155-167 | AUDIT-ASYMMETRY | 整目录 copytree 把 .c/.h/.bat/.lib/.txt 全带进发布夹 |
| P-13 | loom_profiler.py:22-41 | BND-CONCURRENCY | `d[k]=d.get(k,0)+dt` 跨线程读改写 |
| P-14 | loom_single_instance.py:29-63,73-78 | IFACE-PRECOND | user32 全部无 argtypes/restype；kernel32 用 `GetLastError()` 而非 use_last_error |
| P-15 | core_clock.py:66-72 | AUDIT-DOCIMPL | 注释「默认收紧到 0.05s」vs 形参默认 0.333 |
| P-16 | Loom.py:61-76 | AUDIT-DEADCODE | 恢复的函数在 Loom.py 内无调用点 |
| P-17 | Loom.py:79-90 | TOOL-CLI | 只支持空格分隔，`--backend=opengl` 静默失效 |
| P-18 | build_game.py:43-56 | OVERFIT-GEN | 脚本按 `encoding='utf-8'` 硬读，无容错 |
| P-19 | game_pack.py:120-122 | SEM-SILENT / IFACE-ERROR | `load_plugins_pack` 返回 None 时直接 `data.get(...)` |
| P-20 | core_clock.py:111,117-127 | BND-OVERFLOW | time_scale>1 时 `min(render_dt,max_delta)*scale` 与步数预算 `max_steps*fdt` 语义不一致 |
| P-21 | core_clock.py:111-132 | BND-OVERFLOW | 定步时钟浮点累加是否会漂移（本模块重点之一） |
| P-22 | crash_reporter.py:248-267 | SEM-SILENT | filter 路径是否把异常「处理掉」而不留证据 |
| P-23 | loom_log.py:19-36 | SEM-SILENT | LOOM_QUIET 是否误吞运行期错误 |
| P-24 | build_game.py:155-167 | DESIGN-GAP | 未拷贝 assets/ 是否导致玩家缺资源 |
| P-25 | loom_single_instance.py:1-19 + Loom.py:346-349 | SEM-OVERFIT | 单实例锁是否误伤 --run 多开 |
| P-26 | crash_reporter.py:212-221,235-245 | BND-CONCURRENCY | 限流读改写是否在锁外 |
| P-27 | loom_single_instance.py:77-78 | IFACE-PRECOND | 未开 use_last_error 时 GetLastError 是否会被 ctypes 路径清掉 |
| P-28 | game_pack.py:99-130 | DESIGN-AMBIG | secure 模式是否存在发布链路之外的可信锚（签名/服务端校验） |

**跳过登记表**（方法论 §4.2 四类理由，逐项留痕）：

| 编号 | 位置 | 跳过理由类别 | 具体出处 |
|---|---|---|---|
| SKIP-01 | loom_log.py:24-31 verbose 本身 | 已有回归测试覆盖 + 契约明确 | engine.py:549/552/577、parallel.py:243、loom_gui.py:174/548 均为**启动期信息**，不参与错误路径（P-23 据此判 DISPROVED） |
| SKIP-02 | core_clock.py:74-76 fixed_dt 除零 | 语言规范保证 + 契约明确 | 源码自带 `max(self.logic_fps, 1e-6)` 防御；tests/test_core_clock.py:169-170 覆盖 logic_fps<=0 走 None |
| SKIP-03 | core_clock.py:87-93 step_once 常规路径 | 已有回归测试覆盖 | tests/test_core_clock.py 覆盖 fps/alpha/death_spiral/time_scale/reset；P-21 另做长跑探针补强 |
| SKIP-04 | crash_reporter.py:122 _INVALID_HANDLE | 语言规范保证 | ctypes 文档：c_void_p(-1).value == 2**64-1，与 INVALID_HANDLE_VALUE 定义一致 |
| SKIP-05 | crash_reporter.py:194-195 finally CloseHandle | 语言规范保证 | try/finally 在 return 路径同样执行 |
| SKIP-06 | game_pack.py:93-96 _sha256_file | 语言规范保证 | 二进制读 + hashlib，无编码/平台分支 |
| SKIP-07 | build_game.py:36-40 常量路径 | 白盒契约明确声明 | 模块 docstring 第 17-22 行已定死默认目录，不属实现缺陷 |
| SKIP-08 | Loom.py:103-210 _benchmark_math | 契约明确 | 纯数值基准，与打包/启动链路无关 |

---

## 2. 逐项裁决（阶段二：先证伪、再证真，8 段链）

> 每条给出**反手（证伪）**与**正手（证真）**两条链。反手链第 3 段必须给路径枚举表。
> P-13 ~ P-19 为 P3 项，用「8 字段表」等价展开（字段与 8 段一一对应，不省略）。

### P-01 · 逻辑线程「停不下来」——stop 把判活字段置空，循环永远为真

**【反手 · 证伪】**
1. **判定基准**：loom_logic_thread.py:33-34「停逻辑线程 (幂等; 退出/换场景调)」。
2. **代码证据**（原样）：
   ~~~python
   33  def _stop_logic_thread(self):
   34      """★M3-N3: 停逻辑线程 (幂等; 退出/换场景调)。"""
   35      ev = self._logic_stop
   36      t = self._logic_thread
   37      self._logic_thread = None
   38      self._logic_stop = None          # <<< 判活字段被清空
   39      if ev is not None:
   40          ev.set()
   ...
   53      while not (self._logic_stop is not None and self._logic_stop.is_set()):
   ~~~
3. **推理链（路径枚举）** —— 循环的判活表达式只有 3 种取值组合：
   | # | self._logic_stop 状态 | 表达式 | 结论 |
   |---|---|---|---|
   | 1 | 属性为 None（从未 start / stop 之后） | `not (False and …)` = True | **继续跑** |
   | 2 | 属性是 Event 且未 set | `not (True and False)` = True | 继续跑（正常） |
   | 3 | 属性是 Event 且已 set | `not (True and True)` = False | 退出 |
   线程每次迭代**重新读取属性**（第 53 行直接取 self 属性，无本地缓存）。
   stop 的 37-40 行先置 None、再 set(旧 Event)：任何在 set 之后执行的迭代读到的是**None（状态 1）**，永远进不了状态 3。
   唯一能正常退出的窗口是「线程恰好在 38 行执行前完成了一次 is_set() 求值」——那时它已退出循环，与本缺陷无关；
   其余所有时序都落到状态 1。三态全覆盖，**证伪不成立**。
4. **预期**：stop 返回后 `_logic_thread is None` 且线程在 join 超时内结束。
5. **实际**：见第 7 段——join 恰好耗满 2.00s，线程仍 alive。
6. **差异**：「退出/换场景调」的契约不成立；二次 start 后同名线程变成 2 条。
7. **可复现验证**（探针 B）：
   ~~~
   D:/.../Temp/loom_scan11/probe_logic_thread.py
   start 后线程: loom-logic alive= True
   _stop_logic_thread 耗时 2.00s (内部 join timeout=2.0)
   stop 后旧线程 is_alive() = True   <- True 即永不退出
   第二次 start 后 name='loom-logic' 的线程数 = 2 (期望 1)
   is_playing=True 0.5s 内 clock.advance 调用次数 增量 = 607
   ~~~
8. **影响与等级**：**P1**。触发条件是「在线程存在时调用 `_stop_logic_thread`」（其 docstring 明确要求退出/换场景时调用）：
   ①主线程阻塞 2 秒 ②线程永久泄漏 ③重启后两条线程对**同一个 clk** 调 advance → 逻辑帧速率翻倍 + `_prep_pub`/`_interp.alpha` 数据竞争。
   **现网可达性（不夸大）**：当前唯一调用点是 engine.py:1366 `_stop_parallel` ← loom_render.py:842 的 `run()` 退出；
   Qt 宿主下 `run()` 在 loom_render.py:815-817 立即 return，所以**编辑器路径今日不会命中**。
   但该函数正是「换场景/退出」的既定挂点，一旦接线即触发。判 P1（潜在 P0：双驱物理/脚本）。

---

### P-02 · 崩溃落盘从未接线 —— 293 行模块在生产路径零调用

**【反手 · 证伪】**
1. **判定基准**：crash_reporter.py:26-33「用法 (引擎启动期, **Loom.py 早期接线**)」+ :270-293 install()。
2. **代码证据**：install()(:270) / write_dump()(:224) / register_scene_backup()(:134) 都是「被调用才生效」的被动 API，模块顶层**不自动安装**（无模块级 `install()` 调用）。
3. **推理链（调用方枚举）**：
   | 入口 | 是否引用 crash_reporter | 证据 |
   |---|---|---|
   | Loom.py（源码入口） | 否 | 全文 grep 0 |
   | build_entry.py（编译版入口） | 否 | grep 0 |
   | game_player.py（游戏运行时） | 否 | grep 0 |
   | ui/loom_gui.py / editor.py / engine.py | 否 | grep 0 |
   | core_components/module_loader.py、module_registry.py（坏 DLL 自愈链） | 否 | pop_and_fallback 内无落盘调用 |
   全仓 81 个生产 .py 扫描命中 12 处，**全部在 crash_reporter.py 自身**（docstring + def）。无动态 import/反射调用，路径枚举完备。
4. **预期**：启动期 install() → 未处理异常落 `崩溃日志/crash_*.dmp` + 场景备份。
5. **实际**：无任何进程安装 filter；也无任何 OSError 分支调 write_dump。
6. **差异**：docstring 描述「已接线」，实际「零接线」。属「接线缺失」而非实现缺陷。
7. **可复现验证**：
   ~~~
   py -3.12 %TEMP%/loom_scan11/probe_crash_wiring.py
   扫描生产 .py 数 = 81
   命中: crash_reporter.py:2 :22 :27 :28 :29 :32 :47 :66 :128 :134 :224 :274
   => 生产代码命中数 = 12 (0 = 崩溃落盘从未安装/从未调用)
   ~~~
8. **影响与等级**：**P1**（事故定位能力，非崩溃本身）。只有 `build_all.bat:90` 的 `crash_reporter_check.py` 让这条能力「看起来存在」——
   验证资产在跑、产品路径未接。core_components/注册表格式与契约设计说明.txt:157 承诺的
   「ctypes OSError → write_dump → pop_and_fallback」自愈链，**落盘一环是空的**。

---

### P-03 · 编译版入口 build_entry.py 与源码入口 Loom.py 能力分叉（R-04 未同步）

**【反手 · 证伪】**
1. **判定基准**：①本轮 Loom.py:82-86 自述「同一份发布物从 run_player/game_player 启动是 Vk，从 Loom.py 启动却是 GL…」；
   ②发布物由 `tests/_tmp/assemble_release.py:58` 从 `Loom/Loom/build_entry.dist` 组装，`解释器.json` 的 main_exe = Loom.exe。
2. **代码证据**：build_entry.py:305-306 与 :336-337 均为 `engine = PlayerApp(...)`（GL 硬编码）；
   build_entry.py 全文 `--backend` 命中 0、`resolve_backend` 命中 0；`ensure_editor_single_instance` 全仓仅 Loom.py:348-349；
   build_entry.py 无 `_self_check_sources`（Loom.py:213-266）、无 `LOOM_REMOTE_MODE`。
3. **推理链（启动分支枚举，编译版视角）**：
   | 分支 | 编译版实际 | 源码入口 |
   |---|---|---|
   | `--benchmark` | 同 | 同 |
   | `--bench` | 存在但必崩（P-04） | **不存在** |
   | `--run` | PlayerApp（GL），忽略 --backend/render_api | `_launch_player`（Vk/GL/auto） |
   | 游戏配置.json | PlayerApp（GL），无远程模式兜底 | `_launch_player` |
   | 编辑器 | run_loom_gui（**无单实例锁**） | ensure_editor_single_instance → run_loom_gui |
   | `--ui default/minimal` | 仍可走 EditorApp(view=…) | 分支已删，参数被忽略 |
4. **预期**：同一发布物在不同入口行为一致（Loom.py:84-86 明文目标）。
5. **实际**：编译版 GL-only + 无锁 + 无自检；源码版才有 R-04 / 单实例 / 白屏兜底 / AV 自检。
6. **差异**：R-04 的修复面只覆盖源码入口，**用户实际拿到的 exe 没修**。
7. **可复现验证**：
   ~~~
   git -C <repo> diff HEAD --stat -- Loom/build_entry.py   -> 空（本轮未触及）
   grep -c -- "--backend" Loom/build_entry.py               -> 0
   grep -n "ensure_editor_single_instance" Loom/*.py        -> 仅 Loom.py:348-349
   grep -n "build_entry.dist" tests/_tmp/assemble_release.py-> :58
   ~~~
8. **影响与等级**：**P1**。①发布版无法用 --backend/设置切换渲染 API（与 R-04 目标相反）；
   ②发布版仍可「连点开 17 个窗口」；③发布版无 AV 篡改自检。这是本模块最该被立刻看到的一条。

---

### P-04 · build_entry.py `--bench` 必抛 NameError（pygame 未定义）

**【反手 · 证伪】**
1. **判定基准**：build_entry.py:14 用法块「`python build_entry.py --bench <场景> [帧数]`」+ :195-200 文档串。
2. **代码证据**：
   ~~~python
   262        pygame.quit()            # 模块全局查找
   275    if bench_scene is not None:      # --bench 分支
   283        _bench_scene(bench_scene, n_frames=bench_frames)
   284        sys.exit(0)
   286    try:
   287        import pygame                # <<< 晚于 275，且是模块级赋值
   ~~~
3. **推理链（路径枚举）**：`__main__` 顺序固定 benchmark(271) → bench_scene(275) → import pygame(287)。
   - 路径 A：`--bench` → 275 → _bench_scene → 262 行模块全局无 pygame → NameError。
   - 路径 B：`--benchmark` → 271 早退，不触 262。
   - 路径 C：无参/--run → 走 287 之后，pygame 已绑定。
   - 路径 D：外部 `import build_entry; _bench_scene(…)` → 同样 NameError。
   仅 A/D 触达，两者皆失败；无任何分支能在 275 前绑定 pygame。证伪不成立。
4. **预期**：写出 bench_result.txt 并 `sys.exit(0)`（编译版 `--windows-disable-console` 靠文件收结果）。
5. **实际**：结果文件已写出，随后 NameError traceback → 进程 exit 1。
6. **差异**：文件有、退出码失败 → CI/对拍台把「测速成功」判成「构建失败」。
7. **可复现验证**（探针 D，全桩，不碰真 GL）：
   ~~~
   py -3.12 %TEMP%/loom_scan11/probe_bench_entry.py
   模块全局里有 'pygame' 吗: False
     File ".../build_entry.py", line 262, in _bench_scene
       pygame.quit()
   NameError: name 'pygame' is not defined
   bench_result.txt 是否已写出: True
   ~~~
8. **影响与等级**：**P1**（编译版测速/对拍入口完全不可用）。487120c 注释称 pygame.quit 负责 font/mixer 反初始化——
   该副作用在 GLFW 化后已无必要（Loom.py 的等价整段已删）。

---

### P-05 · build_game.py `--output` 无守卫 → `--force` 可删除引擎源码根/仓库根

**【反手 · 证伪】**
1. **判定基准**：build_game.py:11-13 用法「`--output 发布夹`」+ :101「`--force 输出夹已存在时允许覆盖`」；语义边界是**发布夹**。
2. **代码证据**：
   ~~~python
   149    out = os.path.abspath(args.output or os.path.join(BIN_DIR, '发布', args.name))
   150    if os.path.isdir(out) and not args.force:
   151        raise SystemExit("发布夹已存在 (用 --force 覆盖): %s" % out)
   152    if os.path.isdir(out):
   153        shutil.rmtree(out)      # <<< 无 out 与 BIN_DIR/仓库根/盘根 的任何比较
   154    os.makedirs(out, exist_ok=True)
   ~~~
3. **推理链（路径枚举）**：`out` 三种来源（绝对/相对/缺省）× isdir 两态 × --force 两态 = 12 条；
   仅「isdir 为真 且 --force」进入 153 行，而该组合下代码**没有任何**路径合法性判断
   （无 `out == BIN_DIR` 检查、无 `os.path.commonpath`、无盘根检查、无「out 内含 build_game.py」检查）。证伪不成立。
4. **预期**：`--force` 只删除上次构建产生的发布夹。
5. **实际**：`--output . --force` → rmtree(引擎源码根)；`--output .. --force` → rmtree(仓库根，含 .git)。
6. **差异**：破坏性操作作用域由用户字符串直接决定，无二次确认。
7. **可复现验证**（探针 E：**拦截 rmtree，未真正删除**）：
   ~~~
   py -3.12 %TEMP%/loom_scan11/probe_build_game.py
   --output '.'   -> rmtree('D:/.../Loom(py源代码-工作区)/Loom')      是引擎源码根 = True
   --output './'  -> 同上
   --output '..'  -> rmtree('D:/.../Loom(py源代码-工作区)')           (仓库根)
   --output '<绝对:Loom>' -> 同上
   ~~~
8. **影响与等级**：**P1（数据毁灭）**。一行手滑 = 引擎源码（含 .git）被删；
   且 ui/loom_gui.py:1715-1729 的发布对话框也调该入口（参数由 UI 拼），一旦 UI 允许自定义输出目录，风险从 CLI 扩到所有人。

---

### P-06 · secure 模式「哈希互验」可被同夹改写绕过（防作弊声明不成立）

**【反手 · 证伪】**
1. **判定基准**：game_pack.py:117-119「插件包被修改或校验失败…(防修改校验拦截)」；build_game.py:104-105「secure=插件加密+哈希互验 (竞技防作弊)」。
2. **代码证据**：
   ~~~python
   # game_pack.py:110-121
   expect = (gm or {}).get('config', {}).get('plugins_sha256')
   if expect:
       lpc = plugins_path(pack_dir)
       if _sha256_file(lpc) != expect: raise SystemExit("插件包被修改…")
   # sceneio.py:1014-1024 混淆 = zlib + 单字节 XOR 0x5A + base64，解码器随运行时发布
   _ENC_MAGIC = "LOOMSC1"; _XOR_KEY = 0x5A
   ~~~
3. **推理链（篡改路径枚举）**：
   | # | 篡改对象 | 结果 |
   |---|---|---|
   | A | 只改 .lpc | 拦截（sha 不符） |
   | B | 只改 .lsc 期望值 | 拦截（与 .lpc 不符） |
   | C | 改 .lpc + 把 .lsc 期望值改成新 sha | **通过** |
   | D | 删 .lsc 走 MOD 目录投放 | 走 MOD 分支（无校验） |
   路径 C 无需破解密码学：期望值明文在 .lsc 内，.lsc 编码密钥是常量 0x5A，解码器就在玩家运行时里。
4. **预期**：判定「被修改」并拒绝启动。
5. **实际**：装载成功并执行攻击者提供的 entry 源码。
6. **差异**：校验是「自指」的（被校验对象的期望值由被校验方自己携带），不构成防篡改。
7. **可复现验证**（探针 I）：
   ~~~
   py -3.12 %TEMP%/loom_scan11/probe_pack_integrity.py
   原始: .lpc sha256 = 5583c1a30975963b  .lsc 记录 = 5583c1a30975963b
     合法装载 -> 1 个插件, entry 首行='def on_start(self):'
   攻击者: 改 .lpc + 用引擎自带 decode_blob 改 .lsc 期望哈希
     改写后 .lpc sha256 = 679bcb1f44604a10  .lsc 记录 = 679bcb1f44604a10
     装载结果 -> 1 个插件 (未抛 SystemExit)
     entry 首行 = import os
     files[data/a.txt] = UFdORUQ=          # 'PWNED'
   ~~~
8. **影响与等级**：**P1**（功能与声明不符；威胁面 = 本地发布夹可写，**无提权**、不跨机器传播）。
   「防修改」只能拦「改一半」的误操作，拦不住有意改包；.lpc 的 entry 是**直接 exec 的源码**，
   改包后以玩家权限执行任意代码。是否按 P1 修或降为「门槛级保护」→ 见 §5 人类裁决 Q2。

---

### P-07 · [REGRESSION] `_launch_player` 的 docstring 声明了函数体里不存在的优先规则

**【反手 · 证伪】**
1. **判定基准**：Loom.py:93-98 docstring（本轮新增）：「LOOM_REMOTE_MODE=1 (离屏 GL + Qt 窗口白屏兜底) 强制 GL —— 该模式本身就是
   'GL 不可见时改走离屏读回', 与 Vulkan 无关, **必须优先**」。
2. **代码证据**（本轮 diff 原样）：
   ~~~python
   93  def _launch_player(scene, width=1280, height=800):
   99      from run_player import resolve_backend, run_backend
   100     api = resolve_backend(_cli_backend(sys.argv))
   101     run_backend(api, scene, width=width, height=height)
   ~~~
3. **推理链（路径枚举）**：
   | # | 调用点 | 是否判断 LOOM_REMOTE_MODE | 结果 |
   |---|---|---|---|
   | A | Loom.py:300-303（--run） | 是（在调用 _launch_player **之前**提前 return） | 正确 |
   | B | Loom.py:338（游戏配置.json） | 否 → 直接进 _launch_player | 走 Vk |
   `_launch_player` 的函数体 `co_consts` 中不含 'LOOM_REMOTE_MODE'（探针实测 False）→ 函数体内**没有任何分支**读取该环境变量。
   因此 docstring 的「必须优先」只靠调用点 A 的提前 return 兜住，B 完全不成立。证伪不成立。
4. **预期**：`_launch_player` 内部（或 B 分支）在 `LOOM_REMOTE_MODE=1` 时强制 GL/离屏窗口。
5. **实际**：B 分支照常按 `resolve_backend` 取 vulkan（本仓设置默认 vulkan）。
6. **差异**：注释承诺 vs 字节码事实相反；打包游戏「双击启动」在远程/虚拟显示环境仍会命中 P0-1 白屏。
7. **可复现验证**（探针 G3）：
   ~~~
   py -3.12 %TEMP%/loom_scan11/probe_launch.py
   LOOM_REMOTE_MODE=1 -> run_backend 收到 [('RESOLVED(None)', 'scene.json', {'width': 1280, 'height': 800})]
   LOOM_REMOTE_MODE=0 -> run_backend 收到 [('RESOLVED(None)', 'scene.json', {'width': 1280, 'height': 800})]
   docstring 有 / 函数体字节码里出现: False
   ~~~
8. **影响与等级**：**[REGRESSION] P2**。不是崩溃，但①注释是**本轮新写**的，会让下一个人误以为已处理；
   ②游戏配置分支（打包游戏双击）确实缺白屏兜底，与 4f46650 修的 P0-1 同源。

---

### P-08 · [REGRESSION] `--run` 从「恒 GL」改为「设置默认 vulkan 且无回退」

**【反手 · 证伪】**
1. **判定基准**：Loom.py:93-94「按 --backend > 设置 render_api > 默认 的统一策略」（本轮新增）+ run_player.py:26-38。
2. **代码证据**：
   ~~~python
   # Loom.py:304-306（本轮新增）
   _launch_player(run_scene); sys.exit(0)
   # run_player.py:36-52
   api = (requested or _read_setting('render_api', 'vulkan') or 'vulkan')
   if api == 'auto':   try: _run_vulkan(...)  except: _run_opengl(...)
   if api == 'vulkan': return _run_vulkan(...)      # 无 try/except
   ~~~
3. **推理链（取值枚举）**：api ∈ {vulkan, opengl, auto}（其余归一为 vulkan）。
   - vulkan：无回退（源码事实）→ 无 Vulkan 机器直接抛，落到 Loom.py:353 的 `except Exception` → 「无法启动渲染引擎」+ exit 1；
   - auto：有回退；
   - opengl：原行为。
   本仓 `设置.json:15` 与 `Loom/设置.json:16` 均为 `render_api = "vulkan"`；`resolve_backend(None)` 实测返回 'vulkan'。
   故「不带 --backend」的默认调用落在无回退路径。证伪不成立。
4. **预期**：R-04 目标「同一份发布物行为一致」，且不牺牲原有可用性。
5. **实际**：旧代码 PlayerApp 恒 GL（处处可跑）；新代码默认 vulkan（无驱动即不可跑），除非手改设置或显式 `--backend auto`。
6. **差异**：把「默认必可跑」换成了「默认需 Vulkan 能力」。
7. **可复现验证**（探针 K）：
   ~~~
   py -3.12 %TEMP%/loom_scan11/probe_backend_default.py
   设置.json 现存 render_api = vulkan
   resolve_backend(None)   = vulkan
   resolve_backend('auto') = auto
   ~~~
8. **影响与等级**：**[REGRESSION] P2**（可用性回退）。若产品定位就是「Vulkan 为默认」（与 run_player/game_player 一致），
   本条应转为**提示缺失**：启动失败时应引导用户改 `--backend auto` 或 `设置.json render_api=auto`。是否接受该默认 → §5 Q1。

---

### P-09 · 单实例竞态：首实例窗口未建好时，第二实例**静默消失**

**【反手 · 证伪】**
1. **判定基准**：loom_single_instance.py:1-19（立项动机「连点开 17 个窗口」）与 :66-72（行为约定：激活已有窗口 / 提示后退出）。
2. **代码证据**：
   ~~~python
   77  handle = kernel32.CreateMutexW(None, False, EDITOR_MUTEX_NAME)
   78  err = kernel32.GetLastError()
   80  if err == ERROR_ALREADY_EXISTS:
   81      hwnd = _find_window_by_title(EDITOR_WINDOW_TITLE)   # 窗口还没建时为 0
   82      if hwnd: _activate_window(hwnd)
   84      if scene_path:                                      # <<< 只有带场景才提示
   86          print("[编辑器] 已有编辑器实例在运行。…")
   94      sys.exit(0)
   ~~~
   调用点 Loom.py:348-349：`ensure_editor_single_instance(scene_path=open_scene)`；双击启动时 open_scene is None。
3. **推理链（时序枚举）**：
   | # | 首实例进度 | _find_window_by_title | scene_path | 用户可见反馈 |
   |---|---|---|---|---|
   | A | 窗口已建 | HWND → 激活 | None | 无文字，但窗口被提到前台（可接受） |
   | B | **仍在 import PySide6 / 建窗** | 0 → 不激活 | None | **零输出、直接退出** |
   | C | 同上，但带 --open | 0 → 不激活 | 有值 | 打印一行提示 |
   冷启动（PySide6 首次导入数秒）时路径 B 是**常态**而非边角。证伪不成立。
4. **预期**：第二实例总要给出可见结果（激活窗口 / 提示 / 弹窗）。
5. **实际**：路径 B 全静默，`sys.exit(0)`。
6. **差异**：「防连点」达成，「让用户知道为什么没开」未达成。
7. **可复现验证**（探针 C4：先在本进程占锁，再调函数并捕获 stdout）：
   ~~~
   py -3.12 %TEMP%/loom_scan11/probe_single_instance.py
   本进程先占锁: handle=464 GetLastError=0 (183=ALREADY_EXISTS)
   _find_window_by_title('Loom — 编辑器 (Qt)') -> None
   scene_path=None     -> sys.exit(0), stdout=''        # 零输出
   scene_path='a.json' -> sys.exit(0), stdout="[编辑器] 已有编辑器实例在运行。…"
   ~~~
8. **影响与等级**：**P2**（可用性/可理解性）。另：源码入口只在编辑器分支加锁，
   而**编译版入口根本没加锁**（P-03）→ 现网「连点开 17 个窗口」在发布物上依然成立。

---

### P-10 · `_self_check_sources` 的 NUL 判据比真实故障窄一个数量级

**【反手 · 证伪】**
1. **判定基准**：Loom.py:213-222 自检目标：「导致 Python 启动时抛 source code string cannot contain null bytes，用户难以理解…给出明确指引」。
2. **代码证据**：
   ~~~python
   237        with open(fp, 'rb') as f: head = f.read(8192)             # 只读前 8KB
   240        if len(head) >= 16 and head.count(b'\x00') == len(head):   # 要求「全部」为 0
   241            bad.append(fp)
   ~~~
3. **推理链（损坏形态 × 命中）**：
   | 损坏形态 | Python 实际报错 | 本检查 |
   |---|---|---|
   | 前 8KB 全 0（整文件置零） | SyntaxError | 命中 |
   | 前 100 字节 0 + 正常代码 | SyntaxError | **漏** |
   | 代码中间 1 个 NUL | SyntaxError | **漏** |
   | 前 8KB 正常 + 第 9000 字节起为 0 | SyntaxError | **漏** |
   | 空文件 / <16 字节全 0 | 未必报错 | 跳过（有意） |
   判据是「head 内**每一个**字节都是 0」，覆盖率远小于触发条件「文件内**存在**任一 NUL」。证伪不成立。
4. **预期**：能拦下 docstring 描述的那类报错。
5. **实际**：只拦最极端一种；其余仍抛 SyntaxError，用户仍看到无法理解的报错。
6. **差异**：判据过窄（OVERFIT-HARDCODE）。
7. **可复现验证**（探针 H）：
   ~~~
   py -3.12 %TEMP%/loom_scan11/probe_selfcheck.py
   前 8192 字节全 0                    报告=True  sys.exit=1
   前 100 字节全 0 + 正常代码          报告=False sys.exit=None
   正常代码中间插入 1 个 NUL           报告=False sys.exit=None
   前 8192 正常 + 第 9000 字节 NUL     报告=False sys.exit=None
   真实解释器: 导入失败 -> SyntaxError: source code string cannot contain null bytes
   ~~~
8. **影响与等级**：**P2**（自检宣称的能力与实现不符；用户侧仍是「神秘崩溃」）。

---

### P-11 · `clock_from_settings` 无容错契约，唯一生产调用方把异常整段吞掉 → 半初始化

**【反手 · 证伪】**
1. **判定基准**：core_clock.py:157-163「设置.json -> FixedStepClock」；engine.py:478-482 的兜底注释「设置读取失败的兜底」。
2. **代码证据**：
   ~~~python
   # core_clock.py:164-171（无 try）
   lf = float(settings.get("logic_fps", 30))
   sdt = float(settings.get("phys_substep_dt", 0) or 0)
   pf = float(settings.get("physics_fps", 0))
   # engine.py:438-439
   self._split_enable = split_enabled(_s)                                   # 先赋值
   self._clock = (clock_from_settings(_s) if self._split_enable else None)  # 抛 -> _clock 未赋值
   # engine.py:478-482
   except Exception: pass
   self._split_enable = getattr(self, '_split_enable', False)   # 停在 True
   self._clock = getattr(self, '_clock', None)                  # 变 None
   ~~~
3. **推理链（取值枚举）**：
   | 设置值 | clock_from_settings | engine 侧结果 |
   |---|---|---|
   | 数字 / 缺键 | 正常 | 正常 |
   | `null`（JSON null） | TypeError | 半初始化：_split_enable=True + _clock=None + 后续设置项全丢 |
   | `""` / `abc` | ValueError | 同上 |
   | `phys_substep_dt="x"` | ValueError | 同上 |
   异常点固定为 `float()`；engine 的 `except: pass` 不区分配置项 → 一坏全丢（interp_mode / frustum_cull / pbr_enabled / frame_buffer 全部退回默认）。证伪不成立。
4. **预期**：坏值 → 该键退回默认 + 一条可见日志，其余设置照常生效。
5. **实际**：整段设置被丢弃，且**无任何输出**；`_split_enable` 与 `_clock` 不一致。
6. **差异**：归属 SEM-SILENT 类：用户改 `pbr_enabled=false` 未生效且无从知晓原因。
7. **可复现验证**（探针 A4）：
   ~~~
   py -3.12 %TEMP%/loom_scan11/probe_clock.py
   {'logic_fps': None}      -> TypeError: float() argument … not 'NoneType'
   {'logic_fps': ''}        -> ValueError: could not convert string to float: ''
   {'logic_fps': 'abc'}     -> ValueError
   {'phys_substep_dt': 'x'} -> ValueError
   ~~~
   （engine 侧吞异常为源码事实；未另跑真实 EditorApp 以免启动 GUI。）
8. **影响与等级**：**P2**。手改 `设置.json` 是本项目**明确支持**的操作（B7b 注释：「UI 暂不暴露, 手动改 设置.json 切换」），
   一次笔误即静默丢掉整段配置。

---

### P-12 · 发布夹整目录携带 C 源码 / 头文件 / 构建脚本 / 开发文档

**【反手 · 证伪】**
1. **判定基准**：build_game.py:7-8「发布夹…目录里无任何明文脚本/场景」+ game_pack.py:6-7「玩家拿不到源码」。
2. **代码证据**：
   ~~~python
   162    # M4 AUDIT-46: 随同发布独立 Player 核心组件 DLL (pipeline, script, ckernels, registry)
   163    for sub in ('core_components', 'ckernels'):
   166        if os.path.isdir(s_dir):
   167            shutil.copytree(s_dir, d_dir, dirs_exist_ok=True)   # 整目录，无扩展名过滤
   ~~~
3. **推理链**：拷贝粒度是**目录**（非白名单）→ 源目录里有什么就带什么。实测源目录：
   | 类型 | 数量 | 说明 |
   |---|---|---|
   | .c | 41 | loom_kernels.c / loom_pipeline.c / physics / script 等 C 内核源码 |
   | .h | 30 | loom_module.h / loom_pipeline.h 等 ABI 头 |
   | .bat | 8 | build_*.bat |
   | .lib/.exp | 15 | 链接产物 |
   | .txt | 1 | 注册表格式与契约设计说明.txt（12.3 KB 设计文档） |
   | .bak | 1 | loom_physics.c.bak |
   合计 **96 文件 / 2,123,920 字节（约 2.0 MB）**。无白名单、无扩展名过滤 → 证伪不成立。
4. **预期**：发布夹只含运行期必需件（.dll + registry.json + manifest）。
5. **实际**：C 源码、ABI 头、构建脚本、内部设计文档全部随包分发。
6. **差异**：与「玩家拿不到源码」定位冲突；.lsc 的混淆在这一层被直接绕过。
7. **可复现验证**：
   ~~~
   Get-ChildItem ckernels,core_components -Recurse -File |
     ? Extension -in '.c','.h','.lib','.exp','.bat','.txt','.bak' | Measure-Object Length -Sum
   Count : 96   Sum : 2123920
   ~~~
8. **影响与等级**：**P2**（信息泄露 + 体积；非功能故障）。历史上是有意为之（AUDIT-46 要带 Player 组件），
   缺的是「只带 .dll + 清单」的过滤。

---

### P-13 ~ P-19 · P3 项（8 字段等价展开：基准 / 证据 / 路径枚举 / 预期 / 实际 / 差异 / 验证 / 等级）

#### P-13 · LOOM_PROFILE 计数在异步逻辑线程下系统性偏低

| 段 | 内容 |
|---|---|
| 1 基准 | loom_profiler.py:16-21「记录 fn 阶段耗时到 _stage_times（累计 ms）」；engine.py:493 异步逻辑线程**默认开启** |
| 2 证据 | loom_profiler.py:27-28 与 :40-41 均为 d[name] = d.get(name, 0.0) + dt |
| 3 路径枚举 | 写者：逻辑线程 loom_logic_thread.py:64,68 的 _profile('logic_step')；渲染线程 engine.py:1174 / loom_render.py:710 / ui/loom_gui.py:244,257。两线程同时写同一 dict → 读改写可交错 |
| 4 预期 | 累计值 = 各段真实总和（误差仅浮点） |
| 5 实际 | 2 线程 x 200k 次写入，期望 400000，实得 337319（**丢 15.7%**） |
| 6 差异 | 诊断数字偏低，越并发越低；「帧时间 4.95→3.47ms」这类结论的基线本身带 15% 噪声 |
| 7 验证 | py -3.12 %TEMP%/loom_scan11/probe_timescale.py（J2 段）→ 实际 337319.0, 丢失 62681 |
| 8 等级 | **P3**（诊断数据正确性，不影响玩法）。修复方向：每线程本地 dict + 帧尾合并，或改用不可变计数容器 |

#### P-14 · user32 全部无 argtypes/restype；HWND 按 32 位默认转换

| 段 | 内容 |
|---|---|
| 1 基准 | loom_single_instance.py:29-63 直接调 ctypes.windll.user32；同仓 crash_reporter.py:89 用 WinDLL(..., use_last_error=True) + 完整 argtypes（C14） |
| 2 证据 | 实测 8 个 user32 函数 argtypes=None restype=c_long；:74-76 只为 CreateMutexW 设了原型 |
| 3 路径枚举 | ①FindWindowW 返回值按有符号 32 位截断；②GetWindowTextW 等参数按 c_int 转换；③GetLastError() 直读线程 last-error（未用 use_last_error 的保存槽） |
| 4 预期 | HWND 为 64 位指针量级，原型应显式声明 |
| 5 实际 | HWND=0x1_0000_0000 传参 → ArgumentError: int too long to convert；0x7FFFFFFF / 0x80000000 可过 |
| 6 差异 | 当前 Windows 句柄实际值都很小，故**今日不发作**；一旦分配的 HWND 落在高位即抛异常/激活错窗口 |
| 7 验证 | py -3.12 %TEMP%/loom_scan11/probe_single_instance.py（C1/C2 段） |
| 8 等级 | **P3**（潜在）。修复方向：声明 argtypes/restype + use_last_error=True + ctypes.get_last_error() |

#### P-15 · 注释「默认收紧到 0.05s」与形参默认 0.333 矛盾

| 段 | 内容 |
|---|---|
| 1 基准 | core_clock.py:66-68 注释：「步数上限自适应…每渲染帧最多追 maximum_logic_delta 秒…**默认收紧到 0.05s** — 逻辑帧贵时 1 帧/渲染帧」 |
| 2 证据 | core_clock.py:32 形参 maximum_logic_delta=0.333；:69-71 自适应上限 = round(max_delta/fdt) |
| 3 路径枚举 | 只有 _max_steps_explicit is None 时走自适应；clock_from_settings 不传该参 → 生产恒走自适应 → 上限 = round(0.333*30) = 10 |
| 4 预期 | 若注释成立，上限应为 round(0.05*30)=2 |
| 5 实际 | 实测 maximum_logic_delta=0.333, max_steps_per_frame=10；单帧喂 10.0s → 实跑 9 逻辑帧（0.30s 逻辑时间） |
| 6 差异 | 注释口径比实现保守 6.7 倍；tests/test_core_clock.py:88-94 断言的是 10 与 9 步 —— 测试站实现一边，注释单独过时 |
| 7 验证 | probe_clock.py（A2 段） |
| 8 等级 | **P3**（文档）。若 0.05 才是本意，则是 6.7 倍死亡螺旋保险缺口 → 人类裁决 Q3 |

#### P-16 · 本轮恢复的 _make_editor_view 在 Loom.py 内是死代码

| 段 | 内容 |
|---|---|
| 1 基准 | Loom.py:66-69 恢复说明：「editor.py:137 与 build_entry.py:77 仍调用本函数 —— 删除直接造成 ModuleNotFoundError」 |
| 2 证据 | Loom.py 全文仅 :61 一处定义，**无任何调用点**；editor.py:136-138 直接 from ui.minimal_editor_view import MinimalEditorView（不经 Loom）；build_entry.py:71 自带同名函数 |
| 3 路径枚举 | Loom.py 主流程 6 条分支（benchmark / run / 远程 / 游戏配置 / 编辑器 / 兜底异常）：无一条引用 _make_editor_view；--ui 分支在 Loom.py 中已不存在（:338 直接进 Qt 编辑器） |
| 4 预期 | 恢复后应被某分支使用（否则「删除导致 ModuleNotFoundError」的因果不成立） |
| 5 实际 | 仅 tests/test_editor_ui.py:424、tests/test_guiswitch.py:273-278 调用 → 恢复的实际收益 = 让两个测试继续绿 |
| 6 差异 | 注释因果链在 Loom.py 侧不成立；真正需要它的是 build_entry.py，而它一直都有 |
| 7 验证 | grep -n "_make_editor_view" Loom.py（仅 61 行） |
| 8 等级 | **P3**（可维护性/误导），不影响运行 |

#### P-17 · --backend=opengl 等号形式被静默忽略

| 段 | 内容 |
|---|---|
| 1 基准 | Loom.py:80-86「取 --backend <vulkan|opengl|auto>」，注释只示范空格分隔（C16） |
| 2 证据 | for i, a in enumerate(argv): if a == "--backend" and i + 1 < len(argv) |
| 3 路径枚举 | 空格形式 → 命中；等号形式 → 不命中 → 返回 None → 回落设置；无值结尾 → None；重复出现 → 取第一个 |
| 4 预期 | 常见 CLI 两种写法等效（或至少报错） |
| 5 实际 | ['--backend=opengl'] -> None（静默回落 vulkan，用户以为切换成功） |
| 6 差异 | 无声失败（SEM-SILENT） |
| 7 验证 | probe_launch.py（G1 段） |
| 8 等级 | **P3**。建议加 startswith('--backend=') 分支，或未知参数直接报错 |

#### P-18 · 构建器对非 UTF-8 游戏脚本无容错

| 段 | 内容 |
|---|---|
| 1 基准 | build_game.py:43-56 _collect_scripts「收集游戏脚本目录里的 .py 源码」；:11-13 用法（CI 步骤） |
| 2 证据 | :54 open(..., 'r', encoding='utf-8') 无 errors 参数、无 try |
| 3 路径枚举 | ①纯 ASCII/UTF-8 → 正常；②目录不存在 → 返回 []（已容错）；③GBK/ANSI → UnicodeDecodeError |
| 4 预期 | 构建器对玩家脚本给出可读错误并指出文件 |
| 5 实际 | 直接抛 UnicodeDecodeError: 'utf-8' codec can't decode byte 0xd6 in position 2 → 构建中止 |
| 6 差异 | 中文环境下 GBK 脚本很常见（脚本目录由用户手放） |
| 7 验证 | probe_build_inputs.py（L1 段） |
| 8 等级 | **P3**（构建期错误，不污染发布物） |

#### P-19 · 损坏 .lpc 在哈希通过后抛 AttributeError（错误信息误导）

| 段 | 内容 |
|---|---|
| 1 基准 | game_pack.py:101-107「缺/被改 -> SystemExit 报错（缺包/防修改语义）」 |
| 2 证据 | :120 data = load_plugins_pack(pack_dir) → :122 for item in data.get('plugins', []) 未判 None |
| 3 路径枚举 | ①.lpc 缺失 → SystemExit（正确）；②sha 不符 → SystemExit（正确）；③sha 相符但 decode_blob 返回 None（LOOMSC1 头 + 非法载荷）→ None.get → AttributeError |
| 4 预期 | 与「损坏」同类，走 SystemExit 并给出可读原因 |
| 5 实际 | AttributeError: 'NoneType' object has no attribute 'get'；Loom.py:333 只捕 SystemExit → 落到 :353 打印「无法启动渲染引擎」 |
| 6 差异 | 错误分类错误 + 提示与真实原因无关 |
| 7 验证 | probe_build_inputs.py（L2 段） |
| 8 等级 | **P3** |

---

## 2.2 证伪成立的项（P-DISPROVED，附证伪链路径枚举）

### P-20 · 定步时钟长跑累积误差 → **DISPROVED**

| 段 | 内容 |
|---|---|
| 1 基准 | core_clock.py:5-18「accumulator 模型」；tests/test_core_clock.py:65-105（步数/alpha/死亡螺旋口径） |
| 2 证据 | core_clock.py:111-132：self._acc += dt / self._acc -= fdt 每步扣减 |
| 3 路径枚举 | ①dt 恰为 fdt 整数倍 → 余量归零；②dt=1/120 而 fdt=1/30 → 每 4 帧一周期归零；③dt 任意 → 余量始终 < fdt（循环条件保证）；④达 max_steps → 余量清零（死亡螺旋保险）。浮点误差每步约 1 ulp（1e-17 秒），且「加 dt / 减 fdt」不放大 |
| 4 预期 | 长时间运行后逻辑时间 = 墙钟时间（±常数） |
| 5 实际 | 1.2e6 帧（等价 10000 秒）后 steps=300000、期望 300000.000000、误差 0.000000000 步；逻辑时间误差 0.000e+00 s |
| 6 差异 | **无差异**。余量周期性归零（每 4 帧一次），绝对误差不累积 |
| 7 验证 | probe_clock.py（A1 段） |
| 8 等级 | 无（保留此项是为给「定步时钟累积误差」这一重点一个**可引用数据结论**：本实现不漂移） |

### P-21 · step_once 多跑或少跑 → **DISPROVED**

| 段 | 内容 |
|---|---|
| 1 基准 | core_clock.py:87-93「强制恰好跑 1 个逻辑帧」 |
| 2 证据 | self._acc += self.fixed_dt; return self.advance(0.0) |
| 3 路径枚举 | 进入前余量 r ∈ [0, fdt)（循环不变式）→ 注入后 r+fdt ∈ [fdt, 2fdt) → while 最多成立 1 次；advance(0.0) 的 dt=0 不额外注入 |
| 4 预期 | 每次 (1, N) |
| 5 实际 | 有余量 0.016667 时连续两次 step_once → (1,2) / (1,2) |
| 6 差异 | 无 |
| 7 验证 | probe_clock.py（A3 段） |
| 8 等级 | 无 |

### P-22 · crash filter 掩盖异常/二次崩 → **DISPROVED**（但「未安装」见 P-02）

| 段 | 内容 |
|---|---|
| 1 基准 | crash_reporter.py:13-18「回调只做两件事…然后立即返回 EXCEPTION_EXECUTE_HANDLER 让进程退出」 |
| 2 证据 | :248-267 全部逻辑包在 try/except Exception: pass，返回 1；:126-131 _say 自身再包一层 |
| 3 路径枚举 | ①备份回调抛 → 内层 except 吞，继续 dump；②_do_dump 抛 → 自身 :196-198 兜底返回 None；③filter 顶层任意异常 → :265 吞；④返回 1 → 进程带异常码终止。**不存在**「吞掉后让进程继续跑」的路径 |
| 4 预期 | 不掩盖、不静默继续 |
| 5 实际 | 与预期一致（返回码 1 = 进程退出）；限流路径不影响 filter |
| 6 差异 | 无。真正的问题是「压根没装」（P-02），不是「装了但掩盖」 |
| 7 验证 | 源码路径枚举 + probe_crash_wiring.py（证明未安装） |
| 8 等级 | 无 |

### P-23 · LOOM_QUIET 误吞运行期错误 → **DISPROVED**

| 段 | 内容 |
|---|---|
| 1 基准 | loom_log.py:12-14「保留原则：运行期错误（[脚本]出错 / [物理]异常）继续 print」 |
| 2 证据 | loom_log.py:24-31 只包启动信息；错误路径用 print 而非 verbose |
| 3 路径枚举 | 全仓 verbose 调用点 6 处：engine.py:549,552,577、parallel.py:243、loom_gui.py:174,548 —— 全为启动期一次性状态；错误路径（如 engine.py:1357「[脚本]…出错」）用 print |
| 4 预期 | 静默模式不隐藏错误 |
| 5 实际 | 一致 |
| 6 差异 | 无 |
| 7 验证 | grep -n "verbose(" Loom/*.py Loom/ui/*.py（6 处，均为启动信息） |
| 8 等级 | 无 |

### P-24 · 发布夹漏拷 assets/ → **DISPROVED**（按白盒契约）

| 段 | 内容 |
|---|---|
| 1 基准 | build_game.py:21-22 明确声明「externals（obj/音频等素材）：随夹拷贝约定…v1 不自动收集, 文档写明」 |
| 2 证据 | build_game.py:155-167 只拷 runtime dist + core_components + ckernels；game_pack.py:16「externals（随夹拷贝的素材名, v1 留位）」 |
| 3 路径枚举 | assets/ 消费方枚举：editor.py:1091,1115,1148,1302,1323 全部是**编辑器资源浏览器**；玩家侧 runtime/game_player 无 assets 读取点（grep 'assets' 无命中） |
| 4 预期 | 玩家不需要 assets/ 目录即可启动 |
| 5 实际 | 与预期一致（素材走「随夹拷贝约定」） |
| 6 差异 | 无实现缺陷；属**已声明的 v1 设计缺口**，不是 bug |
| 7 验证 | grep -rn "assets" Loom/*.py（仅 editor.py / agent_commands.py） |
| 8 等级 | 无（若要升级为 P2，需人类裁决「素材自动收集是否进 v1 范围」→ §5 Q4） |

### P-25 · 单实例锁误伤 --run 多开 → **DISPROVED**

| 段 | 内容 |
|---|---|
| 1 基准 | loom_single_instance.py:6-11「仅 Qt 编辑器模式加锁 / --run 不加锁 / 游戏配置玩家模式不加锁」 |
| 2 证据 | 全仓唯一调用点 Loom.py:348-349，位于「无游戏配置 → 编辑器」分支内部 |
| 3 路径枚举 | Loom.py 分支：benchmark(:275) 早退 → --run(:296-306) 早退 → 游戏配置(:320-339) 早退 → 编辑器(:340-352) **才**加锁 |
| 4 预期 | 播放器可多开 |
| 5 实际 | 一致（--run / 游戏配置分支都先 sys.exit(0)，不会走到 348） |
| 6 差异 | 无 |
| 7 验证 | 源码分支枚举 + grep -n ensure_editor_single_instance（2 处，均在本模块内） |
| 8 等级 | 无 |

### P-26 · write_dump 限流读改写竞态 → **DISPROVED**

| 段 | 内容 |
|---|---|
| 1 基准 | crash_reporter.py:212-213「限流…调用方必须持锁」+ :66-67「只护 write_dump 手动路径；filter 路径不碰锁」 |
| 2 证据 | :235-241 with _ST['lock']: ... _rate_ok() ... _do_dump() |
| 3 路径枚举 | ①多线程同时 write_dump → 串行（锁）；②filter 路径 → 不调 _rate_ok，不碰锁；③备份回调 _touch_backup 在锁外（:242-245），但只读 _ST['backup_fn']，无读改写 |
| 4 预期 | 限流计数一致 |
| 5 实际 | 一致 |
| 6 差异 | 无（唯一瑕疵：dump 失败也消耗配额，属有意保守，不构成缺陷） |
| 7 验证 | 源码路径枚举（未构造并发崩溃，风险不可控） |
| 8 等级 | 无 |

---

## 2.3 信息不足项（P-UNKNOWN，各附已尝试探针与下一步）

### P-27 · 未开 use_last_error 时 GetLastError 是否会被 ctypes 调用路径清掉

- **已尝试**：probe C 直接读 CreateMutexW.argtypes/restype（均 None），并连续调用 CreateMutexW → GetLastError，
  观察到同进程首次创建返回 0、二次创建走 183 分支（**功能上正确**）。
- **为什么仍 UNKNOWN**：ctypes 文档要求「跨调用可靠取错误码」必须 use_last_error=True + ctypes.get_last_error()；
  未开时 CPython 内部可能调用其它 Win32 API 覆盖线程 last-error，**无法在 CI 稳定复现**（需要精确插入一次会清错误码的调用）。
- **定它需要的信息**：一次「CreateMutexW 与其后 GetLastError 之间插入 Python 分配/GC」的注入实验；
  或直接采用同仓 crash_reporter.py 的正确写法后本项自动关闭。
- **建议下一步探针**：在两次调用之间插入 ctypes.create_string_buffer(1) 循环，1000 次统计 183 命中率（<100% 即坐实）。

### P-28 · secure 模式是否存在发布链路之外的可信锚（签名 / 服务端校验 / Hub 侧校验）

- **已尝试**：本仓内 grep sig / ed25519 / hmac / public key 与 Hub 侧校验点 → 无命中；probe I 证明同夹改写可通过。
- **为什么仍 UNKNOWN**：可信锚可能存在于 **LoomHub** 仓库或发行流程（例如 Hub 下载后校验、编译版另有哈希白名单），
  本模块范围只到 Loom/；不能据「本仓没有」断定「产品没有」。
- **定它需要的信息**：LoomHub/ 侧对发布夹/游戏包的校验代码，或产品文档中「secure 模式的威胁模型」一节。

---

## 3. 统计

| 项 | 数量 |
|---|---|
| 粗筛疑似项 | **28**（P-01 ~ P-28） |
| 跳过登记项 | **8**（SKIP-01 ~ SKIP-08，均附四类理由之一） |
| P-PROVED | **19**（P1×6 / P2×6 / P3×7） |
| P-DISPROVED | **7**（P-20 ~ P-26） |
| P-UNKNOWN | **2**（P-27、P-28） |
| P-CONTRADICTION | **0** |
| [REGRESSION] | **2**（P-07、P-08，均由本轮未提交的 Loom.py 改动引入） |
| 定向探针 | **12 个脚本 / 15 次运行**（见 §0.3；未跑 tests/run_all.py） |

**P-CONTRADICTION = 0 的说明**（方法论要求解释）：本模块没有出现「证伪链声称覆盖全路径且无 bug，同时证真链又构造出反例」的项。
原因可核对：19 条 PROVED 的反手链都在第 3 段的路径枚举表里**明确点出一条失败路径**（如 P-01 的三态表的第 1 态、P-05 的 12 条组合中的一条），
即「证伪失败」发生在枚举阶段而非构造阶段，不存在两条链同时成立；7 条 DISPROVED 的正手链则全部卡在
「无法构造最小复现」（P-20 是拿到实测 0 误差、P-24/P-25 是被白盒契约/分支枚举排除），也不构成矛盾。

按文件分布：Loom.py 5 项（P-07/P-08/P-10/P-16/P-17）、build_entry.py 3 项（P-03/P-04 + 与 Loom.py 的分叉）、
build_game.py 3 项（P-05/P-12/P-18）、game_pack.py 3 项（P-06/P-19/P-28）、core_clock.py 4 项（P-11/P-15/P-20/P-21）、
loom_logic_thread.py 1 项（P-01）、crash_reporter.py 3 项（P-02/P-22/P-26）、loom_single_instance.py 3 项（P-09/P-14/P-27）、
loom_profiler.py 1 项（P-13）、loom_log.py 1 项（P-23）、交叉 1 项（P-24/P-25 跨 build_game/Loom.py）。

---

## 4. 修复建议排序（只给方向，不含代码）

### 4.1 P0/P1（建议本轮内处理）

| 序 | 项 | 方向 |
|---|---|---|
| 1 | **P-03** 编译版入口分叉 | 把 Loom.py 的本轮改动（--backend 解析 / _launch_player / 单实例 / 自检）**逐条同步进 build_entry.py**，或反向收敛为「build_entry.py 只做 `exec(open('Loom.py'))` 式薄壳」。同步后必须重跑 assemble_release 并实机验证 exe。 |
| 2 | **P-05** build_game 删除守卫 | 在执行 rmtree 前加三道闸：①out 不得等于/包含 BIN_DIR ②out 不得是盘根或其父 ③out 必须已存在某个构建标记文件（如 游戏包.lsc）才允许 --force 删除。 |
| 3 | **P-02** crash_reporter 接线 | 在 Loom.py 与 build_entry.py 的「最早期」（import 插件之前）调 install()；在 module_loader 捕获 OSError 的分支调 write_dump()；并补一条「启动后 install() 返回 False 时 stderr 明示」的可见性。 |
| 4 | **P-01** 逻辑线程停止 | 停止标志改为**局部持有**（把 Event 作参数传进线程函数，循环判局部变量），并保证 stop 内 join 前不提前把引用置空；补一条「stop 后线程数回到 0」的自测。 |
| 5 | **P-04** --bench NameError | 把 pygame 的导入提到 --bench 分支之前，或直接删除该行（GLFW 化后已无 font/mixer 需要反初始化的依赖）。 |
| 6 | **P-06** secure 模式定位 | 二选一：①降级为「门槛级」并在文档/UI 明写「不防有意改包」；②引入外部锚（构建时用私钥签名 config，运行时用内置公钥验签）。 |

### 4.2 P2（建议下个迭代）

| 序 | 项 | 方向 |
|---|---|---|
| 7 | **P-07** [REGRESSION] | 要么在 _launch_player 内实现 LOOM_REMOTE_MODE 优先（与 docstring 一致），要么删掉该段声明并在游戏配置分支补同样的提前 return。二者选一，不要留「注释说做了、代码没做」。 |
| 8 | **P-08** [REGRESSION] | 默认值改为 auto（无 Vk 自动回退 GL），或在 vulkan 启动失败时打印「改用 --backend auto / 设置 render_api=auto」的可执行指引。 |
| 9 | **P-09** 单实例静默 | scene_path 为 None 时也输出一行提示；窗口未就绪时给「首实例正在启动，请稍候」而不是无声退出；建议加 500ms 轮询重试激活。 |
| 10 | **P-10** 自检判据 | 改为「前 N KB 中存在任一 NUL」即报，并把提示里的文件路径按「可能被 AV 篡改」归因。 |
| 11 | **P-11** 设置容错 | clock_from_settings 逐键 try + 回退默认；engine 侧把「某一键坏」与「整段失败」区分开并打一行 stderr。 |
| 12 | **P-12** 发布夹过滤 | 只拷 .dll + registry.json + manifest.json（白名单），排除 .c/.h/.lib/.exp/.bat/.txt/.bak。 |

### 4.3 P3（随手清理）

| 序 | 项 | 方向 |
|---|---|---|
| 13 | P-13 | 插桩计数改每线程本地 + 帧尾合并 |
| 14 | P-14 | 统一声明 user32/kernel32 的 argtypes/restype，改用 use_last_error=True |
| 15 | P-15 | 注释与默认值对齐（并明确 0.05 / 0.333 哪个是本意，见 Q3） |
| 16 | P-16 | 要么把 --ui 分支接回 Loom.py，要么删函数并改注释 |
| 17 | P-17 | 支持 --backend= 形式或对未知参数报错 |
| 18 | P-18 | _collect_scripts 对解码失败给「文件名 + 建议另存为 UTF-8」 |
| 19 | P-19 | load_plugins_pack 返回 None 时按「损坏」走 SystemExit |

---

## 5. 需要人类裁决的封闭问题

### Q1（P-08）渲染后端默认值

- 背景：本轮把 `--run` 从「恒 GL」改为「设置 render_api（本仓默认 vulkan）」，而显式 vulkan 分支无回退。
- 已有证据：run_player.py:36-52 源码；设置.json:15 = vulkan；探针 K 输出。
- **问题（选一个）**：
  A. 保持默认 vulkan（与 run_player/game_player 一致），失败时只补提示 → 本条降为 P3；
  B. 默认改为 auto（无 Vk 自动回退 GL）→ 本条按 P2 修；
  C. 默认改为 opengl（保守），Vulkan 需显式开启。
- 代价：A 最一致但会让无 Vulkan 机器首次运行失败；B 最稳但会让「默认就是 Vulkan」的产品叙事变模糊；C 与「Vulkan 对齐」方向相反。

### Q2（P-06）secure 模式的威胁模型

- 背景：期望哈希与被校验文件同夹同链，解码密钥是常量；同夹改写可通过（探针 I）。
- **问题**：secure 模式要防的是
  A. 只有「误操作/半改」→ 现状即达标，本条降为 P3 并在文档写明「不防有意改包」；
  B. 还要防「有意改包」→ 必须引入外部锚（签名/公钥/服务端），本条升为 P1 并按此修。
- 代价：B 需要在构建链路加签名密钥管理（发布流程变重）。

### Q3（P-15）死亡螺旋保险的实际口径

- 背景：注释写「默认收紧到 0.05s」，形参默认 0.333，test_core_clock.py:88-94 断言 10/9 步。
- **问题**：本意是 A. 0.333（现状，允许单帧追 10 个逻辑帧）／B. 0.05（改默认值 + 改测试，单帧最多 2 帧）。
- 代价：A 在重场景卡顿时会一次补 10 个逻辑帧（物理/脚本耗时叠加，可能加重卡顿）；B 更平滑但会「时间膨胀」更明显。

### Q4（P-24）素材自动收集是否进 v1

- 背景：build_game.py 文档明确「externals v1 不自动收集」，玩家需手工放素材。
- **问题**：A. 维持现状（文档已声明）／B. v1 增加「按场景引用自动收集 externals」。
- 代价：B 需要新增引用扫描与相对路径重写，属功能开发。

### Q5（P-03）两个入口的收敛策略

- 背景：Loom.py 与 build_entry.py 已分叉，本轮再次拉大（47 行只进了一边）。
- **问题**：A. build_entry.py 改为薄壳转调 Loom.py（一份逻辑两处入口）／B. 保持双文件，靠 CI 断言两边关键能力齐平／C. 删除 build_entry.py，Nuitka 直接以 Loom.py 为入口。
- 代价：C 最彻底但要验证 Nuitka 对 Loom.py 的 --bench 等历史能力是否还需要（编译版测速依赖它）。

---

## 附录 A · 关键探针最小复现片段（可直接粘贴执行）

第三方复现：`sys.path` 指向 Loom 目录，`LOOM_NO_SAVE_MIGRATE=1`。

### A.1 P-01 逻辑线程停不下来（假宿主，不起 GUI）

~~~python
import sys, time, threading
sys.path.insert(0, r"<Loom 目录>")
from loom_logic_thread import LogicThreadMixin

class Host(LogicThreadMixin):
    def __init__(self):
        self._logic_thread=None; self._logic_stop=None; self._logic_async=True
        self._logic_gen=0; self._logic_steps=0; self._logic_paused=False
        self._step_requested=False; self._prep_pub=None; self._prep_pairs=None
        self._prep_light_vps=None; self._interp=None; self.is_playing=False
        self._stage_times={}; self._stage_calls={}
    def _profile(self, name, fn): return fn()

class Clk:
    def __init__(self): self.steps=0; self.alpha=0.0; self.n=0
    def advance(self, dt): self.n+=1; return (0,0)
    def step_once(self): return (1,1)

h = Host(); clk = Clk()
h._start_logic_thread(clk); time.sleep(0.2)
t = h._logic_thread; t0 = time.perf_counter()
h._stop_logic_thread()
print("stop 耗时 %.2fs" % (time.perf_counter()-t0))   # 期望 <0.1，实测 2.00
time.sleep(0.5); print("旧线程 alive =", t.is_alive())  # 期望 False，实测 True
h._start_logic_thread(clk); time.sleep(0.3)
print("loom-logic 线程数 =", len([x for x in threading.enumerate() if x.name=='loom-logic']))  # 实测 2
~~~

### A.2 P-02 崩溃落盘是否接线（静态扫描）

~~~python
import os, re
LOOM = r"<Loom 目录>"; hits = []
for root, dirs, names in os.walk(LOOM):
    dirs[:] = [d for d in dirs if d not in ('tests','__pycache__','.git','assets','Projects')]
    for n in names:
        if n.endswith('.py'):
            p = os.path.join(root, n)
            for i, line in enumerate(open(p, encoding='utf-8', errors='replace'), 1):
                if 'crash_reporter' in line or 'write_dump' in line:
                    hits.append((os.path.relpath(p, LOOM), i))
print(len(hits), hits[:3])      # 实测 12 处，全部位于 crash_reporter.py 自身
~~~

### A.3 P-05 --force 的删除目标（拦截 rmtree，不真删）

~~~python
import sys, os, types
sys.path.insert(0, r"<Loom 目录>")
import build_game
build_game.sceneio = types.SimpleNamespace(load_scene_data=lambda p: {'objects': []})
build_game.plugin_loader = types.SimpleNamespace(scan_player_plugins=lambda base=None: [])
build_game.game_pack = types.SimpleNamespace(pack=lambda *a, **k: None,
    pack_plugins=lambda *a, **k: None, plugins_path=lambda d: os.path.join(d,'x'))
build_game._resolve_runtime = lambda arg: os.environ['TEMP']
rec = []
def boom(p, *a, **k): rec.append(os.path.abspath(p)); raise RuntimeError("拦截")
build_game.shutil = types.SimpleNamespace(rmtree=boom, copytree=lambda *a, **k: None,
                                          copy2=lambda *a, **k: None)
sys.argv = ['build_game.py','--name','X','--output','.','--force']
try: build_game.main()
except RuntimeError as e: print(e, "->", rec)
# 实测: 拦截 -> ['<引擎源码根>']
~~~

### A.4 P-06 同夹改写绕过互验（临时目录）

~~~python
import sys, os, types, hashlib, tempfile
sys.path.insert(0, r"<Loom 目录>")
pl = types.ModuleType('plugin_loader')
pl.set_mode = lambda m: None
pl.load_plugin_from_pack = lambda *a, **k: None
sys.modules['plugin_loader'] = pl
import game_pack, sceneio
tmp = tempfile.mkdtemp()
sha = lambda p: hashlib.sha256(open(p,'rb').read()).hexdigest()
item = {'id':'demo','name':'D','version':'1','layer':'player','kind':'standard',
        'entry':'x=1\n','files':{'a.txt':b'ORIG'}}
game_pack.pack_plugins(tmp,[item])
game_pack.pack(tmp,{'name':'g','plugins_sha256':sha(game_pack.plugins_path(tmp))},{'objects':[]},[])
evil = dict(item, entry='import os\n', files={'a.txt':b'PWNED'})
game_pack.pack_plugins(tmp,[evil])
gm = game_pack.load(tmp); gm['config']['plugins_sha256'] = sha(game_pack.plugins_path(tmp))
sceneio.save_scene_data(game_pack.pack_path(tmp), gm, encrypt=True)
print(game_pack.install_game_plugins(tmp, game_pack.load(tmp)))   # 实测 1（未被拦截）
~~~

### A.5 P-09/P-10 的一行式复现

~~~python
# P-10: 只含少量 NUL 的 .py 不会被 _self_check_sources 报告
python -c "import sys; sys.path.insert(0,r'<Loom>'); import Loom, tempfile, os; d=tempfile.mkdtemp(); p=os.path.join(d,'x.py'); open(p,'wb').write(b'x=1\n\x00y=2\n'); Loom.__file__=os.path.join(d,'Loom.py'); Loom._self_check_sources(); print('未报告(漏检)')"
# 对照: python -c "import importlib.util" 加载该文件 -> SyntaxError: source code string cannot contain null bytes
~~~

---

## 附录 B · 交叉去重与交接提示（给主 Agent）

1. **P-03（入口分叉）** 与 05_player / 06_editor_ui 模块相关：build_entry.py 的 GL-only 路径会在那边以「编译版行为」出现，
   请优先认领本报告的 P-03，避免重复记账。
2. **P-01（逻辑线程停止）** 与 01_core 的 P-04（同逻辑帧派发两次）**不同根因**：01_core 是派发点重复，本报告是线程生命周期失控；
   但若修复 P-01 后出现「双线程同 clk」，会放大 01_core 的跨线程竞态，建议同一批次修复。
3. **P-06 / P-28** 与 05_player（game_player 装载链）、12_misc（Hub）相关：本报告只覆盖 Loom/ 侧，Hub 侧校验请交由对应模块确认。
4. **P-12（发布夹带源码）** 与 10_assets 无重叠（assets 不进发布夹），属构建器白名单问题。
5. 本报告 **未修改任何文件**；§0.5 的运行期自查可作为「只读审计」凭证。
