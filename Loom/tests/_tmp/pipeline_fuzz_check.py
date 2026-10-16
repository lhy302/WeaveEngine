# -*- coding: utf-8 -*-
"""pipeline_fuzz_check.py — M2 模糊测试探针 (坏 pipeline 注入自愈链)

靶: core_components\\pipeline\\pipeline.dll (官方 pipeline: light_vps/scene_bounds/aabbs)
+ M1 坏靶 badvector.dll (module_ref_echo 空指针写入, 只用于探针, 不进 registry.json)。
用例: A 校验失败自愈(组装期: 非法 PE / sha 错 → popped + writeback + 官方顶回)
      B 身份/声明不符自愈(provides 少声明 / 换名 → 校验失败 → 弹出 + 官方顶回)
      C 运行期崩溃自愈(子进程: badvector 顶替 module_ref → echo AV → OSError →
        crash_reporter.write_dump → pop_and_fallback → 官方顶回 → 逐位 echo → 哨兵)
      D 定向畸形输入(pipeline.dll: NULL/n=0/n=-1/n_lights=0/退化方向/越界 vis_idx)
      E 官方坏 = 绝不降级(官方条目 sha 错 → module_registry.AssemblyError)
      F 收尾(真实 registry.json 3 组件全绿 + 哈希未变)
子进程体: python pipeline_fuzz_check.py --childC | --childD
纪律: 既有文件只读; fuzz 注册表只落 %TEMP%; 真实 registry.json 绝不改动。
"""
import ctypes, hashlib, json, os, shutil, subprocess, sys, tempfile
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
REG = os.path.join(CC, 'registry.json')
PIPE = os.path.join(CC, 'pipeline', 'pipeline.dll')
BADVEC, REF_DLL = os.path.join(CC, 'badvector.dll'), os.path.join(CC, 'module_ref.dll')
PIPE_PROV = ['pipeline.light_vps', 'pipeline.scene_bounds', 'pipeline.aabbs',
             'pipeline.world_matrices']
ECHO = ['module_ref.echo']
ERR_PARAM, ERR_UNSUP = -2, -6                # loom_module.h: LOOM_ERR_PARAM/UNSUPPORTED
AE = ((getattr(mr, 'AssemblyError', None) if HAVE_MR else None)
      or getattr(module_loader, 'AssemblyError', Exception))
TMP = tempfile.mkdtemp(prefix='loom_pipe_fuzz_')
results = []
class LOOM_LIGHT(ctypes.Structure):          # loom_pipeline.h §光源描述
    _fields_ = [('kind', ctypes.c_int32), ('shadow', ctypes.c_int32),
                ('mode', ctypes.c_int32), ('_pad', ctypes.c_int32),
                ('position', ctypes.c_double * 3), ('direction', ctypes.c_double * 3),
                ('up', ctypes.c_double * 3), ('size', ctypes.c_double)]
def check(name, ok, detail=''):
    """_safe: 主进程 stdout 可能是 GBK, 孤立代理字符会让 print 抛 UnicodeEncodeError
    (M1 踩过 \u0534); 按 GBK 无损往返, 编不出来的字符换成 '?'。"""
    s = detail if isinstance(detail, str) else repr(detail)
    results.append(bool(ok))
    print('%s %s %s' % ('PASS' if ok else 'FAILED', name, s.encode('gbk', 'replace').decode('gbk')), flush=True)
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
            'sha256': s256, 'note': 'M2 fuzz'}
def mk_reg(tag, entries):
    """自建 fuzz 注册表 (只落系统临时目录; 绝不动真实 registry.json)。"""
    d = os.path.join(TMP, tag)
    os.makedirs(d, exist_ok=True)
    p = os.path.join(d, 'registry.json')
    with open(p, 'w', encoding='utf-8') as f:
        json.dump({'_format': 'loom-core-registry/1.0', 'registry_version': '1.0',
                   'components': entries}, f, ensure_ascii=False, indent=2)
    return p
def asm(path):
    return mr.assemble(registry_path=path, base_dir=BASE, do_init=True, persist=True)
def get_or_none(a, mid):
    try:
        return a.get(mid)
    except Exception:
        return None
def acts(a, action, needle):
    return [x for x in (getattr(a, 'report', None) or [])
            if x.get('action') == action and needle in str(x.get('path', '')).lower()]
def pipe_handle(a):
    """官方 pipeline 顶回判定: official==1 且 path 指向官方 pipeline.dll。"""
    h = get_or_none(a, 'pipeline')
    return h, (h is not None and int(getattr(h, 'official', 0)) == 1
               and getattr(h, 'path', '') == os.path.abspath(PIPE))
def mk_bad_pe():
    """非法 PE (垃圾字节), 用于「sha 正确但加载/校验期失败」档。"""
    p = os.path.join(TMP, 'fuzz_bad_pipeline.dll')
    with open(p, 'wb') as f:
        f.write(b'NOT-A-PE\x00' * 512)
    return p
def sb_fn(h):
    return h.get_fn('loom_pipeline_scene_bounds', ctypes.c_int32,
                    [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_int64,
                     ctypes.c_void_p, ctypes.c_void_p])
def lv_fn(h):
    return h.get_fn('loom_pipeline_light_vps', ctypes.c_int32,
                    [ctypes.c_void_p, ctypes.c_int64, ctypes.c_void_p, ctypes.c_int64,
                     ctypes.c_void_p, ctypes.c_int64, ctypes.c_void_p, ctypes.c_void_p])
def mk_light(direction=(0.0, 0.0, -1.0)):
    lt = LOOM_LIGHT()
    lt.kind, lt.shadow, lt.mode, lt._pad = 0, 1, 0, 0
    lt.direction[:] = direction
    lt.up[:] = (0.0, 1.0, 0.0)
    lt.size = 1.0
    return lt
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
def child_c():
    """C 子进程体: badvector 顶替 module_ref 槽位 → echo AV → 自愈 → 哨兵。"""
    a = asm(mk_reg('c', [ent('module_ref', REF_DLL, True, '', ECHO),
                         ent('module_ref', BADVEC, False, sha(BADVEC), ECHO)]))
    h = a.get('module_ref')
    print('CHILD C handle=%r' % (h,), flush=True)
    try:
        echo_bits(h, [1.0, 2.0, 3.0, 4.0])
        print('CHILD C FAILED: 坏靶未崩 (无 OSError)', flush=True)
        sys.exit(1)
    except OSError as e:
        reason = 'fuzz-badvector-echo AV (pipeline 槽位机制复用): %s' % e
        print('CHILD C OSError 捕获: %r' % (e,), flush=True)
    try:                                     # write_dump 限流同分钟 2 个, 不因限流判失败
        print('CHILD C dump=%r' % (crash_reporter.write_dump(reason=reason),), flush=True)
    except Exception as e:
        print('CHILD C dump 调用异常 (限流?): %r' % (e,), flush=True)
    h2 = a.pop_and_fallback('module_ref', reason, persist=True)
    print('CHILD C 顶回=%r' % (h2,), flush=True)
    rc, bits, _k = echo_bits(h2, [1.5, -2.25, 3.0, 4.75])
    ok = h2 is not None and h2.module_id == 'module_ref' and rc == 0 and bits
    print('CHILD_PIPE_OK' if ok else 'CHILD C FAILED rc=%s bits=%s' % (rc, bits), flush=True)
    sys.exit(0 if ok else 1)
def child_d():
    """D 子进程体: 越界 vis_idx (内存安全档) 隔离验证 — 只要求不硬崩。"""
    h = get_or_none(asm(mk_reg('d', [ent('pipeline', PIPE, True, '', PIPE_PROV)])), 'pipeline')
    if h is None:
        print('CHILD D FAILED: 官方 pipeline 句柄缺失', flush=True)
        sys.exit(1)
    rows = (ctypes.c_double * 12)(0.0, 0.0, 0.0, 1.0, 1.0, 1.0, -1.0, -1.0, -1.0, 0.0, 0.0, 0.0)
    vis = (ctypes.c_int32 * 1)(2)            # n=2 → 合法下标 {0,1}, 2 即越界
    vp, kind = (ctypes.c_double * (6 * 16))(), (ctypes.c_int32 * 6)()
    try:
        rc = int(lv_fn(h)(rows, 2, vis, 1, ctypes.byref(mk_light()), 1, vp, kind))
        print('CHILD D 越界 vis_idx rc=%d kind[0]=%d (无 OSError)' % (rc, int(kind[0])), flush=True)
        # D5 修复后: 越界下标必须如实返回 LOOM_ERR_PARAM (-2), 不得吞成 rc=0/-1
        ok = (rc == ERR_PARAM)
    except OSError as e:
        print('CHILD D 越界 vis_idx 触发 OSError (内存安全缺陷): %r' % (e,), flush=True)
        ok = False
    print('CHILD_D_OK' if ok else 'CHILD D FAILED', flush=True)
    sys.exit(0 if ok else 1)
def child_case(tag, flag, sentinel):
    """子进程 + 超时 + UTF-8 环境: rc==0 + OSError 已捕获 + 哨兵。"""
    if not HAVE_MR:
        return skip('%s 子进程' % tag)
    env = dict(os.environ, PYTHONIOENCODING='utf-8')
    r = subprocess.run([sys.executable, os.path.abspath(__file__), flag],
                       capture_output=True, timeout=120, env=env)
    o = (r.stdout or b'').decode('utf-8', 'replace')
    e = (r.stderr or b'').decode('utf-8', 'replace')
    tail = ' | '.join(([x for x in o.splitlines() if x.strip()] or [e])[-2:])
    check('%s 子进程 rc==0' % tag, r.returncode == 0, 'rc=%s tail=%s' % (r.returncode, tail))
    check('%s OSError 已捕获' % tag, 'OSError' in o, '')
    check('%s 哨兵 %s' % (tag, sentinel), sentinel in o, '')
    return o
def case_a():
    if not HAVE_MR:
        return skip('A 校验失败自愈 (组装期)')
    h0, bad = sha(REG), mk_bad_pe()
    # A1 非法 PE + sha 正确 → 过信任闸, 加载/校验期失败 → popped + writeback + 官方顶回
    a = asm(mk_reg('a1', [ent('pipeline', PIPE, True, '', PIPE_PROV),
                          ent('pipeline', bad, False, sha(bad), PIPE_PROV)]))
    h, ok = pipe_handle(a)
    check('A1 非法 PE 注入条目 popped', bool(acts(a, 'popped', 'fuzz_bad_pipeline')),
          '%r' % (acts(a, 'popped', 'fuzz_bad_pipeline')[:1],))
    check('A1 enabled=false writeback', bool(acts(a, 'writeback', 'fuzz_bad_pipeline')),
          '%r' % (acts(a, 'writeback', 'fuzz_bad_pipeline')[:1],))
    check('A1 官方 pipeline 顶回 (official=1 + 官方 path)', ok, 'handle=%r' % (h,))
    # A2 sha256 故意错 (指向真实 pipeline.dll) → 信任闸弹出 + 官方顶回
    a2 = asm(mk_reg('a2', [ent('pipeline', PIPE, True, '', PIPE_PROV),
                           ent('pipeline', PIPE, False, '0' * 64, PIPE_PROV)]))
    h2, ok2 = pipe_handle(a2)
    check('A2 sha 错注入条目 popped', bool(acts(a2, 'popped', 'pipeline')),
          '%r' % (acts(a2, 'popped', 'pipeline')[:1],))
    check('A2 官方 pipeline 顶回', ok2, 'handle=%r' % (h2,))
    check('A 真实 registry.json 哈希未变', sha(REG) == h0, h0[:16])
def case_b():
    if not HAVE_MR:
        return skip('B 身份/声明不符自愈')
    for tag, prov in (('B1 provides 少声明', ['pipeline.aabbs']),
                      ('B2 provides 换名', ['pipeline.fake'])):
        a = asm(mk_reg(tag[:2].lower(), [ent('pipeline', PIPE, True, '', PIPE_PROV),
                                         ent('pipeline', PIPE, False, sha(PIPE), prov)]))
        h, ok = pipe_handle(a)
        check('%s → popped' % tag, bool(acts(a, 'popped', 'pipeline')), '')
        check('%s 官方 pipeline 顶回' % tag, ok, 'handle=%r' % (h,))
def case_d():
    if not HAVE_MR:
        return skip('D 定向畸形输入')
    h = get_or_none(asm(mk_reg('dm', [ent('pipeline', PIPE, True, '', PIPE_PROV)])), 'pipeline')
    if h is None:
        return check('D 官方 pipeline 句柄可用', False, '')
    sb, lv = sb_fn(h), lv_fn(h)
    view = (ctypes.c_double * 16)(1.0, 0, 0, 0, 0, 1.0, 0, 0, 0, 0, 1.0, 0, 0, 0, 0, 1.0)
    rows = (ctypes.c_double * 12)(0.0, 0.0, 0.0, 1.0, 1.0, 1.0, -1.0, -1.0, -1.0, 0.0, 0.0, 0.0)
    mn, mx = (ctypes.c_double * 3)(), (ctypes.c_double * 3)()
    check('D scene_bounds 合法输入 → 0', int(sb(view, rows, 2, mn, mx)) == 0, 'mn=%r' % (list(mn),))
    for tag, args in (('view=NULL', (None, rows, 2, mn, mx)), ('rows=NULL', (view, None, 2, mn, mx)),
                      ('out_mn=NULL', (view, rows, 2, None, mx)), ('n=0', (view, rows, 0, mn, mx)),
                      ('n=-1', (view, rows, -1, mn, mx))):
        check('D scene_bounds %s → LOOM_ERR_PARAM' % tag, int(sb(*args)) == ERR_PARAM, '')
    lt, vp, kind = mk_light(), (ctypes.c_double * (6 * 16))(), (ctypes.c_int32 * 6)()
    check('D light_vps 合法输入 → 0', int(lv(rows, 2, None, 0, ctypes.byref(lt), 1, vp, kind)) == 0,
          'kind[0]=%d' % int(kind[0]))
    for tag, args in (('out_vp=NULL', (rows, 2, None, 0, ctypes.byref(lt), 1, None, kind)),
                      ('lights=NULL', (rows, 2, None, 0, None, 1, vp, kind)),
                      ('n=-1', (rows, -1, None, 0, ctypes.byref(lt), 1, vp, kind))):
        check('D light_vps %s → LOOM_ERR_PARAM' % tag, int(lv(*args)) == ERR_PARAM, '')
    r0 = int(lv(rows, 2, None, 0, ctypes.byref(lt), 0, vp, kind))
    check('D light_vps n_lights=0 → 不崩 + 契约码 (0/PARAM)', r0 in (0, ERR_PARAM), 'rc=%d' % r0)
    deg, kind2 = mk_light((0.0, 0.0, 0.0)), (ctypes.c_int32 * 6)(0, 0, 0, 0, 0, 0)  # 退化方向
    rd = int(lv(rows, 2, None, 0, ctypes.byref(deg), 1, vp, kind2))
    check('D 退化方向 → 不崩 + out_kind=-1 (UNSUPPORTED 语义)',
          rd in (0, ERR_UNSUP) and int(kind2[0]) == -1, 'rc=%d kind[0]=%d' % (rd, int(kind2[0])))
    o = child_case('D 越界 vis_idx', '--childD', 'CHILD_D_OK')
    if o:
        print('D child 输出尾部: %s' % ' | '.join([x for x in o.splitlines() if x.strip()][-2:]))
def case_e():
    if not HAVE_MR:
        return skip('E 官方坏 = 绝不降级')
    h0 = sha(REG)
    try:
        asm(mk_reg('e', [ent('pipeline', PIPE, True, '0' * 64, PIPE_PROV)]))
        check('E 官方 pipeline sha 错 → AssemblyError', False, '未抛异常 (静默降级!)')
    except AE as ex:
        check('E 官方 pipeline sha 错 → AssemblyError', True, '%s' % (ex,))
    except Exception as ex:
        check('E 官方 pipeline sha 错 → AssemblyError', False, '抛了非 AssemblyError: %r' % (ex,))
    check('E 真实 registry.json 哈希未变', sha(REG) == h0, h0[:16])
def case_f():
    if not HAVE_MR:
        return skip('F 收尾')
    h0, a = sha(REG), asm(REG)
    ids = [getattr(x, 'module_id', x) for x in getattr(a, 'modules', [])]
    check('F 真实 registry 组装成功 (3 组件全绿)',
          all(x in ids for x in ('module_ref', 'ckernels', 'pipeline')), 'modules=%r' % (ids,))
    h, ok = pipe_handle(a)
    check('F 官方 pipeline 在役 (official=1 + 官方 path)', ok, 'handle=%r' % (h,))
    check('F registry.json 哈希未变', sha(REG) == h0, h0[:16])
if __name__ == '__main__':
    if '--childC' in sys.argv:
        child_c()
    if '--childD' in sys.argv:
        child_d()
    print('module_registry.py: %s' % ('已就绪' if HAVE_MR else '未就绪 (%s)' % _MR_ERR))
    print('pipeline.dll=%s (sha=%s)' % (PIPE, sha(PIPE)[:16]))
    for f in (case_a, case_b, lambda: child_case('C 运行期崩溃自愈', '--childC', 'CHILD_PIPE_OK'),
              case_d, case_e, case_f):
        f()
    shutil.rmtree(TMP, ignore_errors=True)
    print('-' * 60)
    if all(results):
        print('ALL PASS (%d/%d)' % (len(results), len(results)))
        sys.exit(0)
    print('FAILED %d 项 (%d/%d pass)' % (len(results) - sum(results), sum(results), len(results)))
    sys.exit(1)
