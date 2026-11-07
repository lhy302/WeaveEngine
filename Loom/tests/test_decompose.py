# -*- coding: utf-8 -*-

"""验证 decompose_euler: mat4_rotation(euler) -> decompose -> 重构成同一矩阵."""

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
import numpy as np
import math
from matlib import mat4_rotation, decompose_euler

rng = np.random.default_rng(7)
worst = 0.0
n_fail = 0
for _ in range(2000):
    rx, ry, rz = rng.uniform(-math.pi, math.pi, 3)
    R = mat4_rotation(np, rx, ry, rz)
    a, b, g = decompose_euler(R)
    R2 = mat4_rotation(np, a, b, g)
    err = float(np.max(np.abs(R2 - R)))
    worst = max(worst, err)
    if err > 1e-6:
        n_fail += 1
        if n_fail <= 3:
            print("FAIL", (rx, ry, rz), "->", (a, b, g), "err", err)

print("2000 随机角 往返最大误差:", worst)
print("超差次数:", n_fail, "=>", "PASS ✅" if n_fail == 0 else "FAIL ❌")
