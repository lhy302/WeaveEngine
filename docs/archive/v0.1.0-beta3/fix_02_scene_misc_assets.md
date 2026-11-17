# 修复批次 02 — 场景/杂项/资产 (scan_02_scene + scan_12_misc + scan_10_assets)

- 批次: fix_02_scene_misc_assets
- 改动业务文件: `sceneio.py`, `undo.py`, `filedialog.py`, `frame_buffer.py`,
  `loom_net.py`, `guiloader.py`, `loom_texture.py`, `loom_cubemap.py`
  （严格限定在允许清单内；未改 `editor.py` / `ui/loom_gui.py` / `loom_transform.py`）
- 新增测试: `tests/test_scene_cycle_reject.py`, `tests/test_scene_material_no_growth.py`,
  `tests/test_scene_solid_env_roundtrip.py`, `tests/test_undo_full_coverage.py`,
  `tests/test_texture_ctx_release.py`, 另加 `tests/test_frame_buffer_offscreen.py`,
  `tests/test_net_cancel_charset.py`, `tests/test_guiloader_marker.py`
- 未执行任何 `git add/commit`

## 验收

- `python tests/_tmp/ab_batch.py`：22/22 PASS，全部 MAE ≤ 0.0002；
  与改前逐场景数值相同（最大 MAE 仍为 0.000082，`ab_ui_scene`）。
- `python tests/run_all.py`：exit=0（全部测试完成）。
- 新增 8 个测试全部 PASS；原有 `test_sceneio.py` / `test_undo.py` /
  `test_frame_buffer.py` / `test_filedialog_helpers.py` / `test_guiswitch.py` /
  `test_texture.py` / `test_cubemap.py` 全部 exit=0。

### 改前/改后实测对照（从 `git HEAD` 加载旧模块，与当前模块同进程对照）

```
1 cycle: OLD load=loaded 2 save=objects=0 | NEW load=raise SceneCycleError save=raise SceneCycleError
2 material growth: OLD [6, 9, 12, 15, 18] | NEW [3, 3, 3, 3, 3]
3 solid env: OLD (None, None) | NEW ([51, 102, 153, 255], (51, 102, 153, 255))
4 undo keys (normal/prefab/mat/lod/range): OLD (False, False, False, False, False) | NEW (True, True, True, True, True)
5 shape undo: OLD ('circle', [], 5.0, False) | NEW ('line', [(0, 0)], 0.0, True)
6 SHBrowseForFolderW.restype: OLD <class 'ctypes.c_long'> | NEW <class 'ctypes.c_void_p'>
7 framebuffer (depth?, redirects?): OLD (False, False) | NEW (True, True)
8 net cancel/charset: OLD ({'ok': True, 'status': 200}, '<utf8 decode error>') | NEW ({'ok': False, 'error': '已取消'}, '中文')
9 texture switch (old released?, same tex?): OLD (False, False) | NEW (True, False)
10 guiloader BOM/tab: OLD (None, None) | NEW ('#gui:loom', '#gui:loom')
```

---

## 1. [P1] 父链成环：加载/保存都拒绝，不再静默丢对象

**位置**: `sceneio.py::_link_by_map` / `sceneio.py::scene_to_dict` 原 DFS

**根因**: 坏文件里 A.parent=B、B.parent=A 时 `_link_by_map` 直接建出环；
保存只从 `parent is None` 的根 DFS，成环对象全部无根 → 旧行为
`scene_from_dict` 返回 2 个模型，`scene_to_dict` 却输出 `objects=0`（整棵静默丢失）。

**改法**:
- 新增 `SceneCycleError(ValueError)`；
- 新增 `_validate_object_graph(objects)`：按 parent_id 走链，发现回边即抛；
  `scene_from_dict` 在清空/重建引擎状态**之前**校验；`instantiate_prefab` 同样校验；
- 新增 `_validate_model_graph(models)`：保存前检测运行时父链成环 + 从根不可达；
  `scene_to_dict` 先校验再 DFS；
- `_emit_subtree` 加共享 `seen` 集合，Prefab 子树成环也不会无限递归。

**测试**: `tests/test_scene_cycle_reject.py`（加载成环/自环/保存成环/Prefab 成环
全部拒绝；正常父链不误伤；拒绝加载时引擎旧状态不被破坏）。

## 2. [P1] 材质孤儿膨胀：仅加载时丢弃无引用默认材质（D2=A）

**位置**: `sceneio.py::scene_from_dict` 物体创建后

**根因**: 每个 `add_model` 都会先自建材质并登记进 `engine.materials`，随后
`_apply_object` 换成文件里的材质；旧实现把这份自建材质留在库里，保存时随
`engine.materials` 落盘 → 每次 load→save 线性增长。

**改法**: 记录加载前文件显式登记的材质 `keep_ids`，全部物体建链后：
- 本次加载新建且无引用 → 丢弃；
- 文件里显式登记但无引用的“默认形态”材质（无颜色/贴图/PBR、名为“材质”）→ 丢弃并告警；
- 文件里显式登记的非默认材质（有颜色/贴图/PBR/自定义名）即使暂未引用也保留。
保存端不改（`scene_to_dict` 仍原样输出 `engine.materials`）。

**验收**: 连续 5 次 load→save 材质数 `[3,3,3,3,3]`（改前 `[6,9,12,15,18]`）；
显式彩色未引用材质保留；库外 `material_id` 只补建一次。
**测试**: `tests/test_scene_material_no_growth.py`。

## 3. [P1] 纯色 env 保存即丢

**位置**: `sceneio.py::_emit_material` / `_apply_materials`

**根因**: `_emit_material` 只写 `env.paths`；`Cubemap.from_solid` 的 `paths=None`，
所以纯色 env 写出 `paths: None`，加载时被忽略。

**改法**: 有 paths 写 paths；否则写 `solid_color`；加载时
`Cubemap.from_solid(tuple(solid_color), name, guid)` 重建。场景/相机天空盒
原有的 `solid_color` 路径保持并已回归验证。

**测试**: `tests/test_scene_solid_env_roundtrip.py`（材质 env + 场景 skybox
save→load→save 均保留颜色）。

## 4. [P1] 撤销覆盖不全（Q5=A）

**位置**: `undo.py::snapshot/apply_snapshot/light_snapshot/apply_light_snapshot`

**改法**:
- `snapshot(m)` 增加 `normal_mode`、`prefab_ref`、`material_state`
  （color/saturation/metallic/roughness/pbr/albedo/normal_map/env_map）、
  `lod_levels/lod_screen_levels/lod_bias`；
- `apply_snapshot` 回写上述字段，并清 `_lod_cur/_lod_radius` 强制重评 LOD；
- `light_snapshot` 增加 `range`，`apply_light_snapshot` 兼容旧快照
  （无 range 键则跳过）。
- 只改 `undo.py`；`editor.py` 通过 `snapshot as undo_snapshot` 复用，无需改动。

**测试**: `tests/test_undo_full_coverage.py`（全字段 before→after→undo→redo；
光源 range；旧快照兼容）。

## 5. [REGRESSION] ui_set 可达的 Shape 缺撤销分支

**位置**: `undo.py::ui_elem_snapshot/ui_apply_snapshot`

**改法**: 补 `ctype == 'shape'` 分支，覆盖 `shape_type/points/radius/
stroke_color/stroke_width/fill_color/segments/close`。
**测试**: 同上文件；改前 apply 后仍为 `circle/[]/5.0`，改后恢复
`line/[(0,0)]/0.0`。

## 6. [P1] `SHBrowseForFolderW` 未设 restype（64 位不安全）

**位置**: `filedialog.py::_choose_directory_classic`

**改法**: 模块级声明 `SHBrowseForFolderW.restype = c_void_p`、
`SHGetPathFromIDListW.restype = BOOL` 及参数类型；调用处补
`POINTER(BROWSEINFO)` 与 `CoTaskMemFree.argtypes = [c_void_p]`；
`SHBrowseForFolderW` / `SHGetPathFromIDListW` / 回退路径均 try/except，
失败返回 None 不崩；PIDL 用 `CoTaskMemFree` 释放。
**测试**: `tests/test_filedialog_helpers.py` 通过；对照 restype 由
`c_long` → `c_void_p`。

## 7. [P1] FPS 缓冲黑帧（Q8=A）：预画真正写入离屏 FBO + 深度附件

**位置**: `frame_buffer.py::RenderFrameBuffer.ensure_canvas/begin/commit/abort/_release`

**根因**: `begin` 只 `fbo.use()`，但 `e.render` 内部经
`engine._screen_fb()` 绑定 widget FBO，预画实际画到屏幕；离屏 FBO 空白，
下一拍 blit 空白 → 黑帧。旧 FBO 也只有颜色附件，无深度测试。

**改法**（未改 `ui/loom_gui.py` / `editor.py`）:
- `ensure_canvas` 增加 depth renderbuffer（失败回退 depth texture，再失败不崩）；
- `begin` 通过 `GLEngine._LIVE_INSTANCES` 找到持有本缓冲的引擎，渲染期间临时
  把 `engine._external_ctx=True`、`engine._external_fb=self._fbo`，并设置
  viewport / 清颜色+深度；`commit/abort/_release` 恢复原 widget FBO。
- `begin(ctx,w,h,engine=None)` 新增可选 engine 参数，便于测试/未来调用方显式传入。
**测试**: `tests/test_frame_buffer_offscreen.py`（深度附件存在、预画期间引擎目标
指向离屏 FBO、commit/abort 恢复、blit 拷贝、release 释放颜色+深度）。

## 8. [REGRESSION] net cancel 后覆写 + 解码 charset（均裁决 A）

**位置**: `loom_net.py::HttpRequestAsync` / `http_request`

**改法**:
- 增加 `_cancelled` + `_lock`；`cancel` 是终态，`_run` 完成时若已取消直接丢弃
  结果，不再覆写；`is_cancelled()` 暴露状态。
- 新增 `_header_charset/_decode_body`：按 Content-Type charset 解码（大小写不敏感、
  支持引号），缺省 UTF-8，非法 charset/解码失败回退 UTF-8→latin-1；
  成功响应与 HTTPError body 都走同一函数。
**测试**: `tests/test_net_cancel_charset.py`（取消后晚到结果被丢弃、GBK 正确解码、
非法 charset 回退）。

## 9. [P2] 纹理换 ctx 不 release + `id(ctx)` 复用误判

**位置**: `loom_texture.py::Texture.ensure_gl` / `loom_cubemap.py::Cubemap.ensure_gl`

**改法**: 换 ctx 时先 `release()` 旧 GPU 纹理再重建；ctx 归属改用
`weakref.ref(ctx)` 比较（不可弱引用对象回退 `id`），`release()` 同时清弱引用。
**测试**: `tests/test_texture_ctx_release.py`（换 ctx 释放旧纹理、同 ctx 复用、
ctx 回收后弱引用失效、cubemap 同规则）。

## 10. [P3] guiloader BOM/tab 标识失效

**位置**: `guiloader.py::_parse_header`

**改法**: 先 `lstrip('\ufeff')` 去 BOM；按 `# key: value` 解析，key 内允许
空格/tab（`#\tgui:\tloom` 可识别）；marker 取 value 的第一个空白 token 并
归一化为 `#gui:loom`；name/desc 保留原大小写。
**测试**: `tests/test_guiloader_marker.py`（BOM、tab、错程序标识、官方项）。

---

## 遗留 / 新发现（未在本次范围内改）

1. **`editor.py::_load_scene` 先清空再调 `scene_from_dict`**：成环文件现在会被
   `scene_from_dict` 拒绝，但编辑器已先清掉当前场景。若要求“拒绝加载时保留旧场景”，
   最小改动点是 `_load_scene` 在清空前调用 `sceneio._validate_object_graph(data['objects'])`
   （或公开的 `validate_scene_data`），捕获 `SceneCycleError` 后直接返回。按约束未改
   `editor.py`，留给下一批。
2. **`scene_driver.py` 的 env_map 仍只处理 `paths`**（未处理 `solid_color`）：
   GL/编辑器侧已往返，但 VK/Player 驱动加载纯色 env 仍会得到 None。不在允许文件清单。
3. **FPS 缓冲引擎发现依赖 `GLEngine._LIVE_INSTANCES`**：当前引擎构造已注册；
   若未来有引擎实现绕过该注册，`begin` 将找不到 engine，需显式传 `engine=`。
4. `loom_net.cancel` 仍不能中断已发出的网络请求（只丢弃结果），与裁决 A 一致。
5. 加载期材质清理会打印一条告警（每个场景最多一条），便于观察孤儿，不影响功能。
