# verify2_02 — 交付物与验证工具的可信度

- 倒查时间：2026-11-10 21:53–22:05
- 基线：HEAD = 576d18a2a29082c205a446563b101999dc3a3556（工作树干净，core.autocrlf=true）
- 交付物：tools/dist/Loom-0.1.0.beta6-source.zip（365,468,422B）、Loom-0.1.0.beta6-compiled.zip（138,437,421B）
- 规格：docs/design/开发流程_任务后倒查.md、docs/design/开发流程_冒烟与验证分层.md
- 探针：Loom/tests/_tmp/verify2_02_probe.py（被 Loom/.gitignore:22 忽略，未污染工作树）

## 1. 结论表（带分子/分母）

| # | 宣称 | 判定 | 证据 |
|---|---|---|---|
| 1a | source 包与 HEAD 0 不一致 | **成立**（93/93 一致，0 缺失、0 多余） | §2.1 |
| 1b | compiled 的 build_info.git_head == HEAD | **不成立**（dea1f4f ≠ 576d18a） | §2.2 |
| 1c | git_dirty == false | **成立**（两个 zip 内 build_info 均为 false） | §2.2 |
| 1d | 三项 meta 一致 | **部分成立**（version 只有 2 处可比且一致；build_info 无 version 字段） | §2.3 |
| 2 | 冒烟只做正向、<60s、五判据正向 | **成立**（源码 6.3s / 编译 6.2s，全绿，exit 0） | §3 |
| 2b | 冒烟能红（失败场景返回非 0） | **成立**（--scene/--dist 非法均 exit 1） | §3.3 |
| 3 | 测量与冒烟分离、默认只记录 | **成立**（默认 exit 0 无判定；--min-fps 9999 → exit 1） | §4 |
| 4 | 一次性脚本已清理 | **部分成立**（C:\loom_build 顶层 0 个 ps1；但"对拍工具"仍在仓库外） | §5 |

## 2. 复跑 package-vs-HEAD 对拍

命令（外部脚本 C:\loom_build\toolchain_probe\verify_pkg_vs_head.py，7,653B，2026/11/10 21:46:20，单行执行）：

    $env:LOOM_REPO='D:\my-project - 副本\Loom(py源代码-工作区)'
    py -3.13 C:\loom_build\toolchain_probe\verify_pkg_vs_head.py tools\dist\Loom-0.1.0.beta6-source.zip tools\dist\Loom-0.1.0.beta6-compiled.zip --version 0.1.0.beta6

实测输出：

    HEAD commit time: 2026-11-10 21:48:52
    [source] py 文件 93，与 HEAD 不一致 0，HEAD 不存在 0
      key sceneio.py        zip=58b3bdcb8999 head=59cfbd364f92 OK
      key agent_commands.py zip=368ebbfd4841 head=1682b1f6f196 OK
      key loom_post.py      zip=3fe5f6bd4be2 head=3fe5f6bd4be2 OK
      key loom_assets.py    zip=a66f7066a614 head=a66f7066a614 OK
    [source] meta=0.1.0.beta6 nested=0.1.0.beta6 target=0.1.0.beta6 -> OK
    [compiled] meta=0.1.0.beta6 nested=0.1.0.beta6 build_info.mode=release built_at=2026-11-10 21:23:42
    [compiled] git_head=dea1f4fc37ef head=576d18a2a290 dirty=False -> DIFF
    [exit]1

注：key 行的 zip/head 前缀不同（58b3…/59cf…、368e…/1682…）而判 OK，是因为打印的是**未归一**哈希、比较用的是 EOL 归一后哈希——不是缺陷，但输出容易被读成"不一致却判 OK"。

### 2.1 两个已知误报源，实测确认（不是猜测）

    [A] HEAD 引擎 py=238  zip py=93
    [A] HEAD 有 / zip 无 = 145（全部是 Loom/tests/**；tools/package_engine.py:29 EXCLUDE_DIRS 含 'tests'，zip 内 Loom/tests/ 计数 0）
    [A] zip 有 / HEAD 无 = 0
    [B] 未归一不一致=18 归一后不一致=0 (差值=18 即 CRLF 误报源)
    [B] 归一后仍不一致样例: []
    [B] 人为单字节改动仍被归一比较抓到: True

- CRLF 归一确实把 18 个文件从"不一致"降到 0；且归一**不会**掩盖真实差异（单字节篡改仍被抓到）。
- player_runtime 排除生效：zip 内 .py 共 97 个，其中 4 个在 Loom/player_runtime/ 下，比较集 93 个。
- 结论：93/93 一致是**真值**，但"0 不一致"只覆盖包内文件；包外 145 个 tests 文件由 EXCLUDE_DIRS 有意排除，对拍工具没有、也无法断言其一致性。

### 2.2 git_head ≠ HEAD：字面不成立，影响面为零

    git merge-base --is-ancestor dea1f4fc37ef HEAD -> 0（是祖先）
    git log --oneline dea1f4fc37ef..HEAD
    576d18a docs(toolchain): 附录 G …
    27b781b chore: gitignore tools/dist/_engine_stage + 清理 26 个一次性 ps1
    c56fb1d feat(process): 新增 tools/smoke.py + tools/measure_engine.py + 分层文档
    git diff --stat dea1f4fc37ef..HEAD -> 6 files, 379 insertions(+)，全部在 .gitignore/docs/tools，Loom/ 下 0 文件

→ 编译产物与 HEAD 的引擎源码逐字节等价（0 个引擎文件差异），但"git_head==HEAD"这条断言本身为假。
→ **顺带查出一个流程事实**：compiled 的 built_at = 21:23:42，而 smoke.py 首个提交 c56fb1d = 21:36:51。
  即**本交付包构建时冒烟工具尚不存在**，"编译 -> 冒烟 -> 打包 -> 对拍"的门序对该包不可能执行过。
  本次倒查补跑：源码 6.3s 绿、编译版 6.2s 绿（§3），属事后证据，不能倒推为当时门禁通过。

### 2.3 三项 meta

| meta 源 | source.zip | compiled.zip |
|---|---|---|
| 顶层 Loom/解释器.json | version=0.1.0.beta6, python=3.13.15 | version=0.1.0.beta6, python=3.13.15（另有 build_mode） |
| 嵌套 player_runtime/game_player.dist/解释器.json | 0.1.0.beta6 / 3.13.15 | 0.1.0.beta6 / 3.13.15 |
| Loom/build_info.json | **不存在（null）** | mode=release, python=3.13.15, nuitka=4.3.5, built_at=21:23:42, git_head=dea1f4f, git_dirty=false |
| player_runtime/…/build_info.json | mode=release, git_head=dea1f4f, dirty=false | 同上 |

- version：只有 2 处可比（顶层/嵌套），一致 2/2；**build_info 无 version 字段**，所以"三项 version 一致"是口径错误，实际是"两处 version + 三处 python"。
- python_version：顶层/嵌套/build_info 三处均 3.13.15，一致 3/3。
- 源码包不含 build_info.json 属设计（源码包不带构建元数据），但意味着对拍工具的 meta 检查对源码包半盲。

## 3. tools/smoke.py：是否真的"只做正向"

静态审读（154 行）结论：**未偷偷测异常路径、未测回退/降级、未测阈值、未 grep 源码**。

- 判据 1：等 .agent_port.json + proc.poll() is None（启动即证，不构造失败）。
- 判据 2：status.models 数量 > 0（不判具体数量、不判内容）。
- 判据 3：play on → sleep 2.5s → 进程存活且 playing（不做崩溃注入）。
- 判据 4：fps > 0 且 tps > 0（**无任何阈值**；字段兼容 get_tps/tps）。
- 判据 5：仅 --dist 时打印；源码模式 SKIP。
- 两处"非正向"只是**参数守卫**（第 50 行场景不存在、第 57 行 Loom.exe 不存在），不进入引擎路径，符合"失败即停"。
- 第 74 行 env.pop('LOOM_POST')：强制默认姿态，属"只测主线"，不是测异常。
- 轻微瑕疵：第 136 行 "[5/5] 退出后进程仍在" 落在 finally 里 wait(timeout=8) 之后，几乎恒为死检查，且标签挂在 5/5（源码模式下 5/5 是 N/A）。判据 5 也不是独立检查——它复用判据 1–4 已跑过的同一个 exe。

### 3.1 源码模式实跑

    SMOKE PASS  [1/5] 能启动（pid=249544）
    SMOKE PASS  [2/5] 场景已加载（models=126）
    SMOKE PASS  [3/5] 能播放 2.5s
    SMOKE PASS  [4/5] 有读数（fps=236.0 tps=30.34）
    SMOKE SKIP  [5/5] 编译版产物检查（源码模式不适用）
    SMOKE OK  用时 6.3s（预算 60s）      [exit]0

### 3.2 编译版实跑（--dist C:\loom_build\pkgtest_compiled\Loom）

    SMOKE PASS  [1/5] 能启动（pid=248900）
    SMOKE PASS  [2/5] 场景已加载（models=126）
    SMOKE PASS  [3/5] 能播放 2.5s
    SMOKE PASS  [4/5] 有读数（fps=226.0 tps=30.02）
    SMOKE PASS  [5/5] 编译版产物能起（Loom）
    SMOKE OK  用时 6.2s（预算 60s）      [exit]0

### 3.3 失败场景（反证它真的会红）

    py -3.13 tools/smoke.py --scene Z:\nope\missing.json
    SMOKE FAIL  场景不存在: Z:\nope\missing.json      [exit]1
    py -3.13 tools/smoke.py --dist C:\nope
    SMOKE FAIL  找不到 C:\nope\Loom.exe              [exit]1

## 4. tools/measure_engine.py：与冒烟是否分离

- 文件层面：与 smoke.py 无 import、无共享 helper、无共享常量；smoke 不调用 measure，measure 不调用 smoke → **分离成立**。
- 判定层面：--min-fps 默认 None，仅 "if a.min_fps is not None" 分支才判；判定只在末尾，前面全是记录。
- 实测：

      py -3.13 tools/measure_engine.py --frames 40 --runs 1
        [1/1] default fps=435.0 tps=32.12 rc=0
        default  FPS 中位 435.0 (min 435.0 / max 435.0, n=1)  TPS 中位 32.10
        [exit]0                     ← 默认只记录，无"门禁"字样

      py -3.13 tools/measure_engine.py --frames 40 --runs 1 --min-fps 9999
        门禁失败：中位 FPS 404.4 < 9999.0
        [exit]1                     ← 显式给出才生效

- 两个口径问题（非阻塞）：
  1. 门禁只取 summary['default'] 的中位，配了 --ab 时门禁**完全不看**对照配置；
  2. _summ() 用 "[v for v in vals if v]" 过滤，fps=0.0 这种"真·零帧"会被静默丢弃而不是记为失败。

## 5. 遗留一次性脚本 / 探针

    C:\loom_build 顶层 *.ps1 -> 0 个；顶层 *.py -> 0 个（26 个 ps1 的清理确实落地）

| 对象 | 现状 | 判断 |
|---|---|---|
| C:\loom_build\toolchain_probe\verify_pkg_vs_head.py | 仓库外、未受版本管理；docs/design/research_beta6_06_toolchain_upgrade.md:500 按绝对路径引用它作为"包与 HEAD 对拍"工具 | **应收入 tools/verify_pkg_vs_head.py**（当前对拍不可由仓库复现，换机即失效） |
| docs/audit/pacman_ghost.py、pacman_player.py（3,926B / 7,013B） | 实机演示用的吃豆人玩法脚本，仅被报告正文引用 | **应迁到 examples/ 或删除**；docs/audit 不放可执行代码 |
| Loom/tests/_tmp/ | 磁盘上 972 个 .py/.ps1/.sh，受跟踪仅 24 个（其余被 Loom/.gitignore:22 "tests/_tmp/*" 忽略） | 按分层文档 §4"验完必须三选一"：受跟踪的 24 个要逐个裁决收/删；未跟踪的不算仓库工具但仍在被手工跑 |
| tools/loom_lint_except.py vs tools/lint_except_dist/loom_lint_except.py | 同名两份（后者为打包副本） | 保留，但应加一行注释指明从属关系，避免双写者 |
| tools/make_splash.py、tools/migrate_scene_assets_v11.py | 构建期工具 / 版本迁移脚本 | 合理保留（迁移脚本建议标注"仅 v1.0→v1.1 一次性"） |
| LoomHub/tests/_tmp/_probe_*.py、_align_tests/tools/_probe_*.py | 历史探针 | 同理待裁决，非本轮对象 |

## 6. 引入问题 / 待裁决

1. **（P2）** compiled 包的 build_info.git_head 落后 HEAD 一个 docs/tools-only 提交。引擎 0 文件差异，无功能影响；但"git_head==HEAD"不能作为硬门禁字面执行，建议改成"git_head 是 HEAD 祖先 且 git diff --name-only <head>..HEAD -- Loom 为空"，否则每次改文档都会红。
2. **（P2）** 交付包构建时间早于冒烟工具的首个提交，本包**没有**"先冒烟后打包"的当时证据。建议 build_info 记 smoke_passed_at，或让打包脚本内联调用 smoke.py。
3. **（P3）** 对拍脚本 key 行打印未归一哈希、比较用归一哈希，易被误读；应打印归一后哈希。
4. **（P3）** measure 门禁不看 --ab 配置；_summ 把 0.0 当空值丢弃。
5. **（P3）** smoke 判据 5 非独立检查，且 "[5/5] 退出后进程仍在" 是死检查；建议并入判据 1。

## 7. 复现清单（全部只读，未改仓库任何受跟踪文件）

    py -3.13 C:\loom_build\toolchain_probe\verify_pkg_vs_head.py tools\dist\Loom-0.1.0.beta6-source.zip tools\dist\Loom-0.1.0.beta6-compiled.zip
    py -3.13 Loom\tests\_tmp\verify2_02_probe.py
    py -3.13 tools\smoke.py
    py -3.13 tools\smoke.py --dist C:\loom_build\pkgtest_compiled\Loom
    py -3.13 tools\smoke.py --scene Z:\nope\missing.json
    py -3.13 tools\measure_engine.py --frames 40 --runs 1
    py -3.13 tools\measure_engine.py --frames 40 --runs 1 --min-fps 9999
