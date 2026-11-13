// loom_shader_compat.glsl — T3 单源兼容层（2026-11-11；2026-11-13 补 samplerless 扩展 + 阴影坐标约定；
// 2026-11-13 T3b：补天空 / 阴影 pass / mip 三块剩余手写的宏）
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
  // 天空 pass 独立 bind group：0=UBO(SkyC) 1=textureCube 2=sampler
  #define SB_SKY_UBO 0
  #define SB_SKY_CUBE 1
  #define SB_SKY_SAMP 2
  // 阴影 pass 独立 bind group：0=UBO(ShadowU)
  #define SB_SHADOW_U 0
  // ---------- UI（屏幕 UI + world Canvas 共用一对 shader）----------
  // VK：一个 std140 UBO：vec4(屏幕像素宽高 + 模式, z>0.5 = world Canvas) + mat4 VP。
  // 屏幕 UI 管线写 [w,h,0,0]；world 管线写 [0,0,1,0] 并在 16 字节处写 VP。
  #define SB_UI_UBO 0
  #define SB_UI_TEX 1
  #define SB_UI_SAMP 2
  #define DECL_UI_VERT_UNI layout(std140, binding = SB_UI_UBO) uniform UIC { \
        vec4 ui_screen; mat4 ui_vp; } ui;
  #define UI_IS_WORLD (ui.ui_screen.z > 0.5)
  // 顶点输入统一 36B：pos3 + uv2 + color4（屏幕 UI 的 z 恒 0，world 的 color 恒白）
  #define DECL_UI_INPUT layout(location = 0) in vec3 ui_pos; \
                        layout(location = 1) in vec2 ui_uv; \
                        layout(location = 2) in vec4 ui_color;
  #define UI_SCREEN_CLIP vec4(ui_pos.x / ui.ui_screen.x * 2.0 - 1.0, \
                              1.0 - ui_pos.y / ui.ui_screen.y * 2.0, 0.0, 1.0)
  #define UI_WORLD_CLIP  (ui.ui_vp * vec4(ui_pos, 1.0))
  #define DECL_UI_VARYINGS layout(location = 0) out vec2 v_uv; \
                           layout(location = 1) out vec4 v_color;
  #define UI_EMIT_VARYINGS v_uv = ui_uv; v_color = ui_color;
  #define DECL_UI_FRAG_UNI   /* VK：UI 参数只在顶点阶段被引用 */
  #define DECL_UI_FRAG_IN layout(location = 0) in vec2 v_uv; \
                          layout(location = 1) in vec4 v_color;
  #define UI_TINT v_color

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
  // ---------- 天空（VK：SkyC 一次进 UBO；全屏三角无顶点输入）----------
  // 落盘布局与 vk_renderer._draw_sky 的 28 f32 逐字节一致：
  //   inv_vp[0..16) cam[16..20) tint[20..24) size[24..28)
  #define DECL_SKY_UNI layout(std140, binding = SB_SKY_UBO) uniform SkyC { \
        mat4 sky_inv_vp; vec4 sky_cam; vec4 sky_tint; vec4 sky_size; } sky;
  #define SKY_INV_VP sky.sky_inv_vp
  #define SKY_CAM    sky.sky_cam.xyz
  #define SKY_TINT   sky.sky_tint.xyz
  #define DECL_SKY_INPUT        /* VK：全屏三角，无顶点属性 */
  #define SKY_VERT_NDC (vec2((gl_VertexIndex == 1) ? 3.0 : -1.0, \
                             (gl_VertexIndex == 2) ? 3.0 : -1.0))
  // ---------- 阴影 pass（VK：ShadowU 一次进 UBO；深度写进 r32float 颜色附件）----------
  // 落盘布局与 vk_renderer._exec_shadow_maps 的 24 f32 逐字节一致：
  //   vp[0..16) pos[16..20) params[20..24)（x=模式, y=far）
  #define DECL_SHADOW_UNI layout(std140, binding = SB_SHADOW_U) uniform ShadowU { \
        mat4 sh_vp; vec4 sh_pos; vec4 sh_params; } sh;
  #define DECL_SHADOW_PARAMS    /* VK：参数已在上面的 ShadowU 里 */
  #define SHADOW_VP          sh.sh_vp
  #define SHADOW_IS_DISTANCE (sh.sh_params.x > 0.5)
  #define SHADOW_LIGHT_POS   sh.sh_pos.xyz
  #define SHADOW_FAR         max(sh.sh_params.y, 1e-3)
  // wgpu 的 NDC z 就是 [0,1]，窗口深度 = clipz（GL 是 0.5*clipz+0.5，但那边
  // gl_FragCoord.z 本来就已经是窗口深度 —— 两边都用 gl_FragCoord.z 即同一语义）。
  #define SHADOW_STAGE_DEPTH (gl_FragCoord.z)
  #define SHADOW_STORE_DEPTH(d) frag_color = vec4((d), 0.0, 0.0, 1.0)
  #define DECL_SHADOW_OUT layout(location = 0) out vec4 frag_color;
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
  #define SB_SKY_UBO 0
  #define SB_SKY_CUBE 0
  #define SB_SKY_SAMP 0
  #define SB_SHADOW_U 0
  // ---------- UI（屏幕 UI + world Canvas 共用一对 shader）----------
  // GL：两套原 uniform 名全部保留（loom_hud / engine / loom_render 调用点一行未改）；
  //     u_mode 选择路径：world 程序创建时设 1，HUD 程序默认 0。
  #define SB_UI_UBO 0
  #define SB_UI_TEX 0
  #define SB_UI_SAMP 0
  #define DECL_UI_VERT_UNI uniform vec2 u_origin; \
                           uniform vec2 u_size; \
                           uniform mat4 u_view_proj; \
                           uniform int u_mode;
  #define UI_IS_WORLD (u_mode != 0)
  #define DECL_UI_INPUT in vec2 in_pos; in vec3 in_world_pos; in vec2 in_uv;
  // 屏幕 UI 沿用 GL 既有算式（u_origin/u_size 由 loom_hud/engine 按 NDC 写入），逐字未改。
  #define UI_SCREEN_CLIP vec4(in_pos * u_size + u_origin, 0.0, 1.0)
  #define UI_WORLD_CLIP  (u_view_proj * vec4(in_world_pos, 1.0))
  #define DECL_UI_VARYINGS out vec2 v_uv;
  #define UI_EMIT_VARYINGS v_uv = in_uv;
  #define DECL_UI_FRAG_UNI uniform int u_mode; uniform vec4 u_color;
  #define DECL_UI_FRAG_IN in vec2 v_uv;
  // world Canvas 乘 1.0（浮点 x*1.0 == x，逐位不变）；HUD 用 u_color。
  #define UI_TINT ((u_mode != 0) ? vec4(1.0) : u_color)

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
  // ---------- 天空（GL：独立 uniform + 0..1 quad 顶点属性）----------
  #define DECL_SKY_UNI uniform mat4 u_inv_view_proj; \
                       uniform vec3 u_camera_pos; \
                       uniform vec3 u_skybox_tint;
  #define SKY_INV_VP u_inv_view_proj
  #define SKY_CAM    u_camera_pos
  #define SKY_TINT   u_skybox_tint
  #define DECL_SKY_INPUT in vec2 in_pos;
  #define SKY_VERT_NDC ((in_pos) * 2.0 - 1.0)
  // ---------- 阴影 pass（GL：独立 uniform；深度写 gl_FragDepth）----------
  #define DECL_SHADOW_UNI uniform mat4 u_light_vp;
  #define DECL_SHADOW_PARAMS uniform int u_depth_kind; \
                             uniform vec3 u_light_pos; \
                             uniform float u_light_far;
  #define SHADOW_VP          u_light_vp
  #define SHADOW_IS_DISTANCE (u_depth_kind > 0)
  #define SHADOW_LIGHT_POS   u_light_pos
  #define SHADOW_FAR         u_light_far
  #define SHADOW_STAGE_DEPTH (gl_FragCoord.z)
  #define SHADOW_STORE_DEPTH(d) gl_FragDepth = (d)
  #define DECL_SHADOW_OUT        /* GL：阴影 pass 只有深度附件，不写颜色 */
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
