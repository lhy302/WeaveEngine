# -*- coding: utf-8 -*-
# physics_glue.py — 基座 ↔ physics.dll 接线层 (M4, 2026-10-02)

import ctypes
import os
import sys
import threading
_HERE = os.path.dirname(os.path.abspath(__file__))
_CC = os.path.join(_HERE, 'core_components')
if _CC not in sys.path: sys.path.insert(0, _CC)
if _HERE not in sys.path: sys.path.insert(0, _HERE)
LOCK = threading.Lock()
_STATE = {'tried': False, 'handle': None, 'error': None}

def handle():
    """惰性组装并返回 physics 句柄; 失败硬 raise (官方件不兜底)。

    ★B4 退役 (2026-10-16): 删 LOOM_NO_PHYSICS_DLL 整体禁用门 + 静默降级。
    physics 是官方组件, 唯一路径; 缺失/加载失败 = 引擎缺陷, 硬 raise
    (与 B1/B2/B3 同纪律, 见 docs/design/逃生门退役设计.md §6)。
    """
    h = _STATE['handle']
    if h is not None and getattr(h, 'is_live', False): return h
    with LOCK:
        h = _STATE['handle']
        if h is not None and getattr(h, 'is_live', False): return h
        import module_registry as mr
        asm = mr.assemble(persist=False)
        h = asm.get('physics')          # 拿不到硬抛 ModuleNotAvailable
        _STATE['handle'] = h
        _STATE['tried'] = True
        _STATE['error'] = None
        return h
def pre_step(lin_vel, ang_vel, is_dynamic, use_gravity, is_active, friction, rolling_fric, gravity_y, dt):
    h = handle()
    import numpy as np
    n = int(lin_vel.shape[0])
    if n == 0:
        return 0
    pd = ctypes.POINTER(ctypes.c_double)
    pu8 = ctypes.POINTER(ctypes.c_uint8)
    fn = h.get_fn('loom_physics_pre_step', ctypes.c_int32, [pd, pd, pu8, pu8, pu8, pd, pd, ctypes.c_double, ctypes.c_double, ctypes.c_int64])
    rc = int(fn(lin_vel.ctypes.data_as(pd), ang_vel.ctypes.data_as(pd), is_dynamic.ctypes.data_as(pu8), use_gravity.ctypes.data_as(pu8), is_active.ctypes.data_as(pu8), friction.ctypes.data_as(pd), rolling_fric.ctypes.data_as(pd), ctypes.c_double(gravity_y), ctypes.c_double(dt), ctypes.c_int64(n)))
    if rc != 0:
        raise RuntimeError('loom_physics_pre_step 失败 rc=%d' % rc)
    return rc


def post_step(lin_vel, ang_vel, is_active):
    h = handle()
    import numpy as np
    n = int(lin_vel.shape[0])
    if n == 0:
        return 0
    pd = ctypes.POINTER(ctypes.c_double)
    pu8 = ctypes.POINTER(ctypes.c_uint8)
    fn = h.get_fn('loom_physics_post_step', ctypes.c_int32, [pd, pd, pu8, ctypes.c_int64])
    rc = int(fn(lin_vel.ctypes.data_as(pd), ang_vel.ctypes.data_as(pd), is_active.ctypes.data_as(pu8), ctypes.c_int64(n)))
    if rc != 0:
        raise RuntimeError('loom_physics_post_step 失败 rc=%d' % rc)
    return rc


def substep_loop(lin_vel, ang_vel, is_dynamic, use_gravity, is_active, friction, rolling_fric, gravity_y, sub_dt, num_substeps, step_cb=None, user_ctx=None):
    h = handle()
    import numpy as np
    n = int(lin_vel.shape[0])
    if n == 0 or num_substeps <= 0:
        return 0
    pd = ctypes.POINTER(ctypes.c_double)
    pu8 = ctypes.POINTER(ctypes.c_uint8)
    cb_type = ctypes.CFUNCTYPE(ctypes.c_int32, ctypes.c_double, ctypes.c_void_p)
    c_cb = cb_type(step_cb) if step_cb is not None else cb_type()
    fn = h.get_fn('loom_physics_substep_loop', ctypes.c_int32, [pd, pd, pu8, pu8, pu8, pd, pd, ctypes.c_double, ctypes.c_double, ctypes.c_int32, ctypes.c_int64, cb_type, ctypes.c_void_p])
    rc = int(fn(lin_vel.ctypes.data_as(pd), ang_vel.ctypes.data_as(pd), is_dynamic.ctypes.data_as(pu8), use_gravity.ctypes.data_as(pu8), is_active.ctypes.data_as(pu8), friction.ctypes.data_as(pd), rolling_fric.ctypes.data_as(pd), ctypes.c_double(gravity_y), ctypes.c_double(sub_dt), ctypes.c_int32(num_substeps), ctypes.c_int64(n), c_cb, user_ctx))
    if rc != 0:
        raise RuntimeError('loom_physics_substep_loop 失败 rc=%d' % rc)
    return rc


def status():
    h = handle()
    return 'physics: %s v%s official=%d' % (h.module_id, h.version, h.official)
