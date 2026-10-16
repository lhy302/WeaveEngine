# 考察报告B: 纯 Python 批处理缓冲体系 (pyglet/wasabi2d/kivy/arcade) — 2026-09-01

来源: 考察代理B 最终报告原文存档 (源码根 D:\my-project\_engine_study\)

## 一、A2 桶 staging 层目标蓝图

### 1.1 数据结构(每 mesh 一个桶)

```python
class InstanceBucket:
    # --- GPU 侧 ---
    gl_buf   : moderngl.Buffer   # capacity*stride 字节, dynamic;VAO 持有它, 永不重建 VAO
    # --- CPU 镜像(wasabi2d MemoryBackedBuffer 模式)---
    mirror   : np.ndarray        # np.empty(capacity, dtype=INSTANCE_DTYPE), 结构化 dtype
    capacity : int               # 2 的幂 (pyglet _nearest_pow2)
    used     : int               # 高水位
    freelist : 栈                # 空闲槽号 (wasabi2d FreeListAllocator 模式)
    # --- 脏标记(三层混合)---
    _dirty   : bool              # 桶级总闸
    _lo, _hi : int               # 脏槽区间 [lo, hi) (pyglet 模式, 初始 lo=+inf hi=0)
    _grow_pending : bool         # kivy V_NEEDGEN 式"结构性变化"位
```

### 1.2 每帧流程(替代"全量重写所有桶")

```
① 写入期(物理/动画阶段)
   inst.mirror[slot] = mat           # 直接写镜像, 零临时对象
   bucket._mark_dirty(slot)          # 4 次比较合并区间: lo=min(lo,slot); hi=max(hi,slot+1); _dirty=True

② commit 期(每桶一次, 建议阴影 pass 之前统一做)
   if not bucket._dirty: return      # 编辑器全静止 → 本桶零上传
   if bucket._grow_pending:          # 罕见路径: 扩容
       新镜像 = np.empty(new_cap); 新镜像[:len(旧)] = 旧
       gl_buf.orphan(new_bytes)      # moderngl 孤儿化保对象身份, VAO 不用改
       gl_buf.write(新镜像)          # 扩容帧允许一次全量
   elif 脏区间 == 全部已用槽:
       gl_buf.orphan(); gl_buf.write(mirror[:used])        # 全量降级
   else:
       gl_buf.write(mirror[lo:hi], offset=lo*stride)       # 一次最小区间提交, memoryview 零拷贝
   _dirty=False; lo=inf; hi=0

③ draw 期(主 pass + 阴影 pass 共用同一 gl_buf)
   绑定缓存的 VAO (不重建!)
   uniform 提交走 "句柄缓存 + 值比较" (kivy 模式)
   vao.render(GL_TRIANGLES, instances=used)
```

## 二、逐家证据与可抄片段

### A. "CPU 镜像 + 脏区间合并提交"最完整实现 = pyglet BackedBufferObject

pyglet 三者兼备: 镜像 + 字节级 [min,max) 合并 + 全量降级 + 扩容全脏。

1. 属性 setter 写镜像 — pyglet\graphics\vertexdomain.py:97-108 (实例属性版 515-526)
2. 镜像直写 + 脏区间合并 — vertexbuffer.py:279-293 set_region (3.11+ 手工 if 比 min/max 快), _dirty=True; 仅标脏旁路 invalidate_region 315-323
3. commit 前置在 draw — vertexdomain.py:472-474 VertexDomain.draw 开头
4. commit 合并提交 — vertexbuffer.py:252-270: 非脏 return; 脏区间==整个 buffer 降级 glBufferData(264); 否则一次 glBufferSubData(_dirty_min, size, data_ptr+_dirty_min)(266)
5. draw 聚合 — vertexdomain.py:476-486 glMultiDrawArrays; 实例域 594-610 glDrawArraysInstanced
6. 扩容 — vertexdomain.py:427-436 safe_alloc → _nearest_pow2(62-71) → resize; BackedBufferObject.resize(vertexbuffer.py:295-309): memmove 搬旧数据 + 脏区间置全 buffer + get_region.cache_clear()

### B. 三种 slot 分配器对比

| | pyglet Allocator(allocation.py:54) | wasabi2d FreeListAllocator(index.py:160) | kivy Buffer(buffer.pyx:3) |
|---|---|---|---|
| 结构 | starts/sizes 平行 list | SortedList 自由块/自由槽号 | 定长块 + l_free 自由栈 |
| alloc | O(n) 线扫找洞 | first-fit, _reserve 2 的幂对半劈 | 弹栈 O(1) |
| 扩容 | 异常→pow2→resize | NoCapacity.recommended→_grow 追加 | realloc C 内存 |

**结论: Loom 桶内槽位是纯定长单元 → wasabi2d FreeListAllocator(index.py:171-187)是形态正解**。扩容迁移: ①CPU 侧 new[:len(old)]=old 一行(wasabi2d _grow, vertlists.py:209-218); ②GL 侧 gl_buf.orphan(new_size) 保 Buffer 身份 → VAO 不动, 再全量 write; ③容量取 2 的幂; ④realloc 搬完新旧两个区间都标脏(pyglet VertexList.resize, vertexdomain.py:148-155)。

### C. numpy 镜像 ↔ moderngl write 衔接

- wasabi2d 镜像直写: primitives\base.py:210-218 np.matmul(orig_verts, xform[:, :2], lst.vertbuf['in_vert']) — matmul 的 out 直接是结构化数组字段视图, 零临时; sprites.py:145-149 同款
- 衔接: vertlists.py:220-227 MemoryBackedBuffer.get_buffer(dirty): 首次 ctx.buffer(self.array); dirty 时 orphan()+write(self.array) — 是全量 write 无区间(359-361 TODO 自认)
- IndirectBuffer: GL≥4.2 走 render_indirect 真聚合; 否则 render_direct(146-149) Python for 循环逐 allocation render 不聚合; _initialise(124-132) 是死代码; get_vao(359-379) 每帧重建 VAO 是反面教材, 千万别抄
- 最小区间计算: [lo,hi) 合并(4 次比较/写)或 set 攒后折叠; 提交 gl_buf.write(mirror[lo:hi], offset=lo*stride); 传结构化数组行切片(C 连续), 不要 .tobytes()(arcade 5 处都在用, 多一次整块拷贝)

### D. 脏标记粒度谱系与 Loom 选型

| 粒度 | 代表 | 适用 | 不适用 |
|---|---|---|---|
| 对象级 set | wasabi2d Layer._dirty(layers.py:59-66); arcade dirties | 同对象多属性碰、O(1) 去重 | 对象数巨大 |
| 区间 [min,max) | pyglet 字节区间 | 写入点散落、一次上传覆盖全部 | 需对象身份 |
| 位标志 | kivy V_NEEDGEN/V_NEEDUPLOAD(vbo.pyx:37-39); arcade 五路 bool(sprite_list.py:311-331) | 粗粒度总闸 | 定位不到数据; arcade 式"一个动全缓冲传"正是要避免的 |

**Loom 选型: 三层混合** — ①桶级 bool 总闸+_grow_pending(编辑器静止帧整桶零成本); ②槽级 [lo,hi) 区间(物理动几百实例聚簇, 一次 write); ③对象级 set 仅用于"实例↔槽映射变动"(增删/换桶), wasabi2d group.py:54-58 "父算一次、子全标脏"模式用于挂父/层级传播。

### E. GI_IGNORE 式状态去重对 Loom uniform 提交

- 值比较挡上传前: kivy instructions.pyx:849-853 set_state 先比再置脏; shader.pyx:235-237 set_uniform 相同直接 return
- 编译期剔除: compiler.pyx:65-150 GI_IGNORE 打标跳过 apply(127-137)
- 反面教材: wasabi2d shaders.py:116-124 每帧无差别 write proj; arcade 每 draw 设 Projection(sprite_list.py:952-953)
- Loom 落地: ①Uniform 句柄缓存 self._u_proj = prog['proj'] 建桶时取一次; ②帧级值缓存 dict[name→上次 bytes] 比较后再提交; ③"同一程序连续多桶"是静态事实, uniform 从"每桶"上提为"每(程序×帧)一次"; ④场景版本号作总闸

## 三、落地步骤排序 + 验证方法

| 步 | 内容 | 抄谁 | 验证 |
|---|---|---|---|
| 1 | 桶加 _dirty 总闸 + commit 前置判断: 编辑器静止帧整桶跳过 | kivy 位标志 + pyglet commit 首行(257) | 空场景编辑器态 buckets 段≈0; NCC 不变 |
| 2 | 镜像结构化 numpy 化 + setter 直写, 消灭每实例临时对象 | wasabi2d sprites.py:141-149 | stress 167FPS 不回退; 无 per-instance 分配 |
| 3 | 槽位 freelist + pow2 扩容 + [lo,hi) 区间合并提交 | wasabi2d FreeListAllocator + pyglet(261-266) | write 字节≈动实例数×stride; spawn/despawn 压测槽复用无泄漏(used+free==capacity 断言) |
| 4 | 扩容迁移: orphan(new_size) 保 VAO + 镜像一行拷贝 | wasabi2d _grow 改 orphan | 扩容帧不超阈值; NCC 正常 |
| 5 | uniform 句柄缓存 + 值缓存 + 场景版本号 | kivy shader.pyx:235-237 + GI_IGNORE 上提 | 静止帧 uniform 调用计数归零; 转相机帧仅 projection 一次 |
| 6 | VAO/程序常驻化自查(反面确认) | wasabi2d vertlists.py:371-379 反例 | 每帧 VAO 创建次数=0 |

关键源文件:
- pyglet\pyglet-master\pyglet\graphics\{vertexbuffer,allocation,vertexdomain}.py
- wasabi2d\wasabi2d-master\wasabi2d\allocators\{vertlists,abstract,index,packed}.py + layers.py + primitives\{base,group,sprites}.py + shaders.py
- kivy\kivy-master\kivy\graphics\{vbo,buffer,compiler,instructions,shader}.pyx
- arcade\arcade-master\arcade\{sprite_list,buffered_draw_commands}.py (2.3.15 旧版)
