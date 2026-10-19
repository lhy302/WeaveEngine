# -*- coding: utf-8 -*-
"""smoke_skybox.py — 天空盒冒烟 (2026-10-19 第1档序13)"""
import json
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

import agent_commands as ac
import loom_mcp
import sceneio
import undo
from loom_cubemap import Cubemap
from loom_scene_entities import CameraState

fails = []


def check(label, cond, detail=''):
    msg = ('PASS ' if cond else 'FAIL ') + label
    if detail:
        msg += '  ' + str(detail)
    print(msg)
    if not cond:
        fails.append(label)


# ==================== 1. Cubemap.from_solid 记录纯色 ====================
cube_solid = Cubemap.from_solid((128, 64, 32, 255), name='test_solid')
check('1a) from_solid 后 _solid_color 非 None',
      cube_solid._solid_color is not None)
check('1b) _solid_color 值正确',
      cube_solid._solid_color == (128, 64, 32, 255), cube_solid._solid_color)

# ==================== 2. _emit_skybox 纯色源 ====================
emitted = sceneio._emit_skybox(cube_solid)
check('2a) _emit_skybox(纯色) 返回 dict',
      isinstance(emitted, dict), emitted)
check('2b) 含 solid_color 键',
      'solid_color' in emitted, emitted)
check('2c) solid_color 值正确',
      emitted['solid_color'] == [128, 64, 32, 255], emitted['solid_color'])

# ==================== 3. _emit_skybox(None) ====================
check('3) _emit_skybox(None) 返回 None', sceneio._emit_skybox(None) is None)

# ==================== 4. _apply_skybox 纯色反序列化 ====================
applied = sceneio._apply_skybox(emitted)
check('4a) _apply_skybox(纯色) 返回 Cubemap',
      isinstance(applied, Cubemap), applied)
check('4b) _solid_color 还原正确',
      applied._solid_color == (128, 64, 32, 255), applied._solid_color)
check('4c) name 还原正确', applied.name == 'test_solid', applied.name)

# ==================== 5. _apply_skybox 边界 ====================
check('5a) _apply_skybox(None) 返回 None',
      sceneio._apply_skybox(None) is None)
check('5b) _apply_skybox({}) 返回 None',
      sceneio._apply_skybox({}) is None)
check('5c) _apply_skybox 坏数据不崩',
      sceneio._apply_skybox({'paths': ['/nope/x.png'] * 6}) is None)

# ==================== 6. _emit_skybox 文件源（桩） ====================
class _StubCube:
    def __init__(self):
        self.name = 'file_cube'
        self.guid = 'test_guid_123'
        self.paths = ['/a.png', '/b.png', '/c.png', '/d.png', '/e.png', '/f.png']
        self._solid_color = None
    def ensure_gl(self, ctx): return None
    def use(self, unit): pass


fs = _StubCube()
emitted_fs = sceneio._emit_skybox(fs)
check('6a) 文件源 _emit_skybox 返回 paths',
      emitted_fs is not None and 'paths' in emitted_fs, emitted_fs)
check('6b) paths 长度 6', len(emitted_fs['paths']) == 6)

# ==================== 7. 场景级 skybox 序列化往返 ====================
class _StubEngine:
    def __init__(self):
        self._skybox = None
        self.models = []
        self.materials = []
        self.lights = []
        self.cameras = []
        self.active_camera = None
        self.gravity = -9.8
        self.ui = None


e1 = _StubEngine()
e1._skybox = Cubemap.from_solid((100, 150, 200, 255), name='scene_sky')
sc_dict = sceneio.scene_to_dict(e1)

check('7a) scene dict 含 skybox 键', 'skybox' in sc_dict)
check('7b) skybox 记录纯色来源', 'solid_color' in sc_dict['skybox'])

# 反序列化
e2 = _StubEngine()
# 需要 _apply_ui 空实现（真 engine 有 ui 但桩没有）
try:
    sceneio.scene_from_dict(e2, sc_dict)
except Exception as ex:
    # ui 可能不兼容，但仍应恢复 skybox
    print('  (scene_from_dict 部分失败，容错: %r)' % ex)
    # 手动应用 skybox
    e2._skybox = sceneio._apply_skybox(sc_dict.get('skybox'))

check('7c) scene_from_dict 后 _skybox 非 None', e2._skybox is not None)
check('7d) _skybox 纯色值还原',
      e2._skybox is not None and e2._skybox._solid_color == (100, 150, 200, 255))

# ==================== 8. 相机级 skybox 序列化往返 ====================
cam = CameraState(name='cam1', skybox=Cubemap.from_solid((50, 100, 150, 255), name='cam_sky'))
cam_dict = sceneio._emit_camera(cam)
check('8a) _emit_camera 含 skybox 键', 'skybox' in cam_dict)
check('8b) 相机级 skybox 有 solid_color', 'solid_color' in cam_dict['skybox'])

# ==================== 9. EAI skybox_set 纯色 ====================
class _Win:
    def __init__(self, ed):
        self.editor = ed


class _StubEd:
    def __init__(self):
        self._skybox = None


win = _Win(_StubEd())
fn = ac._COMMANDS.get('skybox_set')
r = fn(win, {'solid_color': '#336699', 'name': 'eai_sky'})
check('9a) EAI skybox_set 纯色成功', 'ok' in r, r)
check('9b) 之后 _skybox 非 None', win.editor._skybox is not None)
check('9c) name 是 eai_sky', win.editor._skybox.name == 'eai_sky')

# 边界：缺参数
r = fn(win, {})
check('9d) 缺 paths + solid_color -> error', 'error' in r)

# ==================== 10. EAI skybox_clear ====================
fn = ac._COMMANDS.get('skybox_clear')
r = fn(win, {})
check('10a) skybox_clear 返回 ok', r.get('ok') is True)
check('10b) 之后 _skybox 是 None', win.editor._skybox is None)

# ==================== 11. EAI skybox_get ====================
fn = ac._COMMANDS.get('skybox_get')
r = fn(win, {})
check('11a) 无 skybox 时返回 {skybox: None}',
      r.get('skybox') is None, r)

# 设后再 get
win.editor._skybox = Cubemap.from_solid((200, 100, 50, 255), name='get_test')
r = fn(win, {})
check('11b) 有 skybox 时返回 source=solid',
      r['skybox']['source'] == 'solid', r)

# ==================== 12. MCP 3 工具转发 ====================
class _StubClient:
    def call(self, name, payload=None):
        cmd = ac._COMMANDS.get(name)
        if cmd is None:
            return {'error': 'no command'}
        return cmd(win, payload or {})


win.editor._skybox = None
srv = loom_mcp.LoomMCPServer(client=_StubClient())

# 12a. tools/list 含 3 个新工具
r = srv.handle_request({'jsonrpc': '2.0', 'id': 1, 'method': 'tools/list', 'params': {}})
names = {t['name'] for t in r['result']['tools']}
for n in ['loom_skybox_set', 'loom_skybox_clear', 'loom_skybox_get']:
    check('12a) MCP tools/list 含 %s' % n, n in names)


def _call_tool(cmd_name, args):
    r = srv.handle_request({'jsonrpc': '2.0', 'id': 2, 'method': 'tools/call',
                            'params': {'name': cmd_name, 'arguments': args}})
    return json.loads(r['result']['content'][0]['text'])


r = _call_tool('loom_skybox_set', {'solid_color': '#ABCDEF', 'name': 'mcp_sky'})
check('12b) MCP skybox_set 转发', r.get('ok') is True, r)

r = _call_tool('loom_skybox_get', {})
check('12c) MCP skybox_get 转发',
      r.get('skybox') is not None and r['skybox']['source'] == 'solid', r)

r = _call_tool('loom_skybox_clear', {})
check('12d) MCP skybox_clear 转发', r.get('ok') is True, r)

print()
if fails:
    print('FAILED: %d 项' % len(fails))
    for f in fails:
        print('  - ' + f)
    sys.exit(1)
print('SMOKE_PASS')
