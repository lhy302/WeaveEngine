# -*- coding: utf-8 -*-
"""loom_scene_ubo.py — T3c-1：场景参数**单一来源**（字段表 + std140 打包）。

布局与 VK 既有 SceneC 逐字节一致：头 32 f32 + 8 灯 × 40 f32 = 352 f32 = 1408 B。
GL 与 VK 都用本模块的 pack() 打包；加字段只改这里（同时改两端 shader 的字段读取）。
"""
import numpy as np

HEAD = 32
LIGHT_F32 = 40
LIGHTS = 8
FLOATS = HEAD + LIGHTS * LIGHT_F32          # 352
BYTES = FLOATS * 4                          # 1408

# 头字段（f32 偏移）
OFF_MVP = 0        # mat4 (16)
OFF_CAM = 16       # xyz=view_pos, w=ambient_scale
OFF_CNT = 20       # 灯 0-3 激活标志
OFF_CNT2 = 24      # 灯 4-7
OFF_MISC = 28      # x=pbr_mode, y=light_count, z=dir_shadow_res, w=point_shadow_res

# 每灯字段（相对灯基址的 f32 偏移）
LO_KIND = 0        # kind, mode, shape, shadow
LO_COLOR = 4       # rgb + intensity(a)
LO_DIR = 8
LO_POS = 12
LO_ORTHO = 16      # mat4 (16)
LO_PARAMS = 32     # bias, dir_res, point_far, dir_slot
LO_EXTRA = 36      # cos_inner, cos_outer, range, has_point_shadow


def light_base(i):
    return HEAD + i * LIGHT_F32


def pack(vp, lights, camera_pos, pbr_enabled, point_far=30.0,
         point_res=512.0, dir_res=1024.0, dir_bias=0.002, dir_slots=None,
         light_vps=None, point_shadow_guid=None):
    """按本表打包 -> float32 数组（长度 FLOATS）。调用方只提供语义值。"""
    import math
    buf = np.zeros(FLOATS, dtype=np.float32)
    buf[OFF_MVP:OFF_MVP + 16] = np.asarray(vp, dtype=np.float32).reshape(16)
    buf[OFF_CAM:OFF_CAM + 4] = (camera_pos[0], camera_pos[1], camera_pos[2],
                                1.0 if lights else 0.2)
    buf[OFF_MISC + 0] = 1.0 if pbr_enabled else 0.0
    buf[OFF_MISC + 1] = float(len(lights))
    buf[OFF_MISC + 2] = float(dir_res)
    buf[OFF_MISC + 3] = float(point_res)
    dir_slots = dir_slots or {}
    n_on = min(len(lights), LIGHTS)
    for i in range(LIGHTS):
        if i < 4:
            buf[OFF_CNT + i] = 1.0 if i < n_on else 0.0
        else:
            buf[OFF_CNT2 + (i - 4)] = 1.0 if i < n_on else 0.0
    for i, l in enumerate(lights[:LIGHTS]):
        b = light_base(i)
        kind = 0.0
        if l.kind == "point":
            kind = 1.0
        elif l.kind == "spot":
            kind = 2.0
        mode = 0.0 if l.mode == "full" else 1.0
        shape = 0.0 if l.shape == "circle" else 1.0
        buf[b + LO_KIND:b + LO_KIND + 4] = (kind, mode, shape,
                                            1.0 if l.shadow else 0.0)
        buf[b + LO_COLOR:b + LO_COLOR + 3] = l.color
        buf[b + LO_COLOR + 3] = float(l.intensity)
        d = l.direction
        buf[b + LO_DIR:b + LO_DIR + 3] = (d.x, d.y, d.z)
        pp = l.position
        buf[b + LO_POS:b + LO_POS + 3] = (pp.x, pp.y, pp.z)
        _vps = light_vps or {}
        _vp_l = _vps.get(l.guid)
        if _vp_l is not None and hasattr(_vp_l, 'reshape'):
            buf[b + LO_ORTHO:b + LO_ORTHO + 16] = np.asarray(_vp_l,
                                                             dtype=np.float32).reshape(-1)
        _slot = 0.0
        if kind < 0.5:
            _slot = float(dir_slots.get(l.guid, -1))
        buf[b + LO_PARAMS:b + LO_PARAMS + 4] = (dir_bias, float(dir_res),
                                                float(point_far), _slot)
        inner = math.cos(math.radians(float(getattr(l, "spot_inner_angle", 30.0))))
        outer = math.cos(math.radians(float(getattr(l, "spot_outer_angle", 60.0))))
        has_ps = 1.0 if (point_shadow_guid is not None
                         and getattr(l, 'guid', None) == point_shadow_guid) else 0.0
        buf[b + LO_EXTRA:b + LO_EXTRA + 4] = (inner, outer,
                                              float(getattr(l, "range", 10.0)), has_ps)
    return buf


def assert_layout():
    """单一来源断言：头 + 8 灯 == 352 f32。"""
    assert HEAD + LIGHTS * LIGHT_F32 == FLOATS
    assert FLOATS * 4 == BYTES
    return FLOATS
