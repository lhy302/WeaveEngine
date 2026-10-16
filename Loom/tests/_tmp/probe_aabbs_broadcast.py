# -*- coding: utf-8 -*-
"""探针 6: 终极方案 — 500 球同 mesh → vh 共享一个数组 (id 缓存), 广播 matmul
   一次算全场景, 零堆叠拷贝; 转置布局 + f32 可叠加.
   方案 F: vh (1,V,4) 广播 @ m3 (n,1,4)@(n,4,3)? 不行 — matmul 广播规则:
     (n,4,V) @ (n,3,4) 广播: 前导 n 相同 -> 逐 n matmul. vh 共享需 (1,4,V)
     与 (n,3,4): 广播到 (n,3,4)@(n,4,V) — 前导维 1 vs n 广播 OK!
   即: m3T (n,3,4) @ vhT (1,4,V) -> (n,3,V), numpy 广播免费复用 vh 单份.
"""
import time
import numpy as np
from math import cos as _c, sin as _s

N, V = 500, 2035
rng = np.random.default_rng(7)
st = np.linspace(0, np.pi, 37)
ct = np.linspace(0, 2 * np.pi, 55)
P, T = np.meshgrid(st, ct, indexing='ij')
vs = np.stack([0.8 * np.sin(P) * np.cos(T), 0.8 * np.cos(P),
               0.8 * np.sin(P) * np.sin(T)], axis=-1).reshape(-1, 3)
vh = np.empty((V, 4)); vh[:, :3] = vs; vh[:, 3] = 1.0      # 单份 (V,4)
vhT = np.ascontiguousarray(vh.T)                            # (4,V) 单份
m3 = np.zeros((N, 4, 3))
for i in range(N):
    a = rng.random() * np.pi
    cx, sx = _c(a), _s(a)
    m3[i, :3, :3] = [[cx, -sx, 0], [sx, cx, 0], [0, 0, 1]]
    m3[i, 3, :] = rng.random(3) * 40 - 20 + [0, 1, 0]
m3T = np.ascontiguousarray(m3.transpose(0, 2, 1))           # (n,3,4)

mn = np.empty((N, 3)); mx = np.empty((N, 3)); mnT = np.empty((N, 3)); mxT = np.empty((N, 3))
w = np.empty((N, V, 3)); wT = np.empty((N, 3, V))


def t(label, fn, reps=20):
    fn()
    t0 = time.perf_counter()
    for _ in range(reps):
        fn()
    print(f'  {label}: {(time.perf_counter()-t0)/reps*1000:.2f} ms')


print('=== F. 广播 matmul (共享 vh 单份) ===')
t('F f64: (n,3,4)@(1,4,V)->(n,3,V) 连续归约',
  lambda: (np.matmul(m3T, vhT.reshape(1, 4, V), out=wT),
           np.min(wT, axis=2, out=mnT), np.max(wT, axis=2, out=mxT)))

# 数值对拍 (vs 探针4 A 现状)
np.matmul(vh.reshape(1, V, 4).repeat(N, 0) if False else np.broadcast_to(vh, (N, V, 4)),
          m3, out=w)
np.min(w, axis=1, out=mn); np.max(w, axis=1, out=mx)
print('  数值差 max(|mn|):', float(np.abs(mnT - mn).max()),
      ' max(|mx|):', float(np.abs(mxT - mx).max()))

print('=== G. f32 广播 (极限) ===')
m3T32 = m3T.astype(np.float32); vhT32 = vhT.astype(np.float32).reshape(1, 4, V)
wT32 = np.empty((N, 3, V), dtype=np.float32)
mnT32 = np.empty((N, 3), dtype=np.float32); mxT32 = np.empty((N, 3), dtype=np.float32)
t('G f32 广播', lambda: (np.matmul(m3T32, vhT32, out=wT32),
                         np.min(wT32, axis=2, out=mnT32),
                         np.max(wT32, axis=2, out=mxT32)))

print('=== H. 8 worker 池并行叠加估算 (带宽上限) ===')
# 现状 A 80ms 单线程 -> 池 8worker 实测引擎 24.9ms (3.2x 加速, 带宽饱和)
# F 方案 10ms 级 -> 池收益有限, 单线程已足够
