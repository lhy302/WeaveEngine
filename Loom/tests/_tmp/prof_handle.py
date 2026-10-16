# -*- coding: utf-8 -*-
"""prof_handle.py — handle() 重装配验证 (2026-10-14)"""
import os, sys, time
BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, BASE); os.chdir(BASE)
sys.argv[0] = os.path.join(BASE, 'Loom.py')
import script_glue as _sg

def main():
    h = _sg.handle()
    print("type(h):", type(h))
    print("h.is_live:", getattr(h, 'is_live', 'MISSING'))
    print("dir(h) sample:", [a for a in dir(h) if not a.startswith('__')][:20])
    # handle() 连续两次，看是否同一对象
    h1 = _sg.handle(); h2 = _sg.handle()
    print("handle() 两次 same object?", h1 is h2)
    # 计时 handle()
    N=100
    t0=time.perf_counter()
    for _ in range(N): _sg.handle()
    print("handle() x1 = %.4f ms" % ((time.perf_counter()-t0)/N*1000))
    # 计时 mr.assemble
    import module_registry as mr
    N=20
    t0=time.perf_counter()
    for _ in range(N): mr.assemble(persist=False)
    print("mr.assemble x1 = %.4f ms" % ((time.perf_counter()-t0)/N*1000))

if __name__ == '__main__':
    main()
