# Loom 引擎 0.1.0.beta6（内测 / prerelease）

本版是**编译版引擎包**（Nuitka standalone 编辑器 + **onedir 构建器**（`builder\build_game.exe`）+ 编译版播放器运行时），
可直接安装/解压后由 LoomHub 添加为解释器（`kind=exe`）。实测工具链：Python 3.13.15 + Nuitka 4.3.5 + MSVC cl 14.3。

## 一、场景格式 v12 起**单向不兼容**（重要）

**v12 场景单向不兼容：beta6 场景不能用 beta5 打开。**

- beta6 写出的场景是 **SCENE_VERSION=12**，场景 `materials[]` 只写引用、定义在资产库；
  同时写入 `min_engine_version`。
- beta5 引擎没有 v12 解析与版本闸，打开 beta6 场景会**静默丢字段**。
  回退前请用 beta5 重新导出/或保留 beta5 时代的场景副本。
- beta6 打开 beta5 旧场景：自动迁移（旧路径字段可读 + 告警），可正常使用。

## 二、三大目标：T1/T2/T3 均达成（2026-11-13 收尾倒查独立复核）

- **T1 描述层共享** ✅：pass 顺序 / 目标名与格式 / load·clear / depth / raster / 绘制源 / 后处理阶段与参数，全部由 FramePlan 消费；7 类反例矩阵固化在 `tests/test_frame_plan_vk.py`（改 plan → 两端同向，幅度比 1.000）。
- **T2 差异清单化** ✅：`docs/design/T2差异清单_beta6.md` = **4 条不共享（D-01/03/04/05）+ 4 条合理差异（R-01..R-04）+ 1 条实现细节（I-01）**，每条绑定可复跑探针。
- **T3 着色器单源** ✅：一份 GLSL → 13 个 SPIR-V，GL 与 VK 同源；`Loom/` 产品树手写 WGSL 只剩 P1 诊断逃生舱（见 §五）。
- 旧「语义面 11.5 / 未达成」的判据已由版本计划 §9.31 的人类裁决**废除**（不再折算成分数）。

## 三、构建器 P0 已修（两条，都被冒烟 `[6/7]` 守住）

1. **onefile 解包缺原生组件**：构建器缺 `ckernels`/`core_components`，解包到 %TEMP% 后 import 即崩
   （`--help` 也 exit 1），现场表现为"构建器打不开/一闪而过"。
   修复：`build_engine` 的构建器命令补 `--include-data-dir=ckernels/core_components` + `解释器.json`。
2. **T3 后缺 `shaders/`**（`2e69b38` 修复）：T3 把着色器改成**运行时读文件**（`Loom/shaders/*.spv` 等，
   `loom_shaders.py` 在 **import 阶段**就读），但三个构建入口原先都没把 `shaders` 当数据目录带
   → 编辑器 / 构建器 / 运行时**一启动就 FileNotFoundError**。
   修复：`tools/build_engine.py` 的 `DATA_DIRS` 与 `_builder_includes()`、`Loom/build_game.py` 的运行时
   include 全部加 `shaders`，并补自洽断言（dist 必须有 `shaders/` 且至少一个 `.spv`；运行时 `_need` 加 `shaders`）。

## 四、冒烟升级为 7 项 + 门序硬门

- 7 项：启动 / 场景 / 播放 / 读数 / 产物元数据自洽 / 构建器可执行 / 运行时最小启动。
- 门序：**编译 → 冒烟 → 打包 → 包=代码对拍**；`build_info.smoke_passed_at` 必须晚于 `built_at`，
  否则打包拒绝；超预算默认失败（`--allow-slow` 放行）。
- `--stamp` 只给**本次真跑过且通过**的产物盖章（不再"一次冒烟盖三件"）。
- 包装卫生：`.agent_port.json`（含 port/token/pid）、`editor_state.json`、`崩溃日志/`、`*.log`、
  `tests/_tmp/`、`__pycache__/`、`*.pyc`、`*.c.bak` 一律不进包，zip 自检断言 0。

## 五、T3 着色器单源化（beta6 代码目标收口）

- 13 个 SPIR-V（主 pass vs/fs、post 链 4 个、天空、阴影、mip、UI 各一对），GL 与 VK **同源**；
  `Loom/` 产品树手写 WGSL 只剩 P1 诊断逃生舱（`--stage p1`，**14 个非空行**）。
  **豁免前提如实说**：`tests/test_vk_p1_stage.py` 用假设备（只记录调用、**不解析 WGSL**），能证明「管线对象被创建」，但**证明不了那段 WGSL 语法一定正确** —— 真机 p1 路径无测试（已登记）。
- 像素门实测（2026-11-13，本机，`py -3.13 tests/test_ab_gl_vk.py`）：
  **26 场景 / 失败 0 / 跳过 0**（含新增 `ab_world_canvas`），三向 MAE 最大 = GL/参考 **5.7e-5**、VK/参考 **6.6e-5**、GL↔VK **5.3e-5**（均为 `ab_point_shadow`）；
  UI 专项：`ab_ui_scene` **1.10e-4**、新增纯 UI 场景 `ab_ui_only` **2.726e-3**（门限沿用既有 `ui_mae_abs=5e-3`）；
  闸门 `mae_abs=2e-4`、漂移容差 `5e-5`；场景级例外仅 `ab_mip_minify`（VK/参考与 GL/VK 用 `mae_abs=1e-3`，GL/参考仍 2e-4）。
- 13 个 `.spv` 可由 HEAD 源逐字节复现（glslang 16.6.0 + 与 `tools/build_shaders.py` 同一条展开链路，
  重编后 sha256 **13/13 相同**）。

## 六、包 = 代码对拍（本次真跑结果）

`py -3.13 tools/verify_pkg_vs_head.py <source.zip> <compiled.zip>`（exit 0）：

- source 包：包内引擎 `.py` **97 / HEAD 97**，内容不一致 **0**、包多出 **0**、包缺失 **0**
  （CRLF 归一后逐文件 sha256 对拍；`sceneio.py`/`agent_commands.py`/`loom_post.py`/`loom_assets.py` 四个关键文件同判）。
- compiled 包：`build_info.git_head=2e469a603d60` 与 HEAD **相等**（`equal`）、`git_dirty=False`、
  `smoke_passed_at=2026-11-16 23:03:36 > built_at=2026-11-16 22:46:36`。
- 包内元数据：顶层 `0.1.0.beta6` / 嵌套运行时 `0.1.0.beta6` / 目标 `0.1.0.beta6` 三处一致。
- 着色器实到（打开 zip 逐条数，不是看脚本注释）：compiled 包 **81** 条 `/shaders/`（3×27：`Loom/shaders/` + 运行时 dist + 构建器 dist 各 27 = 13 `.spv` + 13 源 + `loom_shader_compat.glsl`），source 包 **54** 条；
  包内 13 个 `.spv` 与 HEAD 逐字节相同（39/39 副本全等）。
- 构建器实到：`Loom/builder/build_game.exe` **平铺**（**没有** `builder/build_game.dist/` 双层），与 `C:\loom_build\builder\build_game.dist\build_game.exe` 逐字节相同；用包内该构建器真跑最小出包 **ExitCode=0**（`_bin_dir()` 解析到包内 `Loom/`，无「找不到引擎数据根」警告）。

## 七、本次交付包（2026-11-16 补丁版重打，替换 2026-11-13 首版资产）

| 产物 | 字节 | 显示大小 | sha256 | git_head |
|---|---|---|---|---|
| `Loom-0.1.0.beta6-compiled.zip` | 145 288 824 | 138.56 MB | `d77d6f4b61b3fd389806058d19b382d927fbc7cfd709303ea0baa87c01136683` | `2e469a603d60` |
| `Loom-0.1.0.beta6-source.zip` | 358 736 794 | 342.12 MB | `285cf20586c6f7c7fe4c3b68d6bef96e72e9f5baf2390094c1b7933c4477f9ea` | `2e469a603d60` |
| `LoomHub-0.1.4-Setup.exe` | 25 546 396 | 24.36 MB | `e84399bb03d0446f55a9abf83b435add5a64609e709a434f27a57540d6899436` | （Hub 无独立 git_head；版本真源 `LoomHub/版本.json`=0.1.4；本次补丁未重打 Hub） |

- 三件同日同 HEAD 产出：编辑器 dist **150.23 MB**、构建器 **onedir 80.08 MB**（`build_game.exe` 26.37 MB）、玩家运行时 dist **143.43 MB**。
- 构建器 2026-11-13 起由 onefile 改 **onedir**：不再自解压到 `%TEMP%`（安全软件的投放器特征），并给三个 exe 补完整版本资源（`CompanyName=lhy302` / `ProductName=Loom` / `FileDescription` / `FileVersion=0.1.0.6`）。实测该形态改变后本机 360 不再对构建器报毒（单机单样本）。
- 冒烟三件分别盖章（`--stamp` 只盖本次真跑过的）：引擎 dist / 构建器 / 运行时 dist 各自 `smoke_passed_at=2026-11-13 20:59:16`；**7/7 全 PASS**，耗时 6.7s（预算 60s）。
  读数：models=126、fps **96–101**、tps **30.12–30.27**；构建器 `--help` exit=0；运行时最小启动 exit=1（无游戏包，属预期）。

## 八、发布记录（2026-11-13 已执行）

- tag：`engine-v0.1.0.beta6`（**2026-11-16 补丁后重新指向 `2e469a6`**；Hub 的 `hub-v0.1.4` 仍指 `74f8535`，本补丁未动 Hub），Release 标记为 **prerelease**
- Release：<https://github.com/lhy302/WeaveEngine/releases/tag/engine-v0.1.0.beta6>
- 资产：`Loom-0.1.0.beta6-compiled.zip`（145 284 153 B）
- 发布门：`tools/release_github.py engine` 默认先跑全套 `run_all`（**139 个**：137 + 本次补丁新增 2 个），非零即中止且零远端写操作（本次 EXIT=0）
- 源码包 `605012b8…`（342.11 MB）未作为 Release 资产上传（源码本身即仓库，与前几版一致）

## 九、安装安全提示（通用，不只某一家安全软件）

在 Program Files 安装时，安全软件会提示「修改配置」与「写入 DLL」，属正常安装行为，请允许。

原因：在关键目录写入疑似系统 DLL 是**几乎所有安全软件**都可能拦的操作，不只某一家。

引擎安装根现在**默认跟随 LoomHub 自身安装位置**推荐：Hub 在 Program Files（管理员安装）→ 推荐
`C:\Program Files\Loom`；Hub 在用户目录或便携目录 → 推荐 `%LOCALAPPDATA%\Programs\Loom`。
用户在安装对话框里仍可快捷切换系统目录/用户目录，或手动输入、浏览选择。

## 十、2026-11-16 补丁版：修掉三个真缺陷（本包替换 11-13 首版资产）

三条都定位到了具体代码行、都补了回归测试，并且**自证过「修前必红」**（把修复临时撤掉后测试确实失败）。

### 1）把场景物体全部隐藏 → VK 后端必崩（B13）

- **现象**：把所有物体设为不可见（或清空场景）后，VK 渲染帧抛 `ValueError`；编辑器里删光所有物体、只留默认灯时 GL 侧也直接崩在「官方件契约违约」。
- **根因（两处 VK + 一处 GL）**：
  - 平行光阴影相机对**空包围盒**求 min/max（`(0,4)` 空数组）；
  - 零实例时仍向 GPU 写**空实例缓冲**（wgpu 拒绝空数据）；
  - GL 侧对空 AABB 行表硬抛 `-2`，而同一个空表在 `scene_bounds` 是「返回 None 可降级」—— 违反 `loom_lighting` 自己声明的「调用失败 → 返 False 回退 Python 路径」。
- **修法**：零可见实例时该灯本帧判为「无阴影 VP」（不拟合空包围盒）；空实例跳过写缓冲；空行表 / 空可见集统一返 `None` 走 Python 路径。
- **回归**：`tests/test_zero_instance_render.py` —— GL/VK × 3 变体（全隐藏 / 空场景有灯 / 空场景无灯）全部不崩；并用「隐藏后画面必须真的变了」自证测试不是空转。

### 2）UI 描边/填充被深度测试吃掉，而且不报错（B14）

- **现象**：Shape 描边画在 3D 场景上时整条消失（实测 480×320 场景 **0 像素**），**全程没有任何报错**。
- **根因**：两个屏幕空间绘制助手的 docstring 写着「不深度测试」，实现里却没关深度；失败还被三层 `except: pass` 吞掉。
- **修法**：`ctx.scope` 内临时关深度（退出自动恢复、保留裁剪盒），失败改为每进程上报一次。
- **实测**：旧路径 **0 像素** → 新路径 **800 像素**；Shape 元素（填充+描边）**73 680 像素**；画完 UI 后重渲染一帧与基线**逐像素一致**（无状态污染）。

### 3）阴影偏移常量散落四处（B11）

- **现象**：GL 与 VK 各写一份 `0.004`，另有两处形参默认值写成 `0.002` —— 一旦有人吃默认值，两端点光阴影偏移立刻不一致（0.002 会大面积自阴影 acne）。
- **修法**：收敛到 `loom_scene_ubo.POINT_BIAS / DIR_BIAS` 单点常量，两端调用与两个默认值全部引用它；数值不变（0.004 / 0.002）。

### 4）顺带修：包=代码对拍的口径

`verify_pkg_vs_head` 的 `Loom/` diff 过滤原先**没有排除** `Loom/tests/`，于是 tag 之后只要新增/修改任何测试文件，对拍就红（本次新增 2 个测试正好触发）。现已与源码包对拍口径统一（排除 `Loom/tests/`、`Loom/player_runtime/`）。

### 本次门序（真跑结果）

| 门 | 结果 |
|---|---|
| 编译 | EXIT=0：编辑器 **150.2 MB** / 构建器 onedir **80.1 MB** / 运行时 **143.4 MB**，三件 `git_head=2e469a6`、`git_dirty=False` |
| 冒烟 | **7/7 PASS**，三件分别盖章 `smoke_passed_at=2026-11-16 23:03:36` |
| 打包 | compiled **138.56 MB** / source **342.12 MB** |
| 对拍 | **EXIT=0**：source 97/97 内容不一致 0；compiled `git_head` 与 HEAD 相等 |
| 像素门 | **26 场景 / 0 失败 / 0 跳过**；**所有 MAE 与修前逐值一致 —— 没有移动任何基线** |
| 回归 | **139 个测试文件 / 0 失败**（137 + 本次新增 2） |
| 二进制卫生 | **3/3 合格**（`FileVersion=0.1.0.6`、公司/产品/描述齐全、构建器为 onedir 形态） |

### 兼容性

场景格式仍是 **v12**，**本补丁不改变任何场景/资产格式**，与 11-13 首版可互相打开。唯一行为变化就是上面三个缺陷：原本会崩 / 会消失的地方，现在正常。
