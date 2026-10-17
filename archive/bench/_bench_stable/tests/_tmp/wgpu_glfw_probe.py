# -*- coding: utf-8 -*-
"""wgpu_glfw_probe.py — GLFW 表面 (swapchain 呈现) 最小验证 (2026-08-28).

旋风三角形渲染到 GLFW 窗口 (wgpu Vulkan surface):
  - request_adapter_sync(canvas=...) 按 surface 选适配器
  - configure swapchain -> 每帧 get_current_texture -> render pass 提交 -> present
  - 统计 FPS (vsync=False, 无上限) + 每帧 CPU 侧的提交耗时
用法: py -3.12 tests\_tmp\wgpu_glfw_probe.py
"""
import os
os.environ['WGPU_BACKEND_TYPE'] = 'Vulkan'
import sys
import time
import wgpu
from rendercanvas.glfw import GlfwRenderCanvas
import rendercanvas.glfw

W, H = 1024, 768
N_FRAMES = 400

canvas = GlfwRenderCanvas(size=(W, H), title="wgpu-vk surface probe", vsync=False)
canvas.set_update_mode("fastest")      # 持续调度: 每帧尽速绘制 (不等待)

adapter = wgpu.gpu.request_adapter_sync(
    canvas=canvas, power_preference='high-performance')
info = adapter.info
print("适配器:", info['device'], "|", info['backend_type'])
device = adapter.request_device_sync()

ctx = canvas.get_wgpu_context()
fmt = ctx.get_preferred_format(adapter)
ctx.configure(device=device, format=fmt, usage=wgpu.TextureUsage.RENDER_ATTACHMENT)
print("surface 格式:", fmt)

shader = device.create_shader_module(code="""
struct VSOut { @builtin(position) pos: vec4f, }
@vertex fn vs(@builtin(vertex_index) vi: u32) -> VSOut {
    var p = array<vec2f, 3>(vec2f(-1.,-1.), vec2f(1.,-1.), vec2f(-1.,1.));
    var o: VSOut;
    o.pos = vec4f(p[vi], 0., 1.);
    return o;
}
@fragment fn fs(@builtin(position) p: vec4f) -> @location(0) vec4f {
    let t = p.x / 1024.0;
    return vec4f(t, 0.4, 0.7, 1.0);
}
""")
pipe = device.create_render_pipeline(
    layout=device.create_pipeline_layout(bind_group_layouts=[]),
    vertex={"module": shader, "entry_point": "vs"},
    fragment={"module": shader, "entry_point": "fs",
              "targets": [{"format": fmt}]})
# 帧时间环形缓冲 (最近 120 帧均值)
times = []
t_last = time.perf_counter()


def draw():
    global t_last
    now = time.perf_counter()
    times.append(now - t_last)
    t_last = now
    if len(times) > 120:
        times.pop(0)
    tex = ctx.get_current_texture()
    view = tex.create_view()
    enc = device.create_command_encoder()
    rp = enc.begin_render_pass(color_attachments=[
        {"view": view, "load_op": wgpu.LoadOp.clear, "clear_value": (0.1, 0.1, 0.13, 1.0),
         "store_op": wgpu.StoreOp.store}])
    rp.set_pipeline(pipe)
    rp.draw(3, 1, 0, 0)
    rp.end()
    device.queue.submit([enc.finish()])   # 呈现由 rendercanvas draw 返回后自动做
    if len(times) >= 30:
        fps = 1.0 / (sum(times[-30:]) / 30)
        canvas.set_title("wgpu-vk | %.0f FPS | 近30帧均 %.2f ms" % (fps, sum(times[-30:]) / 30 * 1000))
    # 固定帧数后自动关闭; keep 模式窗口留着 (供截图/观察, Ctrl+C 退出)
    if len(times) >= N_FRAMES:
        if len(sys.argv) > 1 and sys.argv[1] == 'keep':
            canvas.set_title("done - 保持窗口 (截图用)")
            times.clear()
        else:
            canvas.close()


canvas.request_draw(draw)
try:
    rendercanvas.glfw.loop.run()   # 阻塞至窗口关闭 (draw 里 N_FRAMES 帧后 close)
except KeyboardInterrupt:
    pass

if times:
    t = times[min(10, len(times)):]   # 去掉启动前 10 帧
    avg = sum(t) / len(t)
    print("\n=== GLFW 表面验证 ===")
    print("有效帧数: %d | 平均帧时间 %.3f ms | FPS %.1f" % (len(t), avg * 1000, 1.0 / avg))
    print("window size:", canvas.get_physical_size())
    """确认: surface 呈现成功 == 窗口标题无错 + 帧时间正常"""
