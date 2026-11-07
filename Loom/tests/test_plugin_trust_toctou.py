# -*- coding: utf-8 -*-

"""
test_plugin_trust_toctou.py — 核心插件信任闸 hash→exec TOCTOU 回归 (scan_09 P-03)

背景 (审计 docs/audit/scan_09_scripting.md P-03)
------------------------------------------------
核心插件契约: "安装须信任确认 + 全文件 SHA256 校验; 未信任/被改过 = 不加载"。
修复前 _try_scan_folder 先 core_trust_state 对目录算 SHA256, 之后 _load_one
再 open(entry) 交给 SourceFileLoader.exec_module 重新读盘 —— 两次读取之间
文件可被替换: 被哈希的是 benign, 被执行的是 malicious, 信任表仍显示 trusted。
契约要求"被验证的字节 = 被执行的字节"。

本文件断言修复后的行为:
  A: 正常核心插件 (已确认信任) 照常加载。
  B: 模拟"哈希完成后、执行前被替换": core_trust_state 仍返回 trusted, 但
     入口指纹已不符 -> 拒载 (broken 含 TOCTOU), 恶意代码未执行 (marker 不存在)。
  C: 把入口恢复成信任表里那份 benign 内容 -> 重新加载成功 (失败不"中毒")。
  D: _load_entry_unrestricted 编译/执行的是**传入的 bytes**, 不是磁盘当前内容
     (证明执行面与校验面共用同一份字节)。
  E: 未打补丁的真实信任闸对"被改过"的核心插件仍报 modified 且不加载
     (纵深防御: 二次校验不替代第一道门)。

运行: python tests\test_plugin_trust_toctou.py   (无头, 无 GPU)
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

_FAILS = []
_MOD_PREFIX = 'loom_plugin_probe_core'
_PID = 'probe.core'
_ENTRY_BENIGN = """# -*- coding: utf-8 -*-
BENIGN = True


def register(api):
    pass
"""


def check(name, cond, extra=""):
    print(("PASS " if cond else "FAIL ") + name + ("  " + str(extra) if extra else ""))
    if not cond:
        _FAILS.append(name)


def _write(path, content):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        f.write(content)


def _core_plugin(tmp, entry_src):
    d = os.path.join(tmp, 'core_plugins', 'render', _PID)
    _write(os.path.join(d, 'plugin.json'), json.dumps({
        "id": _PID, "name": "TOCTOU核心", "version": "0.1.0",
        "entry": "entry.py", "layer": "player", "capability": "render",
        "desc": "TOCTOU 回归"}, ensure_ascii=False))
    _write(os.path.join(d, 'entry.py'), entry_src)
    return d


def _cleanup():
    for pid in list(plugin_loader._LOADED):
        plugin_loader.unload_plugin(pid, disable=False)
    plugin_loader._DISABLED.clear()
    plugin_loader._EDITOR_BUTTONS[:] = []
    for m in list(sys.modules):
        if m.startswith(_MOD_PREFIX):
            sys.modules.pop(m, None)


# ====================================================================
# A: 已信任核心插件正常加载
# ====================================================================
def t_trusted_core_loads():
    _cleanup()
    tmp = tempfile.mkdtemp()
    d = _core_plugin(tmp, _ENTRY_BENIGN)
    check("[A] 确认信任", plugin_loader.confirm_core_trust(_PID, d, base=tmp))
    check("[A] 信任状态 trusted",
          plugin_loader.core_trust_state({'id': _PID}, d, base=tmp) == 'trusted')
    r = plugin_loader.load_plugins(base=tmp)
    check("[A] 已信任核心插件正常加载", r['loaded'] == [_PID], r)
    check("[A] 模块已注册", _MOD_PREFIX in sys.modules)
    ok, err = plugin_loader.unload_plugin(_PID, disable=False)
    check("[A] 卸载成功且模块摘除",
          ok and _MOD_PREFIX not in sys.modules, err)
    _cleanup()


# ====================================================================
# B: 哈希后执行前替换 -> 指纹二次校验拒载
# ====================================================================
def t_replace_between_hash_and_exec():
    _cleanup()
    tmp = tempfile.mkdtemp()
    d = _core_plugin(tmp, _ENTRY_BENIGN)
    check("[B] 确认信任 (benign)", plugin_loader.confirm_core_trust(_PID, d, base=tmp))
    marker = os.path.join(tmp, 'PWNED_TOCTOU.txt')
    _write(os.path.join(d, 'entry.py'),
           "# -*- coding: utf-8 -*-\ndef register(api):\n"
           "    open(%r, 'w').write('escaped')\n" % marker)

    # 模拟 TOCTOU: 信任闸在替换**之前**已判 trusted (真实时序里 hash 已完成)
    orig = plugin_loader.core_trust_state
    plugin_loader.core_trust_state = lambda *a, **k: 'trusted'
    try:
        r = plugin_loader.load_plugins(base=tmp)
    finally:
        plugin_loader.core_trust_state = orig

    check("[B] 被替换的入口 -> 拒载 (loaded 为空)", r['loaded'] == [], r)
    check("[B] broken 报 TOCTOU/指纹不一致",
          len(r['broken']) == 1 and 'TOCTOU' in r['broken'][0]['error'],
          r['broken'])
    check("[B] 恶意代码未执行 (marker 不存在)", not os.path.exists(marker))
    check("[B] 失败插件未进 _LOADED",
          plugin_loader.get_plugin(_PID) is None)
    check("[B] 失败插件模块未残留",
          _MOD_PREFIX not in sys.modules)
    _cleanup()


# ====================================================================
# C: 恢复成信任表内容 -> 重新加载成功
# ====================================================================
def t_restore_then_load():
    _cleanup()
    tmp = tempfile.mkdtemp()
    d = _core_plugin(tmp, _ENTRY_BENIGN)
    check("[C] 确认信任", plugin_loader.confirm_core_trust(_PID, d, base=tmp))
    marker = os.path.join(tmp, 'PWNED_TOCTOU2.txt')
    _write(os.path.join(d, 'entry.py'),
           "def register(api):\n    open(%r, 'w').write('x')\n" % marker)
    orig = plugin_loader.core_trust_state
    plugin_loader.core_trust_state = lambda *a, **k: 'trusted'
    try:
        r1 = plugin_loader.load_plugins(base=tmp)
    finally:
        plugin_loader.core_trust_state = orig
    check("[C] 第一次被拒", r1['loaded'] == [] and r1['broken'])
    _write(os.path.join(d, 'entry.py'), _ENTRY_BENIGN)   # 恢复成信任的那份
    r2 = plugin_loader.load_plugins(base=tmp)
    check("[C] 恢复后重新加载成功", r2['loaded'] == [_PID], r2)
    check("[C] 恶意 marker 仍未生成", not os.path.exists(marker))
    plugin_loader.unload_plugin(_PID, disable=False)
    _cleanup()


# ====================================================================
# D: 执行面 = 传入的 bytes (不是磁盘当前内容)
# ====================================================================
def t_executes_passed_bytes():
    _cleanup()
    tmp = tempfile.mkdtemp()
    path = os.path.join(tmp, 'entry.py')
    _write(path, "DISK = 'malicious'\n")
    src = b"# -*- coding: utf-8 -*-\nVERIFIED = 'bytes'\n"
    mod = plugin_loader._load_entry_unrestricted(src, path, _MOD_PREFIX + '_bytes')
    try:
        check("[D] 执行的是传入 bytes (VERIFIED)", getattr(mod, 'VERIFIED', None) == 'bytes')
        check("[D] 未执行磁盘当前内容", not hasattr(mod, 'DISK'))
        check("[D] __file__ 指向入口路径", mod.__file__ == path, mod.__file__)
    finally:
        sys.modules.pop(_MOD_PREFIX + '_bytes', None)
    _cleanup()


# ====================================================================
# E: 真实信任闸对 modified 仍拒绝 (第一道门未被替代)
# ====================================================================
def t_modified_still_blocked():
    _cleanup()
    tmp = tempfile.mkdtemp()
    d = _core_plugin(tmp, _ENTRY_BENIGN)
    check("[E] 确认信任", plugin_loader.confirm_core_trust(_PID, d, base=tmp))
    marker = os.path.join(tmp, 'PWNED_TOCTOU3.txt')
    _write(os.path.join(d, 'entry.py'),
           "def register(api):\n    open(%r, 'w').write('x')\n" % marker)
    r = plugin_loader.load_plugins(base=tmp)
    check("[E] 真实闸报 modified (不加载)",
          r['loaded'] == [] and len(r['untrusted']) == 1
          and r['untrusted'][0].get('state') == 'modified', r)
    check("[E] 恶意代码未执行", not os.path.exists(marker))
    _cleanup()


if __name__ == "__main__":
    print("========== 核心插件信任闸 TOCTOU (scan_09 P-03) ==========")
    _cleanup()
    t_trusted_core_loads()
    t_replace_between_hash_and_exec()
    t_restore_then_load()
    t_executes_passed_bytes()
    t_modified_still_blocked()
    _cleanup()
    print()
    if _FAILS:
        print("总结果: FAIL ❌", _FAILS)
        sys.exit(1)
    print("总结果: ALL PASS ✅")
