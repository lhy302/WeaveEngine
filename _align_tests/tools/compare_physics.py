# -*- coding: utf-8 -*-
"""compare_physics.py — 物理对齐对比: Loom vs Unity。

用法: py compare_physics.py <physics_dir>

读:
  <dir>/loom_physics_result.json   (align_physics.py 产出; pos/vel = {A: [x,y,z]})
  <dir>/unity_physics_result.json  (AlignRunner.RunPhysics 产出; position/velocity 数组)
产出:
  <dir>/verdict.md
"""
import json
import os
import sys

TOL = 1e-2


def _get(d, *keys):
    for k in keys:
        if k in d:
            return d[k]
    return None


def main():
    d = os.path.abspath(sys.argv[1]) if len(sys.argv) > 1 else os.path.abspath('.')
    loom_p = os.path.join(d, 'loom_physics_result.json')
    unity_p = os.path.join(d, 'unity_physics_result.json')
    loom = json.load(open(loom_p, encoding='utf-8')) if os.path.exists(loom_p) else {}
    unity = json.load(open(unity_p, encoding='utf-8')) if os.path.exists(unity_p) else {}

    lo = {r['case']: r for r in loom.get('results', [])}
    un = {r['name']: r for r in unity.get('results', [])}

    lines = ['# 物理对齐: Loom vs Unity', '',
             '| case | Loom pos | Unity pos | Loom vel | Unity vel | 位置对齐 | 速度对齐 |',
             '|------|----------|-----------|----------|-----------|---------|---------|']
    total = 0
    matched = 0
    for name in sorted(set(lo) | set(un)):
        total += 1
        lr = lo.get(name, {})
        ur = un.get(name, {})
        lpos = (lr.get('pos') or {}).get('A')
        lvel = (lr.get('vel') or {}).get('A')
        upos = _get(ur, 'position')
        uvel = _get(ur, 'velocity')

        def cmp(a, b):
            if a is None or b is None:
                return None
            return all(abs(x - y) <= TOL for x, y in zip(a, b))

        pc = cmp(lpos, upos)
        vc = cmp(lvel, uvel)
        ok = (pc is not False) and (vc is not False)
        if ok:
            matched += 1

        def fmt(v):
            return '[%.4f,%.4f,%.4f]' % tuple(v) if v else '—'

        lines.append('| %s | %s | %s | %s | %s | %s | %s |' % (
            name, fmt(lpos), fmt(upos), fmt(lvel), fmt(uvel),
            {True: '✅', False: '❌', None: '—'}[pc],
            {True: '✅', False: '❌', None: '—'}[vc]))

    lines.append('')
    lines.append('**物理对齐度: %d/%d** (容差 %g)' % (matched, total, TOL))
    out = os.path.join(d, 'verdict.md')
    with open(out, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines))
    print('[对比] ' + out)
    print('\n'.join(lines))


if __name__ == '__main__':
    main()
