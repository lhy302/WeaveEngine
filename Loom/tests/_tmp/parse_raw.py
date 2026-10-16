# -*- coding: utf-8 -*-
import sys, collections
path = sys.argv[1] if len(sys.argv) > 1 else r'D:\rec_edit.txt'
leaf = collections.Counter()
mid = collections.Counter()   # 中间帧（含 render/advance 等主干）
total = 0
for line in open(path, encoding='utf-8', errors='replace'):
    line = line.rstrip('\n')
    if not line:
        continue
    # 最后一个空格分隔样本数
    i = line.rfind(' ')
    if i < 0:
        continue
    try:
        cnt = int(line[i+1:])
    except ValueError:
        continue
    stack = line[:i].split(';')
    total += cnt
    if stack:
        leaf[stack[-1]] += cnt
    for fr in stack:
        # 归一化到函数名（去行号/文件）
        nm = fr.split(' (')[0]
        mid[nm] += cnt

print("总样本:", total)
print("\n=== leaf 热点 (真正占用CPU的最内层) TOP 30 ===")
for fn, c in leaf.most_common(30):
    print("  %6.2f%%  %5d  %s" % (100.0*c/total, c, fn))

print("\n=== 关键函数出现次数 (含所有栈层) TOP 30 ===")
for fn, c in mid.most_common(30):
    print("  %6.2f%%  %5d  %s" % (100.0*c/total, c, fn))
