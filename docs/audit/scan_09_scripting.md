# 脚本/插件/事件/调度（scripts / plugin_loader / plugin_sandbox / script_glue / loom_events / scheduler）扫描报告

> 审计协议：docs/audit/SCAN_PROTOCOL.md（2026-11-07，只读审计）
> 方法论依据：桌面《论如何正确的 vibe coding》《论如何使用 AI 自动化工具正确的判断 AI 给出的黑盒是否符合设计标准》
> 审计对象工作区：D:\my-project - 副本\Loom(py源代码-工作区)\Loom

## 0. 范围与方法（文件清单 + 行数 + 跑过什么命令）

### 0.1 文件清单（HEAD = 4f4665011e7891d221934ac0300ef42544eab90d）

| 文件 | 行数（非空行） | HEAD blob sha1 |
|---|---|---|
| Loom/scripts.py | 662 | 3b004fdc615f2dac5660d74a6c539495c93facd4 |
| Loom/plugin_loader.py | 600 | 73ba287cd112894d8c71f4b29a8a231ca99a1415 |
| Loom/plugin_sandbox.py | 95 | f5230d8c20c8426a1e78dda29b85c5c886a04c6b |
| Loom/script_glue.py | 175 | ead16d969de46e077c5ff394bea5616231fdb388 |
| Loom/loom_events.py | 173 | 35e4d7baf99da4070afa9df3e9a07a2f2516dc08 |
| Loom/scheduler.py | 201 | 1c988c79c3d5d9ee2376c6c9889373d221660d3f |

行数口径：`Get-Content <f> | Measure-Object -Line`（非空行，与 scan_02 一致）。

### 0.2 [REGRESSION] 专项：git diff 结果

```powershell
cd "D:\my-project - 副本\Loom(py源代码-工作区)"
git diff HEAD --stat -- Loom/scripts.py Loom/plugin_loader.py Loom/plugin_sandbox.py Loom/script_glue.py Loom/loom_events.py Loom/scheduler.py
# 输出：（空）
git status --porcelain -- <同上 6 个文件>
# 输出：（空）
git diff HEAD -- <同上 6 个文件> | Measure-Object -Line
# 输出：Lines = 0
```

交叉检查本轮未提交改动是否间接改动本模块调用面：

```powershell
git diff HEAD -- Loom/engine.py Loom/scene_driver.py Loom/runtime.py Loom/loom_render.py |
  Select-String -Pattern '^[+-][^+-].*(script|events|sched|plugin|update_scripts|on_start|on_disable)'
# 输出：（空）
```

结论：**本模块 6 个文件相对 HEAD 零改动**；本轮 "Vulkan 对齐" 未提交 diff 未触碰本模块，也未在 engine/scene_driver/runtime 中改动脚本/事件/调度调用行。**REGRESSION = 0**。

补记：本模块最后一次提交为 de1bc51（2026-10-20，scripts.py 加 Script.http_* 薄转发），早于本轮 2026-11-06 Vulkan 改动；顺带复核 http_*（scripts.py:342-379 仅转发 loom_net，无状态），不构成本轮回归。

### 0.3 实际跑过的命令（全部在临时目录，未改仓库文件）

探针目录：`%TEMP%\loom_scan09`（C:\Users\Administrator\AppData\Local\Temp\loom_scan09）。环境变量：`LOOM_NO_SAVE_MIGRATE=1`、`PYTHONIOENCODING=utf-8`。Python 3.12.10 / pygame 2.6.1。

```powershell
$env:LOOM_NO_SAVE_MIGRATE='1'
python "$env:TEMP\loom_scan09\probe_sandbox.py"           # P-01
python "$env:TEMP\loom_scan09\probe_traceback_escape.py"  # P-02
python "$env:TEMP\loom_scan09\probe_whitelist.py"         # P-01 枚举
python "$env:TEMP\loom_scan09\probe_whitelist2.py"        # P-01 深度2
python "$env:TEMP\loom_scan09\probe_trust_toctou.py"      # P-03
python "$env:TEMP\loom_scan09\probe_plugin_fail.py"       # P-04
python "$env:TEMP\loom_scan09\probe_plugin_life.py"       # P-05 / P-10
python "$env:TEMP\loom_scan09\probe_events.py"            # P-06/07/08/19/20
python "$env:TEMP\loom_scan09\probe_scripts.py"           # P-09 / P-15
python "$env:TEMP\loom_scan09\probe_counttouch.py"        # P-16
python "$env:TEMP\loom_scan09\probe_sched.py"             # P-11/12/13/14
python "$env:TEMP\loom_scan09\probe_misc.py"              # P-14/17/18
python "$env:TEMP\loom_scan09\probe_misc2.py"             # P-21/22
```

定向回归（未跑全量 tests/run_all.py）：

```powershell
cd "D:\my-project - 副本\Loom(py源代码-工作区)\Loom"
python tests/test_plugin_loader.py   # 总结果: ALL PASS
python tests/test_scripts.py         # 总结果: ALL PASS
python tests/_tmp/smoke_events.py    # SMOKE_PASS
```

### 0.4 只读自证

- 审计前后 `git status --porcelain -- <6 文件>` 恒为空；6 个受审文件 mtime 早于本次会话（scripts.py 2026-10-20，其余 2026-11-06 之前）。
- `tests/test_scripts.py`、`tests/test_plugin_loader.py` 的 M 状态为本轮 Vulkan 改动遗留（mtime 2026-11-06 19:15，早于本会话），非本代理写入；本代理只运行了不写受跟踪文件的模块测试。
- 唯一新增仓库文件是本报告 `docs/audit/scan_09_scripting.md`（未跟踪）。

---

## 1. 粗筛清单（含跳过项留痕）

六类标签：契约 / 不变量 / 错误模型 / 资源边界 / 并发 / 边界输入。P-19 之后为阶段二回填项。

### 1.1 疑似项

| ID | 位置 | 标签 | 初步方向（指向的代码事实） |
|---|---|---|---|
| P-01 | plugin_sandbox.py:41-45,69-73；plugin_loader.py:127-129,235-258 | SEM-MISMATCH / 安全 | 白名单模块命名空间直挂 _sys/_os/codecs/builtins，运行时快检只看**直接**危险名 |
| P-02 | plugin_loader.py:193-197,203-232；plugin_sandbox.py:55-79 | SEM-MISMATCH / 安全 | __traceback__/tb_frame/f_globals 不在黑面名单，异常可把宿主帧全局暴露 |
| P-03 | plugin_loader.py:341-349,504,523-529 | BND-TIME / 安全 | 信任哈希在 504、执行在 524，两步之间文件可被替换（TOCTOU） |
| P-04 | plugin_loader.py:400-422,483-537 | IFACE-PARTIAL / 错误模型 | register(api) 抛异常后，已注册的 SCRIPTS/按钮/sys.modules 不回收 |
| P-05 | plugin_loader.py:400-408,633-651 | IFACE-PRECOND / 资源边界 | 脚本 id 无所有权校验：可覆盖内建，卸载按 id 无差别 pop |
| P-06 | loom_events.py:184-194 vs 126-160,78-113 | SEM-MISMATCH / 重入 | clear() 派发期立即生效，与文档"取消延迟应用"和 off() 延迟语义不一致 |
| P-07 | loom_events.py:67-76,149-155,162-173 | SEM-MISMATCH / 重入 | once 的移除被推迟到最外层，重入 emit 可重复触发 |
| P-08 | loom_events.py:36-38 vs 78-93 | AUDIT-DOCIMPL | cancel() 只翻 alive 不摘除，与"等效于 bus.off(handler)"矛盾 |
| P-09 | scripts.py:43-90；script_glue.py:188-194 | BND-RESOURCE | DynamicLuaScript 无 on_disable/on_destroy，loom_script_lua_free 永不调用 |
| P-10 | plugin_loader.py:257,633-656 | BND-RESOURCE | 卸载不删 sys.modules[mod_name]，热重载旧模块常驻 |
| P-11 | scheduler.py:59,90 | AUDIT-DEADCODE | mask 参数未存为 _mask，线程亲和分支恒不执行 |
| P-12 | scheduler.py:74-80,136-153 | AUDIT-DEADCODE | metrics['packages'] 声明后从未累加 |
| P-13 | scheduler.py:136-153,119-134 | BND-CONCURRENCY | 超时降级后 worker 仍在执行，调用方串行兜底与之并发写同一输出 |
| P-14 | scheduler.py:172-180,112-116 | IFACE-PARTIAL / 状态机 | shutdown 清空 _jobs 并归零 _pending，worker 收尾减到 -1；wait 可对未执行任务返回 True |
| P-15 | scripts.py:92,99-100,106 | AUDIT-DOCIMPL | 文档称"跳过 _ 开头(内部文件)"，正则实际放行 |
| P-16 | scripts.py:730-744 | BND-RESOURCE | on_start 向常驻 canvas 挂 HUD 文本，无任何清理路径 |
| P-17 | scripts.py:130-159 | SEM-SILENT / 边界输入 | 字典条目缺 'source' 时 KeyError 逃出，与"坏脚本不崩"相反 |
| P-18 | plugin_loader.py:424-434 | 边界输入（回填） | read_asset 用 startswith 判越界，需验证 Windows 绝对路径/.. 形态 |
| P-19 | loom_events.py:78-93,126-158 | 顺序（回填） | 派发期间 off(handler) 是否真延迟 |
| P-20 | loom_events.py:126-160 | 重入（回填） | 嵌套 emit 是否乱序/重复派发 |
| P-21 | scheduler.py:119-134,136-145 | 状态机（回填） | 上一批 _done 残留是否让下一批假完成 |
| P-22 | plugin_loader.py:282-286 | 边界输入（回填） | entry 正则是否允许路径穿越 |
| P-23 | plugin_loader.py:235-258；plugin_sandbox.py:98-104 | 契约（回填） | _strip_builtins 是否破坏沙箱自身函数 |
| P-24 | scheduler.py:59,136-153 | BND-TIME / 性能 | 2ms 超时在真实负载下的误降级概率（无法离线证明） |
| P-25 | scripts.py:43-90；script_glue.py:86-195 | BND-RESOURCE | 每次播放 Lua VM 实际泄漏字节数（需 C 侧计量） |
| P-26 | plugin_loader.py:341-349,504-529 | BND-TIME / 安全 | 真实时序下 TOCTOU 可赢窗口（路径已证，概率未知） |

### 1.2 跳过登记（防"检查过了"式糊弄）

| 编号 | 位置 | 跳过理由（四类之一） |
|---|---|---|
| SKIP-01 | scripts.py:342-379 Script.http_* | 理由1（语言规范/薄转发）：仅 import loom_net 后一行 return，无状态无分支；网络实现属 12_misc 的 loom_net.py |
| SKIP-02 | scripts.py:457-716 内置脚本数值 | 理由3（已有回归）：tests/test_scripts.py 覆盖自转/浮动/WASD/相机跟随并 ALL PASS；本模块只审入口、生命周期、资源 |
| SKIP-03 | script_glue.py:51-78 batch_rotate | 理由1（argtypes 显式 + 调用方容量检查 engine.py:928-935）；数值由 tests/_tmp/sched_pool_check.py 对拍 |
| SKIP-04 | plugin_loader.py:312-321 _hash_dir 二进制读取 | 理由1（open(...,'rb') 无编码假设）；TOCTOU 已由 P-03 单列 |
| SKIP-05 | loom_events.py 线程安全 | 理由2（白盒契约声明）：loom_events.py:16-17/43-44 明示单线程、不保证线程安全 |
| SKIP-06 | scheduler.py:189-223 sched_wm_chunk | 理由3（已有对拍）：tests/_tmp/pipeline_world_check.py 与 engine/loom_pipeline 逐位对拍；属 03/04 数值面 |
| SKIP-07 | loom_events.py:199 default_bus | 理由2（契约声明）：engine.py:230 每引擎新建 EventBus，模块单例只服务工具脚本 |
| SKIP-08 | scripts.py:182-190 Script.__init__ params | 理由3：tests/test_scripts.py 覆盖 params/vals/script_vars 覆盖链，ALL PASS |

---

## 2. 逐项裁决（8 段式逻辑链）

> 每条链的"验证"段给探针命令与实测输出摘录；完整探针在 %TEMP%\loom_scan09。所有"预期"只引用被审对象自身契约（模块 docstring / 行内注释 / 测试断言）。

### P-01 · [PROVED] 受限插件经白名单模块命名空间拿到真实 sys/os/builtins（沙箱逃逸）

1. **位置**：plugin_sandbox.py:33-36（白名单）、41-45（危险名表）、67-74（运行时快检）；plugin_loader.py:127-129（转发 restricted_import）、235-258（受限加载）。
2. **契约/预期**：plugin_loader.py:22-33 与 plugin_sandbox.py:23-32 声明——普通插件只放行 math/re/collections/itertools/functools/random/copy/json，且"白名单模块放行前运行时快检命名空间：直挂危险名字立即拒载"；插件文件系统"唯一入口 api.read_asset（限插件目录，只读）"。
3. **路径枚举**：受限 entry 的调用面只有 ① 受限 builtins（plugin_loader.py:143-171）② 白名单 import ③ api.*。② 的返回对象是真模块（plugin_sandbox.py:68 real = _imp(...)）；其命名空间只按 `set(ns) & _DANGER_ATTR_NAMES` 检查**直接**键（第 70 行），不递归、不看下划线别名。因此路径 = import 白名单模块 → 取其直挂/二跳子模块 → 取系统能力，全程纯属性/下标，不触发 AST 黑面名单（plugin_loader.py:193-200 不含 _sys/_os/codecs/builtins）。
4. **实际行为**：实测枚举（probe_whitelist.py / probe_whitelist2.py）：

```
collections  module-attrs=['_collections_abc', '_sys']
json         module-attrs=['codecs', 'decoder', 'encoder', 'scanner']
random       module-attrs=['_os', '_random']
re           module-attrs=['_casefix','_compiler','_constants','_parser','_sre','copyreg','enum','functools']
random._os is os module: os
json.codecs module: <module 'codecs' (frozen)>
collections._sys is sys: sys
json.codecs.open write ok: via json.codecs
depth2-hot: collections._collections_abc.sys / collections._sys / json.codecs.{builtins,sys} / random._os.{sys,open} / re.enum.sys
```

端到端（probe_sandbox.py：受限 entry 内 `b = collections._sys.modules['builtins']; b.open(<任意路径>,'w').write(...)`）：

```
STEP0 restricted_import('os') -> blocked (control)
STEP2 AST check: (None, None)
STEP3 loaded: loom_plugin_probe_evil | api: PluginAPI
STEP4 PWNED exists: True
STEP5 content: ESCAPED via collections._sys.modules
STEP6 sandbox_globals_clean: True
```

5. **差异**：契约承诺"文件系统唯一入口 = api.read_asset（插件目录只读）"；实际一次 import collections 就拿到真实 sys 与 builtins.open，写出插件目录之外的任意文件，且运行时快检与 AST 均判"通过"。
6. **触发条件**：编辑器模式（默认 _MODE='editor'，plugin_loader.py:77）加载任意 standard 插件；插件源码出现上述任一属性链；不需要 getattr/__class__ 等黑面名字，也不需要元编程技巧。
7. **验证**：`python "$env:TEMP\loom_scan09\probe_sandbox.py"`；输出见上（PWNED 文件实际生成）。对照 `restricted_import('os')` 正常拒绝，证明不是黑名单失效而是白名单命名空间泄漏。
8. **影响与等级**：**P0（安全）**。受限环境是编辑器默认加载普通插件的唯一护栏；三条独立泄漏（collections/random/json，另 re.enum 二跳）让"防投放误用"在默认路径失效。模块 docstring 已声明"不拦截有意元编程、非真沙箱"，但这几条不需要元编程，属护栏设计漏洞而非已知取舍。

---

### P-02 · [PROVED] 受限插件经 __traceback__ 拿到 plugin_loader 全局（os/sys/importlib）

1. **位置**：plugin_loader.py:193-200（黑面属性名单）、203-232（AST 门禁）、400-422（会抛 ValueError 的 api 校验）；plugin_sandbox.py:55-79。
2. **契约/预期**：plugin_loader.py:187-192 声明"AST 拦'元编程黑面'的直接书写（__subclasses__/__globals__/__builtins__/__class__/__bases__/__mro__ …），正常插件 0 误伤"；受限插件拿不到宿主命名空间。
3. **路径枚举**：受限 entry 能触达的异常源：① 自身 raise ② api.register_script(None) 的 ValueError（plugin_loader.py:404-406）③ api.read_asset 越界 ValueError（427-432）④ api.register_editor_button 参数校验（414-417）。②③④ 的栈帧属于 plugin_loader，其 f_globals 即本模块 dict（含 os/sys/importlib/hashlib）。异常对象的 .__traceback__ 是普通属性，tb_next/tb_frame/f_globals 均不在黑面名单 → 纯属性链可达。
4. **实际行为**（probe_traceback_escape.py，entry 内 `g = e.__traceback__.tb_next.tb_frame.f_globals`，随后用 g['os'] 写文件）：

```
AST check: (None, None)
loaded: loom_plugin_probe_evil2 | PWNED2 exists: True
content: b'ESCAPED via __traceback__ -> plugin_loader globals'
```

5. **差异**：契约要求受限插件无法触达宿主模块命名空间；实际只要调用一次会抛异常的宿主 API，就能拿到 plugin_loader 完整 globals（os/sys/importlib/hashlib 全在），等价全权。
6. **触发条件**：任一 standard 插件在编辑器模式下执行上述属性链；异常源可用任意 api 参数校验触发，不需要宿主缺陷。
7. **验证**：`python "$env:TEMP\loom_scan09\probe_traceback_escape.py"`；输出见上（PWNED2 实际生成）。
8. **影响与等级**：**P0（安全）**。这条不依赖白名单模块，说明"黑面名单 + 检索原语移除"对 __traceback__ 这类未列名反射面无效。建议方向：把 frame/traceback 族（__traceback__/tb_frame/tb_next/f_globals/f_locals/f_back/gi_frame/cr_frame/ag_frame/__code__）纳入黑名单，并明确"名单式防御 = 误用护栏，不是安全边界"，真正边界走已规划的 L2 子进程。

---

### P-03 · [PROVED] 核心插件信任闸 hash→exec 之间存在 TOCTOU 窗口

1. **位置**：plugin_loader.py:341-349（core_trust_state 读哈希）、503-512（闸门判定）、523-529（_load_one 读取并执行 entry）。
2. **契约/预期**：plugin_loader.py:16-18 声明"核心插件全权，安装须信任确认 + 全文件 SHA256 校验；未信任/被改过 = 不加载"；即"被验证的字节 = 被执行的字节"。
3. **路径枚举**：_try_scan_folder（core 分支）→ core_trust_state → _hash_dir 计算 {rel: sha256} → 与信任表比对 → 返回 trusted → _load_one → _load_entry_restricted 重新 open(entry_path).read()。两次读取之间无锁、无二次校验、无句柄复用。
4. **实际行为**（probe_trust_toctou.py；为确定性复现注入 0.3s sleep 放大窗口，真实窗口 = hash 结束到 open(entry) 之间）：

```
A trust state before confirm: untrusted
B confirm_core_trust: True
C trust state after confirm: trusted
D load result: {'loaded': ['probe.core'], 'broken': [], 'untrusted': []}
E MALICIOUS entry executed despite trusted hash: True | trusted hash was of BENIGN
```

5. **差异**：契约要求哈希覆盖实际执行内容；实际执行的是哈希之后被替换的 entry.py，信任表仍显示 trusted。
6. **触发条件**：攻击者对插件目录有写权限、对信任表无写权限（正是信任闸要防的场景）；在 hash 完成后、exec 前替换 entry.py。
7. **验证**：`python "$env:TEMP\loom_scan09\probe_trust_toctou.py"`；输出见上。
8. **影响与等级**：**P2（安全，窗口窄）**。不改变"未信任不加载"的主判定，但破坏"确认过的内容才执行"的承诺。建议方向：信任校验与执行共用同一份读入字节（先读 bytes → hash → compile 同一 bytes），或执行前二次校验。

---

### P-04 · [PROVED] 插件加载失败后残留部分注册（脚本/按钮/模块），且无法卸载

1. **位置**：plugin_loader.py:400-408（register_script 直接写全局 SCRIPTS）、410-422（按钮表）、523-529（异常只记 broken）、530-532（只有成功才入 _LOADED）、633-656（unload 需要 _LOADED）。
2. **契约/预期**：plugin_loader.py:466 注释"异常向上抛由调用方隔离"；544 返回 broken 表示该插件未生效；错误模型隐含"失败 = 无副作用"。
3. **路径枚举**：_try_scan_folder → _load_one → _load_entry_restricted（exec 成功、模块入 sys.modules）→ reg(api)（可能已调用 register_script/register_editor_button）→ 之后抛异常 → except 仅 append broken 并 continue；_LOADED 不写入 → 后续 unload_plugin 第 637-639 行直接返回"插件未加载"，清理链不可达。
4. **实际行为**（probe_plugin_fail.py：entry 先 register_script + register_editor_button，再 raise）：

```
A result loaded = [] | broken = [{'id': 'probe.half', 'error': "RuntimeError('boom after registering')"}]
B _LOADED has probe.half: False
C SCRIPTS['half_sid'] retained after failed load: True -> <class 'loom_plugin_probe_half.C'>
D editor buttons from failed plugin: [('half button', 'probe.half')]
E sys.modules has failed plugin module: ['loom_plugin_probe_half']
```

5. **差异**：加载器向用户报告"失败/回退官方"，但失败插件的脚本仍在检查器下拉并可被挂载执行，工具栏按钮仍可点击，模块常驻 sys.modules，且没有卸载入口。
6. **触发条件**：插件 register() 在部分注册后抛异常（依赖缺失、参数错误、插件自身 bug 均可）。
7. **验证**：`python "$env:TEMP\loom_scan09\probe_plugin_fail.py"`；输出见上。
8. **影响与等级**：**P1（功能/完整性）**。失败路径不是原子的，破坏"坏插件不生效"的安全默认。建议方向：加载前记录 api 快照（_sids/按钮/模块名），失败回滚；或把注册表写入延迟到 register() 成功之后统一提交。

---

### P-05 · [PROVED] 脚本 id 无所有权：插件可覆盖内建，卸载时按 id 无差别 pop

1. **位置**：plugin_loader.py:400-408（SCRIPTS[sid] = cls 无重复检查）、644-646（unload 按 api._sids 逐个 SCRIPTS.pop(sid)）。
2. **契约/预期**：plugin_loader.py:401 注释"与 scripts.SCRIPTS @register 同池，检查器可挂"；卸载语义（633-636）"清理注册脚本/按钮"——按插件所有权理解，只应清理该插件注册的条目。
3. **路径枚举**：① 插件 A 注册 id=X → SCRIPTS[X]=A；② 内建注册表 scripts.py:457-763 全是同名键，插件注册同名字即覆盖；③ 卸载 A → pop(X) → 若 X 原本属内建或属仍加载的 B，原对象永久消失（无备份、无重建）；④ 重启进程才恢复内建（模块级 @register 重新执行）。
4. **实际行为**（probe_plugin_life.py：pa/pb 都注册 'shared'，pc 注册内建 'rotate'）：

```
A loaded = ['probe.pa', 'probe.pb', 'probe.pc']
A SCRIPTS['shared'] -> <class 'loom_plugin_probe_pb.C'> | builtin rotate replaced -> <class 'loom_plugin_probe_pc.C'>
B unload pa ok= True | SCRIPTS has 'shared' after unload: False | pb still loaded: True
C unload pc ok= True | builtin SCRIPTS has 'rotate' after unload: False
```

5. **差异**：卸载"自己"的插件后，仍加载的 B 的脚本被删除；卸载覆盖内建的插件后，内建"自转"脚本从 SCRIPTS 永久消失（检查器下拉少一项，已挂物体静默不执行）。
6. **触发条件**：任意两个插件使用相同 script_id，或插件使用内建 id（rotate/bob/orbit/wasd_move/...）；随后卸载其中一个。
7. **验证**：`python "$env:TEMP\loom_scan09\probe_plugin_life.py"`；输出见上。
8. **影响与等级**：**P1（功能错误）**。属"注册表所有权"缺失。修复方向：注册时记录原持有者并在卸载时按栈恢复，或禁止覆盖已存在 id 并报 broken。

---

### P-06 · [PROVED] EventBus.clear() 派发期立即生效，丢掉当前轮后续回调

1. **位置**：loom_events.py:184-194（clear 直接改 _handlers 并置 alive=False）；对照 78-113（off 在派发期只入 _pending_remove）、126-160（emit 先快照再逐个检查 h.alive）。
2. **契约/预期**：loom_events.py:20 声明"emit() 派发期间的订阅/取消进入延迟队列，派发结束后统一应用（避免遍历中途改字典）"；87-88 进一步声明派发期 off "当前轮仍会调用, 下一轮起不再调用"。
3. **路径枚举**：派发中回调可调用的取消 API = off(handler)（延迟，78-93）/ off(name)（延迟，97-104）/ off(name, cb)（延迟，105-112）/ clear(name)（立即，184-194）/ clear()（立即，186-190）/ handler.cancel()（立即置 alive，P-08）。前三条走延迟队列，后三条绕过队列。
4. **实际行为**（probe_events.py A：h1 内 clear('e')，h2 为第二个订阅者）：

```
A seen = ['h1'] | doc deferral expects ['h1','h2'] | listener_count = 0
A2 seen = ['h3', 'h4']   # 对照：off(handler) 延迟，当前轮 h4 仍被调用
```

5. **差异**：契约要求当前轮订阅者全部收到本次事件；clear() 让 h2 静默丢事件（且 emit 返回计数少 1，调用方无法区分"没人订阅"与"被 clear 吃掉"）。
6. **触发条件**：任一回调在派发中调用 bus.clear()/clear(name)（常见于"死亡清空监听""切场景清事件"）。
7. **验证**：`python "$env:TEMP\loom_scan09\probe_events.py"`；A/A2 输出见上。
8. **影响与等级**：**P1（功能错误，顺序/重入焦点）**。清空是 API 文档明确列出的取消方式，却与 off 语义分叉。修复方向：clear 在派发期同样入延迟队列（并明确"清空到本轮快照为止"的语义边界）。

---

### P-07 · [PROVED] once + 重入 emit 时回调被触发 499 次（"只触发一次"失效）

1. **位置**：loom_events.py:67-76（once 标记）、149-155（once 移除追加到 pending）、162-173（_apply_pending 在 _dispatching>0 时直接 return）。
2. **契约/预期**：loom_events.py:68-69 "once()：订阅 name 事件，触发一次后自动取消"；126-131 "派发期间新增/移除的订阅进入延迟队列，本次派发结束后统一应用"。
3. **路径枚举**：外层 emit（dispatching 1）→ once 回调 → 回调内再 emit 同名（dispatching 2）→ 内层快照仍含该 handler（alive 仍 True，因移除在队列里）→ 再次调用 → …… 只有最外层 finally 把 dispatching 减到 0 才 apply pending。任意深度 ≥2 都重复触发；递归到解释器上限时由 emit 的 per-callback except 吞掉 RecursionError。
4. **实际行为**（probe_events.py B：once 回调内 bus.emit('e')，计数上限 5000）：

```
B once invocations = 499 | listener_count after = 0
（stderr）[事件] e 回调异常: RecursionError('maximum recursion depth exceeded') ×2
```

5. **差异**：契约"触发一次后自动取消"；实际一次外层 emit 触发 499 次回调（若回调有副作用如扣血/发奖励，等价 499 次重复结算）。
6. **触发条件**：once 回调内再次 emit 同一事件名（或回调链 A→B→A 成环）；深度 = 解释器递归上限量级。
7. **验证**：`python "$env:TEMP\loom_scan09\probe_events.py"`；B 段输出见上。
8. **影响与等级**：**P2（功能错误，重入）**。修复方向：once 在"决定调用前"就标记已触发（先 alive=False 再调用），或在嵌套 emit 时对 once 维护"已触发"集合；不要依赖最外层 apply。

---

### P-08 · [PROVED] EventHandler.cancel() 与 bus.off(handler) 不等价：计数/存在性漂移 + 引用滞留

1. **位置**：loom_events.py:36-38（cancel 只 self.alive=False）、78-93（off 摘除并从 dict 移除）、176-182（has / listener_count）。
2. **契约/预期**：loom_events.py:37 字面声明"等效于 bus.off(handler)，方便链式调用"。
3. **路径枚举**：cancel() 后：emit 会跳过（139-141 检查 alive）——行为面等价；但 _handlers 列表与字典键都不变 → listener_count/has 仍为旧值；handler 对象（含 callback 闭包）被 bus 持有到下一次 emit/off/clear 才可能被清理（而 emit 对非 once 的 dead handler 只是 continue，不清理）。
4. **实际行为**（probe_events.py C）：

```
C h.cancel(): alive = False | listener_count = 1 | has = True
C control off(h): listener_count = 0 | has = False
```

5. **差异**：文档称等价，实际 listener_count 从 0 变 1、has 从 False 变 True，且回调引用不释放；任何"按 has/listener_count 做逻辑"的调用方（如"有监听才广播"）会得到错误判断。
6. **触发条件**：脚本在 on_disable 里用 handler.cancel() 而非 bus.off(handler)（两种写法文档都推荐）；对象生命周期长的总线上持续累积。
7. **验证**：`python "$env:TEMP\loom_scan09\probe_events.py"`；C 段输出见上。
8. **影响与等级**：**P2（资源边界/可审计）**。修复方向：cancel 走 off 的路径（handler 持 bus 引用，或 EventBus 维护 alive 清理），或改文档声明"cancel 仅停止派发，不摘除注册"。

---

### P-09 · [PROVED] Lua 脚本 VM 生命周期缺失：每次播放泄漏一个 Lua state

1. **位置**：scripts.py:43-90（DynamicLuaScript 只有 __init__/on_start/update）；script_glue.py:99-111（_init_vm 每次 loom_script_lua_new 分配）、188-194（close() → loom_script_lua_free）。
2. **契约/预期**：scripts.py:201-210 声明 on_disable（"停止播放/脚本卸下"）与 on_destroy（"物体永久消失"）用于"释放/复位脚本持有的外部资源"；script_glue.py:86-195 为 VM 提供显式 close()。
3. **路径枚举**：进入播放 → engine.py:884-897 cls()/s.on_start() → DynamicLuaScript.on_start 新建 LoomLuaScript（持有 C VM）→ 停止播放 → editor.py:1829-1844 调 inst.on_disable() + stop_all_coroutines()（基类 on_disable=pass，DynamicLuaScript 未覆盖）→ sc._script=None → Python 对象被回收，但 self.vm 是裸 c_void_p、无 __del__，close() 未被任何代码调用。删除物体路径（loom_model_gpu.py:266-274 on_destroy）同样落到基类 pass。
4. **实际行为**（probe_scripts.py B：用 fake LoomLuaScript 统计 close 调用）：

```
B vm allocated in on_start, closed count = 0
B after on_disable()+on_destroy(): closed count = 0 | cls.__dict__ has on_disable: False | has on_destroy: False
```

另以 grep 佐证：LoomLuaScript.close 在仓库内除定义处（script_glue.py:188）外无任何调用点；scripts.py 内 close() 只出现在 generator 三处（306/316/445）。
5. **差异**：契约把 on_disable/on_destroy 定义为外部资源释放点，Lua 适配器不实现；每次播放/停止循环 loom_script_lua_new 与 loom_script_lua_free 次数不配对。
6. **触发条件**：任何挂 .lua 脚本的物体，每次"播放→停止"或"删除物体"；编辑器反复调试即线性累积。
7. **验证**：`python "$env:TEMP\loom_scan09\probe_scripts.py"`；B 段输出见上（fake VM 的 close 未被调用）。
8. **影响与等级**：**P1（资源边界，热重载泄漏焦点）**。修复方向：DynamicLuaScript 实现 on_disable/on_destroy 调 self._lua.close()（并置 None），或在 Script 基类提供 _release 钩子由引擎统一调用；同时 LoomLuaScript.close 应幂等。

---

### P-10 · [PROVED] 插件卸载不清理 sys.modules，热重载旧模块常驻

1. **位置**：plugin_loader.py:257（sys.modules[mod_name] = mod）、633-656（unload 只动 SCRIPTS/按钮/_LOADED）。
2. **契约/预期**：plugin_loader.py:634-636 卸载语义 = "调 deactivate + 清理注册脚本/按钮 + 移出 _LOADED"；热重载（rescan/load_plugin）应表现为旧插件完全消失。
3. **路径枚举**：加载 → sys.modules 写入；卸载 → 无删除；重扫同 id → 新 mod_name 相同，覆盖旧条目（旧对象可回收），但已卸载且不再重扫的 id 永久驻留；插件目录改名/升级导致 id 变化时无界累积。
4. **实际行为**（probe_plugin_life.py D）：

```
D sys.modules retained after unload: ['loom_plugin_probe_pa', 'loom_plugin_probe_pb', 'loom_plugin_probe_pc']
（pa/pc 已卸载，仍在 sys.modules）
```

5. **差异**：卸载后模块对象与其 globals 仍被解释器持有；import loom_plugin_xxx 仍可命中已卸载插件代码（缓存语义与"已卸载"事实冲突）。
6. **触发条件**：unload_plugin / rescan 卸载后；插件 id 变动（升级目录名）时累积。
7. **验证**：`python "$env:TEMP\loom_scan09\probe_plugin_life.py"`；D 段输出见上。
8. **影响与等级**：**P3（资源边界/可维护性）**。修复方向：unload 时 sys.modules.pop(mod_name, None)（核心/普通都清）。

---

### P-11 · [PROVED] NgilPool 的 mask 参数被静默忽略（线程亲和永不生效）

1. **位置**：scheduler.py:59（def __init__(self, n_workers=3, mask=0, ...)）、90（if getattr(self, '_mask', 0):）。
2. **契约/预期**：scheduler.py:61 注释"mask: 线程亲和掩码 (0=不绑, 交 OS 调度)"；90-95 声明为 worker 绑定 pin_current_thread(self._mask)。
3. **路径枚举**：__init__ 收到 mask → 未赋值给任何属性（全文件无 self._mask 赋值）→ _loop 用 getattr(self,'_mask',0) → 恒 0 → pin_current_thread 分支永不进入。引擎侧调用（engine.py:575）也没传 mask，但 API 承诺可传。
4. **实际行为**（probe_sched.py A）：

```
A hasattr(_mask) = False | documented 'thread affinity mask' is never stored -> pin_current_thread unreachable (getattr default 0)
```

5. **差异**：契约承诺可绑核，实际参数无任何效果；NgilPool(mask=0x3) 与不传等价。
6. **触发条件**：任何调用方传 mask（当前树内无生产调用方，见 P-13 说明）。
7. **验证**：`python "$env:TEMP\loom_scan09\probe_sched.py"`；A 段输出见上。
8. **影响与等级**：**P2（性能配置失效）**。修复方向：self._mask = int(mask)；或删除参数并在 docstring 声明"亲和未实现"。

---

### P-12 · [PROVED] NgilPool.metrics['packages'] 声明后从未累加

1. **位置**：scheduler.py:74-80（metrics 字典，'packages': 0）、112-116（worker 完成分支）、136-153（wait_exchange 只加 batches/timeouts/worker_errors）。
2. **契约/预期**：scheduler.py:73 注释"SchedMetrics (任务书): 计数面 (engine_metrics 扩展通道消费)"；'packages' 注释"消化的任务包总数"。
3. **路径枚举**：submit_batch 接受 N 包 → worker 逐个执行 → 只有 _pending 变化与 _done 置位；全文件无 metrics['packages'] 累加点；agent_commands.py:918-923 通过 metrics_snapshot() 消费该字段。
4. **实际行为**（probe_sched.py B：3 个任务包成功执行）：

```
B ok = True | out = [0, 1, 2] | metrics = {'batches': 1, 'packages': 0, 'timeouts': 0, 'worker_errors': 0, 'degraded': 0, 'n_workers': 2}
```

5. **差异**：监控面板恒显示 0 包，无法据此判断池是否真的在消化任务（观测面失真）。
6. **触发条件**：任何使用池的进程。
7. **验证**：`python "$env:TEMP\loom_scan09\probe_sched.py"`；B 段输出见上。
8. **影响与等级**：**P3（可审计/可观测）**。修复方向：submit_batch 内 metrics['packages'] += len(pk)（或完成时累加，需与 batches 语义对齐）。

---

### P-13 · [PROVED，当前潜伏] 超时降级后 worker 仍执行，调用方串行兜底与之并发写同一输出

1. **位置**：scheduler.py:136-153（wait_exchange 超时置 degraded 并返回 False）、119-134（submit 后不撤销任务）、15-18/139（"调用方此后走串行旧路"）。
2. **契约/预期**：scheduler.py:15-18 "超时 → 永久降级（调用方此后走串行旧路）"；隐含交接协议要求"返回 False 时 worker 已停止写结果"。
3. **路径枚举**：submit N 包 → worker 开始执行（可能已写部分 out 切片）→ 主线程 _done.wait(t) 超时 → 返回 False → 调用方按契约对同一批数据跑串行版本 → 此时 worker 仍在 fn(*args) 内写同一 numpy 切片 → 两写者并发。worker 侧无取消/join 机制（_stop 只在 shutdown 检查），不可规避。
4. **实际行为**（probe_sched.py C：worker 睡 0.2s 后写事件，超时 0.02s）：

```
C run_batch returned False | degraded = True
C events = [('serial_fallback', ...104.076), ('worker_write', ...104.257)]
C -> worker still writing AFTER caller took serial fallback: True
```

5. **差异**：契约要求降级后串行兜底是"安全重算"；实际是同缓冲并发写，结果可能是串行与 worker 的交错（非确定性脏数据），且无锁、无版本号检测。
6. **触发条件**：worker 执行时间 > timeout（默认 2ms）且任务写共享输出缓冲。当前树内无生产调用方——run_batch/submit_batch 只出现在 scheduler.py 与 tests/_tmp（grep 证据），engine.py:575 建池但从不提交（engine.py 仅 1368-1374 关闭、agent_commands.py:919-922 读指标）。因此本条为**潜伏缺陷**：一旦按设计接线即触发。
7. **验证**：`python "$env:TEMP\loom_scan09\probe_sched.py"`；C 段输出见上。
8. **影响与等级**：**P2（并发/边界，潜伏）**。修复方向：超时后不能直接返回"可串行"；要么给任务包加版本/放弃标记并保证 worker 不写共享缓冲，要么改为"超时即 join 等待"。

---

### P-14 · [PROVED] shutdown 丢队列 + _pending 变负 + wait_exchange 对未执行任务返回 True

1. **位置**：scheduler.py:172-180（shutdown：_jobs=[]、_pending=0、_stop=True）、112-116（worker finally _pending -= 1 后 empty=(<=0) → _done.set()）、136-145（wait 只看 _done）。
2. **契约/预期**：scheduler.py:137-139 "True=完成（结果数组此刻起可读）"；_pending 注释（68）"未完成包数"；shutdown 注释（173）"停止: 哨兵 -> join. 幂等"。
3. **路径枚举**：submit 4 包 → worker 取走部分执行 → shutdown 清空剩余 _jobs 且 _pending=0 → 执行中的 worker 收尾 _pending -= 1 → -1 → empty 为真 → _done.set() → 随后 wait_exchange 立即 True；被清掉的包从未执行。
4. **实际行为**（probe_misc.py C / D）：

```
C wait_exchange after shutdown = True | executed jobs = [0, 1] | submitted = 4, _pending = -1
D _pending after shutdown = -1 (expected 0, negative = invariant violation)
```

5. **差异**：契约"True=全部完成"；实际 4 提交只执行 2 个，wait 仍返回 True；_pending 违背"未完成包数 ≥ 0"不变量。
6. **触发条件**：submit 与 shutdown 交错（引擎退出 _stop_parallel → engine.py:1371 sp.shutdown()）。
7. **验证**：`python "$env:TEMP\loom_scan09\probe_misc.py"`；C/D 段输出见上。
8. **影响与等级**：**P2（状态机/接口契约）**。退出路径上通常无人再读结果，但池被复用于测试/工具时是错误完成信号。修复方向：shutdown 后拒绝 wait 或置"已取消"状态；_pending 用 max(0,...) 或改为按代际计数。

---

### P-15 · [PROVED] load_script_dir 与 docstring 不符：_ 前缀文件被加载

1. **位置**：scripts.py:92（_SCRIPT_FNAME_RE = ^[A-Za-z0-9_]+\.(py|lua)$）、99-100（docstring"跳过 _ 开头(内部文件)"）、105-107。
2. **契约/预期**：scripts.py:99-100 明示文件名白名单且"跳过 _ 开头(内部文件)"。
3. **路径枚举**：目录内文件名 _internal.py → 正则匹配成功（_ 在字符类内）→ 进入加载 → exec_module；没有任何 fname.startswith('_') 判断。
4. **实际行为**（probe_scripts.py A：目录含 _internal.py 与 ok_script.py）：

```
A count = 2 | registered _internal = True | registered ok = True
```

5. **差异**：文档承诺内部文件不加载，实际加载并注册（内部工具文件会出现在脚本下拉、可被挂载）。
6. **触发条件**：scripts/ 目录放入以下划线开头的 .py/.lua。
7. **验证**：`python "$env:TEMP\loom_scan09\probe_scripts.py"`；A 段输出见上。
8. **影响与等级**：**P3（可审计/契约一致）**。修复方向：加载循环加 if fname.startswith('_'): continue，或删掉 docstring 该句（二选一，需与"内部文件约定"的实际用法对齐）。

---

### P-16 · [PROVED] CountTouch 每次播放向常驻 Canvas 叠加一个 HUD 元素

1. **位置**：scripts.py:730-744（on_start 中 canvas.root.add_child(loom_ui.Text(name='_count_touch_hud', ...))）、746-763（update 只改文本）；未覆盖 on_disable/on_destroy。
2. **契约/预期**：scripts.py:201-210 声明 on_disable/on_destroy 用于"释放/复位脚本持有的外部资源"；脚本生命周期（engine.py:884-897 每播放新建实例，editor.py:1843 sc._script=None）。
3. **路径枚举**：播放 1 → 新实例 on_start → add_child；停止 → 仅 sc._script=None（editor.py:1823-1857 不触碰 self.ui；engine.py:363 self.ui = UIManager() 仅构造一次）→ HUD 留在 canvas；播放 2 → 再 add_child 同名元素 → 叠加。引擎内无 remove_child('_count_touch_hud')（全仓 grep 仅 scripts.py:739 一处命名）。
4. **实际行为**（probe_counttouch.py：同一引擎上模拟 3 次播放）：

```
canvas children after 3 plays = 3 | names = ['_count_touch_hud', '_count_touch_hud', '_count_touch_hud']
CountTouch overrides on_disable/on_destroy: False False
```

5. **差异**：契约把 on_start 的副作用视为可回收；实际每次播放多一个永久 UI 节点，且场景保存会把运行时 HUD 写进 UI 树（sceneio 支持 canvas 序列化）。
6. **触发条件**：使用"触碰计数彩球"脚本，反复播放/停止。
7. **验证**：`python "$env:TEMP\loom_scan09\probe_counttouch.py"`；输出见上。
8. **影响与等级**：**P2（资源边界/UI 状态）**。修复方向：on_disable/on_destroy 从 canvas 摘除 _hud_text，或改用"按物体名查找/复用"的幂等挂载。

---

### P-17 · [PROVED] register_sources 对畸形条目直接 KeyError，与"坏脚本不崩"相反

1. **位置**：scripts.py:130-159；135-138 `name, source = item['name'], item['source']` 在 try 之外。
2. **契约/预期**：scripts.py:131-132 "坏脚本打印不崩. 返回成功加载数"。
3. **路径枚举**：sources 元素为 dict 且缺 'source' → 第 136 行 KeyError → 无 except 覆盖（try 从 141/151 才开始）→ 异常逃出函数；若为 tuple 长度不符 → ValueError 同样逃出。
4. **实际行为**（probe_misc.py B）：

```
B raised: KeyError 'source' | docstring: '坏脚本打印不崩'
```

5. **差异**：契约承诺单条坏项不影响整体加载并返回计数；实际整包加载中断。
6. **触发条件**：游戏包 .lsc 内某脚本元数据缺字段（打包器/手改包/旧版本包）。
7. **验证**：`python "$env:TEMP\loom_scan09\probe_misc.py"`；B 段输出见上。
8. **影响与等级**：**P3（错误模型/边界输入）**。修复方向：元数据解包移入 per-item try，打印后 continue。

---

### P-18 · [DISPROVED] PluginAPI.read_asset 路径越界

1. **位置**：plugin_loader.py:424-434。
2. **契约/预期**：424-427 "仅限插件目录内，相对路径，只读；越界/缺失抛 ValueError"。
3. **路径枚举**（覆盖 Windows/POSIX 形态）：相对上跳 ../、..\；Windows 盘符绝对 C:\...、C:/...；POSIX 绝对 /etc/passwd；混合分隔符。判定链 = normpath(join(root,name)) → startswith(root + os.sep)；os.path.join(root, 绝对路径) 在 Windows 返回绝对路径本身（ntpath.join 语义），因此绝对形态也不满足前缀。
4. **实际行为**（probe_misc.py A）：

```
A read_asset('inside.txt') = inside-ok
A read_asset('../plugin.json') -> ValueError
A read_asset('..\evil.txt') -> ValueError
A read_asset('C:\Windows\win.ini') -> ValueError
A read_asset('C:/Windows/win.ini') -> ValueError
A read_asset('/etc/passwd') -> ValueError
```

5. **差异**：无（全部越界形态被拒），与契约一致。
6. **触发条件**：无（尝试越界即被拒）。
7. **验证**：同上命令输出；另 inside.txt 正常读到，证明不是"一律拒绝"。
8. **影响与等级**：无（DISPROVED）。登记残留风险：插件目录内符号链接指向外部时会被读（语义为"目录内文件"），不计为 PROVED。

---

### P-19 · [DISPROVED] EventBus 派发期间 off(handler) 的延迟语义

1. **位置**：loom_events.py:78-93、126-158。
2. **契约/预期**：87-88 "派发期间: 延迟到本轮结束移除（Unity C# 快照语义: 当前轮仍会调用, 下一轮起不再调用）"。
3. **路径枚举**：off(handler) → 派发中 → _pending_remove.append(h)，不改 alive；emit 的快照 lst 仍逐个调用（139-141 只看 alive）；finally → _apply_pending 统一置 alive=False 并摘除。off(name)/off(name, cb) 同构。
4. **实际行为**（probe_events.py A2/E）：

```
A2 seen = ['h3', 'h4'] | listener_count after = 1
E two emits log = ['ha', 'hb', 'ha'] | count = 1
```

5. **差异**：无（当前轮仍调用，下一轮不再调用）。
6. **触发条件**：无缺陷路径。
7. **验证**：同上命令输出。
8. **影响与等级**：无（DISPROVED）。与 P-06 的对照说明缺陷仅存在于 clear()/cancel() 两条旁路。

---

### P-20 · [DISPROVED] EventBus 嵌套 emit 的顺序与重复派发

1. **位置**：loom_events.py:126-160。
2. **契约/预期**：同步派发、按订阅顺序、无优先级（15-16）；嵌套调用不得打乱外层剩余订阅者顺序、不得重复调用同一订阅者。
3. **路径枚举**：外层快照 lst 遍历 → 回调内 emit 另一事件 → 内层独立快照、独立 dispatching 计数；外层剩余 handler 继续按原顺序执行。_apply_pending 在内层结束时不执行（dispatching 仍 >0）。
4. **实际行为**（probe_events.py D）：

```
D order = ['outer', 'inner']
```

5. **差异**：无（外层先于内层结束，无重复/乱序）。
6. **触发条件**：无缺陷路径。
7. **验证**：同上命令输出。
8. **影响与等级**：无（DISPROVED）。注：once 在嵌套中的重复属 P-07，单独计。

---

### P-21 · [DISPROVED] NgilPool 上一批 _done 残留导致下一批假完成

1. **位置**：scheduler.py:119-134（submit 在锁内 _done.clear() 后 _go.set()）、136-145。
2. **契约/预期**：138-139 "True=完成（结果数组此刻起可读）"。
3. **路径枚举**：run_batch = submit → wait；submit 在持锁状态下先 self._done.clear()（132）再入队/加 pending/置 _go（130-133），因此 wait 观察到的一定是"本批之后"的信号；跨批连续调用不会命中陈旧置位。唯一返回 True 的"无提交"形态是显式空批（124-126）或直接 wait（API 前置条件"随后必须 wait_exchange"的反向调用）。
4. **实际行为**（probe_misc2.py B）：

```
B1 True [1]
B2 True [1, 2]
B3 empty-batch submit then wait: True True
B4 direct wait_exchange without submit: True
```

5. **差异**：无（连续批均正确；B4 属未提交即等待的前置条件外用法，且"无工作=已完成"在语义上成立）。
6. **触发条件**：无缺陷路径。
7. **验证**：同上命令输出。
8. **影响与等级**：无（DISPROVED）。若需严格化：wait 在 _pending==0 且未提交时返回 False 并文档声明。

---

### P-22 · [DISPROVED] plugin.json 的 entry 字段路径穿越

1. **位置**：plugin_loader.py:282-286、468。
2. **契约/预期**：282-283 "插件 entry 非法: 仅允许合法 .py 文件名"。
3. **路径枚举**：_ENTRY_RE = ^[A-Za-z0-9_.-]+\.py$ 禁 /、\、:；os.path.join(dir, '..py') 中 ..py 是普通文件名（.. 后必须跟分隔符才是父目录）；os.path.join(dir, 绝对路径) 虽会返回绝对路径，但绝对形态含 :/\ 被正则拒绝。
4. **实际行为**（probe_misc2.py A）：

```
entry='..\evil.py' -> REJECT
entry='../evil.py'    -> REJECT
entry='C:\evil.py'  -> REJECT
entry='sub/evil.py'   -> REJECT
entry='..py'          -> ACCEPT file=...\mtest\47065\..py   （插件目录内的普通文件名）
entry='ok.py'         -> ACCEPT file=...\mtest\46448\ok.py
```

5. **差异**：无（无任何形态越出插件目录）。
6. **触发条件**：无缺陷路径。
7. **验证**：同上命令输出。
8. **影响与等级**：无（DISPROVED）。

---

### P-23 · [DISPROVED] _strip_builtins 破坏 plugin_sandbox 自身函数

1. **位置**：plugin_sandbox.py:55-65（内建全部以定义时默认参数绑定）、82-95、98-104；plugin_loader.py:244-245 调用。
2. **契约/预期**：plugin_sandbox.py:14-17 "本模块 globals 只剩字符串常量、frozenset、函数自己（函数全部用定义时默认参数绑定所需内建）"；剥离后 sandbox_globals_clean 应为 True 且 restricted_import 仍工作。
3. **路径枚举**：剥离 __builtins__ → restricted_import 内使用的 set/sorted/ImportError/hasattr/getattr/__import__ 全部来自默认参数（55-58）；sandbox_globals_clean 用 _globals/_type 默认参数；_strip_builtins 自身用 _globals 默认参数。无裸内建查名。
4. **实际行为**：（a）probe_sandbox.py STEP0/STEP6：剥离后 restricted_import('os') 仍正确抛 ImportError，sandbox_globals_clean()=True；（b）tests/test_plugin_loader.py 的 t_restricted_sandbox_clean/t_restricted_v06_shortcut 全部 PASS（总结果 ALL PASS）。
5. **差异**：无。
6. **触发条件**：无缺陷路径。
7. **验证**：上述两条命令。
8. **影响与等级**：无（DISPROVED）。该设计本身正确。

---

### P-24 · [UNKNOWN] 2ms 默认超时在真实负载下的误降级概率

1. **位置**：scheduler.py:59（timeout=0.002）、136-145（一次超时 = 永久降级，永不重试）。
2. **契约/预期**：62 "任务书: <=2ms 超时降级"；15-16 "超时 → 永久降级（自愈不重试）"。
3. **路径枚举**：worker 唤醒延迟 + numpy 分块执行时间 + GIL 争抢 + OS 调度抖动共同决定 _done.wait(2ms) 是否超时；命中一次即 _degraded=True 且 submit_batch 永久返回 False。
4. **实际行为**：已知 = 超时立即永久降级（142-145）；未知 = 引擎真实帧负载下 2ms 阈值被击穿的概率（需接线后压测，当前树内无生产提交点）。
5. **差异**：无法判定。
6. **触发条件**：待接线后压测确定。
7. **验证**：已尝试 probe_sched.py（空载不超时；未构造真实引擎负载，因不得跑全量/长期 GUI）；缺：接线后的帧内压测（tests/_tmp/sched_microbench.py 可复用）与 GC/负载注入下的超时分布。
8. **影响与等级**：**P-UNKNOWN**。下一步探针（≤3 次）：① sched_microbench 在 60fps 负载下统计 wait 超时率；② 注入 GC pause 后重测；③ 若超时率 >0.1% 建议默认超时 2ms→5ms 或降级前重试 1 次。

---

### P-25 · [UNKNOWN] 每次播放 Lua VM 实际泄漏量

1. **位置**：scripts.py:43-90；script_glue.py:86-195；C 侧 core_components/script/loom_script.c:313（loom_script_lua_free）。
2. **契约/预期**：close() 应释放 VM；泄漏量取决于 C 侧 lua_new 的分配与 lua_free 的释放范围。
3. **路径枚举**：on_start → loom_script_lua_new（分配 lua_State + 预加载库 + 可能加载 code）→ 未 free → 进程内累积；Python 包装对象回收（无 __del__），C 指针随对象丢失。
4. **实际行为**：Python 层已证实 close 从不调用（P-09）；C 层每次分配/释放的字节数未计量（不读 .dll 二进制、不跑长时 GUI 播放）。
5. **差异**：泄漏事实确定，泄漏量未知。
6. **触发条件**：每次"播放→停止"。
7. **验证**：已尝试 probe_scripts.py（wrapper 层）；缺：C 侧 alloc 计数器或进程 RSS 序列（需改 C 或长跑播放，超出只读边界）。
8. **影响与等级**：**P-UNKNOWN**（事实已由 P-09 定级 P1；本条只影响风险量化）。下一步探针：离屏引擎 100 次 play/stop 采样进程内存，对比不复用 Lua 的基线。

---

### P-26 · [UNKNOWN] 核心插件 TOCTOU 的真实可赢窗口

1. **位置**：plugin_loader.py:341-349、504、523-529。
2. **契约/预期**：同 P-03。
3. **路径枚举**：hash 目录遍历（文件数×读取时间）→ 比对 → 导入模块（磁盘 I/O+编译）→ open(entry)。窗口 = hash 结束到 entry 读取完成；可由大目录（哈希慢）放大，或由调度抢占放大。
4. **实际行为**：P-03 已用注入 sleep 确定性证明"路径存在且无二次校验"；真实窗口长度未测（不构造持续竞态压测）。
5. **差异**：路径已证明，可利用概率未知。
6. **触发条件**：本地写权限 + 竞态命中。
7. **验证**：已尝试 probe_trust_toctou.py（注入放大）；缺：真实目录规模下的窗口测量（如 1000 文件插件、重复 1000 次 load 的命中率）。
8. **影响与等级**：**P-UNKNOWN**（P-03 已给 P2；本条只量化概率）。下一步探针：固定 benign/malicious 两版 entry，循环替换 + rescan，统计命中率。

---

## 3. 统计

| 指标 | 数量 |
|---|---|
| 粗筛疑似项 | 26（P-01…P-26） |
| 跳过登记 | 8（SKIP-01…08） |
| **P-PROVED** | **17** |
| **P-DISPROVED** | **6** |
| **P-UNKNOWN** | **3** |
| **P-CONTRADICTION** | **0** |
| **REGRESSION（本轮 diff 引入）** | **0** |

按等级（PROVED 17 条）：

| 等级 | 条数 | 编号 |
|---|---|---|
| P0 安全 | 2 | P-01, P-02 |
| P1 功能/资源 | 4 | P-04, P-05, P-06, P-09 |
| P2 边界/性能/安全 | 7 | P-03, P-07, P-08, P-11, P-13, P-14, P-16 |
| P3 可维护/可审计 | 4 | P-10, P-12, P-15, P-17 |

CONTRADICTION 说明：本模块无"证伪成功且证真也成功"的项。最接近的是 P-08（cancel 与 off 行为面等价 vs 计数面不等价）——两条链作用域不同（emit 跳过 vs 注册表状态），已拆成"行为面 DISPROVED、注册表面 PROVED"的单向结论，未形成矛盾。P-19 的 off 延迟与 P-06 的 clear 不延迟形成对照，不是矛盾（两者代码路径不同）。

---

## 4. 修复建议排序（只给方向，不含代码）

**P0**

1. P-01：白名单模块放行改为"递归扫描命名空间 + 显式拒绝下划线别名"，或直接把普通插件降级为"误用护栏"并在 docstring/UI 明示不可作安全边界（真正隔离走 L2 子进程）。二者必须选一，不能维持"文档说安全、实现是护栏"。
2. P-02：把 traceback/frame/code 族加入黑面名单（__traceback__/tb_frame/tb_next/f_globals/f_locals/f_back/gi_frame/cr_frame/ag_frame/__code__），并在插件边界把 api 异常转换为无栈错误（或在边界层清栈）。

**P1**

3. P-04：插件加载事务化——register() 成功后才提交 SCRIPTS/按钮/sys.modules；失败路径回滚。
4. P-05：脚本 id 注册记录"原持有者"，卸载按栈恢复；或禁止覆盖已存在 id 并报 broken。
5. P-06：clear() 在派发期走与 off() 相同的延迟队列（或文档改口并加断言）。
6. P-09：DynamicLuaScript 实现 on_disable/on_destroy → close()；LoomLuaScript.close 幂等；引擎退出/删除物体路径统一调用。

**P2**

7. P-03：信任校验与执行共用同一份字节（读一次 bytes → hash → compile/exec）。
8. P-07：once 在调用前先标记已触发（或按嵌套深度维护集合）。
9. P-08：cancel 落到 off 的注册表删除，或修改 docstring。
10. P-11：补 self._mask = int(mask) 或删除参数。
11. P-13（接线前必修）：超时不得让调用方与 worker 并发写；引入"放弃代际/版本"或超时即 join。
12. P-14：shutdown 后 wait 返回"已取消"而非 True；_pending 代际化。
13. P-16：on_disable/on_destroy 摘除 HUD 节点。

**P3**

14. P-10：unload 时 sys.modules.pop(mod_name, None)。
15. P-12：submit 时累加 packages。
16. P-15：实现"跳过 _ 前缀"或改文档。
17. P-17：元数据解包移入 per-item try。

---

## 5. 需要人类裁决的封闭问题

**Q1（P-01/P-02 的定位）**：普通插件"受限执行环境"是 **A. 安全边界**（必须修 P-01/P-02，并为每条泄漏加回归靶场用例）还是 **B. 仅误用护栏**（降为 P2，改文档/UI 明示"不防恶意插件"，安全边界留给 L2 子进程）？——选 A 或 B。代价：A 需要持续维护黑名单/白名单扫描（名单式防御仍不完备）；B 不需要新代码但需要承认当前承诺过强。

**Q2（P-05 的语义）**：插件脚本 id 冲突时 **A. 禁止覆盖任何已存在 id（含内建），记 broken** / **B. 允许覆盖，但卸载时按"原持有者栈"恢复** / **C. 维持现状（允许覆盖，卸载即删）**？——选 A/B/C。代价：A 最安全但限制插件扩展意图；B 最贴近"热插拔"但实现复杂；C 已有 P1 缺陷。

**Q3（P-13/P-14 的调度器处置）**：NgilPool 当前**建池但无生产提交点**（engine.py:575 建、1368 关闭，grep 无 run_batch 调用）。是 **A. 标记 experimental / 暂不接线，先修超时与 shutdown 语义** 还是 **B. 按设计接线，并同步修 P-13（版本化放弃）与 P-14（代际计数）**？——选 A/B。代价：A 保持现状（潜在缺陷不触发，但 2-4 worker 常驻空转）；B 得到并行收益但要先补并发正确性。

---

## 附录 A 探针与关键输出索引

| 探针 | 覆盖 | 关键输出 |
|---|---|---|
| probe_sandbox.py | P-01 | STEP4 PWNED exists: True；STEP6 clean: True |
| probe_traceback_escape.py | P-02 | PWNED2 exists: True |
| probe_whitelist.py / probe_whitelist2.py | P-01 | collections._sys / random._os / json.codecs / re.enum.sys |
| probe_trust_toctou.py | P-03/P-26 | MALICIOUS executed despite trusted hash: True |
| probe_plugin_fail.py | P-04 | SCRIPTS 残留 True；按钮残留；sys.modules 残留 |
| probe_plugin_life.py | P-05/P-10 | 'shared' 被误删；'rotate' 被误删；3 个模块常驻 |
| probe_events.py | P-06/07/08/19/20 | seen=['h1']；once 499 次；cancel count=1 |
| probe_scripts.py | P-09/P-15 | closed=0；count=2 且 _internal 已注册 |
| probe_counttouch.py | P-16 | 3 次播放 → 3 个同名 HUD 节点 |
| probe_sched.py | P-11/12/13 | _mask 不存在；packages=0；worker 晚于串行兜底 181ms |
| probe_misc.py | P-14/17/18 | wait True 但只执行 2/4；KeyError；5 种越界全拒 |
| probe_misc2.py | P-21/22 | 连续批正常；entry 越界形态全拒 |

复现总入口（每个探针自包含，直接 python 运行即可；目录在系统临时区，不写仓库）：

```powershell
$env:LOOM_NO_SAVE_MIGRATE='1'; $env:PYTHONIOENCODING='utf-8'
Get-ChildItem "$env:TEMP\loom_scan09\probe_*.py" | ForEach-Object { python $_.FullName }
```

*报告结束。*
