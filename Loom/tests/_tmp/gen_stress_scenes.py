# -*- coding: utf-8 -*-
"""gen_stress_scenes.py — Loom 压力测试场景生成器 (2026-10-14)

按 Unity 官方 Benchmark 思路: 每个场景针对一个子系统施压, 而非一个场景测所有。
输出到 保存/压力测试/ 目录。纯生成, 不改引擎。
"""
import json
import os
import uuid

BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
OUT = os.path.join(BASE, '保存', '压力测试')
os.makedirs(OUT, exist_ok=True)


def gid():
    return uuid.uuid4().hex


def ground(size=120.0, name='地面'):
    return {
        "id": gid(), "parent_id": None, "prefab_ref": None,
        "name": name, "type": "plane", "params": {"width": size, "depth": size},
        "position": [0.0, 0.0, 0.0], "rotation": [0.0, 0.0, 0.0], "scale": [1.0, 1.0, 1.0],
        "color": "#3a4a3a", "material_id": None, "normal_mode": "flat",
        "saturation": 1.0, "visible": True, "scripts": [],
        "collider": {"shape": "box", "enabled": True, "friction": 0.5,
                     "restitution": 0.0, "rolling_friction": 0.1},
        "rigidbody": None, "audio_source": None, "animator": None,
    }


def obj(name, typ, params, pos, color=None, normal='flat',
        collider=None, rigidbody=None, scripts=None, animator=None):
    return {
        "id": gid(), "parent_id": None, "prefab_ref": None,
        "name": name, "type": typ, "params": params,
        "position": list(pos), "rotation": [0.0, 0.0, 0.0], "scale": [1.0, 1.0, 1.0],
        "color": color, "material_id": None, "normal_mode": normal,
        "saturation": 1.0, "visible": True,
        "scripts": scripts or [],
        "collider": collider or {"shape": "box", "enabled": True, "friction": 0.5,
                                 "restitution": 0.0, "rolling_friction": 0.1},
        "rigidbody": rigidbody,
        "audio_source": None, "animator": animator,
    }


def sun(shadow=True):
    return {"id": gid(), "name": "太阳", "kind": "directional",
            "position": [0.0, 30.0, 0.0], "direction": [0.0, -1.0, 0.0],
            "azimuth": 30.0, "elevation": -55.0, "roll": 0.0,
            "color": [1.0, 1.0, 1.0], "intensity": 1.1,
            "mode": "full", "shape": "circle", "size": 20.0, "shadow": shadow}


def point_light(pos, color=(0.9, 0.9, 1.0)):
    return {"id": gid(), "name": "点光", "kind": "point",
            "position": list(pos), "direction": [0.0, 0.0, 0.0],
            "azimuth": None, "elevation": None, "roll": None,
            "color": list(color), "intensity": 0.9,
            "mode": "full", "shape": "circle", "size": 10.0, "shadow": False}


def scene(objs, lights, camera=None):
    return {
        "version": 8,
        "camera": camera or {"target": [0.0, 1.0, 0.0], "distance": 60.0,
                             "yaw": 0.7, "pitch": -0.45},
        "materials": [], "lights": lights, "cameras": [], "active_camera": None,
        "objects": objs,
    }


def save(name, data):
    p = os.path.join(OUT, name)
    with open(p, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False)
    print("  %-32s %d objects" % (name, len(data['objects'])), flush=True)


# ---- 1. 空场景基线 ----
save('压力_空场景.json', scene([ground()], [sun()]))

# ---- 2. 渲染·实例化: 2000 个相同球 (同网格同色 -> 1 桶) ----
objs = [ground(200)]
for i in range(2000):
    r, c = divmod(i, 45)
    x = (c - 22) * 2.0
    z = (r - 22) * 2.0
    objs.append(obj('球%d' % i, 'sphere', {"radius": 0.7, "stacks": 20, "slices": 30},
                    (x, 0.7, z), color='#e05a5a', normal='vertex',
                    collider={"shape": "sphere", "enabled": True, "friction": 0.5,
                              "restitution": 0.0, "rolling_friction": 0.1}))
save('压力_渲染_实例化2000球.json', scene(objs, [sun()]))

# ---- 3. 渲染·多材质: 1000 个不同色立方体 (1000 种颜色 -> 多桶/多 draw) ----
objs = [ground(200)]
for i in range(1000):
    r, c = divmod(i, 32)
    x = (c - 16) * 3.0
    z = (r - 16) * 3.0
    col = '#%02x%02x%02x' % ((i * 37) % 256, (i * 91) % 256, (i * 151) % 256)
    objs.append(obj('方块%d' % i, 'cube', {"size": 1.2},
                    (x, 0.6, z), color=col, normal='flat'))
save('压力_渲染_多材质1000方块.json', scene(objs, [sun()]))

# ---- 4. 物理·纯动态: 1200 个带刚体的球 (散布, 有地面承接) ----
objs = [ground(300)]
for i in range(1200):
    r, c = divmod(i, 35)
    x = (c - 17) * 3.0
    z = (r - 17) * 3.0
    objs.append(obj('刚体球%d' % i, 'sphere', {"radius": 0.6, "stacks": 16, "slices": 24},
                    (x, 3.0 + (i % 5) * 2.0, z), color='#5a8ae0', normal='vertex',
                    collider={"shape": "sphere", "enabled": True, "friction": 0.5,
                              "restitution": 0.3, "rolling_friction": 0.1},
                    rigidbody={"mass": 1.0, "use_gravity": True, "is_kinematic": False,
                               "friction": 0.5, "restitution": 0.3, "rolling_friction": 0.1}))
save('压力_物理_动态1200刚体.json', scene(objs, [sun()]))

# ---- 5. 物理·混合: 600 静态 + 600 动态 ----
objs = [ground(300)]
for i in range(600):
    r, c = divmod(i, 25)
    x = (c - 12) * 4.0
    z = (r - 12) * 4.0
    objs.append(obj('静态%d' % i, 'cube', {"size": 1.5}, (x, 0.75, z), color='#888888'))
for i in range(600):
    r, c = divmod(i, 25)
    x = (c - 12) * 4.0 + 2.0
    z = (r - 12) * 4.0 + 2.0
    objs.append(obj('动态%d' % i, 'sphere', {"radius": 0.6, "stacks": 16, "slices": 24},
                    (x, 4.0, z), color='#e0a05a', normal='vertex',
                    collider={"shape": "sphere", "enabled": True, "friction": 0.5,
                              "restitution": 0.4, "rolling_friction": 0.1},
                    rigidbody={"mass": 1.0, "use_gravity": True, "is_kinematic": False,
                               "friction": 0.5, "restitution": 0.4, "rolling_friction": 0.1}))
save('压力_物理_混合600静600动.json', scene(objs, [sun()]))

# ---- 6. 脚本·大量自转: 1000 个 rotate 脚本 ----
objs = [ground(200)]
for i in range(1000):
    r, c = divmod(i, 32)
    x = (c - 16) * 3.0
    z = (r - 16) * 3.0
    objs.append(obj('脚本方块%d' % i, 'cube', {"size": 1.0}, (x, 1.0, z),
                    color='#8ae05a', scripts=[{"id": "rotate", "vars": {"sx": 45.0, "sy": 90.0, "sz": 0.0}}]))
save('压力_脚本_自转1000.json', scene(objs, [sun()]))

# ---- 7. 动画·大量: 400 个关键帧动画立方体 (位置上下浮动) ----
def anim_clip():
    frames = []
    for k in range(11):
        t = k * 0.5
        y = 1.0 + 2.0 * (k % 2)
        frames.append({"time": t, "position": [0.0, y, 0.0],
                       "rotation": [0.0, t * 1.5, 0.0], "scale": [1.0, 1.0, 1.0]})
    return {"current": "bob", "loop": True, "clips": {"bob": frames}}

objs = [ground(200)]
for i in range(400):
    r, c = divmod(i, 20)
    x = (c - 10) * 4.0
    z = (r - 10) * 4.0
    objs.append(obj('动画%d' % i, 'cube', {"size": 1.0}, (x, 1.0, z),
                    color='#e05ae0', animator=anim_clip()))
save('压力_动画_400关键帧.json', scene(objs, [sun()]))

# ---- 8. 综合·小镇: 全类型混合 ~2200 (模拟 Unity 场景资产构成) ----
objs = [ground(400, '城镇地面')]
# 建筑结构: 50 个大小不一的立方体楼
for i in range(50):
    r, c = divmod(i, 10)
    x = (c - 5) * 40.0
    z = (r - 5) * 40.0
    h = 4.0 + (i % 5) * 3.0
    objs.append(obj('楼%d' % i, 'cube', {"size": 1.0},
                    (x, h / 2, z), color='#7a7a8a',
                    collider={"shape": "box", "enabled": True, "friction": 0.6,
                              "restitution": 0.0, "rolling_friction": 0.1}))
    objs[-1]["scale"] = [8.0, h, 8.0]
# 道具: 800 个小方块/球 (路灯/箱子/桶)
for i in range(800):
    r, c = divmod(i, 29)
    x = (c - 14) * 6.0 + (i % 3)
    z = (r - 14) * 6.0 + (i % 5)
    if i % 2 == 0:
        objs.append(obj('箱子%d' % i, 'cube', {"size": 1.0}, (x, 0.5, z), color='#b08050'))
    else:
        objs.append(obj('桶%d' % i, 'sphere', {"radius": 0.5, "stacks": 12, "slices": 18},
                        (x, 0.5, z), color='#c05050', normal='vertex'))
# 脚本物: 300 个自转 (旋转招牌)
for i in range(300):
    r, c = divmod(i, 18)
    x = (c - 9) * 12.0
    z = (r - 9) * 12.0
    objs.append(obj('招牌%d' % i, 'cube', {"size": 0.8}, (x, 3.0, z), color='#50c080',
                    scripts=[{"id": "rotate", "vars": {"sy": 120.0}}]))
# 动态: 500 个下落的球 (物理)
for i in range(500):
    r, c = divmod(i, 23)
    x = (c - 11) * 8.0
    z = (r - 11) * 8.0
    objs.append(obj('动态球%d' % i, 'sphere', {"radius": 0.5, "stacks": 14, "slices": 20},
                    (x, 8.0 + (i % 4) * 3.0, z), color='#e0c050', normal='vertex',
                    collider={"shape": "sphere", "enabled": True, "friction": 0.4,
                              "restitution": 0.4, "rolling_friction": 0.1},
                    rigidbody={"mass": 1.0, "use_gravity": True, "is_kinematic": False,
                               "friction": 0.4, "restitution": 0.4, "rolling_friction": 0.1}))
# 动画: 150 个
for i in range(150):
    r, c = divmod(i, 13)
    x = (c - 6) * 15.0
    z = (r - 6) * 15.0
    objs.append(obj('动画%d' % i, 'cube', {"size": 0.8}, (x, 2.0, z), color='#e05ae0',
                    animator=anim_clip()))
cam = {"target": [0.0, 6.0, 0.0], "distance": 120.0, "yaw": 0.7, "pitch": -0.4}
save('压力_综合_小镇.json', scene(objs, [sun(), point_light([30, 15, 30]),
                                          point_light([-30, 15, -30], (1.0, 0.8, 0.6))], camera=cam))

print("\n输出目录:", OUT, flush=True)
