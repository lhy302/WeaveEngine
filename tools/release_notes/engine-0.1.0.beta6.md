# Loom 引擎 0.1.0.beta6（内测 · 草稿）

本版是**编译版引擎包**（Nuitka standalone 编辑器 + onefile 构建器 + 编译版播放器运行时），
可直接安装/解压后由 LoomHub 添加为解释器（`kind=exe`）。实测工具链：Python 3.13.15 + Nuitka 4.3.5 + MSVC cl 14.3。

## 一、场景格式 v12 起**单向不兼容**（重要）

**v12 场景单向不兼容：beta6 场景不能用 beta5 打开。**

- beta6 写出的场景是 **SCENE_VERSION=12**，场景 `materials[]` 只写引用、定义在资产库；
  同时写入 `min_engine_version`。
- beta5 引擎没有 v12 解析与版本闸，打开 beta6 场景会**静默丢字段**。
  回退前请用 beta5 重新导出/或保留 beta5 时代的场景副本。
- beta6 打开 beta5 旧场景：自动迁移（旧路径字段可读 + 告警），可正常使用。

## 二、语义面评估：当前 11.5，**未达成**（待人类裁决）

- 语义面（场景→运行时语义一致性）本轮评估为 **11.5**，未达到发布门槛。
- 处置方式（计入 beta6 / 推迟 beta7 / 限定范围发布）**待人类裁决**；本包按"契约与工具链优先"先行。

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
  全仓手写 WGSL 只剩 P1 诊断逃生舱 **16 行**（按 A1-8 裁决豁免，且已有假设备管线测试兜住）。
- 像素门实测（2026-11-13，本机，`py -3.13 tests/test_ab_gl_vk.py`）：
  **23 场景 / 失败 0 / 跳过 0**，三向 MAE 最大 = GL/参考 **5.7e-5**、VK/参考 **6.6e-5**、GL↔VK **5.3e-5**；
  UI 专项 MAE **1.10e-4**（等于基线 1.10e-4）；闸门 `mae_abs=2e-4`、漂移容差 `5e-5`。
- 13 个 `.spv` 可由 HEAD 源逐字节复现（glslang 16.6.0 + 与 `tools/build_shaders.py` 同一条展开链路，
  重编后 sha256 **13/13 相同**）。

## 六、包 = 代码对拍（本次真跑结果）

`py -3.13 tools/verify_pkg_vs_head.py <source.zip> <compiled.zip>`（exit 0）：

- source 包：包内引擎 `.py` **96 / HEAD 96**，内容不一致 **0**、包多出 **0**、包缺失 **0**
  （CRLF 归一后逐文件 sha256 对拍；`sceneio.py`/`agent_commands.py`/`loom_post.py`/`loom_assets.py` 四个关键文件同判）。
- compiled 包：`build_info.git_head=2e69b38…` 与 HEAD **相等**（`equal`）、`git_dirty=False`、
  `smoke_passed_at=2026-11-13 14:38:22 > built_at=2026-11-13 14:17:49`。
- 包内元数据：顶层 `0.1.0.beta6` / 嵌套运行时 `0.1.0.beta6` / 目标 `0.1.0.beta6` 三处一致。
- 着色器实到（打开 zip 逐条数，不是看脚本注释）：两个包各 **54** 条 `/shaders/` 条目 =
  `Loom/shaders/` **27**（13 `.spv` + 13 源 + `loom_shader_compat.glsl`）+ 运行时
  `Loom/player_runtime/game_player.dist/shaders/` **27**（同样 13 `.spv`）。

## 七、本次交付包（2026-11-13 重打，替换 `153c7896` 的旧包）

| 产物 | 字节 | 显示大小 | sha256 | git_head |
|---|---|---|---|---|
| `Loom-0.1.0.beta6-compiled.zip` | 139 227 547 | 132.78 MB | `3df4813f7d5a99268b4d676d8fb8da9fd7810e5eb38e3538bc86c15dcc36b803` | `2e69b38110b8a42f156a1094928e440477ac407e` |
| `Loom-0.1.0.beta6-source.zip` | 358 713 934 | 342.10 MB | `037ca8d922628c082002e88936b54aa1ad0c851497e77e0dc543815673c177d2` | `2e69b38110b8a42f156a1094928e440477ac407e` |
| `LoomHub-0.1.4-Setup.exe` | 27 363 292 | 26.10 MB | `ac75dccfb37b9550e99d2cceb733b26dba4bdc920cddbd535c352101f8b26682` | `2e69b38110b8a42f156a1094928e440477ac407e` |

- 三件同日同 HEAD 产出：编辑器 dist **150.2 MB**、构建器 onefile **23.5 MB**、玩家运行时 dist **143.4 MB**。
- 冒烟三件分别盖章（`--stamp` 只盖本次真跑过的）：引擎 dist / 构建器 / 运行时 dist 各自
  `smoke_passed_at=2026-11-13 14:38:22`；三次冒烟耗时 6.1s / 6.9s / 8.0s（预算 60s）。
  读数：models=126、fps **96–101**、tps **30.12–30.27**；构建器 `--help` exit=0；运行时最小启动 exit=1（无游戏包，属预期）。

## 八、发布命令（**未执行**，等人类裁决后统一跑）

```bat
set LOOM_ENGINE_VERSION=0.1.0.beta6
py -3.13 tools/release_github.py engine
```
