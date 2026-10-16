# -*- coding: utf-8 -*-
"""只读探针: 编辑器态腰斩定量分解 (不改引擎代码).
探针 1: QTimer 8ms vs 1ms 实际触发率 (PreciseTimer, Windows 时间分辨率)
探针 2: numpy aabbs 内核 500 球实测 (matmul+min/max, 与 fastpath._aabbs_minmax_np 同款)
"""
import os
import sys
import time

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import numpy as np

# ---------- 探针 1: QTimer 8ms vs 1ms ----------
def probe_timer():
    from PySide6.QtCore import QTimer, Qt
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication(sys.argv)
    out = {}
    for interval in (8, 1):
        hits = []
        t0 = time.perf_counter()
        tm = QTimer()
        tm.setTimerType(Qt.TimerType.PreciseTimer)
        tm.timeout.connect(lambda: hits.append(time.perf_counter()))
        tm.start(interval)
        end = t0 + 2.0
        while time.perf_counter() < end:
            app.processEvents()
        tm.stop()
        if len(hits) >= 2:
            d = np.diff(hits)
            span = hits[-1] - hits[0]
            out[interval] = (len(hits), float(span / (len(hits) - 1) * 1000),
                             float(d.mean() * 1000), float(d.max() * 1000))
    return out


# ---------- 探针 2: aabbs numpy 内核 500 球 ----------
def probe_aabbs(n_models=500, V=2035):
    # 与引擎同款: vh (n,V,4) f64, m3 (n,4,3) f64, out (n,3)
    rng = np.random.default_rng(7)
    vh = rng.standard_normal((n_models, V, 4))
    vh[:, :, 3] = 1.0
    m3 = rng.standard_normal((n_models, 4, 3))
    mn = np.empty((n_models, 3))
    mx = np.empty((n_models, 3))
    # 预热 (BLAS 线程池拉起)
    np.matmul(vh, m3)
    reps = 20
    t0 = time.perf_counter()
    for _ in range(reps):
        w = np.matmul(vh, m3)                       # 朴素版 (无 out= 复用)
        np.min(w, axis=1, out=mn)
        np.max(w, axis=1, out=mx)
    t_naive = (time.perf_counter() - t0) / reps * 1000
    wbuf = np.empty((n_models, V, 3))
    t0 = time.perf_counter()
    for _ in range(reps):
        np.matmul(vh, m3, out=wbuf)                 # 复用版 (当前工作区 fastpath 已带)
        wbuf.min(axis=1, out=mn)
        wbuf.max(axis=1, out=mx)
    t_reuse = (time.perf_counter() - t0) / reps * 1000
    # 串行纯 Python 模拟 numba 版单线程工作量级对照 (仅 10 模型外推)
    return t_naive, t_reuse


def probe_aabbs_threads(n_models=500, V=2035):
    """OMP 线程数对 matmul 的影响 (OpenBLAS/MKL 线程池)."""
    import numpy
    cfg = numpy.show_config(mode='dicts') if hasattr(numpy, 'show_config') else {}
    try:
        from threadpoolctl import threadpool_info
        info = threadpool_info()
    except Exception:
        info = cfg
    return info


if __name__ == '__main__':
    print('=== 探针1: QTimer 实际触发 (PreciseTimer, offscreen) ===')
    r = probe_timer()
    for k, (n, eff, mean, mx) in r.items():
        print(f'  interval={k}ms: {n} hits / 2s -> 有效周期 {eff:.2f}ms '
              f'(mean {mean:.2f}ms, max {mx:.2f}ms), 理论上限 {1000/eff:.0f} FPS')
    print()
    print('=== 探针2: numpy aabbs 内核 (500球 x 2035顶点, f64) ===')
    tn, tr = probe_aabbs()
    print(f'  朴素 matmul (每帧新分配 24.5MB): {tn:.2f} ms/帧')
    print(f'  out= 复用版 (当前 fastpath 已带): {tr:.2f} ms/帧')
    print()
    print('=== numpy BLAS 线程配置 ===')
    for i in probe_aabbs_threads():
        print(' ', {k: v for k, v in i.items() if k in
                    ('num_threads', 'threading_layer', 'prefix', 'architecture',
                     'filepath', 'internal_api')})
