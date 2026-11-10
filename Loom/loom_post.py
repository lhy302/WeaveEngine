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
# 参数口径（2026-11-10 调参，人类裁决 Q-VIS-1=B）：
#   · HDR 目标存的是**gamma 编码**值；bright/tonemap 都先 pow(2.2) 反线性。
#   · bright 的输入 = 线性 * exposure（与 tonemap 同一曝光），阈值按**曝光后线性亮度**比。
#   · exposure=1.70 由「新图平均亮度 ≈ 旧基线 0.5735」解析标定（预测 0.5714，-0.4%），
#     实测复核对齐（见交付报告）。可用 LOOM_POST_EXPOSURE 覆盖。
DEFAULTS = {
    'threshold': 1.15,   # 曝光后线性亮度阈值（≈ gamma 0.90 以上的真正亮部）
    'knee': 0.35,        # 柔和过渡
    'strength': 0.70,    # bloom 叠加强度
    'exposure': 1.70,
}


def _env_float(name, default):
    try:
        return float(os.environ.get(name, default))
    except (TypeError, ValueError):
        return float(default)


def post_enabled():
    """LOOM_POST=0/off/false/no 关闭（默认开启）。"""
    v = (os.environ.get('LOOM_POST') or '').strip().lower()
    return v not in ('0', 'off', 'false', 'no') and post_stage() > 0


def post_stage():
    """**诊断用**分级开关（2026-11-10 编译版崩溃二分；定稿前清理）。

    LOOM_POST_STAGE: 1 = 只 HDR 目标 + tonemap；2 = +bright；3 = +down（全链，默认）。
    """
    try:
        return max(1, min(3, int(os.environ.get('LOOM_POST_STAGE', '3'))))
    except (TypeError, ValueError):
        return 3


def params():
    p = dict(DEFAULTS)
    p['threshold'] = _env_float('LOOM_BLOOM_THRESHOLD', p['threshold'])
    p['knee'] = _env_float('LOOM_BLOOM_KNEE', p['knee'])
    p['strength'] = _env_float('LOOM_BLOOM_STRENGTH', p['strength'])
    p['exposure'] = _env_float('LOOM_POST_EXPOSURE', p['exposure'])
    return p
