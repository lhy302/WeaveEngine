# 修复报告 · 批次 R3（scan_05 P-09 / P-11 收尾：UI 输入语义 + 日志卫生）

日期: 2026-11-07
来源: `docs/audit/scan_05_player.md` P-09 / P-11；F5 报告 §遗留第 5 条
改动文件: `vk_ui.py`、`game_player.py`
新增测试: `tests/test_wheel_backend_semantics.py`（run_all 自动收集）
对照探针: `tests/_tmp/probe_wheel_backend_semantics.py`（已被 .gitignore 忽略）
未 git add / 未 commit；未改其它源文件。

> 并行写冲突说明：`vk_ui.py` 在 10:35:14 被其它进程整文件覆盖过一次，导致
> 本批的 `_wheel_taken_by_scrollview` / `last_wheel_consumed` 局部改动被回退。
> 已用**局部 patch** 重新应用；随后主 Agent 把 `vk_ui.py` 写权交给 R5
> （line-list 实验），本批不再整文件写 `vk_ui.py`。当前两处改动与 R5 的
> line-list 共存。

---

## 1. [P3] `vk_ui.last_wheel_consumed` 语义偏

**位置**（改后）: `vk_ui.py` 的 `_wheel_taken_by_scrollview`（模块级函数，
当前约 765 行）、`begin_frame` 内 dispatch 前取判据（当前约 847 行）、
`begin_frame` 末尾的新语义赋值（当前约 887 行）。

### 1.1 语义契约（精确定义）

- `last_consumed`：**本帧鼠标事件整体**是否被 UI 消费。它由
  `UIManager.dispatch_mouse` 的返回值决定，包含"滚轮命中 ScrollView"与
  "点击命中按钮/滑条"两条独立路径 —— **不能用它判断滚轮**。
- `_wheel_taken_by_scrollview(ui, pos)`：**滚轮专属**判据，回答"指针下的
  最近 ScrollView 是否存在且可滚动"（与 `dispatch_mouse` 的滚轮分支同源：
  `_hit_scroll_view(pos)` + `can_scroll()`；判不了时保守按已消费）。
- `last_wheel_consumed`：**本帧滚轮是否已被 UI 消费**。精确定义为：

      last_wheel_consumed =
          bool(wheel) and consumed and _wheel_taken_by_scrollview(ui, pos)

  即三个条件同时成立：本帧确有滚轮；UI 确实接收了本帧鼠标事件；
  接收的原因是滚轮命中了可滚动的 ScrollView。

**为什么是"取与"而不是"取或"**：

- 若取或，同帧"点按钮（consumed=True）+ 滚轮不在滚动区
  （wheel_taken=False）"会得到 True，正好复现 P-09 的缺陷（滚轮被误标
  已消费，脚本/相机拿不到）。
- 取与同时排除了两种误判：点击消费但滚轮未消费（A/D 场景）；滚轮命中
  ScrollView 但 UI 整体未接收（异常/未知 UI 的保守分支由 `consumed`
  兜住）。
- F5 在 `vk_player.py:403` 已写成
  `last_wheel_consumed and _wheel_taken_by_scrollview(...)`。本次把
  滚轮判据下沉进 `last_wheel_consumed` 后，这层取与对真实 `UIManager`
  是**幂等**的（两者同真同假），所以 `vk_player` 不需要改；本批允许
  清单也不含 `vk_player.py`。

**改前**（本批改动前的 `begin_frame`）:

    self.last_wheel_consumed = bool(wheel) and consumed

**改法**:

- 新增 `_wheel_taken_by_scrollview(ui, pos)`（模块级函数，当前约 765 行）。
- `begin_frame` 在 `dispatch_mouse` **之前**取 `wheel_taken`
  （当前约 847 行），避免 dispatch 改变 `scroll_pos` 后命中状态漂移。
- `last_wheel_consumed = bool(wheel) and consumed and wheel_taken`
  （`begin_frame` 末尾，当前约 887 行）。
- `last_consumed` 保持"整体事件"语义不变。

### 1.2 改前 / 改后实测

`tests/_tmp/probe_wheel_backend_semantics.py`，同一 UIManager 数据层；"旧公式"列
= `bool(wheel) and consumed`：

| 场景 | consumed | 改前 last_wheel_consumed | 改后 last_wheel_consumed |
|---|---|---|---|
| A 同帧点按钮 + 滚轮（指针不在滚动区） | True | **True（误）** | **False** |
| D 同帧点按钮 + 滚轮（不可滚 ScrollView 内按钮） | True | **True（误）** | **False** |
| C 仅滚轮（可滚 ScrollView） | True | True | True（不变） |
| E 仅滚轮（不可滚 ScrollView 内按钮） | False | False | False（不变） |
| B 仅滚轮（指针不在滚动区） | False | False | False（不变） |
| F 仅滚轮（普通按钮上） | False | False | False（不变） |
| G 无滚轮 | True | False | False（不变） |
| H 无 UI | False | False | False（不变） |

**新增回归**（`tests/test_wheel_backend_semantics.py` §1，19 条断言）:
A/D 同帧点击+滚轮必须 False；C 可滚 ScrollView 必须 True 且
`scroll_pos.y < 0`；E/F/G/H 边界；未知 UI 保守按已消费；判据助手
None/可滚/不可滚三态。

---

## 2. [P3] `game_player` 的 "渲染API=" 打印入参

**位置**（改后）: `game_player.py:83` `_run_backend_safe`、
`game_player.py:150` `_start_pack`。

### 2.1 语义契约

`渲染API=` 打印的是**实际生效的后端**（`vulkan` / `opengl`），不是入参
（`auto` 也不是后端名）。回退发生后必须打印回退后的后端：

- `vulkan` 初始化失败 -> 发布链兜底回退 `opengl` -> 打印 `opengl`；
- `auto` 在 `run_player` 内部回退 `opengl` -> 打印 `opengl`；
- `auto` 成功 -> 打印 `vulkan`；
- 直接 `opengl` -> 打印 `opengl`。

**根因**（改前）: `_start_pack` 把入参 `backend` 直接写进
`渲染API=%s`；`_run_backend_safe` 回退 OpenGL 后不回传实际后端。

**改法**:

- `_run_backend_safe` 返回实际生效的后端名。启动期临时包一层
  `run_player._run_vulkan/_run_opengl`，只观测**真正跑完**的后端调用
  （抛异常的不算），`finally` 恢复原入口；因此 `auto` 在 `run_player`
  内部的回退也能被看见。
- `_start_pack` 用返回值写日志（`game_player.py:150-152`）。
- 回退/异常策略不变：`SystemExit`、`VkRunError` 仍原样上传；其余
  异常仍兜底回退 OpenGL。

### 2.2 改前 / 改后实测

fake `game_pack`/`scripts` + `run_player` 后端桩（Vulkan 桩抛
`RuntimeError`，OpenGL 桩成功）：

| 入参 | 调用序列 | 改前日志 | 改后日志 |
|---|---|---|---|
| `vulkan`（初始化失败 -> 回退） | vulkan -> opengl | `渲染API=vulkan`（误） | **`渲染API=opengl`** |
| `auto`（内部回退） | vulkan -> opengl | `渲染API=auto`（误） | **`渲染API=opengl`** |
| `auto`（Vk 成功） | vulkan | `渲染API=auto`（误） | **`渲染API=vulkan`** |
| `opengl`（直连） | opengl | `渲染API=opengl` | `渲染API=opengl`（不变） |

**实测输出行**（vulkan 初始化失败、回退 opengl 后）：

    [game_player] 渲染后端启动失败: vulkan (RuntimeError('模拟 Vulkan 初始化失败'))
    [game_player] 已自动回退 OpenGL；若仍失败请把上面这行发给开发者
    游戏已启动: ProbeGame (0 个游戏脚本, 0 个插件, 渲染API=opengl)

改前同一场景的最后一行是 `渲染API=vulkan`；`auto` 内部回退时改前是
`渲染API=auto`。

`_run_backend_safe('vulkan')` 回退后返回值：改前 `None`（run_backend 的
GL 返回值）-> 改后 `'opengl'`。

**新增回归**（`tests/test_wheel_backend_semantics.py` §2，12 条断言）:
上述 4 条日志、`_run_backend_safe` 返回值、以及 `SystemExit` 路径下
`run_player` 两个入口被恢复（不污染后续调用）。

---

## 3. 验收数字

| 门槛 | 改前 | 改后 |
|---|---|---|
| `python tests/_tmp/ab_batch.py`（22 场景，MAE <= 0.0002） | 22/22 PASS，最大 MAE 0.000082 | **22/22 PASS，最大 MAE 0.000082**（逐场景同值） |
| `python tests/run_all.py`（exit=0） | 见下方说明 | 待 R5 收尾后最终重跑（本次中途被并行写覆盖打断） |
| `python tests/test_wheel_backend_semantics.py` | — | **exit=0，31 条断言全 PASS** |
| `python tests/test_vk_ui_input.py` | exit=0 | **exit=0** |
| `python tests/test_backend_fallback_policy.py` | exit=0 | **exit=0** |

### run_all 的一次中途失败（非本批逻辑）

首次 `run_all` 在 10:35 左右失败：`test_wheel_backend_semantics.py`（当时
文件名 `test_r5_wheel_backend.py`）报
`vk_ui has no attribute _wheel_taken_by_scrollview`，
`test_vk_bucket_order.py` 同时失败。核对时间戳：`vk_ui.py` 于 **10:35:14**
被其它进程整文件覆盖，本批局部改动被回退；`vk_renderer.py` 于 10:37:08
仍在被并行写入。两个测试单独重跑均已 PASS
（`test_vk_bucket_order.py` 46 条断言全 PASS）。按主 Agent 裁定，
`vk_ui.py` 写权已交给 R5；R5 收尾后本批只做重跑确认，不再写 `vk_ui.py`。

---

## 4. 遗留 / 未改

1. `vk_player.py:109` 仍保留同名 `_wheel_taken_by_scrollview` 助手
   （F5 加的），与 `vk_ui._wheel_taken_by_scrollview` 判据重复；本批
   允许清单不含 `vk_player.py`，未去重。两者语义一致，取与结果不变。
2. `last_wheel_consumed` 对"未知 UI"（无 `_hit_scroll_view`）仍保守
   按已消费处理（与 F5 的 `vk_player` 助手一致）；真实 `UIManager`
   路径不受影响。
3. `_start_pack` 的 "游戏已启动" 日志仍在阻塞式 `run_backend` 返回后
   打印（既有行为，本批未改时序）。
4. `hud_lines_from_driver` 的 `backend` 参数未动（不在本批缺陷清单）。
5. `run_player` 未被修改；`_run_backend_safe` 的观测包装是启动期
   临时 patch，`finally` 恢复，异常路径有测试固定。
