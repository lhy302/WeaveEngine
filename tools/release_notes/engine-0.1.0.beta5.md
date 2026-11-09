# Loom 引擎 0.1.0.beta5（内测）

> 注：本文是**下一次发包**（0.1.0.beta5）的发布说明草案。开发期代码版本号仍是上一个已发布版本，发包时才跳。

> 本轮**不发布**：只备好版本号/发布说明，禁止建 tag、建 Release、上传资产。

## 本版要点

### E1 · 「TPS 打不到 logic_fps」根因与修复（02 号）

- **根因（可复现、已量化）**：同步推进路径把**调用方给的 dt** 当墙钟用。当 dt 是固定名义值
  （`--bench` 传 `1/120`）而实际只跑到 94 FPS 时，逻辑时钟每秒只累计到 3.17s/4.01s 的时间，
  TPS = 目标 × Σdt/墙钟 = 30×0.79 = **23.7**（与现场读数逐位吻合）。修复后同一口径实测
  TPS 由 **24.0 → ≥30**。
- **修复**：新增 `GLEngine._clock_advance()` 作为推进逻辑时钟的**唯一入口**，输入取
  `max(调用方 dt, 实测墙钟间隔)`；同步 `advance_logic`、渲染帧自驱（`loom_render.render`）、
  异步逻辑线程三条路径共用同一口径。测试/直驱传合成 dt 时行为**逐位不变**（墙钟≈0，max 取合成值）。
- **新增体检口** `engine.get_logic_time_ratio()`：`dt 总和 / 墙钟总和`。
  `ratio≈1 且 TPS<目标` → 瓶颈在**每个逻辑帧本身太贵**（看 `logic_step` / `pipe_wait`）；
  `ratio<1` → 时钟没拿到全部墙钟（调用方 dt 口径/掉帧），先修输入。
- **实测对照**（`Loom/tests/_tmp/tps_probe.py`，场景 `Projects/压测500混合.json` 501 模型）：

| 口径 | 改前 | 改后 |
|---|---|---|
| sync（dt=1/120，94 FPS） | TPS **24.0**（每逻辑帧 15.0 ms） | TPS **≥30**（实测 32.6，ratio 1.07） |
| sync（配速 58 FPS） | — | TPS **30.0**，ratio **1.001** |
| async（编辑器逻辑线程口径，58 FPS） | TPS **30.1** | TPS **30.1**（每逻辑帧 23.4 ms / 33.3 ms 预算） |

- **未闭合**：编辑器（Qt 宿主）实测仍可能低于 30 —— 届时用 `get_logic_time_ratio()` 分流：
  ratio≈1 说明时钟输入没问题，缺口来自「每逻辑帧成本 23 ms + 渲染线程 GIL 竞争」；
  ratio<1 则是宿主 dt 口径问题（在 `loom_gui`/入口侧，需 03 号或入口配合）。
- 次要结论：`--bench` 的口径应传**实测**帧间隔（现在传固定 `1/120`，会系统性低估 TPS）；
  引擎侧修复后不再低估，但基准脚本口径仍建议改。

### E2 · remote-mode 自动降级的引擎侧判据（02 号）

- 新增 `RenderMixin._present_swap()`：上屏失败不再被 `except: pass` 吞掉 —— 记连续失败数、
  首次失败打一行（`[present] 原生上屏失败 (...)`）。
- 新增 `present_health()` 与 `should_fallback_remote(threshold=3)`：入口层据此判断"先试原生、
  失败才切离屏回读"。**引擎不自行切换进程形态**（离屏回读需要 Qt 宿主进程）。
- 入口侧接线（**未在本批落地**，需 03/05 协调）：`Loom.py` 的 `LOOM_REMOTE_MODE` 判定接受
  `auto`：先按原生启动，若 `should_fallback_remote()` 为真则以 `LOOM_REMOTE_MODE=1` 重启一次。

### 其余引擎侧修复（02 号前几轮，已随本版发布）

- **鼠标锁定语义重构**：默认不改锁（`allowed/initial` 未配置 = False）；`allowed=False` 时脚本/宿主
  的 `set_mouse_locked(True)` 一律不生效；锁定/解锁统一走后端工具（GLFW 模式 + 回读校验 +
  Win32 兜底 + 一行日志），不再静默失败。
- **VK 播放器**：解锁键改为**每渲染帧**采样（短按不丢），委托引擎唯一实现；首帧 `on_start` 的初始
  锁定先落定；窗口最小化不再被看门狗误杀（真卡死照杀）；`python run_player.py` 入口的
  `VkInitError` 类身份统一（Q6 回退链在该入口同样生效）。
- **配置分层**：引擎/游戏配置改「只读模板层 + 用户层 delta（`%LOCALAPPDATA%\Loom`）」，
  只读安装目录下也能保存改动；`run_player._persist_backend` 写失败不再被 `or True` 掩盖。
- **GL 播放器补 UI 鼠标派发**（此前只有编辑器/VK 有）：Canvas 按钮的声明式事件在 GL 播放器可用。

## 与 LoomHub 0.1.3 的配合

- Hub 侧远程模式默认关闭（H1）：引擎在无 `LOOM_REMOTE_MODE` 环境变量时走直连渲染。
- 引擎侧接受 `LOOM_REMOTE_MODE=auto` 的语义前提已具备（`should_fallback_remote()` 判据）；
  自动重启到 remote 进程的入口接线待 03/05 落地。