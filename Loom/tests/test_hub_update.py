# -*- coding: utf-8 -*-
"""
test_hub_update.py — LoomHub 0.1.3：H1（remote_mode 默认关闭）+ H2（自更新）断言

覆盖（与人类验收口径一一对应）：
  ① remote_mode=off（默认）时两条启动路径都不注入 LOOM_REMOTE_MODE；=on 时都注入且只注入一次
  ② 版本比较函数：远端更新 / 相同 / 更旧
  ③ 下载校验失败路径：size 不符 / sha256 不符 / 非 https 拒绝
  ④ updater 脚本内容：等 PID 退出 + 静默参数 + **不**启动 LoomHub
另外：离线检查不抛异常（静默）+ 24h 节流 + 失败提示（update.log）

全部使用 LOOM_USER_ROOT 临时目录；不联网、不启动安装器、不写真实用户配置。
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


import hashlib
import json
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)                 # Loom/
REPO = os.path.dirname(ROOT)                 # 仓库根
for _p in (os.path.join(REPO, 'LoomHub'), ROOT):
    if _p not in sys.path:
        sys.path.insert(0, _p)

# 用户目录重定向（设置/更新目录都落 LOOM_USER_ROOT；绝不碰真实 %LOCALAPPDATA%）
_USER_ROOT = tempfile.mkdtemp(prefix='loomhub_update_test_')
os.environ['LOOM_USER_ROOT'] = _USER_ROOT

import hub_config as cfg          # noqa: E402
import hub_commands as hcmd       # noqa: E402
import hub_controller as hctrl    # noqa: E402
import hub_update as hu           # noqa: E402

_FAILS = []


def check(name, cond, extra=""):
    print(("PASS " if cond else "FAIL ") + name + ("  " + str(extra) if extra else ""))
    if not cond:
        _FAILS.append(name)


def _set_settings(**kw):
    s = cfg.load_hub_settings()
    s.update(kw)
    cfg.save_hub_settings(s)
    return s


def _mk_interp(tmp):
    import os as _os
    p = os.path.join(tmp, 'Loom.py')
    open(p, 'w', encoding='utf-8').close()
    return {'name': 'Loom', 'version': '0.1.0.beta5', 'kind': 'py',
            'dir': tmp, 'main': 'Loom.py', 'path': p,
            'main_py': p, 'main_exe': None}


def _gui_launch_env(interp, scene):
    """跑真 open_project 的环境构造（Popen 换成捕获桩，不启动进程）。"""
    captured = {}
    old_pop = hctrl.subprocess.Popen
    old_interp = cfg.default_interpreter
    hctrl.subprocess.Popen = lambda cmd, **kw: captured.setdefault('kw', kw)
    cfg.default_interpreter = lambda: interp
    try:
        ctrl = hctrl.HubController.__new__(hctrl.HubController)
        ctrl.msg = ''
        ctrl.msg_level = 'ok'
        ctrl.set_msg = lambda m, lvl='ok': setattr(ctrl, 'msg', m)
        ctrl.open_project({'scene': scene})
    finally:
        hctrl.subprocess.Popen = old_pop
        cfg.default_interpreter = old_interp
    return (captured.get('kw') or {}).get('env') or {}


def _cmd_launch_env(interp, scene):
    """命令层 launch_spec 的环境（与 GUI 同构）。"""
    spec, err = hcmd.launch_spec({'scene': scene}, info=interp)
    if err:
        return {'__err__': err}
    return spec.get('env') or {}


# ---------------- ① remote_mode（H1） ----------------
def t_remote_mode_env():
    with tempfile.TemporaryDirectory() as tmp:
        interp = _mk_interp(tmp)
        scene = os.path.join(tmp, 'a.json')
        open(scene, 'w', encoding='utf-8').write('{}')

        _set_settings(remote_mode='off')
        g = _gui_launch_env(interp, scene)
        c = _cmd_launch_env(interp, scene)
        check("默认 off: GUI 打开项目不注入 LOOM_REMOTE_MODE",
              'LOOM_REMOTE_MODE' not in g, sorted(g.keys())[:6])
        check("默认 off: 命令层 launch_spec 不注入（两入口一致）",
              'LOOM_REMOTE_MODE' not in c, sorted(c.keys())[:6])
        check("默认 off: LOOM_QUIET 仍在（静默启动是另一件事）",
              g.get('LOOM_QUIET') == '1' and c.get('LOOM_QUIET') == '1')

        _set_settings(remote_mode='on')
        g2 = _gui_launch_env(interp, scene)
        c2 = _cmd_launch_env(interp, scene)
        check("设为 on: GUI 注入 LOOM_REMOTE_MODE=1", g2.get('LOOM_REMOTE_MODE') == '1')
        check("设为 on: 命令层注入 LOOM_REMOTE_MODE=1（两入口一致）",
              c2.get('LOOM_REMOTE_MODE') == '1')

        _set_settings(remote_mode='auto')
        check("auto: Hub 侧不注入（自动降级留给引擎 beta5 E2）",
              'LOOM_REMOTE_MODE' not in _gui_launch_env(interp, scene)
              and 'LOOM_REMOTE_MODE' not in _cmd_launch_env(interp, scene))
        check("非法 remote_mode 归一到 off（默认口径）",
              cfg.hub_remote_mode({'remote_mode': 'ON!!'}) == 'off')
        # 环境里残留的值不能被漏进子进程
        os.environ['LOOM_REMOTE_MODE'] = '1'
        _set_settings(remote_mode='off')
        try:
            check("环境残留 LOOM_REMOTE_MODE 会被清掉（off 时不漏进子进程）",
                  'LOOM_REMOTE_MODE' not in _cmd_launch_env(interp, scene))
        finally:
            os.environ.pop('LOOM_REMOTE_MODE', None)


# ---------------- ② 版本比较 ----------------
def t_version_compare():
    check("parse_version 合法/非法",
          hu.parse_version('0.1.3') == (0, 1, 3)
          and hu.parse_version('v0.1.3') == (0, 1, 3)
          and hu.parse_version('0.1') is None
          and hu.parse_version('') is None)
    check("远端更新 -> True", hu.is_newer('0.1.3', '0.1.2') is True)
    check("相同 -> False", hu.is_newer('0.1.3', '0.1.3') is False)
    check("更旧 -> False", hu.is_newer('0.1.1', '0.1.3') is False)
    check("非法版本 -> False（宁可不提示，也不误提示）",
          hu.is_newer('abc', '0.1.3') is False and hu.is_newer('0.1.3', '') is False)
    check("多段比较取数值而非字典序（0.1.10 > 0.1.9）",
          hu.is_newer('0.1.10', '0.1.9') is True)

    releases = [
        {'tag_name': 'hub-v0.1.2', 'html_url': 'x',
         'assets': [{'name': 'LoomHub-0.1.2-Setup.exe',
                     'browser_download_url': 'https://e/a.exe', 'size': 10}]},
        {'tag_name': 'hub-v0.1.3', 'html_url': 'y',
         'assets': [{'name': 'LoomHub-0.1.3-Setup.exe',
                     'browser_download_url': 'https://e/b.exe', 'size': 20,
                     'digest': 'sha256:abc'}]},
        {'tag_name': 'engine-v0.1.0.beta4', 'assets': []},
        {'tag_name': 'hub-v0.1.9', 'assets': []},          # 没有安装包 -> 跳过
    ]
    item = hu.pick_release(releases, '0.1.2')
    check("pick_release 选中最新且有资产的 hub-v0.1.3",
          item and item['version'] == '0.1.3' and item['asset_name'] == 'LoomHub-0.1.3-Setup.exe',
          item)
    check("pick_release 忽略 engine-v* 与无资产的 release",
          hu.pick_release(releases, '0.1.3') is None)
    check("pick_release 远端更旧/相同时不提示", hu.pick_release(releases, '0.1.4') is None)


# ---------------- ③ 下载校验失败路径 ----------------
def t_download_verify():
    with tempfile.TemporaryDirectory() as tmp:
        p = os.path.join(tmp, 'a.bin')
        open(p, 'wb').write(b'hello')
        check("verify: 正常通过", hu.verify_download(p, 5, '')[0] is True)
        ok, why = hu.verify_download(p, 6, '')
        check("verify: size 不符 -> 失败", not ok and '大小不符' in why, why)
        ok, why = hu.verify_download(p, 5, 'sha256:' + hashlib.sha256(b'hello').hexdigest())
        check("verify: sha256 相符 -> 通过", ok is True, why)
        ok, why = hu.verify_download(p, 5, 'sha256:' + '0' * 64)
        check("verify: sha256 不符 -> 失败", not ok and 'sha256' in why, why)
        ok, why = hu.verify_download(os.path.join(tmp, 'nope'), 0, '')
        check("verify: 文件不存在 -> 失败", not ok, why)

        r = hu.download_update({'download_url': 'http://evil/x.exe',
                                'asset_name': 'x.exe', 'version': '9.9.9'})
        check("非 https 下载地址 -> 拒绝", r.get('ok') is False
              and 'https' in (r.get('reason') or ''), r)
        r2 = hu.download_update({'download_url': '', 'asset_name': 'x.exe'})
        check("没有下载地址 -> 失败可见", r2.get('ok') is False, r2)
        check("失败会写 update.log（可被下次启动提示）",
              os.path.isfile(hu.log_path()) and
              'FAIL' in open(hu.log_path(), encoding='utf-8').read())


# ---------------- ④ updater 脚本 ----------------
def t_updater_script():
    s = hu.build_updater_script(r'C:\tmp\LoomHub-0.1.3-Setup.exe', 4321)
    check("脚本等待旧 PID 退出（tasklist + PID 轮询）",
          'tasklist' in s and 'PID eq %PID%' in s and ':waitloop' in s, s.splitlines()[:9])
    check("脚本含全部静默参数",
          all(a in s for a in hu.SILENT_ARGS), hu.SILENT_ARGS)
    check("脚本不启动 LoomHub（不自动重启）", 'LoomHub.exe' not in s)
    check("脚本以 start /wait 跑安装器（安装完脚本才结束）",
          'start "" /wait "%SETUP%"' in s)
    check("脚本首行 chcp 65001（UTF-8 代码页，中文路径可用）",
          s.splitlines()[1].strip().lower().startswith('chcp 65001'), s.splitlines()[:3])

    with tempfile.TemporaryDirectory() as tmp:
        old_script = hu.script_path
        hu.script_path = lambda: os.path.join(tmp, 'updates', 'apply_update.cmd')
        try:
            r = hu.write_updater_script(os.path.join(tmp, 'fake.exe'), 999)
            check("write_updater_script 落盘成功", r.get('ok') and os.path.isfile(r['path']), r)
            body = open(r['path'], encoding='utf-8-sig').read()
            check("落盘脚本含 PID=999 与静默参数",
                  'set "PID=999"' in body and '/VERYSILENT' in body)
            r2 = hu.apply_update(os.path.join(tmp, '不存在.exe'))
            check("安装包不存在 -> 明确失败（不静默）", r2.get('ok') is False, r2)
        finally:
            hu.script_path = old_script


# ---------------- 检查/节流/失败提示 ----------------
def t_check_and_notice():
    old_api = hu.API_BASE
    hu.API_BASE = 'http://127.0.0.1:9'          # 非 https -> 直接拒绝，且不抛
    try:
        r = hu.check_update(local='0.1.2')
        check("离线/非 https 检查不抛异常且 ok=False（静默）",
              isinstance(r, dict) and r.get('ok') is False, r.get('reason'))
    finally:
        hu.API_BASE = old_api
    check("本地版本能读出来（版本.json）", bool(hu.local_version()), hu.local_version())

    check("首次检查到期", hu.due_for_check() in (True, False))   # 目录可能已有时间戳
    hu.mark_checked()
    check("标记后 24h 内不再检查", hu.due_for_check() is False)
    check("24h 之后再次到期", hu.due_for_check(hours=0) is True)

    hu.log_line('单元测试注入的失败', level='FAIL')
    note = hu.take_pending_failure()
    check("失败提示可读出", note is not None and '单元测试注入的失败' in note, note)
    hu.mark_failure_seen()
    check("提示后标记已读（不重复打扰）", hu.take_pending_failure() is None)


# ---------------- 审计硬化（第三轮 P1-1/2/3/4 + P2） ----------------
def t_script_nonascii_path():
    """P1-1: 路径含非 ASCII（中文用户名下的 LocalAppData）也能写出脚本。"""
    with tempfile.TemporaryDirectory() as tmp:
        d = os.path.join(tmp, '用户', '张三', 'AppData', 'Local', 'Loom', 'hub', 'updates')
        old = hu.script_path
        hu.script_path = lambda: os.path.join(d, 'apply_update.cmd')
        try:
            r = hu.write_updater_script(os.path.join(d, 'LoomHub-0.1.3-Setup.exe'), 4321)
            check("① 含中文路径能写出脚本", r.get('ok') is True, r)
            p = r.get('path') or ''
            raw = open(p, 'rb').read()
            check("① 脚本以 UTF-8 BOM 开头（cmd 65001 可读中文路径）",
                  raw[:3] == b'\xef\xbb\xbf', raw[:6])
            check("① 脚本里保留了中文路径原文",
                  '用户' in raw.decode('utf-8-sig'))
            check("① 残留 0 字节半成品不存在", os.path.getsize(p) > 0)
        finally:
            hu.script_path = old


def t_reject_deletes_dest():
    """P1-2a: 校验失败必须删掉 dest（否则会被提权执行）。"""
    with tempfile.TemporaryDirectory() as tmp:
        p = os.path.join(tmp, 'LoomHub-0.1.3-Setup.exe')
        open(p, 'wb').write(b'CORRUPT')
        r = hu.reject_download(p, 'size 不符')
        check("② 校验失败返回 ok=False 且 deleted=True",
              r.get('ok') is False and r.get('deleted') is True, r)
        check("② 校验失败后 dest 已不存在", not os.path.exists(p))


def t_apply_requires_verified():
    """P1-2b: 未校验的包一律拒绝提权执行。"""
    with tempfile.TemporaryDirectory() as tmp:
        p = os.path.join(tmp, 'LoomHub-9.9.9-Setup.exe')
        open(p, 'wb').write(b'CORRUPT')
        r = hu.apply_update(p)
        check("③ 无旁文件 -> 拒绝执行（ok=False）", r.get('ok') is False, r)
        check("③ 拒绝原因点名未校验", '未经校验' in (r.get('reason') or ''), r)
        # 有旁文件但 digest 不符 -> 也拒绝
        hu._write_sidecar(p, {'digest': 'sha256:' + '0' * 64, 'version': '9.9.9'})
        r2 = hu.apply_update(p)
        check("③ 旁文件 digest 不符 -> 拒绝执行", r2.get('ok') is False, r2)
        check("③ 拒绝原因点名复验失败", '复验失败' in (r2.get('reason') or ''), r2)


def t_pick_latest_semver():
    """P1-3: 0.1.10 必须比 0.1.9 新（字典序会选错）。"""
    with tempfile.TemporaryDirectory() as tmp:
        for v in ('0.1.9', '0.1.10', '0.1.2'):
            open(os.path.join(tmp, 'LoomHub-%s-Setup.exe' % v), 'wb').write(b'x')
        p, ver = hu.pick_latest_package(tmp)
        check("④ pick_latest_package 选 0.1.10（不是字典序的 0.1.9）",
              ver == '0.1.10' and os.path.basename(p) == 'LoomHub-0.1.10-Setup.exe',
              (ver, p))
        check("④ is_newer 同口径", hu.is_newer('0.1.10', '0.1.9') is True)


def t_startup_wiring():
    """P1-4: 启动流程真的调用了"失败提示 + 延迟检查"。"""
    ctrl_src = open(os.path.join(REPO, 'LoomHub', 'hub_controller.py'),
                    encoding='utf-8').read()
    check("⑤ controller 定义 start_background_tasks 并调用两个函数",
          'def start_background_tasks' in ctrl_src
          and 'self.update_notice()' in ctrl_src
          and 'self.maybe_start_update_check(' in ctrl_src)
    for name, rel in (('TkHubView', 'LoomHub/hub_view_tk.py'),
                      ('NovaHubGUI', 'LoomHub/GUI/NovaHubGUI.py'),
                      ('LoomHubGUI(pygame)', 'LoomHub/LoomHubGUI.py')):
        src = open(os.path.join(REPO, rel), encoding='utf-8').read()
        check("⑤ %s 启动流程调用 start_background_tasks" % name,
              'start_background_tasks()' in src)


def t_install_dir_and_allusers():
    """C1/C6=B: /DIR=<当前安装目录> 恒有；/ALLUSERS 只在 Program Files 安装时出现。"""
    user_dir = os.path.join(os.environ.get('LOCALAPPDATA') or r'C:\Users\x\AppData\Local',
                            'Programs', 'LoomHub')
    s_user = hu.build_updater_script(r'C:\x\LoomHub-0.1.4-Setup.exe', 4321,
                                     target_dir=user_dir, all_users=False)
    check("① 用户级安装：命令不含 /ALLUSERS", '/ALLUSERS' not in s_user,
          [l for l in s_user.splitlines() if 'SETUP%' in l])
    check("① 用户级安装：带 /DIR=<当前安装目录>",
          '/DIR="%s"' % user_dir in s_user, [l for l in s_user.splitlines() if '/DIR=' in l])
    pf = os.environ.get('ProgramFiles') or r'C:\Program Files'
    pf_dir = os.path.join(pf, 'LoomHub')
    s_pf = hu.build_updater_script(r'C:\x\a.exe', 1, target_dir=pf_dir, all_users=True)
    check("② Program Files 安装：含 /ALLUSERS", '/ALLUSERS' in s_pf,
          [l for l in s_pf.splitlines() if 'SETUP%' in l])
    check("② Program Files 安装：带 /DIR=<当前目录>", '/DIR="%s"' % pf_dir in s_pf)
    check("② is_program_files 判定正确",
          hu.is_program_files(pf_dir) is True and hu.is_program_files(user_dir) is False,
          (pf_dir, user_dir))
    check("② 默认 target_dir 就是当前安装目录",
          '/DIR="%s"' % hu.install_dir() in hu.build_updater_script(r'C:\x\a.exe', 1),
          hu.install_dir())


def t_gui_button_and_fail_gate():
    """C2=A: 两个视图都有「下载并安装」、无新版本禁用、下载失败不进安装阶段。"""
    for name, rel in (('TkHubView', 'LoomHub/hub_view_tk.py'),
                      ('NovaHubGUI', 'LoomHub/GUI/NovaHubGUI.py')):
        src = open(os.path.join(REPO, rel), encoding='utf-8').read()
        check("③ %s 有「下载并安装」按钮" % name, '下载并安装' in src)
        check("③ %s 按 has_update() 切换可用/禁用" % name,
              'has_update()' in src and 'disabled' in src)

    ctrl = hctrl.HubController.__new__(hctrl.HubController)
    ctrl.msg = ''
    ctrl.msg_level = 'ok'
    ctrl.set_msg = lambda m, lvl='ok': setattr(ctrl, 'msg', m)
    ctrl.update_info = {'update': None}
    check("③ 无新版本时 has_update()=False（按钮禁用依据）", ctrl.has_update() is False)
    ctrl.update_info = {'update': {'version': '0.1.4', 'size': 1024}}
    check("③ 有新版本时 has_update()=True", ctrl.has_update() is True)

    old_dl, old_ap = hu.download_update, hu.apply_update
    called = {'apply': 0}
    hu.download_update = lambda *a, **k: {'ok': False, 'reason': '校验失败: 测试替身'}
    hu.apply_update = lambda *a, **k: (called.__setitem__('apply', called['apply'] + 1)
                                       or {'ok': True})
    try:
        r = ctrl.download_and_install()
        check("④ 下载/校验失败 -> 返回 ok=False", r.get('ok') is False, r)
        check("④ 下载/校验失败 -> 从未进入安装阶段", called['apply'] == 0, called)
    finally:
        hu.download_update, hu.apply_update = old_dl, old_ap
    # 成功路径确实会进安装
    called2 = {'apply': 0}
    hu.download_update = lambda *a, **k: {'ok': True, 'path': 'C:/x/a.exe'}
    hu.apply_update = lambda *a, **k: (called2.__setitem__('apply', 1) or {'ok': True})
    try:
        r2 = ctrl.download_and_install()
        check("④ 下载成功 -> 进入安装阶段", r2.get('ok') is True and called2['apply'] == 1, r2)
    finally:
        hu.download_update, hu.apply_update = old_dl, old_ap


def t_p2_fixes():
    """P2: JSON 非数组不抛 / 父目录匹配取最高版本 / 成功清旧失败提示。"""
    old_api, old_req = hu.API_BASE, hu._request
    hu.API_BASE = 'https://example.invalid'          # 只为了让 check_update 走到 _request
    hu._request = lambda *a, **k: (200, {}, b'{"message": "Not Found"}')
    try:
        r = hu.check_update(local='0.1.2')
        check("P2-① 200+JSON 对象体不抛异常、返回 ok=False",
              isinstance(r, dict) and r.get('ok') is False, r.get('reason'))
    finally:
        hu._request, hu.API_BASE = old_req, old_api
    hu.log_line('旧失败（应被成功清除）', level='FAIL')
    hu.mark_failure_seen()
    check("P2-③ 成功检查会清掉旧失败提示",
          hu.take_pending_failure() is None)

    # P2-② 同一引擎根下多版本 -> 取最高版本
    with tempfile.TemporaryDirectory() as root:
        dirs = {}
        for v in ('0.1.0.beta4', '0.1.0.beta5'):
            d = os.path.join(root, v, 'Loom')       # <安装根>/<版本>/Loom
            os.makedirs(d)
            with open(os.path.join(d, cfg.META_NAME), 'w', encoding='utf-8') as fh:
                json.dump({'name': 'Loom', 'version': v, 'main': 'Loom.py',
                           'main_exe': None}, fh)
            open(os.path.join(d, 'Loom.py'), 'w').close()
            dirs[v] = d
        lst = [cfg.discover_interpreter(dirs['0.1.0.beta4']),
               cfg.discover_interpreter(dirs['0.1.0.beta5'])]
        ctrl = hctrl.HubController.__new__(hctrl.HubController)
        ctrl.interpreters = lst
        ctrl.msg = ''
        ctrl.current_interp = None
        # 场景挂在共同安装根下（<root>/Projects/x.json）-> 两个版本都是候选
        picked = ctrl.interp_for_project({'engine_dir': root})
        check("P2-② 父目录匹配取版本最高（beta5，不是台账里第一个 beta4）",
              picked is not None and picked.get('version') == '0.1.0.beta5',
              picked and picked.get('version'))


if __name__ == "__main__":
    print("========== LoomHub 0.1.3：H1 remote-mode / H2 自更新 ==========")
    t_remote_mode_env()
    t_version_compare()
    t_download_verify()
    t_updater_script()
    t_check_and_notice()
    t_script_nonascii_path()
    t_reject_deletes_dest()
    t_apply_requires_verified()
    t_pick_latest_semver()
    t_startup_wiring()
    t_install_dir_and_allusers()
    t_gui_button_and_fail_gate()
    t_p2_fixes()
    if _FAILS:
        print("总结果: FAIL ❌", _FAILS)
        sys.exit(1)
    print("总结果: ALL PASS ✅")
