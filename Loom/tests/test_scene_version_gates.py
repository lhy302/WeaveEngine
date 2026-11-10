# -*- coding: utf-8 -*-
# test_scene_version_gates.py — 版本闸的**入口一致性**（R6-03 缺口 1/2，2026-11-11）
#
# 覆盖：
#   E. 编译版入口 `build_entry.py --run <高版本场景>`（直连 PlayerApp，不走 run_player）
#      也必须：弹窗口径（LOOM_NO_DIALOG=1 时只打印）+ 原因含要求/当前版本 + 非 0，且无 traceback。
#   F. 远程回读窗口（LOOM_REMOTE_MODE=on）的版本失败：关窗 + 可见原因 + 非 0 退出（不留白窗）。
#
# 这两条都是「入口没有走 run_player」的历史缺口；G 类真实子进程调用放在同文件末尾。
import os
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
os.environ['LOOM_NO_DIALOG'] = '1'
os.environ.setdefault('LOOM_NO_PARALLEL', '1')
os.environ['LOOM_NO_SAVE_MIGRATE'] = '1'

_fails = []


def check(name, cond, detail=''):
    print(('PASS ' if cond else 'FAIL ') + name + ('  ' + str(detail) if detail else ''))
    if not cond:
        _fails.append(name)


def _newer_scene_file(tmp):
    import json
    p = os.path.join(tmp, 'newer.json')
    with open(p, 'w', encoding='utf-8') as f:
        json.dump({'version': 11, 'min_engine_version': '99.0.0', 'objects': [],
                   'lights': [], 'materials': [], 'cameras': [],
                   'active_camera': None}, f)
    return p


def _run_entry(args, timeout=90):
    env = dict(os.environ)
    env['LOOM_NO_DIALOG'] = '1'
    env.pop('LOOM_POST', None)
    p = subprocess.run([sys.executable] + args, cwd=ROOT, capture_output=True,
                       text=True, encoding='utf-8', errors='replace',
                       timeout=timeout, env=env)
    return p.returncode, (p.stdout or ''), (p.stderr or '')


def t_build_entry_run(tmp):
    print('=== E. build_entry.py --run（编译版 --run 同一入口） ===')
    scene = _newer_scene_file(tmp)
    try:
        rc, out, err = _run_entry([os.path.join(ROOT, 'build_entry.py'), '--run', scene])
    except subprocess.TimeoutExpired:
        check('E1 --run 高版本场景能自行退出（不挂起）', False, 'timeout')
        return
    blob = out + err
    check('E1 --run 高版本场景 退出码非 0', rc != 0, rc)
    check('E2 原因含要求版本与当前版本',
          '99.0.0' in blob and ('当前引擎' in blob or '当前' in blob), blob.strip()[-140:])
    check('E3 不产生 Python traceback', 'Traceback' not in blob,
          [l for l in blob.splitlines() if 'Traceback' in l][:2])
    check('E4 走的是版本闸文案（不是通用「无法启动渲染引擎」）',
          '引擎版本' in blob or '要求' in blob, blob.strip()[:80])


def t_remote_window_fatal(tmp):
    print('=== F. 远程回读窗口的版本失败（关窗 + 退出） ===')
    import loom_player_window as PW
    import sceneio
    codes = []
    closed = []
    orig_exit = PW._exit_now
    PW._exit_now = lambda code: codes.append(code)
    class _W:
        def close(self):
            closed.append(True)
    try:
        err = sceneio.SceneVersionError(
            '场景要求引擎 >= 99.0.0, 当前引擎 %s: 拒绝加载' % sceneio.ENGINE_VERSION)
        import contextlib, io as _io
        buf = _io.StringIO()
        with contextlib.redirect_stdout(buf):
            PW._scene_version_fatal(err, widget=_W())
        out = buf.getvalue()
    finally:
        PW._exit_now = orig_exit
    check('F1 非 0 退出（os._exit 被调用一次）', codes == [1], codes)
    check('F2 先关窗（不留空白窗口）', closed == [True], closed)
    check('F3 打印原因含要求/当前版本',
          '99.0.0' in out and '当前引擎' in out, out.strip()[-120:])
    check('F4 无 traceback', 'Traceback' not in out, '')


def t_remote_on_entry(tmp):
    print('=== G. LOOM_REMOTE_MODE=on 真实入口（Loom.py --run） ===')
    scene = _newer_scene_file(tmp)
    env = dict(os.environ)
    env['LOOM_NO_DIALOG'] = '1'
    env['LOOM_REMOTE_MODE'] = 'on'
    t0 = time.time()
    try:
        p = subprocess.run([sys.executable, os.path.join(ROOT, 'Loom.py'),
                            '--run', scene],
                           cwd=ROOT, capture_output=True, text=True,
                           encoding='utf-8', errors='replace', timeout=60, env=env)
    except subprocess.TimeoutExpired:
        check('G1 不残留空白窗口/挂起（60s 内退出）', False, 'timeout')
        return
    blob = (p.stdout or '') + (p.stderr or '')
    check('G1 退出码非 0', p.returncode != 0, p.returncode)
    check('G2 打印要求版本与当前版本',
          '99.0.0' in blob and '当前引擎' in blob, blob.strip()[-120:])
    check('G3 无 traceback', 'Traceback' not in blob, '')
    check('G4 2~30s 内自行退出（不常驻）', 1.0 <= time.time() - t0 <= 30.0,
          '%.1fs' % (time.time() - t0))


def main():
    with tempfile.TemporaryDirectory() as tmp:
        t_build_entry_run(tmp)
        t_remote_window_fatal(tmp)
        t_remote_on_entry(tmp)
    print('=' * 60)
    if _fails:
        print('失败:', _fails)
        return 1
    print('ALL PASS')
    return 0


if __name__ == '__main__':
    sys.exit(main())
