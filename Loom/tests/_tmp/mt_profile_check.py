# -*- coding: utf-8 -*-
r"""mt_profile_check.py — M3 主线程分段归因探针 (实测, 非推断)

背景: M2b主线程归因 §5 自述「主线程段账中 Qt/GL/Python 胶水的逐段精确拆分未做」,
      旧 _stage_times 用 time.time() (Windows 粒度 ~15.6ms) 且是全程累计值 →
      无法给出 ms/帧 口径的分段。M3 第一步就是把这段真正测出来。

本探针做法 (零侵入: 引擎侧插桩已由 LOOM_PROFILE=1 门控, 未开时零开销):
  Loom.py --open 保存\压测500混合.json --agent  (env LOOM_PROFILE=1)
    → 等 .agent_port.json (pid 匹配, <=60s)
    → 启动后 --warmup 秒预热 → agent POST /cmd play {on:true}
    → 稳态 --steady 秒 (计数器热身)
    → 快照 A (engine_metrics.mt_profile: frames/times/calls)
    → 采样 --secs 秒
    → 快照 B
    → per-frame ms = (B.times - A.times) / (B.frames - A.frames)
    → qt_glue = mt_paint_total − mt_paint_advance − mt_paint_render
    → agent quit {save:'discard'}

落盘 (UTF-8):
  tests/_tmp/mt_profile_on.json   原始产物 (含 per-frame 表)
  tests/_tmp/mt_profile_on.log    Loom.py 控制台

★B2 退役 (2026-10-16): 删 --mode off (LOOM_NO_PIPELINE=1) 档, 单档 on。

用法:
  py -3.12 tests/_tmp/mt_profile_check.py [--secs 12]
"""
import argparse
import json
import os
import subprocess
import sys
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
LOOM = os.path.abspath(os.path.join(HERE, '..', '..'))
sys.path.insert(0, LOOM)

SCENE = os.path.join(LOOM, '保存', '压测500混合.json')

# 主线程分段清单 (顺序 = 执行序), 用于闭合校验与报告排版
MAIN_SEGMENTS = [
    'mt_paint_total',        # 宿主 paintGL 总耗时 (最外层)
    'mt_paint_advance',      # paintGL 内 advance_logic 调用
    'mt_paint_render',       # paintGL 内 render 调用
    'mt_render_total',       # render() 自身总耗时
    'logic_step',            # 时钟推进 (内含 _logic_frame 全部子段)
    'mt_scripts',
    'mt_pipe_post',
    'mt_audio_anim',
    'pipe_wait',             # 等物理管线 (主线程阻塞等待)
    'mt_logic_prep',         # 逻辑帧尾 prep (含下面 3 段)
    'aabbs',
    'shadow_bounds',
    'collide_pairs',
    'mt_dispatch',
    'mt_interp_advance',
    'world_matrices',
    'interp',
    'shadow_prep',
    'buckets',
    'mt_shadow_maps',
    'mt_main_pass',
    'mt_hud',
    'mt_render_tail',
    'dispatch',
]


def wait_port(proc, timeout=90.0):
    t0 = time.time()
    while time.time() - t0 < timeout:
        try:
            with open(os.path.join(LOOM, '.agent_port.json'), encoding='utf-8') as f:
                cand = json.load(f)
            if cand.get('pid') == proc.pid and cand.get('port'):
                return cand
        except Exception:
            pass
        time.sleep(0.5)
    return None


def make_call(port, token):
    def call(name, args=None):
        body = json.dumps({'cmd': name, 'args': args or {}}).encode('utf-8')
        req = urllib.request.Request(
            'http://127.0.0.1:%d/cmd' % port, data=body, method='POST',
            headers={'X-Agent-Token': token, 'Content-Type': 'application/json'})
        with urllib.request.urlopen(req, timeout=90) as r:
            return json.loads(r.read().decode('utf-8'))
    return call


def snap(call):
    m = call('engine_metrics')
    m = m.get('result', m) if isinstance(m, dict) else m
    prof = (m or {}).get('mt_profile') or {}
    return {
        'frames': prof.get('frames', 0),
        'times': dict(prof.get('times') or {}),
        'calls': dict(prof.get('calls') or {}),
        'counts': dict(prof.get('counts') or {}),
        'fps': (m or {}).get('fps'),
        'tps': (m or {}).get('get_tps'),
        'jitter': (m or {}).get('get_frame_jitter'),
        'metrics': {k: v for k, v in (m or {}).items()
                    if k in ('fps', 'get_tps', 'get_frame_jitter', 'is_playing',
                             'logic_steps', 'clock')},
    }


def kill_tree(pid):
    try:
        subprocess.run(['taskkill', '/F', '/T', '/PID', str(pid)],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=20)
        return
    except Exception:
        pass
    try:
        os.kill(pid, 9)
    except Exception:
        pass


def run(secs, warmup, steady):
    """★B2 退役 (2026-10-16): 删 mode (off=LOOM_NO_PIPELINE=1) 档, 单档 on。"""
    out = {'mode': 'on', 'secs': secs, 'ts': time.strftime('%Y-%m-%dT%H:%M:%S'),
           'scene': SCENE, 'warmup_s': warmup, 'steady_s': steady,
           'env': {'LOOM_PROFILE': '1'},
           'errors': []}

    env = dict(os.environ)
    env['LOOM_PROFILE'] = '1'
    env['PYTHONIOENCODING'] = 'utf-8'

    log_path = os.path.join(HERE, 'mt_profile_on.log')
    logf = open(log_path, 'wb')
    proc = subprocess.Popen(
        [sys.executable, '-u', os.path.join(LOOM, 'Loom.py'),
         '--open', SCENE, '--agent'],
        cwd=LOOM, stdout=logf, stderr=subprocess.STDOUT, env=env)
    out['pid'] = proc.pid
    out['log'] = log_path
    call = None
    try:
        info = wait_port(proc, 90.0)
        if info is None:
            raise RuntimeError('端口文件 90s 未就绪 (pid=%d), 见 %s' % (proc.pid, log_path))
        out['port'] = info['port']
        call = make_call(info['port'], info['token'])

        time.sleep(warmup)
        out['play_result'] = call('play', {'on': True})
        time.sleep(steady)

        a = snap(call)
        t0 = time.perf_counter()
        time.sleep(secs)
        wall = time.perf_counter() - t0
        b = snap(call)

        out['snap_a'] = a
        out['snap_b'] = b
        out['wall'] = wall
        dframes = int(b['frames']) - int(a['frames'])
        out['delta_frames'] = dframes
        out['fps_measured'] = (dframes / wall) if wall > 0 else 0.0
        out['fps_agent_b'] = b.get('fps')
        if dframes <= 0:
            raise RuntimeError('帧计数未增长 (A=%s B=%s) — LOOM_PROFILE 未生效?'
                               % (a['frames'], b['frames']))

        per_frame = {}
        per_call_us = {}
        for name in set(list(a['times'].keys()) + list(b['times'].keys())):
            dt = float(b['times'].get(name, 0.0)) - float(a['times'].get(name, 0.0))
            dc = int(b['calls'].get(name, 0)) - int(a['calls'].get(name, 0))
            per_frame[name] = dt / dframes
            per_call_us[name] = (dt / dc * 1000.0) if dc > 0 else None
        out['ms_per_frame'] = dict(sorted(per_frame.items(), key=lambda kv: -kv[1]))
        out['us_per_call'] = per_call_us
        out['calls_delta'] = {k: int(b['calls'].get(k, 0)) - int(a['calls'].get(k, 0))
                              for k in set(list(a['calls'].keys()) + list(b['calls'].keys()))}
        # M3-P5: 计数类观测量 per-frame (draw_calls / buckets)
        out['counts_per_frame'] = {}
        out['counts_delta'] = {}
        for k in set(list(a.get('counts', {}).keys()) + list(b.get('counts', {}).keys())):
            dv = float(b['counts'].get(k, 0)) - float(a['counts'].get(k, 0))
            out['counts_delta'][k] = dv
            if k == 'draw_calls':          # 累计型: 除以帧数
                out['counts_per_frame'][k] = dv / dframes
            else:                          # 瞬时型 (buckets): 取快照值
                out['counts_per_frame'][k] = b['counts'].get(k, 0)

        # 派生: Qt/GL 胶水 = paintGL 总 − advance − render
        pt = per_frame.get('mt_paint_total', 0.0)
        pa = per_frame.get('mt_paint_advance', 0.0)
        pr = per_frame.get('mt_paint_render', 0.0)
        out['derived'] = {
            'qt_glue_ms': pt - pa - pr,
            'render_inside_total_ms': pr - per_frame.get('mt_render_total', 0.0),
            'logic_step_minus_subsegments_ms': per_frame.get('logic_step', 0.0) - sum(
                per_frame.get(k, 0.0) for k in
                ('mt_scripts', 'mt_pipe_post', 'mt_audio_anim', 'pipe_wait',
                 'mt_logic_prep', 'mt_dispatch', 'mt_interp_advance')),
            'render_total_minus_segments_ms': per_frame.get('mt_render_total', 0.0) - sum(
                per_frame.get(k, 0.0) for k in
                ('logic_step', 'world_matrices', 'interp', 'shadow_prep', 'buckets',
                 'mt_shadow_maps', 'mt_main_pass', 'mt_hud', 'mt_render_tail')),
        }
        # 闭合校验: 主线程最外层 paint_total 应 ≥ 其子段之和 (误差 10%)
        sub = pa + pr
        out['closure'] = {
            'paint_total_ms': pt,
            'paint_sub_ms': sub,
            'gap_ms': pt - sub,
            'ok': (pt <= 0) or (sub <= pt * 1.10),
        }
    finally:
        if call is not None:
            try:
                call('quit', {'save': 'discard'})
            except Exception as e:
                out['errors'].append('quit: %s: %s' % (type(e).__name__, e))
        time.sleep(1.0)
        if proc.poll() is None:
            kill_tree(proc.pid)
            out['killed'] = True
        try:
            logf.close()
        except Exception:
            pass
    return out


def main():
    ap = argparse.ArgumentParser()
    # ★B2 退役 (2026-10-16): 删 --mode; 单档 on。
    ap.add_argument('--secs', type=float, default=12.0)
    ap.add_argument('--warmup', type=float, default=8.0)
    ap.add_argument('--steady', type=float, default=10.0)
    ap.add_argument('--suffix', default='', help='产物文件名后缀 (保留多轮物证)')
    ap.add_argument('--scene', default='', help='场景文件 (默认 保存/压测500混合.json)')
    a = ap.parse_args()
    global SCENE
    if a.scene:
        SCENE = a.scene if os.path.isabs(a.scene) else os.path.join(LOOM, a.scene)
    print('=== mt_profile_check  secs=%.1f ===' % a.secs)
    print('scene =', SCENE)
    out = run(a.secs, a.warmup, a.steady)
    dst = os.path.join(HERE, 'mt_profile_on%s.json' % a.suffix)
    with open(dst, 'w', encoding='utf-8') as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print('saved', dst)
    if out.get('errors'):
        print('ERRORS:')
        for e in out['errors']:
            print('  -', e)
    print('frames=%s wall=%.2fs fps_measured=%.2f fps_agent=%s'
          % (out.get('delta_frames'), out.get('wall', 0), out.get('fps_measured', 0),
             out.get('fps_agent_b')))
    print()
    print('%-30s %10s %10s %8s' % ('stage', 'ms/帧', 'us/调用', '调用/帧'))
    for name in MAIN_SEGMENTS:
        v = out['ms_per_frame'].get(name)
        if v is None:
            continue
        u = out['us_per_call'].get(name)
        c = out['calls_delta'].get(name, 0)
        print('%-30s %10.3f %10s %8.2f'
              % (name, v, ('%.1f' % u) if u else '-', c / max(1, out['delta_frames'])))
    extra = [k for k in out['ms_per_frame'] if k not in MAIN_SEGMENTS]
    if extra:
        print('--- 其它插桩段 ---')
        for name in sorted(extra, key=lambda k: -out['ms_per_frame'][k]):
            print('%-30s %10.3f' % (name, out['ms_per_frame'][name]))
    print()
    print('derived:', json.dumps(out['derived'], ensure_ascii=False))
    print('closure:', json.dumps(out['closure'], ensure_ascii=False))
    return 0 if out['closure']['ok'] and out.get('delta_frames', 0) > 0 else 1


if __name__ == '__main__':
    sys.exit(main())
