# LoomHub 自更新与引擎选择（编号 04）— beta5 第三轮扫描报告

> 审计对象：提交区间 71b31ac..HEAD（d994b2e）
> 审计方式：只读；粗筛 → 双向推演（先证伪再证真）→ 四象限 → 探针闭环
> 探针全部位于 `Loom/tests/_tmp/scan_beta5_04_*.py`（`Loom/.gitignore:20` 忽略 `tests/_tmp/*`）

---

## 0 范围与方法

### 0.1 diff 规模

    命令: git diff --stat 71b31ac..HEAD -- <本模块 9 个文件>
    结果:
      Loom/tests/test_hub_interp_cache.py  | 279 +++++++++++++
      Loom/tests/test_hub_interp_switch.py | 247 +++++++++++++
      Loom/tests/test_hub_update.py        | 292 +++++++++++++
      LoomHub/GUI/NovaHubGUI.py            |  45 +++-
      LoomHub/hub_commands.py              |  66 +++-
      LoomHub/hub_config.py                |  43 +++-
      LoomHub/hub_controller.py            | 207 ++++++++-
      LoomHub/hub_update.py                | 422 +++++++++++++++++++++（新文件）
      LoomHub/hub_view_tk.py               |  83 +++-
      9 files changed, 1669 insertions(+), 15 deletions(-)

附带读到的、被本模块新代码依赖的改动：`tools/installer.iss`（+24，新增 [Code] 卸载询问）、`Loom/Loom.py`（E2 auto 三态）。

### 0.2 关键函数清单（本轮新增/改动，按被审顺序）

| 文件:行 | 函数/代码 | 职责 |
|---|---|---|
| hub_update.py:42-108 | updates_dir / log_path / script_path / take_pending_failure / mark_failure_seen | 更新目录与失败可见性 |
| hub_update.py:113-154 | parse_version / is_newer / local_version | 版本比较 |
| hub_update.py:159-234 | _request / pick_release / check_update | 检查更新 |
| hub_update.py:237-257 | due_for_check / mark_checked | 24h 节流 |
| hub_update.py:270-332 | verify_download / download_update | 下载与校验 |
| hub_update.py:337-422 | build_updater_script / write_updater_script / apply_update / _shell_execute_runas | updater 脚本与提权 |
| hub_config.py:288-312 | refresh_interpreters | 重识别 + 保 default |
| hub_config.py:741-760 | hub_remote_mode / apply_launch_env | LOOM_REMOTE_MODE 唯一注入点 |
| hub_controller.py:447-504 | set_current_interp / current_interp_cached / current_interp_or_default / interp_for_project | 当前引擎缓存与项目归属 |
| hub_controller.py:506-582 | open_project(interp=…) | 四级启动优先级 |
| hub_controller.py:586-693 | check_update / download_update / apply_update / _quit_for_update / maybe_start_update_check / update_notice | 自更新编排 |
| hub_commands.py:605-654 | update_check / update_download / update_apply | EAI 命令层 |
| hub_view_tk.py:229-297,376-381 | 选为当前引擎 / 用当前引擎打开 / 远程模式开关 / 检查更新 | Tk 入口 |
| NovaHubGUI.py:297-326,387-393 | 同上（Nova 入口） | Nova 入口 |

### 0.3 跑过的命令（全部在本机实测）

    python Loom/tests/test_hub_update.py            -> 总结果: ALL PASS (RC=0)
    python Loom/tests/test_hub_interp_cache.py      -> 总结果: ALL PASS (RC=0)
    python Loom/tests/test_hub_interp_switch.py     -> 总结果: ALL PASS (RC=0)
    python Loom/tests/_tmp/scan_beta5_04_nonascii_script.py
    python Loom/tests/_tmp/scan_beta5_04_download_apply.py
    python Loom/tests/_tmp/scan_beta5_04_misc.py
    python Loom/tests/_tmp/scan_beta5_04_concurrency_paths.py
    python Loom/tests/_tmp/scan_beta5_04_interp_paths.py
    python Loom/tests/_tmp/scan_beta5_04_checks.py
    git grep -n -E "maybe_start_update_check|update_notice|download_update|apply_update\(" -- .
    git grep -n -E "/DIR=|CURRENTUSER|/LOG" -- LoomHub tools/installer.iss tools/package_hub.py   (rc=1，无命中)

### 0.4 只读自查

    git status --porcelain
     M Loom/bench_result.txt
     M docs/audit/scan_beta3_05_packaging_release.md
    ?? tools/lint_except_dist/
    ?? tools/loom_lint_except.py

这两处已修改的受跟踪文件**不是本次审计产生**（本代理未运行 bench、未写本模块以外的文件；探针只写 `Loom/tests/_tmp/` 与系统临时目录）。同工作区有并行子代理在写文件，故按"不越权回滚他人改动"处理，仅登记。

---

## 1 粗筛清单（含跳过项留痕）

### 1.1 疑似项（粗筛，不打判决）

| ID | 位置 | 标签 | 初步方向 |
|---|---|---|---|
| P-04-01 | hub_update.py:377-378 | BND-UNICODE / SEM-SILENT | 脚本用 ascii 编码写，路径含中文必炸；except 只抓 OSError |
| P-04-02 | hub_update.py:327-332 | SEM-SILENT / IFACE-PARTIAL | 校验失败不删已落盘的 exe，形成"坏包常驻" |
| P-04-03 | hub_commands.py:649-652 | SEM-MISMATCH / IFACE-UNIT | 用 sorted() 字典序代替版本比较挑"最新包" |
| P-04-04 | hub_controller.py:661,684 | AUDIT-DEADCODE | maybe_start_update_check / update_notice 无调用点 |
| P-04-05 | hub_update.py:35 + installer.iss:16,24 | IFACE-PRECOND | 永远 /ALLUSERS，安装目录不跟随当前 exe |
| P-04-06 | hub_config.py:751-760 | IFACE-PRECOND / SEM-DEFAULT | auto 不注入，而引擎 HEAD 已实现 auto |
| P-04-07 | hub_update.py:214,226-234 | SEM-MISMATCH | docstring 写"失败不抛"，pick_release 会抛 |
| P-04-08 | hub_update.py:84-96 | SEM-SILENT | 失败已读后，成功日志把 mtime 顶新 → 旧 FAIL 复现 |
| P-04-09 | hub_controller.py:497-503 | SEM-MISMATCH | 父目录匹配无 tie-break，多版本共享父目录取最旧 |
| P-04-10 | hub_update.py:356-361 | SEM-SILENT / BND-TIME | PID 等待超时后照装；脚本无任何结果上报 |
| P-04-11 | hub_update.py:56-57,300,369 | BND-CONCURRENCY | 两实例同写固定 .cmd 与固定 .part，无互斥 |
| P-04-12 | hub_config.py:290-299 | AUDIT-DOCIMPL | refresh 重建 entry，自定义键被永久丢弃 |
| P-04-13 | hub_update.py:42-65,318-332 | BND-RESOURCE | updates/ 与 update.log 无清理/轮转 |
| P-04-22 | hub_controller.py:518-521 + NovaHubGUI 文案 | AUDIT-DOCIMPL | 缓存（②）压过项目归属（③），文案却写"双击=归属引擎" |

### 1.2 跳过登记（四类可审计理由）

| 编号 | 位置 | 跳过理由（类别） | 出处 |
|---|---|---|---|
| SKIP-04-01 | hub_update.py:161-162（非 https 拒绝） | 已有回归测试覆盖 | test_hub_update.py:220-223 断言 PASS |
| SKIP-04-02 | hub_update.py:116-129（版本比较主体） | 已有回归测试覆盖 | test_hub_update.py:172-183 含 0.1.10>0.1.9，PASS |
| SKIP-04-03 | hub_update.py:270-286（verify 判据） | 已有回归测试覆盖 | test_hub_update.py:210-218 PASS |
| SKIP-04-04 | hub_update.py:73-76,256-257（log/mark 的 OSError 兜底） | 语言规范保证 | 该分支唯一预期异常即 OSError，标准库语义 |
| SKIP-04-05 | hub_config.py:296-299（保 default） | 已有回归测试覆盖 | test_hub_interp_switch.py:141-155 PASS |
| SKIP-04-06 | hub_view_tk.py:70,105（exportselection=False） | 已有回归测试覆盖（含 Tk 反射） | test_hub_interp_cache.py:225-243 PASS |
| SKIP-04-07 | installer.iss:52（[Run] skipifsilent） | 工具自身文档声明 | Inno Setup：postinstall + skipifsilent 在静默安装下不执行 → "不自动启动 LoomHub"成立 |
| SKIP-04-08 | NovaHubGUI.py:390-393（AttributeError 兜底） | 白盒契约明确声明 | 源码注释"构建早期 label 还没创建（唯一可接受的时序窗）" |

---

## 2 逐项裁决（8 段式）

### P-04-01 · 证真 · PROVED（P1）— 非 ASCII 路径下 updater 脚本编码崩溃且不写日志

1. **判定基准**
   hub_update.py:6-14 模块策略："安装：写 updates/apply_update.cmd…失败**明确报错**并写 update.log（不得静默失败）"、"失败可见：任一步失败写 updates/update.log"。write_updater_script（:369-382）自身两处 except 都返回 `{'ok': False, 'reason': …}` 并 log_line FAIL。
2. **代码证据**
   hub_update.py:377-378
       with open(p, 'w', encoding='ascii', newline='') as f:
           f.write(build_updater_script(setup_path, pid))
   hub_update.py:379  `except OSError as e:`
   hub_update.py:348  `'set "SETUP=%s"' % setup_path`  ← 脚本内容必然嵌入 setup 绝对路径
3. **路径枚举（全部逃逸出口）**
   | 路径 | 进入条件 | 结果 |
   |---|---|---|
   | L1 | setup_path 全 ASCII | 正常返回 {'ok': True}（实测脚本 615 字节） |
   | L2 | setup_path 含非 ASCII | f.write 抛 UnicodeEncodeError |
   | L2a | 调用方 catch OSError | 不匹配（实测 isinstance(e, OSError) == False）→ 逃逸 |
   | L2b | 调用方 catch Exception | hub_update.apply_update:393 无 try、HubController.apply_update:643 无 try → 一路逃逸到 hub_commands.dispatch:123 的 `except Exception`（唯一兜住处，只返回 {'error'}，不写 log） |
   路径完备：open 失败（OSError，已覆盖）、write 失败（UnicodeEncodeError，未覆盖），无其他分支。
4. **预期**：返回 {'ok': False, 'reason': …}，且 updates/update.log 出现一行 [FAIL]。
5. **实际**（探针 scan_beta5_04_nonascii_script.py）
       抛出: UnicodeEncodeError | 'ascii' codec can't encode characters in position 160-161: ordinal not in range(128)
       是否 OSError 子类: False
       脚本是否存在: True 大小: 0
       update.log 是否存在: False
6. **差异**：少了"返回 dict + 写 FAIL 日志"，多了"未捕获异常 + 0 字节 apply_update.cmd"。0 字节脚本若被后续 apply 复用，脚本里 `start "" /wait ""` 会静默什么都不做。
7. **触发条件 / 验证**
   触发：updates_dir() 或安装包路径含非 ASCII。updates_dir() = `<LOOM_USER_ROOT 或 %LOCALAPPDATA%>\Loom\hub\updates`（hub_userpaths.py:22-36,42-44），中文 Windows 用户名即命中。
   命令：`python Loom/tests/_tmp/scan_beta5_04_nonascii_script.py`（输出即第 5 段）。
8. **影响与等级**：P1。中文用户机器上自更新成功率 0，且"失败可见"契约被打破（update.log 一行都没有）。

---

### P-04-02 · 证真 · PROVED（P1）— 校验失败的安装包常驻，并被 update_apply 无差别安装

1. **判定基准**
   hub_update.py:7-8："下载：…校验 size；asset 带 digest 时校验"；download_update 的返回 {'ok': False, …} 语义是"这次下载无效"。
2. **代码证据**
   hub_update.py:318  `os.replace(tmp, dest)`   ← 先落盘
   hub_update.py:327-332
       ok, why = verify_download(dest, …)
       if not ok:
           log_line('下载校验失败: %s (%s)' % …)
           return {'ok': False, …}       ← 只 return，不删 dest
   hub_commands.py:648-653
       if not path:
           cand = [ … sorted(os.listdir(hub_update.updates_dir())) … if '.exe']
           path = cand[-1] if cand else ''
       r = hub_update.apply_update(path)
3. **路径枚举（"坏包"能否被装）**
   | 路径 | 条件 | 结果 |
   |---|---|---|
   | A | 校验失败，调用方丢弃返回值 | dest 留存（实测 True，20 字节） |
   | B | 之后 update_apply 带显式 path | 装用户指定的包（与本项无关） |
   | C | 之后 update_apply 不带 path、目录里只有坏包 | 坏包被选中 → 提权执行（实测） |
   | D | 目录里有多个 exe | cand[-1] 取"排序最后"，见 P-04-03 |
   完备性：:327-332 全段无 remove/rename，故 A 恒真。
4. **预期**：校验失败 → 该二进制不得再进入"可安装"状态（删除或改名隔离）。
5. **实际**（scan_beta5_04_download_apply.py / concurrency_paths.py）
       返回: {'ok': False, 'reason': '校验失败: 大小不符: 20 != 9', 'path': …}
       dest 是否存在: True 大小: 20
       update_apply 提交的包: LoomHub-0.1.4-Setup.exe
       该包内容: b'CORRUPT'
6. **差异**："校验失败"只对本次调用有效，对磁盘状态无效。
7. **触发条件 / 验证**：先发生一次下载校验失败（弱网/镜像/截断），后再跑 update_apply 不带 path。命令见上。
8. **影响与等级**：P1（未通过完整性校验的 exe 被提权静默安装）。

---

### P-04-03 · 证真 · PROVED（P1）— update_apply 用字典序挑"最新安装包"，0.1.9 压过 0.1.10

1. **判定基准**
   仓内版本口径是数值比较：hub_update.py:116-129；test_hub_update.py:182-183 明确锁死 0.1.10 > 0.1.9。
2. **代码证据**
   hub_commands.py:649-652：`sorted(os.listdir(...))` → `cand[-1]`（字符串排序，不是版本排序）
3. **路径枚举**
   | 路径 | 目录内容 | cand[-1] |
   |---|---|---|
   | A | 只有 0.1.4 | 0.1.4（正确） |
   | B | 0.1.9 + 0.1.10 | LoomHub-0.1.9-Setup.exe（错，取旧） |
   | C | 0.1.4 + 0.1.10 | LoomHub-0.1.4-Setup.exe（错） |
   | D | 空目录 | '' → apply_update 返回"安装包不存在"（正确失败） |
   字符串序：'…-0.1.10-…' < '…-0.1.4-…' < '…-0.1.9-…'，故 B/C 恒取旧包。
4. **预期**：取版本最大者（is_newer 口径）。
5. **实际**
       目录里 .exe: ['LoomHub-0.1.10-Setup.exe', 'LoomHub-0.1.4-Setup.exe', 'LoomHub-0.1.9-Setup.exe']
       实际提交安装的包: LoomHub-0.1.9-Setup.exe
       版本比较: is_newer(0.1.10, 0.1.9) = True
6. **差异**：同一仓库两套"最新"口径（数值 vs 字典序），挑包用的是错的那套。
7. **触发条件 / 验证**：updates/ 里同时存在 ≥2 个版本安装包（升级一次后又下载新版必然出现，因为旧包从不清理，见 P-04-13）。
8. **影响与等级**：P1（会降级更新或重装旧版；与 P-04-02 叠加时装的是坏包）。

---

### P-04-04 · 证真 · PROVED（P1）— 自动检查与失败提示两个契约未接线（GUI 无法完成一次更新）

1. **判定基准**
   hub_update.py:5-6："检查：启动后后台线程、延迟 ~10s、每 24h 最多一次"；:14 "下次启动用 take_pending_failure() 提示"。
2. **代码证据**
   hub_controller.py:661 `def maybe_start_update_check(self, delay=10.0)`、:684 `def update_notice(self)`；全仓检索（命令见 0.3）只在定义处与 docs/audit/scan_beta3_05_packaging_release.md:1427 出现，**零调用点**。同理 HubController.download_update(:615)/apply_update(:633) 在视图层无调用点：hub_view_tk.py 只新增"检查更新"按钮（:118 → :281），NovaHubGUI.py 无任何更新入口。
3. **路径枚举（用户如何完成一次更新）**
   | 入口 | 能做到哪一步 |
   |---|---|
   | 启动 | 无（无人调用 maybe_start_update_check） |
   | Tk"检查更新" | 只到 check_update，无下载/安装按钮 |
   | Nova 视图 | 连检查按钮都没有 |
   | EAI update_download / update_apply | 全流程可达 |
   | 下次启动提示 | 无（无人调用 update_notice） |
4. **预期**：启动 10s 后自动检查；发现新版本可下载可安装；上次失败下次启动有提示。
5. **实际**：三条路径中 2 条完全缺失，第 3 条只到"检查"。
6. **差异**：白盒契约 × 实现 = 部分落地且无提示。
7. **验证**：`git grep -n "maybe_start_update_check|update_notice" -- .` 只命中定义与文档。
8. **影响与等级**：P1（自更新功能整体不可用；且因 P-04-08，提示一旦接上会误报）。

---

### P-04-05 · 证真 · PROVED（P2）— 静默安装落点不跟随当前 exe，/ALLUSERS 会造出第二份安装

1. **判定基准**
   installer.iss:16 `DefaultDirName={autopf}\{#MyAppName}`；:24 `PrivilegesRequired=lowest`；:27 `PrivilegesRequiredOverridesAllowed=dialog commandline`。Inno 语义：{autopf} 在最低权限安装下解析为 ${localappdata}\Programs，在 /ALLUSERS 下解析为 Program Files；目标目录可由 /DIR 覆盖，未给则用 DefaultDirName。
2. **代码证据**
   hub_update.py:35 `SILENT_ARGS = ['/VERYSILENT','/SUPPRESSMSGBOXES','/NORESTART','/ALLUSERS','/SP-']`；全仓检索 /DIR=、CURRENTUSER、/LOG：rc=1 无命中（命令见 0.3）；hub_update.py 全文未用 `sys.executable` 推导安装目录（:143 只用于读 版本.json）。
3. **路径枚举**
   | 现状 | /ALLUSERS 后落点 | 运行中的 exe | 结果 |
   |---|---|---|---|
   | 用户级安装（%LOCALAPPDATA%\Programs\LoomHub） | Program Files\LoomHub | 仍是旧 exe | 双份安装，用户继续跑旧版 |
   | 管理员安装 + 默认目录 | Program Files\LoomHub | 同目录 | 正常覆盖 |
   | 管理员安装 + 自定义目录 | Program Files\LoomHub | 另一目录 | 双份安装，用户继续跑旧版 |
   三条里两条失败，且失败无任何日志（见 P-04-10）。
4. **预期**：升级装到"当前运行副本"所在目录（或至少 /DIR 与该目录一致）。
5. **实际**：永远装到 {autopf}\LoomHub。
6. **差异**：安装目标与"正在运行的东西"解耦。
7. **验证**：静态证据链（installer.iss:16/24/27 + hub_update.py:35 + 无 /DIR）；真机复现需一次真实静默安装（本机不跑安装器，见 U-03）。
8. **影响与等级**：P2（"看起来成功、实际没升级"）。

---

### P-04-06 · 证真 · PROVED（P2）— 设置 remote_mode=auto 与 off 等价（引擎侧 auto 已实现）

1. **判定基准**
   hub_config.py:751-752 docstring："off / auto -> **不注入**（auto 的自动降级由引擎侧 beta5 E2 实现）"；:645-646 注释"auto 留给引擎侧自动降级（beta5 的 E2 再做，Hub 侧对 auto 也不注入）"；REMOTE_MODES（:647）含 'auto' → 该值是可写入的合法配置。
2. **代码证据**
   hub_config.py:756-759
       mode = hub_remote_mode(settings)
       env.pop("LOOM_REMOTE_MODE", None)
       if mode == "on":
           env["LOOM_REMOTE_MODE"] = "1"
   引擎侧（本区间内提交 8914bf2，Loom/Loom.py:105-112）
       v = (os.environ.get('LOOM_REMOTE_MODE') or '').strip().lower()
       if v == 'auto': return 'auto'
       if v in _REMOTE_ON_VALUES: return 'on'
       return 'off'
   → 只有环境变量字面等于 'auto' 才能进 auto 分支。
3. **路径枚举**
   | Hub 设置 | 子进程 env | 引擎判读 |
   |---|---|---|
   | off | 无 | off |
   | on | '1' | on |
   | auto | 无 | **off** |
   | 非法串 | 无 | off |
4. **预期**：auto → 引擎 'auto'（先试原生、连续上屏失败再降级一次）。
5. **实际**（scan_beta5_04_misc.py 第 (d) 段，用 ast 从 Loom.py 抽出真实 _remote_mode 执行）
       Hub remote_mode=off   -> 子进程 env=None -> 引擎判读='off'
       Hub remote_mode=on    -> 子进程 env=1 -> 引擎判读='on'
       Hub remote_mode=auto  -> 子进程 env=None -> 引擎判读='off'
       Hub remote_mode=bogus -> 子进程 env=None -> 引擎判读='off'
6. **差异**：注释所依据的前提（"E2 再做"）在 HEAD 已不成立 → auto 成为"可设置但永远无效"的死选项。
7. **触发条件 / 验证**：settings_set {"remote_mode":"auto"} 后用 Hub 启动引擎。
8. **影响与等级**：P2（白屏用户选 auto 得不到兜底；默认 off 的降帧结论不受影响）。

---

### P-04-07 · 证真 · PROVED（P2）— check_update 在 200+JSON 对象体时抛 AttributeError，违背"失败不抛"

1. **判定基准** hub_update.py:214 `"""查更新。返回 {ok, update|None, reason?, local, latest?}；失败**不抛**。"""`
2. **代码证据** hub_update.py:226-234 `releases = json.loads(...)` 之后直接 `item = pick_release(releases, lv)`（无 try）；:183-184 `for rel in releases or []: tag = str(rel.get('tag_name') or '')` —— 对 dict 迭代得到的是 str 键。
3. **路径枚举**
   | 响应 | 处理 |
   |---|---|
   | 非 200 | 返回 ok=False（:220-224） |
   | 200 + 非 JSON | ValueError → ok=False（:227-230） |
   | 200 + JSON 列表 | 正常 |
   | 200 + JSON 对象（非空） | AttributeError 逃逸 |
   | 200 + JSON 空对象 {} | 迭代零次 → 正常返回 |
4. **预期**：任何响应形态都返回 dict。
5. **实际**（scan_beta5_04_misc.py (b) 段）
       抛出: AttributeError | 'str' object has no attribute 'get'
6. **差异**：缺"响应体类型校验"。
7. **触发条件 / 验证**：api.github.com 或中间代理/网关/镜像以 200 返回 ${"message": …} 形态的对象体。命令同上。
8. **影响与等级**：P2。异常被 dispatch(:123) 与 Tk 工作线程(:286-289) 兜住不会崩进程，但"静默/只写 log"契约失效，update.log 无 FAIL 行。

---

### P-04-08 · 证真 · PROVED（P2）— 失败已读之后再成功，下次启动仍提示"上次更新未完成"

1. **判定基准** hub_update.py:79-83 "读上一次失败（若有且未被提示过）"；update_notice（:684-693）渲染成"上次更新未完成：…"。
2. **代码证据** hub_update.py:87-96：以 `getmtime(log) > getmtime(seen)` 作"有未读失败"判据，然后**返回日志里最后一条 [FAIL] 行**；任何 INFO 行（如 :331 "下载完成并校验通过"）都会把 log mtime 顶新。
3. **路径枚举**
   | 序列 | take_pending_failure |
   |---|---|
   | FAIL（未读） | 返回该 FAIL |
   | FAIL → mark_seen | None |
   | FAIL → mark_seen → INFO | **返回旧 FAIL**（未读判据被 INFO 误触发） |
   | 全 INFO | None |
4. **预期**：成功之后不应再报告"上次更新未完成"。
5. **实际**（scan_beta5_04_misc.py (a) 段）
       首次提示: 2026-11-09 14:12:17 [FAIL] 下载失败: 连接中断
       已读后立刻再读: None
       成功日志之后 take_pending_failure(): 2026-11-09 14:12:17 [FAIL] 下载失败: 连接中断
6. **差异**：未读判据用"文件 mtime（任何行都刷新）"而不是"最后一次与失败相关的事件"。
7. **触发条件 / 验证**：先失败并让用户看过提示，之后同一/下一次运行里成功下载。命令同上。
8. **影响与等级**：P2（误报；当前因 P-04-04 未接线暂不影响用户，接线后立即暴露）。

---

### P-04-09 · 证真 · PROVED（P2，触发条件受限）— interp_for_project 的父目录匹配无 tie-break，多版本共享父目录时取最旧

1. **判定基准** hub_controller.py:476-479："显式 > 项目归属引擎 > 默认"，"这样'项目记得自己用哪个引擎版本'，多版本并存时不会一律拿默认引擎去开别人的项目"。
2. **代码证据** hub_controller.py:497-503：案 ② 对每个非 stale 条目比较 `normcase(abspath(dirname(it['dir']))) == want`，**命中即 return**，不看版本。
3. **路径枚举**
   | engine_dir | 命中 | 返回 |
   |---|---|---|
   | 等于 b | 案 ① | b |
   | b 的父目录（a、b 共同父） | 案 ② 首个匹配 | 台账第一条（实测 a=beta4） |
   | 无匹配 | — | 默认 c |
4. **预期**：最匹配的那个；至少确定性取版本最高者。
5. **实际**（scan_beta5_04_interp_paths.py）
       == b 的父目录 -> 选中 a (0.1.0.beta4)   ← 共享 root 时先遍历到 a 就 return
6. **差异**：歧义输入被静默解析成"列表顺序"，而 scan_install_root（hub_config.py:224）与保存顺序都是版本升序 → 系统性偏向最旧版本。
7. **触发条件 / 验证**：某项目 engine_dir 记为多版本共享的父目录（<root>/Projects/… 布局）。命令见上。
8. **影响与等级**：P2。常规布局 engine_dir 就是解释器目录（案 ① 先命中），故不升 P1。

---

### P-04-10 · 证真 · PROVED（P2）— updater 脚本对"安装结果"零上报；PID 等待超时后照装

1. **判定基准** hub_update.py:10-11："…失败**明确报错**并写 update.log（不得静默失败）"；:14 "任一步失败写 update.log"。
2. **代码证据** hub_update.py:344-365 生成的脚本只有 tasklist/find/start，**无任何日志重定向**，最后一行恒为 `exit /b 0`；:353-356 `if %n% GEQ %WAITMAX% goto install` → 超时后无条件进安装。
3. **路径枚举**
   | 情形 | 脚本行为 | update.log |
   |---|---|---|
   | 旧进程按时退出、安装成功 | 安装完 exit 0 | 无记录 |
   | 旧进程 180s 未退出 | 照常 start /wait 安装（文件占用 → Inno 静默失败） | 无记录 |
   | 安装器自身失败（磁盘满/权限/被杀） | 静默 | 无记录 |
   | UAC 被拒（Python 侧） | _shell_execute_runas 返回 False → FAIL（:399） | 有 |
   只覆盖最后一条。
4. **预期**：安装失败可判定。
5. **实际**：脚本不把任何结果写回 updates/update.log。
6. **差异**：可见性只做到"提交安装任务"，"安装是否成功"完全在观测外。
7. **验证**：`python -c "import sys;sys.path.insert(0,'LoomHub');import hub_update;print(hub_update.build_updater_script('C:/x.exe',1))"`（输出 20 行，无重定向）。
8. **影响与等级**：P2（用户以为更了其实没更，下次启动无提示；与 P-04-05 叠加时静默失败概率更高）。

---

### P-04-11 · 证真 · PROVED（P3）— 两实例并发更新：固定脚本路径与固定 .part 路径，无互斥

1. **判定基准** hub_update.py:9 "写 updates/apply_update.cmd（等当前 PID 退出…）"——脚本第一等公民是"当前 PID"，隐含一进程一脚本。
2. **代码证据** script_path()（:56-57）无 PID/时间戳；:300 `tmp = dest + '.part'` 亦无唯一化；:369-378 直接覆盖写。
3. **路径枚举**
   | 场景 | 结果 |
   |---|---|
   | A、B 同时 apply | 后写者覆盖 PID（实测 1111→2222），A 启动的 cmd 可能读到 B 的 PID |
   | A、B 同时 download 同一 asset | 同 .part 双写 → 内容可能交错；两个 os.replace 后最终包来自最后一次 |
   | 单实例 | 正常 |
4. **预期**：一进程一脚本/临时文件，或加锁。
5. **实际**（scan_beta5_04_concurrency_paths.py (i) 段）
       实例A 写入 PID: ['set "PID=1111"']
       实例B 覆盖后 PID: ['set "PID=2222"']
       同一路径: …\hub\updates\apply_update.cmd | 覆盖后内容与A相同: False
6. **差异**：进程级状态被放进全局单例文件。
7. **触发条件**：同时开两个 LoomHub 并在两边提交更新。
8. **影响与等级**：P3（size/digest 兜底仍在，最坏是"一个实例装了、另一个等错 PID"）。

---

### P-04-12 · 证真 · PROVED（P3）— refresh_interpreters 首次刷新永久丢弃非标准键

1. **判定基准** hub_config.py:276-283 只声明"重新识别…按现状重写 kind/main"、"失效条目保留但标记"，未声明丢弃其他键。
2. **代码证据** :290-299：成功分支 `info = discover_interpreter(d)` 后 `out.append(info)`；discover_interpreter 返回键固定为 name/version/kind/dir/main/path/main_py/main_exe（:207-209），旧条目其他键不经 dict 合并。
3. **路径枚举**
   | 旧条目含 | 刷新后 |
   |---|---|
   | default | 保留（:296-297，本轮修复） |
   | stale | 清除（重建） |
   | 任意自定义键（note/added_by/source…） | **丢弃并落盘** |
   | 目录缺失 | 走 else，整个 dict 原样保留 |
4. **预期**：不静默丢字段（或文档声明白名单）。
5. **实际**（scan_beta5_04_misc.py (c) 段）
       刷新前条目0的键: ['added_by','default','dir','kind','main','main_exe','main_py','name','note','path','version']
       第1次刷新键: ['dir','kind','main','main_exe','main_py','name','path','version']   ← note/added_by 消失
6. **差异**：数据丢失无声（无 print、无备份）。
7. **触发条件**：任何曾向台账写入非 discover 键的版本/工具。
8. **影响与等级**：P3。当前仓内无该键读者（读者只用 name/version/kind/dir/main/path/main_py/main_exe/default/stale），**今天不造成功能错误**，但它是 P-04-01 同类"键被重建吞掉"的根因面。

---

### P-04-13 · 证真 · PROVED（P3）— updates/ 与 update.log 无清理/轮转

1. **判定基准** hub_update.py:42-44 只声明"放安装包、updater 脚本与日志"，无保留策略。
2. **代码证据** 全模块除 :321-322（下载失败删 .part）外无 os.remove；无日志截断。
3. **路径枚举** 每次更新成功 → 新增一个 `LoomHub-<ver>-Setup.exe`（数十 MB），apply_update.cmd 被覆盖；update.log 只追加。
4. **预期**：安装成功后删本次包，或日志按大小轮转。
5. **实际**：只增不减。
6. **差异**：长期使用后单调增长。
7. **验证**：`git grep -n "remove\|truncate\|rotate" -- LoomHub/hub_update.py` 只命中 .part 清理。
8. **影响与等级**：P3（也是 P-04-03 多包并存的成因）。

---

### P-04-22 · 证真 · PROVED（P2 / [REGRESSION] AUDIT-DOCIMPL）— 选过「当前引擎」后，双击项目的实际行为与 UI 文案相反

1. **判定基准**
   NovaHubGUI.py 本轮改写的提示文案（diff 中 `_note` 行）："双击项目 = 归属引擎(不明则默认)；「用当前引擎打开」= 左侧选定的当前引擎 (--open)"；test_hub_interp_cache.py:11-13 也把口径写成"① 缓存 / ② 回退 project.engine_dir / ③ 回退默认"。
2. **代码证据**
   hub_controller.py:518-521
       if interp is None:
           interp = self.current_interp_cached()      # ②
       if interp is None:
           interp = self.interp_for_project(project)  # ③ + ④
   → 缓存（②）排在项目归属（③）之前，且缓存是全局内存、跨项目、跨视图持续有效。
3. **路径枚举**
   | 状态 | 双击项目（interp=None）实际用的引擎 | 文案承诺 |
   |---|---|---|
   | 从未点过「选为当前引擎」 | 项目归属 → 默认（与文案一致） | 归属 |
   | 点过「选为当前引擎」= X | **X（压过归属）** | 归属 |
   | 缓存条目变 stale | 归属 → 默认 | 归属 |
   前两条已由 test_hub_interp_cache.py:181-184 显式断言（"有缓存时用缓存引擎 b（压过 project.engine_dir=a）"）。
4. **预期**：文案与行为一致（要么文案写"缓存优先"，要么双击路径显式传 interp=None 时不看缓存）。
5. **实际**：文案说归属，行为是缓存优先；同一份功能有两个互相矛盾的对外解释。
6. **差异**：本轮把"两个 Listbox 不能同时选中"改成"全局当前引擎"后，缓存变成了隐式默认值，但文案仍按旧语义写。
7. **验证**：`python Loom/tests/test_hub_interp_cache.py` → ② 组 PASS（断言缓存压过 engine_dir）；文案见 `git diff 71b31ac..HEAD -- LoomHub/GUI/NovaHubGUI.py` 的 `_note` 行。
8. **影响与等级**：P2。用户在多引擎并存的机器上会"莫名其妙用错版本打开项目"，且 UI 解释与行为不符（最容易被当成引擎 bug 排查）。

---
### 2.x 已证伪清单（DISPROVED，含路径枚举）

#### P-04-14 · DISPROVED — apply_launch_env 会漏进父进程残留的 LOOM_REMOTE_MODE
1 基准：hub_config.py:753-755 "也保证环境里残留的值不会漏进子进程（先 pop 再按设置决定）"。
2 证据：hub_config.py:757 `env.pop("LOOM_REMOTE_MODE", None)` 在赋值前无条件执行，函数只此 4 行。
3 路径枚举：(a) 父 env '1' + off → pop 后不写 → 无键；(b) 父 env '1' + on → pop 后写 '1'（值正确）；(c) 父 env 无 + off/on；(d) 父 env 垃圾值 + 任意设置。四条全部经 pop，无第三条出口。
4-6 预期=实际：test_hub_update.py:160-167 实测 PASS（"环境残留 LOOM_REMOTE_MODE 会被清掉"）。
7 验证：`python Loom/tests/test_hub_update.py` → PASS。
8 等级：无。

#### P-04-15 · DISPROVED — refresh_interpreters 反复刷新会无限增长或残留 stale
1 基准：:302 "重新识别成功即'新鲜'：旧条目的 stale 标记随之清除"；:304 `changed = out != old`。
3 路径枚举：(a) 全新鲜 → out==old，不写盘（幂等）；(b) 含 stale → keep=dict(it) 加 stale，第二次刷新 out==old；(c) 目录回来 → 重建条目，stale 消失。无累加型写入。
5 实际（(c) 段）：连续 3 次刷新 条目数=2、键集恒定、default=[None, True]、stale=[None,None]。
8 等级：无。

#### P-04-16 · DISPROVED — 本轮"保 default"修复无效或引入新翻转
1 基准：hub_config.py:296-297 `if it.get('default'): info['default'] = True`。
3 路径枚举：(a) default=True 且目录有效 → 保留；(b) default=True 且目录失效 → 走 else，dict 原样保留（也保 default）；(c) 无 default 键 → 不写（不造 $default: False 噪音）；(d) 非法真值（如 'yes'）→ 保留为 True。
5 实际：test_hub_interp_switch.py:141-155 PASS；本代理 3 次刷新后 default 仍在 b。
8 等级：无。**残留说明（非本轮引入）**：★ 所在目录失效后 default_interpreter() 仍返回该 stale 条目 → 打开项目得到"解释器已失效"而不是回退另一个可用引擎；基线 71b31ac 的 else 分支同样保留 default（`git show 71b31ac:LoomHub/hub_config.py`），故属既有问题，登记不计入本轮。

#### P-04-17 · DISPROVED — current_interp 缓存在条目移除/失效后仍返回幽灵引擎
1 基准：hub_controller.py:458-469 "仍登记且未失效才返回；否则 None 不回落默认"；:72-74 清除。
3 路径枚举：(a) 条目被移除 → 遍历不到 → None；(b) 目录删除/元数据丢失 → stale → :465 跳过 → None；(c) 引擎原地替换（kind 变）→ 命中并返回**新**条目（:468 用台账最新信息）；(d) 缓存 dir 为空 → `abspath('')==cwd` 的退化比较（见第 4 节 13）。
5 实际（concurrency_paths.py (ii)）：设置后命中 beta4 → 删元数据 → refresh → current_interp_cached()=None、current_interp=None、current_interp_or_default()=beta5。
8 等级：无。

#### P-04-18 · DISPROVED — interp_for_project 路径比较在大小写/尾斜杠/.. 上误配
1 基准：hub_controller.py:484,494,502 三处均 `normcase(abspath(...))`。
3 路径枚举（判别探针：默认引擎设为第三个 c，以区分"命中"与"回退"）：b 精确 / b 全大写 / b 尾斜杠 / b/../b / normcase(b) → 5 条全部命中 b；''、相对路径、b/Projects → 回退默认 c（属文档口径：engine_dir 必须是引擎根）。
5 实际：scan_beta5_04_interp_paths.py 输出（见 P-04-09 表）。
8 等级：无（唯一缺陷是 P-04-09 的父目录歧义）。

#### P-04-19 · DISPROVED — 版本比较在 0.1.10/0.1.9、预发布、非法串上出错
1 基准：hub_update.py:117 "只支持 x.y.z，Hub 版本口径"；:125 "任一不合法返回 False（宁可不提示，也不误提示）"。
3/5 实测（scan_beta5_04_checks.py）：
       is_newer('0.1.10','0.1.9') = True
       is_newer('0.1.9','0.1.10') = False
       is_newer('0.1.4-beta1','0.1.3') = False
       is_newer('v0.1.4','0.1.3') = True
       is_newer('0.1.4 ','0.1.3') = True
       is_newer('01.02.03','1.2.3') = False
       is_newer('0.1.4','0.1.3.beta5') = False
       is_newer('','0.1.3') = False
8 等级：无。**须记录的风险**：若 Hub 版本号将来采用 x.y.z.betaN（与引擎同款），本地版本解析为 None → 自更新永久静默失效（当前 版本.json=0.1.3，暂不触发）。

#### P-04-20 · DISPROVED — 无网/404/asset 缺失会抛或误报
1 基准：:221-230（非 200 静默 + WARN；JSON 解析失败静默）；:196-197（无对应 asset → 跳过）。
5 实测：404 → ${'ok': False, 'reason': '网络/接口不可用 (status=404)'…}；有 tag 无 asset → ${'ok': True, 'update': None, 'latest': '0.1.3'}；asset 无 size/digest → 仍返回 update 项（size=0）。均不抛。
8 等级：无。**须记录的边界**：verify_download 在 size=0 且 digest='' 时退化为"只要求非空"（实测任意 HTML 内容 → (True,'')）；GitHub 侧永远带 size，但 `update_download {url,name}` 这条命令式入口可以不带 size/digest → 任意 https 内容都会被当合格安装包（见 Q3）。

#### P-04-21 · DISPROVED — 安装器会自动启动 LoomHub
1 基准：hub_update.py:13 "不自动启动：静默安装不跑 postinstall；updater 脚本里也没有启动 LoomHub 的命令"。
2/3 证据：installer.iss:52 `Flags: nowait postinstall skipifsilent`（Inno 文档：静默安装下 skipifsilent 抑制该 [Run] 项）；build_updater_script 全量 20 行无任何 LoomHub 启动语句；test_hub_update.py:238-240 PASS。
8 等级：无。

---

## 3 统计

| 判定 | 数量 | 编号 |
|---|---|---|
| P-PROVED | 14 | P-04-01 … P-04-13、P-04-22 |
| P-DISPROVED | 8 | P-04-14 … P-04-21 |
| P-UNKNOWN | 3 | U-01 … U-03（下） |
| P-CONTRADICTION | 0 | 无双边同时成立的项（P-04-06 的"Hub 注释说留给引擎 / 引擎已实现"按"注释前提失效"定性为 SEM-MISMATCH，两条链不矛盾） |

P-UNKNOWN 明细（不为 0）：

- **U-01** 非 ASCII 用户目录的真实发生率。已证"代码在此输入下必然崩溃"，未证"目标用户群普遍命中"（本机 %LOCALAPPDATA% 为纯 ASCII）。需要信息：至少一台中文用户名机器的 %LOCALAPPDATA% 实际取值。下一步探针：在中文用户名机器上跑 `python -c "import sys;sys.path.insert(0,'LoomHub');import hub_update;print(hub_update.updates_dir())"`。
- **U-02** P-04-02/P-04-03 组合链的影响面。当前 GUI 无下载/安装按钮（P-04-04），故组合链只能经 EAI 命令层触发；是否保留该路径取决于 Q2 裁决。需要信息：GUI 是否要接"下载并安装"。
- **U-03** P-04-05 的真实后果（是否真的产生双份安装）。需要一台"按最低权限装过 0.1.3"的机器 + 一次真实静默安装（本机不启动安装器，协议 §0.5）。下一步探针：沙箱机跑 apply_update 后分别用 `where /r "%LOCALAPPDATA%" LoomHub.exe` 与 Program Files 各查一次。

---

## 4 修复建议排序（只给方向，不含代码）

**P1（先修，阻断自更新可用性/安全性）**

1. P-04-01：脚本落盘改为"按需编码 + 编码失败归入可见失败"——写脚本前把非 ASCII 当必须处理的输入（转 8.3 短路径、改 Unicode 友好载体、或把 SETUP 路径写进独立 UTF-8 配置由脚本读取），确保 UnicodeEncodeError 与 OSError 走同一条"返回 dict + 写 FAIL 日志"出口，并清理半成品脚本。
2. P-04-02 + P-04-03 + P-04-13：把"可安装包"变成显式状态——校验失败即删除或改名隔离；挑包改走 is_newer 而非字符串排序；安装成功后清理本次包。
3. P-04-04：给 maybe_start_update_check / update_notice 接线（启动 10s 后 + 窗口绘就后各一次），两个视图补"下载并安装"入口（或在检查成功提示里给出可执行动作）。

**P2**

4. P-04-05：明确"升级落点"——传 /DIR 指向当前 exe 所在目录，或按当前安装形态决定是否传 /ALLUSERS；不可判定时才回退默认并记录。
5. P-04-10：updater 脚本补结果上报（安装器 /LOG + 脚本把退出码追加到 update.log）；PID 等待超时单独记 WARN。
6. P-04-06：二选一——Hub 对 auto 注入 LOOM_REMOTE_MODE=auto（引擎 HEAD 已支持），或从 REMOTE_MODES/设置面移除 auto；同时更新 :751 的过期注释。
7. P-04-07：pick_release 入口做响应体类型校验（非 list → 当失败处理）。
8. P-04-08：未读判据改为"最后一次成功/失败事件"而不是 log mtime。
9. P-04-09：父目录匹配加 tie-break（版本最高者），或只保留案 ①（精确目录）并对案 ② 打一次性提示。

**P3**

10. P-04-11：脚本与 .part 名带 PID/时间戳，或对 updates/ 加进程内锁。
11. P-04-12：刷新时合并旧条目白名单外键（或显式打印丢弃键清单）。
12. P-04-13：update.log 按大小轮转。
13. current_interp_cached 对空 dir 早退（避免 abspath('') 退化到 cwd 比较）。
14. 版本口径守卫：若 Hub 将来采用 beta 后缀，parse_version 需与 _version_key（hub_config.py:132-151）统一。

---

## 5 需要人类裁决的封闭问题

**Q1（P-04-05 / 安装落点）**：自更新应"永远装到 Program Files（需 UAC，允许与用户级副本并存）"，还是"装到当前运行副本所在目录（不产生第二份）"？
- 选 A（保持 /ALLUSERS）：代价 = 用户级安装的副本永远升不上去，需额外提示"请手动卸载旧副本"。
- 选 B（按 sys.executable 目录传 /DIR）：代价 = 自定义/被移动过的安装需要额外校验，且非 Program Files 目录下静默安装可能不需提权，需重新定义"何时弹 UAC"。

**Q2（P-04-04 / 自更新入口）**：GUI 是否必须提供"下载并安装"按钮（含进度与失败提示），还是保持"GUI 只检查、安装只走 EAI 命令层"？
- 选 A（GUI 全流程）：代价 = 新增 2 个按钮 + 进度/取消 + 失败对话框，且必须先把 P-04-01/-02/-10 修完，否则按钮等于把静默失败暴露给用户。
- 选 B（维持命令层）：代价 = "自更新"对普通用户不可用，等于只有 Agent 能升级 Hub。

**Q3（P-04-20 边界 / update_download 的校验下限）**：调用方未提供 size 与 digest 时（update_download {url,name}），是否允许下载并落盘？
- 选 A（拒绝）：代价 = 手工/镜像下载路径不可用，但杜绝"任意 https 内容被当安装包再提权执行"。
- 选 B（允许但打"未校验"标记，apply 时二次确认）：代价 = 多一个状态位与一次交互。
- 选 C（保持现状）：代价 = 依赖调用方自律，EAI 命令层成为可提权执行任意 exe 的通道。

**Q4（P-04-06 / auto 的归属）**：remote_mode=auto 由 Hub 注入 LOOM_REMOTE_MODE=auto 交给引擎（E2 已实现），还是从 Hub 设置面移除 auto（只留 on/off）？
- 选 A（注入）：代价 = 引入"引擎自动重启一次"的新路径，Hub 侧需能解释这次重启。
- 选 B（移除）：代价 = 白屏机器失去自动兜底，需用户手动勾选。

---

*本报告按 A6 标准写就：每条结论含 8 段式链（含路径枚举）、可执行命令与实测输出；跳过项留痕；P-UNKNOWN 不为 0 并写明"还缺什么信息"；全部结论可用 `Loom/tests/_tmp/scan_beta5_04_*.py` 复现。未修改任何受跟踪文件。*
