# -*- coding: utf-8 -*-
"""undo.py 无头测试 (patch _build_gpu 绕过 GL 上下文)."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import engine as E
from mesh import create_cube
import undo as U

# 不开窗口的引擎桩: 替换 _build_gpu 为 no-op
eng = E.GLEngine.__new__(E.GLEngine)
eng.models = []
eng.materials = []               # M23: 材质库桩
eng.current_model_index = 0
E.GLEngine._build_gpu = lambda self, m: None

def add(name, pos=(0,0,0)):
    return eng.add_model(create_cube(1.5), E.Point3D(*pos), E.Point3D(0,0,0), name=name)

um = U.UndoManager(limit=100)
ok = True
def check(label, cond, detail=""):
    global ok
    print(("PASS " if cond else "FAIL ") + label + ("  " + detail if detail else ""))
    if not cond: ok = False

def snap(m):
    return (m.position.x, m.position.y, m.position.z)

# --- 添加 ---
cmdA = um.push(U.AddObjectCommand("加A", eng, create_cube(1.5), E.Point3D(0,0,0),
             E.Point3D(0,0,0), name="A"))
cmdB = um.push(U.AddObjectCommand("加B", eng, create_cube(1.5), E.Point3D(2,0,0),
             E.Point3D(0,0,0), name="B"))
A, B = cmdA.model, cmdB.model
check("添加后 A,B 在场景", [m.name for m in eng.models] == ["A","B"])

# --- 撤销添加 ---
c = um.undo()
check("undo 加B -> B 被删", len(eng.models) == 1 and eng.models[0] is A)
um.redo()
check("redo 加B -> B 回来", [m.name for m in eng.models] == ["A","B"])

# --- StateCommand 改位置 ---
before = U.snapshot(B)
B.position = E.Point3D(5, 5, 5)
after = U.snapshot(B)
um.push(U.StateCommand("移动B", eng, B, before, after))
check("改后 B=(5,5,5)", snap(B) == (5,5,5))
um.undo()
check("undo 移动B -> B=(2,0,0)", snap(B) == (2,0,0))
um.redo()
check("redo 移动B -> B=(5,5,5)", snap(B) == (5,5,5))

# --- 饱和度可撤销 (M22) ---
B.saturation = 2.0
before = U.snapshot(B)
B.saturation = 0.5
after = U.snapshot(B)
um.push(U.StateCommand("饱和度B", eng, B, before, after))
check("改后饱和度=0.5", abs(B.saturation - 0.5) < 1e-9)
um.undo()
check("undo 饱和度 -> 2.0", abs(B.saturation - 2.0) < 1e-9)
um.redo()
check("redo 饱和度 -> 0.5", abs(B.saturation - 0.5) < 1e-9)

# --- 脚本挂载/参数可撤销 (M27) ---
before = U.snapshot(B)
B.script_id = 'rotate'
B.script_vars = {'sx': 30.0}
after = U.snapshot(B)
um.push(U.StateCommand("挂脚本B", eng, B, before, after))
check("挂脚本后 id+var", B.script_id == 'rotate' and B.script_vars == {'sx': 30.0})
um.undo()
check("undo 挂脚本 -> 无脚本", B.script_id is None and B.script_vars == {})
um.redo()
check("redo 挂脚本 -> 恢复", B.script_id == 'rotate' and B.script_vars == {'sx': 30.0})

# --- ReparentCommand: B 挂到 A 下 ---
um.push(U.ReparentCommand("挂父", eng, B, None, A))
check("B 父=A", B.parent is A and A.children == [B])
um.undo()
check("undo 挂父 -> B 独立", B.parent is None and A.children == [])
um.redo()
check("redo 挂父 -> B 父=A", B.parent is A)

# --- DeleteObjectCommand: 删 A (含子 B), 应能完整还原 ---
before_list = list(eng.models)
um.push(U.DeleteObjectCommand("删A子树", eng, A))
check("删后场景空", eng.models == [])
um.undo()
check("undo 删A -> A,B 回来", [m.name for m in eng.models] == ["A","B"])
check("undo 删A -> 父链还在", B.parent is A and A.children == [B])
check("undo 删A -> 顺序不变", eng.models is before_list or eng.models == before_list)
um.redo()
check("redo 删A -> 又删光", eng.models == [])
um.undo()

# --- 材质切换可撤销 (M23): 快照含材质引用 ---
M1 = eng.add_material(color="#FF0000", saturation=1.0, name="红")   # 进库
M2 = eng.add_material(color="#00FF00", saturation=1.0, name="绿")
check("材质库 2 项", len(eng.materials) == 2)
B.renderer.material = M1                                            # 手动换到 M1
before = U.snapshot(B)
B.renderer.material = M2
after = U.snapshot(B)
um.push(U.StateCommand("换材质B", eng, B, before, after))
check("换材质后引用 M2", B.renderer.material is M2)
um.undo()
check("undo 换材质 -> M1", B.renderer.material is M1)
um.redo()
check("redo 换材质 -> M2", B.renderer.material is M2)

# --- AddMaterialCommand: 新建 + 挂物体, 撤销还原 (M23) ---
cmdMat = um.push(U.AddMaterialCommand("新建材质", eng, color="#0000FF",
                                      saturation=1.0, name="蓝", model=B))
new_mat = cmdMat.mat
check("新建材质进库且挂上", len(eng.materials) == 3 and B.renderer.material is new_mat)
um.undo()
check("undo 新建材质 -> 物体还原 M2, 库 2 项", B.renderer.material is M2
      and len(eng.materials) == 2 and new_mat not in eng.materials)
um.redo()
check("redo 新建材质 -> 重新入库并挂上", B.renderer.material is new_mat
      and new_mat in eng.materials and len(eng.materials) == 3)

# --- 碰撞体开关可撤销 (M28): 快照含 collider ---
before = U.snapshot(B)
B.collider.enabled = False
after = U.snapshot(B)
um.push(U.StateCommand("关碰撞B", eng, B, before, after))
check("关碰撞后 enabled=False", not B.collider.enabled)
um.undo()
check("undo 关碰撞 -> 恢复启用", B.collider.enabled)
um.redo()
check("redo 关碰撞 -> 又禁用", not B.collider.enabled)
B.collider.enabled = True

# --- 新 push 清空 redo 栈 ---
um.push(U.StateCommand("再动", eng, A, U.snapshot(A), U.snapshot(A)))
check("新 push 后 redo 栈空", not um.can_redo and um.can_undo)

# --- 深度撤销到空 ---
while um.can_undo:
    um.undo()
check("撤销到初始(空场景)", eng.models == [])

# --- AddCameraCommand 参数槽位对齐 (2026-08-22) ---
# engine.add_camera 签名 name 后插了 guid=None 槽, old args 无占位 → 错位:
# pitch_min=-85.0 落进 pitch_lock 槽 → 新相机误"俯仰限制: 已启用"
eng.cameras = []
eng.active_camera = None          # __init__ 属性, __new__ stub 需手动补
cc = um.push(U.AddCameraCommand("加相机", eng))
cam = cc.cam
check("AddCameraCommand 摄像机已在场景", len(eng.cameras) == 1)
check("AddCameraCommand pitch_lock 默认 False (槽位对齐)",
      cam.pitch_lock is False, "pitch_lock=%r" % (cam.pitch_lock,))
check("AddCameraCommand fov_locked 默认 True", cam.fov_locked is True)
check("AddCameraCommand pitch 范围默认 (-85, 85)",
      (cam.pitch_min, cam.pitch_max) == (-85.0, 85.0),
      str((cam.pitch_min, cam.pitch_max)))
um.undo()
check("撤销加相机 -> cameras 空", eng.cameras == [])
um.redo()
check("重做加相机 -> 相机回来", len(eng.cameras) == 1)

print()
print("总结果:", "ALL PASS ✅" if ok else "有 FAIL ❌")
