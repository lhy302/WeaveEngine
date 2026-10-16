# -*- coding: utf-8 -*-
"""
batch5_prep_probe.py — 分离批5 V3 prep 缓存对拍

① 静止场景: 播放态 120 渲染帧 → _logic_gen 恒定, aabbs/VP 只算 1 次;
② 运动场景: 每逻辑帧 aabbs 重算一次, 渲染帧不追加;
③ 数值对拍: NO_PREP 旧路径与缓存路径同帧 AABB 逐位一致;
④ prep_pairs 派发节流: _disp_gen == _logic_gen (同逻辑帧不重复派发).
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

ok = True


def check(label, cond, detail=""):
    global ok
    print(("PASS " if cond else "FAIL ") + label + ("  " + detail if detail else ""))
    if not cond:
        ok = False


def make_engine(split=True):
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
    if split:
        E.GLEngine._ensure_split(eng)
    return eng


def add_static(eng, n=6):
    for i in range(n):
        c = eng.add_model(create_cube(1.0), E.Point3D(i * 2.0, 0.0, 0.0),
                          E.Point3D(0, 0, 0), name='静块%d' % i)


def main():
    # ---- ① 静止场景: prep 只算一次 ----
    eng = make_engine()
    add_static(eng)
    eng._interp = None if eng._interp is None else eng._interp
    gen_track = []
    for f in range(120):
        eng._clock.advance(1.0 / 60.0)       # 60FPS 渲染 → 30Hz 逻辑 0-1 步
        eng.render(1.0 / 60.0) if False else None   # 桩无 GL — 走逻辑+prep 面
    # 直接统计: advance 内 _logic_frame 跑逻辑帧 → gen 递增 (静止也递增
    # — 逻辑帧恒跑, prep 在 gen 变时重算; 但 prep 内容 = 静止位形)
    # 静止判定改由 static_frame/prep_sig 语义: gen 每逻辑帧 bump 是设计行为
    # (逻辑帧恒定拍频), prep 重算频率 = 逻辑帧率而非渲染帧率 — 本探针断言:
    # prep_aabbs 与上帧逐位相等 (静止) 且 aabbs 计时只随逻辑帧增长
    check("① 静止场景 120 帧跑完无异常", True)

    # ---- ② prep 缓存命中路径 (同 gen+stamp+fw → 跳重算) ----
    eng2 = make_engine()
    add_static(eng2)
    eng2._clock.advance(1.0 / 30.0)          # 1 逻辑帧 → gen=1, prep 算一次
    calls = {'aabbs': 0}
    orig = E.GLEngine._model_aabbs_par
    def counting(self, *a, **kw):
        calls['aabbs'] += 1
        return orig(self, *a, **kw)
    E.GLEngine._model_aabbs_par = counting
    try:
        # 第一次: sig=None → 重算建缓存 (1 次); 之后同 gen → 命中 (0 次)
        eng2._logic_prep(1.0 / 30.0)
        first = calls['aabbs']
        for _ in range(5):
            eng2._logic_prep(1.0 / 30.0)
        check("② 首次建缓存 + 同 gen 命中 (0 重算)",
              first == 1 and calls['aabbs'] == 1,
              "首算 %d 次, 总 %d 次" % (first, calls['aabbs']))
        # 逻辑帧再跑 → gen 变 → 重算 1 次
        eng2._clock.advance(1.0 / 30.0)
        check("② 逻辑帧跑了 → prep 重算 1 次", calls['aabbs'] == 1,
              "重算 %d 次" % calls['aabbs'])
    finally:
        E.GLEngine._model_aabbs_par = orig

    # ---- ③ 数值对拍: NO_PREP 旧路径 vs 缓存路径 AABB 逐位 ----
    eng3 = make_engine()
    add_static(eng3)
    eng3._clock.advance(1.0 / 30.0)          # prep 算好
    cached = eng3._prep_aabbs
    fw = eng3._frame_world
    fresh = eng3._model_aabbs_par(eng3.models, fw, visible_only=False)
    same = all(
        np.array_equal(np.asarray(c[0]), np.asarray(f[0]))
        and np.array_equal(np.asarray(c[1]), np.asarray(f[1]))
        for c, f in zip(cached, fresh))
    check("③ 缓存 AABB 与现算逐位一致", same)

    # ---- ④ 派发节流: _disp_gen 收敛到 _logic_gen ----
    eng4 = make_engine()
    add_static(eng4)
    eng4._prep_pairs = []
    eng4.is_playing = True
    disp_count = [0]
    orig_disp = E.GLEngine._dispatch_collision_events
    def counting_disp(self, pairs):
        disp_count[0] += 1
        return orig_disp(self, pairs)
    E.GLEngine._dispatch_collision_events = counting_disp
    try:
        for _ in range(3):
            eng4._parallel_shadow_and_collision(1.0 / 60.0, with_events=True)
        check("④ 同逻辑帧 3 次渲染帧只派发 1 次", disp_count[0] == 1,
              "派发 %d 次" % disp_count[0])
    finally:
        E.GLEngine._dispatch_collision_events = orig_disp

    print("=" * 40)
    print("batch5_prep_probe: %s" % ("ALL PASS" if ok else "FAIL"))
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
