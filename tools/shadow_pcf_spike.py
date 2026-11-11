# -*- coding: utf-8 -*-
"""shadow_pcf_spike.py — T3c-4 对拍 spike（不改生产代码）：

GL 现状 = 9 次 sampler2DShadow 硬件比较（filter=LINEAR，硬件做 2x2 双线性比较）。
候选① = 原始深度 + 手工比较（= VK 算法）；等价性取决于「硬件双线性比较」vs「最近邻比较」。
本探针用同一 9 次采样、只把阴影贴图 filter 从 LINEAR 改成 NEAREST，量化这两者的像素差：
  · 若 MAE 明显 > 0，说明 option ① 不可能「逐字一致」，必须重生成参考图（或走 option ②）。
用法: py -3.13 tools/shadow_pcf_spike.py
"""
import os
import sys
import time

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "Loom"))
sys.path.insert(0, os.path.join(ROOT, "Loom", "tests"))
os.environ.setdefault("LOOM_NO_PARALLEL", "1")
os.environ["LOOM_NO_SAVE_MIGRATE"] = "1"

import moderngl
import editor as editor_mod
import sceneio
import test_ab_gl_vk as AB


def build(scene_name):
    data = AB._load_scene(os.path.join(AB.SCENES_DIR, scene_name))
    ctx = moderngl.create_standalone_context(require=430)
    rb = ctx.renderbuffer((AB.W, AB.H), components=4)
    drb = ctx.depth_renderbuffer((AB.W, AB.H))
    fbo = ctx.framebuffer(color_attachments=[rb], depth_attachment=drb)
    ed = editor_mod.EditorApp(AB.W, AB.H, view=AB._NullView(), ctx=ctx)
    ed._external_fb = fbo
    ed.show_grid = False
    ed.selected_index = ed.selected_light_index = ed.selected_camera_index = -1
    ed.clear_scene() if hasattr(ed, "clear_scene") else (ed.models.clear(), ed.lights.clear())
    sceneio.scene_from_dict(ed, data, base_dir=AB.SCENES_DIR)
    cam = data.get("camera") or {}
    ed.camera_target = tuple(cam.get("target", (0, 0, 0)))
    ed.camera_distance = float(cam.get("distance", 10.0))
    ed.camera_yaw = float(cam.get("yaw", 0.6))
    ed.camera_pitch = float(cam.get("pitch", -0.35))
    ed.orbit_mode = True
    ed.apply_orbit_camera()
    return ctx, fbo, ed


def shoot(fbo):
    raw = fbo.read(components=3)
    img = np.frombuffer(raw, dtype="u1").reshape(AB.H, AB.W, 3).astype(np.float32) / 255.0
    return np.flipud(img)


def shadow_textures(ed):
    out = []
    for sm in getattr(ed, "_shadow_maps", {}).values():
        for t in sm.get("tex", ()):
            out.append(t)
    return out


def main():
    import moderngl as mgl
    os.makedirs(os.path.join(ROOT, "Loom", "tests", "_tmp"), exist_ok=True)
    rows = []
    for scene in ("ab_c_dir_shadow.json", "ab_point_shadow.json", "ab_scene.json"):
        ctx, fbo, ed = build(scene)
        for _ in range(3):
            ed.render(1 / 60.0)
        base = shoot(fbo)
        texs = shadow_textures(ed)
        for t in texs:
            t.filter = (mgl.NEAREST, mgl.NEAREST)
        for _ in range(2):
            ed.render(1 / 60.0)
        near = shoot(fbo)
        mae = float(np.abs(base - near).mean())
        ref = AB._load_png(os.path.join(AB.REF_DIR_NEXT, scene.replace(".json", ".png")))
        mae_ref = float(np.abs(base - ref).mean())
        # 裁图: 取差异最大的 160x160 区域
        d = np.abs(base - near).mean(axis=2)
        cy, cx = np.unravel_index(int(np.argmax(d)), d.shape)
        y0 = max(0, min(AB.H - 160, cy - 80))
        x0 = max(0, min(AB.W - 160, cx - 80))
        tag = scene.replace(".json", "")
        p1 = os.path.join(ROOT, "Loom", "tests", "_tmp", "pcf_%s_linear.png" % tag)
        p2 = os.path.join(ROOT, "Loom", "tests", "_tmp", "pcf_%s_nearest.png" % tag)
        from PIL import Image
        Image.fromarray((base[y0:y0 + 160, x0:x0 + 160] * 255).astype("uint8")).save(p1)
        Image.fromarray((near[y0:y0 + 160, x0:x0 + 160] * 255).astype("uint8")).save(p2)
        # 帧时间: 同一路径各 60 帧
        def bench():
            t0 = time.perf_counter()
            for _ in range(60):
                ed.render(1 / 60.0)
            return (time.perf_counter() - t0) / 60.0 * 1000.0
        t_lin = bench()
        for t in texs:
            t.filter = (mgl.LINEAR, mgl.LINEAR)
        t_near = bench()
        rows.append((scene, mae_ref, mae, len(texs), t_lin, t_near))
        print("%-22s GL/ref=%.6f  linear-vs-nearest MAE=%.6f  阴影贴图=%d 帧时 %.2f/%.2f ms"
              % (scene, mae_ref, mae, len(texs), t_lin, t_near))
    print("裁图: Loom/tests/_tmp/pcf_<scene>_{linear,nearest}.png")
    return 0


if __name__ == "__main__":
    sys.exit(main())
