# -*- coding: utf-8 -*-
"""smoke_world_ui.py — World Space UI 冒烟 (2026-10-19 第1档序3阶段4)

覆盖：
  Part A - Canvas 数据模型（默认值 + 字段）
  Part B - 序列化（world 三字段 + target_id 绑定）
  Part C - 反序列化（_apply_ui + _link_ui_targets 二次绑定）
  Part D - EAI dispatch ui_canvas_add / ui_canvas_set / ui_list
  Part E - screen Canvas 不带 world 字段（回归）
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

import loom_ui
import sceneio
from engine import GLEngine, Point3D

fails = []


def check(label, cond, detail=''):
    msg = ('PASS ' if cond else 'FAIL ') + label
    if detail:
        msg += '  ' + str(detail)
    print(msg)
    if not cond:
        fails.append(label)


def _make_engine():
    """最小化引擎桩（避开 GL 上下文初始化）."""
    e = GLEngine.__new__(GLEngine)
    e.models = []
    e.lights = []
    e.cameras = []
    e.materials = []
    e.active_camera = None
    e.gravity = -9.8
    e._skybox = None
    e.is_playing = False
    e.width = 1280
    e.height = 800
    e.ui = loom_ui.UIManager()
    e.undo = None
    return e


def _make_model(engine, name, guid=None):
    m = type('M', (), {})()
    m.name = name
    m.guid = guid or name
    m.position = Point3D(1, 2, 3)
    m.rotation = Point3D(0, 0, 0)
    m.scale = (1, 1, 1)
    m.parent = None
    m.children = []
    m.scripts = []
    engine.models.append(m)
    return m


print('=== Part A: Canvas 默认值 ===')

c_default = loom_ui.Canvas(canvas_type='world')
check('A1 world_scale 默认 0.01', c_default.world_scale == 0.01)
check('A2 billboard 默认 True', c_default.billboard is True)
check('A3 target 默认 None', c_default.target is None)

c_custom = loom_ui.Canvas(canvas_type='world', world_scale=0.02,
                          billboard=False, target=None)
check('A4 自定义字段生效',
      c_custom.world_scale == 0.02 and c_custom.billboard is False)

c_screen = loom_ui.Canvas(canvas_type='screen')
check('A5 screen 模式 canvas_type=screen', c_screen.canvas_type == 'screen')


print()
print('=== Part B: 序列化 ===')

engine = _make_engine()
m_tgt = _make_model(engine, '玩家', 'guid-player')
c_world = loom_ui.Canvas(canvas_type='world', width=400, height=200,
                          target=m_tgt, world_scale=0.01, billboard=True)
engine.ui.add_canvas(c_world)

ui_dict = sceneio._emit_ui(engine.ui)
check('B1 canvases 长度 1', len(ui_dict['canvases']) == 1)
cd = ui_dict['canvases'][0]
check('B2 target_id = guid-player', cd.get('target_id') == 'guid-player',
      cd.get('target_id'))
check('B3 world_scale = 0.01', abs(cd.get('world_scale', 0) - 0.01) < 1e-9)
check('B4 billboard = True', cd.get('billboard') is True)


print()
print('=== Part C: 反序列化（target 二次绑定）===')

engine2 = _make_engine()
sceneio._apply_ui(engine2, ui_dict)
check('C1 _apply_ui 后 1 个 canvas', len(engine2.ui.canvases) == 1)
c2 = engine2.ui.canvases[0]
check('C2 canvas_type = world', c2.canvas_type == 'world')
check('C3 _pending_target_id 已暂存',
      getattr(c2, '_pending_target_id', None) == 'guid-player',
      getattr(c2, '_pending_target_id', None))
check('C4 target 此时仍为 None', c2.target is None)
check('C5 world_scale = 0.01', abs(c2.world_scale - 0.01) < 1e-9)
check('C6 billboard = True', c2.billboard is True)

# 模拟 objects 已建好
m2 = _make_model(engine2, '玩家', 'guid-player')
# 二次绑定
sceneio._link_ui_targets(engine2)
check('C7 target 已绑定', c2.target is not None, c2.target)
if c2.target is not None:
    check('C8 target.name = 玩家', c2.target.name == '玩家')
check('C9 _pending_target_id 已清理',
      not hasattr(c2, '_pending_target_id'))


print()
print('=== Part D: EAI dispatch ===')

import agent_commands as ac


class FakeWin:
    def __init__(self, engine):
        self.editor = engine


win2 = FakeWin(engine2)

# ui_canvas_add 带 target/world_scale/billboard
r = ac.dispatch('ui_canvas_add', {
    'type': 'world', 'width': 300, 'height': 100,
    'target': '玩家', 'world_scale': 0.02, 'billboard': False}, win2)
check('D1 ui_canvas_add 成功', r.get('ok') is True, r.get('error'))
res = r.get('result', {})
check('D2 total=2', res.get('total') == 2)
check('D3 target=玩家', res.get('target') == '玩家')
check('D4 world_scale=0.02', abs(res.get('world_scale', 0) - 0.02) < 1e-9)
check('D5 billboard=False', res.get('billboard') is False)

# ui_canvas_set 修改
r2 = ac.dispatch('ui_canvas_set', {
    'canvas': 1, 'world_scale': 0.005, 'billboard': True, 'width': 500}, win2)
check('D6 ui_canvas_set 成功', r2.get('ok') is True, r2.get('error'))
c_new = engine2.ui.canvases[1]
check('D7 world_scale 已改 0.005', abs(c_new.world_scale - 0.005) < 1e-9)
check('D8 billboard 已改 True', c_new.billboard is True)
check('D9 width 已改 500', c_new.width == 500)

# ui_canvas_set 解绑 target
r3 = ac.dispatch('ui_canvas_set', {'canvas': 1, 'target': ''}, win2)
check('D10 解绑 target 成功', r3.get('ok') is True, r3.get('error'))
check('D11 target 已清空', c_new.target is None)

# ui_list 输出验证
r_list = ac.dispatch('ui_list', {}, win2)
check('D12 ui_list 成功', r_list.get('ok') is True, r_list.get('error'))
canvases = r_list.get('result', {}).get('canvases', [])
check('D13 有 2 个 canvas', len(canvases) == 2)
if len(canvases) >= 1:
    cv0 = canvases[0]
    check('D14 canvas0 含 target 字段', 'target' in cv0)
    check('D15 canvas0 target=玩家', cv0.get('target') == '玩家')
    check('D16 canvas0 含 world_scale', 'world_scale' in cv0)
    check('D17 canvas0 含 billboard', 'billboard' in cv0)
if len(canvases) >= 2:
    cv1 = canvases[1]
    check('D18 canvas1 target=None（已解绑）', cv1.get('target') is None)


print()
print('=== Part E: screen Canvas 回归 ===')

engine3 = _make_engine()
c_sc = loom_ui.Canvas(canvas_type='screen', width=1920, height=1080)
engine3.ui.add_canvas(c_sc)
ui_dict_sc = sceneio._emit_ui(engine3.ui)
cd_sc = ui_dict_sc['canvases'][0]
check('E1 screen 序列化不含 target_id', 'target_id' not in cd_sc)
check('E2 screen 序列化不含 world_scale', 'world_scale' not in cd_sc)
check('E3 screen 序列化不含 billboard', 'billboard' not in cd_sc)
# 反序列化也回归
engine4 = _make_engine()
sceneio._apply_ui(engine4, ui_dict_sc)
check('E4 screen 反序列化正常',
      len(engine4.ui.canvases) == 1 and engine4.ui.canvases[0].canvas_type == 'screen')


print()
print('=== Part F: 边界情况 ===')

# target 物体不存在 -> 渲染时跳过（不崩）
engine5 = _make_engine()
sceneio._apply_ui(engine5, ui_dict)  # target_id='guid-player' 但没物体
sceneio._link_ui_targets(engine5)     # 物体空 -> target 保持 None
c5 = engine5.ui.canvases[0]
check('F1 target 不存在时 target=None 不崩', c5.target is None)

# ui_canvas_set 中 target 名不存在 -> 报错
r_f = ac.dispatch('ui_canvas_set', {'canvas': 0, 'target': '不存在的物体'}, win2)
check('F2 target 不存在时报错', r_f.get('ok') is False)


print()
if fails:
    print('FAILED %d 项: %s' % (len(fails), fails))
    sys.exit(1)
else:
    print('ALL PASS (32 项)')
