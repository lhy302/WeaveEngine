# -*- coding: utf-8 -*-
"""test_lod.py — LOD (距离/屏幕占比) 回归 (M36, 2026-10-14)。
独立文件 (干净 GL context)，避免与 test_texture.py 的大量 GL 资源累积冲突。
"""
import os
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)
os.chdir(BASE)
sys.argv[0] = os.path.join(BASE, 'Loom.py')

import moderngl
import editor as editor_mod
import engine as E
from mesh import create_sphere

_fails = []


def check(name, cond, detail=''):
    print("%s %s  %s" % ("PASS" if cond else "FAIL", name, detail))
    if not cond:
        _fails.append(name)


ctx = moderngl.create_standalone_context()
ed = editor_mod.EditorApp(320, 240, ctx=ctx)
ed._external_fb = ctx.detect_framebuffer()
try:
    _g = ed.view.gui.render
    ed.view.gui.render = lambda *a, **k: _g(target=ed._external_fb)
except Exception:
    pass

ed.load_scene(os.path.join(BASE, '保存', '压力测试', '压力_空场景.json'))
hi = create_sphere(0.5, 16, 24)
lo = create_sphere(0.5, 6, 8)
obj = ed.add_model(hi, E.Point3D(0, 0, 0), E.Point3D(0, 0, 0), name='LOD球')
ed.orbit_mode = True
ed.camera_target = (0.0, 0.0, 0.0)


def settle(dist):
    ed.camera_distance = dist
    for _ in range(6):
        ed.render(1 / 60.0)
    return obj.renderer.mesh


# ---- 距离模式 (向后兼容) ----
obj.renderer.lod_levels = [(5.0, hi), (20.0, lo)]
check("距离LOD 近->高精度", settle(3.0) is hi, "")
check("距离LOD 中->低精度", settle(15.0) is lo, "")
check("距离LOD 回近->高精度", settle(3.0) is hi, "")
check("无 LOD 物体零配置", obj.renderer.lod_screen_levels is None, "")

# ---- 屏幕占比模式 (对标 Unity LODGroup) ----
obj.renderer.lod_levels = None
obj.renderer.lod_screen_levels = [(0.1, hi), (0.0, lo)]
check("屏幕LOD 近->高精度", settle(2.0) is hi, "")
check("屏幕LOD 远->低精度", settle(30.0) is lo, "")
check("屏幕LOD 回近->高精度", settle(2.0) is hi, "")

# ---- lod_bias (Unity: 大=更高质量=更晚降级) ----
obj.renderer.lod_bias = 1.0
settle(12.0)
_bias_low = obj.renderer.mesh is lo
obj.renderer.lod_bias = 8.0
settle(12.0)
_bias_high = obj.renderer.mesh is hi
check("lod_bias 大=更高质量", _bias_low and _bias_high,
      "bias1->lo=%s bias8->hi=%s" % (_bias_low, _bias_high))
obj.renderer.lod_bias = 1.0

# ---- 无 LOD 物体不受影响 ----
plain = ed.add_model(hi, E.Point3D(9, 0, 0), E.Point3D(0, 0, 0), name='普通球')
check("无 LOD 物体网格不变", plain.renderer.mesh is hi, "")

ed._stop_parallel()
import pygame
pygame.quit()
print("")
if _fails:
    print("有 FAIL: %s" % _fails)
    sys.exit(1)
print("ALL PASS")
sys.exit(0)
