# -*- coding: utf-8 -*-
r"""ab_batch.py — 全量 A/B 场景 MAE 批量回归 (2026-11-06).

对 tests\_tmp\ab_*.json 每个场景跑 GL / VK 离屏渲染并给 MAE/MAX/NCC,
用于确认"相机对齐改动"没有劣化任何既有 A/B 场景 (门槛 MAE <= 0.0002).

用法: py -3.12 tests\_tmp\ab_batch.py [glob]
"""
import glob
import os
import sys

try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, ROOT)
sys.path.insert(0, HERE)
os.chdir(ROOT)
os.environ.setdefault('LOOM_NO_PARALLEL', '1')
os.environ['LOOM_NO_SAVE_MIGRATE'] = '1'

import numpy as np                      # noqa: E402

import ab_gl_vk as AB                   # noqa: E402

THRESH = 0.0002


def main():
    pattern = sys.argv[1] if len(sys.argv) > 1 else os.path.join(HERE, 'ab_*.json')
    files = sorted(glob.glob(pattern))
    if not files:
        print('找不到场景:', pattern)
        return 1
    print("%-26s %-10s %-10s %-10s %-8s %s"
          % ("场景", "MAE", "MAX", "NCC", "模型数", "结论"))
    print("-" * 84)
    bad = []
    for f in files:
        name = os.path.basename(f)
        data = AB._scene_data(f)
        try:
            g, ed, ctx = AB.render_gl(data)
            v, drv = AB.render_vk(data)
            ctx.release()
            d = np.abs(g - v)
            mae = float(d.mean())
            mx = float(d.max())
            la = g.mean(axis=2).ravel(); lb = v.mean(axis=2).ravel()
            la = la - la.mean(); lb = lb - lb.mean()
            ncc = float((la * lb).sum() /
                        (np.linalg.norm(la) * np.linalg.norm(lb) + 1e-9))
            ok = mae <= THRESH
            if not ok:
                bad.append((name, mae))
            print("%-26s %-10.6f %-10.4f %-10.4f %d/%-6d %s"
                  % (name, mae, mx, ncc, len(ed.models), len(drv.models),
                     "PASS" if ok else "FAIL"))
        except Exception as e:
            bad.append((name, repr(e)))
            print("%-26s 异常: %r" % (name, e))
    print("-" * 84)
    print("场景数 %d, 门槛 MAE <= %g, 失败 %d" % (len(files), THRESH, len(bad)))
    if bad:
        for b in bad:
            print("  FAIL:", b)
        return 1
    print("全部通过 ✅")
    return 0


if __name__ == '__main__':
    sys.exit(main())
