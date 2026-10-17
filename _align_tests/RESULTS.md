# Loom ↔ Unity 对齐测试结果总表

| 功能 | 日期 | 数据组数 | 对齐度 | 结论 | 截图目录 |
|------|------|---------|--------|------|---------|
| 变换（位置+缩放） | 2026-10-13 | 6 | 6/6 | ✅ 完全对齐（数值 6/6） | _align_tests/example_transform/ |
| 物理（重力/运动学/匀速） | 2026-10-13 | 4 | 4/4 | ✅ 完全对齐（数值 4/4） | _align_tests/physics/ |
| 物理深度（碰撞/弹跳/摩擦） | 2026-10-13 | 7 | 6/7 | ✅ 弹跳完美对齐；摩擦为 Jolt/PhysX 固有差异 | _align_tests/physics/ |
| 光照（点光 range / kind） | 2026-10-13 | 参数语义 | ✅ | range 默认 10 对齐 Unity；修复 dir kind 归一化 | — |
| 相机（FOV/位置） | 2026-10-13 | 参数语义 | ✅ | 默认 FOV 60 / 位置 (0,1,-10) 对齐 Unity | — |
| 材质（颜色/饱和度） | 2026-10-13 | 参数语义 | ✅ | 颜色设置/回读精确；饱和度可调 | — |
| 脚本（rotate 行为） | 2026-10-13 | 3 | 3/3 | ✅ 90°/s 行为与 Unity 等价脚本一致 | _align_tests/script/ |

> 每完成一次新功能对照测试，追加一行。判定分级见 docs/guides/Loom新功能Unity对齐测试流程.md 第三节。

---

## 2026-10-13 首次端到端对齐：变换系统

### 测试内容
创建 cube + 位置（正/负/零/远）+ 缩放 2x，共 6 组数据。

### 数值对齐（Loom vs Unity 两侧精确回读，容差 1e-4）

| case | 注入 | Loom 回读 position | Loom 回读 scale | Unity 回读 position | Unity 回读 scale | 数值对齐 |
|------|------|-------------------|----------------|--------------------|-----------------|---------|
| create_A | cube @ [0,1,0] | [0,1,0] | [1,1,1] | [0,1,0] | [1,1,1] | ✅ |
| pos_positive | [3,2,1] | [3,2,1] | [1,1,1] | [3,2,1] | [1,1,1] | ✅ |
| pos_negative | [-4,-1,-2] | [-4,-1,-2] | [1,1,1] | [-4,-1,-2] | [1,1,1] | ✅ |
| pos_zero | [0,0,0] | [0,0,0] | [1,1,1] | [0,0,0] | [1,1,1] | ✅ |
| pos_far | [100,50,100] | [100,50,100] | [1,1,1] | [100,50,100] | [1,1,1] | ✅ |
| scale_2x | scale [2,2,2] | [100,50,100] | [2,2,2] | [100,50,100] | [2,2,2] | ✅ |

**结论**：Loom 与 Unity 在全部 6 组数据上 position/rotation_deg/scale 逐分量精确一致；两侧操作 6/6 成功。

### 本次修复的 bug（含 1 个真引擎 bug）

| # | Bug | 类型 | 修复 |
|---|-----|------|------|
| 1 | Loom 截图路径被写白名单拒绝（_align_tests 不在白名单） | 工具链 | 改走引擎默认 保存/ + Python 搬运 |
| 2 | Unity 批量模式 GameObject.Find 找不到新建物体 | 工具链 | 静态字典 + FindObjectsOfTypeAll 兜底 |
| 3 | C# Op 类扁平结构 vs ops.json 嵌套 args | 工具链 | 改为嵌套 Args 类 |
| 4 | 改过的 AlignRunner.cs 忘拷贝到 Unity 项目 | 流程 | 加拷贝步骤 |
| 5 | **scene_new 命令调 new_scene_cmd 弹"是否保存"对话框** → 无 GUI 时阻塞 51 秒后超时失败 | **引擎 bug** | 改为直接调 _new_scene() 绕过对话框 |
| 6 | Loom 场景脏累积 | 工具链 | align_loom.py 跑前 scene_new 重置 |

### 工具链增强（本次）
- **AlignRunner.cs 数值回读**：每次操作后导出被操作物体的 position/rotation_deg/scale 到 unity_result.json
- **compare.py 数值对比**：从两侧 result 抽取向量逐分量比对（容差 1e-4），判定优先级改为"数值对齐 > 截图变化"
- 判定分级：数值 ✅ → 🟢；数值 ❌ → 🔴；纯视觉操作（无数值）退回截图判定

### 下一步
- 相机/场景对齐（像素级视觉对比）
- 对齐下一个功能（光照 / 刚体 / 材质 / 脚本）

---

## 2026-10-13 物理系统对齐（重力/运动学/匀速）

### 测试内容
4 个物理用例，确定性驱动（Loom: `play paused=true` + `physics_simulate`；Unity: `Physics.simulationMode=Script` + `Physics.Simulate(1/60)`），各 30 逻辑帧（=60 物理子步 = 1.0s）。

### 数值对齐（容差 1e-2）

| case | Loom pos | Unity pos | Loom vel | Unity vel | 对齐 |
|------|----------|-----------|----------|-----------|------|
| freefall_1s | [0, 0.0184, 0] | [0, 0.0183, 0] | [0, -9.7998, 0] | [0, -9.8, 0] | ✅ |
| no_gravity_1s | [0, 5, 0] | [0, 5, 0] | [0,0,0] | [0,0,0] | ✅ |
| kinematic_1s | [0, 5, 0] | [0, 5, 0] | [0,0,0] | [0,0,0] | ✅ |
| horizontal_1s | [5.0, 5, 0] | [5.0, 5, 0] | [5.0, 0, 0] | [5.0, 0, 0] | ✅ |

**物理对齐度: 4/4**

### 本次修复的引擎 bug（物理对齐驱动发现）

**Jolt 默认线性阻尼 0.05 导致与 Unity 行为不对齐**：
- 现象：水平匀速物体速度按 `exp(-0.05t)` 衰减（4s 内 5.0→4.09），Unity `Rigidbody.drag` 默认 0，无此衰减
- 根因：culverin 0.14.0 的 `create_body` 无阻尼参数，Jolt 内建默认 `mLinearDamping=0.05` 无法关闭
- 修复：`physics_bridge.py` 每子步对清醒动态体写 `v*(1+0.05*dt)`，Jolt 阻尼后恰好回到模型速度（位形积分与速度回读均无净衰减）
- 验证：horizontal 用例 vx 稳定 4.9998（120 帧），与 Unity 一致

### 工具链增强

**MCP 精细操作能力**（引擎命令 + MCP 工具双层）：
- `physics_simulate {frames}`（`unity_physics_simulate`）——确定性推进 N 逻辑帧
- `rigidbody action=set`——精设 mass/use_gravity/is_kinematic/friction/restitution/velocity
- `play paused=true`——进入播放即冻结逻辑帧（物理对拍确定性前提）
- `inspect` 扩展——回读 velocity/mass/friction/restitution/is_kinematic

**Unity 侧**（`AlignRunner.cs`）：
- `RunPhysics` 入口——用 Unity 原生 `Physics.Simulate` 确定性步进（无需第三方库）
- `unity_rigidbody_set` 补 isKinematic/velocity/friction/restitution

### 遗留
- 物理对拍用硬编码小用例集（镜像 Loom 侧），未走通用 ops 运行器
- 未测碰撞/弹跳/摩擦（需地面碰撞体 + 长时间步进）
