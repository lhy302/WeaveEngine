# -*- coding: utf-8 -*-

"""
test_plugin_sandbox_escape.py — 受限插件沙箱逃逸回归 (审计 scan_09 P-01/P-02, 裁决 Q1=A)

为什么有这个文件
----------------
docs/audit/scan_09_scripting.md 的两条 P0 逃逸链在修复前是**可直接跑通**的:

  链 1 (P-01, 白名单模块命名空间泄漏):
      import collections
      b = collections._sys.modules['builtins']
      b.open(<任意路径>, 'w').write('ESCAPED')     # 写出插件目录外任意文件
    同类: random._os / json.codecs / re.enum.sys / collections._collections_abc.sys

  链 2 (P-02, 异常 traceback 泄漏):
      try: api.register_script(None)               # 宿主 api 校验抛 ValueError
      except ValueError as e:
          g = e.__traceback__.tb_next.tb_frame.f_globals   # = plugin_loader 命名空间
          g['os'].open(<任意路径>, 'w').write(...)

本文件把两条链写成**固定靶场**回归用例, 断言它们被拦住且**没有落盘副作用**:

  A 组 (链 1): 每条链都真的执行 (插件加载 = 真 exec + 真受限 builtins),
              断言 load 报 broken 且目标文件不存在。
  B 组 (链 1 控制): 白名单模块的正常用法 (math.sqrt/re.match/json.loads)
              仍然放行 —— 证明修复不是"一刀切封掉所有模块"。
  C 组 (链 2 静态层): .__traceback__ 直写被 AST 门禁拒载。
  D 组 (链 2 运行时层): 直接对 plugin_sandbox.guard_api 的产物施压 ——
              宿主异常离开 api 边界后只剩 [调用方帧, 沙箱帧],
              拿不到 plugin_loader 的 f_globals (os/sys/importlib 全在),
              也没有 __context__ 可回溯。
  E 组 (接线): 真实受限加载后, 插件拿到的是代理壳 (不是真 PluginAPI);
              沙箱模块命名空间在加载后仍"榨无可榨" (无 __builtins__/无模块对象)。

运行: python tests\test_plugin_sandbox_escape.py   (无头, 无 GPU)
"""
import sys as _sys_utf8
try:
    _sys_utf8.stdout.reconfigure(encoding='utf-8', errors='replace')
    _sys_utf8.stderr.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

import json
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))            # Loom\

import plugin_loader
import plugin_sandbox
from scripts import SCRIPTS

_FAILS = []


def check(name, cond, extra=""):
    print(("PASS " if cond else "FAIL ") + name + ("  " + str(extra) if extra else ""))
    if not cond:
        _FAILS.append(name)


def _write(path, content):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        f.write(content)


def _manifest(pid):
    return json.dumps({"id": pid, "name": "靶场插件", "version": "0.1.0",
                       "entry": "entry.py"}, ensure_ascii=False)


def _plugin(tmp, name, entry_src, pid=None):
    """在 base=tmp 建 plugins/player/<name>/ (plugin.json + entry.py)."""
    d = os.path.join(tmp, 'plugins', 'player', name)
    _write(os.path.join(d, 'plugin.json'), _manifest(pid or ('pk.' + name)))
    _write(os.path.join(d, 'entry.py'), entry_src)


def _cleanup():
    for pid in list(plugin_loader._LOADED):
        plugin_loader.unload_plugin(pid, disable=False)
    plugin_loader._DISABLED.clear()
    plugin_loader._EDITOR_BUTTONS[:] = []
    for sid in list(SCRIPTS):
        if sid.startswith('pk_'):
            del SCRIPTS[sid]


def _raises(exc, fn):
    try:
        fn()
    except exc:
        return True
    except Exception:
        return False
    return False


def _load_one_plugin(entry_src, name='evil'):
    """在独立临时目录里加载单个受限插件, 返回 (result, 目标文件路径, tmp)."""
    tmp = tempfile.mkdtemp()
    target = os.path.join(tmp, 'PWNED.txt')
    # 生成 entry.py 时写入**正斜杠**路径: Windows 反斜杠在 Python 字符串
    # 字面量里是转义符 (C:\Users 会被当 \UXXXXXXXX 语法错误, 靶场会变成
    # "语法错误"假阳性, 掩盖真正的逃逸断言)。
    _plugin(tmp, name, entry_src.replace('__TARGET__', target.replace('\\', '/')),
            pid='pk.' + name)
    r = plugin_loader.load_plugins(base=tmp)
    return r, target, tmp


# ====================================================================
# A 组: 链 1 —— 白名单模块命名空间泄漏 (P-01)
# 每条链都必须 broken, 且 PWNED 文件不得生成。
# ====================================================================
CHAIN1 = (
    # (变体名, entry 源码)  —— 全部走"纯属性/下标", 不含任何 AST 黑面名,
    # 修复前 AST 与运行时快检都判"通过"。
    ('collections_sys',
     "import collections\n"
     "def register(api):\n"
     "    b = collections._sys.modules['builtins']\n"
     "    b.open('__TARGET__', 'w').write('ESCAPED via collections._sys')\n"),
    ('collections_abc',
     "import collections\n"
     "def register(api):\n"
     "    b = collections._collections_abc.sys.modules['builtins']\n"
     "    b.open('__TARGET__', 'w').write('ESCAPED via collections.abc')\n"),
    ('random_os',
     "import random\n"
     "def register(api):\n"
     "    random._os.open('__TARGET__', 'w').write('ESCAPED via random._os')\n"),
    ('json_codecs',
     "import json\n"
     "def register(api):\n"
     "    json.codecs.open('__TARGET__', 'w').write('ESCAPED via json.codecs')\n"),
    ('re_enum',
     "import re\n"
     "def register(api):\n"
     "    b = re.enum.sys.modules['builtins']\n"
     "    b.open('__TARGET__', 'w').write('ESCAPED via re.enum.sys')\n"),
)


def t_chain1_blocked():
    for vid, src in CHAIN1:
        _cleanup()
        r, target, tmp = _load_one_plugin(src, name=vid)
        errs = [b['error'] for b in r['broken']]
        check("[链1/%s] 加载被拒 (broken 含 受限/AttributeError)" % vid,
              r['loaded'] == [] and len(r['broken']) == 1
              and ('受限' in errs[0] or 'AttributeError' in errs[0]), errs)
        check("[链1/%s] 未落盘 (PWNED 文件不存在)" % vid,
              not os.path.exists(target), target)
        check("[链1/%s] 无脚本注册残留" % vid, r['loaded'] == [])


# ====================================================================
# B 组: 链 1 控制 —— 白名单模块的正常用法仍放行 (防"一刀切")
# ====================================================================
ENTRY_WHITELIST_OK = """# -*- coding: utf-8 -*-
import math
import re
import json
import collections
import random
import functools
import itertools
import copy


class WScript:
    script_id = 'pk_whitelist_ok'
    name = '白名单正常用法'


def register(api):
    assert math.sqrt(9.0) == 3.0
    assert re.match(r'^a', 'ab') is not None
    assert json.loads('{"k": 1}') == {'k': 1}
    c = collections.OrderedDict([('a', 1)])
    assert list(c.keys()) == ['a']
    assert 0.0 <= random.random() < 1.0
    assert functools.reduce(lambda a, b: a + b, [1, 2, 3]) == 6
    assert list(itertools.islice(itertools.count(), 3)) == [0, 1, 2]
    assert copy.copy({'x': 1}) == {'x': 1}
    api.register_script(WScript)
"""


def t_whitelist_still_works():
    _cleanup()
    r, target, tmp = _load_one_plugin(ENTRY_WHITELIST_OK, name='ok')
    check("[链1控制] 白名单正常用法仍放行 (math/re/json/collections/random/"
          "functools/itertools/copy)",
          r['loaded'] == ['pk.ok'] and r['broken'] == []
          and 'pk_whitelist_ok' in SCRIPTS, r)
    _cleanup()


# ====================================================================
# C 组: 链 2 静态层 —— .__traceback__ 直写被 AST 拒载
# ====================================================================
CHAIN2_AST = (
    ('traceback_frame',
     "def register(api):\n"
     "    try:\n"
     "        api.register_script(None)\n"
     "    except ValueError as e:\n"
     "        g = e.__traceback__.tb_next.tb_frame.f_globals\n"
     "        g['os'].open('__TARGET__', 'w').write('ESCAPED')\n"),
    ('frame_first',
     "def register(api):\n"
     "    try:\n"
     "        api.register_script(None)\n"
     "    except ValueError as e:\n"
     "        g = e.__traceback__.tb_frame.f_globals\n"
     "        g['os'].open('__TARGET__', 'w').write('ESCAPED')\n"),
    ('context_chain',
     "def register(api):\n"
     "    try:\n"
     "        api.register_script(None)\n"
     "    except ValueError as e:\n"
     "        g = e.__context__.__traceback__.tb_frame.f_globals\n"
     "        g['os'].open('__TARGET__', 'w').write('ESCAPED')\n"),
)


def t_chain2_ast_blocked():
    for vid, src in CHAIN2_AST:
        _cleanup()
        r, target, tmp = _load_one_plugin(src, name=vid)
        errs = [b['error'] for b in r['broken']]
        check("[链2/AST/%s] 直写被 AST 拒载 (broken 含 AST)" % vid,
              r['loaded'] == [] and len(r['broken']) == 1
              and 'AST' in errs[0], errs)
        check("[链2/AST/%s] 未落盘" % vid, not os.path.exists(target))


# ====================================================================
# D 组: 链 2 运行时层 —— 宿主异常离开 api 边界后只剩沙箱帧
# （AST 名单只能拦"直接书写"; 混淆写法仍可能绕, 故运行时必须兜底）
# ====================================================================
def t_chain2_runtime_sanitized():
    info = {"id": "pk.runtime", "name": "运行时靶场", "version": "0.1.0",
            "entry": "entry.py"}
    api = plugin_loader.PluginAPI(info, kind='standard', layer='editor', path='')
    gapi = plugin_sandbox.guard_api(api)

    target = os.path.join(tempfile.mkdtemp(), 'PWNED_RUNTIME.txt')
    caught = {}
    try:
        gapi.register_script(None)          # 宿主 api 校验 -> 真 ValueError
    except ValueError as e:
        caught['e'] = e
    e = caught.get('e')
    check("[链2/运行时] 宿主异常仍是 ValueError 且消息保留",
          type(e).__name__ == 'ValueError'
          and 'register_script 需要' in str(e), repr(e))
    check("[链2/运行时] 无 __context__ / __cause__ (拿不到宿主原始异常)",
          e.__context__ is None and e.__cause__ is None,
          (e.__context__, e.__cause__))

    chain = []
    tb = e.__traceback__
    while tb is not None:
        fg = tb.tb_frame.f_globals
        chain.append((fg.get('__name__'), fg is plugin_loader.__dict__,
                      'os' in fg, 'sys' in fg, '__builtins__' in fg))
        tb = tb.tb_next
    # 第 0 帧是调用方自己 (本测试文件, 它 import 了 os —— 与逃逸无关);
    # 关键是: 链里不得出现 plugin_loader 帧, 且沙箱帧的 f_globals 不含 os/sys。
    check("[链2/运行时] 异常链里没有 plugin_loader 帧 (沙箱帧 f_globals 不含 os/sys)",
          all(not hit[1] for hit in chain)
          and all(not hit[2] and not hit[3] for hit in chain[1:]), chain)
    check("[链2/运行时] 除调用方帧外的帧都来自 plugin_sandbox (命名空间榨无可榨)",
          all(hit[0] in ('plugin_sandbox', '__main__',
                         'test_plugin_sandbox_escape') for hit in chain), chain)

    # tb_next 就是审计里报的攻击入口: 修复前它是 plugin_loader 的帧
    g = e.__traceback__.tb_next.tb_frame.f_globals
    check("[链2/运行时] tb_next.f_globals 不是 plugin_loader 命名空间 (没有 os)",
          g is not plugin_loader.__dict__ and 'os' not in g and 'sys' not in g,
          sorted(k for k in g if k in ('os', 'sys', '__builtins__')))
    # 真正的验收: 攻击者想照审计写法写盘 -> 拿不到 os, 文件不生成
    try:
        g['os'].open(target, 'w').write('ESCAPED via __traceback__')
        escaped = True
    except Exception:
        escaped = False
    check("[链2/运行时] 复现审计攻击写法 -> 拿不到 os, 未落盘",
          (not escaped) and (not os.path.exists(target)))


# ====================================================================
# E 组: 接线 —— 真实受限加载后拿到的确实是代理壳; 沙箱命名空间仍干净
# ====================================================================
ENTRY_PROBE_API = """# -*- coding: utf-8 -*-
HOOK = None


def register(api):
    global HOOK
    HOOK = api
"""


def t_wiring():
    _cleanup()
    tmp = tempfile.mkdtemp()
    _plugin(tmp, 'wire', ENTRY_PROBE_API, pid='pk.wire')
    r = plugin_loader.load_plugins(base=tmp)
    ent = plugin_loader.get_plugin('pk.wire')
    api = ent and ent.get('api')
    gapi = ent and ent.get('gapi')
    check("[接线] 受限插件 loaded", r['loaded'] == ['pk.wire'], r)
    check("[接线] 插件拿到的是 _GuardedApi 代理壳 (不是真 PluginAPI)",
          type(gapi).__name__ == '_GuardedApi'
          and type(ent['mod'].HOOK).__name__ == '_GuardedApi'
          and ent['mod'].HOOK is gapi,
          (type(ent['mod'].HOOK).__name__, type(gapi).__name__))
    check("[接线] 代理壳内部句柄不可访问",
          _raises(AttributeError, lambda: gapi._ga_impl))
    check("[接线] 宿主侧仍持有真 api (卸载清理用)",
          isinstance(api, plugin_loader.PluginAPI))
    check("[接线] 沙箱命名空间榨无可榨 (无 __builtins__ / 无模块对象)",
          plugin_sandbox.sandbox_globals_clean() is True)
    _cleanup()


if __name__ == "__main__":
    print("========== 受限插件沙箱逃逸回归 (scan_09 P-01/P-02) ==========")
    _cleanup()
    t_chain1_blocked()
    t_whitelist_still_works()
    t_chain2_ast_blocked()
    t_chain2_runtime_sanitized()
    t_wiring()
    _cleanup()
    print()
    if _FAILS:
        print("总结果: FAIL ❌", _FAILS)
        sys.exit(1)
    print("总结果: ALL PASS ✅")
