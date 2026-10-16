# -*- coding: utf-8 -*-
"""探针: 第一人称玩家控制器真实窗口验证.
EditorApp 加地面+角色(刚体+first_person脚本), 进播放跑 60 帧:
角色受重力下落停地面; 相机接管(orbit_mode 关). 不崩 = 通过.
运行: py -3.12 "Loom\tests\_tmp\player_probe.py" (子进程+超时)"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))))
os.chdir(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
import pygame
import editor
from mesh import create_plane, create_cube

e = editor.EditorApp(640, 480)
e.clear_scene()
e.add_model(create_plane(10, 10), editor.Point3D(0, -2, 0), editor.Point3D(0, 0, 0), name="地面")
hero = e.add_model(create_cube(0.8), editor.Point3D(0, 1.0, 0), editor.Point3D(0, 0, 0), name="角色")
hero.add_rigidbody()
hero.add_script('first_person')
e.add_light('directional', position=(0, 8, 0), direction=(0, -1, 0), shadow=False)
e.toggle_play()                       # 进入播放
for _ in range(90):
    e.render(0.016)                   # ~1.5s 播放帧
y_play = hero.position.y
orbit_play = e.orbit_mode
print("播放期 角色 y = %.3f (应停地面 ~-1.6, 立方体半高0.4 贴 y=-2 地面)" % y_play)
print("播放期 orbit_mode = %s (first_person 应关闭轨道相机)" % orbit_play)
print("播放期 相机位置 = " + str(tuple(round(x, 2) for x in e.camera)))
e.toggle_play()                       # 退出播放
print("退出播放 角色 y = %.3f (应还原 1.0)" % hero.position.y)
ok_play = abs(y_play - (-1.6)) < 0.1 and orbit_play is False
ok_exit = abs(hero.position.y - 1.0) < 0.01 and e.orbit_mode is True
print("RESULT:", "PASS" if ok_play and ok_exit else "FAIL",
      " 播放期落地面=%.3f orbit=%s | 退出还原=%.3f orbit=%s"
      % (y_play, orbit_play, hero.position.y, e.orbit_mode))
import pygame as _p; _p.quit()
