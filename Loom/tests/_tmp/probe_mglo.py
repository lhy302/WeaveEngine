# -*- coding: utf-8 -*-
import os, sys
BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, BASE); os.chdir(BASE)
import moderngl, numpy as np
ctx = moderngl.create_standalone_context()
print("=== mglo 完整方法列表 ===")
print([a for a in dir(ctx.mglo) if not a.startswith('_')])
print("=== 是否有 compress 相关 ===")
print([a for a in dir(ctx.mglo) if 'compress' in a.lower() or 'tex' in a.lower()])
ctx.release()
print("完成")
