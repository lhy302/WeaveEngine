# -*- coding: utf-8 -*-
"""smoke_net_capability.py — 网络能力冒烟 (2026-10-20 新增)

覆盖:
  A) loom_net 模块可导入，内置 CA 证书存在
  B) 同步 http_get 可用（本地 HTTP 服务器）
  C) 同步 http_post_json 可用
  D) 异步 http_async 可用（is_done 轮询）
  E) Script 基类有 http_get/http_post_json/http_async 方法
  F) EAI 命令有 http_get/http_post_json/http_request
  G) MCP 工具有 loom_http_get/loom_http_post_json/loom_http_request
"""
import io, os, sys, threading, time
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

HERE = os.path.dirname(os.path.abspath(__file__))
BASE = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, BASE)
os.chdir(BASE)

fails = []
def check(label, cond, detail=''):
    msg = ('PASS ' if cond else 'FAIL ') + label
    if detail:
        msg += '  ' + str(detail)
    print(msg)
    if not cond:
        fails.append(label)


# ============ 启动本地测试 HTTP 服务器 ============
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json

class _TestHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        body = json.dumps({'path': self.path, 'method': 'GET',
                           'headers': dict(self.headers.items())}).encode('utf-8')
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)
    def do_POST(self):
        n = int(self.headers.get('Content-Length', 0) or 0)
        data = self.rfile.read(n).decode('utf-8', 'replace')
        body = json.dumps({'path': self.path, 'method': 'POST',
                           'body': data,
                           'headers': dict(self.headers.items())}).encode('utf-8')
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)
    def log_message(self, *a, **k):
        pass  # 静默

srv = ThreadingHTTPServer(('127.0.0.1', 0), _TestHandler)
port = srv.server_address[1]
srv_thread = threading.Thread(target=srv.serve_forever, daemon=True)
srv_thread.start()
BASE_URL = 'http://127.0.0.1:%d' % port
print('本地测试服务器: %s' % BASE_URL)
print()


# ============ A) loom_net 模块 + CA 证书 ============
try:
    import loom_net
    check('A1) loom_net 可 import', True)
    ca_path = os.path.join(BASE, '_cacert.pem')
    check('A2) 内置 CA 证书存在', os.path.isfile(ca_path),
          '%d 字节' % os.path.getsize(ca_path) if os.path.isfile(ca_path) else 'MISS')
except Exception as e:
    check('A1) loom_net 可 import', False, repr(e))


# ============ B) 同步 http_get ============
try:
    r = loom_net.http_get(BASE_URL + '/api/test?x=1', timeout=3.0)
    check('B1) http_get 成功', r.get('ok') is True, r.get('status'))
    if r.get('ok'):
        data = json.loads(r['body'])
        check('B2) GET 路径正确', data['path'] == '/api/test?x=1', data['path'])
except Exception as e:
    check('B1) http_get 成功', False, repr(e))


# ============ C) 同步 http_post_json ============
try:
    r = loom_net.http_post_json(BASE_URL + '/echo', {'hello': 'world'},
                                timeout=3.0)
    check('C1) http_post_json 成功', r.get('ok') is True, r.get('status'))
    if r.get('ok'):
        data = json.loads(r['body'])
        check('C2) POST 方法正确', data['method'] == 'POST', data['method'])
        check('C3) POST body 透传', 'hello' in data.get('body', ''),
              data.get('body', '')[:80])
except Exception as e:
    check('C1) http_post_json 成功', False, repr(e))


# ============ D) 异步 http_async ============
try:
    req = loom_net.http_async('GET', BASE_URL + '/async', timeout=3.0)
    check('D1) async 创建成功', req is not None)
    # 轮询
    t0 = time.time()
    while not req.is_done() and time.time() - t0 < 5.0:
        time.sleep(0.01)
    check('D2) async 完成', req.is_done())
    r = req.result()
    check('D3) async 结果 ok', r.get('ok') is True, r.get('status'))
except Exception as e:
    check('D1) async 创建成功', False, repr(e))


# ============ E) Script 基类方法 ============
try:
    import scripts as sc
    has_get = hasattr(sc.Script, 'http_get')
    has_post = hasattr(sc.Script, 'http_post_json')
    has_async = hasattr(sc.Script, 'http_async')
    check('E1) Script.http_get', has_get)
    check('E2) Script.http_post_json', has_post)
    check('E3) Script.http_async', has_async)
except Exception as e:
    check('E1) Script.http_get', False, repr(e))


# ============ F) EAI 命令 ============
import agent_commands as ac
cmd_names = set(ac._COMMANDS.keys())
for c in ['http_get', 'http_post_json', 'http_request']:
    check('F) EAI 有 %s' % c, c in cmd_names)


# ============ G) MCP 工具 ============
mcp_src = open(os.path.join(BASE, 'loom_mcp.py'), 'r', encoding='utf-8').read()
for t in ['loom_http_get', 'loom_http_post_json', 'loom_http_request']:
    check('G) MCP 有 %s' % t, ("'name': '%s'" % t) in mcp_src)


# ============ 关闭服务器 ============
srv.shutdown()


print()
if fails:
    print('===== 失败 %d 项 =====' % len(fails))
    for f in fails:
        print('  -', f)
    sys.exit(1)
print('===== 全部通过 =====')
