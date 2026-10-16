*(抢救自炸掉的会话 cf1dc55d; L1178=第一节完整重发, L1166=C尾部衔接+第二~五节)*

收到，以下重发【第一节全部内容】(内容与首版一致，未改动；一.C 的尾部从“见性翻转”起您已收到，此处不再重复)。

---

## 一、每项实施规格

### A. GC 生命周期管理

#### A0. 共享助手 (engine.py 模块级新增，三宿主共用)

**锚点**： engine.py 顶部已 `import json/os/time/numpy as np` (无 `import gc`,全项目唯一 `gc.` 在 soa_bench.py——已核实，零冲突)。在 `GLEngine` 类定义之前、模块级常量区新增：

```python
# ================ GC 生命周期 (2026-09-01 流畅度批) ================
# 播放态 GC 阈值 (threshold0/1/2)。依据:
#   - threshold0 700→50000: 500 球播放期 churn 12-15K tracked 对象/帧, 默认 700
#     每帧可触 17-21 次 gen0 (调度+幸存者升级开销); 50000 → 约 1 次/3-4 帧
#     (counter0 按"净增"计, 大进大出的 churn 净贡献小, 实际频率以 LOOM_GC_PROBE 实测为准)。
#   - threshold1 10→50 / threshold2 200: gen2 自动触发从"每 5-8 帧"降到数分钟级,
#     且配合 freeze 后 gen2 单价从 20-150ms 降到 <1ms (场景 490 万槽已永久代化)。
#   - 备选档 (20000, 25, 100): 若探针显示 gen0 单次 p99 > 1ms 再降档, A/B 用
#     LOOM_GC_LEGACY=1 与 LOOM_GC_PROBE=1 实测裁决, 常量只改这里一处。
_GC_THRESH_PLAY = (50000, 50, 200)
_gc_thresh_prev = None      # 进入前 gc.get_threshold() 快照 (退出恢复用, 非硬编码)
_gc_play_active = False     # 冻结态标志 (PlayerApp.load_scene 包裹判据)

# ★铁律: 禁止 gc.disable ——
#   1) 脚本实例天然成环: update_scripts 绑 s.obj=m / s.engine=self; remove_model
#      (播放中) 后遗留 s.obj→m→sc→_script→s 真环, refcount 不可回收, 必须 gen2;
#   2) 用户脚本更易造环 (self 挂回调/缓存/监听);
#   3) 发布 exe 玩家长局无兜底重启时机, disable = 内存单调上涨;
#   4) 自定义脚本生态 (scripts.py 注册制) 是硬要求, 不能牺牲循环回收换流畅。

def _gc_enabled():
    """LOOM_GC_LEGACY=1 时全部 GC 管理变 no-op (A/B 基线 + 秒级回滚通道)."""
    return os.environ.get('LOOM_GC_LEGACY') != '1'

def engine_gc_frozen():
    """当前是否处于冻结播放态 (load_scene 包裹判据; 探针/测试用)."""
    return _gc_play_active

def gc_play_enter():
    """进入常驻播放态调用 (PlayerApp 场景加载后 / EditorApp toggle_play 进播放 /
    压测探针预热后): full collect 清进入前垃圾 → freeze 把全部 tracked 对象移入
    永久代 (501 Mesh 的 vertices/faces/face_colors 大 list ≈ 490 万槽从此不进
    gen2 遍历) → 放宽阈值. 冻结对象仍完全可用, 只是 GC 不再扫/收."""
    global _gc_thresh_prev, _gc_play_active
    import gc
    if not _gc_enabled():
        return
    try:
        gc.collect()                      # 只冻"活的" (冻结对象 unfreeze 前永不回收)
        gc.freeze()
        if _gc_thresh_prev is None:
            _gc_thresh_prev = gc.get_threshold()
        gc.set_threshold(*_GC_THRESH_PLAY)
        _gc_play_active = True
    except Exception as e:
        print("[gc] gc_play_enter 失败 (忽略, 回退默认 GC): %r" % (e,))

def gc_play_exit():
    """退出播放态调用 (EditorApp toggle_play 退播放 / PlayerApp.load_scene 包裹):
    unfreeze (冻结对象回普通代, 播放期垃圾/断环可回收) → full collect →
    阈值恢复进入前实测值. 幂等: 未 enter 时 unfreeze/collect 亦无害."""
    global _gc_thresh_prev, _gc_play_active
    import gc
    if not _gc_enabled():
        return
    try:
        gc.unfreeze()
        gc.collect()
        if _gc_thresh_prev is not None:
            gc.set_threshold(*_gc_thresh_prev)
            _gc_thresh_prev = None
        _gc_play_active = False
    except Exception as e:
        print("[gc] gc_play_exit 失败 (忽略): %r" % (e,))
```

#### A1. 接入点① runtime.py — PlayerApp 场景加载完成后

**锚点**: `PlayerApp.__init__`,现行为最后一个语句是 `self.set_mouse_locked(True)` (M39,在 active_camera/轨道相机分支之后)。在它之后、`__init__` 末尾插入。同时把顶部 `from engine import GLEngine` 扩为 `from engine import GLEngine, gc_play_enter, gc_play_exit, engine_gc_frozen`。

```python
        # GC 生命周期 (流畅度批): 场景加载完成即冻结长寿命对象 (501 Mesh 大 list
        # ≈490 万槽永久代化) + 放宽阈值 —— 发布玩家=常驻播放态, gen2 不再全量遍历
        # 场景 (1% low 帧尖刺本体). 一次性代价: enter 内 gc.collect() 在加载尾
        # 多花 ~20-150ms (加载时刻, 可接受). LOOM_GC_LEGACY=1 回退.
        gc_play_enter()
```

**同文件** `PlayerApp` 新增覆写 (防脚本 M37 `engine.load_scene` 运行时切关卡把旧场景钉死在永久代):

```python
    def load_scene(self, path):
        """M37 运行时切场景 (GC 批包裹): 冻结态下旧场景对象被 freeze 钉死,
        先解冻回收再冻新场景 —— 防脚本切关卡长局内存单调上涨."""
        frozen = engine_gc_frozen()
        if frozen:
            gc_play_exit()               # 解冻旧场景 + 清播放垃圾 + 阈值还原
        try:
            return super().load_scene(path)
        finally:
            if frozen:
                gc_play_enter()          # 冻结新场景 + 播放阈值 (加载失败也重冻)
```

#### A2. 接入点② stress_probe.py — 预热 40 帧后

**锚点**: `main()`,现行为 `for _ in range(40): eng.render(1.0 / 120.0)` (注释 “---- 预热 (让脚本实例/阴影贴图/缓存就位) ----”) 之后、`eng._stage_times.clear()` 之前插入:

```python
    # GC 冻结 (流畅度批): 预热后把 GL 惰性资源 (阴影 FBO/桶 VAO/文字纹理缓存/
    # 脚本实例) 一起冻进去 —— 测量窗口=稳态, 与发布玩家生命周期一致.
    # (PlayerApp.__init__ 已冻过一次, 此处是叠加冻结预热期新增对象, 合法.)
    from engine import gc_play_enter
    gc_play_enter()
```

#### A3. 接入点③ editor.py — toggle_play 进/出播放

**进入分支锚点**: `toggle_play()` 内 `self.is_playing = True` → `self._ensure_phys_bridge()` (B1 注释块) → `for m in self.models: sc._script = None; sc._script_broken = False` 循环。插在该 **for 循环之后、`cam = self.active_camera_object()` 之前** (顺序有讲究: 先把上一轮播放残留的脚本实例引用摘掉,enter 内的 collect 才能回收它们,冻结前不留垃圾):

```python
            # GC 生命周期 (流畅度批): 冻结编辑态场景 (快照/模型大 list 永久代化)
            # + 放宽阈值 —— 播放期 GC 只扫增量 churn. 上面刚清空的旧脚本实例
            # 会被 enter 的 collect 先行回收, 不被冻进去.
            gc_play_enter()
```

**退出分支锚点**: `toggle_play()` else 分支末尾,现行为最后一段是 `try: self.set_mouse_locked(False) / except Exception: pass` (M39 注释)。插在其后 (此时快照字段已置 None、`_destroy_phys_bridge()` 已完成,播放期全部垃圾已成形,一次 collect 收干净):

```python
            # GC 生命周期 (流畅度批): 解冻 (冻结对象回普通代, 播放期垃圾与
            # remove_model 型脚本环可回收) + full collect + 阈值还原进入前实测值
            # (gc.get_threshold 快照, 非硬编码 700,10,10)
            gc_play_exit()
```

editor.py 顶部 `from engine import (...)` 增加 `gc_play_enter, gc_play_exit`。

**测试桩兼容**: tests/test_playmode_edges.py 用 `EditorApp.__new__` 无头桩直调 toggle_play——gc_play_enter/exit 是纯 gc 调用,无 GL/无 self 依赖,桩路径零影响。

#### 兜底备案 (只设计，不强制实现)

“帧预算有余量时手动 `gc.collect(1)`":

- **判定点**: `GLEngine.render()` 尾部 (`pygame.display.flip()` / 外部模式交换之前) 与 `EditorApp.render()` 尾部 (`self._update_fps()` 之后)。渲染收尾处 = 本帧主要工作已完成,collect 的耗时落在本帧已计量的尾部,不会打乱下一帧阶段计时的对账。
- **预算怎么读**: 帧首 `perf_counter` t0 (render 入口加一行,仅备案启用时);预算 = `1000.0 / 当前帧率档位` (编辑器帧率档位设置 30-240/无上限;无上限档改用滚动中位帧时间 ×0.5 作盈余判据)。条件 `已耗ms < 预算 × 0.5` (盈余 ≥50% 才动手)。
- **时机智能化 (推荐判据)**: 不是定时做,而是**抢跑** —— `gc.get_count()[1] >= gc.get_threshold()[1] * 0.9` (gen1 接近自动触发) 且预算盈余时主动 `gc.collect(1)`,把“随机时刻的自动 gen1”变成“预算内主动 gen1"。
- **频率限制**: 最小间隔 5s (`_gc_babysit_last` 时间戳) + 帧计数节流 (每 600 帧至多评估一次)。collect(1) 在 freeze 后只扫播放期 gen0+gen1,单价 <1ms。
- **验证**: 用 LOOM_GC_PROBE 对比开启备案前后 gen2 触发次数是否归零、gen1 事件是否集中落在盈余帧。

#### 失效路径 (A)

| 风险 | 防护 |
|---|---|
| freeze 钉死本应回收的对象 | 纪律: enter 前必 collect;所有“退出冻结态”路径 (toggle_play 退出 / load_scene 包裹) 必调 gc_play_exit;`_gc_play_active` 标志统一判据 |
| 双重 enter 覆盖阈值快照 | `_gc_thresh_prev is None` 哨兵,重复 enter 不覆盖快照 |
| gc 回调/其他库依赖代际行为 | 阈值只放宽不关闭;freeze 不改对象语义;全 helper try/except 降级 + 打印 |
| 异常中断播放 (脚本崩不崩不影响) | toggle_play 两分支不抛即可;exit 在分支尾,restore 语义完整 |

#### 兼容性表 (A)

| 行为 | PlayerApp (发布玩家) | EditorApp | stress_probe |
|---|---|---|---|
| freeze 时机 | `__init__` 尾 (场景加载后，首帧前) | toggle_play 进播放 (phys bridge + 清旧脚本实例后) | `__init__` 已冻 + 预热 40 帧后叠加 |
| unfreeze | 无常驻退出；仅 load_scene 包裹内 exit→enter | toggle_play 退播放尾 | 无 (进程短命) |
| 阈值 | enter 设 (50000,50,200) 常驻 | 进 set / 退 get_threshold() 快照还原 | 预热后设，窗口内生效 |
| gc.collect | enter 前 1 次 + load_scene 包裹 | enter 前 / exit 后 | enter 前 (窗口外，不污测量) |
| 主要风险 | 脚本 load_scene (已包裹) | 播放期脚本 load_scene (见 §四边界) | 无 |

---

### B. gc 对账探针接入 (stress_probe.py)

(完整逻辑/输出格式/判定标准在 §三；此处为接入点规格。)

**锚点 1 — 逐帧 dt 改造**: `main()` 测量窗口，现行为 `t0 = time.perf_counter()` + `while frames < n_frames: eng.render(...); frames += 1` + `wall = time.perf_counter() - t0`。改为逐帧 perf_counter 列表，**wall/fps 口径与输出行保持不变**:

```python
    t0 = time.perf_counter()
    dts = []                                   # 逐帧墙钟 (秒)
    while frames < n_frames:
        _f0 = time.perf_counter()
        eng.render(1.0 / 120.0)
        dts.append(time.perf_counter() - _f0)
        frames += 1
    wall = time.perf_counter() - t0            # 口径不变 (含循环开销, 兼容旧输出)
```

**锚点 2 — 探针挂载/摘除**: 挂载在测量窗口开始前 (`cpu0 = sample_thread_cpu()` 之后、`while` 之前)，`finally` 里按对象身份摘除 (防误删其他消费者)。`gc_events` 元素 = `(frame_idx, gen, ms, collected, uncollectable)`。

**锚点 3 — 阶段表补位**: 汇总打印的 `for k in ('physics', 'world_matrices', 'aabbs', 'shadow_prep'):` 扩为 `(..., 'shadow_prep', 'buckets')` (组8 已在 engine.render 加 `_profile('buckets', ...)` 插桩，探针补打这一行，旧键不动)。

**锚点 4 — 新增汇总块**: 全部 GC/帧统计打印追加在“每线程 CPU%”块之后、`eng._stop_parallel()` 之前 (格式见 §三)。

**兼容性**: LOOM_GC_PROBE 默认关 → 不挂回调，探针行为与现状唯一差异 = 逐帧 dt 列表 (内存 N×float,可忽略)；LOOM_GC_LEGACY=1 时 gc_play_enter no-op,得到与“今天”完全一致的基线跑。

---

### C. `_fw32` 逐帧分配消减 (engine.py `_prepare_bucket_frame`) — 开头部分

**锚点 (现行为)**: `_prepare_bucket_frame` 内三处分配/拷贝：

1. `self._fw32 = np.ascontiguousarray(fw, dtype='f4')` — 每帧新建 (n,4,4) f4;
2. `st[:k, 0:16] = self._fw32[idxs].reshape(k, 16)` — 花式索引新建 (k,4,4) 临时 + reshape 视图；
3. `inst['sha'].write(self._fw32[idxs], 0)` — 第二次花式索引新建 (k,4,4) 临时再上传。

`self._fw32` 全项目仅此函数消费 (已 grep 核实： 初始化处注释、`_release_bucket_resources` 置 None、本函数 3 处；vk_renderer 不引用)，改分配策略安全。相关协作函数: `_grow_bucket_inst` (容量变化时 `inst.pop('stage', None)`)、`_release_bucket_resources` (`inst.pop('stage', None)` + `self._fw32 = None`)。

**持久缓冲结构定义**: `_fw32` 从“每帧新建 (n,4,4) 精确尺寸”改为**容量缓冲** (cap ≥ n,只在扩容帧 `np.empty` 分配，每帧仅一次原地 cast 拷贝 `buf[:n] = fw`);每桶新增持久 gather 缓冲 `inst['gath']` (cap 级 (inst['n'],4,4) f4,与 stage 同寿命同重建条件)，每帧 `np.take(fw32, idxs, axis=0, out=g[:k], mode='clip')` 直写——主 pass 的 `st[:k,0:16]` 与阴影 pass 的 `sha.write` 都消费同一份 `g[:k]`,消掉全部每帧花式索引临时数组。

**改造代码草稿** (整函数替换，docstring 追加一段)：

```python
    def _prepare_bucket_frame(self):
        """A2 (2026-08-29) 每帧一次: ... (原文保留) ...
        GC 批 (2026-09-01): _fw32 改持久容量缓冲 (cap>=n, 仅扩容帧分配), f64→f4
        走原地赋值 cast (与 ascontiguousarray 同一 RNE 舍入, 逐位一致); 桶内花式
        索引改 np.take(..., out=持久 gather 缓冲, mode='clip') —— 消每帧
        1×(n,4,4) + 每桶 2×(k,4,4) f4 临时分配; sha 写复用同一份 gather 缓冲
        (主/阴影上传字节与旧路径逐位相同)."""
        fw = getattr(self, '_frame_world', None)
        if fw is None:
            fw = self.compute_world_matrices(self.models)
            self._frame_world = fw
        # 持久 _fw32: 容量 >= n, 每帧只做一次原地 cast 拷贝 (零分配)
        n = fw.shape[0]
        buf = self._fw32
        if buf is None or buf.shape[0] < n:
            cap = max(64, n) if buf is None else max(n, buf.shape[0] * 2)
            buf = self._fw32 = np.empty((cap, 4, 4), dtype='f4')
        buf[:n] = fw                       # f64→f4 原地 cast (RNE, 与 astype 逐位同)
        fw32 = buf
        buckets = {}
        for i, m in enumerate(self.models):
            if m.visible and m.mesh is not None:
                buckets.setdefault(self._mesh_key(m), []).append(i)
        self._render_buckets = list(buckets.items())
        for key, idxs in buckets.items():
            ent = self._bucket_geo.get(key)
            if ent is None:                    # 防御: 桶资源未建 (attach 路径遗漏)
                ent = self._build_bucket_geo(key, self.models[idxs[0]])
            k = len(idxs)
            self._grow_bucket_inst(key, k)
            inst = self._bucket_inst[key]
            st = inst.get('stage')
            if st is None:                     # 组1: staging 随桶持久 (release 一并清)
                st = inst['stage'] = np.zeros((inst['n'], 24), dtype='f4')
            elif st.shape[0] < k:              # _grow_bucket_inst 已扩容, stage 跟随
                st = inst['stage'] = np.zeros((inst['n'], 24), dtype='f4')
            g = inst.get('gath')               # GC 批: 持久 gather 缓冲 (与 stage 同寿命)
            if g is None:
                g = inst['gath'] = np.empty((inst['n'], 4, 4), dtype='f4')
            elif g.shape[0] < k:
                g = inst['gath'] = np.empty((inst['n'], 4, 4), dtype='f4')
            # mode='clip' 关键: np.take 默认 mode='raise' 时 out 恒被内部缓冲
            # (numpy 文档明示), 照旧分配; 'clip' 才是直写 out. idxs 恒在
            # [0,n) 内 (enumerate 产出), clip 与 raise 结果逐位相同.
            np.take(fw32, idxs, axis=0, out=g[:k], mode='clip')
            st[:k, 0:16] = g[:k].reshape(k, 16)
            models = self.models
            sat_row = st[:k, 16:17]
            col_rows = st[:k, 20:24]
            col_rows[:] = 0.0                  # color=None 的实例留 0 (旧语义)
            for q, i in enumerate(idxs):
                mat = models[i].renderer.material
                sat_row[q, 0] = mat._sat_f32
                r = mat._rgba                  # Material setter 已算; None=网格面色
                if r is not None:
                    col_rows[q] = r
            inst['main'].write(st[:k], 0)      # moderngl 吃 buffer 协议, 部分写入
            inst['sha'].write(g[:k], 0)        # 同一 gather 缓冲 = 旧 _fw32[idxs] 同字节
```

**配套三处小改** (必须，否则扩容/清场后残留旧缓冲)：

- `_grow_bucket_inst`: `inst.pop('stage', None)` 行后加 `inst.pop('gath', None)   # GC 批: gather 缓冲一并作废 (容量已变)`;
- `_release_bucket_resources`: `inst.pop('stage', None)` 行后加同款 gath pop (该函数已置 `self._fw32 = None`,与持久缓冲的“清场重建”语义一致，保留)；
- `__init__` 中 `self._fw32 = None` 注释更新为 “当帧世界矩阵 f32 **持久容量缓冲** (cap>=n, 每帧原地 cast, GC 批)”。

**逐位一致论证**:

1. **f64→f4 cast**: `buf[:n] = fw` 走 numpy copyto/cast 通路，与 `np.ascontiguousarray(fw, 'f4')` (内部 astype 语义) 使用同一标量 cast 循环，同为 round-to-nearest-even,无 FMA/快路径差异 → 位型全同。
2. **gather**: `np.take(a, idxs, axis=0)` 与 `a[idxs]` 是同一实现 (numpy 花式索引即 take);`mode='clip'` 仅对越界下标有语义差，而 idxs 来自 `enumerate(self.models)` 恒在 [0,n) → 结果逐元素相同。out 直写不改变数值。
3. **布局**: `g[:k]` 是 (k,4,4) C 连续 f4 切片，与旧花式索引临时数组的内存布局一致;`(k,4,4)→(k,16)` reshape 是行主序视图 (零拷贝);`inst['sha'].write` 读到的字节流 = 旧临时数组字节流，逐位相同 → GPU 上传内容 bit-exact。
4. **顺序**: 桶迭代序 = dict 插入序 = mesh key 在 models 中首次出现序，与现行为相同；main/sha 写偏移仍为 0;`_render_buckets` 结构不变，`_draw_main_buckets`/`_render_to_shadow_map` (两者只用 `len(idxs)`) 零改动。
5. **陈旧行**: cap−k 的残留行旧代码同样存在且从不被消费 (`write(st[:k])` 只传 k 行，`instances=len(idxs)` 只采 k 行) → 行为不变。

**与桶键缓存/idxs 变化的交互分析**:

- `_mesh_key` 的 `_bucket_key` 缓存只影响键产出，不影响 gather (每帧从活枚举重建 idxs,无“下标→行号”缓存可失效)；
- idxs 逐帧变化 (可见性/增删/排序)： gather 每帧全量重跑，缓冲只承载容量、不承载内容假设 → 天然正确；`_bump_struct` 不需感知本函数；
- 可见性翻转 (……以下从“可见性翻转”起为您已收到的部分，衔接原文)

---

以上为第一节缺失部分的完整重发；第二~五节 (实施顺序/探针设计/生态风险/验收清单) 维持首版内容不变。

---

*(以下为 L1166 首版通知, 开头与上节 C 尾部重叠, 从衔接处起为第二~五节)*

见性翻转 (visible 翻转) 只改 idxs 长度/内容 → gather 每帧全量重写前 k 行，缓冲容量足够即正确；容量缩小时**不缩容** (`buf.shape[0] < n` 才扩)，残留行同上不消费 → 无需失效钩子；
- 扩容帧 (`_grow_bucket_inst` 重建 main/sha) 同帧 gath 一并重建 (g.shape[0] < k 分支)，不会出现“新 inst['n'] 但旧 gath 更小”的窄读；
- `_fw32` 若被未来代码外部引用 (如 vk 计划)： 它现在持有的是 cap≥n 的缓冲，消费方必须一律 `[:n]` 切片读取——写入 docstring 备案；`_release_bucket_resources` 置 None 语义保留；
- SoA keys numpy 化 (非目标，仅冲突面评估)： `_transform_snapshot` 的 id 钉住机制 (`_soa_snap` 存 cur 对象本体) 在 freeze 后依然成立——冻结只把对象移入永久代，id 不会因 GC 收缩而复用；二者无冲突，numpy 化 keys 反而会减少每帧 tuple churn (与本批同向)。

#### 失效路径 / 兼容性表 (C)

| 宿主 | 行为差异 |
|---|---|
| PlayerApp | 常驻播放，每帧省 1×(n,4,4) + 2×Σ(k,4,4) f4 分配 (500 球 ≈ 3.4MB/帧→0);稳态零分配，churn 大降 |
| EditorApp | 编辑期同路径;`_release_bucket_resources` 清场语义不变 (fw32=None + gath pop) |
| 探针 | `buckets` 阶段计时含新逻辑，同阶段名对账；无新环境变量 |

失效回滚： LOOM_GC_LEGACY=1 **不回滚 C** (C 是纯分配优化，与 GC 无关)；回滚 = git/备份区恢复单函数。

---

## 二、实施顺序与每步验证门槛

| 步 | 内容 | 验证门槛 |
|---|---|---|
| S1 | B 先行 (探针)： 逐帧 dt + LOOM_GC_PROBE | 探针跑 300 帧 500 球，LOOM_GC_LEGACY=1 产出基线： 记录 gen2 次数/ms 分布/尖刺帧-GC 对账表 → 这是“GC 是否元凶”的判卷依据 (§三判定标准)；旧输出行 (FPS/逐阶段/CPU%) 逐字不变 |
| S2 | C: `_fw32` 持久缓冲 + gather out | (a) 回归绿 (tests/run_all.py,含 test_parallel/test_playmode_edges);(b) 渲染 NCC 对拍： 同场景同帧号抓主 pass 截图，改造前后 diff=0 或 NCC=1.000;(c) 探针复跑： 500 球 FPS 不降 (≥持平)，churn 验证——`sys.gettotalrefcount` 或简化为探针加打的 gen0 触发次数显著下降 |
| S3 | A1 接入点① runtime (PlayerApp) | `py -3.12 Loom.py --run stress_500spheres.json` 正常起 + 脚本游戏 (含 load_scene 的) 切关卡内存不涨 (任务管理器观察 3 分钟)；回归绿 |
| S4 | A3 接入点③ editor toggle_play | test_playmode_edges 全绿；实机： 播放→停止→播放循环 20 次，内存无单调上涨 (验证 exit 链回收) |
| S5 | A2 接入点② 探针冻结 + 阈值联测 | 探针 LOOM_GC_PROBE=1 (不带 LEGACY): gen2 事件归零 (freeze 后 490 万槽不在代内)，gen0 频率≈1/3-4 帧、单次 p99<1ms;**1% low 替代指标** (§五) 改善可量化 (p99 帧时间与 >2×中位尖刺计数对比 S1 基线) |
| S6 | 兜底备案 (可选，仅当 S5 后 gen2 仍可见) | 按 §一 A 兜底设计实现帧预算 babysit;验收=gen2 自动触发为 0 且全部 gen1 落在盈余帧 |

每步结束按台账惯例在《未测试功能测试方向指南.txt》补条目 (新功能必须进测试台账铁律)。

---

## 三、探针设计 (LOOM_GC_PROBE)

**开关与挂载**： `os.environ.get('LOOM_GC_PROBE') == '1'` 时，stress_probe.py 在测量窗口前挂 `gc.callbacks`:

```python
class _GCProbe:
    def __init__(self):
        self.events = []            # (frame_idx, gen, cost_ms, collected, uncollectable)
        self._t = 0.0
    def __call__(self, phase, info):
        if phase == 'start':
            self._t = time.perf_counter()
        else:                        # 'end'
            cost = (time.perf_counter() - self._t) * 1000.0
            self.events.append((probe_frame_idx[0], info['generation'], cost,
                                info.get('collected', -1), info.get('uncollectable', -1)))
_gc_probe = _GCProbe() if os.environ.get('LOOM_GC_PROBE') == '1' else None
if _gc_probe:
    import gc; gc.callbacks.append(_gc_probe)
```

frame_idx 由主循环 `probe_frame_idx = [0]` 每帧自增 (闭包列表，探针回调在渲染线程内同步触发，无需锁)。窗口结束 `finally`: `gc.callbacks.remove(_gc_probe)` (按对象身份)。

**输出格式** (追加块，窗口结束打印):

```
========== GC 对账 (LOOM_GC_PROBE) ==========
GC 事件分代统计 (窗口 %d 帧):
  gen0: 事件=%d  总ms=%.2f  avg=%.3f  max=%.3f  p99=%.3f
  gen1: ...
  gen2: ...
延迟直方图 (全部事件, ms):
  [0,0.1)=%d  [0.1,0.5)=%d  [0.5,1)=%d  [1,2)=%d  [2,5)=%d  [5,10)=%d  [10,20)=%d  [20,50)=%d  [50,100)=%d  [100+)=%d
窗口前后 gc.get_stats() 差值 (gen0/1/2 collections): %d/%d/%d -> %d/%d/%d
帧尖刺对账: 尖刺帧 %d 个 (dt > 2×中位数 %.3fms):
  frame %d: dt=%.2fms  落入 GC: gen%d %.2fms (collected=%d)   <- 或 "无 GC 事件"
  (无尖刺帧时打印 "无尖刺帧")
逐帧 dt: p50=%.3f p99=%.3f max=%.3f ms | >2x中位 尖刺=%d 帧 (%.1f%%)
```

实现细节： p99 = 排序后 `sorted[int(0.99*len)]`;直方图边界 0.1/0.5/1/2/5/10/20/50/100;`get_stats()` 在窗口开始/结束各取一次快照差值；逐帧 dt 列表同时打印 p50/p99/max (供 §五度量)。

**尖刺对账判定标准**:

- **证明 GC 是元凶 (或主因)**： 尖刺帧中 ≥70% 落有 GC 事件，且该 GC 事件 ms ≥ 该帧超出中位数部分的 50% (即 `gc_ms >= (frame_dt_ms - p50) * 0.5`);gen2 直方图质量集中在 >10ms 桶。附加证据： LEGACY 基线 vs S5 冻结跑对比，尖刺计数显著下降且下降幅度≈被对账掉的 GC 总量。
- **排除 GC**: 尖刺帧落 GC 比例 <30%,或落入的 GC ms 远小于帧超量 (说明尖刺另有主体—— physics/AABB/GL stall,转交对应代理)；或窗口内 gen2 事件=0 但尖刺仍在。
- **部分成立**: 介于两者之间 → 报告按帧列出 top-10 尖刺帧的 GC 占比，供主线程决定是否追加备案 (§一 A 兜底)。

---

## 四、生态风险 (用户自定义脚本/插件边界)

| 场景 | 行为 | 边界说明 |
|---|---|---|
| 脚本加载顺序 vs freeze | **安全**。scripts.py 注册表 (SCRIPTS dict) 在进程启动 `load_script_dir` 时填充——早于 PlayerApp.__init__ 的 freeze (editor 路径更早)，脚本类天然被冻进永久代；即便晚加载 (游戏包 install_game_plugins 在 PlayerApp 之前、Loom.py 内)，freeze 语义=“冻时已 tracked 的不扫”，晚注册的新类照常进 gen0,无行为差异 |
| 播放中脚本动态 add/remove_model | add 的模型进 gen0 正常回收/正常被扫；**remove_model 是环源**: m→(checker 无强引用) 但 sc._script→s.obj→m、s.engine→self,靠 update_scripts 每帧惰性 (broken 后 sc._script=None) + 退出播放清环兜底；freeze 不阻碍回收 (环在 gen0/1),但**若编辑器播放期 remove 后从未 broken**,环活到 exit_play 的 gc_play_exit 才收 → 一次性延迟回收，可接受 (exit 必 collect) |
| 脚本动态 load_scene (M37 切关卡) | PlayerApp 已包裹 exit→load→enter (§一 A1);**编辑器播放期脚本调 load_scene**: EditorApp.load_scene 未包裹——播放期调用会把新场景建在冻结后世界 (正常)，但旧场景对象已在永久代不回收 → **备案缺陷**: 播放期脚本切关卡在编辑器内属罕见组合 (编辑期 play 快照语义本就冲突)，建议实施时在 EditorApp 也挂同款包裹 load_scene 覆写 (同 A1 代码，frozen 时 exit/enter),成本 8 行，纳入 S3 一起做 |
| 退出播放再进入 | exit: unfreeze→collect→还原阈值；enter: collect→freeze→新阈值。循环 N 次每次重新冻结，无累积泄漏 (exit 收干净播放垃圾)；唯一代价 = 每次进出两次 full collect (~20-150ms @500 球)，落在点击播放/停止按钮时刻，与现 Stop 行为一致可接受 |
| 插件 (plugin_loader 投放式) | 插件模块加载早于引擎构建；插件内后台线程若依赖 GC 时机 (如 __del__ 副作用)： freeze 不改回收时机只改代归属，__del__ 仍会调 (unfreeze 后)；阈值放宽使 __del__ 延迟→插件若做“依赖立即回收”的资源管理 (反模式) 会更晚释放。备案： 无已知插件依赖此;LOOM_GC_LEGACY=1 秒回滚 |
| 自定义 GUI (guiloader 投放) | GUI 走 pygame surface 缓存+脏重绘，不依赖 GC;阈值放宽后 churn 大对象 (文字表面) 生命周期延后一个 gen0 间隔 (~3 帧)，400 项 LRU 上限兜底，无泄漏 |
| gc.get_stats/调试工具 | freeze 后 gen2 stats 不再含冻结对象 (get_count 反映真实代内数)，探针以 callbacks 事件为准，不依赖 count 推断 |

---

## 五、验收清单 (1% low 度量)

**无真 1% low 采集时的替代定义** (探针已有逐帧 dt 后全部可算):

1. **帧时间 p99**: 窗口内逐帧 dt 排序取 [99%] (600 帧=最差 6 帧)。基线 (LEGACY,无 freeze) vs 改造后各跑 3 轮取中位，报告改善百分比。
2. **尖刺计数**： `count(frame_dt > 2 × p50)` 与 `count(frame_dt > 4 × p50)` 两档 (中敏/严苛)。GC 元凶成立时 2× 档应显著下降 (500 球估从每 5-8 帧一次 → 接近 0)。
3. **GC 对账闭环**： S1 基线探针报告的“尖刺帧落 GC”比例 ≥70% (元凶确认) → S5 后同一指标 <30% 且 gen2 事件=0 → 判定本批生效。
4. **附加采集法 (更接近真 1% low)**: 帧时间按 60 帧滑动窗口取窗内 p99 序列，报告该序列的 p50 (即“1% low 帧率的倒数”代理)——比全局 p99 更贴近 1% low 语义，探针打印一行即可。
5. **防假阳性守则**： 全程关 vsync (探针已设 GL_SWAP_CONTROL=0)、预热 40 帧、同场景同帧数、3 轮取中位、CPU%/GPU 采样同步记录 (排除温度/后台进程扰动)；nvidia-smi 采样线程本身有 subprocess 开销，对比跑必须两边同开。

**通过线**： 500 球 300 帧窗口，2× 档尖刺计数下降 ≥60% 且 p99 帧时间下降 ≥30% (以 S1 实测基线为准修正目标值)，FPS 均值不降 >2%,NCC=1.000,回归全绿。

---

**非目标备案** (按任务书，本轮不做): AABB 管道 (另一代理)、Mesh 501→1 共享、SoA keys numpy 化 (冲突面已评估: 与 `_soa_snap` id 钉住机制无冲突,freeze 不影响其失效判据)、vk_renderer、gc.disable (已列为铁律禁用，理由见 §一 A0 注释块)。

**关键文件** (均未改动): `D:\my-project\Loom(py源代码-工作区)\Loom\engine.py` (gc helper 模块级新增 + `_prepare_bucket_frame`/`_grow_bucket_inst`/`_release_bucket_resources`/`__init__` 四处)、`D:\my-project\Loom(py源代码-工作区)\Loom\runtime.py` (`PlayerApp.__init__` 尾 + `load_scene` 覆写)、`D:\my-project\Loom(py源代码-工作区)\Loom\editor.py` (`toggle_play` 进/出分支尾)、`D:\my-project\Loom(py源代码-工作区)\Loom\tests\_tmp\stress_probe.py` (逐帧 dt + LOOM_GC_PROBE + buckets 阶段行)。