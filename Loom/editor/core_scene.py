# -*- coding: utf-8 -*-
"""editor/core_scene.py — 场景文档与快照：场景摘要、脏判定、标记已保存、保存三入口、未保存确认、新建与打开命令、相机字典、天空盒生效解析。

Q-B7-38-1 第 9 批（agent-99）：editor/core.py 按能力域拆分的**纯搬迁**产物 ——
类体成员从 editor/core.py 的 _EditorCore 逐字搬入本 mixin（方法体一行未改）；
装配见 editor/core.py 的 _EditorCore(EngineCore, <各域 mixin> ...)。

我负责：场景文档与快照：场景摘要、脏判定、标记已保存、保存三入口、未保存确认、新建与打开命令、相机字典、天空盒生效解析。
我不负责：真正落盘与对话框记忆的 _save_scene/_load_scene/choose_*（core.py：STATE_FILE/save_last_dir patch 面）。
mixin 之间只经 self 互调（装配后同一个实例），互不 import。
"""
import json
import sceneio

class EditorSceneIOMixin(object):
    """场景文档与快照：场景摘要、脏判定、标记已保存、保存三入口、未保存确认、新建与打开命令、相机字典、天空盒生效解析（纯搬迁）。"""

    def _camera_dict(self):
        """当前场景相机（写场景文件用）。

        2026-11-08 批2 (D7=A): ortho / ortho_size / fov 是**场景相机属性**，随场景
        一起保存；这里显式取值，不再依赖 sceneio 的 setdefault 兜底。
        yaw/pitch 存弧度（与 _apply_camera 读回同单位），fov 存**度**。
        """
        d = {"target": list(self.camera_target),
             "distance": self.camera_distance,
             "yaw": self.camera_yaw,
             "pitch": self.camera_pitch}
        d.update(self._camera_proj_state())
        return d

    def _effective_skybox(self):
        """Q3=A: 生效天空盒 —— **委托** GLEngine.effective_skybox()（GL/VK 同一判定）。

        2026-11-09 收尾: 优先级判定已上收到引擎（相机级优先 → 场景级），本方法只做兼容别名，
        避免编辑器/渲染端各写一套（那正是 Q3 要消灭的分叉）。
        """
        fn = getattr(self, 'effective_skybox', None)
        if callable(fn):
            return fn()
        cam = self.active_camera_object()      # 极旧桩兜底
        cb = getattr(cam, 'skybox', None) if cam is not None else None
        return cb if cb is not None else getattr(self, '_scene_skybox', None)

    def _refresh_effective_skybox(self):
        """生效天空盒换了对象 -> 复位渲染端 sky 状态（02 号 reset_sky_state, 幂等）。

        为什么需要: 旧实现 `_sky_prog = False` 是永久哨兵，一次编译失败后换场景也永不重试
        （天空盒静默消失）。这里与渲染端的"对象变了自动复位"形成双保险。
        返回当前生效的 Cubemap（或 None）。
        """
        # P1-1（回归修复）: 先把**场景级**写回渲染面 engine._skybox ——
        # engine.effective_skybox() 的回落值就是 self._skybox；旧实现只返回不写回，
        # 于是 skybox_set 之后 _skybox 恒 None -> editor.render 门 / loom_render 绘制门
        # 双双早退，"设完天空盒当场不生效（要重载或新建才生效）"。
        self._skybox = getattr(self, '_scene_skybox', None)
        eff = self._effective_skybox()
        if eff is not getattr(self, '_sky_eff_last', None):
            self._sky_eff_last = eff
            rs = getattr(self, 'reset_sky_state', None)
            if callable(rs):
                rs()
            else:                              # 极旧桩兜底
                for attr in ('_sky_prog', '_sky_vao', '_sky_vbo'):
                    setattr(self, attr, None)
        return eff

    # ================ 场景改动跟踪 (2026-08-13 修复: 新建前询问是否保存) ================
    def _scene_digest(self):
        """当前场景内容摘要 (不含编辑器轨道相机) —— 判定"自上次保存/加载后有改动".
        camera 固定传 None: 编辑器转视角/移动相机不算场景内容改动.
        数值规范化: int/float 统一为 float —— render 的 m.update 会把 int 0 变成
        float 0.0, json 视为不同, 导致"没改场景却判脏" (2026-08-13 用户实测 A01)."""
        def _norm(v):
            if isinstance(v, bool):
                return v
            if isinstance(v, (int, float)):
                return float(v)
            if isinstance(v, dict):
                return {k: _norm(x) for k, x in v.items()}
            if isinstance(v, (list, tuple)):
                return [_norm(x) for x in v]
            return v
        data = sceneio.scene_to_dict(self, camera=None, base_dir=self._scene_dir())
        # 2026-11-08 批2 (D7=A): 轨道相机**视角**(target/distance/yaw/pitch) 仍属
        # 编辑器视图状态, 不计入场景内容; 但投影三件套是**场景相机属性** -> 必须进
        # 脏判定, 否则 EAI camera_proj 改完直接关窗口 = 静默丢失（P-03-05 同源）。
        data['_camera_proj'] = self._camera_proj_state()
        try:
            return json.dumps(_norm(data), ensure_ascii=False, sort_keys=True)
        except Exception:
            return repr(data)

    def mark_saved(self):
        """记录当前场景为"已保存"基线 (保存/加载/新建后调用)."""
        self._saved_digest = self._scene_digest()

    def scene_is_dirty(self):
        """当前场景相对上次保存/加载/新建有无改动 (不含编辑器相机视角)."""
        return self._scene_digest() != getattr(self, '_saved_digest', None)

    def save_scene(self):
        """工具栏"保存"按钮 (独立命令, 2026-08-13): 场景有对应文件 (_scene_path)
        直接保存到该文件 (覆盖, 不弹框); 没有对应文件 (从未保存过) 与另存为一致
        (弹保存对话框). 返回 True = 保存成功 / False = 取消或失败."""
        if self._scene_path:
            return self._save_scene(self._scene_path) is not None
        return self._save_scene() is not None   # path=None -> 弹保存对话框

    def save_scene_as(self):
        """工具栏"另存为"按钮 (独立命令, 2026-08-13): 总是弹保存对话框选位置/文件名."""
        return self._save_scene() is not None

    def save_current_scene(self):
        """防丢保存 (新建/加载/退出前调用): 有对应文件直接存, 无文件弹另存为框.
        返回 True = 已保存 (可继续); False = 取消或失败 (应中止, 不覆盖当前场景)."""
        return self.save_scene()

    # ================ 防丢统一入口 (逻辑全在 controller; UI 只发指令) ================
    def _confirm_unsaved(self):
        """新建/加载/退出共用: 场景有未保存改动时询问是否保存.
        询问框由 UI 注入 (self._confirm_callback -> 'save'|'discard'|'cancel';
        兼容旧 bool: True=save / False=discard, 无回调默认保存).
        返回 True = 可继续执行指令; False = 用户取消 (中止当前指令, 不退出).
        保存 -> 成功继续 (取消失败中止); 不保存 -> 丢弃当前工作继续;
        取消 -> 中止 (回到编辑器继续编辑, 弹框 X/Esc 视同取消).
        2026-08-22: 三态化 —— 旧两态 (bool) 下弹框右上角 X 被归为"否"→
        不保存退出 (用户实测 A01); closeEvent/加载/新建 复用本函数."""
        if not self.scene_is_dirty():
            return True
        ask = getattr(self, '_confirm_callback', None)
        choice = ask() if ask is not None else None
        if choice is None:
            choice = 'save'
        if choice is True:
            choice = 'save'
        elif choice is False:
            choice = 'discard'
        if choice == 'cancel':
            return False
        if choice == 'discard':
            return True        # 点"不保存": 丢弃当前工作, 继续执行指令
        return self.save_current_scene()   # 点"保存": 成功继续, 取消失败中止

    def new_scene_cmd(self):
        """UI 指令: 新建场景 (有未保存改动先询问是否保存)."""
        if self.is_playing:
            return
        if not self._confirm_unsaved():
            return
        self._new_scene()

    def load_scene_cmd(self):
        """UI 指令: 加载场景 (有未保存改动先询问是否保存)."""
        if self.is_playing:
            return
        if not self._confirm_unsaved():
            return
        self._load_scene()

    def _new_scene(self):
        if self.is_playing:
            return
        for m in list(self.models):
            self.remove_model(m)
        self.lights.clear()                 # M21: 新建场景无默认光源
        self.cameras.clear()                # Unity Camera: 新建场景无摄像机
        self.active_camera = None
        # 2026-10-19 P0-4: 新建场景必须清 UI/材质/天空盒（防场景互相污染）
        # 之前只清 models/lights/cameras，A 场景的 HUD/材质会漏进 B，场景隔离被破坏。
        # 清 UI 后重建一个空默认 Canvas，否则 ui_add 会因 ui.canvases 为空而报"找不到 Canvas"。
        if getattr(self, 'ui', None) is not None:
            try:
                self.ui.clear()
                from loom_ui import Canvas as _Canvas
                self.ui.add_canvas(_Canvas(
                    canvas_type='screen',
                    width=getattr(self, 'width', 1280),
                    height=getattr(self, 'height', 800),
                    z_order=0))
            except Exception:
                pass
        if getattr(self, 'materials', None):
            self.materials.clear()
        # 2026-11-09 beta5 Q1=A: 新建场景 = **默认纯色蓝天**（白盒契约;
        # 颜色单点在 sceneio.DEFAULT_SKYBOX_COLOR, 这里不写字面量）
        self._scene_skybox = sceneio.default_skybox()
        self._skybox = self._scene_skybox   # 场景级（engine 侧字段保持"场景默认"语义）
        # beta6 轮6 D-01: 新建场景 = 换场景，必须与 scene_from_dict 同口径重置资产状态。
        # 否则上一场景的 _skybox_ref（失效引用）会在保存时被 scene_to_dict 写回新场景，
        # 并把上一场景的资产问题谎报成新场景的（跨场景污染）。
        self._skybox_valid = True
        self._skybox_error = None
        self._skybox_ref = None
        sceneio.reset_asset_errors(self)
        self._sky_eff_last = None           # 强制下一次 refresh 走"变更"分支
        self._refresh_effective_skybox()    # -> reset_sky_state()（幂等）
        self.undo.clear()
        self.selected_index = 0
        self.selected_light_index = -1
        self.selected_camera_index = -1
        self.scene_name = '场景'
        self._scene_path = None
        self.camera_target = (0, 0, 0)
        self.camera_distance = 10.0
        self.camera_yaw = 0.6
        self.camera_pitch = -0.35
        # 2026-11-08 批2 (D7=A): 新空场景 = 默认透视投影; 场景相机快照清空
        self._scene_cam = None
        self._apply_camera_proj({'ortho': False,
                                 'ortho_size': sceneio.ORTHO_SIZE_DEFAULT,
                                 'fov': sceneio.FOV_DEFAULT_DEG})
        self.mark_saved()    # 新空场景视为"已保存"基线
