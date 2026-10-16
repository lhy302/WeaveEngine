# -*- coding: utf-8 -*-
"""loom_texture.py — 纹理资产 (M36 贴图体系第一步)。

对标 Unity Texture 资产：可被多个 Material 共享，guid 稳定身份。
CPU 侧持有 RGBA 像素 (numpy uint8)，GPU 侧延迟创建 (load 时可能无 current GL context)。

依赖：pygame.image (解码 PNG/JPG/BMP 等) + numpy。
GL 资源归属创建时的 context (与桶几何同纪律)；release 由引擎清场统一调。

用法：
    tex = Texture.from_file("path/to.png")     # 加载 (CPU)
    tex.ensure_gl(ctx)                          # 上传 GPU (需 current context)
    tex.gl_tex                                  # moderngl texture (供 use/绑定)
"""
import os
import uuid

import numpy as np

try:
    import pygame
except ImportError:            # 无头环境/测试桩: 仅 from_rgba 可用
    pygame = None


class Texture:
    """纹理资产：RGBA 像素 + 可选 GPU 纹理 + mipmap。可被多材质共享。"""

    # M36 导入设置 (对标 Unity Texture Import Settings)
    WRAP_MODES = ('repeat', 'clamp', 'mirror')
    FILTER_MODES = ('point', 'bilinear', 'trilinear')
    # 压缩格式 (对标 Unity Compression)。moderngl 高层无硬件 DXT/BC API (需绕过),
    # 故用降位深格式 (硬件原生支持)。显存位深由 GL internal_format 决定 (非 components 数)。
    # 键 -> (GL internal_format, 上传分量数, 显存位深)
    # GL 常量: RGB8=0x8051, RGBA8=0x8058, RGB565=0x8D62, RGBA4=0x8056, RGB5_A1=0x8057
    COMPRESSION_FORMATS = {
        'none':     (0x8058, 4, 32),   # RGBA8    32bpp (基准)
        'rgb24':    (0x8051, 3, 24),   # RGB8     24bpp (去 alpha, 省 25%)
        'rgb565':   (0x8D62, 3, 16),   # RGB565   16bpp (省 50%)
        'rgba4444': (0x8056, 4, 16),   # RGBA4444 16bpp (省 50%)
        'rgb5a1':   (0x8057, 4, 16),   # RGB5_A1  16bpp (省 50%)
    }

    def __init__(self, width=0, height=0, rgba=None, name=None, guid=None,
                 path=None, mipmaps=True, wrap='repeat', filter_mode='trilinear',
                 aniso=1.0, max_size=0, compression='none'):
        self.guid = guid or uuid.uuid4().hex
        self.name = name or '纹理'
        self.path = path                      # 源文件路径 (序列化重载用)
        self.width = int(width)
        self.height = int(height)
        # CPU 侧 RGBA (H,W,4) uint8；无数据时为 None (占位/默认白)
        self._rgba = rgba if rgba is not None else None
        self.mipmaps = bool(mipmaps)
        # ---- M36 导入设置 (对标 Unity) ----
        self.wrap = wrap if wrap in self.WRAP_MODES else 'repeat'
        self.filter_mode = (filter_mode if filter_mode in self.FILTER_MODES
                            else 'trilinear')
        self.aniso = float(aniso or 1.0)
        self.max_size = int(max_size or 0)    # 0=不限制 (Unity: 32~8192)
        self.compression = (compression if compression in self.COMPRESSION_FORMATS
                            else 'none')     # 显存格式 (对标 Unity Compression)
        # GPU 侧 (延迟创建，归属创建时 context)
        self._gl_tex = None
        self._gl_ctx_id = None

    # ---- 构造 ----

    @classmethod
    def from_rgba(cls, width, height, rgba, name=None, guid=None,
                  path=None, mipmaps=True, wrap='repeat', filter_mode='trilinear',
                  aniso=1.0, max_size=0, compression='none'):
        arr = np.asarray(rgba, dtype=np.uint8)
        if arr.ndim != 3 or arr.shape[2] != 4:
            raise ValueError("rgba 必须是 (H,W,4) uint8，收到 %r" % (arr.shape,))
        if arr.shape[0] != height or arr.shape[1] != width:
            raise ValueError("rgba 尺寸 (%d,%d) 与 (w=%d,h=%d) 不符"
                             % (arr.shape[1], arr.shape[0], width, height))
        return cls(width, height, rgba=arr, name=name, guid=guid,
                   path=path, mipmaps=mipmaps, wrap=wrap,
                   filter_mode=filter_mode, aniso=aniso, max_size=max_size,
                   compression=compression)

    @classmethod
    def from_file(cls, path, name=None, guid=None, mipmaps=True, wrap='repeat',
                  filter_mode='trilinear', aniso=1.0, max_size=0, compression='none'):
        """从图片文件加载 (pygame 解码 -> RGBA)。失败抛 ValueError。
        wrap/filter_mode/aniso/max_size = 导入设置 (对标 Unity Texture Import Settings)。"""
        if pygame is None:
            raise ValueError("pygame 不可用，无法解码图片: %s" % path)
        if not os.path.isfile(path):
            raise ValueError("图片不存在: %s" % path)
        try:
            img = pygame.image.load(path)
        except Exception as e:
            raise ValueError("图片解码失败 %s: %r" % (path, e))
        # 统一转 RGBA (支持带 alpha 的 PNG)。convert_alpha 需已设显示模式;
        # 无头环境 (命令行工具/测试桩) 回退 SRCALPHA blit (不依赖 display)。
        try:
            img = img.convert_alpha()
        except Exception:
            surf = pygame.Surface(img.get_size(), pygame.SRCALPHA)
            surf.blit(img, (0, 0))
            img = surf
        w, h = img.get_size()
        # M36 Max Size (对标 Unity): 超过则等比缩放 (保持宽高比)
        if max_size and max_size > 0 and max(w, h) > max_size:
            scale = float(max_size) / float(max(w, h))
            nw, nh = max(1, int(round(w * scale))), max(1, int(round(h * scale)))
            try:
                img = pygame.transform.smoothscale(img, (nw, nh))
                w, h = nw, nh
            except Exception:
                pass                          # 缩放失败 -> 用原尺寸
        raw = pygame.image.tostring(img, 'RGBA', False)
        arr = np.frombuffer(raw, dtype=np.uint8).reshape(h, w, 4).copy()
        return cls(w, h, rgba=arr, name=name or os.path.basename(path),
                   guid=guid, path=os.path.abspath(path), mipmaps=mipmaps,
                   wrap=wrap, filter_mode=filter_mode, aniso=aniso,
                   max_size=max_size, compression=compression)

    @classmethod
    def white(cls, name='白纹理'):
        """1x1 纯白纹理：无贴图材质的默认绑定 (采样恒为白, 不改变原色)。"""
        arr = np.full((1, 1, 4), 255, dtype=np.uint8)
        t = cls(1, 1, rgba=arr, name=name, mipmaps=False)
        t._is_default_white = True
        return t

    # ---- GPU ----

    def ensure_gl(self, ctx):
        """在 ctx 上创建/上传 GPU 纹理 (含 mipmap)。已有则直接返回。"""
        if self._gl_tex is not None and self._gl_ctx_id == id(ctx):
            return self._gl_tex
        if self._rgba is None:
            # 无数据 -> 1x1 白兜底
            self._rgba = np.full((1, 1, 4), 255, dtype=np.uint8)
            self.width, self.height = 1, 1
        import moderngl as _mgl
        # M36 压缩: 按 compression 选 internal_format + 分量数 (对标 Unity Compression)
        ifmt, ncomp, _bpp = self.COMPRESSION_FORMATS.get(
            self.compression, self.COMPRESSION_FORMATS['none'])
        rgba = np.ascontiguousarray(self._rgba)
        if ncomp == 3:
            payload = rgba[:, :, :3].tobytes()   # 去 alpha (RGB 格式)
        else:
            payload = rgba.tobytes()
        tex = ctx.texture((self.width, self.height), ncomp, dtype='f1',
                          internal_format=ifmt)
        tex.write(payload)
        has_mip = self.mipmaps and self.width > 1 and self.height > 1
        if has_mip:
            try:
                tex.build_mipmaps()
            except Exception:
                has_mip = False               # mipmap 失败 -> 退化为单级
        # ---- M36 应用导入设置 (对标 Unity Import Settings) ----
        # 寻址模式: repeat -> repeat_x/y=True; clamp -> False。
        # (moderngl 只暴露 repeat_x/repeat_y 布尔, 无 MIRRORED_REPEAT; mirror 回退 repeat)
        try:
            if self.wrap == 'clamp':
                tex.repeat_x = False
                tex.repeat_y = False
            else:                              # repeat / mirror(回退)
                tex.repeat_x = True
                tex.repeat_y = True
        except Exception:
            pass
        # 过滤模式: point/bilinear/trilinear (+mipmap 组合)
        if self.filter_mode == 'point':
            tex.filter = (_mgl.NEAREST_MIPMAP_NEAREST if has_mip else _mgl.NEAREST,
                          _mgl.NEAREST)
        elif self.filter_mode == 'bilinear':
            tex.filter = (_mgl.LINEAR_MIPMAP_NEAREST if has_mip else _mgl.LINEAR,
                          _mgl.LINEAR)
        else:  # trilinear
            tex.filter = (_mgl.LINEAR_MIPMAP_LINEAR if has_mip else _mgl.LINEAR,
                          _mgl.LINEAR)
        # 各向异性过滤
        try:
            tex.anisotropy = float(self.aniso)
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
        """释放 GPU 资源 (清场/重建时调)。CPU 像素保留 (可重建)。"""
        if self._gl_tex is not None:
            try:
                self._gl_tex.release()
            except Exception:
                pass
        self._gl_tex = None
        self._gl_ctx_id = None

    def bump_appearance(self):
        """内容变化 -> 通知外观代计数器 (材质/贴图变化走同款失效)。"""
        try:
            from engine import GameObject
            GameObject._appearance_gen += 1
        except Exception:
            pass

    def __repr__(self):
        return "Texture(%s %dx%d%s)" % (
            self.name, self.width, self.height,
            ' GPU' if self._gl_tex is not None else '')
