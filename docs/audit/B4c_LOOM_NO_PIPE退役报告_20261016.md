# B4c 逃生门退役 — LOOM_NO_PIPE 实施报告

**日期**：2026-10-16
**执行者**：施工 Agent
**依据蓝图**：docs/design/逃生门退役设计.md §2.3（脚本/物理组件类）
**前序锚点**：75f286d（B4 文档同步）

---

## 一、目标

退役 `LOOM_NO_PIPE`（A/B 基线逃生门），同时保留系统极限工况下的有限兜底。
B4c 独立于 B4（用户拍板），涉及 engine 主循环 + 降级边界。

---

## 二、调研发现的偏差（施工前已交用户审核）

| # | 偏差 | 结论 |
|---|---|---|
| A | `LOOM_NO_PIPE` 与「降级分支」共用同一 else 分支 | else 分支保留（服务 _degraded / _pipe_disabled / 桥建失败）|
| B | `LOOM_NO_PIPE` 双重触发（loom_physics + engine 冗余保险）| 两处都删（A1）|
| C | 4 个探针依赖 `LOOM_NO_PIPE` 做 A/B 对照 | 改单档，不删除 |

**用户核心决策（D-final）**：`_ensure_phys_pipe` 的 `Thread.start()` 失败是**系统极限工况**（OS 线程数/内存耗尽），
保留有限兜底 + 醒目双语告警 + `_phys_pipe_sysfail` 标志，**HUD + GUI 状态栏暴露**，
提醒用户立即保存 + 关闭 + 排查。

---

## 三、改动清单

### 3.1 主线

| 文件 | 动作 |
|---|---|
| loom_physics.py | `_ensure_phys_pipe`：删 LOOM_NO_PIPE env 门；`except` 改双语醒目 banner + 置 `_phys_pipe_sysfail` |
| engine.py | `_logic_frame` pipe_ok 删 `LOOM_NO_PIPE` env 判断；初始化加 `_phys_pipe_sysfail = False` |
| loom_hud.py | `_hud_lines` 加醒目标志行（仅 `_phys_pipe_sysfail` 置位时）|
| ui/loom_gui.py | `_refresh_status` 加醒目前缀 + 一次性弹窗（QMessageBox.critical）|

### 3.2 探针同步（C1 决策：改单档，不删除）

| 探针 | 动作 |
|---|---|
| batch5_par_probe.py | 删 `os.environ['LOOM_NO_PIPE'] = '1'` 死语句 |
| qt_play_probe.py | 删 `--nopipe` 分支 |
| split_play_probe.py | 删 `--nopipe`/`--nopipe2` 分支 + docstring 更新 |
| prof_phys_gil.py | 更新注释（引用 `_pipe_disabled` 而非 env）|

### 3.3 docstring

- physics_pipe.py：`LOOM_NO_PIPE=1 = 线程永不建` 改为 B4c 退役说明

---

## 四、退役的 A 类逃生门

| 变量 | 原语义 | 处置 |
|---|---|---|
| `LOOM_NO_PIPE` | 线程永不建（A/B 基线）| 删 |

**保留项（功能边界，非逃生门）**：
- `_degraded`：`wait_pending` 超时降级标志（非 env）
- `_pipe_disabled`：`_pipe_post` 提交异常降级标志（非 env）
- `_phys_bridge is None`：桥建失败（非 env）

**新增（系统极限工况兜底）**：
- `_phys_pipe_sysfail`：`Thread.start()` 失败标志，HUD + GUI 状态栏暴露

---

## 五、验收结果

| 探针 | 结果 |
|---|---|
| pipe_check.py | ALL PASS |
| physics_c_check.py | ALL PASS |
| physics_dll_val_check.py | ALL VERIFICATIONS PASSED |
| module_registry_check.py | ALL PASS（36/36）|
| test_physics_bridge.py | ALL PASS ✅ |
| test_parallel.py | ALL PASS ✅ |
| test_xform_sync.py | OK |

---

## 六、方案偏差记录

无路线分叉（调研阶段的 3 个偏差已交用户审核拍板；D 决策由用户深度质疑后确定 D-final 有限兜底方案）。

**用户原话（D 决策依据）**：
> "所以 D 这是一条针对系统极限工况下的兜底对吧。要不为其提供有限兜底但是提醒用户尽快关闭软件排查为什么出现了系统资源耗尽情况，这种工况再跑下去崩的可能就不是我们的软件而是整个系统了。所以提供兜底但是兜底开始只是保证能把当前的活快速收尾避免丢数据。"

---

## 七、未做项

- B5~B8：SAP / interp C 化 / 帧调度 / 渲染特性 退役（蓝图 §3 顺序 5~8）
- `LOOM_NO_PIPE` 在历史 .txt 报告与旧物证 .json 中的文字引用未清理（只读历史，不动）

---

## 八、后续

- B 线继续：按蓝图 §3 顺序推进 B5（SAP 粗筛退役）
