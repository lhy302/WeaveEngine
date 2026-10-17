# -*- coding: utf-8 -*-
"""probe_draw_lines_reuse.py — GLEngine.draw_lines 缓冲复用安全 像素级探针 (D10 前绿色基线).

背景: engine.py draw_lines (engine.py:2140) 旧实现每次调用新建 ctx.buffer +
ctx.vertex_array, 绘完 release. 即将做 D10: 持久动态缓冲 + VAO 缓存复用.
本探针在旧实现下建立基线; 复用实现落地后重跑, 可抓三类回归:
  1) 旧计数残留: 画 10 条 -> clear -> 只画 2 条, 若复用实现按旧顶点数重放
     或残留旧几何, 后 8 条旧位置会亮起 -> FAIL;
  2) 旧顶点泄漏 / 第二次 write 不完整: 不 clear 连画两组顶点数不同的线,
     第二组必须完整生效且不破坏第一组;
  3) 误清屏 / 串色: 第二组 draw 抹掉第一组, 或跨用例区域出现残留.

方法: standalone moderngl Context 注入 GLEngine (外部模式, 无 pygame 窗口),
自建 FBO 800x600 + 正交 VP (世界坐标 = 屏幕像素, 左上原点 y 向下), 显式传
view_proj 绕过引擎相机 (不调 render, 不触发引擎 flip); 像素经 fb.read 读回
(bottom-up -> 翻 top-down), 期望坐标 ±1px 窗口采样, 不做全图 diff.
退出码: 0=全 PASS, 1=有 FAIL.
用法: py -3.12 tests\\_tmp\\probe_draw_lines_reuse.py
"""
import os
import sys

os.environ.setdefault('LOOM_NO_PARALLEL', '1')   # 测试守卫: 不建脚本线程/不设核亲和
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))))                # ...\Loom

import numpy as np
import moderngl
import pygame
pygame.font.init()      # 引擎 _load_font 需要; 不建窗口 (无 set_mode, 不碰 IME)

import engine

W, H = 800, 600
ctx = moderngl.create_standalone_context()
eng = engine.GLEngine(W, H, ctx=ctx)             # ctx 注入 = 外部模式 (engine.py:1178)

# 自建离屏 FBO (引擎 render 内部 flip, 直读双缓冲屏幕会拿黑图, 学
# gl_p2f_screenshot_probe.py 的外部 FBO 套路; draw_lines 外部模式绘制前
# _screen_fb().use() -> 把 FBO 挂到 eng._external_fb 即画进这里)
color_tex = ctx.texture((W, H), 4)
depth_tex = ctx.depth_texture((W, H))
fb = ctx.framebuffer(color_attachments=[color_tex], depth_attachment=depth_tex)
eng._external_fb = fb

# 正交 VP: 世界 (x, y, z=0) 直接是屏幕像素坐标 (左上原点, y 向下).
# 引擎约定: u_view_proj 直接写 numpy 数组字节, GLSL 等效行向量 v @ M
# (matlib 转置约定, engine.render 的 V@P 同款), 故按 v_row @ M 推元素:
# out.x = 2x/W - 1, out.y = 1 - 2y/H, out.z = 0 (深度 0.5 < 清屏 1.0, 必过), w = 1.
VP = np.zeros((4, 4), dtype='f4')
VP[0, 0] = 2.0 / W
VP[1, 1] = -2.0 / H
VP[3, 0] = -1.0
VP[3, 1] = 1.0
VP[3, 3] = 1.0

total = 0
fails = []


def check(name, ok):
    global total
    total += 1
    print(('PASS  ' if ok else 'FAIL  ') + name)
    if not ok:
        fails.append(name)


def clear():
    fb.use()
    ctx.clear(0.0, 0.0, 0.0, 1.0, depth=1.0)     # 同 _clear_main_fbo: 深度清到 far


def draw(verts, colors):
    eng.draw_lines(verts, colors, view_proj=VP)  # 显式 VP, 不依赖引擎 self._vp


def grab():
    raw = fb.read(components=4, alignment=1)
    return np.frombuffer(raw, dtype=np.uint8).reshape(H, W, 4)[::-1]   # -> top-down


def hit(img, px, py, test):
    """期望坐标 ±1px 窗口内任一像素满足颜色判定即命中 (线宽 1~2px 光栅化均兼容)"""
    for dy in (-1, 0, 1):
        for dx in (-1, 0, 1):
            x, y = px + dx, py + dy
            if 0 <= x < W and 0 <= y < H and test(img[y, x]):
                return True
    return False


def black_at(img, px, py):
    p = img[py, px]
    return p[0] <= 20 and p[1] <= 20 and p[2] <= 20


is_red = lambda p: p[0] >= 200 and p[1] <= 50 and p[2] <= 50
is_blue = lambda p: p[2] >= 200 and p[0] <= 50 and p[1] <= 50
is_green = lambda p: p[1] >= 150 and p[0] <= 80 and p[2] <= 80
is_yellow = lambda p: p[0] >= 180 and p[1] >= 180 and p[2] <= 80

RED, BLUE = (1.0, 0.0, 0.0), (0.0, 0.0, 1.0)
GREEN, YELLOW = (0.0, 0.8, 0.0), (0.9, 0.9, 0.0)


def hseg(y, x0, x1):
    """一条水平线段 (LINES 模式 = 端点对), z=0"""
    return [(x0, y, 0.0), (x1, y, 0.0)]


# ============ 用例1: 计数收缩 (10 红 -> clear -> 2 蓝) ============
rows10 = [50 + i * 50 for i in range(10)]        # y=50..500, 互不重叠 (间隔 50px)

print('--- 用例1a: clear 后画 10 条红 (每条 中点+两端 共 3 采样点) ---')
clear()
verts, cols = [], []
for y in rows10:
    verts += hseg(y, 100, 300)
    cols += [RED, RED]
draw(verts, cols)
img = grab()
for i, y in enumerate(rows10):
    check('红%d 中点(200,%d)' % (i, y), hit(img, 200, y, is_red))
    check('红%d 端A(100,%d)' % (i, y), hit(img, 100, y, is_red))
    check('红%d 端B(300,%d)' % (i, y), hit(img, 300, y, is_red))
for i in range(9):                               # 线间 25px 背景须黑 (防整行泛红)
    y = rows10[i] + 25
    check('用例1 间隙(200,%d)黑' % y, black_at(img, 200, y))

print('--- 用例1b: clear 后只画 2 条蓝 (计数收缩; 复用实现残留旧计数/旧顶点必炸) ---')
clear()
verts, cols = [], []
for y in rows10[:2]:                             # 只画前 2 条的同一位置
    verts += hseg(y, 100, 300)
    cols += [BLUE, BLUE]
draw(verts, cols)
img = grab()
for i, y in enumerate(rows10[:2]):
    check('蓝%d 中点(200,%d)' % (i, y), hit(img, 200, y, is_blue))
for i, y in enumerate(rows10[2:]):               # 旧 8 条位置必须全黑
    ok = (black_at(img, 200, y) and black_at(img, 100, y)
          and black_at(img, 300, y))
    check('旧红%d 位置残留黑(100/200/300,%d)' % (i, y), ok)
check('用例1b 间隙(200,125)黑', black_at(img, 200, 125))

# ============ 用例2: 数据更换 (clear -> 绿 3 条 -> 不 clear -> 黄 5 条) ============
print('--- 用例2: 连续两组不同顶点数 (复用实现下第二次 write 须完整且不毁第一次) ---')
g_rows = [30, 60, 90]                            # 绿 3 条 (6 顶点)
y_rows = [150, 220, 290, 360, 430]               # 黄 5 条 (10 顶点, 数量不同)
clear()
verts, cols = [], []
for y in g_rows:
    verts += hseg(y, 500, 700)
    cols += [GREEN, GREEN]
draw(verts, cols)
verts, cols = [], []                             # 关键: 不 clear, 直接第二组
for y in y_rows:
    verts += hseg(y, 500, 700)
    cols += [YELLOW, YELLOW]
draw(verts, cols)
img = grab()
for i, y in enumerate(g_rows):
    ok = (hit(img, 500, y, is_green) and hit(img, 600, y, is_green)
          and hit(img, 700, y, is_green))
    check('绿%d 仍在(500/600/700,%d)' % (i, y), ok)
for i, y in enumerate(y_rows):
    ok = (hit(img, 500, y, is_yellow) and hit(img, 600, y, is_yellow)
          and hit(img, 700, y, is_yellow))
    check('黄%d 新画(500/600/700,%d)' % (i, y), ok)
ok = all(black_at(img, 200, y) for y in rows10)  # 用例1 区域须仍黑 (抓串色/误残留)
check('用例1 区域仍黑(200, 各红行)', ok)
check('未画区(60,320)黑', black_at(img, 60, 320))
check('未画区(400,320)黑', black_at(img, 400, 320))

print('---')
print('结果: PASS %d / %d, FAIL %d' % (total - len(fails), total, len(fails)))
eng._stop_parallel()
ctx.release()
sys.exit(0 if not fails else 1)
