# -*- coding: utf-8 -*-
"""
plugin_sandbox.py — 受限沙箱内核 (2026-08-28, 渗透靶场 V06 修复)
================================================================================
为什么存在: Python 函数的 `__globals__` 属性是语言机制, 挡不住 —— 若受限
__import__ 检查函数定义在 plugin_loader.py, 受限插件 `__import__.__globals__`
就能拿到 plugin_loader 整个命名空间 (含 os/sys/importlib), 一行写出任意文件
(攻击靶场 _attack_range_普通插件释毒实验 V06 实锤; 修复前任何内置函数皆可
榨出真 builtins → open)。

对策 (双层):
  1. 检查函数定义在**本模块** (改名 restricted_import, 不用下划线防"私有"
     命名也逃不过属性访问 —— 名字无关紧要, 关键是对象的 __globals__);
  2. plugin_loader._load_entry_restricted 首次加载受限插件时 pop 掉本模块
     __dict__ 的 `__builtins__` (见 _strip_builtins 注释) —— 于是本模块
     globals 只剩: 字符串常量、frozenset、函数自己 (本模块函数全部用
     "定义时默认参数"绑定所需内建, 不依赖 builtins 查找)。

⚠️ 本模块**禁止有任何模块级 import** (包括 re/os/typing): 任何模块对象住进
命名空间 = __import__.__globals__ 可摸。测试 t_restricted_sandbox_clean 断言
sandbox_globals_clean() 为 True, 未来有人加 import 会直接 FAIL。
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
_RESTRICTED_MODULES = frozenset((
    'math', 'itertools', 're', 'collections', 'functools', 'random',
    'copy', 'json',
))

# 运行时快检危险名: 白名单模块命名空间**直接**挂这些名字 = 立即拒载.
# (模块直挂 __builtins__ 是通用语言现象, 已无可达路径 —— 检索原语全撤 +
# __builtins__ 在黑面 AST 拦, 故不列入; 其余系统模块名一律查。)
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


def restricted_import(name, globals_=None, locals_=None, fromlist=(),
                      level=0, _imp=__import__, _hasattr=hasattr,
                      _getattr=getattr, _set=set, _sorted=sorted,
                      _ImportError=ImportError):
    """受限 __import__: 唯一放行白名单入口模块, 其余 (含运行期拼接名) 拒绝.
    2026-08-28 二轮加固: 白名单模块放行前**运行时快检**命名空间 —— 直挂
    危险名字 (os/sys/...) 立即拒载 (防 stdlib 版本漂移把"带毒模块"悄悄
    送回白名单; 复扫实锤: dataclasses/typing 直挂 sys 即此形态)。
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
        return real
    if base in _BANNED_MODULES or name in _BANNED_MODULES:
        raise _ImportError('普通插件受限: 危险模块被禁止导入: %s' % name)
    raise _ImportError('普通插件受限: 不允许导入: %s (白名单: math/re/'
                       'collections/itertools/functools/random/copy/json; '
                       '引擎能力走 api.*)' % name)


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
    之后本模块内任意函数 (restricted_import/sandbox_globals_clean) 均不依赖
    builtins 查找 (定义时已绑定), 仅"模块全局名字查不到会向上找 builtins"
    的语言路径被切断 —— 这正是 V06 的目标。
    """
    _globals().pop('__builtins__', None)
