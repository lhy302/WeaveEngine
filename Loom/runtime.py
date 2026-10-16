# -*- coding: utf-8 -*-
"""
runtime.py — Player 运行时 (M17: 引擎/编辑器分层)

PlayerApp 只依赖引擎 + sceneio, 不 import 编辑器: 加载场景文件即渲染。
打包版可只带运行时 (编辑器 UI 不打包), exe 更小、无编辑功能。
Loom.py / build_entry.py 的 --run <scene.json> 都从这里启动。
2026-08-22 发布链路 (Unity Build 对齐): 支持 scene_data 直接喂字典
(游戏包.lsc 解包产物, 场景不出明文) + title (玩家窗口标题 = 游戏名).
"""
import json

import pygame                     # 仅 set_caption (引擎已初始化 pygame)
from engine import GLEngine, gc_play_enter, gc_play_exit, engine_gc_frozen
import sceneio


class PlayerApp(GLEngine):
    """只读场景播放器: 无编辑器 UI, 轨道相机 + 默认引擎键位."""

    def __init__(self, scene_path=None, width=1280, height=800,
                 scene_data=None, title=None):
        super().__init__(width, height)
        for m in list(self.models):
            self.remove_model(m)                 # 清默认场景
        if title:
            pygame.display.set_caption(title)    # 玩家窗口标题 = 游戏名
        cam_out = {}
        # M38: load_scene_data (明文 JSON 与 LOOMSC 混淆场景自动解密);
        # 2026-08-22: scene_data 为游戏包解包产物时直接使用 (场景不出明文).
        if scene_data is not None:
            data = scene_data
        else:
            data = sceneio.load_scene_data(scene_path) if scene_path else None
        if not isinstance(data, dict):
            raise ValueError("无法加载场景: %s" % scene_path)
        sceneio.scene_from_dict(self, data, camera_out=cam_out)
        if cam_out:
            self.camera_target = cam_out['target']
            self.camera_distance = cam_out['distance']
            self.camera_yaw = cam_out['yaw']
            self.camera_pitch = cam_out['pitch']
        # 玩家视角: 场景 active_camera (Unity Camera) 优先, 否则默认轨道相机
        cam = self.active_camera_object()
        if cam is not None:
            self.apply_camera(cam)
        else:
            self.orbit_mode = True
            self.apply_orbit_camera()
        # M39: 播放器默认锁定鼠标 (隐藏+捕获, 第一/第三人称玩家控制器转视角用);
        # 玩家按 Tab 释放/回锁 (释放后鼠标滑动不转视角), 退出用窗口关闭.
        self.set_mouse_locked(True)
        # 分离批2: 首帧快照对齐 (加载位姿=curr, 首渲染帧不插值)
        if getattr(self, '_interp', None) is not None:
            self._interp.advance()
            self._interp.align()
        self._render_world = None
        if hasattr(self, '_prep_sig'):
            self._prep_sig = None           # 批5: prep 缓存强制失效
            self._disp_gen = -1
        clk = getattr(self, '_clock', None)
        if clk is not None:
            clk.reset()
        # GC 生命周期 (2026-09-01 流畅度批): 场景加载完成即冻结长寿命对象
        # (501 Mesh 大 list ≈ 490 万槽永久代化) + 放宽播放阈值 —— 发布玩家=
        # 常驻播放态, gen2 不再全量遍历场景 (1% low 帧尖刺本体治理).
        # 一次性代价: enter 内 collect 在加载尾 ~20-150ms@500球 (加载时刻, 可接受).
        # LOOM_GC_LEGACY=1 秒回退 (A/B 基线用).
        gc_play_enter()

    def load_scene(self, path):
        """M37 运行时切场景 (GC 批包裹): 冻结态下旧场景对象被 freeze 钉死,
        先解冻回收再冻新场景 —— 防脚本切关卡长局内存单调上涨."""
        frozen = engine_gc_frozen()
        if frozen:
            gc_play_exit()               # 解冻旧场景 + 清播放垃圾 + 阈值还原
        try:
            return super().load_scene(path)
        finally:
            if frozen:
                gc_play_enter()          # 冻结新场景 + 播放阈值 (加载失败也重冻)

    def _draw_hud(self):
        """M39: 播放器不画引擎调试 HUD (相机坐标/FPS/操作提示等 — 玩家不该看到).
        游戏自己的 UI (脚本 engine.ui.text 等, M33) 照常在 render 里画."""
        pass
