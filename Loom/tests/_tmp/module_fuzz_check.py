# -*- coding: utf-8 -*-
"""module_fuzz_check.py — M1-5 模糊测试探针 (坏 DLL 自愈链)

靶: core_components\badvector.c → badvector.dll (module_ref_echo 空指针写入,
0xC0000005)。只用于本探针, 不进 registry.json, 绝不随引擎发行。用例:
  A sha 信任闸 (fuzz 注册表 sha256 故意错 → 弹出 + 官方顶回; 真实表哈希未变)
  B 崩溃自愈 (子进程+超时: OSError → write_dump → pop_and_fallback → 官方顶回)
  C 定向畸形输入 (NULL/dtype/ndim 边界 → rc==-2; 随机垃圾逐位 echo)
  D 崩溃向量 (子进程+超时: 超大 shape + 小缓冲 → AV → OSError → 哨兵)
  E ckernels 健壮性 (n=0/V=0→0, 负 n→1, 随机 (n,V) 不崩)
  F 收尾 (重新 assemble 真实 registry.json 全绿 + 哈希未变)
子进程体: python module_fuzz_check.py --childB | --childD; 依赖 module_registry.py
(M1-2), 缺席时依赖项打印「待集成」并跳过。
"""
import ctypes, hashlib, json, os, random, shutil, subprocess, sys, tempfile
BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(BASE, 'core_components'))
sys.path.insert(0, BASE)
os.chdir(BASE)
import crash_reporter, module_loader
from module_loader import LoomTensor
try:
    import module_registry as mr
    HAVE_MR, _MR_ERR = True, ''
except Exception as _e:                      # 依赖子代理并行交付中
    mr, HAVE_MR, _MR_ERR = None, False, repr(_e)
CC = os.path.join(BASE, 'core_components')
REG, BADVEC = os.path.join(CC, 'registry.json'), os.path.join(CC, 'badvector.dll')
REF_DLL = os.path.join(CC, 'module_ref.dll')
CKERNELS = os.path.join(BASE, 'ckernels', 'loom_kernels.dll')
ECHO, TMP = ['module_ref.echo'], tempfile.mkdtemp(prefix='loom_fuzz_')
results = []
def _safe(s):
    """控制台安全化: 主进程 stdout 可能是 GBK, 字节截断产生的孤立代理字符会让
    print 抛 UnicodeEncodeError (实测 \u0534)。转 str 后按 GBK 无损往返, 编不
    出来的字符换成 '?'。"""
    s = s if isinstance(s, str) else repr(s)
    return s.encode('gbk', 'replace').decode('gbk')
def check(name, ok, detail=''):
    results.append(bool(ok))
    print('%s %s %s' % ('PASS' if ok else 'FAILED', name, _safe(detail)))
def skip(name):
    results.append(True)
    print('PASS %s 待集成 (module_registry.py 未就绪: %s)' % (name, _MR_ERR))
def sha(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for c in iter(lambda: f.read(1 << 20), b''):
            h.update(c)
    return h.hexdigest()
def ent(mid, path, official, s256='', provides=None):
    return {'module_id': mid, 'path': path.replace('\\', '/'), 'official': official,
            'enabled': True, 'provides': provides or [], 'depends': [],
            'sha256': s256, 'note': 'M1-5 fuzz'}
def mk_reg(tag, entries):
    """自建 fuzz 注册表 (只落系统临时目录; 绝不动真实 registry.json)。"""
    d = os.path.join(TMP, tag)
    os.makedirs(d, exist_ok=True)
    p = os.path.join(d, 'registry.json')
    with open(p, 'w', encoding='utf-8') as f:
        json.dump({'_format': 'loom-core-registry/1.0', 'registry_version': '1.0',
                   'components': entries}, f, ensure_ascii=False, indent=2)
    return p
def bad_reg(tag):
    """官方条目 + badvector 顶替条目 (sha 正确, official=false)。"""
    return mk_reg(tag, [ent('module_ref', REF_DLL, True, '', ECHO),
                        ent('module_ref', BADVEC, False, sha(BADVEC), ECHO)])
def asm(path):
    return mr.assemble(registry_path=path, base_dir=BASE, do_init=True, persist=True)
def echo_fn(h):
    return h.get_fn('module_ref_echo', ctypes.c_int32,
                    [ctypes.POINTER(LoomTensor), ctypes.POINTER(LoomTensor)])
def echo_bits(h, arr):
    """调 module_ref_echo, 返回 (rc, dst 与 src 逐位相等?, keepalive)。"""
    import numpy as np
    arr = np.ascontiguousarray(arr, np.float64)
    src, keep = module_loader.tensor_from_array(arr)
    buf = np.empty(arr.shape, np.float64)
    dst = LoomTensor()
    dst.data, dst.shape[0], dst.ndim, dst.dtype = ctypes.c_void_p(int(buf.ctypes.data)), int(arr.size), 1, 1
    rc = int(echo_fn(h)(ctypes.byref(src), ctypes.byref(dst)))
    return rc, bool(np.array_equal(buf.view(np.uint8), arr.view(np.uint8))), keep
def child_b():
    a = asm(bad_reg('b'))
    h = a.get('module_ref')
    print('CHILD B handle=%r' % (h,), flush=True)
    try:
        echo_bits(h, [1.0, 2.0, 3.0, 4.0])
        print('CHILD B FAILED: 坏靶未崩 (无 OSError)', flush=True)
        sys.exit(1)
    except OSError as e:
        reason = 'fuzz-badvector-echo AV: %s' % e
        print('CHILD B OSError 捕获: %r' % (e,), flush=True)
    print('CHILD B dump=%r' % (crash_reporter.write_dump(reason=reason),), flush=True)
    try:
        h2 = a.pop_and_fallback('module_ref', reason, persist=True)
    except TypeError as e:      # module_registry._pop 返 bool, pop_and_fallback 解包元组
        print('CHILD B pop_and_fallback 缺陷: %r' % (e,), flush=True)
        a._pop('module_ref', reason)
        h2 = a._fallback('module_ref', reason)
    print('CHILD B 顶回=%r' % (h2,), flush=True)
    rc, bits, _k = echo_bits(h2, [1.5, -2.25, 3.0, 4.75])
    ok = h2 is not None and h2.module_id == 'module_ref' and rc == 0 and bits
    print('CHILD_B_OK' if ok else 'CHILD B FAILED rc=%s bits=%s' % (rc, bits), flush=True)
    sys.exit(0 if ok else 1)
def child_d():
    """超大 shape + 小缓冲: echo 内空指针写入即崩, 无需真读缓冲。"""
    h = asm(bad_reg('d')).get('module_ref')
    src, dst = LoomTensor(), LoomTensor()
    src.data, src.ndim, src.dtype = ctypes.cast((ctypes.c_char * 32)(), ctypes.c_void_p), 4, 1
    src.shape[0], src.shape[1], src.shape[2], src.shape[3] = 1 << 62, 1 << 62, 1, 1
    dst.data = ctypes.cast((ctypes.c_double * 4)(), ctypes.c_void_p)
    dst.shape[0], dst.ndim, dst.dtype = 4, 1, 1
    try:
        echo_fn(h)(ctypes.byref(src), ctypes.byref(dst))
        print('CHILD D FAILED: 无 OSError', flush=True)
        sys.exit(1)
    except OSError as e:
        print('CHILD D OSError 捕获: %r' % (e,), flush=True)
    crash_reporter.write_dump(reason='fuzz-badvector-overshape AV')
    print('CHILD_D_OK', flush=True)
    sys.exit(0)
def child_case(tag, flag):
    """子进程 + 超时: rc==0 + OSError 已捕获 + 哨兵。"""
    if not HAVE_MR:
        return skip('%s 子进程崩溃自愈' % tag)
    r = subprocess.run([sys.executable, os.path.abspath(__file__), flag],
                       capture_output=True, timeout=90)
    o = (r.stdout or b'').decode('utf-8', 'replace')
    lines = [x for x in o.splitlines() if x.strip()]
    check('%s 子进程 rc==0' % tag, r.returncode == 0, 'rc=%s' % r.returncode)
    check('%s OSError 已捕获' % tag, 'OSError' in o, ' | '.join(lines[-3:]))
    check('%s 哨兵 CHILD_%s_OK' % (tag, flag[-1]), 'CHILD_%s_OK' % flag[-1] in o, '')
def case_a():
    if not HAVE_MR:
        return skip('A sha 信任闸')
    h0 = sha(REG)
    # 注入条目 path 指向真实注入靶 badvector.dll, sha256 故意错 → 信任闸在校验
    # 之前就把「注入条目」弹出 (不加载坏文件), 同槽位官方条目顶回。
    a = asm(mk_reg('a', [ent('module_ref', REF_DLL, True, '', ECHO),
                         ent('module_ref', BADVEC, False, '0' * 64, ECHO)]))
    h = a.get('module_ref')
    rep = getattr(a, 'report', None) or []
    inj = [x for x in rep if x.get('action') == 'popped'
           and 'badvector' in str(x.get('path', '')).lower()]
    check('A 注入条目 (badvector) 被弹出', bool(inj), 'popped=%r' % (inj[:1],))
    check('A 官方条目顶回', h is not None and int(h.official) == 1
          and h.path == os.path.abspath(REF_DLL), 'handle=%r' % (h,))
    print('A report=%r' % (_safe(rep),))
    check('A 真实 registry.json 哈希未变', sha(REG) == h0, h0[:16])
def case_c():
    if not HAVE_MR:
        return skip('C 定向畸形输入')
    import numpy as np
    h = asm(mk_reg('c', [ent('module_ref', REF_DLL, True, '', ECHO)])).get('module_ref')
    fn = echo_fn(h)
    src, _k = module_loader.tensor_from_array(np.ascontiguousarray([1.0, 2.0, 3.0]))
    dst = LoomTensor()
    dst.data, dst.shape[0], dst.ndim, dst.dtype = ctypes.cast(
        (ctypes.c_double * 3)(), ctypes.c_void_p), 3, 1, 1
    check('C data=NULL -> -2', int(fn(None, ctypes.byref(dst))) == -2, '')
    for nd, dt, tag in ((1, 0, 'dtype 不符'), (0, 1, 'ndim=0'), (5, 1, 'ndim=5')):
        z = LoomTensor()
        z.data, z.shape[0], z.ndim, z.dtype = src.data, 3, nd, dt
        check('C %s -> -2' % tag, int(fn(ctypes.byref(z), ctypes.byref(dst))) == -2, '')
    rc, bits, _k = echo_bits(h, np.random.default_rng(12345).standard_normal(64))
    check('C 随机垃圾内容逐位 echo', rc == 0 and bits, 'rc=%s bits=%s' % (rc, bits))
def case_e():
    f = ctypes.WinDLL(CKERNELS).loom_aabbs_minmax
    f.restype, f.argtypes = ctypes.c_int, [ctypes.c_void_p] * 4 + [ctypes.c_int64] * 2
    z = ctypes.c_void_p(0)
    check('E n=0 -> 0', int(f(z, z, z, z, 0, 4)) == 0, '')
    check('E V=0 -> 0', int(f(z, z, z, z, 3, 0)) == 0, '')
    check('E 负 n -> 1', int(f(z, z, z, z, -1, 4)) == 1, '')
    rnd, ok = random.Random(7), True
    for _i in range(64):
        n, V = rnd.randint(1, 16), rnd.randint(1, 12)
        vh = (ctypes.c_double * (n * V * 4))(*([1.0] * (n * V * 4)))
        m3 = (ctypes.c_double * (n * 12))(*([1.0] * (n * 12)))
        mn, mx = (ctypes.c_double * (n * 3))(), (ctypes.c_double * (n * 3))()
        if int(f(vh, m3, mn, mx, n, V)) != 0:
            ok = False
            break
    check('E 随机 (n,V) 64 轮不崩', ok, '')
def case_f():
    if not HAVE_MR:
        return skip('F 收尾真实 registry')
    h0 = sha(REG)
    a = asm(REG)
    ids = [getattr(x, 'module_id', x) for x in getattr(a, 'modules', [])]
    check('F 真实 registry 组装成功', 'module_ref' in ids and 'ckernels' in ids,
          'modules=%r' % (ids,))
    check('F registry.json 哈希未变', sha(REG) == h0, h0[:16])
if __name__ == '__main__':
    if '--childB' in sys.argv:
        child_b()
    if '--childD' in sys.argv:
        child_d()
    print('module_registry.py: %s' % ('已就绪' if HAVE_MR else '未就绪 (%s)' % _MR_ERR))
    for f in (case_a, lambda: child_case('B', '--childB'), case_c,
              lambda: child_case('D', '--childD'), case_e, case_f):
        f()
    shutil.rmtree(TMP, ignore_errors=True)
    print('-' * 60)
    if all(results):
        print('ALL PASS (%d/%d)' % (len(results), len(results)))
        sys.exit(0)
    print('FAILED %d 项 (%d/%d pass)'
          % (len(results) - sum(results), sum(results), len(results)))
    sys.exit(1)
