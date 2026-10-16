# -*- coding: utf-8 -*-
"""diag_np_micro_entry.py — Nuitka 微基准编译入口 (任务3 b 侧)

只带 numpy 的最小 standalone: 复用 diag_np_micro.py 的 main()。
编译 (参考台账 build5 配方, 输出目录禁中文):
  py -3.12 -m nuitka --standalone --msvc=latest --assume-yes-for-downloads
    --windows-console-mode=force --nofollow-import-to=numba
    --output-dir=D:\my-project\_diag_npbuild diag_np_micro_entry.py
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import diag_np_micro

if __name__ == '__main__':
    diag_np_micro.main()
