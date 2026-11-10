# 批次 C1 动画底座 — beta6 第五轮阶段性审核（编号 02）

> 只读审计。未修改任何受跟踪源码/测试；探针全部写在 `Loom/tests/_tmp/audit_b6r5_02_*.py`。
> 审计锚点：C1 实质提交 `3a35f8f`（动画底座）与 `d635f35`（版本闸 + EAI speed/seek/loop_mode + 逃生门次序）；批次 B1 基线 `f2d43b1`。
> 审计期间 HEAD 从 `cc62480` → `3249375`(docs) → `1d22e60`(Q-VER-1) 前移，故本文对 C1 的结论以 `git show d635f35:<file>` / `git show 3a35f8f:<file>` 为准；
> 批外后续提交（1d22e60 / 470b7bc / 0b38bc0）单列为「批外接力」，不据此下 C1 结论。

---

## 0. 范围与方法

### 0.1 文件清单

| 文件 | 职责 | 本次关注 |
|---|---|---|
| `Loom/loom_components.py`（~874 行） | AnimationClip / AnimatorComponent / evaluate_animations 唯一内核 | ①②③⑤ |
| `Loom/loom_frame_components.py`（~120） | GL 侧 update_animations 入口（已收敛为一行委派） | ① |
| `Loom/scene_driver.py`（~1312） | VK 侧 SceneDriver（build_models / _update_animations / load_from_data） | ①③ |
| `Loom/engine.py`（~1560） | 逻辑帧次序（脚本→动画→物理→音频）、逃生门分支 | ①④ |
| `Loom/loom_render.py`（~1059） | `_escape_door_step`（NO_SPLIT 分支四段） | ④ |
| `Loom/sceneio.py`（~1750） | animator 序列化、min_engine_version 闸、prefab 资产 | ③④ |
| `Loom/undo.py`（~700） | snapshot/apply_snapshot 的 clips 值拷贝 | ② |
| `Loom/editor.py`（~2400） | 版本预检、set_anim_loop_mode/set_anim_speed、commit_model | ②③ |
| `Loom/agent_commands.py` | EAI animator speed/seek/loop_mode 分支 | ② |
| `Loom/run_player.py` | 播放器后端分派（版本闸的落地处） | ③ |

### 0.2 环境与基线

```
py -3.13 → 3.13.15；numpy 可用；Loom/解释器.json version = 0.1.0.beta6
cd Loom; py -3.13 tests/test_animation_base.py   → ALL PASS（C1 自带硬门全绿）
cd Loom; py -3.13 tests/test_animation.py        → ALL PASS（beta5 旧动画测试未破）
```

**基线说明**：C1 自带 46+ 条断言全绿、旧 `test_animation.py` 也全绿；下述 P-01/P-02/P-05 都是这两套测试**未覆盖**的边界，
因此“测试全绿”不能作为这些点的反证（见 §1 跳过登记与 §2 各链第 7 段）。

### 0.3 探针（全部可重跑）

| 探针 | 覆盖 |
|---|---|
| `_tmp/audit_b6r5_02_p1_const_channel.py` | 常量 position/rotation 通道的写回类型 |
| `_tmp/audit_b6r5_02_p2_neg_phase.py` | once + 负相位（speed<0 / 负 dt）批量 vs 逐物体 |
| `_tmp/audit_b6r5_02_p3_gate_entries.py` + `p3b_trace.py` | 闸门入口覆盖（GL / VK / prefab），含 HEAD 版本 scene_driver 原样落地导入 |
| `_tmp/audit_b6r5_02_p4_edges.py` | 0 帧 / 单帧 / speed=0 / 非法 loop_mode / 超大 dt |
| `_tmp/audit_b6r5_02_p4b_undo_bidir.py` | undo 快照↔模型 四方向隔离 |
| `_tmp/audit_b6r5_02_p5_d6_dynamic.py` | D6 动态刚体跳过后的可见性与“永久不动” |
| `_tmp/audit_b6r5_02_p6_clip_eq.py` / `p6b_copy_speed.py` | __eq__ 内容比较 + hash=身份；copy() 对可变值；非法 speed |
| `_tmp/audit_b6r5_02_p7_stale_batch.py` | batch 读 `_np_batch` 不走 `_np_sync` |
| `_tmp/audit_b6r5_02_head_scene_driver.py` | `git show d635f35:Loom/scene_driver.py` 原样副本（对照提交态） |

### 0.4 关键调用点（路径枚举依据）

- GL：`engine._logic_frame` → pipe 分支 `d635f35:engine.py:1229`、串行分支 `:1254`；`_advance_logic` 逃生门 `:1538`。行号统一以 `d635f35` 为准（HEAD 因 D1 提交 +1~2 行）。
- GL 渲染逃生门：`loom_render.py:897 _escape_door_step`（脚本→动画→物理→音频）；`render` 在 `_ensure_split()` 为 None（`:938`）时 `:977` 调用它，否则走时钟推进。`editor.render` 另经 `:2411-2415` 消费 `_advanced_this_frame` 后自行绘制，不再进 `RenderMixin.render`。
- VK：`scene_driver.py:764`（`_logic_frame` 内）、`:882`（绑死渲染帧；分离分支 `:870 clock.advance`）→ `:1295 _update_animations`。
- 两宿主内核唯一性：`loom_frame_components.py:80-88` 与 `scene_driver.py:1295-1303` 都只 `return evaluate_animations(self.models, dt)`。
- 每帧推进次数：5 个调用点由 `_ensure_split()` / `_advanced_this_frame` 二分成互斥分支（见 D-02 路径枚举）。

---

## 1. 粗筛清单（含跳过留痕）

### 1.1 疑似项（六元组）

| ID | 位置 | 标签 | 初步方向 |
|---|---|---|---|
| P-01 | `loom_components.py:818,847,857` | SEM-MISMATCH / AUDIT-ASYMMETRY | 批量路径把“常量通道”直接赋 `clip.sample(0.0)` 的 plain tuple 到 `tr._position/_rotation`，绕开 property setter 的 Point3D 归一 |
| P-02 | `loom_components.py:764,773-781,798` | BND-TIME / SEM-MISMATCH | once 模式 `phase = t` 不做非负夹取；批量 `_sample_batch` 对负相位外推，而 `sample()` 对负 t 先 `% dur` |
| P-03 | `HEAD scene_driver.py:599`（无 `check_engine_version`） | IFACE-VERSION | 提交态 VK 播放器入口不过版本闸；`run_player.run_backend`（HEAD:409-411）auto 先 VK |
| P-04 | `sceneio.py:1938-1957` | IFACE-VERSION / AUDIT-DOCIMPL | prefab 资产不写 `min_engine_version`、`load_prefab` 不过闸，但 prefab 物体同样带 `speed`/`clip_meta` |
| P-05 | `loom_components.py:798` | AUDIT-ASYMMETRY | 批量路径读 `clip._np_batch` 前不调 `_np_sync()`，与 `sample()` 入口的失效契约不一致 |
| P-06 | `loom_components.py:756-758,808-812` | SEM-SILENT / IFACE-PARTIAL | D6 对动态刚体整条跳过且 time 不推进；告警全进程一条、只到 stdout |
| P-07 | `loom_components.py:363-384` | BND-EMPTY / AUDIT-DOCIMPL | `__eq__` 内容比较 + `__hash__` 身份并存；`copy()` 只深拷 list 值（np 数组等可变值共享） |
| D-01 | `undo.py:121-128,219-240` | — | undo clips 值隔离是否真双向 |
| D-02 | `engine.py:1229/1255/1540`、`loom_render.py:1040`、`scene_driver.py:773/891` | — | 动画/物理次序是否三处一致、每帧是否只推进一次 |
| D-03 | `loom_components.py:760-797` | — | 0 帧/单帧/speed=0/超大 dt 边界是否崩 |
| D-04 | `loom_components.py:620-669` | — | speed/clip_meta/time/playing 序列化契约 |
| D-05 | `loom_components.py:845,854,863` | — | `tuple.__new__(Point3D, ...)` 是否破坏 namedtuple 语义 |
| U-01 | P-01 的可达链 | — | 编辑器播放态是否真能走到 `undo.snapshot`/`_emit_object` |
| U-02 | `loom_components.py:760-797` | DESIGN-AMBIG | 非法 `loop_mode` 的期望策略（拒绝 / 归一 / 告警）文档未定 |
| U-03 | P-04 | DESIGN-GAP | prefab 是否属于 D7 版本闸门范围，文档未写明 |

### 1.2 跳过登记（每项必须给四类理由之一）

| ID | 位置 | 跳过理由（类别 + 出处） |
|---|---|---|
| SKIP-01 | `loom_components.py:611 _P3_NEW = tuple.__new__` | ③已有回归测试 + 探针：`audit_b6r5_02_p1` 实测 `isinstance(..., Point3D) == True`（D-05） |
| SKIP-02 | `loom_components.py:870-871` 每帧只 bump 一次 `_xform_gen` | ②契约声明 + ④消费者枚举：`loom_transform.py:70-73`（缓存键相等性）与 `:183-189`（只比较 `gen == last`），全仓无“bump 次数”读取方 |
| SKIP-03 | `engine.py:1230→1240` 计时段改名 `mt_audio_anim`→`mt_audio` | ④工具/框架自身声明：`grep -rn mt_audio Loom` 仅 `_prof_add` 写入侧，无读取方/断言 |
| SKIP-04 | 0 帧 clip（`frames=[]`） | ②契约声明（旧实现同语义）：`git show 3a35f8f^:Loom/loom_frame_components.py` 对空帧同样 `continue` → 非 C1 引入 |
| SKIP-05 | 单帧 `time=0` + once 永不停播 | ②同上：旧实现 `if clip.duration > 0 and ...` 同样不触发，`p4` 探针实测与旧语义一致 |
| SKIP-06 | `_write_pose` 把 int 分量 `float()` 化 | ③测试证据：全仓 `same_bits` 断言输入本身为 float；JSON `0`→`0.0` 值相等，无逐字节场景断言 |
| SKIP-07 | `copy()` 不拷贝 `_np_*` 缓存 | ③探针：`p4b` 实测 copy 后 `==` 源、采样一致（`__init__` 重建） |
| SKIP-08 | `seek()` 不改变 `playing` | ③测试：`test_animation_base.py` ③“seek 不改变 playing”已覆盖 |

---

## 2. 逐项裁决

### P-01 · 批量路径把常量通道写成 plain tuple（PROVED，P0）

**1) 位置**：`Loom/loom_components.py:818`（`const = clip.sample(0.0)`）、`:847-849`（`tr._position = cpos`）、`:856-858`（`tr._rotation = crot`）、`:865-867`（`tr._scale = cscl`）。

**2) 契约/预期**：`TransformComponent._position/_rotation` 的不变式是 `Point3D` —— `loom_components.py:68-69`（构造 `Point3D(*pos)`）、`:78-88`（setter `Point3D(*v)`）；
`_write_pose` 自己也遵守（`:705-715` 构造 `Point3D(float(...))`）。下游以 `.x/.y/.z` 读取：`undo.py:74-75`（snapshot）、`sceneio._emit_object`、`sceneio.py:1979-1981`（instantiate_prefab 根平移）。

**3) 路径枚举**（`evaluate_animations` 内所有写 position 的分支）：
- 分支 a `:773-779` once 到点 → `_write_pose`（Point3D）✔
- 分支 b `:782-792` pingpong 端点 → `_write_pose`（Point3D）✔
- 分支 c `:799-802` 无快路径/NaN → `_write_pose`（Point3D）✔
- 分支 d `:825-831` 行失败回落 → `_write_pose`（Point3D）✔
- 分支 e `:844-849` 通道“会变” → `P3NEW(Point3D, ...)`（Point3D）✔
- 分支 f `:847-849` 通道“恒定” → `tr._position = cpos`（plain tuple）✘
- 分支 g `:856-858` 旋转恒定 → `tr._rotation = crot`（plain tuple）✘

通道是否“恒定”由 `:436-445` 判定；`:440-443` 的 ±0 保守守卫使“含 0 分量”的常量通道被当成会变（所以 (0,5,0) 反而安全），**无 0 分量**的常量通道才命中分支 f/g。

**4) 实际**（实测）：见第 7 段。

**5) 差异**：`m.position` 从 `Point3D` 降级为 `tuple`；所有 `.x/.y/.z` 读取点 `AttributeError`。

**6) 触发条件**：2 帧以上、三通道齐备、值可转 f64（快路径成立）+ 某通道所有关键帧同值且该值不含 `0.0` + 物体当前值与该常量不同。典型：轮子/风扇（位置恒定 (2,5,3)、只转 Y）、平移平台（旋转恒定 (0.1,0.2,0.3)）。

**7) 验证**：
```
cd Loom
py -3.13 tests/_tmp/audit_b6r5_02_p1_const_channel.py
```
实测输出（节选）：
```
A: _np_fast=True varies={'position': False, 'rotation': True, 'scale': False}
   position type=tuple value=(2.0, 5.0, 3.0)
   m.position.x -> AttributeError: 'tuple' object has no attribute 'x'
   undo.snapshot -> AttributeError: 'tuple' object has no attribute 'x'
   sceneio._emit_object -> AttributeError: 'tuple' object has no attribute 'x'
B: varies={'position': True, 'rotation': False, 'scale': False}
   rotation type=tuple value=(0.1, 0.2, 0.3)
   undo.snapshot -> AttributeError
C: (0,5,0) 常量 -> ±0 守卫 -> varies.position=True -> position type=Point3D（对照）
```

**8) 影响与等级**：**P0（崩溃）**。连锁点：任一 `commit_model`（`editor.py:1752-1758` 首行 `undo_snapshot(m)`）、`scene_to_dict`（播放态/EAI scene_save 存盘）、`instantiate_prefab` 根节点平移（`sceneio.py:1979`）、游戏脚本 `obj.position.x`（VK 侧脚本 broken 后静默停跑）。`[REGRESSION]`

**修复方向**：分支 f/g 写回前走同一归一（`Point3D(float,float,float)`），或把 `const` 值直接缓存为 `Point3D` 对象复用。

---

### P-02 · once 模式的负相位：批量外推 vs 逐物体取模（PROVED，P1）

**1) 位置**：`loom_components.py:764`（`t = an.time + dt * an.speed`）、`:772-781`（once 只夹上界）、`:798`（直接进批量）、`:679-691 _sample_batch`（负相位 `idx=0→1`、`f<0` 外推）；对照 `:460-462 sample()`（`if dur > 0: t = t % dur`）。

**2) 契约/预期**：①`set_speed` 文档（`:541`）“<0 倒放”；②`seek` 文档（`:559-562`）“once: [0,duration] 夹取”；③`_sample_batch` 文档（`:672-677`）“与 AnimationClip.sample 快路径逐位一致”；④模块注释（`:597-600`）“同公式同 searchsorted 同 f 分支，数值逐位一致”。

**3) 路径枚举**（`dt*speed < 0` 时 phase 的去向）：
- loop（`:765-771`）：`phase = t % dur` → 正域，批量与 sample 同域 ✔
- once 且 `t >= dur`：夹到 dur + 末帧 ✔
- once 且 `t < 0`：`an.time = t; phase = t` → 批量分支（`arr is not None`）→ **负相位外推** ✘；若该 clip 非快路径（`arr is None`）→ `sample(t)` → 取模回绕 ✔（同一函数两条路径不同语义）
- pingpong（`:782-792`）：`t % period` → 正域 ✔
- `speed < 0` 在 once 下永不满足 `t >= dur`：`playing` 永远 True，`an.time` 无界负增长 ✘

**4) 实际**：见第 7 段。

**5) 差异**：同一 phase 上，快路径外推 `y=-25`，逐物体语义基准 `sample(-2.5)` = `y=7.5`；once+倒放没有“到尾停/到头停”的任何终止条件。

**6) 触发条件**：`animator.set_speed(负数)`（EAI `animator action=speed value=-1` / 脚本）或以负 dt 调用 `update_animations`（时钟回跳；本审计未证外部可产生负 dt，见 U-01 同类信息需求）。

**7) 验证**：
```
cd Loom
py -3.13 tests/_tmp/audit_b6r5_02_p2_neg_phase.py
```
实测：
```
after dt=0.25 : an.time=-0.25 y=-2.5 playing=True stats={'advanced': 1, 'blocked_dynamic': 0}
clip.sample(time) -> y=(0.0, 7.5, 0.0)
batch == sample? False
after 10 frames : an.time=-2.5 y=-25.0 playing=True
slow clip._np_fast = False ; after dt=0.25 : an.time=-0.25 y=7.5 playing=True
once + 负 dt: y 2.0 -> -3.0 (time=-0.3)
```

**8) 影响与等级**：**P1（功能错误）**。倒放 API 在非循环片段上产生线性外推（物体飞出取景）、永不终止，且违反本批自己写下的“批量==逐物体”不变量。`[REGRESSION]`（beta5 无 speed API，但 `sample()` 的取模语义是老契约）。

---

### P-03 · 提交态 VK 播放器入口不过版本闸（PROVED，P1；已由批外 1d22e60 修复）

**1) 位置**：`d635f35` 的 `Loom/scene_driver.py:599 load_from_data` 全文无 `check_engine_version`、无 `migrate`（`:1304` 是求值入口）；`run_player.py:409-411`（`api == auto` → 先 `_run_vulkan`）。

**2) 契约/预期**：`sceneio.py:64-67` 注释与 `d635f35` 提交信息“migrate() 首行过闸（**所有加载入口**）”；`test_animation_base.py:646` 注释“播放器/驱动同一入口”。

**3) 路径枚举**（场景数据全部加载入口）：
- GL 编辑器 `editor._load_scene` → 预检 `editor.py:1223` + `scene_from_dict` → `migrate`（`sceneio.py:1667`）✔
- GL 播放器 `runtime.PlayerApp` → `scene_from_dict` → `migrate` ✔
- GPU 预览 `loom_model_gpu.py:368 scene_from_dict` ✔
- **VK 播放器 `vk_player.py:328 driver.load_from_data` → 无闸 ✘**
- 游戏包 `scene_data`：GL 有闸、VK 无闸 ✘
- prefab `load_prefab` → 见 P-04 ✘

**4) 实际**：见第 7 段；且 auto 模式**先**走 VK，所以默认配置下闸门从未被执行。

**5) 差异**：`d635f35` 声称“所有加载入口”，实际缺 VK 一侧；同一份更高版本场景，`--backend opengl` 被拒绝、默认 auto 却静默加载并丢弃 `speed`/`clip_meta`（双后端行为分叉）。

**6) 触发条件**：场景/游戏包由更高版本引擎写出（带 `min_engine_version`）→ 用 beta6 VK 播放器打开。

**7) 验证**（对照：HEAD 副本 vs 当前仓库）：
```
cd Loom
git show d635f35:Loom/scene_driver.py | Select-String check_engine_version   # 空
py -3.13 tests/_tmp/audit_b6r5_02_p3_gate_entries.py
```
实测：
```
HEAD 的 scene_driver.py 里有 check_engine_version 吗: False
-- HEAD (提交 3a35f8f/d635f35) : SceneDriver.load_from_data --
   RESULT: 加载成功, models=0  <-- 提交状态下 VK 播放器入口无闸门
-- 当前工作区 (Q-VER-1 提交后) --
   RESULT: SceneVersionError -> 场景要求引擎 >= 99.0.0, 当前引擎 0.1.0.beta6 ...
-- 对照: GL 入口 sceneio.scene_from_dict --
   RESULT: SceneVersionError -> ...（同）
```

**8) 影响与等级**：**P1（跨版本静默丢字段）**。批外接力：`1d22e60`（Q-VER-1）在 `scene_driver.py:605-615` 补闸并在 `run_player` 统一弹窗退出 —— **本轮不计入 C1 未决项**，但保留“C1 提交态确有缺口”的证据链供批次收口核对。

---

### P-04 · prefab 资产不在版本闸门覆盖内（PROVED，P2）

**1) 位置**：`sceneio.py:1938-1945 prefab_to_dict`（只写 `version: PREFAB_VERSION`，无 `min_engine_version`）、`:1952-1957 load_prefab`（只 json.load + 版本回落）、`:1960-1982 instantiate_prefab`（直接 `_apply_object`）。

**2) 契约/预期**：`sceneio.py:64-67` 的闸门目的——“旧引擎读新场景会把 animator.speed / clip_meta 等未知键**静默丢弃**”；而 prefab 物体的 `animator` 由同一个 `animator_to_dict` 写出（`sceneio.py:479`，prefab 走 `_emit_subtree`→`_emit_object`）。

**3) 路径枚举**：prefab 读入口只有 `load_prefab`（编辑器 `editor.py:1417/1532`、`scene_driver.py:629`）→ 三条路径都不经 `migrate/check_engine_version`。

**4) 实际**：见第 7 段：prefab 物体 animator 含 `clip_meta`/`speed`，顶层无 `min_engine_version`。

**5) 差异**：同类“未知键静默丢弃”在 prefab 通道未设防；后果是 `once` 变“永远循环”、变速丢失。

**6) 触发条件**：beta6 存 prefab → beta5 引擎放置实例。

**7) 验证**：
```
cd Loom
py -3.13 tests/_tmp/audit_b6r5_02_p3_gate_entries.py
```
实测：
```
prefab 顶层键 = ['objects', 'prefab', 'version'] | 有 min_engine_version ? False
prefab 物体 animator 键 = ['clip_meta', 'clips', 'current', 'loop', 'speed']
beta5 旧解析只认 current/loop/clips -> 静默丢弃 = ['clip_meta', 'speed']
语义结果: beta6 片段 loop_mode='once' / speed=2.0; beta5 只看到 loop=True -> 变速丢失, once 变永远循环
load_prefab co_names = ('open', 'json', 'load', 'get') | 含闸门? False
```

**8) 影响与等级**：**P2（跨版本语义漂移）**。是否属于 D7 范围属设计缺口 → U-03。

---

### P-05 · 批量路径读 `_np_batch` 前不 `_np_sync()`（PROVED，P2 潜在）

**1) 位置**：`loom_components.py:798 arr = clip._np_batch`；失效契约在 `:448-451 _np_sync` 与类 docstring `:328-335`（“列表对象身份或长度变化即重建”）。

**2) 契约/预期**：`sample()`（`:457`）入口先 `_np_sync()`；批量路径应同守。

**3) 路径枚举**（帧列表被替换后的三种读者）：
- `sample()`：`:450` 键不等 → `_np_rebuild()` ✔
- `evaluate_animations` 快路径：`:798` 直接取旧 `_np_batch`（times/vals 仍旧），而 `:752/763` 的 `frame_list/dur` 已是新帧 → 混用 ✘
- `:818 const = clip.sample(0.0)`：这里**会**触发重建，导致同帧内 `arr`（旧）与 `clip._np_varies`（新）不同源 ✘

**4) 实际**：见第 7 段。

**5) 差异**：换帧后批量给 `y=2.5`（旧数据），契约给 `y=25.0`。

**6) 触发条件**：任何替换 `clip.frames` 列表（或改变长度）的代码。当前**仓库内无生产写入点**（`grep -rn "frames =" Loom` 只命中构造器与 `copy()`），但插件/游戏脚本可直接改 `obj.animator.clips[x].frames`。

**7) 验证**：
```
cd Loom
py -3.13 tests/_tmp/audit_b6r5_02_p7_stale_batch.py
```
实测：
```
换帧后 _np_key = (2739861423168, 3) | 实际 (id,len) = (2739863799488, 3) | 列表已换 = True
evaluate_animations(0.0): time=0.25 -> y=2.5  (旧数据)
同帧集新建 clip.sample(0.25) -> y=25.0  (契约要求的结果)
批量/逐物体一致?  False
-- 对照: 先 sample() 触发 _np_sync, 再 evaluate --  sync 后 y=25.0
```

**8) 影响与等级**：**P2（潜在，非当前崩溃）**。`[REGRESSION]`（`sample()` 原本自动兜住这条路径，批量内核绕开了它）。修复方向：进入分组前与 `sample()` 同点调 `clip._np_sync()`（每组一次即可）。

---

### P-06 · D6 跳过动态刚体 → “动画物体永久不动”的错觉（PROVED，P2，设计取舍需人类确认）

**1) 位置**：`loom_components.py:755-758`（`rb is not None and not rb.is_kinematic` → `blocked += 1; continue`，在 time 推进之前）、`:808-812`（`_ANIM_WARNED_DYNAMIC` 全进程一次性 + `print`）。

**2) 契约/预期**：D6 注释（`:603-605`）与告警文案（`:810-812`）“动态刚体归物理，要让动画驱动请设为 kinematic”。

**3) 路径枚举**（“动画物体不动”的可能原因是否被区分）：
- 物理后端可用且刚体被模拟 → 位姿由物理写，动画“不该”驱动（设计正确）✔
- 物理后端缺失（culverin 缺失 → 播放器打印“物理禁用”）、刚体休眠、无重力且无接触 → 没有任何写者 → **位姿永久冻结** ✘
- 改回 `is_kinematic=True` → 动画从 `time=0` 重新开始（跳过期间时间不累积，`:756` 的 continue 在推进之前）→ 位姿突变 ✘
- 告警：全进程 1 条、只 stdout（release 档无控制台）→ 玩家/美术看不到 ✘

**4) 实际**：见第 7 段。

**5) 差异**：设计意图（物理拥有位姿）与可观测性不匹配：错误配置在运行时表现为“动画根本不播”，与“动画坏了”不可区分；且 `RigidbodyComponent()` 缺省 `is_kinematic=False`，用户加刚体即命中。

**6) 触发条件**：Animator + 默认刚体（动态）；或物理不可用环境下同配置。

**7) 验证**：
```
cd Loom
py -3.13 tests/_tmp/audit_b6r5_02_p5_d6_dynamic.py
```
实测：
```
-- 动态刚体 + Animator: 600 个逻辑帧只跑动画 (不动物理) --
   y=0.0  an.time=0.0  stats={'advanced': 0, 'blocked_dynamic': 1}  playing=True
   告警输出 (全程只 1 条): ['[动画] 1 个物体同时有动态刚体与 Animator: 动画不驱动动态刚体(...)']
-- 若物理没有推进它: 120 帧位姿集合大小 = 1 | 位姿 = (0, 0, 0)
-- 把刚体改回 kinematic 后: an.time=0.0167 y=0.1667 (跳过期间 120 帧未推进时间)
-- 代码事实: 引用 _phys/physics/bridge 的次数 = 0 ; is_kinematic 次数 = 1
```

**8) 影响与等级**：**P2（可观测性/配置陷阱）**，不是数值错误。是否要“无物理时回退动画驱动”属路线选择 → Q3。

---

### P-07 · `__eq__` 内容比较与 `hash`=身份并存 + `copy()` 浅共享（PROVED，P2 边界）

**1) 位置**：`loom_components.py:363-372`（`__eq__` 比较 `loop_mode + frames`；`__hash__ = object.__hash__`）、`:374-384 copy`（`list(v) if isinstance(v, list) else v`）、`undo.py:126`（用 copy 做快照）。

**2) 契约/预期**：`__eq__` 用途被限定为“undo 快照比较”（`:356-362`）；`copy()` 的契约是“值隔离 / 双向不污染”（`:374-379`、`undo.py:225-227`）。

**3) 路径枚举**（容器四种用法）：
- list / `in` / `==`：走 `__eq__`（内容相等 → True）✔
- dict/set 直接查（`groups.get(clip)`、`set([a,b])`）：走身份 hash（不合并）——注释已声明“只影响分组粒度”✔
- 身份 hash + 内容 eq 的混合读者（`{a:1}.get(b)` → None，而 `b in [a]` → True）：语义不对称，本仓当前无此用法 ✔（潜在误用面）
- `copy()` 遇非 list 可变值（numpy 数组）：`isinstance(v, list)` 为 False → **引用共享** → 模型↔快照值隔离被打破；两个不同实例的数组做 `==` 抛 `ValueError` ✘

**4) 实际**：见第 7 段。

**5) 差异**：规范数据（frame 值是 list/tuple）下隔离与比较都成立；非规范数据下隔离失效，`__eq__` 从“比较”变成“抛异常”。

**6) 触发条件**：脚本/插件把 numpy 数组塞进 `clip.frames[i][position]`（`AnimationClip` 不校验帧值类型），随后 undo/commit 或原地改数组。

**7) 验证**：
```
cd Loom
py -3.13 tests/_tmp/audit_b6r5_02_p6_clip_eq.py
py -3.13 tests/_tmp/audit_b6r5_02_p6b_copy_speed.py
```
实测：
```
a == b (内容相等) = True | hash 相等 = False | b in [a] = True | {a:1}.get(b) = None | set([a,b]) = 2
tuple 帧 vs list 帧 == : False (值相同, 类型不同 -> 不等)
n1 == n2 -> ValueError: The truth value of an array with more than one element is ambiguous
copy 的 frame0.position is 源数组 ? True ; 原地改模型数组后 -> 快照值 = [99. 77.  3.]  <-- 值隔离被打破
```

**8) 影响与等级**：**P2（边界，非规范数据）/ P3（类型敏感的内容相等）**。同源附带发现：`an.speed` 是公开属性，绕过 `set_speed` 直接赋非数值会让**整条逻辑帧**抛 `TypeError`（`:764`，实测 `can not multiply sequence by non-int of type float`），存盘则 `ValueError`（`:634`）。单物体坏值放大为全局帧失败 → 建议对非有限 speed 走“单物体降级”而非抛出（P3）。

---

### D-01 · undo clips 值拷贝是否双向隔离（DISPROVED，隔离成立）

**1) 位置**：`undo.py:121-128`（`{name: clip.copy()}` + 第 4 槽 speed）、`:219-240`（apply 时**再** copy 一次、兼容 3 元旧快照、清 `time/playing`）。

**2) 契约**：`:225-227`“值隔离是双向的：存快照时拷、写回模型时也拷”。

**3) 路径枚举**（四方向，全部实测）：改快照→模型；改模型→快照；apply 后改模型→快照；apply 后改快照→模型。

**4) 实际**：四方向均不串（`audit_b6r5_02_p4b_undo_bidir.py`）。

**5) 差异**：无（规范 list/tuple 数据）。**6) 触发**：任意 undo/redo、关键帧编辑、变速、loop_mode 改动。

**7) 验证**：
```
cd Loom
py -3.13 tests/_tmp/audit_b6r5_02_p4b_undo_bidir.py
```
```
快照 clips 是同一 dict 对象? False | 快照 clip 是同一对象? False | len=4 speed=1.5
方向1 模型 frame0 = (0.0, 0.0, 0.0) | 模型 loop_mode = once
方向2 快照 frame1 = (0.0, 1.0, 0.0) | 快照 loop_mode = pingpong
方向3 还原后 frame0=(9,9,9) speed=1.5 time/playing=0.0 False ; 改模型后快照 frame0=(9,9,9) speed=1.5
方向4 改快照后 模型 frame0 = (42.0, 42.0, 42.0)
同内容两次快照相等 = True
```

**8) 判定**：**DISPROVED**（无 bug）；唯一例外是 P-07 的非 list 可变值。

---

### D-02 · 段次序与“每帧一次推进”（DISPROVED，三处一致）

**1) 位置**：`engine.py:1229`（pipe）、`:1254`（串行）、`:1538`（`_advance_logic` 逃生门）、`loom_render.py:897-915`（`_escape_door_step`）与 `:938/977`（render 的二选一）、`editor.py:2411-2415`（宿主先推进则消费标记）、`scene_driver.py:764/870/882`。

**2) 契约**：`3a35f8f` 提交信息“逻辑帧次序改 脚本→动画→物理，pipe 开/关 10 帧后位姿逐位一致”；`loom_render.py:1041-1049`“与分离路径对齐”。

**3) 路径枚举**（每帧是否可能推进两次）：
- `GLEngine._logic_frame` 内部 pipe/串行二选一（`:1229` vs `:1254`）→ 每逻辑步 1 次 ✔
- `advance_logic` 只调 `_logic_frame`（分离）或在 NO_SPLIT 时走 else 四行（`:1538`）→ 二选一 ✔
- `EditorApp.render`：`advance_logic` 后把 `_advanced_this_frame` 置 False 并自行绘制，**不调用** `RenderMixin.render` → 无第二次 ✔
- `RenderMixin.render`：`_ensure_split()` 非 None → 时钟推进（`_logic_frame`）；为 None → `_escape_door_step`（`:977`）→ 二选一 ✔
- `SceneDriver.render_frame`：分离分支 `:870 clock.advance`（→`_logic_frame`）后 return；否则 `:882` 绑死四行 → 二选一 ✔
结论：每帧最多命中 1 个动画调用点。

**4) 实际**：`test_animation_base.py` ⑤ 断言段次序 `[scripts, animations, physics, audio]` 且 10 帧后位姿逐位一致，本审计复跑 ALL PASS；静态阅读 5 个点次序一致。

**5) 差异**：无。**6) 触发**：任意播放/管线配置。

**7) 验证**：`cd Loom; py -3.13 tests/test_animation_base.py` → `ALL PASS`（含 ⑤ 段次序/位姿断言）。

**8) 判定**：**DISPROVED**。

---

### D-03 · 0/1 帧、speed=0、超大 dt 边界（DISPROVED：不崩、语义与旧实现一致）

**3) 路径枚举 / 4) 实际**（`audit_b6r5_02_p4_edges.py`）：
```
0 帧 + loop + 3x dt=0.1        fast=False an.time=0.0  y=0.0 playing=True   (无崩溃; 旧实现同 continue)
1 帧 time=0 + loop             fast=False an.time=0.3  y=1.0 playing=True
1 帧 time=0 + once             fast=False an.time=0.3  y=1.0 playing=True   (不停播; 旧实现 duration>0 条件同)
1 帧 time=0.5 + once 0.3/0.3   fast=False an.time=0.5  y=1.0 playing=False  (新语义正确停末帧)
2 帧 loop + speed=0 + 5x 0.1   fast=True  an.time=0.0  y=0.0 playing=True   (冻结, 契约)
2 帧 once + speed=0            fast=True  an.time=0.0  y=0.0 playing=True
2 帧 loop dt=3.6               fast=True  an.time=0.6  y=6.0 playing=True   (跨周期规范化)
```

**5) 差异**：仅非法 `loop_mode`（U-02）与负相位（P-02）。**8) 判定**：**DISPROVED**（无崩溃；“once+单帧 time=0 永不停播”与旧实现同，非 C1 回归）。

---

### D-04 · animator 序列化契约（DISPROVED）

**1) 位置**：`loom_components.py:620-669`、`sceneio.py:479/629-636`。

**3) 路径枚举**（写侧 4 分支：无 animator / 有 / speed==1.0 / speed!=1.0；读侧 3 分支：无 `clip_meta` / 合法 / 非法值）。

**4) 实际**：`test_animation_base.py` ④ 全绿：`time/playing` 不落盘、`speed` 往返、`clip_meta` 往返、旧文件（无 speed/clip_meta）兼容、`SCENE_VERSION` 仍 11。本审计另核：`speed=0.0`/负数会写盘（`!= 1.0` 判据）、非法 `loop_mode` 不写（`:640` 白名单）。

**5) 差异**：无（规范值域内）；边界见 P-07 末尾（非数值 speed 存盘抛错）。**8) 判定**：**DISPROVED**。

---

### D-05 · `tuple.__new__(Point3D, ...)` 语义（DISPROVED）

**1) 位置**：`loom_components.py:608-611,845,854`。**3) 路径枚举**：`P3NEW` 只在批量 position/rotation 写回用；慢路径/endpoint/fallback 用 `_write_pose`（走 `Point3D(...)`）。

**4) 实际**：探针 P-01 输出 `isinstance(..., Point3D) = True`、`.x/.y/.z` 可读、`== tuple` 成立。**8) 判定**：**DISPROVED**。

---

### U-01 · P-01 在编辑器播放态的真实可达链（UNKNOWN）

已证：只要 transform 里是 tuple，`undo.snapshot`/`_emit_object` 必崩。
未证：编辑器“播放态”下，检查器编辑 / 撤销 / 存盘是否真的会对**已被动画写过**的物体调用上述入口（本审计未启动 GUI 会话）。
**需要的信息**：一次真实 GUI 播放会话（或 `--auto-close` 脚本）里播放中改某物体 visible、按撤销、按保存，观察是否出 `AttributeError`。
**建议探针**：离屏 `EditorApp` + `load_scene` + 上述裁剪片段场景 + `toggle_play` 若干帧 + `commit_model`/`_save_scene`。

### U-02 · 非法 `loop_mode` 的期望策略（UNKNOWN）

实测：`loop_mode=bogus` 时求值器落 `:795-797 else`（不归一），`an.time` 无界增长（12 帧后 3.6），但每帧批量 `ok=False` 回落 `sample()` 又按 loop 取模 → 看到的行为像 loop，`seek()` 却只认 `once/pingpong`（`:574-585`）。无告警、无异常。允许值集合只在 `animator_to_dict/from_dict` 与 EAI 侧收敛，`AnimationClip(...)` 与属性赋值不校验。
**需要的信息**：设计上“非法 loop_mode”属于拒绝、归一为 inherit、还是告警放行。

### U-03 · prefab 是否属于 D7 闸门范围（UNKNOWN）

P-04 已证技术缺口；缺的是“范围定义”（prefab 是资产而非场景，`PREFAB_VERSION` 独立）。需人类确认后才知道是“补闸”还是“prefab 允许跨版本漂移”。

---

## 3. 统计

| 判定 | 数量 | 编号 |
|---|---|---|
| P-PROVED | 7 | P-01(P0)、P-02(P1)、P-03(P1)、P-04(P2)、P-05(P2)、P-06(P2)、P-07(P2/P3) |
| P-DISPROVED | 5 | D-01、D-02、D-03、D-04、D-05 |
| P-UNKNOWN | 3 | U-01、U-02、U-03 |
| P-CONTRADICTION | 0 | 本批未出现“证伪成功 + 证真成功”的互斥对：P-01/P-02/P-05/P-07 的证伪链在路径枚举阶段即发现反例（`:847` / `:773-781` / `:798` / `:382`），未进入“全路径无 bug”的成立态，因此不存在需回查的矛盾 |
| 跳过登记 | 8 | SKIP-01…SKIP-08 |

`[REGRESSION]`（由 C1 diff 引入）：P-01、P-02、P-05。批次外接力（不计入 C1）：P-03 由 `1d22e60` 修复。

---

## 4. 修复建议排序（只给方向，不含代码）

1. **P-01（P0）**：常量通道写回统一为 `Point3D`（或把 `const` 缓存成 `Point3D` 复用）；补“只有位置恒定（无 0 分量）+ 旋转在变”的回归断言，断言 `type(m.transform._position) is Point3D` 且 `undo.snapshot` 可跑。
2. **P-02（P1）**：once 分支对 phase 做与 `seek` 一致的非负夹取（或显式拒绝 once+负速），补“慢路径 vs 批量在负相位逐位一致”的对拍。
3. **P-05（P2）**：进入分组前按组调一次 `_np_sync()`；补“换帧后批量/逐物体一致”的回归（现有对拍只在 `[0,dur)` 取样）。
4. **P-07（P2/P3）**：`copy()` 对非 list 序列做深拷贝或显式拒绝；`__eq__` 对含 ndarray 的帧给确定语义（先转 list）；对非有限 speed 单物体降级。
5. **P-06（P2）**：把“动态刚体跳过动画”在 UI/EAI 侧可查询（不只 stdout），或在物理不可用时回退动画驱动（待人类裁决）。
6. **P-04（P2）**：prefab 顶层写 `min_engine_version` 并在 `load_prefab` 过闸（若人类认定 prefab 属闸门范围）。

---

## 5. 需要人类裁决的封闭问题

- **Q1（P-01 修复口径）**：常量通道写回统一为 `Point3D`（A，推荐）还是允许 `tuple` 并改所有读取点为索引访问（B）？A 代价：每物体每帧多一次 namedtuple 构造（~0.12us）；B 代价：要清理 `snapshot`/`_emit_object`/`instantiate_prefab`/脚本 API 的 `.x` 依赖面。
- **Q2（once + 倒放语义）**：`speed<0` 在非循环片段上应 A 夹取到 `[0,dur]`（与 `seek` 一致，推荐）/ B 从末帧反向播到 0 后停 / C 直接拒绝（`set_speed` 在 once 片段上报错）？
- **Q3（D6 与物理不可用）**：当物理后端缺失或刚体未被模拟时，动画应 A 回退驱动这些动态刚体（推荐）/ B 保持跳过但在 UI 明确标注该物体“位姿归物理”/ C 加载时直接报错要求改 kinematic？

---

## 6. 工作区状态留痕

- 审计开始时 `git status --porcelain` 仅有 `?? tools/lint_except_dist/`、`?? tools/loom_lint_except.py`（与本模块无关）。
- 审计过程中并发批次产生改动：Q-VER-1（1d22e60）已提交；结束时在途改动为 `Loom/engine.py`、`Loom/loom_render.py`、`Loom/fastpath.py`、`Loom/physics_bridge.py`、`Loom/physics_pipe.py`、`Loom/loom_assets.py`、`Loom/loom_profiler.py`、`Loom/ckernels/loom_kernels.c`、`Loom/tests/test_bucket_pack.py` 等（D1/D2 收尾）。
- **在途改动不涉及** `Loom/loom_components.py`、`Loom/undo.py`、`Loom/loom_frame_components.py`、`Loom/sceneio.py`、`Loom/scene_driver.py`（后两者在 1d22e60 之后无改动）→ 本文对 C1 的结论与探针实测可直接复现；行号以 `d635f35` 为准并已在各条注明。
- 本审计只新增：`Loom/tests/_tmp/audit_b6r5_02_*.py`（探针）与本报告；未修改任何受跟踪源码/测试。
