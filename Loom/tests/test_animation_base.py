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
import json
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
# R6 F-02: 门禁口径与实测/承诺统一 —— 设计目标是 ≤1.0ms/逻辑帧，实测
# 1.42-1.69ms **未达成**（剩余成本=两个不可向量化的逐物体 Python 循环
# ≈0.80ms + GC ≈0.24ms；要真到 ≤1ms 需 animator 状态 SoA + 活跃集缓存，
# 属批次2 重构）。因此这里只做"稳定门禁"2.0ms + 相对旧实现 ≥5x 的双重断言，
# 不再用 2.0ms 冒充 1.0ms 的承诺。
check('② 500 动画物体 ≤ 2.0ms 稳定门禁 (实测≈1.5ms; ≤1.0ms 目标未达成, 见上)',
      ms_new <= 2.0, 'new=%.3f ms' % ms_new)
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
# R5-02 P-06: physics_available 由宿主传入; 桩里显式声明"物理桥存在"，
# 才能测到 D6 (物理可用 -> 动态刚体跳过) 这一支; 无桥的回退支见 ⑦。
e19._phys_bridge = object()
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
    e._pipe_post = lambda pipe, sdt, g, pose=None: None   # D1: _pipe_post 增第 4 参 (pose)
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
# C1 自身不抬版本号; 版本号由后续批次决定 (R02 材质真相源已到 12) —— 只断言
# "写出的 version 与 SCENE_VERSION 同源", 不钉死具体数字。
check('⑥ 场景 version 与 SCENE_VERSION 同源 (C1 未自行抬版)',
      d20['version'] == S.SCENE_VERSION and S.SCENE_VERSION >= 11,
      'version=%r SCENE_VERSION=%r' % (d20.get('version'), S.SCENE_VERSION))

# 旧场景 (无该字段) -> 照常加载 (向后兼容)
old_ok = True
try:
    S.migrate({'version': 11, 'objects': []})
    _old_scene = dict(d20)
    _old_scene.pop('min_engine_version', None)   # U-02=B: 字段缺失=旧场景;
    S.scene_from_dict(e20, _old_scene)            # 字段存在但为 None 现在算非法值
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
check('⑥ version_lt 对不可解析返回 False (低层判定; 要求侧由闸门拒绝, 见 ⑨)',
      S.version_lt('abc', '99.0.0') is False)

# ============================================================================
print('---- ⑦ R5-02 审查回归 (P-01/P-02/P-04/P-05/P-06/P-07) ----')
# ============================================================================
import tempfile as _tf7

# ---- P-01 (P0): 常量通道必须写 Point3D, 不能写 plain tuple ----
# 触发面: 轮子/风扇 (位置恒定 (2,5,3) + 只转 Y) / 平移平台 (旋转恒定)。
const_pos_clip = E.AnimationClip([
    {'time': 0.0, 'position': (2.0, 5.0, 3.0), 'rotation': (0.0, 0.0, 0.0),
     'scale': (1.0, 1.0, 1.0)},
    {'time': 1.0, 'position': (2.0, 5.0, 3.0), 'rotation': (0.0, 1.5, 0.0),
     'scale': (1.0, 1.0, 1.0)}])
e40 = make_engine()
m40, an40 = add_anim_obj(e40, const_pos_clip)
for _ in range(10):
    e40.update_animations(0.1)
check('⑦ P-01 常量 position 通道写回 Point3D',
      isinstance(m40.transform._position, E.Point3D),
      type(m40.transform._position).__name__)
check('⑦ P-01 m.position.x/.y/.z 可读 (不 AttributeError)',
      abs(m40.position.x - 2.0) < 1e-12 and abs(m40.position.y - 5.0) < 1e-12
      and abs(m40.position.z - 3.0) < 1e-12, str(tuple(m40.position)))
ok40 = True
try:
    snap40 = U.snapshot(m40)            # 旧实现在这里 AttributeError
    d40 = S._emit_object(m40)           # 存盘路径同断
except Exception as exc:                # noqa: BLE001
    ok40 = False
    snap40, d40 = None, None
    print('    P-01 snapshot/存盘异常:', exc)
check('⑦ P-01 undo.snapshot + sceneio 存盘不崩', ok40)
check('⑦ P-01 存盘 position 正确', ok40 and d40['position'] == [2.0, 5.0, 3.0],
      str(d40.get('position') if ok40 else None))

const_rot_clip = E.AnimationClip([
    {'time': 0.0, 'position': (0.0, 0.0, 0.0), 'rotation': (0.1, 0.2, 0.3),
     'scale': (1.0, 1.0, 1.0)},
    {'time': 1.0, 'position': (0.0, 2.0, 0.0), 'rotation': (0.1, 0.2, 0.3),
     'scale': (1.0, 1.0, 1.0)}])
e41 = make_engine()
m41, an41 = add_anim_obj(e41, const_rot_clip)
for _ in range(10):
    e41.update_animations(0.1)
check('⑦ P-01 常量 rotation 通道写回 Point3D',
      isinstance(m41.transform._rotation, E.Point3D),
      type(m41.transform._rotation).__name__)
check('⑦ P-01 m.rotation.x/.y/.z 可读',
      abs(m41.rotation.x - 0.1) < 1e-12 and abs(m41.rotation.z - 0.3) < 1e-12,
      str(tuple(m41.rotation)))
ok41 = True
try:
    snap41 = U.snapshot(m41)
except Exception as exc:                # noqa: BLE001
    ok41 = False
    snap41 = None
    print('    P-01 常量 rotation snapshot 异常:', exc)
check('⑦ P-01 常量 rotation 下 undo.snapshot 不崩', ok41)

# ---- P-02 (P1): once + 负相位 -> 夹到 [0,dur] 并停播; 批量==逐物体 ----
neg_once = E.AnimationClip([
    {'time': 0.0, 'position': (0.0, 0.0, 0.0), 'rotation': (0.0, 0.0, 0.0),
     'scale': (1.0, 1.0, 1.0)},
    {'time': 1.0, 'position': (0.0, 10.0, 0.0), 'rotation': (0.0, 0.0, 0.0),
     'scale': (1.0, 1.0, 1.0)}], loop_mode='once')
e42 = make_engine()
m42, an42 = add_anim_obj(e42, E.AnimationClip(neg_once.frames, loop_mode='once'))
an42.time = 0.2
an42.set_speed(-1.0)
e42.update_animations(0.5)              # t = 0.2 - 0.5 = -0.3 -> 夹到 0
check('⑦ P-02 once 倒放到 0 停播 (playing=False, time=0)',
      an42.playing is False and an42.time == 0.0,
      'time=%r playing=%r' % (an42.time, an42.playing))
check('⑦ P-02 停在首帧 (与 sample(0) 同位姿)',
      same_bits(m42.position.y, 0.0), 'y=%r' % m42.position.y)
# 批量(快路径) vs 逐物体(慢路径, 缺通道) 在负相位下逐位一致
e43 = make_engine()
mf43, anf43 = add_anim_obj(e43, E.AnimationClip(neg_once.frames, loop_mode='once'),
                           name='f')
ms43, ans43 = add_anim_obj(e43, E.AnimationClip([
    {'time': 0.0, 'position': (0.0, 0.0, 0.0)},
    {'time': 1.0, 'position': (0.0, 10.0, 0.0)}], loop_mode='once'), name='s')
anf43.time = ans43.time = 0.2
anf43.set_speed(-1.0)
ans43.set_speed(-1.0)
for _ in range(10):
    e43.update_animations(0.1)
check('⑦ P-02 负速下 批量/逐物体 位姿逐位一致',
      all(same_bits(a, b) for a, b in zip(mf43.position, ms43.position))
      and anf43.playing is ans43.playing is False,
      '%r vs %r' % (tuple(mf43.position), tuple(ms43.position)))

# ---- P-05 (P2): 换 frames 列表后批量必须看到新帧 (与 sample() 同源失效) ----
stale_clip = E.AnimationClip([
    {'time': 0.0, 'position': (0.0, 0.0, 0.0), 'rotation': (0.0, 0.0, 0.0),
     'scale': (1.0, 1.0, 1.0)},
    {'time': 1.0, 'position': (0.0, 10.0, 0.0), 'rotation': (0.0, 0.0, 0.0),
     'scale': (1.0, 1.0, 1.0)}], loop_mode='loop')
e44 = make_engine()
m44, an44 = add_anim_obj(e44, stale_clip)
e44.update_animations(0.0)              # 建立批量缓存
stale_clip.frames = [                   # 脚本整体换帧 (长度同, 列表换了)
    {'time': 0.0, 'position': (0.0, 0.0, 0.0), 'rotation': (0.0, 0.0, 0.0),
     'scale': (1.0, 1.0, 1.0)},
    {'time': 1.0, 'position': (0.0, 100.0, 0.0), 'rotation': (0.0, 0.0, 0.0),
     'scale': (1.0, 1.0, 1.0)}]
an44.time = 0.0
an44.playing = True
e44.update_animations(0.25)
ref44 = stale_clip.sample(0.25)['position'][1]
check('⑦ P-05 换帧后批量结果来自新帧 (y=25, 旧缓存 y=2.5)',
      same_bits(m44.position.y, 25.0) and same_bits(m44.position.y, ref44),
      'y=%r ref=%r' % (m44.position.y, ref44))

# ---- P-04 (P2): prefab 也过版本闸 + 旧 prefab 向后兼容 ----
e45 = make_engine()
m45, _ = add_anim_obj(e45, full_clip())
m45.animator.set_speed(2.0)                 # 让 prefab 真的带 speed/clip_meta
m45.animator.clips['c'].loop_mode = 'once'
pd45 = S.prefab_to_dict(m45)
check('⑦ P-04 prefab 写出 min_engine_version',
      pd45.get('min_engine_version') == S.ENGINE_VERSION,
      str(pd45.get('min_engine_version')))
check('⑦ P-04 prefab 体内 animator 带 speed/clip_meta (闸门动机成立)',
      'speed' in (pd45['objects'][0].get('animator') or {})
      or 'clip_meta' in (pd45['objects'][0].get('animator') or {}),
      str(sorted((pd45['objects'][0].get('animator') or {}).keys())))
_tf7_dir = _tf7.mkdtemp(prefix='loom_pf7_')
_p_old = os.path.join(_tf7_dir, 'old.prefab')
with open(_p_old, 'w', encoding='utf-8') as _f:
    json.dump({'version': 1, 'prefab': {'guid': 'g0', 'name': 'x'},
               'objects': []}, _f)
ok45 = True
try:
    S.load_prefab(_p_old)
except Exception as exc:                # noqa: BLE001
    ok45 = False
    print('    旧 prefab 加载异常:', exc)
check('⑦ P-04 旧 prefab (无 min_engine_version) 可加载', ok45)
_p_new = os.path.join(_tf7_dir, 'new.prefab')
with open(_p_new, 'w', encoding='utf-8') as _f:
    json.dump({'version': 1, 'min_engine_version': '99.0.0',
               'prefab': {'guid': 'g1', 'name': 'x'}, 'objects': []}, _f)
rej45 = False
try:
    S.load_prefab(_p_new)
except S.SceneVersionError:
    rej45 = True
check('⑦ P-04 更高版本 prefab 被 load_prefab 拒绝', rej45)
rej45b = False
try:
    S.instantiate_prefab(make_engine(),
                         {'min_engine_version': '99.0.0', 'objects': []})
except S.SceneVersionError:
    rej45b = True
check('⑦ P-04 instantiate_prefab 入口同样过闸 (undo 重放)', rej45b)

# ---- P-06 (P2): 物理不可用 -> 回退动画驱动 (不永久冻结) ----
C.reset_anim_warn()
e46 = make_engine()
m46 = e46.add_model(create_cube(1.0), E.Point3D(0, 0, 0), E.Point3D(0, 0, 0))
an46 = m46.add_animator(clips={'c': E.AnimationClip(once.frames, loop_mode='loop')},
                        current='c')
an46.playing = True
m46.rigidbody = E.RigidbodyComponent()
m46.rigidbody.is_kinematic = False
_buf46 = io.StringIO()
with contextlib.redirect_stdout(_buf46):
    st46 = C.evaluate_animations(e46.models, 0.25, physics_available=False)
check('⑦ P-06 物理不可用时动态刚体由动画驱动',
      abs(m46.position.y - 2.5) < 1e-9, 'y=%r' % m46.position.y)
check('⑦ P-06 stats.fallback_dynamic 计数', st46.get('fallback_dynamic') == 1,
      str(st46))
check('⑦ P-06 一次性提示 (物理不可用)',
      '物理后端不可用' in _buf46.getvalue(), _buf46.getvalue().strip()[:100])
# 引擎桩没有物理桥 -> update_animations 自动走回退 (而不是冻结)
e47 = make_engine()
m47 = e47.add_model(create_cube(1.0), E.Point3D(0, 0, 0), E.Point3D(0, 0, 0))
an47 = m47.add_animator(clips={'c': E.AnimationClip(once.frames, loop_mode='loop')},
                        current='c')
an47.playing = True
m47.rigidbody = E.RigidbodyComponent()
e47.update_animations(0.25)
check('⑦ P-06 无桥引擎走回退 (位姿不冻结)', m47.position.y > 0.0,
      'y=%r' % m47.position.y)
# 对照: 有桥 -> D6, 仍然跳过
e47._phys_bridge = object()
m47.position = E.Point3D(0, 0, 0)
an47.time = 0.0
an47.playing = True
e47.update_animations(0.25)
check('⑦ P-06 有桥时回到 D6 (动态刚体跳过)', m47.position.y == 0.0,
      'y=%r' % m47.position.y)

# ---- P-07 (P2/P3): ndarray 帧的深拷 + 可比较 ----
arr_clip = E.AnimationClip([
    {'time': 0.0, 'position': np.array([1.0, 2.0, 3.0]),
     'rotation': (0.0, 0.0, 0.0), 'scale': (1.0, 1.0, 1.0)},
    {'time': 1.0, 'position': np.array([4.0, 5.0, 6.0]),
     'rotation': (0.0, 0.0, 0.0), 'scale': (1.0, 1.0, 1.0)}])
e48 = make_engine()
m48, _ = add_anim_obj(e48, arr_clip)
snap48 = U.snapshot(m48)
copy48 = snap48['animator'][0]['c']
check('⑦ P-07 copy() 不共享 numpy 数组',
      copy48.frames[0]['position'] is not arr_clip.frames[0]['position'])
arr_clip.frames[0]['position'][0] = 99.0        # 原地改模型数组
check('⑦ P-07 改模型数组不污染快照',
      abs(float(copy48.frames[0]['position'][0]) - 1.0) < 1e-12,
      str(copy48.frames[0]['position']))
copy48.frames[1]['position'][1] = 77.0          # 原地改快照数组
check('⑦ P-07 改快照数组不污染模型',
      abs(float(arr_clip.frames[1]['position'][1]) - 5.0) < 1e-12,
      str(arr_clip.frames[1]['position']))
_a1 = E.AnimationClip([{'time': 0.0, 'position': np.array([1.0, 2.0, 3.0])}])
_a2 = E.AnimationClip([{'time': 0.0, 'position': np.array([1.0, 2.0, 3.0])}])
_eq_err = ''
try:
    _eq_ok = (_a1 == _a2) is True
except Exception as exc:                # noqa: BLE001
    _eq_ok = False
    _eq_err = repr(exc)
check('⑦ P-07 含 ndarray 的 __eq__ 可比较 (不抛 ValueError)', _eq_ok, _eq_err)
_l1 = E.AnimationClip([{'time': 0.0, 'position': [1.0, 2.0, 3.0]}])
_t1 = E.AnimationClip([{'time': 0.0, 'position': (1.0, 2.0, 3.0)}])
check('⑦ P-07 list/tuple 同值片段相等 (规范键归一)', (_l1 == _t1) is True)
# 非数值 speed (绕过 set_speed) 只降级该物体, 不炸整帧
e49 = make_engine()
m49, an49 = add_anim_obj(e49, full_clip())
an49.speed = [1.0]
ok49 = True
try:
    e49.update_animations(0.1)
except Exception as exc:                # noqa: BLE001
    ok49 = False
    print('    非数值 speed 引发整帧异常:', exc)
check('⑦ P-07 非数值 speed 单物体降级 (不抛整帧, 重置 1.0)',
      ok49 and an49.speed == 1.0, 'speed=%r' % (an49.speed,))

print()

print('---- ⑧ R6 验证回归 (V-04/V-05/V-08/V-09/V-10/V-11/V-12) ----')

# ---- V-04: dur == 0 的 once 与 seek 同构 (夹 0 停播) ----
single_once = E.AnimationClip([{'time': 0.0, 'position': (0.0, 2.0, 0.0)}],
                              loop_mode='once')
e54 = make_engine()
m54, an54 = add_anim_obj(e54, single_once)
an54.set_speed(-1.0)
for _ in range(10):
    e54.update_animations(0.1)
check('⑧ V-04 dur==0 once + 负速 -> time=0 且停播',
      an54.time == 0.0 and an54.playing is False,
      'time=%r playing=%r' % (an54.time, an54.playing))
check('⑧ V-04 与 seek(-1) 口径一致', an54.seek(-1.0) == 0.0, str(an54.time))

# ---- V-05: NaN/inf speed 不再静默冻结 ----
C.reset_anim_warn()
e55 = make_engine()
m55, an55 = add_anim_obj(e55, full_clip())
an55.speed = float('nan')
_buf55 = io.StringIO()
with contextlib.redirect_stdout(_buf55):
    for _ in range(3):
        e55.update_animations(0.1)
check('⑧ V-05 NaN speed -> 降级 1.0 且时间复位 (不冻结)',
      an55.speed == 1.0 and abs(an55.time - 0.3) < 1e-12,
      'speed=%r time=%r' % (an55.speed, an55.time))
check('⑧ V-05 一次性提示', '非法' in _buf55.getvalue(),
      _buf55.getvalue().strip()[:80])
an55.speed = float('inf')
e55.update_animations(0.1)
check('⑧ V-05 inf speed 同样降级', an55.speed == 1.0
      and abs(an55.time - 0.4) < 1e-12, 'time=%r' % an55.time)

# ---- V-08: 回退动画 + legacy 物理 双写者 (60 帧不漂移, 物理仍驱动其它体) ----
C.reset_anim_warn()
_loop2 = [{'time': 0.0, 'position': (0.0, 0.0, 0.0), 'rotation': (0.0, 0.0, 0.0),
           'scale': (1.0, 1.0, 1.0)},
          {'time': 1.0, 'position': (0.0, 6.0, 0.0), 'rotation': (0.0, 0.0, 0.0),
           'scale': (1.0, 1.0, 1.0)}]
e58 = make_engine()                      # 无 _phys_bridge_auto / 无桥 -> 回退
m58a = e58.add_model(create_cube(1.0), E.Point3D(0.0, 0.0, 0.0),
                     E.Point3D(0, 0, 0))
an58 = m58a.add_animator(clips={'c': E.AnimationClip(_loop2, loop_mode='loop')},
                         current='c')
an58.playing = True
m58a.rigidbody = E.RigidbodyComponent()          # 动态 + 重力
m58b = e58.add_model(create_cube(1.0), E.Point3D(50.0, 0.0, 0.0),
                     E.Point3D(0, 0, 0))
m58b.rigidbody = E.RigidbodyComponent()          # 动态 + 无动画 -> 物理驱动
DT8 = 0.1
for _ in range(60):
    e58.update_animations(DT8)
    e58.update_physics(DT8, events=False)
_expect58 = an58.clips['c'].sample(an58.time)['position'][1]
check('⑧ V-08 回退态 60 帧后位姿=动画位姿 (无逐帧漂移)',
      same_bits(m58a.position.y, _expect58),
      'y=%r expect=%r' % (m58a.position.y, _expect58))
check('⑧ V-08 物理仍驱动其它刚体', m58b.position.y < -1.0,
      'y=%r' % m58b.position.y)
check('⑧ V-08 回退体速度被清零 (物理恢复不突跳)',
      m58a.rigidbody.velocity.y == 0.0, str(m58a.rigidbody.velocity))

# ---- V-09: VK 的 physics_available 不再恒真 ----
_drv = SD.SceneDriver.__new__(SD.SceneDriver)
_drv._bridge = None
_drv._bridge_disabled = False
_orig_cv = getattr(SD.physb, 'cv_available', None) if SD.physb is not None else None
_ok59 = True
try:
    if SD.physb is None:
        _ok59 = False
        check('⑧ V-09 VK 判据 (本机 physics_bridge 模块缺失, 跳过对照)', True)
    else:
        SD.physb.cv_available = False
        check('⑧ V-09 VK: culverin 缺失 -> 物理不可用',
              _drv._physics_available() is False)
        SD.physb.cv_available = True
        check('⑧ V-09 VK: culverin 可用 -> 物理可用',
              _drv._physics_available() is True)
        _drv._bridge = object()
        check('⑧ V-09 VK: 桥已建 -> 物理可用',
              _drv._physics_available() is True)
        _drv._bridge_disabled = True
        check('⑧ V-09 VK: 桥被禁 -> 物理不可用',
              _drv._physics_available() is False)
finally:
    if SD.physb is not None:
        SD.physb.cv_available = _orig_cv
    _drv._bridge = None
    _drv._bridge_disabled = False
# 行为面: culverin 缺失时 VK 动态体由动画驱动
if SD.physb is not None:
    _drv2 = SD.SceneDriver.__new__(SD.SceneDriver)
    _drv2._bridge = None
    _drv2._bridge_disabled = False
    _m59 = E.GameObject(create_cube(1.0), E.Point3D(0, 0, 0), E.Point3D(0, 0, 0))
    _a59 = _m59.add_animator(clips={'c': E.AnimationClip(_loop2, loop_mode='loop')},
                             current='c')
    _a59.playing = True
    _m59.rigidbody = E.RigidbodyComponent()
    _drv2.models = [_m59]
    try:
        SD.physb.cv_available = False
        _st59 = SD.SceneDriver._update_animations(_drv2, 0.25)
    finally:
        SD.physb.cv_available = _orig_cv
    check('⑧ V-09 VK culverin 缺失 -> 回退动画驱动',
          _st59.get('fallback_dynamic') == 1 and _m59.position.y > 0.0,
          'stats=%r y=%r' % (_st59, _m59.position.y))

# ---- V-10: LOOM_NO_PHYSICS=1 真开关 ----
C.reset_anim_warn()
os.environ['LOOM_NO_PHYSICS'] = '1'
try:
    e60 = make_engine()
    e60._phys_bridge_auto = True                 # 真引擎声明会建桥
    m60a = e60.add_model(create_cube(1.0), E.Point3D(0, 0, 0), E.Point3D(0, 0, 0))
    a60 = m60a.add_animator(clips={'c': E.AnimationClip(_loop2, loop_mode='loop')},
                            current='c')
    a60.playing = True
    m60a.rigidbody = E.RigidbodyComponent()
    m60b = e60.add_model(create_cube(1.0), E.Point3D(50, 0, 0), E.Point3D(0, 0, 0))
    m60b.rigidbody = E.RigidbodyComponent()      # 动态无动画 -> 应完全不动
    e60.update_animations(0.25)
    e60.update_physics(0.25, events=False)
    check('⑧ V-10 LOOM_NO_PHYSICS=1: 动画回退驱动动态刚体',
          m60a.position.y > 0.0, 'y=%r' % m60a.position.y)
    check('⑧ V-10 LOOM_NO_PHYSICS=1: 物理整体不跑 (其它体不动)',
          m60b.position.y == 0.0, 'y=%r' % m60b.position.y)
finally:
    os.environ.pop('LOOM_NO_PHYSICS', None)
check('⑧ V-10 取消 env 后恢复正常', C.physics_disabled_by_env() is False)

# ---- V-11: 生产判据 (_phys_bridge_auto / _phys_bridge_disabled) ----
C.reset_anim_warn()
e61 = make_engine()
e61._phys_bridge_auto = True                    # 生产实例形态
m61 = e61.add_model(create_cube(1.0), E.Point3D(0, 0, 0), E.Point3D(0, 0, 0))
a61 = m61.add_animator(clips={'c': E.AnimationClip(_loop2, loop_mode='loop')},
                       current='c')
a61.playing = True
m61.rigidbody = E.RigidbodyComponent()
st61 = e61.update_animations(0.25)
check('⑧ V-11 生产判据 (auto=True, 桥未建) -> 首帧按物理可用跳过',
      st61.get('blocked_dynamic') == 1 and m61.position.y == 0.0, str(st61))
e61._phys_bridge_disabled = True                # 桥被禁 -> 真回退
st61b = e61.update_animations(0.25)
check('⑧ V-11 生产判据 (桥被禁) -> 回退动画驱动',
      st61b.get('fallback_dynamic') == 1 and m61.position.y > 0.0,
      'stats=%r y=%r' % (st61b, m61.position.y))

# ---- V-12: 嵌套容器内的 ndarray (copy 深拷 + __eq__ 可比较) ----
_v0 = [np.array([1.0, 2.0]), np.array([3.0])]
_nested = E.AnimationClip([{'time': 0.0, 'extra': _v0}])
_cp12 = _nested.copy()
check('⑧ V-12 list 内嵌 ndarray 深拷',
      _cp12.frames[0]['extra'][0] is not _v0[0])
_v0[0][0] = 99.0
check('⑧ V-12 改源列表内数组不影响 copy',
      abs(float(_cp12.frames[0]['extra'][0][0]) - 1.0) < 1e-12,
      str(_cp12.frames[0]['extra'][0]))
_n1 = E.AnimationClip([{'time': 0.0, 'extra': [np.array([1.0, 2.0])]}])
_n2 = E.AnimationClip([{'time': 0.0, 'extra': [np.array([1.0, 2.0])]}])
_eq12 = ''
try:
    _eq12_ok = (_n1 == _n2) is True
except Exception as exc:                        # noqa: BLE001
    _eq12_ok = False
    _eq12 = repr(exc)
check('⑧ V-12 list 内嵌 ndarray 内容相等 (不抛)', _eq12_ok, _eq12)
_t1 = E.AnimationClip([{'time': 0.0, 'extra': (np.array([1.0]),)}])
_t2 = E.AnimationClip([{'time': 0.0, 'extra': (np.array([1.0]),)}])
check('⑧ V-12 tuple 内嵌 ndarray 内容相等', (_t1 == _t2) is True)
_tcp = _t1.copy()
check('⑧ V-12 tuple 内嵌 ndarray 深拷',
      _tcp.frames[0]['extra'][0] is not _t1.frames[0]['extra'][0])
# undo 快照对嵌套数组的隔离
_nested3 = E.AnimationClip([
    {'time': 0.0, 'position': [np.array([1.0, 2.0, 3.0])],
     'rotation': (0.0, 0.0, 0.0), 'scale': (1.0, 1.0, 1.0)}])
e62 = make_engine()
m62, _ = add_anim_obj(e62, _nested3)
_snap62 = U.snapshot(m62)
_cp62 = _snap62['animator'][0]['c']
check('⑧ V-12 undo 快照深拷嵌套数组',
      _cp62.frames[0]['position'][0] is not _nested3.frames[0]['position'][0])
_nested3.frames[0]['position'][0][0] = 77.0
check('⑧ V-12 改模型嵌套数组不污染快照',
      abs(float(_cp62.frames[0]['position'][0][0]) - 1.0) < 1e-12,
      str(_cp62.frames[0]['position'][0]))

print()
print('---- ⑨ R6 F-02/F-03 (版本解析 fail-open + 回退名单弱引用) ----')

# ---- F-02: '0.1.0-beta6' 可解析; 不可解析的要求侧必须拒绝 (不再 fail-open) ----
check('⑨ F-02 连字符版本可解析 (= 点分版本)',
      S.parse_version('0.1.0-beta6') == S.parse_version('0.1.0.beta6'),
      '%r vs %r' % (S.parse_version('0.1.0-beta6'),
                    S.parse_version('0.1.0.beta6')))
check('⑨ F-02 连字符版本参与比较 (beta5 < beta6)',
      S.version_lt('0.1.0.beta5', '0.1.0-beta6') is True)
_ok92 = True
try:
    S.check_engine_version({'min_engine_version': '0.1.0-beta6'})
except Exception as exc:                        # noqa: BLE001
    _ok92 = False
    print('    连字符版本闸门异常:', exc)
check('⑨ F-02 连字符版本闸门放行 (当前 beta6 >= 要求)', _ok92)
_rej92 = False
try:
    S.check_engine_version({'min_engine_version': 'banana'})
except S.SceneVersionError:
    _rej92 = True
check('⑨ F-02 不可解析的 min_engine_version -> 拒绝 (不再静默 fail-open)',
      _rej92)
_buf92 = io.StringIO()
with contextlib.redirect_stdout(_buf92):
    _r92 = S.check_engine_version({'min_engine_version': '0.1.0.beta6'},
                                  engine_version='weird')
check('⑨ F-02 引擎自身版本不可解析 -> 显式告警后放行 (不静默)',
      _r92 is True and '无法解析' in _buf92.getvalue(),
      _buf92.getvalue().strip()[:100])
check('⑨ F-02 无版本要求的旧场景仍放行',
      S.check_engine_version({'version': 11}) is True)

# ---- U-02=B: 字段存在但类型不对/空串/乱码 -> 一律拒绝 (不静默放行) ----
_bad_cases = [('int', 11), ('list', ['a']), ('bool', True), ('null', None),
              ('空串', ''), ('全空白', '   '), ('乱码串', 'banana')]
_rej_all = True
_msgs_ok = True
for _label, _val in _bad_cases:
    try:
        S.check_engine_version({'min_engine_version': _val})
        _rej_all = False
        check('⑨ U-02 非法值 %s -> 拒绝' % _label, False, repr(_val))
    except S.SceneVersionError as _e:
        _msg = str(_e)
        # 原因必须"可读": 带字段值 + 期望格式 (发布版无 print, 只能靠这条消息)
        if ('期望形如' not in _msg) or (repr(_val) not in _msg and str(_val) not in _msg):
            _msgs_ok = False
            print('    %s 的拒绝原因缺值/格式:', _msg)
check('⑨ U-02 非 str(int/list/bool/null)/空串/乱码 全部被拒绝', _rej_all)
check('⑨ U-02 拒绝原因含 字段值 + 期望格式', _msgs_ok)
check('⑨ U-02 字段缺失 (旧场景) 仍放行',
      S.check_engine_version({'version': 11, 'objects': []}) is True)
_rej_scene = False
try:
    S.scene_from_dict(make_engine(), {'version': 11, 'min_engine_version': 7,
                                      'objects': []})
except S.SceneVersionError:
    _rej_scene = True
check('⑨ U-02 加载链 (scene_from_dict) 对非法类型同样拒绝', _rej_scene)

# ---- F-03: 回退名单用 WeakSet; 删除模型不被强引用; 播放边界清空 ----
import gc
import weakref

C.reset_anim_warn()
e93 = make_engine()
m93 = e93.add_model(create_cube(1.0), E.Point3D(0, 0, 0), E.Point3D(0, 0, 0))
a93 = m93.add_animator(clips={'c': E.AnimationClip(once.frames, loop_mode='loop')},
                       current='c')
a93.playing = True
m93.rigidbody = E.RigidbodyComponent()
e93.update_animations(0.25)
_fb93 = getattr(e93, '_anim_fallback_models', None)
check('⑨ F-03 回退名单是弱引用容器',
      isinstance(_fb93, weakref.WeakSet), type(_fb93).__name__)
check('⑨ F-03 当前含 1 个被回退驱动的物体', len(_fb93) == 1,
      str(len(_fb93) if _fb93 is not None else None))
e93.models.remove(m93)          # 模拟"播放中删除物体"
del m93, a93
gc.collect()
check('⑨ F-03 删除模型后名单不再强引用 (自动释放)', len(_fb93) == 0,
      'len=%d' % len(_fb93))
e94 = make_engine()
m94 = e94.add_model(create_cube(1.0), E.Point3D(0, 0, 0), E.Point3D(0, 0, 0))
a94 = m94.add_animator(clips={'c': E.AnimationClip(once.frames, loop_mode='loop')},
                       current='c')
a94.playing = True
m94.rigidbody = E.RigidbodyComponent()
e94.update_animations(0.25)
e94._clear_anim_fallback()
check('⑨ F-03 _clear_anim_fallback 清空名单 (停播/开播调用)',
      getattr(e94, '_anim_fallback_models', None) == (),
      str(getattr(e94, '_anim_fallback_models', 'missing')))
# 掩码仍生效 (WeakSet -> set 后按对象身份匹配)
e94._anim_fallback_models = weakref.WeakSet([m94])
_y_before94 = m94.position.y
e94.update_physics(0.25, events=False)      # 掩码命中 -> 位姿不动
check('⑨ F-03 物理掩码按对象匹配 (WeakSet 输入不打偏)',
      m94.position.y == _y_before94 and m94.rigidbody.velocity.y == 0.0,
      'y=%r before=%r' % (m94.position.y, _y_before94))

print()
print('总结果:', 'ALL PASS ✅' if ok else '有 FAIL ❌')
sys.exit(0 if ok else 1)
