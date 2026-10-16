# -*- coding: utf-8 -*-
"""
decouple_check.py — 决定性实验: 逻辑帧与渲染帧是否真解耦 (用户质疑绑定问题)

判据: 无限制模式下连续 render(小dt), 逻辑帧只在 accumulator 攒满时跑。
若解耦: 相邻渲染帧墙钟 = 渲染段耗时 (~2-17ms), 逻辑帧落点帧才出现长帧;
若仍绑定: 每帧都长 (逻辑成本摊在每帧)。

同时测: 逻辑帧墙钟本身 (advance 内耗时) 分解。
"""
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..', '..'))
os.environ['LOOM_NO_PARALLEL'] = '1'

import pygame


def main():
    scene = sys.argv[1] if len(sys.argv) > 1 else 'tests/_tmp/stress_500spheres.json'
    pygame.init()
    pygame.display.gl_set_attribute(pygame.GL_SWAP_CONTROL, 0)
    import runtime
    eng = runtime.PlayerApp(scene, 320, 240)
    eng.set_mouse_locked(False)
    eng.is_playing = True
    for _ in range(40):
        eng.render(1.0 / 120.0)               # 预热

    # 300 帧逐帧墙钟
    frames = []
    for _ in range(300):
        t0 = time.perf_counter()
        eng.render(1.0 / 120.0)
        frames.append((time.perf_counter() - t0) * 1000.0)
    import numpy as np
    fa = np.array(frames)
    n_logic = eng._clock.steps
    print("场景: %s" % scene.split('/')[-1].split('\\')[-1])
    print("渲染帧墙钟: p10=%.2f p50=%.2f p90=%.2f p99=%.2f max=%.2f ms" % (
        np.percentile(fa, 10), np.percentile(fa, 50),
        np.percentile(fa, 90), np.percentile(fa, 99), fa.max()))
    print("帧率: %.1f FPS (均值 %.2f ms)" % (300.0 / fa.sum(), fa.mean()))
    # 分离判据: 快帧 (纯渲染) vs 慢帧 (逻辑帧落点) 双峰分布
    fast = fa[fa < np.percentile(fa, 50)]
    slow = fa[fa >= np.percentile(fa, 50)]
    print("双峰: 快帧 p50=%.2f ms (%d 帧) | 慢帧 p50=%.2f ms (%d 帧)" % (
        np.median(fast), len(fast), np.median(slow), len(slow)))
    print("分离判据: 快帧 = 纯渲染成本 (应 ~= 渲染段), 慢帧 = 渲染+逻辑帧墙钟")
    print("若'每帧都慢' (无双峰) = 逻辑渲染仍绑定; 若'少数帧慢' = 解耦正常")
    # 逻辑帧墙钟: 单独测 advance 内耗时
    st = eng._stage_times
    n = st.get('logic_step', 0.0)
    steps_total = eng._clock.steps
    print("logic_step 段累计: %.2f ms/渲染帧 (本窗口逻辑步 %d)" % (n / 300.0, steps_total))
    pygame.quit()
    return 0


if __name__ == '__main__':
    sys.exit(main())
