# beta6 第六轮复核 · 编号 03 · 版本闸与打包元数据

> 复核对象：HEAD **a41b6f3**（本轮起始 **308a6d1**；两者之间仅两个 docs 提交，03 范围内源码无 diff）。关键修复：**d635f35**（D7 基线闸）、**1d22e60**（Q-VER-1=A）、**0b38bc0**（Q-VER-2=A）、**4de3b4b**（prefab 闸 / 迁移写 min）、**21b44cd**（R5-02）。
> 判定语义：**P-PROVED = 修复/宣称不成立（找到反例）**；**P-DISPROVED = 反例构造失败、修复成立**；**P-UNKNOWN = 信息不足，交人类裁决**。
> 只读：本编号未修改任何受跟踪文件；探针仅写 **Loom/tests/_tmp/audit_b6r6_03_*.py**（Loom/.gitignore:22 忽略），运行产物均在 %TEMP%。审计期间工作区出现其他编号代理的受跟踪改动（Loom/loom_components.py、Loom/loom_frame_components.py、Loom/loom_physics.py、Loom/scene_driver.py、Loom/tests/test_animation_base.py、docs/design/待裁决清单_beta6.md），非本编号所为，未还原、未触碰；其中 scene_driver.py 的改动在 :1319 之后，不影响本报告引用的 :599-614 版本闸行号。

## 0. 范围与方法

### 0.1 文件范围（行数按 read 实测）

| 文件 | 行数 | 本轮关注点 |
|---|---|---|
| Loom/sceneio.py | 2189 | parse_version / version_lt / check_engine_version / ENGINE_VERSION、写侧 stamp、prefab 入口 |
| Loom/run_player.py | 471 | handle_scene_version_error、vulkan/opengl/auto 拦截 |
| Loom/scene_driver.py | 1602 | VK load_from_data 闸门 |
| Loom/editor.py | 2867 | 场景/prefab 加载入口 |
| Loom/game_player.py | 305 | 发布链 _run_backend_safe |
| Loom/build_entry.py | 413 | **编译版 Loom.exe 入口（Q-VER-1 未覆盖）** |
| Loom/Loom.py | 512+ | 源码版 --run / 远程回读入口 |
| Loom/loom_player_window.py | 268+ | 远程回读播放器（Q-VER-1 未覆盖） |
| Loom/build_game.py | 435 | 游戏运行时打包 + meta 拷贝 |
| tools/build_engine.py | 318 | _assert_meta |
| tools/package_engine.py | 614 | 源码包：版本读写、运行时拷贝、_verify_zip |
| tools/package_engine_compiled.py | 240 | 编译包：meta 断言、zip 自检 |

### 0.2 跑过的命令（全部可复现）

~~~text
py -3.13 Loom/tests/_tmp/audit_b6r6_03_p1_version_semantics.py
py -3.13 Loom/tests/_tmp/audit_b6r6_03_p2_engine_version_paths.py
py -3.13 Loom/tests/_tmp/audit_b6r6_03_p3_real_artifact.py
py -3.13 Loom/tests/_tmp/audit_b6r6_03_p4_binaries.py
py -3.13 Loom/tests/_tmp/audit_b6r6_03_p5_editor_prefab.py
py -3.13 Loom/tests/_tmp/audit_b6r6_03_p6_run_entry.py
py -3.13 Loom/tests/_tmp/audit_b6r6_03_p7_pkg_assert.py
py -3.13 Loom/tests/_tmp/audit_b6r6_03_p8_entry_contrast.py
py -3.13 Loom/tests/_tmp/audit_b6r6_03_p9_same_version.py
py -3.13 Loom/tests/_tmp/audit_b6r6_03_p10_source_relabel.py
py -3.13 Loom/tests/_tmp/audit_b6r6_03_p11_zip_tamper.py
py -3.13 Loom/tests/test_scene_version_player.py          # ALL PASS
py -3.13 Loom/tests/test_animation_base.py                # ALL PASS
py -3.13 Loom/tests/test_asset_guid.py                    # ALL PASS
py -3.13 Loom/tests/test_release_version.py               # ALL PASS
~~~

### 0.3 真实产物

- 编译包：tools/dist/Loom-0.1.0.beta6-compiled.zip（136,396,938 B；Loom.exe / MyGame.exe 的 build_info built_at=2026-11-10 13:47:58，Nuitka 4.3.5）。
- 源码包：tools/dist/Loom-0.1.0.beta6-source.zip（2026-11-10 07:35:52 写出；**SCENE_VERSION=10，无版本闸**，见 P-10）。
- tools/dist/ 被 .gitignore:59 忽略，故 git status 看不到；上述包是本地暂存产物，不等于已发布。

### 0.4 与上一轮的对应关系

| 上轮项 | 本轮结论 |
|---|---|
| R5-02 P-03：VK 播放器入口不过版本闸 | **修复成立**（P-02 DISPROVED；编译版实测拒 beta10 场景） |
| R5-02 P-04：prefab 不在闸门内 | **修复成立**（P-02；探针 p5 的 load/instantiate 双入口都拦） |
| R5-01 P-07：迁移产物缺 min_engine_version | **修复成立**（test_asset_guid.py 全绿；写侧在 migrate 工具完成） |
| Q-VER-1：失败必须可见 | **部分成立**：三个 run_backend 入口 + 编辑器 + game_player 成立；build_entry.py --run 与远程回读窗口不成立（P-03/P-04） |
| Q-VER-2=A：产物带 meta + 断言 | **部分成立**：编译包断言成立；源码包可被 --version 重贴、嵌套运行时 meta 不校验（P-08/P-09）；meta 本身可篡改（P-06） |

## 1. 粗筛清单（六元组；跳过项留痕）

| ID | 位置 | 标签 | 初步方向 | 粗筛证据 |
|---|---|---|---|---|
| S-01 | sceneio.py:96-129 | SEM-MISMATCH / BND-OFFBYONE | betaN 数值比较、正式版/beta 序、非法串处理 | part.startswith('beta')；nums 超 3 位被丢弃（:125-129） |
| S-02 | sceneio.py:75-89 | SEM-FALLBACK | meta 缺失/损坏 → 常量兜底，版本事实是否仍可信 | except Exception: pass; return _ENGINE_VERSION_FALLBACK |
| S-03 | sceneio.py:141-163 | IFACE-VERSION | 闸门对非 str/空/无法解析字段的处理是否安全 | :150-152 非 str 直接放行；:155-158 无法解析告警后放行 |
| S-04 | run_player.py:390-437 / scene_driver.py:609-614 / editor.py:1228-1233 | IFACE-ERROR / SEM-SILENT | 三入口 + 编辑器 + prefab 是否都过闸、失败是否可见 | 三处 check_engine_version + 编辑器 _notify |
| S-05 | Loom/build_entry.py:383-387、Loom.py:204-221 | AUDIT-ASYMMETRY | 另有入口绕过 run_backend，可见性可能不同 | build_entry 直接 PlayerApp；远程窗口只 traceback.print_exc() |
| S-06 | tools/build_engine.py:126-138 / package_engine_compiled.py:102-104,122-125 | TOOL-WHITELIST | 断言是否只比字符串、能否被改 dist meta 绕过 | 只比 meta.version == version，不绑二进制 |
| S-07 | tools/package_engine.py:468-505,533-578 | AUDIT-ASYMMETRY | 源码包 --version 重写 meta，是否校验源码版本 | _meta['version'] = version，meta_version_problems 有定义无调用 |
| S-08 | 解释器.json 全链 | SEM-SILENT | 运行时唯一事实源是安装目录可写 json，被改即改变闸门行为 | P3 实测 B 段：同一 exe，改 meta 后由拒变放 |
| S-09 | tools/dist/Loom-0.1.0.beta6-source.zip | OVERFIT-TESTENV | 同版本标签下存在无闸旧构建 | 包内 SCENE_VERSION=10、无 check_engine_version、MyGame.exe 无闸字符串 |
| S-10 | sceneio.py:1933-2004 | IFACE-VERSION | version > SCENE_VERSION 且无 min_engine_version 时是否应拒 | migrate 只在 check_engine_version 后降级，不比较 version |

**跳过（SKIP）登记**

- SKIP-01 version_lt 对不可解析串返回 False（sceneio.py:132-138）：契约 :145-146 明确“无法判定则不拦”，且 :155-158 有打印；不再按 bug 审。
- SKIP-02 LoomHub/hub_config.py:133-152 _version_key：不在本轮文件范围；只做一致性对照（beta6<beta10、正式版>beta 的语义与 sceneio 相同）。
- SKIP-03 migrate 的 v1→v10 分支（:1947-2003）：与引擎版本闸无交互，已有 test_sceneio.py / test_camera.py 覆盖。
- SKIP-04 game_pack.py:58-68 LOOMSC 打包：整份 scene dict 原样保存（:65），不裁剪 min_engine_version。
- SKIP-05 editor._save_scene（:1159-1187）的资产 notice：属 01 资产范围，本轮只确认写侧 stamp 在 :1822。
- SKIP-06 tools/release_github.py:27-62 版本真源解析：已有 test_release_version.py 全绿，本轮只核对与 解释器.json 缺省一致。

## 2. 逐项裁决（8 段式）

### P-01 · 版本比较语义（①）—— **DISPROVED**（核心成立；3 个 P3 边界）

1) **位置**：sceneio.py:96-129 parse_version、:132-138 version_lt、:141-163 check_engine_version。
2) **契约/预期**：docstring :96-101 明确 0.1.0.beta6 -> (0,1,0,0,6)、0.1.0 -> (0,1,0,1,0)（同号正式版 > beta）、1.2 -> (1,2,0,1,0)；:142-146 说明缺字段/不可解析的放行策略。
3) **路径枚举**：① 纯数字段；② betaN 段（含 beta、beta0、大小写、前导零）；③ 未知段（rc1/alpha/带 + 构建元数据）→ None；④ 数字段 >3；⑤ 空段（0..1）。
4) **实际**（探针 p1 输出）：
   - beta6 -> (0,1,0,0,6)、beta10 -> (0,1,0,0,10)、beta6 < beta10 = True；
   - 0.1.0 -> (0,1,0,1,0)，lt(beta6, 0.1.0)=True、lt(0.1.0, beta6)=False；
   - 0.1 -> (0,1,0,1,0)、beta06 == beta6、BETA10 == beta10；
   - 0.1.0.beta6+build7 / v0.1.0.beta6 / 0.1.0-rc1 → None；
   - 0.1.0.7 / 1.2.3.4 → 第四位数字被丢弃；0..1 → (0,1,0,1,0)；
   - check_engine_version 对 beta10 抛 SceneVersionError（原因含要求/当前版本）；对 beta5 通过；对 0.1.0 也抛。
5) **差异**：核心 beta 方案（betaN 数值序、正式版 > beta）与契约一致，**无差异**；边缘见下。
6) **触发条件**：场景 min_engine_version 含第 4 个数字段/空段/构建元数据；或字段非字符串。
7) **验证**：py -3.13 Loom/tests/_tmp/audit_b6r6_03_p1_version_semantics.py（输出见附录 A1）；test_animation_base.py ⑥“beta6<beta7<beta10<0.1.0” PASS。
8) **影响/等级**：核心语义 P-DISPROVED（无 bug）。附加 P3：
   - **O-01** :125-129 只取前 3 个数字，0.1.0.7 被当成正式版 0.1.0 → 对 beta6 是**误拒**（安全方向），但若将来采用 4 段版本会判错；
   - **O-02** :150-152 对非字符串（0.2 / {}）**静默放行且不打印**，与“不可解析字符串会告警”不对称（test_animation_base 只测字符串）；
   - **O-03** :155-158 不可解析（如 0.1.0.beta6+x）只 print 后放行；在 release 播放器（无控制台、无日志 tee）该告警不可见 → 闸门实际关闭。

### P-02 · 三入口/编辑器/game_player 过闸与可见失败（②）—— **DISPROVED**（四条主路径成立）

1) **位置**：run_player.py:390-437；scene_driver.py:609-614；editor.py:1228-1233 / 1430-1436；game_player.py:193-245；sceneio.py:2153-2169。
2) **契约**：Q-VER-1=A（docs/design/待裁决清单_beta6.md:22）——更高版本场景要“弹窗 + 明确原因 + 优雅退出”；三入口与编辑器都不能静默加载。
3) **路径枚举**：
   - run_backend('vulkan')：_run_vulkan 抛 → :430-435 非初始化异常原样上抛 → 外层 :398-403 拦截；
   - run_backend('auto')：:412-417 先判 SceneVersionError 并 raise（不伪装成 VK 不可用、不回退 GL）；
   - run_backend('opengl')：_run_gl_visible :323-325 显式 re-raise；双错路径 :348-350 同样 re-raise；
   - game_player._run_backend_safe：:235 调 run_backend，:236 对 SystemExit 直接 re-raise（不二次跑 GL）；
   - 编辑器：:1228-1233 在清空旧场景**之前**过闸，_notify toast；prefab：:1430-1436 + sceneio.load_prefab/instantiate_prefab 双入口。
4) **实际**：
   - test_scene_version_player.py：A1/A2/A3（真实 SceneDriver/PlayerApp 拒）、B（vulkan/opengl/auto 弹窗+原因+exit1+无 traceback+不重试）、C（game_player）、D（NO_DIALOG 只打印）全 PASS；
   - 本审计 p5（无头编辑器）：拒载后旧场景 1 个哨兵仍在、_scene_path 未改、_notify 文案含 9.9.9 与当前版本；load_prefab/instantiate_prefab 均抛 SceneVersionError，旧 prefab（无字段）仍可加载；
   - 本审计 p3（真实编译包）：Loom.exe --bench 对 beta10 场景 exit=2，bench_error.txt 为 SceneVersionError；beta6 场景 exit=0。
5) **差异**：上述四条主路径无差异。
6) **触发条件**：更高版本场景 + 上述入口。
7) **验证**：见 0.2 的 p3/p5 与三个测试（全 PASS）。
8) **影响**：**P-DISPROVED**（主路径成立）。未覆盖的两个播放器入口见 P-03/P-04；因此 Q-VER-1 的“所有播放器”表述仍不成立。

### P-03 · Loom.exe --run / 旧 游戏配置.json 入口：失败不可见 —— **P-PROVED（P2）**

1) **位置**：Loom/build_entry.py:383-387（--run 直接 PlayerApp）、:401-418（旧 游戏配置.json 同样直接 PlayerApp）、:433-435（统一 except Exception 只 print + sys.exit(1)）；构建入口见 tools/build_engine.py:185-193（build_entry.py → Loom.exe）。
2) **契约**：Q-VER-1=A 的“播放器遇到更高版本场景 → 弹窗 + 明确原因 + 优雅退出”；build_entry.py:385 自述“Player 模式（运行时，无编辑器 UI）”。
3) **路径枚举**：Loom.exe --run S；Loom.exe 双击且同夹 游戏配置.json 含 scene；两者都不经过 run_player.run_backend，也不 import handle_scene_version_error。
4) **实际**：真实编译包实测（探针 p6/p8）：
   - Loom.exe --run newer.json --backend opengl → exit=1（1.5–2.0s），stdout 仅 “[错误] 无法启动渲染引擎: 场景要求引擎 >= ...”，**无弹窗**；
   - 该 exe 二进制不含 handle_scene_version_error / 无法打开场景 字符串；同一包的 MyGame.exe 两者都有，并在 p8 输出 Q-VER-1 的完整文案；
   - release 档 build_info.json 的 console_mode=disable，双击场景下 stdout 无控制台承接 → **零可见反馈**。
5) **差异**：预期“弹窗 + 明确原因 + 优雅退出”；实际“通用错误行 + exit 1 + 无弹窗/无日志”。
6) **触发条件**：用编辑器 exe 的 --run 或旧 游戏配置.json 打开更高版本场景。
7) **验证**：py -3.13 Loom/tests/_tmp/audit_b6r6_03_p6_run_entry.py、..._p8_entry_contrast.py（附录 A6/A8）。
8) **影响/等级**：**P2**（不丢数据——闸门仍拒绝；但发布版用户看到“双击没反应”）。修复方向：build_entry 的两个入口改走 run_player.run_backend（源码版 Loom.py:189-221 已这样做），或显式复用 handle_scene_version_error。

### P-04 · 远程回读播放器：只打印 traceback，窗口不退出 —— **P-PROVED（P2）**

1) **位置**：Loom/Loom.py:204-207（LOOM_REMOTE_MODE=on）、:220-221（auto 降级）→ loom_player_window.run_player_window；Loom/loom_player_window.py:109-119（PlayerApp 建在 Qt timer 回调里，except Exception: traceback.print_exc()）、:121-124（_engine is None 时 _tick 直接 return）、:262-268（进入 app.exec()）。
2) **契约**：同 P-03；远程模式只是“显示通道”不同，场景版本失败仍应可见并退出。
3) **路径枚举**：LOOM_REMOTE_MODE=on 直接走（完全绕开 run_player）；auto 的原生段先走 run_player，若版本不满足会在原生段就按 Q-VER-1 退出、根本到不了回读窗口（:213-221 的 remote 分支只在原生启动成功后执行）——因此**版本场景的实际触发面是 on**，auto 不构成版本触发。
4) **实际**：PlayerApp 在 scene_from_dict 抛 SceneVersionError（p3 A3 已证）→ _init_engine 的 except 仅 traceback.print_exc() → _engine 保持 None → _tick 每 16ms 早退 → Qt 事件循环继续，用户看到空白窗口；无 show_blocking_dialog、无 SystemExit。
5) **差异**：预期弹窗/退出；实际 traceback（release 不可见）+ 空白窗口常驻。
6) **触发条件**：远程桌面/虚拟显示 + LOOM_REMOTE_MODE=on + 更高版本场景。
7) **验证**：静态链 + p3 A3（PlayerApp 确实抛）；未启动 Qt 阻塞窗口（遵守协议 §0-5），代码路径为唯一分支（_init_engine 无其他 except）。
8) **影响/等级**：**P2**；建议在 _init_engine 捕获 SceneVersionError → 复用 handle_scene_version_error（或至少 QMessageBox + sys.exit(1)）。

### P-05 · ENGINE_VERSION 读取路径（③）—— **DISPROVED**（读取/兜底符合文档；写侧兜底风险 P3）

1) **位置**：sceneio.py:72（兜底常量）、:75-89（_read_engine_version，__file__ 同目录 解释器.json）、:89（import 时求值）、写侧 :1822/:2144。
2) **契约**：:76 “单一事实源 = 引擎目录 解释器.json；读不到 → 常量兜底”；:69-71 声称正常产物必带（由 build_engine/package_engine_compiled 断言）。
3) **路径枚举**：① 文件存在且 version 为非空字符串；② 文件缺失；③ JSON 损坏；④ version 为数字/空/非字符串；⑤ 文件名不对。
4) **实际**（p2 探针，直接改 sceneio.__file__ 调真实函数）：
   - 存在 beta7 → '0.1.0.beta7'；带空白 ' 0.1.0.beta10 ' → 去空白；
   - 缺失/损坏/数字/空/无 version 键/文件名不对 → 全部 '0.1.0.beta6'（=兜底常量，且与当前 Loom/解释器.json 一致）；
   - 真实编译产物：p3 A 段 meta=beta6 时 beta10 场景 exit=2；C/D 段删/坏 meta 时同样 exit=2（走兜底 beta6）——**说明编译版确实读同目录文件**；
   - 兜底写侧：sceneio.ENGINE_VERSION=fallback 时 scene_to_dict 写出的 min_engine_version='0.1.0.beta6'。
5) **差异**：读取/兜底行为与文档一致，无差异；但“缺 meta 时写侧也按兜底 stamp”是遗留 P3（见 O-04）。
6) **触发条件**：手工拷贝/部分升级/杀软删文件导致 meta 缺失或损坏。
7) **验证**：py -3.13 Loom/tests/_tmp/audit_b6r6_03_p2_engine_version_paths.py、..._p3_real_artifact.py（附录 A2/A3）。
8) **影响**：**P-DISPROVED**（读取正确）。**O-04（P3）**：兜底常量需人工跟随版本；若未来 beta7 代码缺 meta，会把新场景错误 stamp 成 beta6（对旧引擎变成“可读”），同时会误拒 beta7 场景。当前 beta6 下无实际危害。

### P-06 · 版本事实源是可变 json：改 meta 即改变闸门 —— **P-PROVED（P2）**

1) **位置**：sceneio.py:75-89（每次 import 读安装目录文件）、:154（cur = ENGINE_VERSION）、:159（比较）；LoomHub/hub_install.py:36-61（解包安装无哈希/签名）；release_github.py 无 sha256（grep 0 命中）。
2) **契约**：D7/Q-VER-2 的意图是“旧引擎读新场景明确拒绝”，即引擎实际代码能力应决定是否放行。
3) **路径枚举**：① 正常整包安装（meta 与代码同源）；② 只替换 exe（旧 meta）；③ 只替换/编辑 meta；④ 手工改安装目录 json；⑤ 第三方改 zip。
4) **实际**（真实编译产物 p3 B 段）：
   - 原 meta=0.1.0.beta6：beta10 场景 exit=2（拒绝）；
   - 只把 Loom/解释器.json 改成 0.1.0.beta10（exe 一个字节未换）：同一 beta10 场景 **exit=0、bench 正常跑完**；
   - 反向验证（p2）：篡改后 scene_to_dict 会把新场景 stamp 成篡改值（9.9.9）。
5) **差异**：预期“代码版本决定”；实际“可编辑文本决定”。旧 beta6 代码在新场景上会静默丢字段，正是闸门要防的后果。
6) **触发条件**：混合安装（只换 exe/meta）、手工编辑、被脚本改写；不需要改二进制。
7) **验证**：py -3.13 Loom/tests/_tmp/audit_b6r6_03_p3_real_artifact.py（附录 A3）。
8) **影响/等级**：**P2**（需要写安装目录；正常整包安装不触发；但一旦触发后果是静默丢字段）。若威胁模型包含“可写安装目录=不可信”，应升 P1。见 U-03。

### P-07 · 打包断言本身（④前半）—— **DISPROVED**（按设计工作）

1) **位置**：build_engine.py:118-138（_source_engine_version/_assert_meta）、:193（编辑器 dist）、:242（运行时 dist）；package_engine_compiled.py:102-104（编辑器 dist meta）、:122-125（运行时 meta）、:197-207（写后回读）、:222-232（zip 自检）。
2) **契约**：产物必须带 解释器.json 且 version == 源码/发布版本，否则拒绝。
3) **路径枚举**：缺文件 / 坏 JSON / 版本不等 / version 非字符串 / 正常。
4) **实际**（p7 A 段）：
   - 缺失 → SystemExit + “缺 解释器.json（会静默走 sceneio 常量兜底）”；
   - 损坏 → SystemExit + JSONDecodeError；
   - 0.1.0.beta5 != 0.1.0.beta6 → SystemExit；1（int）→ SystemExit（AttributeError 被兜住）；
   - beta6 == beta6 → 正常返回。
5) **差异**：无（对“文件存在且文本一致”这一层，断言成立）。
6) **触发条件**：构建/打包期。
7) **验证**：py -3.13 Loom/tests/_tmp/audit_b6r6_03_p7_pkg_assert.py（附录 A7）。
8) **影响**：**P-DISPROVED**（设计内成立）。**O-05（P3）**：_assert_meta 前刚由 _sync_data_dirs 把源码 meta 拷进 dist（:167-178），所以该断言证明的是“拷贝成功”，不是“二进制由该源码编出”；不构成 provenance 校验（见 P-08）。

### P-08 · 改 dist meta + --version 可把旧代码重贴成新版本（④中段）—— **P-PROVED（P2）**

1) **位置**：package_engine_compiled.py:72-73（version = PE.load_version(args.version)）、:102-104（只比 dist meta）、:131-188（复制 dist、重写 meta）、:212-232（zip 自检只读回自己写的 meta）。
2) **契约**：Q-VER-2=A “产物版本元数据与发布版本一致”，隐含产物代码就是该版本。
3) **路径枚举**：① 原 dist + 原 version；② 原 dist + 改 --version（被 meta_version_problems 拦住）；③ **改 dist meta 成目标 version + 同值 --version**（当前放行）；④ 再改 zip 内 meta（无签名，放行）。
4) **实际**（p7 C 段，合成 dist，仅验证断言边界）：
   - meta_version_problems(dist,'0.1.0.beta10') 原 dist 返回 mismatch；把 dist meta 改成 beta10 后返回 []；
   - 完整跑 package_engine_compiled.main()（临时 ENGINE_DIR/DIST_DIR）→ 成功产出 Loom-0.1.0.beta10-compiled.zip；
   - zip 内 Loom/解释器.json.version=0.1.0.beta10，但 Loom/Loom.exe 内容仍是标记 OLD_EDITOR_CODE_0.1.0.beta6，build_info.built_at=2026-01-01（未被校验）；
   - 嵌套 player_runtime/game_player.dist/解释器.json 也由同一手改成 beta10（版本断言被“一起改”满足）。
   - p11（真实编译包 zip 后篡改）：把 zip 内 Loom/解释器.json 改成 beta10 后，hub_install.read_zip_metadata 读到 version=0.1.0.beta10，hub_config.validate_meta 返回 None（接受）；无哈希/签名拦截。
5) **差异**：预期“断言保证代码/元数据/版本一致”；实际“断言只保证文本一致”，不建立代码→meta 的绑定。
6) **触发条件**：发布操作者直接改 dist meta 或复用旧 dist；无需改打包器。
7) **验证**：py -3.13 Loom/tests/_tmp/audit_b6r6_03_p7_pkg_assert.py（附录 A7-C）。
8) **影响/等级**：**P2**（发布完整性）。建议：在 meta 写 build_git/built_at 并让打包器校验“dist 构建时间/提交 = 当前源码”；或要求编译产物由本次构建目录直接产出、禁止复用。

### P-09 · 源码包断言缺口：--version 可重贴；嵌套运行时 meta 不校验（④后段）—— **P-PROVED（P2）**

1) **位置**：package_engine.py:35-39（--version 覆盖）、:61-67（只查格式白名单）、:480-505（_meta['version'] = version 无条件重写）、:425-467（拷运行时，不校验其 meta）、:533-578（_verify_zip 只读顶层 meta）；对照 package_engine_compiled.py:122-125 有嵌套 meta 校验。
2) **契约**：Q-VER-2=A “打包链把 解释器.json 带进产物并断言”；两个打包器应同口径。
3) **路径枚举**：① 缺省（version 来自源码 meta）；② --version 覆盖且与源码不同；③ 运行时 dist 的 meta 版本不同；④ zip 顶层 meta 与嵌套 meta 不同。
4) **实际**：
   - p10：meta_version_problems(engine,'0.1.0.beta99') 返回 mismatch（说明检查函数存在），但 package_engine.py 内 meta_version_problems( 只出现 1 次（def），**无调用**；make_zip('0.1.0.beta99') 成功产出 zip，包内 meta=beta99，而 Loom/sceneio.py 代码标记仍是 0.1.0.beta6，_verify_zip 打印“自检通过”；
   - p7 D：构造顶层 meta=beta6、嵌套运行时 meta=beta5 的 zip，_verify_zip 仍“自检通过”；同一嵌套目录交给 meta_version_problems 会报 mismatch（证明只是没调用）。
5) **差异**：预期两个打包器同口径；实际源码包缺“源码版本 == 发布版本”和“嵌套运行时 == 发布版本”两道检查。
6) **触发条件**：直接 py tools/package_engine.py --version X（文档用法）；或运行时 dist 比版本旧。
7) **验证**：py -3.13 Loom/tests/_tmp/audit_b6r6_03_p10_source_relabel.py、..._p7_pkg_assert.py D 段（附录 A10/A7-D）。
8) **影响/等级**：**P2**（可产出“版本更高但代码更旧”的包；旧引擎逻辑 + 新 meta 正是 P-06 的静默丢字段条件）。建议：make_zip 首行校验 meta_version_problems(ENGINE_DIR, version)，并在 _verify_zip 校验嵌套运行时 meta。

### P-10 · 同版本不同构建（⑤）—— **P-PROVED（P2，覆盖缺口而非比较 bug）**

1) **位置**：sceneio.py:141-163（只看 min_engine_version）、:1933-2004（migrate 不比较 data['version'] 与 SCENE_VERSION）、:1822（写侧只写版本字符串）；产物 tools/dist/Loom-0.1.0.beta6-source.zip。
2) **契约**：D7 的目标是“旧引擎读新场景明确拒绝”（sceneio.py:64-67）；版本字符串是唯一身份。
3) **路径枚举**：① 同版本不同 git 提交；② 场景 version > SCENE_VERSION 但无 min_engine_version；③ 有字段但等于当前版本、内容含未知键；④ 第三方/Hub 写场景不写字段。
4) **实际**：
   - 本地源码包（07:35 写出，包名/meta 都是 0.1.0.beta6）：包内 SCENE_VERSION = 10、无 check_engine_version、run_player.py 无 handle_scene_version_error；其 MyGame.exe 不含 min_engine_version/SceneVersionError/handle_scene_version_error 字符串 → **该 beta6 包完全没有版本闸**。同目录的编译包（13:47）有闸。两者版本字符串相同，闸门无法区分。
   - p9：{'version': 12, 'min_engine_version': None}、{'version': 12}、{'version': 12, 'min_engine_version': '0.1.0.beta6'} 全部 migrate OK 且 version 被降为 11；check_engine_version 均返回 True。即：**更高的 version 字段本身不被用作第二道闸**，只有写入方自愿写 min_engine_version 才受保护。
5) **差异**：预期“更高版本场景被拒”；实际“只有带可解析 min_engine_version 且高于当前版本才拒”；同版本标签/缺字段的新场景被静默降级加载。
6) **触发条件**：同一 betaN 下多次构建（nightly/临时修）；第三方或手写场景不写字段；发布时误用旧包。
7) **验证**：py -3.13 Loom/tests/_tmp/audit_b6r6_03_p9_same_version.py；源码包检查命令见附录 A9。
8) **影响/等级**：**P2**（当前 beta6 的正式场景由 scene_to_dict 写字段，主路径受保护；覆盖缺口在“没有字段/同标签旧构建/发布用错包”）。建议：发布流程保证“一次构建一个唯一版本”；migrate 增加 version > SCENE_VERSION 拒绝（留 Hub/手写的显式逃生开关）；长期在 meta 加 min_engine_build/git SHA 并参与比较。

### U-01 · 本地 beta6-source.zip 是否属于待发布物（UNKNOWN）

- 背景：它被 .gitignore 忽略，是本地暂存产物；但它与正式发布包同目录、同命名、同 meta 版本，且完全不含闸门。
- 已有证据：P-10 第 4 段。
- 需要人类回答的封闭问题：**这个 zip 是待发布/可被误发的候选包（→ 必须在发布前删除或重建，否则 P1），还是仅历史测试产物（→ 关闭，但建议删除避免误用）？**

### U-02 · min_engine_version 非字符串/不可解析时的期望策略（UNKNOWN）

- 背景：:150-152 非 str 静默放行；:155-158 不可解析字符串告警后放行；release 播放器无控制台时告警不可见。
- 需要人类回答：**保持“放行 + 告警”（向后兼容），还是改成“拒绝 + 可见错误”？** 选 A 则需把告警写日志/弹窗；选 B 则需评估第三方场景兼容。

### U-03 · meta 与二进制是否要建立可信绑定（UNKNOWN）

- 背景：P-06/P-08 证明改一个可写 json 即可改变闸门行为；LoomHub 安装无哈希/签名。
- 需要人类回答：**接受“安装目录可写 = 可信基”并只做一致性断言（当前），还是要求 meta 带构建身份/签名并让运行时校验？** 前者成本低但挡不住混合安装；后者改动大，需要人类选路线。

## 3. 统计

| 结论 | 数量 | 明细 |
|---|---|---|
| P-PROVED | **6** | P-03（P2）、P-04（P2）、P-06（P2）、P-08（P2）、P-09（P2）、P-10（P2） |
| P-DISPROVED | **4** | P-01（核心语义）、P-02（四条主路径）、P-05（读取/兜底）、P-07（断言设计内） |
| P-UNKNOWN | **3** | U-01、U-02、U-03 |
| P-CONTRADICTION | **0** | — |

补充 P3 观察（不计入上表）：O-01 4 段版本截断；O-02 非 str 静默；O-03 不可解析告警在 release 不可见；O-04 兜底常量需人工同步（写侧）；O-05 _assert_meta 证明的是拷贝而非二进制来源。

## 4. 修复建议排序（只给方向）

1. **P2｜两个打包器同口径**：package_engine.make_zip 写 meta 前调用 meta_version_problems(ENGINE_DIR, version)（不允许 --version 与源码 meta 分叉，除非显式 --allow-relabel）；_verify_zip 增加嵌套 player_runtime/game_player.dist/解释器.json 的版本校验（与 package_engine_compiled.py:122-125 对齐）。
2. **P2｜发布身份**：meta 增加 build_git/built_at（build_info 已有 built_at，但没被断言）；发布前置检查拒绝“dist/运行时构建时间早于源码提交”或“复用旧 dist”；清理 tools/dist 中的旧源码包。
3. **P2｜播放器入口收口**：build_entry.py 的 --run/旧 游戏配置.json 与 loom_player_window._init_engine 复用 run_player.run_backend/handle_scene_version_error；把“弹窗/日志/exit 1”作为三选一的硬验收。
4. **P2｜同版本覆盖**：migrate 在 min_engine_version 缺失时若 data['version'] > SCENE_VERSION 则拒绝（或至少告警到日志）；版本发布纪律：每次构建唯一版本号。
5. **P3｜边界**：非 str 的 min_engine_version 也走“告警/可见记录”；4 段版本要么明确支持要么在写入/打包白名单拒绝；兜底常量与源码 meta 的一致性纳入发版自检。
6. **测试**：新增负向回归：改 dist meta + --version 必须失败；源码 --version 分叉必须失败；嵌套运行时 meta 分叉必须失败；build_entry --run / 远程窗口遇高版本必须弹窗/退出（无 GUI 用 NO_DIALOG 断言打印与 exit 码）。

## 5. 需要人类裁决的封闭问题

1. **U-01**：Loom-0.1.0.beta6-source.zip 是待发布候选（→ 发布前删除/重建）还是历史测试产物（→ 直接删除）？
2. **U-02**：非字符串/不可解析的 min_engine_version：A 保持放行但必须可见（写日志/弹窗）；B 改为拒绝加载；C 维持现状（接受静默）。
3. **U-03**：meta 与二进制的信任基：A 接受“安装目录可写=可信”（当前）；B 增加构建身份/签名并运行时校验；C 只对官方发布链做构建身份检查（本地手工安装不保证）。

## 6. 附录：探针清单与关键实测输出

探针均在 Loom/tests/_tmp/（被忽略），可直接复跑：

| 探针 | 用途 |
|---|---|
| audit_b6r6_03_p1_version_semantics.py | 版本比较矩阵（20 个 parse、10 个 lt、13 个闸门分支） |
| audit_b6r6_03_p2_engine_version_paths.py | meta 存在/缺失/损坏/类型错；篡改 9.9.9；写侧 stamp |
| audit_b6r6_03_p3_real_artifact.py | 真实编译包：meta 原样/改 beta10/删除/损坏 × 场景 beta6/beta10 |
| audit_b6r6_03_p4_binaries.py | 包内 Loom.exe/MyGame.exe 字符串与 build_info 时间线 |
| audit_b6r6_03_p5_editor_prefab.py | 无头编辑器拒载保留旧场景 + prefab 双入口 |
| audit_b6r6_03_p6_run_entry.py | 源码 Loom.py --run vs 编译版 Loom.exe --run |
| audit_b6r6_03_p7_pkg_assert.py | _assert_meta 矩阵 + 编译包重贴 + 源码 _verify_zip 嵌套 |
| audit_b6r6_03_p8_entry_contrast.py | 同一场景 Loom.exe vs MyGame.exe --run |
| audit_b6r6_03_p9_same_version.py | v12 无字段/等版本字段的接受与降级 |
| audit_b6r6_03_p10_source_relabel.py | 源码包 --version 重贴（合成最小树，临时目录） |
| audit_b6r6_03_p11_zip_tamper.py | 真实编译包 zip 后改 meta，LoomHub 读取/校验是否接受 |

**A1（p1）关键输出**

~~~text
ENGINE_VERSION = '0.1.0.beta6'
'0.1.0.beta10' -> (0, 1, 0, 0, 10)
'0.1.0'        -> (0, 1, 0, 1, 0)
'0.1.0.7'      -> (0, 1, 0, 1, 0)
'0.1.0.beta6+build7' -> None
lt('0.1.0.beta6', '0.1.0.beta10') = True
lt('0.1.0.beta6', '0.1.0')        = True
check: higher beta10 -> SceneVersionError（原因含 0.1.0.beta10 / 0.1.0.beta6）
check: number(0.2)   -> PASS(True)   # 无告警
check: garbage       -> PASS(True)   # 有 [场景] 告警
~~~

**A2（p2）关键输出**

~~~text
real ENGINE_VERSION = '0.1.0.beta6'
valid beta7 -> '0.1.0.beta7'; valid beta10 + ws -> '0.1.0.beta10'
missing/corrupt/version int/version empty/no key/wrong filename -> '0.1.0.beta6'
tampered ENGINE_VERSION=9.9.9: check(beta10)=True; scene_to_dict min=9.9.9
fallback ENGINE_VERSION=beta6: scene_to_dict min=0.1.0.beta6
~~~

**A3（p3）真实编译包矩阵（--bench ... 1）**

~~~text
[A] 产物 meta=beta6   : scene min=beta6 exit=0 (bench_result.txt 有 FPS)
                         scene min=beta10 exit=2 (bench_error.txt: SceneVersionError)
[B] meta 改成 beta10  : scene min=beta10 exit=0   <-- 同一 exe，仅改 meta
                         scene min=beta6  exit=0
[C] meta 删除         : scene min=beta10 exit=2（兜底 beta6）
[D] meta 损坏         : scene min=beta10 exit=2（兜底 beta6）
~~~

**A7（p7）断言与重贴**

~~~text
_assert_meta: missing/corrupt/mismatch/int -> SystemExit; match -> None(通过)
meta_version_problems: dist=beta6 vs 请求 beta10 -> ["version='0.1.0.beta6' != '0.1.0.beta10'"]
                       把 dist meta 改成 beta10 -> []
编译包 main(--version 0.1.0.beta10, dist meta 已改) -> 成功
zip 内 meta=0.1.0.beta10；Loom.exe 仍为 OLD_EDITOR_CODE_0.1.0.beta6；built_at=2026-01-01
_verify_zip(源码包, 顶层 meta=beta6, 嵌套运行时 meta=beta5) -> “自检通过”
（对照 meta_version_problems -> ["version='0.1.0.beta5' != '0.1.0.beta6'"]）
~~~

**A8（p8）两入口对比**

~~~text
Loom.exe  --run newer : exit=1，stdout 末行 "[错误] 无法启动渲染引擎: 场景要求引擎 >= 0.1.0.beta10 ..."
                        无「无法打开场景（引擎版本过低）」；无弹窗（二进制无 handle_scene_version_error）
MyGame.exe --run newer: exit=1，stdout 含 Q-VER-1 文案与 “[场景] (未弹窗: ... LOOM_NO_DIALOG=1)”
                        （未设 NO_DIALOG 时会走 show_blocking_dialog）
~~~

**A9（源码包 / 旧构建）**

~~~text
tools/dist/Loom-0.1.0.beta6-source.zip  mtime=2026-11-10 07:35:52
Loom/解释器.json.version = 0.1.0.beta6
Loom/sceneio.py: SCENE_VERSION = 10；check_engine_version 不存在
Loom/run_player.py: handle_scene_version_error 不存在
Loom/player_runtime/game_player.dist/MyGame.exe: min_engine_version/SceneVersionError/handle 均不存在
~~~

**A10（p10）源码包重贴**

~~~text
meta_version_problems(engine, beta99) -> ["version='0.1.0.beta6' != '0.1.0.beta99'"]
make_zip(beta99, --allow-missing-runtime) -> Loom-0.1.0.beta99-source.zip
zip 内 meta.version=0.1.0.beta99；sceneio.py 代码标记 ENGINE_CODE_MARKER='0.1.0.beta6'
输出：“[打包] 自检通过: 包名/元数据/运行时一致（版本 0.1.0.beta99, 精简包）”
~~~

**A11b（p11）zip 后篡改**

~~~text
zip 名 = Loom-0.1.0.beta10-compiled.zip
read_zip_metadata.version = 0.1.0.beta10 prefix = Loom/
validate_meta = None（None = 通过）
zip size = 136396936
~~~

**A12（p9）future scene**

~~~text
v12 + min=beta6  -> migrate OK, version=11
v12 + min=null   -> migrate OK, version=11
v12 no field     -> migrate OK, version=11
check_engine_version(...) = True（四种）
~~~

**受跟踪状态**：本编号开始与结束均未改动任何受跟踪文件；审计期间 git status --porcelain 出现的 Loom/loom_components.py、Loom/loom_frame_components.py、Loom/loom_physics.py、Loom/scene_driver.py、Loom/tests/test_animation_base.py、docs/design/待裁决清单_beta6.md 与新增的 docs/audit/scan_beta6_round6_02_*.md 均属其他编号代理，与本报告无关。
