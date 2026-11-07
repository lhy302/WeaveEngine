# -*- coding: utf-8 -*-
import sys as _sys_utf8
try:
    _sys_utf8.stdout.reconfigure(encoding='utf-8', errors='replace')
    _sys_utf8.stderr.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

# 2026-11-06 失败退出码闸门 (与既有 test_*.py 同款): 出现 "FAIL" 开头的行就把
# 进程退出码改成 1, 全 PASS 时行为完全不变。
import atexit as _atexit_gate
import os as _os_gate
import sys as _sys_gate


class _FailGateStream:
    def __init__(self, stream):
        self._stream = stream
        self.failed = False

    def write(self, text):
        if isinstance(text, str) and (text.startswith("FAIL") or "\nFAIL" in text):
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

"""test_vk_two_dir_shadow.py — VK 双平行光阴影贴图槽位分配 (2026-11-07)

缺陷 (vk_renderer 旧已知限制): VK 只有 1 张平行光阴影贴图, 第 2 盏开阴影的平行光
静默无阴影 (旧实现甚至拿第 1 盏的贴图做 PCF, 阴影位置错).

修法: 第二张 1024² 贴图 + binding 10/11 (仍在同一个完整 bind group 里);
主着色器用 LightX.params.w 传槽位号 (0/1, -1=无贴图) 分支选 t_shadow/t_shadow2;
阴影 pass 按槽位各烘一张; 第 3 盏及以后不分配槽位并只警告一次.

本测试锁 (纯 CPU, 不需要 GPU/窗口):
  A. 布局/着色器静态面: _SHADOW_SLOTS=2; 主 BGL 新增 binding 10 (2d r32 采样)
     与 11 (non-filtering sampler), 且主管线仍只用一个 bind group 布局;
     着色器有 t_shadow2/pcf2 + params.w 分支, 不引入动态纹理数组索引.
  B. 2 盏投影平行光: guid -> 槽位 0/1, 不告警; _pack_scene 的 params.w = 0/1.
  C. 第 3 盏: 不分配槽位 (params.w=-1) 且只打印一次"阴影已知限制"警告;
     前两盏槽位不变, 第 3 盏的 VP 仍保留 (beam 截面要用 ortho).
  D. 单盏投影平行光: 槽位 0, 不告警 (既有场景行为不变).
  E. 点光: 仍只烘第一盏 (第二盏无阴影 + 警告一次), 不占平行光槽位.
"""
import contextlib
import inspect
import io
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

import numpy as np                                  # noqa: E402

import vk_renderer as VR                            # noqa: E402

_fails = []


def check(name, cond, detail=""):
    print(("PASS " if cond else "FAIL ") + name + ("  " + str(detail) if detail else ""))
    if not cond:
        _fails.append(name)


# ============ A. 布局/着色器静态面 ============
print("=" * 60)
print("A. 布局/着色器静态面 (binding 10/11 + params.w 槽位选择)")
print("=" * 60)


class _FakeDevice:
    """只记录 bind group layout / pipeline layout 的假 device (无 GPU)。"""

    def __init__(self):
        self.bgls = []
        self.pipeline_layouts = []
        self.pipelines = 0

    def create_shader_module(self, code=None):
        return {'code': code}

    def create_bind_group_layout(self, entries=None):
        self.bgls.append(entries)
        return ('bgl', len(self.bgls) - 1)

    def create_pipeline_layout(self, bind_group_layouts=None):
        self.pipeline_layouts.append(list(bind_group_layouts or []))
        return ('pl', len(self.pipeline_layouts) - 1)

    def create_render_pipeline(self, **kw):
        self.pipelines += 1
        return ('pipe', self.pipelines)

    def create_buffer(self, **kw):
        return ('buf',)

    def create_bind_group(self, **kw):
        return ('group',)


check("A1 平行光阴影槽位数 = 2", VR._SHADOW_SLOTS == 2, VR._SHADOW_SLOTS)
dev = _FakeDevice()
VR.VkRenderer(dev, 'rgba8unorm')                # 只跑 _build_pipelines (无 GPU 调用)
main_bgl = dev.bgls[0]
entries = {int(e['binding']): e for e in main_bgl}
check("A2 主 BGL 绑定集合 = 0/1/2/3/5/6/7/8/9/10/11",
      set(entries) == {0, 1, 2, 3, 5, 6, 7, 8, 9, 10, 11}, sorted(entries))
check("A3 binding 10 = 2d unfilterable-float 纹理",
      entries[10].get('texture') == {'sample_type': 'unfilterable-float',
                                     'view_dimension': '2d'},
      entries[10])
check("A4 binding 11 = non-filtering 采样器",
      entries[11].get('sampler') == {'type': 'non-filtering'}, entries[11])
check("A5 主管线仍只绑 1 个完整 bind group (未新增组)",
      len(dev.pipeline_layouts[0]) == 1, dev.pipeline_layouts[0])
frag = VR._MAIN_FRAG
check("A6 着色器声明 t_shadow2 / s_shadow2 (binding 10/11)",
      '@binding(10) var t_shadow2' in frag and '@binding(11) var s_shadow2' in frag)
check("A7 槽位 1 有独立 pcf2 (不动态选纹理)",
      'fn pcf2(' in frag and 'textureSample(t_shadow2, s_shadow2' in frag)
check("A8 按 params.w 分支选贴图",
      'L.params.w < -0.5' in frag and 'L.params.w < 0.5' in frag)
check("A9 无动态纹理数组索引 (textureSample 下标写法不存在)",
      'textureSample(t_shadow[' not in frag and 'textureSample(t_shadow2[' not in frag)
check("A10 _pack_scene 写 params.w 槽位 (源码含 _dir_shadow_slots)",
      '_dir_shadow_slots' in inspect.getsource(VR.VkRenderer._pack_scene))
check("A11 阴影 pass 按槽位各烘一张 (源码含 _dir_shadow_bufs/_shadow_view2)",
      '_dir_shadow_bufs' in inspect.getsource(VR.VkRenderer.draw_frame)
      and '_shadow_view2' in inspect.getsource(VR.VkRenderer.draw_frame))


# ============ 灯桩 ============
class _Vec:
    def __init__(self, x, y, z):
        self.x, self.y, self.z = x, y, z


class _FakeLight:
    def __init__(self, guid, kind='directional', shadow=True,
                 direction=(-0.3, -1.0, -0.2)):
        self.guid = guid
        self.kind = kind
        self.shadow = shadow
        self.mode = 'full'
        self.shape = 'circle'
        self.size = 5.0
        self.color = (1.0, 1.0, 1.0)
        self.intensity = 1.0
        self.range = 12.0
        self.spot_inner_angle = 30.0
        self.spot_outer_angle = 60.0
        self.direction = _Vec(*direction)
        self.position = _Vec(0.0, 5.0, 0.0)

    def up_vector(self):
        return _Vec(0.0, 1.0, 0.0)


_EYE = np.eye(4, dtype=np.float32)
_NONE_WORLDS = np.zeros((0, 4, 4), dtype=np.float32)


def _renderer():
    r = VR.VkRenderer.__new__(VR.VkRenderer)      # 绕过 __init__ 的 GPU 资源创建
    r._dir_light_vp = lambda light, worlds, vis: _EYE
    r._light_vps = {}
    r._dir_shadow_slots = {}
    return r


def _params_w(buf, i):
    return float(buf[VR._R_L0 + i * VR._LIGHT_F32 + 35])


def _extra_w(buf, i):
    return float(buf[VR._R_L0 + i * VR._LIGHT_F32 + 39])


def _pack(r, lights):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        r._pack_light_vps(lights, [], _NONE_WORLDS)
        scene = r._pack_scene(_EYE, lights, (0.0, 0.0, 0.0))
    return scene, buf.getvalue()


# ============ B. 2 盏投影平行光 ============
print("=" * 60)
print("B. 2 盏投影平行光: 槽位 0/1, 不告警")
print("=" * 60)
VR.VkRenderer._shadow_limit_warned = False
r = _renderer()
sun_a = _FakeLight('sunA', direction=(-0.6, -1.0, -0.4))
sun_b = _FakeLight('sunB', direction=(0.7, -0.9, 0.35))
scene, warn = _pack(r, [sun_a, sun_b])
check("B1 两盏都算出 VP", set(r._light_vps) == {'sunA', 'sunB'},
      str(sorted(r._light_vps)))
check("B2 槽位分配 = sunA:0 / sunB:1",
      r._dir_shadow_slots == {'sunA': 0, 'sunB': 1}, str(r._dir_shadow_slots))
check("B3 两盏平行光已支持 -> 不打印已知限制警告", warn == '', repr(warn[:60]))
check("B4 params.w = 0 / 1 (着色器按槽位选 t_shadow / t_shadow2)",
      (_params_w(scene, 0), _params_w(scene, 1)) == (0.0, 1.0),
      (_params_w(scene, 0), _params_w(scene, 1)))
check("B5 平行光 extra.w 仍是 0 (点光阴影标志不被占用)",
      (_extra_w(scene, 0), _extra_w(scene, 1)) == (0.0, 0.0),
      (_extra_w(scene, 0), _extra_w(scene, 1)))
check("B6 两盏灯的 shadow 标志都写进场景块",
      float(scene[VR._R_L0 + 3]) == 1.0
      and float(scene[VR._R_L0 + VR._LIGHT_F32 + 3]) == 1.0)

# ============ C. 第 3 盏平行光 ============
print("=" * 60)
print("C. 第 3 盏投影平行光: 不分配槽位 + 只警告一次")
print("=" * 60)
VR.VkRenderer._shadow_limit_warned = False
r = _renderer()
lights3 = [_FakeLight('a', direction=(-0.6, -1.0, -0.4)),
           _FakeLight('b', direction=(0.7, -0.9, 0.35)),
           _FakeLight('c', direction=(0.0, -1.0, 0.9))]
scene, warn = _pack(r, lights3)
check("C1 只分配前两盏 (a:0 / b:1)",
      r._dir_shadow_slots == {'a': 0, 'b': 1}, str(r._dir_shadow_slots))
check("C2 第 3 盏 params.w = -1 (无贴图 -> 该灯无阴影)",
      _params_w(scene, 2) == -1.0, _params_w(scene, 2))
check("C3 第 3 盏 VP 仍保留 (beam 截面/ortho 语义不退化)",
      'c' in r._light_vps, str(sorted(r._light_vps)))
check("C4 打印一次'阴影已知限制'警告",
      warn.count('阴影已知限制') == 1, repr(warn.strip()[:60]))
_, warn2 = _pack(r, lights3)
check("C5 二次打包不重复告警 (只喊一次)", warn2 == '', repr(warn2[:60]))

# ============ D. 单盏投影平行光 (既有场景) ============
print("=" * 60)
print("D. 单盏投影平行光: 槽位 0, 不告警")
print("=" * 60)
VR.VkRenderer._shadow_limit_warned = False
r = _renderer()
scene, warn = _pack(r, [_FakeLight('only')])
check("D1 单灯槽位 0", r._dir_shadow_slots == {'only': 0}, str(r._dir_shadow_slots))
check("D2 params.w = 0", _params_w(scene, 0) == 0.0, _params_w(scene, 0))
check("D3 不告警", warn == '', repr(warn[:60]))

# ============ E. 点光仍只烘第一盏 (既有已知限制) ============
print("=" * 60)
print("E. 点光: 仍只烘第一盏 (第二盏无阴影 + 警告一次)")
print("=" * 60)
VR.VkRenderer._shadow_limit_warned = False
r = _renderer()
p1 = _FakeLight('p1', kind='point')
p2 = _FakeLight('p2', kind='point')
scene, warn = _pack(r, [p1, p2])
check("E1 点光只烘第一盏", r._point_shadow_guid == 'p1', r._point_shadow_guid)
check("E2 第二盏点光没有 VP", 'p2' not in r._light_vps, str(sorted(r._light_vps)))
check("E3 不占平行光槽位", r._dir_shadow_slots == {}, str(r._dir_shadow_slots))
check("E4 点光超限警告一次", warn.count('阴影已知限制') == 1, repr(warn.strip()[:60]))
check("E5 点光 params.w 不参与平行光槽位 (保持 0)",
      _params_w(scene, 0) == 0.0 and _params_w(scene, 1) == 0.0,
      (_params_w(scene, 0), _params_w(scene, 1)))

print("=" * 60)
if _fails:
    print("失败 %d 项: %s" % (len(_fails), _fails))
else:
    print("VK 双平行光阴影槽位 全部 PASS")
