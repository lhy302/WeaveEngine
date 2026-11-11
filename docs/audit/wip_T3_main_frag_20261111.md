# WIP：主 pass 片段单源化（`main.frag.wip`）— 暂停点报告

> 生成时间：2026-11-11（beta6 暂停）。作者：R01（实现者）工作由其主审在主进程落盘——**实现者子代理在写报告前因 API 额度中断**，本文由主审依据实际文件与实测编译结果整理。
> 文件：`Loom/shaders/main.frag.wip`（**260 行，不参与构建**，`build_shaders.py` 清单未包含它）。

## 1. 完成度

| 项 | 状态 |
|---|---|
| 文件结构 | ✅ 已写出：`#version` + 输入 location 0/1/2/3/4/5 + PBR 函数（`_d_ggx` / `_g_smith` / `_f_schlick`）+ `pcf_shadow` / `pcf_shadow_cube` / `point_shadow` + `main()`（PBR 与非 PBR 两分支、gamma、饱和度、`frag_color`） |
| 行数 | 260 / 目标约 334（GL `loom_shaders._FRAG_SRC`）；差异主要在注释与排版，**主体公式已转写** |
| 编译验证 | ❌ **未通过**（见 §2 的两个具体错误） |
| 接入 VK | ❌ 未接入（未生成 SPIR-V、`vk_renderer` 未引用） |
| 像素验证 | ❌ 无（未进入渲染路径） |

## 2. 实测编译错误（主审跑 `expand + glslang -V --target-env vulkan1.1 -DLOOM_VK`）

### 错误 1（已定位，修法明确）

```
ERROR: main.frag:190: 'textureSize' : required extension not requested: GL_EXT_samplerless_texture_functions
```

**原因**：VK 分支里 `textureSize(t_shadow_arr, 0)` 作用在**无采样器**的 texture 上，需要扩展声明。
**修法**：在 compat 的 VK 分支（或展开后的 `#version` 之后）加：
```glsl
#extension GL_EXT_samplerless_texture_functions : require
```
→ 主审实测：加该扩展后**错误 1 消失**。

### 错误 2（下一个阻塞）

```
ERROR: main.frag:229: 'bkt' : undeclared identifier
ERROR: main.frag:229: 'has_normal_map' : unknown swizzle selection
```

**原因**：`bkt`（Bucket UBO）**没有被注入**。GL 主片段里 `bkt.*` 由 `bucket_block_glsl()` 生成；WIP 文件里缺 `@@BUCKET_UBO@@` 标记或该段声明。
**修法**：在 WIP 的 uniforms 区放入 `//@@BUCKET_UBO@@` 标记，并让 `loom_shader_bindings.expand()` 处理该标记（参照 `//@@SCENE_UBO@@` 的现有做法）。

## 3. 本次 WIP 期间踩到的坑（实现者记录 + 主审复核）

1. **宏重复定义 `C7101`**：给 `main.frag` 准备 `SB_*` 绑定宏时，新块与 2b 阶段的 `DECL_SHADOW2D/CUBE` 重复定义。
   - **结论：不要用字符串替换改宏文件**（反斜杠续行/缩进匹配失败），**整文件重写**更快更稳。
2. **VK 点光阴影的采样模型**：`texture_2d_array` + unfilterable `r32float` + `textureLoad`，与 GL 的 `texture()` 不同；已统一到 `texelFetch`，并给 VK 加了 non-filtering sampler（binding 4）。
3. **`textureSize` 需要 samplerless 扩展**（见错误 1）——这是 `texelFetch` 统一路线的连带成本，容易漏。

## 4. 剩余工作（精确清单）

```
① compat VK 分支加 #extension GL_EXT_samplerless_texture_functions : require
② WIP 里补 //@@BUCKET_UBO@@ 标记 + expand() 支持（或手写与 bucket_block_glsl() 一致的声明）
③ 重新编译至 SPIR-V 成功；把 main.frag.wip 改名 main.frag 并加入 build_shaders.SHADERS
④ VK: _MAIN_FRAG(253 行) + pcf/pcf2(~26 行) 删除，改喂 SPIR-V
⑤ 验收: 23 场景 MAE 与基线逐值相同（ab_pbr 0；ab_scene GL 2.6e-5/VK 4.6e-5；ab_c_dir_shadow GL 2.9e-5/VK 5.1e-5；ab_point_shadow GL 2.5e-5/VK 5.1e-5）
⑥ 全量回归 + ab_gl_vk 23/23
```

## 5. 不确定点（宁多勿少）

1. **`pcf_shadow` 的槽位语义**：WIP 里 `pcf_shadow(int slot, ...)` 与 GL 现版一致，但 VK 侧 `t_shadow`/`t_shadow2` 的双槽 select 是否已在宏内完整覆盖，**未验证**。
2. **点光 `point_shadow(slot, rd)`**：WIP 保留了 GL 的 6 面常量分支写法；VK 用 `texelFetch(2d-array, face)`，宏内 face 索引与 GL 的 `slot+face` 是否一一对应，**未验证**。
3. **`v_matv` 与 `bkt` 的取值优先级**：2c 后 GL 材质改读 `v_matv.y/z/w`，但 WIP 里是否还残留 `bkt.metallic` 引用，**未逐行核对**。
4. **行数差（260 vs 334）**：差额是否全是注释/排版，还是**有段落漏转**（尤其非 PBR 分支的 rim/ambient 细节），**未逐段比对**。

## 6. 当前树状态（暂停时）

```
HEAD 1086640（WIP 提交）→ 之后仅文档提交
build_shaders.py: EXIT=0（WIP 不在清单里）
test_ab_gl_vk: 23/23 PASS
23 场景 MAE 与基线逐值相同
```
