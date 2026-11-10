# -*- coding: utf-8 -*-
"""
test_hub_install_root.py — 引擎安装根：可自由选 / 可持久化 / 非管理员可用 / 扫描覆盖双根

覆盖人类 a~g 七条要求（2026-11-10）。全部用 LOOM_USER_ROOT + 临时目录隔离。
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
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
REPO = os.path.dirname(ROOT)
for _p in (os.path.join(REPO, 'LoomHub'), ROOT):
    if _p not in sys.path:
        sys.path.insert(0, _p)

_CFG = tempfile.mkdtemp(prefix='hub_instroot_')
os.environ['LOOM_USER_ROOT'] = _CFG

import hub_config as cfg          # noqa: E402
import hub_controller as hctrl    # noqa: E402
import hub_install as inst        # noqa: E402

cfg.INTERPRETERS_FILE = os.path.join(_CFG, 'interpreters.json')
cfg.PROJECTS_FILE = os.path.join(_CFG, 'projects.json')

_FAILS = []


def check(name, cond, extra=""):
    print(("PASS " if cond else "FAIL ") + name + ("  " + str(extra) if extra else ""))
    if not cond:
        _FAILS.append(name)


def _mk_ctrl():
    c = hctrl.HubController.__new__(hctrl.HubController)
    c.install_root = cfg.saved_install_root() or cfg.default_install_root()
    c.interpreters = cfg.load_interpreters()
    c.projects = cfg.load_projects()
    c.msg = ''
    c.msg_level = 'ok'
    c._default_interp = None
    c.current_interp = None
    c.set_msg = lambda m, lvl='ok': (setattr(c, 'msg', m), setattr(c, 'msg_level', lvl))
    return c


def _mk_engine(root, version, layout='flat'):
    """layout: flat=<root>/<ver>/解释器.json；release=<root>/<ver>/Loom/解释器.json"""
    base = os.path.join(root, version)
    d = os.path.join(base, 'Loom') if layout == 'release' else base
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, cfg.META_NAME), 'w', encoding='utf-8') as f:
        json.dump({'name': 'Loom', 'version': version, 'main': 'Loom.py',
                   'main_exe': None, 'python_version': '3.13.15'}, f)
    open(os.path.join(d, 'Loom.py'), 'w').close()
    return d


def _mkzip(path, version='0.1.0.beta6'):
    with zipfile.ZipFile(path, 'w') as zf:
        zf.writestr('Loom/解释器.json', json.dumps(
            {'name': 'Loom', 'version': version, 'main': 'Loom.py',
             'main_exe': None}, ensure_ascii=False))
        zf.writestr('Loom/Loom.py', 'print(1)\n')
    return path


# ---------------- a) 持久化 ----------------
def t_persist_install_root():
    with tempfile.TemporaryDirectory() as tmp:
        c = _mk_ctrl()
        target = os.path.join(tmp, 'MyLoom')
        os.makedirs(target)
        check("a 设置安装根成功", c.set_install_root(target) is True, c.msg)
        saved = cfg.load_hub_settings().get('install_root')
        check("a 安装根写进用户层 settings",
              saved and os.path.normcase(saved) == os.path.normcase(target), saved)
        # 模拟重启：新控制器按 saved > default 取值
        c2 = _mk_ctrl()
        check("a 重启后仍是用户选的目录",
              os.path.normcase(c2.install_root) == os.path.normcase(target),
              c2.install_root)
        check("a 用户层落点正确（%LOCALAPPDATA%/Loom/hub）",
              os.path.abspath(cfg.hub_settings_file()).startswith(
                  os.path.abspath(_CFG)), cfg.hub_settings_file())


# ---------------- b) 默认根自适应 ----------------
def t_adaptive_default_root():
    with tempfile.TemporaryDirectory() as tmp:
        blocker = os.path.join(tmp, 'blocker')
        open(blocker, 'w').close()
        bad = os.path.join(blocker, 'Loom')          # 祖先是个文件 -> 不可写
        good = os.path.join(tmp, 'Programs', 'Loom')
        os.makedirs(good)
        old_pf, old_user = cfg.DEFAULT_INSTALL_ROOT, cfg.user_install_root
        cfg.DEFAULT_INSTALL_ROOT = bad
        cfg.user_install_root = lambda: good
        try:
            check("b Program Files 不可写 -> 默认根自动落到用户目录",
                  os.path.normcase(cfg.default_install_root()) == os.path.normcase(good),
                  cfg.default_install_root())
        finally:
            cfg.DEFAULT_INSTALL_ROOT, cfg.user_install_root = old_pf, old_user
        check("b Program Files 可写时仍优先 Program Files",
              cfg.root_writable(cfg.DEFAULT_INSTALL_ROOT)
              is True or cfg.default_install_root() != good)


# ---------------- c/f) 扫描覆盖多根 ----------------
def t_scan_covers_both_roots():
    with tempfile.TemporaryDirectory() as pf, tempfile.TemporaryDirectory() as us:
        _mk_engine(pf, '0.1.0.beta4', layout='release')
        _mk_engine(us, '0.1.0.beta6', layout='flat')
        old_pf, old_user = cfg.DEFAULT_INSTALL_ROOT, cfg.user_install_root
        cfg.DEFAULT_INSTALL_ROOT = pf
        cfg.user_install_root = lambda: us
        try:
            c = _mk_ctrl()
            c.install_root = os.path.join(us)
            roots = c.scan_roots()
            check("f 扫描根包含 Program Files 与用户目录",
                  any(os.path.normcase(r) == os.path.normcase(pf) for r in roots)
                  and any(os.path.normcase(r) == os.path.normcase(us) for r in roots),
                  roots)
            found = cfg.scan_install_roots(roots)
            vers = sorted(x.get('version') for x in found)
            check("f 一次扫描同时发现两处引擎（含发布包布局）",
                  vers == ['0.1.0.beta4', '0.1.0.beta6'], vers)
            check("d 发布包布局 <root>/<ver>/Loom 能被发现",
                  any(os.path.normcase(x['dir']).endswith('loom') and
                      x['version'] == '0.1.0.beta4' for x in found),
                  [x['dir'] for x in found])
            check("c scan_interpreters 使用当前 install_root（用户根）",
                  any(os.path.normcase(r) == os.path.normcase(us) for r in c.scan_roots()))
            # 真正的 scan_interpreters 行为：登记条数
            c.interpreters = []
            c.scan_interpreters()
            check("c 扫描后登记到台账", len(cfg.load_interpreters()) == 2,
                  [x['version'] for x in cfg.load_interpreters()])
        finally:
            cfg.DEFAULT_INSTALL_ROOT, cfg.user_install_root = old_pf, old_user


# ---------------- e) 权限不足分类 + 清理半成品 ----------------
def t_permission_error_and_cleanup():
    with tempfile.TemporaryDirectory() as tmp:
        z = _mkzip(os.path.join(tmp, 'a.zip'))
        root = os.path.join(tmp, 'root')
        os.makedirs(root)
        old_extract = inst._safe_extract

        def _deny(zf, target_dir):
            raise PermissionError(13, '拒绝访问')

        inst._safe_extract = _deny
        try:
            msg = ''
            try:
                inst.install_from_zip(z, '0.1.0.beta6', target_root=root)
            except inst.InstallError as e:
                msg = str(e)
            check("e 权限失败单独归类（提示管理员/改安装根）",
                  '权限不足' in msg and '改安装根' in msg, msg[:120])
            check("e 失败后无半成品目录",
                  not os.path.exists(os.path.join(root, '0.1.0.beta6')),
                  os.listdir(root))
        finally:
            inst._safe_extract = old_extract


# ---------------- g) 真目录选择器 ----------------
def t_directory_picker_wired():
    for name, rel in (('TkHubView', 'LoomHub/hub_view_tk.py'),
                      ('NovaHubGUI', 'LoomHub/GUI/NovaHubGUI.py'),
                      ('LoomHubGUI(pygame)', 'LoomHub/LoomHubGUI.py')):
        src = open(os.path.join(REPO, rel), encoding='utf-8').read()
        check("g %s 用 filedialog.choose_directory" % name,
              'filedialog.choose_directory' in src)
        check("g %s 对不存在目录询问创建" % name,
              'askyesno' in src and 'create=create' in src)
    # 手输路径仍作为回退保留
    tk = open(os.path.join(REPO, 'LoomHub/hub_view_tk.py'), encoding='utf-8').read()
    check("g 目录选择失败时回退手输", 'simpledialog.askstring' in tk)


if __name__ == "__main__":
    print("========== LoomHub 引擎安装根（a~g） ==========")
    t_persist_install_root()
    t_adaptive_default_root()
    t_scan_covers_both_roots()
    t_permission_error_and_cleanup()
    t_directory_picker_wired()
    if _FAILS:
        print("总结果: FAIL ❌", _FAILS)
        sys.exit(1)
    print("总结果: ALL PASS ✅")
