# -*- coding: utf-8 -*-
r"""probe_bucket_reorder.py — 桶实例偏移复现 (scan_04 P1 回归) A/B 探针 (2026-11-07)

构造 scan_04 指出的触发形态:
    vis 顺序 = [cube(贴图A), cube(贴图B), sphere(无贴图), cube(贴图A)]
  · 第 0 号与第 3 号同网格 + 同贴图 -> 同一个桶, 但被 1、2 号隔开;
  · 第 1 号同网格不同贴图 -> 另一个桶 (不同贴图不能合并);
  · 第 2 号是别的网格 (插在中间, 迫使同桶不连续)。

对照三条渲染:
  1. GL  (正确基准)
  2. VK 修复前行为: 把 bucket_layout 换成"老语义"(first_instance = idxs[0],
     实例缓冲保持 vis 原序) —— 与 HEAD 的 rp.draw(nv, len(idxs), 0, idxs[0]) 等价
  3. VK 修复后: 真实 bucket_layout (单缓冲 + 按桶重排)

判据: 修复后 MAE 应回到 A/B 常态 (~1e-4 量级), 修复前应显著劣化;
      另按区域统计 "缺失的第 3 个 cube" 像素, 修复前应有明显缺失, 修复后没有。

用法: py -3.12 tests\_tmp\probe_bucket_reorder.py
"""
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, ROOT)
sys.path.insert(0, HERE)
os.chdir(ROOT)
os.environ.setdefault('LOOM_NO_PARALLEL', '1')
os.environ['LOOM_NO_SAVE_MIGRATE'] = '1'

import ab_gl_vk as AB            # noqa: E402
import vk_renderer as VR         # noqa: E402

W, H = AB.W, AB.H


def _make_textures():
    """两张一眼能分的贴图 (A=红白棋盘, B=蓝黑条纹), 落到 _tmp 供 sceneio 读。"""
    import pygame
    pygame.init()
    pa = os.path.join(HERE, 'probe_bucket_tex_a.png')
    pb = os.path.join(HERE, 'probe_bucket_tex_b.png')
    a = pygame.Surface((32, 32))
    for y in range(32):
        for x in range(32):
            c = (230, 60, 60) if ((x // 8) + (y // 8)) % 2 == 0 else (240, 240, 240)
            a.set_at((x, y), c)
    pygame.image.save(a, pa)
    b = pygame.Surface((32, 32))
    for y in range(32):
        for x in range(32):
            c = (40, 80, 220) if (x // 4) % 2 == 0 else (16, 16, 40)
            b.set_at((x, y), c)
    pygame.image.save(b, pb)
    return pa, pb


def _scene():
    pa, pb = _make_textures()
    data = {
        'version': 10,
        'camera': {'target': [0, 0.7, 0], 'distance': 11, 'yaw': 0.12,
                   'pitch': -0.22},
        'materials': [
            {'id': 'm_a', 'name': '贴图A', 'color': '#ffffff', 'saturation': 1,
             'metallic': 0, 'roughness': 0.5, 'pbr': False,
             'albedo': {'guid': 'tex_a', 'path': pa, 'name': 'a'}},
            {'id': 'm_b', 'name': '贴图B', 'color': '#ffffff', 'saturation': 1,
             'metallic': 0, 'roughness': 0.5, 'pbr': False,
             'albedo': {'guid': 'tex_b', 'path': pb, 'name': 'b'}},
        ],
        # ★ 顺序即扫描序: A, B, sphere(插中间的别的物体), A —— 同桶被隔开
        'objects': [],
        'lights': [
            {'id': 'sun', 'kind': 'directional', 'direction': [-0.5, -1, -0.4],
             'color': [1, 1, 1], 'intensity': 1.15, 'shadow': False,
             'mode': 'full', 'shape': 'circle', 'size': 5},
        ],
    }
    defs = [
        ('cubeA1', 'cube', {'size': 1.1}, [-3.2, 0.7, 0.0], 'm_a'),
        ('cubeB', 'cube', {'size': 1.1}, [-1.05, 0.7, 0.0], 'm_b'),
        ('ball', 'sphere', {'radius': 0.6, 'segments': 16}, [1.05, 0.7, 0.0], None),
        ('cubeA2', 'cube', {'size': 1.1}, [3.2, 0.7, 0.0], 'm_a'),
    ]
    for i, (oid, typ, params, pos, mid) in enumerate(defs):
        obj = {'id': oid, 'type': typ, 'params': params, 'position': pos,
               'rotation': [0, 0.35, 0], 'scale': [1, 1, 1],
               'color': '#ffffff', 'visible': True}
        if mid:
            obj['material_id'] = mid
        data['objects'].append(obj)
    return data


def _legacy_layout(groups):
    """HEAD 语义: 实例缓冲保持 vis 原序, first_instance 直接取 idxs[0]."""
    total = sum(len(v) for v in groups.values())
    order = np.arange(total, dtype=np.intp)
    starts = {k: (v[0] if v else 0) for k, v in groups.items()}
    return order, starts, True


def _mae(a, b):
    d = np.abs(a - b)
    la = a.mean(axis=2).ravel(); lb = b.mean(axis=2).ravel()
    la = la - la.mean(); lb = lb - lb.mean()
    ncc = float((la * lb).sum() / (np.linalg.norm(la) * np.linalg.norm(lb) + 1e-9))
    return float(d.mean()), float(d.max()), ncc


def _region_diff(a, b, x0, x1):
    d = np.abs(a[:, x0:x1] - b[:, x0:x1])
    return float(d.mean()), int((d.max(axis=2) > 0.05).sum())


def main():
    data = _scene()
    buckets_seen = {}

    # 抓一次真实的桶构成 (渲染时由 VkRenderer 内部调用, 这里只旁听)
    _orig = VR.bucket_layout

    def _spy(groups):
        buckets_seen['groups'] = {k: list(v) for k, v in groups.items()}
        return _orig(groups)

    VR.bucket_layout = _spy
    print('[GL ] 渲染中...')
    g, ed, ctx = AB.render_gl(data)
    ctx.release()
    print('[VK ] 渲染中 (修复后)...')
    v_fix, drv = AB.render_vk(data)
    print('[VK ] 渲染中 (修复前HEAD语义)...')
    VR.bucket_layout = _legacy_layout
    try:
        v_old, _drv2 = AB.render_vk(data)
    finally:
        VR.bucket_layout = _orig

    print('\n模型数 GL=%d VK=%d' % (len(ed.models), len(drv.models)))
    if 'groups' in buckets_seen:
        gs = buckets_seen['groups']
        print('桶数=%d' % len(gs))
        for _i, (_k, _v) in enumerate(gs.items()):
            print('  桶%d 网格=%r 实例行=%s' % (_i, (_k[0], _k[1]), _v))
        contig = all(
            (max(v) - min(v) + 1) == len(v) for v in gs.values())
        print('每桶实例行是否连续: %s   (False = 触发本缺陷)' % contig)

    m_old = _mae(g, v_old)
    m_fix = _mae(g, v_fix)
    print('\n%-22s %-10s %-10s %-10s' % ('对比', 'MAE', 'MAX', 'NCC'))
    print('-' * 56)
    print('%-22s %-10.6f %-10.4f %-10.4f' % ('GL vs VK修复前', *m_old))
    print('%-22s %-10.6f %-10.4f %-10.4f' % ('GL vs VK修复后', *m_fix))

    # 串形发生在"同桶第 2 个物体"上 —— 自动定位修复前误差最大的列区间
    col_err = np.abs(g - v_old).max(axis=2).sum(axis=0)      # 每列的误差能量
    hot = np.where(col_err > 0.05 * H)[0]
    if hot.size:
        x0, x1 = int(hot.min()), int(hot.max()) + 1
    else:
        x0, x1 = 0, W
    d_old, n_old = _region_diff(g, v_old, x0, x1)
    d_fix, n_fix = _region_diff(g, v_fix, x0, x1)
    print('\n修复前误差热区 (x=%d..%d, 宽 %d px):' % (x0, x1, x1 - x0))
    print('  修复前 区域MAE=%.6f  明显不同像素=%d' % (d_old, n_old))
    print('  修复后 区域MAE=%.6f  明显不同像素=%d' % (d_fix, n_fix))

    try:
        from PIL import Image
        side = np.concatenate(
            [g, np.ones((H, 6, 3)), v_old, np.ones((H, 6, 3)), v_fix], axis=1)
        out = os.path.join(HERE, 'probe_bucket_reorder_side.png')
        Image.fromarray((np.clip(side, 0, 1) * 255).astype('uint8')).save(out)
        print('\n并排图 (GL | VK修复前 | VK修复后):', out)
    except Exception as e:
        print('(并排图保存失败: %r)' % (e,))

    ok = m_fix[0] <= m_old[0] and n_fix < n_old
    print('\n结论: 修复后优于修复前 ->', ok)
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
