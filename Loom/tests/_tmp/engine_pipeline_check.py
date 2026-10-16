# -*- coding: utf-8 -*-
"""engine_pipeline_check.py — engine.py ↔ pipeline.dll 接线验证 (M2a-3)

与 pipeline_base_check.py 的分工:
  · pipeline_base_check.py: 经注册表句柄直接调 DLL, 对拍 Python 基准 (数值等价)
  · 本文件: 直接加载 **engine.py 的真实方法体**, 验证接线后的路径选择与数值等价:
      _pipeline_light_vps  (DLL 分支)
      _compute_light_vps   (DLL 优先 / Python 回退)

方法体用 AST 从 engine.py 抽出后 exec 到一个临时类上 (不 import engine, 免
moderngl/pygame 图形栈依赖) —— 测的是生产代码本身, 不是复刻。
"""
import ast
import hashlib
import math
import os
import sys
import time

BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, BASE)
sys.path.insert(0, os.path.join(BASE, 'core_components'))
os.chdir(BASE)

import numpy as np
import matlib
import module_registry as mr
import pipeline_glue as pg

REG = os.path.join(BASE, 'core_components', 'registry.json')
# ★预存缺陷修复 (2026-10-16): 6 个方法已随 mixin 拆分从 engine.py 移到
# loom_lighting.py 的 LightingMixin; 探针抽取路径同步。
ENGINE_PY = os.path.join(BASE, 'loom_lighting.py')
results = []


def check(name, ok, detail=''):
    results.append(bool(ok))
    print('%s %s %s' % ('PASS' if ok else 'FAILED', name, detail))


def sha(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for c in iter(lambda: f.read(1 << 20), b''):
            h.update(c)
    return h.hexdigest()


class P3(object):
    def __init__(self, x, y, z):
        self.x, self.y, self.z = float(x), float(y), float(z)


class Light(object):
    """engine.Light 的最小鸭子类型。"""

    def __init__(self, kind='directional', shadow=True, mode='full',
                 position=(0.0, 10.0, 0.0), direction=(0.0, -1.0, 0.0),
                 up=(0.0, 1.0, 0.0), size=1.0, guid=None):
        self.kind, self.shadow, self.mode = kind, shadow, mode
        self.position, self.direction = P3(*position), P3(*direction)
        self._up, self.size = P3(*up), size
        self.guid = guid or ('g%d' % id(self))

    def up_vector(self):
        return self._up


def load_engine_methods():
    """从 loom_lighting.py 抽出 LightingMixin 的六个方法, 绑到一个空类上。"""
    src = open(ENGINE_PY, encoding='utf-8').read()
    tree = ast.parse(src)
    want = ('_dir_light_vp', '_point_light_vp', '_pipeline_light_vps',
            '_compute_light_vps', '_model_aabbs_par', '_scene_light_bounds_par')
    found = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == 'LightingMixin':
            for item in node.body:
                if isinstance(item, ast.FunctionDef) and item.name in want:
                    found[item.name] = ast.get_source_segment(src, item)
    missing = [w for w in want if w not in found]
    if missing:
        raise RuntimeError('engine.py 缺少方法: %r' % missing)
    ns = {'np': np, 'math': math, 'os': os,
          'mat4_ortho': matlib.mat4_ortho,
          'mat4_view_forward': matlib.mat4_view_forward,
          'mat4_perspective': matlib.mat4_perspective}
    cls = type('EngineStub', (object,), {})
    static_names = ('_scene_light_bounds_par',)      # engine 内声明为 staticmethod
    for name, seg in found.items():
        exec(compile(ast.parse(seg), ENGINE_PY, 'exec'), ns)
        if name in static_names:
            setattr(cls, name, staticmethod(ns[name]))
        else:
            setattr(cls, name, ns[name])
    return cls


class Stub(object):
    def __init__(self, cls, lights, n):
        self.__class__ = cls
        self.lights = lights
        self.models = [type('M', (), {'visible': True})() for _ in range(n)]
        self._frame_world = None
        self._aabb_shadow_rows = None
        self._aabb_shadow_gen = None
        self._light_vps = {}
        self._stage_times = {}
        self._frame_pool = None
        self._struct_gen = 0
        self._shadow_point_far = 1.0e4      # engine 默认 (点光投影 far 平面)
        # ★B2 后 (2026-10-16): _compute_light_vps 的编辑态静止缓存分支需要
        # _light_vps_cache_sig; 本探针不测缓存, 用播放态跳过该分支, 直走 pipeline。
        self.is_playing = True

    def _profile(self, name, fn):
        return fn()


def rows_to_aabbs(rows):
    return [((rows[i, 0], rows[i, 1], rows[i, 2]),
             (rows[i, 3], rows[i, 4], rows[i, 5])) for i in range(rows.shape[0])]


def make_case(rng, n, tag):
    mn = rng.uniform(-30, 30, size=(n, 3))
    ext = rng.uniform(0.01, 8.0, size=(n, 3))
    rows = np.ascontiguousarray(np.hstack([mn, mn + ext]), dtype=np.float64)
    lights = [
        Light('directional', True, 'full',
              position=tuple(rng.uniform(-20, 20, 3)),
              direction=tuple(rng.uniform(-1, 1, 3)),
              up=tuple(rng.uniform(-0.5, 0.5, 3) + np.array([0, 1, 0])),
              guid='d_' + tag),
        Light('point', True, 'full',
              position=tuple(rng.uniform(-20, 20, 3)), guid='p_' + tag),
        Light('directional', True, 'beam',
              position=tuple(rng.uniform(-20, 20, 3)),
              direction=tuple(rng.uniform(-1, 1, 3)), size=2.5, guid='b_' + tag),
    ]
    return rows, lights


def main():
    print('=== engine_pipeline_check (M2a-3 接线) ===')
    reg0 = sha(REG)
    cls = load_engine_methods()
    check('A engine.py 方法抽取 (_pipeline_light_vps/_compute_light_vps 等)', True,
          '5 个方法已加载')

    st = pg.status()
    check('B pipeline_glue 可用', 'unavailable' not in st and 'disabled' not in st, st)

    rng = np.random.default_rng(20260908)
    # ★B2 退役 (2026-10-16): Python 回退段已删, 本段只验证 DLL 路径产出非空。
    # 数值正确性由 pipeline_val_check.py (C vs numpy 基准) 覆盖。
    ok = True
    for trial, n in enumerate((1, 7, 64, 501)):
        rows, lights = make_case(rng, n, str(trial))
        aabbs = rows_to_aabbs(rows)
        eng = Stub(cls, lights, n)
        eng._aabb_shadow_rows = rows
        eng._aabb_shadow_gen = (id(aabbs), len(aabbs))
        eng._aabbs = aabbs
        dll_vps = eng._compute_light_vps(aabbs)
        if not dll_vps:
            ok = False
            print('   [n=%d] DLL 路径产出空' % n)
    check('C DLL 路径产出非空 (n=1/7/64/501)', ok, 'ok=%r' % ok)

    # D DLL 路径确实被走到 (而不是静默回退)
    rows, lights = make_case(rng, 64, 'd')
    aabbs = rows_to_aabbs(rows)
    eng = Stub(cls, lights, 64)
    eng._aabb_shadow_rows = rows
    eng._aabb_shadow_gen = (id(aabbs), len(aabbs))
    hit = eng._pipeline_light_vps(aabbs, {})
    check('D _pipeline_light_vps 命中 (DLL 路径真实生效)', hit is True, 'hit=%r' % hit)

    # E 行表缺失但可现算 (aabbs=None 且 full 平行光)
    class _Pt(object):
        def __init__(self, t):
            self.x, self.y, self.z = float(t[0]), float(t[1]), float(t[2])
    eng2 = Stub(cls, lights, 64)

    def fake_aabbs(models, fw=None, visible_only=True):
        # engine._model_aabbs_par 的真实返回形态: 每项 = (min Point3D, max Point3D)
        return [(_Pt(r[0]), _Pt(r[1])) for r in aabbs]
    eng2._model_aabbs_par = fake_aabbs
    hit3 = eng2._pipeline_light_vps(None, {})
    check('E aabbs=None → 现算行表后仍走 DLL', hit3 is True, 'hit=%r' % hit3)

    # F 性能口径 (仅报数)
    n = 501
    rows, lights = make_case(rng, n, 'perf')
    aabbs = rows_to_aabbs(rows)
    eng = Stub(cls, lights, n)
    eng._aabb_shadow_rows = rows
    eng._aabb_shadow_gen = (id(aabbs), len(aabbs))

    # ★B2 退役 (2026-10-16): Python 路径已删, 只报 DLL 单档性能。
    ts = []
    for _ in range(30):
        t0 = time.perf_counter()
        eng._compute_light_vps(aabbs)
        ts.append((time.perf_counter() - t0) * 1000.0)
    ts.sort()
    ms_dll = ts[len(ts) // 2]
    print('PERF light_vps n=%d 3光源: DLL median=%.3f ms' % (n, ms_dll))
    check('F 性能口径已采集', ms_dll > 0, 'DLL=%.3fms' % ms_dll)

    check('G registry.json 哈希未变', sha(REG) == reg0, reg0[:16])
    pg.shutdown()

    bad = results.count(False)
    print('--- %d 项: PASS %d / FAILED %d ---'
          % (len(results), results.count(True), bad))
    print('ALL PASS' if bad == 0 else 'FAILED %d 项' % bad)
    return 0 if bad == 0 else 1


if __name__ == '__main__':
    sys.exit(main())
