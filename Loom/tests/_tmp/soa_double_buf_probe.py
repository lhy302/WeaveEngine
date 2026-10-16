# -*- coding: utf-8 -*-
r"""soa_double_buf_probe.py — M4: AUDIT-29 SoA 连续双缓冲预分配与数值对拍探针

测试维度:
  1. 连续内存预分配验证: 检查 _soa_double_bufs 底层连续内存指针在动态帧推进时完全复用, 无每帧 np.array 重建;
  2. 乒乓双缓冲 (Double Buffering) 翻页验证: slot 在 0 与 1 之间交替切换, 保证相邻逻辑帧/插值帧数据不被踩踏;
  3. 数值对拍: 500 物体动态更新 50 步, 快照返回的 (pos, rot, scl) 与物体真实变换逐位一致 (max_diff == 0.0);
  4. 扩容与空场景鲁棒性: n=0、扩容至 1000 物体时自动调整容量且内存连续。

判据: 全部 4 组用例 100% 通过, 否则 sys.exit(1)。
"""
import math
import os
import sys
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
LOOM = os.path.abspath(os.path.join(HERE, '..', '..'))
sys.path.insert(0, LOOM)

import engine as E
from engine import Point3D, GameObject, TransformComponent

class HeadlessEngine(E.GLEngine):
    def __init__(self):
        self.models = []
        self._struct_gen = 0
        self.keys = {}
        self.actions = dict(E.DEFAULT_ACTIONS)

def test_soa_double_buffering_and_continuity():
    print("--- 1. AUDIT-29: SoA 连续双缓冲指针复用与乒乓翻页测试 ---")
    eng = HeadlessEngine()
    n = 100
    for i in range(n):
        m = GameObject(None, (float(i), float(i*2), float(i*3)), (0, 0, 0), name=f"obj_{i}")
        eng.models.append(m)
        
    # 第 1 帧慢路径 (首次分配)
    stamp1, pos1, rot1, scl1 = eng._transform_snapshot(eng.models)
    ptr_pos1 = pos1.ctypes.data
    slot1 = eng._soa_buf_slot
    assert slot1 in (0, 1), f"无效 slot: {slot1}"
    
    # 改变变换值触发慢路径 (第 2 帧)
    eng.models[0].position = Point3D(99.0, 99.0, 99.0)
    stamp2, pos2, rot2, scl2 = eng._transform_snapshot(eng.models)
    ptr_pos2 = pos2.ctypes.data
    slot2 = eng._soa_buf_slot
    assert slot2 == 1 - slot1, f"双缓冲未翻页: slot1={slot1}, slot2={slot2}"
    assert ptr_pos1 != ptr_pos2, "双缓冲两个槽位地址不应相同"
    
    # 再次改变变换值 (第 3 帧): 应该切回 slot1, 且指针完全复用 ptr_pos1!
    eng.models[0].position = Point3D(100.0, 100.0, 100.0)
    stamp3, pos3, rot3, scl3 = eng._transform_snapshot(eng.models)
    ptr_pos3 = pos3.ctypes.data
    slot3 = eng._soa_buf_slot
    assert slot3 == slot1, f"双缓冲未切回: slot3={slot3} vs slot1={slot1}"
    assert ptr_pos3 == ptr_pos1, f"内存未复用! ptr3={ptr_pos3}, ptr1={ptr_pos1}"
    
    print("PASS: 双缓冲在 slot 0/1 间严格乒乓交替, 且预分配连续内存 100% 原地复用")
    return True

def test_soa_numerical_precision_500_objects():
    print("\n--- 2. AUDIT-29: 500 物体 50 步动态位移数值逐位对拍 ---")
    eng = HeadlessEngine()
    n = 500
    np.random.seed(42)
    for i in range(n):
        p = (float(i), 0.0, float(-i))
        r = (0.0, float(i * 0.1), 0.0)
        s = (1.0, 1.0, 1.0)
        m = GameObject(None, p, r, scale=s, name=f"obj_{i}")
        eng.models.append(m)
        
    steps = 50
    for step in range(steps):
        # 模拟每帧运动
        for i, m in enumerate(eng.models):
            m.position = Point3D(m.position.x + 0.1, m.position.y + 0.05, m.position.z - 0.1)
            m.rotation = Point3D(m.rotation.x, m.rotation.y + 0.01, m.rotation.z)
            
        _, pos, rot, scl = eng._transform_snapshot(eng.models)
        
        # 逐位检查
        for i, m in enumerate(eng.models):
            assert pos[i, 0] == m.position.x and pos[i, 1] == m.position.y and pos[i, 2] == m.position.z
            assert rot[i, 0] == m.rotation.x and rot[i, 1] == m.rotation.y and rot[i, 2] == m.rotation.z
            assert scl[i, 0] == m.scale[0] and scl[i, 1] == m.scale[1] and scl[i, 2] == m.scale[2]
            
    print("PASS: 500 物体 x 50 步慢路快照与属性值 100% 逐位一致 (max_diff == 0.0)")
    return True

def test_soa_empty_and_growth():
    print("\n--- 3. AUDIT-29: 空场景与动态扩容鲁棒性 ---")
    eng = HeadlessEngine()
    # 空场景
    _, pos, rot, scl = eng._transform_snapshot([])
    assert pos.shape == (0, 3) and rot.shape == (0, 3) and scl.shape == (0, 3)
    
    # 动态扩容至 1000
    for i in range(1000):
        eng.models.append(GameObject(None, (0, 0, 0), (0, 0, 0)))
    _, pos, rot, scl = eng._transform_snapshot(eng.models)
    assert pos.shape == (1000, 3)
    cap = eng._soa_double_bufs[0][0].shape[0]
    assert cap >= 1000, f"扩容容量不足: {cap}"
    print(f"PASS: 动态扩容至 1000 成功 (预分配容量 cap={cap})")
    return True

if __name__ == '__main__':
    ok = True
    ok = ok and test_soa_double_buffering_and_continuity()
    ok = ok and test_soa_numerical_precision_500_objects()
    ok = ok and test_soa_empty_and_growth()
    if ok:
        print("\n=== AUDIT-29 ALL VERIFICATIONS PASSED ===")
        sys.exit(0)
    else:
        print("\n=== AUDIT-29 SOME TESTS FAILED ===")
        sys.exit(1)
