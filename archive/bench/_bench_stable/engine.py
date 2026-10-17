# -*- coding: utf-8 -*-
"""
engine.py — GLEngine: moderngl (OpenGL) 真 GPU 渲染 + pygame 窗口/输入/HUD

渲染管线:
  顶点数据一次性上传为 VBO (展平: 每三角形 3 个独立顶点, 带位置/法线/颜色)
  MVP 每帧 CPU(numpy) 计算, 以 uniform 传给 GPU
  GPU 顶点着色器变换 + 光栅化 + 硬件深度测试 (Z-buffer) + 背面剔除
  pygame 管窗口/事件/字体 HUD (文字纹理 quad)

矩阵约定 (与 CPU 路径一致, 无镜像):
  - view: mat4_view_yaw_pitch (前方 z_view>0, det=+1)
  - proj: mat4_perspective (clip.w=z_view, clip.z 单调映射 [0,1], 供硬件深度测试)
  - uniform 上传: matlib 行主序 M 直接 tobytes (不转置) = GPU 的 M^T, 使 GLSL u*v 等价 numpy v@M
"""
import json
import math
import os
import threading
import time
import uuid
from collections import namedtuple

import numpy as np
import pygame
import moderngl

from matlib import (mat4_translation, mat4_rotation, mat4_scale,
                    mat4_perspective, mat4_view_yaw_pitch,
                    mat4_ortho, mat4_view_forward, decompose_euler,
                    view_basis_to_angles)   # M29: 光源正交投影/任意朝向视图; M41: set_parent 保世界旋转; 2026-08-16: 相机物体化挂父合成反解
from fastpath import depths as _fp_depths   # 组3: 深度DP Numba可选加速 (未装numba自动降级纯Python, 数值同源, 见fastpath.py)
from fastpath import ancestry_dfs as _fp_ancestry   # 组3层2: ancestry DFS Numba可选加速 (未装numba自动降级纯Python, 语义逐位同源, 见fastpath.py)
import fastpath   # 组3层3: AABB 批量归约 (aabbs_minmax 串行 njit 默认 / _par 逃生门)

Point3D = namedtuple('Point3D', ['x', 'y', 'z'])

# ================ 主渲染着色器 (顶点 + 片元) ================
# 光照模型 (M20): Blinn-Phong 漫反射+镜面高光 + 半球环境光 + 边缘光(菲涅尔) + gamma 校正.
# 之前的纯兰伯特(0.2+0.8*diff)无观察方向项, 立方体相邻面亮度可能完全相等(如 -Y/+Z 都停在环境光),
# 导致分不出边缘. 现在: 高光/边缘光看观察角度, 半球环境光按法线朝向分离相邻面.
_VERT_SRC = """#version 330
in vec3 in_pos;
in vec3 in_normal;
in vec4 in_color;
// A2 (2026-08-29) GL 实例化批绘制: 世界矩阵/饱和度/颜色走 per-instance 属性
// (/i divisor), 桶内全部实例一次 draw —— 逐物体 u_model/uniform 上传循环取消.
// ★构造约定: a_w# = 引擎 numpy M 的行 (行主序), GLSL mat4(a_w0..a_w3) 以"列"收
// 参, 故 mat4 值 = M^T —— 与旧 u_model (M.tobytes() 直传) 数学逐位一致.
in vec4 a_w0; in vec4 a_w1; in vec4 a_w2; in vec4 a_w3;
in vec4 a_sat;   // x = 物体饱和度 (0=灰阶, 1=原始, >1=增艳)
in vec4 a_col;   // rgb + w>0.5 = 材质单色覆盖网格面色 (同组件 color 语义)
uniform mat4 u_view_proj;
out vec4 v_color;
out vec3 v_normal;
out vec3 v_world_pos;
out float v_sat;
void main() {
    mat4 u_model = mat4(a_w0, a_w1, a_w2, a_w3);
    vec4 world = u_model * vec4(in_pos, 1.0);
    gl_Position = u_view_proj * world;
    // 法线变换: 逆转置 (正确处理非等比缩放; 等比缩放时等价 R*n)
    v_normal = transpose(inverse(mat3(u_model))) * in_normal;
    v_world_pos = world.xyz;
    v_color = (a_col.w > 0.5) ? vec4(a_col.rgb, 1.0) : in_color;
    v_sat = a_sat.x;
}"""

_FRAG_SRC = """#version 330
in vec4 v_color;
in vec3 v_normal;
in vec3 v_world_pos;
// 多光源 (最多 8 个): 平行光 / 点光源, 场景光源由用户手动添加 (无默认光源)
const int MAX_LIGHTS = 8;
uniform int u_light_count;
uniform vec3 u_light_dir[MAX_LIGHTS];    // 平行光行进方向 (点光源置 0)
uniform vec3 u_light_pos[MAX_LIGHTS];    // 点光源位置 (平行光置 0)
uniform vec3 u_light_color[MAX_LIGHTS];
uniform float u_light_intensity[MAX_LIGHTS];
uniform float u_light_kind[MAX_LIGHTS];  // 0=平行光, 1=点光源
uniform float u_ambient_scale;           // 有光源=1.0, 无光源=0.2 (压暗提示手动加光)
in float v_sat;                          // A2: 物体饱和度改 per-instance (0=灰阶, 1=原始, >1=增艳)
uniform vec3 u_view_pos;
// M29 阴影 (shadow mapping, 物体遮挡光线, 物理正确):
// 全部阴影贴图平铺进 sampler 数组 (平行光 1 张 2D / 点光 6 面 2D),
// 每光源记录起始槽位 u_shadow_slot; 平行光额外带 view-proj 与 beam 截面参数.
const int MAX_SHADOW_SLOTS = 16;
uniform sampler2DShadow u_shadow_maps[MAX_SHADOW_SLOTS];  // 阴影采样器: GPU 深度比较
uniform int u_shadow_slot[MAX_LIGHTS];              // 每光源阴影贴图起始槽位 (-1=无阴影)
uniform mat4 u_light_ortho[MAX_LIGHTS];             // 平行光 view-proj (正交)
uniform float u_light_mode[MAX_LIGHTS];             // 平行光: 0=full 全场景, 1=beam 光束
uniform float u_light_shape[MAX_LIGHTS];            // beam 截面: 0=circle, 1=rect
uniform float u_shadow_res;                         // 平行光阴影分辨率 (PCF 纹素步长)
uniform float u_shadow_point_res;                   // 点光阴影分辨率
uniform float u_shadow_bias;                        // 平行光深度偏差 (防 acne)
uniform float u_shadow_point_bias;                  // 点光深度偏差
uniform float u_light_far;                          // 点光阴影远平面 (深度归一 [0,1])
out vec4 frag_color;

// 3x3 PCF 软阴影. 本驱动(GTX 1050 Ti)深度纹理采样实测做 stored>=ref 比较
// (忽略 compare_func, 实测 ref<=存值=照亮; 与 moderngl 上报的 '<=' 相反).
// 阴影贴图存真实深度(近=小), 故传 ref = depth-bias (负 bias 把判定阈值推向光源,
// 防自阴影 acne): stored>=depth-bias <=> 遮挡面在片元之后 -> 片元不被挡=照亮.
float pcf_shadow(sampler2DShadow sm, vec2 uv, float depth, float bias, float res) {
    float ts = 1.0 / res;
    float sh = 0.0;
    for (int y = -1; y <= 1; y++) {
        for (int x = -1; x <= 1; x++) {
            sh += texture(sm, vec3(uv + vec2(float(x), float(y)) * ts, depth - bias));
        }
    }
    return sh / 9.0;
}

// 点光源立方体阴影: 手动选面 (匹配引擎 _point_light_vp 的面朝向) + PCF.
// 面索引是片元级变量, sampler 数组用常量偏移 + uniform 槽位 (避免动态 sampler 索引).
// 坑: 负向面(-X/-Y/-Z)的 fc 公式须与 mat4_view_forward 视图 NDC 同号 (已核对, 勿改符号).
float point_shadow(int slot, vec3 rd) {
    float adx = abs(rd.x), ady = abs(rd.y), adz = abs(rd.z);
    int face;
    vec2 fc;
    if (adx >= ady && adx >= adz) {
        if (rd.x > 0.0) { face = 0; fc = vec2( rd.z, -rd.y) / rd.x; }
        else            { face = 1; fc = vec2( rd.z,  rd.y) / rd.x; }
    } else if (ady >= adz) {
        if (rd.y > 0.0) { face = 2; fc = vec2( rd.x, -rd.z) / rd.y; }
        else            { face = 3; fc = vec2( rd.x,  rd.z) / rd.y; }
    } else {
        if (rd.z > 0.0) { face = 4; fc = vec2(-rd.x, -rd.y) / rd.z; }
        else            { face = 5; fc = vec2(-rd.x,  rd.y) / rd.z; }
    }
    vec2 uv = fc * 0.5 + 0.5;
    float depth = length(rd) / u_light_far;     // 与点光深度贴图一致 (距离/far 归一)
    if (depth > 1.0) return 1.0;                // 超出阴影覆盖范围不算遮
    if (face == 0) return pcf_shadow(u_shadow_maps[slot],     uv, depth, u_shadow_point_bias, u_shadow_point_res);
    if (face == 1) return pcf_shadow(u_shadow_maps[slot + 1], uv, depth, u_shadow_point_bias, u_shadow_point_res);
    if (face == 2) return pcf_shadow(u_shadow_maps[slot + 2], uv, depth, u_shadow_point_bias, u_shadow_point_res);
    if (face == 3) return pcf_shadow(u_shadow_maps[slot + 3], uv, depth, u_shadow_point_bias, u_shadow_point_res);
    if (face == 4) return pcf_shadow(u_shadow_maps[slot + 4], uv, depth, u_shadow_point_bias, u_shadow_point_res);
    return              pcf_shadow(u_shadow_maps[slot + 5], uv, depth, u_shadow_point_bias, u_shadow_point_res);
}

void main() {
    vec3 n = normalize(v_normal);
    vec3 v = normalize(u_view_pos - v_world_pos);
    // 半球环境光: 朝上面更亮/朝下面更暗 (按法线朝向分离相邻面)
    // 系数已压低: 顶面 0.30 / 侧面 0.16 / 底面 0.02 —— 避免旧版(顶面 0.50)把纯色面洗白
    float hemi = clamp(0.5 + 0.5 * n.y, 0.0, 1.0);
    float ambient = (0.02 + 0.28 * hemi) * u_ambient_scale;
    vec3 acc = vec3(0.0);
    for (int i = 0; i < MAX_LIGHTS; i++) {
        if (i >= u_light_count) break;
        vec3 l;
        float diff;
        float atten = 1.0;
        if (u_light_kind[i] > 0.5) {
            // 点光源: 位置 + 距离衰减
            vec3 to_l = u_light_pos[i] - v_world_pos;
            float dist = length(to_l);
            l = to_l / max(dist, 1e-4);
            diff = max(dot(n, l), 0.0);
            atten = 1.0 / (1.0 + 0.09 * dist + 0.045 * dist * dist);
        } else {
            // 平行光: 行进方向取反即为光照方向
            l = normalize(-u_light_dir[i]);
            diff = max(dot(n, l), 0.0);
        }
        // 镜面高光: Blinn-Phong 半程向量, 与观察角度相关
        vec3 h = normalize(l + v);
        float spec = pow(max(dot(n, h), 0.0), 24.0);
        // M29 光束截面 (2026-08-22 解耦阴影, v3 最终版): 遮罩独立于 shadow 开关。
        // 用经 M29 验证的 uv/正交路径 (u_light_ortho 每个平行光都有兜底计算)。
        // v3 关键: in_shape 取出循环外存 g_in_shape, 阴影采样结果相乘 ——
        // 阴影块的 pcf 曾直接覆盖独立块结果 (pv 对圆外返回 0 → 形状被"锁圆",
        // 用户实测: 阴影开时矩形永不变), 现在形状判定有最终决定权.
        float sh = 1.0;
        float g_in_shape = 1.0;
        if (u_light_kind[i] < 0.5 && u_light_mode[i] > 0.5) {
            vec4 lp = u_light_ortho[i] * vec4(v_world_pos, 1.0);
            vec2 uv = lp.xy * 0.5 + 0.5;
            float in_shape = 0.0;
            if (uv.x >= 0.0 && uv.x <= 1.0 && uv.y >= 0.0 && uv.y <= 1.0) {
                vec2 xy = uv * 2.0 - 1.0;
                in_shape = (u_light_shape[i] > 0.5)
                    ? (max(abs(xy.x), abs(xy.y)) <= 1.0 ? 1.0 : 0.0)
                    : (length(xy) <= 1.0 ? 1.0 : 0.0);
            }
            g_in_shape = in_shape;
            if (in_shape < 0.5) sh = 0.0;
        }
        // M29 阴影: 被物体遮挡的光线不照亮 (物理遮挡)
        if (u_shadow_slot[i] >= 0) {
            if (u_light_kind[i] > 0.5) {
                sh = point_shadow(u_shadow_slot[i], v_world_pos - u_light_pos[i]);
            } else {
                vec4 lp = u_light_ortho[i] * vec4(v_world_pos, 1.0);
                float depth = (lp.z / lp.w) * 0.5 + 0.5;   // 引擎深度约定 (near->0.5, far->1)
                vec2 uv = lp.xy * 0.5 + 0.5;
                if (uv.x < 0.0 || uv.x > 1.0 || uv.y < 0.0 || uv.y > 1.0) {
                    // beam: 出覆盖保留独立遮罩结果; full: 出范围不遮
                    sh = (u_light_mode[i] > 0.5) ? sh : 1.0;
                } else {
                    // 2026-08-22: pcf × 形状遮罩 —— 阴影采样只决定"遮挡",
                    // 截面形状由 g_in_shape 决定 (修复"阴影开时锁圆")
                    sh = pcf_shadow(u_shadow_maps[u_shadow_slot[i]], uv, depth,
                                    u_shadow_bias, u_shadow_res) * g_in_shape;
                }
            }
        }
        acc += u_light_color[i] * u_light_intensity[i] * (0.60 * diff + 0.25 * spec) * atten * sh;
    }
    // 边缘光 (菲涅尔近似): 法线越偏离视线越亮, 强化轮廓边缘
    float rim = 0.12 * pow(1.0 - max(dot(n, v), 0.0), 3.0);
    // 光照系数压到 max≈0.9 预 gamma: 避免纯色(如 #FF5555 的 R=1.0)直接爆白,
    // 顶面/侧面在亮度上拉开可辨差距 (否则相邻面又分不出边缘)
    vec3 col = v_color.rgb * (ambient + acc) + vec3(rim);
    // gamma 校正 (线性 -> sRGB 显示)
    col = pow(clamp(col, 0.0, 1.0), vec3(1.0 / 2.2));
    // 饱和度 (终色调节): 0=灰阶, 1=原始, >1=增艳 (补偿光照压低后画面偏灰)
    float lum = dot(col, vec3(0.299, 0.587, 0.114));
    col = mix(vec3(lum), col, v_sat);
    frag_color = vec4(col, 1.0);
}"""

# ================ HUD 正交着色器 (文字纹理 quad) ================
_HUD_VERT = """#version 330
in vec2 in_pos;
in vec2 in_uv;
out vec2 v_uv;
uniform vec2 u_origin;
uniform vec2 u_size;
void main() {
    gl_Position = vec4(in_pos * u_size + u_origin, 0.0, 1.0);
    v_uv = in_uv;
}"""

_HUD_FRAG = """#version 330
in vec2 v_uv;
uniform sampler2D u_tex;
uniform vec4 u_color;            // M33: 运行时 UI 纯色矩形用 (文字传白=不变)
out vec4 frag_color;
void main() {
    frag_color = texture(u_tex, v_uv) * u_color;
}"""

# ================ 线条着色器 (逐顶点颜色, gizmo/网格/选中框用) ================
# core profile 线宽仅保证 1px; gizmo 端点用投影小方块 (三角形) 增强可点性
_LINE_VERT = """#version 330
in vec3 in_pos;
in vec4 in_color;
uniform mat4 u_view_proj;
out vec4 v_color;
void main() {
    gl_Position = u_view_proj * vec4(in_pos, 1.0);
    v_color = in_color;
}"""

_LINE_FRAG = """#version 330
in vec4 v_color;
out vec4 frag_color;
void main() {
    frag_color = v_color;
}"""

# ================ 阴影深度 pass 着色器 (M29) ================
# 只输出深度. 顶点着色器声明与主 VAO 相同的三个输入 (交错 '3f 3f 4f'),
# 阴影 VAO 才能用与主 VAO 相同的 VBO/布局 (moderngl VAO 与创建它的程序绑定,
# 不能拿主 prog 的 VAO 去渲染阴影 prog —— 会什么都不画).
# 深度贴图存真实深度 (近=小, 默认 gl_FragCoord.z / 点光=距离/far):
# 本驱动阴影采样实测 stored>=ref 为照亮, 主 pass 传 ref = depth-bias,
# 故遮挡面(stored)在片元之后(stored>=depth-bias)=照亮. 反转深度方案已废弃.
_SHADOW_VERT = """#version 330
in vec3 in_pos;
// A2 (2026-08-29): 阴影 pass 同样走实例化 (world 矩阵 per-instance, 光 VP 仍 uniform)
in vec4 a_w0; in vec4 a_w1; in vec4 a_w2; in vec4 a_w3;
uniform mat4 u_light_vp;
out vec3 v_world_pos;
void main() {
    mat4 u_model = mat4(a_w0, a_w1, a_w2, a_w3);
    vec4 world = u_model * vec4(in_pos, 1.0);
    v_world_pos = world.xyz;
    gl_Position = u_light_vp * world;
}"""

_SHADOW_FRAG = """#version 330
uniform int u_depth_kind;      // 0= 默认深度(z), 1= 到光源距离 (点光)
uniform vec3 u_light_pos;
uniform float u_light_far;
in vec3 v_world_pos;
void main() {
    // 存真实深度 (近=小): 本驱动阴影采样器实测固定比较 stored >= ref (忽略 compare_func),
    // 主 pass 传 ref = depth - bias, 遮挡面在片元之后 => stored >= depth-bias => 照亮.
    // 深度测试用默认 GL_LESS (近小大远), 近的遮挡面正确覆盖远的.
    // 必须无条件写 gl_FragDepth (分支不取时值未定义, 某些驱动写 0.0).
    if (u_depth_kind > 0) {
        gl_FragDepth = clamp(length(v_world_pos - u_light_pos) / u_light_far, 0.0, 1.0);
    } else {
        gl_FragDepth = gl_FragCoord.z;
    }
}"""

# ================ 按键字符 -> pygame 键码 ================
_KEYMAP = {
    'w': pygame.K_w, 's': pygame.K_s, 'a': pygame.K_a, 'd': pygame.K_d,
    'q': pygame.K_q, 'e': pygame.K_e,
    'Left': pygame.K_LEFT, 'Right': pygame.K_RIGHT, 'Up': pygame.K_UP, 'Down': pygame.K_DOWN,
    'i': pygame.K_i, 'k': pygame.K_k, 'j': pygame.K_j, 'l': pygame.K_l,
    'u': pygame.K_u, 'o': pygame.K_o,
    'space': pygame.K_SPACE, 'Tab': pygame.K_TAB,
    'Shift': pygame.K_LSHIFT, 'Ctrl': pygame.K_LCTRL,
    '1': pygame.K_1, '2': pygame.K_2, '3': pygame.K_3,
    '4': pygame.K_4, '5': pygame.K_5, '6': pygame.K_6,
}

# ================ 输入动作层 (M30b, Unity 输入系统理念) ================
# 动作 = "玩家想做什么" ('向前'/'跳跃'), 绑定到一组键名 (_KEYMAP 字符键).
# 脚本/游戏逻辑用 engine.get_action('动作') 而非 is_key('键') —— 改键不动脚本,
# 像 Unity Input System 的动作层 (Action -> Binding). 键位可在 输入配置.json 重映射.
DEFAULT_ACTIONS = {
    '向前': ['w', 'Up'],
    '向后': ['s', 'Down'],
    '向左': ['a', 'Left'],
    '向右': ['d', 'Right'],
    '跳跃': ['space'],
    '交互': ['e'],
    '加速': ['Shift'],
}
_ACTION_FILE = "输入配置.json"   # 键位重映射配置文件 (放引擎目录, 缺失用默认)

# ================ 组件化 (M25): 组合优于继承 ================
# Unity 哲学: GameObject 是最空的容器, 行为全来自挂上去的组件.
# 这里 GameObject = 容器, 组件列表决定它"能干嘛". 一个物体可挂多个脚本.
class Component:
    """组件基类: 挂在 GameObject 上的数据/行为块 (M25).
    owner 反查宿主物体. 子类各自持有自己的数据, 互不干扰."""

    ctype = 'component'

    def __init__(self):
        self.owner = None      # 宿主 GameObject


class TransformComponent(Component):
    """变换组件: 位置/旋转/缩放 + 父子层次 (对应 Unity 的 Transform 组件)."""
    ctype = 'transform'

    def __init__(self, position, rotation, scale=(1.0, 1.0, 1.0)):
        super().__init__()
        self.position = Point3D(*position)
        self.rotation = Point3D(*rotation)
        self.scale = tuple(scale if scale is not None else (1.0, 1.0, 1.0))
        self.parent = None
        self.children = []


class MeshRendererComponent(Component):
    """网格渲染组件: 网格 + 材质引用 + 法线模式 + 可见性 (M23 材质资产化).
    颜色/饱和度移到共享 Material 上 —— 多个物体引用同一材质, 改一处全变."""
    ctype = 'mesh_renderer'

    def __init__(self, mesh, color=None, normal_mode='flat', primitive=None,
                 params=None, saturation=1.0, visible=True, material=None):
        super().__init__()
        self.mesh = mesh
        # 材质 (M23): 默认自建一个 (color/saturation 为该材质初值);
        # 传入 material 则共享引用 (多个物体指向同一材质).
        self.material = material if material is not None else Material(color=color,
                                                                      saturation=saturation)
        self.normal_mode = normal_mode           # 'flat' 面法线 | 'vertex' 顶点径向
        self.primitive = primitive               # 基元类型 'cube'/'sphere'/'plane'/None
        self.params = params                     # 基元参数 (尺寸等, 序列化用)
        self.visible = visible


class ScriptComponent(Component):
    """脚本组件 (M27 -> M25): 一个脚本挂载, 物体可有多个.
    script_id = scripts.SCRIPTS 的键; script_vars = 参数覆盖;
    _script/_script_broken 是播放期运行态 (编辑/非播放期不实例化)."""
    ctype = 'script'

    def __init__(self, script_id=None, script_vars=None):
        super().__init__()
        self.script_id = script_id
        self.script_vars = dict(script_vars or {})
        self._script = None
        self._script_broken = False


class ColliderComponent(Component):
    """碰撞体组件 (M28): 给物体一个"物理碰撞体积", 决定它挡不挡别人/被不被挡.
    shape: 'box'   AABB 盒 (立方体/平面等, 取世界包围盒)
           'sphere' 球体 (球体网格自动用这个, 比 AABB 更贴合)
           'none'   无碰撞 (纯装饰, 谁都不挡)
    enabled: False = 暂时关闭 (不参与碰撞检测).
    碰撞是"世界空间"概念: 组件只存形状开关, 每帧按当前变换实时算世界体积,
    父链移动子物体也会正确挡住别人 (get_bounding_box 已沿父链合成)."""
    ctype = 'collider'

    def __init__(self, shape='box', enabled=True, friction=0.5, restitution=0.0,
                 rolling_friction=0.1):
        super().__init__()
        self.shape = shape
        self.enabled = bool(enabled)
        # B1 (2026-08-30): 接触材质参数 (阿蒙东-库仑 f=μN, 接触面积无关):
        # 摩擦系数 friction (0=冰面, 越大越涩) / 弹性 restitution (0=不回弹)。
        # 静态/运动学体 (无刚体) 的碰撞面材质走这里; 动态体走 RigidbodyComponent.
        # pair 有效值 = Jolt 几何平均 sqrt(μ1*μ2) (默认组合模式).
        self.friction = float(friction)
        self.restitution = float(restitution)
        # B1-P1 (2026-08-30): 滚动摩擦系数 (0=关闭, 默认 0.1, 范围 0-3);
        # culverin 0.14.0 无原生滚动阻尼 -> 桥内按 f = max(0, 1 - μ·rolling·K·dt)
        # 指数衰减 ω/水平线速度 (仅动态体清醒时)。与摩擦/弹性同控制组。
        self.rolling_friction = float(rolling_friction)


class RigidbodyComponent(Component):
    """刚体组件 (M31, Unity Rigidbody 理念): 给物体速度/重力, 引擎每帧按速度带碰撞移动.
    mass          质量 (暂用于未来冲量, 目前不参与响应)
    use_gravity   是否受重力 (默认 true, 沿 -Y)
    is_kinematic  运动学: true = 由脚本/动画控制 (不被重力/碰撞响应推), false = 动态
    velocity      世界速度 (m/s), 每帧 position += velocity*dt (带碰撞, 被挡停)
    注意: 刚体需配合 ColliderComponent 才有碰撞体积; 同树物体仍不互撞.
    运行时状态 (velocity/_colliding) 不序列化, 播放快照自动覆盖."""
    ctype = 'rigidbody'

    def __init__(self, mass=1.0, use_gravity=True, is_kinematic=False,
                 friction=0.5, restitution=0.0, rolling_friction=0.1):
        super().__init__()
        self.mass = float(mass)
        self.use_gravity = bool(use_gravity)
        self.is_kinematic = bool(is_kinematic)
        # B1 (2026-08-30): 动态体接触材质 (阿蒙东-库仑): 摩擦系数/弹性
        # (桥 create_body 透传; pair 有效值 = Jolt 几何平均)。序列化/快照/检查器跟随.
        self.friction = float(friction)
        self.restitution = float(restitution)
        # B1-P1 (2026-08-30): 滚动摩擦系数 (0=关闭, 默认 0.1, 范围 0-3);
        # 桥内衰减 (见 ColliderComponent.rolling_friction 注释)。动态体用本值。
        self.rolling_friction = float(rolling_friction)
        self.velocity = Point3D(0.0, 0.0, 0.0)   # 世界速度 (m/s)
        self._colliding = set()                  # 当前碰撞对 (物体 id), 事件检测用


class AudioSourceComponent(Component):
    """音频源组件 (M34, Unity AudioSource 理念): 挂物体上播放音频文件.
    clip     音频文件路径 (wav/ogg 等 pygame.mixer 支持的格式)
    loop     是否循环播放 (音乐用 true, 音效用 false)
    volume   音量 0..1
    playing  是否播放 (脚本/检查器设, 引擎每帧按状态 play/stop)
    _key     运行时: 已播放的 (clip, playing) 标志 (不序列化, 播放状态变化才重播)"""
    ctype = 'audio'

    def __init__(self, clip=None, loop=False, volume=1.0):
        super().__init__()
        self.clip = clip
        self.loop = bool(loop)
        self.volume = float(volume)
        self.playing = False
        self._key = None


class AnimationClip:
    """动画剪辑 (M35, Unity AnimationClip 简化): 关键帧序列, 随时间插值变换.
    frames: [{ 'time': 秒, 'position': (x,y,z)|None, 'rotation': (rx,ry,rz)|None,
               'scale': (sx,sy,sz)|None }]  —— 缺省字段保持上一帧值.
    旋转为欧拉角弧度 (与 transform 一致). duration = 末帧 time.

    A6 numpy 化: frames 仍是原 dict 列表 (外部可读/可改/可序列化); 内部另建
    numpy 缓存 (_np_times (F,) f64 + 三通道 (F,3) f64), sample() 两条路径并存:
    快路径 = searchsorted 定段 + 向量化插值 + 转 Python float tuple, 仅当
    "F>=2 且时间非降序且 position/rotation/scale 全帧齐备且值可转 (F,3)" 才启用
    (缺任一前提整体走旧循环慢路径, 语义以旧实现为准, 逐位一致——含首段 t 早于
    首帧时间的负 f 外推、span<=0 时 f=0.0、末帧保持原对象). 缓存失效 (红线3):
    sample 入口 id(frames)+len 校验, 列表对象身份或长度变化即重建; 同长度原地
    改帧不在校验范围, 需调 _np_rebuild() 显式重建 (全工程现状无此用法)."""

    _CHANNELS = ('position', 'rotation', 'scale')

    def __init__(self, frames=None):
        self.frames = frames or []
        self._np_key = None      # (id(frames), len(frames)) 缓存失效校验
        self._np_fast = False    # True = sample 可走 numpy 快路径
        self._np_times = None    # (F,) f64 关键帧时间 (frames 列表序, 不重排)
        self._np_vals = None     # {'position'/'rotation'/'scale': (F,3) f64}
        self._np_rebuild()

    @property
    def duration(self):
        return self.frames[-1]['time'] if self.frames else 0.0

    def _np_rebuild(self):
        """A6: 重建 numpy 缓存 (创建时/frames 换列表后调). 任一快路径前提
        不满足 → _np_fast=False 整体留慢路径, 采样语义与旧实现逐位一致.
        (D2 收紧) time/分量只认纯 Python int/float: np.array 会把 None 静默
        转 nan、数字字符串静默转数值, 而旧实现对它们是报错/原样语义, 故
        None/bool/np 数/str 等一律慢路径, 杜绝 nan 静默扩散."""
        frames = self.frames
        self._np_key = (id(frames), len(frames))
        self._np_fast = False
        self._np_times = None
        self._np_vals = None
        if len(frames) < 2:
            return
        try:
            for fr in frames:
                tv = fr['time']
                if type(tv) is not float and type(tv) is not int:
                    return      # None/bool/np 数/str: 旧实现比较/报错语义特殊 → 慢路径
                if type(tv) is int and float(tv) != tv:
                    return      # int 超 f64 精度: 定段可能偏移 → 慢路径
                for k in self._CHANNELS:
                    v = fr[k]   # 缺 k → KeyError → 慢路径 (采样时同旧代码报错)
                    if type(v) is not list and type(v) is not tuple:
                        return  # None/np 数组等: np.array 会静默转 nan/数值 → 慢路径
                    if len(v) < 3:
                        return  # 旧代码 a[j] 会 IndexError → 慢路径保持该语义
                    for j in range(3):
                        x = v[j]
                        if x != x:          # nan 分量 → 慢路径 (旧实现原样算出 nan)
                            return
                        if type(x) is not int and type(x) is not float:
                            return  # 分量含 None/bool/np 数/str → 慢路径
            times = np.array([fr['time'] for fr in frames], dtype=np.float64)
            if times.shape != (len(frames),) or not np.all(times[1:] >= times[:-1]):
                return          # 时间乱序: searchsorted 定段与旧线性扫不等价 → 慢路径
            vals = {}
            for k in self._CHANNELS:
                arr = np.array([fr[k] for fr in frames], dtype=np.float64)  # 缺 k→KeyError
                if arr.shape != (len(frames), 3):
                    return      # 非 3 分量值: 向量化插值语义不可保证 → 慢路径
                vals[k] = arr
        except (TypeError, ValueError, KeyError, IndexError, OverflowError):
            return              # 坏帧数据 → 永久慢路径 (采样时同旧代码报错)
        self._np_times = times
        self._np_vals = vals
        self._np_fast = True

    def _np_sync(self):
        """A6 (红线3): 缓存失效校验——frames 列表对象身份或长度变化即重建."""
        if self._np_key != (id(self.frames), len(self.frames)):
            self._np_rebuild()

    def sample(self, t):
        """时间 t 采样插值变换. 返回 { 'position':(x,y,z) | 'rotation':.. | 'scale':.. } 子集."""
        if not self.frames:
            return {}
        self._np_sync()
        if not self._np_fast or (type(t) is not float and type(t) is not int):
            return self._sample_slow(t)     # 特殊 t 类型 (bool/np 数/Decimal 等) → 旧循环语义
        dur = self.duration
        if dur > 0:
            t = t % dur
        if t != t:
            # NaN t (含 ±inf 取模结果): 旧循环 t<=x 全不命中 → 与旧实现一致保持末帧原值
            last = self.frames[-1]
            return {k: last[k] for k in self._CHANNELS if k in last}
        times = self._np_times
        i = int(np.searchsorted(times, t, side='left'))   # 首个 times[i] >= t
        if i >= len(times):
            # t 越过末帧 (仅 dur<=0 时可达): 与旧循环扫完一致, 保持末帧原值原对象
            last = self.frames[-1]
            return {k: last[k] for k in self._CHANNELS if k in last}
        if i == 0:
            i = 1   # t<=首帧时间: 旧循环首查 i=1 → 段 (0,1) (t 早于首帧时 f<0 外推, 同旧)
        prev_t = float(times[i - 1])
        span = float(times[i]) - prev_t
        f = 0.0 if span <= 0 else (t - prev_t) / span   # 与旧实现同一公式同一顺序
        out = {}
        for k in self._CHANNELS:
            a = self._np_vals[k][i - 1]
            b = self._np_vals[k][i]
            # 行向量化插值: 与旧公式 a[j]+(b[j]-a[j])*f 同序 (减→乘→加), IEEE754
            # 逐位同源; tolist() 转回 Python float 再组 tuple (输出类型与旧一致)
            out[k] = tuple((a + (b - a) * f).tolist())
        return out

    def _sample_slow(self, t):
        """A6 慢路径: 旧逐帧线性扫原样保留 (语义基准)."""
        dur = self.duration
        if dur > 0:
            t = t % dur
        prev = self.frames[0]
        for i in range(1, len(self.frames)):
            nxt = self.frames[i]
            if t <= nxt['time']:
                span = nxt['time'] - prev['time']
                f = 0.0 if span <= 0 else (t - prev['time']) / span
                out = {}
                for k in ('position', 'rotation', 'scale'):
                    if k in prev and k in nxt:
                        a, b = prev[k], nxt[k]
                        out[k] = tuple(a[j] + (b[j] - a[j]) * f for j in range(3))
                    elif k in prev:
                        out[k] = prev[k]
                return out
            prev = nxt
        return {k: prev[k] for k in ('position', 'rotation', 'scale') if k in prev}


class AnimatorComponent(Component):
    """动画组件 (M35, Unity Animator 简化): 挂物体播放关键帧变换动画.
    clips     {'动画名': AnimationClip}
    current   当前动画名 (None=不播)
    time      当前播放时间 (秒)
    playing   是否播放 (脚本 play/stop)
    loop      是否循环 (播到末帧停)"""
    ctype = 'animator'

    def __init__(self, clips=None, current=None, loop=True):
        super().__init__()
        self.clips = clips or {}
        self.current = current
        self.time = 0.0
        self.playing = False
        self.loop = bool(loop)

    def play(self, name, restart=False):
        """播放/切换到动画 (restart=True 从头播)."""
        if restart or self.current != name:
            self.time = 0.0
        self.current = name
        self.playing = True

    def stop(self):
        self.playing = False


class AudioSystem:
    """M34: 音频后端封装 (B2 2026-08-30 换库: 委托 audio_backend.AudioBackend).

    主后端 = game-audio (miniaudio); 兜底 = pygame.mixer (现状语义); 两者皆失败
    → 全静默 no-op (与现状无设备同语义). 公开 API 语义不变: 文件缺失不崩,
    播放失败静默; owner=组件身份 (id 组件) 供同 clip 多组件独立音量.
    ★退出必须 shutdown() (miniaudio 设备线程; 引擎退出链 + atexit 三重兜底)."""
    def __init__(self):
        self._backend = None   # 惰性 (audio_backend.AudioBackend)
        self._init_done = False

    def _ensure(self):
        if not self._init_done:
            from audio_backend import AudioBackend
            self._backend = AudioBackend()
            self._init_done = True
        return self._backend

    def load(self, path):
        """加载/缓存句柄 (失败 None 缓存, 不崩). 无 owner = 共享句柄 (一次性音效)."""
        b = self._ensure()
        return b.load(path, owner=None)

    def play(self, path, loop=False, volume=1.0, owner=None):
        """播放音效 (loop=True 循环). 文件缺失/后端失败静默跳过."""
        self._ensure().play(path, loop=loop, volume=volume, owner=owner)

    def stop(self, path, owner=None):
        """停止 (幂等; 未播放/未加载静默)."""
        b = self._ensure()
        b.stop(path, owner=owner)

    def play_sound(self, path, volume=1.0):
        """脚本用: 一次性音效 (如跳跃/碰撞)."""
        self.play(path, loop=False, volume=volume)

    def shutdown(self):
        """关闭音频设备后端 (幂等; 进程退出链 + atexit 兜底)."""
        if self._backend is not None:
            try:
                self._backend.shutdown()
            except Exception:
                pass


# ================ 材质资产 (M23) ================
class Material:
    """材质资产: 颜色 + 饱和度, 可被多个物体共享 (资产即数据的第一步).
    改一个材质 -> 所有引用它的物体一起变, 与 Unity 材质资产语义一致.
    guid 为稳定身份, 场景/Prefab 序列化引用用."""

    def __init__(self, color=None, saturation=1.0, name=None, guid=None):
        # 组1: 缓存字段先建 (下方 self.color= 走 property setter 时才有落点)
        self._rgba = None                        # (4,) f32 | None (随 color)
        self._sat_f32 = 0.0
        self.color = color                       # 单色覆盖 (hex 字符串) 或 None=网格面色
        self.saturation = float(saturation)      # 0=灰阶, 1=原始, >1=增艳
        self.name = name or '材质'
        self.guid = guid or uuid.uuid4().hex
        # 组1 (2026-08-30) 实例数据批: 渲染侧逐帧消费的 f32 缓存 (创建时算一次,
        # setter 置脏) —— 消每帧逐物体 hex 解析/属性链 (_prepare_bucket_frame
        # 与 vk draw_frame 消费). _rgba 复用 _hex_rgba 同源逻辑 (含 tuple 色
        # 灰色回退) 保证与旧路径逐位一致; color=None 时 _rgba=None (写入端留 0).

    @property
    def color(self):
        return self._color
    @color.setter
    def color(self, v):
        self._color = v
        self._rgba = None if v is None else np.asarray(
            _hex_rgba(v), dtype='f4')            # 同源转换, 逐位一致

    @property
    def saturation(self):
        return self._sat
    @saturation.setter
    def saturation(self, v):
        self._sat = float(v)
        self._sat_f32 = self._sat


# ================ 模型状态 (场景物体) ================
class GameObject:
    """场景物体 (M25 组件化): 容器 + 组件列表.
    组成: TransformComponent + MeshRendererComponent + ScriptComponent[] (可多个).
    便捷属性 (position/color/script_id/...) 委托到组件, 兼容旧代码;
    新代码应直接访问 self.transform / self.renderer / self.scripts."""

    def __init__(self, mesh, position, rotation,
                 name=None, scale=None, visible=True,
                 primitive=None, params=None, color=None, normal_mode='flat',
                 saturation=1.0):
        self.name = name
        # 稳定身份 (M16): 场景/Prefab 引用用
        self.guid = None
        self.prefab_ref = None
        # —— 组件 (M25) ——
        self.components = []
        self.transform = TransformComponent(position, rotation, scale)
        self.transform.owner = self
        self.renderer = MeshRendererComponent(mesh, color, normal_mode, primitive,
                                              params, saturation, visible)
        self.renderer.owner = self
        self.components += [self.transform, self.renderer]
        self.scripts = []            # ScriptComponent 列表 (可挂多个)
        # 碰撞体 (M28): 球体网格自动用球体碰撞体, 其余用 AABB 盒
        auto_shape = 'sphere' if primitive == 'sphere' else 'box'
        self.collider = ColliderComponent(shape=auto_shape)
        self.collider.owner = self
        self.components += [self.collider]
        self.rigidbody = None        # M31: 刚体组件 (None=无刚体, 不受重力/速度物理)
        self.audio_source = None     # M34: 音频源组件 (None=无音频, 不发声)
        self.animator = None         # M35: 动画组件 (None=无动画)
        self.light = None            # 预留: 物体上可选的光源组件 (本期未用)
        self.camera_children = []    # 2026-08-16 相机物体化: 挂在本物体下的摄像机
                                     # (独立列表, 不进 transform.children —— 后者只装
                                     #  GameObject, 避免 models 的 children 迭代误伤)
        # GPU 几何 (add_model 时构建; 运行态, 不序列化)
        self.vbo = None
        self.vao = None
        self._shadow_vao = None   # M29: 阴影深度 pass 专用 VAO (独立 positions-only VBO)
        self._shadow_vbo = None
        self.n_vertices = 0
        # 组1 (2026-08-30) 桶键缓存: mesh/normal_mode/primitive/params setter
        # 置脏 (None), 帧内 _mesh_key 惰性重建 —— 消每帧 json.dumps(params).
        # 边界: params dict 原地 mutate (不经 setter) 不会失效缓存 —— 全库
        # 无此用法 (mesh.py 创建期/sceneio 读取期均走赋值), 注释备案.
        self._bucket_key = None

    # ================ 变换便捷 (委托 TransformComponent) ================
    @property
    def position(self):
        return self.transform.position
    @position.setter
    def position(self, v):
        self.transform.position = Point3D(*v)
    @property
    def rotation(self):
        return self.transform.rotation
    @rotation.setter
    def rotation(self, v):
        self.transform.rotation = Point3D(*v)
    @property
    def scale(self):
        return self.transform.scale
    @scale.setter
    def scale(self, v):
        self.transform.scale = tuple(v)
    @property
    def parent(self):
        return self.transform.parent
    @parent.setter
    def parent(self, v):
        self.transform.parent = v
        # 组2/组3: 旁路挂父 (脚本/编辑器直写) 也失效引擎侧 ancestry+SoA 缓存.
        # GameObject 无引擎引用 -> 类级弱实例表 (GLEngine.__init__ 注册);
        # 只脏不净 (多算不 错算), 无活实例时静默 (引擎未建则无缓存可脏).
        for ref in tuple(getattr(GLEngine, '_LIVE_INSTANCES', ())):
            e = ref()
            if e is not None:
                try:
                    e._bump_struct()
                except Exception:
                    pass
    @property
    def children(self):
        return self.transform.children

    # ================ 渲染便捷 (委托 MeshRendererComponent) ================
    @property
    def mesh(self):
        return self.renderer.mesh
    @mesh.setter
    def mesh(self, v):
        self._bucket_key = None               # 组1: 换网格重键 (防御; 键本身不含 mesh)
        self.renderer.mesh = v
    @property
    def color(self):
        return self.renderer.material.color
    @color.setter
    def color(self, v):
        self.renderer.material.color = v
    @property
    def normal_mode(self):
        return self.renderer.normal_mode
    @normal_mode.setter
    def normal_mode(self, v):
        self._bucket_key = None               # 组1: 桶键成分置脏
        self.renderer.normal_mode = v
    @property
    def primitive(self):
        return self.renderer.primitive
    @primitive.setter
    def primitive(self, v):
        self._bucket_key = None               # 组1: 桶键成分置脏
        self.renderer.primitive = v
    @property
    def params(self):
        return self.renderer.params
    @params.setter
    def params(self, v):
        self._bucket_key = None               # 组1: 桶键成分置脏
        self.renderer.params = v
    @property
    def saturation(self):
        return self.renderer.material.saturation
    @saturation.setter
    def saturation(self, v):
        self.renderer.material.saturation = float(v)
    @property
    def visible(self):
        return self.renderer.visible
    @visible.setter
    def visible(self, v):
        self.renderer.visible = bool(v)

    # ================ 脚本便捷 (操作 scripts[0], 兼容旧单脚本 API) ================
    @property
    def script_id(self):
        return self.scripts[0].script_id if self.scripts else None
    @script_id.setter
    def script_id(self, v):
        if v is None:
            self.clear_scripts()
        elif self.scripts:
            self.scripts[0].script_id = v
        else:
            self.add_script(v)
    @property
    def script_vars(self):
        return self.scripts[0].script_vars if self.scripts else {}
    @script_vars.setter
    def script_vars(self, v):
        if self.scripts:
            self.scripts[0].script_vars = dict(v)
        elif v:
            self.add_script(None, dict(v))
    # 运行态委托 (仅供旧代码; 新代码直接遍历 m.scripts 访问每个 sc)
    @property
    def _script(self):
        return self.scripts[0]._script if self.scripts else None
    @_script.setter
    def _script(self, v):
        if self.scripts:
            self.scripts[0]._script = v
    @property
    def _script_broken(self):
        return self.scripts[0]._script_broken if self.scripts else False
    @_script_broken.setter
    def _script_broken(self, v):
        if self.scripts:
            self.scripts[0]._script_broken = v

    # ================ 脚本管理 (M25: 多脚本) ================
    def add_script(self, script_id, script_vars=None):
        """挂一个脚本组件 (可多个). 返回 ScriptComponent."""
        sc = ScriptComponent(script_id, script_vars)
        sc.owner = self
        self.scripts.append(sc)
        self.components.append(sc)
        return sc

    def remove_script(self, index):
        """移除第 index 个脚本组件 (返回被移除者或 None)."""
        if 0 <= index < len(self.scripts):
            sc = self.scripts.pop(index)
            if sc in self.components:
                self.components.remove(sc)
            return sc
        return None

    def clear_scripts(self):
        """清空全部脚本组件 (撤销还原/退出播放用)."""
        for sc in self.scripts:
            if sc in self.components:
                self.components.remove(sc)
        self.scripts.clear()

    def get_script(self, index):
        """取第 index 个脚本组件 (越界返回 None)."""
        if 0 <= index < len(self.scripts):
            return self.scripts[index]
        return None

    def add_rigidbody(self, mass=1.0, use_gravity=True, is_kinematic=False,
                      friction=0.5, restitution=0.0, rolling_friction=0.1):
        """M31: 给物体加刚体组件 (返回 RigidbodyComponent).
        加刚体后物体由引擎每帧按速度+重力带碰撞移动; 需要碰撞体积请保留 collider.
        B1: friction/restitution/rolling_friction = 动态体接触材质 (桥透传)."""
        rb = RigidbodyComponent(mass=mass, use_gravity=use_gravity,
                                is_kinematic=is_kinematic,
                                friction=friction, restitution=restitution,
                                rolling_friction=rolling_friction)
        rb.owner = self
        self.rigidbody = rb
        self.components.append(rb)
        return rb

    def remove_rigidbody(self):
        """移除刚体组件 (返回被移除者或 None)."""
        rb = self.rigidbody
        if rb is not None:
            self.rigidbody = None
            if rb in self.components:
                self.components.remove(rb)
        return rb

    def add_audio_source(self, clip=None, loop=False, volume=1.0):
        """M34: 给物体加音频源组件 (返回 AudioSourceComponent). 播放状态由 playing 控制."""
        a = AudioSourceComponent(clip=clip, loop=loop, volume=volume)
        a.owner = self
        self.audio_source = a
        self.components.append(a)
        return a

    def remove_audio_source(self):
        """移除音频源组件 (返回被移除者或 None)."""
        a = self.audio_source
        if a is not None:
            self.audio_source = None
            if a in self.components:
                self.components.remove(a)
        return a

    def add_animator(self, clips=None, current=None, loop=True):
        """M35: 给物体加动画组件 (返回 AnimatorComponent). clips={'名': AnimationClip}."""
        an = AnimatorComponent(clips=clips, current=current, loop=loop)
        an.owner = self
        self.animator = an
        self.components.append(an)
        return an

    def remove_animator(self):
        """移除动画组件 (返回被移除者或 None)."""
        an = self.animator
        if an is not None:
            self.animator = None
            if an in self.components:
                self.components.remove(an)
        return an

    # ================ 便捷方法 ================
    def set_scale(self, scale):
        """设置缩放 (tuple (sx,sy,sz))"""
        self.scale = tuple(scale)

    def set_name(self, name):
        """设置显示名称"""
        self.name = name

    def set_visible(self, visible):
        """设置可见性"""
        self.visible = bool(visible)


# ================ 光源状态 ================
def wrap_deg(v, lo=0.0, hi=360.0):
    """角度环绕: 把 v 环绕进 [lo, hi). 用于 朝向/俯仰/倾斜 拖拽越过边界后继续转.
    已在范围内则原样返回 (避免取模引入 ~1e-13 浮点噪声)."""
    if lo <= v < hi:
        return v
    span = hi - lo
    return lo + ((v - lo) % span)


def direction_to_angles(d):
    """平行光行进方向向量 -> (azimuth, elevation) 度.
    引擎 Y-up (高度=y, 前方=+z): az=0,el=0 -> +z 前; el=+90 -> +y 上; el=-90 -> -y 下.
    az 绕 y 轴, 与 mat4_view_yaw_pitch 的 yaw 同约定. 竖直方向 (el=±90) az 退化为 0."""
    x, y, z = d
    n = math.sqrt(x * x + y * y + z * z) or 1.0
    x, y, z = x / n, y / n, z / n
    el = math.degrees(math.asin(max(-1.0, min(1.0, y))))
    az = math.degrees(math.atan2(x, z)) if (z or x) else 0.0
    return wrap_deg(az, 0.0, 360.0), el


class LightState:
    """场景光源实体: 不可见 (不渲染网格)、无碰撞 (不参与射线拾取)。
    kind: 'directional' 平行光 / 'point' 点光源.
    M29: mode='full' 全场景平行光 | 'beam' 光束(截面平行光); shape/size 定光束截面;
    shadow=True 时投射阴影 (物体遮挡光线, shadow mapping).
    M30 (2026-08-12): 平行光方向改用 3 个角度参数 (度):
        azimuth  朝向   [0,360)  绕 y 轴的水平方位角, 0 = 朝 +z 前 (等价旧默认 direction=(0,-1,0) 需 el=-90)
        elevation 俯仰  (-180,180] 与水平面夹角, 0 = 水平, +90 = 朝上 (+y)
        roll      倾斜  (-180,180] 绕光方向线的自旋, 0 = "上方参考" (世界上方在垂直于方向线平面上的投影)
    direction 现在是派生只读属性 (行进方向), 由 azimuth+elevation 算得; 位置 position
    平行光固定 (不可像点光源那样调整, 仅作图标锚点/阴影视图原点)."""

    def __init__(self, kind='directional', position=None, direction=None,
                 color=(1.0, 1.0, 1.0), intensity=1.0, name=None, guid=None,
                 mode='full', shape='circle', size=5.0, shadow=True,
                 azimuth=None, elevation=None, roll=None):
        self.kind = kind                       # 'directional' | 'point'
        # 统一存 Point3D (sceneio 会传 tuple/Point3D 混用)
        self.position = Point3D(*position) if position is not None else Point3D(0, 5, 0)
        if azimuth is not None:
            self.azimuth = wrap_deg(float(azimuth), 0.0, 360.0)
            self.elevation = wrap_deg(float(elevation if elevation is not None else 0.0),
                                      -180.0, 180.0)
            self.roll = wrap_deg(float(roll if roll is not None else 0.0), -180.0, 180.0)
        else:
            az, el = direction_to_angles(direction if direction is not None else (0, 0, 1))
            self.azimuth = az
            self.elevation = el
            self.roll = wrap_deg(float(roll if roll is not None else 0.0), -180.0, 180.0)
        self._dir_cache = None                 # 组2: ((az,el,roll), direction) 惰性缓存
        self.color = tuple(color)
        self.intensity = float(intensity)
        # M29: 平行光模式 / 光束截面 / 阴影
        self.mode = mode                       # 'full' | 'beam'
        self.shape = shape                     # 'circle' | 'rect' (beam 截面)
        self.size = float(size)                # 截面尺寸: 圆=半径, 矩形=半边长
        self.shadow = bool(shadow)             # 是否投射阴影 (物理遮挡)
        self.name = name or ('平行光' if kind == 'directional' else '点光源')
        self.guid = guid or uuid.uuid4().hex   # 稳定身份 (序列化引用用)

    @property
    def direction(self):
        """平行光行进方向 (只读派生): 由 朝向 azimuth + 俯仰 elevation 计算 (引擎 Y-up).
        组2 (2026-08-30): 角度版缓存 —— 每帧 _upload_lights/阴影 VP/光束截面
        反复调本属性 + up_vector 的 trig (每光 5-8 次/帧) 降为角度变更时一次;
        azimuth/elevation/roll 或 direction 反算路径写入即 bump 版本失效."""
        gen = (self.azimuth, self.elevation, self.roll)
        if self._dir_cache is not None and self._dir_cache[0] == gen:
            return self._dir_cache[1]
        az = math.radians(self.azimuth)
        el = math.radians(self.elevation)
        d = Point3D(math.sin(az) * math.cos(el), math.sin(el),
                    math.cos(az) * math.cos(el))
        self._dir_cache = (gen, d)
        return d

    @direction.setter
    def direction(self, vec):
        """兼容旧赋值: 方向向量 -> 反算角度 (roll 归零; 方向向量不含自旋信息)."""
        az, el = direction_to_angles(vec)
        self.azimuth = az
        self.elevation = el
        self.roll = 0.0

    def up_vector(self):
        """光源"上方"参考向量 (垂直于方向线 d 的平面上).
        roll=0: 世界上方 (0,1,0) 在 ⊥d 平面上的投影 (即含 d 的竖直平面与 ⊥d 平面交线, 指向上).
        roll≠0: 绕 d 旋转该参考. 供阴影视图矩阵 / 光束截面基的 up 使用.
        组2: 复用 direction 缓存 (消旧版每次重调 direction 的重复 trig)."""
        d = self.direction
        dy = d.y
        denom = 1.0 - dy * dy
        if abs(denom) < 1e-6:
            # d 与世界上方平行: 参考退化, 用 +x (任意水平方向)
            up_ref = (1.0, 0.0, 0.0) if dy > 0 else (-1.0, 0.0, 0.0)
        else:
            s = 1.0 / math.sqrt(denom)
            up_ref = (-d.x * dy * s, denom * s, -d.z * dy * s)
        r = math.radians(self.roll)
        c = math.cos(r)
        sn = -math.sin(r)          # M30: 负绕向 (用户实测"倾斜"正负方向反了, 翻转)
        cx = d.y * up_ref[2] - d.z * up_ref[1]
        cy = d.z * up_ref[0] - d.x * up_ref[2]
        cz = d.x * up_ref[1] - d.y * up_ref[0]
        return Point3D(up_ref[0] * c + cx * sn, up_ref[1] * c + cy * sn,
                       up_ref[2] * c + cz * sn)


class CameraState:
    """场景摄像机实体 (Unity Camera 概念): 位置 + 朝向(yaw/pitch/roll) + 视角广度(fov).
    玩家视角 = 场景里某个摄像机 (active_camera) 的 位置/朝向/视角广度.
    fov_locked: 视角广度是否玩家可调 (由开发者决定; True=锁定, 玩家不可调).
    2026-08-16 (M41): 朝向改度制存储 (镜像平行光 M30): yaw [0,360) / pitch、roll 环绕
    (-180,180]; 新增 roll 倾斜 (FPS 侧头/被击倒摄像头歪斜); 新增俯仰角限制
    (pitch_lock + pitch_min/pitch_max 度, 玩家可调俯仰范围 = [pitch_min, pitch_max] 含两端).
    摄像机不可见 (不渲染网格)、无碰撞 (不参与拾取), 与光源同型实体."""

    def __init__(self, position=None, yaw=0.0, pitch=0.0, roll=0.0, fov=45.0,
                 fov_locked=True, name=None, guid=None,
                 pitch_lock=False, pitch_min=-85.0, pitch_max=85.0):
        self.position = Point3D(*position) if position is not None else Point3D(0, 0, -5)
        self.yaw   = wrap_deg(float(yaw), 0.0, 360.0)      # 度 [0,360) 水平朝向
        self.pitch = wrap_deg(float(pitch), -180.0, 180.0) # 度 垂直朝向
        self.roll  = wrap_deg(float(roll), -180.0, 180.0)  # 度 倾斜 (绕视线方向自旋)
        self.fov = float(fov)          # 度 (视角广度, 垂直 FOV)
        self.fov_locked = bool(fov_locked)
        self.name = name or '摄像机'
        self.guid = guid or uuid.uuid4().hex   # 稳定身份 (序列化引用用)
        # 俯仰角限制 (开发者配置; 玩家可调俯仰范围 = [pitch_min, pitch_max] 含两端)
        self.pitch_lock = bool(pitch_lock)
        self.pitch_min = float(pitch_min)
        self.pitch_max = float(pitch_max)
        # 相机物体化 (2026-08-16): 可挂父到普通 GameObject (如玩家), 世界 = 局部 × 父链合成.
        # 摄像机只可挂 GameObject (不可当父); children 对称占位, 本期恒空不参与任何迭代.
        self.parent = None
        self.children = []

    @property
    def direction(self):
        """摄像机前方方向 (只读派生, 度 -> 向量). 与 LightState.direction 同 trig."""
        yaw = math.radians(self.yaw)
        pitch = math.radians(self.pitch)
        return Point3D(math.sin(yaw) * math.cos(pitch), math.sin(pitch),
                       math.cos(yaw) * math.cos(pitch))

    def up_vector(self):
        """视线方向上的"上参考"方向 (垂直于 direction, 表示 roll 倾斜指向).
        镜像 LightState.up_vector: roll=0 = 世界上方在垂直于视线平面上的投影,
        roll≠0 绕视线方向自旋 roll 度 (负绕向 M30 同款). 供摄像机 roll 方向标识画箭头."""
        d = self.direction
        dy = d.y
        denom = 1.0 - dy * dy
        if abs(denom) < 1e-6:
            up_ref = (1.0, 0.0, 0.0) if dy > 0 else (-1.0, 0.0, 0.0)
        else:
            s = 1.0 / math.sqrt(denom)
            up_ref = (-d.x * dy * s, denom * s, -d.z * dy * s)
        r = math.radians(self.roll)
        c = math.cos(r)
        sn = -math.sin(r)          # M30: 负绕向 (与光源一致)
        cx = d.y * up_ref[2] - d.z * up_ref[1]
        cy = d.z * up_ref[0] - d.x * up_ref[2]
        cz = d.x * up_ref[1] - d.y * up_ref[0]
        return Point3D(up_ref[0] * c + cx * sn, up_ref[1] * c + cy * sn,
                       up_ref[2] * c + cz * sn)


class RuntimeUI:
    """M33 运行时 UI (Unity uGUI 简化): 脚本每帧用 engine.ui 声明文字/按钮/进度条,
    引擎 render 末尾画在屏幕 HUD 层 (屏幕像素坐标, 左上角 y 向下).
    与编辑器自绘 GUI 分离 —— 这是"游戏里的 UI"(分数/生命/菜单), 非编辑器面板."""
    def __init__(self, engine):
        self.engine = engine
        self.cmds = []

    def clear(self):
        self.cmds = []

    def text(self, text, x, y, size=18, color=(255, 255, 255)):
        """HUD 文字 (左上角坐标)."""
        self.cmds.append(('text', str(text), int(x), int(y), size, tuple(color)))

    def button(self, uid, rect, text, size=15):
        """HUD 按钮: 返回 True = 本帧被点击 (鼠标在矩形内且本帧按下左键)."""
        e = self.engine
        clicked = False
        if 1 in getattr(e, 'pressed', ()):
            mx, my = e.mouse_pos
            if (rect[0] <= mx < rect[0] + rect[2] and
                    rect[1] <= my < rect[1] + rect[3]):
                clicked = True
        self.cmds.append(('button', uid, tuple(rect), str(text), size))
        return clicked

    def bar(self, rect, frac, color=(80, 220, 120)):
        """HUD 进度条 (0..1 填充)."""
        self.cmds.append(('bar', tuple(rect), max(0.0, min(1.0, float(frac))),
                          tuple(color)))

    def draw(self):
        """绘制全部 UI 命令到屏幕 (正交 HUD); render 末尾调用."""
        e = self.engine
        for c in self.cmds:
            if c[0] == 'text':
                _, t, x, y, size, col = c
                e.draw_text_quad(t, x, y, col, size)
            elif c[0] == 'button':
                _, _uid, r, t, size = c
                e.draw_screen_rect(r, (52, 60, 76))                     # 背景
                e.draw_screen_rect((r[0], r[1], r[2], 2), (210, 220, 235))   # 边框
                e.draw_screen_rect((r[0], r[1] + r[3] - 2, r[2], 2), (210, 220, 235))
                e.draw_screen_rect((r[0], r[1], 2, r[3]), (210, 220, 235))
                e.draw_screen_rect((r[0] + r[2] - 2, r[1], 2, r[3]), (210, 220, 235))
                tw = e._measure_text(t, size)[0]                        # 居中文字
                e.draw_text_quad(t, r[0] + max((r[2] - tw) // 2, 0),
                                 r[1] + max((r[3] - size) // 2, 0),
                                 (255, 255, 255), size)
            elif c[0] == 'bar':
                _, r, frac, col = c
                e.draw_screen_rect(r, (40, 44, 54))                     # 背景
                fw = int(r[2] * frac)
                if fw > 0:
                    e.draw_screen_rect((r[0], r[1], fw, r[3]), col)     # 填充
        self.cmds = []


# ================ 按键绑定配置 (可在此处修改) ================
KEY_BINDINGS = {
    # 相机移动控制
    'CAMERA_FORWARD': 'w',
    'CAMERA_BACKWARD': 's',
    'CAMERA_LEFT': 'a',
    'CAMERA_RIGHT': 'd',
    'CAMERA_UP': 'q',
    'CAMERA_DOWN': 'e',

    # 相机视角控制
    'LOOK_LEFT': 'Left',
    'LOOK_RIGHT': 'Right',
    'LOOK_UP': 'Up',
    'LOOK_DOWN': 'Down',

    # 模型选择 (2026-08-28: 删除 'RESET_ALL': 'space' 空格复位 —— 玩具期键位表
    # 遗留, 与输入动作'跳跃'共用空格键, 玩家游戏内按空格(跳跃)被复位回出生点)
    'SELECT_NEXT_MODEL': 'Tab',
}
# ============================================================

# ================ hex 颜色 -> rgba (A2 实例颜色/共享几何用, 缓存) ================
_HEX_RGBA_CACHE = {}


def _hex_rgba(c):
    """'#RRGGBB' -> (r,g,b,alpha=1.0) float 元组 (失败回退灰色 .5)."""
    t = _HEX_RGBA_CACHE.get(c)
    if t is None:
        try:
            t = (int(c[1:3], 16) / 255.0, int(c[3:5], 16) / 255.0,
                 int(c[5:7], 16) / 255.0, 1.0)
        except Exception:
            t = (0.5, 0.5, 0.5, 1.0)
        _HEX_RGBA_CACHE[c] = t
    return t


# ================ GC 生命周期 (2026-09-01 流畅度批, 1% low 帧尖刺治理) ================
# 依据 (GC 批设计规格): 500 球场景 501 独立 Mesh 各带 vertices/faces/face_colors
# 大 list ≈ 490 万槽/次 gen2 遍历, 默认阈值下单次 gen2 停顿 20-150ms、约每 5-8 帧
# 有资格触发 —— 即用户实测"运动时掉帧卡顿感"的本体. 治理 = freeze 永久代化场景 +
# 播放态放宽阈值 (只放宽, 不 disable).
_GC_THRESH_PLAY = (50000, 50, 200)
# 依据: threshold0 700→50000 (500 球播放期 churn 12-15K tracked 对象/帧, 默认每帧
# 可触 17-21 次 gen0; 50000 → 约 1 次/3-4 帧); threshold1/2 放宽使 gen2 自动触发
# 降到数分钟级, 配合 freeze 后 gen2 单价也从 20-150ms 降到 <1ms.
# 备选档 (20000, 25, 100): 若 LOOM_GC_PROBE 实测 gen0 单次 p99 > 1ms 再降档.
_gc_thresh_prev = None      # 进入前 gc.get_threshold() 快照 (退出恢复, 非硬编码)
_gc_play_active = False     # 冻结态标志 (PlayerApp.load_scene 包裹判据/探针查询)

# ★铁律: 禁止 gc.disable ——
#   1) 脚本实例天然成环: update_scripts 绑 s.obj=m / s.engine=self; remove_model
#      (播放中) 后遗留 s.obj→m→sc→_script→s 真环, refcount 不可回收, 必须靠代际回收;
#   2) 用户脚本更易造环 (self 挂回调/缓存/监听);
#   3) 发布 exe 玩家长局无兜底重启时机, disable = 内存单调上涨;
#   4) 自定义脚本生态 (scripts.py 注册制) 是硬要求, 不能牺牲循环回收换流畅.


def _gc_enabled():
    """LOOM_GC_LEGACY=1 时全部 GC 管理变 no-op (A/B 基线 + 秒级回滚通道)."""
    return os.environ.get('LOOM_GC_LEGACY') != '1'


def engine_gc_frozen():
    """当前是否处于冻结播放态 (load_scene 包裹判据; 探针/测试用)."""
    return _gc_play_active


def gc_play_enter():
    """进入常驻播放态调用 (PlayerApp 场景加载后 / EditorApp toggle_play 进播放 /
    压测探针预热后): full collect 清进入前垃圾 → freeze 把全部 tracked 对象移入
    永久代 (490 万槽从此不进 gen2 遍历) → 放宽阈值. 冻结对象仍完全可用,
    只是 GC 不再扫/收. 一次性代价: collect 在加载尾 ~20-150ms@500球 (加载时刻)."""
    global _gc_thresh_prev, _gc_play_active
    import gc
    if not _gc_enabled():
        return
    try:
        gc.collect()                      # 只冻"活的" (冻结对象 unfreeze 前永不回收)
        gc.freeze()
        if _gc_thresh_prev is None:
            _gc_thresh_prev = gc.get_threshold()
        gc.set_threshold(*_GC_THRESH_PLAY)
        _gc_play_active = True
    except Exception as e:
        print("[gc] gc_play_enter 失败 (忽略, 回退默认 GC): %r" % (e,))


def gc_play_exit():
    """退出播放态调用 (EditorApp toggle_play 退播放 / PlayerApp.load_scene 包裹):
    unfreeze (冻结对象回普通代, 播放期垃圾/断环可回收) → full collect →
    阈值恢复进入前实测值. 幂等: 未 enter 时 unfreeze/collect 亦无害."""
    global _gc_thresh_prev, _gc_play_active
    import gc
    if not _gc_enabled():
        return
    try:
        gc.unfreeze()
        gc.collect()
        if _gc_thresh_prev is not None:
            gc.set_threshold(*_gc_thresh_prev)
            _gc_thresh_prev = None
        _gc_play_active = False
    except Exception as e:
        print("[gc] gc_play_exit 失败 (忽略): %r" % (e,))


class GLEngine:
    # 组2 (2026-08-30) _ancestry_ranges 结果缓存 (tin/tout, 类级):
    # key=(id(models 列表对象), _ANCESTRY_GEN 版本号); 五个结构变更点
    # (add_model/remove_model/clear_scene/set_parent/remove_camera) 写 _ANCESTRY_GEN
    # 失效. 挂类级而非实例级: _ancestry_ranges 是 @staticmethod, 无 self 可挂;
    # 多实例共存时 id(models) 对象身份区分列表, 版本号全类共享只会"多算不会错算".
    # 组3 (2026-08-30) SoA: 类属性 _ANCESTRY_GEN 换为实例属性守卫 _bump_struct()
    # (多引擎实例互不误伤; 各失效点改调 self._bump_struct()).
    _ANCESTRY_CACHE = None

    def _bump_struct(self):
        """组3: 结构变更计数器 (SoA 平面快照 + ancestry 缓存共用失效源).
        实例属性守卫: 测试桩 (__new__ 不跑 __init__) 无 _struct_gen 时惰性建."""
        try:
            self._struct_gen += 1
        except AttributeError:
            self._struct_gen = 1

    # 组3: 活实例弱引用表 (GameObject.parent 旁路置脏用; __init__ 注册,
    # 弱引用自动回收死实例)
    import weakref as _weakref
    _LIVE_INSTANCES = []

    def __init__(self, width=800, height=800, fov_deg=45.0, ctx=None):
        # 组3: 活实例弱注册 (GameObject.parent 旁路失效通道; 死实例自动脱落)
        cls_live = GLEngine._LIVE_INSTANCES
        cls_live[:] = [r for r in cls_live if r() is not None]
        cls_live.append(GLEngine._weakref.ref(self))
        self._struct_gen = 0                   # 组3: 结构变更计数器 (SoA+ancestry)
        self.width = width
        self.height = height
        self.window_size = (width, height)   # 窗口模式尺寸 (F11 全屏恢复用)
        self.fullscreen = False              # 假全屏 (无边框铺满, 不切分辨率)
        self.allow_fullscreen = True         # 是否允许 F11 全屏 (编辑器 False / 封装游戏 True; 2026-08-17)
        self._window_rect = None             # 全屏前的窗口矩形 (退出还原位置用)
        self.fov_deg = fov_deg
        self._fov = math.radians(fov_deg)
        self.near = 0.1
        self.far = 100.0

        # ================ 相机/渲染参数 (可在此处修改) ================
        self.camera = Point3D(0, 0, -5)   # 初始相机位置 (2026-08-28: camera_initial 死字段已并)
        self.camera_move_speed = 3.0      # 相机移动速度 (单位/秒)
        self.camera_rotation_speed = 0.6  # 相机旋转速度 (弧度/秒)
        # 2026-08-30 用户实测: 重力加速度可调 (m/s², 负=向下; 默认 -9.8 同 _GRAVITY).
        # 场景文件 'gravity' 字段按场景覆盖; 设置面板可改全局值 (即时生效);
        # 脚本/物理全部走 self.gravity —— 感觉偏慢直接调它, 不用改代码.
        self.gravity = -9.8
        # B1 (2026-08-30): Culverin (Jolt) 物理桥 (physics_bridge.py) —— 播放期接管
        # 刚体动力学 (速度/重力/接触解算/摩擦), 引擎几何碰撞管线全部保留 (混合式).
        # _phys_bridge: 桥实例 (None=未建/不可用); _phys_bridge_auto: 完整 __init__
        # 实例才惰性建桥 —— 测试桩用 __new__ 不跑 __init__, 无此属性 ->
        # getattr 回退 False -> update_physics 永远走 legacy 契约路径
        # (现契约测试零受影响; 详见 update_physics 2674 附近分支说明).
        self._phys_bridge = None
        self._phys_bridge_auto = True

        self.camera_yaw = 0      # 水平旋转角度 (弧度)
        self.camera_pitch = 0    # 垂直旋转角度 (弧度)
        self.camera_roll = 0     # 绕视线方向倾斜 (弧度, M41; 场景摄像机 roll 经 apply_camera 换算)

        # ================ 轨道相机 (编辑器模式用) ================
        self.orbit_mode = False          # True 时 render 用 apply_orbit_camera
        self.camera_target = (0.0, 0.0, 0.0)   # 轨道目标点
        self.camera_distance = 10.0            # 相机到目标距离

        # 场景光源列表 (实体): 无默认光源, 由用户手动添加 (平行光/点光源)
        self.lights = []
        # 场景摄像机列表 (实体, Unity Camera 概念): 玩家视角 = active_camera
        self.cameras = []
        self.active_camera = None      # 当前玩家视角摄像机 guid (None = 默认轨道相机)
        # 材质库 (M23): 场景内全部 Material 资产, 物体按引用共享 (改一处全变)
        self.materials = []

        # ================ 窗口 + OpenGL 上下文 ================
        # ctx 注入 = 嵌入式模式 (2026-08-17): 宿主 (Qt QOpenGLWidget) 已建好 moderngl
        # 上下文, 引擎不再创建 pygame 窗口 —— pygame(SDL) 窗口会进程级污染中文输入法
        # (IME) 候选框 (见记忆 sdl-window-contaminates-ime), 编辑器弃用 pygame 做窗口;
        # 游戏播放器 (PlayerApp) 仍走 pygame 分支, 行为不变.
        self._external_ctx = ctx is not None
        self._desktop_override = None   # 测试钩子: 固定桌面分辨率
        if ctx is None:
            pygame.init()
            pygame.display.gl_set_attribute(pygame.GL_CONTEXT_MAJOR_VERSION, 3)
            pygame.display.gl_set_attribute(pygame.GL_CONTEXT_MINOR_VERSION, 3)
            pygame.display.gl_set_attribute(pygame.GL_CONTEXT_PROFILE_MASK,
                                            pygame.GL_CONTEXT_PROFILE_CORE)
            self.window = pygame.display.set_mode((width, height),
                                                  pygame.OPENGL | pygame.DOUBLEBUF
                                                  | pygame.RESIZABLE)
            pygame.display.set_caption("Loom - OpenGL (moderngl) GPU 渲染")
            # 窗口创建前的桌面分辨率 (Info() 在窗口存在后只返回当前窗口尺寸, 不可信;
            # F11 假全屏要铺满屏幕, 用真桌面尺寸; 运行中桌面分辨率变化极少, 此快照够用)
            _di = pygame.display.Info()
            self._desktop_size = (_di.current_w, _di.current_h)
            # 从控制台(.bat)启动时窗口可能抢不到键盘焦点 -> 强制置前
            # (Windows 限制: SetForegroundWindow 只在进程允许时生效, 创建窗口后立即调用一般可行)
            try:
                import ctypes
                hwnd = pygame.display.get_wm_info()['window']
                ctypes.windll.user32.SetForegroundWindow(hwnd)
            except Exception:
                pass
            # 关闭文本输入合成, 避免中文输入法(IME)吞掉字母/方向键的 KEYDOWN
            pygame.key.stop_text_input()
            self.ctx = moderngl.create_context()
        else:
            self.window = None                 # 外部模式: 无 pygame 窗口 (Qt 宿主管窗口)
            self._desktop_size = (width, height)
            self.ctx = ctx
        self.ctx.viewport = (0, 0, width, height)
        self.ctx.enable(moderngl.DEPTH_TEST)
        self.ctx.enable(moderngl.CULL_FACE)
        # view 前方 +z 约定 (相机在 -z 看向 +z): 法线朝外的面在屏幕空间绕序是 CW
        # (标准 OpenGL 前方 -z 才是 CCW), 所以 front_face 必须设为 cw, 否则正面被剔除
        self.ctx.front_face = 'cw'

        # 着色器程序
        self.prog = self.ctx.program(vertex_shader=_VERT_SRC, fragment_shader=_FRAG_SRC)
        self.hud_prog = self.ctx.program(vertex_shader=_HUD_VERT, fragment_shader=_HUD_FRAG)
        self._build_hud_quad()
        # M29 阴影: 深度 pass 着色器 + 阴影贴图缓存 (guid -> {'type','tex','fbo'})
        self._shadow_prog = self.ctx.program(vertex_shader=_SHADOW_VERT,
                                             fragment_shader=_SHADOW_FRAG)
        self._shadow_maps = {}
        self._shadow_res = 1024        # 平行光阴影分辨率
        self._shadow_point_res = 512   # 点光阴影面分辨率
        self._shadow_point_far = 30.0  # 点光阴影远平面 (距离归一)
        # A2 (2026-08-29): GL 实例化批绘制 —— 按 mesh 桶共享几何/桶级实例缓冲:
        # 逐物体 draw 循环换成桶内一次 draw (50 球 51 draw -> ~3 draw).
        self._bucket_geo = {}     # mesh 桶 key -> {'vbo','vao','sha_vbo','sha_vao','nv'}
        self._bucket_inst = {}    # mesh 桶 key -> {'main','sha','n'} 实例缓冲 (容量生长)
        self._fw32 = None         # 当帧世界矩阵 f32 持久容量缓冲 (cap>=n 每帧原地 cast, GC 批)
        self._render_buckets = [] # 当帧 (桶 key, 模型下标列表) 列表

        # 字体 (微软雅黑, 含中文; 找不到再退回默认)
        self.font = self._load_font(16)
        self._font_cache = {}                 # size -> pygame.font (GUI 用不同字号)
        # 文字纹理 LRU 缓存 (key=(text,color,size) -> (tex,w,h)), 防每帧重复建纹理
        from collections import OrderedDict
        self._text_cache = OrderedDict()
        self._text_cache_max = 400

        # ================ 模型状态初始化 ================
        from mesh import create_cube, create_sphere
        self.models = []
        self.current_model_index = 0
        # 立方体 (主) — 平直光照 (面法线)
        self.add_model(create_cube(1.5),
                       Point3D(0, 0, 0), Point3D(0, 0, 0),
                       normal_mode='flat')
        # 立方体 (小, 右侧) — 平直光照 (面法线)
        self.add_model(create_cube(1.5 * 0.7),
                       Point3D(3, 0, 0), Point3D(0, 0, 0),
                       normal_mode='flat')
        # 高面数球体 (体现批量渲染, 前方偏上) — 光滑光照 (顶点径向法线)
        self.add_model(create_sphere(1.0, stacks=14, slices=28),
                       Point3D(0, 1.2, -1.5), Point3D(0, 0, 0),
                       normal_mode='vertex')
        # ======================================================

        # 按键: 字符配置 -> pygame 键码
        self._key = {name: _KEYMAP[ch] for name, ch in KEY_BINDINGS.items()}
        # 存储按键状态 (按住类按键; 2026-08-28 清除玩具期 MODEL_*/ROTATE_* 键控)
        self.key_state = {}
        for name in ('CAMERA_FORWARD', 'CAMERA_BACKWARD', 'CAMERA_LEFT', 'CAMERA_RIGHT',
                     'CAMERA_UP', 'CAMERA_DOWN', 'LOOK_LEFT', 'LOOK_RIGHT',
                     'LOOK_UP', 'LOOK_DOWN'):
            self.key_state[self._key[name]] = False

        # 帧率计数
        self.last_time = time.time()
        self.fps = 0
        self.frame_count = 0
        self.last_frame_time = time.time()
        self._running = False
        self.ui = RuntimeUI(self)        # M33: 运行时 UI (脚本声明 HUD/按钮/进度条)
        self.audio = AudioSystem()       # M34: 音频 (pygame.mixer 封装, Sound 缓存)
        # M38: 游戏脚本目录 (exe/引擎旁的 scripts/) 启动时加载注册
        # (Unity 项目脚本机制: 游戏专属脚本放这, 检查器可挂, 打包时随游戏分发)
        try:
            from scripts import load_script_dir
            load_script_dir(os.path.join(
                os.path.dirname(os.path.abspath(__file__)), 'scripts'))
        except Exception:
            pass

        # 脚本输入状态 (M27): 每帧 _handle_events 由 pygame.key.get_pressed 刷新,
        # 键名见 _KEYMAP ('w'/'space'/'Left'...). 脚本/游戏逻辑用 engine.is_key() 查询.
        self.script_keys = {}
        # M32: 鼠标相对移动 (每帧 get_rel, 供第一/第三人称玩家控制器转向; 非播放期不消费)
        self.mouse_rel = (0, 0)
        # M39: 鼠标锁定 (FPS 标准: 隐藏+捕获居中, 视角无限转; 释放后显示+滑动不转)
        self.mouse_locked = False
        self.mouse_unlock_requested = False   # 玩家主动解锁意图 (Tab 切换)
        self._ui_capture_mouse = False        # 特殊场景(UI 菜单/暂停)强制显示鼠标标志
        # 输入动作层 (M30b, Unity 输入系统理念): 动作 -> 键名列表, 可重映射.
        # 脚本用 engine.get_action('动作') —— 改键不动脚本.
        self.actions = dict(DEFAULT_ACTIONS)
        try:
            self._load_action_bindings()
        except Exception:
            self.actions = dict(DEFAULT_ACTIONS)

        # ================ 鼠标状态 (编辑器 GUI/gizmo 用) ================
        self.mouse_pos = (0, 0)
        self.buttons = (0, 0, 0)        # 当前按住的鼠标键 (pygame.get_pressed)
        self.pressed = set()            # 本帧新按下 (键码集合)
        self.released = set()           # 本帧新松开 (键码集合)
        self.mouse_wheel = 0            # 本帧滚轮 (ev.y, 上正下负)
        self.mouse_press_pos = {}       # 键码 -> 按下时坐标 (0/1/2)
        self._mods = 0                  # 本帧键盘修饰键 (pygame.key.get_mods)
        self.gui_dirty = True           # 异步GUI: 面板 FBO 需要重绘 (初始 True 保证首帧就渲)

        # ================ 并行/CPU 亲和性 (2026-08-14 多核优化) ================
        # 设置来自 设置.json (parallel_enable/script_cores/show_grid), 见 guiloader.
        # parallel: CPU 拓扑+亲和性策略 (parallel.get_parallel 单例); _script_runner:
        # 脚本专用线程 (固定绑预留大核, 同步模型); _collision_pool: 碰撞检测线程池
        # (自适应, 场景大才启用); _frame_world: 当帧批量世界矩阵 (阴影/主 pass 共享).
        self.parallel_enable = True
        self.script_cores = 2
        self.show_grid = True
        self.parallel = None
        self._script_runner = None
        self._collision_pool = None
        self._frame_pool = None
        self._main_core_sched = None      # 2026-08-15: 主线程锁负载最低大核调度器
        self._frame_world = None
        self._light_vps = {}              # 每帧阴影 view-proj 缓存 (shadow pass 与 upload 复用)
        self._bb_cache = {}               # 网格齐次顶点缓存 (get_bounding_box 热路径)
        self._aabb_staging = None         # spin 治理 (2026-08-31): 堆叠缓冲 thread-local 缓存 (惰性建)
        self._stage_times = {}            # LOOM_PROFILE=1 时逐阶段耗时 (诊断用)
        try:
            import guiloader
            _s = guiloader.load_settings('loom')
            self.parallel_enable = bool(_s.get('parallel_enable', True))
            self.script_cores = max(0, min(8, int(_s.get('script_cores', 2))))
            self.show_grid = bool(_s.get('show_grid', True))
            self.gravity = float(_s.get('gravity', self.gravity))   # 2026-08-30: 可调重力
        except Exception:
            pass
        # LOOM_NO_PARALLEL=1 测试守卫: 测试确定性, 不建脚本线程/不设进程亲和性
        if self.parallel_enable and os.environ.get('LOOM_NO_PARALLEL') != '1':
            try:
                from parallel import (get_parallel, ScriptRunner, FramePool,
                                      frame_workers, MainThreadCoreScheduler)
                self.parallel = get_parallel(self.script_cores)
                _m = (self.parallel.get('policy') or {}).get('script_mask')
                if _m:
                    self._script_runner = ScriptRunner(_m)
                # 每帧 CPU 预计算池 (2026-08-15 8 核均摊): 阴影 AABB/碰撞/矩阵分块丢这里,
                # numpy 释放 GIL -> 真并行; 主线程只做 GL/事件.
                _pol = self.parallel.get('policy') or {}
                _nw = frame_workers(_pol, target=8, script_cores=self.script_cores)
                _pm = _pol.get('pool_mask') or 0
                self._frame_pool = FramePool(_nw, _pm)
                # 2026-08-15 主线程核心调度: 重负载主线程锁到启动时负载最低的 P 核
                # (避开系统静态负载最高的核, 如 CPU1). 引擎本身负载高, 周期跳核会周期性
                # 卡顿 -> **只启动锁一次, 不做周期重选** (interval=0; LoomHub 才做 20s 重选).
                self._main_core_sched = None
                _topo = self.parallel.get('topology') or []
                if _topo:
                    self._main_core_sched = MainThreadCoreScheduler(
                        _topo, exclude_bits=_pol.get('script_mask') or 0,
                        interval=0.0)
                    _cb = self._main_core_sched.current_bit()
                    print("[parallel] 主线程锁定到负载最低的大核 #%s (启动锁一次, 不周期跳核)"
                          % ("?" if _cb is None else _cb))
                print("[parallel] 预计算池 %d worker (目标 8 核均摊, pool_mask=0x%X)"
                      % (_nw, _pm))
            except Exception as e:
                print("[parallel] 初始化失败, 回退单线程:", e)
                self.parallel = None
                self._script_runner = None
                self._frame_pool = None
                self._main_core_sched = None

    # ================ GPU 几何构建 ================
    def add_model(self, mesh, position, rotation, normal_mode='flat',
                  name=None, scale=None, visible=True, color=None, saturation=1.0):
        """
        添加模型并一次性上传展平几何到 VBO.
        normal_mode: 'flat' 用面法线 (平直光照, 立方体), 'vertex' 用顶点径向法线 (光滑光照, 球体)
        name/scale/visible/color: 编辑器扩展属性 (color 为 hex 时覆盖网格面色为单色材质)
        saturation: 终色饱和度 0..2 (0=灰阶, 1=原始, >1=增艳)
        """
        model = GameObject(mesh, position, rotation,
                           name=name, scale=scale, visible=visible,
                           primitive=getattr(mesh, 'primitive', None),
                           params=getattr(mesh, 'params', None),
                           color=color, normal_mode=normal_mode,
                           saturation=saturation)
        if model.name is None:
            # 自动命名: 按基元类型 (编辑器场景) / 网格种类 (默认场景)
            prim = model.primitive
            model.name = {None: '物体', 'cube': '立方体', 'sphere': '球体',
                          'plane': '平面'}.get(prim, '物体')
        # 稳定身份 (M16): 每个物体一个 GUID, 场景/Prefab 引用用
        if model.guid is None:
            model.guid = uuid.uuid4().hex
        self._build_gpu(model)
        self._register_model_material(model)   # M23: 材质进库, 供共享引用
        self.models.append(model)
        self._bump_struct()                    # 组3: 结构变更失效 (ancestry+SoA)
        return model

    # ================ 材质库管理 (M23) ================
    def add_material(self, color=None, saturation=1.0, name=None, guid=None):
        """新建材质并加入材质库 (供物体共享引用). 返回 Material."""
        mat = Material(color=color, saturation=saturation, name=name, guid=guid)
        self.materials.append(mat)
        return mat

    def _find_material(self, guid):
        """按 guid 在材质库找材质 (找不到返回 None)."""
        if guid:
            for mat in self.materials:
                if mat.guid == guid:
                    return mat
        return None

    def _register_model_material(self, model):
        """把物体自带的材质登记进材质库 (未在库中则加入), 保证共享可被引用."""
        mat = model.renderer.material
        if mat is not None and mat not in self.materials:
            self.materials.append(mat)

    def attach_model(self, model, index=None):
        """重新挂载已存在的 GameObject (撤销删除/Prefab 实例化): 重建 GPU 几何并加入列表."""
        if model.vbo is None or model.vao is None:
            self._build_gpu(model)
        if index is None:
            self.models.append(model)
        else:
            self.models.insert(index, model)
        self._bump_struct()                    # 组3: 结构变更失效 (ancestry+SoA)
        return model

    @staticmethod
    def _mesh_key(model):
        """A2 (2026-08-29): GL 桶键 = (基元类型, 参数 json, 法线模式) —— 与
        桶几何共享判据; 同键物体共享 vbo/vao/实例缓冲 (50 球 = 1 桶).
        组1 (2026-08-30): 键缓存挂 GameObject (_bucket_key, setter 置脏) ——
        每帧 json.dumps(params) 降为创建后一次. 无 _bucket_key 属性的
        对象 (测试桩/非 GameObject) 回退现算."""
        k = getattr(model, '_bucket_key', None)
        if k is not None and len(k) == 3:     # 3 元组=GL 键 (Vk 键 2 元组, 拒收防串)
            return k
        k = (getattr(model, 'primitive', None) or 'obj',
             json.dumps(getattr(model, 'params', None) or {}, sort_keys=True),
             getattr(model, 'normal_mode', 'flat'))
        try:
            model._bucket_key = k
        except AttributeError:
            pass                              # __slots__ 桩等不可写场景
        return k

    @staticmethod
    def _flatten_mesh(mesh, normal_mode):
        """网格 -> 展平 (3F,10) f4 + positions-only (3F,3) f4 (阴影 VAO 用).
        颜色 = 网格原生面色 (材质单色覆盖改走实例属性 a_col, 桶共享几何必须
        与物体解耦 —— 与 Vk 桶语义一致)."""
        verts = np.asarray(mesh.vertices, dtype='f4')       # (V,3)
        faces = np.asarray(mesh.faces, dtype=np.int32)      # (F,3)
        tri = verts[faces]                                  # (F,3,3)
        pos = tri.reshape(-1, 3)                            # (3F,3)

        mesh_normals = getattr(mesh, 'normals', None)
        if mesh_normals is not None and len(mesh_normals) == len(verts):
            # 外部网格 (obj 导入) 自带逐顶点法线 (来自 vn 或自动平滑): 直接采用,
            # 不再按 normal_mode 重算 —— Unity 语义: 导入法线优先于 flat/vertex 模式.
            vn_arr = np.asarray(mesh_normals, dtype='f4')   # (V,3)
            norm = vn_arr[faces].reshape(-1, 3)             # (3F,3)
        elif normal_mode == 'vertex':
            # 顶点径向法线: 每顶点归一化 (球心在原点) -> 展平
            ln = np.linalg.norm(verts, axis=1, keepdims=True)
            ln = np.where(ln == 0, 1.0, ln)
            vn = verts / ln
            norm = vn[faces].reshape(-1, 3)                 # (3F,3)
        else:
            # 面法线: 每三角形叉积归一 -> 按 3 顶点重复
            p0, p1, p2 = tri[:, 0], tri[:, 1], tri[:, 2]
            nrm = np.cross(p1 - p0, p2 - p0)                # (F,3)
            ln = np.linalg.norm(nrm, axis=1, keepdims=True)
            ln = np.where(ln == 0, 1.0, ln)
            nrm = nrm / ln
            norm = np.repeat(nrm, 3, axis=0)                # (3F,3)

        colors = np.zeros((len(face_colors := mesh.face_colors), 4), dtype='f4')
        for i, c in enumerate(face_colors):
            colors[i] = _hex_rgba(c)
        col = np.repeat(colors, 3, axis=0)                  # (3F,4)
        packed = np.concatenate([pos, norm, col], axis=1)   # (3F,10)
        return packed.astype('f4'), pos.astype('f4')

    def _build_gpu(self, model):
        """从 model.mesh 绑定桶几何资源 (add_model 与 attach_model 共用).
        A2 (2026-08-29): 几何按 mesh 桶共享 (同键 = 同 vbo/vao/实例缓冲), 物体
        只是"引用"桶资源 —— 删除单物体只解引用, 不释放共享资源 (归属桶, 清场
        统一释放, 见 _release_bucket_resources).
        2026-08-21: Qt 外部模式 UI 回调 (添加物体/导入) 里建 GL 资源前要求
        context current —— QOpenGLWidget 非 paintGL 时机不自动 makeCurrent,
        未激活时 moderngl 资源静默落错 context (VAO 有效但渲染零输出, 用户
        实测"空场景启动后添加物体不显示"). 由视图注入 _gl_guard 钩子."""
        guard = getattr(getattr(self, 'view', None), '_gl_guard', None)
        if guard is not None:
            guard()
        key = self._mesh_key(model)
        ent = self._bucket_geo.get(key)
        if ent is None:
            ent = self._build_bucket_geo(key, model)
        model.vbo = ent['vbo']
        model.vao = ent['vao']
        model._shadow_vbo = ent['sha_vbo']
        model._shadow_vao = ent['sha_vao']
        model.n_vertices = ent['nv']

    def _build_bucket_geo(self, key, model):
        """桶级几何 + 实例缓冲 (初容量 64) + VAO (主 pass 6 属性 / shadow 4 实例属性)."""
        packed, pos = self._flatten_mesh(model.mesh, model.normal_mode)
        vbo = self.ctx.buffer(packed.tobytes())
        sha_vbo = self.ctx.buffer(pos.tobytes())
        ent = {'vbo': vbo, 'sha_vbo': sha_vbo, 'nv': pos.shape[0],
               'vao': None, 'sha_vao': None}
        self._bucket_geo[key] = ent
        self._bucket_inst[key] = {'main': None, 'sha': None, 'n': 0}
        self._grow_bucket_inst(key, 64)
        return ent

    def _grow_bucket_inst(self, key, k):
        """桶级实例缓冲生长: main 96B/实例 (world 16 + sat 4 + color 4), sha 64B
        (world 16). 容量变化 → 重建 VAO (VAO 绑定缓冲对象, 换缓冲必须重建).
        组1: stage (CPU 侧 staging) 一并作废, 下帧按新 cap 重建.
        GC 批: gather 缓冲 (inst['gath']) 一并作废 (与 stage 同寿命)."""
        ent = self._bucket_geo[key]
        inst = self._bucket_inst[key]
        if k <= inst['n'] and inst['main'] is not None:
            return
        cap = max(64, int((k + 15) // 16 * 16))
        inst['main'] = self.ctx.buffer(reserve=cap * 96, dynamic=True)
        inst['sha'] = self.ctx.buffer(reserve=cap * 64, dynamic=True)
        inst['n'] = cap
        inst.pop('stage', None)               # 组1: 旧 staging 作废 (容量已变)
        inst.pop('gath', None)                # GC 批: gather 缓冲一并作废 (容量已变)
        self._build_bucket_vaos(ent, inst)

    def _build_bucket_vaos(self, ent, inst):
        """桶 VAO: 顶点 (位置/法线/颜色) + 实例属性 (格式串尾部 /i = 每实例 divisor;
        moderngl 多属性实例=同一格式串依次排布 offset, 尾部单 /i 整串生效)."""
        ent['vao'] = self.ctx.vertex_array(
            self.prog,
            [(ent['vbo'], '3f 3f 4f', 'in_pos', 'in_normal', 'in_color'),
             (inst['main'], '4f 4f 4f 4f 4f 4f/i',
              'a_w0', 'a_w1', 'a_w2', 'a_w3', 'a_sat', 'a_col')])
        # M29: 阴影 pass 专用 VAO —— moderngl VAO 与创建程序绑定, 不能复用主 VAO;
        # 阴影程序只有 in_pos, 用独立 positions-only VBO (紧凑 '3f') + 实例 world.
        ent['sha_vao'] = self.ctx.vertex_array(
            self._shadow_prog,
            [(ent['sha_vbo'], '3f', 'in_pos'),
             (inst['sha'], '4f 4f 4f 4f/i',
              'a_w0', 'a_w1', 'a_w2', 'a_w3')])

    def _release_bucket_resources(self):
        """清场/重建时释放全部桶资源 (共享几何+实例缓冲+VAO)."""
        if getattr(self, '_bucket_geo', None) is None:
            return                    # 测试桩 (__new__ 不跑 __init__) 无桶状态
        for ent in self._bucket_geo.values():
            for name in ('vao', 'sha_vao', 'vbo', 'sha_vbo'):
                r = ent.get(name)
                if r is not None:
                    try:
                        r.release()
                    except Exception:
                        pass
            ent['vao'] = ent['sha_vao'] = None
        for inst in self._bucket_inst.values():
            for name in ('main', 'sha'):
                r = inst.get(name)
                if r is not None:
                    try:
                        r.release()
                    except Exception:
                        pass
            inst['main'] = inst['sha'] = None
            inst.pop('stage', None)           # 组1: staging 一并清
            inst.pop('gath', None)            # GC 批: gather 缓冲一并清 (与 stage 同寿命)
        self._bucket_geo.clear()
        self._bucket_inst.clear()
        self._fw32 = None
        self._render_buckets = []

    def remove_model(self, model):
        """删除单个模型: 释放 GPU 资源、解除父链引用并从列表移除.
        2026-08-16 相机物体化: 先脱掉挂在本物体下的摄像机 (世界不跳)."""
        for cam in list(getattr(model, 'camera_children', [])):
            self.set_camera_parent(cam, None, preserve_world=True)
        if model in self.models:
            # A2 (2026-08-29): 几何/实例缓冲归 mesh 桶共享 (桶内其他物体还在用),
            # 单物体删除只解除引用; 共享资源由 _release_bucket_resources 统一释放
            # (清场景时). undo.attach_model 依据 vbo is None 重挂会重新解析桶.
            model.vbo = None
            model.vao = None
            model._shadow_vao = None
            model._shadow_vbo = None
            self.models.remove(model)
            self._bump_struct()                # 组3: 结构变更失效 (ancestry+SoA)
        # M23: 材质若不再被任何物体引用 -> 从材质库移除 (避免孤儿堆积)
        mat = model.renderer.material
        if mat is not None and mat in self.materials:
            if not any(other is not model and other.renderer.material is mat
                       for other in self.models):
                self.materials.remove(mat)
        if model.parent is not None:
            if model in model.parent.children:
                model.parent.children.remove(model)
            model.parent = None
        if self.current_model_index >= len(self.models):
            self.current_model_index = max(0, len(self.models) - 1)

    def remove_subtree(self, root):
        """删除 root 及其全部子孙 (M14: 删除物体/撤销 redo 用).
        2026-08-16 相机物体化: 先脱掉整棵子树上挂的摄像机 (父链完整, 世界不跳),
        再逐个删节点."""
        sub = list(self.collect_subtree(root))
        for m in sub:
            for cam in list(getattr(m, 'camera_children', [])):
                self.set_camera_parent(cam, None, preserve_world=True)
        for m in sub:
            self.remove_model(m)

    def clear_scene(self):
        """清空全部模型 (M16: 新建/加载场景用)"""
        for m in list(self.models):
            self.remove_model(m)
        self.models.clear()
        self._bump_struct()                    # 组3: 结构变更失效 (ancestry+SoA)
        self.materials.clear()               # M23: 材质库随场景一起清空
        bb = getattr(self, '_bb_cache', None)
        if bb is not None:
            bb.clear()                       # 网格顶点缓存随场景清空
        self._release_bucket_resources()     # A2: 桶共享几何/实例缓冲统一释放
        self.current_model_index = 0

    def load_scene(self, path):
        """M37/M38: 运行时切换到另一个场景文件 (Unity SceneManager.LoadScene 式).
        清空当前场景 + 加载新场景 (物体/光源/摄像机/材质). 支持明文 JSON 与
        混淆场景 (LOOMSC1, 自动解密). 返回是否成功.
        供脚本/菜单运行时换关卡 (菜单场景 -> 游戏场景)."""
        import sceneio as _sio
        data = _sio.load_scene_data(path)
        if not isinstance(data, dict):
            return False
        self.clear_scene()
        self.lights.clear()
        self.cameras.clear()
        self.active_camera = None
        _sio.scene_from_dict(self, data)
        return True

    # ================ 光源管理 (M21: 场景光源实体; M29 阴影) ================
    def add_light(self, kind='directional', position=None, direction=None,
                  color=(1.0, 1.0, 1.0), intensity=1.0, name=None, guid=None,
                  mode='full', shape='circle', size=5.0, shadow=True,
                  azimuth=None, elevation=None, roll=None):
        """添加场景光源 (不可见实体, 不渲染网格/不参与拾取). 返回 LightState.
        M29: mode='full'|'beam', shape='circle'|'rect', size=截面尺寸, shadow=是否投射阴影.
        M30: 平行光方向用 azimuth/elevation/roll (度); 旧 direction 向量仍兼容 (自动反算)."""
        light = LightState(kind=kind, position=position, direction=direction,
                           color=color, intensity=intensity, name=name, guid=guid,
                           mode=mode, shape=shape, size=size, shadow=shadow,
                           azimuth=azimuth, elevation=elevation, roll=roll)
        self.lights.append(light)
        return light

    def remove_light(self, light):
        """从场景移除光源 (释放其阴影贴图)"""
        sm = self._shadow_maps.pop(light.guid, None)
        if sm is not None:
            self._release_shadow_map(sm)
        if light in self.lights:
            self.lights.remove(light)

    # ================ 摄像机管理 (多摄像机, Unity Camera 概念) ================
    def add_camera(self, position=None, yaw=0.0, pitch=0.0, roll=0.0, fov=45.0,
                   fov_locked=True, name=None, guid=None,
                   pitch_lock=False, pitch_min=-85.0, pitch_max=85.0):
        """添加场景摄像机实体 (不可见实体, 不渲染网格/不参与拾取). 返回 CameraState.
        M41: 朝向度制 (yaw [0,360) / pitch、roll 环绕) + 俯仰角限制字段."""
        cam = CameraState(position=position, yaw=yaw, pitch=pitch, roll=roll,
                          fov=fov, fov_locked=fov_locked, name=name, guid=guid,
                          pitch_lock=pitch_lock, pitch_min=pitch_min,
                          pitch_max=pitch_max)
        self.cameras.append(cam)
        return cam

    def remove_camera(self, cam):
        """从场景移除摄像机 (先脱父, 同时清 active 指向). 相机物体化 2026-08-16."""
        if cam.parent is not None:
            if cam in cam.parent.camera_children:
                cam.parent.camera_children.remove(cam)
            cam.parent = None
            self._bump_struct()                # 组3: 父链变更失效 (ancestry+SoA)
        if cam in self.cameras:
            self.cameras.remove(cam)
        if self.active_camera == cam.guid:
            self.active_camera = None

    def find_camera(self, guid):
        """按 guid 找摄像机, 找不到返回 None."""
        for cam in self.cameras:
            if cam.guid == guid:
                return cam
        return None

    def find_model_by_guid(self, guid):
        """按 guid 找普通物体 (GameObject), 找不到返回 None. 相机挂父/撤销解析用."""
        for m in self.models:
            if m.guid == guid:
                return m
        return None

    def active_camera_object(self):
        """返回当前玩家视角摄像机对象 (无则 None)."""
        return self.find_camera(self.active_camera) if self.active_camera else None

    def apply_camera(self, cam):
        """把某摄像机设为玩家视角: 世界位置=摄像机世界位置, 世界朝向=yaw/pitch/roll,
        视角广度=fov, 并关闭轨道相机 (自由相机语义). 返回是否成功.
        M41: CameraState 度制 -> 引擎内部弧度 (camera_yaw/pitch/roll).
        2026-08-16 相机物体化: 无父相机走原路径精确赋值 (零漂移, 后向兼容);
        挂父相机合成世界基再反解世界 yaw/pitch/roll (Unity 父子语义)."""
        if cam is None:
            return False
        self.camera = self.camera_world_position(cam)
        if cam.parent is None:
            self.camera_yaw = math.radians(cam.yaw)
            self.camera_pitch = math.radians(cam.pitch)
            self.camera_roll = math.radians(cam.roll)
        else:
            ex, ey, ez = self.camera_world_basis(cam)
            self.camera_yaw, self.camera_pitch, self.camera_roll = \
                view_basis_to_angles(ex, ey, ez)
        self._fov = math.radians(cam.fov)
        self.orbit_mode = False
        return True

    # ---- 相机物体化: 世界位姿由父链合成 (2026-08-16) ----
    def camera_world_position(self, cam):
        """摄像机世界位置 (父链合成, 与 world_position 同构): 局部 @ 父世界矩阵."""
        p = np.array([cam.position.x, cam.position.y, cam.position.z, 1.0])
        if cam.parent is not None:
            p = p @ self.model_world_matrix(cam.parent)
        return Point3D(float(p[0]), float(p[1]), float(p[2]))

    def camera_world_basis(self, cam):
        """摄像机世界正交基 (ex,ey,ez) 行向量 (R=[ex;ey;ez] = 世界→视图旋转).
        按 mat4_view_yaw_pitch 同 trig/负绕向由 cam.yaw/pitch/roll (度) 建局部基,
        再沿父链合成世界旋转 (world_rotation_matrix 纯旋转 -> 基保持单位正交)."""
        yaw, pitch, roll = math.radians(cam.yaw), math.radians(cam.pitch), math.radians(cam.roll)
        cy, sy = math.cos(yaw), math.sin(yaw)
        cp, sp = math.cos(pitch), math.sin(pitch)
        ex = (cy, 0.0, -sy)
        ey = (-sy * sp, cp, -cy * sp)
        ez = (sy * cp, sp, cy * cp)
        if roll:
            cr, sr = math.cos(roll), math.sin(roll)
            sn = -sr
            exn = (ex[0] * cr + ey[0] * sn, ex[1] * cr + ey[1] * sn,
                   ex[2] * cr + ey[2] * sn)
            eyn = (ey[0] * cr - ex[0] * sn, ey[1] * cr - ex[1] * sn,
                   ey[2] * cr - ex[2] * sn)
            ex, ey = exn, eyn
        if cam.parent is None:
            return ex, ey, ez
        R3 = np.asarray(self.world_rotation_matrix(cam.parent))[:3, :3]
        return (tuple(float(v) for v in np.array(ex) @ R3),
                tuple(float(v) for v in np.array(ey) @ R3),
                tuple(float(v) for v in np.array(ez) @ R3))

    def set_camera_parent(self, cam, new_parent, preserve_world=True):
        """把摄像机挂到 new_parent (GameObject) 下 (None=根). 只可挂 GameObject,
        CameraState 无缩放. preserve_world=True (默认, Unity 语义): 换父后局部
        位置/朝向按新父空间重算, 世界位置/朝向不变. 维护 cam.parent 与
        parent.camera_children. 相机物体化 2026-08-16.
        (命名 set_camera_parent 避开编辑器 controller 的 reparent_camera(cam,target),
        引擎内部/撤销命令都走本方法.)"""
        if cam.parent is new_parent:
            return
        if new_parent is not None:
            # 摄像机不是 GameObject 不能当父, 防环防御走链 (正常永不触发)
            cur = new_parent
            while cur is not None:
                if cur is cam:
                    return
                cur = cur.parent
        if preserve_world:
            wp = self.camera_world_position(cam)
            ex, ey, ez = self.camera_world_basis(cam)
            Mw = np.array([ex, ey, ez], dtype=np.float64)                 # 世界基 (行)
            Rp = (np.asarray(self.world_rotation_matrix(new_parent))[:3, :3]
                  if new_parent is not None else np.eye(3))
            Ml = Mw @ np.linalg.inv(Rp)                                   # 新父空间局部基
            yaw, pitch, roll = view_basis_to_angles(Ml[0], Ml[1], Ml[2])
            if new_parent is not None:
                loc = np.array([wp[0], wp[1], wp[2], 1.0]) @ \
                      np.linalg.inv(self.model_world_matrix(new_parent))
                cam.position = Point3D(float(loc[0] / loc[3]),
                                       float(loc[1] / loc[3]),
                                       float(loc[2] / loc[3]))
            else:
                cam.position = Point3D(*wp)                               # 脱父: 局部=世界
            cam.yaw = wrap_deg(math.degrees(yaw), 0.0, 360.0)
            cam.pitch = wrap_deg(math.degrees(pitch), -180.0, 180.0)
            cam.roll = wrap_deg(math.degrees(roll), -180.0, 180.0)
        # 换父 (camera_children 列表维护)
        if cam.parent is not None and cam in cam.parent.camera_children:
            cam.parent.camera_children.remove(cam)
        cam.parent = new_parent
        if new_parent is not None:
            new_parent.camera_children.append(cam)

    def player_pitch_limits(self):
        """玩家俯仰角限制 (弧度): 返回 (min_rad, max_rad); 若没有激活相机或未启用
        俯仰角限制则返回 None. 供玩家控制脚本 (first_person/third_person) 夹俯仰角.
        可调范围 = [pitch_min, pitch_max] 含两端 (M41)."""
        cam = self.active_camera_object()
        if cam is None or not cam.pitch_lock:
            return None
        return (math.radians(cam.pitch_min), math.radians(cam.pitch_max))

    def _upload_lights(self):
        """把场景光源写到着色器 uniform 数组 + 绑定阴影贴图 (render 每帧调用).
        M29: 附加 mode/shape/ortho/shadow_slot; 阴影贴图从纹理单元 1 起绑定
        (单元 0 留给文字/HUD). u_ambient_scale: 无光源时压暗环境光.
        多核优化 (2026-08-14): 缓冲惰性建一次, 每帧原地清零复用, 消除每帧 ~9 次
        numpy 数组分配 (GC/CPU 开销)."""
        n = min(len(self.lights), 8)
        self.prog['u_light_count'].value = n
        b = getattr(self, '_light_bufs', None)
        if b is None:
            b = self._light_bufs = {
                'dirs': np.zeros((8, 3), dtype='f4'),
                'poss': np.zeros((8, 3), dtype='f4'),
                'cols': np.zeros((8, 3), dtype='f4'),
                'ints': np.zeros(8, dtype='f4'),
                'kinds': np.zeros(8, dtype='f4'),
                'modes': np.zeros(8, dtype='f4'),   # M29: 平行光 0=full 1=beam
                'shapes': np.zeros(8, dtype='f4'),  # M29: beam 0=circle 1=rect
                'orthos': np.zeros((8, 16), dtype='f4'),  # M29: 平行光 view-proj
                'slots': np.full(8, -1, dtype='i4'),      # M29: 阴影数组下标
                'sampler_units': [0] * 16,
            }
        # 每帧原地清零 (复用缓冲)
        b['dirs'][:] = 0
        b['poss'][:] = 0
        b['cols'][:] = 0
        b['ints'][:] = 0
        b['kinds'][:] = 0
        b['modes'][:] = 0
        b['shapes'][:] = 0
        b['orthos'][:] = 0
        b['slots'][:] = -1
        # 孤儿阴影贴图清理 (光源被删)
        for guid in list(self._shadow_maps):
            if not any(getattr(l, 'guid', None) == guid for l in self.lights):
                self._release_shadow_map(self._shadow_maps.pop(guid))
        unit = 1                                # 阴影贴图从单元 1 起 (0 留给文字)
        sampler_units = b['sampler_units']      # 全 16 个 sampler 元素一次设
        sampler_units[:] = [0] * 16
        for i, light in enumerate(self.lights[:8]):
            b['dirs'][i] = (light.direction.x, light.direction.y, light.direction.z)
            b['poss'][i] = (light.position.x, light.position.y, light.position.z)
            b['cols'][i] = (light.color[0], light.color[1], light.color[2])
            b['ints'][i] = light.intensity
            b['kinds'][i] = 1.0 if light.kind == 'point' else 0.0
            b['modes'][i] = 1.0 if light.mode == 'beam' else 0.0
            b['shapes'][i] = 1.0 if light.shape == 'rect' else 0.0
            if light.kind == 'directional':
                # 2026-08-15: 复用 _compute_light_vps 的当帧缓存 (避免重复算场景包围盒)
                vp = (self._light_vps or {}).get(light.guid)
                if vp is None:
                    vp = self._dir_light_vp(light)
                if vp is not None:
                    b['orthos'][i] = np.asarray(vp, dtype='f4').ravel()
            # 阴影贴图槽位: 平行光 1 张 / 点光 6 面, 平铺进 u_shadow_maps
            if light.shadow:
                sm = self._shadow_maps.get(light.guid)
                need = 6 if light.kind == 'point' else 1
                if sm is not None and unit + need - 1 <= 15:
                    b['slots'][i] = unit - 1     # 数组下标 = 物理单元号 - 1
                    for k, tex in enumerate(sm['tex']):
                        tex.use(unit + k)
                        sampler_units[unit - 1 + k] = unit + k
                    unit += need
        self.prog['u_light_dir'].write(np.ascontiguousarray(b['dirs']).tobytes())
        self.prog['u_light_pos'].write(np.ascontiguousarray(b['poss']).tobytes())
        self.prog['u_light_color'].write(np.ascontiguousarray(b['cols']).tobytes())
        self.prog['u_light_intensity'].write(np.ascontiguousarray(b['ints']).tobytes())
        self.prog['u_light_kind'].write(np.ascontiguousarray(b['kinds']).tobytes())
        self.prog['u_light_mode'].write(np.ascontiguousarray(b['modes']).tobytes())
        self.prog['u_light_shape'].write(np.ascontiguousarray(b['shapes']).tobytes())
        self.prog['u_light_ortho'].write(np.ascontiguousarray(b['orthos']).tobytes())
        self.prog['u_shadow_maps'].value = tuple(sampler_units)
        self.prog['u_shadow_slot'].value = tuple(int(x) for x in b['slots'])  # int 数组用 tuple
        self.prog['u_shadow_res'].value = self._shadow_res
        self.prog['u_shadow_point_res'].value = self._shadow_point_res
        self.prog['u_shadow_bias'].value = 0.002
        self.prog['u_shadow_point_bias'].value = 0.004
        self.prog['u_light_far'].value = self._shadow_point_far
        self.prog['u_ambient_scale'].value = 1.0 if n > 0 else 0.2

    # ================ M29 阴影贴图 (深度 pass) ================
    def _release_shadow_map(self, sm):
        try:
            for f in sm.get('fbo', []):
                f.release()
            for t in sm.get('tex', []):
                t.release()
        except Exception:
            pass

    def _ensure_shadow_map(self, light):
        """取/建光源阴影贴图: 平行光=1 张 2D depth; 点光=6 张 2D depth (面)."""
        sm = self._shadow_maps.get(light.guid)
        if sm is not None:
            return sm
        if light.kind == 'directional':
            tex = self.ctx.depth_texture((self._shadow_res, self._shadow_res))
            # 阴影采样: 存真实深度 + pcf_shadow 传 ref=depth-bias
            # (此驱动实测固定 stored>=ref=照亮, 忽略 compare_func; 反转深度方案已废弃)
            sm = {'type': 'dir', 'tex': [tex],
                  'fbo': [self.ctx.framebuffer(depth_attachment=tex)]}
        else:
            res = self._shadow_point_res
            texs = [self.ctx.depth_texture((res, res)) for _ in range(6)]
            sm = {'type': 'point', 'tex': texs,
                  'fbo': [self.ctx.framebuffer(depth_attachment=t) for t in texs]}
        self._shadow_maps[light.guid] = sm
        return sm

    def _scene_light_bounds(self, view):
        """场景全部可见物体世界 AABB 8 角变换到 view 空间, 返回 x/y/z 的 (min, max).
        (串行回退版: 无预计算池时用; 有池走 _model_aabbs_par + _scene_light_bounds_par.)"""
        aabbs = self._model_aabbs_par(self.models, self._frame_world)
        # getattr 防御: 测试桩 (__new__ 无 __init__) 无 _stage_times (test_parallel 抓过)
        return self._scene_light_bounds_par(
            view, aabbs, times=getattr(self, '_stage_times', None))

    def _model_aabbs_par(self, models, fw=None, visible_only=True):
        """模型世界 AABB (用当帧矩阵), 与 models 下标对齐 (visible_only=False 全量对齐).
        2026-08-15 8 核均摊: 逐模型 get_bounding_box 是 numpy 重活 (高面数球体 = 几万顶点
        批量变换), 池上分块 -> 释放 GIL 真并行; 结果按序拼接, 与逐模型串行逐位一致.
        visible_only=False: 返回全部模型 (含不可见, 下标与 models 对齐) —— 阴影与碰撞
        共享一次包围盒计算用 (阴影再过滤可见).
        组3层3 (2026-08-31): 逐模型 Python 循环改批量化 _aabbs_batched —— 按顶点数
        分组堆叠, 每组一次批量归约 (消每模型 3 次 numpy 调用开销); 每模型仍是同参数
        matmul (k=4 求和序不变) + min/max 纯比较 -> 与逐模型串行逐位一致 (对拍
        aabb_par_check.py). 池路径 (n>=阈值) 分块内同款批量化.
        ★spin 治理 (2026-08-31): 池分块路径同样受益 —— 分块内 _aabbs_batched 默认走
        串行 njit, 不再触碰 numba prange 线程池 (帧路径零 spin).
        LOOM_PROFILE: 阶段名 'aabbs' (shadow_prep 内部大头, 单独观测)."""
        n = len(models)
        if n == 0:
            return []
        _p = os.environ.get('LOOM_PROFILE') == '1'
        if _p:
            t0 = time.time()
        fw = fw if fw is not None else getattr(self, '_frame_world', None)
        pool = getattr(self, '_frame_pool', None)
        if pool is not None and n >= self._AABB_POOL_THRESHOLD:
            def _chunk(idx_iter):
                idxs = list(idx_iter)
                return self._aabbs_batched([models[i] for i in idxs],
                                           [fw[i] for i in idxs] if fw is not None else None,
                                           visible_only)
            out = pool.map_indexed(n, _chunk, batches_per_thread=2)
        else:
            out = self._aabbs_batched(models, fw, visible_only)
        if _p:
            self._stage_times['aabbs'] = self._stage_times.get('aabbs', 0.0) \
                + (time.time() - t0) * 1000.0
        return out

    def _aabbs_batched(self, models, fw, visible_only=True):
        """批量化 AABB (组3层3): 逐模型 vh 复用 _homogeneous_vertices 缓存, 按顶点数
        V 分组, fastpath.aabbs_minmax 逐组一次算全组 min/max —— 每顶点 9乘6加标量
        循环, BLAS 调用/大缓冲/transpose 全消. 数值 = D6 标准 "逐位/1e-7 内" (vs
        numpy dgemm ~4 ULP 舍入差, 实测 8.9e-16, 见 aabb_par_check.py 对拍).
        M 缺失/罕见形态兜底走 get_bounding_box 旧路径 (行为不变). 顺序 = models
        过滤 visible 后的原序 (旧语义). 纯 Python 降级同算法.
        ★spin 治理 (2026-08-31): 默认 aabbs_minmax **串行** njit (nogil, 不碰
        numba 线程池 —— 消 18 worker 帧间 busy-wait 空烧); 仅单组模型数 >=
        _AABB_PAR_MIN_MODELS 才切 prange 并行版 aabbs_minmax_par (工作量摊得开
        spin 税的大规模逃生门). 两版同算法逐位同源.
        组1+ 堆叠缓冲复用: vhN/m3N/mn/mx 堆叠分配按 (n,V) 键缓存
        (thread-local —— 阴影/碰撞池 worker 线程都会进本方法, 免锁), 尺寸
        匹配即原地复用, 消每帧 4 次 np.empty 大分配 (51球 V=2035 ≈ 3.3MB/帧)."""
        sel = []
        for k, m in enumerate(models):
            M = fw[k] if fw is not None and k < len(fw) else None
            if visible_only and not getattr(m, 'visible', True):
                continue
            sel.append((m, M))
        if not sel:
            return []
        out = [None] * len(sel)
        groups = {}                       # V -> [(sel序号, vh, M3)]
        for k, (m, M) in enumerate(sel):
            if M is None:
                out[k] = self.get_bounding_box(m, None)   # 旧路径兜底 (fw 不全罕见)
                continue
            vh = self._homogeneous_vertices(m.mesh)
            if vh.shape[1] != 4 or M.shape != (4, 4):
                # 罕见形态防御: 退回单模型旧路径 (行为不变)
                out[k] = self.get_bounding_box(m, M)
                continue
            groups.setdefault(vh.shape[0], []).append((k, vh, M[:, :3]))
        # thread-local 堆叠缓冲缓存 (键=(组序号, n, V); 线程局部免锁,
        # 主线程/池 worker 各持一份, 生命周期 = 引擎实例)
        tlc = getattr(self, '_aabb_staging', None)
        if tlc is None:
            tlc = self._aabb_staging = threading.local()
        buf_cache = getattr(tlc, 'bufs', None)
        if buf_cache is None:
            buf_cache = tlc.bufs = {}
        for gi, lst in enumerate(groups.values()):
            n = len(lst)
            V = lst[0][1].shape[0]
            ent = buf_cache.get((gi, n, V))
            if ent is None:
                # 分配 (首次/换组形态): vhN (n,V,4)+m3N (n,4,3)+mn/mx (n,3)
                vhN = np.empty((n, V, 4), dtype=np.float64)
                m3N = np.empty((n, 4, 3), dtype=np.float64)
                mn = np.empty((n, 3), dtype=np.float64)
                mx = np.empty((n, 3), dtype=np.float64)
                buf_cache[(gi, n, V)] = (vhN, m3N, mn, mx)
            else:
                vhN, m3N, mn, mx = ent
            for r in range(n):
                vhN[r] = lst[r][1]
                m3N[r] = lst[r][2]
            if n >= self._AABB_PAR_MIN_MODELS:
                fastpath.aabbs_minmax_par(vhN, m3N, mn, mx)   # 逃生门: 大规模 prange
            else:
                fastpath.aabbs_minmax(vhN, m3N, mn, mx)       # 默认串行 njit (无 spin)
            for r in range(n):
                out[lst[r][0]] = (Point3D(float(mn[r, 0]), float(mn[r, 1]), float(mn[r, 2])),
                                  Point3D(float(mx[r, 0]), float(mx[r, 1]), float(mx[r, 2])))
        return out

    @staticmethod
    def _scene_light_bounds_par(view, aabbs, times=None):
        """把已算好的模型 AABB 列表 8 角变换到 view 空间, 返回 numpy (min, max) 或 None.
        向量化: 所有模型全部角点拼一个大 (n*8, 4) 批量一次 matmul + min/max (释放 GIL).
        times: 可选 _stage_times dict (staticmethod 无 self, 由调用方传入; 组8 细拆用)."""
        if not aabbs:
            return None
        n = len(aabbs)
        _pr = os.environ.get('LOOM_PROFILE') == '1'
        _t0 = time.time() if _pr else None
        corners = np.empty((n * 8, 4), dtype=np.float64)
        for i, (a, b) in enumerate(aabbs):
            base = i * 8
            c = corners[base:base + 8]
            c[0] = (a.x, a.y, a.z, 1.0); c[1] = (b.x, a.y, a.z, 1.0)
            c[2] = (a.x, b.y, a.z, 1.0); c[3] = (b.x, b.y, a.z, 1.0)
            c[4] = (a.x, a.y, b.z, 1.0); c[5] = (b.x, a.y, b.z, 1.0)
            c[6] = (a.x, b.y, b.z, 1.0); c[7] = (b.x, b.y, b.z, 1.0)
        if _pr and times is not None:
            # 组8 细拆针 1: 角点填充 (纯 Python 4008 行循环嫌疑)
            times['shadow_cornerfill'] = \
                times.get('shadow_cornerfill', 0.0) + (time.time() - _t0) * 1000.0
            _t0 = time.time()
        w = corners @ view
        mn = w[:, :3].min(axis=0)
        mx = w[:, :3].max(axis=0)
        if _pr and times is not None:
            # 组8 细拆针 2: matmul+minmax (numpy 批量, 应为 µs 级)
            times['shadow_matmul'] = \
                times.get('shadow_matmul', 0.0) + (time.time() - _t0) * 1000.0
        return (mn, mx)

    def _dir_light_vp(self, light, aabbs=None):
        """平行光 view-proj (正交): +z_view = 光行进方向, eye = 光源位置.
        full: 正交 XY 覆盖场景 bbox; beam: 正交 XY = 截面 [-size,size]^2, near=0 (射线起点).
        aabbs: 可选预计算 AABB 列表 (避免每帧重复算高面数模型的包围盒)."""
        D = (light.direction.x, light.direction.y, light.direction.z)
        ln = math.sqrt(D[0] * D[0] + D[1] * D[1] + D[2] * D[2])
        if ln < 1e-6:
            return None
        D = (D[0] / ln, D[1] / ln, D[2] / ln)
        eye = (light.position.x, light.position.y, light.position.z)
        up = (light.up_vector().x, light.up_vector().y, light.up_vector().z)  # M30: roll 倾斜
        view = mat4_view_forward(np, eye, D, up)
        if aabbs is None:
            aabbs = self._model_aabbs_par(self.models, self._frame_world)
        bounds = self._scene_light_bounds_par(
            view, aabbs, times=getattr(self, '_stage_times', None))
        if bounds is None:
            return None
        mn, mx = bounds
        if light.mode == 'beam':
            s = max(light.size, 0.01)
            left, right = -s, s
            bottom, top = -s, s
            near, far = 0.0, max(float(mx[2]) + 2.0, 1.0)
        else:
            pad = 1.5
            left, right = float(mn[0]) - pad, float(mx[0]) + pad
            bottom, top = float(mn[1]) - pad, float(mx[1]) + pad
            near, far = min(0.0, float(mn[2]) - 2.0), max(float(mx[2]) + 2.0, 1.0)
        return view @ mat4_ortho(np, left, right, bottom, top, near, far)

    def _parallel_shadow_and_collision(self, dt, with_events=True):
        """2026-08-15 8 核均摊: 阴影 VP (只读) 与 碰撞检测 (只读) 是两个互不依赖的
        numpy 重活, 池上**并行重叠** (Unity"独立任务并行"); 碰撞事件派发 (改脚本状态)
        回主线程串行. 小场景 / 无池 / 编辑模式 (with_events=False) 走原串行路径.
        2026-08-15 再优化: **阴影与碰撞共享一次全量 AABB 计算** (原来各算一遍, 50 高面数
        球曾 ~7ms 重复); 共享的 aabbs 由 _model_aabbs_par(visible_only=False) 一次算好,
        阴影过滤可见 / 碰撞直接从 AABB 派生碰撞体数据."""
        pool = self._frame_pool
        models = self.models
        n = len(models)
        need_collision = with_events and pool is not None \
            and n >= self._COLLISION_PAR_THRESHOLD
        need_shadow = any(l.kind == 'directional' and l.shadow and l.mode == 'full'
                          for l in self.lights[:8])
        if (need_collision or need_shadow) and pool is not None and n >= 2:
            # 全量 AABB 一次算好 (池上分块并行), 阴影与碰撞共享
            aabbs = self._model_aabbs_par(models, self._frame_world, visible_only=False)
            if need_collision:
                def _shadow():
                    # 2026-09-01 组8 插桩: shadow_bounds 子阶段 (光源 VP + 角点
                    # 包围盒; worker 线程内计时, _stage_times 累计式线程安全)
                    self._profile('shadow_bounds', lambda: self._compute_light_vps(aabbs))
                def _collide():
                    # 2026-09-01 组8 插桩: collide_pairs 子阶段 (候选对生成+判定)
                    return self._profile(
                        'collide_pairs',
                        lambda: self._collision_pairs_parallel(aabbs=aabbs))
                _t = time.time()
                _r = pool.run_parallel([_shadow, _collide])
                # shadow_jobs = 双任务墙钟; 池同步税 = shadow_jobs - max(两任务)
                self._stage_times.setdefault('shadow_jobs', 0.0)
                if os.environ.get('LOOM_PROFILE') == '1':
                    self._stage_times['shadow_jobs'] += (time.time() - _t) * 1000.0
                self._profile('dispatch', lambda: self._dispatch_collision_events(_r[1]))
            else:
                self._compute_light_vps(aabbs)
        else:
            if with_events:
                self._profile('dispatch', lambda: self._update_collision_events(dt))
            self._compute_light_vps()

    def _compute_light_vps(self, aabbs=None):
        """每帧一次: 全部阴影光源的 view-proj (平行光含场景包围, 点光 6 面), 缓存到
        self._light_vps = {guid: vp 或 [vp...]}. shadow pass 与 _upload_lights 都复用,
        消除旧代码"每帧对同一光源算两遍包围盒"的重复开销 (2026-08-15 8 核均摊).
        aabbs: 可选**全量对齐** AABB 列表 (阴影与碰撞共享的那份); 阴影只取可见物体的."""
        vps = {}
        if self.lights:
            # 需要场景 AABB 的只有"阴影+全场景"平行光; 共享时用传入的全量列表并过滤可见
            need_bounds = any(l.kind == 'directional' and l.shadow and l.mode == 'full'
                              for l in self.lights[:8])
            if need_bounds:
                if aabbs is None:
                    aabbs = self._model_aabbs_par(self.models, self._frame_world)
                vis_aabbs = [aabbs[i] for i, m in enumerate(self.models) if m.visible]
            else:
                vis_aabbs = None
            for light in self.lights[:8]:
                if not light.shadow:
                    continue
                if light.kind == 'directional':
                    vp = self._dir_light_vp(light, vis_aabbs)
                    if vp is not None:
                        vps[light.guid] = vp
                else:
                    vps[light.guid] = self._point_light_vp(light)
        self._light_vps = vps
        return vps

    def _point_light_vp(self, light):
        """点光源 6 面 view-proj (90° 透视). 面朝向与 _FRAG_SRC point_shadow 完全对应:
        +X,-X,+Y,-Y,+Z,-Z; ±X/±Z 面 up=(0,1,0), ±Y 面 up=(0,0,1)."""
        pos = (light.position.x, light.position.y, light.position.z)
        proj = mat4_perspective(np, math.radians(90.0), 1.0, 0.05, self._shadow_point_far)
        axes = [(1, 0, 0), (-1, 0, 0), (0, 1, 0), (0, -1, 0), (0, 0, 1), (0, 0, -1)]
        ups = [(0, 1, 0), (0, 1, 0), (0, 0, 1), (0, 0, 1), (0, 1, 0), (0, 1, 0)]
        return [mat4_view_forward(np, pos, a, u) @ proj for a, u in zip(axes, ups)]

    def _render_shadow_maps(self):
        """先画完全部阴影贴图 (深度 pass), 主 pass 再采样. 每帧重渲 (光源/物体可动).
        复用模型 m.vao (in_pos 槽位与 _SHADOW_VERT 一致), 关闭背面剔除 (防背面漏光/acne)."""
        if not self.lights:
            return
        self.ctx.enable(moderngl.DEPTH_TEST)
        self.ctx.disable(moderngl.CULL_FACE)
        vps = self._light_vps or {}
        for i, light in enumerate(self.lights[:8]):
            if not light.shadow:
                continue
            if light.kind == 'directional':
                vp = vps.get(light.guid)
                if vp is None:
                    vp = self._dir_light_vp(light)      # 兜底: 无缓存时现算
                if vp is None:
                    continue
                sm = self._ensure_shadow_map(light)
                self._shadow_prog['u_depth_kind'].value = 0
                self._render_to_shadow_map(sm, [vp])
            else:
                sm = self._ensure_shadow_map(light)
                self._shadow_prog['u_depth_kind'].value = 1
                self._shadow_prog['u_light_pos'].value = (
                    light.position.x, light.position.y, light.position.z)
                self._shadow_prog['u_light_far'].value = self._shadow_point_far
                lv = vps.get(light.guid)
                vps6 = lv if lv is not None else self._point_light_vp(light)
                self._render_to_shadow_map(sm, vps6)

    def _render_to_shadow_map(self, sm, vp_list):
        """把一个光源的所有可见模型实例化渲染进它的各面 (A2: 每面清深度后逐桶
        draw; 桶实例 world 矩阵已在 _prepare_bucket_frame 写入桶级缓冲, 每面只换
        u_light_vp uniform —— 旧版逐模型 u_model 上传+draw 已取消)."""
        for fbo, vp in zip(sm['fbo'], vp_list):
            fbo.clear(depth=1.0)
            fbo.use()
            self._shadow_prog['u_light_vp'].write(
                np.ascontiguousarray(vp, dtype='f4').tobytes())
            for key, idxs in self._render_buckets:
                ent = self._bucket_geo.get(key)
                if ent is None or ent['sha_vao'] is None:
                    continue
                ent['sha_vao'].render(moderngl.TRIANGLES, instances=len(idxs))

    def _build_hud_quad(self):
        """单位 quad (2 三角形), HUD 文字纹理 + M33 运行时 UI 纯色矩形用"""
        quad = np.array([0, 0, 0, 0,  1, 0, 1, 0,  1, 1, 1, 1,
                         0, 0, 0, 0,  1, 1, 1, 1,  0, 1, 0, 1], dtype='f4')
        self._quad_vbo = self.ctx.buffer(quad.tobytes())
        self._quad_vao = self.ctx.vertex_array(
            self.hud_prog, [(self._quad_vbo, '2f 2f', 'in_pos', 'in_uv')])
        # 1x1 白色纹理: draw_screen_rect 用它 + u_color 画纯色矩形
        import numpy as _np
        self._hud_white_tex = self.ctx.texture(
            (1, 1), 4, _np.array([255, 255, 255, 255], dtype='u1').tobytes())
        self._hud_white_tex.filter = (moderngl.NEAREST, moderngl.NEAREST)

    def draw_lines(self, verts, colors, mode=moderngl.LINES, view_proj=None):
        """
        渲染世界空间折线 (逐顶点颜色). verts: (N,3), colors: (N,3) 或 (N,4) 0..1.
        用独立 line 着色器 (不光照, 不深度).
        D10 (2026-08-30) 缓冲复用: VBO/VAO 持久缓存 (容量按需生长重建), 每帧
        6+ 次调用 (gizmo/图标/选中框) 不再逐次建+毁 GL 对象 (旧实现每次
        ctx.buffer+vertex_array+双 release 的 GL churn); 字节布局/着色器/渲染
        语义逐位不变 ('3f 4f' 交错, 同 program, 同 uniform, render vertices=N).
        """
        if mode == moderngl.LINES:
            # 2026-08-18 关键修复: Qt 外部模式下 moderngl scope 的 C 层会把
            # GL_LINE_WIDTH 破坏为 0 (pygame 模式正常) -> scope 内 LINES 线宽 0
            # 光栅化失败, 网格/选中框等一切线全部不可见 (空场景黑屏 + 网格闪烁根因).
            # 每次画线前显式重设线宽, 与 scope 内外无关; pygame 模式无副作用.
            try:
                self.ctx.line_width = 2.0
            except Exception:
                pass
        # 2026-08-18: 外部模式绘制前绑定缓存 widget FBO (scope 退出会把绑定
        # 破坏成 0, 无 scope 的调用直接画会画到 0 不可见). pygame 模式绑定
        # ctx.screen 无副作用.
        if getattr(self, '_external_ctx', False):
            self._screen_fb().use()
        if not hasattr(self, '_line_prog'):
            self._line_prog = self.ctx.program(vertex_shader=_LINE_VERT,
                                               fragment_shader=_LINE_FRAG)
        vp = view_proj if view_proj is not None else self._vp
        verts = np.asarray(verts, dtype='f4')
        colors = np.asarray(colors, dtype='f4')
        if colors.shape[1] == 3:
            colors = np.concatenate([colors, np.ones((colors.shape[0], 1), dtype='f4')],
                                    axis=1)
        packed = np.ascontiguousarray(
            np.concatenate([verts, colors], axis=1), dtype='f4')     # (N,7)
        # D10: 持久 VBO/VAO (容量生长; 换缓冲必须重建 VAO — moderngl VAO 绑定
        # 缓冲对象). 测试桩无 _line_vbo 属性时惰性建. 余量区旧字节无害:
        # render(vertices=N) 只读前 N 个顶点.
        n_bytes = packed.nbytes
        vbo = getattr(self, '_line_vbo', None)
        if vbo is None or vbo.size < n_bytes:
            if vbo is not None:
                try:
                    vbo.release()
                except Exception:
                    pass
            cap = max(4096, 2 * n_bytes)               # 初量 4KB, 生长 2x
            vbo = self.ctx.buffer(reserve=cap, dynamic=True)
            self._line_vbo = vbo
            self._line_vao = None                      # 换缓冲 -> VAO 必重建
        vbo.write(packed.tobytes())
        vao = getattr(self, '_line_vao', None)
        if vao is None:
            vao = self._line_vao = self.ctx.vertex_array(
                self._line_prog, [(vbo, '3f 4f', 'in_pos', 'in_color')])
        self._line_prog['u_view_proj'].write(np.ascontiguousarray(vp, dtype='f4').tobytes())
        vao.render(mode, vertices=len(packed))

    @staticmethod
    def _primary_font_path():
        """主字体文件: 雅黑 > 黑体 > 雅黑Light; 全缺返回 None (用 pygame 默认字体)"""
        for path in ("C:/Windows/Fonts/msyh.ttc",
                     "C:/Windows/Fonts/simhei.ttf",
                     "C:/Windows/Fonts/msyhl.ttc"):
            if os.path.exists(path):
                return path
        return None

    @staticmethod
    def _load_font(size):
        """主字体 (雅黑, 含中文; 找不到退回默认).
        嵌入式模式 (Qt 宿主) 未 pygame.init: font 模块需单独 init —— 只初始化
        SDL_ttf 栅格化, 不建窗口, 与 IME 污染源 (SDL 窗口) 无关."""
        try:
            pygame.font.init()
        except Exception:
            pass
        path = GLEngine._primary_font_path()
        if path is not None:
            return pygame.font.Font(path, size)
        return pygame.font.Font(None, size)

    # ================ 模型管理 ================
    def select_next_model(self):
        """选择下一个模型 (安全加固 2026-08-20: 空场景不崩)"""
        if not self.models:
            return
        self.current_model_index = (self.current_model_index + 1) % len(self.models)

    def get_current_model(self):
        """获取当前选中的模型 (空场景/索引越界返回 None, 安全加固 2026-08-20)"""
        if not self.models:
            return None
        if self.current_model_index >= len(self.models):
            self.current_model_index = 0
        return self.models[self.current_model_index]

    # ================ 变换层次 (M14) ================
    def model_world_matrix(self, m):
        """物体世界模型矩阵 (行向量): local(S@R@T) @ 父世界矩阵 沿父链合成"""
        M = (mat4_scale(np, m.scale[0], m.scale[1], m.scale[2])
             @ mat4_rotation(np, m.rotation.x, m.rotation.y, m.rotation.z)
             @ mat4_translation(np, m.position.x, m.position.y, m.position.z))
        if m.parent is not None:
            M = M @ self.model_world_matrix(m.parent)
        return M

    def _transform_snapshot(self, models):
        """组3层1 (2026-08-30) SoA 变换平面快照: 一次抓取全部物体 position/rotation/
        scale 成三个 (N,3) float64 平面, 返回 (stamp, pos, rot, scl) ——
        compute_world_matrices 的 9 次"属性链列取"收拢到此, 之后列取走 numpy 切片.

        stamp = (id(models), self._struct_gen, len(models)):
        add_model/attach_model/remove_model/clear_scene/set_parent/remove_camera 及
        GameObject.parent 旁路都经 _bump_struct() 递增 _struct_gen; 列表对象身份
        兜住 undo 直接换 list (engine.models = list(...) 不 bump), 长度兜住裸
        append/del 防御. models 参数即 capture 对象 (生产调用方全传 self.models,
        等价于规约的 id(self.models); 取参数是为测试桩安全 —— __new__ 桩/外来
        列表 (test_parallel.compute_world_matrices(_fake)) 无 self.models).

        语义铁律 —— 快照抓"调用时刻"的属性值, 陈旧读不可能:
        Point3D/tuple 不可变, 全库改值只有"换新对象"一条路 (position/rotation/scale
        setter 一律 Point3D(*v)/tuple(v) 重建; 脚本 scripts.py/物理 _resolve/动画
        update_animations/编辑器 commit 均整体赋新对象). 快照 keys 记录每个物体
        当前 (position, rotation, scale) 三对象的 id, 且把对象本体钉在 _soa_snap
        里 —— 被钉住的对象不被 GC, 其 id 在缓存有效期内不可能被新对象复用
        (CPython id=地址, 仅对象死后可复用). 故 keys 相等 ⟺ 三对象同一 ⟹ 值必然
        相同; 任一改值必换新对象 ⟹ id 变 ⟹ 失效重建. 仅 _struct_gen 不够:
        脚本/物理/动画每帧改值不动结构.

        f64 逐位一致: 平面由 Python float (C double) 经 np.array(dtype=f64) 一次
        转换, 与旧逐列 np.array([...], dtype=f64) 同值同型. 测试桩安全: 全程
        getattr 防御 (_struct_gen/_soa_snap 可不存在)."""
        n = len(models)
        stamp = (id(models), getattr(self, '_struct_gen', 0), n)
        # 单遍抓当前 (position, rotation, scale) 对象三件套 (3 次 property 读/物体;
        # 旧路径 compute_world_matrices 是 9 次深链读/物体)
        cur = tuple((m.position, m.rotation, m.scale) for m in models)
        keys = tuple((id(p), id(r), id(s)) for p, r, s in cur)
        snap = getattr(self, '_soa_snap', None)
        if snap is not None and snap[0] == stamp and snap[1] == keys:
            return snap[0], snap[2], snap[3], snap[4]
        if n:
            pos = np.array([(p.x, p.y, p.z) for p, r, s in cur], dtype=np.float64)
            rot = np.array([(r.x, r.y, r.z) for p, r, s in cur], dtype=np.float64)
            scl = np.array([(s[0], s[1], s[2]) for p, r, s in cur], dtype=np.float64)
        else:
            pos = np.empty((0, 3), dtype=np.float64)
            rot = np.empty((0, 3), dtype=np.float64)
            scl = np.empty((0, 3), dtype=np.float64)
        # cur 一并存 (钉住全部抓取对象, 防 id 复用造成假命中, 见上铁律)
        self._soa_snap = (stamp, keys, pos, rot, scl, cur)
        return stamp, pos, rot, scl

    def compute_world_matrices(self, models):
        """批量算全部模型世界矩阵 (2026-08-14 多核优化).

        一次性 numpy 批量 (局部 S@R@T 全向量化 + 沿父链按层级每层一次批量 matmul),
        与逐模型 model_world_matrix 数值一致. 返回 (N,4,4) float64, 顺序与 models 对齐."""
        n = len(models)
        if n == 0:
            return np.empty((0, 4, 4), dtype=np.float64)
        # 父链索引 + 层级深度 (迭代 DP, 任意顺序稳)
        id2i = {id(m): i for i, m in enumerate(models)}
        parent = np.full(n, -1, dtype=np.int64)
        for i, m in enumerate(models):
            if m.parent is not None:
                parent[i] = id2i.get(id(m.parent), -1)
        # 组3层1: 深度 DP 循环 -> fastpath.depths (Numba可选, 降级纯Python同源;
        # 语义逐位同: 沿 parent 爬根, d<n 防环截断, int() 转换当下标)
        depth = _fp_depths(parent)
        # 局部矩阵批量 (与 mat4_scale/translation 逐元素一致)
        # 组3层1: 9 次属性链列取收拢到 _transform_snapshot() 一次性抓成 SoA 平面
        # (Point3D 不可变+对象 id 失效, 快照即调用时刻值; f64 逐位同旧列取).
        _, pos, rot, scl = self._transform_snapshot(models)
        S = np.zeros((n, 4, 4), dtype=np.float64)
        S[:, 0, 0] = scl[:, 0]
        S[:, 1, 1] = scl[:, 1]
        S[:, 2, 2] = scl[:, 2]
        S[:, 3, 3] = 1.0
        T = np.zeros((n, 4, 4), dtype=np.float64)
        T[:, 0, 0] = T[:, 1, 1] = T[:, 2, 2] = T[:, 3, 3] = 1.0
        T[:, 3, 0] = pos[:, 0]
        T[:, 3, 1] = pos[:, 1]
        T[:, 3, 2] = pos[:, 2]
        R = self._batch_rotations(models, rot=rot)
        local = S @ R @ T
        world = np.empty_like(local)
        for d in range(int(depth.max()) + 1):
            idx = np.where(depth == d)[0]
            if d == 0:
                world[idx] = local[idx]
            else:
                world[idx] = local[idx] @ world[parent[idx]]   # (k,4,4)@(k,4,4) 批量
        return world

    @staticmethod
    def _batch_rotations(models, rot=None):
        """批量旋转矩阵 (与 mat4_rotation 逐元素一致: Rx @ Ry @ Rz 行主序).
        组3层1: rot 可选 (N,3) f64 平面 (compute_world_matrices 传 _transform_snapshot
        的 rot 切片, 免 3 次属性链列取); 不传走旧列取 (防御: 其他调用点/测试桩)."""
        n = len(models)
        if rot is not None:
            rx, ry, rz = rot[:, 0], rot[:, 1], rot[:, 2]
        else:
            rx = np.array([m.rotation.x for m in models], dtype=np.float64)
            ry = np.array([m.rotation.y for m in models], dtype=np.float64)
            rz = np.array([m.rotation.z for m in models], dtype=np.float64)
        cx, sx = np.cos(rx), np.sin(rx)
        cy, sy = np.cos(ry), np.sin(ry)
        cz, sz = np.cos(rz), np.sin(rz)
        Rx = np.zeros((n, 4, 4), dtype=np.float64)
        Rx[:, 0, 0] = 1.0
        Rx[:, 1, 1] = cx; Rx[:, 1, 2] = sx
        Rx[:, 2, 1] = -sx; Rx[:, 2, 2] = cx
        Rx[:, 3, 3] = 1.0
        Ry = np.zeros((n, 4, 4), dtype=np.float64)
        Ry[:, 0, 0] = cy; Ry[:, 0, 2] = -sy
        Ry[:, 1, 1] = 1.0
        Ry[:, 2, 0] = sy; Ry[:, 2, 2] = cy
        Ry[:, 3, 3] = 1.0
        Rz = np.zeros((n, 4, 4), dtype=np.float64)
        Rz[:, 0, 0] = cz; Rz[:, 0, 1] = sz
        Rz[:, 1, 0] = -sz; Rz[:, 1, 1] = cz
        Rz[:, 2, 2] = 1.0; Rz[:, 3, 3] = 1.0
        return Rx @ Ry @ Rz

    def parent_world_matrix(self, m):
        """父物体的世界矩阵 (根=单位阵), 用于局部<->世界换算"""
        if m.parent is None:
            return np.eye(4, dtype=np.float64)
        return self.model_world_matrix(m.parent)

    def world_position(self, m):
        """物体中心的世界坐标 (父链合成)"""
        p = np.array([m.position.x, m.position.y, m.position.z, 1.0])
        if m.parent is not None:
            p = p @ self.model_world_matrix(m.parent)
        return Point3D(float(p[0]), float(p[1]), float(p[2]))

    def world_rotation_matrix(self, m):
        """物体旋转部分的世界矩阵 (忽略缩放, 供 gizmo 旋转换算)"""
        R = mat4_rotation(np, m.rotation.x, m.rotation.y, m.rotation.z)
        if m.parent is not None:
            R = R @ self.world_rotation_matrix(m.parent)
        return R

    def world_scale(self, m):
        """物体世界缩放 (沿父链各局部缩放分量相乘, 忽略父旋转; 与引擎缩放处理一致)"""
        s = Point3D(m.scale[0], m.scale[1], m.scale[2])
        cur = m.parent
        while cur is not None:
            s = Point3D(s.x * cur.scale[0], s.y * cur.scale[1], s.z * cur.scale[2])
            cur = cur.parent
        return s

    def world_to_local(self, m, p):
        """世界点 -> 该物体父空间的局部坐标 (行向量: local = world @ inv(parentWorldM))"""
        pw = np.array([p[0], p[1], p[2], 1.0])
        loc = pw @ np.linalg.inv(self.parent_world_matrix(m))
        return Point3D(float(loc[0] / loc[3]), float(loc[1] / loc[3]), float(loc[2] / loc[3]))

    def is_ancestor(self, ancestor, m):
        """ancestor 是否为 m 的祖先 (沿父链向上找)"""
        cur = m
        while cur is not None:
            if cur is ancestor:
                return True
            cur = cur.parent
        return False

    def set_parent(self, child, new_parent, preserve_world=True):
        """把 child 挂到 new_parent 下 (None=根). 拒绝设置自身或设为子孙 (防环).

        preserve_world=True (默认, Unity 挂父语义): 换父后按新父空间重新换算 child
        的局部位置/旋转/缩放, 使 child (及其整棵子树) 的**世界位置/旋转/缩放不变**——
        挂父/脱父那一下物体不会跳。位置用 world_to_local, 旋转 R_local = R_world @
        inv(R_parent), 缩放分量相除; 旋转矩阵用 decompose_euler 还原欧拉角。
        preserve_world=False: 仅改父指针, 局部值原样保留 (调用方已按父空间备好局部值,
        如复制命令/播放退出精确还原; 场景加载不走此方法, 直接 m.parent= 赋值).
        """
        if child is new_parent:
            return
        if new_parent is not None and self.is_ancestor(child, new_parent):
            return
        if child.parent is new_parent:
            return
        # 记录换父前世界变换 (旧父链)
        if preserve_world:
            wp = self.world_position(child)
            wr = self.world_rotation_matrix(child)
            ws = self.world_scale(child)
        # 换父 (children 列表重建)
        if child.parent is not None:
            if child in child.parent.children:
                child.parent.children.remove(child)
        child.parent = new_parent
        if new_parent is not None:
            new_parent.children.append(child)
        self._bump_struct()                    # 组3: 挂父变更失效 (ancestry+SoA)
        # 按新父空间换算局部变换, 保持世界位置/旋转/缩放
        if preserve_world:
            loc = self.world_to_local(child, wp)
            child.position = loc
            Rp = self.world_rotation_matrix(new_parent) if new_parent is not None \
                else np.eye(4, dtype=np.float64)
            Rl = wr @ np.linalg.inv(Rp)
            a, b, g = decompose_euler(Rl)
            child.rotation = Point3D(a, b, g)
            ps = self.world_scale(new_parent) if new_parent is not None else Point3D(1, 1, 1)
            child.scale = Point3D(ws.x / ps.x, ws.y / ps.y, ws.z / ps.z)

    def collect_subtree(self, model):
        """收集 model 及其全部子孙 (DFS, 删除/序列化/Prefab 用)"""
        out = [model]
        for c in list(model.children):
            out.extend(self.collect_subtree(c))
        return out

    def get_bounding_box(self, model, M=None):
        """获取模型的轴对齐包围盒 (AABB), 用世界矩阵变换 (含父链 S@R@T).
        M 可选: 传入当帧批量矩阵避免重算 (多核优化).
        顶点列表->齐次数组结果按 id(mesh) 缓存 (网格创建后不可变, 高面数球一次转换省
        每帧/每包围盒调用重复 asarray 开销; 2026-08-15 8 核均摊压测发现的瓶颈)."""
        M = M if M is not None else self.model_world_matrix(model)
        vh = self._homogeneous_vertices(model.mesh)
        # 只算需要的 3 列, 转置成 (3,V) 连续后沿连续轴归约 (微基准: axis=0 归约慢 4 倍,
        # 高面数球每帧 51+ 次包围盒时差 ~6ms/帧, 压测发现的瓶颈)
        w3t = np.ascontiguousarray((vh @ M[:, :3]).T)       # (3,V) 连续
        mn, mx = w3t.min(axis=1), w3t.max(axis=1)
        return (Point3D(float(mn[0]), float(mn[1]), float(mn[2])),
                Point3D(float(mx[0]), float(mx[1]), float(mx[2])))

    def _homogeneous_vertices(self, mesh):
        """网格顶点 -> 齐次 (V,4) float64 数组, 按 id(mesh) 缓存 (网格不可变).
        校验 vertices 列表身份, 防外部替换列表后用过期缓存.
        _bb_cache 惰性建 (测试桩用 __new__ 不跑 __init__)."""
        cache = getattr(self, '_bb_cache', None)
        if cache is None:
            cache = self._bb_cache = {}
        key = id(mesh)
        ent = cache.get(key)
        if ent is not None and ent[0] is mesh.vertices:
            return ent[1]
        verts = np.asarray(mesh.vertices, dtype=np.float64)
        vh = np.concatenate([verts, np.ones((verts.shape[0], 1))], axis=1)
        if len(cache) > 2048:                   # 防资产频繁增删时无限膨胀
            cache.clear()
        cache[key] = (mesh.vertices, vh)
        return vh

    # ================ 碰撞系统 (M28: 简单物理) ================
    # 设计: 碰撞是"世界空间"实时计算的 —— 每帧按当前变换算世界体积 (含父链),
    # 所以父链移动/旋转子物体也会正确挡人. 支持 box(AABB) 与 sphere 两种碰撞体.
    def collider_bounds(self, m, M=None):
        """世界空间碰撞体数据 -> ('box', (mn, mx)) 或 ('sphere', (center, radius)).
        球体取 AABB 中心 + 最大半长: 对球体网格正好等于真实半径, 比 AABB 更贴合.
        M 可选: 传入当帧批量矩阵避免重算 (多核优化)."""
        if m.collider.shape == 'sphere':
            mn, mx = self.get_bounding_box(m, M)
            c = Point3D((mn.x + mx.x) * 0.5, (mn.y + mx.y) * 0.5, (mn.z + mx.z) * 0.5)
            r = max(mx.x - mn.x, mx.y - mn.y, mx.z - mn.z) * 0.5
            return ('sphere', (c, r))
        return ('box', self.get_bounding_box(m, M))

    @staticmethod
    def _collider_from_aabb(shape, aabb):
        """从 AABB (mn,mx) 派生碰撞体数据, 与 collider_bounds 一致 (共享包围盒时免重算).
        sphere: 中心=AABB 中点, 半径=最大半长 (与 collider_bounds 相同); box: 即 AABB."""
        mn, mx = aabb
        if shape == 'sphere':
            c = Point3D((mn.x + mx.x) * 0.5, (mn.y + mx.y) * 0.5, (mn.z + mx.z) * 0.5)
            r = max(mx.x - mn.x, mx.y - mn.y, mx.z - mn.z) * 0.5
            return ('sphere', (c, r))
        return ('box', (mn, mx))

    @staticmethod
    def _pair_overlap(ba, bb):
        """两个 (shape, data) 碰撞体是否相交 (纯几何, 无副作用).
        用严格 < : 恰好贴边不算碰撞, 静止物不会反复被推."""
        sa, da = ba
        sb, db = bb
        if sa == 'box' and sb == 'box':
            (amn, amx), (bmn, bmx) = da, db
            return all(amn[i] < bmx[i] and bmn[i] < amx[i] for i in (0, 1, 2))
        if sa == 'sphere' and sb == 'sphere':
            (ca, ra), (cb, rb) = da, db
            dx, dy, dz = ca.x - cb.x, ca.y - cb.y, ca.z - cb.z
            return dx * dx + dy * dy + dz * dz < (ra + rb) ** 2
        # box-sphere: 球心到盒最近点距离 < 半径 (球在盒内也算相交)
        if sa == 'sphere':                # a 是球, b 是盒
            (sc, r), (bmn, bmx) = da, db
        else:                             # a 是盒, b 是球
            (bmn, bmx), (sc, r) = da, db
        cx = max(bmn.x, min(sc.x, bmx.x))
        cy = max(bmn.y, min(sc.y, bmx.y))
        cz = max(bmn.z, min(sc.z, bmx.z))
        dx, dy, dz = sc.x - cx, sc.y - cy, sc.z - cz
        return dx * dx + dy * dy + dz * dz < r * r

    @staticmethod
    def _pair_overlap_vec(ai, bj, bmn, bmx, scn, rad, kind):
        """向量化 _pair_overlap 判定 (多核优化: 碰撞检测拆分给线程池).

        ai/bj: 模型下标数组 (len K, 逐对); bmn/bmx (n,3) 盒 min/max; scn (n,3)
        球心; rad (n,) 球半径; kind (n,) 0=box 1=sphere. 返回 bool(K),
        与 _pair_overlap 逐位一致 (严格 <, 贴边不算碰撞)."""
        res = np.zeros(len(ai), dtype=bool)
        ki, kj = kind[ai], kind[bj]
        bb = (ki == 0) & (kj == 0)
        if bb.any():
            a, b = ai[bb], bj[bb]
            res[bb] = ((bmn[a, 0] < bmx[b, 0]) & (bmn[b, 0] < bmx[a, 0]) &
                       (bmn[a, 1] < bmx[b, 1]) & (bmn[b, 1] < bmx[a, 1]) &
                       (bmn[a, 2] < bmx[b, 2]) & (bmn[b, 2] < bmx[a, 2]))
        ss = (ki == 1) & (kj == 1)
        if ss.any():
            a, b = ai[ss], bj[ss]
            d = scn[a] - scn[b]
            res[ss] = np.einsum('ij,ij->i', d, d) < (rad[a] + rad[b]) ** 2
        bs = (ki != kj)                       # 盒-球 / 球-盒: 球心到盒最近点距离 < r
        if bs.any():
            a, b = ai[bs], bj[bs]
            sa = np.where(kind[a] == 1, a, b)       # 球下标
            bx = np.where(kind[a] == 1, b, a)       # 盒下标
            cx = np.clip(scn[sa][:, 0], bmn[bx][:, 0], bmx[bx][:, 0])
            cy = np.clip(scn[sa][:, 1], bmn[bx][:, 1], bmx[bx][:, 1])
            cz = np.clip(scn[sa][:, 2], bmn[bx][:, 2], bmx[bx][:, 2])
            dx = scn[sa][:, 0] - cx
            dy = scn[sa][:, 1] - cy
            dz = scn[sa][:, 2] - cz
            res[bs] = (dx * dx + dy * dy + dz * dz) < rad[sa] ** 2
        return res

    def _related(self, a, b):
        """a/b 是否有祖先/后代关系 (同一棵变换树). 同树物体间不互相碰撞."""
        return a is b or self.is_ancestor(a, b) or self.is_ancestor(b, a)

    @staticmethod
    def _ancestry_ranges(models, gen=None):
        """模型森林 DFS 序区间 (A1 2026-08-29, 每帧一次 O(n)):
        a 是 b 祖先 ⟺ tin[a] <= tin[b] < tout[a]。与旧 _related / is_ancestor 沿父链
        判定语义一致; parent 不在 models 视为根 (id2i.get -> -1); 环状父链防御性
        隔离 (理论上不可能, set_parent 防环)。
        组2 (2026-08-30): 结果挂函数对象缓存 (models 列表同一对象 且 gen 版本号
        未变则直接复用 tin/tout) —— 物理子步/A1 对生成每帧多次调用只算一次;
        六处结构变更点经 _bump_struct() 失效。列表对象身份校验防换场景串用。
        组3: gen 由调用方传 (实例计数器 _struct_gen); 不传=退化为 (id, None)
        键, 同一列表对象仅首算缓存 (静态域拿不到 self, 保守正确: 结构变更
        后列表对象通常仍同一 -> 调用方必须传 gen 才有失效语义, 见 _related3 处
        调用点全带 gen)。
        组3层2: DFS 计算委托 fastpath.ancestry_dfs (numba 编译/纯 Python 降级同源, 对拍网 numba_par_check.py 覆盖)。"""
        gen = getattr(models, '_loosed_gen', None) if gen is None else gen
        key = (id(models), gen)
        cache = GLEngine._ANCESTRY_CACHE
        if cache is not None and cache[0] == key:
            return cache[1], cache[2]
        n = len(models)
        id2i = {id(m): i for i, m in enumerate(models)}
        parent_idx = np.full(n, -1, dtype=np.int64)
        for i, m in enumerate(models):
            if m.parent is not None:
                parent_idx[i] = id2i.get(id(m.parent), -1)
        tin, tout = _fp_ancestry(parent_idx)   # 组3层2: children构建+栈式DFS+兜底 委托 fastpath.ancestry_dfs (CSR/根序/防环/兜底语义逐位一致)
        GLEngine._ANCESTRY_CACHE = (key, tin, tout)
        return tin, tout

    def collider_hit(self, a, b, Ma=None, Mb=None):
        """两物体是否碰撞 (都启用且形状非 none 才判; 同树物体不算).
        Ma/Mb: 可选当帧世界矩阵 (避免每对重算 model_world_matrix, 播放期碰撞检测热点)."""
        if self._related(a, b):
            return False
        ca, cb = a.collider, b.collider
        if not (ca.enabled and cb.enabled):
            return False
        if ca.shape == 'none' or cb.shape == 'none':
            return False
        return self._pair_overlap(self.collider_bounds(a, Ma),
                                  self.collider_bounds(b, Mb))

    def get_collisions(self, m, fw=None, bounds=None):
        """碰撞查询: 返回当前与 m 碰撞的所有其他物体 (按 self.models 顺序).
        脚本里用: others = self.engine.get_collisions(self.obj) —— 碰到就能反应.
        fw: 可选当帧世界矩阵列表 (对齐 self.models), 避免逐对重算 model_world_matrix.
        bounds: 可选共享缓存 dict (A3: move_with_collision 跨子步传同一 dict,
        其他物体子步间不动, 碰撞体每物体只算一次; 与逐调用现算数值一致,
        最终位形时刻所得结果逐位相同).
        A3 (2026-08-29): 每物体碰撞体本调用内也只算一次 —— 旧版逐对调
        collider_hit→collider_bounds = 每对一次全网格顶点变换 (高面数球
        逐子步×逐对, 播放物理场景主热点, 实测 7s/帧级).
        组2 (2026-08-30): m 的下标改在物序循环里顺带确定 (旧: models.index
        额外 O(n) 线性扫; 物理子步逐球调用的场景下省 N 次全表扫)."""
        mi = None
        col_m = m.collider
        if col_m is None or not col_m.enabled or col_m.shape == 'none':
            return []
        if bounds is None:
            bounds = {}
        bm = None
        out = []
        for i, o in enumerate(self.models):
            if o is m:
                if fw is not None:
                    mi = i                     # 顺带: m 在物序中的下标 (供 fw 取矩阵)
                continue
            if self._related(m, o):
                continue
            col_o = o.collider
            if col_o is None or not col_o.enabled or col_o.shape == 'none':
                continue
            bo = bounds.get(id(o))
            if bo is None:
                if bm is None:
                    Ma = fw[mi] if (fw is not None and mi is not None) else None
                    bm = self.collider_bounds(m, Ma)
                bo = self.collider_bounds(o, fw[i] if fw is not None else None)
                bounds[id(o)] = bo
            elif bm is None:
                Ma = fw[mi] if (fw is not None and mi is not None) else None
                bm = self.collider_bounds(m, Ma)
            if self._pair_overlap(bm, bo):
                out.append(o)
        return out

    def _collider_center_radius(self, m):
        """碰撞体 -> (中心, 特征半径). 球=真实半径; 盒=外接球半径 (推挤近似用)."""
        shape, data = self.collider_bounds(m)
        if shape == 'sphere':
            return data
        mn, mx = data
        c = Point3D((mn.x + mx.x) * 0.5, (mn.y + mx.y) * 0.5, (mn.z + mx.z) * 0.5)
        r = math.sqrt(((mx.x - mn.x) ** 2 + (mx.y - mn.y) ** 2 + (mx.z - mn.z) ** 2) * 0.25)
        return (c, r)

    def _push_out(self, a, b, bounds=None):
        """把 a 推出 b 的碰撞体 (仅已相交时调用). 盒-盒走最小穿透轴 (滑墙自然),
        含球时沿球心连线推出. 只改 a.position.
        A3: bounds 缓存中 b 的碰撞体直接复用 (b 帧内静止, 免逐次全网格重算);
        a 自身不缓存 (每次推出都改了 a.position, 必须现算)."""
        ba = self.collider_bounds(a)
        if bounds is not None:
            bb = bounds.get(id(b))
            if bb is None:
                bb = self.collider_bounds(b)
                bounds[id(b)] = bb
        else:
            bb = self.collider_bounds(b)
        if ba[0] == 'box' and bb[0] == 'box':
            (amn, amx), (bmn, bmx) = ba[1], bb[1]
            # 每轴正确穿透量 = 把 a 沿 + / - 推到刚分开的最小位移 (取较小者).
            # 这样零厚度盒 (地面平面) 也能得到真实穿透量, 而不是 0.
            best_axis = best_sign = None
            best_push = None
            for i in (0, 1, 2):
                a0, a1 = amn[i], amx[i]
                b0, b1 = bmn[i], bmx[i]
                if a0 >= b1 or b0 >= a1:      # 该轴不相交 -> 不用推
                    continue
                dist_right = b1 - a0           # a 向右推这么多才分开 (>=0)
                dist_left = a1 - b0            # a 向左推这么多才分开
                if dist_left < dist_right - 1e-9:
                    sign, dist = -1.0, dist_left
                elif dist_right < dist_left - 1e-9:
                    sign, dist = +1.0, dist_right
                else:                          # 相等: 朝远离对方中心方向
                    sign = +1.0 if (a0 + a1) >= (b0 + b1) else -1.0
                    dist = dist_right if sign > 0 else dist_left
                if best_push is None or dist < best_push:
                    best_push, best_sign, best_axis = dist, sign, i
            if best_axis is not None:
                p = list(a.position)
                p[best_axis] += best_sign * (best_push + 1e-4)
                a.position = Point3D(*p)
            return
        # 球-球: 沿两中心连线推出 (球心到球心, 半径和)
        if ba[0] == 'sphere' and bb[0] == 'sphere':
            ca, ra = ba[1]
            cb, rb = bb[1]
            dx, dy, dz = ca.x - cb.x, ca.y - cb.y, ca.z - cb.z
            dist = math.sqrt(dx * dx + dy * dy + dz * dz) or 1e-6
            need = ra + rb - dist + 1e-4
            u = (dx / dist, dy / dist, dz / dist)
            p = list(a.position)
            p[0] += u[0] * need
            p[1] += u[1] * need
            p[2] += u[2] * need
            a.position = Point3D(*p)
            return
        # 盒-球: 用"球心到盒最近点"推出 (与 _pair_overlap 判定一致; 修复 2026-08-12:
        # 旧实现把盒当球取最大半长, 大平面(地面 10x10)被当半径5的球, 球被推出数个单位).
        if ba[0] == 'sphere':
            sc, r = ba[1]; bmn, bmx = bb[1]; a_is_sphere = True
        else:
            bmn, bmx = ba[1]; sc, r = bb[1]; a_is_sphere = False
        nx = min(max(sc.x, bmn.x), bmx.x)
        ny = min(max(sc.y, bmn.y), bmx.y)
        nz = min(max(sc.z, bmn.z), bmx.z)
        dx, dy, dz = sc.x - nx, sc.y - ny, sc.z - nz
        dist = math.sqrt(dx * dx + dy * dy + dz * dz)
        if dist < 1e-9:
            # 球心在盒内: 沿盒中心指向球心方向推出 (球半径距离)
            cc = Point3D((bmn.x + bmx.x) / 2, (bmn.y + bmx.y) / 2,
                         (bmn.z + bmx.z) / 2)
            vx, vy, vz = sc.x - cc.x, sc.y - cc.y, sc.z - cc.z
            vl = math.sqrt(vx * vx + vy * vy + vz * vz) or 1e-6
            u = (vx / vl, vy / vl, vz / vl)
            need = r + 1e-4
        else:
            need = r - dist + 1e-4
            u = (dx / dist, dy / dist, dz / dist)      # 盒最近点 -> 球心
            if not a_is_sphere:
                u = (-u[0], -u[1], -u[2])             # a 是盒: 反方向推盒离球
        p = list(a.position)
        p[0] += u[0] * need
        p[1] += u[1] * need
        p[2] += u[2] * need
        a.position = Point3D(*p)

    def resolve_collisions(self, m, max_iter=4, bounds=None):
        """把 m 推干净: 迭代推离所有相交物体. 返回是否发生过碰撞 (被挡).
        脚本在移动后调用, 或直接交给 move_with_collision.
        bounds: 共享碰撞体缓存 (A3, 见 get_collisions; 其他物体帧内静止时
        一次算全程复用)."""
        hit = False
        for _ in range(max_iter):
            coll = self.get_collisions(m, bounds=bounds)
            if not coll:
                break
            hit = True
            for o in coll:
                self._push_out(m, o, bounds=bounds)
        return hit

    def move_with_collision(self, m, dx, dy, dz, bounds=None):
        """带碰撞的位移 (M28 响应): 子步移动防穿透薄物体 (每步 <= 碰撞体特征尺寸),
        每步移动后把 m 推出所有相交碰撞体. 返回 True = 被挡住/发生碰撞
        (脚本据此停下/反弹/触发事件).
        bounds: 可选共享碰撞体缓存 dict (A3) —— 子步间/同帧物理阶段其他物体静止,
        碰撞体每物体只算一次 (本物体自身每子步现算: m 每个子步后都在变, 且从不
        被写进缓存)。传帧级缓存时 (update_physics._physics_bounds) 特别精确:
        后移动物体查先移动物体的条目 = 首次现算所得 "先移动者的移动后位形"
        (它也不在该缓存里), 与逐调用现算逐位一致."""
        shape, data = self.collider_bounds(m)
        if shape == 'sphere':
            step = max(data[1], 0.02)                 # 球: 特征步长 = 半径
        else:
            mn, mx = data
            # 盒: 最小半边长 (沿任何轴移动该距离都不会跳过相邻薄面)
            step = max(min(mx.x - mn.x, mx.y - mn.y, mx.z - mn.z) * 0.5, 0.02)
        n = max(1, math.ceil(max(abs(dx), abs(dy), abs(dz)) / step))
        n = min(n, 5000)                              # 防御: 病态超大位移不卡死
        if bounds is None:
            bounds = {}
        hit = False
        for _ in range(n):
            m.position = Point3D(m.position.x + dx / n,
                                 m.position.y + dy / n,
                                 m.position.z + dz / n)
            if self.resolve_collisions(m, bounds=bounds):
                hit = True
        bounds.pop(id(m), None)                       # 自身条目不存在, 防御清理
        return hit

    # ================ 刚体物理 + 碰撞事件 (M31) ================
    _GRAVITY = -9.8

    def update_physics(self, delta_time, events=True):
        """M31: 每帧刚体步进 + 碰撞事件回调 (Unity Rigidbody 理念).
        B1 (2026-08-30): **桥分支** —— _phys_bridge 存在且 enabled 时, 刚体动力学
        交给 Culverin (Jolt) (physics_bridge.py: R1 手动重力/策略 R 速度门控/接触
        解算/摩擦滚动/睡眠; pre→step→post 三段内联于 _update_physics_bridge);
        无桥/库不可用/测试桩 -> **_update_physics_legacy** (原实现, 一行未删)。
        进入播放 (toggle_play) / 首次 update_physics 直调由 _ensure_phys_bridge
        惰性建桥 (仅完整 __init__ 实例: getattr(_phys_bridge_auto)); 测试桩
        (__new__ 不跑 __init__) 无该属性 -> 永走 legacy (现契约测试零受影响)。"""
        br = getattr(self, '_phys_bridge', None)
        if br is not None:
            if getattr(br, 'enabled', False):
                self._update_physics_bridge(delta_time, events)
                return
            self._phys_bridge = None            # 僵死桥 (库异常) -> 释放走 legacy
        elif getattr(self, '_phys_bridge_auto', False):
            self._ensure_phys_bridge()
            br = getattr(self, '_phys_bridge', None)
            if br is not None and getattr(br, 'enabled', False):
                self._update_physics_bridge(delta_time, events)
                return
        self._update_physics_legacy(delta_time, events)

    def _update_physics_legacy(self, delta_time, events=True):
        """自研物理 (M31 原实现, B1 起作为**回退分支**): 累加-移动-撞停模型.
        对每个带刚体的动态物体: 重力累加速度 -> 按速度带碰撞移动 (被挡停清速度).
        B1 桥路径下不调用; 无 culverin / 测试桩 / 桥异常回退时走这里 (行为逐位不变).
        events=False: 跳过碰撞事件 (2026-08-15 8 核均摊: 渲染路径把碰撞**检测**与阴影
        VP 并行后, 事件**派发**回主线程单独做; 直调本方法 (测试/旧路径) 默认 events=True 不变).
        A3 (2026-08-29): 物理阶段所有移动物体共享 _physics_bounds 缓存 —— 非移动
        物体的碰撞体本帧只算一次 (旧版每球移动调用逐对全网格变换); 移动者自身
        每子步现算 (move_with_collision 结束 pop 自身条目), 顺序精确性保持:
        后移动物体查先移动者时缓存必为"移动后位形" (先移动者条目未被写进缓存,
        等同现算, 见 move_with_collision 注释)."""
        dt = max(delta_time, 1e-4)
        self._physics_bounds = {}          # 本帧物理级缓存 (id(o) -> 碰撞体数据)
        for m in self.models:
            rb = m.rigidbody
            if rb is None or rb.is_kinematic:
                continue
            if rb.use_gravity:
                # 2026-08-30: 重力可调 (self.gravity, 场景/设置/面板); getattr 防御
                # 测试桩 (__new__ 不跑 __init__ 时无 gravity 属性)
                g = getattr(self, 'gravity', self._GRAVITY)
                rb.velocity = Point3D(rb.velocity.x,
                                      rb.velocity.y + g * dt,
                                      rb.velocity.z)
            vx, vy, vz = rb.velocity.x, rb.velocity.y, rb.velocity.z
            if not (vx or vy or vz):
                continue
            hit = self.move_with_collision(m, vx * dt, vy * dt, vz * dt,
                                           bounds=self._physics_bounds)
            if hit:
                # 撞到东西: 速度归零停住 (简单版; 后续可做轴向分离/反弹/滑墙)
                rb.velocity = Point3D(0.0, 0.0, 0.0)
        if events:
            self._update_collision_events(dt)

    # ================ B1: Culverin (Jolt) 物理桥路径 ================
    def _update_physics_bridge(self, delta_time, events):
        """桥路径: ensure_models 差量 -> pre_step (脏同步+策略R+重力) -> step
        (释放 GIL) -> post_step (批式回读) — 顺序 per 设计 §3.1; 其余不动
        (world matrices/几何事件在回读之后, 见 render/EditorApp.render)."""
        dt = max(delta_time, 1e-4)
        br = getattr(self, '_phys_bridge', None)
        if br is None or not getattr(br, 'enabled', False):
            if events:
                self._update_collision_events(dt)
            return
        try:
            # 2026-09-01 组8 细拆插桩: physics 22.84ms 拆四段 (ensure_models
            # O(N²)扫描嫌疑 vs Jolt step C 调用 vs pre/post), LOOM_PROFILE 子阶段
            g = getattr(self, 'gravity', self._GRAVITY)       # R1: 用引擎实例重力!
            self._profile('phys_bridge_ensure', lambda: br.ensure_models(self.models))
            self._profile('phys_bridge_pre', lambda: br.pre_step(dt, g))
            self._profile('phys_bridge_step', lambda: br.step(dt))
            self._profile('phys_bridge_post', lambda: br.post_step())
        except Exception as e:
            # 桥异常: 本帧回退 legacy 并释放桥 (静默降级, 游戏不崩; 控制台留痕)
            print("[物理] 桥步进异常 (%r) -> 释放桥并回退 legacy" % (e,))
            self._destroy_phys_bridge()
            self._update_physics_legacy(dt, events)
            return
        if events:
            self._update_collision_events(dt)                 # 几何事件 (B1 保留, 见设计 §2.2)

    def _ensure_phys_bridge(self):
        """惰性建桥: 首次进入播放/首次 update_physics 直调. 返回桥实例或 None.
        无 culverin / 建体失败 -> 置 _phys_bridge_disabled 标记, 不再重试 (legacy).
        ★getattr 防御测试桩 (__new__ 无 __init__): _phys_bridge_auto 缺失 -> None."""
        if getattr(self, '_phys_bridge_auto', False) is not True:
            return None
        if getattr(self, '_phys_bridge_disabled', False):
            return None
        br = getattr(self, '_phys_bridge', None)
        if br is not None:
            return br
        try:
            from physics_bridge import PhysicsWorldBridge, cv_available
        except Exception as e:
            print("[物理] physics_bridge 导入失败:", e)
            self._phys_bridge_disabled = True
            return None
        if not cv_available:
            self._phys_bridge_disabled = True       # 无库环境: 静默 legacy (设计 P5 提示点)
            return None
        br = PhysicsWorldBridge()
        try:
            br.build(self.models)
        except Exception as e:
            print("[物理] Culverin 建体失败 (%r) -> 保持 legacy" % (e,))
            try:
                br.destroy()
            except Exception:
                pass
            self._phys_bridge_disabled = True
            return None
        self._phys_bridge = br
        print("[物理] Jolt (Culverin) 物理桥已建立: %d 体" % br.body_count)
        return br

    def _destroy_phys_bridge(self):
        """销毁桥 (播放结束/退出清理). 幂等. 快照还原在 destroy 之前完成
        (toggle_play 退出分支先 apply_snapshot 再 destroy, 见 editor.py)."""
        br = getattr(self, '_phys_bridge', None)
        if br is not None:
            try:
                br.destroy()
            except Exception:
                pass
        self._phys_bridge = None
        # 不置 disabled: 下次进入播放可重建 (播放-停止循环)

    # 碰撞事件并行阈值: 模型数 >= 此值才启用线程池 (小场景走内联零线程开销)
    _COLLISION_PAR_THRESHOLD = 32
    # 碰撞对分块阈值: 碰撞对 >= 此值才真正分块丢线程池 (2026-08-15 实测: 单次向量化
    # 调用比线程池分块快 300 倍; 只有超大场景线程池并发才有收益)
    _COLLISION_POOL_PAIRS = 100000
    # AABB 并行阈值: 模型数 >= 此值才用预计算池分块算包围盒 (压测实测 51 模型池比串行慢,
    # 模型多时 numpy 分块才摊得开线程开销)
    _AABB_POOL_THRESHOLD = 64
    # ★spin-wait 治理 (2026-08-31): prange 并行逃生门闸门 —— 单组模型数 >= 此值才
    # 切 aabbs_minmax_par (numba 线程池). 实测 51球组串行 njit ~104µs / 并行 ~54µs,
    # 差距 <100µs 无关紧要, 而 prange 唤醒的 18 个 worker 在帧间 busy-wait 空烧
    # (18 核满载 99.96% 无效负载, numba_spin_probe.py 实锤). 闸门 = 工作量足够大
    # 才值得付 spin 税 (估算: n_models × V 顶点, 512 模型×2035顶点 ≈ 1M 变换 ~1ms).
    _AABB_PAR_MIN_MODELS = 512
    # A1 (2026-08-29): 候选对 numpy 生成上限 (triu 全对内存 ~ n^2*16B;
    # >2048 碰撞体即 >33MB, 现实场景不触发, 回退原 Python 循环只防内存)
    _PAIR_GEN_NUMPY_MAX = 2048

    def _ensure_collision_pool(self):
        """自适应创建碰撞检测线程池 (线程 affinity = 渲染核 pool_mask). 返回池或 None."""
        if self._collision_pool is None:
            try:
                from concurrent.futures import ThreadPoolExecutor
                from parallel import pin_current_thread
                pol = self.parallel.get('policy') if self.parallel else None
                pmask = (pol or {}).get('pool_mask') or 0

                def _init():
                    if pmask:
                        pin_current_thread(pmask)

                n_logical = (pol or {}).get('n_logical', 0) or (os.cpu_count() or 1)
                nw = min(4, max(1, n_logical - (self.script_cores or 0) - 1))
                self._collision_pool = ThreadPoolExecutor(
                    max_workers=nw, initializer=_init)
            except Exception as e:
                print("[parallel] 碰撞池初始化失败:", e)
                self._collision_pool = None
        return self._collision_pool

    def _update_collision_events(self, dt):
        """M31: 比较每物体当前碰撞集与上次, 触发脚本 on_collision_start/on_collision_end
        (Unity OnCollisionEnter/Exit 式). 只对有脚本的物体检测.
        多核优化: 大场景 (>=阈值) 且并行启用时, 碰撞检测走向量化+线程池 (只读),
        事件派发仍串行 (改脚本状态必须串行). 小场景内联零开销."""
        n = len(self.models)
        if (n >= self._COLLISION_PAR_THRESHOLD
                and getattr(self, 'parallel', None) is not None
                and self._ensure_collision_pool() is not None):
            self._collision_events_parallel()
        else:
            self._collision_events_inline()

    def _collision_events_inline(self):
        """小场景碰撞事件 (O(N^2) 逐对判定).
        2026-08-15 性能修复: **每个物体只算一次碰撞体包围盒 (O(N), 传当帧 _frame_world
        免重算 model_world_matrix), 逐对判定用缓存的包围盒走纯几何 _pair_overlap** ——
        原实现逐对调 collider_bounds 重算全部顶点变换, 20 脚本物体曾 53ms/帧 (19FPS)."""
        models = self.models
        fw = getattr(self, '_frame_world', None)
        n = len(models)
        # 每物体碰撞体缓存 (含当帧矩阵), None=无碰撞体
        bounds = [None] * n
        for i, m in enumerate(models):
            col = m.collider
            if col is not None and col.enabled and col.shape != 'none':
                Mi = fw[i] if fw is not None and i < n else None
                bounds[i] = (m, self.collider_bounds(m, Mi))
        for i, m in enumerate(models):
            if not m.scripts:
                continue
            if bounds[i] is None:
                m._colliding = set()
                continue
            bi = bounds[i][1]
            current = set()
            for j in range(n):
                if j == i or self._related(m, models[j]):
                    continue
                bj = bounds[j]
                if bj is None:
                    continue
                if self._pair_overlap(bi, bj[1]):
                    current.add(id(bj[0]))
            prev = getattr(m, '_colliding', set())
            if current == prev:
                continue
            # 组2 (2026-08-30): id->对象 一次建 (旧: 每事件 next() O(n) 扫;
            # 仅在确有增减事件时才建, 无事件帧零开销)
            id2m = {id(o): o for o in models}
            for cid in current - prev:
                self._call_collision_cb(m, 'on_collision_start', id2m.get(cid))
            for cid in prev - current:
                self._call_collision_cb(m, 'on_collision_end', id2m.get(cid))
            m._colliding = current

    def _collision_events_parallel(self):
        """并行版: 一次算全部碰撞对 (向量化 + 线程池), 串行派发事件.
        current 集合与内联版逐位一致."""
        pairs = self._collision_pairs_parallel()      # 只读检测
        self._dispatch_collision_events(pairs)        # 串行派发 (改脚本状态)

    def _dispatch_collision_events(self, pairs):
        """把碰撞对 [(i,j),...] 串行派发成 on_collision_start/end (改脚本状态, 必须主线程).
        2026-08-15: 从检测中拆出, 让检测能与阴影 VP 并行 (检测只读)."""
        neigh = {}
        for i, j in pairs:
            neigh.setdefault(i, set()).add(j)
            neigh.setdefault(j, set()).add(i)
        # 组2 (2026-08-30): id->对象 一次建 (旧: 每事件 next() 生成器全表扫 O(n))
        id2m = {id(o): o for o in self.models}
        for i, m in enumerate(self.models):
            if not m.scripts:
                continue
            current = {id(self.models[j]) for j in neigh.get(i, ())}
            prev = getattr(m, '_colliding', set())
            if current == prev:
                continue
            for cid in current - prev:
                self._call_collision_cb(m, 'on_collision_start', id2m.get(cid))
            for cid in prev - current:
                self._call_collision_cb(m, 'on_collision_end', id2m.get(cid))
            m._colliding = current

    def _collision_pairs_parallel(self, aabbs=None):
        """全部碰撞对 [(i,j), ...] (i<j, 无副作用).
        aabbs: 可选**全量对齐** AABB 列表 (阴影与碰撞共享的那份, 当帧位形) —— 给定则
        直接从 AABB 派生碰撞体数据, 免重算 world matrices + 免变换全部顶点 (播放期
        50 高面数球碰撞曾 ~10ms 的热点). 不给则现算 (直接调用方/测试, 行为不变).
        2026-08-15: 根对象对 (双方 parent=None) 直接判不相关, 免祖先链遍历 (快路径)."""
        models = self.models
        n = len(models)
        cand = [i for i, m in enumerate(models)
                if m.collider is not None and m.collider.enabled
                and m.collider.shape != 'none']
        if len(cand) < 2:
            return []
        bmn = np.zeros((n, 3), dtype=np.float64)
        bmx = np.zeros((n, 3), dtype=np.float64)
        scn = np.zeros((n, 3), dtype=np.float64)
        rad = np.zeros(n, dtype=np.float64)
        kind = np.zeros(n, dtype=np.int64)
        fw = None
        if aabbs is not None:
            for i in cand:
                shape = models[i].collider.shape
                shape, data = self._collider_from_aabb(shape, aabbs[i])
                if shape == 'box':
                    (mn, mx) = data
                    bmn[i] = (mn.x, mn.y, mn.z)
                    bmx[i] = (mx.x, mx.y, mx.z)
                else:
                    (c, r) = data
                    scn[i] = (c.x, c.y, c.z)
                    rad[i] = r
                    kind[i] = 1
        else:
            fw = self.compute_world_matrices(models)   # 当帧当前位形 (直接调用方)
            for i in cand:
                shape, data = self.collider_bounds(models[i], fw[i])
                if shape == 'box':
                    (mn, mx) = data
                    bmn[i] = (mn.x, mn.y, mn.z)
                    bmx[i] = (mx.x, mx.y, mx.z)
                else:
                    (c, r) = data
                    scn[i] = (c.x, c.y, c.z)
                    rad[i] = r
                    kind[i] = 1
        # ---- 候选对生成 (A1 2026-08-29: numpy 化) ----
        # 旧实现: Python 双循环逐对生成 + 每对 is_ancestor 沿父链遍历 —— 与同逻辑
        # C 代码差百倍级 (Nuitka 编译后仍是 Python 对象操作, 见堵点清单 A1)。
        # numpy 化后全部落到 C:
        #   ① triu_indices 一次生成全部 (i<j) 候选对;
        #   ② 祖先判定改用 DFS 区间 (tin/tout), 每对两次比较, 与 _related 语义
        #      逐位一致 (表亲同树但非祖先仍参与碰撞; 根-根对天然不相关 = 旧快路径);
        #   ③ 极端规模 (> _PAIR_GEN_NUMPY_MAX 候选, 约 >2000 碰撞体) 回退原
        #      Python 循环 —— 只防 numpy 内存 (2M 对 ~33MB), 该规模已远超现实场景.
        n_c = len(cand)
        if n_c > self._PAIR_GEN_NUMPY_MAX:
            roots = [m.parent is None for m in models]
            pairs_i, pairs_j = [], []
            for a in range(n_c):
                i = cand[a]
                for b in range(a + 1, n_c):
                    j = cand[b]
                    if roots[i] and roots[j]:
                        pairs_i.append(i)
                        pairs_j.append(j)
                        continue
                    if not self._related(models[i], models[j]):
                        pairs_i.append(i)
                        pairs_j.append(j)
            if not pairs_i:
                return []
            ai = np.array(pairs_i, dtype=np.int64)
            bj = np.array(pairs_j, dtype=np.int64)
        else:
            tin, tout = self._ancestry_ranges(models, getattr(self, '_struct_gen', None))
            tri_i, tri_j = np.triu_indices(n_c, k=1)
            cand_arr = np.asarray(cand, dtype=np.int64)
            ai = cand_arr[tri_i]
            bj = cand_arr[tri_j]
            related = ((tin[ai] <= tin[bj]) & (tin[bj] < tout[ai])) | \
                      ((tin[bj] <= tin[ai]) & (tin[ai] < tout[bj]))
            keep = ~related
            if not keep.any():
                return []
            ai = ai[keep]
            bj = bj[keep]
        n_pairs = len(ai)
        # 一次向量化判定 (numpy 释放 GIL, 数千对内单次调用远快于线程池分块:
        # 压测实测线程池 map 的提交/轮询/GIL 开销 ~15ms/帧 >> 单次 numpy ~50µs).
        # 只有超大碰撞对 (几千物体) 分块丢线程池才有并发收益.
        if n_pairs < self._COLLISION_POOL_PAIRS or self._collision_pool is None:
            mask = GLEngine._pair_overlap_vec(ai, bj, bmn, bmx, scn, rad, kind)
        else:
            pool = self._collision_pool
            nw = pool._max_workers if pool is not None else 1
            chunks = np.array_split(np.arange(n_pairs), max(1, nw * 4))
            res = pool.map(
                lambda idx: GLEngine._pair_overlap_vec(ai[idx], bj[idx],
                                                       bmn, bmx, scn, rad, kind),
                chunks)
            mask = np.concatenate(list(res))
        return [(int(ai[k]), int(bj[k])) for k in np.where(mask)[0]]

    def update_audio(self, dt):
        """M34: 每帧按 AudioSource 组件 playing 状态 play/stop (播放状态变化才操作).
        B2 (2026-08-30): owner=id(组件) —— game-audio 句柄级音量, 同 clip 多组件
        各自独立 (pygame 同 Sound 共享音量, 旧语义下多音量互踩)."""
        for m in self.models:
            a = m.audio_source
            if a is None or not a.clip:
                continue
            key = (a.clip, bool(a.playing))
            if key != a._key:
                if a.playing:
                    self.audio.play(a.clip, a.loop, a.volume, owner=id(a))
                elif a._key is not None:   # 只在曾播放过才 stop (初始/新组件不空停)
                    self.audio.stop(a.clip, owner=id(a))
                a._key = key

    def update_animations(self, dt):
        """M35: 每帧推进动画并插值应用变换 (位置/旋转/缩放)."""
        for m in self.models:
            an = m.animator
            if an is None or not an.playing or not an.current:
                continue
            clip = an.clips.get(an.current)
            if clip is None or not clip.frames:
                continue
            an.time += dt
            s = clip.sample(an.time)
            if 'position' in s:
                m.position = Point3D(*s['position'])
            if 'rotation' in s:
                m.rotation = Point3D(*s['rotation'])
            if 'scale' in s:
                m.set_scale(s['scale'])
            if clip.duration > 0 and an.time >= clip.duration:
                if an.loop:
                    an.time -= clip.duration
                else:
                    an.playing = False

    def _call_collision_cb(self, m, hook, other):
        """调物体上所有脚本的碰撞回调 (坏脚本标记不崩帧)."""
        for sc in m.scripts:
            inst = getattr(sc, '_script', None)
            if inst is None or getattr(sc, '_script_broken', False):
                continue
            fn = getattr(inst, hook, None)
            if fn is None:
                continue
            try:
                fn(other)
            except Exception as e:
                print("[脚本] %s(%s) %s 出错: %r" % (m.name, sc.script_id, hook, e))
                sc._script_broken = True

    # ================ 输入处理 ================
    def apply_orbit_camera(self):
        """轨道相机: 由 target/yaw/pitch/distance 反推眼睛位置, 复用 mat4_view_yaw_pitch.
        ez = (sin yaw cos pitch, sin pitch, cos yaw cos pitch) 为相机前方 (+z_view).
        M41 修复: 开发者轨道相机恒直立 —— 强制 camera_roll=0 (预览倾斜相机/播放还原
        不会把 roll 残留到轨道视角)."""
        self.camera_roll = 0.0       # 不变式: 轨道(开发者)视角 roll 恒 0
        yaw, pitch, dist = self.camera_yaw, self.camera_pitch, self.camera_distance
        ez = (math.sin(yaw) * math.cos(pitch),
              math.sin(pitch),
              math.cos(yaw) * math.cos(pitch))
        t = self.camera_target
        self.camera = Point3D(t[0] - dist * ez[0],
                              t[1] - dist * ez[1],
                              t[2] - dist * ez[2])

    def move_camera(self, delta_time):
        """根据按键状态移动相机"""
        # 2026-08-19: 引擎设置项 cam_speed 倍率 (0.5-2.0, 默认 1.0) ——
        # 编辑器/播放器移速统一受倍率控制 (缓存读取, 设置面板改后更新实例)
        if not hasattr(self, '_cam_speed'):
            try:
                import guiloader
                self._cam_speed = float(guiloader.load_settings('loom').get('cam_speed', 1.0))
            except Exception:
                self._cam_speed = 1.0
        move_speed = self.camera_move_speed * delta_time * self._cam_speed
        sin_yaw = math.sin(self.camera_yaw)
        cos_yaw = math.cos(self.camera_yaw)
        ks = self.key_state
        forward = ks[self._key['CAMERA_FORWARD']]
        backward = ks[self._key['CAMERA_BACKWARD']]
        if forward and not backward:
            self.camera = Point3D(self.camera.x + sin_yaw * move_speed,
                                  self.camera.y,
                                  self.camera.z + cos_yaw * move_speed)
        elif backward and not forward:
            self.camera = Point3D(self.camera.x - sin_yaw * move_speed,
                                  self.camera.y,
                                  self.camera.z - cos_yaw * move_speed)
        left = ks[self._key['CAMERA_LEFT']]
        right = ks[self._key['CAMERA_RIGHT']]
        if left and not right:
            self.camera = Point3D(self.camera.x - cos_yaw * move_speed,
                                  self.camera.y,
                                  self.camera.z + sin_yaw * move_speed)
        elif right and not left:
            self.camera = Point3D(self.camera.x + cos_yaw * move_speed,
                                  self.camera.y,
                                  self.camera.z - sin_yaw * move_speed)
        up = ks[self._key['CAMERA_UP']]
        down = ks[self._key['CAMERA_DOWN']]
        if up and not down:
            self.camera = Point3D(self.camera.x, self.camera.y + move_speed, self.camera.z)
        elif down and not up:
            self.camera = Point3D(self.camera.x, self.camera.y - move_speed, self.camera.z)

    def rotate_camera(self, delta_time):
        """根据按键状态旋转相机视角"""
        rotation_speed = self.camera_rotation_speed * delta_time
        ks = self.key_state
        left = ks[self._key['LOOK_LEFT']]
        right = ks[self._key['LOOK_RIGHT']]
        if left and not right:
            self.camera_yaw -= rotation_speed
        elif right and not left:
            self.camera_yaw += rotation_speed
        up = ks[self._key['LOOK_UP']]
        down = ks[self._key['LOOK_DOWN']]
        if up and not down:
            self.camera_pitch += rotation_speed
        elif down and not up:
            self.camera_pitch -= rotation_speed
        self.camera_pitch = max(-math.pi / 2, min(math.pi / 2, self.camera_pitch))

    def _on_resize(self, w, h):
        """窗口尺寸变化 (拖拽缩放): 更新 GL viewport + 布局.
        不重设窗口 —— SDL 已把 GL drawable 缩放好, 重复 set_mode 只是多闪一次屏."""
        self.width = max(320, int(w))
        self.height = max(240, int(h))
        self.ctx.viewport = (0, 0, self.width, self.height)

    def _desktop_resolution(self):
        """当前桌面分辨率 (主显示器全屏覆盖用).
        优先 GetSystemMetrics (窗口存在与否都返回真桌面尺寸; Info() 在有窗口时
        只返回窗口尺寸, 不可信); 失败回退 init 时抓的 _desktop_size;
        测试用 _desktop_override 固定."""
        if getattr(self, '_desktop_override', None):
            return self._desktop_override
        try:
            import ctypes
            w = ctypes.windll.user32.GetSystemMetrics(0)   # SM_CXSCREEN
            h = ctypes.windll.user32.GetSystemMetrics(1)   # SM_CYSCREEN
            if w > 0 and h > 0:
                return (w, h)
        except Exception:
            pass
        return getattr(self, '_desktop_size', (self.width, self.height))

    def _set_fullscreen(self, fullscreen):
        """F11: 全屏 / 窗口 切换.
        用「无边框窗口铺满桌面分辨率」的假全屏, 不切显示分辨率 (pygame.FULLSCREEN
        独占模式会真实切换显示器分辨率, 触发 GPU 驱动模式切换/可能重置, 还容易把
        GPU 加速的终端窗口一起带崩). SDL 复用同一窗口+GL 上下文 (OPENGL flag 不变)."""
        self.fullscreen = bool(fullscreen)
        if fullscreen:
            w, h = self._desktop_resolution()   # 桌面分辨率 (不改变显示模式)
            flags = pygame.OPENGL | pygame.DOUBLEBUF | pygame.RESIZABLE | pygame.NOFRAME
        else:
            w, h = self.window_size
            flags = pygame.OPENGL | pygame.DOUBLEBUF | pygame.RESIZABLE
        self.width = max(320, int(w))
        self.height = max(240, int(h))
        self.window = pygame.display.set_mode((self.width, self.height), flags)
        self.ctx.viewport = (0, 0, self.width, self.height)
        self._place_fullscreen_window()

    def _toggle_fullscreen(self):
        """F11: 全屏 / 窗口 切换 (假全屏, 不切分辨率)"""
        self._set_fullscreen(not self.fullscreen)

    def _place_fullscreen_window(self):
        """假全屏的窗口定位 (Win32; pygame 不暴露窗口位置/置顶).
        进全屏: 移 (0,0) 铺满 + 置顶盖住任务栏; 退出: 取消置顶 + 恢复原位置.
        全屏前记下窗口矩形, 退出时还原. 失败静默 (非关键路径)."""
        try:
            import ctypes
            from ctypes import wintypes
            hwnd = pygame.display.get_wm_info()['window']
            user32 = ctypes.windll.user32
            SWP_NOSIZE, SWP_NOACTIVATE, SWP_SHOWWINDOW = 0x0001, 0x0010, 0x0040
            if self.fullscreen:
                # 首次进全屏时记住窗口矩形 (退出还原位置用)
                if self._window_rect is None:
                    r = wintypes.RECT()
                    if user32.GetWindowRect(hwnd, ctypes.byref(r)):
                        self._window_rect = (r.left, r.top, r.right, r.bottom)
                # HWND_TOPMOST=-1: 置顶盖住任务栏; 移到 (0,0) 铺满整个桌面
                user32.SetWindowPos(hwnd, -1, 0, 0, self.width, self.height,
                                    SWP_NOACTIVATE | SWP_SHOWWINDOW)
            else:
                # HWND_NOTOPMOST=-2: 取消置顶 + 恢复原位置 (尺寸已由 set_mode 管理)
                x, y = (self._window_rect[0], self._window_rect[1]) if self._window_rect else (0, 0)
                user32.SetWindowPos(hwnd, -2, x, y, 0, 0, SWP_NOSIZE | SWP_NOACTIVATE)
        except Exception:
            pass

    def _handle_events(self):
        """pygame 事件 -> 按键状态/动作.
        嵌入式模式 (Qt 宿主) 不用本方法: 事件由宿主直接写入引擎状态并调钩子."""
        if self._external_ctx:
            return
        # 每帧批处理开始清零瞬时状态 (pressed/released/wheel)
        self.pressed.clear()
        self.released.clear()
        self.mouse_wheel = 0
        # 脚本/游戏输入: 直接读硬件键盘快照 (脚本不依赖事件流, 查询更稳定)
        try:
            _kp = pygame.key.get_pressed()
            self.script_keys = {name: bool(_kp[k]) for name, k in _KEYMAP.items()}
        except Exception:
            self.script_keys = {}
        for ev in pygame.event.get():
            if ev.type == pygame.QUIT:
                if self.on_quit_request():   # 2026-08-13: 退出拦截钩子 (编辑器防丢)
                    self._running = False
            elif ev.type == pygame.VIDEORESIZE:
                if not self.fullscreen:
                    self.window_size = (ev.size[0], ev.size[1])
                self._on_resize(ev.size[0], ev.size[1])
                self.gui_dirty = True                    # 异步GUI: 尺寸变化置脏(FBO 尺寸驱动重建)
            elif ev.type == pygame.KEYDOWN:
                self.gui_dirty = True                    # 异步GUI: 按键置脏 (含被吞掉的按键)
                # F11 全屏切换 (引擎层, 先于 on_key_event 钩子).
                # 编辑器禁 F11 (allow_fullscreen=False): 输入法会把 SDL 窗口误判为
                # 游戏/全屏而隐藏候选框, 且开发场景几乎不用全屏, 干脆关闭, 只留
                # 最大化+自由缩放; 封装游戏 (PlayerApp) 仍允许假全屏 (2026-08-17).
                if self.allow_fullscreen and ev.key == pygame.K_F11:
                    self._toggle_fullscreen()
                    continue
                # on_key_event 钩子: 返回 True 则吞掉 (编辑器输入框/自定义按键)
                if self.on_key_event(ev):
                    continue
                k = ev.key
                if k == self._key['SELECT_NEXT_MODEL']:
                    self.select_next_model()
                elif k in self.key_state:
                    self.key_state[k] = True
            elif ev.type == pygame.KEYUP:
                self.gui_dirty = True                    # 异步GUI: 按键置脏
                k = ev.key
                if self.on_key_event(ev):
                    continue
                if k in self.key_state:
                    self.key_state[k] = False
            elif ev.type == pygame.MOUSEMOTION:
                self.mouse_pos = ev.pos
                if not any(pygame.mouse.get_pressed()):  # 无按键才置脏(轨道/拖动期保持GUI帧)
                    self.gui_dirty = True
            elif ev.type == pygame.MOUSEBUTTONDOWN:
                self.gui_dirty = True                    # 异步GUI: 按下置脏 (面板必消费输入)
                self.mouse_pos = ev.pos
                self.pressed.add(ev.button)
                self.mouse_press_pos[ev.button] = ev.pos
            elif ev.type == pygame.MOUSEBUTTONUP:
                self.gui_dirty = True                    # 异步GUI: 松开置脏
                self.mouse_pos = ev.pos
                self.released.add(ev.button)
                self.mouse_press_pos.pop(ev.button, None)
            elif ev.type == pygame.MOUSEWHEEL:
                self.gui_dirty = True                    # 异步GUI: 滚轮置脏
                self.mouse_wheel = ev.y
            elif ev.type == pygame.TEXTINPUT:
                # IME 合成文本 (2026-08-17): 中文输入法提交的字符经 TEXTINPUT 送达
                # (KEYDOWN.unicode 在 start_text_input 后不再可靠). 交给钩子转发输入框.
                self.gui_dirty = True
                self.on_text_input(ev)
        self.buttons = pygame.mouse.get_pressed()
        self._mods = pygame.key.get_mods()

    def on_key_event(self, ev):
        """按键钩子: 子类可覆写吞掉特定按键 (编辑器输入框). 返回 True = 吞掉."""
        return False

    def on_text_input(self, ev):
        """文本输入钩子 (IME 合成结果, 2026-08-17). 子类(编辑器)转发给视图/输入框.
        默认忽略 (无输入框场景)."""
        return False

    def on_quit_request(self):
        """窗口关闭请求 (QUIT) 钩子 (2026-08-13): 返回 True = 允许退出.
        编辑器覆写为"有未保存改动先询问" (统一防丢)."""
        return True

    # ================ 脚本系统 (M27) + 输入动作层 (M30b) ================
    def _key_pressed(self):
        """按键快照 (每帧): pygame 返回 get_pressed 数组; 嵌入式模式 (Qt 宿主)
        由宿主维护的 512 长数组 (view.key_pressed_array) 提供. 供 _update_camera 等."""
        if getattr(self, '_external_ctx', False):
            view = getattr(self, 'view', None)
            if view is not None and hasattr(view, 'key_pressed_array'):
                return view.key_pressed_array()
            from collections import defaultdict
            return defaultdict(int)   # 特殊键码 (K_LEFT 等) 超 512, 用 dict 防越界
        return pygame.key.get_pressed()

    def is_key(self, name):
        """脚本/游戏输入查询: name 为 _KEYMAP 字符键 ('w'/'space'/'Left'...).
        由 _handle_events 每帧刷新 script_keys; 未刷新过 (无窗口/测试) 返回 False."""
        return bool(self.script_keys.get(name, False))

    def get_action(self, name):
        """输入动作查询 (Unity 动作层): 动作名 -> 绑定的任意键按下即 True.
        默认动作见 DEFAULT_ACTIONS; 键位可在 输入配置.json 重映射 (改键不动脚本).
        未绑定动作时回退为同名键查询 (方便脚本直接写 'w')."""
        for k in self.actions.get(name, (name,)):
            if self.script_keys.get(k, False):
                return True
        return False

    def set_mouse_locked(self, locked):
        """M39 底层: 直接设鼠标锁定状态 (True=隐藏+捕获居中, False=显示+释放).
        嵌入式模式 (Qt 宿主) 转给视图实现 (QOpenGLWidget 光标/捕获), 不碰 pygame."""
        self.mouse_locked = bool(locked)
        if self._external_ctx:
            view = getattr(self, 'view', None)
            if view is not None and hasattr(view, 'set_mouse_locked'):
                view.set_mouse_locked(locked)
            return
        try:
            pygame.event.set_grab(locked)
            pygame.mouse.set_visible(not locked)
        except Exception:
            pass

    def _apply_mouse_lock(self):
        """M39: 按 [特殊场景标志 | 玩家解锁意图] 计算实际鼠标锁定.
        locked = not (ui_capture_mouse or unlock_requested)."""
        self.set_mouse_locked(not (self._ui_capture_mouse or self.mouse_unlock_requested))

    def toggle_mouse_locked(self):
        """M39: Tab 切换玩家解锁意图 (非特殊场景). 特殊场景下强制置为未解锁."""
        if self._ui_capture_mouse:
            self.mouse_unlock_requested = False     # 特殊场景: 玩家解锁意图强制清零
        else:
            self.mouse_unlock_requested = not self.mouse_unlock_requested
        self._apply_mouse_lock()

    def set_ui_capture_mouse(self, capture):
        """M39: 特殊场景 (UI 菜单/暂停等需要鼠标操作) 强制显示鼠标, 并清玩家解锁意图.
        退出特殊场景时解锁意图仍为"未解锁" -> 鼠标正常回锁 (FPS 通用解锁回锁机制):
        非特殊场景解锁 -> 进特殊场景强制回锁 -> 退出特殊场景鼠标回锁, 需再按 Tab 才解锁."""
        self._ui_capture_mouse = bool(capture)
        if capture:
            self.mouse_unlock_requested = False
        self._apply_mouse_lock()

    def _action_bindings_file(self):
        return os.path.join(os.path.dirname(os.path.abspath(__file__)), _ACTION_FILE)

    def _load_action_bindings(self, path=None):
        """从 输入配置.json 加载动作绑定 (坏文件回退默认)."""
        import json as _json
        p = path or self._action_bindings_file()
        try:
            with open(p, 'r', encoding='utf-8') as f:
                data = _json.load(f)
            if isinstance(data, dict) and data.get('actions'):
                self.actions = {a: list(ks) for a, ks in data['actions'].items()}
                # 补新动作 (旧配置缺的新动作用默认)
                for a, ks in DEFAULT_ACTIONS.items():
                    self.actions.setdefault(a, list(ks))
        except Exception:
            self.actions = dict(DEFAULT_ACTIONS)

    def save_action_bindings(self, path=None):
        """保存当前动作绑定到 输入配置.json (供改键 UI 调用)."""
        import json as _json
        p = path or self._action_bindings_file()
        tmp = p + ".tmp"
        with open(tmp, 'w', encoding='utf-8') as f:
            _json.dump({"actions": self.actions}, f, ensure_ascii=False, indent=2)
        os.replace(tmp, p)

    def rebind_action(self, name, keys):
        """重映射动作到一组键名 (如 {'跳跃': ['space','j']}), 并保存配置."""
        self.actions[name] = list(keys)
        self.save_action_bindings()
        return self.actions[name]

    def update_scripts(self, delta_time):
        """播放期每帧调用: 遍历物体上所有脚本组件 (M25: 可多个), 惰性实例化并 update.
        进入播放时 on_start 调一次; 脚本抛异常 -> 打印并标记 broken, 之后跳过.
        (脚本实例缓存在 sc._script, 编辑/退出播放时由调用方清空重建.)"""
        from scripts import get_script
        for m in self.models:
            for sc in m.scripts:              # 组2: 引用迭代 (旧 list() 每物体每帧复制;
                                              # 契约: update 不增删本物体脚本组件)
                if not sc.script_id:
                    sc._script = None
                    sc._script_broken = False
                    continue
                if sc._script_broken:
                    continue
                s = sc._script
                if s is None:
                    cls = get_script(sc.script_id)
                    if cls is None:
                        continue
                    s = cls()
                    s.obj = m
                    s.engine = self
                    for key, _label, default, *_ in cls.params:
                        if key in sc.script_vars:
                            s.vals[key] = sc.script_vars[key]
                    sc._script = s
                    try:
                        s.on_start()
                    except Exception as e:
                        print("[脚本] %s.on_start 出错: %r" % (m.name, e))
                        sc._script = None
                        sc._script_broken = True
                        continue
                try:
                    s.update(delta_time)
                except Exception as e:
                    print("[脚本] %s(%s) 出错: %r" % (m.name, sc.script_id, e))
                    sc._script = None
                    sc._script_broken = True

    def _run_scripts(self, dt):
        """脚本更新分发 (2026-08-14 多核优化): 有专用脚本线程则交给它 (同步等待),
        否则内联 (测试直调 update_scripts / 未启用并行 时行为零变化)."""
        runner = getattr(self, '_script_runner', None)
        if runner is None:
            self.update_scripts(dt)
            return
        try:
            runner.run_frame(self.update_scripts, dt)
        except BaseException:
            # 脚本线程异常/死亡: 回退内联, 游戏不崩 (本帧脚本照跑)
            self.update_scripts(dt)

    def _profile(self, name, fn):
        """LOOM_PROFILE=1 时记录 fn 阶段耗时到 self._stage_times (累计 ms; 诊断 8 核均摊).
        未开 profiling 时零开销直接跑."""
        if os.environ.get('LOOM_PROFILE') != '1':
            return fn()
        t0 = time.time()
        r = fn()
        self._stage_times[name] = self._stage_times.get(name, 0.0) + (time.time() - t0) * 1000.0
        return r

    def _stop_parallel(self):
        """退出清理 (run 循环结束调): 停脚本线程 + 关闭碰撞/预计算线程池. 幂等.
        B1: 物理桥销毁 (Jolt 世界只存活播放/运行期; 幂等, 未建桥时 no-op)."""
        self._destroy_phys_bridge()
        try:
            sr = getattr(self, '_script_runner', None)
            if sr is not None:
                sr.stop()
                self._script_runner = None
        except Exception:
            pass
        for name in ('_collision_pool', '_frame_pool'):
            pool = getattr(self, name, None)
            if pool is not None:
                try:
                    pool.shutdown(wait=False)
                except Exception:
                    pass
                setattr(self, name, None)
        sched = getattr(self, '_main_core_sched', None)
        if sched is not None:
            try:
                sched.stop()
            except Exception:
                pass
            self._main_core_sched = None

    # ================ 渲染 (核心) ================
    def _clear_main_fbo(self, r, g, b, a=1.0):
        """清主渲染目标 (颜色+深度). pygame 与 Qt 外部模式同一路径.
        2026-08-18 关键结论: 之前"ctx.clear 在 Qt 多采样 FBO 无效"是误判 ——
        实际是 moderngl scope 退出把 framebuffer 绑定破坏成 0 (窗口默认 FBO),
        clear 清到了 id 0 所以看不到. 宿主 (qt_view.paintGL) 每帧缓存 widget FBO
        到 _external_fb, 绑定它再 clear 完全有效 (含 depth=1.0 清深度到 far).
        深度每帧清到 far 是物体稳定渲染的前提 (否则深度残留/初始 0 会把物体
        和网格线全部 LESS 剔除: 静止消失/转动闪烁)."""
        if getattr(self, '_external_ctx', False):
            self._screen_fb().use()
            self.ctx.clear(r, g, b, a, depth=1.0)
            return
        self.ctx.clear(r, g, b, a)

    def _screen_fb(self):
        """当前渲染目标 FBO. pygame 模式 = ctx.screen (窗口默认 FBO);
        嵌入式模式 (Qt QOpenGLWidget) = 宿主缓存的 widget FBO (qt_view.paintGL
        每帧开头 detect 并写入 self._external_fb). 2026-08-18 关键: moderngl
        scope 退出会把绑定恢复成 id 0, detect_framebuffer() 只拿"当前绑定"——
        若已被破坏成 0 就画到 0 (不可见). 统一走缓存."""
        if getattr(self, '_external_ctx', False):
            fb = getattr(self, '_external_fb', None)
            return fb if fb is not None else self.ctx.detect_framebuffer()
        return self.ctx.screen

    # ================ A2: 实例化批绘制帧准备 / 主 pass 绘制 ================
    def _prepare_bucket_frame(self):
        """A2 (2026-08-29) 每帧一次: 当帧世界矩阵 f32 化 + 按 mesh 桶重排 +
        桶级实例缓冲写入 (主 pass 96B/实例: world16+sat4+color4; 阴影 64B:
        world16 与主 pass 共享同一批矩阵). 主 pass/阴影 pass 桶序一致,
        两 pass 都只做"每桶一次 draw" (逐物体 uniform+draw 循环已取消).
        组1 (2026-08-30): 消每帧逐物体属性链/hex 解析 (Material._rgba/
        _sat_f32 缓存) + 消每帧 np.zeros 分配 (staging 随桶持久, 原地写)
        + write 零拷贝 (memoryview 切片, 免 tobytes 全量拷贝).
        GC 批 (2026-09-01): _fw32 改持久容量缓冲 (cap>=n, 仅扩容帧分配), f64→f4
        走原地赋值 cast (与 ascontiguousarray 同一 RNE 舍入, 逐位一致); 桶内花式
        索引改 np.take(..., out=持久 gather 缓冲, mode='clip') —— 消每帧
        1×(n,4,4) + 每桶 2×(k,4,4) f4 临时分配; sha 写复用同一份 gather 缓冲
        (主/阴影上传字节与旧路径逐位相同). 消费方一律 [:n]/[:k] 切片读取,
        cap-n 残留行不被消费 (与旧行为一致)."""
        fw = getattr(self, '_frame_world', None)
        if fw is None:
            fw = self.compute_world_matrices(self.models)
            self._frame_world = fw
        # 持久 _fw32: 容量 >= n, 每帧只做一次原地 cast 拷贝 (零分配)
        n = fw.shape[0]
        buf = self._fw32
        if buf is None or buf.shape[0] < n:
            cap = max(64, n) if buf is None else max(n, buf.shape[0] * 2)
            buf = self._fw32 = np.empty((cap, 4, 4), dtype='f4')
        buf[:n] = fw                       # f64→f4 原地 cast (RNE, 与 astype 逐位同)
        fw32 = buf
        buckets = {}
        for i, m in enumerate(self.models):
            if m.visible and m.mesh is not None:
                buckets.setdefault(self._mesh_key(m), []).append(i)
        self._render_buckets = list(buckets.items())
        for key, idxs in buckets.items():
            ent = self._bucket_geo.get(key)
            if ent is None:                    # 防御: 桶资源未建 (attach 路径遗漏)
                ent = self._build_bucket_geo(key, self.models[idxs[0]])
            k = len(idxs)
            self._grow_bucket_inst(key, k)
            inst = self._bucket_inst[key]
            st = inst.get('stage')
            if st is None:                     # 组1: staging 随桶持久 (release 一并清)
                st = inst['stage'] = np.zeros((inst['n'], 24), dtype='f4')
            elif st.shape[0] < k:              # _grow_bucket_inst 已扩容, stage 跟随
                st = inst['stage'] = np.zeros((inst['n'], 24), dtype='f4')
            g = inst.get('gath')               # GC 批: 持久 gather 缓冲 (与 stage 同寿命)
            if g is None:
                g = inst['gath'] = np.empty((inst['n'], 4, 4), dtype='f4')
            elif g.shape[0] < k:
                g = inst['gath'] = np.empty((inst['n'], 4, 4), dtype='f4')
            # mode='clip' 关键: np.take 默认 mode='raise' 时 out 恒被内部缓冲
            # (numpy 文档明示), 照旧分配; 'clip' 才是直写 out. idxs 恒在
            # [0,n) 内 (enumerate 产出), clip 与 raise 结果逐位相同.
            np.take(fw32, idxs, axis=0, out=g[:k], mode='clip')
            st[:k, 0:16] = g[:k].reshape(k, 16)
            models = self.models
            sat_row = st[:k, 16:17]
            col_rows = st[:k, 20:24]
            col_rows[:] = 0.0                  # color=None 的实例留 0 (旧语义)
            for q, i in enumerate(idxs):
                mat = models[i].renderer.material
                sat_row[q, 0] = mat._sat_f32
                r = mat._rgba                  # Material setter 已算; None=网格面色
                if r is not None:
                    col_rows[q] = r
            inst['main'].write(st[:k], 0)      # moderngl 吃 buffer 协议, 部分写入
            inst['sha'].write(g[:k], 0)        # 同一 gather 缓冲 = 旧 _fw32[idxs] 同字节

    def _draw_main_buckets(self):
        """A2: 主 pass 实例化批绘制 —— 每桶一次 draw (旧法: 每物体
        u_model/u_saturation uniform + 单独 draw)."""
        for key, idxs in self._render_buckets:
            ent = self._bucket_geo.get(key)
            if ent is None or ent['vao'] is None:
                continue
            ent['vao'].render(moderngl.TRIANGLES, instances=len(idxs))

    def render(self, delta_time):
        """渲染一帧: 脚本 -> 刚体物理 -> 模型自转(每帧一次) -> 阴影pass -> MVP -> GPU 绘制 -> HUD -> 交换缓冲"""
        # 脚本 (M27): PlayerApp (--run 运行时) 每次渲染都跑脚本 —— 打包的游戏才会动.
        # 编辑器 (EditorApp) 覆写本方法, 只在播放模式调 update_scripts.
        # M32: 鼠标相对移动 (玩家控制器转向用; 有窗口才读, 别消费 GUI 的绝对位置)
        try:
            if not self._external_ctx and pygame.display.get_init():
                self.mouse_rel = pygame.mouse.get_rel()   # 外部模式由宿主喂 mouse_rel
        except Exception:
            self.mouse_rel = (0, 0)
        # 2026-08-16 相机物体化: 挂父激活相机每帧重应用 -> 世界位姿随父移动
        # (Unity 父子语义). 仅挂父相机触发; 根相机/无激活相机行为不变; 脚本在
        # _run_scripts 里后写仍覆盖 (玩家控制器契约不变).
        _cam = self.active_camera_object()
        if _cam is not None and _cam.parent is not None:
            self.apply_camera(_cam)
        # 多核优化 (2026-08-14): 脚本走专用线程 (固定绑预留大核), 同步模型
        self._run_scripts(delta_time)
        # M31: 刚体步进 (碰撞事件延迟到矩阵后与阴影 VP 并行; 直调方仍 events=True)
        self._profile('physics',
                      lambda: self.update_physics(delta_time, events=False))
        # M34: AudioSource 组件播放状态同步
        self.update_audio(delta_time)
        # M35: 动画推进 (关键帧插值应用变换)
        self.update_animations(delta_time)
        # 多核优化: 当帧批量世界矩阵 (脚本/物理已改位形, 阴影与主 pass 共享同一批)
        self._frame_world = self._profile(
            'world_matrices', lambda: self.compute_world_matrices(self.models))
        # 2026-08-15 8 核均摊: 阴影 VP (只读) 与 碰撞检测 (只读) 池上并行重叠,
        # 事件派发回主线程; shadow pass 与 _upload_lights 复用缓存 VP (不重复算包围盒)
        self._profile('shadow_prep',
                      lambda: self._parallel_shadow_and_collision(delta_time,
                                                                  with_events=True))
        # A2: 当帧实例数据准备 (f32 矩阵 + 桶重排 + 桶级实例缓冲写入), 阴影/
        # 主 pass 共享同一批桶 (旧逐物体 uniform/upload 循环已取消)
        # 2026-09-01 组8 插桩: buckets 子阶段 (原未插桩, 残段口径闭合用)
        self._profile('buckets', lambda: self._prepare_bucket_frame())
        # M29: 先画完全部阴影贴图, 主 pass 再采样到物理遮挡
        self._render_shadow_maps()

        self._screen_fb().use()
        self._clear_main_fbo(0.05, 0.05, 0.1, 1.0)
        # MVP: 每帧 CPU 算一次 view_proj, 每模型 model.
        # uniform 上传: matlib 是行向量约定 v@M (numpy M 存的是标准矩阵的转置),
        # 要 GLSL 的 u*v 等价 numpy 的 v@M, GPU 需得 M^T = 行主序 M 直接 tobytes (不转置).
        if self.orbit_mode:
            self.apply_orbit_camera()
        V = mat4_view_yaw_pitch(np, (self.camera.x, self.camera.y, self.camera.z),
                                self.camera_yaw, self.camera_pitch, self.camera_roll)
        P = mat4_perspective(np, self._fov, self.width / self.height, self.near, self.far)
        self._vp = V @ P                                      # 供 draw_lines / 射线拾取
        self.prog['u_view_proj'].write(np.ascontiguousarray(self._vp, dtype='f4').tobytes())
        self._upload_lights()
        self.prog['u_view_pos'].value = (self.camera.x, self.camera.y, self.camera.z)

        self.ctx.enable(moderngl.DEPTH_TEST)
        self.ctx.enable(moderngl.CULL_FACE)
        # A2: 主 pass 实例化批绘制 (桶已在 _prepare_bucket_frame 备好)
        self._draw_main_buckets()

        self._draw_hud()
        if getattr(self, 'ui', None) is not None:
            self.ui.draw()          # M33: 运行时 UI (脚本声明的 HUD/按钮/进度条)
        self._update_fps()
        if not self._external_ctx:      # 外部模式: 宿主 (QOpenGLWidget) 自动交换缓冲
            pygame.display.flip()

    def _draw_hud(self):
        """HUD: 走 draw_text_quad (LRU 文字纹理缓存), 编辑器场景可覆写为不画"""
        lines = self._hud_lines()
        padx, pady, line_h = 10, 10, 24
        for i, text in enumerate(lines):
            self.draw_text_quad(text, padx, pady + i * line_h, (255, 255, 255))

    def _surf_to_tex(self, surf):
        """pygame Surface -> GL 纹理. 关键坑: surfarray 宽在前 (w,h), GL 纹理需
        逐行扫描线 (h,w) -> 先转置再翻转 y (行0=图像底部)."""
        w, h = surf.get_size()
        rgb = pygame.surfarray.array3d(surf)            # (w,h,3)
        alpha = pygame.surfarray.array_alpha(surf)      # (w,h)
        rgba = np.concatenate([rgb, alpha[:, :, None]], axis=2).astype('u1')  # (w,h,4)
        rgba = np.ascontiguousarray(np.transpose(rgba, (1, 0, 2))[::-1])
        tex = self.ctx.texture((w, h), 4, rgba.tobytes())
        tex.filter = (moderngl.LINEAR, moderngl.LINEAR)
        return tex

    def _get_font(self, size):
        """按字号取字体 (缓存, 避免每帧创建)"""
        if size is None:
            return self.font
        f = self._font_cache.get(size)
        if f is None:
            f = self._load_font(size)
            self._font_cache[size] = f
        return f

    def _render_text(self, text, color, size=None):
        """文本渲染 -> Surface. 单字体 (雅黑) 直渲染, 无逐字符回退.
        (2026-08-15: 删除 M40 字体回退 —— 每字符 freetype get_metrics 判定是 CPU 瞬时负载
        源; GUI 符号已全换成雅黑含的字形, 免回退也正常显示.)"""
        return self._get_font(size).render(text, True, color)

    def _measure_text(self, text, size=None):
        """文本尺寸 (供居中/裁剪)"""
        return self._get_font(size).size(text)

    def draw_text_quad(self, text, x, y, color=(255, 255, 255), size=None):
        """
        屏幕像素坐标 (x,y 左上角, pygame y 向下) 画文字.
        LRU 缓存文字纹理; 用 ctx.scope 保存/恢复混合与深度/剔除状态.
        """
        key = (text, color, size)
        item = self._text_cache.pop(key, None)     # 命中则置顶
        if item is None:
            surf = self._render_text(text, color, size)   # 单字体渲染 (M40 逐字符回退已删)
            w, h = surf.get_size()
            tex = self._surf_to_tex(surf)
            item = (tex, w, h)
            while len(self._text_cache) >= self._text_cache_max:
                _, (old_tex, _, _) = self._text_cache.popitem(last=False)
                old_tex.release()
        else:
            tex, w, h = item
        self._text_cache[key] = item

        # 只开混合 (关深度/剔除), scope 退出自动恢复原状态.
        # 坑: 不带 framebuffer 的 scope 会绑默认 FBO(屏幕) 而非当前绑定的离屏目标,
        # 必须把当前 FBO 显式传进去 (moderngl 5.12).
        # 坑2 (2026-08-15): scope(enable_only=BLEND) 会把 GL_SCISSOR_TEST 关掉 -> GUI
        # 文字无视面板/列表 scissor 画出范围 (检查器滚动时顶部文字不消失的根因).
        # 修: 不用 enable_only (保留全部状态含 scissor), 内部显式开混合/关深度/剔除.
        fb = self._screen_fb()   # 2026-08-18: 外部模式用缓存 widget FBO
        _prev_sc = self.ctx.scissor       # g.render 设的裁剪 box (或 None)
        with self.ctx.scope(framebuffer=fb):
            self.ctx.enable(moderngl.BLEND)
            self.ctx.disable(moderngl.DEPTH_TEST)
            self.ctx.disable(moderngl.CULL_FACE)
            # 坑2 (2026-08-15): moderngl scope 会把 GL_SCISSOR_TEST 启用标志重置掉
            # (box 还在但测试关) -> GUI 文字无视面板 scissor 画出范围. 显式重设.
            if _prev_sc is not None:
                self.ctx.scissor = _prev_sc
            else:
                self.ctx.scissor = None
            tex.use(0)
            self.hud_prog['u_tex'].value = 0
            self.hud_prog['u_color'].value = (1.0, 1.0, 1.0, 1.0)   # M33: 防纯色矩形染色残留
            ox = 2.0 * x / self.width - 1.0               # NDC x 左
            oy = 1.0 - 2.0 * (y + h) / self.height        # NDC y 底
            sx = 2.0 * w / self.width
            sy = 2.0 * h / self.height
            self.hud_prog['u_origin'].value = (ox, oy)
            self.hud_prog['u_size'].value = (sx, sy)
            self._quad_vao.render(moderngl.TRIANGLES)

    def draw_screen_rect(self, rect, color):
        """M33: 屏幕像素填充矩形 (运行时 UI 用). rect=(x,y,w,h) 左上角, color=(r,g,b) 0..255."""
        x, y, w, h = rect
        if w <= 0 or h <= 0:
            return
        fb = self._screen_fb()   # 2026-08-18: 外部模式用缓存 widget FBO
        with self.ctx.scope(framebuffer=fb, enable_only=moderngl.BLEND):
            self._hud_white_tex.use(0)
            self.hud_prog['u_tex'].value = 0
            self.hud_prog['u_color'].value = (
                color[0] / 255.0, color[1] / 255.0, color[2] / 255.0, 1.0)
            self.hud_prog['u_origin'].value = (2.0 * x / self.width - 1.0,
                                               1.0 - 2.0 * (y + h) / self.height)
            self.hud_prog['u_size'].value = (2.0 * w / self.width,
                                             2.0 * h / self.height)
            self._quad_vao.render(moderngl.TRIANGLES)

    def blit_texture(self, tex):
        """异步GUI: 全屏混合离屏 GUI 纹理到屏幕 (面板 FBO 合成). tex 须 = engine 尺寸.
        方向已核验: rect shader 顶部内容在高 NDC y, blit 的 v_uv=0 在底部顶点, 无需翻转."""
        if tex is None:
            return
        try:
            with self.ctx.scope(framebuffer=self._screen_fb(), enable_only=moderngl.BLEND):
                tex.use(0)
                self.hud_prog['u_tex'].value = 0
                self.hud_prog['u_color'].value = (1.0, 1.0, 1.0, 1.0)   # 防纯色矩形染色残留
                self.hud_prog['u_origin'].value = (-1.0, -1.0)
                self.hud_prog['u_size'].value = (2.0, 2.0)
                self._quad_vao.render(moderngl.TRIANGLES)
        except Exception:
            pass

    def _hud_lines(self):
        """HUD 文本行 (与旧 turtle 版 _draw_hud 一致)"""
        m = self.get_current_model()
        yaw_deg = 360 - math.degrees(self.camera_yaw) % 360
        pitch_deg = math.degrees(self.camera_pitch)
        total_faces = sum(len(x.mesh.faces) for x in self.models)
        if not self._external_ctx and pygame.key.get_focused():
            if m is not None:
                model_line = (f"模型 {self.current_model_index + 1}/{len(self.models)}: "
                              f"位置=({m.position.x:.2f}, {m.position.y:.2f}, "
                              f"{m.position.z:.2f}) | FPS: {self.fps} | 三角形: {total_faces}")
                rot_line = (f"旋转角度: X:{math.degrees(m.rotation.x):.1f}° "
                            f"Y:{math.degrees(m.rotation.y):.1f}° "
                            f"Z:{math.degrees(m.rotation.z):.1f}°")
            else:
                model_line = "模型: (无)"
                rot_line = "旋转角度: (无)"
            lines = [
                f"相机位置: ({self.camera.x:.2f}, {self.camera.y:.2f}, {self.camera.z:.2f}) | "
                f"视角: 偏航角={yaw_deg:.1f}°, 俯仰角={pitch_deg:.1f}°",
                model_line,
                rot_line,
                "渲染后端: OpenGL (moderngl) | 硬件深度测试 + 背面剔除",
                "切换模型: Tab",
                "相机移动: W-前, S-后, A-左, D-右, Q-上, E-下 | "
                "视角控制: 方向键",
            ]
        else:
            # 窗口没键盘焦点时按键无效 -> 用醒目提示引导点击窗口
            lines = [
                "!!! 窗口未激活: 请点击本窗口后再按按键 !!!",
                " (点击窗口使其获得键盘焦点; 若仍无效请切换输入法为英文)",
            ]
        return lines

    def _update_fps(self):
        """每秒更新一次 FPS"""
        self.frame_count += 1
        now = time.time()
        if now - self.last_time >= 1.0:
            self.fps = self.frame_count
            self.frame_count = 0
            self.last_time = now

    # ================ 主循环 ================
    def run(self):
        """主运行循环. 嵌入式模式 (Qt 宿主) 由宿主驱动渲染, 不进入本循环."""
        if self._external_ctx:
            print("[engine] 嵌入式模式: 主循环由宿主驱动, 忽略 run()")
            return
        self._running = True
        clock = pygame.time.Clock()
        self.last_frame_time = time.time()
        while self._running:
            self._handle_events()
            now = time.time()
            delta_time = min(now - self.last_frame_time, 0.1)  # 防窗口拖动时 dt 过大
            self.last_frame_time = now
            self.move_camera(delta_time)
            self.rotate_camera(delta_time)
            self.render(delta_time)
            clock.tick(120)   # 限帧 120 (受 vsync 影响, 通常 60)
        self._stop_parallel()          # 多核优化: 停脚本线程/碰撞池
        # B2 (2026-08-30): 音频后端 shutdown —— miniaudio 设备线程不关会挂死进程
        # (pygame.mixer 无此问题, 但 shutdown 幂等对两种情况都安全)
        try:
            self.audio.shutdown()
        except Exception:
            pass
        pygame.quit()
