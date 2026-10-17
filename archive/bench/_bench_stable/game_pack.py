# -*- coding: utf-8 -*-
"""
game_pack.py — 游戏资源包 (2026-08-22 发布链路: Unity Build 对齐)

Unity Build 产出的 ""_Data 文件夹" 里装着场景/资源/编译后代码 (Assembly-CSharp),
玩家拿不到源码。Loom 对齐: 发布夹 = MyGame.exe(玩家运行时, 无编辑器) +
游戏包.lsc(场景+游戏脚本源码+配置, LOOMSC1 混淆打包), 两者同夹不可分离
(缺包 = _Data 缺失, 启动报错)。

包格式 (fmt: 'loom-pack-1'):
  {
    'fmt': 'loom-pack-1',
    'config': {'name','company','version','title'},     (title = 窗口标题)
    'scene': 场景 dict (sceneio.scene_to_dict 产物),
    'scripts': [{'name': 文件名, 'source': 源码}],        (游戏脚本目录收集, 混淆存储)
    'externals': [文件名清单]                             (随夹拷贝的素材名, v1 留位)
  }

构建器 (build_game.py) 负责打包; 玩家运行时 (game_player.py) 负责解包:
先 register_sources(脚本) -> 再加载场景 (顺序关键: 未注册脚本被引擎静默跳过)。
"""
import base64
import json
import os
import sys

import sceneio as S

PACK_NAME = '游戏包.lsc'
PACK_PLUGIN_NAME = '插件包.lpc'
FMT = 'loom-pack-1'
PLUGIN_FMT = 'loom-plugins-1'


def program_dir():
    """程序目录解析: 源码 = 本文件所在目录; 打包版 = exe 目录 (同 guiloader)."""
    return os.path.dirname(os.path.abspath(sys.argv[0]))


def pack_path(directory):
    """某目录下的游戏包路径."""
    return os.path.join(directory, PACK_NAME)


def plugins_path(directory):
    """某目录下的插件包路径."""
    return os.path.join(directory, PACK_PLUGIN_NAME)


def load(pack_dir):
    """读取并校验游戏包; 缺失/损坏/格式不符返回 None."""
    data = S.load_scene_data(pack_path(pack_dir))
    if not isinstance(data, dict) or data.get('fmt') != FMT:
        return None
    return data


def pack(output_dir, config, scene_dict, scripts, externals=None,
         encrypt=True):
    """构建游戏包 .lsc (构建器调用). scripts = [(name, source)...].
    encrypt=False = --no-encrypt-content (MOD 路线, 场景/脚本明文;
    仅 --protection open 下用). 返回 .lsc 路径."""
    data = {'fmt': FMT,
            'config': dict(config),
            'scene': scene_dict,
            'scripts': [{'name': n, 'source': s} for n, s in scripts],
            'externals': list(externals or [])}
    S.save_scene_data(pack_path(output_dir), data, encrypt=encrypt)
    return pack_path(output_dir)


def pack_plugins(output_dir, items):
    """构建插件包 .lpc (secure 模式): LOOMSC1 混淆加密.
    items = [{'id','name','version','layer','kind','entry','files'}];
    files = {相对路径: bytes} (插件目录全文件, 打包时转 base64 存 JSON).
    返回 .lpc 路径."""
    data = {'fmt': PLUGIN_FMT, 'plugins': items}
    for it in data['plugins']:
        it['files'] = {k: base64.b64encode(v).decode('ascii')
                       for k, v in (it.get('files') or {}).items()}
    S.save_scene_data(plugins_path(output_dir), data, encrypt=True)
    return plugins_path(output_dir)


def load_plugins_pack(pack_dir):
    """读插件包 .lpc; 缺失/损坏/格式不符返回 None."""
    data = S.load_scene_data(plugins_path(pack_dir))
    if not isinstance(data, dict) or data.get('fmt') != PLUGIN_FMT:
        return None
    return data


def _sha256_file(path):
    import hashlib
    with open(path, 'rb') as f:
        return hashlib.sha256(f.read()).hexdigest()


def install_game_plugins(pack_dir, gm):
    """玩家端插件装载 (game_player / Loom.py 双启共用, 2026-08-27):
      secure (gm 带 config.plugins_sha256): 校验 .lpc 实体哈希与 .
        lsc 记录一致 -> 解密 -> 逐插件 load_plugin_from_pack 内存注册
        (不落盘). 缺/被改 -> SystemExit 报错 (缺包/防修改语义).
      MOD (无 plugins_sha256 记录 / gm=None): set_mode('player') +
        load_plugins(base=发布夹) —— 允许玩家往发布夹 plugins/player/ 放
        非原版插件 (open 模式随夹分发). 不校验.
    返回注册插件个数."""
    import plugin_loader
    plugin_loader.set_mode('player')          # 玩家进程: 全权加载
    expect = (gm or {}).get('config', {}).get('plugins_sha256')
    if expect:
        lpc = plugins_path(pack_dir)
        if not os.path.isfile(lpc):
            raise SystemExit(
                "插件包缺失: 请把 %s 放到 exe 同目录 (与 游戏包.lsc 同夹不可分离)"
                % PACK_PLUGIN_NAME)
        if _sha256_file(lpc) != expect:
            raise SystemExit(
                "插件包被修改或校验失败: 请重新构建游戏 (防修改校验拦截)")
        data = load_plugins_pack(pack_dir)
        n = 0
        for item in data.get('plugins', []):
            src = item.get('entry')
            if not src:
                continue
            plugin_loader.load_plugin_from_pack(item['id'], src,
                                                item.get('files') or {},
                                                item, item.get('layer', 'player'))
            n += 1
        return n
    # MOD / 双启: 目录投放式 (发布夹 plugins/player/...)
    try:
        r = plugin_loader.load_plugins(base=pack_dir)
    except Exception as e:
        print('[插件] MOD 插件装载跳过: %r' % e)
        return 0
    return len(r['loaded'])
