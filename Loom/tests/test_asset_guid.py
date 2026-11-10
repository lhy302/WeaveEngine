# -*- coding: utf-8 -*-
"""test_asset_guid.py — beta6 B1 资产身份层回归（项目 Assets/ + assets.json + guid）。

覆盖（验收硬门）:
  ① 贴图导入: 复制进项目 + 登记 guid + 指纹;  ② 同文件二次导入去重（不得两个 guid）
  ③ 同 guid 指向不同内容 -> 报错;             ④ 六面图导入为目录资产
  ⑤ 场景落盘只写 guid（无 path/paths）;       ⑥ 原地重载恢复
  ⑦ 项目目录改名后重载仍有效（E2E-1）;      ⑧ 缺文件 -> 回退 + reason（不静默）
  ⑨ 旧路径 fallback -> 告警 + 照常加载;      ⑩ 材质 guid 重复 -> 告警
  ⑪ 索引越界 src -> 拒绝 + reason;           ⑫ 迁移脚本往返 + 幂等
  ⑬ 打包带资产 -> 发布夹里贴图仍在（E2E-2）; ⑬b game_pack 往返
  ⑭ EAI 命令: asset_import / asset_list / asset_get / scene_assets_check

跑法: cd Loom && python tests/test_asset_guid.py
只写临时目录，不写受跟踪文件。
"""
# 2026-11-10 (批次 C1): 与既有测试同款 stdout UTF-8 兜底 —— run_all 走管道时
# Windows 控制台默认 GBK, print('⑪ ...') 等符号会 UnicodeEncodeError, 让
# "全绿"被记成 exit=1 的假失败 (本轮基线实测: test_asset_guid 单独跑绿, 经
# run_all 管道跑红).
import sys as _sys_utf8
try:
    _sys_utf8.stdout.reconfigure(encoding='utf-8', errors='replace')
    _sys_utf8.stderr.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

import contextlib
import glob
import io
import json
import os
import shutil
import struct
import sys
import tempfile
import time
import zlib

HERE = os.path.dirname(os.path.abspath(__file__))
LOOM = os.path.dirname(HERE)
sys.path.insert(0, LOOM)
os.chdir(LOOM)
os.environ.setdefault('LOOM_USER_ROOT', os.path.join(tempfile.gettempdir(), 'loom_ag_user'))
os.environ.setdefault('LOOM_GAME_DIR', os.path.join(tempfile.gettempdir(), 'loom_ag_game'))
os.makedirs(os.environ['LOOM_GAME_DIR'], exist_ok=True)

import engine as E                                       # noqa: E402
import editor                                            # noqa: E402
import sceneio as S                                      # noqa: E402
import loom_assets                                       # noqa: E402
import game_pack                                         # noqa: E402
import build_game                                        # noqa: E402
import agent_commands as AC                              # noqa: E402
from undo import UndoManager                             # noqa: E402

E.GLEngine._build_gpu = lambda self, m: None             # 无头桩

ok = True


def check(label, cond, detail=''):
    global ok
    print(('PASS ' if cond else 'FAIL ') + label + ('  ' + str(detail) if detail else ''))
    if not cond:
        ok = False


def _png(path, rgba=(200, 30, 30, 255)):
    os.makedirs(os.path.dirname(path), exist_ok=True)
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


FACES = ('px', 'nx', 'py', 'ny', 'pz', 'nz')


def six(dirpath, rgba=(20, 120, 220, 255)):
    os.makedirs(dirpath, exist_ok=True)
    return [_png(os.path.join(dirpath, '%s.png' % n), rgba) for n in FACES]


class _View(object):
    def reset_interaction(self):
        pass


def _ed(scene_path=None):
    ed = editor.EditorApp.__new__(editor.EditorApp)
    ed.models, ed.materials, ed.lights, ed.cameras = [], [], [], []
    ed.undo = UndoManager()
    ed.is_playing = False
    ed.active_camera = None
    ed.gravity = -9.8
    ed._skybox = None
    ed._scene_skybox = None
    ed._skybox_valid = True
    ed._skybox_error = None
    ed._asset_errors = []
    ed.ui = None
    ed._scene_path = scene_path
    ed.view = _View()
    ed.camera_target = (0.0, 0.0, 0.0)
    ed.camera_distance = 10.0
    ed.camera_yaw = 0.6
    ed.camera_pitch = -0.35
    # _new_scene() 需要的编辑器态（D-01 要跑真实入口）
    ed.width, ed.height = 1280, 800
    ed._scene_cam = None
    ed.scene_name = '场景'
    ed.selected_index = 0
    ed.selected_light_index = -1
    ed.selected_camera_index = -1
    ed._sky_eff_last = None
    ed.msg = ''
    ed.msg_color = (220, 222, 228)
    ed._msg_until = 0.0
    ed.last_dir = None
    return ed


class _Win(object):
    def __init__(self, ed):
        self.editor = ed


def _cmd(name, ed, args=None):
    return AC.dispatch(name, dict(args or {}), _Win(ed))


def _cap(fn):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        out = fn()
    return out, buf.getvalue()


def _files(d):
    n = 0
    for _r, _ds, fs in os.walk(d):
        n += len(fs)
    return n


# ---------------------------------------------------------------- ①–④ 导入
def t_import():
    print('---- ① 贴图导入 / 去重 / 冲突 / 六面图 ----')
    tmp = tempfile.mkdtemp(prefix='loom_ag_')
    proj = os.path.join(tmp, 'proj')
    os.makedirs(proj)
    png1 = _png(os.path.join(tmp, 'src', 'wood.png'))
    png1b = _png(os.path.join(tmp, 'src', 'wood_copy.png'))
    png2 = _png(os.path.join(tmp, 'src', 'metal.png'), (10, 200, 10, 255))
    ed = _ed(os.path.join(proj, 'scene.json'))

    g1, created, why = ed.asset_import(path=png1, kind='texture')
    check('导入贴图返回 32 hex guid', isinstance(g1, str) and len(g1) == 32 and created, (g1, why))
    check('项目索引 Assets/assets.json 已创建',
          os.path.isfile(os.path.join(proj, 'Assets', 'assets.json')))
    check('源图被复制进 Assets/Textures',
          os.path.isdir(os.path.join(proj, 'Assets', 'Textures'))
          and _files(os.path.join(proj, 'Assets', 'Textures')) == 1,
          _files(os.path.join(proj, 'Assets', 'Textures')))
    ctx = loom_assets.AssetContext.open_root(proj)
    e1 = ctx.entry(g1)
    check('条目 src 是项目相对路径', e1.get('src', '').startswith('Assets/'), e1.get('src'))
    check('条目有指纹 sha256/size/mtime',
          set(('sha256', 'size', 'mtime')) <= set((e1.get('fingerprint') or {})))

    g1b, created_b, why_b = ed.asset_import(path=png1b, kind='texture')
    check('同内容二次导入 -> 同 guid、不重复复制',
          g1b == g1 and created_b is False
          and _files(os.path.join(proj, 'Assets', 'Textures')) == 1, (g1b, created_b))
    g2, _, _ = ed.asset_import(path=png2, kind='texture')
    check('不同内容 -> 不同 guid', g2 and g2 != g1)
    gbad, created_bad, why_bad = ctx.import_texture(png2, guid=g1)
    check('同 guid 指向不同内容 -> 拒绝且 reason 点名',
          gbad is None and '同 guid' in str(why_bad), why_bad)

    faces = six(os.path.join(tmp, 'sky'))
    gc, created_c, why_c = ed.asset_import(kind='cubemap', paths=faces)
    check('六面图导入返回 guid', isinstance(gc, str) and created_c, (gc, why_c))
    ctx = loom_assets.AssetContext.open_root(proj)      # 导入后索引已变 -> 重开
    ec = ctx.entry(gc)
    check('六面图是目录资产（6 个文件）',
          os.path.isdir(os.path.join(proj, ec['src'].replace('/', os.sep)))
          and len(ec.get('files') or []) == 6, ec.get('files'))
    return tmp, proj, g1, gc


# ---------------------------------------------------------------- ⑤–⑦ 场景往返
def t_roundtrip(tmp, proj, g1, gc):
    print('---- ⑤–⑦ 场景只写 guid / 重载 / 改名后重载 ----')
    ctx = loom_assets.AssetContext.open_root(proj)
    tex, ok1, why1 = ctx.texture(g1)
    cube, ok2, why2 = ctx.cubemap(gc)
    check('解析贴图/立方图均 valid', tex is not None and cube is not None, (why1, why2))

    ed = _ed(os.path.join(proj, 'scene.json'))
    mat = ed.add_material(color=None, name='木')
    mat.albedo = tex
    mat.env_map = cube
    m = ed.add_model(__import__('mesh').create_cube(1.0), E.Point3D(0, 0, 0),
                     E.Point3D(0, 0, 0))
    m.renderer.material = mat
    ed._scene_skybox = cube
    ed._skybox = cube
    data = S.scene_to_dict(ed, base_dir=proj)
    md = data['materials'][0]
    check('场景 albedo 只写 guid（无 path）',
          md['albedo'].get('guid') == g1 and 'path' not in md['albedo'], md['albedo'])
    check('场景 env_map 只写 guid（无 paths）',
          md['env_map'].get('guid') == gc and 'paths' not in md['env_map'], md['env_map'])
    check('场景 skybox 只写 guid（无 paths）',
          (data.get('skybox') or {}).get('guid') == gc
          and 'paths' not in (data.get('skybox') or {}), data.get('skybox'))

    scene_p = os.path.join(proj, 'scene.json')
    S.save_json_atomic(scene_p, data)

    ed2 = _ed(scene_p)
    _, out2 = _cap(lambda: S.scene_from_dict(ed2, json.load(open(scene_p, encoding='utf-8')),
                                             base_dir=proj))
    mat2 = [x for x in ed2.materials if x.guid == md['id']][0]
    check('原地重载: 贴图恢复且 guid 一致',
          mat2.albedo is not None and mat2.albedo.guid == g1)
    check('原地重载: 环境贴图恢复',
          mat2.env_map is not None and mat2.env_map.guid == gc)
    check('原地重载: 天空盒 6 面恢复',
          len(getattr(ed2._scene_skybox, 'paths', []) or []) == 6, ed2._skybox_valid)
    check('原地重载: 无资产问题', not S.asset_errors(ed2), S.asset_errors(ed2))

    proj2 = os.path.join(tmp, 'proj_renamed')
    os.rename(proj, proj2)
    scene_p2 = os.path.join(proj2, 'scene.json')
    ed3 = _ed(scene_p2)
    _cap(lambda: S.scene_from_dict(ed3, json.load(open(scene_p2, encoding='utf-8')),
                                   base_dir=proj2))
    mat3 = [x for x in ed3.materials if x.guid == md['id']][0]
    check('E2E-1 项目目录改名后重载: 贴图仍在',
          mat3.albedo is not None and mat3.albedo.width == 8)
    check('E2E-1 改名后: 天空盒仍在', ed3._skybox_valid is True)
    return proj2, data


# ---------------------------------------------------------------- ⑧⑨⑩ 失败可见
def t_failure_visible(tmp, proj2, data):
    print('---- ⑧ 缺文件回退+reason / ⑨ 旧路径 fallback / ⑩ 重复材质 guid ----')
    bad = json.loads(json.dumps(data))
    bad['materials'][0]['albedo'] = {'guid': 'deadbeef' * 4}
    ed = _ed()
    _, out = _cap(lambda: S.scene_from_dict(ed, bad, base_dir=proj2))
    errs = S.asset_errors(ed)
    check('未知 guid -> 有 reason、不崩',
          bool(errs) and any('未在项目索引' in r for _w, _g, r in errs), errs)
    check('未知 guid -> 出声（[资产]）', '[资产]' in out)

    # 缺文件: 把导入的贴图源文件删掉
    idx = loom_assets.load_index(proj2)[0]
    victim_guid = (data['materials'][0]['albedo'] or {}).get('guid')
    victim_entry = idx['assets'].get(victim_guid) or {}
    victim = (victim_guid, os.path.join(proj2, str(victim_entry.get('src', '')).replace('/', os.sep)))
    _backup = open(victim[1], 'rb').read()
    os.remove(victim[1])
    ed2 = _ed()
    data2 = json.loads(json.dumps(data))
    _, out2 = _cap(lambda: S.scene_from_dict(ed2, data2, base_dir=proj2))
    errs2 = S.asset_errors(ed2)
    check('源文件缺失 -> 有 reason（资产文件缺失）',
          any('缺失' in r for _w, _g, r in errs2), errs2)
    check('源文件缺失 -> 出声', '[资产]' in out2)
    check('源文件缺失 -> 贴图回退为 None（不崩）',
          all(getattr(x, 'albedo', None) is None for x in ed2.materials
              if x.guid == data['materials'][0]['id']))
    # 内容变更检测: 写不同字节 -> 软告警（valid 仍 True，提示 asset_reimport）
    with open(victim[1], 'wb') as f:
        f.write(_backup + bytes(8))
    ed2b = _ed()
    _, out2b = _cap(lambda: S.scene_from_dict(ed2b, json.loads(json.dumps(data)), base_dir=proj2))
    check('内容变更 -> 软告警（内容已变更）',
          any('内容已变更' in r for _w, _g, r in S.asset_errors(ed2b)), S.asset_errors(ed2b))
    check('内容变更 -> 仍可加载（valid=True 不阻塞）',
          any(getattr(x, 'albedo', None) is not None for x in ed2b.materials))
    with open(victim[1], 'wb') as f:          # 还原，供 ⑬ 打包用例继续用
        f.write(_backup)

    # 旧路径 fallback：无项目资产库的目录
    plain = os.path.join(tmp, 'plain')
    os.makedirs(plain, exist_ok=True)
    src = _png(os.path.join(plain, 'legacy.png'))
    legacy = {'version': 10, 'objects': [], 'materials': [
        {'id': 'LM', 'name': 'l', 'color': None, 'saturation': 1.0,
         'albedo': {'guid': 'whatever', 'path': src, 'name': 'legacy'}}]}
    ed3 = _ed()
    _, out3 = _cap(lambda: S.scene_from_dict(ed3, legacy, base_dir=plain))
    mat3 = ed3.materials[0]
    check('旧路径 fallback: 照常加载出贴图', mat3.albedo is not None)
    check('旧路径 fallback: 告警点名"旧路径引用"',
          any('旧路径引用' in r for _w, _g, r in S.asset_errors(ed3)), S.asset_errors(ed3))
    check('旧路径 fallback: 出声', '[资产]' in out3)

    dup = {'version': 11, 'materials': [
        {'id': 'dup', 'name': 'a', 'color': '#FF0000', 'saturation': 1.0},
        {'id': 'dup', 'name': 'b', 'color': '#00FF00', 'saturation': 1.0}],
        'objects': []}
    ed4 = _ed()
    _, out4 = _cap(lambda: S.scene_from_dict(ed4, dup))
    check('材质 guid 重复 -> 告警', '材质 guid 重复' in out4, out4.strip()[:120])


# ---------------------------------------------------------------- ⑪ 索引越界
def t_index_guard():
    print('---- ⑪ 索引越界 / 损坏 ----')
    tmp = tempfile.mkdtemp(prefix='loom_ag_idx_')
    os.makedirs(os.path.join(tmp, 'Assets'))
    p = os.path.join(tmp, 'Assets', 'assets.json')
    with open(p, 'w', encoding='utf-8') as f:
        json.dump({'schema': 1, 'assets': {
            'a' * 32: {'type': 'texture', 'src': '../outside.png', 'import': {}}}}, f)
    idx, good, why = loom_assets.load_index(tmp)
    # Q-B1-2=A: 一条坏条目 -> 只剔除该条，索引整体仍可用（不再整本作废）
    check('越界 src -> 剔除该条 + 告警点名（索引仍可用）',
          idx is not None and good and not (idx.get('assets') or {})
          and ('越界' in str(why) or '相对路径' in str(why)), why)
    ctx_bad = loom_assets.AssetContext.for_dir(tmp)
    check('坏条目项目 -> 上下文仍可用（空的可用索引，不再退回旧路径模式）',
          ctx_bad is not None and ctx_bad.entries() == {})

    with open(p, 'w', encoding='utf-8') as f:
        f.write('{ 坏 json')
    idx2, good2, why2 = loom_assets.load_index(tmp)
    check('损坏索引不抛、给 reason', idx2 is None and not good2 and '损坏' in str(why2), why2)
    # 确定性：只有名为 assets（小写、无 assets.json）的目录 -> 不算项目根
    fake = tempfile.mkdtemp(prefix='loom_f02_root_')
    os.makedirs(os.path.join(fake, 'assets', 'Textures'), exist_ok=True)
    check('find_project_root 不误认名叫 assets 的目录（大小写/缺索引）',
          loom_assets.find_project_root(fake) is None)


# ---------------------------------------------------------------- ⑫ 迁移
def t_migrate():
    print('---- ⑫ 迁移脚本往返 + 幂等 ----')
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        'migrate_b1', os.path.join(os.path.dirname(LOOM), 'tools',
                                   'migrate_scene_assets_v11.py'))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    tmp = tempfile.mkdtemp(prefix='loom_ag_mig_')
    proj = os.path.join(tmp, 'legacy_proj')
    os.makedirs(proj)
    alb = _png(os.path.join(proj, 'tex', 'a.png'))
    faces = six(os.path.join(proj, 'sky'))
    rel = ['sky/%s.png' % n for n in FACES]
    scene = {'version': 10, 'objects': [], 'materials': [
        {'id': 'M1', 'name': 'm', 'color': None, 'saturation': 1.0,
         'albedo': {'guid': 'oldg', 'path': alb, 'name': 'a'}}],
        'skybox': {'paths': rel, 'name': 'sky'},
        'cameras': [{'id': 'c1', 'skybox': {'paths': rel, 'name': 'sky'}}]}
    sp = os.path.join(proj, 'scene.json')
    S.save_json_atomic(sp, scene)

    rep = mod.migrate_scene(sp)
    check('迁移: 有改动、无失败', rep['changed'] >= 2 and not rep['failures'], rep)
    check('迁移: 版本升到 SCENE_VERSION', rep['version_after'] == S.SCENE_VERSION)
    new = json.load(open(sp, encoding='utf-8'))
    check('迁移: 材质 albedo 变 guid',
          'path' not in new['materials'][0]['albedo']
          and new['materials'][0]['albedo']['guid'])
    check('迁移: 场景天空盒变 guid',
          'paths' not in (new.get('skybox') or {}) and (new.get('skybox') or {}).get('guid'))
    check('迁移: 相机天空盒变 guid',
          'paths' not in (new['cameras'][0].get('skybox') or {}))
    ed = _ed()
    _cap(lambda: S.scene_from_dict(ed, new, base_dir=proj))
    check('迁移后可直接加载且无资产问题', not S.asset_errors(ed), S.asset_errors(ed))

    rep2 = mod.migrate_scene(sp)
    check('二次迁移幂等（changed=0）', rep2['changed'] == 0, rep2['changed'])


# ---------------------------------------------------------------- ⑬ 打包
def t_pack(tmp, proj2, data):
    print('---- ⑬ 打包带资产（发布夹目录加载）+ game_pack 往返 ----')
    scene_p = os.path.join(proj2, 'scene.json')
    out = os.path.join(tmp, 'release')
    os.makedirs(out, exist_ok=True)
    check('copy_project_assets -> True', build_game.copy_project_assets(scene_p, out) is True)
    check('发布夹内 Assets/assets.json 存在',
          os.path.isfile(os.path.join(out, 'Assets', 'assets.json')))
    check('发布夹内贴图文件在',
          _files(os.path.join(out, 'Assets', 'Textures')) >= 1)

    game_pack.pack(out, {'name': 'T'}, data, [])
    # "解压到别的目录"：把整个发布夹搬走，再从新位置读包 + 加载（模拟换机/换盘）
    out_moved = os.path.join(tmp, 'release_moved', 'Game')
    os.makedirs(os.path.dirname(out_moved), exist_ok=True)
    os.rename(out, out_moved)
    gm = game_pack.load(out_moved)
    check('game_pack 往返可读', isinstance(gm, dict) and gm.get('fmt') == 'loom-pack-1')
    # 模拟 game_player: scene_data + assets_base=发布夹（别的目录启动 = 这里 out）
    ed = _ed()
    _, outp = _cap(lambda: S.scene_from_dict(ed, gm['scene'], base_dir=out_moved))
    mat = [x for x in ed.materials if getattr(x, 'albedo', None) is not None]
    check('E2E-2 发布夹搬到别的目录后加载: 贴图仍在', bool(mat), S.asset_errors(ed))
    check('E2E-2 发布夹搬到别的目录后加载: 天空盒有效', ed._skybox_valid is True)
    check('E2E-2 无资产问题', not S.asset_errors(ed), S.asset_errors(ed))


# ---------------------------------------------------------------- ⑭ 命令
def t_commands(tmp, proj2):
    print('---- ⑭ EAI 命令: asset_import / asset_list / asset_get / scene_assets_check ----')
    png = _png(os.path.join(tmp, 'cmd_src', 'tex.png'), (1, 2, 250, 255))
    ed_no = _ed()
    r = _cmd('asset_import', ed_no, {'type': 'texture', 'path': png})
    check('asset_import 未保存场景 -> 拒绝（不给引擎目录造 Assets/）',
          r.get('ok') is False and '先保存场景' in str(r.get('error')), r)

    ed = _ed(os.path.join(proj2, 'scene.json'))
    r2 = _cmd('asset_import', ed, {'type': 'texture', 'path': png, 'name': 'cmd'})
    check('asset_import 成功返回 guid',
          r2.get('ok') is True and (r2.get('result') or {}).get('guid'), r2)
    guid = r2['result']['guid']
    r3 = _cmd('asset_get', ed, {'guid': guid})
    _r3 = r3.get('result') or {}
    check('asset_get valid + src', r3.get('ok') is True and _r3.get('valid') is True
          and _r3.get('src'), r3)
    r4 = _cmd('asset_list', ed, {'type': 'texture'})
    check('asset_list 列出贴图',
          r4.get('ok') is True and (r4.get('result') or {}).get('count', 0) >= 1, r4)
    r5 = _cmd('scene_assets_check', ed, {})
    check('scene_assets_check 结构 ok/count/errors',
          r5.get('ok') is True and 'count' in (r5.get('result') or {}), r5)
    r6 = _cmd('asset_get', ed, {'guid': 'nope'})
    check('asset_get 未知 guid -> valid False + reason',
          (r6.get('result') or {}).get('valid') is False, r6)




# ================================================================ 轮5 审核修复
# ---------------------------------------------------------------- P1-1
def t_p1_1_preserve_refs():
    print('---- 轮5 P1-1: 解析失败后保存**不得**销毁 guid 引用 ----')
    tmp = tempfile.mkdtemp(prefix='loom_r5_p11_')
    proj = os.path.join(tmp, 'proj')
    os.makedirs(proj)
    ctx = loom_assets.AssetContext.for_dir(proj, create=True)
    png = _png(os.path.join(tmp, 'src', 'a.png'))
    guid, _c, why = ctx.import_texture(png, name='a')
    faces = six(os.path.join(tmp, 'sky'))
    cg, _c2, why2 = ctx.import_cubemap(faces, name='sky')
    check('前置: 贴图/六面图导入', bool(guid) and bool(cg), (why, why2))
    ctx = loom_assets.AssetContext.open_root(proj)
    tex, ok1, _w1 = ctx.texture(guid)
    cube, ok2, _w2 = ctx.cubemap(cg)
    ed = _ed(os.path.join(proj, 'scene.json'))
    mat = ed.add_material(color=None, name='m')
    mat.albedo = tex
    mat.env_map = cube
    m = ed.add_model(__import__('mesh').create_cube(1.0), E.Point3D(0, 0, 0),
                     E.Point3D(0, 0, 0))
    m.renderer.material = mat
    ed._scene_skybox = cube
    ed._skybox = cube
    data = S.scene_to_dict(ed, base_dir=proj)
    scene_p = os.path.join(proj, 'scene.json')
    S.save_json_atomic(scene_p, data)
    mat_id = data['materials'][0]['id']

    # A) 删掉贴图源文件 -> 打开 -> 保存 -> 重开
    alb_rel = (ctx.entry(guid) or {}).get('src') or ''
    os.remove(os.path.join(proj, alb_rel.replace('/', os.sep)))
    ed2 = _ed(scene_p)
    _, out2 = _cap(lambda: S.scene_from_dict(
        ed2, json.load(open(scene_p, encoding='utf-8')), base_dir=proj))
    check('A 缺贴图 -> 打开告警', any('缺失' in r for _w, _g, r in S.asset_errors(ed2)),
          S.asset_errors(ed2))
    check('A 打开后贴图确实没解析出来（前置成立）',
          any(x.guid == mat_id and getattr(x, 'albedo', None) is None
              for x in ed2.materials))
    data2 = S.scene_to_dict(ed2, base_dir=proj)
    md = data2['materials'][0]
    check('A 保存后 albedo guid 仍在（旧行为: 整键消失）',
          (md.get('albedo') or {}).get('guid') == guid, md.get('albedo'))
    check('A 保存后 albedo 仍是 guid 引用（无 path）',
          'path' not in (md.get('albedo') or {}))
    check('A 保存后 env_map 仍在', (md.get('env_map') or {}).get('guid') == cg)
    p2 = os.path.join(proj, 'scene2.json')
    S.save_json_atomic(p2, data2)
    ed3 = _ed(p2)
    _, out3 = _cap(lambda: S.scene_from_dict(
        ed3, json.load(open(p2, encoding='utf-8')), base_dir=proj))
    check('A 重开后仍告警（持续可见）', bool(S.asset_errors(ed3)), S.asset_errors(ed3))
    data3 = S.scene_to_dict(ed3, base_dir=proj)
    check('A 连续两次保存 guid 不漂移',
          (data3['materials'][0].get('albedo') or {}).get('guid') == guid)

    # B) 整个项目没有资产索引（天空盒/贴图都是纯 guid）-> 保存必须保留原 guid
    plain = os.path.join(tmp, 'plain')
    os.makedirs(plain, exist_ok=True)
    raw = {'version': S.SCENE_VERSION, 'objects': [],
           'skybox': {'guid': 'deadsky'},
           'materials': [{'id': 'M', 'name': 'm', 'color': None, 'saturation': 1.0,
                          'albedo': {'guid': 'deadtex'}}]}
    ed4 = _ed()
    _, out4 = _cap(lambda: S.scene_from_dict(ed4, raw, base_dir=plain))
    check('B 无索引 -> 打开不崩且有告警', bool(S.asset_errors(ed4)))
    data4 = S.scene_to_dict(ed4, base_dir=plain)
    check('B 保存后天空盒仍写原 guid（旧行为: 换成默认蓝 + 新 guid）',
          (data4.get('skybox') or {}).get('guid') == 'deadsky', data4.get('skybox'))
    check('B 保存后 albedo 仍写原 guid',
          (data4['materials'][0].get('albedo') or {}).get('guid') == 'deadtex')
    ed5 = _ed()
    _cap(lambda: S.scene_from_dict(ed5, data4, base_dir=plain))
    check('B 重开后仍告警（不再静默假绿）', bool(S.asset_errors(ed5)))

    # D) 用户**显式清空**才真正移除（Q-B1-1=A 的边界）
    mat_b = [x for x in ed4.materials if x.guid == 'M'][0]
    S.clear_asset_slot(mat_b, 'albedo')
    data5 = S.scene_to_dict(ed4, base_dir=plain)
    check('D 显式清空后 albedo 键才消失',
          'albedo' not in (data5['materials'][0] or {}), data5['materials'][0])

    # C) 相机级天空盒失败也保留（相机段不许丢引用）
    rawc = {'version': S.SCENE_VERSION, 'objects': [], 'skybox': None,
            'cameras': [{'id': 'cam1', 'name': 'c', 'skybox': {'guid': 'deadcam'},
                         'position': [0, 0, 0], 'yaw': 0, 'pitch': 0}]}
    edc = _ed()
    _cap(lambda: S.scene_from_dict(edc, rawc, base_dir=plain))
    dcam = S.scene_to_dict(edc, base_dir=plain)
    cam_sb = ((dcam.get('cameras') or [{}])[0] or {}).get('skybox') or {}
    check('C 相机天空盒失败 -> 保存写回原 guid', cam_sb.get('guid') == 'deadcam', cam_sb)


# ---------------------------------------------------------------- P1-2
def t_p1_2_index_partial():
    print('---- 轮5 P1-2: 一条坏条目不再让整本索引作废 ----')
    tmp = tempfile.mkdtemp(prefix='loom_r5_p12_')
    proj = os.path.join(tmp, 'proj')
    os.makedirs(os.path.join(proj, 'Assets', 'Textures'))
    png = _png(os.path.join(tmp, 'src', 'ok.png'))
    shutil.copy2(png, os.path.join(proj, 'Assets', 'Textures', 'ok.png'))
    st = os.stat(png)
    good = {'type': 'texture', 'src': 'Assets/Textures/ok.png', 'name': 'ok',
            'import': {}, 'fingerprint': {'sha256': loom_assets.sha256_file(png),
                                          'size': st.st_size, 'mtime': st.st_mtime}}
    bad = {'type': 'nonsense', 'src': 'Assets/Textures/x.png'}
    idxp = os.path.join(proj, 'Assets', 'assets.json')
    with open(idxp, 'w', encoding='utf-8') as f:
        json.dump({'schema': 1, 'assets': {'g' * 32: good, 'b' * 32: bad}}, f)
    idx, ok_, why = loom_assets.load_index(proj)
    check('坏一条 -> 索引仍可用 + 告警点名坏条目',
          idx is not None and ok_ and why and '坏条目' in why, why)
    check('好条目保留 / 坏条目剔除',
          ('g' * 32 in idx['assets']) and ('b' * 32 not in idx['assets']), list(idx['assets']))
    ctx = loom_assets.AssetContext.for_dir(proj)
    check('上下文可用（旧行为: None）', ctx is not None and ctx.entry('g' * 32) is not None)
    check('上下文把索引告警带出来', bool(getattr(ctx, 'warnings', None)), ctx.warnings)
    g2, created, why2 = ctx.import_texture(png, name='new')
    check('部分坏索引下仍可导入（旧行为: 永久"无法创建项目资产库"）',
          g2 is not None, why2)

    # 命令层三态
    ed = _ed(os.path.join(proj, 'scene.json'))
    r = _cmd('asset_list', ed)
    res = r.get('result') or {}
    check('asset_list 报 partial + warnings', res.get('state') == 'partial'
          and res.get('valid') is True and res.get('warnings'), res)
    with open(idxp, 'w', encoding='utf-8') as f:
        f.write('{ bad json')
    check('损坏索引 -> inspect=corrupt', loom_assets.inspect_index(proj)['state'] == 'corrupt')
    check('损坏索引 -> for_dir(create=False) 不可用（明确）',
          loom_assets.AssetContext.for_dir(proj) is None)
    r2 = _cmd('asset_list', ed)
    res2 = r2.get('result') or {}
    check('asset_list 区分 corrupt（不再谎报"缺文件"）',
          res2.get('state') == 'corrupt' and '损坏' in str(res2.get('reason')), res2)
    ctx2 = loom_assets.AssetContext.for_dir(proj, create=True)
    check('损坏索引 + create -> 可自愈', ctx2 is not None)
    check('自愈前已备份（不静默覆盖）', len(glob.glob(idxp + '.bak-*')) == 1,
          glob.glob(idxp + '.bak-*'))
    r3 = _cmd('asset_list', ed)
    check('自愈后 asset_list 可用', (r3.get('result') or {}).get('valid') is True, r3)


# ---------------------------------------------------------------- P1-3
def t_p1_3_delta_guard():
    print('---- 轮5 P1-3: 用户层 delta 非 dict 不得崩加载 ----')
    tmp = tempfile.mkdtemp(prefix='loom_r5_p13_')
    proj = os.path.join(tmp, 'proj')
    os.makedirs(proj)
    ctx = loom_assets.AssetContext.for_dir(proj, create=True)
    png = _png(os.path.join(tmp, 'src', 'd.png'))
    guid, _c, why = ctx.import_texture(png, name='d')
    check('前置: 贴图导入', bool(guid), why)
    dpath = loom_assets.user_index_path(proj)
    os.makedirs(os.path.dirname(dpath), exist_ok=True)
    with open(dpath, 'w', encoding='utf-8') as f:
        json.dump({'schema': 1, 'assets': {guid: 'oops-not-a-dict'}}, f)
    data = {'version': S.SCENE_VERSION, 'objects': [],
            'materials': [{'id': 'M', 'name': 'm', 'color': None, 'saturation': 1.0,
                           'albedo': {'guid': guid}}]}
    ed = _ed()
    err = None
    buf = io.StringIO()
    try:
        with contextlib.redirect_stdout(buf):
            S.scene_from_dict(ed, data, base_dir=proj)
    except Exception as e:      # noqa: BLE001 - 这里就是要证明"不抛"
        err = e
    out = buf.getvalue()
    check('delta 条目非 dict -> 加载不崩', err is None, err)
    mat = ed.materials[0]
    check('贴图仍按项目层解析出来（delta 被跳过）', getattr(mat, 'albedo', None) is not None)
    check('有 delta 告警（出声，不静默）', 'delta' in out, out.strip()[:120])
    # 编辑器侧: 加载后必须清空过场景却没崩 -> F7 由"不抛"保证
    check('资产问题未污染（delta 不是场景问题）',
          not any('delta' in r for _w, _g, r in S.asset_errors(ed)))


# ---------------------------------------------------------------- P2-①
def t_p2_1_name_traversal():
    print('---- 轮5 P2-①: name 不得写出 Assets/ 之外 ----')
    tmp = tempfile.mkdtemp(prefix='loom_r5_p21_')
    proj = os.path.join(tmp, 'proj')
    os.makedirs(proj)
    ctx = loom_assets.AssetContext.for_dir(proj, create=True)
    png = _png(os.path.join(tmp, 'src', 't.png'))
    g, created, why = ctx.import_texture(png, name='../../escaped')
    e = ctx.entry(g) or {}
    check('越界 name -> 仍落在 Assets/Textures 下',
          str(e.get('src', '')).startswith('Assets/Textures/'), e.get('src'))
    check('项目根没有逃逸文件', not os.path.isfile(os.path.join(proj, 'escaped.png')))
    faces = six(os.path.join(tmp, 'sky'))
    cg, _c, _w = ctx.import_cubemap(faces, name='../../evil dir')
    ce = ctx.entry(cg) or {}
    check('六面图目录也在 Assets/Cubemaps 下',
          str(ce.get('src', '')).startswith('Assets/Cubemaps/'), ce.get('src'))
    check('六面图名字已净化（无 .. / 空格路径段）',
          '..' not in str(ce.get('src', '')), ce.get('src'))


# ---------------------------------------------------------------- P2-②
def t_p2_2_skybox_in_check():
    print('---- 轮5 P2-②: 悬空天空盒 guid 必须进 scene_assets_check ----')
    tmp = tempfile.mkdtemp(prefix='loom_r5_p22_')
    proj = os.path.join(tmp, 'proj')
    os.makedirs(proj)
    loom_assets.AssetContext.for_dir(proj, create=True)     # 空可用索引
    data = {'version': S.SCENE_VERSION, 'objects': [],
            'skybox': {'guid': 'cafebabe'}}
    ed = _ed(os.path.join(proj, 'scene.json'))
    _cap(lambda: S.scene_from_dict(ed, data, base_dir=proj))
    errs = S.asset_errors(ed)
    check('天空盒失败进 asset_errors', any(w == 'skybox' for w, _g, _r in errs), errs)
    r = _cmd('scene_assets_check', ed)
    res = r.get('result') or {}
    check('scene_assets_check ok=False + count>=1（旧行为: 假绿 ok:true）',
          res.get('ok') is False and res.get('count', 0) >= 1, res)


# ---------------------------------------------------------------- P2-③
def t_p2_3_cubemap_fingerprint():
    print('---- 轮5 P2-③: 六面图内容变更必须出声 ----')
    tmp = tempfile.mkdtemp(prefix='loom_r5_p23_')
    proj = os.path.join(tmp, 'proj')
    os.makedirs(proj)
    ctx = loom_assets.AssetContext.for_dir(proj, create=True)
    faces = six(os.path.join(tmp, 'sky'))
    cg, _c, _w = ctx.import_cubemap(faces, name='sky')
    e = ctx.entry(cg)
    fp = e.get('fingerprint') or {}
    check('指纹 size 是字节数（旧行为: 面数 6）', int(fp.get('size', 0)) > 6, fp.get('size'))
    check('条目带逐面指纹 face_stats', isinstance(e.get('face_stats'), dict)
          and len(e['face_stats']) == 6)
    # 替换其中一面（内容/大小都变）
    face0 = os.path.join(proj, e['src'].replace('/', os.sep), e['files'][0])
    _png(face0, (9, 9, 9, 255))
    p, _e, ok, why = ctx.resolve(cg)
    check('六面图内容变更 -> valid + reason 点名"内容已变更"',
          ok is True and '内容已变更' in str(why), why)


# ---------------------------------------------------------------- P2-④
def t_p2_4_migrate_gate():
    print('---- 轮5 P2-④: dry-run 新项目可预演 + 迁移产物带 min_engine_version ----')
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        'migrate_b1_r5', os.path.join(os.path.dirname(LOOM), 'tools',
                                      'migrate_scene_assets_v11.py'))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    tmp = tempfile.mkdtemp(prefix='loom_r5_p24_')
    proj = os.path.join(tmp, 'legacy_proj')
    os.makedirs(proj)
    alb = _png(os.path.join(proj, 'tex', 'a.png'))
    faces = six(os.path.join(proj, 'sky'))
    scene = {'version': 10, 'objects': [], 'materials': [
        {'id': 'M1', 'name': 'm', 'color': None, 'saturation': 1.0,
         'albedo': {'path': alb, 'name': 'a'}}],
        'skybox': {'paths': ['sky/%s.png' % n for n in FACES], 'name': 'sky'}}
    sp = os.path.join(proj, 'scene.json')
    S.save_json_atomic(sp, scene)
    rep = mod.migrate_scene(sp, dry_run=True)
    check('dry-run 新项目可预演（旧行为: 直接失败 changed=0）',
          rep['changed'] >= 2 and not rep['failures'], rep)
    check('dry-run 不写盘（无 Assets 目录）',
          not os.path.isdir(os.path.join(proj, 'Assets')))
    rep2 = mod.migrate_scene(sp)
    check('真跑: 迁移成功', rep2['changed'] >= 2 and not rep2['failures'], rep2)
    new = json.load(open(sp, encoding='utf-8'))
    check('迁移产物带 min_engine_version（D7 闸门生效）',
          new.get('min_engine_version') == S.ENGINE_VERSION, new.get('min_engine_version'))
    hp = os.path.join(tmp, 'future.json')
    S.save_json_atomic(hp, {'version': 11, 'min_engine_version': '9.9.9', 'objects': []})
    rep3 = mod.migrate_scene(hp)
    check('高版本场景 -> 记 failure 不抛（整批不中断）',
          bool(rep3['failures']) and '版本' in rep3['failures'][0], rep3['failures'])


# ---------------------------------------------------------------- P2-⑤
def t_p2_5_pack_hard_fail():
    print('---- 轮5 P2-⑤: 打包缺资产库必须硬失败 ----')
    data = {'objects': [],
            'skybox': {'guid': 's'},
            'materials': [{'albedo': {'guid': 'a'},
                           'normal_map': {'guid': 'n'},
                           'env_map': {'guid': 'e'}}]}
    check('scene_asset_refs 计数（1 skybox + 3 槽）',
          build_game.scene_asset_refs(data) == 4, build_game.scene_asset_refs(data))
    raised = False
    msg = ''
    try:
        build_game.require_assets_or_exit('/tmp/x.json', data, False)
    except SystemExit as e:
        raised = True
        msg = str(e)
    check('无资产库 + 有 guid 引用 -> SystemExit', raised and 'Assets/assets.json' in msg, msg)
    check('无托管引用 -> 不失败',
          build_game.require_assets_or_exit('/tmp/x.json', {'objects': []}, False) == 0)
    # 有资产且索引可用 -> 不失败（D-02: 校验已提到公共路径，必须用真实可用索引）
    btmp = tempfile.mkdtemp(prefix='loom_r5_p25_')
    bproj = os.path.join(btmp, 'proj')
    os.makedirs(bproj)
    loom_assets.AssetContext.for_dir(bproj, create=True)
    bscene = os.path.join(bproj, 's.json')
    S.save_json_atomic(bscene, data)
    check('有资产且索引可用 -> 不失败',
          build_game.require_assets_or_exit(bscene, data, True) == 4)
    # 资产夹在但索引坏了 -> 同样必须拦（包内仍是死 guid）
    cproj = os.path.join(btmp, 'broken')
    os.makedirs(os.path.join(cproj, 'Assets'), exist_ok=True)
    with open(os.path.join(cproj, 'Assets', 'assets.json'), 'w', encoding='utf-8') as f:
        f.write('{ broken')
    cscene = os.path.join(cproj, 's.json')
    S.save_json_atomic(cscene, data)
    raised2 = False
    try:
        build_game.require_assets_or_exit(cscene, data, True)
    except SystemExit:
        raised2 = True
    check('资产夹在但索引损坏 -> 仍拒绝出包', raised2)
    check('legacy path 引用不算托管（不误杀）',
          build_game.scene_asset_refs({'materials': [{'albedo': {'guid': 'a', 'path': 'x.png'}}]}) == 0)


# ---------------------------------------------------------------- P2-⑥
def t_p2_6_notice_visible():
    print('---- 轮5 P2-⑥: 资产问题对用户可见（notice + 编辑器 _notify） ----')
    tmp = tempfile.mkdtemp(prefix='loom_r5_p26_')
    proj = os.path.join(tmp, 'proj')
    os.makedirs(proj)
    loom_assets.AssetContext.for_dir(proj, create=True)
    data = {'version': S.SCENE_VERSION, 'objects': [],
            'skybox': {'guid': 'dead'},
            'materials': [{'id': 'M', 'name': 'm', 'color': None, 'saturation': 1.0,
                           'albedo': {'guid': 'dead2'}}]}
    ed = _ed(os.path.join(proj, 'scene.json'))
    _cap(lambda: S.scene_from_dict(ed, data, base_dir=proj))
    notice = S.asset_issue_notice(ed)
    check('notice 文本含"已保留"（告警 + 未改写）', notice and '已保留' in notice, notice)
    clean = _ed()
    check('干净场景 -> 无 notice', S.asset_issue_notice(clean) is None)
    # 编辑器保存路径: 必须调用 _notify（GUI 可见）
    captured = []
    ed2 = _ed(os.path.join(proj, 'scene.json'))
    _cap(lambda: S.scene_from_dict(ed2, data, base_dir=proj))
    ed2._notify = lambda msg, color=None: captured.append(msg)
    ed2._camera_dict = lambda: None
    ed2.mark_saved = lambda: None
    ed2.last_dir = None
    ed2.scene_name = 's'
    import editor as _edmod
    old_save = _edmod.save_last_dir
    _edmod.save_last_dir = lambda *a, **k: None
    try:
        ed2._save_scene(os.path.join(proj, 'saved.json'))
    finally:
        _edmod.save_last_dir = old_save
    check('编辑器保存 -> _notify 提示（旧行为: 只有 print）',
          any('资产' in str(m) for m in captured), captured)
    saved = json.load(open(os.path.join(proj, 'saved.json'), encoding='utf-8'))
    check('保存文件里引号仍在（保存与提示一致）',
          (saved.get('skybox') or {}).get('guid') == 'dead',
          saved.get('skybox'))




# ================================================================ 轮6 审核修复
# ---------------------------------------------------------------- D-01
def t_d01_new_scene_reset():
    print('---- 轮6 D-01: 新建场景不得复活上一场景的失效引用 ----')
    tmp = tempfile.mkdtemp(prefix='loom_r6_d01_')
    proj = os.path.join(tmp, 'proj')
    os.makedirs(proj)
    loom_assets.AssetContext.for_dir(proj, create=True)      # 空可用索引
    raw = {'version': S.SCENE_VERSION, 'objects': [],
           'skybox': {'guid': 'deadsky-old'},
           'materials': [{'id': 'M', 'name': 'm', 'color': None, 'saturation': 1.0,
                          'albedo': {'guid': 'deadtex-old'}}]}
    sp = os.path.join(proj, 'old.json')
    S.save_json_atomic(sp, raw)
    ed = _ed(sp)
    _cap(lambda: S.scene_from_dict(ed, raw, base_dir=proj))
    check('前置: 旧场景保留 2 条失效引用', S.asset_refs_kept(ed) == 2,
          (S.asset_refs_kept(ed), S.asset_errors(ed)))
    check('前置: 天空盒 valid=False 且 ref 在',
          getattr(ed, '_skybox_valid', None) is False
          and isinstance(getattr(ed, '_skybox_ref', None), dict))

    ed._new_scene()          # 真实入口（不是手工清字段）
    check('新建场景: 失效引用清零 / valid 回 True / ref 清空 / errors 清空',
          S.asset_refs_kept(ed) == 0
          and getattr(ed, '_skybox_valid', None) is True
          and getattr(ed, '_skybox_ref', None) is None
          and S.asset_errors(ed) == [],
          (S.asset_refs_kept(ed), getattr(ed, '_skybox_valid', None),
           getattr(ed, '_skybox_ref', None), S.asset_errors(ed)))
    check('新建场景: 不再谎报上一场景的资产问题', S.asset_issue_notice(ed) is None,
          S.asset_issue_notice(ed))
    d = S.scene_to_dict(ed, camera=None, base_dir=proj)
    sb = d.get('skybox') or {}
    check('新建场景保存: skybox 不得写回上一场景 deadsky-old',
          sb.get('guid') != 'deadsky-old', sb)
    check('新建场景保存: 是默认蓝天纯色', sb.get('solid_color') == list(S.DEFAULT_SKYBOX_COLOR), sb)
    check('新建场景保存: materials 已清空', not (d.get('materials') or []), d.get('materials'))


# ---------------------------------------------------------------- D-02
def t_d02_build_main_e2e():
    print('---- 轮6 D-02: 真实 build_game.main() 必须拦住"索引坏 + guid 引用" ----')
    tmp = tempfile.mkdtemp(prefix='loom_r6_d02_')
    fake_bin = os.path.join(tmp, 'bin')
    os.makedirs(fake_bin)
    for sub in ('core_components', 'ckernels', 'scripts', 'player_runtime'):
        os.makedirs(os.path.join(fake_bin, sub))
    rt = os.path.join(tmp, 'rt')
    os.makedirs(rt)
    with open(os.path.join(rt, 'MyGame.exe'), 'wb') as f:
        f.write(b'\0')
    scripts_dir = os.path.join(tmp, 'gs')
    os.makedirs(scripts_dir)
    guid_scene = {'version': S.SCENE_VERSION, 'objects': [],
                  'skybox': {'guid': 'a' * 32},
                  'materials': [{'id': 'M', 'name': 'm', 'albedo': {'guid': 'b' * 32},
                                 'env_map': {'guid': 'c' * 32}}]}
    path_scene = {'version': S.SCENE_VERSION, 'objects': [],
                  'skybox': {'solid_color': [1, 2, 3, 255]},
                  'materials': [{'id': 'M', 'name': 'm',
                                 'albedo': {'guid': None, 'path': 'tex/a.png'}}]}

    old_bin = build_game.BIN_DIR
    old_argv = list(sys.argv)
    build_game.BIN_DIR = fake_bin

    def _build(tag, scene, scene_dir=None):
        d = scene_dir or tmp
        sp = os.path.join(d, 'scene_%s.json' % tag)
        S.save_json_atomic(sp, scene)
        out = os.path.join(tmp, 'out_%s' % tag)
        sys.argv = ['build_game.py', '--name', 'T', '--scene', sp,
                    '--runtime', rt, '--output', out,
                    '--game-scripts', scripts_dir, '--force']
        err = None
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                build_game.main()
        except BaseException as e:      # noqa: BLE001 - 要区分 SystemExit 与正常返回
            err = e
        return err, out

    try:
        err, out = _build('noidx_guid', guid_scene)
        check('main(): 无资产库 + guid 引用 -> SystemExit', isinstance(err, SystemExit),
              (type(err).__name__, str(err)[:100]))
        check('main(): 失败先于 pack（无游戏包）',
              not os.path.isfile(os.path.join(out, '游戏包.lsc')))
        err2, out2 = _build('noidx_path', path_scene)
        check('main(): 只有 path/纯色 -> 正常出包（不误伤）',
              err2 is None and os.path.isfile(os.path.join(out2, '游戏包.lsc')),
              (err2, out2))
        # C) 资产夹在但索引坏 —— 轮6 的关键用例（旧实现只调 helper，真实 main 走不到）
        projc = os.path.join(tmp, 'projc')
        os.makedirs(os.path.join(projc, 'Assets'))
        with open(os.path.join(projc, 'Assets', 'assets.json'), 'w',
                  encoding='utf-8') as f:
            f.write('{ broken')
        errc, outc = _build('corrupt_idx', guid_scene, scene_dir=projc)
        check('E2E main(): 索引损坏 + guid 引用 -> 拒绝出包',
              isinstance(errc, SystemExit), (type(errc).__name__, str(errc)[:120]))
        check('E2E main(): 拒绝发生在 pack 前（不产出带坏索引的包）',
              not os.path.isfile(os.path.join(outc, '游戏包.lsc')))
        # D) 索引可用 + guid -> 正常，且发布夹带 Assets
        projd = os.path.join(tmp, 'projd')
        os.makedirs(projd)
        loom_assets.AssetContext.for_dir(projd, create=True)
        errd, outd = _build('ok_idx', guid_scene, scene_dir=projd)
        check('E2E main(): 索引可用 + guid -> 正常出包', errd is None,
              (errd, str(errd)[:100] if errd else ''))
        check('E2E main(): 发布夹带 Assets/assets.json',
              os.path.isfile(os.path.join(outd, 'Assets', 'assets.json')))
    finally:
        build_game.BIN_DIR = old_bin
        sys.argv = old_argv


# ---------------------------------------------------------------- D-04
def t_d04_index_merge():
    print('---- 轮6 D-04: 索引并发写按 guid 合并（不丢条目） ----')
    tmp = tempfile.mkdtemp(prefix='loom_r6_d04_')
    proj = os.path.join(tmp, 'proj')
    os.makedirs(proj)
    ctxA = loom_assets.AssetContext.for_dir(proj, create=True)
    pngA = _png(os.path.join(tmp, 'src', 'a.png'), (1, 1, 1, 255))
    pngB = _png(os.path.join(tmp, 'src', 'b.png'), (2, 2, 2, 255))
    ga, _c, why = ctxA.import_texture(pngA, name='a')
    check('前置: A 已落盘', bool(ga), why)
    # 另一写者的**旧快照**（模拟另一个进程早先加载，看不到 A）
    ctxB = loom_assets.AssetContext.open_root(proj)
    ctxB.index = json.loads(json.dumps(ctxB.index))
    ctxB.index.get('assets', {}).pop(ga, None)
    gb, _c2, why2 = ctxB.import_texture(pngB, name='b')
    check('前置: B 导入成功', bool(gb), why2)
    idx = (loom_assets.load_index(proj) or [None])[0] or {'assets': {}}
    check('并发写: 两条 guid 都在（旧行为: 后写者覆盖丢 A）',
          ga in idx['assets'] and gb in idx['assets'], list(idx['assets']))
    check('并发写: 两个正文都在',
          loom_assets.AssetContext.open_root(proj)._entry_body_ok(
              idx['assets'][ga], 'texture')
          and loom_assets.AssetContext.open_root(proj)._entry_body_ok(
              idx['assets'][gb], 'texture'))
    # 合并也不得把坏条目复活（自愈语义）
    with open(loom_assets.index_path(proj), 'r', encoding='utf-8') as f:
        good = json.load(f)
    good['assets']['bad_entry'] = {'type': 'nonsense'}
    with open(loom_assets.index_path(proj), 'w', encoding='utf-8') as f:
        json.dump(good, f)
    loom_assets._CACHE.clear()
    ctxC = loom_assets.AssetContext.open_root(proj)     # 载入时剔除坏条目
    ctxC.import_texture(pngA, name='a2')                # 触发一次写盘（合并）
    idx2 = loom_assets.load_index(proj)[0]
    check('合并不会复活坏条目（自愈保持）', 'bad_entry' not in idx2['assets'],
          list(idx2['assets']))


# ---------------------------------------------------------------- D-05
def t_d05_reimport_repair():
    print('---- 轮6 D-05: reimport 必须修复被删正文 ----')
    tmp = tempfile.mkdtemp(prefix='loom_r6_d05_')
    proj = os.path.join(tmp, 'proj')
    os.makedirs(proj)
    ctx = loom_assets.AssetContext.for_dir(proj, create=True)
    png = _png(os.path.join(tmp, 'src', 't.png'))
    g, _c, why = ctx.import_texture(png, name='t')
    e = ctx.entry(g) or {}
    body = os.path.join(proj, str(e.get('src', '')).replace('/', os.sep))
    os.remove(body)
    check('前置: 正文缺失 -> resolve 失效',
          ctx.resolve(g)[2] is False)
    g2, created2, why2 = ctx.import_texture(png, name='t')
    check('贴图 reimport: 同 guid + created=True（修复）+ reason 点名',
          g2 == g and created2 is True and '重新落盘' in str(why2 or ''),
          (g2, created2, why2))
    check('贴图 reimport 后 resolve 可用', ctx.resolve(g)[2] is True,
          ctx.resolve(g)[3])
    # 六面图
    faces = six(os.path.join(tmp, 'sky'))
    cg, _c3, why3 = ctx.import_cubemap(faces, name='sky')
    ce = ctx.entry(cg) or {}
    face0 = os.path.join(proj, str(ce.get('src', '')).replace('/', os.sep),
                         ce['files'][0])
    os.remove(face0)
    check('前置: 六面图缺一面 -> 失效', ctx.resolve(cg)[2] is False)
    cg2, created4, why4 = ctx.import_cubemap(faces, name='sky')
    check('六面图 reimport: 同 guid + created=True + reason',
          cg2 == cg and created4 is True and '重新落盘' in str(why4 or ''),
          (cg2, created4, why4))
    check('六面图 reimport 后 resolve 可用', ctx.resolve(cg)[2] is True,
          ctx.resolve(cg)[3])
    # 只读模式不得写盘
    os.remove(body)
    ro = loom_assets.AssetContext.for_dir(proj, readonly=True)
    gr, createdr, whyr = ro.import_texture(png, name='t')
    check('只读模式: 不写盘但明确说原因',
          createdr is False and '只读' in str(whyr or '') and not os.path.isfile(body),
          (gr, createdr, whyr))


# ---------------------------------------------------------------- D-06
def t_d06_reserved_long_names():
    print('---- 轮6 D-06: 保留设备名/超长名不得抛异常 ----')
    tmp = tempfile.mkdtemp(prefix='loom_r6_d06_')
    proj = os.path.join(tmp, 'proj')
    os.makedirs(proj)
    ctx = loom_assets.AssetContext.for_dir(proj, create=True)
    cases = [('LPT1', (10, 10, 10, 255)), ('LPT1.png', (11, 11, 11, 255)),
             ('CON', (12, 12, 12, 255)), ('NUL', (13, 13, 13, 255)),
             ('a' * 300 + '.png', (14, 14, 14, 255))]
    for i, (nm, rgba) in enumerate(cases):
        png = _png(os.path.join(tmp, 'src', 'r%d.png' % i), rgba)
        err = None
        try:
            g, created, why = ctx.import_texture(png, name=nm)
        except BaseException as e:      # noqa: BLE001 - 本用例就是证明"不抛"
            err, g, why = e, None, None
        check('name=%r 不抛异常' % (nm[:20],), err is None, err)
        if g:
            src = (ctx.entry(g) or {}).get('src', '')
            check('name=%r 落在 Assets/Textures 下' % (nm[:20],),
                  str(src).startswith('Assets/Textures/'), src)
            check('name=%r 文件名未超 255' % (nm[:20],),
                  len(os.path.basename(str(src))) <= 255, len(os.path.basename(str(src))))
    # 六面图同样不抛
    err2 = None
    try:
        faces = six(os.path.join(tmp, 'sky'))
        cg, _c, why = ctx.import_cubemap(faces, name='LPT1')
    except BaseException as e:          # noqa: BLE001
        err2 = e
    check('六面图 name=LPT1 不抛异常', err2 is None, err2)




# ================================================================ F-02 性能/语义
# ---------------------------------------------------------------- ① 索引校验惰性化
def t_f02_index_perf():
    print('---- F-02 ①: 索引校验惰性化（10k 条 ≤500ms，旧 8190ms） ----')
    tmp = tempfile.mkdtemp(prefix='loom_f02_perf_')
    proj = os.path.join(tmp, 'proj')
    os.makedirs(os.path.join(proj, 'Assets'))
    assets = {}
    for i in range(10000):
        assets['%032x' % i] = {'type': 'texture',
                               'src': 'Assets/Textures/t%d.png' % i,
                               'name': 't', 'import': {},
                               'fingerprint': {'sha256': 'x' * 64, 'size': 1,
                                               'mtime': 1.0}}
    with open(os.path.join(proj, 'Assets', 'assets.json'), 'w',
              encoding='utf-8') as f:
        json.dump({'schema': 1, 'assets': assets}, f)
    loom_assets._CACHE.clear()
    t0 = time.perf_counter()
    idx, ok, why = loom_assets.load_index(proj)
    dt = (time.perf_counter() - t0) * 1000.0
    check('10k 条加载+校验 ≤500ms', ok and idx is not None
          and len(idx.get('assets') or {}) == 10000 and dt <= 500,
          '%.1fms' % dt)
    t0 = time.perf_counter()
    loom_assets.load_index(proj)          # 二次走快照缓存（mtime/size 未变）
    dt2 = (time.perf_counter() - t0) * 1000.0
    check('二次读取命中快照缓存 ≤50ms', dt2 <= 50, '%.1fms' % dt2)
    # 校验本身不再做 realpath：越界条目仍被剔除（语义不变）
    bad = {'schema': 1, 'assets': {
        'a' * 32: {'type': 'texture', 'src': '../escape.png'}}}
    ok2, warns2 = loom_assets.validate_index(bad, proj)
    check('字符串判定仍拒绝越界 src', ok2 and not bad['assets'] and warns2, warns2)


# ---------------------------------------------------------------- ② delta 生效
def t_f02_delta_effective():
    print('---- F-02 ②: 用户层 delta 的 import 覆盖必须生效（含写入方） ----')
    tmp = tempfile.mkdtemp(prefix='loom_f02_delta_')
    proj = os.path.join(tmp, 'proj')
    os.makedirs(proj)
    ctx = loom_assets.AssetContext.for_dir(proj, create=True)
    png = _png(os.path.join(tmp, 'src', 'd.png'))
    g, _c, why = ctx.import_texture(png, name='d',
                                    import_settings={'wrap': 'repeat'})
    check('前置: 贴图导入', bool(g), why)
    ok, why2 = loom_assets.write_user_delta(
        proj, g, import_settings={'wrap': 'clamp', 'mipmaps': False})
    check('用户层 delta 写入成功', ok, why2)
    check('用户在 %LOCALAPPDATA% 的 delta 文件已落盘',
          os.path.isfile(loom_assets.user_index_path(proj)))
    ctx2 = loom_assets.AssetContext.open_root(proj)
    s = ctx2._import_settings(ctx2.entry(g), None, g)
    check('delta 的 import 生效（wrap=clamp / mipmaps=False）',
          s.get('wrap') == 'clamp' and s.get('mipmaps') is False, s)
    tex, ok2, _w2 = ctx2.texture(g)
    check('Texture 实际拿到 delta 设置',
          tex is not None and tex.wrap == 'clamp' and tex.mipmaps is False,
          (getattr(tex, 'wrap', None), getattr(tex, 'mipmaps', None)))
    check('场景内联覆盖优先级最高（> delta）',
          ctx2._import_settings(ctx2.entry(g), {'wrap': 'mirror'}, g).get('wrap')
          == 'mirror')
    ed = _ed(os.path.join(proj, 'scene.json'))
    r = _cmd('asset_user_override', ed,
             {'guid': g, 'wrap': 'clamp', 'mipmaps': 'false', 'max_size': 64})
    check('asset_user_override 可写（旧: 全仓 0 writer）', r.get('ok') is True,
          r.get('error'))
    r2 = _cmd('asset_get', ed, {'guid': g})
    eff = (r2.get('result') or {}).get('effective_import') or {}
    check('asset_get.effective_import 反映 delta',
          eff.get('wrap') == 'clamp' and eff.get('max_size') == 64, eff)
    r3 = _cmd('asset_user_override', ed, {'guid': g, 'clear': True})
    check('clear 后 delta 清空', r3.get('ok') is True
          and not loom_assets.load_user_delta(proj), r3)
    check('清理后设置回项目默认',
          loom_assets.AssetContext.open_root(proj)._import_settings(
              loom_assets.AssetContext.open_root(proj).entry(g), None, g
          ).get('wrap') == 'repeat')


# ---------------------------------------------------------------- ③ 无项目根拒绝
def t_f02_no_root_save():
    print('---- F-02 ③: 无项目根时拒绝写索引（不得落 CWD） ----')
    cwd_assets = os.path.join(os.getcwd(), 'Assets')
    existed = os.path.isdir(cwd_assets)
    p, why = loom_assets.save_index('', {'schema': 1, 'assets': {}})
    check('save_index("") -> 拒绝 + reason 点名项目根',
          p is None and '项目根' in str(why), (p, why))
    check('未在 CWD 创建 Assets/', os.path.isdir(cwd_assets) == existed)
    check('AssetContext.for_dir("", create=True) -> None',
          loom_assets.AssetContext.for_dir('', create=True) is None)
    ed = _ed(None)                      # 未保存场景（_scene_dir() == CWD）
    check('编辑器未保存场景 -> create 上下文为 None',
          ed._asset_context(create=True) is None)
    check('编辑器未保存场景 -> 未在 CWD 建 Assets',
          os.path.isdir(cwd_assets) == existed)
    check('editor.asset_import 仍明确拒绝（先保存场景）',
          ed.asset_import(path=None, kind='texture')[0] is None)


# ---------------------------------------------------------------- ④ 错误记录 O(1)+上限
def t_f02_error_cap():
    print('---- F-02 ④: record_asset_error O(1) + 200 条上限 ----')
    ed = _ed()
    t0 = time.perf_counter()
    for i in range(5000):
        S.record_asset_error(ed, 'materials.albedo', 'g%d' % i, 'reason %d' % i)
    dt = (time.perf_counter() - t0) * 1000.0
    check('5000 条唯一错误 ≤500ms（旧 387ms 且无上限）', dt <= 500, '%.1fms' % dt)
    check('列表截断到上限 200',
          len(S.asset_errors(ed)) == S.ASSET_ERROR_LIMIT,
          len(S.asset_errors(ed)))
    check('总数含溢出计数 = 5000', S.asset_error_count(ed) == 5000,
          S.asset_error_count(ed))
    n = len(S.asset_errors(ed))
    for i in range(100):
        S.record_asset_error(ed, 'x', 'dup', 'same')
    check('重复项不增长（set 去重）', len(S.asset_errors(ed)) == n)
    _cnt = S.asset_error_count(ed)
    check('notice 使用总数（不只列表长度）',
          str(_cnt) in (S.asset_issue_notice(ed) or '') and _cnt >= 5000,
          (_cnt, S.asset_issue_notice(ed)))
    S.reset_asset_errors(ed)
    check('reset 后清空（含溢出计数/去重键）',
          S.asset_errors(ed) == [] and S.asset_error_count(ed) == 0)


def main():
    tmp, proj, g1, gc = t_import()
    proj2, data = t_roundtrip(tmp, proj, g1, gc)
    t_failure_visible(tmp, proj2, data)
    t_index_guard()
    t_migrate()
    t_pack(tmp, proj2, data)
    t_commands(tmp, proj2)
    t_p1_1_preserve_refs()
    t_p1_2_index_partial()
    t_p1_3_delta_guard()
    t_p2_1_name_traversal()
    t_p2_2_skybox_in_check()
    t_p2_3_cubemap_fingerprint()
    t_p2_4_migrate_gate()
    t_p2_5_pack_hard_fail()
    t_p2_6_notice_visible()
    t_d01_new_scene_reset()
    t_d02_build_main_e2e()
    t_d04_index_merge()
    t_d05_reimport_repair()
    t_d06_reserved_long_names()
    t_f02_index_perf()
    t_f02_delta_effective()
    t_f02_no_root_save()
    t_f02_error_cap()
    print('\n总结果: %s' % ('ALL PASS' if ok else 'FAIL'))
    sys.exit(0 if ok else 1)


if __name__ == '__main__':
    main()
