# -*- coding: utf-8 -*-
"""ledger_append.py — 台账追加工具 (避免 -c 内联引号转义坑)"""
import io
import sys

entry = sys.argv[1] if len(sys.argv) > 1 else ''
if not entry:
    raise SystemExit('usage: ledger_append.py <text-file>')
with io.open(sys.argv[1], encoding='utf-8') as f:
    text = f.read()
with io.open('bench_result_对比台账.txt', 'a', encoding='utf-8') as f:
    f.write(text)
print('ledger appended')
