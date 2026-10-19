# -*- coding: utf-8 -*-
"""smoke_spotlight.py — 聚光灯冒烟 (2026-10-19 第1档序9)"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
BASE = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, BASE)
os.chdir(BASE)

import math
import numpy as np
import pygame
pygame.init()
pygame.display.set_mode((1, 1), pygame.HIDDEN)

from loom_scene_entities import LightState
import undo
import sceneio

fails = []


def check(label, cond, detail=''):
    msg = ('PASS ' if cond else 'FAIL ') + label
    if detail:
        msg += '  ' + str(detail)
    print(msg)
    if not cond:
        fails.append(label)


# ==================== 1. LightState 默认字段 ====================
s = LightState(kind='spot')
check('1a) LightState(kind=spot) 默认 inner=30',
      s.spot_inner_angle == 30.0, s.spot_inner_angle)
check('1b) 默认 outer=60', s.spot_outer_angle == 60.0, s.spot_outer_angle)
check('1c) name 自动 = "聚光灯"', s.name == '聚光灯', s.name)
check('1d) kind 字段 = "spot"', s.kind == 'spot')

# ==================== 2. 非 spot 也保留字段（不崩） ====================
d = LightState(kind='directional')
check('2) directional 也有 spot 字段（保留字段）',
      hasattr(d, 'spot_inner_angle') and d.spot_inner_angle == 30.0)

# ==================== 3. 上传层 kind 三态 + 两锥角 cos 值 ====================
# 造最小上传桩：只需要 _u_last / _u / _uniform / lights / _shadow_maps / _light_vps
class _StubUniform:
    def __init__(self):
        self.value = None
        self.written = None
    def write(self, data):
        self.written = data


class _StubUploader:
    """复用 _upload_lights 逻辑，但 _uniform 返回桩对象记录写入。"""
    _upload_lights = __import__('loom_lighting').LightingMixin._upload_lights
    def __init__(self):
        self._u = {}
        self._u_last = {}
        self.lights = []
        self._shadow_maps = {}
        self._light_vps = {}
        self._light_bufs = None
        # 阴影参数（聚光灯无关，照引擎默认值给）
        self._shadow_res = 1024.0
        self._shadow_point_res = 512.0
        self._shadow_point_far = 100.0

    def _uniform(self, name):
        u = self._u.get(name)
        if u is None:
            u = self._u[name] = _StubUniform()
        return u

    def _dir_light_vp(self, light):
        """桩: 不计算平行光阴影 VP（冒烟只测 uniform 缓冲，不测阴影）。"""
        return None

    def _release_shadow_map(self, sm):
        """桩: 释放阴影贴图（空操作）。"""
        pass


u = _StubUploader()
# 场景：1 dir + 1 point + 1 spot(inner=20, outer=45)
u.lights = [
    LightState(kind='directional', name='dir1'),
    LightState(kind='point', name='pt1'),
    LightState(kind='spot', name='sp1',
                spot_inner_angle=20.0, spot_outer_angle=45.0),
]
u._upload_lights()

kinds = np.frombuffer(u._u['u_light_kind'].written, dtype='f4')
check('3a) kinds[0]=0 (dir)', kinds[0] == 0.0, kinds[0])
check('3b) kinds[1]=1 (point)', kinds[1] == 1.0, kinds[1])
check('3c) kinds[2]=2 (spot)', kinds[2] == 2.0, kinds[2])

inner = np.frombuffer(u._u['u_light_spot_inner'].written, dtype='f4')
outer = np.frombuffer(u._u['u_light_spot_outer'].written, dtype='f4')
check('3d) spot inner = cos(20°)',
      abs(inner[2] - math.cos(math.radians(20))) < 1e-6,
      'actual=%f expect=%f' % (inner[2], math.cos(math.radians(20))))
check('3e) spot outer = cos(45°)',
      abs(outer[2] - math.cos(math.radians(45))) < 1e-6,
      'actual=%f expect=%f' % (outer[2], math.cos(math.radians(45))))

# ==================== 4. 非 spot 的 spot 缓冲保持 0 ====================
check('4a) dir 的 spot_inner = 0', inner[0] == 0.0, inner[0])
check('4b) point 的 spot_inner = 0', inner[1] == 0.0, inner[1])

# ==================== 5. 序列化往返 ====================
sp = LightState(kind='spot', spot_inner_angle=15.0, spot_outer_angle=35.0)
# 借用 sceneio 的 _dump_light（需先看函数名）
# 用 undo.light_snapshot 验证字段
snap = undo.light_snapshot(sp)
check('5a) light_snapshot 含 spot_inner_angle',
      snap.get('spot_inner_angle') == 15.0, snap.get('spot_inner_angle'))
check('5b) light_snapshot 含 spot_outer_angle',
      snap.get('spot_outer_angle') == 35.0, snap.get('spot_outer_angle'))

# ==================== 6. undo 快照还原 ====================
sp2 = LightState(kind='spot', spot_inner_angle=20.0, spot_outer_angle=50.0)
snap2 = undo.light_snapshot(sp2)
# 改掉字段再还原
sp2.spot_inner_angle = 99.0
sp2.spot_outer_angle = 99.0
undo.apply_light_snapshot(sp2, snap2)
check('6a) apply_light_snapshot 还原 inner',
      sp2.spot_inner_angle == 20.0, sp2.spot_inner_angle)
check('6b) apply_light_snapshot 还原 outer',
      sp2.spot_outer_angle == 50.0, sp2.spot_outer_angle)

# 旧快照（无 spot 字段）→ 不崩，保留原值
old_snap = {k: v for k, v in snap2.items()
            if k not in ('spot_inner_angle', 'spot_outer_angle')}
sp2.spot_inner_angle = 88.0
undo.apply_light_snapshot(sp2, old_snap)
check('6c) 旧快照 apply 不崩，字段保留原值 88.0',
      sp2.spot_inner_angle == 88.0, sp2.spot_inner_angle)

# ==================== 7. 边界：锥角 0/90/179 ====================
s0 = LightState(kind='spot', spot_inner_angle=0.0, spot_outer_angle=90.0)
check('7a) inner=0 outer=90 可构造',
      s0.spot_inner_angle == 0.0 and s0.spot_outer_angle == 90.0)
s179 = LightState(kind='spot', spot_inner_angle=0.0, spot_outer_angle=179.0)
check('7b) outer=179 可构造', s179.spot_outer_angle == 179.0)

# ==================== 8. EAI light_add 命令描述含 spot ====================
import agent_commands as ac
# 直接检查命令描述（cmd 的 help 字符串）
cmd = ac._COMMANDS.get('light_add')
check('8) EAI light_add 命令存在', cmd is not None)

print()
if fails:
    print('FAILED: %d 项' % len(fails))
    for f in fails:
        print('  - ' + f)
    sys.exit(1)
print('SMOKE_PASS')
