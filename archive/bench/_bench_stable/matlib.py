# -*- coding: utf-8 -*-
"""
matlib.py — 4×4 矩阵数学库（行主序，行向量约定）

约定:
  - 矩阵为 4×4 数组 M, 点用行向量 [x, y, z, w], 变换为 v' = v @ M。
  - 组合顺序: mvp = model @ view @ proj (先 model, 后 view, 再 proj)。
  - 所有函数接受 xp (numpy 或 cupy) 以兼容 CPU/GPU 双后端。

提供的矩阵:
  - model:  mat4_translation / mat4_rotation（位置+旋转, 数值等价旧 rotate_point）
            组合顺序: 行向量下必须 S @ R @ T (先缩放→再旋转→再平移).
            写 T @ R @ S 会把 position 也旋转掉 -> 绕场景原点转 + 旋转后移动乱飞 (已踩坑)
  - view:   mat4_view_yaw_pitch（由相机位置+偏航/俯仰构造, 与旧 project_point 的
            相机空间数学数值一致, 见 mat_validate；前方 z_view > 0, det=+1 无反射）
  - proj:   mat4_perspective（透视投影, 前方 z_view > 0, clip.w = z_view,
            clip.z 单调映射 [0,1] 供 GPU 深度测试）
  - 通用:   mat4_identity / mat4_look_at
"""
import math


def mat4_identity(xp):
    return xp.eye(4, dtype=xp.float64)


def mat4_translation(xp, tx, ty, tz):
    """行主序平移矩阵 (v @ T 将点平移 (tx,ty,tz))"""
    return xp.asarray([
        [1, 0, 0, 0],
        [0, 1, 0, 0],
        [0, 0, 1, 0],
        [tx, ty, tz, 1],
    ], dtype=xp.float64)


def mat4_scale(xp, sx, sy, sz):
    """行主序缩放矩阵 (v @ S 将点缩放 (sx,sy,sz))"""
    return xp.asarray([
        [sx, 0, 0, 0],
        [0, sy, 0, 0],
        [0, 0, sz, 0],
        [0, 0, 0, 1],
    ], dtype=xp.float64)


def mat4_rotation(xp, rx, ry, rz):
    """行主序旋转矩阵, 数值等价旧 rotate_point（先绕X, 再绕Y, 再绕Z）"""
    cx, sx = math.cos(rx), math.sin(rx)
    cy, sy = math.cos(ry), math.sin(ry)
    cz, sz = math.cos(rz), math.sin(rz)
    # 行主序 = 列主序旋转矩阵的转置, 乘积顺序 Rx.T @ Ry.T @ Rz.T = (Rz@Ry@Rx).T
    rx_row = xp.asarray([
        [1, 0, 0, 0],
        [0, cx, sx, 0],
        [0, -sx, cx, 0],
        [0, 0, 0, 1],
    ], dtype=xp.float64)
    ry_row = xp.asarray([
        [cy, 0, -sy, 0],
        [0, 1, 0, 0],
        [sy, 0, cy, 0],
        [0, 0, 0, 1],
    ], dtype=xp.float64)
    rz_row = xp.asarray([
        [cz, sz, 0, 0],
        [-sz, cz, 0, 0],
        [0, 0, 1, 0],
        [0, 0, 0, 1],
    ], dtype=xp.float64)
    return rx_row @ ry_row @ rz_row


def decompose_euler(R):
    """
    把旋转矩阵 R 分解回欧拉角 (α,β,γ), 与 mat4_rotation 的约定一致
    (行向量, 等价 point @ Rx(α) @ Ry(β) @ Rz(γ), 即"先绕X再绕Y再绕Z").
    R 为 3x3 或 4x4 (取左上 3x3). 用于 gizmo 世界旋转增量 -> 局部欧拉角.

    推导: R = Rx@Ry@Rz 时
      R[0,2] = -sinβ,  R[1,2] = sinα·cosβ,  R[2,2] = cosα·cosβ
      R[0,1] = cosβ·sinγ, R[0,0] = cosβ·cosγ
    -> β = asin(-R[0,2]); α = atan2(R[1,2], R[2,2]); γ = atan2(R[0,1], R[0,0])
    """
    import numpy as _np
    R = _np.asarray(R, dtype=_np.float64)
    r = R[:3, :3]
    beta = math.asin(max(-1.0, min(1.0, -float(r[0, 2]))))
    cb = math.cos(beta)
    if abs(cb) < 1e-9:      # 万向锁: 令 γ=0, α 从剩余分量取
        alpha = math.atan2(float(r[1, 0]), float(r[1, 1]))
        gamma = 0.0
    else:
        alpha = math.atan2(float(r[1, 2]), float(r[2, 2]))
        gamma = math.atan2(float(r[0, 1]), float(r[0, 0]))
    return (alpha, beta, gamma)


def mat4_perspective(xp, fov_y, aspect, near, far):
    """透视投影（行主序）. 输入 view 空间（前方 z_view>0, 见 mat4_view_yaw_pitch）,
    输出 clip 空间, clip.w = z_view (正前方 w>0), x/y 按 f/z 透视缩放.
    clip.z 映射到 [0,1] 单调递增 (near->0, far->1): 供 OpenGL 硬件深度测试使用;
    CPU 画家路径只读 clip.w, 不受影响."""
    f = 1.0 / math.tan(fov_y / 2.0)
    return xp.asarray([
        [f / aspect, 0, 0, 0],
        [0, f, 0, 0],
        [0, 0, far / (far - near), 1],
        [0, 0, -near * far / (far - near), 0],
    ], dtype=xp.float64)


def mat4_look_at(xp, eye, target, up):
    """标准视图矩阵（行主序）. eye/target/up 为 (x,y,z) 三元组, 前方 z_view < 0"""
    fx, fy, fz = target[0] - eye[0], target[1] - eye[1], target[2] - eye[2]
    fl = math.sqrt(fx * fx + fy * fy + fz * fz)
    fx, fy, fz = fx / fl, fy / fl, fz / fl
    ux, uy, uz = up
    sx = fy * uz - fz * uy
    sy = fz * ux - fx * uz
    sz = fx * uy - fy * ux
    sl = math.sqrt(sx * sx + sy * sy + sz * sz)
    sx, sy, sz = sx / sl, sy / sl, sz / sl
    ux = sy * fz - sz * fy
    uy = sz * fx - sx * fz
    uz = sx * fy - sy * fx
    ex, ey, ez = eye
    return xp.asarray([
        [sx, ux, -fx, 0],
        [sy, uy, -fy, 0],
        [sz, uz, -fz, 0],
        [-(sx * ex + sy * ey + sz * ez), -(ux * ex + uy * ey + uz * ez),
         fx * ex + fy * ey + fz * ez, 1],
    ], dtype=xp.float64)


def mat4_view_yaw_pitch(xp, camera, yaw, pitch, roll=0.0):
    """
    由相机位置 + 偏航/俯仰构造 view 矩阵（行主序, det=+1 无反射）.
    与旧 project_point 的相机空间数学数值一致（见 mat_validate）:
      x_view=tx, y_view=fy, z_view=+fz（前方为正, 面向相机=法线 nz<0）
    三基 ex/ey/ez 作列, 前方为 ez（+z_view）, 纯旋转不含镜像 → 叉积法线不被翻转.
    投影配合 mat4_perspective（clip.w = z_view）.
    M41: 新增 roll (弧度, 默认 0) —— 绕视线方向 ez 倾斜 (FPS 侧头/被击倒摄像头歪斜).
    ex'/ey' 绕 ez 转 θ: ex'=ex·cosθ+ey·sinθ, ey'=ey·cosθ−ex·sinθ (已验 ez×ex=ey, ez×ey=−ex).
    θ 取 −roll (sn=−sin roll, 与 LightState.up_vector M30 负绕向一致); roll=0 恒等.
    """
    cy, sy = math.cos(yaw), math.sin(yaw)
    cp, sp = math.cos(pitch), math.sin(pitch)
    # 旧投影逻辑的 view 正交基（由 yaw/pitch 定义）
    ex = (cy, 0.0, -sy)
    ey = (-sy * sp, cp, -cy * sp)
    ez = (sy * cp, sp, cy * cp)   # 前方 (+z_view 方向)
    if roll:
        cr = math.cos(roll)
        sr = math.sin(roll)
        sn = -sr                  # M41: 负绕向, 与光源 M30 修正一致 (实测反则翻这里)
        exn = (ex[0] * cr + ey[0] * sn, ex[1] * cr + ey[1] * sn,
               ex[2] * cr + ey[2] * sn)
        eyn = (ey[0] * cr - ex[0] * sn, ey[1] * cr - ex[1] * sn,
               ey[2] * cr - ex[2] * sn)
        ex, ey = exn, eyn
    cx, cyy, cz = camera
    tex = -(ex[0] * cx + ex[1] * cyy + ex[2] * cz)
    tey = -(ey[0] * cx + ey[1] * cyy + ey[2] * cz)
    tez = -(ez[0] * cx + ez[1] * cyy + ez[2] * cz)
    return xp.asarray([
        [ex[0], ey[0], ez[0], 0],
        [ex[1], ey[1], ez[1], 0],
        [ex[2], ey[2], ez[2], 0],
        [tex, tey, tez, 1],
    ], dtype=xp.float64)


def view_basis_to_angles(ex, ey, ez):
    """mat4_view_yaw_pitch 旋转部分的逆 (相机物体化 2026-08-16):
    给定世界/父空间正交基 (ex,ey,ez) 行向量 (+z_view 方向 = ez), 还原
    (yaw, pitch, roll) 弧度, 使 mat4_view_yaw_pitch 的旋转部分重建同一基.
    与 mat4_view_yaw_pitch 的 trig / 负绕向 (sn=-sin roll) 约定一致.
    math:
      ez = (sin yaw·cos pitch, sin pitch, cos yaw·cos pitch)
        -> pitch = asin(clamp(ez.y))     ([-pi/2, pi/2])
        -> yaw   = atan2(ez.x, ez.z)
      未 roll 基: ex_u=(cos yaw,0,-sin yaw), ey_u=(-sin yaw·sin pitch, cos pitch, -cos yaw·sin pitch)
      roll 约定: ex_w = ex_u·cos(r) - ey_u·sin(r), ey_w = ey_u·cos(r) + ex_u·sin(r)
        -> cos(r)=dot(ex_w,ex_u), sin(r)=dot(ey_w,ex_u)  => roll=atan2(sin_r, cos_r)
    ±90° 万向锁时 yaw/roll 退化, 但重建的基仍精确 (渲染正确)."""
    pitch = math.asin(max(-1.0, min(1.0, ez[1])))
    yaw = math.atan2(ez[0], ez[2])
    cy, sy = math.cos(yaw), math.sin(yaw)
    cp, sp = math.cos(pitch), math.sin(pitch)
    ex_u = (cy, 0.0, -sy)
    ey_u = (-sy * sp, cp, -cy * sp)
    cos_r = ex[0] * ex_u[0] + ex[1] * ex_u[1] + ex[2] * ex_u[2]
    sin_r = ey[0] * ex_u[0] + ey[1] * ex_u[1] + ey[2] * ex_u[2]
    return yaw, pitch, math.atan2(sin_r, cos_r)


def mat4_ortho(xp, left, right, bottom, top, near, far):
    """正交投影（行主序, 与 mat4_perspective 同构）.
    clip.w = 1; clip.z 映射 [near->0, far->1]（配合引擎深度测试约定）.
    供光源正交阴影投影（平行光）使用."""
    return xp.asarray([
        [2 / (right - left), 0, 0, 0],
        [0, 2 / (top - bottom), 0, 0],
        [0, 0, 1 / (far - near), 0],
        [-(right + left) / (right - left), -(top + bottom) / (top - bottom),
         -near / (far - near), 1],
    ], dtype=xp.float64)


def mat4_view_forward(xp, eye, forward, up):
    """沿 forward 方向观察的 view 矩阵（行主序, 引擎约定 +z_view=forward, det=+1）.
    eye/forward/up 为三元组; forward 归一化, up 用于定 xy 朝向（自动正交化为右手基:
    right=forward×up, up'=forward×right）. 供光源视图（平行光/点光各面）使用."""
    fx, fy, fz = forward
    fl = math.sqrt(fx * fx + fy * fy + fz * fz)
    fx, fy, fz = fx / fl, fy / fl, fz / fl
    ux, uy, uz = up
    rx = fy * uz - fz * uy              # right = forward × up
    ry = fz * ux - fx * uz
    rz = fx * uy - fy * ux
    rl = math.sqrt(rx * rx + ry * ry + rz * rz) or 1.0
    rx, ry, rz = rx / rl, ry / rl, rz / rl
    px = fy * rz - fz * ry              # up' = forward × right
    py = fz * rx - fx * rz
    pz = fx * ry - fy * rx
    cx, cy, cz = eye
    tex = -(rx * cx + ry * cy + rz * cz)
    tey = -(px * cx + py * cy + pz * cz)
    tez = -(fx * cx + fy * cy + fz * cz)
    return xp.asarray([
        [rx, px, fx, 0],
        [ry, py, fy, 0],
        [rz, pz, fz, 0],
        [tex, tey, tez, 1],
    ], dtype=xp.float64)


def mat_validate():
    """自检: mat4_rotation / mat4_view_yaw_pitch 与旧标量 rotate_point / project_point
    数值一致（max|diff| < 1e-9）"""
    import numpy as np
    xp = np
    rng = np.random.default_rng(42)
    max_err = 0.0

    def old_rotate_point(p, rx, ry, rz):
        x, y, z = p
        y2 = y * math.cos(rx) - z * math.sin(rx)
        z2 = y * math.sin(rx) + z * math.cos(rx)
        y, z = y2, z2
        x3 = x * math.cos(ry) + z * math.sin(ry)
        z3 = -x * math.sin(ry) + z * math.cos(ry)
        x, z = x3, z3
        x4 = x * math.cos(rz) - y * math.sin(rz)
        y4 = x * math.sin(rz) + y * math.cos(rz)
        return (x4, y4, z)  # 绕Z不改变z

    for _ in range(200):
        rx, ry, rz = rng.uniform(-3.14, 3.14), rng.uniform(-3.14, 3.14), rng.uniform(-3.14, 3.14)
        p = rng.uniform(-5, 5, size=3)
        ref = old_rotate_point(tuple(p), rx, ry, rz)
        M = mat4_rotation(xp, rx, ry, rz)
        got = (np.concatenate([p, [1.0]]) @ M)[:3]
        max_err = max(max_err, float(np.max(np.abs(got - np.asarray(ref)))))

    def old_cam_space(p, cam, yaw, pitch):
        rx_, ry_, rz_ = p[0] - cam[0], p[1] - cam[1], p[2] - cam[2]
        cy, sy = math.cos(yaw), math.sin(yaw)
        tx = rx_ * cy - rz_ * sy
        tz = rx_ * sy + rz_ * cy
        cp, sp = math.cos(pitch), math.sin(pitch)
        fy = ry_ * cp - tz * sp
        fz = ry_ * sp + tz * cp
        return (tx, fy, fz)

    for _ in range(200):
        cam = rng.uniform(-3, 3, size=3)
        yaw = rng.uniform(-3, 3)
        pitch = rng.uniform(-1.5, 1.5)
        p = rng.uniform(-5, 5, size=3)
        V = mat4_view_yaw_pitch(xp, tuple(cam), yaw, pitch)
        got = np.concatenate([p, [1.0]]) @ V
        ref = old_cam_space(p, cam, yaw, pitch)
        # view 前方为正 (z_view = +旧 fz)
        err = max(abs(float(got[0]) - ref[0]),
                  abs(float(got[1]) - ref[1]),
                  abs(float(got[2]) - ref[2]))
        max_err = max(max_err, err)

    return max_err
