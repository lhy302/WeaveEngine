# -*- coding: utf-8 -*-
r"""build_engine.py — 引擎三件产物构建器（两档：dev 带控制台 / release 无控制台）

为什么有两档（2026-11-09 人类裁决）：
  · dev   —— 内部开发用，--windows-console-mode=force：exe 起控制台，print/traceback
             直接可见（当初 Loom.exe --bench 静默 exit 1 就是因为 release 无控制台，
             错误被吞掉）。dev 产物**不可发布**，只能本地诊断/调试。
  · release —— 发布用，--windows-console-mode=disable：无控制台，产物可被
             tools/package_engine_compiled.py 消费（打包器会硬校验 build_info.json）。

产物目录（两档物理分开，避免拿错）：
  dev     : C:\loom_build\engine_dev / builder_dev / runtime_dev
  release : C:\loom_build\engine     / builder      / Loom\player_runtime

2026-11-13 打包形态整改（360 只报 build_game.exe 的裁决）：
  · 构建器 onefile -> onedir（--mode=standalone）：产物是
    <out>/build_game.dist/build_game.exe，不再自解压到 %TEMP%（投放器特征）。
  · 三个 exe 全部补 Windows 版本资源（--company-name/--product-name/
    --file-version/--product-version/--file-description/--copyright）；
    版本号取自 Loom/解释器.json 的 version，不硬编码。
  · 运行时是经 Loom/build_game.py --build-runtime 间接调 Nuitka 的，旗标走
    环境变量 LOOM_BUILD_VER_FLAGS 传下去（build_game.py 只做参数拼接）。

用法（必须用 3.13）：
  py -3.13 tools/build_engine.py --mode dev
  py -3.13 tools/build_engine.py --mode release
  py -3.13 tools/build_engine.py --mode dev --what editor,builder
  py -3.13 tools/build_engine.py --mode release --skip-vcvars   # 已自行进过 vcvars 时
"""
import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOOM = os.path.join(ROOT, 'Loom')
BUILD_ROOT = os.environ.get('LOOM_BUILD_ROOT', r'C:\loom_build')

MODES = {
    'dev': {'console': 'force', 'packageable': False,
            'editor': os.path.join(BUILD_ROOT, 'engine_dev'),
            'builder': os.path.join(BUILD_ROOT, 'builder_dev'),
            'runtime': os.path.join(BUILD_ROOT, 'runtime_dev')},
    'release': {'console': 'disable', 'packageable': True,
                'editor': os.path.join(BUILD_ROOT, 'engine'),
                'builder': os.path.join(BUILD_ROOT, 'builder'),
                'runtime': os.path.join(LOOM, 'player_runtime')},
}
WHAT = ('editor', 'builder', 'runtime')


def _fail(msg):
    print('[build_engine] 错误: ' + msg, file=sys.stderr)
    raise SystemExit(1)


def _run(cmd, cwd, env=None):
    print('[build_engine] $ ' + subprocess.list2cmdline(cmd))
    t0 = time.time()
    rc = subprocess.call(cmd, cwd=cwd, env=env)
    if rc != 0:
        _fail('命令失败 (exit %d): %s' % (rc, subprocess.list2cmdline(cmd)))
    return time.time() - t0


def _find_vcvars():
    vswhere = os.path.join(os.environ.get('ProgramFiles(x86)', r'C:\Program Files (x86)'),
                           'Microsoft Visual Studio', 'Installer', 'vswhere.exe')
    if not os.path.isfile(vswhere):
        return None
    try:
        out = subprocess.check_output(
            [vswhere, '-latest', '-products', '*', '-requires',
             'Microsoft.VisualStudio.Component.VC.Tools.x86.x64', '-property',
             'installationPath'], text=True).strip()
    except subprocess.CalledProcessError:
        return None
    if not out:
        return None
    p = os.path.join(out.splitlines()[0].strip(), 'VC', 'Auxiliary', 'Build', 'vcvars64.bat')
    return p if os.path.isfile(p) else None


def _enter_vcvars():
    """把 vcvars64 的环境灌进当前进程（Nuitka 会读 PATH/INCLUDE/LIB）。"""
    vcvars = _find_vcvars()
    if not vcvars:
        _fail('找不到 vcvars64.bat（vswhere 无 VS C++ 工具集）')
    out = subprocess.check_output(
        'cmd /c ""%s" >nul && set"' % vcvars, shell=True, text=True,
        encoding='mbcs', errors='replace')
    for line in out.splitlines():
        if '=' not in line:
            continue
        k, v = line.split('=', 1)
        os.environ[k] = v
    cl = shutil.which('cl')
    print('[build_engine] vcvars64: %s' % vcvars)
    print('[build_engine] cl: %s' % (cl or '<PATH 里没有>'))
    if not cl:
        _fail('vcvars 后 PATH 里仍没有 cl.exe')


def _git_info():
    """来源工作树的提交与脏标记（build_info 硬证据）。
    2026-11-10: compiled 包不含 .py，靠 git_head 才能证明"包 = 哪次提交"。"""
    head = None
    dirty = None
    try:
        head = subprocess.check_output(
            ['git', '-C', ROOT, 'rev-parse', 'HEAD'], encoding='utf-8',
            errors='replace', stderr=subprocess.DEVNULL).strip() or None
    except Exception:
        head = None
    try:
        # 注意: 文件名含中文 -> 必须 utf-8 解码（text=True 走 GBK 会抛错）
        dirty = bool(subprocess.check_output(
            ['git', '-C', ROOT, 'status', '--porcelain'], encoding='utf-8',
            errors='replace', stderr=subprocess.DEVNULL).strip())
    except Exception:
        dirty = None
    return head, dirty


def _nuitka_version():
    try:
        out = subprocess.check_output([sys.executable, '-m', 'nuitka', '--version'],
                                      text=True, stderr=subprocess.STDOUT)
        return out.splitlines()[0].strip()
    except Exception:
        return 'unknown'


def _stash_prev(dist_dir):
    """把上一次的 dist 改名成 .__prev（不删，便于回滚；每次只留一份）。"""
    if not os.path.isdir(dist_dir):
        return
    prev = dist_dir + '.__prev'
    if os.path.isdir(prev):
        shutil.rmtree(prev)
    os.rename(dist_dir, prev)
    print('[build_engine] 旧产物已挪到 %s' % prev)


def _source_engine_version():
    try:
        with open(os.path.join(LOOM, '解释器.json'), 'r', encoding='utf-8') as f:
            return (json.load(f).get('version') or '').strip() or None
    except Exception:
        return None


# 2026-11-13 版本资源（360 误报整改第 2 条）: 三个 exe 必须带非空 CompanyName/
# ProductName/FileDescription/FileVersion，否则安全软件与资源管理器都只能看到
# 一个"无名无版本"的未知二进制。Nuitka 4.3.5 已确认支持下列旗标。
VER_COMPANY = 'lhy302'
VER_PRODUCT = 'Loom'
VER_DESCRIPTIONS = {
    'editor': 'Loom 引擎编辑器',
    'builder': 'Loom 游戏打包器（将项目打包为独立游戏）',
    'runtime': 'Loom 游戏运行时',
}
COPYRIGHT_FALLBACK = 'MIT License, (c) lhy302'


def _copyright_text():
    """版权串 = LICENSE 首行；首行没有版权主体时用兜底。

    LICENSE 首行只有 "MIT License"（主体在第三行），单独写进版本资源会丢掉
    "谁的版权"，所以首行不含 copyright/(c) 时退回 COPYRIGHT_FALLBACK。
    """
    try:
        with open(os.path.join(ROOT, 'LICENSE'), 'r', encoding='utf-8') as f:
            first = f.readline().strip()
    except Exception:
        first = ''
    if first and ('copyright' in first.lower() or '(c)' in first.lower()):
        return first
    return COPYRIGHT_FALLBACK


def _numeric_version(raw):
    """"0.1.0.beta6" -> "0.1.0.6"（Nuitka 的 --file-version 只收最多 4 段纯数字）。

    每一段取其中的数字（"beta6" -> 6：前导数字优先，否则取末尾数字），不足
    4 段补 0；版本号仍由 Loom/解释器.json 单一事实源决定，不硬编码 beta 号。
    """
    parts = []
    for seg in str(raw or '').split('.'):
        seg = seg.strip()
        m = re.match(r'(\d+)', seg) or re.search(r'(\d+)$', seg)
        parts.append(m.group(1) if m else '0')
    while len(parts) < 4:
        parts.append('0')
    return '.'.join(parts[:4])


def _ver_flags(kind, version):
    """返回 Nuitka 版本资源旗标列表（kind 决定 FileDescription）。"""
    if kind not in VER_DESCRIPTIONS:
        _fail('未知产物类型 %r（未定义版本资源描述）' % (kind,))
    if not version:
        _fail('读不到 Loom/解释器.json 的 version，无法写版本资源')
    num = _numeric_version(version)
    return ['--company-name=%s' % VER_COMPANY,
            '--product-name=%s' % VER_PRODUCT,
            '--file-version=%s' % num,
            '--product-version=%s' % num,
            '--file-description=%s' % VER_DESCRIPTIONS[kind],
            '--copyright=%s' % _copyright_text()]


def _assert_meta(dist, label):
    """产物必须带 解释器.json 且 version = 源码版本（sceneio 版本闸的单一事实源）。"""
    path = os.path.join(dist, '解释器.json')
    src = _source_engine_version()
    if not os.path.isfile(path):
        _fail('%s 缺 解释器.json（会静默走 sceneio 常量兜底）: %s' % (label, path))
    try:
        with open(path, 'r', encoding='utf-8') as f:
            got = (json.load(f).get('version') or '').strip()
    except Exception as e:
        _fail('%s 的解释器.json 读不了: %r' % (label, e))
    if not src or got != src:
        _fail('%s 的 解释器.json version=%r != 源码 %r' % (label, got, src))


def _write_info(path, info):
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(info, f, ensure_ascii=False, indent=1)


# 运行期数据目录：必须进编辑器 dist（`--bench`/播放模式在 import 阶段就要 ckernels，
# 裸 dist 缺它 = RuntimeError: loom_kernels.dll 未找到）。2026-11-09 起全部内置，
# 不再依赖 package_engine_compiled 在发布包里补（那会导致"裸 dist 不能跑 bench"）。
# 2026-11-13 T3: 着色器改成**运行时读文件**（Loom/shaders/*.glsl *.frag *.vert *.spv），
# `loom_shaders.py` 在 import 阶段就读，裸 dist 缺 shaders/ = FileNotFoundError。
# 所以 shaders 必须和其它运行期数据目录一样进 dist。
DATA_DIRS = ('ckernels', 'core_components', 'core_plugins', 'plugins',
             'scripts', 'GUI', 'assets', 'shaders')
DATA_FILES = ('设置.json', '输入配置.default.json', '解释器.json')


def _data_includes():
    inc = []
    for d in DATA_DIRS:
        p = os.path.join(LOOM, d)
        if os.path.isdir(p):
            inc.append('--include-data-dir=%s=%s' % (p, d))
    for f in DATA_FILES:
        p = os.path.join(LOOM, f)
        if os.path.isfile(p):
            inc.append('--include-data-files=%s=%s' % (p, f))
    return inc


def _sync_data_dirs(dist):
    """Nuitka 4.x 的 --include-data-dir 会跳过 *.dll（6 个 core_components DLL
    与 loom_kernels.dll 都不进 dist），所以构建后再整目录拷一遍补齐。
    幂等覆盖，保证裸 dist 自洽。"""
    for d in DATA_DIRS:
        src = os.path.join(LOOM, d)
        if os.path.isdir(src):
            shutil.copytree(src, os.path.join(dist, d), dirs_exist_ok=True)
    for f in DATA_FILES:
        src = os.path.join(LOOM, f)
        if os.path.isfile(src):
            shutil.copy2(src, os.path.join(dist, f))


def build_editor(mode, cfg, info):
    out = cfg['editor']
    dist = os.path.join(out, 'build_entry.dist')
    _stash_prev(dist)
    cmd = [sys.executable, '-m', 'nuitka', '--mode=standalone', '--msvc=latest',
           '--assume-yes-for-downloads', '--enable-plugin=pyside6',
           '--windows-console-mode=%s' % cfg['console'],
           '--nofollow-import-to=cupy'] + _data_includes() + \
          _ver_flags('editor', info.get('version')) + [
           '--output-dir=%s' % out, '--output-filename=Loom.exe',
           os.path.join(LOOM, 'build_entry.py')]
    secs = _run(cmd, cwd=LOOM)
    _sync_data_dirs(dist)
    _assert_meta(dist, '编辑器 dist')
    exe = os.path.join(dist, 'Loom.exe')
    qt = os.path.join(dist, 'PySide6', 'qt-plugins', 'platforms', 'qwindows.dll')
    if not os.path.isfile(exe):
        _fail('编辑器产物缺失: %s' % exe)
    if not os.path.isfile(qt):
        _fail('编辑器 dist 缺 Qt 平台插件（Nuitka 必须带 --enable-plugin=pyside6）: %s' % qt)
    kerns = os.path.join(dist, 'ckernels', 'loom_kernels.dll')
    if not os.path.isfile(kerns):
        _fail('编辑器 dist 缺 ckernels/loom_kernels.dll（裸 dist 会 RuntimeError，'
              '--bench 直接 exit 1）: %s' % kerns)
    core = os.path.join(dist, 'core_components')
    if not os.path.isdir(core) or not os.listdir(core):
        _fail('编辑器 dist 缺 core_components/（运行时核心组件 DLL）: %s' % core)
    # 2026-11-13 T3: 着色器运行时读文件；缺 shaders/ 或没有 .spv = 一启动就崩。
    # 用「文件数 + 至少一个 .spv」做断言，避免空目录也算通过。
    shd = os.path.join(dist, 'shaders')
    if not os.path.isdir(shd) or not os.listdir(shd):
        _fail('编辑器 dist 缺 shaders/（T3 起着色器运行时读文件，缺了 import 即崩）: %s' % shd)
    if not any(n.endswith('.spv') for n in os.listdir(shd)):
        _fail('编辑器 dist 的 shaders/ 里没有 .spv（先跑 tools/build_shaders.py）: %s' % shd)
    _write_info(os.path.join(dist, 'build_info.json'), info)
    _write_info(os.path.join(out, 'build_info.json'), info)
    return {'path': exe, 'size_mb': _dir_mb(dist), 'seconds': round(secs, 1)}


def _builder_includes():
    """构建器（onedir）必须自带原生组件与版本元数据。

    2026-11-11 冒烟抓到: fastpath 在程序目录找 ckernels/loom_kernels.dll ——
    不带就 import 即崩（build_game.exe --help exit 1）。2026-11-13 从 onefile 改
    onedir 后语义不变：原生目录仍要随 dist 分发（Nuitka 会跳过 *.dll，构建后补拷）。
    """
    inc = []
    # shaders: 2026-11-13 起 build_game 也是 import loom_shaders，程序目录里
    # 必须有 shaders/（否则 build_game.exe 一启动就 FileNotFoundError）。
    for d in ('ckernels', 'core_components', 'shaders'):
        p = os.path.join(LOOM, d)
        if os.path.isdir(p):
            inc.append('--include-data-dir=%s=%s' % (p, d))
    meta = os.path.join(LOOM, '解释器.json')
    if os.path.isfile(meta):
        inc.append('--include-data-files=%s=解释器.json' % meta)
    return inc


BUILDER_DATA_DIRS = ('ckernels', 'core_components', 'shaders')


def _sync_builder_data(dist):
    """构建器 dist 自带原生组件目录（Nuitka 4.x 的 --include-data-dir 跳过 *.dll，
    不补拷 = 缺 ckernels/loom_kernels.dll，fastpath 硬 raise）。"""
    for d in BUILDER_DATA_DIRS:
        src = os.path.join(LOOM, d)
        if os.path.isdir(src):
            shutil.copytree(src, os.path.join(dist, d), dirs_exist_ok=True)


def build_builder(mode, cfg, info):
    """构建器: 2026-11-13 起 onedir（--mode=standalone）。

    onefile 会自解压到 %TEMP% 再执行，是安全软件眼里的"投放器"特征（360 只报
    这一个 exe 的根因之一），所以改成 <out>/build_game.dist/build_game.exe。
    """
    out = cfg['builder']
    dist = os.path.join(out, 'build_game.dist')
    exe = os.path.join(dist, 'build_game.exe')
    _stash_prev(dist)
    # 旧 onefile 单文件产物挪开（不删，便于回滚；也不能和新 dist 混在同一目录）
    stale = os.path.join(out, 'build_game.exe')
    if os.path.isfile(stale):
        prev = stale + '.__prev'
        if os.path.isfile(prev):
            os.remove(prev)
        os.rename(stale, prev)
        print('[build_engine] 旧 onefile 构建器已挪到 %s' % prev)
    cmd = [sys.executable, '-m', 'nuitka', '--mode=standalone', '--msvc=latest',
           '--assume-yes-for-downloads',
           '--windows-console-mode=%s' % cfg['console']] + _builder_includes() + \
          _ver_flags('builder', info.get('version')) + [
           '--output-dir=%s' % out, '--output-filename=build_game.exe',
           os.path.join(LOOM, 'build_game.py')]
    secs = _run(cmd, cwd=LOOM)
    _sync_builder_data(dist)
    _assert_meta(dist, '构建器 dist')
    if not os.path.isfile(exe):
        _fail('构建器产物缺失: %s' % exe)
    kern = os.path.join(dist, 'ckernels', 'loom_kernels.dll')
    if not os.path.isfile(kern):
        _fail('构建器 dist 缺 ckernels/loom_kernels.dll（fastpath 硬加载，'
              '--help 会 RuntimeError）: %s' % kern)
    shd = os.path.join(dist, 'shaders')
    if not os.path.isdir(shd) or not any(n.endswith('.spv') for n in os.listdir(shd)):
        _fail('构建器 dist 的 shaders/ 里没有 .spv（先跑 tools/build_shaders.py）: %s'
              % shd)
    _write_info(os.path.join(dist, 'build_info.json'), info)
    _write_info(os.path.join(out, 'build_info.json'), info)
    dist_mb = _dir_mb(dist)
    return {'path': exe, 'dist': dist, 'dist_size_mb': dist_mb,
            'size_mb': dist_mb, 'seconds': round(secs, 1)}


def build_runtime(mode, cfg, info):
    out = cfg['runtime']
    dist = os.path.join(out, 'game_player.dist')
    _stash_prev(dist)
    env = dict(os.environ)
    env['LOOM_BUILD_CONSOLE_MODE'] = cfg['console']
    env['LOOM_BUILD_RUNTIME_DIR'] = out
    # 运行时由 build_game.py 间接调 Nuitka：版本资源旗标用换行分隔的环境变量传下去
    # （build_game.py 只把这些行拼接进自己的 Nuitka 命令行，打包逻辑零改动）。
    env['LOOM_BUILD_VER_FLAGS'] = '\n'.join(_ver_flags('runtime', info.get('version')))
    cmd = [sys.executable, os.path.join(LOOM, 'build_game.py'), '--build-runtime']
    secs = _run(cmd, cwd=LOOM, env=env)
    _assert_meta(dist, '运行时 dist')
    exe = os.path.join(dist, 'MyGame.exe')
    if not os.path.isfile(exe):
        _fail('运行时产物缺失: %s' % exe)
    _write_info(os.path.join(dist, 'build_info.json'), info)
    _write_info(os.path.join(out, 'build_info.json'), info)
    return {'path': exe, 'size_mb': _dir_mb(dist), 'seconds': round(secs, 1)}


def _dir_mb(path):
    total = sum(os.path.getsize(os.path.join(dp, f))
                for dp, _, fs in os.walk(path) for f in fs)
    return round(total / 1048576.0, 1)


def main():
    ap = argparse.ArgumentParser(description='Loom 引擎三件构建（dev=带控制台 / release=无控制台）')
    ap.add_argument('--mode', required=True, choices=sorted(MODES))
    ap.add_argument('--what', default='editor,builder,runtime',
                    help='逗号分隔: editor,builder,runtime')
    ap.add_argument('--skip-vcvars', action='store_true', help='已自行进入 VS 环境时跳过')
    args = ap.parse_args()

    cfg = MODES[args.mode]
    what = [w.strip() for w in args.what.split(',') if w.strip()]
    bad = [w for w in what if w not in WHAT]
    if bad:
        _fail('未知产物: %s（可选 %s）' % (', '.join(bad), ','.join(WHAT)))
    if sys.version_info[:2] != (3, 13):
        _fail('必须用 py -3.13 运行（当前 %s）；3.12 仅作回滚环境' 
              % '.'.join(map(str, sys.version_info[:3])))

    print('=' * 64)
    print('[build_engine] 档位: %s  (console=%s, packageable=%s)'
          % (args.mode, cfg['console'], cfg['packageable']))
    print('[build_engine] python: %s' % sys.executable)
    print('[build_engine] nuitka: %s' % _nuitka_version())
    print('[build_engine] 产物: %s' % ', '.join(
        '%s=%s' % (w, cfg[w]) for w in what))
    if args.mode == 'dev':
        print('[build_engine] 提醒: dev 产物带控制台, 仅供诊断/调试, 不可发布')
    print('=' * 64)
    if not args.skip_vcvars:
        _enter_vcvars()

    _git_head, _git_dirty = _git_info()
    _version = _source_engine_version()
    info = {
        'mode': args.mode,
        'version': _version,
        'console_mode': cfg['console'],
        'packageable': cfg['packageable'],
        'python': sys.version.split()[0],
        'nuitka': _nuitka_version(),
        'built_at': time.strftime('%Y-%m-%d %H:%M:%S'),
        'git_head': _git_head,
        'git_dirty': _git_dirty,
        # 冒烟门序: 构建后由 tools/smoke.py 盖章，打包脚本要求
        # smoke_passed_at 存在且晚于 built_at（编译→冒烟→打包→对拍）。
        'smoke_passed_at': None,
    }
    print('[build_engine] git_head=%s git_dirty=%s version=%s'
          % (_git_head or '<不可用>', _git_dirty, _version or '<不可用>'))
    results = {}
    t_all = time.time()
    if 'editor' in what:
        results['editor'] = build_editor(args.mode, cfg, info)
    if 'builder' in what:
        results['builder'] = build_builder(args.mode, cfg, info)
    if 'runtime' in what:
        results['runtime'] = build_runtime(args.mode, cfg, info)

    print('=' * 64)
    print('[build_engine] 完成: mode=%s console=%s 用时 %.0fs'
          % (args.mode, cfg['console'], time.time() - t_all))
    for k, v in results.items():
        extra = ('  dist=%s' % v['dist']) if v.get('dist') else ''
        print('  %-8s %8.1f MB  %6.0fs  %s%s'
              % (k, v['size_mb'], v['seconds'], v['path'], extra))
    if args.mode == 'release':
        print('[build_engine] 现在可打包: py -3.13 tools/package_engine_compiled.py '
              '--version <版本> --editor-dist %s --builder-exe %s'
              % (os.path.join(cfg['editor'], 'build_entry.dist'),
                 os.path.join(cfg['builder'], 'build_game.dist',
                              'build_game.exe')))
    print('=' * 64)


if __name__ == '__main__':
    main()
