# -*- coding: utf-8 -*-
"""shader_spike.py — T3a Phase-2 Step A：naga 对「分离采样器风格 GLSL -> SPIR-V」的兼容性探针。

只写探针，不改生产代码。每项：glslang 编译 -> wgpu create_shader_module -> create_render_pipeline，
记录 OK/FAIL 与原因。用法: py -3.13 tools/shader_spike.py
"""
import os
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GLSLANG = os.environ.get("LOOM_GLSLANG", r"C:\loom_build\shadertools\bin\glslang.exe")

HEAD = "#version 450\n"

CASES = []


def case(name, frag, bgl, vbufs=None):
    CASES.append((name, frag, bgl, vbufs or []))


# 1) 2D shadow（分离采样器）
case("shadow2d", HEAD + """
layout(binding = 0) uniform texture2D t;   // glslang: 阴影纹理也用 texture2D
layout(binding = 1) uniform samplerShadow s;   // 比较采样器必须显式声明
layout(location = 0) in vec2 v_uv;
layout(location = 0) out vec4 o;
void main() { o = vec4(texture(sampler2DShadow(t, s), vec3(v_uv, 0.5))); }
""", [("depth2d", "comparison", None), ("sampler", "comparison", None)])

# 2) cube shadow
case("shadowcube", HEAD + """
layout(binding = 0) uniform textureCube t;   // 立方体阴影同样用 textureCube
layout(binding = 1) uniform samplerShadow s;
layout(location = 0) in vec2 v_uv;
layout(location = 0) out vec4 o;
void main() { o = vec4(texture(samplerCubeShadow(t, s), vec4(v_uv, 0.0, 0.5))); }
""", [("depthcube", "comparison", None), ("sampler", "comparison", None)])

# 3) 普通 cube
case("cube", HEAD + """
layout(binding = 0) uniform textureCube t;
layout(binding = 1) uniform sampler s;
layout(location = 0) in vec2 v_uv;
layout(location = 0) out vec4 o;
void main() { o = vec4(texture(samplerCube(t, s), vec3(v_uv, 1.0)).rgb, 1.0); }
""", [("cube", "float", None), ("sampler", "filtering", None)])

# 4) 实例属性（vertex）
case("inst_attr", HEAD + """
layout(location = 0) in vec4 inst_a;
layout(location = 1) in vec4 inst_b;
layout(location = 0) out vec4 o;
void main() { o = inst_a + inst_b; gl_Position = vec4(0.0, 0.0, 0.0, 1.0); }
""", [], [("instance", 16), ("instance", 16)])

# 5) 多采样器（shadow2d + 2d + cube）
case("multi_sampler", HEAD + """
layout(binding = 0) uniform texture2D sh;
layout(binding = 1) uniform texture2D t2;
layout(binding = 2) uniform textureCube tc;
layout(binding = 3) uniform samplerShadow ss;
layout(binding = 4) uniform sampler s;
layout(location = 0) in vec2 v_uv;
layout(location = 0) out vec4 o;
void main() {
    float d = texture(sampler2DShadow(sh, ss), vec3(v_uv, 0.5));
    vec3 a = texture(sampler2D(t2, s), v_uv).rgb;
    vec3 b = texture(samplerCube(tc, s), vec3(v_uv, 1.0)).rgb;
    o = vec4(a + b + d, 1.0);
}
""", [("depth2d", "comparison", None), ("tex2d", "float", None),
      ("cube", "float", None), ("sampler", "comparison", None),
      ("sampler", "filtering", None)])


def _bgl_entries(bgl):
    out = []
    for i, (kind, sub, _unused) in enumerate(bgl):
        if kind == "depth2d":
            out.append({"binding": i, "visibility": "FRAGMENT",
                        "texture": {"sample_type": "depth", "view_dimension": "2d"}})
        elif kind == "depthcube":
            out.append({"binding": i, "visibility": "FRAGMENT",
                        "texture": {"sample_type": "depth", "view_dimension": "cube"}})
        elif kind == "tex2d":
            out.append({"binding": i, "visibility": "FRAGMENT",
                        "texture": {"sample_type": "float", "view_dimension": "2d"}})
        elif kind == "cube":
            out.append({"binding": i, "visibility": "FRAGMENT",
                        "texture": {"sample_type": "float", "view_dimension": "cube"}})
        elif kind == "sampler":
            out.append({"binding": i, "visibility": "FRAGMENT",
                        "sampler": {"type": "comparison" if sub == "comparison" else "filtering"}})
    return out


TRIVIAL_VS = HEAD + """
layout(location = 0) out vec2 v_uv;   // 与片段输入的 location 0 对齐
void main() { v_uv = vec2(0.0); gl_Position = vec4(0.0, 0.0, 0.0, 1.0); }
"""
TRIVIAL_FS = HEAD + """
layout(location = 0) out vec4 o;
void main() { o = vec4(1.0); }
"""


def _compile(device, tmpdir, name, src, suffix):
    path = os.path.join(tmpdir, name + suffix)
    with open(path, "w", encoding="utf-8") as f:
        f.write(src)
    spv = path + ".spv"
    p = subprocess.run([GLSLANG, "-V", "--target-env", "vulkan1.1", path, "-o", spv],
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    if p.returncode != 0 or not os.path.isfile(spv):
        return None, "glslang: " + ((p.stdout or "") + (p.stderr or "")).strip().splitlines()[-1][:100]
    with open(spv, "rb") as fh:
        data = fh.read()
    return device.create_shader_module(code=data), None


def main():
    import wgpu
    adapter = wgpu.gpu.request_adapter_sync(power_preference="high-performance")
    device = adapter.request_device_sync()
    tmpdir = tempfile.mkdtemp(prefix="loom_spike_")
    rows = []
    vs_triv, vs_err = _compile(device, tmpdir, "trivial_vs", TRIVIAL_VS, ".vert")
    fs_triv, fs_err = _compile(device, tmpdir, "trivial_fs", TRIVIAL_FS, ".frag")
    for name, src, bgl, vbufs in CASES:
        is_vert = name.endswith("inst_attr")
        mod, err = _compile(device, tmpdir, name, src, ".vert" if is_vert else ".frag")
        if mod is None:
            rows.append((name, "FAIL", err))
            continue
        data = b""
        try:
            entries = _bgl_entries(bgl)
            if entries:
                bglayout = device.create_bind_group_layout(entries=entries)
                layout = device.create_pipeline_layout(bind_group_layouts=[bglayout])
            else:
                layout = device.create_pipeline_layout(bind_group_layouts=[])
            if is_vert:
                buffers = [{"array_stride": stride, "step_mode": "instance",
                            "attributes": [{"shader_location": i, "offset": 0,
                                            "format": "float32x4"}]}
                           for i, (mode, stride) in enumerate(vbufs)]
                device.create_render_pipeline(
                    layout=layout,
                    vertex={"module": mod, "entry_point": "main", "buffers": buffers},
                    primitive={"topology": "triangle-list"},
                    fragment={"module": fs_triv, "entry_point": "main",
                              "targets": [{"format": "rgba8unorm"}]})
            else:
                device.create_render_pipeline(
                    layout=layout,
                    vertex={"module": vs_triv, "entry_point": "main", "buffers": []},
                    primitive={"topology": "triangle-list"},
                    fragment={"module": mod, "entry_point": "main",
                              "targets": [{"format": "rgba8unorm"}]})
            rows.append((name, "OK", "SPIR-V 通过 naga"))
        except Exception as e:
            rows.append((name, "FAIL", "naga 管线: " + " ".join(str(e).split())[:220]))
    print("%-14s %-5s %s" % ("case", "结果", "说明"))
    for n, r, d in rows:
        print("%-14s %-5s %s" % (n, r, d))
    return 0 if all(r == "OK" for _n, r, _d in rows) else 1


if __name__ == "__main__":
    sys.exit(main())
