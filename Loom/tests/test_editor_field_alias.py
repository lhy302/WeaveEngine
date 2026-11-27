# -*- coding: utf-8 -*-
import sys as _sys_utf8
try:
    _sys_utf8.stdout.reconfigure(encoding='utf-8', errors='replace')
    _sys_utf8.stderr.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

"""test_editor_field_alias.py — R6 门：SceneDriver 的 orbit_mode ↔ yaw/pitch 按模式别名
（Q-B7-45-1，489e84b 加的）**不得影响编辑器读写的 camera_yaw/camera_pitch/orbit_mode 字段语义**。

背景（Q-B7-47-1「编辑器支持 VK」五阶段 / S2 调研唯一真风险 R6）：
  scene_driver.SceneDriver.__setattr__ 在 orbit_mode=True 时把 camera_yaw/camera_pitch
  双向别名到 yaw/pitch（VK 内部 13 处 self.yaw/self.pitch 零改动的兼容层）。而
  editor.py 对 camera_yaw/pitch 读写 17/21 次、orbit_mode 大量读写。S2 把编辑器方法
  原样搬进 _EditorCore(EngineCore)，将来 VK 编辑器 = _EditorCore + SceneDriver 装配。
  本门是报警器：若别名机制渗透进编辑器字段（例如 orbit_mode 一写就改写角度、或
  camera_yaw 在编辑器装配下被重定向到别的存储），这里立刻红。

两种装配（夹具与生产同构，不依赖 GL 窗口 / VK 宿主）：
  装配 1（编辑器装配）：EngineCore() + 相机字段直写 —— _EditorCore 无 __init__、无相机
          字段，这些字段全部由宿主 __init__ 建立（GLEngine.__init__ render/gl/engine.py:240-265
          的同款直写：camera / camera_yaw / camera_pitch / camera_roll / orbit_mode）。
  装配 2（VK 播放装配）：SceneDriver()（纯数据层，与 test_camera_parity 等既有门同法）。

断言：
  ① 同一串「编辑器操作序列」（交替写 orbit_mode 与 camera_yaw/pitch/roll）喂两种装配，
    编辑器读回的四个字段逐值相等；
  ② 编辑器装配**无别名机制**：写 camera_yaw 不产生/不改动 yaw 伙伴字段；
    写 orbit_mode 不改动任何角度字段（两种装配都查）；
  ③ 往返一致：任一 orbit_mode 取值下「写 camera_yaw/pitch → 立刻读回」= 原值（两种装配）；
  ④ S2 落地后（条件断言，落地前自动跳过、落地后必须全绿）：
     · editor._EditorCore 存在且无自己的 __init__ / __setattr__（不许拦字段写）；
     · EditorApp.mro() = EditorApp → _EditorCore → GLEngine → … → EngineCore → …，
       且 _EditorCore 在 GLEngine 之前、EngineCore 在 GL 后端 mixin 之前。
"""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
os.environ['LOOM_NO_DIALOG'] = '1'

from core.engine_core import EngineCore                             # noqa: E402
from core.primitives import Point3D                                 # noqa: E402
import render.vk.driver as SD                                      # noqa: E402

ok = True


def check(label, cond, detail=''):
    global ok
    print(('PASS ' if cond else 'FAIL ') + label + ('  ' + str(detail) if detail else ''))
    if not cond:
        ok = False


# ---------------- 装配 1：编辑器装配（EngineCore 底座，无别名机制） ----------------
def build_editor_assembly():
    e = EngineCore()
    # 与 GLEngine.__init__ (render/gl/engine.py:240-265) 同款字段直写 —— 生产构造式，非假夹具
    e.camera = Point3D(0, 0, -5)
    e.camera_yaw = 0
    e.camera_pitch = 0
    e.camera_roll = 0
    e.orbit_mode = False
    return e


# ---------------- 装配 2：VK 播放装配（SceneDriver，含按模式别名） ----------------
vk = SD.SceneDriver()

# ---- ① 同一串编辑器操作序列，两种装配逐值一致 ----
SEQ = [
    ('camera_yaw', 1.2), ('camera_pitch', -0.3), ('camera_roll', 0.1),
    ('orbit_mode', True),
    ('camera_yaw', 2.5), ('camera_pitch', 0.4),
    ('orbit_mode', False),
    ('camera_yaw', 0.5), ('camera_pitch', 0.25),
    ('orbit_mode', True),
    ('camera_pitch', -0.9),
]
ed = build_editor_assembly()
for name, value in SEQ:
    setattr(ed, name, value)
for name, value in SEQ:
    setattr(vk, name, value)
print('=== ① 编辑器操作序列：两种装配逐值一致 ===')
for f in ('camera_yaw', 'camera_pitch', 'camera_roll', 'orbit_mode'):
    ev, vv = getattr(ed, f), getattr(vk, f)
    check('① 序列终态 %s：编辑器装配 == VK 装配' % f, ev == vv, 'ed=%r vk=%r' % (ev, vv))

# ---- ② 无别名渗透 ----
print('=== ② 别名不影响编辑器字段 ===')
ed2 = build_editor_assembly()
ed2.camera_yaw = 1.2
check('② 编辑器装配：写 camera_yaw 不产生 yaw 伙伴字段', not hasattr(ed2, 'yaw'))
ed2.camera_pitch = 0.3
check('② 编辑器装配：写 camera_pitch 不产生 pitch 伙伴字段', not hasattr(ed2, 'pitch'))
_ed_angles_before = (ed2.camera_yaw, ed2.camera_pitch, ed2.camera_roll)
ed2.orbit_mode = True
ed2.orbit_mode = False
check('② 编辑器装配：写 orbit_mode 不改动任何角度字段',
      (ed2.camera_yaw, ed2.camera_pitch, ed2.camera_roll) == _ed_angles_before,
      (_ed_angles_before, (ed2.camera_yaw, ed2.camera_pitch, ed2.camera_roll)))
check('② 编辑器装配：EngineCore 未定义 __setattr__（无拦截层）',
      type(ed2).__setattr__ is object.__setattr__)
# VK 装配：写 orbit_mode 本身也不得改角度（别名只随 camera_yaw/pitch 的写触发）
_vk_angles_before = (vk.camera_yaw, vk.camera_pitch)
vk.orbit_mode = False
vk.orbit_mode = True
check('② VK 装配：写 orbit_mode 不改动 camera_yaw/camera_pitch',
      (vk.camera_yaw, vk.camera_pitch) == _vk_angles_before,
      (_vk_angles_before, (vk.camera_yaw, vk.camera_pitch)))

# ---- ③ 往返一致（读回 = 刚写的值），orbit_mode 两种取值 × 两种装配 ----
print('=== ③ 写→读往返一致（两种装配 × orbit_mode 两种取值） ===')
for label, host in (('编辑器装配', build_editor_assembly()), ('VK装配', SD.SceneDriver())):
    for mode in (False, True):
        host.orbit_mode = mode
        host.camera_yaw = 0.7
        host.camera_pitch = -0.2
        check('③ %s orbit_mode=%r：camera_yaw 往返' % (label, mode),
              host.camera_yaw == 0.7, host.camera_yaw)
        check('③ %s orbit_mode=%r：camera_pitch 往返' % (label, mode),
              host.camera_pitch == -0.2, host.camera_pitch)

# ---- ④ S2 落地后的结构锁（落地前 _EditorCore 不存在 → 跳过并显式打印） ----
print('=== ④ S2 结构锁（_EditorCore 落地后生效） ===')
import editor as ED                                            # noqa: E402
import engine as E                                             # noqa: E402
if hasattr(ED, '_EditorCore'):
    check('④ _EditorCore 无自己的 __init__（super().__init__ 直落 GLEngine）',
          '__init__' not in ED._EditorCore.__dict__)
    check('④ _EditorCore 无自己的 __setattr__（不许拦字段写）',
          '__setattr__' not in ED._EditorCore.__dict__)
    mro = ED.EditorApp.__mro__
    check('④ MRO：EditorApp → _EditorCore → GLEngine（_EditorCore 在 GLEngine 之前）',
          mro.index(ED.EditorApp) < mro.index(ED._EditorCore) < mro.index(ED.GLEngine),
          [c.__name__ for c in mro])
    check('④ MRO：EngineCore 在 GL 后端 mixin 之前（Shadow/Hud/Render/ModelGpu/Lighting/GlfwWindow）',
          all(mro.index(E.EngineCore) < mro.index(getattr(E, n))
              for n in ('ShadowMixin', 'HudMixin', 'RenderMixin', 'ModelGpuMixin',
                        'LightingMixin', 'GlfwWindowMixin')),
          [c.__name__ for c in mro])
    check('④ MRO：EngineCore 在 _EditorCore 之后（中间基类不遮内核）',
          mro.index(ED._EditorCore) < mro.index(E.EngineCore),
          [c.__name__ for c in mro])
else:
    print('SKIP  ④ 结构锁：editor._EditorCore 尚未落地（S2 改动前首跑，属预期）')

print()
print('总结果:', 'ALL PASS' if ok else '有 FAIL')
sys.exit(0 if ok else 1)