# -*- coding: utf-8 -*-
"""compiled_verify.py — 编译版同设置实测 (2026-09-06 用户指令; B2 后单档)

对编译版 exe (带 --agent 启动) 采集:
  1. 编辑器态 500混合: fps (腰斩复查: 历史编译 33 vs 源码 60)
  2. 播放态 30s: fps/tps/帧长std + 缓冲命中 (同源码版 A 轮口径)
  3. full_op_sweep 巡检脚本复用 (对编译版端口跑全功能)

★B2 退役 (2026-10-16): 原为 on/off A/B (--on/--off/--both); B2 后 pipeline 无
Python 回退路径, 探针改单档 on。--both 参数保留兼容 build_all.bat, 内部只跑 on,
[GATE-FPS] 判据从「on ≥ off」改为绝对阈值 COMPILED_MIN_FPS。
  * 落盘:
      tests/_tmp/compiled_verify_on.json
      tests/_tmp/compiled_verify_ab.json   (--both: 单档 summary + 判据)
    旧 compiled_verify_result.json 只读保留作历史物证, 本脚本不再写入。
  * 缺失不阻塞: exe/场景缺失 → 'SKIP compiled_verify: 编译版产物缺失 (<路径>)' + 退出码 0
  * 等价环境变量入口 (供 build_all.bat 的 :run_check 只转发 %~1 的现状使用):
      LOOM_CV_MODE=on|both    LOOM_CV_STRICT=1

用法:
  py -3.12 tests/_tmp/compiled_verify.py                 # = --on
  py -3.12 tests/_tmp/compiled_verify.py --both [--strict-fps]

退出码:
  0  采集有效 (默认: 判据不通过也返回 0, 仅打印 [GATE-FPS] ... FAIL)
  1  采集无效 (启动失败/端口超时/采集异常), 或 --strict-fps 且判据不通过
  SKIP(编译版产物缺失) 恒为 0, 不阻塞 build_all
"""
import json
import os
import subprocess
import sys
import time
import urllib.request
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, '..', '..', '..'))
EXE = os.path.join(ROOT, "Loom(编译版)", "Loom", "Loom.exe")
SCENE = os.path.join(ROOT, "Loom(编译版)", "Loom", "保存", "压测500混合.json")
PORT_JSON = os.path.join(os.path.dirname(EXE), ".agent_port.json")
OUT_ON = os.path.join(HERE, "compiled_verify_on.json")
# ★B2 退役 (2026-10-16): OUT_OFF 已无 off 档消费者, 删。
OUT_AB = os.path.join(HERE, "compiled_verify_ab.json")
# 旧产物 compiled_verify_result.json / compiled_verify_off.json: 只读历史物证, 严禁再写入
PORT_WAIT_S = 40.0
SETTLE_S = 8.0          # 启动后稳定期
EDIT_SAMPLES = 6        # 编辑器态采样点数
EDIT_INTERVAL_S = 2.0   # → 12s 编辑器态窗口
PLAY_S = 30.0           # 播放态窗口 (与源码 A 轮同口径)
PLAY_INTERVAL_S = 2.0
# ★B2 退役 (2026-10-16): 原 A/B 闸 = ON fps_mean >= OFF fps_mean; B2 后无 off 对照,
# 改绝对阈值。历史编译版播放态 160~162+ FPS (台账), 留 ~25% 余量防严重回归。
COMPILED_MIN_FPS = 120.0


def now_iso():
    """本地时区 ISO8601 时间戳 (带偏移, 便于物证比对)"""
    return datetime.now().astimezone().isoformat(timespec='seconds')


def iso_from_ts(ts):
    """文件 mtime → ISO8601"""
    return datetime.fromtimestamp(ts).astimezone().isoformat(timespec='seconds')


def parse_args(argv):
    """★B2 退役 (2026-10-16): 删 --off; --on(默认) / --both(兼容, 内部单档) / --strict-fps"""
    mode = None
    strict = False
    for a in argv:
        if a == '--on':
            mode = 'on'
        elif a == '--both':
            mode = 'both'
        elif a == '--strict-fps':
            strict = True
        elif a in ('-h', '--help'):
            print(__doc__, flush=True)
            raise SystemExit(0)
        else:
            print('[args] 未知参数: %s (支持 --on / --both / --strict-fps)'
                  % a, flush=True)
            raise SystemExit(2)
    if mode is None:
        # build_all.bat 的 :run_check 只转发 %~1, 多余参数会被吞掉;
        # 故额外支持 LOOM_CV_MODE / LOOM_CV_STRICT 环境变量作为等价入口
        # (argv 优先, 两者不冲突)
        mode = (os.environ.get('LOOM_CV_MODE') or 'on').strip().lower()
        if mode not in ('on', 'both'):
            mode = 'on'
    if not strict:
        strict = ((os.environ.get('LOOM_CV_STRICT') or '').strip().lower()
                  not in ('', '0', 'false', 'no'))
    return mode, strict


def preflight():
    """编译版产物缺失 → SKIP + 退出码 0 (不阻塞 build_all)"""
    for p in (EXE, SCENE):
        if not os.path.exists(p):
            print('SKIP compiled_verify: 编译版产物缺失 (%s)' % p, flush=True)
            raise SystemExit(0)


def exe_stamp():
    """产物指纹: 大小 + mtime (证明物证对应哪个 exe)"""
    try:
        st = os.stat(EXE)
        return st.st_size, iso_from_ts(st.st_mtime)
    except Exception:
        return None, None


def make_caller(port, token):
    """agent 端口调用闭包 (原样保留原探针协议)"""
    def call(c, a=None):
        body = json.dumps({'cmd': c, 'args': a or {}}).encode('utf-8')
        req = urllib.request.Request(
            'http://127.0.0.1:%d/cmd' % port, data=body, method='POST',
            headers={'X-Agent-Token': token, 'Content-Type': 'application/json'})
        with urllib.request.urlopen(req, timeout=35) as r:
            return json.loads(r.read().decode('utf-8')).get('result', {})
    return call


def wait_port(proc):
    """等 .agent_port.json 就绪 (须 pid 匹配, 忽略上一次残留)"""
    t0 = time.time()
    while time.time() - t0 < PORT_WAIT_S:
        try:
            with open(PORT_JSON, encoding='utf-8') as f:
                cand = json.load(f)
            if cand.get('pid') == proc.pid and cand.get('port'):
                return cand
        except Exception:
            pass
        if proc.poll() is not None:      # 进程已退出, 再等无意义
            return None
        time.sleep(0.5)
    return None


def summarize(play):
    """播放态汇总 (与源码 A 轮口径一致)"""
    fps = [s['fps'] for s in play if s['fps']]
    tps = [s['tps'] for s in play if s['tps']]
    std = [s['std'] for s in play if s['std']]
    return {
        'fps_mean': round(sum(fps) / len(fps), 1) if fps else None,
        'fps_min': min(fps) if fps else None,
        'tps_mean': round(sum(tps) / len(tps), 2) if tps else None,
        'jit_std_mean': round(sum(std) / len(std), 2) if std else None,
        'fb_prefetch_max': max((s['fb_pref'] for s in play), default=0),
    }


def save_json(path, obj):
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(obj, f, ensure_ascii=False, indent=2, default=str)
    print('[dump]', path, flush=True)


def collect():
    """跑一次编译版采集; 返回 (result dict | None, ok)

    ★B2 退役 (2026-10-16): 删 off (LOOM_NO_PIPELINE=1) 档, 单档 on。
    """
    env = dict(os.environ)
    env['LOOM_PROFILE'] = '1'          # 阶段耗时插桩 (stage_times 进 engine_metrics)
    cmd = [EXE, '--open', SCENE, '--agent']
    print('[launch] cmd=%s' % cmd, flush=True)

    try:
        proc = subprocess.Popen(cmd, cwd=os.path.dirname(EXE), env=env)
    except Exception as e:
        print('FAILED compiled_verify: 启动失败 (%s: %s)'
              % (type(e).__name__, e), flush=True)
        return None, False

    call = None
    try:
        info = wait_port(proc)
        if info is None:
            print('FAILED compiled_verify: 端口文件 %ds 未就绪 (存在但采集失败)'
                  % int(PORT_WAIT_S), flush=True)
            return None, False
        port, token = info['port'], info['token']
        call = make_caller(port, token)
        print('[agent] port=%d' % port, flush=True)

        size, mtime = exe_stamp()
        results = {
            'ts': now_iso(),
            'exe': EXE,
            'exe_size': size,
            'exe_mtime': mtime,
            'env_LOOM_NO_PIPELINE': ('LOOM_NO_PIPELINE' in env),
            'scene': SCENE,
            'agent_port': port,
        }

        # ---- 编辑器态 (腰斩复查关键窗口) ----
        time.sleep(SETTLE_S)
        st = call('status')
        results['edit_models'] = len(st.get('models', []))
        results['edit_fps_samples'] = []
        for _ in range(EDIT_SAMPLES):          # 12s 编辑器态采样
            m = call('engine_metrics', {})
            results['edit_fps_samples'].append(m.get('fps'))
            time.sleep(EDIT_INTERVAL_S)
        print('[edit] models=%d fps_samples=%s'
              % (results['edit_models'], results['edit_fps_samples']),
              flush=True)

        # ---- 播放态 30s (与源码 A 轮同口径) ----
        call('play', {'on': True})
        time.sleep(6.0)
        play = []
        t0 = time.time()
        stage_snap = None
        while time.time() - t0 < PLAY_S:
            m = call('engine_metrics', {})
            j = m.get('get_frame_jitter') or [0, 0, 0]
            fb = m.get('frame_buffer') or {}
            play.append({'fps': m.get('fps'), 'tps': m.get('get_tps'),
                         'std': j[0], 'max': j[1],
                         'fb_hits': fb.get('hits') or 0,
                         'fb_pref': fb.get('prefetches') or 0})
            stage_snap = m.get('stage_times')     # 最后一次快照 (累计 ms)
            time.sleep(PLAY_INTERVAL_S)
        results['play_samples'] = play
        results['stage_times'] = stage_snap
        results['play_summary'] = summarize(play)
        print('[play summary]', json.dumps(results['play_summary']),
              flush=True)
        call('screenshot', {'file': os.path.join(HERE, 'compiled_play_on.png'),
                            'full': True})
        return results, True
    except Exception as e:
        print('FAILED compiled_verify: 采集异常 (%s: %s)'
              % (type(e).__name__, e), flush=True)
        return None, False
    finally:
        # 无论成败: quit + 回收进程 (超时 kill), 避免残留实例污染下一档
        if call is not None:
            try:
                call('quit', {'save': 'discard', 'after': 0.2})
            except Exception:
                pass
        try:
            proc.wait(timeout=15)
        except Exception:
            try:
                proc.kill()
                proc.wait(timeout=5)
            except Exception:
                pass


def run_both(strict):
    """★B2 退役 (2026-10-16): 原为 on/off A/B, B2 后无 off 档, 改单档 on +
    绝对 FPS 阈值闸。保留函数名 run_both 以兼容 build_all.bat 的 --both 参数。"""
    r_on, ok_on = collect()
    if ok_on:
        save_json(OUT_ON, r_on)
    else:
        print('[warn] 采集无效, 未落盘 %s (保留旧物证)' % OUT_ON, flush=True)

    on_s = (r_on or {}).get('play_summary') or {}
    on_fps = on_s.get('fps_mean')

    # 判据: 编译版 fps_mean >= COMPILED_MIN_FPS (B2 后绝对阈值)
    gate_pass = bool(ok_on and on_fps is not None and on_fps >= COMPILED_MIN_FPS)
    print('[GATE-FPS] compiled fps_mean=%s  min=%s  -> %s'
          % ('n/a' if on_fps is None else on_fps, COMPILED_MIN_FPS,
             'PASS' if gate_pass else 'FAIL'), flush=True)

    code = 0
    if not ok_on:
        code = 1
    elif strict and not gate_pass:
        code = 1

    size, mtime = exe_stamp()
    ab = {
        'gate': 'B2 后单档: compiled fps_mean >= %s' % COMPILED_MIN_FPS,
        'ts': now_iso(),
        'exe': EXE,
        'exe_size': size,
        'exe_mtime': mtime,
        'scene': SCENE,
        'on': {'json': OUT_ON if ok_on else None, 'valid': ok_on,
               'summary': on_s},
        'fps_mean_on': on_fps,
        'criterion': 'fps_mean >= %s' % COMPILED_MIN_FPS,
        'pass': gate_pass,
        'strict_fps': bool(strict),
        'exit_code': code,
    }
    save_json(OUT_AB, ab)
    return code


def main():
    mode, strict = parse_args(sys.argv[1:])
    preflight()
    if mode == 'both':
        raise SystemExit(run_both(strict))
    result, ok = collect()
    if ok:
        save_json(OUT_ON, result)
    else:
        print('[warn] 采集无效, 未落盘 (保留旧物证)', flush=True)
    raise SystemExit(0 if ok else 1)

if __name__ == '__main__':
    main()
