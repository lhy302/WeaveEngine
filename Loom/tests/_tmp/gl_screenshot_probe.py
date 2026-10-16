# -*- coding: utf-8 -*-
"""gl_screenshot_probe.py — GL 老引擎同视角截图 (vs Vk A/B 对比, 2026-08-29).

与 vk_player.py 同一压测场景/同一轨道相机参数, 渲染保持窗口 12 秒供截图.
用法: py -3.12 tests\_tmp\gl_screenshot_probe.py
"""
import os
import sys
import time

BASE = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))           # ...\Loom (editor.py 所在)
sys.path.insert(0, BASE)
os.chdir(BASE)
os.environ['LOOM_PROFILE'] = '1'

import pygame
pygame.init()
pygame.display.gl_set_attribute(pygame.GL_SWAP_CONTROL, 0)
pygame.display.set_mode((1280, 800))

# 先建一次 freetype 供引擎字体 (Minimal 视图 无 GUI 字面, 但保留)
import pygame.freetype
pygame.freetype.init()

import editor
import sceneio

eng = editor.EditorApp(1280, 800)
for m in list(eng.models):
    eng.remove_model(m)
eng.lights.clear()
data = sceneio.load_scene_data(os.path.join(BASE, '保存', '压测50球.json'))
sceneio.scene_from_dict(eng, data)
# 与 vk_player.py 同相机 (场景文件 camera 同款: target/dist/yaw/pitch)
cam = data.get('camera', {})
eng.camera_target = tuple(cam.get('target', (0, 2, 0)))
eng.camera_distance = cam.get('distance', 32.0)
eng.camera_yaw = cam.get('yaw', 0.7)
eng.camera_pitch = cam.get('pitch', -0.38)
print("GL 探针: models=%d lights=%d 相机 %s" % (len(eng.models), len(eng.lights),
                                               (eng.camera_target,
                                                eng.camera_distance,
                                                eng.camera_yaw, eng.camera_pitch)))
eng.render(1.0 / 60.0)

# 保持窗口 12 秒供截图
end = time.time() + 12.0
while time.time() < end:
    for ev in pygame.event.get():
        pass
    eng.render(1.0 / 60.0)
    pygame.display.flip()
    time.sleep(1.0 / 60.0)

eng._stop_parallel()
pygame.quit()
print("GL 探针结束")
