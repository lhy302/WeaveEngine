# -*- coding: utf-8 -*-

"""
test_scripts_lua_close.py — Lua 脚本 VM 释放回归 (scan_09 P-09/P-25)

背景 (审计 docs/audit/scan_09_scripting.md P-09)
------------------------------------------------
scripts.make_lua_script_class 生成的 DynamicLuaScript 每次 on_start 都
loom_script_lua_new 一台 lua_State, 但**全仓没有任何 close() 调用点**:
  - DynamicLuaScript 不实现 on_disable/on_destroy (基类实现是 pass);
  - script_glue.LoomLuaScript 无 __del__。
于是每次"播放 -> 停止"或"删除挂了 .lua 脚本的物体"都线性泄漏一台 VM
(C 侧 lua_State + 预载标准库), 编辑器反复调试即持续涨内存。

修复 (2026-11-07):
  - DynamicLuaScript.on_disable / on_destroy -> _close_lua() (幂等, 置 None);
  - on_start 重入前先释放旧 VM; 启动失败也释放半初始化的 VM;
  - script_glue.LoomLuaScript.close() 幂等 (先置 vm=None 再 free, 不二次 free)
    且**不抛** (生命周期钩子/__del__ 里抛异常只会制造新崩溃), 另加 __del__ 兜底。

本测试用假 VM/假句柄 (不需要真 script.dll), 断言:
  A: on_start 建 VM; on_disable 关掉它 (close 恰好 1 次), 实例不再持有 VM。
  B: on_destroy 同样关闭; 重复调用幂等 (close 不会二次调用)。
  C: 重入 on_start (再次播放) 先释放旧 VM, 再建新 VM。
  D: 启动失败 (构造函数抛) -> 不留半初始化 VM, 且不崩。
  E: LoomLuaScript.close() 幂等 + 释放失败不抛 (fake handle 抛异常也吞掉);
     __del__ 兜底释放。

运行: python tests\test_scripts_lua_close.py   (无头, 无 GPU, 不需要 script.dll)
"""
import sys as _sys_utf8
try:
    _sys_utf8.stdout.reconfigure(encoding='utf-8', errors='replace')
    _sys_utf8.stderr.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

import ctypes
import gc
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))            # Loom\

import script_glue as sg
import scripts

_FAILS = []


def check(name, cond, extra=""):
    print(("PASS " if cond else "FAIL ") + name + ("  " + str(extra) if extra else ""))
    if not cond:
        _FAILS.append(name)


# ---- 假 VM: 只记录 close 次数 (真 VM 需要 script.dll, 这里只验生命周期) ----
class FakeLua(object):
    def __init__(self, code=""):
        self.code = code
        self.closed = 0
        self._broken = False
        self._pos_buf = (ctypes.c_double * 3)(0.0, 0.0, 0.0)
        self._rot_buf = (ctypes.c_double * 3)(0.0, 0.0, 0.0)
        self._cam_buf = (ctypes.c_double * 3)(0.0, 0.0, 0.0)

    def bind_entity(self, pos, rot, name=""):
        pass

    def bind_camera(self, cam_target):
        pass

    def call_start(self):
        return 0

    def close(self):
        self.closed += 1


class _V(object):
    def __init__(self):
        self.x = self.y = self.z = 0.0


class _Obj(object):
    def __init__(self):
        self.position = _V()
        self.rotation = _V()
        self.name = 'lua_close_probe'


class _Eng(object):
    def __init__(self):
        self.camera_target = (0.0, 0.0, 0.0)
        self.keys = {}
        self.actions = {}


def _new_inst(cls):
    inst = cls()
    inst.obj = _Obj()
    inst.engine = _Eng()
    return inst


# ====================================================================
# A: on_disable 关闭 VM
# ====================================================================
def t_on_disable():
    cls = scripts.make_lua_script_class('probe_lua_a', 'probe', 'x = 1')
    inst = _new_inst(cls)
    inst.on_start()
    fake = inst._lua
    check("[A] on_start 建立 VM", fake is not None)
    inst.on_disable()
    check("[A] on_disable 关闭 VM (close 恰好 1 次)",
          fake.closed == 1 and inst._lua is None, (fake.closed, inst._lua))
    inst.on_disable()                       # 重复 -> 幂等
    check("[A] 重复 on_disable 幂等 (不二次 close)", fake.closed == 1, fake.closed)


# ====================================================================
# B: on_destroy 关闭 VM
# ====================================================================
def t_on_destroy():
    cls = scripts.make_lua_script_class('probe_lua_b', 'probe', 'x = 1')
    inst = _new_inst(cls)
    inst.on_start()
    fake = inst._lua
    inst.on_destroy()
    check("[B] on_destroy 关闭 VM (close 恰好 1 次)",
          fake.closed == 1 and inst._lua is None, (fake.closed, inst._lua))


# ====================================================================
# C: 重入 on_start 先释放旧 VM
# ====================================================================
def t_restart_releases_old():
    cls = scripts.make_lua_script_class('probe_lua_c', 'probe', 'x = 1')
    inst = _new_inst(cls)
    inst.on_start()
    old = inst._lua
    inst.on_start()                          # 再次播放
    new = inst._lua
    check("[C] 重入 on_start 释放旧 VM 并新建",
          old.closed == 1 and new is not old and new is not None,
          (old.closed, new is old))


# ====================================================================
# D: 启动失败不留半初始化 VM
# ====================================================================
def t_start_failure_cleanup():
    class BoomLua(FakeLua):
        def __init__(self, code=""):
            FakeLua.__init__(self, code)
            raise RuntimeError('vm 构造失败')

    orig = sg.LoomLuaScript
    sg.LoomLuaScript = BoomLua
    try:
        cls = scripts.make_lua_script_class('probe_lua_d', 'probe', 'x = 1')
        inst = _new_inst(cls)
        inst.on_start()                      # 内部 try/except: 不向外抛
        check("[D] 启动失败不崩且不持有 VM", inst._lua is None, inst._lua)
    finally:
        sg.LoomLuaScript = orig


# ====================================================================
# E: LoomLuaScript.close() 幂等 + 不抛 + __del__ 兜底
# ====================================================================
class _FakeHandle(object):
    def __init__(self, raise_on_free=False):
        self.freed = []
        self.raise_on_free = raise_on_free

    def get_fn(self, name, restype=None, argtypes=None):
        def fn(*args):
            if name == 'loom_script_lua_new':
                return 0x1234
            if name == 'loom_script_lua_free':
                if self.raise_on_free:
                    raise RuntimeError('free 失败')
                self.freed.append(args)
            return 0
        return fn


class _fake_handle_scope(object):
    """构造 + close 全程都用假句柄 (close 时才调 handle(), 只包构造不够)。"""

    def __init__(self, h):
        self.h = h
        self.orig = None

    def __enter__(self):
        self.orig = sg.handle
        sg.handle = lambda: self.h
        return self

    def __exit__(self, *exc):
        sg.handle = self.orig
        return False


def t_glue_close_idempotent():
    h = _FakeHandle()
    with _fake_handle_scope(h):
        lua = sg.LoomLuaScript('')
        check("[E] 假句柄下 VM 建立", lua.vm == 0x1234, lua.vm)
        lua.close()
        check("[E] close 释放一次并置空", len(h.freed) == 1 and lua.vm is None,
              (h.freed, lua.vm))
        lua.close()
        lua.close()
        check("[E] 重复 close 幂等 (不二次 free)", len(h.freed) == 1, h.freed)
    # 释放动作失败不抛 (生命周期钩子里不能炸)
    h2 = _FakeHandle(raise_on_free=True)
    with _fake_handle_scope(h2):
        lua2 = sg.LoomLuaScript('')
        try:
            lua2.close()
            no_raise = True
        except Exception:
            no_raise = False
        check("[E] 释放失败被吞掉 (不把停止播放变成新崩溃源) + vm 已置空",
              no_raise and lua2.vm is None, lua2.vm)


def t_glue_del_release():
    h = _FakeHandle()
    with _fake_handle_scope(h):
        lua = sg.LoomLuaScript('')
        del lua
        gc.collect()
        check("[E] __del__ 兜底释放 (GC 时 free 一次)", len(h.freed) == 1, h.freed)


if __name__ == "__main__":
    print("========== Lua 脚本 VM 释放 (scan_09 P-09/P-25) ==========")
    orig_lua = sg.LoomLuaScript
    sg.LoomLuaScript = FakeLua
    try:
        t_on_disable()
        t_on_destroy()
        t_restart_releases_old()
        t_start_failure_cleanup()
    finally:
        sg.LoomLuaScript = orig_lua
    t_glue_close_idempotent()
    t_glue_del_release()
    print()
    if _FAILS:
        print("总结果: FAIL ❌", _FAILS)
        sys.exit(1)
    print("总结果: ALL PASS ✅")
