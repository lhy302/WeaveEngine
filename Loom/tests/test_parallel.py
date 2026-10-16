# -*- coding: utf-8 -*-
"""parallel.py 纯逻辑测试 (2026-08-14 多核优化): 拓扑策略/mask/脚本线程.

全部用 mock 拓扑数据, 不调真实 Windows API (除末尾安全冒烟: 应用"当前掩码"无操作).
"""
import os
import sys
import threading

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import parallel
from engine import GLEngine, Point3D
from loom_components import TransformComponent   # 桩类 property setter 需 bump _xform_gen

ok = True


def check(label, cond, detail=""):
    global ok
    print(("PASS " if cond else "FAIL ") + label + ("  " + detail if detail else ""))
    if not cond:
        ok = False


def mask_bits(m):
    return [i for i in range(64) if m & (1 << i)]


# ---------- mask_of ----------
check("mask_of 空 -> 0", parallel.mask_of([]) == 0)
check("mask_of [0,1,2] -> 7", parallel.mask_of([0, 1, 2]) == 7)
check("mask_of id>=64 放弃", parallel.mask_of([0, 64]) == 0)
check("mask_of id>=64 全放弃", parallel.mask_of([100]) == 0)

# ---------- 混合拓扑 (模拟 Intel 12代: 8 P + 4 E, P=逻辑核 0..7) ----------
hyb = [(i, False) for i in range(8)] + [(i, True) for i in range(8, 12)]
p = parallel.compute_policy(hyb, 2)
check("混合 is_hybrid=True", p['is_hybrid'] is True)
check("混合 n_logical=12", p['n_logical'] == 12)
check("混合 process_mask = P 全掩码(0x00FF)", p['process_mask'] == 0xFF,
      "mask=0x%X" % p['process_mask'])
check("混合 script_mask = 前2个P核(bit0,1)", p['script_mask'] == 0x3,
      "mask=0x%X" % p['script_mask'])
check("混合 pool_mask = P减2 (0xFC)", p['pool_mask'] == 0xFC,
      "mask=0x%X" % p['pool_mask'])
check("混合 预留核=2", p['script_cores'] == 2)

# ---------- P 核饥饿 (1 P + 3 E): 不预留, 不锁死 ----------
starve = [(0, False)] + [(i, True) for i in (1, 2, 3)]
p = parallel.compute_policy(starve, 2)
check("饥饿 不预留 (sc=0)", p['script_cores'] == 0)
check("饥饿 script_mask=0", p['script_mask'] == 0)
check("饥饿 process_mask 非空 (bit0)", p['process_mask'] == 1,
      "mask=0x%X" % p['process_mask'])

# ---------- 均质 18 (模拟开发机 Xeon E5-2696 v3) ----------
uni = [(i, False) for i in range(18)]
p = parallel.compute_policy(uni, 2)
check("均质18 is_hybrid=False", p['is_hybrid'] is False)
check("均质18 process_mask = 全18核", p['process_mask'] == (1 << 18) - 1,
      "mask=0x%X" % p['process_mask'])
check("均质18 script_mask = 最高2核(bit16,17)", p['script_mask'] == (3 << 16),
      "bits=%s" % mask_bits(p['script_mask']))
check("均质18 pool_mask = 16核", p['pool_mask'] == 0xFFFF,
      "mask=0x%X" % p['pool_mask'])

# ---------- 均质 4 (n<8 不预留) ----------
p = parallel.compute_policy([(i, False) for i in range(4)], 2)
check("均质4 不预留 (sc=0)", p['script_cores'] == 0)
check("均质4 script_mask=0", p['script_mask'] == 0)
check("均质4 process_mask=全4核", p['process_mask'] == 0xF)

# ---------- 空 / 越界 id ----------
p = parallel.compute_policy([], 2)
check("空拓扑 全 0", p['process_mask'] == 0 and p['script_mask'] == 0
      and p['n_logical'] == 0)
p = parallel.compute_policy([(i, False) for i in range(20)] + [(64, False)], 2)
check("id>=64 放弃绑定", p['process_mask'] == 0)
# 混合且 P 核 id>=64 也放弃
p = parallel.compute_policy([(64, False)] + [(i, True) for i in range(4)], 2)
check("混合 id>=64 放弃绑定", p['is_hybrid'] is True and p['process_mask'] == 0)

# ---------- 防锁死硬约束 (多拓扑遍历) ----------
for cores in [hyb, starve, uni, [(i, False) for i in range(4)],
              [(i, False) for i in range(8)] + [(i, True) for i in range(8, 16)]]:
    p = parallel.compute_policy(cores, 2)
    if p['n_logical'] > 0:
        check("防锁死 process_mask!=0 (%d核)" % p['n_logical'], p['process_mask'] != 0)
        check("防锁死 script_mask⊆process_mask", (p['script_mask'] & ~p['process_mask']) == 0)
        check("防锁死 pool_mask⊆process_mask", (p['pool_mask'] & ~p['process_mask']) == 0)
        # 至少留 1 核给主线程: pool_mask 非空 (或 script_mask 空时 pool=process)
        if p['script_mask']:
            check("防锁死 pool_mask!=0", p['pool_mask'] != 0)

# ---------- ScriptRunner (mask=0, 纯逻辑) ----------
seen = []


def _rec(dt):
    seen.append(threading.current_thread().name + ":" + repr(dt))


r = parallel.ScriptRunner(0)
for i in range(4):
    r.run_frame(_rec, i * 0.5)
check("ScriptRunner 线程名+顺序",
      seen == ["loom-scripts:%s" % repr(i * 0.5) for i in range(4)], str(seen))


def _bad(dt):
    raise ValueError("boom")


try:
    r.run_frame(_bad, 1.0)
    check("ScriptRunner 异常回抛", False)
except ValueError:
    check("ScriptRunner 异常回抛", True)
# 异常后线程仍存活可继续
seen2 = []
r.run_frame(lambda dt: seen2.append(dt), 9.0)
check("ScriptRunner 异常后仍可用", seen2 == [9.0])
r.stop()
check("ScriptRunner stop 后线程结束", not r._t.is_alive())

# ---------- 安全亲和性冒烟 (应用当前掩码 = 无操作) ----------
cur = parallel.current_process_mask()
check("current_process_mask 非空", cur != 0, "mask=0x%X" % cur)
if cur:
    res = parallel.apply_process_policy({'process_mask': cur})
    check("apply_process_policy 当前掩码成功(无操作)", res is True)
    res2 = parallel.pin_current_thread(cur)
    check("pin_current_thread 当前掩码成功(无操作)", res2 is True)
check("apply mask=0 -> False", parallel.apply_process_policy({'process_mask': 0}) is False)
check("pin mask=0 -> False", parallel.pin_current_thread(0) is False)

# ---------- compute_world_matrices 与 model_world_matrix 数值等价 (含父链) ----------
_eng = GLEngine.__new__(GLEngine)   # 未初始化实例, 只测纯矩阵方法


class _FakeModel:
    def __init__(self, pos, rot, scale, parent=None):
        self.position = Point3D(*pos)
        self.rotation = Point3D(*rot)
        self.scale = scale
        self.parent = parent


_rng = np.random.default_rng(42)
_fake = []
for i in range(30):
    _p = _fake[i - 1] if i > 0 and _rng.random() < 0.4 else None
    _fake.append(_FakeModel(
        tuple(_rng.uniform(-5, 5, 3)), tuple(_rng.uniform(-3, 3, 3)),
        tuple(_rng.uniform(0.1, 3, 3)), _p))
_W = _eng.compute_world_matrices(_fake)
_max_err = max(float(np.abs(_W[i] - _eng.model_world_matrix(m)).max())
               for i, m in enumerate(_fake))
check("批量矩阵 vs 逐模型 数值等价(含父链)", _max_err < 1e-9,
      "max_err=%.2e" % _max_err)
check("批量矩阵形状 (N,4,4)", _W.shape == (30, 4, 4), str(_W.shape))
check("空列表批量矩阵", _eng.compute_world_matrices([]).shape == (0, 4, 4))

# ---------- _pair_overlap_vec 与 _pair_overlap 逐位等价 ----------
_rng = np.random.default_rng(7)
_n = 60
_kind = _rng.integers(0, 2, _n).astype(np.int64)
_bmn = _rng.uniform(-3, 3, (_n, 3))
_bmx = _bmn + _rng.uniform(0.5, 3, (_n, 3))
_scn = _rng.uniform(-3, 3, (_n, 3))
_rad = _rng.uniform(0.3, 2, _n)
_data = []
for i in range(_n):
    if _kind[i] == 0:
        _data.append(('box', (Point3D(*_bmn[i]), Point3D(*_bmx[i]))))
    else:
        _data.append(('sphere', (Point3D(*_scn[i]), float(_rad[i]))))
_pairs = [(i, j) for i in range(_n) for j in range(_n) if i != j]
_ai = np.array([p[0] for p in _pairs], dtype=np.int64)
_bj = np.array([p[1] for p in _pairs], dtype=np.int64)
_vec = GLEngine._pair_overlap_vec(_ai, _bj, _bmn, _bmx, _scn, _rad, _kind)
_mism = sum(1 for k, (i, j) in enumerate(_pairs)
            if bool(_vec[k]) != bool(GLEngine._pair_overlap(_data[i], _data[j])))
check("向量化碰撞判定 vs 标量 逐位等价", _mism == 0, "mismatch=%d" % _mism)

# ---------- 并行碰撞检测 vs 内联 get_collisions 结果一致 ----------
from concurrent.futures import ThreadPoolExecutor


class _FMesh:
    def __init__(self, verts):
        self.vertices = np.asarray(verts, dtype=np.float64)


class _FCollider:
    def __init__(self, shape, enabled=True):
        self.shape = shape
        self.enabled = enabled


class _FModel:
    """测试桩: 模拟 GameObject 的 position/rotation/scale 写语义.
    ★关键: 真实 GameObject 的 position/rotation/scale 是 property, setter 会 bump
    TransformComponent._xform_gen (compute_world_matrices 缓存失效的唯一信号).
    桩类必须复现该语义, 否则 compute_world_matrices 返回过期矩阵 → 与
    model_world_matrix 现算路径不一致 (mismatch)."""
    def __init__(self, pos, rot, scale, shape, parent=None):
        self._position = Point3D(*pos)
        self._rotation = Point3D(*rot)
        self._scale = scale
        self.mesh = _FMesh(_cube_v)
        self.collider = _FCollider(shape)
        self.parent = parent
        self.scripts = []
        self._colliding = set()

    @property
    def position(self):
        return self._position
    @position.setter
    def position(self, v):
        self._position = v if isinstance(v, Point3D) else Point3D(*v)
        TransformComponent._xform_gen += 1
    @property
    def rotation(self):
        return self._rotation
    @rotation.setter
    def rotation(self, v):
        self._rotation = v if isinstance(v, Point3D) else Point3D(*v)
        TransformComponent._xform_gen += 1
    @property
    def scale(self):
        return self._scale
    @scale.setter
    def scale(self, v):
        self._scale = tuple(v)
        TransformComponent._xform_gen += 1


_cube_v = [(0, 0, 0), (1, 0, 0), (0, 1, 0), (1, 1, 0),
           (0, 0, 1), (1, 0, 1), (0, 1, 1), (1, 1, 1)]
_eng2 = GLEngine.__new__(GLEngine)
_rng = np.random.default_rng(99)
_fm = []
for i in range(40):
    _p = _fm[i - 1] if i > 0 and _rng.random() < 0.15 else None
    _fm.append(_FModel(tuple(_rng.uniform(-4, 4, 3)),
                       tuple(_rng.uniform(-0.5, 0.5, 3)),
                       tuple(_rng.uniform(0.5, 2.5, 3)),
                       'sphere' if i % 3 == 0 else 'box', _p))
_eng2.models = _fm
_eng2._frame_world = _eng2.compute_world_matrices(_fm)   # 模拟"上一帧"批量矩阵 (将过期)
_eng2.parallel = {'policy': {'pool_mask': 0, 'n_logical': 18}}
_eng2.script_cores = 2
_eng2._collision_pool = ThreadPoolExecutor(max_workers=4)
# 本帧物理移动物体: _frame_world 过期, 并行检测必须用当帧当前位形
for i in range(0, len(_fm), 5):
    _p = _fm[i].position
    _fm[i].position = Point3D(_p.x + 1.2, _p.y + 0.4, _p.z - 0.8)
_pairs2 = _eng2._collision_pairs_parallel()
_par2 = {}
for i, j in _pairs2:
    _par2.setdefault(i, set()).add(j)
    _par2.setdefault(j, set()).add(i)
_mism2 = sum(1 for i, m in enumerate(_fm)
             if {id(_fm[j]) for j in _par2.get(i, ())} != {id(x) for x in _eng2.get_collisions(m)})
_eng2._collision_pool.shutdown(wait=False)
check("并行碰撞检测 vs 内联 结果一致(含物体移动)", _mism2 == 0, "mismatch=%d" % _mism2)

# ================= 2026-08-15: FramePool (8 核均摊预计算池) =================
# ---------- _split_bounds 均分 ----------
check("_split_bounds 8->4 块", parallel._split_bounds(8, 4) == [(0, 2), (2, 4), (4, 6), (6, 8)])
check("_split_bounds 10->3 块 (差<=1)", parallel._split_bounds(10, 3) == [(0, 4), (4, 7), (7, 10)])
check("_split_bounds n==k 每块1", parallel._split_bounds(2, 2) == [(0, 1), (1, 2)])

# ---------- frame_workers (目标 8 核) ----------
fw = parallel.frame_workers({'n_logical': 18, 'script_cores': 2}, target=8, script_cores=2)
check("frame_workers 18核-2脚本-1主 = 8", fw == 8, "n=%d" % fw)
fw = parallel.frame_workers({'n_logical': 4}, target=8, script_cores=0)
check("frame_workers 4核 = min(8,4-0-1)=3", fw == 3, "n=%d" % fw)
fw = parallel.frame_workers({'n_logical': 4}, target=8, script_cores=3)
check("frame_workers 退化保底 1", fw == 1, "n=%d" % fw)

# ---------- FramePool.map_indexed: 结果与串行一致 (工作窃取下顺序确定性) ----------
_pool = parallel.FramePool(4, 0)
_items = list(range(60))
_serial = [i * 2 for i in _items]
_par = _pool.map_indexed(len(_items), lambda idx: [i * 2 for i in idx])
check("map_indexed 顺序=串行 (工作窃取分块)", _par == _serial, "n=%d" % len(_par))
# 空
check("map_indexed 空 -> []", _pool.map_indexed(0, lambda idx: []) == [])
# 单 worker 退化
_pool1 = parallel.FramePool(1, 0)
check("map_indexed 单worker = 串行", _pool1.map_indexed(5, lambda idx: list(idx)) == list(range(5)))
_pool1.shutdown()
# run_parallel 顺序 + 真并行 (非空 job 列表)
_res = _pool.run_parallel([lambda: 1, lambda: 2, lambda: 3])
check("run_parallel 顺序", _res == [1, 2, 3])
check("run_parallel 空 -> []", _pool.run_parallel([]) == [])
_pool.shutdown()

# ---------- _model_aabbs_par vs get_bounding_box 逐模型等价 (含池路径) ----------
_eng3 = GLEngine.__new__(GLEngine)
_fm3 = []
_rng = np.random.default_rng(11)
for i in range(40):
    _fm3.append(_FModel(tuple(_rng.uniform(-5, 5, 3)),
                        tuple(_rng.uniform(-1, 1, 3)),
                        tuple(_rng.uniform(0.5, 3, 3)),
                        'box', _fm3[i - 1] if i > 0 and _rng.random() < 0.3 else None))
_eng3.models = _fm3
_eng3._frame_world = _eng3.compute_world_matrices(_fm3)
_eng3._frame_pool = None          # 串行回退路径
_aabb_serial = _eng3._model_aabbs_par(_fm3, _eng3._frame_world)
_err = 0
for i, (a, b) in enumerate(_aabb_serial):
    a2, b2 = _eng3.get_bounding_box(_fm3[i], _eng3._frame_world[i])
    if abs(a.x - a2.x) + abs(a.y - a2.y) + abs(a.z - a2.z) > 1e-9 \
            or abs(b.x - b2.x) + abs(b.y - b2.y) + abs(b.z - b2.z) > 1e-9:
        _err += 1
check("_model_aabbs_par 串行 = get_bounding_box 逐模型", _err == 0, "mismatch=%d" % _err)

_eng3._frame_pool = parallel.FramePool(4, 0)
_aabb_par = _eng3._model_aabbs_par(_fm3, _eng3._frame_world)
check("_model_aabbs_par 池分块 = 串行 (8核均摊路径)", _aabb_par == _aabb_serial)
_eng3._frame_pool.shutdown()

# ---------- _scene_light_bounds_par vs 旧 _scene_light_bounds 数值一致 ----------
_eng4 = GLEngine.__new__(GLEngine)
_eng4.models = _fm3
_eng4._frame_world = _eng4.compute_world_matrices(_fm3)
_eng4._frame_pool = None
_view = np.eye(4, dtype=np.float64)
_bounds_old = _eng4._scene_light_bounds(_view)     # 走新串行路径 (即 _model_aabbs_par + par)
_aabbs = _eng4._model_aabbs_par(_fm3, _eng4._frame_world)
_bounds_new = _eng4._scene_light_bounds_par(_view, _aabbs)
_d1 = [float(_bounds_old[0][k]) - float(_bounds_new[0][k]) for k in range(3)]
_d2 = [float(_bounds_old[1][k]) - float(_bounds_new[1][k]) for k in range(3)]
check("_scene_light_bounds_par == 串行包围盒", max(abs(x) for x in _d1 + _d2) < 1e-9,
      "diff=%.1e" % max(abs(x) for x in _d1 + _d2))
check("_scene_light_bounds_par 空 -> None", _eng4._scene_light_bounds_par(_view, []) is None)

# ================= 2026-08-15: 每核负载测量 + 主线程核心调度 =================
# ---------- measure_core_busy (真实 API, 只校验结构) ----------
_b = parallel.measure_core_busy(count=None, window=0.05)
if _b is not None:
    _valid = all(0.0 <= v <= 100.0 for v in _b.values()) and len(_b) >= 1
    check("measure_core_busy 返回 {核: 0..100 busy%}", _valid, str(list(_b.items())[:3]))
else:
    check("measure_core_busy (API 不可用, 跳过)", True)

# ---------- MainThreadCoreScheduler (mock busy + disable_pin, 纯逻辑) ----------
def _mk_sched(topo, busy, exclude=0, margin=15.0):
    return parallel.MainThreadCoreScheduler(topo, busy_probe=lambda: busy,
                                            disable_pin=True, margin=margin,
                                            exclude_bits=exclude)

# 混合 8P+4E: P=逻辑核 0..7, E=8..11. CPU1(bit1) 静态负载最高, bit5 最低
_topo_hyb = [(i, False) for i in range(8)] + [(i, True) for i in range(8, 12)]
_busy = {i: 30.0 + (20 if i == 1 else 0) for i in range(12)}
_busy[5] = 5.0
_s1 = _mk_sched(_topo_hyb, _busy)
check("调度器选中负载最低 P 核 (bit5, 避开 CPU1/bit1)",
      _s1.current_bit() == 5, str(_s1.current_bit()))
# E 核负载再低也不选 (bit10=1% 也不选 E)
_busy2 = dict(_busy); _busy2[10] = 1.0
_s2 = _mk_sched(_topo_hyb, _busy2)
check("E 核不被选 (即便负载最低)", _s2.current_bit() == 5, str(_s2.current_bit()))
# exclude_bits: 排除 bit5 -> 选次低 P 核
_s3 = _mk_sched(_topo_hyb, _busy, exclude=1 << 5)
check("exclude_bits 排除 bit5 后选次低 P 核",
      _s3.current_bit() != 5 and _s3.current_bit() in range(8), str(_s3.current_bit()))
# margin 防抖: 当前核差最佳 < margin 不迁移
_s4 = _mk_sched(_topo_hyb, _busy, margin=40.0)
_busy3 = dict(_busy); _busy3[5] = 30.0; _busy3[2] = 10.0
_s4._busy_probe = lambda: _busy3
_s4._rebalance()
check("margin 防抖: 差 20 < margin40 不迁移", _s4.current_bit() == 5, str(_s4.current_bit()))
# margin 达标迁移到更低核
_s5 = _mk_sched(_topo_hyb, _busy, margin=15.0)
_busy4 = dict(_busy); _busy4[5] = 50.0; _busy4[2] = 10.0
_s5._busy_probe = lambda: _busy4
_s5._rebalance()
check("margin 达标: 差 40 >= 15 迁移到 bit2", _s5.current_bit() == 2, str(_s5.current_bit()))
# interval=0: 只启动选核, 不启 20s 重选 watchdog (Loom 用, 防周期跳核卡顿)
_s6 = parallel.MainThreadCoreScheduler(_topo_hyb, busy_probe=lambda: _busy, interval=0)
check("interval=0 仍做启动选核", _s6.current_bit() == 5, str(_s6.current_bit()))
check("interval=0 不启 watchdog 线程", not hasattr(_s6, '_thread'))
# interval>0: 启 watchdog (LoomHub 用)
_s7 = parallel.MainThreadCoreScheduler(_topo_hyb, busy_probe=lambda: _busy, interval=20)
check("interval=20 启 watchdog 线程", hasattr(_s7, '_thread') and _s7._thread.is_alive())
_s7.stop()
try:
    _s7._thread.join(timeout=1.0)
except Exception:
    pass

print("总结果: ALL PASS ✅" if ok else "总结果: 有 FAIL ❌")
sys.exit(0 if ok else 1)
