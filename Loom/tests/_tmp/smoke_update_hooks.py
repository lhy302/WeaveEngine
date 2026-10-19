# -*- coding: utf-8 -*-
"""smoke_update_hooks.py — FixedUpdate/LateUpdate/执行顺序 冒烟 (2026-10-18 第1档序10/11/12)"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
BASE = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, BASE)
os.chdir(BASE)

import numpy as np
import pygame
pygame.init()
pygame.display.set_mode((1, 1), pygame.HIDDEN)

import scripts
from scripts import Script, register
from engine import GLEngine
import scene_driver as SD

fails = []


def check(label, cond, detail=''):
    msg = ('PASS ' if cond else 'FAIL ') + label
    if detail:
        msg += '  ' + str(detail)
    print(msg)
    if not cond:
        fails.append(label)


LOG = []


# ====== 定义 3 个测试脚本 ======
@register
class HookProbeScript(Script):
    script_id = 'hook_probe'
    name = '钩子探针'
    def on_fixed_update(self, dt): LOG.append(('fixed', self.obj.name, round(dt, 3)))
    def on_late_update(self, dt): LOG.append(('late', self.obj.name, round(dt, 3)))
    def update(self, dt): LOG.append(('update', self.obj.name, self.order))


@register
class NoHooksScript(Script):
    """不覆盖任何钩子 —— 应零开销跳过 Fixed/Late。"""
    script_id = 'no_hooks'
    name = '无钩子'
    def update(self, dt): LOG.append(('update_no_hooks', self.obj.name))


@register
class EarlyScript(Script):
    script_id = 'early'
    name = '早执行'
    order = -100
    def update(self, dt): LOG.append(('early', self.obj.name))


@register
class LateScript(Script):
    script_id = 'late_order'
    name = '晚执行'
    order = 100
    def update(self, dt): LOG.append(('late_order', self.obj.name))


@register
class CrashScript(Script):
    script_id = 'crash_fixed'
    name = '崩Fixed'
    def on_fixed_update(self, dt): raise RuntimeError('故意崩')


# ====== 桩 ======
class _Sc:
    def __init__(self, sid):
        self.script_id = sid
        self.script_vars = {}
        self._script = None
        self._script_broken = False


class _M:
    def __init__(self, name):
        self.name = name
        self.scripts = []


def make_eng():
    e = GLEngine.__new__(GLEngine)
    e.models = []
    e._struct_gen = 0
    e._has_scripts_cached = None
    e._has_scripts_gen = -1
    return e


def add_script(m, sid):
    sc = _Sc(sid)
    m.scripts.append(sc)
    return sc


def instantiate_all(e):
    """预实例化所有脚本（避免 update_scripts 里惰性实例化干扰顺序观察）。"""
    for m in e.models:
        for sc in m.scripts:
            if sc._script is None and sc.script_id:
                cls = scripts.get_script(sc.script_id)
                if cls is not None:
                    s = cls()
                    s.obj = m
                    s.engine = e
                    sc._script = s


# ==================== 1. on_fixed_update 派发 ====================
LOG.clear()
e = make_eng()
m1 = _M('obj1'); m1.scripts = [_Sc('hook_probe')]; e.models = [m1]
instantiate_all(e)
e._dispatch_fixed_update(0.033)
check('1) on_fixed_update 被调', LOG == [('fixed', 'obj1', 0.033)], LOG)

# ==================== 2. 基类空实现跳过 ====================
LOG.clear()
e = make_eng()
m2 = _M('obj2'); m2.scripts = [_Sc('no_hooks')]; e.models = [m2]
instantiate_all(e)
e._dispatch_fixed_update(0.033)
check('2) 未覆盖 on_fixed_update 零开销跳过', LOG == [], LOG)

# ==================== 3. on_late_update 派发 ====================
LOG.clear()
e = make_eng()
m3 = _M('obj3'); m3.scripts = [_Sc('hook_probe')]; e.models = [m3]
instantiate_all(e)
e._dispatch_late_update(0.016)
check('3) on_late_update 被调', LOG == [('late', 'obj3', 0.016)], LOG)

# ==================== 4. LateUpdate 基类跳过 ====================
LOG.clear()
e = make_eng()
m4 = _M('obj4'); m4.scripts = [_Sc('no_hooks')]; e.models = [m4]
instantiate_all(e)
e._dispatch_late_update(0.016)
check('4) 未覆盖 on_late_update 零开销跳过', LOG == [], LOG)

# ==================== 5. order 排序 ====================
LOG.clear()
e = make_eng()
m5 = _M('m5'); m5.scripts = [_Sc('hook_probe'), _Sc('late_order'), _Sc('early')]
e.models = [m5]
# 需要 script.dll
try:
    e.update_scripts(0.016)
except Exception:
    pass
updates = [x for x in LOG if x[0] in ('update', 'early', 'late_order')]
check('5) order 排序：early(-100) → update(0) → late_order(100)',
      len(updates) >= 3 and updates[0][0] == 'early'
      and updates[-1][0] == 'late_order', updates)

# ==================== 6. 相同 order 稳定排序 ====================
LOG.clear()
e = make_eng()
m6a = _M('A'); m6a.scripts = [_Sc('hook_probe')]
m6b = _M('B'); m6b.scripts = [_Sc('hook_probe')]
e.models = [m6a, m6b]
try:
    e.update_scripts(0.016)
except Exception:
    pass
updates = [x for x in LOG if x[0] == 'update']
check('6) 同 order 保持物体顺序 (A → B)',
      len(updates) == 2 and updates[0][1] == 'A' and updates[1][1] == 'B', updates)

# ==================== 7. 异常隔离 ====================
LOG.clear()
e = make_eng()
m7 = _M('obj7')
sc_crash = _Sc('crash_fixed')
sc_ok = _Sc('hook_probe')
m7.scripts = [sc_crash, sc_ok]
e.models = [m7]
instantiate_all(e)
e._dispatch_fixed_update(0.033)
check('7a) 崩脚本被标记 broken', sc_crash._script_broken is True)
check('7b) 后续正常脚本仍被调', LOG == [('fixed', 'obj7', 0.033)], LOG)

# ==================== 8. 坏脚本跳过 ====================
LOG.clear()
e = make_eng()
m8 = _M('obj8')
sc_bad = _Sc('hook_probe')
sc_bad._script_broken = True
m8.scripts = [sc_bad]
e.models = [m8]
instantiate_all(e)
e._dispatch_fixed_update(0.033)
check('8) _script_broken=True 跳过', LOG == [], LOG)

# ==================== 9. Vk 后端派发 ====================
LOG.clear()
vk = SD.SceneDriver.__new__(SD.SceneDriver)
vk.models = []
vm = _M('vk_obj'); vm.scripts = [_Sc('hook_probe')]
vk.models = [vm]
instantiate_all(vk)
vk._dispatch_fixed_update(0.033)
check('9a) Vk 后端 on_fixed_update 派发', LOG == [('fixed', 'vk_obj', 0.033)], LOG)
LOG.clear()
vk._dispatch_late_update(0.016)
check('9b) Vk 后端 on_late_update 派发', LOG == [('late', 'vk_obj', 0.016)], LOG)

print()
if fails:
    print('FAILED: %d 项' % len(fails))
    for f in fails:
        print('  - ' + f)
    sys.exit(1)
print('SMOKE_PASS')
