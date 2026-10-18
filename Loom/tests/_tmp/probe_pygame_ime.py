# -*- coding: utf-8 -*-
"""probe_pygame_ime.py — pygame 窗口输入法污染实测 (2026-10-18)

用户要求：验证 pygame 窗口是否仍会导致系统输入法失灵（当初换 Qt 的根因）。
测试流程：
  1. 打开 pygame 窗口，开启 start_text_input()
  2. 用户在窗口中尝试用输入法打中文字
  3. 观察：候选框能否弹出、位置是否正确、字符能否进入窗口
  4. 按 ESC 或关闭窗口退出
所有事件写入 _ime_test.log 供事后分析。
"""
import os
import sys
import time

import pygame

LOG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), '_ime_test.log')

def log(msg):
    line = '[%s] %s' % (time.strftime('%H:%M:%S'), msg)
    print(line)
    with open(LOG_PATH, 'a', encoding='utf-8') as f:
        f.write(line + '\n')

# 清空日志
with open(LOG_PATH, 'w', encoding='utf-8') as f:
    f.write('')

pygame.init()
screen = pygame.display.set_mode((800, 400))
pygame.display.set_caption('输入法实测 - 请用输入法打中文 (ESC 退出)')

font = pygame.font.Font('C:/Windows/Fonts/msyh.ttc', 20)
font_big = pygame.font.Font('C:/Windows/Fonts/msyh.ttc', 28)

# 开启 IME
try:
    pygame.key.start_text_input()
    pygame.key.set_text_input_rect(pygame.Rect(50, 200, 700, 30))
    log('IME 开启: pygame.key.start_text_input() 成功')
except Exception as e:
    log('IME 开启失败: %r' % (e,))

text_buffer = ''      # 所有收到的字符
event_log = []        # 最近 10 条关键事件
event_count = {'TEXTINPUT': 0, 'TEXTEDITING': 0, 'KEYDOWN': 0}
start = time.time()

running = True
while running:
    for ev in pygame.event.get():
        if ev.type == pygame.QUIT:
            running = False
        elif ev.type == pygame.KEYDOWN:
            event_count['KEYDOWN'] += 1
            log('KEYDOWN: key=%r unicode=%r' % (ev.key, getattr(ev, 'unicode', '?')))
            event_log.append('KEYDOWN key=%r' % ev.key)
            if ev.key == pygame.K_ESCAPE:
                running = False
            elif ev.key == pygame.K_BACKSPACE:
                text_buffer = text_buffer[:-1]
            elif ev.key == pygame.K_c and (ev.mod & pygame.KMOD_CTRL):
                text_buffer = ''
        elif ev.type == getattr(pygame, 'TEXTINPUT', -1):
            event_count['TEXTINPUT'] += 1
            t = ev.text
            log('TEXTINPUT: %r' % t)
            event_log.append('TEXTINPUT %r' % t)
            text_buffer += t
        elif ev.type == getattr(pygame, 'TEXTEDITING', -1):
            event_count['TEXTEDITING'] += 1
            log('TEXTEDITING: text=%r start=%r length=%r'
                % (getattr(ev, 'text', '?'), getattr(ev, 'start', '?'),
                   getattr(ev, 'length', '?')))

    screen.fill((30, 30, 40))
    # 提示
    lines = [
        'pygame IME 实测',
        '请点击此窗口，然后用中文输入法打几个字（例如输入 "你好"）',
        '观察：1) 输入法候选框是否弹出  2) 候选框位置是否在下方输入区',
        '3) 字符是否显示在下方缓冲区  4) 切到别的程序看输入法是否正常',
        'ESC 退出 / Backspace 删除 / Ctrl+C 清空',
    ]
    for i, t in enumerate(lines):
        surf = font.render(t, True, (220, 220, 230))
        screen.blit(surf, (20, 20 + i * 28))
    # 输入区
    pygame.draw.rect(screen, (60, 70, 90), (50, 200, 700, 40), 2)
    surf = font_big.render(text_buffer or '(点击此窗口后开始用输入法打字)',
                           True, (255, 255, 255))
    screen.blit(surf, (55, 205))
    # 事件统计
    stat = 'TEXTINPUT=%d  TEXTEDITING=%d  KEYDOWN=%d' % (
        event_count['TEXTINPUT'], event_count['TEXTEDITING'],
        event_count['KEYDOWN'])
    surf = font.render(stat, True, (180, 200, 180))
    screen.blit(surf, (20, 360))
    # 最近事件
    for i, e in enumerate(event_log[-3:]):
        surf = font.render(e[:80], True, (150, 180, 200))
        screen.blit(surf, (20, 260 + i * 24))
    pygame.display.flip()

try:
    pygame.key.stop_text_input()
except Exception:
    pass
pygame.quit()
log('窗口关闭. 总事件: TEXTINPUT=%d TEXTEDITING=%d KEYDOWN=%d'
    % (event_count['TEXTINPUT'], event_count['TEXTEDITING'],
       event_count['KEYDOWN']))
print()
print('=== 测试完成 ===')
print('TEXTINPUT=%d  TEXTEDITING=%d  KEYDOWN=%d' % (
    event_count['TEXTINPUT'], event_count['TEXTEDITING'],
    event_count['KEYDOWN']))
if event_count['TEXTINPUT'] > 0:
    print('结论: pygame 窗口能收到 TEXTINPUT（输入法提交的字符到达窗口）')
else:
    print('结论: 未收到 TEXTINPUT（输入法未工作或未打中文）')
