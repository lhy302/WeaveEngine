# -*- coding: utf-8 -*-
"""mini_game_full.py — 小游戏全面实测 (含本轮贴图/PBR/LOD 新功能)"""
import os, sys, time, traceback
BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, BASE); os.chdir(BASE)
sys.argv[0] = os.path.join(BASE, 'Loom.py')
import numpy as np, moderngl, editor as editor_mod
import engine as E
from mesh import create_plane, create_sphere
from loom_texture import Texture
from loom_material import Material
from loom_cubemap import Cubemap

errors = []
ctx = moderngl.create_standalone_context()
ed = editor_mod.EditorApp(640, 480, ctx=ctx); ed._external_fb = ctx.detect_framebuffer()
try:
    _g = ed.view.gui.render; ed.view.gui.render = lambda *a, **k: _g(target=ed._external_fb)
except Exception: pass
ed.load_scene(os.path.join(BASE, '保存', '压力测试', '压力_空场景.json'))

def step(n=1):
    for _ in range(n):
        now=time.perf_counter(); d=min(now-ed.last_frame_time,0.1); ed.last_frame_time=now; ed.render(d)

print("=== 1. 建场景 (含贴图/PBR 玩家 + LOD 彩球) ===")
ground = ed.add_model(create_plane(20,20), E.Point3D(0,0,0), E.Point3D(0,0,0), name='地面')
# 棋盘贴图地面材质
arr = np.zeros((32,32,4), dtype=np.uint8)
for y in range(32):
    for x in range(32):
        arr[y,x] = [80,80,90,255] if ((x//4)+(y//4))%2==0 else [60,60,70,255]
gtex = Texture.from_rgba(32,32,arr, name='地砖', compression='rgb565',
                         wrap='repeat', filter_mode='trilinear')
ground.renderer.material = Material(name='地砖材质', albedo=gtex)
player = ed.add_model(create_sphere(0.5,12,16), E.Point3D(0,0.5,0), E.Point3D(0,0,0), name='玩家')
player.renderer.material = Material(name='玩家材质', color='#44AAFF', pbr=True, metallic=0.6, roughness=0.3)
player.add_script('wasd_move', {'speed': 4.0})
player.add_script('camera_follow', {'oy': 3.0})
hi = create_sphere(0.4,12,16); lo = create_sphere(0.4,5,7)
balls = []
for i,pos in enumerate([(0,0.4,3), (0,0.4,6), (0,0.4,9)]):
    b = ed.add_model(hi, E.Point3D(*pos), E.Point3D(0,0,0), name='彩球%d'%i)
    b.renderer.material = Material(name='彩球材质%d'%i, color='#FF5555', pbr=True, metallic=0.2, roughness=0.5)
    b.renderer.lod_screen_levels = [(0.15, hi), (0.0, lo)]
    b.renderer.env_map = Cubemap.from_solid('#334466', size=16)
    b.add_script('count_touch', {})
    balls.append(b)
step(10)
print("  场景 OK: %d 物体, 3 彩球" % len(ed.models))

print("=== 2. 进播放 + 移动触碰 ===")
try:
    ed.toggle_play()
    clk = ed._ensure_split()
    hits = 0
    for f in range(180):
        ed.script_keys = {'w': True}          # 模拟按 W 前进 (向前)
        ed._logic_frame(clk.fixed_dt)
        remaining = sum(1 for m in ed.models if m.name.startswith('彩球'))
        hits = 3 - remaining
        if f % 60 == 0:
            print("  帧%d 玩家=(%.2f,%.2f,%.2f) 已碰=%d 剩余=%d" % (
                f, player.position.x, player.position.y, player.position.z, hits, remaining))
    step(5)
    print("  移动/碰撞 OK, 最终碰到 %d 彩球" % hits)
except Exception as e:
    errors.append(("播放移动", traceback.format_exc())); print("  失败:", e)

print("=== 3. 播放期存场景 (含贴图/PBR) ===")
try:
    sp = os.path.join(BASE, 'tests','_tmp','_mini_game.json')
    from sceneio import save_scene_data, scene_to_dict
    save_scene_data(sp, scene_to_dict(ed))
    print("  保存 OK:", os.path.getsize(sp), "字节")
    ed.toggle_play()
    print("  退出播放 OK, 物体=%d" % len(ed.models))
except Exception as e:
    errors.append(("存场景", traceback.format_exc())); print("  失败:", e)

print("=== 4. 重载场景 (贴图/PBR 恢复) ===")
try:
    ed.load_scene(sp)
    step(5)
    mats = ed.materials
    pbr_mats = [m for m in mats if getattr(m,'pbr',False)]
    tex_mats = [m for m in mats if getattr(m,'albedo',None) is not None]
    print("  重载 OK: %d 物体 %d 材质 (%d PBR, %d 贴图)" % (
        len(ed.models), len(mats), len(pbr_mats), len(tex_mats)))
except Exception as e:
    errors.append(("重载", traceback.format_exc())); print("  失败:", e)

print("=== 5. 连续渲染 30 帧 (稳定性) ===")
try:
    for _ in range(30): step(1)
    print("  30 帧 OK")
except Exception as e:
    errors.append(("连续渲染", traceback.format_exc())); print("  失败:", e)

ed._stop_parallel(); import pygame; pygame.quit()
print("")
if errors:
    print("发现 %d 个异常:" % len(errors))
    for name, tb in errors:
        print("---", name, "---"); print(tb)
else:
    print("无异常，小游戏全程正常")
print("完成")
