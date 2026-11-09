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


# ---------------- A-04 复核项 ----------------
def t_dead_fallback_fixed():
    """① 第三条兜底以前载荷是 %%d.%%d -> Py SyntaxError，结构上不可达。"""
    import subprocess
    src = open(os.path.join(REPO, 'LoomHub', 'hub_config.py'), encoding='utf-8').read()
    check("① 旧的错误载荷（%%d.%%d + %% sys.version_info）已不在代码里",
          '%d.%%d" %% sys.version_info' not in src)
    check("① 兜底改为直接读 sys.version_info（Q5=B，不再起子进程）",
          "'%d.%d' % (sys.version_info[0], sys.version_info[1])" in src)
    r = subprocess.run([sys.executable, '-c',
                        'import sys;print("%d.%d" % sys.version_info[:2])'],
                       capture_output=True, text=True, timeout=20)
    check("① 兜底载荷真能跑出 x.y",
          r.returncode == 0 and len((r.stdout or '').strip().split('.')) == 2,
          (r.returncode, (r.stdout or '').strip(), (r.stderr or '')[:80]))


def t_note_passed_through():
    """② launch_spec 算出的 python_note 必须出现在命令层返回体里。"""
    src = open(os.path.join(REPO, 'LoomHub', 'hub_commands.py'), encoding='utf-8').read()
    check("② launch_spec 返回 python_note", "'python_note': cfg.interp_python_note(info)" in src)
    check("② launch_engine 返回体透传 python_note",
          "'python_note': spec.get('python_note')" in src)
    check("② 启动后短窗口查存活并回报 alive/exit_code",
          'probe_started(' in src and "'alive': alive" in src)


def t_message_truthful():
    """③ 文案按实际使用的解释器版本，不再一律写"系统默认"。"""
    src = open(os.path.join(REPO, 'LoomHub', 'hub_controller.py'), encoding='utf-8').read()
    check("③ 文案区分「引擎要求」与系统默认",
          '（引擎要求）' in src or '(引擎要求)' in src)
    check("③ 不再只有「用系统默认 Python 环境启动」",
          '用系统默认 Python 环境启动' not in src, '旧文案已替换')
    nova = open(os.path.join(REPO, 'LoomHub', 'GUI', 'NovaHubGUI.py'),
                encoding='utf-8').read()
    check("③ NovaHubGUI 底部提示同步改口径",
          '源码引擎优先用其声明的 Python' in nova)


def t_cache_invalidates():
    """④ Python 被卸载/移动后，缓存不能继续返回死路径。"""
    cfg._PY_RESOLVE_CACHE.clear()
    dead = os.path.join(tempfile.mkdtemp(prefix='hub_pyver_dead_'), 'python.exe')
    cfg._PY_RESOLVE_CACHE['3.13'] = dead          # 制造"指向不存在文件"的缓存
    old_which, old_run = cfg.shutil.which, cfg.subprocess.run
    cfg.shutil.which = lambda name: None          # 不让 py 启动器兜底
    def _fake_run(cmd, **kw):                     # 当前解释器固定报 3.12，不匹配 3.13
        class R(object):
            returncode = 0
            stdout = '3.12\n'
        return R()
    cfg.subprocess.run = _fake_run
    try:
        got = cfg.resolve_python_for('3.13.15')
    finally:
        cfg.shutil.which, cfg.subprocess.run = old_which, old_run
        cfg._PY_RESOLVE_CACHE.clear()
    # 本机可能真的装了 3.13（那就该解析到真实路径）—— 唯一硬要求是**不返回死路径**
    check("④ 缓存指向已删除文件 -> 绝不返回死路径",
          got is None or (got != dead and os.path.isfile(got)), got)


def t_probe_started():
    """⑤ 启动后查存活：立即退出的进程要能被识别。"""
    import subprocess
    p = subprocess.Popen([sys.executable, '-c', 'import sys;sys.exit(1)'])
    alive, rc = cfg.probe_started(p, wait=2.0)
    check("⑤ 立即退出 -> alive=False 且带 exit_code", alive is False and rc == 1, (alive, rc))
    p2 = subprocess.Popen([sys.executable, '-c', 'import time;time.sleep(1.5)'])
    try:
        alive2, rc2 = cfg.probe_started(p2, wait=0.6)
        check("⑤ 存活进程 -> alive=True", alive2 is True and rc2 is None, (alive2, rc2))
    finally:
        try:
            p2.kill()
        except OSError:
            pass


def t_scene_version_consistent():
    """⑧ Hub 两处新建场景必须跟 sceneio.SCENE_VERSION 一致。"""
    import sceneio
    with tempfile.TemporaryDirectory() as tmp:
        p = os.path.join(tmp, 'x.json')
        import hub_controller as hc
        ctrl = hc.HubController.__new__(hc.HubController)
        ctrl.new_scene_file(p)
        v_ctrl = json.load(open(p, encoding='utf-8')).get('version')
        check("⑧ controller 新建场景版本 = sceneio.SCENE_VERSION",
              v_ctrl == sceneio.SCENE_VERSION == cfg.scene_version(), v_ctrl)
        import hub_commands as hcmd
        old = cfg.PROJECTS_FILE
        cfg.PROJECTS_FILE = os.path.join(tmp, 'projects.json')
        try:
            p2 = os.path.join(tmp, 'y.json')
            r = hcmd.dispatch('project_create', {'path': p2})
            v_cmd = json.load(open(p2, encoding='utf-8')).get('version')
            check("⑧ commands 新建场景版本一致",
                  r.get('ok') and v_cmd == sceneio.SCENE_VERSION, (r, v_cmd))
        finally:
            cfg.PROJECTS_FILE = old


# ---------------- Q2=A：包内 Python 权威 ----------------
def _make_release(root, with_bundled=True, exe_ok=True):
    """造一个发布包布局: <root>/Loom/... + <root>/python/python.exe"""
    eng = os.path.join(root, 'Loom')
    os.makedirs(eng, exist_ok=True)
    with open(os.path.join(eng, cfg.META_NAME), 'w', encoding='utf-8') as fh:
        json.dump({'name': 'Loom', 'version': '0.1.0.beta6',
                   'main': 'Loom.py', 'main_exe': None,
                   'python_version': '3.13.15'}, fh)
    open(os.path.join(eng, 'Loom.py'), 'w').close()
    py = os.path.join(root, 'python')
    if with_bundled:
        os.makedirs(os.path.join(py, 'Lib', 'site-packages'), exist_ok=True)
        if exe_ok:
            open(os.path.join(py, 'python.exe'), 'w').close()
        else:
            os.makedirs(py, exist_ok=True)     # 目录在但没有 python.exe
    return eng


def _sys_python_stub():
    """伪"系统里有个 3.13"（用于证明它**不能**顶掉包内 python）。"""
    def _fake(spec, use_cache=True):
        return r'C:\Python313\python.exe'
    return _fake


def t_bundled_python_authoritative():
    with tempfile.TemporaryDirectory() as root:
        eng = _make_release(root, with_bundled=True, exe_ok=True)
        info = cfg.discover_interpreter(eng)
        bundled = os.path.join(root, 'python', 'python.exe')
        old = cfg.resolve_python_for
        cfg.resolve_python_for = _sys_python_stub()
        try:
            cmd = _launch(info)
            src = cfg.python_source(info)
            note = cfg.interp_python_note(info)
            check("① 包内 python 存在 -> 命令首段 = 包内路径（不被系统顶替）",
                  os.path.normcase(cmd[0]) == os.path.normcase(bundled), cmd[:1])
            check("① python_source = bundled", src == 'bundled', src)
            check("① 包内自足时不打扰用户（note 空）", note == '', note)
        finally:
            cfg.resolve_python_for = old


def t_bundled_missing_fallback():
    with tempfile.TemporaryDirectory() as root:
        eng = _make_release(root, with_bundled=True, exe_ok=False)   # python/ 在但没 exe
        info = cfg.discover_interpreter(eng)
        old = cfg.resolve_python_for
        cfg.resolve_python_for = lambda spec, use_cache=True: None
        try:
            cmd = _launch(info)
            note = cfg.interp_python_note(info)
            check("② 包内不可用 -> 回退系统解释器", cmd[0] == 'python', cmd[:1])
            check("② 回退时提示包内 python 不可用",
                  '包内 python 不可用' in (note or ''), note)
        finally:
            cfg.resolve_python_for = old
    # 开发工作区（压根没有 python/ 目录）不误报
    with tempfile.TemporaryDirectory() as root:
        d = _make_engine(root, python_version='3.13.15')
        info = cfg.discover_interpreter(d)
        check("② 开发工作区（无包内运行时）不误报",
              '包内' not in (cfg.interp_python_note(info) or ''),
              cfg.interp_python_note(info))


def t_frozen_fallback_no_subprocess():
    """Q5=B: 冻结版兜底不拉子进程（否则会再开一个 LoomHub 抢焦点）。"""
    calls = []

    def _fake_run(cmd, **kw):
        calls.append(cmd)
        raise AssertionError('冻结态不应调用 subprocess.run')

    old_run = cfg.subprocess.run
    old_which = cfg.shutil.which
    old_frozen = getattr(sys, 'frozen', None)
    env_keys = ('LOCALAPPDATA', 'ProgramFiles', 'ProgramFiles(x86)', 'ProgramW6432')
    old_env = {k: os.environ.get(k) for k in env_keys}
    empty_root = tempfile.mkdtemp(prefix='hub_pyver_empty_')
    cfg.subprocess.run = _fake_run
    cfg.shutil.which = lambda name: None        # 不让 py 启动器兜底
    for k in env_keys:                          # 让①的安装目录搜索也落空
        os.environ[k] = empty_root
    sys.frozen = True
    cfg._PY_RESOLVE_CACHE.clear()
    try:
        got = cfg.resolve_python_for('3.13.15')
    finally:
        cfg.subprocess.run = old_run
        cfg.shutil.which = old_which
        cfg._PY_RESOLVE_CACHE.clear()
        for k, v in old_env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        if old_frozen is None:
            del sys.frozen
        else:
            sys.frozen = old_frozen
    check("③ 冻结态兜底不产生子进程调用", calls == [], calls)
    check("③ 冻结态不把 Hub 自己当 Python（返回 None）", got is None, got)


if __name__ == "__main__":
    print("========== LoomHub 源码引擎 Python 版本选择 ==========")
    t_ledger_records_python_version()
    t_launch_uses_matching_python()
    t_fallback_when_missing_or_unresolved()
    t_exe_unaffected()
    t_dead_fallback_fixed()
    t_note_passed_through()
    t_message_truthful()
    t_cache_invalidates()
    t_probe_started()
    t_scene_version_consistent()
    t_bundled_python_authoritative()
    t_bundled_missing_fallback()
    t_frozen_fallback_no_subprocess()
    if _FAILS:
        print("总结果: FAIL ❌", _FAILS)
        sys.exit(1)
    print("总结果: ALL PASS ✅")
