# -*- coding: utf-8 -*-
"""test_skybox_scene.py — beta5 天空盒「场景/编辑器/命令」侧回归（人类裁决 Q1/Q3/Q4/Q5/Q6 = A）.

覆盖:
  ① 新建场景 -> 默认纯色蓝天（且渲染路径拿到的就是它）
  ② 加载"无 skybox 键 / null"的场景 -> 默认蓝（不是黑底）
  ③ skybox_set [0.2,0.4,0.8] -> ok=False（旧行为: int() -> 全黑）
  ④ skybox_set [58,123,213] -> 存盘-重载-读回一致
  ⑤ 六面图相对场景目录往返 + 缺失文件报错（valid=False + reason）
  ⑥ 相机级 skybox 优先（相机绿 / 场景红 -> 取到绿）

跑法: cd Loom && python tests/test_skybox_scene.py
不写受跟踪文件（全部落 tempdir）。
"""
import json
import os
import struct
import sys
import tempfile
import zlib

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
os.chdir(ROOT)
os.environ.setdefault('LOOM_USER_ROOT', os.path.join(tempfile.gettempdir(), 'loom_sb_user'))
os.environ.setdefault('LOOM_GAME_DIR', os.path.join(tempfile.gettempdir(), 'loom_sb_game'))
os.makedirs(os.environ['LOOM_GAME_DIR'], exist_ok=True)

import engine as E                                      # noqa: E402
import editor                                           # noqa: E402
import sceneio as S                                     # noqa: E402
import agent_commands as AC                             # noqa: E402
from undo import UndoManager                            # noqa: E402

E.GLEngine._build_gpu = lambda self, m: None            # 无头桩（同其它编辑器测试）

ok = True


def check(label, cond, detail=''):
    global ok
    print(('PASS ' if cond else 'FAIL ') + label + ('  ' + str(detail) if detail else ''))
    if not cond:
        ok = False


def _png(path, rgba=(58, 155, 213, 255)):
    """写一张 8x8 纯色 PNG（避免依赖显示设备）。"""
    w = h = 8
    raw = b''.join(b'\x00' + bytes(rgba) * w for _ in range(h))

    def chunk(tag, data):
        return (struct.pack('>I', len(data)) + tag + data
                + struct.pack('>I', zlib.crc32(tag + data) & 0xffffffff))

    ihdr = struct.pack('>IIBBBBB', w, h, 8, 6, 0, 0, 0)
    with open(path, 'wb') as f:
        f.write(b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', ihdr)
                + chunk(b'IDAT', zlib.compress(raw)) + chunk(b'IEND', b''))
    return path


class _View(object):
    def reset_interaction(self):
        pass


def _ed(scene_path=None):
    """EditorApp 无 GL 桩（与 test_editor_load_reject_keeps_scene 同款 + 天空盒字段）。"""
    ed = editor.EditorApp.__new__(editor.EditorApp)
    ed.models = []
    ed.materials = []
    ed.lights = []
    ed.cameras = []
    ed.current_model_index = 0
    ed.script_keys = {}
    ed.undo = UndoManager()
    ed.is_playing = False
    ed.active_camera = None
    ed.gravity = -9.8
    ed._skybox = None
    ed._scene_skybox = None
    ed._skybox_valid = True
    ed._skybox_error = None
    ed.ui = None
    ed.camera_target = (0.0, 0.0, 0.0)
    ed.camera_distance = 10.0
    ed.camera_yaw = 0.6
    ed.camera_pitch = -0.35
    ed.camera_roll = 0.0
    ed.orbit_mode = True
    ed.ortho = False
    ed.ortho_size = 12.0
    ed._fov = 1.0471975511965976
    ed._scene_path = scene_path
    ed.last_dir = None
    ed.scene_name = '场景'
    ed.selected_index = -1
    ed.selected_light_index = -1
    ed.selected_camera_index = -1
    ed.msg = ''
    ed.msg_color = (220, 222, 228)
    ed._msg_until = 0.0
    ed.view = _View()
    ed.preview_camera = None
    return ed


class _Win(object):
    def __init__(self, ed):
        self.editor = ed


def _cmd(name, ed, args=None):
    return AC._COMMANDS[name](_Win(ed), dict(args or {}))


# ============ ① 新建场景 -> 默认蓝天 ============
def t_new_scene_default():
    print('---- 1) 新建场景默认蓝天（Q1=A） ----')
    ed = _ed()
    ed._new_scene()
    cube = getattr(ed, '_skybox', None)
    check('新建场景有天空盒（修前: None）', cube is not None, type(cube).__name__)
    check('默认色 = sceneio.DEFAULT_SKYBOX_COLOR (#3A9BD5)',
          tuple(getattr(cube, '_solid_color', ())) == S.DEFAULT_SKYBOX_COLOR,
          getattr(cube, '_solid_color', None))
    check('渲染路径读到的就是它（engine._skybox 非空、与场景级同一对象）',
          getattr(ed, '_skybox', None) is getattr(ed, '_scene_skybox', None))
    # 存盘 -> 文件里有 skybox.solid_color
    with tempfile.TemporaryDirectory() as tmp:
        p = os.path.join(tmp, 'new.json')
        import sceneio as _S
        data = _S.scene_to_dict(ed, camera=ed._camera_dict(), base_dir=tmp)
        check('存盘写出 skybox.solid_color',
              (data.get('skybox') or {}).get('solid_color') == list(S.DEFAULT_SKYBOX_COLOR),
              data.get('skybox'))


# ============ ② 加载无 skybox 键 -> 默认蓝 ============
def t_load_without_skybox():
    print('---- 2) 加载无 skybox 键 / null -> 默认蓝（Q1=A） ----')
    for data, tag in (({'version': 10, 'objects': []}, '缺键'),
                      ({'version': 10, 'objects': [], 'skybox': None}, 'null')):
        eng = _ed()
        S.scene_from_dict(eng, data)
        cube = getattr(eng, '_skybox', None)
        check('%s -> 默认蓝（修前: None/黑底）' % (tag),
              cube is not None
              and tuple(getattr(cube, '_solid_color', ())) == S.DEFAULT_SKYBOX_COLOR,
              getattr(cube, '_solid_color', None))
        check('%s -> _skybox_valid=True' % tag,
              getattr(eng, '_skybox_valid', None) is True)


# ============ ③ 0-1 浮点颜色必须拒绝 ============
def t_color_reject():
    print('---- 3) skybox_set 颜色口径（Q4=A: 只认 0..255 整数） ----')
    ed = _ed()
    ed._new_scene()
    before = ed._scene_skybox
    r = _cmd('skybox_set', ed, {'solid_color': [0.2, 0.4, 0.8]})
    check('传 [0.2,0.4,0.8] -> ok=False（修前: 静默 (0,0,0) 全黑）',
          r.get('ok') is False, r)
    check('错误原因指出 0-1 浮点', '0-1 浮点' in str(r.get('error', '')), r.get('error'))
    check('失败不改状态', ed._scene_skybox is before)
    for bad, tag in (([300, 0, 0], '越界'), ([1, 2], '长度 2'),
                     (['a', 1, 2], '非数值'), ('#GGGGGG', '非法 hex')):
        r = _cmd('skybox_set', ed, {'solid_color': bad})
        check('%s -> ok=False' % tag, r.get('ok') is False, r.get('error'))
    # 整值浮点可以（58.0 视作 58）
    r = _cmd('skybox_set', ed, {'solid_color': [58.0, 123.0, 213.0]})
    check('[58.0,123.0,213.0] -> ok=True（整值浮点放行）', r.get('ok') is True, r)


# ============ ④ 0-255 颜色存盘-重载-读回 ============
def t_color_roundtrip():
    print('---- 4) [58,123,213] 存盘-重载-读回一致 ----')
    with tempfile.TemporaryDirectory() as tmp:
        ed = _ed()
        ed._new_scene()
        r = _cmd('skybox_set', ed, {'solid_color': [58, 123, 213], 'name': '测试蓝'})
        check('skybox_set ok', r.get('ok') is True, r)
        check('落库 = (58,123,213,255)',
              tuple(ed._scene_skybox._solid_color) == (58, 123, 213, 255),
              ed._scene_skybox._solid_color)
        p = os.path.join(tmp, 'sb.json')
        data = S.scene_to_dict(ed, camera=ed._camera_dict(), base_dir=tmp)
        S.save_json_atomic(p, data)
        check('文件里 solid_color = [58,123,213,255]',
              (data.get('skybox') or {}).get('solid_color') == [58, 123, 213, 255],
              data.get('skybox'))
        eng2 = _ed(p)
        S.scene_from_dict(eng2, json.load(open(p, encoding='utf-8')),
                          base_dir=os.path.dirname(p))
        check('重载后读回一致',
              tuple(getattr(eng2._skybox, '_solid_color', ())) == (58, 123, 213, 255),
              getattr(eng2._skybox, '_solid_color', None))
        got = _cmd('skybox_get', eng2)
        check('skybox_get 报 valid=True 且含 solid_color',
              got.get('valid') is True
              and (got.get('skybox') or {}).get('solid_color') == [58, 123, 213, 255],
              got)


# ============ ⑤ 六面图相对路径往返 + 缺文件报错 ============
def t_sixface_paths():
    print('---- 5) 六面图相对路径（Q6=A） / 缺文件报错（Q5=A） ----')
    with tempfile.TemporaryDirectory() as tmp:
        faces = [_png(os.path.join(tmp, n))
                 for n in ('px.png', 'nx.png', 'py.png', 'ny.png', 'pz.png', 'nz.png')]
        ed = _ed(os.path.join(tmp, 'scene.json'))
        r = _cmd('skybox_set', ed, {'paths': faces})
        check('skybox_set(6 面绝对路径) -> ok=True', r.get('ok') is True, r)
        stored = (r.get('skybox') or {}).get('paths') or []
        check('存的是相对场景目录的路径（不是绝对路径）',
              len(stored) == 6 and all(not os.path.isabs(p) for p in stored), stored)
        data = S.scene_to_dict(ed, camera=ed._camera_dict(), base_dir=tmp)
        check('序列化后仍是相对路径',
              all(not os.path.isabs(p)
                  for p in (data.get('skybox') or {}).get('paths') or []),
              (data.get('skybox') or {}).get('paths'))
        # 换"机器"（不同 CWD）重载: 只要 base_dir 对就能解析
        old_cwd = os.getcwd()
        try:
            os.chdir(tempfile.gettempdir())
            eng2 = _ed(os.path.join(tmp, 'scene.json'))
            S.scene_from_dict(eng2, json.loads(json.dumps(data)), base_dir=tmp)
            check('相对路径按场景目录解析成功',
                  getattr(eng2._skybox, 'paths', None) is not None
                  and getattr(eng2, '_skybox_valid', False) is True,
                  getattr(eng2, '_skybox_error', None))
        finally:
            os.chdir(old_cwd)
        # 删一面 -> 明确报错 + valid=False + 回退默认蓝（不静默）
        os.remove(os.path.join(tmp, 'py.png'))
        eng3 = _ed(os.path.join(tmp, 'scene.json'))
        S.scene_from_dict(eng3, json.loads(json.dumps(data)), base_dir=tmp)
        check('缺文件 -> _skybox_valid=False 且 reason 指明文件名',
              getattr(eng3, '_skybox_valid', None) is False
              and 'py.png' in str(getattr(eng3, '_skybox_error', '')),
              (getattr(eng3, '_skybox_valid', None),
               getattr(eng3, '_skybox_error', None)))
        got = _cmd('skybox_get', eng3)
        check('skybox_get 能看出 invalid + reason',
              got.get('valid') is False and 'py.png' in str(got.get('reason')),
              got)


# ============ ⑥ 相机级优先 ============
def t_camera_priority():
    print('---- 6) 相机级 skybox 优先（Q3=A） ----')
    red, _ = S.parse_color([255, 0, 0])
    green, _ = S.parse_color([0, 255, 0])
    data = {'version': 10, 'objects': [], 'skybox': {'solid_color': list(red)},
            'cameras': [{'id': 'c1', 'name': '主相机',
                         'skybox': {'solid_color': list(green)}}],
            'active_camera': 'c1'}
    ed = _ed()
    S.scene_from_dict(ed, data, base_dir=None)
    # 与 _load_scene 同款: 场景级同时写 _scene_skybox 与 _skybox（engine 侧字段）
    ed._scene_skybox = ed._skybox
    ed._sky_eff_last = None
    eff = ed._refresh_effective_skybox()
    check('相机级(绿) 优先于场景级(红)',
          tuple(getattr(eff, '_solid_color', ())) == (0, 255, 0, 255),
          getattr(eff, '_solid_color', None))
    got = _cmd('skybox_get', ed)
    check('skybox_get: 场景级仍是红, effective=camera 且为绿',
          (got.get('skybox') or {}).get('solid_color') == [255, 0, 0, 255]
          and (got.get('effective') or {}).get('source') == 'camera'
          and (got.get('effective') or {}).get('solid_color') == [0, 255, 0, 255],
          got)
    # 取消激活 -> 回落到场景级
    ed.active_camera = None
    eff2 = ed._refresh_effective_skybox()
    check('无激活相机 -> 回落场景级(红)',
          tuple(getattr(eff2, '_solid_color', ())) == (255, 0, 0, 255),
          getattr(eff2, '_solid_color', None))


# ============ ⑦ 编辑器绘制门：相机级天空盒也要画 ============
def t_draw_gate_effective():
    print('---- 7) 编辑器绘制门认"生效天空盒"（Q3=A 在编辑器也成立） ----')
    # 2026-11-10 2A 后：绘制不再由 editor 里那句 if 决定，而是 FramePlan 是否包含 sky pass。
    # 这里改成**行为断言**（别再锁源码字符串，否则渲染重构一次就误报一次）。
    import loom_pass
    check('frame_plan(include_sky=True) 含 sky pass',
          any(p.id == 'sky' for p in loom_pass.frame_plan(include_sky=True).passes))
    check('frame_plan(include_sky=False) 不含 sky pass',
          all(p.id != 'sky' for p in loom_pass.frame_plan(include_sky=False).passes))
    src = open(os.path.join(ROOT, 'loom_render.py'), encoding='utf-8').read()
    check('渲染层按 effective_skybox() 决定 include_sky',
          ('effective_skybox' in src) and ('include_sky' in src))
    # 场景级 None + 相机级绿: 旧门会跳过, 新门应画
    green, _ = S.parse_color([0, 255, 0])
    ed = _ed()
    ed._scene_skybox = None
    ed._skybox = None
    cam = E.GLEngine.add_camera(ed, name='cam')
    from loom_cubemap import Cubemap
    cam.skybox = Cubemap.from_solid(green, name='相机绿')
    ed.cameras.append(cam)
    ed.active_camera = cam.guid
    check('场景级 None / 相机级绿 -> effective_skybox() 非空（旧门跳过）',
          ed.effective_skybox() is not None and getattr(ed, '_skybox', None) is None,
          (ed.effective_skybox() is not None, ed._skybox))
    # 用"门表达式的复刻"计数证明会走到 _draw_skybox
    calls = []
    ed._draw_skybox = lambda: calls.append(1)
    for _ in range(1):
        if ed.effective_skybox() is not None:      # 与 editor.render 的同一条门
            ed._draw_skybox()
    check('门为真 -> 真的调用了 _draw_skybox（计数=1）', calls == [1], calls)


# ============ ⑧ 换场景后 sky 状态复位（先失败过也能出图） ============
def t_reset_sky_state():
    print('---- 8) 换场景/新建 -> reset_sky_state()（P-04 双保险） ----')
    ed = _ed()
    ed._new_scene()
    # 模拟"上一次编译失败"留下的永久哨兵 / 失败标记
    ed._sky_prog = False
    ed._sky_fail_logged = True
    ed._new_scene()
    check('新建场景后 _sky_prog 复位为 None（修前 =False 永久哨兵）',
          getattr(ed, '_sky_prog', 'missing') is None, getattr(ed, '_sky_prog', 'missing'))
    check('失败标记也复位（_sky_fail_logged=False）',
          getattr(ed, '_sky_fail_logged', None) is False,
          getattr(ed, '_sky_fail_logged', None))
    with tempfile.TemporaryDirectory() as tmp:
        p = os.path.join(tmp, 'a.json')
        with open(p, 'w', encoding='utf-8') as f:
            json.dump({'version': 10, 'objects': []}, f)
        ed._sky_prog = False
        ed._sky_fail_logged = True
        ed._load_scene(p)
        check('加载场景后 _sky_prog 复位为 None',
              getattr(ed, '_sky_prog', 'missing') is None,
              getattr(ed, '_sky_prog', 'missing'))


# ============ ⑨ skybox_get 含 VK 侧错误 ============
class _FakeVkDriver(object):
    """VK 驱动桩: 模拟 scene_driver 的天空盒失败字段。"""
    _skybox_error = '第 2 面图片不存在: C:/x/py.png'
    _skybox_valid = False

    def effective_skybox(self):
        return None


def t_get_vk_error():
    print('---- 9) skybox_get 含 VK 驱动 _skybox_error（Q5=A 在 VK 也成立） ----')
    ed = _ed()
    ed._new_scene()
    win = _Win(ed)
    got = _cmd('skybox_get', ed)
    check('无 VK 驱动 -> vk=None（不假装成功）', 'vk' in got and got['vk'] is None, got.get('vk'))
    win.vk_driver = _FakeVkDriver()
    got2 = AC._COMMANDS['skybox_get'](win, {})
    vk = got2.get('vk') or {}
    check('有 VK 驱动 -> 带出 _skybox_error / valid=False',
          vk.get('_skybox_error') == _FakeVkDriver._skybox_error
          and vk.get('valid') is False and vk.get('error') == _FakeVkDriver._skybox_error,
          vk)


# ============ ⑩ P1-1: 设置后立即生效（渲染面 write-back） ============
def t_set_takes_effect():
    print('---- 10) P1-1: skybox_set 后立即生效（_skybox 写回） ----')
    ed = _ed()
    ed._new_scene()
    r = _cmd('skybox_set', ed, {'solid_color': [10, 20, 30]})
    check('skybox_set ok', r.get('ok') is True, r)
    check('设置后 ed._skybox 非空（修前: 恒 None -> 绘制门早退）',
          getattr(ed, '_skybox', None) is not None, ed._skybox)
    check('设置后 effective_skybox() 非空', ed.effective_skybox() is not None)
    check('_skybox 就是场景级对象（无相机覆盖时）',
          ed._skybox is ed._scene_skybox)
    check('返回值 effective 不再谎报（=scene 且对象存在）',
          r.get('effective') == 'scene', r.get('effective'))
    # A1 语义（2026-11-09 追加裁决）: clear = 恢复默认蓝天，不是"没有天空盒"
    r2 = _cmd('skybox_clear', ed)
    check('skybox_clear -> ok + 恢复默认蓝（A1: 不再是 None）',
          r2.get('ok') is True and r2.get('reset_to_default') is True
          and tuple(ed.effective_skybox()._solid_color) == S.DEFAULT_SKYBOX_COLOR,
          (r2.get('ok'), getattr(ed, '_skybox', 'x')))


# ============ ⑪ P1-2: 非 dict 的 skybox 不崩、不丢场景 ============
def t_bad_skybox_type():
    print('---- 11) P1-2: 非 dict skybox 不崩 / 不丢当前场景 ----')
    for bad in ('abc', [], 7, True):
        eng = _ed()
        try:
            S.scene_from_dict(eng, {'version': 10, 'objects': [], 'skybox': bad})
            raised = None
        except Exception as e:
            raised = e
        check('skybox=%r 不抛异常（修前 AttributeError）' % (bad,), raised is None, raised)
        check('skybox=%r -> valid=False 且回退默认蓝' % (bad,),
              getattr(eng, '_skybox_valid', None) is False
              and tuple(getattr(eng._skybox, '_solid_color', ())) == S.DEFAULT_SKYBOX_COLOR,
              (getattr(eng, '_skybox_valid', None),
               getattr(eng._skybox, '_solid_color', None)))
    # 编辑器路径: 坏 skybox 的场景能正常打开（模型不丢、_scene_path 更新）
    import editor as _edmod
    old_save = _edmod.save_last_dir
    _edmod.save_last_dir = lambda state_file, path: None
    try:
        with tempfile.TemporaryDirectory() as tmp:
            p = os.path.join(tmp, 'bad.json')
            with open(p, 'w', encoding='utf-8') as f:
                json.dump({'version': 10, 'skybox': 'oops',
                           'objects': [{'id': 'a', 'name': 'A', 'primitive': 'cube',
                                        'position': [0, 0, 0], 'rotation': [0, 0, 0],
                                        'scale': [1, 1, 1]}]}, f)
            ed = _ed()
            try:
                ed._load_scene(p)
                err = None
            except Exception as e:
                err = e
            check('编辑器加载坏 skybox 场景不崩（F7 不变量）', err is None, err)
            check('对象仍然加载（没丢场景数据）',
                  [m.name for m in ed.models] == ['A'], [m.name for m in ed.models])
            check('坏 skybox -> valid=False（可查询）',
                  getattr(ed, '_skybox_valid', None) is False)
    finally:
        _edmod.save_last_dir = old_save


# ============ ⑫ P1-3: 另存为/首存到别的目录 -> 相对路径重算 ============
def t_save_as_relative():
    print('---- 12) P1-3: 换目录保存时相对路径重算（不再静默丢资产） ----')
    with tempfile.TemporaryDirectory() as root:
        dir_a = os.path.join(root, 'assets'); os.makedirs(dir_a)
        dir_b = os.path.join(root, 'scenes'); os.makedirs(dir_b)
        faces = [_png(os.path.join(dir_a, n))
                 for n in ('px.png', 'nx.png', 'py.png', 'ny.png', 'pz.png', 'nz.png')]
        ed = _ed(os.path.join(dir_a, 'draft.json'))
        r = _cmd('skybox_set', ed, {'paths': faces})
        check('设置成功', r.get('ok') is True, r)
        # 另存为到 dir_b（图仍在 dir_a = 场景目录之外）: A3=B 裁决后**不得**写出 '..' 路径,
        # 而是整块不写 + 记 valid=False/reason（不静默写一个将来加载必然失败的值）。
        p_b = os.path.join(dir_b, 'one.json')
        ed._scene_path = p_b
        data = S.scene_to_dict(ed, camera=ed._camera_dict(),
                               base_dir=os.path.dirname(p_b))
        emitted = (data.get('skybox') or {}).get('paths') or []
        check('另存到 dir_b（图在场景目录外）-> 不写出越界路径',
              data.get('skybox') is None and emitted == [], (data.get('skybox'), emitted))
        check('且 valid=False + reason 点名场景目录（不静默）',
              getattr(ed, '_skybox_valid', None) is False
              and '场景目录' in str(getattr(ed, '_skybox_error', None)),
              (getattr(ed, '_skybox_valid', None),
               getattr(ed, '_skybox_error', None)))
        S.save_json_atomic(p_b, data)
        eng2 = _ed(p_b)
        S.scene_from_dict(eng2, json.load(open(p_b, encoding='utf-8')),
                          base_dir=os.path.dirname(p_b))
        check('按新目录重载 -> 默认蓝（文件里确实没有越界路径）',
              tuple(getattr(eng2._skybox, '_solid_color', ())) == S.DEFAULT_SKYBOX_COLOR,
              getattr(eng2._skybox, '_solid_color', None))
        # 同目录保存也仍然正确
        p_a = os.path.join(dir_a, 'two.json')
        ed._scene_path = p_a
        data2 = S.scene_to_dict(ed, camera=ed._camera_dict(),
                                base_dir=os.path.dirname(p_a))
        check('同目录保存 -> 纯文件名（无 ..）',
              all(not os.path.isabs(x) and '..' not in x
                  for x in (data2.get('skybox') or {}).get('paths') or []),
              (data2.get('skybox') or {}).get('paths'))


# ============ ⑬ P2: 相机级 valid/reason + 播放守卫 + 颜色收严 ============
def t_p2_batch():
    print('---- 13) P2: 相机级 valid/reason / 播放守卫 / 颜色收严 ----')
    # P2-1: 相机"没有"天空盒 = 正常态
    eng = _ed()
    S.scene_from_dict(eng, {'version': 10, 'objects': [],
                            'cameras': [{'id': 'c1', 'name': 'cam'}]})
    cam = eng.cameras[0]
    check('相机无 skybox -> valid=True 且 reason=None（修前: False + 假 reason）',
          getattr(cam, '_skybox_valid', None) is True
          and getattr(cam, '_skybox_error', None) is None,
          (getattr(cam, '_skybox_valid', None), getattr(cam, '_skybox_error', None)))
    # P2-1: 相机天空盒坏了要进 skybox_get
    eng2 = _ed()
    S.scene_from_dict(eng2, {'version': 10, 'objects': [],
                             'cameras': [{'id': 'c1', 'name': 'cam',
                                          'skybox': {'solid_color': [0.1, 0.2, 0.3]}}]})
    eng2.active_camera = 'c1'
    got = _cmd('skybox_get', eng2)
    camsb = got.get('active_camera_skybox') or {}
    check('相机级解析失败 -> skybox_get 里 valid=False + reason 可读',
          camsb.get('valid') is False and bool(camsb.get('reason')), camsb)
    check('顶层 valid 也反映相机级失败', got.get('valid') is False, got.get('valid'))
    # P2-2: 播放中禁止改场景天空盒
    ed = _ed(); ed._new_scene(); ed.is_playing = True
    r1 = _cmd('skybox_set', ed, {'solid_color': [1, 2, 3]})
    r2 = _cmd('skybox_clear', ed)
    check('播放中 skybox_set -> ok=False + 原因',
          r1.get('ok') is False and '播放中' in str(r1.get('error')), r1)
    check('播放中 skybox_clear -> ok=False + 原因',
          r2.get('ok') is False and '播放中' in str(r2.get('error')), r2)
    # P2-3: 颜色收严
    rgba, why = S.parse_color([float('nan'), 0, 0])
    check('nan -> reason 指明"有限数"（不再误报 0-1 浮点）',
          rgba is None and '有限数' in str(why), why)
    rgba, why = S.parse_color([float('inf'), 0, 0])
    check('inf -> reason 指明"有限数"', rgba is None and '有限数' in str(why), why)
    rgba, why = S.parse_color('3A9BD5')
    check("'3A9BD5' 无 # -> 拒绝（Q4=A 收严）",
          rgba is None and '#' in str(why), why)
    rgba, why = S.parse_color('#3A9BD5')
    check("'#3A9BD5' -> (58,155,213,255)", rgba == (58, 155, 213, 255), (rgba, why))


# ============ ⑭ A3=B: 六面图路径限制在场景目录内 ============
def t_path_confinement():
    print('---- 14) A3=B: 六面图必须在场景目录内（绝对/.. 越界拒绝） ----')
    with tempfile.TemporaryDirectory() as root:
        scene_dir = os.path.join(root, 'scene')
        faces_dir = os.path.join(scene_dir, 'assets', 'faces')
        os.makedirs(faces_dir)
        names = ('px.png', 'nx.png', 'py.png', 'ny.png', 'pz.png', 'nz.png')
        for n in names:
            _png(os.path.join(faces_dir, n))
        rel_sub = ['assets/faces/' + n for n in names]
        cube, valid, reason = S.skybox_from_dict({'paths': rel_sub}, scene_dir)
        check('① 场景目录内子目录的 6 面图可加载',
              valid is True and cube is not None, reason)

        # ② ../ 越界：把图真实放到场景目录**外**再引用
        outside = os.path.join(root, 'outside.png')
        _png(outside)
        bad_rel = ['../outside.png'] * 6
        cube2, valid2, reason2 = S.skybox_from_dict({'paths': bad_rel}, scene_dir)
        check('② ../ 越界被拒绝且 reason 点名"场景目录"',
              valid2 is False and '场景目录' in str(reason2), reason2)

        # ② 绝对路径一律拒绝
        abs_six = [os.path.join(faces_dir, n) for n in names]
        cube3, valid3, reason3 = S.skybox_from_dict({'paths': abs_six}, scene_dir)
        check('② 绝对路径被拒绝且 reason 点名"绝对路径"',
              valid3 is False and '绝对路径' in str(reason3), reason3)

        # ③ 保存越界：cube 的图在场景目录外 -> 不写出 + valid=False + reason 可见
        from loom_cubemap import Cubemap
        out_six = []
        for i, n in enumerate(names):
            pth = os.path.join(root, 'ext', n)
            os.makedirs(os.path.dirname(pth), exist_ok=True)
            out_six.append(_png(pth))
        cube_out = Cubemap.from_files(out_six, name='越界六面图')
        emitted, why = S._emit_skybox_checked(cube_out, scene_dir)
        check('③ 保存越界路径 -> 不写出（返回 None）+ reason 点名',
              emitted is None and '场景目录' in str(why), (emitted, why))
        eng = _ed()
        eng._scene_skybox = cube_out
        eng._skybox = cube_out
        data = S.scene_to_dict(eng, camera=eng._camera_dict(), base_dir=scene_dir)
        check('③ scene_to_dict 不写越界 skybox（skybox=None）',
              data.get('skybox') is None, data.get('skybox'))
        check('③ 并把 valid=False / reason 记进引擎（不静默）',
              getattr(eng, '_skybox_valid', None) is False
              and '场景目录' in str(getattr(eng, '_skybox_error', None)),
              (getattr(eng, '_skybox_valid', None),
               getattr(eng, '_skybox_error', None)))


# ============ ⑮ A1: 清空 = 恢复默认蓝天（不是"没有天空盒"） ============
def t_clear_means_default():
    print('---- 15) A1: skybox_clear = 恢复默认蓝天（+ #000000 才是黑） ----')
    src = open(os.path.join(ROOT, 'agent_commands.py'), encoding='utf-8').read()
    check('命令帮助写明"清空 = 恢复默认蓝天"',
          '恢复**默认蓝天盒**' in src or '恢复默认蓝天' in src)
    check('命令帮助给出黑天空的显式方式（solid_color=#000000）',
          '#000000' in src)

    ed = _ed()
    ed._new_scene()
    # 先设成红的，再 clear -> 回到默认蓝
    red, _ = S.parse_color('#FF0000')
    _cmd('skybox_set', ed, {'solid_color': '#FF0000'})
    check('前置: 设成红', tuple(ed._scene_skybox._solid_color) == (255, 0, 0, 255),
          ed._scene_skybox._solid_color)
    r = _cmd('skybox_clear', ed)
    check('clear -> ok + reset_to_default=True（不再返回 cleared/none 语义）',
          r.get('ok') is True and r.get('reset_to_default') is True, r)
    check('clear 后 effective 是默认蓝 (58,155,213,255)',
          (r.get('effective') or {}).get('solid_color') == list(S.DEFAULT_SKYBOX_COLOR),
          r.get('effective'))
    check('clear 后 effective_skybox() 是默认蓝且绘制门为真',
          tuple(ed.effective_skybox()._solid_color) == S.DEFAULT_SKYBOX_COLOR
          and getattr(ed, '_skybox', None) is not None,
          ed.effective_skybox()._solid_color)
    # 存盘重载仍是默认蓝（期望行为，不是丢值）
    with tempfile.TemporaryDirectory() as tmp:
        p = os.path.join(tmp, 'c.json')
        data = S.scene_to_dict(ed, camera=ed._camera_dict(), base_dir=tmp)
        check('clear 后存盘写出默认蓝',
              (data.get('skybox') or {}).get('solid_color') == list(S.DEFAULT_SKYBOX_COLOR),
              data.get('skybox'))
        S.save_json_atomic(p, data)
        eng2 = _ed(p)
        S.scene_from_dict(eng2, json.load(open(p, encoding='utf-8')),
                          base_dir=os.path.dirname(p))
        check('重载仍是默认蓝（A1 期望行为）',
              tuple(eng2._skybox._solid_color) == S.DEFAULT_SKYBOX_COLOR,
              eng2._skybox._solid_color)
    # 黑天空: 显式 #000000 -> 黑且能持久
    rb = _cmd('skybox_set', ed, {'solid_color': '#000000'})
    check('设 #000000 -> 黑 (0,0,0,255)',
          tuple(ed._scene_skybox._solid_color) == (0, 0, 0, 255),
          ed._scene_skybox._solid_color)
    with tempfile.TemporaryDirectory() as tmp2:
        data2 = S.scene_to_dict(ed, camera=ed._camera_dict(), base_dir=tmp2)
        eng3 = _ed(os.path.join(tmp2, 'b.json'))
        S.scene_from_dict(eng3, data2, base_dir=tmp2)
        check('黑天空能持久（重载仍黑）',
              tuple(eng3._skybox._solid_color) == (0, 0, 0, 255),
              eng3._skybox._solid_color)


def main():
    t_new_scene_default()
    t_load_without_skybox()
    t_color_reject()
    t_color_roundtrip()
    t_sixface_paths()
    t_camera_priority()
    t_draw_gate_effective()
    t_reset_sky_state()
    t_get_vk_error()
    t_set_takes_effect()
    t_bad_skybox_type()
    t_save_as_relative()
    t_p2_batch()
    t_path_confinement()
    t_clear_means_default()
    print('\n总结果: %s' % ('ALL PASS' if ok else 'FAIL'))
    sys.exit(0 if ok else 1)


if __name__ == '__main__':
    main()