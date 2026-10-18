# -*- coding: utf-8 -*-
"""
ui/qt_uitree.py — Loom 编辑器 UI 树编辑器 dock (2026-10-18 阶段5)
============================================================================
CanvasUI 契约 §七 阶段5 GUI 编辑器面板。

设计（决策 B4 + 命令壳）：
  - 树形展示所有 Canvas 与 UI 元素（可折叠、可选中）
  - 右键菜单：添加/删除/复制等价命令
  - 拖拽：OnItem -> ui_reparent，Above/Below -> ui_move_child（同父）
  - 选中元素时通知 LoomGUI -> 右侧检查器显示 UI 属性（C3）
  - 每次操作后命令日志留下等价 EAI 命令（教学用）
  - 所有实际修改走 LoomGUI._invoke_ui_cmd -> EAI 命令 -> undo 栈
"""
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QFont, QBrush, QColor
from PySide6.QtWidgets import (
    QDockWidget, QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPlainTextEdit, QPushButton, QTreeWidget, QTreeWidgetItem,
    QAbstractItemView, QMenu,
)


_TYPE_PREFIX = {
    'element': '·', 'panel': '□', 'text': 'T', 'image': '▤',
    'button': '⊞', 'slider': '▬', 'toggle': '☑', 'progress_bar': '▮',
    'scroll_view': '⇕', 'input_field': '⎕', 'dropdown': '▼',
    'grid_layout': '▦',
}


def _notify_win(win, msg, color=(220, 222, 228)):
    """代理到 EditorApp._notify（LoomGUI 本身无 _notify）."""
    e = getattr(win, 'editor', None)
    if e is not None:
        try:
            e._notify(msg, color)
        except Exception:
            pass


class UITreeWidget(QTreeWidget):
    """支持拖拽的 UI 树（drop 时走 EAI 命令，不调 super 防双次移动）."""

    def __init__(self, win):
        super().__init__()
        self.win = win
        self.setHeaderHidden(True)
        self.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.setDragEnabled(True)
        self.setAcceptDrops(True)
        self.setDropIndicatorShown(True)
        self.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self._on_menu)
        self.itemSelectionChanged.connect(self._on_sel)

    def _item_data(self, item):
        if item is None:
            return None
        return item.data(0, Qt.ItemDataRole.UserRole)

    def _on_sel(self):
        data = self._item_data(self.currentItem())
        if data is None:
            self.win._ui_tree_set_selection(None, None)
        elif data[0] == 'elem':
            self.win._ui_tree_set_selection(data[2], data[1])
        elif data[0] == 'canvas':
            self.win._ui_tree_set_selection(None, data[1])

    def _on_menu(self, pos):
        item = self.itemAt(pos)
        data = self._item_data(item)
        menu = QMenu(self)
        if data is not None and data[0] == 'elem':
            menu.addAction("+ 在此添加子元素", self._menu_add_under)
            menu.addAction("- 删除此元素", self._menu_delete)
            menu.addSeparator()
            menu.addAction("复制等价命令到剪贴板", self._menu_copy_cmd)
        elif data is not None and data[0] == 'canvas':
            menu.addAction("+ 在此 Canvas 根添加元素", self._menu_add_under)
        else:
            menu.addAction("+ 添加 Canvas", self._menu_add_canvas)
        if not menu.isEmpty():
            menu.exec(self.viewport().mapToGlobal(pos))

    def _menu_add_under(self):
        data = self._item_data(self.currentItem())
        if data is None:
            return
        parent = None
        canvas = 0
        if data[0] == 'elem':
            parent, canvas = data[2], data[1]
        elif data[0] == 'canvas':
            canvas = data[1]
        self.win._ui_tree_add_dialog(canvas=canvas, parent=parent)

    def _menu_delete(self):
        data = self._item_data(self.currentItem())
        if data is None or data[0] != 'elem':
            return
        self.win._invoke_ui_cmd('ui_remove', name=data[2], canvas=data[1])

    def _menu_add_canvas(self):
        self.win._ui_tree_add_canvas_dialog()

    def _menu_copy_cmd(self):
        data = self._item_data(self.currentItem())
        if data is None or data[0] != 'elem':
            return
        from PySide6.QtWidgets import QApplication
        cmd = "ui_list canvas=%d" % data[1]
        QApplication.clipboard().setText(cmd)
        _notify_win(self.win, "已复制: %s" % cmd)

    def dropEvent(self, ev):
        src = self.currentItem()
        try:
            pt = ev.position().toPoint()
        except Exception:
            pt = None
        tgt = self.itemAt(pt) if pt is not None else None
        src_d = self._item_data(src)
        tgt_d = self._item_data(tgt)
        if src_d is None or tgt_d is None or src_d[0] != 'elem':
            ev.ignore()
            return
        if src_d[1] != tgt_d[1]:
            _notify_win(self.win, "不支持跨 Canvas 拖拽", (235, 90, 90))
            ev.ignore()
            return
        canvas = src_d[1]
        src_name = src_d[2]
        pos = self.dropIndicatorPosition()
        try:
            if pos == QAbstractItemView.DropIndicatorPosition.OnItem:
                if tgt_d[0] != 'elem':
                    ev.ignore()
                    return
                self.win._invoke_ui_cmd('ui_reparent', name=src_name,
                                        new_parent=tgt_d[2], canvas=canvas)
                ev.accept()
            elif pos in (QAbstractItemView.DropIndicatorPosition.AboveItem,
                         QAbstractItemView.DropIndicatorPosition.BelowItem):
                if tgt_d[0] != 'elem':
                    ev.ignore()
                    return
                if src.parent() is not tgt.parent():
                    _notify_win(self.win, "拖到不同父元素请用「OnItem」模式",
                                (235, 90, 90))
                    ev.ignore()
                    return
                idx = tgt.parent().indexOfChild(tgt)
                if pos == QAbstractItemView.DropIndicatorPosition.BelowItem:
                    idx += 1
                if src.parent().indexOfChild(src) < idx:
                    idx -= 1
                self.win._invoke_ui_cmd('ui_move_child', name=src_name,
                                        to_index=idx, canvas=canvas)
                ev.accept()
            else:
                ev.ignore()
        except Exception as e:
            _notify_win(self.win, "拖拽失败: %r" % e, (235, 90, 90))
            ev.ignore()


class UITreeDock(QDockWidget):
    """编辑器底部 UI 树 dock."""

    def __init__(self, win):
        super().__init__("UI 树（CanvasUI）", win)
        self.win = win
        self.setAllowedAreas(Qt.DockWidgetArea.BottomDockWidgetArea |
                             Qt.DockWidgetArea.TopDockWidgetArea)

        body = QWidget()
        v = QVBoxLayout(body)
        v.setContentsMargins(4, 4, 4, 4)
        v.setSpacing(2)

        bar = QHBoxLayout()
        btn_canvas = QPushButton("+ Canvas")
        btn_canvas.clicked.connect(self._on_add_canvas)
        bar.addWidget(btn_canvas)
        btn_elem = QPushButton("+ 元素")
        btn_elem.clicked.connect(self._on_add_elem)
        bar.addWidget(btn_elem)
        btn_del = QPushButton("- 删除")
        btn_del.clicked.connect(self._on_delete)
        bar.addWidget(btn_del)
        bar.addStretch(1)
        hint = QLabel("（每次操作下方留下等价 EAI 命令，可复制执行）")
        hint.setStyleSheet("color:#888;")
        bar.addWidget(hint)
        v.addLayout(bar)

        self.tree = UITreeWidget(win)
        v.addWidget(self.tree, 3)

        self.cmd_log = QPlainTextEdit()
        self.cmd_log.setReadOnly(True)
        self.cmd_log.setFont(QFont("Consolas", 9))
        self.cmd_log.setMaximumBlockCount(200)
        self.cmd_log.setMaximumHeight(80)
        v.addWidget(self.cmd_log, 1)

        self.setWidget(body)
        self.resize(self.width(), 260)

        self._expanded = set()
        self._last_digest = None

        self._refresh_timer = QTimer(self)
        self._refresh_timer.timeout.connect(self.refresh_if_changed)
        self._refresh_timer.start(500)

    def refresh_if_changed(self):
        e = getattr(self.win, 'editor', None)
        if e is None:
            return
        ui = getattr(e, 'ui', None)
        if ui is None:
            return
        dig = self._compute_digest(ui)
        if dig != self._last_digest:
            self._last_digest = dig
            self.refresh()

    def _compute_digest(self, ui):
        parts = []
        for c in ui.canvases:
            parts.append(c.canvas_type)
            for elem in c.root.walk():
                parts.append('%s:%s:%r:%r:%r' % (
                    elem.ctype, elem.name, elem.rect, elem.anchor, elem.pivot))
        return '\n'.join(parts)

    def refresh(self):
        e = getattr(self.win, 'editor', None)
        if e is None:
            return
        ui = getattr(e, 'ui', None)
        if ui is None:
            return

        cur = self.tree.currentItem()
        cur_data = (cur.data(0, Qt.ItemDataRole.UserRole)
                    if cur is not None else None)

        self._collect_expanded_state()

        self.tree.blockSignals(True)
        self.tree.clear()
        try:
            for ci, canvas in enumerate(ui.canvases):
                cnode = QTreeWidgetItem([
                    "Canvas %d [%s %dx%d]" % (
                        ci, canvas.canvas_type, canvas.width, canvas.height)])
                cnode.setData(0, Qt.ItemDataRole.UserRole, ('canvas', ci))
                cnode.setForeground(0, QBrush(QColor('#888888')))
                self.tree.addTopLevelItem(cnode)
                cnode.setExpanded(True)
                self._add_children(cnode, canvas.root, ci, '')
        finally:
            self.tree.blockSignals(False)

        if cur_data is not None:
            for it in self._walk_items():
                if it.data(0, Qt.ItemDataRole.UserRole) == cur_data:
                    self.tree.setCurrentItem(it)
                    break

    def _add_children(self, parent_item, elem, canvas_idx, path):
        for child in elem.children:
            cp = path + '/' + child.name
            mark = '√' if child.visible else '×'
            dis = '' if child.enabled else ' (禁用)'
            prefix = _TYPE_PREFIX.get(child.ctype, '?')
            node = QTreeWidgetItem([
                "%s %s %s%s" % (mark, prefix, child.name, dis)])
            node.setData(0, Qt.ItemDataRole.UserRole,
                         ('elem', canvas_idx, child.name))
            parent_item.addChild(node)
            if (canvas_idx, cp) in self._expanded:
                node.setExpanded(True)
            self._add_children(node, child, canvas_idx, cp)

    def _collect_expanded_state(self):
        new_exp = set()
        for it in self._walk_items():
            d = it.data(0, Qt.ItemDataRole.UserRole)
            if d is None or d[0] != 'elem':
                continue
            if not it.isExpanded():
                continue
            new_exp.add((d[1], self._item_path(it)))
        self._expanded = new_exp

    def _item_path(self, item):
        parts = []
        cur = item
        while cur is not None:
            d = cur.data(0, Qt.ItemDataRole.UserRole)
            if d is None:
                break
            if d[0] == 'elem':
                parts.append(d[2])
            cur = cur.parent()
        return '/' + '/'.join(reversed(parts))

    def _walk_items(self, parent=None):
        if parent is None:
            for i in range(self.tree.topLevelItemCount()):
                yield from self._walk_items(self.tree.topLevelItem(i))
        else:
            yield parent
            for i in range(parent.childCount()):
                yield from self._walk_items(parent.child(i))

    def log_cmd(self, cmd_name, args):
        import time
        arg_str = ' '.join('%s=%r' % (k, v)
                           for k, v in args.items() if v is not None)
        self.cmd_log.appendPlainText(
            "[%s] %s %s" % (time.strftime('%H:%M:%S'), cmd_name, arg_str))

    # ---- 按钮事件 ----
    def _on_add_canvas(self):
        self.win._ui_tree_add_canvas_dialog()

    def _on_add_elem(self):
        cur = self.tree.currentItem()
        data = (cur.data(0, Qt.ItemDataRole.UserRole)
                if cur is not None else None)
        canvas = 0
        parent = None
        if data is not None:
            if data[0] == 'elem':
                parent, canvas = data[2], data[1]
            elif data[0] == 'canvas':
                canvas = data[1]
        self.win._ui_tree_add_dialog(canvas=canvas, parent=parent)

    def _on_delete(self):
        cur = self.tree.currentItem()
        data = (cur.data(0, Qt.ItemDataRole.UserRole)
                if cur is not None else None)
        if data is None or data[0] != 'elem':
            return
        self.win._invoke_ui_cmd('ui_remove', name=data[2], canvas=data[1])
