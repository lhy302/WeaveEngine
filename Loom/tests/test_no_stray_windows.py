# -*- coding: utf-8 -*-
"""test_no_stray_windows.py — 门：测试跑完不得在桌面上留下 residual 窗口（人类 2026-11-27 反馈）。

人类原话（本门最高依据）:
  「目前的很多测试流程都会弹出一个不会自动关闭的窗口，需要人手动关掉。例如测试在没有
   VK 驱动的情况下报错并自动退回 GL 的测试，需要人手动关闭窗口，不会自动关闭。还有别的
   很多窗口也是。」

判定标准：跑测试时不允许弹出**需要人工干预**的窗口。解 = 窗口不出现（测试态降级为日志）
或出现但**自动关闭**；不允许「留着等人点」。

本门实测口径（不是读码推断）：
  ① 用 EnumWindows 采样「可见 + 有标题 + 非工具窗」的顶层窗口，记录 (title, class, exe)；
  ② 在子进程里跑一个**已知会开真窗口**的测试；
  ③ 子进程退出瞬间 + 3s 后再采样，差集必须为空（也没有 pid 属于该测试的窗口）；
  ④ 子进程必须真的退出（rc 可得，超时=FAIL）。

样本选择（3 个，覆盖三类真窗口来源，总耗时 ~20s）：
  · test_editor_vk_fallback_panel.py — Qt 真编辑器窗口 + 子进程链 + VK→GL 回退（人类点名的那个）；
  · test_ui_hit_parity.py          — GLFW 真窗口 + 引擎内多窗口；
  · test_vk_camera_align.py        — VK/GL 真窗口矩阵中较快的一条。

环境不可检测时（无交互桌面 / 服务态 / 无 user32）**如实 SKIP 并打印原因**，不假绿。
"""
import ctypes
import ctypes.wintypes as wt
import json
import os
import subprocess
import sys
import tempfile
import time

try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

# 强制测试态（防外部环境把开关污染成 0 —— 实测污染成 0 时 MessageBoxW 会阻塞 200s+）
os.environ['LOOM_NO_DIALOG'] = '1'
os.environ.setdefault('LOOM_DIALOG_AUTO_CLOSE_MS', '8000')
os.environ.setdefault('PYTHONIOENCODING', 'utf-8')

# 每个样本：(文件名, 单测超时秒, 说明)。超时=FAIL（进程不退出本身就是更严重的问题）。
SAMPLES = [
    ('test_editor_vk_fallback_panel.py', 240, 'Qt 真编辑器窗口 + 子进程链（人类点名场景）'),
    ('test_ui_hit_parity.py', 120, 'GLFW 真窗口 + 引擎内多窗口'),
    ('test_vk_camera_align.py', 120, 'VK/GL 真窗口（先 vk 后 gl）'),
]

_fails = []
_pass_n = 0
_skips = []


class _FailGateStream:
    """stdout 里出现 FAIL 行 -> 退出码 1（与其他门的假绿防护同款）。"""

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


# ---------------- 窗口采样（纯 ctypes，零第三方依赖） ----------------
def _proc_exe(pid):
    k32 = ctypes.windll.kernel32
    h = k32.OpenProcess(0x1000, False, pid)      # PROCESS_QUERY_LIMITED_INFORMATION
    if not h:
        return '?'
    try:
        buf = ctypes.create_unicode_buffer(1024)
        size = wt.DWORD(1024)
        if k32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(size)):
            return buf.value.rsplit('\\', 1)[-1]
        return '?'
    finally:
        k32.CloseHandle(h)


def desktop_available():
    """返回 (ok, why)：无交互桌面（服务态/无 user32）时如实 SKIP。"""
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


def snapshot():
    """可见顶层窗口 [(title, cls, exe, pid)]（工具窗/无标题窗不计——它们不打扰人）。"""
    user32 = ctypes.windll.user32
    out = []

    def _cb(hwnd, _l):
        try:
            if not user32.IsWindowVisible(hwnd):
                return True
            if user32.GetWindowLongW(hwnd, -20) & 0x80:      # WS_EX_TOOLWINDOW
                return True
            n = user32.GetWindowTextLengthW(hwnd)
            if n == 0:
                return True
            tb = ctypes.create_unicode_buffer(n + 1)
            user32.GetWindowTextW(hwnd, tb, n + 1)
            cb_ = ctypes.create_unicode_buffer(256)
            user32.GetClassNameW(hwnd, cb_, 256)
            pid = wt.DWORD()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            out.append((tb.value, cb_.value, _proc_exe(pid.value), pid.value))
        except Exception:
            pass
        return True

    user32.EnumWindows(ctypes.WINFUNCTYPE(ctypes.c_bool, wt.HWND, wt.LPARAM)(_cb), 0)
    return out


def keyset(snap):
    # 按 (title, cls, exe) 比：pid 会被系统复用（实测 harness 窗复用了刚死的测试子进程 pid）
    return {(t, c, e) for (t, c, e, _p) in snap}


def run_sample(fname, timeout_s):
    """跑一个样例测试，返回 (rc, timed_out, 新增窗口列表, 该测试 pid 的残留窗口)。"""
    path = os.path.join(HERE, fname)
    env = dict(os.environ)
    env['LOOM_NO_DIALOG'] = '1'                      # 强制：不 setdefault（防污染成 0）
    env.setdefault('LOOM_DIALOG_AUTO_CLOSE_MS', '8000')
    env.setdefault('PYTHONIOENCODING', 'utf-8')
    before = snapshot()
    base = keyset(before)
    rc, timed_out, out = None, False, ''
    pid = None
    try:
        proc = subprocess.Popen([sys.executable, path], cwd=ROOT, env=env,
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                encoding='utf-8', errors='replace')
        pid = proc.pid
        try:
            out = proc.communicate(timeout=timeout_s)[0] or ''
        except subprocess.TimeoutExpired:
            timed_out = True
            try:
                proc.kill()
            except Exception:
                pass
            try:
                out = (proc.communicate(timeout=10)[0] or '')
            except Exception:
                out = ''
        rc = proc.poll()
    except Exception as e:
        print('  子进程启动失败: %r' % (e,))
    after = snapshot()
    stray = [w for w in after if (w[0], w[1], w[2]) not in base]
    time.sleep(3.0)
    after3 = snapshot()
    stray3 = [w for w in after3 if (w[0], w[1], w[2]) not in base]
    same_pid = [w for w in after3 if pid is not None and w[3] == pid]
    return rc, timed_out, stray, stray3, same_pid, out, pid


def main():
    print('=== 测试残留窗口门（人类 2026-11-27 反馈：窗口不得等人点） ===')
    ok, why = desktop_available()
    if not ok:
        skip('全部门', why)
        print()
        print('总结果: SKIP（%d 项）—— 本环境无法检测可见窗口' % len(_skips))
        sys.exit(0)
    for fname, timeout_s, note in SAMPLES:
        print()
        print('---- %s（%s，超时 %ds）----' % (fname, note, timeout_s))
        t0 = time.monotonic()
        rc, timed_out, stray, stray3, same_pid, out, pid = run_sample(fname, timeout_s)
        dur = time.monotonic() - t0
        tail = out.strip().splitlines()[-4:]
        for line in tail:
            print('     | ' + line)
        check('%s 子进程自己退出（rc 可得，非超时）' % fname,
              (not timed_out) and rc is not None,
              'rc=%r timed_out=%r pid=%r %.1fs' % (rc, timed_out, pid, dur))
        check('%s 跑完瞬间无新增可见窗口（实测差集为空）' % fname,
              not stray, [(t, c, e) for (t, c, e, _p) in stray][:5])
        check('%s 3s 后仍无新增可见窗口（抓收尾期残留）' % fname,
              not stray3, [(t, c, e) for (t, c, e, _p) in stray3][:5])
        check('%s 无属于该测试进程的残留窗口（pid 级核对）' % fname,
              not same_pid, [(t, c, e) for (t, c, e, _p) in same_pid][:5])
    print()
    if _fails:
        print('总结果: FAIL（%d 条）' % len(_fails))
        print('FAIL test_no_stray_windows: %s' % (_fails,))
        try:
            sys.stdout.flush()
        except Exception:
            pass
        os._exit(1)
    print('总结果: ALL PASS（%d 条；SKIP %d 条）' % (_pass_n, len(_skips)))
    print('PASS test_no_stray_windows: 测试态不再留窗口（窗口不出现或自动关闭）')


main()