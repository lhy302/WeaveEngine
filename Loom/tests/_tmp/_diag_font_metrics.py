# -*- coding: utf-8 -*-
import pygame
pygame.font.init()

f = pygame.font.Font('C:/Windows/Fonts/msyh.ttc', 16)
print('=== get_metrics 返回格式诊断 ===')
for ch in ('你', 'A', '\U0001F600'):
    m = f.get_metrics(ch)
    print(repr(ch), '-> ', repr(m))
    if m and m[0] is not None:
        print('  len:', len(m[0]), 'type:', type(m[0]))
        print('  elements:', [type(x).__name__ for x in m[0]])
        print('  tuple:', m[0])

print()
print('=== size() 对比 (无字形时 size 会返回什么) ===')
for ch in ('你', '\U0001F600', '\u4e00'):
    print(repr(ch), 'size:', f.size(ch))

print()
print('=== 试试 render 后看宽高 ===')
for ch in ('你', '\U0001F600'):
    s = f.render(ch, True, (255, 255, 255))
    print(repr(ch), 'surface:', s.get_size())
