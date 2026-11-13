// loom_shader_compat.glsl — T3 单源兼容层（2026-11-11；2026-11-13 补 samplerless 扩展 + 阴影坐标约定）
//
// 约定：#ifdef LOOM_VK **只允许出现在本文件**。着色器正文只用下面的宏。
// 本文件为**单一来源**：每个宏只定义一次（GL / VK 各一份分支）。
#ifndef LOOM_SHADER_COMPAT_GLSL
#define LOOM_SHADER_COMPAT_GLSL

#ifdef LOOM_VK
  // 点光阴影走 texture2DArray + texelFetch：textureSize() 没有绑定采样器，
  // 需要此扩展（否则 glslang 报 "required extension not requested"）。
  #extension GL_EXT_samplerless_texture_functions : require
  // ---------- 绑定号（VK：与 vk_renderer._bgl 一致）----------
  #define SB_SCENE 0
  #define SB_BUCKET 8
  #define SB_ALBEDO 5
  #define SB_SAMPLER 6
  #define SB_NORMAL 7
  #define SB_ENV 9
  #define SB_SHADOW 1
  #define SB_SHADOW2 10
  #define SB_SHADOW_ARR 3
  #define SB_ARR_SMP 4
  // ---------- 顶点/片段基础 ----------
  #define LOOM_VERTEX_ID gl_VertexIndex
  #define DECL_FRAG_UV           /* VK：无 varying 输入（用 gl_FragCoord） */
  #define LOOM_FRAG_UV           (gl_FragCoord.xy / par.p1.xy)
  #define LOOM_FRAG_OUT layout(location = 0) out vec4 frag_color;
  // ---------- 纹理/采样器（VK：分离 texture + sampler）----------
  #define DECL_TEX2D(name, b)    layout(binding = b) uniform texture2D name
  #define DECL_SAMPLER(name, b)  layout(binding = b) uniform sampler name
  #define DECL_SAMPLER_B(name, b) layout(binding = b) uniform sampler name
  #define SAMPLE2D(tex, smp, uv) texture(sampler2D(tex, smp), (uv))
  #define SAMPLE2D_LOD(tex, smp, uv, lod) textureLod(sampler2D(tex, smp), (uv), (lod))
  #define DECL_TEXCUBE(name, b)  layout(binding = b) uniform textureCube name
  #define SAMPLECUBE(name, smp, dir) texture(samplerCube(name, smp), (dir))
  #define SAMPLECUBE_LOD(name, smp, dir, lod) textureLod(samplerCube(name, smp), (dir), (lod))
  // ---------- 阴影（VK：平行光两槽 select；点光 2d-array + texelFetch）----------
  #define DECL_SHADOW2D(slot)   layout(binding = SB_SHADOW) uniform texture2D t_shadow; \
                                layout(binding = 2) uniform sampler s_shadow; \
                                layout(binding = SB_SHADOW2) uniform texture2D t_shadow2; \
                                layout(binding = 11) uniform sampler s_shadow2
  #define DECL_SHADOWCUBE(face) layout(binding = SB_SHADOW_ARR) uniform texture2DArray t_shadow_arr; \
                                layout(binding = SB_ARR_SMP) uniform sampler s_shadow_arr
  #define SAMPLE_SHADOW2D(slot, uv) \
      (((slot) < 0.5) ? texture(sampler2D(t_shadow, s_shadow), (uv)).r \
                      : texture(sampler2D(t_shadow2, s_shadow2), (uv)).r)
  // wgpu 的帧缓冲行序是自上而下（阴影 pass 的 NDC +y 落在第 0 行），
  // 与 GL 的 uv 原点相反，故 VK 分支在 texelFetch 前翻转 y（旧手写 WGSL 的 uv.y=1-uv.y）。
  #define SAMPLE_SHADOWCUBE(slot, face, uv) \
      texelFetch(sampler2DArray(t_shadow_arr, s_shadow_arr), \
                 ivec3(ivec2(vec2((uv).x, 1.0 - (uv).y) \
                             * vec2(textureSize(t_shadow_arr, 0).xy)), (face)), 0).r
  // ---------- 阴影坐标约定（两后端窗口深度/纹理行序不同）----------
  // lp = light.ortho * vec4(world_pos,1)。matlib.mat4_ortho 的 clip.z 已经是 [0,1]：
  //   GL  : OpenGL 把 clip.z 再映射一次 -> 窗口深度 0.5 + 0.5*clipz；
  //   VK  : wgpu 的 NDC z 就是 [0,1] -> 窗口深度 = clipz。
  // uv.y：VK 帧缓冲自上而下 -> 取 1-y（与纹理行序对应）。
  #define SHADOW_UV(lp)    vec2((lp).x / (lp).w * 0.5 + 0.5, 0.5 - (lp).y / (lp).w * 0.5)
  #define SHADOW_DEPTH(lp) ((lp).z / (lp).w)
#else
  // ---------- 绑定号（GL：纹理单元 / UBO 绑定点）----------
  #define SB_SCENE 0
  #define SB_BUCKET 1
  #define SB_ALBEDO 0
  #define SB_SAMPLER 0
  #define SB_NORMAL 1
  #define SB_ENV 2
  #define SB_SHADOW 0
  #define SB_SHADOW2 0
  #define SB_SHADOW_ARR 0
  #define SB_ARR_SMP 0
  #define LOOM_VERTEX_ID gl_VertexID
  #define DECL_FRAG_UV           layout(location = 0) in vec2 v_uv;
  #define LOOM_FRAG_UV           v_uv
  #define LOOM_FRAG_OUT out vec4 frag_color;
  #define DECL_TEX2D(name, b)    layout(binding = b) uniform sampler2D name
  #define DECL_SAMPLER(name, b)  /* GL：组合采样器自带采样状态 */
  #define DECL_SAMPLER_B(name, b) /* GL：同上 */
  #define SAMPLE2D(tex, smp, uv) texture(tex, (uv))
  #define SAMPLE2D_LOD(tex, smp, uv, lod) textureLod(tex, (uv), (lod))
  #define DECL_TEXCUBE(name, b)  layout(binding = b) uniform samplerCube name
  #define SAMPLECUBE(name, smp, dir) texture(name, (dir))
  #define SAMPLECUBE_LOD(name, smp, dir, lod) textureLod(name, (dir), (lod))
  #define DECL_SHADOW2D(slot)   uniform sampler2D u_shadow_maps[16]
  #define DECL_SHADOWCUBE(face) /* GL：点光 6 面在 u_shadow_maps 里 */
  #define SAMPLE_SHADOW2D(slot, uv)        texelFetch(u_shadow_maps[(slot)], ivec2((uv) * vec2(textureSize(u_shadow_maps[(slot)], 0))), 0).r
  #define SAMPLE_SHADOWCUBE(slot, face, uv) \
      texelFetch(u_shadow_maps[(slot) + (face)], ivec2((uv) * vec2(textureSize(u_shadow_maps[(slot) + (face)], 0))), 0).r
  // GL：窗口深度重映射；uv 原点在左下，与阴影贴图一致，不翻转。
  #define SHADOW_UV(lp)    vec2((lp).xy * 0.5 + 0.5)
  #define SHADOW_DEPTH(lp) ((lp).z / (lp).w * 0.5 + 0.5)
#endif

#endif // LOOM_SHADER_COMPAT_GLSL
