# -*- coding: utf-8 -*-
"""P2 编辑器路径浮空复现: EditorApp + 跳台试炼场景 + 播放帧循环 (真实 GL 上下文)"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
os.chdir(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

os.environ['LOOM_NO_PARALLEL'] = '1'
import editor
editor.STATE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                 "ed_state_p2.json")

scene = os.path.join(os.path.dirname(os.path.abspath(__file__)), "jt_scene.json")
eng = editor.EditorApp(1280, 800, scene_path=scene)
eng.toggle_play()
print("桥:", eng._phys_bridge)
me = next(m for m in eng.models if m.name == '玩家')
print("播放开始 玩家 y=%.3f" % me.position.y)
for i in range(150):
    eng.render(0.016)
    if i % 30 == 0:
        print("帧%03d 玩家 y=%.4f vy=%.4f active=%s" % (
            i, me.position.y, me.rigidbody.velocity.y,
            eng._phys_bridge.active_count if eng._phys_bridge else -1))
eng.toggle_play()
print("播放结束 玩家 快照还原 y=%.3f" % me.position.y)
