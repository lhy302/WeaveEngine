# -*- coding: utf-8 -*-
# test_frame_plan_vk.py — VK 是否**真按 plan 遍历执行**（V-01 反例矩阵的受跟踪版，2026-11-11）
#
# 做法：把 loom_pass.frame_plan 换成「改过描述」的包装（GL 侧同步改 loom_render/editor 的别名），
# 重渲染 GL 与 VK，比较各自相对基线的 MAE。判据：两端**同向变化**（都 0 或都 >1e-3），
# 且至少 4 类反例两端都 >1e-3。这能抓出「VK 只按 id 读存在性、不真遍历」的假驱动。
import dataclasses
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
sys.path.insert(0, HERE)
os.environ.setdefault('LOOM_NO_PARALLEL', '1')
os.environ['LOOM_NO_SAVE_MIGRATE'] = '1'

import numpy as np

import test_ab_gl_vk as AB
import loom_pass
import loom_render
import editor
from loom_pass import DrawCmd, DepthState

_fails = []


def check(name, cond, detail=''):
    print(('PASS ' if cond else 'FAIL ') + name + ('  ' + str(detail) if detail else ''))
    if not cond:
        _fails.append(name)


def _mae(a, b):
    return float(np.abs(a - b).mean())


def _map_main(plan, **kw):
    return dataclasses.replace(plan, passes=tuple(
        dataclasses.replace(p, **kw) if p.id == 'main' else p for p in plan.passes))


def _del_main(plan):
    return dataclasses.replace(plan, passes=tuple(
        p for p in plan.passes if p.id != 'main'))


def _swap(plan):
    ps = list(plan.passes)
    ids = [p.id for p in ps]
    if 'main' in ids and 'sky' in ids:
        i, j = ids.index('main'), ids.index('sky')
        ps[i], ps[j] = ps[j], ps[i]
    return dataclasses.replace(plan, passes=tuple(ps))


MUTS = (
    ('删 main pass', _del_main),
    ('main<->sky 换序', _swap),
    ('main.draws=skybox', lambda p: _map_main(p, draws=(DrawCmd('skybox'),))),
    ('main.load=load', lambda p: _map_main(p, load='load')),
    ('main.depth.test=False', lambda p: _map_main(
        p, depth=DepthState(test=False, write=False, func='always', clear=None))),
)


def _vk_render_with_renderer(data):
    """渲染一帧并**把 renderer 交回来**（用于断言阴影槽位/绑定表等运行期状态）。"""
    import wgpu
    import scene_driver as sd
    import vk_renderer as vr
    fmt = 'rgba8unorm'
    device = AB._vk_device()
    tex = device.create_texture(
        size=(AB.W, AB.H, 1), format=fmt,
        usage=wgpu.TextureUsage.RENDER_ATTACHMENT | wgpu.TextureUsage.COPY_SRC)

    class _Ctx:
        physical_size = (AB.W, AB.H)

        def get_current_texture(self):
            return tex

    drv = sd.SceneDriver()
    drv.load_from_data(data)
    r = vr.VkRenderer(device, fmt)
    vp, cam_pos = drv.render_pose(aspect=AB.W / AB.H)
    r.draw_frame(_Ctx(), drv.models, drv.lights, vp, cam_pos, interp=None,
                 sky=getattr(drv, 'skybox', None))
    return r


def main():
    data = AB._load_scene(os.path.join(AB.SCENES_DIR, 'ab_sky.json'))
    g0 = AB.render_gl(data)
    v0 = AB.render_vk(data)
    orig = (loom_pass.frame_plan, loom_render.frame_plan, editor.frame_plan)
    rows = []
    try:
        for name, mut in MUTS:
            def wrapper(*a, **k):
                return mut(orig[0](*a, **k))
            loom_pass.frame_plan = wrapper
            loom_render.frame_plan = wrapper
            editor.frame_plan = wrapper
            try:
                g = AB.render_gl(data)
                v = AB.render_vk(data)
            finally:
                loom_pass.frame_plan, loom_render.frame_plan, editor.frame_plan = orig
            mg, mv = _mae(g, g0), _mae(v, v0)
            rows.append((name, mg, mv))
            print('  %-24s GL=%.5f VK=%.5f' % (name, mg, mv))
    finally:
        loom_pass.frame_plan, loom_render.frame_plan, editor.frame_plan = orig
    for name, mg, mv in rows:
        check('反例两端同向：%s' % name, (mg > 1e-3) == (mv > 1e-3),
              (mg, mv))
    both = [n for n, mg, mv in rows if mg > 1e-3 and mv > 1e-3]
    check('至少 4 类反例两端都 >1e-3（VK 真读 plan）', len(both) >= 4,
          '%d/%d' % (len(both), len(rows)))
    check('正常路径未劣化（GL vs VK 基线仍很小）', _mae(g0, v0) <= 2e-4,
          _mae(g0, v0))

    # 行为断言（补 test_vk_two_dir_shadow A11 的源码断言）：真跑一帧双平行光场景，
    # 看**绑定表/槽位**里是否确实有两套阴影（不匹配源码文本）。
    data2 = AB._load_scene(os.path.join(AB.SCENES_DIR, 'ab_c_dir_shadow.json'))
    data2 = dict(data2)
    data2['lights'] = list(data2.get('lights') or [])
    data2['lights'].append({'id': 'dir2', 'kind': 'directional',
                            'direction': [0.6, -0.7, -0.3], 'color': [1, 1, 1],
                            'intensity': 1.0, 'shadow': True, 'mode': 'full',
                            'shape': 'circle', 'size': 4})
    r2 = _vk_render_with_renderer(data2)
    check('双 dir 阴影：阴影绑定表有 2 个槽位',
          len(getattr(r2, '_dir_shadow_groups', {})) == 2,
          len(getattr(r2, '_dir_shadow_groups', {})))
    check('双 dir 阴影：每槽位独立 uniform 缓冲（2 个）',
          len(getattr(r2, '_dir_shadow_bufs', ())) == 2,
          len(getattr(r2, '_dir_shadow_bufs', ())))
    check('双 dir 阴影：两槽位贴图视图不同',
          getattr(r2, '_shadow_view', None) is not getattr(r2, '_shadow_view2', None),
          (id(getattr(r2, '_shadow_view', None)), id(getattr(r2, '_shadow_view2', None))))
    print('=' * 60)
    if _fails:
        print('失败:', _fails)
        return 1
    print('ALL PASS')
    return 0


if __name__ == '__main__':
    sys.exit(main())
