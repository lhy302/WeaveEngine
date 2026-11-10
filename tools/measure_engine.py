# -*- coding: utf-8 -*-
"""tools/measure_engine.py — 测量层：回答「性能是多少 / 变好还是变坏」。

与冒烟（tools/smoke.py）和回归（Loom/tests/run_all.py）严格分离：
  * 冒烟只回答「能不能跑」
  * 回归只回答「功能对不对」
  * 本工具只回答「数字是多少」，默认**不做阈值判定**（除非显式 --min-fps）

用法：
  py -3.13 tools/measure_engine.py --scene examples/PacMan2D.json --runs 3
  py -3.13 tools/measure_engine.py --scene <场景> --runs 5 --ab "LOOM_BUCKET_PACK=0"
  py -3.13 tools/measure_engine.py --scene <场景> --runs 3 --json out.json --min-fps 30
"""
import argparse
import json
import os
import re
import statistics
import subprocess
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOOM = os.path.join(ROOT, 'Loom')
DEFAULT_SCENE = os.path.join(ROOT, 'examples', 'PacMan2D.json')
FPS_RE = re.compile(r'FPS:\s*([0-9.]+)')
TPS_RE = re.compile(r'TPS:\s*([0-9.]+)')


def _bench_once(scene, frames, extra_env):
    env = dict(os.environ)
    env.pop('LOOM_BENCH_RESULT', None)
    env.update(extra_env or {})
    tmp = os.path.join(tempfile.gettempdir(),
                       'loom_measure_%d_%d.txt' % (os.getpid(), int(time.time() * 1000) % 100000))
    env['LOOM_BENCH_RESULT'] = tmp
    cmd = [sys.executable, os.path.join(LOOM, 'Loom.py'),
           '--bench', scene, str(frames)]
    t0 = time.time()
    p = subprocess.run(cmd, cwd=LOOM, env=env, capture_output=True, text=True,
                       encoding='utf-8', errors='replace', timeout=600)
    dt = time.time() - t0
    out = (p.stdout or '') + (p.stderr or '')
    fps = float(FPS_RE.search(out).group(1)) if FPS_RE.search(out) else None
    tps = float(TPS_RE.search(out).group(1)) if TPS_RE.search(out) else None
    if fps is None and os.path.isfile(tmp):
        txt = open(tmp, encoding='utf-8', errors='replace').read()
        m = FPS_RE.search(txt)
        fps = float(m.group(1)) if m else None
        m = TPS_RE.search(txt)
        tps = float(m.group(1)) if m else None
    try:
        os.remove(tmp)
    except OSError:
        pass
    return {'fps': fps, 'tps': tps, 'wall_s': round(dt, 2), 'rc': p.returncode}


def _summ(vals):
    vals = [v for v in vals if v is not None]
    if not vals:
        return None
    return {'n': len(vals), 'median': round(statistics.median(vals), 1),
            'min': round(min(vals), 1), 'max': round(max(vals), 1)}


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument('--scene', default=DEFAULT_SCENE)
    ap.add_argument('--frames', type=int, default=600)
    ap.add_argument('--runs', type=int, default=3)
    ap.add_argument('--ab', action='append', default=[],
                    help='A/B 对照用的 env，如 "LOOM_BUCKET_PACK=0"；给多个则交替跑')
    ap.add_argument('--json', help='把结果写到该 JSON 文件')
    ap.add_argument('--min-fps', type=float, default=None,
                    help='可选门禁：低于该值返回 1（默认只记录不判定）')
    a = ap.parse_args(argv)

    scene = os.path.abspath(a.scene)
    if not os.path.isfile(scene):
        print('测量失败：场景不存在 %s' % scene)
        return 2

    configs = [('default', {})]
    for spec in a.ab:
        if '=' not in spec:
            print('--ab 需要 KEY=VAL：%s' % spec)
            return 2
        k, v = spec.split('=', 1)
        configs.append((spec, {k: v}))

    results = {}
    # 交替采样：优先 A/B 交替，减少机器漂移带来的偏差
    for i in range(a.runs):
        for name, env in configs:
            r = _bench_once(scene, a.frames, env)
            results.setdefault(name, []).append(r)
            print('  [%d/%d] %-28s fps=%s tps=%s rc=%s'
                  % (i + 1, a.runs, name, r['fps'], r['tps'], r['rc']))

    summary = {}
    print('')
    for name, rs in results.items():
        f = _summ([r['fps'] for r in rs])
        t = _summ([r['tps'] for r in rs])
        summary[name] = {'fps': f, 'tps': t, 'raw': rs}
        if f:
            print('%-28s FPS 中位 %6.1f  (min %.1f / max %.1f, n=%d)  TPS 中位 %s'
                  % (name, f['median'], f['min'], f['max'], f['n'],
                     ('%.2f' % t['median']) if t else 'n/a'))
        else:
            print('%-28s 没有拿到 FPS（rc=%s）' % (name, rs[0]['rc'] if rs else '?'))

    payload = {'scene': scene, 'frames': a.frames, 'runs': a.runs,
               'taken_at': time.strftime('%Y-%m-%d %H:%M:%S'), 'summary': summary}
    if a.json:
        with open(a.json, 'w', encoding='utf-8') as fh:
            json.dump(payload, fh, ensure_ascii=False, indent=2)
        print('\n已写入 %s' % a.json)

    if a.min_fps is not None:
        # 门禁对**每个**配置都判（含 --ab 对照组），任一下降都算失败
        bad = []
        for name, s in summary.items():
            med = (s.get('fps') or {}).get('median')
            if med is None:
                bad.append('%s: 拿不到 FPS' % name)
            elif med < a.min_fps:
                bad.append('%s: 中位 %.1f < %.1f' % (name, med, a.min_fps))
        if bad:
            for b in bad:
                print('门禁失败：' + b)
            return 1
        print('门禁通过：全部配置中位 FPS >= %.1f' % a.min_fps)
    return 0


if __name__ == '__main__':
    sys.exit(main())
