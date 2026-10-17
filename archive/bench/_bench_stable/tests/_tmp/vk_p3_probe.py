# -*- coding: utf-8 -*-
"""vk_p3_probe.py — P3 脚本步进验证 (SceneDriver bob 双帧运动差分, 2026-08-29).

加载压测场景 + 前 10 球换 bob 脚本 → driver 步进 → 两时刻各渲染一帧,
逐像素差分证明"脚本驱动物体运动"在 Vk 链路生效.
用法: py -3.12 tests\_tmp\vk_p3_probe.py
"""
import os
import sys
import math
os.environ['WGPU_BACKEND_TYPE'] = 'Vulkan'

import numpy as np
import wgpu

BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, BASE)

import sceneio
import scene_driver
from scene_driver import SceneDriver
from vk_renderer import VkRenderer
from matlib import mat4_view_yaw_pitch, mat4_perspective

W, H = 800, 600
scene = os.path.join(BASE, '保存', '压测50球.json')
data = sceneio.load_scene_data(scene)
# 前 10 个球改挂 bob (幅度 1.0, 频率 1.0) —— 上下浮动可截图差分
for obj in data['objects']:
    if obj.get('name', '').startswith('球'):
        idx = int(obj['name'][1:])
        if idx < 10:
            obj['scripts'] = [{"id": "bob", "vars": {"amp": 1.0, "freq": 1.0}}]

drv = SceneDriver(data)

dev = wgpu.gpu.request_adapter_sync(power_preference='high-performance')
device = dev.request_device_sync()
tex = device.create_texture(size=(W, H, 1), format='rgba8unorm',
                            usage=wgpu.TextureUsage.RENDER_ATTACHMENT
                            | wgpu.TextureUsage.COPY_SRC)


class Ctx:
    physical_size = (W, H)
    def get_current_texture(self):
        return tex


r = VkRenderer(device, 'rgba8unorm')


def render_at(seconds):
    drv = SceneDriver(data)          # 干净实例 (脚本惰性实例从 t=0 起)
    vp, cam_pos = drv.step(0.0, aspect=W / H)   # t=0 第一帧 (脚本 on_start)
    acc = 0.0
    while acc < seconds:            # 步进到目标时刻
        acc += 1.0 / 120.0
        vp, cam_pos = drv.step(1.0 / 120.0, aspect=W / H)
    r.draw_frame(Ctx(), drv.models, drv.lights, vp, cam_pos)
    img = device.queue.read_texture(
        {"texture": tex, "mip_level": 0, "aspect": wgpu.TextureAspect.all},
        {"bytes_per_row": W * 4, "rows_per_image": H}, (W, H, 1))
    return np.frombuffer(img, dtype=np.uint8).reshape(H, W, 4).astype(np.float32)


a = render_at(0.0)     # bob t≈0 (sin 0 = 基位)
b = render_at(0.28)    # t≈0.28s → sin(0.28*2π)≈0.93 → 球抬升 ~0.93
diff = np.abs(a - b)[:, :, :3].max(axis=2)
moved = (diff > 20).sum()
print("bob 差分: 变化像素=%d (0=未动 失败/大=脚本驱动生效)" % moved)
print("差分质心 (y,x)=%.0f,%.0f (bob 球阵应在上方区域 y<420)" %
      tuple(np.unravel_index(np.argmax(diff), diff.shape)) if moved else "无")

# 保存两帧 (供人工复核)
import pygame
pygame.init()
for name, arr in (('vk_p3_t0', a), ('vk_p3_t28', b)):
    s = pygame.image.fromstring(arr.astype(np.uint8).tobytes(), (W, H), 'RGBA')
    pygame.image.save(s, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                      name + '.png'))
print("帧已保存 (tests/_tmp/vk_p3_t0.png / vk_p3_t28.png)")
