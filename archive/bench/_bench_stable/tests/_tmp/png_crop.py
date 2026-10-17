# -*- coding: utf-8 -*-
"""png_crop.py — 裁剪 PNG 区域 (验收链 T1 查看用): py png_crop.py src x0 y0 x1 y1 out"""
import sys
from PIL import Image

src, x0, y0, x1, y1, out = sys.argv[1], int(sys.argv[2]), int(sys.argv[3]), int(sys.argv[4]), int(sys.argv[5]), sys.argv[6]
im = Image.open(src).convert('RGB')
im = im.crop((x0, y0, x1, y1))
if len(sys.argv) > 7:
    im = im.resize((im.width * int(sys.argv[7]), im.height * int(sys.argv[7])), Image.NEAREST)
im.save(out)
print("saved", out, "crop size", (x1 - x0, y1 - y0))
