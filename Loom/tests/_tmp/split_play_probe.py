# -*- coding: utf-8 -*-
r"""split_play_probe.py — 编辑器播放态帧率/阶段耗时探针 (诊断批, 2026-09-05).

目的: 复现"编辑器按下播放后全场景帧率暴跌"并定位根因 (只取证不改引擎源码).

仿真真实路径 = LoomHub -> 编辑器 (Qt GLViewport.paintGL):
    offscreen moderngl ctx -> EditorApp(ctx=ctx) -> load_scene(压测场景)
    -> toggle_play() (真播放边界: 建桥/建物理线程/GC enter/快照)
    -> 每帧 advance_logic(delta) + render(delta)   (与 ui/loom_gui.py:182-183 同链)
  外部模式 render 不 flip, 与 Qt 宿主一致 (QOpenGLWidget 自动交换).

用法:
  py -3.12 tests/_tmp/split_play_probe.py [帧数] [场景json]
    默认 = 分离+管线 (与用户现场默认一致)
  ★B4c 退役 (2026-10-16): 删 --nopipe 分支 (LOOM_NO_PIPE 逃生门退役)。
  ★B7b 退役 (2026-10-16): 删 --nosplit 分支 (LOOM_NO_SPLIT 逃生门退役)。
输出: 编辑态 120 帧 + 播放态 N 帧的 FPS/阶段耗时/pipe_wait 实测/逻辑物理步计数.
"""
import os
import sys
import time

BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, BASE)
os.chdir(BASE)

import moderngl

W, H = 1280, 800


def main():
    n_frames = int(sys.argv[1]) if len(sys.argv) > 1 and sys.argv[1].isdigit() else 300
    args = [a for a in sys.argv[1:] if not a.isdigit()]
    scene = tests_scene = os.path.join(
        BASE, 'tests', '_tmp',
        (args[1] if len(args) > 1 else 'stress_500spheres.json'))
    mode = args[0] if args else ''
    # ★B4c 退役 (2026-10-16): --nopipe 分支已删 (LOOM_NO_PIPE 逃生门退役)。
    # ★B7b 退役 (2026-10-16): --nosplit 分支已删 (LOOM_NO_SPLIT 逃生门退役)。

    os.environ['LOOM_PROFILE'] = '1'

    # ---- offscreen GL context (无窗口, 与 Qt QOpenGLWidget 等价的独立 moderngl ctx) ----
    ctx = moderngl.create_standalone_context()
    import editor as editor_mod
    ed = editor_mod.EditorApp(W, H, ctx=ctx)
    ed._external_fb = ctx.detect_framebuffer()   # 仿 paintGL: 缓存 widget FBO
    # standalone ctx 无 ctx.screen -> gui.render() 默认 target 会炸;
    # 探针侧补 target (Qt 真路径 = widget FBO, 等价), 不改引擎源码
    _orig_grender = ed.view.gui.render
    ed.view.gui.render = (lambda *a, **kw:
                          _orig_grender(target=ed._external_fb))

    # ---- 加载场景 (编辑态) ----
    ok = ed.load_scene(scene)
    print("[probe] load_scene %s -> %s (%d 模型)" % (
        os.path.basename(scene), ok, len(ed.models)))

    # ---- 编辑态跑 120 帧 (基线: 用户说编辑态正常) ----
    ed._stage_times.clear()
    t0 = time.perf_counter()
    for i in range(120):
        now = time.time()
        delta = min(now - ed.last_frame_time, 0.1)
        ed.last_frame_time = now
        ed.advance_logic(delta)      # paintGL 同链 (编辑态 = 空转)
        ed.render(delta)
    wall = time.perf_counter() - t0
    edit_fps = 120 / wall
    st_edit = dict(ed._stage_times)
    print("\n[编辑态] 120 帧 FPS=%.1f (帧时间 %.2f ms)" % (edit_fps, wall / 120 * 1000))
    _dump_stages(st_edit, 120)

    # ---- toggle_play (真播放边界) ----
    print("\n[probe] toggle_play() ...")
    t0 = time.perf_counter()
    ed.toggle_play()
    print("[probe] toggle_play 耗时 %.2f s (建桥/建线程/GC freeze)" % (time.perf_counter() - t0))
    print("[probe] _split_enable=%s _clock=%s _interp=%s _phys_pipe=%s bridge=%s" % (
        getattr(ed, '_split_enable', None),
        type(getattr(ed, '_clock', None)).__name__,
        type(getattr(ed, '_interp', None)).__name__,
        'ON' if getattr(ed, '_phys_pipe', None) is not None else 'OFF',
        'ON' if getattr(ed, '_phys_bridge', None) is not None else 'OFF'))
    # ★B7b 顺带修 (2026-10-16): 预存缺陷 — 批5 已删 clock.physics_fps
    #   (改用 sub_dt); 探针未同步。
    print("[probe] settings: logic_fps=%s sub_dt=%s" % (
        getattr(ed, '_logic_fps_setting', '?') if hasattr(ed, '_logic_fps_setting')
        else ed._clock.logic_fps if ed._clock else '?',
        ('%.4f' % ed._clock.sub_dt) if ed._clock else '?'))

    # ---- 播放态跑 N 帧 (真路径: advance_logic + render, dt=墙钟实测) ----
    # 逐帧记录: 帧耗时 / logic_step / pipe_wait / 逻辑步数 / 物理步数
    pipe = getattr(ed, '_phys_pipe', None)
    _post_t = [0.0]
    _wait_t = [0.0]
    _n = [0]
    if pipe is not None:
        _orig_post = pipe.post
        _orig_wait = pipe.wait

        def timed_post(*a, **kw):
            _t = time.perf_counter()
            r = _orig_post(*a, **kw)
            _post_t[0] += time.perf_counter() - _t
            return r

        def timed_wait(*a, **kw):
            _t = time.perf_counter()
            r = _orig_wait(*a, **kw)
            _wait_t[0] += time.perf_counter() - _t
            _n[0] += 1
            return r

        pipe.post = timed_post
        pipe.wait = timed_wait

    # 预热 40 帧 (建桥后首帧 JIT/缓存)
    for _ in range(40):
        now = time.time()
        delta = min(now - ed.last_frame_time, 0.1)
        ed.last_frame_time = now
        ed.advance_logic(delta)
        ed.render(delta)

    ed._stage_times.clear()
    if pipe is not None:
        _post_t[0] = _wait_t[0] = _n[0] = 0.0
    frames = 0
    dts = []
    logic_steps_total = [0]
    phys_steps_total = [0]
    t0 = time.perf_counter()
    while frames < n_frames:
        now = time.time()
        delta = min(now - ed.last_frame_time, 0.1)
        ed.last_frame_time = now
        f0 = time.perf_counter()
        ed.advance_logic(delta)
        ed.render(delta)
        dts.append(time.perf_counter() - f0)
        clk = getattr(ed, '_clock', None)
        if clk is not None:
            logic_steps_total[0] += clk.steps
            phys_steps_total[0] += clk.phys_steps
        frames += 1
    wall = time.perf_counter() - t0
    play_fps = frames / wall
    st_play = dict(ed._stage_times)

    print("\n[播放态] %d 帧 FPS=%.1f (帧时间 %.2f ms) 墙钟 %.2fs" % (
        frames, play_fps, 1000.0 / play_fps, wall))
    print("  逻辑步合计=%d (%.1f 步/帧)  物理步合计=%d (%.2f 步/帧)" % (
        logic_steps_total[0], logic_steps_total[0] / frames,
        phys_steps_total[0], phys_steps_total[0] / frames))
    _dump_stages(st_play, frames)
    if pipe is not None:
        print("\n[pipe 实测] post=%.2f ms/帧 wait=%.2f ms/帧 (wait调用=%d, 每 物理步 均 wait)"
              % (_post_t[0] / frames * 1000, _wait_t[0] / frames * 1000,
                 _n[0]))
        steps_ph = max(phys_steps_total[0], 1)
        print("  每物理步: post=%.3f ms wait=%.3f ms" % (
            _post_t[0] / steps_ph * 1000, _wait_t[0] / steps_ph * 1000))
    # 帧稳定性
    dms = sorted(d * 1000.0 for d in dts)
    print("\n帧稳定性: p10=%.2f p50=%.2f p90=%.2f p99=%.2f max=%.2f ms" % (
        dms[int(0.10 * len(dms))], dms[len(dms) // 2],
        dms[int(0.90 * len(dms))], dms[min(int(0.99 * len(dms)), len(dms) - 1)],
        dms[-1]))

    ed._stop_parallel()
    print("\n完成。")


def _dump_stages(st, frames):
    keys = ('logic_step', 'interp', 'physics', 'pipe_wait',
            'phys_bridge_ensure', 'phys_bridge_pre', 'phys_bridge_step',
            'phys_bridge_post', 'scripts_inline', 'world_matrices',
            'aabbs', 'shadow_prep', 'shadow_bounds', 'shadow_cornerfill',
            'shadow_matmul', 'collide_pairs', 'shadow_jobs', 'dispatch',
            'buckets')
    tot = 0.0
    for k in keys:
        v = st.get(k, 0.0) / frames
        tot += v
        print("  %-22s %7.2f ms/帧" % (k, v))
    # 其余未知阶段
    known = set(keys)
    rest = sum(v for k, v in st.items() if k not in known) / frames
    if rest > 0.01:
        print("  %-22s %7.2f ms/帧" % ('(其他插桩段)', rest))
        tot += rest
    print("  %-22s %7.2f ms/帧" % ('已插桩合计', tot))


if __name__ == '__main__':
    main()
