# -*- coding: utf-8 -*-
"""probe_glfw_ime_zh.py — GLFW 窗口中文输入法精确测试 (2026-10-18)

明确验证：GLFW 窗口里输入法候选框能否弹出？提交的中文能否被 char_callback 收到？

用户操作流程：
  1. 点击窗口，用中文输入法打几个字（如 "你好"）—— 请明确用中文输入法
  2. 观察：候选框弹出吗？能看到中文候选词吗？
  3. 选中词，看窗口上是否显示中文
  4. ESC 关闭窗口

日志记录所有事件：
  - 每次按键的 KEY 事件（含 scancode）
  - char_callback 收到的所有字符（含 Unicode 码点）
  - 最后汇总：收到了多少中文（CJK 区域 U+4E00~U+9FFF）

与之前 probe_glfw_ime.py 的区别：打印更详细，明确提示用户尝试中文输入。
"""
import os
import sys
import time

import glfw

LOG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        '_glfw_ime_zh_test.log')


def log(msg):
    line = '[%s] %s' % (time.strftime('%H:%M:%S'), msg)
    print(line)
    with open(LOG_PATH, 'a', encoding='utf-8') as f:
        f.write(line + '\n')


with open(LOG_PATH, 'w', encoding='utf-8') as f:
    f.write('')

if not glfw.init():
    print('glfw init failed')
    sys.exit(1)

glfw.window_hint(glfw.CONTEXT_VERSION_MAJOR, 3)
glfw.window_hint(glfw.CONTEXT_VERSION_MINOR, 3)
glfw.window_hint(glfw.OPENGL_PROFILE, glfw.OPENGL_CORE_PROFILE)

win = glfw.create_window(
    800, 400,
    'GLFW IME 测试 - 请用中文输入法打 "你好"（ESC 退出）',
    None, None)
if not win:
    glfw.terminate()
    print('glfw create_window failed')
    sys.exit(1)

glfw.make_context_current(win)
glfw.swap_interval(0)

received = []    # [(codepoint, char)]
all_keypresses = []


def on_char(w, codepoint):
    ch = chr(codepoint) if codepoint < 0x110000 else '?'
    received.append((codepoint, ch))
    log('CHAR: U+%04X %r' % (codepoint, ch))


def on_key(w, key, scancode, action, mods):
    if action == glfw.PRESS:
        all_keypresses.append((key, scancode))
        log('KEYDOWN: key=%d scancode=%d' % (key, scancode))
        if key == glfw.KEY_ESCAPE:
            glfw.set_window_should_close(w, True)


glfw.set_char_callback(win, on_char)
glfw.set_key_callback(win, on_key)

log('=== GLFW 中文输入测试 ===')
log('请在窗口中用中文输入法打 "你好" 两个字，观察：')
log('  1) 候选框是否弹出？')
log('  2) 键盘按键是否被输入法拦截（看上面的 KEYDOWN 日志）？')
log('  3) 选中后 char_callback 收到的字符是什么？')
log('  4) 窗口标题栏是否显示中文？')
log('按 ESC 关闭窗口')
log('')

# 简单画个黑屏但显示文字提示（用 bitmap 内嵌太麻烦，跳过）
start = time.time()
while not glfw.window_should_close(win):
    glfw.poll_events()
    glfw.swap_buffers(win)
    if time.time() - start > 180:
        log('超时 180 秒，自动退出')
        break

glfw.terminate()

# 统计
cjk_chars = [ch for cp, ch in received if 0x4E00 <= cp <= 0x9FFF]
ascii_chars = [ch for cp, ch in received if cp < 128]
log('')
log('=== 测试结果 ===')
log('总字符数: %d' % len(received))
log('ASCII 字符 (%d): %r' % (len(ascii_chars), ''.join(ascii_chars)))
log('CJK 中文 (%d): %r' % (len(cjk_chars), ''.join(cjk_chars)))
log('按键总数: %d' % len(all_keypresses))

print()
print('=== 测试完成 ===')
print('ASCII: %r' % ''.join(ascii_chars))
print('中文: %r' % ''.join(cjk_chars))
print('按键数: %d' % len(all_keypresses))
if cjk_chars:
    print('结论: GLFW 窗口能收到中文（char_callback 工作）')
else:
    print('结论: 未收到中文字符（输入法可能未启动或未选中词）')
