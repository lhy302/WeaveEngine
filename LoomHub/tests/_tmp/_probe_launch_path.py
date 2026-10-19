# -*- coding: utf-8 -*-
"""临时探针: 验证 LoomHub 启动路径解析"""
import os

# __file__ 在 LoomHub/tests/_tmp/，向上 3 级到 LoomHub/
THIS_DIR = os.path.dirname(os.path.abspath(__file__))
HUB = os.path.abspath(os.path.join(THIS_DIR, '..', '..'))
WORKSPACE = os.path.abspath(os.path.join(HUB, '..'))
print('LoomHub 目录:', HUB)
print('工作区根:', WORKSPACE)
print()

# 关键: interpreters.json 里的字段
interp_dir = 'Loom'
interp_path = 'Loom/Loom.py'

# 实测三种启动 cwd 场景
for label, launch_cwd in [
    ('场景 A: 用户从工作区根 cd 到该目录后双击 LoomHub.py', WORKSPACE),
    ('场景 B: 用户从 LoomHub/ 目录启动 LoomHub.py', HUB),
    ('场景 C: 用户从任意目录用 python LoomHub.py 绝对路径启动', 'C:\\'),  # 模拟系统目录
]:
    print('=== %s ===' % label)
    # Popen(cmd, cwd=interp['dir']) 里的 cwd 是 "Loom"（相对）
    # Popen 会相对 python 进程的 cwd（不是脚本目录）解析
    sub_cwd = os.path.join(launch_cwd, interp_dir)
    print('  Popen cwd 解析为:', sub_cwd, '| 存在:', os.path.isdir(sub_cwd))

    # 子进程内 python 拿到的 argv[1] = interp_path = "Loom/Loom.py"
    # python 会相对子进程 cwd 解析它
    resolved = os.path.join(sub_cwd, interp_path)
    print('  子进程 python 解析 Loom.py 为:', resolved)
    print('  存在:', os.path.isfile(resolved))

    # 如果 cwd 不设置（沿用父进程 cwd），期望结果
    expected = os.path.join(launch_cwd, interp_path)
    print('  正确路径应为:', expected, '| 存在:', os.path.isfile(expected))
    print()

# 关键结论: 应该改成绝对路径
print('=== 修复方案验证 ===')
# 方案: build_launch_command 里把 info['path'] 转绝对路径
correct_abs_path = os.path.join(WORKSPACE, interp_path)
print('info[path] 解析为绝对:', correct_abs_path, '| 存在:', os.path.isfile(correct_abs_path))
