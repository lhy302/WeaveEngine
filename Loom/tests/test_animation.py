# -*- coding: utf-8 -*-

"""M35 动画系统: 关键帧插值/播放推进/循环/单次/序列化/undo."""

# 2026-11-06 P-02 修复: Windows 控制台默认 GBK, 末尾 print 的 ✅/❌/≤ 等字符会抛
# UnicodeEncodeError, 让"测试通过"被记录成 exit=1 的假失败 (48/51 曾被误判)。
# 统一把 stdout/stderr 切到 UTF-8(replace), 失败信号重新只由断言决定。
import sys as _sys_utf8
try:
    _sys_utf8.stdout.reconfigure(encoding='utf-8', errors='replace')
    _sys_utf8.stderr.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

# 2026-11-06 失败退出码闸门 (复核 A 指出: 54 个测试里仅 18 个有 sys.exit(1),
# 其余 FAIL 也 exit 0 -> run_all 假绿, 失败被静默吞掉)。
# 做法: 包一层 stdout, 出现以 "FAIL" 开头的行就在进程退出时把状态码改成 1。
# 只在真出现 FAIL 时才改码, 全 PASS 的测试行为完全不变。
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
