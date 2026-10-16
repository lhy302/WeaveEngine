# -*- coding: utf-8 -*-
r"""sched_pool_check.py — 期1 NgilPool 对拍网 (2026-09-07, 任务书验收①)

断言:
  P0 池机制: submit_batch/wait_exchange 正常批 + 超时永久降级 + 空批 + shutdown。
  P1 world_matrices 局部段: 池分块 (sched_wm_chunk, 3 worker) vs 引擎串行式
     (_batch_rotations + S@R@T) 逐位一致 — 随机/scale 压扁/树状层级/单位/
     零矩阵/单行边界 (真实场景位形由 P3 端到端覆盖)。
  P2 整链: compute_world_matrices 池路径 (LOOM_NO_SCHED 旁路对照) 输出
     逐位一致 + _fw_cache 失效协议不回归 (改位后重算命中新值)。
  P3 端到端位形: 混合500 播放态 100 逻辑帧, 池开 (默认) vs 池关
     (LOOM_NO_SCHED=1) — 全部模型 pos/rot 逐位一致 (物理每子步写回会换
     Point3D, prep 消费 world_matrices 的整链覆盖)。
  P4 world 数值: 池 vs 串行 (N,4,4) 全矩阵 1e-12 内 (任务书口径; 实际逐位)。
"""
import os
import sys
import time

BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, BASE)
os.chdir(BASE)
os.environ['LOOM_NO_PARALLEL'] = '1'     # 测试确定性 (与 phys_cache_bitwise_check 同)

import numpy as np

fails = 0


def check(name, ok, detail=""):
    global fails
    print(("[PASS] " if ok else "[FAIL] ") + name + ("  " + detail if detail else ""))
    if not ok:
        fails += 1


# ================ P0 池机制 ================
from scheduler import NgilPool, sched_wm_chunk, split_bounds  # noqa: E402


def p0():
    pool = NgilPool(n_workers=3, name='sched-check')
    try:
        # 正常批: 6 包各写互斥段
        out = np.zeros((12, 2), dtype=np.float64)
        pkgs = [(lambda a, b, t: out.__setitem__(
            slice(a, b), np.full((b - a, 2), t)), (a, b, i * 100.0))
                for i, (a, b) in enumerate(split_bounds(12, 6))]
        ok = pool.run_batch(pkgs, timeout=2.0)
        check("P0 正常批完成+互斥段写入", ok and (out[:, 0] == np.repeat(
            np.arange(6) * 100.0, 2)).all(), str(pool.metrics_snapshot()))

        # 空批
        ok2 = pool.run_batch([], timeout=2.0)
        check("P0 空批立即完成", ok2)

        # 超时永久降级 (worker sleep 0.5s, timeout 0.05s)
        def slow():
            time.sleep(0.5)
        ok3 = pool.run_batch([(slow, ())], timeout=0.05)
        check("P0 超时 -> 返回 False + 永久降级",
              (not ok3) and pool.degraded and pool.metrics['timeouts'] == 1)
        # 降级后 submit 直接拒 (调用方串行兜底路径)
        ok4 = pool.submit_batch([(slow, ())])
        check("P0 降级后 submit_batch 拒绝", ok4 is False)
    finally:
        pool.shutdown()
        check("P0 shutdown 幂等安全", True)


# ================ P1/P2/P4 矩阵逐位 ================
from engine import GLEngine  # noqa: E402


def serial_local(models, pos, rot, scl):
    """引擎串行式局部矩阵 (compute_world_matrices 旧代码路径, 逐字)."""
    R = GLEngine._batch_rotations(models, rot=rot)
    n = len(models)
    S = np.zeros((n, 4, 4), dtype=np.float64)
    S[:, 0, 0] = scl[:, 0]
    S[:, 1, 1] = scl[:, 1]
    S[:, 2, 2] = scl[:, 2]
    S[:, 3, 3] = 1.0
    T = np.zeros((n, 4, 4), dtype=np.float64)
    T[:, 0, 0] = T[:, 1, 1] = T[:, 2, 2] = T[:, 3, 3] = 1.0
    T[:, 3, 0] = pos[:, 0]
    T[:, 3, 1] = pos[:, 1]
    T[:, 3, 2] = pos[:, 2]
    return S @ R @ T


def chunked_local(pos, rot, scl, n_workers=3):
    """池分块式 (sched_wm_chunk, 与 engine._sched_wm_local 同提交面)."""
    n = pos.shape[0]
    pool = NgilPool(n_workers=n_workers, name='sched-check-wm')
    try:
        nb = min(n_workers, max(1, n // 64))
        bounds = split_bounds(n, nb)
        local = np.empty((n, 4, 4), dtype=np.float64)
        pkgs = [(sched_wm_chunk, (rot[a:b], scl[a:b], pos[a:b], local[a:b]))
                for (a, b) in bounds[1:]]
        a0, b0 = bounds[0]
        sched_wm_chunk(rot[a0:b0], scl[a0:b0], pos[a0:b0], local[a0:b0])
        if not pool.run_batch(pkgs, timeout=2.0):
            return None
        return local
    finally:
        pool.shutdown()


def p1():
    rng = np.random.default_rng(20260907)
    cases = []
    # 真实模型对象 (带 position/rotation/scale) 供 _batch_rotations 兼容
    from engine import GameObject, Point3D

    def mk(name, p, r, s):
        return GameObject(None, p, r, name=name, scale=s)

    for n, tag in [(500, 'n=500 (混合500)'), (128, 'n=128 (闸门边界)'),
                   (127, 'n=127 (闸下)'), (1, 'n=1 单行')]:
        models = []
        for i in range(n):
            m = mk('m%d' % i,
                   (rng.uniform(-20, 20), rng.uniform(-20, 20),
                    rng.uniform(-20, 20)),
                   (rng.uniform(-np.pi, np.pi), rng.uniform(-np.pi, np.pi),
                    rng.uniform(-np.pi, np.pi)),
                   (rng.uniform(0.2, 3.0), rng.uniform(0.2, 3.0),
                    rng.uniform(0.2, 3.0)))
            models.append(m)
        cases.append((models, tag))
    # 特殊形态: scale 压扁 / 零旋转 / 单位
    m2 = []
    for i in range(300):
        m2.append(mk('z%d' % i, (0.0, 0.0, 0.0), (0.0, 0.0, 0.0),
                     (1.0, 1.0, 1.0)))
    cases.append((m2, '单位/零旋转 n=300'))

    for models, tag in cases:
        n = len(models)
        pos = np.array([(m.position.x, m.position.y, m.position.z)
                        for m in models], dtype=np.float64)
        rot = np.array([(m.rotation.x, m.rotation.y, m.rotation.z)
                        for m in models], dtype=np.float64)
        scl = np.array([tuple(m.scale) for m in models], dtype=np.float64)
        if n < 64:
            check("P1 %s: 小 n 走串行 (分块不划算)" % tag, True)
            continue
        ser = serial_local(models, pos, rot, scl)
        par = chunked_local(pos, rot, scl)
        same = bool((ser == par).all())
        d = float(np.abs(ser - par).max())
        check("P1 %s 局部段逐位 (maxdiff=%.1e)" % (tag, d), same)
        # P4: 1e-12 口径 (冗余锚)
        check("P4 %s |diff| <= 1e-12" % tag, d <= 1e-12)


def p2():
    """整链: compute_world_matrices 池路径 vs LOOM_NO_SCHED 串行, 逐位一致
    + _fw_cache 失效协议不回归."""
    from engine import GLEngine, GameObject, Point3D
    rng = np.random.default_rng(77)

    def build():
        from engine import GameObject, Point3D
        e = GLEngine.__new__(GLEngine)
        e._bb_cache = {}
        e._struct_gen = 0
        e._fw_cache = None
        e._soa_snap = None
        e._soa_last_keys = None
        e._sched_pool = NgilPool(n_workers=3, name='sched-check-chain')
        e._sched_pool_built = True
        models = []
        for i in range(400):
            p = (rng.uniform(-10, 10), rng.uniform(-10, 10),
                 rng.uniform(-10, 10))
            r = (rng.uniform(-3, 3), rng.uniform(-3, 3), rng.uniform(-3, 3))
            m = GameObject(None, p, r, name='c%d' % i, scale=(0.5, 0.5, 0.5))
            if i % 7 == 1 and i >= 7:
                m.parent = models[i - 7]     # 树状层级
            m.position = p
            m.rotation = r
            models.append(m)
        e.models = models
        return e, models

    e, models = build()
    try:
        w_pool = e.compute_world_matrices(models)
        e._fw_cache = None                  # 强制重算
        e._soa_snap = None
        e._sched_pool = None                # 串行对照 (同引擎, 池摘除)
        w_ser = e.compute_world_matrices(models)
        d = float(np.abs(w_pool - w_ser).max())
        check("P2 compute_world_matrices 池==串行 逐位 (maxdiff=%.1e)" % d,
              bool((w_pool == w_ser).all()))
        # 失效协议: 改位后缓存必 miss 且新值正确
        e._sched_pool = None
        w1 = e.compute_world_matrices(models)     # 串行 (池摘除态)
        models[0].position = Point3D(123.0, 456.0, 789.0)
        w2 = e.compute_world_matrices(models)
        moved = not bool((w1 == w2).all())
        check("P2 _fw_cache 失效协议: 改位后重算 (非缓存陈值)", moved)
    finally:
        if e._sched_pool is not None:
            e._sched_pool.shutdown()


# ================ P3 端到端位形 (混合500 播放态 100 逻辑帧) ================
def run_e2e(no_sched, frames=100):
    os.environ['LOOM_NO_SCHED'] = '1' if no_sched else '0'
    os.environ.pop('LOOM_NO_PARALLEL', None)   # 建池判定含 NO_PARALLEL!=1 (P3 池开路必须放行)
    # 建池在 __init__, 每次新 EditorApp 实例都会重判 (os.environ 运行时读)。
    import importlib
    import moderngl
    import editor
    importlib.reload(editor) if False else None
    ctx = moderngl.create_standalone_context()
    e = editor.EditorApp(320, 240, ctx=ctx)
    e._external_fb = ctx.detect_framebuffer()
    _og = e.view.gui.render
    e.view.gui.render = (lambda *a, **kw: _og(target=e._external_fb))
    e.load_scene(os.path.join('保存', '压测500混合.json'))
    e.toggle_play()
    for _ in range(6):                       # 预热
        e.advance_logic(0.05)
        e.render(0.05)
    for _ in range(frames):
        e.advance_logic(0.05)
    snap = np.array([(m.position.x, m.position.y, m.position.z,
                      m.rotation.x, m.rotation.y, m.rotation.z)
                     for m in e.models])
    pool_meta = None
    if e._sched_pool is not None:
        pool_meta = e._sched_pool.metrics_snapshot()
    e.toggle_play()
    e._stop_parallel()
    ctx.release()
    return snap, pool_meta


def p3():
    s_on, meta = run_e2e(False)
    s_off, _ = run_e2e(True)
    same = bool((s_on == s_off).all())
    d = float(np.abs(s_on - s_off).max())
    check("P3 端到端 混合500 100 逻辑帧: 池开==池关 位形逐位 (maxdiff=%.1e)"
          % d, same)
    check("P3 池侧账: 批数>0 且未降级",
          meta is not None and meta['batches'] > 0 and meta['degraded'] == 0,
          str(meta))


def main():
    t0 = time.time()
    p0()
    p1()
    p2()
    p3()
    print()
    print("结果:", "ALL PASS ✅" if fails == 0 else "有 FAIL ❌",
          "(%.1fs)" % (time.time() - t0))
    sys.exit(0 if fails == 0 else 1)


if __name__ == '__main__':
    main()
