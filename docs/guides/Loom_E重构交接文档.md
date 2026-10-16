# Loom 项目 E 重构交接文档

> 生成：2026-10-13 · 供下一轮无上下文 Agent 接手
> 版本标记：texture-complete-2026-10-15 (HEAD 0c25852 · engine.py 1141 行 · 13 Mixin · 性能 4 提交 + 贴图 13 提交 + 实测修 2 bug + 文档 5 提交)
> 项目根：D:/my-project · 引擎目录：Loom(py源代码-工作区)/Loom

---

## ⚠️ 新 Agent 请先读这里（入口指引）

**接手必读两份文档**（配合使用）：

1. **本文件**（`docs/guides/Loom_E重构交接文档.md`）—— 最权威的白盒：
   方法论（第三节）、子系统现状、陷阱清单、性能优化记录（第九节）、贴图体系（第十节）、
   未实施高风险候选（第十一节）、踩坑（第十二节）。
2. **《AI协作实践指南_VibeCoding工程思维落地.md》**（同目录）—— 在本项目里**怎么做**：
   六层纪律（白盒/黑盒/灰盒/验证/运行时/决策）、每轮工作闭环、红线清单、成熟度自评。

**快速上手**：`git log --oneline -25` 看本轮全部提交（每个都可 `git checkout <hash>` 回滚）；
探针在 `Loom(py源代码-工作区)/Loom/tests/_tmp/`（`probe_*`/`prof_*`/`verify_*` = 证据库）；
压力场景在 `保存/压力测试/`。

---

## ⚠️ AOCI 索引状态：未重建（下一个 Agent 必读）

**当前 AOCI 索引严重滞后于代码，且未重建。** 事实（2026-10-15 实测 `aoci_overview(check_only)`）：

- `state: invalid`，`semantic_change_count: 402`（阈值 30，**超 13 倍**）
- `actionable_missing: 402`，`unbaselined: 187`，`governance_blocker_count: 611`
- 搜 `loom_texture` / `loom_cubemap` / `texture` → **全部 0 条**（本轮新增内容完全未索引）

**结论：目前项目代码剧烈变化（本轮 20+ 提交：性能优化 + 完整贴图体系 + 2 bug 修复），
暂时并不适合立刻开始重建 AOCI。** 强行重建可能触发大量治理阻塞（AOCI 自评 next_action =
"先把当前最小工作单元稳定下来……不要维护索引"）。

**下一个 Agent 注意**：**当代码进入相对稳定态时（例如：一批功能完成并回归全绿、且短期内
不再有大规模改动），必须主动提醒人类"现在可以开始重建 AOCI 索引了"，由人类决定是否启动
重建。** 重建需走 AOCI 完整认知链（`aoci_overview` → `aoci_maintain` → `aoci_update_entry`
→ 严格 attestation），属路线级决策，**不得自行启动**。

---

## 〇、这份文档要解决什么

Loom 3D 游戏引擎的 **engine.py 单体类 GLEngine** 高达 6000+ 行，需要持续重构为高内聚低耦合的子系统（Mixin）。截至本轮已抽出 13 个 Mixin（engine.py 降到 1141 行），本文件记录**方法论 + 现状 + 陷阱 + 后续可选方向**，让接手的 Agent 能不看历史对话直接继续。

**核心目标**：engine.py 进一步瘦身，每个子系统可由不同人独立维护，接口隔离、内部封装。

---

## 一、项目背景（快速认知）

- **Loom** = Python/PySide6 宿主 + C ABI 动态库 + 嵌入式 Lua 5.4 的 3D 游戏引擎
- **对标 Unity**：功能概念对齐，但实现自研（Python + ModernGL + Jolt）
- **对齐策略（三层，务必遵守）**：
  - **魂（概念/流程）**：完全借 —— Unity 术语/组件模型/工作流
  - **骨（可验证数值）**：选择性借 —— 同一操作序列+初始条件 → 用户可感知结果（数值/位姿/行为方向）一致
  - **肉（实现）**：完全自研 —— 渲染管线/语言/序列化格式，不模仿 Unity 内部
- **判定标准**：能写自动化对拍测试的数值行为 → 必须对齐；内部实现 → 不对齐

---

## 二、当前状态

### engine.py 规模
- **1141 行**（本轮渲染管线解耦后；上一轮 3327 行，更早 6049 行）
- **1 个类 GLEngine** + 少量顶层函数/常量（GC 生命周期工具、_gc_enabled 等）

### 已抽出的 Mixin（13 个）
| Mixin | 文件 | 内容 | 轮次 |
|-------|------|------|------|
| ShadowMixin | loom_shadow.py | M29 阴影贴图子系统 | 上一轮 |
| FrameComponentMixin | loom_frame_components.py | update_audio/update_animations/_call_collision_cb | 上一轮 |
| PhysicsMixin | loom_physics.py | M28 碰撞 + M31 刚体物理 | 上一轮 |
| InputMixin | loom_input.py | 按键/动作层/鼠标锁定/键位配置 | 上一轮 |
| HudMixin | loom_hud.py | HUD/文字渲染 | 上一轮 |
| CameraMixin | loom_camera.py | 轨道相机 + 相机实体管理 | 上一轮 |
| RenderMixin | loom_render.py | 渲染管线本体（帧准备/绘制/render/run） | 本轮 |
| ModelGpuMixin | loom_model_gpu.py | GPU 几何构建/材质库/模型挂载删除/场景加载 | 本轮 |
| LightingMixin | loom_lighting.py | 光源上传/阴影 VP/AABB 并行/阴影碰撞并行 | 本轮 |
| WindowMixin | loom_window.py | 窗口尺寸/全屏/事件循环/输入钩子 | 本轮 |
| TransformMixin | loom_transform.py | 世界矩阵/父链层次/包围盒（跨段合并） | 本轮 |
| ProfilerMixin | loom_profiler.py | LOOM_PROFILE 阶段耗时插桩 | 本轮 |
| LogicThreadMixin | loom_logic_thread.py | 异步逻辑线程启停/主循环 | 本轮 |

### 当前 MRO（新 Mixin 一律追加在末尾；方法名不冲突）
```
class GLEngine(ShadowMixin, FrameComponentMixin, PhysicsMixin, InputMixin, HudMixin,
               CameraMixin, RenderMixin, ModelGpuMixin, LightingMixin, WindowMixin,
               TransformMixin, ProfilerMixin, LogicThreadMixin):
```

### 已拆出的基础模块（非 Mixin，供 import）
loom_shaders / loom_types / loom_color / loom_input(常量) / loom_material / loom_components / loom_game_object / loom_scene_entities / core_clock / interp_state / matlib / fastpath / mesh / sceneio / undo / physics_bridge / script_glue

---

## 三、E 重构方法论（核心！照此执行）

### 抽取一个 Mixin 的标准流程

**Step 1 — 选目标**：找连续的方法群（同一功能域），优先低耦合（只通过 self 访问宿主状态，不 import engine）。

**Step 2 — 建 Mixin 文件**：标准模板（文件头 docstring 说明抽出方法列表 + 依赖的 self.xxx 列表）。

**Step 3 — 从 engine.py 精确删除方法群**：
- 不要用大段 edit（易失败）。用**临时 Python 脚本**按方法名边界删除
- find 匹配用 startswith（方法行含参数，不能用 ==）
- 从后往前删（避免行号偏移）
- 删除后**立即语法自检**（ast.parse）

**Step 4 — engine.py 加导入 + 继承**：from loom_xxx import XxxMixin；class GLEngine(..., XxxMixin)

**Step 5 — 处理跨模块引用**：
- 若方法引用 GLEngine.xxx（类名硬编码）→ 改为 type(self).xxx 或 Mixin 类名
- 若引用 engine.py 的全局常量/函数 → 从原模块 import

**Step 6 — 验证（必做）**：语法 ast.parse → import 冒烟 + MRO → 核心测试（脚本式）。

**Step 7 — 提交**：git commit -m "refactor: extract XxxMixin from GLEngine (功能域)"

### 关键注意事项

1. **测试是脚本式**（sys.exit(0) 判成败），**不是 pytest**！用 py -3.12 tests/xxx.py 直接跑，看 exit=0。用 pytest 会 INTERNALERROR。
2. **中文路径**：PowerShell 里路径正常；但 py 脚本内路径用原始字符串 r"..."。
3. **临时脚本**：写到 _align_tests/tools/_tmp_xxx.py，用完删除（别提交）。
4. **不要改逻辑**：抽取是纯搬家，逐行照抄，语义逐位不变。
5. **一次一个 Mixin**：抽完验证通过再抽下一个。
6. **运行时文件别提交**：editor_state.json / tests/_tmp/*.json / LoomHub/projects.json 会被测试改动，提交前 git checkout -- 还原。

---

## 四、子系统清单与后续可选方向

### 已完成（本轮，逐位纯搬家 + 脚本测试全绿）
- RenderMixin / ModelGpuMixin / LightingMixin / WindowMixin / TransformMixin / ProfilerMixin / LogicThreadMixin
- **渲染管线相关子系统已全部解耦**（原始目标达成）

### 不建议动
- __init__（引擎初始化，跨所有子系统，拆分风险极高）
- _bump_struct（被全网调用）

### 后续可选方向（高难度，非必要；闲时可尝试）

> 以下方向**不紧急**。当前 engine.py 剩余的多为协调逻辑（帧调度、脚本分发、逃生门分支），
> 按“抽到只剩协调逻辑就该停”的原则，做到这一步已足够干净。
> 若将来其他方面都优化到头、想进一步拆分，可考虑下面这个**高风险**方向。

**逻辑帧分离域（游戏的“心跳”）**
- 位置：engine.py 中的逻辑帧 / 渲染帧分离系统，约 300+ 行（另含脚本系统 ~170 行）。
- 内容：`_logic_frame`（一个逻辑步 = 全场景最高同步点：脚本 → 物理子步 → 音频/动画 →
  prep → 事件派发 → 插值翻页）、`advance_logic`、`_logic_prep`、`_ensure_split`、
  `_framebuf_prefetch`、`_physics_frame`、`_pipe_post`、`toggle_logic_paused`、
  `step_logic_once`、`get_tps`、`_run_scripts`，以及脚本系统 `update_scripts`。
- **为什么高危**：它是整条帧链的收口，几乎所有子系统都连着它；且含多条行为红线，
  任何改动都可能波及全局。
- **行为红线（若动，必须逐位保留，禁止借重构删/改）**：
  1. `advance_logic` 的“逃生门”分支（`_ensure_split() is None`，即 NO_SPLIT /
     logic_fps<=0 时的旧绑死四行）—— 缺它会导致 NO_SPLIT 编辑器播放态逻辑全丢；
  2. `_logic_frame` 的“物理管线 vs 串行子步”双分支（LOOM_NO_PIPE 逃生门）；
  3. 异步门控：逻辑线程**仅限 Qt 宿主编辑器**（`_logic_async` 且 `_external_ctx`），
     无头探针/测试直驱时不得起线程（否则双驱逻辑帧 + 物理管线 → 同步超时 / IndexError）；
  4. 暂停 / 步进（F9 / F10）语义。
- **建议做法（若做）**：先把它与脚本系统分开评估，且**分多次独立提交**，每次沿用
  第三节的“纯搬家 + 逐行比对 + 脚本测试”流程；出任何问题立即回滚。

---

## 五、验证与门禁

### 测试执行（脚本式）
cd "D:/my-project/Loom(py源代码-工作区)/Loom"
foreach ($t in @("test_engine_safety.py","test_camera.py","test_sceneio.py","test_undo.py","test_scripts.py","test_lighting.py","test_physics.py","test_hierarchy.py","test_animation.py")) { py -3.12 "tests/$t" *> $null; "$t exit=$LASTEXITCODE" }

### 门禁（Graphenium / AOCI，可选）
- MCP graphenium：graph_stats / blast_radius（评估改动影响面）
- MCP aoci：aoci_search（查符号定义）

### 对齐测试（仅当改行为时）
- _align_tests/ 下有对拍工具（Loom↔Unity）；纯重构不应触发对拍（语义不变）

---

## 六、陷阱清单

1. 测试用 pytest 会崩 → 用 py tests/xxx.py 直接跑
2. 大段 edit 易失败 → 删方法群用临时 Python 脚本（find_prefix + 从后往前删）
3. 方法行含参数 → find 匹配用 startswith 不用 ==
4. MRO 顺序：新 Mixin 加在继承列表末尾即可（方法名不冲突）
5. 类名硬编码：GLEngine._xxx() 抽到 Mixin 后要改 type(self)._xxx()
6. 循环 import：Mixin 不能 import engine；需要时函数内延迟 import
7. 运行时文件：提交前 git checkout -- 还原被测试改动的 json
8. 一次一个：抽完一个验证通过再下一个
9. 不改逻辑：纯搬家，逐行照抄

---

## 七、快速上手命令

cd "D:/my-project/Loom(py源代码-工作区)/Loom"
Select-String -Path "engine.py" -Pattern "^    def " | ForEach-Object { $_.LineNumber.ToString().PadLeft(5) + ": " + $_.Line.Trim() }
Select-String -Path "engine.py" -Pattern "^class GLEngine"
py -3.12 -c "import ast; ast.parse(open('engine.py',encoding='utf-8').read()); import engine; print([c.__name__ for c in engine.GLEngine.__mro__][:8])"

---

## 八、已完成的里程碑

### 本轮：渲染管线解耦（原始目标达成）
- engine.py **3327 → 1141 行**（-2176，-65%），抽出 7 个 Mixin：
  RenderMixin / ModelGpuMixin / LightingMixin / WindowMixin / TransformMixin / ProfilerMixin / LogicThreadMixin
- 每个 Mixin 均通过：语法 + import 冒烟 + MRO + **纯搬家逐行比对 mismatches=0** + 脚本测试
- 关键工程发现：Transform 块被逻辑线程方法打断为两段，采用“跨段合并”抽取；
  渲染端到端覆盖在 test_integration.py（起真实 GL 窗口），其余 grep 到的 render 多为误报
- 提交链：2764137 → c58843a → b2b11f4 → f522cd0 → 7421289 → 898b743 → 68b35ec
- **回滚点**：任一提交可 `git checkout <hash>` 回到当时状态

### 上一轮
- 对齐：物理（6/7，含 Jolt 阻尼修复）/ 光照（点光 range）/ 相机（FOV 60）/ 材质 / 脚本（rotate 3/3）
- 重构：engine.py 6049 → 3327 行（-45%），抽出 6 个 Mixin
- 修复的真实 bug：Jolt 线性阻尼、scene_new 挂死、light kind 误判、基元尺寸不统一
- 对齐工具链：_align_tests/（Loom↔Unity 对拍，含 align_loom.py / AlignRunner.cs / compare.py）
- 文档：docs/guides/Loom_引擎操作手册与全功能测试清单.md、Loom_vs_Unity_功能对照表.md、Loom新功能Unity对齐测试流程.md

## 九、本轮性能优化成果（2026-10-14，全部已提交）

> 目标：在不破坏数值行为的前提下压榨性能。原则：**低风险优先**（有现成 C 接口/缓存可加即做），
> 高风险（改物理写回段、静态层、架构级）一律记录待后续一次性做。
> 每个优化都带逃生门（\`LOOM_NO_*\`）+ 逐位对拍 + 回归测试全绿才提交。

### 9.1 脚本模块缓存 BUG（提交 \`4999d14\`）—— 本批最大收益
- **根因**：\`ModuleHandle\` 缺 \`is_live\` 属性 → \`getattr(h,'is_live',False)\` 恒 False
  → 每次 \`handle()\` 重新组装模块栈（6ms）。每帧调 2 次（engine.py 判 use_c + script_glue batch_rotate 内）。
- **修复**：给 \`ModuleHandle\` 加 \`is_live\` property（\`return self._dll is not None\`），9 行。
- **效果**：逻辑帧 **19.5ms → 8.47ms（-57%）**；脚本段 11.65ms → 0.75ms。
- 附带：\`physics_glue.py\` 同款 bug 自动受益。

### 9.2 编辑态阴影 VP 静止缓存（提交 \`1c3cd5b\`）
- **根因**：编辑态物体静止时，阴影 VP 每帧全算（占编辑态 render 51%）。
- **修复**：\`_compute_light_vps\` 加“静止缓存”（世界矩阵对象身份 + 结构/外观代 + 光源参数指纹），
  仅编辑态启用，\`LOOM_NO_SHADOW_CACHE=1\` 逃生门。
- **效果**：\`shadow_prep\` 1.17 → 0.43ms；编辑态 render **2.28 → 1.54ms（-32%）**。

### 9.3 物理摩擦段下沉 C 内核（提交 \`fa03a18\`）
- **调研结论（重要）**：物理线程三段 —— \`pre_step\`(8.1ms Python) / \`step\`(0.35ms C/Jolt) /
  \`post_step\`(8.4ms Python) → **Jolt 真物理仅占 2%，98% 是 Python 胶水**。
- **发现**：\`core_components/physics/loom_physics.c\` **已有批量 C 接口**
  （\`loom_physics_pre_step/post_step/substep_loop\`），\`physics_glue.py\` 已接好，
  但 \`physics_bridge.py\` 只 import 没用（实际走 culverin Python 绑定）——**现成但未接线的低垂果实**。
- **修复**：\`post_step\` 的摩擦+残速整段下沉 C（\`loom_physics_pre_step\`，gravity_y=0 → 纯摩擦+残速），
  Jolt 写回仅对**变化行**做，\`LOOM_NO_BATCH_PHYS=1\` 逃生门。
- **效果**：\`post_step\` **13.9 → 10.1ms（-27%）**，位姿 0 差异（逐位一致），回归 9/9 全绿。

### 9.4 视锥剔除（提交 \`ad79870\`）
- **收益量化**：真实压力场景 **68-79% 物体在视锥外**（小镇 79% / 2000球 68% / 1200刚体 75%）。
- **架构障碍**：主 pass 与阴影**共享 \`_render_buckets\`**，不能简单剔除
  （视野外物体可能投影到视野内）。方案：**主 pass 用可见子集，阴影保持全量**。
- **实现要点**：
  - 新增 \`_frustum_planes\`（Gribb-Hartmann 6 平面提取）、\`_spheres_in_frustum\`、\`_frustum_keep\`（球测试，保守不误剔）
  - 分组时算每桶半径（\`_bucket_radius\`，网格顶点最大距）
  - 打包循环：可见实例重排到缓冲前部，\`_main_bucket_n\` 记每桶主 pass 数；
    主缓冲写 \`st[:n_main]\`，阴影缓冲仍写 \`g[:k]\`（全量）
  - \`_draw_main_buckets\` 用 \`_main_bucket_n\`
  - **关键**：桶脏闸签名加入**相机**（\`_cam_sig\`），否则相机移动时可见子集不更新
  - \`LOOM_NO_FRUSTUM=1\` 逃生门
- **效果**：主 pass 1801 → 375（剔 79%）；集合一致性验证（引擎 375 = 独立复算 375）；回归 8/8 全绿。

### 9.5 本轮提交链与回滚点
\`\`\`
4999d14 fix(script): ModuleHandle.is_live 缓存判据 (逻辑帧 -57%)
1c3cd5b perf(lighting): cache static shadow VPs in edit mode (-32% edit render)
fa03a18 perf(phys): batch friction/stall via loom_physics C kernel (-27% post_step)
ad79870 perf(render): frustum culling for main pass (~79% objects culled; shadow stays full)
\`\`\`
任一提交可 \`git checkout <hash>\` 回滚。物理优化前的探针提交为 \`9f97ea8\`。

### 9.6 压力测试场景（已提交 \`保存/压力测试/\`，生成器 tests/_tmp/gen_stress_scenes.py）
| 场景 | 物体数 | 逻辑帧(修复后) |
|------|--------|--------------|
| 压力_空场景 | 1 | 0.36ms |
| 压力_渲染_实例化2000球 | 2001 | 19.4ms |
| 压力_渲染_多材质1000方块 | 1001 | 9.6ms |
| 压力_物理_动态1200刚体 | 1201 | 44.6ms |
| 压力_物理_混合600静600动 | 1201 | 29.1ms |
| 压力_脚本_自转1000 | 1001 | 22.1ms |
| 压力_动画_400关键帧 | 401 | 4.6ms |
| 压力_综合_小镇 | 1801 | 37.4ms |

**核心结论**：逻辑帧瓶颈 **80-92% 是物理 \`pipe_wait\`**（等 Jolt）。

---

## 十、贴图/纹理体系（2026-10-14 已完成，7 提交）

> 从"完全没有贴图"到"完整贴图体系"：albedo + 法线贴图 + mipmap + 网格 LOD。
> 全部沿用"逐位对拍 + 脚本测试 + 逃生门"流程。回归测试 tests/test_texture.py（29 项）。

### 10.1 已完成的能力
| 能力 | 实现 | 说明 |
|------|------|------|
| Texture 资产 | loom_texture.py | from_file/from_rgba/white；guid 稳定；延迟 GPU 创建（ensure_gl）|
| mesh UV | mesh.py | cube 改 24 顶点（每面独立 UV，对齐 Unity）；sphere/plane 加 UV |
| 材质贴图槽 | loom_material.py | Material.albedo / Material.normal_map（走 setter bump 失效）|
| UV 顶点格式 | loom_model_gpu.py | 顶点格式 3f 3f 4f 2f（加 UV 2f），展平 (3F,12) |
| 桶键含贴图 | _mesh_key | 键 = (primitive, params, normal_mode, albedo_guid, nrm_guid) |
| 着色器采样 | loom_shaders.py | albedo 采样（无贴图绑白纹理=乘白不变）；法线贴图导数法 TBN |
| 每桶绑定 | _draw_main_buckets | 单元0=albedo，单元1=normal_map；u_has_normal_map 控制整段跳过 |
| mipmap | Texture.ensure_gl | build_mipmaps() → filter 自动 LINEAR_MIPMAP_LINEAR，远处自动模糊 |
| 法线贴图 | 导数法 TBN | dFdx/dFdy 解切线，无需预计算切线，不改顶点格式 |
| 网格 LOD | lod_levels + _update_lod | 按相机距离切换网格；无 lod_levels 零开销 |
| 加载命令 | agent_commands.set_texture | 从文件加载并绑定；空 path=清除；失败容错 |
| MCP 工具 | unity_texture_set | Agent 可通过 MCP 设贴图 |
| 序列化 | sceneio._emit_material/_apply_materials | 材质资产含 albedo(guid+path)；加载时重建 |

### 10.2 关键设计决策
- cube 改 24 顶点：原 8 共享顶点无法承载逐面 UV。物理 AABB 极值不变（24 顶点是 8 角点副本）。
- 桶键含贴图 guid：材质是共享资产，物体 _bucket_key 缓存感知不到材质变化，故 guid 每帧从 model 现取。
- 无贴图零开销：绑 1x1 白纹理（采样乘白=原色），视觉不变；回归对拍证明。
- 法线用导数法 TBN：避免预计算切线（需改顶点格式 + UV 缝处理）。
- LOD 无配置零开销：lod_levels=None 时 getattr 跳过；切换走 mesh setter。
- EditorApp 覆写 render：LOD 调用需在 editor.py 的 render 里也加（基类的调用不生效）。

### 10.3 提交链（回滚点）
09bd064 Texture 资产 + mesh UV（数据层）
af85d1c albedo 渲染管线（槽+UV格式+着色器+绑定）
95490c2 set_texture 命令 + MCP + 序列化
eeb7104 mipmap 距离 LOD 验证
71e642e 法线贴图（导数法 TBN）
cf40387 网格 LOD（相机距离）

### 10.4 用法示例
命令: set_texture {"name": "地板", "path": "assets/floor.png"}
MCP:  unity_texture_set {"name_or_id": "地板", "path": "assets/floor.png"}
代码:
from loom_texture import Texture
mat.albedo = Texture.from_file("assets/floor.png")
mat.normal_map = Texture.from_file("assets/floor_normal.png")
obj.renderer.lod_levels = [(10.0, hi_mesh), (40.0, lo_mesh)]

### 10.5 后续可扩展（未做）
- 网格 LOD 的自动网格简化（当前需手工提供多精度网格）
- 距离剔除 Layer Cull Distances / CullingGroup
- 贴图资产独立文件（当前随材质序列化）
- 远处禁用法线贴图（LOD 级别绑定开关）
- 贴图导入编辑器 UI（当前只有命令/MCP 接口）

### 10.6 本轮追加 6 项（2026-10-14 第二批，对标 Unity 完整度补全）

> 按"与 Unity 贴图体系差距"优先级补全：导入设置 → 压缩 → PBR → 屏幕LOD → Cubemap → MCP。

| 提交 | 内容 | 对标 Unity |
|------|------|-----------|
| `76f1bf4` | **纹理导入设置**：wrap(repeat/clamp) / filter(point/bilinear/trilinear) / aniso / max_size | Texture Import Settings |
| `193b453` | **纹理压缩**：RGB565/RGBA4444/RGB5A1 降位深（-50% 显存）；moderngl 无硬件 DXT API，故用降位深 | Compression（注：非 DXT/BC 块压缩） |
| `1820bee` | **PBR 光照**：Cook-Torrance GGX + Smith + Schlick，材质 metallic/roughness/pbr，**向后兼容**（默认 Blinn-Phong 逐位不变） | Standard Shader |
| `cc6f5ea` | **屏幕占比 LOD**：`lod_screen_levels`（ratio=半径/(距离·tan(fov/2))）+ `lod_bias`；保留距离模式 | LODGroup.screenRelativeTransitionHeight + lodBias |
| `508c1a4` | **Cubemap 环境反射**：`loom_cubemap.py` 资产 + 材质 env_map 槽 + 着色器环境反射（漫反射按法线/镜面按反射向量选 mip） | Reflection Probe（静态部分） |
| `7163454` | **MCP 补全**：`unity_lod_set` 工具 + `set_lod` 命令（sphere 自动生成低模） | LODGroup |

**新增 MCP 工具**（AI 可用）：`unity_texture_set`（含导入设置/压缩参数）、`unity_pbr_set`、`unity_env_set`、`unity_lod_set`。

**对应命令**：`set_texture` / `set_pbr` / `set_env` / `set_lod`。

**测试**：`tests/test_texture.py`（29+项）、`tests/test_lod.py`、`tests/test_cubemap.py`（独立文件，干净 GL context）。

**Unity 对照**（2026-10-14）：`E:\UnityAlign\AlignProject` + `Assets/Editor/TextureRunner.cs`（三球：albedo贴图/金属PBR/粗糙PBR）。
对照结论：**贴图体系功能对齐**（albedo 棋盘/金属高光/金属-粗糙区分均正确）；差异仅来自光照参数配置（强度/环境光/光源方向），非体系缺陷。

**关键设计（向后兼容）**：
- PBR 默认关（`u_pbr_mode` 全局 + `u_material_pbr` 材质双门控）；未启用时走原 Blinn-Phong 逐位不变
- 无贴图/无 LOD/无 env 零开销（白纹理乘白 / getattr 跳过）
- 桶键维度：`(primitive, params, normal_mode, albedo_guid, nrm_guid, pbr_tuple, env_guid)` 共 7 维
- `LOOM_NO_PBR=1` 可全局关 PBR（对比测试用）

**踩坑**：Cubemap 无 mipmap 却设 MIPMAP filter → GL 采样返回黑（经典陷阱）；修法=仅 mip 链完整时用 MIPMAP filter。

### 10.7 小游戏实测（2026-10-14，发现并修复 2 个真实 bug）

> 用户要求"做小游戏观察是否还有 BUG"。建《收集彩球》小游戏（地面+玩家 WASD/相机跟随+
> 3 彩球触碰计数+弹跳，含贴图/PBR/LOD/Cubemap 新功能），无头跑播放循环 + 存读场景。

**发现并修复的 2 个真实 bug**（提交 `469463d`）：
1. **`count_touch` 脚本移除物体后崩溃**：命中后 `remove_model(self.obj)` 未 return，
   同帧继续 `e.models.index(self.obj)` → `ValueError: ... is not in list`（引擎容错捕获，
   但脚本应自防护）。修法：命中移除后立即 `return`。
2. **`scene_to_dict` 丢失未注册材质**：只序列化 `engine.materials`（资产库），
   模型直接赋的 `Material()`（脚本/程序化常见）不在库中 → PBR/贴图/环境全丢，重载变默认材质。
   修法：序列化时收集所有模型实际引用的材质（去重）。

**回归测试**：`tests/test_gameplay_bugs.py`（固化为防复发）。

**小游戏实测脚本**：`tests/_tmp/mini_game_collect.py`（基础版）、`tests/_tmp/mini_game_full.py`（全面版）。

**Unity 对照结果**（`E:\UnityAlign\AlignProject\Assets\Editor\TextureRunner.cs`）：
三球（albedo棋盘/金属PBR/粗糙PBR）对照 —— **贴图体系功能对齐**（棋盘显示/金属高光/
金属-粗糙区分均正确）；差异仅来自光照参数配置，非体系缺陷。

**全量回归**：24 个测试文件全绿（texture/lod/cubemap/gameplay_bugs/physics/collision/
lighting/shadow/sceneio/assets/scripts/animation/integration/editor_ui/engine_safety 等）。

---

## 十一、未实施的高风险大改候选（记录待后续）

> 以下都**不是**低风险顺手可做，需要专门立项 + 充分验证。等所有低风险优化做完后，可**一次性**做
> （可减少重合文件的修改）。

1. **物理写回段**（\`post_step\` 剩 9.8ms，最大头）——C 改不动
   （\`Point3D\` 是给用户脚本的 Python 对象，C 造不出），可行优化只有“延迟构造 Point3D”
   （要改 \`GameObject\` 热路径，风险高）或批量化属性赋值。**收益不确定、风险大。**
2. **物理 \`pipe_wait\`**（占逻辑帧 80-92%）——Jolt 自身/子步策略/胶水精简。
3. **静态层分离**（用户提“地图物体不占运动资源”）——**已量化后暂缓**：
   - 纯静止 \`compute_world_matrices\` 0.003ms（已有整批缓存，几乎零成本）
   - 一个物体动 → 整批重算 3.9ms；分离后静态部分省 ~1.8ms（**仅占逻辑帧 5%**）
   - Loom 物体多为单节点根树，“按树分离”退化；批量矩阵改成逐物体判断可能更慢；中高风险
   - 结论：**接受暂缓**，等更高收益方向做完再评估
4. **物理脏检测静态场景白烧**（\`_dirty_mask_batch\` 缓存命中仍 4.4ms：建 2001 元组列表 2ms + numpy 比较 2.4ms）
   —— 需“无动态体早退”，涉及物理状态机（静态→KINEMATIC 升级），中风险。

---

## 十二、本轮踩过的坑（补充到第六节之外）

1. 提交信息里 \`-57%\` 写成 \`-57%%\`（模板字符串转义）→ 用 \`git commit --amend\` 修正（发生多次）
2. 探针里 \`mat4_view_yaw_pitch\` 返回带 batch 维 \`(1,4,4)\`，需 \`reshape(4,4)\`
3. standalone moderngl 上下文里 \`fb.read()\` 只返回 1 行（读缓冲/stride 问题），像素对比困难
   → 改用“引擎剔除集合 vs 独立复算集合”一致性验证（更本质）
4. 视锥剔除初次“剔 0%”，根因是桶脏闸早退（签名不含相机）→ 签名加 \`_cam_sig\` 后生效

*本文件持续更新，供跨 Agent 接手。方法论（第三节）是核心，照做即可。*


