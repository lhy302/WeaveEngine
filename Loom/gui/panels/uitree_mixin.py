# -*- coding: utf-8 -*-
"""
gui/panels/uitree_mixin.py — 底部 UI 树坞（Canvas UI 可视化编辑器面板）（Q-B7-38-1 第 8 批，自 gui/main_window.py 纯搬迁）


我负责：UI 树 dock 构建、+ 元素/+ Canvas 对话框、UI 元素/Canvas 属性面板
（数值/复选/文本行 → ui_set/ui_canvas_set）、选中联动检查器。
我不负责：普通对象/光源/相机检查器（inspector_mixin）。

搬迁纪律（见 docs/guides/开发要求_功能解耦与模块化.md §3）：方法体逐字未动，
只改 def 归属与 import 头；LoomGUI 经 gui/main_window.py 的基类装配混入本类。
"""

from PySide6.QtCore import Qt

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QSpinBox,
    QWidget,
)


class UitreeMixin:
    # 混入 LoomGUI（gui/main_window.py 基类装配）；以下方法体逐字未动。

    # ---------------- UI 树 dock (2026-10-18 阶段5) ----------------
    def _build_ui_tree_dock(self):
        """底部 UI 树 dock（与命令行坞并列，默认显示）.
        2026-10-19 修复: 坞被用户点 X 关闭时同步状态栏按钮态,
        避免按钮"显示已打开"但坞已关。"""
        from ui import qt_uitree
        self.uitree = qt_uitree.UITreeDock(self)
        self.addDockWidget(Qt.DockWidgetArea.BottomDockWidgetArea, self.uitree)
        # 与 console 并排（tabify 或 split），保持两个都在底部
        try:
            self.tabifyDockWidget(self.console, self.uitree)
        except Exception:
            pass
        self.uitree.show()
        # 2026-10-19: 坞可见性 -> 按钮状态同步（对齐 console 同款）
        self.uitree.visibilityChanged.connect(
            lambda vis: self._btn_uitree.setChecked(bool(vis)))

    def _cmd_uitree(self, checked=None):
        """2026-10-19: [UI树] 按钮 / F11: 开关 UI 树坞."""
        show = not self.uitree.isVisible() if checked is None else bool(checked)
        self.uitree.setVisible(show)
        self._btn_uitree.setChecked(show)
        if show:
            self.uitree.raise_()   # 从 tab 切到前台（与 console 同款行为）
        return show

    def _ui_tree_set_selection(self, elem_name, canvas_idx):
        """UI 树选中变化 -> 检查器切到该元素属性（C3）."""
        if elem_name == self._ui_selected_name and canvas_idx == self._ui_selected_canvas:
            return
        self._ui_selected_name = elem_name
        self._ui_selected_canvas = canvas_idx
        self._insp_last_digest = None
        self._rebuild_inspector()

    def _ui_tree_add_dialog(self, canvas=0, parent=None):
        """UI 树「+ 元素」对话框."""
        import agent_commands as ac
        dlg = QDialog(self)
        dlg.setWindowTitle("添加 UI 元素")
        form = QFormLayout(dlg)
        type_combo = QComboBox()
        type_combo.addItems(list(ac._UI_TYPE_NAMES))
        form.addRow("类型:", type_combo)
        name_edit = QLineEdit('')
        name_edit.setPlaceholderText("(自动生成)")
        form.addRow("名字:", name_edit)
        x_spin = QSpinBox(); x_spin.setRange(-10000, 10000); x_spin.setValue(0)
        y_spin = QSpinBox(); y_spin.setRange(-10000, 10000); y_spin.setValue(0)
        w_spin = QSpinBox(); w_spin.setRange(1, 10000); w_spin.setValue(120)
        h_spin = QSpinBox(); h_spin.setRange(1, 10000); h_spin.setValue(32)
        row_rect = QWidget()
        hr = QHBoxLayout(row_rect); hr.setContentsMargins(0,0,0,0)
        for lab, sp in (('x', x_spin), ('y', y_spin), ('w', w_spin), ('h', h_spin)):
            hr.addWidget(QLabel(lab)); hr.addWidget(sp)
        form.addRow("位置/尺寸:", row_rect)
        parent_label = QLabel(parent or "(Canvas root)")
        form.addRow("父元素:", parent_label)
        canvas_label = QLabel(str(canvas))
        form.addRow("Canvas:", canvas_label)
        btns = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok
                                | QDialogButtonBox.StandardButton.Cancel)
        btns.accepted.connect(dlg.accept)
        btns.rejected.connect(dlg.reject)
        form.addRow(btns)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        args = {
            'type': type_combo.currentText(),
            'canvas': canvas,
            'rect': (x_spin.value(), y_spin.value(),
                     w_spin.value(), h_spin.value()),
        }
        if name_edit.text().strip():
            args['name'] = name_edit.text().strip()
        if parent:
            args['parent'] = parent
        self._invoke_ui_cmd('ui_add', **args)

    def _ui_tree_add_canvas_dialog(self):
        """UI 树「+ Canvas」对话框."""
        dlg = QDialog(self)
        dlg.setWindowTitle("添加 Canvas")
        form = QFormLayout(dlg)
        type_combo = QComboBox()
        type_combo.addItems(['screen', 'world'])
        form.addRow("类型:", type_combo)
        w_spin = QSpinBox(); w_spin.setRange(1, 10000); w_spin.setValue(1280)
        h_spin = QSpinBox(); h_spin.setRange(1, 10000); h_spin.setValue(720)
        form.addRow("宽度:", w_spin)
        form.addRow("高度:", h_spin)
        z_spin = QSpinBox(); z_spin.setRange(-1000, 1000); z_spin.setValue(0)
        form.addRow("z_order:", z_spin)
        btns = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok
                                | QDialogButtonBox.StandardButton.Cancel)
        btns.accepted.connect(dlg.accept)
        btns.rejected.connect(dlg.reject)
        form.addRow(btns)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        self._invoke_ui_cmd('ui_canvas_add',
                            type=type_combo.currentText(),
                            width=w_spin.value(),
                            height=h_spin.value(),
                            z_order=z_spin.value())

    def _build_ui_inspector(self, lay, elem):
        """UI 元素检查器 (C3). 每次编辑 = 一个 ui_set 命令 = 一个撤销步骤."""
        typ = elem.ctype
        lay.addRow(QLabel("<b>%s</b>  [%s]" % (elem.name, typ)))

        # 通用字段
        lay.addRow(QLabel("位置/尺寸 (rect)"))
        for i, axis in enumerate(('X', 'Y', 'W', 'H')):
            self._ui_attr_spin(lay, axis, elem.rect[i], -10000, 10000,
                               ('rect', i), step=1, dec=0)
        lay.addRow(QLabel("锚点 (anchor)"))
        for i, axis in enumerate(('AX', 'AY')):
            self._ui_attr_spin(lay, axis, elem.anchor[i], 0, 1,
                               ('anchor', i), step=0.05, dec=2)
        lay.addRow(QLabel("轴心 (pivot)"))
        for i, axis in enumerate(('PX', 'PY')):
            self._ui_attr_spin(lay, axis, elem.pivot[i], 0, 1,
                               ('pivot', i), step=0.05, dec=2)
        self._ui_attr_check(lay, "可见", elem.visible, 'visible')
        self._ui_attr_check(lay, "启用", elem.enabled, 'enabled')
        self._ui_attr_spin(lay, "z_order", elem.z_order, -1000, 1000,
                           ('z_order',), step=1, dec=0)

        # type-specific（常用字段）
        if typ == 'button':
            self._ui_attr_line(lay, "文字", elem.text, 'text')
        elif typ == 'text':
            self._ui_attr_line(lay, "内容", elem.text, 'text')
        elif typ == 'input_field':
            self._ui_attr_line(lay, "文字", elem.text, 'text')
            self._ui_attr_line(lay, "占位", elem.placeholder, 'placeholder')
        elif typ == 'toggle':
            self._ui_attr_check(lay, "勾选", elem.is_on, 'is_on')
            self._ui_attr_line(lay, "标签", elem.label, 'label')
        elif typ == 'slider':
            self._ui_attr_spin(lay, "值", elem.value,
                               elem.min_value, elem.max_value,
                               ('value',), step=0.01, dec=3)
        elif typ == 'progress_bar':
            self._ui_attr_spin(lay, "进度", elem.value, 0, 1,
                               ('value',), step=0.01, dec=3)

        lay.addRow(QLabel(
            "(更多字段请用控制台命令: ui_set name=%s ...)" % elem.name))

    def _ui_attr_spin(self, lay, label, value, lo, hi, path,
                      step=1.0, dec=3):
        sb = QDoubleSpinBox()
        sb.setRange(lo, hi)
        sb.setDecimals(dec)
        sb.setSingleStep(step)
        sb.setValue(float(value))
        sb.editingFinished.connect(
            lambda: self._ui_apply_attr(path, sb.value()))
        lay.addRow(label, sb)

    def _ui_attr_check(self, lay, label, value, attr):
        cb = QCheckBox()
        cb.setChecked(bool(value))
        cb.stateChanged.connect(
            lambda _s: self._ui_apply_attr((attr,), bool(cb.isChecked())))
        lay.addRow(label, cb)

    def _ui_attr_line(self, lay, label, value, attr):
        le = QLineEdit(str(value))
        le.editingFinished.connect(
            lambda: self._ui_apply_attr((attr,), le.text()))
        lay.addRow(label, le)

    def _ui_apply_attr(self, path, value):
        """path 元组：('attr',) 或 ('rect', 0)。构造 ui_set payload。"""
        if self._building:
            return
        name = self._ui_selected_name
        canvas = self._ui_selected_canvas
        if name is None or canvas is None:
            return
        e = self.editor
        if not e.ui.canvases or canvas >= len(e.ui.canvases):
            return
        elem = e.ui.canvases[canvas].root.find(name)
        if elem is None:
            return
        payload = {'name': name, 'canvas': canvas}
        if len(path) == 1:
            payload[path[0]] = value
        else:
            cur = list(getattr(elem, path[0]))
            cur[path[1]] = value
            payload[path[0]] = tuple(cur)
        self._invoke_ui_cmd('ui_set', **payload)

    # ---- 2026-10-19 第1档序3阶段4: Canvas 属性面板 ----
    def _build_canvas_inspector(self, lay, canvas):
        """Canvas 属性：宽高/z_order/类型；world 模式 + world_scale/billboard/target."""
        ci = self._ui_selected_canvas
        lay.addRow(QLabel("<b>Canvas %d</b>  [%s]" % (ci, canvas.canvas_type)))
        self._canvas_spin(lay, "宽度", canvas.width, 1, 10000, 'width',
                          step=1, dec=0)
        self._canvas_spin(lay, "高度", canvas.height, 1, 10000, 'height',
                          step=1, dec=0)
        self._canvas_spin(lay, "z_order", canvas.z_order, -1000, 1000,
                          'z_order', step=1, dec=0)
        type_cb = QComboBox()
        type_cb.addItems(['screen', 'world'])
        type_cb.setCurrentText(canvas.canvas_type)
        type_cb.currentTextChanged.connect(
            lambda v: self._canvas_apply_attr('type', v))
        lay.addRow("类型", type_cb)
        if canvas.canvas_type == 'world':
            self._canvas_spin(lay, "world_scale",
                              getattr(canvas, 'world_scale', 0.01),
                              0.0001, 10.0, 'world_scale',
                              step=0.01, dec=4)
            bb = QCheckBox()
            bb.setChecked(bool(getattr(canvas, 'billboard', True)))
            bb.stateChanged.connect(
                lambda _s: self._canvas_apply_attr(
                    'billboard', bool(bb.isChecked())))
            lay.addRow("面向相机", bb)
            tgt = getattr(canvas, 'target', None)
            tgt_edit = QLineEdit(tgt.name if tgt is not None else '')
            tgt_edit.setPlaceholderText("(空=不绑定物体)")
            tgt_edit.editingFinished.connect(
                lambda: self._canvas_apply_attr('target', tgt_edit.text()))
            lay.addRow("宿主物体", tgt_edit)
        lay.addRow(QLabel(
            "(等价命令: ui_canvas_set canvas=%d ...)" % ci))

    def _canvas_spin(self, lay, label, value, lo, hi, field,
                     step=1.0, dec=3):
        sb = QDoubleSpinBox()
        sb.setRange(lo, hi)
        sb.setDecimals(dec)
        sb.setSingleStep(step)
        sb.setValue(float(value))
        sb.editingFinished.connect(
            lambda: self._canvas_apply_attr(field, sb.value()))
        lay.addRow(label, sb)

    def _canvas_apply_attr(self, field, value):
        if self._building:
            return
        ci = self._ui_selected_canvas
        if ci is None:
            return
        payload = {'canvas': ci, field: value}
        self._invoke_ui_cmd('ui_canvas_set', **payload)
