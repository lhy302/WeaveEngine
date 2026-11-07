# -*- coding: utf-8 -*-

"""engine.py 安全加固断言 (2026-08-20 安全审查第一轮):
空场景按键路径不崩 (ZeroDivisionError/IndexError 修复) + 索引越界 clamp."""

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
from mesh import create_cube

eng = E.GLEngine.__new__(E.GLEngine)
eng.models = []
eng.materials = []
eng.current_model_index = 0
eng.camera = E.Point3D(0, 0, 0)
eng.camera_yaw = eng.camera_pitch = 0.0
eng.fps = 0
eng._external_ctx = True          # 跳过 HUD 绘制分支 (无 pygame 窗口)
E.GLEngine._build_gpu = lambda self, m: None

ok = True
def check(label, cond, detail=""):
    global ok
    print(("PASS " if cond else "FAIL ") + label + ("  " + detail if detail else ""))
    if not cond: ok = False

# ---- 空场景 (0 模型): 各当前模型操作不崩 ----
eng.select_next_model()
check("空场景 select_next_model 不崩", True)
check("空场景 get_current_model 返回 None", eng.get_current_model() is None)
eng._hud_lines()
check("空场景 _hud_lines 不崩", True)

# ---- 索引越界 clamp: 模型减少后 current_model_index 残留 ----
m = eng.add_model(create_cube(1.0), E.Point3D(0, 0, 0), E.Point3D(0, 0, 0))
eng.current_model_index = 5      # 模拟删模型后残留的越界索引
got = eng.get_current_model()
check("索引越界 get_current_model clamp 到有效模型",
      got is m and eng.current_model_index == 0)
eng.select_next_model()
check("有模型 select_next_model 环绕回 0", eng.current_model_index == 0)

print()
print("总结果:", "ALL PASS ✅" if ok else "有 FAIL ❌")
