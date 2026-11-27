# -*- coding: utf-8 -*-
import sys as _sys_utf8
try:
    _sys_utf8.stdout.reconfigure(encoding='utf-8', errors='replace')
    _sys_utf8.stderr.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

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


"""test_beam_light_backend_parity.py — B7-21 门：beam 平行光关阴影后两端必须都照亮。

缺陷（2026-11-17 实测）：
  GL 侧算平行光 VP 的条件是 {BT}light.shadow or light.mode == "beam"{BT}（render/gl/lighting.py:163），
  因为 beam 的光束截面遮罩走 {BT}u.lights[i].ortho{BT}（shaders/main.frag:198-210）。
  VK 侧条件只有 {BT}l.shadow{BT}（render/vk/renderer.py:1582 修前）→ beam 灯一旦关阴影就没有 VP，
  ortho 全零 → {BT}SHADOW_UV(lp){BT} 除 w 得 NaN → {BT}in_shape=0{BT} → {BT}sh=0{BT} → 该灯 radiance 归零，
  **整盏灯失效**（不是整帧黑，而是这盏灯一点光都不出）。

修前必红（实测原文）：
  shadow=False  GL mean=0.454512 | VK mean=0.338061 | MAE(G,V)=0.116452 MAX=0.710
  shadow=True   GL mean=0.454512 | VK mean=0.454512 | MAE(G,V)=0.000000 MAX=0.000
  —— 开阴影时两端**逐字节相同**，说明差异只来自这一处 VP 缺失。

修后：shadow=False 也 MAE=0.000000。

本门四件事：
  ① 像素面：beam + shadow=False → 两端 MAE <= 2e-3（修前 0.1165，红）
  ② 像素面：beam + shadow=True  → 两端 MAE <= 2e-3（对照组，修前也是绿的，防修坏）
  ③ 像素面：beam + rect 截面    → 两端 MAE <= 2e-3（形状分支不被漏掉）
  ④ 数据面 + 反向保护：
       beam 灯（无论 shadow）→ VK {BT}_light_vps{BT} 必须有它（遮罩要用 ortho）；
       **full 灯 + shadow=False → VK {BT}_light_vps{BT} 必须没有它** —— 钉住 M3-N5 优化
       （无条件算 VP 会让 main_pass 0.65 → 18.16 ms/帧，见 render/gl/lighting.py:157-162）。

渲染复用 {BT}test_ab_gl_vk{BT} 的 {BT}render_gl{BT} / {BT}render_vk{BT}（真实 GL 离屏 + 真实 Vulkan 离屏），
与既有 A/B 门同一条路径、同一套口径。
"""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
os.environ['LOOM_NO_SAVE_MIGRATE'] = '1'
os.environ.setdefault('LOOM_NO_PARALLEL', '1')
os.environ['LOOM_NO_DIALOG'] = '1'

import numpy as np                                       # noqa: E402
import test_ab_gl_vk as AB                               # noqa: E402  (复用 A/B 渲染夹具)

ok = True


def check(label, cond, detail=''):
    global ok
    print(('PASS ' if cond else 'FAIL ') + label + ('  ' + str(detail) if detail else ''))
    if not cond:
        ok = False


MAE_ABS = 2e-3      # 与既有 A/B 门同量级；实测两端逐字节相同（MAE=0）


def make_scene(shadow, mode, shape, size=4.0):
    """黑天空 + 白地板 + 单盏平行光（只有这盏灯能照亮，便于把差异归因到它）。"""
    return {
        'version': 12,
        'camera': {'target': [0, 0, 0], 'distance': 8, 'yaw': 0.6, 'pitch': -0.55},
        'gravity': -9.8,
        'skybox': {'name': '黑', 'guid': 'sky_beam_gate',
                   'solid_color': [0, 0, 0, 255]},
        'objects': [
            {'id': 'floor', 'type': 'plane', 'params': {'size': 20},
             'position': [0, 0, 0], 'rotation': [0, 0, 0], 'scale': [1, 1, 1],
             'color': '#ffffff', 'visible': True},
        ],
        'lights': [
            {'id': 'key', 'kind': 'directional',
             'direction': [-0.3, -1.0, -0.2],
             'color': [1, 1, 1], 'intensity': 3.0,
             'shadow': shadow, 'mode': mode, 'shape': shape, 'size': size},
        ],
        'materials': [], 'cameras': [], 'active_camera': None,
    }


def mae(a, b):
    return float(np.abs(a.astype(np.float64) - b.astype(np.float64)).mean())


print("=== 一. 像素面：beam 灯关/开阴影，两端都要照亮 ===")
for label, shadow in (('beam + shadow=False（缺陷本体）', False),
                      ('beam + shadow=True（对照组）', True)):
    d = make_scene(shadow, 'beam', 'circle')
    gl = AB.render_gl(d)
    vk = AB.render_vk(d)
    m = mae(gl, vk)
    check('%s：两端 MAE <= %.0e' % (label, MAE_ABS), m <= MAE_ABS,
          'GL mean=%.6f VK mean=%.6f MAE=%.6f' % (gl.mean(), vk.mean(), m))

print()
print("=== 二. 像素面：beam 矩形截面（shape 分支） ===")
d = make_scene(False, 'beam', 'rect')
gl = AB.render_gl(d)
vk = AB.render_vk(d)
m = mae(gl, vk)
check('beam + rect + shadow=False：两端 MAE <= %.0e' % MAE_ABS, m <= MAE_ABS,
      'GL mean=%.6f VK mean=%.6f MAE=%.6f' % (gl.mean(), vk.mean(), m))

print()
print("=== 三. 数据面 + 反向保护（VP 只在需要时算） ===")
import render.vk.driver as sd                                  # noqa: E402
import render.vk.renderer as vr                                   # noqa: E402

device = AB._vk_device()


def vk_light_vps(shadow, mode):
    d = make_scene(shadow, mode, 'circle')
    drv = sd.SceneDriver()
    drv.build_scene_from_data(d, base_dir=AB.SCENES_DIR)
    r = vr.VkRenderer(device, 'rgba8unorm')
    worlds = vr.world_matrices(drv.models, interp=None)
    r._pack_light_vps(drv.lights, drv.models, worlds)
    return drv.lights[0].guid, dict(r._light_vps), dict(r._dir_shadow_slots)


for shadow in (False, True):
    guid, vps, slots = vk_light_vps(shadow, 'beam')
    check('beam + shadow=%s：VK 必须算出 VP（截面遮罩要 ortho）' % shadow,
          guid in vps, 'guid=%s in _light_vps=%s' % (guid, guid in vps))
    check('beam + shadow=%s：不占阴影贴图槽位' % shadow,
          slots == {} if not shadow else guid in slots,
          'dir_shadow_slots=%s' % (slots,))

guid, vps, _ = vk_light_vps(False, 'full')
check('full + shadow=False：VK **不得**算 VP（M3-N5 优化，无条件算会 0.65→18.16ms/帧）',
      guid not in vps, 'guid=%s in _light_vps=%s' % (guid, guid in vps))

print()
print('总结果: ' + ('ALL PASS' if ok else '有 FAIL'))
sys.exit(0 if ok else 1)