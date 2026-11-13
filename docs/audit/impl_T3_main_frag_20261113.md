# 实现报告 · T3a-3 主 pass 片段单源化（2026-11-13）

> **状态：部分完成**——A1-1（main.frag 补完 + 接入构建）与 A1-2（VK 改喂 SPIR-V、删手写 WGSL）已完成；
> **门 1 / 门 2 / 门 4 全绿**；**门 3（全量回归）红 6 项，均为 HEAD 上已存在的失败**（其中 5 项同一根因），
> 已用独立 HEAD worktree 与 git 历史取证，详见第 5 节。工作树**未 commit / 未 add**。
>
> 基线：开工时 HEAD 50bc81a，收尾时 HEAD 6a92d85（期间主审提交了 docs/tools 两批提交，非本次改动）。
> 环境：Windows PowerShell / py -3.13（3.13.15）/ wgpu 0.33 / glslang 16.6.0（sha256 校验通过）。

---

## 1. 改了什么

| 文件 | 行数变化 | 内容 |
|---|---|---|
| Loom/shaders/main.frag | **新增 264 行** | 由 main.frag.wip 补完：#version 450 + @@COMPAT@@/@@SCENE_UBO@@/@@BUCKET_UBO@@ 三标记；PBR/非 PBR 分支、rim、gamma、饱和度、frag_color 与 GL 现役逐句一致；采样器全部走 compat 宏；阴影坐标走 SHADOW_UV/SHADOW_DEPTH |
| Loom/shaders/main.frag.spv | **新增 33 156 B** | glslang -V --target-env vulkan1.1 -DLOOM_VK 产物（入口名 main） |
| Loom/shaders/main.frag.wip | **删除 266 行** | 已被 main.frag 取代 |
| Loom/shaders/loom_shader_compat.glsl | +18 / −2 | ① VK 分支加 #extension GL_EXT_samplerless_texture_functions : require；② 新增 SHADOW_UV/SHADOW_DEPTH（GL/VK 窗口深度与纹理行序不同）；③ SAMPLE_SHADOWCUBE VK 分支在 texelFetch 前翻 y（旧手写 WGSL 的 uv.y=1-uv.y） |
| Loom/vk_renderer.py | +28 / −295 | 删 _MAIN_VERT+_MAIN_FRAG（含 pcf/pcf2 手写 WGSL，共 289 行）；新增 _main_fs_module()；_build_pipelines 与 _ensure_main_pipe 改读 main.frag.spv，entry_point='main'；point_bias=0.004；点光 params.w 打包对齐 GL 规则 |
| Loom/loom_shaders.py | +23 / −262 | 删掉第二份 GLSL 文本；_FRAG_SRC = _shared_frag_src() 直接读 shaders/main.frag（与 main.vert 同款：替换三标记 + #version 450→430） |
| Loom/loom_shader_bindings.py | +3 / −1 | bucket_block_glsl() 的 UBO 绑定号由 B_BUCKET（GL=1）改为 SB_BUCKET（GL=1 / **VK=8**）；否则 SPIR-V 的 Bucket 会落在 binding 1 与 t_shadow 冲突 |
| tools/build_shaders.py | +3 | _expand() 增加 //@@BUCKET_UBO@@ → bucket_block_glsl()（与 SCENE 完全同做法） |
| Loom/tests/test_vk_two_dir_shadow.py | +35 / −13 | A2/A6–A9/E5 断言改写（见第 8 节） |
| Loom/tests/test_frame_plan.py | +8 / −5 | H19 断言改写（见第 8 节） |
| Loom/shaders/*.spv（5 个旧文件） | 二进制 | 仅因 compat 文本新增 #extension/宏而重新生成；顶点/后处理语义未变（门 2 逐值不变） |

**仓库根临时产物已清空**：诊断脚本/截图已移至 %TEMP%\loom_t3_diag\，_main_frag_backup.glsl 已删除；
git status 只剩上表源码/测试改动 + 新增 main.frag/main.frag.spv。

---

## 2. 门 1：构建

    [shaders] main.frag                    -> main.frag.spv            33156 bytes
    [shaders] main.vert                    -> main.vert.spv             4424 bytes
    [shaders] post_bright.frag             -> post_bright.frag.spv      2144 bytes
    [shaders] post_down.frag               -> post_down.frag.spv        2516 bytes
    [shaders] post_fullscreen.vert         -> post_fullscreen.vert.spv  1312 bytes
    [shaders] post_tonemap.frag            -> post_tonemap.frag.spv     2180 bytes
    BUILD EXIT=0

**实际是 6 个 .spv，不是 7 个**：Loom/shaders 源文件只有 main.vert + main.frag + 4 个 post
（post_bright.frag/post_down.frag/post_tonemap.frag/post_fullscreen.vert）。任务描述里的「7 个」是笔误，主审已确认按真实清单。

---

## 3. 门 2：23 场景像素（改前 = 干净 HEAD 实测；改后 = 最终树）

完整 23×3 表（MAE gl/ref、vk/ref、gl/vk）；**只有 ab_point_shadow 变化，其余 22 场景逐值相同**：

| 场景 | 改前 GL/ref | 改前 VK/ref | 改前 GL/VK | 改后 GL/ref | 改后 VK/ref | 改后 GL/VK |
|---|---|---|---|---|---|---|
| ab_bloom | 0.000000 | 0.000000 | 0.000000 | 0.000000 | 0.000000 | 0.000000 |
| ab_c_dir+point | 0.000000 | 0.000000 | 0.000000 | 0.000000 | 0.000000 | 0.000000 |
| ab_c_dir_only | 0.000000 | 0.000000 | 0.000000 | 0.000000 | 0.000000 | 0.000000 |
| ab_c_dir_shadow | 0.000029 | 0.000051 | 0.000029 | 0.000029 | 0.000051 | 0.000029 |
| ab_c_point_only | 0.000000 | 0.000000 | 0.000000 | 0.000000 | 0.000000 | 0.000000 |
| ab_c_spot_only | 0.000000 | 0.000000 | 0.000000 | 0.000000 | 0.000000 | 0.000000 |
| ab_cube | 0.000000 | 0.000000 | 0.000000 | 0.000000 | 0.000000 | 0.000000 |
| ab_env | 0.000002 | 0.000002 | 0.000001 | 0.000002 | 0.000002 | 0.000001 |
| ab_env_off | 0.000000 | 0.000000 | 0.000000 | 0.000000 | 0.000000 | 0.000000 |
| ab_nrm | 0.000000 | 0.000000 | 0.000000 | 0.000000 | 0.000000 | 0.000000 |
| ab_nrm_off | 0.000000 | 0.000000 | 0.000000 | 0.000000 | 0.000000 | 0.000000 |
| ab_pbr | 0.000000 | 0.000000 | 0.000000 | 0.000000 | 0.000000 | 0.000000 |
| ab_plane | 0.000000 | 0.000000 | 0.000000 | 0.000000 | 0.000000 | 0.000000 |
| ab_plane_cube | 0.000013 | 0.000013 | 0.000000 | 0.000013 | 0.000013 | 0.000000 |
| ab_plane_cube_sun_pt | 0.000011 | 0.000011 | 0.000000 | 0.000011 | 0.000011 | 0.000000 |
| ab_plane_shfalse | 0.000000 | 0.000000 | 0.000000 | 0.000000 | 0.000000 | 0.000000 |
| ab_plane_shtrue | 0.000000 | 0.000000 | 0.000000 | 0.000000 | 0.000000 | 0.000000 |
| ab_plane_sphere | 0.000016 | 0.000038 | 0.000029 | 0.000016 | 0.000038 | 0.000029 |
| **ab_point_shadow** | **0.000057** | **0.000051** | **0.000045** | **0.000057** | **0.000046** | **0.000011** |
| ab_scene | 0.000026 | 0.000046 | 0.000028 | 0.000026 | 0.000046 | 0.000028 |
| ab_sky | 0.000012 | 0.000012 | 0.000000 | 0.000012 | 0.000012 | 0.000000 |
| ab_tex | 0.000000 | 0.000000 | 0.000000 | 0.000000 | 0.000000 | 0.000000 |
| ab_ui_scene | 0.000022 | 0.000066 | 0.000053 | 0.000022 | 0.000066 | 0.000053 |

最终 test_ab_gl_vk.py：**23/23 PASS，EXIT=0**（UI 子项 UI MAE 0.000110 也不变）。
ab_point_shadow 的 MAX 0.0941→0.0314、NCC 0.999306→0.999825。

### 3.1 为什么 ab_point_shadow 的 VK 值变了（不是「顺手调基线」）

单源片段对点光用的是 GL 的 **9 tap PCF**；被删掉的手写 WGSL 是 **单 tap**（textureLoad 一次 + 比较），
且 VK 的 point_bias 是 0.002（GL 在 9 tap 下调成 0.004）。实测三组（同一场景/同一最终树）：

| VK 点光实现 | VK/ref MAE | 结论 |
|---|---|---|
| 旧手写 WGSL：1 tap + bias 0.002 | 0.000051 | 改前基线 |
| 单源 9 tap + bias 0.002 | **0.000828** | 失败：整片 floor 点状 acne（9 tap 需要 GL 的 0.004 偏置） |
| 单源 9 tap + bias 0.004（与 GL 同值） | **0.000046** | 通过；GL/VK 0.000011 |

→ 因此 vk_renderer._pack_scene 显式传 point_bias=0.004（GL 侧在 loom_lighting.py:205 也是 0.004）。
这是**统一后的必然结果**：VK 点光从单 tap 升级为与 GL 相同的 9 tap，像素因此变化；GL 侧完全不变。
**没有修改任何基线文件/参考图。**

### 3.2 文档里的 ab_point_shadow 基线本身是错的

- 任务/docs/handoff/接手须知_T3着色器单源化_20261111.md:38 写「GL 2.5e-5 / VK 5.1e-5」；
- 干净 HEAD 实测（连跑两次一致）：**GL 5.7e-5 / VK 5.1e-5 / GL-VK 4.5e-5**；
- docs/audit/final_03_四批目标达成度核对.md:102 又写「0.000051」，与 handoff 的 2.5e-5 不一致。
→ 大概率是早期把 VK 值抄进了 GL 列。**本报告以干净 HEAD 实测为准**；任务给的 ab_scene / ab_c_dir_shadow / ab_pbr 三组与实测逐值吻合。

---

## 4. 门 4：grep 证据

    # Loom/vk_renderer.py 中 _MAIN_FRAG / pcf2 / "fn pcf" / _MAIN_VERT 出现次数 = 0
    Select-String Loom/vk_renderer.py -Pattern '_MAIN_FRAG|pcf2|fn pcf|_MAIN_VERT'   -> count=0

    # #ifdef LOOM_VK 仍只出现在兼容层（共 2 处：1 处注释说明 + 1 处 #ifdef）
    Loom/shaders/loom_shader_compat.glsl:3   （注释：约定：#ifdef LOOM_VK 只允许出现在本文件）
    Loom/shaders/loom_shader_compat.glsl:8   （真正的 #ifdef）

说明：archive/bench/_bench_stable/vk_renderer.py 与 archive/bench/_bench_ws/vk_renderer.py 里仍有旧
_MAIN_FRAG，那是**归档的历史基准快照**，不是引擎代码，本次未动。
_MAIN_VERT 的唯一使用者原本就是片段的宿主，删除后全仓无引用（测试 H19 已改写）。

---

## 5. 门 3：全量回归（135 个测试）——红 6 项，全部是 HEAD 既有失败

cd Loom; py -3.13 tests/run_all.py → RUNALL EXIT=1，135 个测试文件，失败 6 个：

    有失败: ['test_cubemap.py', 'test_eai_real.py', 'test_light_shadow_slots.py',
            'test_lod.py', 'test_texture.py', 'test_integration.py']

### 5.1 5 项同一根因：uniform mat4 u.mvp;（非法 GLSL，HEAD 上就有）

失败栈全部止于 engine.py:761 编译 _LINE_VERT：
0(4): error C0000: syntax error ... at token "." + invalid character 'm' in swizzle "mvp"。
溯源 git log -S 'uniform mat4 u.mvp' -- Loom/loom_shaders.py → **4a66faa（T3c-1）** 把
_WORLD_UI_VERT / _LINE_VERT 里的 u_view_proj 批量误替换成 u.mvp（主顶点的那处替换是对的）。
engine.py:793 仍在读 self._line_prog['u_view_proj']，证明正确名字就是 u_view_proj。
**独立取证**：在 HEAD 的临时 worktree（不含本次改动）里复制官方 DLL 后，只把这 4 处改回 u_view_proj，
test_cubemap / test_texture / test_lod / test_eai_real / test_integration **全部 ALL PASS**。
python 3.12 下同样报这个 GLSL 错，排除解释器版本因素。

### 5.2 第 6 项：test_light_shadow_slots.py 自 T3c-1 起已失效（HEAD 上同样红）

HEAD worktree 复现一致：SlotEngine 缺 camera；补 camera/_vp/ctx.buffer 桩后下一个错误是
self.prog['u_shadow_slot'].value is None —— T3c-1 已把 shadow slot 移进 Scene UBO，
该测试仍在读被删掉的具名 uniform，需要重写断言（改读 UBO 字节），不是一行能修的。

### 5.3 结论

- 本次改动的两个测试（test_frame_plan / test_vk_two_dir_shadow）**全绿**；run_all 里其余 129 个测试全绿；
- 6 个红项**没有一个由本次改动引入**（5 项是 4a66faa 的 GLSL typo，1 项是 4a66faa 的测试债）。
- 按「只做这两项」的纪律，**未修**这两处既有缺陷，留给主审裁决（修复方案见第 10 节）。

---

## 6. 与 _FRAG_SRC 的逐段对照（强制项）

| 项 | 数值 |
|---|---|
| HEAD 的 main.frag.wip | **266 行**（handoff 写 260，实测 266） |
| HEAD 的 _FRAG_SRC 字面量 | **258 行** |
| 最终 main.frag | **264 行** |
| GL 加载后（展开 compat+两个 UBO 块，450→430） | **386 行** |
| 归一化后的**可执行语句** | **旧 191 行 == 新 191 行** |

归一化逐行 diff（把宏还原成 GL 原写法、剔除声明/注释后）：**唯一差异是 SHADOW_UV(lp) 展开多了一层
vec2(...) 包装，语义完全等价；没有一行可执行语句缺失**。逐项核对过：

- PBR 函数 _d_ggx/_g_smith/_f_schlick/pbr_light：逐字一致；
- pcf_shadow / pcf_shadow_cube / point_shadow：逐字一致（采样调用换成宏）；
- 光照循环：点光/聚光/平行光、range fade、spot 锥角、Blinn-Phong 高光、beam 截面、g_in_shape、阴影门控全部在；
- PBR 分支：env（SAMPLECUBE_LOD/SAMPLECUBE）与无 env 的 amb_pbr 都在；
- 非 PBR 分支：col = base * (ambient + acc) + vec3(rim) 在；
- rim、gamma（1/2.2）、饱和度（v_sat + 亮度权重）、frag_color = vec4(col, 1.0) 在。

**差额来源**：266→264 = 删掉 WIP 里误粘的 4 行兼容层头注释 + 新增 2 行单源说明注释；**不是漏段**。
audit 写的「目标约 334 行」与实际（258 行源码 / 386 行展开）都不符，属旧估算。

---

## 7. 关键设计点（为什么必须这么做）

### 7.1 阴影坐标/深度宏（SHADOW_UV/SHADOW_DEPTH）

matlib.mat4_ortho 的 clip.z 已经是 [0,1]；但两个 API 的窗口深度不同：

- GL：硬件把 clip.z∈[0,1] 再映射一次 → 窗口深度 = 0.5 + 0.5*clipz，旧 GL 源码正是 (lp.z/lp.w)*0.5+0.5；
- wgpu：NDC z 就是 [0,1] → 窗口深度 = clipz，旧手写 WGSL 正是 lp.z/lp.w；
- 纹理行序：GL 的 uv 原点在左下；wgpu 帧缓冲自上而下，同一 NDC 点在 VK 贴图里是 1-uv.y（旧 WGSL 的
  0.5-lp.y/lp.w*0.5 与点光 uv.y=1-uv.y 就是同一个坑）。

若直接把 GL 公式搬进 SPIR-V，VK 阴影会整体错位/镜像（实测 9 tap + 不做深度换算时 MAE 跳到 1e-1 量级）。
宏的注释里已写明依据。

### 7.2 VK 点光 params.w

GL 规则（loom_lighting.py）：b['slots'] 初始 **-1**（line 111/126），只有真正拿到阴影贴图的灯
（if light.shadow: ... b['slots'][i] = unit - 1，line 181）才 >=0；着色器统一 if (int(params.w) >= 0)。
VK 旧 _pack_scene 对点光恒写 0（注释「点光/聚光不用」），旧 WGSL 靠 extra.w 兜底；单源后必须
**有贴图=0 / 无贴图=-1**。已改 vk_renderer._pack_scene，并由 test_vk_two_dir_shadow E5 锁住。
**像素证据**：ab_point_shadow 只有 1 盏点光，改前/改后打包值都是 0，实测像素 delta = 0
（MAE=0.000057/0.000046/0.000011 两次完全相同）；该修复只对「≥2 盏点光」场景有可见效果，
而 23 场景集里没有这种场景，属于防御性修正。

### 7.3 Bucket UBO 绑定号

bucket_block_glsl() 原来写 B_BUCKET（GL 绑定点=1）。SPIR-V 会把它当 descriptor binding=1，
与 t_shadow（binding 1）冲突。改成 compat 的 SB_BUCKET（GL=1 / VK=8），GL 侧行为不变（门 2 逐值相同）。

---

## 8. 测试断言改写清单（含主审要求的 A/B/C）

| 文件:行 | 原断言看什么 | 新断言看什么 | 等价/更强理由 |
|---|---|---|---|
| test_vk_two_dir_shadow.py:130 (A2) | BGL 集合 {0,1,2,3,5..11} | {0..11} | binding 4（点光 texelFetch 的 non-filtering sampler）在 d84dd98 加入后本断言未同步；**HEAD 上本来就是红的**（已用 HEAD 版测试复现），补 4 是修正陈旧断言 |
| :147 (A6) | @binding(10) var t_shadow2 等 WGSL 字符串 | compat VK 分支 SB_SHADOW2 10 + binding = 11 + uniform sampler s_shadow2 + SAMPLE_SHADOW2D 被 main.frag 使用 | WGSL 已删除；新断言把「绑定号 10/11」与「单源宏真实被使用」绑死，**更强** |
| :153 (A7) | fn pcf2( + textureSample | pcf_shadow/pcf_shadow_cube 存在且无 pcf2 | 单源后只有一份 pcf，槽位选择在宏里；等价 |
| :157 (A8) | WGSL 的 L.params.w < -0.5 / < 0.5 | main.frag 的 int(u.lights[i].params.w) >= 0 + 点光/平行光两处调用 + 无 L.params.w | 门控语义从「WGSL 分支」变成「Scene UBO 同一字段」，更强 |
| :162 (A9) | 无 textureSample(t_shadow[ | VK 分支 texelFetch(sampler2DArray(...)) + ivec3 逐面 + 无 u_shadow_maps[ | 等价（动态数组下标只允许出现在 GL 分支） |
| :301 (E5) | 两盏点光 params.w 都=0 | p1=0 / p2=-1 | 对齐 GL slots 规则；旧期望会把第二盏点光送去采第一盏的图（既有缺陷） |
| test_frame_plan.py:406 (H19) | _MAIN_VERT+_MAIN_FRAG 里 6 个字段名 in 字符串 | bucket_block_glsl() 的字段序 == BUCKET_FIELDS 且 float 数 == BUCKET_BYTES/4 | 从「弱 in-匹配」升级为「生成器文本与字段表逐序绑死」，**更强** |

**变异自证（条件 B）**：
- A6：把 compat 的 #define SB_SHADOW2 10 改成 9 → FAIL A6 ...（RC=1），已还原（字节相同）。
- H19：把 bucket_block_glsl() 的 metallic/roughness 两行对调 → FAIL H19 ... ['roughness','metallic',...]（RC=1），已还原（字节相同）。

---

## 9. 遗留不确定点（宁多列）

1. **VK 9 tap 与 GL 9 tap 仍有 1.1e-5 的端间差**（旧基线 4.5e-5，已下降）。未完全定位：可能是 uv 正好落在
   texel 边界时的取整、以及 texelFetch 越界行为在 GL/VK 不同（旧 VK 有 clamp，单源后与 GL 一样不 clamp）。
   当前在门限内且优于基线，但**不是 0**。
2. point_bias=0.004 目前是 GL 与 VK 各写一份字面量（loom_lighting.py:205 与 vk_renderer.py）。若后续把
   bias 收敛进 loom_scene_ubo，应改成单一常量；本次未动该文件（不在允许范围）。
3. SHADOW_UV 的 VK 分支除以 w（照旧 WGSL 的 lp.x/lp.w），GL 分支不除（正交 w=1）。对平行光等价；
   若未来有非正交 light ortho 会分叉。
4. main.vert.spv 字节数 4380→4424：只因 compat 文本多了一行 #extension（VK 分支）与宏，顶点语义未变
   （门 2 所有顶点相关场景逐值相同）。
5. floor 上点状 acne 的敏感度：0.004 是 GL 调好的值；若以后改 PCF 半径/分辨率，bias 可能需要重调。
6. 23 场景里没有「≥2 盏点光都要求阴影」的场景，params.w 修复只有单测（E5）覆盖，缺像素级证据。
7. #extension GL_EXT_samplerless_texture_functions 在 main.vert 的 VK 编译里也会出现（未使用）；
   glslang/naga 都接受（门 1/2 已证）。
8. archive/bench/* 仍有旧 _MAIN_FRAG，如 grep 全仓会命中，需要区分归档目录。

---

## 10. 下一步建议

1. **修 HEAD 既有 red（建议单独提交）**：loom_shaders.py 的 _WORLD_UI_VERT/_LINE_VERT 里
   4 处 uniform mat4 u.mvp; / u.mvp * 改回 u_view_proj（已验证 5 个测试转绿）；再重写
   test_light_shadow_slots.py（读 Scene UBO 的 slots + 补 camera/_vp/ctx 桩）。
2. 主审复核后按需更新 ab_point_shadow 的基线列（新 VK/ref 0.000046 优于旧值），并订正 handoff/版本计划里
   的「GL 2.5e-5」；**参考图/基线文件我未改**。
3. 加一个「2 盏点光都开阴影」的 A/B 场景，锁住 params.w=-1 的行为。
4. 后续批次：天空 _SKY_WGSL、UI vk_ui.py、阴影 pass _SHADOW_VERT、_MIP_WGSL 仍未单源化。
