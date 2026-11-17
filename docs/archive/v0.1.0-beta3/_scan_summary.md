# Loom 全量扫描 · 跨模块总账（2026-11-07）

> 由 12 个模块审计报告汇总。详情：`docs/audit/scan_<NN>_*.md`；逐模块明细：`_scan_ledger.md`。

## 0. 覆盖率

| 模块 | 粗筛 | PROVED | DISPROVED | UNKNOWN | P0 | P1 | 回归 |
|---|---|---|---|---|---|---|---|
| 01_core | 15 | 12 | 3 | 0 | 0 | 2 | 0 |
| 02_scene | 24 | 11 | 12 | 1 | 0 | 4 | 0 |
| 03_gl_render | 13 | 9 | 3 | 1 | 1 | 3 | 1 |
| 04_vk_render | 27 | 13 | 12 | 2 | 0 | 2 | 8 |
| 05_player | 19 | 11 | 6 | 2 | 0 | 2 | 10 |
| 06_editor_ui | 27 | 16 | 9 | 2 | 0 | 3 | 1 |
| 07_eai | 24 | 19 | 4 | 1 | 1 | 4 | 2 |
| 08_physics | 20 | 15 | 4 | 1 | 0 | 6 | 0 |
| 09_scripting | 26 | 17 | 6 | 3 | 2 | 4 | 0 |
| 10_assets | 38 | 26 | 8 | 4 | 0 | 1 | 0 |
| 11_build | 28 | 19 | 7 | 2 | 0 | 6 | 2 |
| 12_misc | 14 | 14 | 7 | 1 | 0 | 4 | 2 |
| **合计** | **275** | **182** | **81** | **20** | **4** | **41** | **26** |

## 1. P0（4 条，全部可复现）

| # | 模块 | 位置 | 后果 | 触发 |
|---|---|---|---|---|
| P0-1 | 07_eai | agent_commands.py:2062-2064 → loom_hud.py:220 | `tuple()` 收字符串 → 渲染帧 `TypeError` → **GLFW 播放器进程退出** | EAI 加带颜色的 UI 元素 |
| P0-2 | 09_scripting | plugin_sandbox.py:41-45,69-73 + plugin_loader.py:235-258 | 受限插件拿到真 `builtins` → **写出插件目录外文件** | `collections._sys.modules["builtins"].open` |
| P0-3 | 09_scripting | plugin_loader.py:193-200 | 经 traceback 拿 loader globals → 同类逃逸 | `tb_frame.f_globals` |
| P0-4 | 03_gl_render | loom_lighting.py:174,177-179 | 聚光灯阴影只记 1 槽 → `sampler_units[17]` IndexError | **≥2 投影点光 + 1 投影聚光灯** → 引擎退出 / Qt 每帧黑屏 |

## 2. P1 按主题分组（37+ 条，只列主干）

### 2.1 崩溃 / 进程退出
- 11_build `--bench` 必崩 `NameError`（import 顺序）；`build_game --output . --force` 可 `rmtree` 引擎源码根（**无路径守卫**）
- 04_vk_render `vis` 为空 + 平行光阴影 → 每帧 ValueError → `os._exit(1)` 闪退
- 10_assets `params.stacks=0` → ZeroDivisionError 中断加载
- 03_gl_render 聚光槽位 IndexError（同 P0-4）

### 2.2 静默错误（不崩但结果错）
- **04_vk_render P-01 桶实例偏移**：同网格同贴图物体被隔开时，绘制覆盖别的桶 → 漏画/错形（A/B 未覆盖该组合）
- 08_physics 建体 identity 旋转写回、AABB 中心瞬移、祖先脏传播断链（父无碰撞体时子体不跟随）、子步异常被覆盖
- 02_scene 加载容错不全致半途中断；父链成环静默丢对象 + `world_scale` 死循环
- 01_core 编辑器播放态矩阵冻结；小场景碰撞事件永不触发
- 06_editor_ui Qt 先清 pressed 再分发 → **官方编辑器 UI 交互全失效**；顶层 Canvas root 拦截低层命中；滚轮不传 UI
- 07_eai `bool("false")=True`、`object_select` 静默取第一个（导致删/复制错对象）、`unity_script_write_file` **无白名单**（路径穿越）

- 12_misc 撤销覆盖缺口：光源 range 不入栈、材质/法线/PBR/env/LOD/prefab 断开均不可撤销；FPS 缓冲黑帧；文件对话框 64 位句柄截断崩溃

### 2.3 数据/资源泄漏
- 02_scene 每次打开-保存 +1 孤儿材质；纯色 env 保存即丢
- 10_assets GL 纹理换 ctx 不 release（5 次泄漏 5 张）；音频 `_handles` 无淘汰
- 09_scripting 每次播放/停止泄漏一个 Lua state；插件部分注册后抛异常无法卸载
- 08_physics `_last_sync` 不清理（50 轮建删 51 条）；`_tree_bit` 不回收（>31 棵跨树漏碰撞）

## 3. 本轮"Vulkan 对齐"引入的回归（24 条，优先修）

| 模块 | 数量 | 代表项 |
|---|---|---|
| 05_player | 10 | 贴图导入设置丢失（VK 512²/10 级 vs GL 128²/1 级）、相机坏值 VK 崩而 GL 正常、LOD 每帧全量重算世界矩阵 +2.17ms、LOD 根本没进序列化、默认视角 0/0 与 GL 分叉、wheel 不清零、覆盖 rendercanvas 回调 |
| 04_vk_render | 8 | 桶实例偏移（P1 静默画错）、法线回落白纹理、env 缓存 id 键无淘汰、文本 LRU 不 release、wrap/filter 被忽略、PBR 开关属性名错、多平行光阴影只用 1 张 |
| 11_build | 2 | `_launch_player` 未实现 docstring 声称的 `LOOM_REMOTE_MODE`；`--run` 无回退导致无 Vulkan 机器启动失败 |
| 03_gl_render | 1 | P-17 守卫前提被证伪（far 无关），+6.44ms/帧 |
| 06_editor_ui | 1 | R-03b 死代码（loom_ui 修好后兜底失效） |

## 4. 需人类裁决（压缩为 8 条封闭题）

| # | 问题 | 选项 |
|---|---|---|
| D1 | 场景/存档是否视为不可信输入？ | A 是（全量防御）／B 否（报错退出即可） |
| D2 | 材质库保存是否裁剪无引用条目？ | A 仅加载时阻止孤儿／B 保存时裁剪／C 两者+资产标记 |
| D3 | Prefab 是否携带材质资产？ | A 携带／B 按 guid 回查／C 声明不支持 |
| D4 | 聚光灯阴影契约 | A 支持 6 面（最多 2 盏非定向阴影光）／B spot 不投影／C 仅 1 盏 |
| D5 | 点光阴影是否保留 C 路径（P-17 守卫去留） | A 删守卫走 C（快）／B 永久 Python（+6.4ms/帧并存基线） |
| D6 | 插件受限环境定位 | A 安全边界（必修 P0-2/3）／B 仅误用护栏（降级+改文档） |
| D7 | `--run` 默认后端 | A 保持 vulkan+失败提示／B 改 auto 回退／C 默认 opengl |
| D8 | 多 Canvas 命中语义 | A root 不参与／B 全屏拦截（现状）／C 只吞空白继续下探 |

## 6. 人类裁决（2026-11-07 定稿）

| # | 问题 | 裁决 | 落地含义 |
|---|---|---|---|
| Q1 | 插件受限环境定位 | **A 安全边界** | 必修两条沙箱逃逸（P0-2/P0-3），补逃逸回归 |
| Q2 | 聚光灯阴影契约 | **A 支持 6 面** | 每盏投影聚光灯登记 6 槽；限制"最多 2 盏非定向阴影光"，超限警告 |
| Q3 | 点光阴影 C 路径 | **A 删 P-17 守卫** | 恢复 `pipeline.dll` 算 VP，仅 `rows is None` 时 Python 兜底（省 6.44ms/帧） |
| Q4 | 场景是否不可信输入 | **B 否** | 不做全量防御；父链成环等"会死循环/丢数据"的仍必须拒绝（否则是崩溃而非报错） |
| Q5 | 撤销覆盖 | **A 扩快照全覆盖** | 快照纳入光源 range、材质 albedo/PBR/env、法线模式、LOD、prefab 断开；补成对测试 |
| Q6 | `--run` 默认后端 | **A + 定制回退** | 默认 vulkan；**失败时崩一次并明确提示"Vulkan 后端不兼容"**，同时把设置回退为 opengl；下次启动用 GL。不静默、不掩盖 |
| Q7 | 多 Canvas 命中 | **C 只吞空白** | root 未命中子元素时继续下探低层；只有无人命中才由 root 消费 |
| Q8 | FPS 缓冲 | **A 修 FBO + 深度** | 预画真正写入离屏 FBO，补深度附件 |
| D2~D13 | 其余 25 条 | **按推荐默认** | 见 §4 表格"默认"列 |

### Q6 精确语义（实现契约）
```
1. 默认后端 = vulkan（设置.json）
2. Vulkan 初始化失败时：
   a. 打印/弹窗明确原因：「Vulkan 后端不兼容（<设备/驱动原因>），已回退 OpenGL，下次启动将使用 OpenGL」
   b. 把 设置.json 的 backend 写成 "opengl"（持久化，只写一次，避免每次启动都崩）
   c. 本次进程以**非零退出码**结束（保持"崩过"的事实，不伪装成功）
3. 下次启动：读设置 = opengl → 正常打开
4. 显式 --backend vulkan（用户强制）时不改写设置，只报错退出（尊重显式选择）
```

## 5. 修复批次建议（按风险/收益排序，等 12 号补齐后定稿）

1. **P0 四连**（崩溃/逃逸）：UI 颜色类型、插件沙箱两条、聚光槽位。
2. **我的 24 条回归**：先删 P-17 守卫（-6.4ms）、修桶实例偏移（静默画错）、修贴图导入设置、修相机坏值崩溃、修 LOD 空转（要么进序列化要么删）。
3. **静默错误**：编辑器 UI 分发顺序、小场景碰撞兜底、物理 identity 旋转/AABB 中心、父链成环、加载容错。
4. **资源泄漏与安全边界**：纹理/Lua/handles/tree_bit、MCP 写白名单、`build_game` 路径守卫。
5. **P2/P3 清理**：死代码、文档失真、日志刷屏。