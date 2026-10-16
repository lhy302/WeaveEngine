# -*- coding: utf-8 -*-
"""stress_scene.py — 高面数球压测场景生成 (2026-08-15 8 核均摊压力测试).

用法: py -3.12 tests/_tmp/stress_scene.py [球数]
  默认 50 (stress_50spheres.json, 历史基线场景, 8 核均摊探针用);
  2026-08-31 组6 后用户指令扩展 500 球 ("现代游戏场景负载量级"):
  py -3.12 tests\_tmp\stress_scene.py 500  ->  stress_500spheres.json

生成 v8 场景 JSON -> tests/_tmp/stress_<N>spheres.json:
  - N 个静态高面数球 (stacks=36/slices=54, 圆润+压测负载) 网格铺开
  - 20% 球挂 rotate 脚本 (压脚本专用线程, 属"拆不动的 GIL 任务", 允许个别核偏高)
  - 全静态: 不用下落刚体 (move_with_collision 对高面数球 O(N×V) 每子步重算包围盒,
    会拖死压测; 稳态负载 = 并行 AABB(阴影) + 并行碰撞事件 + 脚本 + 高面数 GL)
  - 1 个阴影平行光 (full 模式 -> 压场景包围盒 AABB 并行) + 1 个点光源
纯 Python 生成, 无需 GL. 加载/压测见 stress_probe.py.
"""
import json
import math
import os
import sys
import uuid

DIR = os.path.dirname(os.path.abspath(__file__))

STACKS, SLICES = 36, 54          # 高面数: (37*55)=2035 顶点 / 3888 面每球
RADIUS = 0.8
SPACING = 2.0


def make_scene(n_balls):
    """生成 n_balls 球压测场景 dict (50/500 同一设计等比扩展)."""
    cols = int(math.ceil(math.sqrt(n_balls * 1.6)))   # 网格比例 ~1.6:1 (50=10x5, 500=29x18)
    rows = int(math.ceil(n_balls / cols))
    out = os.path.join(DIR, 'stress_%dspheres.json' % n_balls)

    def gid():
        return uuid.uuid4().hex

    def make_sphere(name, pos, color, row, scripts=None):
        return {
            "id": gid(),
            "parent_id": None,
            "prefab_ref": None,
            "name": name,
            "type": "sphere",
            "params": {"radius": RADIUS, "stacks": STACKS, "slices": SLICES},
            "position": [float(pos[0]), float(pos[1]), float(pos[2])],
            "rotation": [0.0, 0.0, 0.0],
            "scale": [1.0, 1.0, 1.0],
            "color": color,
            "material_id": None,
            "normal_mode": "vertex",        # 光滑球面 (径向法线), 更圆润
            "saturation": 1.0,
            "visible": True,
            "scripts": scripts or [],
            "collider": {"shape": "sphere", "enabled": True},
            "rigidbody": None,
            "audio_source": None,
            "animator": None,
        }

    # N 个静态球网格 + 渐变色 (按行, 5 色循环)
    # 说明: 全静态, 不用下落刚体 —— move_with_collision 对高面数球是 O(N×V) 每子步
    # 重算包围盒, 会把压测拖死; 稳态负载由"并行 AABB(阴影) + 并行碰撞事件 + 旋转
    # 脚本 + 高面数 GL 渲染"构成. 20% 挂 rotate 脚本压脚本专用线程.
    row_colors = ["#e05a5a", "#e08a4a", "#e0c04a", "#5ab85a", "#5a9ae0"]
    objects = []
    n_script = 0
    for k in range(n_balls):
        r, c = divmod(k, cols)
        x = (c - (cols - 1) / 2.0) * SPACING
        z = (r - (rows - 1) / 2.0) * SPACING
        # 20% 球挂 rotate (每 5 个取 1), 压脚本专用线程 (GIL 任务, 允许个别核偏高)
        scripts = [{"id": "rotate", "vars": {"sx": 90.0, "sy": 40.0, "sz": 0.0}}] \
            if k % 5 == 0 else []
        n_script += 1 if scripts else 0
        objects.append(make_sphere("球%d" % k, (x, RADIUS, z),
                                   row_colors[r % len(row_colors)], r, scripts))

    # 地面 (覆盖整个网格: 网格对角 x2 + 余量)
    span = max(cols, rows) * SPACING
    ground_size = float(min(200.0, math.ceil(span * 1.8)))
    objects.append({
        "id": gid(), "parent_id": None, "prefab_ref": None, "name": "地面",
        "type": "plane",
        "params": {"width": ground_size, "depth": ground_size},
        "position": [0.0, 0.0, 0.0], "rotation": [0.0, 0.0, 0.0],
        "scale": [1.0, 1.0, 1.0], "color": "#6a6a72", "material_id": None,
        "normal_mode": "flat", "saturation": 1.0, "visible": True,
        "scripts": [], "collider": {"shape": "box", "enabled": True},
        "rigidbody": None, "audio_source": None, "animator": None,
    })

    lights = [
        {"id": gid(), "name": "太阳", "kind": "directional",
         "position": [0.0, 12.0, 0.0], "direction": [0.0, -1.0, 0.0],
         "azimuth": 30.0, "elevation": -55.0, "roll": 0.0,
         "color": [1.0, 1.0, 1.0], "intensity": 1.1,
         "mode": "full", "shape": "circle", "size": 8.0, "shadow": True},
        {"id": gid(), "name": "补光", "kind": "point",
         "position": [10.0, 6.0, 10.0], "direction": [0.0, 0.0, 0.0],
         "azimuth": None, "elevation": None, "roll": None,
         "color": [0.9, 0.9, 1.0], "intensity": 0.9,
         "mode": "full", "shape": "circle", "size": 5.0, "shadow": False},
    ]

    scene = {
        "version": 8,
        "camera": {"target": [0.0, 2.0, 0.0],
                   "distance": max(32.0, span * 0.9),
                   "yaw": 0.7, "pitch": -0.38},
        "materials": [],
        "lights": lights,
        "cameras": [],
        "active_camera": None,
        "objects": objects,
    }

    with open(out, 'w', encoding='utf-8') as f:
        json.dump(scene, f, ensure_ascii=False, indent=1)

    print("已生成 %s" % out)
    print("  球体: %d 个 (%dx%d 网格, 高面数 %dx%d=%d 顶点/球 = %d 顶点总量), "
          "静态 %d + 旋转脚本 %d"
          % (n_balls, cols, rows, STACKS, SLICES, (STACKS + 1) * (SLICES + 1),
             n_balls * (STACKS + 1) * (SLICES + 1), n_balls, n_script))
    print("  地面: %.0fx%.0f | 光源: 1 阴影平行光(full) + 1 点光源 | 相机距离 %.1f"
          % (ground_size, ground_size, scene['camera']['distance']))


if __name__ == '__main__':
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 50
    make_scene(n)
