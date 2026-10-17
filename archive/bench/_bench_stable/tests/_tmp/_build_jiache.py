# -*- coding: utf-8 -*-
"""
_build_jiache.py — 用 Blender 4.5 headless 建"和平精英假车库"obj (测试 Loom obj 导入用)
====================================================================================
对照攻略结构 (2026-08-21 搜索):
  - 两层小楼: 一层大开口车库(可开车入) + 前后各一门 + 小隔间/小窗
  - 转角楼梯 (L 形) 上二楼, 楼梯下有木箱
  - 二楼: 主体 + 楼梯间后门 + 外部阳台(矮围墙)
  - 海岛2.0: 外墙攀爬小平台
  - 浅色墙面 + 深灰屋顶 + 卷帘门(山字楼风格细节, 整活)
尺寸: 主体 8(x) x 6.5(y), 一层高 3, 二层高 2.6, 屋顶+女儿墙。
运行: blender.exe --background --python _build_jiache.py
输出: Loom\assets\假车库.obj / 假车库.mtl + D:\my-project\_jiache_preview.png
"""
import bpy
import bmesh
import math
import os

OUT_DIR = r"D:\my-project\Loom(py源代码)\Loom\assets"
OBJ_PATH = os.path.join(OUT_DIR, "假车库.obj")
PREVIEW = r"D:\my-project\_jiache_preview.png"

# ---------------- 场景重置 ----------------
bpy.ops.wm.read_factory_settings(use_empty=True)   # 空场景

# ---------------- 材质 (obj 导出读 Principled Base Color -> Kd) ----------------
def make_mat(name, rgb):
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    # use_empty 场景下节点树可能无 Principled 节点: 按类型找, 找不到手动建
    bsdf = next((n for n in m.node_tree.nodes if n.type == 'BSDF_PRINCIPLED'), None)
    if bsdf is None:
        bsdf = m.node_tree.nodes.new('ShaderNodeBsdfPrincipled')
        out = next((n for n in m.node_tree.nodes if n.type == 'OUTPUT_MATERIAL'), None)
        if out is not None:
            m.node_tree.links.new(bsdf.outputs[0], out.inputs[0])
    bsdf.inputs["Base Color"].default_value = (rgb[0], rgb[1], rgb[2], 1.0)
    bsdf.inputs["Roughness"].default_value = 0.9
    m.diffuse_color = (rgb[0], rgb[1], rgb[2], 1.0)   # workbench 预览用
    return m

MAT = {
    'wall':  make_mat("Wall",  (0.86, 0.79, 0.62)),   # 米黄墙面
    'trim':  make_mat("Trim",  (0.72, 0.71, 0.68)),   # 檐口/墙基
    'roof':  make_mat("Roof",  (0.30, 0.29, 0.31)),   # 深灰屋顶
    'door':  make_mat("Door",  (0.42, 0.34, 0.26)),   # 棕灰卷帘门
    'metal': make_mat("Metal", (0.55, 0.56, 0.60)),   # 钢灰楼梯/扶手
    'frame': make_mat("Frame", (0.92, 0.92, 0.90)),   # 窗框白
    'glass': make_mat("Glass", (0.13, 0.22, 0.36)),   # 深蓝玻璃
    'wood':  make_mat("Wood",  (0.55, 0.37, 0.20)),   # 木箱
    'floor': make_mat("Floor", (0.76, 0.75, 0.72)),   # 阳台地
}

# ---------------- 几何工具: box / 圆柱 / 布尔差集 ----------------
parts = []          # (object, mat_name)

def add_box(name, cx, cy, cz, sx, sy, sz, mat):
    """中心定位盒 (bmesh 创建, 无 ops 依赖, headless 稳)."""
    mesh = bpy.data.meshes.new(name)
    bm = bmesh.new()
    bmesh.ops.create_cube(bm, size=1.0)
    for v in bm.verts:
        v.co.x = v.co.x * sx + cx
        v.co.y = v.co.y * sy + cy
        v.co.z = v.co.z * sz + cz
    bm.to_mesh(mesh)
    bm.free()
    obj = bpy.data.objects.new(name, mesh)
    bpy.context.collection.objects.link(obj)
    obj.data.materials.append(MAT[mat])
    parts.append((obj, mat))
    return obj

def add_cyl(name, cx, cy, cz, r, depth, axis, mat):
    """圆柱 (axis='x'|'y'|'z' 轴方向)."""
    bpy.ops.mesh.primitive_cylinder_add(vertices=24, radius=r, depth=depth,
                                        location=(cx, cy, cz))
    obj = bpy.context.active_object
    obj.name = name
    if axis == 'x':
        obj.rotation_euler = (0.0, math.pi / 2, 0.0)
    elif axis == 'y':
        obj.rotation_euler = (math.pi / 2, 0.0, 0.0)
    obj.data.materials.append(MAT[mat])
    parts.append((obj, mat))
    return obj

def cut_hole(target, cx, cy, cz, sx, sy, sz):
    """布尔差集: 从 target 挖掉一个盒 (cutter 不保留, 差集后删除)."""
    cutter = add_box("cutter", cx, cy, cz, sx, sy, sz, 'metal')   # 材质无关, 差集后删
    bpy.context.view_layer.objects.active = target
    mod = target.modifiers.new("cut", 'BOOLEAN')
    mod.object = cutter
    mod.operation = 'DIFFERENCE'
    mod.solver = 'EXACT'
    with bpy.context.temp_override(object=target, active_object=target,
                                   selected_objects=[target]):
        bpy.ops.object.modifier_apply(modifier=mod.name)
    parts.remove((cutter, 'metal'))
    mesh = cutter.data
    bpy.data.objects.remove(cutter)
    bpy.data.meshes.remove(mesh)

# ---------------- 建模 ----------------
# 1. 一层墙体 (含车库门/后门/小窗洞) —— 主体 8x6.5x3
w1 = add_box("wall1", 4.0, 3.25, 1.5, 8.0, 6.5, 3.0, 'wall')
cut_hole(w1, 8.3, 2.4, 1.35, 0.8, 3.4, 2.7)    # 车库门 (正面 x=8, 宽3.4 高2.7)
cut_hole(w1, -0.3, 3.2, 1.1, 0.8, 1.1, 2.2)    # 后门 (背面 x=0)
cut_hole(w1, 8.3, 5.6, 2.0, 0.8, 1.0, 1.2)     # 前小窗 (偏房侧)
cut_hole(w1, 5.5, -0.3, 2.0, 1.2, 0.8, 1.0)    # 侧小窗 (y=0 面)

# 2. 二层墙体 (z 3-5.6, 含前窗/侧窗/阳台门/后门)
w2 = add_box("wall2", 4.0, 3.25, 4.3, 8.0, 6.5, 2.6, 'wall')
cut_hole(w2, 8.3, 2.0, 4.6, 0.8, 1.5, 1.4)     # 二层前窗1 (正面)
cut_hole(w2, 8.3, 4.8, 4.6, 0.8, 1.5, 1.4)     # 二层前窗2
cut_hole(w2, 6.0, -0.3, 4.6, 1.4, 0.8, 1.2)    # 二层侧窗 (y=0 面)
cut_hole(w2, 5.8, 6.6, 4.35, 1.6, 0.8, 2.1)    # 阳台门洞 (y=6.5 面, 通阳台)
cut_hole(w2, -0.3, 3.2, 4.0, 0.8, 1.2, 2.1)    # 楼梯间后门 (背面)

# 3. 楼板 + 檐口 (一层顶, 二层底)
add_box("slab", 4.0, 3.25, 2.98, 8.0, 6.5, 0.16, 'floor')
add_box("eave", 4.0, 3.25, 3.02, 8.45, 6.95, 0.18, 'trim')   # 层间檐口环

# 4. 屋顶 + 女儿墙
add_box("roof", 4.0, 3.25, 5.72, 8.45, 6.95, 0.22, 'roof')
add_box("parapet_f", 4.0, 3.25, 6.05, 8.45, 0.14, 0.45, 'roof')   # 后沿
add_box("parapet_b", 4.0, 0.06, 6.05, 8.45, 0.14, 0.45, 'roof')   # 前沿
add_box("parapet_l", 0.14, 1.62, 6.05, 0.14, 3.2, 0.45, 'roof')   # 左半
add_box("parapet_r", 8.32, 1.62, 6.05, 0.14, 3.2, 0.45, 'roof')   # 右半

# 5. 外部阳台 (y 6.5 侧突出 1.6, 矮围墙) —— 阳台在一层顶右端
add_box("balcony_floor", 5.8, 7.3, 2.98, 3.4, 1.6, 0.14, 'floor')
add_box("balcony_wall_o", 5.8, 8.08, 3.5, 3.4, 0.12, 0.9, 'wall')   # 外沿矮墙
add_box("balcony_wall_l", 4.14, 7.3, 3.5, 0.12, 1.6, 0.9, 'wall')   # 左沿
add_box("balcony_wall_r", 7.46, 7.3, 3.5, 0.12, 1.6, 0.9, 'wall')   # 右沿

# 6. 转角楼梯 (背面 x≈0.5 侧: 段1 沿 y 升, 平台, 段2 沿 x 升) —— 每级 0.19 高
step = 0.0
for i in range(8):     # 段1: 从 (0.25, 3.4) 向 +y, 8 级
    add_box("stair_a%d" % i, 0.35, 3.45 + 0.36 * i, 0.1 + 0.19 * (i + 1),
            0.5, 0.34, 0.1 + 0.19 * (i + 1), 'metal')
add_box("landing", 1.05, 6.1, 1.55, 1.5, 1.3, 0.15, 'metal')   # 转角平台 z≈1.5
for i in range(8):     # 段2: 从平台向 +x 升到 z≈2.9
    add_box("stair_b%d" % i, 1.85 + 0.36 * i, 6.1, 1.7 + 0.19 * (i + 1),
            0.34, 1.2, 0.1 + 0.19 * (i + 1), 'metal')
# 扶手 (段1 外侧斜梁 + 2 根柱, 简化)
add_box("rail_p1", 0.06, 5.1, 1.1, 0.06, 3.4, 0.06, 'metal')
add_box("rail_p2", 0.06, 6.1, 1.9, 0.06, 0.06, 1.6, 'metal')
add_box("rail_p3", 3.0, 6.72, 2.5, 2.6, 0.06, 0.06, 'metal')

# 7. 卷帘门 (车库门洞 y 0.7-4.1, z 0-2.7): 8 条横板 + 顶部卷轴
for i in range(8):
    add_box("roller%d" % i, 8.08, 2.4, 0.16 + 0.3 * i, 0.26, 3.3, 0.26, 'door')
add_cyl("roller_drum", 8.08, 2.4, 2.62, 0.3, 3.3, 'y', 'door')   # 卷轴 (沿 y)

# 8. 窗框 + 玻璃 (窗洞位置: 一层小窗2 + 二层窗3 + 阳台门)
def add_window(cx, cy, cz, wx, wy, wz):
    """在墙洞中心放 4 条白框 + 1 块玻璃 (厚 0.04)."""
    t = 0.07
    if wx > wy:   # 洞在 x=const 面 (法线 x): 框沿 y/z
        add_box("wf_t", cx, cy, cz + wz / 2 - t / 2, 0.05, wx, t, 'frame')
        add_box("wf_b", cx, cy, cz - wz / 2 + t / 2, 0.05, wx, t, 'frame')
        add_box("wf_l", cx, cy - wx / 2 + t / 2, cz, 0.05, t, wz, 'frame')
        add_box("wf_r", cx, cy + wx / 2 - t / 2, cz, 0.05, t, wz, 'frame')
        add_box("glass", cx, cy, cz, 0.04, wx - 0.1, wz - 0.1, 'glass')
    else:         # 洞在 y=const 面 (法线 y): 框沿 x/z
        add_box("wf_t", cx, cy, cz + wz / 2 - t / 2, wx, 0.05, t, 'frame')
        add_box("wf_b", cx, cy, cz - wz / 2 + t / 2, wx, 0.05, t, 'frame')
        add_box("wf_l", cx - wx / 2 + t / 2, cy, cz, t, 0.05, wz, 'frame')
        add_box("wf_r", cx + wx / 2 - t / 2, cy, cz, t, 0.05, wz, 'frame')
        add_box("glass", cx, cy, cz, wx - 0.1, 0.04, wz - 0.1, 'glass')

add_window(8.0, 5.6, 2.0, 1.0, 1.0, 1.2)     # 一层前小窗
add_window(5.5, 0.0, 2.0, 1.2, 1.0, 1.0)     # 一层侧小窗
add_window(8.0, 2.0, 4.6, 1.5, 1.5, 1.4)     # 二层前窗1
add_window(8.0, 4.8, 4.6, 1.5, 1.5, 1.4)     # 二层前窗2
add_window(6.0, 0.0, 4.6, 1.4, 1.2, 1.2)     # 二层侧窗
add_window(5.8, 6.5, 4.35, 1.6, 2.1, 2.1)    # 阳台门框 (洞穿 y 面, wx=x 宽, wy=y 深, wz=z 高)
# 门框 (后门/楼梯间门): 只加门框不加玻璃
add_box("df_t", -0.05, 3.2, 4.05, 0.06, 1.3, 0.07, 'frame')
add_box("df_l", -0.05, 2.62, 4.0, 0.06, 0.07, 2.1, 'frame')
add_box("df_r", -0.05, 3.78, 4.0, 0.06, 0.07, 2.1, 'frame')

# 9. 楼梯下木箱 (攻略细节)
add_box("crate1", 0.7, 4.3, 0.32, 0.64, 0.64, 0.64, 'wood')
add_box("crate2", 1.25, 4.9, 0.25, 0.5, 0.5, 0.5, 'wood')
add_box("crate3", 0.75, 5.45, 0.2, 0.4, 0.4, 0.4, 'wood')

# 10. 外墙攀爬小平台 (海岛2.0, 阳台外侧)
add_box("climb_plat", 5.8, 8.42, 2.86, 1.0, 0.5, 0.1, 'trim')

# ---------------- 合并单对象 + UV ----------------
for obj, _ in parts:
    obj.select_set(True)
bpy.context.view_layer.objects.active = parts[0][0]
with bpy.context.temp_override(object=parts[0][0], active_object=parts[0][0],
                               selected_objects=[o for o, _ in parts],
                               selected_editable_objects=[o for o, _ in parts]):
    bpy.ops.object.join()
house = parts[0][0]
house.name = "FakeGarage"

bpy.ops.object.select_all(action='DESELECT')
house.select_set(True)
bpy.context.view_layer.objects.active = house
bpy.ops.object.mode_set(mode='EDIT')
bpy.ops.mesh.select_all(action='SELECT')
bpy.ops.uv.smart_project(angle_limit=math.radians(66.0), island_margin=0.02)
bpy.ops.object.mode_set(mode='OBJECT')

print("[build] joined verts=%d faces=%d mats=%d"
      % (len(house.data.vertices), len(house.data.polygons), len(house.data.materials)))

# ---------------- 渲染预览 (workbench, 材质色) ----------------
scene = bpy.context.scene
cam_data = bpy.data.cameras.new("cam")
cam = bpy.data.objects.new("cam", cam_data)
bpy.context.collection.objects.link(cam)
cam.location = (16.0, 12.0, 9.0)
cam_data.lens = 40
# TRACK_TO 约束对准建筑中心 (headless 下避免手算欧拉角)
target = bpy.data.objects.new("cam_target", None)
bpy.context.collection.objects.link(target)
target.location = (4.5, 3.5, 3.2)
con = cam.constraints.new('TRACK_TO')
con.target = target
con.track_axis = 'TRACK_NEGATIVE_Z'
con.up_axis = 'UP_Y'
scene.camera = cam
scene.render.engine = 'BLENDER_WORKBENCH'
scene.display.shading.color_type = 'MATERIAL'
scene.display.shading.light = 'STUDIO'
scene.render.resolution_x = 1280
scene.render.resolution_y = 960
scene.render.filepath = PREVIEW
bpy.ops.render.render(write_still=True)
print("[build] preview ->", PREVIEW)

# ---------------- 导出 obj (quad/ngon 保留, Loom 扇形三角化; y-up) ----------------
bpy.ops.wm.obj_export(
    filepath=OBJ_PATH,
    export_materials=True,
    export_normals=True,
    export_uv=True,
    apply_modifiers=True,
    up_axis='Y',           # obj 标准 +Y up, Loom 导入约定 Y-up 不转轴
)
print("[build] obj ->", OBJ_PATH)
print("BUILD DONE")
