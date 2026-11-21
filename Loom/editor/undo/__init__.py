# -*- coding: utf-8 -*-
"""editor/undo/ — 撤销/重做包（原 1392 行 Loom/undo.py，B4 批按命令域拆分）。

成员（逐行未动，只搬家；快照与命令语义见各文件 docstring）：
  registry.py   基础设施：Command / BatchCommandError / BatchCommand /
                UndoManager（双栈 + Agent 批次租约 D10=A+B）
  cmd_object.py 物体域：snapshot / apply_snapshot / 材质快照 + State/
                AddMaterial/AddObject/DeleteObject/Duplicate/PrefabPlace/Reparent
  cmd_light.py  灯光域：light_snapshot / apply_light_snapshot + State/Add/Delete
  cmd_camera.py 相机域：camera_snapshot / apply_camera_snapshot +
                State/Add/Delete/ReparentCamera
  cmd_scene.py  场景/UI 域：ui_elem_snapshot / ui_apply_snapshot + 6 个 UI 命令

旧名兼容：Loom/undo.py 薄门面以 sys.modules 别名指向本包（与 B2 sceneio/
B3 engine/B6 scripts 先例同款），仓外 `import undo` / `from undo import X`
一行不改，读/写/monkeypatch 全部落在本包同一对象上。
"""
import time                                    # noqa: F401  旧模块命名空间对齐
from engine import Point3D                     # noqa: F401
import sceneio                                 # noqa: F401

from editor.undo.registry import (             # noqa: F401
    Command, BatchCommandError, BatchCommand, UndoManager,
)
from editor.undo.cmd_object import (           # noqa: F401
    _material_state, _apply_material_state,
    snapshot, apply_snapshot,
    StateCommand, AddMaterialCommand, AddObjectCommand, DeleteObjectCommand,
    DuplicateObjectCommand, PrefabPlaceCommand, ReparentCommand,
)
from editor.undo.cmd_light import (            # noqa: F401
    light_snapshot, apply_light_snapshot,
    LightStateCommand, AddLightCommand, DeleteLightCommand,
)
from editor.undo.cmd_camera import (           # noqa: F401
    camera_snapshot, apply_camera_snapshot,
    CameraStateCommand, AddCameraCommand, DeleteCameraCommand,
    ReparentCameraCommand,
)
from editor.undo.cmd_scene import (            # noqa: F401
    ui_elem_snapshot, ui_apply_snapshot, _ui_add_at, _ui_detach,
    UIStateCommand, UIAddCommand, UIRemoveCommand, UIReparentCommand,
    UIMoveChildCommand, UIAddCanvasCommand,
)
