# -*- coding: utf-8 -*-
r"""script_glue.py — 基座 ↔ script.dll 接线层 (M4, 2026-10-01)

职责: 封装 script.dll 的纯 C 运动类接口, 提供批量自转 (batch_rotate)
      与嵌入式 Lua 5.4 VM 的原生调用。
      天然释放 Python GIL, 无跨帧隐藏状态。

★B3 退役 (2026-10-16): 删 LOOM_NO_SCRIPT_DLL 整体禁用门 + batch_move 死代码
(engine.update_scripts 的 move/linear_move 分流从未被触发)。
失败语义: handle() 拿不到官方件硬 raise (官方件不兜底, 与 B1/B2 同纪律)。
LOOM_NO_DLL='script' (注册表层跳过槽位) 仍保留 (仅注册表探针使用)。
"""
import ctypes
import os
import sys
import threading

_HERE = os.path.dirname(os.path.abspath(__file__))
_CC = os.path.join(_HERE, 'core_components')
for _p in (_CC, _HERE):
    if _p not in sys.path:
        sys.path.insert(0, _p)

LOCK = threading.Lock()
_STATE = {'tried': False, 'handle': None, 'error': None}


def handle():
    """惰性组装并返回 script 句柄; 失败硬 raise (官方件不兜底)。

    ★B3 退役 (2026-10-16): 删 LOOM_NO_SCRIPT_DLL 整体禁用门 + 静默降级。
    script 是官方组件, 唯一路径; 缺失/加载失败 = 引擎缺陷, 硬 raise
    (与 B1 ckernels / B2 pipeline 同纪律, 见 docs/design/逃生门退役设计.md §6)。
    """
    h = _STATE['handle']
    if h is not None and getattr(h, 'is_live', False):
        return h
    with LOCK:
        h = _STATE['handle']
        if h is not None and getattr(h, 'is_live', False):
            return h
        import module_registry as mr
        asm = mr.assemble(persist=False)
        h = asm.get('script')                # 拿不到硬抛 ModuleNotAvailable
        _STATE['handle'] = h
        _STATE['tried'] = True
        _STATE['error'] = None
        return h


def batch_rotate(rot, speeds_deg, dt, out_rot=None):
    """批量自转 (C 原生实现).
    rot: (n, 3) float64 弧度
    speeds_deg: (n, 3) float64 角速度 (度/秒)
    dt: float 秒
    out_rot: 可选 (n, 3) 输出缓冲
    返回: out_rot (n, 3) 或 None (失败/回退)
    """
    h = handle()
    import numpy as np
    r = np.ascontiguousarray(rot, dtype=np.float64)
    s = np.ascontiguousarray(speeds_deg, dtype=np.float64)
    n = int(r.shape[0])
    if n == 0:
        return out_rot if out_rot is not None else np.empty((0, 3), dtype=np.float64)
    if out_rot is None or out_rot.shape[0] < n:
        out = np.empty((n, 3), dtype=np.float64)
    else:
        out = out_rot
    pd = ctypes.POINTER(ctypes.c_double)
    fn = h.get_fn('loom_script_batch_rotate', ctypes.c_int32,
                  [pd, pd, ctypes.c_double, ctypes.c_int64, pd])
    rc = int(fn(r.ctypes.data_as(pd), s.ctypes.data_as(pd),
                ctypes.c_double(dt), ctypes.c_int64(n),
                out.ctypes.data_as(pd)))
    if rc != 0:                          # ★B3: 契约违约硬 raise
        raise RuntimeError('loom_script_batch_rotate 失败 rc=%d' % rc)
    return out


# ★B3 退役 (2026-10-16): batch_move 是死代码 —— engine.update_scripts 的
# move/linear_move 分流从未被触发 (scripts.py 无对应脚本)。C 侧 ABI
# (loom_script_batch_move) 保留不动, 基座侧包装删除。


class LoomLuaScript:
    """Lua 5.4 嵌入式虚拟机脚本运行时包装 (M4)"""

    def __init__(self, code=""):
        self.code = code
        self.vm = None
        self._broken = False
        self._started = False
        self._pos_buf = (ctypes.c_double * 3)(0.0, 0.0, 0.0)
        self._rot_buf = (ctypes.c_double * 3)(0.0, 0.0, 0.0)
        self._cam_buf = (ctypes.c_double * 3)(0.0, 0.0, 0.0)
        self._init_vm()

    def _init_vm(self):
        h = handle()      # ★B3: 失败硬 raise (官方件不兜底)
        fn_new = h.get_fn('loom_script_lua_new', ctypes.c_void_p, [])
        self.vm = fn_new()
        if not self.vm:
            self._broken = True
            return
        if self.code:
            fn_do = h.get_fn('loom_script_lua_dostring', ctypes.c_int32,
                             [ctypes.c_void_p, ctypes.c_char_p])
            rc = fn_do(self.vm, self.code.encode('utf-8'))
            if rc != 0:
                self._broken = True

    def bind_entity(self, pos, rot, name=""):
        if self._broken or not self.vm:
            return
        self._pos_buf[0] = float(pos[0])
        self._pos_buf[1] = float(pos[1])
        self._pos_buf[2] = float(pos[2])
        self._rot_buf[0] = float(rot[0])
        self._rot_buf[1] = float(rot[1])
        self._rot_buf[2] = float(rot[2])
        h = handle()
        fn_bind = h.get_fn('loom_script_lua_bind_entity', ctypes.c_int32,
                           [ctypes.c_void_p, ctypes.POINTER(ctypes.c_double),
                            ctypes.POINTER(ctypes.c_double), ctypes.c_char_p])
        fn_bind(self.vm, self._pos_buf, self._rot_buf, name.encode('utf-8'))

    def set_key(self, key, pressed):
        if self._broken or not self.vm:
            return
        h = handle()
        fn_key = h.get_fn('loom_script_lua_set_key', ctypes.c_int32,
                          [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_int32])
        fn_key(self.vm, key.encode('utf-8'), 1 if pressed else 0)

    def set_action(self, action, active):
        if self._broken or not self.vm:
            return
        h = handle()
        fn_act = h.get_fn('loom_script_lua_set_action', ctypes.c_int32,
                          [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_int32])
        fn_act(self.vm, action.encode('utf-8'), 1 if active else 0)

    def bind_camera(self, cam_target):
        if self._broken or not self.vm:
            return
        self._cam_buf[0] = float(cam_target[0])
        self._cam_buf[1] = float(cam_target[1])
        self._cam_buf[2] = float(cam_target[2])
        h = handle()
        fn_cam = h.get_fn('loom_script_lua_bind_camera', ctypes.c_int32,
                          [ctypes.c_void_p, ctypes.POINTER(ctypes.c_double)])
        fn_cam(self.vm, self._cam_buf)

    def call_start(self):
        if self._broken or not self.vm:
            return -1
        h = handle()
        fn_start = h.get_fn('loom_script_lua_call_start', ctypes.c_int32,
                            [ctypes.c_void_p])
        rc = fn_start(self.vm)
        if rc == 0:
            self._started = True
        else:
            self._broken = True
        return rc

    def call_update(self, dt):
        if self._broken or not self.vm:
            return -1
        h = handle()
        fn_upd = h.get_fn('loom_script_lua_call_update', ctypes.c_int32,
                          [ctypes.c_void_p, ctypes.c_double])
        rc = fn_upd(self.vm, ctypes.c_double(dt))
        if rc != 0:
            self._broken = True
        return rc

    def get_error(self):
        if not self.vm:
            return "vm not initialized"
        h = handle()
        fn_err = h.get_fn('loom_script_lua_get_error', ctypes.c_char_p,
                          [ctypes.c_void_p])
        res = fn_err(self.vm)
        return res.decode('utf-8', errors='ignore') if res else ""

    def close(self):
        if self.vm:
            h = handle()      # ★B3: 失败硬 raise
            fn_free = h.get_fn('loom_script_lua_free', None,
                               [ctypes.c_void_p])
            fn_free(self.vm)
            self.vm = None


def status():
    """一行诊断串。"""
    h = handle()
    return 'script: %s v%s official=%d' % (h.module_id, h.version, h.official)
