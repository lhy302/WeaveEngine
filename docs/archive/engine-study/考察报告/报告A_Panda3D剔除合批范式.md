*(抢救自炸掉的会话 cf1dc55d, jsonl L1995, 2026-09-02)*

证据收集完毕 (coordinator 状态回复： 4 大设计问题的源码证据已全部取证完成， 直接输出最终报告)。

# Panda3D 源码考察报告： 可移植到 Loom 的渲染优化设计

源码根： `D:\my-project\_engine_study\panda3d\panda3d-master\`。以下所有 file:line 均相对该根。行号为本次实读确认。

---

## 第一部分： 四个必答设计问题

### 1. 状态排序桶 (CullBinStateSorted)

**完整排序顺序 (从重到轻)**： 三层结构。

第一层是桶本身的全局绘制顺序， 由 CullBinManager 的 sort 值决定 (`panda\src\pgraph\cullBinManager.cxx:275-289` 默认桶表)：

```cpp
add_bin("background", BT_fixed, 10);
add_bin("opaque",     BT_state_sorted, 20);
add_bin("transparent",BT_back_to_front, 30);
add_bin("fixed",      BT_fixed, 40);
add_bin("unsorted",   BT_unsorted, 50);
```

桶间比较函数 `panda\src\pgraph\cullBinManager.I:28-31`:
```cpp
bool CullBinManager::SortBins::operator () (int a, int b) const {
  return _manager->_bin_definitions[a]._sort < _manager->_bin_definitions[b]._sort;
}
```

第二层是 state_sorted 桶内排序键， **原文** `panda\src\cull\cullBinStateSorted.I:42-69`:
```cpp
INLINE bool CullBinStateSorted::ObjectData::
operator < (const ObjectData &other) const {
  // Group by state changes, in approximate order from heaviest change to
  // lightest change.
  const RenderState *sa = _object->_state;
  const RenderState *sb = other._object->_state;
  int compare = sa->compare_sort(*sb);
  if (compare != 0) return compare < 0;

  // Vertex format changes are also fairly slow.
  if (_format != other._format) return _format < other._format;

  // Prevent unnecessary vertex buffer rebinds.
  if (_object->_munged_data != other._object->_munged_data)
    return _object->_munged_data < other._object->_munged_data;

  // Uniform updates are actually pretty fast.
  if (_object->_internal_transform != other._object->_internal_transform)
    return _object->_internal_transform < other._object->_internal_transform;
  return 0;
}
```

即四键： **RenderState → 顶点格式 → 顶点缓冲 (GeomVertexData) → internal_transform**, 全是指针比较 (等价状态已被 intern 成同一指针， 见第 3 节)。RenderState 内部第三层： `compare_sort` (`panda\src\pgraph\renderState.cxx:160-180`) 按 attrib 注册时的"换状态代价" sort 值逐槽比较：

```cpp
RenderAttribRegistry *reg = RenderAttribRegistry::quick_get_global_ptr();
int num_sorted_slots = reg->get_num_sorted_slots();
for (int n = 0; n < num_sorted_slots; ++n) {
  int slot = reg->get_sorted_slot(n);
  const RenderAttrib *a = _attributes[slot]._attrib;
  const RenderAttrib *b = other._attributes[slot]._attrib;
  if (a != b) return a < b ? -1 : 1;
}
```
注册 sort 值实测： ShaderAttrib=10 (`pgraph\shaderAttrib.h:184`)、LightAttrib=20 (`pgraph\lightAttrib.h:172`)、TextureAttrib=30 (`pgraph\textureAttrib.h:196`)、其余全部=100 (`alphaTestAttrib.h:81` 等)。注释依据： `renderAttribRegistry.cxx:45-51` "heavier (more expensive to change) have lower sort values"。

**创建/排序时机**： 桶对象由 CullResult 惰性创建并跨帧持有 (`cullResult.cxx:351-370 make_new_bin`), 内容每帧重建； `add_object` 只是 O(1) push_back (`cullBinStateSorted.cxx:37-40`), **排序发生在每帧 cull 结束后** 的 `finish_cull` (`cullBinStateSorted.cxx:47-51`: `sort(_objects.begin(), _objects.end())`), 由 `GraphicsEngine::cull_to_bins` 尾部统一调用 (`display\graphicsEngine.cxx:1633-1634`)。不是脏时排序——因为排序键依赖相机距离与当帧对象集合。

**半透明/不透明的桶选择**： 每个 RenderState 只在首次使用时判定一次桶并缓存 (`renderState.cxx:1719-1765 determine_bin_index`):
```cpp
if (bin_name.empty()) {
  bin_name = "opaque";
  const TransparencyAttrib *transparency;
  if (get_attrib(transparency)) {
    switch (transparency->get_mode()) {
    case TransparencyAttrib::M_alpha:
    case TransparencyAttrib::M_premultiplied_alpha:
    case TransparencyAttrib::M_dual:
      bin_name = "transparent";   // 这些模式需要 back-to-front
      break;
    ...}}}
```
transparent 桶 (CullBinBackToFront) 按包围体中心到相机的距离降序， `panda\src\cull\cullBinBackToFront.I:37-40`:
```cpp
bool CullBinBackToFront::ObjectData::operator < (const ObjectData &other) const {
  return _dist > other._dist;   // 远的先画
}
```
距离在 add_object 时算一次 (`cullBinBackToFront.cxx:38-56`: `center = gbv->get_approx_center() * _internal_transform->get_mat(); _dist = _gsg->compute_distance_to(center)`), 空包围体直接丢弃。反向的 BT_front_to_back 桶也存在 (`cullBinFrontToBack.I:37-40` `_dist < other._dist`, 供 HZB early-out)。opaque 桶虽然主键是状态， 但同状态内部也按指针序接近 front-to-back——类注释明说 (`cullBinStateSorted.h:26-34`) "This also sorts objects front-to-back within a particular state, to take advantage of hierarchical Z-buffer algorithms"。

---

### 2. 包围体惰性失效链 (UpdateSeq 协议)

**完整字段清单 (抄给 Loom 用)** — 每个节点两块：

(a) 节点自身内部包围体 (`panda\src\pgraph\pandaNode.h:398-402`):
```cpp
CPT(BoundingVolume) _internal_bounds;
int _internal_vertices;
UpdateSeq _internal_bounds_mark;     // incremented on mark_stale
UpdateSeq _internal_bounds_computed; // set to above when computing
```

(b) 向上聚合的缓存块 (`pandaNode.h:644-654`):
```cpp
// This is the bounding volume around the _user_bounds, the _internal_bounds,
// and all of the children's external bounding volumes.
CPT(BoundingVolume) _external_bounds;
// When _last_update != _next_update, this cache is stale.
UpdateSeq _last_update, _next_update;
// We don't always update the bounding volume and number of nested
// vertices. This indicates the last time they were changed. It is never
// higher than _last_update.
UpdateSeq _last_bounds_update;
```
另有 `_user_bounds` / `_bounds_type` / `_final_bounds` (`pandaNode.h:606-616`)。以及**每条父子边上的缓存** (`pandaNode.h:474-479`, DownConnection):
```cpp
// These values are cached here so that a traverser can efficiently check
// whether a node is in view before recursing.
CollideMask _net_collide_mask;
CPT(GeometricBoundingVolume) _external_bounds;
DrawMask _net_draw_control_mask;
DrawMask _net_draw_show_mask;
```

**mark_bounds_stale 的 O(1) 向上传播** — 两段配合。先看守卫 (`pandaNode.I:612-625`):
```cpp
void PandaNode::mark_bounds_stale(int pipeline_stage, Thread *current_thread) const {
  // We check whether it is already marked stale.  If so, we don't have to
  // make the call to force_bounds_stale().
  bool is_stale_bounds;
  { CDStageReader cdata(_cycler, pipeline_stage, current_thread);
    is_stale_bounds = (cdata->_last_update != cdata->_next_update); }
  if (!is_stale_bounds)
    ((PandaNode *)this)->force_bounds_stale(pipeline_stage, current_thread);
}
```
force 版本只做一次自增然后交给父节点 (`pandaNode.cxx:2194-2221`):
```cpp
void PandaNode::force_bounds_stale(int pipeline_stage, Thread *current_thread) {
  { CDStageWriter cdata(_cycler, pipeline_stage, current_thread);
    ++cdata->_next_update;
    // It is important that we allow this lock to be dropped before we
    // continue up the graph ... }
  ...
  for (int i = 0; i < num_parents; ++i) {
    PandaNode *parent = parents.get_parent(i);
    if (parent != nullptr)
      parent->mark_bounds_stale(pipeline_stage, current_thread);  // 父节点再走"已脏则停"守卫
  }
}
```
要点： 传播不是无脑递归到根——每个祖先入口都有"已脏则停"守卫， 所以单次标记的代价 = 从变更点到第一个已脏祖先的距离， 一批变更合计代价 ≈ 变更子树 + 包络边界。`UpdateSeq` 本体是个带环绕处理的原子 uint (`panda\src\putil\updateSeq.h:37-86`, `updateSeq.I:144-185` 跳过 0/1/0xFFFFFFFF 三个特殊值)。

**查询侧判缓存有效** — 内部包围体 `pandaNode.cxx:2072-2111`:
```cpp
CPT(BoundingVolume) PandaNode::get_internal_bounds(int pipeline_stage, Thread *current_thread) const {
  while (true) {
    UpdateSeq mark;
    { CDStageReader cdata(_cycler, pipeline_stage, current_thread);
      if (cdata->_user_bounds != nullptr) return cdata->_user_bounds;   // 用户显式设置的直接用
      if (cdata->_internal_bounds_mark == cdata->_internal_bounds_computed)
        return cdata->_internal_bounds;                                  // 标记序号==已算序号 → 缓存有效
      mark = cdata->_internal_bounds_mark; }
    compute_internal_bounds(internal_bounds, internal_vertices, ...);    // 无锁重算
    CDStageWriter cdataw(...);
    if (cdataw->_internal_bounds_mark == mark) {                         // 期间没人再弄脏才提交
      cdataw->_internal_bounds_computed = mark;
      cdataw->_internal_bounds = internal_bounds; ... return ...; }
    // Dang, someone in another thread incremented ... go back and do it again.
  }
}
```
外部包围体 `pandaNode.cxx:1875-1891`:
```cpp
CDLockedStageReader cdata(_cycler, pipeline_stage, current_thread);
if (cdata->_last_bounds_update != cdata->_next_update) {
  // The cache is stale; it needs to be rebuilt.
  ... update_cached(true, pipeline_stage, cdata); ...
}
return cdata->_external_bounds;   // 否则直接返回缓存
```

**子节点 around 合成** — update_cached 的核心循环 (`pandaNode.cxx:3241-3581`): 对每个孩子先判 `_last_bounds_update != child->_next_update` (3331), 脏则递归 `child->update_cached(...)` (3333), 干净则**直接抄孩子缓存的外部包围体** (3468-3478, 同时把结果刷新到父子边的 `connection._external_bounds`, 3419/3478); 收集所有非空子包围体后 `compute_external_bounds` → `around()` (3530-3545), 成功后 `_last_bounds_update = next_update`。around 的几何算法 (`panda\src\mathutil\boundingVolume.cxx:40-75` 跳空体/遇无限体即无限 + 双分派 → `panda\src\mathutil\boundingSphere.cxx:361-446 around_finite`): 先取所有子体积 AABB 的 min/max, 球心=盒心； 若列表里全是盒子半径=到最远角， 若含球则半径=max(到各球心距离+球半径)——一个快速近似包络球。类型选择策略在 `pandaNode.cxx:2263-2309`: 指定 BT_box 用盒； 无变换且孩子全是盒则盒； 否则球， 非恒等变换再 xform。

**触发点**： add_child/remove_child → `force_bounds_stale()` (`pandaNode.cxx:506, 536`), set_attrib/set_state → `mark_bounds_stale()` (918, 949), transform 变化 → force (658, 770 等)， `mark_internal_bounds_stale` = `++_internal_bounds_mark` 再 `mark_bounds_stale` (`pandaNode.I:632-639`)。cull 遍历入口用 `is_in_view → check_cached(true)` 兜底 (`pgraph\cullTraverserData.I:169-192` + `pandaNode.cxx:4139-4186`)。另外 `GraphicsEngine::render_frame` 在 App 阶段**预热**场景根 bounds (`display\graphicsEngine.cxx:770-791`), 注释明说： "if we calculate it in App first before it gets calculated in the Cull thread, it will be more likely to stick for subsequent frames, so we won't have to recompute it each frame."

---

### 3. Geom 合批与共享去重

**GeomVertexData 复用/引用计数设计**： `GeomVertexData : public CopyOnWriteObject` (`panda\src\gobj\geomVertexData.h:68`), 内部数组是写时复制指针 `COWPT(GeomVertexArrayData)` (214), 带全局自增 `UpdateSeq _modified` (315) 做内容版本号。多个 Geom 可共享同一 vdata; 转换结果有 per-vdata 缓存 (`geomVertexData.cxx:675-754 convert_to`: CacheEntry 按 format 键控， 命中 `entry->refresh()` 续命， 未命中才重建并 `entry->record()`)。CPU 动画结果也有 `_animated_vertices + _animated_vertices_modified` 缓存， `modified` 序号没变直接返回 (`geomVertexData.cxx:956-960`)。

**多 NodePath 共享同一 Geom 时的 draw 提交去重**——Panda 不在 draw 列表层去重 (每个可见实例仍各产生一个 CullableObject), 去重发生在三层：
1. **GPU 缓冲层**： `Geom::prepare_now` 按 `(geom, PreparedGraphicsObjects)` 记账， 每 Geom 每上下文只建一次 GeomContext (`panda\src\gobj\geom.cxx:1274-1288`, `_contexts` map), 内容未变 (`get_modified()` 序号相同) 就不重传； GL 侧 display list 复用显式判版本 (`glstuff\glGraphicsStateGuardian_src.cxx:5050-5068`):
```cpp
UpdateSeq modified = max(geom_reader->get_modified(), _data_reader->get_modified());
if (ggc->get_display_list(_geom_display_list, nullptr, modified)) {
  // If it hasn't been modified, just play the display list again.
  glCallList(_geom_display_list); ...
}
```
2. **状态层**： RenderState/TransformState 全局 intern——等价对象共享同一指针， 注释原文 `renderState.cxx:130-135` "all equivalent RenderState objects are guaranteed to share the same pointer; thus, a pointer comparison is always sufficient"; intern 入口 `transformState.cxx:1461-1507 return_unique` (hash 表查等价项)， compose 结果缓存在对象内的双向组合缓存 (`transformState.cxx:550-640`)。这让第 1 节的四键排序退化成纯指针比较。
3. **排序层**： state_sorted 桶把同 state+format+vdata 的对象排一起， 驱动侧 program/VAO/VBO 天然免重绑 (这是 `_munged_data` 指针键的目的， cullBinStateSorted.I:58-60)。

**RigidBodyCombiner collect() 时机 (docstring 原文)**， `panda\src\grutil\rigidBodyCombiner.cxx:67-83`:
```cpp
/**
 * ... Nodes that have transforms on them at the time of collect(), or any
 * ModelNodes with the preserve_transform flag, will be identified as "moving"
 * nodes, and their transforms will be monitored as they change in future
 * frames and each new transform directly applied to the vertices.
 *
 * This call must be made after adding any nodes to or removing any nodes from
 * the subgraph rooted at this node.  It should not be made too often, as it
 * is a relatively expensive call.  If you need to hide children of this node,
 * consider scaling them to zero (or very near zero), or moving them behind
 * the camera, instead. */
```
头文件补充 (`rigidBodyCombiner.h:36-40`): "You should call collect() only at startup or if you change the set of children; it is a relatively expensive call. **Once you call collect(), you may change the transforms on the child nodes freely without having to call collect() again.**"

**何时必须重调**： 子节点集合增删 (合并 mesh 的拓扑变了)。**何时免调**： 已识别为 "moving" 的子节点的 transform 任意变化——collect 时给这些节点挂了 NodeVertexTransform 链 (`rigidBodyCombiner.cxx:159-194 r_collect`), 每帧 cull_callback 只 `mark_modified` 这些变换并遍历内部合并场景 (`135-152`), 顶点变换在顶点着色器/blend 表里做。合并本体靠 SceneGraphReducer 三步 (`rigidBodyCombiner.cxx:98-101`): apply_attribs → collect_vertex_data (`pgraph\geomTransformer.cxx:955-1043`: `_already_collected_map` 复用已收 vdata + 按 format 联合求并 + `_max_collect_vertices` 预算超限就开新块) → unify。最终多个源 Geom 的索引全部 offset 指进同一份大 vdata (`geomTransformer.cxx:1420-1427 update_geoms` → `geom.cxx:172-202 offset_vertices`)。同 scene graph 还有硬件实例化路线： InstancedNode 把实例变换合成 InstanceList、逐实例视锥剔除、munge 进 vdata 实例数组 (`pgraph\instancedNode.cxx:203-255` + `pgraph\cullableObject.cxx:178-192, 229-239`), 与 Loom 现有 A2 桶同思路。

---

### 4. CullTraverser 剔除流程

**调用链** (单线程模型)：
```
ShowBase task 'igLoop' sort=50 (direct\src\showbase\ShowBase.py:2343-2368)
 → graphicsEngine.renderFrame() (ShowBase.py:2264)
 → GraphicsEngine::render_frame (display\graphicsEngine.cxx:713)          [App 阶段: 预热 bounds 770-791]
 → cull_to_bins (graphicsEngine.cxx:1474-1609)
    → setup_scene (1909-2037): 组 SceneSetup; view_frustum_cull 时
      lens.make_bounds() 生成 8 角 BoundingHexahedron (gobj\lens.cxx:641-676),
      xform 到 cull_center 空间 → set_view_frustum (2013-2034)
    → dr->do_cull → GraphicsEngine::do_cull (1261-1272)
       → CullTraverser::set_scene (pgraph\cullTraverser.cxx:88-110: 取 frustum/initial_state/camera_mask)
       → traverse(root) (cullTraverser.cxx:115-172)
          data.is_in_view (pgraph\cullTraverserData.I:169-192): check_cached + frustum->contains(node_gbv)
          → do_traverse (cullTraverser.cxx:178-241)
             fancy_bits 快速通道 (无特效节点零开销直落) → apply_transform_and_state
             (cullTraverserData.cxx:31-91; apply_transform 96-138 用逆矩阵把视锥
              变换到子节点局部空间, 奇异变换则放弃该子树剔除)
             renderable 节点 → GeomNode::add_for_draw (pgraph\geomNode.cxx:515-593)
             → traverse_down 每个孩子 (pgraph\cullTraverser.I:280-309)
    → finish_cull (graphicsEngine.cxx:1633-1634)  [各桶排序]
 → draw_bins (graphicsEngine.cxx:1642-1710) → do_draw (2042-2110)
    → cull_result->draw (pgraph\cullResult.cxx:287-305, 按 bin sort 值顺序画各桶)
```

**视锥剔除在哪个环节**： 三级。 (1) 节点级： `traverse_down` → `is_child_in_view(child)` 用**父子边缓存的外部包围体**直接测 (`cullTraverserData.I:226-242`, 无需再 check_cached, 因为父节点已刷新)， `IF_no_intersection` 直接剪枝； (2) **全包含传播**： 若结果带 `IF_all` 位或节点是 final, 传给孩子的 `_view_frustum` 置 nullptr——整棵子树不再做视锥测试 (`cullTraverser.I:296-299`); (3) Geom 级： 单 Geom 的 GeomNode 免测 (复用节点级结果， `geomNode.cxx:533-545`), 多 Geom 才逐 Geom `geom->is_in_view` (570-575)。contains 判定实现在 `mathutil\boundingHexahedron.cxx:279-306` (球心到 6 平面距离 vs 半径， 跨越平面清 IF_all)。

**与状态排序桶的交接点**： `GeomNode::add_for_draw` → `trav->get_cull_handler()->record_object(...)` (`geomNode.cxx:543`) → `BinCullHandler::record_object` (`panda\src\cull\binCullHandler.cxx:22-24`, 一行转发) → `CullResult::add_object` (`cullResult.cxx:107-258`: 透明状态修正 / M_dual 拆成 opaque+transparent 两份 / munge_geom / `_state->get_bin_index()` 选桶) → `bin->add_object`。即**遍历器只管剔除+累积状态， 投桶是 CullResult 的职责**， 两者通过 CullHandler 抽象解耦。

**每帧重建 vs 跨帧缓存** (决定 Loom 缓存粒度的关键答案)：
- **每帧全量重建**： CullResult 及所有桶的内容。证据： `CullResult::make_next` (`cullResult.cxx:83-101`) 会试图把旧桶带回下一帧， 但五个具体桶类**全部没有重写** `make_next`, 基类返回 nullptr (`pgraph\cullBin.cxx:42-45`), 于是 `new_result->_bins.push_back(nullptr)` ——跨帧携带机制目前是空挂的钩子 (头注释 `cullResult.h:40-42` 仍写着 "keep the results of last frame's cull traversal around", 实现已放弃该优化)。原因： 桶内容依赖相机 (距离排序) 与当帧可见集合， 脏判定成本高于重建。
- **跨帧缓存** (这才是 Panda 让每帧重建“便宜”的本钱)： ① 包围体缓存 + UpdateSeq 失效链 (第 2 节)； ② 父子边 DownConnection 缓存 (含 bounds); ③ intern 后的 RenderState/TransformState 指针与组合缓存； ④ GeomContext/dGPU 缓冲与 display list (按 modified 序号)。

**结论**： “剔除结果列表”的正确缓存粒度是**输入侧缓存** (bounds、状态指针、GPU 资源按内容版本缓存)， 而**输出侧** (可见对象列表、桶内排序) 每帧重建但被输入侧缓存降到极廉。Loom 不应跨帧缓存“可见对象数组”， 应跨帧缓存“每个节点的世界包围体 + 每个桶的排序键元组”。

---

## 第二部分： 可移植技术清单 (按节展开)

### 技术 A: UpdateSeq 惰性包围体失效协议 (最高优先)

**原理**： 见第 2 节。核心是“三序号 + 传播守卫”： `_next_update` (每次弄脏 ++), `_last_update`/`_last_bounds_update` (最近一次重建时抄下的 next 值)， 不等即脏； 标记传播在第一个已脏祖先处截止。

**Loom 落点**： 现状 aabbs 10.9ms/帧全量重算、编辑器态 (无物动) 也全量重算。在 Loom 的节点/Model 类上加： `_next_update` 计数器、`_external_bounds` 缓存、`_last_bounds_update`、每条父子边缓存 child bounds。`set_transform` 时调 `mark_bounds_stale()` (先查自身是否已脏， 未脏才 ++ 并向上走)。帧内视锥剔除/阴影 prep/AABB 汇总统一走 `get_bounds()`: 序号相等直接用缓存。

**预期收益**： 500 球静止时 aabbs 10.9ms → ~0 (只有相机无关的纯读)； N 个物体移动时只重算 N 个球包围体 + 各自祖先链的 around, 而不是 500 次全量。对 shadow_prep 里的 AABB 段 (~22ms 中的包围体部分) 同样生效。

**成本与风险**： 纯 Python 实现， 无需 numba; 风险点是失效钩子必须覆盖所有写路径 (transform/state/父子增删/网格替换)， 漏一条就出“幽灵包围体”； 建议给 `mark_bounds_stale` 保留一个每帧断言模式 (调试期抽验缓存==全量重算结果)。Panda 用乐观并发重试环， Loom 单线程可删掉 while(true) 重试只留判等。

**最小草稿**：
```python
class LoomNode:
    def __init__(self):
        self._next_update = 0          # 弄脏计数
        self._last_bounds_update = -1  # 缓存对应的 next 值
        self._external_bounds = None   # (center, radius) 或 AABB
        self._parents = []

    def mark_bounds_stale(self):
        if self._last_bounds_update != self._next_update:
            return                      # 已脏, 祖先必然也脏 → 停, O(1) 守卫
        self._next_update += 1
        for p in self._parents:
            p.mark_bounds_stale()       # 父节点走同样的守卫

    def get_bounds(self):
        if self._last_bounds_update != self._next_update:
            vols = [self._internal_bounds()] + \
                   [c.get_bounds() for c in self.children if c.get_bounds()]
            self._external_bounds = around_sphere(vols)   # 盒心+最大角/球心+r
            self._last_bounds_update = self._next_update
        return self._external_bounds
```

### 技术 B: 父子边 (DownConnection) 缓存

**原理**： `pandaNode.h:474-479` 把孩子的外部包围体等聚合值缓存在**父节点的孩子表项**上， update_cached 刷新 (`pandaNode.cxx:3419/3478`); cull 时 `is_child_in_view` 直接读边缓存， 免去 check_cached (`cullTraverserData.I:226-242`)。

**Loom 落点**： Loom 的视锥剔除 (组 4 待拍板项) 与 shadow_prep 遍历孩子表时， 直接读边缓存 AABB 进视锥测试； 配合 A, 每帧剔除的输入零重算。

**预期收益**： 剔除阶段从“每帧 per-object 矩阵×包围体重算”变为“查表 + 纯数学测试”； 与组 4 视锥剔除天然配套。

**成本与风险**： 低； 注意父子增删时要同步失效父的边缓存 (force_bounds_stale 已覆盖)。

### 技术 C: 双桶结构 opaque(state_sorted) / transparent(back_to_front) + 四键排序

**原理**： 见第 1 节。四键 = 状态(最重的排最前) → 顶点格式 → 顶点缓冲 → transform, 全指针比较； 桶排序在 cull 结束后一次性做； 透明桶按包围体中心距离降序且 add 时即算距离。

**Loom 落点**： Loom 的 A2 实例化桶已是按 mesh 分桶， 补齐两点： (1) opaque 桶内排序键改为 `(program_id, vao_or_bucket_id, mesh_id)` 的 Python 元组 (Loom 状态种类少， 一个静态键即可， 不必做全套 RenderState intern); (2) 若场景有半透明物体， 单独 transparent 桶按 `-dist` 排序， 距离用缓存包围体中心算。每帧 `list.sort()` (Timsort, C 实现) 对 500 元素是微秒级。

**预期收益**： GL 状态切换/VAO 重绑减少 (500 球同 mesh 桶本就集中， 收益主要在混合材质场景与阴影 pass 的 program 切换)； 透明排序修正混合错误。

**成本与风险**： 低。风险仅在于键设计要与 Loom 实际 draw 提交路径的“重绑成本排序”一致 (program > VAO > uniform buffer > uniform)。

### 技术 D: 状态/变换 intern (指针即等价)

**原理**： `transformState.cxx:1461-1507 return_unique` + `renderState.cxx:130-135`——等价对象 intern 成同一指针， 排序/去重退化为 `is` 比较； compose 结果缓存在对象内 (`transformState.cxx:550-640`)。

**Loom 落点**： Loom 编辑器场景大量物体共享同一材质/同一 mesh; 可做一个轻量 intern 表 (dict by 元组)， 让同类物体共享同一 state 元组对象， 桶排序键与脏检查都用 `is`。变换矩阵的 compose (父×子) 也按 `(id(a), id(b))` 缓存。

**预期收益**： 服务于 C 的排序键 O(1) 比较； world 矩阵链在物体静止时命中缓存 (Loom 已有 _frame_world 复用经验， 此处是同思想的更细粒度版)。

**成本与风险**： 中低。风险： intern 表的生命周期管理 (Python 侧用 `weakref` 或接受少量泄漏)， 以及浮点 compose 缓存键的精度语义要钉死。

### 技术 E: RigidBodyCombiner 语义的静态合并 (collect 时机契约)

**原理**： 见第 3 节。合并多个静态 (或刚体) 节点为一个 Geom; **只有子节点集合变化才重调 collect**, 之后 transform 随便动都不用重调。

**Loom 落点**： 对“500 球”这类扩展压测场景， 在 A2 实例化之外提供第二条路： 同材质静态物体合并成大 VBO (Loom 已有堆叠缓冲复用经验)。暴露 `collect()` 等价 API, 文档写明 Panda 的契约： 增删成员→重调； 只动 transform→免调。

**预期收益**： draw call 从 N 降到 1, 顶点提交一次； 编辑器静态装饰物收益最大。与 A/B 正交。

**成本与风险**： 中。风险： 编辑器里物体被选中/单独立编辑时需要回退到独立绘制 (Panda 的答案： 合并节点下不再逐个剔除， 用外层 RigidBodyCombiner 自身包围体， `rigidBodyCombiner.cxx:38-43` 设 OmniBoundingVolume+final); Loom 需要设计“合并组 vs 单物体”的切换机制。

### 技术 F: 视锥全包含传播 (IF_all → 子树免测) 与 final 标志

**原理**： `cullTraverser.I:296-299`: contains 结果含 IF_all (子树整体在视锥内) 时， 向下传 nullptr frustum 停止剔除； `set_final` (`pandaNode.I:563-568`) 让节点显式声明“别再往下测了”。

**Loom 落点**： 组 4 视锥剔除实现里， frustum-contains-AABB 用 Panda 的三值返回 (外/交/全含)， 全含时子树直接整树入桶， 不再逐层测试。

**预期收益**： 相机贴近物体群时剔除成本骤降； 实现简单， 纯控制流。

**成本与风险**： 低； 只需 contains 返回三态而非布尔。

### 技术 G: 阴影 pass 的剔除与跳过策略 (针对 shadow_prep ~22ms)

**原理**： Panda 把阴影相机 pass 与主 pass 统一走 cull_to_bins, 但**延后处理且先判“该光锥是否在主相机视野内/场景是否需要”** (`graphicsEngine.cxx:1522-1541` 收集非阴影 pass 的视锥并集 `non_shadow_bounds`, `1578-1598`: `frustum == nullptr || non_shadow_bounds[...].contains(frustum)` 不满足则整个 shadow pass 跳过， 连 cull 都不做)。且用 `CullResult::make_next` + 相同相机去重 (`AlreadyCulled`, 1543-1566)。

**Loom 落点**： shadow_prep 的非 AABB 段： 先判 (a) 该光源视锥是否与主视锥相交/在场景包围体内， (b) 光源参数+场景静态内容是否自上次渲染后未变 (用 A 的序号做版本)， 都满足则复用上帧阴影 draw 列表甚至整张 shadow map。

**预期收益**： 直接命中 shadow_prep ~22ms 的裁剪段； 静态光+静态场景时阴影 pass 降为 O(1)。

**成本与风险**： 中。风险： 光源在视野外但影子仍可见的边缘情况——Panda 的判据是光锥 vs 主视锥并集相交才画 (即光能照到可见区域才画)， 移植时保持同一判据即可； 动态物体进入场景需正确使版本号失效。

---

## 第三部分： 移植优先级排序 (结论)

| 优先级 | 技术 | 命中瓶颈 | 依据 |
|---|---|---|---|
| P0 | A. UpdateSeq 惰性包围体失效 | aabbs 10.9ms 全量重算 (含编辑器态) + shadow_prep 包围体段 | 第 2 节完整协议可直接抄； 纯 Python 零依赖； “改了才算”从机制上消灭全量重算 |
| P1 | B. 父子边包围体缓存 | 剔除/阴影 prep 遍历输入 | 与 A 同一次重构落地 (update_cached 里顺手写边缓存)； 组 4 视锥剔除的前置 |
| P2 | G. 阴影 pass 跳过/复用 | shadow_prep ~22ms | Panda 有现成判据可抄 (graphicsEngine.cxx:1522-1608); 依赖 A 的序号做版本 |
| P3 | C. opaque/transparent 双桶 + 四键排序 | draw 提交效率、透明正确性 | 键设计简明 (program/vao/vdata/transform), 每帧一次 Timsort; 与 A2 桶融合成本低 |
| P4 | F. IF_all 全包含传播 + final | 剔除常数因子 | 十几行控制流， 跟组 4 一起做 |
| P5 | D. 状态/变换 intern | C 的排序键与矩阵复用 | 收益依赖场景重复度； 可后补 |
| P6 | E. 静态合并 (collect 契约) | draw call 数 | 对 500 球压测与 A2 实例化二选一/互补； 涉及编辑器交互设计， 放最后 |

总原则 (Panda 的架构答案， 直接回答任务书第 4 问的推论)： **每帧重建“输出” (可见列表/桶排序)， 跨帧缓存“输入” (包围体、状态指针、GPU 资源)， 用 UpdateSeq 序号对让“重建”退化成 O(脏量)**。Loom 当前缺的正是这个分层——不是把剔除结果列表缓存起来， 而是让重建它的每一步都先问一句“序号变了吗”。