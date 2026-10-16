# -*- coding: utf-8 -*-
"""loom_scene_entities.py — 场景实体状态类与运行时 UI。

原属 engine.py（"光源状态" + CameraState + RuntimeUI 段）。
内容：
  wrap_deg / direction_to_angles（角度工具）
  LightState（光源实体）
  CameraState（摄像机实体）
  RuntimeUI（M33 运行时 HUD UI；通过 self.engine 反向调用引擎绘制接口）
依赖：math / uuid / loom_types.Point3D。
engine.py 通过 `from loom_scene_entities import *` 重导出。
"""

import math
import uuid

from loom_types import Point3D


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
                 azimuth=None, elevation=None, roll=None, range=10.0):
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
        # 点光源范围 (对齐 Unity Light.range, 默认 10): 超出此距离的光照衰减到 0
        self.range = float(range)
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

    def __init__(self, position=None, yaw=0.0, pitch=0.0, roll=0.0, fov=60.0,
                 fov_locked=True, name=None, guid=None,
                 pitch_lock=False, pitch_min=-85.0, pitch_max=85.0):
        # 默认位置 (0,1,-10) 对齐 Unity 新建 Camera
        self.position = Point3D(*position) if position is not None else Point3D(0, 1, -10)
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
