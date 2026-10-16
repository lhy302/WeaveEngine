# -*- coding: utf-8 -*-
"""
scheduler.py — NgilPool 常驻 nogil 工作池 (调度重构期1, 2026-09-07)

设计: 调度重构总体设计_20260907.txt §二 (2.2 NgilPool 职责 / 2.3 交接协议)。

定位: 主线程只留 Python 胶水, 把逻辑帧里"释放 GIL 的重段" (numpy 大运算 /
ctypes C 内核) 按行分块外包给 2-4 个常驻工作线程 — 段可分块池并行 → 真缩
墙钟 (设计 §〇2 收益判据 (a))。

协议 (零锁, 与 physics_pipe.py v2 同款生产者-消费者模式):
  - submit_batch(packages): 提交一批任务包 [(fn, args_tuple), ...], 非阻塞。
    任务包 = 主线程预打包的 (callable, numpy 参数元组); worker 侧零胶水纯
    执行 fn(*args) — 不做任何包装/分发/对象访问。
  - wait_exchange(timeout): 等全部包完成。超时 → 永久降级 (degraded=True,
    调用方此后走串行旧路, 自愈不重试 — 任务书红线: 主线程 wait 恒带超时)。
  - 完成交接 = 引用交换: worker 写自己的 out 数组切片 (互斥行段, 单写者),
    完成后主线程 Python 赋值换入引擎字段 (GIL 下天然原子) — 无 mutex。
  - shutdown(): 哨兵 + join, 幂等 (退出清理链调)。

红线 (任务书):
  - worker 不碰 GameObject/Qt/脚本对象 — 只接纯 numpy/dll 参数 (调用方用
    已物化 numpy 数组或硬化快照);
  - 时钟/时间轴/interp 语义全留主线程, 本池零接触;
  - LOOM_NO_SCHED=1 时引擎侧根本不建池 (逐位旧行为)。

GIL 争抢缓解 (设计 §五 R1): 任务包主线程打好 (切片视图零拷贝), worker 拿
到就跑 numpy (释放 GIL); Python 胶水每包只有一次 fn(*args) 调用。
"""
import os
import threading
import time

import numpy as np


def _split_bounds(n, k):
    """n 个条目均分 k 块 -> [(start, end), ...] (每块条数差 <=1). 与
    parallel._split_bounds 同式 (本模块自带, 免依赖)."""
    q, r = divmod(n, k)
    bounds = []
    start = 0
    for i in range(k):
        end = start + q + (1 if i < r else 0)
        bounds.append((start, end))
        start = end
    return bounds


def split_bounds(n, k):
    """n 个条目均分 k 块 -> [(start, end), ...] (每块条数差 <=1). 与
    parallel._split_bounds 同式 (引擎侧分块计划用, 公开别名)."""
    return _split_bounds(n, k)


class NgilPool:
    """常驻 nogil 工作池 (2-4 worker, threading; 零锁批式交接)."""

    def __init__(self, n_workers=3, mask=0, name='loom-sched', timeout=0.002):
        """n_workers: 常驻线程数 (2-4; 环境变量 LOOM_SCHED_WORKERS 可调).
        mask: 线程亲和掩码 (0=不绑, 交 OS 调度; 均质大核机器默认 0).
        timeout: wait_exchange 默认超时秒 (任务书: <=2ms 超时降级)."""
        self._timeout = float(timeout)
        self._lock = threading.Lock()
        self._go = threading.Event()      # 有活 (pending>0 或停止)
        self._done = threading.Event()    # 批清空信号 (主线程 wait 点)
        self._jobs = []                   # [(fn, args), ...] 待消化队列
        self._pending = 0                 # 未完成包数 (lock 内读写)
        self._err = None                  # worker 异常 (转永久降级)
        self._degraded = False
        self._stop = False
        self.n_workers = max(1, int(n_workers))
        # SchedMetrics (任务书): 计数面 (engine_metrics 扩展通道消费)
        self.metrics = {
            'batches': 0,                 # 成功提交+完成的批数
            'packages': 0,                # 消化的任务包总数
            'timeouts': 0,                # wait 超时次数 (每次都=永久降级)
            'worker_errors': 0,           # worker 异常次数 (同上)
            'degraded': 0,                # 0/1 永久降级标志 (镜像 _degraded)
        }
        self._threads = []
        for i in range(self.n_workers):
            t = threading.Thread(target=self._loop, name='%s-%d' % (name, i),
                                 daemon=True)
            self._threads.append(t)
            t.start()

    # ---------------- worker 主循环 ----------------
    def _loop(self):
        if getattr(self, '_mask', 0):
            try:
                from parallel import pin_current_thread
                pin_current_thread(self._mask)
            except Exception:
                pass
        while True:
            self._go.wait()
            self._go.clear()
            while True:                   # 逐包消化 (与 physics_pipe 同款)
                with self._lock:
                    if self._stop:
                        return
                    job = self._jobs.pop(0) if self._jobs else None
                if job is None:
                    break
                fn, args = job
                try:
                    fn(*args)             # 零胶水: 纯执行 (numpy/dll 内部释放 GIL)
                except BaseException as e:  # 任务包异常: 记下转永久降级 (调用方串行兜底)
                    self._err = e
                finally:
                    with self._lock:
                        self._pending -= 1
                        empty = (self._pending <= 0)
                    if empty:
                        self._done.set()  # 批清空 -> 唤醒主线程 (happens-before)

    # ---------------- 提交 / 等待 ----------------
    def submit_batch(self, packages):
        """主线程: 提交一批任务包 [(fn, args_tuple), ...] (非阻塞).
        返回 True=已受理 (随后必须 wait_exchange), False=池已降级/停止
        (调用方直接串行兜底). 空批 = 直接收完成信号."""
        pk = list(packages)
        if not pk:
            self._done.set()
            return True
        with self._lock:
            if self._degraded or self._stop:
                return False
            self._jobs.extend(pk)
            self._pending += len(pk)
            self._done.clear()
            self._go.set()
        return True

    def wait_exchange(self, timeout=None):
        """同步点: 等全部已提交包完成. True=完成 (结果数组此刻起可读 —
        Event 置位 happens-before); False=超时/worker 异常 -> 池永久降级,
        调用方必须走串行旧路 (自愈, 不重试)."""
        t = self._timeout if timeout is None else float(timeout)
        if not self._done.wait(t):
            self._degraded = True
            self.metrics['timeouts'] += 1
            self.metrics['degraded'] = 1
            return False
        if self._err is not None:
            self._err = None
            self._degraded = True
            self.metrics['worker_errors'] += 1
            self.metrics['degraded'] = 1
            return False
        self.metrics['batches'] += 1
        return True

    def run_batch(self, packages, timeout=None):
        """提交+等待一步走 (常用入口). True=完成, False=降级 (调用方串行兜底)."""
        if not self.submit_batch(packages):
            return False
        return self.wait_exchange(timeout)

    # ---------------- 状态 / 关闭 ----------------
    @property
    def degraded(self):
        return self._degraded

    def metrics_snapshot(self):
        """只读快照 (engine_metrics 返回; dict 拷贝防污染)."""
        m = dict(self.metrics)
        m['n_workers'] = self.n_workers
        return m

    def shutdown(self):
        """停止: 哨兵 -> join. 幂等 (退出清理链调; physics_pipe.stop 同款)."""
        with self._lock:
            self._stop = True
            self._jobs = []
            self._pending = 0
            self._go.set()
        for t in self._threads:
            t.join(timeout=2.0)


# ---------------- 模块级纯任务函数 (worker 侧零胶水执行体) ----------------
# world_matrices 局部矩阵段 (engine.compute_world_matrices 的 S/R/T 构建 +
# S@R@T). ★必须保持与引擎串行版逐位一致:
#   - Rx@Ry@Rz / (S@R)@T 结合序同 engine._batch_rotations + local=S@R@T;
#   - 全部 zeros 初始化 (与串行版同, 非 zero 元素同式赋值);
#   - 行独立: 每行是独立 4x4 运算, 分块结果与全量串行逐位一致 (无跨行归约).
def sched_wm_chunk(rot, scl, pos, local_out):
    """一块行区间 [a,b) 的局部矩阵: R 构建 + S/T 构建 + (S@R)@T -> local_out.
    rot/scl/pos: (k,3) f64 切片视图; local_out: (k,4,4) f64 互斥切片 (worker 独写)."""
    k = rot.shape[0]
    rx = rot[:, 0]; ry = rot[:, 1]; rz = rot[:, 2]
    cx = np.cos(rx); sx = np.sin(rx)
    cy = np.cos(ry); sy = np.sin(ry)
    cz = np.cos(rz); sz = np.sin(rz)
    Rx = np.zeros((k, 4, 4), dtype=np.float64)
    Rx[:, 0, 0] = 1.0
    Rx[:, 1, 1] = cx; Rx[:, 1, 2] = sx
    Rx[:, 2, 1] = -sx; Rx[:, 2, 2] = cx
    Rx[:, 3, 3] = 1.0
    Ry = np.zeros((k, 4, 4), dtype=np.float64)
    Ry[:, 0, 0] = cy; Ry[:, 0, 2] = -sy
    Ry[:, 1, 1] = 1.0
    Ry[:, 2, 0] = sy; Ry[:, 2, 2] = cy
    Ry[:, 3, 3] = 1.0
    Rz = np.zeros((k, 4, 4), dtype=np.float64)
    Rz[:, 0, 0] = cz; Rz[:, 0, 1] = sz
    Rz[:, 1, 0] = -sz; Rz[:, 1, 1] = cz
    Rz[:, 2, 2] = 1.0; Rz[:, 3, 3] = 1.0
    R = Rx @ Ry @ Rz
    S = np.zeros((k, 4, 4), dtype=np.float64)
    S[:, 0, 0] = scl[:, 0]
    S[:, 1, 1] = scl[:, 1]
    S[:, 2, 2] = scl[:, 2]
    S[:, 3, 3] = 1.0
    T = np.zeros((k, 4, 4), dtype=np.float64)
    T[:, 0, 0] = T[:, 1, 1] = T[:, 2, 2] = T[:, 3, 3] = 1.0
    T[:, 3, 0] = pos[:, 0]
    T[:, 3, 1] = pos[:, 1]
    T[:, 3, 2] = pos[:, 2]
    local_out[:] = S @ R @ T            # 左结合 = (S@R)@T, 与引擎串行版同序
    return 0
