# -*- coding: utf-8 -*-
r"""package_engine.py — Loom 引擎发布包打包器（2026-10-19）

产物：tools/dist/Loom-<version>.zip
内容：Loom/ 运行时文件 + 嵌入式 Python 3.13.15 + 解释器.json
用法：py -3.13 tools/package_engine.py [--version X.Y.Z] [--allow-missing-runtime]

2026-11-09/10 打包链修复（人类裁决 Q1=A / Q3=A / Q4=B）:
  · 内嵌 Python 跟随 解释器.json 的 python_version（默认 3.13.15），不再硬编码 3.12；
    找不到 embeddable 时自动从 python.org 下载到 C:\loom_build\python-embed\<ver>\。
  · 嵌入版本 ≠ 解释器.json 版本 → 拒绝出包（发布硬门）。
  · Loom.bat 双形态: 编译包走 Loom\Loom.exe，源码包才回退 pythonw + Loom.py。
"""
import argparse
import json
import os
import shutil
import subprocess
import sys
import time
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ENGINE_DIR = os.path.join(ROOT, 'Loom')
DIST_DIR = os.path.join(ROOT, 'tools', 'dist')
META_PATH = os.path.join(ENGINE_DIR, '解释器.json')

# player_runtime 由 make_zip 显式预置 (只拷 game_player.dist, 排除 .build 中间产物)
EXCLUDE_DIRS = {'tests', '保存', 'Projects', '__pycache__', '.pytest_cache',
                'assets', 'Assets', 'player_runtime', '发布'}
EXCLUDE_EXTS = {'.pyc', '.pyo', '.log', '.tmp'}
EXCLUDE_FILES = {'解释器.json.bak'}


def load_version(override=None):
    if override:
        return override
    with open(META_PATH, 'r', encoding='utf-8') as f:
        return json.load(f)['version']


def _hub_config():
    """借用 LoomHub 的元数据判据（契约: 发版自检与导入侧共用同一判据）。

    beta4 / P-05-06: 以前 producer 侧完全没有校验，--version 的非法值会被原样
    写进包内 解释器.json，产出一个 LoomHub 直接拒装的 zip。这里强制走同一份
    hub_config.validate_meta，找不到就直接失败（本脚本是仓库内发版工具）。
    """
    hub_dir = os.path.join(ROOT, 'LoomHub')
    if hub_dir not in sys.path:
        sys.path.insert(0, hub_dir)
    try:
        import hub_config
        return hub_config
    except Exception as e:
        raise SystemExit(
            '[错误] 找不到 LoomHub/hub_config.py（%r）：发版自检必须与 LoomHub 导入侧'
            '共用同一判据，请在仓库根目录运行本脚本。' % (e,))


def check_version(version):
    """版本号白名单（x.y.z 或 x.y.z.betaN）。非法则立即失败，不产出任何包。"""
    hc = _hub_config()
    reason = hc.validate_meta({'version': version, 'main': 'Loom.py'}, version)
    if reason is not None:
        raise SystemExit('[错误] --version 非法: %r（%s）' % (version, reason))
    return version


def _runtime_dist(dir_path):
    """从一个候选目录里找"可用运行时 dist"（含 MyGame.exe）。

    beta4 / P-05-10/11: 默认入口与 --runtime 入口共用本函数，避免"同一份磁盘
    布局，默认分支平铺、--runtime 分支多套一层"的语义分裂。
    """
    if not dir_path or not os.path.isdir(dir_path):
        return None
    if os.path.isfile(os.path.join(dir_path, 'MyGame.exe')):
        return dir_path                      # 老布局: 直接在 player_runtime 下
    sub = os.path.join(dir_path, 'game_player.dist')
    if os.path.isfile(os.path.join(sub, 'MyGame.exe')):
        return sub                           # 新布局: 下钻一层
    return None


# ---- 构建产物形状断言 (2026-11-09 工具链升级 Nuitka 4.x) ----
# 背景: 4.x 把 pygame 依赖 DLL 放进 dist 的 pygame/ 子目录（2.7 平铺在根），
# 且编辑器若漏 --enable-plugin=pyside6 就缺 Qt 平台插件——体积反而更小，
# 体积检查会误判成"变好"。所以这里用"路径存在/DLL 数量"作硬判据。
QT_REQUIRED_PATHS = (
    'PySide6',
    os.path.join('PySide6', 'qt-plugins'),
    os.path.join('PySide6', 'qt-plugins', 'platforms', 'qwindows.dll'),
    os.path.join('ckernels', 'loom_kernels.dll'),
    'core_components',
)
PYGAME_MIN_DLLS = 15


def editor_dist_problems(dist):
    """编辑器 Nuitka dist 必须带 PySide6 + Qt 平台插件，返回缺失路径列表。"""
    return [rel for rel in QT_REQUIRED_PATHS
            if not os.path.exists(os.path.join(dist, rel))]


def editor_dist_bloat(dist):
    """编辑器 dist 里不该出现的可选重包（2026-11-09: 3.13 环境装了 cupy-cuda12x，
    不排除会带进 thrust.pyd/cub.pyd/openblas，dist 从 141MB 涨到 265MB）。"""
    return [name for name in ('cupy', 'cupy_backends', 'cupyx')
            if os.path.isdir(os.path.join(dist, name))]


def meta_version_problems(directory, version):
    """产物目录里的 解释器.json 必须存在且 version == 发布版本。

    2026-11-10: sceneio.ENGINE_VERSION 的单一事实源就是这个文件；Nuitka dist
    缺它 -> 引擎自报版本走常量兜底（漏改 = 误拒新场景），所以打包前硬校验。
    """
    path = os.path.join(directory, '解释器.json')
    if not os.path.isfile(path):
        return ['缺 解释器.json（会静默走 sceneio 常量兜底）: %s' % path]
    try:
        with open(path, 'r', encoding='utf-8') as f:
            got = (json.load(f).get('version') or '').strip()
    except Exception as e:
        return ['解释器.json 读取失败: %r' % (e,)]
    if got != version:
        return ['解释器.json version=%r != 发布版本 %r' % (got, version)]
    return []


def build_info_problems(directory, require_mode='release'):
    """产物档位校验：dev 产物（带控制台）不允许进发布包。

    2026-11-09 两档构建: tools/build_engine.py 会在产物目录写 build_info.json，
    打包器只接受 mode=release 的产物；缺失同样拒绝（防止手工编的 dev 版混入）。
    """
    path = os.path.join(directory, 'build_info.json')
    if not os.path.isfile(path):
        return ['缺 build_info.json（请用 tools/build_engine.py --mode release 构建）']
    try:
        with open(path, 'r', encoding='utf-8') as f:
            info = json.load(f)
    except Exception as e:
        return ['build_info.json 读取失败: %r' % (e,)]
    mode = info.get('mode')
    if mode != require_mode:
        return ['产物档位是 %r（要求 %r；dev 带控制台，不可发布）'
                % (mode, require_mode)]
    # R6-03 (2026-11-10): 字段合理性 —— 防"改 meta + --version"把旧产物重贴成新版本
    problems = []
    pyv = str(info.get('python') or '')
    parts = pyv.split('.')
    if len(parts) != 3 or not all(x.isdigit() for x in parts):
        problems.append('build_info.python 非法: %r（应为 x.y.z）' % (pyv,))
    nk = str(info.get('nuitka') or '').strip()
    if not nk or not nk[0].isdigit():
        problems.append('build_info.nuitka 非法: %r' % (nk,))
    ba = str(info.get('built_at') or '')
    try:
        time.strptime(ba, '%Y-%m-%d %H:%M:%S')
    except Exception:
        problems.append('build_info.built_at 非法: %r' % (ba,))
    return problems


def runtime_layout_problems(dist):
    """播放器运行时 dist 的 pygame 依赖布局，返回问题列表（空=通过）。"""
    problems = []
    pygame_dir = os.path.join(dist, 'pygame')
    if not os.path.isdir(pygame_dir):
        problems.append('缺 pygame/ 子目录 (Nuitka>=4 的 DLL 布局)')
    else:
        dlls = [f for f in os.listdir(pygame_dir) if f.lower().endswith('.dll')]
        if len(dlls) < PYGAME_MIN_DLLS:
            problems.append('pygame/ 下 DLL 只有 %d 个 (要求 >=%d)'
                            % (len(dlls), PYGAME_MIN_DLLS))
    if os.path.isfile(os.path.join(dist, 'SDL2.dll')):
        problems.append('SDL2.dll 仍在 dist 根 (旧布局残留)')
    for rel in (os.path.join('ckernels', 'loom_kernels.dll'), 'core_components'):
        if not os.path.exists(os.path.join(dist, rel)):
            problems.append('缺 %s（原生组件未随 dist，裸 dist 跑不起来）' % rel)
    return problems


def collect_files(src_dir):
    out = []
    for dirpath, dirnames, filenames in os.walk(src_dir):
        dirnames[:] = [d for d in dirnames
                       if d not in EXCLUDE_DIRS and not d.startswith('.')]
        for fn in filenames:
            if fn in EXCLUDE_FILES:
                continue
            ext = os.path.splitext(fn)[1].lower()
            if ext in EXCLUDE_EXTS:
                continue
            abs_p = os.path.join(dirpath, fn)
            rel_p = os.path.relpath(abs_p, src_dir).replace('\\', '/')
            out.append((abs_p, rel_p))
    return out


EMBED_URL_TMPL = ('https://www.python.org/ftp/python/{ver}/'
                 'python-{ver}-embed-amd64.zip')
EMBED_CACHE = os.environ.get('LOOM_PYEMBED_CACHE') or r'C:\loom_build\python-embed'


def source_python_version():
    """解释器.json 声明的 Python 版本 —— 内嵌版本与发布硬门的唯一口径。"""
    try:
        with open(META_PATH, 'r', encoding='utf-8') as f:
            return (json.load(f).get('python_version') or '').strip() or None
    except Exception:
        return None


def _python_exe_version(py_exe):
    """跑一次目标 python，返回 x.y.z；失败返回 None。"""
    try:
        out = subprocess.check_output(
            [py_exe, '-c', 'import sys;print("%d.%d.%d" % sys.version_info[:3])'],
            text=True, timeout=60, stderr=subprocess.STDOUT)
        return out.strip().splitlines()[-1].strip() or None
    except Exception:
        return None


def _download_embed(ver):
    r"""下载官方 embeddable 到 C:\loom_build\python-embed\<ver>\ 并解压。"""
    dest = os.path.join(EMBED_CACHE, ver)
    if os.path.isfile(os.path.join(dest, 'python.exe')):
        return dest
    os.makedirs(EMBED_CACHE, exist_ok=True)
    zpath = os.path.join(EMBED_CACHE, 'python-%s-embed-amd64.zip' % ver)
    url = EMBED_URL_TMPL.format(ver=ver)
    if not os.path.isfile(zpath):
        print('[打包] 下载 embeddable: %s' % url)
        try:
            import urllib.request
            urllib.request.urlretrieve(url, zpath)
        except Exception as e:
            print('[打包] 下载失败: %r' % (e,))
            return None
    try:
        with zipfile.ZipFile(zpath) as zf:
            zf.extractall(dest)
    except Exception as e:
        print('[打包] 解压失败: %r' % (e,))
        return None
    return dest if os.path.isfile(os.path.join(dest, 'python.exe')) else None


def find_python_embed(want_version=None):
    r"""定位 Python 运行时目录（优先 embeddable，最后本机同版本完整安装兜底）。

    顺序: LOOM_PYEMBED_DIR → tools/python-embed → C:\loom_build\python-embed\<ver>
          → 从 python.org 下载 embeddable → 本机 Python3xx 完整安装（版本必须一致）。
    """
    for d in (os.environ.get('LOOM_PYEMBED_DIR'),
              os.path.join(ROOT, 'tools', 'python-embed')):
        if d and os.path.isfile(os.path.join(d, 'python.exe')):
            return d
    if want_version:
        d = os.path.join(EMBED_CACHE, want_version)
        if os.path.isfile(os.path.join(d, 'python.exe')):
            return d
        d = _download_embed(want_version)
        if d:
            return d
        mm = want_version.split('.')
        tag = '%s%s' % (mm[0], mm[1]) if len(mm) >= 2 else ''
        for base in (os.path.expandvars(
                         r'%LOCALAPPDATA%\Programs\Python\Python' + tag),
                     r'C:\Python' + tag):
            exe = os.path.join(base, 'python.exe')
            if os.path.isfile(exe) and _python_exe_version(exe) == want_version:
                return base
    return None


def _patch_embed_pth(tmp_py):
    r"""embeddable 的 python3xx._pth 默认禁 site 且不含 site-packages：
    追加 Lib\site-packages、打开 import site，否则 pip 装的包 import 不到。"""
    import glob
    for pth in glob.glob(os.path.join(tmp_py, 'python*._pth')):
        with open(pth, 'r', encoding='utf-8') as f:
            lines = [ln.strip() for ln in f if ln.strip()]
        out = [ln for ln in lines if ln not in ('#import site', 'import site')]
        if not any(ln.replace('/', '\\').lower() == r'lib\site-packages'
                   for ln in out):
            out.insert(1, r'Lib\site-packages')
        # 源码包布局: <pkg>/python/python.exe + <pkg>/Loom/Loom.py。
        # _pth 是隔离模式，脚本目录不会自动进 sys.path -> 显式加 ..\Loom，
        # 否则 pythonw Loom\Loom.py 会 ModuleNotFoundError: plugin_loader。
        if not any(ln.replace('/', '\\').lower() == r'..\loom' for ln in out):
            out.insert(1, r'..\Loom')
        out.append('import site')
        with open(pth, 'w', encoding='utf-8') as f:
            f.write('\r\n'.join(out) + '\r\n')


def build_embed_pyzip(version, out_dir, want_version=None):
    want_version = want_version or source_python_version()
    py_root = find_python_embed(want_version)
    if py_root is None:
        raise SystemExit(
            '[错误] 找不到 Python %s 运行时（embeddable）。\n'
            '  处理: (1) 联网后重跑（会自动下载 python-%s-embed-amd64.zip 到 %s）；\n'
            '         (2) 或设置 LOOM_PYEMBED_DIR 指向已解压的同版本 embeddable。'
            % (want_version or '?', want_version or '?', EMBED_CACHE))
    got = _python_exe_version(os.path.join(py_root, 'python.exe'))
    # 发布硬门 #1: 候选运行时版本必须等于 解释器.json（早失败，不白跑 pip）
    if want_version and got != want_version:
        raise SystemExit(
            '[错误] 嵌入 Python 版本与 解释器.json 不一致，拒绝出包: '
            '运行时=%r, 解释器.json=%r\n  运行时目录: %s\n'
            '  处理: 换 Python %s 的 embeddable，或修正 Loom/解释器.json'
            % (got, want_version, py_root, want_version))
    print('[打包] 嵌入 Python: %s (%s)' % (py_root, got))
    tmp_py = os.path.join(out_dir, '_python_tmp')
    if os.path.isdir(tmp_py):
        shutil.rmtree(tmp_py)
    # embeddable 是扁平小包（无 Lib/、带 python3xx._pth）；完整安装才需要裁剪
    import glob as _glob
    is_embed = (not os.path.isdir(os.path.join(py_root, 'Lib'))) or bool(
        _glob.glob(os.path.join(py_root, 'python*._pth')))
    if is_embed:
        shutil.copytree(py_root, tmp_py)
    else:
        EXCL = {'__pycache__', 'test', 'tests', 'Doc', 'Tools', 'tcl',
                'idlelib', 'site-packages', 'Scripts'}
        shutil.copytree(py_root, tmp_py,
                        ignore=lambda d, names: [n for n in names if n in EXCL])
    site_pkg = os.path.join(tmp_py, 'Lib', 'site-packages')
    os.makedirs(site_pkg, exist_ok=True)
    req_path = os.path.join(ROOT, 'requirements.txt')
    if os.path.isfile(req_path):
        print('[打包] 安装运行时依赖（仅 requirements.txt 声明的包）...')
        subprocess.check_call([
            sys.executable, '-m', 'pip', 'install',
            '-r', req_path, '--target', site_pkg,
            '-q', '--no-warn-script-location',
        ])
    _patch_embed_pth(tmp_py)
    return tmp_py


def write_launcher(out_dir):
    r"""Loom.bat 双形态（2026-11-10 人类裁决 Q4=B）。

    编译包: 包内是 Loom\Loom.exe（无 python/、无 Loom.py）→ 直接启动 exe；
    源码包: 没有 exe → 回退 pythonw.exe + Loom.py。
    纯 ASCII（cmd 对 UTF-8 BAT 支持差，中文会乱码）。
    """
    bat = ('@echo off\r\n'
           'setlocal\r\n'
           'cd /d "%~dp0"\r\n'
           'if exist "%~dp0Loom\\Loom.exe" (\r\n'
           '  start "" "%~dp0Loom\\Loom.exe" %*\r\n'
           '  exit /b 0\r\n'
           ')\r\n'
           'if exist "%~dp0python\\pythonw.exe" (\r\n'
           '  if not defined LOOM_REMOTE_MODE set LOOM_REMOTE_MODE=1\r\n'
           '  "%~dp0python\\pythonw.exe" "%~dp0Loom\\Loom.py" %*\r\n'
           '  exit /b %errorlevel%\r\n'
           ')\r\n'
           'echo [Loom] incomplete package: Loom\\Loom.exe and python\\pythonw.exe are both missing\r\n'
           'pause\r\n'
           'exit /b 1\r\n')
    with open(os.path.join(out_dir, 'Loom.bat'), 'w', encoding='ascii') as f:
        f.write(bat)


def write_meta_readme(out_dir, version, slim=False, compiled=False,
                      python_version=None):
    r"""README 按包形态写（Q4=B）: 编译版双击 Loom\Loom.exe，源码版双击 Loom.bat。"""
    pyver = python_version or source_python_version() or '3.13.15'
    if compiled:
        readme = ('Loom 引擎 %s（编译版）\n================\n'
                  '双击 Loom\\Loom.exe 启动（Loom.bat 也可，会自动转 exe）。\n'
                  '本包不含嵌入式 Python、不含 .py 源码。\n\n'
                  '目录结构:\n'
                  '  Loom.bat              <- 双击启动（转 Loom\\Loom.exe）\n'
                  '  Loom\\Loom.exe         <- 编辑器主程序\n'
                  '  Loom\\build_game.exe   <- 游戏构建器\n'
                  '  Loom\\player_runtime\\  <- 预置玩家运行时\n'
                  '  Loom\\解释器.json      <- LoomHub 识别元数据（python_version=%s）\n'
                  ) % (version, pyver)
    else:
        readme = ('Loom 引擎 %s\n================\n'
                  '双击 Loom.bat 启动（内嵌 Python %s）。\n\n'
                  '目录结构:\n'
                  '  Loom.bat          <- 双击启动\n'
                  '  python/           <- 嵌入式 Python %s（含依赖）\n'
                  '  Loom/             <- 引擎源码\n'
                  '    Loom.py         <- 主程序\n'
                  '    解释器.json     <- LoomHub 识别元数据\n'
                  ) % (version, pyver, pyver)
    if slim:
        readme += ('\n【精简包 / 无预置运行时】\n'
                   '本包**没有**预置播放器运行时（Loom/player_runtime/game_player.dist）。\n'
                   '打包游戏需要本机具备 Nuitka + MSVC，先跑 build_game.py --build-runtime；\n'
                   '或用 --runtime 指定一份已有的 dist 目录。正式发布包不应是精简包。\n')
    with open(os.path.join(out_dir, 'README.txt'), 'w', encoding='utf-8') as f:
        f.write(readme)



def _dir_size(path):
    total = 0
    for dirpath, _dirs, fnames in os.walk(path):
        for fn in fnames:
            try:
                total += os.path.getsize(os.path.join(dirpath, fn))
            except OSError:
                pass
    return total


def make_zip(version, allow_missing_runtime=False, kind='source'):
    # R6-03 (2026-11-10): --version 不得覆盖不一致的元数据 —— 源码包版本
    # 必须与 Loom/解释器.json 一致，否则 exit 1（以前只写警告/直接改写）。
    _bad = meta_version_problems(ENGINE_DIR, version)
    if _bad:
        raise SystemExit('[错误] 源码元数据版本与目标版本不符，拒绝出包: %s'
                         % ('; '.join(_bad),))
    os.makedirs(DIST_DIR, exist_ok=True)
    tmp_dir = os.path.join(DIST_DIR, '_Loom_%s_tmp' % version)
    if os.path.isdir(tmp_dir):
        shutil.rmtree(tmp_dir)
    os.makedirs(tmp_dir)
    key = {}        # 本包的附加标记 (slim = 精简包/无预置运行时)
    print('[打包] 收集引擎文件...')
    engine_files = collect_files(ENGINE_DIR)
    print('[打包] 引擎文件数: %d' % len(engine_files))
    for abs_p, rel_p in engine_files:
        dst = os.path.join(tmp_dir, 'Loom', rel_p)
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.copy2(abs_p, dst)
    # 2026-11-07 Unity 对齐: 预置"编译好的播放器运行时"随引擎分发。
    # Unity 的 UnityPlayer.dll 是随编辑器出厂的; Loom 之前是游戏开发机现场用
    # Nuitka+MSVC 编 (无编译器的机器直接失败)。这里打包时把开发机上已编好的
    # player_runtime/game_player.dist 一起塞进引擎包的 Loom/player_runtime/，
    # 之后 build_game.py 直接复用 -> 游戏开发机零编译器。
    _pr_root = os.path.join(ENGINE_DIR, 'player_runtime')
    _pr_src = _runtime_dist(_pr_root)
    key['slim'] = False
    if _pr_src is not None:
        # R6-03: 预置运行时的嵌套 解释器.json 也必须与目标版本一致
        # （否则会出现"顶层 beta6 + 运行时 beta5"的自检通过坏包）
        _bad = meta_version_problems(_pr_src, version)
        if _bad:
            raise SystemExit('[错误] 预置运行时元数据版本与目标版本不符，拒绝出包: %s'
                             % ('; '.join(_bad),))
        # 2026-11-09: 运行时布局硬断言（缺 pygame/ 或旧布局 -> 拒绝打包，
        # 否则会产出"能装能跑编辑器、一做游戏就缺 SDL2.dll"的坏包）
        _layout = runtime_layout_problems(_pr_src)
        if _layout:
            raise SystemExit(
                '[错误] 播放器运行时布局不符，拒绝打包: %s\n  dist: %s\n'
                '  处理: 用 Nuitka 4.x 重新跑 build_game.py --build-runtime'
                % ('; '.join(_layout), _pr_src))
        _pr_dst = os.path.join(tmp_dir, 'Loom', 'player_runtime', 'game_player.dist')
        _t = time.time()
        shutil.copytree(_pr_src, _pr_dst, dirs_exist_ok=True)
        print('[打包] 预置播放器运行时: %.1f MB (%.1fs)  (%s)'
              % (_dir_size(_pr_src) / 1048576.0, time.time() - _t, _pr_src))
        try:
            with open(os.path.join(tmp_dir, 'Loom', 'player_runtime', '运行时.json'),
                      'w', encoding='utf-8') as _f:
                json.dump({'version': version, 'built_at': time.strftime('%Y-%m-%d %H:%M:%S'),
                           'note': '预编译播放器运行时 (Unity UnityPlayer 同角色); '
                                   'build_game.py 直接复用, 游戏开发机无需编译器'}, _f,
                          ensure_ascii=False, indent=1)
        except Exception as _e:
            # 契约 §7: 写失败必须可判定，不再 except: pass
            raise SystemExit('[错误] 写 运行时.json 失败: %r' % (_e,))
    elif allow_missing_runtime:
        key['slim'] = True
        print('[打包] 警告: 未找到预置播放器运行时 (%s)——按 --allow-missing-runtime '
              '产出【精简包】: 包内元数据与 README 会显式标记"无预置运行时"。' % _pr_root)
    else:
        # beta4 / P-05-04: 缺运行时是"发布包少掉头号特性"，默认必须失败而不是警告
        raise SystemExit(
            '[错误] 缺少预置播放器运行时，拒绝产出发布包。\n'
            '  期望: %s\ngame_player.dist\\MyGame.exe\n'
            '  两种成因: (1) player_runtime 目录不存在（该目录不入库，'
            '全新 clone 天然没有）；(2) 目录在但没有 game_player.dist\\MyGame.exe'
            '（--build-runtime 中途失败或只拷了一半）。\n'
            '  处理: 在带 Nuitka+MSVC 的引擎开发机跑 build_game.py --build-runtime，'
            '或从已有安装包/上次构建拷一份 game_player.dist 过来；\n'
            '  若确实要产出不带走时器的调试瘦包，显式加 --allow-missing-runtime。'
            % _pr_root)
    # Q1/Q3: 内嵌 Python 跟随 解释器.json 的 python_version；版本不一致 = 拒绝出包
    _want_py = source_python_version()
    print('[打包] 复制嵌入式 Python（目标 %s）...' % (_want_py or '?'))
    tmp_py = build_embed_pyzip(version, tmp_dir, want_version=_want_py)
    _py_actual = _python_exe_version(os.path.join(tmp_py, 'python.exe'))
    if not _py_actual:
        raise SystemExit('[错误] 包内 Python 起不来，无法确认版本: %s'
                         % os.path.join(tmp_py, 'python.exe'))
    if _want_py and _py_actual != _want_py:
        raise SystemExit(
            '[错误] 包内 Python 实际版本与 解释器.json 不一致，拒绝出包: '
            'embedded=%r, 解释器.json=%r' % (_py_actual, _want_py))
    target_py = os.path.join(tmp_dir, 'python')
    shutil.move(tmp_py, target_py)
    # 2026-11-07 修复: --version 只改 zip 文件名, 包内 解释器.json 仍是旧版本 ->
    # LoomHub 按元数据登记会装成旧版本 (实测 beta3 包被登记成 beta2)。
    # 这里把请求的 version 写回包内元数据, 保证"文件名/元数据/安装目录"三者一致。
    # beta4 / P-05-05: 回写失败以前只打一行警告就继续出包, 结果是"打包完成"但
    # LoomHub 报"不是有效的 Loom 解释器包"。契约 §7 要求写失败可判定 -> 直接失败。
    _meta_dst = os.path.join(tmp_dir, 'Loom', os.path.basename(META_PATH))
    try:
        with open(_meta_dst, 'r', encoding='utf-8') as _f:
            _meta = json.load(_f)
    except Exception as _e:
        raise SystemExit('[错误] 读不到/解析不了源元数据 %s: %r '
                         '（先修复该文件再打包）' % (_meta_dst, _e))
    _meta['version'] = version
    _meta['python_version'] = _py_actual
    if key.get('slim'):
        _meta['distribution'] = 'slim'
        _meta['player_runtime'] = 'absent'
    try:
        with open(_meta_dst, 'w', encoding='utf-8') as _f:
            json.dump(_meta, _f, ensure_ascii=False, indent=2)
    except Exception as _e:
        raise SystemExit('[错误] 元数据回写失败 %s: %r' % (_meta_dst, _e))
    print('[打包] 元数据版本 -> %s%s'
          % (version, '  (精简包: 无预置运行时)' if key.get('slim') else ''))
    write_launcher(tmp_dir)
    write_meta_readme(tmp_dir, version, slim=bool(key.get('slim')),
                      python_version=_py_actual)
    zip_path = os.path.join(DIST_DIR, 'Loom-%s-%s.zip' % (version, kind))
    print('[打包] 写 zip: %s' % zip_path)
    if os.path.exists(zip_path):
        os.remove(zip_path)
    with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        for dirpath, _dirnames, filenames in os.walk(tmp_dir):
            for fn in filenames:
                abs_p = os.path.join(dirpath, fn)
                rel_p = os.path.relpath(abs_p, tmp_dir).replace('\\', '/')
                zf.write(abs_p, rel_p)
    # beta4 / P-05-05/06: 收尾自检 —— 从**已写好的 zip** 里读回元数据，交给
    # LoomHub 的同一份判据验一遍；同时验"包名版本 == 元数据版本"与运行时到位性。
    # 任何一项不过：删掉这个坏包并失败退出（绝不把装不上的包留在 dist 里）。
    _verify_zip(zip_path, version, slim=bool(key.get('slim')))
    # Windows 下 DLL 可能仍被占用，忽略清理失败（不影响 zip 产物）
    try:
        shutil.rmtree(tmp_dir, ignore_errors=True)
    except Exception:
        pass
    size_mb = os.path.getsize(zip_path) / (1024 * 1024)
    print('[打包] 完成: %s (%.2f MB)' % (zip_path, size_mb))
    return zip_path


def _verify_zip(zip_path, version, slim=False):
    """对已写好的 zip 做发版自检（包名 / 元数据 / 运行时三者一致）。"""
    _bad = []

    def _fail(msg):
        print('[打包][自检失败] %s' % msg)
        _bad.append(msg)

    base = os.path.basename(zip_path)
    # 2026-11-10 Q-PKG-4: 源码包/编译包分开命名（-source / -compiled），
    # 自检接受三种合法名（旧名保留兼容）。
    _allowed = {'Loom-%s.zip' % version,
                'Loom-%s-source.zip' % version,
                'Loom-%s-compiled.zip' % version}
    if base not in _allowed:
        _fail('包名与版本不一致: %r 不在 %r' % (base, sorted(_allowed)))
    try:
        with zipfile.ZipFile(zip_path) as zf:
            names = set(zf.namelist())
            try:
                _meta = json.loads(zf.read('Loom/解释器.json').decode('utf-8'))
            except Exception as e:
                _meta = None
                _fail('包内 解释器.json 读不回来/不是合法 JSON: %r' % (e,))
            if _meta is not None:
                hc = _hub_config()
                reason = hc.validate_meta(_meta, _meta.get('version'))
                if reason is not None:
                    _fail('包内元数据不合 LoomHub 判据: %s' % reason)
                if str(_meta.get('version')) != version:
                    _fail('包内元数据版本 %r != 请求版本 %r'
                          % (_meta.get('version'), version))
                want = 'slim' if slim else None
                got = _meta.get('distribution')
                if want != got:
                    _fail('精简标记不一致: 期望 %r 实际 %r' % (want, got))
                # R6-03: 嵌套运行时元数据版本必须与顶层一致
                _nkey = 'Loom/player_runtime/game_player.dist/解释器.json'
                if _nkey in names:
                    try:
                        _nmeta = json.loads(zf.read(_nkey).decode('utf-8'))
                    except Exception as e:
                        _fail('嵌套运行时 解释器.json 读不回来: %r' % (e,))
                    else:
                        if str(_nmeta.get('version')) != version:
                            _fail('嵌套运行时元数据版本 %r != 目标 %r'
                                  % (_nmeta.get('version'), version))
            exe_key = 'Loom/player_runtime/game_player.dist/MyGame.exe'
            has_exe = exe_key in names
            if slim and has_exe:
                _fail('标称精简包却打进了预置运行时')
            if not slim and not has_exe:
                _fail('正式包缺少预置运行时 (%s)' % exe_key)
    except SystemExit:
        raise
    except Exception as e:
        _fail('无法打开刚写出的 zip: %r' % (e,))
    if _bad:
        try:
            os.remove(zip_path)
        except OSError:
            pass
        raise SystemExit('[错误] 发版自检未通过（已删除坏包）: %d 项 -> %s'
                         % (len(_bad), _bad))
    print('[打包] 自检通过: 包名/元数据/运行时一致（版本 %s%s）'
          % (version, ', 精简包' if slim else ''))


def main():
    parser = argparse.ArgumentParser(description='Loom 引擎发布包打包器')
    parser.add_argument('--version', help='覆盖版本号（默认读 Loom/解释器.json）')
    parser.add_argument('--kind', choices=('source', 'compiled'), default='source',
                        help='产物类型（默认 source）: 产物名 Loom-<ver>-<kind>.zip；'
                             '与编译包分开，避免互相覆盖')
    parser.add_argument('--allow-missing-runtime', action='store_true',
                        help='允许产出【精简包】(无预置播放器运行时)；默认缺运行时即失败')
    args = parser.parse_args()
    version = check_version(load_version(args.version))
    print('=' * 60)
    print('Loom 引擎打包 — 版本 %s' % version)
    print('=' * 60)
    zip_path = make_zip(version, allow_missing_runtime=args.allow_missing_runtime,
                        kind=args.kind)
    print()
    print('下一步:')
    print('  1) 测试: 解压 %s' % os.path.basename(zip_path))
    print('  2) 上传: GitHub Releases -> tag engine-v%s -> 上传 zip' % version)
    print('     或: set LOOM_ENGINE_VERSION=%s && python tools\\release_github.py engine'
          % version)


if __name__ == '__main__':
    main()
