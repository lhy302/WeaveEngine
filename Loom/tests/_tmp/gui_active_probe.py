# -*- coding: utf-8 -*-
"""探针: 复现"操作后控件消失 -> active_id 永久残留 -> UI 卡死"根因.
场景: 点挂脚本按钮(认领 active_id) -> 脚本已挂按钮下一帧消失 -> 释放事件丢失.
运行: py -3.12 "Loom\tests\_tmp\gui_active_probe.py" (子进程+超时)"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))))
import editor

e = editor.EditorApp(400, 300)
g = e.gui

# 帧1: 按下挂脚本按钮 (位置覆盖)
g.begin_frame((20, 20), (1, 0, 0), [1], [], 0)          # 左键按下
claimed = g.button("insp.sadd.gravity", (10, 10, 250, 22), "+ 重力落地", size=13)
print("帧1: claimed=%s active_id=%s" % (claimed, g.active_id))
g.end_frame()

# 帧2: 释放左键, 但挂脚本按钮不再渲染 (模拟"脚本已挂, 按钮消失")
g.begin_frame((20, 20), (1, 0, 0), [], [1], 0)          # 释放
# 不调用 button("insp.sadd.gravity") -> 该控件本帧不存在
g.end_frame()
print("帧2 后: active_id=%s  (残留=释放事件丢失=卡死根因)" % g.active_id)

# 帧3: 尝试点击播放按钮, 看还能否认领
g.begin_frame((120, 120), (1, 0, 0), [1], [], 0)
p_clicked = g.button("tool.play", (120, 120, 56, 26), "▶播放", size=14)
print("帧3: 播放按钮 claimed=%s  (False=UI 已卡死, active_id 被占)" % p_clicked)
g.end_frame()

ok = (g.active_id is None or p_clicked)
print("RESULT:", "PASS (active_id 已清/能交互)" if ok else "FAIL (active_id 残留卡死)")
import pygame; pygame.quit()
