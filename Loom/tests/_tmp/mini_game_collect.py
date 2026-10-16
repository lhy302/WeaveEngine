# -*- coding: utf-8 -*-
"""mini_game_collect.py — 小游戏实测: 收集彩球 (找 bug)"""
import os, sys, time, traceback
BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, BASE); os.chdir(BASE)
sys.argv[0] = os.path.join(BASE, 'Loom.py')
import moderngl, editor as editor_mod
import engine as E
from mesh import create_plane, create_cube, create_sphere

errors = []
ctx = moderngl.create_standalone_context()
ed = editor_mod.EditorApp(640, 480, ctx=ctx); ed._external_fb = ctx.detect_framebuffer()
try:
    _g = ed.view.gui.render; ed.view.gui.render = lambda *a, **k: _g(target=ed._external_fb)
except Exception: pass
ed.load_scene(os.path.join(BASE, '保存', '压力测试', '压力_空场景.json'))

print("=== 建小游戏场景 ===")
ground = ed.add_model(create_plane(20.0, 20.0), E.Point3D(0,0,0), E.Point3D(0,0,0), name='地面')
player = ed.add_model(create_sphere(0.5, 12, 16), E.Point3D(0,0.5,0), E.Point3D(0,0,0), name='玩家')
print("  地面/玩家 OK")

# 加脚本
try:
    player.add_script('wasd_move', {'speed': 4.0})
    player.add_script('camera_follow', {'oy': 3.0})
    print("  玩家脚本 OK:", [s.script_id for s in player.scripts])
except Exception as e:
    errors.append(("加玩家脚本", traceback.format_exc())); print("  玩家脚本失败:", e)

balls = []
for i, pos in enumerate([(2,0.5,2), (-2,0.5,3), (3,0.5,-2)]):
    b = ed.add_model(create_sphere(0.4, 10, 14), E.Point3D(*pos), E.Point3D(0,0,0), name='彩球%d' % i)
    try:
        b.add_script('count_touch', {})
        b.add_script('bounce', {'g': -9.8, 'rest': 0.7})
    except Exception as e:
        errors.append(("加彩球脚本", traceback.format_exc()))
    balls.append(b)
print("  彩球 %d 个 OK" % len(balls))

print("=== 进播放模式 ===")
try:
    ed.toggle_play()
    print("  is_playing =", ed.is_playing)
except Exception as e:
    errors.append(("toggle_play", traceback.format_exc())); print("  进入失败:", e)

print("=== 步进 90 逻辑帧 (模拟玩家按 W 前进) ===")
clk = ed._ensure_split()
try:
    for f in range(90):
        # 模拟按 W (向前) —— 直写按键状态
        try:
            ed.key_state[ed._key['CAMERA_FORWARD']] = True
        except Exception:
            pass
        # 尝试触发脚本输入
        for k in list(getattr(ed, 'script_keys', {}).keys()):
            if k in ('W','w','前进'):
                ed.script_keys[k] = True
        ed._logic_frame(clk.fixed_dt)
        if f % 30 == 0:
            print("  帧%d: 玩家=(%.2f,%.2f,%.2f) 彩球数=%d" % (
                f, player.position.x, player.position.y, player.position.z,
                sum(1 for m in ed.models if m.name.startswith('彩球'))))
except Exception as e:
    errors.append(("逻辑帧", traceback.format_exc())); print("  逻辑帧失败:", e)

print("=== 渲染 5 帧 ===")
try:
    for _ in range(5):
        now=time.perf_counter(); d=min(now-ed.last_frame_time,0.1); ed.last_frame_time=now; ed.render(d)
    print("  渲染 OK")
except Exception as e:
    errors.append(("render", traceback.format_exc())); print("  渲染失败:", e)

print("=== 退出播放模式 ===")
try:
    ed.toggle_play()
    print("  is_playing =", ed.is_playing, " 物体数 =", len(ed.models))
except Exception as e:
    errors.append(("toggle_play 退出", traceback.format_exc()))

ed._stop_parallel(); import pygame; pygame.quit()
print("")
if errors:
    print("发现 %d 个异常:" % len(errors))
    for name, tb in errors:
        print("---", name, "---")
        print(tb)
else:
    print("无异常，小游戏全程正常")
print("完成")
