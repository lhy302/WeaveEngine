# 倒查 01 · 交付物最终倒查（第十一轮，未参与实现）

- 基线：HEAD `e34d4d8e75f5e68277a44fa2d2a7411832d87e15`（commit time 2026-11-11 00:28:15），`git status --porcelain` = 0 行（干净）
- 时间：2026-11-11 00:48~00:58；全部数字为本次实测复跑，未引用任何既有报告

## 1. 包 vs HEAD 双向对拍（自己复跑）

```
py -3.13 tools/verify_pkg_vs_head.py tools/dist/Loom-0.1.0.beta6-source.zip tools/dist/Loom-0.1.0.beta6-compiled.zip --json C:\loom_build\final2_01_verify.json
→ exit code 0
[source] 包内引擎 .py=93 / HEAD=93，内容不一致=0，包多出(HEAD 无)=0，包缺失=0
[source] meta=0.1.0.beta6 nested=0.1.0.beta6 target=0.1.0.beta6 -> OK
[compiled] git_head=e34d4d8e75f5 head=e34d4d8e75f5 dirty=False -> OK（equal）
[compiled] smoke_passed_at=2026-11-11 00:44:30 built_at=2026-11-11 00:31:37
```

| 判据 | 要求 | 实测 | 判定 |
|---|---|---|---|
| 双向文件数 | 93/93 且集合相等 | 93 / 93，缺 0、多 0 | 达成 |
| 内容不一致 | 0 | 0（CRLF 归一后 sha256） | 达成 |
| git_head | == HEAD | `e34d4d8e...` == HEAD | 达成 |
| git_dirty | false | false（JSON 布尔） | 达成 |
| 门序 | smoke_passed_at > built_at | 00:44:30 > 00:31:37 | 达成 |
| meta | 顶层/嵌套 == 0.1.0.beta6 | 两者一致，python_version 3.13.15 | 达成 |

补充（我方反例尝试）：源码包内**不含** `Loom/tests/`（0 条）也不含 `Loom/build_info.json`——源码包不是构建产物，可接受；编译包内 `.py` 仅有 `core_components/*.py`（组件源码属数据，非引擎源码泄漏）。

## 2. 三件产物一致性（build_info 实读 + 二进制哈希交叉）

三处 `build_info.json` 逐字段相同：

| 产物 | git_head | dirty | built_at | smoke_passed_at | mode/nuitka/python |
|---|---|---|---|---|---|
| `C:\loom_build\engine\build_entry.dist` | e34d4d8e… | false | 00:31:37 | 00:44:30 | release / 4.3.5 / 3.13.15 |
| `Loom\player_runtime\game_player.dist`（仓库内） | e34d4d8e… | false | 00:31:37 | 00:44:30 | 同上 |
| `C:\loom_build\builder` | e34d4d8e… | false | 00:31:37 | 00:44:30 | 同上 |

二进制与编译包的哈希交叉（证明"打包进去的就是被审计的那份"）：

```
py -3.13 Loom/tests/_tmp/final2_01_artifact_xref.py
Loom/Loom.exe                                   MATCH 91ae76451126a5d1
Loom/player_runtime/game_player.dist/MyGame.exe MATCH 2323a5b18ce97483
Loom/build_game.exe (= C:\loom_build\builder\build_game.exe) same=True fb86c5468db379a1
```

**注意**：agent 侧 `C:\loom_build\engine\build_entry.dist` 下没有 `player_runtime/` 子目录（嵌套运行时在仓库内），三件产物本身的 build_info 全部对齐 HEAD，但"对齐"≠"能跑"，见 §5-P0。

## 3. Hub 0.1.4

- `tools/dist/LoomHub-0.1.4-Setup.exe` 存在，27,288,908 字节，mtime 2026-11-11 00:05:15（旧 0.1.3 仍在，未混用）。
- 版本单一真源：`LoomHub/版本.json`=0.1.4、`tools/installer.iss` `MyAppVersion=0.1.4`、`test_release_version.py` `EXPECT_HUB='0.1.4'`；`py -3.13 Loom/tests/test_release_version.py` → **总结果: ALL PASS ✅**（含"包名=LoomHub-<ver>-Setup.exe"、env 分叉拒绝）。
- **三处补丁是否真进包**：本机无 7z/innounp，改走"静默安装取真实载荷"：

```
tools/dist/LoomHub-0.1.4-Setup.exe /VERYSILENT /SUPPRESSMSGBOXES /NOICONS /DIR=C:\loom_build\final2_01_hubprobe
exit=0；装出 LoomHub.exe 7312140 字节 + _internal 1101 文件
installed SHA256 = A6DEA2C25CA4CE97EC51729FB4C1C54053420A3835DDAE1575FE03E5DCFE894D
build_hub   SHA256 = 同值  → same=True

py -3.13 Loom/tests/_tmp/final2_01_hub_patch_verify.py C:\loom_build\final2_01_hubprobe\LoomHub.exe
P1 安装根持久化        hub_config   PASS (user_install_root/default_install_root/saved_install_root/root_writable + 常量 install_root)
P2 扫用户目录          hub_config   PASS (scan_install_roots/scan_install_root + 常量 Programs)
P3 PermissionError 归类 hub_install PASS (_install_from_zip_impl + LOAD_GLOBAL PermissionError + 常量 winerror/权限不足)
VERDICT: PATCHES_PRESENT
```

（方法：`PyInstaller.archive.readers.CArchiveReader` 取 exe 内 PYZ → `ZlibArchiveReader` 取 `hub_config`/`hub_install` 代码对象，遍历 `co_name`/`co_names`/`co_consts`；探针见 `Loom/tests/_tmp/final2_01_hub_patch_verify.py`。安装包载荷 exe 与 build_hub 产物同哈希，因此"补丁在 build_hub"+"载荷同哈希"= 补丁在安装包内。）

## 4. 装机冒烟（temp 目录展开 compiled 包）

```
py -3.13 -c "zipfile...extractall(r'C:\loom_build\final2_01_dist')"
py -3.13 tools/smoke.py --dist C:\loom_build\final2_01_dist\Loom
SMOKE PASS [1/5] 能启动 (pid=248056)
SMOKE PASS [2/5] 场景已加载（models=126）
SMOKE PASS [3/5] 能播放 2.5s
SMOKE PASS [4/5] 有读数（fps=206.0 tps=30.34）
SMOKE PASS [5/5] 产物元数据自洽
SMOKE OK  用时 6.1s（预算 60s）   → exit code 0
```

5/5 PASS，**达成**。（副作用：冒烟给临时副本盖章 `smoke_passed_at=2026-11-11 00:53:49`，仅影响 temp 副本。）

## 5. 发布前还差什么（按严重度）

### P0 · 交付的"游戏构建器"一启动就崩（本轮最重要发现，冒烟 5/5 抓不到）

```
C:\loom_build\final2_01_dist\Loom> build_game.exe --help      （ckernels\loom_kernels.dll 就在同目录，Test-Path=True）
EXIT=1
RuntimeError: ckernels 官方组件加载失败: loom_kernels.dll 未找到, 尝试路径
 ['C:...\Temp\onefile_245312_...\ckernels\loom_kernels.dll',
  'C:...\Temp\onefile_245312_...\ckernels\loom_kernels.dll']
```

- 两个候选路径**都指向 onefile 临时解包目录**（`Loom/fastpath.py:58-63` 用 `sys.executable`；Nuitka 4.3.5 onefile 下它指向 temp 而非原 exe）→ 与 cwd、与 exe 旁是否有 ckernels **无关**，任何机器都必崩。
- 反例对照（同机、同 ckernels 目录）：beta5 的构建器 `build_game.exe`（旧包内提取，22958592 字节）`--help` → **EXIT=0**，仅有无害 `pkg_resources-postLoad` 警告。⇒ 这是 beta6（py3.13/Nuitka 4.3.5 升级）引入的**回归**，不是环境问题。
- 影响面：`使用操作指南.txt:364` 明写"build_game.exe 构建器（命令行/CI 用；编辑器 [发布游戏] 也调它）"；编译版安装里没有 `.py`，故该 exe 是唯一入口。
- 为什么门禁没抓到：`tools/smoke.py` 只测 `Loom.exe`（`--dist` 分支硬编码），`package_engine.py:132-181` 只校验 `smoke_passed_at` **戳存在且晚于 built_at**；三件产物的戳是**同一秒 00:44:30**（一次编辑器冒烟 `--stamp` 多处），所以"构建器冒烟通过"实际是**盖章，不是实测**。

### P2 · 两个包都带本机运行时残渣

```
py -3.13 Loom/tests/_tmp/final2_01_zip_hygiene.py tools/dist/Loom-0.1.0.beta6-compiled.zip
Loom/.agent_port.json   160B  2026-11-11 00:44:24 → {"port":62872,"token":"956228fec...","pid":247796}
Loom/editor_state.json  173B  2026-11-11 00:44:26 → {"last_dir":"...\Temp\tmpmqwi7p1q","last_scene":"...\a.json"}
# 源码包内同类文件：.agent_port.json(port=60681, 11-10 23:54:06)、editor_state.json(11-11 00:30:44)
```

两者都在 `.gitignore`（29/32 行）里，但打包是"拷工作树"→ 忽略规则不生效。消费方：`Loom/loom_mcp.py:37-58` 以 `.agent_port.json` 判断"引擎是否已启动"（脏文件会让 MCP 去连一个死端口），`Loom/editor.py:54` 以 `editor_state.json` 恢复上次目录/场景（指向已删除的 temp 路径）。建议从包里剔除（`package_engine.py` EXCLUDE_FILES）。

### P3 · 发布说明缺失

`tools/release_notes/` 只有 `engine-0.1.0.beta4.md / beta5.md / hub-0.1.2.md / hub-0.1.3.md`；**没有** `engine-0.1.0.beta6.md` 与 `hub-0.1.4.md` → `release_github.load_highlights` 会退回通用条目（正是它 docstring 里点名的"版本说明过期"问题）。

### P3 · tag / 交接文档与 HEAD 不一致

- `git tag` 最新 = `engine-v0.1.0.beta5` / `hub-v0.1.3`，无 beta6 / 0.1.4 tag（发版时由 `release_github` 建，符合流程，但仍是"未完成"）。
- `docs/handoff/接手须知_beta6当前状态_20261111.md`（00:16 写）仍是"渲染后端抽象化未达成 → beta6 只是中间版本、不发布、不谈 tag/上传"；而 HEAD 的 `8496a52`（00:27）声称"语义面收口（未共享 4.5<=8 达标）"。二者至少有一处过期，**收尾与否需人类裁决**，不能由交付包自证。

## 6. 达成度统计

| 目标 | 判定 |
|---|---|
| 1 包 vs HEAD 双向 93/93、0 不一致、head/dirty/门序/meta | **达成**（6/6 判据） |
| 2 三件产物 build_info 与 HEAD 对齐 + 二进制同哈希 | **达成**（3/3 产物；但见 P0：对齐≠可运行） |
| 3 Hub 0.1.4 存在/版本三处一致/三补丁在包内 | **达成**（4/4） |
| 4 装机冒烟 5/5 | **达成**（5/5，6.1s/60s） |
| 交付物"可用性"（构建器） | **未达成**（P0，1/1 关键路径崩） |

合计：4 项要求达成，1 项（构建器可用性）未达成；另 4 项前置条件缺失（P2 残渣、P3 release notes、P3 tag、P3 文档过期）。

## 7. 待裁决

1. `build_game.exe` 回归是否阻塞 beta6 交付？（我的判定：**阻塞**，因为它是文档承诺的对外入口，且现有门禁不可能发现）
2. `smoke.py` 是否扩成"三件"（编辑器 / 构建器 / 运行时各一条），并把"盖章来源=实测"写进 `build_info`（如 `smoke_target` 字段）？
3. 打包是否先清 `EXCLUDE_FILES`（`.agent_port.json`/`editor_state.json`/任意 `__pycache__`）？
4. beta6 是否进入收尾（补 release notes、打 tag、上传）——取决于渲染目标裁决。

## 8. 本次探针（只读，均在 Loom/tests/_tmp/）

`final2_01_hub_patch_strings.py`、`final2_01_hub_patch_verify.py`、`final2_01_zip_hygiene.py`、`final2_01_artifact_xref.py`、`final2_01_source_junk.py`。
外部临时物：`C:\loom_build\final2_01_{verify.json,dist,hubprobe,hubinstall.log,beta5}`。
