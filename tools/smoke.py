#!/usr/bin/env python
# -*- coding: utf-8 -*-
r"""tools/smoke.py — 冒烟：只回答一个问题「这个程序能不能跑」。

规则见 docs/design/开发流程_冒烟与验证分层.md：
  * 只做正向；不测异常/回退/降级/阈值
  * 五条检查：能启动 / 能打开场景 / 能播放 / 有性能读数 / 打包产物能起
  * 整轮目标 < 60 秒；红了说明构建坏了，应当阻止打包

用法：
  py -3.13 tools/smoke.py                      # 源码引擎（仓库内 Loom/）
  py -3.13 tools/smoke.py --dist "C:\Program Files\Loom\0.1.0.beta6\Loom"
  py -3.13 tools/smoke.py --scene <绝对场景路径>  # 覆盖默认示例场景
"""
import argparse
import json
import re
import os
import subprocess
import sys
import time
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_SCENE = os.path.join(ROOT, 'examples', 'PacMan2D.json')
BUDGET_S = 60.0


def _post(port, token, cmd, args=None, timeout=20):
    body = {'cmd': cmd}
    if args is not None:
        body['args'] = args
    req = urllib.request.Request(
        'http://127.0.0.1:%d/cmd' % port,
        data=json.dumps(body).encode('utf-8'),
        headers={'Content-Type': 'application/json', 'X-Agent-Token': token},
        method='POST')
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode('utf-8'))


def stamp_build_info(targets):
    """冒烟通过后盖章: build_info.json.smoke_passed_at = now。

    打包脚本要求 smoke_passed_at 存在且晚于 built_at（门序: 编译→冒烟→打包）。
    """
    now = time.strftime('%Y-%m-%d %H:%M:%S')
    for t in targets:
        p = t
        if os.path.isdir(p):
            p = os.path.join(p, 'build_info.json')
        if not os.path.isfile(p):
            print('SMOKE WARN  build_info 不存在，跳过盖章: %s' % p)
            continue
        try:
            with open(p, 'r', encoding='utf-8') as f:
                info = json.load(f)
            info['smoke_passed_at'] = now
            with open(p, 'w', encoding='utf-8') as f:
                json.dump(info, f, ensure_ascii=False, indent=1)
            print('SMOKE STAMP  %s -> smoke_passed_at=%s' % (p, now))
        except Exception as e:
            print('SMOKE WARN  盖章失败 %s: %r' % (p, e))


def check_artifact_meta(engine_dir):
    """[5/5] 编译产物自洽检查（V2-02）：不是复述"能起"，而是查元数据。

    检查: 解释器.json 可读且有 version/python_version；
          build_info.json 可读且 mode=release / git_head 非空 / built_at 可解析；
          若安装目录名形如版本号（.../<x.y.z>/Loom），meta.version 必须与目录名一致。
    返回问题列表（空=通过）。
    """
    problems = []
    meta = bi = None
    try:
        with open(os.path.join(engine_dir, '解释器.json'), 'r',
                  encoding='utf-8') as f:
            meta = json.load(f)
    except Exception as e:
        problems.append('解释器.json 不可读: %r' % (e,))
    try:
        with open(os.path.join(engine_dir, 'build_info.json'), 'r',
                  encoding='utf-8') as f:
            bi = json.load(f)
    except Exception as e:
        problems.append('build_info.json 不可读: %r' % (e,))
    if meta is not None:
        v = str(meta.get('version') or '').strip()
        pyv = str(meta.get('python_version') or '').strip()
        if not v:
            problems.append('解释器.json 缺 version')
        if not pyv:
            problems.append('解释器.json 缺 python_version')
        parent = os.path.basename(os.path.dirname(os.path.abspath(engine_dir)))
        if re.match(r'^\d+\.\d+\.\d+(\.beta\d+)?$', parent or '') and v and v != parent:
            problems.append('解释器.json version=%r 与安装目录名 %r 不一致'
                            % (v, parent))
    if bi is not None:
        if bi.get('mode') != 'release':
            problems.append('build_info.mode=%r（应为 release）' % (bi.get('mode'),))
        if not str(bi.get('git_head') or '').strip():
            problems.append('build_info 缺 git_head')
        try:
            time.strptime(str(bi.get('built_at')), '%Y-%m-%d %H:%M:%S')
        except Exception:
            problems.append('build_info.built_at 非法: %r' % (bi.get('built_at'),))
    return problems


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument('--dist', help='编译版引擎目录（含 Loom.exe）；不给则跑源码版')
    ap.add_argument('--scene', help='场景路径（默认 examples/PacMan2D.json）')
    ap.add_argument('--seconds', type=float, default=2.5, help='播放时长（默认 2.5s）')
    ap.add_argument('--budget', type=float, default=None,
                    help='耗时预算秒（默认 %s；超预算默认判失败）' % BUDGET_S)
    ap.add_argument('--allow-slow', action='store_true',
                    help='超预算只告警不判失败（默认失败）')
    ap.add_argument('--stamp', action='append', default=[],
                    help='冒烟通过后给 build_info.json 盖 smoke_passed_at '
                         '（可多次；目录或文件）')
    a = ap.parse_args(argv)

    t0 = time.time()
    scene = os.path.abspath(a.scene or DEFAULT_SCENE)
    if not os.path.isfile(scene):
        print('SMOKE FAIL  场景不存在: %s' % scene)
        return 1

    if a.dist:
        engine_dir = os.path.abspath(a.dist)
        exe = os.path.join(engine_dir, 'Loom.exe')
        if not os.path.isfile(exe):
            print('SMOKE FAIL  找不到 %s' % exe)
            return 1
        cmd = [exe, '--agent', '--open', scene]
    else:
        engine_dir = os.path.join(ROOT, 'Loom')
        cmd = [sys.executable, os.path.join(engine_dir, 'Loom.py'),
               '--agent', '--open', scene]

    port_file = os.path.join(engine_dir, '.agent_port.json')
    if os.path.isfile(port_file):
        try:
            os.remove(port_file)
        except OSError:
            pass

    env = dict(os.environ)
    env['LOOM_NO_DIALOG'] = '1'      # 批量执行不得弹阻塞框
    env.pop('LOOM_POST', None)          # 冒烟只测默认姿态
    proc = subprocess.Popen(cmd, cwd=engine_dir, env=env,
                            stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)

    fails = []

    # 1) 能启动（拿到 agent 端口 + 进程活着）
    deadline = time.time() + 60
    while time.time() < deadline:
        if os.path.isfile(port_file) and proc.poll() is None:
            break
        if proc.poll() is not None:
            break
        time.sleep(0.3)
    if proc.poll() is not None or not os.path.isfile(port_file):
        err = ''
        try:
            err = (proc.stderr.read() or b'').decode('utf-8', 'replace')[-400:]
        except Exception:
            pass
        print('SMOKE FAIL  [1/5] 起不来（exit=%s）%s' % (proc.poll(), err))
        return 1
    info = json.loads(open(port_file, encoding='utf-8').read())
    print('SMOKE PASS  [1/5] 能启动（pid=%s）' % proc.pid)

    try:
        # 2) 能打开场景（models > 0）
        st = _post(info['port'], info['token'], 'status').get('result') or {}
        models = st.get('models') or []
        if len(models) > 0:
            print('SMOKE PASS  [2/5] 场景已加载（models=%d）' % len(models))
        else:
            fails.append('[2/5] 场景模型数为 0')

        # 3) 能播放（持续 seconds 不崩）
        _post(info['port'], info['token'], 'play', {'on': True})
        time.sleep(a.seconds)
        alive = proc.poll() is None
        play_st = _post(info['port'], info['token'], 'status').get('result') or {}
        if alive and play_st.get('playing'):
            print('SMOKE PASS  [3/5] 能播放 %.1fs' % a.seconds)
        else:
            fails.append('[3/5] 播放期间崩溃或未进入播放态')

        # 4) 有性能读数（不判阈值）
        m = _post(info['port'], info['token'], 'engine_metrics').get('result') or {}
        fps = float(m.get('fps') or 0)
        tps = float(m.get('get_tps') or m.get('tps') or 0)   # 命令里字段名是 get_tps
        if fps > 0 and tps > 0:
            print('SMOKE PASS  [4/5] 有读数（fps=%.1f tps=%.2f）' % (fps, tps))
        else:
            fails.append('[4/5] 没有 fps/tps 读数')

        _post(info['port'], info['token'], 'play', {'on': False})
    finally:
        try:
            proc.terminate()
            proc.wait(timeout=8)
        except Exception:
            proc.kill()

    # 5) 产物自洽（V2-02）：不再只复述 [1/5]，真查 解释器.json / build_info.json
    if proc.poll() is None:
        fails.append('[5/5] 退出后进程仍在')
    if a.dist:
        meta_bad = check_artifact_meta(engine_dir)
        if meta_bad:
            for p in meta_bad:
                fails.append('[5/5] ' + p)
            print('SMOKE FAIL  [5/5] 产物元数据不自洽：%s' % '；'.join(meta_bad))
        else:
            print('SMOKE PASS  [5/5] 产物元数据自洽'
                  '（解释器.json / build_info.json）')
    else:
        print('SMOKE SKIP  [5/5] 源码模式无编译产物可查')

    dt = time.time() - t0
    budget = a.budget if a.budget is not None else BUDGET_S
    if dt > budget:
        if a.allow_slow:
            print('  ! 超出预算（%.1fs > %.0fs）：--allow-slow 放行' % (dt, budget))
        else:
            fails.append('[预算] 冒烟耗时 %.1fs 超过 %.0fs（用 --allow-slow 放行）'
                         % (dt, budget))
    print('SMOKE %s  用时 %.1fs（预算 %.0fs）'
          % ('FAIL' if fails else 'OK', dt, budget))
    for f in fails:
        print('  - ' + f)
    if not fails:
        targets = list(a.stamp)
        if a.dist:
            targets.append(engine_dir)
        if targets:
            stamp_build_info(targets)
    return 1 if fails else 0


if __name__ == '__main__':
    sys.exit(main())
