# -*- coding: utf-8 -*-
"""module_registry_check.py — 注册表验证器/组装器探针 (M1-2 验收)

覆盖 注册表格式与契约设计说明.txt §6 校0-校8 + §7 回退矩阵 + §8 逃生门 + §9 自愈。
全部 fuzz 注册表只落系统临时目录, 真实 registry.json 只读 (结尾断言哈希未变)。
输出 ALL PASS / FAILED 清单; exit 0/1 (项目探针惯例)。
"""
import ctypes
import hashlib
import json
import os
import shutil
import sys
import tempfile

BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, BASE)
sys.path.insert(0, os.path.join(BASE, 'core_components'))
os.chdir(BASE)

import module_loader as ml
import module_registry as mr

REG = os.path.join(BASE, 'core_components', 'registry.json')
REF_DLL = os.path.join(BASE, 'core_components', 'module_ref.dll')
BAD_DLL = os.path.join(BASE, 'core_components', 'badvector.dll')
AMB_DLL = os.path.join(BASE, 'core_components', 'ambiguous.dll')
CK_DLL = os.path.join(BASE, 'ckernels', 'loom_kernels.dll')

results = []
TMP = tempfile.mkdtemp(prefix='loom_regchk_')


def check(name, ok, detail=''):
    results.append(bool(ok))
    print('%s %s %s' % ('PASS' if ok else 'FAILED', name, detail))


def sha(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for c in iter(lambda: f.read(1 << 20), b''):
            h.update(c)
    return h.hexdigest()


def reg_sha():
    return sha(REG)


def mk(tag, entries, fmt='loom-core-registry/1.0'):
    d = os.path.join(TMP, tag)
    os.makedirs(d, exist_ok=True)
    p = os.path.join(d, 'registry.json')
    with open(p, 'w', encoding='utf-8') as f:
        json.dump({'_format': fmt, 'registry_version': '1.0',
                   'components': entries}, f, ensure_ascii=False, indent=2)
    return p


def ent(mid, path, official=True, enabled=True, provides=(), depends=(),
        s256='', note='probe'):
    return {'module_id': mid, 'path': path.replace('\\', '/'), 'official': official,
            'enabled': enabled, 'provides': list(provides), 'depends': list(depends),
            'sha256': s256, 'note': note}


REF = 'core_components/module_ref.dll'
BAD = 'core_components/badvector.dll'
AMB = 'core_components/ambiguous.dll'
CK = 'ckernels/loom_kernels.dll'


def raises(exc, fn):
    try:
        fn()
    except exc:
        return True
    except Exception as e:
        print('   [raises] 期望 %s 实得 %r' % (exc.__name__, e))
        return False
    return False


# ---------------------------------------------------------------------------
# A 正向组装
# ---------------------------------------------------------------------------
def case_a():
    a = mr.assemble()
    check('A1 modules==5', sorted(a.modules) == ['ckernels', 'module_ref', 'physics', 'pipeline', 'script'],
          '%r' % sorted(a.modules))
    check('A2 provides_map 齐全 (12)', a.provides_map == {
        'module_ref.echo': 'module_ref',
        'ckernels.aabbs': 'ckernels', 'ckernels.collide': 'ckernels',
        'pipeline.light_vps': 'pipeline', 'pipeline.scene_bounds': 'pipeline',
        'pipeline.aabbs': 'pipeline', 'pipeline.world_matrices': 'pipeline',
        'script.batch_rotate': 'script', 'script.batch_move': 'script',
        'physics.pre_step': 'physics', 'physics.post_step': 'physics',
        'physics.substep_loop': 'physics'},
        '%r' % a.provides_map)
    check('A3 report 是 list[dict]',
          isinstance(a.report, list) and all(isinstance(r, dict) for r in a.report)
          and all(set(('seq', 'action', 'module_id', 'path', 'official', 'reason'))
                  <= set(r) for r in a.report), 'n=%d' % len(a.report))
    check('A4 0 popped / 全 loaded',
          [r['action'] for r in a.report] == ['loaded'] * 5,
          '%r' % [r['action'] for r in a.report])
    check('A5 句柄已 init', all(h.inited for h in a.modules.values()))
    check('A6 get 缺件抛 ModuleNotAvailable',
          raises(ml.ModuleNotAvailable, lambda: a.get('nonexistent')))
    check('A7 do_init=False 不 init',
          all(not h.inited for h in mr.assemble(do_init=False).modules.values()))
    check('A8 summary() 可读', isinstance(a.summary(), str) and 'modules' in a.summary())
    # 官方弹出 → AssemblyError (无 Python 冗余)
    check('A9 pop_and_fallback 官方 → AssemblyError',
          raises(ml.AssemblyError, lambda: a.pop_and_fallback('module_ref', 'x')))
    a.shutdown()
    check('A10 shutdown 清空', a.modules == {} and a.provides_map == {})


# ---------------------------------------------------------------------------
# 校0 sha 信任闸
# ---------------------------------------------------------------------------
def case_sha():
    good = sha(BAD_DLL)
    # B1 注入 sha 正确 → 顶替官方, 无回退
    p = mk('sha_ok', [ent('module_ref', REF, True, True, ['module_ref.echo']),
                      ent('module_ref', BAD, False, True, ['module_ref.echo'], s256=good)])
    a = mr.assemble(p, base_dir=BASE)
    check('B1 注入 sha 正确 → 顶替官方',
          a.get('module_ref').official == 0 and a.get('module_ref').path.endswith('badvector.dll'),
          'official=%d' % a.get('module_ref').official)
    a.shutdown()
    # B2 注入 sha 错误 → 不加载直接弹出 + 官方顶回 + 回写
    p = mk('sha_bad', [ent('module_ref', REF, True, True, ['module_ref.echo']),
                       ent('module_ref', BAD, False, True, ['module_ref.echo'], s256='0' * 64)])
    a = mr.assemble(p, base_dir=BASE)
    acts = [r['action'] for r in a.report]
    check('B2 sha 错 → 弹出+回写+官方顶回',
          'popped' in acts and 'writeback' in acts and 'fallback' in acts
          and a.get('module_ref').official == 1, '%r' % acts)
    with open(p, encoding='utf-8') as f:
        comps = json.load(f)['components']
    check('B2b 回写只改 enabled 且命中注入条目',
          comps[1]['enabled'] is False and comps[0]['enabled'] is True
          and comps[1]['sha256'] == '0' * 64, '%r' % [c['enabled'] for c in comps])
    a.shutdown()
    # B3 官方 sha 错误 → AssemblyError
    p = mk('sha_off', [ent('module_ref', REF, True, True, ['module_ref.echo'],
                           s256='0' * 64)])
    check('B3 官方 sha 错 → AssemblyError',
          raises(ml.AssemblyError, lambda: mr.assemble(p, base_dir=BASE)))


# ---------------------------------------------------------------------------
# 校3/校4 身份与声明一致
# ---------------------------------------------------------------------------
def case_decl():
    p = mk('decl_off', [ent('module_ref', REF, False, True, ['module_ref.echo'])])
    a = mr.assemble(p, base_dir=BASE)
    check('C1 official 不一致 → 弹出 (条目=注入, 无官方可回退)',
          'module_ref' not in a.modules
          and raises(ml.ModuleNotAvailable, lambda: a.get('module_ref'))
          and 'popped' in [r['action'] for r in a.report],
          'modules=%r acts=%r' % (sorted(a.modules),
                                  [r['action'] for r in a.report]))
    a.shutdown()
    p = mk('decl_prov', [ent('module_ref', REF, True, True,
                             ['module_ref.echo', 'module_ref.fake'])])
    check('C2 provides 声明不符 → AssemblyError',
          raises(ml.AssemblyError, lambda: mr.assemble(p, base_dir=BASE)))
    p = mk('decl_dep', [ent('module_ref', REF, True, True, ['module_ref.echo'],
                            ['nobody.gives.this'])])
    check('C3 depends 声明与 DLL 不符 → 官方 → AssemblyError',
          raises(ml.AssemblyError, lambda: mr.assemble(p, base_dir=BASE)))


# ---------------------------------------------------------------------------
# 校6 接口冲突
# ---------------------------------------------------------------------------
def case_conflict():
    # D1 双官方同接口 → AssemblyError
    p = mk('conf_off', [ent('ckernels', CK, True, True,
                            ['ckernels.aabbs', 'ckernels.collide']),
                        ent('module_ref', REF, True, True, ['module_ref.echo']),
                        ent('module_ref', REF, True, True, ['module_ref.echo'])])
    check('D1 同槽位双官方 → AssemblyError',
          raises(ml.AssemblyError, lambda: mr.assemble(p, base_dir=BASE)))
    # D2 歧义注入 (不同 module_id 提供同接口) → 弹注入保官方
    #     靶 = ambiguous.dll (module_id="ambiguous", provides=["ckernels.aabbs"])
    p = mk('conf_inj', [ent('ckernels', CK, True, True,
                            ['ckernels.aabbs', 'ckernels.collide']),
                        ent('ambiguous', AMB, False, True, ['ckernels.aabbs'],
                            s256=sha(AMB_DLL))])
    a = mr.assemble(p, base_dir=BASE)
    acts = [r['action'] for r in a.report]
    check('D2 歧义注入 → 弹注入保官方',
          'conflict' in acts and sorted(a.modules) == ['ckernels']
          and a.provides_map == {'ckernels.aabbs': 'ckernels',
                                 'ckernels.collide': 'ckernels'}, '%r' % acts)
    a.shutdown()


# ---------------------------------------------------------------------------
# 校5/校7 依赖满足与环
# ---------------------------------------------------------------------------
def case_dep():
    # E1 注入依赖未满足 → 弹出 + 官方顶回 (module_ref 官方无依赖)
    p = mk('dep_unmet', [ent('module_ref', REF, True, True, ['module_ref.echo']),
                         ent('module_ref', BAD, False, True, ['module_ref.echo'],
                             ['nobody.x'], s256=sha(BAD_DLL))])
    a = mr.assemble(p, base_dir=BASE)
    acts = [r['action'] for r in a.report]
    check('E1 注入依赖未满足 → 弹出+官方顶回',
          'popped' in acts and 'fallback' in acts and a.get('module_ref').official == 1,
          '%r' % acts)
    a.shutdown()
    # E2 官方依赖未满足 → AssemblyError
    p = mk('dep_off', [ent('module_ref', REF, True, True, ['module_ref.echo'],
                           ['nobody.x'])])
    check('E2 官方依赖未满足 → AssemblyError',
          raises(ml.AssemblyError, lambda: mr.assemble(p, base_dir=BASE)))
    # E3 校7 依赖环 (单元级): 现有 DLL depends 全空, 端到端无法构造环 →
    #    直接对 _topo_order 喂互为依赖的桩, 验证环检测 + 拓扑序语义。
    class _Stub(object):
        def __init__(self, provides=(), depends=()):
            self.provides, self.depends = tuple(provides), tuple(depends)
    cyc = {'a': _Stub(('x.a',), ('x.b',)), 'b': _Stub(('x.b',), ('x.a',))}
    order, cyclic = mr._topo_order(cyc)
    check('E3 依赖环 → cyclic 非空且顺序为空', cyclic == {'a', 'b'} and order == [],
          'order=%r cyclic=%r' % (order, cyclic))
    dag = {'a': _Stub(('x.a',), ('x.b',)), 'b': _Stub(('x.b',), ())}
    order2, cyc2 = mr._topo_order(dag)
    check('E3b 无环 → 依赖先行 (b 在 a 前)', cyc2 == set() and order2 == ['b', 'a'],
          'order=%r' % order2)


# ---------------------------------------------------------------------------
# §8 LOOM_NO_DLL 逃生门
# ---------------------------------------------------------------------------
def case_skip():
    old = os.environ.get('LOOM_NO_DLL')
    try:
        os.environ['LOOM_NO_DLL'] = 'ckernels'
        a = mr.assemble()
        acts = [r['action'] for r in a.report]
        check("F1 LOOM_NO_DLL='ckernels' → skipped + get 抛",
              'skipped' in acts and sorted(a.modules) == ['module_ref', 'physics', 'pipeline', 'script']
              and raises(ml.ModuleNotAvailable, lambda: a.get('ckernels')),
              '%r' % acts)
        a.shutdown()
        os.environ['LOOM_NO_DLL'] = '*'
        a = mr.assemble()
        check("F2 LOOM_NO_DLL='*' → 全跳",
              a.modules == {} and a.provides_map == {},
              'modules=%r' % sorted(a.modules))
        a.shutdown()
        del os.environ['LOOM_NO_DLL']
        a = mr.assemble()
        check('F3 清 env → 恢复 5 组件', sorted(a.modules) == ['ckernels', 'module_ref', 'physics', 'pipeline', 'script'])
        a.shutdown()
    finally:
        os.environ.pop('LOOM_NO_DLL', None)
        if old is not None:
            os.environ['LOOM_NO_DLL'] = old


# ---------------------------------------------------------------------------
# §9 运行期自愈 (坏注入 → pop_and_fallback → 官方顶回 → 逐位)
# ---------------------------------------------------------------------------
def case_heal():
    import numpy as np
    p = mk('heal', [ent('module_ref', REF, True, True, ['module_ref.echo']),
                    ent('module_ref', BAD, False, True, ['module_ref.echo'],
                        s256=sha(BAD_DLL))])
    a = mr.assemble(p, base_dir=BASE)
    h = a.get('module_ref')
    check('G1 坏注入上岗 (official=0)', h.official == 0)
    src = np.arange(6, dtype=np.float64)
    st, _k1 = ml.tensor_from_array(src)
    dst = np.zeros(6, dtype=np.float64)
    dt, _k2 = ml.tensor_from_array(dst)
    fn = h.get_fn('module_ref_echo', ctypes.c_int32,
                  [ctypes.POINTER(ml.LoomTensor), ctypes.POINTER(ml.LoomTensor)])
    crashed = False
    try:
        fn(ctypes.byref(st), ctypes.byref(dt))
    except OSError:
        crashed = True
    check('G2 坏注入首调 → OSError (SEH 转译)', crashed)
    if crashed:
        nh = a.pop_and_fallback('module_ref', 'probe: badvector AV')
        check('G3 pop_and_fallback → 官方顶回且已 init',
              nh.official == 1 and nh.inited and a.get('module_ref') is nh,
              'official=%d inited=%s' % (nh.official, nh.inited))
        out = np.zeros(6, dtype=np.float64)
        st2, _k3 = ml.tensor_from_array(src)
        dt2, _k4 = ml.tensor_from_array(out)
        fn2 = nh.get_fn('module_ref_echo', ctypes.c_int32,
                        [ctypes.POINTER(ml.LoomTensor),
                         ctypes.POINTER(ml.LoomTensor)])
        rc = int(fn2(ctypes.byref(st2), ctypes.byref(dt2)))
        check('G4 官方顶回后 echo 逐位',
              rc == 0 and float(np.max(np.abs(out - src))) == 0.0, 'rc=%d' % rc)
        with open(p, encoding='utf-8') as f:
            comps = json.load(f)['components']
        check('G5 坏注入 enabled=false 已回写', comps[1]['enabled'] is False)
    a.shutdown()


# ---------------------------------------------------------------------------
# 结构错误 + 真实注册表未变
# ---------------------------------------------------------------------------
def case_struct():
    p = mk('fmt_bad', [ent('module_ref', REF, True, True, ['module_ref.echo'])],
           fmt='loom-core-registry/9.9')
    check('H1 _format 不符 → AssemblyError',
          raises(ml.AssemblyError, lambda: mr.assemble(p, base_dir=BASE)))
    d = os.path.join(TMP, 'struct_bad')
    os.makedirs(d, exist_ok=True)
    p2 = os.path.join(d, 'registry.json')
    with open(p2, 'w', encoding='utf-8') as f:
        json.dump({'_format': 'loom-core-registry/1.0', 'components': 'oops'}, f)
    check('H2 components 非数组 → AssemblyError',
          raises(ml.AssemblyError, lambda: mr.assemble(p2, base_dir=BASE)))
    p3 = os.path.join(d, 'registry2.json')
    with open(p3, 'w', encoding='utf-8') as f:
        json.dump({'_format': 'loom-core-registry/1.0',
                   'components': [{'module_id': 'x'}]}, f)
    check('H3 条目缺字段 → AssemblyError',
          raises(ml.AssemblyError, lambda: mr.assemble(p3, base_dir=BASE)))
    check('H4 注册表文件不存在 → AssemblyError',
          raises(ml.AssemblyError,
                 lambda: mr.assemble(os.path.join(TMP, 'nope.json'))))


def main():
    print('=== module_registry_check (M1-2) ===')
    before = reg_sha()
    case_a()
    case_sha()
    case_decl()
    case_conflict()
    case_dep()
    case_skip()
    case_heal()
    case_struct()
    check('Z 真实 registry.json 哈希未变', reg_sha() == before, before[:16])
    bad = results.count(False)
    print('--- %d 项: PASS %d / FAILED %d ---'
          % (len(results), results.count(True), bad))
    print('ALL PASS' if bad == 0 else 'FAILED %d 项' % bad)
    shutil.rmtree(TMP, ignore_errors=True)
    return 0 if bad == 0 else 1


if __name__ == '__main__':
    sys.exit(main())
