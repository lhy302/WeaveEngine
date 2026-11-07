# -*- coding: utf-8 -*-
r"""verify_world_ui_depth.py — R1 world Canvas 深度测试实证 (2026-11-06).

Vk 侧独立验证 (不依赖 GL):
  1. 同一场景渲染三次:
       A) 遮挡物可见 + world Canvas
       B) 遮挡物隐藏 + world Canvas
       C) 无 UI
  2. 用 B vs C 的差异像素定义 "world Canvas 覆盖区域" (mask).
  3. 比较 A vs B: mask 内必须有差异 —— 说明遮挡物挡住了 Canvas 像素,
     即 world quad 参与了深度测试 (若 quad 永远画在最上层, A/B 在 mask 内
     不会有差异).
  4. 另检查离屏 target 已创建 (每 Canvas 一张), 且 Canvas 区域非空.

用法: python tests\_tmp\verify_world_ui_depth.py
"""
import copy
import os
import sys

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.chdir(ROOT)
os.environ.setdefault('LOOM_NO_PARALLEL', '1')
os.environ['LOOM_NO_SAVE_MIGRATE'] = '1'

import ab_gl_vk_ui as AB                     # noqa: E402

SCENE = os.path.join(ROOT, 'tests', '_tmp', 'ui_world_scene.json')
fails = []


def check(label, cond, detail=''):
    msg = ('PASS ' if cond else 'FAIL ') + label
    if detail:
        msg += '  ' + str(detail)
    print(msg)
    if not cond:
        fails.append(label)


def main():
    base = AB._scene_data(SCENE)
    data_a = copy.deepcopy(base)
    data_b = copy.deepcopy(base)
    data_c = copy.deepcopy(base)

    occl = next(o for o in data_a['objects'] if o.get('id') == 'occluder')
    occ_b = next(o for o in data_b['objects'] if o.get('id') == 'occluder')
    occl['visible'] = True
    occ_b['visible'] = False

    img_a, drv_a, r_a = AB.render_vk(data_a, with_ui=True)
    img_b, drv_b, r_b = AB.render_vk(data_b, with_ui=True)
    img_c, drv_c, r_c = AB.render_vk(data_c, with_ui=False)

    # 1) 离屏 target 数 = world Canvas 数
    n_world = sum(1 for c in drv_b.ui.canvases if c.canvas_type == 'world')
    n_targets = len(getattr(r_b, '_world_targets', {}))
    check('world Canvas 数 = 2', n_world == 2, n_world)
    check('离屏 target 数 = world Canvas 数', n_targets == n_world,
          '%d/%d' % (n_targets, n_world))
    sizes = sorted(t['size'] for t in r_b._world_targets.values())
    check('离屏 target 尺寸正确', sizes == [(140, 70), (320, 160)], sizes)

    # 2) Canvas 覆盖区域 mask = B(有 UI) vs C(无 UI)
    d_ui = np.abs(img_b - img_c).max(axis=2)
    mask = d_ui > 1e-6
    n_mask = int(mask.sum())
    check('world Canvas 可见像素 > 500', n_mask > 500, n_mask)

    # 3) 遮挡物开关差异
    d_occ = np.abs(img_a - img_b).max(axis=2)
    changed = d_occ > 1e-6
    n_all = int(changed.sum())
    n_in = int((changed & mask).sum())
    check('遮挡物开关产生差异 (总计)', n_all > 0, n_all)
    check('Canvas 覆盖区内被遮挡的像素 > 50', n_in > 50, n_in)
    check('遮挡发生在 Canvas 区域内 (占比 > 0)',
          n_in > 0 and n_in <= n_all, '%d/%d' % (n_in, n_all))

    # 4) 反向断言: 若无深度测试, Canvas 会覆盖遮挡物 -> A/B 在 mask 内几乎无差异.
    #    这里把实际值与 "无深度" 期望 (0) 区分开.
    check('结论: world quad 参与深度测试', n_in > 50,
          'mask=%d, occluded_pixels=%d' % (n_mask, n_in))

    print()
    if fails:
        print('FAILED %d: %s' % (len(fails), fails))
        return 1
    print('ALL PASS')
    return 0


if __name__ == '__main__':
    sys.exit(main())
