# -*- coding: utf-8 -*-
r"""buckets_probe.py — 桶闸命中审计 (诊断批): 播放态 buckets 段为何 0ms.

统计 _prepare_bucket_frame 实际重填次数 (闸命中=跳过) + static_frame 命中率
+ 每次 重填耗时. 回答 "播放态 buckets=0.00 是真闸命中还是插桩口径假象".
不改引擎: 实例 monkeypatch 包装.
"""
import os
import sys
import time

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

    C = {'fill': 0, 'skip': 0, 'fill_t': 0.0, 'static_true': 0, 'static_n': 0}
    _opbf = ed._prepare_bucket_frame
    _osf = ed._interp.static_frame

    def pbf():
        before = getattr(ed, '_bucket_frame_sig', None)
        _t = time.perf_counter()
        _opbf()
        dt = time.perf_counter() - _t
        if getattr(ed, '_bucket_frame_sig', None) != before or before is None:
            C['fill'] += 1
            C['fill_t'] += dt
        else:
            C['skip'] += 1

    def sf():
        r = _osf()
        C['static_n'] += 1
        if r:
            C['static_true'] += 1
        return r

    ed._prepare_bucket_frame = pbf
    ed._interp.static_frame = sf

    # 预热
    for _ in range(30):
        now = time.time()
        delta = min(now - ed.last_frame_time, 0.1)
        ed.last_frame_time = now
        ed.advance_logic(delta)
        ed.render(delta)

    C.update(fill=0, skip=0, fill_t=0.0, static_true=0, static_n=0)
    NF = 200
    t0 = time.perf_counter()
    for _ in range(NF):
        now = time.time()
        delta = min(now - ed.last_frame_time, 0.1)
        ed.last_frame_time = now
        ed.advance_logic(delta)
        ed.render(delta)
    wall = time.perf_counter() - t0

    print("\n[buckets] %d 渲染帧 FPS=%.1f" % (NF, NF / wall))
    print("  桶重填=%d (%.0f%%) 闸跳过=%d  重填耗时=%.3f ms/次 (命中帧计 %.2f ms/帧)"
          % (C['fill'], 100.0 * C['fill'] / NF, C['skip'],
             C['fill_t'] / max(C['fill'], 1) * 1000,
             C['fill_t'] / NF * 1000))
    print("  static_frame 判定: True=%d/%d" % (C['static_true'], C['static_n']))
    st = ed._stage_times
    print("  [插桩] buckets=%.3f interp=%.2f world=%.2f" % (
        st.get('buckets', 0) / NF, st.get('interp', 0) / NF,
        st.get('world_matrices', 0) / NF))
    ed._stop_parallel()
    print("完成。")


if __name__ == '__main__':
    main()
