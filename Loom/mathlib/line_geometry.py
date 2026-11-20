# -*- coding: utf-8 -*-
"""loom_line_geometry.py —— 「粗线 = 四边形」的**唯一**一份实现（Q-B7-48-1 裁决 B）。

## 为什么有这个文件

线宽在两端本来是两套能力：GL 有 `ctx.line_width`（engine.py 里设 2.0），
wgpu 0.33 的 `PrimitiveState` **没有 line_width 字段**（实测传 2.0 -> ValueError），
VK 只能 1px。实测同一 gizmo/网格/选中框两端线宽恰 2:1（GL 864 像素 vs VK 432）。

人类裁决（2026-11-20，原话「**问题一：B**」）：两端统一改成「用四边形模拟粗线」，
不再依赖 GL 的 line_width，也不再受 wgpu 缺该参数的限制 —— **GL 画面也会变**，
这是裁决明知的代价。

## 为什么放在 CPU（纯 Python）而不是两端各自的 shader

规则 5.5（同源）：扩宽的数学（顶点 -> clip -> 屏幕像素 -> 垂直偏移 -> 回 NDC）
**只许一份**。放 CPU 上，GL 用 `TRIANGLES`、VK 用 `triangle-list`，两端只负责
「画三角形」—— 「线宽」这件事完全脱离后端，不可能出现 GLSL 与 WGSL 两份实现漂移。

## 为什么是**屏幕空间**像素宽度

按几何空间（世界单位）偏移会近大远小：远处网格线细成一条缝、近处 gizmo 糊成一片。
裁决要的是「像素宽度」，所以每个顶点先投到屏幕像素空间、按像素法线偏移、再回 NDC。

## 深度语义（改造前后一致）

`matlib.mat4_perspective` 的 `clip.z` 单调映射到 [0, 1]（near->0, far->1）。
本模块**原样保留每个端点的 NDC z**，输出顶点配**恒等 view_proj** 直出：
GL 窗口深度 = (z+1)/2、VK 深度 = z —— 两端的相对遮挡关系与改造前逐位同口径
（见 test_vk_overlay_primitives 的 B7：深度缓冲 0.5 前景遮挡 / 1.0 全通过，两端一致）。

## 绕序不变量（实测钉死，别凭直觉改）

两个三角形的输出顺序固定为 (a, d, b) / (a, e, d)，其中
`a=p0+n, b=p1+n, d=p1-n, e=p0-n`、`n = perp(p1-p0) * half`。

引擎的 GL 前脸是 **`front_face='cw'`**（engine.py:308：引擎网格在标准 GL 前方 -z
下是 CW 绕序），且主 pass 之后 **CULL_FACE 是开着的**（loom_pass_gl 帧末复位）。所以
四边形必须 **CW-in-NDC** 才不会被剔掉 —— 实测 CCW 版本在 CULL_FACE 开时整块消失
（0 像素，tests/_tmp 探针 dbg_wind）。旧实现画的是 GL_LINES，永远不受剔除影响，
这条不变量就是「保持该语义」的代价。VK 侧线批管线是 `cull_mode='none'`
（loom_pass_vk），不看绕序。
"""
import math

import numpy as np

# 默认线宽（像素）：与改造前 GL 的 ctx.line_width=2.0 视觉粗细对齐
DEFAULT_WIDTH_PX = 2.0

# 端点齐次 w 的兜底下限（真正的近平面裁剪按 clip.z >= 0，见 _clip_near）
_W_EPS = 1e-5

# mode 归一：GL 枚举值（moderngl.LINES==1 / LINE_STRIP==3 / TRIANGLES==4）
# 与字符串两种形态都收（GL 传枚举、VK 传 int、测试可传字符串）。
_MODES = {
    1: 'lines', 'lines': 'lines', 'line-list': 'lines',
    3: 'line-strip', 'line-strip': 'line-strip', 'line_strip': 'line-strip',
    4: 'triangles', 'triangles': 'triangles', 'triangle-list': 'triangles',
}

_IDENTITY4 = np.eye(4, dtype=np.float32)


def mode_kind(mode):
    """mode -> 'lines' / 'line-strip' / 'triangles'（不认识的模式报错可见）。"""
    kind = _MODES.get(mode)
    if kind is None:
        raise NotImplementedError(
            'build_line_quads 不支持的顶点模式: %r（支持 LINES / LINE_STRIP / TRIANGLES）'
            % (mode,))
    return kind


def expand_segment(p0, p1, half_px):
    """屏幕像素空间：线段 -> 四边形 4 角 (a, b, d, e)；退化段返回 None。

    **这是「垂直偏移」数学的唯一一份实现**（vk_ui 的 UI 描边三角带也调它，
    见 vk_ui.UiRenderer.draw_screen_lines）。

    参数：
        p0, p1   : (x, y) 像素坐标（左上原点，y 向下）
        half_px  : 半线宽（像素）；调用方负责 `max(0.5, width*0.5)` 的下限
    返回：`((ax, ay), (bx, by), (dx, dy), (ex, ey))`，顺序即绕序（见模块头）。
    """
    x0, y0 = float(p0[0]), float(p0[1])
    x1, y1 = float(p1[0]), float(p1[1])
    dx, dy = x1 - x0, y1 - y0
    ln = math.hypot(dx, dy)
    if not (ln >= 1e-9):            # 也吃掉 NaN
        return None
    nx, ny = -dy / ln * half_px, dx / ln * half_px
    return ((x0 + nx, y0 + ny), (x1 + nx, y1 + ny),
            (x1 - nx, y1 - ny), (x0 - nx, y0 - ny))


def _ndc(p, z, W, H):
    """屏幕像素（左上原点, y 向下）-> NDC（y 向上）；z 原样带过（深度语义见模块头）。"""
    return (p[0] / W * 2.0 - 1.0, 1.0 - p[1] / H * 2.0, z)


def _clip_near(clip0, clip1, col0, col1):
    """近平面裁剪：只保留 `clip.z >= 0` 的那一段（返回 (c0,c1,k0,k1) 或 None）。

    为什么用 `clip.z >= 0` 而不是 `clip.w > 0`：本仓库的投影（matlib.mat4_perspective
    / mat4_ortho）把 near 映射到 **clip.z = 0**（模块头/ matlib 文档契约），所以
    「近平面之后」= `clip.z >= 0`。若只按 `w > eps` 裁，裁剪点的 ndc_z 会变成天文数字
    （z/w，w≈0），硬件随即按 z>w 把整个三角形再裁掉 —— 实测网格大部分线段因此消失
    （cov 36752 -> 2007，tests/_tmp/dbg_grid）。按 z=0 裁则裁剪点 ndc_z 恰为 0（近平面），
    与旧实现「GL_LINES 由硬件在近平面裁剪」逐点同义。

    在**齐次空间**按 z 线性插值即正确（z 是参数的线性函数，与硬件裁剪同口径）。
    """
    z0, z1 = float(clip0[2]), float(clip1[2])
    ok0, ok1 = z0 >= 0.0, z1 >= 0.0
    if ok0 and ok1:
        return clip0, clip1, col0, col1
    if not ok0 and not ok1:
        return None
    t = (0.0 - z0) / (z1 - z0)
    inter = clip0 + (clip1 - clip0) * t
    cinter = col0 + (col1 - col0) * t
    if ok0:
        return clip0, inter, col0, cinter
    return inter, clip1, cinter, col1


def _c4(colors, n):
    """(N,3|4) -> (N,4) f4（与 engine.draw_lines / loom_pass_vk._pack_lines 同一规则）。"""
    c = np.asarray(colors, dtype=np.float32)
    if c.ndim != 2 or c.shape[0] != n or c.shape[1] not in (3, 4):
        raise ValueError('build_line_quads: verts (%r) 与 colors (%r) 形状不匹配'
                         % ((n, 3), np.asarray(colors).shape))
    if c.shape[1] == 3:
        c = np.concatenate([c, np.ones((n, 1), dtype=np.float32)], axis=1)
    return np.ascontiguousarray(c, dtype=np.float32)


def build_line_quads(verts, colors, view_proj, width_px=DEFAULT_WIDTH_PX,
                     viewport_size=None, mode='lines'):
    """线段 -> 三角形列表（屏幕空间按像素宽度扩宽）。两端唯一的扩宽入口。

    参数：
        verts        : (N,3) 世界空间顶点（TRIANGLES 模式下原样直通）
        colors       : (N,3) 或 (N,4)，逐顶点颜色 0..1
        view_proj    : (4,4) VP（matlib 行主序约定，与 draw_lines 的 u_view_proj 同源）
        width_px     : 线宽（**像素**，默认 2.0 = 改造前视觉粗细）
        viewport_size: (W, H) 渲染目标像素尺寸（LINES/LINE_STRIP 必需；缺失报错可见）
        mode         : 'lines' / 'line-strip' / 'triangles'（也收 GL 枚举值 1/3/4）

    返回 `(verts_out, colors_out, view_proj_out)`：
        verts_out     (M,3) f4 —— **已是 NDC**（z 保留原 NDC z，见模块头「深度语义」）
        colors_out    (M,4) f4
        view_proj_out (4,4) f4 —— 恒等矩阵（顶点已预算到 NDC），调用方拿它当 u_view_proj。
      TRIANGLES 模式不做任何改动：原样返回 (verts, colors, view_proj)，调用方照旧画三角形。
    """
    v = np.asarray(verts, dtype=np.float32).reshape(-1, 3)
    n = v.shape[0]
    c4 = _c4(colors, n)
    kind = mode_kind(mode)
    vp_in = np.asarray(view_proj, dtype=np.float32).reshape(4, 4)
    if kind == 'triangles' or n == 0:
        # 已经是三角形（draw_screen_polygon 等）：不需要扩宽，原样直通
        return np.ascontiguousarray(v), c4, np.ascontiguousarray(vp_in)

    if viewport_size is None:
        raise ValueError('build_line_quads: LINES/LINE_STRIP 扩宽需要 viewport_size=(W,H)'
                         '（屏幕空间像素宽度的唯一基准）')
    W, H = float(viewport_size[0]), float(viewport_size[1])
    if not (W > 0 and H > 0):
        raise ValueError('build_line_quads: viewport_size 非法 %r' % (viewport_size,))

    # 段索引：LINES = 两两配对（奇数尾顶点丢弃，与 GL 语义一致）；
    #        LINE_STRIP = 相邻成段
    if kind == 'lines':
        pairs = [(i, i + 1) for i in range(0, n - 1, 2)]
    else:
        pairs = [(i, i + 1) for i in range(n - 1)]
    if not pairs:
        return (np.zeros((0, 3), dtype=np.float32), np.zeros((0, 4), dtype=np.float32),
                _IDENTITY4)

    # 世界 -> clip（行向量约定：clip = [x,y,z,1] @ VP，与 GLSL 的 u_view_proj*vec4 等价）
    homo = np.concatenate([v, np.ones((n, 1), dtype=np.float32)], axis=1)
    clip_all = homo @ vp_in                     # (N,4) f32
    half = max(0.5, float(width_px) * 0.5)      # 线宽下限 1px（与 GL line_width 下限同义）

    out_v, out_c = [], []
    for i, j in pairs:
        seg = _clip_near(clip_all[i].astype(np.float64),
                         clip_all[j].astype(np.float64),
                         c4[i].astype(np.float64), c4[j].astype(np.float64))
        if seg is None:
            continue
        c0, c1, k0, k1 = seg
        w0, w1 = float(c0[3]), float(c1[3])
        if w0 <= _W_EPS or w1 <= _W_EPS:        # 兜底：裁剪后仍在眼睛平面/背后
            continue
        n0 = (float(c0[0]) / w0, float(c0[1]) / w0, float(c0[2]) / w0)
        n1 = (float(c1[0]) / w1, float(c1[1]) / w1, float(c1[2]) / w1)
        # NDC -> 屏幕像素（左上原点，y 向下；与 engine._px_to_ndc 同一映射的逆）
        s0 = ((n0[0] * 0.5 + 0.5) * W, (0.5 - n0[1] * 0.5) * H)
        s1 = ((n1[0] * 0.5 + 0.5) * W, (0.5 - n1[1] * 0.5) * H)
        quad = expand_segment(s0, s1, half)
        if quad is None:                        # 屏幕上退化成一个点：无线段方向
            continue
        a, b, d, e = quad
        z0, z1 = n0[2], n1[2]
        na, nb = _ndc(a, z0, W, H), _ndc(b, z0, W, H)
        nd, ne = _ndc(d, z1, W, H), _ndc(e, z1, W, H)
        # 绕序：引擎的 GL front_face='cw'（engine.py:308，网格绕序同款），
        # CULL_FACE 在主 pass 后是开着的 -> 四边形必须 **CW-in-NDC** 才是正面。
        # 实测（tests/_tmp 探针）：CCW 版四边形在 CULL_FACE 开时整块被剔掉（0 像素）。
        out_v += [na, nd, nb, na, ne, nd]                  # (a,d,b) + (a,e,d)
        out_c += [k0, k1, k0, k0, k1, k1]                  # 逐端点颜色线性插值

    if not out_v:
        return (np.zeros((0, 3), dtype=np.float32), np.zeros((0, 4), dtype=np.float32),
                _IDENTITY4)
    return (np.ascontiguousarray(np.asarray(out_v, dtype=np.float32)),
            np.ascontiguousarray(np.asarray(out_c, dtype=np.float32)),
            _IDENTITY4)
