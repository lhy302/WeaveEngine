// loom_shader_compat.glsl — T3b 单源兼容宏层（2026-11-11 Phase 0 spike）
//
// 约定：**#ifdef LOOM_VK 只允许出现在本文件**。着色器正文只用下面的宏：
//   · DECL_TEX2D / DECL_SAMPLER / SAMPLE2D：GL 用组合采样器 sampler2D；
//     VK 用分离的 texture2D + sampler（wgpu 的 bind group 是分离的）。
//   · DECL_FRAG_UV / LOOM_FRAG_UV：GL 用顶点 varying；VK 用 gl_FragCoord（与既有 WGSL 同口径）。
//   · LOOM_VERTEX_ID：GL=gl_VertexID，VK=gl_VertexIndex。
//   · LOOM_FRAG_OUT：输出变量声明。
#ifndef LOOM_SHADER_COMPAT_GLSL
#define LOOM_SHADER_COMPAT_GLSL

#ifdef LOOM_VK
  #define LOOM_VERTEX_ID gl_VertexIndex
  #define DECL_TEX2D(name, b)    layout(binding = b) uniform texture2D name
  #define DECL_SAMPLER(name, b)  layout(binding = b) uniform sampler name
  #define SAMPLE2D(tex, smp, uv) texture(sampler2D(tex, smp), uv)
  #define SAMPLE2D_LOD(tex, smp, uv, lod) textureLod(sampler2D(tex, smp), uv, lod)
  #define DECL_FRAG_UV           /* VK：无 varying 输入 */
  #define LOOM_FRAG_UV           (gl_FragCoord.xy / par.p1.xy)
  #define LOOM_FRAG_OUT layout(location = 0) out vec4 frag_color;
  // ---- T3c-2b: 阴影采样抽象（VK：分离 texture+sampler；平行光两槽 select，点光 2d-array）----
  #define DECL_SHADOW2D(b)    layout(binding = b) uniform texture2D t_shadow; \
                              layout(binding = b##2) uniform sampler s_shadow
  #define DECL_SHADOWCUBE(b)  layout(binding = b) uniform texture2DArray t_shadow_arr; \
                              layout(binding = b##2) uniform sampler s_shadow_arr
  #define SAMPLE_SHADOW2D(slot, uv) \
      (((slot) < 0.5) ? texture(sampler2D(t_shadow, s_shadow), (uv)).r \
                      : texture(sampler2D(t_shadow2, s_shadow2), (uv)).r)
  #define SAMPLE_SHADOWCUBE(slot, face, uv) \
      texture(sampler2DArray(t_shadow_arr, s_shadow_arr), \
              vec3((uv), float(face))).r
#else
  #define LOOM_VERTEX_ID gl_VertexID
  #define DECL_TEX2D(name, b)    layout(binding = b) uniform sampler2D name
  #define DECL_SAMPLER(name, b)  /* GL：组合采样器自带采样状态 */
  #define SAMPLE2D(tex, smp, uv) texture(tex, uv)
  #define SAMPLE2D_LOD(tex, smp, uv, lod) textureLod(tex, uv, lod)
  #define DECL_FRAG_UV           layout(location = 0) in vec2 v_uv;
  #define LOOM_FRAG_UV           v_uv
  #define LOOM_FRAG_OUT out vec4 frag_color;
  // ---- T3c-2b: 阴影采样抽象（GL：组合式 sampler 数组，槽位/面都是数组下标）----
  #define DECL_SHADOW2D(b)    /* GL：u_shadow_maps[16] 已在着色器里声明 */
  #define DECL_SHADOWCUBE(b)  /* GL：点光 6 面 = 6 个连续槽位 */
  #define SAMPLE_SHADOW2D(slot, uv)        texture(u_shadow_maps[(slot)], (uv)).r
  #define SAMPLE_SHADOWCUBE(slot, face, uv) \
      texture(u_shadow_maps[(slot) + (face)], (uv)).r
#endif

#endif // LOOM_SHADER_COMPAT_GLSL
