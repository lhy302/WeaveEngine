# -*- coding: utf-8 -*-
"""test_vk_material_tex_settings.py — 同一材质 GL vs VK 的贴图导入设置必须一致.

scan_05 P-03 ([P1 回归]): scene_driver.build_materials 只给 Texture.from_file
传了 path/name/guid, 其余六项 (mipmaps/wrap/filter_mode/aniso/max_size/
compression) 全取默认值 —— 同一份场景, GL 是 64x64/1 级, Vk 是 256x256/9 级,
采样方式也不同。本测试锁: 同字段输入 -> 两后端 Texture 的尺寸/mip/采样设置
完全一致 (取值列表以 sceneio._apply_materials 为准, 不另立第二份)。
"""
import sys as _sys_utf8
try:
    _sys_utf8.stdout.reconfigure(encoding='utf-8', errors='replace')
    _sys_utf8.stderr.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

# 失败退出码闸门: 出现以 "FAIL" 开头的行就在进程退出时把状态码改成 1
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


import math
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
os.environ.setdefault('LOOM_NO_PARALLEL', '1')
os.environ.setdefault('LOOM_NO_SAVE_MIGRATE', '1')

_fails = []


def check(name, cond, detail=""):
    print(("PASS " if cond else "FAIL ") + name + ("  " + str(detail) if detail else ""))
    if not cond:
        _fails.append(name)

import sceneio
import scene_driver as SD


def _make_png(path, size=256):
    import pygame
    pygame.init()
    surf = pygame.Surface((size, size), pygame.SRCALPHA)
    for x in range(0, size, 8):          # 加点结构, 便于肉眼/工具核对
        for y in range(0, size, 8):
            surf.set_at((x, y), (255, 255, 255, 255))
    pygame.image.save(surf, path)


def _fake_gl_engine():
    """sceneio._apply_materials 需要的引擎面 (materials 列表 + add_material)."""
    from loom_material import Material

    class _Eng:
        def __init__(self):
            self.materials = []

        def add_material(self, color=None, saturation=1.0, name=None, guid=None):
            m = Material(name=name, color=color, saturation=saturation)
            if guid:
                m.guid = guid
            self.materials.append(m)
            return m

    return _Eng()


def _gl_material(matd):
    eng = _fake_gl_engine()
    sceneio._apply_materials(eng, [matd])
    return eng.materials[0]


def _vk_material(matd):
    data = {"version": 10, "materials": [matd], "objects": [], "lights": []}
    return SD.build_materials(data)[0]


def _upload_levels(tex):
    """vk_renderer 上传 mip 级数的同款算法 (mipmaps 关 -> 只有 1 级)."""
    if not getattr(tex, 'mipmaps', False):
        return 1
    return 1 + int(math.log2(max(tex.width, tex.height)))


def _sig(tex):
    return (tex.width, tex.height, bool(tex.mipmaps), _upload_levels(tex),
            tex.wrap, tex.filter_mode, float(tex.aniso), int(tex.max_size),
            getattr(tex, 'compression', 'none'))


def t_import_settings_forwarded(png):
    """非默认导入设置必须原样转发 (scan_05 实测: max_size=128/mipmaps=False)."""
    matd = {"id": "m1", "name": "材质A", "color": "#c8783c", "saturation": 1.0,
            "pbr": True,
            "albedo": {"path": png, "name": "a", "guid": "g-albedo",
                       "max_size": 64, "mipmaps": False, "wrap": "clamp",
                       "filter_mode": "point", "aniso": 4.0,
                       "compression": "rgb24"}}
    gl = _gl_material(matd).albedo
    vk = _vk_material(matd).albedo
    print("  GL:", _sig(gl))
    print("  VK:", _sig(vk))
    check("非默认导入设置: VK 与 GL 完全一致", _sig(vk) == _sig(gl), _sig(vk))
    check("max_size=64 生效 (256x256 -> 64x64)", vk.width == 64 and vk.height == 64,
          (vk.width, vk.height))
    check("mipmaps=False -> 上传 1 级", _upload_levels(vk) == 1, _upload_levels(vk))


def t_default_import_settings(png):
    """缺导入设置键 -> 两端都走同一默认值 (mipmaps=True / max_size=0 / repeat)."""
    matd = {"id": "m2", "name": "材质B", "color": "#4a8fd0",
            "albedo": {"path": png, "name": "b", "guid": "g-b"}}
    gl = _gl_material(matd).albedo
    vk = _vk_material(matd).albedo
    print("  GL:", _sig(gl))
    print("  VK:", _sig(vk))
    check("默认导入设置: VK 与 GL 完全一致", _sig(vk) == _sig(gl), _sig(vk))
    check("默认设置不缩像素 (256x256)", (vk.width, vk.height) == (256, 256),
          (vk.width, vk.height))


def t_normal_map_slot(png):
    """normal_map 槽位同样要转发导入设置 (两个槽共用一个取值列表)."""
    matd = {"id": "m3", "name": "材质C", "color": "#ffffff",
            "normal_map": {"path": png, "name": "n", "guid": "g-n",
                           "max_size": 32, "mipmaps": False,
                           "wrap": "mirror", "filter_mode": "bilinear",
                           "aniso": 2.0}}
    gl = _gl_material(matd).normal_map
    vk = _vk_material(matd).normal_map
    print("  GL:", _sig(gl))
    print("  VK:", _sig(vk))
    check("normal_map: VK 与 GL 完全一致", _sig(vk) == _sig(gl), _sig(vk))


def _env_sig(cube):
    """Cubemap 的可比较签名: (size, 面数, 首像素, solid_color, name, guid)."""
    if cube is None:
        return None
    faces = getattr(cube, '_faces', None) or []
    first = tuple(int(v) for v in faces[0][0, 0]) if faces else None
    return (int(cube.size), len(faces), first,
            tuple(getattr(cube, '_solid_color', None) or ()),
            cube.name, cube.guid)


def t_env_solid_color():
    """纯色环境贴图 (Cubemap.from_solid) 在 VK 侧也要被还原 (F7 联动)."""
    print("=== 纯色 env_map (solid_color) GL vs VK ===")
    matd = {"id": "m5", "name": "纯色环境", "color": "#3a7bd5",
            "env_map": {"guid": "g-env", "name": "环境A",
                        "solid_color": [58, 123, 213, 255]}}
    gl = _gl_material(matd).env_map
    vk = _vk_material(matd).env_map
    print("  GL:", _env_sig(gl))
    print("  VK:", _env_sig(vk))
    check("纯色 env: VK 侧拿到 cubemap", vk is not None, vk)
    if vk is None:
        return
    check("纯色 env: VK 与 GL 完全一致", _env_sig(vk) == _env_sig(gl), _env_sig(vk))
    check("纯色 env: 面数 = 6", len(getattr(vk, '_faces', []) or []) == 6,
          len(getattr(vk, '_faces', []) or []))
    check("纯色 env: 尺寸 = 4x4 (from_solid 默认)",
          vk.size == 4 and all(f.shape == (4, 4, 4) for f in vk._faces), vk.size)
    check("纯色 env: 像素颜色 = (58,123,213,255)",
          tuple(int(v) for v in vk._faces[0][0, 0]) == (58, 123, 213, 255),
          tuple(int(v) for v in vk._faces[0][0, 0]))
    check("纯色 env: 序列化来源 _solid_color 保留 (可再次存盘)",
          tuple(vk._solid_color) == (58, 123, 213, 255), vk._solid_color)
    check("纯色 env: name/guid 保留", (vk.name, vk.guid) == ("环境A", "g-env"),
          (vk.name, vk.guid))


def t_env_solid_color_roundtrip():
    """emit -> apply 往返: sceneio 写出的 solid_color 段 VK 侧也能吃 (F7 契约)."""
    print("=== 纯色 env_map: sceneio emit -> VK build_materials 往返 ===")
    from loom_material import Material
    from loom_cubemap import Cubemap
    mat = Material(name="往返", color="#20c060")
    mat.guid = "m-roundtrip"
    mat.env_map = Cubemap.from_solid((20, 192, 96, 255), name="env-rt",
                                     guid="g-rt")
    matd = sceneio._emit_material(mat)
    check("emit 写出 solid_color (无 paths)",
          matd.get("env_map", {}).get("solid_color") == [20, 192, 96, 255]
          and "paths" not in matd.get("env_map", {}), matd.get("env_map"))
    vk = _vk_material(matd).env_map
    check("VK 读回纯色 env (尺寸/面数/颜色)",
          vk is not None and vk.size == 4 and len(vk._faces) == 6
          and tuple(int(v) for v in vk._faces[0][0, 0]) == (20, 192, 96, 255),
          _env_sig(vk))


def t_env_paths_still_work(tmpdir):
    """6 面 paths 分支在改动后仍工作 (防重构回归)."""
    print("=== 6 面 paths 环境贴图 (回归) ===")
    import pygame
    pygame.init()
    paths = []
    for i in range(6):
        p = os.path.join(tmpdir, "env_%d.png" % i)
        surf = pygame.Surface((8, 8), pygame.SRCALPHA)
        surf.fill((10 * i, 20, 30, 255))
        pygame.image.save(surf, p)
        paths.append(p)
    matd = {"id": "m6", "name": "六面环境", "env_map": {
        "guid": "g-env6", "name": "环境B", "paths": paths}}
    gl = _gl_material(matd).env_map
    vk = _vk_material(matd).env_map
    check("paths env: VK 侧拿到 cubemap", vk is not None, vk)
    if vk is not None:
        check("paths env: VK 与 GL 尺寸/面数一致",
              (vk.size, len(vk._faces)) == (gl.size, len(gl._faces)),
              (vk.size, len(vk._faces)))
        check("paths env: 6 面路径保留", len(vk.paths or []) == 6, vk.paths)


def t_env_missing_tolerated(tmpdir):
    """坏 env 段 (文件缺失 / 非法 solid_color) -> 两端都不挂, 不抛."""
    print("=== 坏 env_map 容错 ===")
    for tag, env in (("文件缺失", {"paths": [os.path.join(tmpdir, "no_%d.png" % i)
                                            for i in range(6)]}),
                     ("solid_color 非法", {"solid_color": "oops"}),
                     ("空对象", {})):
        matd = {"id": "m7", "name": "坏环境", "env_map": env}
        err = None
        gl = vk = None
        try:
            gl = _gl_material(matd).env_map
            vk = _vk_material(matd).env_map
        except BaseException as e:      # noqa: BLE001
            err = "%s: %s" % (type(e).__name__, e)
        check("坏 env 不崩: %s" % tag, err is None, err)
        check("坏 env 两端一致 (都 None): %s" % tag, gl is None and vk is None,
              (gl, vk))


def t_missing_file_tolerated(tmpdir):
    """贴图文件缺失 -> 两端都不挂贴图, 不抛 (容错语义仍一致)."""
    matd = {"id": "m4", "name": "材质D",
            "albedo": {"path": os.path.join(tmpdir, "nope.png"), "name": "x"}}
    gl = _gl_material(matd)
    vk = _vk_material(matd)
    check("文件缺失: GL 无贴图", getattr(gl, 'albedo', None) is None)
    check("文件缺失: VK 无贴图", getattr(vk, 'albedo', None) is None)


def main():
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        png = os.path.join(tmp, "tex256.png")
        _make_png(png)
        print("=== 材质贴图导入设置: GL vs VK (scan_05 P-03) ===")
        t_import_settings_forwarded(png)
        t_default_import_settings(png)
        t_normal_map_slot(png)
        t_env_solid_color()
        t_env_solid_color_roundtrip()
        t_env_paths_still_work(tmp)
        t_env_missing_tolerated(tmp)
        t_missing_file_tolerated(tmp)
    print("=" * 60)
    if _fails:
        print("失败:", _fails)
        return 1
    print("ALL PASS")
    return 0


if __name__ == '__main__':
    sys.exit(main())
