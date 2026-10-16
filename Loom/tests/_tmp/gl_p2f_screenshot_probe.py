# -*- coding: utf-8 -*-
"""gl_p2f_screenshot_probe.py — GL 引擎 offscreen 截图 (同场景/同相机 A/B, 2026-08-29).

EditorApp 渲染一帧后从主 FBO 读回 -> PNG. 与 Vk offscreen 探针对齐像素格式.
用法: py -3.12 tests\_tmp\gl_p2f_screenshot_probe.py [输出.png]
"""
import os
import sys
import math
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))))           # ...\Loom
os.environ['LOOM_PROFILE'] = '1'

import numpy as np

import pygame
import pygame.freetype
pygame.init()
pygame.freetype.init()
pygame.display.gl_set_attribute(pygame.GL_SWAP_CONTROL, 0)

import editor
import sceneio

W, H = 1280, 800
eng = editor.EditorApp(W, H)
for m in list(eng.models):
    eng.remove_model(m)
data = sceneio.load_scene_data(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                            '..', '..', '保存', '压测50球.json'))
sceneio.scene_from_dict(eng, data)
cam = data.get('camera', {})
eng.camera_target = tuple(cam.get('target', (0, 2, 0)))
eng.camera_distance = cam.get('distance', 32.0)
eng.camera_yaw = cam.get('yaw', 0.7)
eng.camera_pitch = cam.get('pitch', -0.38)

# 伪装外部模式: 主 pass 送自建 FBO (flip 被跳过), 直读 (双缓冲屏幕读回会翻黑)
color_tex = eng.ctx.texture((W, H), 4)
depth_tex = eng.ctx.depth_texture((W, H))
fb = eng.ctx.framebuffer(color_attachments=[color_tex], depth_attachment=depth_tex)
eng._external_ctx = True          # 仅用于 _screen_fb() 返回自建 FBO (勿动其余!)
eng._external_fb = fb
eng.render(1.0 / 60.0)            # 完整主 pass (含阴影) + 脚本, 不 flip
print("GLCamera yaw=%.4f pitch=%.4f dist=%.1f target=%s pos=%s" %
      (eng.camera_yaw, eng.camera_pitch, eng.camera_distance,
       tuple(eng.camera_target), tuple(eng.camera)))
raw = fb.read(components=4, alignment=1)    # 行序 bottom-up
arr = np.frombuffer(raw, dtype=np.uint8).reshape(H, W, 4)[::-1]   # 翻转 → top-down

surf = pygame.image.fromstring(arr.tobytes(), (W, H), 'RGBA')
out = sys.argv[1] if len(sys.argv) > 1 else os.path.join(
    os.path.dirname(os.path.abspath(__file__)), 'shot_gl_offscreen.png')
pygame.image.save(surf, out)
print("已保存:", out)
eng._stop_parallel()
pygame.quit()
