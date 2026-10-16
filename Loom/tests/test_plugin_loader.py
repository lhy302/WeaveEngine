# -*- coding: utf-8 -*-
"""
test_plugin_loader.py — Loom 插件加载器测试 (L1 分级, 2026-08-27, 全无头).
覆盖: plugins/editor|player 目录分层 (目录即声明注入层) / core_plugins/<类别>
信任闸 (未信任/modified 不加载 + confirm 后重启生效 + 哈希校验) / 普通插件
受限环境 (黑名单 import 拒 / 无 open·exec·eval / 白名单放行 / 动态名拒) /
player mode 全权 / 跨层按钮注册 / scan_player_plugins 封装收集 (只收
player 层) / 内存包加载 load_plugin_from_pack.
无头 (无需 pygame); 每用例独立 tempfile.TemporaryDirectory; 每次注册脚本
后清理 scripts.SCRIPTS 与 plugin_loader 全局状态, 避免污染其他测试.
"""
import json
import os
import shutil
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))            # Loom\ (plugin_loader / scripts ...)

import plugin_loader
from scripts import SCRIPTS

_FAILS = []


def check(name, cond, extra=""):
    print(("PASS " if cond else "FAIL ") + name + ("  " + str(extra) if extra else ""))
    if not cond:
        _FAILS.append(name)


def _write(path, content, binary=False):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    mode = 'wb' if binary else 'w'
    with open(path, mode, encoding=None if binary else 'utf-8') as f:
        f.write(content)


def _cleanup():
    """清理全局状态 (脚本/按钮/禁用/loaded), 避免跨用例污染."""
    for pid in list(plugin_loader._LOADED):
        plugin_loader.unload_plugin(pid, disable=False)
    plugin_loader._DISABLED.clear()
    plugin_loader._EDITOR_BUTTONS[:] = []
    for sid in list(SCRIPTS):
        if sid.startswith('p_') or sid.startswith('c_'):
            del SCRIPTS[sid]


def _manifest(extra=""):
    info = {
        "id": "com.example.ok",
        "name": "OK 插件",
        "version": "0.1.0",
        "entry": "entry.py",
    }
    info.update(extra)
    return json.dumps(info, ensure_ascii=False)


def _core_manifest(layer="player", cap="render", **extra):
    info = json.loads(_manifest())
    info.update({"layer": layer, "capability": cap, "desc": "测试核心插件"})
    info.update(extra)
    return json.dumps(info, ensure_ascii=False)


# 合法插件 entry.py: 注册一个 script_id='p_ok' 的脚本类
# 2026-08-28: scripts 已移出受限白名单 (靶场 V04 实锤: 命名空间含 os/sys),
# 不再 from scripts import Script —— 注册走 api.register_script 即可
ENTRY_OK = """# -*- coding: utf-8 -*-
class POkScript:
    script_id = 'p_ok'
    name = '插件测试脚本'

def register(api):
    api.register_script(POkScript)
"""

ENTRY_NO_REGISTER = """# -*- coding: utf-8 -*-
class NoRegister(object):
    pass
"""

ENTRY_BOOM = """# -*- coding: utf-8 -*-
def register(api):
    raise RuntimeError('boom 插件坏钩子')
"""

ENTRY_MENU = """# -*- coding: utf-8 -*-
def register(api):
    api.register('menu', {'name': '测试菜单'})
"""

ENTRY_NO_SID = """# -*- coding: utf-8 -*-
class NoSid(object):
    pass

def register(api):
    api.register_script(NoSid)
"""

ENTRY_IMPORT_OS = """# -*- coding: utf-8 -*-
import os
def register(api):
    pass
"""

ENTRY_USE_OPEN = """# -*- coding: utf-8 -*-
def register(api):
    f = open('x.txt')   # 受限 builtins 无 open
"""

ENTRY_USE_EXEC = """# -*- coding: utf-8 -*-
def register(api):
    exec('1+1')   # 受限 builtins 无 exec
"""

ENTRY_DYNAMIC_IMPORT = """# -*- coding: utf-8 -*-
def register(api):
    __import__('o' + 's')   # 拼接名也拒 (受限 __import__ 黑名单)
"""

ENTRY_WHITELIST = """# -*- coding: utf-8 -*-
import math
import re
import json

class WScript:            # 2026-08-28: 不再 from scripts import Script ——
    script_id = 'p_math'  # scripts/engine 已移出受限白名单 (靶场 V04 实锤:
    name = '白名单脚本'     # 命名空间含 os/sys/np, import 即直取系统面);
                          # 脚本注册走 api.register_script, 不需引用基类
def register(api):
    assert math.sqrt(4.0) == 2.0 and re.match(r'^x', 'xy') and json.loads('{}') == {}
    api.register_script(WScript)
"""

ENTRY_ASSET = """# -*- coding: utf-8 -*-
def register(api):
    data = api.read_asset('data.txt')
    assert data.strip() == 'hello', data
    try:
        api.read_asset('../secret.txt')
        raise AssertionError('越界未拦截')
    except ValueError:
        pass
"""

ENTRY_BUTTON = """# -*- coding: utf-8 -*-
def _cb():
    return 'clicked'

def register(api):
    api.register_editor_button('测试按钮', _cb)
"""

ENTRY_IMPORT_OS_FULL = """# -*- coding: utf-8 -*-
import os
def register(api):
    assert os.path is not None
"""

ENTRY_DEACT = """# -*- coding: utf-8 -*-
# 2026-08-28: scripts 已移出受限白名单 (靶场 V04 实锤) —— 不再 from
# scripts import Script, 脚本注册走 api.register_script
class DScript:
    script_id = 'p_deact'
    name = '卸载测试'

GOT = None

def register(api):
    global GOT
    GOT = api
    api.register_script(DScript)

def deactivate(api):
    api._deactivated = True
"""


def _plugin(tmp, layer, name, manifest=None, entry=None, entry_name="entry.py"):
    """在 base=tmp 建 plugins/<layer>/<name>/ (plugin.json + entry.py)."""
    if manifest is None:
        manifest = _manifest()
    if entry is None:
        entry = ENTRY_OK
    _write(os.path.join(tmp, 'plugins', layer, name, 'plugin.json'), manifest)
    _write(os.path.join(tmp, 'plugins', layer, name, entry_name), entry)


def _core(tmp, cat, name, manifest=None, entry=None):
    """core_plugins/<cat>/<name>/ (核心清单默认 layer=player, cap=render)."""
    if manifest is None:
        manifest = _core_manifest()
    if entry is None:
        entry = ENTRY_OK
    _write(os.path.join(tmp, 'core_plugins', cat, name, 'plugin.json'), manifest)
    _write(os.path.join(tmp, 'core_plugins', cat, name, 'entry.py'), entry)


# ============ 1. 插件目录不存在 ============
def t_no_plugins_dir():
    with tempfile.TemporaryDirectory() as tmp:
        r = plugin_loader.load_plugins(base=tmp)
        check("空程序目录 → loaded=[] broken=[] untrusted=[]",
              r == {'loaded': [], 'broken': [], 'untrusted': []}, r)


# ============ 2. player 层合法插件注册脚本 ============
def t_valid_plugin_player():
    with tempfile.TemporaryDirectory() as tmp:
        _plugin(tmp, 'player', 'ok')
        r = plugin_loader.load_plugins(base=tmp)
        check("player 插件 loaded 含 com.example.ok",
              'com.example.ok' in r['loaded'], r)
        check("broken 空", r['broken'] == [], r['broken'])
        check("untrusted 空", r['untrusted'] == [], r['untrusted'])
        check("SCRIPTS 注册了 p_ok", 'p_ok' in SCRIPTS)
        info = plugin_loader.get_plugin('com.example.ok')
        check("layer 记录 = player", info and info['layer'] == 'player',
              info and info['layer'])
        check("kind = standard", info and info['kind'] == 'standard')
        _cleanup()


# ============ 3. editor 层插件 + 封装收集不含 ============
def t_editor_layer_not_collected():
    with tempfile.TemporaryDirectory() as tmp:
        _plugin(tmp, 'editor', 'ed', manifest=_manifest({"id": "com.example.ed"}))
        r = plugin_loader.load_plugins(base=tmp)
        check("editor 插件 loaded", 'com.example.ed' in r['loaded'], r)
        info = plugin_loader.get_plugin('com.example.ed')
        check("layer 记录 = editor", info and info['layer'] == 'editor')
        made = plugin_loader.scan_player_plugins(base=tmp)
        check("封装收集不含 editor 层插件",
              all(m['id'] != 'com.example.ed' for m in made), made)
        _cleanup()


# ============ 4. 散文件被忽略 ============
def t_file_ignored():
    with tempfile.TemporaryDirectory() as tmp:
        _plugin(tmp, 'player', 'ok')
        _write(os.path.join(tmp, 'plugins', 'stray.txt'), '散乱文件')
        _write(os.path.join(tmp, 'plugins', 'stray.py'), 'print(1)')
        _write(os.path.join(tmp, 'plugins', 'player', 'stray.py'), 'print(1)')
        r = plugin_loader.load_plugins(base=tmp)
        check("散文件被忽略", r['loaded'] == ['com.example.ok']
              and r['broken'] == [], r)
        _cleanup()


# ============ 5. 清单缺失/必填字段 ============
def t_manifest_missing_required():
    with tempfile.TemporaryDirectory() as tmp:
        _write(os.path.join(tmp, 'plugins', 'player', 'nomanifest', 'extra.py'), 'x')
        r = plugin_loader.load_plugins(base=tmp)
        check("缺 plugin.json → broken",
              len(r['broken']) == 1 and r['broken'][0]['id'] == 'nomanifest'
              and r['broken'][0]['error'], r)
    for missing in ('id', 'name', 'version', 'entry'):
        with tempfile.TemporaryDirectory() as tmp:
            info = json.loads(_manifest())
            del info[missing]
            _plugin(tmp, 'player', 'miss', manifest=json.dumps(info, ensure_ascii=False))
            r = plugin_loader.load_plugins(base=tmp)
            check("缺必填字段 %s → broken" % missing,
                  len(r['broken']) == 1 and missing in r['broken'][0]['error'], r)
            _cleanup()


# ============ 6. 坏 JSON ============
def t_bad_json():
    with tempfile.TemporaryDirectory() as tmp:
        _plugin(tmp, 'player', 'badjson', manifest='{ 这是坏 json')
        r = plugin_loader.load_plugins(base=tmp)
        check("坏 JSON → broken", len(r['broken']) == 1
              and r['broken'][0]['id'] == 'badjson' and r['broken'][0]['error'], r)


# ============ 7. id 非法 ============
def t_bad_id():
    for bad_id in ('含 空格', 'com..evil', '中文id'):
        with tempfile.TemporaryDirectory() as tmp:
            _plugin(tmp, 'player', 'badid', manifest=_manifest({"id": bad_id}))
            r = plugin_loader.load_plugins(base=tmp)
            check("id 非法 %r → broken" % bad_id,
                  len(r['broken']) == 1 and 'id' in r['broken'][0]['error'], r)


# ============ 8. version 非法 ============
def t_bad_version():
    for bad_ver in ('1.0', 'abc'):
        with tempfile.TemporaryDirectory() as tmp:
            _plugin(tmp, 'player', 'badver', manifest=_manifest({"version": bad_ver}))
            r = plugin_loader.load_plugins(base=tmp)
            check("version 非法 %r → broken" % bad_ver,
                  len(r['broken']) == 1 and 'version' in r['broken'][0]['error'], r)


# ============ 9. entry 不存在/非法名 ============
def t_entry_missing_file():
    with tempfile.TemporaryDirectory() as tmp:
        _plugin(tmp, 'player', 'missfile', manifest=_manifest({"entry": "no_entry.py"}))
        r = plugin_loader.load_plugins(base=tmp)
        check("entry 指向不存在文件 → broken", len(r['broken']) == 1
              and '不存在' in r['broken'][0]['error'], r)


def t_bad_entry_name():
    for bad_entry in ('..\\evil.py', 'sub/x.py'):
        with tempfile.TemporaryDirectory() as tmp:
            _plugin(tmp, 'player', 'baden', manifest=_manifest({"entry": bad_entry}))
            r = plugin_loader.load_plugins(base=tmp)
            check("entry 非法 %r → broken" % bad_entry,
                  len(r['broken']) == 1 and 'entry' in r['broken'][0]['error'], r)


# ============ 10. 无 register / register 抛异常 ============
def t_no_register():
    with tempfile.TemporaryDirectory() as tmp:
        _plugin(tmp, 'player', 'noreg', entry=ENTRY_NO_REGISTER)
        r = plugin_loader.load_plugins(base=tmp)
        check("entry.py 无 register → broken", len(r['broken']) == 1
              and 'register' in r['broken'][0]['error'], r)


def t_register_boom():
    with tempfile.TemporaryDirectory() as tmp:
        _plugin(tmp, 'player', 'boom', entry=ENTRY_BOOM)
        _plugin(tmp, 'player', 'good', manifest=_manifest({"id": "com.example.good"}))
        r = plugin_loader.load_plugins(base=tmp)
        check("register 抛异常 → broken (boom=com.example.ok, RuntimeError)",
              len(r['broken']) == 1
              and r['broken'][0]['id'] == 'com.example.ok'
              and 'RuntimeError' in r['broken'][0]['error'], r['broken'])
        check("同目录另一插件照常 loaded", 'com.example.good' in r['loaded'], r)
        _cleanup()


# ============ 11. min_engine ============
def t_min_engine():
    with tempfile.TemporaryDirectory() as tmp:
        _plugin(tmp, 'player', 'future', manifest=_manifest({"min_engine": "99.0"}))
        r = plugin_loader.load_plugins(base=tmp)
        check("min_engine 99.0 → broken 含 '需要引擎'", len(r['broken']) == 1
              and '需要引擎' in r['broken'][0]['error'], r)
    with tempfile.TemporaryDirectory() as tmp:
        _plugin(tmp, 'player', 'low', manifest=_manifest({"min_engine": "0.1"}))
        r = plugin_loader.load_plugins(base=tmp)
        check("min_engine 0.1 → 正常 loaded", 'com.example.ok' in r['loaded']
              and r['broken'] == [], r)
        _cleanup()
    _old_ver = plugin_loader.CURRENT_VERSION
    plugin_loader.CURRENT_VERSION = '1.0.0.beta2'
    check("beta 引擎版本下 min_engine 1.0 → 放行", plugin_loader._engine_ok('1.0'))
    check("beta 引擎版本下 min_engine 2.0 → 跳过", not plugin_loader._engine_ok('2.0'))
    plugin_loader.CURRENT_VERSION = _old_ver


# ============ 12. 重复 id ============
def t_duplicate_id():
    with tempfile.TemporaryDirectory() as tmp:
        _plugin(tmp, 'player', 'aaa_first')
        _plugin(tmp, 'player', 'bbb_second')   # 同 id, 第二个 broken
        r = plugin_loader.load_plugins(base=tmp)
        check("重复 id → 第二个 broken 含 '重复'", len(r['broken']) == 1
              and '重复' in r['broken'][0]['error'] and len(r['loaded']) == 1, r)
        _cleanup()


# ============ 13. 未开放扩展点记 pending ============
def t_pending_ext():
    with tempfile.TemporaryDirectory() as tmp:
        _plugin(tmp, 'player', 'menu', manifest=_manifest({"id": "com.example.menu"}),
                entry=ENTRY_MENU)
        r = plugin_loader.load_plugins(base=tmp)
        apis = plugin_loader.get_loaded()
        ok = (r['loaded'] == ['com.example.menu'] and r['broken'] == []
              and apis['com.example.menu']['api'].pending)
        check("未开放扩展点 → loaded 不崩 + pending 非空", ok, r)
        _cleanup()


# ============ 14. register_script 无 script_id ============
def t_no_script_id():
    with tempfile.TemporaryDirectory() as tmp:
        _plugin(tmp, 'player', 'nosid', manifest=_manifest({"id": "com.example.nosid"}),
                entry=ENTRY_NO_SID)
        r = plugin_loader.load_plugins(base=tmp)
        check("register_script 无 script_id → broken", len(r['broken']) == 1
              and r['broken'][0]['id'] == 'com.example.nosid', r)


# ============ 15. 返回结构 ============
def t_return_structure():
    with tempfile.TemporaryDirectory() as tmp:
        _plugin(tmp, 'player', 'struct_bad', manifest='{坏json')
        _plugin(tmp, 'player', 'ok')
        r = plugin_loader.load_plugins(base=tmp)
        check("返回结构 {loaded,broken,untrusted}",
              isinstance(r, dict) and set(r.keys()) == {'loaded', 'broken', 'untrusted'}
              and r['loaded'] == ['com.example.ok'], r)
        _cleanup()


# ============ 16. 卸载: deactivate + 清理 ============
def t_unload():
    with tempfile.TemporaryDirectory() as tmp:
        _plugin(tmp, 'player', 'deact', manifest=_manifest({"id": "com.example.deact"}),
                entry=ENTRY_DEACT)
        r = plugin_loader.load_plugins(base=tmp)
        check("卸载前: 已加载 + 脚本已注册", 'com.example.deact' in r['loaded']
              and 'p_deact' in SCRIPTS)
        mod = plugin_loader.get_plugin('com.example.deact')['mod']
        ok, err = plugin_loader.unload_plugin('com.example.deact')
        check("unload_plugin 成功", ok, err)
        check("deactivate 钩子被调用", mod.GOT._deactivated)
        check("脚本已清理", 'p_deact' not in SCRIPTS)
        check("_LOADED 已移除", plugin_loader.get_plugin('com.example.deact') is None)
        ok2, err2 = plugin_loader.unload_plugin('com.example.deact')
        check("重复卸载返回失败不崩", (not ok2) and err2)


# ============ 17. 幂等 ============
def t_idempotent():
    with tempfile.TemporaryDirectory() as tmp:
        _plugin(tmp, 'player', 'ok')
        r1 = plugin_loader.load_plugins(base=tmp)
        check("首次加载成功", 'com.example.ok' in r1['loaded'])
        if 'p_ok' in SCRIPTS:
            del SCRIPTS['p_ok']
        r2 = plugin_loader.load_plugins(base=tmp)
        check("二次加载幂等: loaded=[]", r2 == {'loaded': [], 'broken': [], 'untrusted': []}, r2)
        check("二次加载不重新注册脚本", 'p_ok' not in SCRIPTS)
        _cleanup()


# ============ 18. 重扫: 删目录即卸载 ============
def t_rescan_unload_missing():
    with tempfile.TemporaryDirectory() as tmp:
        _plugin(tmp, 'player', 'rscan', manifest=_manifest({"id": "com.example.rescan"}))
        r = plugin_loader.load_plugins(base=tmp)
        check("重扫前已加载", 'com.example.rescan' in r['loaded'])
        plugin_loader.rescan_plugins(base=tmp)
        check("目录在: rescan 不卸载", _loaded_has('com.example.rescan'))
        shutil.rmtree(os.path.join(tmp, 'plugins', 'player', 'rscan'))
        plugin_loader.rescan_plugins(base=tmp)
        check("目录删: _LOADED 移除", not _loaded_has('com.example.rescan'))
        check("目录删: 脚本已清理", 'p_ok' not in SCRIPTS)
        _cleanup()


def _loaded_has(pid):
    return plugin_loader.get_plugin(pid) is not None


# ============ 19. 手动卸载=会话禁用, load_plugin 恢复 ============
def t_disable_reload():
    with tempfile.TemporaryDirectory() as tmp:
        _plugin(tmp, 'player', 'dis', manifest=_manifest({"id": "com.example.dis"}))
        r = plugin_loader.load_plugins(base=tmp)
        check("加载成功", 'com.example.dis' in r['loaded'])
        plugin_loader.unload_plugin('com.example.dis')
        check("卸载后脚本清理", 'p_ok' not in SCRIPTS)
        plugin_loader.rescan_plugins(base=tmp)
        check("禁用中 rescan 不重载", not _loaded_has('com.example.dis'))
        plugin_loader.load_plugin('com.example.dis', base=tmp)
        check("load_plugin 恢复加载",
              _loaded_has('com.example.dis') and 'p_ok' in SCRIPTS)
        _cleanup()


# ============ 20. 程序目录解析不依赖 cwd ============
def t_cwd_independent():
    LOOM = os.path.dirname(HERE)
    saved = os.getcwd()
    try:
        os.chdir(tempfile.gettempdir())
        check("plugin_dir('loom') 不随 cwd: 指向 Loom\\plugins",
              plugin_loader.plugin_dir('loom') == os.path.join(LOOM, 'plugins'),
              plugin_loader.plugin_dir('loom'))
        check("plugin_dir('player') = Loom\\plugins\\player",
              plugin_loader.plugin_dir('player') == os.path.join(LOOM, 'plugins', 'player'))
        r = plugin_loader.load_plugins()
        check("任意 cwd 下 load_plugins 正常返回结构",
              isinstance(r, dict) and set(r.keys()) == {'loaded', 'broken', 'untrusted'}, r)
    finally:
        os.chdir(saved)


# ============ 21. 受限环境: 黑名单 import 拒绝 ============
def t_restricted_banned_import():
    with tempfile.TemporaryDirectory() as tmp:
        _plugin(tmp, 'player', 'badimp', manifest=_manifest({"id": "com.example.badimp"}),
                entry=ENTRY_IMPORT_OS)
        r = plugin_loader.load_plugins(base=tmp)
        check("editor 模式 import os → broken 含 '受限'",
              len(r['broken']) == 1 and '受限' in r['broken'][0]['error'],
              r['broken'])
        _cleanup()


# ============ 22. 受限: 无 open / exec / 动态拼接名 ============
def t_restricted_builtins_blocked():
    for name, entry, frag in (('open', ENTRY_USE_OPEN, 'NameError'),
                              ('exec', ENTRY_USE_EXEC, 'NameError'),
                              ('dynamic', ENTRY_DYNAMIC_IMPORT, '受限')):
        with tempfile.TemporaryDirectory() as tmp:
            _plugin(tmp, 'player', 'rb', manifest=_manifest({"id": "com.example.rb_%s" % name}),
                    entry=entry)
            r = plugin_loader.load_plugins(base=tmp)
            check("受限: 使用%s → broken 含 %s" % (name, frag),
                  len(r['broken']) == 1 and frag in r['broken'][0]['error'],
                  r['broken'])
            _cleanup()


# ============ 23. 受限: 白名单放行 (纯标准库计算模块) ============
def t_restricted_whitelist_ok():
    with tempfile.TemporaryDirectory() as tmp:
        _plugin(tmp, 'player', 'wl', manifest=_manifest({"id": "com.example.wl"}),
                entry=ENTRY_WHITELIST)
        r = plugin_loader.load_plugins(base=tmp)
        check("白名单 import math/re/json → 正常 loaded + 脚本注册",
              r['loaded'] == ['com.example.wl'] and 'p_math' in SCRIPTS, r)
        _cleanup()


# ============ 23b. 受限: 引擎 SDK 模块也禁 (2026-08-28 靶场 V04/V07 回归) ============
def t_restricted_sdk_module_banned():
    """渗透靶场实锤: import engine → engine.os.open 直接写任意文件 (V04);
    engine.np.savetxt 写文件 (V07)。两个模块的命名空间真实含 os/sys/np,
    必须从白名单移除 —— 移除后: 受限插件 import engine / from scripts
    import Script 一律 ImportError (broken 含 '受限')。"""
    for vid, entry in (('eng', "import engine\ndef register(api):\n    pass\n"),
                       ('scr', "from scripts import Script\n"
                               "def register(api):\n    pass\n"),
                       ('mk', "__import__('engine')\ndef register(api):\n    pass\n")):
        with tempfile.TemporaryDirectory() as tmp:
            _plugin(tmp, 'player', vid, manifest=_manifest(
                {"id": "com.example.sdk_%s" % vid}), entry=entry)
            r = plugin_loader.load_plugins(base=tmp)
            check("受限: import %s → broken 含 '受限'" % vid,
                  len(r['broken']) == 1 and '受限' in r['broken'][0]['error'],
                  [b['error'] for b in r['broken']])
            _cleanup()


# ============ 23c. 受限沙箱内核自检 (V06 面必须榨无可榨) ============
def t_restricted_sandbox_clean():
    import plugin_sandbox as _sb
    check("沙箱命名空间无模块对象/无 __builtins__ (V06 面榨无可榨)",
          _sb.sandbox_globals_clean() is True,
          [k for k, v in vars(_sb).items() if k == '__builtins__'
           or (hasattr(type(v), '__name__') and type(v).__name__ == 'module')])
    # 触发一次受限加载后仍干净 (pop 幂等)
    with tempfile.TemporaryDirectory() as tmp:
        _plugin(tmp, 'player', 'ok')
        plugin_loader.load_plugins(base=tmp)
        _cleanup()
    check("受限加载后沙箱仍干净", _sb.sandbox_globals_clean() is True)


# ============ 23d. 受限: V06 最短逃逸回归 (__import__.__globals__) ============
def t_restricted_v06_shortcut():
    """靶场 V06 实锤路径: 修复前 __import__.__globals__ 直接是 plugin_loader
    命名空间 (含 os) 或保底 $_builtins$ (真 open)。修复后: 沙箱函数定义在
    plugin_sandbox, 且 __builtins__/模块对象已被剥离 —— entry 断言 leak 为空,
    一旦未来改动复活该面, 本用例直接 broken。"""
    # 直写形态 (修复前一行写出文件): AST 层直接拒载 —— 连运行都到不了
    entry_plain = ("# -*- coding: utf-8 -*-\n"
                   "def register(api):\n"
                   "    __import__.__globals__['os']\n")
    with tempfile.TemporaryDirectory() as tmp:
        _plugin(tmp, 'player', 'v06', manifest=_manifest({"id": "com.example.v06"}),
                entry=entry_plain)
        r = plugin_loader.load_plugins(base=tmp)
        check("受限 AST 拒载 `.__globals__` 直写 (V06 形态 1)",
              len(r['broken']) == 1 and 'AST' in r['broken'][0]['error'],
              [b['error'] for b in r['broken']])
        _cleanup()
    # 形态 2: 白名单纯 stdlib 模块的 __dict__['__builtins__'] (模块 dict 自动带
    # 真 builtins 键) —— 直写形态被 AST 拒载 (.__dict__ 在黑面)
    entry_dict = ("# -*- coding: utf-8 -*-\n"
                  "def register(api):\n"
                  "    import math\n"
                  "    math.__dict__['__builtins__']['open']('x.txt', 'w')\n")
    with tempfile.TemporaryDirectory() as tmp:
        _plugin(tmp, 'player', 'v06b', manifest=_manifest({"id": "com.example.v06b"}),
                entry=entry_dict)
        r = plugin_loader.load_plugins(base=tmp)
        check("受限 AST 拒载 `.__dict__['__builtins__']` 直写 (模块字典渗点)",
              len(r['broken']) == 1 and 'AST' in r['broken'][0]['error'],
              [b['error'] for b in r['broken']])
        _cleanup()


# ============ 23e. 受限: AST 元编程黑面拦截 (V05 向量直写拒载) ============
def t_restricted_ast_v05_blocked():
    """靶场 V05 实锤路径的**直接书写**形态必须被 AST 拒载 (broken 含 'AST'):
    `().__class__.__base__.__subclasses__()` / `__import__.__globals__['os']`
    这些在修复前一行写出文件。绕 AST (混淆) 仍可写, 属"门禁非沙箱"档位。"""
    vectors = (
        ('subcls', "def register(api):\n"
                   "    [c for c in ().__class__.__base__.__subclasses__()]\n"),
        ('globals_os', "def register(api):\n"
                       "    __import__.__globals__['os']\n"),
        ('builtins_of', "def register(api):\n"
                        "    __import__.__globals__['__builtins__']['open']\n"),
    )
    for vid, entry in vectors:
        with tempfile.TemporaryDirectory() as tmp:
            _plugin(tmp, 'player', vid, manifest=_manifest(
                {"id": "com.example.v05_%s" % vid}), entry=entry)
            r = plugin_loader.load_plugins(base=tmp)
            check("受限 AST 拦截: %s → broken 含 'AST'" % vid,
                  len(r['broken']) == 1 and 'AST' in r['broken'][0]['error'],
                  [b['error'] for b in r['broken']])
            _cleanup()


# ============ 23f. 受限: 白名单模块收窄 + 运行时快检 (二轮复扫回归) ============
def t_restricted_whitelist_narrowed():
    """二轮复扫实锤: dataclasses/typing 命名空间**直挂 sys** (m05 纯语法
    释放文件), 已移出白名单; 快检兜底 stdlib 漂移 (未来版本白名单模块
    直挂 os/sys 也拒载)."""
    for vid, entry, frag in (
        ('dt', "import dataclasses\ndef register(api):\n    pass\n", 'dataclasses'),
        ('ty', "import typing\ndef register(api):\n    pass\n", 'typing'),
    ):
        with tempfile.TemporaryDirectory() as tmp:
            _plugin(tmp, 'player', vid, manifest=_manifest(
                {"id": "com.example.wl_%s" % vid}), entry=entry)
            r = plugin_loader.load_plugins(base=tmp)
            check("受限: import %s → broken 含 '受限' (已移出白名单)" % vid,
                  len(r['broken']) == 1 and '受限' in r['broken'][0]['error'],
                  [b['error'] for b in r['broken']])
            _cleanup()
    # 保留的白名单模块仍放行 (math/re/...), 且运行时"无危险直挂"断言
    with tempfile.TemporaryDirectory() as tmp:
        _plugin(tmp, 'player', 'wl2', manifest=_manifest({"id": "com.example.wl2"}),
                entry=ENTRY_WHITELIST)
        r = plugin_loader.load_plugins(base=tmp)
        check("保留白名单 math/re/json 仍放行", r['loaded'] == ['com.example.wl2'], r)
        _cleanup()


# ============ 23g. 受限: 检索原语不存在 (二轮复扫 P0 收口) ============
def t_restricted_retrievers_removed():
    """二轮复扫实锤: 受限 builtins 保留 getattr/vars/globals -> 别名化/
    下标/闭包默认参可绕 AST (m06-m08)。现已**全部移除** —— 直用即
    NameError; 复扫报告的三种变换族形态一并断言. 正常插件零依赖。"""
    vectors = (
        ('alias', "def register(api):\n    g = getattr\n"),
        ('subscript', "def register(api):\n    f = {'h': vars}['h']\n"),
        ('closure', "def register(api):\n    def h(g=globals):\n        return g\n"),
        ('direct_vars', "def register(api):\n    vars('x')\n"),
    )
    for vid, entry in vectors:
        with tempfile.TemporaryDirectory() as tmp:
            _plugin(tmp, 'player', vid, manifest=_manifest(
                {"id": "com.example.ret_%s" % vid}), entry=entry)
            r = plugin_loader.load_plugins(base=tmp)
            # 两层防护先撞哪层都得拦: 直写形态 → AST 拒 (retriever);
            # 躲过 AST 的形态 ("g = getattr" 赋值) → 受限 builtins 无此名
            # NameError。两者皆可证"检索原语已不可用"。
            check("受限: %s 检索原语不可用 (AST 拒 或 NameError)" % vid,
                  len(r['broken']) == 1 and
                  ('NameError' in r['broken'][0]['error']
                   or 'AST' in r['broken'][0]['error']),
                  [b['error'] for b in r['broken']])
            _cleanup()


# ============ 24. 受限: read_asset 正常读 + 越界拒 ============
def t_restricted_read_asset():
    with tempfile.TemporaryDirectory() as tmp:
        _plugin(tmp, 'player', 'ast', manifest=_manifest({"id": "com.example.ast"}),
                entry=ENTRY_ASSET)
        _write(os.path.join(tmp, 'plugins', 'player', 'ast', 'data.txt'), 'hello')
        r = plugin_loader.load_plugins(base=tmp)
        check("read_asset 读包内资源 OK + 越界被拒 (register 内断言)",
              r['loaded'] == ['com.example.ast'] and r['broken'] == [], r)
        _cleanup()


# ============ 25. player mode = 全权 (import os 放行) ============
def t_player_mode_full():
    with tempfile.TemporaryDirectory() as tmp:
        plugin_loader.set_mode('player')
        try:
            _plugin(tmp, 'player', 'full', manifest=_manifest({"id": "com.example.full"}),
                    entry=ENTRY_IMPORT_OS_FULL)
            r = plugin_loader.load_plugins(base=tmp)
            check("player mode: import os 全权放行 → loaded",
                  r['loaded'] == ['com.example.full'] and r['broken'] == [], r)
            _cleanup()
        finally:
            plugin_loader.set_mode('editor')


def t_mode_invalid():
    try:
        plugin_loader.set_mode('bad')
        check("set_mode('bad') → ValueError", False)
    except ValueError:
        check("set_mode('bad') → ValueError", True)


# ============ 26. 跨层按钮注册 + 卸载清理 ============
def t_editor_button():
    with tempfile.TemporaryDirectory() as tmp:
        _plugin(tmp, 'player', 'btn', manifest=_manifest({"id": "com.example.btn"}),
                entry=ENTRY_BUTTON)
        r = plugin_loader.load_plugins(base=tmp)
        btns = plugin_loader.editor_buttons()
        check("player 插件注册按钮 → 注册表含 '测试按钮'",
              r['loaded'] == ['com.example.btn']
              and any(b[0] == '测试按钮' and b[2] == 'com.example.btn' for b in btns), btns)
        cb = [b[1] for b in btns if b[0] == '测试按钮'][0]
        check("按钮回调可调用", cb() == 'clicked')
        plugin_loader.unload_plugin('com.example.btn')
        check("卸载后按钮清理",
              not any(b[2] == 'com.example.btn' for b in plugin_loader.editor_buttons()))
        _cleanup()


# ============ 27. 核心插件: 未信任不加载 ============
def t_core_untrusted():
    with tempfile.TemporaryDirectory() as tmp:
        _core(tmp, 'render', 'ker')
        r = plugin_loader.load_plugins(base=tmp)
        check("核心插件未信任 → 不入 loaded", r['loaded'] == [], r)
        check("broken 空 (待信任不等于坏)", r['broken'] == [], r['broken'])
        check("untrusted 1 项 + state=untrusted",
              len(r['untrusted']) == 1
              and r['untrusted'][0]['id'] == 'com.example.ok'
              and r['untrusted'][0]['state'] == 'untrusted', r['untrusted'])
        check("未信任不注册脚本", 'p_ok' not in SCRIPTS)
        _cleanup()


# ============ 28. 核心: 确认信任 → 重启后生效 ============
def t_core_confirm_then_reload():
    with tempfile.TemporaryDirectory() as tmp:
        _core(tmp, 'render', 'ker')
        r = plugin_loader.load_plugins(base=tmp)
        check("确认前未加载", r['loaded'] == [])
        d = os.path.join(tmp, 'core_plugins', 'render', 'ker')
        ok = plugin_loader.confirm_core_trust('com.example.ok', d, base=tmp)
        check("confirm_core_trust 写信任表成功", ok)
        r2 = plugin_loader.load_plugins(base=tmp)
        check("确认后重扫 → 已加载 (重启生效语义: 本次已加载)",
              r2['loaded'] == ['com.example.ok'], r2)
        info = plugin_loader.get_plugin('com.example.ok')
        check("核心 layer 来自清单 (player) + kind=core",
              info and info['layer'] == 'player' and info['kind'] == 'core')
        check("脚本已注册", 'p_ok' in SCRIPTS)
        check("untrusted 空", r2['untrusted'] == [], r2['untrusted'])
        _cleanup()


# ============ 29. 核心: 文件被改 → modified → 拒载重确认 ============
def t_core_modified():
    with tempfile.TemporaryDirectory() as tmp:
        _core(tmp, 'render', 'ker')
        d = os.path.join(tmp, 'core_plugins', 'render', 'ker')
        plugin_loader.confirm_core_trust('com.example.ok', d, base=tmp)
        # 改写入口文件 → 指纹变化
        _write(os.path.join(d, 'entry.py'), ENTRY_DEACT)
        r = plugin_loader.load_plugins(base=tmp)
        check("被改 → state=modified 拒载", len(r['untrusted']) == 1
              and r['untrusted'][0]['state'] == 'modified'
              and r['loaded'] == [], r['untrusted'])
        check("被改后不注册脚本", 'p_deact' not in SCRIPTS)
        # 重新确认 → 恢复
        ok = plugin_loader.confirm_core_trust('com.example.ok', d, base=tmp)
        r2 = plugin_loader.load_plugins(base=tmp)
        check("重确认后恢复加载", ok and 'com.example.ok' in r2['loaded']
              and 'p_deact' in SCRIPTS, r2)
        _cleanup()


# ============ 30. 核心清单更严: 缺 layer/capability/desc → broken ============
def t_core_strict_manifest():
    # (manifest 构造函数, 期望 broken 前缀)
    builders = (
        (lambda i: i.update({"layer": "core"}), 'layer'),
        (lambda i: i.update({"capability": "", "desc": "x"}), 'capability'),
        (lambda i: i.update({"capability": "render", "desc": " "}), 'desc'),
        (lambda i: i.pop("layer", None), 'layer'),
        (lambda i: i.pop("desc", None), 'desc'),
    )
    for mutate, frag in builders:
        with tempfile.TemporaryDirectory() as tmp:
            info = json.loads(_core_manifest())
            mutate(info)
            _core(tmp, 'render', 'strict',
                  manifest=json.dumps(info, ensure_ascii=False))
            r = plugin_loader.load_plugins(base=tmp)
            check("核心 %s 问题 → broken 含 %s" % (frag, frag),
                  len(r['broken']) == 1 and frag in r['broken'][0]['error'],
                  r['broken'])


# ============ 31. 核心: 信任表坏文件不崩 ============
def t_trust_file_corrupt():
    with tempfile.TemporaryDirectory() as tmp:
        _write(os.path.join(tmp, '插件信任.json'), '{ 坏 json')
        _core(tmp, 'render', 'ker')
        r = plugin_loader.load_plugins(base=tmp)
        check("信任表坏 json → 视为无记录, untrusted 不崩",
              len(r['untrusted']) == 1 and r['loaded'] == [], r)
        _cleanup()


# ============ 32. 封装收集: player 普通 + 核心 player; editor 不进 ============
def t_scan_player_plugins():
    with tempfile.TemporaryDirectory() as tmp:
        _plugin(tmp, 'player', 'ok')                                       # player 普通
        _plugin(tmp, 'editor', 'ed', manifest=_manifest({"id": "com.example.ed"}))
        _core(tmp, 'render', 'ker')                                        # layer=player 核心
        _core(tmp, 'render', 'ed_core',
              manifest=_core_manifest(layer="editor"))                     # editor 核心
        made = plugin_loader.scan_player_plugins(base=tmp)
        ids = sorted(m['id'] for m in made)
        kinds = {m['id']: m['kind'] for m in made}
        check("收集 = player 普通 + 核心 player (不含 editor 两例)",
              ids == ['com.example.ok'], made)
        check("kind 分别 standard", kinds.get('com.example.ok') == 'standard')
        check("核心 player layer 正确",
              [m['kind'] for m in made] == ['standard'], [kinds.get(m['id']) for m in made])


def t_scan_player_plugins_core():
    with tempfile.TemporaryDirectory() as tmp:
        _core(tmp, 'render', 'ker')
        _core(tmp, 'physics', 'ph', manifest=_core_manifest(layer="player"))
        made = plugin_loader.scan_player_plugins(base=tmp)
        check("收集含核心插件 (layer=player) + kind=core",
              sorted(m['id'] for m in made) == ['com.example.ok']
              and all(m['kind'] == 'core' for m in made), made)


# ============ 33. 内存包加载 (玩家端, 全权) ============
def t_plugin_from_pack():
    import plugin_loader as pl
    info = json.loads(_manifest())
    info.update({"id": "com.example.pack", "layer": "player",
                 "capability": "render", "desc": "包内插件"})
    api, mod = pl.load_plugin_from_pack('com.example.pack', ENTRY_WHITELIST,
                                        {}, info, 'player')
    check("内存包加载: 脚本注册进 SCRIPTS", 'p_math' in SCRIPTS)
    check("返回 api 带 info/layer", api.info['id'] == 'com.example.pack'
          and api.layer == 'player')
    check("模块独立命名不冲突", mod.__name__.startswith('loom_gameplugin_'))
    _cleanup()


# ============ 34. 核心插件缺 layer 在 scan_player_plugins 被跳过 ============
def t_core_scan_strict():
    with tempfile.TemporaryDirectory() as tmp:
        info = json.loads(_core_manifest())
        del info['layer']
        _core(tmp, 'render', 'strict', manifest=json.dumps(info, ensure_ascii=False))
        made = plugin_loader.scan_player_plugins(base=tmp)
        check("核心缺 layer → 收集跳过 (清单非法)", made == [], made)


if __name__ == "__main__":
    print("========== Loom 插件加载器测试 (L1 分级) ==========")
    _cleanup()
    t_no_plugins_dir()
    t_valid_plugin_player()
    t_editor_layer_not_collected()
    t_file_ignored()
    t_manifest_missing_required()
    t_bad_json()
    t_bad_id()
    t_bad_version()
    t_entry_missing_file()
    t_bad_entry_name()
    t_no_register()
    t_register_boom()
    t_min_engine()
    t_restricted_sdk_module_banned()
    t_restricted_sandbox_clean()
    t_restricted_v06_shortcut()
    t_restricted_ast_v05_blocked()
    t_restricted_whitelist_narrowed()
    t_restricted_retrievers_removed()
    t_duplicate_id()
    t_pending_ext()
    t_no_script_id()
    t_return_structure()
    t_unload()
    t_idempotent()
    t_rescan_unload_missing()
    t_disable_reload()
    t_cwd_independent()
    t_restricted_banned_import()
    t_restricted_builtins_blocked()
    t_restricted_whitelist_ok()
    t_restricted_read_asset()
    t_player_mode_full()
    t_mode_invalid()
    t_editor_button()
    t_core_untrusted()
    t_core_confirm_then_reload()
    t_core_modified()
    t_core_strict_manifest()
    t_trust_file_corrupt()
    t_scan_player_plugins()
    t_scan_player_plugins_core()
    t_plugin_from_pack()
    t_core_scan_strict()
    _cleanup()
    if _FAILS:
        print("总结果: FAIL ❌", _FAILS)
        sys.exit(1)
    print("总结果: ALL PASS ✅")
    print("全部通过")
