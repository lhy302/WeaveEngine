# -*- coding: utf-8 -*-
"""parallel.py — CPU 拓扑 / 亲和性 / 脚本专用线程 (2026-08-14 多核优化)

零新依赖 (ctypes 调 kernel32)。目标: Intel 12 代及以后 P/E 大小核调度 ——
主线程/渲染线程绝不落 E 核; 给"开发者脚本"预留 2 个大核 (P 核) 固定给脚本线程。
AMD / 均质 (全大核, 含 Intel Xeon 如 E5-2696 v3) 不启用大小核逻辑, 但逻辑核>=8
也预留 2 核给脚本线程。

关键结构来自本机 Windows SDK 10.0.22621.0 winnt.h (CPU_SET_INFORMATION_PROCESSOR):
  Id / Group / LogicalProcessorIndex / CoreIndex / LastLevelCacheIndex /
  NumaNodeIndex / EfficiencyClass / AllFlags / {Reserved|SchedulingClass} /
  AllocationTag。E 核判定 = EfficiencyClass 高于全场最小 (数据驱动, 不靠厂商字符串),
  **不是** AllFlags 的位 (AllFlags 只有 Parked/Allocated/AllocatedToTargetProcess/
  RealTime 位, 无 Efficient 位)。
"""
import ctypes
import os
import threading
import time
from ctypes import wintypes

# ---------------- 结构体 (按本机 SDK 实际布局, x64) ----------------

class _CPU_SET(ctypes.Structure):
    """CPU_SET_INFORMATION_PROCESSOR — 实际 32 字节 (x64)."""
    _fields_ = [
        ('Id',                    wintypes.DWORD),    # off 0
        ('Group',                 wintypes.WORD),     # off 4
        ('LogicalProcessorIndex', ctypes.c_ubyte),   # off 6
        ('CoreIndex',             ctypes.c_ubyte),   # off 7
        ('LastLevelCacheIndex',   ctypes.c_ubyte),   # off 8
        ('NumaNodeIndex',         ctypes.c_ubyte),   # off 9
        ('EfficiencyClass',       ctypes.c_ubyte),   # off 10  (P核=低, E核=高)
        ('AllFlags',              ctypes.c_ubyte),   # off 11  (Parked/Allocated/...)
        ('ReservedSched',         wintypes.DWORD),   # off 12  ({Reserved|SchedulingClass})
        ('AllocationTag',         ctypes.c_uint64),  # off 16
    ]


class _SYSTEM_CPU_SET_INFORMATION(ctypes.Structure):
    """外层记录 — 8 字节头 + CpuSet, 实际 40 字节."""
    _fields_ = [
        ('Size',   wintypes.DWORD),          # off 0 (整条记录字节数)
        ('Type',   wintypes.DWORD),          # off 4 (CpuSetInformation=0)
        ('CpuSet', _CPU_SET),                # off 8
    ]


# ---------------- 拓扑检测 ----------------

def _detect_cpu_sets():
    """GetSystemCpuSetInformation -> [(Id, EfficiencyClass), ...]."""
    k32 = ctypes.WinDLL('kernel32', use_last_error=True)
    fn = k32.GetSystemCpuSetInformation
    fn.restype = wintypes.BOOL
    fn.argtypes = [ctypes.c_void_p, wintypes.DWORD,
                   ctypes.POINTER(wintypes.DWORD), ctypes.c_void_p, wintypes.DWORD]
    needed = wintypes.DWORD(0)
    fn(None, 0, ctypes.byref(needed), None, 0)
    if not needed.value:
        raise OSError('GetSystemCpuSetInformation 无数据')
    buf = ctypes.create_string_buffer(needed.value)
    used = wintypes.DWORD(0)
    if not fn(buf, needed.value, ctypes.byref(used), None, 0):
        raise ctypes.WinError(ctypes.get_last_error())
    records = []
    off = 0
    while off < used.value:
        rec = _SYSTEM_CPU_SET_INFORMATION.from_buffer(buf, off)
        if rec.Type == 0:      # CpuSetInformation
            cs = rec.CpuSet
            # 亲和掩码用逻辑核号 LogicalProcessorIndex (组内索引); Id 是 CPU set
            # 标识符 (本机实测 = 256+, 不可作掩码位). Group!=0 属多组系统 (>=64 核),
            # 掩码表达不了 -> 加 4096 偏移强制 mask_of 放弃绑定 (安全回退单线程).
            idx = int(cs.LogicalProcessorIndex) + (4096 if cs.Group != 0 else 0)
            records.append((idx, int(cs.EfficiencyClass)))
        size = int(rec.Size)
        if size <= 0:
            break
        off += size
    if not records:
        raise OSError('GetSystemCpuSetInformation 无 CPU 记录')
    return records


def _fallback_count():
    """退路: 活跃逻辑处理器数; 再退路环境变量."""
    try:
        k32 = ctypes.WinDLL('kernel32', use_last_error=True)
        k32.GetActiveProcessorCount.restype = wintypes.DWORD
        k32.GetActiveProcessorCount.argtypes = [wintypes.WORD]
        n = int(k32.GetActiveProcessorCount(0xFFFF))  # ALL_PROCESSOR_GROUPS
        if n > 0:
            return n
    except Exception:
        pass
    try:
        return int(os.environ.get('NUMBER_OF_PROCESSORS', '4') or 4)
    except Exception:
        return 4


def detect_topology():
    """返回 [(逻辑CPU号, is_effective)]。is_effective=True 表示该逻辑核是 E 核
    (效率等级高于全场最小)。均质 CPU (AMD / Intel Xeon / 全 P 核) 全为 False."""
    try:
        sets = _detect_cpu_sets()
    except Exception:
        sets = None
    if not sets:
        n = _fallback_count()
        return [(i, False) for i in range(n)]
    min_eff = min(e for _, e in sets)
    return [(i, e > min_eff) for i, e in sets]


# ---------------- 策略 (纯函数, 可无头单测) ----------------

def mask_of(ids):
    """逻辑 CPU 列表 -> 64 位亲和掩码。任一 id>=64 (掩码放不下) 返回 0 放弃绑定."""
    if not ids or max(ids) >= 64:
        return 0
    m = 0
    for i in ids:
        m |= (1 << i)
    return m


def compute_policy(cores, script_cores=2):
    """cores: [(id, is_effective), ...] -> 亲和策略 dict.

    返回字段: is_hybrid / n_logical / n_eff / n_perf / script_cores /
    process_mask / script_mask / pool_mask。
      - process_mask: 进程亲和 (混合=只 P 核, 让 E 核彻底不被占用; 均质=全核)
      - script_mask:  脚本线程专用核 (2 个大核; 混合=P 核前 2 个, 均质=最高 2 个)
      - pool_mask:    渲染/碰撞线程池核 (process_mask 去掉 script_mask)
    防锁死铁律: n>0 时 process_mask!=0; 至少留 1 个大核给主线程; script_mask=0 时
    调用方不绑定。掩码放不下 (id>=64) 一律放弃绑定 (全 0)."""
    n = len(cores)
    base = {'is_hybrid': False, 'n_logical': n, 'n_eff': 0, 'n_perf': 0,
            'script_cores': 0, 'process_mask': 0, 'script_mask': 0, 'pool_mask': 0}
    if n <= 0:
        return base
    perf = [i for i, e in cores if not e]
    eff = [i for i, e in cores if e]
    base['n_eff'] = len(eff)
    base['n_perf'] = len(perf)
    is_hybrid = bool(perf) and bool(eff)
    base['is_hybrid'] = is_hybrid

    if is_hybrid:
        proc_mask = mask_of(perf)
        if not proc_mask:
            return base                          # 掩码放不下, 放弃绑定
        sc = max(0, min(int(script_cores), max(0, len(perf) - 1)))   # 至少留 1 P 核给主线程
        script_ids = sorted(perf)[:sc] if sc else []   # 最低 sc 个 P 核 (逻辑核号)
        script_mask = mask_of(script_ids)
        return {'is_hybrid': True, 'n_logical': n, 'n_eff': len(eff), 'n_perf': len(perf),
                'script_cores': sc, 'process_mask': proc_mask,
                'script_mask': script_mask, 'pool_mask': proc_mask & ~script_mask}

    # 均质 (AMD / Intel Xeon / 全 P 核): 用真实逻辑核号, 不能假设 0..n-1
    all_ids = sorted(i for i, _ in cores)
    full = mask_of(all_ids)
    if not full:
        return base
    sc = max(0, min(int(script_cores), max(0, n - 1))) if n >= 8 else 0
    script_ids = all_ids[-sc:] if sc else []             # 最高 sc 个逻辑核
    script_mask = mask_of(script_ids)
    return {'is_hybrid': False, 'n_logical': n, 'n_eff': 0, 'n_perf': n,
            'script_cores': sc, 'process_mask': full,
            'script_mask': script_mask, 'pool_mask': full & ~script_mask}


# ---------------- 亲和性应用 ----------------

def apply_process_policy(policy):
    """把 process_mask 设为当前进程亲和。返回是否成功."""
    m = policy.get('process_mask', 0) if policy else 0
    if not m:
        return False
    try:
        k32 = ctypes.WinDLL('kernel32', use_last_error=True)
        k32.GetCurrentProcess.restype = ctypes.c_void_p
        k32.SetProcessAffinityMask.restype = wintypes.BOOL
        k32.SetProcessAffinityMask.argtypes = [ctypes.c_void_p, ctypes.c_size_t]
        return bool(k32.SetProcessAffinityMask(k32.GetCurrentProcess(), m))
    except Exception:
        return False


def pin_current_thread(mask):
    """把**当前线程**亲和设为 mask (在目标线程函数体内调用; GetCurrentThread 伪句柄).
    返回是否成功."""
    if not mask:
        return False
    try:
        k32 = ctypes.WinDLL('kernel32', use_last_error=True)
        k32.GetCurrentThread.restype = ctypes.c_void_p
        k32.SetThreadAffinityMask.restype = ctypes.c_size_t   # 返回旧掩码, 0=失败
        k32.SetThreadAffinityMask.argtypes = [ctypes.c_void_p, ctypes.c_size_t]
        return k32.SetThreadAffinityMask(k32.GetCurrentThread(), mask) != 0
    except Exception:
        return False


def current_process_mask():
    """当前进程亲和掩码 (诊断/测试用)."""
    try:
        k32 = ctypes.WinDLL('kernel32', use_last_error=True)
        k32.GetCurrentProcess.restype = ctypes.c_void_p
        k32.GetProcessAffinityMask.restype = wintypes.BOOL
        k32.GetProcessAffinityMask.argtypes = [
            ctypes.c_void_p, ctypes.POINTER(ctypes.c_size_t),
            ctypes.POINTER(ctypes.c_size_t)]
        proc = ctypes.c_size_t(0)
        sysm = ctypes.c_size_t(0)
        if k32.GetProcessAffinityMask(k32.GetCurrentProcess(),
                                      ctypes.byref(proc), ctypes.byref(sysm)):
            return int(proc.value)
    except Exception:
        pass
    return 0


# ---------------- 单例入口 ----------------

_PARALLEL = None


def get_parallel(script_cores=2):
    """全局单例: {'topology': [...], 'policy': {...}, 'applied': bool}. 首调应用进程亲和."""
    global _PARALLEL
    if _PARALLEL is None:
        topo = detect_topology()
        policy = compute_policy(topo, script_cores)
        applied = apply_process_policy(policy) if policy.get('process_mask') else False
        _PARALLEL = {'topology': topo, 'policy': policy, 'applied': applied}
        if _PARALLEL['applied']:
            p = policy
            kind = '大小核(混合)' if p['is_hybrid'] else '均质'
            from loom_log import verbose
            verbose("[parallel] %s | 逻辑核 %d (P %d / E %d) | 脚本预留 %d 核 | "
                  "进程亲和已应用 (mask=0x%X)" %
                  (kind, p['n_logical'], p['n_perf'], p['n_eff'],
                   p['script_cores'], p['process_mask']))
    return _PARALLEL


# ---------------- 脚本专用线程 (同步模型, 2026-08-14) ----------------

class ScriptRunner:
    """专用线程逐帧执行脚本更新, 同步模型: 每帧主线程 submit -> 等它跑完再渲染.

    - 线程 affinity 在线程函数体内设置 (线程亲和是线程局部的), 固定绑脚本预留核.
    - Event.wait() 释放 GIL, 脚本线程得以获得 GIL 执行 Python 脚本; 主线程等待期间
      不占 GIL. 收益: 脚本恒定落在预留大核, 不落 E 核, 不被渲染线程抢占.
    - _done.set() 放 finally: 脚本无论如何抛不抛异常都唤醒主线程 (防卡死)."""

    def __init__(self, mask):
        self._mask = mask
        self._lock = threading.Lock()
        self._go = threading.Event()
        self._done = threading.Event()
        self._fn = None
        self._dt = 0.0
        self._exc = None
        self._t = threading.Thread(target=self._loop, name='loom-scripts', daemon=True)
        self._t.start()

    def _loop(self):
        if self._mask:
            pin_current_thread(self._mask)
        while True:
            self._go.wait()
            self._go.clear()
            fn, dt = self._fn, self._dt
            if fn is None:
                break
            try:
                fn(dt)
                self._exc = None
            except BaseException as e:
                self._exc = e
            finally:
                self._done.set()        # 无论成败都唤醒主线程 (防卡死)

    def run_frame(self, fn, dt):
        """主线程调用: 交给脚本线程执行 fn(dt) 并阻塞等待完成; 脚本线程异常回抛."""
        if not self._t.is_alive():
            raise RuntimeError('script thread dead')
        with self._lock:
            self._fn, self._dt, self._exc = fn, dt, None
            self._done.clear()
            self._go.set()
        self._done.wait()
        if self._exc is not None:
            raise self._exc

    def stop(self):
        """停止: 置哨兵 fn=None -> 唤醒线程 -> join. 幂等."""
        with self._lock:
            self._fn = None
            self._go.set()
        self._t.join(timeout=2.0)


# ---------------- 每帧 CPU 预计算线程池 (2026-08-15: 8 核均摊) ----------------
# 设计: CPython GIL 只放行释放 GIL 的 C 调用(numpy/GL)真并行, 纯 Python 任务单核串行.
# 所以"8 核均摊"的落点 = 把每帧 CPU 重活里的 numpy 阶段(AABB/碰撞/矩阵)分块丢到这里,
# 主线程只保留 GL 调用 + 事件处理(不可拆的串行段), 脚本留在专用线程. 单核能用的 GIL 任务
# (脚本/物理步进)属于"实在拆不动的任务", 允许个别核偏高 —— 与用户约定一致.

class FramePool:
    """每帧 CPU 预计算线程池: 一次并行执行多个独立任务 / 把任务空间均分到 worker.

    - run_parallel(jobs): 并行执行可调用列表, 返回按序结果 (numpy 重活释放 GIL -> 真并行).
    - map_indexed(n_items, func): 把下标空间 [0..n_items) 均分到 worker, func(下标迭代器)
      逐块返回结果列表, 按序拼接 (顺序确定性, 与逐条目串行一致).
    线程 affinity = pool_mask (预计算核, 即渲染核减脚本预留核)."""

    def __init__(self, n_workers, mask=0):
        from concurrent.futures import ThreadPoolExecutor
        self.n_workers = max(1, int(n_workers))
        init = (lambda: pin_current_thread(mask)) if mask else None
        self._ex = ThreadPoolExecutor(max_workers=self.n_workers, initializer=init)

    def run_parallel(self, jobs):
        jobs = list(jobs)
        if not jobs:
            return []
        if len(jobs) <= 1 or self.n_workers <= 1:
            return [j() for j in jobs]
        futs = [self._ex.submit(j) for j in jobs]
        return [f.result() for f in futs]

    def map_indexed(self, n_items, func, batches_per_thread=4):
        """把下标空间 [0..n_items) 分块并行调 func(下标迭代器), 结果按序拼接 (确定性).
        Unity/ThreadPoolExecutor 式"工作窃取": 切成 n_workers * batches_per_thread 小块,
        空闲 worker 从队列顺手拿 -> 异构核/中途阻塞时负载更均衡 (快核多拿, 慢核少拿).
        块太小会放大调度开销, 块太大则无法窃取; 默认 4 块/线程平衡两者."""
        n_items = int(n_items)
        if n_items <= 0:
            return []
        if self.n_workers <= 1:
            return list(func(range(n_items)))
        nw = min(self.n_workers, n_items)
        nb = max(nw, min(n_items, nw * max(1, int(batches_per_thread))))
        bounds = _split_bounds(n_items, nb)
        # executor.map 自带工作窃取 (chunksize=1 逐批入队) 且结果按序返回
        res = self._ex.map(func, [range(a, b) for a, b in bounds], chunksize=1)
        out = []
        for r in res:
            out.extend(r)
        return out

    def shutdown(self):
        try:
            self._ex.shutdown(wait=False)
        except Exception:
            pass


def _split_bounds(n, k):
    """n 个条目均分 k 块 -> [(start, end), ...] (每块条数差 <= 1)."""
    q, r = divmod(n, k)
    bounds = []
    start = 0
    for i in range(k):
        end = start + q + (1 if i < r else 0)
        bounds.append((start, end))
        start = end
    return bounds


def frame_workers(policy, target=8, script_cores=0):
    """预计算池 worker 数: 目标 8 核均摊 —— min(target, 逻辑核 - 脚本预留核 - 主线程), 保底 1.
    (主线程自己占 1 核做 GL/事件, 脚本线程占脚本预留核, 其余全给预计算池.)"""
    if script_cores is None:
        script_cores = (policy or {}).get('script_cores', 0) or 0
    n_logical = (policy or {}).get('n_logical', 0) or (_fallback_count() or 1)
    return max(1, min(int(target), n_logical - int(script_cores) - 1))


# ================ 每核负载测量 + 主线程核心调度 (2026-08-15) ================
# 问题: 重负载主线程 (GL/事件/调度) 随机落核, 常撞上系统静态负载最高的核 (如 CPU1) ->
# 单核瓶颈. 修: 启动时测每核 busy% (系统级, 含其他进程), 把主线程锁到**负载最低的大核
# (P核)**; 每 interval 秒重测一次, 若别的 P 核负载显著更低 (>= margin) 就迁移主线程
# 亲和. 判断只在启动 + 每 20s 做, 省动态分配消耗. 混合 CPU (12 代+ P/E) 只用 P 核
# (EfficiencyClass 低 = P), 均质 (Xeon/AMD) 全核参与.

class _SPPI(ctypes.Structure):
    """SYSTEM_PROCESSOR_PERFORMANCE_INFORMATION (x64, 48 字节).
    IdleTime 是内核空闲线程时间 (含在 KernelTime 里)."""
    _fields_ = [('IdleTime', ctypes.c_ulonglong),
                ('KernelTime', ctypes.c_ulonglong),
                ('UserTime', ctypes.c_ulonglong),
                ('DpcTime', ctypes.c_ulonglong),
                ('InterruptTime', ctypes.c_ulonglong),
                ('InterruptCount', ctypes.c_ulong)]


def _sppi_snapshot(count):
    """NtQuerySystemInformation(SystemProcessorPerformanceInformation=8) -> [_SPPI,...]."""
    try:
        ntdll = ctypes.WinDLL('ntdll')
        ntdll.NtQuerySystemInformation.restype = ctypes.c_long
        ntdll.NtQuerySystemInformation.argtypes = [
            ctypes.c_int, ctypes.c_void_p, ctypes.c_ulong,
            ctypes.POINTER(ctypes.c_ulong)]
        size = ctypes.sizeof(_SPPI) * max(1, int(count))
        buf = ctypes.create_string_buffer(size)
        ret = ctypes.c_ulong(0)
        if ntdll.NtQuerySystemInformation(8, buf, size, ctypes.byref(ret)) != 0:
            return None
        return [_SPPI.from_buffer(buf, i * ctypes.sizeof(_SPPI))
                for i in range(max(1, int(count)))]
    except Exception:
        return None


def measure_core_busy(count=None, window=0.15):
    """每核 busy% (系统级, 含其他进程). 采样两次 SPPI 算 Idle 增量:
      busy = (kernel+user - idle) / (kernel+user). 返回 {逻辑核号: busy%}.
    单组系统 (<=64 核) 下 SPPI 下标 = 亲和位. 失败返回 None."""
    if count is None:
        count = _fallback_count()
    s0 = _sppi_snapshot(count)
    if s0 is None:
        return None
    time.sleep(max(window, 0.05))
    s1 = _sppi_snapshot(count)
    if s1 is None:
        return None
    out = {}
    for i in range(min(count, len(s0), len(s1))):
        dtotal = (s1[i].KernelTime - s0[i].KernelTime) + (s1[i].UserTime - s0[i].UserTime)
        didle = s1[i].IdleTime - s0[i].IdleTime
        if dtotal > 0:
            busy = (dtotal - didle) / dtotal * 100.0
        else:
            busy = 0.0
        out[i] = min(100.0, max(0.0, busy))
    return out


class MainThreadCoreScheduler:
    """主线程核心调度: 把重负载主线程锁到启动时负载最低的 P 核, 每 interval 秒重测,
    显著更空闲的 P 核出现就迁移. 测量只在启动+周期做, 省动态分配消耗.

    - topology: [(逻辑核号, is_effective)], 来自 detect_topology()
    - exclude_bits: 排除的亲和位 (如脚本预留核, 不让主线程去抢)
    - busy_probe: 可注入的测量函数 (测试用; None=系统真实测量)
    - disable_pin: True 时不真改线程亲和 (测试用), _rebalance 只算不绑"""

    def __init__(self, topology, interval=20.0, margin=15.0, window=0.15,
                 exclude_bits=0, busy_probe=None, disable_pin=False):
        """interval<=0: 只启动时锁一次, 不做周期重选 (Loom 用 —— 引擎本身负载高,
        周期跳核会引发周期性卡顿). interval>0: 每 interval 秒重测迁移 (LoomHub 用)."""
        self._topo = list(topology)
        self._interval = float(interval)
        self._margin = float(margin)
        self._window = float(window)
        self._exclude = int(exclude_bits or 0)
        self._busy_probe = busy_probe
        self._disable_pin = bool(disable_pin)
        self._main_tid = threading.get_ident()   # 调用方线程 (应为进程主线程)
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._current_bit = None
        self._rebalance()                        # 启动判断 (同步, 首帧前锁核)
        if not self._disable_pin and self._interval > 0:
            self._thread = threading.Thread(target=self._watch, daemon=True,
                                            name='loom-main-core')
            self._thread.start()

    def _p_bits(self):
        return [b for b, eff in self._topo
                if not eff and 0 <= b < 64 and not (self._exclude >> b) & 1]

    def _measure(self):
        if self._busy_probe is not None:
            return self._busy_probe()
        return measure_core_busy(count=len(self._topo) or None,
                                 window=self._window)

    def _rebalance(self):
        busy = self._measure()
        if not busy:
            return self._current_bit
        pbits = [b for b in self._p_bits() if b in busy]
        if not pbits:
            return self._current_bit
        best = min(pbits, key=lambda b: busy[b])
        with self._lock:
            cur = self._current_bit
            if cur is not None and cur in busy:
                # 防抖: 当前核负载不比最佳核高过 margin 就不迁移 (省切换/重锁消耗)
                if busy[cur] - busy[best] < self._margin:
                    return cur
            if self._pin_main(best):
                self._current_bit = best
                return best
            return cur

    def _pin_main(self, bit):
        if self._disable_pin:
            return True
        try:
            k32 = ctypes.WinDLL('kernel32', use_last_error=True)
            k32.OpenThread.restype = wintypes.HANDLE
            k32.OpenThread.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
            k32.SetThreadAffinityMask.restype = ctypes.c_size_t
            k32.SetThreadAffinityMask.argtypes = [wintypes.HANDLE, ctypes.c_size_t]
            k32.CloseHandle.argtypes = [wintypes.HANDLE]
            h = k32.OpenThread(0x0020 | 0x0040, False, self._main_tid)  # SET|QUERY
            if not h:
                return False
            r = k32.SetThreadAffinityMask(h, 1 << bit)
            k32.CloseHandle(h)
            return r != 0
        except Exception:
            return False

    def _watch(self):
        while not self._stop.wait(self._interval):
            try:
                self._rebalance()
            except Exception:
                pass

    def current_bit(self):
        return self._current_bit

    def stop(self):
        self._stop.set()
