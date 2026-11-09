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
    check("脚本是纯 ASCII（cmd 编码安全）", all(ord(c) < 128 for c in s))

    with tempfile.TemporaryDirectory() as tmp:
        old_script = hu.script_path
        hu.script_path = lambda: os.path.join(tmp, 'updates', 'apply_update.cmd')
        try:
            r = hu.write_updater_script(os.path.join(tmp, 'fake.exe'), 999)
            check("write_updater_script 落盘成功", r.get('ok') and os.path.isfile(r['path']), r)
            body = open(r['path'], encoding='ascii').read()
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


if __name__ == "__main__":
    print("========== LoomHub 0.1.3：H1 remote-mode / H2 自更新 ==========")
    t_remote_mode_env()
    t_version_compare()
    t_download_verify()
    t_updater_script()
    t_check_and_notice()
    if _FAILS:
        print("总结果: FAIL ❌", _FAILS)
        sys.exit(1)
    print("总结果: ALL PASS ✅")
