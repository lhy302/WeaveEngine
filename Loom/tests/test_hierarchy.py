# -*- coding: utf-8 -*-

"""M14 层次测试: 世界位置/世界矩阵/AABB 中心/局部<->世界换算/防环."""

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
import engine as E
from mesh import create_cube

# 用 __new__ 拿一个不初始化(不开窗口)的 GLEngine 实例当方法容器
eng = E.GLEngine.__new__(E.GLEngine)

def mk(name, pos, rot=(0,0,0)):
    m = E.GameObject(create_cube(1.5), E.Point3D(*pos), E.Point3D(*rot), name=name)
    return m

root = mk("根", (0, 0, 0))
child = mk("子", (2, 0, 0))
grand = mk("孙", (1, 0, 0))
eng.set_parent(child, root)
eng.set_parent(grand, child)
eng.models = [root, child, grand]

ok = True
def check(label, cond, detail=""):
    global ok
    print(("PASS " if cond else "FAIL ") + label + ("  " + detail if detail else ""))
    if not cond: ok = False

# 1) 世界位置
wp_root = eng.world_position(root)
wp_child = eng.world_position(child)
wp_grand = eng.world_position(grand)
check("根世界位置(0,0,0)", tuple(round(v,6) for v in (wp_root.x, wp_root.y, wp_root.z)) == (0,0,0))
check("子世界位置(2,0,0)", tuple(round(v,6) for v in (wp_child.x, wp_child.y, wp_child.z)) == (2,0,0))
# 2026-08-16: set_parent 默认保世界 (Unity 语义) —— 挂父那一下世界位置不变
check("孙世界位置(1,0,0) (挂父保世界)",
      tuple(round(v,6) for v in (wp_grand.x, wp_grand.y, wp_grand.z)) == (1,0,0),
      str((round(wp_grand.x,3), round(wp_grand.y,3), round(wp_grand.z,3))))
check("孙局部坐标被换算到新父空间 (-1,0,0)",
      tuple(round(v,6) for v in (grand.position.x, grand.position.y, grand.position.z)) == (-1,0,0),
      str((round(grand.position.x,3), round(grand.position.y,3), round(grand.position.z,3))))

# 2) 根绕 Y 90°: 子世界位置应 = (2,0,0)@Ry(90°) = (2·cos90+0·sin90? 按 mat4_rotation)
root.rotation = E.Point3D(0, math.pi/2, 0)
R = eng.world_rotation_matrix(root)
ref = np.array([2.0, 0.0, 0.0, 1.0]) @ eng.model_world_matrix(root)
wc = eng.world_position(child)
check("根旋转后子世界位置=矩阵结果",
      tuple(round(v,6) for v in (wc.x, wc.y, wc.z)) == tuple(round(float(v),6) for v in ref[:3]),
      str((round(wc.x,3), round(wc.y,3), round(wc.z,3))))

# 3) AABB 中心 (世界) 应等于子世界位置 (立方体中心=局部原点)
mn, mx = eng.get_bounding_box(child)
center = np.array([(mn.x+mx.x)/2, (mn.y+mx.y)/2, (mn.z+mx.z)/2])
wc2 = eng.world_position(child)
err = float(np.max(np.abs(center - np.array([wc2.x, wc2.y, wc2.z]))))
check("子 AABB 中心 == 世界位置 (err<1e-6)", err < 1e-6, "err=%.2e" % err)

# 4) 局部<->世界换算
eng.set_parent(child, None)   # 脱父: 保世界, 局部=世界(旋转后 (0,0,-2))
root.rotation = E.Point3D(0, 0, 0)
root.position = E.Point3D(0, 0, 0)
child.position = E.Point3D(2, 0, 0)          # 显式定局部 (非挂父路径, 不换算)
eng.set_parent(child, root)                  # 挂父保世界: child 世界(2,0,0), root 单位 -> 局部不变
root.position = E.Point3D(5, 0, 0)
root.rotation = E.Point3D(0, math.pi/2, 0)   # 父在(5,0,0) 且绕Y 90°
# 子世界位置 = 父原点(5,0,0) + 局部偏移(2,0,0)旋转90° -> (0,0,-2)  => (5,0,-2)
wp = eng.world_position(child)
check("子世界位置 = (5,0,0)+局部(2,0,0)旋转后=(5,0,-2)",
      abs(wp.x-5.0)<1e-6 and abs(wp.y)<1e-6 and abs(wp.z-(-2.0))<1e-6,
      str((round(wp.x,3), round(wp.y,3), round(wp.z,3))))
# 往返: 世界点 (5,0,-2) 换回局部应为 (2,0,0)
loc = eng.world_to_local(child, (5.0, 0.0, -2.0))
check("world_to_local(5,0,-2) 换回局部 (2,0,0)",
      tuple(round(v,6) for v in (loc.x, loc.y, loc.z)) == (2,0,0),
      str((round(loc.x,3), round(loc.y,3), round(loc.z,3))))

# 5) 防环: 不能把 root 设成 grand 的子, 不能设成自己
n0 = len(eng.collect_subtree(root))
eng.set_parent(root, grand)
check("防环: root 不能成为孙的子", root.parent is None and grand.parent is child)
eng.set_parent(child, child)
check("防环: 不能设自己为父", child.parent is root)

# 6) collect_subtree (DFS 前序: 根, 子, 孙)
names = [m.name for m in eng.collect_subtree(root)]
check("collect_subtree DFS 前序 [根,子,孙]", names == ["根", "子", "孙"], str(names))

print()
print("总结果:", "ALL PASS ✅" if ok else "有 FAIL ❌")
