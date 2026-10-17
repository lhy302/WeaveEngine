# -*- coding: utf-8 -*-
"""vk_p2f_screenshot_probe.py — P2F offscreen 截图 (与 GL 同场景/同相机 A/B, 2026-08-29).

离屏渲染压测场景 -> read_texture -> PNG. 避免窗口层级干扰的屏幕截图.
用法: py -3.12 tests\_tmp\vk_p2f_screenshot_probe.py [输出.png]
"""
import os
import sys
import math
os.environ['WGPU_BACKEND_TYPE'] = 'Vulkan'

import numpy as np
import wgpu

BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, BASE)

from matlib import mat4_view_yaw_pitch, mat4_perspective
import vk_player                       # build_models/build_lights 复用
from vk_renderer import VkRenderer, orbit_camera
import sceneio

W, H = 1280, 800
scene = os.path.join(BASE, '保存', '压测50球.json')
data = sceneio.load_scene_data(scene)
models = vk_player.build_models(data)
lights = vk_player.build_lights(data)
cam = data.get('camera', {})
target = tuple(cam.get('target', (0, 2, 0)))
dist = cam.get('distance', 32.0)
yaw, pitch = cam.get('yaw', 0.7), cam.get('pitch', -0.38)

dev = wgpu.gpu.request_adapter_sync(power_preference='high-performance')
device = dev.request_device_sync()
print("backend:", dev.info['backend_type'])

tex = device.create_texture(size=(W, H, 1), format='rgba8unorm',
                            usage=wgpu.TextureUsage.RENDER_ATTACHMENT
                            | wgpu.TextureUsage.COPY_SRC)


class FakeCtx:
    physical_size = (W, H)
    def get_current_texture(self):
        return tex


r = VkRenderer(device, 'rgba8unorm')
cam_pos = orbit_camera(target, dist, yaw, pitch)
print("VkCamera yaw=%.4f pitch=%.4f dist=%.1f target=%s pos=%s" %
      (yaw, pitch, dist, target, cam_pos))
V = mat4_view_yaw_pitch(np, cam_pos, yaw, pitch)
P = mat4_perspective(np, math.radians(45.0), W / H, 0.1, 100.0)
r.draw_frame(FakeCtx(), models, lights, V @ P, cam_pos)

img = device.queue.read_texture(
    {"texture": tex, "mip_level": 0, "aspect": wgpu.TextureAspect.all},
    {"bytes_per_row": W * 4, "rows_per_image": H}, (W, H, 1))
arr = np.frombuffer(img, dtype=np.uint8).reshape(H, W, 4)

import pygame
pygame.init()
surf = pygame.image.fromstring(arr.tobytes(), (W, H), 'RGBA')
out = sys.argv[1] if len(sys.argv) > 1 else os.path.join(BASE, 'tests', '_tmp', 'shot_vk_offscreen.png')
pygame.image.save(surf, out)
print("已保存:", out)
