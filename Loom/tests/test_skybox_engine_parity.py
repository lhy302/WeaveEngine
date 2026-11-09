# -*- coding: utf-8 -*-
# test_skybox_engine_parity.py — 天空盒：GL/VK 结论一致 + base_dir 相对路径 (2026-11-09, 02 号)
# 覆盖人类裁决 Q1=A(缺键→默认蓝) / Q3=A(相机级优先) / Q6=A(六面图相对路径按场景目录解析)。
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
os.environ.setdefault('LOOM_NO_PARALLEL', '1')

_fails = []


def check(name, cond, detail=''):
    print(('PASS ' if cond else 'FAIL ') + name + ('  ' + str(detail) if detail else ''))
    if not cond:
        _fails.append(name)


def _scene(sky=None, cam_sky=None, with_cams=False):
    d = {'version': 10,
         'camera': {'target': [0, 1, 0], 'distance': 8.0, 'yaw': 0.5, 'pitch': -0.3},
         'gravity': -9.8, 'objects': [], 'lights': [], 'materials': [],
         'cameras': [], 'active_camera': None}
    if sky is not None:
        d['skybox'] = sky
    if with_cams:
        cam = {'id': 'cam1', 'name': 'c1', 'position': [0, 1, 0], 'yaw': 0.0,
               'pitch': 0.0, 'roll': 0.0, 'fov': 60.0, 'fov_locked': True}
        if cam_sky is not None:
            cam['skybox'] = cam_sky
        d['cameras'] = [cam]
        d['active_camera'] = 'cam1'
    return d


def _gl_engine(data):
    import moderngl
    import runtime
    ctx = moderngl.create_standalone_context(require=330)
    fbo = ctx.framebuffer(color_attachments=[ctx.renderbuffer((64, 64), components=4)],
                          depth_attachment=ctx.depth_renderbuffer((64, 64)))
    eng = runtime.PlayerApp(width=64, height=64, ctx=ctx, scene_data=data)
    eng._external_fb = fbo
    return eng


def _vk_driver(data, base_dir=None):
    import scene_driver
    d = scene_driver.SceneDriver()
    d.load_from_data(data, base_dir=base_dir)
    return d


def t_default_blue():
    """Q1=A: 场景没有 skybox 键 -> GL/VK 都拿到同一个默认蓝。"""
    print('=== A. 缺 skybox 键 -> 默认蓝 (GL vs VK) ===')
    import sceneio
    want = tuple(sceneio.DEFAULT_SKYBOX_COLOR)
    g = _gl_engine(_scene())
    v = _vk_driver(_scene())
    gs = getattr(g, '_skybox', None)
    vs = getattr(v, 'skybox', None)
    check('GL 有默认蓝天空盒', gs is not None and tuple(gs._solid_color) == want,
          None if gs is None else gs._solid_color)
    check('VK 有默认蓝天空盒', vs is not None and tuple(vs._solid_color) == want,
          None if vs is None else vs._solid_color)
    check('GL/VK 默认色逐位相同', gs is not None and vs is not None
          and tuple(gs._solid_color) == tuple(vs._solid_color))
    check('GL/VK valid 标记同为 True',
          bool(getattr(g, '_skybox_valid', False)) and bool(getattr(v, '_skybox_valid', False)))
    check('GL/VK effective_skybox 结论一致 (都=场景级)',
          getattr(g, 'effective_skybox', lambda: None)() is gs
          and getattr(v, 'effective_skybox', lambda: None)() is vs)


def t_camera_priority():
    """Q3=A: 相机级 skybox 优先于场景级，两端结论一致。"""
    print('=== B. 相机级 skybox 优先 (GL vs VK) ===')
    cam_sky = {'solid_color': [10, 20, 30, 255], 'name': 'camsky'}
    scn_sky = {'solid_color': [200, 100, 50, 255], 'name': 'scnsky'}
    data = _scene(sky=scn_sky, cam_sky=cam_sky, with_cams=True)
    g = _gl_engine(data)
    v = _vk_driver(data)
    gc = getattr(g.cameras[0], 'skybox', None) if getattr(g, 'cameras', None) else None
    vc = getattr(v.cameras[0], 'skybox', None) if getattr(v, 'cameras', None) else None
    check('GL 相机实体拿到相机级 skybox',
          gc is not None and tuple(gc._solid_color) == (10, 20, 30, 255),
          None if gc is None else gc._solid_color)
    check('VK 相机实体拿到相机级 skybox',
          vc is not None and tuple(vc._solid_color) == (10, 20, 30, 255),
          None if vc is None else vc._solid_color)
    ge = g.effective_skybox()
    ve = v.effective_skybox()
    check('两端 effective_skybox 都取相机级',
          ge is gc and ve is vc,
          (None if ge is None else ge.name, None if ve is None else ve.name))


def t_relative_paths_from_other_cwd():
    """Q6=A: 场景在 A 目录、从 B 目录启动 -> 六面图相对路径仍能解析。"""
    print('=== C. 相对六面图路径按场景目录解析 (从别处启动) ===')
    import pygame
    import sceneio
    pygame.init()
    root = tempfile.mkdtemp(prefix='loom_sky_')
    adir = os.path.join(root, 'A')
    bdir = os.path.join(root, 'B')
    img_dir = os.path.join(adir, 'sky')
    os.makedirs(img_dir, exist_ok=True)
    os.makedirs(bdir, exist_ok=True)
    names = ['px.png', 'nx.png', 'py.png', 'ny.png', 'pz.png', 'nz.png']
    for i, n in enumerate(names):
        s = pygame.Surface((8, 8))
        s.fill((40 + i * 10, 80, 120))
        pygame.image.save(s, os.path.join(img_dir, n))
    scene = _scene(sky={'paths': ['sky/' + n for n in names], 'name': 'six'})
    scene_path = os.path.join(adir, 'scene.json')
    import json
    with open(scene_path, 'w', encoding='utf-8') as f:
        json.dump(scene, f)
    old_cwd = os.getcwd()
    try:
        os.chdir(bdir)                       # 从 B 目录启动（CWD 无 sky/ 目录）
        data = sceneio.load_scene_data(scene_path)
        base = os.path.dirname(os.path.abspath(scene_path))
        cube, valid, reason = sceneio.skybox_from_dict(data.get('skybox'), base)
        check('sceneio: 相对路径按 base_dir 解析成功', valid, reason)
        v = _vk_driver(data, base_dir=base)
        check('VK driver: 相对路径解析成功 (valid=True)',
              bool(getattr(v, '_skybox_valid', False)), getattr(v, '_skybox_error', None))
        g = _gl_engine_with_base(scene_path, data)
        check('GL 播放器: 相对路径解析成功 (valid=True)',
              bool(getattr(g, '_skybox_valid', False)), getattr(g, '_skybox_error', None))
    finally:
        os.chdir(old_cwd)


def _gl_engine_with_base(scene_path, data):
    """按 PlayerApp 的真实入口（scene_path）加载，验证它把场景目录作为 base_dir。"""
    import moderngl
    import runtime
    ctx = moderngl.create_standalone_context(require=330)
    fbo = ctx.framebuffer(color_attachments=[ctx.renderbuffer((64, 64), components=4)],
                          depth_attachment=ctx.depth_renderbuffer((64, 64)))
    eng = runtime.PlayerApp(scene_path, 64, 64, ctx=ctx)
    eng._external_fb = fbo
    return eng


def t_a5_invalid_cubemap():
    """A5=A: 无效 cubemap 统一错误模型 —— 拒绝 + 告警一次 + 不画, 不抛到渲染循环。"""
    print("=== D. 无效 cubemap (A5=A) ===")
    import numpy as np
    from loom_cubemap import Cubemap
    arr = np.zeros((2, 2, 4), dtype=np.uint8)
    bad_faces = Cubemap(2, faces=[arr.copy(), arr.copy()])      # 只有 2 面
    ok, why = bad_faces.validate()
    check('缺面(<6) -> validate False 且有原因', ok is False and bool(why), why)
    raised = None
    try:
        bad_faces.ensure_gl(_gl_engine(_scene()).ctx)           # 建纹理前必须拒绝
    except ValueError as e:
        raised = e
    check('缺面 -> ensure_gl 抛 ValueError (不再画 1x1 白)', raised is not None, raised)
    # GL 渲染路径: 注入无效 cubemap 后绘制不得抛、且把结论写回 valid/error
    eng = _gl_engine(_scene())
    eng._skybox = bad_faces
    eng._skybox_valid = True
    thrown = None
    try:
        eng._draw_skybox()
    except BaseException as e:
        thrown = e
    check('GL: 无效天空盒不抛到渲染循环', thrown is None, thrown)
    check('GL: _skybox_valid=False 且 _skybox_error 有原因',
          getattr(eng, '_skybox_valid', None) is False
          and bool(getattr(eng, '_skybox_error', None)),
          getattr(eng, '_skybox_error', None))


def t_a6_camera_identity():
    """A6=A: 相机级 skybox 按身份配对；非法段不得把别人的颜色给激活相机。"""
    print("=== E. 相机级 skybox 按身份配对 (A6=A) ===")
    red = {'solid_color': [200, 0, 0, 255], 'name': 'red'}
    # 场景: c1 有红色天空盒, 第 2 段非法 -> build_cameras 只建 1 个相机
    scn = _scene(with_cams=False)
    scn['cameras'] = [{'id': 'c1', 'name': 'c1', 'position': [0, 1, 0],
                       'yaw': 0.0, 'pitch': 0.0, 'skybox': red},
                      'not-a-dict']
    scn['active_camera'] = 'c1'
    d = _vk_driver(scn)
    check('VK: 按 id 配对 -> c1 拿到自己的红色天空盒',
          len(d.cameras) == 1 and d.cameras[0].skybox is not None
          and tuple(d.cameras[0].skybox._solid_color) == (200, 0, 0, 255),
          None if not d.cameras or d.cameras[0].skybox is None
          else d.cameras[0].skybox._solid_color)
    # 激活相机改成不存在的 c2 -> 不得拿到 c1 的红色 (宁可不画)
    scn2 = dict(scn)
    scn2['active_camera'] = 'c2'
    d2 = _vk_driver(scn2)
    eff = d2.effective_skybox()
    is_red = (eff is not None
              and tuple(getattr(eff, '_solid_color', ())) == (200, 0, 0, 255))
    check('VK: 激活 c2(不存在) 时不得拿到 c1 的 skybox', not is_red,
          None if eff is None else getattr(eff, '_solid_color', None))


def t_c5_present_health():
    """C5=B: GL/VK 共用同一上屏健康实现; 连续 3 次失败 -> 建议降级, 成功一次清零。"""
    print("=== F. 上屏健康判据 (C5=B) ===")
    import loom_render
    import vk_renderer
    import vk_player
    ph = loom_render.PresentHealth()
    for i in range(3):
        ph.note_fail('模拟失败 %d' % i)
    check('PresentHealth: 连续 3 次失败 -> should_fallback(3) 为真',
          ph.should_fallback(3) is True, ph.snapshot())
    ph.note_ok()
    check('PresentHealth: 成功一次后计数清零 -> 不再建议降级',
          ph.fail_streak == 0 and ph.should_fallback(3) is False, ph.snapshot())
    check('VK 侧复用同一实现 (不是复制阈值)',
          getattr(vk_renderer, '_PresentHealth', None) is loom_render.PresentHealth)
    # 包装层: vk_player.should_fallback_remote 走渲染器实例 (注入桩验证语义)
    class _R:
        def __init__(self):
            self.h = loom_render.PresentHealth()

        def present_health(self):
            return self.h.snapshot()

        def should_fallback_remote(self, threshold=None):
            return self.h.should_fallback(threshold)

    r = _R()
    old = list(vk_player._LAST_RENDERER)
    vk_player._LAST_RENDERER[0] = r
    try:
        for i in range(3):
            r.h.note_fail('present fail %d' % i)
        check('vk_player.should_fallback_remote(): 3 次失败为真',
              vk_player.should_fallback_remote(3) is True)
        check('vk_player.present_health(): 带 fail_streak/last_error',
              (vk_player.present_health() or {}).get('fail_streak') == 3,
              vk_player.present_health())
        r.h.note_ok()
        check('成功一次后 vk_player 判据回到 False',
              vk_player.should_fallback_remote(3) is False)
    finally:
        vk_player._LAST_RENDERER[0] = old[0] if old else None


def main():
    t_default_blue()
    t_camera_priority()
    t_relative_paths_from_other_cwd()
    t_a5_invalid_cubemap()
    t_a6_camera_identity()
    t_c5_present_health()
    print('=' * 56)
    if _fails:
        print('有 FAIL:', _fails)
        return 1
    print('总结果: ALL PASS')
    return 0


if __name__ == '__main__':
    sys.exit(main())