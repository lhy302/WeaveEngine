# -*- coding: utf-8 -*-
"""hub_github.py — LoomHub GitHub 集成（2026-10-19）

功能：
  - list_engine_releases(token=None): 拉取 WeaveEngine 仓库的引擎 release 列表
  - download_asset(url, dest, progress_cb=None, cancel_flag=None): 流式下载
  - load_token() / save_token(tok): 保存到 %APPDATA%\\LoomHub\\settings.json
  - get_token_from_git(): 从 git credential manager 提取 token（免手动输入）

设计：
  - 全用 stdlib（urllib），零外部依赖
  - Release tag 前缀：engine-v*（如 engine-v0.1.0.beta1）
  - Token 可选：匿名 60 次/小时，带 token 5000 次/小时
  - 下载走 github.com 直链，无需 token（release asset 都是公开的）
"""
import json
import os
import re
import subprocess
import threading
import time
import urllib.error
import urllib.request

REPO_OWNER = 'lhy302'
REPO_NAME = 'WeaveEngine'
API_BASE = 'https://api.github.com'
TAG_PREFIX = 'engine-v'
USER_AGENT = 'LoomHub/0.1.0'

# 2026-10-19: GitHub release 下载在国内可能极慢（30 KB/s 级）.
# 直连失败/慢速时自动切以下镜像（前缀拼接原 URL）.
# 顺序：常用/稳定优先.
MIRRORS = [
    'https://ghfast.top/',
    'https://gh-proxy.com/',
    'https://ghproxy.net/',
    'https://github.moeyy.xyz/',
]


def _mirror_urls(url):
    """生成下载候选 URL 列表（原 URL 第一优先，其后各镜像）."""
    urls = [url]
    for prefix in MIRRORS:
        urls.append(prefix + url)
    return urls


# ---------------- Token 管理（%APPDATA%\LoomHub\settings.json） ----------------

def _settings_dir():
    base = os.environ.get('APPDATA') or os.path.expanduser('~')
    p = os.path.join(base, 'LoomHub')
    try:
        os.makedirs(p, exist_ok=True)
    except OSError:
        pass
    return p


def _settings_path():
    return os.path.join(_settings_dir(), 'settings.json')


def load_token():
    """读本地保存的 GitHub Token（可能为空字符串）."""
    try:
        with open(_settings_path(), 'r', encoding='utf-8') as f:
            return json.load(f).get('github_token', '')
    except Exception:
        return ''


def save_token(token):
    """保存 GitHub Token（空串 = 清除）."""
    p = _settings_path()
    data = {}
    if os.path.isfile(p):
        try:
            with open(p, 'r', encoding='utf-8') as f:
                data = json.load(f)
        except Exception:
            data = {}
    data['github_token'] = (token or '').strip()
    with open(p, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def get_token_from_git():
    """从 git credential manager 提取 token（用户已有 GitHub 凭据时免手动）.
    只读，不弹窗（GIT_TERMINAL_PROMPT=0）。失败返回空串."""
    try:
        env = dict(os.environ)
        env['GIT_TERMINAL_PROMPT'] = '0'
        r = subprocess.run(
            ['git', 'credential', 'fill'],
            input='protocol=https\nhost=github.com\n\n',
            capture_output=True, text=True, timeout=10, env=env)
        if r.returncode != 0:
            return ''
        for line in r.stdout.splitlines():
            if line.startswith('password='):
                return line[len('password='):].strip()
    except Exception:
        pass
    return ''


# ---------------- GitHub API ----------------

def _request(url, token=None):
    """GET 请求，返回 (status, headers, body_bytes). 忽略 4xx 错误（业务层处理）."""
    req = urllib.request.Request(url)
    req.add_header('User-Agent', USER_AGENT)
    req.add_header('Accept', 'application/vnd.github+json')
    if token:
        req.add_header('Authorization', 'Bearer ' + token)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.status, dict(resp.headers), resp.read()
    except urllib.error.HTTPError as e:
        return e.code, dict(e.headers), e.read()
    except Exception as e:
        return 0, {}, str(e).encode('utf-8')


def list_engine_releases(token=None, max_count=30):
    """拉取引擎 release 列表.

    返回 dict:
        {
          'ok': True,
          'releases': [
            {
              'tag': 'engine-v0.1.0.beta1',
              'version': '0.1.0.beta1',           # 去掉前缀
              'name': 'Loom 0.1.0.beta1',
              'published_at': '2026-10-19T...',
              'size_mb': 285.45,
              'download_url': 'https://github.com/.../Loom-0.1.0.beta1.zip',
              'asset_name': 'Loom-0.1.0.beta1.zip',
            }, ...
          ],
          'rate_limit': {'remaining': N, 'limit': 60},
        }
        {'ok': False, 'error': '...'}  # 网络/API 错误
    """
    url = '%s/repos/%s/%s/releases?per_page=%d' % (
        API_BASE, REPO_OWNER, REPO_NAME, max_count)
    status, headers, body = _request(url, token)

    rate = {
        'remaining': headers.get('X-RateLimit-Remaining', '?'),
        'limit': headers.get('X-RateLimit-Limit', '?'),
    }

    if status == 401:
        return {'ok': False, 'error': 'Token 无效 (401)', 'rate_limit': rate}
    if status == 403:
        return {'ok': False, 'error': '速率限制或权限不足 (403)', 'rate_limit': rate}
    if status == 404:
        return {'ok': False, 'error': '仓库不存在或无权限 (404): %s/%s'
                % (REPO_OWNER, REPO_NAME), 'rate_limit': rate}
    if status != 200:
        return {'ok': False, 'error': 'HTTP %d: %s'
                % (status, body[:200].decode('utf-8', 'ignore')), 'rate_limit': rate}

    try:
        releases_raw = json.loads(body.decode('utf-8'))
    except Exception as e:
        return {'ok': False, 'error': '解析 JSON 失败: %r' % e, 'rate_limit': rate}

    out = []
    for rel in releases_raw:
        tag = rel.get('tag_name') or ''
        if not tag.startswith(TAG_PREFIX):
            continue   # 不是引擎 release（可能是 hub-v*）
        version = tag[len(TAG_PREFIX):]
        # 找 asset：优先 .zip 且名字包含 'Loom'
        assets = rel.get('assets') or []
        zip_asset = None
        for a in assets:
            nm = a.get('name', '')
            if nm.lower().endswith('.zip') and 'loom' in nm.lower():
                zip_asset = a
                break
        if zip_asset is None:
            for a in assets:
                if a.get('name', '').lower().endswith('.zip'):
                    zip_asset = a
                    break
        if zip_asset is None:
            continue   # 该 release 没有 zip asset，跳过
        size_bytes = zip_asset.get('size', 0)
        out.append({
            'tag': tag,
            'version': version,
            'name': rel.get('name') or tag,
            'published_at': rel.get('published_at') or '',
            'size_mb': round(size_bytes / (1024.0 * 1024.0), 2),
            'download_url': zip_asset.get('browser_download_url') or '',
            'asset_name': zip_asset.get('name') or '',
        })
    return {'ok': True, 'releases': out, 'rate_limit': rate}


# ---------------- 下载 ----------------

class CancelToken:
    """下载取消标志（线程安全）."""
    def __init__(self):
        self._flag = threading.Event()

    def cancel(self):
        self._flag.set()

    def is_set(self):
        return self._flag.is_set()


class SlowSpeedError(Exception):
    """速度过低异常（触发切镜像）."""
    pass


def _download_one_url(url, tmp_path, progress_cb, cancel_token,
                      chunk_size, max_retries, per_url_timeout,
                      low_speed_bps, low_speed_secs):
    """单个 URL 的下载尝试（含断点续传 + 重试 + 速度监控）.

    返回 True=成功 / False=取消 / 抛异常=失败（外层会切下一个 URL）
    """
    last_err = None
    for attempt in range(1, max_retries + 1):
        if cancel_token is not None and cancel_token.is_set():
            return False
        resume_pos = (os.path.getsize(tmp_path)
                      if os.path.isfile(tmp_path) else 0)
        req = urllib.request.Request(url)
        req.add_header('User-Agent', USER_AGENT)
        if resume_pos > 0:
            req.add_header('Range', 'bytes=%d-' % resume_pos)
            print('[下载] 断点续传: %d 字节 (attempt %d/%d)'
                  % (resume_pos, attempt, max_retries))
        try:
            url_start = time.time()
            with urllib.request.urlopen(req, timeout=per_url_timeout) as resp:
                status = getattr(resp, 'status', 200)
                if status == 206:
                    content_range = resp.headers.get('Content-Range', '')
                    try:
                        total = int(content_range.split('/')[-1])
                    except Exception:
                        total = resume_pos + int(
                            resp.headers.get('Content-Length', 0) or 0)
                    mode = 'ab'
                    downloaded = resume_pos
                else:
                    total = int(resp.headers.get('Content-Length', 0) or 0)
                    mode = 'wb'
                    downloaded = 0
                    resume_pos = 0

                last_time = time.time()
                last_bytes = downloaded
                low_speed_start = None
                with open(tmp_path, mode) as f:
                    while True:
                        if (cancel_token is not None
                                and cancel_token.is_set()):
                            f.close()
                            try:
                                os.remove(tmp_path)
                            except OSError:
                                pass
                            return False
                        # 整体超时检查
                        if time.time() - url_start > per_url_timeout:
                            raise SlowSpeedError(
                                'URL 超时 (%d 秒)' % per_url_timeout)
                        chunk = resp.read(chunk_size)
                        if not chunk:
                            break
                        f.write(chunk)
                        downloaded += len(chunk)
                        now = time.time()
                        dt = now - last_time
                        if dt >= 0.2:
                            speed = (downloaded - last_bytes) / dt
                            if progress_cb is not None:
                                try:
                                    progress_cb(downloaded, total, speed)
                                except Exception:
                                    pass
                            # 速度监控：连续 low_speed_secs 秒速度 < 阈值则切镜像
                            if speed < low_speed_bps and total > 0:
                                if low_speed_start is None:
                                    low_speed_start = now
                                elif now - low_speed_start >= low_speed_secs:
                                    raise SlowSpeedError(
                                        '速度过低 (%.1f KB/s 持续 %d 秒)'
                                        % (speed / 1024.0, low_speed_secs))
                            else:
                                low_speed_start = None
                            last_time = now
                            last_bytes = downloaded
            if total > 0 and downloaded != total:
                raise IOError('下载不完整: %d / %d 字节'
                              % (downloaded, total))
            return True
        except SlowSpeedError:
            raise  # 不重试，直接切镜像
        except Exception as e:
            last_err = e
            print('[下载] 尝试 %d 失败: %r' % (attempt, e))
            if attempt < max_retries:
                time.sleep(2)
                continue
            raise
    if last_err:
        raise last_err
    return False


def download_asset(url, dest_path, progress_cb=None,
                   cancel_token=None, chunk_size=64 * 1024,
                   max_retries=3, use_mirrors=True,
                   per_url_timeout=180,
                   low_speed_kb=80, low_speed_secs=15):
    """流式下载文件到 dest_path（2026-10-19 强化 + 镜像加速）.

    能力：
      1) 断点续传（同 URL 内重试时）
      2) 完整性校验（字节数 == Content-Length）
      3) 自动重试（每 URL 内 3 次）
      4) 镜像加速：直连慢/失败时自动切到 MIRRORS 列表
      5) 速度监控：连续 low_speed_secs 秒 < low_speed_kb 则切镜像

    progress_cb(downloaded_bytes, total_bytes, speed_bps)
    cancel_token: CancelToken 实例
    返回 True=成功 / False=取消 / 抛异常=所有 URL 失败
    """
    urls = _mirror_urls(url) if use_mirrors else [url]
    tmp_path = dest_path + '.part'
    low_speed_bps = low_speed_kb * 1024.0
    last_err = None

    for idx, cur_url in enumerate(urls):
        if cancel_token is not None and cancel_token.is_set():
            return False
        # 换 URL 前删除 .part（避免镜像内容不一致）
        if idx > 0 and os.path.isfile(tmp_path):
            try:
                os.remove(tmp_path)
            except OSError:
                pass
        label = '直连' if idx == 0 else ('镜像%d' % idx)
        if idx > 0:
            print('[下载] 切到镜像 %s: %s' % (label, cur_url))
            # 通知 UI 已切镜像
            if progress_cb is not None:
                try:
                    progress_cb(0, 0, 0.0)
                except Exception:
                    pass
        try:
            ok = _download_one_url(
                cur_url, tmp_path, progress_cb, cancel_token,
                chunk_size, max_retries, per_url_timeout,
                low_speed_bps, low_speed_secs)
            if ok is False:
                return False   # 用户取消
            # 成功：原子重命名
            if os.path.isfile(dest_path):
                try:
                    os.remove(dest_path)
                except OSError:
                    pass
            os.rename(tmp_path, dest_path)
            if idx > 0:
                print('[下载] 镜像 %s 成功完成' % label)
            return True
        except Exception as e:
            last_err = e
            print('[下载] %s 失败: %r' % (label, e))
            continue

    raise last_err or IOError('所有 URL 均失败')
