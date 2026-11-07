# fix_09_scripting — 脚本/插件/事件/沙箱 缺陷修复报告（scan_09）

- **批次**：`09_scripting`（对应审计 `docs/audit/scan_09_scripting.md`）
- **角色**：修复子代理（非审计员）
- **裁决前提**：**Q1=A（受限环境是安全边界，必须堵死）**；**Q2=A（禁止覆盖任何已存在脚本 id，加载时拒绝并报错）**
- **修改文件（严格限定）**：`plugin_sandbox.py`、`plugin_loader.py`、`scripts.py`、`script_glue.py`、`loom_events.py`
- **新增测试**：`tests/test_plugin_sandbox_escape.py`、`tests/test_plugin_register_rollback.py`、`tests/test_events_clear_defer.py`、`tests/test_scripts_lua_close.py`（均被 `tests/run_all.py` 的 `test_*.py` glob 自动收集）
- **未做**：没有 `git add/commit`；没有改其它文件；没有顺手重构；发现的新问题列在 §4（只登记，未动）。

## 0. 验收数字（改前 → 改后）

| 门槛 | 改前 | 改后 |
|---|---|---|
| `python tests/_tmp/ab_batch.py`（22 场景，MAE ≤ 0.0002） | 22/22 PASS，失败 0 | **22/22 PASS，失败 0**（逐场景 MAE 完全一致） |
| `python tests/_tmp/ab_gl_vk_ui.py`（MAE ≤ 1e-6） | 未改 UI，未跑改前 | **MAE=0.00000009，MAX=0.003922，NCC=0.99998569，exit=0** |
| `python tests/run_all.py`（exit=0） | 未采集¹ | **exit=0，70 个测试文件全部通过（末行 "全部测试完成 ✅"）** |
| `tests/test_plugin_loader.py` | ALL PASS | **ALL PASS** |
| `tests/test_scripts.py` | ALL PASS | **ALL PASS** |
| `tests/_tmp/smoke_events.py` | SMOKE_PASS | **SMOKE_PASS** |

¹ 改前的全量 `run_all` 基线未采集：工作树同时被多个并行修复子代理改动，改动前的"全量基线"与本批无因果可比性。本批只承诺"改动后 exit=0"这条门槛，并对每个缺陷给出**针对性的**改前/改后实测（§0.1 与 §1 各项）。

### 0.1 改前/改后逃逸对照（真机执行，非纸面推演）

探针：`%TEMP%\probe_scan09_ab.py`（两个恶意插件目录 + 真 `load_plugins`）。
"改前" = `git show HEAD:Loom/{plugin_loader,plugin_sandbox}.py` 原样放到临时目录并优先 `sys.path`。

```
================ BEFORE (HEAD 版 plugin_loader/plugin_sandbox) ================
MODE = before | plugin_loader from ...\loom_prefix_scan09\plugin_loader.py
GLOBALS KEYS: ['__builtins__', 'os', 'sys']
[插件] 已加载「probe.evil1」evil1 v0.1.0 (player层)
[插件] 已加载「probe.evil2」evil2 v0.1.0 (player层)
load result : {'loaded': ['probe.evil1', 'probe.evil2'], 'broken': [], 'untrusted': []}
链1 PWNED1 落盘 = True  content='ESCAPED via collections._sys'
链2 PWNED2 落盘 = True  content='ESCAPED via __traceback__'
VERDICT: ESCAPED

================ AFTER (工作树当前版) ================
MODE = after | plugin_loader from ...\Loom\plugin_loader.py
[插件] 加载「probe.evil1」失败 ... AttributeError("普通插件受限: 模块代理不暴露下划线属性 '_sys' (P-01 收口)")
[插件] 加载「probe.evil2」失败 ... ValueError('meta-attr: 受限: 元编程属性 `.f_globals` 被禁止 (AST 审查, V05 靶场路径)')
load result : {'loaded': [], 'broken': [probe.evil1, probe.evil2], 'untrusted': []}
链1 PWNED1 落盘 = False  content=''
链2 PWNED2 落盘 = False  content=''
VERDICT: BLOCKED
```

---

## 1. 逐项修复

### 1. [P0] 逃逸链 1 — 白名单模块命名空间泄漏（P-01）

- **位置**：`plugin_sandbox.py:33-79`（白名单 + `restricted_import` 返回真模块）、`plugin_loader.py:235-258`（受限加载）。
- **根因**：`restricted_import` 只对白名单模块做**直接**键名快检（`set(ns) & _DANGER_ATTR_NAMES`），随后把**真模块对象**交给插件。于是纯属性/下标即可下钻：
  `collections._sys`（下划线别名）→ `sys.modules['builtins']` → `open`；
  `random._os`、`json.codecs`、`re.enum`（二跳子模块）同理。AST 黑面名单与"检索原语已撤"都拦不住，因为它们不是元编程，只是普通属性访问。
- **改法**（运行时收口，不是加名单）：
  1. 新增 `_ModuleProxy`（`__slots__ = ('_mp_target',)`）：`__getattribute__` **拒绝一切下划线属性**、**拒绝任何 type(...).__name__ == 'module' 的返回值**（子模块一律拒）；真模块只住在下划线槽里，槽名本身也被同一条规则拒掉，插件拿不回真模块。
  2. `restricted_import` 放行时返回 `_ModuleProxy(real)`，原"直接危险名快检"保留为版本漂移的第二道门。
  3. 代理的 `__repr__` 仅打印 `<受限模块 ...>`，不泄露内部引用。
- **前后证据**：见 §0.1（改前 `collections._sys` 写出 PWNED1；改后 `AttributeError`，无落盘）。
  逐链改后报错：
  ```
  collections._sys            -> AttributeError 模块代理不暴露下划线属性 '_sys'
  collections._collections_abc-> AttributeError 模块代理不暴露下划线属性 '_collections_abc'
  random._os                  -> AttributeError 模块代理不暴露下划线属性 '_os'
  json.codecs                 -> AttributeError 模块代理不暴露子模块 'codecs' (二跳系统面)
  re.enum                     -> AttributeError 模块代理不暴露子模块 'enum' (二跳系统面)
  ```
  控制组（证明不是一刀切）：`math.sqrt / re.match / json.loads / collections.OrderedDict /
  random.random / functools.reduce / itertools.islice / copy.copy` 全部正常，插件照常 loaded。
- **新增测试**：`tests/test_plugin_sandbox_escape.py` A 组（5 条链，每条断言 broken + **未落盘**）、B 组（白名单正常用法仍放行）。

### 2. [P0] 逃逸链 2 — 异常 traceback 泄漏宿主 globals（P-02）

- **位置**：`plugin_loader.py:193-200`（黑面名单）、`203-232`（AST）、`400-422`（会抛 ValueError 的 api 校验）、`plugin_sandbox.py`（异常边界）。
- **根因**：`PluginAPI` 的参数校验在宿主帧里抛 `ValueError`，插件 `except` 后 `e.__traceback__.tb_next.tb_frame.f_globals` 就是 `plugin_loader` 命名空间（含 `os/sys/importlib`）。`__traceback__/tb_frame/tb_next/f_globals` 都不在黑面名单里，属"未列名反射面"，不需要白名单模块也不需要元编程技巧。
- **改法**（两层，运行时为主）：
  1. **运行时**：受限插件拿到的 api 改为 `plugin_sandbox._GuardedApi` 代理；每次 api 方法调用经 `_GuardedCall.__call__` 转发。宿主异常被捕获后**丢弃**，在 `except` 块**之外**由 `_clean_raise` 抛一个"同类型 + 同消息"的新异常：
     - 新异常的 traceback 只有 `[插件自己的帧, _GuardedCall.__call__ 帧, _clean_raise 帧]`，**没有任何 plugin_loader 帧**；
     - `__context__` / `__cause__` 都是 `None`（在 except 外抛出 → 无隐式上下文），审计建议的 `raise ... from None` 只屏蔽打印、`__context__` 仍可访问，本实现更强；
     - 即使插件摸到沙箱帧的 `f_globals`，那里也只有字符串/常量（`sandbox_globals_clean()` 仍为 True，无 `__builtins__`、无模块对象）。
     - 真 `PluginAPI` 只存于 `_GuardedApi._ga_impl` 槽，该名字在 `__getattribute__/__setattr__` 里明确拒绝；`_load_one` 把它记进 `_LOADED[id]['gapi']`，卸载钩子 `deactivate` 也拿同一个壳（否则卸钩子是绕过清洗的后门）。
  2. **静态**：`_RESTRICTED_ATTR_NAMES` 补 traceback/frame/code 族（`__traceback__/__context__/__cause__/tb_frame/tb_next/tb_lineno/tb_lasti/f_globals/f_locals/f_builtins/f_back/f_code/f_trace/gi_frame/gi_code/gi_yieldfrom/cr_frame/cr_code/cr_await/ag_frame/ag_code/__code__/__closure__/__defaults__/__kwdefaults__`），直接书写在加载期就拒。
- **前后证据**：§0.1（改前 `GLOBALS KEYS: ['__builtins__','os','sys']` 并写出 PWNED2；改后 AST 拒载 + 运行时无宿主帧）。
  运行时层的改后实测（`tests/test_plugin_sandbox_escape.py` D 组）：
  ```
  异常链: [('__main__', ...), ('plugin_sandbox', 无 os/sys), ('plugin_sandbox', 无 os/sys)]
  tb_next.f_globals is plugin_loader.__dict__ = False ; 'os' in g = False
  照审计写法 g['os'].open(target,'w') -> KeyError, 文件未生成
  ```
- **新增测试**：同文件 C 组（3 种直写形态：`tb_next.tb_frame.f_globals` / `tb_frame.f_globals` / `__context__.__traceback__`，均 broken 含 `AST` + 未落盘）、D 组（运行时清洗 5 条断言）、E 组（接线：插件拿到 `_GuardedApi`、内部句柄不可读、宿主侧仍持真 api、沙箱命名空间榨无可榨）。

### 3. [P1] register 部分注册后抛异常 → 注册事务化（P-04）

- **位置**：`plugin_loader.py:400-422`（register_script/register_editor_button 直接写全局）、`523-532`（异常只记 broken）、`633-656`（unload 需要 _LOADED）、`573-585`（load_plugin_from_pack）。
- **根因**：`_load_one` 里 exec 成功、模块已进 `sys.modules`，`reg(api)` 可能先注册了脚本/按钮再抛异常；`except` 只 `append broken`，`_LOADED` 不写入 → `unload_plugin` 直接返回"插件未加载"，清理链不可达。结果是"加载器说失败，但脚本仍可挂、按钮仍可点、模块常驻"。
- **改法**：`_load_one` / `load_plugin_from_pack` 全程事务化：
  - 进 register 前 `_registry_snapshot()` 记录 `(set(SCRIPTS), list(_EDITOR_BUTTONS))`；
  - 任一步抛异常 → `_rollback_load()`：撤本次新增的脚本 id（只撤 `sids_before` 之外、且属于本 api 的）、还原按钮表、`sys.modules.pop(mod_name)`，然后原异常继续上抛（调用方照旧记 broken）。
- **前后证据**（`%TEMP%\probe_scan09_ab2.py`，同一恶意插件"先注册脚本+按钮，再 raise"）：
  ```
  改前: P-04 残留: SCRIPTS=True | 按钮=['半注册按钮'] | sys.modules=['loom_plugin_probe_half']
  改后: P-04 残留: SCRIPTS=False | 按钮=[] | sys.modules=[]
  ```
- **新增测试**：`tests/test_plugin_register_rollback.py` A 组（4 条残留断言 + "不误删他人条目"）、D 组（包内加载同语义，且成功路径不被误伤）、E 组（失败后修好 entry → rescan 能正常加载）。

### 4. [P1] 脚本 id 无所有权 → 禁止覆盖已存在 id（P-05，裁决 Q2=A）

- **位置**：`plugin_loader.py:400-408`（`SCRIPTS[sid] = cls` 无重复检查）、`644-646`（卸载按 `api._sids` 逐个 pop）。
- **根因**：注册表按 id 无差别写入。插件注册 `rotate` 即顶掉内建；卸载时 `pop('rotate')` 让内建**永久消失**（无备份、只有重启进程由模块级 `@register` 重建）；两个插件共用同一 id 时卸载一个会删掉另一个的。
- **改法**：`PluginAPI.register_script` 在写入前检查 `SCRIPTS.get(sid)`：已被**别的类**占用 → 抛 `ValueError("插件 X 注册脚本 id 冲突: 'sid' 已被占用 (禁止覆盖内建/其他插件脚本, Q2=A)")`；同一插件重复注册**同一个类**视为幂等（register 被调两次的容错）。冲突异常由 §3 的事务回滚接住 → 整个插件报 broken，内建/先注册者身份不变。
- **前后证据**：
  ```
  改前: P-05 内建 rotate 未被顶掉: False (name='顶掉内建自转')
  改后: P-05 内建 rotate 未被顶掉: True  (name='自转')
  改后: 插件 probe.pb 注册 'probe_shared' -> broken '冲突'; SCRIPTS['probe_shared'] 仍是 A 的类
  ```
- **新增测试**：`tests/test_plugin_register_rollback.py` B 组（覆盖内建被拒 + 内建身份不变 + 冲突类未混入；两插件抢同一 id：先注册者生效、后注册者 broken）、C 组（卸载只清自己的，内建全在）。

### 5. [P1] EventBus.clear() 派发期立即生效（P-06）

- **位置**：`loom_events.py:184-194`（`clear` 直接改 `_handlers` + `alive=False`），对照 `78-113`（`off` 派发期只入队）、`126-160`（emit 先快照）。
- **根因**：模块 docstring 与 `off()` 注释都声明"派发期间的订阅/取消进入延迟队列"，但 `clear()` 是唯一绕过队列的取消旁路：派发中的回调一调 `clear()/clear(name)`，本轮快照里尚未执行的回调被静默丢掉，`emit` 返回计数也少 1（调用方无法区分"没人订阅"与"被 clear 吃掉"）。
- **改法**：`clear()` 在 `self._dispatching` 时只把"调用那一刻已存在的订阅"追加进 `_pending_remove` 并 `return`（不动 `alive`、不动 `_handlers`），由 `emit` 的 `finally -> _apply_pending()` 统一摘除；非派发期保持原立即语义。语义边界写进 docstring：本轮之后新增的订阅走 `_pending_add`，不会被本次 clear 抹掉。
- **前后证据**（`%TEMP%\probe_scan09_ab2.py`，h1 内 clear，h2 为第二订阅者）：
  ```
  改前: clear('e') 派发期 -> seen=['h1']       emit=1 listeners=0
  改前: clear()   派发期 -> seen=['g1']       emit=1 listeners=0
  改后: clear('e') 派发期 -> seen=['h1','h2'] emit=2 listeners=0
  改后: clear()   派发期 -> seen=['g1','g2'] emit=2 listeners=0
  ```
- **新增测试**：`tests/test_events_clear_defer.py` A/B（本轮完整派发 + 计数 + 本轮后清空）、C（非派发期仍立即生效，原语义不回归）、D（clear 后本轮新增的订阅延迟到下一轮）、E（与 `off(handler)` 语义对照）。

### 6. [P1] Lua VM 泄漏（P-09 / P-25）

- **位置**：`scripts.py:43-90`（`make_lua_script_class`）、`script_glue.py:86-195`（`LoomLuaScript`）。
- **根因**：`DynamicLuaScript.on_start` 每次 `loom_script_lua_new` 一台 lua_State，但全仓**没有任何 `close()` 调用点**：动态类不实现 `on_disable/on_destroy`（基类是 `pass`），`LoomLuaScript` 也没有 `__del__`。每次"播放→停止"/"删除挂 .lua 的物体"都线性泄漏一台 VM（C 侧 lua_State + 预载标准库），编辑器反复调试持续涨内存。
- **改法**：
  1. `DynamicLuaScript` 补 `on_disable()` / `on_destroy()` → `_close_lua()`（幂等：先 `self._lua = None` 再 close，失败只打日志）；`on_start` 重入前先释放旧 VM；启动失败也释放半初始化 VM。
     （引擎侧调用点已存在，无需改引擎：`editor.py:1832` 停止播放调 `on_disable()`；`loom_model_gpu.py:272` `remove_model` 调 `on_destroy()`，`remove_subtree/clear_scene/load_scene` 均经它。）
  2. `LoomLuaScript.close()` 幂等（**先置 `vm=None` 再 free**，杜绝二次 free）且**不抛**（生命周期钩子/`__del__` 里抛异常只会把"停止播放/删物体"变成新崩溃源）；新增 `__del__` 兜底释放孤儿包装。
- **前后证据**（假 VM 计数，见 `%TEMP%\probe_scan09_ab2.py`；C 侧字节数需 instrument 官方件，见 P-25 遗留）：
  ```
  改前: 停止播放后 close 调用次数: 0 | 实例持 VM: True
  改后: 停止播放后 close 调用次数: 1 | 实例持 VM: False
  ```
  （"有无 on_disable 方法"改前后都是 True —— 基类有 pass 版，故真正的判据是 close 次数。）
- **新增测试**：`tests/test_scripts_lua_close.py` A（on_disable 关 1 次 + 重复幂等）、B（on_destroy）、C（重入 on_start 先释放旧 VM）、D（构造失败不留半初始化 VM 且不崩）、E（`LoomLuaScript.close` 幂等 / 释放失败被吞 / `__del__` 兜底），全部用假 VM + 假句柄，**不需要 script.dll**。

---

## 2. 新增回归测试（均被 run_all 收集）

| 文件 | 覆盖 | 断言要点 |
|---|---|---|
| `tests/test_plugin_sandbox_escape.py` | P-01/P-02 | 5 条模块链 + 3 种 traceback 直写 + 运行时清洗 5 条 + 接线 5 条 + 白名单控制组；全部含"**未落盘**"断言 |
| `tests/test_plugin_register_rollback.py` | P-04/P-05 | 失败回滚三表无残留、不误删他人、id 冲突（内建/跨插件）被拒且身份不变、卸载只清自己、包内加载同语义、修好后 rescan 可加载 |
| `tests/test_events_clear_defer.py` | P-06 | 派发中 clear 不吞本轮回调、计数完整、本轮后清空、非派发期仍立即、clear 后新增延迟到下一轮、off 对照 |
| `tests/test_scripts_lua_close.py` | P-09/P-25 | on_disable/on_destroy/重入/构造失败/close 幂等与不抛/`__del__` |

## 3. 设计说明（为什么这样修）

1. **运行时优先，名单为辅**：审计明确指出"名单式防御 = 误用护栏，不是安全边界"。两条 P0 的主防线都放在运行时（模块代理 / 异常边界清洗），AST 名单只作为"直接书写"的第一道门。这样即使攻击者用混淆绕过 AST，拿到的仍是代理对象与清洗后的异常。
2. **不给真对象**：模块代理不返回真模块、不返回子模块；api 代理不返回真绑定方法（`_GuardedCall`）、不暴露真 api（`_ga_impl` 被拒）。"拿不到"比"拦住某个名字"更稳。
3. **异常清洗不用 `from None`**：`raise ... from None` 只设 `__suppress_context__`，`__context__` 仍可读 → 仍能回溯到宿主帧。本实现把宿主异常**整个丢弃**，在 `except` 之外重新抛"同类型+同消息"的新异常，`__context__` 为 `None`。
4. **事务化不引入新状态**：用"进 register 前的注册表快照 + 只撤本次新增"实现，不改注册表数据结构，卸载路径零改动（只是失败路径现在真的没有残留可清）。

## 4. 遗留 / 发现但未动（只登记）

1. **P-10（P3）插件卸载不清理 `sys.modules`**：`unload_plugin` 仍未 `sys.modules.pop`（成功卸载路径）。失败回滚路径已清理；成功卸载路径按"只修列出的问题"未动。
2. **P-03（P2）核心插件 hash→exec TOCTOU**：未改（不在本批清单）。
3. **P-07（P2）once + 重入 emit 触发多次**、**P-08（P2）`cancel()` 与 `off()` 计数漂移**：未改（不在本批清单）；P-06 的修复不依赖它们。
4. **P-11/P-12/P-13/P-14（调度器）**：未改（不在本批清单，且当前无生产提交点）。
5. **P-15（P3）`load_script_dir` 未跳过 `_` 前缀文件**：未改（不在本批清单）。
6. **残余风险（本批修复的边界，必须记录）**：
   - 进程内 Python 无强隔离：`_GuardedApi` 对**下划线属性**仍做转发（为兼容 `deactivate` 钩子里 `api._deactivated = True` 这类既有用法），因此插件可以读写自己的 api 的私有字段（例如清空 `_sids` 只会影响它自己的卸载清理，不能越权覆盖他人 id —— Q2=A 已封死覆盖面）。
   - 模块代理不支持 `from x import *`（需要读 `__all__/__dict__`，两者都被拒）。正常插件按名导入即可；如未来确需支持，应在代理上显式放行 `__all__` 的**值**（字符串列表，不泄露引用）而不是放开下划线规则。
   - 真正的硬边界仍是方案文档里的 L2 子进程最小权限（本批只是把"已证实的进程内逃逸链"堵死）。
   - P-25 的**泄漏字节数**仍未计量（需 C 侧 instrument 或长跑 RSS 采样，超出本批"只改 Python 侧"的边界）；本批只保证"该释放的都释放、且释放幂等"。

## 5. 复现命令

```powershell
cd "D:\my-project - 副本\Loom(py源代码-工作区)\Loom"
python tests/test_plugin_sandbox_escape.py        # 逃逸链固定靶场
python tests/test_plugin_register_rollback.py     # 注册事务化 / id 所有权
python tests/test_events_clear_defer.py           # clear 延迟语义
python tests/test_scripts_lua_close.py            # Lua VM 释放
python tests/test_plugin_loader.py                # 既有插件加载器回归
python tests/test_scripts.py                      # 既有脚本回归
python tests/_tmp/smoke_events.py                 # 既有事件冒烟
python tests/_tmp/ab_batch.py                     # 22 场景渲染对拍
python tests/_tmp/ab_gl_vk_ui.py                  # GL/VK UI 对拍
python tests/run_all.py                           # 全量回归
```

改前/改后对照探针（临时目录，不落仓库）：
`%TEMP%\probe_scan09_ab.py`（P-01/P-02）、`%TEMP%\probe_scan09_ab2.py`（P-04/P-05/P-06/P-09），
"改前"版本由 `git show HEAD:Loom/<file>` 导出到 `%TEMP%\loom_prefix_scan09\` 并优先 `sys.path`。
