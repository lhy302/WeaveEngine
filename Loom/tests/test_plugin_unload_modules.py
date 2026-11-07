# -*- coding: utf-8 -*-

"""
test_plugin_unload_modules.py — 插件卸载清理 sys.modules 回归 (scan_09 P-10)

背景 (审计 docs/audit/scan_09_scripting.md P-10)
------------------------------------------------
plugin_loader 加载插件时把模块写进 sys.modules[mod_name] (受限/全权两条路径
都写), 但 unload_plugin 只清 SCRIPTS / 工具栏按钮 / _LOADED, **从不摘模块**。
于是插件卸载后代码与 globals 仍被解释器缓存: import loom_plugin_xxx 仍命中
已卸载插件; 插件目录改名/升级导致 id 变化时模块无界累积 (热重载表现为
"旧插件常驻")。

本文件断言修复后的行为:
  A: 正常加载 -> sys.modules 有该模块; 卸载 -> 该模块被摘除, 注册脚本也清掉。
  B: 只摘自己那份: 若 sys.modules 里的同名条目已被别的模块对象替换,
     卸载不得误删它; 系统模块 (os/sys/json/importlib) 与其他插件模块不受影响。
  C: rescan 发现目录已消失时走 unload_plugin(disable=False), 模块同样被摘除。
  D: 手动卸载 (disable=True) 后重新 load_plugin -> 得到**新**模块对象,
     证明旧模块没有以缓存形式复活。

运行: python tests\test_plugin_unload_modules.py   (无头, 无 GPU)
"""
import sys as _sys_utf8
try:
    _sys_utf8.stdout.reconfigure(encoding='utf-8', errors='replace')
    _sys_utf8.stderr.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

import json
import os
import shutil
import sys
import tempfile
import types

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))            # Loom\

import plugin_loader
from scripts import SCRIPTS

_FAILS = []
_PREFIX = 'loom_plugin_probe_unload'


def check(name, cond, extra=""):
    print(("PASS " if cond else "FAIL ") + name + ("  " + str(extra) if extra else ""))
    if not cond:
        _FAILS.append(name)


def _write(path, content):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        f.write(content)


def _manifest(pid):
    return json.dumps({"id": pid, "name": "卸载模块测试", "version": "0.1.0",
                       "entry": "entry.py"}, ensure_ascii=False)


def _plugin(tmp, name, pid, entry_src):
    d = os.path.join(tmp, 'plugins', 'player', name)
    _write(os.path.join(d, 'plugin.json'), _manifest(pid))
    _write(os.path.join(d, 'entry.py'), entry_src)
    return d


def _cleanup():
    for pid in list(plugin_loader._LOADED):
        plugin_loader.unload_plugin(pid, disable=False)
    plugin_loader._DISABLED.clear()
    plugin_loader._EDITOR_BUTTONS[:] = []
    for sid in list(SCRIPTS):
        if sid.startswith('probe_unload'):
            del SCRIPTS[sid]
    for m in list(sys.modules):
        if m.startswith(_PREFIX):
            sys.modules.pop(m, None)


ENTRY_A = """# -*- coding: utf-8 -*-
class A:
    script_id = 'probe_unload_a'
    name = '卸载测试A'


def register(api):
    api.register_script(A)
"""

ENTRY_B = """# -*- coding: utf-8 -*-
class B:
    script_id = 'probe_unload_b'
    name = '卸载测试B'


def register(api):
    api.register_script(B)
"""


# ====================================================================
# A: 加载 -> 卸载, 模块被摘除
# ====================================================================
def t_unload_removes_module():
    _cleanup()
    tmp = tempfile.mkdtemp()
    _plugin(tmp, 'a', 'probe.unload.a', ENTRY_A)
    mod_name = _PREFIX + '_a'
    r = plugin_loader.load_plugins(base=tmp)
    entry = plugin_loader.get_plugin('probe.unload.a')
    check("[A] 插件正常加载", r['loaded'] == ['probe.unload.a'] and entry is not None, r)
    check("[A] 加载后模块在 sys.modules 且是本次加载的对象",
          sys.modules.get(mod_name) is entry['mod'], mod_name)
    ok, err = plugin_loader.unload_plugin('probe.unload.a', disable=False)
    check("[A] 卸载成功", ok, err)
    check("[A] 卸载后模块已从 sys.modules 摘除", mod_name not in sys.modules,
          mod_name)
    check("[A] 卸载后注册脚本已清掉", 'probe_unload_a' not in SCRIPTS)
    _cleanup()


# ====================================================================
# B: 只摘自己那份; 系统模块/其他插件不受影响
# ====================================================================
def t_unload_only_own_module():
    _cleanup()
    tmp = tempfile.mkdtemp()
    _plugin(tmp, 'a', 'probe.unload.a', ENTRY_A)
    _plugin(tmp, 'b', 'probe.unload.b', ENTRY_B)
    r = plugin_loader.load_plugins(base=tmp)
    check("[B] 两个插件都加载", sorted(r['loaded']) ==
          ['probe.unload.a', 'probe.unload.b'], r)
    mod_a = _PREFIX + '_a'
    mod_b = _PREFIX + '_b'
    system_before = {name: sys.modules.get(name) for name in
                     ('os', 'sys', 'json', 'importlib', 'hashlib')}
    check("[B] 前置: 两个模块都在", mod_a in sys.modules and mod_b in sys.modules)

    # 模拟"同名条目被别人替换": 卸载时不得误删非本次加载的模块对象
    foreign = types.ModuleType(mod_b)
    sys.modules[mod_b] = foreign
    ok, err = plugin_loader.unload_plugin('probe.unload.b', disable=False)
    check("[B] 卸载 B 成功", ok, err)
    check("[B] 同名条目被替换时, 卸载不误删它", sys.modules.get(mod_b) is foreign,
          sys.modules.get(mod_b))

    ok2, err2 = plugin_loader.unload_plugin('probe.unload.a', disable=False)
    check("[B] 卸载 A 成功", ok2, err2)
    check("[B] 自己的模块被摘除", mod_a not in sys.modules)
    check("[B] 系统模块对象全部未被替换/删除",
          all(sys.modules.get(k) is v for k, v in system_before.items()),
          {k: sys.modules.get(k) is v for k, v in system_before.items()})
    sys.modules.pop(mod_b, None)
    _cleanup()


# ====================================================================
# C: rescan 清理目录已消失的插件
# ====================================================================
def t_rescan_dir_gone_removes_module():
    _cleanup()
    tmp = tempfile.mkdtemp()
    d = _plugin(tmp, 'a', 'probe.unload.a', ENTRY_A)
    mod_name = _PREFIX + '_a'
    r = plugin_loader.load_plugins(base=tmp)
    check("[C] 前置: 加载成功", r['loaded'] == ['probe.unload.a'] and
          mod_name in sys.modules, r)
    shutil.rmtree(d)
    plugin_loader.rescan_plugins(base=tmp)
    check("[C] 目录消失后插件移出 _LOADED",
          plugin_loader.get_plugin('probe.unload.a') is None)
    check("[C] 目录消失后模块被摘除", mod_name not in sys.modules, mod_name)
    _cleanup()


# ====================================================================
# D: 手动卸载后重新加载 -> 新模块对象 (旧缓存不复活)
# ====================================================================
def t_reload_is_fresh_module():
    _cleanup()
    tmp = tempfile.mkdtemp()
    _plugin(tmp, 'a', 'probe.unload.a', ENTRY_A)
    mod_name = _PREFIX + '_a'
    plugin_loader.load_plugins(base=tmp)
    old_mod = sys.modules.get(mod_name)
    ok, err = plugin_loader.unload_plugin('probe.unload.a')   # disable=True
    check("[D] 手动卸载成功", ok and 'probe.unload.a' in plugin_loader._DISABLED,
          err)
    check("[D] 手动卸载也摘模块", mod_name not in sys.modules)
    r2 = plugin_loader.load_plugin('probe.unload.a', base=tmp)
    new_mod = sys.modules.get(mod_name)
    check("[D] 重新加载成功", r2['loaded'] == ['probe.unload.a'], r2)
    check("[D] 重新加载得到新模块对象 (不是旧缓存)",
          new_mod is not None and new_mod is not old_mod,
          (new_mod, old_mod))
    _cleanup()


if __name__ == "__main__":
    print("========== 插件卸载清理 sys.modules (scan_09 P-10) ==========")
    _cleanup()
    t_unload_removes_module()
    t_unload_only_own_module()
    t_rescan_dir_gone_removes_module()
    t_reload_is_fresh_module()
    _cleanup()
    print()
    if _FAILS:
        print("总结果: FAIL ❌", _FAILS)
        sys.exit(1)
    print("总结果: ALL PASS ✅")
