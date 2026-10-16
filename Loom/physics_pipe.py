# -*- coding: utf-8 -*-
"""
physics_pipe.py — 常驻物理线程 v2 (分离批6 帧内流水线, 2026-09-05)

v2 流水线语义 (批6D): 主线程 post 提交子步后**不等待**, 先跑不依赖物理
的段 (音频/动画/prep 可并行部分), 到真正需要物理结果的同步点 (S1) 才
wait_pending() — "发指令不等待" (Panda3D 任务链 frameSync 模型).

生产者-消费者: pending 计数队列 (多子步连发不丢步); 全部桥状态
(Jolt _w/_entries/_last_sync) 只物理线程触碰; 主线程在 S1 后读模型属性
(回读由物理线程写, Event 置位 happens-before 安全).

三段 pre_step/step/post_step 原样搬线程, R1 红线一行不改.
超时降级: wait 超 timeout = RuntimeError → 调用方永久降级主线程直跑.
★B4c 退役 (2026-10-16): 删 LOOM_NO_PIPE 逃生门 (A/B 基线); 线程建失败 =
系统极限工况 (OS 线程/内存耗尽), 由 _ensure_phys_pipe 兜底 + 醒目告警。
"""
import threading


class PhysicsPipeThread:
    """常驻物理线程 (v2: pending 队列 + 同步点等待)."""

    def __init__(self, bridge, mask=0, timeout=1.0):
        self._br = bridge
        self._mask = int(mask or 0)
        self._timeout = float(timeout)
        self._lock = threading.Lock()
        self._go = threading.Event()      # 有活 (pending>0 或停止)
        self._done = threading.Event()    # 队列清空 (S1 同步点信号)
        self._pending = 0                 # 未消化子步数 (lock 内读写)
        self._jobs = []                   # [(models, dt, gravity, events), ...]
        self._err = None
        self._degraded = False
        self._stop = False
        # ★2026-09-07 重帧治理: ensure_models 只在批次首子步跑 (逻辑帧内
        # 结构不会变 — 脚本在逻辑帧首跑, add/remove 场景结构走 _bump_struct
        # 后仍经引擎侧同步; 子步间唯一写者是本桥自身)。500 体 ensure
        # (签名 tuple 重建) ~0.7ms/次 x (N-1) 子步纯重复 — 多子步 TPS
        # (20Hz=3 子步) 下每逻辑帧省 ~1.4ms。
        self._batch_first = True
        self._t = threading.Thread(target=self._loop, name='loom-physics',
                                   daemon=True)
        self._t.start()

    def _loop(self):
        if self._mask:
            try:
                from parallel import pin_current_thread
                pin_current_thread(self._mask)
            except Exception:
                pass
        while True:
            self._go.wait()
            self._go.clear()
            while True:                   # 逐个消化队列 (不丢步)
                with self._lock:
                    if self._stop:
                        return
                    job = self._jobs.pop(0) if self._jobs else None
                if job is None:
                    break
                models, dt, g, ev = job
                try:
                    br = self._br
                    if self._batch_first:
                        br.ensure_models(models)
                    br.pre_step(dt, g)
                    br.step(dt)           # C 层释放 GIL: 主线程跑 D 段真并行
                    br.post_step()
                    self._err = None
                except BaseException as e:
                    self._err = e
                finally:
                    self._batch_first = False
                    with self._lock:
                        self._pending -= 1
                        empty = (self._pending <= 0)
                    if empty:
                        self._batch_first = True   # 批末: 下一逻辑帧首子步重新 ensure
                        self._done.set()  # S1: 队列清空 → 唤醒主线程

    def post(self, models, dt, gravity, events):
        """主线程: 提交一个物理子步 (非阻塞, 可连发 N 子步)."""
        with self._lock:
            self._jobs.append((list(models), dt, gravity, events))
            self._pending += 1
            self._done.clear()
            self._go.set()

    def wait_pending(self):
        """同步点 S1: 等全部已提交子步完成. 超时 = 报错+永久降级."""
        if not self._done.wait(self._timeout):
            self._degraded = True
            raise RuntimeError("物理线程同步超时 (%.1fs) -> 降级主线程直跑"
                               % self._timeout)
        if self._err is not None:
            e, self._err = self._err, None
            raise e

    # 兼容 v1 调用方 (engine._update_physics_bridge 旧路径/测试桩)
    wait = wait_pending

    def pending(self):
        """未消化子步数 (诊断/断言用)."""
        with self._lock:
            return self._pending

    def stop(self):
        """停止: 哨兵 -> join. 幂等 (v1 同款)."""
        with self._lock:
            self._stop = True
            self._jobs = []
            self._pending = 0
            self._go.set()
        self._t.join(timeout=2.0)
