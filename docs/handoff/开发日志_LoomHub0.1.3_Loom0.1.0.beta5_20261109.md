# 开发日志：Loom 0.1.0.beta5 / LoomHub 0.1.3（2026-11-09）

> 本文是这一轮内测版本的**交接与继续开发入口**。读完这一篇 + `docs/handoff/接手总纲_*.md` 即可接手。
> 版本口径：引擎 `0.1.0.beta5`、LoomHub `0.1.3`；两条版本线独立，发包后才跳下一号（见 `docs/README.md` 开发阶段声明 ⑤）。

---

## 1. 本轮一句话总结

把"帧率低但 CPU/GPU 都没吃满"和"天空盒一直偏黑"两个长期问题查到底并修掉了根因，同时补上 Hub 自更新与引擎选择交互；
代价是播放器运行时多了 Qt 依赖（包体 +16.5 MB，人类已裁决接受）。

---

## 2. 交付物

| 产物 | 大小 | SHA256 前 16 位 |
|---|---|---|
| `tools/dist/Loom-0.1.0.beta5.zip` | 125.94 MB | `341A6334912E6928` |
| `tools/dist/LoomHub-0.1.3-Setup.exe` | 23.82 MB | `58D72606483C6D33` |

- 引擎：编译版（Nuitka standalone 编辑器 + onefile 构建器 + 编译版运行时），无 `python/`、无 `.py`
- Hub：PyInstaller onedir + Inno Setup 7，支持用户级/系统级安装
- 安装位置（本机）：`C:\Program Files\Loom\0.1.0.beta5`、`C:\Program Files\LoomHub`

---

## 3. 性能：从 38 FPS 到 90 FPS（同场景 压测500混合）

| 指标 | 修前 | 修后 |
|---|---|---|
| FPS | 38-41（remote-mode 强开）／55-61（直连） | **84-90** |
| TPS | 23.7 | **30.2-30.5**（目标 30） |
| GPU | 31-34% | **56%** |
| 逻辑步墙钟 | 38.25 ms | 33.3 ms（预算内） |

### 根因链（按发现顺序）

1. **Hub 无条件注入 `LOOM_REMOTE_MODE=1`** → 引擎走"离屏 GL + QImage 回读"，每帧多一次 GPU→CPU 拷贝与同步
   → A/B 实测 55-61 → 38-41 FPS。**修复**：`hub_config.apply_launch_env` 单点决定，设置项 `remote_mode=auto|off|on`，默认 off。
2. **逻辑时钟记账错误**：同步路径相信调用方 dt（`--bench` 传 1/120=8.3ms，实跑 94FPS=10.6ms）→ 每秒只累计 0.79 秒
   → TPS = 30 × 0.79 = **23.7**（与现场逐位吻合）。**修复**：`engine._clock_advance()` 取 `max(调用方 dt, 实测墙钟)`，三路径统一。
3. **单核 GIL 饥饿**（修完口径后才暴露的真瓶颈）：满载时逻辑线程每秒只被调度 ~10 次，单步墙钟 15ms→39ms。
   **修复**：① `loom_lighting` 的 AABB `visible_only=True` 同帧记忆化（504 物体 15.3ms/次 → 命中 0.35ms）
   ② `loom_render._prepare_bucket_frame` numpy 化（桶计划预生成 + 每帧一次 `fw32[order]` gather，删 38 次 ctypes pack）
   → 主线程 buckets 4.22→2.30ms、pipe_wait 5.73→3.62ms、逻辑线程回血，TPS 达标。
4. **暂停补欠账**（第三轮审计发现的回归）：暂停期间 `_logic_wall_last` 不更新 → 恢复首帧 `wall_dt` = 停顿长度（截 0.333s）
   → 一帧连跑 9-10 个逻辑步。**修复**：四条暂停路径各重锚（引擎三处 + 渲染 + 逻辑线程 + VK 驱动），恢复首帧 ≤1 步。
5. **逻辑线程停不掉**：先 `_logic_stop=None` 再 `ev.set()`，循环读实例字段 → 永不退出（join 卡 2s、孤儿线程推步、再 start 变双线程）。
   **修复**：先 `ev.set()` 再清引用 + 循环用局部 `ev` + 重复 start 复用。

---

## 4. 天空盒：从"一直偏黑"到"默认蓝天 + 语义自洽"

### 结论先行

- **"偏黑"不是渲染失败**：无天空盒时是硬编码清屏色（`(25,31,41)`，GL 播放器此前更黑 `(13,13,25)`）；
- **纯色天空盒渲染链路一直是好的**（GL/VK 逐像素 MAE=0.000）；
- 真正的问题是**没有"默认天空盒"契约** + 一串"修复存在但没生效"（N1 模式）。

### 本轮落地（人类裁决 Q1-Q6 / A1-A6）

| 项 | 落地 |
|---|---|
| 默认天空盒 | `sceneio.DEFAULT_SKYBOX_COLOR=(58,155,213,255)` 单点；新建场景注入；加载缺键/null 也按默认 |
| 清空语义 | `skybox_clear` = **恢复默认蓝天**（`reset_to_default`）；要黑色须显式 `#000000` |
| 三处底色 | 收敛到 `loom_shaders.CLEAR_COLOR_RGBA` 唯一来源 |
| 相机级优先 | 渲染端读 `engine.effective_skybox()`（相机级→场景级回退）；编辑器绘制门改同一判定 |
| 颜色合法域 | 只认 0..255（`sceneio.parse_color` 先校验后使用）；`from_solid` 非法一律 ValueError |
| 失败可见 | `skybox_get` 带 `valid/reason/scene_valid/active_camera_skybox/vk` |
| 路径可移植 | 六面图存相对场景目录路径；限制在场景目录内（越界/绝对路径拒绝） |
| 哨兵 | `_sky_prog=False` 永久哨兵改为按对象复位 + 失败告警一次 |
| 无效 cubemap | 缺面/尺寸不一致 → 拒绝 + 告警一次 + 不画（删 GL 1×1 白兜底，VK 不再 IndexError 穿透） |
| 相机配对 | 由"下标 zip"改为 id→段映射 + guid 查找，未匹配宁可不画不错色 |

### 实测

```
默认天空盒: 默认蓝天 (58,155,213,255) valid=true
skybox_clear: reset_to_default=true, 生效值 = 默认蓝天
skybox_set #000000 -> [0,0,0,255]（可持久）
#000000 / (58,155,213) 两种输入均正确
```

> 注意：PacMan2D 示例场景的"地板"30×30 铺满 ortho 视口（ortho_size=13），即使默认蓝天生效也看不到天空——这是**场景内容**，不是引擎缺陷。

---

## 5. LoomHub 0.1.3

| 项 | 内容 |
|---|---|
| remote-mode | 默认 off（曾无条件注入，代价 20 FPS）；设置项 + NovaHubGUI 也有开关 |
| 自更新（DSH 式） | 启动 10s 后检查、24h 一次；下载 → 校验(size/sha256) → **提权前再校验** → 关自身 → 静默安装 → **不自动启动** |
| 安装落点 | 跟随当前安装目录（`/DIR`）；`/ALLUSERS` 仅在 Program Files；用户级不弹 UAC |
| GUI | 「检查更新」+「下载并安装」（无新版时禁用） |
| 安全边界 | 未校验包一律拒绝（此前可被提权执行任意 exe） |
| 解释器台账 | 启动重识别（原地替换不再显示"源码版"）；**default 标记不再被 refresh 抹掉** |
| 引擎选择 | 「选为当前引擎」内存缓存 + 「用当前引擎打开」（Tk `exportselection=1` 导致"引擎+项目同时选中"物理不可能，已设 False） |
| 优先级 | 显式传入 > 缓存当前引擎 > 项目 `engine_dir` > 默认引擎 |

---

## 6. 第三轮专项审计（人类要求的"扫一遍新修复代码"）

5 个子代理按两份方法学文档 + `SCAN_PROTOCOL.md` 扫描 `71b31ac..HEAD`（32 文件 / +3434 行）：

| 编号 | 范围 | 报告 |
|---|---|---|
| 01 | 天空盒·场景与命令侧 | `docs/audit/scan_beta5_round_01_skybox_scene.md` |
| 02 | 天空盒·渲染侧与播放器一致性 | `docs/audit/scan_beta5_round_02_skybox_render.md` |
| 03 | 性能改造·时钟与桶管线 | `docs/audit/scan_beta5_round_03_perf_clock_buckets.md` |
| 04 | Hub·自更新与引擎选择 | `docs/audit/scan_beta5_round_04_hub_update_selection.md` |
| 05 | 入口·构建·打包链 | `docs/audit/scan_beta5_round_05_entry_build_pkg.md` |

**审计抓到的真回归（全部已修）**：skybox_set 设了不生效、非 dict skybox 崩且丢场景、六面图相对路径基准不重算、
暂停补欠账、逻辑线程停不掉、`run()` 不再 terminate GLFW、`--bench` 场景不存在/帧数 0 崩溃、`ratio` 注释方向写反、
Hub 提权执行未校验包、启动检查未接线。

---

## 7. 已知未复现 / 未决项

| 项 | 状态 |
|---|---|
| `LOOM_REMOTE_MODE=auto` 真实故障路径 | **逻辑已验证、真实故障路径未复现**（无白屏机器；单测覆盖 3 次失败判真、成功清零、只重启一次） |
| 包体 125.94 MB | **人类裁决接受**（播放器运行时为 remote 回退带入 Qt，+16.5 MB） |
| GPU 像素级 A/B 基线 | 未做（需真机 A/B 采集） |
| 结构优化剩余缺口 | buckets 2.3ms / mt_mp_draws 1.4ms / aabbs 2.1ms / pipe_wait 3.6ms（继续冲高时的下一档目标） |
| 六面图跨机可移植 | 已限制在场景目录内；跨机器仍需连同目录一起搬 |

---

## 8. 如何继续开发（命令速查）

```powershell
# 全量回归（121 个测试文件）
cd "D:\my-project - 副本\Loom(py源代码-工作区)\Loom"; python tests/run_all.py

# 场景基准（结果写 %LOCALAPPDATA%\Loom\bench\bench_result.txt）
python Loom.py --bench Projects\压测500混合.json 300

# 源码编辑器（带 EAI 命令桥，可用 engine_metrics 取 FPS/TPS）
python Loom.py --agent --open Projects\压测500混合.json

# 编译（需先 call vcvars64）
python -m nuitka --standalone --msvc=latest --enable-plugin=pyside6 --include-package=ui --windows-disable-console --output-dir=C:\loom_build\engine --output-filename=Loom.exe build_entry.py
python -m nuitka --onefile --msvc=latest --windows-disable-console --output-dir=C:\loom_build\builder --output-filename=build_game.exe build_game.py
python build_game.py --build-runtime

# 打包
python tools/package_engine_compiled.py --version 0.1.0.beta5 --editor-dist C:\loom_build\engine\build_entry.dist --builder-exe C:\loom_build\builder\build_game.exe
python tools/package_hub.py --version 0.1.3

# 发布（默认先跑全量回归；--no-require-tests 可跳过）
python tools/release_github.py all
```

### 纪律（本轮踩过的坑，务必遵守）

1. **大文件不读全文回写**：读取工具对大文件可能少返回行，整文件回写会截断（`vk_renderer.py` 曾从 1896 行被截到 1064 行）。一律用定点 `edit`。
2. **失败必须可见**：不得 `except: pass` / 假 `ok=True`。本轮修的 P1 里有一半是"静默失败"。
3. **视图不硬依赖控制器新方法**：加 `hasattr` 守卫，否则第三方视图/测试桩直接崩。
4. **改调度/时钟前先取证**：`engine_metrics.logic_metrics` 已有 ratio / drop / clamp / 线程计数，别靠猜。

---

## 9. 后续可选项（按价值排序）

1. 继续压 TPS 上限：桶级 GPU 写入合并（38 次小 write → 1 次大 write）+ draw 派发合并
2. GPU 像素级 A/B 基线（GL vs VK 全场景对拍）
3. 六面图资产的 guid 化（跨机可移植）
4. 播放器运行时瘦身（若未来不需要 remote 回退，可去掉 Qt 依赖回收 16.5 MB）


---

## 10. 发布记录（2026-11-09 15:50 CST）

| Release | 链接 | 类型 | 资产 | GitHub digest |
|---|---|---|---|---|
| `engine-v0.1.0.beta5` | https://github.com/lhy302/WeaveEngine/releases/tag/engine-v0.1.0.beta5 | prerelease | `Loom-0.1.0.beta5.zip` 125.94 MB | `sha256:341a6334912e6928…90993a9` |
| `hub-v0.1.3` | https://github.com/lhy302/WeaveEngine/releases/tag/hub-v0.1.3 | release | `LoomHub-0.1.3-Setup.exe` 23.82 MB | `sha256:58d72606483c6d33…f275fe1d4a` |

- 两个 tag 均指向 `08ad3a3`（= 发布时代码 HEAD）。
- 发布脚本日志里 "推送 tag 失败: already exists" 是**预期噪音**：Release API 建 Release 时已在远端创建同名 tag，脚本随后的 `git push` 因此被拒；tag 指向已由 API 决定，无需强推。
- 线上 digest 与本地 `Get-FileHash` 前 16 位一致（`341A6334912E6928` / `58D72606483C6D33`），确认上传的就是本地构建产物。
