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

用法（必须用 3.13）：
  py -3.13 tools/build_engine.py --mode dev
  py -3.13 tools/build_engine.py --mode release
  py -3.13 tools/build_engine.py --mode dev --what editor,builder
  py -3.13 tools/build_engine.py --mode release --skip-vcvars   # 已自行进过 vcvars 时
"""
import argparse
import json
import os
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
DATA_DIRS = ('ckernels', 'core_components', 'core_plugins', 'plugins',
             'scripts', 'GUI', 'assets')
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
           '--nofollow-import-to=cupy'] + _data_includes() + [
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
    _write_info(os.path.join(dist, 'build_info.json'), info)
    _write_info(os.path.join(out, 'build_info.json'), info)
    return {'path': exe, 'size_mb': _dir_mb(dist), 'seconds': round(secs, 1)}


def build_builder(mode, cfg, info):
    out = cfg['builder']
    exe = os.path.join(out, 'build_game.exe')
    if os.path.isfile(exe):
        prev = exe + '.__prev'
        if os.path.isfile(prev):
            os.remove(prev)
        os.rename(exe, prev)
    cmd = [sys.executable, '-m', 'nuitka', '--mode=onefile', '--msvc=latest',
           '--assume-yes-for-downloads',
           '--windows-console-mode=%s' % cfg['console'],
           '--output-dir=%s' % out, '--output-filename=build_game.exe',
           os.path.join(LOOM, 'build_game.py')]
    secs = _run(cmd, cwd=LOOM)
    if not os.path.isfile(exe):
        _fail('构建器产物缺失: %s' % exe)
    _write_info(os.path.join(out, 'build_info.json'), info)
    return {'path': exe, 'size_mb': round(os.path.getsize(exe) / 1048576.0, 2),
            'seconds': round(secs, 1)}


def build_runtime(mode, cfg, info):
    out = cfg['runtime']
    dist = os.path.join(out, 'game_player.dist')
    _stash_prev(dist)
    env = dict(os.environ)
    env['LOOM_BUILD_CONSOLE_MODE'] = cfg['console']
    env['LOOM_BUILD_RUNTIME_DIR'] = out
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

    info = {
        'mode': args.mode,
        'console_mode': cfg['console'],
        'packageable': cfg['packageable'],
        'python': sys.version.split()[0],
        'nuitka': _nuitka_version(),
        'built_at': time.strftime('%Y-%m-%d %H:%M:%S'),
    }
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
        print('  %-8s %8.1f MB  %6.0fs  %s' % (k, v['size_mb'], v['seconds'], v['path']))
    if args.mode == 'release':
        print('[build_engine] 现在可打包: py -3.13 tools/package_engine_compiled.py '
              '--version <版本> --editor-dist %s --builder-exe %s'
              % (os.path.join(cfg['editor'], 'build_entry.dist'),
                 os.path.join(cfg['builder'], 'build_game.exe')))
    print('=' * 64)


if __name__ == '__main__':
    main()
