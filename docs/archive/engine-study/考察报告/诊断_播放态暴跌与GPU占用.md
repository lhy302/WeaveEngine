# 诊断报告: 播放态暴跌与 GPU 占用 (分离批1-4 落地后, 2026-09-05)

诊断代理现场取证 | 工作区 D:\my-project\Loom(py源代码-工作区)\Loom | 只取证未改引擎源码
场景 = tests\_tmp\stress_500spheres.json (501 物体 / 100 个 rotate 脚本 / 501 collider / 2 光源)
用户现场设置.json: **logic_fps=20 / physics_fps=30 / fps_limit=unlimited / parallel 4 预留核**

====================================================================
〇、执行摘要 (三个数字)
====================================================================
- **播放态实测 FPS (Qt 真路径 500 球): 25.2 FPS** (帧间隔 39.66ms;
  编辑态同场景 74.8FPS/13.37ms; 本机比用户机快 ~1.5×, 用户机等比放大
  → 16-18FPS, 叠加更弱 GPU/更高分辨率即个位数 — 暴跌结构已完全复现)。
- **根因1 (#3 播放态暴跌) = 物理线程同步税**: engine.py:3381-3382 post 后
  立即 wait, post→wait 间隙实测仅 **0.031ms** (批4 设计 §8.1 的
  "step C 段与音频/动画重叠"完全没兑现); 每物理步主线程纯等 11.2ms
  (物理线程内 ensure 0.80 + **pre_step 9.81** + step 0.27 + post 0.06),
  用户设置 30Hz 物理 → 每渲染帧 pipe_wait **13.9ms (35% 帧预算)**。
- **根因2 (#2 GPU 吃不满) = 每渲染帧全额重算的 CPU prep**:
  aabbs 9.4ms + shadow_prep 16.2ms (含 collide_pairs 5.0) 每渲染帧重算,
  而其中内容在"逻辑帧没跑的渲染帧"与上帧逐位相同 (D3 定案 _frame_world
  =逻辑位姿, 却没做按逻辑帧缓存); GPU 实测平均 **30.2%** (峰值 35%),
  帧率被主线程单核 prep 串行卡死, 与 GPU 无关。

附带重大发现 (修复时必读):
- ★NO_SPLIT 逃生门在编辑器路径**逻辑全丢**: engine.advance_logic
  (engine.py:4202-4221) 在 clk=None (NO_SPLIT) 且 is_playing 时零操作直接
  返回, 无批3 设计的 _logic_split_fallback 旧四行分支 → 编辑器播放态
  脚本/物理/音频/动画全部停摆 (实测 rotate 60 帧 0.00°)。bench/PlayerApp
  路径不受影响 (engine.render:4432 else 分支正常)。逃生门回退保证被破坏。
- ★editor.py:1781 `_prepare_bucket_frame()` 裸调未包 _profile → 编辑器
  播放态报表 buckets=0.00 假象, 实测每帧真花 1.01ms (重填 200/200 帧)。
- ★build_entry.py:237 与 stress_probe.py:204 的 keys 元组都没有 'pipe_wait'
  → 分离批4 的最大成本段在台账上不可见 (插桩在 engine.py:3382 有, 报表漏)。

====================================================================
一、A/B/C 三态实测 (bench + Qt 真路径 ×3)
====================================================================
【bench (build_entry --bench, PlayerApp 直调 render(1/120) ×300)】
| 态                        | FPS  | 帧ms   | logic_step | pipe_wait | aabbs | shadow_prep |
|---------------------------|------|--------|-----------|-----------|-------|-------------|
| NO_SPLIT (基线)           | 26.8 | 37.30  | 0.00      | -         | 9.34  | 16.28       |
| 分离默认 (20/30Hz+线程)   | 40.1 | 24.93  | 3.58      | (未上报)  | 9.40  | 17.08       |
| 分离+NO_PIPE              | 45.8 | 21.84  | 3.06      | -         | 8.88  | 15.26       |
(用户报 NO_SPLIT=26.3 / 分离=41.7 — 与本机复跑吻合, 数据可信。
 bench dt=1/120 恒定 → 每帧只累计 0.17 逻辑步, 逻辑成本被摊薄 → 偏乐观;
 dt 里 physics 16.15 (NO_SPLIT) 的一部分被"物理走线程"消掉 = bench 涨幅来源。)

【Qt 真路径 (LoomGUI 完整面板 + QTimer unlimited + paintGL→advance_logic
+render, 用户同款设置 20/30Hz) — tests\_tmp\qt_play_probe.py】
| 态                 | FPS  | 帧ms  | logic_step | pipe_wait | world | aabbs | shadow | interp |
|--------------------|------|-------|-----------|-----------|-------|-------|--------|--------|
| 编辑态             | 74.8 | 13.37 | 0         | 0         | 7.72  | 16.30 | 17.80  | 0.74   |
| 播放态 (默认+线程) | 25.2 | 39.66 | 15.24     | 13.88     | 1.97  | 9.43  | 16.18  | 1.24   |
| 播放态 NO_PIPE     | 20.8 | 48.11 | 22.35     | 0         | 2.10  | 10.34 | 17.33  | 1.15   |
| 播放态 NO_SPLIT    | 50.4 | 19.85 | 0         | 0         | 0.77  | 8.70  | 15.29  | 0.57   |
★播放态 NO_SPLIT "最快"是假象 — 见摘要★: 它根本不跑逻辑 (逃生门 bug)。
★播放态比 NO_SPLIT 真实多付的成本 = logic_step 15.24 (其中 pipe_wait 13.88)
+ interp +0.5 + 桶重填 1.0 ≈ 17ms/帧 — 这就是暴跌的全部来源。
★NO_PIPE 反而更慢 (48ms): 物理三段主线程内联 (pre 16.9ms 持 GIL 卡渲染),
证明线程方向正确, 错在 post→wait 之间零重叠。

【逐逻辑步/物理步成本 (tests\_tmp\micro_probe.py / micro2_probe.py)】
- 物理线程内: ensure_models 0.80ms / **pre_step 9.81ms** / step(Jolt C) 0.27ms
  / post_step 0.06ms → 11.0ms/物理步; 主线程 wait 11.04ms (纯等待)。
- 主线程 post→wait 间隙: **0.031ms/物理步** (audio 0.02 + animations 0.01)。
- 逻辑步内: scripts(线程同步) 0.58ms / audio 0.02 / anims 0.01 / interp.advance
  ~0.3ms (500 物体 _grab 纯 Python)。
- 播放态实测步数: 逻辑 0.79 步/帧, 物理 1.19 步/帧 (20Hz/30Hz × 39.66ms ✓)。
- pipe_wait/帧 13.88 ≈ 1.19 物理步 × 11.66ms ✓ 闭合。

====================================================================
二、根因1 (#3 播放态暴跌) 定位: 物理线程 post→wait 零重叠
====================================================================
【代码位置】
- engine.py:3378-3383 `_update_physics_bridge`:
      pipe = self._phys_pipe
      if pipe is not None and not pipe._degraded and not events:
          pipe.post(self.models, dt, g, events)
          self._profile('pipe_wait', lambda: pipe.wait())
          return
  post 完**同语句块内立刻 wait** — 中间没有任何主线程工作。
- 批4 设计 (分离批3_4_实施设计.md §8.1) 的重叠时序: post 后主线程跑
  update_audio + update_animations (~0.03ms) → wait。设计预期的重叠收益
  = "step C 段 (释放 GIL) 期间主线程跑音频/动画" — 但音频/动画在
  _logic_frame 里排**在 _physics_frame 之后** (core_clock.advance:
  先逻辑步后物理步, D2 定案), 且实测三者合计 0.03ms < 1ms, 重叠窗口
  形同虚设 → 物理线程 11ms 执行时间 100% 变成主线程纯等待。
- physics_pipe.py:59 `br.step(dt)` C 段仅 0.27ms (Jolt 30Hz 步进 501 静态
  球场景, 动态体睡眠红利), 真正大头是 **pre_step 9.81ms 纯 Python**
  (physics_bridge.py:826-930: 每步 501 体脏检测 dict 推导 + _model_dirty
  三对象元组比较 + world_position_vec/quat_from_mat3 逐体 numpy 小矩阵)
  — 这段持 GIL, 即使主线程有活也并不起来。

【为什么编辑态正常、播放态暴跌】
- 编辑态: advance_logic 空转 (engine.py:4207-4212 直接返回), 无物理步 →
  无 pipe_wait, 帧时间 = 纯渲染 13.4ms。
- 播放态: 每渲染帧 1.19 次物理步 × 11.2ms 同步税 ≈ 13.9ms + 逻辑步
  scripts 0.6ms + interp.advance 0.3ms + 桶重填 1.0ms + world/interp 重算
  +2.5ms → 帧时间 39.7ms。用户机 (GPU 弱一档, 分辨率更高) 等比放大后
  ≈55-65ms = 15-18FPS; 若窗口叠加 Qt 面板重绘/VS 打开其他程序 → 个位数。

【连带发现: 逻辑步里的 dt 污染已排除】
- 时钟 advance 收到的 render_dt = paintGL 墙钟 (ui/loom_gui.py:177-179),
  39.66ms/帧 → 20Hz 下 0.79 逻辑步/帧、30Hz 下 1.19 物理步/帧, 实测吻合
  (core_clock.py:73-110 accumulator 数学正确; 无双重推进/标志竞态)。
- 批3 嫌疑② (_advanced_this_frame 竞态): 排除。paintGL 先 advance 置
  True → editor.render:1765 检测跳过 → :1767 清 False, 每渲染帧恰好一次
  (qt_play_probe 逐帧计数 300 帧 = 238 逻辑步/357 物理步, 无重放无丢失)。
- 批3 嫌疑③ (_run_scripts 额外开销): 排除主嫌疑 — 脚本线程同步模型
  0.58ms/逻辑步, 占比小。
- 批3 嫌疑④ (toggle_play _split_reset/interp 对齐): 排除 — 边界 align
  块 (editor.py:1648-1654/1741-1747) 正常执行, 无可见异常。
- 批3 嫌疑⑤ (GC): 排除 — 探针窗口 p99=50.8ms 与 p50=42.5ms 差 <20%,
  无尖刺形态, gc_play_enter freeze 生效。

【修复方向 (按收益排序, 供决策; 本次未改代码)】
1. **pre_step 提速/降频** (治本): 9.81ms 纯 Python 是绝对大头。
   a) 脏检测批量化: _model_dirty 逐体三对象元组比较 → 用 interp_state
      同款 SoA 平面一次抓取 + numpy 广播比较 (500 体 9.81→~1ms 可期);
   b) 或粗筛跳过: 上帧 _transform_snapshot keys 未变的体 (静止/无脚本)
      直接跳过 dirty 扫描 (引擎已有 keys 协议可复用)。
2. **post→wait 填真活**: 把渲染帧 CPU prep (aabbs/shadow VP/桶重填)
   挪进 post 与 wait 之间 (逻辑位姿在该渲染帧已定, 数据安全; 挪移后
   pipe_wait 与 prep 重叠, 帧时间 ≈ max(物理线程, prep) 而非相加)。
   这是批4 设计 §8.1 的本意, 需要编辑器路径把 _parallel_shadow_and_
   collision 之前的段重排进 _update_physics_bridge 的 wait 前钩子。
3. **pre_step 拆两段跨帧流水**: pre 的脏检测/策略R 段在 post 后主线程做
   (改模型属性只有主线程能做), 只把 set_position/set_velocity 调用和
   step 留线程 — 重叠面最大但动 R1 边界, 风险最高, 放最后。
4. 低风险止血: 用户设置 physics_fps=30 且逻辑帧步进后物理步常为 1.19/帧
   — 若物理步与逻辑步同拍 (批1 定案 #1: 物理作为逻辑帧内子步), 每渲染帧
   至多 1 次同步税; 或物理线程化仅对 step C 段 (0.27ms) 收益太薄, 可
   整体回退 NO_PIPE 并接受主线程内联 (48ms 中 pre 16.9ms 持 GIL — 不佳,
   不推荐, 仅作数据留档)。

====================================================================
三、根因2 (#2 GPU 吃不满) 定位: 每渲染帧全额重算的 CPU prep
====================================================================
【GPU 侧实证 (tests\_tmp\gpu_probe.py, PlayerApp 分离模式 400 帧)】
- FPS=44.2 (22.63ms/帧), **GPU 平均 30.2% / 峰值 35.0% / 最低 24.0%**
  (nvidia-smi 40 样本) — GPU 远未吃满, 帧率瓶颈 100% 在 CPU 主线程。
- 已插桩合计 39.73ms ≈ 帧时间 22.63ms (LOOM_PROFILE 计时含池上并行
  双计; 主线程串行关键路径 = logic_step 3.44 + world 0.97 + interp 1.21
  + shadow_prep 15.60 + buckets 1.12 + GL 提交)。

【prep 段逐项 (Qt 播放态实测, ms/渲染帧)】
| 段            | 耗时  | 内容在渲染帧间是否变化      | 可否按逻辑帧缓存   |
|---------------|-------|---------------------------|--------------------|
| aabbs         | 9.43  | 逻辑帧没跑时与上帧逐位相同 | 可以 (D3 已保证)   |
| shadow_bounds | 5.39  | 只依赖 aabbs+光源 (静态)   | 可以               |
| collide_pairs | 5.02  | 只依赖 aabbs (播放期事件)  | 可以               |
| shadow_cornerfill/matmul | 5.0 | 同上                   | 可以               |
| world_matrices| 1.97  | 逻辑矩阵 (fw_cache 命中≈0) | 已缓存 ✓           |
| interp        | 1.24  | 插值矩阵 (每渲染帧必须)    | 不可 (本来就便宜)  |
| buckets       | 1.01  | 插值矩阵 f32 化+上传       | 静止帧可 (闸在, 但播放态必重填) |
| pipe_wait     | 13.88 | 根因1, 见上               | -                  |

【关键账】aabbs+shadow_bounds+collide_pairs+cornerfill+matmul ≈ 15.3ms
/渲染帧, 全部消费 _frame_world (逻辑位姿) — 分离模式下逻辑位姿只在逻辑
帧变 (20Hz), 渲染帧 25FPS 里约 55% 的渲染帧逻辑没跑, 这些帧的 prep 结果
与上帧**逐位相同**却全额重算 (D3 定案 _frame_world=逻辑位姿正是为了
"碰撞/阴影共享一次 AABB", 但没有把这次 AABB 按逻辑帧缓存)。
代码位置:
- engine.py:4451-4453 render 每渲染帧调 _parallel_shadow_and_collision;
- engine.py:2450-2452 内部每帧 _model_aabbs_par (aabbs 段 9.4ms) →
  need_shadow→_compute_light_vps (shadow_bounds) + need_collision→
  collide_pairs (with_events=播放态恒 True)。
- 缓存键现成: 桶闸 pose 维 (engine.py:4335-4341) 已算出 "本渲染帧逻辑
  是否步进+是否静止" (it.static_frame()/_logic_steps), 但只用于桶, 未
  用于 aabbs/阴影 VP/碰撞对 — 三处消费同一 _frame_world, 共用一个
  "逻辑帧代际" 缓存即可 (static_frame 帧 aabbs/shadow_prep/collide
  三段合计 ~15ms 直接归零)。

【为什么 bench 分离只涨到 40-46 而 Qt 播放态掉到 25】
- bench: dt 恒 1/120 → 物理步 0.5/帧 × 11.2ms 同步税 = 5.6ms/帧 (比
  NO_SPLIT 的 update_physics 16.15ms 便宜) → 26.8→40.1 涨;
- Qt: dt=墙钟 39.7ms → 物理步 1.19/帧 × 11.2 = 13.9ms + 逻辑步 0.79×
  (scripts+interp.advance) ≈ 15.2ms → 超过 prep 省下的部分 → 暴跌。
- 结论: 同步税与逻辑步成本是渲染 dt 的函数, 渲染越快 dt 越小步数越少,
  系统自平衡在 ~25FPS (39.7ms) 处稳定 — 与用户实测 "GPU 50 帧上下徘徊"
  同构 (用户机 prep 更快/逻辑更慢的平衡点)。

【修复方向】
1. prep 按逻辑帧代际缓存 (见上, 一次省 ~15ms/静止渲染帧): 收益最大且
   纯增量 (一个 _prep_gen 计数器 + 三处入口早退), 不动 R1/R3。
2. 根因1 修复 (pre_step 批量化 + 重叠) 落地后, 渲染帧率上抬会自动减少
   每帧步数 (accumulator 自平衡), prep 缓存决定上抬的天花板。
3. 顺带把 editor.py:1781 buckets 包上 _profile + build_entry/stress_probe
   keys 补 'pipe_wait', 台账口径闭合 (三处都只改一行, 诊断时代价已付)。

====================================================================
四、附: NO_SPLIT 逃生门编辑器路径逻辑全丢 (bug, 必修)
====================================================================
【复现】tests\_tmp\nosplit_logic_probe.py: LOOM_NO_SPLIT=1 下编辑器
  toggle_play 播放, rotate 脚本球 60 帧 rotation 变化 0.0000°,
  FPS=1406 (因为什么都不跑)。
【根因】engine.py:4202-4221 advance_logic:
      if not getattr(self, 'is_playing', True): ... return
      clk = self._ensure_split()
      if clk is not None: ...        # 分离推进
      # ← 没有 else: clk is None (NO_SPLIT/_split_enable=False) 时
      #   什么都不做, is_playing 播放态的脚本/物理/音频/动画全丢
  批3 设计 (分离批3_4_实施设计.md §2.2 advance_logic) 明确要求 split 关
  时走 `self._logic_split_fallback(render_dt)` 旧四行 (A/B 基线逐位),
  落地代码缺这个分支。批1 的 engine.render:4432 else 分支只救了
  run()/bench/测试直调路径 (不走 advance_logic 的), 编辑器 paintGL
  (loom_gui.py:182 先调 advance_logic) 踩中。
【影响】用户侧表现: 设置.json "logic_fps":0 或 LOOM_NO_SPLIT=1 时,
  编辑器播放态场景完全静止 — 用户按逃生门回退会得到"更坏的假象"
  (帧率 1406FPS + 场景不动), 且这是三档逃生门里承诺"旧行为逐位"的那档。
【修复方向】advance_logic 补 else 分支 = 旧四行 (_run_scripts →
  update_physics → update_audio → update_animations, dt=render_dt),
  与 engine.render:4432-4441 逃生门分支逐字一致; 一行守卫测试:
  NO_SPLIT 下 rotate 球 60 帧 rot.y 必变 (本报告探针即用例)。

====================================================================
五、探针与取证物清单 (tests\_tmp\, 均为新增诊断工具, 未动引擎源码)
====================================================================
- qt_play_probe.py    真 Qt 窗口 (LoomGUI 面板+QTimer+paintGL 真链路),
                      [--nosplit|--nopipe] 三态, paintGL/pipe monkeypatch 计时
- split_play_probe.py offscreen standalone ctx 编辑器 (无 Qt 面板) 对照
- micro_probe.py      逻辑步内部拆解 (scripts/audio/anims/phys 段计时)
- micro2_probe.py     物理线程三段拆解 + post→wait 间隙 (bridge 方法线程侧计时)
- buckets_probe.py    桶闸命中审计 (重填 200/200 帧 + static_frame 0/200)
- gpu_probe.py        GPU 利用率采样 (PlayerApp 分离模式, nvidia-smi)
- nosplit_logic_probe.py  NO_SPLIT 逃生门逻辑丢失复现 (60 帧 0.00°)
数据快照: 本文件 §一/§三两张表 + §〇 执行摘要; 台账 (bench_result_对比台账.txt)
建议把 NO_SPLIT 编辑器播放态 50.4FPS 标注 "逻辑丢失态, 无效基线"。

====================================================================
(完) 诊断代理 2026-09-05; 复跑命令均在各探针 docstring。
====================================================================

