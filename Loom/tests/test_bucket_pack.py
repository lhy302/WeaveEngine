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
    rc_bad3, _, _, _ = run_c(world16, sat, col, [0, 20], None)
    check('⑥ offs[K] != n_total -> rc=1 (区间未铺满)', rc_bad3 == 1, rc_bad3)

    # ⑦ R5-03 P-02: K>0 且 n_total==0 (全空桶) 必须把 out_main_n 全部写成 0
    empty16 = np.zeros((0, 16), dtype='f4')
    empty_sat = np.zeros((0,), dtype='f4')
    empty_col = np.zeros((0, 4), dtype='f4')
    cnt7 = np.full((3,), 77, dtype='i4')          # 故意填垃圾: 未写会被抓出来
    rc7, _, _, c7 = run_c(empty16, empty_sat, empty_col, [0, 0, 0, 0], None,
                          main=np.zeros((0, 24), dtype='f4'),
                          sha=np.zeros((0, 16), dtype='f4'), cnt=cnt7)
    check('⑦ K>0 & n_total==0 -> rc=0 且 out_main_n 全 0',
          rc7 == 0 and c7.tolist() == [0, 0, 0], (rc7, c7.tolist()))

    # ⑧ R5-03 Q-D1-2: 模块契约登记 (provides / has) + 版本化导出
    dll = fastpath._CK['dll']
    ct = fastpath._CK['ctypes']
    have_v1 = hasattr(dll, 'loom_bucket_pack_v1')
    have_alias = hasattr(dll, 'loom_bucket_pack')
    check('⑧ 版本化导出 loom_bucket_pack_v1 存在 (旧名保留别名)',
          have_v1 and have_alias, (have_v1, have_alias))
    dll.loom_module_has.restype = ct.c_int32
    dll.loom_module_has.argtypes = [ct.c_char_p]
    check("⑧ loom_module_has('ckernels.bucket_pack') == 1",
          int(dll.loom_module_has(b'ckernels.bucket_pack')) == 1)
    dll.loom_module_provide.restype = ct.c_char_p
    dll.loom_module_provide.argtypes = [ct.c_uint32]
    names = []
    for i in range(8):
        nm = dll.loom_module_provide(i)
        if nm is None:
            break
        names.append(nm.decode('utf-8', 'replace'))
    check('⑧ provides 列表含 ckernels.bucket_pack', 'ckernels.bucket_pack' in names, names)

    # ---------------- 入口级 (V-02 补): loom_render._prepare_bucket_frame ----------------
    # 只替换 GL 资源 (假 buffer/VAO) —— 被验证的打包/上传逻辑走**真实**代码路径。
    import time as _t
    import types as _types
    import loom_render

    class _FakeBuf:
        def __init__(self, size=0):
            self.data = bytearray(size)

        def write(self, src, offset=0):
            b = bytes(memoryview(src)) if not isinstance(src, (bytes, bytearray)) else bytes(src)
            need = offset + len(b)
            if need > len(self.data):
                self.data.extend(bytes(need - len(self.data)))
            self.data[offset:need] = b

        def read(self):
            return bytes(self.data)

    class _FakeCtx:
        def buffer(self, data=None, reserve=None):
            return _FakeBuf(reserve if reserve else (len(data) if data else 0))

        def vertex_array(self, *a, **k):
            return object()

        def texture(self, *a, **k):
            return None

    class _Mat:
        _sat_f32 = 1.0
        _rgba = None
        albedo = None
        normal_map = None
        env_map = None

    class _Mesh:
        def __init__(self, V, seed):
            self.vertices = np.random.RandomState(seed).rand(V, 3)

    class _Model:
        def __init__(self, mesh, pos):
            self.mesh = mesh
            self.renderer = _types.SimpleNamespace(material=_Mat())
            self.visible = True
            self.normal_mode = 'flat'
            self._pos = pos

    class _Eng(loom_render.RenderMixin):
        def __init__(self, models):
            self.models = models
            self.ctx = _FakeCtx()
            self.prog = object()
            self._shadow_prog = object()
            self._render_buckets = []
            self._bucket_geo = {}
            self._bucket_inst = {}
            self._bucket_frame_sig = None
            self._bucket_grp_sig = None
            self._fw32 = None
            self._main_bucket_n = {}
            self._struct_gen = 0
            self._soa_last_keys = None
            self._interp = None
            self._frustum_cull = True
            self._vp = np.eye(4)
            self.camera = _types.SimpleNamespace(x=0.0, y=0.0, z=5.0)
            self.camera_yaw = 0.0
            self.camera_pitch = 0.0
            self.camera_roll = 0.0
            self._stage_times = {}
            self._stage_calls = {}
            self._bucket_pack_state = 0
            n = len(models)
            fw = np.tile(np.eye(4), (n, 1, 1)).astype(np.float64)
            for i, m in enumerate(models):
                fw[i, 3, 0:3] = m._pos
            self._render_world = fw

        def _prof_t0(self):
            return 0.0

        def _prof_add(self, *a):
            return None

        def _mesh_key(self, m):
            return (id(m.mesh), 'flat')

        def _build_bucket_geo(self, key, model):
            ent = {'vbo': _FakeBuf(16), 'sha_vbo': _FakeBuf(16),
                   'nv': model.mesh.vertices.shape[0], 'vao': object(), 'sha_vao': object()}
            self._bucket_geo[key] = ent
            self._bucket_inst[key] = {'main': None, 'sha': None, 'n': 0}
            self._grow_bucket_inst(key, 1)
            return ent

        def _grow_bucket_inst(self, key, k):
            inst = self._bucket_inst[key]
            if k <= inst['n'] and inst['main'] is not None:
                return
            cap = max(64, k)
            inst['main'] = _FakeBuf(cap * 96)
            inst['sha'] = _FakeBuf(cap * 64)
            inst['n'] = cap
            inst.pop('stage', None)
            inst.pop('gath', None)

        def _build_bucket_vaos(self, ent, inst):
            return None

    # 规模贴近真实场景 (35 桶 / 490 实例): 每桶多实例 (k>1 才走剔除路径),
    # 后 5 桶整体落在远平面外 (identity VP) -> 剔除路径真实生效。
    meshes = [_Mesh(24 + (i % 5) * 7, 100 + i) for i in range(35)]
    ms = []
    for i, mesh in enumerate(meshes):
        far = (i >= 30)
        ms.extend(_Model(mesh, (0.0, 0.0, 50.0) if far else (0.0, 0.0, 0.0))
                  for _ in range(14))
    eng = _Eng(ms)

    def _snap(cull):
        eng._frustum_cull = cull
        mbn = eng._main_bucket_n or {}
        out = {}
        for key, idxs in eng._render_buckets:
            k = len(idxs)
            nm = int(mbn.get(key, k))
            inst = eng._bucket_inst[key]
            out[key] = (nm, inst['main'].read()[:nm * 96], inst['sha'].read()[:k * 64])
        return out

    def _run(pack, cull=True):
        eng._bucket_pack_state = 1 if pack else -1
        eng._frustum_cull = cull          # 必须在 prep 之前设置 (决定 planes 是否为 None)
        eng._bucket_frame_sig = None
        eng._prepare_bucket_frame()
        return _snap(cull)

    a = _run(True)
    b = _run(False)
    ok_entry = (set(a) == set(b) and all(a[k] == b[k] for k in a)
                and any(v[0] < len([i for _, i in eng._render_buckets]) for v in a.values())
                if a else False)
    check('入口级: _prepare_bucket_frame 在 LOOM_BUCKET_PACK=1/0 下逐字节一致',
          bool(ok_entry), 'buckets=%d' % len(a))
    check('入口级: 剔除确实生效 (存在 n_main < k 的桶)',
          any(v[0] < len(dict(eng._render_buckets)[k]) for k, v in a.items()) if a else False)

    a2 = _run(True, cull=False)
    b2 = _run(False, cull=False)
    check('入口级: 剔除关闭档同样逐字节一致',
          bool(a2) and set(a2) == set(b2) and all(a2[k] == b2[k] for k in a2))

    # 性能门禁 (2-3x 余量): C 打包 <= 0.80x Python 路径 (实测 ~0.48x), 绝对上限 12ms
    def _timed(pack, reps=20):
        eng._bucket_pack_state = 1 if pack else -1
        for _ in range(3):
            eng._bucket_frame_sig = None
            eng._prepare_bucket_frame()
        t0 = _t.perf_counter()
        for _ in range(reps):
            eng._bucket_frame_sig = None
            eng._prepare_bucket_frame()
        return (_t.perf_counter() - t0) / reps * 1000.0

    t_c = _timed(True)
    t_py = _timed(False)
    print('  入口耗时: C=%.3f ms  Python=%.3f ms  (比值 %.2f)' % (t_c, t_py, t_c / max(t_py, 1e-9)))
    check('性能门禁: 入口级 C 打包 <= 0.80x Python', t_c <= t_py * 0.80,
          'ratio=%.2f' % (t_c / max(t_py, 1e-9)))
    check('性能门禁: 入口级绝对上限 <= 12ms', t_c <= 12.0)

    print()
    print('test_bucket_pack:', 'ALL PASS' if ok else 'HAS FAILURES')
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
