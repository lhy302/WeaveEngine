# -*- coding: utf-8 -*-
"""widgets.py — 编辑器自定义控件（原 ui/loom_gui.py 控件类，B4 批按类拆出）。

成员（逐行未动，只搬家）：
  AssetListWidget  资源列表（拖拽出 MIME 资产引用，拖入视口 = 放入场景）
  DraggableSpin    可聚焦回调的 QDoubleSpinBox（接入底部拖拽块）
  DragBlock        数值拖拽块（按住左右拖动调值，非滑动条；撤销协议与
                   检查器 spinbox 的 valueChanged/editingFinished 同一封装）
"""
import json

from PySide6.QtCore import Qt, QByteArray, QMimeData
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import QListWidget, QDoubleSpinBox, QWidget

from editor.viewport.event_bridge import _MIME_ASSET


class AssetListWidget(QListWidget):
    """资源列表: 拖拽出 MIME 资产引用 (拖入视口 = 放入场景)."""

    def mimeTypes(self):
        return [_MIME_ASSET]

    def mimeData(self, items):
        m = QMimeData()
        if items:
            d = items[0].data(Qt.ItemDataRole.UserRole)
            if d is not None:
                m.setData(_MIME_ASSET, QByteArray(json.dumps(
                    {'type': d[0], 'key': d[1]}).encode('utf-8')))
        return m


# =====================================================================
# 数值拖拽调节 (2026-08-22 用户需求): 选中可调数值行后在底部弹出拖拽区,
# 按住左右拖动调值 —— 不是滑动条, 是一整块区域
# =====================================================================

class DraggableSpin(QDoubleSpinBox):
    """QDoubleSpinBox 子类: 聚焦时回调 on_focus -> 视图显示底部拖拽块.
    通用性: 所有数值行经由 _spin() (视图通用函数) 创建, 本子类自动接入;
    后续新增"可拖条"数值行只需继续调用 _spin 即自动获得拖拽调节."""

    def __init__(self, key, on_focus, parent=None):
        super().__init__(parent)
        self._key = key
        self._on_focus = on_focus

    def focusInEvent(self, ev):
        super().focusInEvent(ev)
        self._on_focus(self._key)


class DragBlock(QWidget):
    """数值拖拽块: 一块区域 (非滑动条), 左键按下记起点, 左右拖动调值.
    - 灵敏度: 每像素 = step (与 spinbox 单步一致, 位置 0.1/px 等)
    - 拖动中值夹 [lo,hi] 且回写 spinbox (blockSignals 防 valueChanged 回环)
    - 撤销: mousePress 时 edit(True) 拍起点快照, release edit(False) 按差压栈
      (与 _spin 的 valueChanged/editingFinished 同一协议 -> edit_model/light/camera)
    - Qt 隐式鼠标抓取: 按住拖出块边界 move/release 仍到达本控件 (跟手)
    - 不抢焦点 (QWidget 默认 NoFocus): 拖期间聚焦仍在 spinbox, 拖块不消失"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(36)
        self.setCursor(Qt.CursorShape.SizeHorCursor)
        self.hide()
        self._target = None   # dict(label/apply/lo/hi/step/sb/edit)
        self._drag = None     # None | [start_x, start_val]

    def set_target(self, label, apply_, lo, hi, step, sb, edit, view=None):
        self._target = dict(label=label, apply=apply_, lo=lo, hi=hi, step=step,
                            sb=sb, edit=edit, view=view)
        self._drag = None
        self.show()
        self.update()

    def hide_target(self):
        self._target = None
        self._drag = None
        self.hide()

    def is_dragging(self):
        return self._drag is not None

    def mousePressEvent(self, ev):
        t = self._target
        if t is None or ev.button() != Qt.MouseButton.LeftButton:
            return super().mousePressEvent(ev)
        # 按下前强制同步一次 spinbox <- 模型 (undo/gizmo 等改值后 300ms 轮询未到,
        # spinbox 显示滞后时拖动基准会错位; 探针实测 undo 后直接拖 = 增量起点错)
        if t.get('view') is not None:
            try:
                t['view']._sync_inspector_values(force=True)
            except Exception:
                pass
        self._drag = [ev.position().x(), float(t['sb'].value())]
        t['edit'](True)            # 撤销起点快照 (与 spinbox 编辑同一协议)

    def mouseMoveEvent(self, ev):
        t = self._target
        if t is None or self._drag is None:
            return
        nv = self._drag[1] + (ev.position().x() - self._drag[0]) * t['step']
        nv = min(t['hi'], max(t['lo'], nv))
        t['apply'](nv)
        sb = t['sb']
        sb.blockSignals(True)
        sb.setValue(nv)
        sb.blockSignals(False)
        self.update()

    def mouseReleaseEvent(self, ev):
        if self._drag is not None:
            self._drag = None
            t = self._target
            if t is not None:
                t['edit'](False)   # 差值压撤销栈 (无变化则空栈)
        self.update()

    def paintEvent(self, ev):
        p = QPainter(self)
        p.fillRect(self.rect(), QColor('#242a36'))
        p.setPen(QColor('#3d4759'))
        p.drawRect(self.rect().adjusted(0, 0, -1, -1))
        t = self._target
        if t is not None:
            p.setPen(QColor('#c8cede'))
            p.drawText(self.rect().adjusted(10, 0, -100, 0),
                       Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                       "按住左右拖动: %s" % t['label'])
            p.setPen(QColor('#8fc63f'))
            p.drawText(self.rect().adjusted(self.width() - 100, 0, -10, 0),
                       Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight,
                       "%.3f" % t['sb'].value())
        p.end()
