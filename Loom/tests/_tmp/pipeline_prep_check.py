# -*- coding: utf-8 -*-
"""pipeline_prep_check.py — DLL化战役 M1-4: 对拍网 MVP 探针 (绞杀者口径)。

A 真实注册表组装 | B module_ref 全链 | C ckernels 逐位对拍 | D init 重入+hot_reload
| E LOOM_NO_DLL 逃生门 | F 收尾重装。基准 = fastpath._aabbs_minmax_impl
(★不用 _aabbs_minmax_np: numpy dgemm ~4 ULP 差, 假失败)。module_registry.py 缺席时
A/E 标 SKIP 报"待集成", B/C/D/F 走 ModuleHandle.load 直连跑通。只读既有文件。
"""
import ctypes, json, os, sys, tempfile
from contextlib import suppress
with suppress(Exception):                                # 控制台/重定向均 UTF-8 输出
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, BASE); os.chdir(BASE)
sys.path.insert(0, os.path.join(BASE, 'core_components'))
import numpy as np                                       # noqa: E402
import module_loader as ML                               # noqa: E402
import fastpath                                          # noqa: E402

REGISTRY_PATH = os.path.join(BASE, 'core_components', 'registry.json')
try:
    import module_registry as MR
    HAS_REGISTRY, _REG_ERR = True, ''
except Exception as _e:                                  # noqa: BLE001
    MR, HAS_REGISTRY, _REG_ERR = None, False, '%s: %s' % (type(_e).__name__, _e)
RESULTS, LIVE = [], []                                   # LIVE 防 GC (同 ML._LIVE 惯例)


def check(name, ok, detail=''):
    RESULTS.append((bool(ok), name))
    print('%s %s %s' % ('PASS' if ok else 'FAILED', name, detail))
    return bool(ok)


def maxdiff(a, b):
    a, b = np.asarray(a, np.float64), np.asarray(b, np.float64)
    if a.shape != b.shape:
        return float('inf')
    return 0.0 if a.size == 0 else float(np.max(np.abs(a - b)))


ECHO_FN = ('module_ref_echo', ctypes.c_int32,
           [ctypes.POINTER(ML.LoomTensor), ctypes.POINTER(ML.LoomTensor)])
AABB_FN = ('loom_aabbs_minmax', ctypes.c_int32,
           [ctypes.POINTER(ctypes.c_double)] * 4 + [ctypes.c_int64, ctypes.c_int64])
AABB_CASES = [('n137_V37', 137, 37), ('n1_V1', 1, 1), ('n500_V2035', 500, 2035),
              ('n0_empty', 0, 7)]
SKIP_MSG = '(module_registry 未就绪: %s) — 待集成' % _REG_ERR


def echo_check(h, shape, tag):
    """DLL echo vs numpy 副本逐位 → maxdiff。"""
    fn = h.get_fn(*ECHO_FN)
    src = np.ascontiguousarray(np.random.RandomState(
        abs(hash(str(shape))) % 2 ** 31).rand(*shape) * 8.0 - 4.0, np.float64)
    dst = np.zeros(shape, np.float64)
    ts, _ka = ML.tensor_from_array(src); td, kd = ML.tensor_from_array(dst)
    rc = int(fn(ctypes.byref(ts), ctypes.byref(td))); d = maxdiff(src, kd)
    check('%s echo %s' % (tag, shape), rc == 0 and d == 0.0, 'rc=%d maxdiff=%r' % (rc, d))
    return d


def aabb_check(h, name, n, V, tag):
    """DLL kernel vs fastpath._aabbs_minmax_impl 逐位 → maxdiff。"""
    fn = h.get_fn(*AABB_FN); rs = np.random.RandomState(1234)
    vh = np.ascontiguousarray(rs.rand(max(n, 1), max(V, 1), 4) * 10.0 - 5.0, np.float64)
    m3 = np.ascontiguousarray(rs.rand(max(n, 1), 4, 3) * 2.0 - 1.0, np.float64)
    if n == 0:
        vh = np.zeros((0, max(V, 1), 4), np.float64); m3 = np.zeros((0, 4, 3), np.float64)
    omn = np.zeros((max(n, 1), 3), np.float64); omx = np.zeros((max(n, 1), 3), np.float64)
    p = ctypes.POINTER(ctypes.c_double)
    rc = int(fn(ctypes.cast(vh.ctypes.data, p), ctypes.cast(m3.ctypes.data, p),
                ctypes.cast(omn.ctypes.data, p), ctypes.cast(omx.ctypes.data, p),
                ctypes.c_int64(n), ctypes.c_int64(V)))
    rmn, rmx = np.zeros_like(omn), np.zeros_like(omx)
    if n > 0 and V > 0:
        fastpath._aabbs_minmax_impl(vh, m3, rmn, rmx)
    d = max(maxdiff(omn[:n], rmn[:n]), maxdiff(omx[:n], rmx[:n]))
    check('%s aabbs %s' % (tag, name), rc == 0 and d == 0.0, 'rc=%d maxdiff=%r' % (rc, d))
    return d


def echo_max(h, tag):                                    # echo 三形状
    return max(echo_check(h, s, tag) for s in [(16,), (4, 5), (2, 3, 4)])


def aabbs_max(h, tag):                                   # aabbs 四用例 (含 n=0)
    return max(aabb_check(h, nm, n, V, tag) for nm, n, V in AABB_CASES)


def module_path(mid):
    with open(REGISTRY_PATH, 'r', encoding='utf-8') as f:
        for c in json.load(f)['components']:
            if c['module_id'] == mid:
                return os.path.join(BASE, c['path'].replace('/', os.sep))
    raise KeyError(mid)


def load_direct(mid):                                    # 直连 (无 module_registry 时)
    h = ML.ModuleHandle.load(module_path(mid), expected_module_id=mid)
    h.init(); LIVE.append(h)
    return h


def unload_all():
    for h in list(LIVE):
        with suppress(Exception):
            h.unload()
    LIVE.clear()


def part_a():                                            # A 真实注册表组装
    if not HAS_REGISTRY:
        print('SKIP A assemble_real_registry %s' % SKIP_MSG); return None
    asm = MR.assemble(REGISTRY_PATH, base_dir=BASE)
    check('A loaded==3', len(asm.modules) == 3, 'modules=%r' % (sorted(asm.modules),))
    rep = getattr(asm, 'report', None); slots = rep if isinstance(rep, list) else []
    acts = [r.get('action') for r in slots if isinstance(r, dict)]
    check('A popped/skipped/conflict==0', acts.count('popped') == acts.count('skipped') == acts.count('conflict') == 0, 'type=%s acts=%r' % (type(rep).__name__, acts))
    pm = asm.provides_map
    for iface, owner in (('module_ref.echo', 'module_ref'), ('ckernels.aabbs', 'ckernels'),
                         ('ckernels.collide', 'ckernels'),
                         ('pipeline.light_vps', 'pipeline'),
                         ('pipeline.scene_bounds', 'pipeline'),
                         ('pipeline.aabbs', 'pipeline'),
                         ('pipeline.world_matrices', 'pipeline')):
        check('A provides_map %s' % iface, pm.get(iface) == owner, 'got=%r' % (pm.get(iface),))
    check('A provides_map 齐全 (7)', len(pm) == 7, 'size=%d %r' % (len(pm), sorted(pm)))
    return asm

def part_b(h):                                           # B module_ref 全链
    for field, want in (('module_id', 'module_ref'), ('version', '1.0.0'), ('official', 1)):
        got = getattr(h, field)
        check('B %s' % field, got == want, 'got=%r' % (got,))
    check('B provides', tuple(h.provides) == ('module_ref.echo',), 'got=%r' % (h.provides,))
    check('B depends 空', tuple(h.depends) == (), 'got=%r' % (h.depends,))
    abi = int(h.get_fn('loom_module_abi', ctypes.c_uint32, [])())
    check('B abi()/info 双口一致', abi == int(h.abi_version) == ML.loom_abi_make(1, 0),
          'abi()=0x%08X info=0x%08X' % (abi, int(h.abi_version)))
    for iface, want in (('module_ref.echo', True), ('ckernels.aabbs', False),
                        ('module_ref.nope', False)):
        check('B has %s' % iface, h.has(iface) is want, 'got=%r' % (h.has(iface),))
    check('B echo 三形状 maxdiff==0.0', echo_max(h, 'B') == 0.0, '')
    fn = h.get_fn(*ECHO_FN); good = np.zeros((4,), np.float64)
    tg, _k = ML.tensor_from_array(good); rc_null = int(fn(None, ctypes.byref(tg)))
    bad = ML.LoomTensor(); bad.data = ctypes.c_void_p(int(good.ctypes.data))
    bad.ndim, bad.dtype = 0, ML.LOOM_DTYPE_F64           # 参数向量: ndim=0
    rc_ndim0 = int(fn(ctypes.byref(bad), ctypes.byref(tg)))
    check('B 参数向量 NULL/ndim=0 -> -2',
          rc_null == rc_ndim0 == ML.LOOM_ERR_PARAM, 'null=%d ndim0=%d' % (rc_null, rc_ndim0))


def part_c(h):                                           # C ckernels 对拍
    check('C aabbs maxdiff==0.0 (全部用例)', aabbs_max(h, 'C') == 0.0, '')
    check('C provides', tuple(h.provides) == ('ckernels.aabbs', 'ckernels.collide'),
          'got=%r' % (h.provides,))
    check('C depends 空', tuple(h.depends) == (), 'got=%r' % (h.depends,))
    for iface, want in (('ckernels.aabbs', True), ('module_ref.echo', False)):
        check('C has %s' % iface, h.has(iface) is want, 'got=%r' % (h.has(iface),))


def part_d(handles):                                     # D init 重入 + hot_reload
    out = dict(handles)
    for mid in ('module_ref', 'ckernels'):
        h = out.get(mid)
        if h is None:
            print('SKIP D %s (槽位空)' % mid); continue
        rc1, rc2 = h.init(), h.init()                    # 幂等: 重复调返 0
        check('D %s init 幂等' % mid, rc1 == 0 and rc2 == 0,
              'rc1=%d rc2=%d inited=%s' % (rc1, rc2, h.inited))
        nh = h.hot_reload(); LIVE.append(nh); out[mid] = nh
        check('D %s hot_reload 身份/inited' % mid, nh.module_id == mid and nh.inited is True,
              'id=%r inited=%r' % (nh.module_id, nh.inited))
    if out.get('module_ref') is not None:
        check('D module_ref reload echo maxdiff==0.0',
              echo_max(out['module_ref'], 'D reloaded module_ref') == 0.0, '')
    if out.get('ckernels') is not None:
        check('D ckernels reload aabbs maxdiff==0.0',
              aabbs_max(out['ckernels'], 'D reloaded ckernels') == 0.0, '')
    return out


def temp_registry(ids):
    """真实 registry 精简为给定 module_id → 写系统 temp (绝不写真实目录)。"""
    with open(REGISTRY_PATH, 'r', encoding='utf-8') as f:
        reg = json.load(f)
    reg['components'] = [c for c in reg['components'] if c['module_id'] in ids]
    fd, p = tempfile.mkstemp(prefix='loom_reg_', suffix='.json'); os.close(fd)
    with open(p, 'w', encoding='utf-8', newline='\n') as f:
        json.dump(reg, f, ensure_ascii=False)            # 临时注册表 (系统 temp)
    return p


def part_e(asm):                                         # E LOOM_NO_DLL 逃生门
    if not HAS_REGISTRY:
        print('SKIP E LOOM_NO_DLL %s' % SKIP_MSG); return
    old, tmp = os.environ.get('LOOM_NO_DLL', None), None
    try:
        if asm is not None:
            asm.shutdown()                               # 每个 env 变更后重新组装
        tmp = temp_registry({'module_ref', 'ckernels'})
        os.environ['LOOM_NO_DLL'] = 'ckernels'           # E1 单槽跳过
        a1 = MR.assemble(tmp, base_dir=BASE)
        rep = getattr(a1, 'report', None); act = None
        slots = rep if isinstance(rep, list) else (
            rep.get('slots', []) if isinstance(rep, dict) else [])
        for slot in slots or []:
            if isinstance(slot, dict) and slot.get('module_id') == 'ckernels':
                act = slot.get('action')
        if act is None and isinstance(rep, dict):
            act = (rep.get('actions') or {}).get('ckernels')
        check("E LOOM_NO_DLL='ckernels' 槽 action=skipped", act == 'skipped',
              'action=%r report=%r' % (act, rep))
        err = ''
        try:
            a1.get('ckernels'); err = '未抛异常'
        except ML.ModuleNotAvailable:
            pass
        except Exception as e:                           # noqa: BLE001
            err = '抛了 %s: %s' % (type(e).__name__, e)
        check('E get(ckernels) 抛 ModuleNotAvailable', err == '', err)
        try:
            hm = a1.get('module_ref')
            check('E module_ref 正常', getattr(hm, 'module_id', None) == 'module_ref',
                  'handle=%r' % (hm,))
        except Exception as e:                           # noqa: BLE001
            check('E module_ref 正常', False, '抛了 %s: %s' % (type(e).__name__, e))
        a1.shutdown()
        os.environ['LOOM_NO_DLL'] = '*'                  # E2 全跳
        a2 = MR.assemble(tmp, base_dir=BASE); bad = []
        for mid in ('module_ref', 'ckernels'):
            try:
                a2.get(mid); bad.append('%s 未抛' % mid)
            except ML.ModuleNotAvailable:
                pass
            except Exception as e:                       # noqa: BLE001
                bad.append('%s 抛 %s' % (mid, type(e).__name__))
        check("E LOOM_NO_DLL='*' 全跳", not bad, 'bad=%r' % (bad,))
        a2.shutdown()
        os.environ.pop('LOOM_NO_DLL', None)              # E3 清 env 恢复
        a3 = MR.assemble(tmp, base_dir=BASE)
        check('E 清 env 后恢复 loaded==2', len(a3.modules) == 2,
              'modules=%r' % (sorted(a3.modules),))
        a3.shutdown()
    finally:                                             # 务必恢复环境变量
        if old is None:
            os.environ.pop('LOOM_NO_DLL', None)
        else:
            os.environ['LOOM_NO_DLL'] = old
        if tmp and os.path.isfile(tmp):
            with suppress(OSError):
                os.remove(tmp)


def part_f():                                            # F 收尾重装
    unload_all()                                         # 全部句柄 deinit/unload
    if not HAS_REGISTRY:
        print('SKIP F 真实注册表重装 %s; 改直连重装验证' % SKIP_MSG)
        emax = echo_max(load_direct('module_ref'), 'F direct module_ref')
        amax = aabbs_max(load_direct('ckernels'), 'F direct ckernels')
        check('F 直连重装全绿 (无泄漏/无残留)', emax == 0.0 and amax == 0.0,
              'echo_max=%r aabb_max=%r' % (emax, amax))
        unload_all(); return
    asm = MR.assemble(REGISTRY_PATH, base_dir=BASE)
    check('F 重装 loaded==3', len(asm.modules) == 3, 'modules=%r' % (sorted(asm.modules),))
    emax, amax = (echo_max(asm.get('module_ref'), 'F module_ref'),
                  aabbs_max(asm.get('ckernels'), 'F ckernels'))
    check('F 重装全绿 (无泄漏/无残留)', emax == 0.0 and amax == 0.0,
          'echo_max=%r aabb_max=%r' % (emax, amax))
    asm.deinit_all(); asm.shutdown()


def main():
    print('=== pipeline_prep_check (M1-4 对拍网 MVP) ===')
    print('BASE=%s' % BASE)
    print('module_registry: %s' % ('OK' if HAS_REGISTRY else '缺席 → A/E 待集成'))
    print('LOOM_NO_DLL=%r' % os.environ.get('LOOM_NO_DLL', None))
    print('-' * 72)
    asm = part_a(); print('-' * 72)
    handles = ({'module_ref': asm.get('module_ref'), 'ckernels': asm.get('ckernels')}
               if asm is not None else
               {'module_ref': load_direct('module_ref'),
                'ckernels': load_direct('ckernels')})
    LIVE.extend(handles.values())
    part_b(handles['module_ref']); print('-' * 72)
    part_c(handles['ckernels']); print('-' * 72)
    part_d(handles); print('-' * 72)
    part_e(asm); print('-' * 72)
    part_f()
    print('=' * 72)
    bad = [n for ok, n in RESULTS if not ok]
    if bad:
        print('FAILED %d 项' % len(bad))
        for n in bad:
            print('   - %s' % n)
        return 1
    print('ALL PASS (%d 项)' % len(RESULTS))
    if not HAS_REGISTRY:
        print('(注: A/E 因 module_registry.py 未就绪标 SKIP — 待集成; B/C/D/F 已跑通)')
    return 0


if __name__ == '__main__':
    sys.exit(main())
