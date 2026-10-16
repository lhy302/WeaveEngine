# -*- coding: utf-8 -*-
"""
test_gamepack.py — 游戏包/插件包封装链路测试 (2026-08-27, 全无头).
覆盖: .lsc 加密/明文往返 (--no-encrypt-content) / .lpc 插件包加密往返 /
install_game_plugins: secure 校验链 (缺包/被改 -> SystemExit, 一致 -> 内存
注册插件) / MOD 模式目录投放加载 / 玩家进程 set_mode('player') 后全权.
无头 (无需 pygame/SDL 窗口); 每用例独立 tempfile.TemporaryDirectory;
注册脚本后清理 scripts.SCRIPTS / plugin_loader 全局.
"""
import json
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

import game_pack
import plugin_loader
from scripts import SCRIPTS

_FAILS = []


def check(name, cond, extra=""):
    print(("PASS " if cond else "FAIL ") + name + ("  " + str(extra) if extra else ""))
    if not cond:
        _FAILS.append(name)


def _write(path, content):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        f.write(content)


def _cleanup():
    for pid in list(plugin_loader._LOADED):
        plugin_loader.unload_plugin(pid, disable=False)
    plugin_loader._DISABLED.clear()
    plugin_loader._EDITOR_BUTTONS[:] = []
    for sid in list(SCRIPTS):
        if sid.startswith('p_') or sid.startswith('c_'):
            del SCRIPTS[sid]
    plugin_loader.set_mode('editor')


ENTRY_WHITELIST = """# -*- coding: utf-8 -*-
import math
from scripts import Script

class WScript(Script):
    script_id = 'p_math'
    name = '白名单脚本'

def register(api):
    api.register_script(WScript)
"""

_MANIFEST = json.dumps({"id": "com.example.pack", "name": "包内插件",
                        "version": "0.1.0", "entry": "entry.py",
                        "layer": "player", "capability": "render",
                        "desc": "测试包插件"})


def _plugin_dir_item(tmp):
    """在 tmp/plugins/player/pk 建标准插件, 返回扫描结果 (供 pack_plugins 用)."""
    d = os.path.join(tmp, 'plugins', 'player', 'pk')
    _write(os.path.join(d, 'plugin.json'), _MANIFEST)
    _write(os.path.join(d, 'entry.py'), ENTRY_WHITELIST)
    _write(os.path.join(d, 'data.txt'), '资源文件')
    items = plugin_loader.scan_player_plugins(base=tmp)
    assert items, "scan_player_plugins 应有 1 项"
    p = items[0]
    with open(os.path.join(p['path'], p['info']['entry']), 'r',
              encoding='utf-8') as f:
        entry_src = f.read()
    files = {}
    for fn in os.listdir(p['path']):
        if fn == p['info']['entry']:
            continue
        with open(os.path.join(p['path'], fn), 'rb') as fh:
            files[fn] = fh.read()
    return {'id': p['id'], 'name': p['info'].get('name', p['id']),
            'version': p['info']['version'], 'layer': p['layer'],
            'kind': p['kind'], 'entry': entry_src, 'files': files}


def _gm_config(hash_or_none):
    return {'config': {'name': '测试游', 'plugins_sha256': hash_or_none}}


# ============ 1. .lsc 加密往返 ============
def t_pack_roundtrip():
    with tempfile.TemporaryDirectory() as tmp:
        path = game_pack.pack(tmp, {'name': 'g1'}, {'scene': 'x'},
                              [('a.py', 'print(1)')])
        data = game_pack.load(tmp)
        check("加密 .lsc 往返: fmt/config/scripts 完整",
              data and data['fmt'] == 'loom-pack-1'
              and data['config']['name'] == 'g1'
              and data['scripts'] == [{'name': 'a.py', 'source': 'print(1)'}], data)
        with open(path, 'r', encoding='utf-8', errors='replace') as f:
            head = f.read(64)
        check("文件面不是明文 JSON (混淆)", '三' in head or 'fmt' not in head, head)


# ============ 2. 明文 .lsc (--no-encrypt-content) ============
def t_pack_plain():
    with tempfile.TemporaryDirectory() as tmp:
        game_pack.pack(tmp, {'name': 'g2'}, {'scene': 'y'},
                       [('b.py', 'print(2)')], encrypt=False)
        data = game_pack.load(tmp)
        check("明文 .lsc 往返正常", data and data['config']['name'] == 'g2'
              and data['scripts'][0]['name'] == 'b.py', data)
        with open(game_pack.pack_path(tmp), 'r', encoding='utf-8') as f:
            raw = f.read()
        check("明文包可直接阅读 (含 fmt 键)", '"fmt"' in raw and '"name": "g2"' in raw)


# ============ 3. .lpc 插件包加密往返 ============
def t_plugins_pack_roundtrip():
    with tempfile.TemporaryDirectory() as tmp:
        item = _plugin_dir_item(tmp)
        path = game_pack.pack_plugins(tmp, [item])
        data = game_pack.load_plugins_pack(tmp)
        ok = (data and data['fmt'] == 'loom-plugins-1'
              and len(data['plugins']) == 1
              and data['plugins'][0]['id'] == 'com.example.pack'
              and 'files' in data['plugins'][0])
        check("插件包往返: fmt/单 plugin/文件字节在", ok, data)
        with open(path, 'r', encoding='utf-8', errors='replace') as f:
            head = f.read(64)
        check("插件包文件面混淆 (无明文 JSON)", '"fmt"' not in head, head)


# ============ 4. install_game_plugins: secure 一致 -> 内存注册 ============
def t_install_secure_ok():
    with tempfile.TemporaryDirectory() as tmp:
        item = _plugin_dir_item(tmp)
        game_pack.pack_plugins(tmp, [item])
        import hashlib
        with open(game_pack.plugins_path(tmp), 'rb') as f:
            h = hashlib.sha256(f.read()).hexdigest()
        n = game_pack.install_game_plugins(tmp, _gm_config(h))
        check("secure 安装: 插件计数 1 + 脚本注册 (全权, 内存不落盘)",
              n == 1 and 'p_math' in SCRIPTS, n)
        check("插件包文件仍在 (未删除)", os.path.isfile(game_pack.plugins_path(tmp)))
        _cleanup()


# ============ 5. secure: 缺 .lpc -> 报错 ============
def t_install_secure_missing():
    with tempfile.TemporaryDirectory() as tmp:
        try:
            game_pack.install_game_plugins(tmp, _gm_config('aabbcc'))
            check("缺 .lpc -> SystemExit", False)
        except SystemExit as e:
            check("缺 .lpc -> SystemExit 含'插件包缺失'",
                  '插件包缺失' in str(e), str(e))


# ============ 6. secure: 被改 -> 拒绝 ============
def t_install_secure_tampered():
    with tempfile.TemporaryDirectory() as tmp:
        item = _plugin_dir_item(tmp)
        game_pack.pack_plugins(tmp, [item])
        import hashlib
        with open(game_pack.plugins_path(tmp), 'rb') as f:
            h = hashlib.sha256(f.read()).hexdigest()
        # 篡改 .lpc 一个字节
        with open(game_pack.plugins_path(tmp), 'r+', encoding='utf-8') as f:
            f.seek(10)
            ch = f.read(1)
            f.seek(10)
            f.write('X' if ch != 'X' else 'Y')
        try:
            game_pack.install_game_plugins(tmp, _gm_config(h))
            check("被改 .lpc -> SystemExit", False)
        except SystemExit as e:
            check("被改 .lpc -> SystemExit 含'被修改'", '被修改' in str(e), str(e))


# ============ 7. install_game_plugins: MOD 目录投放 (open) ============
def t_install_mod_mode():
    with tempfile.TemporaryDirectory() as tmp:
        _plugin_dir_item(tmp)
        n = game_pack.install_game_plugins(tmp, _gm_config(''))   # open: 无哈希
        check("MOD 安装: plugins/player 目录加载 + 脚本注册 (全权)",
              n == 1 and 'p_math' in SCRIPTS, n)
        _cleanup()


# ============ 8. 玩家进程 mode=player 生效 (全权 import os 放行) ============
def t_player_mode_allowed():
    with tempfile.TemporaryDirectory() as tmp:
        d = os.path.join(tmp, 'plugins', 'player', 'full')
        _write(os.path.join(d, 'plugin.json'), json.dumps({
            "id": "com.example.full", "name": "full", "version": "1.0.0",
            "entry": "entry.py"}))
        _write(os.path.join(d, 'entry.py'),
               "# -*- coding: utf-8 -*-\n"
               "import os\n"
               "def register(api):\n"
               "    assert isinstance(os.sep, str)   # os 模块可用 = 全权\n"
               "    api.register('tool', [1, 2])")
        plugin_loader.set_mode('player')   # 玩家进程语义
        r = plugin_loader.load_plugins(base=tmp)
        check("MOD 插件 import os 全权放行 (玩家进程)",
              'com.example.full' in r['loaded'] and r['broken'] == [], r)
        _cleanup()


if __name__ == "__main__":
    print("========== Loom 游戏包/插件包封装链路测试 ==========")
    _cleanup()
    t_pack_roundtrip()
    t_pack_plain()
    t_plugins_pack_roundtrip()
    t_install_secure_ok()
    t_install_secure_missing()
    t_install_secure_tampered()
    t_install_mod_mode()
    t_player_mode_allowed()
    _cleanup()
    if _FAILS:
        print("总结果: FAIL ❌", _FAILS)
        sys.exit(1)
    print("总结果: ALL PASS ✅")
    print("全部通过")
