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


"""test_vk_logic_frame_parity.py — B7-26 门：逻辑帧段序 / 段内效果 / 配对集合 两端一致。

缺陷（2026-11-17 修复前取证）：VK {BT}_logic_frame{BT} 只有 5 段，GL 有 8 段 ——
  GL  ：FixedUpdate → 脚本 → 动画 → 物理子步×N → **音频** → **prep** → **碰撞事件派发** → 插值翻页
  VK  ：FixedUpdate → 脚本 → 动画 → 物理子步×N → 插值翻页
  缺的三段里最要命的是**碰撞事件派发**：{BT}_dispatch_collision_events{BT} / {BT}_logic_prep{BT} /
  {BT}update_audio{BT} 在 VK 侧**整条链都不存在** → 脚本 {BT}on_collision_*{BT} / {BT}on_trigger_*{BT} 永不触发、
  AudioSource play/stop 永不发生。

修复（B7-26）：抽 {BT}loom_collision.py{BT}（配对/判重/派发/回调）+ {BT}loom_frame_components{BT} 的
模块级 {BT}sync_audio_listener{BT} / {BT}update_audio{BT}，GL 与 VK 调**同一份**；VK 补三段。

本门四部分：
  一 段序对拍：同一逻辑帧内各段的**调用顺序**逐项相等（实例级插桩，不锁源码字符串）；
  二 能力面：VK 暴露 {BT}update_audio{BT} / {BT}_logic_prep{BT} / {BT}_dispatch_collision_events{BT}；
  三 配对集合对拍：GL 的 SAP+C 内核配对 与 共享 {BT}loom_collision.pairs{BT} **产出同一集合**
    （这是「VK 用朴素 O(n²) 也不改变语义」的证明）；
  四 事件序列对拍：同一场景跑两帧（重叠→分离），两端 {BT}on_collision_start/end{BT} 序列逐条相等。

脚本用**真实注册脚本**（{BT}scripts.register{BT} + {BT}m.add_script(id){BT}），不走「手塞 _script」的捷径 ——
后者会被 {BT}_run_scripts{BT} 重新解析成 None（实测踩过），测不到真链路。
"""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
os.environ['LOOM_NO_SAVE_MIGRATE'] = '1'
os.environ['LOOM_NO_PARALLEL'] = '1'
os.environ['LOOM_NO_DIALOG'] = '1'

import moderngl                                            # noqa: E402
import numpy as np                                         # noqa: E402
import engine as E                                         # noqa: E402
import render.vk.driver as SD                                  # noqa: E402
import sceneio                                             # noqa: E402
import components.collision as _lc                               # noqa: E402
from script.scripts import Script as _BaseScript, register as _register_script   # noqa: E402

E.GLEngine._build_gpu = lambda self, m: None               # 无头：不建 VBO/VAO

ok = True


def check(label, cond, detail=''):
    global ok
    print(('PASS ' if cond else 'FAIL ') + label + ('  ' + str(detail) if detail else ''))
    if not cond:
        ok = False


_CTX = moderngl.create_standalone_context()


# ---- 计数脚本：走真实注册/实例化路径（script_id = 类名） ----
HITS = []


class LogicFrameProbe(_BaseScript):
    script_id = 'LogicFrameProbe'      # scripts.register 的键就是 cls.script_id
    name = '逻辑帧对拍探针'

    def on_collision_start(self, other):
        HITS.append(('start', other.name))

    def on_collision_end(self, other):
        HITS.append(('end', other.name))


_register_script(LogicFrameProbe)


def make_scene(gap=0.2):
    """两个立方体（都带 box collider），间距 gap（<1 即重叠）。"""
    return {
        'version': 12,
        'camera': {'target': [0, 0, 0], 'distance': 8, 'yaw': 0.6, 'pitch': -0.3},
        'gravity': -9.8,
        'skybox': None,
        'objects': [
            {'id': 'a', 'type': 'cube', 'params': {'size': 1}, 'name': 'A',
             'position': [0, 0.5, 0], 'rotation': [0, 0, 0], 'scale': [1, 1, 1],
             'color': '#ffffff', 'visible': True,
             'collider': {'shape': 'box', 'enabled': True}},
            {'id': 'b', 'type': 'cube', 'params': {'size': 1}, 'name': 'B',
             'position': [gap, 0.5, 0], 'rotation': [0, 0, 0], 'scale': [1, 1, 1],
             'color': '#ffffff', 'visible': True,
             'collider': {'shape': 'box', 'enabled': True}},
        ],
        'lights': [], 'materials': [], 'cameras': [], 'active_camera': None,
    }


def attach_probe(models):
    for m in models:
        m.add_script('LogicFrameProbe')


# ---------------- 一. 段序对拍 ----------------
print("=== 一. 段序对拍（同一逻辑帧内的段调用顺序） ===")

# 物理子步数随设置变（这里 N=2），所以参考序里不放 physics，单独按「已有段相对顺序」比
REFERENCE_ORDER = ['FixedUpdate', 'scripts', 'animations',
                   'audio', 'prep', 'dispatch', 'interp']

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
    missing = []
    for attr, label in table:
        fn = getattr(engine, attr, None)
        if fn is None:
            missing.append(label)
            continue
        saved.append((attr, fn))

        def make(fn=fn, label=label):
            def wrapper(*a, **k):
                seen.append(label)
                return fn(*a, **k)
            return wrapper

        setattr(engine, attr, make())
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
            setattr(engine, attr, orig)
        if orig_adv is not None:
            it.advance = orig_adv
    return seen, missing


def build_gl(gap=0.2):
    e = E.GLEngine(320, 240, ctx=_CTX)
    e.clear_scene()
    sceneio.scene_from_dict(e, make_scene(gap))
    e.is_playing = True
    e.parallel = None
    e._collision_pool = None
    e._frame_pool = None
    attach_probe(e.models)
    return e


def build_vk(gap=0.2):
    d = SD.SceneDriver()
    d.build_scene_from_data(make_scene(gap))
    attach_probe(d.models)
    return d


gl = build_gl()
vk = build_vk()
gl_seq, gl_missing = trace(gl, GL_SEGMENTS)
vk_seq, vk_missing = trace(vk, VK_SEGMENTS)
print('  GL 段序: ' + ' -> '.join(gl_seq))
print('  VK 段序: ' + ' -> '.join(vk_seq))

check('GL 段序 = 参考实现（8 段齐全 + 插值翻页）',
      [s for s in gl_seq if s != 'physics'] == REFERENCE_ORDER and gl_missing == [],
      'GL=%s missing=%s' % (gl_seq, gl_missing))
check('VK 段序与 GL 逐项相等（段数含物理子步）', gl_seq == vk_seq,
      'GL=%s VK=%s' % (gl_seq, vk_seq))
check('VK 无缺失段', vk_missing == [], 'missing=%s' % (vk_missing,))

# ---------------- 二. 能力面 ----------------
print()
print("=== 二. 能力面（契约 A 类要求） ===")
CAPS = ('update_audio', '_logic_prep', '_dispatch_collision_events')
for cap in CAPS:
    check('VK 暴露 %s' % cap, callable(getattr(vk, cap, None)),
          'hasattr=%s' % hasattr(vk, cap))

# ---------------- 三. 配对集合对拍 ----------------
print()
print("=== 三. 配对集合对拍（GL SAP+C 内核  vs  共享 loom_collision.pairs） ===")
for gap, tag in ((0.2, '重叠'), (0.99, '重叠(临界)'), (1.5, '分离')):
    e = build_gl(gap)
    gl_pairs = set(e._collision_pairs_parallel())
    worlds = e.compute_world_matrices(e.models)
    shared_pairs = set(_lc.pairs(e.models, worlds, {}))
    check('gap=%s（%s）：两端配对集合相同' % (gap, tag), gl_pairs == shared_pairs,
          'GL=%s shared=%s' % (sorted(gl_pairs), sorted(shared_pairs)))

# ---------------- 四. 事件序列对拍 ----------------
print()
print("=== 四. 事件序列对拍（重叠 → 分离，两帧） ===")


def run_two_frames(build):
    """第 1 帧重叠（应 start），第 2 帧把 B 挪远（应 end）。返回事件序列。"""
    HITS.clear()
    eng = build(0.2)
    eng._logic_frame(1.0 / 60.0)
    # 挪远：直接改 position（两端同一操作）
    eng.models[1].position = E.Point3D(5.0, 0.5, 0.0)
    eng._logic_frame(1.0 / 60.0)
    return list(HITS)


gl_hits = run_two_frames(build_gl)
vk_hits = run_two_frames(build_vk)
print('  GL 事件: %s' % (gl_hits,))
print('  VK 事件: %s' % (vk_hits,))
check('两端都产生了碰撞事件（>0）', len(gl_hits) > 0 and len(vk_hits) > 0,
      'GL=%d VK=%d' % (len(gl_hits), len(vk_hits)))
check('两端事件序列逐条相等', gl_hits == vk_hits,
      'GL=%s VK=%s' % (gl_hits, vk_hits))
check('序列含 start 与 end（真的走了进入+离开）',
      any(h[0] == 'start' for h in gl_hits) and any(h[0] == 'end' for h in gl_hits),
      'GL=%s' % (gl_hits,))

print()
print('总结果: ' + ('ALL PASS' if ok else '有 FAIL'))
sys.exit(0 if ok else 1)
