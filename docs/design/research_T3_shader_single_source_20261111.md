# T3 着色器单源 · 语言选型与可行性实测（2026-11-11）

> 背景：渲染语义面按原分母折算 11.5（> 目标 8），人类裁决走「改定义」路线。其中**最大的分裂源是着色器**（GLSL 与 WGSL 两份手写，占新增重复的 ~33%）。本文回答：**源语言选哪个、怎么翻译**。

## 1. 实测环境

| 项 | 值 |
|---|---|
| wgpu-py / wgpu-native | 0.33.0（`wgpu_native-release.dll` 8.7MB） |
| GL 后端 | moderngl 5.13 / GL 4.3 core |
| glslang | **16.6.0**（Khronos 官方 windows-x86_64-release，13.1MB zip，`bin/glslang.exe`） |
| 本机其它工具 | naga / glslc / spirv-cross / dxc 均未安装 |

## 2. 三个关键实测结论

### 2.1 wgpu **能直接吃 GLSL**，但 naga 的 GLSL 前端不支持 sampler

| 用例 | 结果 |
|---|---|
| 顶点着色器（无描述符） | ✅ OK |
| 片段着色器（纯输出常量） | ✅ OK |
| `layout(set=,binding=)` UBO | ✅ OK |
| SSBO | ✅ OK |
| **任何 sampler（`sampler2D`/`samplerCube`/`sampler2DShadow`）** | ❌ `NotImplemented("variable qualifier")` |

→ 结论：**GLSL 直接喂 wgpu 不可行**（我们的着色器全都要采样纹理）。

### 2.2 GLSL → SPIR-V（glslang）→ wgpu 可行，但**合并采样器**不行

| 用例 | 结果 |
|---|---|
| 无描述符 SPIR-V | ✅ OK（380B） |
| 只有 UBO 的 SPIR-V | ✅ OK |
| **合并采样器** `uniform sampler2D tex;` | ❌ `invalid id %14`（naga SPIR-V 前端不接受） |
| **分离采样器** `uniform texture2D tex; uniform sampler samp; texture(sampler2D(tex, samp), uv)` | ✅ **OK** |

→ 结论：**GLSL → SPIR-V → wgpu 是可行路径，前提是采样器用分离写法**。

### 2.3 目标环境无关的 SPIR-V 版本

`glslang -V --target-env vulkan1.0/1.1/1.2/1.3` 都能出 SPIR-V（940/940/948/948B）；**合并采样器在哪个版本都失败**，分离采样器在 vulkan1.1 下通过。

## 3. 选型结论

**源语言：GLSL（430 core 语法子集，按 450 Vulkan 规则书写）**，理由：

1. **GL 侧零翻译**：GL 后端本来就吃 GLSL，源即产物，风险最低；
2. **VK 侧走 SPIR-V**：glslang 是 Khronos 官方、成熟、可离线固定版本；wgpu 接受 SPIR-V 已实测；
3. **WGSL 作源不可行**：naga 的 GLSL 输出后端已被移除（社区事实），WGSL→GLSL 没有可靠工具链；
4. **Unity 同构**：Unity 是「单一源语言 + 兼容宏 + 多翻译器」，我们是「GLSL 单一源 + 兼容宏 + glslang」，思路一致。

**翻译链（构建期，非运行期）**：

```
loom_shaders/*.glsl  ──(GL 后端直接用)──►  moderngl 编译
                     └─(加 -DLOOM_VK + 兼容宏)─► glslang -V ──► *.spv  ──► wgpu.create_shader_module(bytes)
```

## 4. 必须先解决的三个前提（T3c → T3b → T3a）

| 阶段 | 内容 | 为什么必须先做 |
|---|---|---|
| **T3c 绑定模型统一** | 参数块与采样器绑定号在**一处定义**（Python 表），着色器用 `layout(binding=N)`；VK 侧 `set=0`、GL 侧用 binding point/纹理单元 | 否则同一份 GLSL 两边绑定对不上，翻译无意义 |
| **T3b 兼容宏层** | `loom_shader_compat.glsl`：采样器宏（`SAMPLE2D(tex,uv)`）、精度宏、矩阵宏；`#ifdef LOOM_VK` 只出现在这一层 | 分离采样器 vs 合并采样器必须靠宏切换（实测结论 2.2） |
| **T3a 单源化** | 逐个 shader 从「GLSL + WGSL 两份」改为「一份 GLSL + 构建期 SPIR-V」；像素门必须不劣化 | 这是真正的分裂消除 |

## 5. 风险与对策

| 风险 | 对策 |
|---|---|
| naga 对某些 GLSL 特性不支持（如 shadow sampler 的分离写法） | 先做**一个着色器**（tonemap）端到端验证，再逐个推进；不支持的项登记为「合理差异」并保留 WGSL 兜底 |
| SPIR-V 版本与 wgpu-native 不匹配 | 固定 `--target-env vulkan1.1`；构建脚本记录 glslang 版本与 sha256 |
| 构建链多一个外部二进制（glslang） | 固定版本 + sha256 校验 + 随仓库/构建缓存分发；缺失时**构建失败**（不静默回退 WGSL） |
| 像素门基线会变（着色器重写） | 每改一个 shader 就重生成该场景参考图并记录，不一次性全改 |

## 6. 验收（T3 整体）

1. 全仓**手写 WGSL 行数 = 0**（由构建期 SPIR-V 取代）；
2. 每个被迁移的 shader 有「GL 像素 == 迁移前」「VK 像素 == 迁移前」两条证据；
3. `ab_gl_vk` 23 场景三向门不劣化；
4. 构建脚本断言：glslang 版本匹配、SPIR-V 产物存在、wgpu 能加载。
