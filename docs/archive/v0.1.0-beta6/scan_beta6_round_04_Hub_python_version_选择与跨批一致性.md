# Loom 0.1.0.beta6 第四轮独立复核 · 04：Hub python_version 选择与跨批一致性

> 审计对象：`git diff 7c734e8..HEAD`（beta6 开工以来）中 LoomHub 的 Python 版本选择改动（提交 `cb6aa5d`）、3.13 主线直迁（`42d5d55`）与 GL 4.3 / VK 1.1 表述的跨批一致性。
> 审计者：独立复核子代理（不参与实现）。只读：未改任何受跟踪文件；探针只写 `Loom/tests/_tmp/audit_b6_04_*.py`（该目录被 .gitignore 覆盖）。
> 收尾自查：本轮探针未改任何受跟踪文件（只新增 `Loom/tests/_tmp/audit_b6_04_*.py`，被 .gitignore 覆盖）与任务要求的 `docs/audit/` 新报告。
> **并发在途**：收尾时点的工作区另有并行子代理正在改 `Loom/run_player.py`、`Loom/vk_player.py`、`Loom/loom_backend_guard.py`、`Loom/game_player.py`（含 `test_ab_gl_vk.py`、`tools/package_engine*.py`、`使用操作指南.txt`）。这些文件**不计入本文任何结论**（见 §1.5）。
> 结论速览：**PROVED 10 / DISPROVED 4 / UNKNOWN 1 / CONTRADICTION 0**；其中 P1 两条（包内嵌入式解释器被系统解释器覆盖；源码包"元数据说 3.13、实际嵌 3.12"）。

---

## ① 范围与方法

### 1.1 文件清单（全部整读）

| 文件 | 行数 | 读法 |
|---|---|---|
| `LoomHub/hub_config.py` | 900 | 整读（重点 188-230、550-628、685-721） |
| `LoomHub/hub_controller.py` | 804 | 整读（重点 44-75、522-601） |
| `LoomHub/hub_commands.py` | 796 | 整读（重点 143-171、456-546） |
| `LoomHub/hub_view_tk.py` | 455 | 整读（重点 351-427） |
| `LoomHub/GUI/NovaHubGUI.py` | 509 | 整读（重点 430-484） |
| `Loom/Loom.py` | — | 150-240（Q6 旧注释、`_launch_player`） |
| `Loom/run_player.py` | — | 整份 diff + 32-56、130-140、213-330 |
| `Loom/loom_backend_guard.py` | 146 | 整读 |
| `Loom/loom_gl_version.py` | — | 1-24、25-80（地板常量与门） |
| `Loom/sceneio.py` | — | 1409-1532（migrate / 版本迁移） |
| `Loom/tests/test_hub_python_version.py` | 186 | 整读 |
| `Loom/tests/test_release_version.py` | 326 | 整读 |
| `tools/package_engine.py` | — | 1-30、160-235、300-345（HEAD 与工作区双读） |
| `tools/release_github.py` | — | 350-480（发布说明模板与 python_version 事实源） |
| `README.md` / `使用操作指南.txt` / `docs/design/版本计划…beta6…` / `docs/design/research_beta6_05_python_upgrade.md` / `docs/design/架构互联协议总表.md` | — | 相关段落 |
| 两份方法论文档 + `docs/audit/SCAN_PROTOCOL.md` | 614/735/67 | 整读（判据/8 段式/跳过留痕） |

### 1.2 判定基准（白盒契约清单，后续只引这些）

| 编号 | 契约原文 | 出处 |
|---|---|---|
| C1 | "按 解释器.json 的 python_version 找可用的 python.exe……顺序：① 常见安装目录 ② `py -X.Y` 问出 sys.executable ③ **当前进程解释器正好是该版本**" | `hub_config.py:559-567` |
| C2 | "编译版（kind=exe）走 main_exe，与 Python 版本无关，不受影响" | `hub_config.py:700`（注释）、`scan_beta3_05_packaging_release.md:1622` |
| C3 | "本函数**只做纯命令拼装**，不再在此追加 --agent" | `hub_config.py:717-721` |
| C4 | "返回 (spec dict, 错误字符串或 None)。**无副作用, 可被测试直接断言**" | `hub_commands.py:456-460` |
| C5 | "返回值新增 python_note（命令层/Agent 可见）" | `scan_beta3_05_packaging_release.md:1625`（in-flight 文档） |
| C6 | "S4 打包双轨：3.13 embed……产物内 解释器.json 的 python_version = 13.x；S4 必须验证"包里真的是 3.13 解释器"，不能只看元数据" | `research_beta6_05_python_upgrade.md:277,282` |
| C7 | "⑤ 打包链参数化：`find_python_embed(version="3.12")`……（现为 `:97-108` 硬查 `Python312`）"（= 要求参数化，不是保持 3.12） | `research_beta6_05_python_upgrade.md:251` |
| C8 | "VK 失败回退契约（2026-11-09 裁决 A，取代旧 Q6「崩一次」）……同进程改走 GL 4.3" | `架构互联协议总表.md:199`、`docs/design/版本计划…:207-216` |
| C9 | GL 地板 = 4.3 core / VK 地板 = 1.1 | `loom_gl_version.py:21-24`、`loom_backend_guard.py:24-26`、`架构互联协议总表.md:190-200` |
| C10 | "版本号 = 正在开发的版本号（引擎 0.1.0.beta6 / Hub 0.1.4）" | `test_release_version.py:5-11,81-84`、`docs/README.md:12-13` |

### 1.3 跑过的命令（全部可复跑；输出见 §3 各条）

    py -3.13 Loom\tests\_tmp\audit_b6_04_resolve.py     # 解析顺序/缓存/优先级/refresh/xy 归一
    py -3.13 Loom\tests\_tmp\audit_b6_04_surface.py     # open_project 命令与文案 / launch_spec 副作用 / launch_engine 返回体
    py -3.13 Loom\tests\test_hub_python_version.py      # ALL PASS（exit 0）
    py -3.13 Loom\tests\test_hub.py / test_hub_controller.py / test_hub_interp_cache.py / test_hub_interp_switch.py  # 全 ALL PASS
    py -3.13 Loom\tests\test_release_version.py         # ALL PASS（exit 0）
    py -3.13 Loom\tests\test_backend_fallback_policy.py # ALL PASS（A1/B1 含"不再崩一次"）
    py -3.12 -c "import engine" / py -3.13 -c "import engine"   # 两侧 IMPORT OK
    py -3.13 -S -c "import engine"                        # 模拟"没装依赖的 3.13" -> ModuleNotFoundError
    py -3.13 -c "...pe.find_python_embed()"               # -> ...\Programs\Python\Python312
    py -3.13 -c "<源码里那串 -c>"                          # SyntaxError（见 P-04-01）
    git diff 7c734e8..HEAD -- LoomHub/                    # 改动范围
    git status --porcelain                                # 探针前后一致

### 1.4 范围外的在途改动（按任务要求只标注、不下结论）


`tools/build_engine.py`（未跟踪）、`Loom/build_entry.py`、`Loom/build_game.py`、`tools/package_engine.py`、`tools/package_engine_compiled.py`、`使用操作指南.txt`、`docs/audit/scan_beta3_05_packaging_release.md` 均在工作区未提交。**凡涉及这些文件的判断只当"疑似在途"线索**；P-04-03 的判断基于 **HEAD 提交态**（`git show HEAD:tools/package_engine.py`）而不是工作区。

### 1.5 并发在途登记（收尾时点快照，2026-11-09 23:25）

审计期间另一个子代理（round 01/02 的 GL/VK 轮）在改动这些文件，**本文对它们一律不下结论**：

    M Loom/run_player.py        (+129/-…)   # 例：_persist_backend 改为"只写用户层"、_handle_vk_init_failure 重构
    M Loom/loom_backend_guard.py            # 诊断/弹窗链
    M Loom/vk_player.py                     # VK 门接线
    M Loom/game_player.py
    M Loom/tests/test_ab_gl_vk.py
    M tools/package_engine.py / package_engine_compiled.py
    M 使用操作指南.txt / Loom/build_entry.py / Loom/build_game.py
    M docs/audit/scan_beta3_05_packaging_release.md   # §15 即本轮 Hub 改动的自述文档

**本文引用且收尾时确认未被改动的**：`Loom/Loom.py`、`tools/release_github.py`、`LoomHub/**`、`README.md`、`Loom/sceneio.py`、`Loom/loom_gl_version.py`。
→ 因此 P-04-12 只保留"未改动文件里的过时表述"作为结论；`run_player.py` / `vk_player.py` 的同类旧文案（`py -3.12` 用法行、`explicit 不改写设置` 的 docstring）**改列在途备注**，等该轮收口后由对应审计复核。

---

## ② 粗筛清单（含跳过留痕）

粗筛标签取自方法论文档 §4.3（SEM/BND/IFACE/OVERFIT/AUDIT/TOOL）。

| ID | 位置 | 标签 | 初步方向 |
|---|---|---|---|
| P-04-01 | hub_config.py:601-609 | AUDIT-DEADCODE / SEM-MISMATCH | 兜底③的 `-c` 载荷里 `%%` 双重转义，子进程必 SyntaxError → ③ 永不命中 |
| P-04-02 | hub_config.py:697-706 | IFACE-PRECOND / SEM-SILENT | 系统解释器无条件覆盖包内自带嵌入式 python（依赖可能只在包内） |
| P-04-03 | tools/package_engine.py:164-175,326-341 | AUDIT-DOCIMPL / IFACE-VERSION | 源码包元数据 3.13.15 但 `find_python_embed` 仍硬查 Python312 → 包内实为 3.12 |
| P-04-04 | hub_commands.py:493-497 vs 525-526 | SEM-SILENT | `launch_spec` 算了 python_note，`launch_engine` 返回体丢掉 |
| P-04-05 | hub_controller.py:594-599 / NovaHubGUI.py:480-484 | AUDIT-DOCIMPL | 实际用 3.13，文案写"用系统默认 Python 环境启动"（系统默认=3.12） |
| P-04-06 | hub_config.py:717-721 / hub_commands.py:456-460 | AUDIT-NOCHAIN / BND-RESOURCE | 声明"纯拼装/无副作用"，实际起子进程（每次 2 个）并写模块级缓存 |
| P-04-07 | hub_config.py:550,571-572,587-607 | BND-RESOURCE / SEM-DEFAULT | 缓存只记正结果且永不失效；负结果不缓存 → 每次启动重试 |
| P-04-08 | hub_config.py:553-556 | BND-OFFBYONE | `3.13.15` 只归一成 `3.13`（补丁号被忽略） |
| P-04-09 | hub_config.py:281-317 | SEM-DEFAULT | refresh 会不会把台账里的 python_version 冲掉 |
| P-04-10 | hub_config.py:701-714 | IFACE-VERSION | 编译版是否真不受影响（kind=exe） |
| P-04-11 | hub_view_tk.py:375-389 / NovaHubGUI.py:434-446 / hub_commands.py:157-166 | AUDIT-ASYMMETRY | UI 列表签名不含 python_version；命令层列表不回传该字段 |
| P-04-12 | Loom.py:192-194 / release_github.py:386,433,462 / README.md:44-71 / 多处 docstring | AUDIT-DOCIMPL | "崩一次"/"3.12"等旧表述与 3.13+裁决 A 后的实现冲突 |
| P-04-13 | hub_controller.py:106-113 vs hub_commands.py:346 | AUDIT-ASYMMETRY | Hub 两条"新建项目"写 v8 / v10 两种场景版本 |
| P-04-14 | hub_config.py:601-609 + LoomHub.py:35-36 | SEM-SILENT | 冻结版 Hub 里 `sys.executable`=LoomHub.exe，`-c` 会再拉一个 Hub 进程 |
| P-04-15 | 解释器.json:3-4 / 版本.json / installer.iss:3 / test_release_version.py:83-84 | IFACE-VERSION | 三个版本真源与断言是否自洽 |

### 跳过登记（每条给四类理由之一的具体出处）

| ID | 位置 | 跳过理由（可审计） |
|---|---|---|
| SKIP-01 | hub_config.py:243-528（台账/项目/扫描） | **无改动**：`git diff 7c734e8..HEAD -- LoomHub/hub_config.py` 只 +97 行，全部落在 207-214/550-628/697-706；其余函数字节未变，与 python 选择无共享状态。 |
| SKIP-02 | hub_install.py / hub_install_ui.py | **语言规范+代码事实**：`git grep python_version -- LoomHub/` 命中只 4 处（config/controller/view/list），安装器原样解压 zip 不改元数据（`hub_install.py` 无该字段引用）。 |
| SKIP-03 | loom_backend_guard.py 的弹窗/诊断文本 | **归属其他轮次**：属 VK 轮（round 02）裁决范围；本轮只核对其"VK 地板=1.1 / 同进程回退 GL"表述与 C8/C9 一致（一致）。 |
| SKIP-04 | hub_update.py 自更新链 | **已有回归覆盖**：`test_hub_update.py` `pick_release/is_newer` 用例在 beta5 round_04 已裁决；本轮只确认 Hub 版本真源（P-04-15）。 |
| SKIP-05 | `Loom/tests/ab_* `、渲染/场景资产 | **超范围**：与本主题（Hub 解释器选择）无接口。 |
| SKIP-06 | `tools/build_engine.py` 等未提交文件 | **在途**：按任务要求只标注"疑似在途"，不作结论（见 §1.4）。 |
| SKIP-07 | VK 真机 1.1 门实测 | **无设备**：本机无独立 VK 探针需求，按硬约束 2 记 **UNVERIFIED**，不计入统计。 |
| SKIP-08 | 冻结版 LoomHub.exe 行为 | **禁止起阻塞 GUI**：见 P-04-14 的 P-UNKNOWN。 |

---

## ③ 逐项裁决（反手=证伪优先，正手=证真在后）

### P-04-01 兜底③"当前进程解释器正好匹配"是死分支 —— **P-PROVED（P2）**

**【反手 · 证伪】结论：证伪失败（③ 中存在必然失败路径）**

1. **判定基准**：C1 —— "③ 当前进程解释器正好是该版本"（`hub_config.py:566`）。
2. **代码证据**：
       try:
           r = subprocess.run([sys.executable, '-c',
                               'import sys;print("%%d.%%d" %% sys.version_info[:2])'],
                              capture_output=True, text=True, timeout=10)
           if (r.stdout or '').strip() == xy:
     （`hub_config.py:601-609`）
3. **路径枚举**（`resolve_python_for` 全部出口）：
   - 路径 A：`python_xy` 为空 → `return None`（`568-570`）；
   - 路径 B：命中 `_PY_RESOLVE_CACHE` → 返回缓存（`571-572`）；
   - 路径 C：①② 命中 → 返回（`573-600`）；
   - 路径 D：③ 命中 → 返回 `sys.executable`（`601-607`）；
   - 路径 E：全落空 → `return None`（`610`）。
   疑似行为发生在路径 D。**路径 D 能否命中取决于 `subprocess.run` 的 stdout 是否等于 xy**；而该 `-c` 载荷在 Python 侧解析即失败（正手 §4 实测），stdout 恒为 `''`，`'' == xy` 恒假 → 路径 D **结构上不可达**，控制流必落 E。函数体内无 `**kwargs` 转发/动态分派/闭包捕获。→ **覆盖全部路径，证伪失败**。
4. 预期：见正手 §4。5. 实际：见正手 §5。6. 差异：见正手 §6。7. 验证：见正手 §7。8. 判定：**证伪失败**。

**【正手 · 证真】结论：P-PROVED**

1. **判定基准**：C1（`hub_config.py:566`：③ = 当前进程解释器正好是该版本）。
2. **代码证据**：同上 `hub_config.py:601-609`；注意载荷是普通字符串（非 %-格式化），`%%` 未被折半。
3. **推理链 / 最小复现**：把 ①②人为落空（`LOCALAPPDATA/ProgramFiles*` 指向空目录、`shutil.which`→None），运行在 3.13 解释器下调用 `resolve_python_for('3.13.15', use_cache=False)`。
4. **预期**（按 C1）：返回 `sys.executable`（3.13）。
5. **实际**：返回 `None`。
6. **差异分析**：少做了"③ 命中"这一整条路径；机制是 `-c` 载荷 SyntaxError → stdout 空。
7. **可复现验证**：
       py -3.13 Loom\tests\_tmp\audit_b6_04_resolve.py
   实测输出（§A）：
       C:\Python313\python.exe 存在? False
       sys.executable           = ...\Python313\python.exe
       sys.version_info[:2]     = (3, 13)
       resolve_python_for('3.13.15', use_cache=False) = None
       正确 -c 输出 = '3.13'  rc = 0
       源码里那串 -c 输出 = ''  rc = 1
       源码里那串 -c stderr 尾行 = SyntaxError: invalid syntax
   同命令的最小复现：
       py -3.13 -c 'import sys;print("%%d.%%d" %% sys.version_info[:2])'   -> EXIT=1（SyntaxError）
8. **影响与等级**：兜底消失。凡"①安装目录找不到 + ②py 启动器不可用"的机器（便携/自定义目录/裁剪版 py），即使 Hub 自己就跑在目标版本上也不再匹配 → 静默回退默认解释器（见 P-04-05：用户不会被告知用错版本）。**P2**（功能降级 + 不可见；非崩溃）。

---

### P-04-02 系统解释器无条件覆盖包内自带嵌入式 Python —— **P-PROVED（P1）**

**【反手 · 证伪】证伪失败**

1. **判定基准**：`default_python` 的既有契约 —— "引擎自带嵌入式 Python 优先（发布包 zip 设计如此：开箱即用）"（`hub_config.py:644-652`）；新代码未声明要改变该优先级（`697-706` 注释只说"按 python_version 精确挑解释器"，没说"压过包内解释器"）。
2. **代码证据**：
       py_exe = default_python(engine_dir=info.get('dir'))
       if str(info.get('kind') or 'py') != 'exe':
           _want = str(info.get('python_version') or '').strip()
           if _want:
               _matched = resolve_python_for(_want)
               if _matched:
                   py_exe = _matched
   （`hub_config.py:697-706`）
3. **路径枚举**（启动源码引擎时 `py_exe` 的全部来源）：
   - 路径 1：包内 `<pkg>/python/python.exe` 存在，且系统解析到同版本 → `py_exe` **被覆盖**为系统路径（可疑路径）；
   - 路径 2：包内存在，系统解析不到 → 保留包内（正确）；
   - 路径 3：包内不存在，系统命中 → 用系统（本改动的目的，正确）；
   - 路径 4：都无 → 回退 `_py_launcher_python`/PATH（旧行为）。
   证伪要求"路径 1 也安全"，但路径 1 把解释器换成了**与包内 site-packages 无关**的另一个 3.13；包内依赖是用 `pip install --target <pkg>/python/Lib/site-packages` 装的（`package_engine.py:195-206`），系统解释器不会自动继承。→ **证伪失败**。
4. 预期：见正手。5. 实际：见正手。6-7. 见正手。8. 判定：**证伪失败**。

**【正手 · 证真】P-PROVED**

1. **判定基准**：同上（包内解释器优先 = "开箱即用"承诺，`hub_config.py:644-646` 注释）。
2. **代码证据**：`hub_config.py:697-706`；包内目录结构见 `package_engine.py:317-320` 与 `tools/dist/_engine_stage`（实测含 `python/`）。
3. **推理链 / 最小复现**：按发布包布局造目录 `<pkg>/0.1.0.beta6/{Loom/Loom.py, python/python.exe, Loom/解释器.json(python_version=3.13.15)}`；`discover_interpreter` → `build_launch_command`。
4. **预期**：命令首段 = `<pkg>/python/python.exe`（包内，开箱即用）。
5. **实际**：命令首段 = `C:\Users\...\Programs\Python\Python313\python.exe`（系统），包内 python 被丢弃。
6. **差异分析**：优先级被反转；用户机器上"系统 3.13 是干净的（没装 moderngl/numpy/PySide6/culverin）"时，引擎在 import 阶段即死。
7. **可复现验证**：
       py -3.13 Loom\tests\_tmp\audit_b6_04_resolve.py
   §C 实测：
       discover_interpreter = {'kind': 'py', 'python_version': '3.13.15'}
       包内嵌入式 python  = ...\audit_b6_04_pkg_xxx\0.1.0.beta6\python\python.exe
       build_launch_command = ['C:\\Users\\Administrator\\AppData\\Local\\Programs\\Python\\Python313\\python.exe', '...\\0.1.0.beta6\\Loom\\Loom.py']
       系统解析结果         = C:\Users\...\Python313\python.exe
       命令用的是系统 python 而非包内嵌入 = True
   后果链的第二环（依赖缺失 = 启动即死）：
       py -3.13 -S -c "import sys;sys.path.insert(0,'.');import engine"
       -> ModuleNotFoundError: No module named 'numpy'（engine.py:24）  EXIT=1
   第三环（死得看不见）：`hub_controller.open_project` 把 `cmd[0]` 换成同目录 `pythonw.exe`（无控制台，`585-592`），并设 `LOOM_QUIET=1`（`571`）；随后只打印"已启动"（`597-599`），无存活性检查 → 用户看到"已启动"但什么都没发生。
8. **影响与等级**：源码分发版（`Loom.bat` 那条路径之外，由 Hub 打开项目的那条路径）从"开箱即用"退化为"取决于用户恰好装没装引擎依赖"。**P1**（功能错误 + 静默失败）。

---

### P-04-03 源码包"元数据 3.13.15 / 实际嵌入 3.12" —— **P-PROVED（P1）**

**【反手 · 证伪】证伪失败**

1. **判定基准**：C6（S4：产物内 python_version = 3.13.x，且"必须验证包里真的是 3.13 解释器，不能只看元数据"）+ C7（打包链要参数化 `find_python_embed`，而现状是硬查 Python312）。
2. **代码证据**：
   - `tools/package_engine.py:164-175`：`for c in (os.path.expandvars(r'%LOCALAPPDATA%\Programs\Python\Python312'), r'C:\Python312'):` —— 只找 3.12；找不到就 `SystemExit('找不到 Python 3.12 运行时')`（`181-184`）。
   - `tools/package_engine.py:326-341`：只改 `version`/`distribution`/`player_runtime` 后原样写回 —— `python_version` **不做任何改写/校验**。
   - `Loom/解释器.json:4` 已是 `"python_version": "3.13.15"`（提交 `42d5d55`）。
3. **路径枚举**（打源码包时 `python_version` 与包内解释器的组合）：
   - 路径 1：开发者设了 `LOOM_PYEMBED_DIR` 指向 3.13 → 元数据与产物一致（唯一正确路径，但**无断言强制**）；
   - 路径 2：未设 → `find_python_embed` 命中本机 Python312 → 包内是 3.12，元数据仍写 3.13.15（不一致，**默认路径**）；
   - 路径 3：本机连 Python312 都没有 → 打包直接 SystemExit（不能产出）；
   - 路径 4：手工改 `tools/python-embed` → 依赖人工纪律，无校验。
   证伪要求"路径 2 不可能发生"，但 `find_python_embed()` 在**本机实测**就命中 Python312（正手 §7），且这是默认路径。→ **证伪失败**。
4. 预期：见正手。5. 实际：见正手。6-7. 见正手。8. 判定：**证伪失败**。

**【正手 · 证真】P-PROVED**

1. **判定基准**：C6/C7（research_beta6_05 §⑤/S4）。
2. **代码证据**：同上三处 + `tools/package_engine.py:5` docstring 仍写"嵌入式 Python 3.12"、`readme 模板` `230` 也写"嵌入式 Python 3.12（含依赖）"。
3. **推理链 / 最小复现**：`git show HEAD:tools/package_engine.py`（提交态，非工作区）→ 调用 `pe.find_python_embed()`。
4. **预期**：返回 3.13 运行时目录（C7 要求参数化到 3.13）；产物 `解释器.json.python_version` 与实际 `python/python.exe --version` 一致（C6）。
5. **实际**：返回 `C:\Users\...\Programs\Python\Python312`；元数据字段原样来自 `Loom/解释器.json`（3.13.15）→ 包内 3.12 / 元数据 3.13.15。
6. **差异分析**：包对 Hub 撒谎；Hub 拿这个 3.13.15 去选**系统** 3.13（P-04-02），于是"包内 3.12 + 依赖"被彻底绕过 —— 两条缺陷叠乘。
7. **可复现验证**：
       py -3.13 -c "import sys;sys.path.insert(0,'tools');import package_engine as pe;print(pe.find_python_embed())"
       -> C:\Users\Administrator\AppData\Local\Programs\Python\Python312
       git show HEAD:tools/package_engine.py | Select-String 'Python312|嵌入式 Python'
       -> 4 处命中（164-175/184/230）
   现有 beta6 产物是**编译版**（`tools/dist/Loom-0.1.0.beta6.zip` 内 `解释器.json`：`build_mode=compiled`, `python_version=3.13.15`，由 `package_engine_compiled.py:174` 用 `sys.version_info[:3]` 生成，自洽）—— 所以缺陷**只在"下一次打源码包"时引爆**。
8. **影响与等级**：发布链可产出"元数据说 3.13、包内是 3.12"的源码包；`test_release_version.py` 不校验 python_version（`100-118` 只校验 version）→ **无门禁**。**P1**（发布物与元数据不一致 + 无回归门）。

---

### P-04-04 命令层丢掉了 python_note —— **P-PROVED（P2）**

**【反手 · 证伪】证伪失败**

1. **判定基准**：C5（`launch_spec` 的 python_note "命令层/Agent 可见"）；C4 的"可被测试直接断言"也隐含返回值要被使用方消费。
2. **代码证据**：
   - 生产：`return {... 'python_note': cfg.interp_python_note(info)}, None`（`hub_commands.py:493-497`）；
   - 消费：`out = {'pid':…, 'command':…, 'interpreter':…, 'cwd':…, 'prefer':…, 'mode':…}`（`hub_commands.py:525-526`）—— 无 python_note。
3. **路径枚举**（`launch_engine` 的返回构造）：只有 525-526 一处 `out`；后续仅追加 `agent_port`/`agent_wait`（`538,544`）—— 无任何分支会把 `spec['python_note']` 写回。→ `python_note` 在整个文件里除 497 行外无第二个出现（正手 §7 的 grep 已证）。→ **证伪失败**。
4-6. 见正手。7. 见正手。8. 判定：**证伪失败**。

**【正手 · 证真】P-PROVED**

1. **判定基准**：C5。
2. **代码证据**：同上。
3. **推理链 / 最小复现**：`info['python_version']='' `（缺字段，避免真的起子进程），桩 `Popen`，调 `cmd_launch_engine({'agent': False})`，看返回键。
4. **预期**：返回体含 `python_note`（C5）。
5. **实际**：返回键 = `['command','cwd','interpreter','mode','pid','prefer']`，无 `python_note`。
6. **差异分析**：Agent/命令行用户永远看不到"回退默认 Python"的提示；GUI 路径有（`hub_controller.py:596-599`），两路不对称。
7. **可复现验证**：
       py -3.13 Loom\tests\_tmp\audit_b6_04_surface.py
   §I 实测：
       launch_engine 返回键 = ['command', 'cwd', 'interpreter', 'mode', 'pid', 'prefer']
       python_note 在返回体里 = False
       launch_spec 里算了 note = True
   §J 实测（全文件只有 1 处）：
       hub_commands.py:497| 'python_note': cfg.interp_python_note(info)}, None
8. **影响与等级**：违反 C5"命令层/Agent 可见"；排查"为什么 Hub 启的引擎行为不对"时少一条关键证据。**P2**（功能缺失 + 可诊断性下降）。

---

### P-04-05 "用系统默认 Python 环境启动"与实际解释器不符 —— **P-PROVED（P2）**

**【反手 · 证伪】证伪失败**

1. **判定基准**：`hub_controller.py:594` 的默认文案 + 本改动"**不改系统默认**"的口径（`hub_config.py:562-563,698-700`）—— 既然不改系统默认，就不能对外宣称"用系统默认环境"。
2. **代码证据**：
       note = "用系统默认 Python 环境启动" if interp['kind'] == 'py' else "直接运行 exe"
       py_note = cfg.interp_python_note(interp)   # 匹配成功时为 ''
       self.set_msg("已启动: … %s%s" % (note, " ｜ " + py_note if py_note else ''))
   （`hub_controller.py:594-599`）
3. **路径枚举**：
   - 路径 1：`python_version` 有且解析到 3.13 → `note` 仍打印"系统默认 Python 环境启动"（**错误陈述**），`py_note` 为空（无纠正）；
   - 路径 2：解析不到 → note 同样错误 + `py_note` 补一句"已回退默认 Python"（用户会读到前后矛盾的两句话）；
   - 路径 3：`kind='exe'` → "直接运行 exe"（正确）。
   路径 1/2 均产生错误陈述。→ **证伪失败**。
4-6. 见正手。7. 见正手。8. 判定：**证伪失败**。

**【正手 · 证真】P-PROVED**

1. **判定基准**：同上。
2. **代码证据**：`hub_controller.py:594-599`；视图侧 `NovaHubGUI.py:480-484`（"启动 .py 解释器使用系统默认 Python → %s" % `ctrl.py_ver`，而 `py_ver` 是启动时探测的系统默认 = 3.12，`hub_controller.py:54`）。
3. **推理链 / 最小复现**：桩 `Popen`，`open_project` 一个 `python_version=3.13.15` 的源码引擎。
4. **预期**：文案点名实际使用的 3.13（或至少不说"系统默认"）。
5. **实际**：命令用 `...\Python313\pythonw.exe`，文案"用系统默认 Python 环境启动"。
6. **差异分析**：命令与文案互相矛盾；用户按文案去查系统默认（3.12）会查错方向。
7. **可复现验证**：`py -3.13 Loom\tests\_tmp\audit_b6_04_surface.py` §G：
       启动命令 = ['...\Python313\pythonw.exe', '...\Loom.py', '--open', '...\a.json', '--agent']
       状态栏文案 = 已启动: Loom 0.1.0.beta6 (py) 用系统默认 Python 环境启动
       文案声称"系统默认 Python" = True
8. **影响与等级**：**P2**（可诊断性/事实陈述错误；不改变启动行为）。

---

### P-04-06 "纯拼装 / 无副作用"契约被破坏（每次启动最多 4 个子进程）—— **P-PROVED（P2）**

**【反手 · 证伪】证伪失败**

1. **判定基准**：C3（`build_launch_command` "只做纯命令拼装"）、C4（`launch_spec` "无副作用, 可被测试直接断言"）。
2. **代码证据**：`hub_config.py:700-706`（在拼装函数里调 `resolve_python_for` → `subprocess.run`，`589-600`；并写模块级 `_PY_RESOLVE_CACHE`，`587/597/606`）；`hub_commands.py:481` 在 `launch_spec` 里调它，`497` 再调 `interp_python_note`（后者内部又 `resolve_python_for`，`624`）。
3. **路径枚举**（`launch_spec` 的副作用面）：
   - 路径 1：`python_version` 缺失/不可解析 → 两次解析 × 2 子进程 = 4 个（本机实测，见正手 §7）；
   - 路径 2：缓存已命中 → 0 子进程（但这是"曾经有过副作用"的结果）；
   - 路径 3：`kind='exe'` → 0 子进程（`interp_python_note` 立刻返回空）。
   路径 1 违反 C3/C4。→ **证伪失败**。
4-6. 见正手。7. 见正手。8. 判定：**证伪失败**。

**【正手 · 证真】P-PROVED**

1. **判定基准**：C3/C4。
2. **代码证据**：同上。
3. **推理链 / 最小复现**：把 `cfg.subprocess.run` 换成计数器包一层，调 `hcom.launch_spec({}, info=info_with_bad_python)`。
4. **预期**：0 个子进程、0 次外部状态读取（C4）。
5. **实际**：4 个子进程；单次 `resolve_python_for` 首解耗时 311 ms（本机）。
6. **差异分析**：GUI `open_project` 走同一路径 → 打开项目前在 UI 线程里同步等待最多 2×20 s（`timeout=20`/`10`）。"纯函数"的测试断言也不再可信（返回值依赖机器上装了什么）。
7. **可复现验证**：`py -3.13 Loom\tests\_tmp\audit_b6_04_surface.py` §H：
       launch_spec 期间启动子进程次数 = 4
   `audit_b6_04_resolve.py` §D：
       第一次 = None  子进程 2 次  耗时 311 ms
       第二次 = None  子进程 2 次
       open_project 一次（build_launch_command + interp_python_note）子进程 = 4
8. **影响与等级**：**P2**（UI 卡顿 + 破坏可测试性契约；最坏 40 s 同步等待）。

---

### P-04-07 解析缓存"只记好的、永不失效" —— **P-PROVED（P2）**

**【反手 · 证伪】证伪失败**

1. **判定基准**：C1 的"找可用的 python.exe"（"可用"是现在时，不是"曾经可用"）；`resolve_python_for(spec, use_cache=True)` 的缓存语义未声明"永久"。
2. **代码证据**：`hub_config.py:550`（`_PY_RESOLVE_CACHE = {}`）、`571-572`（命中直接返回，无 `os.path.isfile` 复核）、`587/597/606`（只写正结果）、`610`（失败直接 `return None`，不写缓存）。
3. **路径枚举**：
   - 路径 1：命中缓存的路径存在 → 正确；
   - 路径 2：命中缓存的路径已被删除/移动 → **返回死路径**（可疑）；
   - 路径 3：上次失败（未缓存）→ 每次重试（对"装了新 Python"友好，但代价见 P-04-06）；
   - 路径 4：`use_cache=False` → 不复核也不失效缓存（`571` 只在 use_cache 为真时读，不清理）。
   路径 2 违反"可用"。→ **证伪失败**。
4-6. 见正手。7. 见正手。8. 判定：**证伪失败**。

**【正手 · 证真】P-PROVED**

1. **判定基准**：同上。
2. **代码证据**：同上。
3. **推理链 / 最小复现**：造 `<tmp>/Python313/python.exe`，`LOCALAPPDATA=<tmp>`，解析成功 → 删除该 exe → 再解析（默认 `use_cache=True`）。
4. **预期**：返回 `None`（或换下一个候选），总之不是不存在的路径。
5. **实际**：仍返回已删除的路径；只有 `use_cache=False` 才为 `None`。
6. **差异分析**：Hub 常驻进程里"卸载/移动 Python"后，每次开项目都拿死路径 → `Popen` 抛 `FileNotFoundError` → `open_project` 走 `except OSError` 报"启动失败"（可见，但原因指向错误方向，且不会自愈——只能重启 Hub）。
7. **可复现验证**：`audit_b6_04_resolve.py` §B：
       第一次解析 = ...\Python313\python.exe  存在= True
       删除后（默认走缓存）= ...\Python313\python.exe  存在= False
       删除后（use_cache=False）= None
8. **影响与等级**：**P2**（用户态"卸载/换装 Python"这一正常操作会让 Hub 进入不可自愈状态）。

---

### P-04-08 只按 x.y 匹配（3.13.15 → 任意 3.13）—— **P-DISPROVED**

**【反手 · 证伪】证伪成功**

1. 判定基准：`python_xy` 的 docstring **明确**"'''3.13.15''' / '''3.13''' / '''python3.13''' -> '''3.13'''"（`hub_config.py:554`），即按 xy 归一是设计选择，不是缺陷。
2. 代码证据：`555-556`（正则 `(\d+)\.(\d+)`）、注释 `566`（③ 也是按版本"正好是该版本"，实现按 xy）。
3. 路径枚举：`3.13.15`→`3.13`；`3.13`→`3.13`；`python3.13`→`3.13`；空/None→`''`（`568` 返回 None）；`'3'`/`'13'`→`''`（无点，安全）。所有合法输入的行为与 docstring 一致。
4. 预期=实际（见验证）。5-7. 验证输出（`audit_b6_04_resolve.py` §E）：`'3.13.15' -> '3.13'`、`'' -> ''`、`None -> ''`、`'3' -> ''`。8. 判定：**DISPROVED**（唯一副作用在正手侧已无法证真：3.13 的补丁号差异不影响 wheel ABI/API，且提示文案也按 xy 表述，无从构造"补丁号必须精确"的可执行反例）。

**【正手 · 证真】证真失败**

1. 判定基准：同 C1。4. 预期：若"必须精确 3.13.15"，则应拒绝 3.13.0。5. 实际：`python_xy` 恒返回 xy，级别信息在设计上被丢弃。6. 差异：无契约要求精确补丁号 → 不构成差异。7. 验证：`'3.13.0' 与 '3.13.15' 得到同一 xy`（同上探针）。8. 判定：**证真失败**（四象限：反手成功+正手失败 → DISPROVED）。

> 边界留痕：若 metadata 误填引擎版本（如 `0.1.0.beta6`），`python_xy` 会得 `0.1` 并去找 `Python01`（无害但会白跑 2 个子进程）。不单独计项，并入 P-04-11 的卫生建议。

---

### P-04-09 refresh_interpreters 会不会丢 python_version —— **P-DISPROVED**

**【反手 · 证伪】证伪成功**

1. 判定基准：`refresh_interpreters` docstring —— "按各目录下的 解释器.json **重新识别**……目录消失/主程序缺失的条目**直接移除**"（`hub_config.py:282-289`）；即"以磁盘为准"。
2. 代码证据：`290-308`：`info = discover_interpreter(d)` → 成功则 `out.append(info)`（info 含 `python_version`，`214`）；失败则 `keep=dict(it)` 保留原字段 + `stale`。
3. 路径枚举：(a) 正常目录 → discover 重新读出 python_version（保留）；(b) 目录/主程序消失 → 保留原 dict（保留）；(c) 元数据被换成**不含该字段**的版本 → discover 返回 `python_version=''`（**置空**，符合"以磁盘为准"）；(d) 元数据坏 JSON → `load_json` 返回 None → 走 (b)（保留）。三种保留下 + 一种按设计覆盖，均有源码依据。
4. 预期=实际（下）；5-7. 验证（`audit_b6_04_resolve.py` §F）：
       正常 refresh: 3.13.15  changed= False
       磁盘元数据去掉该字段后 refresh: ''  changed= True
   即"正常路径不丢"；`changed=False` 还证明 refresh 不会每次重写台账。8. 判定：**DISPROVED**（不构成缺陷；但 (c) 是"台账手改值会被磁盘覆盖"的边界，需在文档写明，见 §⑥ 问题 3）。

**【正手 · 证真】证真失败**

1. 判定基准：若缺陷成立，应出现"磁盘元数据仍有该字段、台账却丢值"。5. 实际：该路径不存在（(b)(d) 都保留原值）。7. 验证：上面 §F 的第二段是**主动删除磁盘字段**后的结果，不是丢失。8. 判定：**证真失败** → DISPROVED。

---

### P-04-10 编译版是否真不受影响 —— **P-DISPROVED**

**【反手 · 证伪】证伪成功**

1. 判定基准：C2。
2. 代码证据：`hub_config.py:701`（`if str(info.get('kind') or 'py') != 'exe':` 才解析）、`707-714`（`kind=='exe'` → `cmd=[main_path]`）、`interp_python_note` `618-619`（`kind=='exe'` 立即返回空）；`hub_controller.py:586` 的 pythonw 替换只在 `kind=='py'`。
3. 路径枚举：`prefer='exe'` & main_exe 存在 → 纯 exe；`prefer='py'` & 无 main_py → 回落 `kind=='exe'` 分支；`prefer='py'` & 有 main_py（编译包没有 .py）→ 不可能。三条路径都不含 python。附：`default_python(engine_dir=…)` 仍会被调用（`697`）但结果不进入命令。
4/5/7. 验证：`test_hub_python_version.py` ⑤ 断言 `cmd == [<dir>/Loom.exe]` 且 note 为 '' → ALL PASS；实际 beta6 编译包 `tools/dist/Loom-0.1.0.beta6.zip` 内 `解释器.json` = `build_mode=compiled / python_version=3.13.15 / main_exe=Loom.exe`，`discover_interpreter` 得 `kind='exe'`。8. 判定：**DISPROVED**（"完全不受影响"成立）。

**【正手 · 证真】证真失败**

1. 判定基准：C2。5. 实际：找不到任何 `kind='exe'` 且命令含 python 的输入（`main_py` 缺失时无法进入 py 分支）。8. 判定：**证真失败** → DISPROVED。

> 附带发现（不单列）：编译包的 `default_python` 仍会查 `<pkg>/python/python.exe`（不存在，无副作用），属无害冗余。

---

### P-04-11 显示层/命令层对 python_version 的不对称 —— **P-PROVED（P3）**

**【反手 · 证伪】证伪失败**

1. 判定基准：`scan_beta3_05…:1626`（"解释器列表行显示 , py3.13.15"）+ `hub_commands.py:157` docstring"引擎列表 (全量, 含 dir/version/kind/default)"。
2. 代码证据：`hub_view_tk.py:375-376`（`ips = tuple((default,name,version,kind))`）、`NovaHubGUI.py:434-435`（同）、`hub_commands.py:162-166`（字段表无 python_version）。
3. 路径枚举：(a) 引擎被原地替换、name/version/kind 全同但 python_version 变 → 列表签名不变 → **不重建**，显示陈旧；(b) 命令层任何查询 → 永远拿不到 python_version。两条都不满足"全量/显示"承诺。→ **证伪失败**。
4-6. 见正手。7. 见正手。8. 判定：**证伪失败**。

**【正手 · 证真】P-PROVED**

1. 判定基准：同上。
2. 代码证据：同上。
3. 推理链：列表重建由签名决定（`379-380` / `437`）；签名不含 python_version → 值变化不触发重建。命令层字段表是白名单式构造（`162-166`）→ 新字段不会自动出现。
4. 预期：替换引擎后列表行显示新 py 版本；`interpreter_list` 含 python_version。
5. 实际：均不成立（静态事实，两条都是封闭字段表）。
6. 差异：显示/诊断信息缺一维。7. 验证：`git grep -n "python_version" -- LoomHub/\` 仅 4 处（config×2、controller 0、两个视图各 1、commands 0）：
       LoomHub/hub_config.py:214,620,623,702（config 内部）
       LoomHub/GUI/NovaHubGUI.py:442 / LoomHub/hub_view_tk.py:385（只用于格式化行文本）
       -> hub_commands.py 无命中
8. **影响与等级**：**P3**（显示陈旧 + Agent 侧无法核对版本；排查成本）。

---

### P-04-12 过时注释与文档（含 Loom.py:192-194 / 发布说明模板 / README 3.12） —— **P-PROVED（P3）**

**【反手 · 证伪】证伪失败**

1. **判定基准**：C8（裁决 A 取代旧 Q6"崩一次"）、C10（3.13 主线）、`hub_config.py:562-563`（"系统 .py 关联仍是 3.12"，说明 3.12 只剩"回退/历史"身份）。
2. **代码/文档证据**（原样）：
   - `Loom/Loom.py:192-194`：
         显式 --backend 由 _cli_backend 判定, 交给 run_player 的后端策略
         (Q6: 显式 vulkan 失败只报错不改写设置; 设置/默认走到 vulkan 失败则把
         设置回退成 opengl 并崩一次)。
   - `tools/release_github.py:386`：`'- **渲染后端可切换**…；Vulkan 不兼容时崩一次并把配置回退 OpenGL'`（`DEFAULT_HIGHLIGHTS`，且 `tools/release_notes/` 里**没有** `engine-0.1.0.beta6.md`，所以 beta6 发布说明会用这段）；
   - `tools/release_github.py:433,462`：`pyver=_facts['python_version'] or '3.12'`；
   - `README.md:44,49,56,63,70`：`Python 3.12` / `py -3.12`；
   - `hub_view_tk.py:16-17`、`LoomHub.py:5`、`LoomHubGUI.py:9-11`、`NovaHubGUI.py:26`、`ColorHubGUI.py:17`、`ui/loom_gui.py:16`：启动命令示例全写 `py -3.12`（这些文件收尾时未被并行子代理改动）；
   - 计划 §9.2 点名函数 `require_vk_backend()`，实现叫 `require_vulkan_api()`（HEAD 版 `loom_backend_guard.py:96`；该文件当前**在途**）。
   - **在途备注（不作结论）**：HEAD 版 `run_player.py:22,351`（用法行 `py -3.12`）、`run_player.py:297`（`explicit=True … 显式 vulkan 失败不改写设置`，而归属于同一裁决 A 的 `test_backend_fallback_policy.py:157-171` B1 已断言"显式也改写"）、`vk_player.py:9`——这三个文件收尾时正被 round 01/02 子代理改写，等其收口后由该轮复核。
3. **路径枚举**：`DEFAULT_HIGHLIGHTS` 被使用的分支 = `load_highlights` 找不到版本文件时（`release_github.py:400-409`）→ beta6 命中；HEAD 版 `run_player.py:239-247` 里 `_persist_backend('opengl')` 无条件执行（工作区在途）→ 文档句必错。→ **证伪失败**。
4-6. 见正手。7. 见正手。8. 判定：**证伪失败**。

**【正手 · 证真】P-PROVED**

1. 判定基准：C8/C10。
2. 代码证据：HEAD 版 `run_player.py:215-262`（`_handle_vk_init_failure`：先 `_persist_backend('opengl')`，再 `if explicit or was_hand_picked: print(note)`，**不 SystemExit**；工作区在途，结论只对 HEAD 成立）；`test_backend_fallback_policy.py` A1/B1 全 PASS。
3. 推理链：Loom.py 的注释描述的是"崩一次"，实现在 2026-11-09 改成"同进程继续"；release_github 的默认要点仍写"崩一次"；beta6 无版本要点文件 → 发布出去的用户文档会说错行为。
4. 预期：文档与实现一致（"同进程改走 GL 4.3"）。
5. 实际：`Loom.py:192-194` 与 `release_github.py:386` 两处仍写"崩一次"（两个文件收尾时均未被改动）。
6. 差异：方向明确（旧行为描述 vs 新行为）。7. 可复现验证：
       py -3.13 Loom\tests\test_backend_fallback_policy.py   -> ALL PASS（A1 不退出/B1 显式也改写）
       Get-ChildItem tools\release_notes | Select-Object Name -> 无 engine-0.1.0.beta6.md
       git grep -n '3\.12' -- README.md -> 5 行
8. **影响与等级**：**P3**（发布说明/上手文档会写错行为或写错解释器；不改变运行逻辑）。

---

### P-04-13 Hub 两条"新建项目"写不同场景版本（v8 / v10） —— **P-PROVED（P3）**

**【反手 · 证伪】证伪失败**

1. 判定基准：`sceneio.SCENE_VERSION = 10`（`sceneio.py:57`）是唯一写侧版本；同一产品里两个"新建"入口应产出同版本文件。
2. 代码证据：`hub_controller.py:106-113` `{"version": 8, …}`；`hub_commands.py:346` `EMPTY_SCENE = {"version": 10, …}`。
3. 路径枚举：(a) GUI 新建（`new_project`→`do_new_project_file`→`new_scene_file`）→ v8；(b) 命令层新建（`project_create`）→ v10；(c) 引擎内新建 → `SCENE_VERSION=10`。v8 可被加载（`migrate` `1471-1532` 有 v8→v9→v10 分支），所以不是崩溃，但产出不一致、且每次打开 v8 都会走迁移路径。→ **证伪失败**。
4-6. 见正手。7. 见正手。8. 判定：**证伪失败**。

**【正手 · 证真】P-PROVED**

1. 判定基准：同上。
2. 代码证据：同上 + `sceneio.py:1413`（`scene_from_dict` 先 `migrate(data)`）。
3. 推理链：两处常量各自硬编码；无共享常量。
4. 预期：两处都写 `SCENE_VERSION`（或都写 10）。
5. 实际：8 vs 10。
6. 差异：Hub 内部不一致；D7 计划把 SCENE_VERSION 升 11，届时**要改两处**且容易漏（这正是 `v8` 漏到现在的原因）。
7. 可复现验证：
       Get-Content LoomHub\hub_controller.py | Select-Object -Skip 105 -First 9
       -> {"version": 8,
       Select-String -Path LoomHub\hub_commands.py -Pattern '"version": \d+' -> 346: {"version": 10,…}
       git grep -n 'SCENE_VERSION = ' -- Loom/sceneio.py -> 57: SCENE_VERSION = 10
8. **影响与等级**：**P3**（卫生/可维护性；迁移路径无数据损失）。

---

### P-04-14 冻结版 Hub 里 ③ 会再拉起一个 LoomHub.exe —— **P-UNKNOWN（P3）**

**【反手 · 证伪】证伪失败（无法枚举全部路径）**

1. 判定基准：C1 的 ③ 只应"问一下当前解释器版本"，不应产生第二实例/抢焦点等外部可见副作用。
2. 代码证据：`hub_config.py:601-604` 用 `sys.executable` 起子进程；PyInstaller 下 `sys.executable` = `LoomHub.exe`（与 `default_python` 已专门处理的 frozen 分支形成对照，`653-656`）；`LoomHub.py:14-15` 单实例锁；`hub_single_instance.py:76-86` 已有实例时"激活已有窗口 + sys.exit(0)"。
3. **路径枚举（不完整）**：
   - 路径 1：源码运行 Hub（`sys.executable`=python.exe）→ ③ 的 `-c` 语法错误 → 快速失败（已实测）；
   - 路径 2：冻结版 Hub + 已有实例 → 子进程被单实例锁拦下并 exit(0)，但**会调用 `ShowWindow/BringWindowToTop/SetForegroundWindow`**（抢焦点）→ 每次启动引擎都闪一下；
   - 路径 3：冻结版 Hub + 全局 mutex 被其他用户/会话持有 → 同上；
   - 路径 4：冻结版 + 首实例尚未建 mutex（极短窗口）→ 可能真的起第二个 GUI，直到 `timeout=10` 抛 `TimeoutExpired`（被 `subprocess.SubprocessError` 捕获）。
   路径 4 需要在冻结产物上实测才能确定"是否真的会弹第二个窗口/超时多久"，本轮**禁止起阻塞 GUI**（SCAN_PROTOCOL §0.5），无法观察。
4-6. 未知。7. 建议探针（三次上限内第 1 次）：在隔离机器上装官方 `LoomHub-Setup`，用 `py -3.13` 起 `LoomHub.exe --agent`，另起一个进程把 `解释器.json.python_version` 设成不可解析值，观察 `open_project` 前后 `Get-Process LoomHub` 计数与窗口焦点变化，并记录 `resolve_python_for` 耗时。8. **判定：UNKNOWN**（缺"冻结产物 + 可观察焦点/进程表"两个条件）。

---

### P-04-15 三处版本真源与断言是否自洽 —— **P-DISPROVED（自洽）**

**【反手 · 证伪】证伪成功**

1. 判定基准：C10。
2. 代码证据：`Loom/解释器.json:3` = `0.1.0.beta6`；`LoomHub/版本.json` = `0.1.4`；`tools/installer.iss:3` `#define MyAppVersion "0.1.4"`；`test_release_version.py:83-84` 断言同值；`release_github` 缺省由真源派生（`resolve_version`）。
3. 路径枚举：(a) 缺省 → 真源；(b) 环境变量等于真源 → 通过；(c) 环境变量分叉 → SystemExit（3-10 行注释 + `140-217` 用例）；三条都由测试覆盖。
4. 预期=实际。5-7. 验证：`py -3.13 Loom\tests\test_release_version.py` → `总结果: ALL PASS ✅` `EXIT=0`。8. 判定：**DISPROVED**（版本号这条链是自洽的）。

> 但注意：该测试**不校验** `解释器.json.python_version`（`100-118` 只读 `version`），这正是 P-04-03 能溜过去的原因 → 作为修复建议 R3。

**【正手 · 证真】证真失败**：找不到"版本号分叉"的输入（环境变量分叉路径已被 `resolve_version` 拒绝）。8. 判定：**证真失败** → DISPROVED。

---

## ④ 统计

### 4.1 四象限

| 判定 | 数量 | 编号 |
|---|---|---|
| **P-PROVED** | **10** | 01,02,03,04,05,06,07,11,12,13 |
| **P-DISPROVED** | **4** | 08,09,10,15 |
| **P-UNKNOWN** | **1** | 14 |
| **P-CONTRADICTION** | **0** | — |
| 合计 | 15 | |

### 4.2 等级分布（P-PROVED 内）

| 等级 | 数量 | 编号 |
|---|---|---|
| P1（功能错误/静默失败） | 2 | 02,03 |
| P2（边界/性能/可诊断） | 5 | 01,04,05,06,07 |
| P3（可维护性/文档） | 3 | 11,12,13 |
| UNKNOWN（P3 疑似） | 1 | 14 |

### 4.3 分类别说明

- **CONTRADICTION = 0 的原因**：本轮每条疑似项都先做路径枚举；出现"证伪链声称覆盖全部路径"与"证真链构造出反例"同时成立的情况 0 次。特别复核了两处最容易自相矛盾的：P-04-09（证伪"保留"、正手"丢失"——最终发现所谓"丢失"是主动删字段的预期行为，已降级为 DISPROVED）；P-04-10（证伪"不受影响"、正手"受影响"——正手无法构造 `kind='exe'` 却带 python 的命令）。
- **P-UNKNOWN ≠ 0 的原因**：P-04-14 需要"冻结产物 + 焦点/进程可观察"两个条件，本轮只读约束 + 禁止起 GUI，无法观测；按方法论要求交人类裁决（§⑥ 问题 2）。
- **跳过留痕**：8 条（SKIP-01…08），每条给四类理由之一。
- **未兑现的"能跑就不猜"**：仅 P-04-14（明确标注原因与建议探针），其余 14 项均有可执行命令 + 实测输出。

### 4.4 对既有测试的门禁覆盖评估（A6 视角）

| 断言目标 | 现有覆盖 | 缺口 |
|---|---|---|
| 启动命令用对版本 | `test_hub_python_version.py` ②（桩掉 `resolve_python_for`） | **桩掉了整个解析器** → ①/②/③ 真实搜索顺序 0 覆盖（P-04-01 因此漏网） |
| 包内嵌入式 python 优先 | 无 | P-04-02 无门禁 |
| 元数据 python_version 与真实产物一致 | 无（`test_release_version` 不查该字段） | P-04-03 无门禁 |
| 命令层可见 note | 无 | P-04-04 无门禁 |
| 台账 refresh 保留字段 | ①（有） | ok |
| 编译版不受影响 | ⑤（有） | ok |
| "纯拼装/无副作用"契约 | 无（旧测试用无 python_version 的合成 dict，恰好绕过新路径） | P-04-06 无门禁 |

---

## ⑤ 修复建议排序（只给方向，不含代码）

| 顺序 | 对应项 | 方向（一句话） |
|---|---|---|
| **R1** | P-04-02 | 把"包内自带嵌入式解释器"放回优先级最前（命中即用、跳过版本解析），只在包内没有时才走 `resolve_python_for`；并在启动后加一条"子进程活过 N 秒/端口文件出现"的可见性判定，别再用 pythonw 把 ModuleNotFoundError 吞掉。 |
| **R2** | P-04-03 | `find_python_embed` 参数化到目标版本（跟 `解释器.json.python_version` 同源），并在打包后**校验**包内 `python/python.exe --version` 与元数据一致（不一致即拒绝出包）；同步更新 `package_engine.py:5,230` 的"3.12"文案。 |
| **R3** | P-04-03/P-04-15 | `test_release_version.py` 增加一条：`解释器.json.python_version` 的 x.y 与打包工具默认 embed 版本的 x.y 相同（源码包），与 `sys.version_info` 相同（编译包）。 |
| **R4** | P-04-01 | 去掉子进程：直接比较 `sys.version_info[:2]` 与 `xy`；若坚持子进程，把载荷改成不经 %-格式化的常量字符串，并补一条"①②人为落空仍能命中③"的测试。 |
| **R5** | P-04-07 | 缓存命中时复核 `os.path.isfile`（失效即剔除并重解析）；或把缓存做小（只在单次启动内有效）。 |
| **R6** | P-04-04/P-04-05 | `launch_engine` 把 `python_note` 带进返回体；启动文案改为"用 Python 3.13（来源：系统/包内/回退默认）"，不再写"系统默认"。 |
| **R7** | P-04-06 | 把"解析解释器"从 `build_launch_command`/`launch_spec` 的纯函数里移出（调用方先解析再传入），恢复两条契约；同时消除每次启动 4 子进程。 |
| **R8** | P-04-12 | 一次性扫掉 3.12 残留：`Loom.py:192-194`、`release_github.DEFAULT_HIGHLIGHTS:386`（"崩一次"→"同进程降级 GL"）、`release_github:433,462` 的 `or '3.12'`、README + 8 处启动示例、`run_player.py:297`；计划 §9.2 的函数名与实现对齐。 |
| **R9** | P-04-11/P-04-13 | UI 列表签名加 `python_version`；`interpreter_list` 回传该字段；Hub 两个"新建"入口共用 `sceneio.SCENE_VERSION`（D7 升 11 时只改一处）。 |
| **R10** | P-04-09(边界) | 在 `refresh_interpreters` docstring 写明"磁盘元数据缺字段 → 台账值置空（以磁盘为准）"，避免下一个人误判为丢数据。 |

---

## ⑥ 需人类裁决的封闭问题（最多 3 条，每条都可回答 A/B/C）

**Q1（P1，发布链口径）**：源码分发包（`python/ + Loom/`）的"开箱即用解释器"与"Hub 按元数据挑系统解释器"二者谁是权威？
- A：包内解释器权威（Hub 有包内 python 就用它，忽略系统）——恢复开箱即用，代价是用户的 3.13 补丁更新不会自动生效；
- B：系统解释器权威（现状）——依赖用户自备依赖，代价是 P-04-02 的静默失败；需配套"启动存活检查 + 缺依赖可见报错"；
- C：包内优先，但包内版本不满足元数据时再找系统并**出声提示**（折中，实现最复杂）。

**Q2（P-04-14 是否值得投入）**：冻结版 Hub 在"解析不到目标 Python"时，是否会因为 `sys.executable` 兜底而闪现/拉起第二个 Hub 窗口？
- A：认为单实例锁足以兜住（`hub_single_instance` 会 exit(0)），接受"每启动一次抢一次焦点"，不修；
- B：要求实测并修（③ 改为纯 `sys.version_info` 比较，零子进程）；
- C：只在 `py` 启动器与安装目录都落空时才做一次兜底并打日志（可接受一次性卡顿）。

**Q3（P-04-03 门禁强度）**：`解释器.json.python_version` 要不要升格为"发布硬门"（与 version 同级）？
- A：升格——打包后核对包内 `python -VV`，不一致直接失败（会挡住当前"元数据 3.13 / embed 3.12"的默认路径，必须先修 R2）；
- B：只加断言不加硬门（测试红但不阻断打包）；
- C：不处理，靠人工纪律（= 现状，已被证明会漂）。

---

### 附：本轮探针与运行命令清单（复跑即可得到本文所有实测输出）

    Loom/tests/_tmp/audit_b6_04_resolve.py   # §A 兜底③死分支 / §B 缓存失效 / §C 包内 python 被覆盖 / §D 子进程成本 / §E xy 归一 / §F refresh 保留
    Loom/tests/_tmp/audit_b6_04_surface.py   # §G open_project 命令与文案 / §H launch_spec 子进程 / §I launch_engine 返回体 / §J python_note 出现点
    Loom/tests/_tmp/audit_b6_04_deps.py      # 3.12 / 3.13 依赖可用性对照

> 全部探针只读生产代码 + 临时目录；收尾 `git status --porcelain` 与开工时一致（无受跟踪文件改动）。
