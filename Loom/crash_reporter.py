# -*- coding: utf-8 -*-
"""crash_reporter.py — Loom 崩溃落盘 (dbghelp Minidump + 场景自动备份)

DLL 化战役 M1 三闸之一 (总纲: D:\\my-project\\DLL化改造可行性方案与执行路径
报告.txt v1.3 §六 M1)。坏注入 DLL 崩溃后必须"崩了能查" — .dmp 自动落盘 +
场景自动备份, 把"复现崩溃"的时间省下来。

设计理由 (为什么这么做):
1. 为什么不用 Breakpad: Breakpad 面向无源码大规模发行场景 (符号上传/
   独立守护进程/自绘 DWARF 解析)。本引擎单机开发 + MSVC 工具链在场,
   dbghelp 的 MiniDumpWriteDump 一次 ctypes 调用即可, 少一个 C++ 依赖
   少一类编译坑 (报告 v1.1 定案: 不上 Breakpad)。
2. 崩溃回调里为什么不做复杂事: SetUnhandledExceptionFilter 回调执行在
   进程已发生访问违例之后, 进程状态不可信 — 回调里再崩 = 死循环或静默
   失联。所以回调只做两件事: ① 调场景备份闭包 (全包 try/except, 备份
   失败绝不阻断 dump) ② 写 .dmp; 然后立即返回 EXCEPTION_EXECUTE_HANDLER
   让进程退出。善后 (弹出坏 DLL / 提示重启) 由基座下次启动负责 — 崩溃
   现场只负责留证据。
3. 手动 API 与进程级 filter 的分工: ctypes 调 DLL 内部访问违例时, ctypes
   的 SEH 包裹会把 0xC0000005 转成 Python OSError 抛上来 — 这种异常已被
   "处理", 走不到 unhandled filter。所以引擎 try/except 捕到 OSError 后
   必须主动调 write_dump() 落盘, 再走"弹出坏 DLL → 回退官方 DLL"流程
   (v1.3)。进程级 filter 只兜真正的漏网之鱼 (C 扩展深层崩/解释器野指针)。
   两条路收敛到同一个 _do_dump()。

用法 (引擎启动期, Loom.py 早期接线, 本模块不自行 import 引擎任何件):
    import crash_reporter
    crash_reporter.register_scene_backup(备份闭包)   # 可选; fn(reason)->None
    crash_reporter.install()

逃生门: LOOM_NO_CRASHDUMP=1 → 不安装不落盘 (LOOM_NO_* 逃生门族惯例)。
限流: write_dump 同一分钟最多落 2 个 (防连环崩溃刷盘); filter 路径不限流
(真崩溃每进程至多触发一次 filter, 返回即进程退出)。
"""
import os
import sys
import time
import threading

try:
    import ctypes
    from ctypes import wintypes
except ImportError:              # 理论不可达 (CPython 必带 ctypes); 防御保留
    ctypes = None

_DUMP_DIRNAME = '崩溃日志'       # 落点: 引擎根\崩溃日志 (源码版=本文件所在目录)
_MAX_DUMPS_PER_MINUTE = 2        # write_dump 限流: 同一分钟最多 2 个

# MiniDump 级别 = MiniDumpNormal(0x0) | MiniDumpWithHandleData(0x4):
# 含全部线程栈 + 句柄表。不上 MiniDumpWithFullMemory(0x2) — 500 物体场景
# 进程内存数百 MB, 全内存 dump 单文件数百 MB 落盘数十秒, 体积/速度失衡;
# Normal+HandleData 配合同版本 PDB 已可在 WinDbg/VS 定位访问违例点。
_MINIDUMP_TYPE = 0x00000004

# filter 返回值: 按已处理收尾, 进程以异常码退出 (不走 WER 弹框)
_EXCEPTION_EXECUTE_HANDLER = 1

# ---------------------------------------------------------------------------
# 模块级单例状态 (dict 而非裸全局: 与 fastpath._CK 同理 — 容器内容防
# Nuitka 编译期常量折叠, 运行时键访问真实发生)
# ---------------------------------------------------------------------------
_ST = {
    'installed': False,
    'filter_ref': None,        # ★必须持全局引用: ctypes 回调被 GC = 二次崩
    'backup_fn': None,         # 场景备份闭包 fn(reason)->None
    'lock': threading.Lock(),  # 只护 write_dump 手动路径; filter 路径不碰锁
                               # (崩溃时锁可能被别的线程持有 → 死等=失联)
    'minute_slot': None,       # int(time.time() // 60) — 限流时间片
    'minute_count': 0,         # 当前时间片已成功落盘次数
}

if ctypes is not None:
    class _MINIDUMP_EXCEPTION_INFORMATION(ctypes.Structure):
        """MINIDUMP_EXCEPTION_INFORMATION { DWORD ThreadId;
        PEXCEPTION_POINTERS ExceptionPointers; BOOL ClientPointers; }"""
        _fields_ = [('ThreadId', wintypes.DWORD),
                    ('ExceptionPointers', ctypes.c_void_p),
                    ('ClientPointers', wintypes.BOOL)]

    # filter 回调签名: LONG WINAPI TopLevelFilter(PEXCEPTION_POINTERS)
    _UNHANDLED_FILTER_TYPE = ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_void_p)

# ---------------------------------------------------------------------------
# dbghelp / kernel32 绑定 (import 期绑定失败 = dbghelp 不可用 → 静默降级,
# 引擎绝不能因落盘组件起不来)
# ---------------------------------------------------------------------------
if ctypes is not None:
    try:
        _k32 = ctypes.WinDLL('kernel32', use_last_error=True)
        _k32.GetCurrentProcess.restype = wintypes.HANDLE
        _k32.GetCurrentProcess.argtypes = []
        _k32.GetCurrentProcessId.restype = wintypes.DWORD
        _k32.GetCurrentProcessId.argtypes = []
        _k32.GetCurrentThreadId.restype = wintypes.DWORD
        _k32.GetCurrentThreadId.argtypes = []
        _k32.CreateFileW.restype = wintypes.HANDLE
        _k32.CreateFileW.argtypes = [
            wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, wintypes.LPVOID,
            wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
        _k32.CloseHandle.restype = wintypes.BOOL
        _k32.CloseHandle.argtypes = [wintypes.HANDLE]
        # SetUnhandledExceptionFilter 不定 argtypes: 默认转换会把 _CFuncPtr
        # 实例按其函数地址传 (与官方文档 qsort/CMPFUNC 示例同款)

        _dbghelp = ctypes.WinDLL('dbghelp', use_last_error=True)
        # BOOL MiniDumpWriteDump(HANDLE hProcess, DWORD ProcessId,
        #     HANDLE hFile, MINIDUMP_TYPE,
        #     PMINIDUMP_EXCEPTION_INFORMATION,      ← 崩溃上下文 (可 NULL)
        #     PMINIDUMP_USER_STREAM_INFORMATION,    ← 不用 (NULL)
        #     PMINIDUMP_CALLBACK_INFORMATION)       ← 不用 (NULL)
        _dbghelp.MiniDumpWriteDump.restype = wintypes.BOOL
        _dbghelp.MiniDumpWriteDump.argtypes = [
            wintypes.HANDLE, wintypes.DWORD, wintypes.HANDLE, wintypes.ULONG,
            ctypes.POINTER(_MINIDUMP_EXCEPTION_INFORMATION),
            ctypes.c_void_p, ctypes.c_void_p]
        _DBGHELP_OK = True
    except Exception:
        _DBGHELP_OK = False
else:
    _DBGHELP_OK = False

_INVALID_HANDLE = wintypes.HANDLE(-1).value   # INVALID_HANDLE_VALUE (64 位)


def _say(msg):
    """落盘日志输出: 只进 stderr, 自身全包 try/except (绝不二次抛)。"""
    try:
        print('[crash_reporter] ' + msg, file=sys.stderr)
        sys.stderr.flush()
    except Exception:
        pass


def register_scene_backup(fn):
    """注册"崩溃时把当前场景存到备份文件"的闭包 fn(reason:str)->None。

    引擎侧闭包自定备份文件名/目录 (建议带时间戳, 存保存目录旁); 本模块
    已全包 try/except, 备份失败不会阻断 dump, 但闭包自身也应尽量健壮
    (不要在闭包里再引任何 DLL — 崩的就是它)。"""
    _ST['backup_fn'] = fn


def _do_dump(exc_ptrs, reason):
    """核心落盘: 写一个 .dmp; 返回路径, 失败返回 None (绝不抛异常)。"""
    try:
        # 引擎根 = 本文件所在目录; 冻结环境 __file__ 在 dist 内, dump 落
        # exe 同级崩溃日志 (assemble 投放保持相对布局, 口径一致)
        base = os.path.dirname(os.path.abspath(__file__))
        d = os.path.join(base, _DUMP_DIRNAME)
        os.makedirs(d, exist_ok=True)
        ts = time.strftime('%Y%m%d_%H%M%S')
        pid = os.getpid()
        path = os.path.join(d, 'crash_%s_pid%d.dmp' % (ts, pid))
        k = 2
        while os.path.exists(path):   # 同秒同名 (限流窗口/连崩): 追加序号
            path = os.path.join(d, 'crash_%s_pid%d_%d.dmp' % (ts, pid, k))
            k += 1
        # 0x40000000=GENERIC_WRITE, share=0, 2=CREATE_ALWAYS, 0x80=NORMAL
        hfile = _k32.CreateFileW(path, 0x40000000, 0, None, 2, 0x80, None)
        if hfile is None or hfile == _INVALID_HANDLE or not hfile:
            _say('dump 创建文件失败: %s (err=%d)' % (path, ctypes.get_last_error()))
            return None
        try:
            mei = None
            if exc_ptrs:
                # filter 路径: 直传 SEH 给的 EXCEPTION_POINTERS 指针,
                # dump 里带崩溃线程上下文 (WinDbg 里能看到违例点寄存器)
                mei = _MINIDUMP_EXCEPTION_INFORMATION(
                    ThreadId=_k32.GetCurrentThreadId(),
                    ExceptionPointers=exc_ptrs,
                    ClientPointers=False)          # 指针属于本进程
            # ★MiniDumpNormal(0x0)|WithHandleData(0x4) 在 unhandled filter
            #  上下文 (进程已损坏状态) 下被内部校验拒绝 (0x800703E6
            #  ERROR_NOACCESS, 实测 2026-09-08): 损坏进程里走 SuspendThread
            #  之外路径会失败。对策: 崩溃上下文加 MiniDumpWithIndirectly
            #  ReferencedMemory (0x40) — 仍远小于 FullMemory 但实测通过;
            #  手动路径 (进程健康) 保持原级别。
            dump_type = _MINIDUMP_TYPE if not exc_ptrs else (_MINIDUMP_TYPE | 0x40)
            ok = _dbghelp.MiniDumpWriteDump(
                _k32.GetCurrentProcess(), pid, hfile, dump_type,
                mei if mei is not None else None, None, None)
            if not ok:
                # 崩溃上下文首选拒 (0x800703E6) → 降级重试: 裸 Normal (0x0)
                # 不要 SEH 上下文, 只保证栈可查 — 崩溃时留证据 > 证据完美
                _say('MiniDumpWriteDump 首选失败 (err=%d), 降级重试裸 Normal: %s'
                     % (ctypes.get_last_error(), path))
                ok = _dbghelp.MiniDumpWriteDump(
                    _k32.GetCurrentProcess(), pid, hfile, 0x0, None, None, None)
            if not ok:
                _say('MiniDumpWriteDump 降级仍失败 (err=%d): %s'
                     % (ctypes.get_last_error(), path))
                return None
            return path
        finally:
            _k32.CloseHandle(hfile)
    except Exception as e:
        _say('dump 写入异常 (静默降级): %r' % (e,))
        return None


def _touch_backup(reason):
    """调场景备份闭包, 全包 try/except — 备份失败绝不阻断/绝不抛。"""
    fn = _ST['backup_fn']
    if fn is None:
        return
    try:
        fn(reason)
    except Exception as e:
        _say('场景备份回调失败 (不阻断 dump): %r' % (e,))


def _rate_ok():
    """限流: 同一分钟最多 _MAX_DUMPS_PER_MINUTE 个。调用方必须持锁。"""
    now = int(time.time() // 60)
    if _ST['minute_slot'] != now:
        _ST['minute_slot'] = now
        _ST['minute_count'] = 0
    if _ST['minute_count'] >= _MAX_DUMPS_PER_MINUTE:
        return False
    _ST['minute_count'] += 1
    return True


def write_dump(reason='unspecified'):
    """手动落盘 API — ctypes 访问违例场景专用。

    ctypes 把 DLL 内 0xC0000005 转成 OSError 抛给 Python 层 (已被"处理",
    走不到 unhandled filter)。引擎 try/except 捕到 OSError 后调本 API
    落盘, 然后走"弹出坏 DLL → 回退官方 DLL"流程 (v1.3)。
    限流: 同一分钟最多 2 个。返回落盘路径; 限流/失败返回 None — 绝不抛
    异常 (落盘失败不能把一次崩溃升级成二次崩溃)。"""
    if not _DBGHELP_OK:
        _say('dbghelp 不可用, 跳过 dump (%s)' % (reason,))
        return None
    with _ST['lock']:
        if not _rate_ok():
            _say('限流: 本分钟已落 %d 个, 跳过 (%s)'
                 % (_MAX_DUMPS_PER_MINUTE, reason))
            return None
        # 手动路径无 SEH 上下文 (OSError 已脱离异常点), ExceptionParam=NULL
        path = _do_dump(None, reason)
    if path:
        _say('dump 已落盘: %s (%s)' % (path, reason))
        _touch_backup(reason)
    return path


def _filter_proc(exc_ptrs):
    """进程级 unhandled exception filter (C 层直调)。

    只做两件事: 备份回调 + dump, 每一步全包吞异常; 返回 EXECUTE_HANDLER
    让进程退出 (设计理由见模块 docstring 第 2 条)。不碰 _ST['lock']
    (崩溃时锁可能被别的线程持有 → 死等); 不限流 (filter 每进程至多触发
    一次, 返回即进程退出)。"""
    try:
        fn = _ST['backup_fn']
        if fn is not None:
            try:
                fn('unhandled-exception')
            except Exception:
                pass
        path = _do_dump(exc_ptrs, 'unhandled-exception')
        if path:
            _say('崩溃 dump 已落盘: %s' % (path,))
    except Exception:
        pass
    return _EXCEPTION_EXECUTE_HANDLER


def install():
    """安装进程级 unhandled exception filter。幂等; 返回是否已安装。

    LOOM_NO_CRASHDUMP=1 → 直接不装 (逃生门); dbghelp 绑定失败 → 静默
    降级不装 (引擎不受影响)。手动 write_dump 不依赖 install, 永远可用
    (dbghelp 可用时)。"""
    if _ST['installed']:
        return True
    if os.environ.get('LOOM_NO_CRASHDUMP') == '1':
        _say('LOOM_NO_CRASHDUMP=1, 崩溃落盘未安装 (逃生门)')
        return False
    if not _DBGHELP_OK:
        _say('dbghelp 绑定失败, 崩溃落盘未安装 (静默降级, 引擎不受影响)')
        return False
    try:
        ref = _UNHANDLED_FILTER_TYPE(_filter_proc)
        _k32.SetUnhandledExceptionFilter(ref)   # 旧 filter 不保留: 本引擎
                                                # 是唯一持有方, 覆盖即可
        _ST['filter_ref'] = ref                 # ★全局持引用防 GC (见 _ST)
        _ST['installed'] = True
        return True
    except Exception as e:
        _say('filter 安装失败 (静默降级): %r' % (e,))
        return False
