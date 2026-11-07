# VK 渲染器缺陷修复报告 (批次: vk_renderer / vk_ui)

日期: 2026-11-07
来源: docs/audit/scan_04_vk_render.md + scan_05_player.md (本工作区未见这两个文档文件, 按派单
条目原文执行; 派单给的改前行号与工作区实际行号逐条核对一致)
改动文件: vk_renderer.py, vk_ui.py (只这两个; 另新增 2 个测试文件, 未 git add/commit)

| # | 缺陷 | 级别 | 状态 | 改后位置 |
|---|------|------|------|----------|
| 1 | 桶实例偏移 (同桶被隔开时画错/漏画) | P1 回归 | 已修 (裁决 A) | vk_renderer.py:434, 1762, 1791/1833/1876 |
| 2 | PBR 开关属性名错 (pbr_enabled vs _pbr_enabled) | P2 回归 | 已修 | vk_renderer.py:671-687, 1606 |
| 3 | 法线贴图上传失败回落白纹理 | P2 | 已修 | vk_renderer.py:1293-1330 |
| 4 | env 缓存 id(cube) + 不持引用 + 无淘汰 | P2 | 已修 | vk_renderer.py:1408-1450 |
| 5 | 文本 LRU 淘汰不 release、_groups 无界 | P2 | 已修 | vk_ui.py:469-490, 537-570 |
| 6 | 贴图 wrap/filter_mode 被忽略 | P2 | 已修 | vk_renderer.py:465-500, 1352-1385, 1753 |
| 7 | 多平行光阴影只用 1 张贴图 | P2 | 按裁决 A 接受为已知限制 + 警告 | vk_renderer.py:1-30, 1548-1590 |
| 8 | 死代码 + 208B/132B/160B 注释不一致 | P3 | 已修 | vk_renderer.py:8/90/637/724/1689, 1327 |
| 9 | Shape 描边 width<=1 line-list 实验 | P3 | 实验后回退 (无改善, 数值不变) | vk_ui.py:45-65, 241-254 (仅契约注释) |

---

## 1. [P1 回归] 桶实例偏移

**位置** (改前): vk_renderer.py:1592 / 1633 (两个阴影 pass) / 1672 (主 pass), 桶构建在 1554-1572。

**根因**: 实例行是按 vis **原序**写进单块实例缓冲的 (inst[i, ...] = ..., i = vis 下标),
但 draw 只能画**连续**区间, 而 first_instance 直接取了 idxs[0]:

    rp.draw(nv, len(idxs), 0, idxs[0])      # idxs = 该桶的 vis 下标列表

桶键含 albedo/法线/env guid, 所以"同网格不同贴图"本来就分桶 —— 一旦同桶的两个物体被别的桶
隔开 (vis = [cube(贴图A), cube(贴图B), sphere, cube(贴图A)], 桶 A 的行 = [0, 3]),
idxs[0]=0 + len(idxs)=2 会画第 0、1 行: 第 3 行 (第二个 A) **漏画**, 第 1 行 (B 的矩阵)
被套上 A 的几何/贴图 → 串形。旧 HEAD (627 行版本) 同样写法 (HEAD:640/665), 属历史遗留。

**改法** (裁决 A: 单缓冲 + 按桶重排):
- 新增模块级 bucket_layout(groups) (vk_renderer.py:434): 返回 order (重排后缓冲第 r 行来自
  vis[order[r]])、starts (每桶在重排缓冲中的起始行)、identity (order 恰为 0..N-1 时可零拷贝)。
- draw_frame (1762-1770): 桶建好后调 bucket_layout, 按 order 把实例行 gather 成连续区间再上传;
  identity 为真时直接用原 staging 视图 (绝大多数场景零额外拷贝)。
- 三处 draw 的 first_instance 从 idxs[0] 改为 _bstart[k] (1791 平行光阴影 / 1833 点光 6 面 /
  1876 主 pass); 点光 pass 的 stage 与平行光恢复段同样按 order 重排 (1813/1841)。
- 桶序不变 (仍按 dict 插入序 = 首次出现序), 所以 draw 次序与旧实现一致, 只有实例行位置变。

**前后证据** (新增探针 tests/_tmp/probe_bucket_reorder.py, 场景 = 同网格 3 连体 + 不同贴图 +
中间插入球):
- 桶构成实测: 桶0 网格 cube 实例行 [0, 3] (非连续, 正是触发形态), 桶1 [1], 桶2 [2]。
- GL vs VK **修复前 (HEAD 语义)**: MAE=0.003197, MAX=0.8588, NCC=0.8469, 明显不同像素 2093
- GL vs VK **修复后**:            MAE=0.000001, MAX=0.0039, NCC=1.0000, 明显不同像素 0
- 并排图 tests/_tmp/probe_bucket_reorder_side.png (GL | 修复前 | 修复后): 修复前画面只有 3 个
  物体 —— 蓝条纹 cube 被画成红白棋盘 (串形), 最右红白 cube 整块消失; 修复后与 GL 一致。
- 既有 22 场景 A/B 全部与改前**逐值相同** (见"验收数字"), 说明连续场景走 identity 短路无副作用。

**新增测试**: tests/test_vk_bucket_order.py (纯 CPU, 进 run_all): 交错/连续/空场景的 order、
starts、identity; 按 starts 切片的行集合与桶成员集合一致; 旧语义 (idxs[0] 连画) 确实串行的
对照断言; 13 行 4 桶的覆盖/不重叠性质。

---

## 2. [P2 回归] PBR 开关属性名错

**位置** (改前): vk_renderer.py:1425

**根因**: buf[_R_MISC] = 1.0 if getattr(self, 'pbr_enabled', True) else 0.0 —— 读的是
self.pbr_enabled, 但渲染器上从来没有这个属性, 真实开关是 engine._pbr_enabled
(GL 侧 loom_render.py:606 读的就是 _pbr_enabled)。于是永远落到 getattr 的缺省 True,
pbr_enabled=false (B7b 排错后门) 在 VK 后端等于没设。

**改法**: __init__ 增加 pbr_enabled=None 构造参数 (缺省继承语义), 新增 pbr_enabled
property + setter (671-687): 读写统一落到 _pbr_enabled, 缺省回退 True —— 与 GL 的
getattr(self, '_pbr_enabled', True) 完全同义; _pack_scene 改为 self.pbr_enabled。

**前后证据**: tests/test_vk_bucket_order.py 直接断言 _pack_scene 的 misc.x:
pbr_enabled=False -> misc.x=0.0 (改前恒为 1.0), 缺省 -> 1.0; setter 落到 _pbr_enabled;
构造签名含 pbr_enabled。

---

## 3. [P2] 法线贴图失败回落白纹理

**位置** (改前): vk_renderer.py:1198 / 1201 (取视图) + 1229 (except 分支 v = self._white_view)

**根因**: _upload_tex 对 albedo 与法线贴图共用同一条"失败回落白纹理"路径。法线贴图上传失败后
采样到 (255,255,255) → 解码 rgb*2-1 = (1,1,1) → 物体法线被整体搅乱, 比"没有法线贴图"更错。

**改法**: _upload_tex(tex, fallback=None) (1313) 接受回落视图; _tex_view 对法线贴图传
fallback=self._flat_nrm_view (平直法线 (128,128,255) = 恒等扰动)。缓存键按用途分开
(guid vs (guid, id(fallback))), 避免一路失败污染另一路。

**前后证据**: CPU 断言 —— 非法 _rgba 的贴图: albedo 路径返回 'WHITE', 法线路径返回
'FLAT_NORMAL' (改前两条都返回 'WHITE'); 两条缓存条目互不覆盖。

---

## 4. [P2] env 缓存 id(cube) + 不持引用 + 无淘汰

**位置** (改前): vk_renderer.py:1278-1283 (key = id(cube), 命中直接 return), 1321 (写入)

**根因**: 用 id(cube) 当键却不持有 cube 引用 —— cube 被回收后新对象可能复用同一 id, 直接命中
旧缓存 (环境反射变成别人的贴图); 且字典无上限、淘汰时不 destroy, env cube (6 面 + mip 链)
会持续吃显存。

**改法**: _env_cache 改 OrderedDict (init 处建), 键 = cube.guid (无 guid 才退回 ('id', id)),
缓存值持 cube 与 GPU 纹理引用 (防 id 复用 + 便于 destroy), 命中时 move_to_end;
新增 _evict_env_cache() (1410): 超 _ENV_CACHE_MAX=16 时按 LRU 淘汰, **先摘掉引用该 cube
视图的 bind group / 桶 uniform 缓冲, 再 destroy 纹理**。

**前后证据**: CPU 断言 (上限压到 2, 塞 3 张): 淘汰到 2 条、淘汰的是最久未用、GPU 纹理
destroy 计数 1、_tex_groups/_bkt_bufs 里指向被淘汰 view 的条目被摘掉、未淘汰项未销毁。

---

## 5. [P2] vk_ui 文本 LRU 不 release、_groups 无界

**位置** (改前): vk_ui.py:524-525 (while len(self._text_cache) > _TEXT_CACHE_MAX: popitem),
459 (self._groups = {}), 467-480 (group_for 只增不减)

**根因**: 淘汰只把条目从 LRU 字典里丢掉 —— 既不 destroy() GPU 纹理, 也不清 _groups
(以 id(view) 为键): 每出现一条新文本就漏 1 张纹理 + 1 个 bind group, 长时间跑 UI 必然涨。
_groups 对 Image 元素 (每帧 texture_from_surface) 同样只增不减。

**改法** (vk_ui.py):
- texture_for_text 末尾改调 _evict_text_lru() (537/540): 淘汰时 _release_texture ——
  先 self._groups.pop(id(tex.view)) 摘 group (group 里钉着 view), 再 tex.destroy()。
- clear_cache() 也逐个 release 后再清表 (565)。
- _groups 改 OrderedDict + _GROUPS_MAX=512 上限 LRU (469-490): 超限只丢 group 对象
  (view 仍在调用方手里, 下次用到按同一 view 重建), 不涉及纹理所有权。

**前后证据**: CPU 断言 (_TEXT_CACHE_MAX 压到 2, 塞 4 条): 达上限 2 条、被淘汰 2 条的 destroy
计数各 1、最新两条保留、对应 group 从 4 条降到 2 条; _GROUPS_MAX > _TEXT_CACHE_MAX; _groups
超限可收敛到 512。既有 UI A/B 数字不变 (textures:16, groups:17, cached_text:15)。

---

## 6. [P2] 贴图 wrap / filter_mode 被忽略

**位置** (改前): vk_renderer.py:728 (唯一一个 _tex_sampler: repeat + linear/linear/linear),
_tex_group (1259-1271) 恒绑这一个采样器。

**根因**: Texture.wrap / Texture.filter_mode 是 M36 导入设置, GL 侧在 loom_texture._build 里
映射到 repeat_x/y 与 tex.filter; VK 侧完全没读 —— 设了 clamp 的贴图仍按 repeat 采样
(UV 出界处出鬼影), 像素风贴图被线性插值糊掉。

**改法**: 新增模块级 sampler_desc(tex) (465): 与 GL 同一份语义 —— clamp -> clamp-to-edge,
repeat/mirror -> repeat (GL 无 MIRRORED_REPEAT, 同回落); point -> nearest+nearest,
bilinear -> linear+nearest(mip), trilinear -> linear+linear。新增 _sampler_for(tex) (1352)
按参数键懒建并复用采样器; _tex_group 增加 sampler 参数并进 bind group 键 (1368-1385);
采样器按**桶**取一次 (1753, 桶键已含 albedo guid), 不是每物体每帧建字典。
**默认参数 (无贴图 / 默认导入设置) 复用原 _tex_sampler 实例**, 所以无贴图场景的采样器对象与
像素结果逐位不变。

**前后证据**: CPU 断言 5 条映射 (默认 / clamp+point / bilinear / mirror / 默认键等于旧采样器
参数 ('linear','linear','linear','repeat','repeat')); 22 场景 A/B 数值与改前逐值相同
(默认路径未变)。

---

## 7. [P2] 多平行光阴影只用 1 张贴图 → 按裁决 A 接受为已知限制

**位置** (改前): vk_renderer.py:1545-1548 (inst_sha 只挑第一个 4x4 光 VP), 1575-1594 (只烘
一张 _shadow_view), _pack_light_vps (1388-1401, 点光只收第一盏)。

**根因**: 阴影 pass 用 self._shadow_buf/_shadow_view 单张 1024² 贴图; 主 pass 却把**每盏**
平行光各自的 ortho 写进场景块, 第 2 盏及以后会拿别人的贴图做 PCF (阴影位置错, 不崩)。
修成多张需要每灯一组 bind group, 与本项目"多 bind group 组合触发驱动死锁"的硬约束冲突。

**改法** (裁决 A: 不修, 声明): 模块 docstring 顶部新增"★ 已知限制"段说明 "VK 同时最多 1 盏
平行光 + 1 盏点/聚光投影"; _pack_light_vps 统计超限情况, 命中时调 _warn_shadow_limit (1550)
打印**一次**警告 (类级 _shadow_limit_warned, 不刷屏、不崩)。渲染行为不变 (不改任何像素路径)。

**前后证据**: CPU 断言 —— 2 盏平行光投影: 打印 1 条警告且两盏都拿到 VP; 3 盏再跑不重复打印;
单投影灯不打印; 2 盏点光投影: 打印 1 条警告且 _point_shadow_guid 仍是第一盏 (第二盏无阴影,
即已知限制本身)。22 场景 A/B 全部无警告 (场景里都只有 1 盏投影灯), 数值不变。

---

## 8. [P3] 死代码清理 + 注释字节数不一致

**位置** (改前): vk_renderer.py:1212 (tex.ensure_gl(None) if False else None); 注释 8 (132B)、
90 (208B)、557 (132B)、724 (132B)、1508 (208B)。

**根因**: _upload_tex 里那行三元表达式恒不执行 (且 VK 侧不该有 GL 依赖), 属残留; 实例步长实际
是 _INST_BYTES = 160 (40 f32), 注释里的 132B / 208B 都是历史值, 三处互相矛盾。

**改法**: 删掉死代码 (保留说明注释, 行为不变: _rgba is None 时照旧走异常回落分支); 把
132B/208B 全部改成 160B, 并补一句顶点步长 48B (12 f32)。

**前后证据**: grep 208B|132B 改后为 0 处; 22 场景 A/B 数值不变。

---

## 9. [P3] Shape 描边 line-list 实验 (width<=1) → 实测无改善, 回退

> 2026-11-07 追加实验批次: 只改 vk_ui.py 的描边契约注释, 新增
> tests/test_vk_ui_stroke.py; **未保留任何 line-list 渲染代码**。

**背景/假设**: GL 的 Shape 描边走 GL_LINES + line_width (1px 线走驱动的 diamond-exit
光栅化); VK 侧一直用三角带逐段展开。按派单实验: 用 wgpu 的 line-list 拓扑 (恒 1px)
给 width<=1 的描边单开一条管线 (width>1 仍三角带), 看是否更接近 GL。

**实验实现** (临时, 已回退): VkUIPipeline 增加 line_pipeline (与 UI 管线共享 shader /
bind group layout / 顶点格式 / 混合状态, 仅 primitive.topology='line-list'); op 记录
增加 kind, prepare/submit 按 kind 切管线; draw_screen_lines 对 float(width)<=1.0 发
每段 2 顶点。

**实测 (480x320, 同一 GL 基准, 逐像素 MAE)**:

| 场景 | 三角带 (改前) | width<=1 line-list (实验) | 改后 (回退) |
|------|---------------|---------------------------|-------------|
| tests/_tmp/ui_lines_scene.json | 0.00357361 (858/153600, MAX 0.929412) | 0.00357361 (858, MAX 0.929412) | 0.00357361 (逐值相同) |
| tests/_tmp/ui_lines_alpha_scene.json | 0.00680006 (10044, MAX 0.929412) | 0.00680006 (10044, MAX 0.929412) | 0.00680006 (逐值相同) |
| 自建 1px 角度探针 (0/18/22/45/60/90° + 1 条 w2 对照) | 0.00323824 (1034) | 0.00323824 (1034) | 0.00323824 (逐值相同) |
| GPU 直测 tests/_tmp/probe_linelist_gpu.py | — | 5 角度 (0/30/45/60/90°) line-list vs hw=0.5 三角带: 每角度 0 像素差 | — |

**为什么没用** (残差不在 width<=1):

- 不透明场景 858 个差异像素**全部**落在 width>=2 的描边上: line1 是场景里唯一
  width=1 的描边, 距其路径 2.5px 内的差异像素 = 0; 逐形状 diff: poly3 510 /
  line4 198 / poly1 94 / poly2c 60 / circ 52 / line2 12。WebGPU 线宽恒为 1px,
  line-list 无法覆盖 width=2/4。
- alpha 场景 10044 个差异像素中 9500 个是 poly3 填充 (多边形面积 9500) 的 alpha
  语义差 (GL draw_screen_polygon 走 draw_lines, 期间 BLEND 关闭 -> 忽略 alpha;
  VK 恒 SRC_ALPHA), 占 diff 总量 61.6%; 描边部分约 544 像素。与描边拓扑无关。
- 1px 线本身还有 GL/VK 的 tie-break 差: 水平线 y=20.0 时 GL 画 row 20, VK (三角带
  与 line-list 都是) 画 row 19 —— 换拓扑不修, 属两套光栅化规则的边界取舍。

**决定**: 按派单"若没有改善, 回退并如实写结论"—— 回退 line-list 管线, 保留三角带
(STROKE_METHOD='triangle-band', STROKE_PIXEL_EQUIVALENT=False)。最终 vk_ui.py 只增加
契约注释 (实验数值 + 回退原因 + 残差根因), 不含 line-list 代码。

**备注**: 首版 line-list 实验的 prepare 分组有 count 累加笔误 (把 pos 当 count 累加),
产生错误图像 (MAE 0.01882); 修正该笔误后与三角带逐像素相同。笔误属实验代码, 已随
回退消失, 不影响最终文件。

**新增测试**: tests/test_vk_ui_stroke.py (纯 CPU, 进 run_all): 契约常量; width<=1/2
的半宽 0.5/1.0 与每段 6 顶点; alpha 钉 1; close/退化段/点数不足; 并锁定"源码无
line_pipeline / line-list 拓扑"(重引入前必须先跑 A/B)。

**证据文件**: tests/_tmp/probe_linelist_scene.json (1px 多角度场景),
tests/_tmp/probe_linelist_gpu.py (自包含 GPU 直测), 以及
tests/_tmp/ab_ui_lines_{before,list,final}* / ab_ui_lines_alpha_{before,list,final}* /
ab_probe_lines_{band,list,final}* 的 PNG 与 MAE 输出。

---

## 验收数字 (改前 → 改后)

| 门槛 | 改前 | 改后 |
|------|------|------|
| python tests/_tmp/ab_batch.py (22 场景, MAE<=0.0002) | 22/22 PASS, 最大 MAE 0.000082 | 22/22 PASS, 最大 MAE 0.000082 (逐场景逐值相同) |
| python tests/_tmp/ab_gl_vk_ui.py (MAE<=1e-6) | MAE=0.00000009, MAX=0.003922, NCC=0.99998569 | MAE=0.00000009, MAX=0.003922, NCC=0.99998569 (相同) |
| python tests/run_all.py (exit=0) | exit=0 (56 个测试文件) | exit=0 (70 个测试文件, 含新增 test_vk_bucket_order.py; 0 条 FAIL 行) |
| 新增 tests/_tmp/probe_bucket_reorder.py | 修复前语义 MAE=0.003197 / 2093 像素错 | MAE=0.000001 / 0 像素错 |
| 新增 tests/test_vk_bucket_order.py (CPU) | — | 42 条断言全 PASS, exit=0 |

### 关于 run_all 的一次偶发失败 (非本批次)
中间某次 run_all 曾报 test_eai_color_parse.py 失败 (parse_color 系列全 FAIL), 但该测试单独跑
**全 PASS**、且本批次未碰 color/agent_commands 任何代码 —— 属并行子代理正在改写相关文件时
读到的中间态 (同一时刻日志里还能看到 test_vk_material_tex_settings.py 等新增测试文件陆续出现)。
前后各跑一次 run_all 均 exit=0。

## 新增/改动文件清单
- 改: vk_renderer.py (桶重排 + PBR 属性 + 法线回落 + env 缓存 + 采样器 + 阴影限制声明 + 死代码/注释)
- 改: vk_ui.py (文本 LRU 释放 + _groups 有界)
- 新增: tests/test_vk_bucket_order.py (纯 CPU 回归, run_all 自动收集)
- 新增: tests/_tmp/probe_bucket_reorder.py (A/B 复现探针 + 并排图)
- 追加 (2026-11-07 描边实验): 改 vk_ui.py **仅 R2 契约注释** (line-list 实验代码已回退);
  新增 tests/test_vk_ui_stroke.py (纯 CPU, run_all 自动收集);
  新增 tests/_tmp/probe_linelist_scene.json + tests/_tmp/probe_linelist_gpu.py (证据探针)。
- 未 git add / 未 commit; 未改其它任何文件。

## 遗留 / 发现但未改 (不在本批次授权范围)
1. vk_renderer.py 模块 docstring 仍写"4 灯固定展开", 实际已对齐 8 盏 (与字节数同属陈旧注释,
   本批次只按派单修字节数, 未扩大范围)。
2. _upload_tex 的 albedo 缓存键只用 guid: 所有没有 guid 的贴图 (guid == '') 会共用同一条缓存
   —— 多张无 guid 贴图会互相顶替。本次为修法线回落改了键 (加用途维度), 但没改这个。
3. _tex_view 里 albedo 的桶键 guid 取 _tex_guid or guid, 法线贴图只取 guid, 两侧不一致
   (同一张贴图若只设了 _tex_guid 当法线, 桶键会落到空串)。
4. _mesh_corners 缓存 self._bb_local[id(mesh)] 不持 mesh 引用 (与本批次 env 缓存同款 id 复用
   风险), 无淘汰。
5. self._geo (桶几何) 与 self._tex_cache (贴图视图) 都无上限淘汰, 长时间换素材会单调增长。
6. 多平行光阴影 (第 7 项) 仍是已知限制; 彻底修需阴影贴图数组 + 每灯 bind group, 与驱动约束
   冲突, 建议后续在 GL 侧同步评估"多投影灯"的产品语义。
7. Shape 描边 width>=2 的残差 (三角带 vs GL 2/4px 线) 仍是图元级近似; WebGPU 线宽恒为 1px,
   后续若要对齐需在 CPU 端把每段拆成 N 条 1px 线 (或改用几何着色), 属重设计, 本批次不做。
8. 1px 水平线 GL/VK tie-break 差 (GL 画 row20 / VK 画 row19): 与拓扑无关, 需方向相关的
   半像素偏移, 未做。
9. alpha 场景 9500px 的 poly3 填充 alpha 语义差 (GL draw_screen_polygon 忽略 alpha /
   VK 恒 SRC_ALPHA): 属**填充**语义, 不在"描边"派单范围, 未改。
