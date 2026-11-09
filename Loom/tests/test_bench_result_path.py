# -*- coding: utf-8 -*-
"""test_bench_result_path.py — D1 裁决（A）: --bench 结果落**用户目录**.

断言:
  ① 正常情况 -> <user_root>/bench/bench_result.txt，且目录被创建
  ② 用户目录不可用 -> 回退脚本/exe 旁，并给出原因（失败可见）
  ③ 结果文件路径会打印出来（编译版无控制台也能找到）
"""
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
os.chdir(ROOT)

import build_entry                                        # noqa: E402
import userpaths                                          # noqa: E402

ok = True


def check(label, cond, detail=''):
    global ok
    print(('PASS ' if cond else 'FAIL ') + label + ('  ' + str(detail) if detail else ''))
    if not cond:
        ok = False


def main():
    tmp = tempfile.mkdtemp(prefix='loom_bench_')
    old = os.environ.get('LOOM_USER_ROOT')
    os.environ['LOOM_USER_ROOT'] = tmp
    try:
        path, why = build_entry._bench_result_path()
        check('① 落点 = <user_root>/bench/bench_result.txt',
              path == os.path.join(tmp, 'bench', 'bench_result.txt') and why is None,
              (path, why))
        check('① 目录已创建', os.path.isdir(os.path.join(tmp, 'bench')))
    finally:
        if old is None:
            os.environ.pop('LOOM_USER_ROOT', None)
        else:
            os.environ['LOOM_USER_ROOT'] = old

    # ② 用户目录不可用 -> 回退 exe/脚本旁 + 原因
    orig = userpaths.user_root
    try:
        userpaths.user_root = lambda: (_ for _ in ()).throw(OSError('模拟不可写'))
        path2, why2 = build_entry._bench_result_path()
    finally:
        userpaths.user_root = orig
    check('② 回退到脚本/exe 旁', os.path.basename(path2) == 'bench_result.txt'
          and os.path.dirname(os.path.abspath(path2))
          == os.path.dirname(os.path.abspath(sys.argv[0])), path2)
    check('② 回退原因可见（不静默）', bool(why2) and '用户目录' in str(why2), why2)

    # ③ 打印路径（源码静态断言: 写盘后必须告知路径）
    src = open(os.path.join(ROOT, 'build_entry.py'), encoding='utf-8').read()
    check('③ 写盘后打印结果文件路径', '结果文件: %s' in src)
    check('③ 不再写 exe 旁（旧实现已移除）',
          "os.path.dirname(os.path.abspath(sys.argv[0])),\n                       'bench_result.txt'" not in src)

    print('\n总结果: %s' % ('ALL PASS' if ok else 'FAIL'))
    sys.exit(0 if ok else 1)


if __name__ == '__main__':
    main()
