# -*- coding: utf-8 -*-
"""prof_scripts3.py — batch_rotate 返回值与回退路径验证 (2026-10-14)"""
import os, sys, time
BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, BASE); os.chdir(BASE)
sys.argv[0] = os.path.join(BASE, 'Loom.py')
import numpy as np
import script_glue as _sg

def main():
    h = _sg.handle()
    print("handle:", h, "is_live:", getattr(h,'is_live',None))
    print("_STATE error:", _sg._STATE.get('error'))
    n = 100
    rb = np.zeros((n,3)); sb = np.zeros((n,3)); ob = np.zeros((n,3))
    sb[:,1] = 90.0
    out = _sg.batch_rotate(rb, sb, 1.0/30.0, out_rot=ob)
    print("batch_rotate 返回:", type(out), "None?" , out is None)
    print("_STATE error after:", _sg._STATE.get('error'))
    if out is not None:
        print("out[0]:", out[0])
    # 计时 raw C 调用（绕过 wrapper 的 ascontiguousarray/get_fn）
    import ctypes
    pd = ctypes.POINTER(ctypes.c_double)
    try:
        fn = h.get_fn('loom_script_batch_rotate', ctypes.c_int32, [pd,pd,ctypes.c_double,ctypes.c_int64,pd])
        print("get_fn OK:", fn)
        t0=time.perf_counter()
        for _ in range(300):
            rc = int(fn(rb.ctypes.data_as(pd), sb.ctypes.data_as(pd), ctypes.c_double(1/30), ctypes.c_int64(n), ob.ctypes.data_as(pd)))
        print("raw fn call=%.4f ms rc=%d" % ((time.perf_counter()-t0)/300*1000, rc))
    except Exception as e:
        print("get_fn/raw FAIL:", repr(e))
    # get_fn 单独计时
    t0=time.perf_counter()
    for _ in range(300):
        h.get_fn('loom_script_batch_rotate', ctypes.c_int32, [pd,pd,ctypes.c_double,ctypes.c_int64,pd])
    print("get_fn x1 =%.4f ms" % ((time.perf_counter()-t0)/300*1000))
    _sg.shutdown() if hasattr(_sg,'shutdown') else None

if __name__ == '__main__':
    main()
