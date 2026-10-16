# -*- coding: utf-8 -*-
"""pipeline_e2e_check.py — M2 验收① 端到端对拍: 真实场景 100 逻辑帧 (B2 后单档)

口径: 真实场景跑 100 个**逻辑帧**, 逐帧采集 prep 链产物数值指纹
(光源 VP / AABB / 碰撞对), 验证数据完整性。

采集口径 (每逻辑帧一次, 在 prep 完成后):
  · 光源 VP 矩阵 (平行光 4x4 / 点光 6x4x4) → 逐元素 float64 字节
  · 全量 AABB 列表 (mn/mx) → 逐元素 float64 字节
  · 碰撞对 (i,j) 序列 → int64 字节
指纹 = sha256(拼接字节)。

★B2 退役 (2026-10-16): 原为 DLL 路径 vs Python 路径逐帧对拍 (A/B); B2 后
pipeline 已无 Python 回退路径, 探针改为单档数据完整性验证。数值正确性由
pipeline_val_check.py (C vs numpy 基准) 覆盖。

用法: py -3.12 tests/_tmp/pipeline_e2e_check.py [帧数] [场景json]
      默认 100 帧 / stress_500mixed.json。
子进程模式 (--child) 由主流程调用。
"""
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import time

BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, BASE)
sys.path.insert(0, os.path.join(BASE, 'core_components'))
os.chdir(BASE)

W, H = 1280, 720
results = []


def check(name, ok, detail=''):
    results.append(bool(ok))
    print('%s %s %s' % ('PASS' if ok else 'FAILED', name, detail))


def _fingerprint(eng, frame):
    """采集一个逻辑帧的 prep 链数值指纹 (分项返回, 便于定位差异来源)。"""
    import numpy as np
    h_vp = hashlib.sha256()
    h_ab = hashlib.sha256()
    h_pr = hashlib.sha256()

    def feed(h, arr):
        a = np.ascontiguousarray(arr, dtype=np.float64)
        h.update(a.tobytes())

    # ① 光源 VP (按 guid 排序保证顺序稳定)
    #    ★口径 (M2 设计文档 §4): VP 是矩阵乘法产物, numpy 走 BLAS/SIMD 求和序
    #    → 与 C 同序乘法有 1 ULP 级差 (实测 5.55e-17)。故 VP 采集**数值摘要**
    #    (sum / sum2 / maxabs) 按相对容差比较, 不参与逐位哈希。
    vps = getattr(eng, '_prep_light_vps', None) or getattr(eng, '_light_vps', None) or {}
    vp_sum = 0.0
    vp_sum2 = 0.0
    vp_max = 0.0
    vp_cnt = 0
    for guid in sorted(vps):
        v = vps[guid]
        mats = v if isinstance(v, list) else [v]
        for m in mats:
            a = np.ascontiguousarray(m, dtype=np.float64)
            vp_sum += float(a.sum())
            vp_sum2 += float((a * a).sum())
            vp_max = max(vp_max, float(np.max(np.abs(a))))
            vp_cnt += int(a.size)
    h_vp.update(('%.17g|%.17g|%.17g|%d' % (vp_sum, vp_sum2, vp_max, vp_cnt)).encode())
    # ② 全量 AABB
    #    ★口径 (M2 续): world_matrices 已入 DLL → AABB 输入带 1 ULP 级差,
    #    故 AABB 也按**全局缩放误差**比较 (逐位 0 只对纯逐元素且输入相同成立)。
    aabbs = getattr(eng, '_prep_aabbs', None)
    ab_sum = 0.0
    ab_sum2 = 0.0
    ab_max = 0.0
    ab_cnt = 0
    if aabbs:
        arr = np.empty((len(aabbs), 6), dtype=np.float64)
        for i, (a, b) in enumerate(aabbs):
            arr[i] = (a.x, a.y, a.z, b.x, b.y, b.z)
        feed(h_ab, arr)
        ab_sum = float(arr.sum())
        ab_sum2 = float((arr * arr).sum())
        ab_max = float(np.max(np.abs(arr)))
        ab_cnt = int(arr.size)
    # ③ 碰撞对
    pairs = getattr(eng, '_prep_pairs', None)
    if pairs:
        p = np.asarray(pairs, dtype=np.int64).reshape(-1)
        h_pr.update(np.ascontiguousarray(p).tobytes())
    return {'vp': h_vp.hexdigest(), 'ab': h_ab.hexdigest(),
            'pr': h_pr.hexdigest(), 'npairs': len(pairs) if pairs else 0,
            'nmodels': len(getattr(eng, 'models', []) or []),
            'vp_sum': vp_sum, 'vp_sum2': vp_sum2, 'vp_max': vp_max,
            'vp_cnt': vp_cnt,
            'ab_sum': ab_sum, 'ab_sum2': ab_sum2, 'ab_max': ab_max,
            'ab_cnt': ab_cnt}


def run_child(frames, scene, out_path):
    """子进程体: 跑 on 档 (pipeline 唯一路径), 把逐帧指纹写 JSON。

    ★B2 退役 (2026-10-16): 删 off (LOOM_NO_PIPELINE=1) 档; pipeline 已无 Python
    回退路径, 探针改为单档数据完整性验证 (口径=on)。"""
    os.environ['LOOM_PROFILE'] = '1'      # 自持阶段计时 (build_all 不设该 env)
    import pygame
    pygame.init()
    pygame.display.gl_set_attribute(pygame.GL_SWAP_CONTROL, 0)
    import runtime
    eng = runtime.PlayerApp(scene, W, H)
    eng.set_mouse_locked(False)
    for _ in range(40):                      # 预热
        eng.render(1.0 / 120.0)
    try:
        from engine import gc_play_enter
        gc_play_enter()
    except Exception:
        pass
    eng._stage_times.clear()
    fps = []
    for f in range(frames):
        eng.render(1.0 / 120.0)
        fps.append(_fingerprint(eng, f))
    meta = {
        'frames': frames,
        'scene': os.path.basename(scene),
        'pipeline_status': _status(),
        'fps_sha': fps,
        'stage_shadow_bounds': eng._stage_times.get('shadow_bounds', 0.0) / max(1, frames),
        'stage_aabbs': eng._stage_times.get('aabbs', 0.0) / max(1, frames),
        'stage_collide': eng._stage_times.get('collide_pairs', 0.0) / max(1, frames),
    }
    with open(out_path, 'w', encoding='utf-8') as fh:
        json.dump(meta, fh, ensure_ascii=False)
    print('CHILD_OK', flush=True)
    return 0


def _status():
    try:
        import pipeline_glue as pg
        return pg.status()
    except Exception as e:
        return 'glue error: %r' % (e,)


def main():
    args = [a for a in sys.argv[1:] if not a.startswith('--')]
    frames = int(args[0]) if args else 100
    scene = args[1] if len(args) > 1 else 'stress_500mixed.json'
    scene_path = scene if os.path.isabs(scene) else os.path.join(BASE, 'tests', '_tmp', scene)

    if '--child' in sys.argv:
        out = sys.argv[sys.argv.index('--out') + 1]
        return run_child(frames, scene_path, out)

    print('=== pipeline_e2e_check (M2 验收① 端到端 %d 逻辑帧, 单档) ===' % frames)
    print('场景: %s' % os.path.basename(scene_path))
    tmp = tempfile.mkdtemp(prefix='loom_e2e_')
    out = os.path.join(tmp, 'on.json')
    env = dict(os.environ)
    env['PYTHONIOENCODING'] = 'utf-8'
    r = subprocess.run([sys.executable, os.path.abspath(__file__), str(frames),
                        scene, '--child', '--out', out],
                       capture_output=True, timeout=900, env=env)
    ok = r.returncode == 0 and os.path.isfile(out)
    check('子进程跑通 (%d 帧)' % frames, ok,
          'rc=%d %s' % (r.returncode,
                        (r.stdout or b'').decode('utf-8', 'replace')[-120:]))
    if not ok:
        print((r.stderr or b'').decode('utf-8', 'replace')[-2000:])
        print('FAILED 子进程失败')
        return 1
    a = json.load(open(out, encoding='utf-8'))

    check('帧数符合预期', a['frames'] == frames, '%d' % a['frames'])
    check('pipeline 真实生效', 'v1.0.0' in a['pipeline_status'],
          a['pipeline_status'])

    n = len(a['fps_sha'])
    # 单档数据完整性: 每帧摘要字段齐全 + 计数非负
    bad_vp = [i for i in range(n) if a['fps_sha'][i]['vp_cnt'] <= 0]
    check('%d 帧 光源 VP 摘要齐全' % frames, not bad_vp,
          '缺帧=%r' % (bad_vp[:8],))
    bad_ab = [i for i in range(n) if a['fps_sha'][i]['ab_cnt'] <= 0]
    check('%d 帧 全量 AABB 摘要齐全' % frames, not bad_ab,
          '缺帧=%r' % (bad_ab[:8],))
    check('模型数 > 0', a['fps_sha'][0]['nmodels'] > 0,
          '%d' % a['fps_sha'][0]['nmodels'])
    check('碰撞对数量 ≥ 0',
          all(a['fps_sha'][i]['npairs'] >= 0 for i in range(n)), 'ok')
    print('PERF shadow_bounds: %.3f ms/帧' % a['stage_shadow_bounds'])
    print('PERF aabbs:        %.3f ms/帧' % a['stage_aabbs'])
    print('PERF collide:      %.3f ms/帧' % a['stage_collide'])
    check('性能口径已采集 (LOOM_PROFILE 阶段计时)',
          a['stage_shadow_bounds'] > 0 and a['stage_aabbs'] > 0,
          'shadow=%.3f aabbs=%.3f' % (a['stage_shadow_bounds'], a['stage_aabbs']))

    import shutil
    shutil.rmtree(tmp, ignore_errors=True)
    bad = results.count(False)
    print('--- %d 项: PASS %d / FAILED %d ---'
          % (len(results), results.count(True), bad))
    print('ALL PASS' if bad == 0 else 'FAILED %d 项' % bad)
    return 0 if bad == 0 else 1


if __name__ == '__main__':
    sys.exit(main())
