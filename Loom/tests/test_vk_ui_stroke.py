# -*- coding: utf-8 -*-
"""test_vk_ui_stroke.py — VK Shape 描边契约 + line-list 实验回退回归 (2026-11-07)。

覆盖 R2 描边契约 (纯 CPU 记录层, 不需要 GPU/窗口):
  · STROKE_PIXEL_EQUIVALENT=False / STROKE_METHOD='triangle-band' 契约不变;
  · width<=1 仍走三角带 (hw=0.5), width=2 -> hw=1.0; 每段 6 顶点;
  · 描边 alpha 钉为 1 (复刻 GL draw_lines 期间 BLEND 关闭的视觉效果);
  · close=True 自动补首尾段; 退化段 (<1e-6) 跳过; <2 点不产生 op;
  · 2026-11-07 line-list 实验已实测"与三角带逐像素相同、无改善"并回退,
    源码中不得残留 line_pipeline / line-list 拓扑 (重引入前必须先跑 A/B)。

背景数字 (480x320, tests/_tmp/ui_lines_scene.json + ui_lines_alpha_scene.json):
  三角带 MAE=0.00357361 / 0.00680006; width<=1 走 line-list 后两值逐位不变
  (该驱动 1px line-list 与 hw=0.5 三角带 0 像素差), 故按"无改善即回退"处理。
  详见 docs/audit/fix_vk_render_batch.md 第 9 节。

脚本式: 末尾 sys.exit(0 if ok else 1)。
"""
import sys as _sys_utf8
try:
    _sys_utf8.stdout.reconfigure(encoding='utf-8', errors='replace')
    _sys_utf8.stderr.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

import inspect
import os
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)
os.chdir(BASE)

import numpy as np

_fails = []


def check(name, cond, detail=''):
    print("%s %s  %s" % ("PASS" if cond else "FAIL", name, detail))
    if not cond:
        _fails.append(name)


import vk_ui as VU


def _engine():
    # draw_screen_lines 只记录 op, 不碰 GPU 资源 -> 可用 None 当 pipeline
    e = VU.VkUIEngine(None)
    e.begin_frame(480, 320)
    return e


def _ys(verts):
    return sorted(set(round(float(v[1]), 3) for v in verts))


def _xs(verts):
    return sorted(set(round(float(v[0]), 3) for v in verts))


# ============ 1. 契约常量 ============
check("契约: 非逐像素等价", VU.STROKE_PIXEL_EQUIVALENT is False)
check("契约: 三角带方法", VU.STROKE_METHOD == 'triangle-band',
      repr(VU.STROKE_METHOD))

# ============ 2. width<=1 仍走三角带 (hw=0.5) ============
e = _engine()
e.draw_screen_lines([(10.0, 50.0), (190.0, 50.0)], (255, 80, 80, 255),
                    width=1)
check("width=1: 单 op", len(e._ops) == 1, str(len(e._ops)))
verts = e._ops[0][2]
check("width=1: 每段 6 顶点 (2 三角形)", verts.shape == (6, 8),
      str(verts.shape))
check("width=1: 半宽 0.5 (y=49.5/50.5)", _ys(verts) == [49.5, 50.5],
      str(_ys(verts)))
check("width=1: 端点 x 保留 10/190", _xs(verts) == [10.0, 190.0],
      str(_xs(verts)))

# width=2 -> 半宽 1.0
e = _engine()
e.draw_screen_lines([(10.0, 50.0), (190.0, 50.0)], (255, 80, 80, 255),
                    width=2)
verts = e._ops[0][2]
check("width=2: 半宽 1.0 (y=49/51)", _ys(verts) == [49.0, 51.0],
      str(_ys(verts)))

# 垂直段: x 方向 ±0.5
e = _engine()
e.draw_screen_lines([(50.0, 10.0), (50.0, 90.0)], (255, 255, 255, 255),
                    width=1)
check("width=1 垂直段: x=49.5/50.5", _xs(e._ops[0][2]) == [49.5, 50.5],
      str(_xs(e._ops[0][2])))

# ============ 3. alpha 钉 1 (GL 状态语义) ============
e = _engine()
e.draw_screen_lines([(10.0, 10.0), (100.0, 100.0)], (10, 20, 30, 120),
                    width=2)
alphas = set(round(float(v[7]), 6) for v in e._ops[0][2])
check("alpha: 输入 120 -> 顶点 alpha=1.0", alphas == {1.0}, str(alphas))

# ============ 4. close / 退化段 / 点数不足 ============
e = _engine()
e.draw_screen_lines([(0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0)],
                    (255, 255, 255, 255), width=1, close=True)
check("close=True: 4 段 -> 24 顶点", e._ops[0][2].shape == (24, 8),
      str(e._ops[0][2].shape))

e = _engine()
e.draw_screen_lines([(5.0, 5.0), (5.0, 5.0), (50.0, 5.0)],
                    (255, 255, 255, 255), width=1)
check("退化段: 跳过零长段 (1 段 -> 6 顶点)", e._ops[0][2].shape == (6, 8),
      str(e._ops[0][2].shape))

e = _engine()
e.draw_screen_lines([(5.0, 5.0)], (255, 255, 255, 255), width=1)
check("点数不足: 不产生 op", len(e._ops) == 0, str(len(e._ops)))

# ============ 5. line-list 实验已回退 (决策锁定) ============
src = inspect.getsource(VU)
check("回退: 无 line_pipeline", 'line_pipeline' not in src)
check("回退: 无 line-list 拓扑声明", "'line-list'" not in src)

print("=" * 60)
if _fails:
    print("FAIL:", _fails)
    sys.exit(1)
print("ALL PASS (test_vk_ui_stroke.py)")
sys.exit(0)
