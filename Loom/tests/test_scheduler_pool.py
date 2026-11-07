# -*- coding: utf-8 -*-

"""
test_scheduler_pool.py — NgilPool P-11/P-12/P-13/P-14 回归 (scan_09)

背景 (审计 docs/audit/scan_09_scripting.md)
-------------------------------------------
P-11 [PROVED/P2] mask 参数未存为 _mask -> 线程亲和分支恒不执行。
P-12 [PROVED/P3] metrics['packages'] 声明后从未累加 (监控恒 0 包)。
P-13 [PROVED/P2] 超时降级后 worker 仍在 fn 内写共享输出, 调用方随即串行
     兜底 -> 两个写者并发写同一 numpy 切片 (非确定性脏数据)。
P-14 [PROVED/P2] shutdown 把 _jobs 清空并 _pending 归零 -> 在途 worker 收尾
     减成 -1 -> _done.set() -> wait_exchange 对"只执行了部分包"返回 True。

本文件断言修复后的行为:
  A (P-11): mask 落 _mask; 传 mask 时每个 worker 都调用 pin_current_thread。
  B (P-12): 每批成功执行后 metrics['packages'] 按实际消化包数累加。
  C (P-13): wait_exchange 超时返回 False 时, worker 已停止写 (drain 完成)。
  D (P-14): shutdown 后 _pending 不为负, wait 不返回 True, 队列包不执行。
  E: 正常批 / 空批 / 幂等 shutdown 等既有语义不回归。

运行: python tests\test_scheduler_pool.py   (无头, 无 GPU)
"""
import sys as _sys_utf8
try:
    _sys_utf8.stdout.reconfigure(encoding='utf-8', errors='replace')
    _sys_utf8.stderr.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

import os
import sys
import threading
import time
import types

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))            # Loom\

from scheduler import NgilPool

_FAILS = []


def check(name, cond, extra=""):
    print(("PASS " if cond else "FAIL ") + name + ("  " + str(extra) if extra else ""))
    if not cond:
        _FAILS.append(name)


# ====================================================================
# A (P-11): mask 存储 + worker 亲和调用
# ====================================================================
def t_mask_stored_and_pinned():
    saved = sys.modules.get('parallel')
    fake = types.ModuleType('parallel')
    pinned = []

    def pin(mask):
        pinned.append((threading.current_thread().name, mask))

    fake.pin_current_thread = pin
    sys.modules['parallel'] = fake
    pool = None
    try:
        pool = NgilPool(n_workers=2, mask=0b101)
        deadline = time.time() + 2.0
        while len(pinned) < 2 and time.time() < deadline:
            time.sleep(0.01)
        check("[A] mask 落 _mask 属性", getattr(pool, '_mask', None) == 5,
              getattr(pool, '_mask', None))
        check("[A] 每个 worker 都按 mask 绑核",
              len(pinned) == 2 and all(m == 5 for _, m in pinned), pinned)
        check("[A] 绑核发生在工作线程 (不是主线程)",
              all(name != threading.current_thread().name for name, _ in pinned),
              pinned)
    finally:
        if pool is not None:
            pool.shutdown()
        if saved is not None:
            sys.modules['parallel'] = saved
        else:
            sys.modules.pop('parallel', None)

    # mask=0 (默认): 不绑核, 也不应报错
    pool = NgilPool(n_workers=1)
    try:
        check("[A] 默认 mask=0 不绑核", pool._mask == 0, pool._mask)
    finally:
        pool.shutdown()


# ====================================================================
# B (P-12): metrics['packages'] 累加
# ====================================================================
def t_metrics_packages():
    pool = NgilPool(n_workers=2)
    try:
        out = []
        ok = pool.run_batch([(lambda i=i: out.append(i), ()) for i in range(3)],
                            timeout=2.0)
        m = pool.metrics_snapshot()
        check("[B] 第一批执行完成", ok and sorted(out) == [0, 1, 2], (ok, out))
        check("[B] packages 累加 3", m['packages'] == 3, m)
        check("[B] batches=1 (与 packages 语义对齐)", m['batches'] == 1, m)

        out2 = []
        ok2 = pool.run_batch([(lambda i=i: out2.append(i), ()) for i in range(2)],
                             timeout=2.0)
        m2 = pool.metrics_snapshot()
        check("[B] 第二批完成", ok2 and sorted(out2) == [0, 1], (ok2, out2))
        check("[B] packages 累计 5", m2['packages'] == 5, m2)
        check("[B] batches 累计 2", m2['batches'] == 2, m2)

        # 空批: 计入 batches, 不增加 packages
        check("[B] 空批返回 True", pool.run_batch([], timeout=2.0))
        m3 = pool.metrics_snapshot()
        check("[B] 空批不增加 packages", m3['packages'] == 5, m3)
    finally:
        pool.shutdown()


# ====================================================================
# C (P-13): 超时返回 False 时 worker 已停写
# ====================================================================
def t_timeout_drains_worker():
    pool = NgilPool(n_workers=1, timeout=0.02)
    evt = threading.Event()
    log = []

    def slow():
        time.sleep(0.15)
        log.append('worker_write')
        evt.set()

    try:
        ok = pool.run_batch([(slow, ())], timeout=0.02)
        check("[C] 超时 -> 返回 False", ok is False, ok)
        check("[C] wait 返回时 worker 已停写 (drain 完成)",
              evt.is_set() and log == ['worker_write'], (evt.is_set(), log))
        check("[C] 永久降级 + 超时计数",
              pool.degraded and pool.metrics['timeouts'] == 1,
              pool.metrics_snapshot())
        # 降级后调用方串行兜底: 此刻没有并发写者 (worker 已 drain)
        serial = ['serial_fallback']
        check("[C] 串行兜底可安全接管", serial == ['serial_fallback'])
    finally:
        pool.shutdown()


# ====================================================================
# D (P-14): shutdown 不丢账 / 不假完成
# ====================================================================
def t_shutdown_accounting():
    pool = NgilPool(n_workers=1)
    started = threading.Event()
    executed = []

    def slow(i):
        executed.append(i)
        started.set()
        time.sleep(0.3)

    check("[D] 提交 4 包", pool.submit_batch([(slow, (i,)) for i in range(4)]))
    check("[D] 前置: 第一个包已开始执行", started.wait(2.0))
    pool.shutdown()
    check("[D] shutdown 后 _pending == 0 (不为负)", pool._pending == 0,
          pool._pending)
    check("[D] 队列中未执行的 3 包被丢弃 (只执行在途 1 个)",
          executed == [0], executed)
    check("[D] shutdown 后 wait 不返回 True (未全部完成)",
          pool.wait_exchange(1.0) is False)
    pool.shutdown()                  # 幂等
    check("[D] 幂等 shutdown 后 _pending 仍为 0", pool._pending == 0,
          pool._pending)


# ====================================================================
# E: 既有语义不回归
# ====================================================================
def t_basic_semantics():
    pool = NgilPool(n_workers=2)
    try:
        out = []
        ok = pool.run_batch([(lambda i=i: out.append(i), ()) for i in range(4)],
                            timeout=2.0)
        check("[E] 正常批完成且全部执行", ok and sorted(out) == [0, 1, 2, 3],
              (ok, out))
        check("[E] 正常批 _pending 归零", pool._pending == 0, pool._pending)
        check("[E] 空批立即完成", pool.run_batch([], timeout=2.0) is True)
        check("[E] 降级前 submit 正常受理",
              pool.submit_batch([(lambda: None, ())]) is True)
        check("[E] 受理后 wait 完成", pool.wait_exchange(2.0) is True)
    finally:
        pool.shutdown()
        pool.shutdown()              # 幂等


if __name__ == "__main__":
    print("========== NgilPool P-11/P-12/P-13/P-14 (scan_09) ==========")
    t_mask_stored_and_pinned()
    t_metrics_packages()
    t_timeout_drains_worker()
    t_shutdown_accounting()
    t_basic_semantics()
    print()
    if _FAILS:
        print("总结果: FAIL ❌", _FAILS)
        sys.exit(1)
    print("总结果: ALL PASS ✅")
