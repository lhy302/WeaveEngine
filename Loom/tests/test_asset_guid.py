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
import io
import json
import os
import struct
import sys
import tempfile
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
    check('越界 src -> 索引被拒 + reason 点名（越界/相对路径）',
          idx is None and not good and ('越界' in str(why) or '相对路径' in str(why)), why)
    check('越界项目 -> AssetContext.for_dir 返回 None（回旧路径模式）',
          loom_assets.AssetContext.for_dir(tmp) is None)

    with open(p, 'w', encoding='utf-8') as f:
        f.write('{ 坏 json')
    idx2, good2, why2 = loom_assets.load_index(tmp)
    check('损坏索引不抛、给 reason', idx2 is None and not good2 and '损坏' in str(why2), why2)
    check('find_project_root 不误认引擎 assets/（大小写）',
          loom_assets.find_project_root(LOOM) is None)


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


def main():
    tmp, proj, g1, gc = t_import()
    proj2, data = t_roundtrip(tmp, proj, g1, gc)
    t_failure_visible(tmp, proj2, data)
    t_index_guard()
    t_migrate()
    t_pack(tmp, proj2, data)
    t_commands(tmp, proj2)
    print('\n总结果: %s' % ('ALL PASS' if ok else 'FAIL'))
    sys.exit(0 if ok else 1)


if __name__ == '__main__':
    main()
