# -*- coding: utf-8 -*-
"""异步GUI (2026-08-15): 面板离屏FBO + 脏驱动限频合成 + 视口叠加直绘.
真实窗口断言: FBO 创建/尺寸、面板不透明+视口中心透明、脏标记渲染后清除、
无输入时面板 pass 不重渲 (限频生效)."""
import os
import sys

import numpy as np
import pygame

os.environ.setdefault('LOOM_NO_PARALLEL', '1')   # 测试守卫: 不建线程/不设亲和
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import editor


def main():
    app = editor.EditorApp(800, 600)
    app.show_grid = False                          # 采样前关无限网格防污染
    for _ in range(3):
        app.render(0.016)                          # 预热 + 建 FBO
    v = app.view

    # 1) FBO 已建, 尺寸 = 引擎尺寸
    assert v._gui_fbo is not None, "FBO 未创建"
    assert v._gui_fbo_size == (800, 600), "FBO 尺寸 %r != (800,600)" % (v._gui_fbo_size,)
    print("PASS 1: FBO 创建 + 尺寸 = 引擎")

    # 2) 读 GUI FBO: 工具栏像素不透明 / 视口中心 alpha=0 (透出场景)
    data = v._gui_tex.read()
    arr = np.frombuffer(data, dtype='u1').reshape(600, 800, 4).astype(int)
    arr_f = arr[::-1]                              # 纹理行底朝上 -> 翻转成屏幕朝向
    toolbar = arr_f[15, 640]                       # 顶部工具栏区 (面板底色 25,28,33)
    center = arr_f[300, 400]                       # 视口中心 (应全透明)
    assert toolbar[3] > 200, "工具栏 alpha=%d 应不透明" % toolbar[3]
    assert center[3] < 20, "视口中心 alpha=%d 应透明" % center[3]
    print("PASS 2: 面板不透明(alpha=%d) / 视口中心透明(alpha=%d)" % (toolbar[3], center[3]))

    # 3) 脏驱动: 置脏 -> draw 后清除; 无输入 + 长心跳 -> 面板 pass 不重渲 (限频生效)
    v._gui_heartbeat = 999.0                       # 关闭心跳, 纯看脏驱动
    app.gui_dirty = True
    app.render(0.016)
    assert app.gui_dirty is False, "渲染后 gui_dirty 未清除"
    t0 = v._last_gui_render
    for _ in range(5):
        app.render(0.016)                          # 无输入/无脏 -> 面板 pass 跳过
    assert v._last_gui_render == t0, "无输入时面板 pass 不应重渲 (限频失败)"
    print("PASS 3: 脏标记渲染后清除 + 无输入限频不重渲")

    app._stop_parallel()
    try:
        app.view.shutdown()
    except Exception:
        pass
    pygame.quit()
    print("全部 PASS ✅")
    return 0


if __name__ == '__main__':
    sys.exit(main())
