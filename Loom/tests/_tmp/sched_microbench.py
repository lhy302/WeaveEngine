# -*- coding: utf-8 -*-
"""sched_microbench.py — 期1 微基准: aabbs C 内核碎任务批量化收益定量 (2026-09-07)

设计文档七节要求: "开工前先做 '50 次/帧 n≤6 调用批进单次 DLL 调用' 微基准
(预期 ctypes 提交开销占比 30-50%)"。

口径 (批4A aabbs_call_pattern_probe.py 实锤形态复刻):
  混合500 播放态 prep 走 _model_aabbs_par -> 行级缓存 dirty 行 -> FramePool
  map_indexed 16 块 -> 块内 _aabbs_batched 按 V 分组 -> 每逻辑帧 50 次
  loom_aabbs_minmax 调用全部 n<=6, 累计仅 ~100 行。
真实 V 分布 (混合500): 7 组 V=3015x100 / 2501x90 / 2035x90 / 1617x90 /
  1247x90 / 24x40 / 4x1 (cube/plane 组行数少)。

三口径计时 (同数据同内核, 差异只在"每帧多少次 DLL 调用"):
  A) 碎任务形态: 16 块 x 组内交错 -> ~50 次调用, 每次 n<=6 (播放态现状)
  B) 组批形态: 同 V 组跨块合并 -> 7 次调用, 每次 n=组行数 (batch 入口能达到的最好形态)
  C) 空调用税: n=0 调用 (纯 ctypes 提交开销)
判据: 提交开销占比 = (A总耗时 - A内核纯耗时) / A总耗时;
  A内核纯耗时 ~= B总耗时 - B提交税 (B 的提交次数少, 内核时间相同)。
  占比 <20% -> batch 入口降级为可选项 (任务书出口)。
"""
import json
import os
import sys
import time

BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, BASE)
os.environ['LOOM_NO_NUMBA'] = '1'        # 模拟编译版软件形态 (与播放态同口径)

import numpy as np
import fastpath

assert fastpath._CK['dll'] is not None, 'C DLL 未加载 (本基准必须走 loom_kernels)'

# ---- 混合500 真实 V 分布 (aabbs_call_pattern_probe 取证) ----
V_GROUPS = [(3015, 100), (2501, 90), (2035, 90), (1617, 90),
            (1247, 90), (24, 40), (4, 1)]

rng = np.random.default_rng(20260907)


def make_data():
    """按 V 组生成 (vh, m3) 堆叠数组 — 模拟 _aabbs_batched 组装产物."""
    out = []
    for V, n in V_GROUPS:
        vh = rng.standard_normal((n, V, 4))
        vh[:, :, 3] = 1.0
        m3 = rng.standard_normal((n, 4, 3)) * 0.5
        out.append((np.ascontiguousarray(vh), np.ascontiguousarray(m3), V, n))
    return out


DATA = make_data()


def timed(fn, rounds, warmup=50):
    for _ in range(warmup):
        fn()
    t0 = time.perf_counter()
    for _ in range(rounds):
        fn()
    return (time.perf_counter() - t0) / rounds * 1000.0     # ms


# ---- A) 碎任务形态: 复刻池分块 16 块 -> 每块每 V 组一次调用 (n<=6) ----
def run_frag():
    """按 '16 块 x V 组' 切块, 逐块调用内核 (每块每 V 组一次).
    输出写进预分配缓冲."""
    total_calls = 0
    for vh, m3, V, n in DATA:
        mn = np.empty((n, 3), dtype=np.float64)
        mx = np.empty((n, 3), dtype=np.float64)
        blk = max(1, min(6, (n + 15) // 16))
        for a in range(0, n, blk):
            b = min(a + blk, n)
            fastpath._aabbs_minmax_c(vh[a:b], m3[a:b], mn[a:b], mx[a:b])
            total_calls += 1
    return total_calls


# ---- B) 组批形态: 同 V 组一次调用 (batch 入口能达到的最好形态) ----
def run_batch():
    for vh, m3, V, n in DATA:
        mn = np.empty((n, 3), dtype=np.float64)
        mx = np.empty((n, 3), dtype=np.float64)
        fastpath._aabbs_minmax_c(vh, m3, mn, mx)


# ---- C) ctypes 空调用税 (n=0, 内核立即返回) ----
def run_null():
    vh = np.empty((0, 4, 4), dtype=np.float64)
    m3 = np.empty((0, 4, 3), dtype=np.float64)
    mn = np.empty((0, 3), dtype=np.float64)
    mx = np.empty((0, 3), dtype=np.float64)
    fastpath._aabbs_minmax_c(vh, m3, mn, mx)


def main():
    print('== aabbs C 内核碎任务批量化微基准 (混合500 V 分布复刻) ==')
    print('V 组:', ['V=%d x %d' % (V, n) for V, n in V_GROUPS])
    rows = sum(n for _, n in V_GROUPS)
    print('总行数/帧 = %d (播放态 dirty ~100 行同量级)' % rows)

    n_calls = run_frag()
    print('A 口径实测调用次数/帧 =', n_calls, ' (B 口径 = 7)')

    t_A = timed(run_frag, 300)
    t_B = timed(run_batch, 300)
    t_C = timed(run_null, 2000)

    # 提交税: A 的调用次数 x 每次空调用成本; 占比相对 A 总耗时
    tax_A = n_calls * t_C
    share = tax_A / t_A * 100.0 if t_A else 0.0
    batch_gain = (t_A - t_B) / t_A * 100.0 if t_A else 0.0

    print()
    print('A) 碎任务 %d 次调用/帧 : %.4f ms/逻辑帧' % (n_calls, t_A))
    print('B) 组批 7 次调用/帧    : %.4f ms/逻辑帧' % t_B)
    print('C) ctypes 空调用税     : %.4f ms/次 (%.2f us)' % (t_C, t_C * 1000))
    print('A 提交税合计 = %d x %.4f = %.4f ms -> 占比 %.1f%%'
          % (n_calls, t_C, tax_A, share))
    print('批量化潜在收益 (A->B) = %.1f%%' % batch_gain)
    verdict = ('<20% -> batch 入口降级为可选项 (任务书出口)'
               if share < 20.0 else
               '>=20% -> batch 入口值得做')
    print('判定: 提交开销占比 %.1f%% %s' % (share, verdict))

    # 附: 内核本体按行外推 (播放态 dirty ~100 行 / 帧)
    per_row = t_B / rows
    print()
    print('内核本体 (组批口径) = %.4f us/行 -> 播放态 100 dirty 行 = %.3f ms/逻辑帧'
          % (per_row * 1000.0, per_row * 100))

    result = {
        'groups': V_GROUPS, 'rows_total': rows,
        'A_calls_per_frame': n_calls,
        'A_frag_ms': round(t_A, 4), 'B_batch_ms': round(t_B, 4),
        'C_null_call_ms': round(t_C, 5),
        'submit_share_pct': round(share, 1),
        'batch_gain_pct': round(batch_gain, 1),
        'verdict': verdict,
    }
    out = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                       'sched_microbench_result.json')
    with open(out, 'w', encoding='utf-8') as f:
        json.dump(result, f, ensure_ascii=False, indent=1)
    print('SAVED', out)


if __name__ == '__main__':
    main()
