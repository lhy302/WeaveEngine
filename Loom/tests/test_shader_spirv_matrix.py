# -*- coding: utf-8 -*-
import sys as _sys_utf8
try:
    _sys_utf8.stdout.reconfigure(encoding='utf-8', errors='replace')
    _sys_utf8.stderr.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

# 失败退出码闸门（与既有 test_*.py 同款）：出现 FAIL 开头的行就把退出码改成 1。
import atexit as _atexit_gate
import os as _os_gate
import sys as _sys_gate


class _FailGateStream:
    def __init__(self, stream):
        self._stream = stream
        self.failed = False

    def write(self, text):
        if isinstance(text, str) and (text.startswith('FAIL') or '\nFAIL' in text):
            self.failed = True
        return self._stream.write(text)

    def __getattr__(self, name):
        return getattr(self._stream, name)


_fail_gate = _FailGateStream(_sys_gate.stdout)
_sys_gate.stdout = _fail_gate


@_atexit_gate.register
def _enforce_fail_exit_code():
    if not _fail_gate.failed:
        return
    try:
        _sys_gate.stdout.flush()
        _sys_gate.stderr.flush()
    except Exception:
        pass
    _os_gate._exit(1)


"""test_shader_spirv_matrix.py — SPIR-V 管线矩阵：GLSL -> glslang -> wgpu/naga 能建管线 (2026-11-16)

为什么有这条测试（取代一次性 spike `tools/shader_spike.py`，见未完项清单 D4）：
  T3 的全部结论都建立在「wgpu 0.33 接受 GLSL -> glslang -> SPIR-V」之上，而其中最容易
  再次失守的是**分离采样器 + 比较采样器**（`samplerShadow` / `sampler2DShadow` /
  `samplerCubeShadow`）这条组合：它不是 GLSL 的传统写法，靠「glslang 的 Vulkan 语义」
  与「naga 的验证」两边共同成立。
  这条矩阵当初是**一次性 spike**（`tools/shader_spike.py`，提交 48f0a23 / 0fcf508），
  结论进了产品，却没有任何受跟踪测试守着它 —— 一旦 wgpu/glslang 升级把这条链路打破，
  症状是**运行时建管线失败**（黑帧或整后端回退 GL），而不是编译期报错，代价极高。

本测试锁（需要真实 wgpu 适配器 + glslang，不需要窗口）：
  1. 5 类组合都能从 GLSL 经 glslang 得到 SPIR-V，并被 wgpu 建成 render pipeline：
     shadow2d / shadowcube / cube / 实例属性（vertex）/ 多采样器混合；
  2. **有牙自证**：把比较采样器那一格换成普通 filtering sampler，建管线必须失败 ——
     否则说明本测试的断言在空转（什么都能过 = 什么都没测）；
  3. glslang 走 `tools/shader_spirv.lock` 同一把尺子（版本 16.6.0 + sha256 校验），
     直接复用 `tools/build_shaders.py` 的 `_find_glslang`，不复制第二份版本逻辑。

依赖缺失策略（与像素门同口径：默认失败，显式才跳过）：
  · 缺 glslang / 版本或 sha256 不符 -> FAIL（不静默跳过：T3 构建同样用它）；
  · 没有可用 GPU 适配器 -> FAIL，除非显式 `LOOM_ALLOW_NO_GPU=1`（SKIP）。
"""
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
TOOLS = os.path.join(ROOT, "tools")
for _p in (ROOT, TOOLS):
    if _p not in sys.path:
        sys.path.insert(0, _p)

HEAD = "#version 450\n"

CASES = []


def case(name, src, bgl, vbufs=None, is_vert=False, expect_fail=False):
    """登记一个组合。bgl 元素 = (kind, sub, None)，kind in depth2d/depthcube/tex2d/cube/sampler。"""
    CASES.append({"name": name, "src": src, "bgl": bgl, "vbufs": vbufs or [],
                  "is_vert": is_vert, "expect_fail": expect_fail})


# 1) 2D shadow（分离采样器）：glslang 的阴影纹理也声明成 texture2D，比较器必须显式 samplerShadow
case("shadow2d", HEAD + """
layout(binding = 0) uniform texture2D t;
layout(binding = 1) uniform samplerShadow s;
layout(location = 0) in vec2 v_uv;
layout(location = 0) out vec4 o;
void main() { o = vec4(texture(sampler2DShadow(t, s), vec3(v_uv, 0.5))); }
""", [("depth2d", "comparison", None), ("sampler", "comparison", None)])

# 2) cube shadow
case("shadowcube", HEAD + """
layout(binding = 0) uniform textureCube t;
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
""", [], [("instance", 16), ("instance", 16)], is_vert=True)

# 5) 多采样器（shadow2d + 2d + cube 同在一个 pass 里）
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

# 6) 有牙自证：同一个 shadow2d 源，BGL 故意把比较采样器写成 filtering sampler -> 必须失败
case("neg_bgl_mismatch", HEAD + """
layout(binding = 0) uniform texture2D t;
layout(binding = 1) uniform samplerShadow s;
layout(location = 0) in vec2 v_uv;
layout(location = 0) out vec4 o;
void main() { o = vec4(texture(sampler2DShadow(t, s), vec3(v_uv, 0.5))); }
""", [("depth2d", "comparison", None), ("sampler", "filtering", None)], expect_fail=True)


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
layout(location = 0) out vec2 v_uv;
void main() { v_uv = vec2(0.0); gl_Position = vec4(0.0, 0.0, 0.0, 1.0); }
"""
TRIVIAL_FS = HEAD + """
layout(location = 0) out vec4 o;
void main() { o = vec4(1.0); }
"""


def _glslang():
    """复用 tools/build_shaders.py 的锁定校验（版本 + sha256），不复制第二份版本逻辑。"""
    import build_shaders
    try:
        return build_shaders._find_glslang(build_shaders._load_lock())
    except SystemExit as e:
        print("FAIL glslang 不可用（T3 单源构建同样依赖它）: %s" % e)
        return None


def _compile(device, exe, tmpdir, name, src, suffix):
    path = os.path.join(tmpdir, name + suffix)
    with open(path, "w", encoding="utf-8") as f:
        f.write(src)
    spv = path + ".spv"
    p = subprocess.run([exe, "-V", "--target-env", "vulkan1.1", path, "-o", spv],
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    if p.returncode != 0 or not os.path.isfile(spv):
        msg = ((p.stdout or "") + (p.stderr or "")).strip().splitlines()
        return None, "glslang: " + (msg[-1][:160] if msg else "no output")
    with open(spv, "rb") as fh:
        data = fh.read()
    return device.create_shader_module(code=data), None


def _try_pipeline(device, exe, tmpdir, c, vs_triv, fs_triv):
    """返回 (ok, detail)：ok=True 表示成功建成 render pipeline。"""
    mod, err = _compile(device, exe, tmpdir, c["name"], c["src"],
                        ".vert" if c["is_vert"] else ".frag")
    if mod is None:
        return False, err
    try:
        entries = _bgl_entries(c["bgl"])
        if entries:
            layout = device.create_pipeline_layout(
                bind_group_layouts=[device.create_bind_group_layout(entries=entries)])
        else:
            layout = device.create_pipeline_layout(bind_group_layouts=[])
        if c["is_vert"]:
            # 每个 instance buffer 一条属性，location 必须按 buffer 序号递增
            # （着色器里 inst_a=location 0、inst_b=location 1）；写死 0 会撞 location
            buffers = [{"array_stride": stride, "step_mode": "instance",
                        "attributes": [{"shader_location": i, "offset": 0,
                                        "format": "float32x4"}]}
                       for i, (_mode, stride) in enumerate(c["vbufs"])]
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
        return True, "SPIR-V 通过 naga，管线已建"
    except Exception as e:  # _broad_, wgpu/naga 校验失败没有统一异常类型（RuntimeError/ValidationError/ValueError 都用过），只能宽兜住再判定
        return False, "naga 管线: " + " ".join(str(e).split())[:220]


def main():
    ok = True
    exe = _glslang()
    if exe is None:
        return 1

    import wgpu
    adapter = wgpu.gpu.request_adapter_sync(power_preference="high-performance")
    if adapter is None:
        if os.environ.get("LOOM_ALLOW_NO_GPU") == "1":
            print("SKIP 无可用 GPU 适配器（LOOM_ALLOW_NO_GPU=1 显式允许）")
            return 0
        print("FAIL 无可用 GPU 适配器（需要 wgpu 能拿到适配器；显式跳过请设 LOOM_ALLOW_NO_GPU=1）")
        return 1
    device = adapter.request_device_sync()

    tmpdir = tempfile.mkdtemp(prefix="loom_spv_matrix_")
    vs_triv, e1 = _compile(device, exe, tmpdir, "trivial_vs", TRIVIAL_VS, ".vert")
    fs_triv, e2 = _compile(device, exe, tmpdir, "trivial_fs", TRIVIAL_FS, ".frag")
    if vs_triv is None or fs_triv is None:
        print("FAIL 平凡顶点/片段着色器都没能建模块: %s / %s" % (e1, e2))
        return 1

    rows = []
    for c in CASES:
        built, detail = _try_pipeline(device, exe, tmpdir, c, vs_triv, fs_triv)
        if c["expect_fail"]:
            good = not built
            verdict = "OK" if good else "FAIL"
            note = ("按预期被拒绝：" + detail) if good else ("**没有**被拒绝（断言空转）: " + detail)
        else:
            good = built
            verdict = "OK" if good else "FAIL"
            note = detail
        if not good:
            ok = False
        rows.append((c["name"], verdict, note))

    print("%-18s %-5s %s" % ("case", "结果", "说明"))
    print("-" * 78)
    for n, r, d in rows:
        print("%-18s %-5s %s" % (n, r, d))
    print("-" * 78)
    pos = [r for r in rows if not any(c["name"] == r[0] and c["expect_fail"] for c in CASES)]
    neg = [r for r in rows if any(c["name"] == r[0] and c["expect_fail"] for c in CASES)]
    print("正向 %d/%d 建管线成功；反向 %d/%d 被正确拒绝"
          % (sum(1 for r in pos if r[1] == "OK"), len(pos),
             sum(1 for r in neg if r[1] == "OK"), len(neg)))
    print("test_shader_spirv_matrix:", "ALL PASS" if ok else "HAS FAILURES")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
