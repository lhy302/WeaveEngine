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


"""test_clock_settings_propagation.py — B7-18 门：时钟设置必须传播到两端。

缺陷（2026-11-17 实测 / 工程设计失误盘点 D2）：
  VK 侧 {BT}scene_driver.py{BT} 建时钟时用的是**无参**构造函数 —— {BT}FixedStepClock(){BT} 与
  {BT}split_enabled(){BT}，即永远取构造默认值 30Hz，**完全不读设置**的 {BT}logic_fps{BT} /
  {BT}phys_substep_dt{BT} / {BT}physics_fps{BT}。后果：
    · 设置里把 logic_fps 改成 20/45/60/120，GL 播放器生效、VK 播放器与**打包游戏**（默认后端
      vulkan）全部无效，实际仍跑 30Hz；
    · 设 logic_fps<=0（绑死模式）在 VK 侧也不生效（照样 30Hz 分离时钟）；
    · 逻辑帧步长不同 → 物理子步数不同 → 同一场景两端**行为**不同（不只是性能不同）。

本测试是**对拍门**（方法论 §6.2「对拍（差分）」）：同一份设置喂给两端，两端的
时钟参数必须逐项相等。GL 侧用真实 {BT}GLEngine{BT}（离屏上下文 + 无 GPU 桩，与
{BT}test_collision_events_small_scene.py{BT} 同法），VK 侧用真实 {BT}SceneDriver{BT}（纯数据层）。

覆盖：60Hz / 20Hz / 绑死模式(logic_fps=0) / 缺键默认 四种设置 × 两端。
"""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
os.environ['LOOM_NO_SAVE_MIGRATE'] = '1'
os.environ['LOOM_NO_PARALLEL'] = '1'   # 确定性：不建帧池/脚本线程

import moderngl                                            # noqa: E402
import guiloader                                           # noqa: E402
import engine as E                                         # noqa: E402
import scene_driver as SD                                  # noqa: E402

E.GLEngine._build_gpu = lambda self, m: None               # 无头：不建 VBO/VAO

ok = True


def check(label, cond, detail=''):
    global ok
    print(('PASS ' if cond else 'FAIL ') + label + ('  ' + str(detail) if detail else ''))
    if not cond:
        ok = False


_CTX = moderngl.create_standalone_context()

_ORIG_LOAD = guiloader.load_settings
_CURRENT = {}


def _patched_load(name=None, *a, **k):
    """只拦 loom（引擎设置）；其它层（game/用户）走原实现，避免污染。"""
    if name in (None, 'loom'):
        return dict(_CURRENT)
    return _ORIG_LOAD(name, *a, **k)


guiloader.load_settings = _patched_load


def clock_params(clock):
    """时钟的「可观察参数」——两端必须逐项相等的那几项。"""
    if clock is None:
        return None
    return (round(clock.logic_fps, 6),
            round(clock.phys_substep_dt, 6),
            round(clock.fixed_dt, 6),
            int(clock.steps),
            int(clock.sub_steps))


def build_both(settings):
    """同一份设置 → (GL 时钟参数, VK 时钟参数)。"""
    global _CURRENT
    _CURRENT = dict(settings)
    gl = E.GLEngine(320, 240, ctx=_CTX)
    vk = SD.SceneDriver()
    return clock_params(getattr(gl, '_clock', None)), clock_params(getattr(vk, '_clock', None)), gl, vk


CASES = [
    ('60Hz + 物理 120Hz', {'logic_fps': 60, 'physics_fps': 120}),
    ('20Hz + 物理 60Hz', {'logic_fps': 20, 'physics_fps': 60}),
    ('45Hz（设置面板档位）', {'logic_fps': 45, 'physics_fps': 60}),
    ('缺键 → 默认 30Hz', {}),
    ('logic_fps=0 → 绑死模式（无分离时钟）', {'logic_fps': 0}),
]

print('=== 一. 两端对拍：同一设置 → 同一时钟参数 ===')
for label, st in CASES:
    gl_p, vk_p, gl, vk = build_both(st)
    check('对拍 %s：两端时钟参数逐项相等' % label, gl_p == vk_p,
          'GL=%s VK=%s' % (gl_p, vk_p))

print()
print('=== 二. VK 单端：设置真的被读进去了（不是恰好等于默认值） ===')
for label, st, expect in (
        ('logic_fps=60', {'logic_fps': 60, 'physics_fps': 120}, 60.0),
        ('logic_fps=45', {'logic_fps': 45, 'physics_fps': 60}, 45.0),
        ('logic_fps=20', {'logic_fps': 20, 'physics_fps': 60}, 20.0),
        ('缺键 → 30', {}, 30.0)):
    _, vk_p, _, vk = build_both(st)
    check('VK %s：clock.logic_fps == %.1f' % (label, expect),
          vk_p is not None and vk_p[0] == expect,
          'VK=%s' % (vk_p,))

print()
print('=== 三. 物理子步长也来自设置（不是恒 1/60） ===')
_, vk_p120, _, _ = build_both({'logic_fps': 60, 'physics_fps': 120})
_, vk_p60, _, _ = build_both({'logic_fps': 60, 'physics_fps': 60})
check('physics_fps=120 → sub_dt=1/120 且 60Hz 下 2 子步',
      vk_p120 is not None and vk_p120[1] == round(1.0 / 120.0, 6) and vk_p120[4] == 2,
      'VK=%s' % (vk_p120,))
check('physics_fps=60 → sub_dt=1/60 且 60Hz 下 1 子步（子步拉齐 fixed_dt）',
      vk_p60 is not None and vk_p60[1] == round(1.0 / 60.0, 6) and vk_p60[4] == 1,
      'VK=%s' % (vk_p60,))

print()
print('=== 四. 绑死模式：logic_fps<=0 → 两端都不建分离时钟 ===')
gl_p0, vk_p0, gl0, vk0 = build_both({'logic_fps': 0})
check('两端 _clock is None', gl_p0 is None and vk_p0 is None,
      'GL=%s VK=%s' % (gl_p0, vk_p0))
check('两端 _split_enable is False',
      getattr(gl0, '_split_enable', None) is False and getattr(vk0, '_split_enable', None) is False,
      'GL=%s VK=%s' % (getattr(gl0, '_split_enable', '?'), getattr(vk0, '_split_enable', '?')))

guiloader.load_settings = _ORIG_LOAD

print()
print('总结果: ' + ('ALL PASS' if ok else '有 FAIL'))
sys.exit(0 if ok else 1)
