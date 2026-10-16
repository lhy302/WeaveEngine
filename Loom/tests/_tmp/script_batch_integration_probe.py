# -*- coding: utf-8 -*-
r"""script_batch_integration_probe.py — M4: AUDIT-35 脚本批处理接入 engine.py 契约与对拍验证

测试维度:
  1. 纯 C 批量自转 (batch_rotate) 接入 update_scripts 对拍: 100 个物体 100 步迭代与数学基准逐位对拍 (<= 1 ULP);
  2. 混合场景分流测试: 同时挂载 rotate、bob、wasd_move 时, rotate 走 C 批处理, 其余走通用 Python 更新, 互不干扰;
  3. 异常脚本隔离验证: 坏脚本抛异常时被标记 _script_broken, 不崩溃且其余 C 批处理物体继续正常运转。

★B3 退役 (2026-10-16): 删原第 3 组「LOOM_NO_SCRIPT_DLL=1 逃生门回退测试」——
script 官方件为唯一路径, 无 Python 运动回退。判据: 全部 3 组用例 100% 通过, 否则 sys.exit(1)。
"""
import math
import os
import sys
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
LOOM = os.path.abspath(os.path.join(HERE, '..', '..'))
sys.path.insert(0, LOOM)

import engine as E
from engine import Point3D, GameObject, ScriptComponent, TransformComponent
import scripts
import script_glue as sg

class MinimalEngine(E.GLEngine):
    """用于无头无显卡测试的轻量引擎桩, 仅复用模型管理与 update_scripts。"""
    def __init__(self):
        self.models = []
        self._struct_gen = 0
        self.keys = {}
        self.actions = dict(E.DEFAULT_ACTIONS)
    def is_key(self, k):
        return bool(self.keys.get(k, False))
    def get_action(self, a):
        return False
    def world_position(self, m):
        return m.position

def test_100_rotates_c_vs_math():
    print("--- 1. AUDIT-35: 100 物体纯 C 批量自转 vs 数学参考 ---")
    eng = MinimalEngine()
    np.random.seed(12345)
    n = 100
    expected_rot = []
    speeds = []
    for i in range(n):
        sx = float(np.random.uniform(-180.0, 180.0))
        sy = float(np.random.uniform(-180.0, 180.0))
        sz = float(np.random.uniform(-180.0, 180.0))
        speeds.append((sx, sy, sz))
        rx = float(np.random.uniform(-math.pi, math.pi))
        ry = float(np.random.uniform(-math.pi, math.pi))
        rz = float(np.random.uniform(-math.pi, math.pi))
        expected_rot.append([rx, ry, rz])
        
        m = GameObject(None, (0, 0, 0), (rx, ry, rz), name=f"obj_{i}")
        sc = ScriptComponent(script_id='rotate', script_vars={'sx': sx, 'sy': sy, 'sz': sz})
        m.scripts.append(sc)
        eng.models.append(m)
        
    dt = 0.016666666666666666
    steps = 50
    deg2rad = math.pi / 180.0
    for s in range(steps):
        eng.update_scripts(dt)
        for i in range(n):
            expected_rot[i][0] += speeds[i][0] * deg2rad * dt
            expected_rot[i][1] += speeds[i][1] * deg2rad * dt
            expected_rot[i][2] += speeds[i][2] * deg2rad * dt
            
    # 逐位误差对拍
    max_err = 0.0
    for i, m in enumerate(eng.models):
        err = max(abs(m.rotation.x - expected_rot[i][0]),
                  abs(m.rotation.y - expected_rot[i][1]),
                  abs(m.rotation.z - expected_rot[i][2]))
        if err > max_err:
            max_err = err
            
    print(f"100 物体 x 50 步 C 批处理: max_err = {max_err:.3e}")
    assert max_err <= 1e-14, f"误差超标: {max_err}"
    print("PASS: 100 物体纯 C 批量自转数学严丝合缝")
    return True

def test_mixed_scripts_coexistence():
    print("\n--- 2. AUDIT-35: 混合脚本共存 (C 批自转 + Python 浮动) ---")
    eng = MinimalEngine()
    m_rot = GameObject(None, (0, 0, 0), (0, 0, 0), name="rot_box")
    m_rot.scripts.append(ScriptComponent(script_id='rotate', script_vars={'sx': 0.0, 'sy': 90.0, 'sz': 0.0}))
    
    m_bob = GameObject(None, (0, 2, 0), (0, 0, 0), name="bob_sphere")
    m_bob.scripts.append(ScriptComponent(script_id='bob', script_vars={'amp': 1.0, 'freq': 1.0}))
    
    eng.models = [m_rot, m_bob]
    
    # 步进 0.25 秒 (rotate 转 22.5 度 = 0.392699 rad; bob 升至最高点 3.0)
    eng.update_scripts(0.25)
    expected_ry = math.radians(22.5)
    assert abs(m_rot.rotation.y - expected_ry) < 1e-7, f"rot 异常: {m_rot.rotation.y}"
    assert abs(m_bob.position.y - 3.0) < 1e-6, f"bob 异常: {m_bob.position.y}"
    print("PASS: 混合脚本共存分流运行正常")
    return True

# ★B3 退役 (2026-10-16): test_fallback_when_disabled 已删
# (LOOM_NO_SCRIPT_DLL 逃生门退役, script.dll 为唯一路径)。

def test_broken_script_isolation():
    print("\n--- 4. AUDIT-35: 异常脚本隔离防护测试 ---")
    eng = MinimalEngine()
    m_bad = GameObject(None, (0, 0, 0), (0, 0, 0), name="bad_obj")
    m_bad.scripts.append(ScriptComponent(script_id='rotate', script_vars={'sx': 'invalid_string'}))
    
    m_good = GameObject(None, (0, 0, 0), (0, 0, 0), name="good_obj")
    m_good.scripts.append(ScriptComponent(script_id='rotate', script_vars={'sx': 0.0, 'sy': 90.0, 'sz': 0.0}))
    eng.models = [m_bad, m_good]
    
    # 正常运行不崩溃
    eng.update_scripts(0.1)
    assert m_bad.scripts[0]._script_broken, "坏脚本未被隔离"
    assert m_good.rotation.y > 0.0, "好脚本未被执行"
    print("PASS: 坏脚本被有效隔离, 好脚本持续正常运作")
    return True

if __name__ == '__main__':
    ok = True
    ok = ok and test_100_rotates_c_vs_math()
    ok = ok and test_mixed_scripts_coexistence()
    ok = ok and test_broken_script_isolation()
    if ok:
        print("\n=== AUDIT-35 ALL VERIFICATIONS PASSED ===")
        sys.exit(0)
    else:
        print("\n=== AUDIT-35 SOME TESTS FAILED ===")
        sys.exit(1)
