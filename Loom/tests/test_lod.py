# -*- coding: utf-8 -*-

"""test_lod.py — LOD (距离/屏幕占比) 回归 (M36, 2026-10-14)。
独立文件 (干净 GL context)，避免与 test_texture.py 的大量 GL 资源累积冲突。
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

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)
os.chdir(BASE)
sys.argv[0] = os.path.join(BASE, 'Loom.py')

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
