# -*- coding: utf-8 -*-
"""M29 光照遮挡 (阴影) 无头测试:
mat4_ortho / mat4_view_forward 数值, LightState 新字段, light_snapshot+undo,
sceneio v8 序列化与 v7 迁移补默认."""
import sys, os, math
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import numpy as np
import engine as E
import sceneio as S
import undo as U

ok = True
def check(label, cond, detail=""):
    global ok
    print(("PASS " if cond else "FAIL ") + label + ("  " + detail if detail else ""))
    if not cond:
        ok = False

# ---- 1) mat4_ortho: 正交投影数值 (near->0 far->1, w=1) ----
O = E.mat4_ortho(np, -2, 2, -3, 3, 0, 10)
c = np.array([2.0, 3.0, 10.0, 1.0]) @ O
check("ortho 右上角 -> (1,1,1,w=1)",
      np.allclose(c[:3], [1, 1, 1]) and c[3] == 1.0, str(c))
c2 = np.array([-2.0, -3.0, 0.0, 1.0]) @ O
check("ortho 左下角 -> (-1,-1,0,1) (left->-1 right->+1)",
      np.allclose(c2[:3], [-1, -1, 0]) and c2[3] == 1.0, str(c2))
c3 = np.array([0.0, 0.0, 5.0, 1.0]) @ O
check("ortho 深度线性 (中段 z -> clip 0.5)", abs(c3[2] - 0.5) < 1e-9, str(c3[2]))

# ---- 2) mat4_view_forward: +z_view = forward (光源视图) ----
V = E.mat4_view_forward(np, (0, 5, 0), (0, -1, 0), (0, 0, 1))
p = np.array([0.0, 0.0, 0.0, 1.0]) @ V
check("view_forward 原点在光源(0,5,0)下 -> z_view=5", abs(p[2] - 5.0) < 1e-9, str(p[2]))
q = np.array([1.0, 5.0, 0.0, 1.0]) @ V
check("view_forward 同深度点(光所在面) -> z_view=0", abs(q[2]) < 1e-9, str(q[2]))

# ---- 3) LightState 新字段默认值 ----
l = E.LightState('directional')
check("LightState 默认 mode=full/shape=circle/size=5/shadow=True",
      l.mode == 'full' and l.shape == 'circle' and l.shadow is True and l.size == 5.0)
lp = E.LightState('point')
check("点光源同样有默认字段", lp.shadow is True and lp.mode == 'full')

# ---- 4) add_light 透传新字段 ----
e = E.GLEngine.__new__(E.GLEngine)
e.lights = []
l2 = e.add_light('directional', mode='beam', shape='rect', size=3.0, shadow=False)
check("add_light 透传 mode/shape/size/shadow",
      l2.mode == 'beam' and l2.shape == 'rect' and l2.size == 3.0 and l2.shadow is False)

# ---- 5) light_snapshot / apply_light_snapshot 含新字段 (undo 可撤销) ----
snap = U.light_snapshot(l2)
check("snapshot 含 mode/shape/size/shadow",
      snap['mode'] == 'beam' and snap['shape'] == 'rect'
      and snap['size'] == 3.0 and snap['shadow'] is False)
l3 = E.LightState('directional')
U.apply_light_snapshot(l3, snap)
check("apply_snapshot 还原新字段", l3.mode == 'beam' and l3.shape == 'rect'
      and l3.size == 3.0 and l3.shadow is False)

# ---- 6) sceneio v8: 序列化 + v7 迁移 ----
d = S._emit_light(l2)
check("_emit_light 含 mode/shape/size/shadow",
      d['mode'] == 'beam' and d['shape'] == 'rect'
      and d['size'] == 3.0 and d['shadow'] is False)
old = {"version": 7, "camera": {}, "lights": [{"kind": "directional"}], "objects": []}
mig = S.migrate(old)
lt = mig["lights"][0]
check("v7 迁移补 mode/shape/size/shadow 默认",
      lt['mode'] == 'full' and lt['shape'] == 'circle'
      and lt['size'] == 5.0 and lt['shadow'] is True)
check("迁移后 version=当前", mig["version"] == S.SCENE_VERSION)

# ---- 7) M30: 平行光方向 = 3 角度参数 (朝向/俯仰/倾斜) ----
def dir3(az, el=0.0, roll=0.0):
    return E.LightState('directional', azimuth=az, elevation=el, roll=roll)

def near(a, b, eps=1e-6):
    return abs(a - b) < eps

lA = dir3(0, 0)
check("M30 默认 (0,0): 方向朝 +z 前", near(lA.direction.x, 0) and near(lA.direction.y, 0)
      and near(lA.direction.z, 1), str(lA.direction))
check("M30 az=90: 方向朝 +x", near(dir3(90).direction.x, 1)
      and near(dir3(90).direction.z, 0), str(dir3(90).direction))
check("M30 el=+90: 方向朝上 +y", near(dir3(0, 90).direction.y, 1)
      and near(dir3(0, 90).direction.z, 0), str(dir3(0, 90).direction))
check("M30 el=-90: 方向朝下 -y", near(dir3(0, -90).direction.y, -1)
      and near(dir3(0, -90).direction.z, 0), str(dir3(0, -90).direction))
lB = dir3(370, 0)                       # 环绕: 370 -> 10
check("M30 朝向环绕 370 -> 10", near(lB.azimuth, 10), str(lB.azimuth))
lC = dir3(0, 190)                       # 俯仰环绕 190 -> -170
check("M30 俯仰环绕 190 -> -170", near(lC.elevation, -170), str(lC.elevation))
# 方向向量反算角度 (旧 direction 兼容)
lD = E.LightState('directional', direction=(-1, -1, 1))
back = lD.direction
n = math.sqrt(3)
check("M30 direction 反算再回读 (归一化)", near(back.x, -1 / n) and near(back.y, -1 / n)
      and near(back.z, 1 / n), str(back))
check("M30 el=90 竖直: 方向朝上 (az 不影响)", near(dir3(123, 90).direction.y, 1)
      and near(dir3(123, 90).direction.x, 0, 1e-6)
      and near(dir3(123, 90).azimuth, 123))   # 显式给的 az 保留, 不退化
# roll / up_vector: roll=0 上方参考 ≈ 世界上方投影 (水平光 -> +y)
u0 = dir3(0, 0, 0).up_vector()
check("M30 roll=0 水平光 up = 世界上方 +y", near(u0.x, 0) and near(u0.y, 1)
      and near(u0.z, 0), str(u0))
lR = dir3(0, 0, 90)                      # 倾斜 90°
uR = lR.up_vector()
check("M30 roll=90 up 绕方向线转 90 (朝 +x)", near(uR.x, 1) and near(uR.y, 0)
      and near(uR.z, 0, 1e-5), str(uR))
check("M30 up 恒垂直于方向线", near(u0.x * 0 + u0.y * 0 + u0.z * 1, 0))
# sceneio 序列化含 3 角度
d30 = S._emit_light(dir3(30, 20, 10))
check("M30 _emit_light 含 azimuth/elevation/roll",
      d30['azimuth'] == 30.0 and d30['elevation'] == 20.0 and d30['roll'] == 10.0,
      str(d30))

print()
print("总结果:", "ALL PASS ✅" if ok else "有 FAIL ❌")
sys.exit(0 if ok else 1)
