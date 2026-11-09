# beta6 复核 第 02 轮：ab_gl_vk 受跟踪测试质量

> 角色：独立复核子代理（只读审计，不参与实现）
> 范围：`git diff 7c734e8..HEAD` 内的 `Loom/tests/test_ab_gl_vk.py`、`Loom/tests/ab_scenes/`（22 场景 + 2 贴图）、`Loom/tests/ab_gl_vk_baseline.json`
> 判定口径：白盒契约 / 黑盒实现 / 灰盒验证 / 人类掌舵；粗筛 → 双向推演（先证伪后证真）→ 四象限 → 探针闭环；8 段式逻辑链。
> **在途未定稿**：`tools/build_engine.py`、`Loom/build_entry.py`、`Loom/build_game.py`、`tools/package_engine*.py`、`使用操作指南.txt`（另有 `docs/audit/scan_beta3_05_*`）—— 与本轮结论无关，仅标注「疑似在途」。本轮**未**改动任何受跟踪文件。

---

## ① 范围与方法

| 项 | 内容 |
|---|---|
| 受审文件 | `tests/test_ab_gl_vk.py` 315 行；`tests/ab_gl_vk_baseline.json` 126 行；`tests/ab_scenes/*.json` 22 个（共 17.7 KB）+ `assets/{checker,normalmap}.png` |
| 契约来源 | 文件头 1-22 行（三指标判据 + 覆盖边界 + SKIP 契约）；`vk_ui.py:45-65`（R2 描边"非逐像素等价"契约）；`tests/run_all.py:26-40`（只收 `test_*.py`，只看子进程退出码）；`版本计划_Loom0.1.0.beta6_20261109.md:186/217/221`（把 `ab_gl_vk 不劣化` 写成批次 0/0.5 的验收门） |
| 实测命令 | 逐条见 7) 段；探针全部落在 `Loom/tests/_tmp/audit_b6_02_*.py` |
| 真实渲染口径 | GL 离屏 `moderngl.create_standalone_context(require=430)`（本机拿到 4.3，非 UNVERIFIED）；VK 走 wgpu 0.33.0 真实 adapter |
| 全量基线复现 | `py -3.13 Loom/tests/test_ab_gl_vk.py` → 22 场景全 PASS、失败 0、跳过 0、exit 0、耗时 **6.1 s**；逐场景 MAE/MAX/NCC 与基线文件逐位相同 |

**本轮不做的**：不改渲染实现、不评价 GL/VK 是否"应该"等价、不重定阈值（阈值口径属人类裁决，见 ⑥）。

---

## ② 粗筛清单（含跳过留痕）

| ID | 位置 | 标签 | 初步方向 |
|---|---|---|---|
| P-01 | `test_ab_gl_vk.py:296-306` | OVERFIT-ORACLE / SEM-SILENT | 闸门只比"GL vs VK 两端之间"，基线不存参考图 → 两端同样错时不可见 |
| P-02 | `:233-238, 266-267, 298` | SEM-SILENT / BND-EMPTY | `b is None` 直接放行；`load_baseline()` 异常吞成 `{}` |
| P-03 | `:281-286` | AUDIT-ASYMMETRY / SEM-SILENT | VK 侧任何异常 → SKIP + 退出码 0；GL 侧异常 → FAIL + 1 |
| P-04 | `:260-262` | BND-EMPTY / TOOL-CLI | 场景列表为空 → SKIP + 0 |
| P-05 | `:293-295, 307-309` | SEM-SILENT | `--update-baseline` 无条件 `return 0`，失败也写基线 |
| P-06 | `:241-252` | AUDIT-DEADCODE / AUDIT-DOCIMPL | 基线写入 `resolution`/`gate`/`generated`，代码从不读 |
| P-07 | `:221-230` | BND-OVERFLOW | NCC 用 float32 累加 → 实测 1.0000011（数学上不可能 >1） |
| P-08 | 文件头 22 行 + `:196-198` | AUDIT-DOCIMPL / TOOL-SCOPE | "UI 由 `ab_gl_vk_ui.py` 单独覆盖"——该文件只是打印指标的探针 |
| P-09 | `ab_scenes/*.json` | OVERFIT-GEN | 22 场景特征分布（透明/LOD/层级/正交/雾/自发光 全为 0） |
| P-10 | `ab_gl_vk_baseline.json` 全文 | TOOL-WHITELIST | 基线无哈希/来源绑定，字面篡改不可自动发现 |
| P-11 | `ab_scenes/ab_ui_scene.json:2` | IFACE-VERSION | `version: 21` vs 引擎 `SCENE_VERSION=10`，migrate 静默降级 |
| P-12 | `:38, 44-49` | — | 阈值是否过松 / 480×320 是否掩盖高分辨率差异（两条怀疑，需先证伪） |

**跳过登记表（跳过必须留痕）**

| SKIP | 位置 | 理由（可审计） |
|---|---|---|
| SKIP-01 | `render_vk:175-218` 每场景新建 `VkRenderer`/texture/buffer，buffer 未 `unmap/destroy`，GL context 未 `release()` | 超本轮 7 问范围；本机无显存/句柄计数器可量测 → 只在 ⑤ 记 P3 残余风险，本轮不裁决 |
| SKIP-02 | `loom_render.py:176-182` 每场景打印 `天空盒 读 depth 状态失败 (AttributeError: depth_mask)` | 已登记缺陷（版本计划 §5 R01「`ctx.depth_mask` 空操作」）；且 :183-187 的绘制分支与 `old_depth_mask` 无关 → 不改像素。不属本测试缺陷 |
| SKIP-03 | `tests/_tmp/ab_gl_vk_ui.py` 的 compare/PNG 逻辑 | 它不进任何闸门（P-08 已裁决"无阈值"），逐行审其图像处理不属"受跟踪测试质量" |
| SKIP-04 | `tests/_tmp/ab_batch.py` | 未受跟踪，不在文件范围 |
| SKIP-05 | `mae_drift`/`ncc_drift` 取值的跨驱动合理性 | 判据依赖第三方光栅化实现，本机只有一条证据 → 并入 U-02，不单独裁决 |

---

## ③ 逐项裁决（8 段式）

### P-01 · PROVED · P1 · 闸门只测"两端之差"，共享回归不可见

1. **判定基准**：文件头 4-17 行声明"GL/VK **逐像素** A/B，防回归"；`:15` "MAE <= 基线 + mae_drift 且 NCC >= 基线 - ncc_drift: 防回归"。
2. **代码证据**：`:287` `mae, mx, ncc = metrics(g, v)` —— 入参只有 `g`(GL 图) 与 `v`(VK 图)；`:288-292` 基线只存 `mae/max/ncc` 三个标量（`ab_gl_vk_baseline.json:14-124` 全文无图像、无哈希）。
3. **路径枚举**（一次运行的全部比较路径，穷举）：
   - 路径 a：`metrics(g, v)` → 只反映端间差；
   - 路径 b：`b = base_rows.get(name)` → 基线里存的是"历史的两端差"，不是历史图像；
   - 路径 c：`ok_max` 同样只比端间绝对差。
   三条路径都不接触"这一帧应该长什么样"的参考。故任何**同时改变两端**的因素（共享模块：`sceneio`、`matlib`、网格/顶点布局、材质参数、相机数学）在三路上均为零信号。
4. **预期**：契约说"防回归" → 共享模块回归应报警。
5. **实际**：不报。
6. **差异方向**：漏掉"两端一致地变错"这一整类，恰好是 beta6 批次 A 最可能的形态（D5 顶点布局 48→80B、FramePlan 迁移、`matlib` 共用）。
7. **可复现验证**：
```
$env:PYTHONIOENCODING='utf-8'; py -3.13 Loom/tests/_tmp/audit_b6_02_shared_regression.py
```
实测输出：
```
改前: MAE=6.846e-05 MAX=0.0745 NCC=0.99991035  (基线 MAE=6.846e-05)
共享 bug (两端 FOV 均 +15%): 两端之间 MAE=4.900e-05 MAX=0.0784 NCC=0.99993354 -> 闸门=PASS(漏报)
  但"改前 vs 改后"画面差异: MAE=2.334e-02 MAX=0.647  <- 这才是真回归的量级
```
做法：把 `matlib.mat4_perspective` 的 fov 统一放大 15%，模拟"改 `matlib.py` 一处、两端同时变"。改动量级 2.3e-2 是闸门绝对阈值 2e-4 的 **117 倍**，闸门仍 PASS，端间 MAE 还从 6.8e-5 **下降**到 4.9e-5。
8. **影响与等级**：P1。这是闸门的结构性定义问题，不是调参问题；调紧阈值无法解决。

### P-02 · PROVED · P1 · 基线缺失/损坏/场景名不在基线里 → 漂移闸门静默失效（黑画面可 PASS）

1. **判定基准**：文件头 15 行"MAE <= 基线 + mae_drift 且 NCC >= 基线 - ncc_drift: 防回归"；`:19` 只把"没装 wgpu"列为可跳过，未把"基线缺失"列为可跳过。
2. **代码证据**：`:233-238`
```
def load_baseline():
    try:
        with open(BASELINE_PATH, ...) as f: return json.load(f)
    except Exception:
        return {}
```
`:298`：`ok_drift = (b is None) or (mae <= b.get('mae', 0.0) + gate['mae_drift'] ...)`
3. **路径枚举**（`b is None` 的 4 条触发路径，全部实测）：① 基线文件不存在；② 文件存在但 JSON 损坏（:237 的裸 `except Exception`）；③ 场景新增/改名（`base_rows.get(name)` 为 None）；④ 曾经的 `--update-baseline` 丢了该场景（见 P-05）。四条路径下 `ok_drift` 恒 True，**NCC 这条唯一能识别"两端一起退化"的判据被整条旁路**。
4. **预期**：基线是判据的一部分，基线不可用应 FAIL 或至少非 0。
5. **实际**：静默降级为"只判绝对阈值"，且不打印任何"基线不可用"。
6. **差异方向**：少做一次判定，且不留痕。
7. **可复现验证**：
```
$env:PYTHONIOENCODING='utf-8'; py -3.13 Loom/tests/_tmp/audit_b6_02_gate_logic.py
```
实测（合成注入：两端都返回全黑图）：
```
黑/黑 指标: MAE=0.00e+00 MAX=0.0000 NCC=0.00000000
FAIL s0.json  MAE=0.000000 MAX=0.0000 NCC=0.000000 (基线 0.000001)  mae_abs=True drift=False max=True
  -> C1 黑/黑 + 有基线        rc=1 fails=1 skips=0
PASS s0.json  MAE=0.000000 MAX=0.0000 NCC=0.000000
  -> C2 黑/黑 + 基线文件缺失   rc=0 fails=0 skips=0
  -> C4 黑/黑 + 场景不在基线里 rc=0 fails=0 skips=0
  -> C4b 黑/黑 + 基线是别的场景名 rc=0 fails=0 skips=0
load_baseline() 返回: {}
  -> C8 黑/黑 + 基线 JSON 损坏 rc=0 fails=0 skips=0
```
即：**"两后端都画黑"在有基线时被 NCC 挡住（C1，rc=1），但四条基线旁路下全部 PASS（rc=0）**。
8. **影响与等级**：P1。三条旁路（新增场景 / clean clone 基线缺失 / 基线损坏）都在正常运维里出现。

### P-03 · PROVED · P1 · VK 侧任何异常 = SKIP + 退出码 0，无法区分"没设备"与"VK 后端坏了"

1. **判定基准**：文件头 19 行"无 GPU / 无 Vulkan 时打印 SKIP 并以 0 退出（不把'没装 wgpu'当成渲染回归）"——契约只豁免"没装 wgpu"；同时设计计划 :186/:217/:221 把 `ab_gl_vk 不劣化` 写成升级验收门。
2. **代码证据**：`:281-286`
```
try:
    v = render_vk(data)
except Exception as e:
    _skips.append(name)
    print('SKIP %s VK 不可用: %r' % (name, e))
    continue
```
`:311` `return 0 if not _fails else 1` —— `_skips` 不参与退出码。
3. **路径枚举**：`render_vk` 体内所有失败点落进同一个 `except Exception`：① `import wgpu` 失败；② `request_adapter_sync` 返回 None；③ wgpu 升级导致 API 改名（AttributeError/TypeError）；④ `VkRenderer.draw_frame` 内部真 bug；⑤ `copy_texture_to_buffer` 参数错。**五条路径在退出码上完全同形**。
4. **预期**：只豁免"环境不具备"（②，且应由 import/adapter 判定），③④⑤ 属代码回归应 FAIL。
5. **实际**：③④⑤ 全变 SKIP，exit 0，`run_all.py:35` 判绿。
6. **差异方向**：把"代码坏了"报成"机器没装"——正是本仓其它测试反复防范的假绿（`test_agent_commands.py:22`、`test_eai_color_parse.py:11` 的注释）。
7. **可复现验证**：`audit_b6_02_gate_logic.py` 用例组 5：
```
SKIP s0.json VK 不可用: RuntimeError('no adapter')
  -> C9a VK 报错(全部场景) -> 跳过    rc=0 fails=0 skips=1
FAIL s0.json GL 渲染  RuntimeError('GL ctx fail')
  -> C9b GL 报错(全部场景)            rc=1 fails=1 skips=0
```
同一份代码：GL 侧同款失败 → rc=1；VK 侧 → rc=0。22 场景全 skip 时输出只有一行"跳过 22"，退出码 0。
8. **影响与等级**：P1。wgpu 0.32→0.33、PySide6 6.12 都走这条路径；无 Vulkan 的机器上该验收永远"通过"。

### P-04 · PROVED · P2 · 空场景集 = SKIP + 退出码 0

1. **判定基准**：文件头未声明"没有场景文件"可接受；覆盖边界声明 22 场景。
2. **代码证据**：`:260-262` `if not files: print('SKIP 没有场景文件'); return 0`；`:92-97` `names = [s.strip() for s in sel.split(',') if s.strip()]`。
3. **路径枚举**：`_scene_files()` 返回空的 3 条路径：① `ab_scenes/` 不存在/被清空（glob 无匹配）；② 命名约定变更（不再 `ab_*.json`）；③ `LOOM_AB_SCENES=','`（只含分隔符 → `names=[]`）。三条都 rc=0。
4. **预期**：跑 0 个场景应视为"未验证"而非"通过"。
5. **实际**：SKIP + rc=0。
6. **差异方向**：0 场景与 22 场景全 PASS 退出码相同。
7. **可复现验证**：`audit_b6_02_env_bypass.py`
```
SKIP 没有场景文件 (...\Loom\tests\ab_scenes)
LOOM_AB_SCENES=',' -> _scene_files()=[]  rc=0
LOOM_AB_SCENES=' , ' -> _scene_files()=[]  rc=0
LOOM_AB_SCENES='' -> (回落 glob, 22 场景) rc=0
未设置 -> 场景数 22
```
（另见 `audit_b6_02_gate_logic.py` 用例 `C5 空场景列表(无文件) rc=0`。）
8. **影响与等级**：P2。需人为失误才触发，但触发后无任何痕迹。

### P-05 · PROVED · P1 · `--update-baseline` 失败也 rc=0，且会把基线写空/写小（自毁 + 侵蚀）

1. **判定基准**：文件头 9 行"`--update-baseline` 重写基线快照（只在有意变更时用）"隐含"基线可信"；本仓通用约定见 `test_agent_commands.py:22`（出现 FAIL 必须非 0）。
2. **代码证据**：`:293-295` `if update: print('BASE ...'); continue`（不记录 _fails）；`:307-309` `if update: save_baseline(gate, rows); return 0`；`:241-252` `rows` 只含**本次渲染成功**的场景。
3. **路径枚举**（update 模式全部出口）：a) 全成功 → 全量写；b) GL 失败（`:278-280` `continue`）→ 该场景不入 rows，其余照写，rc=0；c) VK 失败（:284-286）→ 同上；d) 全失败 → rows={} → 写入"0 场景"基线，rc=0。四条路径退出码全 0。
4. **预期**：写基线前应要求全部场景成功；失败必须非 0。
5. **实际**：d) 打印两行 FAIL 后仍 rc=0，并把基线覆盖成空。
6. **差异方向**：一次"刷新基线"即可把门禁永久降级（空基线 → 全部走 P-02 旁路）。
7. **可复现验证**：`audit_b6_02_update_mode.py`
```
FAIL A.json GL 渲染  RuntimeError('GL 4.3 上下文不可用')
FAIL B.json GL 渲染  RuntimeError('GL 4.3 上下文不可用')
[基线] 已写入 ...\base.json (0 场景)
  rc=0  fails=['A.json GL 渲染', 'B.json GL 渲染']
---
BASE A.json MAE=0.000000 MAX=0.0000 NCC=0.353043
[基线] 已写入 ...\base.json (1 场景)
  rc=0  基线里的场景=['A.json']        # 原有 B 的漂移锚点被静默删除
```
8. **影响与等级**：P1。这是"基线被误改"的唯一现实入口（问题 ⑦ 的正面回答）。

### P-06 · PROVED · P3 · 基线里 `resolution` / `gate` / `generated` 只写不读

1. **判定基准**：`:245-247` 写入三字段，语义上是"基线自描述"。
2. **代码证据**：全文件检索三个字段各只出现 1 次（:245/:246/:246）；`_gate()`(:61-70) 只读 `DEFAULT_GATE` + 环境变量，从不读基线。
3. **路径枚举**：基线唯一入口 `load_baseline()`(:233) → `base.get('scenes')`(:267) → 只有 :296-300 用 `b.get('mae'/'ncc'/'max')`。三字段无消费者。
4. **预期**：基线应能自证"这份数字在什么分辨率、什么阈值下产生"。
5. **实际**：字段是死的；把 `W,H=480,320`(:38) 改成别的分辨率，旧基线照样被当同口径比较。
6. **差异方向**：少一次口径一致性校验（分辨率/阈值不匹配不报警）。
7. **可复现验证**：`audit_b6_02_update_mode.py` 用例 U4 原样打印：
```
resolution   出现 1 次; 出现行: ["        'resolution': [W, H],"]
'gate'       出现 1 次; 出现行: ["        'gate': gate,"]
generated    出现 1 次; 出现行: ["        'generated': '2026-11-09',"]
```
8. **影响与等级**：P3。当前阈值恰好一致，无数值影响；但它是"审计者读基线会得到错误信心"的来源（AUDIT-DOCIMPL）。

### P-07 · PROVED · P3 · NCC 用 float32 累加 → 实测 >1（数学上不可能）

1. **判定基准**：NCC（零均值相关系数）按 Cauchy–Schwarz 必 ≤1；基线文件里却有 `1.00000107`(:23)、`1.00000131`(:48)、`1.00005174`(:53)。
2. **代码证据**：`:225-229` `la = a.mean(axis=2).ravel()`（float32）→ `la = la - la.mean()`（仍 float32）→ `(la*lb).sum()` 在 float32 上做 153600 元素归约。
3. **路径枚举**：`metrics()` 只有一条路径（无分支），跨 dtype 差异全部来自累加精度。
4. **预期**：同一对图 float64 计算应 ≤1。
5. **实际**：float32 → 1.000001073。
6. **差异方向**：+1.07e-6，等于 `ncc_drift`(1e-4) 的 1.1%。
7. **可复现验证**：`audit_b6_02_ncc_dtype.py`
```
a.mean(axis=2).dtype = float32
metrics() 现实现 (float32 累加) NCC = 1.000001073  -> >1 ? True
同一对图 float64 计算        NCC = 0.999999999  -> >1 ? False
差值 = 1.074e-06  (阈值 ncc_drift=1e-4 的 1.1%)
```
8. **影响与等级**：P3。当前不影响判定，但它是 `ncc_drift` 不能收紧到 1e-6 量级的硬上限。

### P-08 · PROVED · P2 · UI 等价"有独立覆盖"的说法不成立（无闸门）

1. **判定基准**：文件头 22 行"UI 不在本闸门内 —— UI 等价由 `ab_gl_vk_ui.py` 单独覆盖"；:196-198 再次声明。
2. **代码证据**：`tests/_tmp/ab_gl_vk_ui.py:242-247` —— `return compare(...)` 只 print；`if __name__=='__main__': main()` 不 `sys.exit`；`run_all.py:26` 只收 `test_*.py`（该文件名不符）。阈值只存在于文档（`handoff/接手总纲:215` "<=1e-6"），代码里没有。
3. **路径枚举**：a) run_all（121 测试）→ 不收集；b) `test_vk_ui_stroke.py` → 只锁 CPU 级 op 几何（:64-66 锁 `STROKE_PIXEL_EQUIVALENT=False`、`triangle-band`），不比像素；c) 人工跑 `ab_gl_vk_ui.py` → 只看到数字，无机判定。三条路径都不构成闸门。
4. **预期**：契约说"单独覆盖" → 应存在"失败即非 0"的判定。
5. **实际**：不存在。
6. **差异方向**：覆盖声明 > 实际覆盖（AUDIT-DOCIMPL）。另：`ab_ui_scene.json` 虽在 22 场景里，但本闸门不画 UI。
7. **可复现验证**：`audit_b6_02_vacuity.py`
```
ab_ui_scene.json       清空 ui 段   画面变化 MAE=0.000e+00 MAX=0.000  (0=该特性对画面无影响)
```
对照：同一探针里 `ab_tex` 去 albedo → MAE=4.75e-3、`ab_sky` 去天空 → 3.79e-2，说明探针有区分力，`ab_ui_scene` 的 0 是真空。
8. **影响与等级**：P2。R2 描边残差（MAE 3.6e-3/6.8e-3）是**已裁决的非等价**，所以 UI 不能拿本闸门的 2e-4 去卡；但"完全无自动闸门"与"有闸门但给配额"是两件事，后者不存在。

### P-09 · PROVED · P2 · 22 场景特征分布（问题 ④ 的正面回答）

1. **判定基准**：文件头 21 行"覆盖边界（与历史口径一致, 不得悄悄扩大）: 3D 部分（几何/着色/光照/阴影/天空/贴图）"；设计计划把批次 A 定为 FramePlan + tonemap。
2. **代码证据**：见 7) 的矩阵脚本（从 JSON 键与值直接统计，不靠印象）。
3. **路径枚举**：22 场景 × 22 类特征全覆盖枚举（不是抽样）。
4. **预期**：若"阴影/天空/多光/贴图/透明"都在宣称范围内，每类至少 1 个场景。
5. **实际**：见 7) 表。
6. **差异方向**：见"缺口"列。
7. **可复现验证**：`audit_b6_02_scene_matrix.py`（完整输出见脚本）

| 特征 | 命中场景数 | 缺口 |
|---|---|---|
| 方向光 | 19 | — |
| 点光 | 5 | — |
| 聚光 | **1**（`ab_c_spot_only`） | 聚光+阴影、聚光+多光 无 |
| ≥2 光源 | 3 | 三光/四光 无 |
| 阴影开 | 10 | 点光 6 面阴影仅 1 个场景 |
| skybox | **1**（`ab_sky`） | 六面图各面朝向 无独立场景 |
| env/IBL | 2 | — |
| albedo 贴图 | **1**（`ab_tex`） | 多贴图/平铺 wrap/各向异性 无 |
| 法线贴图 | **1**（`ab_nrm`） | — |
| pbr | 3 | — |
| 透明/alpha | **0** | 全无 |
| LOD | **0** | 全无 |
| 父级/层级 | **0** | 全无（`parent_id` 未被任何夹具覆盖） |
| 相机实体 / 正交投影 | **0 / 0** | 全无 |
| 雾 / 自发光 | **0 / 0** | 全无 |
| HDR / tonemap | **0** | 引擎尚无（计划批次 A 才加） |
| UI | 1（不进闸门，见 P-08） | — |

另：22 个场景里 19 个是"1 个方向光 + 1~3 个基础体"；`ab_c_spot_only` 与 `ab_cube` 的基线 MAE 恰为 `0.0`（baseline:35-43），属低信息量但有效的基准点。
8. **影响与等级**：P2。代表性问题不在"缺 HDR"（还没实现），而在**透明、层级、正交投影、LOD 四个已实现特性 0 覆盖**——它们都有在改的代码面（批次 C 动画要动层级，beta3 动过正交投影）。

### P-10 · PROVED · P2 · 基线无哈希/来源绑定

1. **判定基准**：`:243-247` 写入 `generated`（是死字符串 '2026-11-09'，不是生成时刻）、无 sha256、无 git rev、无场景文件指纹。
2. **代码证据**：`save_baseline():241-252` 全文；`ab_gl_vk_baseline.json:1-13` 头部。
3. **路径枚举**：a) 手改 JSON 数字（如把 `mae: 7.084e-05` 改成 `1e-3`）→ :298 直接采信；b) 场景 JSON 改了但基线没重生成 → 无检测；c) 基线由别的分辨率/别的驱动生成 → 无检测（P-06）。三条路径均无守卫。
4. **预期**：基线是判据的一部分，应与"场景内容 + 生成环境"绑定。
5. **实际**：裸 JSON 数字。
6. **差异方向**：少一层完整性绑定，任何"闸门为什么会绿"都无法回溯。
7. **可复现验证**：
```
git diff --stat HEAD -- Loom/tests/ab_gl_vk_baseline.json
Select-String -Path Loom/tests/ab_gl_vk_baseline.json -Pattern 'sha|hash|rev|commit'
```
第二条命令**零命中**（126 行里没有任何指纹字段）。
8. **影响与等级**：P2。现状靠 review 兜（基线受跟踪，改动进 diff）；风险在"一次 --update-baseline 顺带改动"（P-05 已证明可静默破坏）。

### P-11 · UNKNOWN · P3 · `ab_ui_scene.json` 的 `version: 21` 被静默降级

1. **判定基准**：`sceneio.py:57` `SCENE_VERSION = 10`；设计计划 D7（:131）要把版本升到 11 并加 `min_engine_version`「旧引擎明确拒绝新场景」。
2. **代码证据**：`sceneio.py:1471-1532` —— `v = data.get('version', 1)`，之后全是 `if v < N`；v=21 时全部跳过，末尾 `data['version'] = SCENE_VERSION`(:1531) → 21 被改写成 10，无任何提示。
3. **路径枚举**：v=21 的加载路径只有这一条（`migrate()` 无 `else`、无 `v > SCENE_VERSION` 分支）。
4. **证伪尝试**：实测该场景能加载并参与闸门（`PASS ab_ui_scene.json MAE=0.000082`），且清空 ui 段画面零变化（P-08）→ **对当前像素结论无影响**（这部分证伪成功）。
5. **证真尝试**：无法构造"v21 字段被错误解释"的最小复现——该文件 `ui.canvases` 结构在当前 `_apply_ui` 下能正常恢复（UI 探针曾用它产出 MAE 9e-8）。
6. **为什么仍是 UNKNOWN**：这份夹具来自**别的 schema 世代**（其余 21 个都是 10），仓库内证据无法判断 v21 字段语义是否与 v10 同构；一旦 D7 落地 min_engine_version，v21 会被新门禁**拒绝**，该场景会从 PASS 突然变加载失败。
7. **还需要什么信息才能定**：① 该夹具的原始出处（哪个项目/哪次导出）；② D7 落地时对 `version > SCENE_VERSION` 的处置方向（拒绝 / 尽力加载）。两者都不在仓库里。
8. **影响与等级**：P3，且与 D7 耦合。

### P-12 · DISPROVED · "阈值过松"与"480×320 掩盖高分辨率差异"（问题 ②⑥ 的证伪）

1. **判定基准**：`DEFAULT_GATE`(:44-49)：MAE≤2e-4 绝对、MAE≤基线+5e-5、NCC≥基线-1e-4、MAX≤max(0.2, 基线MAX+0.03)。
2. **代码证据**：`:297-300` 三条判据都是 AND；`:38` `W,H=480,320`。
3. **路径枚举**：基线存在时 `mae_drift` 几乎总是**更紧**的一条（基线最大 8.2e-5，+5e-5=1.3e-4 < 2e-4）→ "绝对 2e-4"只在基线缺失时生效（P-02）。真实有效预算 = 基线+5e-5。
4. **证伪 ①（松紧量化）**：完全错的区域面积 N 在误差 d 下需 `3·N·d ≤ 预算·460800`，且 `d ≤ 0.2`：
   - 一般场景（绝对阈值）：d=0.2 → N ≤ 153 px（0.1% 画面）；d=0.1 → N ≤ 307 px；d=0.05 → N ≤ 614 px；
   - 零基线场景（mae_drift 生效，预算 5e-5）：d=0.2 → N ≤ 38 px（0.025% 画面）。
   实测印证（用例组 4，40×40=1600 px 方框）：
```
局部  40px 方框 delta=0.15 -> MAE=5.21e-04 MAX=0.150 NCC=0.99981755 闸门=FAIL
局部 400px 方框 delta=0.10 -> MAE=8.33e-03 MAX=0.100 NCC=0.99886447 闸门=FAIL
```
→ 阈值**不松**（1600 px 就红）。**证伪成功**。
5. **证伪 ②（分辨率）**：同一场景 480×320 vs 960×640（4 倍像素）实测：
```
ab_plane_shtrue   MAE 8.510e-09 -> 1.277e-08   MAX 0.0039 -> 0.0039
ab_plane_sphere   MAE 5.189e-05 -> 5.048e-05   MAX 0.0784 -> 0.0863
ab_point_shadow   MAE 6.264e-05 -> 6.305e-05   MAX 0.1255 -> 0.1373
ab_scene          MAE 6.846e-05 -> 6.714e-05   MAX 0.0745 -> 0.0824
ab_sky            MAE 1.745e-05 -> 1.789e-05   MAX 0.0510 -> 0.0745
```
MAE 与分辨率**无关**（五个场景全部同量级，无一项超闸门）；MAX 随分辨率单调上升，说明 MAX 是"边缘/AA 计数"型指标、不是回归指标（文件头 17 行已声明不作逐像素判据）。**"480×320 掩盖高分辨率差异"证伪成功**。残余：MAX 的 0.2 上限是在 480×320 上标定的，若将来调大 W,H，`ab_sky` 的 0.0745 会继续逼近 0.2 —— 见 ⑥。
6. **证伪 ③（场景是否空壳）**：突变测试（关掉该场景宣称的特性，看画面动不动）：
```
ab_tex  去 albedo      MAE=4.750e-03 MAX=0.502
ab_nrm  去 normal_map  MAE=1.047e-03 MAX=0.063
ab_env  去 env/skybox  MAE=2.362e-02 MAX=0.671
ab_pbr  pbr=False      MAE=8.527e-03 MAX=0.549
ab_sky  去 skybox      MAE=3.793e-02 MAX=0.125
ab_point_shadow shadow=False MAE=1.145e-03 MAX=0.165
```
六个特性场景全部有区分力。唯一例外是 `ab_ui_scene` 的 ui 段（P-08）。
7. **证伪 ④（绝对 _tmp 路径破坏干净 clone 复现）**：`_rebase_paths():73-89` 只在"原路径不存在"时重定向。本机 `tests/_tmp/{checker,normalmap}.png` 存在 → 本机走"原样保留"，CI 走"重定向"。实测两路等价（见下），且 SHA256 同值（`13430B64…` / `CFE0D32A…`）。**证伪成功**；但机制是"两份文件碰巧同字节"，无哈希校验（P-10）。
```
ab_tex.json 干净clone路径 -> ...\tests\ab_scenes\assets\checker.png
  本机路径 vs 重定向路径 画面差: MAE=0.000e+00 MAX=0.000  (0=等价)
ab_nrm.json 干净clone路径 -> ...\tests\ab_scenes\assets\normalmap.png
  本机路径 vs 重定向路径 画面差: MAE=0.000e+00 MAX=0.000
```
8. **证伪 ⑤（提升时丢场景）**：`Compare-Object` 实测 `tests/_tmp/ab_*.json` 与 `tests/ab_scenes/ab_*.json` 同名同大小 22 vs 22，无差异。**证伪成功**。
9. **影响与等级**：三条怀疑全部证伪；真正的问题是 P-01（口径）而非阈值松紧。记录用 P3。

---

## ④ 统计

| 判定 | 数量 | 编号 |
|---|---|---|
| P-PROVED | **10** | P-01 ~ P-10 |
| P-DISPROVED | **6** | P-12 内含 5 条证伪链（阈值松紧/分辨率/空壳/绝对路径/场景集），第 6 条：**"有基线时黑/黑会被 NCC 挡住"**（`audit_b6_02_gate_logic.py` 用例 C1 → `rc=1 drift=False`，是该闸门唯一有效的自检） |
| P-UNKNOWN | **3** | U-01 = P-11（v21 夹具）；U-02 基线跨驱动可复现性；U-03 R06 接受口径 `0.0021/0.2353/0.9741` 来源 |
| P-CONTRADICTION | **0** | 无。解释：所有"两边都说成立"的候选都被单边证据打破（例如"阈值松"被 1600 px 就红打破），未出现两条链同时成立 |

**U-02（跨驱动）**：22 个基线里 8 个 `mae` 恰为 0，对应 `mae_drift` 预算只有 5e-5；在另一块 GPU/另一个 Vulkan 驱动上，光栅化 tie-break 差异（`vk_ui.py:60-62` 已记录"1px 水平线 GL 画 row20 / VK 画 row19"这种真实驱动差）是否会把 0 变成 >5e-5 —— 本机只有一条证据，**无法证伪也无法证真**。需要第二块 GPU（或第二版驱动）跑同一命令对照。

**U-03（R06 接受口径不可复现）**：`research_beta6_06_toolchain_upgrade.md:377/406` 把 `ab_gl_vk` 的验收数写成 `MAE=0.0021 / MAX=0.2353 / NCC=0.9741`，并注"0.0021 本就 > 2e-4，门禁按'不劣化'解读"；而受跟踪闸门 22 个场景实测最差 `MAE=8.229e-05`、最差 `MAX=0.1255`。0.0021 是受跟踪最差值的 25 倍，0.2353 还超过 MAX 上限 0.2。仓库内找不到生成该三元组的命令或场景集（全仓 grep 只命中这两行）。**先证伪**：不是这 22 个场景的任一单场景，也不是它们的和（和 ≈5.2e-4）。**先证真**：无法构造。→ UNKNOWN，需人类回答 ⑥ Q3。

**本轮正面结论（同样留痕）**：
- 闸门在本机**确定性**：22/22 与基线逐位复现（MAE/MAX/NCC 到 6 位小数完全一致），耗时 6.1 s，可进 121 测试循环。
- "两后端都画黑"在有基线的场景上**不会**骗过闸门（NCC=0 < 0.9999 → FAIL）—— 这是它最有价值的一道防线。
- 六个特性场景全部有区分力（突变测试），不是摆设。
- 480×320 不掩盖高分辨率差异（960×640 实测同量级）。

---

## ⑤ 修复建议排序（只给方向，不含代码）

| 优先级 | 条目 | 方向 |
|---|---|---|
| **P1-1** | P-01 共享回归不可见 | 补"对参考图"的一层：基线里存每场景 GL 参考图的哈希（如 8×8 感知哈希）并判 `hash(g)` 是否等于基线；端间差照旧判。这样"两端一起错"才会红 |
| **P1-2** | P-02 基线旁路 | `load_baseline()` 区分"缺失/解析失败/版本不符"三种，任一即 FAIL；`b is None` 只在"该场景首次入库"时允许，并打印可被 grep 审计的"无漂移锚点"警告行 |
| **P1-3** | P-03 SKIP 语义 | SKIP 拆两级：`SKIP-ENV`（import wgpu 失败 / adapter=None，仅这两条）→ 0；其它异常 → FAIL。总结行输出 `跳过 N/TOTAL`，且 `N == TOTAL` 时返回非 0（"未验证"≠"通过"） |
| **P1-4** | P-05 更新基线 | update 模式要求"全部场景渲染成功"才落盘；有失败则非 0 且**不覆盖**原基线；落盘前校验场景数不少于上次，减少则非 0（防侵蚀） |
| P2-1 | P-08 UI | 要么把 `ab_gl_vk_ui.py` 提升为 `test_ab_gl_vk_ui.py` 并给 R2 契约对应的配额阈值（如 MAE ≤ 8e-3 且不劣化基线），要么把文件头 22 行的"单独覆盖"改成"仅人工探针，无闸门" |
| P2-2 | P-09 场景缺口 | 补 4 个已实现特性场景：透明/alpha、父子层级、正交投影、LOD；每个先跑一次 `--update-baseline` 认领基线（注意 P-05） |
| P2-3 | P-10 基线绑定 | 基线头部加 `scene_hashes`（每场景 JSON 的 sha256）+ `engine_git_rev` + `generated_at`；场景改了没重生成基线 → FAIL。顺带让 P-06 三个死字段有消费者（分辨率不符即 FAIL） |
| P3-1 | P-07 NCC | `metrics()` 里把灰度图 `.astype(np.float64)` 再做零均值与归约；否则 `ncc_drift` 永远不能低于 1e-5 量级 |
| P3-2 | SKIP-01 资源 | `render_vk` 末尾 `buf.unmap(); buf.destroy()`；`render_gl` 末尾 `ctx.release()`（22 场景当前无失败，属卫生问题） |
| P3-3 | P-11 夹具 | 把 `ab_ui_scene.json` 的 `version` 改成 10（或注明来源），避免 D7 落地时被 `min_engine_version` 拒绝 |

---

## ⑥ 需人类裁决的封闭问题（每条选 A/B）

**Q1（P-01：闸门定义口径）** —— `ab_gl_vk` 到底承诺什么？
- **A（现状）**：只承诺"GL 与 VK 两端互相等价"。共享模块回归、两端一起退化**不在承诺内**，该风险由别的机制承担（哪一个？）。
- **B（扩展）**：承诺"渲染画面不回归"，即引入对参考图的比较（基线存参考图哈希）。代价：每改一处共用的着色/几何/相机代码都要重生成基线，基线体积与维护成本上升。

**Q2（P-03：SKIP 契约）** —— 没有 Vulkan 的机器上跑 `ab_gl_vk` 应该是什么结果？
- **A（现状）**：22 场景全 SKIP、退出码 0（"机器不支持"不算失败）。
- **B（收紧）**：全 SKIP 即非 0，并在 run_all 输出里明确"渲染等价未验证"。代价：无 Vulkan 的 CI/开发机会红，需要显式白名单（如 `LOOM_AB_ALLOW_SKIP=1`）放行且留痕。设计计划 :186/:217/:221 已把 `ab_gl_vk 不劣化` 写成验收门 —— 若选 A，这条门在无 VK 机器上**不可能失败**，需确认可接受。

**Q3（U-03：验收数字来源）** —— `research_beta6_06` 里 `ab_gl_vk = 0.0021 / 0.2353 / 0.9741` 是哪条命令、哪个场景集产出的？受跟踪闸门复现不出这组数（最差 8.2e-5 / 0.1255）。
- **A**：该三元组来自**另一件**制品（实时窗口截屏 / ab_batch.py / UI 版探针），应在报告里注明来源并保留命令。
- **B**：该三元组是受跟踪闸门某次旧基线时代的读数，下一次验收应改用受跟踪闸门的逐场景数值，并把 0.0021 标注作废。

---

## 附：本轮探针清单（全部在 `Loom/tests/_tmp/`）

| 文件 | 用途 |
|---|---|
| `audit_b6_02_gate_logic.py` | 合成图像注入闸门：黑/黑、基线缺失/损坏/改名、空场景、SKIP、局部差异扫描 |
| `audit_b6_02_update_mode.py` | `--update-baseline` 的退出码与基线侵蚀 |
| `audit_b6_02_real_render.py` | 真实渲染 3 场景：指标复现 + 图像统计 + 耗时 |
| `audit_b6_02_resolution.py` | 480×320 vs 960×640 |
| `audit_b6_02_scene_matrix.py` | 22 场景 × 22 特征矩阵 |
| `audit_b6_02_vacuity.py` | 特性突变测试（场景是否有区分力） |
| `audit_b6_02_shared_regression.py` | 共享模块回归（matlib fov）是否可见 |
| `audit_b6_02_rebase.py` | 干净 clone 的贴图重定向等价性 |
| `audit_b6_02_ncc_dtype.py` | NCC 的 float32 精度 |
| `audit_b6_02_env_bypass.py` | `LOOM_AB_SCENES` 环境变量降级 |

所有探针**不改任何受跟踪文件**、不 `git add/commit/checkout/stash`；`git status --porcelain` 复核后受跟踪改动集合仍 = 任务书列出的在途文件集合（`Loom/build_entry.py`、`Loom/build_game.py`、`tools/package_engine*.py`、`使用操作指南.txt`、`docs/audit/scan_beta3_05_*`，均「疑似在途」，不计入本轮结论）。
