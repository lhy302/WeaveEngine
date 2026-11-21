# -*- coding: utf-8 -*-
"""
plugin_sandbox.py — 受限沙箱内核 (2026-08-28 渗透靶场 V06 修复;
2026-11-07 审计 scan_09 P-01/P-02 运行时收口)
================================================================================
为什么存在: Python 函数的 `__globals__` 属性是语言机制, 挡不住 —— 若受限
__import__ 检查函数定义在 plugin_loader.py, 受限插件 `__import__.__globals__`
就能拿到 plugin_loader 整个命名空间 (含 os/sys/importlib), 一行写出任意文件
(攻击靶场 _attack_range_普通插件释毒实验 V06 实锤; 修复前任何内置函数皆可
榨出真 builtins → open)。

对策 (2026-08-28 双层, 2026-11-07 增补运行时层):
  1. 检查函数定义在**本模块** (改名 restricted_import, 不用下划线防"私有"
     命名也逃不过属性访问 —— 名字无关紧要, 关键是对象的 __globals__);
  2. plugin_loader._load_entry_restricted 首次加载受限插件时 pop 掉本模块
     __dict__ 的 `__builtins__` (见 _strip_builtins 注释) —— 于是本模块
     globals 只剩: 字符串常量、frozenset、函数自己 (本模块函数全部用
     "定义时默认参数"绑定所需内建, 不依赖 builtins 查找)。
  3. **P-01 运行时收口 (2026-11-07)**: 白名单模块不再把**真模块对象**交给
     插件, 一律返回 _ModuleProxy 代理 —— 代理只放行"非下划线属性", 且拒绝
     任何子模块对象。堵死三条已证实的逃逸链:
       collections._sys / random._os / collections._collections_abc (下划线)
       json.codecs / re.enum / re.functools (二跳子模块)
     代理把真模块关在 __slots__ 里, 且该槽名本身也以下划线开头 → 读不到。
  4. **P-02 运行时收口 (2026-11-07)**: 受限插件拿到的 api 是 _GuardedApi
     代理, 方法调用经 _GuardedCall 转发; 宿主侧抛出的异常在**离开 except
     块之后**被替换成"只保留类型+消息"的新异常 → 插件的`e.__traceback__`
     里只剩 [插件自己的帧, 本模块的转发帧], 拿不到 plugin_loader 的
     f_globals (os/sys/importlib 全在), 也没有 `__context__` 可回溯。
     (审计建议的 `raise ... from None` 只屏蔽打印, `__context__` 仍可
     访问; 本实现直接让宿主异常对象不进插件视野, 比 from None 更强。)

⚠️ 本模块**禁止有任何模块级 import** (包括 re/os/typing): 任何模块对象住进
命名空间 = __import__.__globals__ 可摸。测试 t_restricted_sandbox_clean 断言
sandbox_globals_clean() 为 True, 未来有人加 import 会直接 FAIL。
⚠️ 本模块的 __builtins__ 会在受限加载时被剥离: **凡函数体里用到的内建,
必须在定义时绑定 (默认参数) 或固化成下面的模块级别名**, 否则运行期 NameError。
"""
# ---- 白名单 (纯标准库"计算/数据结构"模块, 命名空间经全量探测核实) ----
# 2026-08-28 两轮攻击靶场收口:
#   ① scripts/engine/matlib 已移出 (命名空间真实含 os/sys/np/pygame → V04/V07);
#   ② dataclasses/typing 已移出 (第二轮复扫实锤: 命名空间**直挂 sys**,
#      `dataclasses.sys.modules['os']` 纯语法三行即通 = m05, 连 getattr
#      都不需要); 其余 (re/random/copy/json 等) 只直挂 __builtins__ 且属
#      黑面属性名 (AST 拦) + 检索原语已撤 (无实现可达路径)。
#   ③ 插件要引擎能力一律走 api.*; 白名单**运行时快检**兜底 stdlib 漂移
#      (见 restricted_import 里 _DANGER_NAMES 扫描, 未来 Python 版本给
#      白名单模块塞了 os/sys 就直接拒载, 不会静默带回漏洞)。
#   ④ 2026-11-07 (scan_09 P-01): 白名单模块只以 **_ModuleProxy** 代理形式
#      交到插件手里, 真模块对象永不外泄 (代理细节见文件头对策 3)。
_RESTRICTED_MODULES = frozenset((
    'math', 'itertools', 're', 'collections', 'functools', 'random',
    'copy', 'json',
))

# 运行时快检危险名: 白名单模块命名空间**直接**挂这些名字 = 立即拒载.
# (模块直挂 __builtins__ 是通用语言现象, 已无可达路径 —— 检索原语全撤 +
# __builtins__ 在黑面 AST 拦, 故不列入; 其余系统模块名一律查。)
# 2026-11-07 P-01: 代理层已拒绝一切子模块/下划线属性, 本表退化为"版本漂移
# 早退"的第二道门 (双保险, 不删)。
_DANGER_ATTR_NAMES = frozenset((
    'os', 'sys', 'subprocess', 'shutil', 'socket', 'ctypes', 'threading',
    'tempfile', 'pathlib', 'pickle', 'webbrowser', 'signal', 'mmap',
    'asyncio', 'platform', 'glob', 'gc',
))
# ---- 黑名单 (显式拒, 报错更友好) ----
_BANNED_MODULES = frozenset((
    'os', 'sys', 'subprocess', 'socket', 'ctypes', 'threading',
    'multiprocessing', 'importlib', 'shutil', 'pathlib', 'tempfile',
    'urllib', 'http', 'ftplib', 'webbrowser', 'winreg', 'pickle',
    'marshal', 'atexit', 'signal', 'platform', 'asyncio',
))

# ---- 定义时绑定的内建别名 (本模块 __builtins__ 会被剥离, 见文件头 ⚠️) ----
# 这些值都是纯语言对象 (type/str/异常类/函数), **不是模块对象**, 不违反
# sandbox_globals_clean() 的"命名空间无模块对象"断言。
_type = type
_str = str
_repr = repr
_getattr = getattr
_setattr = setattr
_callable = callable
_BaseException = BaseException
_Exception = Exception
_AttributeError = AttributeError
_ImportError = ImportError
_RuntimeError = RuntimeError


def _slot_get(obj, name, _oga=object.__getattribute__):
    """按名字直取 __slots__ 槽 (绕过代理自己的 __getattribute__ 拦截)。
    模块级函数: 调用方 (代理方法) 在 __builtins__ 剥离后仍可用, 因为
    object 在定义时已绑定。"""
    return _oga(obj, name)


class _ModuleProxy(object):
    """受限模块代理 (scan_09 P-01 运行时收口).

    受限插件 import 白名单模块时拿到**本代理**而不是真模块对象:
      - 只放行非下划线属性 (collections._sys / random._os /
        collections._collections_abc 全被拒);
      - 拒绝任何子模块对象 (json.codecs / re.enum / re.functools 全被拒;
        `json.codecs.open` 这类浅层链因此断根);
      - 真模块只住在 __slots__ 的 _mp_target 里, 而槽名本身以下划线开头,
        同样被 __getattribute__ 拒绝 → 插件拿不回真模块。
    正常插件用法 (math.sqrt / re.match / json.loads / random.random ...)
    完全不受影响 (测试 t_restricted_whitelist_ok 守护)。
    """

    __slots__ = ('_mp_target',)

    def __init__(self, target, _set=object.__setattr__):
        _set(self, '_mp_target', target)

    def __getattribute__(self, name, _oga=object.__getattribute__):
        if name.startswith('_'):
            raise _AttributeError(
                '普通插件受限: 模块代理不暴露下划线属性 %r (P-01 收口)' % name)
        target = _oga(self, '_mp_target')
        value = _getattr(target, name)
        if _type(value).__name__ == 'module':
            raise _AttributeError(
                '普通插件受限: 模块代理不暴露子模块 %r (二跳系统面, P-01 收口)'
                % name)
        return value

    def __repr__(self, _oga=object.__getattribute__):
        return '<受限模块 %s>' % (_oga(self, '_mp_target'),)


def restricted_import(name, globals_=None, locals_=None, fromlist=(),
                      level=0, _imp=__import__, _hasattr=hasattr,
                      _getattr=getattr, _set=set, _sorted=sorted,
                      _ImportError=ImportError):
    """受限 __import__: 唯一放行白名单入口模块, 其余 (含运行期拼接名) 拒绝.
    2026-08-28 二轮加固: 白名单模块放行前**运行时快检**命名空间 —— 直挂
    危险名字 (os/sys/...) 立即拒载 (防 stdlib 版本漂移把"带毒模块"悄悄
    送回白名单; 复扫实锤: dataclasses/typing 直挂 sys 即此形态)。
    2026-11-07 (scan_09 P-01): 放行的模块**再次包装成 _ModuleProxy** ——
    插件拿不到真模块对象, 下划线属性与子模块一律 AttributeError:
      import collections; collections._sys.modules['builtins'].open(...) 断
      import random;      random._os / json.codecs / re.enum              断
    _imp/_hasattr/_getattr/_set/_sorted 均定义时绑定 (真内建) —— 本模块
    __builtins__ 被 pop (V06 修复) 后, 函数内部的名字查找不再有 builtins
    兜底, 凡用到的内建必须在此绑定。"""
    base = name.split('.', 1)[0]
    if name in _RESTRICTED_MODULES or base in _RESTRICTED_MODULES:
        real = _imp(name, globals_, locals_, fromlist, level)
        ns = _hasattr(real, '__dict__') and _getattr(real, '__dict__') or {}
        bad = _sorted(_set(ns) & _DANGER_ATTR_NAMES)
        if bad:
            raise _ImportError('普通插件受限: 白名单模块 %s 命名空间直挂'
                               '危险模块 %s (运行时快检, 拒载)' % (name, bad))
        return _ModuleProxy(real)
    if base in _BANNED_MODULES or name in _BANNED_MODULES:
        raise _ImportError('普通插件受限: 危险模块被禁止导入: %s' % name)
    raise _ImportError('普通插件受限: 不允许导入: %s (白名单: math/re/'
                       'collections/itertools/functools/random/copy/json; '
                       '引擎能力走 api.*)' % name)


def _clean_raise(cls, message, _RuntimeError=RuntimeError,
                 _Exception=Exception):
    """抛"只保留类型 + 消息"的新异常 (scan_09 P-02 运行时收口).

    **必须在本模块的 except 块之外调用** —— 此时 sys.exc_info() 已清空,
    新异常因此没有 __context__, 也没有宿主栈帧 (本模块命名空间已"榨无可榨"):
    插件 `e.__traceback__.tb_next.tb_frame.f_globals` 只能摸到字符串/常量。
    """
    try:
        new = cls(message)
    except _Exception:
        new = _RuntimeError(message)
    raise new


class _GuardedCall(object):
    """受限插件拿到的 api 方法壳 (scan_09 P-02): 宿主异常在边界被清洗.

    调用链: 插件帧 → _GuardedCall.__call__ (本模块帧) → 宿主 api 方法.
    宿主异常被 __call__ 捕获后**丢弃**, 在 except 之外重新抛一个同类型同
    消息的新异常 → 插件侧异常链只剩 [插件自己, 本模块帧], 宿主帧
    (plugin_loader, 含 os/sys/importlib) 不进 traceback。
    """

    __slots__ = ('_gc_fn',)

    def __init__(self, fn, _set=object.__setattr__):
        _set(self, '_gc_fn', fn)

    def __getattribute__(self, name, _oga=object.__getattribute__):
        if name.startswith('_'):
            raise _AttributeError('普通插件受限: api 方法壳不暴露私有属性 %r'
                                  % name)
        return _oga(self, name)

    def __call__(self, *args, **kwargs):
        fn = _slot_get(self, '_gc_fn')
        err = None
        try:
            return fn(*args, **kwargs)
        except _BaseException as e:
            err = (_type(e), _str(e))
        # 已出 except 块: 新异常不带 __context__ (上面捕获的宿主异常被丢弃)
        _clean_raise(err[0], err[1])


class _GuardedApi(object):
    """受限插件看到的 api 代理 (scan_09 P-02 运行时收口).

    属性一律转发给真 PluginAPI; **可调用属性**包成 _GuardedCall, 于是插件
    永远拿不到"会抛宿主原始异常"的真绑定方法。真 api 句柄只在 __slots__
    的 _ga_impl 里, 该名字被 __getattribute__/__setattr__ 明确拒绝。
    构造/转发只发生在宿主侧 (plugin_loader._load_one), 插件侧无入口。
    """

    __slots__ = ('_ga_impl',)

    def __init__(self, impl, _set=object.__setattr__):
        _set(self, '_ga_impl', impl)

    def __getattribute__(self, name, _oga=object.__getattribute__):
        if name == '_ga_impl':
            raise _AttributeError('普通插件受限: api 代理内部句柄不可访问')
        impl = _oga(self, '_ga_impl')
        value = _getattr(impl, name)
        if _callable(value):
            return _GuardedCall(value)
        return value

    def __setattr__(self, name, value, _oga=object.__getattribute__):
        if name == '_ga_impl':
            raise _AttributeError('普通插件受限: api 代理内部句柄不可写')
        _setattr(_oga(self, '_ga_impl'), name, value)

    def __repr__(self, _oga=object.__getattribute__):
        return '<受限api %r>' % (_oga(self, '_ga_impl'),)


def guard_api(impl, _GuardedApi=_GuardedApi):
    """宿主侧调用: 给受限插件构造 api 代理壳 (scan_09 P-02)。"""
    return _GuardedApi(impl)


def sandbox_globals_clean(_globals=globals, _type=type):
    """自检: 本模块命名空间必须"榨无可榨" (无模块对象 / 无 __builtins__).
    攻击者若经 __import__.__globals__ 到这里: 有 __builtins__ 键= 真 open 可
    拿到; 有模块对象= 可能再下钻。两样都必须为 False。
    _globals/_type 定义时绑定 (函数帧内 globals() 返回**定义模块**的命名空间
    —— 不要用 vars(), 它在函数帧里返回局部 dict): 本函数在 __builtins__ 被
    pop 后仍可调用。
    """
    for k, v in _globals().items():
        if k == '__builtins__':
            return False
        if _type(v).__name__ == 'module':
            return False
    return True


def _strip_builtins(_globals=globals):
    """plugin_loader 在加载受限插件前调用: 移除本模块 dict 的 __builtins__.
    之后本模块内任意函数 (restricted_import/sandbox_globals_clean/代理方法)
    均不依赖 builtins 查找 (定义时已绑定), 仅"模块全局名字查不到会向上找
    builtins"的语言路径被切断 —— 这正是 V06 的目标。
    """
    _globals().pop('__builtins__', None)
