# 最终验收审计 · 编号 04：跨批一致性与死代码

> 审计对象：beta6 相对 beta5 的全部改动（跨批：文档 / 代码 / 测试 / 打包脚本）
> 基线：`08ad3a3`（beta5 发布点） → HEAD `a0b0ae0`
> 结论口径：每条结论 = 文件:行号 + 可执行命令 + 实测输出。无实测输出的一律不写。

---

## 0. 范围与基线

### 0.1 改动规模（实测）

```
$ git diff --shortstat 08ad3a3..HEAD
198 files changed, 26529 insertions(+), 875 deletions(-)
```

> 与派单给出的「189 文件 / +23580 / -837」有差：派单测量点更早（其后新增 `a0b0ae0` 第六轮审计文档与 `1d1f8f6`/R6-01 整改）。本报告一律以实测 198/+26529/−875 为准。

### 0.2 方法（只读 + 探针）

全部探针写入 `Loom/tests/_tmp/final_04_*.py`，不改任何受跟踪文件；收尾 `git status --porcelain` 为空（见 §5）。
用到的 12 个探针：

| 探针 | 作用 |
|---|---|
| `final_04_versionchain.py` | 15 个版本真源交叉取值 |
| `final_04_deadfn3.py` | AST 扫「定义 1 次、引用 0 次」的函数（含装饰器排除） |
| `final_04_deadcls.py` | 同类扫描：类 |
| `final_04_envscan.py` | 环境变量定义/读取点计数 |
| `final_04_diffenv.py` | beta6 新增环境变量 |
| `final_04_doccov.py` | 环境变量在 .md/.txt 的文档命中 |
| `final_04_gates.py` | 逃生门读取点总数 + 已退役门残留 |
| `final_04_cmds2.py` | EAI / HUB-EAI 注册命令数（AST，非注释） |
| `final_04_docmatrix.py` | beta6 十项能力在五份顶层文档的命中矩阵 |
| `final_04_srcassert4.py` | 测试里「断言源码文本」的处数 |
| `final_04_testentry.py` | 测试是否触达真实入口模块 |
| `final_04_py312.py` | `py -3.12` 残留分布 |

---

## 1. 目标达成判定表

判定分两栏：**代码/测试是否达成**（可跑）与**文档是否同步**（可 grep）。二者分开，避免"实现了但没人知道"被算成完成。

| # | beta6 原定目标（版本计划 §7/§9） | 代码证据 | 测试证据 | 五份顶层文档命中 | 判定 |
|---|---|---|---|---|---|
| G1 | 批次 0：工具链升级 → Nuitka 4.3.5 / Python 3.13.15 | `Loom/解释器.json:4`=`3.13.15`；`tools/build_engine.py:33-42` 两档目录 | `tools/build_engine.py:271` 硬门「必须用 py -3.13」 | 使用操作指南 §7.5、架构总表 §10.2 已改 | **达成** |
| G2 | 批次 A：FramePlan + tonemap + bloom | `Loom/loom_pass.py`(13.6K) / `loom_pass_gl.py`(10.4K) / `loom_post*.py` | `test_frame_plan.py` 383 行（含 D 段真实 GL 4.3 上下文）+ `test_post_bloom.py` | `frame_plan`/`loom_pass`/`bloom`/`tonemap`/`LOOM_POST` = **0/0/0/0/0** | **代码达成 / 文档 0 覆盖** |
| G3 | 批次 B：资产 guid + 打包带 assets | `Loom/loom_assets.py`(38K)、`SCENE_VERSION=11`(`sceneio.py:58`) | `test_asset_guid.py` 1079 行；资产命令走 `ac.dispatch` 真入口（`test_eai_real.py:636-653`） | `assets.json`/`loom_assets`/`asset_import` = **0/0/0** | **代码达成 / 文档 0 覆盖** |
| G4 | 批次 C：动画底座（SoA/时间落盘/序列化 v2） | 见 `docs/design/research_beta6_03` 落地项 | `test_animation_base.py` 1103 行 | 无新增文档 | **代码达成 / 文档 0 覆盖** |
| G5 | 批次 D：热点下沉（bucket_pack / 位姿 SoA / AABB AVX2） | `ckernels/loom_kernels.c:384/606/622`、`fastpath.py:501-504`、`physics_bridge.py:988 _pose_rows` | `test_bucket_pack.py`/`test_physics_pose_soa.py`/`test_aabb_simd.py` | `bucket_pack`/`AVX2`/`_pose_rows` = **0/0/0** | **代码达成 / 文档 0 覆盖** |
| G6 | D7：SCENE_VERSION 10→11 + min_engine_version | `sceneio.py:58`=11、`:72` fallback、`:1819-1822` 写出 | `test_animation_base.py:600-666`、`test_scene_version_gates.py` | 架构总表 §9 仍写 **v10**、代码架构.txt **7 处**写 v10 | **代码达成 / 文档口径相反** |
| G7 | 版本口径链自洽（解释器.json / ENGINE_VERSION / Hub / installer / 发布说明） | 见 §2.1 实测表（15 源全一致） | `test_release_version.py` → `总结果: ALL PASS ✅` | — | **达成** |
| G8 | 「延迟项必须落盘」（§10） | `路线登记_后续版本.md` 存在，N-01 仍挂 `loom_pose_sync`（代码 0 命中） | — | — | **达成（但 N-01 描述的实现路径已被 Python SoA 取代，属过期登记）** |

**小结**：beta6 的**工程目标（G1-G5、G7）全部达成且有可跑测试**；**唯一的系统性欠账是文档层**——G2/G3/G4/G5 四项交付在五份顶层文档里合计 **0 次**提及（§3.1）。

---

## 2. 逐项证据

### 2.1 版本口径链（③）：自洽，已实测

```
$ python Loom/tests/_tmp/final_04_versionchain.py
SOURCE                                 VALUE
Loom/解释器.json.version                  0.1.0.beta6
Loom/解释器.json.python_version           3.13.15
sceneio.ENGINE_VERSION                 0.1.0.beta6
sceneio.SCENE_VERSION                  11
LoomHub/版本.json                        0.1.4
installer.iss MyAppVersion             0.1.4
package_hub.load_version()             0.1.4
package_engine.load_version()          0.1.0.beta6
release_github.ENGINE_VERSION          0.1.0.beta6
release_github.HUB_VERSION             0.1.4
package_engine source_python_version() 3.13.15
test EXPECT_ENGINE                     0.1.0.beta6
test EXPECT_HUB                        0.1.4
README 环境要求 Python                     3.13
requirements.txt 安装命令                  3.13
```

15 个取值点 0 冲突；`test_release_version.py` 另有「环境变量分叉必须 exit 非 0」的子进程实测。**结论 P-DISPROVED（无版本口径不一致）**。

**但版本链只覆盖"打包器 ↔ 发布器 ↔ 安装器"这一条**，不覆盖「文档里写的版本号」。后者见 §2.3。

### 2.2 死代码（②）：10 个零引用函数 / 65 行；4 个是 beta6 新增

```
$ python Loom/tests/_tmp/final_04_deadfn3.py
changed py files: 73 functions: 1993
=== zero-reference, NO decorator (real dead candidates): 10
  Loom\editor.py:1038  EditorApp._camera_depth  (8 lines)
  Loom\editor.py:1599  EditorApp._hex_to_rgb  (10 lines)
  Loom\editor.py:2076  EditorApp.edit_camera_pitch_bound  (18 lines)
  Loom\loom_assets.py:99  reset_caches  (4 lines)          <- NEW-in-beta6
  Loom\loom_gl_version.py:48  gl_version_text  (4 lines)   <- NEW-in-beta6
  Loom\sceneio.py:1928  scene_asset_summary  (3 lines)     <- NEW-in-beta6
  Loom\tests\test_ab_gl_vk.py:309  _fmt3  (2 lines)        <- NEW-in-beta6
  Loom\ui\loom_gui.py:133  AssetListWidget.mimeTypes  (2)  [Qt 覆写，非死码]
  Loom\vk_renderer.py:714  orbit_camera  (8 lines)
  LoomHub\hub_config.py:458  sanitize_name  (6 lines)
=== zero-reference but decorated (dynamically registered, not dead): 92
```

排除口径说明（防误报）：`@command(...)` 装饰器把函数名注册进 `_COMMANDS`（`agent_commands.py:308-314`），所以 92 个 `cmd_*` 是**动态可达**、不算死码；`mimeTypes` 是 Qt 虚函数覆写。真正的判据是 grep 全仓（含 .c/.md/.json）0 次非定义引用：

```
$ grep -rn "\breset_caches\b" .   -> 1 hit (仅定义处 Loom/loom_assets.py:99)
$ grep -rn "\bgl_version_text\b" . -> 1 hit (仅定义处 Loom/loom_gl_version.py:48)
$ grep -rn "\bscene_asset_summary\b" . -> 1 hit
$ grep -rn "\b_fmt3\b" . -> 1 hit
```

**最能说明问题的一条**：`reset_caches()` 是给测试写的清缓存助手，但测试**绕过它**直接清私有变量——
```
Loom/loom_assets.py:99   def reset_caches():   """测试用: 清空索引缓存与告警去重。"""  _CACHE.clear(); _WARNED.clear()
Loom/tests/test_asset_guid.py:967   loom_assets._CACHE.clear()      <- 调用方走的是私有变量，不是这个 API
```
即：**唯一预期的调用方已经存在，却没有调用它**。

**新增死代码量**：4 函数 / **13 行**（reset_caches 4 + gl_version_text 4 + scene_asset_summary 3 + _fmt3 2）。

**重复实现**：`gl_version_text`（`:48-51`）与 `require_gl_version` 内联格式串（`:71`）是同一语义两份写法，且前者没人调用：

```
Loom/loom_gl_version.py:51  return 'OpenGL %s | 显卡 %s | 厂商 %s | version_code=%d' % (...)
Loom/loom_gl_version.py:71  '[GL] 当前: OpenGL %s | version_code=%d',
```

死类：**0**（`final_04_deadcls.py`：147 个类，0 个零引用）。

### 2.3 文档承诺 vs 代码实现（①）——四类，逐条给行号

#### (a) EAI 命令数：文档写 52 / 91，实测 102（工具自动注册，永远对不上）

```
$ python Loom/tests/_tmp/final_04_cmds2.py
EAI registered: 102
HUB-EAI registered: 21 ['status','interpreter_list',...,'quit']
hub decorators: {'command'}
```

| 文档:行号 | 承诺 | 实测 | 偏差 |
|---|---|---|---|
| `使用操作指南.txt:475` | 「…共 **52** 条命令」 | 102 | **−50%** |
| `docs/design/架构互联协议总表.md:3` | 「EAI **91**」 | 102 | −11 |
| `docs/design/架构互联协议总表.md:220` | 「**91** 个 cmd 方法」 | 102 | −11 |
| `docs/design/架构互联协议总表.md:235` | 「EAI 命令分类（**91** 个，实测 2026-11-06）」 | 102 | −11 |
| `docs/design/架构互联协议总表.md:222` | 「HUB-EAI **18** 命令」 | 21 | −3 |
| `开发进度与Unity对照.txt:26` | 「(52/16 条命令)」 | 102/21 | 大幅偏低 |
| `开发进度与Unity对照.txt:285` | 「agent_commands.py **52** 条命令」 | 102 | −50% |

反向核对（防"是不是只是数字写了没统计"）：102 条命令**全部**在测试里有引用，无死命令：
```
$ python Loom/tests/_tmp/final_04_eai_cov.py
registered EAI commands: 102
commands with NO test reference anywhere in tests/: 0
```

#### (b) SCENE_VERSION：文档写 v10，代码是 11（beta6 自己改的，文档没跟）

```
Loom/sceneio.py:58   SCENE_VERSION = 11  # v11 (beta6 B1 资产 guid)
代码架构.txt:54       │     ├── sceneio.py         序列化 (v10/迁移/Prefab/场景加密/gravity 字段)
代码架构.txt:151      │  sceneio.py    scene_to_dict / scene_from_dict (序列化 v10)│
代码架构.txt:309      - 序列化 v10: cameras 数组加 parent_id, ...
代码架构.txt:704      格式: JSON, SCENE_VERSION = 10。
代码架构.txt:728      migrate(): 老版本(v1..v9)自动升级到 v10 —— 旧场景可加载。
代码架构.txt:735      v9->v10 (相机物体化): ...
代码架构.txt:817      test_sceneio        序列化 v10 / ...
docs/design/架构互联协议总表.md:285  | 场景 JSON | sceneio.py | v10，含版本迁移 / Prefab / ... |
```
**8 处 v10 承诺，全部与 `SCENE_VERSION=11` 相反**。其中 `:728` 还声称"v1..v9 自动升级到 v10"——实际 `migrate()` 的终点是 11。

#### (c) README 承诺的目录不存在

```
README.md:85   │   └── 保存/              示例与压力场景
$ Test-Path "Loom\保存"      -> False
$ Get-ChildItem Loom | Where Name -eq Projects   -> 存在
```
beta6 改过 README（`git diff 08ad3a3..HEAD -- README.md`：仅 3.12→3.13 共 6 行），**同一次编辑没有修正这个早已失效的路径**。

#### (d) 模块契约文档还在承诺一个 2026-10-16 已删的逃生门

```
Loom/pipeline_glue.py:14   · LOOM_NO_PIPELINE=1 → 本模块整体禁用 (engine 回退现行 Python 路径)。
Loom/pipeline_glue.py:57   ★B2 退役 (2026-10-16): 删 LOOM_NO_PIPELINE 整体禁用门 + 静默降级。
```
同一文件头尾自相矛盾：`:14` 是模块对外契约（读者据此判断行为），`:57` 是退役说明。实测该 env 在 .py 里 0 个读取点（见 §2.4）。

#### (e) 顶层文档对 beta6 四批交付 = 0 覆盖（量化矩阵）

```
$ python Loom/tests/_tmp/final_04_docmatrix.py
能力                                使用操作指南  架构总表  代码架构  README  开发进度对照
FramePlan/Pass 抽象                  -        -       -      -      -
tonemap/bloom 后处理                  -        -       -      -      -
资产 guid (Assets/assets.json)        -        -       -      -      -
SCENE_VERSION=11                    -        -       1      -      -
动画 SoA/时间落盘                       -        -      11      -      2
bucket_pack 热点下沉                   -        -       -      -      -
AABB AVX2                           -        -       -      -      -
GL 4.3 地板                            2        6       -      -      -
Hub 精确选 Python                      -        -       2      -      -
VK 回退改配置                            7       11      33      -      8
```

二次核对（防"我的关键词不对"）：逐个 token 直接 grep 五份文档，全部 0 命中——
`frame_plan / FramePlan / loom_pass / bloom / tonemap / LOOM_POST / assets.json / loom_assets / asset_import / min_engine_version / bucket_pack / AVX2 / _pose_rows / assets_base`。
唯一有命中的是 `SCENE_VERSION`（代码架构.txt 1 处，值写错）与 `animator`（旧动画字段，与批次 C 无关）。

**判定**：批次 A/B/C/D 的交付**只存在于 `docs/design/research_beta6_0*` 与 `docs/audit/scan_beta6_*` 里**（设计/审计文档），**没有一份面向使用者或接手者的顶层文档提到它们**。

### 2.4 死配置与未文档化开关（② + ⑤）

#### (a) 规模

```
$ python Loom/tests/_tmp/final_04_envscan.py
py files scanned: 273
distinct env keys: 58
--- LOOM_* keys (count 49) ---
$ python Loom/tests/_tmp/final_04_gates.py
LOOM_* env read sites: 73 in 32 files
```

> 口径修正（自查）：上表只统计字面量 `os.environ.get('字面量')`；另有 4 个键经变量名动态读取（`loom_post._env_float` → `LOOM_BLOOM_THRESHOLD / _KNEE / _STRENGTH / LOOM_POST_EXPOSURE`，见 `Loom/loom_post.py:58-64`）。所以**真实规模 ≥ 62 个键**。另：`docs/design/架构互联协议总表.md:329` 写「逃生门总表（**250+ 处**）」，实测读取点 **73 处**——该数字是历史累计口径，当前代码不支持。

#### (b) 12 个 env 在任何 .md/.txt 里 0 命中

```
$ python Loom/tests/_tmp/final_04_doccov.py
UNDOCUMENTED (0 hits in any .md/.txt outside tests): 12
  LOOM_AABB_POOL_THRESHOLD, LOOM_BUILD_CONSOLE_MODE, LOOM_BUILD_ROOT, LOOM_BUILD_RUNTIME_DIR,
  LOOM_FAULTHANDLER, LOOM_GAME_ID, LOOM_GL_DEBUG, LOOM_POST_STAGE, LOOM_PROJECT_DIR,
  LOOM_PYEMBED_CACHE, LOOM_REMOTE_PROFILE, LOOM_BLOOM_STRENGTH
```

其中 **6 个是 beta6 新增**（`final_04_diffenv.py`：beta6 共新增 20 个 env 键）：
`LOOM_BUILD_CONSOLE_MODE` / `LOOM_BUILD_ROOT` / `LOOM_BUILD_RUNTIME_DIR` / `LOOM_FAULTHANDLER` / `LOOM_POST_STAGE` / `LOOM_PYEMBED_CACHE`。

#### (c) ⑤ 的核心证据：作者自己写了"定稿前清理"，但没清理

```
Loom/loom_post.py:47  def post_stage():
Loom/loom_post.py:48      """**诊断用**分级开关（2026-11-10 编译版崩溃二分；定稿前清理）。
Loom/loom_post.py:53      return max(1, min(3, int(os.environ.get('LOOM_POST_STAGE', '3'))))
```
- HEAD 已到 beta6 审计第 7 轮（`a0b0ae0`），`LOOM_POST_STAGE` 仍在产品路径（`post_enabled()` 依赖它，`:44`）；
- 文档 0 命中（§2.4b）；
- 它的存在直接改变生产行为：`LOOM_POST_STAGE=1` 时 bloom 整条链被跳过。

#### (d) beta5 之前的遗留调试开关，至今仍在产品路径且未文档化

| 开关 | 引入提交 | 位置 | 行为影响 | 指南/文档命中 |
|---|---|---|---|---|
| `LOOM_FLICKER_DEBUG` | `89141af`（Initial commit） | `Loom/ui/loom_gui.py:3801+` | **每帧读回中心 1px**（GL readback），命中差异即打印 | 0 |
| `LOOM_GL_DEBUG` | `a3eff38` | `Loom/ui/loom_gui.py`（paintGL 内） | 每帧打印 FBO/DPR 诊断 | 0 |
| `LOOM_REMOTE_PROFILE` | — | `Loom/ui/loom_gui.py`（2 处） | 每 30 帧打印分段耗时 | 0 |
| `LOOM_VK_DEVMOUSE` | `f53a82a` | `Loom/vk_player.py:567` | 改 VK 鼠标驱动行为 | 0（仅审计文档） |
| `LOOM_VK_HUD` | — | `Loom/vk_player.py:640` | 打开 VK 侧调试 HUD | 0（仅审计文档） |

`LOOM_FLICKER_DEBUG` 是最坏的一个：它是 **per-frame GPU readback**，一旦被写进用户环境变量，性能结论立即失真——而这正是 beta6 批次 D 用 FPS 做验收的门槛所依赖的量。

#### (e) 反向核对（防"死配置"误判）：引擎 `设置.json` 15 个键**全部有用**

```
$ python Loom/tests/_tmp/final_04_settings.py
设置.json keys: 15
  gui / save_dir / parallel_enable / script_cores / show_grid / fps_limit / precise_limit /
  cam_speed / gravity / logic_fps / interp_mode / frame_buffer_tps / frame_buffer_fps /
  render_api / physics_fps      -> 每个键在非测试代码里都有引用
```
**P-DISPROVED**：不存在"定义了从不读取"的设置项。同理 `LOOM_BLOOM_* / LOOM_POST_EXPOSURE` 也不是死配置（`loom_post.py:60-63` 真读）。

### 2.5 测试是否"过拟合测试环境"（④）

#### (a) 直接断言源码文本的检查点：38 处 / 12 文件（另 test_frame_plan 3 处）

```
$ python Loom/tests/_tmp/final_04_srcassert4.py
=== check() 断言『源码文本含/不含某子串』(*src 命名变量): 38 处 / 12 文件
  test_hub_python_version.py   7      test_render_api.py      5
  test_hub_update.py           4      test_vk_camera_align.py 4
  test_backend_fallback_policy.py 3   test_skybox_scene.py    3
  test_bench_result_path.py    2      test_beta3_batch2_camera_proj.py 2
  test_hub_install_root.py     2      test_hub_interp_cache.py 2
  test_hub_interp_switch.py    2      test_vk_ui_stroke.py    2
```
最典型的（用"源码里有这行字"替代"行为正确"）：
```
Loom/tests/test_hub_eai.py:383      'prefer 读 open_py 设置': 'load_settings' in ctrl_src
Loom/tests/test_hub_python_version.py:184  check('改为直接读 sys.version_info（Q5=B）', "'%d.%d' % (sys.version_info[0], sys.version_info[1])" in src)
Loom/tests/test_frame_plan.py:85-88  check('B3 编辑器调用 frame_plan(include_shadow=..., ...)', 'frame_plan(include_shadow=' in src_e)
Loom/tests/test_frame_plan.py:89-90  check('B5 编辑器不再手写清屏字面量 0.10, 0.12, 0.16', '0.10, 0.12, 0.16' not in src_e)
```
性质：**"不出现某字样"的断言（B5、test_vk_ui_stroke:122-123、test_render_api:355/579）是防回归的好手段**；但"出现某字样"的断言（上面 3 条）只是证明了"有人写了这行"，不证明"这行被执行/参数正确"。AI 只需插入该字符串即可过测。

#### (b) 是否只调 helper 不调真实入口（量化）

```
$ python Loom/tests/_tmp/final_04_testentry.py
  test_aabb_simd.py            entry=-                                    standalone_ctx=False
  test_bucket_pack.py          entry=-                                    standalone_ctx=False
  test_physics_pose_soa.py     entry=-                                    standalone_ctx=False
  test_post_bloom.py           entry=-                                    standalone_ctx=False
  test_scene_version_gates.py  entry=-                                    standalone_ctx=False
  test_frame_plan.py           entry=editor                               standalone_ctx=True
  test_ab_gl_vk.py             entry=editor,scene_driver                 standalone_ctx=True
  test_asset_guid.py           entry=editor,engine                        standalone_ctx=False
  test_animation_base.py       entry=engine,scene_driver                  standalone_ctx=False
```
判断：`bucket_pack / aabb_simd / pose_soa` 三个 D 批测试都**只打到 `fastpath` / `physics_bridge` 这一层内核**，没有一条受跟踪断言证明 `loom_render` / `engine` 的调用点**真的走了新内核**。三者的接线证据当前只在设计文档的实测表里（`research_beta6_04` 附录 F/G），不在回归里。**这是"helper 级绿 + 入口级无证据"的典型缺口**（P2）。

#### (c) 全量测试文件数：文档写 121/126/128，实测 133

```
$ (Get-ChildItem Loom\tests -Filter "test_*.py" -File).Count   -> 133
Loom/tests/run_all.py:26-28  glob(test_*.py) + 追加 test_integration.py  -> 跑 133 个
```
文档侧：`版本计划` §9.4/§9.11 写 121 / 313 项，§9.15 写「全量 **126 文件**绿」，`research_beta6_04` F.6 写「全量 **128 文件**」。三者都是当时的快照，且 `research_04` F.6 自己写着"见本次回报（若本轮未跑完则由下一轮补记）"——**该条至今没有闭合记录**。

### 2.6 `py -3.12` 残留（③ 的文档侧）

```
$ python Loom/tests/_tmp/final_04_py312.py
tracked files with 'py -3.12': 72 total occurrences: 240
  in beta6-touched files: 19
```
其中**操作性**（照抄会出错或误导）的 6 处：

| 文件:行 | 内容 | 问题 |
|---|---|---|
| `Loom/build_entry.py:1` | `#! python3.12` | shebang 仍是 3.12（指南 §0 已承认并解释） |
| `Loom/build_entry.py:373` | `py -3.12 -m pip install pygame moderngl` | **缺依赖时的报错指引**指向 3.12；按 README 应装到 3.13 |
| `Loom/tests/run_all.py:3` | `用法: py -3.12 tests\run_all.py` | 一键回归的用法行 |
| `使用操作指南.txt:65` | 「把 `-3.12` 换成目标版本号」 | 与同文件 `:22`「Python 3.13.15」自相矛盾 |
| `使用操作指南.txt:67-68` | 「已绑定 3.12.10 解释器，双击即用 3.12.10 运行」 | 同上 |
| `代码架构.txt:959` | `打包: Nuitka standalone exe (py3.12 + build_entry.py)` | 打包口径反了 |

其余 234 处集中在 `docs/audit/*`、`docs/archive/*`、`AI工作排查笔记/*`（历史快照，可接受）与 `tools/loom_lint_except.py`（工具自带示例，与本工程版本无关）。

**这份"接受/不接受"的界线本身没有写进任何规范**——这是 §4 要人类裁决的问题之一。

---

## 3. 统计

### 3.1 一致性统计

| 指标 | 数值 |
|---|---|
| beta6 改动 | 198 文件 / +26529 / −875 |
| 版本真源交叉核对 | 15 源 / 0 冲突 |
| `py -3.12` 残留 | 240 处 / 72 个受跟踪文件（操作性 6 处） |
| SCENE_VERSION 文档错写 | 8 处（代码架构 7 + 架构总表 1） |
| EAI 命令数文档错写 | 7 处（52×2 / 91×3 / 18×1 / 52-16×1） |
| beta6 十项能力在五份顶层文档的命中 | **5 项有命中 / 5 项 0 命中**（且 `SCENE_VERSION` 那一处写的是错值 v10，`动画 SoA` 命中的是旧 `animator` 字段，实为 4 项有效） |

### 3.2 死代码 / 死配置统计

| 指标 | 数值 |
|---|---|
| 死函数（全仓 0 引用，排除装饰器动态注册） | **10 个 / 65 行** |
| 其中 beta6 新增 | **4 个 / 13 行** |
| 死类 | 0（147 类全有引用） |
| 死 EAI 命令 | 0 / 102（全部在测试里出现） |
| 死设置项（`设置.json` 15 键） | 0 |
| env 键总数 / `LOOM_*` 读取点 | ≥62 键 / 73 处（32 文件） |
| 0 文档命中的 env | 12（其中 beta6 新增 6） |
| 生产路径上未文档化的调试开关（beta5 前遗留） | 5（`LOOM_FLICKER_DEBUG` 最重） |

### 3.3 测试质量统计

| 指标 | 数值 |
|---|---|
| 测试文件 | 133 |
| 「断言源码文本」检查点 | 38 处 / 12 文件（+ test_frame_plan 3 处） |
| 仅打到 helper、无入口级断言的 beta6 新测试 | 3（`test_bucket_pack` / `test_aabb_simd` / `test_physics_pose_soa`） |
| 全量文件数与文档口径差 | 133 vs 121 / 126 / 128 |

---

## 4. 需要人类裁决的问题

1. **顶层文档追认范围**：beta6 四批（FramePlan/后处理、资产 guid、动画、热点下沉）在五份顶层文档 0 覆盖。要不要在收尾前补一轮"顶层文档同步"？还是接受"以 `docs/design/research_beta6_0*` + `docs/audit/scan_beta6_*` 为唯一权威"？
2. **`LOOM_POST_STAGE` 的处置**：作者注释写着"定稿前清理"。删掉它（失去崩溃二分能力）、还是保留并写进指南的"诊断开关"小节？
3. **`py -3.12` 的判定线**：哪些文件里的 3.12 是"必须留的历史快照"（`docs/audit`/`docs/archive`），哪些是"必须改成 3.13"（`build_entry.py:373`、`run_all.py:3`、`代码架构.txt:959`、指南 §0）？建议：定一条"操作性文本（用户会照抄的命令/报错指引）一律 3.13；历史文档不改"的规则并落盘。

---

## 5. 只读自查

```
$ git status --porcelain
?? docs/audit/final_04_跨批一致性与死代码.md      <- 唯一新增项（本报告本身）
```
所有探针仅写 `Loom/tests/_tmp/final_04_*.py`（已被 `.gitignore` 覆盖，不在 git status 中出现），未修改任何受跟踪文件，未做任何 git add/commit。
