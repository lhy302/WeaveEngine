# 调研报告 beta6-03：动画系统底座（骨骼/蒙皮 → 状态机 → 动画事件）

> 编号：03（动画系统底座）
> 日期：2026-11-09
> 范围：**只调研，不实现**。本文不修改任何受跟踪文件；试验脚本全部落在 `Loom/tests/_tmp/research_03_*.py`（`.gitignore` 规则见 `Loom/.gitignore:20` "tests/_tmp/*"）。
> 方法：源码逐行阅读（file:line）+ 可执行探针实测（PowerShell 命令见各节与附录 A）。
> 结论口径：凡写"实测"= 附录 A 探针在本机跑出的输出；凡写"引用"= 源码行号，可 grep 复核。

---

## 0. 结论速览（先给判断，后面给证据）

1. **现有"动画"= 单物体级的 TRS 关键帧线性插值**，只有"播放/停止/循环开关"，**没有时间轴、没有播放头、没有变速、没有 seek、没有每 clip 循环模式、没有事件、没有状态机**；旋转通道是**欧拉角弧度**直接线性插值（跨 ±180° 走长弧）。
2. **当前底座已有 4 个会在"上骨骼/上状态机"时爆炸的硬伤**（均实测）：
   - 一次性动画在 `t == duration` 时**倒回第 0 帧**（`sample()` 无条件取模）；
   - 大 dt 跨末帧时一次性动画**回绕到中间相位**再停播（末帧丢失）；
   - `time` 一帧只减一次 `duration`，跨多周期不规范化（事件计数无从下手）；
   - **undo 快照与模型共享同一个 clips 字典**（别名），撤销关键帧编辑会是假撤销。
3. **动画与物理/脚本的"写者优先级"没有定义**，而且两条路径**胜负相反**（实测段次序）：物理管线开 → 动画先写、物理回读后写（动画被覆盖）；管线关/降级 → 物理先、动画后（动画获胜）。同一场景换个开关行为就变。
4. **求值层必须批量化**才谈得上"每个角色一个 animator"：现实现 **500 个动画物体 = 12.741 ms/逻辑帧**（1000 = 27.123 ms）；同语义 SoA 批量求值 **0.133 ms**（68.5x）。这是"底座"批次的第一优先级，比骨骼更重要。
5. **骨骼/蒙皮：beta6 建议只做「数据模型 + 编辑器可视化」，不做 GPU 蒙皮**。理由（均为实测/引用）：GL 后端是 **OpenGL 3.3 core**（`loom_glfw_window.py:123-125`），**没有 SSBO**，只有 64KB UBO / 14 个顶点 UBO 槽 / 256B 偏移对齐；顶点属性只剩 4 个空槽（现用 10/16）；`moderngl` 不接受 ubyte 顶点格式；更关键的是**没有任何骨骼资产来源**（只有 `.obj`，无 glTF/FBX，`Mesh` 无 joints/weights）。强行上蒙皮要同时改顶点格式、实例 stride、桶共享键、影子 pass、GL/VK 两套 draw、打包运行时——**双份复制**，与版本计划"先铺 Pass 抽象"的判断同源。
6. **状态机最小形态**建议：`状态(名, clip, loopMode, speed)` + `过渡(from,to,条件,exitTime,duration=0)` + `参数(bool/trigger/float/int)`；**脚本只写参数、只收事件，不直接写 pose**；保留 `animator.play()` 为兼容 API（内部转 `force_state`），避免"脚本一套逻辑 + 状态机一套逻辑"。
7. **必须现在定死、否则返工的 5 个集成点**：① 动画写入的"层"（local TRS 还是 pose 层）与物理/脚本优先级；② 时间基准（fixed_dt vs render_dt，两条路径现在不同）；③ 序列化是否含 `time/playing` 与 undo 值隔离；④ 事件派发时机（绝不能进 `update_animations`）；⑤ 求值输出的宿主契约（现在直接写 `m.position`）。

---

## ① 现状（证据）

### 1.1 数据模型：clip 是"帧列表 + 三通道"，组件是"名字→clip"

**引用**

| 对象 | 位置 | 内容 |
|---|---|---|
| `AnimationClip` | `Loom/loom_components.py:322-457` | `frames` = `[{time, position?, rotation?, scale?}, ...]`；`_CHANNELS = ('position','rotation','scale')`（`:337`）；`duration = frames[-1]['time']`（`:347-349`） |
| `AnimationClip.sample(t)` | `Loom/loom_components.py:403-435` | numpy 快路径：`t % dur` → `searchsorted` 定段 → 逐通道 `a + (b-a)*f` |
| 慢路径（语义基准） | `Loom/loom_components.py:437-457` | 线性扫、逐帧线性插值、末帧保持原对象 |
| `AnimatorComponent` | `Loom/loom_components.py:460-486` | `clips: dict[name→clip]`、`current`、`time`、`playing`、`loop`；`play(name, restart)`、`stop()` |
| 每帧推进 | `Loom/loom_frame_components.py:80-101` | `an.time += dt` → `clip.sample` → 写 `m.position / m.rotation / m.set_scale()`；末尾 `time -= duration`（循环）或 `playing=False`（一次） |
| 播放器侧复刻 | `Loom/scene_driver.py:1251-1272` | 与上面**逐行相同**的第二份实现（`SceneDriver` 用） |

**实测（附录 A · `research_03_probe_semantics.py`）**

```
E1 AnimatorComponent 属性  ['clips','ctype','current','loop','owner','play','playing','stop','time']
E2 AnimationClip 属性      ['duration','frames','sample']
```

→ 没有 `speed / paused / normalized_time / state / params / events / skeleton` 任何一个字段。

### 1.2 插值：只有分段线性，没有缓动、没有四元数

**实测**（同一探针，A 组）：

| 用例 | 输入 | 实测输出 | 结论 |
|---|---|---|---|
| A1 | 帧 (0,0,0)→(0.5,10,0)→(1.0,10,10)，t=0.25 | `(5.0, 0.0, 0.0)` | 纯线性，与公式吻合 |
| A2 | 同上 t=0.75 | `(10.0, 5.0, 0.0)` | 段内线性、段间 C0 不 C1 |
| B1 | rotation 170° → −170°，t=0.5 | `[0.0, 0.0, 0.0]`（度） | **走 340° 长弧**，欧拉线性插值 |
| B2 | 中点是否 ≈0° | `True` | 确认绕远路（无 slerp/最短路径） |

**引用**：旋转矩阵入口 `matlib.mat4_rotation` 直接 `math.cos(rx)`（`Loom/matlib.py:47-71`）→ 内部角度单位是**弧度**；UI 层做度↔弧度换算（`Loom/ui/loom_gui.py:3028-3030`）。物理回写同样用欧拉（`Loom/physics_bridge.py:1333-1337`）。

**全仓关键字命中（命令与结果）**：

```powershell
cd Loom
Get-ChildItem -Recurse -Filter *.py | Where-Object { $_.FullName -notmatch '_tmp' } |
  Select-String -Pattern 'easing|bezier|catmull|hermite|slerp|quaternion' | Measure-Object
# Count = 0
Get-ChildItem -Recurse -Filter *.py | Where-Object { $_.FullName -notmatch '_tmp' } |
  Select-String -Pattern 'timeline|sequencer' | Measure-Object
# Count = 0
```

### 1.3 播放控制：只有一个循环开关，且是"组件级"不是"clip 级"

- `loop` 在 `AnimatorComponent` 上（`loom_components.py:469-475`），不能"idle 循环 + attack 单次"共存。
- `play(name, restart=False)` 切换 clip 时**只要名字不同就清零 time**（`:477-482`），无交叉淡入。
- 循环收尾 `an.time -= clip.duration` **只减一次**（`loom_frame_components.py:97-101`）→ 大 dt 后 `time` 长期越界（实测 C1：`loop=True, dt=3.6, duration=1.0` → `time=2.600`，相位仍对但时间未规范化）。

**实测（附录 A · `research_03_probe_dt.py`）—— 两个真缺陷**：

```
A1 t=0.6  y=6.000 time=0.600 playing=True
A2 t=1.2  y=2.000 time=1.200 playing=False     # 一次性动画末帧应为 y=10
A3 末帧被"回绕"到 0.2s 处 -> y=2.000
B1 4x0.25s: y=0.000 time=1.000 playing=False   # 恰好 t==duration 时倒回第 0 帧
C1 dt=3.6 loop: time=2.600 y=6.000             # 一帧只减 1 个 duration
```

**根因**：`sample()` 在 `dur > 0` 时**无条件** `t = t % dur`（`loom_components.py:410-412`），它不知道 `loop` 语义；而 `update_animations` 在取样**之后**才判 `time >= duration`（`loom_frame_components.py:97-101`）。⇒ **一次性动画永远无法停在末帧**（除非末帧时间恰好等于 0）。

> 注意：`tests/test_animation.py:78-79` 断言 `sample(2.5) → phase 0.5`，即"取模"是 `sample` 的**既有契约**。修复必须落在**求值层**（由 evaluator 按 loopMode 归一化 t 再交给 sample），不能改 `sample` 语义，否则破坏测试与"快慢路径逐位一致"红线（`loom_components.py:330-335`）。

### 1.4 序列化：只存"编排"，不存"播放态"

**引用**（写侧）：

```python
# Loom/sceneio.py:298-303
"animator": None if m.animator is None else {
    "current": m.animator.current,
    "loop": m.animator.loop,
    "clips": {name: [dict(f) for f in clip.frames] ...},
},
```

**引用**（读侧）：`Loom/sceneio.py:448-455`（`_apply_object` 重建 `AnimationClip`）、`Loom/scene_driver.py:86-93`（播放器同一逻辑，第三份重建代码）。

**实测（`research_03_probe_semantics.py` C/D 组）**：

```
C1 播放中 time/playing                (0.3, True)
C2 场景 dict 的 animator 键            ['clips', 'current', 'loop']     # 无 time / playing
C3 单帧关键帧的键                      ['position', 'time']             # 无 easing / interp
C4 重载后 time / playing               (0.0, False)
C5 播放位置丢失 (0.3 -> 0.0)            True
```

→ 存盘=回到起点；这也意味着**"预览播放到一半保存"不可复现**（对状态机/调试是硬伤）。

### 1.5 undo：存了组件但**按引用**存 clips，且清空播放态

**引用**：`Loom/undo.py:121-123`（`'animator': (m.animator.clips, m.animator.current, m.animator.loop)` 三元组，**不拷贝**）；还原 `Loom/undo.py:214-226`（重建/回写三元组，然后 `time=0.0; playing=False`）。

**实测**：

```
D1 snap['animator'][0] is m.animator.clips   True     # 同一字典对象
D2 改快照后原片段帧数                          4        # 从 3 变 4 —— 改快照污染了模型
```

→ 现在"加/删动画组件、切 clip、切 loop"三种操作能撤销（因为只改引用/标量），但**任何关键帧编辑都不可撤销**（一改就同时改了历史快照）。时间轴编辑器上线的第一步必须是这里。

### 1.6 创作/编辑入口：**没有关键帧编辑器**

**引用**

| 位置 | 内容 |
|---|---|
| `Loom/editor.py:1832-1848` | 只有 `add_animator / remove_animator / play_anim / toggle_anim_playing / toggle_anim_loop` |
| `Loom/ui/loom_gui.py:3154-3165` | 检查器只有「循环 / 播放 / 移除」按钮 + clip 下拉 + 「＋加动画组件」 |
| `Loom/agent_commands.py:1966-1996` | EAI `animator` 命令：`action=add|remove|loop|play|clip`，**没有写关键帧的能力** |
| `Loom/agent_commands.py:1532-1536` | 查询面只回 `loop/playing/current/clips(名字列表)`，**不回 time** |

**全仓 clip 构造点**（命令 `grep -rn "AnimationClip(" Loom`）：只有 `sceneio.py:452`、`scene_driver.py:90`、`undo.py:218`、测试 2 处。⇒ **引擎内没有任何"创建/编辑关键帧"的代码路径**，clip 只能手写 JSON 或用脚本构造。

`timeline|sequencer` 全仓 0 命中（§1.2 命令）；`Loom/缺失功能_脚本层模拟清单.md:146-161` 记录了"用协程 `yield self.wait()` 模拟动画事件"的**脚本层兜底**，`:338` 明确写"骨骼动画/状态机需要 GPU 蒙皮"。

### 1.7 编辑态根本不推进动画

**引用**：`Loom/engine.py:1462-1467` —— `advance_logic` 在 `is_playing=False` 时**早退**；`update_animations` 只在 `_logic_frame`（`engine.py:1224 / 1243`）与"逃生门"（`engine.py:1523`、`loom_render.py:887`）被调。

⇒ 检查器里点"播放"（`editor.py:1842-1844` 只翻 `playing` 标志）在**编辑态没有任何可见效果**；要预览动画必须先按全场景播放。这就是"没有预览/没有时间轴"的直接后果。

### 1.8 时间基准两条路径不一致

| 路径 | 调用点 | dt 来源 |
|---|---|---|
| 分离（默认） | `engine.py:1224` / `1243` | `fixed_dt`（逻辑步，30 TPS） |
| 逃生门（NO_SPLIT / logic_fps<=0） | `engine.py:1523`、`loom_render.py:887` | `render_dt`（渲染帧，~84-90 FPS） |
| 播放器 | `scene_driver.py:724`（fixed）/ `:839`（render） | 同上两套 |

两者都按真实时间推进，但：① 逃生门路径**没有暂停/步进语义**（`toggle_logic_paused` 要求 `_ensure_split()`，`engine.py:1532`）；② 分离路径在卡顿帧会用**墙钟下限补步进**（`engine.py:1507-1510` 注释与实现），逃生门不补 → 长时间卡顿后两者动画进度不同；③ 事件检测若按"逻辑帧"或"渲染帧"实现，两边结果不同。

### 1.9 写者冲突：动画、物理、脚本三方无优先级契约

**实测段次序**（附录 A · `research_03_probe_order.py`，用假 pipe 驱动真实 `_logic_frame`）：

```
PIPE 路径:  fixed_update → scripts → pipe_post×3 → audio → ANIMATIONS(写 m.position) → physics_readback(wait_pending) → logic_prep → collision_events → interp.advance
串行路径:  fixed_update → scripts → physics_frame×3 → audio → ANIMATIONS → logic_prep → interp.advance
```

**引用**：`_logic_frame` 段次序声明 `engine.py:1190-1197`；pipe 分支 `engine.py:1214-1234`（脚本 1203 → 投递 1219-1220 → 音频/动画 1223-1224 → 等物理 1227）；串行分支 `engine.py:1235-1247`；物理回读**无条件**写 `m.position/m.rotation`：`physics_bridge.py:1316-1337`。

⇒ 结论（可证伪的断言）：
- **动态刚体 + animator**：开管线时动画被物理覆盖（每帧白算），关管线时动画赢。同一场景两种行为。
- **静态体被动画移动**：`pre_step` 一次性升级 `MOTION_STATIC → KINEMATIC`（`physics_bridge.py:37, 585, 1114-1125`），即"瞬移式运动"，不与物理互推。
- **脚本改 position**：脚本先跑（`engine.py:1200-1203`），动画后写 → 脚本的位移在同一帧被动画覆盖。脚本与动画是**两套并行驱动**。

### 1.10 渲染插值：动画位姿会进插值（这是要保留的好性质）

`update_animations` 在 `_logic_prep` 之前写变换 → `compute_world_matrices` 抓 SoA 平面（`loom_transform.py:62-119, 120-145`）→ `_logic_frame` 尾 `it.advance(planes)`（`engine.py:1258-1265`，`interp_state.py:86-116`）→ 渲染帧按 `alpha` 在 prev/curr 间插值（`loom_transform.py:218-260`）。

⇒ 30 TPS 动画在 90 FPS 下是**平滑**的。这条性质要求：**动画求值仍必须发生在逻辑帧内**，不能改到渲染帧（否则与插值层打架）。

### 1.11 成本实测：现实现不可扩展到"每角色一个 animator"

```powershell
cd Loom; python tests/_tmp/research_03_probe_perf.py
# n=100  update_animations = 2.512 ms / 逻辑帧
# n=500  update_animations = 12.741 ms / 逻辑帧
# n=1000 update_animations = 27.123 ms / 逻辑帧
```

对照 SoA 批量求值（`research_03_probe_perf2.py`，同片段、500 物体、只算 position）：

```
n=500  逐物体求值 = 9.109 ms/逻辑帧
n=500  SoA 批量求值 = 0.133 ms/逻辑帧  (加速 68.5x)
```

⇒ 单物体开销 ≈ 25µs/帧（`searchsorted` + `tolist()` + 3 次 `Point3D` 分配 + 3 次属性 setter）。500 个带动画的物体就吃掉逻辑预算的 38%（30 TPS = 33ms/帧）。

### 1.12 骨骼/蒙皮：engine 源码 0 命中

```powershell
cd Loom
Get-ChildItem -Recurse -Filter *.py | Where-Object { $_.FullName -notmatch '\\tests\\' } |
  Select-String -Pattern 'skeleton|skinned|bone|joint|inverseBind' -CaseSensitive:$false | Measure-Object
# Count = 0
```

全仓（含 tests）21 命中，**全部在本次调研的 probe 脚本里**（`Loom/tests/_tmp/research_03_probe_*.py`）。

**资产侧现状**：
- 只有 `.obj` 导入：`mesh.py:269 load_obj`、`editor.py:734-748`、`agent_commands.py:2192-2200`；`gltf|glb|fbx` 在 engine 源码 0 命中。
- `Mesh` 字段只有 `vertices/faces/face_colors/normals/uvs`（`mesh.py:16-36`）——**没有 joints/weights**。
- 场景只存 `type + params`（`sceneio.py:259-260`），不存几何 → 骨骼蒙皮要另立资产文件（而资产 guid 管线本身是 beta6 的 P2 候选，见 `docs/design/版本计划_Loom0.1.0.beta6_20261109.md:116`）。

### 1.13 `animator` 命中数的口径

版本计划写"61 处"。本次精确统计（命令见附录 A · A.1）：

| 统计范围 | 命中 |
|---|---|
| `Loom/**/*.py` 且排除 `tests/`（出现次数，非行数） | **80** |
| 同范围按行计 | 64 |
| `Loom/tests/*.py`（顶层） | 27 |
| 分布 | `undo.py` 20 / `agent_commands.py` 14 / `editor.py` 12 / `loom_game_object.py` 9 / `sceneio.py` 8 / `ui/loom_gui.py` 5 / 其余 ≤4 |

⇒ "61 处"应是某次按行/按文件的旧计数；**不影响结论**（动画相关代码实际 80 次出现、12 个文件）。

---

## ② 目标设计（含数据/接口草案）

### 2.1 分层（一句话：资产 / 实例 / 求值 / 状态机 / 事件 五层，求值层纯函数、可批量）

```
资产层 (只读共享, 可进场景 JSON 或独立资产文件)
  AnimationClipAsset   ← 帧/轨道 + loopMode + speed + events + (可选) skeleton 引用
  SkeletonAsset        ← 骨骼树 + 逆绑定矩阵
  SkinAsset            ← 每顶点 boneIdx/boneWeight (仅数据, 不渲染)
        │
实例层 (每 GameObject 一份)
  AnimatorInstance     ← 当前 state / clip / clipTime / speed / params / 事件游标
        │
求值层 (纯函数, 无 GPU, 无 python 对象分配最好)
  evaluate(clips, instances, dt) -> PoseSoA / 或 evaluate_one(clip, t, loopMode) -> dict
        │
状态机层 (可选, 由 controller 资产描述)
  step(states, transitions, params) -> state 名 + 触发原因
        │
事件层
  events_crossed(clip, cursor, newTime) -> [(event, 跨周期序号)]  → 排队 → 逻辑帧尾派发
```

**关键设计原则**

1. 求值层**不知道宿主**（engine / scene_driver 共用），杜绝第三份复刻。
2. 求值层**不写物体**：输出 Pose（dict 或 SoA），由绑定层决定写到哪（v1：local TRS；v2：骨骼 TRS）。
3. 状态机**不执行用户代码**：只读写参数；事件与过渡都只是数据。
4. 时间基准统一为**逻辑帧 dt**（`fixed_dt`），逃生门路径把 render_dt 折成"整数个编译步 + 余量"，不再直接传 render_dt。

### 2.2 数据草案（JSON，向后兼容）

**v1（可落地，不改现有 `sample` 语义）**

```jsonc
"animator": {
  "version": 2,
  "current": "run",              // 兼容旧字段
  "loop": true,                  // 兼容旧字段（作为"组件默认 loopMode"）
  "speed": 1.0,                  // 新增
  "playing": false,              // 新增（可选持久化，默认不写盘；见 ⑦Q3）
  "time": 0.0,                   // 新增（可选持久化）
  "clips": {
    "run": {
      "loopMode": "loop",        // "once" | "loop" | "pingpong"；缺省继承组件 loop
      "speed": 1.0,
      "events": [ { "t": 0.5, "name": "footstep", "payload": { "foot": "L" } } ],
      "frames": [                // ★ 沿用旧"帧列表"（三通道同帧）—— 保证逐位一致
        { "time": 0.0, "position": [0,0,0], "rotation": [0,0,0], "scale": [1,1,1] }
      ]
    },
    "idle": { "loopMode": "loop", "frames": [ ... ] },
    "attack": { "loopMode": "once", "frames": [ ... ],
                "events": [ { "t": 0.23, "name": "hit" } ] }
  },
  "params": { "speed": 0.0, "grounded": true, "attack": false },   // 状态机参数
  "controller": null             // 状态机资产 id；null = 单 clip 直放（旧行为）
}
```

**为什么"帧列表"不改成 per-channel curves（强约束）**：`sample()` 的快路径与慢路径要求**逐位一致**（`loom_components.py:326-335` 的注释是红线说明），而快路径的前提正是"三通道全帧齐备 + 时间非降序"。改成"每条通道独立时间轴"会：① 破坏 `tests/test_animation.py` 的 4 条断言；② 破坏 `sceneio` 往返；③ 破坏 `tests/_tmp/anim_np_check.py` 这种逐位对比探针。**需要 per-channel 时间轴时，用 `tracks` 作为可选的第二形态**（新增键，不改旧键语义）：

```jsonc
"clips": { "run": { "tracks": { "position": {"times":[...], "values":[[x,y,z],...], "interp": "linear"},
                               "rotation": {"times":[...], "values":[[x,y,z],...], "interp": "linear"} } } }
```

**骨骼数据（v2，先只做数据 + 可视化）**

```jsonc
"skeleton": {                          // GameObject 或资产文件
  "version": 1,
  "bones": [ { "name": "root", "parent": null, "local_trs": {...},
               "inverse_bind": [16 floats] } ],   // 行主序 4x4（与 matlib 一致）
  "bind_pose": "rest"
}
"skin": {                              // 只存索引/权重声明，不含 GPU 资源
  "version": 1, "skeleton": "<skeleton id>",
  "max_influences": 4,
  "vertices": { "joints": [[i0,i1,i2,i3], ...], "weights": [[w0,w1,w2,w3], ...] },
  "normalized": true                   // 加载时校验；未归一化 → 警告 + 归一化（见 ④ 风险）
}
```

### 2.3 接口草案（签名级，非实现）

```python
# ---------- 资产 ----------
class AnimationClip:                       # 现有类，仅加字段；sample 语义不变
    loop_mode: str                         # "once" | "loop" | "pingpong"
    speed: float
    events: list[ClipEvent]                # (t: float, name: str, payload: dict)
    frames: list[dict]                     # 不变
    def sample(self, t) -> dict: ...       # 不变（红线，逐位）
    def sample_loopaware(self, t, loop_mode) -> dict: ...   # 新增：先归一化再 sample

class AnimatorComponent:                   # 现有类，增量
    # 现有: clips / current / time / playing / loop / play() / stop()
    speed: float
    params: dict
    controller: str | None
    def set_param(self, name, value) -> None: ...
    def set_trigger(self, name) -> None: ...
    def seek(self, t: float) -> None: ...            # 编辑器 scrub
    def cross_fade(self, name, duration=0.0) -> None: ...
    def step(self, dt: float, evq: "EventQueue") -> None: ...   # 由求值层调用

# ---------- 求值（引擎/播放器唯一实现） ----------
def evaluate_instances(instances, dt: float, soa: "PoseSoA", evq) -> None:
    """批量：读 instance 状态 → 写 soa 平面 → 事件入队。O(N) 纯 numpy，无逐物体 Python 分支。"""

def evaluate_one(clip, t: float, loop_mode: str) -> dict:
    """单物体/测试/编辑器 scrub 用；必须与 evaluate_instances 同公式（对拍测试）。"""

# ---------- 状态机 ----------
class AnimStateMachine:
    def update(self, dt: float, params: dict, cursor: "ClipCursor") -> str:
        """返回当前 state 名；不做 IO、不调用户代码。"""
class Transition:
    from_state: str; to_state: str
    conditions: list["Cond"]        # ("param", name, op, value) / ("trigger", name) / ("exit_time", 0.9)
    duration: float                 # 0 = 瞬切
    has_exit_time: bool

# ---------- 事件 ----------
class ClipEvent: t: float; name: str; payload: dict
class EventQueue:
    def push(self, obj, clip_name, event_name, payload, wrap_index: int) -> None: ...
    def drain(self, dispatch) -> int:      # 逻辑帧尾统一派发，返回条数

# ---------- 脚本侧（唯一入口，避免两套逻辑） ----------
# 脚本可以: animator.set_param / set_trigger / seek / cross_fade / play(兼容)
# 脚本不可以: 直接写 pose、直接改 clip.frames（要改必须走编辑器命令 = 可撤销）
```

### 2.4 骨骼/蒙皮：双后端最小实现路径（实测限制表）

**GL 后端能力（实测，附录 A · `research_03_probe_glcaps*.py`）**

```
[GL] version='3.3.0 NVIDIA 582.78'   renderer='NVIDIA GeForce GTX 1050 Ti/PCIe/SSE2'
[GL] GL_MAX_VERTEX_ATTRIBS = 16
[GL] GL_MAX_VERTEX_UNIFORM_BLOCKS = 14
[GL] GL_MAX_UNIFORM_BLOCK_SIZE = 65536
[GL] GL_MAX_VERTEX_TEXTURE_IMAGE_UNITS = 32
[GL] #version 330 + std430 buffer(SSBO) 编译失败: syntax error, unexpected identifier "Bones"
[GL]   → GL 3.3 上下文里 SSBO 语法不被接受（盲证据，见下方警告）
[GL] GL_UNIFORM_BUFFER_OFFSET_ALIGNMENT = 256
[GL] UBO 4KB bind_to_uniform_block OK
[GL] #version 330 蒙皮 VS (UBO 64 骨骼 + 4 权重) 编译/链接 OK
[GL] 顶点着色器 texelFetch(sampler2D 骨骼矩阵) 编译 OK
[GL] 蒙皮 VAO (4 顶点属性 + 2 蒙皮实例属性) 创建 OK; 主 pass 合计 12/16 槽
[GL] 骨骼索引实例属性格式 '4B' 拒绝 / '4b' 拒绝 / '4u' 接受 / '4f' 接受
```

> ⚠️ 两条实测陷阱：
> 1. `moderngl` 的 `bind_to_storage_buffer()` 在 3.3 上下文里**不抛异常**（库不检查 GL 错误，绑定是静默无效的）→ **不能靠 try/except 探测能力**。
> 2. `ctx.info` 的键集是 moderngl 固定白名单，**不含** `GL_MAX_SHADER_STORAGE_BLOCK_SIZE`（查询返回 `None` 是"没这个键"，不是"驱动报 0"）→ 不能把 `None` 当驱动能力证据。
> 真正可判定的证据是：3.3 核心上下文 + `#version 330` 下 SSBO 语法**编译失败**（上一条输出），因为 shader storage block 是 GL 4.3 特性。

**VK 后端能力（实测，附录 A · `research_03_probe_vkcaps*.py`；wgpu 0.32，后端 = Vulkan）**

```
[VK] adapter: vendor='NVIDIA' device='NVIDIA GeForce GTX 1050 Ti' backend_type='Vulkan'
[VK-dev] max-vertex-attributes = 32
[VK-dev] max-vertex-buffers = 16
[VK-dev] max-vertex-buffer-array-stride = 2048
[VK-dev] max-uniform-buffer-binding-size = 65536
[VK-dev] max-storage-buffer-binding-size = 2147483644
[VK-dev] max-bind-groups = 8
[VK-dev] min-uniform-buffer-offset-alignment = 256
[VK-dev] min-storage-buffer-offset-alignment = 32
[VK-dev] vertex-stage read-only storage buffer 4KB bind group OK
```

**现状管线约束（引用）**

| 项目 | GL | VK |
|---|---|---|
| 顶点格式 | `'3f 3f 4f 2f'` = 48B（`loom_model_gpu.py:218-222`） | `_VERT_BYTES = 12*4` = 48B（`vk_renderer.py:48, 831-838`） |
| 实例 stride | **96B** = world16 + sat4 + color4（`loom_model_gpu.py:199-209`） | **160B** = world16 + nm16 + sat4 + color4（`vk_renderer.py:50, 1597-1602`） |
| 属性槽用量 | 4 顶点 + 6 实例 = **10 / 16** | 4 顶点 + 6 实例 = 10（上限 32） |
| 几何共享 | 按 `_mesh_key`（primitive+params+normal_mode+材质 GUID）分桶共享 VBO（`loom_model_gpu.py:92-117, 164-196`） | 同桶 + 重排（`bucket_layout`，`vk_renderer.py:474-490`） |
| draw 调用点（蒙皮都要覆盖） | 主 pass `loom_render.py:805`；阴影 `loom_shadow.py:103-107` | 主 pass `vk_renderer.py:2051-2053`；阴影 `:1982-1984`；桶重排 UI 路径 `:1939-1942` |
| 阴影程序 | 独立 VAO（顶点只有 `in_pos`，实例只有 world）：`loom_model_gpu.py:223-229` | 独立 shadow 管线 + `_inst_sha_buf`（`:789-820, 1983-1984`） |

**三条可选路径及取舍（实测支撑）**

| 路径 | GL 3.3 | VK(wgpu) | 结论 |
|---|---|---|---|
| A. 每实例骨骼调色板进 **UBO**（`mat4[64]`），**每个蒙皮物体一次 draw**（动态偏移 256B 对齐） | ✅ 编译 OK，`MAX_UNIFORM_BLOCK_SIZE=65536`→最多 1024 骨骼；14 个顶点 UBO 块；偏移对齐 256 | ✅ uniform binding 64KB、offset 对齐 256 | **最稳但破坏批**：N 个角色 = N 次 draw（现每桶 1 次）；与 `bucket_layout` 重排/`first_instance` 机制冲突 |
| B. 骨骼矩阵进 **RGBA32F 纹理**（每骨骼 4 texel），**顶点着色器 texelFetch/textureLoad**；每实例加 1 个 `bone_base` 属性 | ✅ texelFetch 编译 OK；`MAX_VERTEX_TEXTURE_IMAGE_UNITS=32` | ⚠️ 需在 wgpu 侧验证 vertex 阶段 `textureLoad` + 采样纹理绑定（**本次未实测**，属 ⑦ 待裁决风险） | **能保留实例批**；顶点侧零新 UBO；代价是每角色多一张小纹理 + 采样指令 |
| C. **SSBO/StorageBuffer** 直接存调色板 | ❌ **GL 3.3 无 SSBO**（`#version 330 + std430 + buffer 块` 编译失败实测；moderngl bind 静默无效） | ✅ 2GB、vertex 可读 | **单后端**，违反"双后端逐像素等价"基线 → 不可取 |

**顶点数据增量（两后端必须字节一致）**

- 骨索引 4×f32 + 骨权重 4×f32 = **32B/顶点** → 48B → **80B（+67% 顶点带宽）**。
- `moderngl` 不接受 `'4B'/'4b'`（实测拒绝）→ **不能用 ubyte 索引**；`'4u'` 虽被接受但 moderngl 走的是归一化 float 指针语义，**语义不可靠**（未实测出正确性）→ 结论：**索引也用 f32**，与 VK 的 `float32x4` 完全对齐。
- 若用 B 方案：实例 stride 96B(G) / 160B(V) 各加 1 个 f32（`bone_base`）→ 100B / 176B（VK 侧 ≤2048 上限，安全）。

**beta6 建议：做 ①数据模型 + ②编辑器可视化，不做 GPU 蒙皮**

依据（每条都可复核）：

1. **没有数据来源**：无 glTF/FBX 导入（§1.12），`Mesh` 无 joints/weights；先做渲染只能拿"程序化骨架"演示，验证价值低。
2. **改动面是乘法**：顶点格式 + 实例 stride + 桶共享键（`_mesh_key`）+ 阴影 pass + GL/VK 两套 draw + `_ensure_instances` 重排 + 打包运行时（`player_runtime`）——本报告 §2.4 表格列出 **5 处 draw 调用点 + 2 个 VAO 构造点**，每处都要改两遍。
3. **前置未就绪**：求值层还没批量化（12.7ms@500），骨骼矩阵每帧上传又是纯增量开销；先把求值层批量化（批次 1），蒙皮收益才成立。
4. **版本计划主审倾向已选 A**（`docs/design/版本计划_Loom0.1.0.beta6_20261109.md:130` Q5=A：beta6 不碰）。
5. **但接口要现在定死**：`SkinAsset` 的顶点属性布局（§2.4 增量表）、`bone_base` 实例属性、调色板纹理/UBO 二选一、以及"骨骼矩阵行主序/列主序"约定——这些如果晚定，顶点格式一改就要重导资产、重做影子 pass。

**编辑器可视化范围（不做渲染仍可交付）**：层级/检查器里的**骨骼树**（拖拽选骨、显示世界矩阵/逆绑定矩阵数值）、**骨骼 gizmo**（复用现有 gizmo 线框绘制 `engine.draw_lines`）、**包围盒/权重来源统计**（每顶点影响数分布、未归一化告警）、**蒙皮"预览形变"用 CPU 端点计算**（只画少量顶点/线框，不做全网格 GPU 蒙皮）。

### 2.5 状态机最小形态

```jsonc
"controller": {
  "version": 1,
  "params": { "speed": "float", "grounded": "bool", "attack": "trigger" },
  "default_state": "idle",
  "states": {
    "idle":  { "clip": "idle",  "loopMode": "loop", "speed": 1.0 },
    "run":   { "clip": "run",   "loopMode": "loop", "speedFrom": "speed" },
    "attack":{ "clip": "attack","loopMode": "once", "exit_time": 0.95 }
  },
  "transitions": [
    { "from": "idle", "to": "run",    "conditions": [["speed", ">", 0.1]] },
    { "from": "run",  "to": "idle",   "conditions": [["speed", "<=", 0.1]] },
    { "from": "*",    "to": "attack", "conditions": [["trigger", "attack"]], "duration": 0.1, "interrupt": true },
    { "from": "attack","to": "idle",  "conditions": [["exit_time", 0.95]], "has_exit_time": true }
  ]
}
```

**推进时机**（必须写进设计，否则一定返工）：`scripts → 状态机 → 求值 → 物理 → 事件派发`（或"scripts → 状态机 → 物理 → 求值 → 事件"），**状态机只在逻辑帧跑一次**，参数写入在同一逻辑帧生效；`trigger` 参数**消费即清**（否则会重复触发）。

**与现有脚本系统的分工（避免两套逻辑）**

| 能力 | 归属 | 理由 |
|---|---|---|
| 写参数（速度/是否落地/攻击） | 脚本（`set_param` / `set_trigger`） | 游戏逻辑在脚本，状态机只做"参数→动画"映射 |
| 决定播哪段动画 | **状态机**（`controller` 存在时）；无 controller 时 = 旧 `play()` | 单一权威，避免脚本与状态机各写一份分支 |
| 直接 `play(name)` | 保留（兼容 + 调试），内部转 `force_state(name)`，**并置 `forced=True` 直到下次参数驱动** | 不破坏 `tests/test_animation.py:104` 与既有 EAI `animator action=clip` |
| 事件回调 | 引擎排队派发 → 脚本 `on_anim_event(name, payload)` 钩子 + EventBus `emit('anim:<clip>:<event>')` | 现有 hook 机制可复用（`engine.py:1644-1647` 的钩子派发范式） |
| 时间轴精确等待 | **不再用** `yield self.wait(...)`（`scripts.py:384`，按 dt 累计、与 clip 时间无关） | 现有脚本层兜底会在 clip 被打断/变速时错位（`缺失功能_脚本层模拟清单.md:146-161`） |

### 2.6 事件：跨边界检测 + 排队派发

**契约草案**

```
每逻辑帧对每个 animator:
  t0 = clipTime ; t1 = clipTime + dt*speed
  对 clip.events 中 e.t ∈ (t0, t1] 命中 → push(obj, clip, e.name, e.payload, wrap_index)
  跨周期: 若 loopMode == "loop" 且 (t1 - t0) 跨越 N 次 duration → 对每个事件按周期重复命中
派发点: 逻辑帧尾（与 collide 事件同段, engine.py:1248-1257），主线程，用户代码只在这里跑
```

**为什么必须排队**（不给实现者自由度）：`update_animations` 在**物理管线待同步区**内执行（`engine.py:1223-1227`，实测段次序 §1.9）。在这里直接调用户脚本 = 用户代码跑在"物理 worker 还在跑、帧尾同步点之前"，一旦脚本抛异常/改物理体，会把管线状态搞脏（现有脚本异常隔离只在 `_call_collision_cb` 与 `_run_scripts` 有）。⇒ 事件**必须**入队，在 `engine.py:1248-1257` 同段派发。

**`once` 语义**：`once` 动画播完不自动切状态（除非 controller 有 `exit_time` 过渡），避免"播完悄悄变 idle"这种隐式行为——这与 Unity 默认相反，但要写清（见 ⑦Q5）。

---

## ③ 分步落地计划（每步可验收、含测试点）

> 命名约定：新增内核 `Loom/loom_anim.py`（求值 + 状态机，纯逻辑，不 import moderngl/wgpu）；`Loom/loom_skin.py` 留到批次 2。
> 每批结束都要跑既有回归：`python tests/run_all.py`（若存在）或逐文件跑 `test_animation.py / test_physics_runtime.py / test_e2e_*.py`。

### 批次 1 · 底座（数据 + 序列化 + 播放）—— **beta6 应做**

| 步 | 内容 | 改动面 | 验收标准 | 测试点（新增/扩展） |
|---|---|---|---|---|
| **S1** | 求值内核抽取：`loom_anim.evaluate_one/evaluate_instances`；`engine` 与 `scene_driver` 删除各自实现，统一调用 | 新 `loom_anim.py`；`loom_frame_components.py:80-101` 改为委托；`scene_driver.py:1251-1272` 删除 | ① `tests/test_animation.py` 13 条全绿；② 同一 clip + 同一 dt 序列（100 帧）在 GL/SceneDriver 两侧位姿**逐位相等** | `tests/test_anim_shared.py`：双宿主对拍；`tests/test_anim_clip_regression.py`：把现有 13 条断言扩到 50 组随机帧（含缺通道、乱序时间、t 恰好等于边界） |
| **S2** | 批量求值（SoA）：`evaluate_instances` 走 numpy 平面 | `loom_anim.py`；`loom_frame_components.py` 调用点 | ① ~~500 动画物体 ≤ 1.0 ms/逻辑帧（现 12.7ms）~~ **实测 1.42-1.69ms（≈8-9x），目标未达成** —— 剩余是两个不可向量化的逐物体 Python 循环（扫描 ~0.35ms + 写回 ~0.45ms）+ GC ~0.24ms；真到 ≤1ms 需 animator 状态 SoA + 活跃集缓存（批次2 重构，会动 play/stop 与 undo 链路，风险不在本批）→ 落地口径：稳定门禁 2.0ms + 相对旧实现 ≥5x；② 与 `evaluate_one` 对拍 1000 组随机输入逐位相等（容差 0）✅ | `tests/test_anim_perf.py`（打印实测值 + 阈值断言）；`tests/test_anim_soa_equivalence.py` |
| **S3** | 时间基准 + 播放控制：`speed / pause / seek / loopMode(once|loop|pingpong) / 跨周期计数` | `AnimationClip`（加字段）、`AnimatorComponent`（加字段/方法）、两处求值调用 | ① 修掉 §1.3 两缺陷：`once` 在 `t>=duration` 停在**末帧**；大 dt 跨末帧也停末帧；② F9 暂停 → 动画冻结；F10 步进 → 只前进 1 个 fixed_dt；③ 逃生门路径与分离路径 1 秒后位姿差 < 1e-9（同一逻辑帧数） | `tests/test_anim_timebase.py`：once 末帧、dt 跨多周期、pause/step、两条路径对拍 |
| **S4** | 序列化 v2 + undo 值隔离：`sceneio` 写/读新字段；`undo` 快照对 clips 做**值拷贝**（或改存 clip id 引用表） | `sceneio.py:298-303 / 448-455`、`scene_driver.py:86-93`、`undo.py:121-123 / 214-226`、`SCENE_VERSION 10→11`、`migrate()` | ① 往返无损（含 events/loopMode/speed）；② 旧 v10 文件加载后行为**逐位同旧**（快照对比）；③ 改 undo 快照不再污染模型（§1.5 D2 转 PASS）；④ 未知新字段在**旧引擎**里不是静默丢弃（见 ⑦Q6） | `tests/test_anim_serialize_v2.py`（v10→v11 迁移、未知字段拒绝/警告）、`tests/test_anim_undo_isolation.py` |
| **S5** | 写者优先级契约：动画只写"kinematic 目标"；动态刚体 + animator 给一次性告警并**跳过**动画写；两条物理路径顺序对齐 | `loom_frame_components.py`、`engine.py:1214-1247`（顺序/门控）、`physics_bridge.py`（只读语义确认） | ① pipe 与串行两条路径**同一输入同一结果**（对拍）；② 动态刚体+animator 有且仅有一条告警；③ 现有物理测试（`test_physics_runtime.py`、`test_physics_bridge.py`）全绿 | `tests/test_anim_physics_order.py`（假 pipe 驱动 `_logic_frame`，断言段次序 = 契约）；`tests/test_anim_write_priority.py` |

**批次 1 出口判据**：`test_animation.py` + 5 个新测试全绿；500 物体动画**实测 1.42–1.69ms，≤1.0ms 未达成**（落地 2.0ms 稳定门禁，见 §S2/loom_components 诚实口径）；`scene_driver` 无动画复刻；`SCENE_VERSION=11` 且 v10 文件可读。

### 批次 2 · 蒙皮（数据模型 + 编辑器可视化，**渲染不做**）

| 步 | 内容 | 验收标准 | 测试点 |
|---|---|---|---|
| S6 | `SkeletonAsset` / `SkinAsset` 数据模型 + 校验（权重归一化、骨索引越界、重复骨名、循环父子） | 非法输入**全部**被拒并报错（不静默）；合法输入往返无损 | `tests/test_skin_data.py`（5 类非法 + 3 类畸形输入，对齐 `功能补全5档:420-421` 的测试分类） |
| S7 | 编辑器可视化：骨骼树 + 骨骼 gizmo（`draw_lines`）+ 权重来源统计 | 选中骨骼高亮、gizmo 在位、统计面板数值与数据一致 | `tests/test_skin_editor_view.py`（headless：构造骨架 → 调视图构建函数 → 断言行数/坐标） |
| S8 | CPU 端点形变预览（只画线框/少量顶点） | 与手算矩阵一致（<1e-9） | `tests/test_skin_cpu_preview.py` |

### 批次 3 · 蒙皮渲染（**独立立项，beta7**）

| 步 | 内容 | 验收标准 | 测试点 |
|---|---|---|---|
| S9 | 顶点属性扩展（48→80B）+ 桶键加 skin 维度 + 实例 `bone_base` | 非蒙皮场景**零行为变化**（现存全部渲染测试逐像素/逐值不变） | `tests/test_render_vertex_layout.py`（字节布局断言） |
| S10 | 骨骼调色板上传（UBO 或纹理）+ 主 pass 蒙皮 | GL/VK 逐像素 A/B 一致（沿用现有 A/B 基线方法） | `tests/_tmp/ab_anim_gl_vk.py`（转正为 `ab_gl_vk.py` 同族） |
| S11 | 阴影 pass 蒙皮 | 影子与主 pass 形变一致 | 同上（深度图对比） |
| S12 | 打包运行时验证 | 编译版与编辑器同场景同帧同像素 | `tests/test_player_anim.py` |

### 批次 4 · 状态机（beta6 可选，建议随批次 1 之后）

| 步 | 内容 | 验收标准 | 测试点 |
|---|---|---|---|
| S13 | `controller` 资产 + `AnimStateMachine` | 状态迁移表驱动，无用户代码；非法 controller（未知状态/自环/不可达）加载即报错 | `tests/test_anim_statemachine.py`（含 50 状态压力、循环过渡、trigger 重复消费） |
| S14 | 脚本 API + EAI 命令 + 检查器 | `set_param/set_trigger` 从脚本与 EAI 都可达；`play()` 兼容 | `tests/test_anim_params_api.py`、扩 `tests/test_eai_real.py` |
| S15 | 过渡（duration=0 瞬切 / >0 线性混合） | 混合只影响 pose 输出，不影响事件/时间 | `tests/test_anim_transition_blend.py` |

### 批次 5 · 事件 + 时间轴预览

| 步 | 内容 | 验收标准 | 测试点 |
|---|---|---|---|
| S16 | clip events + 跨周期命中 + 排队派发 | 事件在指定 clipTime 命中；暂停时不命中；跳帧跨多周期命中 N 次；被打断的 clip 不再命中 | `tests/test_anim_events.py`（覆盖 once/loop/pingpong、跨 3 周期、seek 跳过） |
| S17 | 脚本钩子 `on_anim_event` + EventBus 桥 | 钩子异常不影响其他回调（沿用 `EventBus` 现有隔离语义 `loom_events.py:19-25`） | 同上 |
| S18 | 只读时间轴预览（scrub + 事件标记） | 拖动播放头即时看到位姿；不写盘、不进 undo | `tests/test_anim_timeline_preview.py` |

---

## ④ 风险与回滚

| # | 风险 | 证据/触发条件 | 缓解 | 回滚 |
|---|---|---|---|---|
| R1 | **场景文件前向不兼容**：`migrate()` 无条件把 `version` 改成当前版本，旧引擎读新文件不会拒绝，保存后未知字段永久丢失 | `sceneio.py:1471-1532`（`data['version'] = SCENE_VERSION` 在结尾无条件执行） | 加 `min_engine_version` 字段 + 读侧比对（不足则拒绝加载并提示）；写侧提供"导出 v10"开关 | 关开关即写回 v10；R1 修复本身可独立回滚（只加字段） |
| R2 | **undo 别名**：关键帧编辑"撤销"实为共享字典，越撤越乱 | 实测 D1/D2（§1.5） | S4 做值隔离（深拷贝或 id 引用表）；**在 S4 合并前禁止开放任何关键帧编辑 UI** | 保留旧三元组格式（`undo.py` 已有"旧 2/4/5 元快照兼容"先例），可回退到只读动画 |
| R3 | **双实现漂移**：`scene_driver` 复刻 engine 行为，改一处忘另一处 | `loom_frame_components.py:80-101` vs `scene_driver.py:1251-1272` | S1 合并为单一内核 + 双宿主对拍测试（防回归） | 合并是纯重构，回滚=恢复两份实现（不影响数据） |
| R4 | **性能回退**：批量求值改错导致逐帧分配暴涨 | 现 12.741ms@500 vs 目标 ≤1ms | 性能测试进门禁（打印 + 阈值断言）；保留逐物体路径做对拍 | 环境变量 `LOOM_ANIM_LEGACY=1` 走旧逐物体路径（参照 `_pipe_disabled` 现有逃生门风格） |
| R5 | **物理/动画顺序改动**影响现有物理用例/手感 | 现行两条路径胜负相反（§1.9） | S5 只做"契约化 + 告警 + 对齐"，不改物理积分；用 500 场景 bench 对照 | 保留旧顺序开关（默认新、可切旧），一轮 beta 后删 |
| R6 | **moderngl 静默失败**：`bind_to_storage_buffer` 在 3.3 上不报错 | 实测 §2.4 警示 | 能力探测用 `ctx.info` 判据 + 启动自检；禁止 try/except 式探测 | 无（属防御性代码） |
| R7 | **`sample()` 红线被改**：有人为了修末帧直接改 `sample` 语义 | `loom_components.py:326-335` 注释 = 红线 | 设计上把 loop 归一化放求值层；review checklist 明确"`sample` 只允许加参数默认值，不允许改取模" | 直接 revert 该函数（无数据影响） |
| R8 | **状态机与脚本双权威**：脚本直接 `play()` 与状态机抢 | §2.5 分工表 | `forced` 标志 + 检查器显示"当前由状态机/脚本驱动" | 关 `controller` = 回到旧行为（纯单 clip） |
| R9 | **打包运行时不同步**（编辑器改了，Nuitka 编译版没改） | `player_runtime` 是编译产物；`scene_driver` 是共享层 | S1 把内核放 `loom_anim.py` 并被 `build_entry`/`game_player` 显式 import；构建清单加断言 | 重打包（无代码回滚需求） |
| R10 | **权重未归一化 / 骨索引越界**（未来蒙皮输入） | `功能补全5档:420` 已列为非法测试 | S6 加载期校验 + 告警 + 归一化，**不静默** | 数据层校验可独立关闭（只警告） |

---

## ⑤ 工作量估计（人天 / 会话数）

> 口径：1 会话 ≈ 1 次完整 agent 交付（含实现 + 自测 + 报告），按本仓现有节奏（单会话可完成 150-400 行改动 + 1-2 个测试文件）。人天按"熟悉本仓的人类工程师"估算。

| 批次 | 步 | 人天 | 会话 |
|---|---|---|---|
| 1 底座 | S1 内核抽取/去复刻 | 1.5-2 | 1 |
| 1 底座 | S2 批量求值 SoA | 2-2.5 | 1-2 |
| 1 底座 | S3 时间基准 + 播放控制 | 2-2.5 | 1-2 |
| 1 底座 | S4 序列化 v2 + undo 隔离 | 2-2.5 | 1-2 |
| 1 底座 | S5 写者优先级契约 | 2 | 1 |
| **批次 1 合计** | | **9.5-11.5** | **5-8** |
| 2 数据+可视化 | S6 数据模型/校验 | 1.5-2 | 1 |
| 2 | S7 骨骼树/gizmo/统计 | 2.5-3 | 1-2 |
| 2 | S8 CPU 端点预览 | 1.5-2 | 1 |
| **批次 2 合计** | | **5.5-7** | **3-4** |
| 3 蒙皮渲染（beta7） | S9 顶点/桶键/实例属性 | 3-4 | 2 |
| 3 | S10 调色板 + 主 pass（双后端） | 5-6 | 3-4 |
| 3 | S11 阴影 pass | 2-3 | 1-2 |
| 3 | S12 打包运行时 + A/B | 2-3 | 1-2 |
| **批次 3 合计** | | **12-16** | **7-10** |
| 4 状态机 | S13-S15 | 6-8 | 3-4 |
| 5 事件+时间轴 | S16-S18（只读预览） | 5-7 | 3-4 |
| 5 | （完整关键帧编辑器，若要做） | +8-12 | +4-6 |
| **beta6 建议范围（批次 1 + 2 + 4 + 5 只读预览）** | | **26-34** | **14-20** |
| **若含蒙皮渲染** | | **38-50** | **21-30** |

**建议切分**：beta6 = 批次 1（9.5-11.5 人天）为主；批次 2 与 4 视 beta6 剩余窗口；**批次 3 直接进 beta7 立项**（与版本计划 P2/Q5 判断一致）。

---

## ⑥ 与现有代码的兼容边界

**必须保持不变（改了就破回归）**

| 契约 | 位置 | 原因 |
|---|---|---|
| `AnimationClip.sample(t)` 的取模/末帧/外推语义（含 `span<=0 → f=0`、首段负 f 外推、NaN 保持末帧） | `loom_components.py:403-457` | `tests/test_animation.py:74-80` 直接断言；`tests/_tmp/anim_np_check.py` 做逐位对拍 |
| numpy 快路径与慢路径**逐位一致** | `loom_components.py:326-335` | 红线注释 |
| `AnimatorComponent(clips, current, loop)` + `play()/stop()` 签名 | `loom_components.py:460-486` + `loom_game_object.py:408-423` | `editor.py`、`agent_commands.py`、`undo.py`、`sceneio.py`、测试都在用 |
| `sceneio` 的 `"animator": {current, loop, clips:{name: [frames]}}` **读**兼容 | `sceneio.py:448-455` | 旧场景文件必须能开 |
| `undo` 三元组 `(clips, current, loop)` **读**兼容 | `undo.py:214-226` | 旧快照/旧 redo 栈 |
| `m.rotation` 是**弧度**、Euler XYZ（`Rx@Ry@Rz`） | `matlib.py:47-71`、`loom_transform.py:53-60` | 全仓（相机/物理/脚本/序列化）都按这个约定；改成四元数是全局改造 |
| 动画写变换必须发生在 `_logic_prep` **之前**（否则丢插值） | `engine.py:1224/1243` vs `1258-1265` | 渲染帧插值依赖 SoA 平面 |
| EAI `animator` 命令名与 `action=add/remove/loop/play/clip` | `agent_commands.py:1966-1996` | 98 条命令全覆盖测试（`test_eai_real.py`）与 MCP 透传文档（`loom_mcp.py:92`） |
| `SCENE_VERSION` 单调递增 + 旧文件可读 | `sceneio.py:57, 1471-1532` | 用户场景库 |

**允许变（新契约，需登记）**

- `SCENE_VERSION: 10 → 11`：新增 `animator.version/speed/events/loopMode/params/controller`、`skeleton/skin` 字段（全部**可缺省**，缺省 = 旧行为）。
- `undo` 快照格式：新增可选第 4 元（版本号）或改成 dict；旧元组仍可 apply。
- 新增模块 `loom_anim.py`（engine + scene_driver 共用）；`scene_driver._update_animations` **删除**（对外行为不变）。
- 新增 `player_runtime` 构建清单条目（否则打包版无动画内核）。

**明确不做（防止设计误读）**

- 不把 `m.rotation` 改四元数（v1 只允许"数据里可存 quaternion 通道"，求值时转回欧拉——见 ⑦Q2）。
- 不改"动画在逻辑帧内求值"的架构（不搬到渲染帧）。
- 不在 beta6 引入 SSBO（GL 3.3 不支持）。
- 不让状态机执行任意 Python（避免与脚本重复、避免在物理待同步区跑用户代码）。

---

## ⑦ 需要人类裁决的封闭问题

> 每条给"选项 + 主审倾向 + 影响面"，便于直接拍板。

**Q1｜beta6 是否做 GPU 蒙皮渲染？**
A 不做（只数据模型 + 编辑器可视化）／B 做最小蒙皮（单骨骼链、无权重混合）／C 做完整（4 权重 + 影子 pass + 双后端 A/B）
**倾向 A**。依据 §0.5、§2.4：GL 3.3 无 SSBO（编译实证）、顶点槽余量 4、无骨骼资产来源、5 处 draw/2 个 VAO 要改两遍、12-16 人天。若选 B，必须先回答 Q7。

**Q2｜旋转是否引入四元数？**
A 不引入，保持 Euler 弧度（v1 只允许数据侧存 quaternion，求值时转 Euler）／B 内部改用四元数 + slerp，Euler 仅作 I/O／C 全链路四元数
**倾向 A**（beta6 内）。B 会牵动 `matlib/loom_transform/physics_bridge/interp_state/序列化` 全链，且现有测试多处按 Euler 弧度断言（`tests/test_eai_real.py:255`、`tests/test_scripts_collision.py:175`、`tests/test_collision_edges.py:83`）；但**跨 ±180 的长弧问题是真缺陷**，建议 v1 在 `loopMode` 层加"Euler 最短路径（按通道 wrap 到 ±π）"作为**可选开关**，默认关（保逐位一致），并单列验收。

**Q3｜`time` / `playing` 是否写入场景文件？**
A 不写（保存=回到起点，现状）／B 写（续播）／C 写但只写"预览用"字段，运行时不读
**倾向 C**（`time` 写盘仅用于编辑器预览恢复；播放器加载时强制 0）。理由：写 `playing=True` 会让"打开场景即自动播放"，与当前播放相关测试/用户预期冲突。

**Q4｜动画与物理的写者优先级怎么定？**
A 动画只驱动 kinematic/静态体；动态刚体忽略动画 + 一次性告警（**倾向**）／B 动画驱动动态刚体的目标速度（物理跟随）／C 保持现状（两条路径不一致）
A 改动最小且可解释；B 需要"动画→期望速度→物理"求解，属角色控制器范畴（beta6 之外）。

**Q5｜`once` 动画播完的默认行为？**
A 停在末帧（**倾向**）／B 自动回 default state（Unity 默认）／C 保持 `playing=True` 但冻结
A 最不隐式；B 需要 controller 才成立，无 controller 时应为 A。

**Q6｜场景版本策略？**
A `SCENE_VERSION=11` + 新增 `min_engine_version`，旧引擎**拒绝**加载（**倾向**）／B 只加版本号（现状：旧引擎静默丢字段）／C 双写 v10/v11
A 一次到位，代价是旧引擎打不开新场景（可接受：本仓是"开发期代号=正在开发的版本"）；C 复杂度高。

**Q7｜骨骼资产来源？**
A beta6 只支持"引擎内程序化骨架"（用于验证数据模型）／B 接 glTF 2.0 导入（骨骼 + skin + clip）／C 接 Assimp（FBX/glTF 都覆盖，需 DLL）
**倾向 B**（若要做蒙皮），但**必须单独立项**：B 需要资产 guid 管线（beta6 P2 候选）先落地；C 与"DLL 化总纲"方向一致但工作量最大（`docs/design/功能补全5档:409` 已标"需先做 D8 接口调研"）。

**Q8｜是否合并 `scene_driver` 的动画复刻？**
A 合并（**倾向**，S1）／B 保持两份 + 加对拍测试
合并是纯重构且有对拍测试兜底；保持两份会让"骨骼/状态机/事件"三批都要写两遍。

**Q9｜时间轴编辑器范围？**
A 只读预览（scrub + 事件标记，**倾向**）／B 只读 + 加/删关键帧（需先修 undo 别名）／C 完整曲线编辑器
A 可独立交付且不碰 undo 风险；B 依赖 S4 完成；C 至少 +8-12 人天。

**Q10｜本报告是否登记进 `docs/design/_README.md` 索引？**
`docs/design/_README.md:36` 规定"新增设计文档必须在本索引登记"，但本次任务硬约束是"报告是唯一允许写的文件"。**默认不登记**，请人类/父代理在合并时补登记（一行表格）。

---

## 附录 A：证据复现命令与探针清单

### A.1 静态统计（无需运行）

```powershell
cd "D:\my-project - 副本\Loom(py源代码-工作区)"

# animator 出现次数（排除 tests）
$files = Get-ChildItem Loom -Recurse -Filter *.py | Where-Object { $_.FullName -notmatch '\\tests\\' }
$rows = foreach ($f in $files) {
  $c = (Select-String -Path $f.FullName -Pattern 'animator' -CaseSensitive:$false -AllMatches |
        ForEach-Object { $_.Matches.Count } | Measure-Object -Sum).Sum
  if ($c) { [pscustomobject]@{ File = $f.Name; Count = $c } } }
$rows | Sort-Object Count -Descending | Format-Table -AutoSize
($rows | Measure-Object Count -Sum).Sum        # => 80

# 骨骼/蒙皮命中（engine 源码，排除 tests）
Get-ChildItem Loom -Recurse -Filter *.py | Where-Object { $_.FullName -notmatch '\\tests\\' } |
  Select-String -Pattern 'skeleton|skinned|bone|joint|inverseBind' -CaseSensitive:$false | Measure-Object
# => Count 0

# timeline / sequencer / easing / quaternion（排除 tests）
foreach ($p in 'timeline|sequencer', 'easing|bezier|catmull|hermite|slerp|quaternion') {
  (Get-ChildItem Loom -Recurse -Filter *.py | Where-Object { $_.FullName -notmatch '\\tests\\' } |
   Select-String -Pattern $p | Measure-Object).Count }

# 3D 导入格式
Get-ChildItem Loom -Recurse -Filter *.py | Select-String -Pattern 'gltf|glb|fbx' | Measure-Object
```

### A.2 探针脚本（均在 `Loom/tests/_tmp/`，被 `Loom/.gitignore:20` 忽略）

| 探针 | 命令（在 `Loom/` 下） | 输出要点 |
|---|---|---|
| `research_03_probe_semantics.py` | `python tests/_tmp/research_03_probe_semantics.py` | A1-A4 线性插值；B1-B2 欧拉长弧；C1-C5 播放态不落盘；D1-D2 undo 别名；E1-E2 属性面 |
| `research_03_probe_dt.py` | `python tests/_tmp/research_03_probe_dt.py` | A2/A3 一次性动画末帧丢失；B1 `t==duration` 倒回第 0 帧；C1 跨周期不规范化 |
| `research_03_probe_order.py` | `python tests/_tmp/research_03_probe_order.py` | pipe/串行两条路径的段次序（动画 vs 物理回读 胜负相反） |
| `research_03_probe_perf.py` | `python tests/_tmp/research_03_probe_perf.py` | 2.512 / 12.741 / 27.123 ms（100/500/1000 物体） |
| `research_03_probe_perf2.py` | `python tests/_tmp/research_03_probe_perf2.py` | 逐物体 9.109ms vs SoA 0.133ms（68.5x） |
| `research_03_probe_glcaps2.py` | `python tests/_tmp/research_03_probe_glcaps2.py` | GL 3.3 上下文 + #version 330 蒙皮 VS 编译 OK + UBO 对齐 256 |
| `research_03_probe_glcaps3.py` | `python tests/_tmp/research_03_probe_glcaps3.py` | texelFetch 骨骼采样编译 OK；`MAX_VERTEX_TEXTURE_IMAGE_UNITS=32` |
| `research_03_probe_glcaps4.py` | `python tests/_tmp/research_03_probe_glcaps4.py` | 12 属性 VAO OK；`'4B'/'4b'` 顶点格式被拒 |
| `research_03_probe_ssbo.py` | `python tests/_tmp/research_03_probe_ssbo.py` | **GL 3.3 下 SSBO 语法编译失败**（GLSL 拒绝 `std430 buffer`）→ 蒙皮不能走 SSBO |
| `research_03_probe_vkcaps.py` | `python tests/_tmp/research_03_probe_vkcaps.py` | wgpu 0.32 / backend=Vulkan / vertex 阶段 storage buffer 可用 |
| `research_03_probe_vkcaps3.py` | `python tests/_tmp/research_03_probe_vkcaps3.py` | 设备 limits 全表（stride 2048 / uniform 64KB / offset 对齐 256） |

### A.3 既有回归（本案相关的既有测试）

```powershell
cd Loom
python tests/test_animation.py          # 13 条：插值/推进/循环/单次/序列化/undo —— 本次实测 ALL PASS
python tests/test_physics_runtime.py    # 动画/音频运行态快照清零
python tests/test_eai_real.py           # animator EAI 命令
python tests/test_scene_driver_lod.py   # SceneDriver 侧
```

> 说明：`test_animation.py` 本次运行输出 `总结果: ALL PASS ✅`（13/13），可作"改动前基线"。

---

## 附录 B：本报告的"未实测"清单（避免误读）

- 本报告**没有**实测 wgpu 侧 `textureLoad` 在 vertex 阶段的可用性（§2.4 路径 B 的 VK 半边，标为 ⚠️）。选路径 B 前必须补一个 headless wgpu 探针。
- 本报告**没有**实测"动态刚体 + animator 在真实物理 DLL 下被覆盖"的端到端现象（只有代码路径 + 段次序实测 + 回读代码引用）。S5 的第一个测试就是这个端到端用例。
- 本报告**没有**实测编辑器点"播放"按钮无效果（只有 `advance_logic` 早退的代码依据）；如需人肉确认，用 GUI 手测一次即可。
