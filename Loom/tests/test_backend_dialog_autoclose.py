# -*- coding: utf-8 -*-
"""test_backend_dialog_autoclose.py — 门：show_blocking_dialog 的「可选自动关闭」能力（人类 2026-11-27）。

人类原话: 「很多测试流程都会弹出一个不会自动关闭的窗口，需要人手动关掉……不会自动关闭。」

背景契约（本门锁三件事）：
  ① **产品默认行为不变**：不设任何环境变量时，弹窗**必须真弹并阻塞**（真实用户照旧要看见、
     要手动点）—— 实测口径：外部 3s 才关，函数必须阻塞到那时（elapsed >= 2.5s）；
  ② LOOM_NO_DIALOG=1：立即返回 False、不弹窗（测试/无头语义，与既有行为一致）；
  ③ LOOM_DIALOG_AUTO_CLOSE_MS=<毫秒>：真弹 + 到点自动关（无人值守兜底），函数在 ~N ms 返回
     True，且进程 stdout 有「N ms 后自动关闭弹窗」自证行。
另：非法取值（非整数）不得让弹窗消失或崩 —— 只打印忽略并保持默认阻塞行为。

为什么用子进程：默认分支**就是**要证明它会阻塞等人点 —— 在本进程里会挂住整条 run_all。
子探针 = tests/_dialog_case_child.py（下划线前缀，run_all 不收集）。
无交互桌面/无 user32 时如实 SKIP（不假绿）。
"""
import ctypes
import ctypes.wintypes as wt
import json
import os
import subprocess
import sys
import threading
import time

try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
CHILD = os.path.join(HERE, '_dialog_case_child.py')

os.environ['LOOM_NO_DIALOG'] = '1'          # 父门自身绝不允许弹窗
os.environ.setdefault('PYTHONIOENCODING', 'utf-8')

_fails = []
_pass_n = 0
_skips = []


class _FailGateStream:
    def __init__(self, stream):
        self._stream = stream
        self.failed = False

    def write(self, text):
        if isinstance(text, str) and (text.startswith('FAIL') or '\nFAIL' in text):
            self.failed = True
        return self._stream.write(text)

    def __getattr__(self, name):
        return getattr(self._stream, name)


_gate = _FailGateStream(sys.stdout)
sys.stdout = _gate


def check(name, cond, detail=''):
    global _pass_n
    print(('PASS ' if cond else 'FAIL ') + name + ('  ' + str(detail) if detail else ''))
    if cond:
        _pass_n += 1
    else:
        _fails.append(name)


def skip(name, why):
    print('SKIP ' + name + '  ' + str(why))
    _skips.append(name)


def desktop_available():
    try:
        user32 = ctypes.windll.user32
    except Exception as e:
        return False, '无 user32 (%r)' % (e,)
    try:
        if user32.GetSystemMetrics(0) <= 0 or user32.GetSystemMetrics(1) <= 0:
            return False, '无交互桌面（屏幕尺寸为 0，服务态/无头会话）'
    except Exception as e:
        return False, 'GetSystemMetrics 失败 (%r)' % (e,)
    return True, ''


def close_dialog_after(seconds, title_prefix):
    """外部「人」：到点关掉标题前缀匹配的对话框（证明默认分支没有自动关）。"""
    def _run():
        time.sleep(seconds)
        try:
            user32 = ctypes.windll.user32
            hits = []

            def _cb(hwnd, _l):
                try:
                    if not user32.IsWindowVisible(hwnd):
                        return True
                    cb = ctypes.create_unicode_buffer(64)
                    user32.GetClassNameW(hwnd, cb, 64)
                    if cb.value != '#32770':
                        return True
                    tb = ctypes.create_unicode_buffer(256)
                    user32.GetWindowTextW(hwnd, tb, 256)
                    if not tb.value.startswith(title_prefix):
                        return True
                    hits.append(hwnd)
                except Exception:
                    pass
                return True

            user32.EnumWindows(
                ctypes.WINFUNCTYPE(ctypes.c_bool, wt.HWND, wt.LPARAM)(_cb), 0)
            for hwnd in hits:
                user32.PostMessageW(hwnd, 0x0010, 0, 0)      # WM_CLOSE
        except Exception:
            pass

    th = threading.Thread(target=_run, daemon=True)
    th.start()
    return th


def run_case(case, closer_after=0.0, timeout_s=60):
    """跑一个子探针 case，返回 (rc, out, elapsed_wall)。"""
    env = dict(os.environ)
    env.pop('LOOM_NO_DIALOG', None)         # 子探针自己按 case 设（它第一行就清空）
    env.pop('LOOM_DIALOG_AUTO_CLOSE_MS', None)
    env.setdefault('PYTHONIOENCODING', 'utf-8')
    t0 = time.monotonic()
    proc = subprocess.Popen([sys.executable, CHILD, case], cwd=ROOT, env=env,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            encoding='utf-8', errors='replace')
    if closer_after > 0:
        close_dialog_after(closer_after, 'AUTOCLOSE-CASE-' + case)
    try:
        out = proc.communicate(timeout=timeout_s)[0] or ''
    except subprocess.TimeoutExpired:
        try:
            proc.kill()
        except Exception:
            pass
        out = ''
    return proc.poll(), out, time.monotonic() - t0


def parse(out):
    for line in (out or '').splitlines():
        if line.startswith('RESULT '):
            try:
                return json.loads(line[len('RESULT '):])
            except ValueError:
                return None
    return None


def main():
    print('=== show_blocking_dialog 可选自动关闭门（人类 2026-11-27 反馈） ===')
    ok, why = desktop_available()
    if not ok:
        skip('全部门', why)
        print()
        print('总结果: SKIP（%d 项）—— 本环境无法验证弹窗行为' % len(_skips))
        sys.exit(0)

    # ---- A. LOOM_NO_DIALOG=1：立即返回 False，不弹窗 ----
    rc, out, dt = run_case('no_dialog', timeout_s=30)
    r = parse(out)
    check('A1 LOOM_NO_DIALOG=1：立即返回 False（不阻塞、不弹）',
          r is not None and r.get('shown') is False and r.get('elapsed', 99) < 1.0,
          'rc=%s result=%r' % (rc, r))
    check('A2 LOOM_NO_DIALOG=1：子进程快速退出（无窗口待关）', rc == 0 and dt < 5.0,
          'rc=%s wall=%.1fs' % (rc, dt))

    # ---- B. 默认（两个开关都不设）：必须真弹 + 阻塞到外部去点（产品行为不变）----
    rc, out, dt = run_case('default', closer_after=3.0, timeout_s=30)
    r = parse(out)
    check('B1 默认不设开关：**真弹**（shown=True，不是静默降级）',
          r is not None and r.get('shown') is True, 'rc=%s result=%r' % (rc, r))
    check('B2 默认不设开关：弹窗**不会自动关**（外部 3s 才点掉 -> elapsed >= 2.5s）',
          r is not None and r.get('elapsed', 0) >= 2.5,
          'elapsed=%r（若这里变小=有人把默认行为改成自动关，真实用户会错过原因）'
          % ((r or {}).get('elapsed'),))
    check('B3 默认不设开关：没有自动关闭自证行（证明 auto-close 没被误开启）',
          '[backend]' not in out or '自动关闭' not in out, out.strip()[-120:])

    # ---- C. LOOM_DIALOG_AUTO_CLOSE_MS=1500：真弹 + 到点自动关 ----
    rc, out, dt = run_case('auto_close', timeout_s=30)
    r = parse(out)
    check('C1 设了自动关闭：**真弹**（shown=True）',
          r is not None and r.get('shown') is True, 'rc=%s result=%r' % (rc, r))
    check('C2 设了自动关闭：约 1.5s 后自动关（1.2s <= elapsed <= 8s）',
          r is not None and 1.2 <= r.get('elapsed', -1) <= 8.0,
          'elapsed=%r' % ((r or {}).get('elapsed'),))
    check('C3 自动关闭有 stdout 自证（[backend] ... 后自动关闭弹窗）',
          ('[backend]' in out) and ('自动关闭弹窗' in out),
          [ln for ln in out.splitlines() if '自动关闭' in ln][:2])
    check('C4 自动关闭后子进程正常退出（不留僵尸）', rc == 0 and dt < 15.0,
          'rc=%s wall=%.1fs' % (rc, dt))

    # ---- D. 非法取值：不静默丢掉弹窗，只打印忽略并保持默认阻塞 ----
    rc, out, dt = run_case('bad_value', closer_after=3.0, timeout_s=30)
    r = parse(out)
    check('D1 非法 LOOM_DIALOG_AUTO_CLOSE_MS：仍真弹（不因配置脏而静默）',
          r is not None and r.get('shown') is True, 'rc=%s result=%r' % (rc, r))
    check('D2 非法取值被打印忽略（不崩溃、不假装自动关）',
          '忽略非法' in out and r is not None and r.get('elapsed', 0) >= 2.5,
          [(r or {}).get('elapsed'), [ln for ln in out.splitlines() if '忽略非法' in ln][:1]])

    print()
    if _fails:
        print('总结果: FAIL（%d 条）' % len(_fails))
        print('FAIL test_backend_dialog_autoclose: %s' % (_fails,))
        try:
            sys.stdout.flush()
        except Exception:
            pass
        sys.exit(1)
    print('总结果: ALL PASS（%d 条；SKIP %d 条）' % (_pass_n, len(_skips)))
    print('PASS test_backend_dialog_autoclose: 默认行为不变 + 自动关闭能力可用')


main()