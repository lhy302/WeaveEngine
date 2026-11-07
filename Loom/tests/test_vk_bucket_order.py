# -*- coding: utf-8 -*-
"""test_vk_bucket_order.py — VK 渲染器桶实例偏移 / 贴图资源生命周期回归 (2026-11-07)。

覆盖 scan_04_vk_render 修复批次 (纯 CPU 逻辑, 不需要 GPU/窗口):
  · P1 回归 桶实例偏移: bucket_layout() 把同桶实例重排到连续区间, draw 的
    first_instance 用重排后的桶起点 (原实现用 idxs[0], 同桶被隔开就串行)。
  · P2 PBR 开关: VkRenderer.pbr_enabled 属性与 _pack_scene 的 misc.x 落地。
  · P2 法线贴图上传失败回落: _upload_tex(..., fallback=平直法线) 而不是白纹理。
  · P2 env cube 缓存: guid 键 + 持引用 + 上限淘汰 (摘 group + destroy)。
  · P2 vk_ui 文本 LRU: 淘汰时销毁纹理并摘掉对应 bind group; _groups 有界。

脚本式: 末尾 sys.exit(0 if ok else 1)。
"""
import sys as _sys_utf8
try:
    _sys_utf8.stdout.reconfigure(encoding='utf-8', errors='replace')
    _sys_utf8.stderr.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

import os
import sys
from collections import OrderedDict

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)
os.chdir(BASE)

import numpy as np

_fails = []


def check(name, cond, detail=''):
    print("%s %s  %s" % ("PASS" if cond else "FAIL", name, detail))
    if not cond:
        _fails.append(name)


import vk_renderer as VR
import vk_ui as VU


# ============ 1. 桶重排核心逻辑 ============
# 场景: 同网格 + 不同贴图 + 被别的物体隔开 (scan_04 指出的触发形态)
#   vis = [A(tex1), B(tex2), A(tex1)] -> 桶 {"A": [0, 2], "B": [1]}
groups = {'A': [0, 2], 'B': [1]}
order, starts, ident = VR.bucket_layout(groups)
check("交错: 需要重排", ident is False, "order=%s" % (order.tolist(),))
check("交错: order 顺序", order.tolist() == [0, 2, 1], str(order.tolist()))
check("交错: 桶起点", starts == {'A': 0, 'B': 2}, str(starts))

# 连续场景必须零拷贝 (identity=True, 老场景行为不变)
order2, starts2, ident2 = VR.bucket_layout({'A': [0, 1], 'B': [2, 3]})
check("连续: identity 短路", ident2 is True and order2.tolist() == [0, 1, 2, 3], str(order2.tolist()))
check("连续: 桶起点不变", starts2 == {'A': 0, 'B': 2}, str(starts2))

# 空场景
order3, starts3, ident3 = VR.bucket_layout({})
check("空场景: 空 order + identity", ident3 is True and len(order3) == 0 and starts3 == {})


def drawn_rows(order, starts, groups):
    """模拟 draw(nv, len(idxs), 0, first_instance=starts[k]) 真正吃到的实例行."""
    got = {}
    for k, idxs in groups.items():
        got[k] = [int(x) for x in order[starts[k]:starts[k] + len(idxs)]]
    return got


# 修复后: 每个桶画到的正是它自己的实例行
got = drawn_rows(order, starts, groups)
check("交错: 桶 A 画到 A 的行", sorted(got['A']) == [0, 2], str(got['A']))
check("交错: 桶 B 画到 B 的行", sorted(got['B']) == [1], str(got['B']))

# 回归对照: 旧实现 first_instance = idxs[0] 连画 len(idxs) 行 (单缓冲 + 原序)
_old_rows = []
for k, idxs in groups.items():
    _old_rows.extend(range(idxs[0], idxs[0] + len(idxs)))
_old = {}
for k, idxs in groups.items():
    _old[k] = list(range(idxs[0], idxs[0] + len(idxs)))
check("旧实现确实会串行 (回归证据)", _old['A'] == [0, 1] and _old['A'] != got['A'],
      "旧 A 行=%s, 新 A 行=%s" % (_old['A'], got['A']))

# 更大规模: 覆盖性 / 不重叠 / 每个桶成员集合完全一致
big = {'b%d' % (i % 4): [] for i in range(4)}
for row in range(13):
    big['b%d' % (row % 4)].append(row)
order4, starts4, ident4 = VR.bucket_layout(big)
got4 = drawn_rows(order4, starts4, big)
check("13 行 4 桶: 非 identity", ident4 is False)
check("13 行 4 桶: 每桶行集合正确",
      all(sorted(got4[k]) == big[k] for k in big), str({k: len(v) for k, v in got4.items()}))
check("13 行 4 桶: 覆盖全部行且不重叠",
      sorted(order4.tolist()) == list(range(13)) and
      sum(len(v) for v in got4.values()) == 13)


# ============ 2. PBR 全局开关 (属性名修复) ============
r = VR.VkRenderer.__new__(VR.VkRenderer)      # 绕过 __init__ 的 GPU 资源创建
check("PBR 缺省 True", r.pbr_enabled is True)
r.pbr_enabled = False
check("PBR setter 落到 _pbr_enabled", r._pbr_enabled is False and r.pbr_enabled is False)
r._light_vps = {}
_eye = np.eye(4, dtype=np.float32)
buf = r._pack_scene(_eye, [], (1.0, 2.0, 3.0))
check("PBR=False -> misc.x=0", abs(float(buf[VR._R_MISC]) - 0.0) < 1e-9,
      "misc.x=%.1f" % buf[VR._R_MISC])
r2 = VR.VkRenderer.__new__(VR.VkRenderer)
r2._light_vps = {}
check("PBR 默认 -> misc.x=1",
      abs(float(r2._pack_scene(_eye, [], (0.0, 0.0, 0.0))[VR._R_MISC]) - 1.0) < 1e-9)


# ============ 3. 法线贴图上传失败回落平直法线 ============
class _BadTex:
    """_rgba 非法 -> 上传必失败 (走 except 分支)."""
    guid = 'badtex'
    _rgba = 'not-an-array'


r3 = VR.VkRenderer.__new__(VR.VkRenderer)
r3._tex_cache = {}
r3._white_view = 'WHITE'
r3._flat_nrm_view = 'FLAT_NORMAL'
check("albedo 失败回落白纹理",
      r3._upload_tex(_BadTex()) == 'WHITE', str(r3._upload_tex(_BadTex())))
check("法线失败回落平直法线",
      r3._upload_tex(_BadTex(), fallback=r3._flat_nrm_view) == 'FLAT_NORMAL')
check("两种用途不共用缓存条目", len(r3._tex_cache) == 2, str(len(r3._tex_cache)))


# ============ 4. env cube 缓存: 上限淘汰 + 释放 ============
class _FakeGPU:
    def __init__(self):
        self.destroyed = 0

    def destroy(self):
        self.destroyed += 1


r4 = VR.VkRenderer.__new__(VR.VkRenderer)
r4._env_cache = OrderedDict()
r4._tex_groups = {}
r4._bkt_bufs = {}
r4._ENV_CACHE_MAX = 2
_views = []
for i in range(3):
    v, g = ('envview%d' % i, _FakeGPU())
    _views.append((v, g))
    r4._env_cache['guid%d' % i] = (v, float(i), object(), g)
# 给最老的 env 建一个 bind group 键 (第 4 项 = id(env_view)), 淘汰时必须摘掉
r4._tex_groups[('a', 'b', True, id(_views[0][0]), 0.0, 1)] = 'GROUP0'
r4._bkt_bufs[('a', 'b', True, id(_views[0][0]), 0.0, 1)] = 'BKT0'
r4._evict_env_cache()
check("env 缓存淘汰到上限", len(r4._env_cache) == 2, str(len(r4._env_cache)))
check("env 淘汰的是最久未用", 'guid0' not in r4._env_cache, str(list(r4._env_cache)))
check("env 淘汰销毁 GPU 纹理", _views[0][1].destroyed == 1, str(_views[0][1].destroyed))
check("env 淘汰摘掉 bind group", len(r4._tex_groups) == 0 and len(r4._bkt_bufs) == 0)
check("env 命中时保活 (未淘汰项未销毁)",
      _views[1][1].destroyed == 0 and _views[2][1].destroyed == 0)


# ============ 5. vk_ui 文本 LRU: 淘汰释放 + _groups 有界 ============
class _FakeUiTex:
    def __init__(self, tag):
        self.view = ('view', tag)      # 可哈希, 模拟 wgpu view 对象
        self.tex = _FakeGPU()
        self.key = tag


p = VU.VkUIPipeline.__new__(VU.VkUIPipeline)
p._text_cache = OrderedDict()
p._groups = OrderedDict()
_old_max = VU._TEXT_CACHE_MAX
VU._TEXT_CACHE_MAX = 2
_texs = []
for i in range(4):
    t = _FakeUiTex(i)
    _texs.append(t)
    p._text_cache[('text%d' % i)] = t
    p._groups[id(t.view)] = ('group', t.view)
    p._evict_text_lru()
VU._TEXT_CACHE_MAX = _old_max
check("文本 LRU 达上限", len(p._text_cache) == 2, str(len(p._text_cache)))
check("文本 LRU 淘汰销毁纹理",
      _texs[0].tex.destroyed == 1 and _texs[1].tex.destroyed == 1,
      "destroyed=%d" % sum(t.tex.destroyed for t in _texs))
check("文本 LRU 保留最新两条", list(p._text_cache) == [('text2'), ('text3')],
      str(list(p._text_cache)))
check("文本 LRU 摘掉对应 group", len(p._groups) == 2, str(len(p._groups)))
check("_groups 有界常量 > 文本缓存", VU.VkUIPipeline._GROUPS_MAX > VU._TEXT_CACHE_MAX,
      "%d > %d" % (VU.VkUIPipeline._GROUPS_MAX, VU._TEXT_CACHE_MAX))

# _groups 的 LRU 上限: group_for 依赖真实 device, 这里只校验淘汰逻辑的副作用
p2 = VU.VkUIPipeline.__new__(VU.VkUIPipeline)
p2._groups = OrderedDict()
for i in range(VU.VkUIPipeline._GROUPS_MAX + 3):
    p2._groups[id(('view', i))] = ('g', i)
while len(p2._groups) > VU.VkUIPipeline._GROUPS_MAX:
    p2._groups.popitem(last=False)
check("_groups 上限淘汰可收敛", len(p2._groups) == VU.VkUIPipeline._GROUPS_MAX,
      str(len(p2._groups)))


# ============ 6. 采样器: wrap / filter_mode 生效 ============
class _T:
    def __init__(self, wrap, fm):
        self.wrap = wrap
        self.filter_mode = fm


d_default = VR.sampler_desc(None)
check("默认采样器 = repeat+trilinear",
      (d_default['address_mode_u'], d_default['mag_filter'], d_default['min_filter'],
       d_default['mipmap_filter']) == ('repeat', 'linear', 'linear', 'linear'),
      str(d_default))
d_clamp = VR.sampler_desc(_T('clamp', 'point'))
check("clamp+point 映射",
      (d_clamp['address_mode_u'], d_clamp['address_mode_v'],
       d_clamp['mag_filter'], d_clamp['mipmap_filter'])
      == ('clamp-to-edge', 'clamp-to-edge', 'nearest', 'nearest'), str(d_clamp))
d_bili = VR.sampler_desc(_T('repeat', 'bilinear'))
check("bilinear: 线性采样 + mip 最近",
      (d_bili['mag_filter'], d_bili['mipmap_filter']) == ('linear', 'nearest'), str(d_bili))
d_mirror = VR.sampler_desc(_T('mirror', 'trilinear'))
check("mirror 回落 repeat (与 GL 一致)",
      d_mirror['address_mode_u'] == 'repeat', str(d_mirror))
check("默认参数与旧单采样器同键",
      VR._sampler_key(d_default) == ('linear', 'linear', 'linear', 'repeat', 'repeat'))


# ============ 7. 多投影灯: 已知限制只警告一次 (不崩) ============
import contextlib
import inspect
import io


class _Vec:
    def __init__(self, x, y, z):
        self.x, self.y, self.z = x, y, z


class _FakeLight:
    def __init__(self, guid, kind='directional', shadow=True):
        self.guid = guid
        self.kind = kind
        self.shadow = shadow
        self.mode = 'full'
        self.shape = 'circle'
        self.size = 5.0
        self.direction = _Vec(-0.3, -1.0, -0.2)
        self.position = _Vec(0.0, 5.0, 0.0)

    def up_vector(self):
        return _Vec(0.0, 1.0, 0.0)


check("构造参数 pbr_enabled 存在",
      'pbr_enabled' in inspect.signature(VR.VkRenderer.__init__).parameters)

r5 = VR.VkRenderer.__new__(VR.VkRenderer)
r5._dir_light_vp = lambda light, worlds, vis: _eye     # 跳过几何依赖 (CPU 单测)
_none_worlds = np.zeros((0, 4, 4), dtype=np.float32)

VR.VkRenderer._shadow_limit_warned = False
_buf = io.StringIO()
with contextlib.redirect_stdout(_buf):
    r5._pack_light_vps([_FakeLight('sun1'), _FakeLight('sun2')], [], _none_worlds)
_warn = _buf.getvalue()
# 2026-11-07: VK 已支持 2 张平行光阴影 -> 两盏投影灯是合法配置, 不再告警
check("两盏平行光投影: 已支持 2 张, 不警告", _warn == '', _warn.strip()[:48])
check("两盏平行光: 两盏都拿到 VP",
      set(r5._light_vps) == {'sun1', 'sun2'}, str(sorted(r5._light_vps)))
check("两盏平行光: 槽位 0/1", r5._dir_shadow_slots == {'sun1': 0, 'sun2': 1},
      str(r5._dir_shadow_slots))

_buf2 = io.StringIO()
with contextlib.redirect_stdout(_buf2):
    r5._pack_light_vps([_FakeLight('a'), _FakeLight('b'), _FakeLight('c')], [],
                       _none_worlds)
check("第 3 盏平行光: 打一次已知限制警告",
      _buf2.getvalue().count('阴影已知限制') == 1, _buf2.getvalue().strip()[:48])
check("第 3 盏平行光: 不分配槽位 (前两盏 0/1)",
      r5._dir_shadow_slots == {'a': 0, 'b': 1}, str(r5._dir_shadow_slots))

VR.VkRenderer._shadow_limit_warned = False
_buf3 = io.StringIO()
with contextlib.redirect_stdout(_buf3):
    r5._pack_light_vps([_FakeLight('only')], [], _none_worlds)
check("单投影灯不警告", _buf3.getvalue() == '', repr(_buf3.getvalue()[:40]))

VR.VkRenderer._shadow_limit_warned = False
_buf4 = io.StringIO()
with contextlib.redirect_stdout(_buf4):
    r5._pack_light_vps([_FakeLight('p1', 'point'), _FakeLight('p2', 'point')], [],
                       _none_worlds)
check("两盏点光投影: 同样打一次警告",
      _buf4.getvalue().count('阴影已知限制') == 1, _buf4.getvalue().strip()[:48])
check("点光只烘第一盏 (已知限制)",
      r5._point_shadow_guid == 'p1' and 'p2' not in r5._light_vps,
      str(r5._point_shadow_guid))


print("-" * 60)
if _fails:
    print("FAILED:", _fails)
    sys.exit(1)
print("全部通过 ✅")
sys.exit(0)
