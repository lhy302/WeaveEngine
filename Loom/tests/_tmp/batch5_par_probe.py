# -*- coding: utf-8 -*-
"""
batch5_par_probe.py — 分离批5 V2 物理行为对拍 (R1/R3 核心闸)

同场景同初态, 两种模式物理步数/步长/dt 序列完全相同 → Jolt 确定性 → 逐位:
  甲 = 旧绑死 (make_engine split=False): 300 渲染帧 × update_physics(1/60)
  乙 = 分离 (logic 30Hz, sub_dt=1/60, N=2): 300 渲染帧 @60FPS
       = 150 逻辑帧 × 2 子步(1/60) = 300 物理步 (同序列!)
断言: 第 k 逻辑帧末全部模型位形 == 旧模式第 2k 渲染帧 (逐位 ==).
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..', '..'))
os.environ['LOOM_NO_PARALLEL'] = '1'

import numpy as np
import engine as E
from mesh import create_cube, create_sphere, create_plane

E.GLEngine._build_gpu = lambda self, m: None


def build_models():
    models = []
    ground = E.GameObject(create_plane(20, 20), E.Point3D(0, -0.5, 0),
                          E.Point3D(0, 0, 0), name='地面')
    ground.collider.shape = 'box'
    models.append(ground)
    for i in range(12):
        b = E.GameObject(create_sphere(0.5),
                         E.Point3D((i % 4) * 1.2 - 1.8, 2.0 + (i // 4) * 1.5, 0.0),
                         E.Point3D(0, 0, 0), name='球%d' % i)
        b.collider.shape = 'sphere'
        b.add_rigidbody(mass=1.0, use_gravity=True)
        b.rigidbody.velocity = E.Point3D(0.3 * (i % 3), 0.0, 0.1 * (i % 2))
        models.append(b)
    for i in range(3):
        r = E.GameObject(create_cube(0.8), E.Point3D(-2.0 + i * 2.0, 6.0 + i * 2.0, 0.0),
                         E.Point3D(0, 0, 0), name='滚块%d' % i)
        r.collider.shape = 'sphere'
        r.add_rigidbody(mass=0.5, use_gravity=True)
        r.rigidbody.velocity = E.Point3D(0.5, 0.0, 0.0)
        models.append(r)
    return models


def snapshot(models):
    return np.array([[m.position.x, m.position.y, m.position.z,
                      m.rotation.x, m.rotation.y, m.rotation.z,
                      m.rigidbody.velocity.x if m.rigidbody else 0.0,
                      m.rigidbody.velocity.y if m.rigidbody else 0.0,
                      m.rigidbody.velocity.z if m.rigidbody else 0.0]
                     for m in models])


def make_engine(split):
    eng = E.GLEngine.__new__(E.GLEngine)
    eng.models = []
    eng.materials = []
    eng.lights = []
    eng.cameras = []
    eng.current_model_index = 0
    eng.is_playing = True
    eng._split_enable = split
    eng._clock = None
    eng._interp = None
    eng._render_world = None
    eng._logic_steps = 0
    eng._logic_gen = 0
    eng._prep_aabbs = None
    eng._prep_light_vps = None
    eng._prep_pairs = None
    eng._prep_sig = None
    eng._disp_gen = -1
    eng._pipe_disabled = False
    eng._tps_events = []
    if split:
        E.GLEngine._ensure_split(eng)
    return eng


def main():
    from physics_bridge import PhysicsWorldBridge, cv_available
    if not cv_available:
        print("SKIP: culverin 不可用")
        return 0
    # ★B4c 退役 (2026-10-16): LOOM_NO_PIPE 逃生门已删; 本闸验证批5 串行子步语义
    # (批6 时序闸在 batch6_pipe_probe), 不再关管线线程——语义由 _logic_frame 的
    # else 分支保证 (pipe 未建时自动走串行)。

    N_FRAMES = 300
    DT = 1.0 / 60.0

    # 甲: NO_SPLIT 旧绑死
    # ★B7b 退役 (2026-10-16): 删 LOOM_NO_SPLIT env (A/B 门已退役);
    #   make_engine(split=False) 直接构造绑死模式引擎, 无需 env。
    eng_a = make_engine(split=False)
    build_models.__globals__['_'] = None
    for m in build_models():
        eng_a.models.append(m)
    snaps_a = []
    for f in range(N_FRAMES):
        eng_a.update_physics(DT, events=False)
        snaps_a.append(snapshot(eng_a.models))
    snaps_a = np.array(snaps_a)
    br_a = getattr(eng_a, '_phys_bridge', None)
    if br_a is not None:
        br_a.destroy()

    # 乙: 分离 30Hz × 2 子步 (60FPS 渲染 → 每帧 0-1 逻辑步)
    eng_b = make_engine(split=True)
    for m in build_models():
        eng_b.models.append(m)
    snaps_b = []
    logic_frame_idx = []
    k = 0
    for f in range(N_FRAMES):
        s, p = eng_b._clock.advance(DT)
        if s > 0:
            # 本渲染帧跑过逻辑帧 → 记录末位形与逻辑帧序号
            for _ in range(s):
                logic_frame_idx.append(k)
                k += 1
            snaps_b.append(snapshot(eng_b.models))
    br_b = getattr(eng_b, '_phys_bridge', None)
    if br_b is not None:
        br_b.destroy()

    # 对拍: 第 k 逻辑帧末 == 旧模式第 2k 渲染帧 (30Hz×2子步 = 60Hz 物理)
    ok = True
    n_cmp = min(len(snaps_b), N_FRAMES // 2)
    for k in range(n_cmp):
        sa = snaps_a[2 * (k + 1) - 1]      # 第 (k+1) 个逻辑帧末 = 旧第 2(k+1) 帧末
        sb = snaps_b[k]
        if not np.array_equal(sa, sb):
            d = np.abs(sa - sb).max()
            print("FAIL: 逻辑帧 %d 与旧模式帧 %d 差 max|Δ|=%r" %
                  (k, 2 * (k + 1) - 1, d))
            ok = False
            break
    if ok:
        print("V2 物理对拍: PASS (%d 逻辑帧 == 旧模式 2k 帧逐位, %d 物体)" %
              (n_cmp, snaps_a.shape[1]))
    else:
        print("V2 物理对拍: FAIL — 架构重排引入时序差, 禁止落地")
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
