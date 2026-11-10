# -*- coding: utf-8 -*-
"""
build_game.py — 游戏构建器 (Unity BuildPipeline 对齐, 2026-08-22)

把"开发期材料"变成"玩家发布夹" (Unity Build 语义):
  输入:  场景.json (明文, 开发者文件) + 游戏脚本目录 (*.py) + 玩家运行时 exe
  输出:  发布夹 = 玩家运行时(MyGame.exe) + 游戏包.lsc (场景+脚本+配置, LOOMSC1
         混淆打包) — 与 exe 同夹不可分离; 目录里无任何明文脚本/场景.

用法 (可作 CI 步骤, 对齐 BuildPipeline.BuildPlayer):
  py build_game.py --name 游戏名 [--company 公司] [--version 1.0] \
      [--title 窗口标题] [--scene 场景.json] [--game-scripts 脚本目录] \
      [--output 发布夹] [--runtime 玩家运行时exe 或 dist 目录]
  py build_game.py --build-runtime    # 首次/引擎更新: Nuitka 打包玩家运行时

约定:
  - 游戏脚本目录默认 = 本文件所在目录/scripts (开发者把游戏脚本 .py 放那,
    编辑器 exe 启动时会自动加载注册 (engine load_script_dir), 可挂到物体).
  - 玩家运行时默认 = 本文件所在目录/玩家运行时 (MyGame.exe + dll 运行库,
    由 --build-runtime 生成).
  - externals (obj/音频等素材): 随夹拷贝约定 —— 场景引用相对文件路径时,
    把素材放"与游戏包同目录"并整夹分发 (v1 不自动收集, 文档写明).
"""
import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys

import game_pack
import plugin_loader
import sceneio

try:
    import loom_assets
except Exception:                     # 极旧引擎目录（无资产层）: 退化为"不拷资产"
    loom_assets = None

def project_assets_dir(scene_path):
    """场景 -> 项目 Assets 目录（beta6 B1）。找不到项目索引返回 None。"""
    if loom_assets is None or not scene_path:
        return None
    root = loom_assets.find_project_root(os.path.dirname(os.path.abspath(scene_path)))
    if not root:
        return None
    d = loom_assets.assets_dir(root)
    return d if os.path.isdir(d) else None


def _count_files(d):
    n = 0
    for _root, _dirs, files in os.walk(d):
        n += len(files)
    return n


def copy_project_assets(scene_path, out_dir):
    """把项目 Assets/ 拷进发布夹（返回 True=有资产可拷）。

    beta6 B1 P0 修复: 旧构建只把**场景 dict** 打进 .lsc，贴图/六面图一个都不带，
    玩家侧必然"贴图全丢"。Assets/ 与 游戏包.lsc 同夹，运行时以发布夹为 base_dir
    解析（game_player → PlayerApp(assets_base=发布夹)）。
    """
    src = project_assets_dir(scene_path)
    if not src:
        return False
    dst = os.path.join(out_dir, 'Assets')
    shutil.copytree(src, dst, dirs_exist_ok=True)
    return True


def _bin_dir():
    """引擎"数据根目录"（scripts/ player_runtime/ core_components/ ckernels/ 所在处）。

    2026-11-08 (编译版支持): Nuitka **onefile** 下 `__file__` 指向临时解包目录，
    那里没有随引擎分发的数据目录 —— 直接用它会导致:
      · "[2/5] 游戏脚本: 0 个"（找不到 scripts/）
      · "缺少玩家运行时 (需要含 MyGame.exe 的 game_player.dist)"
    所以优先用**程序目录**(sys.argv[0] 的目录)，只有它没有数据目录时才回退 `__file__`。
    源码运行 (`python build_game.py`) 时 argv[0] 就是本文件 → 两者相同，行为不变。
    """
    exe_dir = os.path.dirname(os.path.abspath(sys.argv[0] or '')) if sys.argv else ''
    here = os.path.dirname(os.path.abspath(__file__))
    for cand in (exe_dir, here):
        if cand and (os.path.isdir(os.path.join(cand, 'player_runtime'))
                     or os.path.isdir(os.path.join(cand, 'scripts'))):
            return cand
    return here


BIN_DIR = _bin_dir()
# 注意: Nuitka 输出目录不支持中文路径 (实测 --build-runtime 中文目录名
# 打包 exit 1; 纯 ASCII rt_test 成功) —— 运行库目录用 ASCII.
DEFAULT_RUNTIME_DIR = os.path.join(BIN_DIR, 'player_runtime')
DEFAULT_SCRIPTS_DIR = os.path.join(BIN_DIR, 'scripts')


def _collect_scripts(directory):
    """收集游戏脚本目录里的 .py 源码 (与引擎 load_script_dir 同白名单语义).
    返回 [(name, source)...]."""
    import re
    name_re = re.compile(r'^[A-Za-z0-9_]+\.(py|lua)$')
    out = []
    if not directory or not os.path.isdir(directory):
        return out
    for fname in sorted(os.listdir(directory)):
        if not name_re.match(fname):
            continue        # 跳过内部文件/非白名单 (与引擎一致)
        with open(os.path.join(directory, fname), 'r', encoding='utf-8') as f:
            out.append((fname, f.read()))
    return out


# 2026-11-08 P-05-10/11: 两条入口（默认 player_runtime / 显式 --runtime）
# 共用一个归一化函数，消除"同一份磁盘布局，默认分支平铺、--runtime 分支多套一层"
# 的语义分裂；同时把"目录在但没有可用 dist"和"目录不存在"合并成同一条失败。
_RUNTIME_HINT = (
    "缺少玩家运行时 (需要含 MyGame.exe 的 game_player.dist)。\n"
    "  · 正式引擎包已预置该运行时, 无需编译器;\n"
    "  · 源码工作区首次使用: 在**引擎开发机**跑 --build-runtime \n"
    "    (需要 Nuitka + MSVC), 或用 --runtime 指定已有 dist 目录。")


def _runtime_dist(dir_path):
    """从一个候选目录里找"可用运行时 dist"（含 MyGame.exe）；找不到返回 None。

    接受两种历史布局：
      · <dir>/game_player.dist/MyGame.exe   (Nuitka --standalone 产物, 现行布局)
      · <dir>/MyGame.exe                    (更早的直接铺开布局)
    """
    if not dir_path or not os.path.isdir(dir_path):
        return None
    if os.path.isfile(os.path.join(dir_path, 'MyGame.exe')):
        return dir_path
    sub = os.path.join(dir_path, 'game_player.dist')
    if os.path.isfile(os.path.join(sub, 'MyGame.exe')):
        return sub
    return None


def _resolve_runtime(runtime_arg):
    """定位玩家运行时: dist 目录 (全拷) / 单个 exe (取其所在目录) / 默认预置目录.

    返回 **可平铺进发布夹** 的 dist 目录（保证 MyGame.exe 直接位于返回值下），
    找不到就给出明确错误（绝不静默返回一个没有 exe 的目录）。"""
    if runtime_arg:
        p = os.path.abspath(runtime_arg)
        if os.path.isfile(p):
            p = os.path.dirname(p)
        if not os.path.isdir(p):
            raise SystemExit("--runtime 不存在: %s" % p)
        dist = _runtime_dist(p)
        if dist is None:
            raise SystemExit(
                "--runtime 指定的目录里没有可用的玩家运行时: %s\n"
                "  期望: <该目录>/MyGame.exe 或 <该目录>/game_player.dist/MyGame.exe\n"
                "  (给 .dist 目录、给 player_runtime 目录、或直接给 MyGame.exe 都可以)"
                % p)
        if dist != p:
            print("[4/5] --runtime 归一化: %s -> %s" % (p, dist))
        return dist
    dist = _runtime_dist(DEFAULT_RUNTIME_DIR)
    if dist is None:
        # 目录不存在 / 目录在但只有 .build 残留 —— 同一条失败，避免静默选错层
        raise SystemExit(_RUNTIME_HINT)
    return dist


def _build_runtime():
    r"""Nuitka 打包玩家运行时 (game_player.py -> 玩家运行时/MyGame.exe + 运行库).

    2026-11-09 两档构建: 环境变量覆盖（由 tools/build_engine.py 设置）——
      LOOM_BUILD_CONSOLE_MODE : force(dev, 带控制台) | disable(release)
      LOOM_BUILD_RUNTIME_DIR  : 产物根目录（dev 进 C:\loom_build\runtime_dev）
    """
    console_mode = os.environ.get('LOOM_BUILD_CONSOLE_MODE', 'disable')
    out_root = os.environ.get('LOOM_BUILD_RUNTIME_DIR') or DEFAULT_RUNTIME_DIR
    cmd = [sys.executable, '-m', 'nuitka', '--mode=standalone', '--msvc=latest',
           '--assume-yes-for-downloads', '--enable-plugin=tk-inter',
           # 2026-11-07: wgpu(Vulkan) 需要 resources/combined_header.h 等数据文件，
           # 旧构建没带 -> 打包版 Vulkan 初始化失败 (Could not find combined_header.h)。
           # 2026-11-09 工具链升级 (Nuitka 4.3.5): wgpu_native 不是 dist 包，
           # 4.x 会对它报 "Failed to locate package directory"，已移除（数据在 wgpu 里）。
           '--include-package-data=wgpu',
           # Nuitka 2.7 起 --windows-disable-console 已弃用，4.x 将删
           '--windows-console-mode=%s' % console_mode,
           '--output-dir=%s' % out_root,
           '--output-filename=MyGame.exe',
           os.path.join(BIN_DIR, 'game_player.py')]
    # 2026-11-07: wgpu-native 的 DLL 不是 package-data, 必须显式带进 dist,
    # 否则打包版 Vulkan 报 'Could not find WGPU library libwpgu_native'。
    try:
        import wgpu as _wgpu
        _dll = os.path.join(os.path.dirname(_wgpu.__file__), 'resources',
                            'wgpu_native-release.dll')
        if os.path.isfile(_dll):
            cmd.append('--include-data-files=%s=wgpu/resources/wgpu_native-release.dll' % _dll)
            print('包含 wgpu-native DLL:', _dll)
    except Exception as _e:
        print('警告: 未包含 wgpu-native DLL (%r)' % (_e,))
    # 2026-11-09 产物自洽: 原生组件目录随 dist 分发, 裸 dist 也能跑
    # (游戏发布时 build_game 仍会再拷一份到发布根, 幂等)。
    for _d in ('ckernels', 'core_components'):
        _p = os.path.join(BIN_DIR, _d)
        if os.path.isdir(_p):
            cmd.append('--include-data-dir=%s=%s' % (_p, _d))
    print("打包玩家运行时:", ' '.join(cmd))
    subprocess.check_call(cmd)
    # Nuitka 4.x --include-data-dir 会跳过 *.dll, 构建后补拷原生目录, 保证裸 dist 自洽
    for _d in ('ckernels', 'core_components'):
        _src = os.path.join(BIN_DIR, _d)
        if os.path.isdir(_src):
            _dst = os.path.join(out_root, 'game_player.dist', _d)
            shutil.copytree(_src, _dst, dirs_exist_ok=True)
    # 2026-11-10: 引擎版本单一事实源（sceneio 版本闸）随 dist 分发
    _meta_src = os.path.join(BIN_DIR, '解释器.json')
    if os.path.isfile(_meta_src):
        shutil.copy2(_meta_src, os.path.join(out_root, 'game_player.dist', '解释器.json'))
    exe = os.path.join(out_root, 'game_player.dist', 'MyGame.exe')
    if not os.path.isfile(exe):
        raise SystemExit("打包意外, 未找到: %s" % exe)
    for _need in ('ckernels\\loom_kernels.dll', 'core_components', '解释器.json'):
        if not os.path.exists(os.path.join(out_root, 'game_player.dist', _need)):
            raise SystemExit("打包产物不自洽, 缺 %s（ckernels/core_components 未随 dist）"
                             % _need)
    print("玩家运行时已生成:", exe)


def main():
    ap = argparse.ArgumentParser(description='Loom 游戏构建器')
    ap.add_argument('--name', default='我的游戏', help='游戏名 (Unity 产品名)')
    ap.add_argument('--company', default='', help='公司名 (Player Settings)')
    ap.add_argument('--version', default='1.0', help='游戏版本')
    ap.add_argument('--title', default=None, help='窗口标题 (默认=游戏名)')
    ap.add_argument('--scene', default=None, help='启动场景 .json (明文)')
    ap.add_argument('--game-scripts', default=None,
                    help='游戏脚本目录 (默认: 本文件旁 scripts/)')
    ap.add_argument('--output', default=None, help='发布夹 (不存在或 --force)')
    ap.add_argument('--runtime', default=None, help='玩家运行时 dist 目录/exe')
    ap.add_argument('--force', action='store_true', help='输出夹已存在时允许覆盖')
    ap.add_argument('--build-runtime', action='store_true',
                    help='先 Nuitka 打包玩家运行时, 再构建')
    # 2026-08-27 游戏安全策略: secure=插件加密+哈希互验 (竞技防作弊);
    # open=插件明文+允许非原版插件 (单机 MOD 自由)
    ap.add_argument('--protection', choices=('secure', 'open'),
                    default='secure',
                    help='安全模式: secure(默认, 插件包.lpc 加密+哈希防修改) '
                         '| open(插件明文+允许 MOD, 见 --no-encrypt-content)')
    ap.add_argument('--no-encrypt-content', action='store_true',
                    help='仅 open 模式: 场景/脚本也不混淆 (纯 MOD 友好, 修改器可用)')
    args = ap.parse_args()

    if args.no_encrypt_content and args.protection != 'open':
        print("[警告] --no-encrypt-content 仅在 --protection open 下生效, 已忽略"
              " (secure 模式强制加密)")
        args.no_encrypt_content = False

    if args.build_runtime:
        _build_runtime()
        # 2026-11-09: 只给了 --build-runtime 时, 构建完运行时即结束。
        # 旧行为会继续走游戏打包 (缺 场景.json -> exit 1), 让
        # tools/build_engine.py 误判"运行时构建失败"。
        if args.output is None and args.scene is None and args.game_scripts is None:
            print("[build_game] 仅构建运行时完成（未指定 --output/--scene，跳过游戏打包）")
            return

    # 1) 场景 (明文开发者文件 -> 读入内存)
    scene_json = args.scene or os.path.join(BIN_DIR, '场景.json')
    data = sceneio.load_scene_data(scene_json)
    if not isinstance(data, dict):
        raise SystemExit("场景读取失败: %s" % scene_json)
    print("[1/5] 场景已读入:", scene_json)

    # 2) 游戏脚本源码 (内存收集, 只进包不出明文)
    scripts = _collect_scripts(args.game_scripts or DEFAULT_SCRIPTS_DIR)
    print("[2/5] 游戏脚本: %d 个 -> 加密打包" % len(scripts),
          [n for n, _ in scripts])

    # 3) 播放器层插件收集 (只带 layer=player: plugins/player 普通 +
    #    core_plugins 中声明 player 的核心插件; editor 层工具不携带)
    player_plugins = plugin_loader.scan_player_plugins(base=BIN_DIR)
    print("[3/5] 播放器层插件: %d 个 -> %s" % (
        len(player_plugins), '加密打包 (secure)' if args.protection == 'secure'
        else '明文复制 (open, 允许 MOD)'))
    for p in player_plugins:
        print("      - %s (%s%s)" % (
            p['id'], '核心' if p['kind'] == 'core' else '标准', p['info'].get('name', '')))

    # 4) 定位玩家运行时
    runtime_dir = _resolve_runtime(args.runtime)
    print("[4/5] 玩家运行时:", runtime_dir)

    # 5) 组装发布夹
    out = os.path.abspath(args.output or os.path.join(BIN_DIR, '发布', args.name))
    if os.path.isdir(out) and not args.force:
        raise SystemExit("发布夹已存在 (用 --force 覆盖): %s" % out)
    if os.path.isdir(out):
        shutil.rmtree(out)
    os.makedirs(out, exist_ok=True)
    for fname in os.listdir(runtime_dir):
        s = os.path.join(runtime_dir, fname)
        d = os.path.join(out, fname)
        if os.path.isdir(s):
            shutil.copytree(s, d, dirs_exist_ok=True)
        else:
            shutil.copy2(s, d)
    # M4 AUDIT-46: 随同发布独立 Player 核心组件 DLL (pipeline, script, ckernels, registry)
    for sub in ('core_components', 'ckernels'):
        s_dir = os.path.join(BIN_DIR, sub)
        d_dir = os.path.join(out, sub)
        if os.path.isdir(s_dir):
            shutil.copytree(s_dir, d_dir, dirs_exist_ok=True)

    config = {'name': args.name, 'company': args.company,
              'version': args.version,
              'title': args.title or args.name}
    if player_plugins and args.protection == 'secure':
        # 插件全量收集 (entry 源码 + 目录文件) -> 插件包.lpc 加密 -> 哈希写 .lsc
        items = []
        for p in player_plugins:
            d = p['path']
            entry_name = p['info']['entry']
            with open(os.path.join(d, entry_name), 'r', encoding='utf-8') as f:
                entry_src = f.read()
            files = {}
            for root, _, fnames in os.walk(d):
                for fn in fnames:
                    sf = os.path.join(root, fn)
                    if sf == os.path.join(d, entry_name):
                        continue   # entry 源码单列进 'entry', 不进 files
                    rel = os.path.relpath(sf, d).replace('\\', '/')
                    with open(sf, 'rb') as fh:
                        files[rel] = fh.read()
            items.append({'id': p['id'], 'name': p['info'].get('name', p['id']),
                          'version': p['info']['version'],
                          'layer': p['layer'], 'kind': p['kind'],
                          'entry': entry_src, 'files': files})
        game_pack.pack_plugins(out, items)
        with open(game_pack.plugins_path(out), 'rb') as f:
            config['plugins_sha256'] = hashlib.sha256(f.read()).hexdigest()
    elif player_plugins:
        # open: 插件目录明文复制到发布夹 plugins/player/ (可被玩家修改/替换)
        for p in player_plugins:
            src = p['path']
            dst = os.path.join(out, 'plugins', 'player',
                               os.path.basename(src.rstrip('/\\')))
            shutil.copytree(src, dst, dirs_exist_ok=True)
        config['plugins_sha256'] = ''   # open 模式: 无防修改校验

    # beta6 B1: 项目资产随包（Assets/ 与 游戏包.lsc 同夹；缺它 = 贴图/六面图全丢）
    _has_assets = copy_project_assets(scene_json, out)
    config['assets'] = bool(_has_assets)
    if _has_assets:
        print("  资产: Assets/ 已随包 (%d 个文件)"
              % _count_files(os.path.join(out, 'Assets')))
    else:
        print("  资产: 场景无项目资产库 (Assets/assets.json) -> 不携带资产")

    game_pack.pack(out, config, data, scripts,
                   encrypt=not args.no_encrypt_content)
    print("[5/5] 构建完成:", out)
    if args.protection == 'secure':
        print("  插件: 插件包.lpc (%d 个, 加密+哈希防修改) -> 与 exe/游戏包 同夹互验"
              % len(player_plugins))
    else:
        print("  插件: plugins/player/ (%d 个明文, 玩家可 MOD/替换) | 场景脚本: %s"
              % (len(player_plugins), '混淆' if not args.no_encrypt_content
                 else '明文 (--no-encrypt-content)'))
    print("  MyGame.exe + 游戏包.lsc (场景/脚本/配置%s, 无明文)" % (
        '已混淆打包' if not args.no_encrypt_content else '明文'))
    print("  玩家: 双击 exe 即玩 (缺 游戏包.lsc = _Data 缺失, 不可分离)")


if __name__ == '__main__':
    main()
