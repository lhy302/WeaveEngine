# -*- coding: utf-8 -*-
"""module_loader.py — Loom 核心组件加载器 (DLL化战役 M1-3, 契约 Python 侧机械层)

地位: loom_module.h (C ABI v1.0) 的 Python 镜像 + LoadLibrary/校验/热重载原语。
本模块只做**机械层**: 加载、校验、调用、卸载。策略层 (槽位/回退/注册表规则)
一律不做 — 那是 module_registry.py (M1-2) 的职责。

纪律 (交接文档 §4.1):
  · 不 import module_registry / fastpath / engine (无反向依赖, 可单独测)。
  · LoomModuleInfo 布局 = 4+4+64+16+4+4+4+4 = 104 字节 (无对齐尾补);
    按 65 字节建镜像会让后续字段整体错位 (已实证), 故模块级 assert 钉死。
  · 模块级 _LIVE dict 持句柄防 GC (Nuitka 折叠防御, 同 fastpath._CK 惯例)。
"""
import ctypes
import hashlib
import os
import sys
from ctypes import (POINTER, Structure, byref, c_char_p, c_int32, c_int64,
                    c_uint32, c_void_p)

# ---------------------------------------------------------------------------
# 常量 (严格对齐 loom_module.h)
# ---------------------------------------------------------------------------
LOOM_MODULE_MAGIC = 0x4D4F4F4C
LOOM_NAME_MAX = 63
LOOM_TENSOR_MAX_DIM = 4

LOOM_DTYPE_F32 = 0
LOOM_DTYPE_F64 = 1
LOOM_DTYPE_I32 = 2
LOOM_DTYPE_I64 = 3
LOOM_DTYPE_U8 = 4

LOOM_OK = 0
LOOM_ERR_CAPACITY = -1
LOOM_ERR_PARAM = -2
LOOM_ERR_INTERNAL = -3
LOOM_ERR_ABI = -4
LOOM_ERR_NO_INIT = -5
LOOM_ERR_UNSUPPORTED = -6

# provides/depends 枚举上限 (畸形 DLL 防呆: 谎报巨大 count 不得拖死枚举)
LOOM_MAX_INTERFACES = 4096

# 6 个必需导出 (契约 7 个里 has 可选; 缺席 = 基座按 0 处理)
LOOM_REQUIRED_EXPORTS = ('loom_module_info', 'loom_module_provide',
                         'loom_module_depend', 'loom_module_init',
                         'loom_module_deinit', 'loom_module_abi')
LOOM_OPTIONAL_EXPORTS = ('loom_module_has',)

_DTYPE_BY_KIND = {'f4': LOOM_DTYPE_F32, 'f8': LOOM_DTYPE_F64,
                  'i4': LOOM_DTYPE_I32, 'i8': LOOM_DTYPE_I64,
                  'u1': LOOM_DTYPE_U8}


def loom_abi_make(major, minor):
    return ((int(major) & 0xFFFF) << 16) | (int(minor) & 0xFFFF)


def loom_abi_major(v):
    return (int(v) >> 16) & 0xFFFF


def loom_abi_minor(v):
    return int(v) & 0xFFFF


LOOM_ABI_VERSION_CURRENT = loom_abi_make(1, 0)


# ---------------------------------------------------------------------------
# 异常族 (基座按类型决定策略: 弹出 / 报错不降级 / 感知缺件)
# ---------------------------------------------------------------------------
class ModuleLoadError(Exception):
    """加载器异常基类。"""


class ModuleValidationFailed(ModuleLoadError):
    """加载或校验失败 → 基座 catch 后弹出该模块 (用户注入) 或 AssemblyError (官方)。"""


class ModuleNotAvailable(ModuleLoadError):
    """LOOM_NO_DLL 跳过 / 槽位空 / 已卸载 → get 抛此异常 (调用方感知缺件)。"""


class AssemblyError(ModuleLoadError):
    """官方组件坏 / 注册表结构错 → 绝不静默降级。"""


# ---------------------------------------------------------------------------
# POD 结构体镜像
# ---------------------------------------------------------------------------
class LoomModuleInfo(Structure):
    _fields_ = [('magic', c_uint32),
                ('abi_version', c_uint32),
                ('module_id', ctypes.c_char * (LOOM_NAME_MAX + 1)),
                ('version', ctypes.c_char * 16),
                ('official', c_uint32),
                ('provides_count', c_uint32),
                ('depends_count', c_uint32),
                ('reserved', c_uint32)]


class LoomTensor(Structure):
    _fields_ = [('data', c_void_p),
                ('shape', c_int64 * LOOM_TENSOR_MAX_DIM),
                ('ndim', c_int32),
                ('dtype', c_int32)]


# 布局铁律: MSVC 实测 104 字节 (无对齐尾补)。错位即读出垃圾字段。
assert ctypes.sizeof(LoomModuleInfo) == 104, (
    'LoomModuleInfo 布局错位: %d != 104 (module_id 数组必须 64 字节)'
    % ctypes.sizeof(LoomModuleInfo))
assert ctypes.sizeof(LoomTensor) == 48, (
    'LoomTensor 布局错位: %d != 48' % ctypes.sizeof(LoomTensor))

# 句柄保活表 (path → ModuleHandle); Nuitka 对 dict 内容不做常量折叠。
_LIVE = {}


def _tensor_from_array(arr):
    """numpy 数组 → (LoomTensor, keepalive)。

    keepalive 必须由调用方持有到 DLL 调用结束 (否则底层缓冲可能被回收)。
    numpy 延迟 import (本模块在无 numpy 环境也应可 import)。
    """
    import numpy as np
    a = np.ascontiguousarray(arr)
    ndim = int(a.ndim)
    if ndim < 1 or ndim > LOOM_TENSOR_MAX_DIM:
        raise ModuleValidationFailed('tensor_from_array: ndim=%d 越界 (1..4)' % ndim)
    kind = a.dtype.kind + str(a.dtype.itemsize)
    dtype = _DTYPE_BY_KIND.get(kind)
    if dtype is None:
        raise ModuleValidationFailed('tensor_from_array: 不支持的 dtype %r' % (a.dtype,))
    t = LoomTensor()
    t.data = c_void_p(int(a.ctypes.data))
    for i in range(LOOM_TENSOR_MAX_DIM):
        t.shape[i] = int(a.shape[i]) if i < ndim else 0
    t.ndim = ndim
    t.dtype = dtype
    return t, a


tensor_from_array = _tensor_from_array


def no_dll_skips():
    """LOOM_NO_DLL 逃生门解析: 未设→空集; '*'→{'*'}; 'a,b'→{'a','b'}。"""
    raw = os.environ.get('LOOM_NO_DLL', '') or ''
    raw = raw.strip()
    if not raw:
        return set()
    if raw == '*':
        return {'*'}
    return set(x.strip() for x in raw.split(',') if x.strip())


def file_sha256(path):
    """磁盘文件 SHA256 (十六进制小写)。注册表 sha256 前置闸用。"""
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()


# ---------------------------------------------------------------------------
# 模块句柄
# ---------------------------------------------------------------------------
class ModuleHandle(object):
    """一个已加载 (可选已 init) 的核心组件 DLL。

    生命周期: load() → init() → 使用 → deinit() → unload(); 或 hot_reload()。
    """

    def __init__(self):
        self.path = None
        self.module_id = None
        self.version = None
        self.official = 0
        self.abi_version = 0
        self.provides = ()
        self.depends = ()
        self.inited = False
        self._dll = None
        self._fn = {}
        self._info = None

    # -- 内部 ---------------------------------------------------------------
    def _bind(self, dll, name, restype, argtypes):
        try:
            fn = getattr(dll, name)
        except AttributeError:
            raise ModuleValidationFailed(
                '导出缺席: %s (path=%s)' % (name, self.path))
        fn.restype = restype
        fn.argtypes = argtypes
        return fn

    def _read_info(self):
        info_fn = self._fn['loom_module_info']
        ptr = info_fn()
        if not ptr:
            raise ModuleValidationFailed('loom_module_info() 返回 NULL (path=%s)' % self.path)
        info = ctypes.cast(ptr, POINTER(LoomModuleInfo)).contents
        self._info = info
        if info.magic != LOOM_MODULE_MAGIC:
            raise ModuleValidationFailed(
                'magic 不符: 0x%08X != 0x%08X (path=%s)'
                % (info.magic, LOOM_MODULE_MAGIC, self.path))
        base_major = loom_abi_major(LOOM_ABI_VERSION_CURRENT)
        if loom_abi_major(info.abi_version) != base_major:
            raise ModuleValidationFailed(
                'ABI 主版本不符: DLL=0x%08X (主 %d) 基座主 %d (path=%s)'
                % (info.abi_version, loom_abi_major(info.abi_version),
                   base_major, self.path))
        abi_fn = self._fn['loom_module_abi']
        quick = int(abi_fn())
        if quick != int(info.abi_version):
            raise ModuleValidationFailed(
                '双口 ABI 不一致: loom_module_abi()=0x%08X info.abi_version=0x%08X (path=%s)'
                % (quick, info.abi_version, self.path))
        self.abi_version = int(info.abi_version)

    @staticmethod
    def _strict_utf8(raw, field, path):
        try:
            s = raw.decode('utf-8')
        except UnicodeDecodeError as e:
            raise ModuleValidationFailed('%s 非严格 UTF-8: %s (path=%s)' % (field, e, path))
        if '\x00' in s:
            raise ModuleValidationFailed('%s 含内嵌 NUL (path=%s)' % (field, path))
        return s

    def _read_identity(self):
        info = self._info
        mid = self._strict_utf8(bytes(info.module_id), 'module_id', self.path)
        if not mid or len(mid) > LOOM_NAME_MAX:
            raise ModuleValidationFailed(
                'module_id 长度违约 (%d, 上限 %d): %r (path=%s)'
                % (len(mid), LOOM_NAME_MAX, mid, self.path))
        ver = self._strict_utf8(bytes(info.version), 'version', self.path)
        if not ver:
            raise ModuleValidationFailed('version 为空 (path=%s)' % self.path)
        self.module_id = mid
        self.version = ver
        self.official = int(info.official)

    def _enum(self, fn_name, count, kind):
        """枚举 provides/depends 全集: NULL/重复/超上限/越界未返 NULL 皆失败。"""
        if count > LOOM_MAX_INTERFACES:
            raise ModuleValidationFailed(
                '%s_count=%d 超上限 %d (path=%s)'
                % (kind, count, LOOM_MAX_INTERFACES, self.path))
        fn = self._fn[fn_name]
        out = []
        seen = set()
        for i in range(int(count)):
            raw = fn(i)
            if not raw:
                raise ModuleValidationFailed(
                    '%s(%d) 返回 NULL (声明 count=%d) (path=%s)'
                    % (fn_name, i, count, self.path))
            name = self._strict_utf8(bytes(raw), kind, self.path)
            if not name:
                raise ModuleValidationFailed(
                    '%s(%d) 为空串 (path=%s)' % (fn_name, i, self.path))
            if name in seen:
                raise ModuleValidationFailed(
                    '%s 重复: %r (path=%s)' % (kind, name, self.path))
            seen.add(name)
            out.append(name)
        # 越界必须返 NULL (契约); 不返 = 谎报 count
        if fn(int(count)):
            raise ModuleValidationFailed(
                '%s(%d) 越界未返回 NULL (谎报 count) (path=%s)' % (fn_name, count, self.path))
        return tuple(out)

    # -- 公开 API -----------------------------------------------------------
    @property
    def is_live(self):
        """句柄是否仍可用 (DLL 未卸载)。热重载/卸载后为 False。
        供胶水层惰性句柄缓存判据 (script_glue/physics_glue 的 handle()):
        未定义本属性时 getattr(h,'is_live',False) 恒 False -> 每调用重装配 (性能 bug)。"""
        return self._dll is not None

    @classmethod
    def load(cls, path, expected_module_id=None):
        """LoadLibrary + 完整校验链 → ModuleHandle。失败抛 ModuleValidationFailed。"""
        h = cls()
        h.path = os.path.abspath(path)
        if not os.path.isfile(h.path):
            raise ModuleValidationFailed('路径不存在: %s' % h.path)
        try:
            h._dll = ctypes.WinDLL(h.path)
        except OSError as e:
            raise ModuleValidationFailed('LoadLibrary 失败: %s (path=%s)' % (e, h.path))
        try:
            # ① 必需导出在位 + 签名绑定 (按契约 typedef)
            h._fn['loom_module_info'] = h._bind(
                h._dll, 'loom_module_info', POINTER(LoomModuleInfo), [])
            h._fn['loom_module_provide'] = h._bind(
                h._dll, 'loom_module_provide', c_char_p, [c_uint32])
            h._fn['loom_module_depend'] = h._bind(
                h._dll, 'loom_module_depend', c_char_p, [c_uint32])
            h._fn['loom_module_init'] = h._bind(
                h._dll, 'loom_module_init', c_int32, [])
            h._fn['loom_module_deinit'] = h._bind(
                h._dll, 'loom_module_deinit', None, [])
            h._fn['loom_module_abi'] = h._bind(
                h._dll, 'loom_module_abi', c_uint32, [])
            try:
                h._fn['loom_module_has'] = h._bind(
                    h._dll, 'loom_module_has', c_int32, [c_char_p])
            except ModuleValidationFailed:
                h._fn['loom_module_has'] = None      # 可选导出缺席
            # ② info: 非 NULL / magic / ABI 主版本 / 双口一致
            h._read_info()
            # ③ 身份: 严格 utf-8 + 长度守约
            h._read_identity()
            # ④ provides/depends 枚举 (声明值 vs 实际枚举)
            h.provides = h._enum('loom_module_provide',
                                 h._info.provides_count, 'provides')
            h.depends = h._enum('loom_module_depend',
                                h._info.depends_count, 'depends')
            # ⑤ 期望槽位一致
            if expected_module_id is not None and h.module_id != expected_module_id:
                raise ModuleValidationFailed(
                    'module_id 不符: DLL=%r 期望=%r (path=%s)'
                    % (h.module_id, expected_module_id, h.path))
        except ModuleValidationFailed:
            h._release()
            raise
        _LIVE[h.path] = h
        return h

    def has(self, iface_name):
        """查询命名接口是否可用 (loom_module_has 缺席 → False)。"""
        fn = self._fn.get('loom_module_has')
        if fn is None or iface_name is None:
            return False
        try:
            return int(fn(iface_name.encode('utf-8'))) == 1
        except OSError:
            raise

    def get_fn(self, name, restype, argtypes):
        """取导出函数 (dict 缓存 + 绑定签名); 已卸载抛 ModuleNotAvailable。"""
        if self._dll is None:
            raise ModuleNotAvailable('模块已卸载: %s' % (self.module_id or self.path))
        key = (name, restype, tuple(argtypes))
        if key in self._fn:
            return self._fn[key]
        fn = self._bind(self._dll, name, restype, argtypes)
        self._fn[key] = fn
        return fn

    def init(self):
        """资源建立; 已 inited 幂等返 0; 失败抛 ModuleValidationFailed。"""
        if self.inited:
            return 0
        if self._dll is None:
            raise ModuleNotAvailable('模块已卸载: %s' % (self.module_id or self.path))
        rc = int(self._fn['loom_module_init']())
        if rc != LOOM_OK:
            raise ModuleValidationFailed(
                'loom_module_init() 返回 %d (path=%s)' % (rc, self.path))
        self.inited = True
        return rc

    def deinit(self):
        """资源释放; 未 inited 幂等; 之后 DLL 内不得再持基座指针。"""
        if not self.inited or self._dll is None:
            self.inited = False
            return
        self._fn['loom_module_deinit']()
        self.inited = False

    def _release(self):
        """FreeLibrary + 清缓存 + 移出 _LIVE (失败仅 stderr warning)。"""
        self._fn = {}
        self._info = None
        self.inited = False
        dll = self._dll
        self._dll = None
        if dll is not None:
            handle = getattr(dll, '_handle', None)
            del dll
            if handle:
                try:
                    ctypes.windll.kernel32.FreeLibrary(c_void_p(handle))
                except Exception as e:      # pragma: no cover - 仅诊断
                    sys.stderr.write('module_loader: FreeLibrary 失败 %s (%s)\n'
                                     % (self.path, e))
        if self.path in _LIVE:
            del _LIVE[self.path]

    def unload(self):
        """deinit + FreeLibrary + 清缓存 + 移出 _LIVE。幂等。"""
        self.deinit()
        self._release()

    def hot_reload(self, new_path=None):
        """deinit → unload → load(同 module_id) → init。返回新句柄。"""
        module_id = self.module_id
        target = new_path or self.path
        self.unload()
        h = ModuleHandle.load(target, expected_module_id=module_id)
        h.init()
        return h

    def __repr__(self):
        return ('<ModuleHandle %s v%s official=%d provides=%d depends=%d inited=%s>'
                % (self.module_id, self.version, self.official,
                   len(self.provides), len(self.depends), self.inited))
