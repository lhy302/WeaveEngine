# -*- coding: utf-8 -*-
import culverin as cv
print('=== PhysicsWorld 全部方法 ===')
for name in dir(cv.PhysicsWorld):
    if name.startswith('_'):
        continue
    print(' ', name)
print()
print('=== 含 ray/cast/hit 关键词的方法 ===')
hits = [n for n in dir(cv.PhysicsWorld) if not n.startswith('_')
        and ('ray' in n.lower() or 'cast' in n.lower() or 'hit' in n.lower())]
print(hits)
print()
print('=== culverin 包路径 ===')
import os
print(os.path.dirname(cv.__file__))
print()
print('=== 包内文件清单 ===')
for f in sorted(os.listdir(os.path.dirname(cv.__file__))):
    print(' ', f)
