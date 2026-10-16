# -*- coding: utf-8 -*-
"""test_gameplay_bugs.py — 小游戏实测发现的两个 bug 回归 (2026-10-14)。"""
import os
import sys
import tempfile

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)
os.chdir(BASE)
sys.argv[0] = os.path.join(BASE, 'Loom.py')

import numpy as np
import moderngl
import editor as editor_mod
import engine as E
import sceneio
from mesh import create_cube
from loom_texture import Texture
from loom_material import Material

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

# ---- Bug 1: count_touch 移除物体后不崩溃 ----
# 直接测脚本 update：物体被移除后 index() 不应抛（修复=命中后 return）
import scripts
class _FakeEngine:
    def __init__(self):
        self.models = []
        self._count_hits = 0
        self.ui = type('U', (), {'text': lambda *a, **k: None})()
    def get_collisions(self, obj):
        return [type('O', (), {'name': '玩家'})()]
    def remove_model(self, obj):
        if obj in self.models:
            self.models.remove(obj)

fe = _FakeEngine()
obj = type('O', (), {'name': '彩球0'})()
fe.models.append(obj)
sc = scripts.get_script('count_touch')()
sc.obj = obj
sc.engine = fe
sc.on_start()   # 初始化 _hit_printed / hits
try:
    sc.update(0.016)   # 命中 -> 移除 -> 修复后应 return（不再 index 已移除物体）
    check("count_touch 移除后不崩溃", obj not in fe.models, "hits=%d" % sc.hits)
except Exception as e:
    check("count_touch 移除后不崩溃", False, repr(e))

# ---- Bug 2: 未注册材质也能序列化 ----
arr = np.zeros((8, 8, 4), dtype=np.uint8)
tex = Texture.from_rgba(8, 8, arr, name='测试贴图')
mat = Material(name='未注册PBR', metallic=0.8, roughness=0.2, pbr=True, albedo=tex)
m = ed.add_model(create_cube(1.0), E.Point3D(0, 0, 0), E.Point3D(0, 0, 0), name='块')
m.renderer.material = mat   # 直接赋, 不入 engine.materials
d = sceneio.scene_to_dict(ed)
mat_dicts = d.get('materials', [])
found = [mm for mm in mat_dicts if mm.get('name') == '未注册PBR']
check("未注册材质被序列化", len(found) == 1, "材质数=%d" % len(mat_dicts))
if found:
    check("未注册材质 PBR 保留", found[0].get('pbr') is True
          and found[0].get('metallic') == 0.8, str(found[0].get('metallic')))
    check("未注册材质贴图保留", found[0].get('albedo') is not None, "")

# 完整往返
sp = os.path.join(tempfile.gettempdir(), '_gameplay_bug_rt.json')
sceneio.save_scene_data(sp, d)
ed.load_scene(sp)
_pbr = [mm for mm in ed.materials if getattr(mm, 'pbr', False)]
check("往返后 PBR 材质恢复", len(_pbr) >= 1, "%d PBR" % len(_pbr))
os.remove(sp)

ed._stop_parallel()
import pygame
pygame.quit()
print("")
if _fails:
    print("有 FAIL: %s" % _fails)
    sys.exit(1)
print("ALL PASS")
sys.exit(0)
