# Loom 引擎 0.1.0.beta7（内测 / prerelease）

本版是**编译版引擎包**（Nuitka standalone 编辑器 + onedir 构建器（`builder\build_game.exe`）+ 编译版播放器运行时），
可直接安装/解压后由 LoomHub 添加为解释器（`kind=exe`）。实测工具链：Python 3.13.15 + Nuitka 4.3.5 + MSVC cl 14.3。

## 一、本版定位：设计失误扫尾 + 地基重构（人类裁定）

beta7 不是功能版。人类 2026-11-18 裁定原文：「beta7 是对所有设计失误的扫尾。只要是找出来的工程失误都算作 beta7 的修复之一」；
同月方法论定稿把「大文件按域拆分」明确列为**设计失误修正**而非重构偏好（「多功能混杂在同一文件本身就是设计失误」）。
因此本版主工作量在**结构**（目录重构成 20 个语义包、四个超大文件按域拆开、双后端语义收口）与**工程失误清零**（残留窗口、打包链 P0、文件卫生）。
功能面变化逐条列在第二节，全部是「原本就坏/不一致」的地方被修正，没有新增功能。

## 二、用户可见的行为变化（逐条：现象 → 修法 → 守门）

### 1）编辑器可以用 Vulkan 后端（S1~S5 五阶段落地）
- 以前：编辑器只有 GL 一种视口后端，VK 只在播放器可用。
- 现在：`--backend vulkan` / 配置 `render_api=vulkan` 时编辑器走 `VkEditorApp(_EditorCore, SceneDriver)`，`--ui qt` 下是 LoomGUI + `VkViewport`。
- 关键是**播放态对拍**：编辑器里点播放后的表现，与「同一份场景用同一后端正常播放」逐项相等（相机/世界矩阵/钩子序/时钟/UI 树/生效天空盒），4 个时刻逐像素 MAE=0.0，gizmo/选中框叠加层中心线重合。
- 守门：`test_editor_play_parity`（575）、`test_editor_play_pixel_parity`（17）、`test_vk_overlay_primitives`（24）、`test_vk_editor_smoke`（16）。

### 2）编辑器渲染后端改为配置驱动（一个键全局消费）
- 设置面板里可选「渲染后端」（GL / Vulkan / 自动），**重启编辑器生效**；该键同时决定编辑视口与编辑器内播放的后端。
- 优先级：`--backend` 命令行显式最高 > 配置文件 `render_api` > 默认（自动 = 先试 VK，失败回退 GL）。
- **VK 启动失败自动回退**：backend=vulkan（无论来自配置还是显式）启动时先探测；失败不建 VK 视口、本次回退 GL 视口并给出可见提示。
  其中**配置来源**的 vulkan 会被自动改写为 `opengl`（避免每次启动都撞同一堵墙）；显式 `--backend vulkan` **不改写配置**（只回退 + 提示）。
- 设置面板**无条件可达**：编辑器尚未就绪（或 VK 初始化失败）时，界面/保存目录/渲染后端下拉仍照常渲染，不会点不开设置。
- 守门：`test_editor_backend_config_parity`（101）、`test_editor_vk_fallback_panel`（55，真窗口父子进程）、`test_entry_backend_parity`（112）。

### 3）GUI 操作全量走命令层，且进撤销栈
- 工具栏/菜单动作、层级树挂父与改名、检查器数值写、同名族等 GUI 操作，全部改走 `_invoke_cmd` → EAI 命令层，与命令行坞/远程调用共用**同一批命令体**（以前是 GUI 自己直接调引擎方法，两套行为会漂移）。
- 相机操作也进了撤销栈：GUI 里移动相机后可以撤销/重做（以前相机命令不进撤销栈）。
- 豁免面保持直调：鼠标拾取/gizmo 拖拽/右键轨道/滚轮/WASDQE 这些**连贯性操作**不进命令层（否则每一帧都会塞进撤销栈）。
- 守门：`test_gui_command_unification`（225，含「GUI ≡ 命令行等价」与拒绝批次的 toast 文案）。

### 4）相机挂相机崩溃修复 + 相机父链保存/加载持久化
- 现象：把相机挂到另一个相机下（reparent camera→camera）直接 `AttributeError` 崩溃；且相机父链保存后重新加载会丢。
- 修法：引擎层单点修复（不再各入口各写一份）+ `scene.camera._link_camera_parents` 唯一实现；`id_map` 纳入相机 guid、防环整次拒绝、孤儿父脱根并告警。
- 守门：`test_camera_parent_serialization`（28）。

### 5）编辑器「滚轮反语义」修复
- 现象：编辑器视口里滚轮缩放方向与播放器相反（P-09 裁决要求同向）。
- 修法：对齐播放器同款判据（同源共享，不是再写一份取反）。
- 守门：`test_editor_wheel_semantics`（20）、`test_wheel_backend_semantics`（31）。

### 6）网格遮挡 / 粗线深度修复（网格不再穿物体）
- 现象：编辑器网格画在 3D 物体前面（深度不参与），粗线四边形的角点 z 还被互换过一次，导致网格深度算错。
- 修法：GL 网格改在场景 pass 内绘制（深度 = 场景深度，深度测试才成立）；粗线四边形角点 z 修正；`grid_in_scene_pass` 提升为两端显式能力契约（`EngineCore=False` / `GLEngine=True`）。
- 守门：`test_grid_occlusion_parity`（真窗口像素对拍，GL/VK 各 8 条 + 父门 13 条）、`test_line_depth_plane`（6）、`test_line_degenerate_segment_parity`（13）。

### 7）`mouse_rel` 语义两端统一 + `ui_consumed`
- 现象：VK 的「本帧鼠标增量」在 UI 拖动/滚轮时与 GL 不一致，脚本读到的 `mouse_rel` 会有两端差异。
- 修法：VK 改为**无条件喂**（= GL 本帧物理增量语义），`SceneDriver` 补 `ui_consumed`，相机消费点早退（UI 拖动不转视角、滚轮不连坐）。
- 守门：`test_mouse_rel_ui_consumed_parity`（45）。

### 8）编辑器「退出播放」的 `on_disable` 从未触发
- 现象：脚本里挂了 `on_disable`，进播放再退出时回调从不触发（GL 编辑器形状下）。
- 修法：派发循环前移到 `apply_snapshot` 重建组件之前（同源唯一实现）。
- 守门：S1 对拍门（编辑器播放态 vs 播放器，299 条）。

### 9）collider 命令带字段时 `enabled` 被翻转
- 现象：命令行/EAI 下发 collider 属性时，`enabled` 字段被反向写入。
- 修法：字段翻转修掉 + 加不变量断言（22 条）。
- 守门：`test_gui_command_unification` F9 组。

### 10）场景 guid 确定性派生
- 以前资产 guid 来自随机/时间，同一份内容重复导入会产生不同 guid。
- 现在按内容确定性派生（唯一真源 `scene/identity.py`），迁移模块独立化。
- 守门：`test_scene_contract`（48，含 guid 派生 G 组）、`test_asset_guid`。

## 三、兼容性（重要）

1. **场景格式仍是 v12**，唯一真源 `scene/contract.CURRENT_VERSION = 12`。beta7 场景与 beta6 **可以互相打开**（本版不改任何场景/资产格式）。
2. **VK `SceneDriver` 的 5 个历史内部形态名不再是入口**（Q-B7-24-5）：
   `step`（删除）、`render_pose`→`compute_frame_view_proj`、`load_from_data`→`build_scene_from_data`、
   `camera_pos`→`current_camera_position`、`apply_dev_camera_mouse`→`apply_editor_camera_mouse`。
   理由：它们是「名字像但语义不同」的假别名（例如 `render(delta_time)` 是整帧含上屏，`render_pose` 只算位姿/VP）。
   **引擎公开 API 不变**；只有直接 reach VK 后端内部名的脚本需要改名。
3. **目录重构与大文件拆分不影响用户脚本**：旧导入名全部保留兼容 shim（`import agent_commands` 仍是可用入口，`agent_commands is eai`；`import loom_ui` 同理 `loom_ui is ui.canvas`）。

## 四、工程结构（本版主要工作量）

- **117 个平铺模块 → 20 个语义包**（B1~B6 六批，行为零变化，旧导入名换身不换语义）。
- **四个超大文件按域拆分**（纯搬迁 + 兼容 shim，每批都有结构门锁行数与方法数）：

| 原文件 | 原行数 | 拆成 | 现在 |
|---|---|---|---|
| `agent_commands.py` | 4222 | `eai/` 36 个域文件 | 25 行 shim（`_COMMANDS` 106 条逐字锁） |
| `loom_ui.py` | 1728 | `ui/canvas/` 7 个文件 | 24 行 shim（15 类双路导入同一对象） |
| `gui/main_window.py` | 4129 | `gui/panels/` 12 个面板 mixin | 1084 行装配壳（131 方法 = 23 + 108） |
| `editor/core.py` | 3101 | `editor/core_*.py` 11 个域 | 1172 行装配层（146 方法 = 留守 17 + 搬走 129） |

- **全仓最大文件从 4222 行降到 2127 行**（`render/vk/renderer.py`，下一批拆分目标）。
- 台账 `ARCHITECTURE.md` 按实况重画为 23 张 Mermaid 图，逐文件行数实测：**245 个 .py / 67898 行**。

## 五、打包链：修掉两个 P0 + 一个被发布门拦下的收包缺陷

### 1）两个 P0（打包链断在编译产物里）
- `build_engine` 调构建器的方式改为 `-m build.build_game`：B6 目录重构后按脚本方式调用会让包内绝对 import `build.game_pack` 无法解析（`ModuleNotFoundError: No module named 'build'`）。
- `build_entry.py` 补 `import run_player`：Q-B7-60-1 引入的裸名，在 `--ui qt` 默认分支会 `NameError`。

### 2）源码包排除表撞名（本次发布门 `verify_pkg_vs_head` 拦下，已修 + 加门）
- 现象：源码包里**整个 `Loom/assets/` 引擎包缺失**（5 个 .py），包内引擎 .py 221 / HEAD 226。
- 根因：`tools/package_engine.py` 的 `EXCLUDE_DIRS` 里有小写 `'assets'` —— 那是「排除**用户游戏**资产目录」时代写的条目；B6 把引擎自己的资产层做成 `Loom/assets/` 包后撞名，被打包器当成用户资产整个排除。
- 修法：去掉小写 `assets`（保留用户工程约定的大写 `Assets` / `Projects` / `保存` / `发布` 排除），并新增防回潮门 `test_package_excludes_no_engine_package`：锁「排除表 ∩ 引擎 .py 包 = 空（`tests` / `player_runtime` 两个设计上就排除的子树除外）」「用户工程排除项不许丢」「`collect_files` 必须真收到 `Loom/assets/` 的 5 个 .py」。
- 结果：重打源码包后对拍 **226/226、缺失 0**。

## 六、验证体系（本版真实数字）

- `Loom/tests/run_all.py` 收集 **179 个**测试文件（本版新增 8 个门：四个拆分结构门 + 残留窗口两门 + 打包排除表门 + eai 拆分结构门）。
- 新增门：`test_eai_split` 11 / `test_ui_canvas_split` 19 / `test_gui_split` 65 / `test_editor_core_split` 41（结构拆分）、`test_no_stray_windows` 12 / `test_backend_dialog_autoclose` 11（残留窗口）、`test_package_excludes_no_engine_package` 7。
- **残留窗口清零**：以前跑测试会弹出不自动关闭的窗口等人手点（实测某模态框阻塞 213.7s / 283.8s 直到人工关闭）。现在测试套件可**完全无人值守**跑完：`LOOM_NO_DIALOG` 在 33 个测试文件里强制置 1（不再 `setdefault`，外部环境污染不再破防）、`backend_guard` 新增**可选**弹窗自动关闭 `LOOM_DIALOG_AUTO_CLOSE_MS=<毫秒>`（不设时产品行为不变，真实用户照旧必须看弹窗）、子探针优雅关窗 + 有界 watchdog、父门 `finally` 收尸。
- 像素门：A/B 场景 26 个，MAE 与既有基线逐值一致（**没有移动任何基线**）。
- 二进制卫生：三个 exe `3/3 合格`（`CompanyName=lhy302` / `ProductName=Loom` / `FileDescription` 齐全 / `FileVersion=0.1.0.7` / 形态 onedir）。

## 七、本次交付包

| 产物 | 字节 | 显示大小 | sha256 |
|---|---|---|---|
| `Loom-0.1.0.beta7-compiled.zip` | 145852556 | 139.10 MB | `4c866ea1822e4d3b53d016b136e90855c5e149d4c94afec44c1087dbfeb82faa` |
| `Loom-0.1.0.beta7-source.zip` | 359299507 | 342.65 MB | `67acafcd870909efe066bbbc4d0beeae62592d50738eec188bf3d0acd81128ca` |
| `LoomHub-0.1.5-Setup.exe` | 25668225 | 24.48 MB | `516516fc9c3eaac80fafc36ab33fdf566338e6722e2ed106d879e32902ca3de6` |

- 三件同日同 HEAD 产出（`git_head=be45eb7c7599`、`git_dirty=false`）：编辑器 dist 149.9 MB、构建器 onedir（`build_game.exe` 27.02 MB）、运行时 dist 143.4 MB。
- 冒烟三件分别盖章（`--stamp` 只盖本次真跑过的）：`smoke_passed_at=2026-11-27 13:43:52` > `built_at=2026-11-27 13:27:36`，**7/7 全 PASS**，耗时 7.9s（预算 60s）。读数：models=126、fps 93.0、tps 30.23；构建器 `--help` exit=0；运行时最小启动 exit=1（无游戏包，属预期）。
- 包=代码对拍：`py -3.13 tools/verify_pkg_vs_head.py --version 0.1.0.beta7 <source.zip> <compiled.zip>` **EXIT=0** —— source 包内引擎 .py **226 / HEAD 226**、内容不一致 **0**、包多出 **0**、包缺失 **0**；compiled `git_head` 与 HEAD 相等、`git_dirty=False`。

## 八、发布记录

- tag：`engine-v0.1.0.beta7`；Hub：`hub-v0.1.5`。Release 标记：引擎 **prerelease**、Hub 正式版。
- 发布门：`tools/release_github.py all` 默认先跑全套 `Loom/tests/run_all.py`（本版 179 个文件），非零即中止且零远端写操作。
- 包内 `git_head=be45eb7c7599` 与 tag 之间只隔 tools/docs/tests 的提交（不触 `Loom/` 产品代码），故「包 = 代码」仍成立（与 beta6 补丁版同一处理口径）。

## 九、安装安全提示（通用，不只某一家安全软件）

在 Program Files 安装时，安全软件会提示「修改配置」与「写入 DLL」，属正常安装行为，请允许。
原因：在关键目录写入疑似系统 DLL 是**几乎所有安全软件**都可能拦的操作，不只某一家。
引擎安装根默认跟随 LoomHub 自身安装位置推荐：Hub 在 Program Files（管理员安装）→ 推荐 `C:\Program Files\Loom`；Hub 在用户目录或便携目录 → 推荐 `%LOCALAPPDATA%\Programs\Loom`。

## 十、版本号形态说明（避免误判）

exe 属性页里的 `FileVersion = 0.1.0.7` 是 Windows PE 的**数字形态**（Nuitka 的 `--file-version` 只收最多 4 段纯数字，字母进不去），
beta 号落在第 4 段：beta6 → `0.1.0.6`、beta7 → `0.1.0.7`。
带 beta 字样的是这几处：`Loom/解释器.json` 的 `version = 0.1.0.beta7`、包内 `build_info.json`、产物包名、Release tag。