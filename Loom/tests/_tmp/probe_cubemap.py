# -*- coding: utf-8 -*-
import os, sys
BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, BASE); os.chdir(BASE)
import moderngl, numpy as np
ctx = moderngl.create_standalone_context()
print("=== ctx.texture_cube 签名 ===")
import inspect
try:
    print(inspect.signature(ctx.texture_cube))
except Exception as e:
    print("签名取不到:", e)
print("=== 试创建 cubemap ===")
try:
    # 6 面, 每面 4x4
    cube = ctx.texture_cube((4,4), 4, dtype='f1')
    print("  texture_cube OK:", cube.size, "components=", cube.components)
    print("  cubemap 属性:", [a for a in dir(cube) if not a.startswith('_')])
    # 写单面
    face_data = np.zeros((4,4,4), dtype=np.uint8)
    cube.write(0, face_data.tobytes())   # face 0 = +X
    print("  write(face=0) OK")
    cube.build_mipmaps()
    print("  build_mipmaps OK, filter=", cube.filter)
    cube.release()
except Exception as e:
    import traceback; traceback.print_exc()
ctx.release()
print("完成")
