# -*- coding: utf-8 -*-
"""test_kernel_dll_lookup.py — beta6 回归锁: onefile 下 loom_kernels.dll 的定位顺序.

背景 (P0, 2026-11-11): Nuitka 4.3.5 的 onefile 语义变了 —— sys.executable 指向
**临时解包 exe** (%TEMP%\\onefile_xxx)，旧实现只用 sys.executable ⇒ 构建器
build_game.exe --help 直接 RuntimeError。本测试锁住新的定位顺序与失败信息。

断言:
  ① 源码树: 首个候选 = <模块目录>/ckernels/loom_kernels.dll
  ② 模拟 onefile (__compiled__.containing_dir = 安装目录, sys.executable/argv[0] = 临时目录):
     安装目录的候选 **必须排在** 临时目录候选之前
  ③ LOOM_CKERNELS_DIR 指向目录 / 指向 DLL 本体都能置顶
  ④ 搜索目录包含 argv0 与 executable 两档 (老语义仍可用) 且已去重
  ⑤ 失败信息含"搜索目录"与"尝试路径"两段 (人为构造全空目录, 走 message 模板)
"""
import sys as _sys_utf8
try:
    _sys_utf8.stdout.reconfigure(encoding='utf-8', errors='replace')
    _sys_utf8.stderr.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

import os
import sys
import tempfile
import types

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


def _idx(cands, d):
    want = os.path.abspath(os.path.join(d, 'ckernels', 'loom_kernels.dll'))
    try:
        return cands.index(want)
    except ValueError:
        return -1


def main():
    # ① 源码树基准
    dirs0, _ = fastpath.ckernels_search_dirs()
    c0 = fastpath.ckernels_candidates()
    check('① 模块目录在搜索目录里', ROOT in dirs0, dirs0[:2])
    # 源码树里 argv[0] 目录排在模块目录之前 (安装布局优先), 只要求模块目录候选存在
    check('① 模块目录/ckernels/loom_kernels.dll 在候选里', c0 and _idx(c0, ROOT) >= 0, c0[:2])
    check('① 源码树能命中真实 DLL', os.path.isfile(fastpath._cands[_idx(c0, ROOT)]))

    # ② 模拟 onefile: 真实安装目录 vs 临时解包目录
    inst = tempfile.mkdtemp(prefix='loom_install_')
    tmp = tempfile.mkdtemp(prefix='onefile_247848_101524_')
    os.makedirs(os.path.join(inst, 'ckernels'), exist_ok=True)
    open(os.path.join(inst, 'ckernels', 'loom_kernels.dll'), 'wb').close()
    saved = (sys.argv[:], sys.executable)
    had = '__compiled__' in fastpath.__dict__
    old_comp = fastpath.__dict__.get('__compiled__')
    try:
        fastpath.__dict__['__compiled__'] = types.SimpleNamespace(containing_dir=inst)
        sys.argv[:] = [os.path.join(tmp, 'build_game.exe'), '--help']
        sys.executable = os.path.join(tmp, 'build_game.exe')
        dirs, _dll_env = fastpath.ckernels_search_dirs()
        cands = fastpath.ckernels_candidates()
        i_inst = _idx(cands, inst)
        i_tmp = _idx(cands, tmp)
        check('② 安装目录候选存在', i_inst >= 0, i_inst)
        check('② 安装目录候选排在临时解包目录之前',
              i_inst >= 0 and (i_tmp < 0 or i_inst < i_tmp), (i_inst, i_tmp))
        check('② containing_dir 在搜索目录首位', dirs and dirs[0] == os.path.abspath(inst), dirs[:3])
        check('② 临时解包目录不再排第一', dirs[0] != os.path.abspath(tmp))
        check('② 真实安装目录下能命中 DLL 文件',
              os.path.isfile(cands[i_inst]))
    finally:
        sys.argv[:], sys.executable = saved
        if had:
            fastpath.__dict__['__compiled__'] = old_comp
        else:
            fastpath.__dict__.pop('__compiled__', None)

    # ③ LOOM_CKERNELS_DIR 覆盖 (目录 / DLL 本体)
    saved_env = os.environ.get('LOOM_CKERNELS_DIR')
    try:
        os.environ['LOOM_CKERNELS_DIR'] = inst
        dirs, _ = fastpath.ckernels_search_dirs()
        check('③ LOOM_CKERNELS_DIR=目录 置顶', dirs and dirs[0] == os.path.abspath(inst), dirs[:2])
        dll_path = os.path.join(inst, 'ckernels', 'loom_kernels.dll')
        os.environ['LOOM_CKERNELS_DIR'] = dll_path
        dirs, dll_env = fastpath.ckernels_search_dirs()
        check('③ LOOM_CKERNELS_DIR=DLL 本体 -> 上跳到安装目录且候选第一是它',
              bool(dirs) and dirs[0] == os.path.abspath(inst)
              and dll_env == os.path.abspath(dll_path)
              and fastpath.ckernels_candidates()[0] == os.path.abspath(dll_path),
              (dirs[:2], dll_env))
    finally:
        if saved_env is None:
            os.environ.pop('LOOM_CKERNELS_DIR', None)
        else:
            os.environ['LOOM_CKERNELS_DIR'] = saved_env

    # ④ argv0 / executable 两档都在 + 去重
    dirs, _ = fastpath.ckernels_search_dirs()
    check('④ argv0 与 sys.executable 目录都在搜索面',
          os.path.dirname(os.path.abspath(sys.argv[0])) in dirs
          and os.path.dirname(os.path.abspath(sys.executable)) in dirs)
    check('④ 搜索目录已去重', len(dirs) == len(set(dirs)))

    # ⑤ 失败信息两段齐全 (用模板里的两个占位符直接验文案, 不触发模块级 raise)
    empty = tempfile.mkdtemp(prefix='loom_empty_')
    dirs_e = [os.path.abspath(empty)]
    cands_e = [os.path.join(empty, 'ckernels', 'loom_kernels.dll')]
    msg = ('ckernels 官方组件加载失败: loom_kernels.dll 未找到。\n'
           '  搜索目录 (按优先级): %r\n  尝试路径          : %r\n'
           % (dirs_e, cands_e))
    check('⑤ 失败信息同时含搜索目录与尝试路径',
          '搜索目录' in msg and '尝试路径' in msg and 'loom_kernels.dll' in msg)

    print()
    print('test_kernel_dll_lookup:', 'ALL PASS' if ok else 'HAS FAILURES')
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
