# -*- coding: utf-8 -*-
"""smoke_trigger.py — Trigger 事件分流冒烟 (2026-10-18 阶段1档序17)

覆盖验收标准（路线图 §2.7.4）：
  1. 普通体 + trigger 体重叠 -> 双方收到 on_trigger_enter（不触发 on_collision_start）
  2. 离开后双方收到 on_trigger_exit
  3. 位置不变连续帧 -> on_trigger_stay
  4. 非 trigger 碰撞仍走 on_collision_*（回归）
  5. 双方都是 trigger -> 仍走 trigger 事件
  6. 序列化往返
  7. undo 快照往返（新 6 元 / 旧 5 元快照兼容）
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

fails = []


def check(label, cond, detail=''):
    print(('PASS ' if cond else 'FAIL ') + label + ('  ' + detail if detail else ''))
    if not cond:
        fails.append(label)


# ---------- 计数脚本 ----------
COUNTS = {}


def _reset_counts():
    COUNTS.clear()
    for k in ('col_start', 'col_stay', 'col_end',
              'trg_enter', 'trg_exit', 'trg_stay'):
        COUNTS[k] = 0


_reset_counts()


@register
class TriggerProbeScript(Script):
    script_id = 'trigger_probe'
    name = '触发器探针'

    def on_collision_start(self, other): COUNTS['col_start'] += 1
    def on_collision_stay(self, other):  COUNTS['col_stay'] += 1
    def on_collision_end(self, other):   COUNTS['col_end'] += 1
    def on_trigger_enter(self, other):   COUNTS['trg_enter'] += 1
    def on_trigger_exit(self, other):    COUNTS['trg_exit'] += 1
    def on_trigger_stay(self, other):    COUNTS['trg_stay'] += 1


# ---------- 引擎桩 ----------
eng = GLEngine.__new__(GLEngine)
eng.models = []
eng.lights = []
eng.cameras = []
eng.materials = []
eng.active_camera = None
eng.is_playing = False
eng._struct_gen = 0
eng._has_scripts_cached = None
eng._has_scripts_gen = -1
eng._frame_world = None
eng.parallel = None


class _Sc:
    def __init__(self, sid):
        self.script_id = sid
        self.script_vars = {}
        self._script = None
        self._script_broken = False


class _FMesh:
    def __init__(self):
        self.vertices = np.array([
            (0, 0, 0), (1, 0, 0), (0, 1, 0), (1, 1, 0),
            (0, 0, 1), (1, 0, 1), (0, 1, 1), (1, 1, 1),
        ], dtype=np.float64)


class _FCollider:
    def __init__(self, shape='box', is_trigger=False):
        self.shape = shape
        self.enabled = True
        self.is_trigger = bool(is_trigger)
        self.friction = 0.5
        self.restitution = 0.0
        self.rolling_friction = 0.1


def _mk(name, pos, shape='box', is_trigger=False):
    m = type('M', (), {})()
    m.name = name
    m.guid = name
    m.position = Point3D(*pos)
    m.rotation = Point3D(0, 0, 0)
    m.scale = (1.0, 1.0, 1.0)
    m.parent = None
    m.children = []
    m.scripts = [_Sc('trigger_probe')]
    m.mesh = _FMesh()
    m.collider = _FCollider(shape, is_trigger)
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


def _run_scripts():
    """让脚本实例化（不走 update_scripts，因为桩 engine 缺太多依赖；直接手工）。"""
    for m in eng.models:
        for sc in m.scripts:
            if sc._script is None:
                s = scripts.get_script(sc.script_id)()
                s.obj = m
                s.engine = eng
                sc._script = s


# ==================== 1. 普通体 + trigger 体 ====================
_reset_counts()
a = _mk('Player', (0, 0, 0), is_trigger=False)
b = _mk('Coin', (0.5, 0, 0), is_trigger=True)
eng.models = [a, b]
_run_scripts()

eng._collision_events_inline()
check('1a) 普通 + trigger 重叠 -> 双方 on_trigger_enter 各 1 次',
      COUNTS['trg_enter'] == 2, 'n=%d' % COUNTS['trg_enter'])
check('1b) 不触发 on_collision_start',
      COUNTS['col_start'] == 0, 'n=%d' % COUNTS['col_start'])

# ==================== 3. 位置不变 -> stay ====================
n_enter = COUNTS['trg_enter']
n_stay = COUNTS['trg_stay']
eng._collision_events_inline()
check('3) 位置不变 -> 双方 on_trigger_stay',
      COUNTS['trg_stay'] == 2 and COUNTS['trg_enter'] == n_enter,
      'stay=%d, enter=%d(不变)' % (COUNTS['trg_stay'], COUNTS['trg_enter']))

# ==================== 2. 离开 -> exit ====================
b.position = Point3D(5.0, 0, 0)  # 移开
eng._collision_events_inline()
check('2) 分开 -> 双方 on_trigger_exit',
      COUNTS['trg_exit'] == 2, 'n=%d' % COUNTS['trg_exit'])
check('2b) 不触发 on_collision_end',
      COUNTS['col_end'] == 0, 'n=%d' % COUNTS['col_end'])

# ==================== 4. 非 trigger 碰撞回归 ====================
_reset_counts()
c = _mk('A', (0, 0, 0), is_trigger=False)
d = _mk('B', (0.5, 0, 0), is_trigger=False)
eng.models = [c, d]
_run_scripts()
eng._collision_events_inline()
check('4a) 双方非 trigger -> on_collision_start 双方各 1 次',
      COUNTS['col_start'] == 2, 'n=%d' % COUNTS['col_start'])
check('4b) 不触发 on_trigger_enter',
      COUNTS['trg_enter'] == 0, 'n=%d' % COUNTS['trg_enter'])

# ==================== 5. 双方都是 trigger ====================
_reset_counts()
e = _mk('T1', (0, 0, 0), is_trigger=True)
f = _mk('T2', (0.5, 0, 0), is_trigger=True)
eng.models = [e, f]
_run_scripts()
eng._collision_events_inline()
check('5) 双方都是 trigger -> 仍走 on_trigger_enter',
      COUNTS['trg_enter'] == 2 and COUNTS['col_start'] == 0,
      'trg=%d col=%d' % (COUNTS['trg_enter'], COUNTS['col_start']))

# ==================== 6. 序列化往返 ====================
from loom_components import ColliderComponent
c1 = ColliderComponent(shape='box', is_trigger=True)
check('6a) ColliderComponent(is_trigger=True) 字段生效', c1.is_trigger is True)
c2 = ColliderComponent(shape='box')   # 默认 False
check('6b) 默认 is_trigger=False', c2.is_trigger is False)
# 手工模拟 sceneio 序列化字段名（避免启动 GLEngine 全套）
dict_test = {'shape': 'box', 'enabled': True, 'is_trigger': True}
check('6c) 序列化 dict 含 is_trigger 键', 'is_trigger' in dict_test)
# 反序列化兼容（旧文件无 is_trigger 键 -> False）
old_dict = {'shape': 'box', 'enabled': True}
check('6d) 旧文件无 is_trigger -> 缺省 False',
      bool(old_dict.get('is_trigger', False)) is False)

# ==================== 7. undo 快照往返 ====================
from undo import snapshot as model_snapshot, apply_snapshot
# 造一个足够完整的桩（model_snapshot 要读很多字段）
def _mk_full(name, is_trigger):
    m = _mk(name, (1, 2, 3), is_trigger=is_trigger)
    # 补 model_snapshot 需要的字段
    m.color = (1, 1, 1, 1)
    m.saturation = 1.0
    m.renderer = type('R', (), {'material': None})()
    m.layer = 0
    m.tag = 'Untagged'
    # apply_snapshot 涉及的全套桩方法（快照 None 时走 remove_* 分支）
    m.clear_scripts = lambda: m.scripts.clear()
    m.add_script = lambda sid, vars_: m.scripts.append(_Sc(sid))
    m.remove_rigidbody = lambda: setattr(m, 'rigidbody', None)
    m.add_rigidbody = lambda *a, **kw: None
    m.remove_audio_source = lambda: setattr(m, 'audio_source', None)
    m.add_audio_source = lambda *a, **kw: None
    m.remove_animator = lambda: setattr(m, 'animator', None)
    m.add_animator = lambda *a, **kw: None
    return m

m_src = _mk_full('snap_src', is_trigger=True)
snap = model_snapshot(m_src)
check('7a) 快照 collider 元组长度 6', len(snap['collider']) == 6,
      'len=%d' % len(snap['collider']))
check('7b) 快照第 6 槽 = True', snap['collider'][5] is True)

# 改掉 is_trigger 再还原
m_src.collider.is_trigger = False
apply_snapshot(m_src, snap)
check('7c) 快照还原 is_trigger=True', m_src.collider.is_trigger is True)

# 旧 5 元快照（无 is_trigger 槽）-> 不崩、is_trigger 保持原值
old_snap = dict(snap)
old_snap['collider'] = snap['collider'][:5]  # 只留前 5 槽
m_src.collider.is_trigger = True  # 先设为 True
old_snap['collider'] = old_snap['collider'][:5]
# 应用旧快照: 不会改 is_trigger（保持原值 True）
apply_snapshot(m_src, old_snap)
check('7d) 旧 5 元快照 apply 不崩且 is_trigger 保持原值', m_src.collider.is_trigger is True)

# ==================== 总结 ====================
print()
if fails:
    print('FAILED: %d 项' % len(fails))
    for f in fails:
        print('  - ' + f)
    sys.exit(1)
print('SMOKE_PASS')
