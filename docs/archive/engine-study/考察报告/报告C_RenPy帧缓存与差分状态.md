*(抢救自炸掉的会话 cf1dc55d, jsonl L1974, 2026-09-02)*

所有源码已通读完毕 (render.pyx / gl2statecache.pyx / gl2draw.pyx / predict.py / im.py / gl2texture.pyx / gl2shader.pyx / gl2uniform.pyx / core.py GC 部分 / ursina main.py+combine.py / moderngl.cpp 核心段 / mglw scene/node)。以下为最终报告。

---

# 引擎源码考察报告： 三层设计 (帧缓存 / GL 状态差分 / 资源预载) 供 Loom 移植

说明： 源码根 `D:\my-project\_engine_study\`, 下文行号均指该根下文件。renpy 源码为 Cython .pyx (无纯 py 版 render.py)。**一个澄清： Ren'Py 里不存在名为 FramePool 的机制** (全仓 grep 无命中)， 其“多画布帧复用”实际由 render_cache 子树复用 + gl2texture 的 free_list 延迟删除承担， 下文如实对应。

---

## 第一层： Ren'Py render 缓存 (对应 Loom “编辑器态整帧缓存”)

### 1.1 机制原理 (必答问题 A 前半)

**三件套 = 键设计 + 单点失效 + 手动 mark-sweep 回收**

**(1) 键设计** — `renpy\renpy-master\renpy\display\render.pyx`

- render.pyx:48 `render_cache = collections.defaultdict(dict)` — 二级结构： 外层键 `id(displayable)`, 内层 dict 键为 `(width, height, frame_time-st, frame_time-at)` 四元组 (render.pyx:207, 250)。
- render.pyx:212-217 `render()` 先查 `render_cache_d.get(orig_wh)` 命中直接返回 — **st/at 的“基准时间”(frame_time-st) 进键而非进失效条件**： 动画时基变了是“换键”而不是“全清”。
- render.pyx:291-294 写缓存时同时存 `wh` 和 `orig_wh` 两个键 (同一 Render 可按两种尺寸命中)； render.pyx:74-103 `adjust_render_cache_times` 在 frame_time/interact_time 重同步时**批量重键 (rebase) 而不是失效**。

**(2) 失效协议 — 单点 invalidate + 向上冒泡**

- render.pyx:325-336 `invalidate(d)`: 正在渲染中则对 `render_cache[id(d)]` 里每个 Render 调 `kill_cache()`; 否则转 `redraw(d, 0)` 排队。
- render.pyx:1153-1175 `kill_cache()`: 置 `cache_killed`, **沿 `self.parents` 集合递归向上** (父 Render 也失效)， 再把自己在 `render_cache[id(render_of)]` 的条目删掉 — 失效方向是“子变 → 全部父作废”， 因为父的合成结果包含子。
- render.pyx:388-396 `process_redraws` 关键注释： "Remove this displayable and all its parents from the render cache. **But don't kill them yet, as that will kill the children that we want to reuse**" — 父失效但子不动， 未变子树整体复用。这就是 Ren'Py 的“多画布帧复用”。
- render.pyx:1177-1225 `kill()` (彻底回收， 区别于 kill_cache): 显式清空 `depends_on_list`/`render_of`/`children` (1212-1215), 置 `cached_texture=None, cached_model=None` (1220-1221), uniforms 里含 Render 时整体置 None (1223-1225) — **断环 + 释放 GPU 侧引用**。

**(3) 内存回收 — 手动 mark-sweep 绕开 Python GC (必答问题 A 后半)**

- render.pyx:704 每个 Render 构造时 append 进模块级 `live_renders` list — 引擎自己登记所有渲染产物， **不依赖 GC 发现**。
- render.pyx:501-550 `mark_sweep()`: 根集 = `screen_render` + 图像缓存里的 Render + 视频纹理 (514-527); 用**平铺 worklist 迭代 BFS** 沿 `depends_on_list` 标记 (529-542, 显式 `while i < len(worklist)` 避免递归爆栈)； 未标记的 `r.kill()`, 幸存者回写 `live_renders = worklist` (550)。每帧绘制后调用 (`display\core.py:1295`)。
- **为什么绕 Python GC**: Render 图存在双向环 (`child.parents` ↔ `parent.depends_on_list`, render.pyx:650, 653)。Python 分代 GC 收环必须从根遍历整堆可达对象 — 对象图一大 (Loom 对应 501 个大 Mesh, gen2 78ms) 就是帧尖刺。Ren'Py 的组合拳：
  1. **手动 mark-sweep 替代 gen2**: 用精确的 O(N_render) 平铺标记， 不碰整堆；
  2. **kill() 显式断环** → 剩余引用走引用计数立即释放， 不等 gen2;
  3. **抬高自动 GC 阈值**： config.py:935-941 `manage_gc=True, gc_thresholds=(25000, 10, 10), idle_gc_count=2500` (gen0 从默认 700 提到 25000), main.py:313/554-565 设置；
  4. **GC 挪到空闲帧**： core.py:2215-2241 `consider_gc` 按 `gc.get_count()` 与阈值挑最低代数收集； core.py:2259-2277 `idle_frame` 把 GC 排为空闲帧第 1 步 (且 2260 行先确认无事件待处理)， 永不发生在渲染帧中间；
  5. 渲染帧本身由 `should_redraw` (core.py:2837-2840, gl2draw.pyx:1007-1036) 决定要不要重绘 — 没变化 + 未到 0.2s 心跳就不渲染 (vsync 下 idle)。

### 1.2 Loom 移植设计 (编辑器态整帧缓存)

Loom 的对应物： 场景版本号 + 相机指纹为键， 命中则跳过 aabbs(10.9ms)+shadow_prep(~22ms)+world_matrices(2.5ms), 只做合成。数据结构与伪码：

```python
class EditorFrameCache:
    __slots__ = ('entries', 'live', 'frame_no')
    def __init__(self):
        self.entries = {}    # key -> _Entry  (键设计抄 renpy 四元组思想)
        self.live   = []     # 手动登记表, 等价 live_renders, 平铺 list
        self.frame_no = 0

class _Entry:
    __slots__ = ('key', 'color_tex', 'depth_tex', 'fbo',
                 'draw_meta', 'stamp', 'released')
    # 铁律: 只持 GL 对象 + 小元数据(int/float/tuple), 不持 Mesh/numpy 大数组
    # → 每个 entry 是小对象, gc 遍历代价趋近 0

def editor_frame_key(scene, camera, viewport):
    # 键 = (场景版本, 相机指纹, 视口, 渲染特性档)
    # 相机指纹必须包含: pos(3) yaw/pitch fov near far + 平行光方向版本(影响阴影)
    return (scene.version, camera.fingerprint(), viewport.size,
            scene.shadow_light_version)

def draw_editor_frame(cache, scene, camera, state_cache):
    key = editor_frame_key(scene, camera, viewport)
    e = cache.entries.get(key)
    if e is None:
        e = render_scene_to_fbo(scene, camera)   # 现有全管线原样走一遍
        e.key, e.stamp = key, cache.frame_no
        cache.entries[key] = e; cache.live.append(e)
    else:
        e.stamp = cache.frame_no                 # LRU touch
    composite_to_viewport(e.color_tex)           # 命中路径: 只合成 + gizmo/UI 照常
    frame_end_sweep(cache)

def frame_end_sweep(cache):                      # 抄 mark_sweep, 每帧帧末
    keep = []
    for e in cache.live:
        if e.released: continue
        if cache.frame_no - e.stamp > 60 or len(cache.live) > 8:
            e.color_tex.release(); e.depth_tex.release(); e.fbo.release()
            e.draw_meta = None; e.released = True   # 抄 kill() 显式断链
            cache.entries.pop(e.key, None)
        else:
            keep.append(e)
    cache.live = keep
```

- **失效单点**： `scene.version` 在所有 commit_* 编辑入口 +1 (Loom 的 controller 命令层 edit_*/commit_* 本就集中， 天然单点)； 相机移动 = 指纹变化 = 换键 (抄 renpy “变的是键不是缓存”)， 旧键自然被 sweep。
- **粒度决策**： 第一版做整帧粒度 (命中即全跳)， 不做 renpy 的子树级复用 — Loom 场景“无物动”时整帧命中即可吃掉全部三段堵点； 子树级留到以后。

### 1.3 与 GC 治理 / Qt scope 坑的兼容性

- **GC**: entry 不引用 501 个大 Mesh → 不制造新的“跨帧大对象图”； `live` 是平铺 list, sweep 是 O(条目数) 而非 gc.get_objects(); entry 释放显式断链走引用计数， 与已落地的 gc.freeze+阈值治理正交互补 — 治理的是“自动 GC 少发生”， 本设计保证“即使发生也无大图可遍历”。
- **Qt scope**: 缓存的是场景 FBO 的**纹理内容**， Qt 往返只破坏 GL 绑定不破坏纹理数据； 命中合成时经第二层 state_cache 恢复绑定即可 (与现有 `_screen_fb()` 雏形合并： `_screen_fb` 的差分归入 state_cache.set_fbo)。

### 1.4 Ursina 反例 (引以为戒)

`ursina\ursina-master\ursina\main.py`:
- main.py:196-221 `_update` 每帧对每个实体做 `hasattr(e,'update') and callable(e.update)` (206), scripts 二次反射 (211-214), shader continuous_input (218-220); `input()` 同款 (286-317), `text_input` 同款 (335-347); 每实体每帧 `has_disabled_ancestor()` 向上遍历 (203)。**没有任何注册表/缓存， 反射调用即帧循环主成本**。Loom 的 numba/脚本实体调度应保持“可调用对象显式注册”， 严禁每帧 hasattr 扫描。
- `ursina\scripts\combine.py:4-100` 静态合并： 每顶点 Python 循环 `Vec3(*vertex_to_world_matrix.xformPoint(...))` (38), 三角重排纯 Python (42-55), UV/法线逐顶点 Python 变换 (64-83); 缺陷： **不 weld/去重共享顶点** (verts 直接 `+=`, 三角仅按 o 偏移， 58 行)， 合并结果无缓存每次重算， auto_destroy 直接销毁原实体 (86-91) 静态批处理后不可再动， 且扫描 `scene.entities` 全局列表 (18)。教训： 批合并必须一次性 numpy 化 (矩阵整列乘) + 去重索引 + 结果缓存。

---

## 第二层： gl2statecache GL 状态差分缓存 (Loom GLStateCache 直接模板)

### 2.1 机制原理

`renpy\renpy-master\renpy\gl2\gl2statecache.pyx` 全文 209 行 (字段声明 pxd:24-58), 纯“影子状态 + 差分发出”：

| 缓存项 | 字段 | 函数 (file:line) | 差分写法 |
|---|---|---|---|
| 程序 | `current_program` | use_program 102-106 | `if program != self.current_program: glUseProgram(...)` |
| 活动纹理单元 | `current_active_texture` | activate_texture 108-112 | 初始 0 (非合法 GL_TEXTURE0, 见 31-33 注释) 强制首次必发 |
| 纹理绑定 | `current_texture[8]` | bind_texture 114-126 | 前 8 单元走数组差分， 第 8 单元以上**无条件直发** (124-126) — 缓存只覆盖确信可控的范围 |
| 混合 | 6 个 GLenum | set_blend 128-154 | eq 与 func 分两级， 各自独立差分 |
| 颜色掩码 | 4 个 bint | set_color_mask 156-163 | 任一不同才发 |
| 顶点属性开关 | `enabled_attrib_mask` 位掩码 | sync_attrib_arrays 165-193 | `to_enable = req & ~cached; to_disable = cached & ~req`, 只对差位发 glEnable/DisableVertexAttribArray (176-191) |
| sampler→unit | `sampler_bindings` dict, 键 `(program, location)` | check_sampler_binding 195-209 | 程序相关的 uniform 避免重复 glUniform1i |

调用方纪律： gl2shader.pyx:524-588 `Program.draw` 每次绘制只经 cache 走 (use_program 533 / sync_attrib_arrays 553 / set_color_mask 574 / set_blend 578, 且 **draw 后立即恢复默认 blend/mask** 585-588); gl2uniform.pyx:312-325 纹理绑定的完整三步 (activate_texture → check_sampler_binding → bind_texture)。

**外部代码绕过缓存改状态怎么处理 (必答问题 B)** — Ren'Py 的答案是“不检测， 用三个纪律把问题消灭”：

1. **只缓存引擎独占的状态**： viewport、FBO 根本不进 GLStateCache — glViewport 在 draw_screen 直接发 (gl2draw.pyx:1143), FBO 用独立小差分 `change_fbo` (gl2draw.pyx:844-851 `if self.current_fbo != fbo: glBindFramebuffer`)。缓存范围 = 全部经由唯一访问器的状态。
2. **pass 边界 reset() 重发+重同步**： 每个渲染 pass 开头 `state_cache.reset()` (gl2draw.pyx:1943-1944), gl2statecache.pyx:52-100 的 reset 是“把 GL 强制设回已知默认 + 缓存记为该默认” — pass 之间外部动了什么都被覆盖， 缓存自动重新可信。
3. **pass 末尾恢复默认**： gl2draw.pyx:1971-1975 恢复 blend/color_mask/清空属性掩码。
4. 另有帧首两阶段纪律： gl2draw.pyx:1108-1165 `draw_screen` 先 `load_all_textures` (所有延迟上传/PBO/RTT 完成于绘制前， 1126), 再 clear + 纯绘制 — 绘制段不被上传打断。

### 2.2 Loom 移植设计

```python
class GLStateCache:
    __slots__ = ('program','tex_units','active_unit','blend','color_mask',
                 'depth_test','depth_func','viewport','fbo','line_width',
                 'cull','fbo_dirty','lw_dirty','_verify_n')
    def begin_frame(self):        # 每帧入口, 等价 reset(): 
        # 已知安全项: 信任缓存继续用
        # 已知被 Qt 破坏项: 标脏, 下次访问强制重发
        self.fbo_dirty = True; self.lw_dirty = True

    def set_fbo(self, fb):
        if fb is not self.fbo or self.fbo_dirty:
            fb.use()              # moderngl Framebuffer.use()
            self.fbo = fb; self.fbo_dirty = False   # 吸收 _screen_fb() 雏形
    def set_line_width(self, w):
        if w != self.line_width or self.lw_dirty:
            ctx.line_width = w; self.line_width = w; self.lw_dirty = False
    def set_program(self, prog):
        if prog is not self.program: prog.use(); self.program = prog
    def set_blend(self, ...):  # 同 renpy 两级差分
```

**接 Qt FBO 往返** (对应 Loom 已知坑： scope 退出破坏 FBO 绑定/LINE_WIDTH, moderngl 还会破坏 color_mask/depth_mask 属性且 scope 不恢复)： Ren'Py 模式翻译到 Loom = **脏栅栏 (dirty fence)** 而非全量重置 — Qt scope 退出点 (`ui/qt_view` 返回渲染循环处) 调 `state.begin_frame()`, 只把 Qt 确定会碰的项 (fbo/line_width, 保守可加 color_mask/depth_mask/viewport) 标脏； 其余 (program/texture/blend) Qt 不动， 保留缓存价值。调试守卫： `LOOM_GL_VERIFY=1` 时每 N 帧 glGet 读真值抽查比对， 抓“谁又绕过了缓存”。

### 2.3 兼容性

- moderngl 边界事实： `VertexArray.render` 内部**无条件** `gl.UseProgram + gl.BindVertexArray` (moderngl-main\src\moderngl.cpp:6936-6937), 无法从 Python 绕开 — program 差分应在 `prog.use()` 层做， VAO 切换接受现状； `_write_uniform` 每次内部 UseProgram (moderngl.cpp:8118), 且 `prog[name]=value` 每次走 struct.pack (见第三层 3.4) — **uniform 差分必须由 Loom 在 Python 层自缓存** (值 tuple 相等则不赋值)。
- 与层一的关系： 整帧缓存命中路径只需 set_fbo + 一次 blit, 状态差分让“命中帧”的 GL 开销压到个位数调用。

---

## 第三层： 预测式预载与资源管线 (predict.py + im.py + gl2texture.pyx)

### 3.1 机制原理 (必答问题 C)

**三段式： 协程切片决策 → 后台线程解码 → 主线程上传**

1. **协程 = “预载什么”的分片器** (predict.py:81-217): `prediction_coroutine` 是生成器， 每预测一小批 displayable/屏幕就 `yield` 交还主循环； 主循环 core.py:2281-2294 `send(expensive)` 步进， **每个切片之间检查事件队列** (2260: 有事件待处理立即 break) 且非 expensive 模式限 0.5ms 预算 (2263-2265) — 预载决策永远碎片化， 不占整帧。协程在 2693-2694 创建。
2. **后台线程 = 解码器**： im.py:114-118 常驻 daemon 线程 + Condition wait/notify (540-546, 由 preload_image 477-500 的 `notify()` 唤醒)； 并行解码池 ThreadPoolExecutor 自动定容 (511-538: cpu-2, 可封顶)； 队列批提交 (598-608)。
3. **线程边界 — 解码在后台， 上传在主线程 (硬证据)**： 后台线程走 `get(predict=True, texture=True)` (preload_texture im.py:460-466) → `load_texture` → gl2texture.pyx:346-360 `from_surface` **只存 self.surface 并加入 `texture_load_queue` WeakSet (360), 不发任何 GL 调用**； 真正的 glGenTextures/glBufferData/glTexImage2D 在 `load_gltexture` (489-538), 只被**主线程**的 `ready_one_texture()` 从队列弹出执行 (gl2texture.pyx:248-264), 泵点两处： 空闲帧第 2 步循环泵 (core.py:2272-2277) 与真用图时同步泵 (im.py:372-374 `while ready_one_texture(): pass`)。上传走 PBO 中转 (gl2texture.pyx:534-538: surf.pixels → GL_PIXEL_UNPACK_BUFFER → glTexImage2D)。
4. **预算与逐出**： 像素预算 `cache_limit` — im.py:167-178: `2 * image_cache_size * 屏幕宽高` 或 `image_cache_size_mb` 字节/4; LRU 按代 (`ce.time` 逐 tick 递增， tick 232-237) 逐出 `cleanout` im.py:411-441: 超限从最老代杀， **只剩当前代仍超限 → 返回 False 直接停止预载** (防抖)； entry 尺寸估算含纹理+表面积+0.34 mipmap 系数 (im.py:67-73)。
5. **失败黑名单**： im.py:104-105 `preload_blacklist: set`; 预载异常即加入 (串行 574-578, 并行 616), 黑名单项不再预载； **主线程真用时绕过黑名单正常加载并带异常上下文报错** (im.py:313) — 预载失败静默， 使用失败显式。
6. **RTT/纹理回收**： gl2texture.pyx:229-245 `free_list` + 每帧帧末 `cleanup()` (gl2draw.pyx:1165 flip 后调用) — glDeleteTextures 延迟到帧末统一执行； gl2texture.pyx:77/90 队列用 WeakSet 防止“待加载”引用反锁对象。

### 3.2 Loom 移植设计 (obj/纹理加载)

```python
class ResourcePreloader:
    def __init__(self, ctx_thread_only):
        self.requests = collections.deque()   # 主线程投递: 场景引用的 obj/贴图路径
        self.decoded  = collections.deque()   # 后台产出: 纯 numpy/PIL 数据, 零 GL 对象
        self.blacklist = set()
        self.upload_budget_bytes = 8 << 20    # 每帧上传预算
        self.wake = threading.Condition()
        threading.Thread(target=self._worker, daemon=True).start()

    def _worker(self):                        # 只做: 读文件+解析+法线平滑+bounds
        while True:
            with self.wake: self.wake.wait()
            while self.requests:
                path = self.requests.popleft()
                if path in self.blacklist: continue
                try:
                    self.decoded.append(decode_obj_or_image(path))  # 纯数据
                except Exception:
                    self.blacklist.add(path)   # 抄 renpy: 预载失败静默入黑名单

    def pump(self, engine):                    # 主线程, 帧首调用 (抄 ready_one_texture)
        uploaded = 0
        while self.decoded and uploaded < self.upload_budget_bytes:
            res = self.decoded.popleft()
            res.upload(engine)                 # ctx.texture/ctx.buffer/vao 构建
            uploaded += res.size_bytes
```

- 抄的要点： (a) 解码产物是纯 numpy, GL 上传只发生在持有上下文的主线程 — Loom 单上下文硬约束正好同构； (b) 每帧上传预算把首帧尖刺拆散 (500 球导入不再一帧卡死)； (c) 失败黑名单+主线程真用时显式报错； (d) 决策协程可简化为“帧末空闲时从解码队列预取下一批” (Loom 无 predict 场景图， 协程机制可不做， 只抄切片+事件让路的纪律： 有输入事件待处理立即停)。

### 3.3 与 GC 治理 / Qt scope 的兼容性

- 后台线程产物 (numpy 数组) 生命周期短且无环， 不构成大对象图； decoded 队列持有的大数组在上传后立即置 None — 上传完成即引用计数释放， 不等 GC。后台解码属 GIL 竞争源， 应与已定的 `_AABB_PAR_MIN_MODELS` 闸门同理： 设 `PRELOAD_WORKERS` 环境变量逃生门 (默认 1 线程)。
- Qt scope: pump 必须放在 Qt 往返完成、`state.begin_frame()` 之后、任何 GL 绘制之前 (抄 gl2draw 两阶段帧： 上传段与绘制段分离)。

### 3.4 必答问题 D: moderngl Buffer.write 的拷贝层数与零拷贝形态 (硬事实)

`moderngl\moderngl-main\src\moderngl.cpp`:

- **Buffer.write** (moderngl.cpp:922-956; Python 包装 __init__.py:100-101 一行直透)： 939 行 `PyObject_GetBuffer(data, &view, PyBUF_SIMPLE)` — **直接取 data 的内存指针， Python 侧零拷贝** (numpy 数组实现 buffer protocol, C 连续时 view.buf 就是数组首地址)； 945-948 越界检查； 953 行 `gl.BufferSubData(GL_ARRAY_BUFFER, offset, view.len, view.buf)` — 唯一一次数据移动是**驱动侧**从用户内存进 GL 缓冲 (DMA, 不可避免)； 954 释放 view。结论： **numpy→GL 共 1 层拷贝 (驱动层)， Python 侧 0 层**。
- **创建路径同构**： ctx.buffer(numpy) → moderngl.cpp:847-896, 850 行 GetBuffer + 887 行 `gl.BufferData(..., buffer_view.buf, ...)` 同样零 Python 拷贝。
- **orphan** (moderngl.cpp:1306-1327): `BufferData(size, NULL)` (1325) 纯重分配提示， 不拷数据 — 动态缓冲的“orphan 后再 write”防同步停顿套路成立。
- **能到零拷贝的调用形态**： GL 3.3 下 CPU→GL 必有驱动搬运， “零拷贝”只能指 **Python 侧零额外拷贝**， 条件 = 传入对象满足： ① 自带 buffer protocol ② C 连续。具体： 直接传 **C 连续 numpy 数组** (float32 最优) 或 bytes/memoryview; **禁止** `arr.tobytes()` (多一整份拷贝)、禁止传 Python list (无 buffer protocol, write 直接报错)、非连续数组 PyBUF_SIMPLE 会失败 (需先 ascontiguousarray, 那次才是真拷贝)。moderngl 不暴露持久映射 (write_chunks 走 MapBufferRange+memcpy, moderngl.cpp:1105-1121, 反而多一次用户内存拷贝； read/read_into 走 map+memcpy 985-996/1044-1047), tp_as_buffer (1399-1430) 只是把 GL 缓冲反向暴露为 Python buffer, 与上传路径无关。附带： `prog[name]=tuple` 每次经 `struct.pack` 造 bytes (_moderngl.py:68-79) 再 `_write_uniform` (moderngl.cpp:8098-8146, y* 格式取 view 后按类型 Uniform\*fv) — 小 uniform 无所谓， 但印证 2.3 的“uniform 差分要自己做”。
- **对 Loom 实例上传的落地指令**： 预分配一块 C 连续 float32 实例大数组跨帧复用 (与组6 堆叠缓冲复用思路一致)， 每帧 `vbo.orphan(); vbo.write(inst_array[:n])` (切片是视图， 仍零拷贝)； 500 球 16.4FPS 場景下这把实例上传压到理论最小。

### 3.5 moderngl-window 场景图速览结论 (矩阵有无缓存)

`moderngl-window\...\scene
ode.py` + `scene.py`: **有缓存， 不逐帧乘** — 全局矩阵只在 `scene.matrix` setter 时由 `calc_model_mat` 递归重算一次 (node.py:206-221, scene.py:93-97), `draw()` 只读 `_matrix_global` (node.py:106-132); 但**没有脏标记传播**， 单节点动了必须手动重算其子树， 属静态场景优化。对应 Loom: world_matrices 2.5ms 段应做“组件变换版本号”脏标记， 只重算被改子树， 与层一整帧缓存互补 (命中帧完全不重算， 未命中帧只算脏子树)。

---

## 实施顺序建议

1. **GLStateCache (层二) 先行** — 改动最小、风险最低、当天见效： 治 Qt scope 已知坑 (fbo/line_width 脏栅栏吸收 `_screen_fb()` 雏形)， 且为后续一切 GL 路径提供“只发差分”基础设施； uniform/纹理/program 差分在 Python 层自持。
2. **编辑器态整帧缓存 (层一)** — 直击 500 球编辑器态 35ms+ 全量重算 (命中帧 aabbs/shadow_prep/world_matrices/视锥全跳)； 依赖点只有 `scene.version` 单点 (controller 命令层已集中)； 与组 4 视锥剔除正交 (剔除只在未命中帧生效， 以后可叠加)； entry 设计天然防 GC 大图， 与 gc.freeze+阈值治理互补。
3. **实例上传零拷贝规范化 (D)** — 就地小改： 预分配连续 numpy 实例缓冲 + orphan/write, 全局禁 `tobytes()` 进上传路径； 顺手给 uniform 加差分 (层二顺带完成)。
4. **预载线程 (层三) 收尾** — 后台 obj/纹理解码 + 主线程预算上传 + 失败黑名单； 影响导入/加载体验而非稳态帧率， 放最后； 带 `_AABB_PAR_MIN_MODELS` 式环境变量逃生门 (worker 数与开关)， 呼应 360 拦截子进程的历史教训。

**贯穿纪律三条** (Ren'Py 二十年答案的浓缩)： ① 变化进键， 不进失效； ② 失效单点向上冒泡， 子树尽量复用； ③ 引擎自己登记渲染产物、每帧平铺 mark-sweep、释放时显式断链 — 让 Python GC 永远只面对小对象。