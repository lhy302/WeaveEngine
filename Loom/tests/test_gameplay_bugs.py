# -*- coding: utf-8 -*-

"""test_gameplay_bugs.py — 小游戏实测发现的两个 bug 回归 (2026-10-14)。"""

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
import editor as editor_mod
# 2026-11-06: 测试不得改动仓库内的 保存/ 目录 —— EditorApp.__init__ 首次运行会把
# 保存/ 迁移为 Projects/ (线上正确行为), 但测试跑一次就把受版本控制的数据搬走。
# 把两个目录常量重定向到临时目录, 迁移逻辑面对空目录 = 零副作用。
import tempfile as _tf_save
_SAVE_ROOT = _tf_save.mkdtemp(prefix="loom_test_save_")
editor_mod.DEFAULT_SAVE_DIR = os.path.join(_SAVE_ROOT, "Projects")
editor_mod._LEGACY_SAVE_DIR = os.path.join(_SAVE_ROOT, "保存")
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
class _FakeUIManager:
    """最小 Canvas UI 替身: 只满足 count_touch 用到的 default_canvas().root.add_child."""
    class _Root:
        def __init__(self):
            self.children = []
        def add_child(self, el):
            self.children.append(el)
            return el
    def __init__(self):
        self._c = type('_C', (), {'root': _FakeUIManager._Root()})()
    def default_canvas(self):
        return self._c
    def text(self, *a, **k):
        return None


class _FakeEngine:
    def __init__(self):
        self.models = []
        self._count_hits = 0
        # 2026-11-06 桩同步: count_touch 的 on_start 已从 RuntimeUI 改走
        # Canvas UI 保留模式 (loom_ui.UIManager.default_canvas().root.add_child),
        # 旧桩只有 text() -> AttributeError。
        self.ui = _FakeUIManager()
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
