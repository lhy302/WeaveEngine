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
    """引擎发布资产: 优先编译包（主发布物），其次源码包，最后兼容历史命名。

    2026-11-10 Q-PKG-4: 两种包改成 Loom-<ver>-compiled.zip / Loom-<ver>-source.zip，
    不再互相覆盖；发布按这个顺序找，找不到再回退旧名（旧包仍可发）。
    """
    dist = os.path.join(ROOT, 'tools', 'dist')
    for kind in ('compiled', 'source'):
        p = os.path.join(dist, 'Loom-%s-%s.zip' % (ENGINE_VERSION, kind))
        if os.path.isfile(p):
            return p
    return os.path.join(dist, 'Loom-%s.zip' % ENGINE_VERSION)


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

> {runtime_line}

### 本版要点

{highlights}

### 安装方式

**方式 1：LoomHub 在线安装**
LoomHub -> 解释器面板 -> 「从 GitHub 安装」-> 选 {version} -> 下载并安装

**方式 2：LoomHub 离线安装**
下载下方 {artifact} -> LoomHub -> 「安装 .zip」-> 选 zip

**方式 3：手动解压**
下载 zip -> 解压到任意目录 -> 双击 `Loom.bat` 启动
或 LoomHub -> 「导入目录」-> 选解压后的 Loom 子目录

### 系统要求
Windows 10 64-bit 或更高（{python_note}）
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

### 本版要点

{highlights}

### 安装
下载下方 LoomHub-{version}-Setup.exe，双击安装。桌面会创建快捷方式，控制面板可卸载；卸载时会询问是否同时删除用户配置（默认保留）。

### 系统要求
Windows 10 64-bit 或更高
"""


_RUNTIME_LINE_COMPILED = (
    '**编译版引擎**：引擎本体为 Nuitka 编译产物 `Loom.exe`（**无需安装 Python**），'
    '游戏打包器 = 同目录 `build_game.exe`；包内**不含** .py 源码与嵌入式 Python。')
_RUNTIME_LINE_SOURCE = '含嵌入式 Python {pyver} 运行时，开箱即用，无需安装 Python。'
_PYTHON_NOTE_COMPILED = '引擎与打包器均为编译产物，不依赖系统 Python'
_PYTHON_NOTE_SOURCE = 'Python 已内置'


def engine_artifact_facts(zip_path):
    """从引擎 zip 的 Loom/解释器.json 读事实（build_mode / main_exe / python_version）。

    2026-11-08: 发布说明不再手写「含嵌入式 Python」这类会随打包形态变化的话 ——
    模板必须由**实际产物**决定，否则会出现「编译版包 + 源码版说明」的自相矛盾（本轮回溯取证）。
    """
    facts = {'build_mode': 'source', 'main_exe': '', 'python_version': ''}
    try:
        import zipfile
        with zipfile.ZipFile(zip_path) as zf:
            meta = json.loads(zf.read('Loom/解释器.json').decode('utf-8'))
        facts['build_mode'] = str(meta.get('build_mode') or 'source')
        facts['main_exe'] = str(meta.get('main_exe') or '')
        facts['python_version'] = str(meta.get('python_version') or '')
    except (OSError, KeyError, ValueError) as e:
        print('[警告] 读不到包内 解释器.json，按源码版写发布说明: %r' % (e,))
    return facts


DEFAULT_HIGHLIGHTS = (
    '- **预编译玩家运行时随包分发**（约 97 MB）：游戏开发机**无需 Python / 无需 C 编译器**，打包游戏约数秒'
    '（对齐 Unity 预置 UnityPlayer 的做法）\n'
    '- **每游戏配置**：`游戏设置.json`（开发者只读默认）+ 用户层 `%LOCALAPPDATA%/Loom/games/<id>/`（只存改动）；'
    '装到只读目录也能保存\n'
    '- **渲染后端可切换**：`render_api`（vulkan / opengl / auto）；Vulkan 初始化失败时写回配置并给出明确指引（不再静默中断）\n'
    '- **鼠标锁定默认关闭**：`mouse_lock_allowed` / `mouse_locked`；解锁键归引擎独占且可改键，'
    '脚本用 `set_ui_capture_mouse()` 显式决定何时给光标\n'
    '- **键位可配置**：`key_bindings`，76 键表；与脚本 `keys_used` 冲突时拒绝保存\n'
    '- **崩溃日志落盘**：`%LOCALAPPDATA%/Loom/logs/`（含 traceback 与 faulthandler 硬崩栈）')


# ---------------- 发布说明体检（2026-11-13 事故后新增）----------------
# 事故：两个 Release 的正文都还是「内测 · 草稿」口径，还写着过期的
# 「默认 C:\Program Files\Loom」，而这一版已经把默认安装根改成跟随 LoomHub 位置。
# 资产哈希是对的，但**正文是错的** —— 发布前只核了资产没核正文。
# 现在把它变成硬门：正文里出现过期词 / 没有本资产的 sha256 或字节数 → 中止
# （此时还没创建 release、没上传资产，零远端写操作）。
NOTES_BANNED = (
    "草稿",            # 发布说明不是草稿
    "未执行",          # 已经发布了就别写「发布命令未执行」
    "待人类裁决",      # 已裁决的结论才能进正文
    "TBD", "TODO", "待定",
)
STALE_CLAIMS = (
    "默认 `C:\\Program Files\\Loom`",   # 0.1.4 起改为跟随 Hub 位置推荐
)


def _sha256(path):
    import hashlib
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def notes_lint(text, artifact, label=""):
    """发布说明体检：返回问题列表（空=通过）。

    判据只检「能机器判的」部分，语义仍需人读一遍（见 docs/design/开发流程_发布检查单.md）：
      1. 不得含过期/未定稿词（NOTES_BANNED）；
      2. 不得保留已作废的说法（STALE_CLAIMS）；
      3. 必须写出**本资产的真实 sha256 与字节数**（防止骨架里写的是上一个包的数字）。
    """
    problems = []
    body = text or ""
    for w in NOTES_BANNED:
        if w in body:
            problems.append("含过期/未定稿词「%s」" % w)
    for w in STALE_CLAIMS:
        if w in body:
            problems.append("含已作废的说法「%s」" % w)
    if artifact and os.path.isfile(artifact):
        sha = _sha256(artifact)
        if sha not in body.lower():
            problems.append("说明里没有本资产 sha256 %s..." % sha[:12])
        size = os.path.getsize(artifact)
        cands = (str(size), "%-12d".strip() % size,
                 ("{:,}".format(size)).replace(",", " "),
                 "{:,}".format(size))
        if not any(c in body for c in cands):
            problems.append("说明里没有本资产字节数 %d" % size)
    return problems


def _notes_gate(body, artifact, label):
    probs = notes_lint(body, artifact, label)
    if probs:
        print("[错误] 发布说明体检不通过（%s）—— 未做任何远端写操作：" % label)
        for p in probs:
            print("  · " + p)
        print("  说明文件：tools/release_notes/%s" % label)
        raise SystemExit(1)
    print("[发布] 说明体检通过: %s（sha256/字节数/无过期词）" % label)


def load_highlights(kind, version):
    """读 tools/release_notes/engine-<version>.md；缺失则用通用条目。

    为什么拆文件：发布说明里的「本版要点」天生是**版本相关**的，混在模板里必然过期
    （本轮回溯：beta4 的说明还写着 beta3 的功能清单与「含嵌入式 Python」）。
    """
    p = os.path.join(ROOT, 'tools', 'release_notes', '%s-%s.md' % (kind, version))
    try:
        with open(p, 'r', encoding='utf-8') as fh:
            txt = fh.read().strip()
        if txt:
            print('[发布] 版本要点: %s' % os.path.relpath(p, ROOT))
            return txt
    except OSError:
        pass
    print('[发布] 未找到版本要点文件，使用通用条目: %s' % os.path.relpath(p, ROOT))
    return DEFAULT_HIGHLIGHTS


def update_notes(token):
    """只更新已有 Release 的正文（不重传资产）。用于发布说明写错/需补充时。

    2026-11-08 新增：本轮回溯发现「编译版包 + 源码版说明」矛盾，而资产本身没问题 ——
    没有这个入口就只能删了重发（会丢下载计数与讨论链接）。
    """
    ok = True
    for kind, tag, version in (('engine', 'engine-v%s' % ENGINE_VERSION, ENGINE_VERSION),
                               ('hub', 'hub-v%s' % HUB_VERSION, HUB_VERSION)):
        s, b = _req('%s/repos/%s/%s/releases/tags/%s' % (API_BASE, REPO_OWNER, REPO_NAME, tag), token)
        if s != 200:
            print('[警告] %s 取不到 release: %s' % (tag, _why(s, b)))
            ok = False
            continue
        rel = json.loads(b.decode())
        if kind == 'engine':
            _facts = engine_artifact_facts(ENGINE_ZIP)
            _compiled = _facts['build_mode'] == 'compiled'
            body = ENGINE_BODY.format(
                version=version,
                artifact=os.path.basename(ENGINE_ZIP),
                runtime_line=(_RUNTIME_LINE_COMPILED if _compiled
                              else _RUNTIME_LINE_SOURCE.format(pyver=_facts['python_version'] or '3.13')),
                python_note=(_PYTHON_NOTE_COMPILED if _compiled else _PYTHON_NOTE_SOURCE),
                highlights=load_highlights('engine', version))
        else:
            body = HUB_BODY.format(version=version, highlights=load_highlights('hub', version))
        payload = json.dumps({'body': body}).encode('utf-8')
        s, b = _req('%s/repos/%s/%s/releases/%d' % (API_BASE, REPO_OWNER, REPO_NAME, rel['id']),
                    token, method='PATCH', data=payload,
                    headers={'Content-Type': 'application/json'})
        if s == 200:
            print('[发布] 已更新说明: %s' % tag)
        else:
            print('[错误] 更新 %s 失败: %s' % (tag, _why(s, b)))
            ok = False
    return ok


def publish_engine(token):
    print()
    print('=' * 60)
    print('发布引擎 %s' % ENGINE_VERSION)
    print('=' * 60)
    tag = 'engine-v%s' % ENGINE_VERSION
    title = 'Loom 引擎 %s' % ENGINE_VERSION
    _facts = engine_artifact_facts(ENGINE_ZIP)
    _compiled = _facts['build_mode'] == 'compiled'
    body = ENGINE_BODY.format(
        version=ENGINE_VERSION,
        artifact=os.path.basename(ENGINE_ZIP),
        runtime_line=(_RUNTIME_LINE_COMPILED if _compiled
                      else _RUNTIME_LINE_SOURCE.format(pyver=_facts['python_version'] or '3.13')),
        python_note=(_PYTHON_NOTE_COMPILED if _compiled else _PYTHON_NOTE_SOURCE),
        highlights=load_highlights('engine', ENGINE_VERSION))
    _notes_gate(body, ENGINE_ZIP, 'engine-%s.md' % ENGINE_VERSION)
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
    body = HUB_BODY.format(version=HUB_VERSION,
                           highlights=load_highlights('hub', HUB_VERSION))
    _notes_gate(body, HUB_SETUP, 'hub-%s.md' % HUB_VERSION)
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
    if '--update-notes' in argv:          # 只改发布说明，不重传资产
        tok = get_token()
        if not tok or not check_token(tok):
            sys.exit(1)
        sys.exit(0 if update_notes(tok) else 1)
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
