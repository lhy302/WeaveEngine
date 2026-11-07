# -*- coding: utf-8 -*-

"""test_texture.py — M36 贴图体系回归 (2026-10-14)。

覆盖: Texture 资产 (from_rgba/from_file/white/ensure_gl) / mesh UV / Material albedo 槽 /
桶键含贴图 / 着色器采样 / set_texture 命令 / 材质序列化往返。
脚本式: 末尾 sys.exit(0 if ok else 1)。
"""

# 2026-11-06 P-02 修复: Windows 控制台默认 GBK, 末尾 print 的 ✅/❌/≤ 等字符会抛
# UnicodeEncodeError, 让"测试通过"被记录成 exit=1 的假失败 (48/51 曾被误判)。
# 统一把 stdout/stderr 切到 UTF-8(replace), 失败信号重新只由断言决定。
import sys as _sys_utf8
try:
    _sys_utf8.stdout.reconfigure(encoding='utf-8', errors='replace')
    _sys_utf8.stderr.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

# 2026-11-06 失败退出码闸门 (复核 A 指出: 54 个测试里仅 18 个有 sys.exit(1),
# 其余 FAIL 也 exit 0 -> run_all 假绿, 失败被静默吞掉)。
# 做法: 包一层 stdout, 出现以 "FAIL" 开头的行就在进程退出时把状态码改成 1。
# 只在真出现 FAIL 时才改码, 全 PASS 的测试行为完全不变。
import atexit as _atexit_gate
import os as _os_gate
import sys as _sys_gate


class _FailGateStream:
    def __init__(self, stream):
        self._stream = stream
        self.failed = False

    def write(self, text):
        if isinstance(text, str) and (text.startswith("FAIL") or "\nFAIL" in text):
            self.failed = True
        return self._stream.write(text)

    def __getattr__(self, name):
        return getattr(self._stream, name)


_fail_gate = _FailGateStream(_sys_gate.stdout)
_sys_gate.stdout = _fail_gate


@_atexit_gate.register
def _enforce_fail_exit_code():
    if not _fail_gate.failed:
        return
    try:
        _sys_gate.stdout.flush()
        _sys_gate.stderr.flush()
    except Exception:
        pass
    _os_gate._exit(1)


import os
import sys
import tempfile

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)
os.chdir(BASE)
sys.argv[0] = os.path.join(BASE, 'Loom.py')

import numpy as np

_fails = []


def check(name, cond, detail=''):
    print("%s %s  %s" % ("PASS" if cond else "FAIL", name, detail))
    if not cond:
        _fails.append(name)


# ---- 1. Texture 资产 ----
from loom_texture import Texture

t1 = Texture.white()
check("white 纹理 1x1", t1.width == 1 and t1.height == 1, "%dx%d" % (t1.width, t1.height))

arr = np.zeros((4, 8, 4), dtype=np.uint8)
arr[:, :, 0] = 255
t2 = Texture.from_rgba(8, 4, arr, name='红')
check("from_rgba 尺寸", t2.width == 8 and t2.height == 4, "%dx%d" % (t2.width, t2.height))
check("from_rgba guid 稳定", bool(t2.guid) and t2.guid == t2.guid, t2.guid[:8])

# 尺寸不符 -> 报错
try:
    Texture.from_rgba(4, 4, np.zeros((2, 2, 4), dtype=np.uint8))
    check("from_rgba 尺寸不符报错", False, "未报错")
except ValueError:
    check("from_rgba 尺寸不符报错", True)

# 文件加载
import pygame
pygame.init()
surf = pygame.Surface((16, 16)); surf.fill((10, 200, 30))
_tmpf = os.path.join(tempfile.gettempdir(), '_loom_tex_test.png')
pygame.image.save(surf, _tmpf)
t3 = Texture.from_file(_tmpf)
check("from_file 加载", t3.width == 16 and t3.height == 16, "%dx%d" % (t3.width, t3.height))
px = t3._rgba[8, 8]
check("from_file 像素正确", px[0] == 10 and px[1] == 200 and px[2] == 30, str(list(px)))
os.remove(_tmpf)
try:
    Texture.from_file(os.path.join(tempfile.gettempdir(), '_no_such_xyz.png'))
    check("from_file 缺文件报错", False, "未报错")
except ValueError:
    check("from_file 缺文件报错", True)

# ---- 2. mesh UV ----
from mesh import create_cube, create_sphere, create_plane

c = create_cube(1.0)
check("cube 24 顶点 (每面独立 UV)", len(c.vertices) == 24, "v=%d" % len(c.vertices))
check("cube UV 数对齐", c.uvs is not None and len(c.uvs) == 24, "")
check("cube 面数 12", len(c.faces) == 12, "f=%d" % len(c.faces))
check("cube UV 角点", c.uvs[0] == (0.0, 0.0) and c.uvs[2] == (1.0, 1.0), str(c.uvs[:4]))
# 法线朝外 (极值不变)
xs = [v[0] for v in c.vertices]
check("cube AABB 极值不变", min(xs) == -0.5 and max(xs) == 0.5, "%s..%s" % (min(xs), max(xs)))

s = create_sphere(0.5, 8, 12)
check("sphere UV 数对齐", s.uvs is not None and len(s.uvs) == len(s.vertices),
      "%d/%d" % (len(s.uvs), len(s.vertices)))
p = create_plane()
check("plane UV 数对齐", p.uvs is not None and len(p.uvs) == 4, str(p.uvs))

# ---- 3. Material albedo / normal_map 槽 ----
from loom_material import Material

mat = Material(color='#FF0000')
check("材质默认无贴图", mat.albedo is None and mat._tex_guid == '', "")
mat.albedo = t2
check("材质设贴图", mat.albedo is t2 and mat._tex_guid == t2.guid, mat._tex_guid[:8])
mat.albedo = None
check("材质清贴图", mat.albedo is None and mat._tex_guid == '', "")
mat.normal_map = t2
check("材质设法线贴图", mat.normal_map is t2 and mat._nrm_guid == t2.guid, mat._nrm_guid[:8])
mat.normal_map = None
check("材质清法线贴图", mat.normal_map is None and mat._nrm_guid == '', "")

# ---- 4. 桶键含贴图 ----
import moderngl
from mesh import create_cube as _cc
import engine as E

ctx = moderngl.create_standalone_context()
import editor as editor_mod
# 2026-11-06: 测试不得改动仓库内的 保存/ 目录 —— EditorApp.__init__ 首次运行会把
# 保存/ 迁移为 Projects/ (线上正确行为), 但测试跑一次就把受版本控制的数据搬走。
# 把两个目录常量重定向到临时目录, 迁移逻辑面对空目录 = 零副作用。
import tempfile as _tf_save
_SAVE_ROOT = _tf_save.mkdtemp(prefix="loom_test_save_")
editor_mod.DEFAULT_SAVE_DIR = os.path.join(_SAVE_ROOT, "Projects")
editor_mod._LEGACY_SAVE_DIR = os.path.join(_SAVE_ROOT, "保存")
ed = editor_mod.EditorApp(320, 240, ctx=ctx)
ed._external_fb = ctx.detect_framebuffer()
try:
    _g = ed.view.gui.render
    ed.view.gui.render = lambda *a, **k: _g(target=ed._external_fb)
except Exception:
    pass

ed.load_scene(os.path.join(BASE, '保存', '压力测试', '压力_空场景.json'))
mm = ed.add_model(_cc(1.0), E.Point3D(0, 0, 0), E.Point3D(0, 0, 0), name='贴图块')
mat_t = Material(name='贴图材质', albedo=t2)
mm.renderer.material = mat_t
k = ed._mesh_key(mm)
check("桶键含贴图 guid", len(k) == 7 and k[3] == t2.guid, "k[3]=%s" % (k[3][:8] if len(k) > 3 else None))
check("桶键含法线贴图 guid", len(k) == 7 and k[4] == '', "k[4]=%r" % (k[4] if len(k) > 4 else None))
# 无贴图 -> guid 空串
mm2 = ed.add_model(_cc(1.0), E.Point3D(2, 0, 0), E.Point3D(0, 0, 0), name='纯色块')
k2 = ed._mesh_key(mm2)
check("无贴图桶键 guid 空", len(k2) == 7 and k2[3] == '' and k2[4] == '',
      "k2[3:5]=%r" % (k2[3:5],))

# ---- 5. 渲染不崩 ----
for _ in range(5):
    ed.render(1 / 60.0)
alb = getattr(ed, '_bucket_albedo', {})
check("渲染后 albedo 表", len(alb) >= 1 and any(v is not None for v in alb.values()),
      "非None=%d" % sum(1 for v in alb.values() if v is not None))
check("白纹理已建", ed._white_tex is not None, "")

# ---- 6. set_texture 命令 ----
import agent_commands as ac
surf2 = pygame.Surface((8, 8)); surf2.fill((5, 5, 250))
tf = os.path.join(tempfile.gettempdir(), '_loom_cmd_tex.png')
pygame.image.save(surf2, tf)
class _Win:
    editor = ed
r = ac.dispatch('set_texture', {'name': '贴图块', 'path': tf}, _Win())
check("set_texture 命令成功", r.get('ok') is True, str(r.get('result')))
check("set_texture 挂上贴图", mm.renderer.material.albedo is not None, "")
r2 = ac.dispatch('set_texture', {'name': '贴图块', 'path': ''}, _Win())
check("set_texture 清除", r2.get('ok') is True and mm.renderer.material.albedo is None, "")
r3 = ac.dispatch('set_texture', {'name': '贴图块', 'path': '/no/such/file.png'}, _Win())
check("set_texture 错误容错", r3.get('ok') is False, "")
os.remove(tf)

# ---- 6b. LOD 按距离切换 ----
from mesh import create_sphere as _cs
hi_m = _cs(0.5, 16, 24)
lo_m = _cs(0.5, 6, 8)
lod_m = ed.add_model(hi_m, E.Point3D(0, 0, 0), E.Point3D(0, 0, 0), name='LOD球')
lod_m.renderer.lod_levels = [(5.0, hi_m), (20.0, lo_m)]
ed.orbit_mode = True
ed.camera_target = (0.0, 0.0, 0.0)

def _settle(dist):
    ed.camera_distance = dist
    for _ in range(6):
        ed.render(1 / 60.0)
    return lod_m.renderer.mesh

check("LOD 近距->高精度", _settle(3.0) is hi_m, "")
check("LOD 中距->低精度", _settle(15.0) is lo_m, "")
check("LOD 回近距->高精度", _settle(3.0) is hi_m, "")
check("无 LOD 物体零配置", ed.add_model(hi_m, E.Point3D(9, 0, 0),
      E.Point3D(0, 0, 0), name='普通').renderer.lod_levels is None, "")

# ---- 6c. 导入设置 (对标 Unity Import Settings) ----
t_imp = Texture.from_rgba(32, 32, np.zeros((32, 32, 4), dtype=np.uint8),
                          wrap='clamp', filter_mode='point', aniso=4.0, max_size=16)
check("导入设置字段", t_imp.wrap == 'clamp' and t_imp.filter_mode == 'point'
      and t_imp.aniso == 4.0 and t_imp.max_size == 16, "")
ctx_i = moderngl.create_standalone_context()
gi = t_imp.ensure_gl(ctx_i)
check("wrap=clamp -> repeat_x False", gi.repeat_x is False, str(gi.repeat_x))
check("filter=point -> NEAREST", gi.filter[0] in (9984, 9986), str(gi.filter))
check("aniso 生效", abs(gi.anisotropy - 4.0) < 1e-6, str(gi.anisotropy))
t_rep = Texture.from_rgba(32, 32, np.zeros((32, 32, 4), dtype=np.uint8), wrap='repeat')
check("wrap=repeat -> repeat_x True", t_rep.ensure_gl(ctx_i).repeat_x is True, "")
ctx_i.release()
# max_size 缩放
from mesh import create_plane as _cp2
import pygame as _pg
_pg.init()
_surf = _pg.Surface((128, 64)); _surf.fill((9, 9, 9))
_pf = os.path.join(tempfile.gettempdir(), '_loom_maxsz.png')
_pg.image.save(_surf, _pf)
_tmax = Texture.from_file(_pf, max_size=32)
check("max_size 等比缩放", _tmax.width == 32 and _tmax.height == 16,
      "%dx%d" % (_tmax.width, _tmax.height))
os.remove(_pf)

# ---- 6d. 纹理压缩 (对标 Unity Compression) ----
ctx_c = moderngl.create_standalone_context()
_carr = np.zeros((32, 32, 4), dtype=np.uint8)
_carr[:, :, 0] = 200; _carr[:, :, 1] = 100; _carr[:, :, 3] = 255
for _fmt in ('none', 'rgb24', 'rgb565', 'rgba4444', 'rgb5a1'):
    _t = Texture.from_rgba(32, 32, _carr, compression=_fmt)
    _g = _t.ensure_gl(ctx_c)
    check("压缩格式 %s 可用" % _fmt, _g is not None, "components=%d" % _g.components)
check("压缩位深表", Texture.COMPRESSION_FORMATS['rgb565'][2] == 16
      and Texture.COMPRESSION_FORMATS['none'][2] == 32, "")
_tbogus = Texture.from_rgba(8, 8, np.zeros((8, 8, 4), dtype=np.uint8),
                            compression='bogus')
check("无效压缩回退 none", _tbogus.compression == 'none', _tbogus.compression)
ctx_c.release()

# ---- 6e. PBR (对标 Unity Standard Shader) ----
_m_pbr = Material(name='PBR材质')
check("PBR 默认关", _m_pbr.pbr is False, "")
check("PBR 默认金属/粗糙", _m_pbr.metallic == 0.0 and _m_pbr.roughness == 0.5,
      "%.2f/%.2f" % (_m_pbr.metallic, _m_pbr.roughness))
_m_pbr.metallic = 0.9; _m_pbr.roughness = 0.2; _m_pbr.pbr = True
check("PBR 设值", _m_pbr.metallic == 0.9 and _m_pbr.roughness == 0.2 and _m_pbr.pbr, "")
_m_pbr.metallic = 5.0
check("PBR 金属度钳制", _m_pbr.metallic == 1.0, "%.2f" % _m_pbr.metallic)
# 命令
_pbr_obj = ed.add_model(_cc(1.0), E.Point3D(7, 0, 0), E.Point3D(0, 0, 0), name='PBR对象')
_r_pbr = ac.dispatch('set_pbr', {'name': 'PBR对象', 'metallic': 0.8,
                                 'smoothness': 0.7}, _Win())
check("set_pbr 命令", _r_pbr.get('ok') is True
      and abs(_pbr_obj.renderer.material.roughness - 0.3) < 1e-6,
      str(_r_pbr.get('result')))
# 桶键含 PBR
# 2026-11-06 契约同步: 桶键已从 6 元组扩到 7 元组
#   base(3) + tex_guid + nrm_guid + pbr(3元组) + env_guid
# (M36 PBR 参数 / 天空盒 env 先后入键, 见 loom_model_gpu._mesh_key 文档)。
# 原断言写死 len==6 且 pbr 在末位, 已随契约演化过期。
_kp = ed._mesh_key(_pbr_obj)
check("桶键含 PBR (metallic/roughness/pbr 三元组)",
      len(_kp) == 7 and isinstance(_kp[-2], tuple)
      and _kp[-2] == (0.8, 0.3, 1), "len=%d key=%r" % (len(_kp), _kp))
# 序列化
import sceneio as _sio_pbr
_dp = _sio_pbr._emit_material(_pbr_obj.renderer.material)
check("序列化含 PBR", _dp.get('metallic') == 0.8 and _dp.get('pbr') is True, str(_dp.get('metallic')))

# ---- 7. 材质序列化往返 ----
import sceneio
mat.albedo = t2
d = sceneio._emit_material(mat)
check("序列化含 albedo", isinstance(d.get('albedo'), dict) and d['albedo']['guid'] == t2.guid,
      str(d.get('albedo')))
# 无贴图材质不写 albedo 键
d2 = sceneio._emit_material(Material(color='#00FF00'))
check("无贴图不写 albedo 键", 'albedo' not in d2, str(d2.keys()))

ed._stop_parallel()
pygame.quit()
print("")
if _fails:
    print("有 FAIL: %s" % _fails)
    sys.exit(1)
print("ALL PASS")
sys.exit(0)
