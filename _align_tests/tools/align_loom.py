# -*- coding: utf-8 -*-
"""align_loom.py — Loom 侧对齐测试驱动 (MCP stdio -> 引擎 HTTP)。

用法:
    py align_loom.py <case_dir>

<case_dir>/ops.json 格式:
    {"cases": [{"name": ..., "op": ..., "args": {...}}, ...]}

每 case 三步:
    1. screenshot 到引擎默认目录 (避开写路径白名单) -> 搬到 case_dir
    2. 调 MCP 工具 (op/args)
    3. screenshot 到引擎默认目录 -> 搬到 case_dir

前置: 引擎以 --agent 启动。
"""
import glob
import json
import os
import shutil
import subprocess
import sys
import time

LOOM_DIR = r"D:\my-project - 副本\Loom(py源代码-工作区)\Loom"
SAVE_DIR = os.path.join(LOOM_DIR, '保存')


def check_engine_alive():
    pf = os.path.join(LOOM_DIR, '.agent_port.json')
    if not os.path.exists(pf):
        print('[对齐] 引擎未启动 (无 .agent_port.json)')
        return False
    try:
        info = json.load(open(pf, encoding='utf-8'))
        import ctypes
        k = ctypes.windll.kernel32
        h = k.OpenProcess(0x1000, False, int(info['pid']))
        if not h:
            print('[对齐] 引擎进程 %s 已死, 请重启' % info['pid'])
            return False
        k.CloseHandle(h)
        return True
    except Exception as e:
        print('[对齐] 端口文件解析失败: %r' % e)
        return False


class MCPClient:
    def __init__(self):
        self.p = subprocess.Popen(
            ['py', '-3.12', os.path.join(LOOM_DIR, 'loom_mcp.py')],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            cwd=LOOM_DIR, text=True, encoding='utf-8', bufsize=1)
        self._id = 0
        self._handshake()

    def _send(self, obj):
        self.p.stdin.write(json.dumps(obj) + '\n')
        self.p.stdin.flush()

    def _recv(self):
        line = self.p.stdout.readline()
        if not line:
            err = self.p.stderr.read()
            raise RuntimeError('MCP 无响应: %s' % err[:400])
        return json.loads(line)

    def _handshake(self):
        self._send({'jsonrpc': '2.0', 'id': 1, 'method': 'initialize',
                    'params': {'protocolVersion': '2024-11-05', 'capabilities': {}}})
        self._recv()
        self._send({'jsonrpc': '2.0', 'method': 'notifications/initialized'})

    def call(self, tool, args=None):
        self._id += 1
        self._send({'jsonrpc': '2.0', 'id': self._id, 'method': 'tools/call',
                    'params': {'name': tool, 'arguments': args or {}}})
        r = self._recv()
        res = r.get('result', {})
        return {'isError': res.get('isError', False),
                'content': (res.get('content') or [{}])[0].get('text', '')}

    def close(self):
        try:
            self.p.stdin.close()
            self.p.terminate()
        except Exception:
            pass


def _snap_before():
    """记下 保存/ 里现有的 png 集合 (用于识别新产生的)."""
    return set(glob.glob(os.path.join(SAVE_DIR, 'shot_*.png')))


def _grab_new(before_set, dest):
    """取 保存/ 里新增的那个 png, 搬到 dest."""
    for _ in range(30):
        now = set(glob.glob(os.path.join(SAVE_DIR, 'shot_*.png')))
        new = now - before_set
        if new:
            src = sorted(new, key=os.path.getmtime)[-1]
            try:
                os.makedirs(os.path.dirname(dest), exist_ok=True)
                shutil.copy2(src, dest)
                os.remove(src)         # 清走, 避免下 case 认错
                return True
            except Exception as e:
                print('[截图] 搬运失败 %r' % e)
                return False
        time.sleep(0.1)
    print('[截图] 超时未发现新图: %s' % dest)
    return False


def shot(cli, dest):
    before = _snap_before()
    r = cli.call('unity_capture_viewport', {'path': ''})
    if r['isError']:
        print('[截图] 失败: %s' % r['content'][:200])
        return False
    return _grab_new(before, dest)


def main():
    if len(sys.argv) < 2:
        print('用法: py align_loom.py <case_dir>')
        sys.exit(1)
    case_dir = os.path.abspath(sys.argv[1])
    ops_path = os.path.join(case_dir, 'ops.json')
    if not os.path.exists(ops_path):
        print('缺少 ops.json: %s' % ops_path)
        sys.exit(1)
    if not check_engine_alive():
        sys.exit(2)

    ops = json.load(open(ops_path, encoding='utf-8'))
    os.makedirs(case_dir, exist_ok=True)
    cli = MCPClient()
    # ★ 跑前重置场景 (清脏状态)
    r0 = cli.call('unity_scene_new', {})
    print('[重置] scene_new -> isError=%s' % r0['isError'])
    time.sleep(0.5)
    results = []
    try:
        for c in ops.get('cases', []):
            name = c['name']
            print('[case] %s  op=%s' % (name, c.get('op')))
            shot(cli, os.path.join(case_dir, '%s_before.png' % name))
            r = cli.call(c['op'], c.get('args') or {})
            time.sleep(0.3)
            shot(cli, os.path.join(case_dir, '%s_after.png' % name))
            results.append({'name': name, 'op': c.get('op'),
                            'args': c.get('args'), 'isError': r['isError'],
                            'result': r['content']})
    finally:
        cli.close()

    out = os.path.join(case_dir, 'loom_result.json')
    with open(out, 'w', encoding='utf-8') as f:
        json.dump({'results': results}, f, ensure_ascii=False, indent=2)
    print('[对齐] Loom 侧完成: %s' % out)


if __name__ == '__main__':
    main()
