# Agent 可视化 — GUI 侧 (B 状态栏进度 / E 步进模式) 修复报告

- 日期: 2026-11-07
- 负责文件: `ui/loom_gui.py`（独占）
- 新增测试: `tests/test_agent_ui_indicator.py`
- 未改 `agent_commands.py` / `loom_mcp.py`；未执行 git add/commit。

## 1. 改动

| 位置 | 改动 |
|---|---|
| `LoomGUI.__init__` | 新增 `_agent_service/_agent_status_active/_agent_busy_active/_agent_idle_token` 四个状态字段（在构建工具栏前就位）。 |
| `_build_toolbar` | 新增 QLabel 红点「● AI 操作中」与 QToolButton「下一步」；两者用 `QWidgetAction` 控制显隐，默认隐藏。 |
| `_build_statusbar` | 新增永久控件「AI 等待下一步」提示（步进模式 paused 时显示）。 |
| 新方法 | `_agent_args_summary / _agent_progress / _agent_idle / _agent_tb_visible / _agent_busy / _agent_after_command / _bind_agent_service / _update_agent_step_ui / _on_agent_step_clicked`。 |
| `_refresh_status` | 在最终 `showMessage` 前加保护：Agent 进度占用状态栏时，300ms 轮询不得覆盖；物理线程告警仍优先。 |
| `run_loom_gui --agent` | 创建 `AgentService` 后调用 `win._bind_agent_service(agent)`（绑定 + 按 `step_mode` 同步按钮），再启动 HTTP 服务。 |

## 2. 共享契约实现（严格按契约，无单方面改动）

```python
win._agent_progress(cmd, args, done, total)  # "AI: <cmd> <k=v 摘要<=40> (done/total)"
win._agent_busy(active)                      # 红点显隐 + 状态栏 #e06c75 / 复位
win._agent_after_command()                   # viewport.update() + repaint()
```

- 参数摘要：`k=v` 空格拼接，dict/list 走紧凑 JSON，换行压平，超 40 字符截断为 39 字 + 省略号。
- 空闲恢复：每条命令后 `QTimer.singleShot(1500, ...)`；用自增 token 防重入（新命令使旧定时器作废），到期后 `clearMessage()` 并回调 `_refresh_status()` 恢复默认文本。
- 步进：`_update_agent_step_ui()` 读 `service.step_mode` / `service.paused`；按钮点击调 `service.resume_step()`。因 A1 的 `drain()` 在 `_run_one()`（含钩子）之后才置 `paused=True`，额外用 200ms 轻量轮询兜底，保证「AI 等待下一步」不滞后。
- 真机启动顺序 = 构造 → 绑定 → `win.show()`；show 时 QToolBar 会把当时不可见的 QWidgetAction 控件重新藏起，故绑定后加 `singleShot(0, _update_agent_step_ui)` 首拍重同步（已实测必需）。

## 3. 验收实测

### 3.1 新增测试（Qt offscreen + 桩 service）

```
python tests\test_agent_ui_indicator.py   -> exit=0, 18/18 PASS
```

覆盖：`_agent_progress` 文本含 `(3/10)` 与 `k=v` 摘要、摘要 <= 40、1.5s 空闲恢复；`_agent_busy(True/False)` 红点显隐与状态栏 `#e06c75` 变色/复位；`_agent_after_command` 各调用一次 update/repaint；步进按钮仅 `step_mode` 可见、paused 提示、点击 `resume_step()`。测试复刻真机「绑定在 show 之前」顺序。

### 3.2 改前 / 改后（同一检查脚本）

```
HEAD:Loom/ui/loom_gui.py  hooks: {_agent_progress: False, _agent_busy: False, _agent_after_command: False}
当前 ui/loom_gui.py       hooks: {_agent_progress: True,  _agent_busy: True,  _agent_after_command: True}
```

改前模块无任何 Agent 钩子，新增测试 18 项在 HEAD 上全部不成立；改后 18/18 PASS。

### 3.3 回归

```
python tests\run_all.py                    -> exit=0, "全部测试完成 ✅"（含新增测试）
python tests\test_agent_pacing.py          -> ALL PASS (26 项, A1 契约联调)
python tests\test_editor_ui.py             -> ALL PASS
python tests\test_qt_delete_confirm.py     -> ALL PASS
python tests\_tmp\ab_batch.py             -> 22 场景全 PASS, 最大 MAE 0.000082 (门槛 0.0002)
```

## 4. 遗留 / 注意

- 无功能遗留。
- `_agent_busy(False)` 在无 Agent 进度时清空状态栏消息；下一次 300ms `_refresh_status` 会恢复默认文本。
- 步进模式下 200ms 轮询只读 `service.paused`，无写操作；非步进模式自动停表。
