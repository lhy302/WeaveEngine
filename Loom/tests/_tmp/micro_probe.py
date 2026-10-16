# -*- coding: utf-8 -*-
r"""micro_probe.py — 逻辑步内部段计时探针 (诊断批, 只取证不改引擎).

monkeypatch _run_scripts/update_audio/update_animations/update_physics 包计时,
量化逻辑步内 scripts/audio/animations 各占多少 (500球/100脚本 场景).
另: 实测 pipe post->wait 之间主线程真正做了什么 (音频+动画只有 500 次
属性遍历, ~0.1ms —— 重叠窗口基本空转 = 同步税全额交).
"""
import os
import sys
import time

BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, BASE)
os.chdir(BASE)
sys.argv[0] = os.path.join(BASE, 'Loom.py')     # 设置.json 指向根目录
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

    # 编辑态预热
    for _ in range(40):
        now = time.time()
        delta = min(now - ed.last_frame_time, 0.1)
        ed.last_frame_time = now
        ed.render(delta)

    ed.toggle_play()
    print("[probe] split=%s pipe=%s clock=%sHz/%sHz" % (
        ed._split_enable,
        'ON' if ed._phys_pipe else 'OFF',
        ed._clock.logic_fps if ed._clock else '-',
        ed._clock.physics_fps if ed._clock else '-'))

    # monkeypatch 逻辑步内段计时
    T = {'scripts': 0.0, 'audio': 0.0, 'anims': 0.0, 'phys': 0.0,
         'scripts_n': 0, 'phys_n': 0}
    _ors, _oa, _oan, _oph = (ed._run_scripts, ed.update_audio,
                             ed.update_animations, ed.update_physics)

    def rs(dt):
        _t = time.perf_counter()
        _ors(dt)
        T['scripts'] += time.perf_counter() - _t
        T['scripts_n'] += 1

    def ua(dt):
        _t = time.perf_counter()
        _oa(dt)
        T['audio'] += time.perf_counter() - _t

    def uan(dt):
        _t = time.perf_counter()
        _oan(dt)
        T['anims'] += time.perf_counter() - _t

    def up(dt, events=True):
        _t = time.perf_counter()
        _oph(dt, events)
        T['phys'] += time.perf_counter() - _t
        T['phys_n'] += 1

    ed._run_scripts = rs
    ed.update_audio = ua
    ed.update_animations = uan
    ed.update_physics = up

    # 预热
    for _ in range(30):
        now = time.time()
        delta = min(now - ed.last_frame_time, 0.1)
        ed.last_frame_time = now
        ed.advance_logic(delta)
        ed.render(delta)

    # 计时窗口 (200 渲染帧)
    for k in T:
        T[k] = 0.0
    N = 200
    t0 = time.perf_counter()
    steps = 0
    psteps = 0
    for _ in range(N):
        now = time.time()
        delta = min(now - ed.last_frame_time, 0.1)
        ed.last_frame_time = now
        ed.advance_logic(delta)
        ed.render(delta)
        steps += ed._clock.steps
        psteps += ed._clock.phys_steps
    wall = time.perf_counter() - t0

    print("\n[micro] %d 渲染帧 wall=%.2fs FPS=%.1f 逻辑步=%d (%.2f/帧) 物理步=%d" % (
        N, wall, N / wall, steps, steps / N, psteps))
    print("  scripts(线程同步)  = %7.2f ms/渲染帧 (%d 次, %.2f ms/逻辑步)" % (
        T['scripts'] / N * 1000, T['scripts_n'],
        T['scripts'] / max(T['scripts_n'], 1) * 1000))
    print("  audio              = %7.2f ms/渲染帧" % (T['audio'] / N * 1000,))
    print("  animations         = %7.2f ms/渲染帧" % (T['anims'] / N * 1000,))
    print("  update_physics合计 = %7.2f ms/渲染帧 (%d 次, %.2f ms/物理步)" % (
        T['phys'] / N * 1000, T['phys_n'],
        T['phys'] / max(T['phys_n'], 1) * 1000))
    st = ed._stage_times
    print("  [插桩] logic_step=%.2f pipe_wait=%.2f physics=%.2f interp=%.2f" % (
        st.get('logic_step', 0) / N, st.get('pipe_wait', 0) / N,
        st.get('physics', 0) / N, st.get('interp', 0) / N))
    # scripts 线程外 vs logic_step 差值 = audio+anims+interp.advance+Event 税
    ls = st.get('logic_step', 0) / N
    pw = st.get('pipe_wait', 0) / N
    print("\n[结论口径] logic_step %.2f = scripts %.2f + (audio+anims+interp) %.2f"
          % (ls, T['scripts'] / N * 1000, ls - T['scripts'] / N * 1000))
    print("           pipe_wait %.2f ms/渲染帧 = 物理线程 (ensure+pre+step+post)" % pw)
    ed._stop_parallel()
    print("完成。")


if __name__ == '__main__':
    main()
