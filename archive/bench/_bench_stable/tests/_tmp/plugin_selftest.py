# -*- coding: utf-8 -*-
"""插件自测脚本 (2026-08-20, 供 DSH 开发插件后自测用, 无头不弹窗):
用法: py -3.12 tests/_tmp/plugin_selftest.py <插件id> <script_id>
加载真实 Loom/plugins 目录 → 打印 LOADED/BROKEN → 断言 script_id 在 SCRIPTS →
卸载指定插件保持环境干净. 返回码: 0=通过, 1=失败."""
import os
import sys

LOOM_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))   # tests\_tmp → tests → Loom\
sys.path.insert(0, LOOM_DIR)

import plugin_loader
from scripts import SCRIPTS

pid = sys.argv[1] if len(sys.argv) > 1 else ''
sid = sys.argv[2] if len(sys.argv) > 2 else ''
r = plugin_loader.load_plugins(base=LOOM_DIR)
print('LOADED:', r['loaded'])
print('BROKEN:', r['broken'])
if sid:
    ok = sid in SCRIPTS
    print('script registered:', ok)
    if ok:
        print('script name:', SCRIPTS[sid].name)
else:
    ok = not r['broken']
    print('script registered: (未指定 script_id, 以 broken 为空为准)')
if pid:
    ok2, err2 = plugin_loader.unload_plugin(pid)
    print('cleanup unload:', pid, ok2, err2)
print('SELFTEST:', 'PASS' if ok else 'FAIL')
sys.exit(0 if ok else 1)
