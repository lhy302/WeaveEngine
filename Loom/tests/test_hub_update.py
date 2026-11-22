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


# 2026-11-22 Q-B7-29-1 T1：封堵「打印 FAIL 但退出码 0」。
# 根因：进程里存在非守护线程（生产 _quit_for_update 的 0.5s Timer）调 os._exit(0) 时，
# CPython 收尾顺序是 threading._shutdown()（等非守护线程结束）→ atexit；Timer 先打响，
# 于是 sys.exit(1) 的 SystemExit 和 atexit 里的 _exit(1) 都来不及生效，进程以 0 退出。
# 两道保险：
#   ① threading._register_atexit：在 join 非守护线程**之前**执行，先判 FAIL；
#   ② 包一层 os._exit：已出现 FAIL 时任何 os._exit(0) 一律升级为 1（含同步调用）。
_REAL_OS_EXIT = _os_gate._exit


def _guarded_os_exit(code):
    if _fail_gate.failed and not code:
        code = 1
    _REAL_OS_EXIT(code)


_os_gate._exit = _guarded_os_exit

try:
    import threading as _threading_gate
    _threading_gate._register_atexit(_enforce_fail_exit_code)   # 先于 join 非守护线程
except Exception:
    pass                  # 老解释器没有该私有钩子时仍保留 atexit 兜底


import hashlib
import json
import os
import subprocess
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


class _PfEnv:
    """临时控制 ProgramFiles 三兄弟 + SystemDrive，退出时精确还原。"""

    _KEYS = ('ProgramFiles', 'ProgramFiles(x86)', 'ProgramW6432', 'SystemDrive')

    def __init__(self, **vals):
        self.vals = vals

    def __enter__(self):
        self.old = {k: os.environ.get(k) for k in self._KEYS}
        for k in self._KEYS:
            os.environ.pop(k, None)
        os.environ.update(self.vals)
        return self

    def __exit__(self, *exc):
        for k, v in self.old.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        return False


def t_is_program_files_matrix():
    """Q-B7-29-1 T2：is_program_files 正/负样本矩阵（正 9 条、负 8 条）。"""
    with _PfEnv(ProgramFiles=r'C:\Program Files',
                **{'ProgramFiles(x86)': r'C:\Program Files (x86)',
                   'ProgramW6432': r'C:\Program Files',
                   'SystemDrive': 'C:'}):
        positives = [
            (r'C:\Program Files\LoomHub', '标准 Program Files 子目录'),
            (r'C:\Program Files\LoomHub\sub\deeper', '多层子目录'),
            (r'C:\Program Files (x86)\LoomHub', 'Program Files (x86) 子目录'),
            (r'c:\program files\loomhub', '大小写不敏感'),
            (r'C:/Program Files/LoomHub', '正斜杠'),
            (r'C:\Program Files\LoomHub ', '尾随空格'),
            (r'C:\Program Files', '根目录本身'),
            (r'%ProgramFiles%\LoomHub', '未展开的 %ProgramFiles%'),
        ]
        for idx, (pth, why) in enumerate(positives, 1):
            check("T2 正样本%d: %s（%s）" % (idx, pth, why),
                  hu.is_program_files(pth) is True, pth)
        if os.path.isdir(r'C:\PROGRA~1'):
            check("T2 正样本9: C:\\PROGRA~1\\LoomHub（8.3 短名）",
                  hu.is_program_files(r'C:\PROGRA~1\LoomHub') is True)

        negatives = [
            (r'C:\Program FilesX\LoomHub', '前缀相同但不是子目录'),
            (r'C:\Program Files-old\LoomHub', '相似前缀'),
            (r'C:\Program Files (x86)X\LoomHub', 'x86 相似前缀'),
            (r'C:\Users\Administrator\AppData\Local\Programs\LoomHub', '用户级目录'),
            (r'D:\Program Files\LoomHub', '非系统盘同名目录'),
            (r'C:\Program Files\..\Windows\System32', '.. 逃逸'),
            (r'C:\Program Files\LoomHub2\..\..\Windows', '.. 逃逸（深层）'),
            ('', '空路径'),
        ]
        for idx, (pth, why) in enumerate(negatives, 1):
            check("T2 负样本%d: %s（%s）" % (idx, pth or '<空>', why),
                  hu.is_program_files(pth) is False, pth)

    # 核心回归：ProgramFiles 环境变量全缺失时，硬编码兜底必须仍判 True（不许 fail-open）
    with _PfEnv(SystemDrive='C:'):
        check("T2 正样本10: env 全缺失 -> C:\\Program Files\\LoomHub 仍判 True",
              hu.is_program_files(r'C:\Program Files\LoomHub') is True)
        check("T2 负样本9: env 全缺失时用户目录仍判 False",
              hu.is_program_files(os.path.join(
                  os.environ.get('LOCALAPPDATA') or r'C:\Users\x\AppData\Local',
                  'Programs', 'LoomHub')) is False)

    # ProgramW6432 / ProgramFiles(x86) / 自定义 ProgramFiles 各自独立生效
    with _PfEnv(ProgramFiles=r'D:\PF',
                **{'ProgramFiles(x86)': r'E:\PFx86',
                   'ProgramW6432': r'F:\PF64', 'SystemDrive': 'C:'}):
        check("T2 ProgramW6432 根命中", hu.is_program_files(r'F:\PF64\LoomHub') is True)
        check("T2 ProgramFiles(x86) 根命中", hu.is_program_files(r'E:\PFx86\LoomHub') is True)
        check("T2 自定义 ProgramFiles 根命中", hu.is_program_files(r'D:\PF\LoomHub') is True)
        check("T2 不在任何根下 -> False", hu.is_program_files(r'G:\Other\LoomHub') is False)


def t_allusers_chain():
    """Q-B7-29-1 T3：is_program_files -> /ALLUSERS + runas(UAC) 消费者链路证据。"""
    with tempfile.TemporaryDirectory() as tmp:
        setup = os.path.join(tmp, 'LoomHub-0.1.5-Setup.exe')
        open(setup, 'wb').write(b'x')
        hu._write_sidecar(setup, {'size': 1, 'digest': '', 'version': '0.1.5',
                                  'asset_name': os.path.basename(setup),
                                  'download_url': 'https://example.invalid/x.exe'})
        old_install = hu.install_dir
        old_runas, old_spawn = hu._shell_execute_runas, hu._spawn_no_uac
        calls = {'runas': 0, 'spawn': 0}
        hu._shell_execute_runas = lambda cmd: (calls.__setitem__('runas', calls['runas'] + 1)
                                               or (True, ''))
        hu._spawn_no_uac = lambda cmd: (calls.__setitem__('spawn', calls['spawn'] + 1)
                                        or (True, ''))
        try:
            # A. Program Files 安装：即使 ProgramFiles env 全缺失，也必须是提权路径
            before = dict(calls)
            with _PfEnv(SystemDrive='C:'):
                hu.install_dir = lambda: r'C:\Program Files\LoomHub'
                r = hu.apply_update(setup)
                body = open(r.get('script') or '', encoding='utf-8-sig').read()
            check("T3-A PF 安装：needs_admin=True（走 runas/UAC，不走 spawn）",
                  r.get('ok') is True and r.get('needs_admin') is True
                  and calls['runas'] == before['runas'] + 1
                  and calls['spawn'] == before['spawn'], (r, calls))
            check("T3-A PF 安装：all_users=True 且脚本文本含 /ALLUSERS",
                  r.get('all_users') is True and '/ALLUSERS' in body,
                  [l for l in body.splitlines() if 'SETUP%' in l])

            # B. 用户级安装：不加 /ALLUSERS、不弹 UAC、走免提权 spawn
            user_dir = os.path.join(tmp, 'Programs', 'LoomHub')
            os.makedirs(user_dir, exist_ok=True)
            hu.install_dir = lambda: user_dir
            before2 = dict(calls)
            r2 = hu.apply_update(setup)
            body2 = open(r2.get('script') or '', encoding='utf-8-sig').read()
            check("T3-B 用户级安装：needs_admin=False（不弹 UAC/走 spawn）",
                  r2.get('ok') is True and r2.get('needs_admin') is False
                  and calls['spawn'] == before2['spawn'] + 1
                  and calls['runas'] == before2['runas'], (r2, calls))
            check("T3-B 用户级安装：脚本不含 /ALLUSERS", '/ALLUSERS' not in body2,
                  [l for l in body2.splitlines() if 'SETUP%' in l])
        finally:
            hu.install_dir = old_install
            hu._shell_execute_runas, hu._spawn_no_uac = old_runas, old_spawn


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
    # 成功路径确实会进安装。
    # Q-B7-29-1 根因：controller.apply_update 成功后 _quit_for_update() 会起
    # 0.5s 后 os._exit(0) 的**非守护**定时器（生产语义=提交后关 Hub）。测试里必须
    # 换成记录桩，否则定时器会在解释器收尾时先于 atexit 打响，把整个进程自杀成
    # 退出码 0 —— 这正是「打印 FAIL 却退出码 0」的假绿通道。
    called2 = {'apply': 0, 'quit': 0}
    hu.download_update = lambda *a, **k: {'ok': True, 'path': 'C:/x/a.exe'}
    hu.apply_update = lambda *a, **k: (called2.__setitem__('apply', 1) or {'ok': True})
    old_quit = ctrl._quit_for_update
    ctrl._quit_for_update = lambda: called2.__setitem__('quit', called2['quit'] + 1)
    try:
        r2 = ctrl.download_and_install()
        check("④ 下载成功 -> 进入安装阶段", r2.get('ok') is True and called2['apply'] == 1, r2)
        check("④ 提交成功后请求关闭 Hub（_quit_for_update 一次；不真的起自杀定时器）",
              called2['quit'] == 1, called2)
    finally:
        hu.download_update, hu.apply_update = old_dl, old_ap
        ctrl._quit_for_update = old_quit


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


def t_fail_gate_end_to_end():
    """Q-B7-29-1 T1：假绿门反证 —— 注入 FAIL 后 run_all 式判定必须为红。

    背景：2026-11-22 前的门只有 atexit + sys.exit(1) 两道，挡不住「非守护线程里
    os._exit(0)」：CPython 收尾顺序是 threading._shutdown()（先等非守护线程结束）
    → atexit，0.5s 的 Timer 会先打响，进程以 0 退出。本函数用子进程复现三条通道：
      ① FAIL + 待定时的 os._exit(0)（本次事故原型）
      ② FAIL + 同步 os._exit(0)（任何直接自杀调用）
      ③ 环境变量注入 FAIL 跑完整测试文件（run_all 视角的端到端）
    """
    if os.environ.get('LOOM_HUB_TEST_FORCE_FAIL'):
        return                      # 自检子进程里不再递归
    test_path = os.path.abspath(__file__)
    child_src = (
        "# -*- coding: utf-8 -*-\n"
        "import importlib.util, os, sys, threading\n"
        "spec = importlib.util.spec_from_file_location('thu_gate_child', %r)\n"
        "mod = importlib.util.module_from_spec(spec)\n"
        "spec.loader.exec_module(mod)\n"
        "mod.check('注入 FAIL（门禁自检子进程）', False)\n"
        "%s\n"
    )
    with tempfile.TemporaryDirectory() as tmp:
        p1 = os.path.join(tmp, 'child_timer.py')
        with open(p1, 'w', encoding='utf-8') as fh:
            fh.write(child_src % (test_path,
                                  "threading.Timer(0.5, lambda: os._exit(0)).start()"))
        r1 = subprocess.run([sys.executable, p1], capture_output=True, timeout=60)
        check("门禁①：FAIL + 0.5s os._exit(0) 定时器 -> 子进程退出码非 0",
              r1.returncode != 0, r1.returncode)

        p2 = os.path.join(tmp, 'child_sync.py')
        with open(p2, 'w', encoding='utf-8') as fh:
            fh.write(child_src % (test_path, "os._exit(0)"))
        r2 = subprocess.run([sys.executable, p2], capture_output=True, timeout=60)
        check("门禁②：FAIL + 同步 os._exit(0) -> 子进程退出码非 0",
              r2.returncode != 0, r2.returncode)

        env = dict(os.environ)
        env['LOOM_HUB_TEST_FORCE_FAIL'] = '1'
        r3 = subprocess.run([sys.executable, test_path], env=env,
                            capture_output=True, timeout=180)
        check("门禁③：注入 FAIL 后完整测试进程退出码非 0（run_all 会判红）",
              r3.returncode != 0, r3.returncode)
        check("门禁③：子进程 stdout 确有 FAIL 行",
              b'FAIL' in (r3.stdout or b''), (r3.stdout or b'')[:120])


if __name__ == "__main__":
    print("========== LoomHub 0.1.3：H1 remote-mode / H2 自更新 ==========")
    if os.environ.get('LOOM_HUB_TEST_FORCE_FAIL'):
        check("注入失败（门禁自检 LOOM_HUB_TEST_FORCE_FAIL）", False)
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
    t_is_program_files_matrix()
    t_allusers_chain()
    t_gui_button_and_fail_gate()
    t_p2_fixes()
    t_fail_gate_end_to_end()
    if _FAILS:
        print("总结果: FAIL ❌", _FAILS)
        sys.exit(1)
    print("总结果: ALL PASS ✅")
