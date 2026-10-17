# -*- coding: utf-8 -*-
"""
vk_player.py — Vulkan 后端播放器 (wgpu-py + GLFW, 2026-08-29 入口化)

中间层 (scene_driver) = 单一数据来源; 本文件 = Vk 后端 窗口/表面/循环:
  run_vk(scene, ...) 可由文员入口/LoomHub/发布链 (game_player) 复用;
  --mini/--keep/--no-shadow/--frames/--stage 为探针能力 (保留).

用法: py -3.12 Loom\vk_player.py <场景.json> [--frames N] [--keep] [--mini]
"""
import os
import sys
import time

os.environ.setdefault('WGPU_BACKEND_TYPE', 'Vulkan')

import math as _math
import numpy as np
import wgpu
from matlib import mat4_view_yaw_pitch, mat4_perspective  # noqa: F401 (探针兼容)

# 中间层 (scene_driver) 为单一数据来源
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import sceneio
from scene_driver import SceneDriver, build_models, build_lights  # noqa: F401

from rendercanvas.glfw import GlfwRenderCanvas
import rendercanvas.glfw

from vk_renderer import VkRenderer


def run_vk(scene=None, frames_n=None, keep=False, mini=False, no_shadow=False,
           stage='p4', width=1280, height=800, title="Loom (Vulkan)",
           scene_data=None):
    """Vk 播放器 (阻塞至窗口关闭/帧数达成). 返回平均 FPS 或 None.
    scene: 明文场景文件路径 (None 时用 scene_data 字典, 游戏包模式)."""
    if scene_data is not None:
        data = scene_data
    elif mini:
        data = _mini_data()
    else:
        if scene is None or not os.path.exists(scene):
            raise FileNotFoundError("场景不存在: %s" % scene)
        data = sceneio.load_scene_data(scene)
    driver = SceneDriver()
    driver.load_from_data(data)
    try:
        from physics_bridge import cv_available as _pb_ok
    except Exception:
        _pb_ok = False
    print("加载 %s: 物体 %d, 相机 target=%s dist=%.1f | 物理后端: %s" %
          (os.path.basename(scene or '<数据>'), len(driver.models),
           driver.target, driver.distance,
           "Culverin (Jolt)" if _pb_ok else "无 (culverin 缺失, 物理禁用)"))

    canvas = GlfwRenderCanvas(size=(width, height), title=title, vsync=False)
    canvas.set_update_mode('fastest')
    adapter = wgpu.gpu.request_adapter_sync(
        canvas=canvas, power_preference='high-performance')
    device = adapter.request_device_sync()
    ctx = canvas.get_wgpu_context()
    fmt = ctx.get_preferred_format(adapter)
    ctx.configure(device=device, format=fmt, usage=wgpu.TextureUsage.RENDER_ATTACHMENT)
    print("设备:", adapter.info['device'], "| format:", fmt)

    renderer = VkRenderer(device, fmt, stage=stage)
    if no_shadow:
        import copy
        driver.lights = [copy.copy(l) for l in driver.lights]
        for l in driver.lights:
            l.shadow = False

    times = []
    t_last = time.perf_counter()
    frame_count = 0
    result = [None]


    def draw():
        nonlocal t_last, frame_count
        frame_count += 1
        now = time.perf_counter()
        times.append(now - t_last)
        t_last = now
        if len(times) > 300:
            times.pop(0)
        if not keep and frames_n and frame_count >= frames_n:
            canvas.close()
            return
        try:
            w, h = ctx.physical_size
            vp, cam_pos = driver.step(1.0 / 60.0, aspect=w / h)
            renderer.draw_frame(ctx, driver.models, driver.lights, vp, cam_pos)
        except BaseException:      # 含 wgpu PanicError (device lost 风暴), 立即终止
            import traceback
            traceback.print_exc()
            print("渲染异常, 终止进程 (防卡死)")
            os._exit(1)
        if len(times) > 30:
            fps = 1.0 / (sum(times[-30:]) / len(times[-30:]))
            canvas.set_title("%s | %.0f FPS" % (title, fps))
            result[0] = fps

    canvas.request_draw(draw)
    import threading
    last_ok = [time.perf_counter()]


    def _heartbeat():
        while True:
            time.sleep(5)
            if time.perf_counter() - last_ok[0] > 60:
                print("watchdog: 渲染无进展 60s, 强制退出 (防卡死)")
                os._exit(9)
    threading.Thread(target=_heartbeat, daemon=True).start()

    try:
        rendercanvas.glfw.loop.run()
    except KeyboardInterrupt:
        pass
    if times:
        t = times[min(10, len(times)):]
        avg = sum(t) / len(t)
        print("\n=== Vk 播放 (物体 %d) | 帧数 %d | %.3f ms/帧 | FPS %.1f ==="
              % (len(driver.models), len(t), avg * 1000, 1.0 / avg))
    return result[0]


def _mini_data():
    """探针最小场景: 1 立方体 + 1 平行光 (shadow=True)."""
    return {
        "version": 10, "materials": [], "cameras": [], "active_camera": None,
        "camera": {"target": [0, 1, 0], "distance": 6.0, "yaw": 0.6,
                   "pitch": -0.35},
        "lights": [{"id": "l1", "name": "太阳", "kind": "directional",
                    "position": [0, 12, 0], "azimuth": 30, "elevation": -55,
                    "roll": 0, "color": [1.0, 1.0, 1.0], "intensity": 1.1,
                    "mode": "full", "shape": "circle", "size": 8.0,
                    "shadow": True}],
        "objects": [{"id": "o1", "name": "立方体", "type": "cube",
                     "params": {"size": 1.0}, "position": [0, 0.5, 0],
                     "rotation": [0.3, 0.6, 0.0], "scale": [1, 1, 1],
                     "color": "#e0804a", "normal_mode": "flat",
                     "saturation": 1.0, "visible": True, "scripts": [],
                     "collider": {"shape": "box", "enabled": True},
                     "rigidbody": None, "audio_source": None,
                     "animator": None}]}


def main():
    args = sys.argv[1:]
    scene = args[0] if args and not args[0].startswith('--') else \
        os.path.join(os.path.dirname(os.path.abspath(__file__)),
                     '保存', '压测50球.json')
    frames_n = None
    stage = 'p4'
    w, h = 1280, 800
    for i, a in enumerate(args):
        if a == '--frames' and i + 1 < len(args):
            frames_n = int(args[i + 1])
        if a == '--stage' and i + 1 < len(args):
            stage = args[i + 1]
        if a == '--size' and i + 1 < len(args):
            w, h = (int(x) for x in args[i + 1].split('x'))
    run_vk(scene, frames_n=frames_n, keep='--keep' in args,
           mini='--mini' in args, no_shadow='--no-shadow' in args,
           stage=stage, width=w, height=h)


if __name__ == '__main__':
    main()
