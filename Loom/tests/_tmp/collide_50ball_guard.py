# -*- coding: utf-8 -*-
"""collide_50ball_guard.py — 50球守护 (闸门 c): 编辑器态 FPS >= 158.7

口径: EditorApp 加载 保存\\压测50球.json, 不进播放态 (编辑器态), 关 vsync,
预热后测 180 渲染帧 (与 ckernels_e2e_worker 同骨架).
用法: py -3.12 tests\\_tmp\\collide_50ball_guard.py
"""
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
BASE = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, BASE)
os.chdir(BASE)
os.environ['LOOM_NO_NUMBA'] = '1'
os.environ['LOOM_PROFILE'] = '1'

import pygame
import editor
import sceneio


def main():
    pygame.init()
    pygame.display.gl_set_attribute(pygame.GL_SWAP_CONTROL, 0)
    eng = editor.EditorApp(1280, 800)
    try:
        for m in list(eng.models):
            eng.remove_model(m)
        eng.lights.clear()
        data = sceneio.load_scene_data(os.path.join('保存', '压测50球.json'))
        sceneio.scene_from_dict(eng, data)
        eng.current_model_index = 0
        for _ in range(40):
            eng._handle_events()
            eng.render(1.0 / 120.0)
        eng._stage_times.clear()
        n = 180
        t0 = time.perf_counter()
        for _ in range(n):
            eng._handle_events()
            eng.render(1.0 / 120.0)
        wall = time.perf_counter() - t0
        fps = n / wall
        st = eng._stage_times
        print('50球编辑器态: FPS=%.1f (%.3f ms/帧)' % (fps, 1000.0 / fps),
              flush=True)
        print('  collide_pairs=%.3f ms/帧 (编辑态不走碰撞)'
              % (st.get('collide_pairs', 0.0) / n), flush=True)
        ok = fps >= 158.7
        print('GUARD %s (%.1f vs 158.7)' % ('PASS' if ok else 'FAIL', fps),
              flush=True)
        sys.exit(0 if ok else 1)
    finally:
        try:
            eng._stop_parallel()
        except Exception:
            pass
        pygame.quit()


if __name__ == '__main__':
    main()
