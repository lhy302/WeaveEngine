# -*- coding: utf-8 -*-

"""test_camera_parent_serialization.py — Q-B7-57-1 已知边界：相机挂相机 序列化持久化门。

背景（agent-63 在 edf1336 登记的已知边界）: 运行期「相机挂相机」已修（CameraState
也能当父），但序列化侧 `_link_camera_parents` / `link_camera_parents` 的 id_map 只含
物体 guid -> 保存再加载时相机父链回落根。修前该状态无法达成（会崩），故非回归；
现在可达 -> 必须能存能读。

本门（全部无头，GL = sceneio.scene_from_dict / VK = SceneDriver.build_scene_from_data）:
  ① 相机挂相机 -> 保存 -> 加载 -> 父链保持（GL/VK 各一遍，两端父 guid 映射逐值相等）
  ② 三级链 A→B→C 往返保持（父链 guid 序列 + 世界位置逐值相等）
  ③ 防环：A→B 后 B→A 拒绝且状态不变；文件直接写环也拒绝（可见报错，不递归爆栈）
  ④ 孤儿父（父已删/悬空 guid）脱根 + 告警，不崩溃
  ⑤ 两端父链解析函数 object is 同一对象（唯一实现，无 driver 副本）

修前真红（HEAD e2709e8，本文件原样跑）: 见交付报告原文；核心是 GL/VK 加载后
cam-b.parent is None（回落根），且 sceneio._link_camera_parents is driver.link_camera_parents
为 False。修后全绿。
"""

import sys as _sys_utf8
try:
    _sys_utf8.stdout.reconfigure(encoding='utf-8', errors='replace')
    _sys_utf8.stderr.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

# 失败退出码闸门（与仓库既有 test_*.py 同款）: 出现 FAIL 行 -> exit 1，防 run_all 假绿。
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


import contextlib
import copy
import io
import os
import sys
import tempfile
import uuid

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)                    # Loom/
sys.path.insert(0, ROOT)
os.environ.setdefault('LOOM_NO_DIALOG', '1')
os.environ.setdefault('LOOM_NO_PARALLEL', '1')
os.environ.setdefault('LOOM_NO_PHYSICS', '1')
os.environ.setdefault('LOOM_USER_ROOT', tempfile.mkdtemp(prefix='loom_qb757_ser_'))

import engine as E
import sceneio as S
import render.vk.driver as SD
from mathlib.mesh import create_cube
import scene.camera as SC

E.GLEngine._build_gpu = lambda self, m: None     # 无 GL: 只建组件（同 test_camera_parent）

_FAILS = []


def check(label, cond, detail=""):
    print(("PASS " if cond else "FAIL ") + label + ("  " + str(detail) if detail else ""))
    if not cond:
        _FAILS.append(label)


def _engine():
    e = E.GLEngine.__new__(E.GLEngine)
    e.cameras = []
    e.active_camera = None
    e.models = []
    e.lights = []
    e.materials = []
    e.camera = E.Point3D(0, 0, -5)
    e.camera_yaw = 0.0
    e.camera_pitch = 0.0
    e.camera_roll = 0.0
    e.orbit_mode = False
    e._fov = 0.785
    e.gravity = -9.8
    e._skybox = None
    return e


def mk_obj(name, pos=(0, 0, 0)):
    m = E.GameObject(create_cube(1.5), E.Point3D(*pos), E.Point3D(0, 0, 0), name=name)
    m.guid = uuid.uuid4().hex
    return m


def mk_cam(guid, pos=(0, 0, 0), yaw=0.0, pitch=0.0, roll=0.0, fov=60.0, name=None):
    c = E.CameraState(position=pos, yaw=yaw, pitch=pitch, roll=roll, fov=fov,
                      name=name or guid)
    c.guid = guid
    return c


def _scene(cameras):
    return {"version": S.SCENE_VERSION,
            "camera": {"target": [0, 0, 0], "distance": 10.0,
                       "yaw": 0.6, "pitch": -0.35},
            "cameras": cameras, "active_camera": None,
            "materials": [], "lights": [], "objects": []}


def _cam_dict(cid, parent=None, pos=(0, 0, 0), yaw=0.0):
    return {"id": cid, "name": cid, "position": list(pos),
            "yaw": yaw, "pitch": 0.0, "roll": 0.0, "fov": 60.0,
            "fov_locked": True, "pitch_lock": False,
            "pitch_min": -85.0, "pitch_max": 85.0,
            "parent_id": parent, "skybox": None}


def _vk_driver(data):
    d = SD.SceneDriver()
    d._bridge_disabled = True
    d.build_scene_from_data(copy.deepcopy(data))
    return d


def _parents(cams):
    return {c.guid: (c.parent.guid if getattr(c, 'parent', None) is not None else None)
            for c in cams}


def _chain(cam):
    out = []
    cur = cam
    while cur is not None and len(out) < 16:
        out.append(getattr(cur, 'guid', None))
        cur = getattr(cur, 'parent', None)
    return out


def _cap(fn):
    """跑 fn 并收集 stdout；返回 (结果, 文本, 异常)。"""
    buf = io.StringIO()
    err = None
    try:
        with contextlib.redirect_stdout(buf):
            res = fn()
    except Exception as exc:          # 不崩门本身：异常作为 FAIL 证据
        res = None
        err = exc
    return res, buf.getvalue(), err


def _v3(t):
    return tuple(round(float(v), 6) for v in t)


# ============ ① 相机挂相机 -> 保存 -> 加载（GL/VK 各一遍 + 两端一致） ============
e = _engine()
e.models = [mk_obj("父物体", (5, 0, 0))]
c_a = mk_cam("cam-a", (10, 0, 0))
c_b = mk_cam("cam-b", (1, 2, 3), yaw=25.0, pitch=-10.0, roll=5.0)
e.cameras = [c_a, c_b]
e.set_camera_parent(c_b, c_a, preserve_world=False)
d1 = S.scene_to_dict(e)
_saved = {cm["id"]: cm for cm in d1["cameras"]}
check("① 保存: 相机 parent_id 写出父相机 guid",
      _saved["cam-b"]["parent_id"] == "cam-a",
      _saved["cam-b"].get("parent_id"))

e_gl = _engine()
S.scene_from_dict(e_gl, copy.deepcopy(d1))
_gl = {c.guid: c for c in e_gl.cameras}
check("① GL 加载后相机挂相机父链保持",
      _gl["cam-b"].parent is _gl["cam-a"],
      getattr(_gl["cam-b"].parent, "guid", None))
check("① GL 父.camera_children 含子相机",
      _gl["cam-a"].camera_children == [_gl["cam-b"]],
      [getattr(x, "guid", None) for x in _gl["cam-a"].camera_children])
check("① GL 子相机局部字段不被加载改写",
      _v3((_gl["cam-b"].position.x, _gl["cam-b"].position.y, _gl["cam-b"].position.z)) == (1, 2, 3)
      and abs(_gl["cam-b"].yaw - 25.0) < 1e-9
      and abs(_gl["cam-b"].pitch - (-10.0)) < 1e-9
      and abs(_gl["cam-b"].roll - 5.0) < 1e-9,
      (_gl["cam-b"].position, _gl["cam-b"].yaw, _gl["cam-b"].pitch, _gl["cam-b"].roll))

drv1 = _vk_driver(d1)
_vk = {c.guid: c for c in drv1.cameras}
check("① VK 加载后相机挂相机父链保持",
      _vk["cam-b"].parent is _vk["cam-a"],
      getattr(_vk["cam-b"].parent, "guid", None))
check("① VK 父.camera_children 含子相机",
      _vk["cam-a"].camera_children == [_vk["cam-b"]],
      [getattr(x, "guid", None) for x in _vk["cam-a"].camera_children])
_expect_parents = {"cam-a": None, "cam-b": "cam-a"}
check("① 两端父 guid 映射逐值相等且=期望",
      _parents(e_gl.cameras) == _expect_parents == _parents(drv1.cameras),
      (_parents(e_gl.cameras), _parents(drv1.cameras)))

# 加载后再保存: 父链不能被「读进来又写回去」洗掉
d1b = S.scene_to_dict(e_gl)
_saved_b = {cm["id"]: cm for cm in d1b["cameras"]}
check("① GL 加载->再保存 parent_id 仍指向父相机",
      _saved_b["cam-b"]["parent_id"] == "cam-a",
      _saved_b["cam-b"].get("parent_id"))

# 真实磁盘 JSON 往返（save_scene_data -> load_scene_data -> scene_from_dict）
_disk = os.path.join(tempfile.mkdtemp(prefix="loom_qb757_disk_"), "scene.json")
S.save_scene_data(_disk, d1)
_d1_disk = S.load_scene_data(_disk)
_e_disk = _engine()
S.scene_from_dict(_e_disk, copy.deepcopy(_d1_disk))
_dm = {c.guid: c for c in _e_disk.cameras}
check("① 磁盘 JSON 保存->加载 相机挂相机父链保持",
      _dm["cam-b"].parent is _dm["cam-a"],
      getattr(_dm["cam-b"].parent, "guid", None))

# ============ ② 三级链 A→B→C 往返保持 ============
e3 = _engine()
ch_a = mk_cam("chain-a", (10, 0, 0))
ch_b = mk_cam("chain-b", (2, 0, 0))
ch_c = mk_cam("chain-c", (0, 1, 0))
e3.cameras = [ch_a, ch_b, ch_c]
e3.set_camera_parent(ch_c, ch_b, preserve_world=False)
e3.set_camera_parent(ch_b, ch_a, preserve_world=False)
_world_before = _v3(e3.camera_world_position(ch_c))
d3 = S.scene_to_dict(e3)

e3g = _engine()
S.scene_from_dict(e3g, copy.deepcopy(d3))
_g3 = {c.guid: c for c in e3g.cameras}
check("② GL 三级链 A→B→C 往返保持",
      _chain(_g3["chain-c"]) == ["chain-c", "chain-b", "chain-a"],
      _chain(_g3["chain-c"]))
check("② GL 三级链世界位置保持",
      _v3(e3g.camera_world_position(_g3["chain-c"])) == _world_before,
      (_v3(e3g.camera_world_position(_g3["chain-c"])), _world_before))

drv3 = _vk_driver(d3)
_v3map = {c.guid: c for c in drv3.cameras}
check("② VK 三级链 A→B→C 往返保持",
      _chain(_v3map["chain-c"]) == ["chain-c", "chain-b", "chain-a"],
      _chain(_v3map["chain-c"]))
_expect3 = {"chain-a": None, "chain-b": "chain-a", "chain-c": "chain-b"}
check("② 两端三级链父 guid 映射一致且=期望",
      _parents(e3g.cameras) == _expect3 == _parents(drv3.cameras),
      (_parents(e3g.cameras), _parents(drv3.cameras)))

# ============ ③ 防环: 拒绝 + 可见报错 + 状态不变 / 不递归爆栈 ============
ec = _engine()
cy_a = mk_cam("A")
cy_b = mk_cam("B")
ec.cameras = [cy_a, cy_b]
_n1 = S._link_camera_parents(ec, [(cy_a, "B"), (cy_b, None)])
check("③ 先挂 A→B 成功",
      cy_a.parent is cy_b and cy_b.camera_children == [cy_a],
      (getattr(cy_a.parent, "guid", None), [getattr(x, "guid", None) for x in cy_b.camera_children]))
_res, _out, _err = _cap(lambda: S._link_camera_parents(
    ec, [(cy_a, "B"), (cy_b, "A")]))
check("③ B→A 被拒绝且有可见报错（含成环/拒绝字样）",
      _err is None and ("成环" in _out) and ("拒绝" in _out),
      _out.strip() or repr(_err))
check("③ 拒绝后状态不变（A 仍挂 B，B 仍根，children 不变）",
      cy_a.parent is cy_b and cy_b.parent is None and cy_b.camera_children == [cy_a],
      (getattr(cy_a.parent, "guid", None), getattr(cy_b.parent, "guid", None)))
check("③ 防环不递归爆栈（函数正常返回，未抛 RecursionError）",
      _res == 0, _res)

# 文件里直接写出的环：整次链接拒绝（相机全部保持根），加载不崩
_dcyc = _scene([_cam_dict("cy-a", "cy-b"), _cam_dict("cy-b", "cy-a")])
_r, _out2, _err2 = _cap(lambda: S.scene_from_dict(_engine(), copy.deepcopy(_dcyc)))
check("③ 文件写环: 加载不崩且可见拒绝",
      _err2 is None and ("成环" in _out2) and ("拒绝" in _out2),
      _out2.strip() or repr(_err2))

# 自指也是环
_es = _engine()
_self = mk_cam("SELF")
_es.cameras = [_self]
_r3, _out3, _err3 = _cap(lambda: S._link_camera_parents(_es, [(_self, "SELF")]))
check("③ 自指父 guid 被拒绝且相机保持根",
      _err3 is None and _self.parent is None and ("成环" in _out3),
      _out3.strip() or repr(_err3))

# ============ ④ 孤儿父（父已删）脱根 + 告警，不崩溃 ============
# 父相机从 engine.cameras 删除 -> 子相机仍指向它 -> 保存写出悬空 parent_id
eo = _engine()
op = mk_cam("gone-parent", (3, 0, 0))
oc = mk_cam("orphan-child", (1, 0, 0))
eo.cameras = [op, oc]
eo.set_camera_parent(oc, op, preserve_world=False)
eo.remove_camera(op)
_dorph = S.scene_to_dict(eo)
_osaved = {cm["id"]: cm for cm in _dorph["cameras"]}
check("④ 保存出现悬空 parent_id（父已不在 cameras[]）",
      _osaved["orphan-child"]["parent_id"] == "gone-parent"
      and all(cm["id"] != "gone-parent" for cm in _dorph["cameras"]),
      _osaved["orphan-child"].get("parent_id"))

_eo = _engine()
_ro, _outo, _erro = _cap(lambda: S.scene_from_dict(_eo, copy.deepcopy(_dorph)))
_och = {c.guid: c for c in _eo.cameras}["orphan-child"]
check("④ GL 孤儿父脱根（parent is None）且不崩溃",
      _erro is None and _och.parent is None,
      (getattr(_och.parent, "guid", None), repr(_erro)))
check("④ GL 孤儿父可见告警（含不存在/脱根字样）",
      ("不存在" in _outo) and ("脱根" in _outo),
      _outo.strip())

drv_o = SD.SceneDriver()
drv_o._bridge_disabled = True
_ro2, _outo2, _erro2 = _cap(lambda: drv_o.build_scene_from_data(copy.deepcopy(_dorph)))
_ovk = {c.guid: c for c in drv_o.cameras}["orphan-child"]
check("④ VK 孤儿父脱根（parent is None）且不崩溃",
      _erro2 is None and _ovk.parent is None,
      (getattr(_ovk.parent, "guid", None), repr(_erro2)))
check("④ VK 孤儿父可见告警（含不存在/脱根字样）",
      ("不存在" in _outo2) and ("脱根" in _outo2),
      _outo2.strip())

# ============ ⑤ 两端父链解析函数 is 同一对象（唯一实现） ============
import inspect
check("⑤ sceneio._link_camera_parents is driver.link_camera_parents",
      S._link_camera_parents is SD.link_camera_parents,
      (S._link_camera_parents, SD.link_camera_parents))
check("⑤ scene.camera._link_camera_parents is driver.link_camera_parents",
      SC._link_camera_parents is SD.link_camera_parents,
      (SC._link_camera_parents, SD.link_camera_parents))
check("⑤ driver.link_camera_parents 的源码文件 = scene/camera.py（无副本）",
      os.path.normcase(inspect.getsourcefile(SD.link_camera_parents)).endswith(
          os.path.normcase(os.path.join('scene', 'camera.py'))),
      inspect.getsourcefile(SD.link_camera_parents))
_pub = getattr(SC, "link_camera_parents", None)
check("⑤ 公开别名 link_camera_parents 与 _link_camera_parents 同一对象",
      _pub is not None and _pub is SC._link_camera_parents,
      (_pub, SC._link_camera_parents))

# ============ 汇总 ============
print("=" * 60)
if _FAILS:
    print("FAILED %d 条: %s" % (len(_FAILS), _FAILS))
    sys.exit(1)
print("总结果: ALL PASS ✅")
