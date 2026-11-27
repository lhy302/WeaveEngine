# -*- coding: utf-8 -*-
"""_dialog_case_child.py — test_backend_dialog_autoclose.py 的子探针（下划线前缀：不会被 run_all 收集）。

用法: py -3.13 _dialog_case_child.py <no_dialog|default|auto_close|bad_value>
行为：按 argv 设环境 -> 真调 hostenv.backend_guard.show_blocking_dialog -> 打印一行
RESULT json（shown / elapsed / stdout 自证），不 stub、不 mock（测的是生产方式）。
父门负责「外部点掉」对话框（本子探针会一直阻塞到有人点，这正是要证明的默认行为）。
"""
import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

CASE = (sys.argv[1] if len(sys.argv) > 1 else 'default').strip().lower()

# 环境**先清空再按 case 设置**（父门 env 里可能带 LOOM_NO_DIALOG=1）
os.environ.pop('LOOM_NO_DIALOG', None)
os.environ.pop('LOOM_DIALOG_AUTO_CLOSE_MS', None)
if CASE == 'no_dialog':
    os.environ['LOOM_NO_DIALOG'] = '1'
elif CASE == 'auto_close':
    os.environ['LOOM_DIALOG_AUTO_CLOSE_MS'] = '1500'
elif CASE == 'bad_value':
    os.environ['LOOM_DIALOG_AUTO_CLOSE_MS'] = 'not-a-number'
# default: 两个都不设（真实用户态）

from hostenv.backend_guard import show_blocking_dialog   # noqa: E402

t0 = time.monotonic()
shown = show_blocking_dialog('AUTOCLOSE-CASE-' + CASE, 'body of %s' % CASE)
elapsed = time.monotonic() - t0
print('RESULT ' + json.dumps({'case': CASE, 'shown': bool(shown),
                              'elapsed': round(elapsed, 2)}, ensure_ascii=False))