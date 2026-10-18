# -*- coding: utf-8 -*-
"""probe_glfw_ime.py — GLFW 窗口输入法污染实测 (2026-10-18)

目的：验证 GLFW 窗口（Vulkan 后端默认窗口）是否与 pygame 一样
      会进程级污染系统输入法（候选框不弹 + 影响其他程序）。
方法：
  1. 打开 GLFW 3.4 窗口，注册 char/key 回调
  2. 用户窗口内打中文（观察候选框、字符是否被收到）
  3. 用户切到记事本打中文（观察是否受影响）
  4. ESC 关闭窗口后再切到记事本打中文（观察是否恢复）
日志：_glfw_ime_test.log
"""
import os
import sys
import time

import glfw

LOG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        '_glfw_ime_test.log')


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
    'GLFW IME 实测 - 点我后用中文输入法打字 (ESC 退出)',
    None, None)
if not win:
    glfw.terminate()
    print('glfw create_window failed')
    sys.exit(1)

glfw.make_context_current(win)
glfw.swap_interval(0)

received = []


def on_char(w, codepoint):
    ch = chr(codepoint)
    received.append(ch)
    log('CHAR: U+%04X %r' % (codepoint, ch))


def on_key(w, key, scancode, action, mods):
    if action == glfw.PRESS:
        log('KEY: %d (ESC=%d)' % (key, glfw.KEY_ESCAPE))
        if key == glfw.KEY_ESCAPE:
            glfw.set_window_should_close(w, True)


glfw.set_char_callback(win, on_char)
glfw.set_key_callback(win, on_key)

if hasattr(glfw, 'set_preedit_callback'):
    def on_preedit(w, text):
        log('PREEDIT: %r' % text)
    glfw.set_preedit_callback(win, on_preedit)
    log('PREEDIT callback 已注册 (GLFW 3.4)')
else:
    log('PREEDIT callback 不可用 (Python 绑定未暴露)')

log('GLFW 窗口已创建。请按以下步骤操作：')
log('  1) 点击本窗口，用中文输入法打几个字（如 "你好"）')
log('  2) 切到记事本打中文，观察输入法是否正常')
log('  3) 按 ESC 关闭窗口')
log('  4) 关闭后再切到记事本打中文，观察输入法是否恢复')

start = time.time()
while not glfw.window_should_close(win):
    glfw.poll_events()
    glfw.swap_buffers(win)
    if time.time() - start > 180:
        log('超时 180 秒，自动退出')
        break

glfw.terminate()
log('窗口关闭。共收到 %d 个字符：%r' % (len(received), ''.join(received)))
print()
print('=== 测试完成 ===')
print('收到字符数:', len(received))
print('收到内容:', repr(''.join(received)))
if received:
    print('结论: GLFW 窗口能收到字符 (char_callback 工作)')
else:
    print('结论: 未收到字符 (输入法未提交或 char_callback 未触发)')
