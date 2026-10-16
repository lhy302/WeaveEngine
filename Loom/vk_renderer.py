# -*- coding: utf-8 -*-
"""
vk_renderer.py — Vulkan 渲染后端 (wgpu-py, 2026-08-29 性能调优 P4F: 实例化批绘制)

★ 驱动死锁规避 (1050Ti/582.66/wgpu 0.32 实测):
  多 bind group 组合 / fragment 数组动态索引 → 驱动死锁 (整机卡死)。
  P4F 形态: 单 bind group (场景块 uniform + 阴影纹理 + 采样器);
  矩阵走 instance 步进顶点缓冲 (世界矩阵 132B/实例), 4 灯固定展开无数组;
  阴影 R32Float 手动比较; 法线逆转置 CPU 预算; front_face='cw' (引擎绕序)。

里程碑: P4 = 按 mesh 分桶实例化 (50 球 → 2 draw / 1 bind group);
shader 双源 (Vk=WGSL; GL=现 GLSL)。矩阵全部行主序 tobytes() 直传。
"""
import json
import math

import numpy as np

import wgpu

from matlib import mat4_view_yaw_pitch, mat4_view_forward, mat4_perspective, mat4_ortho

_VERT_BYTES = 10 * 4          # 每顶点 40 字节: pos3f + normal3f + color4f
_INST_BYTES = 160             # 每实例 40 f32: world(16)+nm(16)+satvec(4)+color(4, 覆盖标志)
_R_WORLD = 0                  # loc3-6  (mat4)
_R_NM = 16                    # loc7-10 (mat4)
_R_SAT = 32                   # loc11   (vec4, .x=sat)
_R_COLOR = 36                 # loc12   (vec4, rgb+覆標w)
_INST_SHADOW_BYTES = 64       # 阴影实例: world@光VP (mat4)
_SCENE_CAP = 64               # 空余实例槽 (扩容单位)
_SHADOW_RES = 1024

# 场景块 f32 布局 (SceneC): mvp[0..16) cam[16..20) cnt[20..24) L0..L3[24..)
_R_MVP = 0
_R_CAM = 16
_R_CNT = 20
_R_L0 = 24
_LIGHT_F32 = 36

# ---------------- WGSL: 主 pass ----------------
_MAIN_VERT = """
struct SceneC {
    mvp: mat4x4<f32>,         // 公共 V@P
    cam: vec4f,               // xyz view_pos, w ambient_scale
    cnt: vec4f,               // 每灯激活标志 (固定展开)
    l0: LightX, l1: LightX, l2: LightX, l3: LightX,
}
struct LightX {
    kind: f32, mode: f32, shape: f32, shadow: f32,
    color: vec4f,             // rgb + intensity (a)
    dir: vec4f,
    pos: vec4f,
    ortho: mat4x4<f32>,
    params: vec4f,            // shadow_bias, shadow_res, beam size, pad
}
@group(0) @binding(0) var<uniform> sc: SceneC;
struct VSOut {
    @builtin(position) pos: vec4f,
    @location(0) color: vec4f,
    @location(1) n: vec3f,
    @location(2) wpos: vec3f,
    @location(3) sat: f32,
}
// 实例缓冲每实例 208B: world(loc3-6) + nm(loc7-10) + satv(loc11) + color(loc12)
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
) -> VSOut {
    var o: VSOut;
    let iw = mat4x4<f32>(c0, c1, c2, c3);        // 列主序解释 = 数学行主序 (同引擎)
    let inm = mat4x4<f32>(n0, n1, n2, n3);
    o.n = (inm * vec4f(n, 0.0)).xyz;             // 逆转置 (CPU 预算, 非等比缩放正确)
    o.wpos = (iw * vec4f(p, 1.0)).xyz;
    o.pos = sc.mvp * iw * vec4f(p, 1.0);
    o.color = select(c, vec4f(icol.rgb, c.a), icol.w > 0.5);  // 实例色覆盖 (网格原生面颜色)
    o.sat = isatv.x;
    return o;
}
"""

_MAIN_FRAG = """
// SceneC / LightX 定义见 _MAIN_VERT (同一 module); fragment 引用 sc 公共块
@group(0) @binding(1) var t_shadow: texture_2d<f32>;
@group(0) @binding(2) var s_shadow: sampler;

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

fn light_contrib(L: LightX, n: vec3f, v: vec3f, wpos: vec3f) -> vec3f {
    var l: vec3f;
    var diff: f32;
    var atten: f32 = 1.0;
    if (L.kind > 0.5) {
        let to_l = L.pos.xyz - wpos;
        let dist = max(length(to_l), 1e-4);
        l = to_l / dist;
        diff = max(dot(n, l), 0.0);
        atten = 1.0 / (1.0 + 0.09 * dist + 0.045 * dist * dist);
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
        let uv = lp.xy / lp.w * 0.5 + 0.5;
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
    if (L.shadow > 0.5 && L.kind < 0.5) {
        let lp = L.ortho * vec4f(wpos, 1.0);
        let depth = lp.z / lp.w;
        let uv = lp.xy / lp.w * 0.5 + 0.5;
        if (uv.x < 0.0 || uv.x > 1.0 || uv.y < 0.0 || uv.y > 1.0) {
            sh = select(1.0, sh, L.mode > 0.5);
        } else {
            sh = pcf(uv, depth, L.params.x, L.params.y) * g_in_shape;
        }
    }
    return L.color.rgb * L.color.a * (0.60 * diff + 0.25 * spec) * atten * sh;
}

@fragment fn fs(in: VSOut) -> @location(0) vec4f {
    let n = normalize(in.n);
    let v = normalize(sc.cam.xyz - in.wpos);
    let hemi = clamp(0.5 + 0.5 * n.y, 0.0, 1.0);
    let amb = (0.02 + 0.28 * hemi) * sc.cam.w;
    var acc = vec3f(0.0);
    if (sc.cnt.x > 0.5) { acc += light_contrib(sc.l0, n, v, in.wpos); }
    if (sc.cnt.y > 0.5) { acc += light_contrib(sc.l1, n, v, in.wpos); }
    if (sc.cnt.z > 0.5) { acc += light_contrib(sc.l2, n, v, in.wpos); }
    if (sc.cnt.w > 0.5) { acc += light_contrib(sc.l3, n, v, in.wpos); }
    let rim = 0.12 * pow(1.0 - max(dot(n, v), 0.0), 3.0);
    var col = in.color.rgb * (amb + acc) + vec3f(rim);
    col = pow(clamp(col, vec3f(0.0), vec3f(1.0)), vec3f(1.0 / 2.2));
    let lum = dot(col, vec3f(0.299, 0.587, 0.114));
    col = mix(vec3f(lum), col, in.sat);
    return vec4f(col, 1.0);
}
"""

# ---------------- WGSL: 阴影 pass (实例矩阵, R32Float) ----------------
_SHADOW_VERT = """
@vertex fn vs(
    @location(0) p: vec3f,
    @location(3) c0: vec4f, @location(4) c1: vec4f,
    @location(5) c2: vec4f, @location(6) c3: vec4f,   // 每实例世界@光VP (列拆)
) -> @builtin(position) vec4f {
    let mvp = mat4x4<f32>(c0, c1, c2, c3);
    return mvp * vec4f(p, 1.0);
}
@fragment fn fs(@builtin(position) pos: vec4f) -> @location(0) vec4f {
    return vec4f(pos.z / pos.w, 0.0, 0.0, 1.0);   // 深度 [0,1] (手动比较用)
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
    return np.concatenate([pos, norm, col], axis=1)


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

    def __init__(self, device, present_format, stage='p4'):
        self.device = device
        self.format = present_format
        self.stage = stage
        self._build_pipelines()
        self._depth = None          # (w, h, view)
        self._scene_buf = None      # 场景块 uniform (公共)
        self._inst_buf = None       # 实例缓冲 (132B/实例)
        self._inst_sha_buf = None   # 阴影实例缓冲 (64B/实例)
        # 组1 (2026-08-30): CPU 侧 staging 持久复用 (消每帧 np.zeros×2);
        # _ensure_instances 扩容时作废, 下帧按新 cap 重建.
        self._inst_stage = None
        self._inst_sha_stage = None
        self._inst_cap = 0
        self._geo = {}              # mesh 键 -> (vertex_buf, n_verts)
        self._shadow_tex = None
        self._shadow_view = None
        self._shadow_sampler = None
        self._light_vps = {}
        self._bb_local = {}

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
             'sampler': {'type': 'non-filtering'}}])
        # 主管线: 顶点(40B) + 实例(132B: world/nm/sat)
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
        self._shadow_pipeline = d.create_render_pipeline(
            layout=d.create_pipeline_layout(bind_group_layouts=[]),
            vertex=self._vertex_desc(shad, 'vs', inst=_INST_SHADOW_BYTES, nattr=4),
            primitive=self._prim(),
            fragment={'module': shad, 'entry_point': 'fs',
                      'targets': [{'format': 'r32float'}]})

    def _prim(self):
        return {'topology': 'triangle-list', 'cull_mode': 'back',
                'front_face': 'cw'}     # 引擎网格绕序 (ccw 会剔除 plane)

    def _vertex_desc(self, shader, entry, inst, nattr=12):
        bufs = [{'array_stride': _VERT_BYTES, 'step_mode': 'vertex',
                 'attributes': [
                     {'shader_location': 0, 'offset': 0, 'format': 'float32x3'},
                     {'shader_location': 1, 'offset': 12, 'format': 'float32x3'},
                     {'shader_location': 2, 'offset': 24, 'format': 'float32x4'}]}]
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
            size=720, usage=wgpu.BufferUsage.UNIFORM | wgpu.BufferUsage.COPY_DST)
        tex = d.create_texture(
            size=(_SHADOW_RES, _SHADOW_RES, 1),
            usage=wgpu.TextureUsage.RENDER_ATTACHMENT
            | wgpu.TextureUsage.TEXTURE_BINDING,
            format='r32float')
        self._shadow_tex = tex
        self._shadow_view = tex.create_view()
        self._shadow_sampler = d.create_sampler(
            mag_filter='nearest', min_filter='nearest')
        self._scene_group = d.create_bind_group(
            layout=self._bgl, entries=[
                {'binding': 0, 'resource': {'buffer': self._scene_buf,
                                            'offset': 0, 'size': 720}},
                {'binding': 1, 'resource': self._shadow_view},
                {'binding': 2, 'resource': self._shadow_sampler}])

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

    def _pack_light_vps(self, lights, vis, worlds):
        self._light_vps = {}
        for l in lights[:4]:
            if l.kind == 'directional' and l.shadow:
                vp = self._dir_light_vp(l, worlds, vis)
                if vp is not None:
                    self._light_vps[l.guid] = vp

    # ---------------- 每帧打包 ----------------
    def _pack_scene(self, vp, lights, camera_pos):
        """场景块 f32[180]: mvp[0..16) cam[16..20) cnt[20..24) L0..L3[24..)"""
        buf = np.zeros(180, dtype=np.float32)
        buf[_R_MVP:_R_MVP + 16] = vp.reshape(16)
        buf[_R_CAM:_R_CAM + 4] = (camera_pos[0], camera_pos[1], camera_pos[2],
                                  1.0 if lights else 0.2)
        for i in range(4):
            buf[_R_CNT + i] = 1.0 if i < min(len(lights), 4) else 0.0
        for i, l in enumerate(lights[:4]):
            b = _R_L0 + i * _LIGHT_F32
            kind = 0.0 if l.kind == 'directional' else 1.0
            mode = 0.0 if l.mode == 'full' else 1.0
            shape = 0.0 if l.shape == 'circle' else 1.0
            buf[b:b + 4] = (kind, mode, shape, 1.0 if l.shadow else 0.0)
            buf[b + 4:b + 7] = l.color
            buf[b + 7] = float(l.intensity)
            d = l.direction
            buf[b + 8:b + 11] = (d.x, d.y, d.z)
            p = l.position
            buf[b + 12:b + 15] = (p.x, p.y, p.z)
            vp_l = self._light_vps.get(l.guid)
            if vp_l is not None:
                buf[b + 16:b + 32] = vp_l.reshape(-1)
            buf[b + 32:b + 36] = (0.002, float(_SHADOW_RES), float(l.size), 0.0)
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
    def draw_frame(self, ctx, models, lights, vp, camera_pos, interp=None):
        d = self.device
        w, h = ctx.physical_size
        vis = [m for m in models if getattr(m, 'visible', True) and m.mesh is not None]
        self._ensure_scene()
        self._ensure_instances(len(vis))
        worlds = world_matrices(vis, interp=interp)   # 分离批2: 插值平面可选
        self._pack_light_vps(lights, vis, worlds)

        d.queue.write_buffer(self._scene_buf, 0,
                             self._pack_scene(vp, lights, camera_pos).tobytes())

        # 实例缓冲 (按 mesh 桶重排): world/nm/sat/color (208B) + 阴影 world@光VP (64B)
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
        lvp = next(iter(self._light_vps.values()), None)
        if lvp is not None:
            inst_sha[:n_vis, :16] = (worlds @ lvp).reshape(n_vis, 16)
        d.queue.write_buffer(self._inst_buf, 0, inst[:n_vis].tobytes())
        d.queue.write_buffer(self._inst_sha_buf, 0, inst_sha[:n_vis].tobytes())

        # mesh 桶 -> 实例范围 (桶序 == 实例序); 桶几何取该桶首个模型
        # ★ 颜色不进桶几何: 各物体颜色经实例属性覆盖 (桶仅共享 pos/normal)
        buckets = {}
        bucket_geo = {}
        for i, m in enumerate(vis):
            k = self._mesh_key(m)
            buckets.setdefault(k, []).append(i)
            if k not in bucket_geo:
                bucket_geo[k] = (m.mesh, m.normal_mode)

        # ---- 阴影 pass ----
        if lvp is not None and vis:
            enc = d.create_command_encoder()
            rp = enc.begin_render_pass(color_attachments=[{
                'view': self._shadow_view,
                'load_op': wgpu.LoadOp.clear, 'clear_value': (1.0, 0.0, 0.0, 1.0),
                'store_op': wgpu.StoreOp.store}])
            rp.set_pipeline(self._shadow_pipeline)
            for k, idxs in buckets.items():
                mesh, nm = bucket_geo[k]
                buf, nv = self._ensure_geo_data(k, mesh, nm)
                rp.set_vertex_buffer(0, buf)
                rp.set_vertex_buffer(1, self._inst_sha_buf)
                rp.draw(nv, len(idxs), 0, idxs[0])
            rp.end()
            d.queue.submit([enc.finish()])

        # ---- 主 pass ----
        if self._depth is None or self._depth[0] != (w, h):
            tex = d.create_texture(
                size=(w, h, 1), usage=wgpu.TextureUsage.RENDER_ATTACHMENT,
                format='depth32float')
            self._depth = ((w, h), tex.create_view())
        view = ctx.get_current_texture().create_view()
        enc = d.create_command_encoder()
        rp = enc.begin_render_pass(color_attachments=[{
            'view': view, 'load_op': wgpu.LoadOp.clear,
            'clear_value': (0.10, 0.12, 0.16, 1.0), 'store_op': wgpu.StoreOp.store}],
            depth_stencil_attachment={
                'view': self._depth[1], 'depth_clear_value': 1.0,
                'depth_load_op': wgpu.LoadOp.clear, 'depth_store_op': wgpu.StoreOp.store})
        rp.set_pipeline(self._pipeline)
        rp.set_bind_group(0, self._scene_group, [], 0, 1)
        for k, idxs in buckets.items():
            mesh, nm = bucket_geo[k]
            buf, nv = self._ensure_geo_data(k, mesh, nm)
            rp.set_vertex_buffer(0, buf)
            rp.set_vertex_buffer(1, self._inst_buf)
            rp.draw(nv, len(idxs), 0, idxs[0])
        rp.end()
        d.queue.submit([enc.finish()])
