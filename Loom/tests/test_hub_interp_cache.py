# -*- coding: utf-8 -*-
"""
test_hub_interp_cache.py — LoomHub 0.1.3 内修：引擎选择改为「内存缓存」交互

人类实测反馈（不是他点错）：
  "选项目后按『用选中引擎打开项目』提示要选引擎；选完引擎又提示要选项目..."
根因：Tk Listbox 默认 exportselection=1 —— 在另一个 Listbox 里选中会清掉前一个的选中，
      所以"引擎+项目同时选中"物理上不可能；旧实现却依赖两个 Listbox 同时有选中。

本文件锁死新口径：
  ① set_current_interp(b) 后 refresh_interpreters() / _refresh() 都不失效
  ② open_project(proj, interp=None) 在有缓存时用缓存
  ③ 缓存为空 -> 回退 project.engine_dir -> 再回退默认
  ④ 两处 Listbox 都设 exportselection=False（反射 + 源码双保险）
  ⑤ Tk 视图：按钮在右侧项目面板下，且存在「选为当前引擎」
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

_CFG_DIR = tempfile.mkdtemp(prefix='hub_interp_cache_')
os.environ['LOOM_USER_ROOT'] = _CFG_DIR

import hub_config as cfg          # noqa: E402
import hub_controller as hctrl    # noqa: E402

cfg.INTERPRETERS_FILE = os.path.join(_CFG_DIR, 'interpreters.json')
cfg.PROJECTS_FILE = os.path.join(_CFG_DIR, 'projects.json')

_FAILS = []


def check(name, cond, extra=""):
    print(("PASS " if cond else "FAIL ") + name + ("  " + str(extra) if extra else ""))
    if not cond:
        _FAILS.append(name)


def _make_interp(root, version, kind='py'):
    d = os.path.join(root, version)
    os.makedirs(d, exist_ok=True)
    main = 'Loom.py' if kind == 'py' else 'Loom.exe'
    with open(os.path.join(d, cfg.META_NAME), 'w', encoding='utf-8') as f:
        json.dump({"name": "Loom", "version": version,
                   "main": main if kind == 'py' else None,
                   "main_exe": main if kind == 'exe' else None,
                   "python_version": "3.12.10"}, f, ensure_ascii=False)
    open(os.path.join(d, main), 'w').close()
    return d


def _mk_ctrl():
    ctrl = hctrl.HubController.__new__(hctrl.HubController)
    ctrl.install_root = ''
    ctrl.interpreters = cfg.load_interpreters()
    ctrl.projects = cfg.load_projects()
    ctrl.msg = ''
    ctrl.msg_level = 'ok'
    ctrl.py_ver = None
    ctrl.current_interp = None
    return ctrl


def _capture_launch(ctrl, project, interp=None):
    captured = {}
    old_pop = hctrl.subprocess.Popen
    old_py = cfg.default_python
    hctrl.subprocess.Popen = lambda cmd, **kw: captured.setdefault('cmd', list(cmd))
    cfg.default_python = lambda engine_dir=None: 'python'
    try:
        if interp is None:
            ctrl.open_project(project)
        else:
            ctrl.open_project(project, interp=interp)
    finally:
        hctrl.subprocess.Popen = old_pop
        cfg.default_python = old_py
    return captured.get('cmd') or []


def _norm(p):
    return os.path.normcase(os.path.abspath(p))


# ---------------- ① 缓存不失效 ----------------
def t_cache_survives_refresh():
    with tempfile.TemporaryDirectory() as root:
        a = _make_interp(root, '0.1.0.beta4')
        b = _make_interp(root, '0.1.0.beta5')
        cfg.save_interpreters([cfg.discover_interpreter(a),
                               cfg.discover_interpreter(b)])
        cfg.set_default_interpreter(cfg.discover_interpreter(a))    # ★ 在 a
        ctrl = _mk_ctrl()
        ctrl.set_current_interp(ctrl.interpreters[1])               # 当前引擎 = b
        check("① 设置后立即生效（缓存命中 b）",
              _norm(ctrl.current_interp_cached()['dir']) == _norm(b),
              ctrl.current_interp_cached())
        ctrl.interpreters, _ = cfg.refresh_interpreters()
        check("① refresh_interpreters() 之后缓存仍指向 b",
              _norm(ctrl.current_interp_cached()['dir']) == _norm(b),
              ctrl.current_interp_cached())
        ctrl._refresh()
        check("① _refresh() 之后缓存仍指向 b",
              _norm(ctrl.current_interp_cached()['dir']) == _norm(b),
              ctrl.current_interp_cached())
        check("① 当前引擎与 ★ 默认引擎互不影响（默认仍是 a）",
              _norm(cfg.default_interpreter()['dir']) == _norm(a),
              cfg.default_interpreter()['version'])
        check("① current_interp_or_default() 返回缓存 b（有缓存时默认不抢）",
              _norm(ctrl.current_interp_or_default()['dir']) == _norm(b))
        # 条目被移除 -> 缓存自动清空（不让 UI 显示不存在的引擎）
        cfg.remove_interpreter(ctrl.interpreters[1])
        ctrl._refresh()
        check("① 引擎被移除后缓存自动清空", ctrl.current_interp_cached() is None)


# ---------------- ② 有缓存时 open_project 用它 ----------------
def t_cached_interp_used():
    with tempfile.TemporaryDirectory() as root:
        a = _make_interp(root, '0.1.0.beta4')
        b = _make_interp(root, '0.1.0.beta5')
        cfg.save_interpreters([cfg.discover_interpreter(a),
                               cfg.discover_interpreter(b)])
        cfg.set_default_interpreter(cfg.discover_interpreter(a))
        ctrl = _mk_ctrl()
        ctrl.set_current_interp(ctrl.interpreters[1])       # b
        scene = os.path.join(a, 'Projects', 'z.json')
        os.makedirs(os.path.dirname(scene), exist_ok=True)
        open(scene, 'w', encoding='utf-8').write('{}')
        # 项目归属 a，但缓存是 b -> 缓存优先
        cmd = _capture_launch(ctrl, {'name': 'z', 'scene': scene,
                                     'engine_dir': os.path.dirname(a)})
        check("② 有缓存时用缓存引擎 b（压过 project.engine_dir=a）",
              any(_norm(os.path.join(b, 'Loom.py')) == _norm(c) for c in cmd), cmd)

        # 显式传入 > 缓存
        cmd2 = _capture_launch(ctrl, {'name': 'z', 'scene': scene},
                               interp=ctrl.interpreters[0])
        check("② 显式传入 a 时压过缓存 b",
              any(_norm(os.path.join(a, 'Loom.py')) == _norm(c) for c in cmd2), cmd2)


# ---------------- ③ 缓存为空 -> engine_dir -> 默认 ----------------
def t_fallback_chain():
    # 分放两个引擎根：父目录命中只有一个候选（同根多版本取最高由 test_hub_update 覆盖）
    with tempfile.TemporaryDirectory() as root, \
            tempfile.TemporaryDirectory() as rootB:
        a = _make_interp(root, '0.1.0.beta4')
        b = _make_interp(rootB, '0.1.0.beta5')
        cfg.save_interpreters([cfg.discover_interpreter(a),
                               cfg.discover_interpreter(b)])
        cfg.set_default_interpreter(cfg.discover_interpreter(b))   # ★ 在 b
        ctrl = _mk_ctrl()
        check("③ 缓存为空时 current_interp_cached() 返回 None",
              ctrl.current_interp_cached() is None)
        scene = os.path.join(a, 'Projects', 'w.json')
        os.makedirs(os.path.dirname(scene), exist_ok=True)
        open(scene, 'w', encoding='utf-8').write('{}')
        cmd = _capture_launch(ctrl, {'name': 'w', 'scene': scene,
                                     'engine_dir': os.path.dirname(a)})
        check("③ 无缓存 -> 回退 project.engine_dir（a）",
              any(_norm(os.path.join(a, 'Loom.py')) == _norm(c) for c in cmd), cmd)
        cmd2 = _capture_launch(ctrl, {'name': 'w', 'scene': scene,
                                      'engine_dir': os.path.join(root, 'nope')})
        check("③ engine_dir 无匹配 -> 回退默认（b）",
              any(_norm(os.path.join(b, 'Loom.py')) == _norm(c) for c in cmd2), cmd2)
        check("③ 无缓存时 current_interp_or_default() 给默认 b",
              _norm(ctrl.current_interp_or_default()['dir']) == _norm(b))


# ---------------- ④ Listbox exportselection ----------------
def t_exportselection_false():
    tk_src = open(os.path.join(REPO, 'LoomHub', 'hub_view_tk.py'),
                  encoding='utf-8').read()
    nova_src = open(os.path.join(REPO, 'LoomHub', 'GUI', 'NovaHubGUI.py'),
                    encoding='utf-8').read()
    check("④ TkHubView 两个 Listbox 都 exportselection=False",
          tk_src.count('exportselection=False') >= 2,
          tk_src.count('exportselection=False'))
    check("④ NovaHubGUI 列表 exportselection=False",
          'exportselection=False' in nova_src)
    # 反射：真建一个 Listbox 验证 True/False 语义（Tk 不可用则跳过并注明）
    try:
        import tkinter
        r = tkinter.Tk()
        r.withdraw()
        try:
            lb_default = tkinter.Listbox(r)
            lb_off = tkinter.Listbox(r, exportselection=False)
            default_on = bool(int(lb_default.cget('exportselection')))
            off_value = bool(int(lb_off.cget('exportselection')))
        finally:
            r.destroy()
        check("④ 反射: Tk 默认 exportselection=1（所以必须显式关）", default_on is True)
        check("④ 反射: Listbox(exportselection=False) 生效", off_value is False)
    except Exception as e:
        print("SKIP Tk 反射（%r）—— 已用源码断言覆盖" % (e,))


# ---------------- ⑤ UI 位置与文案 ----------------
def t_ui_layout():
    src = open(os.path.join(REPO, 'LoomHub', 'hub_view_tk.py'),
               encoding='utf-8').read()
    i_left = src.find('left = tk.LabelFrame')
    i_right = src.find('right = tk.LabelFrame')
    # 用按钮元组定位（注释里也会出现这些文案，不能用裸 find）
    i_current_btn = src.find('("选为当前引擎", self._set_current_interp)')
    i_open_btn = src.find('("用当前引擎打开", self._open_project_with_current)')
    check("⑤ 「选为当前引擎」在左侧解释器面板（right 之前）",
          0 < i_left < i_current_btn < i_right, (i_left, i_current_btn, i_right))
    check("⑤ 「用当前引擎打开」在右侧项目面板（right 之后）",
          i_right < i_open_btn, (i_right, i_open_btn))
    check("⑤ 存在「当前引擎: 未选（将用默认）」状态行",
          '当前引擎: 未选（将用默认）' in src)
    nova = open(os.path.join(REPO, 'LoomHub', 'GUI', 'NovaHubGUI.py'),
                encoding='utf-8').read()
    check("⑤ NovaHubGUI 同步：选为当前引擎 + 用当前引擎打开",
          '选为当前引擎' in nova and '用当前引擎打开' in nova)


if __name__ == "__main__":
    print("========== LoomHub 当前引擎缓存（exportselection 修复） ==========")
    t_cache_survives_refresh()
    t_cached_interp_used()
    t_fallback_chain()
    t_exportselection_false()
    t_ui_layout()
    if _FAILS:
        print("总结果: FAIL ❌", _FAILS)
        sys.exit(1)
    print("总结果: ALL PASS ✅")
