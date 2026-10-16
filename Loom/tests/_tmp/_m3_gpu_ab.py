# -*- coding: utf-8 -*-
r"""_m3_gpu_ab.py — M3 诊断: 同一会话内交错开关"阴影", 量化 GPU 侧代价

背景: GPU 3D 已 97% 饱和, 主线程大部分时间在等 GPU。要继续降最高核%/涨 FPS
      必须减 GPU 负载, 但需要先知道代价分布。本脚本在同一次播放会话内
      交替 light_set(shadow=on/off) 并各测一段, 用 FPS 反推 GPU 工作占比。

用法: py -3.12 tests\_tmp\_m3_gpu_ab.py [--secs 8]
落盘: tests\_tmp\_m3_gpu_ab.json / _m3_gpu_ab.log
"""
import argparse
import json
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import mt_profile_check as mp  # noqa: E402


def measure(call, secs, label):
    a = mp.snap(call)
    t0 = time.perf_counter()
    time.sleep(secs)
    wall = time.perf_counter() - t0
    b = mp.snap(call)
    df = int(b['frames']) - int(a['frames'])
    per = {}
    for k in set(list(a['times'].keys()) + list(b['times'].keys())):
        per[k] = (float(b['times'].get(k, 0.0)) - float(a['times'].get(k, 0.0))) / max(1, df)
    rec = {'label': label, 'frames': df, 'wall': wall,
           'fps': (df / wall) if wall > 0 else 0.0,
           'fps_agent': b.get('fps'),
           'ms_per_frame': {k: round(v, 3) for k, v in per.items()},
           'closure_ok': None}
    print('[%s] fps=%.1f  paint_total=%.3f  shadow_maps=%.3f  main_pass=%.3f  advance=%.3f'
          % (label, rec['fps'], per.get('mt_paint_total', 0.0),
             per.get('mt_shadow_maps', 0.0), per.get('mt_main_pass', 0.0),
             per.get('mt_paint_advance', 0.0)))
    return rec


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--secs', type=float, default=8.0)
    a = ap.parse_args()

    env = dict(os.environ)
    env['LOOM_PROFILE'] = '1'
    env['PYTHONIOENCODING'] = 'utf-8'
    log_path = os.path.join(HERE, '_m3_gpu_ab.log')
    logf = open(log_path, 'wb')
    proc = subprocess.Popen(
        [sys.executable, '-u', os.path.join(mp.LOOM, 'Loom.py'),
         '--open', mp.SCENE, '--agent'],
        cwd=mp.LOOM, stdout=logf, stderr=subprocess.STDOUT, env=env)
    out = {'scene': mp.SCENE, 'secs': a.secs, 'phases': [], 'errors': []}
    call = None
    try:
        info = mp.wait_port(proc, 90.0)
        if info is None:
            raise RuntimeError('端口未就绪')
        call = mp.make_call(info['port'], info['token'])
        time.sleep(8.0)
        call('play', {'on': True})
        time.sleep(10.0)

        out['phases'].append(measure(call, a.secs, 'A_shadow_on'))
        r = call('light_set', {'name': '太阳', 'shadow': False})
        out['light_set_off'] = r
        time.sleep(2.0)
        out['phases'].append(measure(call, a.secs, 'B_shadow_off'))
        r = call('light_set', {'name': '太阳', 'shadow': True})
        out['light_set_on'] = r
        time.sleep(2.0)
        out['phases'].append(measure(call, a.secs, 'C_shadow_on'))
    except Exception as e:
        out['errors'].append('%s: %s' % (type(e).__name__, e))
    finally:
        if call is not None:
            try:
                call('quit', {'save': 'discard'})
            except Exception:
                pass
        time.sleep(1.0)
        if proc.poll() is None:
            mp.kill_tree(proc.pid)
        try:
            logf.close()
        except Exception:
            pass

    dst = os.path.join(HERE, '_m3_gpu_ab.json')
    with open(dst, 'w', encoding='utf-8') as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print('saved', dst)
    ph = {p['label']: p for p in out['phases']}
    on = [p['fps'] for p in out['phases'] if 'on' in p['label']]
    off = [p['fps'] for p in out['phases'] if 'off' in p['label']]
    if on and off:
        mo = sum(on) / len(on)
        mf = sum(off) / len(off)
        print('阴影 ON  平均 fps = %.1f' % mo)
        print('阴影 OFF 平均 fps = %.1f' % mf)
        print('⇒ 阴影 GPU 代价占比 ≈ %.1f%% (1 - on/off)'
              % (100.0 * (1.0 - mo / mf) if mf else 0.0))
    for e in out['errors']:
        print('ERROR:', e)
    return 0


if __name__ == '__main__':
    sys.exit(main())
