# -*- coding: utf-8 -*-

"""物理线程/桥生命周期回归 (scan_08_physics P1 修复锁定).

覆盖:
  1. 子步异常不被后续成功子步覆盖: 首个未消费错误保持到 wait_pending
  2. stop() join 超时被检测: 线程仍存活时抛 RuntimeError (不再静默返回)
  3. 桥异常后本场一次性 disabled: 不逐帧重建 + 日志节流 (每场 1 条)
  4. 线程未确认退出时 _destroy_phys_bridge 拒绝销毁桥并抛给上层

用法: py -3.12 tests\test_physics_pipe_errors.py
"""

# 2026-11-06 P-02 修复: Windows 控制台默认 GBK, 中文/符号 print 会抛
# UnicodeEncodeError 造成假失败; 统一 UTF-8(replace), 失败信号只由断言决定.
import sys as _sys_utf8
try:
    _sys_utf8.stdout.reconfigure(encoding='utf-8', errors='replace')
    _sys_utf8.stderr.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

# 2026-11-06 失败退出码闸门: 出现以 FAIL 开头的行 -> 退出码改 1 (run_all 不假绿).
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


import contextlib
import io
import os
import sys
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import engine as E                    # noqa: E402
from physics_pipe import PhysicsPipeThread   # noqa: E402
from mesh import create_cube          # noqa: E402

DT = 1.0 / 60.0
ok = True


def check(label, cond, detail=""):
    global ok
    print(("PASS " if cond else "FAIL ") + label + ("  " + detail if detail else ""))
    if not cond:
        ok = False


# ============================================================
# 1. 子步异常不被覆盖
# ============================================================
class _ErrStubBridge:
    """第 1 次 pre_step 抛异常, 之后正常."""
    def __init__(self):
        self.n = 0
        self.ensure_calls = 0

    def ensure_models(self, models):
        self.ensure_calls += 1

    def pre_step(self, dt, g, pose=None):   # D2: 桥 API 增加 pose (位姿 SoA 平面)
        self.n += 1
        if self.n == 1:
            raise RuntimeError("boom-substep")

    def step(self, dt):
        pass

    def post_step(self):
        pass


br = _ErrStubBridge()
pipe = PhysicsPipeThread(br, timeout=5.0)
pipe.post([], DT, -9.8, False)          # 子步 1: 抛异常
pipe.post([], DT, -9.8, False)          # 子步 2: 成功 (旧实现会清空 _err)
raised_msg = None
try:
    pipe.wait_pending()
except RuntimeError as e:
    raised_msg = str(e)
check("1a.同批后续成功子步不覆盖前序异常",
      raised_msg is not None and "boom-substep" in raised_msg,
      "wait_pending=%r" % (raised_msg,))
# 错误已被消费: 再提交一个成功子步不应重复抛
pipe.post([], DT, -9.8, False)
try:
    pipe.wait_pending()
    again = False
except RuntimeError:
    again = True
check("1b.错误只消费一次 (成功批次不重复抛)", not again)
pipe.stop()

# ============================================================
# 2. stop() join 超时被检测
# ============================================================
class _BlockBridge:
    def __init__(self):
        self.entered = threading.Event()
        self.gate = threading.Event()

    def ensure_models(self, models):
        pass

    def pre_step(self, dt, g, pose=None):   # D2: 桥 API 增加 pose (位姿 SoA 平面)
        self.entered.set()
        self.gate.wait(10.0)

    def step(self, dt):
        pass

    def post_step(self):
        pass


bbr = _BlockBridge()
pipe = PhysicsPipeThread(bbr, timeout=5.0)
pipe.post([], DT, -9.8, False)
entered = bbr.entered.wait(2.0)
raised = False
try:
    pipe.stop(timeout=0.2)
except RuntimeError:
    raised = True
alive = pipe._t.is_alive()
check("2a.join 超时被检测 (线程仍存活 -> RuntimeError)",
      entered and raised and alive and pipe._degraded,
      "entered=%s raised=%s alive=%s degraded=%s"
      % (entered, raised, alive, pipe._degraded))
bbr.gate.set()                           # 放行阻塞子步, 线程应自行退出
try:
    pipe.stop(timeout=3.0)
    stopped = not pipe._t.is_alive()
except RuntimeError:
    stopped = False
check("2b.放行后线程确认退出 (可再次 stop)", stopped)

# ============================================================
# 3. 桥异常后本场一次性 disabled (不逐帧重建 + 日志节流)
# ============================================================
class _BoomBridge:
    enabled = True

    def __init__(self):
        self.calls = 0
        self.destroyed = False

    def ensure_models(self, models):
        self.calls += 1
        raise RuntimeError("boom-bridge")

    def destroy(self):
        self.destroyed = True


def _engine_stub():
    e = E.GLEngine.__new__(E.GLEngine)
    e.models = []
    e.materials = []
    e.lights = []
    e.current_model_index = 0
    e.gravity = -9.8
    e._phys_bridge_auto = True
    e._phys_pipe = None
    E.GLEngine._build_gpu = lambda self, m: None
    return e


e = _engine_stub()
fb = _BoomBridge()
e._phys_bridge = fb
m = E.GameObject(create_cube(1.0), E.Point3D(0, 3, 0), E.Point3D(0, 0, 0),
                 name='掉体')
m.add_rigidbody()
e.models = [m]
buf = io.StringIO()
with contextlib.redirect_stdout(buf):
    for _ in range(5):
        e.update_physics(DT)
log_text = buf.getvalue()
check("3a.桥异常 -> 本场 disabled, 不逐帧重建 (ensure 只 1 次)",
      fb.calls == 1 and e._phys_bridge_disabled is True
      and e._phys_bridge is None and fb.destroyed is True,
      "calls=%d disabled=%s bridge=%r destroyed=%s"
      % (fb.calls, e._phys_bridge_disabled, e._phys_bridge, fb.destroyed))
check("3b.异常日志节流 (每场只 1 条)", log_text.count("桥步进异常") == 1,
      "log_count=%d" % log_text.count("桥步进异常"))
check("3c.异常后仍回退 legacy (重力生效)", m.position.y < 3.0,
      "y=%.4f" % m.position.y)
# 已 disabled: 再调用 _ensure_phys_bridge 不会建桥
check("3d.disabled 后 _ensure_phys_bridge 不重建",
      e._ensure_phys_bridge() is None)

# ============================================================
# 4. 线程未确认退出 -> 拒绝销毁桥并抛给上层
# ============================================================
class _StuckPipe:
    def __init__(self):
        self.stop_calls = 0

    def stop(self, timeout=2.0):
        self.stop_calls += 1
        raise RuntimeError("stop-timeout")


e2 = _engine_stub()
fb2 = _BoomBridge()
e2._phys_bridge = fb2
e2._phys_pipe = _StuckPipe()
e2._phys_bridge_disabled = True          # 本场异常禁用态
raised = False
try:
    e2._destroy_phys_bridge()
except RuntimeError:
    raised = True
check("4a.线程未退出 -> 拒绝销毁桥并抛 RuntimeError",
      raised and fb2.destroyed is False and e2._phys_bridge is fb2
      and e2._phys_pipe is not None and e2._pipe_disabled is True,
      "raised=%s destroyed=%s bridge=%r pipe=%r pipe_disabled=%s"
      % (raised, fb2.destroyed, e2._phys_bridge, e2._phys_pipe,
         e2._pipe_disabled))
# 线程最终退出 (模拟) -> 正常销毁并清本场禁用标志
e2._phys_pipe = None
e2._destroy_phys_bridge()
check("4b.线程确认退出后正常销毁并允许下一场重建",
      fb2.destroyed is True and e2._phys_bridge is None
      and e2._phys_bridge_disabled is False,
      "destroyed=%s bridge=%r disabled=%s"
      % (fb2.destroyed, e2._phys_bridge, e2._phys_bridge_disabled))

print()
print("总结果:", "ALL PASS ✅" if ok else "有 FAIL ❌")
sys.exit(0 if ok else 1)
