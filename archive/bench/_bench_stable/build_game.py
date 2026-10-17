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

BIN_DIR = os.path.dirname(os.path.abspath(__file__))
# 注意: Nuitka 输出目录不支持中文路径 (实测 --build-runtime 中文目录名
# 打包 exit 1; 纯 ASCII rt_test 成功) —— 运行库目录用 ASCII.
DEFAULT_RUNTIME_DIR = os.path.join(BIN_DIR, 'player_runtime')
DEFAULT_SCRIPTS_DIR = os.path.join(BIN_DIR, 'scripts')


def _collect_scripts(directory):
    """收集游戏脚本目录里的 .py 源码 (与引擎 load_script_dir 同白名单语义).
    返回 [(name, source)...]."""
    import re
    name_re = re.compile(r'^[A-Za-z0-9_]+\.py$')
    out = []
    if not directory or not os.path.isdir(directory):
        return out
    for fname in sorted(os.listdir(directory)):
        if not name_re.match(fname):
            continue        # 跳过内部文件/非白名单 (与引擎一致)
        with open(os.path.join(directory, fname), 'r', encoding='utf-8') as f:
            out.append((fname, f.read()))
    return out


def _resolve_runtime(runtime_arg):
    """定位玩家运行时: 可以是 dist 目录 (全拷) 或单个 exe (拷夹内全部运研).
    v1 要求 runtime 是'完整 dist 目录'或已预置的 <BIN>玩家运行时 目录."""
    if runtime_arg:
        p = os.path.abspath(runtime_arg)
        if os.path.isdir(p):
            return p
        if os.path.isfile(p):
            return os.path.dirname(p)
        raise SystemExit("--runtime 不存在: %s" % p)
    if os.path.isdir(DEFAULT_RUNTIME_DIR):
        return DEFAULT_RUNTIME_DIR
    raise SystemExit("缺少玩家运行时: 先 --build-runtime 打包, 或 --runtime 指定")


def _build_runtime():
    """Nuitka 打包玩家运行时 (game_player.py -> 玩家运行时/MyGame.exe + 运行库)."""
    cmd = [sys.executable, '-m', 'nuitka', '--standalone', '--msvc=latest',
           '--assume-yes-for-downloads', '--enable-plugin=tk-inter',
           '--windows-disable-console',
           '--output-dir=%s' % DEFAULT_RUNTIME_DIR,
           '--output-filename=MyGame.exe',
           os.path.join(BIN_DIR, 'game_player.py')]
    print("打包玩家运行时:", ' '.join(cmd))
    subprocess.check_call(cmd)
    exe = os.path.join(DEFAULT_RUNTIME_DIR, 'game_player.dist', 'MyGame.exe')
    if not os.path.isfile(exe):
        raise SystemExit("打包意外, 未找到: %s" % exe)
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
