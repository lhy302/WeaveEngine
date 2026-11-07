# -*- coding: utf-8 -*-
import sys as _sys_utf8
try:
    _sys_utf8.stdout.reconfigure(encoding='utf-8', errors='replace')
    _sys_utf8.stderr.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

# 2026-11-06 失败退出码闸门 (与既有 test_*.py 同款): 出现 "FAIL" 开头的行就把
# 进程退出码改成 1, 全 PASS 时行为完全不变。
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

"""test_light_vp_cache_roll.py — 编辑态阴影 VP 静止缓存键必须含 roll (2026-11-07 P1)

缺陷 (loom_lighting.py 旧 823-838 / _light_vps_cache_sig):
  缓存键里放的是 l.direction 向量, 而 LightState.direction 只由 azimuth/elevation
  派生 —— roll (倾斜) 只影响 up_vector()。于是在编辑态"光源静止"缓存下:
      改 roll -> 签名不变 -> 直接 return 上一帧的 _light_vps -> 阴影视图/光束截面
      不跟着转 (必须再动一下物体或角度才刷新)。
  修法: 签名加入 float(l.roll), 改 roll 立即失效重算。

本测试锁三条:
  A. roll 变化必须改变签名 (回归断言: 旧实现下两条签名相同);
  B. 签名变了就必须重算出**不同**的 VP (不是复用了旧矩阵);
  C. 状态没变时缓存仍然生效 (同一次 _light_vps 对象, 不白算 -> 不牺牲性能修法)。
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

import numpy as np                                     # noqa: E402

from loom_lighting import LightingMixin                # noqa: E402
from loom_scene_entities import LightState             # noqa: E402
from loom_types import Point3D                          # noqa: E402

_fails = []


def check(name, cond, detail=""):
    print(("PASS " if cond else "FAIL ") + name + ("  " + str(detail) if detail else ""))
    if not cond:
        _fails.append(name)


class _Model:
    visible = True


class VpEngine(LightingMixin):
    """最小宿主: 只喂 _compute_light_vps / _light_vps_cache_sig 需要的属性。
    无 GL / 无 DLL: _pipeline_light_vps 恒 False, 走 Python VP 路径。"""

    def __init__(self):
        self.lights = []
        self.models = [_Model(), _Model()]
        self._frame_world = np.zeros((2, 4, 4), dtype=np.float64)
        self._light_vps = {}
        self._light_vps_sig = None
        self._struct_gen = 0
        self.is_playing = False

    # --- 宿主依赖桩 ---
    def _pipeline_light_vps(self, aabbs, vps):
        return False

    def _model_aabbs_par(self, models, fw=None, visible_only=True):
        return [(Point3D(-1.0, -1.0, -1.0), Point3D(1.0, 1.0, 1.0)),
                (Point3D(-0.5, 0.0, -0.5), Point3D(2.0, 3.0, 0.5))]


def make_engine(roll=0.0, mode='full', shadow=True):
    eng = VpEngine()
    eng.lights.append(LightState(kind='directional', position=(0.0, 5.0, 0.0),
                                 azimuth=35.0, elevation=-40.0, roll=roll,
                                 shadow=shadow, mode=mode, size=5.0,
                                 name='d1'))
    return eng


def vp_of(eng):
    return np.asarray(eng._light_vps[eng.lights[0].guid], dtype=np.float64)


print("=" * 60)
print("A. roll 变化必须改变缓存签名")
print("=" * 60)
eng = make_engine(roll=0.0)
sig0 = eng._light_vps_cache_sig()
vp0 = vp_of_after = None
vps0 = eng._compute_light_vps()
vp0 = np.asarray(vps0[eng.lights[0].guid], dtype=np.float64)
check("A1 roll=0 时算出 VP (16 元素)", vp0.shape == (4, 4), vp0.shape)

eng.lights[0].roll = 30.0
sig1 = eng._light_vps_cache_sig()
check("A2 改 roll 后签名改变 (修复前相同 -> 缓存不失效)", sig1 != sig0,
      "sig_equal=%s" % (sig1 == sig0))

vps1 = eng._compute_light_vps()
vp1 = np.asarray(vps1[eng.lights[0].guid], dtype=np.float64)
check("A3 改 roll 后 VP 真的重算了 (不是复用旧矩阵)",
      np.max(np.abs(vp1 - vp0)) > 1e-6, "maxdiff=%.3e" % np.max(np.abs(vp1 - vp0)))

print("=" * 60)
print("B. roll 的语义位置: 只转正交框的 XY 基, 不动 z 行")
print("=" * 60)
# up_vector 决定视图矩阵的 up: roll=0 与 roll=30 的 up 不同 -> 视图 XY 基不同
up0 = LightState(kind='directional', azimuth=35.0, elevation=-40.0, roll=0.0).up_vector()
up1 = LightState(kind='directional', azimuth=35.0, elevation=-40.0, roll=30.0).up_vector()
dot_u = (up0.x * up1.x + up0.y * up1.y + up0.z * up1.z)
check("B1 roll 只绕光方向自旋: up 夹角 cos≈cos(30°)",
      abs(dot_u - np.cos(np.radians(30.0))) < 1e-9, "cos=%.6f" % dot_u)
# 行向量约定 (v_clip = v_world @ VP): 深度映射在**第 3 列**, 与 roll 无关
check("B2 深度列 (VP[:,2]) 不随 roll 变 (roll 只转 XY 基)",
      np.allclose(vp1[:, 2], vp0[:, 2], atol=1e-12),
      "col2_0=%s col2_1=%s" % (vp0[:, 2], vp1[:, 2]))

print("=" * 60)
print("C. roll 与其他角度参数同权: 改回 0 恢复原 VP")
print("=" * 60)
eng.lights[0].roll = 0.0
vps2 = eng._compute_light_vps()
vp2 = np.asarray(vps2[eng.lights[0].guid], dtype=np.float64)
check("C1 roll 回 0 -> VP 回到 roll=0 的值",
      np.allclose(vp2, vp0, atol=1e-12), "maxdiff=%.3e" % np.max(np.abs(vp2 - vp0)))
check("C2 改 roll 也会让签名回到旧值 (双向一致)",
      eng._light_vps_cache_sig() == sig0,
      "sig_equal=%s" % (eng._light_vps_cache_sig() == sig0))

print("=" * 60)
print("D. 状态不变时缓存仍生效 (修法不牺牲性能)")
print("=" * 60)
first = eng._compute_light_vps()          # C 段末尾刚重算过, 这里是新的 dict
cached = eng._compute_light_vps()
check("D1 签名不变 -> 直接返回上帧 _light_vps (同一对象, 零重算)",
      cached is first, "%s vs %s" % (id(cached), id(first)))
# 改结构代 -> 必须重算 (返回新的 dict, 不是上帧那份)
eng._struct_gen += 1
vp_re = eng._compute_light_vps()
check("D2 结构代变化 -> 重算 (缓存失效面未被削弱)", vp_re is not first,
      "重算后应产出新 dict")

print("=" * 60)
print("E. beam 光束截面同样吃 roll (u_light_ortho 走同一份 VP)")
print("=" * 60)
eng_beam = make_engine(roll=0.0, mode='beam')
b0 = np.asarray(eng_beam._compute_light_vps()[eng_beam.lights[0].guid], dtype=np.float64)
eng_beam.lights[0].roll = 45.0
b1 = np.asarray(eng_beam._compute_light_vps()[eng_beam.lights[0].guid], dtype=np.float64)
check("E1 beam 模式改 roll 后横截面基改变", np.max(np.abs(b1 - b0)) > 1e-6,
      "maxdiff=%.3e" % np.max(np.abs(b1 - b0)))

print("=" * 60)
if _fails:
    print("失败 %d 项: %s" % (len(_fails), _fails))
else:
    print("阴影 VP 缓存键 roll 全部 PASS")
