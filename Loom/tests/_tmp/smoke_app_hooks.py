# -*- coding: utf-8 -*-
"""smoke_app_hooks.py — 应用级钩子冒烟 (2026-10-19 第1档序7)

覆盖：
  1) on_application_quit 派发一次（幂等）
  2) on_became_visible / on_became_invisible 派发
  3) 未覆盖的脚本走零开销快路径（不报错）
  4) 异常隔离（一个脚本报错不影响下一个）
"""
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

fails = []


def check(label, cond, detail=''):
    msg = ('PASS ' if cond else 'FAIL ') + label
    if detail:
        msg += '  ' + str(detail)
    print(msg)
    if not cond:
        fails.append(label)


LOG = []


@register
class AppHookProbe(Script):
    script_id = 'app_hook_probe'
    name = '应用钩子探针'

    def on_application_quit(self):
        LOG.append('quit')

    def on_became_visible(self):
        LOG.append('visible')

    def on_became_invisible(self):
        LOG.append('invisible')


@register
class BadQuitProbe(Script):
    script_id = 'bad_quit_probe'
    name = '坏退出探针'

    def on_application_quit(self):
        raise RuntimeError('intentional')


@register
class EmptyProbe(Script):
    """只定义 script_id / name，不覆盖任何钩子（测试零开销路径）"""
    script_id = 'empty_probe'
    name = '空脚本'


print('=== Part A: 基础派发 ===')

# 构造引擎 + 3 个物体各挂 1 个脚本
engine = GLEngine.__new__(GLEngine)
# 手动最小初始化（避免 GL 上下文）
engine.models = []
engine._app_quit_dispatched = False


def _mk_model(name, script_id):
    m = type('M', (), {})()
    m.name = name
    m.scripts = []
    sc = type('SC', (), {})()
    sc.script_id = script_id
    sc._script = None
    sc._script_broken = False
    sc.script_vars = {}
    m.scripts.append(sc)
    return m, sc


m1, sc1 = _mk_model('obj1', 'app_hook_probe')
m2, sc2 = _mk_model('obj2', 'bad_quit_probe')
m3, sc3 = _mk_model('obj3', 'empty_probe')
engine.models = [m1, m2, m3]

# 手动创建脚本实例（模拟 update_scripts 的实例化）
for sc in (sc1, sc2, sc3):
    cls = scripts.get_script(sc.script_id)
    inst = cls()
    inst.obj = engine.models[0]
    inst.engine = engine
    sc._script = inst

# 派发 on_application_quit
engine._dispatch_application_quit()

check('A1 quit 派发到 app_hook_probe', 'quit' in LOG, LOG)
check('A2 quit 只派发一次（幂等）', LOG.count('quit') == 1, LOG)
check('A3 坏脚本触发异常但被隔离',
      sc2._script_broken is True, 'broken=%r' % sc2._script_broken)
check('A4 空脚本无异常', sc3._script_broken is False)

# 再派发一次（幂等）
engine._dispatch_application_quit()
check('A5 第二次派发被幂等拦截', LOG.count('quit') == 1, LOG)


print()
print('=== Part B: 可见性派发 ===')

LOG.clear()
engine._dispatch_visibility_changed(False)
check('B1 on_became_invisible 派发', 'invisible' in LOG, LOG)

LOG.clear()
engine._dispatch_visibility_changed(True)
check('B2 on_became_visible 派发', 'visible' in LOG, LOG)

# 空脚本不参与
check('B3 空脚本从未被派发（零开销路径）', 'quit' not in LOG and 'invisible' not in LOG)


print()
print('=== Part C: 异常隔离（可见性）===')


@register
class BadVisibleProbe(Script):
    script_id = 'bad_visible_probe'
    name = '坏可见性探针'

    def on_became_visible(self):
        raise RuntimeError('intentional visible')


m4, sc4 = _mk_model('obj4', 'bad_visible_probe')
engine.models.append(m4)
cls = scripts.get_script(sc4.script_id)
inst = cls()
inst.obj = m4
inst.engine = engine
sc4._script = inst

LOG.clear()
engine._dispatch_visibility_changed(True)
check('C1 bad_visible_probe 标记 broken', sc4._script_broken is True)
check('C2 正常脚本仍收到 visible', 'visible' in LOG, LOG)


print()
print('=== Part D: 已 broken 的脚本不参与后续派发 ===')

LOG.clear()
engine._dispatch_visibility_changed(False)
check('D1 broken 脚本不触发（broken 标志生效）',
      LOG.count('invisible') == 1, LOG)


print()
if fails:
    print('FAILED %d 项: %s' % (len(fails), fails))
    sys.exit(1)
else:
    print('ALL PASS (9 项)')
