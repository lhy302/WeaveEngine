# -*- coding: utf-8 -*-
"""test_package_excludes_no_engine_package.py — 打包器排除表防回潮门（2026-11-27）

根因（beta7 发布门拦下的真实事故）：tools/package_engine.py 的 EXCLUDE_DIRS 里有
小写 'assets'，是「排除用户游戏资产目录」时代写的；B6 目录重构把引擎自己的资产层
做成 Loom/assets/ 包后撞名 —— 源码包装出来缺整个引擎包（5 个 .py），import 即崩。
verify_pkg_vs_head 红了（包内引擎 .py 221 / HEAD 226，缺 5）才被拦下。

本门锁三件事（读到的信息 -> 判定，不依赖打包真跑）：
  A. 排除表 ∩ 引擎 .py 包 = 空，**除两个设计上就该排除的子树**：
       tests          —— 测试套件不入引擎发行包（verify 对拍口径同样排除）
       player_runtime —— 冻结发行子树，由 make_zip 显式预置而非靠文件收集
     这两个是**白名单事实**（不是兜底豁免）：门会确认它们真的各自有 .py，
     防止白名单变成「谁红就往里塞谁」。
  B. 用户工程约定的排除项不许丢（防「删表了事」式修复）
  C. 打包器现在真的会收集 Loom/assets/ 的 .py（直证，非仅看表）
"""
import importlib.util
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)                      # Loom/
REPO = os.path.dirname(ROOT)                      # 仓库根
sys.path.insert(0, ROOT)
os.environ.setdefault('LOOM_NO_DIALOG', '1')

fails = []


def check(name, ok, detail=''):
    print('%s %s%s' % ('PASS' if ok else 'FAIL', name, ('  %s' % (detail,)) if detail else ''))
    if not ok:
        fails.append(name)


def load_packer():
    spec = importlib.util.spec_from_file_location(
        '_pkg_engine_under_test', os.path.join(REPO, 'tools', 'package_engine.py'))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def has_py(d):
    for dp, dn, fn in os.walk(d):
        dn[:] = [x for x in dn if x != '__pycache__']
        if any(f.endswith('.py') for f in fn):
            return True
    return False


print('=== A. 排除表 ∩ 引擎 .py 包 = 空（tests / player_runtime 除外，理由见文件头）===')
pe = load_packer()
excl = set(getattr(pe, 'EXCLUDE_DIRS', ()) or ())
check('A0 能读到 EXCLUDE_DIRS', bool(excl), '共 %d 项: %s' % (len(excl), sorted(excl)))
py_pkgs = set(name for name in os.listdir(ROOT)
              if name != '__pycache__' and os.path.isdir(os.path.join(ROOT, name))
              and has_py(os.path.join(ROOT, name)))
DESIGN_EXCLUDED = {'tests', 'player_runtime'}
collided = (excl & py_pkgs) - DESIGN_EXCLUDED
check('A1 引擎 .py 包（%d 个）与排除表零撞名' % len(py_pkgs),
      not collided, '撞名: %s' % (sorted(collided),) if collided else '')
check('A2 具体事故项 assets 不在排除表', 'assets' not in excl,
      '' if 'assets' not in excl else '事故回归：Loom/assets/（%d 个 .py）会被吃掉' % (
          len([f for f in os.listdir(os.path.join(ROOT, 'assets')) if f.endswith('.py')]),))
check('A3 两个白名单子树确实各含 .py（白名单不能是空的兜底）',
      DESIGN_EXCLUDED <= py_pkgs,
      '白名单里没有 .py 的项: %s' % (sorted(DESIGN_EXCLUDED - py_pkgs),))

print('=== B. 用户工程排除项不许丢 ===')
required = {'tests', '保存', 'Projects', '__pycache__', '.pytest_cache',
            'Assets', 'player_runtime', '发布'}
lost = required - excl
check('B1 用户工程约定排除项齐全（缺 = 修复变成删表）', not lost, '缺: %s' % (sorted(lost),))

print('=== C. 打包器真的收集 Loom/assets/ ===')
files = pe.collect_files(ROOT)
rels = {rel.replace(os.sep, '/') for _, rel in files}
assets_rel = sorted(r for r in rels if r.startswith('assets/') and r.endswith('.py'))
check('C1 collect_files 收到 Loom/assets/ 全部 .py（>0）', len(assets_rel) > 0,
      '实到 %d 个: %s' % (len(assets_rel), assets_rel))
expect = sorted(f for f in os.listdir(os.path.join(ROOT, 'assets')) if f.endswith('.py'))
check('C2 收集数 == 磁盘上 assets 包的 .py 数',
      sorted(os.path.basename(r) for r in assets_rel) == expect,
      '收集 %d / 磁盘 %d' % (len(assets_rel), len(expect)))

print()
print('总结果:', 'ALL PASS' if not fails else '有 FAIL')
sys.exit(0 if not fails else 1)