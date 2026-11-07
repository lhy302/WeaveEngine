# -*- coding: utf-8 -*-

"""test_vk_camera_align.py — Vk 播放器"相机与控制"对齐 GL (2026-11-06).

覆盖两件事:
  1. active_camera 对齐: 场景含摄像机实体 (cameras + active_camera) 时, Vk 中间层
     (scene_driver.SceneDriver) 的相机位置/朝向/视角必须与 GL
     (runtime.PlayerApp + loom_camera.apply_camera + loom_render.render) 一致 ——
     同一场景两后端算出的 VP 逐元素 |差| <= 1e-6; 无 active_camera 时保持轨道相机。
     GL 参考侧走真实 GL 代码 (engine.GLEngine 桩 + sceneio.scene_from_dict +
     apply_camera/apply_orbit_camera + matlib), 不手写公式, 避免自证。
  2. 鼠标交互对齐: 锁定状态机 (Tab/特殊场景/回调) 与 loom_input.InputMixin 同语义;
     光标增量只在锁定态累积; 滚轮推拉与 GL editor._update_camera 同公式
     (distance *= exp(-wheel*0.1), 钳 0.5..1000); 右键拖动转视角 pitch 钳 ±1.55。
"""

# 2026-11-06 P-02 修复: Windows 控制台默认 GBK, 末尾 print 的 ✅/❌/≤ 等字符会抛
# UnicodeEncodeError, 让"测试通过"被记录成 exit=1 的假失败 (48/51 曾被误判)。
# 统一把 stdout/stderr 切到 UTF-8(replace), 失败信号重新只由断言决定。
import sys as _sys_utf8
try:
    _sys_utf8.stdout.reconfigure(encoding='utf-8', errors='replace')
    _sys_utf8.stderr.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

# 2026-11-06 失败退出码闸门 (复核 A 指出: 54 个测试里仅 18 个有 sys.exit(1),
# 其余 FAIL 也 exit 0 -> run_all 假绿, 失败被静默吞掉)。
# 做法: 包一层 stdout, 出现以 "FAIL" 开头的行就在进程退出时把状态码改成 1。
# 只在真出现 FAIL 时才改码, 全 PASS 的测试行为完全不变。
import atexit as _atexit_gate
import os as _os_gate
import sys as _sys_gate


class _FailGateStream:
    def __init__(self, stream):
        self._stream = stream
        self.failed = False

    def write(self, text):
        if isinstance(text, str) and (text.startswith("FAIL") or "\nFAIL" in text):
            self.failed = True
        return self._stream.write(text)

    def __getattr__(self, name):
        return getattr(self._stream, name)


_fail_gate = _FailGateStream(_sys_gate.stdout)
_sys_gate.stdout = _fail_gate


@_atexit_gate.register
def _enforce_fail_exit_code():
    if not _fail_gate.failed:
        return
    try:
        _sys_gate.stdout.flush()
        _sys_gate.stderr.flush()
    except Exception:
        pass
    _os_gate._exit(1)


import copy
import math
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))       # Loom\
os.environ.setdefault('LOOM_NO_PARALLEL', '1')

import numpy as np

import engine as E
import sceneio as S
import scene_driver as SD
from loom_camera import clamp_camera_distance, CAM_DIST_MIN, CAM_DIST_MAX
from matlib import mat4_view_yaw_pitch, mat4_perspective

E.GLEngine._build_gpu = lambda self, m: None    # 无 GL: 只建组件 (同 test_camera_parent)

W, H = 480, 320
ASPECT = W / H
TOL = 1e-6
_FAILS = []


def check(name, cond, extra=""):
    print(("PASS " if cond else "FAIL ") + name + ("  " + str(extra) if extra else ""))
    if not cond:
        _FAILS.append(name)


# ============ GL 参考侧 (runtime.PlayerApp + loom_render.render 的相机段) ============
def gl_engine(data):
    """真实 GLEngine 相机状态: 与 runtime.py:50-65 逐行对应 (同一份 sceneio 加载)."""
    e = E.GLEngine.__new__(E.GLEngine)
    e.cameras = []; e.active_camera = None
    e.models = []; e.lights = []; e.materials = []
    e.camera = E.Point3D(0, 0, -5)
    e.camera_yaw = 0.0; e.camera_pitch = 0.0; e.camera_roll = 0.0
    e.orbit_mode = False
    e._fov = math.radians(60.0)
    e.near = 0.1; e.far = 1000.0
    e.width = W; e.height = H
    e.gravity = -9.8; e._skybox = None; e.undo = None
    cam_out = {}
    S.scene_from_dict(e, copy.deepcopy(data), camera_out=cam_out)
    if cam_out:                                   # ← PlayerApp: 轨道相机字段
        e.camera_target = cam_out['target']
        e.camera_distance = clamp_camera_distance(cam_out['distance'])
        e.camera_yaw = cam_out['yaw']
        e.camera_pitch = cam_out['pitch']
    cam = e.active_camera_object()                # ← PlayerApp: 激活相机优先
    if cam is not None:
        e.apply_camera(cam)
    else:
        e.orbit_mode = True
        e.apply_orbit_camera()
    return e


def gl_vp(e):
    """与 loom_render.render:684-771 同序: 挂父激活相机重应用 -> 轨道合成 -> VP."""
    cam = e.active_camera_object()
    if cam is not None and cam.parent is not None:
        e.apply_camera(cam)
    if e.orbit_mode:
        e.apply_orbit_camera()
    V = mat4_view_yaw_pitch(np, (e.camera.x, e.camera.y, e.camera.z),
                            e.camera_yaw, e.camera_pitch, e.camera_roll)
    P = mat4_perspective(np, e._fov, e.width / e.height, e.near, e.far)
    return V @ P, (e.camera.x, e.camera.y, e.camera.z)


def vk_driver(data):
    d = SD.SceneDriver()
    d._bridge_disabled = True                     # 只比相机, 不建物理桥 (快 + 无日志)
    d.load_from_data(copy.deepcopy(data))
    return d


def vp_diff(data, driver=None):
    vp_g, pos_g = gl_vp(gl_engine(data))
    d = driver or vk_driver(data)
    vp_v, pos_v = d.render_pose(aspect=ASPECT)
    dvp = float(np.max(np.abs(np.asarray(vp_g) - np.asarray(vp_v))))
    dpos = float(max(abs(a - b) for a, b in zip(pos_g, pos_v)))
    return dvp, dpos, pos_g, pos_v


# ============ 场景构造 ============
def scene(camera=None, cameras=None, active=None, objects=None):
    return {"version": S.SCENE_VERSION,
            "camera": camera or {"target": [0, 0, 0], "distance": 10.0,
                                 "yaw": 0.6, "pitch": -0.35},
            "cameras": cameras or [], "active_camera": active,
            "materials": [], "lights": [], "objects": objects or []}


def cam_dict(cid="c1", pos=(2.0, 3.0, -4.0), yaw=35.0, pitch=-12.0, roll=0.0,
             fov=60.0, parent=None, pitch_lock=False, pmin=-85.0, pmax=85.0):
    return {"id": cid, "name": "相机" + cid, "position": list(pos),
            "yaw": yaw, "pitch": pitch, "roll": roll, "fov": fov,
            "fov_locked": True, "pitch_lock": pitch_lock,
            "pitch_min": pmin, "pitch_max": pmax, "parent_id": parent,
            "skybox": None}


# ============ 1) 无 active_camera: 轨道相机 (行为不变) ============
def t_orbit_unchanged():
    for dist, yaw, pitch in ((10.0, 0.6, -0.35), (3.5, -1.2, 0.25),
                             (250.0, 2.8, -0.9), (0.5, 0.0, 0.0)):
        data = scene(camera={"target": [0, 1, 0], "distance": dist,
                             "yaw": yaw, "pitch": pitch})
        d = vk_driver(data)
        check("1 无active -> 轨道模式 (dist=%.1f)" % dist,
              d.orbit_mode is True and abs(d.distance - dist) < 1e-12,
              (d.orbit_mode, d.distance))
        dvp, dpos, pg, pv = vp_diff(data, d)
        check("1 轨道 VP 与 GL 一致 (dist=%.1f yaw=%.2f pitch=%.2f) |ΔVP|=%.2e"
              % (dist, yaw, pitch, dvp), dvp <= TOL and dpos <= TOL, (dvp, dpos))
    # 加载入口钳制仍在 (R-03 契约不被本次改动破坏)
    data = scene(camera={"target": [0, 0, 0], "distance": 5000.0,
                         "yaw": 0.6, "pitch": -0.35})
    d = vk_driver(data)
    check("1 加载 distance=5000 仍钳到 1000", abs(d.distance - CAM_DIST_MAX) < 1e-9, d.distance)


# ============ 2) 有 active_camera (根相机): 位置/朝向/FOV 全对齐 ============
def t_active_root():
    for yaw, pitch, fov in ((0.0, 0.0, 60.0), (35.0, -12.0, 48.0),
                            (300.0, 40.0, 90.0), (-120.0, -60.0, 25.0)):
        data = scene(cameras=[cam_dict(yaw=yaw, pitch=pitch, fov=fov)], active="c1")
        d = vk_driver(data)
        check("2 有active -> 关掉轨道 (yaw=%.0f)" % yaw, d.orbit_mode is False)
        check("2 相机位置 = 实体位置 (yaw=%.0f)" % yaw,
              abs(d.camera.x - 2.0) < 1e-12 and abs(d.camera.y - 3.0) < 1e-12
              and abs(d.camera.z + 4.0) < 1e-12,
              (d.camera.x, d.camera.y, d.camera.z))
        # CameraState 存储时把 yaw 环绕进 [0,360) (M41 度制): -120 -> 240
        from loom_scene_entities import wrap_deg
        check("2 朝向 度->弧度 (yaw=%.0f pitch=%.0f)" % (yaw, pitch),
              abs(d.camera_yaw - math.radians(wrap_deg(yaw, 0.0, 360.0))) < 1e-12
              and abs(d.camera_pitch
                      - math.radians(wrap_deg(pitch, -180.0, 180.0))) < 1e-12,
              (d.camera_yaw, d.camera_pitch))
        check("2 FOV = 相机 fov (%.0f° -> rad)" % fov,
              abs(d.fov - math.radians(fov)) < 1e-12, d.fov)
        dvp, dpos, pg, pv = vp_diff(data, d)
        check("2 active VP 与 GL 一致 (yaw=%.0f pitch=%.0f fov=%.0f) |ΔVP|=%.2e"
              % (yaw, pitch, fov, dvp), dvp <= TOL and dpos <= TOL, (dvp, dpos))


# ============ 3) active_camera + roll (GL camera_roll 进 view 矩阵) ============
def t_active_roll():
    for roll in (15.0, 90.0, -33.0):
        data = scene(cameras=[cam_dict(yaw=25.0, pitch=-8.0, roll=roll, fov=55.0)],
                     active="c1")
        d = vk_driver(data)
        check("3 roll 度->弧度 (%.0f°)" % roll,
              abs(d.camera_roll - math.radians(roll)) < 1e-12, d.camera_roll)
        dvp, dpos, pg, pv = vp_diff(data, d)
        check("3 roll VP 与 GL 一致 (roll=%.0f) |ΔVP|=%.2e" % (roll, dvp), dvp <= TOL)
    # roll=0 时与原轨道公式同构 (无 roll 回归)
    data = scene(cameras=[cam_dict(roll=0.0)], active="c1")
    d = vk_driver(data)
    check("3 roll=0 恒等", abs(d.camera_roll) < 1e-15, d.camera_roll)


# ============ 4) active_camera 挂父 + 父移动每帧跟随 ============
_PARENT = scene(
    cameras=[cam_dict(pos=(1.0, 1.6, 0.0), yaw=0.0, pitch=0.0, fov=70.0, parent="o1")],
    active="c1",
    objects=[{"id": "o1", "name": "玩家", "type": "cube", "params": {"size": 1.0},
              "position": [5.0, 0.0, -2.0],
              "rotation": [0.0, 0.7853981633974483, 0.0],
              "scale": [1.0, 1.0, 1.0], "visible": True}])

_PARENT2 = scene(
    cameras=[cam_dict(cid="c2", pos=(0.6, 1.2, 1.8), yaw=20.0, pitch=10.0, roll=5.0,
                      fov=65.0, parent="o2")],
    active="c2",
    objects=[{"id": "o2", "name": "躯干", "type": "cube", "params": {"size": 1.0},
              "position": [-3.0, 2.0, 4.0], "rotation": [0.2, -0.7, 0.35],
              "scale": [1.5, 1.5, 1.5], "visible": True}])


def t_active_parent():
    d = vk_driver(_PARENT)
    cam = d.active_camera_object()
    check("4 相机挂父链恢复", cam is not None and cam.parent is d.models[0])
    check("4 父.camera_children 同步", d.models[0].camera_children == [cam])
    check("4 世界位置 = 父变换(局部眼高)", 
          abs(d.camera.x - 5.707106781186548) < 1e-9
          and abs(d.camera.y - 1.6) < 1e-9
          and abs(d.camera.z + 2.7071067811865475) < 1e-9,
          (d.camera.x, d.camera.y, d.camera.z))
    dvp, dpos, pg, pv = vp_diff(_PARENT, d)
    check("4 挂父相机 VP 与 GL 一致 |ΔVP|=%.2e" % dvp, dvp <= TOL, (dvp, dpos))

    d2 = vk_driver(_PARENT2)
    dvp, dpos, pg, pv = vp_diff(_PARENT2, d2)
    check("4 挂父相机 (父3轴旋转+缩放1.5) VP 与 GL 一致 |ΔVP|=%.2e" % dvp, dvp <= TOL)

    # 父移动 -> 帧首 _refresh_player_camera 重应用 -> 相机跟随 (GL loom_render 同语义)
    for tag, move, drot in (("位移 +x10", (10.0, 0.0, 0.0), 0.0),
                            ("位移 +y3 且自转 90°", (0.0, 3.0, 0.0),
                             math.pi / 2)):
        data = copy.deepcopy(_PARENT)
        e = gl_engine(data)
        obj = e.models[0]
        obj.position = E.Point3D(obj.position.x + move[0], obj.position.y + move[1],
                                 obj.position.z + move[2])
        obj.rotation = E.Point3D(obj.rotation.x, obj.rotation.y + drot,
                                 obj.rotation.z)
        vp_g, pos_g = gl_vp(e)
        d = vk_driver(_PARENT)
        dv_obj = d.models[0]
        dv_obj.position = E.Point3D(dv_obj.position.x + move[0],
                                    dv_obj.position.y + move[1],
                                    dv_obj.position.z + move[2])
        dv_obj.rotation = E.Point3D(dv_obj.rotation.x, dv_obj.rotation.y + drot,
                                    dv_obj.rotation.z)
        d.advance_logic(1.0 / 60.0)        # 帧首: 鼠标结算 + 挂父相机重应用
        vp_v, pos_v = d.render_pose(aspect=ASPECT)
        dvp = float(np.max(np.abs(np.asarray(vp_g) - np.asarray(vp_v))))
        dpos = float(max(abs(a - b) for a, b in zip(pos_g, pos_v)))
        check("4 父%s -> 相机跟随且 VP 与 GL 一致 |ΔVP|=%.2e" % (tag, dvp),
              dvp <= TOL and dpos <= TOL, (dvp, dpos))
        check("4 父%s -> 相机位置真的变了" % tag,
              abs(pos_v[0] - 5.707106781186548) > 1e-6
              or abs(pos_v[1] - 1.6) > 1e-6, pos_v)


# ============ 5) 多相机 / active 容错 ============
def t_multi_camera():
    data = scene(cameras=[cam_dict("c1", pos=(0, 5, 0), yaw=180.0),
                          cam_dict("c2", pos=(-6.0, 1.0, 3.0), yaw=95.0,
                                   pitch=-20.0, fov=40.0)], active="c2")
    d = vk_driver(data)
    check("5 两相机都建出来", len(d.cameras) == 2, len(d.cameras))
    check("5 active 指向第二个", d.find_camera("c2") is d.active_camera_object())
    dvp, dpos, pg, pv = vp_diff(data, d)
    check("5 多相机 active=c2 VP 与 GL 一致 |ΔVP|=%.2e" % dvp, dvp <= TOL)

    # active_camera 指向不存在的 guid -> 回落轨道 (不崩)
    data = scene(cameras=[cam_dict()], active="不存在的guid")
    d = vk_driver(data)
    check("5 active 指向不存在 -> 轨道回落", d.orbit_mode is True
          and d.active_camera_object() is None)
    dvp, dpos, pg, pv = vp_diff(data, d)
    check("5 回落轨道后 VP 与 GL 一致 |ΔVP|=%.2e" % dvp, dvp <= TOL)

    # active_camera = None (显式) -> 轨道
    d = vk_driver(scene(cameras=[cam_dict()], active=None))
    check("5 active=None -> 轨道", d.orbit_mode is True and len(d.cameras) == 1)

    # 相机字段解析与 GL 侧完全一致 (同一份 sceneio 语义)
    data = scene(cameras=[cam_dict(cid="cX", pos=(1, 2, 3), yaw=370.0, pitch=190.0,
                                   roll=-200.0, fov=70.0, pmin=-45.0, pmax=60.0)],
                 active="cX")
    d = vk_driver(data)
    e = gl_engine(copy.deepcopy(data))
    cg, cv = e.cameras[0], d.cameras[0]
    check("5 相机字段与 GL 解析一致 (环绕/位置/FOV/限制)",
          (cv.guid, cv.yaw, cv.pitch, cv.roll, cv.fov, cv.pitch_min, cv.pitch_max)
          == (cg.guid, cg.yaw, cg.pitch, cg.roll, cg.fov, cg.pitch_min, cg.pitch_max),
          ((cv.yaw, cv.pitch, cv.roll), (cg.yaw, cg.pitch, cg.roll)))


# ============ 6) 鼠标: 锁定状态机 (与 loom_input 同语义) ============
def t_mouse_lock():
    calls = []
    d = vk_driver(scene())
    d.on_mouse_lock_changed = lambda locked: calls.append(locked)

    d.set_mouse_locked(True)
    check("6 set_mouse_locked(True) -> 锁定", d.mouse_locked is True)
    check("6 锁定回调转发 (后端据此捕获光标)", calls == [True], calls)

    d.toggle_mouse_locked()                       # Tab: 非特殊场景 -> 解锁意图
    check("6 Tab 解锁", d.mouse_locked is False and d.mouse_unlock_requested is True)
    d.toggle_mouse_locked()                       # Tab: 再回锁
    check("6 Tab 回锁", d.mouse_locked is True and d.mouse_unlock_requested is False)

    # 特殊场景 (UI 菜单) 强制解锁 + 清意图; 退出后自动回锁 (GL FPS 通用机制)
    d.toggle_mouse_locked()                       # 先解锁
    d.set_ui_capture_mouse(True)
    check("6 特殊场景强制解锁 + 清意图",
          d.mouse_locked is False and d.mouse_unlock_requested is False)
    d.toggle_mouse_locked()                       # 特殊场景下 Tab 不产生意图
    check("6 特殊场景 Tab 不清锁定意图", d.mouse_unlock_requested is False)
    d.set_ui_capture_mouse(False)
    check("6 退出特殊场景鼠标回锁", d.mouse_locked is True)
    check("6 回调按状态收到全部变化", calls[-1] is True, calls)


# ============ 7) 鼠标: 光标增量只在锁定态累积 ============
def t_mouse_rel():
    d = vk_driver(scene())
    d.set_mouse_locked(False)
    d.feed_mouse_rel(30, 0)
    d.consume_mouse_input()
    check("7 解锁态不累积增量 (GL: 解锁后滑动不转视角)", d.mouse_rel == (0, 0), d.mouse_rel)

    d.set_mouse_locked(True)
    d.feed_mouse_rel(120.5, -40.2)
    d.feed_mouse_rel(80.5, -0.8)                  # 同帧多次 -> 累加成一帧增量
    d.consume_mouse_input()
    check("7 锁定态累积 + int 截断 (120.5+80.5=201, -41)",
          d.mouse_rel == (201, -41), d.mouse_rel)
    d.consume_mouse_input()
    check("7 结算后清零 (下一帧无移动 = 0)", d.mouse_rel == (0, 0), d.mouse_rel)

    # 玩家脚本读的就是这个值 (first_person: yaw += mx*sens, 0.002 rad/px)
    d.set_mouse_locked(True)
    d.feed_mouse_rel(500, 0)
    d.consume_mouse_input()
    yaw0 = 0.0
    yaw1 = yaw0 + d.mouse_rel[0] * 0.002
    check("7 转视角量与 GL 玩家脚本同式 (500px*0.002=+1rad)",
          abs(yaw1 - 1.0) < 1e-12, yaw1)


# ============ 8) 鼠标: 滚轮推拉 (GL editor._update_camera 同公式) ============
def t_mouse_wheel():
    d = vk_driver(scene(camera={"target": [0, 0, 0], "distance": 10.0,
                                "yaw": 0.0, "pitch": 0.0}))
    d.mouse_wheel = 1
    d.apply_dev_camera_mouse()
    check("8 滚轮上推 -> 拉近 (d*exp(-0.1))",
          abs(d.distance - 10.0 * math.exp(-0.1)) < 1e-12, d.distance)
    check("8 滚轮读后清零", d.mouse_wheel == 0)

    d.mouse_wheel = -3
    d.apply_dev_camera_mouse()
    want = 10.0 * math.exp(-0.1) * math.exp(0.3)
    check("8 滚轮下滑 -> 拉远 (同公式连乘)", abs(d.distance - want) < 1e-12, d.distance)

    d.mouse_wheel = -100                          # 巨量 -> 钳到上限 1000
    d.apply_dev_camera_mouse()
    check("8 拉远钳到 1000", abs(d.distance - CAM_DIST_MAX) < 1e-12, d.distance)
    d.mouse_wheel = 100                           # 巨量 -> 钳到下限 0.5
    d.apply_dev_camera_mouse()
    check("8 拉近钳到 0.5", abs(d.distance - CAM_DIST_MIN) < 1e-12, d.distance)

    # 公式与 GL 源码一致 (文本契约: 同一常数, 别两边各写一份)
    src = open(os.path.join(os.path.dirname(HERE), "editor.py"), encoding="utf-8").read()
    check("8 GL 侧同公式 exp(-wheel*0.1) 未被改",
          "math.exp(-self.mouse_wheel * 0.1)" in src)

    # 玩家相机 (active_camera) 接管时滚轮不动相机 (GL 同: 不由鼠标直接驱动)
    d2 = vk_driver(scene(cameras=[cam_dict()], active="c1"))
    before = (d2.camera.x, d2.camera.y, d2.camera.z, d2.fov)
    d2.mouse_wheel = 5
    d2.apply_dev_camera_mouse()
    check("8 玩家相机接管时滚轮不动相机",
          (d2.camera.x, d2.camera.y, d2.camera.z, d2.fov) == before)
    check("8 玩家相机接管时滚轮也清零", d2.mouse_wheel == 0)


# ============ 9) 鼠标: 右键拖动转视角 (GL editor 同式, pitch 钳 ±1.55) ============
def t_mouse_look():
    d = vk_driver(scene(camera={"target": [0, 0, 0], "distance": 10.0,
                                "yaw": 0.0, "pitch": 0.0}))
    d.set_mouse_locked(True)                      # 播放期默认锁定 (增量才累积)
    d.feed_mouse_rel(100, -50)                    # 无按键 -> 不转视角
    d.consume_mouse_input()
    d.apply_dev_camera_mouse()
    check("9 无右键不转视角", abs(d.yaw) < 1e-12 and abs(d.pitch) < 1e-12,
          (d.yaw, d.pitch))

    d.mouse_buttons = (False, False, True)        # 右键按住
    d.feed_mouse_rel(100, -50)
    d.consume_mouse_input()
    d.apply_dev_camera_mouse()
    check("9 右键拖动 yaw += dx*0.01", abs(d.yaw - 1.0) < 1e-12, d.yaw)
    check("9 右键拖动 pitch -= dy*0.01 (上拖抬头)", abs(d.pitch - 0.5) < 1e-12, d.pitch)

    d.mouse_buttons = (False, False, True)
    d._pending_mouse_rel = (0.0, 0.0)
    d.mouse_rel = (0, -100000)                    # 巨量上拖 -> 钳到 +1.55
    d.apply_dev_camera_mouse()
    check("9 pitch 上限钳 1.55", abs(d.pitch - 1.55) < 1e-12, d.pitch)
    d.mouse_rel = (0, 100000)
    d.apply_dev_camera_mouse()
    check("9 pitch 下限钳 -1.55", abs(d.pitch + 1.55) < 1e-12, d.pitch)


# ============ 10) 玩家脚本 (first_person) 在驱动里 Tab 解锁 + 俯仰限制 ============
def t_player_script():
    data = scene(cameras=[cam_dict(pitch_lock=True, pmin=-40.0, pmax=50.0)],
                 active="c1",
                 objects=[{"id": "hero", "name": "玩家", "type": "cube",
                           "params": {"size": 1.0}, "position": [0, 0, 0],
                           "rotation": [0, 0, 0], "scale": [1, 1, 1],
                           "visible": True,
                           "scripts": [{"id": "first_person", "vars": {}}]}])
    d = vk_driver(data)
    check("10 俯仰限制 = 激活相机 pitch_lock",
          d.player_pitch_limits() == (math.radians(-40.0), math.radians(50.0)),
          d.player_pitch_limits())
    d._update_scripts(1.0 / 60.0)                 # on_start: 脚本锁定鼠标
    check("10 玩家脚本 on_start 锁定鼠标", d.mouse_locked is True)
    d.key_state['Tab'] = True                     # 按下 Tab 帧 -> 解锁
    d._update_scripts(1.0 / 60.0)
    check("10 Tab 经脚本解锁鼠标", d.mouse_locked is False and 
          d.mouse_unlock_requested is True, (d.mouse_locked, d.mouse_unlock_requested))
    d.key_state['Tab'] = False
    d._update_scripts(1.0 / 60.0)
    d.key_state['Tab'] = True                     # 再按 Tab -> 回锁
    d._update_scripts(1.0 / 60.0)
    check("10 再按 Tab 回锁", d.mouse_locked is True)

    # 无激活相机时 player_pitch_limits 为 None (脚本走默认钳位)
    d2 = vk_driver(scene())
    check("10 无激活相机 -> 俯仰限制 None", d2.player_pitch_limits() is None)


# ============ 11) GL 侧行为未被改动 (契约) ============
def t_gl_contract():
    root = os.path.dirname(HERE)
    runtime_src = open(os.path.join(root, "runtime.py"), encoding="utf-8").read()
    check("11 PlayerApp 仍按 active_camera 应用相机",
          "self.active_camera_object()" in runtime_src
          and "self.apply_camera(cam)" in runtime_src)
    render_src = open(os.path.join(root, "loom_render.py"), encoding="utf-8").read()
    check("11 GL 渲染仍用 camera_yaw/pitch/roll 组 VP",
          "self.camera_pitch, self.camera_roll)" in render_src)
    drv_src = open(os.path.join(root, "scene_driver.py"), encoding="utf-8").read()
    check("11 驱动不再硬编码 self.yaw/self.pitch 组 VP (改为按模式取)",
          "mat4_view_yaw_pitch(np, cam_pos, yaw, pitch, roll)" in drv_src
          and "mat4_view_yaw_pitch(np, cam_pos, self.yaw, self.pitch)" not in drv_src)


def main():
    for fn in (t_orbit_unchanged, t_active_root, t_active_roll, t_active_parent,
               t_multi_camera, t_mouse_lock, t_mouse_rel, t_mouse_wheel,
               t_mouse_look, t_player_script, t_gl_contract):
        print("---- %s ----" % fn.__name__)
        fn()
    print()
    print("总结果:", "ALL PASS ✅" if not _FAILS else "有 FAIL ❌ %s" % _FAILS)
    return 0 if not _FAILS else 1


if __name__ == "__main__":
    sys.exit(main())
