# VK Shape 描边 line-list 实验报告 (批次: r_vk_stroke)

日期: 2026-11-07
工作区: D:\my-project - 副本\Loom(py源代码-工作区)\Loom (Windows, Python 3.12.10)
来源: 修复子代理派单 —— "Shape 描边在 VK 用三角带近似, 与 GL 的 GL_LINES 覆盖规则不同
(改前不透明 MAE 0.00357 / alpha 0.00680); 先实验 wgpu line-list, 有改善才保留"。

改动文件:
- vk_ui.py: **只改 R2 描边契约注释** (STROKE_PIXEL_EQUIVALENT 段落 + draw_screen_lines
  docstring); line-list 实验代码已全部回退, 最终无渲染代码改动。
- tests/test_vk_ui_stroke.py: 新增 (纯 CPU, run_all 自动收集)。
- docs/audit/fix_vk_render_batch.md: 新增第 9 节 + 表格行。
- 证据探针 (tests/_tmp, 不进 run_all): probe_linelist_scene.json, probe_linelist_gpu.py。
- 未 git add / 未 commit; 未改其它文件。

## 0. 结论 (先给结果)

**line-list 方案实测与三角带逐像素相同, 两个验收场景 MAE 与改前逐值不变**
(0.00357361 / 0.00680006), 按派单"若没有改善, 回退并如实写结论" -> **已回退**。
最终 vk_ui.py 仍为 STROKE_METHOD='triangle-band' / STROKE_PIXEL_EQUIVALENT=False,
只保留契约注释记录本次实验与残差根因。

## 1. 实验设计

假设: GL 的 1px 描边走 GL_LINES (diamond-exit 光栅化), VK 的 1px 三角带是
"像素中心落在 1px 矩形内" —— 换用 wgpu line-list 拓扑 (恒 1px) 应更接近 GL。

实现 (临时):
1. VkUIPipeline 增加 line_pipeline: 与 UI 管线共享 shader / bind group layout /
   顶点格式 / 混合状态, 仅 primitive.topology='line-list'。
2. op 记录增加 kind (tri/line); prepare 分组键含 kind; submit 按 kind 切管线。
3. draw_screen_lines: float(width) <= 1.0 发 line-list (每段 2 顶点), width>1
   保持三角带 (WebGPU 线宽恒为 1px, 无法表达 2/4px)。
4. 首版实验有 prepare 分组 count 累加笔误 (把 pos 当 count), 产生错误图像
   (MAE 0.01882); 修正后得到下述有效数值。该笔误属实验代码, 已随回退消失。

## 2. 改前 / line-list / 改后 实测对照

命令: python tests/_tmp/ab_gl_vk_ui.py <scene> <out> (480x320, 同场景/相机/分辨率,
逐像素 MAE/MAX/NCC)。

| 场景 | 改前 (三角带) | line-list 实验 | 改后 (回退) |
|------|----------------|----------------|-------------|
| tests/_tmp/ui_lines_scene.json (不透明) | **MAE 0.00357361**, MAX 0.929412, NCC 0.92875874, 858/153600 px | **MAE 0.00357361**, MAX 0.929412, NCC 0.92875874, 858 px (逐值相同) | **MAE 0.00357361** (相同) |
| tests/_tmp/ui_lines_alpha_scene.json (半透明) | **MAE 0.00680006**, MAX 0.929412, NCC 0.91586465, 10044/153600 px | **MAE 0.00680006**, MAX 0.929412, NCC 0.91586465, 10044 px (逐值相同) | **MAE 0.00680006** (相同) |
| tests/_tmp/probe_linelist_scene.json (自建 1px 多角度 + w2 对照) | MAE 0.00323824, 1034 px | MAE 0.00323824, 1034 px (逐值相同) | MAE 0.00323824 (相同) |
| tests/_tmp/probe_linelist_gpu.py (GPU 直测, 不依赖 vk_ui) | — | 0/30/45/60/90° 五角度: line-list vs hw=0.5 三角带 **每角度 0 像素差** | — |

补充: line-list 实验产出的 VK 图像与三角带 VK 图像**逐像素相同** (PNG 数组 0 差异),
不是"接近", 而是完全相同。

## 3. 为什么 line-list 没用 (根因)

残差根本不在 width<=1:

1. **不透明场景 858 个差异像素全部落在 width>=2 的描边上**。line1 是场景里唯一
   width=1 的描边, 距其路径 2.5px 内差异像素 = **0**; 逐形状 diff: poly3 510 /
   line4 198 / poly1 94 / poly2c 60 / circ 52 / line2 12。WebGPU 线宽恒为 1px,
   line-list 覆盖不到 width=2/4。
2. **alpha 场景 10044 个差异像素中 9500 个是 poly3 填充** (多边形面积 9500) 的 alpha
   语义差: GL draw_screen_polygon 走 draw_lines, 期间 BLEND 关闭 -> 忽略 alpha;
   VK 恒 SRC_ALPHA。占 diff 总量 61.6%; 描边部分约 544 像素。与描边拓扑无关。
3. **1px 线本身存在 GL/VK tie-break 差**: 水平线 y=20.0 时 GL 画 row 20, VK (三角带与
   line-list 都是) 画 row 19。换拓扑不修, 属两套光栅化规则的边界取舍。

## 4. 验收

| 项 | 结果 |
|----|------|
| python tests/_tmp/ab_batch.py (22 场景, MAE<=0.0002) | **22/22 PASS**, 最大 MAE 0.000082 (ab_ui_scene.json), exit=0 |
| python tests/run_all.py | **exit=0**, 102 个测试文件, "全部测试完成" (含新增 test_vk_ui_stroke.py 与 R3 test_r5_wheel_backend.py) |
| python tests/test_vk_ui_stroke.py | ALL PASS (14 条断言), exit=0 |
| 描边 A/B 不透明 | MAE 0.00357361 (改前 = 改后, 未劣化) |
| 描边 A/B alpha | MAE 0.00680006 (改前 = 改后, 未劣化) |

## 5. 并行协作 / 交叉验证 (父级要求)

- **最终 vk_ui.py 包含 R3 的滚轮语义改动**: _wheel_taken_by_scrollview()
  (模块级函数)、begin_frame 里的 wheel_taken = ...、以及
  self.last_wheel_consumed = bool(wheel) and consumed and wheel_taken。
  本批次**未触碰**这些区域 (也未动文本 LRU / _groups)。
- python tests/test_r5_wheel_backend.py 单独跑 **ALL PASS** (含 J helper 三条)。
- 事故与恢复 (如实记录): 回退 line-list 时曾用整文件恢复 09:37 备份, 一度把 R3 的
  滚轮改动回退; 已由 R3/父级恢复。此后只做局部 patch, 并重新跑通 R3 单测与 run_all。
  最终文件经 grep + 单测交叉确认。

## 6. 遗留 (发现但未改, 不在"描边"派单范围)

1. width>=2 描边仍是三角带 vs GL 2/4px 线的图元级近似; WebGPU 线宽恒 1px, 要更接近
   需在 CPU 端把每段拆成 N 条 1px 线 (或几何着色), 属重设计。
2. 1px 水平线 GL/VK tie-break 差 (row20 vs row19): 需方向相关的半像素偏移, 未做。
3. alpha 场景 9500px 的 poly3 **填充** alpha 语义差 (GL 忽略 alpha / VK 恒混合):
   属填充语义, 不在本批次范围; 若要修, 应在 draw_screen_polygon 同样把 alpha 钉 1
   (与描边一致), 但会改变现有填充视觉, 需单独裁决。

## 7. 复现命令

    python tests/_tmp/ab_gl_vk_ui.py tests/_tmp/ui_lines_scene.json tests/_tmp/ab_ui_lines_final
    python tests/_tmp/ab_gl_vk_ui.py tests/_tmp/ui_lines_alpha_scene.json tests/_tmp/ab_ui_lines_alpha_final
    python tests/_tmp/ab_gl_vk_ui.py tests/_tmp/probe_linelist_scene.json tests/_tmp/ab_probe_lines_final
    python tests/_tmp/probe_linelist_gpu.py
    python tests/test_vk_ui_stroke.py
    python tests/_tmp/ab_batch.py
    python tests/run_all.py
