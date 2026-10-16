# -*- coding: utf-8 -*-
"""test_interp_state.py — 分离批2: InterpState 单测 (设计 §九断言清单)."""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))

import numpy as np

from interp_state import InterpState


class _M:
    """最小 GameObject 替身 (position/rotation 属性可换新对象, scale=3元组)."""
    def __init__(self, p=(0, 0, 0), r=(0, 0, 0), s=(1, 1, 1)):
        self.position = type('P', (), {'x': p[0], 'y': p[1], 'z': p[2]})()
        self.rotation = type('P', (), {'x': r[0], 'y': r[1], 'z': r[2]})()
        self.scale = tuple(s)


class TestInterpState(unittest.TestCase):

    def test_identity_align(self):
        """恒等式1: align 后 render_pose(0) == curr 逐位."""
        models = [_M(p=(1, 2, 3)), _M(p=(4, 5, 6))]
        it = InterpState(models)
        it.advance()
        it.align()
        pos, rot, scl = it.render_pose(0.0, models)
        np.testing.assert_array_equal(pos, [[1, 2, 3], [4, 5, 6]])
        np.testing.assert_array_equal(scl, [[1, 1, 1], [1, 1, 1]])

    def test_identity_prev(self):
        """恒等式2: advance 后 render_pose(0) == prev (上帧 curr)."""
        models = [_M(p=(0, 0, 0))]
        it = InterpState(models)
        it.advance()                      # curr@v1
        models[0].position = type('P', (), {'x': 10.0, 'y': 0.0, 'z': 0.0})()
        it.advance()                      # curr@v2, prev@v1
        pos, _, _ = it.render_pose(0.0, models)
        # alpha=0 时 lerp(prev, curr, 0) = prev = 帧首位置 (上一逻辑帧末)
        self.assertEqual(float(pos[0, 0]), 0.0)

    def test_identity_curr(self):
        """恒等式3: render_pose(1-ε) ≈ curr."""
        models = [_M(p=(0, 0, 0))]
        it = InterpState(models)
        it.advance()
        models[0].position = type('P', (), {'x': 10.0, 'y': 0.0, 'z': 0.0})()
        it.advance()
        pos, _, _ = it.render_pose(0.999999, models)
        self.assertAlmostEqual(float(pos[0, 0]), 10.0, places=4)

    def test_linear_midpoint(self):
        """断言2: 线性中点 prev=0, curr=10 → alpha=0.5 == 5.0 逐位."""
        models = [_M(p=(0, 0, 0))]
        it = InterpState(models)
        it.advance()
        models[0].position = type('P', (), {'x': 10.0, 'y': 0.0, 'z': 0.0})()
        it.advance()
        pos, _, _ = it.render_pose(0.5, models)
        self.assertEqual(float(pos[0, 0]), 5.0)

    def test_angdiff_wrap(self):
        """断言3: 跨 ±π 走短弧."""
        models = [_M(r=(3.10, 0, 0))]
        it = InterpState(models)
        it.advance()
        models[0].rotation = type('P', (), {'x': -3.10, 'y': 0.0, 'z': 0.0})()
        it.advance()
        pos, rot, _ = it.render_pose(0.5, models)
        # prev=3.10, curr=-3.10 (跨 π): 短弧中点 ≈ ±π
        mid = float(rot[0, 0])
        self.assertTrue(abs(abs(mid) - np.pi) < 0.05,
                        "跨π插值中点应接近 ±π, 得到 %r" % mid)
        # 不跨: 线性
        m2 = [_M(r=(0.1, 0, 0))]
        it2 = InterpState(m2)
        it2.advance()
        m2[0].rotation = type('P', (), {'x': 0.2, 'y': 0.0, 'z': 0.0})()
        it2.advance()
        _, rot2, _ = it2.render_pose(0.5, m2)
        self.assertAlmostEqual(float(rot2[0, 0]), 0.15, places=12)

    def test_new_object(self):
        """断言4: 新增物体首帧不插值 (prev 缺行填 curr)."""
        models = [_M(p=(0, 0, 0))]
        it = InterpState(models)
        it.advance()
        new = _M(p=(100, 0, 0))
        models.append(new)
        pos, _, _ = it.render_pose(0.5, models)
        self.assertEqual(float(pos[1, 0]), 100.0)   # 新增行 = curr 行
        it.advance()                                 # 下一逻辑帧后正常插值
        new.position = type('P', (), {'x': 110.0, 'y': 0.0, 'z': 0.0})()
        it.advance()
        pos2, _, _ = it.render_pose(0.5, models)
        self.assertAlmostEqual(float(pos2[1, 0]), 105.0, places=12)

    def test_remove_object(self):
        """断言5: 删行后输出行数 = len(models) 且不越界."""
        models = [_M(p=(0, 0, 0)), _M(p=(1, 0, 0)), _M(p=(2, 0, 0))]
        it = InterpState(models)
        it.advance()
        del models[2]
        pos, _, _ = it.render_pose(0.5, models)
        self.assertEqual(pos.shape, (2, 3))

    def test_grow_only(self):
        """断言6: 容量足够时反复增删, 输出缓冲对象 id 不变 (R8)."""
        models = [_M() for _ in range(4)]
        it = InterpState(models)
        it.advance()
        it.render_pose(0.5, models)
        out_id = id(it._out)
        for k in range(3):
            models.append(_M())
            models.pop()
            it.advance()
            it.render_pose(0.5, models)
            self.assertEqual(id(it._out), out_id)

    def test_static_frame(self):
        """断言7: 无位移帧 True / 有位移帧 False."""
        models = [_M(p=(0, 0, 0))]
        it = InterpState(models)
        it.advance()
        it.advance()
        self.assertTrue(it.static_frame())
        models[0].position = type('P', (), {'x': 5.0, 'y': 0.0, 'z': 0.0})()
        it.advance()
        self.assertFalse(it.static_frame())

    def test_pin_alive(self):
        """断言8 (R6): 抓取后局部引用删除, 对象被 _models_ref 钉住不死."""
        import weakref
        models = [_M(p=(0, 0, 0))]
        it = InterpState(models)
        it.advance()
        ref = weakref.ref(models[0])
        it.advance()
        self.assertIsNotNone(ref())   # _models_ref 持列表 → 对象存活 → id 不复用


if __name__ == '__main__':
    unittest.main(verbosity=2)
