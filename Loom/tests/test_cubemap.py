# -*- coding: utf-8 -*-
"""test_cubemap.py — Cubemap 环境反射回归 (M36, 2026-10-14)。
独立文件 (干净 GL context)。
"""
import os
import sys
import tempfile

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)
os.chdir(BASE)
sys.argv[0] = os.path.join(BASE, 'Loom.py')

import numpy as np
import moderngl
from loom_cubemap import Cubemap

_fails = []


def check(name, cond, detail=''):
    print("%s %s  %s" % ("PASS" if cond else "FAIL", name, detail))
    if not cond:
        _fails.append(name)


# ---- Cubemap 资产 ----
c = Cubemap.from_solid((200, 100, 50), size=8)
check("from_solid 尺寸", c.size == 8 and len(c._faces) == 6, "%d/%d" % (c.size, len(c._faces)))
check("from_solid guid 稳定", bool(c.guid), c.guid[:8])

import pygame
pygame.init()
# 6 面文件
paths = []
for i in range(6):
    surf = pygame.Surface((4, 4)); surf.fill((i * 40 % 256, 100, 50))
    p = os.path.join(tempfile.gettempdir(), '_cube_%d.png' % i)
    pygame.image.save(surf, p); paths.append(p)
c2 = Cubemap.from_files(paths)
check("from_files 加载", c2.size == 4 and len(c2._faces) == 6, "%d" % c2.size)
check("from_files 记录路径", c2.paths is not None and len(c2.paths) == 6, "")
for p in paths:
    os.remove(p)
try:
    Cubemap.from_files(paths[:3])
    check("from_files 面数不足报错", False, "未报错")
except ValueError:
    check("from_files 面数不足报错", True)

# ---- GPU ----
ctx = moderngl.create_standalone_context()
g = c.ensure_gl(ctx)
check("ensure_gl 可用", g is not None and g.size == (8, 8), str(g.size))
c.release()
check("release 后 gl_tex 为 None", c.gl_tex is None, "")
ctx.release()

# ---- 材质 env_map 槽 ----
from loom_material import Material
mat = Material(color='#FFFFFF')
check("材质默认无 env", mat.env_map is None and mat._env_guid == '', "")
mat.env_map = Cubemap.from_solid('#8080FF', size=4)
check("材质设 env", mat.env_map is not None and mat._env_guid != '', mat._env_guid[:8])
mat.env_map = None
check("材质清 env", mat.env_map is None and mat._env_guid == '', "")

# ---- set_env 命令 ----
import editor as editor_mod
import engine as E
import agent_commands as ac
from mesh import create_cube
ctx2 = moderngl.create_standalone_context()
ed = editor_mod.EditorApp(320, 240, ctx=ctx2)
ed._external_fb = ctx2.detect_framebuffer()
try:
    _g = ed.view.gui.render
    ed.view.gui.render = lambda *a, **k: _g(target=ed._external_fb)
except Exception:
    pass
ed.load_scene(os.path.join(BASE, '保存', '压力测试', '压力_空场景.json'))
obj = ed.add_model(create_cube(1.0), E.Point3D(0, 0, 0), E.Point3D(0, 0, 0), name='反射块')
class _Win:
    editor = ed
r = ac.dispatch('set_env', {'name': '反射块', 'color': '#FF8800'}, _Win())
check("set_env 纯色命令", r.get('ok') is True and obj.renderer.material.env_map is not None,
      str(r.get('result')))
k = ed._mesh_key(obj)
check("桶键含 env guid", len(k) == 7 and k[6] != '', "len=%d k[6]=%s" % (len(k), k[6][:8]))
r2 = ac.dispatch('set_env', {'name': '反射块'}, _Win())
check("set_env 清除", r2.get('ok') is True and obj.renderer.material.env_map is None, "")

# 渲染不崩
obj.renderer.material.env_map = Cubemap.from_solid('#FF0000', size=8)
obj.renderer.material.pbr = True
for _ in range(3):
    ed.render(1 / 60.0)
check("渲染不崩", len(ed._render_buckets) >= 1, "%d 桶" % len(ed._render_buckets))

ed._stop_parallel()
pygame.quit()
print("")
if _fails:
    print("有 FAIL: %s" % _fails)
    sys.exit(1)
print("ALL PASS")
sys.exit(0)
