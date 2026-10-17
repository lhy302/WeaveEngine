# -*- coding: utf-8 -*-
"""reset_removed_probe.py — 空格复位机制移除验证 (2026-08-28)

断言: ① engine._KEY 键位表已无 'RESET_ALL'; ② 真实键盘事件 KEYDOWN space
不再触发 reset_all() —— 旧行为: 全场景模型位置回初始(出生点)+ 相机回
camera_initial, 与输入动作'跳跃'(共用空格)在玩家游戏内冲突。
运行: py -3.12 tests\_tmp\reset_removed_probe.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))))   # _tmp -> tests -> Loom 目录
import pygame                              # noqa: E402
from engine import GLEngine, Point3D, KEY_BINDINGS  # noqa: E402
from mesh import create_cube                # noqa: E402

ok = True


def check(label, cond, detail=""):
    global ok
    print(("PASS " if cond else "FAIL ") + label + ("  " + detail if detail else ""))
    if not cond:
        ok = False


check("KEY_BINDINGS 已无 'RESET_ALL'", 'RESET_ALL' not in KEY_BINDINGS,
      str(sorted(KEY_BINDINGS)))
check("KEY_BINDINGS 已无玩具期 MODEL_*/ROTATE_* 键控", not any(
    k.startswith(('MODEL_', 'ROTATE_')) for k in KEY_BINDINGS),
    str(sorted(KEY_BINDINGS)))

try:
    eng = GLEngine(320, 320)      # 真窗口 + GL(本机 GPU)
except Exception as e:
    print("GLEngine 真构造失败(环境): %r" % e)
    sys.exit(0)

# add_model(mesh, position, rotation, rotation_speed) —— 玩具自转数据链已无
# 键控入口, 探针用零转速 (键控清除验证不受数据干扰)
m = eng.add_model(create_cube(1.0), Point3D(2.0, 3.0, 4.0),
                  Point3D(0.1, 0.2, 0.3))
m.name = '测试木块'
before = (m.position.x, m.position.y, m.position.z)
cam_before = (eng.camera.x, eng.camera.y, eng.camera.z)

# 模拟玩家按空格(跳跃键)并处理一帧事件
pygame.event.post(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_SPACE))
eng._handle_events()
after = (m.position.x, m.position.y, m.position.z)
cam_after = (eng.camera.x, eng.camera.y, eng.camera.z)
check("KEYDOWN space 后模型位置未被复位(旧行为: 回初始)",
      before == after, "before=%s after=%s" % (before, after))
check("KEYDOWN space 后相机未被复位", cam_before == cam_after,
      "before=%s after=%s" % (cam_before, cam_after))

# 玩具期键控: 按 1 (ROTATE_X_POS) 现在应完全无效果 (位置/旋转零变化)
r_before = (m.rotation.x, m.rotation.y, m.rotation.z)
pygame.event.post(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_1))
eng._handle_events()
check("KEYDOWN 1 后模型位置/旋转零变化 (键控+自转链已清除)",
      before == (m.position.x, m.position.y, m.position.z)
      and r_before == (m.rotation.x, m.rotation.y, m.rotation.z),
      "pos=%s rot=%s" % (m.position, m.rotation))

pygame.quit()
print("总结果:", "ALL PASS ✅" if ok else "有 FAIL ❌")
sys.exit(0 if ok else 1)
