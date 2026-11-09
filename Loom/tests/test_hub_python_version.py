# -*- coding: utf-8 -*-
"""
test_hub_python_version.py — 源码版引擎按 解释器.json 的 python_version 选解释器

背景（2026-11-09 人类要求，不改系统默认解释器/文件关联）：
  系统 .py 关联仍是 3.12，而新版 Loom 源码引擎要求 3.13；
  Hub 以前只按注册表 .py 关联找 python -> 从 Hub 启动源码引擎会跑 3.12。

断言：
  ① discover_interpreter 把 python_version 记进台账
  ② 有 3.13.15 且能解析 -> 启动命令用 3.13（不是默认 3.12）
  ③ 有版本但解析不到 -> 回退默认 + 提示（note 非空、点名版本）
  ④ 缺 python_version -> 回退默认 + 提示（未声明）
  ⑤ 编译版（kind=exe）不受影响（命令就是 exe，无 python 前缀、无提示）
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


import json
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
REPO = os.path.dirname(ROOT)
for _p in (os.path.join(REPO, 'LoomHub'), ROOT):
    if _p not in sys.path:
        sys.path.insert(0, _p)

os.environ['LOOM_USER_ROOT'] = tempfile.mkdtemp(prefix='hub_pyver_')

import hub_config as cfg          # noqa: E402

_FAILS = []


def check(name, cond, extra=""):
    print(("PASS " if cond else "FAIL ") + name + ("  " + str(extra) if extra else ""))
    if not cond:
        _FAILS.append(name)


def _make_engine(root, version='0.1.0.beta6', python_version='3.13.15', kind='py'):
    d = os.path.join(root, version)
    os.makedirs(d, exist_ok=True)
    main = 'Loom.py' if kind == 'py' else 'Loom.exe'
    meta = {'name': 'Loom', 'version': version,
            'main': main if kind == 'py' else None,
            'main_exe': main if kind == 'exe' else None}
    if python_version is not None:
        meta['python_version'] = python_version
    with open(os.path.join(d, cfg.META_NAME), 'w', encoding='utf-8') as f:
        json.dump(meta, f, ensure_ascii=False)
    open(os.path.join(d, main), 'w').close()
    return d


def _with_python(path_or_none, fn):
    """临时替换 resolve_python_for（避免依赖本机是否真的装了 3.13）。"""
    old = cfg.resolve_python_for
    cfg._PY_RESOLVE_CACHE.clear()
    cfg.resolve_python_for = lambda spec, use_cache=True: path_or_none
    try:
        return fn()
    finally:
        cfg.resolve_python_for = old
        cfg._PY_RESOLVE_CACHE.clear()


def _launch(info):
    old_dp = cfg.default_python
    cfg.default_python = lambda engine_dir=None: 'python'      # 系统默认（3.12）
    try:
        return cfg.build_launch_command(info, None)
    finally:
        cfg.default_python = old_dp


def t_ledger_records_python_version():
    with tempfile.TemporaryDirectory() as root:
        d = _make_engine(root, python_version='3.13.15')
        info = cfg.discover_interpreter(d)
        check("① 台账记录 python_version（3.13.15）",
              info is not None and info.get('python_version') == '3.13.15', info)
        # 刷新后仍保留（refresh 走 discover）
        cfg.save_interpreters([info])
        lst, _ = cfg.refresh_interpreters()
        check("① refresh_interpreters 后 python_version 仍在",
              lst and lst[0].get('python_version') == '3.13.15', lst)


def t_launch_uses_matching_python():
    with tempfile.TemporaryDirectory() as root:
        d = _make_engine(root, python_version='3.13.15')
        info = cfg.discover_interpreter(d)
        fake = os.path.join(root, 'Python313', 'python.exe')
        os.makedirs(os.path.dirname(fake), exist_ok=True)
        open(fake, 'w').close()
        cmd = _with_python(fake, lambda: _launch(info))
        check("② 有 3.13 时启动命令用 3.13（不是默认 3.12）",
              cmd and os.path.normcase(cmd[0]) == os.path.normcase(fake), cmd)
        check("② 主程序仍是该引擎的 Loom.py",
              os.path.normcase(cmd[1]) == os.path.normcase(os.path.join(d, 'Loom.py')), cmd)
        note = _with_python(fake, lambda: cfg.interp_python_note(info))
        check("② 匹配成功时不打扰用户（note 空）", note == '', note)


def t_fallback_when_missing_or_unresolved():
    with tempfile.TemporaryDirectory() as root:
        d = _make_engine(root, python_version='3.13.15')
        info = cfg.discover_interpreter(d)
        cmd = _with_python(None, lambda: _launch(info))
        check("③ 解析不到 3.13 -> 回退默认 python", cmd and cmd[0] == 'python', cmd)
        note = _with_python(None, lambda: cfg.interp_python_note(info))
        check("③ 回退时给出提示且点名版本",
              '3.13' in note and '回退' in note, note)

        d2 = _make_engine(root, version='0.1.0.beta5', python_version=None)
        info2 = cfg.discover_interpreter(d2)
        cmd2 = _with_python(None, lambda: _launch(info2))
        check("④ 缺 python_version -> 回退默认 python", cmd2 and cmd2[0] == 'python', cmd2)
        note2 = _with_python(None, lambda: cfg.interp_python_note(info2))
        check("④ 缺字段时给出提示（未声明）", '未声明' in (note2 or ''), note2)


def t_exe_unaffected():
    with tempfile.TemporaryDirectory() as root:
        d = _make_engine(root, kind='exe', python_version='3.13.15')
        info = cfg.discover_interpreter(d)
        cmd = _with_python(None, lambda: _launch(info))
        check("⑤ 编译版命令就是 exe（不受 python 版本影响）",
              cmd == [os.path.join(d, 'Loom.exe')], cmd)
        check("⑤ 编译版不产生 python 提示",
              _with_python(None, lambda: cfg.interp_python_note(info)) == '')


if __name__ == "__main__":
    print("========== LoomHub 源码引擎 Python 版本选择 ==========")
    t_ledger_records_python_version()
    t_launch_uses_matching_python()
    t_fallback_when_missing_or_unresolved()
    t_exe_unaffected()
    if _FAILS:
        print("总结果: FAIL ❌", _FAILS)
        sys.exit(1)
    print("总结果: ALL PASS ✅")
