*(抢救自炸掉的会话 cf1dc55d, jsonl L1428, 2026-09-02)*

排查完成。以下为分析报告(只读，未改任何文件)。

# Loom 500 球场景 GPU 50% 归因与压榨设计报告

## 一、GPU 每帧工作量与 GL 调用结构 (file:line)

### 1.1 场景规模 (stress_scene.py:25-26, 82-92, 94-105)
- 500 球 × (stacks=36, slices=54) = 每球 2035 顶点 / 3888 三角 → **1,017,500 顶点 / 1,944,000 三角**；地面 plane 104×104。
- 光源： 1 阴影平行光 (full 模式) + 1 无阴影点光。

### 1.2 每帧两遍全量几何
| Pass | 位置 | 顶点/三角 | 说明 |
|---|---|---|---|
| 阴影 pass | engine.py:2411-2439 → 2441-2454 | 1.94M tri | 1024² 深度 FBO (engine.py:1445, 2147);**CULL_FACE 关闭** (engine.py:2417, 注释“防背面漏光/acne”) → 背面也光栅化， 深度填充 ~2× |
| 主 pass | editor.py:1777 → engine.py:4061-4068 | 1.94M tri | 每片元 2 光 Blinn-Phong + 阴影光 3×3 PCF 9 次比较采样 (engine.py:104-113, 205-206);**顶点着色器逐顶点 `transpose(inverse(mat3(u_model)))`** (engine.py:63) |

### 1.3 每帧 GL 调用结构 (编辑器态， 2 桶： 500 球 + 地面)
- **draw call**: 阴影 2 (engine.py:2450-2454) + 主 2 (engine.py:4064-4068) + view.draw 线族 ~6 次 (网格 editor.py→loom_gui.py:541-544 → engine.py:2524; 选中框 editor.py:1816-1817; gizmo loom_gui.py:596-597; 光源/相机图标) + gizmo 端帽 draw_screen_rect 若干 (engine.py:4239)。**合计 ~12-18 draw/帧** — 实例化后极低。
- **FBO use/切换**： 阴影 fbo.clear+use (engine.py:2446-2447) ×1 面 + 主 `use()`+clear (engine.py:4110-4111, 3977-3979) + view.draw 里每个 `scope(framebuffer=...)` 重绑同一 widget FBO ~5-8 次 (loom_gui.py:541, 596, 759; engine.py:4203, 4230, 4247) ≈ **8-12 次 bind/帧**。
- **buffer.write 上传 (每帧)**： 实例缓冲 501×96B + 501×64B = **80KB/帧** (engine.py:4058-4059); 线 VBO 每次 draw_lines 全量重写， 网格 121×4 顶点×28B ≈ 13KB × ~6 次 (engine.py:2518); uniform 小写入 ~20 次 (u_view_proj engine.py:4121/1770; 灯光块 9 连发 engine.py:2114-2121; 阴影 u_light_vp engine.py:2448)。
- **静态 (建桶一次)**： 桶 VBO/阴影 VBO (engine.py:1740-1741), 实例缓冲 reserve 按容量生长 (engine.py:1749-1764), 阴影 depth 纹理/FBO (engine.py:2141-2158)。
- **逐帧 CPU 侧 Python 打包**： `_prepare_bucket_frame` 的 501 次 `mat._sat_f32/_rgba` 属性循环 (engine.py:4052-4057) + `np.take` + 2 次写； `draw_lines` 每次 `np.concatenate+tobytes` (engine.py:2501-2518)。

**结论**： draw/FBO/上传量级都在“Python 提交 <0.5-1ms/帧”水平， GL 调用结构本身不是瓶颈。

## 二、CPU 供给链与 Qt 宿主层 (file:line)

### 2.1 编辑器态帧分解 (无物理无碰撞， 40-50FPS → 20-25ms)
| 阶段 | 实测 | 位置 |
|---|---|---|
| world_matrices | 2.51ms | editor.py:1740-1741 → engine.py:2622-2660 (501 物体 3×property 快照 engine.py:2689-2705 + S@R@T 批量) |
| aabbs | 10.86ms | engine.py:2168-2201 (n=501≥64 走池， engine.py:3274) → `_aabbs_batched` engine.py:2203-2268: **每帧 500×2035×4×8B ≈ 32.6MB f64 堆叠拷贝** (2258-2260) + 串行 njit (501<512 闸门 engine.py:3280, 2261-2264) + 501 次 Point3D 构造 (2266-2267) |
| shadow_bounds | 5.2ms | engine.py:2368 编辑器无碰撞时在**主线程串行** `_compute_light_vps` → `_scene_light_bounds_par` 4008 角点逐行 Python 填充 (engine.py:2280-2287) |
| buckets | 1.22ms | engine.py:4052-4057 (501 次 Python 属性循环) + 2 次 write |
| GL 提交+绘制+view.draw+gizmo+Qt | 残段 ~2-5ms | 上表全部 + editor.py:1780-1784 |

合计 ≈ 19.8-24ms — 与 40-50FPS 帧时间吻合。**CPU 是帧长主体， GPU 大半时间在等**。

### 2.2 moderngl/驱动提交成本
每帧 ~60-90 次 moderngl Python 调用 (含 scope 进出)， 每次约 1-3µs → **合计 <0.5ms**, 驱动 C 侧提交同样微秒级。60-90 call/帧远未触及驱动单线程提交墙 (数千 call/帧才会)。

### 2.3 Qt 宿主层 (ui/loom_gui.py)
- 帧驱动： QTimer PreciseTimer, 档位 120→周期 8ms (loom_gui.py:453-456, 1126-1135; guiloader.py:47 `FPS_LIMITS={'30':33,'60':16,'90':11,'120':8,'240':4,'unlimited':1}`); `_on_tick` → `_update_camera` → `viewport.update()` (loom_gui.py:763-782), Qt 合并 update → paintGL 同步执行整帧引擎 (loom_gui.py:163-180)。8ms 周期在 <120FPS 时不是约束， 但给测量加了 ±4ms 量化抖动。
- **swapInterval=0** 已关 vsync (loom_gui.py:2622-2626) ✓。
- **两个隐性 GPU 项**： ① QOpenGLWidget 机制下视口每帧 update 会使**整个顶层窗口走 GL 合成** (层级/检查器/工具栏全部作为纹理参与合成)， 这部分 GPU 工作不在引擎插桩内； ② **MSAA samples=4** (loom_gui.py:2621, 注释“TEMP-回退”) → 视口 4× 带宽 + 每帧 resolve。
- 300ms `_refresh_all` 轮询有 digest 缓存 (loom_gui.py:457-459, 1961), 均摊成本低。

## 三、GPU 50% 构成判定 (三分归因 + 极限帧率估算)

以帧 20-25ms、GPU busy ~10-12ms (nvidia-smi 口径) 归因：

| 成分 | 估算 | 依据 |
|---|---|---|
| **CPU 喂不饱 (GPU 等待)** | **~50-60%** | 插桩 CPU 段 19.8ms 几乎占满帧； GL 提交仅 <0.5ms; aabbs 10.86+shadow_bounds 5.2+world 2.51 三个纯 CPU 项是主凶 |
| **GPU 真实工作本就 ~8-12ms** | **~35-45%** | 阴影 pass (1.94M tri 深度-only, 不剔背面) + 主 pass (1.94M tri, ~2.5× overdraw 球海 + 9-tap PCF + 4×MSAA 带宽/resolve) + Qt 全窗合成 ≈ 5-9ms 有效工作， 加 resolve/合成/上传 ~10-12ms |
| **驱动单线程提交瓶颈** | **<3%** | 60-90 call/帧, <0.5ms Python+驱动开销 |

**CPU 归零时的 GPU 极限**： 场景两 pass 有效 GPU 工作 ≈ **5-8ms/帧** → 理论 125-200FPS; 计入 MSAA resolve + Qt 全窗合成后现实上限 **~100-150FPS** (关 MSAA 可再抬 ~20-30%)。即： 当前 50% 利用率下 GPU 每帧只干了约一半“真活”， 另一半是被 CPU 慢帧拉长的空窗被 nvidia-smi 计入了。

## 四、压榨选项 (按风险升序， 预期为估算)

### P0 — 低风险高收益 (CPU 侧， 编辑器态直接兑现)
1. **静止世界矩阵/AABB 缓存**： 编辑器态无脚本无物理， 500 球位形不变； `_soa_snap` 快照命中 (engine.py:2689-2705) 已是现成判据 — 命中时直接复用 `_frame_world` (world 2.51→0), 并给每模型世界 AABB 挂 `_struct_gen`+变换版本脏标 (aabbs 10.86→<1ms)。失效面： 位置/旋转/缩放 setter、gizmo 拖拽、undo、reparent、prefab、可见性。**预期： 帧 CPU 19.8→~5ms, FPS 40-50→75-95, GPU% 50→65-75%。风险： 失效遗漏导致幽灵碰撞/阴影错位， 需要一个“改即失效”的统一 bump 计数**。
2. **shadow_bounds 下池 + 角点填充向量化**： `_compute_light_vps` 是纯 numpy 只读 (engine.py:2374-2400), 可与 buckets 的 CPU 打包段并行； 角点 4008 行 Python 填充 (engine.py:2280-2287) 一次 numpy 成形 → 5.2→<0.5ms。光源与场景都静止时 VP 可按 (guid, AABB 脏标) 缓存。风险低。
3. **buckets 材质行向量化**： 501 次属性循环改 SoA 材质缓存 (脏标)， 1.22→~0.3ms。风险低。
4. **网格线零上传**： ui/grid.py 内容只随相机整数格变化， 淡出改 shader uniform 传 eye → 消每帧 6×13KB vbo.write+重打包 (engine.py:2518)。~0.3-0.5ms, 低风险。

**P0 合计预期： 帧 20-25→~9-12ms → 85-110FPS; GPU 供给转紧， GPU% 65-80%。**

### P1 — 中风险 (GPU/结构， 拍板后做)
5. **MSAA samples=4 去留** (loom_gui.py:2621): 关掉省 4× 带宽+resolve, 边缘质量回退 — 用户此前要求恢复， 属视觉决策， 不单方面动。
6. **法线矩阵改逐实例 CPU 预算**： 主 pass 顶点着色器 `transpose(inverse(mat3))` (engine.py:63) 每顶点执行 100 万次/帧； 改实例属性传入 (96B→+48B/实例或复用)， 顶点负载显著降。数值与 GLSL 相差 ULP 级， 视觉等价。风险： 中低。
7. **阴影 pass 恢复背面剔除**： 球体闭合网格， 深度填充减半； 但与 engine.py:2412 注释“防背面漏光/acne”的历史决策冲突， 需靶场验证 acne。风险中。
8. **full 模式 ortho 盒收缩**： 目前被 104×104 地面撑大 (engine.py:2316-2331 pad=1.5), 球区仅 58×34 → 阴影纹素密度浪费 ~2.7×; 按 caster bbox 或 receiver/caster 分离收紧。收益偏质量+少量填充， 风险低-中。

### P2 — 大工程 (与既有路线合并)
9. **组4 视锥剔除**： 主 pass 剔除球海中出视口实例 (需桶内实例紧缩/间接表)； 阴影 full 模式仍需全量 caster。收益随视角， 工程量中-大。
10. **组5 物理桥治理** (等 V02): 只解播放态 22.8ms, 不动编辑器态。
11. **分帧重叠 (frame N+1 预计算)**： aabbs/world_matrices 挪后台线程算下一帧， GL 仍单上下文主线程 — 1 帧延迟+交互滞后， 仅当 P0/P1 后仍不达标再考虑。

### 明确否决项 (只列不做)
- Vulkan/wgpu 双后端切换 (vk_renderer 已存在， 本轮冻结)； 多线程 GL/共享上下文并行提交； GPU compute 算 AABB (回读延迟+复杂度不划算)； 渲染进程外置。

## 五、诚实地板与验收指标建议

- **Python+moderngl 架构的 CPU 地板**： 缓存全落地后每帧仍剩 ~4-6ms (Qt 宿主 1-2 + buckets/GL/线族 1.5-2 + 快照/残段 1-2) — **编辑器态现实帧率天花板 ~100-130FPS**, 再往上必须动 GPU 侧或架构 (C 扩展/Vulkan, 均在否决/冻结范围)。
- **GPU 地板**： 当前负载两 pass + 合成 ≈ 5-8ms → GPU 饱和上限 ~110-150FPS (关 MSAA ~150-200)。
- **“压榨到位”验收组合 (500 球编辑器态)**： ① FPS ≥ 90 (120 档 QTimer 8ms 下可稳定贴 100+); ② GPU% ≥ 75% (nvidia-smi 同窗口采样)； ③ 插桩 CPU 合计 ≤ 4ms/帧； ④ p50 ≤ 11ms、p99 ≤ 16ms、GC 事件 0 (沿用 stress_probe.py:224-231 口径)； ⑤ NCC/回归绿。达到即认为该架构下已到地板， 剩余空间只在新场景规模 (1000+) 或后端更换。

## 六、未决问题
1. **aabbs 10.86ms 内部分解未实测**： 32.6MB f64 堆叠拷贝 vs njit vs 池同步各占多少， 需 chunk 级细拆针 (该值是主线程墙钟含池等待； shadow_bounds 是 worker 内计时 — 两种口径混在一张表， 对比需谨慎)。
2. **编辑器态无插桩探针**： stress_probe.py 是 PlayerApp+pygame 路径， 不含 Qt 合成/MSAA; 需要 Qt 宿主内 (paintGL 前后) 同款 LOOM_PROFILE 探针闭环残段。
3. **GPU% 采样口径**： nvidia-smi 150ms 轮询的窗口平均， 与 20ms 帧相位可能错拍； 建议对齐测量窗口。
4. **MSAA samples=4 是“TEMP-回退”状态** (loom_gui.py:2621), 去留需用户拍板 (涉及视觉承诺)。
5. **编辑器视口实际物理分辨率/dpr** 未确认， fragment 工作量估算 (1M px 级) 按窗口 1780×860 推算。
6. **静止缓存的失效面完备清单**需与 undo/reparent/prefab/脚本直改 transform 逐项对账后才能实施 P0-1。