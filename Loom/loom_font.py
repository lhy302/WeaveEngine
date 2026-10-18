# -*- coding: utf-8 -*-
"""loom_font.py — 多字体回退链与字符映射缓存 (2026-10-18)

契约: docs/design/CanvasUI系统契约_20261018.md §2.5
目标: UTF-8 全字符集显示 (中文/emoji/符号/日文/韩文), 且不引入逐字符查询开销.

方案 B (用户决策):
  - 字符 -> 字体索引 缓存 (进程级), 首次查 freetype, 之后纯 dict 命中
  - 分段渲染: 连续同字体合并, 每段一次 render, 最后横向拼接
  - emoji 等比缩放到主字体行高, 垂直居中 (用户决策 B)

实现注意 (2026-10-18 实测): 字形检测必须用 pygame.freetype.Font.get_metrics,
pygame.font.Font 无此方法. 返回格式 [(min_x, max_x, min_y, max_y, adv_x, adv_y)] 或 [None].
"""
import os

import pygame
import pygame.freetype

_FONT_DIR = 'C:/Windows/Fonts/'

# 主字体候选 (与 loom_hud._primary_font_path 一致)
_PRIMARY_CANDIDATES = ('msyh.ttc', 'simhei.ttf', 'msyhl.ttc')

# 回退链 (主字体之后的顺序, 契约 §2.5.1)
_FALLBACK_CHAIN = ('seguiemj.ttf', 'seguisym.ttf', 'simsun.ttc',
                   'msgothic.ttc', 'malgun.ttf')


def _has_glyph(font, ch):
    """用 freetype 的 get_metrics 判定字形是否存在.

    返回格式实测: [(min_x, max_x, min_y, max_y, adv_x, adv_y)] 或 [None].
    adv_x > 0 说明有实际宽度; [None] 说明无字形.
    """
    try:
        m = font.get_metrics(ch)
    except Exception:
        return False
    if not m:
        return False
    first = m[0]
    if first is None:
        return False
    try:
        # 元组第 5 项是 advance_x (浮点)
        return float(first[4]) > 0.5
    except (IndexError, TypeError, ValueError):
        return False


class FontChain:
    """多字体回退链. 按字号惰性加载, 字符索引进程级缓存."""

    def __init__(self, primary_candidates=None, fallback_chain=None):
        self._primary = tuple(primary_candidates or _PRIMARY_CANDIDATES)
        self._fallback = tuple(fallback_chain or _FALLBACK_CHAIN)
        self._chains = {}         # size -> [freetype.Font, ...] (0=主, 1+=回退)
        self._char_index = {}     # (size, char) -> 索引
        self._missing = set()     # 全链都无字形的字符

    def _load_chain(self, size):
        """按字号加载整条链. 主字体必定有 (退默认); 回退项缺失位置为 None."""
        try:
            pygame.freetype.init()
        except Exception:
            pass
        chain = []
        primary = None
        for name in self._primary:
            p = os.path.join(_FONT_DIR, name)
            if os.path.exists(p):
                try:
                    primary = pygame.freetype.Font(p, size)
                    break
                except Exception:
                    continue
        if primary is None:
            # 兜底: freetype 默认字体 (无中文字形)
            primary = pygame.freetype.Font(None, size)
        chain.append(primary)
        for name in self._fallback:
            p = os.path.join(_FONT_DIR, name)
            if not os.path.exists(p):
                chain.append(None)
                continue
            try:
                chain.append(pygame.freetype.Font(p, size))
            except Exception:
                chain.append(None)
        self._chains[size] = chain
        return chain

    def get_chain(self, size):
        c = self._chains.get(size)
        if c is None:
            c = self._load_chain(size)
        return c

    def get_primary(self, size):
        return self.get_chain(size)[0]

    def char_index(self, ch, size):
        """字符 -> 字体链索引 (无字形返回 -1)."""
        key = (size, ch)
        hit = self._char_index.get(key)
        if hit is not None:
            return hit
        if ch in self._missing:
            return -1
        chain = self.get_chain(size)
        for i, f in enumerate(chain):
            if f is None:
                continue
            if _has_glyph(f, ch):
                self._char_index[key] = i
                return i
        self._missing.add(ch)
        return -1

    def split(self, text, size):
        """切分文本为 [(chain_index, substring), ...], 连续同字体合并."""
        segs = []
        cur_idx = None
        cur_chars = []
        for ch in text:
            idx = self.char_index(ch, size)
            if idx == -1:
                idx = 0    # 兜底: 主字体 (显示方块)
            if idx != cur_idx:
                if cur_chars:
                    segs.append((cur_idx, ''.join(cur_chars)))
                cur_idx = idx
                cur_chars = [ch]
            else:
                cur_chars.append(ch)
        if cur_chars:
            segs.append((cur_idx, ''.join(cur_chars)))
        return segs

    def _render_segment(self, font, text, color):
        """单段渲染 -> Surface (freetype.render 返回 (Surface, Rect), 取 Surface)."""
        try:
            surf, _rect = font.render(text, fgcolor=color)
            return surf
        except Exception:
            # 极端降级: 空表面
            return pygame.Surface((1, 1), pygame.SRCALPHA)

    def _measure_segment(self, font, text):
        """单段测量 -> (w, h) (freetype.get_rect 返回 Rect)."""
        try:
            r = font.get_rect(text)
            return (r.width, r.height)
        except Exception:
            return (0, 0)

    def render(self, text, color, size):
        """分段渲染 -> Surface. 空文本返回 1x1 透明表面."""
        if not text:
            return pygame.Surface((1, 1), pygame.SRCALPHA)
        chain = self.get_chain(size)
        target_h = chain[0].get_rect('Mg').height or size
        segs = self.split(text, size)
        surfs = []
        for idx, seg in segs:
            f = chain[idx] if 0 <= idx < len(chain) else chain[0]
            if f is None:
                f = chain[0]
            s = self._render_segment(f, seg, color)
            if idx != 0 and s.get_height() > 0 and abs(s.get_height() - target_h) > 2:
                new_w = max(1, int(round(s.get_width() * target_h / s.get_height())))
                try:
                    s = pygame.transform.smoothscale(s, (new_w, target_h))
                except Exception:
                    pass
            surfs.append(s)
        if not surfs:
            return pygame.Surface((1, 1), pygame.SRCALPHA)
        total_w = sum(s.get_width() for s in surfs)
        max_h = max(s.get_height() for s in surfs)
        result = pygame.Surface((max(1, total_w), max(1, max_h)), pygame.SRCALPHA)
        x = 0
        for s in surfs:
            y = (max_h - s.get_height()) // 2
            result.blit(s, (x, y))
            x += s.get_width()
        return result

    def measure(self, text, size):
        """返回 (w, h). 分段累计宽度, 高度取行高."""
        if not text:
            return (0, 0)
        chain = self.get_chain(size)
        target_h = chain[0].get_rect('Mg').height or size
        segs = self.split(text, size)
        total_w = 0
        for idx, seg in segs:
            f = chain[idx] if 0 <= idx < len(chain) else chain[0]
            if f is None:
                f = chain[0]
            w, h = self._measure_segment(f, seg)
            if idx != 0 and h > 0 and abs(h - target_h) > 2:
                w = int(round(w * target_h / h))
            total_w += w
        return (total_w, target_h)
