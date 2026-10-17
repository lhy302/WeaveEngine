# -*- coding: utf-8 -*-
"""挂父行为探针 (2026-08-16): 验证"挂父后物体乱飞"是不是正常/自主运动.

回答两个问题:
  A) 挂父那一下, 子物体世界位置会不会"跳"?  -> 会, 当父有非单位变换时.
  B) 不加脚本/刚体/动画, 子物体会不会自己持续动? -> 不会 (纯渲染每帧只读变换).
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
import numpy as np
import engine as E
from mesh import create_cube

eng = E.GLEngine.__new__(E.GLEngine)

def mk(name, pos, rot=(0, 0, 0)):
    return E.GameObject(create_cube(1.5), E.Point3D(*pos), E.Point3D(*rot), name=name)

def wpos(m):
    p = eng.world_position(m)
    return (round(p.x, 4), round(p.y, 4), round(p.z, 4))

print("== A) 挂父瞬间子物体世界位置是否跳变 ==")
# A1: 父在原点无旋转 -> 应该不跳
pa = mk("父A", (0, 0, 0)); ch = mk("子A", (5, 0, 0))
eng.models = [pa, ch]
print("A1 挂前 子世界 =", wpos(ch))
eng.set_parent(ch, pa)
print("A1 挂后 子世界 =", wpos(ch), "  (父原点无旋转: 期望不变)")

# A2: 父在原点但带旋转 -> 修复后不跳 (保世界: 局部被换算, 世界位置不变)
pa2 = mk("父B", (0, 0, 0), (0, np.pi / 2, 0)); ch2 = mk("子B", (5, 0, 0))
eng.models = [pa2, ch2]
print("A2 挂前 子世界 =", wpos(ch2), "  父旋转 y=90°")
eng.set_parent(ch2, pa2)
print("A2 挂后 子世界 =", wpos(ch2), "  (修复后: 期望保持 (5,0,0), 局部被换算)")

# A3: 父在远处无旋转 -> 修复后不跳 (局部被换算成 5-10=-5)
pa3 = mk("父C", (10, 0, 0)); ch3 = mk("子C", (5, 0, 0))
eng.models = [pa3, ch3]
print("A3 挂前 子世界 =", wpos(ch3))
eng.set_parent(ch3, pa3)
print("A3 挂后 子世界 =", wpos(ch3), "  (修复后: 期望保持 (5,0,0), 局部变 -5)")

# A4: 父在原点无旋转, 父后拉远父 -> 子跟着走 (正确父子行为)
pa4 = mk("父D", (0, 0, 0)); ch4 = mk("子D", (5, 0, 0))
eng.models = [pa4, ch4]
eng.set_parent(ch4, pa4)
pa4.position = E.Point3D(20, 0, 0)
print("A4 挂父后拖父到(20,0,0): 子世界 =", wpos(ch4), "  (子应跟着到25 -> 正确)")

print()
print("== B) 不加脚本/刚体/动画, 子物体会不会自己动 ==")
pa5 = mk("父E", (0, 0, 0)); ch5 = mk("子E", (5, 0, 0))
eng.models = [pa5, ch5]
eng.set_parent(ch5, pa5)
before = (ch5.position.x, ch5.position.y, ch5.position.z,
          ch5.rotation.x, ch5.rotation.y, ch5.rotation.z,
          pa5.position.x, pa5.position.y, pa5.position.z)
moved = False
for _ in range(120):            # 模拟 120 帧纯渲染 (只读变换, 无 update_scripts/physics)
    eng.model_world_matrix(ch5)  # 渲染路径每帧都会算世界矩阵
    now = (ch5.position.x, ch5.position.y, ch5.position.z,
           ch5.rotation.x, ch5.rotation.y, ch5.rotation.z,
           pa5.position.x, pa5.position.y, pa5.position.z)
    if now != before:
        moved = True
        break
print("B 120 帧纯渲染后子物体字段是否变化:", "变化了(自主运动!)" if moved else "无变化(不会自己动)")
print("   子世界位置:", wpos(ch5))
print()
print("结论: 挂父瞬间世界位置会跳(父有非单位变换时), 但无脚本不会自主持续运动。")
