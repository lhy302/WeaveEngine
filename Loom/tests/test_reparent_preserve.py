# -*- coding: utf-8 -*-
"""2026-08-16: set_parent 保世界 (Unity 挂父语义) 回归测试.

修复: 挂父/脱父那一下, 子物体(及整棵子树)的世界位置/旋转/缩放保持不变,
局部变换被换算到新父空间. 之前 set_parent 只改父指针, 父带位移/旋转/缩放时
子物体会瞬间跳到错误位置 ("乱飞"). 相关: 问题记录 B4.
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import math
import uuid
import numpy as np
import engine as E
import undo as U
from mesh import create_cube

E.GLEngine._build_gpu = lambda self, m: None   # 无头: add_model 不碰 GL (同 test_sceneio)

eng = E.GLEngine.__new__(E.GLEngine)
eng.undo = U.UndoManager()
eng.materials = []          # sceneio 序列化需要
eng.lights = []
eng.cameras = []
eng.active_camera = None
eng.current_model_index = 0

def mk(name, pos, rot=(0, 0, 0), scale=(1, 1, 1)):
    m = E.GameObject(create_cube(1.5), E.Point3D(*pos), E.Point3D(*rot), name=name, scale=E.Point3D(*scale))
    m.guid = uuid.uuid4().hex        # 序列化父链需 guid (add_model 会自动给)
    return m

def wpos(m):
    p = eng.world_position(m)
    return (round(p.x, 6), round(p.y, 6), round(p.z, 6))

def v3(t):
    return tuple(round(float(v), 6) for v in t)

ok = True
def check(label, cond, detail=""):
    global ok
    print(("PASS " if cond else "FAIL ") + label + ("  " + detail if detail else ""))
    if not cond: ok = False

# —— 1) 挂到带位移的父: 世界位置不变, 局部被换算 ——
pa = mk("父位移", (10, 0, 0)); ch = mk("子", (5, 0, 0))
eng.models = [pa, ch]
eng.set_parent(ch, pa)
check("1 挂父(父位移10)后子世界仍 (5,0,0)", wpos(ch) == (5, 0, 0), str(wpos(ch)))
check("1 子局部换算到父空间 (-5,0,0)",
      v3((ch.position.x, ch.position.y, ch.position.z)) == (-5, 0, 0),
      str(v3((ch.position.x, ch.position.y, ch.position.z))))
check("1 子世界缩放不变 (1,1,1)", v3(eng.world_scale(ch)) == (1, 1, 1))

# —— 2) 挂到带旋转的父: 世界位置/旋转不变 ——
pa2 = mk("父旋", (0, 0, 0), (0, math.pi / 2, 0)); ch2 = mk("子旋", (5, 0, 0))
eng.models = [pa2, ch2]
R_world_before = eng.world_rotation_matrix(ch2)
eng.set_parent(ch2, pa2)
check("2 挂父(父转90°)后子世界仍 (5,0,0)", wpos(ch2) == (5, 0, 0), str(wpos(ch2)))
Rw = eng.world_rotation_matrix(ch2)
err = float(np.max(np.abs(Rw - R_world_before)))
check("2 子世界旋转矩阵不变 (err<1e-9)", err < 1e-9, "err=%.1e" % err)

# —— 3) 挂到带缩放的父: 世界缩放不变 ——
pa3 = mk("父缩放", (0, 0, 0), scale=(2, 2, 2)); ch3 = mk("子缩放", (0, 0, 0))
eng.models = [pa3, ch3]
eng.set_parent(ch3, pa3)
check("3 子世界缩放不变 (1,1,1)", v3(eng.world_scale(ch3)) == (1, 1, 1),
      str(v3(eng.world_scale(ch3))))
check("3 子局部缩放换算 (0.5,0.5,0.5)",
      v3((ch3.scale[0], ch3.scale[1], ch3.scale[2])) == (0.5, 0.5, 0.5),
      str(v3((ch3.scale[0], ch3.scale[1], ch3.scale[2]))))

# —— 4) 脱父: 世界不变, 局部=世界 ——
pa4 = mk("父脱", (3, 0, 0)); ch4 = mk("子脱", (5, 0, 0))
eng.models = [pa4, ch4]
eng.set_parent(ch4, pa4)
eng.set_parent(ch4, None)
check("4 脱父后子世界仍 (5,0,0)", wpos(ch4) == (5, 0, 0), str(wpos(ch4)))
check("4 脱父后局部=世界 (5,0,0)",
      v3((ch4.position.x, ch4.position.y, ch4.position.z)) == (5, 0, 0),
      str(v3((ch4.position.x, ch4.position.y, ch4.position.z))))

# —— 5) 子树: 孙的世界也保持不变 ——
pa5 = mk("父5", (10, 0, 0)); ch5 = mk("子5", (5, 0, 0)); gc5 = mk("孙5", (7, 0, 0))
eng.models = [pa5, ch5, gc5]
eng.set_parent(gc5, ch5)
eng.set_parent(ch5, pa5)
check("5 挂父后子世界 (5,0,0)", wpos(ch5) == (5, 0, 0), str(wpos(ch5)))
check("5 孙世界 (7,0,0)", wpos(gc5) == (7, 0, 0), str(wpos(gc5)))

# —— 6) ReparentCommand 撤销/重做 全程世界不变 ——
pa6 = mk("父6", (10, 0, 0)); ch6 = mk("子6", (5, 0, 0))
eng.models = [pa6, ch6]
eng.undo.push(U.ReparentCommand("挂父", eng, ch6, None, pa6))
check("6 挂父后世界 (5,0,0)", wpos(ch6) == (5, 0, 0), str(wpos(ch6)))
eng.undo.undo()
check("6 撤销挂父后世界仍 (5,0,0)", wpos(ch6) == (5, 0, 0), str(wpos(ch6)))
eng.undo.redo()
check("6 重做挂父后世界仍 (5,0,0)", wpos(ch6) == (5, 0, 0), str(wpos(ch6)))

# —— 7) set_parent(preserve_world=False): 局部原样 (复制命令/播放退出精确还原路径) ——
pa7 = mk("父7", (10, 0, 0)); ch7 = mk("子7", (5, 0, 0))
eng.models = [pa7, ch7]
eng.set_parent(ch7, pa7)                          # 先保世界挂父 -> 局部 (-5,0,0)
eng.set_parent(ch7, None)                         # 保世界脱父 -> 局部 (5,0,0)
ch7.position = E.Point3D(5.8, 0, 0)               # 模拟复制: 局部值已按父空间备好
eng.set_parent(ch7, pa7, preserve_world=False)    # 复制路径: 不换算, 局部原样
check("7 preserve_world=False 局部原样 5.8", abs(ch7.position.x - 5.8) < 1e-9,
      str(ch7.position.x))
check("7 世界 x = 10+5.8 = 15.8", abs(eng.world_position(ch7).x - 15.8) < 1e-9,
      str(round(eng.world_position(ch7).x, 4)))
# 对照: 同场景保世界挂父 -> 局部被换算 (-5), 世界仍 (5)
ch7b = mk("子7b", (5, 0, 0)); eng.models.append(ch7b)
eng.set_parent(ch7b, pa7)
check("7 对照: 保世界挂父局部换算 (-5)", abs(ch7b.position.x + 5.0) < 1e-9,
      str(ch7b.position.x))

# —— 8) 防环仍生效 (保世界换算不影响) ——
pa8 = mk("父8", (0, 0, 0)); ch8 = mk("子8", (2, 0, 0)); gc8 = mk("孙8", (1, 0, 0))
eng.models = [pa8, ch8, gc8]
eng.set_parent(ch8, pa8)
eng.set_parent(gc8, ch8)
eng.set_parent(pa8, gc8)
check("8 防环: 祖不能设为孙子", pa8.parent is None)
eng.set_parent(ch8, ch8)
check("8 防环: 不能设自己为父", ch8.parent is pa8)

# —— 9) 场景 round-trip 后子世界仍保 (经 sceneio 直接 m.parent=, 不受 set_parent 影响) ——
pa9 = mk("父9", (10, 0, 0)); ch9 = mk("子9", (5, 0, 0))
eng.models = [pa9, ch9]   # 清掉前 8 节的测试残留, 只序列化这一组
eng.set_parent(ch9, pa9)
import sceneio as S
d = S.scene_to_dict(eng)
eng9 = E.GLEngine.__new__(E.GLEngine)
eng9.models = []; eng9.materials = []; eng9.lights = []
eng9.cameras = []; eng9.active_camera = None; eng9.current_model_index = 0
S.scene_from_dict(eng9, d)
g9 = {m.name: m for m in eng9.models}
check("9 序列化/回读后子世界仍 (5,0,0)", wpos(g9["子9"]) == (5, 0, 0),
      str(wpos(g9["子9"])))

print()
print("总结果:", "ALL PASS ✅" if ok else "有 FAIL ❌")
