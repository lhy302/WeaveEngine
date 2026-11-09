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
import weakref

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
        # 2026-10-19 天空盒: 记录纯色来源（from_solid 时设），供序列化还原
        # paths 有值 -> 序列化存 paths；paths 为 None 且 _solid_color 有值 -> 存纯色
        self._solid_color = None                              # (r,g,b,a) 0-255 或 None
        self._gl_tex = None
        # 2026-11-07 P2: 弱引用识别 context (防 id(ctx) 复用误判)
        self._gl_ctx_ref = None
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
        """单色立方体贴图（占位/纯色环境）。

        口径（2026-11-09 人类裁决 Q4=A / P-07）: **只认 0-255 通道值** 或 '#RRGGBB'。
          · 不再做 "全通道 <= 1.0 就自动乘 255" 的隐式放大（与命令层 int() 截断口径不一致，
            且会把 0.5 这类非法输入静默变成合法颜色 128）；
          · 越界 / 非数值 / 非法颜色串一律 ValueError（命令层由 03 号负责给出可读拒绝，
            这里是最后一道防御）；
          · alpha 缺省 255。
        """
        if isinstance(color, str):
            # loom_color._hex_rgba 对非法串会静默回退灰色（假成功）—— 这里先严格校验形态。
            s = color.strip()
            ok_form = (len(s) in (4, 7, 9) and s[:1] == '#'
                       and all(ch in '0123456789abcdefABCDEF' for ch in s[1:]))
            if not ok_form:
                raise ValueError("from_solid 颜色串必须是 #RGB / #RRGGBB / #RRGGBBAA: %r"
                                 % (color,))
            from loom_color import _hex_rgba
            rf = _hex_rgba(s[:7])
            rgba = [int(round(rf[0] * 255)), int(round(rf[1] * 255)),
                    int(round(rf[2] * 255)), 255]
            if len(s) == 4:      # #RGB 简写: 每位重复一次 (f -> ff)
                rgba = [int(s[1] * 2, 16), int(s[2] * 2, 16),
                        int(s[3] * 2, 16), 255]
            elif len(s) == 9:    # #RRGGBBAA
                rgba[3] = int(s[7:9], 16)
        else:
            if color is None or isinstance(color, (int, float, bool)):
                raise ValueError("from_solid 需要 (r,g,b[,a]) 0-255 或颜色串，收到 %r"
                                 % (color,))
            rgba = list(color)
            if len(rgba) < 3:
                raise ValueError("from_solid 颜色至少 3 个通道，收到 %r" % (color,))
            if len(rgba) < 4:
                rgba = rgba + [255]
            rgba = rgba[:4]
            out = []
            for i, v in enumerate(rgba):
                if isinstance(v, bool) or not isinstance(v, (int, float)):
                    raise ValueError("from_solid 通道 %d 不是数值: %r" % (i, v))
                fv = float(v)
                if not (0.0 <= fv <= 255.0):
                    raise ValueError("from_solid 通道 %d 越界 (%r)：本 API 只认 0-255"
                                     % (i, v))
                out.append(int(round(fv)))
            rgba = out

        arr = np.zeros((size, size, 4), dtype=np.uint8)
        arr[:, :, 0] = int(rgba[0]); arr[:, :, 1] = int(rgba[1])
        arr[:, :, 2] = int(rgba[2]); arr[:, :, 3] = int(rgba[3])
        cube = cls(size, faces=[arr.copy() for _ in range(6)], name=name,
                   guid=guid, mipmaps=mipmaps)
        # 2026-10-19 天空盒: 记录纯色来源（序列化还原用）
        cube._solid_color = (int(rgba[0]), int(rgba[1]), int(rgba[2]),
                             int(rgba[3]))
        return cube

    def _same_ctx(self, ctx):
        """GPU 纹理是否属于当前 ctx (弱引用优先; 无弱引用时退回 id)."""
        ref = self._gl_ctx_ref
        if ref is not None:
            try:
                return ref() is ctx
            except Exception:
                return False
        return self._gl_ctx_id is not None and self._gl_ctx_id == id(ctx)

    def _remember_ctx(self, ctx):
        try:
            self._gl_ctx_ref = weakref.ref(ctx)
        except TypeError:
            self._gl_ctx_ref = None
        self._gl_ctx_id = id(ctx)

    def ensure_gl(self, ctx):
        """在 ctx 上创建 cubemap GPU 纹理（含 mipmap）。已有则直接返回。

        2026-11-07 P2: 换 ctx 时先 release 旧纹理, 防旧 GPU 资源泄漏.
        """
        if self._gl_tex is not None:
            if self._same_ctx(ctx):
                return self._gl_tex
            self.release()                 # 换上下文: 释放旧纹理, 再重建
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
        self._remember_ctx(ctx)
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
        self._gl_ctx_ref = None
        self._gl_ctx_id = None

    def __repr__(self):
        return "Cubemap(%s %d%s)" % (self.name, self.size,
                                     ' GPU' if self._gl_tex is not None else '')