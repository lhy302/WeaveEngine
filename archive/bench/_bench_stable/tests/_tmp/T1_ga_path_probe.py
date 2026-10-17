# -*- coding: utf-8 -*-
"""T1_ga_path_probe.py — 定位 game_audio load_sound 路径解析失败因素 (中文? 括号? 相对?).
用法: py -3.12 tests\_tmp\T1_ga_path_probe.py"""
import os
import shutil
import sys

import game_audio as ga

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, 'tone_test.wav')
mgr = ga.AudioManager.get_instance()
mgr.initialize()

cases = {
    'ascii_no_paren_abs': r'C:\Windows\Temp\tone_test.wav',
    'ascii_paren_abs': r'C:\Windows\Temp\a(b)\t1.wav',
    'chin_no_paren_abs': r'D:\my-project\测试目录\t1.wav',
    'chin_paren_abs': SRC,                       # 开发工作区路径 (中文+括号)
    'rel_ascii': 't1.wav',                        # 相对路径 (cwd=Loom\)
}
os.makedirs(r'C:\Windows\Temp\a(b)', exist_ok=True)
shutil.copy(SRC, r'C:\Windows\Temp\a(b)\t1.wav')
os.makedirs(r'D:\my-project\测试目录', exist_ok=True)
shutil.copy(SRC, r'D:\my-project\测试目录\t1.wav')
shutil.copy(SRC, 't1.wav')

for name, p in cases.items():
    try:
        h = mgr.load_sound(p)
        print('%-20s OK   %r' % (name, h))
    except Exception as e:
        print('%-20s FAIL %r' % (name, e))
mgr.shutdown()
print('shutdown done')
