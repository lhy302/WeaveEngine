# -*- coding: utf-8 -*-
"""editor/core_commands.py — 撤销命令桥：把编辑操作封装成 undo 命令并入栈。

Q-B7-38-1 第 9 批（agent-99）：editor/core.py 按能力域拆分的**纯搬迁**产物 ——
类体成员从 editor/core.py 的 _EditorCore 逐字搬入本 mixin（方法体一行未改）；
装配见 editor/core.py 的 _EditorCore(EngineCore, <各域 mixin> ...)。

我负责：撤销命令桥：把编辑操作封装成 undo 命令并入栈。
我不负责：场景文档读写与播放态（core_scene / core.py）；undo 命令类本体（editor/undo 包）。
mixin 之间只经 self 互调（装配后同一个实例），互不 import。
"""
from editor.undo import Command

class _CameraProjCommand(Command):
    """主相机投影（ortho / ortho_size / fov）改值命令（2026-11-08 批2, 裁决 D7=A）.

    为什么需要它: D7=A 把投影三件套定为**场景相机属性** —— 那就必须可撤销，
    否则 EAI camera_proj / 相机面板改完只能靠"手改回来"。
    命令只持有两组值（before/after），do/undo 都走引擎的同一条赋值路径，
    不复制任何归一逻辑（归一在 sceneio，赋值在 EditorApp._apply_camera_proj）。
    """

    label = "相机投影"

    def __init__(self, engine, before, after):
        self.engine = engine
        self.before = dict(before)
        self.after = dict(after)

    def do(self):
        self.engine._apply_camera_proj(self.after)

    def undo(self):
        self.engine._apply_camera_proj(self.before)

class _OrbitViewCommand(Command):
    """开发者轨道相机视角 (target/distance/yaw/pitch) 改值命令
    （Q-B7-56-1 裁定②, 2026-11-22: 命令行 camera_move/camera_look 进撤销栈）。

    与 _CameraProjCommand 同款: 只持有 before/after 两组值, do/undo 都走引擎的
    同一条赋值路径 (_apply_orbit_view), 不复制任何钳制逻辑 (钳制在 set_orbit_view)。
    视角属**编辑器视图状态**（_scene_digest 口径, 2026-11-08 批2 注）—— 不进场景
    脏判定: 撤销视角不把场景变脏, 与 camera_proj 先例（投影三件套才进脏判定）对齐。
    GUI 右键轨道/中键平移/滚轮/WASDQE 老链路不走 set_orbit_view, 不产生本命令。
    """

    label = "相机视角"

    def __init__(self, engine, before, after):
        self.engine = engine
        self.before = dict(before)
        self.after = dict(after)

    def do(self):
        self.engine._apply_orbit_view(self.after)

    def undo(self):
        self.engine._apply_orbit_view(self.before)

class EditorUndoBridgeMixin(object):
    """撤销命令桥：把编辑操作封装成 undo 命令并入栈（纯搬迁）。"""

    # ================ 撤销/重做 ================
    def _history_op(self, kind):
        """撤销/重做的公共实现. 返回 {'ok','blocked','error','label'} 供 GUI/EAI 出声.

        2026-11-08 批4 (裁决 D10=B): Agent 批次租约内 undo/redo 会被 UndoManager
        拒绝 —— 这里把拒绝原因原样带出去, 而不是像旧实现那样"静默什么都不做"。
        """
        if self.is_playing:
            return {'ok': False, 'blocked': '播放态不可撤销/重做（先停止播放）',
                    'error': None, 'label': ''}
        sel = self._selected()
        guid = sel.guid if sel is not None else None
        um = getattr(self, 'undo', None)
        if um is None:
            return {'ok': False, 'blocked': None, 'error': '编辑器没有撤销管理器',
                    'label': ''}
        fn = getattr(um, 'undo' if kind == 'undo' else 'redo', None)
        if fn is not None:
            fn()
        self._reselect(guid)
        self._clamp_light_selection()
        blocked = getattr(um, 'last_refusal', None)
        error = getattr(um, 'last_error', None)
        label = ''
        try:
            label = um.undo_label() if kind == 'undo' else um.redo_label()
        except Exception:
            label = ''
        return {'ok': not (blocked or error), 'blocked': blocked,
                'error': error, 'label': label}

    def _undo_action(self):
        return self._history_op('undo')

    def _redo_action(self):
        return self._history_op('redo')
