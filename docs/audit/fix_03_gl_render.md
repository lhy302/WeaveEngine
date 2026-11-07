# 修复批次 03 — GL 渲染/光照 (scan_03_gl_render)

- 批次: fix_03_gl_render
- 改动文件: `loom_lighting.py`, `loom_render.py`（仅此两个业务文件；另新增测试 2 个 + 本文档）
- 未执行任何 `git add/commit`
- 验收: `ab_batch.py` 22/22 PASS（MAE 与改前逐项相同）、`ab_gl_vk_ui.py` MAE=0.00000009、`tests/run_all.py` exit=0

---

## 1. [P0] 聚光灯阴影槽位: 只登记 1 槽却绑 6 张面图 → `sampler_units[17]` IndexError

**位置**: `loom_lighting.py::_upload_lights` 阴影槽位分配段（旧 171-180 行，现 171-193）

**根因**:
- 着色器对 `u_light_kind > 0.5`（点光=1 / 聚光灯=2）统一走 `point_shadow(u_shadow_slot[i], ...)`，
  即从 `slot` 起**连续采样 6 张面图**；
- 旧代码 `need = 6 if light.kind == 'point' else 1`：聚光灯只登记 1 个槽位，却用
  `for k, tex in enumerate(sm['tex'])` 把 6 张面图连续绑到 `unit..unit+5`。
  `unit-1+5 > 15` 时 `sampler_units[16] = ...` → IndexError；不越界时面 1..5 的
  单元号落进后一盏灯刚绑的槽位，等于把别的灯的深度图当自己的面用。

**改法**:
- `need = 1 if kind == 'directional' else 6`（点光与聚光灯同权，各 6 槽）；
- 面图按『本灯 guid 的面图列表』逐个绑定，槽位与灯一一对应（同根因的 P1 项一并修掉）；
- 16 槽预算用尽时**降级不崩**：把该灯 `shadow = False`，并调用新增的
  `_warn_shadow_slot_overflow()`（现 227-236 行）只打印一次警告。
  按『非定向 6 槽/盏』计，16 槽最多容纳 2 盏非定向阴影光 + 4 盏平行光；
- 面图缺失/张数不足时保持旧语义（不登记槽位、不改灯状态），不新增降级面。

**前后证据**（真实 GL 上下文: 2 投影点光 + 1 投影聚光灯 + 1 平行光，320x240，渲染 2 帧）:

改前:
```
  File "...\loom_lighting.py", line 179, in _upload_lights
    sampler_units[unit - 1 + k] = unit + k
IndexError: list assignment index out of range
```

改后:
```
[loom_lighting] 阴影贴图槽位上限 16 已用尽: 关闭光源 's1' 的阴影 (非定向阴影光每盏占 6 槽, 16 槽最多容纳 2 盏 + 定向光各 1 槽)
NO-ERROR  u_shadow_slot= (0, 6, -1, 12)  maps= (1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 0, 0, 0)
kind order: ['point', 'point', 'spot', 'directional']  shadow: [True, True, False, True]
```

**新增测试**: `tests/test_light_shadow_slots.py`（无 GL，用假 program / 假深度纹理驱动真实
`_upload_lights`；A=超预算不抛异常+降级+只警告一次，B=预算内 1 点光+1 聚光灯+2 平行光全登记，
C=2 聚光灯+1 点光时第三盏降级）。改前该测试 A1 直接 IndexError，改后 24 项全 PASS。

---

## 2. [P1 同根因] 聚光灯非最后一盏时，面 1..5 采到后一盏灯的深度图

同第 1 项一并修复：槽位以 `light.guid` 自己的面图列表为准分配，`u_shadow_slot[i]` 之后
6 个单元必然是本灯的面 0..5。测试 B5/B7 断言 `face_units(spot) == [slot+1 .. slot+6]`；
改前渲染实况: 聚光灯槽位 0，面 1..5 的单元 = 2..6 = 第二盏灯的 face 0..4。

---

## 3. [P1] 删除 P-17 守卫: 有投影点光就整帧弃用 C 路径（裁决 Q3=A）

**位置**: `loom_lighting.py::_pipeline_light_vps`（旧 789-797 行，已删）

**根因**: 旧守卫 `if any(l.kind == 'point' for l in lights): return False` 让**所有**阴影
光源退回 Python 重算，只为规避『C 侧 `PIPE_POINT_FAR = 1.0e4` 与引擎 `_shadow_point_far = 30.0`
不一致』。该不一致实际不影响数值：面图里存的深度由 `_SHADOW_FRAG` 显式写
`gl_FragDepth = clamp(length(p-light)/u_light_far, 0, 1)`（u_light_far 仍是引擎的 30.0），
远平面只进投影矩阵 z 行，x/y 投影与 far 无关。

**改法**: 删除守卫，保留 804-805 的 `rows is None` 兜底（P-11）与 `pg.light_vps` 失败回退；
原注释改写为裁决理由 + 数值等价论证。

**前后证据**（2001 体 + 3 平行光；每轮清空 `_light_vps_sig` 强制真算，7 轮取中位数）:

| 场景 (N=2001) | 改前 | 改后 |
|---|---|---|
| `_compute_light_vps` 3 平行光 | 0.932 ms | 0.928 ms |
| `_compute_light_vps` 3 平行光 + 1 投影点光 | **6.468 ms** | **0.909 ms** |
| `_pipeline_light_vps` 3 平行光 + 1 投影点光 | 0.004 ms（直接 return False，等于没跑） | 0.953 ms（真跑 C） |

数值不变证据: `ab_point_shadow.json` MAE 0.000063、`ab_c_point_only.json` MAE 0.000000、
`ab_plane_cube_sun_pt.json` MAE 0.000018 —— 与改前**逐位相同**。

---

## 4. [P1] 编辑态阴影 VP 缓存键缺 roll

**位置**: `loom_lighting.py::_light_vps_cache_sig`（旧 823-838 行，现 847-866）

**根因**: 缓存键里是 `l.direction` 向量，而 `LightState.direction` 只由 azimuth/elevation
派生，`roll` 只影响 `up_vector()`（被 `_dir_light_vp` 用作视图 up）。编辑态静止缓存下
改 roll → 签名不变 → `_compute_light_vps` 直接返回上一帧 `_light_vps` → 阴影视图与
光束截面不跟着转。

**改法**: 签名加入 `float(getattr(l, 'roll', 0.0))`（现 857-861 行）。

**前后证据**: `tests/test_light_vp_cache_roll.py` 在**改前源码**（git HEAD 的两个模块拷到
临时目录跑）:
```
FAIL A2 改 roll 后签名改变 (修复前相同 -> 缓存不失效)  sig_equal=True
FAIL A3 改 roll 后 VP 真的重算了 (不是复用旧矩阵)  maxdiff=0.000e+00
FAIL E1 beam 模式改 roll 后横截面基改变  maxdiff=0.000e+00
```
改后（本工作区）:
```
PASS A2 改 roll 后签名改变  sig_equal=False
PASS A3 改 roll 后 VP 真的重算了  maxdiff=1.186e-01
PASS B2 深度列 (VP[:,2]) 不随 roll 变 (roll 只转 XY 基)
PASS C1 roll 回 0 -> VP 回到 roll=0 的值  maxdiff=0.000e+00
PASS D1 签名不变 -> 直接返回上帧 _light_vps (零重算)
PASS E1 beam 模式改 roll 后横截面基改变  maxdiff=5.417e-01
```

**新增测试**: `tests/test_light_vp_cache_roll.py`（A 签名/重算、B roll 语义位置、C 可逆、
D 缓存仍生效、E beam 截面）。

---

## 5. [P1] 视锥剔除半径不乘实例缩放

**位置**: `loom_render.py::_frustum_keep` / `_spheres_in_frustum`（旧 369-382 行；
调用点 533-542 未改）

**根因**: 桶半径 `r` 是**模型空间**最大顶点距，`_frustum_keep` 直接当世界半径用。
放大过的实例真实包围球远大于剔除球 → 贴视锥边缘时整实例被误剔（主 pass 少画、
阴影 pass 仍全量画，现象是『物体没了但影子还在』）。

**改法**: `_frustum_keep` 用行向量世界矩阵（`S@R@T`，行 0..2 前三列 = 旋转轴×各轴缩放）
算每实例三轴缩放（`einsum('kij,kij->ki')` 一次求出三条轴的模平方再取 max），
取 `max(scale) * mesh_radius` 作为逐实例半径；`_spheres_in_frustum`
的 radius 参数改为『标量或 (k,) 数组』（广播，保守性不变）。`_bucket_radius` 的桶级
mesh 半径缓存保留（仍缓存模型空间半径）。

**前后证据**（单位投影视锥 |x|,|y|,|z| <= 1，mesh 半径 2，同一段输入）:

| 实例 | 改前 | 改后 |
|---|---|---|
| 中心 (1.5,0,0) 缩放 10 | keep=True | keep=True |
| 中心 (5,0,0) 缩放 1 | keep=False | keep=False |
| 中心 (30,0,0) 缩放 20（真实半径 40） | **keep=False（误剔）** | **keep=True（保留）** |

代价: `_frustum_keep` k=500 实例 / 6 平面 119.8 µs → 193.3 µs（+73 µs）。该函数只在
桶实例数据脏帧执行（静止编辑态在 `_bucket_frame_sig` 处整段早退，见 `loom_render.py:458`），
播放态每帧 ~5 个桶约 +0.36 ms；若要再压，可把 `_spheres_in_frustum` 的逐平面点乘改成矩阵乘
（不在本批次范围）。

---

## 验收数字（本工作区实测）

```
python tests/_tmp/ab_batch.py
场景数 22, 门槛 MAE <= 0.0002, 失败 0 -> 全部通过 ✅
重点: ab_c_spot_only 0.000000 / ab_point_shadow 0.000063 / ab_scene 0.000068 / ab_c_dir_shadow 0.000071
（22 行 MAE 与改前逐项相同）

python tests/_tmp/ab_gl_vk_ui.py
GL(UI) vs VK(UI)  MAE=0.00000009  MAX=0.003922  NCC=0.99998569   （门槛 1e-6）

python tests/test_light_shadow_slots.py  -> 24 项全 PASS, exit=0
python tests/test_light_vp_cache_roll.py -> 12 项全 PASS, exit=0
```

---

## 遗留 / 新发现（本批次未改）

1. **降级是永久性的**: 槽位超限把 `light.shadow` 置 False 后不会自动恢复；用户删掉
   别的灯后需手动重新勾选阴影。裁决 Q2=A 未要求自动恢复（自动恢复需要『被降级』
   标记 + 每帧回收，属于新设计）。
2. **降级按灯序而非优先级**: 先分配者保留，后一盏被关；平行光与点光不区分优先级。
3. **C 侧点光远平面仍硬编码 1e4**（官方 DLL 不改）。本批次靠『`gl_FragDepth` 显式写
   `length/far`』证明数值等价；若将来改成标准深度写入、或改 `_shadow_point_far` 默认值，
   需重新审查这条等价。
4. **聚光灯仍按点光 6 面立方阴影渲染**（6×512²），比单张透视深度图贵约 6 倍；本批次
   只修槽位正确性，未改渲染结构。
5. **`_light_vps_cache_sig` 仍未包含 `_shadow_point_far` / `_shadow_res` 等全局渲染参数**：
   运行期改这些值不会让编辑态 VP 缓存失效（改 far 会改点光 6 面 VP）。与本批次第 4 项
   同类，超出范围。
6. `tests/_tmp/` 下历史探针仍有硬编码绝对路径，未修。
