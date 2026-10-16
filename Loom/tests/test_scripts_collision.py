# -*- coding: utf-8 -*-
"""《未测试功能测试方向指南》A4(脚本×碰撞组合) + A7(多脚本边界)."""
import sys, os, math
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import engine as E
import scripts
from mesh import create_cube, create_plane

E.GLEngine._build_gpu = lambda self, m: None

def new_eng():
    e = E.GLEngine.__new__(E.GLEngine)
    e.models = []; e.materials = []; e.lights = []
    e.current_model_index = 0
    e.script_keys = {}
    e.actions = dict(E.DEFAULT_ACTIONS)   # M30b 输入动作层
    return e

def add(e, mesh, pos, **kw):
    return e.add_model(mesh, E.Point3D(*pos), E.Point3D(0, 0, 0), **kw)

ok = True
def check(label, cond, detail=""):
    global ok
    print(("PASS " if cond else "FAIL ") + label + ("  " + detail if detail else ""))
    if not cond: ok = False

# ============ A4 脚本 × 碰撞 组合 ============
# A4-1 WASD移动 挂到带碰撞体角色: 撞墙被挡不穿模
e = new_eng()
wall = add(e, create_cube(1.0), (0, 0, 5))            # AABB z[4.5,5.5]
hero = add(e, create_cube(1.0), (0, 0, 0))            # 半边长0.5
hero.add_script('wasd_move', {'speed': 3.0})
e.script_keys = {'w': True}
for _ in range(30):
    e.update_scripts(0.1)                              # 每帧 dz=+0.3
z = hero.position.z
check("A4 WASD撞墙: 被墙挡住不穿模 (z≤4.05)", 3.0 < z <= 4.05, f"z={z:.3f}")

# A4-2 脚本内 get_collisions 做触发器: 碰到别的物体改颜色
@scripts.register
class _Trigger(scripts.Script):
    script_id = '_test_trigger'
    name = '测试触发器'
    params = ()
    def update(self, dt):
        if self.engine.get_collisions(self.obj):
            self.obj.renderer.material.color = (1.0, 0.0, 0.0)

e2 = new_eng()
ta = add(e2, create_cube(1.0), (0, 0, 0))
tb = add(e2, create_cube(1.0), (0.4, 0, 0))           # 与 ta 重叠
ta.add_script('_test_trigger')
e2.update_scripts(0.05)
red = ta.renderer.material.color
check("A4 get_collisions 触发器: 碰撞改红", red is not None and red[0] > 0.9,
      str(red))
del scripts.SCRIPTS['_test_trigger']                  # 清理, 不污染选项

# A4-3 bounce 参数边界: rest=1.0 永弹 / rest=0.0 停住 / g=0 不动
def bounce_peak_after_first(rest, g=-9.8, frames=400):
    """返回第一次碰地后出现的最高 y."""
    e = new_eng()
    gnd = add(e, create_plane(8, 8), (0, -4, 0))
    b = add(e, create_cube(1.0), (0, 2, 0))
    b.add_script('bounce', {'rest': rest, 'g': g})
    grounded = False
    peak = None
    for _ in range(frames):
        e.update_scripts(0.05)
        if b.position.y <= -3.49:
            grounded = True
        if grounded:
            peak = b.position.y if peak is None else max(peak, b.position.y)
    return peak

p_keep = bounce_peak_after_first(1.0)                 # 永不衰减
p_half = bounce_peak_after_first(0.5)                 # 衰减一半
p_stop = bounce_peak_after_first(0.0)                 # 落一次就停
# rest 越大弹得越高: 1.0 > 0.5 > 0.0 (数值积分有损耗, 不做精确无损断言)
check("A4 bounce rest 参数单调 (1.0 > 0.5 > 0.0)",
      p_keep is not None and p_half is not None and p_stop is not None
      and p_keep > p_half and p_half > p_stop,
      f"peaks=({p_keep:.3f},{p_half:.3f},{p_stop:.3f})")
check("A4 bounce rest=1.0 反弹明显 (峰值高于半高)", p_keep > 1.0, f"peak={p_keep}")
check("A4 bounce rest=0.0 停住 (碰地后不弹起)", p_stop < -3.3, f"peak={p_stop}")

e3 = new_eng()
g3 = add(e3, create_plane(8, 8), (0, -4, 0))
b3 = add(e3, create_cube(1.0), (0, 2, 0))
b3.add_script('bounce', {'g': 0.0})                   # 无重力
e3.update_scripts(1.0)
check("A4 bounce g=0 不动", abs(b3.position.y - 2.0) < 1e-6, str(b3.position))

# A4-4 fall 大重力 (g=-100): 子步仍不穿透
e4 = new_eng()
g4 = add(e4, create_plane(8, 8), (0, -4, 0))
d4 = add(e4, create_cube(1.0), (0, 2, 0))
d4.add_script('fall', {'g': -100.0})
for _ in range(60):
    e4.update_scripts(0.05)
check("A4 fall 大重力: 落地不穿透 (y≈-3.5)", abs(d4.position.y - (-3.5)) < 0.1,
      f"y={d4.position.y:.3f}")

# ============ A7 多脚本边界 ============
# A7-1 三脚本 remove_script(1) 删中间 -> 剩 [A,C], 参数独立
e5 = new_eng()
m5 = add(e5, create_cube(1.0), (0, 0, 0))
m5.add_script('rotate', {'sy': 90})
m5.add_script('bob')
m5.add_script('orbit')
removed = m5.remove_script(1)
check("A7 remove_script(1) 删中间", removed is not None and removed.script_id == 'bob'
      and len(m5.scripts) == 2
      and m5.scripts[0].script_id == 'rotate' and m5.scripts[1].script_id == 'orbit')

# A7-2 同物体两份同名 rotate: 各自参数独立, 行为叠加
e6 = new_eng()
m6 = add(e6, create_cube(1.0), (0, 0, 0))
m6.add_script('rotate', {'sy': 90})
m6.add_script('rotate', {'sy': 180})
e6.update_scripts(1.0)
check("A7 双 rotate 参数独立叠加 (y=270°)",
      abs(m6.rotation.y - math.radians(270)) < 0.01, f"y={m6.rotation.y:.3f}")

# A7-3 add_script 无 vars / None -> 用脚本默认参数
e7 = new_eng()
m7 = add(e7, create_cube(1.0), (0, 0, 0))
m7.add_script('rotate', None)                         # 默认 sy=90
e7.update_scripts(1.0)
check("A7 无 vars/None 用默认参数 (y=90°)",
      abs(m7.rotation.y - math.radians(90)) < 0.01, f"y={m7.rotation.y:.3f}")

print()
print("总结果:", "ALL PASS ✅" if ok else "有 FAIL ❌")
