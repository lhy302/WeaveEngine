# -*- coding: utf-8 -*-
"""crash_reporter_check.py — crash_reporter 三子项验证探针

M1 崩溃落盘闸门 (总纲 v1.3 §六 M1)。子项:
  A (进程内, 安全): install + write_dump → .dmp 存在且 >0 字节, 备份回调被调
  B (子进程+超时): filter 兜真崩溃 — 子进程 ctypes 空指针解引用 → 非零退出
     + 崩溃日志目录出现新 .dmp (超时 30s)
  C (进程内): 限流 — 连调 write_dump 5 次, 只落 1-2 个
输出 ALL PASS / FAILED 清单; exit 0/1 (项目探针惯例)。
B 子进程独立可运行: python crash_reporter_check.py --childB
"""
import os
import sys
import glob
import time
import ctypes

BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, BASE)
os.chdir(BASE)

import crash_reporter

_DUMP_DIR = os.path.join(BASE, '崩溃日志')
results = []


def _dumps():
    return sorted(glob.glob(os.path.join(_DUMP_DIR, '*.dmp')), key=os.path.getmtime)


def check(name, ok, detail=''):
    results.append(ok)
    print('%s %s %s' % ('PASS' if ok else 'FAILED', name, detail))


# ---------------------------------------------------------------------------
# 子项 A: 手动 dump + 备份回调 (进程内, 安全)
# ---------------------------------------------------------------------------
def case_a():
    before = _dumps()
    calls = []
    crash_reporter.register_scene_backup(lambda reason: calls.append(reason))
    if not crash_reporter.install():
        check('A install', False, 'install 返回 False (dbghelp 不可用?)')
        return
    check('A install', True, 'filter 已安装')
    p = crash_reporter.write_dump(reason='manual-test')
    time.sleep(0.05)
    after = [x for x in _dumps() if x not in before]
    check('A dump 文件落盘', p is not None and len(after) >= 1,
          'path=%r' % p)
    if p:
        check('A dump 大小>0', os.path.getsize(p) > 0,
              'size=%d bytes' % os.path.getsize(p))
    else:
        check('A dump 大小>0', False, '无文件')
    check('A 备份回调被调', len(calls) >= 1, 'calls=%r' % calls)


# ---------------------------------------------------------------------------
# 子项 B 子进程体: 注册 filter 后真崩 (空指针解引用) — 独立可运行
# ---------------------------------------------------------------------------
def case_b_child():
    crash_reporter.install()
    # 裸崩触发 unhandled filter (实测 2026-09-08, py3.12):
    # - ctypes.string_at(0, 4) 被 CPython 空指针守卫拦成静默返回 (不崩不抛)
    # - ctypes.string_at 的 SEH 包裹也把违例转 OSError (write_dump 存在的原因)
    # 两者都走不到 unhandled filter。ctypes.c_int.from_address(0).value 在
    # buffer 协议层直接野读, 无 SEH 包裹 → 真 0xC0000005 → filter 兜住。
    v = ctypes.c_int.from_address(0).value
    print('no crash?! v=%r' % v, flush=True)   # 不该到这


def case_b():
    import subprocess
    before = set(_dumps())
    me = os.path.abspath(__file__)
    r = subprocess.run([sys.executable, me, '--childB'],
                       capture_output=True, timeout=30)
    new = [x for x in _dumps() if x not in before]
    # 判据: 子进程非零退出 (0xC0000005=3221225477) + 落了盘
    check('B 子进程非零退出', r.returncode not in (0, None),
          'rc=%d stderr=%r' % (r.returncode, r.stderr[-120:]))
    check('B dump 落盘', len(new) >= 1,
          'new=%r' % [os.path.basename(x) for x in new])
    if new:
        check('B dump 大小>0', all(os.path.getsize(x) > 0 for x in new),
              'sizes=%r' % [os.path.getsize(x) for x in new])
    else:
        check('B dump 大小>0', False, '无文件')


# ---------------------------------------------------------------------------
# 子项 C: 限流 (进程内) — 连调 5 次只落 1-2 个
# ---------------------------------------------------------------------------
def case_c():
    before = set(_dumps())
    got = []
    for i in range(5):
        p = crash_reporter.write_dump(reason='rate-test-%d' % i)
        if p:
            got.append(p)
    n = len(got)
    check('C 限流 5 次只落 1-2 个', 1 <= n <= 2,
          '实际落盘=%d' % n)
    check('C 全部 >0 字节', all(os.path.getsize(x) > 0 for x in got),
          'sizes=%r' % [os.path.getsize(x) for x in got])


if __name__ == '__main__':
    if '--childB' in sys.argv:
        case_b_child()
        os._exit(1)   # 未走到崩溃出口: 视为失败 (不该到这)
    case_a()
    case_b()
    case_c()
    print('-' * 60)
    if all(results):
        print('ALL PASS (%d/%d)' % (len(results), len(results)))
        sys.exit(0)
    print('FAILED (%d/%d pass)' % (sum(results), len(results)))
    sys.exit(1)
