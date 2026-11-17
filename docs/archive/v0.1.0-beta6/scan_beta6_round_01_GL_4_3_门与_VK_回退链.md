# beta6 复核 第 01 轮：GL 4.3 门与 VK 回退链

> 角色：独立复核子代理（只读审计，不参与实现）
> 范围：`git diff 7c734e8..HEAD` 内的 GL 门 / VK 门 / 回退链相关文件
> 判定口径：白盒契约 / 黑盒实现 / 灰盒验证 / 人类掌舵；粗筛 → 双向推演（先证伪后证真）→ 四象限 → 探针闭环；8 段式逻辑链（SCAN_PROTOCOL §1 模板）
> **在途未定稿**：`tools/build_engine.py`、`Loom/build_entry.py`、`Loom/build_game.py`、`tools/package_engine*.py`、`使用操作指南.txt`（另有 `docs/audit/scan_beta3_05_*`）—— 属并行任务，本文**只标注「疑似在途」**，不据此下任何结论。
> 本轮**未改动任何受跟踪文件**；探针只写 `Loom/tests/_tmp/audit_b6_01_*.py`（gitignore 内）。跑完 `git status --porcelain` 自查：受跟踪改动 = 开工前就在的 6 项（在途）+ 并行子代理在 23:22:20 改动的 `Loom/tests/test_ab_gl_vk.py`，两者均与本文结论无关（详见证末尾「并发写入留痕」）。

---

## ① 范围与方法

| 项 | 内容 |
|---|---|
| 受审文件 | `Loom/loom_gl_version.py` 80 行（新增）；`Loom/loom_backend_guard.py` 146 行（新增）；`Loom/run_player.py` 361 行（+82/-…）；`Loom/vk_player.py`（+25）；`Loom/game_player.py`（+18）；`Loom/loom_glfw_window.py`（+25）；`Loom/loom_player_window.py`（+7）；`Loom/ui/loom_gui.py`（+48）；`Loom/engine.py`（+4，过门处 285-293）；另读 `game_settings.py`/`guiloader.py`（原子写与 delta 口径） |
| 契约来源 | 版本计划 §6 D1=B（GL 地板 4.3）、§9.2（VK 地板 1.1 + 打印 device/driver/apiVersion、不静默黑窗）、§9.3（裁决 A：可见失败 + 写用户层 render_api=opengl + 同进程回 GL + GL 也失败报两条原因并退出 + VkRunError 不回退）、§9.5（发布档不带控制台）；`loom_gl_version` 模块头 10-15 行；`loom_backend_guard` 模块头 4-19 行；`run_player` 模块头 15-20 行；`test_backend_fallback_policy.py` 文件头 1-16 行 |
| 实测命令 | 全部逐条列在 ③ 的「7) 验证」段；探针：`audit_b6_01_{env,vkdiag,glgate,glfw43,fallback,glonly,canvasleak,runtime_cfg}.py` |
| 真机口径 | 本机 GL：`NVIDIA GTX 1050 Ti / 582.78`，`create_standalone_context(require=460)` 可得 4.6；VK：`vulkan_api_version()=(1,4,309)`，真实 adapter = `NVIDIA GeForce GTX 1050 Ti`（**不是** UNVERIFIED） |
| 已跑既有测试 | `test_backend_fallback_policy.py` → **ALL PASS**；`test_render_api.py` → **ALL PASS**（含新增双错项）；`test_ab_gl_vk.py`（ab_cube/ab_pbr 两场景）→ **PASS，MAE=0** |

**本轮不做的**：不评审渲染是否应逐像素等价（round 02 已覆盖 `test_ab_gl_vk.py`）；不评审 `build_entry/build_game/package_engine`（在途）；不改任何代码。

> **并发写入留痕（不是本代理所为）**：审计过程中 23:22:20 有**另一个子代理**改动受跟踪文件 `Loom/tests/test_ab_gl_vk.py`（`git diff --stat` = +349/−107），并新出现 `docs/audit/scan_beta6_round_02/03_*.md`。本代理只写 `Loom/tests/_tmp/audit_b6_01_*.py`（gitignore 内）与本报告；按硬约束**不使用 `git checkout` 还原**（那会抹掉并行任务的成果），仅登记。P-15 的 `test_ab_gl_vk` 实测（23:19）取自改动前的 HEAD 版本，全量 A/B 结论以 round 02 为准。

---

## ② 粗筛清单（含跳过留痕）

| ID | 位置 | 标签 | 初步方向 |
|---|---|---|---|
| P-01 | `run_player.py:322` + `game_player.py:221-228` | SEM-SILENT / AUDIT-DOCIMPL | 只走 GL 且 GL 地板不满足时，`run_player.run_backend('opengl')` 无任何处理 → 发布版用户零反馈 |
| P-02 | `loom_backend_guard.py:78-93` | IFACE-VERSION / AUDIT-DOCIMPL | `vk_diag_text` 读 `driver/driver_info/backend/device_type`，本机 wgpu 0.33 的 info 只有 `description/adapter_type/backend_type` |
| P-03 | `vk_player.py:333-354` | IFACE-PARTIAL / BND-RESOURCE | 建窗之后初始化失败，canvas 从未 close，同进程继续开 GL 窗 |
| P-04 | `run_player.py:240-245` | SEM-MISMATCH | 只写引擎层成功时，日志仍说「写用户层 游戏设置.json」 |
| P-05 | `loom_backend_guard.py:138-143` | SEM-SILENT | `MessageBoxW` 返回值被丢弃，返回 0（无桌面/会话 0）也报「已弹窗」 |
| P-06 | `run_player.py:264-266` | AUDIT-ASYMMETRY | 双错时连续两次阻塞弹窗；消息前缀「[VK] [VK]」重复 |
| P-07 | `loom_backend_guard.py:25-26` | IFACE-VERSION | VK 地板常量 1.1 取自 wgpu 0.32；环境实装 wgpu **0.33.0**，地板是否变化未记录（§9.2#3 要求记录） |
| P-08 | `loom_backend_guard.py:137-143` | BND-ENV | 服务会话/无桌面下 MessageBoxW 是阻塞还是立即返回，未实测 |
| P-09 | `run_player.py:246-248, 194-195` | DESIGN-DRIFT | 显式 `--backend vulkan`（旧 Q6 明文「不改写设置」）现在会改写配置，且同时写**引擎层 设置.json**（编辑器默认后端也跟着变） |
| P-10 | `run_player.py:303-304, 316-321` | — | 运行期 VkRunError 是否真的不回退 / 不改配置（找反例） |
| P-11 | `loom_gl_version.py:35-57` | — | 门读的是「请求版本」还是「硬件上限」；会不会误判 4.6 机器 |
| P-12 | `engine.py:288-297` | — | 外部注入 ctx 不设门，会不会被真实用户路径误用 |
| P-13 | `game_settings.py:155-173` / `guiloader.py:189-224` | — | 写配置的原子性、是否只写 delta、写失败行为 |
| P-14 | `run_player.py:254-269` | — | 双错是否真退出且给出两条原因，还是可能黑屏 |
| P-15 | D1=B 的可行性前提 | — | 现有 `#version 330` 源码在 4.3 core 下是否照常编译 |

**跳过登记表（跳过必须留痕，四类理由之一）**

| SKIP | 位置 | 理由 |
|---|---|---|
| SKIP-01 | `loom_gl_version.py:17-18` 的「着色器版本策略」 | 白盒契约明确声明（理由②）：现有着色器不动是裁决的一部分；本轮只做可行性抽查（P-15），不做逐 shader 审查 |
| SKIP-02 | `ui/loom_gui.py:149-168` 的 `QTimer.singleShot+QMessageBox` 弹窗实现细节 | 语言/框架规范保证（理由①/④）：Qt 事件循环内 singleShot 会在 exec 后投递；且 `_pop` 全包 try |
| SKIP-03 | `loom_backend_guard.py:127-136` 非 Windows 分支 | 白盒契约（理由②）：引擎声明仅 Windows（版本计划 §1「仅 Windows」），`os.name != 'nt'` 分支不可达 |
| SKIP-04 | `game_player.py:111-137` `_run_from_pack/_run_from_scene` | 已有证据（理由③）：全仓 grep 无调用点（死代码），不影响本轮链路 |
| SKIP-05 | `tests/test_ab_gl_vk.py` 的闸门强度/阈值 | 已由 `scan_beta6_round_02_ab_gl_vk_受跟踪测试质量.md` 覆盖（含 VK SKIP→0 的 P-03），本轮不重复裁决 |
| SKIP-06 | `vk_player.py:719-721` watchdog `os._exit(9)` | 白盒契约（理由②）：2026-11-07 已登记的既有防线，非本轮 diff；且它「不回退不改配置」，与 ⑥ 的口径同向 |

---

## ③ 逐项裁决（8 段式）

### P-01 · PROVED · **P1** · GL 4.3 门在「玩家路径」不可见 —— 第二次启动=双击没反应

1. **位置**：`Loom/run_player.py:311-322`（`api == 'opengl'` 分支直接 `return _run_opengl(...)`，无 try）；`Loom/game_player.py:220-228`；`Loom/game_player.py:73-84`（stdout/stderr tee 到日志文件）；对照 `Loom/ui/loom_gui.py:149-168,208-209`（**只有编辑器**有地板弹窗）。
2. **契约/预期**：`loom_gl_version.py:10`「失败必须可见 —— 绝不静默黑屏、不吞异常」；§9.3#1「可见失败」、#3「若 GL 也失败，报出两条原因并退出」；§9.5 发布档 `--windows-console-mode=disable`。
3. **路径枚举**（`run_backend` 的全部入口 × 后端取值）：
   - a) `api='auto'` → VK 失败 → `_handle_vk_init_failure` + `_run_gl_or_double_fault` → GL 失败 = **弹窗 + SystemExit(1)**（可见）；
   - b) `api='vulkan'`（默认值）→ 同上 → 可见；
   - c) `api='opengl'` → 直线 `return _run_opengl(...)`（:322）→ GL 抛 `GLVersionError` → **无 handler、无弹窗、无 SystemExit**；
   - d) 下一次启动：配置已被写成 `opengl`（裁决 A 持久化）→ 走 c) → 同样静默；
   - e) `game_player._run_backend_safe('opengl')` → 进 :225 的 `except Exception` → 打印「已自动回退 OpenGL」（本来就是 GL）→ :228 重跑 `run_backend('opengl')` → 再次抛出 → **第二次调用不在 try 内 → 原样冒泡**。
   路径 c/d/e 全都没有任何 `show_blocking_dialog` 调用点（全仓 grep：`show_blocking_dialog` 仅 `run_player.py:235,268` 两处，都在 VK 段）。
4. **实际行为**：探针 A/B 实测（见 7）。`run_backend('opengl')` → `exc=GLVersionError, SystemExit=False, 弹窗=[], PlayerApp 尝试=1`；`game_player._run_backend_safe('opengl')` → `exc=GLVersionError, 弹窗=[], 尝试=2`，日志尾行是「已自动回退 OpenGL；若仍失败请把上面这行发给开发者」。
5. **差异**：预期「换不了后端也要让用户当场看见」（§9.3#1）；实际在发布档（无控制台 + 日志 tee）**屏幕上什么都没有**，只有 `%LOCALAPPDATA%\Loom\logs\game\日志.txt` 里一条 traceback。且「两条原因」条款只在 VK 曾被尝试的首次启动成立。
6. **触发条件**：机器 GL 上限 < 4.3（如 Intel HD 4000/4.0、虚拟机/远程桌面 3.3），且配置 `render_api=opengl`（首次双错回退后即自动变成这个状态）→ 第二次双击游戏 = 静默退出。
7. **验证**：
```
py -3.13 Loom\tests\_tmp\audit_b6_01_glonly.py
```
实测输出：
```
--- A) run_player.run_backend("opengl") ---
A exc= GLVersionError | SystemExit? False | 弹窗= [] | PlayerApp 尝试次数= 1
--- B) game_player._run_backend_safe("opengl") ---
B exc= GLVersionError | SystemExit? False | 弹窗= [] | PlayerApp 尝试次数= 2
B 输出尾 4 行: ["[game_player] 渲染后端启动失败: opengl (GLVersionError(...))",
              "[game_player] 已自动回退 OpenGL；若仍失败请把上面这行发给开发者"]
--- C) game_player._run_backend_safe("vulkan") 且 VK 失败后 GL 也失败 ---
C exc= SystemExit | code= 1 | 弹窗= ['[VK] Vulkan 驱动不兼容（需要 1.1+）',
                                     '无法启动渲染（Vulkan 与 OpenGL 均不可用）']
```
（C 说明「首次启动」这条链是好的，问题只在 GL-only / 二次启动。）
8. **影响与等级**：**P1**。这是本轮 4.3 地板带来的新可达失败面（旧版 3.3 机器能跑，不会走到这里），且直接违背本轮自己写的「可见失败」硬约束。修复方向（只给方向）：给 `api=='opengl'` 与 `_run_gl_or_double_fault` 同一出口 —— GL 段失败也走「打印 + 弹窗 + SystemExit(1)」；`_run_backend_safe` 在 backend 已是 opengl 时不要再打「已自动回退」并重试。

---

### P-02 · PROVED · **P2** · `vk_diag_text` 在实装 wgpu 0.33 上丢 driver/device_type，§9.2 要求的诊断缺一半

1. **位置**：`Loom/loom_backend_guard.py:78-93`（`vk_diag_text` 读 `info['driver'] / info['driver_info'] / info['backend'] / info['device_type']`）。
2. **契约/预期**：§9.2#2 要求「打印 `[VK] device / driver / apiVersion`」；模块头 :11「一段人可读诊断：device / driver / driver_info / backend / device_type」。
3. **路径枚举**：`vk_diag_text` 只有一条路径（`info.get(...)` 全走 `or '未知'`），**关键在入参 schema**：
   - a) 旧口径 `AdapterInfo`（代码假定的键：`device/driver/driver_info/backend/device_type`；**据代码推定，未在本机实装 0.32 验证**）→ 全命中；
   - b) 实装 **wgpu 0.33.0**：`GPUAdapterInfo(dict)` 键 = `vendor/architecture/device/description/stackgroup_*/vendor_id/device_id/adapter_type/backend_type` → `driver`/`driver_info`/`device_type` **不存在**，`backend` 也不存在（靠 `or 'vulkan'` 兜成字面量）。
4. **实际行为**：真实 adapter 下实测（7）。
5. **差异**：预期「驱动: NVIDIA 582.78 / 类型: DiscreteGPU」；实际「驱动: 未知 (版本未知)」+「后端/类型: vulkan / 未知」。而 `description='582.78'`、`adapter_type='DiscreteGPU'`、`backend_type='Vulkan'` 其实都在 info 里，只是键名不同。
6. **触发条件**：任何 wgpu 0.33 环境（`requirements.txt:8` 是 `wgpu>=0.32` **无上界**，全新机器 pip 装即 0.33）。本机就是 0.33.0。
7. **验证**：
```
py -3.13 Loom\tests\_tmp\audit_b6_01_vkdiag.py
```
实测输出（节选）：
```
info keys: ['adapter_type','architecture','backend_type','description','device','device_id',
            'stackgroup_max_size','stackgroup_min_size','vendor','vendor_id']
info: {'device': 'NVIDIA GeForce GTX 1050 Ti', 'description': '582.78',
       'adapter_type': 'DiscreteGPU', 'backend_type': 'Vulkan', ...}
---- vk_diag_text(真实 info) ----
[VK] 设备: NVIDIA GeForce GTX 1050 Ti
[VK] 驱动: 未知 (版本未知)
[VK] 后端/类型: vulkan / 未知
[VK] Vulkan API: 1.4.309（地板: 1.1）
```
（对照 `test_backend_fallback_policy.py` 的 F1 断言 `all(k in str(err) for k in ("设备","驱动","Vulkan API"))` —— 它只查**标签存在**，不查值非空，所以测试全绿而诊断是空的。）
8. **影响与等级**：**P2**。回退本身仍正确（仍会报 apiVersion + 设备 + 原因），但「让用户知道该升级驱动」的关键字段是空的；且它同时暴露 `wgpu>=0.32` 无上界导致的 schema 漂移。修复方向：按 WebGPU 规范键读取并兼容旧键（`driver = description`、`device_type = adapter_type`、`backend = backend_type`），并把 F1 断言从「标签存在」升级为「值 != 未知」。

---

### P-03 · PROVED · **P2** · 同进程回退遗留一个可见的空白 VK 窗口

1. **位置**：`Loom/vk_player.py:333-354`（`canvas = GlfwRenderCanvas(...)` 之后任何失败都直接 `raise`，**没有 `canvas.close()`**）；`Loom/run_player.py:254-260`（随即同进程 `_run_opengl`）。
2. **契约/预期**：`vk_player.py:644-646`「不再 os._exit … 关窗结束循环」体现「切后端前先收干净」；§9.3#3 要求同进程「立即按 GL 路径继续」——用户只应看到一个窗口。
3. **路径枚举**（初始化段 3 个 raise 点）：
   - a) `require_vulkan_api` 失败 —— 在建窗**之前**，无残留；
   - b) `adapter is None`（本轮新增，:341-342）—— 建窗**之后**，残留；
   - c) `request_device_sync/get_wgpu_context/get_preferred_format/`交换链渲染器初始化失败（:344-381）—— 建窗**之后**，残留。
   b/c 的 traceback 通过 `raise ... from _ie` 挂在异常链上，帧对象持有 `canvas` 局部变量 → 窗口在 GL 会话期间**一直存活**。
4. **实际行为**：探针实测（7）：1 个窗口被创建，异常捕获点时 `should_close=0 visible=1 title='Loom (Vulkan)'`。
5. **差异**：预期「VK 走不通就只留 GL 一个窗口」；实际桌面/任务栏多一个标题为 `Loom (Vulkan)` 的空白窗口，直到进程退出。旧代码在 `vulkan` 分支上会立刻 SystemExit（进程级清理），所以这条残留是本轮「同进程继续」新引入的（`auto` 分支的同类残留是旧行为，见 `git show 7c734e8:Loom/run_player.py` 的 :269）。
6. **触发条件**：VK 运行时在、但 adapter/device/交换链建不起来（无独显/远程桌面/驱动残缺/显存不足）→ 建窗后才失败。
7. **验证**：
```
py -3.13 Loom\tests\_tmp\audit_b6_01_canvasleak.py
```
实测输出：
```
exc: VkInitError | segment: vulkan-init
创建的 GLFW 窗口数: 1
  窗口0 should_close=0 visible=1 title='Loom (Vulkan)'
异常未释放时窗口仍存活 = True
```
8. **影响与等级**：**P2**（视觉残留/资源未收回，不崩：实测 `glfw.terminate()` 后 canvas 析构只产生一条 `GLFW library is not initialized` 警告，见 `audit_b6_01_runtime_cfg.py` 的 b 段）。修复方向：初始化段整体包 `try/finally`，失败时 `canvas.close()`（与 :632-636 的降级路径同一写法）。

---

### P-04 · PROVED · **P3** · 「已把 render_api 回退为 opengl（写用户层 游戏设置.json）」在只写成功引擎层时是假话

1. **位置**：`Loom/run_player.py:239-245`（`ok = _persist_backend('opengl')` → `if ok: print("...写用户层 游戏设置.json...")`）。
2. **契约/预期**：`run_player.py:184-192` 的 docstring 与 §9.3#2 都明确「写**用户层** 游戏设置.json」；契约 §7 禁止假成功。
3. **路径枚举**：`_persist_backend` 有 4 条路径：两层都成功 / 仅游戏层成功 / 仅引擎层成功 / 都失败。`ok` 取自「解析链复核通过」（:202-212），因此**第 3 条路径 `ok=True`**，而提示文案写死「写用户层 游戏设置.json」。
4. **实际行为**：探针把 `_write_game_layer` 替换成失败、引擎层保留成功 → 输出同时出现「写 游戏设置.json 失败: 模拟…」和「已把 render_api 回退为 opengl（写用户层 游戏设置.json）」。
5. **差异**：同一屏两条互相矛盾的结论；用户以为游戏配置已改，实际改的是编辑器配置。
6. **触发条件**：`%LOCALAPPDATA%\Loom\games\...\游戏设置.json` 不可写（只读安装/权限/被占用），但引擎 设置.json 可写。
7. **验证**：
```
py -3.13 Loom\tests\_tmp\audit_b6_01_fallback.py
```
实测（T4）：
```
> [run_player] 写 游戏设置.json 失败: 模拟: 游戏层不可写
> [run_player] 已把 render_api 回退为 opengl（写用户层 游戏设置.json），下次启动直接走 OpenGL
```
8. **影响与等级**：**P3**（可审计性/诚实性；最终行为仍然正确，因为引擎层也让解析链得到 opengl）。修复方向：文案按 `ok_game/ok_engine` 分别输出，或在 `_persist_backend` 返回「哪层真的写了」。

---

### P-05 · PROVED · **P3** · `show_blocking_dialog` 丢弃 `MessageBoxW` 返回值 → 无桌面时谎报「已弹窗」

1. **位置**：`Loom/loom_backend_guard.py:138-143`（`fn(None, text, title, ...)` 返回值被忽略，函数固定 `return True`）。
2. **契约/预期**：`run_player.py:249-250` 用返回值决定是否提示「(未弹窗: 无 GUI 或 LOOM_NO_DIALOG=1)」；模块头 :12-13 声明「非 Windows / 无 user32 / LOOM_NO_DIALOG=1 时只打印不弹」——即「弹没弹」这一事实必须诚实。
3. **路径枚举**：a) `LOOM_NO_DIALOG` 置位 → False（正确）；b) 非 nt → False（正确）；c) 抛异常 → False（正确）；d) **`MessageBoxW` 返回 0（会话 0 / 无交互桌面 / 桌面被禁用）→ 仍 True（错误）**。
4. **实际行为**：探针 stub 返回 0 → 函数返回 True，且调用次数=1。
5. **差异**：预期「没弹出来要如实说」；实际提示被跳过，且 `run_player` 里「未弹窗」的解释行不打印。
6. **触发条件**：Windows 服务会话 / 计划任务（无交互桌面）/ Kiosk 受限桌面下启动发布版。
7. **验证**：
```
py -3.13 Loom\tests\_tmp\audit_b6_01_fallback.py     # T1
```
实测：
```
T1a LOOM_NO_DIALOG=1 -> False
T1b MessageBoxW 返回 0 -> True | 调用次数 {'n': 1}
T1c MessageBoxW 抛错 -> False（并打印「弹窗失败 … 不阻断回退」）
```
8. **影响与等级**：**P3**。修复方向：`return fn(...) != 0`（0 = 失败/被拒）。

---

### P-06 · PROVED · **P3** · 双错时连弹两次阻塞框 + 消息前缀重复

1. **位置**：`Loom/run_player.py:235-240`（VK 诊断弹窗）与 `run_player.py:264-268`（双错弹窗）；`run_player.py:264-266` 的 `"[VK] %s"` 拼在已经以 `[VK]` 开头的异常文本前。
2. **契约/预期**：§9.3#1/#3 要求「让用户当场看见原因」；无「弹两次」的要求，也无「前缀重复」的允许。
3. **路径枚举**：a) VK 失败 + GL 成功 → 1 次弹窗（合理）；b) VK 失败 + GL 失败 → 2 次弹窗（第二个要等第一个点掉）；c) 消息文本 2 条来源（`require_vulkan_api` 的 msg / `VkInitError` 包装后的 msg）都自带 `[VK]` 前缀 → 双层前缀。
4. **实际行为**：探针 C 捕获到 `弹窗=['[VK] Vulkan 驱动不兼容（需要 1.1+）','无法启动渲染（Vulkan 与 OpenGL 均不可用）']`，文本里出现 `[VK] [VK] 模拟: 无适配器`。
5. **差异**：预期一次到位的「两条原因」框；实际两次模态 + 重复前缀。
6. **触发条件**：两条后端都不可用（无 VK 运行库 + GL < 4.3）。
7. **验证**：
```
py -3.13 Loom\tests\_tmp\audit_b6_01_glonly.py        # C 段
py -3.13 Loom\tests\test_backend_fallback_policy.py    # C1 段同现象
```
实测（节选）：`C 输出尾 5 行: [... '[VK] [VK] 模拟: 无适配器', '[GL] [GL] 模拟: 当前上下文 3.3 < 4.3 (GLFW 窗口)']`
8. **影响与等级**：**P3**（体验/可审计）。修复方向：双错时只弹一个合并框；拼装前剥掉已存在的 `[VK]` 前缀。

---

### P-07 · UNKNOWN（U-01）· wgpu 0.33 的 Vulkan 地板是否仍是 1.1

1. **位置**：`loom_backend_guard.py:25-26`（`VK_MIN_API_MAJOR/MINOR = 1/1`）。
2. **契约/预期**：§9.2#3「每次升 wgpu-py/wgpu-native，必须记录 Vulkan 地板是否变化，写进该批次验收表」；地板常量应随 wgpu-native 抬升。
3. **路径枚举**：a) 0.33 地板仍 1.1 → 现状正确；b) 地板 > 1.1 → 1.1/1.2 设备会「过门 → request_adapter 失败 → 仍走 VkInitError → 仍回退 GL」，但诊断文案会变成「初始化失败」而不是「驱动不兼容」，且 §9.2 的验收记录缺失。
4. **实际行为**：本机 `vulkan_api_version()=(1,4,309)`，无法构造 1.1/1.2 设备；`requirements.txt:8` 为 `wgpu>=0.32`，实装 0.33.0；仓内 grep 无「Vulkan 地板变化」记录。
5. **差异**：无法判定（缺低版本 Vulkan 设备与官方记录）。
6. **触发条件**：在 Vulkan 1.1/1.2 的旧驱动机器上启动 VK 后端。
7. **验证**：`py -3.13 Loom\tests\_tmp\audit_b6_01_vkdiag.py`（得 1.4.309 + 0.33.0）；要定案还需：wgpu-native 0.33 的 Vulkan 地板官方说明，或一台 1.1/1.2 设备。
8. **影响与等级**：**P-UNKNOWN**。需要什么信息才能定：wgpu-native 0.33 的地板声明 / 旧驱动实测。建议下一步探针：在 1.1 设备上跑 `require_vulkan_api()` + `request_adapter_sync` 并记录失败点。

---

### P-08 · UNKNOWN（U-02）· 无桌面/服务会话下 `MessageBoxW` 是「立即返回 0」还是「阻塞」

1. **位置**：`loom_backend_guard.py:137-143`。
2. **契约/预期**：模块头 :12-13「阻塞式原生错误弹窗」+ §9.3#1「原因必须让用户当场看见」；隐含「不该在无人值守时挂死」。
3. **路径枚举**：a) 交互桌面 → 阻塞到点击（预期）；b) 会话 0/无交互窗口站 → 可能立即返回 0（T1b 已覆盖**返回 0 时的处理**），也可能弹到不可见桌面并**永久阻塞**（无法在普通会话复现）。
4. **实际行为**：只能验证返回值语义，无法验证「阻塞」这一支。
5. **差异**：无法判定。若为「永久阻塞」，发布版在 CI/无人值守启动时会挂死（比静默退出更糟）。
6. **触发条件**：服务/计划任务/Kiosk 下启动发布版且 VK 初始化失败。
7. **验证**：`py -3.13 Loom\tests\_tmp\audit_b6_01_fallback.py`（T1 三态）；要定案需：在 session 0（`psexec -s` / 计划任务）跑 `LOOM_NO_DIALOG` 未置位的 VK 失败路径，观察是否返回。
8. **影响与等级**：**P-UNKNOWN**。需要什么信息：session 0 实测。

---

### P-09 · HUMAN-ARBITRATION · 显式 `--backend vulkan` / `--backend auto` 改写用户配置，并同时改「引擎层 设置.json」（编辑器默认后端）

1. **位置**：`run_player.py:215-251`（不再区分 explicit 的持久化）+ `run_player.py:194-195`（`_persist_backend` 同时写游戏层与引擎层）+ 测试 `test_backend_fallback_policy.py:157-171,174-185`（已把新口径固化为断言）。
2. **契约/预期**：`run_player.py:297` 的 docstring **仍写着**「explicit=True … (Q6: 显式 vulkan 失败不改写设置)」；旧测试曾断言「显式 vulkan: 设置未被改写 / auto: 设置未被改写」；§9.3#2 只写了「把**用户层 游戏设置.json** 的 render_api 写成 opengl」。
3. **路径枚举**：a) 默认/设置走 vulkan（非手选）→ 写（与裁决一致）；b) `--backend vulkan` 显式 → 现在也写（旧 Q6 明文不写）；c) `--backend auto` 显式 → 也写（旧 Q6 明文不写）；d) b/c 同时会通过 `_write_engine_layer` 改**编辑器**默认（§9.3 未提）。
4. **实际行为**：探针 T6 实测 `--backend vulkan` 失败后引擎层 `设置.json` 的 `render_api` 变成 `opengl`，并打印「本次 vulkan 是用户手选」。
5. **差异**：实现把「裁决 A」的口径扩到了「显式手选」与「引擎层」两处，均超出裁决原文。
6. **触发条件**：开发者在无 VK 机器上跑 `run_player.py <scene> --backend vulkan` 做一次性对比。
7. **验证**：`py -3.13 Loom\tests\_tmp\audit_b6_01_fallback.py`（T4/T6）；`test_backend_fallback_policy.py` 的 B1/E1 已把当前口径锁死。
8. **影响与等级**：**HUMAN-ARBITRATION**（见 ⑥ Q1/Q2）。不自动改：这是「显式覆盖是否应持久化」的工程路线选择。

---

### P-10 · DISPROVED · 运行期 `VkRunError` 确实不回退、不改配置

1. **位置**：`run_player.py:302-304`（auto）、`run_player.py:316-321`（vulkan）；`vk_player.py:747-751`（循环内异常 → `VkRunError`）。
2. **契约/预期**：§9.3 末句「运行期失败（VkRunError）不回退、不改配置」；`game_player.py:193-195` 同口径。
3. **路径枚举**（3 个入口 × 该异常）：
   - a) `api='auto'` → :303 `raise`；
   - b) `api='vulkan'` + explicit → :318 `isinstance(VkInitError)` 为假、`_is_vk_error(e,'vulkan-init')` 为假 → :321 `raise`；
   - c) `api='vulkan'`（设置/默认）→ 同 b；
   - d) 发布链：`game_player.py:223` catch `(SystemExit, run_player.VkRunError)` → `raise`。
   四个入口都直接上抛，无 `_persist_backend` 调用点。
4. **每条路径证据**：探针实测 3 个入口 `calls=['vk']`、异常类型 `VkRunError`，且 `设置.json`/`游戏设置.json` **字节未变**（`render_api` 仍 `vulkan`）。
5. **实际行为**：符合契约。
6. **触发条件**：渲染循环内 device lost / wgpu PanicError。
7. **验证**：
```
py -3.13 Loom\tests\_tmp\audit_b6_01_runtime_cfg.py     # a 段
py -3.13 Loom\tests\test_backend_fallback_policy.py      # t_loop_failure_not_swallowed
```
实测：`a) 两份配置字节未变 = True` / `calls=['vk']` / 测试 `PASS auto: VkRunError 原样上传 (不回退 GL)`。
8. **判定**：**DISPROVED**（未找到反例）。残余风险（不构成 PROVED）：`vk_player.py:382-405,684` 在「初始化段之后、渲染循环之前」的少数语句不在任何 try 内，其异常不带 `segment`，会被 `game_player` 的「最后一道网」当作意外异常回退 GL —— 但本机未构造出具体触发条件，故记残余、不裁决。
9. **跳过留痕**：`vk_player.py:719-721` 的 `os._exit(9)` 是既有的卡死防线，不写配置也不回退，与 ⑥ 同向，SKIP-06。

---

### P-11 · DISPROVED · 门的判定依据 = **上下文实际授予版本**，不是硬件上限；但产品侧 4 处全部请求 4.3，所以不会误判「4.6 机器」

1. **位置**：`loom_gl_version.py:35-57`（`version_code` / `gl_info`）、`60-80`（门）。
2. **契约/预期**：§6 D1=B「GL 地板 4.3」；`loom_gl_version.py:4-5`「地板 = 4.3 core」。
3. **路径枚举**（ctx 来源 × 请求版本）：
   - a) `loom_glfw_window.py:133-135` → 请求 `GL_MIN_MAJOR/MINOR`(4,3) → 授予 ≥4.3 → 门过（本机 430）；
   - b) `loom_player_window.py:79` → 4.3 → 门过；
   - c) `ui/loom_gui.py:4208` `setDefaultFormat(4.3 core)` → 两个视口（:195/:554）门过；
   - d) 测试/探测 `create_standalone_context(require=330)`（`test_skybox_engine_parity.py:42,145`）→ `version_code=330` → **若走门会失败**，但这些路径按设计不走门（P-12）。
4. **每条路径证据**：`version_code` 实测随 `require=` 变（330→330 / 430→430 / 460→460），证明它是「授予的上下文版本」；产品 4 处请求值 = 地板值（grep 证据），故不存在「驱动 4.6 而代码只要 3.3」被误判的产品路径。
5. **实际行为**：符合设计。
6. **触发条件**：只有「未来有人新增一条请求 <4.3 的产品 ctx 且复用门」才会误判 —— 属回归风险，不是现状缺陷。
7. **验证**：
```
py -3.13 Loom\tests\_tmp\audit_b6_01_glgate.py
py -3.13 Loom\tests\_tmp\audit_b6_01_glfw43.py
```
实测：
```
require=330 -> info[GL_VERSION]='3.3.0 NVIDIA 582.78' version_code=330  supports_gl(430)=False  → gate RAISE
require=430 -> version_code=430 → gate PASS
require=460 -> version_code=460 → gate PASS
create_window(4.3 core) -> True | ctx.info GL_VERSION = '4.3.0 NVIDIA 582.78' | require_gl_version -> 430
```
8. **判定**：**DISPROVED**（误判结论不成立）。备注：门对「0 / 缺字段」一律判失败（`gl_info` :39-41），方向正确（宁可失败可见）。

---

### P-12 · DISPROVED · 「外部注入 ctx 不设门」没有被真实用户路径误用

1. **位置**：`engine.py:279-297`（`self._external_ctx = ctx is not None` → 只有 `ctx is None` 分支才过门）。
2. **契约/预期**：`loom_gl_version.py:12-15`「产品路径必须走此门；测试/探测的外部注入 ctx 不走此门，注入方自担版本」。
3. **路径枚举**（全仓 `create_context/create_standalone_context` 产品侧 4 处 + 注入点）：
   - a) `engine.py:290` GLFW 自建 → 门（:293）；
   - b) `loom_player_window.py:92` Qt 离屏 → 门（:94），随后 `PlayerApp(ctx=self.ctx)`（:113-114）注入的是**已过门**的 ctx；
   - c) `ui/loom_gui.py:193` 编辑器视口 → 门（:195）；
   - d) `ui/loom_gui.py:553` 离屏回读视口 → 门（:554）；
   - e) 测试注入（`test_skybox_engine_parity`、`test_ab_gl_vk:133`、`test_texture` 等）→ 不过门（设计如此）。
4. **每条路径证据**：产品侧「创建 ctx 的地方」= 「过门的地方」一一对应（b/c/d 都是先门后注入）；不存在「产品先建 ctx 再交给引擎」的第三种形态。
5. **实际行为**：符合设计。
6. **触发条件**：仅当第三方插件自己建 3.3 ctx 再 `EditorApp(ctx=...)`；仓内无此调用点。
7. **验证**：`grep -n "create_context\|create_standalone_context" Loom/**/*.py`（产品侧仅上述 4 处）；`py -3.13 Loom\tests\test_ab_gl_vk.py`（注入 4.3 ctx 走通，证明注入链本身健康）。
8. **判定**：**DISPROVED**。备注：风险面从「产品误用」降级为「插件误用」，建议在 `EditorApp/PlayerApp` 的 ctx 分支加一次性 `supports_gl` 断言（只警告不 raise）——属建议，不是缺陷。

---

### P-13 · DISPROVED · 回退写配置：原子、只写 delta、保留其它键

1. **位置**：`game_settings.py:155-173`（`tmp + os.replace`）、`273-281`（`set_value` 读改写保留老键）、`guiloader.py:189-224`（只写 delta）。
2. **契约/预期**：契约 §4/§7（用户层只存 delta、写失败必须出声、原子写）。
3. **路径枚举**：a) 正常 → 原子替换；b) 写入抛错 → `write_render_api` 返回 `(False, …, err)` → `_persist_backend` 打「写 … 失败」并继续 GL（不假成功）；c) 用户文件损坏 → `_read_layer` 备份后返回 `{}` → 新文件只带本次 delta（老键会丢，但原文件已备份）；d) 并发两进程写同一 `*.tmp` → 后写者 `os.replace` 抛错 → 返回 False（可接受，非静默）。
4. **实际行为**：T3 实测——`render_api` 变 `opengl`，`mouse_locked=True`、`key_bindings={'jump':['space']}` 全部保留；引擎层只写 delta。
5. **差异**：无（除 P-04 的文案问题）。
6. **触发条件**：正常回退 / 权限受限 / 配置损坏。
7. **验证**：
```
py -3.13 Loom\tests\_tmp\audit_b6_01_fallback.py     # T3
```
实测：
```
T3 游戏设置 values = {'render_api': 'opengl', 'mouse_locked': True, 'key_bindings': {'jump': ['space']}}
T3 其它键保留 = True | key_bindings 保留 = {'jump': ['space']}
```
8. **判定**：**DISPROVED**（无缺陷）。残余：`*.tmp` 是固定名，跨进程并发会互相打断（失败可见，不损坏数据）。

---

### P-14 · DISPROVED · 双错确实 `SystemExit(1)` 且两条原因都在（但在「只走 GL」时不成立，见 P-01）

1. **位置**：`run_player.py:254-269`。
2. **契约/预期**：§9.3#3。
3. **路径枚举**：a) `_run_opengl` 抛普通 `RuntimeError` → 捕获（`except BaseException`）→ 打印 + 弹窗 + `SystemExit(1)`；b) 抛 `GLVersionError`（`RuntimeError` 子类）→ 同 a；c) 抛 `SystemExit/KeyboardInterrupt` → 原样 `raise`（不吞）。
4. **实际行为**：C 段实测 `SystemExit code=1`、输出含 `[VK] …` 与 `[GL] …`、两次弹窗（见 P-06）。
5. **差异**：a/b/c 均符合；唯一缺口是「从来没试过 VK 的 `api='opengl'` 路径不进这个函数」（P-01）。
6. **触发条件**：VK 与 GL 都不可用。
7. **验证**：`py -3.13 Loom\tests\_tmp\audit_b6_01_glonly.py`（C 段）/ `test_render_api.py`（「脚本入口: GL 也不可用 -> 非零退出 + 两条原因」PASS）。
8. **判定**：**DISPROVED**（本路径无缺陷）。

---

### P-15 · DISPROVED · `#version 330` 源码在 4.3 core 下照常编译，且 A/B 基线未劣化

1. **位置**：`loom_gl_version.py:17-18`（着色器不动的前提）；`engine.py:306-333`（程序构建点）。
2. **契约/预期**：D1=B 的前提「4.3 core 驱动能编 330」。
3. **路径枚举**：a) 330 最小着色器在 4.3 core 直接编；b) 引擎全量 shader 在 4.3 core 下由 `test_ab_gl_vk` 的 `EditorApp(ctx=4.3)` 覆盖；c) GL vs VK 逐位（本轮只抽 2 场景，全量由 round 02 负责）。
4. **实际行为**：a 编译成功；b/c 两场景 `PASS MAE=0`。
5. **差异**：无。
6. **触发条件**：产品 GL 路径。
7. **验证**：
```
py -3.13 Loom\tests\_tmp\audit_b6_01_glfw43.py
$env:LOOM_AB_SCENES='ab_cube.json,ab_pbr.json'; py -3.13 Loom\tests\test_ab_gl_vk.py
```
实测：
```
330 着色器在 4.3 core 编译 = True
PASS ab_cube.json  MAE=0.000000 MAX=0.0000 NCC=0.999946 (基线 0.000000)
PASS ab_pbr.json   MAE=0.000000 MAX=0.0039 NCC=1.000003 (基线 0.000000)
--- 场景 2, 失败 0, 跳过 0 ---
```
8. **判定**：**DISPROVED**（无缺陷）。注：NCC=1.000003 的溢出属 round 02 的 P-07，不重复裁决。

---

## ④ 统计

| 判定 | 数量 | 编号 |
|---|---|---|
| **P-PROVED** | **6** | P-01(P1) / P-02(P2) / P-03(P2) / P-04(P3) / P-05(P3) / P-06(P3) |
| **P-DISPROVED** | **6** | P-10 / P-11 / P-12 / P-13 / P-14 / P-15 |
| **P-UNKNOWN** | **2** | P-07(U-01) / P-08(U-02) |
| **P-CONTRADICTION** | **0** | 本轮证伪链与证真链未同时成立；每条 PROVED 都有可复现反例，每条 DISPROVED 都枚举了全部入口/分支 |
| **HUMAN-ARBITRATION** | **1** | P-09（展开为 ⑥ 的 Q1/Q2） |
| 跳过项 | 6 | SKIP-01…SKIP-06 |

按严重度：**P1×1、P2×2、P3×3**；[REGRESSION] 标记：**P-01、P-02、P-03、P-04、P-05、P-06**（均为 `7c734e8..HEAD` 引入或本轮改动使其可达）。

P-CONTRADICTION=0 的说明：本轮 6 条证真链都给了「最小复现 + 实测输出」，对应的证伪被实测反例推翻（如 P-01 的 `弹窗=[]`、P-02 的 `info keys` 缺键），不存在「既证伪成功又证真成功」的项。

P-UNKNOWN 不为 0（2 项），均写明「需要什么信息才能定」。

---

## ⑤ 修复建议排序（只给方向，不含代码）

| 顺序 | 编号 | 等级 | 方向 |
|---|---|---|---|
| 1 | P-01 | **P1** | 把「GL 段失败」纳入与 VK 段同一出口：`_run_opengl` 的调用点统一 try→打印+弹窗+`SystemExit(1)`；`_run_backend_safe` 在 backend 已是 opengl 时不得再打「已自动回退」并重跑。**这是本轮唯一会直接导致发布版「双击没反应」的项。** |
| 2 | P-02 | P2 | `vk_diag_text` 按 WebGPU 规范键读（`driver=description`、`device_type=adapter_type`、`backend=backend_type`）并兼容旧键；把 F1 断言从「标签存在」升级为「值非未知」。顺带把 `requirements.txt` 的 `wgpu>=0.32` 收紧到实测版本。 |
| 3 | P-03 | P2 | VK 初始化段 `try/finally`：失败必 `canvas.close()`（与 :632-636 同一写法），再上抛 `VkInitError`。 |
| 4 | P-04/P-05/P-06 | P3 | 文案按「实际写了哪层」输出；`show_blocking_dialog` 用 `!= 0` 作返回值；双错只弹一个合并框并去重 `[VK]/[GL]` 前缀。 |
| 5 | P-07 | UNKNOWN | 在批次 A 验收表补一行「wgpu 0.33 的 Vulkan 地板 = ?」；拿不到结论就先在注释里写明「1.1 来自 0.32」。 |
| 6 | P-08 | UNKNOWN | 给弹窗加「无人值守」兜底（例如 `LOOM_NO_DIALOG` 之外再加超时/不可见桌面检测），或先接受并写进已知限制。 |

---

## ⑥ 需人类裁决的封闭问题

**Q1 · 显式 `--backend vulkan` 失败时，是否允许改写用户配置？**
- 背景：旧 Q6 明文「显式 vulkan 不改写设置」，本轮实现与测试（`test_backend_fallback_policy.py:157-171`）已改为「同样改写」，但 §9.3 只写了「把用户层 游戏设置.json 写成 opengl」，没有对「显式」开口。
- 可选方向：**A** 保持现状（显式也持久化，理由：下次不再空试）；**B** 恢复旧 Q6（显式只本次降级，不改配置）。
- 代价：A = 一次 `--backend vulkan` 的临时对比会永久改变用户配置；B = 每次显式启动都要重试一次 VK。

**Q2 · VK 回退时是否允许同时改写「引擎层 设置.json」（= 编辑器默认后端）？**
- 背景：`_persist_backend` 会写引擎层，§9.3#2 只授权「游戏设置.json（用户层）」。
- 可选方向：**A** 只写游戏层（严格按裁决）；**B** 两层都写（保证开发机「一致切回」，现状）。
- 代价：A = 开发机噪声少、语义单一；B = 线上/玩家机器会把编辑器默认后端一起改掉（玩家机器上编辑器可能根本不存在）。

**Q3（确认口径，不阻塞）· 「GL 也不可用」的可见性要求是否覆盖「只走 GL」的启动？**
- 背景：§9.3#3 只覆盖「VK 失败后 GL 也失败」；而 P-01 是「配置已是 opengl / 用户手选 opengl，GL 4.3 不满足」。发布档无控制台，当前**屏幕零反馈**。
- 可选方向：**A** 让 GL 段失败也弹窗 + `SystemExit(1)`（与 VK 段对称）；**B** 依赖 `%LOCALAPPDATA%\Loom\logs\game\日志.txt`（现状）。
- 代价：A = 多一个阻塞框，但「双击没反应」消失；B = 保持现状，玩家需自己找日志。
