# -*- coding: utf-8 -*-
"""engine.py 安全加固断言 (2026-08-20 安全审查第一轮):
空场景按键路径不崩 (ZeroDivisionError/IndexError 修复) + 索引越界 clamp."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import engine as E
from mesh import create_cube

eng = E.GLEngine.__new__(E.GLEngine)
eng.models = []
eng.materials = []
eng.current_model_index = 0
eng.camera = E.Point3D(0, 0, 0)
eng.camera_yaw = eng.camera_pitch = 0.0
eng.fps = 0
eng._external_ctx = True          # 跳过 HUD 绘制分支 (无 pygame 窗口)
E.GLEngine._build_gpu = lambda self, m: None

ok = True
def check(label, cond, detail=""):
    global ok
    print(("PASS " if cond else "FAIL ") + label + ("  " + detail if detail else ""))
    if not cond: ok = False

# ---- 空场景 (0 模型): 各当前模型操作不崩 ----
eng.select_next_model()
check("空场景 select_next_model 不崩", True)
check("空场景 get_current_model 返回 None", eng.get_current_model() is None)
eng._hud_lines()
check("空场景 _hud_lines 不崩", True)

# ---- 索引越界 clamp: 模型减少后 current_model_index 残留 ----
m = eng.add_model(create_cube(1.0), E.Point3D(0, 0, 0), E.Point3D(0, 0, 0))
eng.current_model_index = 5      # 模拟删模型后残留的越界索引
got = eng.get_current_model()
check("索引越界 get_current_model clamp 到有效模型",
      got is m and eng.current_model_index == 0)
eng.select_next_model()
check("有模型 select_next_model 环绕回 0", eng.current_model_index == 0)

print()
print("总结果:", "ALL PASS ✅" if ok else "有 FAIL ❌")
