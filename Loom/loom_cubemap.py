# -*- coding: utf-8 -*-
"""loom_cubemap.py — 立方体贴图资产 (M36 贴图体系第5步: 环境反射)。

对标 Unity Cubemap / Reflection Probe 的静态部分：
  - 6 面图片加载（+X/-X/+Y/-Y/+Z/-Z）
  - 单色生成（占位/纯色环境）
  - GPU 上传（含 mipmap，粗糙度分级采样用）

CPU 侧持 6 面 RGBA (numpy uint8)，GPU 侧延迟创建（同 Texture 纪律）。
"""
import os
import uuid

import numpy as np

try:
    import pygame
except ImportError:
    pygame = None


class Cubemap:
    """立方体贴图：6 面 RGBA + GPU 立方纹理。可作为材质环境反射贴图。"""

    FACES = ('px', 'nx', 'py', 'ny', 'pz', 'nz')   # +X -X +Y -Y +Z -Z

    def __init__(self, size=0, faces=None, name=None, guid=None, paths=None,
                 mipmaps=True):
        self.guid = guid or uuid.uuid4().hex
        self.name = name or '立方体贴图'
        self.size = int(size)
        self._faces = faces if faces is not None else None   # [6 x (H,W,4)]
        self.paths = paths                                    # 6 面文件路径
        self.mipmaps = bool(mipmaps)
        self._gl_tex = None
        self._gl_ctx_id = None

    @classmethod
    def from_files(cls, paths, name=None, guid=None, mipmaps=True):
        """从 6 张图片加载（顺序 +X,-X,+Y,-Y,+Z,-Z）。失败抛 ValueError。"""
        if pygame is None:
            raise ValueError("pygame 不可用，无法解码图片")
        if len(paths) != 6:
            raise ValueError("需要 6 张图 (px,nx,py,ny,pz,nz)，收到 %d" % len(paths))
        faces = []
        size = None
        for i, p in enumerate(paths):
            if not os.path.isfile(p):
                raise ValueError("第 %d 面图片不存在: %s" % (i, p))
            try:
                img = pygame.image.load(p)
                try:
                    img = img.convert_alpha()
                except Exception:
                    surf = pygame.Surface(img.get_size(), pygame.SRCALPHA)
                    surf.blit(img, (0, 0))
                    img = surf
            except Exception as e:
                raise ValueError("第 %d 面解码失败 %s: %r" % (i, p, e))
            w, h = img.get_size()
            if w != h:
                raise ValueError("cubemap 每面必须正方形，第 %d 面 %dx%d" % (i, w, h))
            if size is None:
                size = w
            elif w != size:
                raise ValueError("cubemap 各面尺寸须一致 (第 %d 面 %d != %d)"
                                 % (i, w, size))
            raw = pygame.image.tostring(img, 'RGBA', False)
            faces.append(np.frombuffer(raw, dtype=np.uint8).reshape(h, w, 4).copy())
        return cls(size, faces=faces, name=name, guid=guid,
                   paths=[os.path.abspath(p) for p in paths], mipmaps=mipmaps)

    @classmethod
    def from_solid(cls, color, size=4, name=None, guid=None, mipmaps=True):
        """单色立方体贴图（占位/纯色环境）。color=(r,g,b,a) 0-255 或 '#RRGGBB'。"""
        if isinstance(color, str):
            from loom_color import _hex_rgba
            rgba = _hex_rgba(color)
        else:
            rgba = color
        arr = np.zeros((size, size, 4), dtype=np.uint8)
        arr[:, :, 0] = int(rgba[0]); arr[:, :, 1] = int(rgba[1])
        arr[:, :, 2] = int(rgba[2]); arr[:, :, 3] = int(rgba[3]) if len(rgba) > 3 else 255
        return cls(size, faces=[arr.copy() for _ in range(6)], name=name,
                   guid=guid, mipmaps=mipmaps)

    def ensure_gl(self, ctx):
        """在 ctx 上创建 cubemap GPU 纹理（含 mipmap）。已有则直接返回。"""
        if self._gl_tex is not None and self._gl_ctx_id == id(ctx):
            return self._gl_tex
        faces = self._faces
        if not faces:
            faces = [np.full((1, 1, 4), 255, dtype=np.uint8) for _ in range(6)]
            self.size = 1
        tex = ctx.texture_cube((self.size, self.size), 4, dtype='f1')
        for i, f in enumerate(faces[:6]):
            tex.write(i, np.ascontiguousarray(f).tobytes())
        has_mip = False
        if self.mipmaps and self.size > 1:
            try:
                tex.build_mipmaps()
                has_mip = True
            except Exception:
                pass
        # 过滤：★只在 mip 链完整时才用 MIPMAP filter（否则 GL 采样返回黑 —— 经典陷阱）
        import moderngl as _mgl
        try:
            tex.filter = ((_mgl.LINEAR_MIPMAP_LINEAR if has_mip else _mgl.LINEAR),
                          _mgl.LINEAR)
        except Exception:
            pass
        self._gl_tex = tex
        self._gl_ctx_id = id(ctx)
        return tex

    @property
    def gl_tex(self):
        return self._gl_tex

    def use(self, unit=0):
        if self._gl_tex is not None:
            self._gl_tex.use(unit)

    def release(self):
        if self._gl_tex is not None:
            try:
                self._gl_tex.release()
            except Exception:
                pass
        self._gl_tex = None
        self._gl_ctx_id = None

    def __repr__(self):
        return "Cubemap(%s %d%s)" % (self.name, self.size,
                                     ' GPU' if self._gl_tex is not None else '')
