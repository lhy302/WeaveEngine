# 编号 02：批次 B（资产）与批次 C（动画）—— 目标达成度独立判定（第十轮倒查）

> 判定者：未参与实现的独立子代理（第十轮）。**只读仓库，未修改任何受跟踪文件**。
> 仓库根：D:/my-project - 副本/Loom(py源代码-工作区)；本轮实测落点：
> - HEAD = 5b0a91d（docs-only 提交，父提交 d1674fa 为派单时 HEAD）
> - 工作树**非完全干净**：M tools/verify_pkg_vs_head.py（非本子代理所改），另有兄弟子代理报告 docs/audit/goal_01_*、docs/audit/goal_03/ 未跟踪
> - 探针：Loom/tests/_tmp/goal_02_a_assets.py、goal_02_a_setup.py、goal_02_b_anim.py、goal_02_b2_adversarial.py、goal_02_c_pack.py、goal_02_d_delta.py（均在 Loom/.gitignore 的 tests/_tmp/* 内）
> - 方法：目标**逐条抄自原始设计文档**（research_beta6_02_asset_guid.md、research_beta6_03_animation.md、版本计划 §7/§9.15/§9.23），不采用任何实现报告/自评口径；每条判定给"命令 + 实际输出 + file:line"。
> - 纪律：先证伪（努力证明"没达成"），再证真；任一侧成功才下结论，两侧都失败记 UNKNOWN。全程未用 AI 打分，结论全部来自可重跑探针输出。

---

## 0. 判定汇总

| 编号 | 目标（原文出处） | 判定 | 一句话证据 |
|---|---|---|---|
| **B-1** | 资产索引单点：项目级 Assets/assets.json 为唯一真相源（R02 §2.2 方案 B / 计划 D3、Q-B1-3=A） | **达成** | 加载/保存均只经 loom_assets.AssetContext；场景不再持有材质定义 |
| **B-2** | 材质内联定义**真的被忽略**（计划 §9.15:381；交接 §6 Q-B1-3=A） | **达成** | 内联写 name/color/metallic/pbr/albedo=green，加载后全取库值且 albedo 像素确为库图 |
| **B-3** | guid 保存后不丢、索引可解析（R02 §2.7 Q-B1-1） | **达成** | 存盘后 materials[] 只剩 {id,name}；删正文后保存仍保留 albedo guid |
| **B-4** | 场景引用只写 guid，无 path/paths（R02 §2.4） | **达成** | 递归扫整份场景 JSON：path/paths 命中 0 |
| **B-5** | 失败必须出声，不静默（R02 §2.1-3） | **达成** | 缺正文 -> _asset_errors 点名文件；内联冲突 -> 点名"已按资产库加载" |
| **B-6** | **打包真的带资产**（R02 §③ S5:274：打包->移盘->启动->贴图仍在） | **达成**（1 处计数漏洞见 P3-1） | 真实 build_game.py 出包："Assets/ 已随包 (8 个文件)"；移盘后像素级复验通过 |
| **B-7** | 索引 10k 冷加载 <=500ms（计划 §9.23 P2-1，门禁 test_asset_guid.py:1082-1101） | **达成** | 自造 10000 条 3.44MB：冷加载 **72.3-75.3ms**、inspect 71.6-74.7ms |
| **B-8** | 用户层 delta 的 import 覆盖真的生效（§9.23 P2-2） | **达成** | write_user_delta(wrap=clamp) -> Texture.wrap=='clamp'，user index 真实落盘 |
| **B-9** | save_index('') 不得落 CWD（§9.23 P2-3） | **达成** | 返回 (None,'没有项目根…')，仓库根未出现 Assets/ |
| **C-1** | 动画**去复刻**：唯一内核（R03 §③ S1:510） | **达成** | 两宿主入口 co_names 只含 evaluate_animations；全仓仅 loom_components.py 调 .sample( / 按 dt*speed 推进 |
| **C-2** | SoA 批量求值（S2:511，目标 <=1.0ms/500 物体） | **部分达成** | 入口级实测 **1.699ms**（批=500 x 30 帧全命中）；<=1.0ms 未达成，R6 已裁决诚实化为 2.0ms 门禁 |
| **C-3** | once 末帧 / 大 dt 跨末帧 / 循环时间规范化 / pingpong（S3:512） | **达成** | once 到点停在末帧且 time==duration；dt=5.0 仍停末帧；loop 3.6s 后 time∈[0,dur) |
| **C-4** | speed / pause / seek / loopMode(once\|loop\|pingpong)（S3:512） | **达成** | set_speed/seek/effective_loop_mode 存在且探针验证；speed=0 冻结、nan 降级 1.0 并告警 |
| **C-5** | 序列化 v2 + **undo 值隔离**（S4:513） | **达成**（1 个畸形输入反例见 P3-2） | 快照/模型双向隔离成立；关键帧新增可撤销；旧 3 元快照仍可 apply |
| **C-6** | 写者优先级 D6：动画只驱动 kinematic/静态（S5:514 + 计划 D6:130） | **达成** | 动态刚体+animator 位姿不动、blocked_dynamic=1、告警仅一次；kinematic/静态被驱动 |
| **C-7** | 两条物理路径（管线/串行）同序同结果（S5:514） | **达成** | 串行 scripts->anim->physics x2；管线 scripts->anim->pipe_post x2->pipe_wait，动画两侧均在物理前 |
| **C-8** | 蒙皮/状态机/事件/时间轴编辑器 | **不适用** | 计划 §7:150-154 与 D5:129：beta6 只做动画批次1，批次3/4/5 不进本版 |

**结论：批次 B = 达成（含 1 处 P3 计数漏洞）；批次 C = 达成，其中"SoA <=1.0ms"子项 = 部分达成（已人类裁决诚实化，不阻塞）。**

---

## 1. 复现命令

```powershell
cd Loom; $env:PYTHONIOENCODING='utf-8'
py -3.13 tests/_tmp/goal_02_a_assets.py        # 资产单一真相源 / 打包结构 / 索引 10k
py -3.13 tests/_tmp/goal_02_b_anim.py          # 去复刻 / SoA 入口 / 时间语义 / undo / 写者优先级 / 段次序
py -3.13 tests/_tmp/goal_02_b2_adversarial.py  # 反例矩阵（试图打破隔离与优先级）
py -3.13 tests/_tmp/goal_02_d_delta.py         # 用户层 delta + save_index('') 守卫
# 真实打包（不改受跟踪文件，全部落 %TEMP%）
py -3.13 tests/_tmp/goal_02_a_setup.py
py -3.13 build_game.py --name G02 --scene "%TEMP%/goal02_pack/proj/scene.json" (续行) --runtime player_runtime/game_player.dist --output "%TEMP%/goal02_pack/dist" (续行) --protection open --no-encrypt-content --force
py -3.13 tests/_tmp/goal_02_c_pack.py          # 把发布夹整体移盘后按包内 base 解析
```

---

## 2. 资产（批次 B）逐条证据

### B-1/B-2 单一真相源：材质内联"真的被忽略"

**判定基准（原文）**：版本计划 §9.15:381 "材料 albedo/normal/env 与 skybox/相机 skybox 托管时只写 guid"；交接 §6 "Q-B1-3 材质真相源 **A 只认 assets.json**（v12，内联降级为引用）"。

**代码证据**
- Loom/sceneio.py:1457-1505 _apply_materials：仅当 ctx is not None and guid and ctx.owns(guid,'material') 时**一律用库定义**（:1480-1490），内联只用于"是否一致"的比较与告警（:1483-1489）。
- Loom/sceneio.py:1422-1454 _emit_material_refs：写盘只发 {'id','name'}。
- Loom/loom_assets.py:91-95 material_has_inline / :73-88 material_canon（规范化比较）。

**探针反例（证真）**：库里材质 = 库材质/metallic .4/roughness .2/pbr True/albedo=red.png；场景内联写 场景副本/metallic 0/roughness .9/pbr False/albedo={guid:green.png, path:Assets/Textures/green.png}。

```
PASS ② 内联定义被忽略: 加载材质名来自资产库  name='库材质'
PASS ② 内联定义被忽略: metallic/roughness/pbr 来自库  (0.4, 0.2, True)
PASS ② 内联 albedo 指向 green 但按库取值: guid=red  albedo.guid='ab69da8a…c4fc'
PASS ② 实际解码像素来自 red(220,20,20) 而非 green(20,220,20)  (220, 20, 20, 255)
PASS ② 冲突必须出声(含"场景副本与资产不一致")  [('materials[]', 'ca31804b…', '场景副本与资产不一致，已按资产库加载')]
```
-> 内联不仅"被忽略"，连它指向的另一张贴图也没有被解码（像素级证伪）。

**迁移期 fallback（非违例，按设计）**：库中**没有**该材质时回退内联 + 出声：
```
PASS ⑩ 库缺该材质 -> 迁移期回退内联定义(不丢数据)  ('未登记', 0.9)
PASS ⑩ 回退必须出声(尚未登记资产库)  [('materials[]', 'ea15bc16…', '该材质尚未登记资产库（保存时会自动迁移）')]
```

### B-3/B-4 guid 不丢、场景无 path

```
PASS ④ 保存后 materials[] 只剩 id/name  {'id': 'ca31804bba…', 'name': '库材质'}
PASS ④ 保存后 guid 不变  ca31804bba93414dabb5d259ae794faf
PASS ④ 保存后 skybox 只有 guid  {'name': 'sky', 'guid': '3726eec0…'}
PASS ④ 整份场景无 path/paths 残留
PASS ④ 库 value 记录 albedo/env guid  {'albedo': 'ab69da8a…', 'env_map': '3726eec0…'}
PASS ⑤ 贴图缺失后保存: 库 value 仍保留 albedo guid(不丢引用)
PASS ⑤ 场景仍无 path 残留(不退回绝对路径)
```
代码侧对应"失败也保留引用"：Loom/sceneio.py:1289-1300（_keep_slot_ref 语义）、:1540-1549（失效引用不得当默认材质丢弃）、Loom/loom_assets.py:1116-1125（库层同样保留）。

### B-5 失败出声

```
PASS ⑤ 贴图缺失: albedo 未解析
PASS ⑤ 贴图缺失: 资产错误点名  [('materials[]', 'ca31804b…', '资产文件缺失: Assets/Textures/red.png')]
PASS ③ 改名后无资产错误
```

### B-6 打包**真的**带资产（真实 CLI 打包 + 移盘复验）

build_game.py 真实出包（非直接调 helper）：
```
[2/5] 游戏脚本: 11 个 -> 加密打包 [...]
[4/5] 玩家运行时: …/Loom/player_runtime/game_player.dist
  资产: Assets/ 已随包 (8 个文件, 1 条托管引用)
[5/5] 构建完成: %TEMP%/goal02_pack/dist
```
包内结构（Get-ChildItem -Recurse dist/Assets）：assets.json、Textures/wood.png、Cubemaps/sky/{px,nx,py,ny,pz,nz}.png；游戏包.lsc = 25326 B，其 config.assets == True。

把整个发布夹搬到**另一个目录名**后按包内 base 解析（等价 runtime.PlayerApp(assets_base=pack_dir)，Loom/runtime.py:141-148）：
```
[pack] 发布夹已移盘: %TEMP%/goal02_pack_moved/ReleaseG02
PASS ② 移盘后按发布夹解析: 贴图恢复  ['木材质']
PASS ② 移盘后按发布夹解析: env 六面图恢复
PASS ② 移盘后按发布夹解析: 天空盒 valid
PASS ② 贴图像素来自项目 Assets (200,60,20)  (200, 60, 20, 255)
PASS ③ 反例: 不给 assets_base(按 CWD) -> 贴图确实丢失(说明 base 是必需项)  [('木材质', None)]
```
负例守卫（§9.15 要求的"不许死 guid 出包"）：build_game.py:88-112 require_assets_or_exit -> 死 guid 无库时 SystemExit。
编译版运行时亦含新代码（二进制符号）：{assets_base:True, 'Assets/assets.json':True, evaluate_animations:True, loom_components:True}（game_player.dist/MyGame.exe，33.7MB；dist build_info.git_head=d1674fa）。

> **未做**：真正启动 MyGame.exe 看画面（release 档无控制台、无头环境无法目视）。这是本项唯一未覆盖的最后一厘米；结构/解析层证据已闭环。

### B-7 索引 10k 冷加载（自造数据）

自造 10000 条 texture 条目（3.44MB），清 _CACHE 后计冷加载：
```
[perf] index size=3.44MB load=72.3ms inspect=74.7ms validate=113.7ms ctx_open=0.9ms
PASS ⑨ 10k 索引冷加载 ok 且条数=10000
PASS ⑨ 10k 冷加载 <=500ms  72.3ms
PASS ⑨ 10k inspect <=500ms 且 state ok  74.7ms ok
```
（多轮重复 72.3 / 73.0 / 75.3ms。）根因修复在 Loom/loom_assets.py:384-408 _norm_src 纯字符串判定（零文件系统调用）、:314-348 单次快照缓存；is_inside（:234-247，2x realpath）只在 resolve() 真正解析时调用。

### B-8/B-9 打包外两条 P2 收口

```
delta write ok=True 项目层 wrap='repeat' filter='trilinear' ; delta 后 wrap='clamp' filter='point'
user_index_path=…/projects/dir-b90e3ab2/assets.json exists=True
save_index('') -> path=None reason="没有项目根（root=''），拒绝写资产索引"
CWD 未被污染( Assets/assets.json 在仓库根? )=False
```

---

## 3. 动画（批次 C）逐条证据

### C-1 去复刻：第二份实现已清零

```
PASS ① engine.update_animations 只调 evaluate_animations(无 sample)  ('getattr','bool','physics_disabled_by_env','evaluate_animations',…)
PASS ① scene_driver._update_animations 只调 evaluate_animations(无 sample)  ('evaluate_animations','models','_physics_available',…)
[反例8] 改写 time 的文件 / 调 .sample( 的文件: ADV ['loom_components.py'] | SAMPLE ['loom_components.py']
PASS 反例8: 只有内核按 dt*speed 推进播放头
PASS 反例8: 只有内核调 AnimationClip.sample( 无第二份插值实现
```
代码：Loom/loom_frame_components.py:81-108（engine 侧）、Loom/scene_driver.py:1353-1365（播放器侧）均 evaluate_animations(...)；内核 Loom/loom_components.py:786-1005。
editor.py:2274（开始播放置 an.time=0.0）与 undo.py:239（撤销清运行态）是复位，不是第二份推进。

### C-2 SoA 真的接在入口上（不是只测 helper）

对内核 _sample_batch 打桩计数，跑**真实入口** SceneDriver._update_animations：
```
PASS ② SceneDriver 入口 30 帧内批量求值被调用  30
PASS ② 每批覆盖 500 个实例(入口级真实批量化)  500
[perf] 500 动画物体 入口=SceneDriver._update_animations -> 1.699 ms/逻辑帧
PASS ② 入口结果与 clip.sample(同相位) 逐值一致  ((0.0,0.25,0.5), (0.0,0.24999999999999967,0.49999999999999933))
```
判定：**接线达成**（批次数=帧数、每批 500 实例、结果与逐物体 sample() 同值）；**<=1.0ms 未达成**（1.699ms，Loom/loom_components.py:799-805 已诚实登记并给 2.0ms 门禁）。

### C-3/C-4 时间语义与播放控制

```
PASS ③ once 到点停在末帧 (position=末帧)  (0.0, 2.0, 4.0)
PASS ③ once 到点 playing=False
PASS ③ once 到点 time=duration(不取模回 0)  0.9
PASS ③ 大 dt 跨末帧仍停末帧  (0.0, 2.0, 4.0)
PASS ③ loop 大 dt 后 time 被规范化到 [0,dur)
PASS ③ pingpong 时间折返 (不越界)  [0.1,…,0.9,0.8,0.9,0.8]
PASS ③ dur=0 片段夹 0 停播(不无界负增长)  (0.0, False)
PASS 反例6(speed=0 暂停): 位姿冻结  (0.0, 0.0, 0.0)
PASS 反例6(nan speed): 降级 1.0 且一次性告警
```
API：Loom/loom_components.py:583-631（set_speed / effective_loop_mode / seek），speed 字段 :566-571。

### C-5 undo 值隔离（双向）

```
PASS ④ 快照里的 clip 不是模型同一对象
PASS ④ 改快照不污染模型 (帧数)  3
PASS ④ 改模型不污染快照 (快照首帧位姿)  (0.0, 0.0, 0.0)
PASS ④ 撤销回写后模型首帧恢复
PASS ④ 撤销后 time/playing 清零(运行态不入快照)
PASS ④ 旧 3 元快照仍可 apply (兼容)
PASS ④ 快照比较能识别"关键帧被编辑"(__eq__ 按内容)
PASS ④ 关键帧新增可撤销(帧数回到 3)
```
代码：Loom/undo.py:121-128（存快照时 clip.copy()）、:219-240（写回再拷一份）；AnimationClip.copy() 见 Loom/loom_components.py:406-428（list/tuple/ndarray 递归拷）；__eq__ 内容比较 :370-404（防"拷贝=改了"误判）。

### C-6/C-7 写者优先级 + 两条物理路径同序

```
PASS ⑤ 动态刚体+animator: 动画不写位姿  (0, 0, 0)
PASS ⑤ 动态刚体被计入 blocked  {'advanced': 2, 'blocked_dynamic': 1, 'fallback_dynamic': 0}
PASS ⑤ 警告有且仅有一次  [动画] 1 个物体同时有动态刚体与 Animator: … (D6: 只驱动 kinematic/静态体)
PASS ⑤ kinematic 被动画驱动 / 无刚体(静态)被动画驱动
PASS ⑤ 物理不可用 -> 回退动画驱动动态刚体  + 回退名单被记录(物理侧要避让)
PASS ⑤ LOOM_NO_PHYSICS=1 真开关 -> 动画驱动
[order] 串行: ['fixed','scripts','anim','physics_serial','physics_serial','audio','prep']
[order] 管线: ['fixed','scripts','anim','pipe_post','pipe_post','audio','pipe_wait','prep']
PASS ⑥ 两条路径同序: scripts -> anim -> 物理 -> prep
PASS ⑦ 回读循环按 MOTION_DYNAMIC 过滤(kinematic/静态不被回写)
```
代码：Loom/engine.py:1200-1295（两分支都先 update_animations 再物理，:1229/:1265）；回读只写动态体 Loom/physics_bridge.py:1304-1307；回退名单 Loom/loom_frame_components.py:99-112 -> Loom/loom_physics.py:498。

---

## 4. 反例矩阵（先证伪、再证真）

| # | 反例（想打破什么） | 结果 | 判定 |
|---|---|---|---|
| P-01 | 内联 albedo 指向**另一张**图，看能否把库图挤掉 | 库图胜出，绿图未被解码（像素 220,20,20） | **P-DISPROVED**（单一真相源成立） |
| P-02 | 场景内联写与库冲突的 name/pbr/metallic | 全部取库值 + 出声 | **P-DISPROVED** |
| P-03 | 删掉贴图正文后保存，看 guid 是否被抹 | 库 value 仍保留 albedo guid；场景无 path | **P-DISPROVED** |
| P-04 | 把项目目录改名/发布夹移盘后重载 | 贴图/六面图/天空盒全部仍在 | **P-DISPROVED** |
| P-05 | 只给 assets_base 之外（按 CWD）启动 | 贴图丢失 | 反向证明 base 必需（不是"碰巧能跑"） |
| P-06 | 10000 条索引冷加载能否仍慢 | 72-75ms | **P-DISPROVED**（旧 8660ms 病根已去） |
| P-07 | 在 SceneDriver 入口下让 SoA 只存在于 helper | 入口 30 帧 30 次批、每批 500 | **P-DISPROVED** |
| P-08 | 改 undo 快照污染模型 / 改模型污染快照 | 双向均隔离 | **P-DISPROVED** |
| P-09 | 动态刚体+animator 想让动画赢（换管线开关） | 两路径都被 blocked，否则显式回退 | **P-DISPROVED** |
| P-10 | 给帧通道塞 dict（畸形），看隔离是否仍成立 | **改快照会串到模型（leaked=True）** | **P-PROVED（P3-2）** |
| P-11 | 只含"材质库引用"、无 skybox 的场景能否被出包守卫拦 | scene_asset_refs=0 -> **不拦** | **P-PROVED（P3-1）** |

---

## 5. 残留与风险（不阻塞本编号判定，但需登记）

**P3-1 出包守卫的计数口径落后于 v12（build_game.py:69-85 scene_asset_refs）**
v12 之后材质贴图引用搬进 assets.json，场景 materials[] 只剩 {id,name}；守卫只数 skybox/相机 skybox/内联材质槽 -> 只有材质贴图的场景 scene_asset_refs=0，require_assets_or_exit 不拦。实测：scene_asset_refs({'materials':[{'id':…}]})=0，require_assets_or_exit(..., False) 返回 0。
影响：项目根缺失时仍会"绿着出包"，运行期才在 _asset_errors 出声（不是静默错画，但违反"构建期拦死 guid"的意图）。建议：scene_asset_refs 追加"库内被引用材质 -> 其 albedo/normal/env 计数"。

**P3-2 undo 值隔离对畸形通道值不成立（loom_components.py:415-425 的 _cv 不递归 dict）**
裂口：frames[i]['position'] 若是 dict，快照与模型共享同一对象 -> 改快照串到模型（实测 leaked）。合法通道按契约必须是 3 元序列（tuple/list/ndarray 均已覆盖），JSON 反序列化也只会给 list，因此真实场景不可达；建议 _cv 顺带支持 dict 或在校验处拒绝非序列通道。

**P3-3 文档与实现不一致（轻微）**：scene_driver.py:6-7 头部仍写 "engine.update_scripts / update_animations 的**复刻**，与 engine.py 保持同步注释，勿分叉公式"，而 C1 之后已是委托同一内核（:1353-1365）。陈旧注释会让下一个接手者误以为仍有两份实现。

**性能门禁偏松（沿用既有审计口径）**：10k 门禁 500ms 对实测 72-75ms 有 ~6.6x 余量，抓不住中等回退；R03 §③ S2 的 <=1.0ms 已按 R6 裁决改写为 2.0ms 门禁（实测 1.70ms，余量仅 15%，方向正确）。

---

## 6. 与"自评/报告口径"的差异（本轮独立发现）

1. 交接文档 5 写"C 动画 500 物体 **1.61ms**"，本轮入口级实测 **1.699ms**（同量级，落在 R6 公布的 1.42-1.69 区间上沿；不矛盾，但单点数字应带区间）。
2. 计划 §9.23 的 P2 第 2/3 项（用户层 delta、save_index('')）本轮**已复验修好**；第 1 项（10k 8.6s）复验 72-75ms。
3. §9.15 的"test_asset_guid 46 项"已增长，本轮不引用该项计数，只用自己的探针。
4. 本轮仅对**源码**路径做端到端复验；**编译版**只有二进制符号与 build_info.git_head 证据，未做"启动编译版看画面"的最后一步（无头环境限制）。

---

## 7. 结论

- **批次 B（资产）**：目标"项目级单一真相源 + guid 引用 + 打包带资产 + 索引可扩展" **达成**；两条 P2 已收口；残留 1 处 P3 计数漏洞（出包守卫口径）。
- **批次 C（动画批次1）**：**去复刻 / 时间语义 / undo 值隔离 / 写者优先级 / 两条物理路径同序** 均 **达成**；"SoA <=1.0ms" **部分达成**（1.70ms，已裁决诚实化，不阻塞）。
- 不建议因 P3-1/P3-2 阻塞 beta6；建议登记进 路线登记_后续版本.md 或就地小修（两处均 <10 行改动）。
