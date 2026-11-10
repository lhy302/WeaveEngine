# -*- coding: utf-8 -*-
"""loom_post.py — 后处理链的开关与参数（tonemap + bloom，2026-11-10 阶段 2B2）。

口径（与人类裁决一致）：
  · 默认开启：主 pass 渲染到 HDR 目标（rgba16float），后处理链 = bright -> 0.5 -> 0.25
    -> 上采样合成 -> tonemap 到 LDR；HUD/UI 仍在 tonemap 之后。
  · LOOM_POST=0/off/false 走**旧路径**（无 HDR、无后处理；像素必须与 2B1 逐位一致）。

为什么 main/sky 着色器不用改：现有 shader 输出的是**已 gamma 编码**的颜色，HDR 目标只是
用 16F 存同一批数值（>1 的亮部也能保留）；tonemap 统一做 pow(2.2) 反线性 -> 曲线 -> 编码。
这样 GL/VK 的既有着色器与 uniform 布局一个字节都不用动（双后端同源）。
"""
import os

# HDR / bloom 的语义目标名（GL 与 VK 各自解析）
HDR_TARGET = 'color.hdr'
HALF_TARGET = 'bloom.half'
QUARTER_TARGET = 'bloom.quarter'

# 默认参数（可用环境变量微调，便于人眼对比与压测）
DEFAULTS = {
    'threshold': 0.85,   # 线性空间亮度阈值（gamma 编码值先 pow(2.2)）
    'knee': 0.35,        # 柔和过渡
    'strength': 0.55,    # bloom 叠加强度
    'exposure': 1.0,
}


def _env_float(name, default):
    try:
        return float(os.environ.get(name, default))
    except (TypeError, ValueError):
        return float(default)


def post_enabled():
    """LOOM_POST=0/off/false/no 关闭（默认开启）。"""
    v = (os.environ.get('LOOM_POST') or '').strip().lower()
    return v not in ('0', 'off', 'false', 'no')


def params():
    p = dict(DEFAULTS)
    p['threshold'] = _env_float('LOOM_BLOOM_THRESHOLD', p['threshold'])
    p['knee'] = _env_float('LOOM_BLOOM_KNEE', p['knee'])
    p['strength'] = _env_float('LOOM_BLOOM_STRENGTH', p['strength'])
    p['exposure'] = _env_float('LOOM_POST_EXPOSURE', p['exposure'])
    return p
