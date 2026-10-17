# -*- coding: utf-8 -*-
"""
mesh.py — 顶点/索引缓冲 (Mesh) 与模型生成器 (cube / sphere / obj 导入)

渲染管线的输入: 唯一顶点数组 + 三角形索引数组 + 每面颜色 (+ 可选逐顶点法线/UV)。
  vertices    # (V,3) 顶点 (x,y,z)
  faces       # (F,3) 三角形索引 (逆时针, 法线朝外)
  face_colors # (F,)  十六进制颜色
  normals     # (V,3) 逐顶点法线 (可选; obj 导入用, 无则 None)
  uvs         # (V,2) 逐顶点纹理坐标 (可选; obj 导入用, 无则 None)
"""
import math
import os


class Mesh:
    def __init__(self, vertices, faces, face_colors, normals=None, uvs=None):
        self.vertices = list(vertices)
        self.faces = [tuple(f) for f in faces]
        self.face_colors = list(face_colors)
        self.normals = list(normals) if normals is not None else None
        self.uvs = list(uvs) if uvs is not None else None
        self._validate()

    def _validate(self):
        # nosec B101: 开发期数据结构一致性校验 (断言失败=代码 bug, 非用户输入路径;
        # Loom 运行/打包均不启用 -O, assert 始终生效)
        assert len(self.faces) == len(self.face_colors), "面数与颜色数不一致"
        nv = len(self.vertices)
        for (a, b, c) in self.faces:
            assert 0 <= a < nv and 0 <= b < nv and 0 <= c < nv, "面索引越界"
        assert all(len(v) == 3 for v in self.vertices), "顶点必须是三维"
        if self.normals is not None:
            assert len(self.normals) == nv, "法线数与顶点数不一致"
        if self.uvs is not None:
            assert len(self.uvs) == nv, "UV 数与顶点数不一致"


def create_cube(size):
    """立方体: 8 唯一顶点 / 12 面, 6 面色 (绕序与旧版一致, 法线朝外)"""
    s = size / 2.0
    vertices = [
        (-s, -s, -s),  # 0
        (s, -s, -s),   # 1
        (s, s, -s),    # 2
        (-s, s, -s),   # 3
        (-s, -s, s),   # 4
        (s, -s, s),    # 5
        (s, s, s),     # 6
        (-s, s, s),    # 7
    ]
    # 前 后 左 右 顶 底 (每面 2 个三角形, 逆时针朝外)
    faces = [
        (4, 5, 6), (4, 6, 7),
        (1, 0, 3), (1, 3, 2),
        (0, 4, 7), (0, 7, 3),
        (5, 1, 2), (5, 2, 6),
        (7, 6, 2), (7, 2, 3),
        (0, 1, 5), (0, 5, 4),
    ]
    colors = ['#FF5555', '#55FF55', '#5555FF', '#FFFF55', '#55FFFF', '#FF55FF']
    face_colors = []
    for c in colors:
        face_colors.extend([c, c])
    mesh = Mesh(vertices, faces, face_colors)
    mesh.primitive = 'cube'
    mesh.params = {'size': size}
    return mesh


def create_sphere(radius, stacks=14, slices=28):
    """UV 球体: (stacks+1)*(slices+1) 唯一顶点, 2*stacks*slices 面, 法线朝外"""
    vertices = []
    for i in range(stacks + 1):
        phi = math.pi * i / stacks          # 0..pi (北极..南极)
        cp_, sp_ = math.cos(phi), math.sin(phi)
        for j in range(slices + 1):
            theta = 2 * math.pi * j / slices  # 0..2pi
            ct, st = math.cos(theta), math.sin(theta)
            vertices.append((radius * sp_ * ct, radius * cp_, radius * sp_ * st))

    def vid(i, j):
        return i * (slices + 1) + j

    faces = []
    for i in range(stacks):
        for j in range(slices):
            a, b, c, d = vid(i, j), vid(i, j + 1), vid(i + 1, j), vid(i + 1, j + 1)
            faces.append((a, d, c))   # 已验证: 法线朝外
            faces.append((a, b, d))

    # 按纬度渐变: 顶部亮白 -> 赤道天蓝 -> 底部深蓝
    face_colors = []
    for i in range(stacks):
        t = i / (stacks - 1) if stacks > 1 else 0.5
        col = _lat_color(t)
        for _ in range(slices):
            face_colors.append(col)
            face_colors.append(col)
    mesh = Mesh(vertices, faces, face_colors)
    mesh.primitive = 'sphere'
    mesh.params = {'radius': radius, 'stacks': stacks, 'slices': slices}
    return mesh


def create_plane(width=8.0, depth=8.0):
    """平面: 4 顶点 / 2 三角形, 法线 +y 朝上 (地面), 灰色"""
    w, d = width / 2.0, depth / 2.0
    vertices = [(-w, 0, -d), (w, 0, -d), (w, 0, d), (-w, 0, d)]
    faces = [(0, 2, 1), (0, 3, 2)]   # cross 沿 +y (朝上)
    face_colors = ["#888888", "#888888"]
    mesh = Mesh(vertices, faces, face_colors)
    mesh.primitive = 'plane'
    mesh.params = {'width': width, 'depth': depth}
    return mesh


def spec_to_mesh(spec_type, params):
    """基元类型 + 参数 -> Mesh (场景序列化加载用). 附加 primitive/params 供 add_model 读取"""
    params = dict(params or {})
    if spec_type == "cube":
        mesh = create_cube(params.get("size", 1.0))
    elif spec_type == "sphere":
        mesh = create_sphere(params.get("radius", 1.0),
                             params.get("stacks", 14), params.get("slices", 28))
    elif spec_type == "plane":
        mesh = create_plane(params.get("width", 8.0), params.get("depth", 8.0))
    else:
        raise ValueError("未知基元类型: %r" % (spec_type,))
    mesh.primitive = spec_type
    mesh.params = dict(params)
    return mesh


def _lat_color(t):
    """按纬度 t (0=顶, 1=底) 插值蓝白渐变"""
    r = int(255 - 215 * t)
    g = int(240 - 160 * t)
    b = int(255 - 55 * t)
    return "#%02x%02x%02x" % (r, g, b)


def mesh_validate(mesh):
    """自检: 面数/颜色数一致, 球体法线朝外 (法线·(质心-中心) > 0)"""
    n = len(mesh.vertices)
    f = len(mesh.faces)
    assert len(mesh.face_colors) == f, "颜色数 != 面数"
    # 逐面法线朝外检查 (以网格几何中心为原点)
    cx = sum(v[0] for v in mesh.vertices) / n
    cy = sum(v[1] for v in mesh.vertices) / n
    cz = sum(v[2] for v in mesh.vertices) / n
    outward_min = float('inf')
    for (a, b, c) in mesh.faces:
        p1, p2, p3 = mesh.vertices[a], mesh.vertices[b], mesh.vertices[c]
        u = (p2[0] - p1[0], p2[1] - p1[1], p2[2] - p1[2])
        v = (p3[0] - p1[0], p3[1] - p1[1], p3[2] - p1[2])
        nx = u[1] * v[2] - u[2] * v[1]
        ny = u[2] * v[0] - u[0] * v[2]
        nz = u[0] * v[1] - u[1] * v[0]
        # 质心相对中心
        gx = (p1[0] + p2[0] + p3[0]) / 3 - cx
        gy = (p1[1] + p2[1] + p3[1]) / 3 - cy
        gz = (p1[2] + p2[2] + p3[2]) / 3 - cz
        dot = nx * gx + ny * gy + nz * gz
        outward_min = min(outward_min, dot)
    return outward_min


# ---- OBJ 导入辅助 ----
_DEFAULT_OBJ_COLOR = "#AAAAAA"   # 缺失 MTL/颜色时的默认面色 (与旧版一致)
# 2026-08-20 安全加固 (Qoder 报告低危5): OBJ 资源上限 (恶意超大文件内存 DoS 防护)
_OBJ_MAX_VERTS = 1_000_000
_OBJ_MAX_FACES = 2_000_000


def _parse_face_corner(tok):
    """'v' / 'v/vt' / 'v//vn' / 'v/vt/vn' -> (v, vt, vn) int (可为负); 解析失败返回 None."""
    if not tok:
        return None
    parts = tok.split('/')
    try:
        v = int(parts[0])
    except (ValueError, IndexError):
        return None
    vt = int(parts[1]) if len(parts) >= 2 and parts[1] else None
    vn = int(parts[2]) if len(parts) >= 3 and parts[2] else None
    return (v, vt, vn)


def _resolve_idx(i, count):
    """1-based OBJ 索引 (支持负索引: -1 = 最后一个) -> 0-based; 越界/None 返回 None."""
    if i is None:
        return None
    if i < 0:
        i = count + 1 + i
    i -= 1
    return i if 0 <= i < count else None


def _resolve_corner(corner, nv, nvt, nvn):
    """面角 (v, vt, vn) int -> (v_idx, vt_idx, vn_idx) 0-based (分量可为 None); v 无效返回 None."""
    v, vt, vn = corner
    vi = _resolve_idx(v, nv)
    if vi is None:
        return None
    return (vi, _resolve_idx(vt, nvt), _resolve_idx(vn, nvn))


def _normalize3(n):
    """向量归一化; 零向量 -> +z 兜底."""
    x, y, z = n
    ln = math.sqrt(x * x + y * y + z * z)
    if ln < 1e-12:
        return (0.0, 0.0, 1.0)
    return (x / ln, y / ln, z / ln)


def _kdt_to_hex(r, g, b):
    """MTL Kd 分量 (0..1 浮点 或 0..255 整数) -> '#RRGGBB'."""
    vals = [r, g, b]
    if max(vals) > 1.0:
        vals = [v / 255.0 for v in vals]

    def ch(v):
        return max(0, min(255, int(round(v * 255.0))))
    return "#%02x%02x%02x" % (ch(vals[0]), ch(vals[1]), ch(vals[2]))


def _load_mtl_colors(path):
    """读取 .mtl 文件 -> {mtl名: '#RRGGBB'} (取 Kd 漫反射色). 缺失/损坏返回 {}."""
    colors = {}
    cur = None
    try:
        f = open(path, 'r', encoding='utf-8', errors='ignore')
    except OSError:
        return {}
    with f:
        for line in f:
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            parts = line.split()
            if not parts:
                continue
            if parts[0] == 'newmtl' and len(parts) >= 2:
                cur = parts[1]
            elif parts[0] == 'Kd' and cur is not None and len(parts) >= 4:
                try:
                    colors[cur] = _kdt_to_hex(float(parts[1]), float(parts[2]),
                                              float(parts[3]))
                except ValueError:
                    pass
    return colors


def load_obj(path):
    """解析 Wavefront .obj -> Mesh (对齐 Unity 导入管线).

    解析:
      v       顶点位置 (x,y,z)
      vn      顶点法线 (nx,ny,nz) —— 有 vn 用 obj 法线
      vt      纹理坐标 (u,v) —— 存进 mesh.uvs (渲染暂不使用, 为后续纹理打基础)
      f       面 (v/vt/vn 任意组合, 1-based, 支持负索引; 四边面扇形三角化)
      usemtl + mtllib —— 读同目录 .mtl 的 Kd 漫反射色作对应材质组面色
    法线策略 (对齐 Unity 默认):
      有 vn 用 obj 法线; 无 vn 自动计算平滑法线 (相邻面法线平均).
    顶点槽: 按 (v, vt, vn) 三元组去重 —— 硬边/UV 缝处同一位置拆成多个顶点,
      与 Unity 导入一致 (法线/UV 逐顶点对齐).
    单位/轴向: OBJ 惯例 Y-up 与 Loom 引擎一致, 不缩放、不转轴 (Unity 导入 .obj
      默认 scale=1 且同为 Y-up, 故原样读入即可).
    返回 Mesh (附 normals/uvs, primitive='obj', params={'obj': 绝对路径}).
    失败 (无顶点/无面/文件错) 抛 ValueError.
    """
    vs, vts, vns = [], [], []
    mtllibs = []
    raw_faces = []          # [(corner 列表, 当前材质名)]
    cur_mtl = None
    try:
        f = open(path, 'r', encoding='utf-8', errors='ignore')
    except OSError as e:
        raise ValueError("无法打开 obj: %s" % e)
    with f:
        for line in f:
            line = line.strip()
            if not line or line[0] == '#':
                continue
            parts = line.split()
            if not parts:
                continue
            tag = parts[0]
            if tag == 'v' and len(parts) >= 4:
                if len(vs) >= _OBJ_MAX_VERTS:
                    raise ValueError("obj 顶点数超限: %s" % path)
                try:
                    vs.append((float(parts[1]), float(parts[2]), float(parts[3])))
                except ValueError:
                    pass
            elif tag == 'vt' and len(parts) >= 3:
                try:
                    vts.append((float(parts[1]), float(parts[2])))
                except ValueError:
                    pass
            elif tag == 'vn' and len(parts) >= 4:
                try:
                    vns.append((float(parts[1]), float(parts[2]), float(parts[3])))
                except ValueError:
                    pass
            elif tag == 'mtllib':
                mtllibs.extend(parts[1:])
            elif tag == 'usemtl':
                cur_mtl = parts[1] if len(parts) >= 2 else None
            elif tag == 'f':
                if len(raw_faces) >= _OBJ_MAX_FACES:
                    raise ValueError("obj 面数超限: %s" % path)
                corners = [c for c in (_parse_face_corner(t) for t in parts[1:])
                           if c is not None]
                if len(corners) >= 3:
                    raw_faces.append((corners, cur_mtl))
    if not vs or not raw_faces:
        raise ValueError("obj 无顶点/面: %s" % path)

    # MTL 材质颜色 (与 .obj 同目录, 多文件合并)
    obj_dir = os.path.dirname(os.path.abspath(path))
    mtl_colors = {}
    for name in mtllibs:
        mtl_colors.update(_load_mtl_colors(os.path.join(obj_dir, os.path.basename(name))))

    nv, nvt, nvn = len(vs), len(vts), len(vns)

    # 顶点槽: 按 (v, vt, vn) 去重, 逐槽记录位置/UV/法线/原始 v 索引 (平滑法线用)
    slot_index = {}
    slots = []               # [{'pos':.., 'uv':..|None, 'vn':..|None, 'v_idx':..}]

    def slot_of(v_idx, vt_idx, vn_idx):
        key = (v_idx, vt_idx, vn_idx)
        s = slot_index.get(key)
        if s is None:
            s = len(slots)
            slot_index[key] = s
            slots.append({'pos': vs[v_idx],
                          'uv': vts[vt_idx] if vt_idx is not None else None,
                          'vn': vns[vn_idx] if vn_idx is not None else None,
                          'v_idx': v_idx})
        return s

    faces = []
    face_colors = []
    for corners, mtl in raw_faces:
        idx = [_resolve_corner(c, nv, nvt, nvn) for c in corners]
        idx = [c for c in idx if c is not None]
        if len(idx) < 3:
            continue
        col = mtl_colors.get(mtl) if mtl else None
        if not col:
            col = _DEFAULT_OBJ_COLOR
        a = slot_of(*idx[0])
        for i in range(1, len(idx) - 1):          # 扇形三角化 (与旧版一致)
            faces.append((a, slot_of(*idx[i]), slot_of(*idx[i + 1])))
            face_colors.append(col)
    if not faces:
        raise ValueError("obj 无有效面: %s" % path)

    vertices = [s['pos'] for s in slots]

    # 平滑法线 (供无 vn 的槽使用): 按原始 v 索引累加相邻面法线再归一化.
    # 简化对齐 Unity"自动平滑": 全平滑 (不按平滑角劈硬边); 有 vn 时逐槽直用 vn.
    smooth_sum = [[0.0, 0.0, 0.0] for _ in range(nv)]
    for (a, b, c) in faces:
        p0, p1, p2 = vertices[a], vertices[b], vertices[c]
        u = (p1[0] - p0[0], p1[1] - p0[1], p1[2] - p0[2])
        w = (p2[0] - p0[0], p2[1] - p0[1], p2[2] - p0[2])
        fn = (u[1] * w[2] - u[2] * w[1],
              u[2] * w[0] - u[0] * w[2],
              u[0] * w[1] - u[1] * w[0])
        for s in (a, b, c):
            vi = slots[s]['v_idx']
            smooth_sum[vi][0] += fn[0]
            smooth_sum[vi][1] += fn[1]
            smooth_sum[vi][2] += fn[2]

    normals = []
    for s in slots:
        if s['vn'] is not None:
            normals.append(_normalize3(s['vn']))
        else:
            normals.append(_normalize3(smooth_sum[s['v_idx']]))

    uvs = None
    if nvt:
        uvs = [s['uv'] if s['uv'] is not None else (0.0, 0.0) for s in slots]

    mesh = Mesh(vertices, faces, face_colors, normals=normals, uvs=uvs)
    mesh.primitive = 'obj'                     # sceneio 序列化 type=obj, 重读此路径
    mesh.params = {'obj': os.path.abspath(path)}
    return mesh
