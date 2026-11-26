# -*- coding: utf-8 -*-
"""eai.service — EAI 服务（端口文件 + HTTP 服务）

我负责：.agent_port.json 端口/令牌文件 (port_file_path / _write_port_file /
load_agent_info)、HTTP 请求处理器 _CmdHandler、服务生命周期 AgentService。
我不负责：命令表与派发（registry.py）、任何具体命令。
"""

import json
import os
import queue
import secrets
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from .registry import _COMMANDS, dispatch, last_log_seq, log, log_since

# ====================================================================
# AGENT 桥: 端口/令牌 + HTTP 服务 (仅 127.0.0.1)
# ====================================================================
def port_file_path(base=None):
    base = base or os.path.dirname(os.path.abspath(sys.argv[0]))
    return os.path.join(base, '.agent_port.json')


def _write_port_file(base, port, token):
    data = {'port': port, 'token': token,
            'pid': os.getpid(),
            'url': 'http://127.0.0.1:%d' % port,
            'started': time.strftime('%Y-%m-%d %H:%M:%S')}
    path = port_file_path(base)
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    return path


class _CmdHandler(BaseHTTPRequestHandler):
    """POST /cmd {cmd,args} / GET /logs?after=N / GET /status / GET /"""
    service = None

    def log_message(self, fmt, *args):      # 静默 request 日志进 LOG_RING
        pass

    def _auth(self):
        """令牌校验 (2026-08-28 二轮中危2): ①hmac.compare_digest 常量时间
        比较 (原 == 存在时序侧信道); ②Host 头只认本机 (防 DNS rebinding/
        恶意网页向 127.0.0.1 发请求携带同 token 的真实场景覆盖率低, 但
        native bind 127.0.0.1 已是主边界, 这里再收一道)."""
        import hmac
        tok = self.headers.get('X-Agent-Token') or ''
        if not hmac.compare_digest(tok.encode('utf-8'),
                                   self.server.service.token.encode('utf-8')):
            return False
        host = (self.headers.get('Host') or '').split(':')[0]
        return host in ('127.0.0.1', 'localhost', '')

    def _json(self, code, obj):
        # 2026-10-19 P0-1 修复: 两层兜底，绝不让编码异常空断连
        #   ① encode('utf-8', 'replace') —— 孤立代理字符替换为 '?'，避免 UnicodeEncodeError
        #   ② 最外层 try/except —— json.dumps 本身失败（循环引用等）时返回最小错误 JSON
        try:
            body = json.dumps(obj, ensure_ascii=False).encode('utf-8', 'replace')
        except Exception as e:
            try:
                err_txt = repr(e).encode('utf-8', 'replace').decode('utf-8', 'replace')
            except Exception:
                err_txt = 'unknown encoding error'
            body = json.dumps({'ok': False, 'error': 'json dump failed',
                               'detail': err_txt}).encode('utf-8', 'replace')
        self.send_response(code)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        # 2026-10-19 P0-1 修复: 外层兜底，任何路径异常都返回 500 JSON，绝不空断连
        try:
            if not self._auth():
                return self._json(401, {'ok': False, 'error': 'bad token'})
            if self.path.startswith('/logs'):
                after = 0
                if 'after=' in self.path:
                    try:
                        after = int(self.path.split('after=')[1].split('&')[0])
                    except Exception:
                        after = 0
                return self._json(200, {'ok': True, 'seq': last_log_seq(),
                                        'lines': log_since(after)})
            if self.path.startswith('/status'):
                # self.service 是类属性 None (handler 实例上没有), 服务实例只在
                # self.server.service —— 曾写成 self.service.started 直接 500.
                return self._json(200, {'ok': True, 'pid': os.getpid(),
                                        'alive': self.server.service.started})
            return self._json(200, {'ok': True, 'service': 'loom-agent',
                                    'commands': list(_COMMANDS)})
        except Exception as e:
            try:
                self._json(500, {'ok': False, 'error': 'do_GET crashed',
                                 'detail': repr(e)[:300]})
            except Exception:
                pass

    def do_POST(self):
        # 2026-10-19 P0-1 修复: 外层兜底，命令执行后若 _json 抛异常，客户端至少
        # 能收到 500 JSON（带"可能已执行"提示），避免误判失败后重试重复操作。
        try:
            if not self._auth():
                return self._json(401, {'ok': False, 'error': 'bad token'})
            if not self.path.startswith('/cmd'):
                return self._json(404, {'ok': False, 'error': 'not found'})
            try:
                req = json.loads(self.rfile.read(
                    int(self.headers.get('Content-Length', 0)) or 0)
                    .decode('utf-8'))
            except Exception as e:
                return self._json(400, {'ok': False, 'error': repr(e)})
            cmd, args = req.get('cmd'), req.get('args') or {}
            result = self.server.service.submit(cmd, args)
            self._json(200, result)
        except Exception as e:
            try:
                self._json(500, {'ok': False,
                                 'error': 'do_POST crashed (可能已执行, 勿盲目重试)',
                                 'detail': repr(e)[:300]})
            except Exception:
                pass


def _env_float(name, default):
    """环境变量 -> 非负浮点 (缺省/坏值/负数回 default)."""
    try:
        v = float(os.environ.get(name, default))
    except (TypeError, ValueError):
        return float(default)
    if v != v or v < 0:        # NaN / 负数
        return float(default)
    return v


class AgentService:
    """EAI 服务: 命令队列 -> Qt 主线程执行 (qt_view QTimer 轮询 drain).

    2026-11-07 A/E (用户裁决 B): 逐条执行 + 节奏 + 步进模式.
      · drain() 每拍**最多执行 1 条**; 距上次执行不足 pace_ms 直接返回
        (QTimer 4ms 会持续触发, 节奏由时间戳判, 不靠定时器精度);
      · LOOM_AGENT_PACE_MS=0 -> 一次排空 (旧行为, 批量脚本用);
      · GUI 钩子 (getattr 缺失即跳过, 绝不因 UI 未实现而崩命令链):
          win._agent_progress(cmd, args, done, total)
          win._agent_busy(active)
          win._agent_after_command()
    """

    def __init__(self, win, base=None):
        self.win = win
        self.base = base or os.path.dirname(os.path.abspath(sys.argv[0]))
        self.token = secrets.token_hex(16)
        self.queue = queue.Queue()
        self.server = None
        self.thread = None
        self.started = False
        self.port = 0
        # ---- 节奏/步进/进度 (契约见 docs/audit/fix_agent_visual_*.md) ----
        self.pace_ms = _env_float('LOOM_AGENT_PACE_MS', 120.0)
        self._last_run = None       # 上次执行完成的 perf_counter (None=从未执行)
        self._busy = False          # GUI 忙态 (队列空转非空 -> True; 空闲 0.8s -> False)
        self._run_done = 0          # 本轮已执行条数
        self._inflight = None       # 正在执行的 (cmd, args) 或 None
        self._last_info = ('', False, 0.0)
        self._draining = False
        self._idle_release_s = 0.8
        # 批次租约可视化 (2026-11-08 批4 / D10): 上次推给 GUI 的剩余秒数,
        # 用于"每秒只变一次"的节流; 'init' = 尚未同步过。
        self._batch_secs = 'init'

    def start(self):
        """启动 HTTP 服务 + 写端口文件 (Qt 事件循环前调用).
        serve_forever 线程异常会记录到日志并打印 (进程死不了,
        socket 释放; 此信息用于排查 "端口文件在但连不上")."""
        self.server = ThreadingHTTPServer(('127.0.0.1', 0), _CmdHandler)
        self.server.service = self

        def _serve():
            try:
                self.server.serve_forever(poll_interval=0.1)
            except Exception as e:          # noqa: 调试可见
                print('[agent] serve_forever 线程退出: %r' % e, flush=True)
                log('[agent] serve_forever 线程退出: %r' % e)
        self.thread = threading.Thread(target=_serve, daemon=True)
        self.thread.start()
        self.started = True
        self.port = self.server.server_address[1]
        _write_port_file(self.base, self.port, self.token)
        print('[agent] EAI serving on http://127.0.0.1:%d (pid=%d)'
              % (self.port, os.getpid()), flush=True)
        log('[agent] EAI 启动: http://127.0.0.1:%d' % self.port)
        # 2026-08-28 二轮(中危2): 不再打印 token 任何片段 (启动日志泄露面)
        return self.port

    def submit(self, cmd, args):
        """HTTP 线程调用: 入队 + 等主线程执行结果 (超时 30s)."""
        ev = threading.Event()
        self.queue.put((cmd, args, ev))
        if not ev.wait(30.0):
            return {'ok': False, 'error': '命令超时 (30s): %s' % cmd}
        return ev.result

    # ---- GUI 钩子 (缺失/异常一律跳过: UI 未实现时命令链必须照常跑) ----
    def _hook(self, name, *a):
        fn = getattr(self.win, name, None)
        if fn is None:
            return
        try:
            fn(*a)
        except Exception as e:
            log('[agent] GUI 钩子 %s 失败: %r' % (name, e))

    def _set_busy(self, active):
        """忙态切换 (只在状态真变时通知 GUI, 避免 4ms 定时器刷爆状态栏)."""
        if self._busy == active:
            return
        self._busy = active
        if active:
            self._run_done = 0      # 新一轮开始: 进度从 0 计
        self._hook('_agent_busy', active)

    def _update_busy(self, now, has_work):
        """队列空转非空 -> busy True; 队列空且距上次执行 >= 0.8s -> busy False."""
        if has_work:
            if not self._busy:
                self._set_busy(True)
            return
        if (self._busy and self._last_run is not None
                and (now - self._last_run) >= self._idle_release_s):
            self._set_busy(False)
            self._run_done = 0

    def _notify_progress(self, cmd, args):
        """每条命令执行后回调进度 (done = 本轮已执行, total = done + 队列剩余)."""
        total = self._run_done + self.queue.qsize()
        self._hook('_agent_progress', cmd, args, self._run_done, total)

    def _undo_of_editor(self):
        """取编辑器上的 UndoManager (没有就是 None; 桩/无头路径照常跑)."""
        ed = getattr(self.win, 'editor', None)
        return getattr(ed, 'undo', None) if ed is not None else None

    def _tick_batch(self):
        """练约维护 (D10=A): 到点自动 end_batch (历史保留) + 状态栏剩余秒数 (D10=可视化).

        2026-11-08 批4: 4ms QTimer 每拍调一次 —— 只有剩余秒数变化才通知 GUI,
        避免刷爆状态栏；收口时写一条日志, 便于事后核查"这批为何变成一步"。
        """
        um = self._undo_of_editor()
        if um is None or not hasattr(um, 'tick_batch'):
            return
        try:
            closed = um.tick_batch()
            if closed is not None:
                log('[agent] 批次租约到期, 已自动收口为一步 (%d 条命令)'
                    % len(getattr(closed, 'cmds', ()) or ()))
            rem = um.batch_remaining()
            if rem is None:
                secs = None
            else:
                secs = int(rem) + (1 if rem > int(rem) else 0)
            if secs != self._batch_secs:
                self._batch_secs = secs
                self._hook('_agent_batch_status', secs)
        except Exception as e:
            log('[agent] 批次租约维护失败: %r' % (e,))

    def _run_one(self):
        """出队并执行 1 条, 回填结果. 返回执行条数 (0/1)."""
        try:
            cmd, args, ev = self.queue.get_nowait()
        except queue.Empty:
            return 0
        self._inflight = (cmd, args)
        t0 = time.perf_counter()
        try:
            res = dispatch(cmd, args, self.win)
        except Exception as e:          # dispatch 已兜底; 这里再兜一层防 ev 永挂
            res = {'ok': False, 'error': repr(e)}
        finally:
            # "Agent 命令作用域"由 dispatch 统一标记 (见其 docstring):
            # 一条 EAI 命令 = 一个 Agent 命令单位, 与调用来源 (HTTP/控制台/直调) 无关。
            self._inflight = None
        ms = (time.perf_counter() - t0) * 1000.0
        self._last_run = time.perf_counter()
        ev.result = res
        ev.set()
        self._run_done += 1
        self._last_info = (cmd, bool(res.get('ok')), ms)
        self._notify_progress(cmd, args)
        self._hook('_agent_after_command')
        return 1

    def drain(self):
        """Qt 主线程轮询 (QTimer 4ms): 按节奏执行命令, 回填结果.

        返回本拍实际执行的条数 (观测/测试用).
          · 队列空 -> 只做忙态释放, 返回;
          · 距上次执行不足 pace_ms -> 直接返回 (等下一次 4ms 触发);
          · pace_ms > 0: 每拍最多 1 条; pace_ms == 0: 一次排空 (旧行为).
        """
        now = time.perf_counter()
        self._update_busy(now, (not self.queue.empty())
                          or (self._inflight is not None))
        # 2026-11-08 批4 (D10=A): 批次租约维护必须在"队列空早退"之前 —— 悬挂批
        # 往往正是"队列已空、客户端已断"的状态, 只有这里还在按拍跑。
        self._tick_batch()
        if self.queue.empty():
            return 0
        if self._draining:              # GUI 钩子里重入的兜底
            return 0
        self._draining = True
        n = 0
        try:
            while True:
                if self.queue.empty():
                    break
                if (self.pace_ms > 0 and self._last_run is not None
                        and (time.perf_counter() - self._last_run) * 1000.0
                        < self.pace_ms):
                    break
                n += self._run_one()
                if self.pace_ms > 0:
                    break                   # 有节奏: 本拍只放一条
                # pace_ms == 0: 继续排空 (向后兼容批量脚本)
        finally:
            self._draining = False
        # 排空/暂停后按最新时间戳释放忙态 (最后一条执行完的时刻)
        self._update_busy(time.perf_counter(),
                          (not self.queue.empty())
                          or (self._inflight is not None))
        return n

    def progress(self):
        """(done, total): total = 本轮已执行 + 队列剩余 (+ 在途 1 条).
        队列空且无在途时归零."""
        q = self.queue.qsize()
        if q == 0 and self._inflight is None:
            self._run_done = 0
            return (0, 0)
        total = self._run_done + q + (1 if self._inflight is not None else 0)
        return (self._run_done, total)

    def last_info(self):
        """最后一条命令 (cmd, ok, ms)."""
        return self._last_info

    def stop(self):
        self.started = False
        if self.server:
            self.server.shutdown()
        try:
            os.remove(port_file_path(self.base))
        except Exception:
            pass
        self._set_busy(False)           # 关服务后 GUI 忙态红点必须熄掉


def load_agent_info(base=None):
    """Agent 侧: 读端口文件 -> (port, token, url, pid) 或 None."""
    path = port_file_path(base)
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return None
