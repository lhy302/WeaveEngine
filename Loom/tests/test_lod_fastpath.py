# -*- coding: utf-8 -*-
"""test_lod_fastpath.py — 无 LOD 场景的 _update_lod 快路径 (O(1) 早退).

背景 (_fix_summary §5 遗留 5)
----------------------------
_update_lod 旧实现每帧遍历全部 models 找"配了 lod_levels 的物体" (getattr x2
+ 真值判断)。500 物体无 LOD 的场景实测 ~0.11ms/帧 的纯扫描开销 (生产默认
路径, 绝大多数场景没有 LOD)。

修复: SceneDriver 维护"配了 LOD 的模型"集合 —— 加载时登记一次, 运行期靠
MeshRendererComponent._lod_gen 变化惰性重建; 集合为空时 _update_lod 只做
一次整数比较 + 空判断 (O(1))。

本文件断言:
  A: 500 物体无 LOD: 候选集合为空, _update_lod 平均耗时 < 0.02ms (验收项)。
  B: 无 LOD 时 5 帧 render_pose 不触发任何世界矩阵计算 (零扫描)。
  C: 加载时有 LOD 的模型进入集合; 500 物体里只有 1 个时只算 1 次世界矩阵。
  D: 运行期挂 LOD (直接写 renderer.lod_levels) 被自动感知并生效。
  E: 运行期摘 LOD (置 None) 后集合剪枝, 快路径恢复。
  F: remove_model 同步剪枝候选集合。
  G: 距离选模语义在注册表路径下不变 (近 -> 高模, 远 -> 低模)。

运行: python tests/test_lod_fastpath.py   (无头, 无 GPU)
"""
import sys as _sys_utf8
try:
    _sys_utf8.stdout.reconfigure(encoding='utf-8', errors='replace')
    _sys_utf8.stderr.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
os.environ.setdefault('LOOM_NO_PARALLEL', '1')
os.environ.setdefault('LOOM_NO_SAVE_MIGRATE', '1')

import scene_driver as SD
from loom_components import MeshRendererComponent

_fails = []


def check(name, cond, detail=""):
    print(("PASS " if cond else "FAIL ") + name
          + ("  " + str(detail) if detail else ""))
    if not cond:
        _fails.append(name)


def _cube_obj(i, **extra):
    o = {"id": "o%d" % i, "name": "o%d" % i, "type": "cube",
         "params": {"size": 1.0}, "position": [i * 0.1 - 25.0, 0.0, 0.0],
         "rotation": [0, 0, 0], "scale": [1, 1, 1], "color": "#808080",
         "visible": True, "scripts": []}
    o.update(extra)
    return o


def _scene(objects, dist=10.0):
    return {"version": 10, "materials": [], "lights": [], "cameras": [],
            "camera": {"target": [0, 0, 0], "distance": dist,
                       "yaw": 0.0, "pitch": 0.0},
            "objects": objects}


HI = {"type": "cube", "params": {"size": 1.0}}
LO = {"type": "cube", "params": {"size": 0.5}}


class _MatCounter:
    """替换 scene_driver.object_world_matrix, 统计真实矩阵计算次数."""

    def __init__(self):
        self.n = 0
        self._orig = SD.object_world_matrix

    def __enter__(self):
        orig = self._orig

        def _wrapped(m):
            self.n += 1
            return orig(m)

        SD.object_world_matrix = _wrapped
        return self

    def __exit__(self, *a):
        SD.object_world_matrix = self._orig
        return False


def _avg_ms(fn, n):
    t0 = time.perf_counter()
    for _ in range(n):
        fn()
    return (time.perf_counter() - t0) / n * 1000.0


def _best_ms(fn, n=1000, rounds=3):
    return min(_avg_ms(fn, n) for _ in range(rounds))


def _big_driver(n=500):
    d = SD.SceneDriver()
    d.load_from_data(_scene([_cube_obj(i) for i in range(n)]))
    return d


# ====================================================================
# A: 500 物体无 LOD 的快路径耗时
# ====================================================================
def t_no_lod_fastpath():
    print("=== A: 500 物体无 LOD -> O(1) 早退 ===")
    d = _big_driver(500)
    check("[A] 模型数 500", len(d.models) == 500, len(d.models))
    check("[A] LOD 候选集合为空", len(d._lod_models) == 0, d._lod_models)
    ms = _best_ms(d._update_lod, n=1000, rounds=3)
    check("[A] _update_lod 平均 < 0.02ms/帧", ms < 0.02, "%.6f ms" % ms)
    print("    实测: %.6f ms/帧 (500 物体, 无 LOD)" % ms)


# ====================================================================
# B: 无 LOD 零世界矩阵
# ====================================================================
def t_no_lod_zero_matrix():
    print("=== B: 无 LOD 5 帧 0 次世界矩阵 ===")
    d = _big_driver(500)
    with _MatCounter() as c:
        for _ in range(5):
            d.render_pose(aspect=1.5)
    check("[B] 500 物体无 LOD: 5 帧 0 次世界矩阵", c.n == 0, c.n)


# ====================================================================
# C: 加载登记 + 只遍历候选
# ====================================================================
def t_load_registers_only_configured():
    print("=== C: 加载登记, 只遍历候选 ===")
    objs = [_cube_obj(i) for i in range(500)]
    objs[123]["lod_levels"] = [[5.0, HI], [30.0, LO]]
    d = SD.SceneDriver()
    d.load_from_data(_scene(objs))
    check("[C] 候选集合只有 1 个", len(d._lod_models) == 1, len(d._lod_models))
    check("[C] 登记的是配置 LOD 的物体", d._lod_models[0] is d.models[123],
          d._lod_models[0].name)
    with _MatCounter() as c:
        d.render_pose(aspect=1.5)
        first = c.n
        for _ in range(5):
            d.render_pose(aspect=1.5)
        cached = c.n
    check("[C] 500 物体里只算 1 次世界矩阵", first == 1, first)
    check("[C] 静止 5 帧复用缓存", cached == first, cached)


# ====================================================================
# D/E: 运行期挂 / 摘 LOD 被自动感知
# ====================================================================
def t_runtime_attach_detach():
    print("=== D/E: 运行期挂/摘 LOD ===")
    d = _big_driver(500)
    m = d.models[250]                    # x=0: 相机距离即 d.distance
    hi = SD.spec_to_mesh('cube', {})
    lo = SD.spec_to_mesh('cube', {})
    gen0 = MeshRendererComponent._lod_gen
    m.renderer.lod_levels = [(5.0, hi), (30.0, lo)]
    check("[D] 写 renderer.lod_levels bump _lod_gen",
          MeshRendererComponent._lod_gen == gen0 + 1,
          MeshRendererComponent._lod_gen - gen0)
    d.distance = 3.0
    d._update_lod()
    check("[D] 下一帧自动登记", len(d._lod_models) == 1, len(d._lod_models))
    check("[D] 近处选高模", m.mesh is hi, getattr(m.mesh, 'params', None))
    d.distance = 20.0
    d._update_lod()
    check("[D] 远处选低模", m.mesh is lo, getattr(m.mesh, 'params', None))

    m.renderer.lod_levels = None
    d._update_lod()
    check("[E] 摘 LOD 后集合剪枝", len(d._lod_models) == 0, len(d._lod_models))
    ms = _best_ms(d._update_lod, n=1000, rounds=2)
    check("[E] 摘除后恢复快路径 < 0.02ms", ms < 0.02, "%.6f ms" % ms)


# ====================================================================
# F: remove_model 剪枝
# ====================================================================
def t_remove_model_prunes():
    print("=== F: remove_model 剪枝 ===")
    d = _big_driver(20)
    m = d.models[3]
    m.renderer.lod_levels = [(5.0, SD.spec_to_mesh('cube', {}))]
    d._update_lod()
    check("[F] 挂 LOD 后候选 1 个", len(d._lod_models) == 1, len(d._lod_models))
    d.remove_model(m)
    check("[F] remove_model 后候选空", len(d._lod_models) == 0, len(d._lod_models))
    check("[F] remove_model 后 models 少 1", len(d.models) == 19, len(d.models))


# ====================================================================
# G: 选模语义不变
# ====================================================================
def t_selection_semantics():
    print("=== G: 注册表路径下选模语义 ===")
    d = SD.SceneDriver()
    d.load_from_data(_scene([_cube_obj(0, position=[0, 0, 0],
                                       lod_levels=[[5.0, HI], [30.0, LO]])]))
    m = d.models[0]
    hi, lo = m.renderer.lod_levels[0][1], m.renderer.lod_levels[1][1]
    picks = []
    for dist in (3.0, 20.0):
        d.distance = dist
        d.render_pose(aspect=1.5)
        picks.append("hi" if m.mesh is hi else ("lo" if m.mesh is lo else "?"))
    check("[G] 距离 3 -> 高模, 距离 20 -> 低模", picks == ["hi", "lo"], picks)


if __name__ == "__main__":
    print("========== LOD 无配置快路径 (_fix_summary §5 遗留 5) ==========")
    t_no_lod_fastpath()
    t_no_lod_zero_matrix()
    t_load_registers_only_configured()
    t_runtime_attach_detach()
    t_remove_model_prunes()
    t_selection_semantics()
    print()
    if _fails:
        print("总结果: FAIL", _fails)
        sys.exit(1)
    print("总结果: ALL PASS")
