# 打包与发布链 扫描报告（beta3_scan_05）

> 审计对象：上一轮 Agent 对 beta3 内测版的打包/发布链修补（git 区间 f53a82a..HEAD，29 提交）
> 方法论：「论如何正确的vibe coding.md」+「论如何使用AI自动化工具正确的判断AI给出的黑盒是否符合设计标准.md」+ docs/audit/SCAN_PROTOCOL.md
> 本轮只读：未修改任何受跟踪文件；只新建了本报告与 Loom/tests/_tmp/beta3_scan_05_*.py 探针（探针全部被 Loom/.gitignore:20 的 tests/_tmp/* 忽略）
> 判定基准一律引用"被审对象自身白盒契约"（代码注释 / docstring / docs/handoff / 本仓库既有测试），不混用外部标准。

---

## 0. 范围与方法

### 0.1 被审文件（本子代理负责的模块）

| 文件 | 行数 | 本轮 diff | 说明 |
|---|---|---|---|
| Loom/build_game.py | 244 | +25 行 | 游戏构建器；_resolve_runtime、_build_runtime |
| tools/package_engine.py | 231 | +53 行 | 引擎 zip 打包器；预置运行时 + 版本回写 |
| tools/release_github.py | 284 | +72 行 | GitHub Release 自动化发布 |
| tools/installer.iss | 44 | 1 行 | Inno Setup 定义（package_hub 的生成物） |
| LoomHub/hub_config.py | 469 | +5 行 | build_launch_command 追加 --agent |
| LoomHub/interpreters.json | 14 | -20 行 | 解释器台账 |
| Loom/.gitignore | 50 | +5 行 | 忽略 player_runtime / 例外放行 e2e 脚本 |

为判定"接口另一侧"的契约，只读旁证（不在本模块修改范围，仅作判定基准）：
tools/package_hub.py(182)、LoomHub/hub_install.py(211)、LoomHub/hub_commands.py(730)、
LoomHub/hub_controller.py(539)、LoomHub/hub_github.py(389)、Loom/解释器.json(8)、
Loom/plugin_loader.py:66、Loom/tests/test_hub.py。

### 0.2 判定基准清单（白盒契约，后续只能引这些）

| 编号 | 契约原文 | 出处 |
|---|---|---|
| C1 | "这里把请求的 version 写回包内元数据，保证文件名/元数据/安装目录三者一致" | tools/package_engine.py:180-182（本轮新注释） |
| C2 | "预置播放器运行时…之后 build_game.py 直接复用 -> 游戏开发机零编译器" | tools/package_engine.py:152-156 |
| C3 | "新增：把 Loom/player_runtime/game_player.dist 拷进 zip，并写 运行时.json（版本/构建时间）" | docs/handoff/接手总纲_20261107_引擎发布与游戏打包.md:51 |
| C4 | "建议后续：给 player_runtime 写源码哈希，build_game 检测到不匹配时告警"（即：目前没有版本戳机制） | 同上:197-198 |
| C5 | "_resolve_runtime 之前返回 player_runtime（exe 被多套一层 game_player.dist/），改为优先返回 dist" | 同上:56 |
| C6 | "缺少玩家运行时 (player_runtime/game_player.dist)。… 给出明确指引" | Loom/build_game.py:77-80 |
| C7 | build_launch_command 的 mode 语义："'open' = 编辑器打开项目场景 / 'run' = 播放场景 / None = 纯启动编辑器" | LoomHub/hub_config.py:444-446 |
| C8 | "编辑器模式追加 --agent —— 否则 LoomHub 打开的编辑器没有 EAI 命令桥…与'打开引擎后 Agent 接上'的设计目标不符" | LoomHub/hub_config.py:464-466（本轮新注释） |
| C9 | "版本号格式白名单…发版自检（打 zip 前）与导入/扫描（discover_interpreter）共用同一判据——两边平行线唯一接缝" | LoomHub/hub_config.py:107-112 |
| C10 | "版本号须为 x.y.z 或 x.y.z.betaN 格式" | hub_config.py:122-123；hub_install.py:116-117 |
| C11 | "安装版本 = zip 元数据里的 version（None = 从 zip 元数据自动读）" | hub_controller.py:142-173 |
| C12 | "在线安装版本 = release tag 去掉 engine-v 前缀" | hub_github.py:179；hub_commands.py:292-295,322 |
| C13 | 台账 interpreters.json 是"已登记的解释器列表"，可由 scan_install_root（扫 C:\Program Files\Loom）重建 | hub_config.py:10,158-171；hub_controller.py:102-111 |
| C14 | _req 的失败语义：HTTP 错误 → (code, body)；其它异常 → (0, 字符串) | release_github.py:65-71 |
| C15 | "上传大文件超时已放宽到 7200s；如果 tag 已存在远端会 push 失败（用 git push -f 校正）" | docs/handoff/接手总纲.md:149 |
| C16 | 版本参数化："set LOOM_ENGINE_VERSION=0.1.0.beta3 / set LOOM_HUB_VERSION=0.1.1"（三处必须一致） | 同上:143-147 |
| C17 | package_engine --version 缺省读 Loom/解释器.json | tools/package_engine.py:29-33,217 |

### 0.3 跑过的东西（全部实跑，原始输出见 §2 各条"7) 验证"）

    cd "D:\my-project - 副本\Loom(py源代码-工作区)"
    git log --oneline f53a82a..HEAD                     # 29 提交
    git diff f53a82a..HEAD -- <本模块 7 个文件>
    git show f53a82a:"Loom/build_game.py"               # 基线 _resolve_runtime
    git show f53a82a:"Loom/解释器.json"                  # 基线元数据 = 0.1.0.beta2
    cd Loom; python tests/test_hub.py                   # 3 FAIL / exit 1   <- P-05-01 实证
    cd Loom; python tests/test_hub_eai.py               # ALL PASS
    cd Loom; python tests/test_hub_controller.py        # ALL PASS
    python Loom\tests\_tmp\beta3_scan_05_launch.py      # 启动命令矩阵
    python Loom\tests\_tmp\beta3_scan_05_pack.py        # 收集/排除/元数据校验
    python Loom\tests\_tmp\beta3_scan_05_zip.py         # 已发布 zip 的真实内容
    python Loom\tests\_tmp\beta3_scan_05_makezip.py     # make_zip 三态（有/无运行时、坏元数据）
    python Loom\tests\_tmp\beta3_scan_05_runtime.py     # _resolve_runtime 六种布局
    python Loom\tests\_tmp\beta3_scan_05_release.py     # 本地假 GitHub API 的发布/重试幂等
    python Loom\tests\_tmp\beta3_scan_05_instver.py     # tag 版本 vs 包内元数据版本
    python Loom\tests\_tmp\beta3_scan_05_zipdiff.py     # 两个 zip 的包体归因（按顶层目录）
    python -c "…wgpu wheel RECORD…"                     # wgpu 资源是否随 wheel 分发
    git check-ignore -v <4 条路径>                       # .gitignore 生效性
    git status --porcelain                              # 工作树自查

环境：Windows + Python 3.12.10 + 仓库 HEAD。

### 0.4 探针清单（一次性，不被产品代码 import）

| 探针 | 用途 | 是否入库 |
|---|---|---|
| Loom/tests/_tmp/beta3_scan_05_launch.py | build_launch_command 八种入参矩阵 | 否（gitignored） |
| Loom/tests/_tmp/beta3_scan_05_pack.py | collect_files 实收集清单 / load_version / validate_meta | 否 |
| Loom/tests/_tmp/beta3_scan_05_zip.py | 已发布 beta2/beta3/beta4 zip 的内部元数据与构成 | 否 |
| Loom/tests/_tmp/beta3_scan_05_makezip.py | make_zip 三态实跑（临时假引擎树） | 否 |
| Loom/tests/_tmp/beta3_scan_05_runtime.py | _resolve_runtime 六种目录布局 | 否 |
| Loom/tests/_tmp/beta3_scan_05_release.py | 本地假 GitHub API（127.0.0.1）验证发布幂等性；不联网、不执行 git 写操作 | 否 |
| Loom/tests/_tmp/beta3_scan_05_instver.py | install_from_zip 在版本不一致/非法时的真实行为（全临时目录 + 临时台账） | 否 |
| Loom/tests/_tmp/beta3_scan_05_zipdiff.py | 两个已发布 zip 按顶层目录的未压缩体积对比（包体归因） | 否 |

### 0.5 工作树自查

    $ git status --porcelain
    ?? tools/lint_except_dist/
    ?? tools/loom_lint_except.py

这两个未跟踪项是交接说明里点名的既有残留（非本次扫描造成，未触碰）。本报告与 7 个探针均未被 git 跟踪
（git check-ignore -v Loom/tests/_tmp/beta3_scan_05_pack.py → Loom/.gitignore:20:tests/_tmp/*）。
本轮没有任何受跟踪文件被修改，无"曾误改需还原"事项。

### 0.6 [REGRESSION] 标记口径

本报告 [REGRESSION] = 本轮 diff（f53a82a..HEAD）引入，含两种情形：(a) 既有代码行为被改变并产生风险；
(b) 本轮新增代码自带缺陷。每条附 git diff 片段或"基线 vs HEAD"对照。

---

## 1. 粗筛清单（含跳过项留痕）

### 1.1 疑似项（23 项）

| ID | 位置 | 标签 | 初步方向（指向具体代码事实） |
|---|---|---|---|
| P-05-01 | LoomHub/hub_config.py:467-468 | AUDIT-ASYMMETRY / IFACE-CONTRACT | 追加 --agent 改的是被既有回归测试精确断言列表的函数；Loom/tests/test_hub.py:310-320 有 3 条 == 断言 |
| P-05-02 | LoomHub/hub_config.py:444-446,467 | SEM-MISMATCH / AUDIT-ASYMMETRY | C7 把 mode=None 定义为"纯启动编辑器"，但 --agent 只在 mode == 'open' 时追加 |
| P-05-03 | hub_commands.py:482-483 + hub_config.py:467 | AUDIT-ASYMMETRY | 命令层 as_bool(agent) 再追加一次，叠加后出现两个 --agent |
| P-05-04 | tools/package_engine.py:159-175 | SEM-SILENT | 缺 player_runtime/game_player.dist 只 print 警告；make_zip 正常返回、main() 无 sys.exit |
| P-05-05 | tools/package_engine.py:183-192 | SEM-SILENT | 元数据回写 except Exception 后继续打 zip，产物对 LoomHub 不可安装 |
| P-05-06 | tools/package_engine.py:187,217 | IFACE-VERSION / SEM-OVERFIT | --version 原样写进元数据，未过 C10 白名单；C9 声称"发版自检"存在但 producer 侧无此检查 |
| P-05-07 | release_github.py:17-18 vs package_engine.py:29-33 | IFACE-VERSION / DESIGN-DRIFT | 发布工具默认 0.1.0.beta3，打包工具缺省版本来自 Loom/解释器.json = 0.1.0.beta2 |
| P-05-08 | release_github.py:138-140,145-150,155-161 | SEM-SILENT / AUDIT-DEADCODE | 上传失败后重跑在 create_release 422 处硬退；"删同名 asset"分支在新建 release 上永不命中 |
| P-05-09 | release_github.py:236-241 vs hub_github.py:179 / hub_controller.py:169 | IFACE-VERSION | tag 版本进入安装目录名，包内元数据版本进入台账，两者无一致性校验 |
| P-05-10 | Loom/build_game.py:69-76 | SEM-SILENT / IFACE-PRECOND | 默认运行时目录存在但缺 game_player.dist/MyGame.exe 时静默返回该目录（不是 dist，也不报错） |
| P-05-11 | Loom/build_game.py:62-68 | AUDIT-ASYMMETRY | --runtime 分支不做"下钻一层"归一化，与默认分支语义不等价（C5 声称已消除多套一层） |
| P-05-12 | package_engine.py:164-172 | AUDIT-DOCIMPL / SEM-DEFAULT | 运行时.json.version 来自打包参数、built_at 为打包时刻；仓库内无任何消费者（grep 实证） |
| P-05-13 | Loom/解释器.json:3 + package_engine.py:29-33 | DESIGN-DRIFT | 工具链从不更新源码元数据，"版本单一事实源"不存在（C16 要求三处手抄一致） |
| P-05-14 | tools/installer.iss:1-3 vs package_hub.py:23-31 / LoomHub/版本.json:2 | AUDIT-DOCIMPL / DESIGN-DRIFT | iss 自称"自动生成"却被入库；--version 只回写 iss，不回写 版本.json（0.1.0 vs iss 0.1.1） |
| P-05-15 | release_github.py:15 | AUDIT-DEADCODE | USER_AGENT = 'LoomHub-Release/0.1.0' 未参数化，与 C16 的参数化范围不一致 |
| P-05-16 | release_github.py:153-157 | BND-RESOURCE | 上传前 f.read() 整包入内存（332 MB），7200s 超时下内存峰值未评估 |
| P-05-17 | Loom/.gitignore:49 vs :50 | AUDIT-DEADCODE | Loom/player_runtime/ 写在 Loom/.gitignore 里指向 Loom/Loom/player_runtime/，实际由第 50 行兜住 |
| P-05-18 | package_engine.py:23-24 + 实测收集表 | TOOL-SCOPE | %SystemDrive%/…SogouInput/*.bin、压测500混合.json、_cacert.pem、AI工作排查笔记/ 等无关文件入包 |
| P-05-19 | Loom/build_game.py:89,96-104 | TOOL-CLI / OVERFIT-HARDCODE | --include-package-data=wgpu_native 指向不存在的包；DLL 用 import wgpu 推导绝对路径 |
| P-05-20 | LoomHub/interpreters.json:1-14 | IFACE-PRECOND | 删掉 beta1/beta2 条目是否破坏安装/卸载台账 |
| P-05-21 | release_github.py:178-228 | SEM-OVERFIT | 发布说明改用 {version} + .format()，模板若含其它花括号会 KeyError |
| P-05-22 | release_github.py:35-51,74-94 | TOOL-HEURISTIC | token 取自 git credential fill，不校验账号是否等于 REPO_OWNER |
| P-05-23 | package_engine.py:23-24,157-175 | BND-RESOURCE | 预置运行时 + 排除规则是否导致"包体暴涨 / 漏排除大文件" |

### 1.2 跳过登记（8 项，四类可审计理由）

| 编号 | 位置 | 跳过理由（四类之一 + 出处） |
|---|---|---|
| SKIP-05-01 | package_engine.py:68-95 build_embed_pyzip（pip install / copytree） | 无 diff（git diff 无该 hunk）+ 语言规范保证；真实校验需联网 pip，超本轮可复现边界 |
| SKIP-05-02 | package_engine.py:98-111 write_launcher | 无 diff；纯 ASCII 字面量写入，open(..., 'ascii') 不会抛（语言规范保证） |
| SKIP-05-03 | package_engine.py:139-151 复制循环 + 199-209 写 zip/清理 | 无 diff；shutil.copy2 / zipfile.ZipFile 语义由标准库文档保证（语言规范保证）；产物已在 P-05-23 用真实 zip 复核 |
| SKIP-05-04 | Loom/build_game.py:113-141 argparse 段 | 无 diff；参数定义与 help 文本一致，属已有回归测试覆盖（Loom/tests 打包相关用例 + docs 记录的手工验收） |
| SKIP-05-05 | Loom/build_game.py:178-190 第 5 步拷贝循环 | 无 diff；shutil 语义由标准库保证（语言规范保证）；我在探针里复刻同一循环观察布局，不改产品代码 |
| SKIP-05-06 | tools/installer.iss:8-44 除版本号外全部段落 | 无 diff（仅 MyAppVersion 一行变动）；AppId/[Files]/[Run] 属 Inno Setup 自身声明（工具框架自身声明） |
| SKIP-05-07 | LoomHub/interpreters.json 的 JSON 语法（无末尾换行） | 语言规范保证：JSON 允许文件末尾无换行；json.load 实测可读（探针 pack.py 与 hub_config.load_json 一致） |
| SKIP-05-08 | release_github.py 的 HTTPS/urllib 协议细节（分块、证书） | 工具框架自身声明：urllib 行为由标准库文档保证；C14 只约束返回元组形状，我按 C14 判定（见 P-05-08） |

---

## 2. 逐项裁决
### 2.1 P-05-01 · build_launch_command 追加 --agent 打破既有回归测试 3 条断言 [P-PROVED / P1 / REGRESSION]

**反手（证伪：证明"这里没有 bug"）**

1. 判定基准：C8 明确要求"编辑器模式追加 --agent"，所以"命令里出现 --agent"本身是预期行为，不是缺陷；
   若测试失败只是"测试过时"，缺陷等级应是 P3（可维护性）而不是 P1。
2. 代码证据（原样引用）：

       LoomHub/hub_config.py:462-468
           if scene_path:
               cmd += ['--open' if mode == 'open' else '--run', scene_path]
           # 2026-11-07 修复: 编辑器模式追加 --agent ...
           if mode == 'open' and '--agent' not in cmd:
               cmd.append('--agent')

       Loom/tests/test_hub.py:310-320（本轮未改，git diff f53a82a..HEAD -- 该文件 = 0 行）
           check(".py 用系统默认 python + --open",
                 cfg.build_launch_command(py, scene, 'open') ==
                 ["python", py['path'], "--open", scene])
           check(".py 播放模式 --run",
                 cfg.build_launch_command(py, scene, 'run') ==
                 ["python", py['path'], "--run", scene])
           check(".py 纯启动无场景参数",
                 cfg.build_launch_command(py, None) == ["python", py['path']])
           check(".exe 直接运行 + --open",
                 cfg.build_launch_command(exe, scene, 'open') ==
                 [exe['path'], "--open", scene])
3. 路径枚举（该函数全部出口，mode/scene/prefer/kind 四维）：
   - 路径 1 prefer='py' 且 main_py 存在 → cmd=[py, main_py] → 加 scene → (mode=='open' 才) 加 --agent
   - 路径 2 prefer='exe' 且 main_exe 存在 → cmd=[main_exe] → 同上
   - 路径 3 kind=='exe' → cmd=[main_path] → 同上
   - 路径 4 其余（kind=='py'）→ cmd=[py_exe, main_path] → 同上
   - 路径 5 mode=='open' 且 cmd 里已含 '--agent' → 不重复追加
   四条主路径在 mode='open' 时都追加（探针实测 --agent x1），mode='run'/None 时不追加。函数无动态分派、无 **kwargs 转发，枚举完备。
4. 实际行为：mode='open' 时返回值在基线基础上多一个尾部元素 '--agent'。
5. 差异：C8 期望的"open 带 --agent"成立；但 test_hub.py 的三条精确列表断言把"不带"写成了契约，两处契约现在互斥。
6. 触发条件：任何一次执行 Loom/tests/test_hub.py（打包/发布前必跑的回归脚本）。
7. 验证（实测输出）：

       $ cd Loom; python tests/test_hub.py
       FAIL .py 用系统默认 python + --open
       PASS .py 播放模式 --run
       FAIL .py 纯启动无场景参数
       FAIL .exe 直接运行 + --open
       总结果: FAIL ❌ ['.py 用系统默认 python + --open', '.py 纯启动无场景参数', '.exe 直接运行 + --open']
       $ echo $LASTEXITCODE
       1
       对照：python tests/test_hub_eai.py → 总结果: ALL PASS；python tests/test_hub_controller.py → 总结果: ALL PASS
8. 结论：证伪失败（测试确实被打红，且这是打包链已有的自动化闸门），判 P-PROVED。
   等级分析：行为本身符合 C8 意图，但 (a) 打包链失去"启动命令没退化"的既有证明手段；
   (b) 仓库同时存在两套权威断言（测试 vs 新注释），后续任何改 --agent 语义的人都踩坑；
   (c) 这是发布链唯一的自动化闸门被打破 —— 按"发布闸门失效"记 P1，不记 P3。

**建议修复方向（不含代码）**：二选一（人类裁决，见 §5 问题 Q1）——
(A) 把 test_hub.py 的 3 条断言更新为符合 C8 的期望值；
(B) 把 --agent 的追加从 build_launch_command 移到调用方（hub_controller.open_project / hub_commands.launch_spec），
保住 build_launch_command 的"纯命令拼装"契约。
两条路都必须补一条新断言："mode='open' 必含且只含一个 --agent；mode='run' 必不含 --agent"。

**修复时必须保持的白盒契约**：C7（mode 三态语义）、C8（编辑器要带 Agent 桥）、
resolve_runtime_path 对相对路径的解析（不能把 scene 变回相对路径，否则踩 2026-10-19 启动路径 bug）。
**波及调用方**：hub_controller.py:458（GUI open_project，必须继续带）、hub_commands.py:481（命令层 engine_launch，
必须继续带且不能重复带）、LoomHub/tests/_tmp/_verify_launch_fix.py:41（手工验证脚本中的期望值）。

---

### 2.2 P-05-02 · mode=None（纯启动编辑器）不追加 --agent，与设计目标不一致 [P-PROVED / P2 / REGRESSION]

**反手（证伪）**

1. 判定基准：C8 的措辞是"编辑器模式追加 --agent …与'打开引擎后 Agent 接上'的设计目标不符"。
   若"编辑器模式"只指 --open <scene>，则 mode=None 不追加是正确的（没有场景）。
2. 代码证据：hub_config.py:444-446 把 mode 定义为三态，None = "纯启动编辑器"；hub_config.py:467 判断 mode == 'open'。
3. 路径枚举（mode ∈ {open, run, None} × scene ∈ {有, 无} × kind ∈ {py, exe}）：
   - open + scene → 追加（探针 x1）
   - open + 无 scene → 追加（探针 x1）
   - run + scene → 不追加（符合 C8：玩家进程不能开端口）
   - None + scene → 拼出 --run，不追加 --agent（探针 x0）
   - None + 无 scene → 不追加（探针 x0）   ← 唯一与"纯启动编辑器"语义冲突的格子
   枚举完备（无动态分派）。
4. 实际行为：mode=None 的两种组合都拿不到 --agent。
5. 差异：C8 的目标是"LoomHub 打开的编辑器就有 Agent 桥"；mode=None 打开的也是编辑器（C7 原文），却没有桥。
6. 触发条件：任何以 mode=None 启动编辑器的调用方。当前 GUI 主路径不传 None，因此这是"契约可表达、当前无调用方"的不一致。
7. 验证：

       $ python Loom\tests\_tmp\beta3_scan_05_launch.py
       info=py  mode=open  scene=有      -> [... '--open', 'D:\s\a.json', '--agent'] --agent x1
       info=py  mode=run   scene=有      -> [... '--run', 'D:\s\a.json']              --agent x0
       info=py  mode=open  scene=无      -> [... '--agent']                            --agent x1
       info=py  mode=缺省  scene=无      -> [... '--agent']                            --agent x1
       info=py  mode=None  scene=有      -> [... '--run', 'D:\s\a.json']               --agent x0
       info=py  mode=None  scene=无      -> [...]                                      --agent x0
8. 结论：证伪失败（在"纯启动编辑器也算编辑器"这一读法下存在反例），判 P-PROVED，P2。

**建议修复方向**：把判定从 mode == 'open' 改为"非播放模式"（mode != 'run'），使"编辑器语义"与 C7 三态定义对齐；
或反向修 C7 的 docstring，把 None 明确改述为"不启动编辑器"，让契约与实现收敛。二者选一必须同步 §2.1 的断言。
**修复必须保持的契约**：mode='run' 永不带 --agent；已含 --agent 时不重复追加。
**波及调用方**：同 P-05-01。

---

### 2.3 P-05-03 · 命令层与配置层重复追加 --agent，最终命令行出现两个 --agent [P-PROVED / P3 / REGRESSION]

**反手（证伪）**

1. 判定基准：没有任何契约规定"参数只能出现一次"；若下游用成员判断，重复无害。
2. 代码证据：
   - hub_commands.py:482-483：if as_bool(args.get('agent')): cmd_parts.append('--agent')
   - hub_config.py:467：if mode == 'open' and '--agent' not in cmd —— 该守卫在 build_launch_command 返回前执行，
     此刻 cmd 里还没有命令层要追加的那个 --agent，守卫看不到它。
   - 下游消费方：Loom/ui/loom_gui.py:4089 用 if '--agent' in sys.argv（成员判断，重复不影响）。
3. 路径枚举：
   - 路径 1 agent=true + mode='open' → 两个 --agent（探针 x2）
   - 路径 2 agent=true + mode='run' → 一个（来自命令层）
   - 路径 3 agent=false + mode='open' → 一个（来自配置层：命令层的"关"已失效）
   - 路径 4 agent=false + mode='run' → 零个
4. 实际行为：路径 1 出现两个 --agent；路径 3 出现"命令层要求不开、配置层照样开"的语义反转。
5. 差异：agent 参数在 open 模式下不再是可关闭开关，as_bool(args.get('agent')) 沦为死逻辑（AUDIT-DEADCODE）。
6. 触发条件：命令层 engine_launch {scene, agent:true/false}。
7. 验证：

       $ python Loom\tests\_tmp\beta3_scan_05_launch.py
       1) build_launch_command 返回      : [... '--open', 'D:\s\a.json', '--agent']
       2) 命令层 as_bool(agent) 再追加后 : [... '--open', 'D:\s\a.json', '--agent', '--agent']   --agent x2
8. 结论：证伪失败（路径 1 确有重复、路径 3 确有语义反转），判 P-PROVED，P3。

**建议修复方向**：只在一层决定 --agent（推荐配置层，因为它服务"所有 LoomHub 打开的编辑器"这一设计目标）；
命令层的 agent 参数改为"显式关闭"语义或删除并同步文档；无论哪种都要保证最终命令行里 --agent 恰好一次。
**修复必须保持的契约**：C8；hub_commands.launch_spec 的返回结构 {'cmd','cwd','env','prefer','mode','interpreter'} 不得改。
**波及调用方**：Loom/tests/test_hub_eai.py:459（断言"命令含 --agent"，改后仍应通过）。

---

### 2.4 P-05-04 · 缺预置运行时只打警告：发布包可以不带 97MB 头号特性而"成功"出厂 [P-PROVED / P1 / REGRESSION]

**反手（证伪）**

1. 判定基准：C2/C3 说"随包分发预编译运行时"；C6 只要求 build_game（消费端）在缺运行时给出指引，
   没有明文要求 package_engine（生产端）失败退出。
2. 代码证据：

       tools/package_engine.py:157-175
           _pr_src = os.path.join(ENGINE_DIR, 'player_runtime', 'game_player.dist')
           if os.path.isdir(_pr_src) and os.path.isfile(os.path.join(_pr_src, 'MyGame.exe')):
               ... copytree + 写 运行时.json ...
           else:
               print('[打包] 警告: 未找到预置播放器运行时 … 游戏开发机将需要 --build-runtime (需 Nuitka+MSVC)')
       tools/package_engine.py:215-227   main() 无 sys.exit、无 --require-runtime 开关
       Loom/.gitignore:50                player_runtime/     <- 该目录永不入库
       docs/handoff/接手总纲.md:125      "前提：工作区 Loom/player_runtime/game_player.dist 存在（已 gitignore，不入库；从安装版引擎或上次构建拷贝）"
3. 路径枚举（make_zip 的运行时分支只有两条）：
   - 路径 A：dist 目录存在且含 MyGame.exe → 拷贝 + 写 运行时.json（探针用例 2）
   - 路径 B：其它一切（目录不存在 / 目录在但 exe 名不符 / exe 只是占位）→ 打印一行警告后继续 python 打包、写元数据、写 zip
   两条路径都到达 zip_path = os.path.join(DIST_DIR, 'Loom-%s.zip' % version) 并 return zip_path。
4. 实际行为：路径 B 产出的 zip 名称与元数据版本与正式发布版完全一致，只少 97MB 运行时（探针用例 1：5 个条目，无 player_runtime）。
5. 差异：C2 期望"零编译器"是发布包卖点；实际可产出"版本号正确、卖点缺失"的包，构建命令返回 0。
6. 触发条件：全新 clone / CI checkout（目录被 gitignore，天然不存在）后执行
   python tools\package_engine.py --version 0.1.0.beta3；或 --build-runtime 失败只留下 .build。
7. 验证（探针在临时假引擎树上跑真实 make_zip，将 build_embed_pyzip 换成桩以避开联网 pip）：

       $ python Loom\tests\_tmp\beta3_scan_05_makezip.py
       === 用例 1: 缺 player_runtime (等价于 git clone 后没放预编译运行时) ===
       [打包] 警告: 未找到预置播放器运行时 (player_runtime/game_player.dist)，游戏开发机将需要 --build-runtime (需 Nuitka+MSVC)
       [打包] 元数据版本 -> 0.1.0.beta3
       [打包] 完成: ...\Loom-0.1.0.beta3.zip (0.00 MB)
       [探针] make_zip 正常返回: Loom-0.1.0.beta3.zip   (没有抛异常)
       [探针] 含 player_runtime/game_player.dist/MyGame.exe : False
       === 用例 2: 有预置运行时 + 正常元数据 ===
       [探针] 含 player_runtime/game_player.dist/MyGame.exe : True
       真实发布物对照（探针 beta3_scan_05_zip.py）：beta3 zip 内 player_runtime 条目 100 个、解压后 96.70 MB
8. 结论：证伪失败（缺特性仍"成功"出厂，且该路径天然存在），判 P-PROVED。等级 P1：
   不崩不报错，但会让后续版本带着"零编译器"卖点发布而实际不带运行时；用户侧要等到"游戏开发机打不出包"才发现，
   而发布产物不可逆（tag 已推、release 已建，见 P-05-07/P-05-08）。

**建议修复方向**：把"缺运行时"升级为可判定的失败（退出码非 0），或加显式开关（如 --allow-missing-runtime）让
"故意不带运行时"成为必须写下来的决定；警告文本要区分两种成因（目录不存在 / 缺 MyGame.exe）。
可选加强：**加一次运行时可执行性抽检**（检查 dist 里是否存在运行库 python3xx.dll 与 MyGame.exe 两个必备项）。
**修复必须保持的契约**：C2；zip 内布局 Loom/player_runtime/game_player.dist/*（build_game 依赖，见 P-05-10）；
package_engine 仍需支持"故意不带运行时"的调试场景。
**波及调用方**：docs/handoff §3.2 发布手册；任何包装 package_engine 的脚本（当前无，但 release_github 隐式依赖产物存在）。

---

### 2.5 P-05-05 · 元数据回写失败被 except 吞掉，仍产出一个 LoomHub 装不上的 zip [P-PROVED / P2 / REGRESSION]

**反手（证伪）**

1. 判定基准：C1 要求"文件名/元数据/安装目录三者一致"；实现里确有 print 警告，不是完全静默。
2. 代码证据：package_engine.py:183-192

       try:
           _meta_dst = os.path.join(tmp_dir, 'Loom', os.path.basename(META_PATH))
           with open(_meta_dst, 'r', encoding='utf-8') as _f:
               _meta = json.load(_f)
           _meta['version'] = version
           with open(_meta_dst, 'w', encoding='utf-8') as _f:
               json.dump(_meta, _f, ensure_ascii=False, indent=2)
           print('[打包] 元数据版本 -> %s' % version)
       except Exception as _e:
           print('[打包] 警告: 元数据版本回写失败: %r' % _e)

   之后 193-212 行继续 write_launcher / write_meta_readme / 写 zip / 返回。
3. 路径枚举：回写分支两条 ——
   (A) 成功：包内元数据版本 = version；
   (B) 任意异常（JSONDecodeError / UnicodeDecodeError / PermissionError）：打印警告后继续，包内 解释器.json 保持原始（可能损坏）内容。
4. 实际行为：路径 B 产出的 zip 内 解释器.json 为非法 JSON。
5. 差异：LoomHub 侧 read_zip_metadata 对非法 JSON 返回 (None, None)（hub_install.py:51-54）；
   GUI 侧 preview_zip 报"压缩包里没有找到 解释器.json（不是有效的 Loom 解释器包）"（hub_controller.py:136-140）。
   即：发布者看到"打包完成"，用户拿到装不上的包。
6. 触发条件：源 解释器.json 被安全软件/编辑器写坏、编码变异、或磁盘半写。
   本仓库对该类事故有先例：Loom.py:227-280 的 _self_check_sources（检测 .py 被改成全零）即为同类事故的针对性防线。
7. 验证：

       $ python Loom\tests\_tmp\beta3_scan_05_makezip.py
       === 用例 3: 元数据文件损坏 (模拟 AV/编码/半写), 看是否静默继续 ===
       [打包] 警告: 元数据版本回写失败: JSONDecodeError('Expecting property name enclosed in double quotes: line 1 column 3 (char 2)')
       [打包] 完成: ...\Loom-0.1.0.beta3.zip (0.00 MB)
       [探针] make_zip 正常返回: Loom-0.1.0.beta3.zip   (没有抛异常)
       [探针] 包内 解释器.json 无法解析: JSONDecodeError(...)
       [探针] LoomHub.read_zip_metadata 结果: (None, None)
8. 结论：证伪失败（失败模式可复现且下游确实装不上），判 P-PROVED，P2。

**建议修复方向**：回写失败应中止打包（或至少在写 zip 之前中止），并把"读不到/解析不了源元数据"与"写不进去"分成两种可辨识错误；
收尾前加一次自检：从已写好的 zip 里读回 解释器.json，交给 hub_config.validate_meta 判一遍（兑现 C9 的"发版自检"）。
**修复必须保持的契约**：C1、C9、C10；不得改动 解释器.json 的其它字段（name/python_version/main/main_exe/description 均被消费）。
**波及调用方**：LoomHub/hub_install.read_zip_metadata、hub_controller.preview_zip / do_install_zip。
### 2.6 P-05-06 · --version 原样写进包内元数据，未过 C9/C10 白名单：非法版本号会产出装不上的包 [P-PROVED / P2 / REGRESSION]

**反手（证伪）**

1. 判定基准：C9（hub_config.py:107-112）声称"发版自检（打 zip 前）与导入/扫描共用同一判据"；C10 给出格式白名单。
   若 producer 侧真有这个自检，非法 --version 会在打包时被拦下 —— 那样 P-05-06 不成立。
2. 代码证据：
   - producer 侧：tools/package_engine.py:217 只有 parser.add_argument('--version', help='覆盖版本号…')，
     全文无 validate_meta、无正则、无长度校验；:187 直接执行 _meta['version'] = version。
   - consumer 侧：hub_config.py:122-123 与 hub_install.py:116-117 两处都用白名单拒收。
   - 实测：package_engine 里 META_PATH 的全部引用只有 3 行（L20 定义、L32 读、L184 拼路径），无任何校验调用。
3. 路径枚举：
   - 路径 A：--version 合法（0.1.0.beta3）→ 包内元数据合法，LoomHub 可装
   - 路径 B：--version 非法（0.1.0-beta3 / v0.1.0.beta3 / 0.1 / beta3）→ 非法字符串被原样写进 解释器.json，LoomHub 拒装
   - 路径 C：--version 缺省 → 取自 Loom/解释器.json（当前合法 0.1.0.beta2）
4. 实际行为：路径 B 产出"内容自洽但不可安装"的 zip。
5. 差异：C9 承诺的发版自检不存在；且本轮改动**加重了失败模式**：
   基线 f53a82a 下 --version 只影响 zip 文件名，包内元数据始终是源文件里的合法值（0.1.0.beta2），
   非法 --version 最多造成"文件名与元数据不一致"（正是 C1 要修的那类）；
   现在非法 --version 会污染元数据本身，使 zip 完全不可安装。
6. 触发条件：python tools\package_engine.py --version 0.1.0-beta3（点写成横线），或照 tag 习惯加 v 前缀
   （tag 命名是 engine-v0.1.0.beta3，见 release_github.py:236，"加 v"是极自然误输入）。
7. 验证：

       $ python Loom\tests\_tmp\beta3_scan_05_pack.py
       4) 元数据回写: package_engine 里所有 META_PATH 引用行
          L20: META_PATH = os.path.join(ENGINE_DIR, '解释器.json')
          L32: with open(META_PATH, 'r', encoding='utf-8') as f:
          L184: _meta_dst = os.path.join(tmp_dir, 'Loom', os.path.basename(META_PATH))
          --version '0.1.0.beta3'  -> validate_meta(): None
          --version '0.1.0-beta3'  -> validate_meta(): "版本号须为 x.y.z 或 x.y.z.betaN 格式 (实际: '0.1.0-beta3')"
          --version 'v0.1.0.beta3' -> validate_meta(): "版本号须为 x.y.z 或 x.y.z.betaN 格式 (实际: 'v0.1.0.beta3')"
          --version '0.1'          -> validate_meta(): "版本号须为 x.y.z 或 x.y.z.betaN 格式 (实际: '0.1')"
          --version 'beta3'        -> validate_meta(): "版本号须为 x.y.z 或 x.y.z.betaN 格式 (实际: 'beta3')"
       端到端后果（探针 beta3_scan_05_instver.py）：
       === 用例 2: package_engine 回写了非法版本号 --version 0.1.0-beta3 ===
         InstallError -> 版本号格式非法 (需 x.y.z 或 x.y.z.betaN): 0.1.0-beta3
8. 结论：证伪失败（C9 的自检不存在，且非法输入产生不可安装产物），判 P-PROVED，P2。

**建议修复方向**：在 package_engine 复用 hub_config 的同一判据（C9 原话即"共用同一判据"），
校验失败立即失败退出；一次校验同时约束"文件名版本"与"包内元数据版本"两个派生点。
**修复必须保持的契约**：C9、C10、C17（缺省仍读 Loom/解释器.json）；
不得把合法性判定复制成第二份手写正则（否则又回到"两边平行线"）。
**波及调用方**：release_github 的 ENGINE_VERSION 也必须过同一校验（见 P-05-07）。

---

### 2.7 P-05-07 · 两个工具的版本缺省值彼此不一致：漏一个 --version 就会发出空 release 并烧掉 tag [P-PROVED / P1]

**反手（证伪）**

1. 判定基准：C16 要求三处版本号一致（手抄或环境变量）；若不一致只是使用者操作失误、工具无法防御，则不算缺陷。
2. 代码证据：
   - tools/package_engine.py:29-33 load_version()：缺省读 Loom/解释器.json
   - Loom/解释器.json:3  "version": "0.1.0.beta2"（git show f53a82a 同样是 beta2 —— 全程未被工具链更新）
   - tools/release_github.py:17 ENGINE_VERSION = os.environ.get('LOOM_ENGINE_VERSION', '0.1.0.beta3')
   - tools/release_github.py:21-32 由 ENGINE_VERSION 派生资产路径
3. 路径枚举（发布链只有 4 个版本组合）：
   - 组合 1：打包带 --version 0.1.0.beta3 + 发布用缺省 → 一致（本次实际路径）
   - 组合 2：打包不带 --version（得到 Loom-0.1.0.beta2.zip）+ 发布用缺省 → 不一致
   - 组合 3：打包带 X + 环境变量 Y ≠ X → 不一致
   - 组合 4：打包带 X + 环境变量 X → 一致
   组合 2 完全由两个工具的缺省值决定，不需要任何人犯错（"忘记加参数"本身就是缺省路径）。
4. 实际行为：组合 2 下 release_github 会建 release、打本地 tag、推远端 tag，但上传因文件不存在被跳过。
5. 差异：C16 期望三处一致；实际缺省值互相矛盾（beta3 vs beta2），且无任何一致性断言。
6. 触发条件：先 python tools\package_engine.py（无参），再 python tools\release_github.py（无 env）。
7. 验证：

       $ python Loom\tests\_tmp\beta3_scan_05_pack.py
       1) load_version() 无参默认值 = 0.1.0.beta2
          源码 Loom/解释器.json version = 0.1.0.beta2
       tools/release_github.py:17 缺省 = 0.1.0.beta3（源码直读）

       假 GitHub API 端到端（探针 beta3_scan_05_release.py，场景 A = dist 里没有对应版本 zip）：
       [发布] 创建 GitHub Release: engine-v0.1.0.beta3
       [发布] release 已创建: http://fake/rel/1
       [警告] 文件不存在，跳过: ...\Loom-0.1.0.beta3.zip
       [探针] publish_engine 正常返回 (未抛异常), 退出码将是 0
       [探针] 打过 tag: [('create_local_tag', 'engine-v0.1.0.beta3')]
       [探针] 推过 tag: [('push_tag', 'engine-v0.1.0.beta3')]
       [探针] 上传 asset 请求数: 0
8. 结论：证伪失败（缺省组合即可触发，后果是已发布状态），判 P-PROVED，P1。
   不可逆性：tag 已在远端（同 tag 再建 release 会 422，见 P-05-08）；
   用户侧 hub_github.py:193-194 会跳过"没有 zip asset 的 release"，于是该版本在 LoomHub 里"看不见"，
   但仓库里挂着一个标题写着版本号的空 Release，极易被当成"已发布"。

**建议修复方向**：给发布链建单一事实源（一份 version 定义，打包与发布都读它）；
release_github 的 publish_* 入口做资产存在性预检：任一目标资产缺失就不做任何写操作（不建 release、不打 tag、不推 tag），退出非 0。
**修复必须保持的契约**：C15、C16、C17；不得让"tag 已存在"从跳过变成失败（会打断 §3.5 的重跑流程）。
**波及调用方**：docs/handoff §3.2/§3.5 手册；tools/package_hub.py 的版本来源（见 P-05-14）；
LoomHub 在线安装对 tag 的解析（hub_github.py:179）。

---

### 2.8 P-05-08 · 上传失败后"重跑"无法恢复；"删同名 asset"分支永无命中对象 [P-PROVED / P2]

**反手（证伪）**

1. 判定基准：C15 只说明"tag 已存在时 push 会失败、用 git push -f 校正"，并未承诺脚本可重入；
   代码里写了"删除已存在 asset"的分支，看起来是考虑过重试的。
2. 代码证据：
   - release_github.py:116-134 create_release：非 200/201 一律 print + raise SystemExit(1)，不区分 422 already_exists
   - release_github.py:137-150 upload_asset：先按名删除 release['assets'] 里的同名项，再 POST 上传
   - 删除逻辑遍历的是 create_release 刚返回的对象；新 release 的 assets 必为空数组
   - release_github.py:104-113 create_local_tag：本地 tag 已存在则跳过（不失败）
3. 路径枚举（一次完整发布 = tag → release → upload → push）：
   - 路径 1 全新 tag，上传成功 → 正常
   - 路径 2 全新 tag，上传失败 → SystemExit(1)，release 与本地 tag 都已留下
   - 路径 3 重跑（tag 与 release 都已存在）→ create_local_tag 跳过 → create_release 收 422 → SystemExit(1)，
     **永远到不了 upload_asset**，故"删同名 asset 再传"这条自愈路径不可达
   - 路径 4 手工删掉远端 release 后重跑 → 回到路径 1/2
4. 实际行为：失败后只能人工介入（删远端 release 或手工上传资产）。
5. 差异："删除同名 asset"暗示可重复上传的意图，但控制流保证它永不命中（AUDIT-DEADCODE）。
6. 触发条件：332MB 资产在 7200s 内上传失败（网络抖动、GitHub 5xx），或本地资产缺失（P-05-07）。
7. 验证：

       $ python Loom\tests\_tmp\beta3_scan_05_release.py
       === 场景 B: zip 存在但首次上传失败 (HTTP 502), 然后按文档重跑一次 ===
       [发布] 上传 asset: Loom-0.1.0.beta9.zip (0.00 MB)
       [错误] 上传失败 (HTTP 502)
       {"message": "bad gateway"}
       [探针] 第一次: SystemExit -> 1
       [探针] 第一次请求序列: [... ('POST', '/repos/lhy302/WeaveEngine/releases'), ('POST', '/uploads/2?name=Loom-0.1.0.beta9.zip')]
       [发布] 创建 GitHub Release: engine-v0.1.0.beta9
       [错误] 创建 release 失败 (HTTP 422)
       {"message": "Validation Failed", "errors": [{"code": "already_exists"}]}
       [探针] 第二次(重跑): SystemExit -> 1
       [探针] 两轮合计 DELETE(删同名 asset) 请求数: 0
8. 结论：证伪失败（重跑必失败、自愈分支不可达），判 P-PROVED，P2。
   注：该缺陷在基线同样存在（422 处理与删除分支都不是本轮新写），**不标 [REGRESSION]**；
   但本轮把"大文件 + 7200s 超时"引入发布链（:155-157），使"上传需要重试"的概率上升，风险量级被放大，故列 P2。

**建议修复方向**：让发布真正两段式幂等 ——
(1) create_release 遇 422 already_exists 时改为 GET 取回该 tag 的 release 并继续；
(2) 取回的 release 若已有同名 asset，先删再传（届时删除分支才有意义）；
(3) 失败信息区分"网络/超时"（_req 返回 status 0）与 HTTP 错误，避免"HTTP 0"这种无信息报错。
**修复必须保持的契约**：C15；asset 命名规则 Loom-<version>.zip；不得在失败路径 delete 远端既有 release（会误删历史资产）。
**波及调用方**：docs/handoff §3.5 手册；hub_github.list_engine_releases（依赖 assets 非空）。

---

### 2.9 P-05-09 · tag 版本与包内元数据版本无一致性校验，可造成"目录名 A、台账版本 B" [P-PROVED / P2]

**反手（证伪）**

1. 判定基准：C11 说离线安装版本来自 zip 元数据；C12 说在线安装版本来自 tag。
   两条路径用**两个不同来源**，若二者永远相等则无缺陷。
2. 代码证据：
   - 离线（选 zip）：hub_controller.py:163-173 version = info.get('version')（包内元数据）
   - 在线（GitHub）：hub_github.py:179 version = tag 去掉 engine-v 前缀；hub_commands.py:322 调
     inst.install_from_zip(dest, version, ...) —— 用的是 tag 版本，不读包内元数据
   - install_from_zip 用 version 建目录（hub_install.py:115-118），登记时用 discover_interpreter(target)（读元数据版本）
   - release_github.py 侧：tag 来自 ENGINE_VERSION，包内元数据来自 package_engine 的 --version，二者无交叉校验
3. 路径枚举：
   - 路径 1 ENGINE_VERSION == 打包 --version → 目录名与台账版本一致（正常）
   - 路径 2 二者不等（或有人手工上传别的包）→ 目录名 <root>/<tag版本>，台账版本 <包内版本>
   - 路径 3 包内版本非法 → install_from_zip 直接 InstallError（P-05-06），不会产生错目录
4. 实际行为：路径 2 产生"目录名 0.1.0.beta4 / 台账 0.1.0.beta3"的错位安装。
5. 差异：C11 与 C12 对"版本"的定义不同却共用一个落地点（安装目录名），不一致时无任何检测。
6. 触发条件：发布时 ENGINE_VERSION 与打包 --version 不一致（P-05-07 的缺省路径即可），或资产被替换。
7. 验证（探针用真实 install_from_zip，台账指向临时文件）：

       $ python Loom\tests\_tmp\beta3_scan_05_instver.py
       === 用例 1: zip 元数据 beta3, 但安装参数(来自 release tag)给 beta4 ===
         安装后目标目录 : ...\root1\0.1.0.beta4\Loom
         目录内元数据版本: 0.1.0.beta3
         台账登记版本   : ['0.1.0.beta3']
         目录名与元数据是否一致: False
8. 结论：证伪失败（错位可复现），判 P-PROVED，P2。
   影响面：scan_install_root 按元数据版本排序/显示（hub_config.py:170 _version_key），
   用户看到 beta3 而磁盘目录是 beta4；add/remove 以 dir 为 key（hub_config.py:186,212），因此不会误删，但版本视图长期错位。

**建议修复方向**：在线安装下载完成后先用 read_zip_metadata 读包内元数据，与 tag 版本比对；
不等则拒绝安装并打印两个版本号（或以元数据为准）；发布侧在 upload 前校验"资产名版本 == 包内元数据版本"。
**修复必须保持的契约**：C11/C12 两条入口不得删除；hub_install 的 _safe_extract 与完整性自检不得绕过。
**波及调用方**：hub_commands.interpreter_github_install、GUI"从 GitHub 安装"、hub_github.list_engine_releases。

---

### 2.10 P-05-10 · _resolve_runtime 在"目录在但 dist 缺 exe"时静默选中错误层 [P-PROVED / P2 / 已有]

**反手（证伪）**

1. 判定基准：C6 要求"缺运行时给出明确指引"；目录整体不存在时实现确实抛 SystemExit（探针用例 F）。
2. 代码证据（HEAD）：

       Loom/build_game.py:69-80
           if os.path.isdir(DEFAULT_RUNTIME_DIR):
               _dist = os.path.join(DEFAULT_RUNTIME_DIR, 'game_player.dist')
               if os.path.isfile(os.path.join(_dist, 'MyGame.exe')):
                   return _dist
               return DEFAULT_RUNTIME_DIR        # <- 静默兜底，不抛错
           raise SystemExit("缺少玩家运行时 (player_runtime/game_player.dist)。...")

   基线（git show f53a82a）只有 return DEFAULT_RUNTIME_DIR，兜底行为原本就存在；本轮新增的只是 dist 优先分支。
3. 路径枚举（默认分支三种目录状态）：
   - 路径 A 目录不存在 → SystemExit（C6 满足，探针 F）
   - 路径 B 目录存在且 game_player.dist/MyGame.exe 在 → 返回 dist（C5 满足，探针 A）
   - 路径 C 目录存在但缺 dist/MyGame.exe → 返回目录本身，不报错（探针 B）
   路径 C 覆盖现实状态"只留 game_player.build"（--build-runtime 中途失败，或只拷了一半）。
4. 实际行为：路径 C 下 build_game 第 5 步把 game_player.build/ 拷进发布夹，没有 MyGame.exe。
5. 差异：C6 要求明确指引；实际静默继续，并打印"双击 exe 即玩"（build_game.py:240）。
6. 触发条件：player_runtime 存在但为空 / 只含 .build / 只含残缺 dist（含 MyGame.exe 但缺运行库时**不会**被发现）。
7. 验证：

       $ python Loom\tests\_tmp\beta3_scan_05_runtime.py
       === 用例 B: 默认目录存在, 但只有 .build 中间产物, 没有 dist/MyGame.exe ===
         返回: ...\tmpwnibn105  (没有抛错)
         发布夹顶层: ['game_player.build']  -> 含 MyGame.exe ?  False
       === 用例 F: 默认目录整个不存在 ===
         SystemExit 前两行: 缺少玩家运行时 (player_runtime/game_player.dist)。 |   · 正式引擎包已预置该运行时, 无需编译器;
8. 结论：证伪失败（存在一条静默选错层的路径），判 P-PROVED，P2。
   非本轮引入（标"已有"），但本轮修复宣称解决的"exe 被多套一层 / 选错层"只覆盖路径 B，未闭环。

**建议修复方向**：把"目录存在但无可用 dist"与"目录不存在"合并为同一条失败路径（同一文案）；
决定拷贝前确认两个必备项同时存在（MyGame.exe + 运行库 DLL）。
**修复必须保持的契约**：C5（发布夹必须平铺 exe）、C6（文案给出三种解法：装引擎包 / --build-runtime / --runtime）；
"直接在 player_runtime 下放 MyGame.exe"的历史布局仍需可用。
**波及调用方**：build_game.main 第 4/5 步；agent_commands 的 unity_build_player（同一脚本）。

---

### 2.11 P-05-11 · --runtime 分支不做分层归一化，仍能造出"多套一层目录" [P-PROVED / P2 / 已有]

**反手（证伪）**

1. 判定基准：_resolve_runtime 的 docstring（build_game.py:60-61）只承诺"可以是 dist 目录（全拷）或单个 exe"，
   用户显式给 player_runtime 目录属超出声明契约的输入，可以不算缺陷。
2. 代码证据：build_game.py:62-68

       if runtime_arg:
           p = os.path.abspath(runtime_arg)
           if os.path.isdir(p):
               return p                    # 原样返回，不下钻
           if os.path.isfile(p):
               return os.path.dirname(p)

   默认分支则会下钻到 game_player.dist（:73-75）。
3. 路径枚举（--runtime 三种形态）：
   - 路径 1 目录（无论是否 dist 布局）→ 原样返回
   - 路径 2 文件（exe）→ 返回其所在目录
   - 路径 3 不存在 → SystemExit
4. 实际行为：路径 1 传入 player_runtime 目录 → 发布夹 = 发布/<名>/game_player.dist/MyGame.exe。
5. 差异：同一份磁盘布局，默认分支平铺、--runtime 分支嵌套 —— 两条分支语义不等价（AUDIT-ASYMMETRY）。
6. 触发条件：C6 的错误文案明确建议"--runtime 指定已有 dist 目录"，用户很容易把上次构建出的 player_runtime 整目录传进来。
7. 验证：

       $ python Loom\tests\_tmp\beta3_scan_05_runtime.py
       === 用例 C: --runtime 直接给了 player_runtime 目录 (内含 game_player.dist) ===
         返回: ...\tmpfbybmzjp  (原样返回, 没有下钻到 game_player.dist)
         发布夹顶层: ['game_player.dist']
         MyGame.exe 实际位置: [...\game_player.dist\MyGame.exe]
8. 结论：证伪失败（两条分支语义不等价，C5 宣称"已改为优先返回 dist"对此路径未覆盖），判 P-PROVED，P2。

**建议修复方向**：两条分支共用同一个归一化步骤 —— 无论入参来自默认值还是 --runtime，
都先尝试下钻 game_player.dist（若存在且含 MyGame.exe），再判定是否为可用 dist；都不满足时给同一文案错误。
**修复必须保持的契约**：C5、C6；"直接给 dist 目录"与"直接给 exe 文件"两种历史用法继续有效。
**波及调用方**：同 P-05-10。

---

### 2.12 P-05-12 · 运行时.json 的 version/built_at 不可被下游信任（与 C3 的"构建时间"语义不符）[P-PROVED / P2 / REGRESSION]

**反手（证伪）**

1. 判定基准：C3 说写"版本/构建时间"；C4 说明目前没有源码哈希机制。若这两个字段只是备注性元信息、无下游消费者，
   则"不可信任"只是文档措辞问题，等级应降为 P3。
2. 代码证据：

       tools/package_engine.py:164-172
               json.dump({'version': version,                              # 打包参数
                          'built_at': time.strftime('%Y-%m-%d %H:%M:%S'),  # 打包时刻
                          'note': '预编译播放器运行时 …'}, _f, ...)
       except Exception:
           pass        # 写失败完全静默

   - version 来自 load_version()（--version 或 解释器.json），与磁盘那份 dist 的实际来源无关；
   - built_at 是"打包这台机器此刻的时间"，不是运行时编译时间；
   - 消费者搜索：本条 grep 全仓库，运行时.json 只有 tools/package_engine.py:165 一处写入 + docs 三处提及，**无任何读取代码**。
3. 路径枚举：
   - 路径 1 用旧安装包里的 dist 打包新版（docs/handoff:125 明确允许"从安装版引擎或上次构建拷贝"）→ version=新版本号，二进制是老的
   - 路径 2 重新 --build-runtime 后打包 → version=新版本号，二进制是新的；与路径 1 的元数据完全相同、不可区分
4. 实际行为：两个 zip 的 运行时.json 只反映"谁在何时打包"，不反映"运行时从哪份源码编出来"。
5. 差异：C3 的"构建时间"暗示可追溯；C4 明说没有版本戳机制。字段名会诱导下游（以及"下一位 Agent"）当版本戳使用。
6. 触发条件：任何人想用它实现 C4 建议的一致性告警（handoff §7 第 4 条正是这个建议）。
7. 验证（真实发布物）：

       $ python Loom\tests\_tmp\beta3_scan_05_zip.py
       zip 文件名 : Loom-0.1.0.beta3.zip
       包内 解释器.json version : 0.1.0.beta3
       player_runtime 条目数    : 100   player_runtime 解压后 : 96.70 MB
       运行时.json : {"version": "0.1.0.beta3", "built_at": "2026-11-07 21:36:35", "note": "预编译播放器运行时 ..."}
       zip 文件名 : Loom-0.1.0.beta4.zip
       player_runtime 条目数    : 100   player_runtime 解压后 : 96.60 MB
       运行时.json : {"version": "0.1.0.beta4", "built_at": "2026-11-07 18:19:26", ...}
       ↑ 两个包运行时大小不同（96.70 vs 96.60 MB -> 确系两次不同构建），
         而 built_at 的大小顺序（beta4 18:19 早于 beta3 21:36）与版本号顺序相反：
         该字段记录的是打包时刻，用它无法判断哪份二进制更新。
8. 结论：证伪失败（字段语义与名字不符、与二进制无绑定），判 P-PROVED，P2；附带项 P3：
   写失败被 except: pass 完全吞掉（比 P-05-05 更彻底，连警告都没有）。

**建议修复方向**：把 运行时.json 明确定位为"打包记录"（改字段名或加 note 说明），
或按 C4 补一个与二进制真正绑定的标识（dist 内文件的 mtime / 构建日志摘要），并给 build_game 一个只告警不阻断的一致性检查；
写失败至少打印一行警告。
**修复必须保持的契约**：C2、C4；zip 内路径 Loom/player_runtime/运行时.json 不得改名（否则新旧包不同构）。
**波及调用方**：tools/package_engine.py、Loom/build_game.py（若启用一致性检查）、docs/handoff §3.2/§6.2。
### 2.13 P-05-13 · 不存在"版本单一事实源"：源码元数据从不被工具链更新 [P-PROVED / P2 / 已有]

**反手（证伪）**

1. 判定基准：C16 只要求"三处手抄一致"，若把一致性责任完全交给操作者且文档已写明，则工具无缺陷。
2. 代码证据：
   - Loom/解释器.json:3 version = 0.1.0.beta2（HEAD；git show f53a82a 亦为 beta2）
   - tools/package_engine.py:180-192 只写 **tmp_dir 里的副本**（_meta_dst = tmp_dir/Loom/解释器.json），从不写回 META_PATH（源码）
   - 探针实测：make_zip 跑完后源文件仍是 0.1.0.beta2
   - 另一个"与 解释器.json 同步"的契约声称：Loom/plugin_loader.py:66
     CURRENT_VERSION = '1.0.0'   # 与 解释器.json 同步 (合同第九节) —— 而 解释器.json 是 0.1.0.beta2，两者在 HEAD 已不一致
3. 路径枚举（谁会读 解释器.json 的 version）：
   - 路径 1 LoomHub 安装/登记（discover_interpreter → 目录名/台账）→ 读的是**包内副本**（已被回写，正确）
   - 路径 2 package_engine 缺省版本（load_version）→ 读**源码原文**（0.1.0.beta2，与最新发布无关）
   - 路径 3 plugin_loader 的 CURRENT_VERSION → 硬编码常量，不是读文件（作者注释声称"同步"，实际是手抄）
   - 路径 4 引擎运行时 → 无读取（grep 全仓库，解释器.json 只有 LoomHub 与 tools 两处消费）
4. 实际行为：发过 beta3/beta4 之后，源码元数据仍停在 beta2，且没有任何机制会更新它。
5. 差异：C16 的三处一致靠人脑维持；C9 的"唯一接缝"也不覆盖版本号来源。
6. 触发条件：任何一次"忘记带 --version"的打包（见 P-05-07 组合 2）；或读 plugin_loader 注释被误导去对照 解释器.json。
7. 验证：

       $ python Loom\tests\_tmp\beta3_scan_05_makezip.py
       === 用例 2: 有预置运行时 + 正常元数据 ===
       [探针] 包内 解释器.json version : 0.1.0.beta3   文件名版本: 0.1.0.beta3
       [探针] 源文件 Loom/解释器.json 是否被改写 : 0.1.0.beta2
       基线与 HEAD 对照：
       $ git show f53a82a:"Loom/解释器.json" | findstr version   ->  "version": "0.1.0.beta2"
       $ type Loom\解释器.json | findstr version                 ->  "version": "0.1.0.beta2"
8. 结论：证伪失败（发过两个版本后源码仍停在 beta2，且 plugin_loader 的同步声明已失真），判 P-PROVED，P2。

**建议修复方向**：确立一个事实源并在打包时**回写**（收进 VCS 变更，让版本号在 git 里可见），
或反之——把 解释器.json 明确定义为"运行期元数据、由打包注入"，同时让 package_engine 的缺省版本不再依赖它；
并把 plugin_loader.py:66 的注释与真实关系（或改成读文件）对齐。
**修复必须保持的契约**：C1、C17；解释器.json 的字段集合（name/version/python_version/main/main_exe/description）
是 LoomHub 的导入契约，不得增删必需项。
**波及调用方**：package_engine.load_version、release_github 的缺省版本、plugin_loader 的 min_engine 比较（:109-119）、docs/handoff §10 自检清单第 2 条。

---

### 2.14 P-05-14 · installer.iss 是生成物却被入库；--version 不回写 版本.json，LoomHub 自身版本元数据与安装器脱节 [P-PROVED / P2 / 已有]

**反手（证伪）**

1. 判定基准：installer.iss 第 1 行自称"由 package_hub.py 自动生成"，若它每次构建都被重写并提交，入库只是"快照"，无害。
2. 代码证据：
   - tools/package_hub.py:96-146 ISS_TEMPLATE + write_iss(version)：每次运行都用 --version 覆盖 tools/installer.iss
   - tools/package_hub.py:18,23-31 load_version：版本来自 LoomHub/版本.json（不存在则以 0.1.0 新建），
     **不回写** 版本.json；本轮 a732ee9 改的是 installer.iss:3 的字面值 0.1.1
   - LoomHub/版本.json:2 仍是 "0.1.0"（全仓库 grep 版本.json 只有 package_hub.py 一处引用）
   - tools/release_github.py:18 HUB_VERSION 缺省 0.1.1
3. 路径枚举（"LoomHub 版本"的 4 个来源）：
   - 来源 1 版本.json = 0.1.0
   - 来源 2 installer.iss:3 = 0.1.1（本轮改）
   - 来源 3 产物名 LoomHub-<iss版本>-Setup.exe
   - 来源 4 release_github 的 HUB_VERSION 缺省 = 0.1.1
   来源 1 与其余三者矛盾。
4. 实际行为：重新执行 python tools\package_hub.py（不带 --version）→ installer.iss 被改回 0.1.0、
   产物变 LoomHub-0.1.0-Setup.exe，而 release_github 仍去找 0.1.1 → 又落到 P-05-07 的"空 release"路径。
5. 差异：引擎侧刚修掉的"只有文件名变、元数据没变"（C1 的动机）在 Hub 侧以对称形式仍然存在。
6. 触发条件：任何一次不带 --version 的 Hub 重打包。
7. 验证：

       $ type LoomHub\版本.json
       {
         "version": "0.1.0"
       }
       $ findstr MyAppVersion tools\installer.iss
       #define MyAppVersion "0.1.1"
       $ python -c "import ...; print(open('tools/package_hub.py').read().count('版本.json'))"  -> 1 处（仅 VERSION_FILE 定义）
       本轮 diff（a732ee9）：tools/installer.iss  1 +-   （#define MyAppVersion "0.1.0" -> "0.1.1"）
8. 结论：证伪失败（四个来源里有一个永远落后，且生成物与推导脚本同时入库），判 P-PROVED，P2。

**建议修复方向**：让 package_hub 把 --version 回写到 版本.json（与 package_engine 对 解释器.json 的做法对齐），
并把 installer.iss 从版本库移除或标记为生成物（构建时覆盖、比对前后差异）；
release_github 的 HUB_VERSION 缺省应改读同一个事实源。
**修复必须保持的契约**：安装器 AppId（{8D2B5F1A-...}）不得变（否则升级会装成旁装）；
OutputBaseFilename 必须是 LoomHub-<version>-Setup；package_hub --skip-exe 流程继续可用。
**波及调用方**：tools/release_github.py:26-28,245-256；docs/handoff §3.1/§3.5；LoomHub 的"关于"信息（若将来读版本.json）。

---

### 2.15 P-05-15 · USER_AGENT 未参数化 [P-PROVED / P3 / 已有]

**反手（证伪）**

1. 判定基准：C16 只把 LOOM_ENGINE_VERSION / LOOM_HUB_VERSION 列为参数化对象，未提 UA；若 UA 不影响任何行为则可跳过。
2. 代码证据：tools/release_github.py:15 USER_AGENT = 'LoomHub-Release/0.1.0'（本轮把相邻两行改成 env 可配，UA 留在原处）。
3. 路径枚举：UA 只出现在 _req 的 add_header（:57），无分支依赖其内容。
4. 实际行为：发 0.1.0.beta3 时 UA 仍自称 0.1.0。
5. 差异：与"发布工具参数化"的意图不一致，GitHub 侧审计日志/滥用排查会看到过期客户端标识。
6. 触发条件：任何人查 release 上传的 UA 记录。
7. 验证：grep USER_AGENT 只有 :15 定义与 :57 使用，无版本派生。
8. 结论：证伪失败（确实是漏参数化），判 P-PROVED，P3（纯可维护性/可观测性）。

**建议修复方向**：由 ENGINE_VERSION/HUB_VERSION 派生 UA，或改为固定工具名（去掉版本号）以避免长期失真。
**修复必须保持的契约**：无（UA 不得为空，GitHub API 要求有 UA）。
**波及调用方**：无。

---

### 2.16 P-05-16 · 332MB 资产一次性读入内存，7200s 超时下的内存峰值未评估 [P-UNKNOWN / P3]

**反手（证伪）**

1. 判定基准：代码本身无内存预算契约（白盒层未定义 Resource 边界），标准库行为也不保证流式上传。
2. 代码证据：tools/release_github.py:153-157

       with open(file_path, 'rb') as f:
           data = f.read()                 # 332 MB 字节串常驻
       s, b = _req(upload_url, token, method='POST', data=data, ... timeout=7200)

3. 路径枚举：单条路径（无分支）。实测本机内存充足（本次审计环境），未触发失败。
4. 实际行为：进程常驻 332MB 字节串 + urllib 内部缓冲，峰值未知。
5. 差异：无法在当前环境证明"会 OOM"，也无法证明"不会"。
6. 触发条件：可用内存 < 约 1GB 的机器/CI（332MB 资产 + 解释器 + 系统）。
7. 验证（已尝试的探针/还缺什么）：
   - 已做：代码路径确认、资产实际大小 348,764,749 B（探针 zip.py）。
   - 缺：需要一台可用内存受控（如 512MB/1GB 容器）的机器跑一次真实/模拟上传，采 Peak Working Set。
     本沙箱无法创建内存受限环境，故不升级为 PROVED。
8. 结论：判 **P-UNKNOWN**，P3。**还不能定的原因**：缺少"内存受限环境下的峰值测量"这一条信息。
   建议下一步探针：在 Windows 用 Start-Process + Get-Process PeakWorkingSet64 跑一次本地假 API 上传（P-05-08 的假服务器可直接复用）。

**建议修复方向（待定）**：若探针显示峰值过高，改为流式上传（分块读取 + Content-Length 头）或调用外部 curl。
**修复必须保持的契约**：C14（_req 返回元组形状）、asset 名称与 Content-Type。
**波及调用方**：upload_asset 的 engine/hub 两条调用。

---

### 2.17 P-05-17 · Loom/.gitignore 第 49 行是死模式 [P-PROVED / P3 / REGRESSION]

**反手（证伪）**

1. 判定基准：只要"player_runtime 目录被忽略"这一效果成立，写几行都算达成目的（行为正确）。
2. 代码证据：Loom/.gitignore:48-50

       # 预编译播放器运行时 (随引擎包分发, 不入库; 由 package_engine.py 打入 zip)
       Loom/player_runtime/
       player_runtime/

   该 .gitignore 位于 Loom/ 下，故第 49 行的 Loom/player_runtime/ 实际匹配的是 <repo>/Loom/Loom/player_runtime/。
3. 路径枚举：两种路径各查一次生效规则（git check-ignore -v）。
4. 实际行为：目标路径由第 50 行的 player_runtime/ 命中，第 49 行永不命中。
5. 差异：两条同义规则并存，其中一条无效；若有人日后删掉第 50 行"重复项"会立刻失去保护（隐性耦合）。
6. 触发条件：代码审查/清理误删第 50 行。
7. 验证：

       $ git check-ignore -v "Loom/player_runtime/game_player.dist/MyGame.exe"
       Loom/.gitignore:50:player_runtime/	Loom/player_runtime/game_player.dist/MyGame.exe
       （命中第 50 行，不是第 49 行）
8. 结论：证伪失败（第 49 行是死规则），判 P-PROVED，P3。

**建议修复方向**：删掉第 49 行只留通用模式（或反之），并在注释里写明"本文件位于 Loom/，路径相对该目录"。
**修复必须保持的契约**：player_runtime 必须继续被忽略（否则 96.7MB 会进版本库）；tests/_tmp 的 e2e 例外必须继续生效
（实测 git check-ignore -v Loom/tests/_tmp/e2e_mcp_full.py 无输出 = 未被忽略）。
**波及调用方**：package_engine（依赖该目录"不入库但存在"）。

---

### 2.18 P-05-18 · 无关文件被无条件打进发布包（量级小，但属于"包内容不可控"）[P-PROVED / P3 / 已有]

**反手（证伪）**

1. 判定基准：EXCLUDE_DIRS 只承诺排除 tests/保存/Projects/assets/__pycache__ 等；文档未承诺"包内只有引擎源码"。
2. 代码证据：tools/package_engine.py:22-26 的排除集 + collect_files:36-50 的白名单式过滤（只按目录名/扩展名）。
3. 路径枚举：collect_files 的过滤只有三种（目录名 ∈ EXCLUDE_DIRS、目录名以 . 开头、扩展名 ∈ EXCLUDE_EXTS），
   没有"白名单目录"式约束，因此引擎目录下任何新增杂项目录都会被收进去。
4. 实际行为：把 %SystemDrive%/…/SogouInput/*.bin（两个 172152 B）、压测500混合.json（0.33MB）、
   _cacert.pem（0.27MB）、AI工作排查笔记/ 等收进包内。
5. 差异：C2 只关心"运行时在不在"，没有"包内容应只含运行所需文件"的明示契约，故这是 TOOL-SCOPE（范围）问题而非功能错误。
6. 触发条件：每次打包。
7. 验证：

       $ python Loom\tests\_tmp\beta3_scan_05_pack.py
       2) 收集到引擎文件数 = 230  合计 5.36 MB
          %SystemDrive%             2      0.33 MB
          压测500混合.json          1      0.33 MB
          _cacert.pem               1      0.27 MB
          AI工作排查笔记             1      0.01 MB
          Loom/tests 条目数 = 0（真实 beta3 zip 复核，探针 zip.py）
8. 结论：证伪失败（确实把无关文件打进去），判 P-PROVED，P3。
   量级结论：无关内容合计约 0.94MB / 5.36MB 引擎载荷，占整包（332MB）约 0.3%，
   **不构成"包体暴涨"**；包体从 beta2 的 298.10MB 涨到 beta3 的 332.61MB，增幅 34.5MB 主要来自
   python/ 依赖与 96.70MB 运行时（与上一版 0 运行时相比的另一笔账见 P-05-23）。

**建议修复方向**：把"打包内容"从黑名单改为白名单（引擎根下的 *.py + 明确目录清单），
或至少把 %SystemDrive%、压测/bench 产物、笔记类目录加进排除集并写测试固定住。
**修复必须保持的契约**：C2（运行时与 wgpu/core_components/ckernels/plugins/scripts/ui/GUI 必须在包内）。
**波及调用方**：无（只影响包内容）。

---

### 2.19 P-05-19 · wgpu 资源与 DLL：硬编码路径在非开发机是否失效 [P-DISPROVED]

**反手（证伪：证明"这里没有 bug"）**

1. 判定基准：本轮注释声称"wgpu(Vulkan) 需要 resources/combined_header.h 等数据文件，旧构建没带 -> 打包版 Vulkan 初始化失败"，
   以及"wgpu-native 的 DLL 不是 package-data，必须显式带进 dist"（build_game.py:87-101）。
   若 DLL 其实已随 wheel 分发、或路径由 import 推导而非写死，则该风险不成立。
2. 代码证据：build_game.py:96-104

       try:
           import wgpu as _wgpu
           _dll = os.path.join(os.path.dirname(_wgpu.__file__), 'resources', 'wgpu_native-release.dll')
           if os.path.isfile(_dll):
               cmd.append('--include-data-files=%s=wgpu/resources/wgpu_native-release.dll' % _dll)
       except Exception as _e:
           print('警告: 未包含 wgpu-native DLL (%r)' % (_e,))

   路径由 **import 结果**推导，不是写死的盘符/绝对路径。
3. 路径枚举：
   - 路径 1 构建解释器里装了 wgpu 且 resources/wgpu_native-release.dll 存在 → 显式带上（本机现状）
   - 路径 2 构建解释器里装了 wgpu 但 DLL 不存在 → 警告后继续；此时 --include-package-data=wgpu 仍会带包内数据文件
   - 路径 3 wgpu 未安装 → 同上警告；此时 Nuitka 的 --include-package-data=wgpu 也会失败/告警，无法产生可用 Vulkan 运行时（用户本来就没装依赖）
4. 实际行为（三重实测）：
   a) wgpu 安装位置与 DLL 存在性；
   b) wheel 的 RECORD 里包含 wgpu/resources/wgpu_native-release.dll —— 即**它本来就是 package-data**；
   c) 真实 dist 里 wgpu/resources 同时含 combined_header.h / webgpu.h / webgpu.idl / wgpu.h / wgpu_native-release.dll。
5. 差异：无（"非开发机失效"不成立）。
6. 触发条件：无（路径不可写死，随安装位置变化）。
7. 验证：

       $ python -c "import wgpu, os; d=os.path.dirname(wgpu.__file__); ..."
       wgpu 0.32.0 C:\Users\Administrator\AppData\Local\Programs\Python\Python312\Lib\site-packages\wgpu
       resources dir exists: True
       ['__init__.py', '__pycache__', 'codegen_report.md', 'combined_header.h', 'webgpu.h', 'webgpu.idl', 'wgpu.h', 'wgpu_native-release.dll']
       dll exists: True 9117696
       wgpu_native module spec: False          <- 注意：wgpu_native 不是已安装的包
       wgpu wheel RECORD resources entries:
         ['wgpu/resources/__init__.py', ..., 'wgpu/resources/combined_header.h', 'wgpu/resources/webgpu.h',
          'wgpu/resources/webgpu.idl', 'wgpu/resources/wgpu.h', 'wgpu/resources/wgpu_native-release.dll']
       dist 复核（Loom\player_runtime\game_player.dist\wgpu\resources）：
         2002   codegen_report.md
         108249 combined_header.h
         259569 webgpu.h
         38566  webgpu.idl
         9117696 wgpu_native-release.dll
         55926  wgpu.h
       Test-Path ...\wgpu_native -> False
8. 结论（证伪成功）：**P-DISPROVED**。硬编码路径风险不存在（路径由 import 推导）；
   DLL 亦随 wheel 作为 package-data 分发，故"必须显式带"的注释与事实不符（显式带上无害，属重复保险）。
   证真链无法构造失败复现（我尝试的解释器缺 wgpu 场景，其后果是"整个 Vulkan 后端不可用"，与本项宣称的"路径在非开发机失效"不同因）。
   **另一处附带发现（P3，AUDIT-DEADCODE）**：build_game.py:89 的 --include-package-data=wgpu_native 指向一个
   **不存在的包**（find_spec('wgpu_native') 为 None，dist 里也没有 wgpu_native 目录），是无效旗标；
   它未导致构建失败（本机 dist 构建成功且含全部 wgpu 数据），因此只是噪音。

**建议修复方向（P3 级）**：删掉无效的 wgpu_native 旗标，或改为真实存在的包名；
把"必须显式带 DLL"的注释改成事实描述（wheel 已含，显式带属兜底）。
**修复必须保持的契约**：Vulkan 在打包版可用（dist 内必须同时存在 wgpu/resources/wgpu_native-release.dll 与 combined_header.h）。
**波及调用方**：--build-runtime 流程（引擎开发机 6-10 分钟），以及任何 CI 复现脚本。

---

### 2.20 P-05-20 · 删掉 interpreters.json 里 beta1/beta2 条目是否破坏 LoomHub 解释器台账 [P-DISPROVED]

**反手（证伪：证明"删了也没事"）**

1. 判定基准：C13 —— 台账是"已登记的解释器列表"，scan_install_root 可从 C:\Program Files\Loom 重建。
2. 代码证据：
   - hub_config.py:158-171 scan_install_root：遍历安装根，逐个 discover_interpreter
   - hub_controller.py:102-111 scan_interpreters：把扫描结果全部 add_interpreter（同 dir 覆盖）
   - hub_config.py:186-188 add_interpreter 以 dir 为 key 覆盖；:210-214 remove_interpreter 只按 dir 过滤
   - 台账文件位置：hub_config.py:53 INTERPRETERS_FILE = HUB_DIR/interpreters.json（**源码目录**，不是安装产物）
   - package_hub.py:48-92 PyInstaller 命令只传 --paths/--hidden-import，**未把 interpreters.json 作为数据文件打入**
     （实测 tools/build_hub/LoomHub 顶层只有 _internal 与 LoomHub.exe）
3. 路径枚举（谁读台账）：
   - 路径 1 LoomHub GUI 列表/默认解释器（load_interpreters）→ 条目变少只影响"列表里少两个已卸载版本"
   - 路径 2 卸载/移除（remove_interpreter + rmtree）→ 只对**列表里存在**的条目可用；删条目后若要删磁盘，
     需先扫描重新登记（可恢复）
   - 路径 3 发行物 → 该文件不随 LoomHub 安装包分发（PyInstaller 未收集），用户侧不受影响
4. 实际行为：本次删除只影响开发机台账；被删的两条指向 C:\Program Files\Loom\0.1.0.beta1|beta2，已不在盘上。
5. 差异：无功能破坏。
6. 触发条件：无。
7. 验证：

       $ python -c "…读取 interpreters.json…"    → 14 行、1 条（version 1.0.0，指向工作区 Loom）
       $ Get-ChildItem tools\build_hub\LoomHub  → _internal, LoomHub.exe（无 interpreters.json）
       hub_config.py:10/53/158-171/186/210-214 代码路径如上
8. 结论（证伪成功）：**P-DISPROVED**——删 20 行不破坏安装/卸载台账能力，且不进入发行物。
   **但登记两个附带事实（P3，DESIGN-DRIFT）**：
   (a) 该文件是**机器相关的运行期状态**却被 git 追踪，任何一次运行 LoomHub 都会把它改脏；
       Loom/tests/test_hub.py:70-76 的注释记录了"历史测试把 %TEMP% 引擎写进真实台账"的事故，正是这个结构性原因。
   (b) 现存条目的 version 字段是 "1.0.0"，与 Loom/解释器.json 的 0.1.0.beta2 不一致 —— 台账版本靠登记当时的元数据快照，
       不会随引擎更新而刷新（这与 P-05-13 同源）。
   建议方向：把 interpreters.json 移出版本库（或改为 *.example.json + .gitignore），
   台账版本改为每次启动对已登记条目做一次轻量"元数据续读"。
   **不得**在本轮修改该文件（只建议）。

---

### 2.21 P-05-21 · 发布说明模板改 {version} 占位是否会 KeyError [P-DISPROVED]

**反手（证伪）**

1. 判定基准：C16 的模板参数化方式；若模板里除 {version} 外还有花括号则该调用会抛 KeyError/ValueError。
2. 代码证据：release_github.py:178-228 两个模板，逐字符检查除 {version} 外无其它花括号；
   调用点 :238 body = ENGINE_BODY.format(version=ENGINE_VERSION)；:252 body = HUB_BODY.format(version=HUB_VERSION)。
3. 路径枚举：engine/hub 两条发布路径，各一次 format 调用。
4. 实际行为：探针真实调用 publish_engine（假 API）成功生成 release（body 未抛异常）。
5. 差异：无。
6. 触发条件：无（当前模板安全）。
7. 验证：

       $ python Loom\tests\_tmp\beta3_scan_05_release.py
       [发布] 创建 GitHub Release: engine-v0.1.0.beta3
       [发布] release 已创建: http://fake/rel/1        <- format() 未抛异常
8. 结论（证伪成功）：**P-DISPROVED**。备注（P3 潜在风险）：str.format 对模板里的任何字面花括号都敏感，
   将来若在发布说明里写 JSON/代码片段（例如 {'a': 1}）会让发布在最后一步崩掉；
   改模板时须同步检查这一点（或改用 replace 占位策略）。此项不构成本轮缺陷。

---

### 2.22 P-05-22 · token 读取链路是否可能"用错账号仍能发布" [P-DISPROVED]

**反手（证伪）**

1. 判定基准：C14 之外，发布流程自身有 check_token（release_github.py:74-94）。
2. 代码证据：get_token（:35-51）优先 GITHUB_TOKEN，否则 git credential fill；
   check_token 依次校验 /user（401 拦截）与 /repos/{owner}/{name} 的 permissions.push（无 push 直接 False → exit 1）。
3. 路径枚举：
   - 路径 1 有 GITHUB_TOKEN → 用它，仍过 check_token（含 push 权限）
   - 路径 2 无 env → git credential fill 取到某账号 token，仍过 check_token
   - 路径 3 取不到 token → 打印错误 + exit 1
4. 实际行为：任何路径都要求"该 token 对 WeaveEngine 有 push 权限"，账号身份不匹配但权限足够时仍可发布（这正是授权模型的本意）。
5. 差异：无（不存在"错误账号造成错误版本"的链路，版本号来自 env/缺省，与账号无关）。
6. 触发条件：无。
7. 验证：代码路径逐条核对（:74-94 的三个 return False 分支 + :270 的 exit 1）；假 API 探针中 check_token 也走通（/user → 200，/repos → 200 push=True）。
8. 结论（证伪成功）：**P-DISPROVED**。

---

### 2.23 P-05-23 · 预置运行时 + 排除规则是否导致包体暴涨或漏排除大文件 [P-DISPROVED]

**反手（证伪）**

1. 判定基准：C2 + 本轮注释"排除 .build 中间产物/发布/tests/Projects/assets"。
2. 代码证据：package_engine.py:22-26（EXCLUDE_DIRS 含 'assets','player_runtime','发布'；
   collect_files:39-40 还排除以 . 开头的目录 → .build 天然排除；EXCLUDE_EXTS 含 .pyc/.log/.tmp）。
3. 路径枚举：collect_files 会走到的每一层目录都过 dirnames 过滤；player_runtime 只在 make_zip 里被判空后显式拷贝 dist。
4. 实际行为：探针用例 2 在假引擎树里同时放了 game_player.dist、game_player.build、发布/MyGame 三样，
   zip 条目里只有 .dist（build 与 发布 均未进包）。
5. 差异：无漏排除；包体变化来自运行时本身（96.70MB），不是中间产物。
6. 触发条件：无。
7. 验证：

       $ python Loom\tests\_tmp\beta3_scan_05_makezip.py
       === 用例 2: 有预置运行时 + 正常元数据 ===
       [探针] zip 条目: 8
       [探针] 含 player_runtime/game_player.dist/MyGame.exe : True
       [探针] 含 player_runtime/game_player.build (中间产物) : False
       [探针] 含 发布/ (build_game 输出) : False
       真实发布物（探针 zip.py）：
       beta2 zip 298.10 MB / 7834 条目 / player_runtime 条目 0
       beta3 zip 332.61 MB / 7942 条目 / player_runtime 条目 100（96.70 MB）
       Loom/tests 条目数 = 0，Loom/Projects 条目数 = 0
       包体构成实测（探针 beta3_scan_05_zipdiff.py，按顶层目录累计未压缩大小）：
       beta2: python 798.03 MB | Loom/ 2.10 MB | Loom/core_components 2.32 MB | Loom/ui 0.22 MB
       beta3: python 798.15 MB | Loom/player_runtime 96.70 MB | Loom/ 2.41 MB | Loom/core_components 2.32 MB
              | Loom/%SystemDrive% 0.33 MB | Loom/ui 0.23 MB
       -> python/ 未压缩体积两版几乎相同（798.03 -> 798.15 MB），引擎源码只多了 0.31 MB；
          zip 体积 +34.51 MB（298.10 -> 332.61 MB）几乎全部来自 96.70 MB 运行时的压缩后体积（DLL 压缩率高）。
8. 结论（证伪成功）：**P-DISPROVED**（无漏排除、无中间产物入包、无"包体暴涨"）。
   附带（P3，同 P-05-18）：包内仍含约 0.94MB 无关文件。

---

## 3. 统计

### 3.1 四象限

| 判定 | 数量 | 编号 |
|---|---|---|
| P-PROVED | 17 | 01,02,03,04,05,06,07,08,09,10,11,12,13,14,15,17,18 |
| P-DISPROVED | 5 | 19,20,21,22,23 |
| P-UNKNOWN | 1 | 16 |
| P-CONTRADICTION | 0 | — |
| 合计（疑似项） | 23 | 另：跳过登记 8 项（SKIP-05-01..08） |

### 3.2 等级分布（仅 PROVED）

| 等级 | 数量 | 编号 | 含义 |
|---|---|---|---|
| P0 | 0 | — | 无安全/崩溃类 |
| P1 | 3 | 01,04,07 | 发布链闸门失效 / 发布包缺头号特性 / 空 release + 烧 tag |
| P2 | 10 | 02,05,06,08,09,10,11,12,13,14 | 功能错误或契约漂移，有可复现后果 |
| P3 | 4 | 03,15,17,18 | 可维护性 / 死代码 / 包内容范围 |

### 3.3 [REGRESSION]（本轮引入）

| 编号 | 等级 | 一句话 |
|---|---|---|
| P-05-01 | P1 | 追加 --agent 打破 Loom/tests/test_hub.py 3 条既有断言（实测 exit 1） |
| P-05-02 | P2 | mode=None 的"纯启动编辑器"不带 --agent，与 C8 目标不一致 |
| P-05-03 | P2→P3 | 命令层二次追加 --agent，出现两个 --agent；agent 开关在 open 模式失效 |
| P-05-04 | P1 | 新增的"缺运行时只警告"分支让发布包可静默缺失 96.7MB 运行时 |
| P-05-05 | P2 | 新增的元数据回写把异常吞成警告，可产出 LoomHub 装不上的 zip |
| P-05-06 | P2 | --version 直接污染包内元数据（基线只影响文件名），非法输入使包不可安装 |
| P-05-12 | P2 | 新增的 运行时.json 字段语义与名字不符，且写失败完全静默 |
| P-05-17 | P3 | .gitignore 新增的 Loom/player_runtime/ 是死模式 |

### 3.4 零值说明（按要求解释）

- **P-CONTRADICTION = 0 的原因**：两个高嫌疑项（P-05-04、P-05-07）在反手链里一度成立
  （"'缺运行时'只是缺一个优化项，不算错误"／"版本不一致属使用者失误"），我在正手链拿到实测证据
  （gitignore 使缺运行时是**缺省状态**；缺省组合即可触发空 release）后推翻反手链，属于正常收束而不是两说并存。
  唯一尝试过"两边都成功"的是 P-05-19：反手成功（wheel 自带 DLL + 路径由 import 推导），正手无法构造复现 → 判 DISPROVED。
- **P-UNKNOWN = 1 的原因**：P-05-16 的判据是"内存峰值会不会超限"，本沙箱无法创建内存受限环境，
  该信息只能由外部机器产出；按协议允许"最多 3 次探针"，我只做了 1 次（代码路径 + 资产实测），
  已写清"还缺什么信息"和下一步探针方案，未擅自升级为 PASS/FAIL。
- **P0 = 0 的原因**：本模块不含安全/崩溃路径；最接近的是 P-05-07（空 release），
  但它不崩、不泄露，破坏的是发布流程的可逆性，按 P1 记。

---

## 4. 修复建议排序（只给方向，不含实现代码；修复动作交人类裁决后由本审计者执行）

### 4.1 先修（P1，均需在下次发版前完成）

| 序 | 编号 | 位置 | 方向 | 必须保持的契约 |
|---|---|---|---|---|
| 1 | P-05-04 | package_engine.py:159-175 | 缺预置运行时 → 失败退出或显式开关；警告分两种成因 | C2、zip 内 dist 布局 |
| 2 | P-05-07 | release_github.py:17-18,231-256 + package_engine.py:29-33 | 发布前资产预检（缺失即零写操作退出非 0）；版本单一事实源 | C15、C16、C17 |
| 3 | P-05-01 | hub_config.py:467 或 tests/test_hub.py:310-320 | 二选一（见 §5 Q1），并补"恰好一个 --agent"断言 | C7、C8 |

### 4.2 次修（P2）

| 序 | 编号 | 方向 |
|---|---|---|
| 4 | P-05-05+P-05-06 | package_engine 收尾前自检：从 zip 读回元数据过 validate_meta（兑现 C9），失败即失败；--version 走同一白名单 |
| 5 | P-05-09 | 在线安装下载后比对 tag 版本与包内元数据版本；发布侧 upload 前比对资产名与元数据版本 |
| 6 | P-05-08 | create_release 遇 422 → GET 复用该 release 对象，令"删同名 asset 再传"成为可达路径 |
| 7 | P-05-10+P-05-11 | _resolve_runtime 两分支共用归一化；"目录在但无可用 dist"与"目录不存在"合并为同一失败 |
| 8 | P-05-02 | --agent 判定改为"非播放模式"，或反向修 C7 文档，二者与 §5 Q1 一并定 |
| 9 | P-05-13+P-05-14 | 单点版本事实源；package_hub 回写 版本.json；iss 移出版本库（或标记生成物） |
| 10 | P-05-12 | 运行时.json 降级为打包记录 / 补与二进制绑定的标识；写失败至少告警 |

### 4.3 收尾（P3）

| 序 | 编号 | 方向 |
|---|---|---|
| 11 | P-05-03 | --agent 只在一层产生 |
| 12 | P-05-18 | 包内容白名单化，排除 %SystemDrive%/bench 产物/笔记 |
| 13 | P-05-17 | 清理 .gitignore 死模式（保留 player_runtime 忽略） |
| 14 | P-05-15 | USER_AGENT 参数化或去掉版本号 |
| 15 | P-05-20（附带） | interpreters.json 移出版本库 + 台账版本续读 |
| 16 | P-05-19（附带） | 删除无效的 --include-package-data=wgpu_native；修正"必须显式带 DLL"的注释 |

### 4.4 动手前需确认的点（路线分叉，人类拍板；其余按表中推荐默认执行）

| 序 | 分叉 | 选项 A | 选项 B | 若不确认的后果 |
|---|---|---|---|---|
| D1 | --agent 归谁决定 | 改测试断言（配置层继续负责） | 移到调用方（保住 build_launch_command 纯拼装语义） | 两条路都能通过测试，但选中途再改会二次打破闸门 |
| D2 | 缺运行时是否致命 | 直接失败退出 | 保留但需显式 --allow-missing-runtime | 影响"无编译器机器打包"的可用性承诺表述 |
| D3 | 版本事实源放哪 | 回写 Loom/解释器.json（版本号进 git 可见） | 新增独立 version 文件，解释器.json 退化为运行期元数据 | 决定 P-05-13/P-05-14/P-05-07 三处改动是否共享一个实现 |
| D4 | 预检失败时的副作用边界 | 允许已建 release 保留（仅不再推 tag） | 尽量零写操作（先预检再建任何远端对象） | 决定一次失败要人工清理多少东西 |

---

## 5. 需要人类裁决的封闭问题

**Q1（--agent 的归属与测试口径）**
现状：build_launch_command 在 mode='open' 时追加 --agent，导致 Loom/tests/test_hub.py 3 条断言失败。
请裁决：
- A. 保留配置层追加，改测试断言为期望含 --agent（配置层是"所有 LoomHub 打开的编辑器"的唯一入口，语义最省事）；
- B. 把追加移到调用方（hub_controller.open_project / hub_commands.launch_spec），build_launch_command 恢复"纯拼装、不带隐含行为"，
  测试保持原样。
两项代价：A 改动最小但把"隐含行为"留在被单测覆盖的纯函数里；B 语义最干净，但要同时改 2 个调用方并新增一条断言。

**Q2（缺预置运行时的失败策略）**
现状：未找到 player_runtime/game_player.dist 时只打印警告，仍然产出与正式包同名的 zip。
请裁决：
- A. 直接失败退出（发布包天然必须带运行时，符合 C2 的"零编译器"承诺）；
- B. 保留可产包，但必须显式传 --allow-missing-runtime，且 zip 名与被跳过的特征写进 README/元数据（便于区分"精简调试包"）。
代价：A 会让"只想快速打个瘦包"的调试流程多一步；B 多一个开关与一处文档。

**Q3（版本事实源）**
现状：Loom/解释器.json = 0.1.0.beta2（源码）、release_github 缺省 = 0.1.0.beta3、LoomHub/版本.json = 0.1.0、installer.iss = 0.1.1。
请裁决：
- A. 打包时回写 Loom/解释器.json（版本号进 git，符合 C1 的"文件名/元数据/安装目录一致"），并让 release_github 缺省读它；
- B. 新增一个纯版本文件（如 VERSION）作为唯一来源，解释器.json 明确降级为"打包注入的运行期元数据"（源码里保持占位值）。
代价：A 会让每次发版产生一个"版本号变更"的 git 提交（可审计，但要求发版必须提交工作区）；
B 需要把现有三处读取点都改指向新文件，但源码元数据不再有"看起来是版本号"的误导。

---

## 附：本轮结论可信度自评

- 每条 PROVED 都有可执行命令 + 实测输出，外部可复跑（探针全在 Loom/tests/_tmp/beta3_scan_05_*.py）；
- 反手链均给出路径枚举表，未出现"检查过主要路径"式结论；
- P-DISPROVED 的 5 项都写明了"为什么所有路径都不成立"，其中 2 项（19、23）用真实构建产物验证；
- 唯一 UNKNOWN（P-05-16）保留了明确的"还缺什么信息"，未擅自降级；
- 未引用任何外部标准（PEP/官方最佳实践）作为判据，全部落在本仓库的注释/docstring/handoff/测试上；
- 本轮未修改任何受跟踪文件，未执行 git 写操作。

---

## 6. 第 5 批修复记录（2026-11-08，人类裁决 D1=A/beta4、D2=B、D3=B、D4=A）

> 本节是「修了什么、凭什么说修好了、还剩什么」，供主审复核。只改本批清单内的文件 + 明确指派的
> P-05-10/11（Loom/build_game.py）与版本口径文件（Loom/解释器.json、LoomHub/版本.json）。

### 6.1 逐项状态

| 编号 | 状态 | 改动位置 | 修前 -> 修后（实测） |
|---|---|---|---|
| P-05-04 | **已修**（D2=B） | tools/package_engine.py:157-186 + main() 新增 --allow-missing-runtime | 缺 player_runtime 时：仅警告、exit 0、照常出包 -> **SystemExit 并列出两种成因**；显式 --allow-missing-runtime 才出「精简包」，包内元数据写 distribution=slim / player_runtime=absent，README 增「精简包」段 |
| P-05-05 | **已修** | package_engine.py:190-215 元数据回写去掉 except 吞异常 | 元数据坏 -> 只警告并出装不上的包 -> **SystemExit 且不产出 zip**（探针用例 4） |
| P-05-06 | **已修** | package_engine.py:check_version + _verify_zip | --version 非法原样写进包内 -> **打包前用 hub_config.validate_meta 同款白名单拒收**；收尾再从 zip 读回元数据复验（探针用例 5） |
| P-05-07 | **已修**（D1=A） | release_github.py:17-18, 21-32, require_assets, main() | 缺省 beta3 vs 打包缺省 beta2 -> **两处统一 0.1.0.beta4**；main 先做版本白名单 + 资产前置检查，缺资产时**零远端写**退出 1（实测） |
| P-05-08 | **已修** | release_github.py: find_release_by_tag + create_release(422 复用) + upload_asset(删除分支可达/网络错误分型) | 重跑必 422 硬退、DELETE 分支 0 次命中 -> **失败后连跑三次：第 2 次复用 release 上传成功，第 3 次先 DELETE 同名 asset 再传（DELETE 次数=1）** |
| P-05-10 | **已修** | Loom/build_game.py: _runtime_dist / _resolve_runtime | 只有 .build 残留时静默返回目录（发布夹无 exe）-> **与「目录不存在」同一条 SystemExit** |
| P-05-11 | **已修** | 同上 | --runtime 给 player_runtime 目录仍多套一层 -> **归一化下钻并打印「--runtime 归一化: A -> A/game_player.dist」** |
| P-05-01 | **已修**（D3=B） | hub_config.py:462-468 删 --agent 追加；hub_controller.py:459-463 追加一次 | test_hub.py 3 FAIL/exit1 -> **ALL PASS/exit0**；新增「纯拼装不带 --agent」「调用方恰好一个 --agent」两条断言 |
| P-05-02 | **已修**（D3=B） | 同上 | mode=None 缺 Agent 桥的语义矛盾随「职责上移」消失（拼装层不再产生 --agent） |
| P-05-03 | **已修** | hub_config 删除追加后，hub_commands 的 as_bool(agent) 恢复为唯一决定点 | 两个 --agent -> 至多一个 |
| P-05-13 / P-05-14 | **已修**（D1 口径） | Loom/解释器.json -> 0.1.0.beta4；LoomHub/版本.json -> **0.1.2**（2026-11-08 因 Hub 配置体系改动而升版，见 README 零节） | 新增 Loom/tests/test_release_version.py 锁定：源码元数据 = package_engine.load_version() = release_github 缺省 = zip 名 = tag 派生；版本.json = HUB_VERSION = installer.iss MyAppVersion |
| Hub 配置落用户目录 | **部分完成** | hub_config.py 新增 DEFAULT_HUB_SETTINGS / hub_settings_template / hub_settings_file / load_hub_settings / save_hub_settings / hub_settings_delta | 新增断言：设置落 LOOM_USER_ROOT 下、{schema,values} 格式、只写 delta、模板字节不变 —— **但见 6.3 遗留 1** |
| 卸载器选项 | **已修** | tools/installer.iss 新增 [Code] CurUninstallStepChanged | 询问「是否同时删除 %LOCALAPPDATA%/Loom/hub」，MB_DEFBUTTON2=否（默认不删），静默卸载一律保留；**ISCC 7.1 实编译成功（exit 0）** |
| 发布前测试闸门 | **已修** | release_github.py: run_test_gate + --require-tests（默认关闭） | 缺资产 + --require-tests 时在**跑回归与任何远端写之前**退出 1（实测）；开启后才跑 Loom/tests/run_all.py，非零中止 |
| P-05-12 | 未修（P2） | — | 运行时.json 语义未动（需人类决定字段改名 / 加源码哈希）；仍在遗留清单 |
| P-05-15 / 17 / 18 / 16 | 未修（P3/UNKNOWN） | — | 与本批缺陷无耦合，未顺手改（符合「只改本批缺陷」） |

### 6.2 本轮跑过的定向验证（全部实跑）

    python tests/test_hub.py              -> ALL PASS, exit 0（修前 3 FAIL / exit 1）
    python tests/test_hub_eai.py          -> ALL PASS, exit 0
    python tests/test_hub_controller.py   -> ALL PASS, exit 0
    python tests/test_release_version.py  -> 20 条断言 ALL PASS, exit 0（新增）
    python tests/test_eai_real.py         -> ALL PASS, exit 0，命令 98 条全部覆盖
    ISCC.exe tools/installer.iss          -> Successful compile (15.6s)
    Loom/tests/_tmp/beta3_scan_05_gate.py      -> 缺运行时失败 / 精简包标记 / 正常包自检 / 坏元数据失败 / 非法版本拒收 全部符合预期
    Loom/tests/_tmp/beta3_scan_05_idem.py      -> 失败后可重跑；第 3 次 DELETE 同名 asset 后重传（DELETE=1）
    Loom/tests/_tmp/beta3_scan_05_runtime2.py  -> A-G 七种布局全部给出预期结果（含两条新的明确错误）

### 6.3 修复过程中新发现（需主审裁决，本轮**未**改）

1. **LoomHub/guiloader.py:100-123 仍把 Hub 设置读写在 <程序目录>/设置.json**（它是 Loom/guiloader.py 的独立副本，未接入 userpaths）。
   hub_config 的收口 API 已就位且有断言，但真正调用它的是 LoomHub/guiloader.py，**不在本批文件清单内**，
   于是「装到 Program Files -> 设置改了没保存/一重启就丢」这条攻击面仍在。
   建议：由 guiloader 属主把 load_settings('loomhub') / save_settings('loomhub') 委派到
   hub_config.load_hub_settings / save_hub_settings（1 行级改动），我再补一条「经由 guiloader 也不落程序目录」的端到端断言。
2. **interpreters.json / projects.json 仍写在 LoomHub 程序目录**（hub_config.save_json_atomic 的默认落点）。
   契约 §2 只规范了「设置」，但装到 Program Files 时这两份台账同样不可写 —— 同一根因的未覆盖面。
   若决定一起搬，需同步 Loom/tests/test_hub.py 的落点断言与 LoomHub 侧的迁移逻辑。
3. **tools/installer.iss 是 package_hub.py 的生成物却入库**（P-05-14 的一半）：本轮只同步了版本号与 [Code]，
   真正的收敛（移出版本库或构建期比对）仍需裁决。
4. **构建产物副作用**：为验证 [Code] 语法跑了 ISCC，重新生成了 tools/dist/LoomHub-0.1.1-Setup.exe（gitignored，非受跟踪文件）。
   正式发版仍应走 python tools/package_hub.py --version 0.1.1 重新打包。
5. Loom/tests/run_all.py 目前仍有多处红（其他批次），因此 --require-tests 默认关闭；等主审清零后再改默认值。

### 6.4 复现口径

所有断言都可用上述命令原样复跑；探针均为一次性脚本（Loom/tests/_tmp/beta3_scan_05_*.py，被 .gitignore 忽略），不参与产品行为。

---

## 7. 第 5b 批修复记录：LoomHub 侧配置与台账全部搬进用户目录（2026-11-08）

> 人类裁决：「所有配置类文件（包括 LoomHub 的）应该都要这么处理，之前没想到普通用户运行的问题，现在全部补上」。
> 本轮把 6.3 遗留 1、2 两项做完（原报告 P-05-20 的结论需修正：台账里「删条目不破坏功能」成立，
> 但**落点**在 Program Files 下不可写，属同一根因的未覆盖面，现已迁移）。

### 7.1 改动清单

| 文件 | 性质 | 内容 |
|---|---|---|
| LoomHub/hub_userpaths.py | **新增** | Hub 侧用户目录收口（契约 §2 的 Hub 等价物）：user_root() = LOOM_USER_ROOT > %LOCALAPPDATA%\Loom > ~/.loom；hub_settings() / interpreters() / projects() / log_path() / backup_path() / ensure_dir() / ensure_parent() / safe_name()。规则与 Loom/userpaths.py 一致，落点同为 <root>/hub/（卸载器删 %LOCALAPPDATA%\Loom\hub 即可一次覆盖 Hub 全部配置）。不直接 import Loom/userpaths.py 的原因：安装版 LoomHub 是独立 PyInstaller 包，引擎源码不在其导入路径上（这正是老代码静默退化成写程序目录的根因）。 |
| LoomHub/guiloader.py | 改 | load_settings/save_settings 对 loomhub 且**未给 base=** 时委派 hub_config（模板只读 + 用户层 delta + 旧文件迁移），写失败上抛；base= 保持旧单文件语义供测试注入；settings_path() 保留为「模板/旧位置」并加说明；读失败不再静默（打印原因）。 |
| LoomHub/hub_config.py | 改 | (a) 台账落点默认改到用户目录（default_interpreters_file / default_projects_file），LEGACY_* 保留程序目录旧路径；(b) 首次运行迁移（条目全带、旧文件不动、失败出声）；(c) save_json_atomic 保持「父目录不存在即失败」旧语义，由 save_interpreters/save_projects/_maybe_migrate_ledger 自己 _ensure_parent；(d) 设置侧同样支持旧 设置.json 迁移；(e) _userpaths() 改为优先 hub_userpaths。 |
| Loom/tests/test_hub.py | 改 | 新增 4 个用例：程序目录只读仍可保存、写失败上抛、台账/设置首次迁移、guiloader 委派与 base= 旧语义；模块级 LOOM_USER_ROOT 隔离。 |
| Loom/tests/test_hub_eai.py | 改 | 模块级 LOOM_USER_ROOT 隔离（它会真的 save_settings('loomhub')）。 |
| Loom/tests/test_hub_controller.py | 改 | 同上（部分用例走默认台账路径）。 |

### 7.2 验收证据（实跑）

**验收 1：程序目录只读（icacls deny W,AD）→ 仍能保存且落用户层**

    程序目录: C:\Users\...\Temp\scan_prog_b7d1...
    模板文件: ...\设置.json 存在: True
    [前置] 程序目录不可写（符合预期）: PermissionError 13      <- ACL 确实生效
    读取(合并后): {'gui': 'TkHubView', 'open_py': True}
    保存目标  : C:\Users\...\Temp\scan_user_0ade...\hub\settings.json
    用户层已写: True
    用户层内容: {'schema': 1, 'app': 'loomhub', 'updated_at': '...', 'values': {'open_py': False}}
    模板字节未变: True
    读回 open_py: False

**验收 2：旧 设置.json / interpreters.json / projects.json 首次运行被迁移**

    迁移前旧台账条目: 2 / 旧项目: 1
    [设置] 已把旧设置迁移到用户目录: ...\设置.json -> ...\hub\settings.json（gui）
    迁移后 Settings   : {'gui': 'NovaHubGUI', 'open_py': True} -> 用户层文件: True
    [台账] 已把旧文件迁移到用户目录: ...\interpreters.json -> ...\hub\interpreters.json（2 条）
    [台账] 已把旧文件迁移到用户目录: ...\projects.json -> ...\hub\projects.json（1 条）
    迁移后 解释器条目数: 2  内容版本: ['0.1.0.beta2', '0.1.0.beta3']
    迁移后 项目条目数  : 1  内容: ['PacMan2D']
    旧文件保持不动     : True

**验收 3：既有套件保持全绿 + 真实用户目录未被写**

    test_hub.py               exit=0  FAIL=0
    test_hub_controller.py    exit=0  FAIL=0
    test_hub_eai.py           exit=0  FAIL=0
    test_release_version.py   exit=0  FAIL=0
    %LOCALAPPDATA%\Loom\hub：hub/ 不存在（测试全部隔离到 LOOM_USER_ROOT）

### 7.3 过程中发现并修掉的两个副作用（留痕）

1. **save_json_atomic 一度被我加了 ensure_parent**，导致 test_hub_controller.py 的「坏路径 -> err 不崩」变红
   （写不存在的目录以前失败、现在被自动建目录）。已回退：该函数恢复「父目录不存在即失败」，
   需要建目录的台账路径自己调 _ensure_parent。这条反过来印证：写失败可判定不能靠顺手建目录来软化。
2. **测试污染真实用户配置**：迁移上线后，未隔离的测试会把台账/设置写进 %LOCALAPPDATA%\Loom\hub。
   本轮实测发生过一次（test_hub_controller.py 触发，产生 interpreters.json / projects.json 两个测试产物），
   确认内容为测试数据后删除，并给三个 test_hub* 文件加模块级 os.environ.setdefault('LOOM_USER_ROOT', <tempdir>)；
   复核后真实用户目录不再被写。

### 7.4 仍未做（按主审要求保持原状态）

- P-05-12（运行时.json 语义 / 写失败静默）、P-05-15、P-05-17、P-05-18 维持 P3 未修；P-05-16 维持 P-UNKNOWN。
- --require-tests 维持默认关闭，等主审统一清零后由主审改默认。
- LoomHub/hub_github.py 的 GitHub token 存 %APPDATA%\LoomHub\settings.json：本来就是用户可写目录，
  不属本次「普通用户写不了 Program Files」的病灶，故未动；若要统一到 <root>/hub/ 需另开一批并带 token 迁移。
- LoomHub/interpreters.json / LoomHub/projects.json 仍在版本库里（作为旧台账/迁移源），
  运行时不再写它们（写入都去用户层）；是否移出版本库待裁决。

---

## 8. 第 6 批修复记录：N5 版本事实源漏口（2026-11-08，人类裁决 A）

### 8.1 改动

| 文件 | 内容 |
|---|---|
| tools/package_hub.py | 删掉 DEFAULT_VERSION = '0.1.0' 与整段静默回落/回写逻辑；load_version() 现在只认 LoomHub/版本.json：缺文件 / 缺 version 字段 / 坏 JSON 一律 SystemExit（exit 1）并给出原因与修复提示；--version 覆盖仍生效且**不写回**任何文件。读取异常收窄为 (OSError, ValueError)（IO/权限 + JSON/编码），其余照常上抛。 |
| Loom/tests/test_release_version.py | 新增 t_hub_version_single_source() 12 条断言：真源存在、load_version() == 版本.json、**调用后文件字节与 mtime 均未变**（无隐式回写）、--version 覆盖生效、缺失→SystemExit 且不自动建文件、坏 JSON→SystemExit、缺字段→SystemExit、AST 级断言 DEFAULT_VERSION 不再是任何 Name/Attribute（注释里出现不算）。 |

### 8.2 修前 / 修后对照（探针实跑：Loom/tests/_tmp/beta3_scan_05_n5.py）

    修前（git HEAD 的 package_hub.py，内存里 exec 同一份源码）:
        文件存在?  False
        返回值      : '0.1.0'
        现在文件存在?  True
        被自动写成  : {'version': '0.1.0'}      <- 与 release_github 的 0.1.1 分叉的源头

    修后（工作区）:
        文件存在?  False
        SystemExit 首行: [错误] 缺少版本真源: ...\\版本.json
        SystemExit 次行: 该文件是 LoomHub 版本号的唯一来源 —— release_github 的缺省 HUB_VERSION 与 installer.iss 的 MyAppVersion 都必须与它相等。
        现在文件存在?  False (没有静默回写)

    CLI 级（package_hub.main() 走同一条 load_version）: exit=1

### 8.3 定向套件（实跑）

    python tests/test_release_version.py  exit=0 FAIL=0  (24 条断言)
    python tests/test_hub.py              exit=0 FAIL=0
    python tests/test_hub_eai.py          exit=0 FAIL=0
    python tests/test_hub_controller.py   exit=0 FAIL=0

### 8.4 关于 --require-tests 的状态确认（本轮**未改默认值**）

- 开关已存在且行为正确：tools/release_github.py 的 main() 解析 --require-tests，命中后调用 run_test_gate() →
  Loom/tests/run_all.py，非零即中止；它排在**版本白名单 + 资产前置检查之后、任何远端写操作之前**，
  所以闸门失败时是零远端写（已实测：缺资产场景在跑回归之前就 exit 1）。
- 默认值仍是**关闭**（require_tests = '--require-tests' in argv），按人类裁决由**主审在合并后统一改默认**；
  本轮未改，也未把它接进任何自动化路径。

### 8.5 剩余未解决（与上轮一致）

- P-05-12 / P-05-15 / P-05-17 / P-05-18 维持 P3 未修；P-05-16 维持 P-UNKNOWN。
- --require-tests 默认关闭，待主审切换。

---

## 9. 第 7 批修复记录：release_github 的第二份字面版本值（2026-11-08，独立验收 A 条）

### 9.1 缺陷

tools/release_github.py 的 ENGINE_VERSION/HUB_VERSION 各写了一份缺省**字面值**（工作区当时为
0.1.0.beta4 / 0.1.2），而 LoomHub/版本.json、Loom/解释器.json 才是打包工具的真源 ——
两份字面值之间没有任何交叉校验。独立验收实测：LOOM_HUB_VERSION=9.9.9 时 release 用 9.9.9、
package_hub.load_version() 仍是 0.1.2，两条链静默分叉。
（上一版测试 test_release_version.py 先 pop 了该环境变量，所以测不出来 —— 这正是本轮要补的断言缺口。）

### 9.2 改动（只动 tools/release_github.py + 测试）

| 改动 | 内容 |
|---|---|
| 删除字面值 | 不再有 ENGINE_VERSION = os.environ.get(..., 字面值)；改为 resolve_version(env, _load_true_source_version(what), what) |
| _load_true_source_version(what) | engine → package_engine.load_version()（读 Loom/解释器.json）；hub → package_hub.load_version()（读 LoomHub/版本.json）。两者都是**纯读取**（N5 之后已无回写）；读失败即 SystemExit(1) |
| resolve_version(env_name, source_value, what) | 环境变量只用于**确认同一版本**：为空 → 用真源；等于真源 → 通过；不等 → SystemExit，消息写明「版本号只有一个真源：引擎 = Loom/解释器.json，LoomHub = LoomHub/版本.json；要么改真源，要么删掉环境变量」 |
| import 路径 | 模块顶部把 tools/ 加进 sys.path，保证 import package_engine / package_hub 在命令行与测试两种入口下都成立 |

### 9.3 修前 / 修后（探针实跑：Loom/tests/_tmp/beta3_scan_05_versrc.py）

    修前（git HEAD 的 release_github.py，内存 exec；机制同上一版，只是字面值不同）:
      LOOM_HUB_VERSION=9.9.9
      release_github.HUB_VERSION = 9.9.9
      package_hub.load_version()  = 0.1.2      <- 两条链分叉
      是否报错/退出: 否（静默使用环境变量）

    修后（工作区）:
      同一进程内默认值: ENGINE_VERSION='0.1.0.beta4'  HUB_VERSION='0.1.2'
      真源值          : 解释器.json='0.1.0.beta4'   版本.json='0.1.2'
      子进程 import (LOOM_HUB_VERSION=9.9.9) -> returncode = 1
      [错误] 版本号分叉：环境变量 LOOM_HUB_VERSION='9.9.9' 与真源值 '0.1.2' 不一致（hub 侧）。
      一致时 (LOOM_HUB_VERSION=真源值) -> returncode = 0  HUB_VERSION = 0.1.2

    git diff 中被删掉的两行字面值（HEAD 版）:
      -ENGINE_VERSION = os.environ.get('LOOM_ENGINE_VERSION', '0.1.0.beta3')
      -HUB_VERSION = os.environ.get('LOOM_HUB_VERSION', '0.1.1')

### 9.4 新增断言（test_release_version.py · t_version_env_crosscheck，9 条）

1. 缺省 HUB_VERSION == LoomHub/版本.json；2. 缺省 ENGINE_VERSION == Loom/解释器.json；
3. 无环境变量 → 返回真源；4. 环境变量 == 真源 → 通过（仅确认）；
5. LOOM_HUB_VERSION=9.9.9 → 报错退出（消息含「分叉」）；6. 引擎侧同理；
7-8. 子进程 import release_github 在上述两种分叉下 returncode != 0（端到端证据，不依赖进程内状态）；
9. 子进程无环境变量 → 正常导入且两版本都等于真源。

### 9.5 定向套件（实跑）

    python tests/test_release_version.py  exit=0 FAIL=0  (现共 33 条断言)
    python tests/test_hub.py              exit=0 FAIL=0
    python tests/test_hub_eai.py          exit=0 FAIL=0
    python tests/test_hub_controller.py   exit=0 FAIL=0

### 9.6 兼容性说明

- docs/handoff §3.5 的发布手册写法（set LOOM_ENGINE_VERSION=... / set LOOM_HUB_VERSION=...）**仍然可用**，
  因为这些值本来就该等于真源；写错的（分叉）现在会被拦下而不是静默生效。
- tools/package_hub.py 无需新增函数：N5 之后 load_version() 已是纯读取（缺文件即报错、不回写）。
