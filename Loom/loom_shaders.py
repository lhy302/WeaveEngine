# -*- coding: utf-8 -*-
"""loom_shaders.py — 从 engine.py 抽取的全部 GLSL 着色器源码常量。

原属 engine.py 45–307 行（着色器定义段）。纯字符串常量，零运行时依赖。
engine.py 通过 `from loom_shaders import *` 重新导出这些名字，
以保持既有 `from engine import _VERT_SRC` 之类的引用完全兼容。
"""

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
in vec2 in_uv;   // M36 贴图: 逐顶点 UV
uniform mat4 u_view_proj;
out vec4 v_color;
out vec3 v_normal;
out vec3 v_world_pos;
out float v_sat;
out vec2 v_uv;
void main() {
    mat4 u_model = mat4(a_w0, a_w1, a_w2, a_w3);
    vec4 world = u_model * vec4(in_pos, 1.0);
    gl_Position = u_view_proj * world;
    // 法线变换: 逆转置 (正确处理非等比缩放; 等比缩放时等价 R*n)
    v_normal = transpose(inverse(mat3(u_model))) * in_normal;
    v_world_pos = world.xyz;
    v_color = (a_col.w > 0.5) ? vec4(a_col.rgb, 1.0) : in_color;
    v_sat = a_sat.x;
    v_uv = in_uv;
}"""

_FRAG_SRC = """#version 330
in vec4 v_color;
in vec3 v_normal;
in vec3 v_world_pos;
// M36 PBR (2026-10-14): (metallic, roughness, pbr_flag)。全局 u_pbr_mode 与逐实例
// v_pbr.z 双门控 —— 默认(0)走原 Blinn-Phong 逐位不变 (向后兼容)。
uniform float u_pbr_mode;          // 全局 PBR 开关 (0=Blinn-Phong, 1=允许 PBR)
uniform float u_metallic;          // 材质金属度 (每桶 uniform, 对标 Unity Metallic)
uniform float u_roughness;         // 材质粗糙度 (对标 Unity Smoothness 的反相)
uniform float u_material_pbr;      // 材质 PBR 开关 (>0.5=该材质用 PBR)
// M36 环境反射 (对标 Unity Reflection Probe / Cubemap): 有 env 时替代环境光项
uniform samplerCube u_env;
uniform float u_has_env;           // 0=无 env (走原 ambient), 1=有
uniform float u_env_max_lod;       // cubemap mip 级数 (粗糙度选级用)
// M36 贴图: 颜色贴图 (albedo) 采样。无贴图材质绑 1x1 白纹理 (乘白=原色, 视觉不变)。
in vec2 v_uv;
uniform sampler2D u_albedo;
// M36 法线贴图: 切线空间法线 (导数法 TBN, 无需预计算切线)。
uniform sampler2D u_normal_map;
uniform float u_has_normal_map;    // 0=无 (跳过整段), 1=有
// 多光源 (最多 8 个): 平行光 / 点光源, 场景光源由用户手动添加 (无默认光源)
const int MAX_LIGHTS = 8;
uniform int u_light_count;
uniform vec3 u_light_dir[MAX_LIGHTS];    // 平行光/聚光灯行进方向 (点光源置 0)
uniform vec3 u_light_pos[MAX_LIGHTS];    // 点光/聚光灯位置 (平行光置 0)
uniform vec3 u_light_color[MAX_LIGHTS];
uniform float u_light_intensity[MAX_LIGHTS];
uniform float u_light_kind[MAX_LIGHTS];  // 0=平行光, 1=点光源, 2=聚光灯
uniform float u_light_range[MAX_LIGHTS]; // 点光/聚光灯影响半径 (对齐 Unity Light.range; 平行光忽略)
// 2026-10-19 第1档序9 聚光灯: 内外锥角余弦 (避免每片元 cos 计算; Python 侧上传算好)
uniform float u_light_spot_inner[MAX_LIGHTS];  // 聚光灯内锥 cos(inner_angle)
uniform float u_light_spot_outer[MAX_LIGHTS];  // 聚光灯外锥 cos(outer_angle)
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

// ---- M36 PBR (Cook-Torrance): GGX 分布 + Smith 几何 + Schlick 菲涅尔 ----
float _d_ggx(vec3 N, vec3 H, float rough) {
    float a = rough * rough;
    float a2 = a * a;
    float NdotH = max(dot(N, H), 0.0);
    float d = NdotH * NdotH * (a2 - 1.0) + 1.0;
    return a2 / max(3.14159265 * d * d, 1e-7);
}
float _g_smith(vec3 N, vec3 V, vec3 L, float rough) {
    float r = rough + 1.0;
    float k = (r * r) / 8.0;
    float NdotV = max(dot(N, V), 0.0);
    float NdotL = max(dot(N, L), 0.0);
    float gv = NdotV / (NdotV * (1.0 - k) + k);
    float gl = NdotL / (NdotL * (1.0 - k) + k);
    return gv * gl;
}
vec3 _f_schlick(float cosT, vec3 F0) {
    return F0 + (1.0 - F0) * pow(clamp(1.0 - cosT, 0.0, 1.0), 5.0);
}
// PBR 单光源贡献 (radiance=光色*强度*衰减*阴影, albedo=底色, metal/rough=材质)
vec3 pbr_light(vec3 N, vec3 V, vec3 L, vec3 radiance, vec3 albedo,
               float metal, float rough, float NdotL) {
    vec3 H = normalize(V + L);
    vec3 F0 = mix(vec3(0.04), albedo, metal);
    float D = _d_ggx(N, H, rough);
    float G = _g_smith(N, V, L, rough);
    float NdotV = max(dot(N, V), 1e-4);
    vec3 F = _f_schlick(max(dot(H, V), 0.0), F0);
    vec3 spec = (D * G * F) / max(4.0 * NdotL * NdotV, 1e-4);
    vec3 kD = (1.0 - F) * (1.0 - metal);
    vec3 diff = kD * albedo / 3.14159265;
    return (diff + spec) * radiance * NdotL;
}

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
    // M36 法线贴图: 导数法 TBN (从世界位置与 UV 的屏幕空间导数解切线/副切线,
    // 免预计算切线)。无贴图 (u_has_normal_map=0) 整段跳过, 零开销。
    if (u_has_normal_map > 0.5) {
        vec3 dp1 = dFdx(v_world_pos);
        vec3 dp2 = dFdy(v_world_pos);
        vec2 duv1 = dFdx(v_uv);
        vec2 duv2 = dFdy(v_uv);
        float det = duv1.x * duv2.y - duv2.x * duv1.y;
        if (abs(det) > 1e-8) {
            vec3 T = normalize((dp1 * duv2.y - dp2 * duv1.y) / det);
            vec3 B = normalize((dp2 * duv1.x - dp1 * duv2.x) / det);
            T = normalize(T - n * dot(n, T));      // Gram-Schmidt 正交化
            B = cross(n, T);
            vec3 nm = texture(u_normal_map, v_uv).rgb * 2.0 - 1.0;
            n = normalize(mat3(T, B, n) * nm);
        }
    }
    vec3 v = normalize(u_view_pos - v_world_pos);
    // M36 PBR: 底色提前算 (Blinn-Phong 与 PBR 共用)
    vec3 base = v_color.rgb * texture(u_albedo, v_uv).rgb;
    bool use_pbr = (u_pbr_mode > 0.5) && (u_material_pbr > 0.5);
    float metal = clamp(u_metallic, 0.0, 1.0);
    float rough = clamp(u_roughness, 0.04, 1.0);
    vec3 pbr_acc = vec3(0.0);
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
            // 点光源 / 聚光灯: 位置 + 距离衰减 + range 截断 (对齐 Unity Light.range)
            vec3 to_l = u_light_pos[i] - v_world_pos;
            float dist = length(to_l);
            l = to_l / max(dist, 1e-4);
            diff = max(dot(n, l), 0.0);
            atten = 1.0 / (1.0 + 0.09 * dist + 0.045 * dist * dist);
            // range 边缘平滑衰减到 0 (Unity 点光超出 range 不照亮)
            float rng = max(u_light_range[i], 1e-3);
            float fade = clamp(1.0 - (dist * dist) / (rng * rng), 0.0, 1.0);
            atten *= fade * fade;
            // 2026-10-19 第1档序9 聚光灯: 锥角衰减（内锥全亮, 内→外线性衰减, 外锥外 0）
            if (u_light_kind[i] > 1.5) {
                vec3 spot_dir = normalize(u_light_dir[i]);   // 光源照射方向 (从光源指向场景)
                vec3 frag_dir = -to_l / max(dist, 1e-4);      // 光源->片元方向
                float cos_theta = dot(frag_dir, spot_dir);
                float inner = u_light_spot_inner[i];          // cos(inner_angle)
                float outer = u_light_spot_outer[i];          // cos(outer_angle)
                float spot_atten = clamp((cos_theta - outer) / max(inner - outer, 1e-4), 0.0, 1.0);
                atten *= spot_atten;
            }
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
        vec3 radiance = u_light_color[i] * u_light_intensity[i] * atten * sh;
        if (use_pbr) {
            pbr_acc += pbr_light(n, v, l, radiance, base, metal, rough, diff);
        }
        acc += u_light_color[i] * u_light_intensity[i] * (0.60 * diff + 0.25 * spec) * atten * sh;
    }
    // 边缘光 (菲涅尔近似): 法线越偏离视线越亮, 强化轮廓边缘
    float rim = 0.12 * pow(1.0 - max(dot(n, v), 0.0), 3.0);
    // M36 PBR 二选一: 全局+材质双门控; 未启时走原 Blinn-Phong (逐位不变)
    vec3 col;
    if (use_pbr) {
        if (u_has_env > 0.5) {
            // M36 环境反射: 漫反射=法线方向采样 × base×(1-metal);
            // 镜面=反射向量采样 (粗糙度选 mip 级) × 菲涅尔 F0 (粗糙度调高光衰减)
            vec3 F0 = mix(vec3(0.04), base, metal);
            vec3 R = reflect(-v, n);
            vec3 spec_env = textureLod(u_env, R, rough * u_env_max_lod).rgb * F0;
            vec3 diff_env = texture(u_env, n).rgb * base * (1.0 - metal);
            col = pbr_acc + diff_env + spec_env + vec3(rim);
        } else {
            vec3 amb_pbr = base * ambient * (1.0 - metal);   // 金属无漫反射环境项
            col = pbr_acc + amb_pbr + vec3(rim);
        }
    } else {
        // 光照系数压到 max≈0.9 预 gamma: 避免纯色(如 #FF5555 的 R=1.0)直接爆白,
        // 顶面/侧面在亮度上拉开可辨差距 (否则相邻面又分不出边缘)
        col = base * (ambient + acc) + vec3(rim);
    }
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
