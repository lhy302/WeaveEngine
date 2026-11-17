# 全量扫描 → 修复总报告（2026-11-07）

> 上游：`_scan_summary.md`（275 项粗筛 / 182 PROVED / P0×4 / P1×41）；
> 明细：`_scan_ledger.md`、`_fix_ledger.md`、各 `scan_*.md` 与 `fix_*.md`。

## 0. 结论速览

| 指标 | 数值 |
|---|---|
| 审计模块 | 12（69 个顶层 .py + ui/，约 33.6k 行） |
| 粗筛 / 证真 / 证伪 / 未知 | 275 / 182 / 81 / 20 |
| 修复批次 | **9 批 + 4 个跨文件收尾** |
| 修复项 | **P0×4、P1×41 全部处理**；P2/P3 处理主要项 |
| 测试文件 | 56 → **91**（新增 35 个） |
| 新增断言 | 300+ |

## 1. 四个 P0（全部修复并有回归用例）

| P0 | 修复 | 改前 → 改后 |
|---|---|---|
| `ui_add` 颜色类型错 → 进程退出 | 统一 `parse_color` + `_coerce_color_args` | `("#","f","f",...)` → TypeError → 崩 | `(255,0,0,255)` → 正常渲染 |
| 插件沙箱逃逸 1（`collections._sys`） | `_ModuleProxy` 拒下划线/子模块 | 真写出 PWNED | AttributeError 且不落盘 |
| 插件沙箱逃逸 2（`tb_frame.f_globals`） | 宿主异常重抛无宿主帧 + AST 名单 | 拿到 os/sys 并写文件 | 栈只剩 [插件帧, 沙箱帧] |
| 聚光灯阴影槽位 IndexError | 每灯 6 槽 + 预算降级 | ≥2 点光+1 聚光 → 引擎退出 | 不崩，`slots=(0,6,-1,12)` |

## 2. 被"22 场景 A/B 全绿"掩盖的问题（本轮审计最大价值）

这些问题在像素对比里**看不出来**，因为 A/B 场景恰好没有覆盖：

1. **VK 桶实例偏移**：同网格同贴图物体被隔开时画到别的桶 → 漏画/错形（2093 错像素，A/B 无该组合）；
2. **编辑器播放态矩阵冻结**：逻辑在跑、画面停在起点（A/B 用离屏单帧，不跑播放）；
3. **小场景碰撞事件永不触发**：n<32 且无池时回调 0 次（A/B 不测脚本回调）；
4. **Qt 编辑器 UI 输入全失效**：清空早于分发（A/B 直接调 dispatch，绕过 Qt 时序）；
5. **物理建体写回 identity 旋转 / AABB 瞬移**：一进物理就"摆正/瞬移"（A/B 不跑物理）；
6. **撤销系统漏项**：材质/PBR/env/LOD/光源 range 改了不入栈（A/B 不测撤销）；
7. **插件沙箱逃逸**：与渲染无关。

## 3. 我（主 Agent）引入并修掉的回归（26 条）

| 模块 | 代表项 | 改前 → 改后 |
|---|---|---|
| VK 渲染 | 桶实例偏移、PBR 开关属性名、法线回落白纹理、env 缓存 id 键、文本 LRU 不 release | 2093 错像素 → 0；属性名 → `_pbr_enabled` |
| 播放器 | 贴图导入设置丢失、相机坏值崩溃、LOD 每帧全量重算且配置读不到、wheel 累积、覆盖库回调 | 512²/10 级 → 一致；2.201ms → 0.112ms |
| GL 光照 | P-17 守卫前提被证伪 | 6.468ms → 0.909ms |
| 构建 | `_launch_player` 文档失真、`--run` 无回退 | 实现 `LOOM_REMOTE_MODE`；Q6 策略 |

## 4. 人类裁决落地情况

| 题 | 裁决 | 落地 |
|---|---|---|
| Q1 插件沙箱 | A 安全边界 | 两条逃逸链堵死 + 攻击用例进回归 |
| Q2 聚光阴影 | A 支持 6 面 | 6 槽/灯 + 预算 16 降级 + 一次警告 |
| Q3 点光 C 路径 | A 删守卫 | 性能恢复 6.4ms/帧 |
| Q4 场景不可信 | B 否 | 不做全量防御，但成环拒绝（否则丢数据） |
| Q5 撤销覆盖 | A 全覆盖 | 快照扩到材质/PBR/env/LOD/range + Shape 分支 |
| Q6 后端 | A + 定制 | 默认 vk → 失败崩一次并写明"不兼容" → 写回 opengl → 下次能开 |
| Q7 多 Canvas | C 只吞空白 | `_hit_screen` 下探低层，全未命中才吞 |
| Q8 FPS 缓冲 | A 修 FBO | 预画重定向到离屏 + 深度附件 |
| Q3 删父 | A + 提示 | 连子树删 + Qt 确认框（N 个子物体，默认"否"） |

## 5. 仍未修（P2/P3 与遗留，按影响排序）

| # | 项 | 位置 | 影响 |
|---|---|---|---|
| 1 | `scene_driver._step_physics` 每帧打印桥异常 | scene_driver.py | 日志刷屏（P3） |
| 2 | `TransformComponent.scale` 直写短元组仍可绕过入口归一化 | loom_components.py | 极端写法下 IndexError（P3） |
| 3 | `GameObject.parent` 直写无环保护 | loom_game_object.py | 成环 → `collect_subtree` 递归（P2） |
| 4 | 插件残余：卸载不清 sys.modules、TOCTOU、once 重入、调度器若干 | plugin_loader / scheduler | P2/P3 |
| 5 | `_update_lod` 无 LOD 仍有 ~0.11ms/帧 扫描 | scene_driver.py | P3 性能 |
| 6 | `vk_ui.last_wheel_consumed` 语义偏、`game_player` 日志打印入参 | vk_ui / game_player | P3 |
| 7 | 多平行光阴影仅 1 张（VK 已知限制） | vk_renderer.py | 文档已声明 |
| 8 | Shape 描边非逐像素等价（已契约化 `STROKE_PIXEL_EQUIVALENT=False`） | vk_ui.py | 已知边界 |
| 9 | 离屏 Canvas（RenderTexture 型）未实现 | — | 功能缺口 |
| 10 | `tests/_tmp` 仍有 569 个历史受跟踪文件 | tests/_tmp | 仓库卫生 |

## 6. 验收方法（可复跑）

```
python tests/_tmp/ab_batch.py          # 22 场景 GL vs VK，门槛 MAE <= 0.0002
python tests/_tmp/ab_gl_vk_ui.py       # UI 场景，门槛 <= 1e-6
python tests/run_all.py                # 90 个测试文件，要求 exit=0
python tests/_tmp/probe_bucket_reorder.py   # 桶重排（修复前 2093 错像素）
python tests/_tmp/cam_align_probe.py        # 相机 VP 对齐（17 场景）
```

## 7. 最终统一回归结果（2026-11-07 收口）

| 验收项 | 结果 |
|---|---|
| `ab_batch.py` 22 场景 GL vs VK | **22/22 PASS**，最大 MAE 0.000082（门槛 0.0002） |
| `ab_gl_vk_ui.py` UI 场景 | **MAE 9e-8**（4/153600 像素差 1 LSB） |
| `run_all.py` | **exit=0**，91 个测试文件，0 FAIL |
| VK 真窗口 + UI 冒烟 | 正常，`bgra8unorm`，**101.7 FPS** |
| 桶重排探针 | 修复前 2093 错像素 → **修复后 0** |
| 相机对齐探针（17 场景） | `|ΔVP| = 0.000e+00` |

**结论**：9 个修复批次 + 4 个跨文件收尾全部落地；4 个 P0 全部修复并有回归用例；26 条自引入回归全部修复；
渲染像素级对齐与引擎行为正确性同时成立。

> 本文件为汇总，明细见 `_fix_ledger.md` 与各 `fix_*.md`。