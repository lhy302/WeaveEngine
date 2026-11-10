# Loom 引擎 0.1.0.beta6（内测 · 草稿）

本版是**编译版引擎包**（Nuitka standalone 编辑器 + onefile 构建器 + 编译版播放器运行时），
可直接安装/解压后由 LoomHub 添加为解释器（`kind=exe`）。当前 Python 3.13.15 + Nuitka 4.3.5 + MSVC 14.44。

## 一、场景格式 v12 起**单向不兼容**（重要）

- beta6 写出的场景是 **SCENE_VERSION=12**，场景 `materials[]` 只写引用、定义在资产库；
  同时写入 `min_engine_version`。
- **beta6 场景不能回退 beta5 打开**：beta5 引擎没有 v12 解析与版本闸，会静默丢字段。
  回退前请用 beta5 重新导出/或保留 beta5 时代的场景副本。
- beta6 打开 beta5 旧场景：自动迁移（旧路径字段可读 + 告警），可正常使用。

## 二、语义面评估：当前 11.5，**未达成**（待人类裁决）

- 语义面（场景→运行时语义一致性）本轮评估为 **11.5**，未达到发布门槛。
- 处置方式（计入 beta6 / 推迟 beta7 / 限定范围发布）**待人类裁决**；本包按"契约与工具链优先"先行。

## 三、构建器 P0 已修

- 症状：onefile 构建器缺 `ckernels`/`core_components`，解包到 %TEMP% 后 import 即崩（`--help` 也 exit 1），
  现场表现为"构建器打不开/一闪而过"。
- 修复：`build_engine` 的构建器命令补 `--include-data-dir=ckernels/core_components` + `解释器.json`；
  冒烟 `[6/7]` 直接跑 `build_game.exe --help` 防回归。

## 四、冒烟升级为 7 项 + 门序硬门

- 7 项：启动 / 场景 / 播放 / 读数 / 产物元数据自洽 / 构建器可执行 / 运行时最小启动。
- 门序：**编译 → 冒烟 → 打包 → 包=代码对拍**；`build_info.smoke_passed_at` 必须晚于 `built_at`，
  否则打包拒绝；超预算默认失败（`--allow-slow` 放行）。
- `--stamp` 只给**本次真跑过且通过**的产物盖章（不再"一次冒烟盖三件"）。

## 五、包 = 代码对拍（交付证据）

- `tools/verify_pkg_vs_head.py <source.zip> <compiled.zip>`：
  - source 包：`Loom/**.py`（排除 tests/ 与 player_runtime/）与 HEAD **双向**对拍（数量/缺失/多出/内容，CRLF 归一）；
  - compiled 包：`build_info.git_head` 必须是 HEAD 祖先，且 HEAD 相对它在 `Loom/` **零 diff**；`git_dirty=false`。
- 打包卫生：`.agent_port.json`（含 port/token/pid）、`editor_state.json`、`崩溃日志/`、`*.log`、`tests/_tmp/`、
  `__pycache__/`、`*.pyc`、`*.c.bak` 一律不进包，zip 自检断言 0。

## 六、发布命令（**未执行**，等人类裁决后统一跑）

```bat
set LOOM_ENGINE_VERSION=0.1.0.beta6
py -3.13 tools/release_github.py engine
```
