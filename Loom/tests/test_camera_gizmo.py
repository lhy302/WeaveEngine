# -*- coding: utf-8 -*-

"""M41 摄像机 gizmo 平移测试 (无头 EditorApp.__new__ 桩):
  选中摄像机 -> gizmo 目标=摄像机、可平移 (世界增量直改 position)、旋转被挡、
  拖完压 CameraStateCommand 撤销."""

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
import undo as U
from engine import CameraState
from editor import EditorApp

class _View:
    """极简 IEditorView 桩: 提供 input_state (鼠标位置)"""
    def __init__(self, mp=(200, 300)):
        self._mp = mp
    def input_state(self):
        return {'mouse_pos': self._mp, 'buttons': (0, 0, 0), 'pressed': set(),
                'released': set(), 'wheel': 0, 'click_captured': False,
                'focus_id': None}

def _make_editor():
    ed = EditorApp.__new__(EditorApp)
    ed.cameras = []
    ed.lights = []
    ed.models = []
    ed.selected_camera_index = 0
    ed.selected_light_index = -1
    ed.selected_index = -1
    ed.gizmo_mode = 'translate'
    ed.gizmo_axis = None
    ed.gizmo_drag = None
    ed.gizmo_undo_before = None
    ed._vp = np.eye(4, dtype=np.float64)   # 单位投影: 屏幕中心 -> 世界原点
    ed.width = 800
    ed.height = 600
    ed.camera_yaw = 0.0
    ed.camera_pitch = 0.0
    ed.camera_roll = 0.0
    ed.undo = U.UndoManager()
    ed.view = _View()
    ed.buttons = (0, 0, 0)
    return ed

ok = True
def check(label, cond, detail=""):
    global ok
    print(("PASS " if cond else "FAIL ") + label + ("  " + detail if detail else ""))
    if not cond:
        ok = False

ed = _make_editor()
cam = CameraState(position=(0, 0, -5), name="镜头")
ed.cameras = [cam]

# 1) gizmo 目标 = 摄像机 (平移)
check("选中摄像机 -> gizmo 目标 = 摄像机", ed._gizmo_target() is cam)
check("gizmo 世界位置 = 摄像机 position",
      tuple(EditorApp._target_world_pos(ed, cam)) == (0, 0, -5))

# 2) 旋转模式被挡 (摄像机不可旋转)
ed.gizmo_mode = 'rotate'
check("摄像机旋转 gizmo_hit = None (不可旋转)", ed._gizmo_hit(400, 300) is None)
ed.gizmo_mode = 'translate'

# 3) 平移拖拽: 屏幕 x=200 (左半屏) -> 世界 X 轴负向偏移 0.5
ed.view = _View((200, 300))
ed.gizmo_drag = ('X', (0, 0, -5), (0, 0, -5))
ed.gizmo_axis = 'X'
ed.gizmo_undo_before = U.camera_snapshot(cam)
ed._gizmo_drag_apply()
check("平移拖拽移动摄像机 position.x", abs(cam.position.x + 0.5) < 1e-6,
      str(cam.position))

# 4) 拖完松开 -> 压 CameraStateCommand 撤销
ed._update_gizmo()
check("拖完压入 CameraStateCommand",
      isinstance(ed.undo.undo_stack[-1], U.CameraStateCommand))
check("撤销栈非空且 gizmo_drag 清空", ed.gizmo_drag is None)

print()
print("总结果:", "ALL PASS ✅" if ok else "有 FAIL ❌")
