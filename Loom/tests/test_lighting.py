# -*- coding: utf-8 -*-
"""M20+M21 光照回归: 镜像 engine._FRAG_SRC 的 GLSL 数学, 验证默认视角下立方体
可见三面(-X/+Y/-Z)亮度互不相同. 旧兰伯特模型下 +Y 与 -Z 面 diffuse 相同(都 0.577)
亮度相等 -> 分不出边缘; 新 Blinn-Phong 必须让它们可区分.

M21 追加: 无光源时环境光压暗 (提醒用户手动加光), 点光源距离衰减.
"""
import math
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import numpy as np

ok = True
def check(label, cond, detail=""):
    global ok
    print(("PASS " if cond else "FAIL ") + label + ("  " + detail if detail else ""))
    if not cond: ok = False

# 立方体真实颜色 #FF5555: R=0xFF/255=1.0, G=B=0x55/255=0.333 (线性段直喂着色器)
CUBE_COLOR = (1.0, 1/3.0, 1/3.0)

def dir_light(direction, color=(1.0, 1.0, 1.0), intensity=1.0):
    return {'kind': 'directional', 'direction': tuple(direction),
            'position': [0, 5, 0], 'color': tuple(color), 'intensity': intensity}

def point_light(position, color=(1.0, 1.0, 1.0), intensity=1.0):
    return {'kind': 'point', 'position': list(position),
            'direction': [0, -1, 0], 'color': tuple(color), 'intensity': intensity}

# 与 M21 _FRAG_SRC 完全一致的着色 (多光源: 平行光 + 点光源); M22 加终色饱和度
def shade(n, v, pos, color=CUBE_COLOR, lights=None, ambient_scale=1.0, saturation=1.0):
    n = n / np.linalg.norm(n)
    v = v / np.linalg.norm(v)
    hemi = float(np.clip(0.5 + 0.5 * n[1], 0.0, 1.0))
    ambient = (0.02 + 0.28 * hemi) * ambient_scale
    acc = np.zeros(3)
    for L in (lights or []):
        if L['kind'] == 'point':
            to_l = np.array(L['position']) - np.array(pos)
            dist = np.linalg.norm(to_l)
            l = to_l / max(dist, 1e-4)
            diff = max(float(np.dot(n, l)), 0.0)
            atten = 1.0 / (1.0 + 0.09 * dist + 0.045 * dist * dist)
        else:
            l = -np.array(L['direction']); l = l / np.linalg.norm(l)
            diff = max(float(np.dot(n, l)), 0.0)
            atten = 1.0
        h = (l + v) / np.linalg.norm(l + v)
        spec = max(float(np.dot(n, h)), 0.0) ** 24
        acc += np.array(L['color']) * L['intensity'] * (0.60 * diff + 0.25 * spec) * atten
    rim = 0.12 * (1.0 - max(float(np.dot(n, v)), 0.0)) ** 3
    col = np.array(color, dtype=float) * (ambient + acc) + rim
    col = np.clip(col, 0.0, 1.0) ** (1.0 / 2.2)   # gamma 校正
    # 饱和度 (与 _FRAG_SRC 一致): 0=灰阶, 1=原始, >1=增艳
    lum = float(np.dot(col, np.array([0.299, 0.587, 0.114])))
    return np.clip(lum + saturation * (col - lum), 0.0, 1.0)

def shade_old(n, l, v, color=CUBE_COLOR):
    """旧模型 (回归对照): 0.2 + 0.8*diff, 无观察方向."""
    n = n / np.linalg.norm(n); l = l / np.linalg.norm(l)
    b = 0.2 + 0.8 * max(float(np.dot(n, l)), 0.0)
    return np.array(color, dtype=float) * b

# 默认相机: yaw=0.6 pitch=-0.35 dist=10 target=0 (engine.apply_orbit_camera)
yaw, pitch, dist = 0.6, -0.35, 10.0
ez = np.array([math.sin(yaw) * math.cos(pitch), math.sin(pitch),
               math.cos(yaw) * math.cos(pitch)])
cam = np.array([0.0, 0.0, 0.0]) - dist * ez

# 方向光: shader 用 l = normalize(-direction); direction=(-1,-1,1) 等价旧 l=(1,1,-1)
LIGHTS = [dir_light((-1, -1, 1))]

# 立方体: 中心 (1.2,0.75,0.3), 半边长 0.75, 红色 #FF5555=(0.55,0.33,0.33)
cc = np.array([1.2, 0.75, 0.3]); half = 0.75
faces = {
    '-X': (np.array([-1, 0, 0]), np.array([cc[0]-half, cc[1], cc[2]])),
    '+Y': (np.array([0, 1, 0]),  np.array([cc[0], cc[1]+half, cc[2]])),
    '-Z': (np.array([0, 0, -1]), np.array([cc[0], cc[1], cc[2]-half])),
    '+X': (np.array([1, 0, 0]),  np.array([cc[0]+half, cc[1], cc[2]])),
    '-Y': (np.array([0, -1, 0]), np.array([cc[0], cc[1]-half, cc[2]])),
    '+Z': (np.array([0, 0, 1]),  np.array([cc[0], cc[1], cc[2]+half])),
}

L_old = -np.array(LIGHTS[0]['direction'])      # 旧 l = (1,1,-1)/√3
L_old = L_old / np.linalg.norm(L_old)
vis = []
print("相机位置 =", cam)
for name, (n, fc) in faces.items():
    v = cam - fc                      # 面中心 -> 相机
    facing = float(np.dot(n, v)) > 0  # 朝向相机 (CULL_FACE 剔除背面)
    if facing:
        vis.append(name)
        b = shade(n, v, fc, lights=LIGHTS)
        b_old = shade_old(n, L_old, v)
        print("  %s面: 新亮度=%s  旧亮度=%s" % (name,
              "[%.3f %.3f %.3f]" % tuple(b), "[%.3f %.3f %.3f]" % tuple(b_old)))

check("默认视角可见三面 = -X/+Y/-Z", sorted(vis) == sorted(['-X', '+Y', '-Z']), str(vis))

# 核心回归: 可见三面亮度两两不同 (取 RGB 最大通道做亮度)
lum = {}
for name in vis:
    n, fc = faces[name]
    lum[name] = float(shade(n, cam - fc, fc, lights=LIGHTS).max())
print("可见面显示亮度(最大通道):", {k: round(v, 3) for k, v in lum.items()})

pairs = [('+Y', '-Z'), ('+Y', '-X'), ('-X', '-Z')]
worst = min(abs(lum[a] - lum[b]) for a, b in pairs)
check("三面亮度两两不同, 最小差 > 0.10", worst > 0.10, "worst=%.3f" % worst)

# 防爆白: 任何可见面都不能饱和到 1.0 (顶面 #FF5555 的 R=1.0 若被光照推爆会洗成白色,
# +Y/-Z 亮度差坍缩 -> 又分不出边缘)
blown = [k for k in vis if lum[k] >= 1.0 - 1e-6]
check("任何可见面都不爆白", not blown, "爆白面=" + str(blown))

# 对照: 旧模型是否真的退化 (证明 bug 存在)
lum_old = {}
for name in vis:
    n, fc = faces[name]
    lum_old[name] = float(shade_old(n, L_old, cam - fc).max())
check("旧模型 +Y/-Z 亮度相同(复现原 bug)", abs(lum_old['+Y'] - lum_old['-Z']) < 1e-9,
      "%.3f vs %.3f" % (lum_old['+Y'], lum_old['-Z']))

# ---- M21: 无光源场景压暗 (ambient_scale=0.2, 提醒用户手动加光) ----
lum_dark = {}
for name in vis:
    n, fc = faces[name]
    lum_dark[name] = float(shade(n, cam - fc, fc, lights=[], ambient_scale=0.2).max())
print("无光源显示亮度(最大通道):", {k: round(v, 3) for k, v in lum_dark.items()})
check("无光源: 最亮面明显偏暗 (< 0.45)", max(lum_dark.values()) < 0.45,
      "max=%.3f" % max(lum_dark.values()))
check("加光后最亮面 > 无光最亮面 + 0.3 (可区分有无光源)",
      max(lum.values()) > max(lum_dark.values()) + 0.3,
      "%.3f vs %.3f" % (max(lum.values()), max(lum_dark.values())))

# ---- M21: 点光源距离衰减: r 处亮度 > 2r 处 ----
n = np.array([0.0, 0.0, 1.0])
v = np.array([0.0, 0.0, 1.0])
b_near = float(shade(n, v, np.array([0, 0, 0]), lights=[point_light((0, 0, 2.0))]).max())
b_far = float(shade(n, v, np.array([0, 0, 0]), lights=[point_light((0, 0, 4.0))]).max())
check("点光源距离衰减: r=2 比 r=4 亮", b_near > b_far, "%.3f vs %.3f" % (b_near, b_far))

# ---- M22: 物体饱和度调节 (终色): 0=灰阶, 1=原始, >1=增艳 ----
nY, fcY = faces['+Y']
sy0 = shade(nY, cam - fcY, fcY, lights=LIGHTS, saturation=0.0)
sy1 = shade(nY, cam - fcY, fcY, lights=LIGHTS, saturation=1.0)
sy2 = shade(nY, cam - fcY, fcY, lights=LIGHTS, saturation=2.0)
ch = lambda x: float(np.max(x) - np.min(x))          # 彩色度 (RGB 极差)
check("饱和度0: +Y面变灰阶 (RGB 相等)", ch(sy0) < 1e-6, "ch=%.3f" % ch(sy0))
check("饱和度1: 颜色不变 (默认渲染不变)", np.allclose(sy1, shade(nY, cam - fcY, fcY, lights=LIGHTS)),
      "%.3f/%.3f/%.3f" % tuple(sy1))
check("增艳(2.0)色度 > 原始(1.0) > 灰阶(0.0)",
      ch(sy2) > ch(sy1) > ch(sy0), "%.3f/%.3f/%.3f" % (ch(sy0), ch(sy1), ch(sy2)))

# 顶点法线逆转置正确性: 非等比缩放 (2,1,0.5) 下, 逆转置方向应垂直于真实面
S = np.diag([2.0, 1.0, 0.5])
n_true = np.array([1.0, 0.0, 0.0])          # 缩放后 +X 面真实法线仍是 +X
n_it = np.linalg.inv(S.T).T @ n_true        # 逆转置
n_it = n_it / np.linalg.norm(n_it)
check("非等比缩放逆转置法线方向正确", abs(float(np.dot(n_it, [1, 0, 0])) - 1.0) < 1e-9,
      str(n_it))
n_bad = S @ n_true                          # 旧做法 mat3(M)*n (未归一), 方向仍对但长度错
n_bad = n_bad / np.linalg.norm(n_bad)
check("旧做法方向也没错(只是长度), 逆转置用于鲁棒性", abs(float(np.dot(n_bad, [1, 0, 0])) - 1.0) < 1e-9)

print()
print("总结果:", "ALL PASS ✅" if ok else "有 FAIL ❌")
