# -*- coding: utf-8 -*-
"""
vk_renderer.py — Vulkan 渲染后端 (wgpu-py, 2026-08-29 性能调优 P4F: 实例化批绘制)

★ 驱动死锁规避 (1050Ti/582.66/wgpu 0.32 实测):
  多 bind group 组合 / fragment 数组动态索引 → 驱动死锁 (整机卡死)。
  P4F 形态: 单 bind group (场景块 uniform + 阴影纹理 + 采样器);
  矩阵走 instance 步进顶点缓冲 (世界矩阵 160B/实例), 4 灯固定展开无数组;
  阴影 R32Float 手动比较; 法线逆转置 CPU 预算; front_face='cw' (引擎绕序)。

里程碑: P4 = 按 mesh 分桶实例化 (50 球 → 2 draw / 1 bind group);
shader 双源 (Vk=WGSL; GL=现 GLSL)。矩阵全部行主序 tobytes() 直传。

★ 阴影容量 (2026-11-07 修复): 2 张平行光阴影贴图 + 1 套点光 6 面。
  即 VK 后端**同时最多 2 盏平行光投影 + 1 盏点/聚光投影**真正生效:
    · 平行光: 两张 1024² 贴图 (纹理 binding 1/10, 采样器 binding 2/11),
      阴影 pass 按槽位各烘一张; 主着色器用 LightX.params.w 传槽位号
      (0/1, -1=无贴图), 分支选 t_shadow / t_shadow2 采样 —— **不做动态纹理
      数组索引** (本机驱动对数组动态索引有死锁史);
    · 第 3 盏及以后的平行光: 不分配槽位 (params.w=-1) -> 该灯无阴影 (不再
      拿别人的贴图做 PCF), _pack_light_vps 打印一次警告, 不崩、不静默;
    · 点光/聚光: 仍只收录第一盏 (第二盏 -> 该灯无阴影), 同样打印一次警告。
  两张贴图仍走**同一个完整 bind group** (只加 binding 10/11, 不新增组),
  保持本项目 "同一时刻只绑一个完整 bind group" 的硬约束 (见上)。
"""
import json
import math
from collections import OrderedDict

import numpy as np

from loom_shaders import CLEAR_COLOR_RGBA   # 2026-11-09 Q2=A
# 2026-11-09 C5=B: 上屏健康计数**唯一实现**在 loom_render.PresentHealth（阈值不复制）
try:
    from loom_render import PresentHealth as _PresentHealth
except Exception as _ph_e:      # 不能静默: 退化成"没有降级判据"必须可见
    _PresentHealth = None
    print('[vk] 上屏健康计数器不可用 (%r) -> present_health/should_fallback_remote 将报错'
          % (_ph_e,))

import wgpu

from matlib import (mat4_view_yaw_pitch, mat4_view_forward, mat4_perspective,
                    mat4_ortho, mat4_rotation)
from vk_ui import (VkUIEngine, VkUIPipeline,   # 2026-11-06 Canvas UI / HUD (独立管线)
                   VkWorldUIPipeline)          # 2026-11-06 R1 world Canvas

_VERT_BYTES = 12 * 4          # 每顶点 48 字节: pos3f + normal3f + color4f + uv2f
_VERT_FLOATS = 12
_INST_BYTES = 160             # 每实例 40 f32: world(16)+nm(16)+satvec(4)+color(4, 覆盖标志)
_R_WORLD = 0                  # loc3-6  (mat4)
_R_NM = 16                    # loc7-10 (mat4)
_R_SAT = 32                   # loc11   (vec4, .x=sat)
_R_COLOR = 36                 # loc12   (vec4, rgb+覆標w)
_INST_SHADOW_BYTES = 64       # 阴影实例: world@光VP (mat4)
_SCENE_CAP = 64               # 空余实例槽 (扩容单位)
_SHADOW_RES = 1024
_SHADOW_SLOTS = 2             # 2026-11-07: 平行光阴影贴图张数 (槽 0/1)
_POINT_SHADOW_RES = 512   # 与 GL _shadow_point_res 一致
_POINT_FAR = 30.0          # 与 GL _shadow_point_far 一致

# 场景块 f32 布局 (SceneC): mvp[0..16) cam[16..20) cnt[20..24) L0..L3[24..)
_R_MVP = 0
_R_CAM = 16
_R_CNT = 20
_R_CNT2 = 24          # 2026-11-06 对齐 GL: 8 盏灯 (原 4 盏)
_R_MISC = 28          # x = 全局 PBR 开关
_R_L0 = 32
_LIGHT_F32 = 40       # +extra vec4 (cos_inner, cos_outer, range, pad)
_SCENE_FLOATS = _R_L0 + 8 * _LIGHT_F32   # 352

# ---------------- WGSL: 主 pass ----------------
_MAIN_VERT = """
struct SceneC {
    mvp: mat4x4<f32>,         // 公共 V@P
    cam: vec4f,               // xyz view_pos, w ambient_scale
    cnt: vec4f,               // 灯 0-3 激活标志 (固定展开)
    cnt2: vec4f,              // 灯 4-7 (2026-11-06 对齐 GL: 8 盏)
    misc: vec4f,              // x = 全局 PBR 开关 (GL u_pbr_mode 同语义)
    l0: LightX, l1: LightX, l2: LightX, l3: LightX,
    l4: LightX, l5: LightX, l6: LightX, l7: LightX,
}
struct LightX {
    kind: f32, mode: f32, shape: f32, shadow: f32,
    color: vec4f,             // rgb + intensity (a)
    dir: vec4f,
    pos: vec4f,
    ortho: mat4x4<f32>,
    params: vec4f,            // shadow_bias, shadow_res, beam size, pad
    extra: vec4f,             // cos(inner), cos(outer), range, pad
}
@group(0) @binding(0) var<uniform> sc: SceneC;
struct VSOut {
    @builtin(position) pos: vec4f,
    @location(0) color: vec4f,
    @location(1) n: vec3f,
    @location(2) wpos: vec3f,
    @location(3) sat: f32,
    @location(4) matv: vec4f,   // (sat, metallic, roughness, pbr_flag)
    @location(5) uv: vec2f,
}
// 实例缓冲每实例 160B (40 f32): world(loc3-6) + nm(loc7-10) + satv(loc11) + color(loc12)
// ★naga 0.32 顶点属性仅接受标量/向量 (mat 声明被拒, 标量属性触发 inter-stage
// 误检) → 矩阵必须列拆 vec4, 全程无标量. 颜色 = 每实例覆盖标志 (w>0.5 用实例色,
// 否则网格原生面颜色) —— 桶共享几何但各物体颜色可不同.
@vertex fn vs(
    @location(0) p: vec3f,
    @location(1) n: vec3f,
    @location(2) c: vec4f,
    @location(3) c0: vec4f, @location(4) c1: vec4f,
    @location(5) c2: vec4f, @location(6) c3: vec4f,
    @location(7) n0: vec4f, @location(8) n1: vec4f,
    @location(9) n2: vec4f, @location(10) n3: vec4f,
    @location(11) isatv: vec4f,
    @location(12) icol: vec4f,
    @location(13) uv0: vec2f,
) -> VSOut {
    var o: VSOut;
    let iw = mat4x4<f32>(c0, c1, c2, c3);        // 列主序解释 = 数学行主序 (同引擎)
    let inm = mat4x4<f32>(n0, n1, n2, n3);
    o.n = (inm * vec4f(n, 0.0)).xyz;             // 逆转置 (CPU 预算, 非等比缩放正确)
    o.wpos = (iw * vec4f(p, 1.0)).xyz;
    o.pos = sc.mvp * iw * vec4f(p, 1.0);
    o.color = select(c, vec4f(icol.rgb, c.a), icol.w > 0.5);  // 实例色覆盖 (网格原生面颜色)
    o.sat = isatv.x;
    o.matv = isatv;             // 2026-11-06 PBR: y=metallic z=roughness w=pbr
    o.uv = uv0;
    return o;
}
"""

_MAIN_FRAG = """
// SceneC / LightX 定义见 _MAIN_VERT (同一 module); fragment 引用 sc 公共块
@group(0) @binding(1) var t_shadow: texture_2d<f32>;
@group(0) @binding(2) var s_shadow: sampler;
// 2026-11-06 点光阴影 (对齐 GL): 6 面深度存 r32float cube, 方向采样
// 2026-11-06 点光阴影: 6 层 2d-array + textureLoad 手算面/UV (避开 cube 约定差异)
@group(0) @binding(3) var t_shadow_arr: texture_2d_array<f32>;
// 2026-11-06 贴图 (与 GL u_albedo 同语义): 无贴图时绑 1x1 白
@group(0) @binding(5) var t_albedo: texture_2d<f32>;
@group(0) @binding(6) var s_albedo: sampler;
// 2026-11-06 法线贴图 (与 GL u_normal_map 同式); 无贴图时绑 1x1 平直法线(0.5,0.5,1)
@group(0) @binding(7) var t_normal: texture_2d<f32>;
// 2026-11-06: 每桶参数 x = 是否有法线贴图 (GL u_has_normal_map 同语义)
@group(0) @binding(8) var<uniform> bkt: vec4f;
// 2026-11-06 PBR 环境反射 (与 GL u_env 同式); y=has_env z=env_max_lod
@group(0) @binding(9) var t_env: texture_cube<f32>;
// 2026-11-07 第 2 张平行光阴影贴图 (binding 10/11): 第 2 盏投影平行光专用.
// 主着色器按 LightX.params.w 的槽位号分支选贴图, 不做动态纹理数组索引.
@group(0) @binding(10) var t_shadow2: texture_2d<f32>;
@group(0) @binding(11) var s_shadow2: sampler;

fn pcf(uv: vec2f, depth: f32, bias: f32, res: f32) -> f32 {
    let ts = 1.0 / res;
    var sh = 0.0;
    for (var y = -1; y <= 1; y++) {
        for (var x = -1; x <= 1; x++) {
            let d = textureSample(t_shadow, s_shadow,
                                  uv + vec2f(f32(x), f32(y)) * ts).x;
            if (d >= depth - bias) { sh += 1.0; }
        }
    }
    return sh / 9.0;
}

// 槽位 1 的 PCF: 与 pcf 逐式相同, 只换贴图/采样器 (WGSL 不支持动态选纹理).
fn pcf2(uv: vec2f, depth: f32, bias: f32, res: f32) -> f32 {
    let ts = 1.0 / res;
    var sh = 0.0;
    for (var y = -1; y <= 1; y++) {
        for (var x = -1; x <= 1; x++) {
            let d = textureSample(t_shadow2, s_shadow2,
                                  uv + vec2f(f32(x), f32(y)) * ts).x;
            if (d >= depth - bias) { sh += 1.0; }
        }
    }
    return sh / 9.0;
}

// ---------------- 2026-11-06 PBR (与 GL _FRAG_SRC 逐式一致) ----------------
fn _d_ggx(N: vec3f, H: vec3f, rough: f32) -> f32 {
    let a = rough * rough;
    let a2 = a * a;
    let NdotH = max(dot(N, H), 0.0);
    let d = NdotH * NdotH * (a2 - 1.0) + 1.0;
    return a2 / max(3.14159265 * d * d, 1e-7);
}
fn _g_smith(N: vec3f, V: vec3f, L: vec3f, rough: f32) -> f32 {
    let r = rough + 1.0;
    let k = (r * r) / 8.0;
    let NdotV = max(dot(N, V), 0.0);
    let NdotL = max(dot(N, L), 0.0);
    let gv = NdotV / (NdotV * (1.0 - k) + k);
    let gl = NdotL / (NdotL * (1.0 - k) + k);
    return gv * gl;
}
fn _f_schlick(cosT: f32, F0: vec3f) -> vec3f {
    return F0 + (1.0 - F0) * pow(clamp(1.0 - cosT, 0.0, 1.0), 5.0);
}
fn pbr_light(N: vec3f, V: vec3f, L: vec3f, radiance: vec3f, albedo: vec3f,
             metal: f32, rough: f32, NdotL: f32) -> vec3f {
    let H = normalize(V + L);
    let F0 = mix(vec3f(0.04), albedo, vec3f(metal));
    let D = _d_ggx(N, H, rough);
    let G = _g_smith(N, V, L, rough);
    let NdotV = max(dot(N, V), 1e-4);
    let F = _f_schlick(max(dot(H, V), 0.0), F0);
    let spec = (D * G * F) / max(4.0 * NdotL * NdotV, 1e-4);
    let kD = (1.0 - F) * (1.0 - metal);
    let diff = kD * albedo / 3.14159265;
    return (diff + spec) * radiance * NdotL;
}

// 单灯双路输出 (Blinn-Phong / PBR), 与 GL 两段累加同式
struct LC { bl: vec3f, pb: vec3f }
fn light_pair(L: LightX, n: vec3f, v: vec3f, wpos: vec3f,
              albedo: vec3f, metal: f32, rough: f32, use_pbr: bool) -> LC {
    var l: vec3f;
    var diff: f32;
    var atten: f32 = 1.0;
    if (L.kind > 0.5) {
        let to_l = L.pos.xyz - wpos;
        let dist = max(length(to_l), 1e-4);
        l = to_l / dist;
        diff = max(dot(n, l), 0.0);
        atten = 1.0 / (1.0 + 0.09 * dist + 0.045 * dist * dist);
        let rng = max(L.extra.z, 1e-3);
        let fade = clamp(1.0 - (dist * dist) / (rng * rng), 0.0, 1.0);
        atten *= fade * fade;
        if (L.kind > 1.5) {
            let spot_dir = normalize(L.dir.xyz);
            let frag_dir = -to_l / dist;
            let cos_theta = dot(frag_dir, spot_dir);
            let inner = L.extra.x;
            let outer = L.extra.y;
            atten *= clamp((cos_theta - outer) / max(inner - outer, 1e-4), 0.0, 1.0);
        }
    } else {
        l = normalize(-L.dir.xyz);
        diff = max(dot(n, l), 0.0);
    }
    let h = normalize(l + v);
    let spec = pow(max(dot(n, h), 0.0), 24.0);
    var sh: f32 = 1.0;
    var g_in_shape: f32 = 1.0;
    if (L.kind < 0.5 && L.mode > 0.5) {
        let lp = L.ortho * vec4f(wpos, 1.0);
        let uv = vec2f(lp.x / lp.w * 0.5 + 0.5, 0.5 - lp.y / lp.w * 0.5);
        var in_shape = 0.0;
        if (uv.x >= 0.0 && uv.x <= 1.0 && uv.y >= 0.0 && uv.y <= 1.0) {
            let xy = uv * 2.0 - 1.0;
            if (L.shape > 0.5) {
                in_shape = select(0.0, 1.0, max(abs(xy.x), abs(xy.y)) <= 1.0);
            } else {
                in_shape = select(0.0, 1.0, length(xy) <= 1.0);
            }
        }
        g_in_shape = in_shape;
        if (in_shape < 0.5) { sh = 0.0; }
    }
    // 点光/聚光阴影: 方向采样 cube 深度 (extra.w = 本灯有点光阴影贴图)
    if (L.kind > 0.5 && L.shadow > 0.5 && L.extra.w > 0.5) {
        let rd = wpos - L.pos.xyz;
        let dist = max(length(rd), 1e-6);
        let adx = abs(rd.x); let ady = abs(rd.y); let adz = abs(rd.z);
        var face: i32 = 0;
        var fc: vec2f = vec2f(0.0);
        if (adx >= ady && adx >= adz) {
            if (rd.x > 0.0) { face = 0; fc = vec2f( rd.z, -rd.y) / rd.x; }
            else            { face = 1; fc = vec2f( rd.z,  rd.y) / rd.x; }
        } else if (ady >= adz) {
            if (rd.y > 0.0) { face = 2; fc = vec2f( rd.x, -rd.z) / rd.y; }
            else            { face = 3; fc = vec2f( rd.x,  rd.z) / rd.y; }
        } else {
            if (rd.z > 0.0) { face = 4; fc = vec2f(-rd.x, -rd.y) / rd.z; }
            else            { face = 5; fc = vec2f(-rd.x,  rd.y) / rd.z; }
        }
        var uv = fc * 0.5 + 0.5;
        uv.y = 1.0 - uv.y;              // wgpu 帧缓冲 y 向下, GL 的 uv 假设 y 向上
        let res: i32 = 512;             // _POINT_SHADOW_RES
        let px = clamp(i32(uv.x * f32(res)), 0, res - 1);
        let py = clamp(i32(uv.y * f32(res)), 0, res - 1);
        let stored = textureLoad(t_shadow_arr, vec2<i32>(px, py), face, 0).x;
        let refd = dist / max(L.params.z, 1e-3);
        sh = select(0.0, 1.0, stored >= refd - L.params.x);
    }
    if (L.shadow > 0.5 && L.kind < 0.5) {
        let lp = L.ortho * vec4f(wpos, 1.0);
        let depth = lp.z / lp.w;
        let uv = vec2f(lp.x / lp.w * 0.5 + 0.5, 0.5 - lp.y / lp.w * 0.5);
        if (uv.x < 0.0 || uv.x > 1.0 || uv.y < 0.0 || uv.y > 1.0) {
            sh = select(1.0, sh, L.mode > 0.5);
        } else if (L.params.w < -0.5) {
            // 第 3 盏及以后: 没有分配阴影贴图槽位 -> 不采样任何图 (不拿错图),
            // 该灯无阴影 (已知限制, CPU 侧 _pack_light_vps 打印一次警告).
            sh = g_in_shape;
        } else {
            // params.w = 槽位号 (0 -> t_shadow, 1 -> t_shadow2): 分支选图,
            // 不做动态纹理数组索引 (本机驱动对数组动态索引有死锁史).
            if (L.params.w < 0.5) {
                sh = pcf(uv, depth, L.params.x, L.params.y) * g_in_shape;
            } else {
                sh = pcf2(uv, depth, L.params.x, L.params.y) * g_in_shape;
            }
        }
    }
    let radiance = L.color.rgb * L.color.a * atten * sh;
    var out: LC;
    out.bl = L.color.rgb * L.color.a * (0.60 * diff + 0.25 * spec) * atten * sh;
    if (use_pbr) {
        out.pb = pbr_light(n, v, l, radiance, albedo, metal, rough, diff);
    } else {
        out.pb = vec3f(0.0);
    }
    return out;
}

@fragment fn fs(in: VSOut) -> @location(0) vec4f {
    var n = normalize(in.n);
    if (bkt.x > 0.5) {
        // 与 GL 一致的导数 TBN: dp/duv 解切线/副切线, Gram-Schmidt 正交化
        let dp1 = dpdx(in.wpos);
        let dp2 = dpdy(in.wpos);
        let duv1 = dpdx(in.uv);
        let duv2 = dpdy(in.uv);
        let det = duv1.x * duv2.y - duv2.x * duv1.y;
        if (abs(det) > 1e-8) {
            var T = normalize((dp1 * duv2.y - dp2 * duv1.y) / det);
            var B = normalize((dp2 * duv1.x - dp1 * duv2.x) / det);
            T = normalize(T - n * dot(n, T));
            B = cross(n, T);
            let nm = textureSample(t_normal, s_albedo, in.uv).rgb * 2.0 - 1.0;
            n = normalize(mat3x3<f32>(T, B, n) * nm);
        }
    }
    let v = normalize(sc.cam.xyz - in.wpos);
    let hemi = clamp(0.5 + 0.5 * n.y, 0.0, 1.0);
    let amb = (0.02 + 0.28 * hemi) * sc.cam.w;
    // 2026-11-06 贴图: 实测**不翻转 v** 与 GL 一致 (翻转后 MAE 0.0004 -> 0.0058),
    // 因为上传的 _rgba 行序与 GL 上传同源, 两侧约定恰好抵销。
    let base = in.color.rgb * textureSample(t_albedo, s_albedo, in.uv).rgb;
    let use_pbr = (sc.misc.x > 0.5) && (in.matv.w > 0.5);
    let metal = clamp(in.matv.y, 0.0, 1.0);
    let rough = clamp(in.matv.z, 0.04, 1.0);
    var acc = vec3f(0.0);
    var pbr_acc = vec3f(0.0);
    var r: LC;
    if (sc.cnt.x > 0.5) { r = light_pair(sc.l0, n, v, in.wpos, base, metal, rough, use_pbr); acc += r.bl; pbr_acc += r.pb; }
    if (sc.cnt.y > 0.5) { r = light_pair(sc.l1, n, v, in.wpos, base, metal, rough, use_pbr); acc += r.bl; pbr_acc += r.pb; }
    if (sc.cnt.z > 0.5) { r = light_pair(sc.l2, n, v, in.wpos, base, metal, rough, use_pbr); acc += r.bl; pbr_acc += r.pb; }
    if (sc.cnt.w > 0.5) { r = light_pair(sc.l3, n, v, in.wpos, base, metal, rough, use_pbr); acc += r.bl; pbr_acc += r.pb; }
    if (sc.cnt2.x > 0.5) { r = light_pair(sc.l4, n, v, in.wpos, base, metal, rough, use_pbr); acc += r.bl; pbr_acc += r.pb; }
    if (sc.cnt2.y > 0.5) { r = light_pair(sc.l5, n, v, in.wpos, base, metal, rough, use_pbr); acc += r.bl; pbr_acc += r.pb; }
    if (sc.cnt2.z > 0.5) { r = light_pair(sc.l6, n, v, in.wpos, base, metal, rough, use_pbr); acc += r.bl; pbr_acc += r.pb; }
    if (sc.cnt2.w > 0.5) { r = light_pair(sc.l7, n, v, in.wpos, base, metal, rough, use_pbr); acc += r.bl; pbr_acc += r.pb; }
    let rim = 0.12 * pow(1.0 - max(dot(n, v), 0.0), 3.0);
    var col: vec3f;
    if (use_pbr) {
        if (bkt.y > 0.5) {
            let F0e = mix(vec3f(0.04), base, vec3f(metal));
            let R = reflect(-v, n);
            let spec_env = textureSampleLevel(t_env, s_albedo, R,
                                              rough * bkt.z).rgb * F0e;
            let diff_env = textureSampleLevel(t_env, s_albedo, n, 0.0).rgb
                           * base * (1.0 - metal);
            col = pbr_acc + diff_env + spec_env + vec3f(rim);
        } else {
            let amb_pbr = base * amb * (1.0 - metal);
            col = pbr_acc + amb_pbr + vec3f(rim);
        }
    } else {
        col = base * (amb + acc) + vec3f(rim);
    }
    col = pow(clamp(col, vec3f(0.0), vec3f(1.0)), vec3f(1.0 / 2.2));
    let lum = dot(col, vec3f(0.299, 0.587, 0.114));
    col = mix(vec3f(lum), col, in.sat);
    return vec4f(col, 1.0);
}
"""

# ---------------- WGSL: 阴影 pass (实例矩阵, R32Float) ----------------
_SHADOW_VERT = """
// 2026-11-06 点光阴影: 平行光走"实例=world@光VP + 模式0(投影深度)",
// 点光走"实例=world + u_vp=面VP + 模式1(到光源距离/far)"。
struct SU {
    vp: mat4x4<f32>,
    pos: vec4f,
    params: vec4f,      // x=模式(0 投影深度 / 1 距离), y=far
}
@group(0) @binding(0) var<uniform> su: SU;

struct SVOut {
    @builtin(position) pos: vec4f,
    @location(0) wpos: vec3f,
}

@vertex fn vs(
    @location(0) p: vec3f,
    @location(3) c0: vec4f, @location(4) c1: vec4f,
    @location(5) c2: vec4f, @location(6) c3: vec4f,
) -> SVOut {
    let m = mat4x4<f32>(c0, c1, c2, c3);
    let w = m * vec4f(p, 1.0);
    var o: SVOut;
    o.pos = su.vp * w;
    o.wpos = w.xyz;
    return o;
}

@fragment fn fs(in: SVOut) -> @location(0) vec4f {
    var d: f32;
    if (su.params.x > 0.5) {
        d = clamp(length(in.wpos - su.pos.xyz) / max(su.params.y, 1e-3), 0.0, 1.0);
    } else {
        d = in.pos.z / in.pos.w;
    }
    return vec4f(d, 0.0, 0.0, 1.0);
}
"""

# ---------------- WGSL: P1 逃生舱 ----------------
_MAIN_P1_VERT = """
struct PerObject { mvp: mat4x4<f32>, sat: f32, }
@group(0) @binding(0) var<uniform> per: PerObject;
struct VSOut { @builtin(position) pos: vec4f, @location(0) color: vec4f, }
@vertex fn vs(@location(0) p: vec3f, @location(1) n: vec3f,
              @location(2) c: vec4f) -> VSOut {
    var o: VSOut;
    o.pos = per.mvp * vec4f(p, 1.0);
    o.color = c;
    return o;
}
"""
_MAIN_P1_FRAG = """
@fragment fn fs(in: VSOut) -> @location(0) vec4f {
    let lum = dot(in.color.rgb, vec3f(0.299, 0.587, 0.114));
    return vec4f(mix(vec3f(lum), in.color.rgb, per.sat), in.color.a);
}
"""

_SKY_WGSL = """
// 2026-11-06 天空盒: 全屏三角 + 反投影采样 cubemap (与 GL _SKY_FRAG 同式)
struct SkyC {
    inv_vp: mat4x4<f32>,
    cam: vec4f,
    tint: vec4f,
    size: vec4f,      // x=宽 y=高
}
@group(0) @binding(0) var<uniform> sky: SkyC;
@group(0) @binding(1) var t_cube: texture_cube<f32>;
@group(0) @binding(2) var s_cube: sampler;

@vertex fn vs(@builtin(vertex_index) vi: u32) -> @builtin(position) vec4f {
    var p = vec2f(-1.0, -1.0);
    if (vi == 1u) { p = vec2f(3.0, -1.0); }
    if (vi == 2u) { p = vec2f(-1.0, 3.0); }
    return vec4f(p, 1.0, 1.0);
}

@fragment fn fs(@builtin(position) frag: vec4f) -> @location(0) vec4f {
    // 与 GL 一致: clip=(ndc.x, ndc.y, 1, 1), world = clip @ inv(VP)
    let ndc = vec2f(frag.x / max(sky.size.x, 1.0) * 2.0 - 1.0,
                    1.0 - frag.y / max(sky.size.y, 1.0) * 2.0);
    let clip = vec4f(ndc.x, ndc.y, 1.0, 1.0);
    let world = sky.inv_vp * clip;
    let dir = normalize(world.xyz / max(world.w, 1e-6) - sky.cam.xyz);
    let col = textureSample(t_cube, s_cube, dir).rgb * sky.tint.rgb;
    return vec4f(col, 1.0);
}
"""



_POST_WGSL = """
// 2026-11-10 阶段 2B2: bloom + tonemap（与 GL loom_post_gl 的 4 段逐公式一致）
// 目标里存的是 gamma 编码值 -> 统一先 pow(2.2) 反线性，最后 tonemap 再编码。
struct P { p0: vec4f, p1: vec4f }
@group(0) @binding(0) var t0: texture_2d<f32>;
@group(0) @binding(1) var t1: texture_2d<f32>;
@group(0) @binding(2) var samp: sampler;
@group(0) @binding(3) var<uniform> par: P;

// WGSL 的属性只能挂在结构体成员上，不能直接写在函数参数上（naga 实测报错）。
struct FragIn { @builtin(position) pos: vec4f }

@vertex fn vs(@builtin(vertex_index) vi: u32) -> @builtin(position) vec4f {
    var p = vec2f(-1.0, -1.0);
    if (vi == 1u) { p = vec2f(3.0, -1.0); }
    if (vi == 2u) { p = vec2f(-1.0, 3.0); }
    return vec4f(p, 0.0, 1.0);
}

fn uv_of(p: vec2f) -> vec2f {
    // 与天空 shader 同一约定: 像素坐标(y 向下) 除以当前目标尺寸得 uv
    return p / max(par.p1.xy, vec2f(1.0, 1.0));
}

fn to_linear(c: vec3f) -> vec3f {
    return pow(max(c, vec3f(0.0, 0.0, 0.0)), vec3f(2.2, 2.2, 2.2));
}

@fragment fn fs_bright(inp: FragIn) -> @location(0) vec4f {
    // p0.z = exposure（与 tonemap 同一曝光；阈值按曝光后线性亮度）
    let c = to_linear(textureSample(t0, samp, uv_of(inp.pos.xy)).rgb) * par.p0.z;
    let l = dot(c, vec3f(0.2126, 0.7152, 0.0722));
    let w = smoothstep(par.p0.x, par.p0.x + max(par.p0.y, 1e-4), l);
    return vec4f(c * w, 1.0);
}

@fragment fn fs_down(inp: FragIn) -> @location(0) vec4f {
    let uv = uv_of(inp.pos.xy);
    let o = par.p1.zw;
    let c = textureSample(t0, samp, uv + vec2f(-o.x, -o.y)).rgb
          + textureSample(t0, samp, uv + vec2f( o.x, -o.y)).rgb
          + textureSample(t0, samp, uv + vec2f(-o.x,  o.y)).rgb
          + textureSample(t0, samp, uv + vec2f( o.x,  o.y)).rgb;
    return vec4f(c * 0.25, 1.0);
}

@fragment fn fs_up(inp: FragIn) -> @location(0) vec4f {
    return vec4f(textureSample(t0, samp, uv_of(inp.pos.xy)).rgb, 1.0);
}

@fragment fn fs_tonemap(inp: FragIn) -> @location(0) vec4f {
    let uv = uv_of(inp.pos.xy);
    var c = to_linear(textureSample(t0, samp, uv).rgb);
    c += textureSample(t1, samp, uv).rgb * par.p0.z;
    c *= par.p0.w;
    c = c / (1.0 + c);
    return vec4f(pow(c, vec3f(1.0 / 2.2, 1.0 / 2.2, 1.0 / 2.2)), 1.0);
}
"""


def bucket_layout(groups):
    """把实例行按桶重排成连续区间 (裁决 A: 单缓冲 + 按桶重排).

    groups: {桶键: [按 vis 原序的实例行号, ...]}, dict 插入序 = 桶首次出现序
    (与原实现 "同一个 dict 的 items() 决定桶序" 一致, draw 次序不变)。

    返回 (order, starts, identity):
      order    np.intp[N] —— 重排后缓冲第 r 行 = 原 vis[order[r]] 那一行
      starts   {桶键: 该桶在重排缓冲中的起始行} —— 即 draw(..., first_instance)
      identity order 恰为 0..N-1 (无交错, 调用方可以直接复用原 staging 视图,
               省一次 gather)

    ★ 为什么必须有: 实例是按 vis 原序写进缓冲的, 而 draw 只能画连续区间。
     同桶物体被别的桶隔开时 (同网格 A、别的网格 B、同网格 A), 旧实现直接
     用 idxs[0] 当 first_instance 再画 len(idxs) 个 —— 于是第二个 A 画成了
     B 的实例行 (既漏画 A, 又把 B 的矩阵/颜色套在 A 的几何上, 串形)。
    """
    total = 0
    for v in groups.values():
        total += len(v)
    order = np.fromiter((i for idxs in groups.values() for i in idxs),
                        dtype=np.intp, count=total)
    starts = {}
    off = 0
    for k, idxs in groups.items():
        starts[k] = off
        off += len(idxs)
    identity = bool(np.array_equal(order, np.arange(total, dtype=np.intp)))
    return order, starts, identity


def sampler_desc(tex):
    """Texture 导入设置 (wrap / filter_mode) -> wgpu 采样器参数.

    与 GL 侧 loom_texture._build 的映射同义 (两后端同一份语义):
      wrap   : clamp -> clamp-to-edge; repeat / mirror -> repeat
               (GL 只有 repeat_x/y 布尔, 无 MIRRORED_REPEAT, mirror 同样回落 repeat)
      filter : point     -> nearest + mipmap nearest
               bilinear  -> linear  + mipmap nearest
               trilinear -> linear  + mipmap linear
    tex 为 None (无贴图/占位) 时返回默认 repeat + trilinear, 与旧单采样器逐字段相同
    (所以无贴图场景的采样行为/像素结果不变)。
    """
    wrap = getattr(tex, 'wrap', 'repeat') if tex is not None else 'repeat'
    if wrap == 'clamp':
        au = av = 'clamp-to-edge'
    else:                       # repeat / mirror(回退 repeat) / 任何未知值
        au = av = 'repeat'
    fmode = getattr(tex, 'filter_mode', 'trilinear') if tex is not None else 'trilinear'
    if fmode == 'point':
        mag, mnf, mip = 'nearest', 'nearest', 'nearest'
    elif fmode == 'bilinear':
        mag, mnf, mip = 'linear', 'linear', 'nearest'
    else:                       # trilinear (含未知值回退)
        mag, mnf, mip = 'linear', 'linear', 'linear'
    return {'mag_filter': mag, 'min_filter': mnf, 'mipmap_filter': mip,
            'address_mode_u': au, 'address_mode_v': av}


def _sampler_key(desc):
    """采样器参数字典 -> 可哈希键 (供 _tex_samplers 复用)."""
    return (desc['mag_filter'], desc['min_filter'], desc['mipmap_filter'],
            desc['address_mode_u'], desc['address_mode_v'])


def flatten_mesh(mesh, normal_mode='flat', color=None):
    """展平网格为 (3F,10) float32 (与 engine._build_gpu 同语义)."""
    verts = np.asarray(mesh.vertices, dtype=np.float32)
    faces = np.asarray(mesh.faces, dtype=np.int32)
    tri = verts[faces]
    pos = tri.reshape(-1, 3)
    mesh_normals = getattr(mesh, 'normals', None)
    if mesh_normals is not None and len(mesh_normals) == len(verts):
        vn = np.asarray(mesh_normals, dtype=np.float32)
        norm = vn[faces].reshape(-1, 3)
    elif normal_mode == 'vertex':
        ln = np.linalg.norm(verts, axis=1, keepdims=True)
        ln = np.where(ln == 0, 1.0, ln)
        norm = (verts / ln)[faces].reshape(-1, 3)
    else:
        p0, p1, p2 = tri[:, 0], tri[:, 1], tri[:, 2]
        nrm = np.cross(p1 - p0, p2 - p0)
        ln = np.linalg.norm(nrm, axis=1, keepdims=True)
        ln = np.where(ln == 0, 1.0, ln)
        norm = np.repeat(nrm / ln, 3, axis=0)
    face_colors = mesh.face_colors
    if color is not None:
        face_colors = [color] * len(face_colors)
    colors = np.zeros((len(face_colors), 4), dtype=np.float32)
    for i, c in enumerate(face_colors):
        colors[i] = (int(c[1:3], 16) / 255.0, int(c[3:5], 16) / 255.0,
                     int(c[5:7], 16) / 255.0, 1.0)
    col = np.repeat(colors, 3, axis=0)
    # 2026-11-06 贴图: UV 展平 (与 GL _flatten_mesh 同语义; 无 uvs -> 全零)
    mesh_uvs = getattr(mesh, 'uvs', None)
    if mesh_uvs is not None and len(mesh_uvs) == len(verts):
        uv_arr = np.asarray(mesh_uvs, dtype=np.float32)
        uv = uv_arr[faces].reshape(-1, 2)
    else:
        uv = np.zeros((len(pos), 2), dtype=np.float32)
    return np.concatenate([pos, norm, col, uv], axis=1)


def world_matrices(models, interp=None):
    """批量世界矩阵 (与 engine.compute_world_matrices 同数学: S@R@T 沿父链, 行主序).
    分离批2: interp 非 None → S/T/R 吃 InterpState.render_pose() 插值平面
    (f64→f32 cast 与原 np.array(dtype=f32) 同一 RNE 舍入, 逐位同); None = 原逻辑位姿."""
    n = len(models)
    if n == 0:
        return np.empty((0, 4, 4), dtype=np.float32)
    id2i = {id(m): i for i, m in enumerate(models)}
    parent = np.full(n, -1, dtype=np.int64)
    for i, m in enumerate(models):
        if m.parent is not None:
            parent[i] = id2i.get(id(m.parent), -1)
    depth = np.zeros(n, dtype=np.int64)
    for i in range(n):
        d, cur = 0, i
        while parent[cur] >= 0 and d < n:
            cur, d = int(parent[cur]), d + 1
        depth[i] = d
    if interp is not None:
        # 方案二 (2026-09-05): 外推模式由 driver 侧 _extrap_this_frame 决定
        # (落点帧回退插值), 走同 render_pose 公式 a'=1+alpha 封顶 1.5
        mode = getattr(interp, '_extrap_mode', 0)
        pos, rot, scl = interp.render_pose(interp.alpha, models, mode=mode)
        if pos is None:
            interp = None
    S = np.zeros((n, 4, 4), dtype=np.float32)
    T = np.zeros((n, 4, 4), dtype=np.float32)
    T[:, 0, 0] = T[:, 1, 1] = T[:, 2, 2] = T[:, 3, 3] = 1.0
    if interp is not None:
        S[:, 0, 0] = scl[:, 0]
        S[:, 1, 1] = scl[:, 1]
        S[:, 2, 2] = scl[:, 2]
        S[:, 3, 3] = 1.0
        T[:, 3, 0] = pos[:, 0]
        T[:, 3, 1] = pos[:, 1]
        T[:, 3, 2] = pos[:, 2]
        rx = np.array(rot[:, 0], dtype=np.float32)
        ry = np.array(rot[:, 1], dtype=np.float32)
        rz = np.array(rot[:, 2], dtype=np.float32)
    else:
        S[:, 0, 0] = [m.scale[0] for m in models]
        S[:, 1, 1] = [m.scale[1] for m in models]
        S[:, 2, 2] = [m.scale[2] for m in models]
        S[:, 3, 3] = 1.0
        T[:, 3, 0] = [m.position.x for m in models]
        T[:, 3, 1] = [m.position.y for m in models]
        T[:, 3, 2] = [m.position.z for m in models]
        rx = np.array([m.rotation.x for m in models], dtype=np.float32)
        ry = np.array([m.rotation.y for m in models], dtype=np.float32)
        rz = np.array([m.rotation.z for m in models], dtype=np.float32)
    cx, sx = np.cos(rx), np.sin(rx)
    cy, sy = np.cos(ry), np.sin(ry)
    cz, sz = np.cos(rz), np.sin(rz)
    Rx = np.zeros((n, 4, 4), dtype=np.float32)
    Rx[:, 1, 1] = cx; Rx[:, 1, 2] = sx
    Rx[:, 2, 1] = -sx; Rx[:, 2, 2] = cx
    Rx[:, 0, 0] = Rx[:, 3, 3] = 1.0
    Ry = np.zeros((n, 4, 4), dtype=np.float32)
    Ry[:, 0, 0] = cy; Ry[:, 0, 2] = -sy
    Ry[:, 2, 0] = sy; Ry[:, 2, 2] = cy
    Ry[:, 1, 1] = Ry[:, 3, 3] = 1.0
    Rz = np.zeros((n, 4, 4), dtype=np.float32)
    Rz[:, 0, 0] = cz; Rz[:, 0, 1] = sz
    Rz[:, 1, 0] = -sz; Rz[:, 1, 1] = cz
    Rz[:, 2, 2] = Rz[:, 3, 3] = 1.0
    local = S @ Rx @ Ry @ Rz @ T
    world = np.empty_like(local)
    for d in range(int(depth.max()) + 1):
        idx = np.where(depth == d)[0]
        if d == 0:
            world[idx] = local[idx]
        else:
            world[idx] = local[idx] @ world[parent[idx]]
    return world


def orbit_camera(target, distance, yaw, pitch):
    """轨道相机位置 (与 scene_driver.SceneDriver.camera_pos 同公式; 兼容旧探针)."""
    ez = (math.sin(yaw) * math.cos(pitch),
          math.sin(pitch),
          math.cos(yaw) * math.cos(pitch))
    return (target[0] - distance * ez[0],
            target[1] - distance * ez[1],
            target[2] - distance * ez[2])


class VkRenderer:
    """Vulkan 渲染器 (wgpu-py) P4F: 单组场景块 + 实例化批绘制 (mesh 分桶)."""

    def __init__(self, device, present_format, stage='p4', pbr_enabled=None):
        self.device = device
        self.format = present_format
        self.stage = stage
        # 2026-11-07 PBR 全局开关: 构造参数 pbr_enabled 优先, 缺省继承 GL 同名语义
        # (engine._pbr_enabled, 缺省 True)。读写统一落到 _pbr_enabled,
        # 见 pbr_enabled property。
        self._pbr_enabled = (True if pbr_enabled is None else bool(pbr_enabled))
        # 2026-11-10 阶段 2B2: 后处理（HDR + bloom + tonemap）。LOOM_POST=0 时保持旧路径。
        from loom_post import post_enabled
        self._post_on = post_enabled()
        self._frame_fmt = self.format        # 当前帧主链目标格式（post 开=rgba16float）
        self._post_t = None                  # HDR / 半 / 四分之一 目标（按尺寸懒建）
        self._post_pipes = None              # bloom/tonemap 管线（固定 rgba16float 内部）
        self._post_layout = None
        self._post_samples = None            # 采样器（linear clamp）
        self._build_pipelines()
        self._depth = None          # (w, h, view)
        self._scene_buf = None      # 场景块 uniform (公共)
        self._inst_buf = None       # 实例缓冲 (160B/实例)
        self._inst_sha_buf = None   # 阴影实例缓冲 (64B/实例, 槽 0)
        self._inst_sha_buf2 = None  # 2026-11-07 槽 1 阴影实例缓冲
        # 组1 (2026-08-30): CPU 侧 staging 持久复用 (消每帧 np.zeros×2);
        # _ensure_instances 扩容时作废, 下帧按新 cap 重建.
        self._inst_stage = None
        self._inst_sha_stage = None
        self._inst_cap = 0
        self._geo = {}              # mesh 键 -> (vertex_buf, n_verts)
        self._shadow_tex = None
        self._shadow_view = None
        self._shadow_tex2 = None    # 2026-11-07 第 2 张平行光阴影贴图
        self._shadow_view2 = None
        self._shadow_sampler = None
        self._dir_shadow_slots = {}  # 平行光 guid -> 阴影槽位 (0/1)
        self._light_vps = {}
        self._bb_local = {}
        # 2026-11-06 天空盒 (与 GL 对齐): 懒建 pipeline + cube 纹理
        self._sky_pipe = None
        self._sky_group = None
        self._sky_buf = None
        self._sky_tex = None
        self._sky_cube_key = None
        self._sky_sampler = None
        # 2026-11-09 C5=B: 上屏健康（与 GL 共用 loom_render.PresentHealth —— 阈值不复制）
        self._present_health = None      # 惰性建 (见 _present_guard)
        self._present_err_logged = False
        # 2026-11-06 Canvas UI / HUD (与 GL 对齐): 独立管线 + 独立 bind group,
        # 不与其他组混用 (本机驱动对多组组合有死锁史)
        self._ui_pipe = None        # VkUIPipeline (纹理/采样器/白纹理/顶点缓冲)
        self._ui_engine = None      # VkUIEngine (UIManager.draw_all 门面)
        # 2026-11-06 R1 world Canvas: 离屏纹理 -> 世界 quad (带深度测试).
        # _world_targets: id(canvas) -> {canvas, tex, view, group, size}
        self._world_ui_pipe = None
        self._world_targets = {}
        # 2026-11-07 贴图采样器池 (wrap/filter_mode 生效) 与 env cube 缓存
        # (按 guid 键 + 持 cube 引用 + 上限淘汰, 见 _upload_cube_env)
        self._tex_samplers = {}      # 采样器键 -> wgpu sampler (懒建)
        self._env_cache = OrderedDict()

    @property
    def pbr_enabled(self):
        """全局 PBR 开关 (与 GL 的 u_pbr_mode 同语义: True -> 允许材质级 PBR).

        真实开关在 engine._pbr_enabled (设置项 pbr_enabled, ★B7b 排错后门)。
        本属性既是读口也是写口, 且缺省回退 True —— 与 GL loom_render 的
        getattr(self, '_pbr_enabled', True) 完全一致, 因此:
          · VkRenderer(dev, fmt, pbr_enabled=False) 直接关；
          · r.pbr_enabled = False / r._pbr_enabled = False 同样生效；
          · 两者都不设时与其他后端一样默认开启。
        """
        return bool(getattr(self, '_pbr_enabled', True))

    @pbr_enabled.setter
    def pbr_enabled(self, v):
        self._pbr_enabled = bool(v)

    def _build_pipelines(self):
        d = self.device
        if self.stage == 'p1':
            shader = d.create_shader_module(code=_MAIN_P1_VERT + _MAIN_P1_FRAG)
            self._bgl = d.create_bind_group_layout(entries=[
                {'binding': 0, 'visibility': wgpu.ShaderStage.VERTEX
                 | wgpu.ShaderStage.FRAGMENT, 'buffer': {'type': 'uniform'}}])
            self._pipeline = d.create_render_pipeline(
                layout=d.create_pipeline_layout(bind_group_layouts=[self._bgl]),
                vertex=self._vertex_desc(shader, 'vs', inst=None),
                primitive=self._prim(),
                depth_stencil={'format': 'depth32float',
                               'depth_write_enabled': True, 'depth_compare': 'less'},
                fragment={'module': shader, 'entry_point': 'fs',
                          'targets': [{'format': self.format}]})
            return
        shader = d.create_shader_module(code=_MAIN_VERT + _MAIN_FRAG)
        self._bgl = d.create_bind_group_layout(entries=[
            {'binding': 0, 'visibility': wgpu.ShaderStage.VERTEX
             | wgpu.ShaderStage.FRAGMENT, 'buffer': {'type': 'uniform'}},
            {'binding': 1, 'visibility': wgpu.ShaderStage.FRAGMENT,
             'texture': {'sample_type': 'unfilterable-float', 'view_dimension': '2d'}},
            {'binding': 2, 'visibility': wgpu.ShaderStage.FRAGMENT,
             'sampler': {'type': 'non-filtering'}},
            {'binding': 3, 'visibility': wgpu.ShaderStage.FRAGMENT,
             'texture': {'sample_type': 'unfilterable-float',
                         'view_dimension': '2d-array'}},
            {'binding': 5, 'visibility': wgpu.ShaderStage.FRAGMENT,
             'texture': {'sample_type': 'float', 'view_dimension': '2d'}},
            {'binding': 6, 'visibility': wgpu.ShaderStage.FRAGMENT,
             'sampler': {'type': 'filtering'}},
            {'binding': 7, 'visibility': wgpu.ShaderStage.FRAGMENT,
             'texture': {'sample_type': 'float', 'view_dimension': '2d'}},
            {'binding': 8, 'visibility': wgpu.ShaderStage.FRAGMENT,
             'buffer': {'type': 'uniform'}},
            {'binding': 9, 'visibility': wgpu.ShaderStage.FRAGMENT,
             'texture': {'sample_type': 'float', 'view_dimension': 'cube'}},
            # 2026-11-07 第 2 张平行光阴影贴图 (仍属同一个完整 bind group)
            {'binding': 10, 'visibility': wgpu.ShaderStage.FRAGMENT,
             'texture': {'sample_type': 'unfilterable-float', 'view_dimension': '2d'}},
            {'binding': 11, 'visibility': wgpu.ShaderStage.FRAGMENT,
             'sampler': {'type': 'non-filtering'}}])
        # 主管线: 顶点(48B, pos/normal/color/uv) + 实例(160B: world/nm/sat/color)
        self._pipeline = d.create_render_pipeline(
            layout=d.create_pipeline_layout(bind_group_layouts=[self._bgl]),
            vertex=self._vertex_desc(shader, 'vs', inst=_INST_BYTES, nattr=10),
            primitive=self._prim(),
            depth_stencil={'format': 'depth32float',
                           'depth_write_enabled': True, 'depth_compare': 'less'},
            fragment={'module': shader, 'entry_point': 'fs',
                      'targets': [{'format': self.format}]})
        # 阴影管线: 顶点(40B) + 实例(64B: world@光VP), R32Float 手动比较
        # 布局 = 空 (shader 无绑定, 矩阵走实例属性)
        shad = d.create_shader_module(code=_SHADOW_VERT)
        # 2026-11-06 点光阴影: 阴影 pass 需要一个 uniform (面VP/光源位置/模式)
        self._shadow_bgl = d.create_bind_group_layout(entries=[
            {'binding': 0, 'visibility': wgpu.ShaderStage.VERTEX
             | wgpu.ShaderStage.FRAGMENT, 'buffer': {'type': 'uniform'}}])
        # 每面一个缓冲: 一次 encoder 里写同一缓冲会被后续写覆盖 (实测 6 面
        # 深度完全相同 -> 点光阴影失效), 故 face 独立。
        self._shadow_bufs = [
            d.create_buffer(size=96,
                            usage=wgpu.BufferUsage.UNIFORM | wgpu.BufferUsage.COPY_DST)
            for _ in range(7)]
        self._shadow_groups = [
            d.create_bind_group(layout=self._shadow_bgl,
                                entries=[{'binding': 0,
                                          'resource': {'buffer': b, 'offset': 0,
                                                       'size': 96}}])
            for b in self._shadow_bufs]
        self._shadow_buf = self._shadow_bufs[0]
        self._shadow_group = self._shadow_groups[0]
        # 2026-11-07: 平行光阴影 2 槽位各一个 uniform 缓冲 (与点光 6 面同理:
        # 同一 encoder 里两趟阴影 pass 写同一缓冲会被后写覆盖)。槽 0 复用
        # _shadow_bufs[0], 槽 1 追加一条; 点光仍占 _shadow_bufs[1..6]。
        self._dir_shadow_bufs = [
            self._shadow_bufs[0],
            d.create_buffer(size=96,
                            usage=wgpu.BufferUsage.UNIFORM | wgpu.BufferUsage.COPY_DST)]
        self._dir_shadow_groups = [
            self._shadow_groups[0],
            d.create_bind_group(layout=self._shadow_bgl,
                                entries=[{'binding': 0,
                                          'resource': {'buffer': self._dir_shadow_bufs[1],
                                                       'offset': 0, 'size': 96}}])]
        self._shadow_pipeline = d.create_render_pipeline(
            layout=d.create_pipeline_layout(bind_group_layouts=[self._shadow_bgl]),
            vertex=self._vertex_desc(shad, 'vs', inst=_INST_SHADOW_BYTES, nattr=4),
            primitive=self._prim(),
            fragment={'module': shad, 'entry_point': 'fs',
                      'targets': [{'format': 'r32float'}]})

    # ---------------- 2026-11-10 阶段 2B2: 后处理（HDR + bloom + tonemap） ----------------
    def _ensure_main_pipe(self, fmt):
        """主链管线按**目标格式**缓存（HDR 化后不能用 self.format 那份）。"""
        if getattr(self, '_main_pipe_fmt', None) == fmt and self._pipeline is not None:
            return
        d = self.device
        if getattr(self, '_pipeline_base', None) is None:
            self._pipeline_base = self._pipeline
            self._main_pipe_fmt = self.format
        if fmt == self.format:
            self._pipeline = self._pipeline_base
        else:
            shader = d.create_shader_module(code=_MAIN_VERT + _MAIN_FRAG)
            self._pipeline = d.create_render_pipeline(
                layout=d.create_pipeline_layout(bind_group_layouts=[self._bgl]),
                vertex=self._vertex_desc(shader, 'vs', inst=_INST_BYTES, nattr=10),
                primitive=self._prim(),
                depth_stencil={'format': 'depth32float',
                               'depth_write_enabled': True, 'depth_compare': 'less'},
                fragment={'module': shader, 'entry_point': 'fs',
                          'targets': [{'format': fmt}]})
        self._main_pipe_fmt = fmt

    def _ensure_post_targets(self, w, h):
        """HDR(全) / half(0.5) / quarter(0.25) 三张 rgba16float 目标（尺寸变化重建）。"""
        if self._post_t is not None and self._post_t['size'] == (w, h):
            return
        d = self.device
        usage = wgpu.TextureUsage.RENDER_ATTACHMENT | wgpu.TextureUsage.TEXTURE_BINDING

        def _mk(tw, th):
            t = d.create_texture(size=(max(1, tw), max(1, th), 1),
                                 format='rgba16float', usage=usage)
            return t, t.create_view()

        hdr, hdr_v = _mk(w, h)
        half, half_v = _mk(w // 2, h // 2)
        quar, quar_v = _mk(w // 4, h // 4)
        self._post_t = {'size': (w, h), 'hdr': hdr, 'hdr_view': hdr_v,
                        'half': half, 'half_view': half_v,
                        'quarter': quar, 'quarter_view': quar_v}

    def _ensure_post_pipes(self):
        if self._post_pipes is not None:
            return
        d = self.device
        sh = d.create_shader_module(code=_POST_WGSL)
        bgl = d.create_bind_group_layout(entries=[
            {'binding': 0, 'visibility': wgpu.ShaderStage.FRAGMENT,
             'texture': {'sample_type': 'float', 'view_dimension': '2d'}},
            {'binding': 1, 'visibility': wgpu.ShaderStage.FRAGMENT,
             'texture': {'sample_type': 'float', 'view_dimension': '2d'}},
            {'binding': 2, 'visibility': wgpu.ShaderStage.FRAGMENT,
             'sampler': {'type': 'filtering'}},
            {'binding': 3, 'visibility': wgpu.ShaderStage.FRAGMENT,
             'buffer': {'type': 'uniform'}},
        ])
        lay = d.create_pipeline_layout(bind_group_layouts=[bgl])

        def _pipe(entry, fmt, blend=None):
            tgt = {'format': fmt}
            if blend is not None:
                tgt['blend'] = blend
            return d.create_render_pipeline(
                layout=lay,
                vertex={'module': sh, 'entry_point': 'vs', 'buffers': []},
                primitive={'topology': 'triangle-list', 'cull_mode': 'none'},
                fragment={'module': sh, 'entry_point': entry, 'targets': [tgt]})

        add = {'color': {'src_factor': 'one', 'dst_factor': 'one',
                         'operation': 'add'},
               'alpha': {'src_factor': 'one', 'dst_factor': 'one',
                         'operation': 'add'}}
        self._post_pipes = {
            'bright': _pipe('fs_bright', 'rgba16float'),
            'down': _pipe('fs_down', 'rgba16float'),
            'up': _pipe('fs_up', 'rgba16float', blend=add),
            'tonemap': _pipe('fs_tonemap', self.format),
        }
        self._post_layout = bgl
        self._post_samples = d.create_sampler(mag_filter='linear', min_filter='linear',
                                              address_mode_u='clamp-to-edge',
                                              address_mode_v='clamp-to-edge')
        # 每个 pass 独立 params 缓冲（同一 encoder 里写同一缓冲会被后写覆盖）
        self._post_bufs = [d.create_buffer(
            size=32, usage=wgpu.BufferUsage.UNIFORM | wgpu.BufferUsage.COPY_DST)
            for _ in range(4)]
        self._post_groups = None

    def _ensure_post_groups(self):
        if self._post_groups is not None:
            return
        d = self.device
        t = self._post_t

        def _grp(v0, v1, buf):
            return d.create_bind_group(layout=self._post_layout, entries=[
                {'binding': 0, 'resource': v0},
                {'binding': 1, 'resource': v1},
                {'binding': 2, 'resource': self._post_samples},
                {'binding': 3, 'resource': {'buffer': buf, 'offset': 0, 'size': 32}},
            ])

        self._post_groups = {
            'bright': _grp(t['hdr_view'], t['hdr_view'], self._post_bufs[0]),
            'down': _grp(t['half_view'], t['half_view'], self._post_bufs[1]),
            'up': _grp(t['quarter_view'], t['quarter_view'], self._post_bufs[2]),
            # 缓冲索引必须与 _record_post 的 rows 顺序一致（bright=0, down=1, tonemap=2）
            'tonemap': _grp(t['hdr_view'], t['quarter_view'], self._post_bufs[2]),
        }

    def _record_post(self, enc, view, w, h):
        """在**同一个 encoder** 里追加 bloom + tonemap（最后一步写交换链 texture）。"""
        import numpy as _np
        from loom_post import params as _params
        p = _params()
        t = self._post_t
        self._ensure_post_pipes()
        self._ensure_post_groups()
        hw, hh = max(1, w // 2), max(1, h // 2)
        qw, qh = max(1, w // 4), max(1, h // 4)
        # params: (thr, knee, strength, exposure) + (target_w, target_h, src_texel_x, src_texel_y)
        rows = [
            ('bright', t['half_view'], (p['threshold'], p['knee'], p['exposure'], 0.0),
             (hw, hh, 0.0, 0.0)),
            ('down', t['quarter_view'], (0.0, 0.0, 0.0, 0.0),
             (qw, qh, 1.0 / hw, 1.0 / hh)),
            # 没有独立 up pass：tonemap 直接双线性上采样 quarter（与 GL 同口径）
            ('tonemap', view, (0.0, 0.0, p['strength'], p['exposure']),
             (w, h, 0.0, 0.0)),
        ]
        for i, (name, target, p0, p1) in enumerate(rows):
            data = _np.array(list(p0) + list(p1), dtype='f4')
            self.device.queue.write_buffer(self._post_bufs[i], 0, data.tobytes())
        for i, (name, target, p0, p1) in enumerate(rows):
            rp = enc.begin_render_pass(color_attachments=[{
                'view': target,
                'load_op': wgpu.LoadOp.load if name == 'up' else wgpu.LoadOp.clear,
                'clear_value': (0.0, 0.0, 0.0, 1.0),
                'store_op': wgpu.StoreOp.store}])
            rp.set_pipeline(self._post_pipes[name])
            rp.set_bind_group(0, self._post_groups[name], [], 0, 1)
            rp.draw(3, 1, 0, 0)
            rp.end()

    def _prim(self):
        return {'topology': 'triangle-list', 'cull_mode': 'back',
                'front_face': 'cw'}     # 引擎网格绕序 (ccw 会剔除 plane)

    def _vertex_desc(self, shader, entry, inst, nattr=12):
        bufs = [{'array_stride': _VERT_BYTES, 'step_mode': 'vertex',
                 'attributes': [
                     {'shader_location': 0, 'offset': 0, 'format': 'float32x3'},
                     {'shader_location': 1, 'offset': 12, 'format': 'float32x3'},
                     {'shader_location': 2, 'offset': 24, 'format': 'float32x4'},
                     # 2026-11-06 贴图: UV (location 13, 避开实例属性 3..12)
                     {'shader_location': 13, 'offset': 40, 'format': 'float32x2'}]}]
        if inst is not None:
            # 属性数 = shader 声明的 vec4 个数 (主 pass 12 / 阴影 4); 多余的会
            # 与 shader 失配致验证错误或读取错位
            bufs.append({'array_stride': inst, 'step_mode': 'instance',
                         'attributes': [{'shader_location': 3 + k, 'offset': k * 16,
                                         'format': 'float32x4'}
                                        for k in range(nattr)]})
        return {'module': shader, 'entry_point': entry, 'buffers': bufs}

    # ---------------- 资源懒建 ----------------
    def _ensure_geo_data(self, key, mesh, normal_mode):
        """桶几何懒算+缓存 (每帧只做一次 flatten; 缓存后命零开销)."""
        ent = self._geo.get(key)
        if ent is not None:
            return ent
        data = flatten_mesh(mesh, normal_mode)
        buf = self.device.create_buffer(
            size=int(data.nbytes),
            usage=wgpu.BufferUsage.VERTEX | wgpu.BufferUsage.COPY_DST)
        self.device.queue.write_buffer(buf, 0, data.tobytes())
        ent = (buf, data.shape[0])
        self._geo[key] = ent
        return ent

    def _ensure_scene(self):
        if self._scene_buf is not None:
            return
        d = self.device
        self._scene_buf = d.create_buffer(
            size=_SCENE_FLOATS * 4,
            usage=wgpu.BufferUsage.UNIFORM | wgpu.BufferUsage.COPY_DST)
        tex = d.create_texture(
            size=(_SHADOW_RES, _SHADOW_RES, 1),
            usage=wgpu.TextureUsage.RENDER_ATTACHMENT
            | wgpu.TextureUsage.TEXTURE_BINDING,
            format='r32float')
        self._shadow_tex = tex
        self._shadow_view = tex.create_view()
        # 2026-11-07 第 2 张平行光阴影贴图 (与第 1 张同参数; 采样器共用)
        tex2 = d.create_texture(
            size=(_SHADOW_RES, _SHADOW_RES, 1),
            usage=wgpu.TextureUsage.RENDER_ATTACHMENT
            | wgpu.TextureUsage.TEXTURE_BINDING,
            format='r32float')
        self._shadow_tex2 = tex2
        self._shadow_view2 = tex2.create_view()
        self._shadow_sampler = d.create_sampler(
            mag_filter='nearest', min_filter='nearest')
        # 点光阴影: 6 层 r32float (存 length/far), cube 视图供方向采样
        ptex = d.create_texture(
            size=(_POINT_SHADOW_RES, _POINT_SHADOW_RES, 6),
            dimension='2d', format='r32float',
            usage=wgpu.TextureUsage.RENDER_ATTACHMENT
            | wgpu.TextureUsage.TEXTURE_BINDING
            | wgpu.TextureUsage.COPY_SRC)   # COPY_SRC: 诊断探针可读回深度
        self._point_shadow_tex = ptex
        self._point_face_views = [
            ptex.create_view(base_array_layer=i, array_layer_count=1)
            for i in range(6)]
        self._point_arr_view = ptex.create_view(dimension='2d-array')
        self._point_sampler = d.create_sampler(
            mag_filter='nearest', min_filter='nearest')
        # 2026-11-06 贴图: 1x1 白纹理 (无贴图材质) + 每纹理一个"完整"bind group
        # (同一时刻只绑一组, 不做多组组合 —— 规避本项目驱动多 bind group 死锁史)
        self._tex_sampler = d.create_sampler(
            mag_filter='linear', min_filter='linear', mipmap_filter='linear',
            address_mode_u='repeat', address_mode_v='repeat')
        # 2026-11-07 采样器池: 默认参数 (无贴图 / 默认导入设置) 直接复用上面
        # 那一个实例 -> 老场景的采样器对象、字节、bind group 全不变;
        # 只有显式设了 wrap=clamp / filter_mode=point|bilinear 的贴图才新建。
        self._tex_samplers = {_sampler_key(sampler_desc(None)): self._tex_sampler}
        self._white_tex = d.create_texture(
            size=(1, 1, 1), format='rgba8unorm',
            usage=wgpu.TextureUsage.TEXTURE_BINDING | wgpu.TextureUsage.COPY_DST)
        d.queue.write_texture({'texture': self._white_tex}, bytes([255] * 4),
                              {'bytes_per_row': 4, 'rows_per_image': 1}, (1, 1, 1))
        self._white_view = self._white_tex.create_view()
        # 平直法线 (0,0,1) 编码: (128,128,255) —— 无法线贴图时采样=恒等
        self._flat_nrm_tex = d.create_texture(
            size=(1, 1, 1), format='rgba8unorm',
            usage=wgpu.TextureUsage.TEXTURE_BINDING | wgpu.TextureUsage.COPY_DST)
        d.queue.write_texture({'texture': self._flat_nrm_tex},
                              bytes([128, 128, 255, 255]),
                              {'bytes_per_row': 4, 'rows_per_image': 1}, (1, 1, 1))
        self._flat_nrm_view = self._flat_nrm_tex.create_view()
        # 无 env 时的占位 cube (1x1 六面黑)
        self._empty_env_tex = d.create_texture(
            size=(1, 1, 6), dimension='2d', format='rgba8unorm',
            usage=wgpu.TextureUsage.TEXTURE_BINDING | wgpu.TextureUsage.COPY_DST)
        for _i in range(6):
            d.queue.write_texture({'texture': self._empty_env_tex, 'origin': (0, 0, _i)},
                                  bytes([0, 0, 0, 255]),
                                  {'bytes_per_row': 4, 'rows_per_image': 1}, (1, 1, 1))
        self._empty_env_view = self._empty_env_tex.create_view(dimension='cube')
        self._bkt_default = d.create_buffer(
            size=16, usage=wgpu.BufferUsage.UNIFORM | wgpu.BufferUsage.COPY_DST)
        d.queue.write_buffer(self._bkt_default, 0,
                             __import__('numpy').zeros(4, dtype='f4').tobytes())
        self._tex_groups = {}
        self._bkt_bufs = {}
        self._tex_cache = {}
        self._scene_group = d.create_bind_group(
            layout=self._bgl, entries=[
                {'binding': 0, 'resource': {'buffer': self._scene_buf,
                                            'offset': 0,
                                            'size': _SCENE_FLOATS * 4}},
                {'binding': 1, 'resource': self._shadow_view},
                {'binding': 2, 'resource': self._shadow_sampler},
                {'binding': 3, 'resource': self._point_arr_view},
                {'binding': 5, 'resource': self._white_view},
                {'binding': 6, 'resource': self._tex_sampler},
                {'binding': 7, 'resource': self._flat_nrm_view},
                {'binding': 8, 'resource': {'buffer': self._bkt_default,
                                            'offset': 0, 'size': 16}},
                {'binding': 9, 'resource': self._empty_env_view},
                {'binding': 10, 'resource': self._shadow_view2},
                {'binding': 11, 'resource': self._shadow_sampler}])

    # ---------------- 2026-11-06 天空盒 (对齐 GL A1+B1) ----------------
    def _ensure_sky(self, cube):
        """懒建天空盒 pipeline/bind group/cube 纹理 (cube 变化才重建)."""
        d = self.device
        key = (id(cube), getattr(cube, 'guid', None), getattr(cube, 'size', 0),
               getattr(self, '_frame_fmt', self.format))
        if self._sky_pipe is not None and self._sky_cube_key == key:
            return True
        faces = getattr(cube, '_faces', None)
        if not faces:
            return False
        h, w = faces[0].shape[0], faces[0].shape[1]
        if self._sky_pipe is None:
            shader = d.create_shader_module(code=_SKY_WGSL)
            bgl = d.create_bind_group_layout(entries=[
                {'binding': 0, 'visibility': wgpu.ShaderStage.VERTEX | wgpu.ShaderStage.FRAGMENT,
                 'buffer': {'type': 'uniform'}},
                {'binding': 1, 'visibility': wgpu.ShaderStage.FRAGMENT,
                 'texture': {'sample_type': 'float', 'view_dimension': 'cube'}},
                {'binding': 2, 'visibility': wgpu.ShaderStage.FRAGMENT,
                 'sampler': {'type': 'filtering'}}])
            self._sky_pipe = d.create_render_pipeline(
                layout=d.create_pipeline_layout(bind_group_layouts=[bgl]),
                vertex={'module': shader, 'entry_point': 'vs', 'buffers': []},
                primitive={'topology': 'triangle-list', 'cull_mode': 'none',
                           'front_face': 'cw'},
                depth_stencil={'format': 'depth32float', 'depth_write_enabled': False,
                               'depth_compare': 'always'},
                fragment={'module': shader, 'entry_point': 'fs',
                          'targets': [{'format': getattr(self, '_frame_fmt', self.format)}]})
            self._sky_bgl = bgl
            # SkyC: inv_vp 64B + cam 16B + tint 16B + size 16B = 112B
            self._sky_buf = d.create_buffer(
                size=112, usage=wgpu.BufferUsage.UNIFORM | wgpu.BufferUsage.COPY_DST)
            self._sky_sampler = d.create_sampler(
                mag_filter='linear', min_filter='linear', address_mode_u='clamp-to-edge',
                address_mode_v='clamp-to-edge')
        # wgpu: cube 纹理 = 2D 纹理 + 6 层 (dimension 必须 '2d', view 时再转 cube)
        tex = d.create_texture(
            size=(w, h, 6), format='rgba8unorm', dimension='2d',
            usage=wgpu.TextureUsage.TEXTURE_BINDING | wgpu.TextureUsage.COPY_DST)
        for i in range(6):
            f = faces[i]
            arr = np.ascontiguousarray(f, dtype=np.uint8)
            d.queue.write_texture(
                {'texture': tex, 'mip_level': 0, 'origin': (0, 0, i)},
                arr.tobytes(), {'bytes_per_row': w * 4, 'rows_per_image': h},
                (w, h, 1))
        self._sky_tex = tex
        self._sky_group = d.create_bind_group(layout=self._sky_bgl, entries=[
            {'binding': 0, 'resource': {'buffer': self._sky_buf, 'offset': 0, 'size': 112}},
            {'binding': 1, 'resource': tex.create_view(dimension='cube')},
            {'binding': 2, 'resource': self._sky_sampler}])
        self._sky_cube_key = key
        return True

    # ---------------- 2026-11-09 C5=B: 上屏健康 (与 GL 同语义) ----------------
    def _present_guard(self):
        """惰性建共享计数器（唯一实现在 loom_render.PresentHealth）。"""
        if self._present_health is None:
            if _PresentHealth is None:
                raise RuntimeError('上屏健康计数器不可用 (loom_render.PresentHealth 导入失败)')
            self._present_health = _PresentHealth()
        return self._present_health

    def present_health(self):
        """上屏健康快照（GL 同名字段/同语义）。"""
        return self._present_guard().snapshot()

    def should_fallback_remote(self, threshold=None):
        """连续上屏失败达阈值 -> 建议改走离屏回读（GL 同判据/同阈值）。"""
        return self._present_guard().should_fallback(threshold)

    def _draw_sky(self, ctx, rp, vp, camera_pos, cube, w, h, tint=None, engine=None):
        # 2026-11-09 A5=A: 与 GL 统一错误模型 —— 无效 cubemap 拒绝绘制、告警一次、
        # 绝不把 IndexError 之类逃逸到 vk_player 的渲染循环。
        try:
            _ok, _why = cube.validate()
        except Exception as e:
            _ok, _why = False, repr(e)
        if not _ok:
            if engine is not None and hasattr(engine, '_skybox_valid'):
                engine._skybox_valid, engine._skybox_error = False, _why
            if not getattr(self, '_sky_invalid_logged', False):
                self._sky_invalid_logged = True
                print('[vk] skybox 无效 (%s) -> 不绘制（本局只报一次）' % (_why,))
            return False
        if not self._ensure_sky(cube):
            return False
        try:
            inv = np.linalg.inv(np.asarray(vp, dtype=np.float64)).astype(np.float32)
        except Exception:
            return False
        buf = np.zeros(28, dtype=np.float32)
        buf[0:16] = inv.reshape(16)
        buf[16:19] = (camera_pos[0], camera_pos[1], camera_pos[2])
        buf[19] = 1.0
        # 2026-11-09 P-06: tint 的唯一来源是引擎的 _skybox_tint（旧实现读 renderer 上的
        # skybox_tint，而 GL 写的是 engine._skybox_tint -> VK 侧 tint 永远不生效）。
        if tint is None:
            tint = getattr(self, 'skybox_tint', (1.0, 1.0, 1.0))
        buf[20:23] = tint
        buf[24] = float(w)
        buf[25] = float(h)
        self.device.queue.write_buffer(self._sky_buf, 0, buf.tobytes())
        rp.set_pipeline(self._sky_pipe)
        rp.set_bind_group(0, self._sky_group, [], 0, 1)
        rp.draw(3, 1, 0, 0)
        return True

    # ---------------- 2026-11-06 Canvas UI / HUD ----------------
    def _ensure_ui(self, w, h):
        """懒建 UI 管线 + 门面 (单 pipeline / 单 bind group / 单纹理)."""
        if self._ui_pipe is None:
            self._ui_pipe = VkUIPipeline(self.device, self.format)
            self._ui_engine = VkUIEngine(self._ui_pipe)
        self._ui_pipe.set_screen(w, h)
        return self._ui_engine

    def draw_ui(self, view, w, h, ui=None, hud_lines=None, hud=None, engine=None):
        """在已存在颜色附件 view 上叠加 HUD + Canvas UI (独立 pass, load_op=load).

        ui        : loom_ui.UIManager (driver.ui) —— 画所有 screen Canvas 元素树
        hud_lines : [str] HUD 文本行 (左上角, 语义同 loom_hud._draw_hud)
        hud       : dict 可选样式覆盖 {'x','y','line_h','color'}
        返回提交的 draw call 数 (0 = 无内容, 不产生额外 pass).
        """
        if ui is None and not hud_lines:
            return 0
        eng = self._ensure_ui(w, h)
        eng.begin_frame(w, h)
        try:
            if hud_lines:
                st = hud or {}
                eng.draw_hud_lines(hud_lines,
                                   x=st.get('x', 10), y=st.get('y', 10),
                                   line_h=st.get('line_h', 24),
                                   color=st.get('color', (255, 255, 255)))
            if ui is not None:
                # 2026-11-07 修复(P0): 必须传**引擎/驱动**, 不是 UIManager 本体。
                # loom_ui.UIManager.draw_all(engine) 会把 engine 记进 _ACTIVE_ENGINE,
                # 事件派发 (_fire_binding) 靠它找脚本实例。旧代码传的是 ui 自己 ->
                # _ACTIVE_ENGINE 变成 UIManager -> "找不到脚本实例: sid=..." ->
                # 打包版(VK) 里所有 UI 按钮点击**全部无效**(通关面板按钮点不动)。
                eng.draw_all(ui, script_host=engine)
        except Exception as e:
            print('[vk] UI 记录失败 (跳过本帧 UI):', repr(e))
            return 0
        if not eng.has_content():
            return 0
        d = self.device
        enc = d.create_command_encoder()
        rp = enc.begin_render_pass(color_attachments=[{
            'view': view,
            'load_op': wgpu.LoadOp.load,
            'store_op': wgpu.StoreOp.store}])
        n = eng.submit(rp)
        rp.end()
        d.queue.submit([enc.finish()])
        return n


    # ---------------- 2026-11-06 R1: world Canvas ----------------
    def _ensure_world_ui(self):
        """懒建 world quad 管线 (独立于屏幕 UI 管线)."""
        fmt = getattr(self, '_frame_fmt', self.format)
        if self._world_ui_pipe is None or getattr(self, '_world_ui_fmt', None) != fmt:
            self._world_ui_pipe = VkWorldUIPipeline(
                self.device, fmt, 'depth32float')
            self._world_ui_fmt = fmt
        return self._world_ui_pipe

    @staticmethod
    def _world_canvases(ui):
        """挑出可绘制的 world Canvas (GL 同判据: canvas_type='world' 且 target 有效)."""
        if ui is None:
            return []
        out = []
        for c in (getattr(ui, 'canvases', None) or []):
            if getattr(c, 'canvas_type', 'screen') != 'world':
                continue
            if getattr(c, 'target', None) is None:
                continue
            out.append(c)
        return out

    def _ensure_world_target(self, canvas, w, h):
        """每个 world Canvas 一张离屏 RGBA 纹理 + bind group (尺寸变化时重建)."""
        key = id(canvas)
        ent = self._world_targets.get(key)
        if ent is not None and ent['canvas'] is canvas and ent['size'] == (w, h):
            return ent
        pipe = self._ensure_world_ui()
        if ent is not None:
            try:
                ent['tex'].destroy()
            except Exception:
                pass
            self._world_targets.pop(key, None)
        tex = self.device.create_texture(
            size=(max(1, w), max(1, h), 1), format=self.format,
            usage=wgpu.TextureUsage.RENDER_ATTACHMENT
            | wgpu.TextureUsage.TEXTURE_BINDING
            | wgpu.TextureUsage.COPY_SRC)
        view = tex.create_view()
        ent = {'canvas': canvas, 'tex': tex, 'view': view,
               'group': pipe.group_for(view), 'size': (w, h)}
        self._world_targets[key] = ent
        return ent

    def _prune_world_targets(self, alive):
        for key in list(self._world_targets):
            if key in alive:
                continue
            ent = self._world_targets.pop(key, None)
            if ent is None:
                continue
            try:
                ent['tex'].destroy()
            except Exception:
                pass

    def render_world_canvases(self, ui, screen_w, screen_h, models=None):
        """把每个 world Canvas 的元素树离屏渲染到自己的纹理.

        与 GL loom_render._draw_world_canvases 的第一步同语义:
        透明底 + 同一份 UI 元素绘制逻辑 (UIManager._draw_elem) + 独立 pass.
        返回 [(canvas, target)]; 空 = 无 world Canvas (零额外 pass).

        models 非空时补一次 target 二次绑定: SceneDriver.load_from_data 只调
        sceneio._apply_ui, 没有调 _link_ui_targets (GL scene_from_dict 末尾会调),
        所以 Vk 侧 canvas.target 仍是 None + _pending_target_id. 这里按 guid 懒绑,
        与 sceneio._link_ui_targets 完全同语义 (只补 driver 缺的那一步).
        """
        if models:
            _idmap = {m.guid: m for m in models if getattr(m, 'guid', None)}
            for c in (getattr(ui, 'canvases', None) or []):
                if getattr(c, 'target', None) is not None:
                    continue
                tid = getattr(c, '_pending_target_id', None)
                if tid:
                    c.target = _idmap.get(tid)
                    if c.target is not None:
                        try:
                            delattr(c, '_pending_target_id')
                        except Exception:
                            pass
        canvases = self._world_canvases(ui)
        if not canvases:
            self._prune_world_targets(set())
            return []
        _draw_elem = getattr(ui, '_draw_elem', None)
        if _draw_elem is None:
            return []
        eng = self._ensure_ui(screen_w, screen_h)
        out = []
        for c in canvases:
            cw = max(1, int(getattr(c, 'width', 1) or 1))
            ch = max(1, int(getattr(c, 'height', 1) or 1))
            try:
                tgt = self._ensure_world_target(c, cw, ch)
            except Exception as e:
                print('[vk] world Canvas 离屏纹理创建失败 (跳过):', repr(e))
                continue
            # 每个 Canvas 单独 encoder+submit: UI 顶点缓冲是共享的, 若把多个
            # Canvas 录进同一 encoder, 后一次 write_buffer 会覆盖前一次的数据
            # (wgpu 在 submit 时应用写入, 不是录制时) -> 全部 Canvas 都读到
            # 最后一份顶点. 独立提交是最小且正确的做法.
            try:
                eng.begin_frame(cw, ch)
                _draw_elem(c.root, eng, (0.0, 0.0, float(cw), float(ch)))
            except Exception as e:
                print('[vk] world Canvas 元素绘制失败 (画空):', repr(e))
                eng.begin_frame(cw, ch)
            self._ui_pipe.set_screen(cw, ch)
            enc = self.device.create_command_encoder()
            rp = enc.begin_render_pass(color_attachments=[{
                'view': tgt['view'],
                'load_op': wgpu.LoadOp.clear,
                'clear_value': (0.0, 0.0, 0.0, 0.0),   # 透明底 (同 GL)
                'store_op': wgpu.StoreOp.store}])
            try:
                eng.submit(rp)
            finally:
                rp.end()
            self.device.queue.submit([enc.finish()])
            out.append((c, tgt))
        self._prune_world_targets({id(c) for c in canvases})
        return out

    @staticmethod
    def _camera_billboard_basis(vp, cam_pos):
        """按 GL 的算法求 billboard 的 right/up.

        GL (_draw_world_canvases) 用 mat4_view_yaw_pitch 的 V[0]/V[1] 行作为
        right/up —— 这里必须**逐行复刻同一取法**, 否则两端 quad 朝向不同.
        没有显式相机角时, 从 VP 反投影出前方向量再还原 yaw/pitch (roll=0);
        A/B 工具会显式传 cam_basis 以避免这层反解误差.
        """
        try:
            inv = np.linalg.inv(np.asarray(vp, dtype=np.float64))
            p = np.array([0.0, 0.0, 1.0, 1.0], dtype=np.float64) @ inv
            w = float(p[3])
            if abs(w) > 1e-12:
                fwd = p[:3] / w - np.asarray(cam_pos, dtype=np.float64)
                n = float(np.linalg.norm(fwd))
                if n > 1e-12:
                    fwd = fwd / n
                    pitch = math.asin(max(-1.0, min(1.0, float(fwd[1]))))
                    yaw = math.atan2(float(fwd[0]), float(fwd[2]))
                    V = mat4_view_yaw_pitch(
                        np, tuple(cam_pos), yaw, pitch, 0.0)
                    return ((float(V[0, 0]), float(V[0, 1]), float(V[0, 2])),
                            (float(V[1, 0]), float(V[1, 1]), float(V[1, 2])))
        except Exception:
            pass
        return (1.0, 0.0, 0.0), (0.0, 1.0, 0.0)

    @staticmethod
    def _target_rotation_basis(target):
        """billboard=False: 跟随 target 的世界旋转 (与 GL world_rotation_matrix 同式).

        GL: R = mat4_rotation(local) @ world_rotation_matrix(parent) (递归右乘),
        再取行 0/1 作为 right/up. 这里沿父链逐级右乘同一公式 (float64).
        """
        def _rot(m):
            return mat4_rotation(np, m.rotation.x, m.rotation.y, m.rotation.z)
        R = _rot(target)
        cur = getattr(target, 'parent', None)
        depth = 0
        while cur is not None and depth < 256:
            R = R @ _rot(cur)
            cur = getattr(cur, 'parent', None)
            depth += 1
        return ((float(R[0, 0]), float(R[0, 1]), float(R[0, 2])),
                (float(R[1, 0]), float(R[1, 1]), float(R[1, 2])))

    def _draw_world_quads(self, rp, items, all_worlds, id2i, vp, cam_pos,
                          cam_basis=None):
        """在主 pass 内画 world Canvas quad (深度测试开, 深度写关)."""
        pipe = self._ensure_world_ui()
        if cam_basis is not None:
            right, up = cam_basis
        else:
            right, up = self._camera_billboard_basis(vp, cam_pos)
        verts = []
        groups = []
        for c, tgt in items:
            target = getattr(c, 'target', None)
            idx = id2i.get(id(target)) if target is not None else None
            if idx is None or all_worlds is None:
                continue
            W = all_worlds[idx]
            cx = float(W[3, 0])
            cy = float(W[3, 1])
            cz = float(W[3, 2])
            if getattr(c, 'billboard', True):
                r_, u_ = right, up
            else:
                try:
                    r_, u_ = self._target_rotation_basis(target)
                except Exception:
                    r_, u_ = right, up
            scale = float(getattr(c, 'world_scale', 0.01))
            cw, ch = tgt['size']
            hw = cw * scale * 0.5
            hh = ch * scale * 0.5

            def corner(rx, ry):
                return (cx + r_[0] * rx + u_[0] * ry,
                        cy + r_[1] * rx + u_[1] * ry,
                        cz + r_[2] * rx + u_[2] * ry)

            TL = corner(-hw, +hh)
            TR = corner(+hw, +hh)
            BL = corner(-hw, -hh)
            BR = corner(+hw, -hh)
            base = len(verts)
            # 三角形 1: TL, BL, TR; 三角形 2: TR, BL, BR (GL TRIANGLE_STRIP
            # TL,BL,TR,BR 的等价展开). uv 上下翻转见 _WORLD_UI_WGSL 注释.
            for p, uv in ((TL, (0.0, 0.0)), (BL, (0.0, 1.0)),
                          (TR, (1.0, 0.0)), (TR, (1.0, 0.0)),
                          (BL, (0.0, 1.0)), (BR, (1.0, 1.0))):
                verts.append((p[0], p[1], p[2], uv[0], uv[1]))
            groups.append((tgt['group'], base))
        if not groups:
            return 0
        pipe.set_vertices(verts)
        pipe.set_view_proj(vp)
        rp.set_pipeline(pipe.pipeline)
        rp.set_vertex_buffer(0, pipe._vbuf)
        for group, base in groups:
            rp.set_bind_group(0, group, [], 0, 1)
            rp.draw(6, 1, base, 0)
        return len(groups)

    _MIP_WGSL = """
@group(0) @binding(0) var t_src: texture_2d<f32>;
@group(0) @binding(1) var s_src: sampler;
@vertex fn vs(@builtin(vertex_index) i: u32) -> @builtin(position) vec4f {
    var p = vec2f(-1.0, -1.0);
    if (i == 1u) { p = vec2f(3.0, -1.0); }
    if (i == 2u) { p = vec2f(-1.0, 3.0); }
    return vec4f(p, 0.0, 1.0);
}
@fragment fn fs(@builtin(position) frag: vec4f) -> @location(0) vec4f {
    // 目标 mip 尺寸 = 源的一半; uv 必须按**目标**像素归一 (按源归一只能采到 1/4 区域)
    let dst = max(vec2f(textureDimensions(t_src, 0)) * 0.5, vec2f(1.0));
    return textureSampleLevel(t_src, s_src, frag.xy / dst, 0.0);
}
"""

    def _ensure_mip_pipeline(self, fmt='rgba8unorm'):
        # 2B2: 目标格式参数化（旧实现写死 rgba8unorm，HDR/半分辨率链会立刻踩到）
        if getattr(self, '_mip_pipe', None) is not None and \
                getattr(self, '_mip_fmt', None) == fmt:
            return
        d = self.device
        shader = d.create_shader_module(code=self._MIP_WGSL)
        bgl = d.create_bind_group_layout(entries=[
            {'binding': 0, 'visibility': wgpu.ShaderStage.FRAGMENT,
             'texture': {'sample_type': 'float', 'view_dimension': '2d'}},
            {'binding': 1, 'visibility': wgpu.ShaderStage.FRAGMENT,
             'sampler': {'type': 'filtering'}}])
        self._mip_bgl = bgl
        self._mip_pipe = d.create_render_pipeline(
            layout=d.create_pipeline_layout(bind_group_layouts=[bgl]),
            vertex={'module': shader, 'entry_point': 'vs', 'buffers': []},
            primitive={'topology': 'triangle-list'},
            fragment={'module': shader, 'entry_point': 'fs',
                      'targets': [{'format': fmt}]})
        self._mip_fmt = fmt
        self._mip_sampler = d.create_sampler(
            mag_filter='linear', min_filter='linear',
            address_mode_u='repeat', address_mode_v='repeat')

    def _gen_mips(self, tex, w, h, levels):
        """逐级 downsample 生成 mip (与 GL 的 mipmap=True 对齐)."""
        self._ensure_mip_pipeline(getattr(tex, 'format', 'rgba8unorm'))
        d = self.device
        for lv in range(1, levels):
            src_view = tex.create_view(base_mip_level=lv - 1, mip_level_count=1)
            dst_view = tex.create_view(base_mip_level=lv, mip_level_count=1)
            grp = d.create_bind_group(layout=self._mip_bgl, entries=[
                {'binding': 0, 'resource': src_view},
                {'binding': 1, 'resource': self._mip_sampler}])
            enc = d.create_command_encoder()
            rp = enc.begin_render_pass(color_attachments=[{
                'view': dst_view, 'load_op': wgpu.LoadOp.clear,
                'clear_value': (0, 0, 0, 0), 'store_op': wgpu.StoreOp.store}])
            rp.set_pipeline(self._mip_pipe)
            rp.set_bind_group(0, grp, [], 0, 1)
            rp.draw(3, 1, 0, 0)
            rp.end()
            d.queue.submit([enc.finish()])

    def _tex_view(self, mat):
        """材质贴图 -> (albedo 视图, albedo guid, 法线视图, 法线 guid).

        2026-11-06 法线贴图: 无法线贴图时回落 1x1 平直法线, 采样恒等
        (等价 GL 的 u_has_normal_map=0 分支)。
        """
        tex = getattr(mat, 'albedo', None) if mat is not None else None
        ntex = getattr(mat, 'normal_map', None) if mat is not None else None
        # 2026-11-07 修复: 法线贴图上传失败时必须回落 _flat_nrm_view (平直法线
        # (128,128,255) = 恒等扰动); 原先统一回落白纹理 (255,255,255), 解码成
        # (1,1,1) 法线向量 -> 整个物体法线被搅乱, 比"没有法线贴图"还错。
        nview = (self._flat_nrm_view if ntex is None
                 else self._upload_tex(ntex, fallback=self._flat_nrm_view))
        if tex is None:
            return (self._white_view, '', nview,
                    '' if ntex is None else getattr(ntex, 'guid', ''))
        return (self._upload_tex(tex), getattr(tex, '_tex_guid', None) or getattr(tex, 'guid', ''),
                nview,
                '' if ntex is None else (getattr(ntex, '_tex_guid', None) or getattr(ntex, 'guid', '')))

    def _upload_tex(self, tex, fallback=None):
        """把 Texture 上传为 GPU 视图 (带 mip), 失败回落 fallback (缺省白纹理).

        fallback 是给法线贴图用的: 法线贴图失败要回落 **平直法线**, 回落白纹理
        会让采样出 (1,1,1) 法线, 整个物体比"无法线贴图"还错。
        """
        guid = getattr(tex, 'guid', '')
        # 缓存键按用途分开: 同一 guid 当 albedo 与当法线贴图, 失败时回落视图
        # 不同, 不能共用一条缓存 (否则谁先失败谁污染另一路)。
        ckey = guid if fallback is None else (guid, id(fallback))
        if ckey in self._tex_cache:
            return self._tex_cache[ckey]
        try:
            rgba = getattr(tex, '_rgba', None)
            # 2026-11-07 死代码清理: 原有一行 tex.ensure_gl(None) if False else None
            # (三元表达式恒不执行, 且 VK 侧不该有 GL 依赖)。_rgba 为 None 时
            # 照旧由下面的 np.ascontiguousarray 抛异常 -> 走回落分支。
            import numpy as _np
            arr = _np.ascontiguousarray(rgba, dtype=_np.uint8)
            h, w = arr.shape[0], arr.shape[1]
            import math as _m
            levels = max(1, int(_m.log2(max(w, h))) + 1) if getattr(tex, 'mipmaps', True) else 1
            t = self.device.create_texture(
                size=(w, h, 1), format='rgba8unorm', mip_level_count=levels,
                usage=wgpu.TextureUsage.TEXTURE_BINDING
                | wgpu.TextureUsage.COPY_DST | wgpu.TextureUsage.RENDER_ATTACHMENT)
            self.device.queue.write_texture(
                {'texture': t}, arr.tobytes(),
                {'bytes_per_row': w * 4, 'rows_per_image': h}, (w, h, 1))
            if levels > 1:
                self._gen_mips(t, w, h, levels)
            v = t.create_view()
        except Exception as e:
            v = self._white_view if fallback is None else fallback
            print("[vk] 贴图上传失败 (回落 %s):" % (
                '白纹理' if fallback is None else '平直法线'), repr(e))
        self._tex_cache[ckey] = v
        return v

    def _sampler_for(self, tex):
        """按贴图导入设置取采样器 (repeat/clamp + nearest/linear), 懒建并复用.

        2026-11-07: 原先所有贴图共用 _tex_sampler (repeat + trilinear),
        Texture.wrap / Texture.filter_mode 在 VK 后端被完全忽略 -> 设了
        clamp 的贴图仍按 repeat 采样 (边缘出鬼影), 设了 point 的像素风贴图
        被线性插值糊掉。这里按 GL 侧同一份映射选采样器。
        """
        desc = sampler_desc(tex)
        key = _sampler_key(desc)
        s = self._tex_samplers.get(key)
        if s is None:
            s = self.device.create_sampler(**desc)
            self._tex_samplers[key] = s
        return s

    def _tex_group(self, view, nview=None, has_nrm=False, env_view=None,
                   env_maxlod=0.0, sampler=None):
        """按 (albedo, normal, has_nrm, env, sampler) 取/建完整 bind group。"""
        nview = nview if nview is not None else self._flat_nrm_view
        sampler = sampler if sampler is not None else self._tex_sampler
        # 注意: has_env 必须在替换成占位 cube **之前**判定, 否则恒为 1
        # (占位 cube 全黑 -> 金属材质变黑, A/B 从 0.0000 劣化到 NCC 0.785)
        has_env = env_view is not None
        env_view = env_view if env_view is not None else self._empty_env_view
        key = (id(view), id(nview), bool(has_nrm), id(env_view), float(env_maxlod),
               id(sampler))
        g = self._tex_groups.get(key)
        if g is not None:
            return g
        d = self.device
        bbuf = self._bkt_bufs.get(key)
        if bbuf is None:
            import numpy as _np
            bbuf = d.create_buffer(size=16,
                                  usage=wgpu.BufferUsage.UNIFORM | wgpu.BufferUsage.COPY_DST)
            _v = _np.zeros(4, dtype=_np.float32)
            _v[0] = 1.0 if has_nrm else 0.0
            _v[1] = 1.0 if has_env else 0.0
            _v[2] = float(env_maxlod)
            d.queue.write_buffer(bbuf, 0, _v.tobytes())
            self._bkt_bufs[key] = bbuf
        g = d.create_bind_group(layout=self._bgl, entries=[
            {'binding': 0, 'resource': {'buffer': self._scene_buf,
                                        'offset': 0, 'size': _SCENE_FLOATS * 4}},
            {'binding': 1, 'resource': self._shadow_view},
            {'binding': 2, 'resource': self._shadow_sampler},
            {'binding': 3, 'resource': self._point_arr_view},
            {'binding': 5, 'resource': view},
            {'binding': 6, 'resource': sampler},
            {'binding': 7, 'resource': nview},
            {'binding': 8, 'resource': {'buffer': bbuf, 'offset': 0, 'size': 16}},
            {'binding': 9, 'resource': env_view},
            {'binding': 10, 'resource': self._shadow_view2},
            {'binding': 11, 'resource': self._shadow_sampler}])
        self._tex_groups[key] = g
        return g

    _ENV_CACHE_MAX = 16      # env cube 缓存上限 (每张 = 6 面 + mip 链, 不设上限会吃显存)

    def _evict_env_cache(self):
        """超上限淘汰最久未用的 env cube (顺带摘 group + 销毁 GPU 纹理)."""
        while len(self._env_cache) > self._ENV_CACHE_MAX:
            _k, item = self._env_cache.popitem(last=False)
            v_old, _ml, _cb, tex_old = item
            # 顺序要紧: bind group 持有 view, 先摘 group 再 destroy 纹理,
            # 否则淘汰只是字典里忘了, 显存与 group 都还在 (原来的泄漏点)。
            for gk in [g for g in self._tex_groups if g[3] == id(v_old)]:
                self._tex_groups.pop(gk, None)
                self._bkt_bufs.pop(gk, None)
            try:
                tex_old.destroy()
            except Exception:
                pass

    def _upload_cube_env(self, cube):
        """材质 env cubemap -> GPU cube 视图 + max_lod (与 GL textureLod 分级对齐)."""
        faces = getattr(cube, '_faces', None)
        if not faces:
            return None, 0.0
        # 2026-11-07 修复: 原来用 id(cube) 当键且不持引用 —— cube 一旦被回收,
        # 新 cube 可能拿到同一 id, 直接命中旧缓存 (env 变别人的环境贴图)。
        # 改按 guid 键 (无 guid 才退回 id, 且此时缓存**持有 cube 引用**, id 不会
        # 被复用), 并加上限淘汰。
        key = getattr(cube, 'guid', '') or ('id', id(cube))
        hit = self._env_cache.get(key)
        if hit is not None:
            self._env_cache.move_to_end(key)
            return hit[0], hit[1]
        d = self.device
        h, w = faces[0].shape[0], faces[0].shape[1]
        import math as _m
        levels = max(1, int(_m.log2(max(w, h))) + 1)
        tex = d.create_texture(
            size=(w, h, 6), dimension='2d', format='rgba8unorm',
            mip_level_count=levels,
            usage=wgpu.TextureUsage.TEXTURE_BINDING | wgpu.TextureUsage.COPY_DST
            | wgpu.TextureUsage.RENDER_ATTACHMENT)
        for i in range(6):
            arr = np.ascontiguousarray(faces[i], dtype=np.uint8)
            d.queue.write_texture({'texture': tex, 'mip_level': 0, 'origin': (0, 0, i)},
                                  arr.tobytes(),
                                  {'bytes_per_row': w * 4, 'rows_per_image': h},
                                  (w, h, 1))
        if levels > 1:
            self._ensure_mip_pipeline()
            for lv in range(1, levels):
                for i in range(6):
                    src_v = tex.create_view(base_mip_level=lv - 1, mip_level_count=1,
                                            base_array_layer=i, array_layer_count=1)
                    dst_v = tex.create_view(base_mip_level=lv, mip_level_count=1,
                                            base_array_layer=i, array_layer_count=1)
                    grp = d.create_bind_group(layout=self._mip_bgl, entries=[
                        {'binding': 0, 'resource': src_v},
                        {'binding': 1, 'resource': self._mip_sampler}])
                    enc = d.create_command_encoder()
                    rp = enc.begin_render_pass(color_attachments=[{
                        'view': dst_v, 'load_op': wgpu.LoadOp.clear,
                        'clear_value': (0, 0, 0, 0), 'store_op': wgpu.StoreOp.store}])
                    rp.set_pipeline(self._mip_pipe)
                    rp.set_bind_group(0, grp, [], 0, 1)
                    rp.draw(3, 1, 0, 0)
                    rp.end()
                    d.queue.submit([enc.finish()])
        view = tex.create_view(dimension='cube')
        # 4 元组里第 3/4 项是 cube 与 GPU 纹理的**持有引用**: 防 id 复用, 也便于
        # 淘汰时 destroy (view 本身不暴露底层纹理)。
        out = (view, float(levels - 1), cube, tex)
        self._env_cache[key] = out
        self._evict_env_cache()
        return out[0], out[1]

    def _ensure_instances(self, n):
        if self._inst_cap >= n and self._inst_buf is not None:
            return
        cap = max(_SCENE_CAP, n)
        self._inst_buf = self.device.create_buffer(
            size=cap * _INST_BYTES,
            usage=wgpu.BufferUsage.VERTEX | wgpu.BufferUsage.COPY_DST)
        self._inst_sha_buf = self.device.create_buffer(
            size=cap * _INST_SHADOW_BYTES,
            usage=wgpu.BufferUsage.VERTEX | wgpu.BufferUsage.COPY_DST)
        # 2026-11-07: 第 2 张平行光阴影的实例缓冲 (槽 1 专用; 两趟阴影 pass
        # 各读各的, 避免同一 encoder 内先写后提交互相覆盖)
        self._inst_sha_buf2 = self.device.create_buffer(
            size=cap * _INST_SHADOW_BYTES,
            usage=wgpu.BufferUsage.VERTEX | wgpu.BufferUsage.COPY_DST)
        self._inst_cap = cap
        # 组1: GPU 缓冲重建 -> CPU staging 作废 (下帧按新 cap 重建)
        self._inst_stage = None
        self._inst_sha_stage = None

    def _mesh_corners(self, mesh):
        cs = self._bb_local.get(id(mesh))
        if cs is None:
            v = np.asarray(mesh.vertices, dtype=np.float32)
            mn, mx = v.min(axis=0), v.max(axis=0)
            cs = np.array([
                [mn[0], mn[1], mn[2]], [mx[0], mn[1], mn[2]],
                [mn[0], mx[1], mn[2]], [mx[0], mx[1], mn[2]],
                [mn[0], mn[1], mx[2]], [mx[0], mn[1], mx[2]],
                [mn[0], mx[1], mx[2]], [mx[0], mx[1], mx[2]]], dtype=np.float32)
            self._bb_local[id(mesh)] = cs
        return cs

    def _dir_light_vp(self, light, worlds, vis):
        D = (light.direction.x, light.direction.y, light.direction.z)
        ln = math.sqrt(D[0] ** 2 + D[1] ** 2 + D[2] ** 2)
        if ln < 1e-6:
            return None
        D = (D[0] / ln, D[1] / ln, D[2] / ln)
        eye = (light.position.x, light.position.y, light.position.z)
        up = (light.up_vector().x, light.up_vector().y, light.up_vector().z)
        view = mat4_view_forward(np, eye, D, up)
        n = len(vis)
        corners = np.empty((n * 8, 4), dtype=np.float32)
        for k, m in enumerate(vis):
            cs = self._mesh_corners(m.mesh)
            base = k * 8
            corners[base:base + 8, :3] = cs
            corners[base:base + 8, 3] = 1.0
        w = np.empty((n * 8, 4), dtype=np.float32)
        for k in range(n):
            w[k * 8:(k + 1) * 8] = (corners[k * 8:(k + 1) * 8].astype(np.float64)
                                   @ worlds[k]).astype(np.float32)
        w = (w.astype(np.float64) @ view.astype(np.float64)).astype(np.float32)
        mn = w[:, :3].min(axis=0)
        mx = w[:, :3].max(axis=0)
        if light.mode == 'beam':
            s = max(light.size, 0.01)
            left, right, bottom, top = -s, s, -s, s
            near, far = 0.0, max(float(mx[2]) + 2.0, 1.0)
        else:
            pad = 1.5
            left = float(mn[0]) - pad; right = float(mx[0]) + pad
            bottom = float(mn[1]) - pad; top = float(mx[1]) + pad
            near = min(0.0, float(mn[2]) - 2.0)
            far = max(float(mx[2]) + 2.0, 1.0)
        return (view @ mat4_ortho(np, left, right, bottom, top, near, far)
                ).astype(np.float32)

    # 已知限制 (见模块 docstring): VK 只有 2 张平行光阴影贴图 + 1 套点光 6 面。
    # 多出来的投影灯不再拿别人的贴图 (params.w=-1 -> 该灯无阴影) —— 每进程只警告
    # 一次, 不崩。
    _shadow_limit_warned = False

    def _warn_shadow_limit(self, n_dir, n_pt):
        """阴影贴图张数超限时打印一次警告 (第 3 盏平行光 / 第 2 盏点光起)."""
        if VkRenderer._shadow_limit_warned:
            return
        VkRenderer._shadow_limit_warned = True
        print('[vk] 阴影已知限制: VK 后端只有 2 张平行光阴影 + 1 套点光 6 面阴影;'
              ' 当前场景有 %d 盏平行光 / %d 盏点光 要求投影 -> 超出部分无阴影'
              ' (见 vk_renderer 模块 docstring, 不崩)。' % (n_dir, n_pt))

    def _pack_light_vps(self, lights, vis, worlds):
        self._light_vps = {}
        self._dir_shadow_slots = {}     # 平行光 guid -> 阴影槽位 (0/1)
        self._point_shadow_guid = None
        _n_dir = 0          # 真正算出 VP 的平行光投影灯数
        _n_pt = 0           # 要求投影的点/聚光灯数
        for l in lights[:8]:
            if l.kind == 'directional' and l.shadow:
                vp = self._dir_light_vp(l, worlds, vis)
                if vp is not None:
                    self._light_vps[l.guid] = vp
                    _n_dir += 1
                    # 2026-11-07: 前 2 盏投影平行光各占一张 1024² 贴图槽位
                    # (0/1); 第 3 盏及以后不分配 -> params.w=-1, 该灯无阴影
                    # (不再拿别人的贴图做 PCF)。VP 仍保留 (beam 截面要用 ortho)。
                    if len(self._dir_shadow_slots) < _SHADOW_SLOTS:
                        self._dir_shadow_slots[l.guid] = len(self._dir_shadow_slots)
            elif l.kind in ('point', 'spot') and l.shadow:
                _n_pt += 1
                # 2026-11-06 点光 6 面 VP (与 GL _point_light_vp 同式);
                # 仍只支持一盏点光阴影 (第二盏无贴图, 由 extra.w=0 退化为无阴影)
                if self._point_shadow_guid is None:
                    self._light_vps[l.guid] = self._point_light_vp6(l)
                    self._point_shadow_guid = l.guid
        # 2026-11-07: 超限是**已知限制**而非崩溃点 —— 打一次警告说明清楚。
        if _n_dir > _SHADOW_SLOTS or _n_pt > 1:
            self._warn_shadow_limit(_n_dir, _n_pt)

    def _point_light_vp6(self, light):
        """点光 6 面 VP (与 GL scene_driver/_point_light_vp 同式: 90° 透视, far=30)."""
        pos = (light.position.x, light.position.y, light.position.z)
        proj = mat4_perspective(np, math.radians(90.0), 1.0, 0.05, _POINT_FAR)
        axes = [(1, 0, 0), (-1, 0, 0), (0, 1, 0), (0, -1, 0), (0, 0, 1), (0, 0, -1)]
        ups = [(0, 1, 0), (0, 1, 0), (0, 0, 1), (0, 0, 1), (0, 1, 0), (0, 1, 0)]
        return [mat4_view_forward(np, pos, a, u) @ proj for a, u in zip(axes, ups)]

    # ---------------- 每帧打包 ----------------
    def _pack_scene(self, vp, lights, camera_pos):
        """场景块 f32[352]: mvp[0..16) cam[16..20) cnt[20..24) cnt2[24..28)
        misc[28..32) L0..L7[32..)

        2026-11-06 渲染 API 对齐:
          · 灯数 4 -> 8; kind 0=平行 1=点 2=聚光 (与 GL 逐值一致)
          · extra = (cos_inner, cos_outer, range, has_point_shadow)
          · params = (bias, shadow_res, point_far, dir_shadow_slot)
            params.w = 平行光阴影槽位号 (0/1, -1=该灯无贴图 -> 无阴影)
          · misc.x = 全局 PBR 开关
        """
        buf = np.zeros(_SCENE_FLOATS, dtype=np.float32)
        buf[_R_MVP:_R_MVP + 16] = vp.reshape(16)
        buf[_R_CAM:_R_CAM + 4] = (camera_pos[0], camera_pos[1], camera_pos[2],
                                  1.0 if lights else 0.2)
        # 2026-11-07 修复: 原读 self.pbr_enabled (属性名拼错, 真实开关是
        # engine._pbr_enabled) -> 永远落到 getattr 缺省 True, pbr_enabled=False
        # 在 Vk 后端等于没设。现统一走 property, 语义与 GL 一致。
        buf[_R_MISC] = 1.0 if self.pbr_enabled else 0.0
        n_on = min(len(lights), 8)
        _dir_slots = getattr(self, "_dir_shadow_slots", {})
        for i in range(8):
            if i < 4:
                buf[_R_CNT + i] = 1.0 if i < n_on else 0.0
            else:
                buf[_R_CNT2 + (i - 4)] = 1.0 if i < n_on else 0.0
        for i, l in enumerate(lights[:8]):
            b = _R_L0 + i * _LIGHT_F32
            kind = 0.0
            if l.kind == "point":
                kind = 1.0
            elif l.kind == "spot":
                kind = 2.0
            mode = 0.0 if l.mode == "full" else 1.0
            shape = 0.0 if l.shape == "circle" else 1.0
            buf[b:b + 4] = (kind, mode, shape, 1.0 if l.shadow else 0.0)
            buf[b + 4:b + 7] = l.color
            buf[b + 7] = float(l.intensity)
            d = l.direction
            buf[b + 8:b + 11] = (d.x, d.y, d.z)
            pp = l.position
            buf[b + 12:b + 15] = (pp.x, pp.y, pp.z)
            vp_l = self._light_vps.get(l.guid)
            # 点光存的是 6 面 VP 列表 (走 cube 采样, 不用 ortho); 只有平行光是
            # 单个 4x4。(2026-11-06 点光阴影)
            if vp_l is not None and hasattr(vp_l, "reshape"):
                buf[b + 16:b + 32] = vp_l.reshape(-1)
            # params.z = 点光阴影 far 平面 (GL u_light_far 同义), params.x = bias,
            # params.w = 平行光阴影槽位号 (2026-11-07: 0/1, -1=无贴图; 点光不用)
            _has_ps = 1.0 if getattr(self, "_point_shadow_guid", None) == l.guid else 0.0
            _slot = 0.0                 # 点光/聚光不用 (保持旧值)
            if kind < 0.5:
                _slot = float(_dir_slots.get(l.guid, -1))
            buf[b + 32:b + 36] = (0.002, float(_SHADOW_RES), float(_POINT_FAR), _slot)
            inner = math.cos(math.radians(float(getattr(l, "spot_inner_angle", 30.0))))
            outer = math.cos(math.radians(float(getattr(l, "spot_outer_angle", 60.0))))
            buf[b + 36:b + 40] = (inner, outer, float(getattr(l, "range", 10.0)), _has_ps)
        return buf

    @staticmethod
    def _mesh_key(model):
        """mesh 分桶键: (primitive, params) —— 同几何共享缓冲 (P4 最小 draw).
        组1 (2026-08-30): 消费 GameObject._bucket_key 缓存 (GL 侧同约定,
        mesh/normal_mode/primitive/params setter 置脏; GL 键含 normal_mode,
        Vk 键语义不变仅消费缓存——注意两后端键值不互通, 各自独立成键).
        无缓存属性 (测试桩) 回退现算."""
        k = getattr(model, '_bucket_key', None)
        if k is not None and len(k) == 2:     # 2 元组=Vk 键 (GL 键 3 元组, 拒收防串)
            return k
        k = (getattr(model, 'primitive', None) or 'obj',
             json.dumps(getattr(model, 'params', None) or {}, sort_keys=True))
        try:
            model._bucket_key = k              # 与 GL 同一缓存槽 (键值两后端各自成键)
        except AttributeError:
            pass
        return k

    # ---------------- 帧提交 ----------------
    def draw_frame(self, ctx, models, lights, vp, camera_pos, interp=None, sky=None,
                   ui=None, hud_lines=None, hud=None, cam_basis=None, engine=None):
        d = self.device
        w, h = ctx.physical_size
        vis = [m for m in models if getattr(m, 'visible', True) and m.mesh is not None]
        self._ensure_scene()
        self._ensure_instances(len(vis))
        worlds = world_matrices(vis, interp=interp)   # 分离批2: 插值平面可选
        self._pack_light_vps(lights, vis, worlds)

        # ---- 2026-11-06 R1 world Canvas: 先把元素树离屏渲染到纹理 ----
        # GL 在天空盒之后、HUD 之前画; VK 的等价位置是主 pass 里几何之后
        # (见下面 _draw_world_quads), 这里只做离屏 target 的准备.
        world_items = (self.render_world_canvases(ui, w, h, models=models)
                       if ui is not None else [])
        world_all = None
        world_id2i = None
        if world_items:
            try:
                world_all = world_matrices(models, interp=interp)
                world_id2i = {id(m): i for i, m in enumerate(models)}
            except Exception as e:
                print('[vk] world Canvas 世界矩阵计算失败 (跳过):', repr(e))
                world_items = []

        d.queue.write_buffer(self._scene_buf, 0,
                             self._pack_scene(vp, lights, camera_pos).tobytes())

        # 实例缓冲 (按 mesh 桶重排): world/nm/sat/color (160B) + 阴影 world@光VP (64B)
        # 组1 (2026-08-30): 预分配复用 (np.zeros×2 每帧分配消除; 容量生长重建时
        # 重建, y/z/w 等不写区恒 0 与旧 np.zeros 语义一致) + 消每帧逐物体
        # hex 解析/属性链 (Material._rgba/_sat_f32 缓存, getattr 防御回退).
        n_vis = len(vis)
        if self._inst_cap < n_vis:
            self._ensure_instances(n_vis)
        inst = self._inst_stage
        inst_sha = self._inst_sha_stage
        if inst is None or inst.shape[0] < n_vis:
            inst = self._inst_stage = np.zeros(
                (self._inst_cap, _INST_BYTES // 4), dtype=np.float32)
            inst_sha = self._inst_sha_stage = np.zeros(
                (self._inst_cap, _INST_SHADOW_BYTES // 4), dtype=np.float32)
        inst[:n_vis, _R_WORLD:_R_WORLD + 16] = worlds.reshape(n_vis, 16)
        inv = np.linalg.inv(worlds)
        inst[:n_vis, _R_NM:_R_NM + 16] = np.transpose(inv, (0, 2, 1)).reshape(n_vis, 16)
        for i, m in enumerate(vis):
            mat = getattr(m, 'renderer', None).material if hasattr(m, 'renderer') else None
            if mat is not None and hasattr(mat, '_sat_f32'):
                inst[i, _R_SAT] = mat._sat_f32
                # 2026-11-06 PBR: 槽 8 余下 3 float = (metallic, roughness, pbr)
                inst[i, _R_SAT + 1] = float(getattr(mat, '_metallic', 0.0))
                inst[i, _R_SAT + 2] = float(getattr(mat, '_roughness', 0.5))
                inst[i, _R_SAT + 3] = 1.0 if getattr(mat, '_pbr', False) else 0.0
                r = mat._rgba
                if r is not None:
                    inst[i, _R_COLOR:_R_COLOR + 4] = r
            else:                              # 测试桩/无 Material: 旧路径回退
                inst[i, _R_SAT] = getattr(m, 'saturation', 1.0)
                col = getattr(m, 'color', None)
                if col is not None:
                    inst[i, _R_COLOR:_R_COLOR + 4] = (
                        int(col[1:3], 16) / 255.0, int(col[3:5], 16) / 255.0,
                        int(col[5:7], 16) / 255.0, 1.0)
        # 2026-11-07: 平行光阴影按槽位取 (guid -> 0/1); 点光是 6 面列表不参与。
        # 第 3 盏及以后没有槽位 (params.w=-1) -> 不烘贴图, 该灯无阴影。
        _dir_maps = []
        for _guid, _slot in getattr(self, '_dir_shadow_slots', {}).items():
            _vp = self._light_vps.get(_guid)
            if _vp is not None and getattr(_vp, 'shape', None) == (4, 4):
                _dir_maps.append((int(_slot), _vp))
        _dir_maps.sort(key=lambda t: t[0])
        lvp = _dir_maps[0][1] if _dir_maps else None
        lvp2 = _dir_maps[1][1] if len(_dir_maps) > 1 else None
        if lvp is not None:
            inst_sha[:n_vis, :16] = (worlds @ lvp).reshape(n_vis, 16)

        # mesh 桶 -> 实例范围 (桶序 == 实例序); 桶几何取该桶首个模型
        # ★ 颜色不进桶几何: 各物体颜色经实例属性覆盖 (桶仅共享 pos/normal)
        buckets = {}
        bucket_geo = {}
        for i, m in enumerate(vis):
            _mat = getattr(getattr(m, 'renderer', None), 'material', None)
            _view, _tguid, _nview, _nguid = self._tex_view(_mat)
            _has_nrm = bool(_nguid)
            _etex = getattr(_mat, 'env_map', None) if _mat is not None else None
            if _etex is not None:
                _eview, _emaxlod = self._upload_cube_env(_etex)
            else:
                _eview, _emaxlod = None, 0.0
            _eguid = (getattr(_etex, 'guid', '') if _etex is not None and _eview is not None
                      else '')
            # 2026-11-06 贴图: albedo + 法线都进桶键 (同网格不同贴图不能合并)
            k = self._mesh_key(m) + (_tguid, _nguid, _eguid)
            buckets.setdefault(k, []).append(i)
            if k not in bucket_geo:
                # 2026-11-07 采样器 (wrap/filter_mode 生效) 按**桶**取一次: 桶键已含
                # albedo guid, 同桶必然同采样器 -> 不是每物体每帧都建一次字典。
                # 缺省参数复用 _tex_sampler, 老场景采样行为逐位不变。
                _samp = self._sampler_for(getattr(_mat, 'albedo', None))
                bucket_geo[k] = (m.mesh, m.normal_mode, _view, _nview, _has_nrm,
                                 _eview, _emaxlod, _samp)

        # 2026-11-07 [P1 回归] 桶实例偏移: 实例行按 vis 原序写入, 而 draw 只能
        # 画**连续**实例区间。同桶物体被别的桶隔开时 (同网格 A、别的网格 B、
        # 同网格 A), 旧代码 rp.draw(nv, len(idxs), 0, idxs[0]) 会从第一个 A 起
        # 连画 len(idxs) 行 —— 把 B 的行当成 A 画 (A 漏画 + B 串形)。
        # 裁决 A 的落地: 单缓冲 + 按桶重排, 桶起点用重排后的累计偏移。
        _order, _bstart, _ident = bucket_layout(buckets)
        if _ident:                       # 已连续 (绝大多数场景): 零拷贝直传
            _inst_pack = inst[:n_vis]
            _sha_pack = inst_sha[:n_vis]
        else:
            _inst_pack = inst[_order]
            _sha_pack = inst_sha[_order]
        d.queue.write_buffer(self._inst_buf, 0, _inst_pack.tobytes())
        d.queue.write_buffer(self._inst_sha_buf, 0, _sha_pack.tobytes())
        # 2026-11-07 第 2 张平行光阴影: 实例矩阵 = world @ 槽 1 光 VP, 独立缓冲
        # (同一 encoder 里两趟阴影 pass 各读各的, 不会互相覆盖)。
        if lvp2 is not None:
            _sha2 = (worlds @ lvp2).reshape(n_vis, 16)
            d.queue.write_buffer(self._inst_sha_buf2, 0,
                                 (_sha2 if _ident else _sha2[_order]).tobytes())

        # ---- 阴影 pass (2026-11-07: 2 个槽位各烘一张 1024²) ----
        if _dir_maps and vis:
            enc = d.create_command_encoder()
            _u = np.zeros(24, dtype=np.float32)
            _u[0:16] = np.eye(4, dtype=np.float32).reshape(16)   # 平行光: 实例已含 VP
            _u[20] = 0.0                                          # 模式=投影深度
            for _slot, _vp in _dir_maps:
                _sview = self._shadow_view if _slot == 0 else self._shadow_view2
                _sbuf = self._inst_sha_buf if _slot == 0 else self._inst_sha_buf2
                # 每槽位独立 uniform 缓冲 (与点光 6 面同理: 写同一缓冲会被后写覆盖)
                d.queue.write_buffer(self._dir_shadow_bufs[_slot], 0, _u.tobytes())
                rp = enc.begin_render_pass(color_attachments=[{
                    'view': _sview,
                    'load_op': wgpu.LoadOp.clear,
                    'clear_value': (1.0, 0.0, 0.0, 1.0),
                    'store_op': wgpu.StoreOp.store}])
                rp.set_pipeline(self._shadow_pipeline)
                rp.set_bind_group(0, self._dir_shadow_groups[_slot], [], 0, 1)
                for k, idxs in buckets.items():
                    mesh, nm, _texv, _nrmv, _hn, _ev, _eml, _samp = bucket_geo[k]
                    buf, nv = self._ensure_geo_data(k, mesh, nm)
                    rp.set_vertex_buffer(0, buf)
                    rp.set_vertex_buffer(1, _sbuf)
                    # first_instance = 重排后的桶起点 (不是 idxs[0]: 实例行已重排)
                    rp.draw(nv, len(idxs), 0, _bstart[k])
                rp.end()
            d.queue.submit([enc.finish()])

        # ---- 点光 6 面阴影 pass (2026-11-06 对齐 GL) ----
        _psg = getattr(self, '_point_shadow_guid', None)
        if _psg is not None and vis:
            pv6 = self._light_vps.get(_psg)
            if pv6:
                enc = d.create_command_encoder()
                n_v = len(vis)
                stage = np.zeros((max(n_v, 1), 16), dtype=np.float32)
                _w = np.asarray(worlds, dtype=np.float32)
                _lpos = None
                for _l in lights:
                    if getattr(_l, 'guid', None) == _psg:
                        _lpos = (_l.position.x, _l.position.y, _l.position.z)
                        break
                _lpos = _lpos or (0.0, 0.0, 0.0)
                for f, vp_f in enumerate(pv6):
                    # 点光: 实例 = world; 面 VP 走 uniform (shader 里 su.vp * world)
                    # 同样要按桶重排: draw 的 first_instance 用的是 _bstart[k]
                    stage[:n_v] = (_w if _ident else _w[_order]).reshape(n_v, 16)
                    d.queue.write_buffer(self._inst_sha_buf, 0, stage.tobytes())
                    _u = np.zeros(24, dtype=np.float32)
                    _u[0:16] = np.asarray(vp_f, dtype=np.float32).reshape(16)
                    _u[16:19] = _lpos
                    _u[20] = 1.0                 # 模式=距离/far
                    _u[21] = _POINT_FAR
                    d.queue.write_buffer(self._shadow_bufs[1 + f], 0, _u.tobytes())
                    rp = enc.begin_render_pass(color_attachments=[{
                        'view': self._point_face_views[f],
                        'load_op': wgpu.LoadOp.clear,
                        'clear_value': (1.0, 0.0, 0.0, 1.0),
                        'store_op': wgpu.StoreOp.store}])
                    rp.set_pipeline(self._shadow_pipeline)
                    rp.set_bind_group(0, self._shadow_groups[1 + f], [], 0, 1)
                    for k, idxs in buckets.items():
                        mesh, nm, _texv, _nrmv, _hn, _ev, _eml, _samp = bucket_geo[k]
                        buf, nv = self._ensure_geo_data(k, mesh, nm)
                        rp.set_vertex_buffer(0, buf)
                        rp.set_vertex_buffer(1, self._inst_sha_buf)
                        rp.draw(nv, len(idxs), 0, _bstart[k])
                    rp.end()
                d.queue.submit([enc.finish()])
                # 恢复平行光实例缓冲 (主 pass 不再用, 但保持一致)
                if lvp is not None:
                    inst_sha[:n_v, :16] = (worlds @ lvp).reshape(n_v, 16)
                    d.queue.write_buffer(
                        self._inst_sha_buf, 0,
                        (inst_sha[:n_v] if _ident
                         else inst_sha[_order]).tobytes())

        # ---- 主 pass ----
        if self._depth is None or self._depth[0] != (w, h):
            tex = d.create_texture(
                size=(w, h, 1), usage=wgpu.TextureUsage.RENDER_ATTACHMENT,
                format='depth32float')
            self._depth = ((w, h), tex.create_view())
        # 2026-11-09 C5=B: 上屏健康 —— 取交换链纹理失败(超时/outdated/设备丢失)计入连续失败,
        # 跳过本帧(不抛), 达到阈值后由 vk_player/Loom 的 auto 判据降级为离屏回读。
        try:
            view = ctx.get_current_texture().create_view()
        except Exception as _e:
            self._present_guard().note_fail('取交换链纹理失败: %r' % (_e,))
            if not getattr(self, '_present_err_logged', False):
                self._present_err_logged = True
                print('[vk] 上屏失败 (本局只报一次, 本帧跳过):', repr(_e))
            return
        # 2026-11-10 阶段 2B2: 开后处理时主链写 HDR(rgba16float)，最后在**同一 encoder**
        # 里追加 bloom + tonemap 写回交换链；LOOM_POST=0 时逐位保持旧路径。
        if self._post_on:
            self._ensure_post_targets(w, h)
            color_view = self._post_t['hdr_view']
            self._frame_fmt = 'rgba16float'
        else:
            color_view = view
            self._frame_fmt = self.format
        self._ensure_main_pipe(self._frame_fmt)
        enc = d.create_command_encoder()
        rp = enc.begin_render_pass(color_attachments=[{
            'view': color_view, 'load_op': wgpu.LoadOp.clear,
            'clear_value': CLEAR_COLOR_RGBA, 'store_op': wgpu.StoreOp.store}],
            depth_stencil_attachment={
                'view': self._depth[1], 'depth_clear_value': 1.0,
                'depth_load_op': wgpu.LoadOp.clear, 'depth_store_op': wgpu.StoreOp.store})
        # 2026-11-06 天空盒: 先画背景 (不写深度), 再画几何 -> 与 GL 的
        # "几何后画天空但只在 depth==1 处通过" 视觉等价 (无 overdraw 顾虑:
        # 天空只画一次, 且几何随后完整覆盖)。sky=None 时保持原清屏色。
        # 2026-11-09 (Q3=A / P-06): 生效天空盒与 tint 都从引擎取（与 GL 同一判定/同一来源）;
        # 上层显式给了 sky 就用它（相机级已由上层解析）。
        _tint = getattr(engine, '_skybox_tint', None)
        if engine is not None:
            # 引擎是"生效天空盒"的权威（相机级优先, 见 GLEngine/SceneDriver.effective_skybox）;
            # 上层传入的 sky 只在引擎给不出时兜底 —— 否则 VK 永远用场景级、丢掉相机级。
            eff = getattr(engine, 'effective_skybox', None)
            if callable(eff):
                try:
                    _c = eff()
                    if _c is not None:
                        sky = _c
                except Exception as e:
                    print('[vk] 取生效天空盒失败 (改用上层传入值):', repr(e))
        if sky is not None:
            try:
                if self._draw_sky(ctx, rp, vp, camera_pos, sky, w, h, tint=_tint,
                                  engine=engine):
                    pass
            except Exception as e:
                if not getattr(self, '_sky_err_logged', False):
                    self._sky_err_logged = True
                    print("[vk] 天空盒绘制失败 (本局只报一次, 本帧跳过):", repr(e))
        rp.set_pipeline(self._pipeline)
        rp.set_bind_group(0, self._scene_group, [], 0, 1)
        for k, idxs in buckets.items():
            mesh, nm, _texv, _nrmv, _hn, _ev, _eml, _samp = bucket_geo[k]
            buf, nv = self._ensure_geo_data(k, mesh, nm)
            rp.set_bind_group(0, self._tex_group(_texv, _nrmv, _hn, _ev, _eml, _samp),
                              [], 0, 1)
            rp.set_vertex_buffer(0, buf)
            rp.set_vertex_buffer(1, self._inst_buf)
            rp.draw(nv, len(idxs), 0, _bstart[k])
        # 2026-11-06 R1: world Canvas quad, 与 GL 同位置 (几何/天空之后, HUD 之前).
        # 同 pass 深度附件 = 可被 3D 物体遮挡; 管线 depth_write=False (GL 同).
        if world_items and world_all is not None:
            try:
                self._draw_world_quads(rp, world_items, world_all, world_id2i,
                                       vp, camera_pos, cam_basis)
            except Exception as e:
                print('[vk] world Canvas quad 绘制失败 (跳过):', repr(e))
        rp.end()
        if self._post_on:
            self._record_post(enc, view, w, h)   # 同一 encoder, 帧内仍只 submit 一次
        d.queue.submit([enc.finish()])
        # 2026-11-09 C5=B: 主 pass 提交成功 -> 记一次上屏成功（连续失败清零）
        try:
            self._present_guard().note_ok()
        except Exception as e:
            if not getattr(self, '_present_ok_err_logged', False):
                self._present_ok_err_logged = True
                print('[vk] 上屏健康记账失败 (%r)' % (e,))
        # ---- 2026-11-06 Canvas UI / HUD 叠加 pass (load_op=load, 无深度) ----
        # 顺序与 GL 一致: HUD 文本先, UI 元素树后 (loom_render.render 的
        # _draw_hud() -> ui.draw_all() 次序); 独立 pass/管线, 不与 3D 组混绑。
        # 2026-11-07 修复(P0): engine(脚本宿主) 必须透传 —— 否则 UI 事件派发
        # 拿不到 driver, 打包版(VK) 所有按钮点击无效。
        self.draw_ui(view, w, h, ui=ui, hud_lines=hud_lines, hud=hud,
                     engine=engine)
