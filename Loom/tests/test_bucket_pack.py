# -*- coding: utf-8 -*-
"""test_bucket_pack.py — D1/P1: loom_bucket_pack 逐字节对拍 + 契约错误码.

断言:
  ① ckernels.loom_bucket_pack 导出存在 (官方件契约)
  ② 无剔除 (keep=None): main/sha 字节 == Python 参考实现, main_n == 各桶实例数
  ③ 有剔除 (keep 含空洞): 过滤顺序/字节/main_n 与参考实现逐字节一致
  ④ 单实例桶守卫: 桶内 n<=1 时即使 keep=0 也必须保留 (与 Python k>1 守卫同)
  ⑤ 全剔除桶: main_n=0 且不写 main (字节区域保持原样)
  ⑥ 契约错误码: offs[0]!=0 / 区间越界 -> rc=1; K=0 -> rc=0
参考实现 = loom_render._prepare_bucket_frame 现行 Python 路径的直译 (numpy)。
"""
import sys as _sys_utf8
try:
    _sys_utf8.stdout.reconfigure(encoding='utf-8', errors='replace')
    _sys_utf8.stderr.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
os.chdir(ROOT)

import fastpath                                              # noqa: E402

ok = True


def check(label, cond, detail=''):
    global ok
    print(('PASS ' if cond else 'FAIL ') + label + ('  ' + str(detail) if detail else ''))
    if not cond:
        ok = False


def ref_pack(world16, sat, col, offs, keep):
    """Python 参考: 现行 _prepare_bucket_frame 的语义直译 (逐字节可对照)."""
    n = world16.shape[0]
    K = len(offs) - 1
    out_main = np.zeros((n, 24), dtype='f4')
    out_sha = np.zeros((n, 16), dtype='f4')
    cnt = np.zeros((K,), dtype='i4')
    for b in range(K):
        a, e = int(offs[b]), int(offs[b + 1])
        k = e - a
        if k:
            out_sha[a:a + k] = world16[a:a + k]
        if keep is None or k <= 1:
            sel = list(range(a, e))
        else:
            sel = [i for i in range(a, e) if keep[i]]
        for q, i in enumerate(sel):
            row = out_main[a + q]
            row[0:16] = world16[i]
            row[16] = sat[i]
            row[17:20] = 0.0
            row[20:24] = col[i]
        cnt[b] = len(sel)
    return out_main, out_sha, cnt


def run_c(world16, sat, col, offs, keep, main=None, sha=None, cnt=None):
    n = world16.shape[0]
    K = len(offs) - 1
    if main is None:
        main = np.zeros((n, 24), dtype='f4')
    if sha is None:
        sha = np.zeros((n, 16), dtype='f4')
    if cnt is None:
        cnt = np.zeros((K,), dtype='i4')
    rc = fastpath.bucket_pack(world16, sat, col, np.asarray(offs, dtype=np.int64),
                              keep, main, sha, cnt)
    return rc, main, sha, cnt


def main():
    check('① loom_bucket_pack 导出可用', fastpath.bucket_pack_available())

    rng = np.random.RandomState(1234)
    offs = [0, 20, 30, 31, 31]          # 4 桶: 20 / 10 / 1 / 0 实例 (含空桶)
    n = offs[-1]
    world16 = rng.rand(n, 16).astype('f4')
    sat = rng.rand(n).astype('f4')
    col = rng.rand(n, 4).astype('f4')

    # ② 无剔除
    rc, m, s, c = run_c(world16, sat, col, offs, None)
    rm, rs, rc_ref = ref_pack(world16, sat, col, offs, None)
    check('② rc=0', rc == 0, rc)
    check('② main 逐字节一致', m.tobytes() == rm.tobytes())
    check('② sha 逐字节一致', s.tobytes() == rs.tobytes())
    check('② main_n 一致', c.tolist() == rc_ref.tolist(), (c.tolist(), rc_ref.tolist()))

    # ③ 有剔除 (桶1保留 3 个, 桶0保留 17 个)
    keep = np.ones(n, dtype=np.uint8)
    keep[0:3] = 0
    keep[20:27] = 0
    rc, m, s, c = run_c(world16, sat, col, offs, keep)
    rm, rs, rc_ref = ref_pack(world16, sat, col, offs, keep)
    check('③ rc=0', rc == 0, rc)
    check('③ main 逐字节一致 (含重排)', m.tobytes() == rm.tobytes())
    check('③ sha 逐字节一致 (全量不受剔除影响)', s.tobytes() == rs.tobytes())
    check('③ main_n 一致', c.tolist() == rc_ref.tolist(), (c.tolist(), rc_ref.tolist()))
    check('③ 桶1 实例数 = 3', int(c[1]) == 3, int(c[1]))

    # ④ 单实例桶守卫 (offs[2]=30, offs[3]=31 -> 1 个实例; keep[30]=0)
    keep2 = np.ones(n, dtype=np.uint8)
    keep2[30] = 0
    rc, m, s, c = run_c(world16, sat, col, offs, keep2)
    check('④ 单实例桶不被剔除 (与 k>1 守卫同)', rc == 0 and int(c[2]) == 1, (rc, int(c[2])))

    # ⑤ 全剔除桶 -> main_n=0, main 区域不被改写
    keep3 = np.ones(n, dtype=np.uint8)
    keep3[20:30] = 0
    main5 = np.full((n, 24), 9.0, dtype='f4')
    rc, m, s, c = run_c(world16, sat, col, offs, keep3, main=main5)
    check('⑤ 桶1 全剔除 -> main_n=0', rc == 0 and int(c[1]) == 0, (rc, int(c[1])))
    check('⑤ 全剔除桶的 main 字节未被改写',
          np.all(m[20:30] == np.float32(9.0)))

    # ⑥ 契约错误码
    rc_bad0, _, _, _ = run_c(world16, sat, col, [3, 20, 30, 31, n], None)
    check('⑥ offs[0]!=0 -> rc=1', rc_bad0 == 1, rc_bad0)
    rc_bad1, _, _, _ = run_c(world16, sat, col, [0, 20, n + 5], None)
    check('⑥ 区间越界 -> rc=1', rc_bad1 == 1, rc_bad1)
    rc_bad2, _, _, _ = run_c(world16, sat, col, [0], None)
    check('⑥ K=0 -> rc=0 (空批合法)', rc_bad2 == 0, rc_bad2)

    print()
    print('test_bucket_pack:', 'ALL PASS' if ok else 'HAS FAILURES')
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
