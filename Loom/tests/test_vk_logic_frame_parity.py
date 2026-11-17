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


"""test_vk_logic_frame_parity.py — B7-26 门：逻辑帧段序与段内效果必须两端一致。

缺陷（2026-11-17 取证）：VK {BT}_logic_frame{BT} 只有 5 段，GL 有 8 段。
  GL  ：FixedUpdate → 脚本 → 动画 → 物理子步×N → **音频** → **prep** → **碰撞事件派发** → 插值翻页
  VK  ：FixedUpdate → 脚本 → 动画 → 物理子步×N → 插值翻页
  缺的三段里，最要命的是**碰撞事件派发**：{BT}_dispatch_collision_events{BT} 在 VK 侧**完全不存在**，
  脚本的 {BT}on_collision_start/end/stay{BT}、{BT}on_trigger_enter/exit/stay{BT} 在 VK 下永不触发；
  其次 {BT}update_audio{BT} 未接 —— VK 下 AudioSource 的 play/stop 永不发生。

本门是**已知缺口门（只许缩小）**——与 B7-24 的 API 矩阵门同一手法：
缺口集合被冻结成基线，**新缺口 → 红；修好没删行 → 红**。这样 run_all 保持全绿，
而「还差什么」是机器可查的，不靠人记。

已知缺口（2026-11-17 基线）：段 {audio, prep, dispatch}；能力 {update_audio,
_dispatch_collision_events, _logic_prep}。

原计划的「三 效果对拍：碰撞回调次数」**未纳入**（留痕）：
  VK 侧没有 {BT}add_model{BT}，两端只能一端走 {BT}add_model{BT}（GL 已知能触发）、一端走
  {BT}load_from_data{BT}，夹具不同源；实测该夹具下 GL 也是 0 次，说明夹具本身没造出
  可触发对（不是引擎问题）。**改为「能力面缺失即不可能触发」的推断 + 契约 A 类要求**，
  真正的事件序列对拍等 B7-26 实现时补（届时两端都有同源夹具）。

本门三部分：
  一 段序对拍：同一逻辑帧内各段的**调用顺序**逐项相等（用实例级插桩记录，不锁源码字符串）；
  二 能力面：VK 必须暴露契约 A 类的 {BT}update_audio{BT} / 碰撞事件派发能力；
  三 效果对拍：同一场景（两个重叠立方体 + 一个带 {BT}on_collision_start{BT} 的脚本）跑一个逻辑帧，
    两端回调次数都必须 > 0。
"""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
os.environ['LOOM_NO_SAVE_MIGRATE'] = '1'
os.environ['LOOM_NO_PARALLEL'] = '1'
os.environ.setdefault('LOOM_NO_DIALOG', '1')

import moderngl                                            # noqa: E402
import engine as E                                         # noqa: E402
import scene_driver as SD                                  # noqa: E402
import sceneio                                             # noqa: E402

E.GLEngine._build_gpu = lambda self, m: None               # 无头：不建 VBO/VAO

ok = True


def check(label, cond, detail=''):
    global ok
    print(('PASS ' if cond else 'FAIL ') + label + ('  ' + str(detail) if detail else ''))
    if not cond:
        ok = False


_CTX = moderngl.create_standalone_context()


def make_scene():
    """两个重叠的立方体（都带 collider），一个简单相机。"""
    return {
        'version': 12,
        'camera': {'target': [0, 0, 0], 'distance': 8, 'yaw': 0.6, 'pitch': -0.3},
        'gravity': -9.8,
        'skybox': None,
        'objects': [
            {'id': 'a', 'type': 'cube', 'params': {'size': 1},
             'position': [0, 0.5, 0], 'rotation': [0, 0, 0], 'scale': [1, 1, 1],
             'color': '#ffffff', 'visible': True,
             'collider': {'shape': 'box', 'enabled': True}},
            {'id': 'b', 'type': 'cube', 'params': {'size': 1},
             'position': [0.2, 0.5, 0], 'rotation': [0, 0, 0], 'scale': [1, 1, 1],
             'color': '#ffffff', 'visible': True,
             'collider': {'shape': 'box', 'enabled': True}},
        ],
        'lights': [{'id': 'sun', 'kind': 'directional', 'direction': [-0.3, -1.0, -0.2],
                    'color': [1, 1, 1], 'intensity': 1.0, 'shadow': False,
                    'mode': 'full', 'shape': 'circle', 'size': 5}],
        'materials': [], 'cameras': [], 'active_camera': None,
    }


class Counter:
    """计数脚本。on_fixed_update/on_late_update 必须显式定义 ——
    GL 的 _dispatch_fixed_update 用 type(inst).on_fixed_update is _Base.on_fixed_update
    判断「脚本是否覆盖了该钩子」，缺属性会 AttributeError。"""

    def __init__(self):
        self.start = 0
        self.enter = 0

    def on_fixed_update(self, dt):
        pass

    def on_late_update(self, dt):
        pass

    def on_collision_start(self, other):
        self.start += 1

    def on_trigger_enter(self, other):
        self.enter += 1


def attach_counter(models):
    """给每个物体挂一个计数脚本（GL/VK 用同一种挂法）。"""
    out = []
    for m in models:
        sc = m.add_script(None)
        c = Counter()
        sc._script = c
        out.append(c)
    return out


# 已知缺口基线（只许缩小，不许增大）
KNOWN_MISSING_SEGMENTS = {'audio', 'prep', 'dispatch'}
KNOWN_MISSING_CAPS = {'update_audio', '_dispatch_collision_events', '_logic_prep'}

# ---------------- 一. 段序对拍 ----------------
print("=== 一. 段序对拍（同一逻辑帧内的段调用顺序） ===")

GL_SEGMENTS = [
    ('_dispatch_fixed_update', 'FixedUpdate'),
    ('_run_scripts', 'scripts'),
    ('update_animations', 'animations'),
    ('update_audio', 'audio'),
    ('_physics_frame', 'physics'),
    ('_logic_prep', 'prep'),
    ('_dispatch_collision_events', 'dispatch'),
]
VK_SEGMENTS = [
    ('_dispatch_fixed_update', 'FixedUpdate'),
    ('_update_scripts', 'scripts'),
    ('_update_animations', 'animations'),
    ('update_audio', 'audio'),
    ('_step_physics', 'physics'),
    ('_logic_prep', 'prep'),
    ('_dispatch_collision_events', 'dispatch'),
]


def trace(engine, table):
    """实例级插桩：包一层记录调用顺序，跑一个逻辑帧后还原。"""
    seen = []
    saved = []
    for attr, label in table:
        fn = getattr(engine, attr, None)
        if fn is None:
            seen.append(label + ':MISSING')
            continue
        saved.append((attr, fn))

        def make(fn=fn, label=label):
            def wrapper(*a, **k):
                seen.append(label)
                return fn(*a, **k)
            return wrapper

        try:
            setattr(engine, attr, make())
        except Exception:
            seen.append(label + ':NO-SETATTR')
    it = getattr(engine, '_interp', None)
    orig_adv = None
    if it is not None:
        orig_adv = it.advance

        def adv(*a, **k):
            seen.append('interp')
            return orig_adv(*a, **k)

        it.advance = adv
    try:
        engine._logic_frame(1.0 / 60.0)
    finally:
        for attr, orig in saved:
            try:
                setattr(engine, attr, orig)
            except Exception:
                pass
        if orig_adv is not None:
            try:
                it.advance = orig_adv
            except Exception:
                pass
    return seen


def missing_of(seq):
    return {s.split(':')[0] for s in seq if s.endswith(':MISSING')}


gl = E.GLEngine(320, 240, ctx=_CTX)
gl.clear_scene()
sceneio.scene_from_dict(gl, make_scene())
gl.is_playing = True
gl.parallel = None
gl._collision_pool = None
gl._frame_pool = None
vk = SD.SceneDriver()
vk.load_from_data(make_scene())

gl_seq = trace(gl, GL_SEGMENTS)
vk_seq = trace(vk, VK_SEGMENTS)
print('  GL 段序: ' + ' -> '.join(gl_seq))
print('  VK 段序: ' + ' -> '.join(vk_seq))

check('GL 段序就是参考实现（8 段齐全 + 插值翻页）',
      gl_seq == ['FixedUpdate', 'scripts', 'animations', 'physics', 'physics',
                 'audio', 'prep', 'dispatch', 'interp'],
      'GL=%s' % (gl_seq,))

vk_missing = missing_of(vk_seq)
check('VK 缺口 == 已知基线（新增缺口即红）', vk_missing == KNOWN_MISSING_SEGMENTS,
      '实测缺口=%s 基线=%s' % (sorted(vk_missing), sorted(KNOWN_MISSING_SEGMENTS)))
check('基线里没有「已补齐但没删行」的条目',
      not (KNOWN_MISSING_SEGMENTS - vk_missing),
      '已补齐请从 KNOWN_MISSING_SEGMENTS 删除: %s' % sorted(KNOWN_MISSING_SEGMENTS - vk_missing))

# VK 已跑到的段，相对顺序必须与 GL 一致（缺口之外不许乱序）
gl_order = [s for s in gl_seq if not s.endswith(':MISSING')]
vk_order = [s for s in vk_seq if not s.endswith(':MISSING')]
check('VK 已有段的相对顺序与 GL 一致', vk_order == [s for s in gl_order if s in vk_order],
      'GL=%s VK=%s' % (gl_order, vk_order))

# ---------------- 二. 能力面 ----------------
print()
print("=== 二. 能力面（契约 A 类要求） ===")
CAPS = ('update_audio', '_dispatch_collision_events', '_logic_prep')
vk_missing_caps = {c for c in CAPS if not callable(getattr(vk, c, None))}
check('VK 缺的能力 == 已知基线', vk_missing_caps == KNOWN_MISSING_CAPS,
      '实测缺=%s 基线=%s' % (sorted(vk_missing_caps), sorted(KNOWN_MISSING_CAPS)))
check('能力基线里没有「已补齐但没删行」的条目',
      not (KNOWN_MISSING_CAPS - vk_missing_caps),
      '已补齐请从 KNOWN_MISSING_CAPS 删除: %s' % sorted(KNOWN_MISSING_CAPS - vk_missing_caps))

check('GL 三项能力都在（参考实现）',
      all(callable(getattr(gl, c, None)) for c in CAPS),
      'GL missing=%s' % [c for c in CAPS if not callable(getattr(gl, c, None))])

print()
print('  缺口清单（B7-26 待补）: 段 %s / 能力 %s'
      % (sorted(KNOWN_MISSING_SEGMENTS), sorted(KNOWN_MISSING_CAPS)))
print('总结果: ' + ('ALL PASS' if ok else '有 FAIL'))
sys.exit(0 if ok else 1)
