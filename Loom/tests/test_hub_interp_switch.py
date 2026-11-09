# -*- coding: utf-8 -*-
"""
test_hub_interp_switch.py — LoomHub 0.1.3 内修：默认引擎切换 + 用非默认引擎打开项目

回归核心（两个真 bug）：
  Bug1  refresh_interpreters() 把 default 标记擦掉（discover_interpreter 天生没这个键）
        -> set_default 之后立刻被自己的 _refresh 擦掉，UI 永远看不到 ★
  Bug2  open_project() 写死用默认解释器
        -> 没法用"非默认引擎"打开项目；应支持显式传入 + 项目 engine_dir 归属

全程临时目录 + LOOM_USER_ROOT 重定向；不启动真实进程（Popen 换捕获桩）。
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

_CFG_DIR = tempfile.mkdtemp(prefix='hub_interp_switch_')
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
    """在 <root>/<version> 造一个解释器（解释器.json + 主程序）。"""
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
    return ctrl


def _capture_launch(ctrl, project, interp=None):
    """跑真 open_project，捕获 Popen 的 cmd（不启动进程）。"""
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


def t_default_survives_refresh():
    """① set_default 后经 refresh_interpreters()，default 仍是 b（回归核心）。"""
    with tempfile.TemporaryDirectory() as root:
        a = _make_interp(root, '0.1.0.beta4')
        b = _make_interp(root, '0.1.0.beta5')
        cfg.save_interpreters([cfg.discover_interpreter(a),
                               cfg.discover_interpreter(b)])
        cfg.set_default_interpreter(cfg.discover_interpreter(b))
        ctrl = _mk_ctrl()
        ctrl.set_default(ctrl.interpreters[1])          # 走真实动作（内部会 _refresh）
        ctrl.interpreters, _changed = cfg.refresh_interpreters()
        lst = cfg.load_interpreters()
        by_dir = {os.path.normcase(x['dir']): x for x in lst}
        check("① set_default 后 refresh，b 仍是默认", 
              bool(by_dir[os.path.normcase(b)].get('default')), lst)
        check("① a 未被误标为默认", 
              not by_dir[os.path.normcase(a)].get('default'), lst)
        check("② default_interpreter() 返回 b（不是列表第一条）",
              os.path.normcase(cfg.default_interpreter()['dir']) == os.path.normcase(b),
              cfg.default_interpreter())
        # 再刷新一次仍稳定（幂等，不会每次都改写/丢标记）
        cfg.refresh_interpreters()
        lst2 = cfg.load_interpreters()
        check("① 连续两次 refresh 后默认仍稳定",
              bool({os.path.normcase(x['dir']): x for x in lst2}[
                  os.path.normcase(b)].get('default')), lst2)
        check("① stale 标记不残留（重新识别成功即清）",
              not any(x.get('stale') for x in lst2), lst2)


def t_open_project_explicit_interp():
    """③ open_project(proj, interp=a) 用 a 启动（命令里的主程序来自 a）。"""
    with tempfile.TemporaryDirectory() as root:
        a = _make_interp(root, '0.1.0.beta4')
        b = _make_interp(root, '0.1.0.beta5')
        cfg.save_interpreters([cfg.discover_interpreter(a),
                               cfg.discover_interpreter(b)])
        cfg.set_default_interpreter(cfg.discover_interpreter(b))
        ctrl = _mk_ctrl()
        scene = os.path.join(a, 'Projects', 'x.json')
        os.makedirs(os.path.dirname(scene), exist_ok=True)
        open(scene, 'w', encoding='utf-8').write('{}')
        proj = {'name': 'x', 'scene': scene, 'engine_dir': None}
        cmd_a = _capture_launch(ctrl, proj, interp=ctrl.interpreters[0])
        check("③ 显式 interp=a：命令主程序来自 a",
              any(os.path.normcase(c) == os.path.normcase(
                  os.path.join(a, 'Loom.py')) for c in cmd_a), cmd_a)
        check("③ 显式 interp=a：命令里不含 b 的路径",
              not any(os.path.normcase(b) in os.path.normcase(c) for c in cmd_a), cmd_a)
        check("③ 仍然带 --open 与场景路径",
              '--open' in cmd_a and any(os.path.normcase(scene) == os.path.normcase(c)
                                        for c in cmd_a), cmd_a)


def t_open_project_by_engine_dir():
    """④ 未显式传 interp：engine_dir 命中 a 就用 a；命中不了回退默认。"""
    with tempfile.TemporaryDirectory() as root:
        a = _make_interp(root, '0.1.0.beta4')
        b = _make_interp(root, '0.1.0.beta5')
        cfg.save_interpreters([cfg.discover_interpreter(a),
                               cfg.discover_interpreter(b)])
        cfg.set_default_interpreter(cfg.discover_interpreter(b))
        ctrl = _mk_ctrl()
        scene = os.path.join(a, 'Projects', 'y.json')
        os.makedirs(os.path.dirname(scene), exist_ok=True)
        open(scene, 'w', encoding='utf-8').write('{}')

        # engine_dir = 解释器目录本身
        cmd = _capture_launch(ctrl, {'name': 'y', 'scene': scene, 'engine_dir': a})
        check("④ engine_dir == a 的目录 -> 用 a 启动",
              any(os.path.normcase(os.path.join(a, 'Loom.py')) == os.path.normcase(c)
                  for c in cmd), cmd)

        # engine_dir = 解释器目录的父目录（Projects/ 在 <引擎根>/ 下的常见形态）
        cmd2 = _capture_launch(ctrl, {'name': 'y', 'scene': scene,
                                      'engine_dir': os.path.dirname(a)})
        check("④ engine_dir == a 的父目录 -> 仍用 a 启动",
              any(os.path.normcase(os.path.join(a, 'Loom.py')) == os.path.normcase(c)
                  for c in cmd2), cmd2)

        # engine_dir 无匹配 -> 回退默认（b）
        cmd3 = _capture_launch(ctrl, {'name': 'y', 'scene': scene,
                                      'engine_dir': os.path.join(root, 'nope')})
        check("④ engine_dir 无匹配 -> 回退默认解释器 b",
              any(os.path.normcase(os.path.join(b, 'Loom.py')) == os.path.normcase(c)
                  for c in cmd3), cmd3)

        # 没有 engine_dir 字段 -> 回退默认
        cmd4 = _capture_launch(ctrl, {'name': 'y', 'scene': scene})
        check("④ 项目无 engine_dir -> 回退默认解释器 b",
              any(os.path.normcase(os.path.join(b, 'Loom.py')) == os.path.normcase(c)
                  for c in cmd4), cmd4)


def t_ui_entry_exists():
    """只在 controller 有 API 而没有 UI 入口 == 没修：两个官方视图都要有入口。"""
    for name, path in (('TkHubView', os.path.join(REPO, 'LoomHub', 'hub_view_tk.py')),
                       ('NovaHubGUI', os.path.join(REPO, 'LoomHub', 'GUI',
                                                    'NovaHubGUI.py'))):
        src = open(path, encoding='utf-8').read()
        check("%s 有「用选中引擎打开项目」入口" % name,
              '用选中引擎打开项目' in src and '_open_project_with_interp' in src)
    src = open(os.path.join(REPO, 'LoomHub', 'hub_controller.py'),
               encoding='utf-8').read()
    check("controller.open_project 支持 interp 参数",
          'def open_project(self, project, interp=None)' in src)


if __name__ == "__main__":
    print("========== LoomHub 默认引擎切换 / 用非默认引擎打开项目 ==========")
    t_default_survives_refresh()
    t_open_project_explicit_interp()
    t_open_project_by_engine_dir()
    t_ui_entry_exists()
    if _FAILS:
        print("总结果: FAIL ❌", _FAILS)
        sys.exit(1)
    print("总结果: ALL PASS ✅")
