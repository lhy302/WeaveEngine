# -*- coding: utf-8 -*-
r"""打「编译版」引擎包（2026-11-08 新增）。

与 package_engine.py 的区别：**不含嵌入式 Python、不含 .py 源码**，主程序是 Nuitka 编出的
Loom.exe（编辑器）+ build_game.exe（游戏构建器）。运行时通过 Hub 的 main_exe 字段识别。

包结构：
    Loom-<version>.zip
      Loom/
        Loom.exe            <- 编辑器（Nuitka standalone 产物，同目录带依赖）
        build_game.exe      <- 构建器（Nuitka onefile）
        player_runtime/game_player.dist/**   <- 预置玩家运行时
        scripts/ GUI/ Projects/ assets/     <- 运行时数据（可编辑，非编译）
        解释器.json / 输入配置.default.json / 设置.json
      Loom.bat
      README.txt

用法:
    python tools/package_engine_compiled.py --version 0.1.0.beta4 \
        --editor-dist C:\loom_build\engine\build_entry.dist \
        --builder-exe C:\loom_build\builder\build_game.exe
"""
import json
import os
import shutil
import sys
import time
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
if HERE not in sys.path:
    sys.path.insert(0, HERE)
import package_engine as PE          # 复用版本白名单/运行时校验/元数据

ENGINE_DIR = PE.ENGINE_DIR
DIST_DIR = PE.DIST_DIR

# 注意: ckernels / core_components 是**原生组件目录**（loom_kernels.dll、module_ref.dll、
# registry.json、official_manifest 哈希表），由 ctypes/自检在**程序目录**下按路径加载，
# 不编进 exe。实测漏带时 fastpath 直接 raise：loom_kernels.dll 未找到（B1 退役后是硬加载）。
DATA_DIRS = ['scripts', 'GUI', 'assets', 'ckernels', 'core_components',
             'core_plugins', 'plugins']
# Projects/ 不整目录拷: 仓库里那堆 压测500混合/压测500球/_m3_* 是**开发压测资产**，
# 不该进发布包（2026-11-09 实测发布包里带了 7 个开发场景）。只放 examples/ 的样例。
SAMPLE_DIR = os.path.join(os.path.dirname(HERE), 'examples')
DATA_FILES = ['输入配置.default.json', '设置.json']


def _fail(msg):
    print('[编译包] 错误: ' + msg)
    sys.exit(1)


def _dir_size(p):
    return sum(os.path.getsize(os.path.join(dp, f))
               for dp, _, fs in os.walk(p) for f in fs)


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument('--version', help='覆盖版本号（默认读 Loom/解释器.json）')
    ap.add_argument('--editor-dist', required=True, help='Nuitka 编辑器 dist 目录（内含 Loom.exe）')
    ap.add_argument('--builder-exe', required=True, help='Nuitka onefile 构建器 exe')
    ap.add_argument('--allow-missing-runtime', action='store_true')
    args = ap.parse_args()

    version = PE.load_version(args.version)
    PE.check_version(version)
    print('=' * 60)
    print('Loom 引擎**编译版**打包 — 版本 %s' % version)
    print('=' * 60)

    if not os.path.isfile(os.path.join(args.editor_dist, 'Loom.exe')):
        _fail('--editor-dist 里没有 Loom.exe: %s' % args.editor_dist)
    if not os.path.isfile(args.builder_exe):
        _fail('--builder-exe 不存在: %s' % args.builder_exe)

    # 2026-11-09 工具链升级: 编辑器 dist 必须带 PySide6 + Qt 平台插件。
    # 漏 --enable-plugin=pyside6 时 dist 体积反而小 ~8MB（体积检查会误判成变好），
    # 所以这里用"路径存在"作硬判据，缺一个就拒绝打包。
    _bad = PE.editor_dist_problems(args.editor_dist)
    if _bad:
        _fail('编辑器 dist 缺 Qt 依赖: %s\n'
              '  Nuitka 构建必须显式带 --enable-plugin=pyside6（漏了 Loom.exe 启动即崩）\n'
              '  dist: %s' % (', '.join(_bad), args.editor_dist))

    _mode_bad = PE.build_info_problems(os.path.dirname(os.path.abspath(args.builder_exe)))
    if _mode_bad:
        _fail('构建器产物档位不合格: %s\n  exe: %s'
              % ('; '.join(_mode_bad), args.builder_exe))

    _mode_bad = PE.build_info_problems(args.editor_dist)
    if _mode_bad:
        _fail('编辑器 dist 档位不合格: %s\n  dist: %s'
              % ('; '.join(_mode_bad), args.editor_dist))

    _bloat = PE.editor_dist_bloat(args.editor_dist)
    if _bloat:
        _fail('编辑器 dist 含可选重包: %s\n'
              '  构建必须加 --nofollow-import-to=cupy（3.13 环境有 cupy-cuda12x，'
              '漏了 dist 多 ~123MB）\n  dist: %s' % (', '.join(_bloat), args.editor_dist))

    runtime = PE._runtime_dist(os.path.join(ENGINE_DIR, 'player_runtime'))
    if runtime is None and not args.allow_missing_runtime:
        _fail('缺预置播放器运行时（player_runtime/game_player.dist）；'
              '显式传 --allow-missing-runtime 才允许出不带运行时的精简探针包')
    slim = runtime is None
    if runtime is not None:
        _mode_bad = PE.build_info_problems(runtime)
        if _mode_bad:
            _fail('播放器运行时档位不合格: %s\n  dist: %s'
                  % ('; '.join(_mode_bad), runtime))
        _bad = PE.runtime_layout_problems(runtime)
        if _bad:
            _fail('播放器运行时布局不符: %s\n  dist: %s'
                  % ('; '.join(_bad), runtime))

    tmp = os.path.join(DIST_DIR, '_compiled_tmp_%s' % version)
    if os.path.isdir(tmp):
        shutil.rmtree(tmp, ignore_errors=True)
    out_loom = os.path.join(tmp, 'Loom')
    os.makedirs(out_loom, exist_ok=True)

    print('[编译包] 复制编辑器 dist ...')
    for name in os.listdir(args.editor_dist):
        s = os.path.join(args.editor_dist, name)
        d = os.path.join(out_loom, name)
        if os.path.isdir(s):
            shutil.copytree(s, d, dirs_exist_ok=True)
        else:
            shutil.copy2(s, d)

    print('[编译包] 复制构建器 ...')
    shutil.copy2(args.builder_exe, os.path.join(out_loom, 'build_game.exe'))

    if runtime:
        print('[编译包] 预置播放器运行时: %.1f MB' % (_dir_size(runtime) / 1048576.0))
        shutil.copytree(runtime, os.path.join(out_loom, 'player_runtime', 'game_player.dist'),
                        dirs_exist_ok=True)
        try:
            with open(os.path.join(out_loom, 'player_runtime', '运行时.json'), 'w', encoding='utf-8') as f:
                json.dump({'version': version, 'build_mode': 'compiled',
                           'built_at': time.strftime('%Y-%m-%d %H:%M:%S')}, f,
                          ensure_ascii=False, indent=1)
        except OSError as e:
            _fail('写 运行时.json 失败: %r' % (e,))

    print('[编译包] 复制运行时数据（脚本/GUI/Projects/assets/配置模板）...')
    for d in DATA_DIRS:
        s = os.path.join(ENGINE_DIR, d)
        if os.path.isdir(s):
            shutil.copytree(s, os.path.join(out_loom, d), dirs_exist_ok=True)
    for f in DATA_FILES:
        s = os.path.join(ENGINE_DIR, f)
        if os.path.isfile(s):
            shutil.copy2(s, os.path.join(out_loom, f))

    # 只放 examples/ 的样例场景（开发压测场景不随发布包分发）
    if os.path.isdir(SAMPLE_DIR):
        proj = os.path.join(out_loom, 'Projects')
        os.makedirs(proj, exist_ok=True)
        for fn in sorted(os.listdir(SAMPLE_DIR)):
            if fn.lower().endswith('.json'):
                shutil.copy2(os.path.join(SAMPLE_DIR, fn), os.path.join(proj, fn))

    meta = {
        'name': 'Loom',
        'version': version,
        'main': '',                  # 编译版没有 .py 主程序
        'main_exe': 'Loom.exe',
        'build_mode': 'compiled',
        'python_version': '%d.%d.%d' % sys.version_info[:3],
        'note': 'Nuitka 编译版引擎（无嵌入式 Python、无 .py 源码）；'
                '游戏构建器 = 同目录 build_game.exe；配置写用户目录 %LOCALAPPDATA%/Loom',
    }
    bad = PE._hub_config().validate_meta(meta, version) if PE._hub_config() else None
    if bad:
        _fail('包内元数据没过 LoomHub 的 validate_meta: %s' % bad)
    try:
        with open(os.path.join(out_loom, '解释器.json'), 'w', encoding='utf-8') as f:
            json.dump(meta, f, ensure_ascii=False, indent=2)
    except OSError as e:
        _fail('写 解释器.json 失败: %r' % (e,))

    PE.write_launcher(tmp)
    PE.write_meta_readme(tmp, version, slim=slim, compiled=True)

    zip_path = os.path.join(DIST_DIR, 'Loom-%s.zip' % version)
    print('[编译包] 写 zip: %s' % zip_path)
    with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        for dp, dns, fns in os.walk(tmp):
            dns[:] = [d for d in dns if d not in ('__pycache__',)]
            for fn in fns:
                if fn.endswith(('.pyc', '.pyo', '.tmp', '.log')):
                    continue
                full = os.path.join(dp, fn)
                zf.write(full, os.path.relpath(full, tmp).replace(os.sep, '/'))
    shutil.rmtree(tmp, ignore_errors=True)

    print('[编译包] 完成: %s (%.2f MB)' % (zip_path, os.path.getsize(zip_path) / 1048576.0))
    print('下一步: 解压到 C:/Program Files/Loom/<版本>/ 后, 用 LoomHub 添加解释器（kind=exe）')


if __name__ == '__main__':
    main()
