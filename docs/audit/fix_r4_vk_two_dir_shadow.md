# R4 — VK 双平行光阴影贴图（2 张）修复报告

- 日期: 2026-11-07
- 批次: **R4 (vk_multi_shadow)**
- 生产改动: `vk_renderer.py`（唯一一个生产文件）
- 新增测试: `tests/_tmp/probe_two_dir_shadow.py`（GL vs VK 像素口径）,
  `tests/test_vk_two_dir_shadow.py`（CPU 槽位/布局断言, `run_all` 自动收集）
- 既有测试同步: `tests/test_vk_bucket_order.py` 第 7 段（原因见 §5）
- 本报告: `docs/audit/fix_r4_vk_two_dir_shadow.md`

---

## 1. 缺陷（改前）

VK 后端只有 **1 张平行光阴影贴图**（`_shadow_tex/_shadow_view` 单张 1024² r32float）：

- `_pack_light_vps` 把**每盏**投影平行光的 VP 都收进 `_light_vps`；
- 阴影 pass 只把「第一个 4x4 光 VP」烘进唯一一张贴图；
- 主 pass 却把每盏灯**各自的 ortho** 写进场景块。

结果：第 2 盏开阴影的平行光会拿第 1 盏的贴图 + 自己的 ortho 做 PCF —— 阴影位置错
（不是崩溃），属于裁决 A 记录在模块 docstring 里的已知限制。

## 2. 改法（只动 vk_renderer.py）

1. **第二张贴图**：`_SHADOW_SLOTS = 2`（49 行）；`_ensure_scene` 里新增
   `_shadow_tex2/_shadow_view2`（1024² r32float，与第 1 张同参数，采样器共用），
   见 863-872 行。
2. **binding 10/11（同一个 bind group）**：主 BGL 增加
   - `binding 10` = `texture_2d<f32>` / `unfilterable-float`
   - `binding 11` = `non-filtering` sampler
   （760-763 行）；`_scene_group`（941-942）与所有 `_tex_group`（1468-1469）
   都绑定 `_shadow_view2` / `_shadow_sampler`。**没有新增 bind group**。
3. **着色器按槽位选图**：fragment 新增 `t_shadow2/s_shadow2`（141-142）与
   `pcf2`（158-169）；平行光阴影分支读 `LightX.params.w`（284-296）：
   `-1` -> 不采样任何图（无阴影）；`<0.5` -> `pcf`（槽 0）；否则 `pcf2`（槽 1）。
   全程**没有动态纹理数组索引**。
4. **槽位分配**：`_pack_light_vps` 按灯序给前 2 盏投影平行光分配 `guid -> 0/1`
   （1645-1646），第 3 盏及以后不分配；所有平行光 VP 仍保留（beam 截面要用 ortho）。
5. **场景块**：`_pack_scene` 写 `params.w` = 槽位号（平行光 0/1/-1；点光/聚光保持 0，
   不参与），见 1717-1719。
6. **阴影 pass 按槽位各烘一张**：`draw_frame` 用 `_dir_maps` 按槽位循环
   （1810-1818、1868-1894）；每槽位独立 uniform 缓冲 `_dir_shadow_bufs`
   （797-806）与独立实例缓冲 `_inst_sha_buf / _inst_sha_buf2`（1559），
   避免同一 encoder 内「先写后提交」互相覆盖（与点光 6 面同一处理）。
7. **警告文案**：只有 `n_dir > 2 或 n_pt > 1` 才打一次（1621-1656），文案改为
   「只有 2 张平行光阴影 + 1 套点光 6 面」。

## 3. 核对项 1：两张图的 binding 与「单组」约束

| 槽位 | 纹理 binding | 采样器 binding | 资源 |
|------|--------------|----------------|------|
| 0 | **1**（沿用） | **2**（沿用） | `_shadow_tex / _shadow_view` 1024² r32float |
| 1 | **10**（新增） | **11**（新增） | `_shadow_tex2 / _shadow_view2` 1024² r32float |

- 现有 0/1/2/3/5/6/7/8/9 全部未动；10/11 原本空闲，无冲突。
- 两张图与两个采样器都在 **`@group(0)` 的同一个完整 bind group** 里：
  每个 draw 仍只调用一次 `rp.set_bind_group(0, group, [], 0, 1)`，主管线
  pipeline layout 仍是**一个** BGL —— 满足「同一时刻只绑一个完整 bind group」。
  证据：`tests/test_vk_two_dir_shadow.py` 的 A2/A3/A4/A5（用假 device 抓 BGL：
  绑定集合 = {0,1,2,3,5,6,7,8,9,10,11}，pipeline layout 长度 = 1）。
- 没有动态纹理数组索引（A9 断言）。

## 4. 核对项 2：第 3 盏及以后 =「打印一次警告 + 该灯无阴影」

**明确结论**：不是静默无阴影，也不是拿错图；是 **stdout 打印一次警告 + 该灯无阴影**。

- CPU 证据（`test_vk_two_dir_shadow.py` C 段）：3 盏投影平行光 -> 槽位只有
  `{a:0, b:1}`，第 3 盏 `params.w = -1.0`，警告恰好 1 条；再打包一次不再打印。
- GPU 实测（3 盏投影平行光，第三盏 `shadow=True` vs `shadow=False`，同一场景）：

```
3 灯 shadow=True : 槽位=[0, 1] params.w=[0.0, 1.0, -1.0]
  警告次数=1 文本='[vk] 阴影已知限制: VK 后端只有 2 张平行光阴影 + 1 套点光 6 面阴影;
  当前场景有 3 盏平行光 / 0 盏点光 要求投影 -> 超出部分无阴影
  (见 vk_renderer 模块 docstring, 不崩)。'
3 灯 shadow=False: 槽位=[0, 1] 警告次数=0
C 灯 shadow=True vs False 的 VK 像素差: MAE=0.00000000 MAX=0.000000
GL(3 片影) vs VK(2 片影): MAE=0.000188（已知限制：第 3 片影 GL 有、VK 无）
```

第三盏开/关阴影的 VK 输出**逐像素完全相同（MAE=0）** -> 证明它确实「无阴影」，
而不是采样了别人的贴图（旧实现是错位阴影）。GL 有第 3 片影所以两者 MAE 0.000188，
这是保留的已知限制。

## 5. 既有测试同步（为什么动了 test_vk_bucket_order.py）

`tests/test_vk_bucket_order.py` 第 7 段原先锁的是**旧已知限制**：
「两盏平行光投影 -> 打一次警告」。本次修复后 2 盏是合法配置（不再告警），
不同步该断言 `run_all` 必然 exit!=0。只改了第 7 段的 3 条断言：
2 盏 -> 不告警 + 槽位 0/1；3 盏 -> 告警一次 + 只分配前两槽；点光/单灯断言原样保留。
没有改动该文件其它任何测试逻辑。

## 6. 改前/改后实测对照

| 口径 | 改前 | 改后 |
|------|------|------|
| 新探针两平行光阴影 GL vs VK（MAE，门槛 0.0002） | **0.004560**（旧单张贴图语义，8855 像素 >0.05） | **0.000089 PASS**（MAX 0.0392, NCC 1.000006） |
| `ab_batch.py` 22 场景 | 22/22 PASS，最大 MAE 0.000082 | 22/22 PASS，**逐场景逐值相同** |
| `ab_scene.json` | 0.000068 | 0.000068 |
| `ab_c_dir_shadow.json` | 0.000071 | 0.000071 |
| 第 3 盏投影平行光 | 旧实现：错位阴影（拿第 1 张图） | 无阴影 + 警告一次（MAE 0.00000000 vs shadow=False） |

探针输出原文：

```
两平行光阴影 GL vs VK  MAE=0.0001  MAX=0.0392  NCC=1.0000
改前对照 (旧单张贴图语义): MAE=0.004560 MAX=0.1451 错像素>0.05: 8855 槽位=[0]
PASS  MAE=0.000089 (门槛 0.0002)  MAX=0.0392  NCC=1.000006  |  改前 MAE=0.004560
```

（改前对照用探针内的 `_OldSingleMapVk` 子类把渲染器压回旧语义：只保留 1 个槽位、
两盏灯都采样 `t_shadow`；不改生产代码，可复现。）

## 7. 验收数字

| 门槛 | 结果 |
|------|------|
| `python tests/_tmp/ab_batch.py`（22 场景, MAE<=0.0002） | **22/22 PASS, exit=0**，数值与改前逐值相同 |
| `python tests/_tmp/probe_two_dir_shadow.py`（两平行光, MAE<=0.0002） | **MAE=0.000089 PASS, exit=0** |
| `python tests/test_vk_two_dir_shadow.py`（CPU 槽位/布局, 30 条断言） | **全部 PASS, exit=0** |
| `python tests/run_all.py` | **exit=0**（含新增 test_vk_two_dir_shadow.py，0 条 FAIL 行） |

## 8. 遗留（已知限制，不在本批修）

- 第 3 盏及以后开阴影的平行光仍**无阴影**（打印一次警告；已验证不会拿错图）。
- 点光/聚光仍只支持 1 盏投影（第二盏无阴影 + 同一警告），本批未改。
- 固定 2 张 1024² r32float（新增显存约 4 MB）；未做按需分配。
- 旧字段 `_shadow_buf/_shadow_group` 保留为槽 0 别名（兼容既有引用）。
