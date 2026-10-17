# -*- coding: utf-8 -*-
"""一次性诊断: M29 阴影异常 (正面黑 + 大片黑区). 读回阴影贴图 + 渲染采样, 量化.
运行: py -3.12 "Loom\tests\_tmp\diag_shadow.py"   (子进程+超时, 别前台跑)"""
import sys, os
_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, _ROOT)
os.chdir(_ROOT)
import pygame
import numpy as np
import editor
from mesh import create_cube, create_plane

def check(label, cond, detail=""):
    print(("PASS " if cond else "FAIL ") + label + ("  " + detail if detail else ""))

def frames(e, n=6):
    for _ in range(n):
        e.render(0.016)

def capture(e):
    rb = e.ctx.renderbuffer((e.width, e.height), components=4)
    fbo = e.ctx.framebuffer(color_attachments=[rb])
    e.ctx.copy_framebuffer(fbo, e.ctx.screen)
    data = fbo.read(components=4)
    rb.release(); fbo.release()
    return np.flipud(np.frombuffer(data, dtype='u1').reshape(
        e.height, e.width, 4)[:, :, :3].astype(float) / 255.0)

def samp_at(e, img, w):
    """世界坐标 -> 屏幕像素 5x5 邻域 (返回 max 亮度 + max RGB)"""
    h = np.array([w[0], w[1], w[2], 1.0]) @ e._vp
    ndc = h[:3] / h[3]
    sx = int((ndc[0] + 1) / 2 * e.width); sy = int((1 - (ndc[1] + 1) / 2) * e.height)
    if not (0 <= sx < e.width and 0 <= sy < e.height):
        return None, None, (sx, sy)
    patch = img[max(0, sy-2):sy+3, max(0, sx-2):sx+3].reshape(-1, 3)
    return float(patch.max(axis=0).max()), tuple(round(float(c), 3) for c in patch.max(axis=0)), (sx, sy)

print("== 场景搭建 (同 M29 集成测试): 640x480, 平面+立方体+平行光向下 ==")
e = editor.EditorApp(640, 480)
e.clear_scene()
e.add_model(create_plane(20, 20), editor.Point3D(0, 0, 0), editor.Point3D(0, 0, 0), normal_mode='flat', name="地面")
e.add_model(create_cube(1.0), editor.Point3D(0, 1.0, 0), editor.Point3D(0, 0, 0), normal_mode='flat', name="立方体")
e.add_light('directional', position=(0, 8, 0), direction=(0, -1, 0),
            shadow=True, mode='full', shape='circle', size=5.0)
e.selected_index = -1
e.camera_target = (0, 0.5, 0); e.camera_distance = 8
e.camera_yaw = 0.0; e.camera_pitch = 0.0
e.orbit_mode = True; e.apply_orbit_camera()
# monkeypatch: 深度 pass 进出时打印实际 viewport
_orig_rtsm = e._render_to_shadow_map
def _patched_rtsm(sm, vp_list):
    print("  深度pass进入 viewport=%s  fbo尺寸=%s" % (e.ctx.viewport, (sm['tex'][0].size, sm['tex'][0].size)))
    _orig_rtsm(sm, vp_list)
    print("  深度pass退出 viewport=%s" % (e.ctx.viewport,))
e._render_to_shadow_map = _patched_rtsm
frames(e, 4)

print("\n== 阴影深度 pass 视口检查 ==")
vp_before = e.ctx.viewport
e.render(0.016)
vp_after = e.ctx.viewport
print("render 前 ctx.viewport =", vp_before)
print("render 后 ctx.viewport =", vp_after, "  (深度 pass 若未改视口, 仍是窗口尺寸 -> 阴影贴图被压扁)")

print("\n== 阴影贴图深度纹理内容 ==")
sm = next(iter(e._shadow_maps.values()))
res = e._shadow_res
print("阴影贴图尺寸 = %dx%d (方向光)" % (res, res))
try:
    raw = sm['tex'][0].read()          # 直接读深度纹理像素
    print("tex.read() 字节数 =", len(raw), " 每像素字节 =", len(raw) / (res * res))
    arr = np.frombuffer(raw, dtype='f4').reshape(res, res)
except Exception as ex:
    print("depth 读取失败:", repr(ex))
    arr = None

if arr is not None:
    frac1 = float((arr >= 0.999).mean())
    frac_drawn = float((arr <= 0.5).mean())
    frac_mid = float(((arr > 0.5) & (arr < 0.999)).mean())
    print("内容分布: 值==1.0(未绘制/清除)占 %.1f%%, 值<=0.5(已绘制)占 %.1f%%, 中间值 %.1f%%" % (
        frac1 * 100, frac_drawn * 100, frac_mid * 100))
    print("值域: min=%.4f max=%.4f mean=%.4f" % (arr.min(), arr.max(), arr.mean()))
    # 非清除区 (值<0.999) 包围盒: 确定深度 pass 实际视口占比
    ys, xs = np.where(arr < 0.999)
    if len(ys):
        print("非清除区包围盒: U[%.3f,%.3f] V[%.3f,%.3f] (像素 [%d,%d]x[%d,%d])"
              % (xs.min()/res, xs.max()/res, ys.min()/res, ys.max()/res,
                 xs.min(), xs.max(), ys.min(), ys.max()))
        print("  -> 若约为 [0,%.3f]x[0,%.3f] 即深度 pass 视口=窗口尺寸; 若满幅 [0,1]x[0,1] 即正常"
              % (e.width/res, e.height/res))
    # 8x6 数值网格 (每块 min): 直接看内容形状
    print("8x6 深度网格 (每块 min 值, '.'=已清除~1.0):")
    for j in range(6):
        row = []
        for i in range(8):
            blk = arr[j*res//6:(j+1)*res//6, i*res//8:(i+1)*res//8]
            row.append("%.2f" % blk.min() if blk.min() < 0.999 else " .  ")
        print("  " + " ".join(row))
    # ASCII 热图 (下采样 64x48): 显示内容在贴图的哪个区域
    h, w = arr.shape
    gx, gy = 64, 48
    stepx, stepy = w // gx, h // gy
    chars = ' .:-=+*#%@'
    print("\n阴影贴图内容分布图 (水平=U, 垂直=V; 亮色=有深度内容, 空格=清除区=主pass判黑):")
    print('+' + '-' * gx + '+')
    for j in range(gy):
        row = []
        for i in range(gx):
            blk = arr[j*stepy:(j+1)*stepy, i*stepx:(i+1)*stepx]
            v = float(blk.min())  # 该块最小深度值 -> 有物体就很小
            idx = min(len(chars) - 1, int(v * (len(chars) - 1)))
            row.append(chars[idx])
        print('|' + ''.join(row) + '|')
    print('+' + '-' * gx + '+')
    print("注: 内容集中在中心(87%=平面占正交范围)是正常的 (fbo.use 会自动设视口=贴图尺寸)。")
    print("本图用于检查阴影贴图是否有内容; 真实根因见记忆: 驱动比较方向 GEQUAL + 反转深度反了。")

print("\n== Python 侧重算 shader 阴影比较 ==")
if arr is not None and e.lights:
    lt = e.lights[0]
    vp = e._dir_light_vp(lt)
    bias = 0.002
    def py_shadow(w):
        lp = np.array([w[0], w[1], w[2], 1.0], dtype='f8') @ vp
        depth = (lp[2] / lp[3]) * 0.5 + 0.5
        uv = (lp[0] / lp[3]) * 0.5 + 0.5, (lp[1] / lp[3]) * 0.5 + 0.5
        ref = depth - bias
        if not (0 <= uv[0] <= 1 and 0 <= uv[1] <= 1):
            return ("uv出界->全亮", None, None, None)
        u = int(uv[0] * res); v = int(uv[1] * res)
        v = max(0, min(res-1, v)); u = max(0, min(res-1, u))
        stored = float(arr[v, u])
        return (stored >= ref, stored, ref, uv)   # 实测驱动 stored>=ref 照亮
    for name, w in [("立方体顶面", (0.0, 1.51, 0.0)),
                    ("立方体正前", (0.0, 1.0, 0.51)),
                    ("地面·正下(应阴影)", (0.0, 0.02, 0.0)),
                    ("地面·相机侧", (0.0, 0.02, 3.0)),
                    ("地面·远侧", (0.0, 0.02, -3.0))]:
        lit, stored, ref, uv = py_shadow(w)
        if lit is None:
            print("  %-16s %s" % (name, lit))
        else:
            print("  %-16s %s  stored'=%.4f  ref=%.4f  uv=%s" % (
                name, "照亮" if lit else "阴影!", stored, ref, tuple(round(x,3) for x in uv)))
    # 直接看立方体处阴影贴图值 (应为接近 1.0 的反转近深度)
    print("  立方体中心 贴图值 =", float(arr[res//2, res//2]),
          "  (远离处平面=%.4f)" % float(arr[res//2, int(res*0.93)]))
    # 中心窗口 max: 立方体若被深度剔除, 贴图里就找不到 0.15 的值
    cw = arr[res//2-8:res//2+8, res//2-8:res//2+8]
    print("  中心 16x16 窗口: min=%.4f max=%.4f (若 max 仍~0.10 -> 立方体被深度剔除未入贴图)" % (
        cw.min(), cw.max()))

print("\n== 探针: 加大 bias 应全亮 (验证阴影确实是压暗来源) ==")
if e.lights:
    e.prog['u_shadow_bias'].value = 1.0
    frames(e, 2)
    img_bias = capture(e)
    for name, w in [("地面·正下", (0.0, 0.02, 0.0)), ("地面·相机侧", (0.0, 0.02, 3.0))]:
        lum, rgb, px = samp_at(e, img_bias, w)
        print("  %-12s lum=%.3f (原阴影on=%.3f / 关阴影=%.3f)" % (
            name, lum, 0.541 if "正下" in name else 0.549,
            0.780 if "正下" in name else 0.784))
    e.prog['u_shadow_bias'].value = 0.002

print("\n== 最终渲染采样 (光照 + 阴影) ==")
img = capture(e)
# 保存 PNG 供目视检查
try:
    import pygame.image
    pygame.image.save(pygame.surfarray.make_surface(np.transpose((img*255).astype('u1'), (1,0,2))),
                      os.path.join(os.path.dirname(os.path.abspath(__file__)), "sh_on.png"))
except Exception as ex:
    print("PNG 保存失败:", repr(ex))
# 垂直亮度剖面 (x=320, y 140..285): 看立方体顶/正面/地面/阴影区域
print("垂直剖面 x=320 (每5px, y=140..285):")
lumcol = img[:, 320, :].max(axis=1)
for y in range(140, 285, 5):
    print("  y=%3d lum=%.3f %s" % (y, lumcol[y], "#" * int(lumcol[y] * 50)))

POINTS = [
    ("立方体顶面(朝光, 应亮)",      (0.0, 1.51, 0.0)),
    ("立方体正前面(朝相机, 应亮)",  (0.0, 1.0, 0.51)),
    ("地面·立方体正下(应在阴影)",   (0.0, 0.02, 0.0)),
    ("地面·相机侧(应亮)",           (0.0, 0.02, 3.0)),
    ("地面·远侧(应亮)",             (0.0, 0.02, -3.0)),
    ("地面·右侧(应亮)",             (3.0, 0.02, 0.0)),
]
for name, w in POINTS:
    lum, rgb, px = samp_at(e, img, w)
    if lum is None:
        print("%-22s 屏幕外 pixel=%s" % (name, px))
    else:
        print("%-22s lum=%.3f rgb=%s pixel=%s" % (name, lum, rgb, px))

# 与"关阴影"对照: 同一场景 shadow=False 应全亮 (无大片黑)
e2 = editor.EditorApp(640, 480)
e2.clear_scene()
e2.add_model(create_plane(20, 20), editor.Point3D(0, 0, 0), editor.Point3D(0, 0, 0), normal_mode='flat', name="地面")
e2.add_model(create_cube(1.0), editor.Point3D(0, 1.0, 0), editor.Point3D(0, 0, 0), normal_mode='flat', name="立方体")
e2.add_light('directional', position=(0, 8, 0), direction=(0, -1, 0),
             shadow=False, mode='full')
e2.selected_index = -1
e2.camera_target = (0, 0.5, 0); e2.camera_distance = 8
e2.camera_yaw = 0.0; e2.camera_pitch = 0.0
e2.orbit_mode = True; e2.apply_orbit_camera()
frames(e2, 4)
img2 = capture(e2)
print("\n== 对照 (shadow=False, 同一视角) ==")
for name, w in POINTS:
    lum, rgb, px = samp_at(e2, img2, w)
    if lum is None:
        print("%-22s 屏幕外 pixel=%s" % (name, px))
    else:
        print("%-22s lum=%.3f rgb=%s pixel=%s" % (name, lum, rgb, px))

# 对角方向光: 影子应明显落在立方体一侧地面 (真实太阳场景)
print("\n== 对角方向光 (direction=(-1,-2,-1)): 影子应落在 +X/+Z 侧地面 ==")
e4 = editor.EditorApp(640, 480)
e4.clear_scene()
e4.add_model(create_plane(20, 20), editor.Point3D(0, 0, 0), editor.Point3D(0, 0, 0), normal_mode='flat', name="地面")
e4.add_model(create_cube(1.0), editor.Point3D(0, 1.0, 0), editor.Point3D(0, 0, 0), normal_mode='flat', name="立方体")
e4.add_light('directional', position=(6, 10, 6), direction=(-1, -2, -1),
             shadow=True, mode='full')
e4.selected_index = -1
e4.camera_target = (0, 1.0, 0); e4.camera_distance = 10
e4.camera_yaw = 0.6; e4.camera_pitch = -0.35
e4.orbit_mode = True; e4.apply_orbit_camera()
frames(e4, 4)
img4 = capture(e4)
P4 = [
    ("(-1,-1)应阴影", (-1.2, 0.02, -1.2)),
    ("(+1,+1)应亮",   (1.2, 0.02, 1.2)),
    ("(+1,-1)应亮",   (1.2, 0.02, -1.2)),
    ("(-1,+1)应亮",   (-1.2, 0.02, 1.2)),
]
for name, w in P4:
    lum, rgb, px = samp_at(e4, img4, w)
    if lum is None:
        print("  %-14s 屏幕外 %s" % (name, px))
    else:
        print("  %-14s lum=%.3f pixel=%s" % (name, lum, px))

# Python 侧重算 e4 阴影 (新逻辑 stored>=ref, ref=depth-bias)
sm4 = next(iter(e4._shadow_maps.values()))
arr4 = np.frombuffer(sm4['tex'][0].read(), dtype='f4').reshape(res, res)
lt4 = e4.lights[0]
vp4 = e4._dir_light_vp(lt4)
print("  --- Python 侧重算 (GPU 若不符 => 阴影位移/翻转) ---")
for name, w in P4:
    lp = np.array([w[0], w[1], w[2], 1.0], dtype='f8') @ vp4
    depth = (lp[2] / lp[3]) * 0.5 + 0.5
    uv = ((lp[0] / lp[3]) * 0.5 + 0.5, (lp[1] / lp[3]) * 0.5 + 0.5)
    if not (0 <= uv[0] <= 1 and 0 <= uv[1] <= 1):
        print("  %-14s uv出界" % name); continue
    stored = float(arr4[int(min(1, max(0, uv[1])) * (res-1)), int(min(1, max(0, uv[0])) * (res-1))])
    lit = stored >= depth - 0.002
    print("  %-14s %s  stored=%.3f ref=%.3f uv=%s" % (name, "照亮" if lit else "阴影", stored, depth - 0.002, tuple(round(float(x),3) for x in uv)))
# 影子足迹: 沿 -X-Z 对角线向外采样 (光源在 +X+Z, 影子应向 -X-Z 延伸)
print("  影子足迹 (-0.7..-2.0 沿 -X=-Z 对角, 应向远端变亮):")
for d in [-0.7, -1.0, -1.4, -1.8, -2.2]:
    lum, rgb, px = samp_at(e4, img4, (d, 0.02, d))
    print("    d=%+.1f lum=%.3f" % (d, lum if lum is not None else -1))

# 离轴点光源: 影子应落在光源对侧 (-X-Z 方向)
print("\n== 点光源 (3,4,3): 影子应在 (-1,-1) 侧 ==")
e5 = editor.EditorApp(640, 480)
e5.clear_scene()
e5.add_model(create_plane(20, 20), editor.Point3D(0, 0, 0), editor.Point3D(0, 0, 0), normal_mode='flat', name="地面")
e5.add_model(create_cube(1.0), editor.Point3D(0, 1.0, 0), editor.Point3D(0, 0, 0), normal_mode='flat', name="立方体")
e5.add_light('point', position=(3, 4, 3), shadow=True)
e5.selected_index = -1
e5.camera_target = (0, 1.0, 0); e5.camera_distance = 10
e5.camera_yaw = 0.6; e5.camera_pitch = -0.35
e5.orbit_mode = True; e5.apply_orbit_camera()
frames(e5, 4)
img5 = capture(e5)
P5 = [("(-1.6,-1.6)阴影?", (-1.6, 0.02, -1.6)), ("(-2.2,-2.2)亮?", (-2.2, 0.02, -2.2)),
      ("(+1.6,+1.6)亮?", (1.6, 0.02, 1.6))]
for name, w in P5:
    lum, rgb, px = samp_at(e5, img5, w)
    if lum is None:
        print("  %-16s 屏幕外 %s" % (name, px))
    else:
        print("  %-16s lum=%.3f pixel=%s" % (name, lum, px))
# 关阴影对照
lt5 = e5.lights[0]; lt5.shadow = False
frames(e5, 2)
img5b = capture(e5)
for name, w in P5:
    lum, rgb, px = samp_at(e5, img5b, w)
    if lum is None:
        continue
    print("  %-16s 关阴影 lum=%.3f" % (name, lum))
lt5.shadow = True
# 读点光源阴影贴图 (6面), 找含立方体(暗块)的面
sm5 = e5._shadow_maps.get(lt5.guid)
if sm5:
    print("  点光阴影贴图 6 面内容 (min深度, '#'=含内容):")
    for fi, tex5 in enumerate(sm5['tex']):
        w5, h5 = tex5.size
        a5 = np.frombuffer(tex5.read(), dtype='f4').reshape(h5, w5)
        frac_drawn = float((a5 < 0.999).mean())
        print("    面%d: %dx%d 内容占比 %.1f%%  min=%.3f" % (fi, w5, h5, frac_drawn*100, a5.min()))

# 对角方向光: (+1,-1) 点 0.220 是否自阴影(acne)? 开关阴影对照
print("  --- 对角光 shadow on/off 对照 (acne 检查) ---")
lt4 = e4.lights[0]
for name, w in [("(+1,-1)疑acne", (1.2, 0.02, -1.2)), ("(-1,-1)影", (-1.0, 0.02, -1.0)),
                ("(0,0)下", (0.0, 0.02, 0.0))]:
    lum_on, rgb_on, px = samp_at(e4, img4, w)
    lt4.shadow = False
    frames(e4, 2)
    lum_off, rgb_off, px = samp_at(e4, capture(e4), w)
    lt4.shadow = True
    frames(e4, 2)
    print("  %-12s on=%.3f off=%.3f 差=%.3f" % (name, lum_on, lum_off, lum_on - lum_off))

# Python 复算点光 point_shadow (与 GLSL 完全一致), 对比 GPU
print("  --- Python 复算点光 point_shadow ---")
_far = e5._shadow_point_far
_tex5 = sm5['tex']
_bb = 0.004
for name, w in [("(-1.6,-1.6)", (-1.6, 0.02, -1.6)), ("(-2.2,-2.2)", (-2.2, 0.02, -2.2)),
                ("(+1.6,+1.6)", (1.6, 0.02, 1.6)), ("(0,0)下", (0.0, 0.02, 0.0))]:
    rd = np.array([w[0]-3, w[1]-4, w[2]-3])       # frag - light
    adx, ady, adz = abs(rd)
    if adx >= ady and adx >= adz:
        face, fc = (0, np.array([rd[2], -rd[1]])/rd[0]) if rd[0] > 0 else (1, np.array([rd[2], rd[1]])/rd[0])
    elif ady >= adz:
        face, fc = (2, np.array([rd[0], -rd[2]])/rd[1]) if rd[1] > 0 else (3, np.array([rd[0], rd[2]])/rd[1])
    else:
        face, fc = (4, np.array([-rd[0], -rd[1]])/rd[2]) if rd[2] > 0 else (5, np.array([-rd[0], rd[1]])/rd[2])
    uv = fc*0.5 + 0.5
    depth = float(np.linalg.norm(rd)) / _far
    if depth > 1.0:
        print("  %-12s depth=%.3f >1 全亮" % (name, depth)); continue
    w5, h5 = _tex5[face].size
    a5 = np.frombuffer(_tex5[face].read(), dtype='f4').reshape(h5, w5)
    u, v = int(min(1, max(0, uv[0]))*(w5-1)), int(min(1, max(0, uv[1]))*(h5-1))
    stored = float(a5[v, u])
    lit = stored >= depth - _bb
    print("  %-12s %s  face=%d uv=(%.3f,%.3f) stored=%.3f depth=%.3f" % (
        name, "照亮" if lit else "阴影!", face, uv[0], uv[1], stored, depth))

# M21 参考: 默认种子场景 + 对角线方向光 (已知测试断言立方体顶面 0.857)
print("\n== M21 参考 (默认场景 + 对角线光, 应复现顶面 0.857) ==")
e3 = editor.EditorApp(1280, 800)
e3.selected_index = -1
e3.add_light('directional', direction=(-1, -1, 1), shadow=False)
frames(e3, 3)
img3 = capture(e3)
lum3, rgb3, px3 = samp_at(e3, img3, (1.2, 0.75, 0.3))   # 默认立方体中心
print("  默认立方体面中心 lum=%.3f rgb=%s pixel=%s (期望顶面~0.857)" % (lum3, rgb3, px3))

pygame.quit()
print("\n诊断完成")
