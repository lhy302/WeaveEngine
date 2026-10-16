# -*- coding: utf-8 -*-
"""_m2_count_exports.py — 独立清点 DLL 导出符号 (R4 复核用, 只读)

用途: 不依赖任何文档, 直接解析 PE 导出表, 核对
  · pipeline.dll 的 provides 4 接口 vs 实际导出符号数
  · verify_release 报告里的 "导出符号 13/8/10" 是否属实
用法: py -3.12 tests/_tmp/_m2_count_exports.py
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import verify_release as v  # noqa: E402

ROOT = os.path.abspath(os.path.join(HERE, '..', '..'))
TARGETS = [
    ('pipeline.dll', r'core_components\pipeline\pipeline.dll'),
    ('module_ref.dll', r'core_components\module_ref.dll'),
    ('loom_kernels.dll', r'ckernels\loom_kernels.dll'),
    ('badvector.dll', r'core_components\badvector.dll'),
    ('ambiguous.dll', r'core_components\ambiguous.dll'),
]

for name, rel in TARGETS:
    path = os.path.join(ROOT, rel)
    if not os.path.isfile(path):
        print('%-18s MISSING %s' % (name, path))
        continue
    with open(path, 'rb') as f:
        data = f.read()
    try:
        dll_name, exports, info = v.parse_pe_exports(data)
        print('%-18s exports=%2d  dll_name=%s' % (name, len(exports), dll_name))
        for e in exports:
            print('    - %s' % e)
    except Exception as exc:
        print('%-18s PARSE FAIL %s: %s' % (name, type(exc).__name__, exc))
