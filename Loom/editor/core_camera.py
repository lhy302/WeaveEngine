# -*- coding: utf-8 -*-
"""editor/core_camera.py — 相机视图状态：投影三件套、轨道视角命令、场景相机应用、相机深度、聚焦动画。

Q-B7-38-1 第 9 批（agent-99）：editor/core.py 按能力域拆分的**纯搬迁**产物 ——
类体成员从 editor/core.py 的 _EditorCore 逐字搬入本 mixin（方法体一行未改）；
装配见 editor/core.py 的 _EditorCore(EngineCore, <各域 mixin> ...)。

我负责：相机视图状态：投影三件套、轨道视角命令、场景相机应用、相机深度、聚焦动画。
我不负责：开发者视角鼠标泵 _update_camera（core.py：def 唯一性门 + 滚轮公式/±1.55 文本门）。
mixin 之间只经 self 互调（装配后同一个实例），互不 import。
"""
from editor.core_commands import _CameraProjCommand, _OrbitViewCommand
import math
import time
import sceneio

class EditorCameraMixin(object):
    """相机视图状态：投影三件套、轨道视角命令、场景相机应用、相机深度、聚焦动画（纯搬迁）。"""

    # ---- 相机投影三件套（D7=A: 场景相机属性 -> 脏判定 / 撤销 / 播放前后恒等） ----
    def _camera_proj_state(self):
        """当前投影状态 {'ortho','ortho_size','fov'(度)}（值已归一）。"""
        return {'ortho': bool(getattr(self, 'ortho', False)),
                'ortho_size': sceneio.norm_ortho_size(
                    getattr(self, 'ortho_size', None), '编辑器 ortho_size'),
                'fov': sceneio.norm_fov_deg(
                    math.degrees(float(getattr(self, '_fov', math.radians(60.0)))),
                    '编辑器 fov')}

    def _camera_proj_from(self, cam):
        """从场景 camera 段取归一后的投影状态（非法值出声后钳制/回落）。"""
        if not isinstance(cam, dict):
            return self._camera_proj_state()
        return {'ortho': sceneio._b_strict(cam.get('ortho'), False,
                                          '场景 camera.ortho'),
                'ortho_size': sceneio.norm_ortho_size(cam.get('ortho_size'),
                                                      '场景 camera.ortho_size'),
                'fov': sceneio.norm_fov_deg(cam.get('fov'), '场景 camera.fov')}

    def _apply_camera_proj(self, proj):
        """把投影状态写进引擎（**唯一赋值点**：加载/播放还原/撤销都走这里）。"""
        self.ortho = bool(proj.get('ortho', False))
        self.ortho_size = sceneio.norm_ortho_size(proj.get('ortho_size'),
                                                  '相机投影 ortho_size')
        self._fov = math.radians(sceneio.norm_fov_deg(proj.get('fov'),
                                                      '相机投影 fov'))

    def set_camera_projection(self, ortho=None, ortho_size=None, fov=None):
        """改主相机投影（**进脏判定 + 进撤销**；裁决 D7=A）。

        EAI 命令 camera_proj / 未来相机面板都应走本方法 —— 直接写 self.ortho 会绕过
        撤销栈，也让"改了但没保存"无法被撤销回去。None = 该项不变。
        返回改后的 {'ortho','ortho_size','fov'}。
        """
        before = self._camera_proj_state()
        after = dict(before)
        if ortho is not None:
            after['ortho'] = sceneio._b_strict(ortho, before['ortho'],
                                               'camera_proj.ortho')
        if ortho_size is not None:
            after['ortho_size'] = sceneio.norm_ortho_size(ortho_size,
                                                          'camera_proj.size')
        if fov is not None:
            after['fov'] = sceneio.norm_fov_deg(fov, 'camera_proj.fov')
        if after != before:
            self.undo.push(_CameraProjCommand(self, before, after))
        else:
            self._apply_camera_proj(after)
        return self._camera_proj_state()

    # ---- 开发者轨道相机视角 (Q-B7-56-1 裁定②, 2026-11-22) ----
    def _orbit_view_state(self):
        """轨道相机视角四元组快照 (与 _apply_orbit_view 成对)."""
        return {'target': tuple(float(v) for v in self.camera_target),
                'distance': float(self.camera_distance),
                'yaw': float(self.camera_yaw),
                'pitch': float(self.camera_pitch)}

    def _apply_orbit_view(self, state):
        """把视角快照写回 (undo/redo 与 set_orbit_view 共用同一条赋值路径)."""
        t = state['target']
        self.camera_target = (float(t[0]), float(t[1]), float(t[2]))
        self.camera_distance = float(state['distance'])
        self.camera_yaw = float(state['yaw'])
        self.camera_pitch = float(state['pitch'])

    def set_orbit_view(self, target=None, distance=None, yaw=None, pitch=None):
        """改开发者轨道相机视角（**进撤销栈**；Q-B7-56-1 裁定② 2026-11-22）。

        EAI 命令 camera_move / camera_look 应走本方法 —— 直接写 self.camera_target
        等会绕过撤销栈，命令行转的视角/移动撤不回（与 camera_proj / 裁决 D7=A
        同病同修）。None = 该项不变；pitch 钳制 [-1.55, 1.55] 与 cmd_camera_look
        旧实现一致。视角是编辑器视图状态（_scene_digest 不含它）：进撤销栈但
        **不进场景脏判定**（对齐 camera_proj 先例：只有投影三件套进脏判定）。
        GUI 右键轨道 / WASDQE 老链路**不走这里**（裁定②: 连贯性操作不进栈）。
        返回改后的 {'target','distance','yaw','pitch'}（yaw/pitch 弧度）。
        """
        before = self._orbit_view_state()
        if target is not None:
            self.camera_target = (float(target[0]), float(target[1]),
                                  float(target[2]))
        if distance is not None:
            self.camera_distance = float(distance)
        if yaw is not None:
            self.camera_yaw = float(yaw)
        if pitch is not None:
            self.camera_pitch = max(-1.55, min(1.55, float(pitch)))
        after = self._orbit_view_state()
        if after != before:
            # push 会先 do()（再走一遍 _apply_orbit_view, 幂等）—— 与
            # set_camera_projection 同一款"先写后 push"模式。
            self.undo.push(_OrbitViewCommand(self, before, after))
        return after

    def _camera_depth(self, cam):
        """摄像机挂父链深度 (层级树缩进用, 相机物体化 2026-08-16)."""
        depth = 0
        cur = cam.parent
        while cur is not None:
            depth += 1
            cur = cur.parent
        return depth

    def _apply_camera(self, cam):
        self.camera_target = tuple(cam.get('target', [0, 0, 0]))
        # 2026-11-08 批2 (D7=A / P-03-03/04/06): 投影三件套走 sceneio 的**唯一**归一实现
        # （与 scene_from_dict / scene_driver.load_from_data 同一出处）：
        # 非法类型出声后钳制/回落，不再 bool('false')=True，也不再 float('abc') 抛异常。
        proj = self._camera_proj_from(cam)
        self._apply_camera_proj(proj)
        # 2026-11-06 R-03: 场景恢复同样在入口钳制 (与 Vk 后端一致)
        from loom_camera import clamp_camera_distance
        self.camera_distance = clamp_camera_distance(cam.get('distance', 10.0))
        self.camera_yaw = cam.get('yaw', 0.6)
        # 2026-08-18: pitch 恢复时 clamp 到俯视范围 [-1.55, 0] —— 网格是 XZ 平面
        # 线框, 仰视/平视时全部在视锥外 (几何上不可见). 用户上次保存的仰视姿态
        # 恢复后编辑器打开即"无网格", 转动时才闪出 (实测根因之一). 运行时拖动
        # 仍可仰视 (编辑自由度), 仅恢复路径修正.
        self.camera_pitch = max(-1.55, min(0.0, cam.get('pitch', -0.35)))
        # 2026-11-07: 记录场景相机 (播放时强制套用, 不让编辑态拖动后的视角带进播放)
        self._scene_cam = dict(cam)

    # ================ 相机聚焦 (2026-11-07 C: Agent 操作必须看得见) ================
    FOCUS_DURATION = 0.18          # 平滑聚焦时长 (秒, 线性插值)

    FOCUS_DISTANCE_FACTOR = 2.6    # camera_distance = 包围球半径 * 系数

    def _focus_aabb(self, index):
        """第 index 个物体的世界 AABB (当帧世界矩阵; 失败回 None).

        世界矩阵走 compute_world_matrices (与 render 同源, 静止时有缓存);
        单个物体 get_bounding_box 失败时回 None, 聚焦命令转成错误而不是崩.
        """
        try:
            fw = self.compute_world_matrices(self.models)
            return self.get_bounding_box(self.models[index], fw[index])
        except Exception:
            try:
                return self.get_bounding_box(self.models[index])
            except Exception:
                return None

    def focus_on_object(self, index, smooth=True):
        """把轨道相机对准第 index 个物体 (EAI view_focus / 自动聚焦).

        camera_target = 世界 AABB 中心; camera_distance = 包围球半径 *
        FOCUS_DISTANCE_FACTOR (保持 yaw/pitch 不变). smooth=True 时记录
        _focus_anim, 由 render/_update_camera 在 ~180ms 内线性插值; 逻辑值
        先落目标值, 任何即时读取都看到最终结果. 播放态不移动编辑器相机
        (不动播放相机), 返回 False.

        2026-11-08 批4 (P-04-10): 失败原因写进 self._focus_fail
        ('playing' / 'bad_index' / 'no_aabb'), 让 EAI view_focus 能给出**不同**
        的 error —— 旧实现在编辑态取不到包围盒时也报"播放态不能移动编辑器相机",
        把排查方向带偏。
        """
        self._focus_fail = None
        if getattr(self, 'is_playing', False):
            self._focus_fail = 'playing'
            return False
        try:
            index = int(index)
        except (TypeError, ValueError):
            self._focus_fail = 'bad_index'
            return False
        if not 0 <= index < len(self.models):
            self._focus_fail = 'bad_index'
            return False
        box = self._focus_aabb(index)
        if box is None:
            self._focus_fail = 'no_aabb'
            return False
        mn, mx = box
        if mn is None or mx is None:
            self._focus_fail = 'no_aabb'
            return False
        target = ((mn.x + mx.x) * 0.5, (mn.y + mx.y) * 0.5,
                  (mn.z + mx.z) * 0.5)
        dx, dy, dz = (mx.x - mn.x), (mx.y - mn.y), (mx.z - mn.z)
        radius = 0.5 * math.sqrt(dx * dx + dy * dy + dz * dz)
        try:
            from loom_camera import clamp_camera_distance
            dist = clamp_camera_distance(radius * self.FOCUS_DISTANCE_FACTOR)
        except Exception:
            dist = max(0.5, min(1000.0, radius * self.FOCUS_DISTANCE_FACTOR))
        from_target = tuple(self.camera_target)
        from_dist = float(self.camera_distance)
        self.camera_target = target
        self.camera_distance = dist
        if smooth and self.FOCUS_DURATION > 0:
            self._focus_anim = {
                't0': time.perf_counter(),
                'dur': float(self.FOCUS_DURATION),
                'from_target': from_target,
                'to_target': target,
                'from_distance': from_dist,
                'to_distance': dist,
            }
        else:
            self._focus_anim = None
            self.apply_orbit_camera()      # 无动画: 立即把 camera 摆到新位姿
        return True

    def _cancel_focus_anim(self):
        """用户主动操作相机 / 新聚焦 -> 丢弃进行中的插值动画."""
        self._focus_anim = None

    def _advance_focus_anim(self, now=None):
        """推进聚焦插值 (render/_update_camera 每拍调). 返回是否仍在动画中."""
        anim = getattr(self, '_focus_anim', None)
        if not anim:
            return False
        now = time.perf_counter() if now is None else float(now)
        dur = float(anim.get('dur') or 0.0)
        p = 1.0 if dur <= 0 else (now - anim['t0']) / dur
        if p >= 1.0:
            self.camera_target = anim['to_target']
            self.camera_distance = anim['to_distance']
            self._focus_anim = None
            return False
        p = max(0.0, p)
        a, b = anim['from_target'], anim['to_target']
        self.camera_target = (a[0] + (b[0] - a[0]) * p,
                              a[1] + (b[1] - a[1]) * p,
                              a[2] + (b[2] - a[2]) * p)
        self.camera_distance = (anim['from_distance']
                                + (anim['to_distance'] - anim['from_distance']) * p)
        return True
