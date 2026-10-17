# -*- coding: utf-8 -*-
# M38 闭环演示: 用引擎桩构建"收集金币"小游戏场景 (玩家移动+跳跃+收集金币+得分UI),
# 加密保存场景 + 写游戏配置.json. 生成到 Loom(编译版本)\示例游戏\ 供封装验证.
# 运行: py -3.12 "Loom\tests\_tmp\make_demo_game.py"
import sys, os, json
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))))
import engine as E
import sceneio as S
from mesh import create_plane, create_cube, create_sphere

OUT = r"D:\my-project\Loom(编译版本)\示例游戏"

eng = E.GLEngine.__new__(E.GLEngine)
eng.models = []; eng.materials = []; eng.lights = []
eng.cameras = []; eng.active_camera = None
eng.current_model_index = 0
E.GLEngine._build_gpu = lambda self, m: None

# 地面 (y=-2)
ground = eng.add_model(create_plane(30, 30), E.Point3D(0, -2, 0),
                       E.Point3D(0, 0, 0), name="地面")
ground.add_script('coin_game')                       # 游戏管理 (HUD 得分)

# 玩家: 立方体 + 刚体(受重力) + 第一人称控制器 (WASD+鼠标转向+跳跃)
hero = eng.add_model(create_cube(0.8), E.Point3D(0, 0, 0),
                     E.Point3D(0, 0, 0),
                     name="玩家", color="#55AAFF")
hero.add_rigidbody()
hero.add_script('first_person', {'speed': 6.0, 'eye': 1.6, 'jump_v': 7.0})

# 金币: 球体 + 碰撞事件脚本 (玩家碰到 -> 加分+消失)
for i, (x, z) in enumerate([(3, 3), (-3, 3), (3, -3), (-3, -3), (0, 5)]):
    c = eng.add_model(create_sphere(0.5), E.Point3D(x, -1.0, z),
                      E.Point3D(0, 0, 0),
                      name="金币%d" % i, color="#FFD700")
    c.add_script('coin')

# 光源
eng.add_light('directional', position=(0, 10, 0), direction=(0, -1, 0),
              shadow=False)

data = S.scene_to_dict(eng, camera={'target': (0, 0, 0), 'distance': 12,
                                    'yaw': 0.6, 'pitch': -0.3})
os.makedirs(OUT, exist_ok=True)
S.save_scene_data(os.path.join(OUT, '游戏场景.json'), data, encrypt=True)
with open(os.path.join(OUT, '游戏配置.json'), 'w', encoding='utf-8') as f:
    json.dump({'scene': '游戏场景.json'}, f, ensure_ascii=False, indent=2)
print("已生成示例游戏到:", OUT)
print("  游戏场景.json (加密) + 游戏配置.json")
print("  物体数:", len(eng.models), " 光源:", len(eng.lights))
