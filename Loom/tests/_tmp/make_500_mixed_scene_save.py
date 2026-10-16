# -*- coding: utf-8 -*-
r"""make_500_mixed_scene_save.py — 生成 500 混合物体压测场景 (2026-09-02).

用户指令 (2026-09-02): "500球测试是为了模拟游戏场景的大量物体渲染, 不是刷帧率;
多个相同建模复用优化正常, 但不能只盯着多相同物体场景优化。加一个测试: 多不同
物体测试, 每个物体有 10 个重复的样本, 分 50 个不同模型, 测试真正多物体场景"。

设计:
- 50 种模型规格 (46 球体 + 4 立方体), 每种 10 个样本 = 500 物体。
- 每种规格 = 独立 bucket/网格 (primitive+params 键不同): 500球场景全场景
  只 2 个桶 (球+地面), 本场景 51 个桶 → 考察"每桶少量实例"的真实游戏形状。
- 顶点总量对齐 500 球场景 (~101.7 万): 球体细分 5 档轮转
  (44x66=3015v / 40x60=2501v / 36x54=2035v / 32x48=1617v / 28x42=1247v),
  46 球规格 ≈ 96.7 万 + 立方体 960v ≈ 96.8 万。
- 其余与 压测500球.json 逐字段同构: 29x18 网格间距 2.0 / 20% rotate 脚本
  (100 个) / 地面 105x105 / 太阳+补光 / 相机距离 52.2 / v8 格式。
- 50 种颜色 (HSV 均匀采样), 同规格 10 样本同色 (颜色是实例属性, 不影响桶键)。

输出: Loom\保存\压测500混合.json (LoomHub 保存目录) + 同内容拷到
tests\_tmp\stress_500mixed.json (--bench 用, 与 500 球同款双落)。
生成后 sceneio 无头校验 (不进 GL, 不改文件)。
"""
import colorsys
import json
import math
import os
import shutil
import sys
import uuid

BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # ...\Loom
sys.path.insert(0, BASE)
os.chdir(BASE)

N_SPECS = 50
SAMPLES = 10
N_OBJECTS = N_SPECS * SAMPLES            # 500
SPACING = 2.0

SRC = os.path.join(BASE, '保存', '压测50球.json')
OUT_SAVE = os.path.join(BASE, '保存', '压测500混合.json')
OUT_BENCH = os.path.join(BASE, 'tests', '_tmp', 'stress_500mixed.json')

src = json.load(open(SRC, encoding='utf-8'))
assert src['version'] == 8

sun = next(l for l in src['lights'] if l['name'] == '太阳')
fill = next(l for l in src['lights'] if l['name'] == '补光')

# 50 种模型规格: 46 球体 (细分 5 档轮转, 半径 0.6~1.1) + 4 立方体
SPHERE_LEVELS = [(44, 66), (40, 60), (36, 54), (32, 48), (28, 42)]
specs = []                                # (type, params, est_verts)
for i in range(46):
    stacks, slices = SPHERE_LEVELS[i % len(SPHERE_LEVELS)]
    radius = round(0.6 + (i % 6) * 0.1, 1)
    specs.append(('sphere', {'radius': radius, 'stacks': stacks, 'slices': slices},
                  (stacks + 1) * (slices + 1)))
for size in (1.6, 1.3, 1.1, 0.9):
    specs.append(('cube', {'size': size}, 24))

total_verts = sum(v * SAMPLES for _, _, v in specs)
n_buckets = len(specs) + 1                # + 地面

# 50 种颜色: HSV 均匀色相, 高饱和 (肉眼可辨不同模型)
def hex_color(t):
    r, g, b = colorsys.hsv_to_rgb(t, 0.55, 0.85)
    return "#%02x%02x%02x" % (int(r * 255), int(g * 255), int(b * 255))

cols_n = int(math.ceil(math.sqrt(N_OBJECTS * 1.6)))   # 29 (与 500 球同)
rows_n = int(math.ceil(N_OBJECTS / float(cols_n)))    # 18
span = max(cols_n, rows_n) * SPACING
ground_size = float(min(200.0, math.ceil(span * 1.8)))
cam_dist = max(32.0, span * 0.9)

def gid():
    return uuid.uuid4().hex

objects = []
n_script = 0
k = 0
for si, (typ, params, _v) in enumerate(specs):
    for j in range(SAMPLES):
        r, c = divmod(k, cols_n)
        x = (c - (cols_n - 1) / 2.0) * SPACING
        z = (r - (rows_n - 1) / 2.0) * SPACING
        scripts = [{"id": "rotate", "vars": {"sx": 90.0, "sy": 40.0, "sz": 0.0}}] \
            if k % 5 == 0 else []
        n_script += 1 if scripts else 0
        if typ == 'sphere':
            y = params['radius']
            collider = {"shape": "sphere", "enabled": True}
        else:
            y = params['size'] / 2.0
            collider = {"shape": "box", "enabled": True}
        objects.append({
            "id": gid(), "parent_id": None, "prefab_ref": None,
            "name": "物体%d" % k, "type": typ, "params": dict(params),
            "position": [float(x), y, float(z)],
            "rotation": [0.0, 0.0, 0.0], "scale": [1.0, 1.0, 1.0],
            "color": hex_color(si / float(N_SPECS)),
            "material_id": None, "normal_mode": "vertex" if typ == 'sphere' else 'flat',
            "saturation": 1.0, "visible": True, "scripts": scripts,
            "collider": collider, "rigidbody": None,
            "audio_source": None, "animator": None,
        })
        k += 1

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

for out in (OUT_SAVE, OUT_BENCH):
    with open(out, 'w', encoding='utf-8') as f:
        json.dump(scene, f, ensure_ascii=False, indent=1)

print("已生成: %s" % OUT_SAVE)
print("已生成: %s" % OUT_BENCH)
print("  物体: %d (%d 种模型 x %d 样本) | 旋转脚本 %d (20%%)"
      % (N_OBJECTS, N_SPECS, SAMPLES, n_script))
print("  顶点总量: %d (500球场景 = %d, 占比 %.0f%%)"
      % (total_verts, 500 * 2035, total_verts / (500.0 * 2035) * 100))
print("  桶数(不同网格): %d (500球场景 = 2: 球+地面)" % n_buckets)
print("  地面: %.0fx%.0f | 相机距离 %.1f | 网格 %dx%d"
      % (ground_size, ground_size, cam_dist, cols_n, rows_n))

# ---- 校验: sceneio 真实加载 (无头, 不进 GL) ----
import sceneio  # noqa: E402
data = sceneio.load_scene_data(OUT_SAVE)
n = len(data.get('objects', []))
ok = (n == N_OBJECTS + 1)
print("sceneio 校验: version=%d objects=%d (期望 %d) -> %s"
      % (data.get('version'), n, N_OBJECTS + 1, "PASS" if ok else "FAIL"))
sys.exit(0 if ok else 1)
