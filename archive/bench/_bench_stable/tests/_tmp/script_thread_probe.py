# -*- coding: utf-8 -*-
"""临时探针: 真实引擎 + 并行启用 -> 脚本专用线程播放验证 (用完可删).

注意: 不设 LOOM_NO_PARALLEL, 走真实 parallel 初始化 (应用进程亲和 + 建脚本线程).
"""
import os
import sys
import threading

sys.path.insert(0, os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))))
import editor
import pygame

app = editor.EditorApp(800, 600)
print("show_grid:", app.show_grid, "parallel_enable:", app.parallel_enable)
print("_script_runner:", app._script_runner)
print("parallel applied:", app.parallel is not None and app.parallel.get('applied'))

# 种子场景: 第一个模型挂 rotate 脚本 (默认 sy=90°/s 绕 Y 转)
m = app.models[0]
m.add_script('rotate', {})   # 默认参数 sy=90
print("初始 rotation.y:", m.rotation.y)

# 播放模式: 渲染 10 帧 -> 脚本应在 loom-scripts 线程执行, 旋转推进
app.toggle_play()
for _ in range(10):
    app.render(0.016)
print("播放 10 帧后 rotation.y:", m.rotation.y)
assert abs(m.rotation.y) > 0.001, "脚本旋转未推进!"
app.toggle_play()

# 直接走 _run_scripts 验证线程名
thread_names = set()


def spy():
    thread_names.add(threading.current_thread().name)


orig = app.update_scripts
app.update_scripts = lambda dt: (orig(dt), spy())
app._run_scripts(0.016)
print("脚本执行线程:", thread_names)
assert 'loom-scripts' in thread_names, "脚本未在专用线程执行!"
app.update_scripts = orig

app._stop_parallel()
pygame.quit()
print("PROBE OK ✅")
