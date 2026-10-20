# -*- coding: utf-8 -*-
"""loom_net.py — 网络助手（HTTP / HTTPS），纯标准库实现。

供游戏脚本调用外部 API（LLM 服务、游戏服务器等）。
设计原则：
  - 零第三方依赖（urllib + ssl + socket + threading + json）
  - 内置 CA 证书（certifi 的 cacert.pem，见 _cacert.pem 同目录）
  - 支持同步/异步两种调用方式
    - 同步：直接返回结果，会阻塞当前线程（游戏逻辑帧卡顿 1~10s）
    - 异步：后台线程执行，主线程轮询 is_done()/result()，不阻塞逻辑帧
  - 默认 10 秒超时，可配置
  - 响应体最大 10 MB（防止意外大响应耗尽内存）

用法示例（异步，推荐）：
    def on_start(self):
        self._req = None

    def update(self, dt):
        if self._req is None:
            self._req = http_async(
                'POST', 'https://api.openai.com/v1/chat/completions',
                headers={'Authorization': 'Bearer sk-xxx',
                         'Content-Type': 'application/json'},
                body=json.dumps({'model': 'gpt-4', 'messages': [...]}).encode('utf-8'))
        elif self._req.is_done():
            r = self._req.result()
            if r['ok']:
                data = json.loads(r['body'])
                print(data['choices'][0]['message']['content'])
            else:
                print('失败:', r['error'])
            self._req = None

用法示例（同步，简单但会卡帧）：
    r = http_get('https://example.com/api/status')
    if r['ok']:
        print(r['body'])
"""
import json as _json
import os as _os
import socket as _socket
import ssl as _ssl
import threading as _threading
import time as _time
import urllib.error as _urlerr
import urllib.request as _urlreq

# ---- 配置 ----
DEFAULT_TIMEOUT = 10.0           # 秒
DEFAULT_MAX_BYTES = 10 * 1024 * 1024  # 10 MB

# ---- CA 证书 ----
_CA_PATH = _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), '_cacert.pem')


def _make_ssl_context(verify=True):
    """创建 SSL 上下文。verify=True 用内置 CA 证书校验服务器。"""
    if not verify:
        ctx = _ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = _ssl.CERT_NONE
        return ctx
    # 有内置 CA 就用；否则用系统 CA（Windows 可能不全，但有时能工作）
    if _os.path.isfile(_CA_PATH):
        return _ssl.create_default_context(cafile=_CA_PATH)
    return _ssl.create_default_context()


def http_request(method, url, headers=None, body=None,
                 timeout=DEFAULT_TIMEOUT, verify=True,
                 max_bytes=DEFAULT_MAX_BYTES):
    """执行一次 HTTP 请求（同步，阻塞当前线程）。

    返回 dict:
        {'ok': True, 'status': 200, 'headers': {...}, 'body': '<str>', 'bytes': N}
        {'ok': False, 'error': '<msg>', 'status': N 或 None}

    参数:
        method: 'GET' / 'POST' / 'PUT' / 'DELETE' / 'PATCH' / 'HEAD'
        url:    完整 URL（http:// 或 https://）
        headers: dict[str, str]
        body:   bytes 或 str（str 会被 UTF-8 编码）
        timeout: 秒
        verify: True=校验证书（推荐）
        max_bytes: 响应体上限
    """
    if not method or not url:
        return {'ok': False, 'error': 'method 和 url 必填'}
    method = str(method).upper()
    if isinstance(body, str):
        body = body.encode('utf-8')
    headers = dict(headers or {})
    req = _urlreq.Request(url, data=body, method=method, headers=headers)
    # HTTPS 手动构造 opener 以控制 SSL 上下文
    handlers = []
    if url.lower().startswith('https://'):
        try:
            handlers.append(_urlreq.HTTPSHandler(context=_make_ssl_context(verify)))
        except Exception as e:
            return {'ok': False, 'error': 'SSL 上下文失败: %r' % e}
    opener = _urlreq.build_opener(*handlers)
    try:
        with opener.open(req, timeout=float(timeout)) as resp:
            status = resp.status
            resp_headers = dict(resp.headers.items())
            # 分块读取，防止意外大响应
            chunks = []
            total = 0
            while True:
                chunk = resp.read(65536)
                if not chunk:
                    break
                total += len(chunk)
                if total > max_bytes:
                    return {'ok': False, 'status': status,
                            'error': '响应体超过 %d 字节上限' % max_bytes}
                chunks.append(chunk)
            body_bytes = b''.join(chunks)
            # 尝试按 UTF-8 解码（失败则用 latin-1 保底）
            try:
                body_text = body_bytes.decode('utf-8')
            except UnicodeDecodeError:
                body_text = body_bytes.decode('latin-1', 'replace')
            return {'ok': True, 'status': status,
                    'headers': resp_headers,
                    'body': body_text, 'bytes': total}
    except _urlerr.HTTPError as e:
        # HTTP 4xx/5xx：读 body 也返回
        try:
            body_bytes = e.read(max_bytes)
            body_text = body_bytes.decode('utf-8', 'replace')
        except Exception:
            body_text = ''
        return {'ok': False, 'status': e.code,
                'error': 'HTTP %d: %s' % (e.code, e.reason),
                'body': body_text}
    except _urlerr.URLError as e:
        return {'ok': False, 'error': 'URL 错误: %s' % (e.reason,)}
    except _socket.timeout:
        return {'ok': False, 'error': '超时 (%.1fs)' % timeout}
    except Exception as e:
        return {'ok': False, 'error': '%r' % (e,)}


def http_get(url, headers=None, timeout=DEFAULT_TIMEOUT, verify=True):
    """HTTP GET 简写。"""
    return http_request('GET', url, headers=headers,
                        timeout=timeout, verify=verify)


def http_post_json(url, obj, headers=None, timeout=DEFAULT_TIMEOUT, verify=True):
    """HTTP POST JSON 简写。自动 Content-Type: application/json。"""
    h = dict(headers or {})
    h.setdefault('Content-Type', 'application/json; charset=utf-8')
    body = _json.dumps(obj, ensure_ascii=False).encode('utf-8')
    return http_request('POST', url, headers=h, body=body,
                        timeout=timeout, verify=verify)


# ---- 异步封装 ----
class HttpRequestAsync:
    """后台线程执行 HTTP 请求，主线程轮询结果。不阻塞逻辑帧。

    用法:
        req = http_async('GET', 'https://example.com/api')
        # ... 在 update() 里 ...
        if req.is_done():
            r = req.result()  # 返回与 http_request 相同的 dict
            ...
    """

    def __init__(self, method, url, headers=None, body=None,
                 timeout=DEFAULT_TIMEOUT, verify=True):
        self._result = None
        self._done = _threading.Event()
        self._thread = _threading.Thread(
            target=self._run,
            args=(method, url, headers, body, timeout, verify),
            daemon=True, name='loom-net-%s' % method)
        self._thread.start()

    def _run(self, method, url, headers, body, timeout, verify):
        try:
            self._result = http_request(method, url, headers=headers, body=body,
                                        timeout=timeout, verify=verify)
        except Exception as e:
            self._result = {'ok': False, 'error': '%r' % (e,)}
        finally:
            self._done.set()

    def is_done(self):
        """是否已完成（非阻塞）。"""
        return self._done.is_set()

    def result(self, wait=False, timeout=None):
        """获取结果。wait=False 时未完成返回 None；wait=True 时阻塞等待。"""
        if wait:
            self._done.wait(timeout)
        return self._result if self._done.is_set() else None

    def cancel(self):
        """尝试取消（只能让结果被丢弃，不能中断已发的网络请求）。"""
        self._result = {'ok': False, 'error': '已取消'}
        self._done.set()


def http_async(method, url, headers=None, body=None,
               timeout=DEFAULT_TIMEOUT, verify=True):
    """创建异步 HTTP 请求（不阻塞当前线程）。返回 HttpRequestAsync。"""
    return HttpRequestAsync(method, url, headers=headers, body=body,
                            timeout=timeout, verify=verify)
