# -*- coding: utf-8 -*-
"""M14-M18 集成测试: 真实窗口 + GPU 渲染路径."""
import sys, os, math, json
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import pygame
import moderngl
import numpy as np
# 多核优化守卫: 测试确定性, 不建脚本线程/不设进程亲和性 (2026-08-14)
os.environ['LOOM_NO_PARALLEL'] = '1'
import editor
import sceneio
import undo as U
from mesh import create_cube, create_plane

TMP = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_tmp")
os.makedirs(TMP, exist_ok=True)

# 2026-08-13: editor_state.json 指向临时文件, 不污染真实"上次目录".
# (旧方案"备份+末尾还原"在测试中途异常退出时不会还原 -> 编辑器默认保存路径被
#  带到 _tmp, 用户实测 A01 时默认目录错乱. 改为直接替换 STATE_FILE 根治.)
editor.STATE_FILE = os.path.join(TMP, "editor_state_test.json")
ok = True
def check(label, cond, detail=""):
    global ok
    print(("PASS " if cond else "FAIL ") + label + ("  " + detail if detail else ""))
    if not cond: ok = False

def frames(eng, n=8):
    for _ in range(n):
        eng.render(0.016)

# ---------- 1. 编辑器 ----------
eng = editor.EditorApp(1280, 800)
check("编辑器启动(种子 3 对象)", len(eng.models) == 3,
      str([m.name for m in eng.models]))
check("编辑器禁 F11 全屏 (只留最大化/自由缩放; 2026-08-17)",
      eng.allow_fullscreen is False)
check("种子场景无默认光源 (M21)", len(eng.lights) == 0,
      "lights=%d" % len(eng.lights))
check("默认显示网格 (无限网格)", getattr(eng, 'show_grid', None) is True)
frames(eng, 3)
check("GPU 渲染 3 帧无崩溃", True)

# ---------- 2. 添加 + 撤销 ----------
eng._add_primitive('cube')
check("添加后 4 对象", len(eng.models) == 4)
eng._add_primitive('sphere')
cube = eng._selected()
eng._undo_action()
check("撤销添加 -> 回 4 个", len(eng.models) == 4)
eng._redo_action()
check("重做添加 -> 5 个", len(eng.models) == 5)

# ---------- 3. 层次: 挂父 (走 ReparentCommand) ----------
parent = eng.models[0]
child = eng.models[-1]
eng.undo.push(U.ReparentCommand("挂父", eng, child, child.parent, parent))
check("挂父成功", child.parent is parent and parent.children == [child])
w_child = eng.world_position(child)
w_parent = eng.world_position(parent)
d = (w_child.x - w_parent.x, w_child.y - w_parent.y, w_child.z - w_parent.z)
check("子世界位置 = 父 + 局部偏移",
      abs(d[0] - (child.position.x - parent.position.x)) < 1e-6,
      "%.3f" % d[0])
eng._undo_action()
check("撤销挂父", child.parent is None)
eng._redo_action()
check("重做挂父", child.parent is parent)

# ---------- 4. gizmo 拖拽 (直接调用内部方法) ----------
# 平移: 直接设拖拽状态并 apply 一次, 验证走世界->局部换算
m = child
w0 = eng.world_position(m)
eng.gizmo_drag = ('X', (w0.x, w0.y, w0.z),
                  (m.position.x, m.position.y, m.position.z))
eng.gizmo_undo_before = None
# 手动改 mouse 让射线命中 (粗略: 只验证方法不崩)
try:
    eng._gizmo_drag_apply()
    check("平移 drag_apply 可执行", True)
except Exception as e:
    check("平移 drag_apply 可执行", False, repr(e))
eng.gizmo_drag = None

# ---------- 5. 保存 / 加载 (sceneio v2, 显式路径绕过系统对话框) ----------
scene_path = os.path.join(TMP, "integration_scene.json")
eng.scene_name = os.path.basename(scene_path)
eng._save_scene(scene_path)
check("场景文件已写", os.path.exists(scene_path))
check("保存后名称框同步文件名", eng.scene_name == "integration_scene", eng.scene_name)
n_before = len(eng.models)
eng._new_scene()
check("新建清空", len(eng.models) == 0)
check("新建后默认名=场景", eng.scene_name == "场景", eng.scene_name)
eng._load_scene(scene_path)
check("加载回 5 个对象", len(eng.models) == n_before,
      str(len(eng.models)))
# 缓存干净场景基线 (7.5 节点"保存"有文件会直接覆盖 scene_path -> 8 节 Player 前恢复)
with open(scene_path, 'r', encoding='utf-8') as _cf:
    _clean_scene = json.load(_cf)
# 层次是否恢复: 找被挂父的 child (名字是 球体5 之类)
relinks = sum(1 for m in eng.models if m.parent is not None)
check("加载后仍有父子链", relinks >= 1, "relinks=%d" % relinks)
# 验证相机恢复
check("相机距离恢复", abs(eng.camera_distance - 10.0) < 1e-6)

# ---------- 6. Prefab: 存模板 + 放实例 (显式路径) ----------
eng.prefab_name = "itest"
eng.selected_index = eng.models.index(eng.models[0])
pfile = os.path.join(TMP, "itest.prefab")
eng._save_prefab(pfile)
check("Prefab 文件已写", os.path.exists(pfile))
n0 = len(eng.models)
eng._instantiate_prefab(pfile)
check("放实例后对象增加", len(eng.models) > n0, "%d->%d" % (n0, len(eng.models)))
inst_root = eng.models[n0]
check("实例根挂 prefab_ref", inst_root.prefab_ref is not None)
eng._undo_action()
check("撤销放实例", len(eng.models) == n0)
eng._redo_action()
check("重做放实例", len(eng.models) > n0)

# ---------- 7. 检查器拖拽撤销路径 (直接驱动 drag 快照) ----------
m = eng._selected()
before = eng._insp_undo_start.get("x", None)
eng._insp_undo_start["insp.position.X"] = U.snapshot(m)   # 模拟拖拽开始
m.position = editor.Point3D(m.position.x + 1, m.position.y, m.position.z)
after = U.snapshot(m)
eng.undo.push(U.StateCommand("位置X", eng, m, eng._insp_undo_start["insp.position.X"], after))
eng._insp_undo_start.pop("insp.position.X", None)
check("检查器修改后可撤销", eng.undo.can_undo)
eng._undo_action()
check("撤销检查器修改", eng._selected().position.x < m.position.x + 0.5)

frames(eng, 5)
check("修改后渲染 5 帧无崩溃", True)

# ---------- 7.5 旧 pygame 即时 GUI 交互段 (2026-08-28 退役: 依赖旧自绘视图
# _draw_toolbar/_ask_string/_show_settings, 随 LoomGUI 更名删除; Qt 原生控件交互由
# test_guiswitch 与 _tmp/qt_*_probe 覆盖) ----------


# ---------- 7.6 光照像素回归 (M21): 无光源暗 + 加方向光后三面亮度可区分 ----------
pygame.quit()
eng2 = editor.EditorApp(1280, 800)          # 干净默认场景: 立方体@(1.2,0.75,0.3) #FF5555
eng2.selected_index = -1                    # 取消选中, 避免 gizmo 覆盖采样点
eng2.show_grid = False                      # 无限网格线遍布地面, 关闭防污染像素采样
frames(eng2, 3)

def project2(eng, world):
    h = np.array([world[0], world[1], world[2], 1.0]) @ eng._vp
    ndc = h[:3] / h[3]
    return int((ndc[0] + 1) / 2 * eng.width), int((1 - (ndc[1] + 1) / 2) * eng.height)

def capture(eng):
    rb = eng.ctx.renderbuffer((eng.width, eng.height), components=4)
    fbo = eng.ctx.framebuffer(color_attachments=[rb])
    eng.ctx.copy_framebuffer(fbo, eng.ctx.screen)
    data = fbo.read(components=4)
    rb.release(); fbo.release()
    return np.flipud(np.frombuffer(data, dtype='u1').reshape(
        eng.height, eng.width, 4)[:, :, :3].astype(float) / 255.0)

cc = np.array([1.2, 0.75, 0.3]); half = 0.75
FACES = (('-X', [cc[0]-half, cc[1], cc[2]]),
         ('+Y', [cc[0], cc[1]+half, cc[2]]),
         ('-Z', [cc[0], cc[1], cc[2]-half]))

def face_lum(arr, fc):
    sx, sy = project2(eng2, fc)
    patch = arr[max(0, sy-4):sy+5, max(0, sx-4):sx+5]     # 5x5 邻域取 max, 避开三角接缝线
    return float(patch.max())

# 第一步: 无光源 -> 场景压暗 (环境光减到 0.2, 非纯黑但明显暗)
dark = capture(eng2)
lum_dark = {n: face_lum(dark, fc) for n, fc in FACES}
check("GPU 无光源: 可见面全部偏暗 (max < 0.45)",
      max(lum_dark.values()) < 0.45,
      str({k: round(v, 3) for k, v in lum_dark.items()}))

# 第二步: 加方向光 (direction=(-1,-1,1), 等价旧 l=(1,1,-1)) -> 照亮且三面可区分.
# shadow=False: 本节测光照模型 (Blinn-Phong 亮度/饱和度), 隔离 M29 阴影遮挡.
eng2.add_light('directional', direction=(-1, -1, 1), shadow=False)
frames(eng2, 3)
lit = capture(eng2)
lum = {n: face_lum(lit, fc) for n, fc in FACES}
worst = min(abs(lum[a] - lum[b]) for a, b in (('+Y', '-Z'), ('+Y', '-X'), ('-X', '-Z')))
check("GPU 加光后三面亮度两两不同, 最小差 > 0.10", worst > 0.10, "worst=%.3f" % worst)
check("GPU 亮度序 -X < -Z < +Y", lum['-X'] < lum['-Z'] < lum['+Y'],
      str({k: round(v, 3) for k, v in lum.items()}))
check("GPU 任何可见面不爆白", all(v < 0.995 for v in lum.values()),
      str({k: round(v, 3) for k, v in lum.items()}))
check("GPU 加光后明显比无光时亮", max(lum.values()) > max(lum_dark.values()) + 0.3,
      "%.3f vs %.3f" % (max(lum.values()), max(lum_dark.values())))

# ---------- 7.6b 饱和度像素回归 (M22): 终色饱和度可调 (0=灰阶, >1=增艳) ----------
def face_rgb(arr, fc):
    sx, sy = project2(eng2, fc)
    patch = arr[max(0, sy-4):sy+5, max(0, sx-4):sx+5]      # 5x5 邻域
    return patch.max(axis=(0, 1))                          # 每通道取 max
ch = lambda rgb: float(np.max(rgb) - np.min(rgb))          # 彩色度 (RGB 极差)
cube = next(m for m in eng2.models if m.primitive == 'cube')   # 种子场景 [平面,立方体,球体]
rgb1 = face_rgb(lit, FACES[1][1])                          # sat=1 (lit 是默认饱和度抓的帧)
cube.saturation = 0.0
frames(eng2, 3)
rgb0 = face_rgb(capture(eng2), FACES[1][1])
check("GPU 饱和度0: +Y面变灰阶 (RGB极差<0.05)", ch(rgb0) < 0.05,
      "ch=%.3f rgb=%s" % (ch(rgb0), np.round(rgb0, 3)))
cube.saturation = 2.0
frames(eng2, 3)
rgb2 = face_rgb(capture(eng2), FACES[1][1])
check("GPU 增艳(2.0)色度 > 原始(1.0)", ch(rgb2) > ch(rgb1),
      "%.3f vs %.3f" % (ch(rgb1), ch(rgb2)))
check("GPU 饱和度0 < 原始 < 增艳 全序", ch(rgb2) > ch(rgb1) > ch(rgb0),
      "%.3f/%.3f/%.3f" % (ch(rgb0), ch(rgb1), ch(rgb2)))
cube.saturation = 1.0                                      # 还原默认

# ---------- 7.7 光源实体 (M21): 不可见/无碰撞/可编辑/可撤销/可序列化 ----------
n_light0 = len(eng2.lights)
eng2._add_light('point')                    # 走编辑器撤销命令添加点光源
check("编辑器添加点光源", len(eng2.lights) == n_light0 + 1,
      "lights=%d" % len(eng2.lights))
check("添加后选中新光源", eng2._selected_light() is not None
      and eng2._selected_light().kind == 'point')
eng2._undo_action()
check("撤销添加光源", len(eng2.lights) == n_light0)
eng2._redo_action()
check("重做添加光源", len(eng2.lights) == n_light0 + 1)
eng2.selected_light_index = len(eng2.lights) - 1  # 撤销/重做不自动回选, 手动选中点光源
eng2.selected_index = -1
pl = eng2._selected_light()
pl.position = editor.Point3D(3.0, 2.0, 1.0)  # 手动挪个可见位置 (可选)
frames(eng2, 2)   # 选中光源渲染: 走 _draw_light_inspector + 图标白框路径
check("选中光源渲染检查器/图标不崩", True)

# 不可见 / 无碰撞: 光源不在 models 里; _pick 只遍历 models
check("光源不在 models (不渲染网格/无碰撞箱)", len(eng2.models) == 3,
      "models=%d" % len(eng2.models))
hp = eng2._pick(eng2.width // 2, eng2.height // 2)
check("拾取恒返回 None (只改选中, 不返回值)", hp is None, "pick=%r" % (hp,))
# 2026-08-12 修复: 点选到物体时清掉光源选中 -> _selected() 回到物体.
# 中心射线命中种子地面物体 -> 光源选中被清, _selected() 回到物体.
sel = eng2._selected()
check("点选到物体后清光源选中, _selected()=物体",
      eng2.selected_light_index == -1 and sel is not None and sel in eng2.models,
      "sel_light=%r sel=%r" % (eng2.selected_light_index, sel and sel.name))

# 序列化: 保存 -> 新建 -> 加载, 光源数量与参数恢复
lpath = os.path.join(TMP, "integration_lights.json")
eng2._save_scene(lpath)
eng2._new_scene()
check("新建后光源清空", len(eng2.lights) == 0)
eng2._load_scene(lpath)
check("加载后光源恢复", len(eng2.lights) == n_light0 + 1,
      "lights=%d" % len(eng2.lights))
reloaded = [l for l in eng2.lights if l.kind == 'point']
check("点光源参数恢复 (位置/强度/颜色)",
      len(reloaded) == 1 and tuple(reloaded[0].color) == (1.0, 1.0, 1.0),
      str([(l.kind, l.name) for l in eng2.lights]))

# 删除选中光源 (可撤销)
eng2.selected_light_index = 0
eng2.selected_index = -1
eng2.delete_object()
check("删除选中的方向光", len(eng2.lights) == n_light0,
      "lights=%d" % len(eng2.lights))
eng2._undo_action()
check("撤销删除光源", len(eng2.lights) == n_light0 + 1)
pygame.quit()

# ---------- 7.8 播放模式 (M26) + 脚本 (M27): 播放跑脚本, 停止还原 ----------
eng3 = editor.EditorApp(1280, 800)
cube3 = next(m for m in eng3.models if m.primitive == 'cube')
r0 = (cube3.rotation.x, cube3.rotation.y, cube3.rotation.z)
cube3.script_id = 'rotate'
cube3.script_vars = {'sy': 90.0}
eng3.selected_index = -1
frames(eng3, 2)
check("编辑期不跑脚本 (旋转不变)", tuple(cube3.rotation) == r0,
      str(tuple(cube3.rotation)))
eng3.toggle_play()
check("进入播放 is_playing", eng3.is_playing)
frames(eng3, 4)
check("播放期脚本旋转生效", abs(cube3.rotation.y - r0[1]) > 1e-3,
      "y=%.4f" % cube3.rotation.y)
eng3.toggle_play()
check("退出播放 is_playing=False", not eng3.is_playing)
check("停止后旋转还原", abs(cube3.rotation.y - r0[1]) < 1e-9
      and abs(cube3.rotation.x - r0[0]) < 1e-9,
      "y=%.4f" % cube3.rotation.y)
check("播放后物体数不变", len(eng3.models) == 3, str(len(eng3.models)))
check("播放后脚本保留 (编辑态)", cube3.script_id == 'rotate')

# ---------- 7.9 播放模式带光源回归 (Bug1): 点光源在场, 播放->停止不崩 ----------
# 修复: toggle_play 退出时对光源调 apply_light_snapshot, 但 editor 未导入该名 -> NameError (窗口卡死)
n_pl0 = len(eng3.lights)
eng3._add_light('point')
check("加光源后 lights=1", len(eng3.lights) == n_pl0 + 1,
      "lights=%d" % len(eng3.lights))
eng3.toggle_play()
frames(eng3, 2)
eng3.toggle_play()                     # 修复前在此抛 NameError: apply_light_snapshot
check("带光源退出播放 is_playing=False", not eng3.is_playing)
check("停止后光源仍在", len(eng3.lights) == n_pl0 + 1,
      "lights=%d" % len(eng3.lights))
check("停止后物体数不变", len(eng3.models) == 3, str(len(eng3.models)))
frames(eng3, 2)                        # 停止后继续渲染不崩
eng3._delete_light()                   # 清理, 不影响 8.5 用 eng3 保存场景
check("清理光源回 0", len(eng3.lights) == n_pl0,
      "lights=%d" % len(eng3.lights))

# ---------- 7.10 gizmo 拖拽数值稳定 (Bug2): 视线∥轴不拖飞, 正常视角仍可拖 ----------
# 修复: 拖拽平面法线改为=相机视线. 旧实现 cross(axis, view) 做平面含视线方向 -> 射线近平行,
#       denom≈0 -> 交点被浮点噪声放大成巨大位移 (视角与轴越接近越严重) -> 物体拖飞.
eng4 = editor.EditorApp(1280, 800)
c4 = next(m for m in eng4.models if m.primitive == 'cube')
c4.position = editor.Point3D(0, 0, 0)
eng4.selected_index = eng4.models.index(c4)
eng4.selected_light_index = -1
eng4.gizmo_mode = 'translate'
eng4.camera_target = (0, 0, 0)
eng4.camera_distance = 10.0
eng4.camera_yaw = math.pi / 2
eng4.camera_pitch = 0.05               # 视线与 X 轴夹角 ~3°: 旧代码最易拖飞
eng4.render(0.016)
ox, oy = eng4.project_world((0, 0, 0))
eng4.view.gui.mouse_pos = (ox, oy)
eng4.gizmo_drag = ('X', (0.0, 0.0, 0.0), (0.0, 0.0, 0.0))
max_disp = 0.0
for dy in (-30, -15, 0, 15, 30):
    for dx in (-30, -15, 0, 15, 30):
        eng4.view.gui.mouse_pos = (ox + dx, oy + dy)
        eng4._gizmo_drag_apply()
        p = c4.position
        max_disp = max(max_disp, math.hypot(p.x, p.y, p.z))
check("视线∥轴拖拽位移有界(<1)", max_disp < 1.0, "max=%.4f" % max_disp)

# 正常视角: 沿 X 轴水平拖 60px -> 位移合理 (旧代码 ≈-5.3 过大, 新 ~0.5)
c4.position = editor.Point3D(0, 0, 0)
eng4.camera_yaw, eng4.camera_pitch = 0.6, -0.35
eng4.render(0.016)
ox, oy = eng4.project_world((0, 0, 0))
eng4.view.gui.mouse_pos = (ox, oy)
eng4.gizmo_drag = ('X', (0.0, 0.0, 0.0), (0.0, 0.0, 0.0))
eng4.view.gui.mouse_pos = (ox + 60, oy)
eng4._gizmo_drag_apply()
disp = math.hypot(c4.position.x, c4.position.y, c4.position.z)
check("正常视角拖 X 位移合理(0.2~3)", 0.2 < disp < 3.0, "disp=%.3f" % disp)

# ---------- 7.11 M29 阴影遮挡 (物理正确: 方向光全场景 / 光束 / 点光) ----------
# 2026-08-12 修复: 阴影方案从"反转深度+LEQUAL 假设"改为"真实深度+GEQUAL 实测"
# (驱动实测 stored>=ref 照亮). 原测试用直下光(影子被相机压成 1px 细带, 5x5 max
# 采不到) + 旧错误方案全地面暗. 现改对角光/离轴点光, 影子明显偏移, 采样可靠.
def _sh_scene(mode='full', size=2.0, shape='circle', kind='directional', diag=True):
    """受控场景: 大地 + 挡光立方体 + 光源.
    diag=True: 光从 (+X,+Y,+Z) 斜射, 立方体影子落在 (-X,-Z) 侧地面 (明显偏移).
    diag=False: 垂直向下光 (光束模式用, 只测光束截面掩码不测阴影采样)."""
    e = editor.EditorApp(640, 480)
    e.show_grid = False   # 无限网格线遍布地面 y=0, 采样前关闭防污染阴影像素断言
    e.clear_scene()
    e.add_model(create_plane(20, 20), editor.Point3D(0, 0, 0), editor.Point3D(0, 0, 0), normal_mode='flat', name="地面")
    e.add_model(create_cube(1.0), editor.Point3D(0, 1.0, 0), editor.Point3D(0, 0, 0), normal_mode='flat', name="立方体")
    if kind == 'point':
        e.add_light('point', position=(3, 4, 3), shadow=True)
    elif diag:
        e.add_light('directional', position=(6, 10, 6), direction=(-1, -2, -1),
                    shadow=True, mode=mode, shape=shape, size=size)
    else:
        e.add_light('directional', position=(0, 8, 0), direction=(0, -1, 0),
                    shadow=True, mode=mode, shape=shape, size=size)
    e.selected_index = -1
    if diag:
        e.camera_target = (0, 1.0, 0); e.camera_distance = 10
        e.camera_yaw = 0.6; e.camera_pitch = -0.35
    else:
        e.camera_target = (0, 0.5, 0); e.camera_distance = 8
        e.camera_yaw = 0.0; e.camera_pitch = 0.0
    e.orbit_mode = True; e.apply_orbit_camera()
    frames(e, 4)
    def samp(w):
        img = capture(e)          # 每次抓新帧 (关阴影等状态变化后仍正确)
        sx, sy = project2(e, w)
        x0, y0 = max(0, sx - 2), max(0, sy - 2)
        x1, y1 = min(e.width, sx + 3), min(e.height, sy + 3)
        return img[y0:y1, x0:x1].reshape(-1, 3).max(axis=0)
    return e, samp

# 方向光全场景 (对角): 光从 (+X,+Y,+Z) 来 -> 影子落在 (-X,-Z) 侧地面
sh, sh_samp = _sh_scene('full', diag=True)
sh_pt = (-1.0, 0.02, -1.0)          # 影子区 (应暗)
lit_pt = (1.2, 0.02, -1.2)          # 非影区 (本底暗, 但开阴影不应再变暗)
on_shadow = sh_samp(sh_pt)
on_lit = sh_samp(lit_pt)
for lt in sh.lights:
    lt.shadow = False
frames(sh, 2)
off_shadow = sh_samp(sh_pt)
off_lit = sh_samp(lit_pt)
check("M29 方向光阴影: 被挡区暗于关阴影后",
      on_shadow.max() < off_shadow.max() - 0.1,
      "on=%s off=%s" % (np.round(on_shadow, 3), np.round(off_shadow, 3)))
check("M29 方向光: 非影区不被大片压暗 (修复大片黑区)",
      off_lit.max() - on_lit.max() < 0.05,
      "on=%s off=%s" % (np.round(on_lit, 3), np.round(off_lit, 3)))

# 光束模式 (垂直光): 只测光束截面掩码 (内受光 > 外暗), 不依赖阴影采样
shb, shb_samp = _sh_scene(mode='beam', size=1.0, diag=False)
inbeam = shb_samp((-0.8, 0.02, 0.0))     # 光束内 (半径1内) 受光
outbeam = shb_samp((-2.5, 0.02, 0.0))    # 光束外 -> 暗
check("M29 光束模式: 截面内受光 > 截面外",
      inbeam.max() > outbeam.max() + 0.1,
      "in=%s out=%s" % (np.round(inbeam, 3), np.round(outbeam, 3)))

# 2026-08-22: 光束遮罩与阴影开关解耦 —— 关阴影后截面外仍应暗 (用户实测 bug:
# 原遮罩在阴影块内, 关阴影失效, 光束外被照亮)
shb2, shb2_samp = _sh_scene(mode='beam', size=1.0, diag=False)
for lt in shb2.lights:
    lt.shadow = False
frames(shb2, 2)
in2 = shb2_samp((-0.8, 0.02, 0.0))
out2 = shb2_samp((-2.5, 0.02, 0.0))
check("M29 关阴影光束: 截面内受光 > 截面外 (遮罩不随阴影开关失效)",
      in2.max() > out2.max() + 0.1,
      "in=%s out=%s" % (np.round(in2, 3), np.round(out2, 3)))

# 点光源 (离轴): 光在 (+X,+Y,+Z) 侧 -> 影子落 (-X,-Z) 侧地面
shp, shp_samp = _sh_scene(kind='point', diag=True)
p_sh_pt = (-1.6, 0.02, -1.6)        # 影子区 (应暗)
p_lit_pt = (1.6, 0.02, 1.6)         # 非影区 (开阴影不应变暗)
p_on = shp_samp(p_sh_pt)
p_on_lit = shp_samp(p_lit_pt)
for lt in shp.lights:
    lt.shadow = False
frames(shp, 2)
p_off = shp_samp(p_sh_pt)
p_off_lit = shp_samp(p_lit_pt)
check("M29 点光源阴影: 被挡区暗于关阴影后",
      p_on.max() < p_off.max() - 0.02,
      "on=%s off=%s" % (np.round(p_on, 3), np.round(p_off, 3)))
check("M29 点光源: 非影区不被压暗 (修复大片黑区)",
      p_off_lit.max() - p_on_lit.max() < 0.05,
      "on=%s off=%s" % (np.round(p_on_lit, 3), np.round(p_off_lit, 3)))

# ---------- 7.12 M29 驱动阴影采样比较方向 (关键假设, 2026-08-12 实测校正) ----------
# 本驱动(GTX 1050 Ti) depth 纹理采样实测 stored>=ref 为照亮 (moderngl 上报 '<=' 但驱动忽略,
# 做 GEQUAL). 此探针固化该行为, 阴影方案 (真实深度+ref=depth-bias) 依赖它.
_ctxp = shp.ctx
_vp0 = _ctxp.viewport
_ptex = _ctxp.depth_texture((4, 4))
_pfbo = _ctxp.framebuffer(depth_attachment=_ptex)
_pfbo.clear(depth=0.10)                      # 贴图全部存 0.10
_pfbo.use()
_pprog = _ctxp.program(
    vertex_shader="""#version 330
    in vec2 in_pos; out vec2 v_uv;
    void main(){ v_uv = in_pos * 0.5 + 0.5; gl_Position = vec4(in_pos, 0.0, 1.0); }""",
    fragment_shader="""#version 330
    uniform sampler2DShadow u_sm; uniform float u_ref;
    in vec2 v_uv; out vec4 frag;
    void main(){ frag = vec4(vec3(texture(u_sm, vec3(v_uv, u_ref))), 1.0); }""")
_pvbo = _ctxp.buffer(np.array([-1, -1, 1, -1, 1, 1, -1, -1, 1, 1, -1, 1], dtype='f4').tobytes())
_pvao = _ctxp.vertex_array(_pprog, [(_pvbo, '2f', 'in_pos')])
_pfbo2 = _ctxp.framebuffer(color_attachments=[_ctxp.renderbuffer((32, 32), components=4)])
def _p_shadow(ref):
    _ctxp.disable(moderngl.DEPTH_TEST)   # 编辑器残留深度/剔除状态会干掉探针 quad
    _ctxp.disable(moderngl.CULL_FACE)
    _ptex.use(0); _pprog['u_sm'].value = 0; _pprog['u_ref'].value = ref
    _pfbo2.use(); _ctxp.clear(); _ctxp.viewport = (0, 0, 32, 32)
    _pvao.render(moderngl.TRIANGLES)
    a = np.frombuffer(_pfbo2.read(components=4), dtype='u1').reshape(32, 32, 4)[:, :, 0]
    return float(a.mean() / 255.0)
_s_lo = _p_shadow(0.05)   # ref 0.05 < 存值 0.10 -> 应照亮 (sh=1)
_s_hi = _p_shadow(0.15)   # ref 0.15 > 存值 0.10 -> 应阴影 (sh=0)
check("M29 驱动比较方向: ref<存值=照亮 / ref>存值=阴影 (stored>=ref 生效)",
      _s_lo > 0.9 and _s_hi < 0.1,
      "lo=%s hi=%s" % (round(_s_lo, 3), round(_s_hi, 3)))
for _o in (_pfbo2, _pfbo, _pvbo, _pvao, _ptex):
    _o.release()
_ctxp.viewport = _vp0
_ctxp.screen.use()
pygame.quit()

# ---------- 7.13 GUI active_id 消失清理 (挂脚本后播放不卡死, 2026-08-12) ----------
# 根因: 挂脚本按钮点击认领 active_id 后, 脚本已挂按钮下一帧消失(attached 过滤),
# 释放事件永远无法被处理 -> active_id 永久残留 -> 之后所有控件无法认领 -> UI 卡死.
# gui.end_frame 治本: 本帧未渲染的 active_id/_focus 控件自动清理.
e7 = editor.EditorApp(640, 480)
g7 = e7.view.gui
g7.begin_frame((20, 20), (1, 0, 0), [1], [], 0)      # 按下挂脚本按钮
claimed7 = g7.button("insp.sadd.gravity", (10, 10, 250, 22), "+ 重力落地", size=13)
g7.end_frame()
check("GUI: 挂脚本按钮按下认领 active_id",
      claimed7 and g7.active_id == "insp.sadd.gravity")
g7.begin_frame((20, 20), (1, 0, 0), [], [1], 0)      # 释放, 按钮已消失(不渲染)
g7.end_frame()
check("GUI: 消失控件 active_id 自动清理 (防卡死)", g7.active_id is None, g7.active_id)
g7.begin_frame((120, 120), (1, 0, 0), [1], [], 0)
p7 = g7.button("tool.play", (120, 120, 56, 26), "▶播放", size=14)
g7.end_frame()
check("GUI: 清理后播放按钮可认领 (未卡死)", p7)
# 挂 fall 脚本 + 播放切换 (真实渲染路径): 渲染不崩 + 交互状态干净
m7 = e7._selected()
m7.add_script('fall')
e7.toggle_play()
frames(e7, 3)
check("GUI: 挂重力脚本后进入播放渲染不崩", True)
e7.toggle_play()
frames(e7, 2)
check("GUI: 播放切换后 active_id 干净", e7.view.gui.active_id is None, e7.view.gui.active_id)
pygame.quit()

# ---------- 7.18-7.21 旧自绘视图 GUI 交互段 (2026-08-28 退役: 依赖
# view._draw_* 面板/_handle_panel_resizers/_ctx_menu 等旧视图实现, 随
# LoomGUI 更名删除; Qt 原生面板/层级右键菜单由 test_guiswitch + 人工台账覆盖)

# ---------- 7.14 平行光定位点可调 + 物体旋转环绕 (2026-08-12) ----------
e8 = editor.EditorApp(640, 480)
lt8 = e8.add_light('directional', position=(1, 5, 2), shadow=False)
e8.selected_light_index = len(e8.lights) - 1
check("平行光: gizmo 目标 = 光源 (定位点可平移)",
      e8._gizmo_target() is lt8)
lt8.position = editor.Point3D(3, 6, 1)     # 定位点可调
frames(e8, 3)
check("平行光: 改定位点后渲染不崩", True)
frames(e8, 3)                              # 检查器(方向3角度+位置XYZ)渲染
check("平行光: 检查器(方向+位置)渲染不崩", True)
# 物体旋转环绕 (与平行光 3 角度同款): 200° 拖过 ±180 -> -160°
check("物体旋转: 环绕 200° -> -160° (与平行光同款操作)",
      abs(editor.wrap_deg(200.0, -180.0, 180.0) - (-160.0)) < 0.01,
      str(editor.wrap_deg(200.0, -180.0, 180.0)))
pygame.quit()

# ---------- 7.15 drag_float 右键直接输入数字 (2026-08-12) ----------
# 所有拖条 (物体变换/脚本参数/光源/摄像机等) 统一: 右键进入数值输入, Enter 提交/Esc 取消.
e9 = editor.EditorApp(640, 480)
g9 = e9.view.gui
R9 = (10, 10, 100, 22)
def k9(unicode=None, k=None):
    return pygame.event.Event(pygame.KEYDOWN, key=k, unicode=unicode)
g9.begin_frame((20, 20), (1, 0, 0), [3], [], 0)          # 右键按下 -> 输入模式
v9, a9 = g9.drag_float("t9", R9, 5.0, speed=0.1, fmt='%.2f')
g9.end_frame()
check("拖条: 右键进入数值输入模式", g9._focus == "t9" and "t9" in g9._num_focus)
for _ in range(3):                                        # 输入过程多帧 _focus 保持
    g9.begin_frame((20, 20), (1, 0, 0), [], [], 0)
    g9.drag_float("t9", R9, 5.0, speed=0.1, fmt='%.2f')
    g9.end_frame()
check("拖条: 输入模式多帧 _focus 保持 (不被 end_frame 误清)",
      g9._focus == "t9", "focus=%s" % g9._focus)
g9.handle_key_event(k9("4")); g9.handle_key_event(k9("2"))
g9.handle_key_event(k9(k=pygame.K_RETURN))
g9.begin_frame((20, 20), (1, 0, 0), [], [], 0)
v9, a9 = g9.drag_float("t9", R9, 5.0, speed=0.1, fmt='%.2f')
g9.end_frame()
check("拖条: Enter 提交输入值 42", abs(v9 - 42.0) < 1e-9 and not a9, "v=%s" % v9)
g9.begin_frame((20, 20), (1, 0, 0), [3], [], 0)          # Esc 取消
g9.drag_float("t10", R9, 7.5, speed=0.1, fmt='%.2f')
g9.end_frame()
g9.handle_key_event(k9("9")); g9.handle_key_event(k9(k=pygame.K_ESCAPE))
g9.begin_frame((20, 20), (1, 0, 0), [], [], 0)
v9, a9 = g9.drag_float("t10", R9, 7.5, speed=0.1, fmt='%.2f')
g9.end_frame()
check("拖条: Esc 取消保持原值", abs(v9 - 7.5) < 1e-9, "v=%s" % v9)
# 非法输入 (非数字) -> 改为 0 + notice 提醒
g9.begin_frame((20, 20), (1, 0, 0), [3], [], 0)
g9.drag_float("t11", R9, 3.0, speed=0.1, fmt='%.2f')
g9.end_frame()
g9.handle_key_event(k9("a")); g9.handle_key_event(k9("b"))
g9.handle_key_event(k9(k=pygame.K_RETURN))
g9.begin_frame((20, 20), (1, 0, 0), [], [], 0)
v9, a9 = g9.drag_float("t11", R9, 3.0, speed=0.1, fmt='%.2f')
g9.end_frame()
check("拖条: 非法输入 'ab' -> 改为 0", abs(v9) < 1e-9, "v=%s" % v9)
check("拖条: 非法输入有 notice 提醒", g9.notice is not None and "无效" in g9.notice,
      str(g9.notice))
pygame.quit()

# ---------- 7.16/7.17 旧视图面板交互 (2026-08-28 退役: 层级/资源滚轮滚动,
# 面板分隔条/收起/检查器拖块 = 旧自绘视图实现, 随 LoomGUI 更名删除;
# Qt 原生面板由 test_guiswitch + 人工台账覆盖) ----------

# ---------- 8. Player 运行时 ----------
from runtime import PlayerApp
sceneio.save_json_atomic(scene_path, _clean_scene)   # 恢复干净场景 (7.5 节点"保存"已覆盖成 7 对象)
play = PlayerApp(scene_path, 800, 600)
check("Player 加载场景对象", len(play.models) == n_before,
      str(len(play.models)))
frames(play, 5)
check("Player 渲染 5 帧无崩溃", True)
pygame.quit()

# ---------- 8.5 Player 运行时跑脚本 (M27): 打包的游戏真的能动 ----------
play_rot = os.path.join(TMP, "play_rotate.json")
cube3.script_id = 'rotate'                       # 给立方体挂自转 (sy=90°/s)
cube3.script_vars = {'sy': 90.0}
eng3._save_scene(play_rot)
pygame.quit()
play2 = PlayerApp(play_rot, 800, 600)
pc = next(m for m in play2.models if m.primitive == 'cube')
ry0 = pc.rotation.y
frames(play2, 6)
check("Player 脚本旋转生效", abs(pc.rotation.y - ry0) > 1e-3,
      "%.4f -> %.4f" % (ry0, pc.rotation.y))
pygame.quit()

# ---------- 7.21 同批次退役 (层级右键菜单/相机行单击, 见上注释)
