# -*- coding: utf-8 -*-

"""test_cubemap.py — Cubemap 环境反射回归 (M36, 2026-10-14)。
独立文件 (干净 GL context)。
"""

# 2026-11-06 P-02 修复: Windows 控制台默认 GBK, 末尾 print 的 ✅/❌/≤ 等字符会抛
# UnicodeEncodeError, 让"测试通过"被记录成 exit=1 的假失败 (48/51 曾被误判)。
# 统一把 stdout/stderr 切到 UTF-8(replace), 失败信号重新只由断言决定。
import sys as _sys_utf8
try:
    _sys_utf8.stdout.reconfigure(encoding='utf-8', errors='replace')
    _sys_utf8.stderr.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

# 2026-11-06 失败退出码闸门 (复核 A 指出: 54 个测试里仅 18 个有 sys.exit(1),
# 其余 FAIL 也 exit 0 -> run_all 假绿, 失败被静默吞掉)。
# 做法: 包一层 stdout, 出现以 "FAIL" 开头的行就在进程退出时把状态码改成 1。
# 只在真出现 FAIL 时才改码, 全 PASS 的测试行为完全不变。
import atexit as _atexit_gate
import os as _os_gate
import sys as _sys_gate


class _FailGateStream:
    def __init__(self, stream):
        self._stream = stream
        self.failed = False

    def write(self, text):
        if isinstance(text, str) and (text.startswith("FAIL") or "\nFAIL" in text):
            self.failed = True
        return self._stream.write(text)

    def __getattr__(self, name):
        return getattr(self._stream, name)


_fail_gate = _FailGateStream(_sys_gate.stdout)
_sys_gate.stdout = _fail_gate


@_atexit_gate.register
def _enforce_fail_exit_code():
    if not _fail_gate.failed:
        return
    try:
        _sys_gate.stdout.flush()
        _sys_gate.stderr.flush()
    except Exception:
        pass
    _os_gate._exit(1)


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
# 2026-11-06: 测试不得改动仓库内的 保存/ 目录 —— EditorApp.__init__ 首次运行会把
# 保存/ 迁移为 Projects/ (线上正确行为), 但测试跑一次就把受版本控制的数据搬走。
# 把两个目录常量重定向到临时目录, 迁移逻辑面对空目录 = 零副作用。
import tempfile as _tf_save
_SAVE_ROOT = _tf_save.mkdtemp(prefix="loom_test_save_")
editor_mod.DEFAULT_SAVE_DIR = os.path.join(_SAVE_ROOT, "Projects")
editor_mod._LEGACY_SAVE_DIR = os.path.join(_SAVE_ROOT, "保存")
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
