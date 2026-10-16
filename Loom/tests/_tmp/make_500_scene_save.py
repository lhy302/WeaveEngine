# -*- coding: utf-8 -*-
r"""make_500_scene_save.py — 生成 500 球压测场景到 Loom\保存\压测500球.json (2026-08-31).

用户指令: "操作 LoomHub 启动 Loom 的五十球压测场景改造成 500 球压测场景然后保存"
—— 直接在 保存\压测50球.json (用户实测 195FPS 的那份) 的设计基础上等比扩展
到 500 球, 存为 保存\压测500球.json (LoomHub 保存目录, Loom 打开场景对话框
默认可达), 保持 v8 格式与 50 球逐字段同构。

布局: 500 球 29x18 网格 (间距 2.0), 20% 挂 rotate 脚本 (同 50 球的 10/50 比例),
地面放大到 105x105 覆盖全场, 相机距离拉远 (52.2) 收全场。
生成后用 sceneio 校验加载 (不改任何文件)。
"""
import json
import math
import os
import sys
import uuid

BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # ...\Loom
sys.path.insert(0, BASE)
os.chdir(BASE)

N_BALLS = 500
STACKS, SLICES = 36, 54          # 同 50 球: (37*55)=2035 顶点/球 3888 面
RADIUS = 0.8
SPACING = 2.0

SRC = os.path.join(BASE, '保存', '压测50球.json')
OUT = os.path.join(BASE, '保存', '压测500球.json')

src = json.load(open(SRC, encoding='utf-8'))
assert src['version'] == 8

# 光源/相机骨架直接取自 50 球原文件 (id 保留同款结构)
sun = next(l for l in src['lights'] if l['name'] == '太阳')
fill = next(l for l in src['lights'] if l['name'] == '补光')

# 布局参数
cols = int(math.ceil(math.sqrt(N_BALLS * 1.6)))   # 29
rows = int(math.ceil(N_BALLS / cols))             # 18
span = max(cols, rows) * SPACING                  # 58
ground_size = float(min(200.0, math.ceil(span * 1.8)))   # 105
cam_dist = max(32.0, span * 0.9)                  # 52.2

row_colors = ["#e05a5a", "#e08a4a", "#e0c04a", "#5ab85a", "#5a9ae0"]

def gid():
    return uuid.uuid4().hex

objects = []
n_script = 0
for k in range(N_BALLS):
    r, c = divmod(k, cols)
    x = (c - (cols - 1) / 2.0) * SPACING
    z = (r - (rows - 1) / 2.0) * SPACING
    # 20% 挂 rotate 脚本 (50 球同比例: 每 5 个取 1, 压脚本专用线程)
    scripts = [{"id": "rotate", "vars": {"sx": 90.0, "sy": 40.0, "sz": 0.0}}] \
        if k % 5 == 0 else []
    n_script += 1 if scripts else 0
    objects.append({
        "id": gid(),
        "parent_id": None,
        "prefab_ref": None,
        "name": "球%d" % k,
        "type": "sphere",
        "params": {"radius": RADIUS, "stacks": STACKS, "slices": SLICES},
        "position": [float(x), RADIUS, float(z)],
        "rotation": [0.0, 0.0, 0.0],
        "scale": [1.0, 1.0, 1.0],
        "color": row_colors[r % len(row_colors)],
        "material_id": None,
        "normal_mode": "vertex",
        "saturation": 1.0,
        "visible": True,
        "scripts": scripts,
        "collider": {"shape": "sphere", "enabled": True},
        "rigidbody": None,
        "audio_source": None,
        "animator": None,
    })

# 地面 (覆盖全场, 同 50 球设计)
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

scene = {
    "version": 8,
    "camera": {"target": [0.0, 2.0, 0.0], "distance": cam_dist,
               "yaw": 0.7, "pitch": -0.38},
    "materials": [],
    "lights": [sun, fill],
    "cameras": [],
    "active_camera": None,
    "objects": objects,
}

with open(OUT, 'w', encoding='utf-8') as f:
    json.dump(scene, f, ensure_ascii=False, indent=1)

print("已生成: %s" % OUT)
print("  球: %d 个 (%dx%d 网格, %d 顶点/球 = %d 顶点总量) + 旋转脚本 %d"
      % (N_BALLS, cols, rows, (STACKS + 1) * (SLICES + 1),
         N_BALLS * (STACKS + 1) * (SLICES + 1), n_script))
print("  地面: %.0fx%.0f | 相机距离 %.1f | 光源: 太阳(shadow) + 补光"
      % (ground_size, ground_size, cam_dist))

# ---- 校验: sceneio 真实加载 (无头, 不进 GL) ----
import sceneio  # noqa: E402
data = sceneio.load_scene_data(OUT)
n = len(data.get('objects', []))
print("sceneio 校验: version=%d objects=%d (500 球+1 地面=%d) -> %s"
      % (data.get('version'), n, N_BALLS + 1,
         "PASS" if n == N_BALLS + 1 else "FAIL"))
