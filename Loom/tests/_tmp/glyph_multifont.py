# -*- coding: utf-8 -*-
"""临时探针: 多字体渲染字形对比 (alpha通道看真实形状). 定位是 msyh 缺字形还是系统/pygame 问题."""
import numpy as np
import pygame

pygame.init()
fonts = {
    "msyh(雅黑)": "C:/Windows/Fonts/msyh.ttc",
    "simhei(黑体)": "C:/Windows/Fonts/simhei.ttf",
    "simsun(宋体)": "C:/Windows/Fonts/simsun.ttc",
    "segoeui": "C:/Windows/Fonts/segoeui.ttf",
}
chars = "A中✓●«»"


def shape(surf):
    alpha = np.transpose(pygame.surfarray.array_alpha(surf))
    mask = alpha > 10
    # 统计: 非零 alpha 像素比例 + 中心是否实心 (空心方框中心空)
    n = int(mask.sum())
    ratio = n / mask.size if mask.size else 0
    h, w = mask.shape
    center = mask[h // 2 - 2:h // 2 + 3, w // 2 - 2:w // 2 + 3]
    return n, ratio, bool(center.any()), mask


for name, path in fonts.items():
    print("===== 字体:", name, "=====")
    try:
        f = pygame.font.Font(path, 40)
    except Exception as e:
        print("  加载失败:", e)
        continue
    for ch in chars:
        try:
            surf = f.render(ch, True, (255, 255, 255))
        except Exception as e:
            print("  %r 渲染失败: %s" % (ch, e))
            continue
        n, ratio, center, mask = shape(surf)
        w = surf.get_width()
        # 若整面实心 (ratio>0.9) = 缺字形块; 若中心空+有边框 = tofu 空心框; 否则真字形
        if ratio > 0.85:
            kind = "整面实心块(缺字形?)"
        elif n > 5 and not center:
            kind = "空心/笔画(可能正常或tofu)"
        elif n > 5:
            kind = "实心字形"
        else:
            kind = "空"
        print("  %r %dx%d 非零alpha:%d(%.0f%%) 中心实=%s => %s" %
              (ch, w, surf.get_height(), n, ratio * 100, center, kind))
pygame.quit()
