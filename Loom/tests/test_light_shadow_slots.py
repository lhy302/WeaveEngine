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

"""test_light_shadow_slots.py — 阴影贴图槽位分配回归 (2026-11-07 P0/P1)

缺陷 (docs/audit/scan_03_gl_render.md 第 1/2 项, loom_lighting.py 旧 171-180):
  · u_shadow_maps 是 16 槽 sampler 数组, 着色器对 u_light_kind>0.5 (点光/聚光灯)
    统一走 point_shadow(u_shadow_slot[i]) 采样 slot..slot+5 共 6 张面图;
  · 旧代码 need = 6 if kind=='point' else 1 —— 聚光灯只登记 1 槽却绑 6 张面图:
    ① 面 1..5 的单元号落进"后一盏灯"刚绑的深度图 -> 阴影错位;
    ② 累加器越过 15 时 sampler_units[16] 直接 IndexError (2 投影点光 + 1 投影
       聚光灯 + 1 平行光即触发)。

本测试锁:
  A. 每盏非定向阴影光登记 6 槽, 且 6 张面图的纹理单元 = 该灯自己的面图 (guid 绑定);
  B. 16 槽预算用尽时**降级不崩**: 多余的灯 shadow 置 False + 只打印一次警告;
  C. 预算内的组合 (1 点光 + 1 聚光灯 + 2 平行光 = 14 槽) 全部正常登记。

全程无 GL 上下文: 用假 program/假深度纹理驱动真实的 _upload_lights。
"""
import contextlib
import io
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

import numpy as np                              # noqa: E402

from loom_lighting import LightingMixin         # noqa: E402
from loom_scene_entities import LightState      # noqa: E402

_fails = []


def check(name, cond, detail=""):
    print(("PASS " if cond else "FAIL ") + name + ("  " + str(detail) if detail else ""))
    if not cond:
        _fails.append(name)


# ---------------- 假 GL 资源 ----------------
class FakeTex:
    """假深度纹理: 只记录自己被绑到哪个纹理单元。"""

    def __init__(self, tag):
        self.tag = tag
        self.unit = None

    def use(self, unit):
        self.unit = int(unit)


class FakeUniform:
    def __init__(self, name):
        self.name = name
        self.value = None
        self.writes = []

    def write(self, raw):
        self.writes.append(raw)


class FakeProg:
    def __init__(self):
        self.uniforms = {}

    def __getitem__(self, name):
        u = self.uniforms.get(name)
        if u is None:
            u = self.uniforms[name] = FakeUniform(name)
        return u


class SlotEngine(LightingMixin):
    """最小宿主: 只喂 _upload_lights 需要的属性 (无 GL / 无窗口)。"""

    def __init__(self):
        self.lights = []
        self.models = []
        self.prog = FakeProg()
        self._u = {}
        self._u_last = {}
        self._shadow_maps = {}
        self._shadow_res = 1024
        self._shadow_point_res = 512
        self._shadow_point_far = 30.0
        self._light_vps = {}
        self._struct_gen = 0
        self._frame_world = None
        self.is_playing = False

    # --- 宿主依赖桩 ---
    def _release_shadow_map(self, sm):
        pass

    def _dir_light_vp(self, light):
        return np.eye(4, dtype=np.float64)

    # --- 建灯 + 建阴影贴图 (镜像 ShadowMixin._ensure_shadow_map 的贴图张数) ---
    def add(self, kind, name, shadow=True, **kw):
        light = LightState(kind=kind, position=(0.0, 5.0, 0.0),
                           direction=(0.0, -1.0, 0.0), shadow=shadow,
                           name=name, **kw)
        self.lights.append(light)
        n = 1 if kind == 'directional' else 6
        self._shadow_maps[light.guid] = {
            'type': 'dir' if kind == 'directional' else 'point',
            'tex': [FakeTex('%s#%d' % (name, i)) for i in range(n)],
            'fbo': []}
        return light

    def upload(self):
        self._upload_lights()
        return (tuple(int(x) for x in self.prog['u_shadow_slot'].value),
                tuple(int(x) for x in self.prog['u_shadow_maps'].value))


def build(layout):
    eng = SlotEngine()
    made = {}
    for kind, name in layout:
        made[name] = eng.add(kind, name)
    return eng, made


def face_units(eng, light):
    return [t.unit for t in eng._shadow_maps[light.guid]['tex']]


# ============ A. 2 投影点光 + 1 投影聚光灯 + 1 平行光 (超预算, 必须降级不崩) ============
print("=" * 60)
print("A. 2 点光 + 1 聚光灯 + 1 平行光 (16 槽预算超限)")
print("=" * 60)
eng, made = build([('point', 'p1'), ('point', 'p2'), ('spot', 's1'),
                   ('directional', 'd1')])
buf = io.StringIO()
raised = None
try:
    with contextlib.redirect_stdout(buf):
        slots, units = eng.upload()
except Exception as e:                          # noqa: BLE001
    raised = e
    slots = units = None
warn = buf.getvalue()

check("A1 不再抛 IndexError", raised is None, repr(raised))
check("A2 u_shadow_slot 8 元素 / 面图单元号全在 0..15", slots is not None
      and len(slots) == 8 and all(-1 <= s <= 15 for s in slots), slots)
check("A3 点光各占连续 6 槽 (p1=0, p2=6)", slots[:2] == (0, 6), slots)
check("A4 超限的聚光灯 shadow 被关掉 (降级)", made['s1'].shadow is False,
      made['s1'].shadow)
check("A5 聚光灯不再占用槽位 (-1)", slots[2] == -1, slots)
check("A6 仍有余量的平行光照常拿到 1 槽", slots[3] == 12, slots)
check("A7 警告只打印一次 (且说明了槽位上限)", warn.count('槽位上限 16') == 1, repr(warn))
check("A8 已分配的 6 面确实绑到本灯自己的面图", face_units(eng, made['p1']) == list(range(1, 7))
      and face_units(eng, made['p2']) == list(range(7, 13)),
      (face_units(eng, made['p1']), face_units(eng, made['p2'])))
check("A9 sampler_units 与槽位自洽 (下标=槽, 值=物理单元)",
      units == (1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 0, 0, 0), units)
# 每个已分配槽位 k 的 6 张面图 = 单元 [slot+1 .. slot+6]
ok_slots = True
slot_p1 = slots[0]
for k in range(6):
    if (slot_p1 + 1 + k) != face_units(eng, made['p1'])[k]:
        ok_slots = False
check("A10 槽位 k -> 面图单元 [slot+1, slot+6] 连续 (着色器 point_shadow 口径)",
      ok_slots, slot_p1)

# 第二次上传: 被降级的灯已无 shadow, 不应再喊
buf2 = io.StringIO()
with contextlib.redirect_stdout(buf2):
    slots2, units2 = eng.upload()
check("A11 二次上传不重复告警 (只喊一次)", buf2.getvalue() == '', repr(buf2.getvalue()))
check("A12 二次上传槽位稳定", slots2 == slots, (slots, slots2))

# ============ B. 预算内组合: 1 点光 + 1 聚光灯 + 2 平行光 = 14 槽 ============
print("=" * 60)
print("B. 1 点光 + 1 聚光灯 + 2 平行光 (14 槽, 全登记)")
print("=" * 60)
eng_b, made_b = build([('point', 'p1'), ('spot', 's1'),
                       ('directional', 'd1'), ('directional', 'd2')])
buf_b = io.StringIO()
raised_b = None
try:
    with contextlib.redirect_stdout(buf_b):
        slots_b, units_b = eng_b.upload()
except Exception as e:                          # noqa: BLE001
    raised_b = e
    slots_b = units_b = None

check("B1 无异常", raised_b is None, repr(raised_b))
check("B2 无告警 (预算内)", buf_b.getvalue() == '', repr(buf_b.getvalue()))
check("B3 槽位分配 点光=0 聚光灯=6 平行光=12,13",
      slots_b == (0, 6, 12, 13, -1, -1, -1, -1), slots_b)
check("B4 聚光灯 shadow 保持开启", made_b['s1'].shadow is True, made_b['s1'].shadow)
check("B5 聚光灯 6 面绑到自己的面图 (修复前只登记 1 槽)", 
      face_units(eng_b, made_b['s1']) == list(range(7, 13)),
      face_units(eng_b, made_b['s1']))
check("B6 点光 6 面绑到自己的面图", face_units(eng_b, made_b['p1']) == list(range(1, 7)),
      face_units(eng_b, made_b['p1']))
# 着色器按 slot 取 6 面: slot_k = slots[i] 时, 面图单元必须是 slot_k+1 .. slot_k+6
shader_ok = True
for i, L in enumerate(eng_b.lights):
    s = slots_b[i]
    if L.kind == 'directional':
        continue
    want = [s + 1 + k for k in range(6)]
    if face_units(eng_b, L) != want:
        shader_ok = False
check("B7 每盏非定向灯: 面图单元 = slot+1..slot+6 (无跨灯串图)", shader_ok,
      [(slots_b[i], face_units(eng_b, L)) for i, L in enumerate(eng_b.lights)])

# ============ C. 2 聚光灯 + 1 点光 (超预算: 第三盏降级) ============
print("=" * 60)
print("C. 2 聚光灯 + 1 点光 (超预算, 第三盏降级)")
print("=" * 60)
eng_c, made_c = build([('spot', 's1'), ('spot', 's2'), ('point', 'p1')])
buf_c = io.StringIO()
raised_c = None
try:
    with contextlib.redirect_stdout(buf_c):
        slots_c, units_c = eng_c.upload()
except Exception as e:                          # noqa: BLE001
    raised_c = e
    slots_c = units_c = None

check("C1 无异常", raised_c is None, repr(raised_c))
check("C2 两盏聚光灯各 6 槽 (0, 6), 点光降级 (-1)",
      slots_c == (0, 6, -1, -1, -1, -1, -1, -1), slots_c)
check("C3 降级的是第三盏 (点光)", (made_c['s1'].shadow, made_c['s2'].shadow,
                                    made_c['p1'].shadow) == (True, True, False),
      [L.shadow for L in eng_c.lights])
check("C4 降级告警出现一次", buf_c.getvalue().count('槽位上限 16') == 1,
      repr(buf_c.getvalue()))
check("C5 聚光灯 s2 面图绑到自己的 (7..12)", face_units(eng_c, made_c['s2'])
      == list(range(7, 13)), face_units(eng_c, made_c['s2']))

print("=" * 60)
if _fails:
    print("失败 %d 项: %s" % (len(_fails), _fails))
else:
    print("阴影贴图槽位分配 全部 PASS")
