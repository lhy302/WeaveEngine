# -*- coding: utf-8 -*-
import sys as _sys_utf8
try:
    _sys_utf8.stdout.reconfigure(encoding='utf-8', errors='replace')
    _sys_utf8.stderr.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

"""loom_net: cancel 后结果永久丢弃 (A) + 按 Content-Type charset 解码 (A)."""
import threading
import loom_net as N

ok = True
def check(label, cond, detail=""):
    global ok
    print(("PASS " if cond else "FAIL ") + label + ("  " + detail if detail else ""))
    if not cond:
        ok = False

def new_async():
    q = N.HttpRequestAsync.__new__(N.HttpRequestAsync)
    q._result = None
    q._done = threading.Event()
    q._cancelled = False
    q._lock = threading.Lock()
    return q

orig = N.http_request
try:
    # cancel 之后, 后台线程完成也不得覆写取消态
    q = new_async()
    q.cancel()
    check("cancel 立即完成", q.is_done() and q.result()["error"] == "已取消")
    N.http_request = lambda *a, **k: {"ok": True, "status": 200, "body": "late"}
    q._run("GET", "http://example.invalid", None, None, 1.0, True)
    check("cancel 后结果永久丢弃", q.result()["error"] == "已取消",
          str(q.result()))

    # 正常完成仍返回结果
    q2 = new_async()
    q2._run("GET", "http://example.invalid", None, None, 1.0, True)
    check("正常请求完成", q2.is_done() and q2.result()["ok"] is True
          and q2.result()["body"] == "late")
finally:
    N.http_request = orig

# charset 解码
gbk = "中文响应".encode("gbk")
check("按 Content-Type charset=gbk 解码",
      N._decode_body(gbk, {"Content-Type": "text/plain; charset=gbk"})
      == "中文响应")
check("无 charset 默认 UTF-8",
      N._decode_body("中文".encode("utf-8"),
                     {"Content-Type": "application/json"}) == "中文")
check("非法 charset 回退 UTF-8",
      N._decode_body(b"abc", {"Content-Type": "text/plain; charset=not-a-codec"})
      == "abc")
check("大小写不敏感",
      N._decode_body(gbk, {"content-type": "text/plain; CHARSET=GBK"})
      == "中文响应")

print()
print("总结果:", "ALL PASS" if ok else "有 FAIL")
sys.exit(0 if ok else 1)
