# -*- coding: utf-8 -*-
"""script_lifecycle_check.py — C1 脚本生命周期钩子探针.

验证 on_enable / on_disable / on_destroy / on_collision_stay 四钩子触发次数.

跑法: py -3.12 tests/_tmp/script_lifecycle_check.py
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
from engine import GLEngine, Point3D
from mesh import create_cube, create_sphere

fails = []


def check(label, cond, detail=''):
    print(('PASS ' if cond else 'FAIL ') + label + ('  ' + detail if detail else ''))
    if not cond:
        fails.append(label)


# 定义一个计数脚本
COUNTS = {'enable': 0, 'start': 0, 'update': 0, 'disable': 0,
          'destroy': 0, 'collision_start': 0, 'collision_stay': 0,
          'collision_end': 0}


@register
class LifecycleProbeScript(Script):
    script_id = 'lifecycle_probe'
    name = '生命周期探针'

    def on_enable(self):
        COUNTS['enable'] += 1

    def on_start(self):
        COUNTS['start'] += 1

    def on_disable(self):
        COUNTS['disable'] += 1

    def on_destroy(self):
        COUNTS['destroy'] += 1

    def update(self, dt):
        COUNTS['update'] += 1

    def on_collision_start(self, other):
        COUNTS['collision_start'] += 1

    def on_collision_stay(self, other):
        COUNTS['collision_stay'] += 1

    def on_collision_end(self, other):
        COUNTS['collision_end'] += 1


eng = GLEngine.__new__(GLEngine)
# 最小初始化：模拟 EditorApp 的必备字段
eng.models = []
eng.lights = []
eng.cameras = []
eng.materials = []
eng.active_camera = None
eng.current_model_index = 0
eng.is_playing = False
eng._struct_gen = 0
eng._has_scripts_cached = None
eng._has_scripts_gen = -1

# 挂载脚本组件
class _Sc:
    def __init__(self, sid):
        self.script_id = sid
        self.script_vars = {}
        self._script = None
        self._script_broken = False

# 建 2 个物体（用桩避免 GPU 依赖）
class _FMesh:
    def __init__(self):
        self.vertices = np.array([(0,0,0),(1,0,0),(0,1,0),(1,1,0),
                                  (0,0,1),(1,0,1),(0,1,1),(1,1,1)], dtype=np.float64)
class _FCollider:
    def __init__(self, shape):
        self.shape = shape
        self.enabled = True

def _mk_model(name, pos, shape='box'):
    m = type('M', (), {})()
    m.name = name
    m.guid = name
    m.position = Point3D(*pos)
    m.rotation = Point3D(0, 0, 0)
    m.scale = (1.0, 1.0, 1.0)
    m.parent = None
    m.children = []
    m.scripts = []
    m.mesh = _FMesh()
    m.collider = _FCollider(shape)
    m.rigidbody = None
    m.animator = None
    m.audio_source = None
    m.camera_children = []
    m.visible = True
    m.vbo = None
    m.vao = None
    m._shadow_vao = None
    m._shadow_vbo = None
    m._colliding = set()
    return m

m1 = _mk_model('A', (0, 0, 0))
m2 = _mk_model('B', (0.5, 0, 0))   # 与 m1 相邻接触
m1.scripts.append(_Sc('lifecycle_probe'))
m2.scripts.append(_Sc('lifecycle_probe'))
eng.models = [m1, m2]

# ---- 测试 1: on_enable + on_start ----
eng.update_scripts(0.016)
check('on_enable 调 2 次 (每物体脚本实例化)', COUNTS['enable'] == 2, 'n=%d' % COUNTS['enable'])
check('on_start 调 2 次', COUNTS['start'] == 2, 'n=%d' % COUNTS['start'])
check('update 调 2 次', COUNTS['update'] == 2, 'n=%d' % COUNTS['update'])

# ---- 测试 2: on_collision_start + on_collision_stay ----
# 用 _collision_events_inline 触发（走 _call_collision_cb）
# 需 collider_bounds / _pair_overlap / _related / _frame_world
eng._frame_world = None
eng._collision_events_inline()
check('on_collision_start 至少 1 次 (m1 与 m2 相撞)',
      COUNTS['collision_start'] >= 1, 'n=%d' % COUNTS['collision_start'])
n_start_before = COUNTS['collision_start']
n_stay_before = COUNTS['collision_stay']
# 再跑一帧：位置不变，应触发 stay 而不触发 start
eng._collision_events_inline()
check('on_collision_stay 触发 (集合不变但脚本覆盖 stay)',
      COUNTS['collision_stay'] > n_stay_before,
      'n_stay=%d -> %d' % (n_stay_before, COUNTS['collision_stay']))
check('on_collision_start 不再触发 (集合不变)',
      COUNTS['collision_start'] == n_start_before,
      'n_start=%d -> %d' % (n_start_before, COUNTS['collision_start']))

# ---- 测试 3: on_disable ----
# 直接调 on_disable（模拟 toggle_play 退出逻辑）
for m in eng.models:
    for sc in m.scripts:
        inst = sc._script
        if inst is not None:
            inst.on_disable()
check('on_disable 调 2 次', COUNTS['disable'] == 2, 'n=%d' % COUNTS['disable'])

# ---- 测试 4: on_destroy ----
# 直接调 on_destroy（模拟 remove_model）
for m in eng.models:
    for sc in m.scripts:
        inst = sc._script
        if inst is not None:
            inst.on_destroy()
check('on_destroy 调 2 次', COUNTS['destroy'] == 2, 'n=%d' % COUNTS['destroy'])

# ---- 测试 5: 未定义 on_collision_stay 的脚本走快路径 ----
COUNTS2 = {'update': 0}

@register
class NoStayScript(Script):
    script_id = 'no_stay'
    name = '无 stay'

    def update(self, dt):
        COUNTS2['update'] += 1

# 新物体挂 NoStayScript，应不破坏"无事件零开销"
m3 = _mk_model('C', (10, 0, 0))
m4 = _mk_model('D', (10.5, 0, 0))
m3.scripts.append(_Sc('no_stay'))
m4.scripts.append(_Sc('no_stay'))
eng.models = [m3, m4]
eng._struct_gen = 1
eng._collision_events_inline()   # 应走原快路径（集合不变 → continue）
# 应不崩、且 stay 计数不变
check('无 stay 脚本物体不触发 stay', COUNTS['collision_stay'] > n_stay_before)

print('ALL PASS' if not fails else '%d FAIL: %r' % (len(fails), fails))
sys.exit(0 if not fails else 1)
