#!/usr/bin/env python
# -*- coding: utf-8 -*-
r"""tools/smoke.py — 冒烟：只回答一个问题「这个程序能不能跑」。

规则见 docs/design/开发流程_冒烟与验证分层.md：
  * 只做正向；不测异常/回退/降级/阈值
  * 七条检查：能启动 / 能打开场景 / 能播放 / 有性能读数 / 产物元数据自洽 /
    构建器可执行 / 运行时最小启动
  * 整轮目标 < 60 秒；超预算默认判失败（--allow-slow 放行）
  * --stamp 只给"本次真正测过且通过"的产物盖 smoke_passed_at：
    引擎跑全流程才盖引擎；构建器/运行时只有真跑过才盖；不跑不盖

用法：
  py -3.13 tools/smoke.py                      # 源码引擎（仓库内 Loom/）
  py -3.13 tools/smoke.py --dist "C:\Program Files\Loom\0.1.0.beta6\Loom"
  py -3.13 tools/smoke.py --scene <绝对场景路径>  # 覆盖默认示例场景
"""
import argparse
import json
import re
import os
import shutil
import subprocess
import sys
import tempfile
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


def find_builder(engine_dir, explicit=None):
    """构建器 exe：显式指定优先；否则在 dist 同目录/上级找 build_game.exe。"""
    if explicit:
        return explicit if os.path.isfile(explicit) else None
    for cand in (engine_dir, os.path.dirname(os.path.abspath(engine_dir))):
        p = os.path.join(cand, 'build_game.exe')
        if os.path.isfile(p):
            return p
    return None


def check_builder(exe):
    """构建器能不能跑：--help 必须 exit 0（崩了的构建器冒烟必须抓到）。"""
    try:
        r = subprocess.run([exe, '--help'], stdout=subprocess.DEVNULL,
                           stderr=subprocess.DEVNULL, timeout=30)
        return r.returncode == 0, 'exit=%s' % r.returncode
    except Exception as e:
        return False, repr(e)


def find_runtime(engine_dir, explicit=None):
    """运行时 dist：显式优先；否则找 player_runtime/game_player.dist（包内或仓库内）。"""
    if explicit:
        return explicit if os.path.isfile(
            os.path.join(explicit, 'MyGame.exe')) else None
    for cand in (os.path.join(engine_dir, 'player_runtime', 'game_player.dist'),
                 os.path.join(os.path.dirname(os.path.abspath(engine_dir)),
                              'player_runtime', 'game_player.dist'),
                 os.path.join(ROOT, 'Loom', 'player_runtime',
                              'game_player.dist')):
        if os.path.isfile(os.path.join(cand, 'MyGame.exe')):
            return cand
    return None


def check_runtime(dist):
    """运行时最小启动：无 游戏包.lsc 时预期 exit 1（能起但不进游戏），0 也算能起；
    >=2 或超时视为失败。"""
    exe = os.path.join(dist, 'MyGame.exe')
    try:
        p = subprocess.Popen([exe], cwd=dist, stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL)
    except Exception as e:
        return False, repr(e)
    try:
        rc = p.wait(timeout=25)
    except subprocess.TimeoutExpired:
        p.kill()
        return False, '启动超时(25s)'
    return rc in (0, 1), 'exit=%s' % rc


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
    ap.add_argument('--stamp', action='store_true',
                    help='给"本次真正被测过且通过"的产物盖 smoke_passed_at'
                         '（引擎/构建器/运行时分别实测才分别盖）')
    ap.add_argument('--builder-exe', help='构建器 exe（默认在 dist 同目录/上级找 build_game.exe）')
    ap.add_argument('--runtime-dist', help='运行时 dist（默认找 player_runtime/game_player.dist）')
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
        print('SMOKE FAIL  [1/7] 起不来（exit=%s）%s' % (proc.poll(), err))
        return 1
    info = json.loads(open(port_file, encoding='utf-8').read())
    print('SMOKE PASS  [1/7] 能启动（pid=%s）' % proc.pid)

    try:
        # 2) 能打开场景（models > 0）
        st = _post(info['port'], info['token'], 'status').get('result') or {}
        models = st.get('models') or []
        if len(models) > 0:
            print('SMOKE PASS  [2/7] 场景已加载（models=%d）' % len(models))
        else:
            fails.append('[2/7] 场景模型数为 0')

        # 3) 能播放（持续 seconds 不崩）
        _post(info['port'], info['token'], 'play', {'on': True})
        time.sleep(a.seconds)
        alive = proc.poll() is None
        play_st = _post(info['port'], info['token'], 'status').get('result') or {}
        if alive and play_st.get('playing'):
            print('SMOKE PASS  [3/7] 能播放 %.1fs' % a.seconds)
        else:
            fails.append('[3/7] 播放期间崩溃或未进入播放态')

        # 4) 有性能读数（不判阈值）
        m = _post(info['port'], info['token'], 'engine_metrics').get('result') or {}
        fps = float(m.get('fps') or 0)
        tps = float(m.get('get_tps') or m.get('tps') or 0)   # 命令里字段名是 get_tps
        if fps > 0 and tps > 0:
            print('SMOKE PASS  [4/7] 有读数（fps=%.1f tps=%.2f）' % (fps, tps))
        else:
            fails.append('[4/7] 没有 fps/tps 读数')

        _post(info['port'], info['token'], 'play', {'on': False})
    finally:
        try:
            proc.terminate()
            proc.wait(timeout=8)
        except Exception:
            proc.kill()

    # 5) 产物自洽（V2-02）：不再只复述 [1/5]，真查 解释器.json / build_info.json
    if proc.poll() is None:
        fails.append('[5/7] 退出后进程仍在')
    engine_ok = False
    if a.dist:
        meta_bad = check_artifact_meta(engine_dir)
        if meta_bad:
            for p in meta_bad:
                fails.append('[5/7] ' + p)
            print('SMOKE FAIL  [5/7] 产物元数据不自洽：%s' % '；'.join(meta_bad))
        else:
            engine_ok = True
            print('SMOKE PASS  [5/7] 产物元数据自洽'
                  '（解释器.json / build_info.json）')
    else:
        print('SMOKE SKIP  [5/7] 源码模式无编译产物可查')

    # 6/7 构建器: 同目录/上级有 build_game.exe 就真跑 --help（构建器崩了冒烟要能抓到）
    builder_exe = find_builder(engine_dir, a.builder_exe) if a.dist else None
    builder_ok = False
    if a.dist and a.builder_exe and not builder_exe:
        fails.append('[6/7] 指定的 --builder-exe 不存在: %s' % a.builder_exe)
        print('SMOKE FAIL  [6/7] --builder-exe 不存在')
    elif builder_exe:
        ok, why = check_builder(builder_exe)
        if ok:
            builder_ok = True
            print('SMOKE PASS  [6/7] 构建器可执行（%s, %s）'
                  % (os.path.basename(builder_exe), why))
        else:
            fails.append('[6/7] 构建器 --help 失败（%s）' % why)
            print('SMOKE FAIL  [6/7] 构建器 --help 失败（%s）' % why)
    else:
        print('SMOKE SKIP  [6/7] 未找到 build_game.exe（构建器检查不适用）')

    # 7/7 运行时: 有 player_runtime/game_player.dist 就真起一次（缺包 exit 1 也算能起）
    runtime_dist = find_runtime(engine_dir, a.runtime_dist) if a.dist else None
    runtime_ok = False
    if a.dist and a.runtime_dist and not runtime_dist:
        fails.append('[7/7] 指定的 --runtime-dist 无效: %s' % a.runtime_dist)
        print('SMOKE FAIL  [7/7] --runtime-dist 无效')
    elif runtime_dist:
        ok, why = check_runtime(runtime_dist)
        if ok:
            runtime_ok = True
            print('SMOKE PASS  [7/7] 运行时最小启动（%s, %s）'
                  % (os.path.basename(runtime_dist), why))
        else:
            fails.append('[7/7] 运行时启动失败（%s）' % why)
            print('SMOKE FAIL  [7/7] 运行时启动失败（%s）' % why)
    else:
        print('SMOKE SKIP  [7/7] 未找到 player_runtime/game_player.dist')

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
    # 盖章规则（V2-02 修订）: 只盖"本次真正被测过且通过"的产物。
    # 引擎跑 agent 全流程通过 -> 盖 engine_dir；构建器/运行时只有真跑过才盖；
    # 要盖三件，smoke 必须真的逐个测（本函数已逐个启动）。
    if a.stamp and not fails:
        targets = []
        _engine_bi = os.path.abspath(os.path.join(engine_dir, 'build_info.json'))
        if engine_ok:
            targets.append(engine_dir)
        if builder_ok:
            _bdir = os.path.dirname(os.path.abspath(builder_exe))
            if os.path.abspath(os.path.join(_bdir, 'build_info.json')) == _engine_bi:
                print('SMOKE WARN  构建器与引擎共用 build_info.json，跳过重复盖章')
            else:
                targets.append(_bdir)
        if runtime_ok:
            targets.append(runtime_dist)
        if targets:
            stamp_build_info(targets)
        else:
            print('SMOKE WARN  --stamp 但没有任何产物被测通过，未盖章')
    return 1 if fails else 0


if __name__ == '__main__':
    sys.exit(main())
