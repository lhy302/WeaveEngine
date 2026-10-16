# -*- coding: utf-8 -*-
"""test_xform_sync.py — 编辑态插值失同步修复守护 (2026-09-06)

用户报告: 编辑模式拖动物体, 黄框 (gizmo/逻辑矩阵) 跟着走但物体画面不动,
按播放后才同步。根因: 编辑态改位不走逻辑帧 (无 advance 快照翻页),
_interp.prev/curr 停旧位 + static_frame() 恒 True → _render_world 复用。

修复: TransformComponent position/rotation/scale setter bump 类级
_xform_gen; engine._consume_xform_gen 检测变化 → _interp.align() +
_render_world/_prep_sig/_frame_world 失效。
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from engine import GameObject, TransformComponent, GLEngine


def _mk_engine_stub():
    """不跑 __init__ 的最小桩 (测试惯例 __new__): 只挂插值/缓存字段."""
    e = GLEngine.__new__(GLEngine)
    e._interp = None
    e._render_world = 'STALE'
    e._prep_sig = 'STALE'
    e._frame_world = 'STALE'
    e._last_xform_gen = None
    return e


class _FakeInterp:
    def __init__(self):
        self.aligned = 0

    def align(self):
        self.aligned += 1


class T1_XformGen(unittest.TestCase):
    def setUp(self):
        # 类级代数: 每测试从已知值出发 (记录当前值, 断言增量)
        self._g0 = TransformComponent._xform_gen

    def test_position_write_bumps(self):
        m = GameObject(None, (0, 0, 0), (0, 0, 0), name='t')
        m.position = (1.0, 2.0, 3.0)
        self.assertEqual(TransformComponent._xform_gen, self._g0 + 1)

    def test_rotation_scale_write_bumps(self):
        m = GameObject(None, (0, 0, 0), (0, 0, 0), name='t')
        m.rotation = (0.1, 0.2, 0.3)
        self.assertEqual(TransformComponent._xform_gen, self._g0 + 1)
        m.scale = (2.0, 2.0, 2.0)
        self.assertEqual(TransformComponent._xform_gen, self._g0 + 2)

    def test_transform_direct_write_bumps(self):
        """编辑器 gizmo 路径: t.position = ... (TransformComponent 直写)"""
        m = GameObject(None, (0, 0, 0), (0, 0, 0), name='t')
        from engine import Point3D
        m.transform.position = Point3D(5.0, 0.0, 0.0)
        self.assertEqual(TransformComponent._xform_gen, self._g0 + 1)

    def test_read_does_not_bump(self):
        m = GameObject(None, (0, 0, 0), (0, 0, 0), name='t')
        _ = m.position.x; _ = m.rotation; _ = m.scale
        self.assertEqual(TransformComponent._xform_gen, self._g0)


class T2_Consume(unittest.TestCase):
    def setUp(self):
        self._g0 = TransformComponent._xform_gen

    def test_first_call_anchors(self):
        e = _mk_engine_stub()
        self.assertFalse(e._consume_xform_gen())
        self.assertEqual(e._render_world, 'STALE')   # 首帧锚定不追溯

    def test_write_triggers_align_and_invalidate(self):
        e = _mk_engine_stub()
        e._consume_xform_gen()                        # 锚定
        it = e._interp = _FakeInterp()
        m = GameObject(None, (0, 0, 0), (0, 0, 0), name='t')
        m.position = (9.0, 9.0, 9.0)                  # 编辑态改位
        self.assertTrue(e._consume_xform_gen())
        self.assertEqual(it.aligned, 1)
        self.assertIsNone(e._render_world)
        self.assertIsNone(e._prep_sig)
        self.assertIsNone(e._frame_world)

    def test_no_write_no_align(self):
        e = _mk_engine_stub()
        e._consume_xform_gen()
        it = e._interp = _FakeInterp()
        self.assertFalse(e._consume_xform_gen())
        self.assertEqual(it.aligned, 0)


class T3_InterpAlignedAfterAlign(unittest.TestCase):
    """端到端语义: align 后插值输出 = 现读值 (画面跟手)."""

    def test_render_pose_matches_after_move(self):
        from interp_state import InterpState
        m = GameObject(None, (0, 0, 0), (0, 0, 0), name='t')
        models = [m]
        it = InterpState(models)
        it.advance()          # curr = (0,0,0)
        it.align()
        # 编辑态移动物体 (不跑逻辑帧)
        m.position = (4.0, 2.0, 1.0)
        TransformComponent._xform_gen += 1
        # _consume_xform_gen 语义 = 重抓快照对齐:
        it.advance()          # curr = (4,2,1)
        it.align()            # prev = curr
        pos, _, _ = it.render_pose(0.5, models)
        self.assertAlmostEqual(pos[0, 0], 4.0, places=9)
        self.assertAlmostEqual(pos[0, 1], 2.0, places=9)


if __name__ == '__main__':
    unittest.main(verbosity=2)
