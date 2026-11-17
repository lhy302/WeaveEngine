# Agent 可视化改造 — 逐条节奏 / 步进 / 批次撤销 / 相机聚焦

- 日期: 2026-11-07
- 负责文件: `agent_commands.py`、`undo.py`、`editor.py`
- 新增测试: `tests/test_agent_pacing.py`、`tests/test_undo_batch.py`、`tests/test_editor_focus.py`
- 台账同步: `tests/test_eai_real.py` 的命令覆盖率闸门补 4 条新命令的真编辑器执行 (命令表 95 条)
- 未改: `loom_mcp.py`(MCP 工具层)、`ui/loom_gui.py`(并行代理负责)、其它业务代码

## 1. 共享接口契约 (与 GUI 侧严格一致, 已按契约实现)

```python
# AgentService
.pace_ms    float  # LOOM_AGENT_PACE_MS, 缺省 120.0
.step_mode  bool   # LOOM_AGENT_STEP == "1"
.paused     bool   # 步进模式执行完 1 条置 True
.resume_step()     # 解除暂停 + 立即执行下一条 (drain 内重入有 _draining 兜底)
.progress()        # (done, total): total = 本轮已执行 + 队列剩余; 队列空且无在途 -> (0,0)
.last_info()       # (cmd, ok, ms)

# GUI 钩子 (全部 getattr 取, 缺失/异常只记日志, 绝不打断命令链)
win._agent_progress(cmd, args, done, total)
win._agent_busy(active)
win._agent_after_command()
```

## 2. 逐条执行 + 节奏 (A)

- `drain()` 每拍**最多执行 1 条**: 出队前先判 `paused` / 队列空 / `pace_ms` 时间戳;
  不足 pace 直接返回, 由 4ms QTimer 继续触发, 不依赖定时器精度。
- 执行后顺序回调 `_agent_progress(cmd,args,done,total)` -> `_agent_after_command()`。
- 忙态: 队列空转非空 -> `_agent_busy(True)`; 队列空且距上次执行 >= 0.8s -> `_agent_busy(False)`
  (时间戳在 drain 里判; 状态不变不重复通知, 防 4ms 刷爆状态栏)。
- `LOOM_AGENT_PACE_MS=0` -> 一次排空 = 旧行为 (批量脚本/既有 HTTP 链路兼容)。
- 命令异常仍由 `dispatch` 兜底; `_run_one` 再兜一层, 保证 `ev` 一定 `set()`(HTTP submit 不会永挂)。

## 3. 步进模式 (E)

- `LOOM_AGENT_STEP=1`: 每执行完 1 条 `paused=True`, 后续 drain 直接返回;
  `resume_step()` 清 paused 并立即执行下一条。paused 时队列非空仍保持忙态 (红点常亮)。
- 未开启步进模式时行为与旧版一致 (仅多了节奏)。

## 4. 批次撤销 (D)

`undo.py`:
- 新增 `BatchCommand` (undo 逆序 / redo 正序) 与 `UndoManager.begin_batch/end_batch/cancel_batch`、
  `batch_active/batch_size` 只读属性。
- 批内 `push`/`push_no_do` 照常执行 `do()`, 但只收进批列表; `end_batch` 合成一条压栈,
  **不再重复执行**; 空批不压栈; `clear()` 一并复位批次状态。
- 悬挂保护: 未 end 又 `begin_batch` -> 自动 cancel 旧批并返回 `had_stale=True`。

`agent_commands.py` 新增 EAI 命令:
- `agent_batch_begin {label?}` (检测到悬挂批次自动 cancel 并写日志告警)
- `agent_batch_end` (返回 `{commands, label, undoable}`; 无批次 -> 明确拒绝)
- `agent_batch_cancel` (返回 `{cancelled}`; 已执行的修改不回滚, 也不留撤销记录)

## 5. 相机聚焦 (C)

`editor.py`:
- `focus_on_object(index, smooth=True)`: 世界 AABB 中心 -> `camera_target`;
  包围球半径 × `FOCUS_DISTANCE_FACTOR(2.6)` -> `camera_distance` (clamp 0.5~1000), yaw/pitch 不变。
- `smooth`: `_focus_anim = {t0, dur=0.18, from/to target+distance}`, 由 `render()` 与
  `_update_camera()` 调 `_advance_focus_anim()` 做 180ms 线性插值; 播放态不推进、不移动播放相机。
  逻辑值先落目标值, 因此聚焦命令的任何即时回读都看到最终值; 用户滚轮/平移/转视角会取消动画。
- 自动聚焦: `object_add` / `object_select` 成功后, 若 `settings.agent_auto_focus` 未显式关闭
  (缺省 True) 则调用 `focus_on_object(index, smooth=True)`; 播放态/无该方法时静默跳过。

`agent_commands.py` 新增 `view_focus {name?|index?, smooth?=true}`
(缺省聚焦当前选中; 重名走 `index=` 歧义契约; 越界/找不到/播放态 -> 明确 error)。

## 6. 测试与实测

新增测试 (均无头, run_all 自动收集):
| 测试 | 覆盖 |
|---|---|
| `tests/test_agent_pacing.py` | pace=120 需 5 次 drain 且间隔受控 / pace=0 一次排空 / step 模式 1 条即 paused + resume_step / 三个 GUI 钩子 / progress+last_info / 无钩子桩不崩 |
| `tests/test_undo_batch.py` | 批内 do 正常但不压栈 / end 合成一步不重复执行 / undo 逆序 + redo 正序 / cancel / 悬挂 begin 自动 cancel / EAI 三件套 |
| `tests/test_editor_focus.py` | target=世界 AABB 中心、distance=包围球半径×系数 (容差 1e-6) / 180ms 插值 0%/50%/100% / 播放态拒绝 / view_focus / 自动聚焦开关 |

改前 (未实现时):
- `test_agent_pacing.py` exit=1: `AttributeError: 'AgentService' object has no attribute 'pace_ms'`
- `test_undo_batch.py` exit=1: `AttributeError: 'UndoManager' object has no attribute 'begin_batch'`
- `test_editor_focus.py` exit=1: FAIL 11 项 (无 focus_on_object / 无 view_focus / 无 _auto_focus_enabled)

改后: 三个新测试全部 ALL PASS。

回归实测 (改后):
- `python tests/run_all.py` -> **exit=0**, 末尾 "全部测试完成 ✅"。
  (改前基线 exit=1 的唯一失败是并行代理的 `tests/test_agent_ui_indicator.py` —— 当时 GUI 侧钩子
  尚未落地; 该代理落地后本部分改后跑已全绿。)
- `python tests/_tmp/ab_batch.py` -> 22 场景, 失败 0, MAE 最大 `0.000082`
  (`ab_ui_scene.json`, 门槛 <= 0.0002), 与改前完全一致。

命令台账同步 (说明):
- `tests/test_eai_real.py` 的覆盖率闸门要求"命令表每条命令都被真编辑器执行过",
  新增 4 条命令后必须补测; 已在 `t_api_coverage_fill` 末尾补 `view_focus` /
  `agent_batch_begin` / `agent_batch_end` / `agent_batch_cancel` 的真编辑器执行与断言
  (命令表 95 条全绿)。这是唯一一处本部分职责外的文件改动 (测试台账, 非业务代码)。

## 7. 遗留 / 风险

1. 步进模式下 HTTP `submit` 仍按 30s 超时等待人手点"下一步": 超时返回错误, 但命令仍会在
   人点击后执行 -> Agent 重试可能重复提交。步进模式是人工裁决的可选模式, 暂按现状保留
   (GUI 侧 [下一步] 按钮走 `resume_step()`, 不受 30s 影响)。
2. 自动聚焦缺省开启, 会让每个 `object_add`/`object_select` 多一次 `compute_world_matrices`
   (静止场景走缓存, 实测 ~0.1ms); 批量脚本要完全静默可设 `agent_auto_focus=false`。
3. 相机"用此相机预览"(preview_camera) 期间聚焦只改轨道相机参数, 退出预览后才可见;
   未强制退出预览 (避免打断人工预览状态)。
