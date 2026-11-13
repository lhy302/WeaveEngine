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

"""test_light_shadow_slots.py — 阴影贴图槽位分配回归 (2026-11-07 P0/P1; 2026-11-13 T3c-1 迁移)

缺陷 (docs/audit/scan_03_gl_render.md 第 1/2 项, loom_lighting.py 旧 171-180):
  · 阴影采样器数组 16 槽, 着色器对 kind>0.5 (点光/聚光灯) 统一走
    point_shadow(slot) 采样 slot..slot+5 共 6 张面图;
  · 旧代码 need = 6 if kind=='point' else 1 —— 聚光灯只登记 1 槽却绑 6 张面图:
    ① 面 1..5 的单元号落进"后一盏灯"刚绑的深度图 -> 阴影错位;
    ② 累加器越过 15 时 sampler_units[16] 直接 IndexError (2 投影点光 + 1 投影
       聚光灯 + 1 平行光即触发)。

T3c-1 (4a66faa) 起逐灯参数整体搬进 std140 Scene UBO (loom_scene_ubo.py 单表生成),
u_shadow_slot 这个逐灯 uniform 已不存在。槽位/面图单元号的新真实通路:
  · 槽位           = Scene UBO lights[i].params.w  (loom_scene_ubo.py:29, 157-158)
                     <- _upload_lights 的 b['slots']  (loom_lighting.py:111, 181)
  · shadow 开关    = Scene UBO lights[i].kind.w    (loom_scene_ubo.py:24, 149-150)
  · 面图单元号     = 独立 sampler 数组 u_shadow_maps[16] 的 value
                     (不能进 UBO; loom_lighting.py:214-217), 与
                     sampler_units[unit-1+k] = unit+k (loom_lighting.py:185) 一致。
  · 着色器消费点   = main.frag:212-226 读 params.w, compat:87-88 用
                     u_shadow_maps[slot+face] 采样。

本测试锁:
  A. 每盏非定向阴影光登记 6 槽, 且 6 张面图的纹理单元 = 该灯自己的面图 (guid 绑定);
  B. 16 槽预算用尽时**降级不崩**: 多余的灯 shadow 置 False + 只打印一次警告;
  C. 预算内的组合 (1 点光 + 1 聚光灯 + 2 平行光 = 14 槽) 全部正常登记。

全程无 GL 上下文: 用假 program/假深度纹理/假 UBO buffer 驱动真实的 _upload_lights。
槽位一律从 Scene UBO 的**原始字节**里按灯基址读回 (假 buffer 记录真正的 write),
不是读 _light_bufs 之类打包前的中间量。
"""
import contextlib
import io
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

import numpy as np                              # noqa: E402

import loom_scene_ubo as SU                     # noqa: E402
from loom_lighting import LightingMixin         # noqa: E402
from loom_scene_entities import LightState      # noqa: E402
from loom_types import Point3D                  # noqa: E402

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


class FakeSceneUBO:
    """假 Scene UBO: 记录 _upload_lights 真正写到 GPU 侧的 std140 原始字节。"""

    def __init__(self, reserve):
        self.reserve = int(reserve)
        self.raw = None
        self.binding = None
        self.writes = 0

    def write(self, data):
        raw = bytes(data)
        if len(raw) != self.reserve:
            raise AssertionError('Scene UBO write %d B != reserve %d B'
                                 % (len(raw), self.reserve))
        self.raw = raw
        self.writes += 1

    def bind_to_uniform_block(self, binding):
        self.binding = int(binding)


class FakeCtx:
    def __init__(self):
        self.buffers = []

    def buffer(self, data=None, reserve=None, **kw):
        buf = FakeSceneUBO(reserve if reserve else 0)
        self.buffers.append(buf)
        return buf


class SlotEngine(LightingMixin):
    """最小宿主: 喂 _upload_lights 在新通路 (T3c-1) 上真实需要的属性 (无 GL / 无窗口)。

    camera/_vp:
        loom_lighting.py:197-206 的 pack_arrays(_vp, _cam, ...) 需要它们填 Scene UBO
        的 mvp/cam 字段 —— 这是新通路本身的一部分, 不是为了掩盖缺陷的假数据。
    ctx/_scene_ubo:
        loom_lighting.py:207-208 惰性创建 `self.ctx.buffer(reserve=SU.BYTES)`;
        假 buffer 记录真实 write 的字节, 测试再从这份字节读回槽位。
    """

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
        # T3c-1 场景 UBO 真实依赖的宿主属性
        self.camera = Point3D(0.0, 0.0, 5.0)
        self._vp = np.eye(4, dtype=np.float64)
        self.ctx = FakeCtx()
        self._scene_ubo = None

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
        """跑真实 _upload_lights, 再从新通路读回:
        (Scene UBO 8 灯条目槽位, u_shadow_maps 16 单元号, UBO shadow 标志, 有效灯数)
        """
        self._upload_lights()
        units = self.prog['u_shadow_maps'].value
        return (ubo_slots(self), tuple(int(x) for x in units),
                ubo_shadow_flags(self), ubo_light_count(self))


def build(layout):
    eng = SlotEngine()
    made = {}
    for kind, name in layout:
        made[name] = eng.add(kind, name)
    return eng, made


def face_units(eng, light):
    return [t.unit for t in eng._shadow_maps[light.guid]['tex']]


# ---------------- 新通路读回 (Scene UBO raw bytes) ----------------
def _scene_f32(eng):
    """从假 Scene UBO 读回 _upload_lights 真正写下去的 std140 字节。"""
    buf = getattr(eng, '_scene_ubo', None)
    raw = getattr(buf, 'raw', None)
    if raw is None:
        raise AssertionError('_upload_lights 未创建/未写入 Scene UBO')
    if len(raw) != SU.BYTES:
        raise AssertionError('Scene UBO 字节数 %d != %d' % (len(raw), SU.BYTES))
    return np.frombuffer(raw, dtype='<f4')


def ubo_slots(eng):
    """8 个灯条目的阴影槽位 (lights[i].params.w, LO_PARAMS+3)。未使用条目由
    pack_arrays 保持 0, 但着色器只遍历 i < misc.y, 所以它们不会被采样。"""
    f = _scene_f32(eng)
    return tuple(int(round(float(f[SU.light_base(i) + SU.LO_PARAMS + 3])))
                 for i in range(SU.LIGHTS))


def ubo_shadow_flags(eng):
    """8 个灯条目的 shadow 标志 (lights[i].kind.w; slot<0 时 pack 写 0)。"""
    f = _scene_f32(eng)
    return tuple(int(round(float(f[SU.light_base(i) + SU.LO_KIND + 3])))
                 for i in range(SU.LIGHTS))


def ubo_light_count(eng):
    """Scene UBO misc.y = 有效灯数 (着色器循环上界)。"""
    f = _scene_f32(eng)
    return int(round(float(f[SU.OFF_MISC + 1])))


# ============ A. 2 投影点光 + 1 投影聚光灯 + 1 平行光 (超预算, 必须降级不崩) ============
print("=" * 60)
print("A. 2 点光 + 1 聚光灯 + 1 平行光 (16 槽预算超限)")
print("=" * 60)
eng, made = build([('point', 'p1'), ('point', 'p2'), ('spot', 's1'),
                   ('directional', 'd1')])
buf = io.StringIO()
raised = None
slots = units = flags = count = None
try:
    with contextlib.redirect_stdout(buf):
        slots, units, flags, count = eng.upload()
except Exception as e:                          # noqa: BLE001
    raised = e
warn = buf.getvalue()

check("A1 不再抛 IndexError", raised is None, repr(raised))
check("A2 Scene UBO 8 灯条目槽位 ∈ -1/0..15, 有效灯数 4 (着色器只读前 4 条)",
      slots is not None and len(slots) == 8
      and all(-1 <= s <= 15 for s in slots) and count == 4, (slots, count))
check("A3 点光各占连续 6 槽 (p1=0, p2=6)", slots is not None
      and slots[:2] == (0, 6), slots)
check("A4 超限的聚光灯 shadow 被关掉 (宿主 False + UBO kind.w=0)", 
      made['s1'].shadow is False and flags is not None and flags[2] == 0,
      (made['s1'].shadow, flags))
check("A5 聚光灯不再占用槽位 (-1)", slots is not None and slots[2] == -1, slots)
check("A6 仍有余量的平行光照常拿到 1 槽", slots is not None and slots[3] == 12,
      slots)
check("A7 警告只打印一次 (且说明了槽位上限)", warn.count('槽位上限 16') == 1,
      repr(warn))
check("A8 已分配的 6 面确实绑到本灯自己的面图", face_units(eng, made['p1']) == list(range(1, 7))
      and face_units(eng, made['p2']) == list(range(7, 13)),
      (face_units(eng, made['p1']), face_units(eng, made['p2'])))
check("A9 sampler_units 与槽位自洽 (下标=槽, 值=物理单元)",
      units == (1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 0, 0, 0), units)
# 每个已分配槽位 k 的 6 张面图 = 单元 [slot+1 .. slot+6]
ok_slots = slots is not None
slot_p1 = slots[0] if slots is not None else -99
if ok_slots:
    for k in range(6):
        if (slot_p1 + 1 + k) != face_units(eng, made['p1'])[k]:
            ok_slots = False
check("A10 槽位 k -> 面图单元 [slot+1, slot+6] 连续 (着色器 point_shadow 口径)",
      ok_slots, slot_p1)

# 第二次上传: 被降级的灯已无 shadow, 不应再喊
buf2 = io.StringIO()
slots2 = None
with contextlib.redirect_stdout(buf2):
    slots2, _u2, _f2, _c2 = eng.upload()
check("A11 二次上传不重复告警 (只喊一次)", buf2.getvalue() == '', repr(buf2.getvalue()))
check("A12 二次上传槽位稳定 (Scene UBO 重读)", slots is not None
      and slots2 == slots, (slots, slots2))

# ============ B. 预算内组合: 1 点光 + 1 聚光灯 + 2 平行光 = 14 槽 ============
print("=" * 60)
print("B. 1 点光 + 1 聚光灯 + 2 平行光 (14 槽, 全登记)")
print("=" * 60)
eng_b, made_b = build([('point', 'p1'), ('spot', 's1'),
                       ('directional', 'd1'), ('directional', 'd2')])
buf_b = io.StringIO()
raised_b = None
slots_b = units_b = flags_b = count_b = None
try:
    with contextlib.redirect_stdout(buf_b):
        slots_b, units_b, flags_b, count_b = eng_b.upload()
except Exception as e:                          # noqa: BLE001
    raised_b = e

check("B1 无异常", raised_b is None, repr(raised_b))
check("B2 无告警 (预算内)", buf_b.getvalue() == '', repr(buf_b.getvalue()))
# T3c-1: Scene UBO 固定 8 条灯位, 后 4 条由 misc.y 门控 (着色器只读到 4), 不再写 -1。
check("B3 槽位分配 点光=0 聚光灯=6 平行光=12,13 (前 4 条有效, UBO misc.y=4)",
      slots_b is not None and count_b == 4
      and slots_b[:4] == (0, 6, 12, 13)
      and flags_b[4:] == (0, 0, 0, 0),
      (slots_b, count_b, flags_b))
check("B4 聚光灯 shadow 保持开启", made_b['s1'].shadow is True, made_b['s1'].shadow)
check("B5 聚光灯 6 面绑到自己的面图 (修复前只登记 1 槽)", 
      face_units(eng_b, made_b['s1']) == list(range(7, 13)),
      face_units(eng_b, made_b['s1']))
check("B6 点光 6 面绑到自己的面图", face_units(eng_b, made_b['p1']) == list(range(1, 7)),
      face_units(eng_b, made_b['p1']))
# 着色器按 slot 取 6 面: slot_k = slots[i] 时, 面图单元必须是 slot_k+1 .. slot_k+6
shader_ok = slots_b is not None
if shader_ok:
    for i, L in enumerate(eng_b.lights):
        s = slots_b[i]
        if L.kind == 'directional':
            continue
        want = [s + 1 + k for k in range(6)]
        if face_units(eng_b, L) != want:
            shader_ok = False
check("B7 每盏非定向灯: 面图单元 = slot+1..slot+6 (无跨灯串图)", shader_ok,
      [] if slots_b is None else [(slots_b[i], face_units(eng_b, L))
                                  for i, L in enumerate(eng_b.lights)])

# ============ C. 2 聚光灯 + 1 点光 (超预算: 第三盏降级) ============
print("=" * 60)
print("C. 2 聚光灯 + 1 点光 (超预算, 第三盏降级)")
print("=" * 60)
eng_c, made_c = build([('spot', 's1'), ('spot', 's2'), ('point', 'p1')])
buf_c = io.StringIO()
raised_c = None
slots_c = units_c = flags_c = count_c = None
try:
    with contextlib.redirect_stdout(buf_c):
        slots_c, units_c, flags_c, count_c = eng_c.upload()
except Exception as e:                          # noqa: BLE001
    raised_c = e

check("C1 无异常", raised_c is None, repr(raised_c))
check("C2 两盏聚光灯各 6 槽 (0, 6), 点光降级 (-1) (前 3 条有效)",
      slots_c is not None and count_c == 3
      and slots_c[:3] == (0, 6, -1), (slots_c, count_c))
check("C3 降级的是第三盏 (点光): 宿主 shadow + UBO kind.w 一致",
      (made_c['s1'].shadow, made_c['s2'].shadow,
       made_c['p1'].shadow) == (True, True, False)
      and flags_c is not None and flags_c[:3] == (1, 1, 0),
      ([L.shadow for L in eng_c.lights], flags_c))
check("C4 降级告警出现一次", buf_c.getvalue().count('槽位上限 16') == 1,
      repr(buf_c.getvalue()))
check("C5 聚光灯 s2 面图绑到自己的 (7..12)", face_units(eng_c, made_c['s2'])
      == list(range(7, 13)), face_units(eng_c, made_c['s2']))

print("=" * 60)
if _fails:
    print("失败 %d 项: %s" % (len(_fails), _fails))
else:
    print("阴影贴图槽位分配 全部 PASS")
