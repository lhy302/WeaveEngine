# -*- coding: utf-8 -*-
import json, sys, collections
path = sys.argv[1] if len(sys.argv) > 1 else r'D:\rec_edit.json'
d = json.load(open(path, encoding='utf-8'))
frames = d['shared']['frames']
# 统计：每个样本取栈顶（最后进入的帧）
top = collections.Counter()
bythread = collections.Counter()
for prof in d['profiles']:
    name = prof.get('name', '?')
    for s in prof.get('samples', []):
        stack = s if isinstance(s, list) else s.get('stack', [])
        if not stack:
            continue
        bythread[name] += 1
        leaf = stack[-1]
        top[frames[leaf]['name']] += 1
total = sum(top.values())
print("总样本:", total, " 线程:", dict(bythread))
print("\n=== 热点函数 (leaf, 按占用排序) ===")
for fn, c in top.most_common(25):
    print("  %6.2f%%  %6d  %s" % (100.0 * c / total, c, fn))
