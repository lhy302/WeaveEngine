# MCP 全功能自动化验收（2026-11-07）

> 方式：真实启动编辑器（`Loom.py --agent`）→ 真实 MCP stdio 协议（`loom_mcp.py`）→ 逐操作调用 74 个工具中的代表集。
> 脚本：`Loom/tests/_tmp/e2e_mcp_full.py`；原始数据：`docs/audit/e2e_mcp_report.json`；视口证据：`docs/audit/e2e_mcp_viewport.png`。

## 结果：**40/40 全部通过**

| 阶段 | 覆盖项 | 结果 |
|---|---|---|
| 协议 | `initialize` 握手、`tools/list`（74 个工具）、`resources/list`、`prompts/list` | ✅ |
| 场景 | 新建空场景、创建立方体/球体/平面、物体列表 | ✅ |
| 变换与外观 | 选中、改位置、改颜色、隐藏/显示 | ✅ |
| 灯光/相机 | 加平行光、加相机 | ✅ |
| 查询 | 射线检测（命中平面，distance=5.0）、按名查找 | ✅ |
| UI | `loom_ui_add` 文本元素 | ✅ |
| 批次撤销 | `agent_batch_begin` → 3 次创建 → `agent_batch_end` → **一步 undo 三个全消失** → **一步 redo 全部恢复** | ✅ |
| 播放与物理 | 进入播放、`physics_simulate` 10 帧（fixed_dt=0.0333, sub_steps=2）、退出播放 | ✅ |
| 渲染 | `unity_capture_viewport` 出图（见 viewport 证据） | ✅ |
| 存档 | 保存 → 新建空场景 → 加载 → 物体恢复 | ✅ |
| 诊断 | 引擎指标（fps=234）、控制台日志、检查物体 | ✅ |
| 收尾 | `quit`（丢弃）正常退出 | ✅ |

## 附：一次测试中的真实错误（已确认是**测试脚本参数错**，非引擎缺陷）

首轮 39/40：`loom_find_by_name` 传了 `{name: ...}`，而 MCP schema 与 EAI 命令都要求 `model`。
两者契约**一致**（schema `properties.model` ↔ `cmd_find_by_name` 读 `args["model"]`），
修正参数后 40/40。

## 结论

- 引擎可正常启动、MCP 可正常连接、命令链路（HTTP → Qt 主线程 → EditorApp）工作正常；
- 主要功能（建模/变换/材质/灯光/相机/UI/批次撤销/播放/物理/渲染/存档/诊断）在**真实 MCP 路径**下均可用；
- 单条命令耗时 10~255ms（首条含编辑器预热），符合 120ms 节奏下的可视化预期。