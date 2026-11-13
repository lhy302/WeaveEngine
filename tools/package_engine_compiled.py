# -*- coding: utf-8 -*-
r"""打「编译版」引擎包（2026-11-08 新增）。

与 package_engine.py 的区别：**不含嵌入式 Python、不含 .py 源码**，主程序是 Nuitka 编出的
Loom.exe（编辑器）+ build_game.exe（游戏构建器）。运行时通过 Hub 的 main_exe 字段识别。

包结构（2026-11-13 起构建器改为 onedir）：
    Loom-<version>.zip
      Loom/
        Loom.exe            <- 编辑器（Nuitka standalone 产物，同目录带依赖）
        builder/            <- 构建器（Nuitka onedir，build_game.dist 的**内容**平铺）
          build_game.exe
          *.dll / ckernels/ / core_components/ / shaders/ ...
        player_runtime/game_player.dist/**   <- 预置玩家运行时
        scripts/ GUI/ Projects/ assets/     <- 运行时数据（可编辑，非编译）
        解释器.json / 输入配置.default.json / 设置.json
      Loom.bat
      README.txt

为什么构建器是目录：onefile 会自解压到 %TEMP% 再执行，是安全软件（360）眼里的
"投放器"特征；onedir 不再落 %TEMP%，也不会被误报（2026-11-13 裁决）。

用法:
    python tools/package_engine_compiled.py --version 0.1.0.beta6 \
        --editor-dist C:\loom_build\engine\build_entry.dist \
        --builder-exe C:\loom_build\builder\build_game.dist\build_game.exe

（--builder-exe 仍传 exe 路径；打包时把它的**整个父目录内容**平铺到包内
 Loom/builder/ —— 不出现 builder/build_game.dist/ 双层。）
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
    ap.add_argument('--builder-exe', required=True,
                    help='Nuitka onedir 构建器 exe（...\\build_game.dist\\build_game.exe；'
                         '打包时复制其整个父目录到 Loom/builder/）')
    ap.add_argument('--kind', choices=('compiled', 'source'), default='compiled',
                    help='产物类型（默认 compiled）: Loom-<ver>-compiled.zip，'
                         '与源码包分开避免互相覆盖')
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
    # 2026-11-13: 构建器必须是 onedir —— exe 的父目录就是 <stem>.dist。
    # 传入旧 onefile 的 <out>/build_game.exe 时，父目录是输出根（里面还有
    # .__prev / 中间产物），整目录拷进包会带进垃圾，这里直接拒绝。
    _b_parent = os.path.dirname(os.path.abspath(args.builder_exe))
    _b_stem = os.path.splitext(os.path.basename(args.builder_exe))[0]
    if os.path.basename(_b_parent).lower() != (_b_stem + '.dist').lower():
        _fail('构建器不是 onedir 形态（父目录必须叫 %s.dist）: %s\n'
              '  打包器会整目录复制 --builder-exe 的父目录到包内 Loom/builder/，\n'
              '  传旧 onefile 的 <out>/build_game.exe 会把输出根（含 .__prev 与\n'
              '  中间产物）一起带进包。请先跑:\n'
              '    py -3.13 tools/build_engine.py --mode release --what builder'
              % (_b_stem, args.builder_exe))

    def _show_bi(dist, label):
        """展示 build_info 的来源证据；dirty 工作树要醒目警告（R6-03 扩展）。"""
        try:
            with open(os.path.join(dist, 'build_info.json'), 'r',
                      encoding='utf-8') as _f:
                _bi = json.load(_f)
        except Exception:
            return
        print('[编译包] %s build_info: git_head=%s git_dirty=%s '
              'python=%s nuitka=%s built_at=%s'
              % (label, _bi.get('git_head'), _bi.get('git_dirty'),
                 _bi.get('python'), _bi.get('nuitka'), _bi.get('built_at')))
        if _bi.get('git_dirty'):
            print('[编译包] 警告: %s 来自 dirty 工作树（git_dirty=True），'
                  '产物与提交不可逐位对拍！' % label)

    _show_bi(os.path.dirname(os.path.abspath(args.builder_exe)), '构建器')

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

    _meta_bad = PE.meta_version_problems(args.editor_dist, version)
    if _meta_bad:
        _fail('编辑器 dist 版本元数据不合格: %s' % ('; '.join(_meta_bad),))
    _show_bi(args.editor_dist, '编辑器 dist')

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
        _show_bi(runtime, '运行时 dist')
        _meta_bad = PE.meta_version_problems(runtime, version)
        if _meta_bad:
            _fail('播放器运行时版本元数据不合格: %s'
                  % ('; '.join(_meta_bad),))
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

    # 2026-11-13: 构建器是 onedir —— 把父目录（build_game.dist）的**内容**平铺到
    # Loom/builder/，绝不把单个 exe 拷成 Loom/build_game.exe（那是 onefile 形态，
    # 也是 360 误报的根因），也不留 builder/build_game.dist/ 双层。
    print('[编译包] 复制构建器 onedir 内容 -> Loom/builder/ (%s) ...' % _b_parent)
    _builder_dst = os.path.join(out_loom, 'builder')
    if os.path.isdir(_builder_dst):
        shutil.rmtree(_builder_dst)
    os.makedirs(_builder_dst, exist_ok=True)
    for _b_name in os.listdir(_b_parent):
        _b_src = os.path.join(_b_parent, _b_name)
        _b_dst = os.path.join(_builder_dst, _b_name)
        if os.path.isdir(_b_src):
            shutil.copytree(_b_src, _b_dst, dirs_exist_ok=True)
        else:
            shutil.copy2(_b_src, _b_dst)

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
                '游戏构建器 = builder/build_game.exe；'
                '配置写用户目录 %LOCALAPPDATA%/Loom',
    }
    bad = PE._hub_config().validate_meta(meta, version) if PE._hub_config() else None
    if bad:
        _fail('包内元数据没过 LoomHub 的 validate_meta: %s' % bad)
    try:
        with open(os.path.join(out_loom, '解释器.json'), 'w', encoding='utf-8') as f:
            json.dump(meta, f, ensure_ascii=False, indent=2)
    except OSError as e:
        _fail('写 解释器.json 失败: %r' % (e,))
    # 2026-11-10: 回读校验（版本闸单一事实源）
    try:
        with open(os.path.join(out_loom, '解释器.json'), 'r', encoding='utf-8') as f:
            _m = json.load(f)
        if str(_m.get('version')) != version:
            _fail('包内 解释器.json version=%r != %r'
                  % (_m.get('version'), version))
    except SystemExit:
        raise
    except Exception as e:
        _fail('包内 解释器.json 回读失败: %r' % (e,))

    # 2026-11-11 打包卫生: 清掉运行时状态/日志（smoke 会在 dist 里留 .agent_port.json）
    _removed = PE.purge_forbidden(tmp)
    if _removed:
        print('[编译包] 排除运行时状态/日志 %d 项: %s'
              % (len(_removed), ', '.join(_removed[:5])))

    PE.write_launcher(tmp)
    PE.write_meta_readme(tmp, version, slim=slim, compiled=True)

    zip_path = os.path.join(DIST_DIR, 'Loom-%s-%s.zip' % (version, args.kind))
    print('[编译包] 写 zip: %s' % zip_path)
    with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        for dp, dns, fns in os.walk(tmp):
            dns[:] = [d for d in dns if d not in ('__pycache__',)]
            for fn in fns:
                if fn.endswith(('.pyc', '.pyo', '.tmp', '.log')):
                    continue
                full = os.path.join(dp, fn)
                _rel = os.path.relpath(full, tmp).replace(os.sep, '/')
                if PE.packaging_excluded(_rel):
                    continue
                zf.write(full, _rel)
    # zip 自检: Loom/解释器.json 必须在且版本一致（否则版本闸走常量兜底）
    try:
        with zipfile.ZipFile(zip_path) as _zf:
            _names = set(_zf.namelist())
            _forbidden = [n for n in _names if PE.packaging_excluded(n)]
            if _forbidden:
                _fail('zip 内含运行时状态/日志文件: %s'
                      % ', '.join(sorted(_forbidden)[:5]))
            _m = json.loads(_zf.read('Loom/解释器.json').decode('utf-8'))
        if str(_m.get('version')) != version:
            _fail('zip 内 解释器.json version=%r != %r'
                  % (_m.get('version'), version))
    except SystemExit:
        raise
    except Exception as e:
        _fail('zip 自检失败（Loom/解释器.json 读不回来）: %r' % (e,))
    shutil.rmtree(tmp, ignore_errors=True)

    print('[编译包] 完成: %s (%.2f MB)' % (zip_path, os.path.getsize(zip_path) / 1048576.0))
    print('下一步: 解压到 C:/Program Files/Loom/<版本>/ 后, 用 LoomHub 添加解释器（kind=exe）')


if __name__ == '__main__':
    main()
