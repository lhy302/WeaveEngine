# -*- coding: utf-8 -*-
"""wgpu_vk_probe.py — Vulkan 后端最小链路验证 (2026-08-28 性能调优启动).

验证 1050Ti + Windows 10 + Python 3.12 + wgpu-py:
  1. WGPU_BACKEND_TYPE=Vulkan 强制后端, request_adapter 拿到 GPU 适配器
  2. request_device 成功
  3. 最小 compute: WGSL 写 buffer -> map 读回 (GPU 侧执行链路, 不碰窗口)
  4. 最小 render: 128x128 offscreen 纹理画红色 (无窗口, 纯 GPU 渲染验证)
用法: py -3.12 tests\_tmp\wgpu_vk_probe.py
"""
import os
import sys

os.environ['WGPU_BACKEND_TYPE'] = 'Vulkan'   # 强制 Vulkan 后端 (Metal/DX12 不适用)

import wgpu


def main():
    print("wgpu-py", wgpu.__version__)
    # ---- 1. 适配器 ----
    adapter = wgpu.gpu.request_adapter_sync(power_preference='high-performance')
    if adapter is None:
        print("FAIL: 无适配器 (Vulkan 驱动问题?)")
        sys.exit(1)
    info = adapter.info          # 0.32 起是 dict 风格 (vendor/device/backend_type...)
    print("适配器: %s | backend=%s | type=%s"
          % (info['device'], info['backend_type'], info['adapter_type']))

    # ---- 2. 设备 ----
    device = adapter.request_device_sync()
    print("设备:", device)

    # ---- 3. compute: WGSL 写 buffer 并读回 ----
    buf = device.create_buffer(
        size=64, usage=wgpu.BufferUsage.STORAGE | wgpu.BufferUsage.COPY_DST
        | wgpu.BufferUsage.COPY_SRC)
    code = """
@group(0) @binding(0) var<storage, read_write> out_: array<u32>;
@compute @workgroup_size(16)
fn main(@builtin(global_invocation_id) gid: vec3u) {
    let i: u32 = gid.x;
    out_[i] = i * 2u + 7u;
}
"""
    shader = device.create_shader_module(code=code)
    bind = device.create_bind_group_layout(entries=[
        {"binding": 0, "visibility": wgpu.ShaderStage.COMPUTE,
         "buffer": {"type": "storage"}}])
    pl = device.create_pipeline_layout(bind_group_layouts=[bind])
    place = device.create_compute_pipeline(layout=pl,
        compute={"module": shader, "entry_point": "main"})
    bgl = device.create_bind_group(layout=bind, entries=[
        {"binding": 0, "resource": {"buffer": buf, "offset": 0, "size": 64}}])
    enc = device.create_command_encoder()
    pass_ = enc.begin_compute_pass()
    pass_.set_pipeline(place)
    pass_.set_bind_group(0, bgl, [], 0, 1)
    pass_.dispatch_workgroups(4, 1, 1)   # 4 组 * 16 = 64 线程 = 64 u32
    pass_.end()
    device.queue.submit([enc.finish()])
    data = device.queue.read_buffer(buf, 0, 64)
    vals = [int.from_bytes(data[i * 4:i * 4 + 4], 'little') for i in range(4)]
    ok = vals == [7, 9, 11, 13]
    print("compute 写buffer读回: %s (%s)" % (vals if ok else vals, "OK" if ok else "FAIL"))
    if not ok:
        sys.exit(1)

    # ---- 4. offscreen render: 128x128 画纯色 ----
    tex = device.create_texture(
        size=(128, 128, 1), usage=wgpu.TextureUsage.RENDER_ATTACHMENT
        | wgpu.TextureUsage.COPY_SRC,
        format=wgpu.TextureFormat.rgba8unorm)
    rsh = device.create_shader_module(code="""
struct VSOut { @builtin(position) pos: vec4f, }
@vertex fn vs(@builtin(vertex_index) vi: u32) -> VSOut {
    var p = array<vec2f, 3>(vec2f(-1,-1), vec2f(3,-1), vec2f(-1,3));
    var o: VSOut;
    o.pos = vec4f(p[vi], 0., 1.);
    return o;
}
@fragment fn fs() -> @location(0) vec4f { return vec4f(1., 0., 0., 1.); }
""")
    rpl = device.create_render_pipeline(
        layout=device.create_pipeline_layout(bind_group_layouts=[]),
        vertex={"module": rsh, "entry_point": "vs"},
        fragment={"module": rsh, "entry_point": "fs",
                  "targets": [{"format": wgpu.TextureFormat.rgba8unorm}]})
    view = tex.create_view()
    enc = device.create_command_encoder()
    rp = enc.begin_render_pass(
        color_attachments=[{"view": view, "clear_value": (0, 0, 0, 1),
                            "load_op": wgpu.LoadOp.clear, "store_op": wgpu.StoreOp.store}])
    rp.set_pipeline(rpl)
    rp.draw(3, 1, 0, 0)
    rp.end()
    device.queue.submit([enc.finish()])
    img = device.queue.read_texture(
        {"texture": tex, "mip_level": 0, "aspect": wgpu.TextureAspect.all},
        {"bytes_per_row": 512, "rows_per_image": 128},
        (128, 128, 1))                  # 0.32 返回 memoryview
    px = bytes(img[0 * 4:4])            # 第一像素 RGBA
    ok2 = px == bytes([255, 0, 0, 255])
    print("offscreen 画红: 像素=%s (%s)" % (tuple(px), "OK" if ok2 else "FAIL"))
    if not ok2:
        sys.exit(1)

    print("\n=== Vulkan 链路全部验证通过 ===")


if __name__ == '__main__':
    main()
