# -*- coding: utf-8 -*-
"""冒烟：验证游戏脚本能自由 import 网络模块"""
import io, sys, os
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

# 加引擎路径
ENGINE = r'D:\my-project - 副本\Loom(py源代码-工作区)\Loom'
sys.path.insert(0, ENGINE)
os.chdir(ENGINE)

import scripts as sc

fails = []
def check(label, cond, detail=''):
    msg = ('PASS ' if cond else 'FAIL ') + label
    if detail:
        msg += '  ' + str(detail)
    print(msg)
    if not cond:
        fails.append(label)

# 1) 模拟脚本类里 import urllib
@sc.register
class _NetTestScript(sc.Script):
    script_id = '_net_test'
    name = '网络测试'
    params = ()
    def on_start(self):
        try:
            import urllib.request
            import socket
            check('脚本可 import urllib.request', True)
            check('脚本可 import socket', True)
        except ImportError as e:
            check('脚本可 import urllib.request', False, e)

# 2) 检查 sandbox 限制是否只针对插件
import plugin_sandbox
print('=== plugin_sandbox 限制（仅插件用）===')
danger = getattr(plugin_sandbox, '_DANGER_NAMES', None)
print('_DANGER_NAMES:', danger)
print()

# 3) 验证 game script load 路径没挂沙箱
import inspect
src = inspect.getsource(sc.load_script_dir)
print('=== load_script_dir 是否用 restricted_import ===')
print('use restricted_import:', 'restricted_import' in src)
print('use standard exec_module:', 'exec_module' in src)
print()

# 4) 检查 game_pack 是否限制网络
try:
    import game_pack
    print('game_pack 存在，检查是否含网络限制关键词')
    gp_src = inspect.getsource(game_pack)
    for kw in ['network', 'socket', 'forbid', 'block', 'restrict']:
        if kw in gp_src.lower():
            print('  game_pack 含关键词:', kw)
except Exception as e:
    print('game_pack 读取失败:', e)

# 清理
if '_net_test' in sc.SCRIPTS:
    del sc.SCRIPTS['_net_test']

print()
if fails:
    print('===== 失败 %d 项 =====' % len(fails))
    sys.exit(1)
print('===== 全部通过 =====')
