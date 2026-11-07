# -*- coding: utf-8 -*-
"""test_camera_robust_vk.py — 相机段坏值不崩 + 默认值与 GL/PlayerApp 不分叉.

scan_05 P-05 ([P1]): scene_driver.load_from_data 的相机段是裸 float()/tuple(),
同一函数内已有的 _f3/_f1 容错助手没用上 -> yaw='abc' / pitch=None /
target='abc' / target=[1,2] 四种坏场景在 VK 侧抛异常 (load 或 render_pose),
最后被 draw() 的 except 变成进程退出; 同一份文件 GL 全部正常加载。

scan_05 P-04 ([P2]): 默认值分叉 —— 有 camera 键但缺字段时 GL (sceneio) 兜底
0.6/-0.35, VK 却是 0/0; 完全没有 camera 键时 GL 走引擎默认 0/0, VK 也必须 0/0。
"""
import sys as _sys_utf8
try:
    _sys_utf8.stdout.reconfigure(encoding='utf-8', errors='replace')
    _sys_utf8.stderr.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

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


import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
os.environ.setdefault('LOOM_NO_PARALLEL', '1')
os.environ.setdefault('LOOM_NO_SAVE_MIGRATE', '1')

_fails = []


def check(name, cond, detail=""):
    print(("PASS " if cond else "FAIL ") + name + ("  " + str(detail) if detail else ""))
    if not cond:
        _fails.append(name)

import sceneio
import scene_driver as SD

BASE_CAM = {"target": [0, 0, 0], "distance": 10.0, "yaw": 0.6, "pitch": -0.35}
_MISSING = object()


def _scene(cam):
    d = {"version": 10, "materials": [], "objects": [], "lights": [], "cameras": []}
    if cam is not _MISSING:
        d["camera"] = cam
    return d


def gl_reference(cam):
    """GL 参考值: sceneio.scene_from_dict 的 camera_out 分支 (同一算法, 不手写)."""
    if cam is _MISSING or not cam:
        return None                      # 不给 camera_out -> 引擎默认 0/0
    return {"target": sceneio._f3(cam.get("target"), (0, 0, 0)),
            "distance": sceneio._f1(cam.get("distance"), 10.0),
            "yaw": sceneio._f1(cam.get("yaw"), 0.6),
            "pitch": sceneio._f1(cam.get("pitch"), -0.35)}


def _num_eq(a, b):
    """数值相等 (两端同时 NaN 也算"一致" —— 那是 shared 行为, 不是分叉)."""
    a, b = float(a), float(b)
    if a != a and b != b:
        return True
    return abs(a - b) < 1e-9


BAD_CASES = [
    ("yaw='abc'", {"target": [1, 2, 3], "distance": 12.0, "yaw": "abc", "pitch": 0.2}),
    ("pitch=None", {"target": [1, 2, 3], "distance": 12.0, "yaw": 0.3, "pitch": None}),
    ("target='abc'", {"target": "abc", "distance": 12.0, "yaw": 0.3, "pitch": 0.2}),
    ("target=[1,2]", {"target": [1, 2], "distance": 12.0, "yaw": 0.3, "pitch": 0.2}),
    ("target 含非数", {"target": [1, "x", 3], "distance": 12.0}),
    ("distance='abc'", {"target": [1, 2, 3], "distance": "abc", "yaw": 0.3}),
    ("yaw=nan 字符串", {"target": [1, 2, 3], "yaw": "nan"}),
    ("camera 不是 dict", ["not", "a", "dict"]),
]


def t_bad_cases_do_not_crash():
    """5 类坏字段 (加 3 个变体) 都必须加载成功 + render_pose 成功."""
    print("=== 相机坏值 (scan_05 P-05) ===")
    for name, cam in BAD_CASES:
        drv = None
        err = None
        try:
            drv = SD.SceneDriver()
            drv.load_from_data(_scene(cam))
            drv.render_pose(aspect=1.6)
        except BaseException as e:            # noqa: BLE001 - 崩了就是缺陷
            err = "%s: %s" % (type(e).__name__, e)
        check("坏相机段不崩: %s" % name, err is None, err)
        if err is not None:
            continue
        ref = gl_reference(cam if isinstance(cam, dict) else {})
        if isinstance(cam, dict):
            check("  与 GL 参考值一致: %s" % name,
                  (len(drv.target) == 3
                   and all(_num_eq(a, b) for a, b in zip(drv.target, ref["target"]))
                   and _num_eq(drv.distance, ref["distance"])
                   and _num_eq(drv.yaw, ref["yaw"])
                   and _num_eq(drv.pitch, ref["pitch"])),
                  (drv.target, drv.distance, drv.yaw, drv.pitch))
        else:
            check("  非 dict 的 camera 键回落默认 (0/0): %s" % name,
                  drv.yaw == 0.0 and drv.pitch == 0.0, (drv.yaw, drv.pitch))


def t_defaults_match_backend():
    """默认值分叉 (scan_05 P-04): 有键缺字段 -> 0.6/-0.35; 无键 -> 0/0."""
    print("=== 相机默认值 (scan_05 P-04) ===")
    key_only_target = {"target": [1, 2, 3]}
    d = SD.SceneDriver()
    d.load_from_data(_scene(key_only_target))
    ref = gl_reference(key_only_target)
    check("有 camera 键但缺 yaw/pitch -> 0.6/-0.35 (GL 同)",
          (round(d.yaw, 6), round(d.pitch, 6)) == (0.6, -0.35)
          and (d.yaw, d.pitch) == (ref["yaw"], ref["pitch"]), (d.yaw, d.pitch))

    d2 = SD.SceneDriver()
    d2.load_from_data(_scene(_MISSING))
    check("完全没有 camera 键 -> 0/0 (PlayerApp 同)",
          (d2.yaw, d2.pitch) == (0.0, 0.0), (d2.yaw, d2.pitch))

    d3 = SD.SceneDriver()
    d3.load_from_data(_scene({}))
    check("空 camera 对象 -> 也算没有 (sceneio 同口径): 0/0",
          (d3.yaw, d3.pitch) == (0.0, 0.0), (d3.yaw, d3.pitch))

    d4 = SD.SceneDriver()
    d4.load_from_data(_scene(dict(BASE_CAM)))
    check("四字段齐全 -> 原样采用",
          (d4.yaw, d4.pitch, d4.distance) == (0.6, -0.35, 10.0),
          (d4.yaw, d4.pitch, d4.distance))


def t_render_pose_stable_after_bad_target():
    """坏 target 之后 VP 必须仍有意义 (不是 nan/异常)."""
    import numpy as np
    d = SD.SceneDriver()
    d.load_from_data(_scene({"target": "abc", "distance": "x", "yaw": None}))
    vp, cam = d.render_pose(aspect=1.5)
    arr = np.asarray(vp)
    check("坏值后 VP 有限", bool(np.isfinite(arr).all()), arr.shape)
    check("坏值后相机位置有限", all(abs(v) < 1e6 for v in cam), cam)


def main():
    t_bad_cases_do_not_crash()
    t_defaults_match_backend()
    t_render_pose_stable_after_bad_target()
    print("=" * 60)
    if _fails:
        print("失败:", _fails)
        return 1
    print("ALL PASS")
    return 0


if __name__ == '__main__':
    sys.exit(main())
