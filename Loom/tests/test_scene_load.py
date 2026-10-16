# -*- coding: utf-8 -*-
"""M37 多场景/场景切换: engine.load_scene 清空并加载新场景 (物体/光源), 坏文件容错."""
import sys, os, json, tempfile
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import engine as E
import sceneio as S
from mesh import create_cube

ok = True
def check(label, cond, detail=""):
    global ok
    print(("PASS " if cond else "FAIL ") + label + ("  " + detail if detail else ""))
    if not cond: ok = False

def new_eng():
    e = E.GLEngine.__new__(E.GLEngine)
    e.models = []; e.materials = []; e.lights = []
    e.cameras = []; e.active_camera = None
    e.current_model_index = 0
    return e

E.GLEngine._build_gpu = lambda self, m: None

# 造一个源场景 (立方体 + 平行光), 存成场景文件
eng = new_eng()
eng.add_model(create_cube(1.0), E.Point3D(0, 0, 0), E.Point3D(0, 0, 0), name="关卡物体")
eng.add_light('directional', position=(0, 5, 0), direction=(0, -1, 0))
data = S.scene_to_dict(eng, camera={'target': (0, 0, 0), 'distance': 10.0,
                                    'yaw': 0.6, 'pitch': -0.35})
tmp = tempfile.mktemp(suffix='.json')
with open(tmp, 'w', encoding='utf-8') as f:
    json.dump(data, f, ensure_ascii=False)

# load_scene 到空引擎
eng2 = new_eng()
ok2 = eng2.load_scene(tmp)
check("load_scene 加载物体", ok2 and len(eng2.models) == 1, str(len(eng2.models)))
check("load_scene 加载光源", len(eng2.lights) == 1, str(len(eng2.lights)))
check("load_scene 物体名保留", eng2.models[0].name == "关卡物体", eng2.models[0].name)

# 先放些物体再 load_scene -> 应被清空替换
eng2.add_model(create_cube(1.0), E.Point3D(5, 5, 5), E.Point3D(0, 0, 0))
eng2.load_scene(tmp)
check("load_scene 清空替换旧场景", len(eng2.models) == 1, str(len(eng2.models)))

# 坏文件 / 非 dict -> False
check("load_scene 缺失文件返回 False", eng2.load_scene(tmp + '.nope') is False)
with open(tmp, 'w', encoding='utf-8') as f:
    f.write("{broken json")
check("load_scene 坏 JSON 返回 False", eng2.load_scene(tmp) is False)

# ---- M38 场景加密 (混淆保存 / 解密加载 / 明文兼容) ----
gdata = {"version": 8, "camera": None, "materials": [], "lights": [],
         "cameras": [], "active_camera": None,
         "objects": [{"id": "o1", "name": "秘密物体", "type": "cube",
                      "params": {"size": 1.0}}]}
enc = tempfile.mktemp(suffix='.json')
S.save_scene_data(enc, gdata, encrypt=True)
raw = open(enc, 'r', encoding='utf-8').read()
check("场景加密: 混淆后非明文 (LOOMSC 头)", raw.startswith('LOOMSC1')
      and '秘密物体' not in raw, raw[:20])
check("场景加密: 解密回读一致", S.load_scene_data(enc) == gdata)
plain = tempfile.mktemp(suffix='.json')
S.save_scene_data(plain, gdata, encrypt=False)
check("场景明文: 可读回", S.load_scene_data(plain) == gdata)
check("场景坏文件: None", S.load_scene_data(enc + '.nope') is None)
# 引擎加载加密场景
e3 = new_eng()
ok3 = e3.load_scene(enc)
check("引擎加载加密场景", ok3 and len(e3.models) == 1, str(len(e3.models)))

print()
print("总结果:", "ALL PASS ✅" if ok else "有 FAIL ❌")
sys.exit(0 if ok else 1)
