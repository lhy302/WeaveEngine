# -*- coding: utf-8 -*-
r"""micro2_probe.py — 物理线程三段拆解 + post→wait 间隙分析 (诊断批).

量化: pipe_wait 里 ensure/pre/step/post 各占多少 (线程侧计时),
     以及主线程 post→wait 之间实际只跑了 audio+anims (~0.03ms) →
     物理线程全部执行时间都是主线程纯等待 (同步税).
不改引擎源码: monkeypatch pipe._loop 内桥调用? 不能 —— 线程已跑.
改为 monkeypatch 桥方法本身 (bridge.ensure_models/pre_step/step/post_step
线程内也走这些方法, 计时天然落线程侧).
"""
import os
import sys
import time
import threading

BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, BASE)
os.chdir(BASE)
sys.argv[0] = os.path.join(BASE, 'Loom.py')
os.environ['LOOM_PROFILE'] = '1'

import moderngl                                  # noqa: E402


def main():
    scene = os.path.join(BASE, 'tests', '_tmp', 'stress_500spheres.json')
    ctx = moderngl.create_standalone_context()
    import editor as editor_mod
    ed = editor_mod.EditorApp(1280, 800, ctx=ctx)
    ed._external_fb = ctx.detect_framebuffer()
    _orig_grender = ed.view.gui.render
    ed.view.gui.render = (lambda *a, **kw:
                          _orig_grender(target=ed._external_fb))
    ed.load_scene(scene)
    for _ in range(40):
        now = time.time()
        delta = min(now - ed.last_frame_time, 0.1)
        ed.last_frame_time = now
        ed.render(delta)
    ed.toggle_play()

    # 计时主线程 post→wait 间隙 (pipe.post 返回到 pipe.wait 开始)
    pipe = ed._phys_pipe
    T = {'ensure': 0.0, 'pre': 0.0, 'step': 0.0, 'post': 0.0,
         'gap': 0.0, 'wait': 0.0}
    N = {'ensure': 0, 'pre': 0, 'step': 0, 'post': 0, 'gap': 0}
    br = ed._phys_bridge
    _oe, _op, _os, _opst = (br.ensure_models, br.pre_step, br.step, br.post_step)

    def en(m):
        _t = time.perf_counter()
        r = _oe(m)
        T['ensure'] += time.perf_counter() - _t
        N['ensure'] += 1
        return r

    def pr(dt, g=None):
        _t = time.perf_counter()
        r = _op(dt, g)
        T['pre'] += time.perf_counter() - _t
        N['pre'] += 1
        return r

    def st(dt):
        _t = time.perf_counter()
        r = _os(dt)
        T['step'] += time.perf_counter() - _t
        N['step'] += 1
        return r

    def po(dt=None):
        _t = time.perf_counter()
        r = _opst(dt)
        T['post'] += time.perf_counter() - _t
        N['post'] += 1
        return r

    br.ensure_models = en
    br.pre_step = pr
    br.step = st
    br.post_step = po

    _opipe_post, _opipe_wait = pipe.post, pipe.wait

    def p_post(*a, **kw):
        T['_post_end'] = time.perf_counter()
        return _opipe_post(*a, **kw)

    def p_wait(*a, **kw):
        # 主线程从 post 返回到进入 wait 的间隙 (audio+anims 等)
        if T.get('_post_end') is not None:
            T['gap'] += time.perf_counter() - T['_post_end']
            N['gap'] += 1
        _t = time.perf_counter()
        r = _opipe_wait(*a, **kw)
        T['wait'] += time.perf_counter() - _t
        return r

    pipe.post = p_post
    pipe.wait = p_wait

    # 预热
    for _ in range(30):
        now = time.time()
        delta = min(now - ed.last_frame_time, 0.1)
        ed.last_frame_time = now
        ed.advance_logic(delta)
        ed.render(delta)

    for k in T:
        T[k] = 0.0
    for k in N:
        N[k] = 0
    NF = 200
    t0 = time.perf_counter()
    steps = psteps = 0
    for _ in range(NF):
        now = time.time()
        delta = min(now - ed.last_frame_time, 0.1)
        ed.last_frame_time = now
        ed.advance_logic(delta)
        ed.render(delta)
        steps += ed._clock.steps
        psteps += ed._clock.phys_steps
    wall = time.perf_counter() - t0
    th = threading.current_thread()

    print("\n[micro2] %d 渲染帧 FPS=%.1f 逻辑步=%d 物理步=%d" % (
        NF, NF / wall, steps, psteps))
    print("  线程侧 (物理线程执行): ensure=%.2f pre=%.2f step=%.2f post=%.2f ms/物理步"
          % (T['ensure'] / max(N['ensure'], 1) * 1000,
             T['pre'] / max(N['pre'], 1) * 1000,
             T['step'] / max(N['step'], 1) * 1000,
             T['post'] / max(N['post'], 1) * 1000))
    print("    (调用次数 ensure=%d pre=%d step=%d post=%d)" % (
        N['ensure'], N['pre'], N['step'], N['post']))
    print("  主线程: post→wait 间隙=%.3f ms/物理步 (audio+anims 重叠窗口)"
          % (T['gap'] / max(N['gap'], 1) * 1000,))
    print("  主线程: wait=%.2f ms/物理步 (纯等待 = 线程执行+唤醒税)" % (
        T['wait'] / max(N['gap'], 1) * 1000,))
    st = ed._stage_times
    print("  [插桩] logic_step=%.2f pipe_wait=%.2f interp=%.2f world=%.2f aabbs=%.2f shadow=%.2f" % (
        st.get('logic_step', 0) / NF, st.get('pipe_wait', 0) / NF,
        st.get('interp', 0) / NF, st.get('world_matrices', 0) / NF,
        st.get('aabbs', 0) / NF, st.get('shadow_prep', 0) / NF))
    ed._stop_parallel()
    print("完成。")


if __name__ == '__main__':
    main()
