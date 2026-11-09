# -*- coding: utf-8 -*-
"""hub_update.py — LoomHub 自更新（H2：2026-11-09 人类指定策略，逐条照做）。

策略边界（与人类口径一一对应）：
  · 检查：启动后后台线程、延迟 ~10s、每 24h 最多一次；GET /repos/<o>/<r>/releases，
    筛 hub-v* tag，与本地 版本.json 做语义版本比较；失败/无网**静默**。
  · 下载：取 LoomHub-<ver>-Setup.exe 到 <用户根>/hub/updates/；校验 size；
    asset 带 digest(sha256) 时校验；**非 https 一律拒绝**。
  · 安装：写 updates/apply_update.cmd（等当前 PID 退出 → 静默参数 → 结束）；
    安装目录在 Program Files 需提权 → ShellExecuteW(..., 'runas', ...) 弹一次 UAC，
    失败**明确报错**并写 update.log（不得静默失败）。
  · 关闭自身：由调用方（HubController）提交后退出，本模块**不**重启 LoomHub。
  · 不自动启动：静默安装不跑 postinstall；updater 脚本里也没有启动 LoomHub 的命令。
  · 失败可见：任一步失败写 updates/update.log；下次启动用 take_pending_failure() 提示。
"""
import hashlib
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request

import hub_userpaths as up

API_BASE = 'https://api.github.com'
REPO_OWNER = 'lhy302'
REPO_NAME = 'WeaveEngine'
HUB_TAG_PREFIX = 'hub-v'
ASSET_FMT = 'LoomHub-%s-Setup.exe'
USER_AGENT = 'LoomHub-Update/0.1.3'
# 静的安装参数（人类口径原文）：/VERYSILENT /SUPPRESSMSGBOXES /NORESTART /ALLUSERS /SP-
SILENT_ARGS = ['/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART', '/ALLUSERS', '/SP-']
CHECK_INTERVAL_HOURS = 24
WAIT_MAX_SECONDS = 180          # updater 等旧进程退出的上限


# ---------------- 路径 ----------------

def updates_dir():
    """<用户根>/hub/updates（放安装包、updater 脚本与日志）。"""
    return os.path.join(up.hub_dir(), 'updates')


def _ensure_updates_dir():
    up.ensure_dir(updates_dir())
    return updates_dir()


def log_path():
    return os.path.join(updates_dir(), 'update.log')


def script_path():
    return os.path.join(updates_dir(), 'apply_update.cmd')


def last_check_file():
    return os.path.join(updates_dir(), 'last_check.txt')


def seen_file():
    return os.path.join(updates_dir(), 'update.log.seen')


def log_line(msg, level='INFO'):
    """失败/进度可见性：追加一行到 update.log（写不进去也不抛，只上 stderr）。"""
    line = '%s [%s] %s' % (time.strftime('%Y-%m-%d %H:%M:%S'), level, msg)
    try:
        _ensure_updates_dir()
        with open(log_path(), 'a', encoding='utf-8') as f:
            f.write(line + '\n')
    except OSError as e:
        print('[更新] 写 update.log 失败: %r (%s)' % (e, line), file=sys.stderr)


def take_pending_failure():
    """读上一次失败（若有且未被提示过），返回一行文本；无则 None。

    规则：update.log 里最后一条以 FAIL 开头，且其 mtime 比 .seen 标记新。
    """
    try:
        if not os.path.isfile(log_path()):
            return None
        mtime = os.path.getmtime(log_path())
        seen = os.path.getmtime(seen_file()) if os.path.isfile(seen_file()) else 0
        if mtime <= seen:
            return None
        last = None
        with open(log_path(), 'r', encoding='utf-8', errors='replace') as f:
            for line in f:
                if '[FAIL]' in line:
                    last = line.strip()
        return last
    except OSError:
        return None


def mark_failure_seen():
    try:
        _ensure_updates_dir()
        with open(seen_file(), 'w', encoding='utf-8') as f:
            f.write(time.strftime('%Y-%m-%d %H:%M:%S'))
        return True
    except OSError:
        return False


# ---------------- 版本比较 ----------------

_VER_RE = re.compile(r'^v?(\d+)\.(\d+)\.(\d+)$')


def parse_version(text):
    """'0.1.3' -> (0,1,3)；不合法返回 None（只支持 x.y.z，Hub 版本口径）。"""
    m = _VER_RE.match(str(text or '').strip())
    if not m:
        return None
    return tuple(int(x) for x in m.groups())


def is_newer(remote, local):
    """远端是否比本地新；任一不合法返回 False（宁可不提示，也不误提示）。"""
    a, b = parse_version(remote), parse_version(local)
    if a is None or b is None:
        return False
    return a > b


def local_version():
    """本地 LoomHub 版本：读 版本.json（源码/HUB_DIR、打包后的 _MEIPASS、exe 同目录）。"""
    cands = [os.path.join(up.HUB_DIR if hasattr(up, 'HUB_DIR') else '', ''),
             ]
    here = os.path.dirname(os.path.abspath(__file__))
    cands = [os.path.join(here, '版本.json'),
             os.path.join(os.path.dirname(os.path.abspath(sys.argv[0])), '版本.json')]
    mei = getattr(sys, '_MEIPASS', None)
    if mei:
        cands.insert(0, os.path.join(mei, '版本.json'))
        cands.insert(1, os.path.join(mei, '_internal', '版本.json'))
    exe_dir = os.path.dirname(os.path.abspath(sys.executable))
    cands += [os.path.join(exe_dir, '版本.json'),
              os.path.join(exe_dir, '_internal', '版本.json')]
    for p in cands:
        try:
            with open(p, 'r', encoding='utf-8') as f:
                v = str(json.load(f).get('version') or '').strip()
            if parse_version(v):
                return v
        except (OSError, ValueError):
            continue
    return ''


# ---------------- 检查 ----------------

def _request(url, token=None, timeout=15):
    """GET，返回 (status, headers, body)。仅 https（非 https 直接拒绝）。"""
    if not str(url).lower().startswith('https://'):
        return -1, {}, b'non-https url rejected'
    req = urllib.request.Request(url)
    req.add_header('User-Agent', USER_AGENT)
    req.add_header('Accept', 'application/vnd.github+json')
    if token:
        req.add_header('Authorization', 'Bearer ' + token)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, dict(resp.headers), resp.read()
    except urllib.error.HTTPError as e:
        return e.code, dict(e.headers or {}), e.read()
    except Exception as e:                     # 无网/DNS/TLS：静默（调用方决定提示与否）
        return 0, {}, str(e).encode('utf-8')


def pick_release(releases, local):
    """从 GitHub releases 里挑出"hub-v* 且比本地新、且带 Setup.exe asset"的最新一条。

    返回 dict 或 None。纯函数（无网络），便于单测。
    """
    best = None
    for rel in releases or []:
        tag = str(rel.get('tag_name') or '')
        if not tag.startswith(HUB_TAG_PREFIX):
            continue
        ver = tag[len(HUB_TAG_PREFIX):]
        if not is_newer(ver, local):
            continue
        asset = None
        want = ASSET_FMT % ver
        for a in rel.get('assets') or []:
            if a.get('name') == want:
                asset = a
                break
        if asset is None:
            continue                    # 该 release 没有对应安装包 -> 跳过
        item = {
            'version': ver,
            'tag': tag,
            'name': rel.get('name') or tag,
            'html_url': rel.get('html_url') or '',
            'asset_name': asset.get('name'),
            'download_url': asset.get('browser_download_url') or '',
            'size': int(asset.get('size') or 0),
            'digest': asset.get('digest') or '',
        }
        if best is None or is_newer(item['version'], best['version']):
            best = item
    return best


def check_update(token=None, local=None):
    """查更新。返回 {ok, update|None, reason?, local, latest?}；失败**不抛**。"""
    lv = local or local_version()
    if not lv:
        return {'ok': False, 'reason': '本地版本未知（缺 版本.json）', 'update': None}
    url = '%s/repos/%s/%s/releases?per_page=30' % (API_BASE, REPO_OWNER, REPO_NAME)
    status, _h, body = _request(url, token=token)
    if status != 200:
        # 无网/被限流都静默：只记录，不打扰用户
        log_line('检查更新失败 status=%s' % status, level='WARN')
        return {'ok': False, 'reason': '网络/接口不可用 (status=%s)' % status,
                'update': None, 'local': lv}
    try:
        releases = json.loads(body.decode('utf-8'))
    except ValueError as e:
        log_line('release JSON 解析失败: %r' % (e,), level='WARN')
        return {'ok': False, 'reason': 'release JSON 解析失败', 'update': None,
                'local': lv}
    item = pick_release(releases, lv)
    return {'ok': True, 'local': lv,
            'update': item,
            'latest': item['version'] if item else lv}


def due_for_check(hours=CHECK_INTERVAL_HOURS):
    """是否到了检查窗口（24h 最多一次）。"""
    try:
        if not os.path.isfile(last_check_file()):
            return True
        with open(last_check_file(), 'r', encoding='utf-8') as f:
            last = float(f.read().strip() or 0)
        return (time.time() - last) >= hours * 3600
    except (OSError, ValueError):
        return True


def mark_checked():
    try:
        _ensure_updates_dir()
        with open(last_check_file(), 'w', encoding='utf-8') as f:
            # 用截断而非四舍五入：写进去的时间不能"比现在还晚"，
            # 否则 hours=0 的立即复检会被算成还没到点。
            f.write('%d' % int(time.time()))
    except OSError:
        pass


# ---------------- 下载与校验 ----------------

def _sha256_file(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()


def verify_download(path, size=0, digest=''):
    """校验下载结果。返回 (ok, reason)。纯文件检查，单测可直接造文件。"""
    if not os.path.isfile(path):
        return False, '文件不存在'
    got = os.path.getsize(path)
    if size and got != int(size):
        return False, '大小不符: %d != %d' % (got, int(size))
    if got <= 0:
        return False, '空文件'
    d = str(digest or '').strip().lower()
    if d:
        if d.startswith('sha256:'):
            d = d.split(':', 1)[1]
        real = _sha256_file(path)
        if real != d:
            return False, 'sha256 不符: %s != %s' % (real, d)
    return True, ''


def download_update(item, dest_dir=None, progress_cb=None):
    """下载 Setup.exe 到 updates/（非 https 拒绝；校验 size/digest）。"""
    if not isinstance(item, dict) or not item.get('download_url'):
        return {'ok': False, 'reason': '没有下载地址'}
    url = item['download_url']
    if not url.lower().startswith('https://'):
        log_line('拒绝非 https 下载地址: %s' % url, level='FAIL')
        return {'ok': False, 'reason': '非 https 下载地址，已拒绝'}
    d = dest_dir or _ensure_updates_dir()
    up.ensure_dir(d)
    dest = os.path.join(d, item.get('asset_name') or ASSET_FMT % item.get('version'))
    tmp = dest + '.part'
    try:
        req = urllib.request.Request(url)
        req.add_header('User-Agent', USER_AGENT)
        with urllib.request.urlopen(req, timeout=120) as resp, open(tmp, 'wb') as f:
            total = int(resp.headers.get('Content-Length') or 0)
            got = 0
            while True:
                chunk = resp.read(1 << 16)
                if not chunk:
                    break
                f.write(chunk)
                got += len(chunk)
                if progress_cb:
                    try:
                        progress_cb(got, total)
                    except Exception:
                        pass
        os.replace(tmp, dest)
    except Exception as e:
        try:
            if os.path.exists(tmp):
                os.remove(tmp)
        except OSError:
            pass
        log_line('下载失败: %r (%s)' % (e, url), level='FAIL')
        return {'ok': False, 'reason': '下载失败: %r' % (e,)}
    ok, why = verify_download(dest, item.get('size') or 0, item.get('digest') or '')
    if not ok:
        log_line('下载校验失败: %s (%s)' % (why, dest), level='FAIL')
        return {'ok': False, 'reason': '校验失败: ' + why, 'path': dest}
    log_line('下载完成并校验通过: %s' % dest)
    return {'ok': True, 'path': dest, 'size': os.path.getsize(dest)}


# ---------------- 安装（写 updater 脚本 + 提权） ----------------

def build_updater_script(setup_path, pid=None, wait_max=WAIT_MAX_SECONDS):
    """生成后台 updater 脚本内容（纯函数，便于断言）。

    必须满足：① 等旧进程 PID 退出；② 静默安装参数；③ **不**启动 LoomHub。
    脚本用纯 ASCII，避免 cmd 与 UTF-8 编码打架。
    """
    pid = int(pid if pid is not None else os.getpid())
    lines = [
        '@echo off',
        'setlocal',
        'rem LoomHub updater (generated by hub_update.py; do not launch LoomHub)',
        'set "SETUP=%s"' % setup_path,
        'set "PID=%d"' % pid,
        'set "WAITMAX=%d"' % int(wait_max),
        'set /a n=0',
        ':waitloop',
        'tasklist /FI "PID eq %PID%" 2>nul | find "%PID%" >nul',
        'if errorlevel 1 goto install',
        'set /a n+=1',
        'if %n% GEQ %WAITMAX% goto install',
        'timeout /t 1 /nobreak >nul',
        'goto waitloop',
        ':install',
        # 注意 %% 转义：这一行本身还要过 % 格式化
        'start "" /wait "%%SETUP%%" %s' % ' '.join(SILENT_ARGS),
        'rem NOTE: intentionally NOT starting LoomHub here (user opens it manually)',
        'endlocal',
        'exit /b 0',
    ]
    return '\r\n'.join(lines) + '\r\n'


def write_updater_script(setup_path, pid=None):
    p = script_path()
    try:
        up.ensure_parent(p)          # 目标脚本所在目录（测试会把它指到临时目录）
    except OSError as e:
        log_line('创建 updater 目录失败: %r' % (e,), level='FAIL')
        return {'ok': False, 'reason': '创建 updater 目录失败: %r' % (e,)}
    try:
        with open(p, 'w', encoding='ascii', newline='') as f:
            f.write(build_updater_script(setup_path, pid))
    except OSError as e:
        log_line('写 updater 脚本失败: %r' % (e,), level='FAIL')
        return {'ok': False, 'reason': '写 updater 脚本失败: %r' % (e,)}
    return {'ok': True, 'path': p}


def apply_update(setup_path, pid=None):
    """提交安装任务：写脚本 → runas 提权启动（一次 UAC）→ 返回。

    调用方成功后应主动退出 Hub（这就是"暂时关闭"）。本函数**不**重启 LoomHub。
    """
    if not setup_path or not os.path.isfile(setup_path):
        log_line('安装包不存在: %r' % (setup_path,), level='FAIL')
        return {'ok': False, 'reason': '安装包不存在'}
    w = write_updater_script(setup_path, pid)
    if not w.get('ok'):
        return w
    cmd = w['path']
    launched, why = _shell_execute_runas(cmd)
    if not launched:
        log_line('提权启动 updater 失败: %s' % why, level='FAIL')
        return {'ok': False, 'reason': '提权启动失败（需要管理员权限）: %s' % why,
                'script': cmd}
    log_line('已提交安装任务: %s' % setup_path)
    return {'ok': True, 'script': cmd, 'setup': setup_path}


def _shell_execute_runas(cmd_path):
    """用 ShellExecuteW(..., 'runas', ...) 提权（用户点一次 UAC）。

    返回 (ok, 说明)。非 Windows / 提权被拒都会返回 False 并写明原因，
    由 apply_update 写 update.log —— 不静默失败。
    """
    if os.name != 'nt':
        return False, '非 Windows 平台'
    try:
        import ctypes
        rc = ctypes.windll.shell32.ShellExecuteW(
            None, 'runas', 'cmd.exe', '/c "%s"' % cmd_path, updates_dir(), 0)
        if int(rc) > 32:
            return True, ''
        return False, 'ShellExecuteW 返回 %s（UAC 被拒或无权限）' % rc
    except Exception as e:
        return False, repr(e)
