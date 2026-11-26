# -*- coding: utf-8 -*-
"""eai.http_ops — HTTP 命令

我负责：http_get / http_post_json / http_request（Agent 出网工具命令）。
我不负责：EAI 自身的 HTTP 服务面（service.py）。
"""

from .helpers import as_float
from .registry import command

# ====================================================================
# 2026-10-20 网络助手命令（供 Agent/MCP 直接调 HTTP API）
# 底层复用 net/net.py（纯标准库），与游戏脚本共用同一套实现。
# ====================================================================
@command('http_get', 'HTTP GET: {url, headers?, timeout?} 返回 {ok,status,body,error}')
def cmd_http_get(win, args):
    url = args.get('url')
    if not url:
        return {'error': '需要 url'}
    from net.net import http_get
    timeout = as_float(args.get('timeout'), 10.0)
    return http_get(url, headers=args.get('headers'),
                             timeout=max(1.0, min(60.0, timeout)))


@command('http_post_json', 'HTTP POST JSON: {url, body, headers?, timeout?}')
def cmd_http_post_json(win, args):
    url = args.get('url')
    if not url:
        return {'error': '需要 url'}
    body = args.get('body')
    if body is None:
        return {'error': '需要 body (JSON 对象)'}
    from net.net import http_post_json
    timeout = as_float(args.get('timeout'), 10.0)
    return http_post_json(url, body, headers=args.get('headers'),
                                   timeout=max(1.0, min(60.0, timeout)))


@command('http_request', '通用 HTTP: {method, url, headers?, body?, timeout?}')
def cmd_http_request(win, args):
    method = args.get('method')
    url = args.get('url')
    if not method or not url:
        return {'error': '需要 method 和 url'}
    from net.net import http_request
    timeout = as_float(args.get('timeout'), 10.0)
    return http_request(method, url,
                                 headers=args.get('headers'),
                                 body=args.get('body'),
                                 timeout=max(1.0, min(60.0, timeout)))
