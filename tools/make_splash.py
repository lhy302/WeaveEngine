# -*- coding: utf-8 -*-
"""make_splash.py — 生成 LoomHub 启动画面 PNG（2026-10-19）

背景：PyInstaller --onedir 启动仍需 0.3~1 秒，用户连点可能开多个实例。
虽然已有单实例锁兜底，但加一张启动图让用户立刻看到"正在启动..."反馈更好。

产物：tools/build_assets/splash.png（480x300）
依赖：Pillow（pip install pillow）
"""
import os
import sys

try:
    from PIL import Image, ImageDraw, ImageFont
except ImportError:
    print('[错误] 需要 Pillow: py -3.12 -m pip install pillow')
    sys.exit(1)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_DIR = os.path.join(ROOT, 'tools', 'build_assets')
OUT_PATH = os.path.join(OUT_DIR, 'splash.png')

W, H = 480, 300


def _load_font(size):
    """尝试加载系统字体，失败则返回 PIL 默认字体."""
    candidates = [
        r'C:\Windows\Fonts\msyh.ttc',        # 微软雅黑
        r'C:\Windows\Fonts\msyhbd.ttc',
        r'C:\Windows\Fonts\segoeui.ttf',
        r'C:\Windows\Fonts\simhei.ttf',      # 黑体
    ]
    for c in candidates:
        if os.path.isfile(c):
            try:
                return ImageFont.truetype(c, size)
            except Exception:
                continue
    try:
        return ImageFont.load_default()
    except Exception:
        return None


def make_splash():
    os.makedirs(OUT_DIR, exist_ok=True)
    img = Image.new('RGB', (W, H), color=(30, 34, 46))   # 深蓝灰
    d = ImageDraw.Draw(img)

    # 顶部装饰线
    d.rectangle([0, 0, W, 4], fill=(90, 130, 220))

    # 大标题
    f_title = _load_font(48)
    if f_title:
        text = 'LoomHub'
        bbox = d.textbbox((0, 0), text, font=f_title)
        tw = bbox[2] - bbox[0]
        th = bbox[3] - bbox[1]
        d.text(((W - tw) / 2, 90), text, fill=(230, 235, 245), font=f_title)

    # 副标题
    f_sub = _load_font(18)
    if f_sub:
        sub = '项目管理器 · 多版本共存'
        bbox = d.textbbox((0, 0), sub, font=f_sub)
        tw = bbox[2] - bbox[0]
        d.text(((W - tw) / 2, 165), sub, fill=(150, 160, 180), font=f_sub)

    # 底部进度提示
    f_hint = _load_font(14)
    if f_hint:
        hint = '正在启动...'
        bbox = d.textbbox((0, 0), hint, font=f_hint)
        tw = bbox[2] - bbox[0]
        d.text(((W - tw) / 2, 245), hint, fill=(120, 130, 150), font=f_hint)

    # 底部装饰线
    d.rectangle([0, H - 4, W, H], fill=(90, 130, 220))

    img.save(OUT_PATH, 'PNG')
    print('已生成:', OUT_PATH)


if __name__ == '__main__':
    make_splash()
