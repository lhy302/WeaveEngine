# research_beta6_06 · 工具链升级调研（Nuitka / MSVC / 依赖整链）

> 调研日期 2026-11-09 · 只读调研 + 隔离试验（`C:\loom_build\toolchain_probe\`），未改任何受跟踪文件
> 关联：`research_beta6_05_python_upgrade.md`（Python 3.13/3.14 结论）、`版本计划_Loom0.1.0.beta6_20261109.md`
> 实测环境：**Python 3.12.10 + 隔离 venv（`--system-site-packages`）**；仓库 `git status` 仅剩调研前就存在的 2 个未跟踪项

## 0. 三行结论

1. **Nuitka 2.7.1 → 4.3.5 可升，但不能"只换版本号"**：三个必须处理的坑——`--windows-disable-console` → `--windows-console-mode=disable`（2.7.1 就已弃用）、`--standalone` → `--mode=standalone`（2.8 起从 help 移除）、**编辑器构建必须显式 `--enable-plugin=pyside6`**（实测 2.7.1 与 4.3.5 **都不自动启用**：发现 `PySide6.QtCore` 只告警；不给 flag 时 dist 里没有 `qwindows.dll`，`Loom.exe` 起不来。旧编辑器产物是带 flag 打的，但《使用操作指南》§7.5 的命令没写——这是既有文档陷阱）。本机实测：最小 standalone 65.8s 通过；`game_player` standalone 532.8s / 140.9MB，同命令 2.7.1 为 369.5s / 139.2MB → **构建慢 44%，体积 +1.2%**。
2. **MSVC 14.44 就是 VS2022 的最新工具集（17.14，EOL 2032-01-13）**；更新的产品线是 **VS2026（18.11.3, 2026-10-29）** 的 MSVC **14.50 LTS / 14.51 / 14.52 preview**。VS2026 只有 **Nuitka ≥ 2.8.7** 捆绑的 SCons 才认 → **换 VS2026 必须与 Nuitka 升级捆绑**；只升 Nuitka 则 MSVC 可以原地不动（14.44 继续用）。
3. **依赖整链在 3.12 与 3.13 都有 wheel**：numpy 2.5.4 / moderngl 5.13.0 / PySide6 6.12.0 / wgpu 0.33.0 / pygame 2.6.1 / glfw 2.11.0 / pillow 13.0.0；3.14 仍只被 pygame 卡住（无 cp314 wheel）。**顺序**：Nuitka（现在、独立）→ 依赖（3.12 上、独立）→ Python 3.13（等 05 判定门）→ VS2026（最后、可选）。

---

## ① 现状（证据）

### 1.1 事实底账（本机实测，2026-11-09）

| 项 | 现值 | 证据 |
|---|---|---|
| Python | 3.12.10 (`MSC v.1943`) | `python --version` |
| Nuitka | **2.7.1**（2025-05-08） | `python -m nuitka --version` |
| 构建用 MSVC | **14.44.35207**，Nuitka 报 `cl 14.3` | VS2022 17.14.37516.0（July 2026），`vswhere` |
| 其他 Python | 3.9/3.10/3.11/3.13/3.14（3.14 里已装 Nuitka **4.3.5**） | `py -0p` |
| 依赖 | numpy 2.2.5 / moderngl 5.12.0 / PySide6 6.11.1 / wgpu 0.32.0 / pygame 2.6.1 / glfw 2.10.2 / pillow 13.0.0 / zstandard 0.23.0 | `pip list` |
| 现有玩家运行时 | `Loom/player_runtime/game_player.dist` **139.2MB / 118 files**（2026-11-09 15:25） | `Measure-Object` |
| 现有编辑器产物 | `C:\loom_build\engine\build_entry.dist` **140.1MB / 134 files**，Qt 插件在 `PySide6/qt-plugins/platforms/qwindows.dll` | 目录清点 |
| 现有构建器产物 | `C:\loom_build\builder\build_game.exe` **22.96MB**（onefile） | 文件大小 |
| 测试面 | 123 个 `Loom/tests/test_*.py`（历史口径"121 个"= 稳定集合）；非 pytest，脚本式 + `FAIL` 闸门 | `research_beta6_01` §R9 |

### 1.2 Nuitka 版本谱（PyPI JSON，2026-11-09）

| 版本 | 发布日 | 与本项目相关的关键变化（官方 changelog） |
|---|---|---|
| 2.7.1（现） | 2025-05-08 | 当前 pin；Windows onefile 默认 DLL 模式 |
| 2.8 | 2025-10-11 | 编译模式选项从 help 移除（以 `--mode=` 为准）；MSVC 运行时 DLL 默认进 standalone；拒绝 Windows 版 CPython 3.13.4；anti-bloat `global_change_function`；`--recompile-extension-modules` |
| 2.8.7 | 2025-12 | **捆绑 SCons 支持 Visual Studio 2026**（4.0 changelog 注明 "Added in 2.8.7 already"） |
| 4.0 | 2026-02-05 | 规模化重构；`--project`；`--nofollow-import-to` **开始对 stdlib 生效**（行为变化）；`--include-windows-runtime-dlls`（默认 auto）；MSVC 信息缓存；onefile `--onefile-child-grace-time=infinity`；**不再默认安装 zstandard** |
| 4.1 | 2026-05-11 | Windows `--windows-console-mode=attach` 改进；编译报告含 ccache/clcache 统计；MSVC 不可用时回退 Zig |
| 4.2 | 2026-08-27 | **Python 3.14 正式支持**；Windows NSIS / Linux AppImage 安装器（`--windows-create-installer`）；新式 code object 默认（生成代码量下降） |
| 4.3 | 2026-10-10 | Python 3.15 实验支持；3.13 frame locals proxy（实验） |
| **4.3.5**（最新） | 2026-11-08 | hotfix；本机 3.14 环境已装 |

来源：<https://nuitka.net/changelog/Changelog.html>（2026-11-09 抓取，全文 18,292 行）、<https://pypi.org/pypi/nuitka/json>。

### 1.3 CLI 兼容性实测（`--help` 逐项 + 真编译）

| 选项 | 2.7.1 | 4.3.5 | 结论 |
|---|---|---|---|
| `--windows-disable-console` | 可用但**告警**："The old console option '--disable-console' should not be given anymore, use '--windows-console-mode=disable' instead" | 同左（仍可用） | **必须改** `--windows-console-mode=disable`（未来会删） |
| `--windows-console-mode` | 有 | 有（新增 `attach` 语义改进） | 目标写法 |
| `--standalone` / `--onefile` | 有（help 中） | **help 已移除**，仍可解析 | 改 `--mode=standalone` / `--mode=onefile` |
| `--enable-plugin=pyside6` | 有，**不自动启用**（实测：只告警） | 有，**同样不自动启用**（`--plugin-list`：`pyside6 ... [has detector]` 只是探测器） | **编辑器构建必须显式加**（见 1.6） |
| `--include-package=…` | 有 | 有 | 不变 |
| `--include-package-data=…` | 有 | 有（4.0 起数据文件追踪更严，onefile 下不再告警） | 不变；`wgpu_native` 仍会 WARNING "Failed to locate package directory"（两版相同，属噪声） |
| `--nofollow-import-to` | 有（仅包） | 有，**且对 stdlib 生效**（4.0） | 仓库仅 `tests/_tmp` 用 `--nofollow-import-to=numba`，无风险 |
| `--msvc=latest` | 有 | 有（4.3.5 实测解析到 14.3） | 不变 |
| `--onefile-tempdir-spec` / `--onefile-no-dll` / `--onefile-no-compression` | 有 | 有（另有 `--onefile-cache-mode`、`--onefile-as-archive`） | 不变 |
| clcache | 内置（2.7 changelog） | 内置，编译报告出命中率 | 两版都会用 clcache |

### 1.4 实测 A：最小 standalone（验证 MSVC 检测）

```
C:\loom_build\toolchain_probe\venv312\Scripts\python.exe -m nuitka --standalone --msvc=latest \
  --assume-yes-for-downloads --windows-disable-console --output-filename=hello435.exe hello_probe.py
→ Nuitka-Scons: MSVC version resolved to 14.3.
→ Nuitka-Scons: Backend C compiler: cl (cl 14.3).
→ Compiled 6 C files using clcache with 0 cache hits and 6 cache misses.
→ EXIT=0 SECONDS=65.8   DIST_MB=12.31 FILES=6   运行输出: probe-ok 3.12.10
```

结论：**4.3.5 在 3.12.10 + MSVC 14.44 上开箱可用**，`--system-site-packages` 隔离 venv 不污染主环境。

### 1.5 实测 B：`game_player` 全量 standalone（同一条 build_game 命令，2.7.1 vs 4.3.5）

命令（与 `Loom/build_game.py:135-143` 等价，产物写 `C:\loom_build\toolchain_probe\runtime{271,435}`）：

```
python -m nuitka --standalone --msvc=latest --assume-yes-for-downloads --enable-plugin=tk-inter \
  --include-package-data=wgpu --include-package-data=wgpu_native --windows-disable-console \
  --output-filename=MyGame.exe --include-data-files=<wgpu.dll>=wgpu/resources/wgpu_native-release.dll \
  Loom\game_player.py
```

| 指标 | 2.7.1 | 4.3.5 | 变化 |
|---|---|---|---|
| 构建耗时 | **369.5 s**（6m10s） | **532.8 s**（8m53s） | **+44.2%** |
| dist 体积 | 139.2 MB | 140.9 MB | +1.7MB（+1.2%） |
| 文件数 | 118 | 125 | +7 |
| C 文件数 | clcache 全 miss | **292** | — |
| 运行冒烟 | — | `MyGame.exe` 启动 → pygame 2.6.1 横幅 → "缺少游戏包: 请把 游戏包.lsc 放到 exe 同目录" | 通过（exe 能起、依赖能加载、按预期报缺包） |

**布局差异（会影响打包脚本/排障）**：2.7.1 把 pygame 的 8 个 DLL 平铺在 dist 根；4.3.5 把它们（15 个，含 libjpeg/libwebp/libopus 等）放进 **`pygame/` 子目录**。`build_game.py`/打包脚本都是整目录递归拷贝 → 功能上无碍；但任何"只拷根目录文件"的脚本会漏 DLL。另 4.3.5 输出的 VC 运行时（msvcp140 等）来自本机 14.44，比 2.7.1 记录的旧版本新。

### 1.6 实测 C：编辑器 `Loom.exe`（PySide6 插件收集）

| 构建 | 命令 | 耗时 | 体积 / 文件 | Qt 插件 |
|---|---|---|---|---|
| 2.7.1 既有产物（`C:\loom_build\engine\build_entry.dist`） | 文档命令 **+ `--enable-plugin=pyside6`**（由 dist 含 qt-plugins 反推） | 未记录 | 140.1 MB / 134 | `qwindows.dll` ✅，另有 imageformats/styles/tls/iconengines、`qt6pdf.dll`/`qt6svg.dll` |
| **4.3.5** | `--standalone --msvc=latest --windows-console-mode=disable build_entry.py`（即《使用操作指南》§7.5 原命令，**无**插件 flag） | **448.1 s**（7m28s） | **132.2 MB / 120** | **无 `qt-plugins`、无 `qwindows.dll`** |
| 2.7.1 对照实验 | 同一"无插件"写法，最小 PySide6 程序 | 39.3 s | — | **无 `qwindows.dll`**（并打印同一条 "Use '--enable-plugin=pyside6'" 告警） |

**结论（关键）**：
1. **pyside6 插件在两版里都是 opt-in**，不存在"4.x 变严格"这回事；差异来自**旧编辑器产物带 flag、文档命令漏写**。
2. 不带 flag 时 4.3.5 的 `Loom.exe` 会因缺 Qt 平台插件**启动即失败**（"could not find or load the Qt platform plugin windows"），而且 dist **反而小 7.9MB** → **体积检查会误判"变好了"**，必须用"文件存在"断言而不是体积断言。
3. 4.3.5 编辑器构建**耗时 448.1s**（255 C 文件）；2.7.1 无同口径计时，不能算"变慢/变快"，但同机 player 全量对比是 +44%（§1.5）。

### 1.7 实测 D：onefile 构建器 `build_game.py`（2.7.1 既有产物 vs 4.3.5 重打）

4.3.5 命令：`--mode=onefile --msvc=latest --assume-yes-for-downloads --windows-console-mode=disable build_game.py`

| 指标 | 2.7.1（`C:\loom_build\builder\build_game.exe`，15:25） | **4.3.5**（`C:\loom_build\toolchain_probe\builder435`） | 变化 |
|---|---|---|---|
| 构建耗时 | 未记录 | **252.7 s**（4m13s） | — |
| exe 体积 | 22.96 MB | **22.67 MB** | **−1.3%** |
| payload | — | 91.78 MB → **23.55 MB**（"Using compression for onefile payload"） | — |
| clcache | — | 260 C 文件：**254 命中 / 6 miss**（复用 §1.6 的缓存） | — |
| 启动耗时（`--help`，3 次中位数） | **1.87 s**（3.78 / 1.87 / 1.74） | **2.05 s**（16.2 / 2.05 / 2.03） | **+0.18 s（≈+10%）** |

**结论**：onefile 体积略降、稳态启动 +0.18s（正好卡在 G6 的 +10% 边界）；**首跑 16.2s 是杀毒扫描新 exe 的一次性成本** → 发布前必须预热/加白，否则用户首启会以为"没反应"（R10 的早期信号就长这样）。onefile 走默认 DLL 模式，未用 `--onefile-no-dll`。

### 1.8 MSVC 产品线（官方版本表）

| VS 版本 | MSVC | 状态 / EOL |
|---|---|---|
| VS2022 17.13 | 14.43 | 已 EOL |
| **VS2022 17.14（本机）** | **14.44** | 支持到 **2032-01-13**（LTSC 线） |
| VS2026 18.0+ | **14.50** | 长期支持（LTS），EOL 2028-11 |
| VS2026 | 14.51 | 标准支持，EOL 2027-02 |
| VS2026 | 14.52 | **preview**（GA 后定 EOL） |

来源：<https://learn.microsoft.com/en-us/cpp/overview/compiler-versions>（2026-11-09）；VS2026 最新更新 18.11.3（2026-10-29）：<https://learn.microsoft.com/en-us/visualstudio/releases/vs18/release-notes>。

**ABI**：<https://learn.microsoft.com/en-us/cpp/windows/latest-supported-vc-redist> 明确 "Any apps built by MSVC Build Tools v14.* available in Visual Studio 2017, 2019, 2022, or 2026 can use the latest Visual C++ v14 Redistributable" → 14.5x 与 14.4x **同一 v14 ABI**，预编译 wheel（numpy/PySide6）不需重编；风险只在 CRT DLL 分发与 Nuitka 运行时 DLL 收集。

### 1.9 依赖 × 最新 stable × wheel 矩阵（PyPI，2026-11-09）

| 依赖 | 现值 | 最新 stable（日期） | requires_python | 3.12 wheel | 3.13 wheel | 3.14 wheel |
|---|---|---|---|---|---|---|
| numpy | 2.2.5 | **2.5.4**（2026-10-10） | >=3.12 | cp312 ✅ | cp313 ✅ | cp314 ✅ |
| moderngl | 5.12.0 | **5.13.0**（2026-10-07） | >=3.7 | cp312 ✅ | cp313 ✅ | cp314 ✅ |
| PySide6 | 6.11.1 | **6.12.0**（2026-10-08）；保守替代 6.11.3（2026-10-26） | <3.16,>=3.10 | cp310-abi3 ✅ | abi3 ✅ | abi3（未实测） |
| wgpu | 0.32.0 | **0.33.0**（2026-11-06，仅 3 天） | >=3.11 | py3-none-win_amd64 ✅ | ✅ | ✅（纯 py + 自带 dll） |
| pygame | 2.6.1 | 2.6.1（**2024-09-29 后未再发版**） | >=3.6 | cp312 ✅ | cp313 ✅ | **无 cp314 ❌** |
| glfw | 2.10.2 | **2.11.0**（2026-10-16） | — | py2.py3-none ✅ | ✅ | ✅ |
| pillow | 13.0.0 | 13.0.0（2026-10-16，已最新） | >=3.11 | cp312 ✅ | cp313 ✅ | cp314 ✅ |
| zstandard | 0.23.0 | 0.25.0（2025-09-14） | >=3.9 | cp312 ✅ | cp313 ✅ | cp314 ✅ |

**3.12 / 3.13 两套可用版本矩阵（结论）**：
- **3.12**：上表全部最新版可直接装（numpy 2.5.4 要求 >=3.12，正好卡边界）。
- **3.13**：同样全部可装；与 `research_beta6_05` 的 `--dry-run` 一致（05 当时解析到 numpy 2.2.6 / moderngl 5.12.0 / wgpu 0.33.0，因为 2.5.4 尚未发布——**本轮更新后 3.13 应解析到 numpy 2.5.4 / moderngl 5.13.0**）。
- **3.14**：唯一硬阻塞仍是 **pygame 无 cp314 wheel**（与 05 结论一致）；PySide6 6.12 的 `<3.16` 不构成阻塞。

### 1.10 逐项 breaking changes（只列与本项目实际调用相关的）

**wgpu 0.32 → 0.33**（来源：wgpu-py `CHANGELOG.md` main "unreleased" 段，2026-11-09 抓取）
- wgpu-native 升到 29：`push-constants` → `immediates` 改名（feat/limit 同步改名）；`extras.set_push_constants` → `encoder.set_immediates`。**Loom 零命中**（`push_constant|immediates` 全仓 0 处）。
- `context.get_current_texture()` 现在可能抛 `wgpu.DrawCancelled`（窗口被遮挡/无可用纹理）。Loom 已在 `Loom/vk_renderer.py:2003-2010` 用 `except Exception` 包住并计入 `PresentHealth` 失败 → **语义已兼容**。
- 本机 API surface 实测（`api_dump.py`，0.32.0 vs 0.33.0）：模块级与 `GPUDevice/GPUQueue/GPUTexture/GPUCanvasContext/DrawCancelled` 属性**完全一致**，无删除。
- 风险级别：**低**；但 0.33.0 发布仅 3 天，建议排在依赖升级最后，并跑 `ab_gl_vk` + 真实窗口上屏。

**moderngl 5.12 → 5.13**（来源：<https://api.github.com/repos/moderngl/moderngl/contents/CHANGELOG.md>，2026-11-09）
- 5.13.0 条目写 "to be added later"（**无成文 breaking**）；main 段列出一批**内存/生命周期修复**：Context 在派生对象存活期间保持分配、已释放 Context 的 framebuffer/scope 现在抛 `moderngl.Error`、新增 `Query.release()`、修 `Sampler.release()` use-after-free、修各类构造器泄漏。
- API surface 实测：`Context/Texture/Framebuffer/VertexArray/Buffer` 完全一致；`Program` 新增 `draw_mesh_tasks*`（网格着色器，**纯增量**）。
- **本项目敏感点**：GL 后端大量 `.release()`（`engine.py:769`、`frame_buffer.py:318-330`、`loom_texture.py:162/228`、`loom_render.py:261-263`、`loom_shadow.py:39-41`、`loom_cubemap.py:190/229`…），且有"换上下文→释放旧纹理→重建"与离屏回退路径 → **必须实跑 GL 后端 + 离屏回退 A/B**。

**PySide6 6.11.1 → 6.12.0**（Qt 6.12.0 于 **2026-09-30** 发布，LTS：<https://wiki.qt.io/Qt_6.12_Release>；PySide6 6.12.0 PyPI 2026-10-08）
- `QOpenGLWidget` 在 Qt 6.12 文档中仍存在、无弃用声明：<https://doc.qt.io/qt-6/qopenglwidget.html>（2026-11-09）。
- 但 Qt 6.12 是 LTS，OpenGL/RHI 行为与平台插件随驱动/版本变化 → QOpenGLWidget 离屏回退与 `QT_QPA_PLATFORM=offscreen` 都要实测。
- 保守路线：先升 **6.11.3**（6.11 线最后补丁，2026-10-26），A/B 全绿后再上 6.12.0。
- Nuitka 侧：PySide6 ≥6.10 会额外收集 `QtPrintSupport`（`PySidePyQtPlugin.py:702`）→ **插件必须启用**。

**numpy 2.2.5 → 2.5.4**（numpy 2.4.0 / 2.5.0 release notes）
- 2.4 移除：`np.trapz`、`corrcoef(bias/ddof)`、`array2string(style=)`、`np.sum(generator)` 改 TypeError、`round` 恒返回拷贝。
- 2.5 移除：`numpy.distutils`、`np.row_stack`、`np.chararray`、**2 维 `np.cross`**、`bincount` 非整数 TypeError、`linalg.eig` 恒返回复数；构建要求 MSVC ≥19.35（wheel 用户无感）。
- 本机 grep：`np.cross` 仅 3D 用法（`editor.py:433/435`、`loom_model_gpu.py:144`、`vk_renderer.py:555`），未用其它被删 API → **兼容风险低**，但需全量测试 + bench（ufunc/内存布局可能有性能位移）。

**anti-bloat 行为**（2.7.1 → 4.3.5）
- 2.8：新增 `global_change_function`（整包统一替换函数）与 `--recompile-extension-modules`。
- 4.0/4.1/4.3：大量包级修正（sqlalchemy 编译内存膨胀、**numpy 不再连带 `typing_extensions`**、PySimpleGUI 不拉 `pydoc`、pyparsing.testing 排除…），方向是"自动排除无用模块"更积极。
- 对本项目的可见影响：构建日志会打印 `Not including 'cv2' automatically in order to avoid bloat`（两版都有）；4.x 不会因此少带 Loom 需要的东西，但**新增依赖**时可能出现"被 anti-bloat 自动排除"的意外，要看 WARNING。
- 覆盖手段：`--include-package` / `--noinclude-custom-mode` 可强制带回（`--nofollow-import-to` 在 4.0 起也作用于 stdlib，慎用）。

**pygame 2.6.1**：两年未发新版；cp313 有 wheel、cp314 无 → 3.14 不可行（05 已判）。
**glfw 2.10.2 → 2.11.0**：wheel 为 `py2.py3-none-win_amd64`（无 Python ABI 绑定），窗口/上下文 API 稳定；变更点是随附 GLFW DLL 版本 → 真实窗口测试必跑。
**pillow 13.0.0**：已最新，无需动。

---

## ② 目标（升级目标态）

### 2.1 目标矩阵（3.12 主线）

| 组件 | 目标 | 备注 |
|---|---|---|
| Python | 3.12.10（不动） | 3.13 走 05 的隔离预研分支 |
| Nuitka | **4.3.5** | `--mode=*` + `--windows-console-mode=disable` + 编辑器 `--enable-plugin=pyside6` |
| MSVC | **14.44（不动）** | 控制变量；VS2026 另立项 |
| numpy | 2.5.4 | 与 3.13 兼容 |
| moderngl | 5.13.0 | GL 后端 A/B |
| PySide6 | 6.12.0（回退位 6.11.3） | Qt 6.12 LTS |
| wgpu | 0.33.0（回退位 0.32.0） | 最后升 |
| pygame | 2.6.1（不动） | 无新版 |
| glfw | 2.11.0 | 真实窗口验证 |
| pillow | 13.0.0（不动） | — |

### 2.2 不做的事（显式边界）
- 不升 Python 3.14（pygame 卡死）；不启用 free-threading（05 已判不可行）。
- 不在本轮升 VS2026：收益（新工具集）< 风险（SCons 兼容、CRT 分发、CI 未知）。
- 不改动 onefile 的"默认 DLL 模式"（2.7 起默认，4.3.x 官方称 "finally perfect"）；如遇异常，回退开关 `--onefile-no-dll`。

### 2.3 判定门（硬条件，任一不过就不合入）
- **G1**：最小 standalone 编译通过且产物可运行（已验证 4.3.5 ✅）。
- **G2**：`game_player` standalone + `--build-runtime` 全链路通过，dist 能启动到"缺游戏包"提示（已验证 4.3.5 ✅）。
- **G3**：编辑器 `Loom.exe` 能起（dist 内 `PySide6/qt-plugins/platforms/qwindows.dll` 存在），`QT_QPA_PLATFORM=offscreen` 下 `--bench` 可跑。
- **G4**：121 个 `test_*.py` 全绿（GL/Vulkan 用例按既有 skip 规则）。
- **G5**：`ab_gl_vk` 逐像素 diff 不劣化（阈值同既有验收口径）；`bench` 帧时间不退化 >5%。
- **G6**：包体积 ≤ +5%，启动时间 ≤ +10%。

---

## ③ 分步计划（每步可独立验收、可回滚）

### Step 0（0.5 人天）冻结基线
- 动作：`pip freeze > C:\loom_build\baseline-3.12-freeze.txt`；用 2.7.1 复跑三件产物（本轮已做 player：369.5s/139.2MB）；跑 121 测试存基线；记录 `bench` 与启动时间。
- 验收：基线四件套（耗时/体积/测试绿/帧时间）落盘。
- 回滚：无（只读）。

### Step 1（1 人天）Nuitka 4.3.5 + 参数现代化（**不依赖任何其它升级**）
1. 建隔离 venv：`py -3.12 -m venv C:\loom_build\nuitka435 --system-site-packages`；`pip install "nuitka[onefile]==4.3.5"`（4.x 不再默认装 zstandard）。
2. 改 `Loom/build_game.py`：`--standalone` → `--mode=standalone`；`--windows-disable-console` → `--windows-console-mode=disable`；处理 `--include-package-data=wgpu_native` 的无效警告（该包不存在，保留 wgpu 即可）。
3. 编辑器构建命令补 `--enable-plugin=pyside6`（见 1.6），并把"dist 内 `PySide6/qt-plugins/platforms/qwindows.dll` 存在"写成构建后断言。
4. 三件重打 + 冒烟。
- 验收：G1/G2/G3；体积/耗时对比表更新。
- 回滚：还原 `build_game.py` 两行 + 主环境 2.7.1 重打（旧 dist 保留即可秒回）。

### Step 2（1.5 人天）依赖升级（仍在 3.12）
顺序（风险从低到高）：pillow(不动) → glfw 2.11.0 → numpy 2.5.4 → moderngl 5.13.0 → PySide6 6.11.3 → PySide6 6.12.0 → wgpu 0.33.0。
每升一项：相关测试文件 + 全量 121 + 一次 `ab_gl_vk` + 一次 `bench`；记体积/启动。
- 验收：G4/G5/G6。
- 回滚：`pip install <旧版本>`（wheel 全在 PyPI，无需源码编译）+ requirements 回滚。

### Step 3（2~3 人天）Python 3.13（依赖 05 报告的门禁）
- 仅在 05 的 G1-G4 通过后执行；先复制 3.12 依赖矩阵到 3.13（本轮矩阵已证明全可解析）。
- 关键耦合：3.13 下 Nuitka 必须 ≥4.0（4.3.5 ✅）；**3.13.4 被 Nuitka 明确拒绝**（2.8 changelog），选 3.13.5+。
- 回滚：3.12 环境原样保留，`解释器.json` 指回。

### Step 4（1 人天，可选）VS2026 / MSVC 14.5x
- 前置：Nuitka ≥4.3.5（SCons 认 VS2026）+ 三件产物在 14.44 已全绿。
- 装 VS2026 Build Tools（与 VS2022 并存），`--msvc=latest` 验证解析到 14.5x；跑 G1-G3 + 冒烟；确认 `--include-windows-runtime-dlls` 带的是 14.5x CRT。
- 回滚：切回 `--msvc=14.44` 或卸载 VS2026。

---

## ④ 风险与回滚

| # | 风险 | 早期信号 | 缓解 | 回滚 |
|---|---|---|---|---|
| R1 | 4.3.5 构建慢 44%（实测） | CI 时长、开发等待 | 保留 clcache；只在发布机全量重打；日常用 2.7.1 快速迭代 | 换回 2.7.1 venv（并存不冲突） |
| R2 | **Qt 平台插件没进 dist**（两版都 opt-in；4.3.5 实测无 flag=无插件） | `Loom.exe` 报 "could not find or load the Qt platform plugin windows"；dist 无 `PySide6/qt-plugins/platforms/qwindows.dll`，且体积异常小 7.9MB | 显式 `--enable-plugin=pyside6`；构建后断言该文件存在 | 用旧 dist / 补插件重打 |
| R3 | PySide6 6.12 的 QOpenGLWidget/离屏回退行为变化 | 离屏回退触发率上升、`QT_QPA_PLATFORM=offscreen` 报错、画面黑 | 先 6.11.3；A/B + 真实窗口双跑；`ab_gl_vk` 逐像素 | `pip install PySide6==6.11.1` |
| R4 | moderngl 5.13 生命周期语义（release/已释放 Context） | 换上下文后 `moderngl.Error`、GL 资源泄漏或崩溃 | 重点跑 GL 上下文切换/离屏回退；必要时延迟 5.13 | 回 5.12.0 |
| R5 | wgpu 0.33 太新（发布 3 天） | 上屏失败/黑帧、`DrawCancelled` 计数飙升 | 0.32.0 作为默认，0.33 单列预研；`PresentHealth` 监控 | 回 0.32.0 |
| R6 | pygame DLL 位置变化（根 → `pygame/`） | 打包后缺 SDL2.dll、音频/字体失效 | 打包脚本整目录递归（现状即是）+ 发布包清单校验 | 回退版本即回退布局 |
| R7 | Nuitka 缓存/临时目录污染 | 编译报错指向 `%TEMP%\onefile_*`、构建目录残留 | 构建前清 `--output-dir`；onefile 用 `--onefile-tempdir-spec` 固定；失败先删 build 目录 | 删 build/dist 重打 |
| R8 | MSVC 探测失败/版本漂移 | `--msvc=latest` 解析不到 cl、或悄悄用 Zig | 构建日志断言 "MSVC version resolved to 14.3"；固定 `--msvc=14.44` | 指回 14.44 |
| R9 | numpy 2.5 性能/数值位移 | bench 帧时间变化、物理逐位对拍失败 | 保留 2.2.5 回退位；跑物理逐位对拍用例 | `pip install numpy==2.2.5` |
| R10 | onefile 启动变慢（解压/杀毒） | 双击到窗口 >2s、单实例锁误触；**实测第 1 次 16.2s、稳态 2.05s（2.7.1 是 1.87s）** | 优先 `--mode=standalone`；onefile 只用于构建器；评估 `--onefile-no-compression`/`--onefile-cache-mode` | 回 standalone |

**总回滚剧本**：所有升级都在 `C:\loom_build\<阶段>\venv` + `<阶段>.txt` freeze 中进行；主环境 `Python312` 不动；旧 dist（`runtime271`/`editor`）保留 → 任何一步失败都能在 10 分钟内回到升级前。

---

## ⑤ 工作量估计

| 项 | 人天 | 说明 |
|---|---|---|
| Step 0 基线 | 0.5 | 已有大部分数据 |
| Step 1 Nuitka 4.3.5 | 1.0 | 参数改造 + 编辑器插件 + 三件重打 |
| Step 2 依赖升级 | 1.5 | 7 个包 ×（测试 + AB + bench） |
| Step 3 Python 3.13 | 2~3 | 主要成本在 05 的预研分支与回归 |
| Step 4 VS2026 | 1.0 | 可选，建议推迟 |
| 文档/裁决 | 0.5 | 本报告 + 版本计划登记 |
| **合计（不含 3.13）** | **3.5** | Nuitka + 依赖 + 验证 |
| **合计（含 3.13）** | **6.5** | — |

---

## ⑥ 兼容边界

1. **ABI/CRT**：MSVC 14.4x 与 14.5x 同属 v14 ABI（官方 redist 声明），预编译 wheel（numpy/PySide6/shiboken）不需重编；风险只在 CRT DLL 分发与 Nuitka 的运行时 DLL 收集。
2. **Python 版本**：Nuitka 2.7.1 支持到 3.13；**3.14 起必须 ≥4.0，3.14 正式支持从 4.2 开始**；VS2026 需 ≥2.8.7。3.13 + Nuitka 4.3.5 可用（05 实测）。
3. **Qt**：编辑器依赖 Qt 平台插件（`qwindows.dll`）与 Qt 6.12 的 DLL 集合；`--enable-plugin=pyside6` 是硬前提。玩家运行时（`game_player`）不建 Qt 窗口，插件缺失不影响其启动（实测 dist 无 qt-plugins 也能到"缺游戏包"）。
4. **wgpu/Vulkan**：wgpu 的数据文件（`combined_header.h` 等）必须随包（`--include-package-data=wgpu`），wgpu_native DLL 必须显式 `--include-data-files`（现状 build_game.py 已做）；0.33 的 `DrawCancelled` 已被现有 `except Exception` 兜住。
5. **打包布局**：4.3.5 把 pygame DLL 放进 `pygame/`；`--include-windows-runtime-dlls` 4.x 默认 auto；dist 清单断言要按新布局写。
6. **onefile**：Windows onefile 自 2.7 起默认 DLL 模式（`--onefile-no-dll` 可退回）；2.7.1 官方称该模式仍需打磨，4.3.x 称 "finally perfect"；实测 4.3.5 体积 22.67MB（−1.3%）、稳态启动 2.05s（+0.18s）→ **稳定性是收益，解压成本仍在**。
7. **缓存**：clcache 与 Nuitka 构建缓存跨版本**不保证兼容**；升级后首次构建全 miss（实测 4.3.5 292 C 文件 0 命中），耗时以冷缓存为准。

---

## ⑦ 待裁决（封闭问题）

- **Q1**：Nuitka 升级是否接受 **+44% 构建时间**（369.5s → 532.8s）？若不可接受，是否只在发布机用 4.3.5、开发机保留 2.7.1？
- **Q2**：编辑器构建是否统一加 `--enable-plugin=pyside6`（+7.9MB，但否则 exe 起不来）？是否把"dist 内 `qwindows.dll` 存在"写成构建断言（而不是体积断言）？
- **Q3**：PySide6 走 **6.11.3（保守）** 还是直接 **6.12.0（LTS）**？
- **Q4**：wgpu 0.33.0 仅发布 3 天，是否本轮跳过、维持 0.32.0？
- **Q5**：是否启动 VS2026 迁移（需 Nuitka ≥4.3.5 + 新装 VS2026 Build Tools，且本机无法预演 14.5x）？
- **Q6**：3.13 迁移是否按 05 报告继续（本报告只确认工具链侧不阻塞）？

---

## 附录 A：可复现证据索引（2026-11-09，本机）

| 证据 | 路径/URL |
|---|---|
| Nuitka 4.3.5 隔离 venv | `C:\loom_build\toolchain_probe\venv312`（`--system-site-packages`） |
| 最小 standalone 日志 | `C:\loom_build\toolchain_probe\hello435_build.log`（65.8s / 12.31MB） |
| player 4.3.5 构建 | `C:\loom_build\toolchain_probe\runtime435_build.log`（532.8s / 140.9MB / 125 files） |
| player 2.7.1 基线 | `C:\loom_build\toolchain_probe\runtime271_build.log`（369.5s / 139.2MB / 118 files） |
| 编辑器 4.3.5 | `C:\loom_build\toolchain_probe\editor435_build.log`（448.1s / 132.2MB / 120 files，**无 qwindows.dll**） |
| onefile 4.3.5 | `C:\loom_build\toolchain_probe\builder435_build.log`（252.7s / 22.67MB，payload 91.78MB→23.55MB） |
| onefile 2.7.1 | `C:\loom_build\builder\build_game.exe`（22.96MB；启动 1.87s 中位数） |
| PySide6 插件对照 | `C:\loom_build\toolchain_probe\qt271\hello_qt.dist`（2.7.1 无 flag → 无 qwindows.dll） |
| CLI help 对比 | `C:\loom_build\toolchain_probe\help_271.txt` / `help_435.txt` |
| API surface 对比 | `C:\loom_build\toolchain_probe\{mgl_512,mgl_513,wgpu_032,wgpu_033}.json` |
| Nuitka changelog | <https://nuitka.net/changelog/Changelog.html>（2026-11-09） |
| Nuitka/PyPI 版本日期 | <https://pypi.org/pypi/nuitka/json> |
| 依赖版本/wheel | <https://pypi.org/pypi/{numpy,moderngl,PySide6,wgpu,pygame,glfw,pillow,zstandard}/json> |
| MSVC 版本表 | <https://learn.microsoft.com/en-us/cpp/overview/compiler-versions> |
| v14 ABI/redist | <https://learn.microsoft.com/en-us/cpp/windows/latest-supported-vc-redist> |
| VS2026 release notes | <https://learn.microsoft.com/en-us/visualstudio/releases/vs18/release-notes>（18.11.3 / 2026-10-29） |
| Qt 6.12.0 日期 | <https://wiki.qt.io/Qt_6.12_Release>（2026-09-30） |
| QOpenGLWidget（Qt 6.12） | <https://doc.qt.io/qt-6/qopenglwidget.html> |
| wgpu changelog | <https://api.github.com/repos/pygfx/wgpu-py/contents/CHANGELOG.md> |
| moderngl changelog | <https://api.github.com/repos/moderngl/moderngl/contents/CHANGELOG.md> |
| numpy 2.4/2.5 notes | <https://numpy.org/doc/stable/release/2.4.0-notes.html> / <https://numpy.org/doc/stable/release/2.5.0-notes.html> |

## 附录 B：本次未闭合项（诚实登记）

1. **2.7.1 的 onefile/编辑器构建耗时无同口径记录**（既有产物只留体积：onefile 22.96MB、editor 140.1MB/134 files）；4.3.5 侧数据完整（onefile 252.7s/22.67MB、editor 448.1s/132.2MB/120 files）。
2. **VS2026/14.5x 无法本机预演**（机器仅装 VS2022）→ 相关结论为官方文档 + Nuitka changelog 推断。
3. **PySide6 6.12.0 未在本机安装实测**（只做 wheel 元数据核对）；QOpenGLWidget 结论来自 Qt 6.12 文档存在性，非行为实测。
4. **依赖升级后的 121 测试/ab_gl_vk/bench/启动时间**均未跑（本报告是"升级前调研"，不是"升级后验收"）。
5. **editor 448.1s 只能与自身比**（2.7.1 无同口径计时），不能据此说编辑器构建变慢/变快。

---

## 附录 C：批次 0 实施结果（2026-11-09，3.12 主线）

按裁决执行：**Nuitka 4.3.5** + numpy 2.5.4 / moderngl 5.13.0 / PySide6 6.11.3 / glfw 2.11.0 / pillow 13.0.0；**wgpu 0.32.0、pygame 2.6.1 不动**；**MSVC 14.44 不动**；Python 3.12.10 不动。

**改动文件（7 个，全部是构建/打包/文档，未动引擎业务代码）**

| 文件 | 改动 |
|---|---|
| `Loom/build_game.py` | `--mode=standalone`、`--windows-console-mode=disable`、移除无效的 `--include-package-data=wgpu_native` |
| `Loom/game_player.py` / `Loom/build_entry.py` | 注释里的构建命令同步 |
| `使用操作指南.txt` | §7.5 补 `--enable-plugin=pyside6` 与新 flag，写明"漏插件 → 缺 qwindows.dll → exe 启动即崩，且体积反小 ~8MB" |
| `docs/design/架构互联协议总表.md` | §10.2 打包链命令同步（编辑器带插件、构建器明确 onefile） |
| `tools/package_engine.py` | 新增 `editor_dist_problems()` / `runtime_layout_problems()`；打包前硬断言运行时布局 |
| `tools/package_engine_compiled.py` | 打包前硬断言编辑器 dist 含 `PySide6`、`qt-plugins`、`platforms/qwindows.dll`，以及运行时 `pygame/` 布局 |

**改前 / 改后对照（同一台机，2026-11-09）**

| 指标 | 改前 | 改后 | Δ / 门禁 |
|---|---|---|---|
| 运行时构建耗时 | 369.5 s（Nuitka 2.7.1，同命令） | **363.9 s**（4.3.5，clcache 热） | −1.5%（4.3.5 冷缓存实测 532.8s，见 §1.5） |
| 编辑器构建耗时 | 无同口径基线 | **476.6 s** | — |
| 构建器构建耗时 | 无同口径基线 | **252.5 s** | — |
| 运行时 dist | 139.2 MB / 118 files | **140.4 MB / 125** | +0.9% |
| 编辑器 dist | 140.1 MB / 134 | **141.7 MB / 141**（含 qwindows.dll） | +1.1% |
| build_game.exe | 22.96 MB | **22.73 MB** | −1.0% |
| 发布包 zip | 125.94 MB | **128.46 MB** | **+2.0%**（门禁 ≤+5% ✅） |
| 启动中位数（`--help`×4） | 1.57 s | **1.615 s** | **+2.9%**（门禁 ≤+10% ✅） |
| `--bench` FPS（压测500混合/300帧） | 88.8 / 88.7 / 89.3 → 中位 **88.8**（n=3） | 88.0/83.6/87.0/89.2/88.5/88.7/86.7/87.8/88.1 → 中位 **88.0**（n=9） | **−0.9%**（9 次中 8 次在 84–90；单次 83.6 为离群） |
| `--bench` TPS | 29.92–30.24 | 29.98–30.24 | 持平 |
| `ab_gl_vk` MAE / MAX / NCC | 0.0021 / 0.2353 / 0.9741 | **0.0021 / 0.2353 / 0.9741** | 逐位相同（注：0.0021 本就 > 2e-4，门禁按"不劣化"解读） |
| 121 测试 | 基线全绿 | **121/121 PASS** | ✅ |
| 打包断言（负向） | — | 用无插件 dist 打包 → **exit 1**（缺 qt-plugins/qwindows.dll） | ✅ |

**回滚点（全部保留）**：`C:\loom_build\pre_upgrade_freeze_3.12.txt`（pip 回滚清单）、`C:\loom_build\engine\build_entry.dist.__old271`、`C:\loom_build\builder\build_game.exe.__old271`（启动对照用 `build_game_271.exe`）、`Loom/player_runtime/game_player.dist.__old271`、`C:\loom_build\toolchain_probe\runtime271\game_player.dist`、`C:\loom_build\toolchain_probe\pkg_baseline_0.1.0.beta6.zip`。

**附录 B 状态**：第 1、4、5 条已闭合（onefile/编辑器耗时、121 测试、ab/bench 均已有数）；第 2 条仍开放（VS2026 无环境）；第 3 条已在批次 0.5 实测（PySide6 6.12.0 + 3.13：qwindows 正常、121 测试全过、ab 无差）。
---

## 附录 D：批次 0.5 实施结果（2026-11-09，主线迁 Python 3.13）

按 D8 裁决：主线直接迁 **Python 3.13.15**，依赖拉满；保留 3.12 回滚路径。

**环境终态（3.13.15）**：Nuitka 4.3.5 / numpy 2.5.4 / moderngl 5.13.0 / wgpu **0.33.0** / PySide6 **6.12.0** / glfw 2.11.0 / pygame 2.6.1 / pillow 13.0.0 / culverin 0.14.0 / game-audio 2.1.0；MSVC 14.44 不变。
**期间补装（3.13 原本缺失，会静默降级）**：culverin 0.14.0（物理）、game-audio 2.1.0（音频）、numba 0.67.0（与 3.12 对齐；fastpath 实测两版均不启用）。

**改动文件**：`Loom/解释器.json`（python_version→3.13.15）、`使用操作指南.txt`（全量 py -3.13 + §7.5 补 `--nofollow-import-to=cupy` + 3.12 回滚段）、`架构互联协议总表.md` §10.2、`Loom/game_player.py` 注释、`tools/package_engine.py`（新增 `editor_dist_bloat`）、`tools/package_engine_compiled.py`（cupy 断言 + python_version 全量号）。

**3.12 → 3.13 对照（同机，source 口径）**

| 指标 | 3.12（批次 0 终态） | 3.13（本批） | Δ / 门禁 |
|---|---|---|---|
| 运行时构建 | 363.9 s / 140.4 MB / 125 | **443.7 s / 139.8 MB / 125** | 体积 −0.4%；耗时不可比（3.13 首次编译，clcache 冷） |
| 编辑器构建 | 476.6 s / 141.7 MB / 141 | **454.5 s / 141.6 MB / 141** | −4.6% 耗时，体积持平（含 qwindows.dll） |
| 构建器（onefile） | 252.5 s / 22.73 MB | **399.1 s / 21.56 MB** | 体积 −5.1% |
| 发布包 zip | 128.46 MB | **127.65 MB** | **−0.6%**（门禁 ≤+5% ✅） |
| 启动中位数（`--help`×4） | 1.61 s | **1.535 s** | **−4.7%**（门禁 ≤+10% ✅） |
| `--bench` FPS 中位（n=3，交替） | 84.2–88.8（漂移） | **79.5–80.3** | **−6%~−9%，门禁 ≥85 ✗** |
| `--bench` TPS 中位 | 30.05 | 30.04 | 持平 ✅ |
| `ab_gl_vk` | 0.0021 / 0.2353 / 0.9741 | **同值** | 不劣化 ✅（wgpu 0.33 + PySide6 6.12 实测无差） |
| 121 测试 | 121/121 | **121/121 PASS** | ✅（含物理/音频/编辑器/离屏） |
| 导入/解析 | 启动 72.7ms；import engine 690ms；editor 701ms；71 文件解析 418ms | **67.3ms / 579ms / 586ms / 425ms** | **−7.4% / −16.0% / −16.3% / +1.7%** |

**FPS 门禁失败（唯一未过项）**：3.13 在 `压测500混合`（物理重载）上稳定慢 6–9%；逐阶段看 `logic_step`（4.4 vs 3.8ms）与 `pipe_wait`（3.0 vs 2.5ms）同时变大，渲染/解析反而更快。已排除：culverin 版本（0.14/0.15 同）、numba（两版均未启用）、PySide6（bench 走 runtime.PlayerApp，不建 Qt 窗口）、wgpu（GL bench 不走）。**未定位**到具体调用点（疑似 3.13 下物理桥的小对象/线程调度开销）。

**重要干扰项**：本批执行期间有另一条并行批次在改业务代码（`Loom/engine.py`、`loom_glfw_window.py`、`loom_player_window.py`、`ui/loom_gui.py`、新增 `loom_gl_version.py`，时间 21:06–21:09）。3.12/3.13 交替 bench 同在改后代码上跑（相对比较有效），但 3.13 产物与 beta6 包**包含这些在途修改**；若该批次未定稿，需在其定稿后重打三件。

**回滚点**：`C:\loom_build\pre_py313_freeze.txt`（3.12 依赖+产物路径）、`C:\loom_build\post_py313_freeze.txt`、`C:\loom_build\engine\build_entry.dist.__py312`、`C:\loom_build\builder\build_game.exe.__py312`、`Loom/player_runtime/game_player.dist.__py312`、`tools/dist/Loom-0.1.0.beta6.zip`（3.13 版）。

**裁决（2026-11-09）**：人类**接受 −6%~−9% 物理 FPS 换 Python 3.13**，3.13 主线保留，不整体回滚；FPS 门禁记为"有条件豁免"。

---

## 附录 E：构建档位落地 + 编译版 bench 静默失败根因（2026-11-09）

**根因（已实锤）**：Nuitka standalone **不会**把运行期数据目录打包进 dist。编辑器 dist 缺 `ckernels/loom_kernels.dll`，而 `fastpath.py`（B1 退役后）是**硬加载** → `RuntimeError: ckernels 官方组件加载失败` → 进程 exit 1。release 档 `--windows-console-mode=disable` 无控制台，traceback 无人接收，于是表现为"静默 exit 1"。
- 源码版能跑：仓库 `Loom/ckernels` 就在旁边；
- 安装版能跑：`package_engine_compiled` 的 `DATA_DIRS` 会把 ckernels 复制进 zip；
- **裸 dist 是唯一断点** → 只有"直接跑 dist 里的 Loom.exe --bench"会炸。

**修复（构建/打包/断言，未动引擎业务逻辑）**
1. `tools/build_engine.py`（新增）：两档构建 + 自己进 vcvars64 + 打印档位/cl/python/nuitka + 旧 dist 挪 `.__prev` + **数据目录内嵌**（ckernels/core_components/core_plugins/plugins/scripts/GUI/assets/设置.json/输入配置.default.json）。
2. Nuitka 4.x 的 `--include-data-dir` 会**跳过 `*.dll`**（实测 core_components 6 个 DLL 全丢）→ 构建后再整目录补拷一次，并以 `ckernels/loom_kernels.dll`、`core_components`、`PySide6/qt-plugins/platforms/qwindows.dll` 作硬断言。
3. `Loom/build_game.py`：运行时 dist 同样内嵌 ckernels/core_components（构建后补拷 + 断言）；`--build-runtime` 单独使用时构建完即返回（旧行为会继续走游戏打包而 exit 1，导致工具误判）。
4. 档位隔离：dev 产物写 `C:\loom_build\*_dev`、`--windows-console-mode=force`；release 写正式目录、`disable`。每个产物目录写 `build_info.json`（mode/console/packageable/python/nuitka/built_at）。
5. `package_engine_compiled.py` 只接受 `mode=release`（编辑器/构建器/运行时三处都校验；dev 实测被拒 exit 1）。
6. `--bench` 失败契约：traceback → stderr + **退出码 2** + `%LOCALAPPDATA%\Loom\bench\bench_error.txt`（release 无控制台也能查）。

**实测（编译版，300 帧）：**
| 档位 | 验证 | FPS | TPS |
|---|---|---|---|
| dev（控制台） | stdout 完整输出阶段表，exit 0 | **75.9** | **30.21** |
| release（无控制台） | 写 bench_result.txt，exit 0 | **76.7** | **30.22** |
| 失败路径（坏场景） | stderr traceback + exit **2** + bench_error.txt | — | — |
| 负向打包（dev dist） | 被拒：档位 'dev' 要求 'release'，exit 1 | — | — |

**产物变化**：编辑器 dist 141.6→**144.1MB**、运行时 139.8→**142.3MB**（内嵌数据目录 +2.5MB×2）、构建器 22.77MB；发布包 127.65→**129.72MB**（+1.6%，仍含包根 DATA_DIRS 的一份冗余，属可接受冗余）。
遗留观察项：物理桥（`physics_bridge` / culverin 步进）在 3.13 下的 1ms 级开销未定位，后续若做性能专项可 profile 后补回；产物与当前工作树一致（业务文件最后修改 21:06–21:09，三件产物 21:45–22:13 之后生成，无需重打）。

---

## 附录 F：打包链修复（2026-11-10，Q1=A / Q3=A / Q4=B）

**Q1 内嵌 Python 改为 3.13.15**：`find_python_embed` 不再硬编码 Python312，改为跟随 `Loom/解释器.json` 的 `python_version`：
`LOOM_PYEMBED_DIR` → `tools/python-embed` → `C:\loom_build\python-embed\<ver>` → 从 python.org 下载 `python-<ver>-embed-amd64.zip` → 本机同版本完整安装兜底。
embeddable 是隔离模式（`python3xx._pth` 禁 site、且**脚本目录不进 sys.path**）→ 补丁加 `Lib\site-packages`、`..\Loom`、`import site`；否则 `pythonw Loom\Loom.py` 会 `ModuleNotFoundError: plugin_loader`（首次实测即为此失败，已修）。

**Q3 版本一致性硬门（两道）**：
1. 候选运行时 `python.exe` 实际版本 ≠ `解释器.json.python_version` → 打包前拒绝（不白跑 pip）；
2. 包内组装完成的 `python/python.exe` 再验一次，仍不一致 → 拒绝出包；
3. 元数据回写 `python_version = 实际内嵌版本`，README 版本口径同步。
负向实测：`LOOM_PYEMBED_DIR=Python312` + meta=3.13.15 → exit 1，报"运行时='3.12.10', 解释器.json='3.13.15'"。

**Q4 Loom.bat 双形态**：`if exist Loom\Loom.exe` → `start Loom\Loom.exe %*`；否则 `pythonw Loom\Loom.py`；两者都缺 → ASCII 错误提示 + `exit 1`。README 按包形态分开写（编译版：双击 `Loom\Loom.exe`；源码版：双击 `Loom.bat`，内嵌 Python 3.13.15）。

**实测**：
| 项 | 结果 |
|---|---|
| 源码包（仅 3.13 环境） | 346.6 MB；`python/python.exe`=3.13.15、`_pth` 含 `..\Loom`；meta/README 均 3.13.15 |
| 源码包 `Loom.bat` | 走 python 分支，`pythonw.exe` 进程存活（编辑器起来） |
| 编译包 `Loom.bat` | 走 exe 分支，`Loom\Loom.exe` 从包目录启动，bat exit 0 |
| 版本不一致 | exit 1（见上） |
| 测试 | `test_release_version` + 6 个 `test_hub*` 打包相关测试全绿 |

**已修（2026-11-10 Q-PKG-4）**：源码包/编译包加 `--kind source|compiled`（默认各自脚本自动取），产物名 `Loom-<ver>-source.zip` / `Loom-<ver>-compiled.zip`，不再互相覆盖；`package_engine._verify_zip` 与 `release_github.engine_zip()`（优先 compiled → source → 旧名）同步；`test_release_version` 的包名断言更新。实测：compiled 129.70MB、source 346.60MB 并存。

**R6-03 复核修复（2026-11-10）**：① 源码包接线 `meta_version_problems`（源码 Loom/解释器.json、预置运行时嵌套 meta 都必须 == 目标版本，`--version` 不再覆盖不一致 meta）；② `_verify_zip` 增加嵌套 `Loom/player_runtime/game_player.dist/解释器.json` 与顶层版本一致性校验；③ 编译包校验 `build_info.json` 字段（mode=release、python=x.y.z、nuitka、built_at 可解析），写 zip 前校验 dist meta == `--version`、写后回读 + zip 内再验。
负向实测全部 exit 1：源码 dist meta=beta10×--version=beta6；顶层 beta6+嵌套运行时 beta5；--version=beta10 vs meta beta6；编译包 editor meta=beta10；编译包运行时 meta=beta5；build_info mode=dev。
**源码包已删除（原 07:35 的 SCENE_VERSION=10 旧包）**，发布前用当前代码重建：`py -3.13 tools/package_engine.py --version 0.1.0.beta6 --allow-missing-runtime` → `tools/dist/Loom-0.1.0.beta6-source.zip`。

**遗留**：① （已修，见上）；② 源码包 `requirements.txt` 未含 `culverin`/`game-audio`（源码版物理/音频降级，编译版不受影响），是否补进 requirements 待裁决。

---

## 附录 G：交付包自证、HEAD 中途前进与对拍工具坑（2026-11-10）

### G.1 「HEAD 中途前进 → 停下报告 → 裁决 B」

- 21:23 构建启动时 HEAD=**dea1f4f**、`git status` 干净；21:36 另一 agent 提交 **c56fb1d**；21:41–21:43 完成两包；自证发现 compiled `build_info.git_head=dea1f4f` ≠ HEAD `c56fb1d` → **按协议停下报告，未硬交**。
- 事实核对：`dea1f4f..c56fb1d` 仅 +354 行（`tools/smoke.py`、`tools/measure_engine.py`、两份文档），**引擎代码零改动**；源码包 93 个引擎 `.py` 与 HEAD **0 不一致 / 0 缺失**；**version 两处可比**（顶层 meta / 嵌套运行时 meta）均 0.1.0.beta6 且 == `--version`；`git_dirty=false`。
- **裁决 B**：接受当前包，不为"来源提交号"重编 20 分钟。
- **纪律（写死）**：最终发布版必须在**最新干净 HEAD** 上重编；`build_info.git_head` 必须等于**发布 tag 指向的提交**，`git_dirty` 必须 false。再遇 "HEAD 中途前进" 一律按本节流程停下报告，不得硬交。

### G.2 对拍工具自身误报（踩过两次，必须记住）

1. **EOL 误报**：仓库 `core.autocrlf=true` → 工作树 CRLF、git blob LF；直接用 zip 原始字节 vs `git show HEAD:` 字节比 sha，会把所有 CRLF 文件误判成"不一致"（实测 24/18 个假阳性）。工具必须两侧 `\r\n`→`\n` 归一后再算内容哈希。
2. **运行时 dist 混入源码比对**：源码包内 `Loom/player_runtime/game_player.dist/**.py` 是预置运行时产物（core_components 的 boot_check/module_loader/module_registry/official_manifest），不在 git 树里，会被误报为"HEAD 不存在"。比对范围必须限定 `Loom/*.py` 且排除 `Loom/player_runtime/`。
3. 自证同时要查：version 只有 **2 处**可比（顶层/嵌套运行时 meta）+ `--version`；**python 有 3 处**（editor build_info.python、runtime build_info.python、meta.python_version）——不要再说"三项 version 一致"（build_info 没有 version 字段）。compiled 包无 `.py`，用 `build_info.git_head` 作代码级证据，但判据是 **祖先 + Loom/ 零 diff**（见 G.4），不是相等。

### G.3 当前交付物（裁决 B 后）

- `tools/dist/Loom-0.1.0.beta6-compiled.zip` **132.02MB**（build_info: git_head=dea1f4f / git_dirty=false / python 3.13.15 / nuitka 4.3.5）
- `tools/dist/Loom-0.1.0.beta6-source.zip` **348.54MB**（93 个引擎 `.py` 与 HEAD 0 不一致；内嵌 Python 3.13.15；SCENE_VERSION=11）
- 自证脚本已收编进仓库：`py -3.13 tools/verify_pkg_vs_head.py <source.zip> <compiled.zip> [--version <ver>] [--json out.json]`（EOL 归一 + 排除 runtime dist + git_head 祖先/引擎零 diff 判据）。

### G.4 V2-02 修订（2026-11-10，按审计纠正）

1. **compiled 判据改为"祖先 + 引擎零 diff"**：`git_head` 必须是 HEAD 的祖先，且 `git diff --name-only <git_head> HEAD -- Loom/` 为空才判 OK。理由：审计实测 `dea1f4f..HEAD` 只动 `.gitignore/docs/tools` 6 个文件、`Loom/` 零改动，旧"必须相等"会因每次改文档误红。工具 `tools/verify_pkg_vs_head.py` 已实现并实测：当前包 `git_head=dea1f4f` vs HEAD 更新后判 **OK（引擎等价）**。
2. **门序硬门 `smoke_passed_at`**：`build_info.json` 新增该字段（build_engine 初值 null；`tools/smoke.py` 通过后盖章，支持 `--stamp <dir|file>`，`--dist` 时自动盖该 dist）。打包脚本要求它**存在且晚于 built_at**，否则 exit 1（实测：未盖章 → 拒绝打包；冒烟通过后三件盖章 → 打包通过）。审计证据：本包 built_at=21:23:42，而 `tools/smoke.py` 首个提交 21:36 → 该包从未执行"编译→冒烟→打包→对拍"。
3. **口径纠正**：`build_info` 无 `version` 字段 → version 可比 **2 处**（顶层/嵌套运行时 meta）+ `--version`；python 可比 **3 处**（editor/runtime 两份 build_info + meta.python_version）。
4. **工具收编**：自证脚本已在仓库 `tools/verify_pkg_vs_head.py`（原 `C:\loom_build\toolchain_probe` 版本仅作历史）；用法见上。


