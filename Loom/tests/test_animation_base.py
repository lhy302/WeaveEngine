# -*- coding: utf-8 -*-

"""test_animation_base.py — beta6 批次 C1「动画底座」回归硬门.

覆盖 docs/design/research_beta6_03_animation.md 批次1 五条:
  ① 去复刻: engine(FrameComponentMixin) 与 scene_driver(SceneDriver) 共用
     loom_components.evaluate_animations —— 同一份内核, 两宿主数值一致;
  ② SoA 批量求值: 与逐物体 sample() **逐位一致** (含段边界/外推) + 性能对照;
  ③ 时间语义: once 到点=末帧 / 跨多周期规范化 / pingpong / seek / 变速 /
     每片段循环模式 (旧实现两个真 bug 的回归锁);
  ④ 序列化 v2 + undo 值隔离: time/playing 不落盘; speed/clip_meta 往返;
     undo 快照与模型互不污染 (旧实现共享同一 clips 字典);
  ⑤ 写者优先级 D6「动画只驱动 kinematic/静态体」: 动态刚体跳过 + 只告警一次;
     物理管线开/关两种配置下结果一致 (旧实现两条路径胜负相反)。

跑法: cd Loom && python tests/test_animation_base.py
"""
import sys as _sys_utf8
try:
    _sys_utf8.stdout.reconfigure(encoding='utf-8', errors='replace')
    _sys_utf8.stderr.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

# 失败退出码闸门 (P-02 同款: 只由断言决定, 不被控制台编码假失败污染)
import atexit as _atexit_gate
import os as _os_gate
import sys as _sys_gate


class _FailGateStream:
    def __init__(self, stream):
        self.stream = stream
        self.failed = False

    def write(self, text):
        if isinstance(text, str) and (text.startswith("FAIL") or "\nFAIL" in text):
            self.failed = True
        return self.stream.write(text)

    def __getattr__(self, name):
        return getattr(self.stream, name)


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
import io
import math
import os
import struct
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

import engine as E
import sceneio as S
import scene_driver as SD
import undo as U
import loom_components as C
import loom_frame_components as LFC
from mesh import create_cube

E.GLEngine._build_gpu = lambda self, m: None

ok = True


def check(label, cond, detail=""):
    global ok
    print(("PASS " if cond else "FAIL ") + label + ("  " + detail if detail else ""))
    if not cond:
        ok = False


def bits(x):
    return struct.pack('<d', float(x))


def same_bits(a, b):
    return bits(a) == bits(b)


def make_engine(models=None):
    e = E.GLEngine.__new__(E.GLEngine)
    e.models = models if models is not None else []
    e.materials = []
    e.lights = []
    e.current_model_index = 0
    return e


def add_anim_obj(e, clip, name='c', loop=True, pos=(0, 0, 0)):
    m = e.add_model(create_cube(1.0), E.Point3D(*pos), E.Point3D(0, 0, 0))
    an = m.add_animator(clips={name: clip}, current=name, loop=loop)
    an.playing = True
    return m, an


def full_clip(times=(0.0, 0.4, 0.9), scale_last=2.0, loop_mode=None):
    frames = []
    for i, t in enumerate(times):
        frames.append({'time': t,
                       'position': (0.0, 1.0 * i, 2.0 * i),
                       'rotation': (0.1 * i, 0.2 * i, 0.3 * i),
                       'scale': (1.0 + 0.1 * i, 1.0 + 0.1 * i, 1.0 + 0.1 * i)})
    return E.AnimationClip(frames, loop_mode=loop_mode)


# ============================================================================
print('---- ① 去复刻: 两宿主同一份内核 ----')
# ============================================================================
stub = SD.SceneDriver._update_animations.__code__.co_names
check('① scene_driver._update_animations 只调 evaluate_animations',
      'evaluate_animations' in stub and 'sample' not in stub, str(stub))
stub2 = LFC.FrameComponentMixin.update_animations.__code__.co_names
check('① engine.update_animations 只调 evaluate_animations',
      'evaluate_animations' in stub2 and 'sample' not in stub2, str(stub2))

steps = [0.017, 0.033, 0.021, 0.05, 0.011, 0.033, 0.033, 0.029]
e1 = make_engine()
c1 = full_clip()
m1, _ = add_anim_obj(e1, c1)
drv = SD.SceneDriver.__new__(SD.SceneDriver)
drv.models = []
e2 = make_engine()
m2, _ = add_anim_obj(e2, full_clip())
drv.models = e2.models
for dt in steps:
    e1.update_animations(dt)                      # FrameComponentMixin 入口
    SD.SceneDriver._update_animations(drv, dt)    # SceneDriver 入口
check('① 两宿主 8 帧后 position 逐位一致', m1.position == m2.position,
      '%r vs %r' % (tuple(m1.position), tuple(m2.position)))
check('① 两宿主 rotation/scale 逐位一致',
      m1.rotation == m2.rotation and m1.scale == m2.scale)

# ============================================================================
print('---- ② SoA 批量求值与逐物体 sample 逐位一致 ----')
# ============================================================================
import numpy as np
rng = np.random.default_rng(20261110)
mismatch = 0
total_cmp = 0
for case in range(40):
    nf = int(rng.integers(3, 9))
    ts = np.cumsum(rng.uniform(0.01, 0.4, size=nf))
    ts[0] = 0.0
    frames = []
    for i in range(nf):
        frames.append({'time': float(ts[i]),
                       'position': tuple(rng.uniform(-5, 5, 3).tolist()),
                       'rotation': tuple(rng.uniform(-3, 3, 3).tolist()),
                       'scale': tuple(rng.uniform(0.5, 2, 3).tolist())})
    clip = E.AnimationClip(frames)
    if not clip._np_fast:
        continue
    times, vals = clip._np_batch
    dur = clip.duration
    # 相位由调用方 (evaluate_animations) 归一到 [0, dur); 这里只比较该区间,
    # 外加各关键帧时刻 —— 归一化本身由 ③ 的断言语义覆盖。
    probes = list(rng.uniform(0.0, dur * 0.999999, size=40))
    probes += [0.0, float(ts[0]), float(ts[1]), float(ts[-1]) * 0.5,
               (float(ts[1]) + float(ts[2])) / 2.0]
    phases = np.asarray(probes, dtype=np.float64)
    with np.errstate(divide='ignore', invalid='ignore'):
        batched, okm = C._sample_batch(times, vals, phases)
    for j, t in enumerate(probes):
        if not okm[j]:
            continue
        ref = clip.sample(float(t))
        for ch in ('position', 'rotation', 'scale'):
            for d in range(3):
                total_cmp += 1
                if not same_bits(batched[ch][j][d], ref[ch][d]):
                    mismatch += 1
check('② 随机片段 40 组×40+ 相位 三通道逐位一致 (%d 次比较)' % total_cmp,
      mismatch == 0, 'mismatch=%d' % mismatch)

# 快路径片段 vs 慢路径片段 (缺通道) 的 position 轨迹一致
e3 = make_engine()
fast_clip = E.AnimationClip([
    {'time': 0.0, 'position': (0.0, 0.0, 0.0), 'rotation': (0.0, 0.0, 0.0), 'scale': (1.0, 1.0, 1.0)},
    {'time': 0.4, 'position': (1.0, 2.0, 3.0), 'rotation': (0.1, 0.2, 0.3), 'scale': (1.0, 1.0, 1.0)},
    {'time': 0.9, 'position': (4.0, 5.0, 6.0), 'rotation': (0.4, 0.5, 0.6), 'scale': (2.0, 2.0, 2.0)}])
slow_clip = E.AnimationClip([
    {'time': 0.0, 'position': (0.0, 0.0, 0.0)},
    {'time': 0.4, 'position': (1.0, 2.0, 3.0)},
    {'time': 0.9, 'position': (4.0, 5.0, 6.0)}])
mf, _ = add_anim_obj(e3, fast_clip, name='f')
msl, _ = add_anim_obj(e3, slow_clip, name='s')
for _ in range(60):
    e3.update_animations(0.0173)
check('② 批量路径(快) 与 逐物体路径(慢) position 逐位一致',
      all(same_bits(a, b) for a, b in zip(mf.position, msl.position)),
      '%r vs %r' % (tuple(mf.position), tuple(msl.position)))

# 性能对照: 500 动画物体, 新批量 vs 本文件内联的旧逐物体实现
perf_frames = []
for i in range(11):
    perf_frames.append({'time': i * 0.1, 'position': (0.0, i * 0.1, 0.0),
                        'rotation': (0.0, 0.0, 0.0), 'scale': (1.0, 1.0, 1.0)})
perf_clip = E.AnimationClip(perf_frames)


def build_500():
    e = make_engine()
    for i in range(500):
        m, an = add_anim_obj(e, perf_clip, pos=(float(i), 0, 0))
        an.time = (i % 10) * 0.05
    return e


def legacy_update(models, dt):
    """旧实现 (逐物体 sample + property 写回) —— 仅作本测试的性能基准."""
    for m in models:
        an = m.animator
        if an is None or not an.playing or not an.current:
            continue
        clip = an.clips.get(an.current)
        if clip is None or not clip.frames:
            continue
        an.time += dt
        s = clip.sample(an.time)
        if 'position' in s:
            m.position = E.Point3D(*s['position'])
        if 'rotation' in s:
            m.rotation = E.Point3D(*s['rotation'])
        if 'scale' in s:
            m.set_scale(s['scale'])
        if clip.duration > 0 and an.time >= clip.duration:
            if an.loop:
                an.time -= clip.duration
            else:
                an.playing = False


DT_PERF = 1.0 / 30.0
e_perf = build_500()
e_perf.update_animations(DT_PERF)                     # 预热
t0 = time.perf_counter()
for _ in range(60):
    e_perf.update_animations(DT_PERF)
ms_new = (time.perf_counter() - t0) / 60 * 1000.0
e_old = build_500()
t0 = time.perf_counter()
for _ in range(20):
    legacy_update(e_old.models, DT_PERF)
ms_old = (time.perf_counter() - t0) / 20 * 1000.0
print('     500 动画物体: 旧逐物体 %.3f ms / 新批量 %.3f ms (%.1fx)'
      % (ms_old, ms_new, ms_old / ms_new if ms_new > 0 else 0.0))
check('② 500 动画物体 ≤ 2.0 ms/逻辑帧 (旧实现 12.7ms 量级)', ms_new <= 2.0,
      'new=%.3f ms' % ms_new)
check('② 批量至少快 5x', ms_new * 5.0 <= ms_old, '%.2fx' % (ms_old / ms_new))

# ============================================================================
print('---- ③ 时间语义 / 播放控制 ----')
# ============================================================================
once = E.AnimationClip([
    {'time': 0.0, 'position': (0.0, 0.0, 0.0), 'rotation': (0.0, 0.0, 0.0), 'scale': (1.0, 1.0, 1.0)},
    {'time': 0.5, 'position': (0.0, 5.0, 0.0), 'rotation': (0.0, 0.0, 0.0), 'scale': (1.0, 1.0, 1.0)},
    {'time': 1.0, 'position': (0.0, 10.0, 0.0), 'rotation': (0.0, 0.0, 0.0), 'scale': (1.0, 1.0, 1.0)}],
    loop_mode='once')
e4 = make_engine()
m4, an4 = add_anim_obj(e4, once)
e4.update_animations(1.0)                       # 恰好 t == duration
check('③ once: t==duration 停在末帧 (旧实现倒回第 0 帧)',
      same_bits(m4.position.y, 10.0) and same_bits(an4.time, 1.0) and an4.playing is False,
      'y=%r time=%r playing=%r' % (m4.position.y, an4.time, an4.playing))

e5 = make_engine()
m5, an5 = add_anim_obj(e5, once)
e5.update_animations(0.6)
e5.update_animations(0.6)                       # 两次跨过末帧
check('③ once: 大 dt 跨末帧停在末帧 (旧实现回绕到中间相位)',
      same_bits(m5.position.y, 10.0) and an5.playing is False,
      'y=%r time=%r' % (m5.position.y, an5.time))

e6 = make_engine()
loop2 = E.AnimationClip([
    {'time': 0.0, 'position': (0.0, 0.0, 0.0), 'rotation': (0.0, 0.0, 0.0), 'scale': (1.0, 1.0, 1.0)},
    {'time': 1.0, 'position': (0.0, 10.0, 0.0), 'rotation': (0.0, 0.0, 0.0), 'scale': (1.0, 1.0, 1.0)}],
    loop_mode='loop')
m6, an6 = add_anim_obj(e6, loop2)
e6.update_animations(3.6)
check('③ loop: 跨 3 个周期后 time 规范化到 [0,dur)',
      0.0 <= an6.time < 1.0 and abs(an6.time - 0.6) < 1e-9, 'time=%r' % an6.time)
check('③ loop: 相位正确 (y=6.0)', abs(m6.position.y - 6.0) < 1e-9, 'y=%r' % m6.position.y)

ping = E.AnimationClip([
    {'time': 0.0, 'position': (0.0, 0.0, 0.0), 'rotation': (0.0, 0.0, 0.0), 'scale': (1.0, 1.0, 1.0)},
    {'time': 1.0, 'position': (0.0, 10.0, 0.0), 'rotation': (0.0, 0.0, 0.0), 'scale': (1.0, 1.0, 1.0)}],
    loop_mode='pingpong')
e7 = make_engine()
m7, an7 = add_anim_obj(e7, ping)
e7.update_animations(1.5)
check('③ pingpong: 1.5s -> 折返 0.5s (y=5.0)',
      abs(an7.time - 0.5) < 1e-9 and abs(m7.position.y - 5.0) < 1e-9,
      'time=%r y=%r' % (an7.time, m7.position.y))
e8 = make_engine()
m8, an8 = add_anim_obj(e8, E.AnimationClip(ping.frames, loop_mode='pingpong'))
e8.update_animations(1.0)                       # 折返峰值 t==dur = 末帧
check('③ pingpong: 端点 t==dur 用末帧 (y=10)',
      same_bits(m8.position.y, 10.0) and same_bits(an8.time, 1.0),
      'y=%r time=%r' % (m8.position.y, an8.time))
e8b = make_engine()
m8b, an8b = add_anim_obj(e8b, E.AnimationClip(ping.frames, loop_mode='pingpong'))
e8b.update_animations(2.0)                      # 整周期 -> 回起点
check('③ pingpong: 整周期 t==2*dur 回到起点 (y=0)',
      same_bits(m8b.position.y, 0.0) and same_bits(an8b.time, 0.0),
      'y=%r time=%r' % (m8b.position.y, an8b.time))

# 组件级: 每片段循环模式覆盖组件 loop
e9 = make_engine()
m9, an9 = add_anim_obj(e9, E.AnimationClip(loop2.frames, loop_mode='once'), loop=True)
e9.update_animations(1.2)
check('③ 每片段 loop_mode 覆盖组件 loop (once 生效)',
      an9.playing is False and same_bits(m9.position.y, 10.0), 'y=%r' % m9.position.y)

# 变速: 2x 一帧 == 1x 两帧 (相位)
e10 = make_engine()
m10, an10 = add_anim_obj(e10, E.AnimationClip(loop2.frames, loop_mode='loop'))
an10.set_speed(2.0)
e10.update_animations(0.25)
e11 = make_engine()
m11, an11 = add_anim_obj(e11, E.AnimationClip(loop2.frames, loop_mode='loop'))
e11.update_animations(0.25)
e11.update_animations(0.25)
check('③ 变速 2x (一帧 0.25s) 与 1x (两帧) 相位一致',
      same_bits(an10.time, an11.time) and same_bits(m10.position.y, m11.position.y),
      '%.17g vs %.17g' % (an10.time, an11.time))
try:
    an10.set_speed(float('nan'))
    bad_speed = False
except ValueError:
    bad_speed = True
check('③ 非法 speed (nan) 被拒', bad_speed)
check('③ speed 重置回 1.0', an10.set_speed(1.0) == 1.0)

# seek
e12 = make_engine()
m12, an12 = add_anim_obj(e12, E.AnimationClip(loop2.frames, loop_mode='loop'))
check('③ seek(3.4) loop -> 0.4', abs(an12.seek(3.4) - 0.4) < 1e-9, str(an12.time))
e13 = make_engine()
m13, an13 = add_anim_obj(e13, once, name='c', loop=False)
check('③ seek(9) once -> 夹到 duration', same_bits(an13.seek(9.0), 1.0))
check('③ seek 不改变 playing', an13.playing is True)

# ============================================================================
print('---- ④ 序列化 v2 + undo 值隔离 ----')
# ============================================================================
e14 = make_engine()
clip_v2 = E.AnimationClip(loop2.frames, loop_mode='pingpong')
m14, an14 = add_anim_obj(e14, clip_v2, loop=True)
an14.set_speed(1.5)
an14.time = 0.37
d = S._emit_object(m14)
check('④ 场景字典不含 time/playing (只作预览态, 不落盘)',
      'time' not in d['animator'] and 'playing' not in d['animator'],
      str(sorted(d['animator'].keys())))
check('④ 场景字典保留 speed', abs(d['animator'].get('speed', 0.0) - 1.5) < 1e-12,
      str(d['animator'].get('speed')))
check('④ 场景字典保留每片段 loop_mode',
      d['animator'].get('clip_meta', {}).get('c', {}).get('loop_mode') == 'pingpong',
      str(d['animator'].get('clip_meta')))

e15 = make_engine()
m15, _ = S._apply_object(e15, d)
check('④ 反序列化: speed/loop_mode 还原',
      abs(m15.animator.speed - 1.5) < 1e-12
      and m15.animator.clips['c'].loop_mode == 'pingpong')
check('④ 反序列化: 运行态清零 (time=0/playing=False)',
      m15.animator.time == 0.0 and m15.animator.playing is False)

# 旧文件 (无 speed / clip_meta) 兼容
old_dict = {'name': 'old', 'type': 'cube', 'params': {'size': 1.0},
            'position': [0, 0, 0], 'rotation': [0, 0, 0], 'scale': [1, 1, 1],
            'color': '#88CC88', 'saturation': 1.0, 'visible': True,
            'collider': {'shape': 'box', 'enabled': True},
            'animator': {'current': 'c', 'loop': True,
                         'clips': {'c': [{'time': 0.0, 'position': (1, 2, 3)}]}}}
e16 = make_engine()
m16, _ = S._apply_object(e16, old_dict)
check('④ 旧文件 (无 speed/clip_meta) 兼容: speed=1.0 & loop_mode=None',
      m16.animator is not None and m16.animator.speed == 1.0
      and m16.animator.clips['c'].loop_mode is None)

# undo 值隔离
e17 = make_engine()
m17, an17 = add_anim_obj(e17, full_clip())
snap = U.snapshot(m17)
check('④ 快照与模型不共享 clips 字典', snap['animator'][0] is not m17.animator.clips)
check('④ 快照与模型不共享 clip 对象',
      snap['animator'][0]['c'] is not m17.animator.clips['c'])
snap['animator'][0]['c'].frames[0]['position'] = (99.0, 99.0, 99.0)
check('④ 改快照不污染模型',
      tuple(m17.animator.clips['c'].frames[0]['position']) != (99.0, 99.0, 99.0),
      str(m17.animator.clips['c'].frames[0]['position']))
m17.animator.clips['c'].frames[1]['position'] = (77.0, 77.0, 77.0)
check('④ 改模型不污染快照',
      tuple(snap['animator'][0]['c'].frames[1]['position']) != (77.0, 77.0, 77.0),
      str(snap['animator'][0]['c'].frames[1]['position']))
# 关键帧编辑可撤销
e18 = make_engine()
m18, _ = add_anim_obj(e18, full_clip())
snap18 = U.snapshot(m18)
before = [tuple(f['position']) for f in m18.animator.clips['c'].frames]
m18.animator.clips['c'].frames[0]['position'] = (5.0, 6.0, 7.0)
U.apply_snapshot(m18, snap18)
after = [tuple(f['position']) for f in m18.animator.clips['c'].frames]
check('④ 关键帧编辑可撤销 (撤销后帧值复原)', before == after, '%r vs %r' % (before, after))
check('④ 撤销后快照仍独立', m18.animator.clips is not snap18['animator'][0])
check('④ 撤销清运行态 (time=0/playing=False)',
      m18.animator.time == 0.0 and m18.animator.playing is False)
check('④ 撤销保留 speed', m18.animator.speed == 1.0)

# 快照按"值"相等: 未改动时两次快照必须相等 (否则 commit_model 会把每次编辑
# 都当成"改了" -> 撤销栈被空操作塞满)
e18b = make_engine()
m18b, _ = add_anim_obj(e18b, full_clip())
s_a = U.snapshot(m18b)
s_b = U.snapshot(m18b)
check('④ 未改动时两次快照相等 (空撤销不产生)', s_a == s_b)
m18b.animator.set_speed(2.0)
check('④ 变速后快照不等 (会被记入撤销)', U.snapshot(m18b) != s_a)
m18b.animator.set_speed(1.0)
check('④ 变速改回后快照又相等', U.snapshot(m18b) == s_a)
m18b.animator.clips['c'].loop_mode = 'once'
check('④ loop_mode 改动使快照不等', U.snapshot(m18b) != s_a)

# ============================================================================
print('---- ⑤ 写者优先级 D6 + 管线一致性 ----')
# ============================================================================
C.reset_anim_warn()
e19 = make_engine()
m_static, an_static = add_anim_obj(e19, E.AnimationClip(once.frames, loop_mode='loop'))
m_kin, an_kin = add_anim_obj(e19, E.AnimationClip(once.frames, loop_mode='loop'))
m_kin.rigidbody = E.RigidbodyComponent()
m_kin.rigidbody.is_kinematic = True
m_dyn, an_dyn = add_anim_obj(e19, E.AnimationClip(once.frames, loop_mode='loop'))
m_dyn.rigidbody = E.RigidbodyComponent()
m_dyn.rigidbody.is_kinematic = False
buf = io.StringIO()
with contextlib.redirect_stdout(buf):
    stats = e19.update_animations(0.5)
out = buf.getvalue()
check('⑤ 静态体被动画驱动', abs(m_static.position.y - 5.0) < 1e-9, 'y=%r' % m_static.position.y)
check('⑤ kinematic 体被动画驱动', abs(m_kin.position.y - 5.0) < 1e-9, 'y=%r' % m_kin.position.y)
check('⑤ 动态刚体被跳过 (位姿不动)', m_dyn.position == m_dyn.transform._position
      and tuple(m_dyn.position) == (0.0, 0.0, 0.0), str(tuple(m_dyn.position)))
check('⑤ 动态刚体 time 不推进 (整条动画不跑)', an_dyn.time == 0.0, 'time=%r' % an_dyn.time)
check('⑤ stats.blocked_dynamic 计数', stats.get('blocked_dynamic') == 1, str(stats))
check('⑤ 一次性告警 (只打一条)', out.count('动画不驱动动态刚体') == 1, out.strip()[:120])
buf2 = io.StringIO()
with contextlib.redirect_stdout(buf2):
    e19.update_animations(0.5)
check('⑤ 第二次不再告警', '动画不驱动动态刚体' not in buf2.getvalue(), buf2.getvalue()[:80])


class _FakeClock:
    sub_dt = 1.0 / 90.0
    sub_steps = 3


class _FakePipe:
    _degraded = False

    def wait_pending(self):
        return None


def make_logic_engine(with_pipe):
    e = make_engine()
    e._clock = _FakeClock()
    e._phys_bridge = object()
    e._pipe_disabled = False
    e._phys_pipe = _FakePipe() if with_pipe else None
    e.gravity = -9.8
    e.is_playing = False            # 跳过碰撞事件派发
    e._prep_pairs = None
    e._disp_gen = 0
    e._logic_gen = 0
    e._interp = None
    e._soa_snap = None
    e._prof_t0 = lambda: 0.0
    e._prof_add = lambda *a: None
    e._profile = lambda name, fn: fn()
    e._dispatch_fixed_update = lambda dt: None
    e._run_scripts = lambda dt: None
    e.update_audio = lambda dt: None
    e._logic_prep = lambda dt: None
    e._pipe_post = lambda pipe, sdt, g: None
    e._physics_frame = lambda dt: None
    return e


def scene_with_three(with_pipe):
    e = make_logic_engine(with_pipe)
    ms, _ = add_anim_obj(e, E.AnimationClip(once.frames, loop_mode='loop'))
    mk, _ = add_anim_obj(e, E.AnimationClip(once.frames, loop_mode='loop'))
    mk.rigidbody = E.RigidbodyComponent()
    mk.rigidbody.is_kinematic = True
    md, _ = add_anim_obj(e, E.AnimationClip(once.frames, loop_mode='loop'))
    md.rigidbody = E.RigidbodyComponent()
    md.rigidbody.is_kinematic = False
    return e, (ms, mk, md)


ep, objs_pipe = scene_with_three(True)
es, objs_ser = scene_with_three(False)
for _ in range(10):
    ep._logic_frame(1.0 / 30.0)
    es._logic_frame(1.0 / 30.0)
same = all(tuple(a.position) == tuple(b.position) and a.rotation == b.rotation
           for a, b in zip(objs_pipe, objs_ser))
check('⑤ 物理管线 开/关 两种配置 10 帧后位姿一致 (旧实现胜负相反)', same,
      'pipe=%r serial=%r' % ([tuple(o.position) for o in objs_pipe],
                             [tuple(o.position) for o in objs_ser]))
check('⑤ 管线路径动画确实推进 (静态体 y>0)', objs_pipe[0].position.y > 0.0,
      'y=%r' % objs_pipe[0].position.y)

# ---- 逃生门 (render 的 NO_SPLIT 分支) 段次序 + 与分离路径逐位一致 ----
import loom_render as LR


class _EscapeHost:
    """只承担 _escape_door_step 需要的 5 个口子 (无 GL 上下文)."""

    def __init__(self):
        self.models = []
        self.calls = []

    def _run_scripts(self, dt):
        self.calls.append('scripts')

    def update_animations(self, dt):
        self.calls.append('animations')
        LFC.FrameComponentMixin.update_animations(self, dt)

    def update_physics(self, dt, events=False):
        self.calls.append('physics')

    def update_audio(self, dt):
        self.calls.append('audio')

    def _profile(self, name, fn):
        return fn()


host = _EscapeHost()
_src = make_engine()
add_anim_obj(_src, E.AnimationClip(once.frames, loop_mode='loop'))
host.models = _src.models
LR.RenderMixin._escape_door_step(host, 1.0 / 30.0)
check('⑤ 逃生门段次序 = 脚本→动画→物理→音频 (与分离路径对齐)',
      host.calls == ['scripts', 'animations', 'physics', 'audio'], str(host.calls))

host2 = _EscapeHost()
_src2 = make_engine()
me, _ = add_anim_obj(_src2, E.AnimationClip(once.frames, loop_mode='loop'))
host2.models = _src2.models
split_eng = make_logic_engine(False)
m_split, _ = add_anim_obj(split_eng, E.AnimationClip(once.frames, loop_mode='loop'))
for _ in range(10):
    LR.RenderMixin._escape_door_step(host2, 1.0 / 30.0)
    split_eng._logic_frame(1.0 / 30.0)
check('⑤ 逃生门 vs 分离路径 10 帧后位姿逐位一致',
      tuple(me.position) == tuple(m_split.position)
      and me.rotation == m_split.rotation and me.scale == m_split.scale,
      'escape=%r split=%r' % (tuple(me.position), tuple(m_split.position)))

# ============================================================================
print('---- ⑥ 场景版本闸门 (D7: min_engine_version) ----')
# ============================================================================
e20 = make_engine()
add_anim_obj(e20, full_clip())
e20.cameras = []            # scene_to_dict 需要的场景相机段
e20.active_camera = None
e20.ui = None
d20 = S.scene_to_dict(e20)
check('⑥ 场景写出 min_engine_version (= 当前引擎版本)',
      d20.get('min_engine_version') == S.ENGINE_VERSION,
      '%r vs %r' % (d20.get('min_engine_version'), S.ENGINE_VERSION))
check('⑥ 未抬 SCENE_VERSION (仍是 11)', S.SCENE_VERSION == 11 and d20['version'] == 11,
      'version=%r' % (d20.get('version'),))

# 旧场景 (无该字段) -> 照常加载 (向后兼容)
old_ok = True
try:
    S.migrate({'version': 11, 'objects': []})
    S.scene_from_dict(e20, dict(d20, min_engine_version=None))
except Exception as exc:                     # noqa: BLE001
    old_ok = False
    print('    旧场景加载异常:', exc)
check('⑥ 旧场景 (无 min_engine_version) 可加载', old_ok)

# 同版本 / 更低要求 -> 加载
same_ok = True
try:
    S.migrate({'version': 11, 'min_engine_version': S.ENGINE_VERSION, 'objects': []})
    S.check_engine_version({'min_engine_version': '0.0.1'})
except Exception as exc:                     # noqa: BLE001
    same_ok = False
    print('    同版本加载异常:', exc)
check('⑥ 同版本 / 更低要求 可加载', same_ok)

# 更高要求 -> 明确拒绝, 原因里带"要求版本 + 当前版本"
rejected = False
reason = ''
try:
    S.migrate({'version': 11, 'min_engine_version': '99.0.0', 'objects': []})
except S.SceneVersionError as exc:
    rejected = True
    reason = str(exc)
check('⑥ 更高版本要求 -> 抛 SceneVersionError 拒绝', rejected, reason[:80])
check('⑥ 拒绝原因同时给出要求版本与当前版本',
      '99.0.0' in reason and S.ENGINE_VERSION in reason, reason[:120])

# 旧引擎读新场景 (模拟: 把"当前引擎版本"降级后检查 beta6 写出的场景)
rejected_old = False
try:
    S.check_engine_version({'min_engine_version': S.ENGINE_VERSION},
                           engine_version='0.1.0.beta5')
except S.SceneVersionError:
    rejected_old = True
check('⑥ 旧引擎 (beta5) 读 beta6 场景 -> 拒绝', rejected_old)
check('⑥ 同版本引擎读同一场景 -> 通过',
      S.check_engine_version({'min_engine_version': S.ENGINE_VERSION},
                             engine_version=S.ENGINE_VERSION) is True)

# 整个加载链 (scene_from_dict) 也必须被拦住 (播放器/驱动同一入口)
rejected_chain = False
try:
    e21 = make_engine()
    S.scene_from_dict(e21, {'version': 11, 'min_engine_version': '99.0.0',
                            'objects': []})
except S.SceneVersionError:
    rejected_chain = True
check('⑥ scene_from_dict 加载链被拒绝 (不静默加载)', rejected_chain)

# 版本比较语义: beta 递增, 同号正式版 > beta
check('⑥ 版本比较: beta6 < beta7 < beta10 < 0.1.0',
      S.version_lt('0.1.0.beta6', '0.1.0.beta7')
      and S.version_lt('0.1.0.beta7', '0.1.0.beta10')
      and S.version_lt('0.1.0.beta10', '0.1.0'))
check('⑥ 版本比较: 正式版 0.1.0 不 < beta6',
      S.version_lt('0.1.0', '0.1.0.beta6') is False)
check('⑥ 无法解析的版本号不拦 (只告警)', S.version_lt('abc', '99.0.0') is False)

print()
print('总结果:', 'ALL PASS ✅' if ok else '有 FAIL ❌')
sys.exit(0 if ok else 1)
