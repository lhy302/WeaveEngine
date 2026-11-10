# 动画 P0 修复验证 — beta6 第六轮复核（编号 02）

> 只读审计：未修改任何受跟踪源码/测试/文档，未做 git 写操作。探针全部在 `Loom/tests/_tmp/audit_b6r6_02_*.py`（被 `.gitignore:22 tests/_tmp/*` 忽略，`git status --porcelain` 全程为空）。
> 本轮对象 = R5-02 的 6 项整改（提交 `21b44cd`，另含 `4de3b4b` 的 prefab 闸）。方法与口径按 `docs/audit/SCAN_PROTOCOL.md`：**先尝试证伪，打不破才判修好**；每条给 文件:行号 + 逻辑链 + 命令 + 实测输出。

---

## 0. 范围与方法

### 0.1 文件清单（HEAD = `308a6d1`，工作区干净）

| 文件 | 本轮关注点 | 改动来源 |
|---|---|---|
| `Loom/loom_components.py` | 常量通道写回 `:917-956`、once 夹取 `:826-844`、speed 降级 `:807-818`、`_np_sync` `:478-481/861-864`、copy/eq `:369-414` | `21b44cd` |
| `Loom/loom_frame_components.py` | GL 宿主 physics_available 判定 `:93-98` | `21b44cd` |
| `Loom/scene_driver.py` | VK 宿主判定 `:1326-1327` | `21b44cd` |
| `Loom/sceneio.py` | prefab 版本闸 `:2136-2169` | `4de3b4b` |
| `Loom/undo.py` | clips 值拷贝 `:125-128 / 219-240`、PrefabPlaceCommand `:616-639` | 未改（被①②③⑥波及） |
| `Loom/loom_physics.py` / `Loom/engine.py` | `_phys_bridge_disabled` 的真实写入点 `:547/574/577/588`、`_phys_bridge_auto` `engine.py:251` | 未改，是⑤的判据来源 |
| `Loom/tests/test_animation_base.py` | 新增 26 条断言的实际覆盖面 `:452-454 / 826-860` | `21b44cd` |

### 0.2 环境

```
py -3.13 = 3.13.15；numpy 可用；physics_bridge.cv_available = True（本机装了 culverin）
cd Loom; py -3.13 tests/test_animation_base.py  -> 总结果: ALL PASS ✅ (EXIT=0)
cd Loom; py -3.13 tests/test_animation.py       -> 总结果: ALL PASS ✅ (EXIT2=0)
```

**基线说明**：两套测试全绿只说明"他们写下的断言没被打破"。⑦ 段的 P-06 回退断言用的引擎桩是 `make_engine()`（`__new__` 不跑 `__init__`，**没有** `_phys_bridge_auto`），与生产实例（`engine.py:251` 恒为 True）不是同一个判据——见 V-11。

### 0.3 探针（可重跑）

| 探针 | 覆盖 |
|---|---|
| `_tmp/audit_b6r6_02_a_const_point3d.py` | ① 四类常量/混合通道 + once 到点 + 存盘 |
| `_tmp/audit_b6r6_02_b_once_edges.py` | ② 负速/负 dt/恰好 dur/dur=0/单帧/非法 speed |
| `_tmp/audit_b6r6_02_c_npsync_prefab.py` | ③ 换帧/原地改帧/undo + ④ prefab 三路径 |
| `_tmp/audit_b6r6_02_d_physics_available.py` | ⑤ GL/VK 判定矩阵 + 双写者 + env |
| `_tmp/audit_b6r6_02_e_ndarray_copy_eq.py` | ⑥ 顶层/嵌套 ndarray 的隔离与相等 |

---

## 1. 粗筛清单（改动的风险面与编号）

| ID | 位置 | 标签 | 为什么可疑（具体代码事实） |
|---|---|---|---|
| V-01 | `loom_components.py:917-956` | SEM-MISMATCH | 常量分支改成 `P3NEW(Point3D, v)`，但前置 `len(v) == 3` 可能静默跳过写回 |
| V-02 | `:826-844` | BND-TIME | 夹取条件写死 `dur > 0.0 and t < 0.0`——`dur == 0` 时整段不生效 |
| V-03 | `:861-864` | CACHE-STALE | `synced` 只按 `id(clip)` 去重；`_np_sync` 键是 `(id(frames), len)`（`:423/480`），同长度原地改帧不触发 |
| V-04 | `:2136-2169` | IFACE-VERSION | 三处闸门是否覆盖 load/instantiate/undo redo；会不会拦到旧 prefab |
| V-05 | `loom_frame_components.py:93-98` | DESIGN-GAP | `(pb is not None) or _phys_bridge_auto`：`auto` 在生产实例恒 True（`engine.py:251`），首帧永远误判为"物理可用" |
| V-06 | `scene_driver.py:1326-1327` | TAUTOLOGY | `physics_available=physb is not None` 里 `physb` 是**模块**（`:35-38`），culverin 缺失时模块照样导入成功 |
| V-07 | `:406-414 / 369-389` | DEEPCOPY-PARTIAL | `_cv` 只处理顶层 list/ndarray；`_canon_value` 只折叠顶层 ndarray，未递归 |
| V-08 | `loom_components.py:807-818` | SEM-SILENT | 只 catch `TypeError`；NaN/inf 是数值，不进降级分支 |
| V-09 | `tests:826-860` | AUDIT-ASYMMETRY | 回退断言用无 `_phys_bridge_auto` 的桩，生产判据未被测到 |
| V-10 | `loom_physics.py:459-485` | NEW-BEHAVIOR | 回退动画驱动后，legacy 物理仍逐帧写同一批动态刚体 → 双写者 |

跳过登记（判定无风险、留痕）：`_P3_NEW` 语义（D-05 已证，本轮 A 探针复核 `isinstance(..., Point3D)` 全 True）；`reset_anim_warn` 新增两标记（纯测试辅助）；prefab `version<1` 回落分支（旧路径语义未变）。

---

## 2. 逐项裁决

### V-01 · 常量通道 Point3D（P-DISPROVED，修复成立）

**1) 位置**：`loom_components.py:917-929`（cpos/crot/cscl 构造）、`:932-956`（写回）。
**2) 契约**：`_position/_rotation` 不变式是 `Point3D`（`:66-88` setter）；下游 `undo.snapshot:74-75`、`sceneio._emit_object`、`instantiate_prefab:2186`、脚本 `obj.position.x` 全按 `.x/.y/.z` 读。
**3) 路径枚举**：a) once 到点→`_write_pose`（Point3D）；b) pingpong 端点→`_write_pose`；c) 非快路径/NaN→`sample()`→`_write_pose`；d) 行失败回落→`_write_pose`；e) 通道会变→`P3NEW`；f) 通道恒定→**本轮新分支** `P3NEW`（旧实现写 plain tuple）；g) 三通道全恒定→f 的三次。
**4) 实际**：7 组用例（位置常量/旋转常量/scale 常量/三通道全常量/含 0 分量/list 值/两常量一插值）+ once 到点 + `scene_to_dict` 存盘，全部 `Point3D`、`.x/.y/.z` 可读、`undo.snapshot` 与 `json.dumps(_emit_object)` 不崩。
**5) 差异**：无（与旧实现相比只剩"常量通道值不为 None 且长度 3 才写"这一保守化；快路径下值必为 3 元组，不可达）。
**6) 触发条件**：轮子/风扇（位置恒定）、平移平台（旋转恒定）、纯缩放呼吸（scale 恒定）。
**7) 验证**：
```
cd Loom
py -3.13 tests/_tmp/audit_b6r6_02_a_const_point3d.py
```
实测（节选）：
```
--- A 位置常量+旋转插值+scale插值 | fast=True varies={'position': False, 'rotation': True, 'scale': True}
    pos=(2.0, 5.0, 3.0) rot=(0.24, 0.3, 0.36) scale=(1.3, 1.3, 1.3)
PASS A 常量position是Point3D  Point3D
PASS A undo.snapshot 不崩  (2.0, 0.3, 1.3)
PASS A _emit_object+json 不崩  True
--- D 三通道全常量: pos=(2.0, 5.0, 3.0) rot=(0.1, 0.2, 0.3) scale=(2.0, 2.0, 2.0)
--- E 位置常量含0分量(+/-0守卫) varies.position=True (对照)
--- once 到点: playing=False time=0.5 pos=(2.0, 5.0, 3.0)
--- scene_to_dict: position=[2.0, 5.0, 3.0] animator_keys=['clip_meta','clips','current','loop']
FAILED = []
```
**8) 影响与等级**：R5 P-01（P0 崩溃）已消除。

---

### V-02 · once 夹取（dur>0 全路径）（P-DISPROVED，修复成立）

**1) 位置**：`loom_components.py:826-844`。
**2) 契约**：Q2=A"once 夹到 [0,dur]，与 seek 一致"（`:588-617`）；批量与 `sample()` 同相位。
**3) 路径枚举**：`t >= dur`→末帧停播 `:827-833`；`t < 0`（dur>0）→夹 0 停播 `:834-841`；其余→`phase=t`。负速与负 dt 都只改 `t` 的来源，同一分支。
**4) 实际**：倒放到 0 停播、停在首帧、与 `sample(0)` 逐位一致；负 dt 同；`t==dur` 停末帧且 `time==dur`；`t=dur-1e-9` 未停播且位姿连续。
**5) 差异**：无。
**6) 触发条件**：`set_speed(负数)`、EAI `animator speed`、时钟回跳产生的负 dt。
**7) 验证**：
```
cd Loom; py -3.13 tests/_tmp/audit_b6r6_02_b_once_edges.py
```
实测：
```
   f0 time=0.200000 y=4.000000 playing=True ; f2 time=0.000000 y=0.000000 playing=False
PASS 倒放到 0 停播 / 停在首帧位姿 / 批量==sample(0)
   time=0.0 y=0.0 playing=False              (负 dt)
   t==dur: time=0.5 y=10.0 playing=False     (恰好 dur)
   t==dur-1e-9: time=0.499999999 y=9.99999998 playing=True
```
**8) 影响与等级**：R5 P-02（P1 外推/永不终止）在 `dur>0` 域内已消除；`dur==0` 域见 V-04。

---

### V-03 · `_np_sync` 覆盖三条路径（P-DISPROVED，见 V-07）

**1) 位置**：`loom_components.py:861-864`（扫描期每片段一次）、`:478-481`（键 = `(id(frames), len)`）、`undo.py:219-240`（apply 时再 `copy()`）。
**2) 契约**：类文档 `:328-335`"列表对象身份或长度变化即重建；同长度原地改帧不在校验范围，需调 `_np_rebuild()`"。
**3) 路径枚举**：换 frames 列表（id 变）→重建；undo 还原（apply 造新 `AnimationClip` → `__init__` 已重建）→新缓存；原地改 dict 值（id/len 都不变）→**不重建**（文档已声明）。
**4) 实际**：换帧后 `y=10.0`（新数据）且与 `sample(0.25)` 一致；两个片段同时换帧都同步；undo 还原后 `y=2.5`（还原数据）。
**5) 差异**：只有"原地改帧"这条路径按契约不生效（V-07 单列）。
**6) 触发条件**：脚本/插件整体替换 `clip.frames`；undo/redo；编辑器改 loop_mode。
**7) 验证**：
```
cd Loom; py -3.13 tests/_tmp/audit_b6r6_02_c_npsync_prefab.py
```
实测：
```
   换帧后 id 变化=True len=2
   换帧后 y=10.0  同帧集 sample(0.25)=(0.0, 10.0, 0.0)
PASS 换 frames 后批量用新数据 (y=10) / 批量==sample
   y1=10.0 (期望10) y2=20.0 (期望20)     PASS 两片段同时换帧都被同步
   还原后 clips 是新对象? True ; 还原后 y=2.5 PASS undo 还原后批量用还原数据
```
**8) 影响与等级**：R5 P-05（P2 换帧后旧数据）已消除。

---

### V-04 · `dur == 0` 的 once 不受夹取（P-PROVED，P3）

**1) 位置**：`loom_components.py:834`（`if dur > 0.0 and t < 0.0`）；对照 `seek:604-607`（`t < 0` 无条件夹 0）。
**2) 契约**：提交信息"P-02: once `t<0` 夹到 0 且 `playing=False`（与 seek 一致）"——**无条件**表述；Q2=A。
**3) 路径枚举**：`dur > 0`→夹取；`dur == 0`（单帧片段或所有关键帧同 time）→`:858-860 else`→`an.time = t`、`playing` 不动。单帧时 `_np_batch is None`→走 `sample()`，位姿不崩，但 `an.time` 无界负增长。
**4) 实际**：单帧 once + `speed=-1`，10 帧后 `time=-1.0`、`playing=True`；同一片段的 `seek(-1.0)` 返回 `0.0`。两条 API 对"once 负相位"口径不一致。
**5) 差异**：时间状态与 `seek`/提交声明不一致；位姿本身停在首帧（无视觉崩溃）。
**6) 触发条件**：单关键帧片段（姿态片段）或所有关键帧同 time 的片段 + `speed<0` 或负 dt。
**7) 验证**：`py -3.13 tests/_tmp/audit_b6r6_02_b_once_edges.py`
```
== 4) dur=0 单帧片段 + once + 负速 ==
   after 10 reverse frames: time=-0.9999999999999999 y=2.0 playing=True
   seek(-1.0) on same once clip -> 0.0 (playing=True)
FAIL dur=0 once 负速被夹取/停播 (与 seek 一致)  time=0.0 playing=True
```
**8) 影响与等级**：**P3**（运行态时间漂移、`playing` 语义错，不崩；时间在切换到 `dur>0` 片段后被夹回）。非新回归：旧实现同样不夹，但本轮宣称的"与 seek 一致"在该域未兑现。

---

### V-05 · 非法 speed 只降级 TypeError，不降级 NaN/inf（P-PROVED，P3）

**1) 位置**：`loom_components.py:810-818`（只 `except TypeError`）；`set_speed:576-577` 明确拒绝非有限值，但 `an.speed` 是公开属性，可绕过。
**2) 契约**：提交信息"`an.speed` 直写非法值改为单物体降级 1.0+提示"。
**3) 路径枚举**：list/None/str → `dt * speed` 抛 `TypeError`→降级 ✔；`float('nan')`/`inf`→乘法合法→`t=nan`→once/loop 分支都不命中→`phase=nan`→`:866` 的 `phase != phase` 走 `sample(nan)`→末帧；`an.time=nan` 永久保持。
**4) 实际**：`speed=nan` 三帧后 `time=nan y=10.0 playing=True`，无任何提示；位姿永久冻结在末帧，且无法自愈（nan 传播）。`speed=[1,2]` 则正确降级 1.0 并打一条提示。
**5) 差异**：降级面只覆盖"非数值"，不覆盖"非有限数值"；后者表现为静默冻结（与"动画坏了"不可区分）。
**6) 触发条件**：脚本里 `an.speed = a / b`（numpy 标量除 0）、`math.nan`、反序列化脏值（`animator_from_dict:695-703` 有 `isfinite` 兜底，故只限运行期直写）。
**7) 验证**：
```
   speed=[1,2] -> speed=1.0 time=0.1 y=2.0      (降级 + 一条提示)
   speed=nan -> time=nan y=10.0 playing=True    (无提示、永久冻结)
```
**8) 影响与等级**：**P3**（非 crash，单物体静默失效；与 P-07 的"降级"承诺有缺口）。

---

### V-06 · prefab 版本闸三条路径（P-DISPROVED，修复成立）

**1) 位置**：`sceneio.py:2141-2146`（写 `min_engine_version`）、`:2153-2160`（load_prefab 过闸）、`:2163-2169`（instantiate_prefab 过闸，注释点名 undo redo）；`undo.py:616-639`。
**2) 契约**：D7"所有加载入口"；prefab 物体带 `animator.speed/clip_meta`（`animator_to_dict:662-678`）。
**3) 路径枚举**：编辑器按钮 `editor.py:1430-1436`（`load_prefab`→`_notify`）；拖放 `:1548-1560`（`load_prefab`→`PrefabPlaceCommand`）；EAI `agent_commands.py:2312`→`_instantiate_prefab`；undo `do()` 首次→`instantiate_prefab`（过闸）；redo→只 `attach_model`（数据已在首次过闸）。
**4) 实际**：`min_engine_version='0.1.0.beta6'` 写出；`parse_version('0.1.0.beta6')=(0,1,0,0,6)`（闸门非静默放行）；`99.0.0` prefab 在 `load_prefab` 与 `instantiate_prefab` 均抛 `SceneVersionError`；旧 prefab（无字段）可加载；正常 prefab do→undo→redo 通；持有坏 data 的 `PrefabPlaceCommand.do()` 在写模型前抛错（`engine.models=0`，无半成品）。
**5) 差异**：无。
**6) 触发条件**：beta6 存 prefab → beta5/更旧引擎放置；或场景里持有更高版本 prefab data 的撤销项被重放。
**7) 验证**：
```
cd Loom; py -3.13 tests/_tmp/audit_b6r6_02_c_npsync_prefab.py
```
实测：
```
   prefab 顶层键=['min_engine_version','objects','prefab','version']
   load_prefab: SceneVersionError -> 场景要求引擎 >= 99.0.0 ... 拒绝加载
   instantiate_prefab: SceneVersionError -> 同上
   do=1 undo=0 PASS undo 删掉整棵 ; PASS redo 重挂 (不再过闸/不崩)
   PrefabPlaceCommand.do -> SceneVersionError; engine.models=0 PASS
```
**8) 影响与等级**：R5 P-04（P2）已消除。附注（P3）：拖放路径 `editor.py:1552` 用 `except Exception` 只 `print`、不走 `_notify`，同一 `SceneVersionError` 在按钮入口弹提示、在拖放入口只落 stdout——可观测性不对称，非功能缺口。

---

### V-07 · 原地改帧不同步（P-PROVED，P3，文档已声明的边界）

**1) 位置**：`loom_components.py:423`（`_np_key=(id(frames),len)`）、`:480-481`、`:861-864`、文档 `:334-335`。
**2) 契约**：文档明说"同长度原地改帧不在校验范围，需调 `_np_rebuild()`"；本仓 grep 未命中任何生产写入点（`frames` 赋值 / `frames.append` / 帧下标赋值）。
**3) 路径枚举**：`clip.frames = 新列表`→同步；`clip.frames[1]['position']=(...)`→id/len 不变→批量与 `sample()` **同时**用旧缓存。
**4) 实际**：原地改成 `y_end=40` 后求值仍 `y=2.5`（源数据应为 10.0）；`sample(0.25)` 未重建 `=2.5`，显式 `_np_rebuild()` 后 `=10.0`。
**5) 差异**：位姿与 `clip.frames` 内容不一致；但两条采样路径**同源同错**，不产生批量/逐物体分叉（这是 R5 P-05 的判据，已不成立）。
**6) 触发条件**：脚本直接改 `obj.animator.clips['x'].frames[i]['position']` 的值而不换列表。
**7) 验证**：
```
   原地改后 y=2.5  (源数据期望 y=10)
   原地改后 sample(0.25) 未重建=(0.0, 2.5, 0.0) | 显式 _np_rebuild 后=(0.0, 10.0, 0.0)
```
**8) 影响与等级**：**P3**（契约外数据，无仓内写入点；本轮判定为"未覆盖"而非"新破坏"）。若要让 `frames` 原地编辑成为受支持 API，则升为 P2。

---

### V-08 · GL 回退后"动画 + legacy 物理"双写者（P-PROVED，P1 [REGRESSION]）

**1) 位置**：`loom_frame_components.py:93-98`（判据）、`engine.py:250-251`（`_phys_bridge_auto` 恒 True）、`loom_physics.py:459-485`（无桥→`_update_physics_legacy`）、`:500-518`（legacy 对动态体写位姿）、`loom_components.py:880-885`。
**2) 契约**：P-06/Q-C1-3=A"物理不可用时回退动画驱动，否则位姿永久冻结"。
**3) 路径枚举**：桥可用→跳过（D6）✔；桥建体失败/步进异常→`_phys_bridge_disabled=True`（`loom_physics.py:547/574/577/588`）→下一帧起 `phys_ok=False`→回退；回退后同一帧仍执行 `update_physics`（`engine.py:1229→1246/1265`）→`update_physics` 因 disabled 走 legacy→legacy 对**同一批动态刚体**再写一次位姿。
**4) 实际**：动画把 y 设为 f(t)，legacy 再叠加 v·dt 且 v 逐帧累加重力 → 每帧偏移线性增长。实测 6 帧 offset = -0.098 / -0.196 / -0.294 / -0.392 / -0.490 / -0.588（dt=0.1, g=-9.8→0.098/帧）。
**5) 差异**：契约只承诺"回退动画驱动"，没承诺"关掉 legacy 物理"；实际两个写者同时生效，位姿 = 动画位姿 + 不断增大的物理偏移（长时间播放物体被重力拽离动画轨道）。
**6) 触发条件**：GL 播放（pipe 或串行均可）中 culverin 缺失/建体失败/桥步进异常，且物体同时有 `Animator` 与 `use_gravity=True` 的动态刚体。
**7) 验证**：
```
cd Loom; py -3.13 tests/_tmp/audit_b6r6_02_d_physics_available.py
```
实测：
```
[物理] 桥步进异常 (RuntimeError('桥步进坏 (模拟)')) -> 本场禁用 Culverin 桥, 回退 legacy
   f0 disabled=True anim_y=1.000000 -> after_legacy_y=0.902000 legacy_moved=True
   f1 disabled=True anim_y=2.000000 -> after_legacy_y=1.804000 legacy_moved=True
   f3 disabled=True anim_y=4.000000 -> after_legacy_y=3.608000 legacy_moved=True
PASS 桥坏时 animation 与 legacy 物理同时写位姿 (双写者)  y=5.412 anim_y=6.0
```
**8) 影响与等级**：**P1 [REGRESSION]**：这是本批新引入的行为（旧行为只有 legacy 在写；本批把动画也接上后没有抑制 legacy）。修法方向：`fallback` 时对这批物体在物理侧排除（或 `_update_physics_legacy` 跳过"本帧已被动画驱动"的刚体），并补"回退态 60 帧后 y == 动画位姿"的断言。

---

### V-09 · VK 宿主判定恒真（P-PROVED，P2）

**1) 位置**：`scene_driver.py:1326-1327`（`physics_available=physb is not None`）；`:35-38`（`physb` 是模块，`except` 只在模块级导入失败时置 None）；`:1055-1074`（真实可用性判据在 `physb.cv_available` + `_bridge_disabled`）；`:1076-1083`（桥 None → 直接 return，VK **没有** legacy 兜底）。
**2) 契约**：P-06"物理后端缺失（culverin 缺失）→ 回退动画驱动"。
**3) 路径枚举**：culverin 缺失→`physics_bridge` 模块仍导入成功（`try: import culverin` 内部兜底）→`physb is not None` 为 True→动画按"物理可用"跳过；桥 None→`_step_physics` 直接 return→**没有任何写者**→动态刚体位姿永久冻结。
**4) 实际**：强制 `physb.cv_available=False`（等价 culverin 缺失）后，同一对象的 `_ensure_phys_bridge` 返回 None（打印"culverin 不可导入 -> 无物理步进"），而 `_update_animations` 仍返回 `blocked_dynamic=1, fallback_dynamic=0`、`y=0`。
**5) 差异**：物理**不可用**却被判为可用，P-06 在 VK 侧完全未兑现；且 VK 无 legacy 物理，后果正是 P-06 描述的"永久冻结"。
**6) 触发条件**：VK 播放器（`run_player` auto 默认先 VK）在无 culverin 的机器上播放含"Animator + 动态刚体"的场景。
**7) 验证**：同上探针 ⑤-2：
```
   scene_driver.physb is not None = True ; physb.cv_available = True
[驱动] 物理: culverin 不可导入 -> 无物理步进 (legacy 语义缺失)
   force cv_available=False -> _ensure_phys_bridge 返回 None (物理不可用)
   同一对象 _update_animations -> stats={'advanced': 0, 'blocked_dynamic': 1, 'fallback_dynamic': 0} y=0
FAIL VK 在 culverin 缺失时应回退动画驱动
```
**8) 影响与等级**：**P2**（与 R5 P-06 同级；修复未覆盖 VK 宿主）。修法方向：判据与 `_ensure_phys_bridge` 的三条 early-return 同构（`physb is not None and physb.cv_available and not _bridge_disabled`，桥存在时也按可用）。

---

### V-10 · `LOOM_NO_PHYSICS=1` 不存在（P-DISPROVED，命题不成立）

**3) 路径枚举**：grep `LOOM_NO_PHYSICS` 只命中 `loom_components.py` 新注释与 `physics_glue.py:18`"删 LOOM_NO_PHYSICS_DLL 整体禁用门"；`git log -S` 全历史只出现过 `LOOM_NO_PHYSICS_DLL` 一个 token。
**4) 实际**：设 `LOOM_NO_PHYSICS=1` 后 GL 判定与未设置完全一致（`blocked_dynamic=1`）。
**7) 验证**：
```
git log -S "LOOM_NO_PHYSICS" -p --all -- Loom | Select-String "LOOM_NO_PHYSICS\w*" -AllMatches ...
-> 唯一 token: LOOM_NO_PHYSICS_DLL
   LOOM_NO_PHYSICS=1 下 GL stats={'advanced': 0, 'blocked_dynamic': 1, 'fallback_dynamic': 0}
```
**8) 判定**：该 env 既无读者也无历史，不能造成误判；⑤ 的真实误判面是 V-08（双写者）与 V-09（VK 恒真）。

---

### V-11 · 回退测试用的是桩判据（P-PROVED，P3，AUDIT-ASYMMETRY）

**1) 位置**：`tests/test_animation_base.py:844-860`（`e47 = make_engine()` 后直接 `update_animations`；`make_engine` `:101-107` 用 `__new__`，无 `_phys_bridge_auto`）。
**2) 契约**：`loom_frame_components.py:88-96` 注释称"未建但引擎声明会惰性建桥 → 仍按可用处理"。
**3) 路径枚举**：真引擎（`engine.py:251` `auto=True`）首帧 → `phys_ok=True`→跳过；测试桩（无 `auto` 属性）→`getattr(...,False)`→`phys_ok=False`→立刻回退。
**4) 实际**：测试 `PASS ⑦ P-06 无桥引擎走回退 (位姿不冻结)` 走的是**桩分支**；生产实例首帧必然先 `blocked_dynamic`（探针 ⑤-1 实测两条分支都打印过）。
**5) 差异**：断言绿≠生产判据成立；该测试无法捕获 V-08/V-09。
**6) 触发条件**：任何人以"⑦ 全绿"作为 P-06 已修的证据。
**7) 验证**：探针 ⑤-1 矩阵：`auto=True`→`blocked_dynamic=1`；`disabled=True`→`fallback_dynamic=1 y=1.0`；无 `auto` 属性→`fallback_dynamic=1`。
**8) 影响与等级**：**P3**（测试设计），建议补一条"生产判据（auto=True + disabled=True）"的断言。

---

### V-12 · 混合容器内 ndarray 的隔离/相等（P-PROVED，P2）

**1) 位置**：`loom_components.py:406-414`（`_cv` 只处理顶层 list / 顶层 ndarray）、`:369-375`（`_canon_value` 不递归）、`:383-389`（异常→`self is other`）、`undo.py:125-128/219-240`。
**2) 契约**：`copy()` 文档 `:398-404`"深拷贝（帧字典 + 值序列都复制）…否则模型与快照共享同一个可变数组，值隔离被打破"；`_canon_value` 注释"把 ndarray 折成 (形状/类型/字节)"。
**3) 路径枚举**：值 = ndarray（顶层）→`v.copy()` ✔；值 = list[ndarray]→`list(v)` 浅拷→内层共享 ✘；值 = tuple[ndarray]→`return v`→共享 ✘；比较同理：顶层折叠成字节 ✔，嵌套时 `tuple(v)` 内仍是数组→`==` 歧义→`except`→`self is other`→**同内容判不等**（除非两侧共享同一数组对象，CPython tuple 比较的身份捷径会让它"相等"）。
**4) 实际**：顶层 ndarray 隔离/相等都成立（含 `copy()==源`）；list/tuple 内嵌 ndarray 时 `copy` 与源共享同一数组（改源后 copy 侧读数变成 99.0），且两个同内容片段 `==` 返回 False；经 `undo.snapshot` 后快照与模型共享内层数组（改模型 77.0 → 快照读到 77.0）。
**5) 差异**：`copy()` 的"深拷贝"承诺与 `__eq__` 的"规范键可比较"承诺在嵌套容器下不成立；破坏面正是 undo 值隔离（R5 P-07 的原问题换了个形态）。
**6) 触发条件**：脚本/插件把 ndarray 放进 list/tuple 帧值（如 `position=[ax, ay, az]`），或 `np.array(list_of_vectors)` 拆包；`AnimationClip` 不校验帧值类型（`:432-460` 只决定快/慢路径）。
**7) 验证**：
```
cd Loom; py -3.13 tests/_tmp/audit_b6r6_02_e_ndarray_copy_eq.py
```
实测：
```
PASS 顶层 ndarray 被 copy 隔离 / 顶层 ndarray 内容相等可比 (True)
   list 内嵌 ndarray 同一对象? True ; 改源后 copy=np.float64(99.0)
FAIL list 内嵌 ndarray 值隔离  copy 侧 = np.float64(99.0)
FAIL list 内嵌 ndarray 内容相等可比   -> a == b 返回 False
   tuple 内嵌 ndarray 同一对象? True ; 改源后 copy=np.float64(99.0)
FAIL tuple 内嵌 ndarray 值隔离 / 内容相等可比
   快照与模型共享内层数组? True ; 改模型后快照值=np.float64(77.0)
FAIL 混合容器下 undo 快照值隔离
```
**8) 影响与等级**：**P2**（边界数据；R5 P-07 的修复只覆盖顶层数组）。方向：`_cv` 递归（tuple/list 逐元素、ndarray.copy、其余原样），`_canon_value` 递归并在比较前把嵌套数组折成字节元组；或显式拒绝非规范帧值（在 `AnimationClip.__init__` 校验并报错，避免静默）。

---

### V-13 · 顶层 ndarray / list↔tuple 归一（P-DISPROVED，修复成立）

**4) 实际**：`copy()` 后数组非同一对象；`copy() == 源`；`tuple` 帧与 `list` 帧同值 `==` 返回 True（旧实现 False）。
**7) 验证**：`py -3.13 tests/_tmp/audit_b6r6_02_e_ndarray_copy_eq.py`（⑥-1 与 ⑥-5 全 PASS）。
**8) 判定**：**P-DISPROVED**（R5 P-07 的顶层部分已修，剩余见 V-12）。

---

## 3. 统计

| 判定 | 数量 | 编号（等级） |
|---|---|---|
| P-PROVED | 7 | V-04(P3)、V-05(P3)、V-07(P3)、V-08(**P1**)、V-09(P2)、V-11(P3)、V-12(P2) |
| P-DISPROVED | 6 | V-01、V-02、V-03、V-06、V-10、V-13 |
| P-UNKNOWN | 2 | U-01、U-02 |
| P-CONTRADICTION | 0 | 无"证伪+证真同时成立"的对（V-02 与 V-04 按 dur>0 / dur=0 分域后各自单边成立） |
| 跳过登记 | 4 | 见 `1 末尾 |

[REGRESSION]：**V-08**（回退动画 + legacy 物理双写者，本批新引入）；V-09 属"应修未修/只修一半"（VK 侧），非新破坏。
按承诺项统计：6 项整改中 **① ② ③ ④ ⑥(顶层)** 成立；**⑤ 只兑现 GL、VK 未兑现**，且 ⑤ 的 GL 实现引入 P1 副作用；⑥ 的"所有混合容器"不成立。

---

## 4. 修复建议排序（只给方向，不含代码）

1. **V-08（P1）**：`fallback_dynamic` 生效时，物理侧必须停写这批刚体——在 `update_physics` / `_update_physics_legacy` 入口用"本帧已被动画驱动"的集合（或 `stats['fallback_dynamic']` 的物体表）做排除；回归断言：回退态 60 帧后 `y == clip.sample(time)` 逐位相等。
2. **V-09（P2）**：VK 的 `physics_available` 改与 `_ensure_phys_bridge` 同构（`physb is not None and physb.cv_available and not self._bridge_disabled`，且桥存在）；补"culverin 缺失时 VK 动态体由动画驱动"的断言（monkeypatch `cv_available=False` 即可，无需真缺库）。
3. **V-12（P2）**：`_cv` / `_canon_value` 递归；或对非规范帧值在构造/赋值处显式拒绝并给出可读错误。补 `list/tuple[ndarray]` 的双向隔离与相等断言。
4. **V-04 / V-05（P3）**：once 负相位夹取去掉 `dur > 0` 前置（`dur==0` 夹到 0/停播，与 `seek` 同构）；speed 直写改为"非有限值也降级 1.0 + 一次性提示"，补 `nan/inf` 断言。
5. **V-07（P3）**：明确"原地改帧"是 API 外行为（写进 `AnimationClip` 文档）或提供 `set_frame()` 强制 `_np_rebuild()`。
6. **V-11（P3）**：P-06 的回归断言改用生产判据（`_phys_bridge_auto=True` + `_phys_bridge_disabled=True`），不要只测"缺属性桩"。

---

## 5. 需要人类裁决的封闭问题

- **U-01（V-08 的可观测幅度）**：回退态双写者的偏移是"每帧线性增长"（探针：0.098/帧 @dt=0.1, g=-9.8）。需要一次真实 GL 播放会话（或 `--auto-close` 脚本）采样 300 帧两套数值（动画目标 y vs 最终 y），才能定它是"可见抖动"还是"缓慢漂移"。本审计未启 GUI，故列 UNKNOWN；已给的代码链与探针足以定性"两个写者同时存在"。
- **U-02（非规范帧值的真实可达性）**：V-05 的 NaN speed 与 V-12 的嵌套 ndarray 都需要"脚本/插件写入"，本仓无此写入点（grep 无 `frames` 原地写、无 `an.speed` 直写）。需要的信息：是否有发布级脚本/插件样例会这么写（或设计上是否承诺支持）。在此之前按 P3/P2 边界处理，不计入"当前可复现崩溃"。
- **U-03（V-04 期望口径）**：`dur==0` 的 once 负相位，选 A"同 seek 夹 0 并停播"（推荐，改动 1 个条件）/ B"维持现状（文档已声明 once 只在 dur>0 时有夹取语义）"？

---

## 6. 工作区状态留痕

- 审计开始/结束时 `git status --porcelain` 均为空；本轮只新增 `Loom/tests/_tmp/audit_b6r6_02_{a,b,c,d,e}_*.py`（被 `Loom/.gitignore:22 tests/_tmp/*` 忽略）与本报告。
- 未做任何 git 写操作；未改受跟踪源码/测试。
