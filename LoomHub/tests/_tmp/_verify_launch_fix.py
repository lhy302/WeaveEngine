# -*- coding: utf-8 -*-
"""修复后校验：路径解析 + 模块 import + launch_spec 结构"""
import os
import sys
THIS_DIR = os.path.dirname(os.path.abspath(__file__))
HUB = os.path.abspath(os.path.join(THIS_DIR, '..', '..'))
sys.path.insert(0, HUB)

print('=== 1) 模块 import ===')
ok, fail = [], []
for m in ['LoomHubGUI', 'hub_controller', 'hub_config', 'hub_commands',
          'hub_install', 'hub_console', 'hub_view_tk']:
    try:
        __import__(m)
        ok.append(m)
    except Exception as e:
        fail.append((m, repr(e)))
print('  OK:', ok)
print('  FAIL:', fail)

print()
print('=== 2) hub_config.WORKSPACE + resolve_runtime_path ===')
import hub_config as cfg
print('  HUB_DIR:', cfg.HUB_DIR)
print('  WORKSPACE:', cfg.WORKSPACE)
# 测试相对路径解析
for p in ['Loom/Loom.py', 'Loom/保存/场景.json', None, '']:
    r = cfg.resolve_runtime_path(p)
    print('  resolve(%r) ->' % p, r, '| 存在:', os.path.isfile(r) if r else 'N/A')

# 测试绝对路径不被改写
abs_p = os.path.join(cfg.WORKSPACE, 'Loom', 'Loom.py')
r = cfg.resolve_runtime_path(abs_p)
print('  resolve(绝对路径) ->', r, '| 未修改:', r == abs_p)

print()
print('=== 3) build_launch_command 检查 ===')
interp = cfg.default_interpreter()
print('  default_interpreter:', interp)
if interp:
    cmd = cfg.build_launch_command(interp, None, mode='open', prefer='py')
    print('  build_launch_command 结果:')
    for i, c in enumerate(cmd):
        print('    [%d] %s' % (i, c))
    # 检查第 2 个元素（Loom.py 路径）是否为绝对路径且存在
    if len(cmd) >= 2:
        py_path = cmd[1]
        print('  python 脚本路径:', py_path)
        print('  存在:', os.path.isfile(py_path))
        print('  是绝对路径:', os.path.isabs(py_path))

print()
print('=== 4) launch_spec 检查（EAI 路径） ===')
import hub_commands
spec, err = hub_commands.launch_spec({})
if err:
    print('  ERROR:', err)
else:
    print('  cmd:', spec['cmd'])
    print('  cwd:', spec['cwd'], '| 存在:', os.path.isdir(spec['cwd']))
    # 检查 cmd[1] 是否为绝对且存在的路径
    if len(spec['cmd']) >= 2:
        print('  cmd[1] 存在:', os.path.isfile(spec['cmd'][1]))

print()
print('=== 5) 带场景的 launch_spec ===')
scene_rel = 'Loom/保存/场景.json'
spec2, err2 = hub_commands.launch_spec({'scene': scene_rel})
if err2:
    print('  ERROR:', err2)
else:
    print('  cmd:', spec2['cmd'])
    print('  cwd:', spec2['cwd'])
