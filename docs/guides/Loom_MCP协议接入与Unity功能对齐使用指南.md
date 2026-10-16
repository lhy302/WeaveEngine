# Loom 引擎 MCP 协议接入与 Unity 功能对齐使用指南

## 一、架构设计与工作原理

Loom 引擎内置了基于 **Anthropic Model Context Protocol (MCP)** 标准协议（JSON-RPC 2.0，基于 `stdio` 传输）的智能化服务层 `loom_mcp.py`。

```text
┌──────────────────────────────────────────────────────────┐
│    大模型客户端 (Claude Desktop / Cursor / DSH Agent)    │
└────────────────────────────┬─────────────────────────────┘
                             │ (MCP 协议: JSON-RPC 2.0 stdio)
┌────────────────────────────▼─────────────────────────────┐
│                 Loom MCP Server (loom_mcp.py)            │
│    • Tools (24 项 Unity 对齐与问题排查原子工具)          │
│    • Resources (场景树、运行度量、控制台日志、DLL 注册表) │
│    • Prompts (自动化关卡搭建、运行性能与崩溃排查模板)    │
└────────────────────────────┬─────────────────────────────┘
                             │ (EAI 接口: HTTP / .agent_port.json)
┌────────────────────────────▼─────────────────────────────┐
│                  Loom 3D 游戏引擎运行时                  │
│   (OpenGL 视口 + 5 大 C ABI 核心 DLL + 嵌入式 Lua 5.4)   │
└──────────────────────────────────────────────────────────┘
```

### 核心设计优势：
1. **轻量零依赖**：基于 Python 3.12 纯标准库开发，无需额外 `pip install` 任何第三方包，开箱即用；
2. **全生命周期自愈**：无论引擎是否已打开，MCP 服务均能自愈处理（未启动时友好提示或通过离线场景 IO 读取）；
3. **线程绝对安全**：外部模型工具调用由 Qt 主线程事件循环安全消费，天然杜绝多线程竞争造成的 OpenGL 上下文或物理崩溃。

---

## 二、三方客户端接入配置

### 1. Claude Desktop 配置
在 `claude_desktop_config.json`（Windows 位于 `%APPDATA%\Claude\claude_desktop_config.json`）中追加：

```json
{
  "mcpServers": {
    "loom-engine": {
      "command": "py",
      "args": [
        "-3.12",
        "D:\\my-project\\Loom(py源代码-工作区)\\Loom\\loom_mcp.py"
      ]
    }
  }
}
```

### 2. Cursor / VS Code (Continue) 配置
在项目 `.cursor/mcp.json` 中配置：
```json
{
  "mcpServers": {
    "loom": {
      "command": "py -3.12 loom_mcp.py",
      "cwd": "D:\\my-project\\Loom(py源代码-工作区)\\Loom"
    }
  }
}
```

---

## 三、Unity 体系功能对齐工具表（24 项核心 Tools）

| 分类 | MCP 工具名称 | 对应 Unity 核心 API | 功能描述 |
|:---:|---|---|---|
| **场景管理** | `unity_scene_new` | `SceneManager.CreateScene` | 创建一个全新的空白场景 |
| | `unity_scene_save` | `EditorSceneManager.SaveScene` | 保存当前场景至指定 `.json` 文件 |
| | `unity_scene_load` | `EditorSceneManager.OpenScene` | 打开并加载指定场景文件 |
| **实体层级** | `unity_gameobject_create` | `GameObject.CreatePrimitive` / `Instantiate` | 实例化物体（支持 `cube`, `sphere`, `plane` 或空白物体） |
| | `unity_gameobject_list` | `Scene.GetRootGameObjects` / Hierarchy | 遍历并输出当前场景的完整物体树状结构 |
| | `unity_gameobject_select` | `Selection.activeGameObject` | 在编辑器中聚焦选中指定物体 |
| | `unity_gameobject_delete` | `Object.Destroy` | 销毁删除指定物体及其子树 |
| | `unity_gameobject_duplicate` | `Object.Instantiate` | 原地复制克隆指定物体 |
| | `unity_gameobject_set_parent` | `Transform.SetParent` | 设置父子层级关系，支持保持世界坐标不变 (`keep_world`) |
| **组件属性** | `unity_transform_set` | `Transform` (position, rotation, scale) | 调整物体三维坐标、欧拉角与缩放比例 |
| | `unity_material_set` | `MeshRenderer.material` | 调整材质基础色、饱和度及法线渲染模式 |
| | `unity_collider_set` | `BoxCollider` / `SphereCollider` | 挂载或配置包围盒碰撞体积与启用状态 |
| | `unity_rigidbody_set` | `Rigidbody` | 赋予刚体动力学参数（质量、重力、运动学、摩擦阻尼系数） |
| **脚本玩法** | `unity_script_add` | `GameObject.AddComponent<Script>` | 为物体挂载内置或自定义玩法脚本（支持 `rotate`、`wasd_move` 等） |
| | `unity_script_remove` | `Object.Destroy(Script)` | 卸载物体上指定序号的脚本组件 |
| | `unity_script_write_file` | `AssetDatabase.CreateAsset` (Script) | 直接在项目 `scripts/` 目录编写或更新纯 Lua 5.4 / Python 脚本 |
| **测试视口** | `unity_playmode_toggle` | `EditorApplication.isPlaying` | 一键切换运行态播放与编辑态（对应 `F5` / `play` 指令） |
| | `unity_capture_viewport` | `ScreenCapture.CaptureScreenshot` | 截取当前视口高清画面，供多模态模型视觉核验与对齐 |
| **发布流水** | `unity_build_player` | `BuildPipeline.BuildPlayer` | 将项目与独立运行时剥离打包为纯净免安装游戏发布夹 |
| **问题排查** | `diag_get_engine_metrics` | `Unity.Profiling.Profiler` | 获取实时帧率、逻辑时钟 TPS、各阶段耗时、DrawCalls 与物理活跃数 |
| | `diag_get_console_logs` | `Application.logMessageReceived` / Console | 读取内部环形控制台日志流与错误堆栈信息 |
| | `diag_inspect_gameobject` | `EditorUtility.DisplayCustomInfo` | 深度透视指定物体的所有组件、局部/世界矩阵与脚本变量 |
| | `diag_check_dll_integrity` | Native DLL Validation | 校验 5 大核心 C ABI 动态库 SHA256 钉扎与 ABI 导出完整性 |
| | `diag_check_crash_dumps` | Crash Dump Forensics | 扫描崩溃日志目录下的 Windows MiniDump (`.dmp`) 文件记录 |

---

## 四、模型可感知的上下文资源（MCP Resources）

客户端通过标准 `resources/read` 协议可直接订阅引擎核心状态：

1. `loom://scene/active`
   - **MIME 类型**：`application/json`
   - **内容**：当前激活场景所有物体的层级树、GUID、坐标、旋转、挂载组件与自定义变量，结构与 Unity 场景资产一一对齐。
2. `loom://engine/metrics`
   - **MIME 类型**：`application/json`
   - **内容**：当前渲染帧率（FPS）、物理逻辑时钟（TPS）、DrawCall 批次、材质桶数量、主线程阶段耗时（`_stage_times`）。
3. `loom://engine/logs`
   - **MIME 类型**：`text/plain`
   - **内容**：引擎控制台最近 200 行实时日志，包含脚本报错、物理告警与命令响应记录。
4. `loom://engine/dll_registry`
   - **MIME 类型**：`application/json`
   - **内容**：5 大官方核心动态库（`ckernels`, `pipeline`, `script`, `physics`, `module_ref`）的官方认证标志与 SHA256 物理钉扎哈希。

---

## 五、典型问题排查与开发工作流（MCP Prompts）

### 1. 场景与性能故障自动化排查 (`diagnose_engine_issue`)
* **用户输入**：“为什么我的场景一按播放模式画面就会掉帧？”
* **模型通过 MCP 自动执行**：
  1. 调用 `diag_get_engine_metrics`，提取 FPS 与逻辑 TPS 分段耗时；
  2. 调用 `diag_get_console_logs`，检查是否有脚本抛出未捕获异常导致堆栈重试；
  3. 调用 `diag_check_dll_integrity`，核对 `pipeline.dll` 与 `physics.dll` 是否已并网生效；
  4. 输出根因诊断报告并直接给出优化指令。

### 2. 自然语言全自动生成可玩关卡 (`create_player_character`)
* **用户输入**：“在场景原点放置一个红色球体玩家，加刚体物理，并让它能用 WASD 移动与第三人称相机跟随。”
* **模型通过 MCP 自动执行**：
  1. 调用 `unity_gameobject_create(primitive="sphere", name="Player", position=[0, 1, 0])` 创建物体；
  2. 调用 `unity_material_set(name_or_id="Player", color="#E74C3C", saturation=1.2)` 赋予红色材质；
  3. 调用 `unity_rigidbody_set(name_or_id="Player", mass=1.0, use_gravity=true)` 开启真实物理刚体；
  4. 调用 `unity_script_add(name_or_id="Player", script_id="wasd_move")` 与 `camera_follow`；
  5. 调用 `unity_playmode_toggle(on=true)` 开启测试；
  6. 调用 `unity_capture_viewport()` 截取画面回传给用户核验：“角色与玩法已就绪，已开始播放！”

---

## 六、自动化测试与协议自检验证

已在工程中固化独立的 MCP 协议栈与工具集全功能自动化验证探针：

```powershell
cd 'Loom(py源代码-工作区)\Loom'
py -3.12 tests\_tmp\test_mcp_server.py
```

### 实测结果（100% PASS）：
- `[Pass 1]` JSON-RPC 2.0 协议初始化握手（`initialize`）与保活（`ping`）完全遵从 MCP 标准；
- `[Pass 2]` 24 项 Unity 体系核心工具定义与 inputSchema 参数规范验证通过；
- `[Pass 3]` 4 大实时 MCP Resource 资源订阅与读取全部闭环；
- `[Pass 4]` 故障排查与角色搭建 MCP Prompt 模板解析就绪；
- `[Pass 5]` 实机调用 `diag_check_dll_integrity`、`diag_check_crash_dumps` 与 `unity_script_write_file`，5 大 C ABI 动态库 SHA 验证 100% 吻合，测试脚本写入挂载成功。
