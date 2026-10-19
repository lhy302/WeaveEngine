# -*- coding: utf-8 -*-
"""release_github.py — 自动化发布 Loom 引擎 + LoomHub 到 GitHub Release（2026-10-19）"""
import json
import os
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPO_OWNER = 'lhy302'
REPO_NAME = 'WeaveEngine'
API_BASE = 'https://api.github.com'
USER_AGENT = 'LoomHub-Release/0.1.0'

ENGINE_ZIP = os.path.join(ROOT, 'tools', 'dist', 'Loom-0.1.0.beta1.zip')
HUB_SETUP = os.path.join(ROOT, 'tools', 'dist', 'LoomHub-0.1.0-Setup.exe')


def get_token():
    t = os.environ.get('GITHUB_TOKEN')
    if t:
        return t
    try:
        env = dict(os.environ)
        env['GIT_TERMINAL_PROMPT'] = '0'
        r = subprocess.run(
            ['git', 'credential', 'fill'],
            input='protocol=https\nhost=github.com\n\n',
            capture_output=True, text=True, timeout=10, env=env)
        for line in r.stdout.splitlines():
            if line.startswith('password='):
                return line[len('password='):].strip()
    except Exception:
        pass
    return ''


def _req(url, token, method='GET', data=None, headers=None):
    req = urllib.request.Request(url, method=method)
    req.add_header('User-Agent', USER_AGENT)
    req.add_header('Accept', 'application/vnd.github+json')
    if token:
        req.add_header('Authorization', 'Bearer ' + token)
    if headers:
        for k, v in headers.items():
            req.add_header(k, v)
    if data is not None:
        req.data = data
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            return resp.status, resp.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()
    except Exception as e:
        return 0, str(e).encode()


def check_token(token):
    print('[发布] 验证 token...')
    s, b = _req('%s/user' % API_BASE, token)
    if s != 200:
        print('[错误] token 无效 (HTTP %d)' % s)
        print(b[:300].decode('utf-8', 'ignore'))
        return False
    user = json.loads(b.decode())
    print('[发布] 用户: %s' % user.get('login'))
    s, b = _req('%s/repos/%s/%s' % (API_BASE, REPO_OWNER, REPO_NAME), token)
    if s != 200:
        print('[错误] 仓库访问失败 (HTTP %d)' % s)
        return False
    repo = json.loads(b.decode())
    perms = repo.get('permissions', {})
    print('[发布] 仓库权限: push=%s admin=%s'
          % (perms.get('push'), perms.get('admin')))
    if not perms.get('push'):
        print('[错误] 无 push 权限，无法发布')
        return False
    return True


def tag_exists_locally(tag):
    r = subprocess.run(['git', 'rev-parse', '--verify', '--quiet',
                        'refs/tags/' + tag],
                       cwd=ROOT, capture_output=True)
    return r.returncode == 0


def create_local_tag(tag, msg):
    if tag_exists_locally(tag):
        print('[发布] tag 已存在: %s' % tag)
        return
    r = subprocess.run(['git', 'tag', '-a', tag, '-m', msg],
                       cwd=ROOT, capture_output=True, text=True)
    if r.returncode != 0:
        print('[错误] 打 tag 失败: %s' % r.stderr)
        raise SystemExit(1)
    print('[发布] 已打 tag: %s' % tag)


def create_release(tag, name, body, token, prerelease=False):
    print('[发布] 创建 GitHub Release: %s' % tag)
    payload = json.dumps({
        'tag_name': tag,
        'name': name,
        'body': body,
        'draft': False,
        'prerelease': prerelease,
    }).encode('utf-8')
    s, b = _req('%s/repos/%s/%s/releases' % (API_BASE, REPO_OWNER, REPO_NAME),
                token, method='POST', data=payload,
                headers={'Content-Type': 'application/json'})
    if s not in (200, 201):
        print('[错误] 创建 release 失败 (HTTP %d)' % s)
        print(b[:500].decode('utf-8', 'ignore'))
        raise SystemExit(1)
    rel = json.loads(b.decode())
    print('[发布] release 已创建: %s' % rel.get('html_url'))
    return rel


def upload_asset(release, file_path, token):
    if not os.path.isfile(file_path):
        print('[警告] 文件不存在，跳过: %s' % file_path)
        return
    size = os.path.getsize(file_path)
    name = os.path.basename(file_path)
    print('[发布] 上传 asset: %s (%.2f MB)'
          % (name, size / (1024.0 * 1024.0)))
    for a in release.get('assets', []):
        if a['name'] == name:
            print('[发布] 删除已存在 asset: %s' % name)
            _req('%s/repos/%s/%s/releases/assets/%d'
                 % (API_BASE, REPO_OWNER, REPO_NAME, a['id']),
                 token, method='DELETE')
    upload_url = release['upload_url'].replace(
        '{?name,label}', '?name=' + urllib.parse.quote(name))
    with open(file_path, 'rb') as f:
        data = f.read()
    s, b = _req(upload_url, token, method='POST', data=data,
                headers={'Content-Type': 'application/zip'})
    if s not in (200, 201):
        print('[错误] 上传失败 (HTTP %d)' % s)
        print(b[:500].decode('utf-8', 'ignore'))
        raise SystemExit(1)
    result = json.loads(b.decode())
    print('[发布] asset 已上传: %s (%.2f MB)'
          % (result.get('name'),
             result.get('size', 0) / (1024.0 * 1024.0)))


def push_tag(tag):
    print('[发布] 推送 tag 到远端...')
    r = subprocess.run(['git', 'push', 'origin', tag],
                       cwd=ROOT, capture_output=True, text=True)
    if r.returncode != 0:
        print('[警告] 推送 tag 失败: %s' % r.stderr)
    else:
        print('[发布] tag 已推送')


ENGINE_BODY = """## Loom 引擎 0.1.0.beta1

首个内测版本。含嵌入式 Python 3.12 运行时（开箱即用，无需安装 Python）。

### 安装方式

**方式 1：LoomHub 在线安装**
LoomHub -> 解释器面板 -> 「从 GitHub 安装」-> 选 0.1.0.beta1 -> 下载并安装

**方式 2：LoomHub 离线安装**
下载下方 Loom-0.1.0.beta1.zip -> LoomHub -> 「安装 .zip」-> 选 zip

**方式 3：手动解压**
下载 zip -> 解压到任意目录 -> 双击 Loom.bat 启动
或 LoomHub -> 「导入目录」-> 选解压后的 Loom 子目录

### 系统要求
Windows 10 64-bit 或更高（Python 已内置）
"""

HUB_BODY = """## LoomHub 项目管理器 0.1.0

Loom 引擎的官方项目管理器。

### 功能

- 多版本引擎管理：同时安装多个 Loom 引擎版本，一键切换默认版本
- 项目列表：创建 / 导入 / 打开 / 移除项目，与 Unity Hub 对齐的体验
- 在线安装：从 GitHub 直接下载并安装 Loom 引擎（需联网）
- 离线安装：支持 zip 安装包（选择文件 -> 预览 -> 自定义位置 -> 安装）
- 目录导入：已手动解压的引擎可直接导入
- 三模式移除：仅从列表移除 / 彻底删除磁盘文件 / 取消
- 单实例保护：连点不会开多个窗口

### 安装
下载下方 LoomHub-0.1.0-Setup.exe，双击安装。桌面会创建快捷方式，控制面板可卸载。

### 系统要求
Windows 10 64-bit 或更高
"""


def publish_engine(token):
    print()
    print('=' * 60)
    print('发布引擎 0.1.0.beta1')
    print('=' * 60)
    tag = 'engine-v0.1.0.beta1'
    create_local_tag(tag, 'Loom 引擎 0.1.0.beta1')
    rel = create_release(tag, 'Loom 引擎 0.1.0.beta1',
                         ENGINE_BODY, token, prerelease=True)
    upload_asset(rel, ENGINE_ZIP, token)
    push_tag(tag)


def publish_hub(token):
    print()
    print('=' * 60)
    print('发布 LoomHub 0.1.0')
    print('=' * 60)
    tag = 'hub-v0.1.0'
    create_local_tag(tag, 'LoomHub 项目管理器 0.1.0')
    rel = create_release(tag, 'LoomHub 项目管理器 0.1.0',
                         HUB_BODY, token, prerelease=False)
    upload_asset(rel, HUB_SETUP, token)
    push_tag(tag)


def main():
    target = sys.argv[1] if len(sys.argv) > 1 else 'all'
    if target not in ('engine', 'hub', 'all'):
        print('用法: release_github.py [engine|hub|all]')
        sys.exit(1)
    token = get_token()
    if not token:
        print('[错误] 找不到 GitHub Token。请设置环境变量 GITHUB_TOKEN '
              '或确保 git 凭据管理器已登录。')
        sys.exit(1)
    if not check_token(token):
        sys.exit(1)
    if target in ('engine', 'all'):
        publish_engine(token)
    if target in ('hub', 'all'):
        publish_hub(token)
    print()
    print('=' * 60)
    print('发布完成！')
    print('=' * 60)
    print('查看: https://github.com/%s/%s/releases'
          % (REPO_OWNER, REPO_NAME))


if __name__ == '__main__':
    main()
