# -*- coding: utf-8 -*-

"""EAI / MCP 目标与写路径守卫回归 (2026-11-07, P1-3 + P1-4).

两块同源风险: [按名字/序号定位] 与 [按模型给的路径落盘] —— 两者出错都是
不可逆动作 (删错对象 / 往工程外写文件)。

A) object_select 重名歧义 (P1-3):
   旧实现 `hits = [h for h in hits if h[2] == want] or hits` 有三处坑:
     1) 没传 index 时直接选 hits[0] (只回一个 ambiguous 提示, 动作已发生);
     2) index 越界时 `or hits` 兜底回全量, 仍然选 hits[0];
     3) 只按序号过滤不分类型 (model#1 与 light#1 会同时命中)。
   MCP 的 unity_gameobject_delete / _duplicate 就是先 object_select 再动手。
   新契约: 歧义/越界一律 ok=False, 错误串列出候选 kind#index。

B) MCP unity_script_write_file 写路径 (P1-4):
   旧实现直接 os.path.join(scripts_dir, filename) 就写 -> '../..' 出工程、
   绝对路径整体丢弃前缀、scripts 内放 junction 也能绕。
   新契约: realpath 必须落在 <工程>/scripts/ 内, 且复用 EAI 写白名单。
"""

import sys as _sys_utf8
try:
    _sys_utf8.stdout.reconfigure(encoding='utf-8', errors='replace')
    _sys_utf8.stderr.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

import atexit as _atexit_gate
import os as _os_gate
import sys as _sys_gate


class _FailGateStream:
    def __init__(self, stream):
        self._stream = stream
        self.failed = False

    def write(self, text):
        if isinstance(text, str) and (text.startswith("FAIL") or "\nFAIL" in text):
            self.failed = True
        return self._stream.write(text)

    def __getattr__(self, name):
        return getattr(self._stream, name)


_fail_gate = _FailGateStream(_sys_gate.stdout)
_sys_gate.stdout = _fail_gate


@_atexit_gate.register
def _enforce_fail_exit_code():
    if not _fail_gate.failed:
        return
    try:
        _sys_gate.stdout.flush()
        _sys_gate.stderr.flush()
    except Exception:
        pass
    _os_gate._exit(1)


import os
import shutil
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
os.chdir(ROOT)
os.environ.setdefault('LOOM_NO_PARALLEL', '1')

import agent_commands as ac
import loom_mcp

ok = True


def check(label, cond, detail=''):
    global ok
    print(('PASS ' if cond else 'FAIL ') + label + ('  ' + str(detail) if detail else ''))
    if not cond:
        ok = False


# ====================================================================
# A) object_select: 歧义 / 越界 index 必须拒绝
# ====================================================================
class _Obj:
    def __init__(self, name, guid=None):
        self.name = name
        self.guid = guid


class _Ed:
    def __init__(self):
        self.models = [_Obj('dup', 'g0'), _Obj('dup', 'g1'), _Obj('solo', 'g2')]
        self.lights = [_Obj('dup', 'g3')]
        self.cameras = []
        self.selected_index = -1
        self.selected_light_index = -1
        self.selected_camera_index = -1

    def _select_model(self, i):
        self.selected_index = i
        self.selected_light_index = self.selected_camera_index = -1

    def _selected(self):
        return self.models[self.selected_index] if self.selected_index >= 0 else None


def _win(ed):
    return type('W', (), {'editor': ed})()


ed = _Ed()
win = _win(ed)

r = ac.dispatch('object_select', {'name': 'dup'}, win)
check('重名 + 无 index -> ok=False (不再静默选第一个)', r.get('ok') is False, r.get('error'))
check('重名 + 无 index -> 错误串含候选清单 (重名 ... model#0) ',
      '重名' in (r.get('error') or '') and 'model#0' in (r.get('error') or ''),
      r.get('error'))
check('重名 + 无 index -> 没有改动选中态', ed.selected_index == -1, ed.selected_index)

ed.selected_index = -1
r = ac.dispatch('object_select', {'name': 'dup', 'index': 99}, win)
check('index 越界 -> ok=False (原来 or hits 兜底会选第一个)',
      r.get('ok') is False, r.get('error'))
check('index 越界 -> 没有改动选中态', ed.selected_index == -1, ed.selected_index)

r = ac.dispatch('object_select', {'name': 'dup', 'index': 1}, win)
check('index 精确命中 -> ok=True 且选中 #1',
      r.get('ok') and r['result']['index'] == 1 and ed.selected_index == 1,
      r.get('result'))

r = ac.dispatch('object_select', {'name': 'solo'}, win)
check('唯一名 -> ok=True (老行为不变)',
      r.get('ok') and r['result']['selected'] == 'solo' and r['result']['index'] == 2,
      r.get('result'))

r = ac.dispatch('object_select', {'index': 99}, win)
check('无 name + index 越界 -> 拒绝 (老契约)', r.get('ok') is False and '越界' in r['error'],
      r.get('error'))

# model#0 与 light#0 序号相同: 只按序号过滤会同时命中, 必须拒绝而不是挑一个
r = ac.dispatch('object_select', {'name': 'dup', 'index': 0}, win)
check('跨类型同序号 (model#0 与 light#0) -> 仍明确拒绝',
      r.get('ok') is False and '重名' in (r.get('error') or ''), r.get('error'))

r = ac.dispatch('object_select', {'name': 'g1'}, win)
check('GUID 精确寻址不受重名影响',
      r.get('ok') and r['result']['index'] == 1, r.get('result'))

r = ac.dispatch('object_select', {'name': '不存在'}, win)
check('找不到 -> 拒绝', r.get('ok') is False and '找不到' in r['error'], r.get('error'))

# ====================================================================
# B) MCP unity_script_write_file: 写路径白名单
# ====================================================================
BASE = tempfile.mkdtemp(prefix='loom_mcpwl_')
PROJ = os.path.join(BASE, 'proj')
os.makedirs(PROJ)
srv = loom_mcp.LoomMCPServer(loom_mcp.LoomEngineClient(base_dir=PROJ))


def _write(fname, code='print(1)'):
    r = srv.dispatch_tool('unity_script_write_file', {'filename': fname, 'code': code})
    return r['isError'], r['content'][0]['text']


bad, msg = _write('player.lua')
check('正常脚本名 -> 写入成功', bad is False, msg)
check('正常脚本名 -> 文件真在 <工程>/scripts 下',
      os.path.isfile(os.path.join(PROJ, 'scripts', 'player.lua')), msg)

for fname in ('../escape1.py', '../../escape2.py', 'a/../../../escape3.lua'):
    bad, msg = _write(fname)
    check('路径逃逸 %r -> 拒绝' % fname, bad is True and '越域' in msg, msg)

_outside = os.path.join(tempfile.gettempdir(), 'loom_mcp_abs_proof.py')
bad, msg = _write(_outside)
check('脚本目录外的绝对路径 -> 拒绝', bad is True and '越域' in msg, msg)
check('被拒绝的绝对路径 -> 文件没被创建', not os.path.exists(_outside), _outside)

for p in (os.path.join(BASE, 'escape1.py'), os.path.join(BASE, 'escape2.py'),
          os.path.join(BASE, 'escape3.py'), os.path.join(BASE, 'escape3.lua')):
    if os.path.exists(p):
        check('逃逸文件不该存在: %s' % p, False, p)
        try:
            os.remove(p)
        except OSError:
            pass

bad, msg = _write('wrong.txt')
check('非 .lua/.py -> 拒绝 (老契约)', bad is True and 'lua' in msg, msg)

# junction / symlink 逃逸: 在 scripts/ 里放一个指向工程外的链接,
# 字符串前缀完全合法, 只有 realpath 能挡住。Windows 建 junction 需要权限,
# 失败就跳过 (不算 FAIL), 成功则必须被拒绝。
_scripts = os.path.join(PROJ, 'scripts')
_link = os.path.join(_scripts, 'evil')
_target = os.path.join(BASE, 'outside_target')
os.makedirs(_target, exist_ok=True)
_linked = False
try:
    if hasattr(os, 'symlink'):
        os.symlink(_target, _link, target_is_directory=True)
        _linked = True
except (OSError, NotImplementedError, AttributeError):
    _linked = False
if not _linked:
    try:
        import subprocess
        _p = subprocess.run(['cmd', '/c', 'mklink', '/J', _link, _target],
                            capture_output=True)
        _linked = _p.returncode == 0 and os.path.isdir(_link)
    except Exception:
        _linked = False
if _linked:
    bad, msg = _write(os.path.join('evil', 'escape4.py'))
    check('junction/symlink 指向工程外 -> 拒绝 (realpath 生效)',
          bad is True and '越域' in msg, msg)
    check('junction 逃逸文件没被创建',
          not os.path.exists(os.path.join(_target, 'escape4.py')),
          os.path.join(_target, 'escape4.py'))
else:
    print('SKIP junction 逃逸用例 (当前环境无法建链接, 不算失败)')

# 脚本目录内的相对子目录属于合法目标 (只校验路径, 不真写: 子目录不存在时
# open 会抛 FileNotFoundError —— 那是既有行为, 不在本项修复范围)
_ok_sub, _p_sub = loom_mcp._safe_script_path(PROJ, 'sub/dir/x.lua')
check('脚本目录内的相对子目录 -> 路径校验通过',
      _ok_sub is True and os.path.basename(_p_sub) == 'x.lua', _p_sub)

shutil.rmtree(BASE, ignore_errors=True)
try:
    os.remove(_outside)
except OSError:
    pass

# ====================================================================
# C) ui_add / ui_set 的 rect/anchor/pivot: 字符串不能变坏 tuple
# ====================================================================
import loom_ui as _lu


class _UWin:
    def __init__(self):
        ed = type('Ed', (), {})()
        ed.ui = _lu.UIManager()
        ed.ui.default_canvas()
        ed.undo = None
        self.editor = ed

    def root(self):
        return self.editor.ui.canvases[0].root


uw = _UWin()
r = ac.dispatch('ui_add', {'type': 'panel', 'rect': '0,0,120,40'}, uw)
_p = uw.root().children[-1] if r.get('ok') else None
check('ui_add rect 逗号字符串 -> 真生效 (0,0,120,40)',
      r.get('ok') and _p.rect == (0.0, 0.0, 120.0, 40.0),
      (r.get('error'), getattr(_p, 'rect', None)))

r = ac.dispatch('ui_add', {'type': 'panel', 'rect': [1, 2, 3, 4],
                          'anchor': '0.5 0.5', 'pivot': (0, 1)}, uw)
_p2 = uw.root().children[-1] if r.get('ok') else None
check('ui_add rect 数组 + anchor 空格串 + pivot 元组 -> 真生效',
      r.get('ok') and _p2.rect == (1.0, 2.0, 3.0, 4.0)
      and _p2.anchor == (0.5, 0.5) and _p2.pivot == (0.0, 1.0),
      (r.get('error'), getattr(_p2, 'rect', None),
       getattr(_p2, 'anchor', None), getattr(_p2, 'pivot', None)))

for _bad, _why in (('0100', '项数不对/字符拆分'), ([1, 2], 'rect 只有 2 项'),
                   ((1, 2, 3, 4, 5), 'rect 5 项'), ('a,b,c,d', '非数值'),
                   ([1, 2, float('nan'), 4], 'NaN'), (123, '非数组')):
    _n0 = len(uw.root().children)
    r = ac.dispatch('ui_add', {'type': 'panel', 'rect': _bad}, uw)
    check('ui_add rect=%r (%s) -> 拒绝且不建元素' % (_bad, _why),
          r.get('ok') is False and len(uw.root().children) == _n0,
          r.get('error'))

r = ac.dispatch('ui_add', {'type': 'panel', 'anchor': [0.5]}, uw)
check('ui_add anchor 项数不对 -> 拒绝', r.get('ok') is False, r.get('error'))
r = ac.dispatch('ui_add', {'type': 'panel', 'pivot': 'x,y'}, uw)
check('ui_add pivot 非数值 -> 拒绝', r.get('ok') is False, r.get('error'))

r = ac.dispatch('ui_set', {'name': _p.name, 'rect': '10,20,30,40'}, uw)
check('ui_set rect 字符串 -> 真生效 (老代码静默丢弃)',
      r.get('ok') and _p.rect == (10.0, 20.0, 30.0, 40.0),
      (r.get('error'), _p.rect))
_before = _p.rect
r = ac.dispatch('ui_set', {'name': _p.name, 'rect': '1,2,3'}, uw)
check('ui_set rect 项数不对 -> 拒绝且不改',
      r.get('ok') is False and _p.rect == _before, r.get('error'))

# ====================================================================
# D) loom_mcp.run_stdio_server: 工具异常不能打死进程
# ====================================================================
import io
import json as _json


class _BoomServer:
    """handle_request: 'boom' 抛异常, 其它正常返回 —— 验证循环继续。"""

    def handle_request(self, req):
        if req.get('method') == 'boom':
            raise RuntimeError('kaboom')
        return {'jsonrpc': '2.0', 'id': req.get('id'), 'result': {'ok': True}}


_orig_cls = loom_mcp.LoomMCPServer
_orig_stdin = sys.stdin
_orig_stdout = sys.stdout
_buf = io.StringIO()
try:
    loom_mcp.LoomMCPServer = lambda *a, **k: _BoomServer()
    sys.stdin = io.StringIO(
        _json.dumps({'jsonrpc': '2.0', 'id': 1, 'method': 'boom'}) + '\n'
        + _json.dumps({'jsonrpc': '2.0', 'id': 2, 'method': 'ping'}) + '\n')
    sys.stdout = _buf
    loom_mcp.run_stdio_server()
finally:
    loom_mcp.LoomMCPServer = _orig_cls
    sys.stdin = _orig_stdin
    sys.stdout = _orig_stdout

_lines = [ln for ln in _buf.getvalue().splitlines() if ln.strip()]
check('run_stdio_server: 工具异常后进程不退出, 后续请求继续处理 (2 条响应)',
      len(_lines) == 2, _lines)
if len(_lines) == 2:
    _e = _json.loads(_lines[0])
    _okr = _json.loads(_lines[1])
    check('异常请求 -> JSON-RPC error (code -32603, id 对齐)',
          _e.get('error', {}).get('code') == -32603 and _e.get('id') == 1, _e)
    check('异常后的正常请求 -> 正常 result',
          _okr.get('result', {}).get('ok') is True and _okr.get('id') == 2, _okr)

print()
print('总结果:', 'ALL PASS' if ok else '有 FAIL')
sys.exit(0 if ok else 1)
