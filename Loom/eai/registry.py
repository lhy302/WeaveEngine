# -*- coding: utf-8 -*-
"""eai.registry — 命令注册表与派发

我负责：命令表 _COMMANDS / _CMDS_DESC、@command 注册装饰器、dispatch 派发、
命令作用域栈 (_CommandScope / current_scope) 与统一日志环 (LOG_RING / log)。
我不负责：任何具体命令的实现（按域在 cmd_*_ops.py / inspector.py 等）。
"""

import threading
import time
from collections import deque
from .commit import _Ambiguous
from .undo_base import _undo_manager

LOG_RING = deque(maxlen=2000)
_LOG_SEQ = 0
_LOG_LOCK = threading.Lock()

_COMMANDS = {}           # 命令名 -> fn(win, args) -> dict/值
_CMDS_DESC = {}          # 命令名 -> 用途说明 (GUI 控制台提示)


# ---- 命令作用域 (Q-B7-56-1 裁定①/D10=A, 2026-11-22) ----
# 'agent' = EAI 命令行语义 (F12 控制台 / 远程 HTTP / MCP): dispatch 缺省, 执行期
#           打 Agent 命令作用域 (批内写命令可被吸进批, D10=A/B 现状不变);
# 'user'  = GUI 点击翻译的命令 (gui/main_window._invoke_cmd): 用户编辑 —— 进撤销
#           栈, 但**不进** agent 批作用域 (不 agent_command_begin, 不续租)。
# 线程约定: 命令只跑在 Qt 主线程 (HTTP 队列经 QTimer drain 回主线程执行), 栈式
# 嵌套 (dispatch/命令壳各自 push/pop) 在该约定下安全。
class _CommandScope:
    """命令作用域栈 ('agent' | 'user'), dispatch / GUI 命令壳 push, cmd_* 经
    current_scope() 读取 (按需区分, 如写白名单对人类对话框授权的放行)。"""

    def __init__(self):
        self._stack = ['agent']

    def push(self, scope):
        self._stack.append(scope if scope in ('agent', 'user') else 'agent')

    def pop(self):
        if len(self._stack) > 1:
            self._stack.pop()

    @property
    def current(self):
        return self._stack[-1]


_CMD_SCOPE = _CommandScope()


def current_scope():
    """当前命令作用域 ('agent'|'user') — cmd_* 内部按需区分。"""
    return _CMD_SCOPE.current


def log(msg):
    """统一调试日志环 (命令/错误/事件; GUI 控制台与 Agent /logs 共用).

    2026-10-19 P0-1 修复: str(msg) 强制 utf-8 'replace' 往返一次，清洗孤立代理字符
    (Windows surrogateescape 残留会导致后续 /logs 的 json.dumps().encode('utf-8')
    抛 UnicodeEncodeError -> 空断连 -> Agent 看不到日志且重试会重复执行命令).
    """
    global _LOG_SEQ
    s = str(msg)
    try:
        s.encode('utf-8')
    except UnicodeEncodeError:
        s = s.encode('utf-8', 'replace').decode('utf-8', 'replace')
    with _LOG_LOCK:
        _LOG_SEQ += 1
        seq = _LOG_SEQ
        LOG_RING.append((seq, time.strftime('%H:%M:%S'), s))
    return seq


def log_since(after):
    """since seq 之后的日志行 [(seq, time, text)...]."""
    with _LOG_LOCK:
        return [r for r in LOG_RING if r[0] > after]


def last_log_seq():
    """当前日志序号 (GUI 控制台挂载时取基线, 之后只拉增量; 远程用 /logs?after)."""
    with _LOG_LOCK:
        return _LOG_SEQ


def command(name, desc=""):
    """命令注册装饰器: @command('play', '播放/停止播放')"""
    def deco(fn):
        _COMMANDS[name] = fn
        _CMDS_DESC[name] = desc
        return fn
    return deco


def command_names():
    return {k: _CMDS_DESC.get(k, '') for k in _COMMANDS}


def dispatch(cmd, args, win, scope='agent'):
    """执行一条命令 (win=LoomGUI 或桩). 返回 {"ok":..., "result"/"error"}.
    命令报错不会崩编辑器: 记录日志并返回错误.

    2026-11-08 批4 (裁决 D10=A): **一条 EAI 命令 = 一个 Agent 命令单位** ——
    这里给 UndoManager 打上 "agent 命令作用域", 让批次只吸 EAI 命令产生的写命令。
    用户在检查器/gizmo/层级面板上的编辑不走 dispatch, 因此仍是"用户编辑":
    不进批、不续租 (批内 undo 时会被 D10=B 拒绝, 历史不丢)。

    2026-11-22 (Q-B7-56-1 裁定①): 增 scope 参数 —— 'agent' (缺省, 兼容现状) =
    EAI 命令行路径 (控制台 F12 / 远程 HTTP / MCP), 执行期打 agent 命令作用域
    (D10 批语义现状不变); 'user' = GUI 点击翻译路径, **不打** agent 作用域
    (GUI 翻译的命令 = 用户编辑, 只进撤销栈不进批)。GUI 命令壳
    main_window._invoke_cmd 直调命令函数并自带 user 作用域包裹, 不经 dispatch;
    本参数供测试与未来调用方显式表达路径。
    """
    fn = _COMMANDS.get(cmd)
    if fn is None:
        return {'ok': False, 'error': '未知命令: %s (可用: %s)'
                % (cmd, ' '.join(sorted(_COMMANDS)))}
    _um, _ = _undo_manager(win)
    if scope == 'agent' and _um is not None and hasattr(_um, 'agent_command_begin'):
        _um.agent_command_begin()
    else:
        _um = None
    _CMD_SCOPE.push(scope)
    try:
        t0 = time.perf_counter()
        result = fn(win, args or {})
        ms = (time.perf_counter() - t0) * 1000
        # 契约统一 (2026-08-27): 命令用 {'error': ...} 表达"参数/前置条件不对"
        # 时, 外层也必须 ok=False —— 否则 Agent 看到 ok=true 就当成功了,
        # 错误藏在 result 里没人看 (远程 HTTP 与 GUI 控制台同此语义).
        if isinstance(result, dict) and result.get('error'):
            log('[命令] %s %s -> 拒绝: %s' % (cmd, args or '', result['error']))
            return {'ok': False, 'error': result['error'], 'result': result}
        log('[命令] %s %s -> ok (%.1fms)' % (cmd, args or '', ms))
        return {'ok': True, 'result': result}
    except _Ambiguous as e:
        # 重名歧义 = 输入问题, 不是崩溃: 拒绝但给出 index= 提示
        log('[命令] %s %s -> 重名歧义: %s' % (cmd, args or '', e))
        return {'ok': False, 'error': str(e)}
    except Exception as e:
        log('[命令] %s 失败: %r' % (cmd, e))
        return {'ok': False, 'error': repr(e)}
    finally:
        _CMD_SCOPE.pop()
        if _um is not None:
            try:
                _um.agent_command_end()
            except Exception:
                pass
