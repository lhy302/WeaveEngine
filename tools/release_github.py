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

# 版本号只有一个真源（人类裁决 2026-11-08）：
#   引擎 = Loom/解释器.json      Hub = LoomHub/版本.json
# 这里不再保留任何字面版本值。以前 ENGINE/HUB 各写一份缺省字面值，实测能出现
# "LOOM_HUB_VERSION=9.9.9 时 release 用 9.9.9、package_hub 仍用 0.1.2" 的静默分叉。
_TOOLS_DIR = os.path.dirname(os.path.abspath(__file__))
if _TOOLS_DIR not in sys.path:
    sys.path.insert(0, _TOOLS_DIR)


def _load_true_source_version(what):
    """读版本真源（只读，无副作用）：engine -> Loom/解释器.json；hub -> LoomHub/版本.json。"""
    try:
        if what == 'hub':
            import package_hub as _ph
            return str(_ph.load_version())
        import package_engine as _pe
        return str(_pe.load_version())
    except SystemExit as e:
        print('[错误] 读取 %s 版本真源失败: %s' % (what, e))
        raise SystemExit(1)
    except Exception as e:                       # 真源不可读属硬错误，出声退出
        print('[错误] 读取 %s 版本真源失败: %r' % (what, e))
        raise SystemExit(1)


def resolve_version(env_name, source_value, what='engine'):
    """把"真源值 + 可选环境变量"收敛成一个版本号。

    环境变量只用于**确认同一个版本**（例如发布手册里 set LOOM_ENGINE_VERSION=...）；
    一旦与真源不一致就报错退出 —— 不允许两条链各说一个版本号。
    """
    override = (os.environ.get(env_name) or '').strip()
    if not override:
        return source_value
    if override != source_value:
        raise SystemExit(
            '[错误] 版本号分叉：环境变量 %s=%r 与真源值 %r 不一致（%s 侧）。\n'
            '  版本号只有一个真源：引擎 = Loom/解释器.json，'
            'LoomHub = LoomHub/版本.json。\n'
            '  处理: 改真源文件（推荐），或删掉该环境变量；'
            '环境变量只用于确认"仍是同一个版本"，不能单独指定另一个版本。'
            % (env_name, override, source_value, what))
    return override


ENGINE_VERSION = resolve_version('LOOM_ENGINE_VERSION',
                                 _load_true_source_version('engine'), 'engine')
HUB_VERSION = resolve_version('LOOM_HUB_VERSION',
                              _load_true_source_version('hub'), 'hub')


def engine_zip():
    return os.path.join(ROOT, 'tools', 'dist',
                        'Loom-%s.zip' % ENGINE_VERSION)


def hub_setup():
    return os.path.join(ROOT, 'tools', 'dist',
                        'LoomHub-%s-Setup.exe' % HUB_VERSION)


ENGINE_ZIP = engine_zip()
HUB_SETUP = hub_setup()


def check_version(version, what='engine'):
    """版本号白名单（与 LoomHub/package_engine 共用同一判据）。"""
    try:
        import package_engine as _pe
        return _pe.check_version(version)
    except SystemExit as e:
        # 用 SystemExit(1) 而不是 SystemExit(msg)：避免同一条错误被打印两次
        print('[错误] %s 版本号非法: %s' % (what, e))
        raise SystemExit(1)


def require_assets(pairs):
    """发布前置检查：资产缺失 -> 一个远端写操作都不做。"""
    missing = [(label, p) for label, p in pairs if not os.path.isfile(p)]
    if missing:
        print('[错误] 发布前置检查未通过，以下资产不存在（未做任何远端写操作）：')
        for label, p in missing:
            print('   - %-8s %s' % (label, p))
        print('   提示: 先跑 tools\\package_engine.py --version <版本> 产出 zip。')
        return False
    return True


def run_test_gate():
    """回归闸门: 先跑全套回归，非零即中止（此时零远端写操作）。默认开启（Q10=A）。"""
    runner = os.path.join(ROOT, 'Loom', 'tests', 'run_all.py')
    if not os.path.isfile(runner):
        print('[错误] 找不到回归入口: %s' % runner)
        return False
    print('[发布] --require-tests: 先跑全套回归（Loom/tests/run_all.py）...')
    r = subprocess.run([sys.executable, runner], cwd=os.path.join(ROOT, 'Loom'))
    if r.returncode != 0:
        print('[错误] 回归未通过 (rc=%d) —— 中止发布，未做任何远端写操作' % r.returncode)
        return False
    print('[发布] 回归通过')
    return True


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


def _req(url, token, method='GET', data=None, headers=None, timeout=120):
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
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, resp.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()
    except Exception as e:
        return 0, str(e).encode()


def _why(s, b):
    """把 _req 的 (status, body) 转成人能读的一句原因（status 0 = 网络/超时）。"""
    if s == 0:
        return '网络/超时，没有收到 HTTP 响应: %s' % b[:200].decode('utf-8', 'ignore')
    return 'HTTP %d: %s' % (s, b[:300].decode('utf-8', 'ignore'))


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


def find_release_by_tag(tag, token):
    """按 tag 取既有 release（无则 None）。GET 不算远端写操作。"""
    s, b = _req('%s/repos/%s/%s/releases/tags/%s'
                % (API_BASE, REPO_OWNER, REPO_NAME, urllib.parse.quote(tag)),
                token)
    if s != 200:
        return None
    try:
        return json.loads(b.decode())
    except Exception:
        return None


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
    if s in (200, 201):
        rel = json.loads(b.decode())
        print('[发布] release 已创建: %s' % rel.get('html_url'))
        return rel
    if s == 422:
        # beta4 / P-05-08: 上传失败后重跑不该死在"tag 已存在"上。
        # 复用远端既有 release，让 upload_asset 的"删同名 asset 再传"真正可达。
        rel = find_release_by_tag(tag, token)
        if rel is not None:
            print('[发布] release 已存在，复用: %s（assets=%d）'
                  % (rel.get('html_url'), len(rel.get('assets') or [])))
            return rel
        print('[错误] 创建 release 失败 (HTTP 422 already_exists)，且按 tag 取不回: %s' % tag)
        print(b[:500].decode('utf-8', 'ignore'))
        raise SystemExit(1)
    print('[错误] 创建 release 失败: %s' % _why(s, b))
    raise SystemExit(1)


def upload_asset(release, file_path, token):
    if not os.path.isfile(file_path):
        # beta4 / P-05-07: 以前这里只打一条警告就 return，于是"release 建了、
        # tag 推了、资产没有"，退出码还是 0。现在前置检查 + 这里都硬失败。
        print('[错误] 资产不存在（不应发生，前置检查应已拦截）: %s' % file_path)
        raise SystemExit(1)
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
                headers={'Content-Type': 'application/zip'},
                timeout=7200)          # 大包(数百 MB)按慢速网络留足时间
    if s not in (200, 201):
        if s == 0:
            # _req 把"没有 HTTP 响应"(超时/DNS/TLS/连接重置)折成 status 0，
            # 与真正的 HTTP 错误分开报，避免出现"上传失败 (HTTP 0)"这种无信息日志。
            print('[错误] 上传未完成：网络/超时（%.0f 秒超时）' % 7200)
            print(b[:500].decode('utf-8', 'ignore'))
            print('[提示] 可重跑同一条命令恢复：同名 release 会被复用、'
                  '同名 asset 会先删再传（幂等）。')
        else:
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


ENGINE_BODY = """## Loom 引擎 {version}

> 内测版本序列：beta1 → beta2 → **{version}**（共 3 个内测版本）。含嵌入式 Python 3.12 运行时，开箱即用，无需安装 Python。

### 本版要点

- **预编译玩家运行时随包分发**（约 97 MB）：游戏开发机**无需 Python / 无需 C 编译器**，打包游戏约 2 秒（对齐 Unity 预置 UnityPlayer 的做法）
- **渲染后端可切换**：`游戏设置.json` 的 `render_api`（`vulkan` / `opengl` / `auto`）；Vulkan 不兼容时自动崩一次并把配置回退为 OpenGL
- **正交投影**（2D 游戏）+ 播放时强制套用场景相机（位置/朝向/距离/正交/FOV）
- **鼠标锁定配置化**：`mouse_lock_allowed` / `mouse_locked`，并保留强制解锁键（可改键）
- **键位可配置**：`key_bindings`（解锁键不再固定 Tab）；键位表 30 → **76 键**（F1–F12 / Esc / Enter / 字母数字 / 标点）
- **修复**：Vulkan 看门狗 60 秒必杀（"玩一半闪退"）、VK 打包版所有 UI 按钮点击无效、播放器退出残留鼠标捕获
- **崩溃日志落盘**：打包游戏目录生成 `日志.txt`（含完整 traceback 与 faulthandler 硬崩栈）

### 安装方式

**方式 1：LoomHub 在线安装**
LoomHub -> 解释器面板 -> 「从 GitHub 安装」-> 选 {version} -> 下载并安装

**方式 2：LoomHub 离线安装**
下载下方 Loom-{version}.zip -> LoomHub -> 「安装 .zip」-> 选 zip

**方式 3：手动解压**
下载 zip -> 解压到任意目录 -> 双击 `Loom.bat` 启动
或 LoomHub -> 「导入目录」-> 选解压后的 Loom 子目录

### 系统要求
Windows 10 64-bit 或更高（Python 已内置）
"""

HUB_BODY = """## LoomHub 项目管理器 {version}

Loom 引擎的官方项目管理器。

### 功能

- 多版本引擎管理：同时安装多个 Loom 引擎版本，一键切换默认版本
- 项目列表：创建 / 导入 / 打开 / 移除项目，与 Unity Hub 对齐的体验
- 在线安装：从 GitHub 直接下载并安装 Loom 引擎（需联网）
- 离线安装：支持 zip 安装包（选择文件 -> 预览 -> 自定义位置 -> 安装）
- 目录导入：已手动解压的引擎可直接导入
- 三模式移除：仅从列表移除 / 彻底删除磁盘文件 / 取消
- 单实例保护：连点不会开多个窗口
- **打开项目自动启用 Agent 通道**（`--agent`）：外部 Agent / MCP 可直接连上编辑器

### 安装
下载下方 LoomHub-{version}-Setup.exe，双击安装。桌面会创建快捷方式，控制面板可卸载。

### 系统要求
Windows 10 64-bit 或更高
"""


def publish_engine(token):
    print()
    print('=' * 60)
    print('发布引擎 %s' % ENGINE_VERSION)
    print('=' * 60)
    tag = 'engine-v%s' % ENGINE_VERSION
    title = 'Loom 引擎 %s' % ENGINE_VERSION
    body = ENGINE_BODY.format(version=ENGINE_VERSION)
    create_local_tag(tag, title)
    rel = create_release(tag, title, body, token, prerelease=True)
    upload_asset(rel, ENGINE_ZIP, token)
    push_tag(tag)


def publish_hub(token):
    print()
    print('=' * 60)
    print('发布 LoomHub %s' % HUB_VERSION)
    print('=' * 60)
    tag = 'hub-v%s' % HUB_VERSION
    title = 'LoomHub 项目管理器 %s' % HUB_VERSION
    body = HUB_BODY.format(version=HUB_VERSION)
    create_local_tag(tag, title)
    rel = create_release(tag, title, body, token, prerelease=False)
    upload_asset(rel, HUB_SETUP, token)
    push_tag(tag)


def want_test_gate(argv):
    """发布回归闸门（2026-11-08 人类裁决 Q10=A：**默认开启**）。

    为什么默认开：审计发现 beta3 发版时全量回归是红的（5 个文件）却无人看见，
    因为验收口径只有"MCP 40/40 + 定向探针"，与被改模块没有交集。
    现在推送任何 release 前先跑 Loom/tests/run_all.py，非零即中止且零远端写操作。
    逃生口：显式传 --no-require-tests（仅限确认过"红与本版无关"的紧急情形）。
    """
    return '--no-require-tests' not in argv


def main():
    argv = sys.argv[1:]
    require_tests = want_test_gate(argv)
    rest = [a for a in argv if a not in ('--require-tests', '--no-require-tests')]
    target = rest[0] if rest else 'all'
    if target not in ('engine', 'hub', 'all'):
        print('用法: release_github.py [engine|hub|all] [--no-require-tests]')
        sys.exit(1)

    # 1) 版本号白名单（与打包/LoomHub 共用同一判据）
    if target in ('engine', 'all'):
        check_version(ENGINE_VERSION, 'engine')
    if target in ('hub', 'all'):
        check_version(HUB_VERSION, 'hub')

    # 2) 资产前置检查：缺任何一个就退出，且**零远端写操作**（不建 release/不推 tag）
    wanted = []
    if target in ('engine', 'all'):
        wanted.append(('engine', ENGINE_ZIP))
    if target in ('hub', 'all'):
        wanted.append(('hub', HUB_SETUP))
    if not require_assets(wanted):
        sys.exit(1)

    # 3) 回归闸门（Q10=A：默认开启；--no-require-tests 才跳过）
    if require_tests and not run_test_gate():
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
