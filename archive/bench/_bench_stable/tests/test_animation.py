# -*- coding: utf-8 -*-
"""M35 动画系统: 关键帧插值/播放推进/循环/单次/序列化/undo."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import engine as E
from engine import AnimationClip
import sceneio as S
import undo as U
from mesh import create_cube

ok = True
def check(label, cond, detail=""):
    global ok
    print(("PASS " if cond else "FAIL ") + label + ("  " + detail if detail else ""))
    if not cond: ok = False

# ---- AnimationClip 关键帧插值 ----
clip = AnimationClip([
    {'time': 0.0, 'position': (0, 0, 0)},
    {'time': 1.0, 'position': (0, 2, 0)},
    {'time': 2.0, 'position': (0, 0, 0)},
])
s = clip.sample(0.5)
check("动画: 关键帧插值 0.5s -> y=1", abs(s['position'][1] - 1.0) < 1e-9, str(s))
s2 = clip.sample(1.5)
check("动画: 中段插值 1.5s -> y=1", abs(s2['position'][1] - 1.0) < 1e-9, str(s2))
s3 = clip.sample(2.5)                          # 循环: 2.5 % 2.0 = 0.5
check("动画: 超时循环采样 2.5s -> y=1", abs(s3['position'][1] - 1.0) < 1e-9, str(s3))
check("动画: 时长 2s", clip.duration == 2.0)

# ---- update_animations 播放推进 / 循环 / 单次停 ----
eng = E.GLEngine.__new__(E.GLEngine)
eng.models = []; eng.materials = []; eng.lights = []
eng.current_model_index = 0
E.GLEngine._build_gpu = lambda self, m: None
m = eng.add_model(create_cube(1.0), E.Point3D(0, 0, 0), E.Point3D(0, 0, 0))
an = m.add_animator(clips={'跳': clip}, current='跳')
an.playing = True
eng.update_animations(0.5)
check("动画: 播放推进位置 y=1", abs(m.position.y - 1.0) < 1e-9, "y=%.4f" % m.position.y)
eng.update_animations(0.5)
eng.update_animations(0.5)                     # time=1.5
check("动画: 循环继续播 (y=1)", abs(m.position.y - 1.0) < 1e-9, "y=%.4f" % m.position.y)
# 单次不循环
an.loop = False
an.time = 0.0
eng.update_animations(2.0)                   # time=2.0 到末帧
check("动画: 单次播到末帧停", an.playing is False)
# play/stop
an.stop()
check("动画: stop 停止", an.playing is False)
an.play('跳', restart=True)
check("动画: play 从头播", an.playing and an.time == 0.0)

# ---- sceneio round-trip ----
d = S._emit_object(m)
check("sceneio animator 序列化", d.get('animator') is not None
      and d['animator']['current'] == '跳' and '跳' in d['animator']['clips'],
      str(d.get('animator')))
eng2 = E.GLEngine.__new__(E.GLEngine); eng2.models = []; eng2.materials = []
m2, _ = S._apply_object(eng2, d)
check("sceneio 加载动画 (clips 关键帧)", m2.animator is not None
      and m2.animator.current == '跳'
      and m2.animator.clips['跳'].duration == 2.0)

# ---- undo 还原动画 ----
snap = U.snapshot(m)
m.remove_animator()
check("移除动画后 None", m.animator is None)
U.apply_snapshot(m, snap)
check("undo 还原动画", m.animator is not None and m.animator.current == '跳')

print()
print("总结果:", "ALL PASS ✅" if ok else "有 FAIL ❌")
sys.exit(0 if ok else 1)
