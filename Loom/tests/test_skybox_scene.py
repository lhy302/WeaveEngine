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
    src = open(os.path.join(ROOT, 'editor.py'), encoding='utf-8').read()
    check('绘制门用 self.effective_skybox()（修前只认 self._skybox）',
          'if self.effective_skybox() is not None:' in src)
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
    print('\n总结果: %s' % ('ALL PASS' if ok else 'FAIL'))
    sys.exit(0 if ok else 1)


if __name__ == '__main__':
    main()