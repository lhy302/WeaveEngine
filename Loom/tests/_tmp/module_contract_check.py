# -*- coding: utf-8 -*-
"""module_contract_check.py — module_loader.py 契约加载器探针 (M1-3 验收)

子项:
  A 正向加载: module_ref.dll / loom_kernels.dll 六导出+info 字段+provides/depends
    + has() 正反 + sizeof(LoomModuleInfo)==104
  B 热路径: module_ref echo 逐位 (形状 (16,)/(4,5)/(2,3,4)) + 参数向量 rc==-2
  C 热重载: hot_reload 后 info 一致 + echo 仍逐位 + init 幂等/重入
  D 负向: 路径不存在 / 期望 id 不符 / 非法 PE / 未加载调用 get_fn
  E 逃生门: no_dll_skips 解析口径 (模块级, 不涉注册表)
输出 ALL PASS / FAILED 清单; exit 0/1 (项目探针惯例)。
"""
import ctypes
import os
import shutil
import sys
import tempfile

BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, BASE)
os.chdir(BASE)

sys.path.insert(0, os.path.join(BASE, 'core_components'))
import module_loader as ml

REF_DLL = os.path.join(BASE, 'core_components', 'module_ref.dll')
CK_DLL = os.path.join(BASE, 'ckernels', 'loom_kernels.dll')

results = []


def check(name, ok, detail=''):
    results.append(bool(ok))
    print('%s %s %s' % ('PASS' if ok else 'FAILED', name, detail))


def _echo(h, arr):
    import numpy as np
    src = np.ascontiguousarray(arr, dtype=np.float64)
    dst = np.zeros_like(src)
    st, ka = ml.tensor_from_array(src)
    dt, kb = ml.tensor_from_array(dst)
    fn = h.get_fn('module_ref_echo', ctypes.c_int32,
                  [ctypes.POINTER(ml.LoomTensor), ctypes.POINTER(ml.LoomTensor)])
    rc = int(fn(ctypes.byref(st), ctypes.byref(dt)))
    out = np.frombuffer(dst.data, dtype=np.float64, count=dst.size).reshape(dst.shape)
    return rc, out, src


# ---------------------------------------------------------------------------
# A 正向加载
# ---------------------------------------------------------------------------
def case_a():
    import numpy as np
    check('A0 sizeof(LoomModuleInfo)==104', ctypes.sizeof(ml.LoomModuleInfo) == 104,
          '%d' % ctypes.sizeof(ml.LoomModuleInfo))
    check('A0 sizeof(LoomTensor)==48', ctypes.sizeof(ml.LoomTensor) == 48,
          '%d' % ctypes.sizeof(ml.LoomTensor))

    h = ml.ModuleHandle.load(REF_DLL)
    check('A1 module_ref 加载', h.module_id == 'module_ref',
          'id=%s ver=%s official=%d abi=0x%X'
          % (h.module_id, h.version, h.official, h.abi_version))
    check('A2 module_ref 字段', h.version == '1.0.0' and h.official == 1
          and h.abi_version == ml.LOOM_ABI_VERSION_CURRENT
          and h.provides == ('module_ref.echo',) and h.depends == (),
          'provides=%s depends=%s' % (h.provides, h.depends))
    check('A3 module_ref has 正反',
          h.has('module_ref.echo') is True and h.has('nope.x') is False,
          'has(echo)=%s has(nope)=%s' % (h.has('module_ref.echo'), h.has('nope.x')))
    check('A4 module_ref init', h.init() == 0 and h.inited is True)
    check('A5 module_ref init 幂等', h.init() == 0)

    # echo 逐位
    ok_all = True
    for shape in [(16,), (4, 5), (2, 3, 4)]:
        a = np.arange(int(np.prod(shape)), dtype=np.float64).reshape(shape) * 1.5 - 3.25
        rc, out, src = _echo(h, a)
        ok_all = ok_all and rc == 0 and out.shape == src.shape
        ok_all = ok_all and float(np.max(np.abs(out - src))) == 0.0
    check('A6 echo 逐位 maxdiff=0 (16/4x5/2x3x4)', ok_all)

    # 参数向量: dtype 不符 / ndim 越界 → -2
    bad = ml.LoomTensor()
    bad.ndim = 0
    good, _k = ml.tensor_from_array(np.zeros(4, dtype=np.float64))
    fn = h.get_fn('module_ref_echo', ctypes.c_int32,
                  [ctypes.POINTER(ml.LoomTensor), ctypes.POINTER(ml.LoomTensor)])
    rc_null = int(fn(None, ctypes.byref(good)))
    rc_ndim = int(fn(ctypes.byref(bad), ctypes.byref(good)))
    check('A7 参数向量 rc==-2 (NULL/ndim=0)',
          rc_null == ml.LOOM_ERR_PARAM and rc_ndim == ml.LOOM_ERR_PARAM,
          'null=%d ndim=%d' % (rc_null, rc_ndim))

    # ckernels
    k = ml.ModuleHandle.load(CK_DLL)
    check('A8 ckernels 加载+字段', k.module_id == 'ckernels' and k.official == 1
          and k.provides == ('ckernels.aabbs', 'ckernels.collide') and k.depends == (),
          'id=%s provides=%s' % (k.module_id, k.provides))
    check('A9 ckernels has 正反',
          k.has('ckernels.aabbs') is True and k.has('module_ref.echo') is False)
    check('A10 ckernels init', k.init() == 0 and k.inited is True)

    # aabbs 热路径: DLL vs 纯 Python 标量基准逐位
    import fastpath
    rng = np.random.default_rng(20260908)
    ok_bit = True
    for (n, V) in [(137, 37), (1, 1), (500, 2035), (0, 0)]:
        vh = np.ascontiguousarray(rng.standard_normal((n, V, 4)), dtype=np.float64)
        m3 = np.ascontiguousarray(rng.standard_normal((n, 4, 3)), dtype=np.float64)
        mn = np.zeros((n, 3), dtype=np.float64)
        mx = np.zeros((n, 3), dtype=np.float64)
        fn_ab = k.get_fn('loom_aabbs_minmax', ctypes.c_int32,
                         [ctypes.POINTER(ctypes.c_double)] * 4
                         + [ctypes.c_int64, ctypes.c_int64])
        rc = int(fn_ab(vh.ctypes.data_as(ctypes.POINTER(ctypes.c_double)),
                       m3.ctypes.data_as(ctypes.POINTER(ctypes.c_double)),
                       mn.ctypes.data_as(ctypes.POINTER(ctypes.c_double)),
                       mx.ctypes.data_as(ctypes.POINTER(ctypes.c_double)),
                       ctypes.c_int64(n), ctypes.c_int64(V)))
        if n == 0:
            # n=0: numpy 参考无意义 (np.min 空数组报错); 只测 C 内核 rc==0
            if rc != 0:
                ok_bit = False
                print('   [aabbs] n=0 rc=%d (期望 0)' % rc)
            continue
        pmn = np.zeros((n, 3), dtype=np.float64)
        pmx = np.zeros((n, 3), dtype=np.float64)
        # B1 收尾 (2026-10-16): _aabbs_minmax_impl (numba 标量版) 已随 B1 退役;
        # 改用保留的 _aabbs_minmax_np (numpy dgemm). 断言口径从"逐位 0"放宽到
        # D6 标准 1e-7 (dgemm 分块求和与 C 逐位标量有 ~4 ULP 差; 同
        # ckernels_val_check.py 对 C vs numpy 的判据).
        fastpath._aabbs_minmax_np(vh, m3, pmn, pmx)
        d1 = float(np.max(np.abs(mn - pmn))) if mn.size else 0.0
        d2 = float(np.max(np.abs(mx - pmx))) if mx.size else 0.0
        if rc != 0 or d1 > 1e-7 or d2 > 1e-7:
            ok_bit = False
            print('   [aabbs] n=%d V=%d rc=%d dmn=%g dmx=%g' % (n, V, rc, d1, d2))
    check('A11 aabbs DLL vs numpy 参考 (D6: maxdiff<=1e-7, 含 n=0)', ok_bit)

    h.unload()
    k.unload()
    check('A12 unload 后 get_fn 抛 ModuleNotAvailable',
          _raises(ml.ModuleNotAvailable, lambda: h.get_fn('module_ref_echo',
                                                          ctypes.c_int32, [])))
    return h


def _raises(exc, fn):
    try:
        fn()
    except exc:
        return True
    except Exception as e:
        print('   [raises] 期望 %s 实得 %r' % (exc.__name__, e))
        return False
    return False


# ---------------------------------------------------------------------------
# B/C 热重载 + init 重入
# ---------------------------------------------------------------------------
def case_c():
    import numpy as np
    h = ml.ModuleHandle.load(REF_DLL, expected_module_id='module_ref')
    h.init()
    a = np.arange(24, dtype=np.float64).reshape(2, 3, 4)
    rc1, out1, _ = _echo(h, a)
    h2 = h.hot_reload()
    check('C1 hot_reload 返回新句柄', h2 is not h and h2.module_id == 'module_ref'
          and h2.inited is True, 'id=%s inited=%s' % (h2.module_id, h2.inited))
    rc2, out2, src = _echo(h2, a)
    check('C2 hot_reload 后 echo 逐位', rc1 == 0 and rc2 == 0
          and float(np.max(np.abs(out1 - src))) == 0.0
          and float(np.max(np.abs(out2 - src))) == 0.0)
    check('C3 hot_reload 后 info 一致',
          h2.version == '1.0.0' and h2.official == 1
          and h2.provides == ('module_ref.echo',))
    h2.deinit()
    h2.deinit()
    check('C4 deinit 幂等', h2.inited is False)
    h2.init()
    check('C5 deinit 后 init 可重入', h2.inited is True)
    h2.unload()
    return h2


# ---------------------------------------------------------------------------
# D 负向
# ---------------------------------------------------------------------------
def case_d():
    tmp = tempfile.mkdtemp(prefix='loom_mlchk_')
    try:
        check('D1 路径不存在 → ModuleValidationFailed',
              _raises(ml.ModuleValidationFailed,
                      lambda: ml.ModuleHandle.load(os.path.join(tmp, 'nope.dll'))))
        check('D2 期望 module_id 不符 → ModuleValidationFailed',
              _raises(ml.ModuleValidationFailed,
                      lambda: ml.ModuleHandle.load(REF_DLL, expected_module_id='ckernels')))
        fake = os.path.join(tmp, 'fake.dll')
        with open(fake, 'wb') as f:
            f.write(b'MZ' + b'\x00' * 510)
        check('D3 非法 PE → ModuleValidationFailed',
              _raises(ml.ModuleValidationFailed, lambda: ml.ModuleHandle.load(fake)))
        h = ml.ModuleHandle.load(REF_DLL)
        check('D4 不存在的导出 → ModuleValidationFailed',
              _raises(ml.ModuleValidationFailed,
                      lambda: h.get_fn('no_such_symbol', ctypes.c_int32, [])))
        h.unload()
        check('D5 未加载调用 init → ModuleNotAvailable',
              _raises(ml.ModuleNotAvailable, lambda: h.init()))
        # 加载失败不残留 _LIVE
        before = len(ml._LIVE)
        try:
            ml.ModuleHandle.load(os.path.join(tmp, 'nope.dll'))
        except ml.ModuleValidationFailed:
            pass
        check('D6 失败不残留 _LIVE', len(ml._LIVE) == before,
              '%d -> %d' % (before, len(ml._LIVE)))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# ---------------------------------------------------------------------------
# E 逃生门解析
# ---------------------------------------------------------------------------
def case_e():
    old = os.environ.pop('LOOM_NO_DLL', None)
    try:
        check('E1 未设 → 空集', ml.no_dll_skips() == set(), repr(ml.no_dll_skips()))
        os.environ['LOOM_NO_DLL'] = '*'
        check("E2 '*' → {'*'}", ml.no_dll_skips() == {'*'})
        os.environ['LOOM_NO_DLL'] = 'ckernels, module_ref'
        check("E3 'a,b' → {'a','b'}",
              ml.no_dll_skips() == {'ckernels', 'module_ref'}, repr(ml.no_dll_skips()))
        os.environ['LOOM_NO_DLL'] = '  '
        check('E4 空白 → 空集', ml.no_dll_skips() == set())
    finally:
        os.environ.pop('LOOM_NO_DLL', None)
        if old is not None:
            os.environ['LOOM_NO_DLL'] = old


def main():
    print('=== module_contract_check (M1-3) ===')
    case_a()
    case_c()
    case_d()
    case_e()
    bad = results.count(False)
    print('--- %d 项: PASS %d / FAILED %d ---'
          % (len(results), results.count(True), bad))
    print('ALL PASS' if bad == 0 else 'FAILED %d 项' % bad)
    return 0 if bad == 0 else 1


if __name__ == '__main__':
    sys.exit(main())
